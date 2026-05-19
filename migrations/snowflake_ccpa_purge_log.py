"""B-535 — CREATE TABLE ``General.ops.SnowflakeCcpaPurgeLog`` (append-only CCPA purge audit).

Per D26 (append-only) + D92 (forward-only additive) + D121 (Option B) + user
choice 2026-05-18 per v3 gap-check G6-4: NEW table for Snowflake-side CCPA
purge audit (cleaner separation than extending SnowflakeReplicationLog
``Status`` enum with a 4th value 'purged_per_ccpa').

Authored per ``docs/migration/PHASE2_LARGE_TABLES_AUDITLOG_PILOT_PLAN_2026-05-18.md``
§15.3 canonical DDL (v5; B-535 MEDIUM closure target Phase 2 R1).

**Dependencies**: ``General.ops.SnowflakeReplicationLog`` (B-523 +
``migrations/snowflake_replication_log.py``) MUST be created first; this
migration FKs into it. ``General.ops.CcpaDeletionLog`` (existing per Round 1
schema) MUST exist (it does; canonical at `phase1/01_database_schema.md`).

Schema (per plan v5 §15.3)
--------------------------

* ``PurgeLogId BIGINT IDENTITY(1,1) PRIMARY KEY``
* ``ReplicationId BIGINT NOT NULL`` FK → ``SnowflakeReplicationLog(ReplicationId)``
* ``CcpaDeletionLogId BIGINT NOT NULL`` FK → ``CcpaDeletionLog(DeletionLogId)``
* ``SnowflakeAction NVARCHAR(50) NOT NULL`` with CHECK constraint
* ``SnowflakePurgedAt DATETIME2(3) NOT NULL DEFAULT SYSUTCDATETIME()``
* ``AffectedIcebergRowCount BIGINT NULL`` — operator-supplied
* ``Actor NVARCHAR(255) NOT NULL``
* ``Justification NVARCHAR(MAX) NULL``

Indexes
-------

* ``IX_SnowflakeCcpaPurgeLog_Replication`` on ``(ReplicationId)``
* ``IX_SnowflakeCcpaPurgeLog_CcpaDeletion`` on ``(CcpaDeletionLogId)``

Constraints
-----------

* ``CK_SnowflakeCcpaPurgeLog_Action CHECK (SnowflakeAction IN ('masking_policy_activated','deleted','row_access_policy_filtered'))``

Audit trail
-----------

One ``MIGRATION_SNOWFLAKE_CCPA_PURGE_LOG`` row in ``General.ops.PipelineEventLog``
per invocation; canonical Metadata shape.

One SchemaContract row per Round 7 § 1.1.

Safety
------

* Idempotent — re-running is a no-op + audit row event_kind='noop'.
* ``--dry-run`` default per D75.
* D92 forward-only — NO DROP TABLE path.
* **Pre-flight check**: this migration verifies ``SnowflakeReplicationLog``
  exists before attempting CREATE (FK target must exist). Fails with clear
  error if dependency missing.

Execution classification
------------------------

* **Trigger**: Manual CLI
* **Frequency**: One-time per server (after ``migrations/snowflake_replication_log.py``)
* **Audit-row family**: ``MIGRATION_SNOWFLAKE_CCPA_PURGE_LOG``
* **Idempotency**: YES

Usage
-----

::

    # Prereq: migrations/snowflake_replication_log.py must have run first
    python3 migrations/snowflake_ccpa_purge_log.py --dry-run \\
        --actor pipeline-lead --justification "B-535 Phase 2 R1 dev pre-flight" \\
        --server dev

    python3 migrations/snowflake_ccpa_purge_log.py --apply \\
        --actor pipeline-lead --justification "B-535 Phase 2 R1 dev apply" \\
        --server dev
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import utils.configuration as config
from utils.connections import get_connection

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


MIGRATION_NAME = "MIGRATION_SNOWFLAKE_CCPA_PURGE_LOG"
TABLE_SCHEMA = "ops"
TABLE_NAME = "SnowflakeCcpaPurgeLog"
SOURCE_NAME = "General"
DEPENDENCY_TABLE = "SnowflakeReplicationLog"  # FK target; must exist first


TABLE_DDL = f"""
CREATE TABLE [{{db}}].{TABLE_SCHEMA}.{TABLE_NAME} (
    PurgeLogId                BIGINT IDENTITY(1,1) NOT NULL,
    ReplicationId             BIGINT          NOT NULL,
    CcpaDeletionLogId         BIGINT          NOT NULL,
    SnowflakeAction           NVARCHAR(50)    NOT NULL,
    SnowflakePurgedAt         DATETIME2(3)    NOT NULL
        CONSTRAINT DF_SnowflakeCcpaPurgeLog_SnowflakePurgedAt DEFAULT SYSUTCDATETIME(),
    AffectedIcebergRowCount   BIGINT          NULL,
    Actor                     NVARCHAR(255)   NOT NULL,
    Justification             NVARCHAR(MAX)   NULL,
    CONSTRAINT PK_SnowflakeCcpaPurgeLog PRIMARY KEY CLUSTERED (PurgeLogId),
    CONSTRAINT FK_SnowflakeCcpaPurgeLog_ReplicationId
        FOREIGN KEY (ReplicationId)
        REFERENCES [{{db}}].ops.SnowflakeReplicationLog(ReplicationId)
        ON DELETE NO ACTION ON UPDATE NO ACTION,
    CONSTRAINT FK_SnowflakeCcpaPurgeLog_CcpaDeletionLogId
        FOREIGN KEY (CcpaDeletionLogId)
        REFERENCES [{{db}}].ops.CcpaDeletionLog(DeletionLogId)
        ON DELETE NO ACTION ON UPDATE NO ACTION,
    CONSTRAINT CK_SnowflakeCcpaPurgeLog_Action
        CHECK (SnowflakeAction IN ('masking_policy_activated','deleted','row_access_policy_filtered'))
)
""".strip()


INDEX_REPLICATION_DDL = f"""
CREATE INDEX IX_SnowflakeCcpaPurgeLog_Replication
    ON [{{db}}].{TABLE_SCHEMA}.{TABLE_NAME} (ReplicationId)
""".strip()


INDEX_CCPA_DELETION_DDL = f"""
CREATE INDEX IX_SnowflakeCcpaPurgeLog_CcpaDeletion
    ON [{{db}}].{TABLE_SCHEMA}.{TABLE_NAME} (CcpaDeletionLogId)
""".strip()


class DependencyMissingError(RuntimeError):
    """Raised when SnowflakeReplicationLog (FK target) is not present."""


def _table_exists(cursor, db: str, schema: str, table: str) -> bool:
    cursor.execute(
        f"SELECT 1 FROM [{db}].INFORMATION_SCHEMA.TABLES "
        f"WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?",
        schema, table,
    )
    return cursor.fetchone() is not None


def _verify_dependency(cursor, db: str) -> None:
    """Pre-flight check: SnowflakeReplicationLog must exist before this migration runs.

    Raises ``DependencyMissingError`` if missing — operator must run
    ``migrations/snowflake_replication_log.py`` first.
    """
    if not _table_exists(cursor, db, TABLE_SCHEMA, DEPENDENCY_TABLE):
        raise DependencyMissingError(
            f"FK target [{db}].{TABLE_SCHEMA}.{DEPENDENCY_TABLE} does NOT exist. "
            f"Run `migrations/snowflake_replication_log.py --apply` first (B-523)."
        )


def _write_schema_contract_row(cursor, actor: str) -> None:
    cursor.execute(
        f"INSERT INTO [{config.GENERAL_DB}].ops.SchemaContract "
        f"(SourceName, ObjectName, ColumnName, ContractKey, ContractValue, "
        f" EffectiveFrom, CreatedBy, Notes) "
        f"VALUES (?, ?, NULL, ?, ?, SYSUTCDATETIME(), ?, ?)",
        SOURCE_NAME, TABLE_NAME, "expected_type", "TABLE",
        f"migration:{MIGRATION_NAME.lower()}",
        f"B-535 additive CREATE TABLE per D26 + D92 + user choice 2026-05-18 per v3 gap-check G6-4 (cleaner separation than SnowflakeReplicationLog Status enum extension).",
    )


def _write_audit_row(cursor, metadata: dict, actor: str, justification: str,
                     status: str = "SUCCESS", error_message: str | None = None) -> None:
    metadata_with_actor = dict(metadata)
    metadata_with_actor["actor"] = actor
    metadata_with_actor["justification"] = justification
    cursor.execute(
        f"INSERT INTO [{config.GENERAL_DB}].ops.PipelineEventLog "
        f"(BatchId, TableName, SourceName, EventType, EventDetail, "
        f" StartedAt, CompletedAt, Status, ErrorMessage, Metadata) "
        f"VALUES (NEXT VALUE FOR [{config.GENERAL_DB}].ops.PipelineBatchSequence, "
        f"        NULL, NULL, ?, ?, SYSUTCDATETIME(), SYSUTCDATETIME(), ?, ?, ?)",
        MIGRATION_NAME,
        f"B-535 snowflake ccpa purge log / server={metadata.get('server')}",
        status, error_message, json.dumps(metadata_with_actor),
    )


def apply(connection, *, actor: str, justification: str, server: str,
          dry_run: bool = False) -> dict:
    """Apply B-535 SnowflakeCcpaPurgeLog migration.

    Idempotent: re-running is a no-op. Verifies SnowflakeReplicationLog
    (FK target per B-523) exists before attempting CREATE.

    Preconditions: ``connection.autocommit=False``; ``SnowflakeReplicationLog``
    + ``CcpaDeletionLog`` MUST exist before this runs.

    Raises:
        DependencyMissingError: SnowflakeReplicationLog not present (operator
            must run ``migrations/snowflake_replication_log.py`` first).
    """
    cursor = connection.cursor()

    _verify_dependency(cursor, config.GENERAL_DB)

    table_present = _table_exists(cursor, config.GENERAL_DB, TABLE_SCHEMA, TABLE_NAME)
    needs_create = not table_present

    if dry_run:
        if needs_create:
            logger.info("[DRY RUN] Would execute: %s", TABLE_DDL.format(db=config.GENERAL_DB))
            logger.info("[DRY RUN] Would execute: %s", INDEX_REPLICATION_DDL.format(db=config.GENERAL_DB))
            logger.info("[DRY RUN] Would execute: %s", INDEX_CCPA_DELETION_DDL.format(db=config.GENERAL_DB))
        else:
            logger.info("[DRY RUN] Table [%s].%s.%s already present — would skip",
                        config.GENERAL_DB, TABLE_SCHEMA, TABLE_NAME)
        result = {
            "event_kind": "apply" if needs_create else "noop",
            "ddl_applied": False,
            "idempotency_path": "first" if needs_create else "no-op",
            "ddl_statements_executed": 0,
            "server": server,
            "table_created": False,
            "dry_run": True,
            "would_create_table": needs_create,
        }
        cursor.close()
        return result

    if not needs_create:
        metadata = {
            "event_kind": "noop",
            "ddl_applied": False,
            "idempotency_path": "no-op",
            "ddl_statements_executed": 0,
            "server": server,
            "table_created": False,
        }
        _write_audit_row(cursor, metadata, actor, justification)
        connection.commit()
        cursor.close()
        return metadata

    try:
        cursor.execute(TABLE_DDL.format(db=config.GENERAL_DB))
        cursor.execute(INDEX_REPLICATION_DDL.format(db=config.GENERAL_DB))
        cursor.execute(INDEX_CCPA_DELETION_DDL.format(db=config.GENERAL_DB))
        _write_schema_contract_row(cursor, actor)
        metadata = {
            "event_kind": "apply",
            "ddl_applied": True,
            "idempotency_path": "first",
            "ddl_statements_executed": 3,
            "server": server,
            "table_created": True,
        }
        _write_audit_row(cursor, metadata, actor, justification)
        connection.commit()
    except Exception as exc:
        connection.rollback()
        metadata = {
            "event_kind": "error",
            "ddl_applied": False,
            "idempotency_path": "first",
            "ddl_statements_executed": 0,
            "server": server,
            "table_created": False,
        }
        try:
            _write_audit_row(cursor, metadata, actor, justification,
                             status="FAILED", error_message=str(exc)[:4000])
            connection.commit()
        except Exception:
            pass
        cursor.close()
        raise
    cursor.close()
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description="B-535 SnowflakeCcpaPurgeLog migration")
    parser.add_argument("--apply", action="store_true", help="Execute DDL (default is dry-run per D75)")
    parser.add_argument("--actor", required=True, help="Auth principal (D75)")
    parser.add_argument("--justification", required=True, help="Why running (D75)")
    parser.add_argument("--server", required=True, choices=["dev", "test", "prod"],
                        help="Target server (D86 ladder)")
    args = parser.parse_args()

    dry_run = not args.apply
    conn = get_connection(config.GENERAL_DB)
    conn.autocommit = False
    try:
        result = apply(conn, actor=args.actor, justification=args.justification,
                       server=args.server, dry_run=dry_run)
    finally:
        conn.close()

    logger.info("B-535 migration result: %s", json.dumps(result, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
