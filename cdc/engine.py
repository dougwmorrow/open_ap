"""Polars CDC: hash comparison, detect inserts/updates/deletes.

Provides two modes:
  - run_cdc(): Full comparison (small tables). Detects I/U/D across all rows.
  - run_cdc_windowed(): Date-scoped comparison (large tables). Only compares rows
    within the extraction window. Delete detection scoped to window (P1-4).

Algorithm:
  - Filter rows with NULL PKs (P0-4: prevent duplicate inserts)
  - Anti-join on PKs (inserts): rows in fresh but not in existing
  - Inner-join + hash compare (updates/unchanged): rows in both, hash changed vs same
  - Reverse anti-join (deletes): rows in existing but not in fresh (window-scoped for large)

CDC columns: _cdc_operation (I/U/D), _cdc_valid_from/to, _cdc_is_current, _cdc_batch_id

H-4 NOTE — No-op source updates:
  Oracle no-op updates (UPDATE SET col=col) and SQL Server no-op updates still
  generate redo/undo and change tracking metadata. These rows are extracted and
  compared, but the hash comparison correctly identifies them as unchanged (same
  hash before and after). The extraction work is wasted but harmless — no data
  corruption, no false positives. Accept as-is.

T-3 NOTE — Oracle metadata-only DEFAULT changes:
  Oracle 11g+ metadata-only DEFAULT values are transparent to SELECT * — existing
  rows return the default without physical updates. If the DEFAULT definition
  changes, old rows return the old default, new rows the new one. The pipeline
  correctly detects this as a real data difference (hash changes). Expect a
  one-time CDC update surge after any source DEFAULT change. This is correct
  behavior, not a bug.

C-6 KNOWN LIMITATION — INSERT-first timing gap:
  The P0-9 crash safety design creates a deliberate window where duplicate
  _cdc_is_current=1 rows exist in Stage:
    t0: CDC INSERT new versions (BCP load) — both old and new are current=1
    t1: CDC expire old versions (UPDATE JOIN) — old versions set to current=0
  The window between t0 and t1 is 30-60 seconds for typical loads. Any consumer
  reading Stage during this window sees duplicate current rows per affected PK.
  Downstream consumers should either:
    (a) Wait for pipeline completion (use PipelineEventLog as trigger)
    (b) Query with GROUP BY pk_columns HAVING COUNT(*) = 1
    (c) Tolerate the transient duplicates

B-5 AUDIT (2026-02-23) — Polars join validation bug (#19624):
  Audited all .join() calls in this module. None use the `validate` parameter.
  All joins use only `on`, `how`, and `suffix`. Polars #19624 (false errors when
  `validate` is used with NULL keys) does not apply. Additionally,
  `_filter_null_pks()` runs before all CDC joins, so NULL PKs are never present
  in join inputs. No action required.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import json

import polars as pl
import utils.configuration as config
from utils.connections import cursor_for, quote_identifier, quote_table
from data_load import bcp_loader
from data_load.bcp_csv import validate_schema_before_concat, write_bcp_csv
from data_load.sanitize import cast_bit_columns, reorder_columns_for_bcp, sanitize_strings
from data_load.schema_utils import align_pk_dtypes, get_column_types
from extract.udm_connectorx_extractor import (
    read_stage_table,
    read_stage_table_windowed,
    table_exists,
)

from utils.safe_concat import (
    safe_concat as _safe_concat,
    conform_to_schema,
    build_target_schema,
    CDC_SCHEMA,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from orchestration.table_config import TableConfig

logger = logging.getLogger(__name__)

@dataclass
class CDCResult:
    """Results from CDC comparison."""

    inserts: int = 0
    updates: int = 0
    deletes: int = 0
    unchanged: int = 0
    null_pk_rows: int = 0
    df_current: pl.DataFrame | None = None
    pk_columns: list[str] | None = None
    # P0-11: Deleted PKs from windowed CDC, needed for targeted SCD2 Bronze close.
    # Only populated by run_cdc_windowed() — run_cdc() doesn't need it because
    # run_scd2() reads ALL active Bronze rows and catches deletes via anti-join.
    deleted_pks: pl.DataFrame | None = None
    # Phase 2 of cdc_root_cause_blueprint.md: VerificationResult.as_metadata_dict()
    # output from verify-before-close. None when no candidate deletes were
    # generated this run; populated otherwise so PipelineEventLog can record
    # candidate_count, confirmed_count, false_negative_count, skipped, etc.
    verify_before_close: dict | None = None


@dataclass
class CDCContext:
    """Parameterizes differences between full and windowed CDC."""

    read_existing: Callable[[], pl.DataFrame]
    track_deleted_pks: bool
    log_label: str   # "CDC" or "Windowed CDC"
    log_window: str  # "" or " [2025-02-15, 2025-02-16)"

# P0-4b: Sentinel value for empty-string PKs that BCP would convert to NULL.
# Must be deterministic (same value every run) so CDC hash comparison and
# SCD2 PK joins produce stable results. Using a visually distinct sentinel
# so it's obvious in queries that this is a substitution, not source data.
_BLANK_PK_SENTINEL = "<BLANK>"


def _cdc_now_ms() -> datetime:
    """Return ``datetime.now()`` as **naive UTC wall time, millisecond
    precision**.

    The expire step's ``_cdc_valid_from < batch_valid_from`` filter
    requires that the timestamp BCP writes to the new rows is bit-identical
    to the timestamp pyodbc sends as the ``batch_valid_from`` parameter.

    Two independent precision drops would otherwise corrupt the comparison:

    * BCP writes datetime with ``'%Y-%m-%d %H:%M:%S.%3f'`` per the BCP CSV
      Contract (CLAUDE.md) — that's millisecond precision. A
      ``20:30:47.948992`` Python datetime lands in Stage as
      ``20:30:47.948``.
    * pyodbc preserves Python datetime microseconds end-to-end. The same
      ``20:30:47.948992`` arrives at SQL Server intact.

    Strict ``<`` then matches the just-inserted row
    (``20:30:47.948 < 20:30:47.948992``) and the expire UPDATE clobbers
    its own batch's writes. The fix is to truncate at the source so the
    BCP-stored value and pyodbc parameter are identical.

    Naive (no tzinfo) is the second half of the SCD2-P1-f invariant:
    ``DATETIME2 = DATETIMEOFFSET`` triggers an implicit timezone
    conversion in SQL Server when the parameter carries tz info — the
    BCP-stored value is naive UTC wall time, and the parameter must
    match.
    """
    n = datetime.now(timezone.utc).replace(tzinfo=None)
    return n.replace(microsecond=(n.microsecond // 1000) * 1000)


def _coerce_blank_pks(
    df: pl.DataFrame,
    pk_columns: list[str],
    table_config: TableConfig,
) -> pl.DataFrame:
    """P0-4b: Replace empty-string PK values with a deterministic sentinel.

    BCP character mode converts '' to NULL in SQL Server. NULL PKs break
    CDC anti-joins (NULL != NULL → perpetual re-insert) and SCD2 business
    key matching. Rather than filtering these rows out (data loss), coerce
    blank PK strings to a known sentinel that survives BCP round-tripping.

    Only applies to string-typed PK columns. Non-string PKs are unaffected.
    """
    coercions = []
    coerced_cols = []

    for col in pk_columns:
        if df[col].dtype in (pl.Utf8, pl.String):
            blank_count = df.filter(pl.col(col).str.strip_chars() == "").height
            if blank_count > 0:
                coercions.append(
                    pl.when(pl.col(col).str.strip_chars() == "")
                    .then(pl.lit(_BLANK_PK_SENTINEL))
                    .otherwise(pl.col(col))
                    .alias(col)
                )
                coerced_cols.append((col, blank_count))

    if coercions:
        df = df.with_columns(coercions)
        for col, count in coerced_cols:
            logger.info(
                "P0-4b: Coerced %d blank PK values in [%s] to '%s' for %s.%s "
                "— prevents BCP empty-string-to-NULL conversion that would "
                "break CDC/SCD2 joins.",
                count, col, _BLANK_PK_SENTINEL,
                table_config.source_name,
                table_config.source_object_name,
            )

    return df

def run_cdc(
    table_config: TableConfig,
    df_fresh: pl.DataFrame,
    batch_id: int,
    output_dir: str | Path,
) -> CDCResult:
    """Run CDC comparison: detect inserts, updates, and deletes.

    Args:
        table_config: Table configuration with PK columns.
        df_fresh: Fresh extraction DataFrame (already has _row_hash, _extracted_at).
        batch_id: Pipeline batch ID for _cdc_batch_id.
        output_dir: Directory for staging CSV files.

    Returns:
        CDCResult with counts and df_current (all current CDC rows after changes applied).
    """
    # Phase 1 of cdc_root_cause_blueprint.md: log Stage↔Bronze drift before
    # CDC mutates Stage. Read-only, never blocks. Set CDC_DRIFT_DETECTION=0
    # to skip.
    from cdc.drift_detector import log_stage_bronze_drift
    log_stage_bronze_drift(table_config)

    stage_table = table_config.stage_full_table_name
    ctx = CDCContext(
        read_existing=lambda: read_stage_table(stage_table),
        track_deleted_pks=False,
        log_label="CDC",
        log_window="",
    )
    return _run_cdc_core(table_config, df_fresh, batch_id, output_dir, ctx)


def _run_cdc_core(
    table_config: TableConfig,
    df_fresh: pl.DataFrame,
    batch_id: int,
    output_dir: str | Path,
    ctx: CDCContext,
) -> CDCResult:
    """Shared CDC engine for both full and windowed modes.

    Called by run_cdc() and run_cdc_windowed() — not intended for direct use.
    Differences between full and windowed CDC are parameterized via CDCContext.
    """
    result = CDCResult()
    pk_columns = table_config.pk_columns
    result.pk_columns = pk_columns
    # CDC-NOW-MS: naive UTC wall time, millisecond precision. See
    # _cdc_now_ms() docstring — bypassing this re-introduces the expire
    # double-close bug that produced alternating I/U on every PK that
    # updated. Do NOT replace with datetime.now() / datetime.now(timezone.utc).
    now = _cdc_now_ms()

    stage_table = table_config.stage_full_table_name

    if not pk_columns:
        logger.warning("No PK columns for %s — skipping %s", table_config.source_object_name, ctx.log_label)
        return result

    # S-4: Validate PK columns exist in df_fresh before proceeding
    missing_pks = [c for c in pk_columns if c not in df_fresh.columns]
    if missing_pks:
        logger.error(
            "S-4: PK columns %s not found in extraction for %s.%s. "
            "Available columns: %s. This may indicate a source schema change. "
            "Use --refresh-pks to re-discover PKs from the source.",
            missing_pks, table_config.source_name,
            table_config.source_object_name, df_fresh.columns,
        )
        return result

    # --- P0-4b: Coerce blank string PKs to sentinel (before NULL filter) ---
    df_fresh = _coerce_blank_pks(df_fresh, pk_columns, table_config)

    # --- P0-4: Filter rows with true NULL PKs ---
    df_fresh = _filter_null_pks(df_fresh, pk_columns, table_config, result)

    # --- S-1: Source PK duplicate guard ---
    df_fresh = _dedup_source_pks(df_fresh, pk_columns, table_config)

    if len(df_fresh) == 0:
        logger.warning(
            "No rows remaining after NULL PK filter for %s — skipping %s",
            table_config.source_object_name, ctx.log_label,
        )
        return result

    # First run: table doesn't exist yet — all rows are inserts
    if not table_exists(stage_table):
        logger.info(
            "Stage table %s doesn't exist — all %d rows are inserts%s",
            stage_table, len(df_fresh), ctx.log_window,
        )
        result.inserts = len(df_fresh)

        df_inserts = _add_cdc_columns(df_fresh, "I", now, batch_id)
        result.df_current = df_inserts

        _write_and_load_cdc(df_inserts, stage_table, output_dir, table_config, "inserts")
        return result

    # Read existing current rows from Stage
    df_existing = ctx.read_existing()
    logger.info("Existing CDC current rows%s: %d", ctx.log_window, len(df_existing))

    # L-1: Deduplicate Stage current rows (crash recovery may leave duplicates)
    df_existing = _dedup_stage_current(df_existing, pk_columns, table_config)

    if len(df_existing) == 0:
        # No current rows — all fresh rows are inserts
        result.inserts = len(df_fresh)
        df_inserts = _add_cdc_columns(df_fresh, "I", now, batch_id)
        result.df_current = df_inserts
        _write_and_load_cdc(df_inserts, stage_table, output_dir, table_config, "inserts")
        return result

    # --- P0-12: Align PK dtypes before joins ---
    df_fresh, df_existing = align_pk_dtypes(
        df_fresh, df_existing, pk_columns, context=ctx.log_label,
    )

    # --- Detect changes ---

    # P-6: Use lazy + streaming engine for anti-joins to reduce peak memory.
    # Polars v1.32+ supports native streaming anti-joins (PR #21937).
    # The streaming engine uses morsel-driven parallelism, avoiding
    # materialization of the full join result in memory.

    # INSERTS: rows in fresh but not in existing (anti-join on PKs)
    df_new = (
        df_fresh.lazy()
        .join(df_existing.lazy(), on=pk_columns, how="anti")
        .collect(engine="streaming")
    )
    result.inserts = len(df_new)

    # DELETES: rows in existing but not in fresh (reverse anti-join)
    # P1-4 (windowed): Only detects deletes WITHIN the extraction window,
    # not rows outside the window. Rows older than the window are untouched.
    df_deleted = (
        df_existing.lazy()
        .join(df_fresh.lazy(), on=pk_columns, how="anti")
        .collect(engine="streaming")
    )

    # Phase 2 of cdc_root_cause_blueprint.md: verify candidate-delete PKs
    # against the source before the expire step closes their Stage current
    # rows. False positives (PKs the extractor missed but the source still
    # has) are suppressed — Stage stays current, the next run hashes the
    # row normally. See cdc/source_verifier.py and CLAUDE.md "Do NOT".
    if len(df_deleted) > 0:
        from cdc.source_verifier import verify_deletes_against_source
        verification = verify_deletes_against_source(
            candidate_pks=df_deleted.select(pk_columns),
            pk_columns=pk_columns,
            table_config=table_config,
            windowed=ctx.track_deleted_pks,
        )
        result.verify_before_close = verification.as_metadata_dict()
        if not verification.skipped and verification.false_negative_count > 0:
            # Filter df_deleted to only the source-confirmed deletes via a
            # semi-join on confirmed_deletes' PK set. Keeps original row
            # ordering and any extra columns df_deleted carries.
            confirmed = verification.confirmed_deletes.select(pk_columns)
            df_deleted = df_deleted.join(confirmed, on=pk_columns, how="semi")

    result.deletes = len(df_deleted)

    # P0-11: Capture deleted PKs for targeted SCD2 Bronze close (windowed only).
    # Without this, windowed deletes never propagate to Bronze because
    # run_scd2_targeted() only reads Bronze rows for PKs in df_current
    # (which excludes deleted PKs).
    if ctx.track_deleted_pks and result.deletes > 0:
        result.deleted_pks = df_deleted.select(pk_columns)

    # UPDATES vs UNCHANGED: inner join on PKs, compare _row_hash
    df_matched = df_fresh.join(
        df_existing.select(pk_columns + ["_row_hash"]),
        on=pk_columns,
        how="inner",
        suffix="_existing",
    )

    # P0-10: NULL hash guards — treat NULL hashes as "changed" to prevent
    # silent misclassification when hashes are missing (partial load, non-pipeline path).
    changed_mask = (
        (pl.col("_row_hash") != pl.col("_row_hash_existing"))
        | pl.col("_row_hash").is_null()
        | pl.col("_row_hash_existing").is_null()
    )
    df_updated = df_matched.filter(changed_mask).drop("_row_hash_existing")
    df_unchanged = df_matched.filter(~changed_mask).drop("_row_hash_existing")

    result.updates = len(df_updated)
    result.unchanged = len(df_unchanged)

    # P0-12: Count validation — all fresh rows must be accounted for
    accounted = result.inserts + result.updates + result.unchanged
    if accounted != len(df_fresh):
        logger.error(
            "P0-12 COUNT MISMATCH in %s %s%s: "
            "inserts(%d) + updates(%d) + unchanged(%d) = %d, "
            "but fresh has %d rows. Possible PK dtype mismatch causing silent join failure.",
            ctx.log_label, table_config.source_object_name, ctx.log_window,
            result.inserts, result.updates, result.unchanged, accounted, len(df_fresh),
        )

    logger.info(
        "%s %s%s: inserts=%d, updates=%d, deletes=%d, unchanged=%d",
        ctx.log_label, table_config.source_object_name, ctx.log_window,
        result.inserts, result.updates, result.deletes, result.unchanged,
    )
    # O-2: Structured JSON for downstream alerting without regex parsing.
    logger.info(
        "O-2_CDC: %s",
        json.dumps({
            "signal": "cdc_result",
            "source": table_config.source_name,
            "table": table_config.source_object_name,
            "mode": ctx.log_label.lower().replace(" ", "_"),
            "inserts": result.inserts,
            "updates": result.updates,
            "deletes": result.deletes,
            "unchanged": result.unchanged,
            "null_pk_rows": result.null_pk_rows,
            "total_fresh": len(df_fresh),
        }),
    )

    # --- Apply changes ---
    # P0-9: INSERT first, THEN expire. A crash after insert but before expire
    # leaves duplicate "current" rows (recoverable), instead of zero current
    # rows (data loss that cascades as mass re-insert + SCD2 re-versioning).

    # P2-7: Build CDC-annotated DataFrames once and reuse for both changes
    # list and current_parts to avoid duplicate memory allocation.
    df_insert_cdc = _add_cdc_columns(df_new, "I", now, batch_id) if result.inserts > 0 else None
    df_update_cdc = _add_cdc_columns(df_updated, "U", now, batch_id) if result.updates > 0 else None

    # 1. Insert new CDC rows (inserts + updates) with _cdc_is_current=1
    changes: list[pl.DataFrame] = []
    if df_insert_cdc is not None:
        changes.append(df_insert_cdc)
    if df_update_cdc is not None:
        changes.append(df_update_cdc)

    if changes:
        # W-7: Validate schemas match before concat (prevent silent type coercion).
        validate_schema_before_concat(changes, f"{ctx.log_label} changes for {table_config.source_object_name}")
        df_changes = pl.concat(changes)
        _write_and_load_cdc(df_changes, stage_table, output_dir, table_config, "changes")


    # 2. Mark expired rows (updates + deletes) as _cdc_is_current=0
    if result.updates > 0 or result.deletes > 0:
        if result.updates > 0 and result.deletes > 0:
            pk_parts = [df_updated.select(pk_columns), df_deleted.select(pk_columns)]
            validate_schema_before_concat(pk_parts, f"{ctx.log_label} expire PKs for {table_config.source_object_name}")
            expired_pks = pl.concat(pk_parts)
        else:
            expired_pks = df_updated.select(pk_columns) if result.updates > 0 else df_deleted.select(pk_columns)
        # FIX: Pass batch_valid_from=now to prevent double-expire.
        # The INSERT step above added new _cdc_is_current=1 rows with
        # _cdc_valid_from=now. Without this filter, the expire UPDATE
        # matches both old and new rows for updated PKs.
        _expire_cdc_rows(expired_pks, pk_columns, stage_table, now, output_dir, table_config,
                         batch_valid_from=now)

    # Build df_current: unchanged existing rows + new inserts + updated rows
    current_parts = []

    # Build df_current: unchanged existing rows + new inserts + updated rows
    #
    # P0-7b/c: Use conform_to_schema to normalize ALL parts to a single
    # canonical schema BEFORE concat. This eliminates:
    #   - P0-7 NULL inflation (missing columns filled with TYPED nulls from
    #     known schema, not injected by _safe_concat's untyped pl.lit(None))
    #   - C-3 dtype drift (all CDC columns cast to CDC_SCHEMA types)
    #   - The need for _validate_concat_columns post-hoc correction
    #
    # The target schema is derived from df_fresh (current extraction — 
    # authoritative for source column dtypes) + CDC_SCHEMA (canonical CDC
    # column types). This means unchanged_existing rows (read from Stage
    # with potentially stale dtypes) get cast to match the current schema.

    current_parts = []
    if result.unchanged > 0:
        unchanged_existing = df_existing.join(df_unchanged, on=pk_columns, how="semi")
        current_parts.append(unchanged_existing)
    if df_insert_cdc is not None:
        current_parts.append(df_insert_cdc)
    if df_update_cdc is not None:
        current_parts.append(df_update_cdc)

    if current_parts:
        # P0-7b: Build canonical target schema from fresh extraction + CDC columns
        target_schema = build_target_schema(df_fresh)
        context = f"CDC current_parts for {table_config.source_name}.{table_config.source_object_name}"

        # P0-7c: Conform each part to the target schema
        conformed = [
            conform_to_schema(part, target_schema, context=context)
            for part in current_parts
        ]

        # Strict vertical concat — all parts now have identical schemas.
        # If this raises SchemaError, it's a bug in conform_to_schema
        # (should never happen — all parts are explicitly aligned).
        try:
            result.df_current = pl.concat(conformed, how="vertical")
        except pl.exceptions.SchemaError as e:
            # Fallback: log the error and use safe_concat as safety net.
            # This should never fire, but if it does, we don't want to
            # crash the pipeline — safe_concat handles schema differences.
            logger.error(
                "P0-7b: Strict vertical concat FAILED after conform_to_schema "
                "for %s — falling back to safe_concat. Error: %s. "
                "This is a bug in conform_to_schema — investigate.",
                context, e,
            )
            result.df_current = _safe_concat(current_parts)
            result.df_current = _validate_concat_columns(
                result.df_current, df_fresh, table_config
            )

        # W-12: Release over-allocated memory after filter/join/concat operations.
        if len(result.df_current) > 100_000:
            result.df_current.shrink_to_fit(in_place=True)
    else:
        result.df_current = pl.DataFrame()

    return result


# ---------------------------------------------------------------------------
# P0-4: NULL PK filter
# ---------------------------------------------------------------------------

# V-13: Percentage threshold for NULL PK escalation to ERROR.
# If more than this fraction of extracted rows have NULL PKs, escalate to ERROR.
NULL_PK_ERROR_THRESHOLD = 0.01  # 1%


def _filter_null_pks(
    df: pl.DataFrame,
    pk_columns: list[str],
    table_config: TableConfig,
    result: CDCResult,
) -> pl.DataFrame:
    """Filter out rows with NULL values in PK columns.

    NULL PKs cause Polars anti-join to always classify those rows as inserts
    (NULL != NULL), creating duplicates every run.

    V-13: Escalates to ERROR if NULL PKs exceed 1% of total rows (likely
    source data quality issue rather than occasional NULLs).
    """
    null_mask = pl.lit(False)
    for col in pk_columns:
        null_mask = null_mask | pl.col(col).is_null()

    null_count = df.filter(null_mask).height

    if null_count > 0:
        # P3-12: Per-column NULL breakdown for actionable debugging
        null_breakdown = {}
        for col in pk_columns:
            col_nulls = df[col].null_count()
            if col_nulls > 0:
                null_breakdown[col] = col_nulls

        # V-13: Percentage-based escalation — if NULLs exceed threshold,
        # this is likely a source data quality problem, not occasional NULLs.
        total_rows = len(df)
        null_pct = null_count / total_rows if total_rows > 0 else 0

        if null_pct > NULL_PK_ERROR_THRESHOLD:
            logger.error(
                "V-13: %d rows (%.2f%%) with NULL PK columns in %s.%s — "
                "exceeds %.0f%% threshold. Likely source data quality issue. "
                "Filtering out to prevent duplicate inserts. "
                "PK columns checked: %s. NULL breakdown: %s",
                null_count, null_pct * 100,
                table_config.source_name,
                table_config.source_object_name,
                NULL_PK_ERROR_THRESHOLD * 100,
                pk_columns,
                null_breakdown,
            )
        else:
            logger.warning(
                "Found %d rows (%.2f%%) with NULL PK columns in %s.%s — "
                "filtering out to prevent duplicate inserts. "
                "PK columns checked: %s. NULL breakdown: %s",
                null_count, null_pct * 100,
                table_config.source_name,
                table_config.source_object_name,
                pk_columns,
                null_breakdown,
            )

        # P3-12: Log sample of filtered rows (first 5) for debugging
        df_nulls = df.filter(null_mask)
        if len(df_nulls) > 0:
            sample = df_nulls.head(5).select(pk_columns)
            logger.info(
                "P3-12: Sample NULL PK rows for %s.%s (first %d of %d): %s",
                table_config.source_name, table_config.source_object_name,
                min(5, len(df_nulls)), null_count,
                sample.to_dicts(),
            )

        result.null_pk_rows = null_count
        df = df.filter(~null_mask)

    return df


# ---------------------------------------------------------------------------
# S-1: Source PK duplicate guard
# ---------------------------------------------------------------------------


def _parse_duplicate_resolution_order(
    raw: str | None,
) -> list[tuple[str, bool]]:
    """R-8: parse ``UdmTablesList.DuplicateResolutionOrder`` into ORDER BY pieces.

    Accepts a comma-separated column list. Each entry may carry an explicit
    direction: ``DATELASTMAINT DESC`` or ``UdmEffectiveDateTime ASC``. When
    omitted the direction defaults to ``DESC`` — legacy proc convention is
    "newest wins" on the typical ``DATELASTMAINT, UdmEffectiveDateTime`` tuple.

    Returns a list of ``(column_name, descending: bool)`` pairs. Empty list
    when the input is None/blank.
    """
    if raw is None:
        return []
    parts: list[tuple[str, bool]] = []
    for piece in str(raw).split(","):
        piece = piece.strip()
        if not piece:
            continue
        tokens = piece.split()
        col = tokens[0]
        direction = tokens[1].upper() if len(tokens) > 1 else "DESC"
        descending = direction != "ASC"
        parts.append((col, descending))
    return parts


def _apply_duplicate_resolution_order(
    df: pl.DataFrame,
    pk_columns: list[str],
    ordering: list[tuple[str, bool]],
    *,
    context: str,
) -> pl.DataFrame:
    """R-8: deterministically dedup ``df`` by PK using a tiebreak ORDER BY.

    Sorts by the configured columns (filtered to those present in ``df``)
    and keeps the first row per PK. When ``ordering`` is empty or no
    configured columns exist in ``df``, returns ``df.unique(subset=pk_columns,
    keep="last")`` — the previous arbitrary-but-stable behavior — and logs
    a WARNING so the operator knows the configured order didn't apply.

    Args:
        df: DataFrame with PK and (ideally) the ordering columns.
        pk_columns: business key columns.
        ordering: parsed ``DuplicateResolutionOrder`` (column, descending).
        context: human label for log messages (e.g. table name + step).
    """
    if not ordering:
        return df.unique(subset=pk_columns, keep="last")

    df_cols = set(df.columns)
    applicable = [(c, d) for c, d in ordering if c in df_cols]
    missing = [c for c, _ in ordering if c not in df_cols]
    if missing:
        logger.warning(
            "R-8: DuplicateResolutionOrder for %s references %d column(s) not "
            "in DataFrame: %s. Dropping missing names; using remaining order.",
            context, len(missing), missing,
        )
    if not applicable:
        logger.warning(
            "R-8: No DuplicateResolutionOrder columns found in DataFrame for %s "
            "(configured: %s). Falling back to non-deterministic unique(keep=last).",
            context, [c for c, _ in ordering],
        )
        return df.unique(subset=pk_columns, keep="last")

    sort_cols = [c for c, _ in applicable]
    descending = [d for _, d in applicable]
    return (
        df.sort(by=sort_cols, descending=descending, nulls_last=True)
          .unique(subset=pk_columns, keep="first", maintain_order=True)
    )


def _dedup_source_pks(
    df: pl.DataFrame,
    pk_columns: list[str],
    table_config: TableConfig,
) -> pl.DataFrame:
    """S-1 + R-8: detect and deduplicate source rows with non-unique PKs.

    Non-unique PKs in source data cause Cartesian products in inner-joins,
    leading to compounding duplicates in Stage and Bronze. Deduplicate by
    the configured ``DuplicateResolutionOrder`` when present (R-8) — typical
    DNA convention is ``DATELASTMAINT,UdmEffectiveDateTime`` so the most
    recently-touched row wins. Without configuration, falls back to
    ``unique(keep="last")`` (arbitrary but stable) and the row picked across
    runs may differ, so configure the order on any table that genuinely
    sees duplicates.
    """
    before_count = len(df)
    ordering = _parse_duplicate_resolution_order(table_config.duplicate_resolution_order)
    df_deduped = _apply_duplicate_resolution_order(
        df, pk_columns, ordering,
        context=f"{table_config.source_name}.{table_config.source_object_name} source dedup",
    )
    dup_count = before_count - len(df_deduped)

    if dup_count > 0:
        # Sample the duplicate PKs for debugging
        dup_pks = (
            df.group_by(pk_columns)
            .len()
            .filter(pl.col("len") > 1)
        )
        sample = dup_pks.head(5).drop("len").to_dicts()

        logger.error(
            "S-1: Source data for %s.%s has %d duplicate PK rows "
            "(%d unique PKs affected). Deduplicating via R-8 order=%s. "
            "Sample duplicate PKs: %s",
            table_config.source_name, table_config.source_object_name,
            dup_count, len(dup_pks),
            table_config.duplicate_resolution_order or "<unconfigured: keep=last>",
            sample,
        )
        return df_deduped

    return df


# ---------------------------------------------------------------------------
# L-1: Stage duplicate current row dedup
# ---------------------------------------------------------------------------

def _dedup_stage_current(
    df_existing: pl.DataFrame,
    pk_columns: list[str],
    table_config: TableConfig,
) -> pl.DataFrame:
    """L-1: Deduplicate Stage _cdc_is_current=1 rows by PK.

    The P0-8/P0-9 INSERT-first crash safety design can leave duplicate
    current rows after a crash (old + new version both _cdc_is_current=1).
    Keep the row with the latest _cdc_valid_from per PK to prevent
    Cartesian products in the inner-join hash comparison.
    """
    before_count = len(df_existing)

    if "_cdc_valid_from" in df_existing.columns:
        df_existing = (
            df_existing
            .sort("_cdc_valid_from", descending=True)
            .unique(subset=pk_columns, keep="first")
        )
    else:
        df_existing = df_existing.unique(subset=pk_columns, keep="first")

    dedup_count = before_count - len(df_existing)
    if dedup_count > 0:
        logger.warning(
            "L-1: Found %d duplicate _cdc_is_current=1 Stage rows for %s.%s "
            "(likely from prior crash recovery — P0-8/P0-9 INSERT-first design). "
            "Deduplicated to %d rows before CDC comparison.",
            dedup_count, table_config.source_name,
            table_config.source_object_name, len(df_existing),
        )

    return df_existing


# ---------------------------------------------------------------------------
# P0-7: Post-concat validation
# ---------------------------------------------------------------------------


class ConcatCorruptionError(Exception):
    """P0-7d: Raised when post-concat NULL inflation exceeds safe thresholds.

    This halts processing for the affected table, preventing corrupted data
    from propagating to Bronze/SCD2 where it would cause:
      - NULL PK rows hitting the unique filtered index (BCP failure)
      - Hash mismatches triggering mass SCD2 re-versioning
      - Silent data loss in downstream consumers
    """


# P0-7d: Thresholds for escalation
# If ANY PK column gains even 1 excess NULL, that's an immediate abort —
# NULL PKs cause duplicate key violations in Bronze (see BankruptcyType failure).
_PK_NULL_INFLATION_TOLERANCE = 0  # Zero tolerance for PK columns

# For non-PK columns, allow small NULL inflation before aborting.
# Based on fail_logs: AddressLine2 gained 628,832 NULLs — clearly catastrophic.
# A 1% threshold catches this while tolerating minor float/cast artifacts.
_NON_PK_NULL_INFLATION_PCT = 0.01  # 1% of total rows


def _validate_concat_columns(
    df_current: pl.DataFrame,
    df_fresh: pl.DataFrame,
    table_config,  # TableConfig
) -> pl.DataFrame:
    """Validate and fix diagonal_relaxed / safe_concat side-effects.

    P0-7:  Warns if concat introduced unexpected NULLs.
    P0-7d: ESCALATES to ConcatCorruptionError when NULL inflation exceeds
           safe thresholds — prevents corrupted data from reaching Bronze.
    C-3:   Detects and corrects dtype widening that would change hash
           representations (e.g., Int8 widened to Int64).

    Returns:
        df_current, potentially with dtype corrections applied.

    Raises:
        ConcatCorruptionError: If NULL inflation exceeds thresholds.
    """
    source_cols = [c for c in df_fresh.columns if not c.startswith("_")]
    pk_columns = table_config.pk_columns or []
    dtype_corrections: list[pl.Expr] = []

    # P0-7d: Collect violations for a single, actionable error message
    pk_violations: list[str] = []
    non_pk_violations: list[str] = []
    total_rows = len(df_current)

    for col in source_cols:
        if col not in df_current.columns:
            logger.warning(
                "P0-7: Column [%s] from fresh extraction is missing in "
                "df_current after concat for %s.%s — schema evolution may "
                "have caused column mismatch",
                col, table_config.source_name,
                table_config.source_object_name,
            )
            continue

        # --- C-3: Check for dtype drift ---
        fresh_dtype = df_fresh[col].dtype
        current_dtype = df_current[col].dtype
        if fresh_dtype != current_dtype:
            # C-3c: Demoted from WARNING to DEBUG after C-3a/C-3b deployment.
            # With canonical CDC_SCHEMA (C-3a) and Boolean→Int8 normalization
            # at extraction time (C-3b), this cast-back should no longer fire.
            # If it DOES fire, it signals a new mismatch source — investigate.
            logger.debug(
                "C-3: Column [%s] dtype changed from %s to %s after "
                "concat for %s.%s — casting back to prevent hash "
                "representation drift",
                col, fresh_dtype, current_dtype,
                table_config.source_name,
                table_config.source_object_name,
            )
            dtype_corrections.append(
                pl.col(col).cast(fresh_dtype, strict=False)
            )

        # --- P0-7 / P0-7d: Check for NULL inflation ---
        fresh_nulls = df_fresh[col].null_count()
        current_nulls = df_current[col].null_count()

        if current_nulls > fresh_nulls and total_rows > 0:
            excess_nulls = current_nulls - fresh_nulls

            if col in pk_columns:
                # P0-7d: ANY excess NULLs in PK columns = immediate abort.
                # This is the exact scenario that killed BankruptcyType:
                # NULL PK -> unique index violation -> BCP failure.
                pk_violations.append(
                    f"[{col}]: +{excess_nulls} NULLs"
                )
                logger.error(
                    "P0-7d: PK column [%s] in df_current has %d excess "
                    "NULLs after concat for %s.%s — aborting to prevent "
                    "Bronze unique index violation",
                    col, excess_nulls,
                    table_config.source_name,
                    table_config.source_object_name,
                )
            else:
                excess_pct = excess_nulls / total_rows
                if excess_pct > _NON_PK_NULL_INFLATION_PCT:
                    non_pk_violations.append(
                        f"[{col}]: +{excess_nulls} NULLs "
                        f"({excess_pct:.2%} of rows)"
                    )
                    logger.error(
                        "P0-7d: Column [%s] in df_current has %d excess "
                        "NULLs (%.2f%%) after concat for %s.%s — exceeds "
                        "%.0f%% threshold. Aborting to prevent hash "
                        "corruption and mass SCD2 re-versioning.",
                        col, excess_nulls, excess_pct * 100,
                        table_config.source_name,
                        table_config.source_object_name,
                        _NON_PK_NULL_INFLATION_PCT * 100,
                    )
                else:
                    # Below threshold — warn only (existing P0-7 behavior)
                    logger.warning(
                        "P0-7: Column [%s] in df_current has %d more NULLs "
                        "than fresh extraction for %s.%s — safe_concat may "
                        "have introduced NULLs from schema-mismatched rows.",
                        col, excess_nulls,
                        table_config.source_name,
                        table_config.source_object_name,
                    )

    # C-3: Apply dtype corrections before checking for abort
    if dtype_corrections:
        df_current = df_current.with_columns(dtype_corrections)
        logger.info(
            "C-3: Corrected %d column dtypes after concat for %s.%s",
            len(dtype_corrections),
            table_config.source_name,
            table_config.source_object_name,
        )

    # P0-7d: Abort if any threshold was exceeded
    if pk_violations or non_pk_violations:
        all_violations = []
        if pk_violations:
            all_violations.append(
                f"PK NULL inflation (zero tolerance): "
                f"{'; '.join(pk_violations)}"
            )
        if non_pk_violations:
            all_violations.append(
                f"Non-PK NULL inflation (>{_NON_PK_NULL_INFLATION_PCT:.0%} "
                f"threshold): {'; '.join(non_pk_violations)}"
            )

        raise ConcatCorruptionError(
            f"P0-7d: Concat introduced dangerous NULL inflation in "
            f"{table_config.source_name}.{table_config.source_object_name}. "
            f"Aborting to prevent data corruption in Bronze/SCD2. "
            f"Violations: {' | '.join(all_violations)}. "
            f"Root cause: schema mismatch between unchanged existing rows "
            f"(read from Stage) and freshly CDC-annotated rows. "
            f"Investigate _safe_concat W-7 logs for the schema diff."
        )

    return df_current

# ---------------------------------------------------------------------------
# CDC column helpers
# ---------------------------------------------------------------------------

def _add_cdc_columns(
    df: pl.DataFrame,
    operation: str,
    valid_from: datetime,
    batch_id: int,
) -> pl.DataFrame:
    """Add CDC tracking columns to a DataFrame.

    C-3a: All CDC columns are explicitly cast to their canonical types
    defined in CDC_SCHEMA. This eliminates the Boolean/Int8 mismatch
    for _cdc_is_current (Stage BIT reads as Boolean, we produce Int8)
    and the Int64/Int32 mismatch for _cdc_batch_id (ConnectorX
    inconsistency).

    Before this fix, Polars' literal type inference created:
      - _cdc_is_current as Int8 (from pl.lit(1).cast(Int8)) — correct
      - _cdc_batch_id as Int64 (from Python int) — correct
      - _cdc_valid_from as Datetime("us") WITHOUT timezone if valid_from
        had tzinfo stripped — WRONG, Stage reads UTC-aware datetimes

    Now all types are explicitly pinned to CDC_SCHEMA.
    """
    return df.with_columns(
        pl.lit(operation).cast(pl.String).alias("_cdc_operation"),
        pl.lit(valid_from).cast(pl.Datetime("us", "UTC")).alias("_cdc_valid_from"),
        pl.lit(None, dtype=pl.Datetime("us", "UTC")).alias("_cdc_valid_to"),
        pl.lit(1).cast(pl.Int8).alias("_cdc_is_current"),
        pl.lit(batch_id).cast(pl.Int64).alias("_cdc_batch_id"),
        pl.lit(config.SQL_SERVER_USER).cast(pl.String).alias("UdmModifiedBy"),
    )


def _write_and_load_cdc(
    df: pl.DataFrame,
    stage_table: str,
    output_dir: str | Path,
    table_config: TableConfig,
    label: str,
) -> None:
    """Write CDC rows to CSV and BCP load into Stage table.

    BCP-HANG-FIX-v3: Stage CDC loads now use bulk_load_stage_context (TABLOCK)
    and is_stage=True (100K batch size). Previously this function called
    bcp_load() with default is_stage=False, resulting in:
      - batch_size=800 (Bronze default) instead of 100K (Stage)
      - No sp_tableoption TABLOCK (no BU lock acquisition)
      - 973 micro-commits for 778K rows instead of 8 commits
      - TLS/TCP connection drops during inter-batch idle gaps → hang

    Stage tables are heaps (no clustered index), truncated before each load,
    with no concurrent readers. TABLOCK is always safe and optimal:
      - BU locks are compatible with other BU locks → parallel streams work
      - Minimal logging on heaps in BULK_LOGGED recovery → 90-99% less log I/O
      - Connection stays active continuously (no idle gaps between batches)

    The old pipeline always used TABLOCK for all tables via
    BCPLoader._enable_bulk_load_optimizations(). This function was the only
    code path in the new pipeline that skipped it for Stage loads.

    E-3: Stage loads use atomic=False — Stage is truncated before each load,
    so partial loads are harmless and -b batching improves performance.
    """
    df = sanitize_strings(df)
    df = cast_bit_columns(df)

    # P0-1: Reorder columns to match target table positional order
    if table_exists(stage_table):
        df = reorder_columns_for_bcp(
            df, stage_table,
            fill_null_columns=table_config.exclude_columns or None,
        )

    csv_path = write_bcp_csv(
        df,
        Path(output_dir) / f"{table_config.source_name}_{table_config.source_object_name}_cdc_{label}.csv",
    )

    # BCP-HANG-FIX-v3: Wrap in bulk_load_stage_context for TABLOCK + BULK_LOGGED.
    # Previously this was a bare bcp_load() call with no context manager and
    # is_stage=False (default), causing 800-row batches and connection hangs.
    db = stage_table.split(".")[0]
    row_count = len(df)

    logger.info(
        "BCP-HANG-FIX-v3: Loading %d CDC rows into %s with TABLOCK + "
        "batch_size=%d (Stage heap context)",
        row_count, stage_table, config.BCP_STAGE_BATCH_SIZE,
    )

    with bcp_loader.bulk_load_stage_context(db, stage_table):
        # Route through smart_load for automatic parallel BCP on large loads.
        # smart_load decision matrix:
        #   < 1K rows + df available  → pyodbc fast_executemany (milliseconds)
        #   >= 1M rows + is_stage     → bcp_load_parallel (8 concurrent streams)
        #   everything else           → bcp_load (single stream)
        # For 50M-row tables, this engages parallel BCP automatically.
        bcp_loader.smart_load(
            str(csv_path),
            stage_table,
            expected_row_count=row_count,
            atomic=False,  # E-3: Stage is truncated before load, partial OK
            is_stage=True,  # Use BCP_STAGE_BATCH_SIZE (100K) not 800
        )

def _expire_cdc_rows(
    expired_pks: pl.DataFrame,
    pk_columns: list[str],
    stage_table: str,
    valid_to: datetime,
    output_dir: str | Path,
    table_config: TableConfig,
    batch_valid_from: datetime | None = None,
) -> None:
    """Expire existing CDC rows by UPDATE via staging table.

    SCD-4 NOTE: Uses cursor.execute() (single statement), NOT executemany().
    pyodbc issue #481 confirms rowcount returns -1 after executemany().

    FIX: The P0-9 INSERT-first design inserts new CDC rows with
    _cdc_is_current=1 BEFORE expiring old versions. Without a batch filter,
    the expire UPDATE matches BOTH the old row AND the just-inserted new row
    for the same PK (both have _cdc_is_current=1), doubling the affected
    row count and expiring the new data.

    The batch_valid_from filter (AND t._cdc_valid_from < ?) ensures only
    rows from PRIOR batches are expired. New rows inserted in this batch
    have _cdc_valid_from = batch_valid_from, so the strict < excludes them.

    P2-14 validation: The expected count is len(expired_pks) — one row per PK.
    But crash recovery (P0-8/P0-9 INSERT-first) can leave duplicate
    _cdc_is_current=1 rows from prior crashed runs. The expire correctly
    closes ALL stale rows, so actual > expected is normal after a crash.
    This is logged as INFO (not ERROR) when actual is an exact multiple of
    expected (indicating N crashed runs left N duplicates per PK).

    Args:
        expired_pks: DataFrame of PK values to expire.
        pk_columns: Primary key column names.
        stage_table: Fully qualified Stage table name.
        valid_to: Timestamp to set as _cdc_valid_to on expired rows.
        output_dir: Directory for temp CSV files.
        table_config: Table configuration.
        batch_valid_from: Timestamp of the current batch (from _add_cdc_columns).
            When provided, only rows with _cdc_valid_from < this value are expired,
            preventing the just-inserted new versions from being closed.
    """
    db = stage_table.split(".")[0]
    schema = stage_table.split(".")[1]
    staging_table = f"{db}.{schema}._staging_expire_{table_config.source_object_name}"
    q_staging = quote_table(staging_table)

    # P0-3: Use actual PK column types from target table instead of NVARCHAR(MAX)
    pk_types = get_column_types(stage_table, pk_columns)

    pk_col_defs = ", ".join(f"{quote_identifier(c)} {pk_types[c]}" for c in pk_columns)
    with cursor_for(db) as cur:
        cur.execute(f"IF OBJECT_ID(?, 'U') IS NOT NULL DROP TABLE {q_staging}", staging_table)
        cur.execute(f"CREATE TABLE {q_staging} ({pk_col_defs})")

    try:
        # Write PKs to CSV — keep native dtypes (don't cast to Utf8)
        expired_pks_clean = sanitize_strings(expired_pks)
        csv_path = write_bcp_csv(
            expired_pks_clean,
            Path(output_dir) / f"{table_config.source_name}_{table_config.source_object_name}_expire_pks.csv",
        )
        # E-3: Staging tables are ephemeral — atomic=False for performance.
        # is_stage=True picks BCP_STAGE_BATCH_SIZE (100K) so heap-style
        # staging loads don't fall through to the 800-row Bronze default
        # and time out the BCP subprocess on million-row PK sets.
        bcp_loader.bcp_load(str(csv_path), staging_table, atomic=False, is_stage=True)

        # P2-5: Index staging table for efficient JOIN against large Stage tables
        bcp_loader.create_staging_index(staging_table, pk_columns, row_count=len(expired_pks))

        # UPDATE join to expire rows
        join_condition = " AND ".join(
            f"t.{quote_identifier(c)} = s.{quote_identifier(c)}" for c in pk_columns
        )
        q_stage = quote_table(stage_table)

        # FIX: Add batch_valid_from filter to prevent double-expire of THIS batch.
        if batch_valid_from is not None:
            expire_sql = f"""
                UPDATE t
                SET t._cdc_is_current = 0, t._cdc_valid_to = ?
                FROM {q_stage} t
                INNER JOIN {q_staging} s ON {join_condition}
                WHERE t._cdc_is_current = 1
                  AND t._cdc_valid_from < ?
            """
            expire_params = (valid_to, batch_valid_from)
        else:
            expire_sql = f"""
                UPDATE t
                SET t._cdc_is_current = 0, t._cdc_valid_to = ?
                FROM {q_stage} t
                INNER JOIN {q_staging} s ON {join_condition}
                WHERE t._cdc_is_current = 1
            """
            expire_params = (valid_to,)

        with cursor_for(db) as cur:
            cur.execute(expire_sql, *expire_params)

            # P2-14: Verify actual vs expected UPDATE row count
            actual_rows = cur.rowcount

        expected = len(expired_pks)
        if actual_rows != expected:
            if actual_rows < expected:
                # C-2: Expected during retries — already-expired rows won't be touched.
                logger.info(
                    "P2-14: CDC expire affected %d rows (expected %d) in %s — "
                    "delta of %d (idempotent retry: already-expired rows from prior run)",
                    actual_rows, expected, stage_table,
                    expected - actual_rows,
                )
            elif expected > 0 and actual_rows % expected == 0:
                # Crash recovery: prior crashed runs (P0-8/P0-9 INSERT-first)
                # left duplicate _cdc_is_current=1 rows. The expire correctly
                # closes ALL stale duplicates. actual/expected = N means N-1
                # prior crashed runs left orphan current rows.
                dup_factor = actual_rows // expected
                logger.info(
                    "P2-14: CDC expire affected %d rows (expected %d) in %s — "
                    "%dx multiplier indicates %d prior crashed run(s) left "
                    "duplicate _cdc_is_current=1 rows (P0-8/P0-9 INSERT-first "
                    "crash recovery). All stale duplicates correctly expired.",
                    actual_rows, expected, stage_table,
                    dup_factor, dup_factor - 1,
                )
            else:
                # Non-integer multiple — genuine anomaly worth investigating.
                logger.warning(
                    "P2-14: CDC expire affected %d rows (expected %d) in %s — "
                    "MORE rows affected than expected. This may indicate "
                    "duplicate _cdc_is_current=1 rows from crash recovery "
                    "or unexpected join fan-out. Investigate if this persists "
                    "after a clean (non-crash-recovery) run.",
                    actual_rows, expected, stage_table,
                )
        else:
            logger.info("Expired %d CDC rows in %s", actual_rows, stage_table)
    finally:
        # Always drop staging table — prevents orphaned tables on exception
        with cursor_for(db) as cur:
            cur.execute(f"DROP TABLE IF EXISTS {q_staging}")

# ---------------------------------------------------------------------------
# L-2: Stage purge utility
# ---------------------------------------------------------------------------

# Default retention period for expired CDC rows (days).
_PURGE_RETENTION_DAYS = 30
# Batch size for batched DELETEs to avoid transaction log bloat.
_PURGE_BATCH_SIZE = 100_000


def purge_expired_cdc_rows(
    stage_table: str,
    retention_days: int = _PURGE_RETENTION_DAYS,
    batch_size: int = _PURGE_BATCH_SIZE,
) -> int:
    """L-2: Delete expired CDC rows older than retention_days.

    Expired rows (_cdc_is_current=0) accumulate over time since CDC only
    marks them as expired but never removes them. This utility removes
    old expired rows in batches to avoid transaction log bloat.

    The retention_days must exceed LookbackDays for any table using the
    Stage table to avoid deleting rows that might be needed for gap
    reprocessing.

    Args:
        stage_table: Full Stage table name (e.g., 'UDM_Stage.DNA.ACCT_cdc').
        retention_days: Keep expired rows newer than this many days.
        batch_size: DELETE TOP N per iteration to limit log growth.

    Returns:
        Total number of rows purged.
    """
    db = stage_table.split(".")[0]
    total_purged = 0
    q_stage = quote_table(stage_table)

    # Item-15: Use cursor_for() per batch — each batch gets a fresh connection.
    # Prevents a single dropped connection from failing the entire purge loop.
    while True:
        with cursor_for(db) as cur:
            cur.execute(f"""
                DELETE TOP (?) FROM {q_stage}
                WHERE _cdc_is_current = 0
                  AND _cdc_valid_to < DATEADD(day, -?, GETUTCDATE())
            """, batch_size, retention_days)
            deleted = cur.rowcount
        total_purged += deleted

        if deleted < batch_size:
            break  # No more rows to purge

        logger.info(
            "L-2: Purged %d expired CDC rows from %s (%d total so far)",
            deleted, stage_table, total_purged,
        )

    if total_purged > 0:
        logger.info(
            "L-2: Purge complete for %s — removed %d expired CDC rows "
            "(retention=%d days)",
            stage_table, total_purged, retention_days,
        )

    return total_purged


# ---------------------------------------------------------------------------
# P1-3/P1-4: Windowed CDC for large tables
#
# P3-9 KNOWN LIMITATION: Late-arriving data beyond the lookback window is
# invisible to windowed CDC. If a source system backdates a correction to a
# date older than LookbackDays, the change will not be detected. The periodic
# reconciliation (P3-4 in reconciliation.py) catches this on a weekly basis.
#
# L-5 KNOWN LIMITATION: Date column value migration creates phantom deletes
# and phantom inserts. When a source system changes a row's date column value
# (e.g., order effective_date moved from Jan 1 to Jan 15), windowed CDC sees
# the row disappear from the Jan 1 window (delete) and appear in the Jan 15
# window (insert). This creates an unnecessary close + re-insert cycle in SCD2,
# inflating Bronze version count with misleading revision history.
# Mitigations: (a) Use a stable date column (created_date vs modified_date) as
# SourceAggregateColumnName, (b) accept as inherent to windowed CDC, (c) weekly
# reconciliation (P3-4) provides eventual consistency but cannot restore lineage.
# ---------------------------------------------------------------------------

def run_cdc_windowed(
    table_config: TableConfig,
    df_fresh: pl.DataFrame,
    batch_id: int,
    output_dir: str | Path,
    date_column: str,
    window_start: date,
    window_end: date,
) -> CDCResult:
    """Run CDC comparison scoped to a date window (large tables).

    Unlike run_cdc(), this only compares df_fresh against Stage rows whose
    business date falls within [window_start, window_end). This prevents
    rows outside the window from being classified as deletes (P1-4).

    Args:
        table_config: Table configuration with PK columns.
        df_fresh: Fresh extraction DataFrame for this window.
        batch_id: Pipeline batch ID for _cdc_batch_id.
        output_dir: Directory for staging CSV files.
        date_column: Business date column name (SourceAggregateColumnName).
        window_start: Start of date window (inclusive).
        window_end: End of date window (exclusive).

    Returns:
        CDCResult with counts and df_current.
    """
    # Phase 1 of cdc_root_cause_blueprint.md: log Stage↔Bronze drift before
    # windowed CDC. Read-only, never blocks.
    from cdc.drift_detector import log_stage_bronze_drift
    log_stage_bronze_drift(table_config)

    stage_table = table_config.stage_full_table_name
    ctx = CDCContext(
        read_existing=lambda: read_stage_table_windowed(
            stage_table, date_column, window_start, window_end,
        ),
        track_deleted_pks=True,
        log_label="Windowed CDC",
        log_window=f" [{window_start}, {window_end})",
    )
    return _run_cdc_core(table_config, df_fresh, batch_id, output_dir, ctx)