"""Add ``LastModifiedColumn`` to ``General.dbo.UdmTablesList`` for the
R-?? modified-date sweep.

Tier 2 of the large-table CDC strategy. Daily windowed extraction
(``SourceAggregateColumnName`` + ``LookbackDays``) catches changes that
fall inside the window. Any row updated outside the lookback window slips
through. The modified-date sweep periodically extracts only
``(PK, LastModifiedColumn)`` from source and compares against Bronze to
catch the drift.

Typical DNA convention: ``DATELASTMAINT``. NULL on tables without such a
column → sweep is skipped for that table.

Safety
------

* Idempotent — skips when the column already exists.
* ``--dry-run`` previews the DDL.
* No row data touched.

Usage
-----

    python3 migrations/scd2_last_modified_column.py --dry-run
    python3 migrations/scd2_last_modified_column.py
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


COLUMN_NAME = "LastModifiedColumn"
COLUMN_TYPE = "NVARCHAR(128) NULL"


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
        f"ADD [{COLUMN_NAME}] {COLUMN_TYPE}"
    )
    ok = _run_or_preview(config.GENERAL_DB, sql, args.dry_run)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
