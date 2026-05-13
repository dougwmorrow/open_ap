"""Bulk-discover SCD2 config proposals for tables in ``UdmTablesList``.

Fills the R-2 configuration fields (``SCD2DateColumns``, ``ExcludeFromHash``,
``SourceDeleteDateColumn``, ``DuplicateResolutionOrder``, ``DefaultBeginDate``)
for hundreds of tables without manual per-table editing. Uses per-source
conventions from :mod:`schema.scd2_autoconfig` (DNA ``DATELASTMAINT``
exclusion, ``ADDDATE``/``EFFDATE`` waterfalls, ``INACTIVEDATE`` soft-delete,
etc.).

Never overwrites manual config. Every field where ``UdmTablesList`` already
holds a non-NULL value is left alone — the operator's explicit choice wins.

Two-phase workflow
------------------

1. **Discover (default):** scans ``UdmTablesColumnsList`` for Stage-layer
   column metadata per (source, table), calls :func:`propose_config`, and
   writes one row per (source, table, field) to
   ``General.dbo.UdmScd2ConfigProposal`` with ``Status = 'PENDING'``.

       python3 tools/detect_scd2_config.py --source DNA
       python3 tools/detect_scd2_config.py --all

   Review the proposals:

       SELECT * FROM General.dbo.UdmScd2ConfigProposal
       WHERE Status = 'PENDING'
       ORDER BY SourceName, TableName, FieldName;

   Mark rows APPROVED / REJECTED manually:

       UPDATE General.dbo.UdmScd2ConfigProposal
       SET Status = 'APPROVED'
       WHERE ProposalId IN (...);

2. **Apply:** copies only APPROVED rows into ``UdmTablesList`` and stamps
   ``AppliedAt``. Idempotent — re-running skips already-applied rows.

       python3 tools/detect_scd2_config.py --apply

Adding a new source
-------------------

Edit :mod:`schema.scd2_autoconfig` to add a ``SourceProfile`` entry. Then
``--source NEW_SOURCE``. Unknown sources fall through to ``GENERIC_FALLBACK``
which only proposes universal values (``DATELASTMAINT`` hash exclusion when
present, ``DefaultBeginDate='1900-01-01'``).
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections import defaultdict
from pathlib import Path

# Add parent directory for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import utils.configuration as config
from utils.connections import get_general_connection, quote_identifier
from schema.scd2_autoconfig import propose_config, get_profile

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# Field names in the proposal table. Order matters for reproducible diffs.
PROPOSAL_FIELDS = [
    "SCD2DateColumns",
    "ExcludeFromHash",
    "SourceDeleteDateColumn",
    "DuplicateResolutionOrder",
    "DefaultBeginDate",
    "LastModifiedColumn",
]


PROPOSAL_TABLE_DDL = """
IF NOT EXISTS (
    SELECT 1 FROM INFORMATION_SCHEMA.TABLES
    WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME = 'UdmScd2ConfigProposal'
)
CREATE TABLE dbo.UdmScd2ConfigProposal (
    ProposalId      BIGINT IDENTITY(1,1) PRIMARY KEY,
    SourceName      NVARCHAR(50)  NOT NULL,
    TableName       NVARCHAR(128) NOT NULL,
    FieldName       NVARCHAR(50)  NOT NULL,
    CurrentValue    NVARCHAR(MAX) NULL,
    ProposedValue   NVARCHAR(MAX) NULL,
    Reason          NVARCHAR(500) NULL,
    Status          NVARCHAR(20)  NOT NULL CONSTRAINT DF_UdmScd2ConfigProposal_Status DEFAULT 'PENDING',
    CreatedAt       DATETIME2(3)  NOT NULL CONSTRAINT DF_UdmScd2ConfigProposal_CreatedAt DEFAULT SYSDATETIME(),
    AppliedAt       DATETIME2(3)  NULL,
    CONSTRAINT UQ_UdmScd2ConfigProposal UNIQUE (SourceName, TableName, FieldName)
);
"""


def _ensure_proposal_table() -> None:
    conn = get_general_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(PROPOSAL_TABLE_DDL)
        cursor.close()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _load_tables_and_columns(
    source_filter: str | None,
    table_filter: str | None,
) -> tuple[
    dict[tuple[str, str], dict[str, str | None]],  # current config per (source, table)
    dict[tuple[str, str], set[str]],               # column names per (source, table)
]:
    """Load current UdmTablesList config + Stage column names per table."""
    current_cfg: dict[tuple[str, str], dict[str, str | None]] = {}
    cols_by_table: dict[tuple[str, str], set[str]] = defaultdict(set)

    # Current UdmTablesList values — include effective stage name so we can
    # join against UdmTablesColumnsList (which keys on StageTableName or
    # SourceObjectName).
    fields_csv = ", ".join(PROPOSAL_FIELDS)
    sql_tables = (
        f"SELECT SourceName, SourceObjectName, StageTableName, {fields_csv} "
        f"FROM dbo.UdmTablesList "
        f"WHERE StageLoadTool IN ('Python', 'Python-AppendOnly')"
    )
    tables_params: list = []
    if source_filter:
        sql_tables += " AND SourceName = ?"
        tables_params.append(source_filter)
    if table_filter:
        sql_tables += " AND SourceObjectName = ?"
        tables_params.append(table_filter)

    conn = get_general_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(sql_tables, *tables_params)
        rows = cursor.fetchall()
        table_name_by_key: dict[tuple[str, str], str] = {}
        for row in rows:
            source_name = row[0]
            source_obj = row[1]
            stage_name = row[2] or source_obj
            key = (source_name, source_obj)
            cfg = {
                fld: (row[3 + i] if row[3 + i] is not None else None)
                for i, fld in enumerate(PROPOSAL_FIELDS)
            }
            current_cfg[key] = cfg
            # UdmTablesColumnsList keys on the effective stage table name.
            table_name_by_key[key] = stage_name
        cursor.close()

        if not current_cfg:
            logger.warning(
                "No matching rows in UdmTablesList (filters: source=%s, table=%s).",
                source_filter, table_filter,
            )
            return current_cfg, cols_by_table

        # Columns — filter by Stage layer. Pull in one pass, index in memory.
        cursor = conn.cursor()
        col_sql = (
            "SELECT SourceName, TableName, ColumnName "
            "FROM dbo.UdmTablesColumnsList "
            "WHERE Layer = 'Stage'"
        )
        col_params: list = []
        if source_filter:
            col_sql += " AND SourceName = ?"
            col_params.append(source_filter)
        cursor.execute(col_sql, *col_params)
        stage_col_rows = cursor.fetchall()
        cursor.close()

        # Reverse-map stage name -> (source, source_obj) so we can bucket
        # columns by the original table key.
        name_lookup: dict[tuple[str, str], tuple[str, str]] = {
            (src, stage): key for key, stage in table_name_by_key.items()
            for src in [key[0]]
        }
        for source_name, table_name, column_name in stage_col_rows:
            lookup_key = (source_name, table_name)
            orig_key = name_lookup.get(lookup_key)
            if orig_key is None:
                # Columns might be keyed on the original source object name
                # instead of the stage name — try both.
                orig_key = (source_name, table_name)
                if orig_key not in current_cfg:
                    continue
            cols_by_table[orig_key].add(column_name)
    finally:
        conn.close()

    return current_cfg, cols_by_table


def _build_reason(
    field: str,
    proposed: str | None,
    source_name: str,
) -> str:
    profile = get_profile(source_name)
    if proposed is None:
        return f"{profile.source_name} profile has no match for {field}"
    return f"Proposed by {profile.source_name} profile (convention-based)"


def discover(
    source_filter: str | None,
    table_filter: str | None,
    dry_run: bool,
) -> tuple[int, int, int]:
    """Scan UdmTablesList + UdmTablesColumnsList and write PENDING proposals.

    Returns a tuple (proposals_written, fields_skipped_manual, tables_scanned).
    """
    _ensure_proposal_table()
    current_cfg, cols_by_table = _load_tables_and_columns(source_filter, table_filter)

    if not current_cfg:
        return (0, 0, 0)

    proposals_written = 0
    fields_skipped_manual = 0
    tables_scanned = 0

    conn = get_general_connection()
    try:
        cursor = conn.cursor()
        for (source_name, source_obj), current in current_cfg.items():
            column_names = cols_by_table.get((source_name, source_obj), set())
            if not column_names:
                logger.debug(
                    "No Stage columns found for %s.%s — skipping (run column sync?).",
                    source_name, source_obj,
                )
                continue
            tables_scanned += 1
            proposed_cfg = propose_config(source_name, column_names)

            for field, proposed_value in proposed_cfg.items():
                current_value = current.get(field)
                # Skip fields where manual config already exists.
                if current_value is not None:
                    fields_skipped_manual += 1
                    continue
                # Skip fields where the profile has nothing to suggest.
                if proposed_value is None:
                    continue

                reason = _build_reason(field, proposed_value, source_name)
                if dry_run:
                    logger.info(
                        "[DRY RUN] %s.%s %s: %s   (%s)",
                        source_name, source_obj, field, proposed_value, reason,
                    )
                else:
                    # MERGE upsert so re-running updates PENDING rows but
                    # preserves APPROVED/REJECTED decisions.
                    cursor.execute("""
                        MERGE dbo.UdmScd2ConfigProposal AS t
                        USING (SELECT ? AS SourceName, ? AS TableName, ? AS FieldName) AS s
                          ON  t.SourceName = s.SourceName
                          AND t.TableName  = s.TableName
                          AND t.FieldName  = s.FieldName
                        WHEN MATCHED AND t.Status = 'PENDING' THEN
                          UPDATE SET ProposedValue = ?, Reason = ?, CreatedAt = SYSDATETIME()
                        WHEN NOT MATCHED THEN
                          INSERT (SourceName, TableName, FieldName, CurrentValue, ProposedValue, Reason)
                          VALUES (?, ?, ?, ?, ?, ?);
                    """,
                        source_name, source_obj, field,
                        proposed_value, reason,
                        source_name, source_obj, field,
                        current_value, proposed_value, reason,
                    )
                proposals_written += 1
        if not dry_run:
            conn.commit()
        cursor.close()
    finally:
        conn.close()

    return proposals_written, fields_skipped_manual, tables_scanned


# ---------------------------------------------------------------------------
# Apply
# ---------------------------------------------------------------------------


def apply_approved(dry_run: bool) -> int:
    """Copy APPROVED proposal rows into UdmTablesList, mark AppliedAt.

    Idempotent — skips rows that already have AppliedAt set.
    """
    _ensure_proposal_table()

    conn = get_general_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT ProposalId, SourceName, TableName, FieldName, ProposedValue
            FROM dbo.UdmScd2ConfigProposal
            WHERE Status = 'APPROVED' AND AppliedAt IS NULL
            ORDER BY SourceName, TableName, FieldName
        """)
        rows = cursor.fetchall()
        cursor.close()

        if not rows:
            logger.info("No APPROVED proposals pending application.")
            return 0

        applied = 0
        for proposal_id, source_name, table_name, field_name, proposed_value in rows:
            # Validate field name against known list to prevent SQL injection
            # via unexpected identifiers.
            if field_name not in PROPOSAL_FIELDS:
                logger.warning(
                    "Proposal %d has unknown FieldName %r — skipping.",
                    proposal_id, field_name,
                )
                continue

            col = quote_identifier(field_name)
            update_sql = (
                f"UPDATE dbo.UdmTablesList SET {col} = ? "
                f"WHERE SourceName = ? AND SourceObjectName = ?"
            )

            if dry_run:
                logger.info(
                    "[DRY RUN] UPDATE %s.%s %s = %r",
                    source_name, table_name, field_name, proposed_value,
                )
                continue

            cursor = conn.cursor()
            cursor.execute(update_sql, proposed_value, source_name, table_name)
            affected = cursor.rowcount
            cursor.close()
            if affected == 0:
                logger.warning(
                    "Proposal %d: UPDATE affected 0 rows (%s.%s) — "
                    "UdmTablesList row missing. Marking applied anyway.",
                    proposal_id, source_name, table_name,
                )
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE dbo.UdmScd2ConfigProposal "
                "SET AppliedAt = SYSDATETIME() WHERE ProposalId = ?",
                proposal_id,
            )
            cursor.close()
            applied += 1
            logger.info(
                "Applied: %s.%s %s = %r",
                source_name, table_name, field_name, proposed_value,
            )

        if not dry_run:
            conn.commit()
        return applied
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", help="Only scan/apply this SourceName (e.g. DNA).")
    parser.add_argument("--table", help="Only scan this SourceObjectName (discover only).")
    parser.add_argument("--all", action="store_true",
                        help="Scan every source (omit --source).")
    parser.add_argument("--apply", action="store_true",
                        help="Copy APPROVED proposals into UdmTablesList.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would be written; do not persist.")
    args = parser.parse_args()

    if args.apply:
        if args.table or args.source or args.all:
            logger.warning(
                "--apply ignores --source/--table/--all. Applies every APPROVED "
                "row regardless of filters."
            )
        count = apply_approved(args.dry_run)
        logger.info("Applied %d proposals.", count)
        return 0

    if not args.source and not args.table and not args.all:
        parser.error("Specify --source, --all, or --apply.")

    written, skipped, scanned = discover(args.source, args.table, args.dry_run)
    logger.info(
        "Scanned %d tables. %d proposals %s. %d fields skipped "
        "(manual config already present).",
        scanned,
        written,
        "previewed" if args.dry_run else "written",
        skipped,
    )
    if not args.dry_run and written > 0:
        logger.info(
            "Review proposals: SELECT * FROM %s.dbo.UdmScd2ConfigProposal "
            "WHERE Status = 'PENDING' ORDER BY SourceName, TableName, FieldName.",
            config.GENERAL_DB,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
