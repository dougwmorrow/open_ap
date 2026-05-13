"""Seed python pipeline Bronze + Stage from legacy SCD2 data.

After truncating the python-side tables, this tool copies the legacy
SCD2 snapshot into the python-format targets:

  * ``UDM_Bronze.<SourceName>.<table>_scd2_python``  — full history
  * ``UDM_Stage.<SourceName>.<table>_cdc``           — current rows only

Legacy table naming convention is the *same source-schema name as python
target* — there is **no** ``_SCD2`` suffix on legacy. Examples::

    UDM_Bronze.dna.PERS         (legacy SCD2 history — has UdmActiveFlag,
                                  UdmEffectiveDateTime, UdmEndDateTime,
                                  UdmHash, UdmSource)

    UDM_Bronze.ccm.Account      (same shape, ccm schema)

The script reads from this legacy SCD2 table and writes to the python
target ``UDM_Bronze.<SourceName_uppercase>.<table>_scd2_python``. Schema
casing differs (legacy lowercase ``dna``/``ccm``; python uppercase
``DNA``/``CCM``) and the ``_scd2_python`` suffix prevents any collision.

Then the regular pipeline picks up where legacy left off::

    python3 tools/seed_from_legacy.py --source DNA --table PERS \\
        --legacy-table UDM_Bronze.dna.PERS

    python3 main_small_tables.py --source DNA --table PERS

The first run after seeding compares the live source against the seeded
Stage and produces only the deltas. Validation then compares legacy vs
python Bronze on a row-for-row basis.

What this script does

  1. Read legacy Bronze (``cx.read_sql``).
  2. Drop legacy-only metadata columns
     (``UdmCreateId``, ``UdmCreateDateTime``, ``UdmUpdateId``,
     ``UdmUpdateDateTime``, ``UdmSource``, the legacy ``UdmHash``,
     and any ``_scd2_key`` IDENTITY).
  3. Pad the DataFrame with NULL for any column the python target has
     that legacy is missing (``W-?`` schema drift — source gained columns
     after the legacy snapshot was built).
  4. Compute fresh ``UdmHash`` via ``add_row_hash()`` over **source
     columns only** (excludes ``UdmActiveFlag``, ``UdmEffectiveDateTime``,
     ``UdmEndDateTime``, etc.) so the hash matches what the pipeline
     produces on a live extract. Honors ``ExcludeFromHash``
     (``DATELASTMAINT``) per the table's R-10.2 config.
  5. Backfill ``UdmSourceBeginDate`` via the configured R-2 waterfall
     (or ``UdmEffectiveDateTime`` when no waterfall column has data).
  6. Stamp ``UdmSourceEndDate`` from the Flag value:

       * ``Flag = 1`` → ``'2999-12-31'`` sentinel
       * ``Flag = 0`` or ``2`` → legacy ``UdmEndDateTime`` (or NULL)

  7. Stamp ``UdmScd2Operation`` from the Flag value (legacy doesn't have
     this column):

       * ``Flag = 1`` → ``'I'``
       * ``Flag = 2`` → ``'D'``
       * ``Flag = 0`` → ``'U'``

  8. Stamp ``UdmModifiedBy = 'legacy_seed'``.
  9. BCP-load into the python Bronze table (``atomic=True``).
  10. Build a Stage snapshot from the Flag=1 rows + CDC columns and
      BCP-load into the python Stage table (``atomic=False``).
  11. Print row-count summary and verification queries.

Limitations / by-design omissions

  * Column compatibility check is best-effort (column-name-level).
    Type mismatches that survive a Polars cast will silently load —
    rerun ``validate_scd2.py`` after seeding to surface defects.
  * Does not seed legacy enrichment columns (e.g. MEMBERAGREEMENT's
    ``UdmSourceAddDateTime`` from ACTVSUBACTV). Legacy proc behavior
    for those is reproduced by the python pipeline's R-2 waterfall in
    subsequent runs once ``SCD2DateColumns`` is configured correctly.
  * Single-table only. Bulk seeding is left to a shell loop.
  * No ``--all`` flag. Operator runs per-table by intent.

Schema drift expectation

  Source systems gain columns over time. When legacy was last built
  the source may have had fewer columns than today. The python target
  Bronze (auto-created from current source) carries the new columns;
  legacy doesn't. This script:

  - pads NULL for python-target columns missing from legacy
    (preserves Bronze positional schema for BCP),

  - computes the hash over the union of those columns so the hash
    represents the post-pad row state.

  After seeding, the first pipeline run will likely detect the new
  column values as updates (NULL → real value) — a one-time mass
  update wave per the B-3 schema-evolution pattern. Expected behavior.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import polars as pl

# Add parent directory for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import utils.configuration as config
from utils.connections import bronze_connectorx_uri
from data_load import bcp_loader
from data_load.bcp_csv import write_bcp_csv
from data_load.row_hash import add_row_hash
from data_load.sanitize import cast_bit_columns, reorder_columns_for_bcp, sanitize_strings
from data_load.schema_utils import get_target_column_order
from extract.udm_connectorx_extractor import table_exists
from orchestration.table_config import TableConfigLoader
from extract import cx_read_sql_safe

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# Columns we drop from legacy before mapping (legacy-only metadata).
LEGACY_DROP_COLUMNS = {
    "_scd2_key",
    "UdmCreateId", "UdmCreateDateTime",
    "UdmUpdateId", "UdmUpdateDateTime",
    "UdmSource",
    # Legacy hash format incompatible — recomputed fresh below.
    "UdmHash",
}


def _read_legacy(legacy_table: str) -> pl.DataFrame:
    uri = bronze_connectorx_uri()
    logger.info("Reading legacy table %s", legacy_table)
    df = cx_read_sql_safe(
        conn=uri, query=f"SELECT * FROM {legacy_table}",
        context=f"legacy seed read {legacy_table}",
    )
    logger.info("Read %d rows from %s", len(df), legacy_table)
    return df


def _drop_legacy_columns(df: pl.DataFrame) -> pl.DataFrame:
    drop = [c for c in df.columns if c in LEGACY_DROP_COLUMNS]
    if drop:
        logger.info("Dropping legacy-only columns: %s", drop)
        df = df.drop(drop)
    return df


def _build_source_begin(
    df: pl.DataFrame,
    waterfall_cols: list[str] | None,
    default_begin: str | None,
) -> pl.DataFrame:
    """Compute UdmSourceBeginDate per row from the waterfall.

    Mirrors :func:`scd2.engine._build_source_begin_expr` so seeded values
    align with what the engine would produce on a normal run.
    """
    fallback_dt = datetime.strptime(default_begin or "1900-01-01", "%Y-%m-%d") \
        if default_begin else datetime(1900, 1, 1)

    if not waterfall_cols:
        # No waterfall — use UdmEffectiveDateTime (load time) as best
        # available proxy for source business date.
        if "UdmEffectiveDateTime" in df.columns:
            df = df.with_columns(
                pl.col("UdmEffectiveDateTime")
                .cast(pl.Datetime("us"), strict=False)
                .alias("UdmSourceBeginDate")
            )
        else:
            df = df.with_columns(
                pl.lit(fallback_dt).cast(pl.Datetime("us")).alias("UdmSourceBeginDate")
            )
        return df

    existing = [c for c in waterfall_cols if c in df.columns]
    if not existing:
        logger.warning(
            "Waterfall columns %s not found in legacy data — using "
            "UdmEffectiveDateTime / fallback.",
            waterfall_cols,
        )
        if "UdmEffectiveDateTime" in df.columns:
            df = df.with_columns(
                pl.col("UdmEffectiveDateTime")
                .cast(pl.Datetime("us"), strict=False)
                .alias("UdmSourceBeginDate")
            )
        else:
            df = df.with_columns(
                pl.lit(fallback_dt).cast(pl.Datetime("us")).alias("UdmSourceBeginDate")
            )
        return df

    cast_exprs = [pl.col(c).cast(pl.Datetime("us"), strict=False) for c in existing]
    fallback_expr = (
        pl.col("UdmEffectiveDateTime").cast(pl.Datetime("us"), strict=False)
        if "UdmEffectiveDateTime" in df.columns
        else pl.lit(fallback_dt).cast(pl.Datetime("us"))
    )
    df = df.with_columns(
        pl.coalesce(cast_exprs + [fallback_expr])
        .fill_null(pl.lit(fallback_dt).cast(pl.Datetime("us")))
        .dt.truncate("1ms")
        .alias("UdmSourceBeginDate")
    )
    return df


def _build_source_end_and_op(df: pl.DataFrame) -> pl.DataFrame:
    """Stamp UdmSourceEndDate and UdmScd2Operation from the Flag value.

      Flag=1 → SourceEndDate = '2999-12-31', Op = 'I'
      Flag=2 → SourceEndDate = UdmEndDateTime (or NULL), Op = 'D'
      Flag=0 → SourceEndDate = UdmEndDateTime (or NULL), Op = 'U'
    """
    sentinel = datetime(2999, 12, 31)

    end_expr: pl.Expr
    if "UdmEndDateTime" in df.columns:
        end_expr = pl.col("UdmEndDateTime").cast(pl.Datetime("us"), strict=False)
    else:
        end_expr = pl.lit(None, dtype=pl.Datetime("us"))

    df = df.with_columns(
        pl.when(pl.col("UdmActiveFlag") == 1)
        .then(pl.lit(sentinel).cast(pl.Datetime("us")))
        .otherwise(end_expr)
        .alias("UdmSourceEndDate"),

        pl.when(pl.col("UdmActiveFlag") == 1).then(pl.lit("I"))
        .when(pl.col("UdmActiveFlag") == 2).then(pl.lit("D"))
        .otherwise(pl.lit("U"))
        .alias("UdmScd2Operation"),

        pl.lit("legacy_seed").alias("UdmModifiedBy"),
    )
    return df


def _seed_bronze(
    df: pl.DataFrame,
    target_bronze: str,
    table_config,
    output_dir: Path,
    dry_run: bool,
) -> int:
    """BCP-load the prepared DataFrame into python Bronze (atomic=True)."""
    df = sanitize_strings(df)
    df = cast_bit_columns(df)

    # Bronze auto-create gives _scd2_key as IDENTITY — include placeholder.
    if "_scd2_key" not in df.columns:
        df = df.with_columns(pl.lit(0).cast(pl.Int64).alias("_scd2_key"))

    # P0-1: enforce Bronze column order before BCP write.
    df = reorder_columns_for_bcp(
        df, target_bronze,
        fill_null_columns=table_config.exclude_columns or None,
    )

    if dry_run:
        logger.info(
            "[DRY RUN] Would BCP-load %d rows into %s. First 3 rows: %s",
            len(df), target_bronze, df.head(3).to_dicts(),
        )
        return len(df)

    csv_path = write_bcp_csv(
        df,
        output_dir / f"legacy_seed_{table_config.source_name}_{table_config.source_object_name}_bronze.csv",
    )
    bcp_loader.bcp_load(
        str(csv_path), target_bronze,
        expected_row_count=len(df),
        atomic=True,
    )
    logger.info("Bronze seed: loaded %d rows into %s", len(df), target_bronze)
    return len(df)


def _seed_stage(
    df_active: pl.DataFrame,
    target_stage: str,
    table_config,
    output_dir: Path,
    dry_run: bool,
) -> int:
    """Build CDC current snapshot from Flag=1 rows and BCP-load into Stage."""
    if len(df_active) == 0:
        logger.info("No Flag=1 rows — skipping Stage seed.")
        return 0

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    batch_id = -1  # Sentinel batch_id for legacy seed; future runs assign real ones.

    # Strip Bronze-only columns before adding CDC columns.
    bronze_only = {
        "_scd2_key", "UdmEffectiveDateTime", "UdmEndDateTime",
        "UdmSourceBeginDate", "UdmSourceEndDate",
        "UdmActiveFlag", "UdmScd2Operation", "UdmModifiedBy",
    }
    keep_cols = [c for c in df_active.columns if c not in bronze_only]
    df_stage = df_active.select(keep_cols)

    df_stage = df_stage.with_columns(
        pl.lit(now).alias("_cdc_valid_from"),
        pl.lit(None, dtype=pl.Datetime("us")).alias("_cdc_valid_to"),
        pl.lit(1).cast(pl.Int8).alias("_cdc_is_current"),
        pl.lit("I").alias("_cdc_operation"),
        pl.lit(batch_id).cast(pl.Int64).alias("_cdc_batch_id"),
    )
    df_stage = sanitize_strings(df_stage)
    df_stage = cast_bit_columns(df_stage)
    df_stage = reorder_columns_for_bcp(
        df_stage, target_stage,
        fill_null_columns=table_config.exclude_columns or None,
    )

    if dry_run:
        logger.info(
            "[DRY RUN] Would BCP-load %d Stage rows into %s",
            len(df_stage), target_stage,
        )
        return len(df_stage)

    csv_path = write_bcp_csv(
        df_stage,
        output_dir / f"legacy_seed_{table_config.source_name}_{table_config.source_object_name}_stage.csv",
    )
    bcp_loader.bcp_load(
        str(csv_path), target_stage,
        expected_row_count=len(df_stage),
        atomic=False,
    )
    logger.info("Stage seed: loaded %d rows into %s", len(df_stage), target_stage)
    return len(df_stage)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", required=True, help="SourceName (e.g. DNA).")
    parser.add_argument("--table", required=True, help="SourceObjectName.")
    parser.add_argument(
        "--legacy-table", required=True,
        help="Fully-qualified legacy table (e.g. UDM_Bronze.dna.PERS_SCD2).",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview only.")
    args = parser.parse_args()

    # Locate the python target tables via UdmTablesList.
    loader = TableConfigLoader()
    configs = loader.load_small_tables(source_name=args.source, table_name=args.table)
    configs += loader.load_large_tables(source_name=args.source, table_name=args.table)
    if not configs:
        logger.error(
            "No matching row in UdmTablesList for source=%s table=%s.",
            args.source, args.table,
        )
        return 2
    table_config = configs[0]
    target_bronze = table_config.bronze_full_table_name
    target_stage = table_config.stage_full_table_name

    if not table_exists(target_bronze):
        logger.error(
            "Target Bronze %s does not exist. Run a no-op pipeline pass first "
            "to auto-create the table from source schema.",
            target_bronze,
        )
        return 2
    if not table_exists(target_stage):
        logger.error(
            "Target Stage %s does not exist. Run a no-op pipeline pass first.",
            target_stage,
        )
        return 2

    df = _read_legacy(args.legacy_table)
    if len(df) == 0:
        logger.warning("Legacy table %s is empty — nothing to seed.", args.legacy_table)
        return 0

    df = _drop_legacy_columns(df)

    # Schema drift handling. The python target Bronze was auto-created from
    # the *current* source which may have gained columns since the legacy
    # snapshot was taken. Pad those columns with NULL so the hash and the
    # BCP load both see the canonical target schema.
    udm_meta_cols = {
        "UdmActiveFlag", "UdmEffectiveDateTime", "UdmEndDateTime",
        "UdmSourceBeginDate", "UdmSourceEndDate",
        "UdmHash", "UdmSource", "UdmScd2Operation", "UdmModifiedBy",
        "UdmCreateId", "UdmCreateDateTime",
        "UdmUpdateId", "UdmUpdateDateTime",
        "_scd2_key",
    }
    target_cols = set(get_target_column_order(target_bronze, exclude_columns=None))
    target_source_cols = target_cols - udm_meta_cols
    legacy_cols = set(df.columns)
    drift_padding = target_source_cols - legacy_cols
    if drift_padding:
        logger.info(
            "Schema drift: %d target column(s) missing from legacy — "
            "padding with NULL: %s",
            len(drift_padding), sorted(drift_padding),
        )
        df = df.with_columns(
            pl.lit(None).cast(pl.Utf8).alias(c) for c in drift_padding
        )

    # Compute UdmHash over SOURCE columns only — matches the pipeline's
    # behaviour where add_row_hash() runs on the extractor output before
    # any UDM metadata is appended. Without this filter the seeded hash
    # would include UdmActiveFlag / UdmEffectiveDateTime / UdmEndDateTime
    # and never match a fresh pipeline hash on the same data.
    source_only_cols = [c for c in df.columns if c not in udm_meta_cols]
    df_for_hash = df.select(source_only_cols)
    df_for_hash = add_row_hash(
        df_for_hash, exclude_cols=table_config.exclude_from_hash,
    )
    df = df.with_columns(df_for_hash["_row_hash"].alias("UdmHash"))

    # Now stamp the dual-pair source-date columns and the operation code.
    df = _build_source_begin(df, table_config.scd2_date_columns, table_config.default_begin_date)
    df = _build_source_end_and_op(df)

    output_dir = Path(config.CSV_OUTPUT_DIR)
    output_dir.mkdir(parents=True, exist_ok=True)

    bronze_rows = _seed_bronze(df, target_bronze, table_config, output_dir, args.dry_run)

    df_active = df.filter(pl.col("UdmActiveFlag") == 1)
    stage_rows = _seed_stage(df_active, target_stage, table_config, output_dir, args.dry_run)

    logger.info(
        "Legacy seed complete: Bronze=%d rows, Stage=%d rows. "
        "Verify with:\n"
        "  SELECT UdmActiveFlag, COUNT(*) FROM %s GROUP BY UdmActiveFlag;\n"
        "  python3 tools/validate_scd2.py --source %s --table %s",
        bronze_rows, stage_rows, target_bronze, args.source, args.table,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
