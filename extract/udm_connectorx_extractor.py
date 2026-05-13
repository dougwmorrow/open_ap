"""ConnectorX reader for internal UDM SQL Server reads (Stage/Bronze comparisons).

Used by CDC and SCD2 to read existing data from UDM_Stage and UDM_Bronze tables.

Provides:
  - read_stage_table(): Full read of current CDC rows (small tables).
  - read_stage_table_windowed(): Scoped to a date range (large tables).
  - read_bronze_table(): Full read of active Bronze rows (small tables).
  - read_bronze_for_pks(): Targeted Bronze read via PK staging table (large tables).
  - table_exists(), get_table_row_count(): Utility functions.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import connectorx as cx
import polars as pl
from utils.connections import stage_connectorx_uri, bronze_connectorx_uri, get_connection
from extract import cx_read_sql_safe
from data_load.bcp_csv import write_bcp_csv
from data_load.sanitize import sanitize_strings
from data_load.schema_utils import get_column_types
from data_load.sanitize import normalize_boolean_to_int8

if TYPE_CHECKING:
    from orchestration.table_config import TableConfig

logger = logging.getLogger(__name__)


def read_stage_table(
    full_table_name: str,
    columns: list[str] | None = None,
) -> pl.DataFrame:
    """Read current CDC rows from Stage table.

    Args:
        full_table_name: e.g. 'UDM_Stage.DNA.ACCT_cdc'
        columns: S-3 — If provided, select only these columns plus CDC internals
                 instead of SELECT *. Reduces memory for tables with accumulated
                 schema drift columns.

    Returns:
        DataFrame of rows WHERE _cdc_is_current = 1.
    """
    uri = stage_connectorx_uri()

    if columns:
        # S-3: Select only needed columns to avoid loading phantom columns
        # from schema drift. Always include CDC internal columns.
        cdc_internals = [
            "_row_hash", "_extracted_at",
            "_cdc_operation", "_cdc_valid_from", "_cdc_valid_to",
            "_cdc_is_current", "_cdc_batch_id",
        ]
        all_cols = list(dict.fromkeys(columns + cdc_internals))
        col_list = ", ".join(f"[{c}]" for c in all_cols)
        query = f"SELECT {col_list} FROM {full_table_name} WHERE _cdc_is_current = 1"
    else:
        query = f"SELECT * FROM {full_table_name} WHERE _cdc_is_current = 1"

    logger.info("Reading Stage table: %s", full_table_name)
    # B-7: Use safe wrapper with Rust panic recovery and retry.
    df = cx_read_sql_safe(
        conn=uri, query=query, context=f"Stage read {full_table_name}",
    )
    logger.info("Read %d current rows from %s", len(df), full_table_name)
    # C-3b: Normalize BIT columns (Boolean→Int8) at read time to prevent
    # dtype mismatch when concatenating with CDC-annotated DataFrames.
    df = normalize_boolean_to_int8(df)
    return df


def read_bronze_table(full_table_name: str) -> pl.DataFrame:
    """Read active Bronze rows for SCD2 comparison.

    Args:
        full_table_name: e.g. 'UDM_Bronze.DNA.ACCT_scd2_python'

    Returns:
        DataFrame of rows WHERE UdmActiveFlag = 1, excluding _scd2_key.
    """
    uri = bronze_connectorx_uri()

    # Get columns excluding _scd2_key (IDENTITY)
    col_query = (
        f"SELECT COLUMN_NAME FROM {full_table_name.split('.')[0]}.INFORMATION_SCHEMA.COLUMNS "
        f"WHERE TABLE_SCHEMA = '{full_table_name.split('.')[1]}' "
        f"AND TABLE_NAME = '{full_table_name.split('.')[2]}' "
        f"AND COLUMN_NAME != '_scd2_key' "
        f"ORDER BY ORDINAL_POSITION"
    )
    cols_df = cx.read_sql(uri, col_query, return_type="polars")
    columns = cols_df["COLUMN_NAME"].to_list()

    col_list = ", ".join(f"[{c}]" for c in columns)
    query = f"SELECT {col_list} FROM {full_table_name} WHERE UdmActiveFlag = 1"

    logger.info("Reading Bronze table: %s", full_table_name)
    # B-7: Use safe wrapper with Rust panic recovery and retry.
    df = cx_read_sql_safe(
        conn=uri, query=query, context=f"Bronze read {full_table_name}",
    )
    logger.info("Read %d active rows from %s", len(df), full_table_name)
    df = normalize_boolean_to_int8(df)
    return df


def read_stage_table_windowed(
    full_table_name: str,
    date_column: str,
    start_date: date,
    end_date: date,
) -> pl.DataFrame:
    """Read current CDC rows from Stage table within a date window.

    For large tables — only loads rows where the business date column
    falls within [start_date, end_date). This scopes CDC comparison
    to the extraction window.

    Args:
        full_table_name: e.g. 'UDM_Stage.DNA.ACCT_cdc'
        date_column: The business date column to filter on.
        start_date: Start of date range (inclusive).
        end_date: End of date range (exclusive).

    Returns:
        DataFrame of current CDC rows within the date window.
    """
    uri = stage_connectorx_uri()
    # P2-9: Use open-ended datetime range instead of CAST(AS DATE) to preserve
    # SARGability. CAST() wrapping the column prevents index seeks, causing full
    # scans on 300M+ row Stage tables. Using 00:00:00.000 handles DATETIME2
    # precision without wrapping the column.
    query = (
        f"SELECT * FROM {full_table_name} "
        f"WHERE _cdc_is_current = 1 "
        f"AND [{date_column}] >= '{start_date} 00:00:00.000' "
        f"AND [{date_column}] < '{end_date} 00:00:00.000'"
    )

    logger.info(
        "Reading Stage table windowed: %s [%s, %s)",
        full_table_name, start_date, end_date,
    )
    # B-7: Use safe wrapper with Rust panic recovery and retry.
    df = cx_read_sql_safe(
        conn=uri, query=query,
        context=f"Stage windowed read {full_table_name} [{start_date}, {end_date})",
    )
    logger.info("Read %d current rows from %s in window", len(df), full_table_name)
    df = normalize_boolean_to_int8(df)
    return df


def read_bronze_deleted_pks(
    full_table_name: str,
    pk_columns: list[str],
    candidate_pks: pl.DataFrame,
    output_dir: str | Path,
    table_config: TableConfig,
) -> pl.DataFrame:
    """M3: return PK columns of Bronze rows with ``UdmActiveFlag = 2`` (deleted at
    source) that match any of ``candidate_pks``.

    Used by ``run_scd2`` (small tables) for resurrection detection. When a PK
    appears in the current extract but is not in the active Bronze set, it
    might be a brand-new insert OR a resurrection of a previously deleted PK.
    Querying Bronze for matching Flag=2 rows distinguishes the two cases.

    Returns only the PK columns — full row content is not needed since the
    new version is built entirely from the current extract data.

    Implementation mirrors ``read_bronze_for_pks`` (staging table + JOIN) so
    it scales beyond ``WHERE PK IN (...)`` size limits. Staging table is
    named ``_staging_scd2_resurrection_lookup_{table}`` so
    ``schema/staging_cleanup.py`` reclaims it after a crash.
    """
    from data_load import bcp_loader

    if len(candidate_pks) == 0:
        # Empty candidate set — return empty DataFrame with PK schema preserved.
        return candidate_pks.select(pk_columns)

    db = full_table_name.split(".")[0]
    schema = full_table_name.split(".")[1]
    staging_table = (
        f"{db}.{schema}._staging_scd2_resurrection_lookup_{table_config.source_object_name}"
    )

    pk_types = get_column_types(full_table_name, pk_columns)

    conn = get_connection(db)
    try:
        cursor = conn.cursor()
        pk_col_defs = ", ".join(f"[{c}] {pk_types[c]}" for c in pk_columns)
        cursor.execute(f"""
            IF OBJECT_ID('{staging_table}', 'U') IS NOT NULL DROP TABLE {staging_table};
            CREATE TABLE {staging_table} ({pk_col_defs})
        """)
        cursor.close()
    finally:
        conn.close()

    try:
        pks_clean = sanitize_strings(candidate_pks.select(pk_columns))
        csv_path = write_bcp_csv(
            pks_clean,
            Path(output_dir)
            / f"{table_config.source_name}_{table_config.source_object_name}_resurrection_lookup_pks.csv",
        )
        # is_stage=True picks BCP_STAGE_BATCH_SIZE (100K) so heap-style
        # staging loads don't fall through to the 800-row Bronze default.
        bcp_loader.bcp_load(str(csv_path), staging_table, atomic=False, is_stage=True)
        bcp_loader.create_staging_index(staging_table, pk_columns, row_count=len(candidate_pks))

        uri = bronze_connectorx_uri()
        select_cols = ", ".join(f"b.[{c}]" for c in pk_columns)
        join_condition = " AND ".join(f"b.[{c}] = s.[{c}]" for c in pk_columns)
        query = (
            f"SELECT DISTINCT {select_cols} "
            f"FROM {full_table_name} b "
            f"INNER JOIN {staging_table} s ON {join_condition} "
            f"WHERE b.UdmActiveFlag = 2"
        )

        logger.info(
            "M3: Looking up Flag=2 PKs (potential resurrections) for %d candidates in %s",
            len(candidate_pks), full_table_name,
        )
        df = cx_read_sql_safe(
            conn=uri, query=query,
            context=f"M3 resurrection lookup {full_table_name}",
        )
        logger.info("M3: Found %d resurrection candidates (Flag=2 PKs match)", len(df))
        df = normalize_boolean_to_int8(df)
        return df
    finally:
        conn = get_connection(db)
        try:
            cursor = conn.cursor()
            cursor.execute(f"DROP TABLE IF EXISTS {staging_table}")
            cursor.close()
        finally:
            conn.close()


def read_bronze_for_pks(
    full_table_name: str,
    pk_columns: list[str],
    pk_df: pl.DataFrame,
    output_dir: str | Path,
    table_config: TableConfig,
) -> pl.DataFrame:
    """Read active Bronze rows matching specific PKs via staging table.

    For large tables — avoids loading all 3B active rows. Instead:
      1. BCP the PKs into a temp staging table.
      2. SELECT Bronze rows with INNER JOIN on staging.
      3. DROP staging table.

    Args:
        full_table_name: e.g. 'UDM_Bronze.DNA.ACCT_scd2_python'
        pk_columns: Primary key column names.
        pk_df: DataFrame containing PKs to look up.
        output_dir: Directory for staging CSV files.
        table_config: Table config for naming.

    Returns:
        DataFrame of active Bronze rows matching the provided PKs,
        excluding _scd2_key.
    """
    from data_load import bcp_loader

    db = full_table_name.split(".")[0]
    schema = full_table_name.split(".")[1]
    table_part = full_table_name.split(".")[2]
    staging_table = f"{db}.{schema}._staging_bronze_lookup_{table_config.source_object_name}"

    # Get PK types from Bronze table
    pk_types = get_column_types(full_table_name, pk_columns)

    # Create staging table
    conn = get_connection(db)
    try:
        cursor = conn.cursor()
        pk_col_defs = ", ".join(f"[{c}] {pk_types[c]}" for c in pk_columns)
        cursor.execute(f"""
            IF OBJECT_ID('{staging_table}', 'U') IS NOT NULL DROP TABLE {staging_table};
            CREATE TABLE {staging_table} ({pk_col_defs})
        """)
        cursor.close()
    finally:
        conn.close()

    try:
        # BCP load PKs into staging
        pks_clean = sanitize_strings(pk_df.select(pk_columns))
        csv_path = write_bcp_csv(
            pks_clean,
            Path(output_dir) / f"{table_config.source_name}_{table_config.source_object_name}_bronze_lookup_pks.csv",
        )
        # E-3: Staging tables are ephemeral — atomic=False for performance.
        # is_stage=True picks BCP_STAGE_BATCH_SIZE (100K) so heap-style
        # staging loads don't fall through to the 800-row Bronze default.
        bcp_loader.bcp_load(str(csv_path), staging_table, atomic=False, is_stage=True)

        # P2-5: Index staging table for efficient JOIN against large Bronze tables
        bcp_loader.create_staging_index(staging_table, pk_columns, row_count=len(pk_df))

        # Get Bronze columns excluding _scd2_key
        uri = bronze_connectorx_uri()
        col_query = (
            f"SELECT COLUMN_NAME FROM {db}.INFORMATION_SCHEMA.COLUMNS "
            f"WHERE TABLE_SCHEMA = '{schema}' "
            f"AND TABLE_NAME = '{table_part}' "
            f"AND COLUMN_NAME != '_scd2_key' "
            f"ORDER BY ORDINAL_POSITION"
        )
        cols_df = cx.read_sql(uri, col_query, return_type="polars")
        columns = cols_df["COLUMN_NAME"].to_list()

        col_list = ", ".join(f"b.[{c}]" for c in columns)
        join_condition = " AND ".join(f"b.[{c}] = s.[{c}]" for c in pk_columns)

        query = (
            f"SELECT {col_list} "
            f"FROM {full_table_name} b "
            f"INNER JOIN {staging_table} s ON {join_condition} "
            f"WHERE b.UdmActiveFlag = 1"
        )

        logger.info("Reading Bronze rows for %d PKs from %s", len(pk_df), full_table_name)
        df = cx.read_sql(uri, query, return_type="polars")
        logger.info("Read %d active Bronze rows matching PKs", len(df))
        df = normalize_boolean_to_int8(df)
        return df

    finally:
        # Always drop staging table
        conn = get_connection(db)
        try:
            cursor = conn.cursor()
            cursor.execute(f"DROP TABLE IF EXISTS {staging_table}")
            cursor.close()
        finally:
            conn.close()


def table_exists(full_table_name: str) -> bool:
    """Check if a table exists in the target database.

    Args:
        full_table_name: e.g. 'UDM_Stage.DNA.ACCT_cdc'

    Returns:
        True if the table exists.
    """
    parts = full_table_name.split(".")
    db, schema, table = parts[0], parts[1], parts[2]

    conn = get_connection(db)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?",
            schema,
            table,
        )
        count = cursor.fetchone()[0]
        cursor.close()
        return count > 0
    finally:
        conn.close()


def get_table_row_count(full_table_name: str) -> int:
    """Get approximate row count via sys.dm_db_partition_stats (P2-4).

    Uses partition stats instead of COUNT(*) — returns instantly even on 3B-row tables.
    Accuracy is within a few percent, sufficient for monitoring and guards.
    """
    db = full_table_name.split(".")[0]
    conn = get_connection(db)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT SUM(p.row_count) "
            "FROM sys.dm_db_partition_stats p "
            "WHERE p.object_id = OBJECT_ID(?) "
            "AND p.index_id IN (0, 1)",
            full_table_name,
        )
        row = cursor.fetchone()
        cursor.close()
        count = int(row[0]) if row and row[0] is not None else 0
        return count
    finally:
        conn.close()