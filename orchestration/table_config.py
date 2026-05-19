"""TableConfig + TableConfigLoader from General.dbo.UdmTablesList metadata.

Drives extraction routing, table naming, and column/PK configuration.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import connectorx as cx
import polars as pl

import utils.configuration as config
from utils.connections import general_connectorx_uri, get_general_connection, resolve_schema_name

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# R-9 helpers — parse the SCD2 enhancement columns from UdmTablesList rows.
# The columns are NVARCHAR strings (comma-separated) or BIT flags; empty /
# NULL values must collapse to sensible Python defaults.
# ---------------------------------------------------------------------------


def _none_if_blank(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_csv_list(value: object) -> list[str] | None:
    """Parse a comma-separated string into a trimmed list. Empty → None."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    parts = [p.strip() for p in text.split(",") if p.strip()]
    return parts or None


def _bit_to_bool(value: object, *, default: bool) -> bool:
    """Parse a SQL BIT value (0/1/True/False/None) into a Python bool."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "t", "yes", "y"}:
        return True
    if text in {"0", "false", "f", "no", "n", ""}:
        return False
    return default


@dataclass
class ColumnConfig:
    """Column metadata from General.dbo.UdmTablesColumnsList."""

    source_name: str
    table_name: str
    column_name: str
    ordinal_position: int
    is_primary_key: bool
    layer: str
    is_index: bool = False
    index_name: str | None = None
    index_type: str | None = None


@dataclass
class TableConfig:
    """Configuration for a single table in the pipeline.

    Populated from General.dbo.UdmTablesList + UdmTablesColumnsList.
    """

    source_object_name: str
    source_server: str
    source_database: str
    source_schema_name: str
    source_name: str
    stage_table_name: str | None = None
    bronze_table_name: str | None = None
    source_aggregate_column_name: str | None = None
    source_aggregate_column_type: str | None = None
    source_index_hint: str | None = None
    partition_on: str | None = None
    first_load_date: str | None = None
    lookback_days: int | None = None
    stage_load_tool: str | None = None
    # SS-1: opt-in flag — when True, stage_full_table_name and
    # bronze_full_table_name return bare names (no _cdc / _scd2_python
    # suffix). Default False preserves the existing convention so
    # everything other than explicitly-migrated tables behaves identically.
    # Populated from UdmTablesList.StripSuffix (added by
    # migrations/strip_suffix_column.py).
    strip_suffix: bool = False
    # Per-table override for the P1-13 daily-extraction guard. When set,
    # the growth-guard limit becomes max(growth_threshold * baseline,
    # max_rows_per_day) instead of growth_threshold * baseline alone.
    # Lets growing tables (e.g. CARDTXN, AuditLog) bypass the multiplier
    # check while still blocking Cartesian-join-class spikes above the
    # absolute ceiling. NULL → use the global MAX_ROWS_PER_DAY default.
    # Populated from UdmTablesList.MaxRowsPerDay (added by
    # migrations/extraction_guard_per_table.py).
    max_rows_per_day: int | None = None
    columns: list[ColumnConfig] = field(default_factory=list)
    # Resolved schema casing from sys.schemas — set by _build_configs()
    _resolved_stage_schema: str | None = None
    _resolved_bronze_schema: str | None = None
    exclude_columns: set[str] = field(default_factory=set)

    # --- SCD2 enhancement configuration (R-9.1) ---
    # Populated from UdmTablesList columns added by migrations/scd2_phase1_config.py.
    # All defaults preserve current behavior so tables without configuration
    # process identically to the pre-Phase-1 pipeline.

    # "incremental" (CDC → SCD2, today's default) or "temporal" (Mode 2, R-10).
    scd2_mode: str = "incremental"

    # Ordered date columns for SCD2 effective-date derivation (R-2).
    # Column 0 is the primary (extraction windowing + first-row EffDate);
    # columns 1+ are waterfall tie-breakers.
    scd2_date_columns: list[str] | None = None

    # Source column containing soft-delete/inactive date (R-4.2).
    source_delete_date_column: str | None = None

    # ORDER BY expression for duplicate (PK + EffDate) resolution (R-8).
    duplicate_resolution_order: str | None = None

    # R-8: allow non-deterministic duplicate resolution when no ORDER BY provided.
    allow_duplicates: bool = False

    # R-2.4: preserve datetime precision vs truncate to date-only.
    preserve_datetime: bool = False

    # R-6.2: run chain-integrity repair after each SCD2 promotion.
    repair_chain_after: bool = True

    # R-5.1: suppress GAP warnings in chain validation.
    allow_gaps: bool = False

    # R-10.2 step 1: columns excluded from change-detection hash.
    exclude_from_hash: list[str] | None = None

    # R-2.5: default date for NULL primary begin dates (ISO string).
    default_begin_date: str | None = None

    # R-11: columns that force a new SCD2 segment on value change
    # (applies to 3+ column waterfalls only).
    force_new_segment_columns: list[str] | None = None

    # R-2 retention-aware delete classification. When set, delete-closes
    # older than this many days are INFO (expected purge); anything newer
    # is WARNING (anomalous delete). Typical values: CCM TransactionDetail
    # = 1080, StatementHistory = 365. Source:
    # ``UdmTablesList.ExpectedRetentionDays`` (see migrations/scd2_expected_retention_days.py).
    # NULL leaves the pre-R-2 unclassified behaviour intact.
    expected_retention_days: int | None = None

    # Modified-date sweep (Tier 2 large-table CDC). Source column that
    # records the row's last-modification timestamp (typical DNA
    # convention: DATELASTMAINT). When set, the modified-date sweep
    # extracts only (PK, LastModifiedColumn) from source, compares against
    # Bronze active rows' UdmSourceBeginDate, and reloads PKs whose source
    # has been touched after Bronze last saw them. Catches late updates
    # that fall outside the LookbackDays window. NULL → sweep skipped.
    # Source: ``UdmTablesList.LastModifiedColumn``.
    last_modified_column: str | None = None

    # D63 + D125 (2026-05-19) per-table CDC mode dispatch flag.
    # Values: 'change_detect' (legacy Stage→CDC→SCD2; D63 default),
    # 'parquet_snapshot' (D2 Parquet→replay→SCD2 path),
    # 'both' (D125 BOTH_LEGACY_FEEDS: Parquet audit substrate + legacy
    # CDC drives Bronze). Per-table column on UdmTablesList added by
    # migrations/cdc_mode_column.py (B-542). Default 'change_detect'
    # preserves current behavior on tables where the column is absent
    # (defensive for pre-migration code paths).
    cdc_mode: str = "change_detect"

    @property
    def effective_stage_name(self) -> str:
        return self.stage_table_name or self.source_object_name

    @property
    def effective_bronze_name(self) -> str:
        return self.bronze_table_name or self.source_object_name

    @property
    def stage_schema(self) -> str:
        return self._resolved_stage_schema or self.source_name

    @property
    def bronze_schema(self) -> str:
        return self._resolved_bronze_schema or self.source_name

    @property
    def stage_full_table_name(self) -> str:
        # SS-1: ``StripSuffix = 1`` drops the trailing ``_cdc`` for tables
        # that have migrated off the legacy T-SQL pipeline. Default 0
        # keeps the existing behavior for every other table.
        suffix = "" if self.strip_suffix else "_cdc"
        return f"{config.STAGE_DB}.{self.stage_schema}.{self.effective_stage_name}{suffix}"

    @property
    def bronze_full_table_name(self) -> str:
        # SS-1: see stage_full_table_name. Drops ``_scd2_python`` when
        # opted in.
        suffix = "" if self.strip_suffix else "_scd2_python"
        return f"{config.BRONZE_DB}.{self.bronze_schema}.{self.effective_bronze_name}{suffix}"

    @property
    def source_full_table_name(self) -> str:
        return f"{self.source_database}.{self.source_schema_name}.{self.source_object_name}"

    @property
    def is_large_table(self) -> bool:
        return self.source_aggregate_column_name is not None

    @property
    def pk_columns(self) -> list[str]:
        return [
            c.column_name
            for c in self.columns
            if c.is_primary_key and c.layer == "Stage"
        ]

    @property
    def index_configs(self) -> list[ColumnConfig]:
        return [c for c in self.columns if c.is_index]

    @property
    def uses_oracledb(self) -> bool:
        """Oracle + SourceIndexHint populated -> oracledb with INDEX hints."""
        return self.source_index_hint is not None

    @property
    def is_oracle(self) -> bool:
        from utils.sources import SourceType, get_source
        return get_source(self.source_name).source_type == SourceType.ORACLE

    @property
    def is_sql_server(self) -> bool:
        from utils.sources import SourceType, get_source
        return get_source(self.source_name).source_type == SourceType.SQL_SERVER


class TableConfigLoader:
    """Loads table configs from General.dbo.UdmTablesList.

    Uses ConnectorX for unfiltered bulk reads and pyodbc for filtered queries
    (H-3: parameterized queries prevent SQL injection on user-supplied values).
    """

    def __init__(self) -> None:
        self._uri = general_connectorx_uri()

    _TABLES_SELECT = (
        "SELECT SourceObjectName, SourceServer, SourceDatabaseName, "
        "SourceSchemaName, SourceName, StageTableName, BronzeTableName, "
        "SourceAggregateColumnName, SourceAggregateColumnType, "
        "SourceIndexHint, PartitionOn, FirstLoadDate, LookbackDays, "
        "StageLoadTool, ExcludeColumns, "
        # R-9.2 SCD2 enhancement columns (added by migrations/scd2_phase1_config.py).
        "SCD2Mode, SCD2DateColumns, SourceDeleteDateColumn, "
        "DuplicateResolutionOrder, AllowDuplicates, PreserveDateTime, "
        "RepairChainAfter, AllowGaps, ExcludeFromHash, DefaultBeginDate, "
        "ForceNewSegmentColumns, ExpectedRetentionDays, LastModifiedColumn, "
        # SS-1 (added by migrations/strip_suffix_column.py).
        "StripSuffix, "
        # Per-table extraction-guard override (added by
        # migrations/extraction_guard_per_table.py).
        "MaxRowsPerDay, "
        # D63 + D125 per-table CDC mode dispatch flag (added by
        # migrations/cdc_mode_column.py B-542 2026-05-19).
        "CDCMode "
        "FROM dbo.UdmTablesList"
    )

    def _load_tables_df(
        self,
        conditions: list[str] | None = None,
        params: list | None = None,
    ) -> pl.DataFrame:
        """Load table list with optional parameterized WHERE clause.

        H-3: When conditions contain parameter placeholders (?), uses pyodbc
        for safe parameterized execution. Otherwise uses ConnectorX for speed.
        """
        if conditions:
            where = " WHERE " + " AND ".join(conditions)
            if params:
                # H-3: Use pyodbc for parameterized queries (user-supplied values)
                conn = get_general_connection()
                try:
                    cursor = conn.cursor()
                    cursor.execute(self._TABLES_SELECT + where, *params)
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
            else:
                # No params — safe static conditions, use ConnectorX
                return cx.read_sql(self._uri, self._TABLES_SELECT + where, return_type="polars")
        return cx.read_sql(self._uri, self._TABLES_SELECT, return_type="polars")

    def _load_columns_df(self) -> pl.DataFrame:
        query = (
            "SELECT SourceName, TableName, ColumnName, OrdinalPosition, "
            "IsPrimaryKey, Layer, IsIndex, IndexName, IndexType "
            "FROM dbo.UdmTablesColumnsList"
        )
        return cx.read_sql(self._uri, query, return_type="polars")

    def _resolve_schemas(self, source_names: set[str]) -> dict[tuple[str, str], str]:
        """Resolve actual schema casing for each (database, source_name) pair.

        Caches results so we only query sys.schemas once per unique pair
        (typically 2 queries total: one for Stage DB, one for Bronze DB).
        """
        resolved: dict[tuple[str, str], str] = {}
        for source_name in source_names:
            for database in (config.STAGE_DB, config.BRONZE_DB):
                key = (database, source_name)
                if key not in resolved:
                    resolved[key] = resolve_schema_name(database, source_name)
        return resolved

    def _build_configs(self, tables_df: pl.DataFrame, columns_df: pl.DataFrame) -> list[TableConfig]:
        # Resolve schema casing once per unique source_name
        unique_sources = set(tables_df["SourceName"].to_list())
        schema_map = self._resolve_schemas(unique_sources)

        configs = []
        for row in tables_df.iter_rows(named=True):
            tc = TableConfig(
                source_object_name=row["SourceObjectName"],
                source_server=row["SourceServer"] or "",
                source_database=row["SourceDatabaseName"] or "",
                source_schema_name=row["SourceSchemaName"] or "",
                source_name=row["SourceName"],
                stage_table_name=row.get("StageTableName"),
                bronze_table_name=row.get("BronzeTableName"),
                source_aggregate_column_name=row.get("SourceAggregateColumnName"),
                source_aggregate_column_type=row.get("SourceAggregateColumnType"),
                source_index_hint=row.get("SourceIndexHint"),
                partition_on=row.get("PartitionOn"),
                first_load_date=str(row["FirstLoadDate"]) if row.get("FirstLoadDate") else None,
                lookback_days=int(row["LookbackDays"]) if row.get("LookbackDays") else None,
                stage_load_tool=row.get("StageLoadTool"),
            )

            # Parse ExcludeColumns as comma-separated set
            _raw_exclude = row.get("ExcludeColumns") or ""
            tc.exclude_columns = {
                c.strip() for c in _raw_exclude.split(",") if c.strip()
            }

            # --- R-9.1 SCD2 enhancement fields ---
            tc.scd2_mode = (row.get("SCD2Mode") or "incremental").strip().lower()
            tc.scd2_date_columns = _parse_csv_list(row.get("SCD2DateColumns"))
            tc.source_delete_date_column = _none_if_blank(row.get("SourceDeleteDateColumn"))
            tc.duplicate_resolution_order = _none_if_blank(row.get("DuplicateResolutionOrder"))
            tc.allow_duplicates = _bit_to_bool(row.get("AllowDuplicates"), default=False)
            tc.preserve_datetime = _bit_to_bool(row.get("PreserveDateTime"), default=False)
            tc.repair_chain_after = _bit_to_bool(row.get("RepairChainAfter"), default=True)
            tc.allow_gaps = _bit_to_bool(row.get("AllowGaps"), default=False)
            tc.exclude_from_hash = _parse_csv_list(row.get("ExcludeFromHash"))
            _dbd = row.get("DefaultBeginDate")
            tc.default_begin_date = str(_dbd) if _dbd is not None else None
            tc.force_new_segment_columns = _parse_csv_list(row.get("ForceNewSegmentColumns"))
            _retention = row.get("ExpectedRetentionDays")
            tc.expected_retention_days = int(_retention) if _retention is not None else None
            tc.last_modified_column = _none_if_blank(row.get("LastModifiedColumn"))

            # SS-1 — bare-name opt-in flag. _bit_to_bool handles the full
            # range pyodbc / ConnectorX may surface (int 0/1, bool, str).
            tc.strip_suffix = _bit_to_bool(row.get("StripSuffix"), default=False)

            # Per-table extraction-guard override. NULL → keep current behavior.
            _max_rows = row.get("MaxRowsPerDay")
            tc.max_rows_per_day = int(_max_rows) if _max_rows is not None else None

            # D63 + D125 per-table CDC mode dispatch. Defaults to
            # 'change_detect' when column is missing (pre-migration) OR
            # when value is NULL (defensive against malformed UdmTablesList
            # rows that bypass the CHECK constraint).
            _cdc_mode = row.get("CDCMode")
            tc.cdc_mode = str(_cdc_mode) if _cdc_mode is not None else "change_detect"

            # Set resolved schema casing from sys.schemas
            tc._resolved_stage_schema = schema_map.get((config.STAGE_DB, tc.source_name))
            tc._resolved_bronze_schema = schema_map.get((config.BRONZE_DB, tc.source_name))

            table_name = tc.effective_stage_name
            source_name = tc.source_name

            table_cols = columns_df.filter(
                (pl.col("SourceName") == source_name)
                & (pl.col("TableName") == table_name)
            )

            for col_row in table_cols.iter_rows(named=True):
                tc.columns.append(
                    ColumnConfig(
                        source_name=col_row["SourceName"],
                        table_name=col_row["TableName"],
                        column_name=col_row["ColumnName"],
                        ordinal_position=int(col_row["OrdinalPosition"]) if col_row["OrdinalPosition"] is not None else 0,
                        is_primary_key=bool(col_row["IsPrimaryKey"]),
                        layer=col_row["Layer"] or "",
                        is_index=bool(col_row.get("IsIndex")),
                        index_name=col_row.get("IndexName"),
                        index_type=col_row.get("IndexType"),
                    )
                )

            configs.append(tc)
        return configs

    def load_small_tables(self, source_name: str | None = None, table_name: str | None = None) -> list[TableConfig]:
        conditions = [
            "SourceAggregateColumnName IS NULL",
            # NoPK-2: Include both Python (CDC/SCD2) and Python-AppendOnly
            # (keyless tables — extract-and-append only, no CDC/SCD2).
            "StageLoadTool IN ('Python', 'Python-AppendOnly')",
        ]
        params: list = []
        if source_name:
            conditions.append("SourceName = ?")
            params.append(source_name)
        if table_name:
            conditions.append("SourceObjectName = ?")
            params.append(table_name)

        tables_df = self._load_tables_df(conditions, params or None)
        columns_df = self._load_columns_df()
        configs = self._build_configs(tables_df, columns_df)
        logger.info("Loaded %d small table configs", len(configs))
        return configs

    def load_large_tables(self, source_name: str | None = None, table_name: str | None = None) -> list[TableConfig]:
        conditions = [
            "SourceAggregateColumnName IS NOT NULL",
            "StageLoadTool IN ('Python', 'Python-AppendOnly')",
        ]
        params: list = []
        if source_name:
            conditions.append("SourceName = ?")
            params.append(source_name)
        if table_name:
            conditions.append("SourceObjectName = ?")
            params.append(table_name)

        tables_df = self._load_tables_df(conditions, params or None)
        columns_df = self._load_columns_df()
        configs = self._build_configs(tables_df, columns_df)
        logger.info("Loaded %d large table configs", len(configs))
        return configs

    def get_known_sources(self) -> set[str]:
        """H-4: Get all known source names from UdmTablesList for CLI validation."""
        df = cx.read_sql(
            self._uri,
            "SELECT DISTINCT SourceName FROM dbo.UdmTablesList",
            return_type="polars",
        )
        return set(df["SourceName"].to_list())

    def get_known_tables(self) -> set[str]:
        """H-4: Get all known table names from UdmTablesList for CLI validation."""
        df = cx.read_sql(
            self._uri,
            "SELECT DISTINCT SourceObjectName FROM dbo.UdmTablesList",
            return_type="polars",
        )
        return set(df["SourceObjectName"].to_list())