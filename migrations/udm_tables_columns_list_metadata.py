"""Ensure ``UdmTablesColumnsList`` carries the metadata columns the
column-sync writer expects.

Adds three columns idempotently when missing:

  * ``ObjectType``           VARCHAR(20)   NULL  — 'TABLE' / 'VIEW' from source
  * ``DatabaseName``         VARCHAR(255)  NULL  — source database name
  * ``MetadataLastUpdated``  DATETIME2(7)  NULL  — sync timestamp

``schema/column_sync.py`` populates these on every column-sync run.
Operators get a self-describing audit trail (which DB, which object type,
how stale) without having to query system catalogs.

Idempotent — skips columns already present. ``--dry-run`` previews.

Usage::

    python3 migrations/udm_tables_columns_list_metadata.py --dry-run
    python3 migrations/udm_tables_columns_list_metadata.py
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


COLUMNS: list[tuple[str, str]] = [
    ("ObjectType", "VARCHAR(20) NULL"),
    ("DatabaseName", "VARCHAR(255) NULL"),
    ("MetadataLastUpdated", "DATETIME2(7) NULL"),
]


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

    added = 0
    skipped = 0
    for column, type_def in COLUMNS:
        if _column_exists(config.GENERAL_DB, "dbo", "UdmTablesColumnsList", column):
            logger.info(
                "[%s.dbo.UdmTablesColumnsList] Column [%s] already exists — skipping",
                config.GENERAL_DB, column,
            )
            skipped += 1
            continue
        sql = (
            f"ALTER TABLE [{config.GENERAL_DB}].dbo.UdmTablesColumnsList "
            f"ADD [{column}] {type_def}"
        )
        if _run_or_preview(config.GENERAL_DB, sql, args.dry_run):
            added += 1

    logger.info(
        "UdmTablesColumnsList: %d columns %s, %d already present",
        added, "previewed" if args.dry_run else "added", skipped,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
