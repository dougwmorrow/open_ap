"""Configure AuditLog (CCM) + CARDTXN (DNA) for the bare-name
``StripSuffix`` convention.

Phase 1 of the legacy-pipeline migration: two large tables move off
the ``_cdc`` / ``_scd2_python`` naming so downstream consumers can
point at the bare names. ``StripSuffix = 1`` on both rows opts them in
without affecting any other table.

Operations
----------

**AuditLog (CCM) — new row**

* INSERT into ``General.dbo.UdmTablesList`` (idempotent — skips if a
  row already exists for SourceName='CCM' AND SourceObjectName='AuditLog').
* The actual CCM database is named ``CCMREPORT`` on the source server,
  so the row carries ``SourceDatabaseName = 'CCMREPORT'``. The legacy
  ``CCM`` alias is reserved for a different login.
* Resolves ``FirstLoadDate`` by querying the source for
  ``MIN([DateTime]) FROM dbo.AuditLog`` so backfill replays the full
  history starting from the earliest row. Pass
  ``--first-load-date YYYY-MM-DD`` to bypass the source query if the
  source is unreachable from the migration host.
* ``StripSuffix = 1`` → table names are
  ``UDM_Stage.ccm.AuditLog`` and ``UDM_Bronze.ccm.AuditLog`` (no
  ``_cdc`` / ``_scd2_python`` suffix).
* ``SourceServer`` is left NULL — operator populates the linked-server
  value directly in UdmTablesList after this migration runs.
* PK is ``ID``; the column-sync step on the first pipeline run will
  populate ``UdmTablesColumnsList`` from ``INFORMATION_SCHEMA.COLUMNS``
  and discover the PK from the source's primary-key constraint.

**CARDTXN (DNA) — existing row UPDATE**

* UPDATE the existing UdmTablesList row for SourceName='DNA' AND
  SourceObjectName='CARDTXN' so ``StageTableName='CARDTXN'``,
  ``BronzeTableName='CARDTXN'``, ``StripSuffix=1``.
* Idempotent — re-running is a no-op if the row already has those
  values.
* If ``UDM_Stage.dna.CARDTXN_cdc`` exists, ``sp_rename`` it to
  ``UDM_Stage.dna.CARDTXN`` (preserves the loaded data — no
  re-extraction of 214M rows). Same for Bronze. If the suffixed table
  doesn't exist (e.g. CARDTXN never finished its first load), the
  pipeline will create the bare-name table on the next run.
* Other CARDTXN config (FirstLoadDate, LookbackDays, SourceAggregate-
  ColumnName, etc.) is **not touched** — the existing values stay.

Prerequisites
-------------

1. Run ``migrations/strip_suffix_column.py`` first — adds the
   ``StripSuffix`` column to UdmTablesList.
2. The CCM source must be reachable from the migration host (uses
   the same ``utils.sources`` registry the pipeline uses).
3. Run ``--dry-run`` first to preview every operation.

Usage
-----

::

    # Prereq — once
    python3 migrations/strip_suffix_column.py

    # Path A — production: query source via linked server (typical)
    python3 migrations/audit_log_cardtxn_config.py \
        --linked-server PDCAAGDNA02 --dry-run
    python3 migrations/audit_log_cardtxn_config.py \
        --linked-server PDCAAGDNA02

    # Path B — operator already knows the earliest DateTime
    python3 migrations/audit_log_cardtxn_config.py \
        --first-load-date 2018-01-01 --dry-run
    python3 migrations/audit_log_cardtxn_config.py \
        --first-load-date 2018-01-01

    # Path C — direct ODBC to the source DB (only if migration host
    # has rights on the source server)
    python3 migrations/audit_log_cardtxn_config.py --dry-run
    python3 migrations/audit_log_cardtxn_config.py
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import utils.configuration as config
from utils.connections import get_connection

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

AUDITLOG_CONFIG = {
    "SourceObjectName": "AuditLog",
    "SourceName": "CCM",
    # SourceServer is left NULL — operator populates the linked-server
    # value directly in UdmTablesList after the INSERT.
    "SourceServer": "PDCAAGDNA02",
    # The actual CCM database is named ``CCMREPORT`` on the source
    # server (the legacy "CCM" alias resolves to a different login that
    # this migration host doesn't have rights on).
    "SourceDatabaseName": "CCMREPORT",
    "SourceSchemaName": "dbo",
    "StageTableName": "AuditLog",
    "BronzeTableName": "AuditLog",
    "SourceAggregateColumnName": "DateTime",
    "SourceAggregateColumnType": "DATETIME",
    "LookbackDays": 3,
    "StageLoadTool": "Python",
    "StripSuffix": 1,
}

CARDTXN_KEY = {"SourceName": "DNA", "SourceObjectName": "CARDTXN"}
CARDTXN_UPDATE = {
    "StageTableName": "CARDTXN",
    "BronzeTableName": "CARDTXN",
    "StripSuffix": 1,
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _check_strip_suffix_column_exists() -> bool:
    """Pre-flight: ``StripSuffix`` column must exist in UdmTablesList."""
    conn = get_connection(config.GENERAL_DB)
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT 1 FROM [{config.GENERAL_DB}].INFORMATION_SCHEMA.COLUMNS "
            f"WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'UdmTablesList' "
            f"AND COLUMN_NAME = 'StripSuffix'"
        )
        exists = cursor.fetchone() is not None
        cursor.close()
        return exists
    finally:
        conn.close()


def _row_exists(source_name: str, source_object: str) -> bool:
    conn = get_connection(config.GENERAL_DB)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM dbo.UdmTablesList "
            "WHERE SourceName = ? AND SourceObjectName = ?",
            source_name, source_object,
        )
        exists = cursor.fetchone() is not None
        cursor.close()
        return exists
    finally:
        conn.close()


def _query_min_datetime_from_source(linked_server: str | None) -> str | None:
    """Resolve ``FirstLoadDate`` from ``MIN([DateTime])`` on the source.

    Returns the value as an ISO-8601 string for use as FirstLoadDate.
    Returns None if the source query fails or AuditLog is empty.

    Two query paths:

    * ``linked_server`` provided → ``OPENQUERY([linked_server], ...)`` from
      the General DB. Use this when the migration host can't reach the
      source database directly via ODBC. The General DB already has the
      linked server configured (typical in environments with one
      reporting SQL Server that fans out to source servers).

    * ``linked_server`` is None → direct ODBC connect to
      ``AUDITLOG_CONFIG['SourceDatabaseName']`` via the source registry.
      Works when the migration host has rights on the source DB.

    The OPENQUERY path is preferred over 4-part naming
    (``[server].[db].[schema].[table]``) because OPENQUERY pushes the
    full query to the remote server — for an aggregate like ``MIN()``
    that means the remote does the work and only the scalar result
    crosses the network.
    """
    if linked_server:
        return _query_min_via_openquery(linked_server)
    return _query_min_via_direct_connection()


def _query_min_via_openquery(linked_server: str) -> str | None:
    """Run ``SELECT MIN([DateTime]) FROM AuditLog`` through ``OPENQUERY``
    against the General DB's linked-server ``linked_server``.

    The inner query is built from ``AUDITLOG_CONFIG`` constants so we
    never interpolate user input. SQL Server requires the OPENQUERY
    string to be a literal — it cannot be parameterized.
    """
    db_name = AUDITLOG_CONFIG["SourceDatabaseName"]
    schema = AUDITLOG_CONFIG["SourceSchemaName"]
    table = AUDITLOG_CONFIG["SourceObjectName"]
    date_col = AUDITLOG_CONFIG["SourceAggregateColumnName"]

    # Defense in depth: escape single quotes inside the inner query
    # string. None of the AUDITLOG_CONFIG values contain quotes today,
    # but if a future config change does, we don't want to silently
    # break the OPENQUERY parser.
    def _esc(value: str) -> str:
        return value.replace("'", "''")

    inner_sql = (
        f"SELECT MIN([{_esc(date_col)}]) AS min_dt "
        f"FROM [{_esc(db_name)}].[{_esc(schema)}].[{_esc(table)}]"
    )
    outer_sql = f"SELECT min_dt FROM OPENQUERY([{linked_server}], '{inner_sql}')"

    logger.info("Resolving MIN([%s]) via OPENQUERY on [%s]", date_col, linked_server)
    logger.debug("OPENQUERY SQL: %s", outer_sql)

    conn = get_connection(config.GENERAL_DB)
    try:
        cursor = conn.cursor()
        try:
            cursor.execute(outer_sql)
            row = cursor.fetchone()
            if not row or row[0] is None:
                logger.warning(
                    "MIN([%s]) returned NULL via OPENQUERY on [%s] — "
                    "table is empty? Skipping FirstLoadDate.",
                    date_col, linked_server,
                )
                return None
            return row[0].isoformat() if hasattr(row[0], "isoformat") else str(row[0])
        finally:
            cursor.close()
    finally:
        conn.close()


def _query_min_via_direct_connection() -> str | None:
    """Direct-ODBC fallback. Connects to
    ``AUDITLOG_CONFIG['SourceDatabaseName']`` via the source registry.

    Works only when the migration host has rights on the source DB.
    Most production environments need ``--linked-server`` instead.
    """
    from utils.sources import SourceType, get_source

    source = get_source("CCM")
    if source.source_type != SourceType.SQL_SERVER:
        logger.error(
            "CCM source is registered as %s — expected SQL_SERVER. "
            "Cannot query MIN([DateTime]).",
            source.source_type,
        )
        return None

    db_name = AUDITLOG_CONFIG["SourceDatabaseName"]

    from utils.connections import get_source_connection
    conn = get_source_connection(
        host=source.host,
        database=db_name,
        port=source.port,
    )
    try:
        cursor = conn.cursor()
        try:
            cursor.execute(
                f"SELECT MIN([{AUDITLOG_CONFIG['SourceAggregateColumnName']}]) "
                f"FROM [{AUDITLOG_CONFIG['SourceSchemaName']}]."
                f"[{AUDITLOG_CONFIG['SourceObjectName']}]"
            )
            row = cursor.fetchone()
            if not row or row[0] is None:
                logger.warning(
                    "MIN([DateTime]) returned NULL via direct connection — "
                    "table is empty? Skipping FirstLoadDate.",
                )
                return None
            return row[0].isoformat() if hasattr(row[0], "isoformat") else str(row[0])
        finally:
            cursor.close()
    finally:
        conn.close()


def _stage_or_bronze_table_exists(db: str, schema: str, table: str) -> bool:
    conn = get_connection(db)
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT 1 FROM [{db}].INFORMATION_SCHEMA.TABLES "
            f"WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?",
            schema, table,
        )
        exists = cursor.fetchone() is not None
        cursor.close()
        return exists
    finally:
        conn.close()


def _execute(db: str, sql: str, params: tuple = (), dry_run: bool = False) -> bool:
    if dry_run:
        logger.info("[DRY RUN] [%s] %s    params=%s", db, sql, params)
        return True
    conn = get_connection(db)
    try:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        cursor.close()
        return True
    except Exception:
        logger.exception("Failed: %s    params=%s", sql, params)
        return False
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Operations
# ---------------------------------------------------------------------------


def _insert_auditlog(
    dry_run: bool,
    first_load_date_override: str | None,
    linked_server: str | None,
) -> bool:
    """INSERT the AuditLog config row. Idempotent.

    Resolution precedence for ``FirstLoadDate``:

    1. ``--first-load-date`` (``first_load_date_override``) — used as-is,
       no source query.
    2. ``--linked-server`` — query the source via
       ``OPENQUERY([linked_server], ...)`` from the General DB. The
       typical production path when the migration host can't reach the
       source DB directly.
    3. Direct ODBC connect to the source — only works when the
       migration host has rights on the source DB.
    """
    if _row_exists(AUDITLOG_CONFIG["SourceName"], AUDITLOG_CONFIG["SourceObjectName"]):
        logger.info(
            "AuditLog row already in UdmTablesList — skipping INSERT. "
            "Update manually if config has drifted.",
        )
        return True

    if first_load_date_override:
        first_load_date = first_load_date_override
        logger.info(
            "Using --first-load-date override: %s (skipping source query)",
            first_load_date,
        )
    else:
        first_load_date = _query_min_datetime_from_source(linked_server)
        if first_load_date is None:
            bypass_hint = (
                "--first-load-date YYYY-MM-DD to bypass the source query"
                if linked_server
                else "--linked-server <name> to query via OPENQUERY, or "
                     "--first-load-date YYYY-MM-DD to bypass the source query"
            )
            logger.error(
                "Cannot determine FirstLoadDate for AuditLog. INSERT aborted. "
                "Either the source is unreachable or AuditLog is empty. "
                "Re-run with %s.",
                bypass_hint,
            )
            return False
        logger.info("Resolved FirstLoadDate from MIN([DateTime]): %s", first_load_date)

    sql = (
        "INSERT INTO dbo.UdmTablesList "
        "(SourceObjectName, SourceName, SourceServer, SourceDatabaseName, "
        " SourceSchemaName, StageTableName, BronzeTableName, "
        " SourceAggregateColumnName, SourceAggregateColumnType, "
        " FirstLoadDate, LookbackDays, StageLoadTool, StripSuffix) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    )
    params = (
        AUDITLOG_CONFIG["SourceObjectName"],
        AUDITLOG_CONFIG["SourceName"],
        AUDITLOG_CONFIG["SourceServer"],
        AUDITLOG_CONFIG["SourceDatabaseName"],
        AUDITLOG_CONFIG["SourceSchemaName"],
        AUDITLOG_CONFIG["StageTableName"],
        AUDITLOG_CONFIG["BronzeTableName"],
        AUDITLOG_CONFIG["SourceAggregateColumnName"],
        AUDITLOG_CONFIG["SourceAggregateColumnType"],
        first_load_date,
        AUDITLOG_CONFIG["LookbackDays"],
        AUDITLOG_CONFIG["StageLoadTool"],
        AUDITLOG_CONFIG["StripSuffix"],
    )
    return _execute(config.GENERAL_DB, sql, params, dry_run)


def _update_cardtxn(dry_run: bool) -> bool:
    """UPDATE the CARDTXN config row. Idempotent — no-op if already set."""
    if not _row_exists(CARDTXN_KEY["SourceName"], CARDTXN_KEY["SourceObjectName"]):
        logger.error(
            "CARDTXN row not found in UdmTablesList. The user said it was "
            "already configured — investigate before re-running this migration.",
        )
        return False

    sql = (
        "UPDATE dbo.UdmTablesList "
        "SET StageTableName = ?, BronzeTableName = ?, StripSuffix = ? "
        "WHERE SourceName = ? AND SourceObjectName = ?"
    )
    params = (
        CARDTXN_UPDATE["StageTableName"],
        CARDTXN_UPDATE["BronzeTableName"],
        CARDTXN_UPDATE["StripSuffix"],
        CARDTXN_KEY["SourceName"],
        CARDTXN_KEY["SourceObjectName"],
    )
    return _execute(config.GENERAL_DB, sql, params, dry_run)


def _rename_cardtxn_data_tables(dry_run: bool) -> bool:
    """``sp_rename`` existing ``CARDTXN_cdc`` / ``CARDTXN_scd2_python`` to
    bare names if they exist.

    Preserves loaded data — avoids a 214M-row re-extraction. If the
    suffixed tables don't exist (CARDTXN was truncated and not yet
    reloaded), no-op — the pipeline will create the bare-name tables
    on the next ``main_large_tables.py`` run.
    """
    ok = True

    renames = [
        # (db, schema, old_name, new_name)
        (config.STAGE_DB, "dna", "CARDTXN_cdc", "CARDTXN"),
        (config.BRONZE_DB, "dna", "CARDTXN_scd2_python", "CARDTXN"),
    ]

    for db, schema, old_name, new_name in renames:
        if not _stage_or_bronze_table_exists(db, schema, old_name):
            logger.info(
                "[%s.%s.%s] Does not exist — pipeline will create [%s.%s.%s] on next run.",
                db, schema, old_name, db, schema, new_name,
            )
            continue

        if _stage_or_bronze_table_exists(db, schema, new_name):
            logger.warning(
                "[%s.%s.%s] AND [%s.%s.%s] both exist. Refusing to "
                "sp_rename over an existing target. Inspect manually — "
                "drop the suffixed table if its data was already migrated, "
                "or drop the bare-name table if it was created in error.",
                db, schema, old_name, db, schema, new_name,
            )
            ok = False
            continue

        sql = (
            f"EXEC [{db}].sys.sp_rename "
            f"N'[{schema}].[{old_name}]', N'{new_name}', N'OBJECT'"
        )
        if not _execute(db, sql, (), dry_run):
            ok = False
        elif not dry_run:
            logger.info(
                "[%s.%s] Renamed %s -> %s — data preserved.",
                db, schema, old_name, new_name,
            )

    return ok


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview every INSERT / UPDATE / sp_rename without committing.")
    parser.add_argument(
        "--first-load-date", default=None,
        help=(
            "Optional override for AuditLog FirstLoadDate (YYYY-MM-DD or "
            "YYYY-MM-DDTHH:MM:SS). If omitted, the migration queries "
            "SELECT MIN([DateTime]) on the source. Use this when the "
            "source is unreachable from any path or the operator already "
            "knows the earliest DateTime."
        ),
    )
    parser.add_argument(
        "--linked-server", default=None,
        help=(
            "Linked-server name on the General DB to use for the "
            "MIN([DateTime]) query (e.g. 'PDCAAGDNA02'). When set, the migration "
            "runs OPENQUERY([linked_server], '...') from the General DB "
            "instead of connecting to the source directly. This is the "
            "typical production path when the migration host has rights "
            "on the General DB but not on the source DB."
        ),
    )
    args = parser.parse_args()

    if not _check_strip_suffix_column_exists():
        logger.error(
            "[%s.dbo.UdmTablesList] StripSuffix column missing. Run "
            "migrations/strip_suffix_column.py first.",
            config.GENERAL_DB,
        )
        return 1

    ok = True

    logger.info("=== Step 1/3: INSERT AuditLog (CCM) config ===")
    if not _insert_auditlog(args.dry_run, args.first_load_date, args.linked_server):
        ok = False

    logger.info("=== Step 2/3: UPDATE CARDTXN (DNA) config ===")
    if not _update_cardtxn(args.dry_run):
        ok = False

    logger.info("=== Step 3/3: sp_rename existing CARDTXN data tables (if any) ===")
    if not _rename_cardtxn_data_tables(args.dry_run):
        ok = False

    if ok:
        if args.dry_run:
            logger.info(
                "Dry-run complete. Re-run without --dry-run to apply.",
            )
        else:
            logger.info(
                "Migration complete. Next run of main_large_tables.py will "
                "use UDM_Stage.ccm.AuditLog, UDM_Bronze.ccm.AuditLog, "
                "UDM_Stage.dna.CARDTXN, UDM_Bronze.dna.CARDTXN.",
            )

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
