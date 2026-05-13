"""SCD2 chain validation CLI (R-5).

Read-only diagnostic. Surfaces structural defects in Bronze SCD2 tables
WITHOUT modifying any data — repairs are out of scope here (R-6 ships
separately).

Three layers of check (all in :func:`cdc.reconciliation.scd2_integrity.validate_scd2_integrity`):

  1. **Load-time pair** — overlapping intervals, zero-active PKs, version gaps
     on ``UdmEffectiveDateTime`` / ``UdmEndDateTime``.
  2. **Source-date pair** (R-2) — same checks on ``UdmSourceBeginDate`` /
     ``UdmSourceEndDate``. Pre-Phase-1 legacy rows with NULL
     ``UdmSourceBeginDate`` are exempt.
  3. **Invariants** — Flag=1 must have sentinel and NULL UdmEndDateTime;
     Flag=2 must have populated UdmEndDateTime and no sentinel; Flag and
     Op value domains; B-4 in-flight orphans (informational).

Usage::

    python3 tools/validate_scd2.py --source DNA --table PERS
    python3 tools/validate_scd2.py --source DNA              # all DNA tables
    python3 tools/validate_scd2.py --all                     # everything

Exit code 0 if every checked table is clean, 1 if any defect is found.

Pipes a one-line summary per table to stdout plus structured details to
``General.ops.PipelineLog`` via the standard SqlServerLogHandler.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Add parent directory for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cdc.reconciliation.scd2_integrity import validate_scd2_integrity
from orchestration.table_config import TableConfigLoader

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _load_targets(
    source: str | None,
    table: str | None,
    include_all: bool,
):
    loader = TableConfigLoader()
    small = loader.load_small_tables(source_name=source, table_name=table)
    large = loader.load_large_tables(source_name=source, table_name=table)
    configs = small + large

    if not configs:
        logger.error(
            "No matching tables in UdmTablesList (filters: source=%s, table=%s, all=%s)",
            source, table, include_all,
        )
        sys.exit(2)

    return configs


def _print_table_summary(result) -> bool:
    """Return True if the table is clean."""
    label = f"{result.source_name}.{result.table_name}"
    if result.errors:
        print(f"[{label}] ERROR: {'; '.join(result.errors)}")
        return False

    findings = []
    if result.overlapping_intervals:
        findings.append(f"load-overlaps={result.overlapping_intervals}")
    if result.zero_active_pks:
        findings.append(f"zero-active={result.zero_active_pks}")
    if result.version_gaps:
        findings.append(f"load-gaps={result.version_gaps}")
    if result.source_overlapping_intervals:
        findings.append(f"source-overlaps={result.source_overlapping_intervals}")
    if result.source_version_gaps:
        findings.append(f"source-gaps={result.source_version_gaps}")
    if result.active_missing_source_sentinel:
        findings.append(f"active-no-sentinel={result.active_missing_source_sentinel}")
    if result.active_with_end_date:
        findings.append(f"active-has-end={result.active_with_end_date}")
    if result.invalid_flag_values:
        findings.append(f"invalid-flag={result.invalid_flag_values}")
    if result.invalid_operation_values:
        findings.append(f"invalid-op={result.invalid_operation_values}")
    if result.flag2_missing_end_date:
        findings.append(f"flag2-no-end={result.flag2_missing_end_date}")
    if result.flag2_with_active_sentinel:
        findings.append(f"flag2-has-sentinel={result.flag2_with_active_sentinel}")
    # Inflight orphans are informational, not a defect
    inflight_note = (
        f" (informational: inflight-orphans={result.inflight_orphans})"
        if result.inflight_orphans else ""
    )

    if not findings:
        print(f"[{label}] CLEAN{inflight_note}")
        return True

    print(f"[{label}] DEFECTS: {', '.join(findings)}{inflight_note}")
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", help="Filter by SourceName (e.g. DNA).")
    parser.add_argument("--table", help="Filter by SourceObjectName.")
    parser.add_argument(
        "--all", action="store_true",
        help="Validate every Python pipeline table (overrides individual filters).",
    )
    args = parser.parse_args()

    if not (args.source or args.table or args.all):
        parser.error("Specify --source, --table, or --all.")

    configs = _load_targets(args.source, args.table, args.all)
    logger.info("R-5: validating SCD2 chain integrity on %d table(s)", len(configs))

    all_clean = True
    for cfg in configs:
        try:
            result = validate_scd2_integrity(cfg)
        except Exception:
            logger.exception(
                "R-5: validate_scd2_integrity raised on %s.%s",
                cfg.source_name, cfg.source_object_name,
            )
            all_clean = False
            continue
        clean = _print_table_summary(result)
        if not clean:
            all_clean = False

    if all_clean:
        logger.info("R-5: all checked tables clean.")
        return 0
    logger.error("R-5: one or more tables have defects. See PipelineLog for details.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
