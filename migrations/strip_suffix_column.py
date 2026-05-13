"""Add ``StripSuffix`` BIT column to ``General.dbo.UdmTablesList``.

When ``StripSuffix = 1`` the pipeline drops the trailing ``_cdc`` /
``_scd2_python`` suffix from the resulting Stage / Bronze table names::

    StripSuffix = 0 (default, current behavior)
        UDM_Stage.{schema}.{StageTableName or SourceObjectName}_cdc
        UDM_Bronze.{schema}.{BronzeTableName or SourceObjectName}_scd2_python

    StripSuffix = 1 (opt-in, large tables migrating off the legacy pipeline)
        UDM_Stage.{schema}.{StageTableName or SourceObjectName}
        UDM_Bronze.{schema}.{BronzeTableName or SourceObjectName}

The schema (``ccm``, ``dna``, ``epicor``) already isolates Python-pipeline
tables from the legacy ``dbo.*`` SCD2 stored-proc tables, so the
``_cdc`` / ``_scd2_python`` markers were defense in depth — useful while
both pipelines coexist, redundant once consumers have migrated.

Per-table opt-in is the safe migration path: leave ``StripSuffix = 0``
on every existing row and turn it on only for tables operators have
explicitly migrated. The default-0 NOT NULL column populates every
existing row in one ALTER, no behavior change.

Safety
------

* Idempotent — skips the ALTER if the column already exists.
* ``--dry-run`` previews the DDL.
* No row data touched.
* UdmTablesList is small (a few hundred rows max); the ALTER is
  metadata-only on this table.

Usage
-----

::

    python3 migrations/strip_suffix_column.py --dry-run
    python3 migrations/strip_suffix_column.py
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import utils.configuration as config
from utils.connections import get_connection

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


COLUMN_NAME = "StripSuffix"
COLUMN_DEFINITION = "BIT NOT NULL CONSTRAINT DF_UdmTablesList_StripSuffix DEFAULT 0"


def _column_exists(db: str, schema: str, table: str, column: str) -> bool:
    conn = get_connection(db)
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT 1 FROM [{db}].INFORMATION_SCHEMA.COLUMNS "
            f"WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? AND COLUMN_NAME = ?",
            schema, table, column,
        )
        exists = cursor.fetchone() is not None
        cursor.close()
        return exists
    finally:
        conn.close()


def _run_or_preview(db: str, sql: str, dry_run: bool) -> bool:
    if dry_run:
        logger.info("[DRY RUN] [%s] %s", db, sql)
        return True
    conn = get_connection(db)
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        cursor.close()
        return True
    except Exception:
        logger.exception("Failed: %s", sql)
        return False
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="Preview DDL.")
    args = parser.parse_args()

    if _column_exists(config.GENERAL_DB, "dbo", "UdmTablesList", COLUMN_NAME):
        logger.info(
            "[%s.dbo.UdmTablesList] Column [%s] already exists — nothing to do.",
            config.GENERAL_DB, COLUMN_NAME,
        )
        return 0

    sql = (
        f"ALTER TABLE [{config.GENERAL_DB}].dbo.UdmTablesList "
        f"ADD [{COLUMN_NAME}] {COLUMN_DEFINITION}"
    )
    ok = _run_or_preview(config.GENERAL_DB, sql, args.dry_run)

    if ok and not args.dry_run:
        logger.info(
            "[%s.dbo.UdmTablesList] Column [%s] added with default 0 — "
            "every existing row preserved its current behavior. Set "
            "StripSuffix = 1 per-table to opt in to bare table names.",
            config.GENERAL_DB, COLUMN_NAME,
        )

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
