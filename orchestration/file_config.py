"""FileConfig + FileConfigLoader from General.dbo.UDMFileExtract metadata.

Duck-type compatible with TableConfig — provides the same property interface
(source_object_name, stage_full_table_name, bronze_full_table_name, pk_columns,
index_configs, etc.) so all shared pipeline functions work without modification.

UPDATED: Added Silver/Gold table name support and TargetLayer routing.
Silver and Gold layers use truncate-and-reload (no CDC/SCD2 overhead).

FileConfig sources are Excel/CSV files from network drives, not databases.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

import utils.configuration as config
from utils.connections import get_general_connection, resolve_schema_name

logger = logging.getLogger(__name__)


@dataclass
class FileConfig:
    """Configuration for a file-based pipeline source.

    Duck-types the TableConfig interface so shared pipeline functions
    (run_cdc_promotion, run_scd2_promotion, ensure_stage_table, etc.)
    work without modification.
    """

    # --- Core identity ---
    source_name: str
    table_name: str

    # --- File location ---
    base_path: str
    file_pattern: str
    file_type: str  # 'xlsx', 'xls', 'csv', 'txt', 'json', 'ndjson'

    # --- File reading options ---
    sheet_name: str | None = None
    header_row: int = 0
    skip_rows: int = 0
    delimiter: str | None = None
    encoding: str = "utf-8"

    # --- Column mapping / selection ---
    column_mapping: dict[str, str] | None = None
    columns_to_extract: list[str] | None = None

    # --- Table naming overrides ---
    stage_table_name: str | None = None
    bronze_table_name: str | None = None
    silver_table_name: str | None = None
    gold_table_name: str | None = None

    # --- Primary keys (from UDMFileExtract.PrimaryKeyColumns) ---
    pk_column_names: list[str] = field(default_factory=list)

    # --- Change detection mode ---
    change_mode: str = "full_replace"  # 'full_replace' or 'append_only'

    # --- Target layer routing ---
    # Comma-separated string parsed into a set for fast lookup.
    # Valid values: 'Stage', 'Bronze', 'Silver', 'Gold'
    target_layers: set[str] = field(default_factory=lambda: {"Stage", "Bronze"})

    # --- Validation ---
    expected_frequency: str | None = None
    expected_min_rows: int | None = 1
    expected_columns: list[str] | None = None

    # --- Column metadata (from UdmTablesColumnsList, same as TableConfig) ---
    columns: list = field(default_factory=list)  # list[ColumnConfig]

    # --- SCD2 / CDC duck-type attributes ---
    # File sources don't carry these in UDMFileExtract today, so safe defaults
    # match the disabled / no-op semantics in cdc/engine.py and scd2/engine.py.
    # Adding them here (rather than scattering getattr() guards across the
    # shared pipeline) keeps the duck-type contract intact and prevents
    # silent failures when newer SCD2 features land. If a file source ever
    # needs to opt in (e.g. a CSV with DATELASTMAINT-style metadata),
    # promote the relevant field to a UDMFileExtract column and load it
    # from the row dict in _build_file_config().
    scd2_mode: str = "incremental"
    scd2_date_columns: list[str] | None = None
    source_delete_date_column: str | None = None
    duplicate_resolution_order: str | None = None
    allow_duplicates: bool = False
    preserve_datetime: bool = False
    repair_chain_after: bool = True
    allow_gaps: bool = False
    exclude_from_hash: list[str] | None = None
    default_begin_date: str | None = None
    force_new_segment_columns: list[str] | None = None
    expected_retention_days: int | None = None
    last_modified_column: str | None = None

    # --- Resolved schema casing from sys.schemas ---
    _resolved_stage_schema: str | None = None
    _resolved_bronze_schema: str | None = None
    _resolved_silver_schema: str | None = None
    _resolved_gold_schema: str | None = None

    # -----------------------------------------------------------------------
    # Layer routing helpers
    # -----------------------------------------------------------------------

    @property
    def targets_stage(self) -> bool:
        return "Stage" in self.target_layers

    @property
    def targets_bronze(self) -> bool:
        return "Bronze" in self.target_layers

    @property
    def targets_silver(self) -> bool:
        return "Silver" in self.target_layers

    @property
    def targets_gold(self) -> bool:
        return "Gold" in self.target_layers
    
    @property
    def exclude_columns(self) -> set[str]:
        """Duck-type compatibility with TableConfig — file sources have no excluded columns."""
        return set()

    # -----------------------------------------------------------------------
    # Duck-type properties matching TableConfig interface
    # -----------------------------------------------------------------------

    @property
    def source_object_name(self) -> str:
        """TableConfig compat: source object name used for logging, CSV naming, etc."""
        return self.table_name

    @property
    def effective_stage_name(self) -> str:
        return self.stage_table_name or self.table_name

    @property
    def effective_bronze_name(self) -> str:
        return self.bronze_table_name or self.table_name

    @property
    def effective_silver_name(self) -> str:
        return self.silver_table_name or self.table_name

    @property
    def effective_gold_name(self) -> str:
        return self.gold_table_name or self.table_name

    @property
    def stage_schema(self) -> str:
        return self._resolved_stage_schema or self.source_name

    @property
    def bronze_schema(self) -> str:
        return self._resolved_bronze_schema or self.source_name

    @property
    def silver_schema(self) -> str:
        return self._resolved_silver_schema or self.source_name

    @property
    def gold_schema(self) -> str:
        return self._resolved_gold_schema or self.source_name

    @property
    def stage_full_table_name(self) -> str:
        if self.stage_table_name:
            return f"{config.STAGE_DB}.{self.stage_schema}.{self.stage_table_name}"
        return f"{config.STAGE_DB}.{self.stage_schema}.{self.table_name}_cdc"

    @property
    def bronze_full_table_name(self) -> str:
        if self.bronze_table_name:
            return f"{config.BRONZE_DB}.{self.bronze_schema}.{self.bronze_table_name}"
        return f"{config.BRONZE_DB}.{self.bronze_schema}.{self.table_name}_scd2_python"

    @property
    def silver_full_table_name(self) -> str:
        """Full 3-part name for the Silver table. No _cdc/_scd2 suffix — clean names."""
        return f"{config.SILVER_DB}.{self.silver_schema}.{self.effective_silver_name}"

    @property
    def gold_full_table_name(self) -> str:
        """Full 3-part name for the Gold table. No _cdc/_scd2 suffix — clean names."""
        return f"{config.GOLD_DB}.{self.gold_schema}.{self.effective_gold_name}"

    @property
    def source_full_table_name(self) -> str:
        """Not applicable for file sources — returns a descriptive string."""
        return f"FILE:{self.base_path}/{self.file_pattern}"

    @property
    def is_large_table(self) -> bool:
        return False

    @property
    def pk_columns(self) -> list[str]:
        """PKs from UdmTablesColumnsList (after column sync), or fallback to pk_column_names."""
        from orchestration.table_config import ColumnConfig
        synced_pks = [
            c.column_name
            for c in self.columns
            if isinstance(c, ColumnConfig) and c.is_primary_key and c.layer == "Stage"
        ]
        if synced_pks:
            return synced_pks
        # Fallback: use pk_column_names from FileExtract before column sync runs
        return list(self.pk_column_names)

    @property
    def index_configs(self) -> list:
        """Index configs from UdmTablesColumnsList columns."""
        return [c for c in self.columns if hasattr(c, "is_index") and c.is_index]

    @property
    def is_oracle(self) -> bool:
        return False

    @property
    def is_sql_server(self) -> bool:
        return False

    @property
    def source_server(self) -> str:
        return ""

    @property
    def source_database(self) -> str:
        return ""

    @property
    def source_schema_name(self) -> str:
        return ""

    @property
    def uses_oracledb(self) -> bool:
        return False

    @property
    def source_index_hint(self) -> str | None:
        return None

    @property
    def partition_on(self) -> str | None:
        return None

    @property
    def source_aggregate_column_name(self) -> str | None:
        return None

    @property
    def source_aggregate_column_type(self) -> str | None:
        return None

    @property
    def first_load_date(self) -> str | None:
        return None

    @property
    def lookback_days(self) -> int | None:
        return None

    @property
    def stage_load_tool(self) -> str | None:
        return "Python"


class FileConfigLoader:
    """Loads file configs from General.dbo.UDMFileExtract.

    Uses pyodbc for all queries (H-3: parameterized queries prevent SQL injection).
    """

    def load_file_configs(
        self,
        source_name: str | None = None,
        table_name: str | None = None,
    ) -> list[FileConfig]:
        """Load file configurations from General.dbo.UDMFileExtract.

        Args:
            source_name: Optional filter by SourceName.
            table_name: Optional filter by TableName.

        Returns:
            List of FileConfig instances for active file sources.
        """
        conditions = ["IsActive = 1", "StageLoadTool = 'Python'"]
        params: list = []

        if source_name:
            conditions.append("SourceName = ?")
            params.append(source_name)
        if table_name:
            conditions.append("TableName = ?")
            params.append(table_name)

        where = " WHERE " + " AND ".join(conditions)
        query = (
            "SELECT FileExtractId, SourceName, TableName, BasePath, FilePattern, "
            "FileType, SheetName, HeaderRow, SkipRows, Delimiter, Encoding, "
            "ColumnMapping, ColumnsToExtract, StageTableName, BronzeTableName, "
            "SilverTableName, GoldTableName, "
            "PrimaryKeyColumns, ChangeMode, TargetLayer, "
            "ExpectedFrequency, ExpectedMinRows, ExpectedColumns "
            "FROM dbo.UDMFileExtract"
            + where
        )

        conn = get_general_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, *params)
            col_names = [desc[0] for desc in cursor.description]
            rows = cursor.fetchall()
            cursor.close()
        finally:
            conn.close()

        if not rows:
            logger.info("No file configs found matching filters")
            return []

        # Load column metadata from UdmTablesColumnsList
        columns_df = self._load_columns()

        # Resolve schema casing — now includes Silver and Gold databases
        unique_sources = {dict(zip(col_names, row))["SourceName"] for row in rows}
        schema_map = self._resolve_schemas(unique_sources)

        configs = []
        for row in rows:
            row_dict = dict(zip(col_names, row))
            fc = self._build_file_config(row_dict, schema_map)
            self._attach_columns(fc, columns_df)
            configs.append(fc)

        logger.info("Loaded %d file configs", len(configs))
        return configs

    def get_known_sources(self) -> set[str]:
        """H-4: Get all known source names from UDMFileExtract for CLI validation."""
        conn = get_general_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT SourceName FROM dbo.UDMFileExtract WHERE IsActive = 1")
            sources = {row[0] for row in cursor.fetchall()}
            cursor.close()
            return sources
        finally:
            conn.close()

    def get_known_tables(self) -> set[str]:
        """H-4: Get all known table names from UDMFileExtract for CLI validation."""
        conn = get_general_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT DISTINCT TableName FROM dbo.UDMFileExtract WHERE IsActive = 1")
            tables = {row[0] for row in cursor.fetchall()}
            cursor.close()
            return tables
        finally:
            conn.close()

    def _build_file_config(
        self,
        row: dict,
        schema_map: dict[tuple[str, str], str],
    ) -> FileConfig:
        """Build a FileConfig from a database row."""
        source_name = row["SourceName"]

        # Parse JSON columns safely
        column_mapping = _parse_json_dict(row.get("ColumnMapping"))
        columns_to_extract = _parse_json_list(row.get("ColumnsToExtract"))
        expected_columns = _parse_json_list(row.get("ExpectedColumns"))

        # Parse PrimaryKeyColumns as comma-separated list
        pk_raw = row.get("PrimaryKeyColumns", "")
        pk_column_names = [c.strip() for c in pk_raw.split(",") if c.strip()] if pk_raw else []

        # Parse TargetLayer as comma-separated set
        target_layer_raw = row.get("TargetLayer") or "Stage,Bronze"
        target_layers = {t.strip() for t in target_layer_raw.split(",") if t.strip()}

        fc = FileConfig(
            source_name=source_name,
            table_name=row["TableName"],
            base_path=row["BasePath"],
            file_pattern=row["FilePattern"],
            file_type=(row["FileType"] or "csv").lower(),
            sheet_name=row.get("SheetName"),
            header_row=int(row.get("HeaderRow") or 0),
            skip_rows=int(row.get("SkipRows") or 0),
            delimiter=row.get("Delimiter"),
            encoding=row.get("Encoding") or "utf-8",
            column_mapping=column_mapping,
            columns_to_extract=columns_to_extract,
            stage_table_name=row.get("StageTableName"),
            bronze_table_name=row.get("BronzeTableName"),
            silver_table_name=row.get("SilverTableName"),
            gold_table_name=row.get("GoldTableName"),
            pk_column_names=pk_column_names,
            change_mode=row.get("ChangeMode") or "full_replace",
            target_layers=target_layers,
            expected_frequency=row.get("ExpectedFrequency"),
            expected_min_rows=int(row["ExpectedMinRows"]) if row.get("ExpectedMinRows") is not None else 1,
            expected_columns=expected_columns,
        )

        # Set resolved schema casing for all four layers
        fc._resolved_stage_schema = schema_map.get((config.STAGE_DB, source_name))
        fc._resolved_bronze_schema = schema_map.get((config.BRONZE_DB, source_name))
        fc._resolved_silver_schema = schema_map.get((config.SILVER_DB, source_name))
        fc._resolved_gold_schema = schema_map.get((config.GOLD_DB, source_name))

        return fc

    def _resolve_schemas(self, source_names: set[str]) -> dict[tuple[str, str], str]:
        """Resolve schema casing from sys.schemas for all target databases.

        Caches results so we only query sys.schemas once per unique pair.
        Now includes Silver and Gold databases in addition to Stage and Bronze.
        """
        resolved: dict[tuple[str, str], str] = {}
        databases = [config.STAGE_DB, config.BRONZE_DB, config.SILVER_DB, config.GOLD_DB]
        for source_name in source_names:
            for database in databases:
                key = (database, source_name)
                if key not in resolved:
                    resolved[key] = resolve_schema_name(database, source_name)
        return resolved

    def _load_columns(self) -> list[tuple]:
        """Load all column metadata from UdmTablesColumnsList."""
        conn = get_general_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT SourceName, TableName, ColumnName, OrdinalPosition, "
                "IsPrimaryKey, Layer, IsIndex, IndexName, IndexType "
                "FROM dbo.UdmTablesColumnsList"
            )
            rows = cursor.fetchall()
            cursor.close()
            return rows
        finally:
            conn.close()

    def _attach_columns(self, fc: FileConfig, columns_df: list[tuple]) -> None:
        """Attach column metadata to a FileConfig instance."""
        from orchestration.table_config import ColumnConfig

        table_name = fc.effective_stage_name
        source_name = fc.source_name

        fc.columns = [
            ColumnConfig(
                source_name=row[0],
                table_name=row[1],
                column_name=row[2],
                ordinal_position=row[3],
                is_primary_key=bool(row[4]),
                layer=row[5],
                is_index=bool(row[6]) if row[6] is not None else False,
                index_name=row[7],
                index_type=row[8],
            )
            for row in columns_df
            if row[0] == source_name and row[1] == table_name
        ]


# ---------------------------------------------------------------------------
# JSON parsing helpers
# ---------------------------------------------------------------------------

def _parse_json_dict(value: str | None) -> dict[str, str] | None:
    """Parse a JSON string as a dict, returning None if empty or invalid."""
    if not value:
        return None
    try:
        parsed = json.loads(value)
        if isinstance(parsed, dict):
            return parsed
    except (json.JSONDecodeError, TypeError):
        logger.warning("Invalid JSON dict in UDMFileExtract: %s", value[:200])
    return None


def _parse_json_list(value: str | None) -> list[str] | None:
    """Parse a JSON string as a list, returning None if empty or invalid."""
    if not value:
        return None
    try:
        parsed = json.loads(value)
        if isinstance(parsed, list):
            return parsed
    except (json.JSONDecodeError, TypeError):
        logger.warning("Invalid JSON list in UDMFileExtract: %s", value[:200])
    return None
