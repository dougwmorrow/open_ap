"""Truncate (drop) Stage and Bronze tables for a source — clean-slate recovery.

Used during development when the Stage/Bronze state is inconsistent and the
fastest path to a known-good baseline is to rebuild from source. Drops every
``_cdc`` and ``_scd2_python`` table for the configured source, so the next
pipeline run hits the first-load path:

    extract → write CSV → ensure_stage_table (create) → ensure_bronze_table (create)
            → CDC: 'Stage table doesn't exist — all rows are inserts'
            → SCD2: every row gets UdmActiveFlag=1 with operation 'I'

Usage::

    # Dry-run (default) — list what WOULD be dropped
    python3 tools/truncate_stage_bronze.py --source DNA

    # Actually drop
    python3 tools/truncate_stage_bronze.py --source DNA --apply

    # One specific table
    python3 tools/truncate_stage_bronze.py --source DNA --table ACCT --apply

    # Multiple tables
    python3 tools/truncate_stage_bronze.py --source DNA --table ACCT --table ACCTACCTROLEPERS --apply

After the drop, run the pipeline normally::

    python3 main_small_tables.py --source DNA
    python3 main_large_tables.py --source DNA

The pipeline will recreate the tables from the DataFrame schema and load
all rows as fresh inserts. Bronze ends up with one row per PK,
``UdmActiveFlag=1``, ``_cdc_operation='I'`` in Stage.

Safety
------

* **Never operates without --apply.** The default is dry-run; it only
  enumerates and prints.
* **Drops `PipelineExtractionState` rows** for the table only when
  ``--reset-checkpoints`` is supplied, so large-table runs start from
  ``FirstLoadDate`` again.
* **Will NOT touch UDM_Stage._cdc tables outside the named source** —
  every drop is scoped by ``SourceName`` derived from
  ``UdmTablesList``.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import utils.configuration as config  # noqa: E402
from utils.connections import (  # noqa: E402
    get_connection,
    get_general_connection,
    quote_table,
)


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Discover what to drop from UdmTablesList.
# ---------------------------------------------------------------------------


def _list_tables(source: str, table_filter: list[str] | None) -> list[dict]:
    """Return one dict per table to drop. Each dict has ``stage`` and
    ``bronze`` fully-qualified names plus the ``table`` name itself.
    """
    sql = (
        "SELECT SourceObjectName, StageTableName, BronzeTableName, SourceName "
        "FROM dbo.UdmTablesList WHERE SourceName = ?"
    )
    params: list = [source]
    if table_filter:
        placeholders = ", ".join(["?"] * len(table_filter))
        sql += f" AND SourceObjectName IN ({placeholders})"
        params.extend(table_filter)

    conn = get_general_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(sql, *params)
        rows = cursor.fetchall()
        cursor.close()
    finally:
        conn.close()

    if not rows:
        if table_filter:
            logger.error(
                "No matching rows in UdmTablesList for source=%s tables=%s",
                source, table_filter,
            )
        else:
            logger.error("No rows in UdmTablesList for source=%s", source)
        return []

    out = []
    for row in rows:
        source_obj, stage_name, bronze_name, source_name = row
        effective_stage = stage_name or source_obj
        effective_bronze = bronze_name or source_obj
        out.append({
            "table": source_obj,
            "stage_full": f"{config.STAGE_DB}.{source_name}.{effective_stage}_cdc",
            "bronze_full": f"{config.BRONZE_DB}.{source_name}.{effective_bronze}_scd2_python",
            "source": source_name,
        })
    return out


# ---------------------------------------------------------------------------
# Drop logic.
# ---------------------------------------------------------------------------


def _drop_table(full_name: str, label: str) -> bool:
    """``DROP TABLE IF EXISTS`` with logging. Returns True if SQL ran."""
    db = full_name.split(".")[0]
    quoted = quote_table(full_name)
    conn = get_connection(db)
    try:
        cursor = conn.cursor()
        cursor.execute(f"DROP TABLE IF EXISTS {quoted}")
        cursor.commit()
        cursor.close()
        logger.info("DROPPED %s table: %s", label, full_name)
        return True
    except Exception as exc:
        logger.error("Failed to drop %s table %s: %s", label, full_name, exc)
        return False
    finally:
        conn.close()


def _reset_checkpoints(source: str, tables: list[str]) -> None:
    """Delete rows from ``PipelineExtractionState`` so large tables restart
    from ``FirstLoadDate`` on the next run.

    Batches the DELETE so a whole-source reset (hundreds of tables) doesn't
    overflow ODBC's TLS packet size with a 500-element ``IN`` list — the
    error mode is::

        [08S01] SSL Provider: Packet size too large for SSL Encrypt/Decrypt
        operations [50]

    With a chunk size of 100 each ``DELETE`` carries 101 parameters
    (1 source name + 100 table names), well within ODBC + TLS limits.
    """
    if not tables:
        return

    chunk_size = 100
    sql_template = (
        "DELETE FROM ops.PipelineExtractionState "
        "WHERE SourceName = ? AND TableName IN ({}) "
    )

    conn = get_general_connection()
    total_affected = 0
    try:
        cursor = conn.cursor()
        try:
            for i in range(0, len(tables), chunk_size):
                chunk = tables[i:i + chunk_size]
                sql = sql_template.format(", ".join(["?"] * len(chunk)))
                cursor.execute(sql, source, *chunk)
                total_affected += cursor.rowcount
            cursor.commit()
        finally:
            cursor.close()
        logger.info(
            "Cleared %d PipelineExtractionState rows for %s across %d table(s)",
            total_affected, source, len(tables),
        )
    except Exception as exc:
        logger.error("Failed to reset checkpoints for %s: %s", source, exc)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Drop Stage and Bronze tables for a source so the next "
                    "pipeline run rebuilds from scratch.",
    )
    parser.add_argument("--source", required=True,
                        help="SourceName (e.g. DNA, CCM, EPICOR).")
    parser.add_argument("--table", action="append", default=None,
                        help="One or more SourceObjectName values. Repeat the "
                             "flag for each (e.g. --table ACCT --table CARD). "
                             "If omitted, every table for the source is dropped.")
    parser.add_argument("--apply", action="store_true",
                        help="Actually run DROP statements. Without this flag, "
                             "the script only enumerates what it would do.")
    parser.add_argument("--reset-checkpoints", action="store_true",
                        help="Also clear PipelineExtractionState rows so large "
                             "tables restart from FirstLoadDate. Recommended "
                             "when --table is not supplied (whole-source reset).")
    parser.add_argument("-y", "--yes", action="store_true",
                        help="Skip the interactive confirmation prompt.")
    args = parser.parse_args()

    targets = _list_tables(args.source, args.table)
    if not targets:
        return 1

    print()
    print(f"Source:           {args.source}")
    print(f"Mode:             {'APPLY' if args.apply else 'DRY-RUN'}")
    print(f"Reset checkpoints:{' yes' if args.reset_checkpoints else ' no'}")
    print(f"Tables targeted:  {len(targets)}")
    print()
    print(f"{'TABLE':<40} {'STAGE':<60} {'BRONZE'}")
    for t in targets:
        print(f"{t['table']:<40} {t['stage_full']:<60} {t['bronze_full']}")
    print()

    if not args.apply:
        print("Dry-run. Re-run with --apply to actually drop.")
        return 0

    if not args.yes:
        confirm = input(
            f"About to DROP {len(targets) * 2} tables in {config.STAGE_DB} "
            f"and {config.BRONZE_DB}. Type the source name ({args.source}) "
            f"to confirm: "
        )
        if confirm.strip() != args.source:
            print("Confirmation mismatch — aborting.")
            return 1

    dropped = 0
    failed = 0
    for t in targets:
        if _drop_table(t["stage_full"], "Stage"):
            dropped += 1
        else:
            failed += 1
        if _drop_table(t["bronze_full"], "Bronze"):
            dropped += 1
        else:
            failed += 1

    if args.reset_checkpoints:
        _reset_checkpoints(args.source, [t["table"] for t in targets])

    print()
    logger.info("Done. dropped=%d failed=%d", dropped, failed)
    print()
    print("Next steps:")
    print(f"  python3 main_small_tables.py --source {args.source} --workers 4")
    print(f"  python3 main_large_tables.py --source {args.source} --workers 4")
    print()
    print("After the rebuild, verify the affected PK with:")
    print(f"  python3 tools/inspect_cdc_pk.py --source {args.source} "
          f"--table <T> --pk-values <PK>")

    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
