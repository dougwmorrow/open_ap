"""Orchestrator for small tables (no date column — full extract each run).

Data flow per table:
  Source -> ConnectorX/oracledb extract -> Polars DataFrame
  -> add _row_hash + _extracted_at
  -> Write BCP CSV
  -> Ensure stage/bronze tables exist
  -> Schema evolution: detect new/removed/changed columns (P0-2)
  -> Column sync: auto-populate UdmTablesColumnsList + discover PKs from source
  -> Empty extraction guard: skip CDC if row count drops >90% (P1-1)
  -> CDC promotion (hash comparison, I/U/D with NULL PK filter)
  -> SCD2 promotion (2-step UPDATE+INSERT)
  -> CSV cleanup
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

import utils.configuration as config
from data_load.schema_utils import clear_column_metadata_cache
from data_load.bcp_loader import _safe_delete_csv
from extract.router import extract_full
from schema.column_sync import sync_columns
from observability.event_tracker import PipelineEventTracker
from orchestration.guards import run_extraction_guard
from orchestration.pipeline_steps import cleanup_csvs, run_cdc_promotion, run_scd2_promotion, dispatch_check_cdc_mode, run_parquet_write_step, run_parquet_replay_step, CDC_MODE_CHANGE_DETECT, CDC_MODE_PARQUET_SNAPSHOT, CDC_MODE_BOTH
from schema.evolution import SchemaEvolutionError, SchemaEvolutionResult, evolve_schema, validate_source_schema
from schema.table_creator import ensure_bronze_table, ensure_bronze_point_in_time_index, ensure_bronze_unique_active_index, ensure_stage_table
from orchestration.table_lock import acquire_table_lock, release_table_lock
from orchestration.pk_validation import NoPrimaryKeyError
from cdc.engine import ConcatCorruptionError
from utils.safe_concat import stabilize_extraction_dtypes

if TYPE_CHECKING:
    import polars as pl
    from orchestration.table_config import TableConfig

logger = logging.getLogger(__name__)

# P3-1: Small table size guard threshold.
# If extraction exceeds this row count, log WARNING suggesting reclassification.
SMALL_TABLE_SIZE_THRESHOLD = 100_000_000

# S-2: Absolute ceiling on first-run extraction for small tables.
# Prevents OOM when a large table is misconfigured as small (no SourceAggregateColumnName).
FIRST_RUN_MAX_ROWS = 100_000_000


def process_small_table(
    table_config: TableConfig,
    event_tracker: PipelineEventTracker,
    output_dir: str | Path | None = None,
    force: bool = False,
    refresh_pks: bool = False,
) -> bool:
    """Process a single small table through the full pipeline.

    Args:
        table_config: Table configuration.
        event_tracker: Event tracker for PipelineEventLog.
        output_dir: Directory for temp CSV files. Defaults to config.CSV_OUTPUT_DIR.
        force: If True, skip empty extraction guard (P1-1). For intentional reloads.
        refresh_pks: P1-10 — If True, re-discover PKs even if columns already populated.

    Returns:
        True if the pipeline succeeded, False if it failed.
    """
    if output_dir is None:
        output_dir = config.CSV_OUTPUT_DIR

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    table_name = table_config.source_object_name
    source_name = table_config.source_name

    # M-5: Clear INFORMATION_SCHEMA cache at the start of each table's
    # processing to handle schema evolution within a run.
    clear_column_metadata_cache()

    # P1-2: Acquire table lock to prevent concurrent runs
    lock_conn = acquire_table_lock(source_name, table_name)
    if lock_conn is None:
        logger.warning(
            "Skipping %s.%s — another pipeline run holds the lock",
            source_name, table_name,
        )
        # OBS-3: Write SKIPPED event so lock contention is visible in
        # PipelineEventLog. Without this, skipped tables are indistinguishable
        # from tables that were never scheduled.
        with event_tracker.track("TABLE_TOTAL", table_config) as skip_event:
            skip_event.status = "SKIPPED"
            skip_event.event_detail = "Lock held by another run"
        return False

    try:
        with event_tracker.track("TABLE_TOTAL", table_config) as total_event:
            # --- EXTRACT ---
            with event_tracker.track("EXTRACT", table_config) as extract_event:
                df, csv_path = extract_full(table_config, output_dir)
                extract_event.rows_processed = len(df)

            if len(df) == 0:
                logger.warning("Empty extraction for %s.%s — skipping", source_name, table_name)
                total_event.rows_processed = 0
                return True

            # P3-1: Size guard — warn if "small" table is growing large
            if len(df) > SMALL_TABLE_SIZE_THRESHOLD:
                logger.warning(
                    "P3-1 SIZE GUARD: %s.%s extracted %d rows (threshold=%d). "
                    "Consider reclassifying as a large table in UdmTablesList by setting "
                    "SourceAggregateColumnName to enable date-windowed extraction.",
                    source_name, table_name, len(df), SMALL_TABLE_SIZE_THRESHOLD,
                )

            # ST-1 + P2-12: Memory-based size guard — estimate memory for CDC comparison.
            # CDC loads both fresh + existing in memory simultaneously.
            if not _check_small_table_memory(df, source_name, table_name):
                total_event.rows_processed = len(df)
                total_event.status = "FAILED"
                total_event.error_message = (
                    f"ST-1: Estimated CDC peak memory exceeds hard ceiling "
                    f"({_MEM_HARD_CEILING_GB} GB). Reclassify as large table."
                )
                return False

            # --- E-11: PRE-PROCESSING SCHEMA VALIDATION ---
            # Catches column renames/drops before they propagate to CDC/SCD2.
            schema_warnings = validate_source_schema(table_config, df)
            if schema_warnings:
                # Missing columns are ERROR-level — skip table to prevent corruption
                has_missing = any("MISSING" in w for w in schema_warnings)
                if has_missing:
                    total_event.rows_processed = len(df)
                    total_event.status = "FAILED"
                    total_event.error_message = "; ".join(schema_warnings)
                    return False

            # --- ENSURE TABLES ---
            stage_created = ensure_stage_table(table_config, df)
            bronze_created = ensure_bronze_table(table_config, df)
            total_event.table_created = stage_created or bronze_created

            df = stabilize_extraction_dtypes(df, table_config)

            # --- SCHEMA EVOLUTION (P0-2) ---
            # Detect new/removed/changed columns. Runs on every run (not just first).
            # Raises SchemaEvolutionError on type changes (cannot auto-resolve).
            # B-3: Capture result to condition E-12 warning during schema migration runs.
            schema_result: SchemaEvolutionResult | None = None
            if not stage_created and not bronze_created:
                schema_result = evolve_schema(table_config, df)
                if schema_result.hash_affecting_change:
                    logger.warning(
                        "B-3: Schema migration detected for %s.%s — %d column(s) added: %s. "
                        "All row hashes will change (new column included in hash). "
                        "Expect mass CDC updates — this is correct behavior, not a bug.",
                        source_name, table_name,
                        len(schema_result.columns_added), schema_result.columns_added,
                    )

            # --- COLUMN SYNC ---
            # Auto-populate UdmTablesColumnsList + discover PKs from source.
            # Runs once per table (skips if already populated). Reloads columns
            # into table_config so pk_columns is available for CDC/SCD2.
            if stage_created or bronze_created:
                sync_columns(table_config, refresh_pks=refresh_pks)
            elif refresh_pks:
                # P1-10: Re-discover PKs even if columns already populated
                sync_columns(table_config, refresh_pks=True)

            # SCD-1: Ensure unique filtered index on Bronze to prevent duplicate
            # active rows from INSERT-first retry. Created once; idempotent.
            if table_config.pk_columns:
                ensure_bronze_unique_active_index(table_config, table_config.pk_columns)
                # V-9: Ensure point-in-time lookup index for historical queries.
                ensure_bronze_point_in_time_index(table_config, table_config.pk_columns)


            # --- NoPK-1: Reject keyless tables ---
            # After column sync, pk_columns should be populated if the table
            # has PKs in the source. If still empty, skip CDC/SCD2.
            if not table_config.pk_columns:
                if table_config.stage_load_tool == "Python-AppendOnly":
                    # NoPK-2: Append-only mode — skip CDC/SCD2, just load to Stage
                    logger.info(
                        "NoPK-2: %s.%s configured as Python-AppendOnly — "
                        "skipping CDC/SCD2 (no PK required). "
                        "Appending %d rows directly to Stage.",
                        source_name, table_name, len(df),
                    )
                    from cdc.engine import _add_cdc_columns, _write_and_load_cdc
                    from datetime import datetime, timezone

                    now = datetime.now(timezone.utc)
                    df_append = _add_cdc_columns(df, "A", now, event_tracker.batch_id)
                    _write_and_load_cdc(
                        df_append, table_config.stage_full_table_name,
                        output_dir, table_config, "append",
                    )
                    total_event.rows_processed = len(df)
                    return True
                else:
                    logger.error(
                        "NoPK-1: %s.%s has no PK columns after column sync. "
                        "Skipping CDC/SCD2 — CDC joins on empty column lists "
                        "produce undefined behavior. To fix: run "
                        "'python3 discover_pks.py --source %s --table %s' "
                        "or set IsPrimaryKey=1 manually in "
                        "General.dbo.UdmTablesColumnsList. "
                        "For genuinely keyless tables (logs, events), set "
                        "StageLoadTool='Python-AppendOnly' in UdmTablesList.",
                        source_name, table_name, source_name, table_name,
                    )
                    total_event.rows_processed = len(df)
                    total_event.status = "FAILED"
                    total_event.error_message = (
                        f"NoPK-1: No PK columns configured for "
                        f"{source_name}.{table_name}. "
                        f"Run discover_pks.py or set StageLoadTool='Python-AppendOnly'."
                    )
                    return False

            # --- P1-1: EMPTY EXTRACTION GUARD ---
            if not force and not stage_created:
                guard_ok = run_extraction_guard(
                    table_config, len(df), event_tracker.batch_id,
                    first_run_ceiling=FIRST_RUN_MAX_ROWS,
                    # Per-table override from UdmTablesList.MaxRowsPerDay.
                    # NULL → keep current behavior.
                    max_rows_per_day_override=table_config.max_rows_per_day,
                )
                if not guard_ok:
                    total_event.rows_processed = len(df)
                    total_event.status = "FAILED"
                    total_event.error_message = (
                        f"Extraction row count dropped >90% vs previous run. "
                        f"Fresh={len(df)}. Use --force to override."
                    )
                    return False

            # Phase 2 of cdc_root_cause_blueprint.md: source-count integrity.
            # Compares len(df) to source COUNT(*) right now — catches partial
            # extractions that the historical-baseline guard above misses
            # (first-run case, or steady-state under-extraction). Disabled
            # via CDC_SOURCE_COUNT_CHECK=0; tolerance via
            # CDC_SOURCE_COUNT_TOLERANCE_PCT (default 0.5%).
            if not force:
                from extract.source_count_check import check_source_count_integrity
                count_result = check_source_count_integrity(df, table_config)
                if not count_result.ok:
                    total_event.rows_processed = len(df)
                    total_event.status = "FAILED"
                    total_event.error_message = (
                        f"Source-count integrity FAILED: extracted "
                        f"{count_result.extracted_count} rows, source has "
                        f"{count_result.source_count} "
                        f"(delta {count_result.delta_pct:.4f}% > "
                        f"{count_result.tolerance_pct:.4f}% tolerance). "
                        f"Use --force to override after confirming source state."
                    )
                    return False

            # OBS-1: BCP_LOAD event removed — it wrapped an empty block and tracked
            # no actual BCP work. BCP timing is captured within CDC_PROMOTION
            # (staging table loads) and SCD2_PROMOTION (Bronze INSERT/UPDATE loads).

            # --- Delete extraction CSV immediately (MEM-2) ---
            # The extraction CSV is never consumed by CDC or SCD2 — they work
            # from the in-memory DataFrame. For CCM tables with XML columns,
            # this CSV can be 10+ GB. Deleting it before CDC frees disk/tmpfs
            # space during the memory-intensive CDC anti-join + SCD2 phases.
            _safe_delete_csv(csv_path)

            # --- B-544 + B-552: 3-MODE CDC DISPATCH per D63 + D125 ---
            cdc_mode = dispatch_check_cdc_mode(table_config)

            # Small tables lack a SourceAggregateColumnName (date column),
            # so business_date for Parquet Hive partition uses today() —
            # one Parquet snapshot per pipeline run (matches small-table
            # full-refresh extraction semantic).
            from datetime import date as _date
            small_table_business_date = _date.today()

            # 'both' or 'parquet_snapshot': write Parquet BEFORE legacy CDC.
            # Per CLAUDE.md Do-NOT rule.
            parquet_write_result = None
            if cdc_mode in (CDC_MODE_PARQUET_SNAPSHOT, CDC_MODE_BOTH):
                parquet_write_result = run_parquet_write_step(
                    table_config, df, event_tracker,
                    business_date=small_table_business_date,
                )

            # B-552 v1: 'parquet_snapshot' end-to-end Parquet→replay→SCD2 path.
            # Same architecture as large_tables.py per D125 plan §5.2 +
            # D2/D115 source-exactness invariants.
            if cdc_mode == CDC_MODE_PARQUET_SNAPSHOT:
                # Release extraction df BEFORE replay loads its own from disk
                extracted_row_count = len(df)
                del df
                import gc; gc.collect()

                cdc_result = run_parquet_replay_step(
                    table_config, parquet_write_result, event_tracker,
                    business_date=small_table_business_date,
                )
                # B-552 v1: small-tables canonical path is targeted=False.
                # run_scd2() detects deletes via Bronze anti-join (full path).
                run_scd2_promotion(
                    table_config, cdc_result, event_tracker, output_dir,
                )
                # CSV cleanup still required even on parquet_snapshot path
                with event_tracker.track("CSV_CLEANUP", table_config) as cleanup_event:
                    cleaned = cleanup_csvs(output_dir, table_config)
                    cleanup_event.rows_processed = cleaned
                total_event.rows_processed = extracted_row_count
                logger.info(
                    "Successfully processed %s.%s (parquet_snapshot mode)",
                    source_name, table_name,
                )
                return True  # Skip legacy CDC path for 'parquet_snapshot' mode

            # --- CDC PROMOTION — runs for 'change_detect' + 'both' ---
            cdc_result = run_cdc_promotion(
                table_config, df, event_tracker, schema_result, output_dir,
            )

            # MEM-3: Release extraction DataFrame before SCD2 to reduce peak memory.
            # Mirrors P2-10 in large_tables.py. CDC has captured everything needed
            # in cdc_result.df_current and cdc_result.deleted_pks.
            extracted_row_count = len(df)
            del df
            import gc; gc.collect()

            # --- SCD2 PROMOTION ---
            run_scd2_promotion(
                table_config, cdc_result, event_tracker, output_dir,
            )

            # --- CSV CLEANUP ---
            with event_tracker.track("CSV_CLEANUP", table_config) as cleanup_event:
                cleaned = cleanup_csvs(output_dir, table_config)
                cleanup_event.rows_processed = cleaned

            total_event.rows_processed = extracted_row_count

        logger.info("Successfully processed %s.%s", source_name, table_name)
        return True
    
    except NoPrimaryKeyError as e:
        logger.error(
            "NoPK-1: Skipping %s.%s — %s",
            table_config.source_name, table_config.source_object_name, e,
        )
        total_event.status = "FAILED"
        total_event.error_message = str(e)
        return False
    
    except ConcatCorruptionError as e:
        # P0-7d: Concat corruption detected — skip table, don't retry
        logger.error("P0-7d: %s — skipping table", e)
        total_event.status = "FAILED"
        total_event.error_message = str(e)
        return False

    except SchemaEvolutionError:
        logger.exception(
            "Schema evolution error for %s.%s — skipping table", source_name, table_name
        )
        return False
    except Exception:
        logger.exception("Failed to process %s.%s", source_name, table_name)
        return False
    finally:
        release_table_lock(lock_conn, source_name, table_name)


# ---------------------------------------------------------------------------
# P2-12: Memory-based size guard
# ---------------------------------------------------------------------------
#
# Sized for the production server: 64 GB physical RAM, ~49 GB usable
# (config.MAX_RSS_GB). Hard ceiling 40 GB leaves ~9 GB headroom for
# concurrent workers, BCP subprocesses, and connection pools. Warn
# threshold 25 GB flags tables that should probably be reclassified as
# large (windowed) before they bump the ceiling on a busier day.
#
# Anti-join peak = ~3× DataFrame size (both frames + hash table) — so a
# 40 GB ceiling caps the input DataFrame at ~13 GB. Tables larger than
# that need SourceAggregateColumnName set in UdmTablesList to flow
# through the large-table windowed path.
#
# Both can be overridden via env vars on systems with different capacity:
#   ST_MEM_WARN_GB    (default 25.0)
#   ST_MEM_CEILING_GB (default 40.0)

_MEM_WARN_THRESHOLD_GB = float(os.getenv("ST_MEM_WARN_GB", "25.0"))
# ST-1: Hard ceiling in GB: ERROR and skip if estimated peak memory exceeds this.
_MEM_HARD_CEILING_GB = float(os.getenv("ST_MEM_CEILING_GB", "40.0"))


def _check_small_table_memory(
    df: pl.DataFrame,
    source_name: str,
    table_name: str,
) -> bool:
    """P2-12 + ST-1: Check estimated CDC comparison memory.

    CDC requires both the fresh extraction and the full Stage read in
    memory simultaneously. Anti-join peaks at ~3× DataFrame size.

    Returns:
        True if safe to proceed, False if memory would exceed hard ceiling.
    """
    estimated_bytes = df.estimated_size("b")
    # Anti-join peak = ~3× DataFrame size (fresh + existing + hash table)
    estimated_peak_gb = (estimated_bytes * 3) / (1024 ** 3)

    if estimated_peak_gb > _MEM_HARD_CEILING_GB:
        logger.error(
            "ST-1 MEMORY GUARD: %s.%s estimated CDC peak memory %.1f GB "
            "(hard ceiling=%.1f GB). %d rows × %d cols. "
            "This table MUST be reclassified as a large table by setting "
            "SourceAggregateColumnName in UdmTablesList. Skipping.",
            source_name, table_name, estimated_peak_gb,
            _MEM_HARD_CEILING_GB, len(df), len(df.columns),
        )
        return False

    if estimated_peak_gb > _MEM_WARN_THRESHOLD_GB:
        logger.warning(
            "P2-12 MEMORY GUARD: %s.%s estimated CDC peak memory %.1f GB "
            "(warn threshold=%.1f GB). %d rows × %d cols. "
            "Consider reclassifying as large table or reducing --workers.",
            source_name, table_name, estimated_peak_gb,
            _MEM_WARN_THRESHOLD_GB, len(df), len(df.columns),
        )

    return True