"""SCD2 Phase 1 Migration: configuration columns + source-date pair + sentinel.

One-time schema migration to support the SCD2 engine temporal-integrity upgrade
described in ``todos/scd2_engine_enhancement_requirements.md``. Authored for
later execution — review and run during a maintenance window BEFORE deploying
the Phase 1 code changes.

Design note — preserve the UdmEffectiveDateTime / UdmEndDateTime contract
-------------------------------------------------------------------------

Silver and Gold tables in the medallion architecture consume Bronze's
``UdmEffectiveDateTime`` as the *load timestamp* (when a row arrived in UDM).
Changing its semantic would break downstream watermarking (e.g. ``WHERE
UdmEffectiveDateTime > last_processed``) and is a silent data-skip hazard for
historical backfills. Phase 1 therefore leaves the existing pair untouched:

* ``UdmEffectiveDateTime`` — load timestamp at insert. Unchanged.
* ``UdmEndDateTime``       — NULL while active; load timestamp at close. Unchanged.

All business-date semantics from the requirements doc (R-1, R-3) move onto a
NEW pair of columns added by this migration:

* ``UdmSourceBeginDate DATETIME2(3)`` — source business date for the row.
  ``target_date`` for large (windowed) tables; ``_extracted_at`` for small
  tables (falls back to ``UdmEffectiveDateTime`` when no source date exists).
* ``UdmSourceEndDate   DATETIME2(3)`` — business chain end. Active rows carry
  the sentinel ``'2999-12-31'`` so point-in-time queries can use
  ``WHERE @d BETWEEN UdmSourceBeginDate AND UdmSourceEndDate`` without special
  NULL handling. NULL on this column is reserved for in-flight inserts
  (Flag=0, operation U/R, not yet activated).

Changes applied
---------------

1. ``General.dbo.UdmTablesList`` — add R-9.2 configuration columns. All are
   nullable with defaults chosen so existing tables keep their current
   behavior (``SCD2Mode = 'incremental'``, no date columns configured).

2. Every Bronze SCD2 table in ``UDM_Bronze`` — add ``UdmSourceBeginDate`` and
   ``UdmSourceEndDate`` (both ``DATETIME2(3)`` for millisecond precision).

3. Every Bronze SCD2 table in ``UDM_Bronze`` — backfill
   ``UdmSourceEndDate = '2999-12-31'`` for active rows (``UdmActiveFlag = 1``).
   ``UdmSourceBeginDate`` is left NULL on existing rows; the first CDC/SCD2
   run after deployment will populate it for new versions going forward.
   Historical ``UdmSourceBeginDate`` backfill (from ``UdmEffectiveDateTime``)
   is NOT attempted here — load time is an approximation of business date
   only, and we prefer explicit NULLs to silently-incorrect values.

Safety
------

* ``--dry-run`` prints every DDL/DML statement without executing it.
* Idempotent — ALTER ADD checks for existing columns first; UPDATE filters
  ``UdmSourceEndDate IS NULL AND UdmActiveFlag = 1`` so re-running is a no-op.
* ``UdmEffectiveDateTime`` and ``UdmEndDateTime`` are NEVER touched.

Usage
-----

    python3 scd2_phase1_config.py --dry-run
    python3 scd2_phase1_config.py
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Add parent directory for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import utils.configuration as configuration
from utils.connections import get_connection, get_general_connection, quote_table

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# R-9.2: UdmTablesList configuration columns
# ---------------------------------------------------------------------------

# Column name -> ALTER fragment (sans table prefix).
# Defaults preserve current behavior: everything is 'incremental' with no
# temporal date columns configured.
UDM_TABLES_LIST_COLUMNS: list[tuple[str, str]] = [
    ("SCD2Mode",                 "VARCHAR(20) NULL CONSTRAINT DF_UdmTablesList_SCD2Mode DEFAULT 'incremental'"),
    ("SCD2DateColumns",          "NVARCHAR(500) NULL"),
    ("SourceDeleteDateColumn",   "NVARCHAR(128) NULL"),
    ("DuplicateResolutionOrder", "NVARCHAR(500) NULL"),
    ("AllowDuplicates",          "BIT NULL CONSTRAINT DF_UdmTablesList_AllowDuplicates DEFAULT 0"),
    ("PreserveDateTime",         "BIT NULL CONSTRAINT DF_UdmTablesList_PreserveDateTime DEFAULT 0"),
    ("RepairChainAfter",         "BIT NULL CONSTRAINT DF_UdmTablesList_RepairChainAfter DEFAULT 1"),
    ("AllowGaps",                "BIT NULL CONSTRAINT DF_UdmTablesList_AllowGaps DEFAULT 0"),
    ("ExcludeFromHash",          "NVARCHAR(MAX) NULL"),
    ("DefaultBeginDate",         "DATETIME NULL"),
    ("ForceNewSegmentColumns",   "NVARCHAR(500) NULL"),
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


def migrate_udm_tables_list(dry_run: bool) -> tuple[int, int]:
    """Add R-9.2 configuration columns to General.dbo.UdmTablesList."""
    logger.info("--- Step 1: General.dbo.UdmTablesList configuration columns ---")

    added = 0
    skipped = 0
    for column, type_def in UDM_TABLES_LIST_COLUMNS:
        if _column_exists(configuration.GENERAL_DB, "dbo", "UdmTablesList", column):
            logger.info("[%s.dbo.UdmTablesList] Column [%s] already exists — skipping",
                        configuration.GENERAL_DB, column)
            skipped += 1
            continue

        sql = (
            f"ALTER TABLE [{configuration.GENERAL_DB}].dbo.UdmTablesList "
            f"ADD [{column}] {type_def}"
        )
        if _run_or_preview(configuration.GENERAL_DB, sql, dry_run):
            added += 1

    logger.info("UdmTablesList: %d columns %s, %d already present",
                added, "previewed" if dry_run else "added", skipped)
    return added, skipped


# ---------------------------------------------------------------------------
# R-1/R-3: UdmSourceBeginDate + UdmSourceEndDate on every Bronze SCD2 table
# R-3.3:   UdmSourceEndDate sentinel backfill on active rows
# ---------------------------------------------------------------------------

SENTINEL = "2999-12-31"
SOURCE_DATE_COLUMNS: list[tuple[str, str]] = [
    ("UdmSourceBeginDate", "DATETIME2(3) NULL"),
    ("UdmSourceEndDate",   "DATETIME2(3) NULL"),
]


def _bronze_tables() -> list[tuple[str, str, str]]:
    """Return (schema, table, full_name) for every Bronze SCD2 Python table."""
    conn = get_general_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT TABLE_SCHEMA, TABLE_NAME
            FROM [{configuration.BRONZE_DB}].INFORMATION_SCHEMA.TABLES
            WHERE TABLE_TYPE = 'BASE TABLE'
              AND TABLE_NAME LIKE '%_scd2_python'
            ORDER BY TABLE_SCHEMA, TABLE_NAME
            """
        )
        rows = cursor.fetchall()
        cursor.close()
        return [(r[0], r[1], f"{configuration.BRONZE_DB}.{r[0]}.{r[1]}") for r in rows]
    finally:
        conn.close()


def add_source_date_columns(dry_run: bool) -> tuple[int, int]:
    """R-1/R-3: Add UdmSourceBeginDate + UdmSourceEndDate to every Bronze SCD2 table."""
    logger.info("--- Step 2: Add UdmSourceBeginDate + UdmSourceEndDate to Bronze ---")

    tables = _bronze_tables()
    logger.info("Scanning %d Bronze SCD2 tables", len(tables))

    added = 0
    skipped = 0
    for schema, table, full_name in tables:
        q_full = quote_table(full_name)
        for column, type_def in SOURCE_DATE_COLUMNS:
            if _column_exists(configuration.BRONZE_DB, schema, table, column):
                logger.debug("[%s] %s already exists", full_name, column)
                skipped += 1
                continue

            sql = f"ALTER TABLE {q_full} ADD [{column}] {type_def}"
            if _run_or_preview(configuration.BRONZE_DB, sql, dry_run):
                added += 1

    logger.info("Source-date columns: %d column-additions %s, %d already present",
                added, "previewed" if dry_run else "applied", skipped)
    return added, skipped


def backfill_source_end_date_sentinel(dry_run: bool) -> int:
    """R-3.3: Backfill UdmSourceEndDate = '2999-12-31' for active rows.

    Invariants after this migration:
      * Active rows (UdmActiveFlag=1) carry UdmSourceEndDate = sentinel.
      * Historical rows (UdmActiveFlag=0) carry the chained end date once
        the Phase 1 code has closed them; rows closed by the legacy engine
        retain NULL here (load time lives in UdmEndDateTime).
      * UdmSourceEndDate IS NULL + UdmActiveFlag = 0 + operation U/R is the
        Phase 1 "in-flight insert" marker for activation and orphan recovery.

    We intentionally do NOT backfill UdmSourceBeginDate — load time is an
    approximation of business date and we prefer explicit NULLs over
    silently-incorrect values. The first SCD2 run after deployment
    populates it for every new version going forward.
    """
    logger.info("--- Step 3: Backfill UdmSourceEndDate sentinel on active rows ---")

    tables = _bronze_tables()
    total = 0
    for schema, table, full_name in tables:
        q_full = quote_table(full_name)
        sql = (
            f"UPDATE {q_full} "
            f"SET UdmSourceEndDate = '{SENTINEL}' "
            f"WHERE UdmActiveFlag = 1 AND UdmSourceEndDate IS NULL"
        )

        if dry_run:
            logger.info("[DRY RUN] [%s] %s", configuration.BRONZE_DB, sql)
            continue

        conn = get_connection(configuration.BRONZE_DB)
        try:
            cursor = conn.cursor()
            cursor.execute(sql)
            rows = cursor.rowcount
            cursor.close()
            if rows and rows > 0:
                logger.info("[%s] backfilled %d active rows to sentinel", full_name, rows)
                total += rows
        except Exception:
            logger.exception("Failed to backfill %s", full_name)
        finally:
            conn.close()

    logger.info("Sentinel backfill: %d active rows %s",
                total, "previewed" if dry_run else "updated")
    return total


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def migrate(dry_run: bool = False) -> None:
    logger.info("=" * 72)
    logger.info("SCD2 Phase 1 Migration — config columns + source-date pair + sentinel")
    logger.info("Mode: %s", "DRY RUN" if dry_run else "LIVE")
    logger.info("=" * 72)

    migrate_udm_tables_list(dry_run)
    add_source_date_columns(dry_run)
    backfill_source_end_date_sentinel(dry_run)

    logger.info("=" * 72)
    logger.info("Migration %s complete.", "preview" if dry_run else "live")
    if not dry_run:
        logger.info(
            "Deploy the Phase 1 code after this migration. New invariants: "
            "active rows have UdmSourceEndDate = '%s'; NULL on UdmSourceEndDate "
            "marks in-flight (Flag=0, operation U/R) rows. UdmEffectiveDateTime "
            "and UdmEndDateTime retain their pre-Phase-1 load-time semantics.",
            SENTINEL,
        )
    logger.info("=" * 72)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="SCD2 Phase 1 migration: config columns + UdmSourceBeginDate/UdmSourceEndDate",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview DDL/DML statements without executing them",
    )
    args = parser.parse_args()

    migrate(dry_run=args.dry_run)