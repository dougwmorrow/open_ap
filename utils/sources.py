"""Source system registry: Oracle (DNA) and SQL Server (CCM, EPICOR) connection factories.

OPT-B: SourceSystem provides credentials + source_type. Host and database
are overridable per-table via TableConfig values from UdmTablesList.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING
from urllib.parse import quote_plus
import oracledb
try:
    import configuration
except ImportError:
    from . import configuration
if TYPE_CHECKING:
    from orchestration.table_config import TableConfig


class SourceType(Enum):
    ORACLE = "ORACLE"
    SQL_SERVER = "SQL_SERVER"
    FILE = "FILE"


@dataclass(frozen=True)
class SourceSystem:
    name: str
    source_type: SourceType
    host: str
    port: int
    user: str
    password: str
    service_or_database: str

    def with_overrides(
        self,
        *,
        host: str | None = None,
        database: str | None = None,
    ) -> SourceSystem:
        """Return a new SourceSystem with overridden host and/or database.

        OPT-B: Allows per-table host/database from UdmTablesList (via
        TableConfig.source_server / TableConfig.source_database) while
        preserving credentials and source_type from the registry.

        Args:
            host: Override host. If None or empty, keeps registry default.
            database: Override database/service. If None or empty, keeps default.

        Returns:
            New SourceSystem with effective host/database.
        """
        return SourceSystem(
            name=self.name,
            source_type=self.source_type,
            host=host or self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            service_or_database=database or self.service_or_database,
        )

    def connectorx_uri(self) -> str:
        pwd = quote_plus(self.password)
        usr = quote_plus(self.user)
        if self.source_type == SourceType.ORACLE:
            return f"oracle://{usr}:{pwd}@{self.host}:{self.port}/{self.service_or_database}"
        return f"mssql://{usr}:{pwd}@{self.host}:{self.port}/{self.service_or_database}?TrustServerCertificate=true"

    def pyodbc_connection_string(self) -> str:
        """Build a pyodbc connection string for this source system.

        Uses self.host and self.service_or_database, which reflect
        UdmTablesList overrides when constructed via get_source_for_table()
        -> with_overrides(). Credentials come from the source registry
        (config.py env vars), since UdmTablesList does not store credentials.

        Used by _get_xml_columns in connectorx_sqlserver_extractor.py to
        query INFORMATION_SCHEMA.COLUMNS for XML column detection (E-7).

        Raises:
            ValueError: If called on an Oracle source.
        """
        if self.source_type == SourceType.ORACLE:
            raise ValueError(
                f"pyodbc_connection_string is not valid for Oracle source {self.name}. "
                "Use oracledb_connect_params() instead."
            )
        return (
            f"DRIVER={{{configuration.ODBC_DRIVER}}};"
            f"SERVER={self.host},{self.port};"
            f"DATABASE={self.service_or_database};"
            f"UID={self.user};"
            f"PWD={self.password};"
            "TrustServerCertificate=yes;"
        )

    def oracledb_connect_params(self) -> dict:
        if self.source_type != SourceType.ORACLE:
            raise ValueError(
                f"oracledb_connect_params only valid for Oracle sources, not {self.name}"
            )
        return {
            "user": self.user,
            "password": self.password,
            "dsn": oracledb.makedsn(host=self.host, port=self.port, service_name=self.service_or_database),
        }


# --- Source Registry (credentials + source_type authority) ---
_SOURCES: dict[str, SourceSystem] = {
    "DNA": SourceSystem(
        name="DNA",
        source_type=SourceType.ORACLE,
        host=configuration.ORACLE_HOST,
        port=configuration.ORACLE_PORT,
        user=configuration.ORACLE_USER,
        password=configuration.ORACLE_PASSWORD,
        service_or_database=configuration.ORACLE_SERVICE,
    ),
    "CCM": SourceSystem(
        name="CCM",
        source_type=SourceType.SQL_SERVER,
        host=configuration.CCM_SERVER_HOST,
        port=configuration.CCM_SERVER_PORT,
        user=configuration.CCM_SERVER_USER,
        password=configuration.CCM_SERVER_PASSWORD,
        service_or_database="CCM",
    ),
    "EPICOR": SourceSystem(
        name="EPICOR",
        source_type=SourceType.SQL_SERVER,
        host=configuration.EPICOR_SERVER_HOST,
        port=configuration.EPICOR_SERVER_PORT,
        user=configuration.EPICOR_SERVER_USER,
        password=configuration.EPICOR_SERVER_PASSWORD,
        service_or_database="EPICOR",
    ),
}


def get_source(name: str) -> SourceSystem:
    """Get source credentials + type from registry (no per-table overrides)."""
    key = name.upper()
    if key not in _SOURCES:
        raise ValueError(f"Unknown source: {name}. Available: {list(_SOURCES.keys())}")
    return _SOURCES[key]


def get_source_for_table(table_config: TableConfig) -> SourceSystem:
    """OPT-B: Get source with host/database overridden from TableConfig.

    UdmTablesList (SourceServer, SourceDatabase) becomes the single source
    of truth for where to connect. The registry provides credentials and
    source_type only.

    Empty/missing TableConfig values fall back to registry defaults, so
    existing tables that haven't set SourceServer/SourceDatabase continue
    to work unchanged.

    Args:
        table_config: Table configuration from UdmTablesList.

    Returns:
        SourceSystem with effective host/database for this specific table.
    """
    base = get_source(table_config.source_name)
    return base.with_overrides(
        host=table_config.source_server or None,
        database=table_config.source_database or None,
    )


def register_source(source: SourceSystem) -> None:
    """Register a new source system at runtime.

    Intended for programmatic source registration (e.g., loading sources from a
    config file or adding test fixtures). Not currently called by production code —
    all production sources are statically defined in _SOURCES above.
    """
    _SOURCES[source.name.upper()] = source