"""turbodbc SQL Server extraction -> Arrow -> Polars DataFrame -> BCP CSV.

XML-capable fallback extractor for SQL Server sources (CCM, EPICOR, etc.)
when ConnectorX cannot handle tables containing XML data type columns.

turbodbc uses ODBC Driver 18 with Apache Arrow columnar fetching
(fetchallarrow()), providing ~3-10x faster bulk reads than pyodbc's
row-wise cursor. Arrow tables convert to Polars via zero-copy pl.from_arrow().

Routing: router.py sends tables here when INFORMATION_SCHEMA detects XML
columns that would crash ConnectorX (PanicException: not implemented: xml).

XML handling strategy:
  - turbodbc also cannot fetch raw XML columns (SQL_SS_XML type -152).
  - All XML columns are auto-detected via INFORMATION_SCHEMA.COLUMNS and
    CAST to NVARCHAR(MAX) in the SELECT, which is lossless (both types
    store up to 2 GB). This happens transparently — callers see string
    columns where XML columns existed in the source.

Provides two modes matching ConnectorX extractor signatures:
  - extract_sqlserver_turbodbc(): Full table scan (small tables).
  - extract_sqlserver_turbodbc_windowed(): Date-windowed extraction (large tables).

Dependencies:
  - turbodbc (pip install turbodbc or conda install -c conda-forge turbodbc)
  - pyarrow (transitive dependency of turbodbc Arrow fetching)
  - ODBC Driver 18 for SQL Server (system-level, already installed for BCP/pyodbc)
  - unixODBC-devel (system-level: dnf install unixODBC-devel)
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

import utils.configuration as config
from data_load.bcp_csv import prepare_dataframe_for_bcp, write_bcp_csv
from utils.sources import get_source

if TYPE_CHECKING:
    from orchestration.table_config import TableConfig

logger = logging.getLogger(__name__)

# SQL Server data types that turbodbc/ConnectorX cannot handle natively.
# All are CAST to NVARCHAR(MAX) in extraction queries.
_UNSUPPORTED_TYPES = frozenset({
    "xml",
    "geography",
    "geometry",
    "hierarchyid",
    "sql_variant",
})


# ---------------------------------------------------------------------------
# ODBC connection factory
# ---------------------------------------------------------------------------

def _build_odbc_connection_string(source_name: str) -> str:
    """Build an ODBC connection string for a SQL Server source.

    Uses the same ODBC Driver 18 already installed for BCP and pyodbc.
    """
    source = get_source(source_name)
    return (
        f"Driver={{{config.ODBC_DRIVER}}};"
        f"Server={source.host},{source.port};"
        f"Database={source.service_or_database};"
        f"UID={source.user};"
        f"PWD={source.password};"
        "TrustServerCertificate=yes;"
    )


def _get_turbodbc_connection(source_name: str):
    """Create a turbodbc connection with optimal fetch settings.

    Returns a turbodbc connection configured for:
      - prefer_unicode=True: Ensures NVARCHAR columns return proper Unicode.
      - use_async_io=True: Overlaps network I/O with Arrow buffer construction.
      - read_buffer_size: Rows buffered per ODBC fetch call. turbodbc's Arrow
        path works best with large buffers (fewer round-trips).
    """
    import turbodbc

    connection_string = _build_odbc_connection_string(source_name)

    options = turbodbc.make_options(
        prefer_unicode=True,
        use_async_io=True,
        read_buffer_size=turbodbc.Rows(10_000),
    )

    conn = turbodbc.connect(connection_string=connection_string, turbodbc_options=options)
    return conn


# ---------------------------------------------------------------------------
# XML column detection and query rewriting
# ---------------------------------------------------------------------------

def _detect_xml_columns(source_name: str, schema: str, table: str) -> list[str]:
    """Query INFORMATION_SCHEMA.COLUMNS to find XML (and other unsupported) columns.

    Uses pyodbc for this metadata query since it's lightweight and always
    available. Returns list of column names that need CAST to NVARCHAR(MAX).
    """
    import pyodbc

    source = get_source(source_name)
    conn_str = (
        f"DRIVER={{{config.ODBC_DRIVER}}};"
        f"SERVER={source.host},{source.port};"
        f"DATABASE={source.service_or_database};"
        f"UID={source.user};"
        f"PWD={source.password};"
        "TrustServerCertificate=yes;"
    )

    conn = pyodbc.connect(conn_str)
    try:
        cursor = conn.cursor()
        # H-3: Parameterized query to prevent SQL injection.
        cursor.execute(
            "SELECT COLUMN_NAME, DATA_TYPE "
            "FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? "
            "ORDER BY ORDINAL_POSITION",
            schema,
            table,
        )
        rows = cursor.fetchall()
        cursor.close()
    finally:
        conn.close()

    xml_cols = [row[0] for row in rows if row[1].lower() in _UNSUPPORTED_TYPES]

    if xml_cols:
        logger.info(
            "Detected %d unsupported-type columns in %s.%s requiring CAST: %s",
            len(xml_cols), schema, table, xml_cols,
        )

    return xml_cols


def _build_safe_select(
    source_name: str,
    schema: str,
    table: str,
    where_clause: str = "",
) -> tuple[str, list[str]]:
    """Build a SELECT that CASTs XML columns to NVARCHAR(MAX).

    Returns:
        Tuple of (SQL query string, list of XML column names that were CAST).
    """
    import pyodbc

    source = get_source(source_name)
    conn_str = (
        f"DRIVER={{{config.ODBC_DRIVER}}};"
        f"SERVER={source.host},{source.port};"
        f"DATABASE={source.service_or_database};"
        f"UID={source.user};"
        f"PWD={source.password};"
        "TrustServerCertificate=yes;"
    )

    conn = pyodbc.connect(conn_str)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COLUMN_NAME, DATA_TYPE "
            "FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? "
            "ORDER BY ORDINAL_POSITION",
            schema,
            table,
        )
        all_columns = cursor.fetchall()
        cursor.close()
    finally:
        conn.close()

    xml_cols = []
    select_parts = []
    for col_name, data_type in all_columns:
        if data_type.lower() in _UNSUPPORTED_TYPES:
            select_parts.append(f"CAST([{col_name}] AS NVARCHAR(MAX)) AS [{col_name}]")
            xml_cols.append(col_name)
        else:
            select_parts.append(f"[{col_name}]")

    query = f"SELECT {', '.join(select_parts)} FROM [{schema}].[{table}]"
    if where_clause:
        query += f" {where_clause}"

    return query, xml_cols


# ---------------------------------------------------------------------------
# Arrow -> Polars conversion
# ---------------------------------------------------------------------------

def _fetch_as_polars(conn, query: str, context: str) -> pl.DataFrame:
    """Execute query via turbodbc and return a Polars DataFrame.

    Uses turbodbc's fetchallarrow() for columnar Arrow output, then
    zero-copy converts to Polars via pl.from_arrow(). This avoids the
    Python-object materialization that makes pyodbc slow for bulk reads.
    """
    cursor = conn.cursor()
    try:
        logger.debug("turbodbc executing: %s", query[:200])
        cursor.execute(query)

        # fetchallarrow() returns a pyarrow.Table in one call.
        # For very large result sets (>10M rows), fetchnumpybatches()
        # would allow streaming, but Arrow tables are the Polars-native path.
        arrow_table = cursor.fetchallarrow()

        # Zero-copy conversion: Polars wraps the Arrow buffers directly.
        df = pl.from_arrow(arrow_table)

        logger.info(
            "turbodbc fetched %d rows, %d columns (%s)",
            len(df), len(df.columns), context,
        )
        return df

    except Exception:
        logger.error("turbodbc fetch failed for %s", context, exc_info=True)
        raise
    finally:
        cursor.close()


# ---------------------------------------------------------------------------
# Public extraction functions (matching ConnectorX extractor signatures)
# ---------------------------------------------------------------------------

def extract_sqlserver_turbodbc(
    table_config: TableConfig,
    output_dir: str | Path,
) -> tuple[pl.DataFrame, Path]:
    """Extract from SQL Server via turbodbc into a Polars DataFrame and write BCP CSV.

    Full table scan mode for small tables. XML columns are auto-CAST to
    NVARCHAR(MAX). Signature matches extract_sqlserver_connectorx() for
    drop-in routing from router.py.

    Args:
        table_config: Table configuration with source details.
        output_dir: Directory for output CSV file.

    Returns:
        Tuple of (prepared DataFrame, CSV file path).
    """
    schema = table_config.source_schema_name
    table = table_config.source_object_name

    query, xml_cols = _build_safe_select(
        source_name=table_config.source_name,
        schema=schema,
        table=table,
    )

    if xml_cols:
        logger.info(
            "turbodbc extract %s.%s — CAST applied to XML columns: %s",
            schema, table, xml_cols,
        )
    else:
        logger.info("turbodbc extract %s.%s — no XML columns detected", schema, table)

    conn = _get_turbodbc_connection(table_config.source_name)
    try:
        df = _fetch_as_polars(
            conn, query,
            context=f"turbodbc full extract {table_config.source_name}.{table}",
        )
    finally:
        conn.close()

    logger.info(
        "Extracted %d rows, %d columns from %s",
        len(df), len(df.columns), table_config.source_full_table_name,
    )

    # P3-5: Warn about large full-scan extractions
    if len(df) > 5_000_000:
        logger.warning(
            "P3-5: turbodbc full-scan returned %d rows from %s. "
            "Consider date-windowed extraction for better performance.",
            len(df), table_config.source_full_table_name,
        )

    if len(df) == 0:
        csv_path = Path(output_dir) / f"{table_config.source_name}_{table}.csv"
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
        Path(output_dir) / f"{table_config.source_name}_{table}.csv",
    )

    return df, csv_path


def extract_sqlserver_turbodbc_windowed(
    table_config: TableConfig,
    output_dir: str | Path,
    start_date: date,
    end_date: date,
) -> tuple[pl.DataFrame, Path]:
    """Extract a date window from SQL Server via turbodbc.

    For large tables. Uses SourceAggregateColumnName for the WHERE clause.
    XML columns are auto-CAST to NVARCHAR(MAX). Signature matches
    extract_sqlserver_connectorx_windowed() (minus partition_on/partition_num
    which turbodbc does not support — single-connection only).

    Args:
        table_config: Table configuration with source details.
        output_dir: Directory for output CSV file.
        start_date: Start of date range (inclusive).
        end_date: End of date range (exclusive).

    Returns:
        Tuple of (prepared DataFrame, CSV file path).
    """
    date_col = table_config.source_aggregate_column_name
    schema = table_config.source_schema_name
    table = table_config.source_object_name

    where_clause = (
        f"WHERE [{date_col}] >= '{start_date}' AND [{date_col}] < '{end_date}'"
    )

    query, xml_cols = _build_safe_select(
        source_name=table_config.source_name,
        schema=schema,
        table=table,
        where_clause=where_clause,
    )

    if xml_cols:
        logger.info(
            "turbodbc windowed %s [%s, %s) — CAST applied to XML columns: %s",
            table, start_date, end_date, xml_cols,
        )
    else:
        logger.info(
            "turbodbc windowed %s [%s, %s) — no XML columns",
            table, start_date, end_date,
        )

    conn = _get_turbodbc_connection(table_config.source_name)
    try:
        df = _fetch_as_polars(
            conn, query,
            context=f"turbodbc windowed {table} [{start_date}, {end_date})",
        )
    finally:
        conn.close()

    logger.info(
        "Extracted %d rows from %s.%s for [%s, %s)",
        len(df), schema, table, start_date, end_date,
    )

    if len(df) == 0:
        csv_path = Path(output_dir) / f"{table_config.source_name}_{table}_{start_date}.csv"
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
        Path(output_dir) / f"{table_config.source_name}_{table}_{start_date}.csv",
    )

    return df, csv_path


# ---------------------------------------------------------------------------
# Utility: check if a table has XML columns (used by router.py)
# ---------------------------------------------------------------------------

def table_has_xml_columns(source_name: str, schema: str, table: str) -> bool:
    """Check if a source table contains XML (or other unsupported) columns.

    Called by router.py to decide between ConnectorX (fast, no XML) and
    turbodbc (Arrow-fast, XML-safe) extraction paths.
    """
    xml_cols = _detect_xml_columns(source_name, schema, table)
    return len(xml_cols) > 0