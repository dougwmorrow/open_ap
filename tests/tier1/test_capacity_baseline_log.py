"""Tier 1 unit tests for migrations/capacity_baseline_log.py.

Tests run on every commit. No live DB or network required; all pyodbc
connections are mocked with unittest.mock.MagicMock.

North Star pillars addressed:
  - Idempotent (D15): B195 migration must be safe to re-run; IF NOT EXISTS
    guard on CREATE TABLE must prevent duplicate-create errors.
  - Audit-grade (D76): exactly one MIGRATION_CAPACITY_BASELINE_LOG event
    row per invocation; Metadata JSON must match canonical shape per
    phase2/01 § 4.4.
  - Traceability (D26 + D92): CapacityBaselineLog is append-only per D26;
    migration that creates it must itself produce a SchemaContract row per
    Round 1 § 23 + D92 forward-only additive.

Edge case IDs (per 04_EDGE_CASES.md I-series idempotency):
  - I1 (same-BatchId retry ledger short-circuits): analogous here — re-run
    on same server short-circuits CREATE TABLE via IF NOT EXISTS guard.
  - I3 (concurrent same-key UNIQUE prevents): SchemaContract UNIQUE-guarded
    insert must not double-write on re-run.

Decision citations:
  D15 (idempotency mandatory), D26 (append-only CapacityBaselineLog),
  D76 (audit-row contract), D92 (forward-only additive schema), D74 (exit
  codes), D75 (arg naming).

Backlog/spec refs:
  B195 (this migration's backlog entry),
  phase2/01 § 4.4 (apply() contract + Metadata JSON canonical shape),
  phase1/04b § 5 (CapacityResult dataclass — table schema mirrors it
  field-for-field per B195 spec).

Pattern: mirrors tests/tier1/test_lateness_columns.py (B193 canary).

Key shape difference from B193 (ALTER COLUMN):
  B195 is a CREATE TABLE migration, so:
  - 'table_created' (bool) replaces 'columns_added' (list) in the return dict.
  - ddl_statements_executed = 2 on first apply (CREATE TABLE + CREATE INDEX
    per cycle-1 reviewer fix 2026-05-12 B204 — the IX_CapacityBaselineLog_Table
    NONCLUSTERED index is a separate DDL statement and counts toward the audit
    contract per § 4.4).
  - idempotency_path = 'first' on first apply, 'no-op' on re-run.
  - event_kind = 'apply' on first apply, 'noop' on re-run.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Project root on sys.path (matches tests/ convention)
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Constants — single source of truth for expected values
# ---------------------------------------------------------------------------

# DDL count on first apply: CREATE TABLE + CREATE INDEX = 2 statements
# (cycle-1 reviewer fix 2026-05-12 per B204 — the IX_CapacityBaselineLog_Table
# NONCLUSTERED index is a separate DDL statement; both execute on a clean
# first-apply, so ddl_statements_executed = 2 per § 4.4 audit contract).
FIRST_APPLY_DDL_COUNT = 2

# Canonical Metadata JSON keys for B195 (phase2/01 § 4.4 CREATE TABLE variant)
# 'table_created' replaces 'columns_added' from the B193 ALTER COLUMN shape.
REQUIRED_METADATA_KEYS = {
    "event_kind",
    "ddl_applied",
    "idempotency_path",
    "ddl_statements_executed",
    "server",
    "table_created",
}

# Target table name per phase1/04b § 5 + B195 spec
TARGET_TABLE_NAME = "CapacityBaselineLog"

# PipelineEventLog audit row EventType (phase2/01 § 4.4 + D76 MIGRATION_* family)
EXPECTED_EVENT_TYPE = "MIGRATION_CAPACITY_BASELINE_LOG"

_ACTOR = "test-author"
_JUSTIFICATION = "Tier 1 unit test"
_SERVER = "dev"


# ---------------------------------------------------------------------------
# Fixture: module loader
#
# Re-loads the module on every test to prevent cross-test state leakage
# (e.g., a cached table-exists flag at module level).
# ---------------------------------------------------------------------------


def _load_module() -> Any:
    """Load migrations/capacity_baseline_log.py with DB imports patched out."""
    module_path = _PROJECT_ROOT / "migrations" / "capacity_baseline_log.py"
    module_key = "migrations.capacity_baseline_log"

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
    """Cursor reporting CapacityBaselineLog ABSENT (first-apply scenario)."""
    cursor = MagicMock()
    # fetchone() called to check OBJECT_ID / sys.tables / INFORMATION_SCHEMA
    cursor.fetchone.return_value = None
    return cursor


def _cursor_table_present() -> MagicMock:
    """Cursor reporting CapacityBaselineLog PRESENT (idempotent re-run)."""
    cursor = MagicMock()
    cursor.fetchone.return_value = (1,)
    return cursor


def _make_conn(cursor: MagicMock) -> MagicMock:
    """Wrap a cursor mock in a connection mock."""
    conn = MagicMock()
    conn.cursor.return_value = cursor
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    return conn


# ---------------------------------------------------------------------------
# Helper: collect SQL strings passed to cursor.execute()
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
# Test: test_first_apply_clean_state
# ---------------------------------------------------------------------------


def test_first_apply_clean_state():
    """B195, I1: First apply on a clean DB — 1 CREATE TABLE runs, event_kind='apply'.

    Idempotency edge case I1 (first-application path; table absent).

    Decision: D15 (idempotency mandatory) + D92 (forward-only additive —
    new table created, never dropped).

    Verifies:
    - CREATE TABLE statement emitted to cursor.
    - Return dict has event_kind='apply', ddl_applied=True,
      idempotency_path='first', ddl_statements_executed=1.
    - table_created=True.
    - server field matches caller-supplied value.

    Pillar: Idempotent + Audit-grade.
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
    assert result["ddl_applied"] is True, (
        "First apply must set ddl_applied=True"
    )
    assert result["idempotency_path"] == "first", (
        "First apply must set idempotency_path='first'"
    )
    assert result["ddl_statements_executed"] == FIRST_APPLY_DDL_COUNT, (
        f"Expected {FIRST_APPLY_DDL_COUNT} DDL statement (one CREATE TABLE), "
        f"got {result['ddl_statements_executed']}"
    )
    assert result["table_created"] is True, (
        "First apply must set table_created=True"
    )
    assert result["server"] == _SERVER, (
        "server key must echo the caller-supplied server value (Gate 6 counting key)"
    )

    # Confirm CREATE TABLE emitted to cursor
    sqls = _executed_sql_strings(cursor)
    create_sqls = [s for s in sqls if "CREATE" in s.upper() and "TABLE" in s.upper()]
    assert len(create_sqls) >= 1, (
        f"Expected >= 1 CREATE TABLE statement. Got: {create_sqls!r}"
    )


# ---------------------------------------------------------------------------
# Test: test_idempotent_rerun
# ---------------------------------------------------------------------------


def test_idempotent_rerun():
    """B195, I1: Re-run after first apply — 0 DDL, event_kind='noop'.

    Idempotency edge case I1 (IF NOT EXISTS / OBJECT_ID guard short-circuits
    on re-run when CapacityBaselineLog already exists).

    Decision: D15 (idempotency mandatory) + D92 (forward-only — no DROP path).

    Verifies:
    - No CREATE TABLE statement emitted.
    - Return dict has event_kind='noop', ddl_applied=False,
      idempotency_path='no-op', ddl_statements_executed=0.
    - table_created=False (table was already there).
    - server field still echoed correctly.

    Pillar: Idempotent.
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
    assert result["ddl_applied"] is False, (
        "Re-run must set ddl_applied=False"
    )
    assert result["idempotency_path"] == "no-op", (
        "Re-run must set idempotency_path='no-op'"
    )
    assert result["ddl_statements_executed"] == 0, (
        "Re-run must execute 0 DDL statements (IF NOT EXISTS guard fired)"
    )
    assert result["table_created"] is False, (
        "Re-run must set table_created=False (table already existed)"
    )
    assert result["server"] == _SERVER

    # Confirm no CREATE TABLE emitted
    sqls = _executed_sql_strings(cursor)
    create_sqls = [s for s in sqls if "CREATE" in s.upper() and "TABLE" in s.upper()]
    assert create_sqls == [], (
        f"No CREATE TABLE statements should be emitted on re-run. Got: {create_sqls!r}"
    )


# ---------------------------------------------------------------------------
# Test: test_schema_contract_row_written_on_first_apply
# ---------------------------------------------------------------------------


def test_schema_contract_row_written_on_first_apply():
    """B195, I3: First apply writes SchemaContract row per Round 7 § 1.1 + D92.

    Idempotency edge case I3 (SchemaContract UNIQUE index prevents double-write
    — contract rows must NOT be emitted on re-run because the table-existence
    guard fires before reaching SchemaContract write).

    Decision: D92 (forward-only additive + SchemaContract protocol).

    Verifies:
    - cursor.execute called with a SchemaContract INSERT on first apply.
    - On re-run (table already present), SchemaContract INSERT NOT emitted.

    Pillar: Audit-grade + Traceability.
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
        "Expected >= 1 SchemaContract INSERT statement on first apply. "
        f"Statements: {schema_contract_inserts!r}"
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
        "table-existence guard must fire before reaching the contract write. "
        f"Got: {schema_contract_inserts_rerun!r}"
    )


# ---------------------------------------------------------------------------
# Test: test_audit_row_metadata_shape
# ---------------------------------------------------------------------------


def test_audit_row_metadata_shape():
    """B195, D76: One MIGRATION_CAPACITY_BASELINE_LOG audit row per apply() call.

    North Star: Audit-grade (D76 audit-row contract — every migration
    invocation writes ONE PipelineEventLog row per phase2/01 § 4.4).

    Verifies:
    - Exactly one PipelineEventLog INSERT emitted per apply() call.
    - Return dict (which mirrors Metadata JSON) contains all required keys.
    - event_kind discriminator partitions correctly: 'apply' on first-apply,
      'noop' on re-run.

    Pillar: Audit-grade.
    """
    # First apply — event_kind must be 'apply'
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

    assert set(result.keys()) >= REQUIRED_METADATA_KEYS, (
        f"Metadata dict missing keys: {REQUIRED_METADATA_KEYS - set(result.keys())!r}"
    )

    # Confirm PipelineEventLog INSERT emitted
    sqls = _executed_sql_strings(cursor)
    event_log_inserts = [
        s for s in sqls
        if "PipelineEventLog" in s and "INSERT" in s.upper()
    ]
    assert len(event_log_inserts) >= 1, (
        "apply() must INSERT exactly one row into PipelineEventLog per D76. "
        f"Statements seen: {sqls!r}"
    )

    # Verify event_kind discriminator on first apply
    assert result["event_kind"] == "apply"
    assert result["ddl_applied"] is True


# ---------------------------------------------------------------------------
# Test: test_dry_run_no_writes
# ---------------------------------------------------------------------------


def test_dry_run_no_writes():
    """B195: dry_run=True — zero DB writes (no DDL, no SchemaContract, no audit row).

    Per phase2/01 § 4.4: dry_run suppresses ALL writes. Return dict must
    have ddl_applied=False, table_created=False.

    Decision: D75 (--dry-run default for side-effecting tools).
    Pillar: Idempotent (dry-run is a special no-write idempotency path).
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

    assert result["ddl_applied"] is False, (
        "dry_run must produce ddl_applied=False"
    )
    assert result["table_created"] is False, (
        "dry_run must produce table_created=False (no DDL executed)"
    )

    # No write statements executed (ALTER / CREATE / INSERT / UPDATE / DELETE)
    sqls = _executed_sql_strings(cursor)
    write_sqls = [
        s for s in sqls
        if any(kw in s.upper() for kw in ("CREATE", "INSERT", "UPDATE", "DELETE", "ALTER"))
    ]
    assert write_sqls == [], (
        f"dry_run=True must produce ZERO write statements. Got: {write_sqls!r}"
    )


# ---------------------------------------------------------------------------
# Test: test_dry_run_idempotency_path_reflects_real_apply
# ---------------------------------------------------------------------------


def test_dry_run_idempotency_path_reflects_real_apply():
    """B195: dry_run idempotency_path must reflect what a REAL apply would produce.

    Per phase2/01 § 4.4 canonical Metadata JSON shape — idempotency_path values:
      - 'first' when CREATE TABLE WOULD be executed (table absent)
      - 'no-op' when CREATE TABLE WOULD be a no-op (table present)

    This test exercises the B202 fix pattern (dry-run path must NOT hardcode
    'no-op' regardless of state — it must reflect the real-apply outcome).

    Decision: phase2/01 § 4.4 canonical shape; B195 dry-run contract.
    Pillar: Idempotent + Audit-grade.
    """
    mod = _load_module()

    # Case 1: would-be-first-apply (table absent) → idempotency_path='first'
    cursor_absent = _cursor_table_absent()
    conn_absent = _make_conn(cursor_absent)
    result_absent = mod.apply(
        conn_absent,
        actor=_ACTOR,
        justification=_JUSTIFICATION,
        server=_SERVER,
        dry_run=True,
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
        conn_present,
        actor=_ACTOR,
        justification=_JUSTIFICATION,
        server=_SERVER,
        dry_run=True,
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
# Test: test_server_key_present_in_result
# ---------------------------------------------------------------------------


def test_server_key_present_in_result():
    """B195, D76: 'server' key echoed in result for Gate 6 DISTINCT-counting.

    Per phase2/01 § 4.4 G1 finding: the mandatory 'server' key enables the
    Gate 6 acceptance check which COUNTs DISTINCT servers where event_kind='apply'
    AND ddl_applied=True. Missing this key breaks the acceptance query.

    Tested for BOTH table-absent and table-present paths.
    Pillar: Audit-grade + Traceability.
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

        assert "server" in result, (
            "Result dict must contain 'server' key per phase2/01 § 4.4 G1 fix"
        )
        assert result["server"] == _SERVER, (
            f"server key must match caller value. Expected {_SERVER!r}, "
            f"got {result['server']!r}"
        )


# ---------------------------------------------------------------------------
# Test: test_event_kind_apply_vs_noop_discriminator
# ---------------------------------------------------------------------------


def test_event_kind_apply_vs_noop_discriminator():
    """B195, I1, D76: event_kind discriminator partitions apply vs noop correctly.

    Covers phase2/01 § 4.4 contract: 'apply' rows = first-applications with
    ddl_applied=True + idempotency_path='first'; 'noop' rows = re-runs with
    ddl_applied=False + idempotency_path='no-op'.

    Pairs the two scenarios back-to-back to confirm the discriminator flips
    correctly between invocations.

    Pillar: Audit-grade + Idempotent.
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

    # Discriminator must differ between the two invocations
    assert result_a["event_kind"] != result_b["event_kind"], (
        "event_kind must differ between apply and noop invocations"
    )


# ---------------------------------------------------------------------------
# Test: test_create_table_schema_mirrors_capacity_result_fields
# ---------------------------------------------------------------------------


def test_create_table_schema_mirrors_capacity_result_fields():
    """B195: CREATE TABLE DDL references all CapacityResult field names.

    Per phase1/04b § 5: 'schema MUST match Tool 16 CapacityResult dataclass
    field-for-field'. This test is a structural guard — verifies that the
    DDL string emitted to cursor.execute() references the canonical field names
    from the CapacityResult dataclass.

    CapacityResult fields per phase1/04b § 5:
      source_name, table_name, current_row_count, current_storage_mb,
      growth_rate_rows_per_month, projected_rows_12_months,
      projected_rows_7_years, projected_storage_mb_12_months,
      projected_storage_mb_7_years, current_partition_layout,
      avg_partition_file_size_mb, partition_recommendation, measured_at.

    Pillar: Traceability (phase1/04b § 5 field-for-field contract).
    Decision: D92 (forward-only; CREATE TABLE is the ONLY DDL for B195).
    """
    # Canonical CapacityResult fields (per phase1/04b § 5 — frozen)
    CAPACITY_RESULT_FIELDS = [
        "source_name",
        "table_name",
        "current_row_count",
        "current_storage_mb",
        "growth_rate_rows_per_month",
        "projected_rows_12_months",
        "projected_rows_7_years",
        "projected_storage_mb_12_months",
        "projected_storage_mb_7_years",
        "current_partition_layout",
        "avg_partition_file_size_mb",
        "partition_recommendation",
        "measured_at",
    ]

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

    # Collect all SQL strings
    sqls = _executed_sql_strings(cursor)
    create_ddl_candidates = [
        s for s in sqls if "CREATE" in s.upper() and "TABLE" in s.upper()
    ]
    assert create_ddl_candidates, (
        "No CREATE TABLE DDL found in cursor.execute calls on first apply."
    )

    # Check each CapacityResult field appears in the DDL (normalize case + strip
    # underscores per cycle-1 post-fix verify 2026-05-12 — Python dataclass fields
    # are snake_case [source_name]; SQL columns are PascalCase [SourceName].
    # Normalize both sides to lowercase-alphanumeric for matching).
    def _normalize(s: str) -> str:
        return "".join(c.lower() for c in s if c.isalnum())

    combined_ddl_norm = _normalize(" ".join(create_ddl_candidates))
    missing_fields = [
        f for f in CAPACITY_RESULT_FIELDS
        if _normalize(f) not in combined_ddl_norm
    ]
    assert not missing_fields, (
        f"CREATE TABLE DDL is missing CapacityResult fields: {missing_fields!r}. "
        "Per phase1/04b § 5, B195 schema must mirror CapacityResult field-for-field. "
        f"DDL seen: {combined_ddl!r}"
    )


# ---------------------------------------------------------------------------
# Test: test_apply_idempotent_called_twice_same_connection
# ---------------------------------------------------------------------------


def test_apply_idempotent_called_twice_same_connection():
    """B195, I1: Two sequential calls on the same connection — second is a no-op.

    Property: first call = event_kind='apply'; second call = event_kind='noop'.
    Simulates a crash-and-retry scenario where the migration runs twice.

    Decision: D15 (idempotency mandatory at every layer).
    Pillar: Idempotent.
    """
    mod = _load_module()

    # Simulate: first call checks existence → absent, runs DDL.
    # Second call checks existence → now present, skips DDL.
    cursor = MagicMock()
    cursor.fetchone.side_effect = [
        None,  # first call: table absent → run CREATE TABLE
        (1,),  # second call: table present → skip
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
    """B195: All required Metadata JSON keys have non-None values on first apply.

    Audit-grade invariant: a None value on a required key silently breaks
    Gate 6 PipelineEventLog filter queries (WHERE event_kind='apply' AND
    ddl_applied=true) if NULL propagates into the JSON column.

    Pillar: Audit-grade.
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
# Test: test_target_table_name_in_ddl
# ---------------------------------------------------------------------------


def test_target_table_name_in_ddl():
    """B195: CREATE TABLE DDL targets General.ops.CapacityBaselineLog.

    Verifies the correct table name (per phase1/04b § 5 + B195 spec) appears
    in the DDL string. A wrong table name would create a shadow table, leaving
    CapacityBaselineLog uninitialized and silently breaking Tool 16 (B190).

    Pillar: Traceability (Tool 16 depends on this table).
    Decision: D26 (append-only — CapacityBaselineLog must be the target).
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
    create_sqls = [s for s in sqls if "CREATE" in s.upper() and "TABLE" in s.upper()]
    assert create_sqls, (
        "No CREATE TABLE statement found in cursor.execute calls on first apply."
    )

    combined = " ".join(create_sqls)
    assert TARGET_TABLE_NAME in combined, (
        f"CREATE TABLE DDL must reference '{TARGET_TABLE_NAME}'. "
        f"Got DDL: {combined!r}"
    )
