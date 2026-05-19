"""Tier 0 smoke test for migrations/cdc_mode_column.py (B-542 + D63 + D125).

Per D67 — runtime ceiling < 5s; all external dependencies mocked.

Asserts:
- Module imports cleanly
- apply() callable with dry_run=True returns a dict with required keys
- DDL strings contain canonical column + DEFAULT + CHECK constraint surface
- 3-value enum per D125 (`'change_detect'`, `'parquet_snapshot'`, `'both'`)
- Idempotent paths (no-op / partial / first) covered

North Star pillars:
- Idempotent (D15): apply() returns event_kind='noop' on second run.
- Audit-grade (D76): single MIGRATION_CDC_MODE_COLUMN event row per invocation.
- Forward-only (D92): NO DROP COLUMN path; sys.columns/check_constraints guarded.

Pattern: mirrors `tests/tier0/test_snowflake_replication_log.py` (B-523 canary).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


REQUIRED_RETURN_KEYS = {
    "event_kind",
    "ddl_applied",
    "idempotency_path",
    "ddl_statements_executed",
    "server",
    "column_added",
    "constraint_added",
}

_ACTOR = "test-build-smoke"
_JUSTIFICATION = "Tier 0 build-time assertion"
_SERVER = "dev"


def _make_mock_connection(column_exists: bool = False,
                          check_exists: bool = False) -> MagicMock:
    """Return a mock pyodbc-style connection whose cursor.fetchone() returns
    (1,) when the queried object exists, None otherwise.

    Two queries are issued in apply(): column existence, then check-constraint
    existence. fetchone() is configured to return values matching the order.
    """
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    # apply() first checks column existence, then check-constraint existence
    cursor.fetchone.side_effect = [
        (1,) if column_exists else None,
        (1,) if check_exists else None,
    ]
    return conn


def _import_migration():
    from migrations import cdc_mode_column  # noqa: PLC0415
    return cdc_mode_column


# ---------------------------------------------------------------------------
# Class A — surface invariants (module imports + DDL string content)
# ---------------------------------------------------------------------------


def test_module_imports_cleanly():
    mod = _import_migration()
    assert mod is not None
    assert mod.MIGRATION_NAME == "MIGRATION_CDC_MODE_COLUMN"
    assert mod.TABLE_NAME == "UdmTablesList"
    assert mod.COLUMN_NAME == "CDCMode"


def test_allowed_values_3_value_per_d125():
    """D125 extends D63's 2-value enum to 3 values from day 1."""

    mod = _import_migration()
    assert mod.ALLOWED_CDC_MODE_VALUES == (
        "change_detect", "parquet_snapshot", "both",
    ), "D125 3-value enum required from day 1"
    assert mod.DEFAULT_CDC_MODE_VALUE == "change_detect", \
        "D63 default 'change_detect' must be preserved"


def test_column_add_ddl_contains_canonical_surface():
    mod = _import_migration()
    ddl = mod.COLUMN_ADD_DDL
    assert "ALTER TABLE" in ddl
    assert "UdmTablesList" in ddl
    assert "CDCMode NVARCHAR(20) NOT NULL" in ddl
    assert "DF_UdmTablesList_CDCMode" in ddl
    assert "'change_detect'" in ddl


def test_check_constraint_ddl_3_value_per_d125():
    mod = _import_migration()
    ddl = mod.CHECK_CONSTRAINT_DDL
    assert "CK_UdmTablesList_CDCMode" in ddl
    assert "'change_detect'" in ddl
    assert "'parquet_snapshot'" in ddl
    assert "'both'" in ddl, \
        "D125 'both' value MUST be in CHECK constraint DDL from day 1"


def test_check_constraint_ddl_excludes_unknown_values():
    """Defensive: CHECK constraint should not accidentally include 'legacy'
    (a pre-D63 candidate name) or 'parquet' (typo risk)."""

    mod = _import_migration()
    ddl = mod.CHECK_CONSTRAINT_DDL
    assert "'legacy'" not in ddl, "Pitfall #9.k drift class: 'legacy' is stale; canonical is 'change_detect'"
    # Check that 'parquet' only appears as part of 'parquet_snapshot'
    assert ddl.count("'parquet'") == 0


# ---------------------------------------------------------------------------
# Class B — behavioral invariants (apply() callable; idempotent paths)
# ---------------------------------------------------------------------------


def test_apply_dry_run_first_time_returns_apply_event():
    """First-time dry-run: column missing + check missing → event_kind='apply'."""

    mod = _import_migration()
    conn = _make_mock_connection(column_exists=False, check_exists=False)
    result = mod.apply(conn, actor=_ACTOR, justification=_JUSTIFICATION,
                       server=_SERVER, dry_run=True)
    assert isinstance(result, dict)
    assert REQUIRED_RETURN_KEYS.issubset(result.keys())
    assert result["event_kind"] == "apply"
    assert result["dry_run"] is True
    assert result["would_add_column"] is True
    assert result["would_add_constraint"] is True
    # No commit on dry-run
    conn.commit.assert_not_called()


def test_apply_dry_run_idempotent_noop_when_both_present():
    """Idempotency: column + check both present → event_kind='noop'."""

    mod = _import_migration()
    conn = _make_mock_connection(column_exists=True, check_exists=True)
    result = mod.apply(conn, actor=_ACTOR, justification=_JUSTIFICATION,
                       server=_SERVER, dry_run=True)
    assert result["event_kind"] == "noop"
    assert result["would_add_column"] is False
    assert result["would_add_constraint"] is False
    # No commit on dry-run
    conn.commit.assert_not_called()


def test_apply_dry_run_partial_recovery_when_only_column_present():
    """Partial-recovery: column present but check missing (DDL ran mid-tx
    crash on first run) → event_kind='apply'; would add constraint only."""

    mod = _import_migration()
    conn = _make_mock_connection(column_exists=True, check_exists=False)
    result = mod.apply(conn, actor=_ACTOR, justification=_JUSTIFICATION,
                       server=_SERVER, dry_run=True)
    assert result["event_kind"] == "apply"
    assert result["would_add_column"] is False
    assert result["would_add_constraint"] is True
    # Standardized to 'partial-recovery' per cohort-review Agent
    # ad50cb5cceda3f90c 2026-05-19 IMPROVE — dry-run/apply path symmetry.
    assert result["idempotency_path"] == "partial-recovery"


def test_apply_dry_run_returns_required_keys():
    mod = _import_migration()
    conn = _make_mock_connection(column_exists=False, check_exists=False)
    result = mod.apply(conn, actor=_ACTOR, justification=_JUSTIFICATION,
                       server=_SERVER, dry_run=True)
    for key in REQUIRED_RETURN_KEYS:
        assert key in result, f"Required key {key!r} missing from result dict"


def test_apply_dry_run_no_ddl_executed():
    """D75: --dry-run default MUST NOT execute DDL or write audit rows."""

    mod = _import_migration()
    conn = _make_mock_connection(column_exists=False, check_exists=False)
    cursor = conn.cursor.return_value
    mod.apply(conn, actor=_ACTOR, justification=_JUSTIFICATION,
              server=_SERVER, dry_run=True)
    # Only 2 SELECTs executed (column-exists + check-exists probes)
    # NO ALTER TABLE, NO INSERT INTO PipelineEventLog/SchemaContract
    executed_sqls = [call.args[0] for call in cursor.execute.call_args_list]
    for sql in executed_sqls:
        assert "ALTER TABLE" not in sql.upper(), \
            f"D75 dry-run violation: ALTER TABLE executed: {sql[:80]}"
        assert "INSERT INTO" not in sql.upper(), \
            f"D75 dry-run violation: INSERT executed: {sql[:80]}"


def test_apply_server_value_round_trips():
    """server kwarg propagates into result metadata."""

    mod = _import_migration()
    conn = _make_mock_connection()
    result = mod.apply(conn, actor=_ACTOR, justification=_JUSTIFICATION,
                       server="prod", dry_run=True)
    assert result["server"] == "prod"
