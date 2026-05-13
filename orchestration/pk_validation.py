"""PK-1: Pre-flight PK validation + NoPK-1: Keyless table rejection.

PK-1:  Batch-level check at pipeline startup — queries UdmTablesColumnsList
       once for ALL tables in the batch and reports which ones are missing
       IsPrimaryKey=1 columns. Runs before any table processing begins.

NoPK-1: Per-table guard called before CDC/SCD2 — rejects tables with empty
        pk_columns with a clear error directing the operator to run
        discover_pks.py.

Both are non-blocking by default (skip the table, don't halt the pipeline)
so that tables WITH valid PKs still get processed.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from utils.connections import get_general_connection

if TYPE_CHECKING:
    from orchestration.table_config import TableConfig

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PK-1: Pre-flight batch validation
# ---------------------------------------------------------------------------

def validate_pks_preflight(configs: list[TableConfig]) -> list[TableConfig]:
    """PK-1: Check all tables in the batch have PK columns configured.

    Queries UdmTablesColumnsList ONCE for all tables and identifies any
    that have zero IsPrimaryKey=1 columns in the Stage layer.

    Tables missing PKs are logged at ERROR level with remediation guidance.
    They are NOT removed from the config list — downstream NoPK-1 guards
    in run_cdc_promotion / run_scd2_promotion will skip them individually.

    Args:
        configs: List of TableConfig objects for the batch.

    Returns:
        List of TableConfig objects that are MISSING PKs (for reporting).
        The caller can use this to log a summary or adjust behavior.
    """
    if not configs:
        return []

    # Build lookup of source_name -> set of table names
    table_keys = {
        (tc.source_name, tc.effective_stage_name)
        for tc in configs
    }

    # Single query: get all tables that DO have PKs
    conn = get_general_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT DISTINCT SourceName, TableName "
            "FROM dbo.UdmTablesColumnsList "
            "WHERE IsPrimaryKey = 1 AND Layer = 'Stage'"
        )
        tables_with_pks = {
            (row[0], row[1]) for row in cursor.fetchall()
        }
        cursor.close()
    finally:
        conn.close()

    # Identify tables missing PKs
    missing_pk_configs = []
    for tc in configs:
        key = (tc.source_name, tc.effective_stage_name)
        # Also check in-memory pk_columns — covers first-run tables
        # where UdmTablesColumnsList hasn't been populated yet
        if key not in tables_with_pks and not tc.pk_columns:
            missing_pk_configs.append(tc)

    if missing_pk_configs:
        missing_names = [
            f"{tc.source_name}.{tc.source_object_name}"
            for tc in missing_pk_configs
        ]
        logger.error(
            "PK-1: %d of %d tables have no PK columns configured in "
            "UdmTablesColumnsList (Stage layer). These tables will be "
            "SKIPPED during CDC/SCD2 processing. Missing PKs: [%s]. "
            "To fix: run 'python3 discover_pks.py --source <SOURCE>' to "
            "auto-discover PKs from source metadata, or manually set "
            "IsPrimaryKey=1 in General.dbo.UdmTablesColumnsList.",
            len(missing_pk_configs), len(configs),
            ", ".join(missing_names),
        )
    else:
        logger.info(
            "PK-1: All %d tables have PK columns configured — pre-flight OK",
            len(configs),
        )

    return missing_pk_configs


# ---------------------------------------------------------------------------
# NoPK-1: Per-table guard (called before CDC/SCD2)
# ---------------------------------------------------------------------------

class NoPrimaryKeyError(Exception):
    """NoPK-1: Raised when a table has no PK columns configured.

    Caught by process_small_table / process_large_table to skip the table
    gracefully while logging a clear remediation message.
    """


def require_pk_columns(table_config: TableConfig, step: str = "CDC/SCD2") -> None:
    """NoPK-1: Validate that pk_columns is non-empty before CDC/SCD2.

    Args:
        table_config: Table configuration to check.
        step: Human-readable step name for the error message.

    Raises:
        NoPrimaryKeyError: If pk_columns is empty or None.
    """
    if not table_config.pk_columns:
        raise NoPrimaryKeyError(
            f"NoPK-1: Table {table_config.source_name}."
            f"{table_config.source_object_name} has no PK columns configured "
            f"— cannot proceed with {step}. CDC joins on empty column lists "
            f"produce undefined behavior, SCD2 integrity checks will bail, "
            f"and UX_Active indexes can't enforce uniqueness. "
            f"To fix: run 'python3 discover_pks.py --source "
            f"{table_config.source_name} --table "
            f"{table_config.source_object_name}' or manually set "
            f"IsPrimaryKey=1 in General.dbo.UdmTablesColumnsList."
        )