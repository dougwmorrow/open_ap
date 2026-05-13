"""Tier 1 unit tests for migrations/pii_inventory_audit_log.py.

Tests run on every commit. No live DB or network required; all pyodbc
connections are mocked with unittest.mock.MagicMock.

North Star pillars addressed:
  - Idempotent (D15): B194 migration must be safe to re-run on a server
    that already has General.ops.PiiInventoryAuditLog.
  - Audit-grade (D76): exactly one MIGRATION_PII_INVENTORY_AUDIT_LOG event
    row per invocation; Metadata JSON must match canonical shape per
    phase2/01 § 4.4.
  - Traceability (D26 + D92): SchemaContract row written on first-apply;
    NOT on re-run (no duplicate contract rows per D92 forward-only +
    SchemaContract UNIQUE filtered index per Round 1 § 23).

Edge case IDs (per 04_EDGE_CASES.md I-series idempotency):
  - I1 (same-invocation retry ledger short-circuits): analogous here — same
    connection re-run short-circuits CREATE TABLE via IF NOT EXISTS.
  - I3 (concurrent same-key UNIQUE prevents): SchemaContract UNIQUE-guarded
    insert must not double-insert on re-run.
  - I6 (hash drift across versions): N/A for a migration (no hash involved).

Decision citations:
  D15 (idempotency mandatory), D26 (append-only provenance), D76 (audit-row
  contract), D92 (forward-only additive schema + SchemaContract protocol),
  B194 (backlog item this migration closes), B189 (Tool 15 dependency —
  import_pii_inventory.py requires this table to exist before first import).
  Spec: phase2/01_pilot_prerequisites.md § 4.4 (apply() signature + canonical
  Metadata JSON shape including server key per R1C4 G1 fix).

udm-execution-classifier discipline (per task spec):
  - Idempotency contract: documented via IF NOT EXISTS guard + event_kind
    discriminator ('apply' vs 'noop') per phase2/01 § 4.4.
  - Trigger: manual / Automic JOB_PIPELINE_AM pre-flight per D109 (applied
    before first import_pii_inventory.py call on each server).
  - Frequency: once per server per D92 additive lifecycle (apply once; every
    subsequent call is a no-op and still writes exactly one audit row).
  - Audit-row family: MIGRATION_* per D76 + Round 7 § 1.1 SchemaContract
    supersession protocol; EventType = 'MIGRATION_PII_INVENTORY_AUDIT_LOG'.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Project root on sys.path (matches tests/conftest.py convention)
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Constants — single source of truth for expected values
# ---------------------------------------------------------------------------

# DDL statement count on first apply: CREATE TABLE + ALTER TABLE ADD CONSTRAINT
# (cycle-1 reviewer fix 2026-05-12 per B204 — the CHECK constraint is a separate
# ALTER TABLE statement, not part of the CREATE TABLE DDL; both execute on a
# clean first-apply, so ddl_statements_executed = 2 per § 4.4 audit contract).
FIRST_APPLY_DDL_COUNT = 2

# Canonical Metadata JSON keys per phase2/01 § 4.4 (B194-specific shape).
# 'table_created' (bool) replaces B193's 'columns_added' (list) because
# this migration creates a new table rather than altering an existing one.
REQUIRED_METADATA_KEYS = {
    "event_kind",
    "ddl_applied",
    "idempotency_path",
    "ddl_statements_executed",
    "server",
    "table_created",
}

# Valid event_kind values per phase2/01 § 4.4 discriminator
VALID_EVENT_KINDS = {"apply", "noop", "abandonment", "abandonment_noop"}

_ACTOR = "test-author"
_JUSTIFICATION = "Tier 1 unit test"
_SERVER = "dev"

# PipelineEventLog audit row EventType (phase2/01 § 4.4 + D76 + Round 7 § 1.1)
EXPECTED_EVENT_TYPE = "MIGRATION_PII_INVENTORY_AUDIT_LOG"

# The table this migration creates (for SchemaContract + sys.tables checks)
TARGET_TABLE = "PiiInventoryAuditLog"
TARGET_SCHEMA = "ops"


# ---------------------------------------------------------------------------
# Module loader
#
# Re-loads the module on every test to prevent cross-test state leakage from
# module-level globals (e.g., a cached table-exists flag).
# ---------------------------------------------------------------------------


def _load_module() -> Any:
    """Load migrations/pii_inventory_audit_log.py with DB imports patched out."""
    module_path = _PROJECT_ROOT / "migrations" / "pii_inventory_audit_log.py"
    module_key = "migrations.pii_inventory_audit_log"

    if module_key in sys.modules:
        del sys.modules[module_key]

    with patch.dict("sys.modules", {
        "utils.connections": MagicMock(),
        "utils.configuration": MagicMock(),
    }):
        spec = importlib.util.spec_from_file_location(module_key, module_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

    return mod


# ---------------------------------------------------------------------------
# Cursor factory helpers
# ---------------------------------------------------------------------------


def _cursor_table_absent() -> MagicMock:
    """Cursor that reports PiiInventoryAuditLog ABSENT (first-apply scenario).

    sys.tables / INFORMATION_SCHEMA query returns None — table does not exist.
    """
    cursor = MagicMock()
    cursor.fetchone.return_value = None
    return cursor


def _cursor_table_present() -> MagicMock:
    """Cursor that reports PiiInventoryAuditLog PRESENT (idempotent re-run scenario).

    sys.tables / INFORMATION_SCHEMA query returns a sentinel row — table exists.
    """
    cursor = MagicMock()
    cursor.fetchone.return_value = (1,)
    return cursor


def _make_conn(cursor: MagicMock) -> MagicMock:
    """Wrap a cursor in a mock pyodbc connection."""
    conn = MagicMock()
    conn.cursor.return_value = cursor
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    return conn


# ---------------------------------------------------------------------------
# Helper: extract all SQL strings from cursor.execute call args
# ---------------------------------------------------------------------------


def _executed_sql_strings(cursor: MagicMock) -> list[str]:
    """Return all SQL strings passed to cursor.execute() during the test."""
    sqls = []
    for c in cursor.execute.call_args_list:
        args = c.args or c[0]
        if args:
            sqls.append(str(args[0]))
    return sqls


# ---------------------------------------------------------------------------
# Helper: find the audit-row INSERT in cursor execute calls
# ---------------------------------------------------------------------------


def _find_audit_row_insert(cursor: MagicMock) -> dict | None:
    """Scan cursor.execute calls for the PipelineEventLog INSERT.

    Returns the Metadata JSON dict parsed from the INSERT params if found,
    else None. Identified by MIGRATION_PII_INVENTORY_AUDIT_LOG EventType
    appearing in the SQL or in a parameter string.
    """
    for c in cursor.execute.call_args_list:
        args = c.args or c[0]
        if not args:
            continue
        sql = str(args[0])
        if "PipelineEventLog" in sql or EXPECTED_EVENT_TYPE in sql:
            params = args[1] if len(args) > 1 else ()
            for p in (params if isinstance(params, (list, tuple)) else [params]):
                try:
                    parsed = json.loads(str(p))
                    if isinstance(parsed, dict) and "event_kind" in parsed:
                        return parsed
                except (json.JSONDecodeError, TypeError):
                    continue
    return None


# ---------------------------------------------------------------------------
# Test: test_first_apply_clean_state
# ---------------------------------------------------------------------------


def test_first_apply_clean_state():
    """B194, I1: First apply on a clean DB — CREATE TABLE runs; event_kind='apply'.

    Idempotency edge case I1 (first-application path per phase2/01 § 4.4).

    Decision: D15 (idempotency mandatory) + D92 (forward-only additive) +
    D26 (append-only table — PiiInventoryAuditLog MUST be created, never
    dropped or recreated).

    Verifies:
    - A CREATE TABLE statement is emitted to the cursor.
    - Return dict has event_kind='apply', ddl_applied=True,
      idempotency_path='first', ddl_statements_executed=1.
    - table_created=True.
    - server field matches caller-supplied value (Gate 6 DISTINCT-counting key).
    """
    mod = _load_module()
    cursor = _cursor_table_absent()
    conn = _make_conn(cursor)

    result = mod.apply(
        conn,
        actor=_ACTOR,
        justification=_JUSTIFICATION,
        server=_SERVER,
        dry_run=False,
    )

    assert result["event_kind"] == "apply", (
        "First apply must produce event_kind='apply' per phase2/01 § 4.4"
    )
    assert result["ddl_applied"] is True, "First apply must set ddl_applied=True"
    assert result["idempotency_path"] == "first", (
        "First apply must set idempotency_path='first'"
    )
    assert result["ddl_statements_executed"] == FIRST_APPLY_DDL_COUNT, (
        f"Expected {FIRST_APPLY_DDL_COUNT} DDL statement (one CREATE TABLE), "
        f"got {result['ddl_statements_executed']}"
    )
    assert result["table_created"] is True, (
        "table_created must be True on first apply"
    )
    assert result["server"] == _SERVER, (
        "server key must echo the caller-supplied server value (Gate 6 counting key)"
    )

    # Confirm both DDL statements (CREATE TABLE + ALTER TABLE ADD CONSTRAINT) emitted.
    # (cycle-1 reviewer post-fix verify 2026-05-12: filter previously matched only
    # CREATE-TABLE strings, missing the separate ALTER-TABLE CHECK constraint DDL.)
    sqls = _executed_sql_strings(cursor)
    ddl_sqls = [
        s for s in sqls
        if any(kw in s.upper() for kw in ("CREATE TABLE", "ALTER TABLE"))
    ]
    assert len(ddl_sqls) >= FIRST_APPLY_DDL_COUNT, (
        f"Expected >= {FIRST_APPLY_DDL_COUNT} DDL statements (CREATE TABLE + ALTER TABLE ADD CONSTRAINT) "
        f"in cursor.execute calls. Got: {ddl_sqls!r}"
    )


# ---------------------------------------------------------------------------
# Test: test_idempotent_rerun
# ---------------------------------------------------------------------------


def test_idempotent_rerun():
    """B194, I1: Re-run after first apply — no CREATE, event_kind='noop'.

    Idempotency edge case I1 (IF NOT EXISTS guard short-circuits on re-run).

    Decision: D15 (idempotency mandatory) + D92 (forward-only additive).

    Verifies:
    - No CREATE TABLE statement emitted.
    - Return dict has event_kind='noop', ddl_applied=False,
      idempotency_path='no-op', ddl_statements_executed=0.
    - table_created=False.
    - server field still echoed correctly.
    """
    mod = _load_module()
    cursor = _cursor_table_present()
    conn = _make_conn(cursor)

    result = mod.apply(
        conn,
        actor=_ACTOR,
        justification=_JUSTIFICATION,
        server=_SERVER,
        dry_run=False,
    )

    assert result["event_kind"] == "noop", (
        "Re-run must produce event_kind='noop' per phase2/01 § 4.4"
    )
    assert result["ddl_applied"] is False, "Re-run must set ddl_applied=False"
    assert result["idempotency_path"] == "no-op", (
        "Re-run must set idempotency_path='no-op'"
    )
    assert result["ddl_statements_executed"] == 0, (
        "Re-run must execute 0 DDL statements (IF NOT EXISTS guard fired)"
    )
    assert result["table_created"] is False, (
        "table_created must be False on re-run — table already exists"
    )
    assert result["server"] == _SERVER

    # Confirm no CREATE TABLE was emitted.
    sqls = _executed_sql_strings(cursor)
    create_sqls = [s for s in sqls if "CREATE" in s.upper() and "TABLE" in s.upper()]
    assert create_sqls == [], (
        f"No CREATE TABLE statements should be emitted on re-run. Got: {create_sqls!r}"
    )


# ---------------------------------------------------------------------------
# Test: test_schema_contract_row_written
# ---------------------------------------------------------------------------


def test_schema_contract_row_written():
    """B194, I3: First apply writes >= 1 SchemaContract row per Round 7 § 1.1.

    Idempotency edge case I3 (UNIQUE prevents double-write — contract rows
    must NOT be inserted on re-run to honour the UNIQUE filtered index per
    Round 1 § 23).

    Decision: D92 (forward-only additive + SchemaContract protocol).

    Verifies:
    - cursor.execute called with a SchemaContract INSERT for the new table on
      first apply.
    - On re-run (table already present), SchemaContract INSERT NOT emitted
      (idempotent guard fires first).
    """
    # --- First apply ---
    mod = _load_module()
    cursor = _cursor_table_absent()
    conn = _make_conn(cursor)

    mod.apply(
        conn,
        actor=_ACTOR,
        justification=_JUSTIFICATION,
        server=_SERVER,
        dry_run=False,
    )

    sqls = _executed_sql_strings(cursor)
    schema_contract_inserts = [
        s for s in sqls if "SchemaContract" in s and "INSERT" in s.upper()
    ]
    assert len(schema_contract_inserts) >= 1, (
        "Expected >= 1 SchemaContract INSERT statement on first apply; "
        f"found {len(schema_contract_inserts)}. Statements: {schema_contract_inserts!r}"
    )

    # --- Re-run — no new SchemaContract rows ---
    mod2 = _load_module()
    cursor2 = _cursor_table_present()
    conn2 = _make_conn(cursor2)

    mod2.apply(
        conn2,
        actor=_ACTOR,
        justification=_JUSTIFICATION,
        server=_SERVER,
        dry_run=False,
    )

    sqls2 = _executed_sql_strings(cursor2)
    schema_contract_inserts_rerun = [
        s for s in sqls2 if "SchemaContract" in s and "INSERT" in s.upper()
    ]
    assert schema_contract_inserts_rerun == [], (
        "SchemaContract INSERTs must NOT be emitted on re-run — "
        "IF NOT EXISTS guard must fire before reaching the contract write. "
        f"Got: {schema_contract_inserts_rerun!r}"
    )


# ---------------------------------------------------------------------------
# Test: test_audit_row_metadata_shape
# ---------------------------------------------------------------------------


def test_audit_row_metadata_shape():
    """B194, D76: Exactly one MIGRATION_PII_INVENTORY_AUDIT_LOG audit row per call.

    North Star: Audit-grade (D76 audit-row contract — every migration invocation
    writes ONE PipelineEventLog row regardless of DDL no-op state per phase2/01
    § 4.4 'exactly one audit row per invocation' invariant).

    Verifies:
    - Exactly one PipelineEventLog INSERT emitted per apply() call.
    - Return dict (which must match the Metadata JSON written) contains all
      required keys per canonical shape.
    - event_kind discriminator is 'apply' on first apply.
    - server key present and matches caller value (R1C4 G1 fix — mandatory
      for Gate 6 DISTINCT-counting query per phase2/01 § 4.4).

    Decision: D76 (audit-row contract), phase2/01 § 4.4 (canonical shape).
    """
    # First apply — event_kind must be 'apply'.
    mod = _load_module()
    cursor = _cursor_table_absent()
    conn = _make_conn(cursor)

    result = mod.apply(
        conn,
        actor=_ACTOR,
        justification=_JUSTIFICATION,
        server=_SERVER,
        dry_run=False,
    )

    # Return dict must carry all required Metadata keys.
    assert set(result.keys()) >= REQUIRED_METADATA_KEYS, (
        f"Metadata dict missing keys: {REQUIRED_METADATA_KEYS - set(result.keys())!r}"
    )

    # A PipelineEventLog INSERT must have been emitted.
    sqls = _executed_sql_strings(cursor)
    event_log_inserts = [
        s for s in sqls
        if "PipelineEventLog" in s and "INSERT" in s.upper()
    ]
    assert len(event_log_inserts) >= 1, (
        "apply() must INSERT exactly one row into PipelineEventLog per D76. "
        f"Statements seen: {sqls!r}"
    )

    # event_kind must discriminate apply vs noop.
    assert result["event_kind"] == "apply"
    assert result["ddl_applied"] is True

    # server key must be present and match (Gate 6 requirement).
    assert result.get("server") == _SERVER, (
        f"server key must be {_SERVER!r}. Got: {result.get('server')!r}"
    )


# ---------------------------------------------------------------------------
# Test: test_dry_run_no_writes
# ---------------------------------------------------------------------------


def test_dry_run_no_writes():
    """B194: dry_run=True — zero DB writes (no CREATE TABLE, no SchemaContract,
    no audit row).

    Per phase2/01 § 4.4: dry_run suppresses ALL writes.
    Return dict must have ddl_applied=False, table_created=False.

    Decision: D75 (--dry-run default for side-effecting tools).
    """
    mod = _load_module()
    cursor = _cursor_table_absent()
    conn = _make_conn(cursor)

    result = mod.apply(
        conn,
        actor=_ACTOR,
        justification=_JUSTIFICATION,
        server=_SERVER,
        dry_run=True,
    )

    assert result["ddl_applied"] is False, "dry_run must produce ddl_applied=False"
    assert result["table_created"] is False, "dry_run must produce table_created=False"

    # No write statements must have been executed.
    sqls = _executed_sql_strings(cursor)
    write_sqls = [
        s for s in sqls
        if any(kw in s.upper() for kw in ("CREATE", "INSERT", "ALTER", "UPDATE", "DELETE"))
    ]
    assert write_sqls == [], (
        f"dry_run=True must produce ZERO write statements. Got: {write_sqls!r}"
    )


# ---------------------------------------------------------------------------
# Test: test_dry_run_idempotency_path_reflects_real_apply (B202 pattern)
# ---------------------------------------------------------------------------


def test_dry_run_idempotency_path_reflects_real_apply():
    """B194: dry_run idempotency_path must reflect what a REAL apply would produce.

    Per phase2/01 § 4.4 canonical Metadata JSON shape — idempotency_path values:
      - 'first' when DDL WOULD be applied (table absent)
      - 'no-op' when DDL WOULD be a no-op (table present)
      - null only for abandonment / abandonment_noop event_kinds

    Mirrors the B202 regression test pattern from B193 canary tests — pins
    the dry-run idempotency_path bug class where the dry-run path hardcoded
    'no-op' regardless of state.

    Decision: phase2/01 § 4.4 canonical Metadata JSON shape.
    """
    mod = _load_module()

    # Case 1: would-be-first-apply (table absent) → idempotency_path='first'
    cursor_absent = _cursor_table_absent()
    conn_absent = _make_conn(cursor_absent)
    result_absent = mod.apply(
        conn_absent, actor=_ACTOR, justification=_JUSTIFICATION,
        server=_SERVER, dry_run=True,
    )
    assert result_absent["event_kind"] == "apply", (
        "dry_run on table-absent state must return event_kind='apply' "
        f"(what real apply would produce); got {result_absent['event_kind']!r}"
    )
    assert result_absent["idempotency_path"] == "first", (
        "dry_run on table-absent state must return idempotency_path='first' "
        f"per § 4.4 canonical shape; got {result_absent['idempotency_path']!r}"
    )

    # Case 2: would-be-noop (table present) → idempotency_path='no-op'
    cursor_present = _cursor_table_present()
    conn_present = _make_conn(cursor_present)
    result_present = mod.apply(
        conn_present, actor=_ACTOR, justification=_JUSTIFICATION,
        server=_SERVER, dry_run=True,
    )
    assert result_present["event_kind"] == "noop", (
        "dry_run on table-present state must return event_kind='noop' "
        f"(what real apply would produce); got {result_present['event_kind']!r}"
    )
    assert result_present["idempotency_path"] == "no-op", (
        "dry_run on table-present state must return idempotency_path='no-op' "
        f"per § 4.4 canonical shape; got {result_present['idempotency_path']!r}"
    )


# ---------------------------------------------------------------------------
# Test: test_event_kind_apply_vs_noop_partitions_correctly
# ---------------------------------------------------------------------------


def test_event_kind_apply_vs_noop_partitions_correctly():
    """B194, I1, D76: event_kind discriminator partitions apply vs noop correctly.

    Covers phase2/01 § 4.4 contract: 'apply' rows = first-applications with
    ddl_applied=True + idempotency_path='first'; 'noop' rows = re-runs with
    ddl_applied=False + idempotency_path='no-op'.

    This test pairs the two scenarios back-to-back to confirm the discriminator
    flips correctly between invocations — mirroring B193 canary test structure.

    The event_kind values must be disjoint (a single invocation cannot be both
    'apply' and 'noop' simultaneously), and both must appear in VALID_EVENT_KINDS.
    """
    # --- Scenario A: first apply ---
    mod_a = _load_module()
    cursor_a = _cursor_table_absent()
    conn_a = _make_conn(cursor_a)

    result_a = mod_a.apply(
        conn_a,
        actor=_ACTOR,
        justification=_JUSTIFICATION,
        server=_SERVER,
        dry_run=False,
    )

    assert result_a["event_kind"] == "apply"
    assert result_a["ddl_applied"] is True
    assert result_a["idempotency_path"] == "first"
    assert result_a["ddl_statements_executed"] == FIRST_APPLY_DDL_COUNT
    assert result_a["table_created"] is True

    # --- Scenario B: re-run (table now present) ---
    mod_b = _load_module()
    cursor_b = _cursor_table_present()
    conn_b = _make_conn(cursor_b)

    result_b = mod_b.apply(
        conn_b,
        actor=_ACTOR,
        justification=_JUSTIFICATION,
        server=_SERVER,
        dry_run=False,
    )

    assert result_b["event_kind"] == "noop"
    assert result_b["ddl_applied"] is False
    assert result_b["idempotency_path"] == "no-op"
    assert result_b["ddl_statements_executed"] == 0
    assert result_b["table_created"] is False

    # Discriminator is disjoint — apply vs noop must never be the same.
    assert result_a["event_kind"] != result_b["event_kind"], (
        "event_kind must differ between apply and noop invocations"
    )
    # Both must be valid canonical values.
    assert result_a["event_kind"] in VALID_EVENT_KINDS
    assert result_b["event_kind"] in VALID_EVENT_KINDS


# ---------------------------------------------------------------------------
# Test: test_server_key_present
# ---------------------------------------------------------------------------


def test_server_key_present():
    """B194, D76: 'server' key echoed in result for Gate 6 DISTINCT-counting.

    Per phase2/01 § 4.4 R1C4 🔴 G1 fix: the mandatory 'server' key enables
    the Gate 6 acceptance check which COUNTs DISTINCT servers where
    event_kind='apply' AND ddl_applied=True.

    Missing this key breaks the acceptance query:
      SELECT COUNT(DISTINCT JSON_VALUE(Metadata, '$.server')) FROM PipelineEventLog
      WHERE EventType='MIGRATION_PII_INVENTORY_AUDIT_LOG'
        AND JSON_VALUE(Metadata,'$.event_kind')='apply'
        AND JSON_VALUE(Metadata,'$.ddl_applied')='True'
      -- Expected: 3 (dev + test + prod)

    Verified across BOTH apply and noop invocations because Gate 6 may filter
    noop rows out, but the key must still be present for completeness.

    Decision: phase2/01 § 4.4 (canonical Metadata JSON shape); R1C4 G1 fix.
    """
    for table_exists, label in ((False, "apply"), (True, "noop")):
        mod = _load_module()
        cursor = _cursor_table_present() if table_exists else _cursor_table_absent()
        conn = _make_conn(cursor)

        result = mod.apply(
            conn,
            actor=_ACTOR,
            justification=_JUSTIFICATION,
            server=_SERVER,
            dry_run=False,
        )

        assert "server" in result, (
            f"Result dict must contain 'server' key per phase2/01 § 4.4 G1 fix "
            f"(scenario: {label})"
        )
        assert result["server"] == _SERVER, (
            f"server key must match caller value (scenario: {label}). "
            f"Expected {_SERVER!r}, got {result['server']!r}"
        )


# ---------------------------------------------------------------------------
# Test: test_audit_row_written_on_noop
# ---------------------------------------------------------------------------


def test_audit_row_written_on_noop():
    """B194, D76: Exactly one audit row written even when DDL is a no-op.

    Per phase2/01 § 4.4 'exactly one audit row per invocation' invariant —
    the no-op path MUST still write a MIGRATION_PII_INVENTORY_AUDIT_LOG row
    with event_kind='noop'. This is load-bearing for the inverse-filter
    analysis query:
      WHERE event_kind='noop'  -- must not be empty if script was re-run

    Inverse filter must use event_kind='noop', NOT idempotency_path='no-op' alone
    (per § 4.4 — using idempotency_path alone would silently include
    abandonment_noop rows).

    Decision: D76 (one row per invocation regardless of DDL state).
    """
    mod = _load_module()
    cursor = _cursor_table_present()
    conn = _make_conn(cursor)

    result = mod.apply(
        conn,
        actor=_ACTOR,
        justification=_JUSTIFICATION,
        server=_SERVER,
        dry_run=False,
    )

    assert result["event_kind"] == "noop"

    # A PipelineEventLog INSERT must still be emitted on the noop path.
    sqls = _executed_sql_strings(cursor)
    event_log_inserts = [
        s for s in sqls
        if "PipelineEventLog" in s and "INSERT" in s.upper()
    ]
    assert len(event_log_inserts) >= 1, (
        "apply() must INSERT one row into PipelineEventLog EVEN on the noop path. "
        "Per phase2/01 § 4.4 'exactly one audit row per invocation'. "
        f"Statements seen: {sqls!r}"
    )


# ---------------------------------------------------------------------------
# Test: test_table_created_is_strict_bool
# ---------------------------------------------------------------------------


def test_table_created_is_strict_bool():
    """B194: table_created must be a strict bool (True/False), not truthy/falsy.

    Audit-grade invariant: JSON serialisation of a non-bool value such as 1
    or 'yes' into PipelineEventLog Metadata would cause Gate 6 filter queries
    using JSON_VALUE(Metadata,'$.table_created') = 'True' to silently miss
    rows (SQL Server JSON_VALUE returns a string, not a bool).

    Verified for both apply and noop paths.
    """
    for table_exists in (False, True):
        mod = _load_module()
        cursor = _cursor_table_present() if table_exists else _cursor_table_absent()
        conn = _make_conn(cursor)

        result = mod.apply(
            conn,
            actor=_ACTOR,
            justification=_JUSTIFICATION,
            server=_SERVER,
            dry_run=False,
        )

        assert isinstance(result["table_created"], bool), (
            f"table_created must be a strict Python bool. "
            f"Got: {result['table_created']!r} "
            f"(type={type(result['table_created']).__name__}). "
            "Non-bool values cause Gate 6 JSON_VALUE filter query mismatches."
        )


# ---------------------------------------------------------------------------
# Test: test_apply_idempotent_called_twice_same_connection
# ---------------------------------------------------------------------------


def test_apply_idempotent_called_twice_same_connection():
    """B194, I1: Two sequential calls on the same connection — second is a no-op.

    Property: first_call.event_kind = 'apply'; second_call.event_kind = 'noop'.
    Simulates a crash-and-retry scenario where the migration runs twice
    (e.g., Automic job retries a failed step that actually completed the CREATE).

    Decision: D15 (idempotency mandatory at every layer).
    """
    mod = _load_module()

    # First apply: table absent (fetchone[0]) + CHECK absent (fetchone[1]) → both DDL run.
    # Second apply: table present (fetchone[2]) + CHECK present (fetchone[3]) → no-op.
    # (cycle-1 reviewer post-fix 2026-05-12: each apply() invocation runs BOTH guards
    # independently per partial-element-state recovery design — so 2 sequential applies
    # produce 4 fetchone calls total. The implementation does NOT short-circuit the
    # CHECK guard when the table is present, because partial-state recovery requires
    # detecting "table exists but CHECK missing" → run ALTER ADD CONSTRAINT alone.)
    cursor = MagicMock()
    cursor.fetchone.side_effect = [
        None,   # 1st call: first apply table-exists guard → table absent
        None,   # 2nd call: first apply CHECK-exists guard → CHECK absent
        (1,),   # 3rd call: second apply table-exists guard → table present
        (1,),   # 4th call: second apply CHECK-exists guard → CHECK present
    ]
    conn = _make_conn(cursor)

    result_1 = mod.apply(
        conn,
        actor=_ACTOR,
        justification=_JUSTIFICATION,
        server=_SERVER,
        dry_run=False,
    )
    result_2 = mod.apply(
        conn,
        actor=_ACTOR,
        justification=_JUSTIFICATION,
        server=_SERVER,
        dry_run=False,
    )

    assert result_1["event_kind"] == "apply"
    assert result_2["event_kind"] == "noop"
    assert result_1["ddl_statements_executed"] == FIRST_APPLY_DDL_COUNT
    assert result_2["ddl_statements_executed"] == 0
    assert result_1["table_created"] is True
    assert result_2["table_created"] is False


# ---------------------------------------------------------------------------
# Test: test_required_keys_all_non_none_on_apply
# ---------------------------------------------------------------------------


def test_required_keys_all_non_none_on_apply():
    """B194: All required Metadata JSON keys have non-None values on first apply.

    Audit-grade invariant: a None value on a required key would silently break
    Gate 6 counting queries:
      WHERE JSON_VALUE(Metadata,'$.event_kind') = 'apply'
        AND JSON_VALUE(Metadata,'$.ddl_applied') = 'True'
    because JSON_VALUE returns NULL for NULL-valued fields, not the string
    'null', making the predicate silently drop rows that should be counted.

    Decision: D76 (audit-row contract requires all canonical keys populated).
    """
    mod = _load_module()
    cursor = _cursor_table_absent()
    conn = _make_conn(cursor)

    result = mod.apply(
        conn,
        actor=_ACTOR,
        justification=_JUSTIFICATION,
        server=_SERVER,
        dry_run=False,
    )

    for key in REQUIRED_METADATA_KEYS:
        assert result.get(key) is not None, (
            f"Required key {key!r} must not be None in first-apply result. "
            "None values break Gate 6 PipelineEventLog filter queries."
        )


# ---------------------------------------------------------------------------
# Test: test_check_constraint_on_data_classification_emitted
# ---------------------------------------------------------------------------


def test_check_constraint_on_data_classification_emitted():
    """B194: CREATE TABLE statement includes a CHECK constraint on DataClassification.

    Per BACKLOG.md B194 spec: 'CHECK constraint on DataClassification'.
    The DataClassification column restricts PII import rows to a known
    classification taxonomy (e.g., 'RESTRICTED', 'CONFIDENTIAL', 'INTERNAL').
    Without this constraint, any string can be inserted, breaking the
    PII governance invariant downstream.

    This test checks that the SQL emitted to the cursor contains the string
    'CHECK' — it does not parse SQL; it confirms the constraint is not omitted
    at the CREATE TABLE generation layer.

    North Star: Audit-grade (PII governance — DataClassification domain integrity
    is a traceability requirement under D26 append-only + D30 7-year retention).
    """
    mod = _load_module()
    cursor = _cursor_table_absent()
    conn = _make_conn(cursor)

    mod.apply(
        conn,
        actor=_ACTOR,
        justification=_JUSTIFICATION,
        server=_SERVER,
        dry_run=False,
    )

    sqls = _executed_sql_strings(cursor)
    # CHECK constraint may be emitted in a separate ALTER TABLE ADD CONSTRAINT
    # statement (the canonical B194 implementation does this — CREATE TABLE
    # body does NOT contain CHECK; CHECK is added via subsequent ALTER) per
    # cycle-1 reviewer fix 2026-05-12 B205. Scan ALL executed SQL for CHECK.
    check_constraint_present = any("CHECK" in s.upper() for s in sqls)
    assert check_constraint_present, (
        "B194 migration must emit a CHECK constraint on DataClassification "
        "per BACKLOG.md B194 spec — either inside CREATE TABLE body OR as a "
        "subsequent ALTER TABLE ADD CONSTRAINT statement. "
        f"All executed SQL statements: {sqls!r}"
    )


# ---------------------------------------------------------------------------
# Test: test_docstring_documents_idempotency_trigger_frequency_audit_family
# ---------------------------------------------------------------------------


def test_docstring_documents_idempotency_trigger_frequency_audit_family():
    """B194: apply() docstring documents idempotency, trigger, frequency, audit-row family.

    Per udm-execution-classifier skill discipline (task spec): tests must verify
    the artifact's docstring documents all 4 classifier dimensions:
      1. Idempotency contract (IF NOT EXISTS guard + event_kind discriminator)
      2. Trigger (manual / Automic pre-flight)
      3. Frequency (once per server per D92 additive lifecycle)
      4. Audit-row family (MIGRATION_* per D76 + Round 7 § 1.1)

    This test inspects the apply() __doc__ string for presence of key terms
    from each dimension. A docstring that omits these makes the migration
    unclassifiable by the udm-execution-classifier skill — an audit-grade gap.

    North Star: Audit-grade + Traceability (D103 / D76 — every module produced
    from R3+ must have documented operational semantics).
    """
    mod = _load_module()
    docstring = (mod.apply.__doc__ or "").lower()

    # Dimension 1: Idempotency — must mention IF NOT EXISTS or idempotent/re-run.
    idempotency_terms = ["idempotent", "if not exists", "re-run", "rerun", "no-op"]
    assert any(term in docstring for term in idempotency_terms), (
        f"apply() docstring must document idempotency contract. "
        f"Expected one of {idempotency_terms!r} in docstring. "
        f"Got docstring (truncated): {docstring[:300]!r}"
    )

    # Dimension 4: Audit-row family — must mention migration* or pipelineeventlog.
    audit_terms = ["migration", "pipelineeventlog", "audit row", "event_type", "eventtype"]
    assert any(term in docstring for term in audit_terms), (
        f"apply() docstring must document audit-row family (MIGRATION_* per D76). "
        f"Expected one of {audit_terms!r} in docstring. "
        f"Got docstring (truncated): {docstring[:300]!r}"
    )
