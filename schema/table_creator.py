"""Auto-create Stage (CDC) and Bronze (SCD2) tables from DataFrame dtypes.

Creates tables if they don't exist, with the correct schema for CDC and SCD2 columns.

W-10 NOTE — Ordered clustered columnstore indexes (SQL Server 2022):
  For billion-row Bronze tables (100M+), SQL Server 2022 ordered clustered
  columnstore indexes (ORDER on BusinessKey, EffectiveDateTime) enable segment
  elimination for point-in-time queries without sacrificing columnstore
  compression benefits. ensure_bronze_columnstore_index() provides this as
  an opt-in migration for specific large tables. Since columnstore replaces
  the clustered B-tree (IDENTITY PK), the PK must be recreated as nonclustered.
  Benchmark query performance before and after on production data.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import polars as pl

from utils.connections import quote_identifier, quote_table, get_connection
from extract.udm_connectorx_extractor import table_exists
from data_load.schema_utils import get_column_metadata

if TYPE_CHECKING:
    from orchestration.table_config import TableConfig

logger = logging.getLogger(__name__)

# Polars dtype -> SQL Server type mapping
_DTYPE_MAP: dict[type, str] = {
    pl.Int8: "TINYINT",
    pl.Int16: "SMALLINT",
    pl.Int32: "INT",
    pl.Int64: "BIGINT",
    pl.UInt8: "TINYINT",
    pl.UInt16: "SMALLINT",
    pl.UInt32: "INT",
    pl.UInt64: "BIGINT",
    pl.Float32: "FLOAT",
    pl.Float64: "FLOAT",
    pl.Boolean: "BIT",
    pl.Utf8: "NVARCHAR(MAX)",
    pl.String: "NVARCHAR(MAX)",
    pl.Date: "DATE",
    pl.Datetime: "DATETIME2",
    pl.Time: "TIME",
    pl.Duration: "BIGINT",
}

# The default NVARCHAR length for PK columns. SQL Server index key max = 900 bytes.
# NVARCHAR uses 2 bytes/char, so 450 is the theoretical max. Using 255 is safer
# and covers virtually all Oracle VARCHAR2 PKs (Oracle max is typically 4000 bytes).
_PK_NVARCHAR_LENGTH = 255


def _polars_dtype_to_sql(dtype: pl.DataType, is_pk: bool = False) -> str:
    """Map a Polars dtype to SQL Server column type.

    E-7b: Handles pl.Decimal (returned by pyodbc fallback) by mapping to
    DECIMAL(p,s) with the precision and scale from the Polars type. This
    prevents the pyodbc fallback from producing NVARCHAR(MAX) for numeric
    columns, which would cause false SchemaEvolutionError on the next run.

    ConnectorX maps SQL Server DECIMAL/NUMERIC/MONEY to Float64, while
    pyodbc preserves the exact Decimal type. Both must map to compatible
    SQL Server types — FLOAT and DECIMAL(p,s) are both numeric.

    Args:
        dtype: Polars data type.
        is_pk: If True and dtype is string, use bounded NVARCHAR instead of MAX.
    """
    # Handle string types with PK awareness
    if isinstance(dtype, (pl.Utf8, pl.String)):
        if is_pk:
            return f"NVARCHAR({_PK_NVARCHAR_LENGTH})"
        return "NVARCHAR(MAX)"

    # E-7b: Handle Decimal — pyodbc returns Decimal(precision, scale) for
    # SQL Server DECIMAL, NUMERIC, MONEY, and SMALLMONEY columns.
    # Map to DECIMAL(p,s) to preserve exact numeric semantics.
    if isinstance(dtype, pl.Decimal):
        precision = dtype.precision if dtype.precision is not None else 38
        scale = dtype.scale if dtype.scale is not None else 0
        return f"DECIMAL({precision},{scale})"

    for pl_type, sql_type in _DTYPE_MAP.items():
        if isinstance(dtype, pl_type):
            return sql_type
    if hasattr(dtype, "base_type"):
        base = type(dtype)
        if base in _DTYPE_MAP:
            return _DTYPE_MAP[base]
    return "NVARCHAR(MAX)"

def _build_source_columns_ddl(
    df: pl.DataFrame,
    exclude_cols: set[str] | None = None,
    pk_columns: list[str] | None = None,
) -> list[str]:
    """Build DDL column definitions from DataFrame, excluding internal columns.
    
    Args:
        df: Source DataFrame.
        exclude_cols: Columns to skip.
        pk_columns: Primary key columns — string PKs get NVARCHAR(255) 
                     instead of NVARCHAR(MAX) to allow SQL Server indexing.
    """
    if exclude_cols is None:
        exclude_cols = set()
    if pk_columns is None:
        pk_columns = []
    
    pk_set = set(pk_columns)
    cols = []
    for col_name, dtype in zip(df.columns, df.dtypes):
        if col_name.startswith("_") or col_name in exclude_cols:
            continue
        is_pk = col_name in pk_set
        sql_type = _polars_dtype_to_sql(dtype, is_pk=is_pk)
        cols.append(f"    [{col_name}] {sql_type} NULL")
    return cols


def ensure_stage_table(table_config: TableConfig, df: pl.DataFrame) -> bool:
    """Create Stage (CDC) table if it doesn't exist.

    Schema:
        - All source columns (from df, excluding _ prefixed)
        - _row_hash VARCHAR(64) (B-1: full SHA-256 hex string)
        - _extracted_at DATETIME2
        - _cdc_operation NVARCHAR(1)  (I/U/D)
        - _cdc_valid_from DATETIME2
        - _cdc_valid_to DATETIME2 NULL
        - _cdc_is_current BIT
        - _cdc_batch_id BIGINT
        - UdmModifiedBy NVARCHAR(128)

    Returns:
        True if the table was created, False if it already existed.
    """
    full_name = table_config.stage_full_table_name

    if table_exists(full_name):
        logger.info("Stage table %s already exists", full_name)
        return False

    source_cols = _build_source_columns_ddl(df)

    cdc_cols = [
        "    [_row_hash] VARCHAR(64) NULL",
        "    [_extracted_at] DATETIME2 NULL",
        "    [_cdc_operation] NVARCHAR(1) NULL",
        "    [_cdc_valid_from] DATETIME2 NULL",
        "    [_cdc_valid_to] DATETIME2 NULL",
        "    [_cdc_is_current] BIT NULL",
        "    [_cdc_batch_id] BIGINT NULL",
        "    [UdmModifiedBy] NVARCHAR(128) NULL DEFAULT SYSTEM_USER",
    ]

    all_cols = source_cols + cdc_cols
    col_ddl = ",\n".join(all_cols)

    parts = full_name.split(".")
    db, schema, table = parts[0], parts[1], parts[2]
    q_db = quote_identifier(db)
    q_schema = quote_identifier(schema)
    q_full = quote_table(full_name)

    conn = get_connection(db)
    try:
        cursor = conn.cursor()
        # Check if table already exists (parameterized)
        cursor.execute(
            f"SELECT 1 FROM {q_db}.INFORMATION_SCHEMA.TABLES "
            f"WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?",
            schema, table,
        )
        if cursor.fetchone():
            cursor.close()
            conn.close()
            logger.info("Created Stage table: %s (already existed)", full_name)
            return True

        # Ensure schema exists
        cursor.execute(
            f"SELECT 1 FROM {q_db}.sys.schemas WHERE name = ?", schema,
        )
        if not cursor.fetchone():
            cursor.execute(f"EXEC({q_db}..sp_executesql N'CREATE SCHEMA {q_schema}')")

        # Create table
        cursor.execute(f"CREATE TABLE {q_full} (\n{col_ddl}\n)")
        cursor.close()
        logger.info("Created Stage table: %s", full_name)
    finally:
        conn.close()

    return True


def ensure_bronze_table(table_config: TableConfig, df: pl.DataFrame) -> bool:
    """Create Bronze (SCD2) table if it doesn't exist.

    Schema:
        - _scd2_key BIGINT IDENTITY(1,1) PRIMARY KEY
        - All source columns (from df, excluding _ prefixed)
        - UdmHash VARCHAR(64) (B-1: full SHA-256 hex string)
        - UdmEffectiveDateTime DATETIME2   (load timestamp into UDM — Silver/Gold contract)
        - UdmEndDateTime DATETIME2 NULL    (load-time close; NULL while active)
        - UdmSourceBeginDate DATETIME2(3)  (R-1: source business begin date)
        - UdmSourceEndDate DATETIME2(3)    (R-3: source business chain end; '2999-12-31' sentinel when active)
        - UdmActiveFlag TINYINT            (1 current, 2 deleted at source, 0 historic)
        - UdmScd2Operation NVARCHAR(10)

    Returns:
        True if the table was created, False if it already existed.
    """
    full_name = table_config.bronze_full_table_name

    if table_exists(full_name):
        logger.info("Bronze table %s already exists", full_name)
        return False
    
    # Pass PK columns so string PKs get bounded NVARCHAR
    pk_columns = table_config.pk_columns if hasattr(table_config, 'pk_columns') else []
    source_cols = _build_source_columns_ddl(df, pk_columns=pk_columns)

    # SCD-2: BIGINT IDENTITY — max 9.2 quintillion. At 3M inserts/day,
    # lasts 8.4 trillion years. INT would overflow in ~716 days.
    identity_col = "    [_scd2_key] BIGINT IDENTITY(1,1) PRIMARY KEY"

    scd2_cols = [
        "    [UdmHash] VARCHAR(64) NULL",
        # UdmEffectiveDateTime / UdmEndDateTime: load-time pair consumed by
        # Silver/Gold. UdmEffectiveDateTime = arrival timestamp in UDM.
        # UdmEndDateTime = NULL while active, load timestamp at close.
        "    [UdmEffectiveDateTime] DATETIME2 NULL",
        "    [UdmEndDateTime] DATETIME2 NULL",
        # R-1/R-3 source-date pair: separate chain driven by the source
        # business date. UdmSourceEndDate = '2999-12-31' sentinel while active,
        # NULL while in-flight (Flag=0, operation U/R, pending activation).
        "    [UdmSourceBeginDate] DATETIME2(3) NULL",
        "    [UdmSourceEndDate] DATETIME2(3) NULL",
        # R-4 legacy alignment: TINYINT (not BIT) so the column can hold 2 for
        # delete-close ("deleted at source") alongside 1 (active) and 0 (historical
        # update-close). BIT would silently coerce SET = 2 to 1 under SQL Server's
        # implicit conversion rules.
        "    [UdmActiveFlag] TINYINT NULL",
        "    [UdmScd2Operation] NVARCHAR(10) NULL",
        "    [UdmModifiedBy] NVARCHAR(128) NULL DEFAULT SYSTEM_USER",
    ]

    all_cols = [identity_col] + source_cols + scd2_cols
    col_ddl = ",\n".join(all_cols)

    parts = full_name.split(".")
    db, schema, table = parts[0], parts[1], parts[2]
    q_db = quote_identifier(db)
    q_schema = quote_identifier(schema)
    q_full = quote_table(full_name)

    conn = get_connection(db)
    try:
        cursor = conn.cursor()
        # Check if table already exists (parameterized)
        cursor.execute(
            f"SELECT 1 FROM {q_db}.INFORMATION_SCHEMA.TABLES "
            f"WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?",
            schema, table,
        )
        if cursor.fetchone():
            cursor.close()
            conn.close()
            logger.info("Created Bronze table: %s (already existed)", full_name)
            return True

        # Ensure schema exists
        cursor.execute(
            f"SELECT 1 FROM {q_db}.sys.schemas WHERE name = ?", schema,
        )
        if not cursor.fetchone():
            cursor.execute(f"EXEC({q_db}..sp_executesql N'CREATE SCHEMA {q_schema}')")

        # Create table
        cursor.execute(f"CREATE TABLE {q_full} (\n{col_ddl}\n)")
        cursor.close()
        logger.info("Created Bronze table: %s", full_name)
    finally:
        conn.close()

    return True


def _narrow_max_pk_columns(
    table_config: TableConfig,
    pk_columns: list[str],
) -> bool:
    """SCD-1b: Narrow NVARCHAR(MAX) PK columns in Bronze to source-accurate widths.

    SQL Server cannot include MAX-length columns in index keys (error 1919).
    Tables created before PK-aware DDL (or before PKs were discovered) may
    have string PK columns stored as NVARCHAR(MAX). This function detects
    those columns, queries the source system for the actual CHARACTER_MAXIMUM_LENGTH,
    and ALTERs them to bounded NVARCHAR(n) so index creation can proceed.

    Uses actual source widths instead of the blanket _PK_NVARCHAR_LENGTH (255)
    to stay within the 900-byte nonclustered index key limit. For example,
    three PK columns at NVARCHAR(255) = 1,530 bytes (over the limit), but
    at their actual widths (e.g. 8+10+200 chars = 436 bytes) they fit.

    Only applies to SQL Server sources. Oracle sources are skipped (return False).

    Args:
        table_config: Table configuration (must have source connection info).
        pk_columns: Primary key columns to check.

    Returns:
        True if any columns were altered, False otherwise.
    """
    full_name = table_config.bronze_full_table_name

    # Identify PK columns currently stored as NVARCHAR(MAX) or VARCHAR(MAX)
    bronze_meta = get_column_metadata(full_name)
    bronze_meta_map = {m.column_name: m for m in bronze_meta}

    max_columns = []
    for col in pk_columns:
        meta = bronze_meta_map.get(col)
        if meta is None:
            continue
        if meta.data_type.upper() in ("NVARCHAR", "VARCHAR") and meta.character_maximum_length == -1:
            max_columns.append(col)

    if not max_columns:
        return False

    # Only SQL Server sources — Oracle doesn't hit this issue
    if not table_config.is_sql_server:
        logger.warning(
            "SCD-1b: PK columns %s in %s are NVARCHAR(MAX) but source is not "
            "SQL Server — skipping automatic narrowing. Create indexes manually.",
            max_columns, full_name,
        )
        return False

    # Query the source system for actual column widths
    from utils.sources import get_source_for_table

    source = get_source_for_table(table_config)
    try:
        import pyodbc as _pyodbc
        src_conn = _pyodbc.connect(source.pyodbc_connection_string(), autocommit=True)
    except Exception:
        logger.warning(
            "SCD-1b: Could not connect to source %s to look up PK column widths "
            "for %s — skipping narrowing",
            table_config.source_name, full_name, exc_info=True,
        )
        return False

    try:
        cursor = src_conn.cursor()
        placeholders = ", ".join("?" for _ in max_columns)
        cursor.execute(
            f"SELECT COLUMN_NAME, CHARACTER_MAXIMUM_LENGTH "
            f"FROM [{table_config.source_database}].INFORMATION_SCHEMA.COLUMNS "
            f"WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? "
            f"AND COLUMN_NAME IN ({placeholders})",
            table_config.source_schema_name,
            table_config.source_object_name,
            *max_columns,
        )
        source_widths = {row[0]: row[1] for row in cursor.fetchall()}
        cursor.close()
    except Exception:
        logger.warning(
            "SCD-1b: Could not query source INFORMATION_SCHEMA for PK column "
            "widths on %s.%s — skipping narrowing",
            table_config.source_name, table_config.source_object_name,
            exc_info=True,
        )
        return False
    finally:
        src_conn.close()

    # ALTER each MAX column to its actual source width
    parts = full_name.split(".")
    db = parts[0]
    q_full = quote_table(full_name)

    altered = []
    conn = get_connection(db)
    try:
        cursor = conn.cursor()
        for col in max_columns:
            src_width = source_widths.get(col)
            if src_width is None or src_width == -1:
                # Source column is also MAX or not found — fall back to default
                src_width = _PK_NVARCHAR_LENGTH
                logger.warning(
                    "SCD-1b: Source column [%s] width not found or is MAX — "
                    "falling back to NVARCHAR(%d)",
                    col, _PK_NVARCHAR_LENGTH,
                )

            src_type = bronze_meta_map[col].data_type.upper()  # preserve NVARCHAR vs VARCHAR
            new_type = f"{src_type}({src_width})"
            q_col = quote_identifier(col)

            try:
                cursor.execute(f"ALTER TABLE {q_full} ALTER COLUMN {q_col} {new_type} NULL")
                altered.append((col, new_type))
                logger.info(
                    "SCD-1b: Narrowed %s.%s from %s(MAX) to %s for index compatibility",
                    full_name, col, src_type, new_type,
                )
            except Exception:
                logger.warning(
                    "SCD-1b: Failed to ALTER COLUMN %s on %s to %s — "
                    "index creation may fail",
                    col, full_name, new_type, exc_info=True,
                )
        cursor.close()
    finally:
        conn.close()

    if altered:
        # M-5: Invalidate cached metadata so subsequent calls see the new types
        from data_load.schema_utils import clear_column_metadata_cache
        clear_column_metadata_cache()

    return len(altered) > 0


def ensure_bronze_unique_active_index(
    table_config: TableConfig,
    pk_columns: list[str],
) -> bool:
    """SCD-1: Create unique filtered index on Bronze to prevent duplicate active rows.

    The INSERT-first SCD2 design (P0-8) can leave duplicate active rows on retry
    (crash after INSERT but before UPDATE). This index prevents the second INSERT
    from succeeding — the retry gets a constraint violation (detectable, recoverable)
    instead of silently creating duplicate active records.

    Index: CREATE UNIQUE NONCLUSTERED INDEX UX_Active_<table>
           ON Bronze(pk1, pk2, ...) WHERE UdmActiveFlag = 1

    Args:
        table_config: Table configuration (Bronze table must already exist).
        pk_columns: Primary key columns for the uniqueness constraint.

    Returns:
        True if the index was created, False if it already existed or no PKs.
    """
    if not pk_columns:
        logger.debug("SCD-1: No PK columns for %s — skipping unique active index",
                      table_config.source_object_name)
        return False

    full_name = table_config.bronze_full_table_name
    if not table_exists(full_name):
        return False

    # SCD-1b: Narrow any NVARCHAR(MAX) PK columns to source-accurate widths
    # so they can participate in the index key (SQL Server error 1919).
    _narrow_max_pk_columns(table_config, pk_columns)

    parts = full_name.split(".")
    db, schema, table = parts[0], parts[1], parts[2]

    index_name = f"UX_Active_{table_config.source_object_name}"
    pk_col_list = ", ".join(quote_identifier(c) for c in pk_columns)

    conn = get_connection(db)
    try:
        cursor = conn.cursor()
        # Check if index already exists
        cursor.execute(
            "SELECT COUNT(*) FROM sys.indexes "
            "WHERE object_id = OBJECT_ID(?) AND name = ?",
            full_name, index_name,
        )
        exists = cursor.fetchone()[0] > 0

        if exists:
            logger.debug("SCD-1: Unique active index %s already exists on %s",
                         index_name, full_name)
            cursor.close()
            return False

        # Create unique filtered index
        q_full = quote_table(full_name)
        ddl = (
            f"CREATE UNIQUE NONCLUSTERED INDEX {quote_identifier(index_name)} "
            f"ON {q_full} ({pk_col_list}) "
            f"WHERE [UdmActiveFlag] = 1"
        )
        cursor.execute(ddl)
        cursor.close()
        logger.info("SCD-1: Created unique active index %s on %s (%s)",
                     index_name, full_name, pk_col_list)
        return True
    except Exception:
        logger.warning(
            "SCD-1: Failed to create unique active index on %s — "
            "duplicate active row prevention unavailable",
            full_name, exc_info=True,
        )
        return False
    finally:
        conn.close()


def ensure_bronze_point_in_time_index(
    table_config: TableConfig,
    pk_columns: list[str],
) -> bool:
    """V-9: Create point-in-time lookup index on Bronze table.

    Index: CREATE NONCLUSTERED INDEX IX_PIT_<table>
           ON Bronze(pk1, pk2, ..., UdmEffectiveDateTime DESC)

    Supports historical queries like "what was the value of this record on date X"
    without full table scans. At 3B+ rows, this is critical for query performance.

    Args:
        table_config: Table configuration (Bronze table must already exist).
        pk_columns: Primary key columns for the index prefix.

    Returns:
        True if the index was created, False if it already existed or no PKs.
    """
    if not pk_columns:
        return False

    full_name = table_config.bronze_full_table_name
    if not table_exists(full_name):
        return False

    # SCD-1b: Narrow any NVARCHAR(MAX) PK columns to source-accurate widths.
    # Idempotent — skips columns already narrowed by ensure_bronze_unique_active_index.
    _narrow_max_pk_columns(table_config, pk_columns)

    parts = full_name.split(".")
    db = parts[0]

    index_name = f"IX_PIT_{table_config.source_object_name}"
    pk_col_list = ", ".join(quote_identifier(c) for c in pk_columns)

    conn = get_connection(db)
    try:
        cursor = conn.cursor()
        # Check if index already exists
        cursor.execute(
            "SELECT COUNT(*) FROM sys.indexes "
            "WHERE object_id = OBJECT_ID(?) AND name = ?",
            full_name, index_name,
        )
        exists = cursor.fetchone()[0] > 0

        if exists:
            logger.debug("V-9: Point-in-time index %s already exists on %s",
                         index_name, full_name)
            cursor.close()
            return False

        q_full = quote_table(full_name)
        ddl = (
            f"CREATE NONCLUSTERED INDEX {quote_identifier(index_name)} "
            f"ON {q_full} ({pk_col_list}, [UdmEffectiveDateTime] DESC)"
        )
        cursor.execute(ddl)
        cursor.close()
        logger.info("V-9: Created point-in-time index %s on %s (%s, UdmEffectiveDateTime DESC)",
                     index_name, full_name, pk_col_list)
        return True
    except Exception:
        logger.warning(
            "V-9: Failed to create point-in-time index on %s — "
            "historical lookups will use full scans",
            full_name, exc_info=True,
        )
        return False
    finally:
        conn.close()


# W-10: Minimum row count threshold for columnstore index migration.
_COLUMNSTORE_ROW_THRESHOLD = 100_000_000


def ensure_bronze_columnstore_index(
    table_config: TableConfig,
    pk_columns: list[str],
    row_count: int | None = None,
    min_rows: int = _COLUMNSTORE_ROW_THRESHOLD,
) -> bool:
    """W-10: Create ordered clustered columnstore index on large Bronze tables.

    SQL Server 2022 ordered clustered columnstore indexes enable segment
    elimination for point-in-time queries while providing columnstore
    compression for billion-row tables.

    WARNING: This is a DESTRUCTIVE schema migration. The existing clustered
    PK index (_scd2_key) is dropped and recreated as nonclustered to make
    room for the clustered columnstore index. Run during a maintenance window.

    Prerequisites:
      - SQL Server 2022 or later
      - Bronze table must already exist
      - Table should have > min_rows to justify the overhead

    Args:
        table_config: Table configuration (Bronze table must exist).
        pk_columns: PK columns for the ORDER clause.
        row_count: Known row count (avoids extra query). If None, queries it.
        min_rows: Skip below this threshold (default 100M).

    Returns:
        True if the columnstore index was created, False otherwise.
    """
    if not pk_columns:
        logger.debug("W-10: No PK columns for %s — skipping columnstore index",
                      table_config.source_object_name)
        return False

    full_name = table_config.bronze_full_table_name
    if not table_exists(full_name):
        return False

    parts = full_name.split(".")
    db = parts[0]

    # Check row count threshold
    if row_count is None:
        from extract.udm_connectorx_extractor import get_table_row_count
        row_count = get_table_row_count(full_name)

    if row_count < min_rows:
        logger.debug(
            "W-10: %s has %d rows (threshold=%d) — skipping columnstore index",
            full_name, row_count, min_rows,
        )
        return False

    cci_name = f"CCI_{table_config.source_object_name}"
    order_cols = ", ".join(quote_identifier(c) for c in pk_columns) + ", [UdmEffectiveDateTime]"

    conn = get_connection(db)
    try:
        cursor = conn.cursor()

        # Check if columnstore index already exists
        cursor.execute(
            "SELECT COUNT(*) FROM sys.indexes "
            "WHERE object_id = OBJECT_ID(?) AND type_desc = 'CLUSTERED COLUMNSTORE'",
            full_name,
        )
        has_cci = cursor.fetchone()[0] > 0
        if has_cci:
            logger.debug("W-10: Clustered columnstore index already exists on %s", full_name)
            cursor.close()
            return False

        # Verify SQL Server 2022+
        cursor.execute("SELECT SERVERPROPERTY('ProductMajorVersion')")
        version_row = cursor.fetchone()
        major_version = int(version_row[0]) if version_row and version_row[0] else 0
        if major_version < 16:
            logger.warning(
                "W-10: SQL Server version %d does not support ordered columnstore indexes "
                "(requires SQL Server 2022 / version 16+). Skipping %s.",
                major_version, full_name,
            )
            cursor.close()
            return False

        q_full = quote_table(full_name)

        # Step 1: Drop existing clustered PK and recreate as nonclustered
        # Find the current PK constraint name
        cursor.execute(
            "SELECT name FROM sys.key_constraints "
            "WHERE parent_object_id = OBJECT_ID(?) AND type = 'PK'",
            full_name,
        )
        pk_row = cursor.fetchone()
        if pk_row:
            pk_name = pk_row[0]
            logger.info(
                "W-10: Dropping clustered PK [%s] on %s to make room for columnstore",
                pk_name, full_name,
            )
            cursor.execute(f"ALTER TABLE {q_full} DROP CONSTRAINT {quote_identifier(pk_name)}")
            # Recreate PK as nonclustered
            cursor.execute(
                f"ALTER TABLE {q_full} ADD CONSTRAINT {quote_identifier(pk_name)} "
                f"PRIMARY KEY NONCLUSTERED ([_scd2_key])"
            )
            logger.info("W-10: Recreated PK [%s] as NONCLUSTERED on %s", pk_name, full_name)

        # Step 2: Create ordered clustered columnstore index
        ddl = (
            f"CREATE CLUSTERED COLUMNSTORE INDEX {quote_identifier(cci_name)} "
            f"ON {q_full} ORDER ({order_cols})"
        )
        cursor.execute(ddl)
        cursor.close()

        logger.info(
            "W-10: Created ordered clustered columnstore index [%s] on %s "
            "ORDER (%s) — %d rows",
            cci_name, full_name, order_cols, row_count,
        )
        return True

    except Exception:
        logger.warning(
            "W-10: Failed to create columnstore index on %s — "
            "continuing with existing B-tree indexes",
            full_name, exc_info=True,
        )
        return False
    finally:
        conn.close()