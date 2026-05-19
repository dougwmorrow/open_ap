"""B-523 — CREATE TABLE ``General.ops.SnowflakeReplicationLog`` (append-only audit witness).

Per D26 (append-only provenance) + D92 (forward-only additive) + D121 (Option B
core: SnowflakeReplicationLog is the audit witness for Snowflake-bound masked
parquet replications) + D123 (INSERT-first crash-safety pattern; ``Status``
transitions in_progress → replicated | failed) + D124 (deterministic stage
path includes ``ReplicationAttempt`` so retries don't collide).

Authored per ``docs/migration/PHASE2_LARGE_TABLES_AUDITLOG_PILOT_PLAN_2026-05-18.md``
§15.3 canonical DDL (v5; B-523 CRITICAL closure target Phase 2 R1).

Schema (per plan v5 §15.3)
--------------------------

* ``ReplicationId BIGINT IDENTITY(1,1) PRIMARY KEY`` — surrogate append-only PK
* ``RegistryId BIGINT NOT NULL`` FK → ``ParquetSnapshotRegistry(RegistryId)`` ON DELETE NO ACTION
* ``SnowflakeStagePath NVARCHAR(MAX) NOT NULL`` — per D124 deterministic format
* ``MaskedContentChecksum VARCHAR(64) NULL`` — SHA-256 of in-memory masked bytes per gap-check G6-1; NULL until STEP S9 UPDATE
* ``VaultTokenSnapshotMarker DATETIME2(3) NOT NULL`` — pre-tokenize SYSUTCDATETIME() round-trip per B-527
* ``RowsCopied INT NULL`` — from Snowflake COPY response per B-523 + Q1
* ``CopyHistoryId NVARCHAR(255) NULL`` — Snowflake QUERY_ID for COPY_HISTORY cross-ref per B-523
* ``SourceFilePurgedAt DATETIME2(3) NULL`` — set when registry row flips to 'purged' per B-523 + Q8
* ``ReplicatedAt DATETIME2(3) NOT NULL DEFAULT SYSUTCDATETIME()``
* ``ReplicationAttempt INT NOT NULL DEFAULT 1``
* ``Status NVARCHAR(20) NOT NULL`` with CHECK constraint
* ``ErrorMessage NVARCHAR(MAX) NULL``

Indexes
-------

* ``UX_SnowflakeReplicationLog_Identity`` UNIQUE on ``(RegistryId, ReplicationAttempt)`` — idempotency contract: retries get new attempt rows
* ``IX_SnowflakeReplicationLog_PendingRetry`` filtered ``WHERE Status IN ('in_progress','failed')`` per B-529

Constraints
-----------

* ``CK_SnowflakeReplicationLog_Status CHECK (Status IN ('replicated','failed','in_progress'))``

Audit trail
-----------

One ``MIGRATION_SNOWFLAKE_REPLICATION_LOG`` row in ``General.ops.PipelineEventLog``
per invocation with canonical Metadata shape ``{event_kind, ddl_applied,
idempotency_path, ddl_statements_executed, server, table_created}``.

One SchemaContract row per Round 7 § 1.1 (table-level ``ContractKey='expected_type'``
with ``ContractValue='TABLE'``).

Safety
------

* Idempotent — re-running on a server that already has the table writes
  ``event_kind='noop'`` audit row + no DDL.
* ``--dry-run`` default per D75 (no DDL, no audit row, no SchemaContract row).
* D92 forward-only — NO DROP TABLE path. Rollback via SchemaContract abandonment
  per Phase 2 R1 procedure.

Execution classification (per ``udm-execution-classifier``)
-----------------------------------------------------------

* **Trigger**: Manual CLI (operator runs the script directly per dev → test → prod ladder per D86)
* **Frequency**: One-time per server
* **Audit-row family**: ``MIGRATION_SNOWFLAKE_REPLICATION_LOG``
* **Idempotency**: YES — re-running is a no-op + audit row event_kind='noop'

Usage
-----

::

    python3 migrations/snowflake_replication_log.py --dry-run \\
        --actor pipeline-lead --justification "B-523 Phase 2 R1 dev pre-flight" \\
        --server dev

    python3 migrations/snowflake_replication_log.py --apply \\
        --actor pipeline-lead --justification "B-523 Phase 2 R1 dev apply" \\
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


MIGRATION_NAME = "MIGRATION_SNOWFLAKE_REPLICATION_LOG"
TABLE_SCHEMA = "ops"
TABLE_NAME = "SnowflakeReplicationLog"
SOURCE_NAME = "General"


TABLE_DDL = f"""
CREATE TABLE [{{db}}].{TABLE_SCHEMA}.{TABLE_NAME} (
    ReplicationId             BIGINT IDENTITY(1,1) NOT NULL,
    RegistryId                BIGINT          NOT NULL,
    SnowflakeStagePath        NVARCHAR(MAX)   NOT NULL,
    MaskedContentChecksum     VARCHAR(64)     NULL,
    VaultTokenSnapshotMarker  DATETIME2(3)    NOT NULL,
    RowsCopied                INT             NULL,
    CopyHistoryId             NVARCHAR(255)   NULL,
    SourceFilePurgedAt        DATETIME2(3)    NULL,
    ReplicatedAt              DATETIME2(3)    NOT NULL
        CONSTRAINT DF_SnowflakeReplicationLog_ReplicatedAt DEFAULT SYSUTCDATETIME(),
    ReplicationAttempt        INT             NOT NULL
        CONSTRAINT DF_SnowflakeReplicationLog_ReplicationAttempt DEFAULT 1,
    Status                    NVARCHAR(20)    NOT NULL,
    ErrorMessage              NVARCHAR(MAX)   NULL,
    CONSTRAINT PK_SnowflakeReplicationLog PRIMARY KEY CLUSTERED (ReplicationId),
    CONSTRAINT FK_SnowflakeReplicationLog_RegistryId
        FOREIGN KEY (RegistryId)
        REFERENCES [{{db}}].ops.ParquetSnapshotRegistry(RegistryId)
        ON DELETE NO ACTION ON UPDATE NO ACTION,
    CONSTRAINT CK_SnowflakeReplicationLog_Status
        CHECK (Status IN ('replicated','failed','in_progress'))
)
""".strip()


UNIQUE_INDEX_DDL = f"""
CREATE UNIQUE INDEX UX_SnowflakeReplicationLog_Identity
    ON [{{db}}].{TABLE_SCHEMA}.{TABLE_NAME} (RegistryId, ReplicationAttempt)
""".strip()


FILTERED_INDEX_DDL = f"""
CREATE INDEX IX_SnowflakeReplicationLog_PendingRetry
    ON [{{db}}].{TABLE_SCHEMA}.{TABLE_NAME} (ReplicatedAt)
    WHERE Status IN ('in_progress', 'failed')
""".strip()


def _table_exists(cursor, db: str, schema: str, table: str) -> bool:
    cursor.execute(
        f"SELECT 1 FROM [{db}].INFORMATION_SCHEMA.TABLES "
        f"WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?",
        schema, table,
    )
    return cursor.fetchone() is not None


def _write_schema_contract_row(cursor, actor: str) -> None:
    cursor.execute(
        f"INSERT INTO [{config.GENERAL_DB}].ops.SchemaContract "
        f"(SourceName, ObjectName, ColumnName, ContractKey, ContractValue, "
        f" EffectiveFrom, CreatedBy, Notes) "
        f"VALUES (?, ?, NULL, ?, ?, SYSUTCDATETIME(), ?, ?)",
        SOURCE_NAME, TABLE_NAME, "expected_type", "TABLE",
        f"migration:{MIGRATION_NAME.lower()}",
        f"B-523 additive CREATE TABLE per D26 + D92 forward-only; Option B Snowflake replication audit witness per D121 + D123.",
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
        f"B-523 snowflake replication log / server={metadata.get('server')}",
        status, error_message, json.dumps(metadata_with_actor),
    )


def apply(connection, *, actor: str, justification: str, server: str,
          dry_run: bool = False) -> dict:
    """Apply B-523 SnowflakeReplicationLog migration.

    Idempotent: re-running on a server that already has the table is a no-op.

    Preconditions: ``connection`` MUST have ``autocommit=False`` — ``apply()``
    controls transactions to bundle CREATE TABLE + 2 indexes + SchemaContract
    row + audit row into a single atomic transaction.
    """
    cursor = connection.cursor()
    table_present = _table_exists(cursor, config.GENERAL_DB, TABLE_SCHEMA, TABLE_NAME)
    needs_create = not table_present

    if dry_run:
        if needs_create:
            logger.info("[DRY RUN] Would execute: %s", TABLE_DDL.format(db=config.GENERAL_DB))
            logger.info("[DRY RUN] Would execute: %s", UNIQUE_INDEX_DDL.format(db=config.GENERAL_DB))
            logger.info("[DRY RUN] Would execute: %s", FILTERED_INDEX_DDL.format(db=config.GENERAL_DB))
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
        cursor.execute(UNIQUE_INDEX_DDL.format(db=config.GENERAL_DB))
        cursor.execute(FILTERED_INDEX_DDL.format(db=config.GENERAL_DB))
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
    parser = argparse.ArgumentParser(description="B-523 SnowflakeReplicationLog migration")
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

    logger.info("B-523 migration result: %s", json.dumps(result, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
