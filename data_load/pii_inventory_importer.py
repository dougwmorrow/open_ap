"""B189 — PII inventory importer module consumed by ``tools/import_pii_inventory.py``.

Per **phase1/04b_phase_0_closure_tools.md § 4** (Tool 15 canonical spec) +
**D6** (vault) + **D26** (append-only audit trail) + **D30** (retention) +
**D63** (``UdmTablesList`` canonical column inventory) + **D67** (Tier 0
discipline) + **D74** (CLI exit-code contract 0/1/2) + **D75** (argument
naming) + **D76** (audit-row contract; ``CLI_IMPORT_PII_INVENTORY`` family)
+ **D77** (Tier 0 6-canonical-assertion scaffold) + **D92** (forward-only
additive — NEW module function; no rename of locked R3 modules) + **D102**
(AES-256-GCM PiiVault context, downstream of this importer's output).

What this module does (per canonical spec § 4)
----------------------------------------------

Reads a CSV file per the canonical 7-column schema below, validates each row
against ``UdmTablesList`` (SourceName + TableName must exist) and the
``DataClassification`` enum, and (when ``dry_run=False``) UPDATEs
``UdmTablesList.PiiColumnList`` + ``DataClassification`` per row. Idempotent:
re-running with the same CSV produces NO ``UdmTablesList`` writes if values
are unchanged (value-equality compare before UPDATE). ``PiiInventoryAuditLog``
INSERTs are intentionally append-only per § 4 L134 audit-trail discipline.

CSV canonical schema (per § 4 L107-L114)
----------------------------------------

::

    SourceName,TableName,PiiColumnList,DataClassification,Rationale,ReviewedBy,ReviewedAt
    DNA,ACCT,"ACCT_NUMBER,SSN,CUST_EMAIL",PII,Customer PII per compliance review 2026-XX-XX,compliance-lead,2026-05-12
    DNA,CARDTXN,"CARD_NUMBER,CUST_EMAIL,POSTAL_CODE",PCI,Payment card data per PCI-DSS scoping,compliance-lead,2026-05-12

* ``PiiColumnList`` is a comma-separated list of column names within the
  source table that contain protected data; tokenized at extraction per the
  D6 vault flow.
* ``DataClassification`` is one of the 7-value enum per § 4 L116:
  ``{'PII', 'PCI', 'GLBA', 'SOX', 'INTERNAL', 'PUBLIC', 'NONE'}``.

Function signature
------------------

::

    import_pii_inventory(
        csv_path: str,
        *,
        reviewer: str | None = None,
        allow_unknown: bool = False,
        dry_run: bool = False,
        csv_reader=None,       # injected for tests; default reads from disk
        db_connection=None,    # injected for tests; default opens General DB
        actor: str | None = None,
        batch_id: str | None = None,
    ) -> ImportResult

Returns a frozen ``ImportResult`` dataclass per the spec contract.

Idempotency (per D15 + D26)
---------------------------

* Read-only on CSV.
* UPDATE-on-change on ``UdmTablesList`` — value-equality compare against the
  current row contents; UPDATE issued ONLY if (PiiColumnList,
  DataClassification) differ from existing values. Re-running the same CSV
  → zero UPDATEs.
* INSERT-only (append-only) on ``General.ops.PiiInventoryAuditLog`` — every
  applied CSV row produces one audit row regardless of whether the UPDATE
  was a no-op. Multi-invocation produces multiple audit rows; this is the
  audit trail discipline per § 4 L134.

Classification per ``udm-execution-classifier`` skill
-----------------------------------------------------

* **Trigger**: Manual CLI invocation by an operator (compliance lead).
* **Frequency**: One-time per CSV file (Manual × One-time per CSV per § 4
  L131 — "Operator-driven; never scheduled. Pipeline: NEVER").
* **Idempotency**: YES — UPDATE-on-change; append-only audit log; CSV
  re-import detects unchanged rows and skips UDMTL writes.
* **Audit-row family**: ``CLI_IMPORT_PII_INVENTORY`` (one row per CLI
  INVOCATION — NOT per CSV row; per § 4 L126).
* **Routing**: ``ONE_OFF_SCRIPTS.md`` "Active items" → "One-time operator
  tools" sub-table (manual × one-time per CSV input).

D-numbers consumed
------------------

D6, D15, D26, D30, D62, D63, D67, D74, D75, D76, D77, D92, D102, B185, B189,
B194.
"""

from __future__ import annotations

import csv
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
from typing import Any, Callable, Iterable

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants per § 4 canonical spec
# ---------------------------------------------------------------------------

# D76 EventType registered in CLAUDE.md CLI_* family registry.
EVENT_TYPE = "CLI_IMPORT_PII_INVENTORY"

# CLI exit-code constants per D74 contract.
EXIT_SUCCESS = 0
EXIT_WARNING = 1
EXIT_FATAL = 2

# Canonical CSV header per § 4 L110. Order is significant — operator-authored
# CSVs are expected to match this header exactly; mismatches surface as
# CsvParseError per § 4 error mode mapping.
CANONICAL_CSV_HEADER: tuple[str, ...] = (
    "SourceName",
    "TableName",
    "PiiColumnList",
    "DataClassification",
    "Rationale",
    "ReviewedBy",
    "ReviewedAt",
)

# Canonical DataClassification enum per § 4 L116. Matches D63
# `UdmTablesList.DataClassification` permitted values (NOTE: the B194
# `PiiInventoryAuditLog` CHECK constraint is intentionally permissive of a
# different 5-value enum {PII, PHI, PCI, PUBLIC, INTERNAL} per the B194
# migration rationale — the audit log enum is BROADER than the source-column
# enum it audits. This tool enforces the source-column 7-value enum on
# import; rows with PHI fail validation here even though the audit log
# would accept them).
ALLOWED_DATA_CLASSIFICATIONS: frozenset[str] = frozenset(
    {"PII", "PCI", "GLBA", "SOX", "INTERNAL", "PUBLIC", "NONE"},
)


# ---------------------------------------------------------------------------
# Exception hierarchy per § 4 error-mode mapping
# ---------------------------------------------------------------------------


class PiiInventoryImportError(Exception):
    """Base class for PII inventory import failures (per D68 hierarchy)."""


class CsvParseError(PiiInventoryImportError):
    """Raised when the CSV is malformed (header mismatch, missing columns,
    unreadable file). Per § 4 → exit 2 fatal."""


class InvalidDataClassificationError(PiiInventoryImportError):
    """Raised when a CSV row's ``DataClassification`` is not in
    ``ALLOWED_DATA_CLASSIFICATIONS``. Per § 4 → exit 2 fatal."""


class UnknownSourceTableError(PiiInventoryImportError):
    """Raised when a CSV row references a (SourceName, TableName) pair not
    present in ``UdmTablesList``. Per § 4 → exit 1 (skip + warning) when
    ``--allow-unknown`` is set; exit 2 fatal otherwise."""


class UdmTablesListNotWritable(PiiInventoryImportError):
    """Raised when the persistence layer rejects an UDMTL UPDATE (permissions
    / lock / connection failure). Per § 4 → exit 2 fatal."""


# ---------------------------------------------------------------------------
# Result dataclass per canonical signature
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ImportResult:
    """Frozen result of one ``import_pii_inventory()`` invocation per § 4 spec.

    Per the pre-spec'd test-fixture contract (B189 build authoring 2026-05-12):
    fields are frozen + named exactly as in the spec; new fields may be added
    forward-only per D92 but existing fields MUST NOT be renamed or removed.
    """

    csv_path: str
    rows_total: int
    rows_imported: int
    rows_skipped: int
    rows_failed: int
    errors: tuple[str, ...] = field(default_factory=tuple)  # per-row error msgs
    imported_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc).replace(tzinfo=None))

    def as_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dict for the CLI Metadata payload."""
        return {
            "csv_path": self.csv_path,
            "rows_total": self.rows_total,
            "rows_imported": self.rows_imported,
            "rows_skipped": self.rows_skipped,
            "rows_failed": self.rows_failed,
            "errors": list(self.errors),
            "imported_at": self.imported_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# CSV reader injection point (mocking-friendly per build prompt)
# ---------------------------------------------------------------------------


def _default_csv_reader(csv_path: str) -> tuple[tuple[str, ...], list[dict[str, str]]]:
    """Read a CSV file from disk; return (header_tuple, list_of_row_dicts).

    Wrapped so tests can inject a synthetic reader without touching the
    filesystem (per the build prompt's "mocking-friendly: inject csv-reader
    via parameters" directive).
    """
    path = Path(csv_path)
    if not path.exists():
        raise CsvParseError(f"CSV file not found: {csv_path}")
    try:
        text = path.read_text(encoding="utf-8-sig")  # tolerate BOM from Excel
    except OSError as exc:
        raise CsvParseError(f"Failed to read CSV file {csv_path}: {exc}") from exc

    return _parse_csv_text(text, csv_path)


def _parse_csv_text(
    text: str,
    csv_path: str,
) -> tuple[tuple[str, ...], list[dict[str, str]]]:
    """Parse a CSV text payload into (header, list_of_row_dicts).

    Public-ish helper used by both the default file reader and by tests that
    want to pass a string payload directly through the ``csv_reader``
    injection. Validates header shape; raises ``CsvParseError`` on drift.
    """
    try:
        buf = StringIO(text)
        reader = csv.reader(buf)
        rows = list(reader)
    except csv.Error as exc:
        raise CsvParseError(f"Malformed CSV {csv_path}: {exc}") from exc

    if not rows:
        raise CsvParseError(f"CSV is empty: {csv_path}")

    raw_header = tuple(col.strip() for col in rows[0])
    if raw_header != CANONICAL_CSV_HEADER:
        raise CsvParseError(
            f"CSV header mismatch in {csv_path}: "
            f"expected {CANONICAL_CSV_HEADER}, got {raw_header}"
        )

    parsed_rows: list[dict[str, str]] = []
    for line_idx, raw_row in enumerate(rows[1:], start=2):  # 1-based; header is line 1
        if not raw_row or all(not (cell or "").strip() for cell in raw_row):
            continue  # tolerate blank trailing lines
        if len(raw_row) < len(CANONICAL_CSV_HEADER):
            # Pad short rows with empty strings; downstream validation handles.
            raw_row = list(raw_row) + [""] * (len(CANONICAL_CSV_HEADER) - len(raw_row))
        elif len(raw_row) > len(CANONICAL_CSV_HEADER):
            raise CsvParseError(
                f"CSV row {line_idx} in {csv_path} has {len(raw_row)} columns; "
                f"expected {len(CANONICAL_CSV_HEADER)}"
            )
        row_dict = {
            CANONICAL_CSV_HEADER[i]: (raw_row[i] or "").strip()
            for i in range(len(CANONICAL_CSV_HEADER))
        }
        row_dict["_line_number"] = str(line_idx)  # for error messages
        parsed_rows.append(row_dict)

    return raw_header, parsed_rows


# ---------------------------------------------------------------------------
# DB-side helpers (injectable connection per build prompt)
# ---------------------------------------------------------------------------


def _open_default_connection():
    """Open a General DB connection via ``utils.connections.get_connection``.

    Local import so the module remains importable in Tier 0 environments
    where ``utils.connections`` may not be wired (Tier 0 tests inject a mock
    connection via the ``db_connection`` parameter).
    """
    try:
        import utils.configuration as config
        from utils.connections import get_connection
    except Exception as exc:  # noqa: BLE001
        raise UdmTablesListNotWritable(
            f"DB connection factory not importable: {exc}"
        ) from exc
    try:
        conn = get_connection(config.GENERAL_DB)
    except Exception as exc:  # noqa: BLE001
        raise UdmTablesListNotWritable(
            f"Failed to open General DB connection: {exc}"
        ) from exc
    try:
        conn.autocommit = False
    except Exception:  # noqa: BLE001
        logger.warning(
            "Connection autocommit not settable; relying on explicit commit/rollback.",
        )
    return conn


def _general_db_name() -> str:
    """Return the canonical General DB name; falls back to 'General' if utils
    is not importable (Tier 0 / synthetic test envs)."""
    try:
        import utils.configuration as config
        return config.GENERAL_DB
    except Exception:  # noqa: BLE001
        return "General"


def _udm_row_exists(cursor, db: str, source_name: str, table_name: str) -> bool:
    """Return True iff ``UdmTablesList`` has a row matching (source, table).

    Test envs MAY pre-stub the cursor to return a sentinel without hitting
    a live DB; production envs query the General DB.
    """
    cursor.execute(
        f"SELECT 1 FROM [{db}].dbo.UdmTablesList "
        f"WHERE SourceName = ? AND TableName = ?",
        source_name, table_name,
    )
    return cursor.fetchone() is not None


def _udm_current_values(
    cursor, db: str, source_name: str, table_name: str,
) -> tuple[str | None, str | None]:
    """Read current (PiiColumnList, DataClassification) for value-equality compare.

    Returns ``(None, None)`` if the row is missing (caller should have checked
    ``_udm_row_exists`` first; this is defensive).
    """
    cursor.execute(
        f"SELECT PiiColumnList, DataClassification "
        f"FROM [{db}].dbo.UdmTablesList "
        f"WHERE SourceName = ? AND TableName = ?",
        source_name, table_name,
    )
    row = cursor.fetchone()
    if row is None:
        return None, None
    return row[0], row[1]


def _udm_update(
    cursor, db: str,
    source_name: str, table_name: str,
    pii_column_list: str, data_classification: str,
) -> None:
    """UPDATE ``UdmTablesList`` SET PiiColumnList + DataClassification."""
    cursor.execute(
        f"UPDATE [{db}].dbo.UdmTablesList "
        f"SET PiiColumnList = ?, DataClassification = ? "
        f"WHERE SourceName = ? AND TableName = ?",
        pii_column_list, data_classification, source_name, table_name,
    )


def _audit_log_insert(
    cursor, db: str,
    *,
    batch_id: str,
    source_name: str,
    table_name: str,
    pii_column_list: str,
    data_classification: str,
    rationale: str | None,
    reviewed_by: str,
    reviewed_at: datetime,
    actor: str,
) -> None:
    """INSERT one row into ``General.ops.PiiInventoryAuditLog`` per applied CSV row.

    Per B194 migration schema:
    ``BatchId, ImportedAt (DEFAULT SYSUTCDATETIME), Source, [Table],
    PiiColumnList, DataClassification, Rationale, ReviewedBy, ReviewedAt, Actor``.
    """
    cursor.execute(
        f"INSERT INTO [{db}].ops.PiiInventoryAuditLog "
        f"(BatchId, Source, [Table], PiiColumnList, DataClassification, "
        f" Rationale, ReviewedBy, ReviewedAt, Actor) "
        f"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        batch_id,
        source_name,
        table_name,
        pii_column_list,
        data_classification,
        rationale,
        reviewed_by,
        reviewed_at,
        actor,
    )


# ---------------------------------------------------------------------------
# Row-level validation helpers
# ---------------------------------------------------------------------------


def _parse_reviewed_at(value: str, line_number: int) -> datetime:
    """Parse the ``ReviewedAt`` CSV cell into a UTC-naive datetime.

    Accepts ISO-8601 date (``YYYY-MM-DD``) or datetime (``YYYY-MM-DD HH:MM:SS``
    or ``YYYY-MM-DDTHH:MM:SSZ``). Falls back to None on unparseable values
    (caller decides whether None is acceptable).
    """
    if not value:
        return datetime.now(timezone.utc).replace(tzinfo=None).replace(tzinfo=None)
    formats = (
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%f",
        "%Y-%m-%dT%H:%M:%S.%fZ",
    )
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    # Last-resort fromisoformat (Python 3.11+ handles many edge cases)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed
    except ValueError as exc:
        raise CsvParseError(
            f"CSV row {line_number}: unparseable ReviewedAt value {value!r}"
        ) from exc


def _validate_row(
    row: dict[str, str],
    *,
    allow_unknown: bool,
    udm_exists_fn: Callable[[str, str], bool],
) -> tuple[bool, str | None]:
    """Validate a single parsed CSV row.

    Returns ``(is_valid, skip_reason_or_none)``:
    * ``(True, None)`` — row passes all validation
    * ``(False, "<reason>")`` — row should be skipped (unknown SourceName/
      TableName with allow_unknown=True)

    Raises:
        InvalidDataClassificationError — DataClassification not in enum
        UnknownSourceTableError — (Source, Table) missing in UDMTL AND
            allow_unknown=False
        CsvParseError — required field empty
    """
    line_no = row.get("_line_number", "?")
    source_name = row.get("SourceName", "").strip()
    table_name = row.get("TableName", "").strip()
    classification = row.get("DataClassification", "").strip()

    if not source_name:
        raise CsvParseError(f"CSV row {line_no}: SourceName is required")
    if not table_name:
        raise CsvParseError(f"CSV row {line_no}: TableName is required")
    if not classification:
        raise CsvParseError(f"CSV row {line_no}: DataClassification is required")

    if classification not in ALLOWED_DATA_CLASSIFICATIONS:
        raise InvalidDataClassificationError(
            f"CSV row {line_no}: DataClassification {classification!r} not in "
            f"allowed enum {sorted(ALLOWED_DATA_CLASSIFICATIONS)}"
        )

    # PiiColumnList may be empty for classifications like NONE / PUBLIC /
    # INTERNAL where there are no PII columns; ReviewedBy required for audit
    # row even when reviewer arg is passed.
    if not row.get("ReviewedBy", "").strip():
        # Caller-supplied --reviewer is checked by the CLI layer before passing
        # rows in (we don't have access to it here); empty ReviewedBy is a
        # row-level warning the CLI handles via the audit-row "actor" field.
        pass

    if not udm_exists_fn(source_name, table_name):
        if allow_unknown:
            return False, (
                f"Row {line_no}: unknown source/table {source_name}.{table_name} "
                f"in UdmTablesList (--allow-unknown=true; skipping)"
            )
        raise UnknownSourceTableError(
            f"Row {line_no}: unknown source/table {source_name}.{table_name} "
            f"in UdmTablesList (use --allow-unknown to skip instead of failing)"
        )

    return True, None


# ---------------------------------------------------------------------------
# Public entry point — canonical signature per spec
# ---------------------------------------------------------------------------


def import_pii_inventory(
    csv_path: str,
    *,
    reviewer: str | None = None,
    allow_unknown: bool = False,
    dry_run: bool = False,
    csv_reader: Callable[[str], tuple[tuple[str, ...], list[dict[str, str]]]] | None = None,
    db_connection: Any = None,
    actor: str | None = None,
    batch_id: str | None = None,
) -> ImportResult:
    """Read PII inventory CSV; validate; UPDATE ``UdmTablesList`` per row.

    Canonical signature per ``phase1/04b_phase_0_closure_tools.md`` § 4. The
    CLI shim ``tools/import_pii_inventory.py`` wraps this function and adds
    the ``CLI_IMPORT_PII_INVENTORY`` PipelineEventLog audit-row write at the
    invocation level.

    Parameters
    ----------
    csv_path:
        Path to the CSV per the canonical 7-column header. Read via the
        injected ``csv_reader`` (default reads from disk).
    reviewer:
        Operator-supplied reviewer NAME used when a CSV row's ``ReviewedBy``
        cell is empty (per § 4 L155 ``--reviewer`` arg semantics).
    allow_unknown:
        When True, rows whose (SourceName, TableName) pair is not in
        ``UdmTablesList`` are SKIPPED with a warning (counted in
        ``rows_skipped``) instead of raising. Per § 4 L157 ``--allow-unknown``.
    dry_run:
        When True, validates + reports but issues NO UDMTL UPDATEs and NO
        ``PiiInventoryAuditLog`` INSERTs. The returned ``ImportResult`` is
        identical in shape to a real run; ``rows_imported`` reflects what
        WOULD have been written. Per § 4 L156.
    csv_reader:
        Optional injection point — callable taking ``csv_path`` and returning
        ``(header_tuple, list_of_row_dicts)``. Default: ``_default_csv_reader``
        which reads from disk. Tests pass a stub that returns synthetic rows.
    db_connection:
        Optional injection point — pre-opened DB connection (pyodbc-style;
        must support ``.cursor()`` + ``.commit()`` + ``.rollback()``). Tests
        pass a MagicMock; production opens via ``utils.connections``.
    actor:
        Operator identity for the ``PiiInventoryAuditLog.Actor`` column. The
        CLI shim passes the validated ``--actor`` argument; programmatic
        callers SHOULD supply a meaningful value. Defaults to ``"unknown"``.
    batch_id:
        Optional pre-allocated BatchId (UUID string) correlating audit rows
        with the parent ``CLI_IMPORT_PII_INVENTORY`` PipelineEventLog row.
        Default: generate a fresh UUID per invocation.

    Returns
    -------
    ImportResult
        Frozen dataclass per canonical signature. ``rows_imported`` counts
        rows whose UDMTL values DIFFER from the CSV's values (actual UPDATEs);
        rows whose values already match are still SUCCESS but do not increment
        ``rows_imported`` (they increment a separate "rows_unchanged" tally
        carried in the ``errors`` list as informational entries).

    Raises
    ------
    CsvParseError
        Malformed CSV (header mismatch, unreadable file, row count drift, or
        unparseable ``ReviewedAt`` value).
    InvalidDataClassificationError
        Any CSV row's ``DataClassification`` is not in
        ``ALLOWED_DATA_CLASSIFICATIONS``.
    UdmTablesListNotWritable
        DB persistence failure (connection / permissions / transaction error).

    Idempotency (per D15 + D26)
    ---------------------------

    Re-running with an UNCHANGED CSV produces 0 UDMTL writes (value-equality
    compare) BUT N audit rows in ``PiiInventoryAuditLog`` — append-only audit
    trail per § 4 L134 is intentional. To suppress audit rows on re-runs, use
    ``dry_run=True``.
    """
    csv_reader_fn = csv_reader or _default_csv_reader
    effective_actor = actor or "unknown"
    effective_batch_id = batch_id or str(uuid.uuid4())
    db = _general_db_name()

    # 1. Read + parse CSV (raises CsvParseError on malformed input)
    _header, csv_rows = csv_reader_fn(csv_path)
    rows_total = len(csv_rows)
    errors: list[str] = []
    rows_imported = 0
    rows_skipped = 0
    rows_failed = 0

    if rows_total == 0:
        logger.info(
            "No CSV data rows in %s; returning zero-row ImportResult.", csv_path,
        )
        return ImportResult(
            csv_path=csv_path,
            rows_total=0,
            rows_imported=0,
            rows_skipped=0,
            rows_failed=0,
            errors=tuple(),
        )

    # 2. Open DB connection (injected for tests; default opens General)
    conn = db_connection if db_connection is not None else None
    owns_connection = False
    if conn is None and not dry_run:
        conn = _open_default_connection()
        owns_connection = True
    elif conn is None and dry_run:
        # Dry-run with no injected connection: still need UDMTL lookups to
        # validate rows. Open a read-only-ish connection if available;
        # otherwise raise CsvParseError so the operator knows the dry-run
        # cannot produce trustworthy output.
        try:
            conn = _open_default_connection()
            owns_connection = True
        except UdmTablesListNotWritable as exc:
            # Without DB access we cannot validate (Source, Table) existence.
            # Treat this as fatal so dry-run output is never misleading.
            raise UdmTablesListNotWritable(
                f"--dry-run requires DB read access for UdmTablesList "
                f"validation; failed to open connection: {exc}"
            ) from exc

    cursor = conn.cursor()

    def _udm_exists_closure(src: str, tbl: str) -> bool:
        return _udm_row_exists(cursor, db, src, tbl)

    try:
        # 3. Iterate rows; validate + (optionally) write
        for row in csv_rows:
            line_no = row.get("_line_number", "?")
            try:
                is_valid, skip_reason = _validate_row(
                    row,
                    allow_unknown=allow_unknown,
                    udm_exists_fn=_udm_exists_closure,
                )
            except InvalidDataClassificationError:
                # Per § 4 fatal — propagate after rolling back any in-flight tx.
                if not dry_run and owns_connection:
                    try:
                        conn.rollback()
                    except Exception:  # noqa: BLE001
                        pass
                raise
            except UnknownSourceTableError as exc:
                # allow_unknown=False path → fatal per § 4
                if not dry_run and owns_connection:
                    try:
                        conn.rollback()
                    except Exception:  # noqa: BLE001
                        pass
                raise
            except CsvParseError:
                if not dry_run and owns_connection:
                    try:
                        conn.rollback()
                    except Exception:  # noqa: BLE001
                        pass
                raise

            if not is_valid:
                rows_skipped += 1
                if skip_reason:
                    errors.append(skip_reason)
                continue

            source_name = row["SourceName"]
            table_name = row["TableName"]
            pii_column_list = row.get("PiiColumnList", "").strip()
            classification = row["DataClassification"]
            rationale = row.get("Rationale", "").strip() or None
            reviewed_by = row.get("ReviewedBy", "").strip() or reviewer or effective_actor
            reviewed_at = _parse_reviewed_at(
                row.get("ReviewedAt", "").strip(), int(line_no) if line_no.isdigit() else 0,
            )

            # 4. Idempotency check — value-equality compare against existing
            #    UDMTL row before issuing UPDATE.
            try:
                current_pii, current_class = _udm_current_values(
                    cursor, db, source_name, table_name,
                )
            except Exception as exc:  # noqa: BLE001
                rows_failed += 1
                err_msg = (
                    f"Row {line_no}: failed to read current UDMTL values for "
                    f"{source_name}.{table_name}: {type(exc).__name__}: {exc}"
                )
                logger.warning(err_msg)
                errors.append(err_msg)
                continue

            values_unchanged = (
                (current_pii or "") == pii_column_list
                and (current_class or "") == classification
            )

            try:
                if dry_run:
                    # Preview path: count would-be UPDATEs as rows_imported when
                    # values WOULD change; report unchanged rows as informational.
                    if not values_unchanged:
                        rows_imported += 1
                    else:
                        errors.append(
                            f"Row {line_no}: {source_name}.{table_name} values "
                            f"unchanged; would skip UDMTL UPDATE (dry-run preview)"
                        )
                else:
                    if not values_unchanged:
                        _udm_update(
                            cursor, db,
                            source_name, table_name,
                            pii_column_list, classification,
                        )
                        rows_imported += 1
                    else:
                        # No UDMTL write needed; still log informational.
                        errors.append(
                            f"Row {line_no}: {source_name}.{table_name} values "
                            f"unchanged; UDMTL UPDATE skipped (idempotent)"
                        )
                    # Audit row ALWAYS written on non-dry-run (per § 4 L134
                    # append-only audit trail).
                    _audit_log_insert(
                        cursor, db,
                        batch_id=effective_batch_id,
                        source_name=source_name,
                        table_name=table_name,
                        pii_column_list=pii_column_list,
                        data_classification=classification,
                        rationale=rationale,
                        reviewed_by=reviewed_by,
                        reviewed_at=reviewed_at,
                        actor=effective_actor,
                    )
            except Exception as exc:  # noqa: BLE001
                rows_failed += 1
                err_msg = (
                    f"Row {line_no}: persistence failed for "
                    f"{source_name}.{table_name}: {type(exc).__name__}: {exc}"
                )
                logger.warning(err_msg)
                errors.append(err_msg)

        # 5. Commit (or rollback in dry-run) the atomic batch.
        if not dry_run and rows_failed == 0:
            try:
                conn.commit()
            except Exception as exc:  # noqa: BLE001
                # Persistence-layer failure on commit → fatal per § 4
                try:
                    conn.rollback()
                except Exception:  # noqa: BLE001
                    pass
                raise UdmTablesListNotWritable(
                    f"Commit failed after {rows_imported} successful UDMTL writes: {exc}"
                ) from exc
        elif not dry_run and rows_failed > 0:
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass
            raise UdmTablesListNotWritable(
                f"{rows_failed} row(s) failed persistence; transaction rolled back "
                f"(see errors list for per-row details)"
            )
        else:
            # Dry run: roll back any read-only side effects.
            try:
                conn.rollback()
            except Exception:  # noqa: BLE001
                pass
    finally:
        try:
            cursor.close()
        except Exception:  # noqa: BLE001
            pass
        if owns_connection and conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    return ImportResult(
        csv_path=csv_path,
        rows_total=rows_total,
        rows_imported=rows_imported,
        rows_skipped=rows_skipped,
        rows_failed=rows_failed,
        errors=tuple(errors),
    )


__all__ = (
    "EVENT_TYPE",
    "EXIT_SUCCESS",
    "EXIT_WARNING",
    "EXIT_FATAL",
    "CANONICAL_CSV_HEADER",
    "ALLOWED_DATA_CLASSIFICATIONS",
    "PiiInventoryImportError",
    "CsvParseError",
    "InvalidDataClassificationError",
    "UnknownSourceTableError",
    "UdmTablesListNotWritable",
    "ImportResult",
    "import_pii_inventory",
)
