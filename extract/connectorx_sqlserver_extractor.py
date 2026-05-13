# ==========================================================================
# E-7: ConnectorX SQL Server XML type fallback to pyodbc.
#
# Location: extract/connectorx_sqlserver_extractor.py
#
# Root cause: ConnectorX panics on SQL Server XML columns because the Rust
# MSSQL type system has no XML mapping (connectorx/src/sources/mssql/
# typesystem.rs:99). This crashes MsgAccount, MsgAccountCache, and any
# other table with XML-typed columns.
#
# Fix: Before ConnectorX extraction, query INFORMATION_SCHEMA for XML
# columns. If found, build an explicit SELECT that CASTs XML columns to
# NVARCHAR(MAX), similar to how connectorx_oracle_extractor handles
# sentinel dates (E-4). If ConnectorX still fails (defense-in-depth),
# fall back to pyodbc extraction.
# ==========================================================================

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import pyodbc
import connectorx as cx
import polars as pl

from data_load.bcp_csv import prepare_dataframe_for_bcp, validate_schema_before_concat, write_bcp_csv
from extract import cx_read_sql_safe
from utils.sources import get_source_for_table

if TYPE_CHECKING:
    from orchestration.table_config import TableConfig
    from utils.sources import SourceSystem

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers: partition skew logging, NULL partition row supplementation
# ---------------------------------------------------------------------------

def _log_partition_skew(
    df: pl.DataFrame,
    partition_on: str,
    partition_num: int,
    table_config: TableConfig,
) -> None:
    """P2-3: Log partition column statistics and warn about potential skew."""
    if partition_on not in df.columns:
        return

    try:
        col = df[partition_on]
        col_min = col.min()
        col_max = col.max()
        col_null = col.null_count()
        avg_per_partition = len(df) / partition_num if partition_num > 0 else len(df)

        logger.info(
            "P2-3: Partition stats for %s.%s on [%s]: min=%s, max=%s, "
            "nulls=%d, total=%d, partitions=%d, avg_per_partition=%.0f",
            table_config.source_name, table_config.source_object_name,
            partition_on, col_min, col_max,
            col_null, len(df), partition_num, avg_per_partition,
        )

        if col_null > len(df) * 0.1:
            logger.warning(
                "P2-3: Partition column [%s] has %d NULL values (%.1f%%) in %s. "
                "ConnectorX excludes NULL rows from partitioned reads. "
                "Consider a different partition_on column.",
                partition_on, col_null, col_null / len(df) * 100,
                table_config.source_object_name,
            )
    except Exception:
        logger.debug("Could not compute partition skew stats for %s", partition_on)


def _supplement_null_partition_rows(
    df: pl.DataFrame,
    uri: str,
    base_query: str,
    partition_on: str,
    table_config: TableConfig,
) -> pl.DataFrame:
    """E-2: Fetch rows where partition column IS NULL and concat with main result.

    T-2 FIX: Uses safe_concat instead of diagonal_relaxed to prevent
    interpreter crashes on schema-mismatched DataFrames.
    """
    from utils.safe_concat import safe_concat

    try:
        null_query = f"{base_query} WHERE [{partition_on}] IS NULL"
        if " WHERE " in base_query.upper():
            null_query = f"{base_query} AND [{partition_on}] IS NULL"

        df_nulls = cx.read_sql(uri, null_query, return_type="polars")

        if len(df_nulls) > 0:
            logger.warning(
                "E-2: Found %d rows with NULL [%s] in %s — these would be "
                "silently excluded by ConnectorX partitioned extraction. "
                "Supplementing result.",
                len(df_nulls), partition_on, table_config.source_object_name,
            )
            df = safe_concat([df, df_nulls])
        else:
            logger.debug(
                "E-2: No NULL [%s] rows in %s",
                partition_on, table_config.source_object_name,
            )

    except Exception:
        logger.warning(
            "E-2: Failed to check NULL partition column rows for %s — "
            "continuing with partitioned result only",
            table_config.source_object_name, exc_info=True,
        )

    return df


# ---------------------------------------------------------------------------
# E-7: XML column detection and safe SELECT builder
# ---------------------------------------------------------------------------
# All three helpers use source.pyodbc_connection_string() to connect to the
# SOURCE server with source-specific credentials (e.g. DLHDEV for CCM).
# Do NOT use connections.get_source_connection() — that uses UDM target
# credentials which may differ from source credentials.
# ---------------------------------------------------------------------------

def _get_source_pyodbc_conn(source: SourceSystem) -> pyodbc.Connection:
    """Open a pyodbc connection to the source system using its own credentials.

    Centralises the single call to source.pyodbc_connection_string() so that
    every helper in this module goes through one place.
    """
    return pyodbc.connect(source.pyodbc_connection_string(), autocommit=True)


def _get_xml_columns(source: SourceSystem, table_config: TableConfig) -> set[str]:
    """Query source INFORMATION_SCHEMA to find XML-typed columns.

    Args:
        source: SourceSystem with host/database already overridden via
                get_source_for_table(table_config) -> with_overrides().
        table_config: TableConfig from UdmTablesList.

    Returns:
        Set of column names with DATA_TYPE = 'xml', or empty set if
        the query fails (logged as E-7 warning, extraction continues
        with SELECT * and may panic if XML columns exist).
    """
    try:
        conn = _get_source_pyodbc_conn(source)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COLUMN_NAME "
                "FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? AND DATA_TYPE = 'xml'",
                table_config.source_schema_name,
                table_config.source_object_name,
            )
            xml_cols = {row[0] for row in cursor.fetchall()}
            cursor.close()

            if xml_cols:
                logger.info(
                    "E-7: Found %d XML column(s) in %s.%s.%s: %s",
                    len(xml_cols),
                    table_config.source_database,
                    table_config.source_schema_name,
                    table_config.source_object_name,
                    sorted(xml_cols),
                )
            return xml_cols
        finally:
            conn.close()
    except Exception:
        logger.warning(
            "E-7: Could not query XML columns for %s.%s — "
            "ConnectorX extraction may panic if XML columns exist",
            table_config.source_name,
            table_config.source_object_name,
            exc_info=True,
        )
        return set()


def _get_all_columns(source: SourceSystem, table_config: TableConfig) -> list[str]:
    """Query source INFORMATION_SCHEMA for all column names in ordinal order.

    Needed to build an explicit SELECT that replaces SELECT * when XML
    columns are present. Column order matches what SELECT * would return.
    """
    conn = _get_source_pyodbc_conn(source)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COLUMN_NAME "
            "FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? "
            "ORDER BY ORDINAL_POSITION",
            table_config.source_schema_name,
            table_config.source_object_name,
        )
        columns = [row[0] for row in cursor.fetchall()]
        cursor.close()
        return columns
    finally:
        conn.close()


def _build_safe_select(
    all_cols: list[str],
    xml_cols: set[str],
    table_config: TableConfig,
) -> str:
    """Build an explicit SELECT with CAST for XML columns.

    Uses schema and table from TableConfig (sourced from UdmTablesList).
    """
    parts = [
        f"CAST([{c}] AS NVARCHAR(MAX)) AS [{c}]" if c in xml_cols else f"[{c}]"
        for c in all_cols
    ]
    return (
        f"SELECT {', '.join(parts)} "
        f"FROM [{table_config.source_schema_name}].[{table_config.source_object_name}]"
    )


def build_extract_query(
    source: SourceSystem,
    table_config: TableConfig,
    where_clause: str = "",
) -> str:
    """Build the extraction SQL: SELECT * or explicit SELECT with XML CASTs.

    Main entry point called before cx.read_sql(). Checks for XML columns
    and builds the appropriate query.

    Args:
        source: SourceSystem from get_source_for_table(table_config).
        table_config: TableConfig from UdmTablesList.
        where_clause: Optional WHERE clause to append (for windowed extraction).

    Returns:
        SQL query string for ConnectorX extraction.
    """
    xml_cols = _get_xml_columns(source, table_config)
    exclude_cols = table_config.exclude_columns

    if not xml_cols and not exclude_cols:
        # Hot path — no XML columns, no exclusions, use simple SELECT *
        base = (
            f"SELECT * FROM "
            f"[{table_config.source_schema_name}].[{table_config.source_object_name}]"
        )
        return f"{base} {where_clause}".strip()

    # Need explicit SELECT — get all columns from INFORMATION_SCHEMA
    all_cols = _get_all_columns(source, table_config)

    # Remove excluded columns
    if exclude_cols:
        before_count = len(all_cols)
        all_cols = [c for c in all_cols if c not in exclude_cols]
        dropped = before_count - len(all_cols)
        if dropped:
            logger.info(
                "E-XX: Excluding %d column(s) from %s.%s extraction: %s",
                dropped, table_config.source_name,
                table_config.source_object_name, sorted(exclude_cols),
            )
        else:
            logger.warning(
                "E-XX: ExcludeColumns configured for %s.%s but none matched "
                "INFORMATION_SCHEMA: %s",
                table_config.source_name,
                table_config.source_object_name, sorted(exclude_cols),
            )

    query = _build_safe_select(all_cols, xml_cols or set(), table_config)

    if xml_cols:
        logger.info(
            "E-7: Using explicit SELECT with CAST for %s.%s (XML columns: %s)",
            table_config.source_name,
            table_config.source_object_name,
            sorted(xml_cols),
        )
    return f"{query} {where_clause}".strip()


# ---------------------------------------------------------------------------
# Main extraction entry point
# ---------------------------------------------------------------------------

def extract_sqlserver_connectorx(
    table_config: TableConfig,
    output_dir: str | Path,
    partition_on: str | None = None,
    partition_num: int = 4,
) -> tuple[pl.DataFrame, Path]:
    """Extract from SQL Server via ConnectorX into a Polars DataFrame and write BCP CSV.

    E-7: Detects XML columns and CASTs them to NVARCHAR(MAX) to prevent
    ConnectorX Rust panics. Falls back to pyodbc if ConnectorX still fails.
    """
    source = get_source_for_table(table_config)
    uri = source.connectorx_uri()

    # E-7: Build query with XML column detection
    query = build_extract_query(source, table_config)

    logger.info(
        "ConnectorX SQL Server extract: %s (host=%s, db=%s)",
        query[:200], source.host, source.service_or_database,
    )

    cx_kwargs: dict = {
        "conn": uri,
        "query": query,
        "return_type": "polars",
    }

    if partition_on:
        if partition_num > 1:
            logger.warning(
                "E-1: Overriding partition_num from %d to 1 for %s — "
                "CDC-sensitive extraction requires a single consistent snapshot.",
                partition_num, table_config.source_object_name,
            )
        cx_kwargs["partition_on"] = partition_on
        cx_kwargs["partition_num"] = 1

    try:
        # B-7: Use safe wrapper with Rust panic recovery and retry.
        df = cx_read_sql_safe(
            conn=uri,
            query=query,
            return_type="polars",
            partition_on=cx_kwargs.get("partition_on"),
            partition_num=cx_kwargs.get("partition_num"),
            context=f"SQL Server extract {table_config.source_object_name}",
        )
    except BaseException as cx_err:
        # E-7 defense-in-depth: if ConnectorX still panics (e.g. XML column
        # we couldn't detect, or a new unsupported type), fall back to pyodbc.
        logger.warning(
            "E-7: ConnectorX failed for %s.%s (%s). Falling back to pyodbc.",
            table_config.source_name, table_config.source_object_name, cx_err,
        )
        df = _pyodbc_fallback_extract(source, table_config)

    logger.info(
        "Extracted %d rows, %d columns from %s.%s.%s",
        len(df), len(df.columns),
        table_config.source_database,
        table_config.source_schema_name,
        table_config.source_object_name,
    )

    if partition_on and partition_on in df.columns:
        _log_partition_skew(df, partition_on, 1, table_config)
        df = _supplement_null_partition_rows(df, uri, query, partition_on, table_config)

    # Prepare and write BCP CSV
    df = prepare_dataframe_for_bcp(
        df,
        exclude_from_hash=table_config.exclude_from_hash,
    )
    csv_path = write_bcp_csv(
        df,
        Path(output_dir)
        / f"{table_config.source_name}_{table_config.source_object_name}.csv",
    )

    return df, csv_path


def _pyodbc_fallback_extract(
    source: SourceSystem,
    table_config: TableConfig,
) -> pl.DataFrame:
    """E-7 fallback: Extract via pyodbc when ConnectorX panics.

    Slower than ConnectorX but handles all SQL Server types including XML.
    """
    conn = _get_source_pyodbc_conn(source)
    try:
        query = (
            f"SELECT * FROM "
            f"[{table_config.source_schema_name}].[{table_config.source_object_name}]"
        )
        cursor = conn.cursor()
        cursor.execute(query)
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        cursor.close()

        if not rows:
            return pl.DataFrame(schema={c: pl.Utf8 for c in columns})

        return pl.DataFrame(
            [dict(zip(columns, row)) for row in rows],
        )
    finally:
        conn.close()

# --- Similarly update extract_sqlserver_connectorx_windowed() ---

def extract_sqlserver_connectorx_windowed(
    table_config: TableConfig,
    output_dir: str | Path,
    start_date: date,
    end_date: date,
    partition_on: str | None = None,
    partition_num: int = 4,
) -> tuple[pl.DataFrame, Path]:
    """Extract a date window from SQL Server via ConnectorX.

    E-7: Detects XML columns and CASTs them to NVARCHAR(MAX).
    """
    source = get_source_for_table(table_config)
    uri = source.connectorx_uri()

    date_col = table_config.source_aggregate_column_name
    table = table_config.source_object_name

    where_clause = (
        f"WHERE [{date_col}] >= '{start_date}' AND [{date_col}] < '{end_date}'"
    )

    # E-7: Build query with XML column detection + WHERE clause
    query = build_extract_query(source, table_config, where_clause)

    logger.info(
        "ConnectorX SQL Server windowed extract: %s [%s, %s)",
        table, start_date, end_date,
    )

    cx_kwargs: dict = {
        "conn": uri,
        "query": query,
        "return_type": "polars",
    }

    if partition_on:
        if partition_num > 1:
            logger.warning(
                "E-1: Overriding partition_num from %d to 1 for windowed %s.",
                partition_num, table,
            )
            partition_num = 1
        cx_kwargs["partition_on"] = partition_on
        cx_kwargs["partition_num"] = partition_num

    # B-7: Use safe wrapper with Rust panic recovery and retry.
    df = cx_read_sql_safe(
        conn=cx_kwargs["conn"],
        query=cx_kwargs["query"],
        return_type=cx_kwargs["return_type"],
        partition_on=cx_kwargs.get("partition_on"),
        partition_num=cx_kwargs.get("partition_num"),
        context=f"SQL Server windowed extract {table} [{start_date}, {end_date})",
    )
    logger.info(
        "Extracted %d rows from %s.%s for [%s, %s)",
        len(df), table_config.source_schema_name, table, start_date, end_date,
    )

    if len(df) == 0:
        csv_path = (
            Path(output_dir)
            / f"{table_config.source_name}_{table}_{start_date}.csv"
        )
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        csv_path.write_text("")
        return df, csv_path

    df = prepare_dataframe_for_bcp(
        df,
        fix_oracle_dates=False,
        exclude_from_hash=table_config.exclude_from_hash,
    )

    csv_path = write_bcp_csv(
        df,
        Path(output_dir)
        / f"{table_config.source_name}_{table}_{start_date}.csv",
    )

    return df, csv_path