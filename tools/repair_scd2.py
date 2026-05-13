"""SCD2 chain repair CLI (R-6).

Pairs with ``tools/validate_scd2.py``: validate first, then repair only the
defects R-6 considers safe to auto-fix. Anything ambiguous (overlaps,
zero-active without Flag=2, source-date gaps, invalid domain values) is
deliberately NOT repaired here — those need human review.

Default mode is **dry-run**. Real repairs require ``--apply``.

Usage::

    # Single table, dry-run (default)
    python3 tools/repair_scd2.py --source DNA --table PERS

    # Single table, apply
    python3 tools/repair_scd2.py --source DNA --table PERS --apply

    # Whole source
    python3 tools/repair_scd2.py --source DNA --apply

    # Skip specific repair types
    python3 tools/repair_scd2.py --source DNA --apply --no-duplicate-active-dedup

Repair types
------------

* **sentinel_fill** — Flag=1 rows with NULL UdmSourceEndDate get the sentinel.
* **orphan_cleanup** — DELETE in-flight orphans (Flag=0 + Op IN ('U','R') + both EndDates NULL).
* **duplicate_active_dedup** — close duplicate Flag=1 rows per PK; keep latest UdmEffectiveDateTime.

Each operation writes one row to ``General.ops.SCD2RepairLog`` with row count,
sample PKs, status (DRY_RUN / APPLIED / FAILED / SKIPPED), and duration.

Exit code 0 if every operation succeeded, 1 otherwise.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cdc.reconciliation.scd2_repair import (
    persist_repair_result,
    repair_duplicate_active,
    repair_orphan_cleanup,
    repair_sentinel_fill,
)
from orchestration.table_config import TableConfigLoader

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# Map of repair-type name -> (function, default-on flag).
REPAIRS: list[tuple[str, callable]] = [
    ("sentinel_fill", repair_sentinel_fill),
    ("orphan_cleanup", repair_orphan_cleanup),
    ("duplicate_active_dedup", repair_duplicate_active),
]


def _print_result(r) -> None:
    label = f"{r.source_name}.{r.table_name}/{r.repair_type}"
    samples = ""
    if r.sample_pks:
        samples = f"  samples={r.sample_pks[:3]}"
    if r.error_message:
        print(f"[{label}] {r.status} ERROR: {r.error_message}{samples}")
        return
    print(
        f"[{label}] {r.status} rows={r.rows_affected}  "
        f"({r.duration_ms} ms)  {r.message}{samples}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", help="Filter by SourceName (e.g. DNA).")
    parser.add_argument("--table", help="Filter by SourceObjectName.")
    parser.add_argument(
        "--all", action="store_true",
        help="Repair every Python pipeline table (overrides individual filters).",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Apply repairs. Default is dry-run.",
    )
    parser.add_argument("--no-sentinel-fill", action="store_true",
                        help="Skip the sentinel_fill repair.")
    parser.add_argument("--no-orphan-cleanup", action="store_true",
                        help="Skip the orphan_cleanup repair.")
    parser.add_argument("--no-duplicate-active-dedup", action="store_true",
                        help="Skip the duplicate_active_dedup repair.")
    args = parser.parse_args()

    if not (args.source or args.table or args.all):
        parser.error("Specify --source, --table, or --all.")

    skip_set = set()
    if args.no_sentinel_fill:
        skip_set.add("sentinel_fill")
    if args.no_orphan_cleanup:
        skip_set.add("orphan_cleanup")
    if args.no_duplicate_active_dedup:
        skip_set.add("duplicate_active_dedup")

    enabled = [(name, fn) for name, fn in REPAIRS if name not in skip_set]
    if not enabled:
        parser.error("All repair types skipped — nothing to do.")

    dry_run = not args.apply
    mode = "DRY-RUN" if dry_run else "APPLY"

    loader = TableConfigLoader()
    configs = loader.load_small_tables(source_name=args.source, table_name=args.table)
    configs += loader.load_large_tables(source_name=args.source, table_name=args.table)
    if not configs:
        logger.error(
            "No matching tables in UdmTablesList (filters: source=%s, table=%s, all=%s).",
            args.source, args.table, args.all,
        )
        return 2

    logger.info(
        "R-6 chain repair (%s) on %d table(s); enabled: %s",
        mode, len(configs), [n for n, _ in enabled],
    )

    all_ok = True
    for cfg in configs:
        for name, fn in enabled:
            try:
                result = fn(cfg, dry_run=dry_run)
            except Exception:
                logger.exception(
                    "R-6: %s.%s/%s raised unexpectedly",
                    cfg.source_name, cfg.source_object_name, name,
                )
                all_ok = False
                continue
            _print_result(result)
            persist_repair_result(result)
            if result.status == "FAILED":
                all_ok = False

    if all_ok:
        logger.info("R-6: all repairs %s successfully.", "previewed" if dry_run else "applied")
        if dry_run:
            logger.info("To execute: re-run with --apply.")
        return 0
    logger.error("R-6: one or more operations failed. See ops.SCD2RepairLog.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
