"""B193 — ADD COLUMN ``LatenessL99Minutes`` + ``LatenessL99UpdatedAt`` to
``General.dbo.UdmTablesList``.

Per D63 + D92 forward-only additive ALTER pattern. Required for B188 Tool 14
(``measure_lateness.py``) which writes ``LatenessL99Minutes`` per-table for
D11 empirical L_99 baseline. Authored per phase2/01_pilot_prerequisites.md
§ 4.4 audit-row contract — every script invocation writes EXACTLY ONE row to
PipelineEventLog regardless of DDL no-op state.

Columns added
-------------

* ``LatenessL99Minutes INT NULL`` — empirical 99th-percentile lateness for the
  source table in minutes (per D11). NULL until Tool 14 first writes it.
* ``LatenessL99UpdatedAt DATETIME2(3) NULL`` — last write timestamp for the
  paired metric. NULL when ``LatenessL99Minutes`` is NULL.

Audit trail
-----------

* One ``MIGRATION_LATENESS_COLUMNS`` row in ``General.ops.PipelineEventLog``
  per invocation, with canonical Metadata JSON shape per § 4.4:
  ``{event_kind, ddl_applied, idempotency_path, ddl_statements_executed,
  server, columns_added}``.
* Two SchemaContract rows per added column (``expected_type`` + ``nullability``
  per Round 1 § 23 example rows L1228-1236; total 4 rows on first apply).

Safety
------

* Idempotent — every ALTER checks ``INFORMATION_SCHEMA.COLUMNS`` first; both
  ALTERs run inside a single transaction so partial application cannot leave
  one column added without the other.
* ``--dry-run`` previews DDL without executing; no audit row written, no
  SchemaContract row written.
* D92 forward-only — there is no DROP COLUMN path here. Rollback is the
  SchemaContract abandonment procedure per Phase 2 § 7 § 4.4 rollback row.

Usage
-----

::

    python3 migrations/lateness_columns.py --dry-run --actor pipeline-lead \\
        --justification "B193 Phase 2 R1 dev pre-flight" --server dev

    python3 migrations/lateness_columns.py --actor pipeline-lead \\
        --justification "B193 Phase 2 R1 dev apply" --server dev

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


MIGRATION_NAME = "MIGRATION_LATENESS_COLUMNS"
TABLE_SCHEMA = "dbo"
TABLE_NAME = "UdmTablesList"
SOURCE_NAME = "General"  # SchemaContract.SourceName for General.dbo.UdmTablesList

# (column_name, ddl_type_fragment, contract_expected_type, contract_nullability)
COLUMNS: list[tuple[str, str, str, str]] = [
    ("LatenessL99Minutes",   "INT NULL",           "INT",           "NULL"),
    ("LatenessL99UpdatedAt", "DATETIME2(3) NULL",  "DATETIME2(3)",  "NULL"),
]


def _column_exists(cursor, db: str, schema: str, table: str, column: str) -> bool:
    cursor.execute(
        f"SELECT 1 FROM [{db}].INFORMATION_SCHEMA.COLUMNS "
        f"WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? AND COLUMN_NAME = ?",
        schema, table, column,
    )
    return cursor.fetchone() is not None


def _write_schema_contract_rows(cursor, columns_added: list[str], actor: str) -> None:
    """Two rows per added column (expected_type + nullability) per Round 1 § 23."""
    for column_name in columns_added:
        spec = next(c for c in COLUMNS if c[0] == column_name)
        _, _, expected_type, nullability = spec
        cursor.execute(
            f"INSERT INTO [{config.GENERAL_DB}].ops.SchemaContract "
            f"(SourceName, ObjectName, ColumnName, ContractKey, ContractValue, "
            f" EffectiveFrom, CreatedBy, Notes) "
            f"VALUES (?, ?, ?, ?, ?, SYSUTCDATETIME(), ?, ?)",
            SOURCE_NAME, TABLE_NAME, column_name, "expected_type", expected_type,
            f"migration:{MIGRATION_NAME.lower()}",
            f"B193 additive ADD COLUMN per D63 + D92 forward-only.",
        )
        cursor.execute(
            f"INSERT INTO [{config.GENERAL_DB}].ops.SchemaContract "
            f"(SourceName, ObjectName, ColumnName, ContractKey, ContractValue, "
            f" EffectiveFrom, CreatedBy, Notes) "
            f"VALUES (?, ?, ?, ?, ?, SYSUTCDATETIME(), ?, ?)",
            SOURCE_NAME, TABLE_NAME, column_name, "nullability", nullability,
            f"migration:{MIGRATION_NAME.lower()}",
            f"B193 additive ADD COLUMN per D63 + D92 forward-only.",
        )


def _write_audit_row(cursor, metadata: dict, actor: str, justification: str,
                     status: str = "SUCCESS", error_message: str | None = None) -> None:
    """Write the single MIGRATION_LATENESS_COLUMNS row per § 4.4 audit-row contract.

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
        MIGRATION_NAME, f"B193 lateness columns / server={metadata.get('server')}",
        status, error_message, json.dumps(metadata_with_actor),
    )


def apply(connection, *, actor: str, justification: str, server: str,
          dry_run: bool = False) -> dict:
    """Apply B193 lateness-columns migration.

    Idempotent: re-running on a server that already has both columns is a
    no-op and still writes exactly one audit row with ``event_kind='noop'``.

    Returns Metadata JSON dict per § 4.4 canonical shape.

    Preconditions:
        - ``connection`` MUST have ``autocommit=False``; ``apply()`` controls
          transactions via explicit commit/rollback to bundle both ALTERs +
          SchemaContract rows + audit row into a single atomic transaction.
          The ``main()`` entry point sets this; direct callers (test harness,
          orchestrator) MUST do the same to prevent partial-state on failure.

    Partial-column-state behavior:
        - If only one of the two columns is absent (e.g., manual ADD or prior
          partial run), only the missing ALTER runs;
          ``ddl_statements_executed=1``, ``columns_added`` lists the single
          recovered column, and ``event_kind='apply'``. Intentional + safe
          for partial-state recovery (cycle-1 design review note 2026-05-12).
    """
    cursor = connection.cursor()
    columns_to_add: list[str] = []
    for column_name, _, _, _ in COLUMNS:
        if not _column_exists(cursor, config.GENERAL_DB, TABLE_SCHEMA, TABLE_NAME, column_name):
            columns_to_add.append(column_name)

    if dry_run:
        # Preview only: no DDL execution, no audit row, no SchemaContract row.
        for column_name, type_def, _, _ in COLUMNS:
            if column_name in columns_to_add:
                logger.info("[DRY RUN] Would execute: ALTER TABLE [%s].%s.%s ADD [%s] %s",
                            config.GENERAL_DB, TABLE_SCHEMA, TABLE_NAME, column_name, type_def)
            else:
                logger.info("[DRY RUN] Column [%s] already present — would skip", column_name)
        result = {
            "event_kind": "apply" if columns_to_add else "noop",
            "ddl_applied": False,
            # idempotency_path reflects what a REAL apply would produce per § 4.4 canonical shape:
            # would-be-first-apply (columns absent) → "first"; would-be-noop (columns present) → "no-op"
            # (cycle-1 design review 🔴 fix 2026-05-12)
            "idempotency_path": "first" if columns_to_add else "no-op",
            "ddl_statements_executed": 0,
            "server": server,
            "columns_added": [],
            "dry_run": True,
            "would_add_columns": columns_to_add,
        }
        cursor.close()
        return result

    if not columns_to_add:
        # True no-op: both columns already present.
        metadata = {
            "event_kind": "noop",
            "ddl_applied": False,
            "idempotency_path": "no-op",
            "ddl_statements_executed": 0,
            "server": server,
            "columns_added": [],
        }
        _write_audit_row(cursor, metadata, actor, justification)
        connection.commit()
        cursor.close()
        logger.info("[%s.%s.%s] All B193 columns already present — no-op (audit row written).",
                    config.GENERAL_DB, TABLE_SCHEMA, TABLE_NAME)
        return metadata

    # First-apply path: both ALTERs in a single transaction with SchemaContract rows
    # and audit row. autocommit must be False on the supplied connection.
    try:
        for column_name, type_def, _, _ in COLUMNS:
            if column_name in columns_to_add:
                sql = (
                    f"ALTER TABLE [{config.GENERAL_DB}].{TABLE_SCHEMA}.{TABLE_NAME} "
                    f"ADD [{column_name}] {type_def}"
                )
                logger.info("Executing: %s", sql)
                cursor.execute(sql)

        _write_schema_contract_rows(cursor, columns_to_add, actor)

        metadata = {
            "event_kind": "apply",
            "ddl_applied": True,
            "idempotency_path": "first",
            "ddl_statements_executed": len(columns_to_add),
            "server": server,
            "columns_added": list(columns_to_add),
        }
        _write_audit_row(cursor, metadata, actor, justification)
        connection.commit()
        cursor.close()
        logger.info("[%s.%s.%s] Added %d column(s): %s — audit row + %d SchemaContract row(s) written.",
                    config.GENERAL_DB, TABLE_SCHEMA, TABLE_NAME,
                    len(columns_to_add), columns_to_add, 2 * len(columns_to_add))
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
                "columns_added": [],
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
        logger.exception("Fatal error during B193 lateness-columns migration")
        return 2
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
