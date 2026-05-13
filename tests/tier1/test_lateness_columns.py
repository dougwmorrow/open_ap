"""Tier 1 unit tests for migrations/lateness_columns.py.

Tests run on every commit.  No live DB or network required; all pyodbc
connections are mocked with unittest.mock.MagicMock.

North Star pillars addressed:
  - Idempotent (D15): B193 migrations must be safe to re-run.
  - Audit-grade (D76): exactly one MIGRATION_LATENESS_COLUMNS event row per
    invocation; Metadata JSON must match canonical shape per phase2/01 § 4.4.
  - Traceability (D92): SchemaContract rows written on first-apply; not on
    re-run (no duplicate contract rows).

Edge case IDs (per 04_EDGE_CASES.md I-series idempotency):
  - I1 (same-BatchId retry ledger short-circuits): analogous here — same
    connection re-run short-circuits DDL via IF NOT EXISTS.
  - I3 (concurrent same-key UNIQUE prevents): SchemaContract UNIQUE-guarded
    insert must not double-insert on re-run.
  - I6 (hash drift across versions): N/A for a migration (no hash involved).

Decision citations:
  D15 (idempotency mandatory), D76 (audit-row contract), D92 (forward-only
  additive schema), B193 (backlog item this migration closes), phase2/01 §
  4.4 (apply() function signature + Metadata JSON canonical shape).
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

# Columns B193 adds per BACKLOG.md L376 + phase2/01 § 4.4
COLUMNS_ADDED = ["LatenessL99Minutes", "LatenessL99UpdatedAt"]

# DDL statement count on first apply: one ALTER per column
FIRST_APPLY_DDL_COUNT = 2

# Canonical Metadata JSON keys (phase2/01 § 4.4)
REQUIRED_METADATA_KEYS = {
    "event_kind",
    "ddl_applied",
    "idempotency_path",
    "ddl_statements_executed",
    "server",
    "columns_added",
}

_ACTOR = "test-author"
_JUSTIFICATION = "Tier 1 unit test"
_SERVER = "dev"

# PipelineEventLog audit row EventType (phase2/01 § 4.4 + D76 + Round 7 § 1.1)
EXPECTED_EVENT_TYPE = "MIGRATION_LATENESS_COLUMNS"


# ---------------------------------------------------------------------------
# Fixture: mock module loader
#
# Re-loads the module on every test to prevent cross-test state leakage from
# module-level globals (e.g., a cached column-exists flag).
# ---------------------------------------------------------------------------


def _load_module() -> Any:
    """Load migrations/lateness_columns.py with DB imports patched out."""
    module_path = _PROJECT_ROOT / "migrations" / "lateness_columns.py"
    module_key = "migrations.lateness_columns"

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


def _cursor_columns_absent() -> MagicMock:
    """Cursor that reports both columns ABSENT (first-apply scenario)."""
    cursor = MagicMock()
    # fetchone() called once per column to check INFORMATION_SCHEMA
    cursor.fetchone.side_effect = [None, None]
    return cursor


def _cursor_columns_present() -> MagicMock:
    """Cursor that reports both columns PRESENT (idempotent re-run scenario)."""
    cursor = MagicMock()
    cursor.fetchone.side_effect = [(1,), (1,)]
    return cursor


def _make_conn(cursor: MagicMock) -> MagicMock:
    conn = MagicMock()
    conn.cursor.return_value = cursor
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    return conn


# ---------------------------------------------------------------------------
# Helper: extract SQL strings from cursor.execute call args
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
# Helper: find the audit-row write in cursor execute calls
# ---------------------------------------------------------------------------


def _find_audit_row_call(cursor: MagicMock) -> dict | None:
    """Scan cursor.execute calls for the PipelineEventLog INSERT.

    Returns the Metadata JSON dict if found, else None.
    The INSERT is identified by the MIGRATION_LATENESS_COLUMNS EventType.
    """
    for c in cursor.execute.call_args_list:
        args = c.args or c[0]
        if not args:
            continue
        sql = str(args[0])
        if "PipelineEventLog" in sql or EXPECTED_EVENT_TYPE in sql:
            # Second positional arg should be a tuple of parameter values.
            # The Metadata JSON is conventionally the last non-trivial param.
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
    """B193, I1: First apply on a clean DB — 2 ALTERs run, event_kind='apply'.

    Idempotency edge case I1 (first-application path).

    Decision: D15 (idempotency mandatory) + D92 (forward-only additive ALTER).

    Verifies:
    - Both ALTER statements are emitted to the cursor.
    - Return dict has event_kind='apply', ddl_applied=True,
      idempotency_path='first', ddl_statements_executed=2.
    - columns_added == COLUMNS_ADDED.
    - server field matches caller-supplied value.
    """
    mod = _load_module()
    cursor = _cursor_columns_absent()
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
        f"Expected {FIRST_APPLY_DDL_COUNT} DDL statements (one ALTER per column), "
        f"got {result['ddl_statements_executed']}"
    )
    assert sorted(result["columns_added"]) == sorted(COLUMNS_ADDED), (
        f"columns_added must list both new columns. Got: {result['columns_added']!r}"
    )
    assert result["server"] == _SERVER, (
        "server key must echo the caller-supplied server value (Gate 6 counting key)"
    )

    # Confirm ALTER statements actually emitted to DB
    sqls = _executed_sql_strings(cursor)
    alter_sqls = [s for s in sqls if "ALTER" in s.upper()]
    assert len(alter_sqls) >= FIRST_APPLY_DDL_COUNT, (
        f"Expected >= {FIRST_APPLY_DDL_COUNT} ALTER statements in cursor.execute calls. "
        f"Got: {alter_sqls!r}"
    )


# ---------------------------------------------------------------------------
# Test: test_idempotent_rerun
# ---------------------------------------------------------------------------


def test_idempotent_rerun():
    """B193, I1: Re-run after first apply — 0 ALTERs, event_kind='noop'.

    Idempotency edge case I1 (IF NOT EXISTS guard short-circuits on re-run).

    Decision: D15 (idempotency mandatory) + D92 (forward-only additive).

    Verifies:
    - No ALTER statements emitted.
    - Return dict has event_kind='noop', ddl_applied=False,
      idempotency_path='no-op', ddl_statements_executed=0.
    - columns_added == [] (nothing new).
    - server field still echoed correctly.
    """
    mod = _load_module()
    cursor = _cursor_columns_present()
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
    assert result["columns_added"] == [], (
        "Re-run must return empty columns_added"
    )
    assert result["server"] == _SERVER

    # Confirm no ALTER was emitted
    sqls = _executed_sql_strings(cursor)
    alter_sqls = [s for s in sqls if "ALTER" in s.upper()]
    assert alter_sqls == [], (
        f"No ALTER statements should be emitted on re-run. Got: {alter_sqls!r}"
    )


# ---------------------------------------------------------------------------
# Test: test_schema_contract_rows_written
# ---------------------------------------------------------------------------


def test_schema_contract_rows_written():
    """B193, I3: First apply writes >= 2 SchemaContract rows per Round 7 § 1.1.

    Idempotency edge case I3 (UNIQUE prevents double-write — contract rows
    must NOT be inserted on re-run to honour the UNIQUE filtered index per
    Round 1 § 23).

    Decision: D92 (forward-only additive + SchemaContract protocol).

    Verifies:
    - cursor.execute called with a SchemaContract INSERT for each column.
    - On re-run (columns already present), SchemaContract INSERTs are NOT
      emitted (idempotent guard fires first).
    """
    # --- First apply ---
    mod = _load_module()
    cursor = _cursor_columns_absent()
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
    assert len(schema_contract_inserts) >= len(COLUMNS_ADDED), (
        f"Expected >= {len(COLUMNS_ADDED)} SchemaContract INSERT statements on first apply, "
        f"found {len(schema_contract_inserts)}. Statements: {schema_contract_inserts!r}"
    )

    # --- Re-run — no new SchemaContract rows ---
    mod2 = _load_module()
    cursor2 = _cursor_columns_present()
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
    """B193, D76: Exactly one MIGRATION_LATENESS_COLUMNS audit row written per call.

    North Star: Audit-grade (D76 audit-row contract — every CLI/migration
    invocation writes ONE PipelineEventLog row per phase2/01 § 4.4).

    Verifies:
    - Exactly one PipelineEventLog INSERT emitted per apply() call.
    - Metadata JSON contains all required keys per canonical shape.
    - event_kind discriminator partitions correctly (apply vs noop).
    """
    # First apply — event_kind must be 'apply'
    mod = _load_module()
    cursor = _cursor_columns_absent()
    conn = _make_conn(cursor)

    result = mod.apply(
        conn,
        actor=_ACTOR,
        justification=_JUSTIFICATION,
        server=_SERVER,
        dry_run=False,
    )

    # The audit row Metadata is the return dict itself (apply() is required
    # to write this content to PipelineEventLog AND return it).
    assert set(result.keys()) >= REQUIRED_METADATA_KEYS, (
        f"Metadata dict missing keys: {REQUIRED_METADATA_KEYS - set(result.keys())!r}"
    )

    # Confirm a PipelineEventLog INSERT was emitted to cursor
    sqls = _executed_sql_strings(cursor)
    event_log_inserts = [
        s for s in sqls
        if "PipelineEventLog" in s and "INSERT" in s.upper()
    ]
    assert len(event_log_inserts) >= 1, (
        "apply() must INSERT exactly one row into PipelineEventLog per D76. "
        f"Statements seen: {sqls!r}"
    )

    # Verify event_kind discriminator
    assert result["event_kind"] == "apply"
    assert result["ddl_applied"] is True


# ---------------------------------------------------------------------------
# Test: test_dry_run_no_writes
# ---------------------------------------------------------------------------


def test_dry_run_no_writes():
    """B193: dry_run=True — zero DB writes (no DDL, no SchemaContract, no audit row).

    Per phase2/01 § 4.4: dry_run suppresses ALL writes.
    Return dict must have ddl_applied=False.

    Decision: D75 (--dry-run default for side-effecting tools).
    """
    mod = _load_module()
    cursor = _cursor_columns_absent()
    conn = _make_conn(cursor)

    result = mod.apply(
        conn,
        actor=_ACTOR,
        justification=_JUSTIFICATION,
        server=_SERVER,
        dry_run=True,
    )

    assert result["ddl_applied"] is False, "dry_run must produce ddl_applied=False"

    # No ALTER statements executed
    sqls = _executed_sql_strings(cursor)
    write_sqls = [
        s for s in sqls
        if any(kw in s.upper() for kw in ("ALTER", "INSERT", "UPDATE", "DELETE"))
    ]
    assert write_sqls == [], (
        f"dry_run=True must produce ZERO write statements. Got: {write_sqls!r}"
    )


def test_dry_run_idempotency_path_reflects_real_apply():
    """B193: dry_run idempotency_path must reflect what a REAL apply would produce.

    Per phase2/01 § 4.4 canonical Metadata JSON shape — idempotency_path values:
      - "first" when ddl WOULD be applied (columns absent)
      - "no-op" when ddl WOULD be a no-op (columns present)
      - null only for abandonment / abandonment_noop event_kinds (out of scope for B193)

    Pins the cycle-1 design-review 🔴 fix 2026-05-12 (B202): the dry-run path
    previously hardcoded "no-op" regardless of state. This test asserts the
    correct partition.

    Decision: phase2/01 § 4.4 canonical Metadata JSON shape; B202 carryover.
    """
    mod = _load_module()

    # Case 1: would-be-first-apply (columns absent) → idempotency_path = "first"
    cursor_absent = _cursor_columns_absent()
    conn_absent = _make_conn(cursor_absent)
    result_absent = mod.apply(
        conn_absent, actor=_ACTOR, justification=_JUSTIFICATION,
        server=_SERVER, dry_run=True,
    )
    assert result_absent["event_kind"] == "apply", (
        "dry_run on columns-absent state must return event_kind='apply' "
        f"(what real apply would produce); got {result_absent['event_kind']!r}"
    )
    assert result_absent["idempotency_path"] == "first", (
        "dry_run on columns-absent state must return idempotency_path='first' "
        f"per § 4.4 canonical shape; got {result_absent['idempotency_path']!r}"
    )

    # Case 2: would-be-noop (columns present) → idempotency_path = "no-op"
    cursor_present = _cursor_columns_present()
    conn_present = _make_conn(cursor_present)
    result_present = mod.apply(
        conn_present, actor=_ACTOR, justification=_JUSTIFICATION,
        server=_SERVER, dry_run=True,
    )
    assert result_present["event_kind"] == "noop", (
        "dry_run on columns-present state must return event_kind='noop' "
        f"(what real apply would produce); got {result_present['event_kind']!r}"
    )
    assert result_present["idempotency_path"] == "no-op", (
        "dry_run on columns-present state must return idempotency_path='no-op' "
        f"per § 4.4 canonical shape; got {result_present['idempotency_path']!r}"
    )


# ---------------------------------------------------------------------------
# Test: test_audit_row_event_kind_apply_vs_noop
# ---------------------------------------------------------------------------


def test_audit_row_event_kind_apply_vs_noop():
    """B193, I1, D76: event_kind discriminator partitions apply vs noop correctly.

    Covers phase2/01 § 4.4 contract: 'apply' rows = first-applications with
    ddl_applied=True + idempotency_path='first'; 'noop' rows = re-runs with
    ddl_applied=False + idempotency_path='no-op'.

    This test pairs the two scenarios back-to-back to confirm the
    discriminator flips correctly between invocations.
    """
    # --- Scenario A: first apply ---
    mod_a = _load_module()
    cursor_a = _cursor_columns_absent()
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

    # --- Scenario B: re-run (columns now present) ---
    mod_b = _load_module()
    cursor_b = _cursor_columns_present()
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

    # Discriminator separates the two — never both the same
    assert result_a["event_kind"] != result_b["event_kind"], (
        "event_kind must differ between apply and noop invocations"
    )


# ---------------------------------------------------------------------------
# Test: test_server_key_present_in_result
# ---------------------------------------------------------------------------


def test_server_key_present_in_result():
    """B193, D76: 'server' key echoed in result for Gate 6 DISTINCT-counting.

    Per phase2/01 § 4.4 G1 finding: the mandatory 'server' key enables the
    Gate 6 acceptance check which COUNTs DISTINCT servers where event_kind='apply'
    AND ddl_applied=True. Missing this key breaks the acceptance query.
    """
    for columns_exist in (False, True):
        mod = _load_module()
        cursor = _cursor_columns_present() if columns_exist else _cursor_columns_absent()
        conn = _make_conn(cursor)

        result = mod.apply(
            conn,
            actor=_ACTOR,
            justification=_JUSTIFICATION,
            server=_SERVER,
            dry_run=False,
        )

        assert "server" in result, (
            "Result dict must contain 'server' key per phase2/01 § 4.4 G1 fix"
        )
        assert result["server"] == _SERVER, (
            f"server key must match caller value. Expected {_SERVER!r}, "
            f"got {result['server']!r}"
        )


# ---------------------------------------------------------------------------
# Test: test_columns_added_list_is_canonical
# ---------------------------------------------------------------------------


def test_columns_added_list_is_canonical():
    """B193: columns_added exactly names LatenessL99Minutes + LatenessL99UpdatedAt.

    Pillar: Traceability — downstream Tool 14 (measure_lateness.py, B188)
    depends on knowing WHICH columns were added to wire its UPDATE statement.
    An incorrect or empty list silently breaks Tool 14.
    """
    mod = _load_module()
    cursor = _cursor_columns_absent()
    conn = _make_conn(cursor)

    result = mod.apply(
        conn,
        actor=_ACTOR,
        justification=_JUSTIFICATION,
        server=_SERVER,
        dry_run=False,
    )

    assert sorted(result["columns_added"]) == sorted(COLUMNS_ADDED), (
        f"columns_added must be exactly {COLUMNS_ADDED!r}. "
        f"Got: {result['columns_added']!r}"
    )
    # Re-run: empty list expected
    mod2 = _load_module()
    cursor2 = _cursor_columns_present()
    conn2 = _make_conn(cursor2)

    result2 = mod2.apply(
        conn2,
        actor=_ACTOR,
        justification=_JUSTIFICATION,
        server=_SERVER,
        dry_run=False,
    )

    assert result2["columns_added"] == [], (
        "columns_added must be [] on re-run (no new columns added)"
    )


# ---------------------------------------------------------------------------
# Test: test_apply_idempotent_called_twice_same_connection
# ---------------------------------------------------------------------------


def test_apply_idempotent_called_twice_same_connection():
    """B193, I1: Two sequential calls on the same connection — second is a no-op.

    Property: f(apply_first) = 'apply'; f(apply_second) = 'noop'.
    Simulates a crash-and-retry scenario where the migration runs twice.

    Decision: D15 (idempotency mandatory at every layer).
    """
    # First call: columns absent
    mod = _load_module()

    # Simulate: first call checks INFORMATION_SCHEMA → absent, runs DDL.
    # Second call checks INFORMATION_SCHEMA → now present, skips DDL.
    cursor = MagicMock()
    cursor.fetchone.side_effect = [
        None, None,  # first call: both columns absent
        (1,), (1,),  # second call: both columns present
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


# ---------------------------------------------------------------------------
# Test: test_required_keys_all_non_none_on_apply
# ---------------------------------------------------------------------------


def test_required_keys_all_non_none_on_apply():
    """B193: All required Metadata JSON keys have non-None values on first apply.

    Audit-grade invariant: a None value on a required key would silently
    break Gate 6 counting queries (WHERE event_kind = 'apply' AND
    ddl_applied = true) if NULL propagates into the JSON column.
    """
    mod = _load_module()
    cursor = _cursor_columns_absent()
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
