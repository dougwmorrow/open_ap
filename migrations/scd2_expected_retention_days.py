"""SCD2 R-2: add ``ExpectedRetentionDays`` column to UdmTablesList.

Purpose
-------

Delete-close classification. When a row disappears from source, the pipeline
today stamps ``UdmSourceEndDate = batch business date`` and logs it as a
delete. That's fine for anomalous deletes (ACTV September incident style)
but creates alert noise on tables that get age-based purges by policy:

  * CCM.TransactionDetail  — 1,080 days (36 months)
  * CCM.StatementHistory   — 365 days (12 months)
  * CCM.AccessLog          — 60 days
  * CCM.AuditLog           — 1,095 days (36 months)
  * ...

When ``ExpectedRetentionDays`` is set on a table, the SCD2 engine classifies
each delete-close as either "within retention" (expected purge, INFO) or
"exceeds retention" (anomalous, WARNING). Classification only — no behavior
change. Bronze still keeps the closed row; UdmSourceEndDate still stamps the
batch date.

Defaults to NULL so tables without a policy behave identically to today.

Safety
------

* Idempotent — skips the ALTER when the column already exists.
* ``--dry-run`` previews the DDL without executing.
* Never touches row data. No backfill.

Usage
-----

    python3 migrations/scd2_expected_retention_days.py --dry-run
    python3 migrations/scd2_expected_retention_days.py
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


COLUMN_NAME = "ExpectedRetentionDays"
COLUMN_TYPE = "INT NULL"


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
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview DDL without executing.",
    )
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
