"""R-13 large-table backfill — re-process an explicit date range.

Operator-driven recovery for large (date-windowed) tables. The daily
pipeline processes ``LookbackDays`` worth of dates each run; if a date
range falls outside that window or was missed entirely (e.g. a January gap
discovered in March), this tool re-runs the per-day pipeline against the
explicit range.

Idempotent: re-extracting a date that already produced its current Bronze
state writes nothing new (hashes match). Only true differences become
inserts/updates/closes.

Usage::

    # Single table, one month
    python3 tools/backfill.py \\
        --source DNA --table ACCT \\
        --from 2024-01-01 --to 2024-01-31

    # Single date
    python3 tools/backfill.py \\
        --source DNA --table ACCT --date 2024-01-15

    # Whole source, multi-month gap
    python3 tools/backfill.py \\
        --source DNA \\
        --from 2024-01-01 --to 2024-02-29

    # Dry-run preview (lists dates that would be processed; no extraction)
    python3 tools/backfill.py \\
        --source DNA --table ACCT \\
        --from 2024-01-01 --to 2024-01-31 \\
        --dry-run

Defaults:

* The modified-date sweep is suppressed during backfills (the explicit
  reload IS the action; sweep would be redundant).
* No confirmation prompt — the operator's date range is the explicit
  authorization.
* Per-day checkpoint state is updated as each day completes.

Exit code 0 if every date succeeded for every table, 1 if any failed.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import utils.configuration as config
from observability.event_tracker import PipelineEventTracker
from orchestration.large_tables import process_large_table
from orchestration.table_config import TableConfigLoader

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _parse_date(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _build_date_range(start: date, end: date) -> list[date]:
    if end < start:
        raise ValueError(f"--to ({end}) must be on or after --from ({start})")
    days = (end - start).days + 1
    return [start + timedelta(days=i) for i in range(days)]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", required=True, help="SourceName (e.g. DNA).")
    parser.add_argument(
        "--table",
        help="SourceObjectName. Omit to backfill every large table for the source.",
    )
    parser.add_argument(
        "--from", dest="from_date", type=_parse_date,
        help="Inclusive start date (YYYY-MM-DD). Required unless --date.",
    )
    parser.add_argument(
        "--to", dest="to_date", type=_parse_date,
        help="Inclusive end date (YYYY-MM-DD). Required unless --date.",
    )
    parser.add_argument(
        "--date", dest="single_date", type=_parse_date,
        help="Single date to backfill (alternative to --from/--to).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List dates and tables that would be processed; no extraction.",
    )
    args = parser.parse_args()

    # Build the explicit date list.
    if args.single_date is not None:
        if args.from_date or args.to_date:
            parser.error("--date conflicts with --from/--to.")
        dates = [args.single_date]
    else:
        if not args.from_date or not args.to_date:
            parser.error("Provide --from and --to, or --date.")
        dates = _build_date_range(args.from_date, args.to_date)

    loader = TableConfigLoader()
    configs = loader.load_large_tables(
        source_name=args.source, table_name=args.table,
    )
    if not configs:
        logger.error(
            "No matching LARGE tables in UdmTablesList "
            "(source=%s, table=%s).",
            args.source, args.table,
        )
        return 2

    if args.dry_run:
        logger.info(
            "[DRY RUN] Would backfill %d table(s) over %d date(s):",
            len(configs), len(dates),
        )
        for cfg in configs:
            logger.info("  %s.%s", cfg.source_name, cfg.source_object_name)
        logger.info(
            "Date range: %s -> %s (%d days)",
            dates[0], dates[-1], len(dates),
        )
        return 0

    output_dir = Path(config.CSV_OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    all_ok = True
    event_tracker = PipelineEventTracker()
    for cfg in configs:
        logger.info(
            "R-13 backfill: %s.%s — %d dates from %s to %s",
            cfg.source_name, cfg.source_object_name,
            len(dates), dates[0], dates[-1],
        )
        ok = process_large_table(
            cfg,
            event_tracker,
            output_dir=output_dir,
            force=True,                # bypass extraction guards on backfill
            dates_override=list(dates),
        )
        if not ok:
            all_ok = False
            logger.error(
                "R-13 backfill: %s.%s reported failures — see PipelineEventLog.",
                cfg.source_name, cfg.source_object_name,
            )

    if all_ok:
        logger.info("R-13 backfill complete: every date succeeded across every table.")
        return 0
    logger.error("R-13 backfill: one or more failures. See PipelineEventLog for details.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
