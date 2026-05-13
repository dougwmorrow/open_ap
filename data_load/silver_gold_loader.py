"""Truncate-and-reload loader for UDM_Silver and UDM_Gold tables.

Silver and Gold layers are "clean" copies — no CDC _row_hash, no SCD2
UdmHash/UdmActiveFlag columns. The load pattern is:

  1. Ensure target table exists (CREATE TABLE if not, ALTER TABLE ADD if
     schema drifts — mirrors table_creator.py logic).
  2. TRUNCATE the target table.
  3. BCP BULK INSERT the full extraction DataFrame.

This is intentionally simple. File-based sources that target Silver/Gold
are typically reference data, lookup tables, or aggregated datasets where
full-replace is the correct semantic. No CDC or SCD2 overhead.

Data flow:
  extract_file() -> DataFrame
    -> prepare_dataframe_for_bcp() (sanitize, but NO _row_hash)
    -> write_bcp_csv()
    -> ensure_silver_gold_table() (DDL if needed)
    -> TRUNCATE TABLE
    -> bcp_load()

Place this file at: data_load/silver_gold_loader.py
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

from utils.connections import cursor_for, quote_identifier, quote_table, get_connection
from data_load.bcp_csv import prepare_dataframe_for_bcp, write_bcp_csv
from data_load import bcp_loader
from data_load.schema_utils import get_column_metadata

if TYPE_CHECKING:
    from orchestration.file_config import FileConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_to_silver(
    file_config: FileConfig,
    df: pl.DataFrame,
    output_dir: Path,
) -> int:
    """Truncate-and-reload data into the Silver table.

    Args:
        file_config: File configuration with silver_full_table_name.
        df: Extracted DataFrame (source columns only, no CDC/SCD2 columns).
        output_dir: Directory for temp BCP CSV files.

    Returns:
        Number of rows loaded.
    """
    return _truncate_and_reload(
        file_config=file_config,
        df=df,
        full_table_name=file_config.silver_full_table_name,
        layer="Silver",
        output_dir=output_dir,
    )


def load_to_gold(
    file_config: FileConfig,
    df: pl.DataFrame,
    output_dir: Path,
) -> int:
    """Truncate-and-reload data into the Gold table.

    Args:
        file_config: File configuration with gold_full_table_name.
        df: Extracted DataFrame (source columns only, no CDC/SCD2 columns).
        output_dir: Directory for temp BCP CSV files.

    Returns:
        Number of rows loaded.
    """
    return _truncate_and_reload(
        file_config=file_config,
        df=df,
        full_table_name=file_config.gold_full_table_name,
        layer="Gold",
        output_dir=output_dir,
    )


# ---------------------------------------------------------------------------
# Internal implementation
# ---------------------------------------------------------------------------

def _truncate_and_reload(
    file_config: FileConfig,
    df: pl.DataFrame,
    full_table_name: str,
    layer: str,
    output_dir: Path,
) -> int:
    """Core truncate-and-reload logic shared by Silver and Gold.

    Steps:
        1. Prepare DataFrame for BCP (sanitize strings, cast booleans, NO row hash).
        2. Ensure target table exists (auto-create DDL from DataFrame schema).
        3. Handle schema evolution (add new columns if source has them).
        4. TRUNCATE TABLE.
        5. BCP BULK INSERT.

    Returns:
        Number of rows loaded.
    """

    source_name = file_config.source_name
    table_name = file_config.table_name

    logger.info(
        "%s truncate-and-reload: %s.%s -> %s (%d rows)",
        layer, source_name, table_name, full_table_name, len(df),
    )

    if len(df) == 0:
        logger.warning(
            "%s: Empty DataFrame for %s.%s — skipping load",
            layer, source_name, table_name,
        )
        return 0

    # Step 1: Prepare for BCP
    df_clean = prepare_dataframe_for_bcp(df, source_is_oracle=False)

    # Step 2: Drop and recreate table from current source schema.
    # Silver/Gold is full-replace — no CDC/SCD2 state to preserve.
    # This guarantees the table always matches the source, avoiding
    # column order drift (P0-1) and stale columns from prior schemas.
    _drop_if_exists(full_table_name)
    _ensure_table(full_table_name, df_clean)

    # Step 3: Write BCP CSV (column order matches table — both come from df_clean)
    csv_path = output_dir / f"{source_name}_{table_name}_{layer.lower()}.csv"
    write_bcp_csv(df_clean, csv_path)

    # Step 4: BCP load
    rows_loaded = bcp_loader.bcp_load(
        str(csv_path), full_table_name,
        is_stage=False,
        atomic=False,
    )

    logger.info(
        "%s: Loaded %d rows into %s",
        layer, rows_loaded, full_table_name,
    )

    try:
        csv_path.unlink()
    except OSError:
        logger.debug("Could not delete temp CSV: %s", csv_path)

    return rows_loaded

def _drop_if_exists(full_table_name: str) -> None:
    """Drop a Silver/Gold table if it exists."""
    parts = full_table_name.split(".")
    db = parts[0]
    q_full = quote_table(full_table_name)

    with cursor_for(db) as cur:
        cur.execute(
            f"IF OBJECT_ID('{full_table_name}', 'U') IS NOT NULL "
            f"DROP TABLE {q_full}"
        )
    logger.info("Dropped table (if existed): %s", full_table_name)

def _ensure_table(full_table_name: str, df: pl.DataFrame) -> bool:
    """Create the target table if it doesn't exist. Returns True if created.

    Schema: source columns only — no CDC or SCD2 metadata columns.
    Silver/Gold tables are clean, business-ready copies.
    """
    parts = full_table_name.split(".")
    db, schema, table = parts[0], parts[1], parts[2]
    q_db = quote_identifier(db)
    q_schema = quote_identifier(schema)
    q_full = quote_table(full_table_name)

    conn = get_connection(db)
    try:
        cursor = conn.cursor()

        # Check if table exists
        cursor.execute(
            f"SELECT 1 FROM {q_db}.INFORMATION_SCHEMA.TABLES "
            f"WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?",
            schema, table,
        )
        if cursor.fetchone():
            cursor.close()
            return False

        # Ensure schema exists
        cursor.execute(
            f"SELECT 1 FROM {q_db}.sys.schemas WHERE name = ?", schema,
        )
        if not cursor.fetchone():
            cursor.execute(f"EXEC({q_db}..sp_executesql N'CREATE SCHEMA {q_schema}')")

        # Build column DDL from DataFrame — source columns only
        col_defs = _build_column_ddl(df)
        col_ddl = ",\n".join(col_defs)

        cursor.execute(f"CREATE TABLE {q_full} (\n{col_ddl}\n)")
        cursor.close()
        logger.info("Created %s table: %s", db, full_table_name)
        return True
    finally:
        conn.close()


def _evolve_columns(full_table_name: str, df: pl.DataFrame, layer: str) -> None:
    """Add new columns to an existing Silver/Gold table if the source has them.

    Only ADDs columns — never drops or changes types. Mirrors the Stage/Bronze
    schema evolution philosophy from schema/evolution.py.
    """
    existing_meta = get_column_metadata(full_table_name)
    existing_names = {m.column_name for m in existing_meta}
    new_names = set(df.columns)

    added = new_names - existing_names
    if not added:
        return

    logger.info(
        "%s schema evolution for %s: adding %d column(s): %s",
        layer, full_table_name, len(added), sorted(added),
    )

    parts = full_table_name.split(".")
    db = parts[0]
    q_full = quote_table(full_table_name)

    conn = get_connection(db)
    try:
        cursor = conn.cursor()
        for col_name in sorted(added):
            sql_type = _polars_to_sql_type(df[col_name].dtype)
            q_col = quote_identifier(col_name)
            cursor.execute(f"ALTER TABLE {q_full} ADD {q_col} {sql_type} NULL")
            logger.info("%s: Added column %s (%s) to %s", layer, col_name, sql_type, full_table_name)
        cursor.close()
    finally:
        conn.close()


def _build_column_ddl(df: pl.DataFrame) -> list[str]:
    """Build SQL column definitions from a Polars DataFrame."""
    defs = []
    for col_name in df.columns:
        sql_type = _polars_to_sql_type(df[col_name].dtype)
        q_col = quote_identifier(col_name)
        defs.append(f"    {q_col} {sql_type} NULL")
    return defs


def _polars_to_sql_type(dtype: pl.DataType) -> str:
    """Map Polars dtype to SQL Server type. Matches table_creator.py logic."""
    import polars as pl

    if dtype == pl.Utf8 or dtype == pl.Categorical:
        return "NVARCHAR(MAX)"
    elif dtype == pl.Int8:
        return "TINYINT"
    elif dtype == pl.Int16:
        return "SMALLINT"
    elif dtype == pl.Int32:
        return "INT"
    elif dtype == pl.Int64:
        return "BIGINT"
    elif dtype == pl.UInt8:
        return "SMALLINT"
    elif dtype == pl.UInt16:
        return "INT"
    elif dtype == pl.UInt32:
        return "BIGINT"
    elif dtype == pl.UInt64:
        return "BIGINT"
    elif dtype == pl.Float32:
        return "REAL"
    elif dtype == pl.Float64:
        return "FLOAT"
    elif dtype == pl.Boolean:
        return "BIT"
    elif dtype == pl.Date:
        return "DATE"
    elif dtype in (pl.Datetime, pl.Datetime("ms"), pl.Datetime("us"), pl.Datetime("ns")):
        return "DATETIME2"
    elif dtype == pl.Time:
        return "TIME"
    elif dtype == pl.Duration:
        return "BIGINT"
    elif dtype == pl.Binary:
        return "VARBINARY(MAX)"
    elif dtype == pl.Null:
        return "NVARCHAR(MAX)"
    else:
        # Catch-all for Decimal, nested types, etc.
        return "NVARCHAR(MAX)"


def _truncate_with_retry(
    full_table_name: str,
    layer: str,
    max_retries: int = 3,
    retry_delay: float = 2.0,
) -> None:
    """TRUNCATE TABLE with connection retry logic.

    The first connection after table creation can fail with TCP reset
    (0x2746 / 10054) if the server hasn't fully committed the DDL.
    Retrying with a fresh connection resolves this.

    Args:
        full_table_name: 3-part table name (e.g. UDM_Silver.fin.CallReportProduct).
        layer: 'Silver' or 'Gold' for logging.
        max_retries: Number of retry attempts.
        retry_delay: Seconds to wait between retries.
    """
    import time

    db = full_table_name.split(".")[0]
    q_full = quote_table(full_table_name)

    for attempt in range(1, max_retries + 1):
        try:
            conn = get_connection(db)
            try:
                cursor = conn.cursor()
                cursor.execute(f"TRUNCATE TABLE {q_full}")
                cursor.close()
            finally:
                conn.close()
            logger.info("%s: Truncated %s", layer, full_table_name)
            return
        except Exception:
            if attempt == max_retries:
                logger.exception(
                    "%s: TRUNCATE failed for %s after %d attempts",
                    layer, full_table_name, max_retries,
                )
                raise
            logger.warning(
                "%s: TRUNCATE attempt %d/%d failed for %s — "
                "retrying in %.1fs with fresh connection",
                layer, attempt, max_retries, full_table_name, retry_delay,
            )
            time.sleep(retry_delay)