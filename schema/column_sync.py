"""Auto-populate UdmTablesColumnsList for new tables.

Syncs column metadata from INFORMATION_SCHEMA on newly created Stage/Bronze tables,
then discovers primary keys from the source system (Oracle or SQL Server).

Runs once per table — skips entirely if UdmTablesColumnsList already has rows for
the given SourceName + TableName combination.

Oracle views without discoverable PKs log a warning; IsPrimaryKey must be set manually.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pyodbc

import utils.configuration as config
from utils.connections import get_general_connection, get_connection
from utils.sources import SourceType, get_source_for_table

if TYPE_CHECKING:
    from orchestration.table_config import ColumnConfig, TableConfig

logger = logging.getLogger(__name__)


# Oracle connections use thin mode (default). Oracle Instant Client is not
# installed in the runtime environment, so any call to
# oracledb.init_oracle_client() raises DPI-1047. oracledb.connect() works
# directly against the listener without thick-mode initialization.


def sync_columns(table_config: TableConfig,
                 refresh_pks: bool = False,
                 file_pk_columns: list[str] | None = None) -> bool:
    """Sync column metadata into UdmTablesColumnsList for a new table.

    1. Check if rows already exist — skip if so (idempotent).
    2. Read INFORMATION_SCHEMA.COLUMNS from the Stage and Bronze tables.
    3. Insert rows into UdmTablesColumnsList for both layers.
    4. Discover PKs from the source system (or use file_pk_columns if provided).
    5. UPDATE IsPrimaryKey for discovered PKs.
    6. Reload columns into table_config so CDC/SCD2 work on the first run.

    Args:
        table_config: Table configuration (tables must already exist in UDM).
        refresh_pks: P1-10 — If True, re-discover PKs even if columns already exist.
        file_pk_columns: Explicit PK column names for file-based sources.
            When provided, skips _discover_pks() (files have no source database
            to query) and uses these columns directly.

    Returns:
        True if columns were synced (new table), False if already populated.
    """
    table_name = table_config.effective_stage_name
    source_name = table_config.source_name

    if _columns_exist(source_name, table_name):
        if refresh_pks:
            # P1-10: Re-discover PKs from source and update UdmTablesColumnsList
            logger.info(
                "P1-10: Refreshing PKs for %s.%s (--refresh-pks)",
                source_name, table_name,
            )
            _refresh_pk_flags(table_config, source_name, table_name)
            _reload_columns_into_config(table_config)
            return False

        logger.debug(
            "UdmTablesColumnsList already populated for %s.%s — skipping sync",
            source_name, table_name,
        )
        return False

    logger.info(
        "Syncing columns for %s.%s into UdmTablesColumnsList",
        source_name, table_name,
    )

    # Step 1: Insert column metadata from INFORMATION_SCHEMA
    stage_count = _insert_columns_from_info_schema(
        table_config, table_name, source_name, layer="Stage",
    )
    bronze_count = _insert_columns_from_info_schema(
        table_config, table_name, source_name, layer="Bronze",
    )
    logger.info(
        "Inserted %d Stage columns and %d Bronze columns for %s.%s",
        stage_count, bronze_count, source_name, table_name,
    )

    # Step 2: Discover PKs — use explicit file PKs or discover from source
    if file_pk_columns:
        # File-based sources: PKs are declared in FileExtract.PrimaryKeyColumns
        pk_columns = file_pk_columns
        logger.info(
            "Using explicit file PK columns for %s.%s: %s",
            source_name, table_name, pk_columns,
        )
    else:
        # Step 2: Discover PKs from source system
        pk_columns = _discover_pks(table_config)

    if pk_columns:
        _update_pk_flags(source_name, table_name, pk_columns)
        logger.info(
            "Discovered and set PKs for %s.%s: %s",
            source_name, table_name, pk_columns,
        )
    else:
        logger.warning(
            "No PKs discovered for %s.%s — IsPrimaryKey must be set manually "
            "in General.dbo.UdmTablesColumnsList before CDC/SCD2 will run",
            source_name, table_name,
        )

    # Step 3: Reload columns into in-memory table_config for this run
    _reload_columns_into_config(table_config)

    return True


# ---------------------------------------------------------------------------
# Check if columns already exist
# ---------------------------------------------------------------------------

def _columns_exist(source_name: str, table_name: str) -> bool:
    """Check if UdmTablesColumnsList already has rows for this source + table."""
    conn = get_general_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM dbo.UdmTablesColumnsList "
            "WHERE SourceName = ? AND TableName = ?",
            source_name, table_name,
        )
        count = cursor.fetchone()[0]
        cursor.close()
        return count > 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Insert column metadata from INFORMATION_SCHEMA
# ---------------------------------------------------------------------------

def _discover_source_object_type(table_config: TableConfig) -> str | None:
    """Return ``'TABLE'`` / ``'VIEW'`` (or whatever the source labels it) for
    the source object, or None when the lookup fails.

    Helps populate ``UdmTablesColumnsList.ObjectType`` so operators can
    quickly distinguish view-backed entries from table-backed ones (views
    need ``UdmTablesList.PrimaryKeyColumns`` populated; tables typically
    auto-discover).

    Non-blocking — any error returns None and the column is left NULL.
    """
    try:
        source = get_source_for_table(table_config)
        schema = table_config.source_schema_name
        table = table_config.source_object_name

        if source.source_type == SourceType.ORACLE:
            import oracledb
            params = source.oracledb_connect_params()
            with oracledb.connect(**params) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(
                        "SELECT object_type FROM ALL_OBJECTS "
                        "WHERE owner = :owner AND object_name = :name "
                        "AND object_type IN ('TABLE', 'VIEW') "
                        "ORDER BY CASE object_type WHEN 'TABLE' THEN 0 ELSE 1 END "
                        "FETCH FIRST 1 ROWS ONLY",
                        owner=schema.upper(), name=table.upper(),
                    )
                    row = cursor.fetchone()
                    return row[0] if row else None
        else:
            import pyodbc
            with pyodbc.connect(source.pyodbc_connection_string(), autocommit=True) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT type_desc FROM sys.objects "
                    "WHERE object_id = OBJECT_ID(? + '.' + ?)",
                    schema, table,
                )
                row = cursor.fetchone()
                if not row:
                    return None
                # type_desc values: USER_TABLE, VIEW. Normalize to TABLE / VIEW
                # for human readability.
                td = row[0]
                if td == "USER_TABLE":
                    return "TABLE"
                if td == "VIEW":
                    return "VIEW"
                return td
    except Exception:
        logger.debug(
            "ObjectType lookup failed for %s.%s — leaving column NULL",
            table_config.source_name, table_config.source_object_name,
            exc_info=True,
        )
        return None


def _insert_columns_from_info_schema(
    table_config: TableConfig,
    table_name: str,
    source_name: str,
    layer: str,
) -> int:
    """Read INFORMATION_SCHEMA.COLUMNS for a UDM table and insert into UdmTablesColumnsList.

    Populates the metadata columns added by
    ``migrations/udm_tables_columns_list_metadata.py``:

      * ``ObjectType``           — 'TABLE' / 'VIEW' from the source system.
      * ``DatabaseName``         — source database name (table_config.source_database).
      * ``MetadataLastUpdated``  — SYSDATETIME() at INSERT time.

    Args:
        table_config: Table configuration.
        table_name: The effective table name used in UdmTablesColumnsList.
        source_name: The source name (DNA, CCM, etc.).
        layer: 'Stage' or 'Bronze'.

    Returns:
        Number of columns inserted.
    """
    if layer == "Stage":
        full_table_name = table_config.stage_full_table_name
    else:
        full_table_name = table_config.bronze_full_table_name

    parts = full_table_name.split(".")
    db, schema, tbl = parts[0], parts[1], parts[2]

    # Read columns from the actual created table
    conn = get_connection(db)
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT COLUMN_NAME, ORDINAL_POSITION "
            f"FROM [{db}].INFORMATION_SCHEMA.COLUMNS "
            f"WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? "
            f"ORDER BY ORDINAL_POSITION",
            schema, tbl,
        )
        columns = cursor.fetchall()
        cursor.close()
    finally:
        conn.close()

    if not columns:
        logger.warning("No columns found in INFORMATION_SCHEMA for %s", full_table_name)
        return 0

    # Source-side metadata for the new audit columns. ObjectType lookup runs
    # once per layer; cheap. DatabaseName comes straight off table_config.
    object_type = _discover_source_object_type(table_config)
    database_name = table_config.source_database or None

    # Insert into UdmTablesColumnsList. SYSDATETIME() server-side keeps
    # MetadataLastUpdated consistent across rows of the same batch.
    conn = get_general_connection()
    try:
        cursor = conn.cursor()
        cursor.executemany(
            """
            INSERT INTO dbo.UdmTablesColumnsList
                (SourceName, TableName, ColumnName, OrdinalPosition,
                 IsPrimaryKey, Layer, IsIndex, IndexName, IndexType,
                 ObjectType, DatabaseName, MetadataLastUpdated)
            VALUES (?, ?, ?, ?, 0, ?, 0, NULL, NULL, ?, ?, SYSDATETIME())
            """,
            [
                (source_name, table_name, col_name, ordinal, layer,
                 object_type, database_name)
                for col_name, ordinal in columns
            ],
        )
        cursor.close()
    finally:
        conn.close()

    return len(columns)


# ---------------------------------------------------------------------------
# PK discovery — routes to Oracle or SQL Server
# ---------------------------------------------------------------------------

def _discover_pks(table_config: TableConfig) -> list[str]:
    """Discover primary key columns from the source system.

    Routes by source system:
      * Oracle  -> :func:`_discover_oracle_pks`   (DNA in this pipeline).
      * SQL Server -> :func:`_discover_sqlserver_pks`  (CCM, EPICOR).
      * Other  -> warn and return empty (operator must populate
        ``UdmTablesColumnsList.IsPrimaryKey`` manually for now).

    Each branch handles tables AND views:
      * Tables: standard PK constraint / unique index lookup.
      * Views: standard catalogs return empty, so the discovery walks
        the view's referenced tables and uses their PKs (matching
        against the view's column set).

    No operator config required — the column-sync flow stays self-healing
    on first encounter for both tables and views, as long as the view
    selects through to a referenced table's PK columns.
    """
    return _discover_pks_from_source(table_config)


def _discover_pks_from_source(table_config: TableConfig) -> list[str]:
    """Discover primary key columns from the source system.

    Routing:
        Oracle -> ALL_CONSTRAINTS (tables) -> ALL_INDEXES unique (views) -> warn
        SQL Server -> sys.indexes PK -> unique index fallback -> warn

    Returns:
        List of PK column names, or empty list if none discovered.
    """
    source = get_source_for_table(table_config)

    try:
        if source.source_type == SourceType.ORACLE:
            return _discover_oracle_pks(table_config, source)
        else:
            return _discover_sqlserver_pks(table_config, source)
    except Exception:
        logger.exception(
            "PK discovery failed for %s.%s — columns synced but PKs unknown",
            table_config.source_name, table_config.source_object_name,
        )
        return []


def _discover_oracle_pks(table_config: TableConfig, source) -> list[str]:
    """Discover PKs from Oracle: constraints first, then unique indexes as fallback.

    Oracle views don't expose PKs via ALL_CONSTRAINTS, so we try ALL_INDEXES
    for unique indexes on the view. If neither returns results, the pipeline
    logs a warning and IsPrimaryKey must be set manually.
    """
    import oracledb

    connect_params = source.oracledb_connect_params()

    schema = table_config.source_schema_name.upper()
    table = table_config.source_object_name.upper()

    conn = oracledb.connect(**connect_params)
    try:
        # Attempt 1: Primary key constraint (works for tables, not views)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT acc.COLUMN_NAME
            FROM ALL_CONSTRAINTS ac
            JOIN ALL_CONS_COLUMNS acc
                ON ac.CONSTRAINT_NAME = acc.CONSTRAINT_NAME
                AND ac.OWNER = acc.OWNER
            WHERE ac.OWNER = :schema
              AND ac.TABLE_NAME = :table_name
              AND ac.CONSTRAINT_TYPE = 'P'
            ORDER BY acc.POSITION
            """,
            schema=schema, table_name=table,
        )
        pk_cols = [row[0] for row in cursor.fetchall()]
        cursor.close()

        if pk_cols:
            logger.info(
                "Oracle PK constraint discovered for %s.%s: %s",
                schema, table, pk_cols,
            )
            return pk_cols

        # Attempt 2: Unique index (works for some views and tables without PK constraints)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT aic.COLUMN_NAME
            FROM ALL_INDEXES ai
            JOIN ALL_IND_COLUMNS aic
                ON ai.INDEX_NAME = aic.INDEX_NAME
                AND ai.TABLE_OWNER = aic.INDEX_OWNER
            WHERE ai.TABLE_OWNER = :schema
              AND ai.TABLE_NAME = :table_name
              AND ai.UNIQUENESS = 'UNIQUE'
            ORDER BY aic.COLUMN_POSITION
            """,
            schema=schema, table_name=table,
        )
        unique_cols = [row[0] for row in cursor.fetchall()]
        cursor.close()

        if unique_cols:
            logger.info(
                "Oracle unique index discovered for %s.%s (using as PK): %s",
                schema, table, unique_cols,
            )
            return unique_cols

        # Attempt 3: View walk — look up the view's referenced tables in
        # ALL_DEPENDENCIES, take each referenced table's PK, and use it
        # if all PK columns appear in the view's column list. Catches the
        # common case where a view exposes the underlying table's business
        # key as-is.
        view_pks = _oracle_view_pk_via_underlying_tables(
            conn, schema, table,
            view_columns=_oracle_object_columns(conn, schema, table),
        )
        if view_pks:
            return view_pks

        # Nothing found — view derived from non-PK columns or unsupported source.
        logger.warning(
            "No PK discoverable for Oracle source %s.%s (constraint, unique "
            "index, and view-walk all empty). Set IsPrimaryKey=1 manually in "
            "General.dbo.UdmTablesColumnsList for the relevant column(s).",
            schema, table,
        )
        return []
    finally:
        conn.close()


def _oracle_object_columns(conn, schema: str, table: str) -> set[str]:
    """Return the set of column names for an Oracle table or view."""
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT COLUMN_NAME FROM ALL_TAB_COLUMNS "
            "WHERE OWNER = :schema AND TABLE_NAME = :table_name",
            schema=schema, table_name=table,
        )
        return {row[0] for row in cursor.fetchall()}
    finally:
        cursor.close()


def _oracle_view_pk_via_underlying_tables(
    conn,
    schema: str,
    view_name: str,
    view_columns: set[str],
) -> list[str]:
    """Walk ``ALL_DEPENDENCIES`` for a view's referenced tables and use one
    of their PKs as the view's PK.

    Strategy:
      1. Get the set of TABLEs this view directly references.
      2. For each referenced table, look up its PK columns.
      3. The first referenced table whose PK columns are ALL present in
         the view's column set wins. Multiple matches log a warning and
         return the first match (deterministic by ALL_DEPENDENCIES
         ordering); pick the right one manually if that's wrong.

    Returns an empty list if no underlying-table PK matches the view.
    """
    cursor = conn.cursor()
    try:
        cursor.execute(
            """
            SELECT DISTINCT REFERENCED_OWNER, REFERENCED_NAME
            FROM ALL_DEPENDENCIES
            WHERE OWNER = :schema
              AND NAME = :view_name
              AND REFERENCED_TYPE = 'TABLE'
            """,
            schema=schema, view_name=view_name,
        )
        referenced_tables = cursor.fetchall()
    finally:
        cursor.close()

    if not referenced_tables:
        logger.info(
            "Oracle view-walk: %s.%s has no referenced TABLE dependencies "
            "(possibly built on other views or computed columns).",
            schema, view_name,
        )
        return []

    matches: list[tuple[str, str, list[str]]] = []
    for ref_owner, ref_name in referenced_tables:
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT acc.COLUMN_NAME
                FROM ALL_CONSTRAINTS ac
                JOIN ALL_CONS_COLUMNS acc
                    ON ac.CONSTRAINT_NAME = acc.CONSTRAINT_NAME
                    AND ac.OWNER = acc.OWNER
                WHERE ac.OWNER = :owner
                  AND ac.TABLE_NAME = :table_name
                  AND ac.CONSTRAINT_TYPE = 'P'
                ORDER BY acc.POSITION
                """,
                owner=ref_owner, table_name=ref_name,
            )
            ref_pk = [row[0] for row in cursor.fetchall()]
        finally:
            cursor.close()
        if ref_pk and all(c in view_columns for c in ref_pk):
            matches.append((ref_owner, ref_name, ref_pk))

    if not matches:
        return []
    if len(matches) > 1:
        logger.warning(
            "Oracle view-walk: %s.%s has %d underlying-table PK candidates; "
            "using first (%s.%s -> %s). If this is wrong, set IsPrimaryKey "
            "manually. Other candidates: %s",
            schema, view_name, len(matches),
            matches[0][0], matches[0][1], matches[0][2],
            [(o, n, p) for o, n, p in matches[1:]],
        )
    chosen = matches[0]
    logger.info(
        "Oracle view-walk: %s.%s -> using PK from %s.%s = %s",
        schema, view_name, chosen[0], chosen[1], chosen[2],
    )
    return chosen[2]

def _discover_sqlserver_pks(table_config: TableConfig, source) -> list[str]:
    """PK-3: Discover PKs from SQL Server with improved fallback logic.

    Priority order:
      1. is_primary_key = 1 — always valid, SQL Server enforces NOT NULL
      2. is_unique_constraint = 1, all key columns NOT NULL, no filter
      3. is_unique = 1 (index), all key columns NOT NULL, no filter,
         prefer clustered > nonclustered, then fewest columns
      4. If nothing qualifies, log error and return [] for manual intervention

    PK-3 improvements over the original:
      - Rejects nullable unique index columns (prevents BankruptcyType-style crashes)
      - Rejects filtered indexes (has_filter=1) — these don't cover all rows
      - Logs ALL candidate indexes so operators can review via --setup
      - Prefers clustered > nonclustered, then fewest columns

    See: "Fixing Three Silent Data-Corruption Bugs" doc, section 1.
    """

    schema = table_config.source_schema_name
    table = table_config.source_object_name

    conn = pyodbc.connect(source.pyodbc_connection_string(), autocommit=True)
    try:
        cursor = conn.cursor()

        # --- Attempt 1: Primary key (always valid — SQL Server enforces NOT NULL) ---
        cursor.execute(
            """
            SELECT COL_NAME(ic.object_id, ic.column_id) AS ColumnName
            FROM sys.indexes i
            JOIN sys.index_columns ic
                ON i.object_id = ic.object_id AND i.index_id = ic.index_id
            WHERE i.is_primary_key = 1
              AND i.object_id = OBJECT_ID(? + '.' + ?)
              AND ic.is_included_column = 0
            ORDER BY ic.key_ordinal
            """,
            schema, table,
        )
        pk_cols = [row[0] for row in cursor.fetchall()]

        if pk_cols:
            logger.info(
                "SQL Server PK discovered for %s.%s: %s",
                schema, table, pk_cols,
            )
            cursor.close()
            return pk_cols

        # --- Log all candidate unique indexes for operator review ---
        cursor.execute(
            """
            SELECT
                i.name AS index_name,
                i.index_id,
                i.is_unique_constraint,
                i.type_desc,
                i.has_filter,
                i.filter_definition,
                COUNT(ic.column_id) AS key_column_count,
                MAX(CASE WHEN c.is_nullable = 1 THEN 1 ELSE 0 END) AS has_nullable_key
            FROM sys.indexes i
            JOIN sys.index_columns ic
                ON i.object_id = ic.object_id AND i.index_id = ic.index_id
                AND ic.is_included_column = 0
            JOIN sys.columns c
                ON ic.object_id = c.object_id AND ic.column_id = c.column_id
            WHERE i.is_unique = 1
              AND i.is_primary_key = 0
              AND i.is_disabled = 0
              AND i.object_id = OBJECT_ID(? + '.' + ?)
            GROUP BY i.name, i.index_id, i.is_unique_constraint,
                     i.type_desc, i.has_filter, i.filter_definition
            ORDER BY
                i.is_unique_constraint DESC,
                CASE WHEN i.type_desc = 'CLUSTERED' THEN 0 ELSE 1 END,
                COUNT(ic.column_id),
                i.index_id
            """,
            schema, table,
        )
        candidates = cursor.fetchall()

        if candidates:
            logger.info(
                "PK-3: %d unique index candidates for %s.%s:",
                len(candidates), schema, table,
            )
            for c in candidates:
                idx_name, idx_id, is_constraint, type_desc, has_filter, filter_def, key_count, has_nullable = c
                status_parts = []
                if has_nullable:
                    status_parts.append("REJECTED: nullable key column")
                if has_filter:
                    status_parts.append(f"REJECTED: filtered ({filter_def})")
                status = " | ".join(status_parts) if status_parts else "ELIGIBLE"
                logger.info(
                    "  %s (id=%d, %s, %s, %d key cols): %s",
                    idx_name, idx_id, type_desc,
                    "CONSTRAINT" if is_constraint else "INDEX",
                    key_count, status,
                )

        # --- Attempt 2: Best eligible unique index ---
        # Priority: constraint > clustered > nonclustered, then fewest columns
        cursor.execute(
            """
            SELECT TOP 1 i.name, i.index_id
            FROM sys.indexes i
            WHERE i.is_unique = 1
              AND i.is_primary_key = 0
              AND i.is_disabled = 0
              AND i.has_filter = 0
              AND i.object_id = OBJECT_ID(? + '.' + ?)
              AND NOT EXISTS (
                  SELECT 1
                  FROM sys.index_columns ic
                  JOIN sys.columns c
                      ON ic.object_id = c.object_id AND ic.column_id = c.column_id
                  WHERE ic.object_id = i.object_id
                    AND ic.index_id = i.index_id
                    AND ic.is_included_column = 0
                    AND c.is_nullable = 1
              )
            ORDER BY
                i.is_unique_constraint DESC,
                CASE WHEN i.type_desc = 'CLUSTERED' THEN 0 ELSE 1 END,
                (SELECT COUNT(*)
                 FROM sys.index_columns ic2
                 WHERE ic2.object_id = i.object_id
                   AND ic2.index_id = i.index_id
                   AND ic2.is_included_column = 0),
                i.index_id
            """,
            schema, table,
        )
        best = cursor.fetchone()

        if best:
            idx_name, idx_id = best
            # Fetch the columns for the selected index
            cursor.execute(
                """
                SELECT COL_NAME(ic.object_id, ic.column_id)
                FROM sys.index_columns ic
                WHERE ic.object_id = OBJECT_ID(? + '.' + ?)
                  AND ic.index_id = ?
                  AND ic.is_included_column = 0
                ORDER BY ic.key_ordinal
                """,
                schema, table, idx_id,
            )
            unique_cols = [row[0] for row in cursor.fetchall()]

            if unique_cols:
                logger.info(
                    "PK-3: Selected unique index %s for %s.%s as PK: %s "
                    "(all key columns NOT NULL, no filter)",
                    idx_name, schema, table, unique_cols,
                )
                cursor.close()
                return unique_cols

        # --- Attempt 3: View walk via sys.dm_sql_referenced_entities ---
        # Common case: source object is a view that selects through to one
        # or more underlying tables. The view exposes the underlying
        # table's PK columns as-is; auto-discover them by walking the
        # dependency graph and matching against the view's column set.
        view_pks = _sqlserver_view_pk_via_underlying_tables(
            cursor, schema, table,
            view_columns=_sqlserver_object_columns(cursor, schema, table),
        )
        if view_pks:
            cursor.close()
            return view_pks

        # --- Nothing qualified ---
        if candidates:
            logger.error(
                "PK-3: %s.%s has %d unique indexes but NONE qualify as PK "
                "(all have nullable key columns or are filtered). View-walk "
                "also produced no candidates. Set IsPrimaryKey manually in "
                "UdmTablesColumnsList for the relevant column(s).",
                schema, table, len(candidates),
            )
        else:
            logger.warning(
                "PK-3: No PK, unique index, or underlying-table PK match "
                "found for %s.%s — set IsPrimaryKey manually in "
                "UdmTablesColumnsList for the relevant column(s).",
                schema, table,
            )

        cursor.close()
        return []
    finally:
        conn.close()


def _sqlserver_object_columns(cursor, schema: str, table: str) -> set[str]:
    """Return the set of column names for a SQL Server table or view."""
    cursor.execute(
        "SELECT COLUMN_NAME FROM INFORMATION_SCHEMA.COLUMNS "
        "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?",
        schema, table,
    )
    return {row[0] for row in cursor.fetchall()}


def _sqlserver_view_pk_via_underlying_tables(
    cursor,
    schema: str,
    view_name: str,
    view_columns: set[str],
) -> list[str]:
    """Walk a view's referenced tables (``sys.dm_sql_referenced_entities``)
    and use one of their PKs as the view's PK.

    Strategy:
      1. Get the set of TABLEs this view directly references.
      2. For each referenced table, look up its PK columns via
         ``sys.indexes`` / ``sys.index_columns``.
      3. The first referenced table whose PK columns are ALL present in
         the view's column set wins. Multiple matches log a warning and
         return the first match.

    Returns an empty list if no underlying-table PK matches the view's
    columns (e.g. view selects only computed/non-PK columns, or is built
    on other views).

    Note: ``sys.dm_sql_referenced_entities`` requires the view to compile
    successfully against the current database. If the view is invalid,
    the function raises and we fall back to the empty-list path.
    """
    qualified = f"{schema}.{view_name}"
    try:
        cursor.execute(
            """
            SELECT DISTINCT
                referenced_schema_name AS s,
                referenced_entity_name AS n
            FROM sys.dm_sql_referenced_entities(?, 'OBJECT')
            WHERE referenced_minor_id = 0
              AND referenced_entity_name IS NOT NULL
              AND referenced_class_desc = 'OBJECT_OR_COLUMN'
            """,
            qualified,
        )
        referenced = cursor.fetchall()
    except Exception:
        logger.debug(
            "SQL Server view-walk: sys.dm_sql_referenced_entities failed for "
            "%s — possibly an invalid view, skipping the walk.",
            qualified, exc_info=True,
        )
        return []

    if not referenced:
        logger.info(
            "SQL Server view-walk: %s has no referenced TABLE dependencies.",
            qualified,
        )
        return []

    matches: list[tuple[str, str, list[str]]] = []
    for ref_schema, ref_name in referenced:
        if ref_schema is None or ref_name is None:
            continue
        # Skip self-referencing or non-table entries.
        if ref_schema == schema and ref_name == view_name:
            continue
        try:
            cursor.execute(
                """
                SELECT COL_NAME(ic.object_id, ic.column_id) AS ColumnName
                FROM sys.indexes i
                JOIN sys.index_columns ic
                    ON i.object_id = ic.object_id AND i.index_id = ic.index_id
                WHERE i.is_primary_key = 1
                  AND i.object_id = OBJECT_ID(? + '.' + ?)
                  AND ic.is_included_column = 0
                ORDER BY ic.key_ordinal
                """,
                ref_schema, ref_name,
            )
            ref_pk = [row[0] for row in cursor.fetchall()]
        except Exception:
            logger.debug(
                "SQL Server view-walk: PK lookup failed for %s.%s",
                ref_schema, ref_name, exc_info=True,
            )
            continue
        if ref_pk and all(c in view_columns for c in ref_pk):
            matches.append((ref_schema, ref_name, ref_pk))

    if not matches:
        return []
    if len(matches) > 1:
        logger.warning(
            "SQL Server view-walk: %s has %d underlying-table PK candidates; "
            "using first (%s.%s -> %s). If this is wrong, set IsPrimaryKey "
            "manually. Other candidates: %s",
            qualified, len(matches),
            matches[0][0], matches[0][1], matches[0][2],
            [(s, n, p) for s, n, p in matches[1:]],
        )
    chosen = matches[0]
    logger.info(
        "SQL Server view-walk: %s -> using PK from %s.%s = %s",
        qualified, chosen[0], chosen[1], chosen[2],
    )
    return chosen[2]

# ---------------------------------------------------------------------------
# P1-10: Refresh PK flags from source (for --refresh-pks)
# ---------------------------------------------------------------------------

def _refresh_pk_flags(
    table_config: TableConfig,
    source_name: str,
    table_name: str,
) -> None:
    """Re-discover PKs from source and update UdmTablesColumnsList.

    Resets all IsPrimaryKey to 0, re-discovers from source, then sets new PKs to 1.
    """
    # Reset all existing PK flags
    conn = get_general_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE dbo.UdmTablesColumnsList SET IsPrimaryKey = 0 "
            "WHERE SourceName = ? AND TableName = ?",
            source_name, table_name,
        )
        cursor.close()
    finally:
        conn.close()

    # Re-discover from source
    pk_columns = _discover_pks(table_config)

    if pk_columns:
        _update_pk_flags(source_name, table_name, pk_columns)
        logger.info(
            "P1-10: Refreshed PKs for %s.%s: %s",
            source_name, table_name, pk_columns,
        )
    else:
        logger.warning(
            "P1-10: No PKs discovered during refresh for %s.%s — "
            "IsPrimaryKey must be set manually",
            source_name, table_name,
        )


# ---------------------------------------------------------------------------
# Update PK flags in UdmTablesColumnsList
# ---------------------------------------------------------------------------

def _update_pk_flags(
    source_name: str,
    table_name: str,
    pk_columns: list[str],
) -> None:
    """Set IsPrimaryKey = 1 for discovered PK columns in both Stage and Bronze layers."""
    if not pk_columns:
        return

    conn = get_general_connection()
    try:
        cursor = conn.cursor()
        placeholders = ", ".join("?" for _ in pk_columns)
        cursor.execute(
            f"""
            UPDATE dbo.UdmTablesColumnsList
            SET IsPrimaryKey = 1
            WHERE SourceName = ?
              AND TableName = ?
              AND ColumnName IN ({placeholders})
            """,
            source_name, table_name, *pk_columns,
        )
        cursor.close()
    finally:
        conn.close()


def validate_pk_uniqueness(table_config: TableConfig) -> bool:
    """NoPK-3: Validate that declared PK columns are actually unique in source.

    For tables where PKs are set manually (synthetic PKs from NoPK-3),
    this checks for duplicate values in the declared PK columns BEFORE
    the pipeline processes the table. If duplicates exist, the PKs are
    invalid and will cause Cartesian products in CDC joins.

    Args:
        table_config: Table configuration with pk_columns set.

    Returns:
        True if PKs are unique (or no PKs configured), False if duplicates found.
    """
    pk_columns = table_config.pk_columns
    if not pk_columns:
        return True  # Nothing to validate

    from utils.sources import get_source_for_table
    source = get_source_for_table(table_config)

    schema = table_config.source_schema_name
    table = table_config.source_object_name

    pk_list = ", ".join(f"[{c}]" for c in pk_columns)

    query = (
        f"SELECT TOP 5 {pk_list}, COUNT(*) AS dup_count "
        f"FROM [{schema}].[{table}] "
        f"GROUP BY {pk_list} "
        f"HAVING COUNT(*) > 1 "
        f"ORDER BY COUNT(*) DESC"
    )

    try:
        if source.source_type.name == "ORACLE":
            import oracledb
            connect_params = source.oracledb_connect_params()
            conn = oracledb.connect(**connect_params)
            pk_list_ora = ", ".join(f'"{c}"' for c in pk_columns)
            query = (
                f"SELECT {pk_list_ora}, COUNT(*) AS dup_count "
                f"FROM {schema}.{table} "
                f"GROUP BY {pk_list_ora} "
                f"HAVING COUNT(*) > 1 "
                f"ORDER BY COUNT(*) DESC "
                f"FETCH FIRST 5 ROWS ONLY"
            )
        else:
            conn = pyodbc.connect(source.pyodbc_connection_string(), autocommit=True)

        try:
            cursor = conn.cursor()
            cursor.execute(query)
            dups = cursor.fetchall()
            cursor.close()

            if dups:
                logger.error(
                    "NoPK-3: Declared PK columns %s are NOT unique in source "
                    "%s.%s — %d duplicate PK groups found. Sample duplicates: %s. "
                    "CDC joins will produce Cartesian products. Fix the PK "
                    "definition in UdmTablesColumnsList.",
                    pk_columns, table_config.source_name,
                    table_config.source_object_name,
                    len(dups),
                    [dict(zip(pk_columns + ["count"], row)) for row in dups[:3]],
                )
                return False

            logger.info(
                "NoPK-3: PK uniqueness validated for %s.%s on columns %s",
                table_config.source_name, table_config.source_object_name,
                pk_columns,
            )
            return True

        finally:
            conn.close()

    except Exception as e:
        logger.warning(
            "NoPK-3: PK uniqueness validation failed for %s.%s — %s. "
            "Continuing without validation.",
            table_config.source_name, table_config.source_object_name, e,
        )
        return True  # Don't block pipeline on validation failures

# ---------------------------------------------------------------------------
# Reload columns into in-memory TableConfig
# ---------------------------------------------------------------------------

def _reload_columns_into_config(table_config: TableConfig) -> None:
    """Re-read UdmTablesColumnsList and update table_config.columns in place.

    This ensures pk_columns and index_configs reflect the newly synced metadata
    so CDC/SCD2 work on the very first pipeline run.
    """
    from orchestration.table_config import ColumnConfig

    table_name = table_config.effective_stage_name
    source_name = table_config.source_name

    conn = get_general_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT SourceName, TableName, ColumnName, OrdinalPosition, "
            "IsPrimaryKey, Layer, IsIndex, IndexName, IndexType "
            "FROM dbo.UdmTablesColumnsList "
            "WHERE SourceName = ? AND TableName = ?",
            source_name, table_name,
        )
        rows = cursor.fetchall()
        cursor.close()
    finally:
        conn.close()

    table_config.columns.clear()
    for row in rows:
        table_config.columns.append(
            ColumnConfig(
                source_name=row[0],
                table_name=row[1],
                column_name=row[2],
                ordinal_position=int(row[3]) if row[3] is not None else 0,
                is_primary_key=bool(row[4]),
                layer=row[5] or "",
                is_index=bool(row[6]) if row[6] is not None else False,
                index_name=row[7],
                index_type=row[8],
            )
        )

    pk_count = len(table_config.pk_columns)
    logger.info(
        "Reloaded %d columns for %s.%s (%d PKs)",
        len(table_config.columns), source_name, table_name, pk_count,
    )


# ---------------------------------------------------------------------------
# E-16: Cross-platform type drift detection
# ---------------------------------------------------------------------------

def detect_source_type_drift(table_config: TableConfig) -> list[str]:
    """E-16: Detect source column type/precision/scale changes.

    Compares current source column metadata against the existing UDM Stage
    table's INFORMATION_SCHEMA. Detects precision/scale changes that could
    affect hash computation (e.g., NUMBER(10,2) → NUMBER(15,4) causing
    silent precision differences).

    Does NOT query Oracle or SQL Server source metadata directly — that
    would add a dependency on source availability. Instead, compares the
    current extraction DataFrame types (already available) against the
    target table types. The schema/evolution.py module handles the actual
    ALTER TABLE changes; this function provides early warning logging.

    Args:
        table_config: Table configuration.

    Returns:
        List of warning messages for detected type drifts. Empty if clean.
    """
    stage_table = table_config.stage_full_table_name
    from extract.udm_connectorx_extractor import table_exists

    if not table_exists(stage_table):
        return []

    # OPT-B: Use table_config host/database instead of hardcoded registry
    source = get_source_for_table(table_config)
    warnings = []

    try:
        if source.source_type == SourceType.ORACLE:
            warnings = _check_oracle_type_drift(table_config, source)
        else:
            warnings = _check_sqlserver_type_drift(table_config, source)
    except Exception:
        logger.debug(
            "E-16: Type drift detection failed for %s.%s — continuing",
            table_config.source_name, table_config.source_object_name,
            exc_info=True,
        )

    if warnings:
        logger.warning(
            "E-16: Source type drift detected for %s.%s: %s",
            table_config.source_name, table_config.source_object_name,
            warnings,
        )

    return warnings


def _check_oracle_type_drift(table_config: TableConfig, source) -> list[str]:
    """E-16: Check Oracle source for precision/scale changes."""
    import oracledb

    connect_params = source.oracledb_connect_params()

    schema = table_config.source_schema_name.upper()
    table = table_config.source_object_name.upper()

    warnings = []
    conn = oracledb.connect(**connect_params)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT COLUMN_NAME, DATA_TYPE, DATA_PRECISION, DATA_SCALE, DATA_LENGTH
            FROM ALL_TAB_COLUMNS
            WHERE OWNER = :schema AND TABLE_NAME = :table_name
            ORDER BY COLUMN_ID
            """,
            schema=schema, table_name=table,
        )
        source_cols = {
            row[0]: {
                "type": row[1],
                "precision": row[2],
                "scale": row[3],
                "length": row[4],
            }
            for row in cursor.fetchall()
        }
        cursor.close()
    finally:
        conn.close()

    # Compare against Stage INFORMATION_SCHEMA
    stage_parts = table_config.stage_full_table_name.split(".")
    db, stage_schema, stage_tbl = stage_parts[0], stage_parts[1], stage_parts[2]

    stage_conn = get_connection(db)
    try:
        cursor = stage_conn.cursor()
        cursor.execute(
            f"SELECT COLUMN_NAME, DATA_TYPE, NUMERIC_PRECISION, NUMERIC_SCALE, "
            f"CHARACTER_MAXIMUM_LENGTH "
            f"FROM [{db}].INFORMATION_SCHEMA.COLUMNS "
            f"WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?",
            stage_schema, stage_tbl,
        )
        stage_cols = {
            row[0]: {
                "type": row[1],
                "precision": row[2],
                "scale": row[3],
                "length": row[4],
            }
            for row in cursor.fetchall()
        }
        cursor.close()
    finally:
        stage_conn.close()

    # Check numeric precision/scale changes for common columns
    for col_name, src in source_cols.items():
        if col_name not in stage_cols:
            continue
        if src["type"] == "NUMBER" and src["precision"] is not None:
            stg = stage_cols[col_name]
            if stg["precision"] is not None:
                if src["precision"] != stg["precision"] or src["scale"] != stg["scale"]:
                    warnings.append(
                        f"{col_name}: Oracle NUMBER({src['precision']},{src['scale']}) "
                        f"vs Stage ({stg['type']} precision={stg['precision']}, "
                        f"scale={stg['scale']})"
                    )

    return warnings


def _check_sqlserver_type_drift(table_config: TableConfig, source) -> list[str]:
    """E-16: Check SQL Server source for precision/scale changes."""
    schema = table_config.source_schema_name
    table = table_config.source_object_name

    warnings = []
    source_conn = pyodbc.connect(source.pyodbc_connection_string(), autocommit=True)
    try:
        cursor = source_conn.cursor()
        cursor.execute(
            "SELECT COLUMN_NAME, DATA_TYPE, NUMERIC_PRECISION, NUMERIC_SCALE, "
            "CHARACTER_MAXIMUM_LENGTH "
            "FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ? "
            "ORDER BY ORDINAL_POSITION",
            schema, table,
        )
        source_cols = {
            row[0]: {
                "type": row[1],
                "precision": row[2],
                "scale": row[3],
                "length": row[4],
            }
            for row in cursor.fetchall()
        }
        cursor.close()
    finally:
        source_conn.close()

    # Compare against Stage INFORMATION_SCHEMA
    stage_parts = table_config.stage_full_table_name.split(".")
    db, stage_schema, stage_tbl = stage_parts[0], stage_parts[1], stage_parts[2]

    stage_conn = get_connection(db)
    try:
        cursor = stage_conn.cursor()
        cursor.execute(
            f"SELECT COLUMN_NAME, DATA_TYPE, NUMERIC_PRECISION, NUMERIC_SCALE, "
            f"CHARACTER_MAXIMUM_LENGTH "
            f"FROM [{db}].INFORMATION_SCHEMA.COLUMNS "
            f"WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?",
            stage_schema, stage_tbl,
        )
        stage_cols = {
            row[0]: {
                "type": row[1],
                "precision": row[2],
                "scale": row[3],
                "length": row[4],
            }
            for row in cursor.fetchall()
        }
        cursor.close()
    finally:
        stage_conn.close()

    # Check for precision/scale changes in common numeric columns
    for col_name, src in source_cols.items():
        if col_name not in stage_cols:
            continue
        stg = stage_cols[col_name]
        if src["precision"] is not None and stg["precision"] is not None:
            if src["precision"] != stg["precision"] or src["scale"] != stg["scale"]:
                warnings.append(
                    f"{col_name}: source ({src['type']} precision={src['precision']}, "
                    f"scale={src['scale']}) vs Stage ({stg['type']} "
                    f"precision={stg['precision']}, scale={stg['scale']})"
                )
        if src["length"] is not None and stg["length"] is not None:
            if src["length"] != stg["length"]:
                warnings.append(
                    f"{col_name}: source length={src['length']} "
                    f"vs Stage length={stg['length']}"
                )

    return warnings