"""Safe DataFrame concatenation utilities — T-2 + P0-7b/c + C-3a.

T-2:    safe_concat() replaces diagonal_relaxed to avoid Polars crash bugs.
P0-7b:  conform_to_schema() normalizes all DataFrames to a canonical schema
        BEFORE concat, using typed nulls instead of untyped pl.lit(None).
P0-7c:  By conforming to a known schema, NULL inflation from missing columns
        is eliminated at the source (no more silent pl.lit(None) injection).
C-3a:   CDC_SCHEMA defines canonical types for CDC columns — eliminates the
        Boolean/Int8 and Int64/Int32 drift between fresh CDC and Stage reads.
"""

from __future__ import annotations

import logging
import polars as pl
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from orchestration.table_config import TableConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# C-3a: Canonical CDC column schema
# ---------------------------------------------------------------------------

CDC_SCHEMA: dict[str, pl.DataType] = {
    "_cdc_operation":  pl.String,
    "_cdc_valid_from": pl.Datetime("us", "UTC"),
    "_cdc_valid_to":   pl.Datetime("us", "UTC"),
    "_cdc_is_current": pl.Int8,         # NOT Boolean — Stage stores as BIT,
                                         # ConnectorX reads BIT as Boolean,
                                         # but we canonicalize to Int8 to prevent
                                         # Boolean/Int8 mismatch in concat.
    "_cdc_batch_id":   pl.Int64,         # Stage DDL is BIGINT → Int64.
                                         # ConnectorX sometimes returns Int32.
    "UdmModifiedBy":   pl.String,
}


# ---------------------------------------------------------------------------
# P0-7b: Build canonical target schema for concat
# ---------------------------------------------------------------------------

def build_target_schema(
    df_fresh: pl.DataFrame,
    extra_schemas: list[dict[str, pl.DataType]] | None = None,
) -> dict[str, pl.DataType]:
    """Derive the canonical target schema for current_parts concat.

    The target schema is the UNION of:
      1. df_fresh columns (source extraction dtypes — authoritative)
      2. CDC_SCHEMA (canonical CDC column types)
      3. Any extra_schemas (e.g., _extracted_at, _row_hash)

    df_fresh is authoritative because it comes from the current extraction.
    Stage reads may have stale dtypes from prior schema versions. Using
    df_fresh as the source-of-truth ensures the concat result matches the
    current source schema.

    Args:
        df_fresh: The fresh extraction DataFrame (post-hash, pre-CDC).
        extra_schemas: Additional schema dicts to merge (optional).

    Returns:
        Ordered dict of column_name → pl.DataType.
    """
    # Start with fresh extraction schema (all columns including _row_hash, _extracted_at)
    schema: dict[str, pl.DataType] = dict(df_fresh.schema)

    # Overlay CDC columns with canonical types
    schema.update(CDC_SCHEMA)

    # Add any extras
    if extra_schemas:
        for extra in extra_schemas:
            schema.update(extra)

    return schema


# ---------------------------------------------------------------------------
# P0-7b/c: Conform DataFrame to target schema
# ---------------------------------------------------------------------------

def conform_to_schema(
    df: pl.DataFrame,
    schema: dict[str, pl.DataType],
    context: str = "",
) -> pl.DataFrame:
    """Conform a DataFrame to an exact target schema.

    For each column in the target schema:
      - If present in df: cast to the target dtype (strict=False)
      - If missing from df: add as pl.lit(None, dtype=target_dtype)
        This creates TYPED nulls, not untyped Null columns.

    Columns in df that are NOT in the target schema are DROPPED.
    This prevents schema bloat from stale Stage columns.

    Args:
        df: Input DataFrame to conform.
        schema: Target schema (column_name → pl.DataType).
        context: Description for log messages.

    Returns:
        DataFrame with exactly the columns and dtypes in schema.
    """
    expressions = []
    missing_cols = []
    cast_cols = []

    for col_name, col_dtype in schema.items():
        if col_name in df.columns:
            if df[col_name].dtype != col_dtype:
                expressions.append(
                    pl.col(col_name).cast(col_dtype, strict=False)
                )
                cast_cols.append((col_name, df[col_name].dtype, col_dtype))
            else:
                expressions.append(pl.col(col_name))
        else:
            # P0-7c: Typed null — NOT untyped pl.lit(None)
            expressions.append(
                pl.lit(None, dtype=col_dtype).alias(col_name)
            )
            missing_cols.append(col_name)

    # Log schema adjustments
    if missing_cols:
        logger.warning(
            "P0-7b: conform_to_schema added %d missing columns as typed NULLs "
            "for %s: %s. This indicates schema divergence between persisted "
            "Stage/Bronze data and current extraction.",
            len(missing_cols), context or "unknown", missing_cols,
        )

    if cast_cols:
        cast_details = {c: (str(src), str(tgt)) for c, src, tgt in cast_cols}
        logger.debug(
            "C-3a: conform_to_schema cast %d columns for %s: %s",
            len(cast_cols), context or "unknown", cast_details,
        )

    # Detect columns being dropped (in df but not in schema)
    extra_cols = set(df.columns) - set(schema.keys())
    if extra_cols:
        logger.info(
            "P0-7b: conform_to_schema dropping %d extra columns not in target "
            "schema for %s: %s",
            len(extra_cols), context or "unknown", sorted(extra_cols),
        )

    return df.select(expressions)


# ---------------------------------------------------------------------------
# Type classification helpers (unchanged from existing safe_concat.py)
# ---------------------------------------------------------------------------

def _is_integer(dtype: pl.DataType) -> bool:
    return dtype in (pl.Int8, pl.Int16, pl.Int32, pl.Int64,
                     pl.UInt8, pl.UInt16, pl.UInt32, pl.UInt64)

def _is_float(dtype: pl.DataType) -> bool:
    return dtype in (pl.Float32, pl.Float64)

def _is_boolean(dtype: pl.DataType) -> bool:
    return dtype == pl.Boolean

def _is_datetime(dtype: pl.DataType) -> bool:
    return isinstance(dtype, pl.Datetime) or dtype == pl.Date


def _resolve_common_dtype(dtypes: list[pl.DataType]) -> pl.DataType:
    """Resolve a list of Polars dtypes to a single common type for safe concat.

    Resolution rules (in priority order):
      1. All same -> keep as-is
      2. Boolean vs Int8 -> Int8 (BIT column round-trip through SQL Server)
      3. Boolean vs other int -> wider int
      4. Boolean vs Float -> Float64
      5. Datetime timezone mismatch -> prefer UTC-aware
      6. Numeric width mismatch -> wider type
      7. Fallback -> Utf8
    """
    unique = list(set(dtypes))
    if len(unique) == 1:
        return unique[0]

    has_boolean = any(_is_boolean(d) for d in unique)
    has_integer = any(_is_integer(d) for d in unique)
    has_float   = any(_is_float(d) for d in unique)
    has_datetime = any(_is_datetime(d) for d in unique)

    # Boolean vs Int8 -> Int8 (SQL Server BIT round-trip)
    if has_boolean and has_integer:
        ints = [d for d in unique if _is_integer(d)]
        int_rank = {pl.Int8: 1, pl.Int16: 2, pl.Int32: 3, pl.Int64: 4,
                    pl.UInt8: 1, pl.UInt16: 2, pl.UInt32: 3, pl.UInt64: 4}
        return max(ints, key=lambda d: int_rank.get(d, 0))

    if has_boolean and has_float:
        return pl.Float64

    if has_boolean:
        return pl.Int8

    if has_datetime:
        datetimes = [d for d in unique if _is_datetime(d)]
        with_tz = [d for d in datetimes
                    if hasattr(d, 'time_zone') and d.time_zone is not None]
        if with_tz:
            return with_tz[0]
        return datetimes[0]

    if has_integer and has_float:
        return pl.Float64
    if has_integer:
        int_rank = {pl.Int8: 1, pl.Int16: 2, pl.Int32: 3, pl.Int64: 4,
                    pl.UInt8: 1, pl.UInt16: 2, pl.UInt32: 3, pl.UInt64: 4}
        ints = [d for d in unique if _is_integer(d)]
        return max(ints, key=lambda d: int_rank.get(d, 0))
    if has_float:
        return pl.Float64

    return pl.Utf8


def safe_concat(dfs: list[pl.DataFrame]) -> pl.DataFrame:
    """T-2: Safe vertical concat that pre-aligns schemas.

    Replaces all uses of pl.concat(..., how="diagonal_relaxed") which can
    cause full interpreter crashes (Polars #12543, #18911) when DataFrames
    have large column count differences.

    NOTE: For current_parts concat in CDC/SCD2, prefer conform_to_schema()
    + pl.concat(how="vertical") over this function. safe_concat is kept for
    cases where a canonical schema is not available (e.g., E-2 NULL partition
    supplement in connectorx_sqlserver_extractor.py).

    Fixes:
      - Pre-aligns all DataFrames to the same column set
      - Resolves dtype conflicts via smart common-supertype resolution
      - Uses plain vertical concat (never diagonal_relaxed)
      - Adds missing columns as NULL with the resolved dtype
    """
    if len(dfs) == 0:
        return pl.DataFrame()
    if len(dfs) == 1:
        return dfs[0]

    # W-7: Log schema mismatches (informational)
    reference = dfs[0].schema
    for i, df in enumerate(dfs[1:], 1):
        if df.schema != reference:
            mismatches = {
                col: (reference.get(col), df.schema.get(col))
                for col in set(reference) | set(df.schema)
                if reference.get(col) != df.schema.get(col)
            }
            logger.warning(
                "W-7: Schema mismatch in safe_concat at index %d: %s. "
                "Aligning schemas before vertical concat.",
                i, mismatches,
            )

    # Collect ALL dtypes seen for each column across all DataFrames
    col_dtypes: dict[str, list[pl.DataType]] = {}
    for df in dfs:
        for col in df.columns:
            if col not in col_dtypes:
                col_dtypes[col] = []
            col_dtypes[col].append(df[col].dtype)

    # Resolve each column to a common dtype
    resolved: dict[str, pl.DataType] = {}
    for col, dtypes in col_dtypes.items():
        resolved[col] = _resolve_common_dtype(dtypes)

    # Align each DataFrame: add missing columns, cast to resolved dtype
    col_order = list(resolved.keys())
    aligned = []
    for df in dfs:
        cast_exprs = []
        missing_exprs = []

        for col in col_order:
            target_dtype = resolved[col]
            if col in df.columns:
                if df[col].dtype != target_dtype:
                    cast_exprs.append(
                        pl.col(col).cast(target_dtype, strict=False).alias(col)
                    )
            else:
                missing_exprs.append(
                    pl.lit(None).cast(target_dtype).alias(col)
                )

        if cast_exprs:
            df = df.with_columns(cast_exprs)
        if missing_exprs:
            df = df.with_columns(missing_exprs)

        aligned.append(df.select(col_order))

    return pl.concat(aligned)


def stabilize_extraction_dtypes(
    df: pl.DataFrame,
    table_config: TableConfig,
) -> pl.DataFrame:
    """Cast extraction DataFrame columns to match existing Stage schema.

    Solves Oracle/ConnectorX type inference instability: the same Oracle
    NUMBER column can arrive as Int64, Float64, Utf8, or Null depending on
    the data present in each day's extraction. The Stage table (once created)
    has the authoritative types — this function casts the DataFrame to match.

    Idempotency guarantees:
      - Stage doesn't exist (first run): returns df unchanged — DataFrame
        types will CREATE the Stage table via ensure_stage_table().
      - Stage exists, types match: casting is a no-op.
      - Stage exists, types differ: casts to Stage type (strict=False —
        incompatible values become NULL, which is safe for sparse days).
      - New columns not in Stage: left untouched — schema evolution will
        ADD them on the next step.
      - Null-typed columns (all NULLs): cast to the Stage type — Null
        values are type-agnostic in both Polars and SQL Server.

    Args:
        df: Freshly extracted DataFrame (before schema evolution).
        table_config: Table configuration.

    Returns:
        DataFrame with source columns cast to match Stage schema.
    """
    from extract.udm_connectorx_extractor import table_exists
    from data_load.schema_utils import get_stage_polars_schema

    stage_table = table_config.stage_full_table_name

    if not table_exists(stage_table):
        # First run — no Stage table yet. DataFrame types are authoritative.
        return df

    stage_schema = get_stage_polars_schema(stage_table)

    if not stage_schema:
        return df

    cast_exprs = []
    cast_log = []

    for col in df.columns:
        if col not in stage_schema:
            # New column or internal column — leave as-is for schema evolution
            continue

        target_dtype = stage_schema[col]
        current_dtype = df[col].dtype

        if current_dtype == target_dtype:
            continue

        # Null dtype (all NULLs) or mismatched inference — cast to Stage type
        cast_exprs.append(pl.col(col).cast(target_dtype, strict=False))
        cast_log.append(f"{col}: {current_dtype} -> {target_dtype}")

    if cast_exprs:
        df = df.with_columns(cast_exprs)
        logger.info(
            "DTYPE-STABILIZE: Cast %d columns to match Stage schema for %s.%s: %s",
            len(cast_exprs),
            table_config.source_name,
            table_config.source_object_name,
            cast_log,
        )

    return df
