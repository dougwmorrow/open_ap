"""Tier 0 smoke test for migrations/snowflake_replication_log.py (B-523).

Per D67 — runtime ceiling < 5 s; all external dependencies mocked.
Asserts module imports, apply() callable with dry_run=True, returned dict
has required keys, DDL string contains the canonical column + constraint
surface per plan v5 §15.3.

North Star pillars:
- Idempotent (D15): apply() returns event_kind='noop' on second run.
- Audit-grade (D76): single MIGRATION_SNOWFLAKE_REPLICATION_LOG event row per invocation.
- Forward-only (D92): NO DROP TABLE path; IF NOT EXISTS guard via _table_exists.

Pattern: mirrors tests/tier0/test_capacity_baseline_log.py (B-195 canary)
and tests/tier0/test_lateness_columns.py (B-193 canary).
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


def _make_mock_connection(table_exists: bool = False) -> MagicMock:
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    if table_exists:
        cursor.fetchone.return_value = (1,)
    else:
        cursor.fetchone.return_value = None
    return conn


def _import_migration():
    from migrations import snowflake_replication_log  # noqa: PLC0415
    return snowflake_replication_log


def test_module_imports_cleanly():
    mod = _import_migration()
    assert hasattr(mod, "apply")
    assert hasattr(mod, "TABLE_DDL")
    assert hasattr(mod, "UNIQUE_INDEX_DDL")
    assert hasattr(mod, "FILTERED_INDEX_DDL")
    assert hasattr(mod, "MIGRATION_NAME")
    assert mod.MIGRATION_NAME == "MIGRATION_SNOWFLAKE_REPLICATION_LOG"
    assert mod.TABLE_NAME == "SnowflakeReplicationLog"
    assert mod.TABLE_SCHEMA == "ops"


def test_ddl_contains_canonical_columns_per_plan_v5():
    mod = _import_migration()
    ddl = mod.TABLE_DDL
    for column in [
        "ReplicationId", "RegistryId", "SnowflakeStagePath",
        "MaskedContentChecksum", "VaultTokenSnapshotMarker",
        "RowsCopied", "CopyHistoryId", "SourceFilePurgedAt",
        "ReplicatedAt", "ReplicationAttempt", "Status", "ErrorMessage",
    ]:
        assert column in ddl, f"Required column {column} missing from TABLE_DDL"


def test_ddl_contains_check_constraint_per_d123():
    mod = _import_migration()
    ddl = mod.TABLE_DDL
    assert "CK_SnowflakeReplicationLog_Status" in ddl
    for status_value in ["'replicated'", "'failed'", "'in_progress'"]:
        assert status_value in ddl, f"Status CHECK missing value {status_value}"


def test_ddl_contains_fk_to_parquet_snapshot_registry():
    mod = _import_migration()
    ddl = mod.TABLE_DDL
    assert "FK_SnowflakeReplicationLog_RegistryId" in ddl
    assert "REFERENCES" in ddl
    assert "ParquetSnapshotRegistry(RegistryId)" in ddl
    assert "ON DELETE NO ACTION" in ddl


def test_unique_index_on_registryid_replicationattempt():
    mod = _import_migration()
    assert "UX_SnowflakeReplicationLog_Identity" in mod.UNIQUE_INDEX_DDL
    assert "(RegistryId, ReplicationAttempt)" in mod.UNIQUE_INDEX_DDL


def test_filtered_pending_retry_index_per_b529():
    mod = _import_migration()
    ddl = mod.FILTERED_INDEX_DDL
    assert "IX_SnowflakeReplicationLog_PendingRetry" in ddl
    assert "WHERE Status IN ('in_progress', 'failed')" in ddl


def test_apply_dry_run_first_apply_path():
    mod = _import_migration()
    conn = _make_mock_connection(table_exists=False)
    result = mod.apply(conn, actor=_ACTOR, justification=_JUSTIFICATION,
                       server=_SERVER, dry_run=True)
    assert REQUIRED_RETURN_KEYS.issubset(result.keys())
    assert result["event_kind"] == "apply"
    assert result["idempotency_path"] == "first"
    assert result["dry_run"] is True
    assert result["would_create_table"] is True
    assert result["ddl_applied"] is False  # dry-run doesn't execute
    assert result["server"] == _SERVER


def test_apply_dry_run_noop_path_table_exists():
    mod = _import_migration()
    conn = _make_mock_connection(table_exists=True)
    result = mod.apply(conn, actor=_ACTOR, justification=_JUSTIFICATION,
                       server=_SERVER, dry_run=True)
    assert result["event_kind"] == "noop"
    assert result["idempotency_path"] == "no-op"
    assert result["would_create_table"] is False


def test_main_callable_with_argparse():
    mod = _import_migration()
    assert callable(mod.main)
