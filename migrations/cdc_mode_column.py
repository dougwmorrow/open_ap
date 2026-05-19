"""B-542 — ALTER ``General.dbo.UdmTablesList`` ADD COLUMN ``CDCMode`` per D63 + D125.

Per D63 (6-column UdmTablesList extension; locked Round 1.5) + D125 (3-value
CDCMode enum extension for dual-execute shadow-write safety; proposed
2026-05-19 in ``docs/migration/UDM_PIPELINE_CDC_MODE_3WAY_DISPATCH_PLAN_2026-05-19.md``)
+ D92 (forward-only-additive schema evolution discipline) + D34 (greenfield
posture; idempotent ``IF NOT EXISTS`` guards).

**B-542 closure context**: D63 referenced this migration script at
``02_PHASES.md`` L95 since Round 6 R2 (~2026-05-09) but the script was NEVER
BUILT. Verified missing 2026-05-19 via ``git show HEAD:migrations/cdc_mode_column.py``
returning "fatal: path does not exist". This script closes the implementation
gap with 3-value CHECK constraint from day 1 (D125 + D63 combined).

Schema additions per D63 + D125
-------------------------------

* ``CDCMode NVARCHAR(20) NOT NULL DEFAULT 'change_detect'`` (named constraint
  ``DF_UdmTablesList_CDCMode``) — per-table CDC mode dispatch flag
* CHECK constraint ``CK_UdmTablesList_CDCMode`` per D125 3-value extension:
  ``CHECK (CDCMode IN ('change_detect', 'parquet_snapshot', 'both'))``

Audit trail
-----------

One ``MIGRATION_CDC_MODE_COLUMN`` row in ``General.ops.PipelineEventLog`` per
invocation with canonical Metadata shape ``{event_kind, ddl_applied,
idempotency_path, ddl_statements_executed, server, column_added,
constraint_added}``.

Two SchemaContract rows per Round 7 § 1.1:

* Column-level: ``ContractKey='expected_default'``, ``ContractValue='change_detect'``
* Constraint-level: ``ContractKey='expected_check'``,
  ``ContractValue='CDCMode IN (''change_detect'', ''parquet_snapshot'', ''both'')'``

Safety
------

* Idempotent (D15) — re-running checks ``sys.columns`` for CDCMode + ``sys.check_constraints``
  for ``CK_UdmTablesList_CDCMode``; emits ``event_kind='noop'`` audit row + no DDL
* ``--dry-run`` default per D75 (no DDL, no audit row, no SchemaContract rows)
* D92 forward-only — NO DROP COLUMN / DROP CONSTRAINT path
* Existing UdmTablesList rows get the DEFAULT value at ALTER ADD time per SQL
  Server semantics (DEFAULT propagates to existing rows when NOT NULL column added)

Execution classification (per ``udm-execution-classifier``)
-----------------------------------------------------------

* **Trigger**: Manual CLI (operator runs the script directly per dev → test → prod ladder per D86)
* **Frequency**: One-time per server
* **Audit-row family**: ``MIGRATION_CDC_MODE_COLUMN`` (registered per CLAUDE.md L209+ family registry)
* **Idempotency**: YES — re-running is a no-op + audit row event_kind='noop'

Usage
-----

::

    python3 migrations/cdc_mode_column.py --dry-run \\
        --actor pipeline-lead --justification "B-542 D63+D125 dev pre-flight" \\
        --server dev

    python3 migrations/cdc_mode_column.py --apply \\
        --actor pipeline-lead --justification "B-542 D63+D125 dev apply" \\
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


MIGRATION_NAME = "MIGRATION_CDC_MODE_COLUMN"
TABLE_SCHEMA = "dbo"
TABLE_NAME = "UdmTablesList"
COLUMN_NAME = "CDCMode"
DEFAULT_CONSTRAINT_NAME = "DF_UdmTablesList_CDCMode"
CHECK_CONSTRAINT_NAME = "CK_UdmTablesList_CDCMode"
SOURCE_NAME = "General"

# D63 + D125 canonical values — 3-value enum from day 1 per D125 extension
ALLOWED_CDC_MODE_VALUES = ("change_detect", "parquet_snapshot", "both")
DEFAULT_CDC_MODE_VALUE = "change_detect"


# Column ADD with named DEFAULT constraint per D63 § 1.3 pattern.
# Uses {db} placeholder for cross-environment dev/test/prod parametrization.
COLUMN_ADD_DDL = f"""
ALTER TABLE [{{db}}].{TABLE_SCHEMA}.{TABLE_NAME}
    ADD {COLUMN_NAME} NVARCHAR(20) NOT NULL
        CONSTRAINT {DEFAULT_CONSTRAINT_NAME} DEFAULT '{DEFAULT_CDC_MODE_VALUE}'
""".strip()


# CHECK constraint per D125 3-value extension (canonical from day 1).
# Note: SQL Server CHECK constraint definition requires quoted values inline.
CHECK_CONSTRAINT_DDL = f"""
ALTER TABLE [{{db}}].{TABLE_SCHEMA}.{TABLE_NAME}
    ADD CONSTRAINT {CHECK_CONSTRAINT_NAME}
        CHECK ({COLUMN_NAME} IN ('change_detect', 'parquet_snapshot', 'both'))
""".strip()


def _column_exists(cursor, db: str, schema: str, table: str, column: str) -> bool:
    cursor.execute(
        f"SELECT 1 FROM [{db}].INFORMATION_SCHEMA.COLUMNS "
        f"WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? AND COLUMN_NAME = ?",
        schema, table, column,
    )
    return cursor.fetchone() is not None


def _check_constraint_exists(cursor, db: str, name: str) -> bool:
    cursor.execute(
        f"SELECT 1 FROM [{db}].sys.check_constraints WHERE name = ?",
        name,
    )
    return cursor.fetchone() is not None


def _write_schema_contract_rows(cursor, actor: str) -> None:
    """Write 2 SchemaContract rows: column-level + constraint-level."""

    # Column-level: expected DEFAULT value
    cursor.execute(
        f"INSERT INTO [{config.GENERAL_DB}].ops.SchemaContract "
        f"(SourceName, ObjectName, ColumnName, ContractKey, ContractValue, "
        f" EffectiveFrom, CreatedBy, Notes) "
        f"VALUES (?, ?, ?, ?, ?, SYSUTCDATETIME(), ?, ?)",
        SOURCE_NAME, TABLE_NAME, COLUMN_NAME, "expected_default",
        DEFAULT_CDC_MODE_VALUE,
        f"migration:{MIGRATION_NAME.lower()}",
        "B-542 D63+D125 additive ALTER ADD COLUMN; CDCMode 3-value enum dispatch.",
    )

    # Constraint-level: expected CHECK constraint values
    cursor.execute(
        f"INSERT INTO [{config.GENERAL_DB}].ops.SchemaContract "
        f"(SourceName, ObjectName, ColumnName, ContractKey, ContractValue, "
        f" EffectiveFrom, CreatedBy, Notes) "
        f"VALUES (?, ?, ?, ?, ?, SYSUTCDATETIME(), ?, ?)",
        SOURCE_NAME, TABLE_NAME, COLUMN_NAME, "expected_check",
        "CDCMode IN ('change_detect', 'parquet_snapshot', 'both')",
        f"migration:{MIGRATION_NAME.lower()}",
        "B-542 D125 3-value extension; future sub-variants additive per D92.",
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
        f"B-542 CDCMode column / server={metadata.get('server')}",
        status, error_message, json.dumps(metadata_with_actor),
    )


def apply(connection, *, actor: str, justification: str, server: str,
          dry_run: bool = False) -> dict:
    """Apply B-542 CDCMode column migration (D63 + D125).

    Idempotent: re-running on a server that already has CDCMode column +
    CHECK constraint is a no-op.

    Preconditions: ``connection`` MUST have ``autocommit=False`` — ``apply()``
    controls transactions to bundle ALTER ADD COLUMN + ADD CONSTRAINT +
    SchemaContract rows + audit row into a single atomic transaction.
    """
    cursor = connection.cursor()
    column_present = _column_exists(
        cursor, config.GENERAL_DB, TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME,
    )
    check_present = _check_constraint_exists(
        cursor, config.GENERAL_DB, CHECK_CONSTRAINT_NAME,
    )
    needs_column = not column_present
    needs_check = not check_present

    if dry_run:
        if needs_column:
            logger.info("[DRY RUN] Would execute: %s", COLUMN_ADD_DDL.format(db=config.GENERAL_DB))
        else:
            logger.info("[DRY RUN] Column [%s].%s.%s.%s already present — would skip ADD COLUMN",
                        config.GENERAL_DB, TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME)
        if needs_check:
            logger.info("[DRY RUN] Would execute: %s", CHECK_CONSTRAINT_DDL.format(db=config.GENERAL_DB))
        else:
            logger.info("[DRY RUN] Check constraint %s already present — would skip ADD CONSTRAINT",
                        CHECK_CONSTRAINT_NAME)
        result = {
            "event_kind": "apply" if (needs_column or needs_check) else "noop",
            "ddl_applied": False,
            "idempotency_path": "first" if needs_column else (
                "partial" if needs_check else "no-op"
            ),
            "ddl_statements_executed": 0,
            "server": server,
            "column_added": False,
            "constraint_added": False,
            "dry_run": True,
            "would_add_column": needs_column,
            "would_add_constraint": needs_check,
        }
        cursor.close()
        return result

    if not needs_column and not needs_check:
        metadata = {
            "event_kind": "noop",
            "ddl_applied": False,
            "idempotency_path": "no-op",
            "ddl_statements_executed": 0,
            "server": server,
            "column_added": False,
            "constraint_added": False,
        }
        _write_audit_row(cursor, metadata, actor, justification)
        connection.commit()
        cursor.close()
        return metadata

    statements_executed = 0
    column_added = False
    constraint_added = False
    try:
        if needs_column:
            cursor.execute(COLUMN_ADD_DDL.format(db=config.GENERAL_DB))
            statements_executed += 1
            column_added = True
        if needs_check:
            cursor.execute(CHECK_CONSTRAINT_DDL.format(db=config.GENERAL_DB))
            statements_executed += 1
            constraint_added = True

        # SchemaContract rows only written when column was newly added (first-time);
        # partial-recovery runs (column exists, constraint missing) don't re-write contract.
        idempotency_path = (
            "first" if (column_added and constraint_added)
            else "partial-recovery"
        )
        if column_added:
            _write_schema_contract_rows(cursor, actor)

        metadata = {
            "event_kind": "apply",
            "ddl_applied": True,
            "idempotency_path": idempotency_path,
            "ddl_statements_executed": statements_executed,
            "server": server,
            "column_added": column_added,
            "constraint_added": constraint_added,
        }
        _write_audit_row(cursor, metadata, actor, justification)
        connection.commit()
    except Exception as exc:
        connection.rollback()
        metadata = {
            "event_kind": "error",
            "ddl_applied": False,
            "idempotency_path": "first" if needs_column else "partial-recovery",
            "ddl_statements_executed": statements_executed,
            "server": server,
            "column_added": False,
            "constraint_added": False,
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
    parser = argparse.ArgumentParser(description="B-542 CDCMode column migration (D63+D125)")
    parser.add_argument("--apply", action="store_true",
                        help="Execute DDL (default is dry-run per D75)")
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
        logger.info("Migration result: %s", json.dumps(result, indent=2))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
