"""B195 — CREATE TABLE ``General.ops.CapacityBaselineLog`` (append-only).

Per D26 (append-only provenance) + D92 (forward-only additive) — required for
B190 Tool 16 (``tools/measure_capacity_and_partition.py``) which writes one row
per monthly Automic measurement (``JOB_CAPACITY_BASELINE``, frozen-13 inventory
per ``phase1/04b_phase_0_closure_tools.md`` § 6). Schema MUST match the Tool 16
``CapacityResult`` dataclass field-for-field per § 5 of that supplement; the
table also carries the standard append-only-log surrounding columns
(``BaselineId`` IDENTITY PK, ``BatchId`` FK linkage to PipelineEventLog,
``CreatedAt`` DEFAULT SYSUTCDATETIME(), ``CreatedBy`` DEFAULT SUSER_SNAME()).

Authored per ``phase2/01_pilot_prerequisites.md`` § 4.4 audit-row contract —
every script invocation writes EXACTLY ONE row to PipelineEventLog regardless
of DDL no-op state, with canonical Metadata JSON shape:
``{event_kind, ddl_applied, idempotency_path, ddl_statements_executed, server,
table_created}`` (the ``table_created`` boolean is this migration's
kind-specific field per § 4.4).

Schema (matches ``CapacityResult`` dataclass per § 5)
-----------------------------------------------------

* ``BaselineId BIGINT IDENTITY(1,1) PRIMARY KEY`` — surrogate append-only PK
* ``BatchId BIGINT NULL`` — links to PipelineEventLog.BatchId (NULL allowed
  for ad-hoc invocations that do not allocate from the sequence)
* ``SourceName NVARCHAR(50) NOT NULL`` — source registry (DNA / CCM / EPICOR)
* ``TableName NVARCHAR(255) NOT NULL`` — measured table
* ``CurrentRowCount BIGINT NOT NULL`` — point-in-time row count from source
* ``CurrentStorageMb BIGINT NOT NULL`` — current storage in MB
* ``GrowthRateRowsPerMonth BIGINT NOT NULL`` — rolling 12-month average
* ``ProjectedRows12Months BIGINT NOT NULL`` — D42 projection horizon (1y)
* ``ProjectedRows7Years BIGINT NOT NULL`` — D42 + D30 retention projection
* ``ProjectedStorageMb12Months BIGINT NOT NULL``
* ``ProjectedStorageMb7Years BIGINT NOT NULL``
* ``CurrentPartitionLayout NVARCHAR(255) NULL`` — NULL when ParquetDirectoryUnreachable per § 5 error mode
* ``AvgPartitionFileSizeMb DECIMAL(12,3) NULL`` — paired with above
* ``PartitionRecommendation NVARCHAR(MAX) NULL`` — human-readable narrative
* ``MeasuredAt DATETIME2(3) NOT NULL`` — Tool 16 measurement timestamp
* ``CreatedAt DATETIME2(3) NOT NULL DEFAULT SYSUTCDATETIME()`` — row write time
* ``CreatedBy NVARCHAR(255) NOT NULL DEFAULT SUSER_SNAME()`` — auth principal
* ``IX_CapacityBaselineLog_Table`` NONCLUSTERED (SourceName, TableName, MeasuredAt DESC)

Audit trail
-----------

* One ``MIGRATION_CAPACITY_BASELINE_LOG`` row in ``General.ops.PipelineEventLog``
  per invocation, with canonical Metadata JSON shape per § 4.4:
  ``{event_kind, ddl_applied, idempotency_path, ddl_statements_executed,
  server, table_created}``.
* One SchemaContract row per Round 7 § 1.1 (table-level
  ``ContractKey = 'expected_type'`` with ``ContractValue = 'TABLE'`` per
  Round 1 § 23 L1192 — ``ColumnName IS NULL`` indicates table-level contract).

Safety
------

* Idempotent — ``IF NOT EXISTS`` guard on the CREATE TABLE; full DDL (table +
  index) runs inside a single transaction so partial application cannot leave
  the table without its operational index.
* ``--dry-run`` previews DDL without executing; no audit row written, no
  SchemaContract row written.
* D92 forward-only — NO DROP TABLE path. Rollback is the SchemaContract
  abandonment procedure per Phase 2 § 7 § 4.4 rollback row.

Execution classification (per ``udm-execution-classifier``)
-----------------------------------------------------------

* **Trigger**: Manual CLI (operator runs the script directly)
* **Frequency**: One-time per server (dev → test → prod ladder per D86)
* **Audit-row family**: ``MIGRATION_CAPACITY_BASELINE_LOG``
* **Idempotency**: Re-running on a server that already has the table is a
  no-op; one audit row still writes with ``event_kind='noop'``.

Usage
-----

::

    python3 migrations/capacity_baseline_log.py --dry-run --actor pipeline-lead \\
        --justification "B195 Phase 2 R1 dev pre-flight" --server dev

    python3 migrations/capacity_baseline_log.py --actor pipeline-lead \\
        --justification "B195 Phase 2 R1 dev apply" --server dev

Exit codes (per D74)
--------------------

* 0 — clean (apply OR no-op OR dry-run preview)
* 1 — drift / warning (operational failure surfaced but not fatal)
* 2 — fatal error (DDL failure, connection failure)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import utils.configuration as config
from utils.connections import get_connection

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


MIGRATION_NAME = "MIGRATION_CAPACITY_BASELINE_LOG"
TABLE_SCHEMA = "ops"
TABLE_NAME = "CapacityBaselineLog"
SOURCE_NAME = "General"  # SchemaContract.SourceName for General.ops.CapacityBaselineLog

# Full table DDL — schema columns mirror CapacityResult dataclass per
# phase1/04b § 5 (str → NVARCHAR; int → BIGINT; float → DECIMAL(12,3);
# datetime → DATETIME2(3); bool → BIT n/a here). Nullability per § 5 error
# modes: CurrentPartitionLayout + AvgPartitionFileSizeMb + PartitionRecommendation
# are NULLable because ParquetDirectoryUnreachable returns NULL for those.
TABLE_DDL = f"""
CREATE TABLE [{{db}}].{TABLE_SCHEMA}.{TABLE_NAME} (
    BaselineId                   BIGINT IDENTITY(1,1) NOT NULL,
    BatchId                      BIGINT          NULL,
    SourceName                   NVARCHAR(50)    NOT NULL,
    TableName                    NVARCHAR(255)   NOT NULL,
    CurrentRowCount              BIGINT          NOT NULL,
    CurrentStorageMb             BIGINT          NOT NULL,
    GrowthRateRowsPerMonth       BIGINT          NOT NULL,
    ProjectedRows12Months        BIGINT          NOT NULL,
    ProjectedRows7Years          BIGINT          NOT NULL,
    ProjectedStorageMb12Months   BIGINT          NOT NULL,
    ProjectedStorageMb7Years     BIGINT          NOT NULL,
    CurrentPartitionLayout       NVARCHAR(255)   NULL,
    AvgPartitionFileSizeMb       DECIMAL(12,3)   NULL,
    PartitionRecommendation      NVARCHAR(MAX)   NULL,
    MeasuredAt                   DATETIME2(3)    NOT NULL,
    CreatedAt                    DATETIME2(3)    NOT NULL
        CONSTRAINT DF_CapacityBaselineLog_CreatedAt DEFAULT SYSUTCDATETIME(),
    CreatedBy                    NVARCHAR(255)   NOT NULL
        CONSTRAINT DF_CapacityBaselineLog_CreatedBy DEFAULT SUSER_SNAME(),
    CONSTRAINT PK_CapacityBaselineLog PRIMARY KEY CLUSTERED (BaselineId)
)
""".strip()

INDEX_DDL = f"""
CREATE NONCLUSTERED INDEX IX_CapacityBaselineLog_Table
    ON [{{db}}].{TABLE_SCHEMA}.{TABLE_NAME} (SourceName, TableName, MeasuredAt DESC)
""".strip()


def _table_exists(cursor, db: str, schema: str, table: str) -> bool:
    cursor.execute(
        f"SELECT 1 FROM [{db}].INFORMATION_SCHEMA.TABLES "
        f"WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?",
        schema, table,
    )
    return cursor.fetchone() is not None


def _write_schema_contract_row(cursor, actor: str) -> None:
    """One row per Round 7 § 1.1 — table-level contract (``ColumnName IS NULL``).

    Per Round 1 § 23 L1192 the ``ColumnName`` column is NULL when the contract
    is table-level (matches L1236 example row). ContractKey ``'expected_type'``
    with ContractValue ``'TABLE'`` formalizes the additive table creation
    against the SchemaContract supersession protocol.
    """
    cursor.execute(
        f"INSERT INTO [{config.GENERAL_DB}].ops.SchemaContract "
        f"(SourceName, ObjectName, ColumnName, ContractKey, ContractValue, "
        f" EffectiveFrom, CreatedBy, Notes) "
        f"VALUES (?, ?, NULL, ?, ?, SYSUTCDATETIME(), ?, ?)",
        SOURCE_NAME, TABLE_NAME, "expected_type", "TABLE",
        f"migration:{MIGRATION_NAME.lower()}",
        f"B195 additive CREATE TABLE per D26 + D92 forward-only.",
    )


def _write_audit_row(cursor, metadata: dict, actor: str, justification: str,
                     status: str = "SUCCESS", error_message: str | None = None) -> None:
    """Write the single MIGRATION_CAPACITY_BASELINE_LOG row per § 4.4 audit-row contract.

    BatchId is allocated from ``General.ops.PipelineBatchSequence`` per D45.3 —
    migration runs are pipeline-wide events so TableName + SourceName are NULL.
    """
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
        f"B195 capacity baseline log / server={metadata.get('server')}",
        status, error_message, json.dumps(metadata_with_actor),
    )


def apply(connection, *, actor: str, justification: str, server: str,
          dry_run: bool = False) -> dict:
    """Apply B195 CapacityBaselineLog migration.

    Idempotent: re-running on a server that already has the table is a no-op
    and still writes exactly one audit row with ``event_kind='noop'``.

    Returns Metadata JSON dict per § 4.4 canonical shape with the
    migration-specific field ``table_created: bool``.

    Preconditions:
        - ``connection`` MUST have ``autocommit=False``; ``apply()`` controls
          transactions via explicit commit/rollback to bundle CREATE TABLE +
          CREATE INDEX + SchemaContract row + audit row into a single atomic
          transaction. The ``main()`` entry point sets this; direct callers
          (test harness, orchestrator) MUST do the same to prevent
          partial-state on failure.

    Partial-state behavior:
        - This migration creates ONE table; ``IF NOT EXISTS`` makes the
          whole-DDL guard binary. There is no per-column partial-state path
          analogous to B193 (B193's two ALTERs could each independently
          succeed/fail across runs). If a prior run created the table but
          failed before the audit row was written, re-running this migration
          treats it as a no-op (table exists) and emits a fresh audit row
          with ``event_kind='noop'`` — the original failure is detectable in
          PipelineEventLog history via the absence of a prior SUCCESS row.
    """
    cursor = connection.cursor()
    table_present = _table_exists(cursor, config.GENERAL_DB, TABLE_SCHEMA, TABLE_NAME)
    needs_create = not table_present

    if dry_run:
        # Preview only: no DDL execution, no audit row, no SchemaContract row.
        if needs_create:
            logger.info("[DRY RUN] Would execute: %s", TABLE_DDL.format(db=config.GENERAL_DB))
            logger.info("[DRY RUN] Would execute: %s", INDEX_DDL.format(db=config.GENERAL_DB))
        else:
            logger.info("[DRY RUN] Table [%s].%s.%s already present — would skip",
                        config.GENERAL_DB, TABLE_SCHEMA, TABLE_NAME)
        result = {
            "event_kind": "apply" if needs_create else "noop",
            "ddl_applied": False,
            # idempotency_path reflects what a REAL apply would produce per § 4.4
            # canonical shape: would-be-first-apply (table absent) → "first";
            # would-be-noop (table present) → "no-op".
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
        # True no-op: table already present.
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
        logger.info("[%s].%s.%s already present — no-op (audit row written).",
                    config.GENERAL_DB, TABLE_SCHEMA, TABLE_NAME)
        return metadata

    # First-apply path: CREATE TABLE + CREATE INDEX + SchemaContract row + audit
    # row in a single transaction. autocommit must be False on the supplied
    # connection.
    try:
        table_sql = TABLE_DDL.format(db=config.GENERAL_DB)
        index_sql = INDEX_DDL.format(db=config.GENERAL_DB)
        logger.info("Executing: %s", table_sql)
        cursor.execute(table_sql)
        logger.info("Executing: %s", index_sql)
        cursor.execute(index_sql)

        _write_schema_contract_row(cursor, actor)

        metadata = {
            "event_kind": "apply",
            "ddl_applied": True,
            "idempotency_path": "first",
            "ddl_statements_executed": 2,  # CREATE TABLE + CREATE INDEX
            "server": server,
            "table_created": True,
        }
        _write_audit_row(cursor, metadata, actor, justification)
        connection.commit()
        cursor.close()
        logger.info("[%s].%s.%s created with index IX_CapacityBaselineLog_Table — "
                    "audit row + 1 SchemaContract row written.",
                    config.GENERAL_DB, TABLE_SCHEMA, TABLE_NAME)
        return metadata
    except Exception:
        connection.rollback()
        # Try to record the failure as a separate audit row on a fresh cursor.
        # Best-effort: if this also fails, the original exception still propagates.
        try:
            err_cursor = connection.cursor()
            failed_metadata = {
                "event_kind": "apply",
                "ddl_applied": False,
                "idempotency_path": None,
                "ddl_statements_executed": 0,
                "server": server,
                "table_created": False,
            }
            _write_audit_row(err_cursor, failed_metadata, actor, justification,
                             status="FAILED", error_message=traceback.format_exc()[:4000])
            connection.commit()
            err_cursor.close()
        except Exception:
            logger.exception("Failed to write FAILED audit row after migration failure")
        logger.exception("Migration failed; transaction rolled back.")
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="Preview DDL without executing.")
    parser.add_argument("--actor", required=True,
                        help="Operator running the migration (per D75); written to audit row.")
    parser.add_argument("--justification", required=True,
                        help="Operator justification for the migration (per D75); written to audit row.")
    parser.add_argument("--server", required=True,
                        help="Target server tag (e.g. dev / test / prod) per D75 + § 4.4 server key.")
    args = parser.parse_args()

    conn = None
    try:
        conn = get_connection(config.GENERAL_DB)
        try:
            conn.autocommit = False
        except Exception:
            logger.warning("Connection autocommit attribute not settable; relying on explicit commit/rollback.")

        result = apply(conn, actor=args.actor, justification=args.justification,
                       server=args.server, dry_run=args.dry_run)
        logger.info("Result: %s", json.dumps(result))
        return 0
    except Exception:
        logger.exception("Fatal error during B195 capacity-baseline-log migration")
        return 2
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
