"""CLI entry point for small tables pipeline.

Usage:
    python3 main_small_tables.py --workers 4
    python3 main_small_tables.py --table ACCTLOAN --source DNA
    python3 main_small_tables.py --list-tables
    python3 main_small_tables.py --workers 4 --source DNA
"""

from __future__ import annotations

# L-1: cli_common sets MALLOC_ARENA_MAX (M-1), POLARS_MAX_THREADS (M-2),
# and sys.path — must be imported before any other project modules.
import utils.cli_common as cli_common  # noqa: F401

import argparse
import logging
import multiprocessing
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed

from observability.event_tracker import PipelineEventTracker
from orchestration.table_config import TableConfigLoader


def _process_table_worker(table_config_dict: dict) -> tuple[str, str, bool]:
    """Worker function for ProcessPoolExecutor.

    Takes a serialized table config dict (for pickling across processes),
    reconstructs the config, and processes the table.

    NOTE: With mp_context='spawn', all imports happen fresh in the child
    process — ConnectorX gets a clean tokio/rayon runtime with no inherited
    mutex state. The deferred imports below are defense-in-depth.
    """
    from orchestration.small_tables import process_small_table
    from utils.cli_common import table_config_from_dict

    tc, metadata = table_config_from_dict(table_config_dict)

    tracker = PipelineEventTracker()
    tracker._batch_id = metadata["batch_id"]

    force = metadata.get("force", False)
    refresh_pks = metadata.get("refresh_pks", False)
    success = process_small_table(tc, tracker, force=force, refresh_pks=refresh_pks)
    return tc.source_name, tc.source_object_name, success


def main() -> None:
    parser = argparse.ArgumentParser(description="UDM Small Tables Pipeline")
    # M-2: Default to 4 workers (not 6). On 64 GB with OS overhead (2-4 GB),
    # 4 workers get ~15 GB each — enough for 3M x 100-col CDC joins.
    # 6 workers at ~10 GB each OOM during anti-join peak memory (2.5-3x DataFrame).
    parser.add_argument("--workers", type=int, default=4, help="Number of parallel workers (default: 4, max recommended: 4 on 64 GB)")
    parser.add_argument("--table", type=str, help="Process a single table by name")
    parser.add_argument("--source", type=str, help="Filter by source name (DNA, CCM, EPICOR)")
    parser.add_argument("--list-tables", action="store_true", help="List available tables and exit")
    parser.add_argument("--force", action="store_true", help="Skip extraction row-count guard (P1-1). Use for intentional reloads.")
    parser.add_argument("--refresh-pks", action="store_true", help="P1-10: Re-discover PKs from source and update UdmTablesColumnsList.")
    args = parser.parse_args()

    logger = logging.getLogger(__name__)

    # H-4: Validate CLI arguments against known values before querying
    cli_common.validate_cli_filters(args.source, args.table)

    # Load table configs
    loader = TableConfigLoader()
    configs = loader.load_small_tables(
        source_name=args.source,
        table_name=args.table,
    )

    if args.list_tables:
        print(f"\n{'Source':<12} {'Table':<30} {'Stage Name':<30} {'Bronze Name':<30}")
        print("-" * 102)
        for tc in sorted(configs, key=lambda x: (x.source_name, x.source_object_name)):
            print(
                f"{tc.source_name:<12} {tc.source_object_name:<30} "
                f"{tc.effective_stage_name:<30} {tc.effective_bronze_name:<30}"
            )
        print(f"\nTotal: {len(configs)} small tables")
        return

    if not configs:
        print("No tables found matching the specified filters.")
        return

    # Set up tracking
    tracker = PipelineEventTracker()
    batch_id = tracker.batch_id
    sql_handler = cli_common.setup_logging(batch_id)

    # L-1: Startup checks (staging cleanup + RCSI verification)
    cli_common.startup_checks()

    # W-4: Warn if MALLOC_ARENA_MAX was not set in the external environment.
    cli_common.warn_malloc_arena()

    # M-2: Warn if workers exceed recommended maximum for 64 GB system
    cli_common.warn_workers(args.workers)

    logger.info("Starting small tables pipeline: batch_id=%d, tables=%d, workers=%d",
                batch_id, len(configs), args.workers)
    
    from orchestration.pk_validation import validate_pks_preflight
    missing_pk_tables = validate_pks_preflight(configs)

    succeeded = 0
    failed = 0

    # FIX: Switch recovery model ONCE at pipeline level instead of per-table.
    # Each ALTER DATABASE SET RECOVERY takes a database-level exclusive lock.
    # Per-table switching causes lock contention between workers and risks
    # mid-transaction recovery model changes if one worker's finally block
    # runs while another worker's BCP is mid-load.
    from data_load.bcp_loader import bulk_load_recovery_context
    import utils.configuration as pipeline_config

    with bulk_load_recovery_context(pipeline_config.STAGE_DB):
        with bulk_load_recovery_context(pipeline_config.BRONZE_DB):
            if args.workers <= 1:
                # Sequential execution
                for tc in configs:
                    # B-8: RSS monitoring between table iterations.
                    cli_common.check_rss_memory(tc.source_name, tc.source_object_name)
                    sql_handler.set_context(batch_id=batch_id, table_name=tc.source_object_name, source_name=tc.source_name)
                    from orchestration.small_tables import process_small_table
                    success = process_small_table(tc, tracker, force=args.force, refresh_pks=args.refresh_pks)
                    if success:
                        succeeded += 1
                    else:
                        failed += 1
            else:
                # Parallel execution
                table_dicts = [cli_common.table_config_to_dict(tc, batch_id) for tc in configs]
                if args.force:
                    for td in table_dicts:
                        td["force"] = True
                if args.refresh_pks:
                    for td in table_dicts:
                        td["refresh_pks"] = True

                # FIX: Use 'spawn' context to prevent ConnectorX/Polars fork deadlocks.
                # Python 3.12 on Linux defaults to 'fork', which copies the parent's
                # Rust thread pool mutex state into children. Tokio/rayon threads that
                # held those mutexes don't exist in the child → permanent deadlock.
                # 'spawn' starts a fresh Python interpreter per worker via fork()+exec(),
                # giving each child a clean tokio/rayon runtime. The ~1s startup cost
                # per worker is invisible against minutes of database I/O.
                # See: tokio-rs/tokio#4301, CPython#84559, Polars#8032.
                mp_ctx = multiprocessing.get_context('spawn')

                with ProcessPoolExecutor(max_workers=args.workers, mp_context=mp_ctx) as executor:
                    futures = {
                        executor.submit(_process_table_worker, td): td
                        for td in table_dicts
                    }
                    for future in as_completed(futures):
                        td = futures[future]
                        try:
                            source, table, success = future.result()
                            if success:
                                succeeded += 1
                                logger.info("Completed: %s.%s", source, table)
                            else:
                                failed += 1
                                logger.error("Failed: %s.%s", source, table)
                        except Exception:
                            failed += 1
                            logger.exception("Worker exception for %s.%s",
                                             td.get("source_name"), td.get("source_object_name"))
                            

    # Restore SIMPLE recovery now that all loads are complete.
    # The pipeline needs FULL during execution for idempotency, but
    # SIMPLE between runs prevents log growth from LOG_BACKUP waits.
    cli_common.restore_simple_recovery()

    # P3-7: Final sweep of output directory for orphaned temp files.
    # Catches CSVs and .fmt files from tables that failed mid-pipeline
    # (after CSV write but before reaching per-table CSV_CLEANUP).
    # Also cleans up tmpfs staging directory.
    cli_common.final_cleanup_output_dir()

    # P-3: Log connection overhead before flushing.
    cli_common.log_connection_overhead()

    # Item-18: Close pooled connections at shutdown.
    cli_common.shutdown_connections()

    # Flush logs
    sql_handler.flush()

    logger.info(
        "Pipeline complete: batch_id=%d, succeeded=%d, failed=%d",
        batch_id, succeeded, failed,
    )

    sys.exit(1 if failed > 0 else 0)


if __name__ == "__main__":
    main()
