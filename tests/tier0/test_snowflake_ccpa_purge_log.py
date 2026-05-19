"""Tier 0 smoke test for migrations/snowflake_ccpa_purge_log.py (B-535).

Per D67 — runtime ceiling < 5 s; all external dependencies mocked.
Asserts module imports, apply() callable with dry_run=True, DDL contains
canonical column + FK + CHECK surface per plan v5 §15.3, dependency
pre-flight raises DependencyMissingError when SnowflakeReplicationLog
is absent.

North Star pillars:
- Idempotent (D15): apply() returns event_kind='noop' on second run.
- Audit-grade (D76): single MIGRATION_SNOWFLAKE_CCPA_PURGE_LOG event row.
- Forward-only (D92): NO DROP TABLE path.

Pattern: mirrors tests/tier0/test_snowflake_replication_log_migration.py (B-523).
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
    "table_created",
}

_ACTOR = "test-build-smoke"
_JUSTIFICATION = "Tier 0 build-time assertion"
_SERVER = "dev"


def _make_mock_connection_with_dependency(
    dependency_exists: bool = True, table_exists: bool = False
) -> MagicMock:
    """Mock connection where _table_exists returns based on which table.

    First call checks SnowflakeReplicationLog (dependency); second checks
    SnowflakeCcpaPurgeLog (this migration's target).
    """
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    # _verify_dependency runs first → checks SnowflakeReplicationLog
    # Then if it passes, apply() checks SnowflakeCcpaPurgeLog
    fetchone_returns = [
        (1,) if dependency_exists else None,
        (1,) if table_exists else None,
    ]
    cursor.fetchone.side_effect = fetchone_returns
    return conn


def _import_migration():
    from migrations import snowflake_ccpa_purge_log  # noqa: PLC0415
    return snowflake_ccpa_purge_log


def test_module_imports_cleanly():
    mod = _import_migration()
    assert hasattr(mod, "apply")
    assert hasattr(mod, "TABLE_DDL")
    assert hasattr(mod, "INDEX_REPLICATION_DDL")
    assert hasattr(mod, "INDEX_CCPA_DELETION_DDL")
    assert hasattr(mod, "DependencyMissingError")
    assert mod.MIGRATION_NAME == "MIGRATION_SNOWFLAKE_CCPA_PURGE_LOG"
    assert mod.TABLE_NAME == "SnowflakeCcpaPurgeLog"
    assert mod.DEPENDENCY_TABLE == "SnowflakeReplicationLog"


def test_ddl_contains_canonical_columns_per_plan_v5():
    mod = _import_migration()
    ddl = mod.TABLE_DDL
    for column in [
        "PurgeLogId", "ReplicationId", "CcpaDeletionLogId",
        "SnowflakeAction", "SnowflakePurgedAt", "AffectedIcebergRowCount",
        "Actor", "Justification",
    ]:
        assert column in ddl, f"Required column {column} missing from TABLE_DDL"


def test_ddl_contains_action_check_constraint():
    mod = _import_migration()
    ddl = mod.TABLE_DDL
    assert "CK_SnowflakeCcpaPurgeLog_Action" in ddl
    for action in [
        "'masking_policy_activated'",
        "'deleted'",
        "'row_access_policy_filtered'",
    ]:
        assert action in ddl, f"SnowflakeAction CHECK missing value {action}"


def test_ddl_contains_fk_to_snowflake_replication_log():
    mod = _import_migration()
    ddl = mod.TABLE_DDL
    assert "FK_SnowflakeCcpaPurgeLog_ReplicationId" in ddl
    assert "SnowflakeReplicationLog(ReplicationId)" in ddl


def test_ddl_contains_fk_to_ccpa_deletion_log():
    mod = _import_migration()
    ddl = mod.TABLE_DDL
    assert "FK_SnowflakeCcpaPurgeLog_CcpaDeletionLogId" in ddl
    assert "CcpaDeletionLog(DeletionLogId)" in ddl


def test_indexes_on_fk_columns():
    mod = _import_migration()
    assert "IX_SnowflakeCcpaPurgeLog_Replication" in mod.INDEX_REPLICATION_DDL
    assert "(ReplicationId)" in mod.INDEX_REPLICATION_DDL
    assert "IX_SnowflakeCcpaPurgeLog_CcpaDeletion" in mod.INDEX_CCPA_DELETION_DDL
    assert "(CcpaDeletionLogId)" in mod.INDEX_CCPA_DELETION_DDL


def test_apply_dry_run_first_apply_with_dependency_present():
    mod = _import_migration()
    conn = _make_mock_connection_with_dependency(
        dependency_exists=True, table_exists=False
    )
    result = mod.apply(conn, actor=_ACTOR, justification=_JUSTIFICATION,
                       server=_SERVER, dry_run=True)
    assert REQUIRED_RETURN_KEYS.issubset(result.keys())
    assert result["event_kind"] == "apply"
    assert result["idempotency_path"] == "first"
    assert result["dry_run"] is True
    assert result["would_create_table"] is True


def test_apply_dry_run_noop_when_table_already_exists():
    mod = _import_migration()
    conn = _make_mock_connection_with_dependency(
        dependency_exists=True, table_exists=True
    )
    result = mod.apply(conn, actor=_ACTOR, justification=_JUSTIFICATION,
                       server=_SERVER, dry_run=True)
    assert result["event_kind"] == "noop"
    assert result["idempotency_path"] == "no-op"
    assert result["would_create_table"] is False


def test_dependency_missing_raises():
    mod = _import_migration()
    conn = _make_mock_connection_with_dependency(
        dependency_exists=False, table_exists=False
    )
    with pytest.raises(mod.DependencyMissingError) as exc_info:
        mod.apply(conn, actor=_ACTOR, justification=_JUSTIFICATION,
                  server=_SERVER, dry_run=True)
    err_msg = str(exc_info.value)
    assert "SnowflakeReplicationLog" in err_msg
    assert "migrations/snowflake_replication_log.py" in err_msg
    assert "B-523" in err_msg


def test_main_callable_with_argparse():
    mod = _import_migration()
    assert callable(mod.main)
