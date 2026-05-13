#!/usr/bin/env python3
"""PK-2: Standalone table setup — sync columns + PK discovery outside the hot path.

Runs sync_columns and PK discovery for all tables (or filtered by --source/--table),
outputs a summary report, and exits. This should be run BEFORE the production pipeline
to ensure UdmTablesColumnsList is fully populated with correct PKs.

Usage:
    python3 main_pre_pipeline_setup.py                        # All tables
    python3 main_pre_pipeline_setup.py --source CCM           # CCM tables only
    python3 main_pre_pipeline_setup.py --table BankruptcyType  # Single table
    python3 main_pre_pipeline_setup.py --refresh-pks          # Re-discover PKs even if columns exist
    python3 main_pre_pipeline_setup.py --validate-only        # PK-4: Read-only PK validation
    python3 main_pre_pipeline_setup.py --table LoanDelinquencyHistory --source CCM

The production pipeline (main_small_tables.py --workers) should NOT call sync_columns —
it should only read from the already-populated UdmTablesColumnsList. The PK-1 pre-flight
check will fail fast if setup hasn't been run.

This script replaces the fragile auto-discovery that ran during the pipeline hot path,
which had three failure modes:
  - Oracle views return no PKs (expected but unrecoverable in-flight)
  - Wrong unique index selected as PK (SQL Server MIN(index_id) heuristic)
  - Crash mid-sync leaves columns populated but IsPrimaryKey=0 for everything
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Module-level environment setup (must come before project imports)
import os
os.environ.setdefault("MALLOC_ARENA_MAX", "2")
os.environ.setdefault("POLARS_MAX_THREADS", "1")
sys.path.insert(0, str(Path(__file__).parent))

import utils.cli_common as cli_common
from orchestration.table_config import TableConfigLoader

logger = logging.getLogger(__name__)


def _setup_tables(
    configs: list,
    refresh_pks: bool = False,
) -> dict:
    """Run sync_columns + PK discovery for all tables.

    Returns:
        Summary dict with counts and per-table details.
    """
    from schema.column_sync import sync_columns
    from extract.udm_connectorx_extractor import table_exists
    from schema.table_creator import ensure_stage_table, ensure_bronze_table

    summary = {
        "total": len(configs),
        "synced": 0,
        "already_populated": 0,
        "pk_discovered": 0,
        "pk_missing": 0,
        "tables_with_pks": [],
        "tables_without_pks": [],
        "errors": [],
    }

    for tc in sorted(configs, key=lambda x: (x.source_name, x.source_object_name)):
        table_id = f"{tc.source_name}.{tc.source_object_name}"
        try:
            # sync_columns returns True if columns were newly synced
            was_new = sync_columns(tc, refresh_pks=refresh_pks)
            if was_new:
                summary["synced"] += 1
            else:
                summary["already_populated"] += 1

            # Check PK status after sync

            if tc.pk_columns:
                # NoPK-3: Validate that discovered PKs are actually unique in source
                from schema.column_sync import validate_pk_uniqueness
                is_unique = validate_pk_uniqueness(tc)
                summary["pk_discovered"] += 1
                summary["tables_with_pks"].append({
                    "table": table_id,
                    "pk_columns": tc.pk_columns,
                    "unique_validated": is_unique,
                })
                if not is_unique:
                    summary.setdefault("pk_not_unique", []).append(table_id)
            else:
                summary["pk_missing"] += 1
                summary["tables_without_pks"].append(table_id)

        except Exception as e:
            summary["errors"].append({
                "table": table_id,
                "error": str(e),
            })
            logger.error("Setup failed for %s: %s", table_id, e, exc_info=True)

    return summary


def _validate_pks(configs: list) -> dict:
    """PK-4: Read-only PK validation — compare configured vs discoverable.

    Compares currently configured PKs in UdmTablesColumnsList against what
    would be discovered from the source. Does NOT modify any data.
    """
    from schema.column_sync import _discover_pks

    summary = {
        "total": len(configs),
        "matches": 0,
        "mismatches": [],
        "missing_configured": [],
        "missing_source": [],
        "errors": [],
    }

    for tc in sorted(configs, key=lambda x: (x.source_name, x.source_object_name)):
        table_id = f"{tc.source_name}.{tc.source_object_name}"
        try:
            configured_pks = sorted(tc.pk_columns)

            # Discover what source says
            discovered_pks = sorted(_discover_pks(tc))

            if configured_pks == discovered_pks:
                summary["matches"] += 1
            elif not configured_pks and discovered_pks:
                summary["missing_configured"].append({
                    "table": table_id,
                    "discoverable": discovered_pks,
                })
            elif configured_pks and not discovered_pks:
                summary["missing_source"].append({
                    "table": table_id,
                    "configured": configured_pks,
                })
            else:
                summary["mismatches"].append({
                    "table": table_id,
                    "configured": configured_pks,
                    "discoverable": discovered_pks,
                })

        except Exception as e:
            summary["errors"].append({
                "table": table_id,
                "error": str(e),
            })
            logger.error("PK validation failed for %s: %s", table_id, e)

    return summary


def _print_setup_report(summary: dict) -> None:
    """Print human-readable setup summary."""
    print("\n" + "=" * 70)
    print("TABLE SETUP SUMMARY")
    print("=" * 70)
    print(f"  Total tables:       {summary['total']}")
    print(f"  Newly synced:       {summary['synced']}")
    print(f"  Already populated:  {summary['already_populated']}")
    print(f"  PKs discovered:     {summary['pk_discovered']}")
    print(f"  PKs MISSING:        {summary['pk_missing']}")
    print(f"  Errors:             {len(summary['errors'])}")

    if summary["tables_with_pks"]:
        print(f"\n--- Tables with PKs ({summary['pk_discovered']}) ---")
        for t in summary["tables_with_pks"]:
            print(f"  {t['table']}: {t['pk_columns']}")

    if summary["tables_without_pks"]:
        print(f"\n--- Tables MISSING PKs ({summary['pk_missing']}) ---")
        print("  ACTION REQUIRED: Set IsPrimaryKey=1 manually in")
        print("  General.dbo.UdmTablesColumnsList for these tables:")
        for t in summary["tables_without_pks"]:
            print(f"  - {t}")

    if summary["errors"]:
        print(f"\n--- Errors ({len(summary['errors'])}) ---")
        for e in summary["errors"]:
            print(f"  {e['table']}: {e['error']}")

    print("=" * 70 + "\n")


def _print_validation_report(summary: dict) -> None:
    """Print human-readable PK validation report."""
    print("\n" + "=" * 70)
    print("PK VALIDATION REPORT (read-only)")
    print("=" * 70)
    print(f"  Total tables:              {summary['total']}")
    print(f"  PKs match source:          {summary['matches']}")
    print(f"  Configured but not source:  {len(summary['missing_source'])}")
    print(f"  Source but not configured:  {len(summary['missing_configured'])}")
    print(f"  Mismatches:                {len(summary['mismatches'])}")
    print(f"  Errors:                    {len(summary['errors'])}")

    if summary["mismatches"]:
        print("\n--- PK Mismatches (configured != discoverable) ---")
        for m in summary["mismatches"]:
            print(f"  {m['table']}:")
            print(f"    Configured:   {m['configured']}")
            print(f"    Discoverable: {m['discoverable']}")

    if summary["missing_configured"]:
        print("\n--- Discoverable but NOT configured ---")
        print("  ACTION: Run setup_tables.py --refresh-pks to update:")
        for m in summary["missing_configured"]:
            print(f"  - {m['table']}: {m['discoverable']}")

    if summary["missing_source"]:
        print("\n--- Configured but NOT discoverable from source ---")
        print("  These may be manually set PKs (views, synthetic keys):")
        for m in summary["missing_source"]:
            print(f"  - {m['table']}: {m['configured']}")

    if summary["errors"]:
        print(f"\n--- Errors ({len(summary['errors'])}) ---")
        for e in summary["errors"]:
            print(f"  {e['table']}: {e['error']}")

    print("=" * 70 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="PK-2: Standalone table setup — sync columns + PK discovery",
    )
    parser.add_argument("--source", type=str, help="Filter by source name (DNA, CCM, EPICOR)")
    parser.add_argument("--table", type=str, help="Process a single table by name")
    parser.add_argument("--refresh-pks", action="store_true",
                        help="Re-discover PKs from source even if columns already exist")
    parser.add_argument("--validate-only", action="store_true",
                        help="PK-4: Read-only — compare configured PKs vs source, don't modify")
    parser.add_argument("--large-tables", action="store_true",
                        help="Include large tables (default: small tables only)")
    args = parser.parse_args()

    # Minimal logging setup (no SQL handler needed for setup)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        stream=sys.stdout,
    )

    # H-4: Validate CLI arguments
    cli_common.validate_cli_filters(args.source, args.table)

    # Load configs
    loader = TableConfigLoader()
    configs = []

    small = loader.load_small_tables(source_name=args.source, table_name=args.table)
    configs.extend(small)

    if args.large_tables:
        large = loader.load_large_tables(source_name=args.source, table_name=args.table)
        configs.extend(large)

    if not configs:
        print("No tables found matching the specified filters.")
        return

    print(f"\nFound {len(configs)} tables to process.")

    if args.validate_only:
        # PK-4: Read-only validation
        summary = _validate_pks(configs)
        _print_validation_report(summary)
        # Exit with error code if any issues found
        if summary["mismatches"] or summary["missing_configured"]:
            sys.exit(1)
    else:
        # PK-2: Full setup
        summary = _setup_tables(configs, refresh_pks=args.refresh_pks)
        _print_setup_report(summary)
        # Exit with error code if PKs are missing
        if summary["pk_missing"] > 0 or summary["errors"]:
            sys.exit(1)


if __name__ == "__main__":
    main()