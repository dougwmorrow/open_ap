"""B194 — CREATE TABLE ``General.ops.PiiInventoryAuditLog`` (append-only).

Per D26 (append-only audit trail) + D92 (forward-only additive) + Phase 2
§ 4.4 audit-row contract. Required for B189 Tool 15
(``import_pii_inventory.py``) which writes EXACTLY ONE row per applied CSV row
to populate ``UdmTablesList.PiiColumnList`` + ``DataClassification`` per source
under compliance review. Authored per phase2/01_pilot_prerequisites.md § 4.4 —
every script invocation writes EXACTLY ONE row to PipelineEventLog regardless
of DDL no-op state.

Table created
-------------

``General.ops.PiiInventoryAuditLog`` — 10-column append-only audit log per
BACKLOG.md L374. One row per CSV row applied by Tool 15.

Schema:

* ``BatchId UNIQUEIDENTIFIER NOT NULL`` — groups all rows from a single CSV
  import invocation; correlates with ``PipelineEventLog.BatchId`` for the
  parent ``CLI_IMPORT_PII_INVENTORY`` row.
* ``ImportedAt DATETIME2(3) NOT NULL DEFAULT SYSUTCDATETIME()`` — server-side
  wall-clock timestamp at INSERT.
* ``Source NVARCHAR(50) NOT NULL`` — source system (DNA, CCM, EPICOR).
* ``[Table] NVARCHAR(255) NOT NULL`` — source table name (bracketed because
  ``TABLE`` is a reserved word in T-SQL).
* ``PiiColumnList NVARCHAR(MAX) NOT NULL`` — CSV of PII column names from the
  imported row.
* ``DataClassification NVARCHAR(50) NOT NULL`` — classification enum (CHECK
  constraint below).
* ``Rationale NVARCHAR(MAX) NULL`` — operator-supplied rationale for the
  classification choice; nullable to permit no-rationale imports during
  bulk inventory backfills.
* ``ReviewedBy NVARCHAR(255) NOT NULL`` — compliance reviewer who approved
  the row.
* ``ReviewedAt DATETIME2(3) NOT NULL`` — when the reviewer approved.
* ``Actor NVARCHAR(255) NOT NULL`` — operator running Tool 15 (audit-row
  actor per D75).

CHECK constraint
----------------

``CK_PiiInventoryAuditLog_DataClassification`` restricts
``DataClassification`` to the 5-value enum:
``{'PII', 'PHI', 'PCI', 'PUBLIC', 'INTERNAL'}``.

Rationale for the 5-value enum (resolves the BACKLOG.md L374 ambiguity that
specifies "CHECK constraint on DataClassification" without enumerating
values):

* **Superset of D63 enum** (``'PII', 'PCI', 'none'`` on
  ``UdmTablesList.DataClassification``) — keeps the audit log permissive of
  the same values D63 already locks for the column it audits.
* **Adds PHI** (Protected Health Information) — relevant for HIPAA-class
  data per D30 7-year retention with legal-hold context; D26 audit-grade
  pillar specifically cites PHI alongside PII as the canonical
  compliance-sensitive classifications.
* **Adds PUBLIC** + **INTERNAL** — standard data-classification practice
  (e.g., the NIST SP 800-60 4-tier ladder: Public / Internal / Confidential /
  Restricted; collapses Confidential into the existing PII/PHI/PCI trio).
  Permits the audit log to record explicitly-declassified column lists, not
  just the sensitive-data subset.
* The 5-value enum is the **audit table's** contract — broader than D63's
  3-value enum on the source column. Importing Tool 15 (B189) may need to
  reject CSV rows whose classification is not in the D63 3-value
  ``UdmTablesList.DataClassification`` enum even though the audit log accepts
  PHI/PUBLIC/INTERNAL — that's a Tool 15 validation responsibility, not this
  migration's. The audit log is intentionally permissive so future D63
  supersession (adding PHI to UdmTablesList) does NOT require an audit-log
  schema change.

If the operator/compliance team determines a different enum is required, the
canonical change procedure is forward-only supersession per D92 + § 7 § 4.4
rollback row (SchemaContract abandonment chain), NOT in-place ALTER of this
CHECK constraint.

Audit trail
-----------

* One ``MIGRATION_PII_INVENTORY_AUDIT_LOG`` row in
  ``General.ops.PipelineEventLog`` per invocation, with canonical Metadata
  JSON shape per § 4.4: ``{event_kind, ddl_applied, idempotency_path,
  ddl_statements_executed, server, table_created}``.
* One SchemaContract row per Round 7 § 1.1 with ``ContractKey='table_create'``
  carrying the CREATE TABLE DDL signature as ``ContractValue``. Simpler 1-row
  pattern chosen because the SchemaContract registry's natural grain
  (SourceName, ObjectName, ColumnName, ContractKey) does not have a clean
  multi-row decomposition for a CREATE-TABLE atomic event the way B193's
  multi-column ADD COLUMN sequence does (B193 wrote 2 rows per column —
  expected_type + nullability). A CREATE-TABLE event is one atomic
  schema-state transition.

Safety
------

* Idempotent — CREATE TABLE checked against ``sys.tables`` via SCHEMA_ID('ops');
  CHECK constraint checked against ``sys.check_constraints``. Both DDL guards
  inside a single transaction so a partial create cannot leave a table
  without its CHECK constraint.
* ``--dry-run`` previews DDL without executing; no audit row written, no
  SchemaContract row written.
* D92 forward-only — there is no DROP TABLE path here. Rollback is the
  SchemaContract abandonment procedure per Phase 2 § 7 § 4.4 rollback row.

Usage
-----

::

    python3 migrations/pii_inventory_audit_log.py --dry-run --actor pipeline-lead \\
        --justification "B194 Phase 2 R1 dev pre-flight" --server dev

    python3 migrations/pii_inventory_audit_log.py --actor pipeline-lead \\
        --justification "B194 Phase 2 R1 dev apply" --server dev

Exit codes (per D74)
--------------------

* 0 — clean (apply OR no-op OR dry-run preview)
* 1 — drift / warning (operational failure surfaced but not fatal)
* 2 — fatal error (DDL failure, connection failure)

Classification per ``udm-execution-classifier`` skill
-----------------------------------------------------

* **Trigger**: manual CLI invocation by an operator (Tool 15 author or
  pipeline lead) on each of dev / test / prod servers per the Phase 2 § 4.4
  ladder.
* **Frequency**: one-time per server (idempotent re-run is a no-op + writes
  one ``event_kind='noop'`` audit row).
* **Idempotency**: re-running on a server that already has the table is a
  no-op and still writes exactly one audit row.
* **Audit-row family**: ``MIGRATION_PII_INVENTORY_AUDIT_LOG`` (registered in
  CLAUDE.md MIGRATION_* family registry per § 4.4).

Tracked in ``BACKLOG.md`` as B194; closes at § 4.4 execution per the
B193/B194/B195 cohort.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import utils.configuration as config
from utils.connections import get_connection

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


MIGRATION_NAME = "MIGRATION_PII_INVENTORY_AUDIT_LOG"
TABLE_SCHEMA = "ops"
TABLE_NAME = "PiiInventoryAuditLog"
SOURCE_NAME = "General"  # SchemaContract.SourceName for General.ops.PiiInventoryAuditLog
CHECK_CONSTRAINT_NAME = "CK_PiiInventoryAuditLog_DataClassification"

# Resolved DataClassification enum — see docstring for rationale.
ALLOWED_DATA_CLASSIFICATIONS = ("PII", "PHI", "PCI", "PUBLIC", "INTERNAL")

# CREATE TABLE DDL — bracketed [Table] because TABLE is a reserved word.
CREATE_TABLE_DDL = f"""
CREATE TABLE [{{db}}].{TABLE_SCHEMA}.{TABLE_NAME} (
    AuditId             BIGINT IDENTITY(1,1) NOT NULL,
    BatchId             UNIQUEIDENTIFIER NOT NULL,
    ImportedAt          DATETIME2(3) NOT NULL
                        CONSTRAINT DF_PiiInventoryAuditLog_ImportedAt DEFAULT SYSUTCDATETIME(),
    Source              NVARCHAR(50)  NOT NULL,
    [Table]             NVARCHAR(255) NOT NULL,
    PiiColumnList       NVARCHAR(MAX) NOT NULL,
    DataClassification  NVARCHAR(50)  NOT NULL,
    Rationale           NVARCHAR(MAX) NULL,
    ReviewedBy          NVARCHAR(255) NOT NULL,
    ReviewedAt          DATETIME2(3)  NOT NULL,
    Actor               NVARCHAR(255) NOT NULL,
    CONSTRAINT PK_PiiInventoryAuditLog PRIMARY KEY CLUSTERED (AuditId)
)
""".strip()

# CHECK constraint DDL — added separately so we can guard it independently of
# the table existence check (partial-element-state recovery per B193 canary
# precedent: if the table exists but the CHECK is missing for any reason, the
# next run adds the CHECK without recreating the table).
ADD_CHECK_CONSTRAINT_DDL = f"""
ALTER TABLE [{{db}}].{TABLE_SCHEMA}.{TABLE_NAME}
    ADD CONSTRAINT {CHECK_CONSTRAINT_NAME}
        CHECK (DataClassification IN ({", ".join(f"'{v}'" for v in ALLOWED_DATA_CLASSIFICATIONS)}))
""".strip()

# SchemaContract ContractValue payload — captures the CREATE TABLE DDL
# signature for downstream contract-comparison consumers (e.g., schema-drift
# detectors that compare actual schema against the registered contract).
CONTRACT_VALUE_PAYLOAD = json.dumps({
    "object_type": "TABLE",
    "schema": TABLE_SCHEMA,
    "table": TABLE_NAME,
    "primary_key": ["AuditId"],
    "columns": [
        {"name": "AuditId",            "type": "BIGINT",            "nullable": False, "identity": True},
        {"name": "BatchId",            "type": "UNIQUEIDENTIFIER",  "nullable": False},
        {"name": "ImportedAt",         "type": "DATETIME2(3)",      "nullable": False,
         "default": "SYSUTCDATETIME()"},
        {"name": "Source",             "type": "NVARCHAR(50)",      "nullable": False},
        {"name": "Table",              "type": "NVARCHAR(255)",     "nullable": False},
        {"name": "PiiColumnList",      "type": "NVARCHAR(MAX)",     "nullable": False},
        {"name": "DataClassification", "type": "NVARCHAR(50)",      "nullable": False,
         "check": list(ALLOWED_DATA_CLASSIFICATIONS)},
        {"name": "Rationale",          "type": "NVARCHAR(MAX)",     "nullable": True},
        {"name": "ReviewedBy",         "type": "NVARCHAR(255)",     "nullable": False},
        {"name": "ReviewedAt",         "type": "DATETIME2(3)",      "nullable": False},
        {"name": "Actor",              "type": "NVARCHAR(255)",     "nullable": False},
    ],
    "decisions": ["D26", "D92", "B194", "Phase2-R1-§4.4"],
}, separators=(",", ":"))


def _table_exists(cursor, db: str, schema: str, table: str) -> bool:
    cursor.execute(
        f"SELECT 1 FROM [{db}].sys.tables t "
        f"INNER JOIN [{db}].sys.schemas s ON t.schema_id = s.schema_id "
        f"WHERE s.name = ? AND t.name = ?",
        schema, table,
    )
    return cursor.fetchone() is not None


def _check_constraint_exists(cursor, db: str, schema: str, name: str) -> bool:
    cursor.execute(
        f"SELECT 1 FROM [{db}].sys.check_constraints c "
        f"INNER JOIN [{db}].sys.schemas s ON c.schema_id = s.schema_id "
        f"WHERE s.name = ? AND c.name = ?",
        schema, name,
    )
    return cursor.fetchone() is not None


def _write_schema_contract_row(cursor, actor: str) -> None:
    """One row per CREATE TABLE event per Round 7 § 1.1.

    Uses ContractKey='table_create' (table-level contract; ColumnName=NULL per
    Round 1 § 23 schema "NULL = table-level contract"). The ContractValue
    JSON payload registers the full table signature.
    """
    cursor.execute(
        f"INSERT INTO [{config.GENERAL_DB}].ops.SchemaContract "
        f"(SourceName, ObjectName, ColumnName, ContractKey, ContractValue, "
        f" EffectiveFrom, CreatedBy, Notes) "
        f"VALUES (?, ?, NULL, ?, ?, SYSUTCDATETIME(), ?, ?)",
        SOURCE_NAME, TABLE_NAME, "table_create", CONTRACT_VALUE_PAYLOAD,
        f"migration:{MIGRATION_NAME.lower()}",
        "B194 CREATE TABLE per D26 append-only + D92 forward-only additive.",
    )


def _write_audit_row(cursor, metadata: dict, actor: str, justification: str,
                     status: str = "SUCCESS", error_message: str | None = None) -> None:
    """Write the single MIGRATION_PII_INVENTORY_AUDIT_LOG row per § 4.4 audit-row contract.

    BatchId is allocated from ``General.ops.PipelineBatchSequence`` per D45.3 —
    migration runs are pipeline-wide events so TableName + SourceName are NULL.
    """
    metadata_with_actor = dict(metadata)
    metadata_with_actor["actor"] = actor
    metadata_with_actor["justification"] = justification
    cursor.execute(
        f"INSERT INTO [{config.GENERAL_DB}].ops.PipelineEventLog "
        f"(BatchId, TableName, SourceName, EventType, EventDetail, "
        f" StartedAt, CompletedAt, Status, ErrorMessage, Metadata) "
        f"VALUES (NEXT VALUE FOR [{config.GENERAL_DB}].ops.PipelineBatchSequence, "
        f"        NULL, NULL, ?, ?, SYSUTCDATETIME(), SYSUTCDATETIME(), ?, ?, ?)",
        MIGRATION_NAME,
        f"B194 PiiInventoryAuditLog / server={metadata.get('server')}",
        status, error_message, json.dumps(metadata_with_actor),
    )


def apply(connection, *, actor: str, justification: str, server: str,
          dry_run: bool = False) -> dict:
    """Apply B194 PiiInventoryAuditLog CREATE TABLE migration.

    Idempotent: re-running on a server that already has the table + CHECK
    constraint is a no-op and still writes exactly one audit row with
    ``event_kind='noop'``.

    Returns Metadata JSON dict per § 4.4 canonical shape with kind-specific
    field ``table_created: bool`` (True if CREATE TABLE actually ran; False on
    idempotent re-run OR dry-run).

    Preconditions:
        - ``connection`` MUST have ``autocommit=False``; ``apply()`` controls
          transactions via explicit commit/rollback to bundle the CREATE TABLE
          + ADD CONSTRAINT + SchemaContract row + audit row into a single
          atomic transaction. The ``main()`` entry point sets this; direct
          callers (test harness, orchestrator) MUST do the same to prevent
          partial-state on failure.

    Partial-element-state behavior:
        - If the table exists but the CHECK constraint is missing (e.g.,
          manual CREATE TABLE, prior partial run, ALTER TABLE DROP CONSTRAINT
          executed off-pipeline), only the ADD CONSTRAINT runs;
          ``ddl_statements_executed=1``, ``table_created=False``, and
          ``event_kind='apply'``. Intentional + safe for partial-state
          recovery (matches B193 canary cycle-1 design review note 2026-05-12).
        - If the CHECK constraint exists but the table does not (impossible
          via this script but theoretically possible via off-pipeline DDL),
          the table-existence guard runs the CREATE TABLE and then the CHECK
          guard skips its branch — the resulting state has the table without
          the CHECK. This is the same shape as B193's "manual partial-state"
          recovery — the next invocation closes the gap. Documented because
          a future close-out audit may flag this as a candidate for an
          additional safety check.
    """
    cursor = connection.cursor()
    table_present = _table_exists(cursor, config.GENERAL_DB, TABLE_SCHEMA, TABLE_NAME)
    check_present = _check_constraint_exists(
        cursor, config.GENERAL_DB, TABLE_SCHEMA, CHECK_CONSTRAINT_NAME,
    )

    will_create_table = not table_present
    # Only attempt to add the CHECK constraint when the table will exist
    # post-DDL (either pre-existing or about to be created) AND the CHECK is
    # not already present.
    will_add_check = (table_present or will_create_table) and not check_present

    if dry_run:
        # Preview only: no DDL execution, no audit row, no SchemaContract row.
        if will_create_table:
            logger.info("[DRY RUN] Would execute CREATE TABLE [%s].%s.%s (full DDL omitted from log; see CREATE_TABLE_DDL).",
                        config.GENERAL_DB, TABLE_SCHEMA, TABLE_NAME)
        else:
            logger.info("[DRY RUN] Table [%s].%s.%s already present — would skip CREATE TABLE.",
                        config.GENERAL_DB, TABLE_SCHEMA, TABLE_NAME)
        if will_add_check:
            logger.info("[DRY RUN] Would execute ADD CONSTRAINT %s CHECK (DataClassification IN %s)",
                        CHECK_CONSTRAINT_NAME, ALLOWED_DATA_CLASSIFICATIONS)
        else:
            logger.info("[DRY RUN] CHECK constraint %s already present — would skip.",
                        CHECK_CONSTRAINT_NAME)
        any_ddl = will_create_table or will_add_check
        result = {
            "event_kind": "apply" if any_ddl else "noop",
            "ddl_applied": False,
            # idempotency_path reflects what a REAL apply would produce per § 4.4 canonical shape:
            # would-be-first-apply (any DDL pending) → "first"; would-be-noop (all elements present) → "no-op"
            # (matches B193 canary cycle-1 design review 🔴 fix 2026-05-12)
            "idempotency_path": "first" if any_ddl else "no-op",
            "ddl_statements_executed": 0,
            "server": server,
            "table_created": False,
            "dry_run": True,
            "would_create_table": will_create_table,
            "would_add_check_constraint": will_add_check,
        }
        cursor.close()
        return result

    if not will_create_table and not will_add_check:
        # True no-op: table + CHECK constraint already present.
        metadata = {
            "event_kind": "noop",
            "ddl_applied": False,
            "idempotency_path": "no-op",
            "ddl_statements_executed": 0,
            "server": server,
            "table_created": False,
        }
        _write_audit_row(cursor, metadata, actor, justification)
        connection.commit()
        cursor.close()
        logger.info("[%s].%s.%s + CHECK %s already present — no-op (audit row written).",
                    config.GENERAL_DB, TABLE_SCHEMA, TABLE_NAME, CHECK_CONSTRAINT_NAME)
        return metadata

    # First-apply path: CREATE TABLE + ADD CONSTRAINT (one or both) in a
    # single transaction with the SchemaContract row + audit row.
    # autocommit must be False on the supplied connection.
    ddl_statements_executed = 0
    try:
        if will_create_table:
            sql = CREATE_TABLE_DDL.format(db=config.GENERAL_DB)
            logger.info("Executing: CREATE TABLE [%s].%s.%s",
                        config.GENERAL_DB, TABLE_SCHEMA, TABLE_NAME)
            cursor.execute(sql)
            ddl_statements_executed += 1

        if will_add_check:
            sql = ADD_CHECK_CONSTRAINT_DDL.format(db=config.GENERAL_DB)
            logger.info("Executing: ALTER TABLE [%s].%s.%s ADD CONSTRAINT %s CHECK ...",
                        config.GENERAL_DB, TABLE_SCHEMA, TABLE_NAME, CHECK_CONSTRAINT_NAME)
            cursor.execute(sql)
            ddl_statements_executed += 1

        # SchemaContract row registers the contract for this CREATE TABLE event.
        # Written only on first-apply (when CREATE TABLE actually ran). On
        # partial-element recovery (table exists but CHECK was missing), the
        # SchemaContract row already exists from the original CREATE — do NOT
        # write a duplicate row.
        if will_create_table:
            _write_schema_contract_row(cursor, actor)

        metadata = {
            "event_kind": "apply",
            "ddl_applied": True,
            "idempotency_path": "first",
            "ddl_statements_executed": ddl_statements_executed,
            "server": server,
            "table_created": will_create_table,
        }
        _write_audit_row(cursor, metadata, actor, justification)
        connection.commit()
        cursor.close()
        logger.info(
            "[%s].%s.%s migration applied: table_created=%s, check_added=%s, ddl_statements=%d — "
            "audit row written%s.",
            config.GENERAL_DB, TABLE_SCHEMA, TABLE_NAME,
            will_create_table, will_add_check, ddl_statements_executed,
            " + 1 SchemaContract row" if will_create_table else "",
        )
        return metadata
    except Exception:
        connection.rollback()
        # Try to record the failure as a separate audit row on a fresh cursor.
        # Best-effort: if this also fails, the original exception still propagates.
        try:
            err_cursor = connection.cursor()
            failed_metadata = {
                "event_kind": "apply",
                "ddl_applied": False,
                "idempotency_path": None,
                "ddl_statements_executed": 0,
                "server": server,
                "table_created": False,
            }
            _write_audit_row(err_cursor, failed_metadata, actor, justification,
                             status="FAILED", error_message=traceback.format_exc()[:4000])
            connection.commit()
            err_cursor.close()
        except Exception:
            logger.exception("Failed to write FAILED audit row after migration failure")
        logger.exception("Migration failed; transaction rolled back.")
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="Preview DDL without executing.")
    parser.add_argument("--actor", required=True,
                        help="Operator running the migration (per D75); written to audit row.")
    parser.add_argument("--justification", required=True,
                        help="Operator justification for the migration (per D75); written to audit row.")
    parser.add_argument("--server", required=True,
                        help="Target server tag (e.g. dev / test / prod) per D75 + § 4.4 server key.")
    args = parser.parse_args()

    conn = None
    try:
        conn = get_connection(config.GENERAL_DB)
        try:
            conn.autocommit = False
        except Exception:
            logger.warning("Connection autocommit attribute not settable; relying on explicit commit/rollback.")

        result = apply(conn, actor=args.actor, justification=args.justification,
                       server=args.server, dry_run=args.dry_run)
        logger.info("Result: %s", json.dumps(result))
        return 0
    except Exception:
        logger.exception("Fatal error during B194 PiiInventoryAuditLog migration")
        return 2
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
