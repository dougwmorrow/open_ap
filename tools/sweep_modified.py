"""Modified-date sweep CLI (Tier 2 large-table CDC).

Detects rows whose source ``LastModifiedColumn`` is newer than the matching
Bronze active row's ``UdmSourceBeginDate`` — i.e. updated at source AFTER
the daily windowed extraction last saw them. Catches late updates that
fall outside the ``LookbackDays`` window.

Usage::

    # Detect-only (default), single table
    python3 tools/sweep_modified.py --source DNA --table ACCT

    # Detect-only, whole source
    python3 tools/sweep_modified.py --source DNA

    # Custom sweep window (days back from now)
    python3 tools/sweep_modified.py --source DNA --table ACCT --window 30

    # Apply (reload drift PKs) — v1 not yet implemented; use tools/backfill.py
    python3 tools/sweep_modified.py --source DNA --table ACCT --apply

Tables without ``UdmTablesList.LastModifiedColumn`` configured are skipped
silently. Run ``tools/detect_scd2_config.py --source DNA`` to populate it
via the autoconfig DNA profile (proposes ``DATELASTMAINT``).

Exit code 0 if every checked table is clean (no drift), 1 otherwise.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cdc.reconciliation.modified_sweep import (
    DEFAULT_SWEEP_WINDOW_DAYS,
    run_modified_sweep,
)
from orchestration.table_config import TableConfigLoader

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _print_result(r) -> bool:
    """Return True if clean."""
    label = f"{r.source_name}.{r.table_name}"
    if r.skipped:
        print(f"[{label}] SKIPPED ({r.skip_reason})")
        return True
    if r.errors:
        print(f"[{label}] ERROR: {'; '.join(r.errors)}")
        return False
    print(
        f"[{label}] window={r.sweep_window_days}d  "
        f"source_in_window={r.source_rows_in_window}  "
        f"bronze_active={r.bronze_active_rows_compared}  "
        f"drift_pks={r.drift_pks}  ({r.duration_ms} ms)"
    )
    return r.drift_pks == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", help="Filter by SourceName (e.g. DNA).")
    parser.add_argument("--table", help="Filter by SourceObjectName.")
    parser.add_argument(
        "--all", action="store_true",
        help="Sweep every Python pipeline LARGE table (overrides individual filters).",
    )
    parser.add_argument(
        "--window", type=int, default=DEFAULT_SWEEP_WINDOW_DAYS,
        help=f"Sweep window in days (default {DEFAULT_SWEEP_WINDOW_DAYS}).",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Reload drift PKs (v1: not yet implemented; reports only).",
    )
    args = parser.parse_args()

    if not (args.source or args.table or args.all):
        parser.error("Specify --source, --table, or --all.")

    loader = TableConfigLoader()
    # Modified-date sweep targets large tables (date-windowed extraction
    # is where late-update drift is meaningful). Small tables do a full
    # extract every run so drift can't accumulate.
    configs = loader.load_large_tables(source_name=args.source, table_name=args.table)

    if not configs:
        logger.error(
            "No matching LARGE tables in UdmTablesList "
            "(filters: source=%s, table=%s, all=%s).",
            args.source, args.table, args.all,
        )
        return 2

    logger.info(
        "Modified-date sweep on %d table(s) (window=%dd, apply=%s)",
        len(configs), args.window, args.apply,
    )

    all_clean = True
    for cfg in configs:
        try:
            result = run_modified_sweep(
                cfg,
                sweep_window_days=args.window,
                apply=args.apply,
            )
        except Exception:
            logger.exception(
                "Modified-date sweep raised on %s.%s",
                cfg.source_name, cfg.source_object_name,
            )
            all_clean = False
            continue
        clean = _print_result(result)
        if not clean:
            all_clean = False

    if all_clean:
        logger.info("Modified-date sweep: all checked tables clean (no drift).")
        return 0
    logger.warning("Modified-date sweep: drift detected — see PipelineLog for details.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
