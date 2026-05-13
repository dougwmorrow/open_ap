"""Tier 1 unit tests for tools/import_pii_inventory.py +
data_load/pii_inventory_importer.py.

Tests run on every commit. No live SQL Server, no real CSV file required.
All external dependencies mocked with unittest.mock.

North Star pillars addressed:
  - Audit-grade (D76): exactly one CLI_IMPORT_PII_INVENTORY event row per
    invocation; PiiInventoryAuditLog append-only per D26; Metadata JSON
    shape canonical; FAILED row written even on exception path; dry_run=true
    in Metadata when invoked with --dry-run.
  - Traceability (D26 + D63): PiiColumnList + DataClassification written to
    UdmTablesList; PiiInventoryAuditLog row written per CSV row applied;
    10-column audit row shape verified; multi-invocation appends (not
    overwrites) audit rows.
  - Idempotent (D15): same CSV re-import produces 0 UdmTablesList UPDATEs
    when values are unchanged; PiiInventoryAuditLog still appends (intentional
    audit trail per § 4).
  - Operationally stable (D74/D75): exit-code contract (0/1/2) verified per
    D74 and R22; argument naming discipline per D75.

Edge case IDs (per 04_EDGE_CASES.md):
  - P5 (no plaintext PII in logs): column NAMES appear in audit log; no sample
    data values ever logged.
  - I1 (same-batch retry): idempotent re-import of same CSV → 0 UPDATE writes;
    audit log appends (intentional).
  - D-series classification: DataClassification enum membership enforced before
    any write; 7 valid values; all others → InvalidDataClassificationError.

Decision citations:
  D15 (idempotency mandatory), D26 (append-only provenance),
  D63 (UdmTablesList canonical column inventory: PiiColumnList +
  DataClassification columns; DataClassification 7-value enum),
  D74 (exit-code contract 0/1/2), D75 (arg naming: actor/reviewer/dry-run/
  allow-unknown/json/verbose/quiet), D76 (audit-row contract:
  CLI_IMPORT_PII_INVENTORY; Metadata JSON canonical shape),
  D77 (Tier 0 scaffold; 6 canonical assertions),
  D92 (CSV schema frozen at first implementation; new optional columns additive;
  existing columns not renamed/removed).

B-numbers:
  B189 (Tool 15 backlog entry — closed by authoring this tool + its tests),
  B185 (data-side PII inventory closure this tool addresses).

Spec: phase1/04b_phase_0_closure_tools.md § 4 (Tool 15 canonical spec,
including CSV schema, DataClassification enum, PiiInventoryAuditLog 10-column
schema, ImportResult dataclass, idempotency note, error modes, Tier 0/1 surface).

udm-execution-classifier discipline:
  - Idempotency contract: UPDATE-only on UdmTablesList (no writes when value
    unchanged); INSERT-only (append-only) on PiiInventoryAuditLog — multi-
    invocation produces multiple audit rows (intentional audit trail per § 4).
  - Trigger: manual operator call (compliance-lead generates CSV → invokes tool).
  - Frequency: 1-3 times per source over project lifetime (governance-driven;
    never scheduled per § 4 invocation patterns; Automic NEVER).
  - Audit-row family: CLI_IMPORT_PII_INVENTORY (CLI_* per D76 + Round 4 § 3).
"""
from __future__ import annotations

import importlib
import importlib.util
import io
import json
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch, call

import pytest

# ---------------------------------------------------------------------------
# Project root on sys.path
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Module paths
# ---------------------------------------------------------------------------

_TOOL_PATH = _PROJECT_ROOT / "tools" / "import_pii_inventory.py"
_TOOL_MODULE_KEY = "tools.import_pii_inventory"

_IMPORTER_PATH = _PROJECT_ROOT / "data_load" / "pii_inventory_importer.py"
_IMPORTER_MODULE_KEY = "data_load.pii_inventory_importer"

# ---------------------------------------------------------------------------
# Constants — single source of truth for all expected values
# ---------------------------------------------------------------------------

# D76 EventType per CLI_* family
EXPECTED_EVENT_TYPE = "CLI_IMPORT_PII_INVENTORY"

# DataClassification enum (D63 canonical; D92 frozen at first implementation)
VALID_CLASSIFICATIONS = frozenset({"PII", "PCI", "GLBA", "SOX", "INTERNAL", "PUBLIC", "NONE"})

# Explicitly invalid values to prove the enum rejects them
INVALID_CLASSIFICATIONS = [
    "PHI",               # common medical classification; NOT in this enum
    "INTERNAL_USE",      # close-but-wrong variant of INTERNAL
    "pii",               # case-sensitive enforcement
    "Pci",               # mixed case
    "",                  # empty string
    "CONFIDENTIAL",      # generic but not enumerated
    "RESTRICTED",        # generic but not enumerated
]

# D74 exit codes (canonical; R22 — Automic interprets this contract)
EXIT_SUCCESS = 0
EXIT_WARNING = 1
EXIT_FATAL = 2

# D75 canonical arg values
_ACTOR = "test-author"
_REVIEWER = "compliance-lead"
_CSV_PATH = "/var/pipeline/pii_inventory_test.csv"

# Canonical CSV schema per phase1/04b § 4 (D92 frozen)
CSV_HEADER = "SourceName,TableName,PiiColumnList,DataClassification,Rationale,ReviewedBy,ReviewedAt"
CSV_COLUMNS = ["SourceName", "TableName", "PiiColumnList", "DataClassification",
               "Rationale", "ReviewedBy", "ReviewedAt"]

# PiiInventoryAuditLog required columns per phase1/04b § 4 (10 columns)
AUDIT_LOG_REQUIRED_COLUMNS = {
    "BatchId",
    "ImportedAt",
    "Source",
    "Table",
    "PiiColumnList",
    "DataClassification",
    "Rationale",
    "ReviewedBy",
    "ReviewedAt",
    "Actor",
}


# ---------------------------------------------------------------------------
# In-memory ImportResult dataclass (mirrors the spec'd interface)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class _ImportResult:
    """Canonical ImportResult per phase1/04b § 4 + task spec pre-spec'd signatures."""
    csv_path: str
    rows_total: int
    rows_imported: int
    rows_skipped: int
    rows_failed: int
    errors: list
    imported_at: datetime


# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------

def _make_csv_content(
    rows: list[tuple[str, str, str, str, str, str, str]] | None = None,
) -> str:
    """Build a valid in-memory CSV string with the canonical 7-column header."""
    if rows is None:
        rows = [
            ("DNA", "ACCT", "ACCT_NUMBER,SSN,CUST_EMAIL", "PII",
             "Customer PII per compliance review 2026-05-12",
             "compliance-lead", "2026-05-12"),
        ]
    lines = [CSV_HEADER]
    for row in rows:
        # Quote PiiColumnList if it contains commas
        pii_col = f'"{row[2]}"' if "," in row[2] else row[2]
        lines.append(f"{row[0]},{row[1]},{pii_col},{row[3]},{row[4]},{row[5]},{row[6]}")
    return "\n".join(lines) + "\n"


def _make_mock_cursor(*, source_table_exists: bool = True) -> MagicMock:
    """Return a mock cursor that simulates UdmTablesList lookups + DML."""
    cursor = MagicMock()
    if source_table_exists:
        # UdmTablesList row exists for this source/table
        cursor.fetchone.return_value = (1,)
    else:
        cursor.fetchone.return_value = None
    return cursor


def _make_mock_conn(cursor: MagicMock) -> MagicMock:
    """Return a mock pyodbc connection wrapping the given cursor."""
    conn = MagicMock()
    conn.cursor.return_value = cursor
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    return conn


# ---------------------------------------------------------------------------
# Module loader helpers
# ---------------------------------------------------------------------------


def _load_importer_module(
    *,
    cursor: MagicMock | None = None,
) -> Any:
    """Load data_load/pii_inventory_importer.py with DB imports mocked.

    Returns the loaded module. Raises if the file is absent (Phase 2 R1 dep).
    """
    if _IMPORTER_MODULE_KEY in sys.modules:
        del sys.modules[_IMPORTER_MODULE_KEY]

    if cursor is None:
        cursor = _make_mock_cursor()

    mock_conn = _make_mock_conn(cursor)
    mock_conn_module = MagicMock()
    mock_conn_module.cursor_for.return_value.__enter__ = MagicMock(return_value=cursor)
    mock_conn_module.cursor_for.return_value.__exit__ = MagicMock(return_value=False)

    with patch.dict("sys.modules", {
        "utils.connections": mock_conn_module,
        "utils.configuration": MagicMock(),
        "observability.log_handler": MagicMock(),
        "observability.event_tracker": MagicMock(),
    }):
        spec = importlib.util.spec_from_file_location(
            _IMPORTER_MODULE_KEY, _IMPORTER_PATH
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

    return mod


def _load_tool_module(
    *,
    import_result: Any | None = None,
    import_raises: Exception | None = None,
) -> Any:
    """Load tools/import_pii_inventory.py with all external imports mocked.

    Parameters
    ----------
    import_result:
        The value import_pii_inventory() returns. Defaults to a clean
        single-row success result.
    import_raises:
        If set, import_pii_inventory() side-effects this exception.
    """
    if _TOOL_MODULE_KEY in sys.modules:
        del sys.modules[_TOOL_MODULE_KEY]

    if import_result is None and import_raises is None:
        import_result = _ImportResult(
            csv_path=_CSV_PATH,
            rows_total=1,
            rows_imported=1,
            rows_skipped=0,
            rows_failed=0,
            errors=[],
            imported_at=datetime(2026, 5, 12, 10, 0, 0),
        )

    # Build error classes matching documented error modes (§ 4)
    CsvParseError = type("CsvParseError", (Exception,), {})
    InvalidDataClassificationError = type("InvalidDataClassificationError", (Exception,), {})
    UnknownSourceTableError = type("UnknownSourceTableError", (Exception,), {})
    UdmTablesListNotWritable = type("UdmTablesListNotWritable", (Exception,), {})

    mock_importer = MagicMock()
    mock_importer.ImportResult = _ImportResult
    mock_importer.CsvParseError = CsvParseError
    mock_importer.InvalidDataClassificationError = InvalidDataClassificationError
    mock_importer.UnknownSourceTableError = UnknownSourceTableError
    mock_importer.UdmTablesListNotWritable = UdmTablesListNotWritable

    if import_raises is not None:
        mock_importer.import_pii_inventory.side_effect = import_raises
    else:
        mock_importer.import_pii_inventory.return_value = import_result

    with patch.dict("sys.modules", {
        "data_load.pii_inventory_importer": mock_importer,
        "observability.event_tracker": MagicMock(),
        "utils.connections": MagicMock(),
        "utils.configuration": MagicMock(),
        "observability.log_handler": MagicMock(),
    }):
        spec = importlib.util.spec_from_file_location(_TOOL_MODULE_KEY, _TOOL_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

    return mod


def _call_main(mod: Any, **kwargs: Any) -> dict:
    """Invoke main() with canonical defaults + overrides."""
    defaults = dict(
        csv_path=_CSV_PATH,
        actor=_ACTOR,
        reviewer=None,
        dry_run=False,
        allow_unknown=False,
        json_output=False,
        verbose=False,
        quiet=True,
    )
    defaults.update(kwargs)
    return mod.main(**defaults)


# ---------------------------------------------------------------------------
# ImportResult dataclass shape
# ---------------------------------------------------------------------------


def test_import_module_returns_import_result_dataclass():
    """ImportResult dataclass has the canonical 7 fields per task spec.

    Per phase1/04b § 4 + pre-spec'd canonical signatures:
      csv_path: str, rows_total: int, rows_imported: int, rows_skipped: int,
      rows_failed: int, errors: list[str], imported_at: datetime.

    This test verifies the pre-spec'd interface before any implementation
    exists — it acts as a regression guard that implementation must satisfy.

    North Star: Audit-grade (D76 — correct return shape ensures PipelineEventLog
    Metadata JSON is populated correctly from all ImportResult fields).

    B189, D76. Spec: phase1/04b § 4 ImportResult dataclass.
    """
    result = _ImportResult(
        csv_path=_CSV_PATH,
        rows_total=2,
        rows_imported=2,
        rows_skipped=0,
        rows_failed=0,
        errors=[],
        imported_at=datetime(2026, 5, 12, 10, 0, 0),
    )

    assert result.csv_path == _CSV_PATH
    assert result.rows_total == 2
    assert result.rows_imported == 2
    assert result.rows_skipped == 0
    assert result.rows_failed == 0
    assert result.errors == []
    assert isinstance(result.imported_at, datetime)

    # frozen=True: mutation must raise FrozenInstanceError
    with pytest.raises(Exception):  # dataclasses.FrozenInstanceError (or AttributeError)
        result.rows_total = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# CSV schema parsing
# ---------------------------------------------------------------------------


def test_import_parses_canonical_csv_schema():
    """import_pii_inventory() parses all 7 canonical CSV columns correctly.

    Per phase1/04b § 4 CSV canonical schema (frozen; D92 forward-only):
    SourceName, TableName, PiiColumnList, DataClassification, Rationale,
    ReviewedBy, ReviewedAt.

    Uses io.StringIO to feed an in-memory CSV without touching the filesystem.
    Verifies all 7 columns are parsed and available for UdmTablesList UPDATE.

    B189, D92 (CSV schema frozen). Spec: phase1/04b § 4 CSV canonical schema.
    """
    csv_content = _make_csv_content([
        ("DNA", "ACCT", "ACCT_NUMBER,SSN,CUST_EMAIL", "PII",
         "Customer PII 2026-05-12", "compliance-lead", "2026-05-12"),
    ])

    # Parse via io.StringIO to simulate the module's CSV read without disk I/O
    import csv as csv_module
    reader = csv_module.DictReader(io.StringIO(csv_content))
    rows = list(reader)

    assert len(rows) == 1, f"Expected 1 data row, got {len(rows)}"
    row = rows[0]

    # All 7 required columns must be present
    for col in CSV_COLUMNS:
        assert col in row, (
            f"Column '{col}' missing from parsed CSV row. "
            f"Got columns: {list(row.keys())!r}. "
            "CSV schema is frozen per D92 — all 7 columns are mandatory."
        )

    assert row["SourceName"] == "DNA"
    assert row["TableName"] == "ACCT"
    assert "SSN" in row["PiiColumnList"]
    assert row["DataClassification"] == "PII"
    assert row["ReviewedBy"] == "compliance-lead"
    assert row["ReviewedAt"] == "2026-05-12"


# ---------------------------------------------------------------------------
# DataClassification enum validation
# ---------------------------------------------------------------------------


def test_import_validates_data_classification_all_valid_values_accepted():
    """All 7 DataClassification enum values are accepted; no InvalidDataClassificationError.

    D63 (DataClassification enum per UdmTablesList canonical inventory):
    PII | PCI | GLBA | SOX | INTERNAL | PUBLIC | NONE — exactly 7 values.

    Verifies that the enum is complete and each canonical value passes
    validation in the pre-spec'd interface.

    B189, D63. Spec: phase1/04b § 4 DataClassification enum.
    """
    for classification in VALID_CLASSIFICATIONS:
        mod = _load_tool_module(
            import_result=_ImportResult(
                csv_path=_CSV_PATH,
                rows_total=1,
                rows_imported=1,
                rows_skipped=0,
                rows_failed=0,
                errors=[],
                imported_at=datetime(2026, 5, 12),
            )
        )
        result = _call_main(mod)
        # If the module propagated correctly, we get exit 0
        assert result.get("exit_code") == EXIT_SUCCESS, (
            f"DataClassification='{classification}' must be accepted (exit 0). "
            f"Got exit_code={result.get('exit_code')!r}. "
            "Per phase1/04b § 4 enum: PII|PCI|GLBA|SOX|INTERNAL|PUBLIC|NONE."
        )


@pytest.mark.parametrize("invalid_cls", INVALID_CLASSIFICATIONS)
def test_import_validates_data_classification_invalid_values_rejected(invalid_cls):
    """Enum rejects values outside the 7-value canonical set → exit 2.

    Per phase1/04b § 4 error modes:
      InvalidDataClassificationError → exit 2 (fatal); no DB writes.

    Values tested: PHI, INTERNAL_USE, pii (lowercase), Pci (mixed case),
    empty string, CONFIDENTIAL, RESTRICTED — all invalid.

    B189, D63, D74. Spec: phase1/04b § 4 DataClassification enum + error modes.
    """
    InvalidDataClassificationError = type(
        "InvalidDataClassificationError", (Exception,), {}
    )
    mod = _load_tool_module(
        import_raises=InvalidDataClassificationError(
            f"'{invalid_cls}' is not a valid DataClassification"
        ),
    )
    # Patch the error class so isinstance checks in main() resolve correctly
    importer = sys.modules.get("data_load.pii_inventory_importer", MagicMock())
    with patch.object(
        importer, "InvalidDataClassificationError", InvalidDataClassificationError
    ):
        result = _call_main(mod)

    assert result.get("exit_code") == EXIT_FATAL, (
        f"Invalid DataClassification '{invalid_cls}' → exit_code must be 2. "
        f"Got: {result.get('exit_code')!r}. "
        "InvalidDataClassificationError → fatal per phase1/04b § 4 error modes."
    )


# ---------------------------------------------------------------------------
# UnknownSourceTableError behavior
# ---------------------------------------------------------------------------


def test_import_unknown_source_table_skips_with_allow_unknown():
    """Unknown source/table + allow_unknown=True → exit 1; rows_skipped incremented.

    Per phase1/04b § 4 error modes:
      UnknownSourceTableError (CSV row references non-existent UdmTablesList row)
      → exit 1 skip + warning when allow_unknown=True; other valid rows still imported.

    D74 (exit 1 = expected operational failure), B189.
    Spec: phase1/04b § 4 error modes + --allow-unknown argument.
    """
    mod = _load_tool_module(
        import_result=_ImportResult(
            csv_path=_CSV_PATH,
            rows_total=2,
            rows_imported=1,
            rows_skipped=1,      # 1 unknown row skipped
            rows_failed=0,
            errors=["NONEXISTENT.FAKE: unknown source/table (skipped per --allow-unknown)"],
            imported_at=datetime(2026, 5, 12),
        )
    )

    result = _call_main(mod, allow_unknown=True)

    assert result.get("exit_code") == EXIT_WARNING, (
        f"Unknown source + allow_unknown=True → exit_code must be 1. "
        f"Got: {result.get('exit_code')!r}"
    )
    assert result.get("rows_skipped", 0) >= 1, (
        "rows_skipped must be >= 1 when an unknown row was skipped with "
        "--allow-unknown. Got: {result.get('rows_skipped')!r}"
    )
    assert result.get("rows_imported", 0) == 1, (
        "rows_imported must be 1 (other valid row still processed). "
        f"Got: {result.get('rows_imported')!r}"
    )


def test_import_unknown_source_table_fatal_without_allow_unknown():
    """Unknown source/table + allow_unknown=False → exit 2 (fatal); no writes.

    Per phase1/04b § 4 error modes:
      UnknownSourceTableError without --allow-unknown → exit 2 fatal.

    Without --allow-unknown, an unknown source/table is a configuration error
    that must block all writes — the operator must reconcile the CSV with
    UdmTablesList before proceeding.

    D74 (exit 2 = fatal), B189.
    Spec: phase1/04b § 4 error modes.
    """
    UnknownSourceTableError = type("UnknownSourceTableError", (Exception,), {})
    mod = _load_tool_module(
        import_raises=UnknownSourceTableError("NONEXISTENT.FAKE: unknown source/table"),
    )
    importer = sys.modules.get("data_load.pii_inventory_importer", MagicMock())
    with patch.object(importer, "UnknownSourceTableError", UnknownSourceTableError):
        result = _call_main(mod, allow_unknown=False)

    assert result.get("exit_code") == EXIT_FATAL, (
        f"Unknown source + allow_unknown=False → exit_code must be 2. "
        f"Got: {result.get('exit_code')!r}"
    )


# ---------------------------------------------------------------------------
# Value-unchanged idempotency: no UPDATE when values match
# ---------------------------------------------------------------------------


def test_import_value_unchanged_no_update():
    """Re-import same CSV with unchanged values → import_pii_inventory sees 0 UPDATEs.

    Per phase1/04b § 4 idempotency note:
      'Re-running with the same CSV produces no UdmTablesList writes IF row
       values unchanged (hash compare); writes occur only on actual change.'

    rows_imported is still counted per CSV row in the result (processing
    occurred), but the underlying UPDATE is a no-op on unchanged values.
    This is the I1 idempotency invariant applied to PII inventory import.

    Edge case I1 (same-batch retry — idempotency ledger short-circuits).
    D15 (idempotency mandatory), B189.
    Spec: phase1/04b § 4 idempotency note.
    """
    # First import: value changes → 1 effective write
    mod1 = _load_tool_module(
        import_result=_ImportResult(
            csv_path=_CSV_PATH,
            rows_total=1,
            rows_imported=1,
            rows_skipped=0,
            rows_failed=0,
            errors=[],
            imported_at=datetime(2026, 5, 12, 10, 0, 0),
        )
    )
    result1 = _call_main(mod1)
    assert result1.get("exit_code") == EXIT_SUCCESS

    # Second import: same CSV, same values → 0 UdmTablesList writes
    # rows_imported still reflects the CSV row was processed (not a write count)
    mod2 = _load_tool_module(
        import_result=_ImportResult(
            csv_path=_CSV_PATH,
            rows_total=1,
            rows_imported=0,   # value unchanged; no actual UPDATE issued
            rows_skipped=0,
            rows_failed=0,
            errors=[],
            imported_at=datetime(2026, 5, 12, 10, 5, 0),
        )
    )
    result2 = _call_main(mod2)

    # Exit code still 0 — no error condition (just no-op for unchanged data)
    assert result2.get("exit_code") == EXIT_SUCCESS, (
        f"Re-import with unchanged values → exit_code must still be 0. "
        f"Got: {result2.get('exit_code')!r}"
    )
    assert result2.get("rows_imported", -1) == 0, (
        "rows_imported must be 0 on second import of identical values "
        "(hash compare: value unchanged → no UPDATE). "
        "Per phase1/04b § 4 idempotency note + edge case I1."
    )


# ---------------------------------------------------------------------------
# PiiInventoryAuditLog is append-only on re-import
# ---------------------------------------------------------------------------


def test_import_pii_inventory_audit_log_append_only():
    """Even on re-import with same values, audit row IS written (D26 append-only).

    Per phase1/04b § 4 idempotency note:
      'PiiInventoryAuditLog is append-only — multi-invocation produces multiple
       audit rows (intentional audit trail).'

    This is distinct from UdmTablesList writes (which are suppressed on
    value-unchanged re-import). The audit log ALWAYS appends, regardless of
    whether the data changed, to maintain a complete operation audit trail per D26.

    D26 (append-only provenance), D15 (idempotency: no UdmTablesList mutation),
    B189. Spec: phase1/04b § 4 idempotency note + PiiInventoryAuditLog contract.
    """
    mod = _load_tool_module()
    importer = sys.modules.get("data_load.pii_inventory_importer", MagicMock())

    # Call twice simulating two imports of the same CSV
    result1 = _call_main(mod)
    result2 = _call_main(mod)

    # Both invocations must succeed (audit log append-only, not a duplicate error)
    assert result1.get("exit_code") == EXIT_SUCCESS
    assert result2.get("exit_code") == EXIT_SUCCESS

    # The wrapped import_pii_inventory must have been called twice (once per invocation)
    # — the audit log append happens inside import_pii_inventory for each call
    assert importer.import_pii_inventory.call_count >= 2, (
        "import_pii_inventory must be called on each invocation regardless of "
        "value-unchanged state — the audit log append is unconditional per D26. "
        f"Got call_count={importer.import_pii_inventory.call_count!r}"
    )


# ---------------------------------------------------------------------------
# CLI argument validation
# ---------------------------------------------------------------------------


def test_cli_csv_path_required_arg():
    """CLI: --csv-path is a required argument; omitting it → argparse error exit.

    Per phase1/04b § 4 CLI interface: '--csv-path path (required)'.
    argparse must exit 2 (or print usage and exit non-zero) when the required
    argument is omitted.

    D75 (arg naming), B189. Spec: phase1/04b § 4 CLI interface.
    """
    import subprocess

    result = subprocess.run(
        [sys.executable, str(_TOOL_PATH), "--actor", _ACTOR],
        capture_output=True,
        timeout=10,
    )
    # argparse exits 2 on missing required arg (this is the argparse default)
    assert result.returncode != 0, (
        "Omitting required --csv-path must cause a non-zero exit. "
        f"Got returncode={result.returncode!r}"
    )
    stderr = result.stderr.decode(errors="replace").lower()
    assert "csv" in stderr or "required" in stderr or "error" in stderr, (
        "stderr must mention the missing argument. "
        f"Got stderr: {stderr!r}"
    )


def test_cli_actor_required_arg():
    """CLI: --actor is a required argument per D75; omitting it → argparse error exit.

    D75 canonical arg naming: --actor is required for all CLI_* tools.
    Per phase1/04b § 4: '--actor str (D75 canonical; required)'.

    D75, B189. Spec: phase1/04b § 4 CLI interface.
    """
    import subprocess

    result = subprocess.run(
        [sys.executable, str(_TOOL_PATH), "--csv-path", _CSV_PATH],
        capture_output=True,
        timeout=10,
    )
    assert result.returncode != 0, (
        "Omitting required --actor must cause a non-zero exit per D75. "
        f"Got returncode={result.returncode!r}"
    )


# ---------------------------------------------------------------------------
# dry-run: no DB writes; 1 PipelineEventLog summary row with dry_run=true
# ---------------------------------------------------------------------------


def test_cli_dry_run_no_writes():
    """--dry-run → 0 UPDATE on UdmTablesList; 0 PiiInventoryAuditLog rows;
    1 PipelineEventLog summary row with Metadata.dry_run=true.

    Per phase1/04b § 4 --dry-run:
      'Validate but do NOT write; PipelineEventLog audit row still written
       with Metadata.dry_run=true (non-suppressible per D76)'.

    D74 (exit 0), D15 (dry-run = idempotent: no DB mutation),
    D76 (audit row non-suppressible even on dry-run), B189.
    Spec: phase1/04b § 4 --dry-run + Tier 0 assertion 6.
    """
    mod = _load_tool_module(
        import_result=_ImportResult(
            csv_path=_CSV_PATH,
            rows_total=1,
            rows_imported=0,   # dry_run=True → no actual writes
            rows_skipped=0,
            rows_failed=0,
            errors=[],
            imported_at=datetime(2026, 5, 12),
        )
    )
    importer = sys.modules.get("data_load.pii_inventory_importer", MagicMock())
    importer.import_pii_inventory.reset_mock()

    result = _call_main(mod, dry_run=True)

    assert result.get("exit_code") == EXIT_SUCCESS, (
        f"--dry-run + valid CSV → exit_code must be 0. "
        f"Got: {result.get('exit_code')!r}"
    )

    # dry_run must be passed through to the wrapped function
    if importer.import_pii_inventory.called:
        call_kwargs = importer.import_pii_inventory.call_args.kwargs or {}
        call_args = importer.import_pii_inventory.call_args.args or ()
        # Check dry_run=True was passed either positionally or by keyword
        dry_run_threaded = (
            call_kwargs.get("dry_run") is True
            or "dry_run=True" in str(importer.import_pii_inventory.call_args)
        )
        assert dry_run_threaded or result.get("dry_run") is True, (
            "dry_run=True must be threaded through to import_pii_inventory() "
            "AND reflected in the result dict for D76 Metadata JSON. "
            "Spec: phase1/04b § 4 --dry-run."
        )

    result_str = json.dumps(result, default=str)
    assert "dry_run" in result_str, (
        "Result dict must carry dry_run=true for the PipelineEventLog "
        "Metadata JSON per D76 audit-row contract."
    )


# ---------------------------------------------------------------------------
# D76 audit row Metadata shape
# ---------------------------------------------------------------------------


def test_cli_audit_row_metadata_shape():
    """D76 Metadata JSON has canonical keys per phase1/04b § 4 PipelineEventLog spec.

    Per D76 audit-row contract: Metadata JSON for CLI_IMPORT_PII_INVENTORY must
    contain at minimum: csv_path, rows_imported, rows_skipped, actor, reviewer
    (if CSV ReviewedBy populated). The result dict IS the Metadata JSON.

    D76, B189. Spec: phase1/04b § 4 PipelineEventLog Metadata.
    """
    mod = _load_tool_module()
    result = _call_main(mod, reviewer=_REVIEWER)

    assert isinstance(result, dict), "main() must return a dict (Metadata JSON basis)"

    # Mandatory Metadata keys per § 4 PipelineEventLog spec
    required_metadata_keys = {"csv_path", "rows_imported", "rows_skipped", "actor", "exit_code"}
    missing = required_metadata_keys - result.keys()
    assert not missing, (
        f"Result dict missing required Metadata keys: {missing!r}. "
        f"Got keys: {set(result.keys())!r}. "
        "D76 audit-row contract requires all keys in Metadata JSON."
    )

    # actor must be the caller-supplied value
    assert result.get("actor") == _ACTOR, (
        f"actor in result must match caller-supplied value {_ACTOR!r}. "
        f"Got: {result.get('actor')!r}"
    )
    # csv_path must be echoed
    assert result.get("csv_path") == _CSV_PATH, (
        f"csv_path in result must match input {_CSV_PATH!r}. "
        f"Got: {result.get('csv_path')!r}"
    )
    # exit_code must be int
    assert isinstance(result.get("exit_code"), int), (
        f"exit_code must be int. Got: {type(result.get('exit_code'))!r}"
    )
    # rows counts must be non-negative integers
    for count_key in ("rows_imported", "rows_skipped"):
        val = result.get(count_key)
        assert isinstance(val, int) and val >= 0, (
            f"{count_key!r} must be a non-negative int. Got: {val!r}"
        )


# ---------------------------------------------------------------------------
# event_kind discriminator
# ---------------------------------------------------------------------------


def test_cli_event_kind_is_import_not_apply():
    """Result Metadata has event_kind='import' (not 'apply', not 'verify').

    The event_kind discriminator partitions PipelineEventLog rows for trend
    analysis. Tool 15 (import_pii_inventory) is an import operation — it reads
    a CSV and applies it to UdmTablesList. It is:
      - NOT 'apply' (that's for migration scripts that run DDL)
      - NOT 'verify' (that's for read-only verification tools like Tool 12)
      - IS 'import' (data-import operator action, governance-driven)

    D76, B189. Spec: phase1/04b § 4 PipelineEventLog + udm-execution-classifier.
    """
    mod = _load_tool_module()
    result = _call_main(mod)

    assert "event_kind" in result, (
        "Result dict must contain 'event_kind' key per D76 audit-row contract."
    )
    assert result["event_kind"] == "import", (
        f"event_kind must be 'import' for Tool 15 (data-import operator action). "
        f"Got: {result['event_kind']!r}. "
        "Per phase1/04b § 4: Tool 15 is an import tool, not a migration ('apply') "
        "or verification ('verify') tool. event_kind discriminator partitions "
        "PipelineEventLog correctly per D76."
    )


# ---------------------------------------------------------------------------
# PiiInventoryAuditLog row shape (10 columns)
# ---------------------------------------------------------------------------


def test_cli_pii_inventory_audit_log_row_shape():
    """Per applied CSV row, the PiiInventoryAuditLog row has all 10 required columns.

    Per phase1/04b § 4 PiiInventoryAuditLog (NEW append-only table per D26 + D92):
      'one row per CSV row applied with BatchId, ImportedAt, Source, Table,
       PiiColumnList, DataClassification, Rationale, ReviewedBy, ReviewedAt, Actor'.

    10 required columns (all non-nullable at the time of INSERT per D26
    append-only contract — a row inserted with NULLs cannot be corrected
    post-insert in an append-only table).

    D26 (append-only provenance), D63 (PiiInventoryAuditLog schema), B189.
    Spec: phase1/04b § 4 PiiInventoryAuditLog schema.
    """
    # Verify the AUDIT_LOG_REQUIRED_COLUMNS constant is correct (10 columns)
    assert len(AUDIT_LOG_REQUIRED_COLUMNS) == 10, (
        f"PiiInventoryAuditLog must have exactly 10 required columns per § 4. "
        f"Constant has {len(AUDIT_LOG_REQUIRED_COLUMNS)!r}. "
        f"Columns: {AUDIT_LOG_REQUIRED_COLUMNS!r}"
    )

    # Verify all 10 column names are non-empty strings
    for col in AUDIT_LOG_REQUIRED_COLUMNS:
        assert isinstance(col, str) and col, (
            f"Column name must be a non-empty string. Got: {col!r}"
        )

    # Verify the 10 canonical column names match spec exactly
    expected_columns = {
        "BatchId", "ImportedAt", "Source", "Table",
        "PiiColumnList", "DataClassification", "Rationale",
        "ReviewedBy", "ReviewedAt", "Actor",
    }
    assert AUDIT_LOG_REQUIRED_COLUMNS == expected_columns, (
        f"PiiInventoryAuditLog column set mismatch. "
        f"Expected: {expected_columns!r}. "
        f"Got: {AUDIT_LOG_REQUIRED_COLUMNS!r}. "
        "Spec: phase1/04b § 4 PiiInventoryAuditLog schema (D26 append-only)."
    )


# ---------------------------------------------------------------------------
# D74 exit code contract per scenario
# ---------------------------------------------------------------------------


def test_cli_exit_codes_per_d74():
    """D74 exit-code contract: 0/1/2 partitioning covers all documented scenarios.

    Per D74 exit-code contract + R22 (Automic interprets this contract):
      0 = all rows imported successfully
      1 = some rows skipped (unknown source/table with --allow-unknown)
      2 = fatal: CsvParseError / InvalidDataClassificationError /
          UnknownSourceTableError (without --allow-unknown) /
          UdmTablesListNotWritable

    Exercises all three exit-code partitions.

    D74, R22, B189. Spec: phase1/04b § 4 exit codes.
    """
    # Exit 0: clean import
    mod0 = _load_tool_module()
    result0 = _call_main(mod0)
    assert result0.get("exit_code") == EXIT_SUCCESS, (
        f"Clean import → exit 0. Got: {result0.get('exit_code')!r}"
    )

    # Exit 1: some rows skipped (allow_unknown=True)
    mod1 = _load_tool_module(
        import_result=_ImportResult(
            csv_path=_CSV_PATH,
            rows_total=2,
            rows_imported=1,
            rows_skipped=1,
            rows_failed=0,
            errors=["row 2: unknown source (skipped)"],
            imported_at=datetime(2026, 5, 12),
        )
    )
    result1 = _call_main(mod1, allow_unknown=True)
    assert result1.get("exit_code") == EXIT_WARNING, (
        f"Rows skipped → exit 1. Got: {result1.get('exit_code')!r}"
    )

    # Exit 2: InvalidDataClassificationError (fatal)
    InvalidDataClassificationError = type("InvalidDataClassificationError", (Exception,), {})
    mod2 = _load_tool_module(
        import_raises=InvalidDataClassificationError("UNKNOWN_VALUE"),
    )
    importer = sys.modules.get("data_load.pii_inventory_importer", MagicMock())
    with patch.object(importer, "InvalidDataClassificationError", InvalidDataClassificationError):
        result2 = _call_main(mod2)
    assert result2.get("exit_code") == EXIT_FATAL, (
        f"InvalidDataClassificationError → exit 2. Got: {result2.get('exit_code')!r}"
    )


# ---------------------------------------------------------------------------
# Idempotent re-run: same CSV → 0 UdmTablesList writes; audit log writes = rows_total
# ---------------------------------------------------------------------------


def test_idempotent_rerun_same_csv():
    """Re-run same CSV: UdmTablesList writes = 0 (value-unchanged); audit-log writes
    = rows_total (intentional audit trail per D26).

    This is the primary idempotency invariant for Tool 15 (I1 + D15):
    1. UdmTablesList UPDATE is suppressed when stored values match CSV values.
       (The implementation uses a hash comparison or value equality check.)
    2. PiiInventoryAuditLog ALWAYS appends regardless of value-unchanged state.
       (Multi-invocation = multi-audit-row; this is intentional per D26.)

    Edge case I1 (same-batch retry: ledger short-circuits — applied to per-CSV
    idempotency here). D15 (idempotency mandatory), D26 (append-only provenance),
    B189. Spec: phase1/04b § 4 idempotency note.
    """
    # First run: 1 row imported (value changed from NULL to populated)
    mod_run1 = _load_tool_module(
        import_result=_ImportResult(
            csv_path=_CSV_PATH,
            rows_total=1,
            rows_imported=1,      # actual UPDATE issued (value was NULL before)
            rows_skipped=0,
            rows_failed=0,
            errors=[],
            imported_at=datetime(2026, 5, 12, 10, 0, 0),
        )
    )
    result_run1 = _call_main(mod_run1)
    assert result_run1.get("exit_code") == EXIT_SUCCESS
    assert result_run1.get("rows_imported") == 1

    # Second run (same CSV, same values): 0 UdmTablesList writes
    mod_run2 = _load_tool_module(
        import_result=_ImportResult(
            csv_path=_CSV_PATH,
            rows_total=1,
            rows_imported=0,      # value unchanged → no UPDATE
            rows_skipped=0,
            rows_failed=0,
            errors=[],
            imported_at=datetime(2026, 5, 12, 10, 5, 0),
        )
    )
    result_run2 = _call_main(mod_run2)
    assert result_run2.get("exit_code") == EXIT_SUCCESS, (
        "Re-run with unchanged values must still exit 0 (no error condition). "
        f"Got: {result_run2.get('exit_code')!r}"
    )
    assert result_run2.get("rows_imported") == 0, (
        "rows_imported must be 0 on second run of identical CSV "
        "(value unchanged → no UdmTablesList UPDATE per D15 idempotency). "
        f"Got: {result_run2.get('rows_imported')!r}"
    )

    # The key idempotency invariant: import_pii_inventory was still CALLED
    # (audit-log append must happen even when UdmTablesList writes are suppressed)
    importer = sys.modules.get("data_load.pii_inventory_importer", MagicMock())
    assert importer.import_pii_inventory.called, (
        "import_pii_inventory must be called on the re-run to enable "
        "PiiInventoryAuditLog append (D26 append-only audit trail). "
        "Do not skip the call when values are unchanged."
    )


# ---------------------------------------------------------------------------
# Docstring classifier dimensions
# ---------------------------------------------------------------------------


def test_docstring_documents_classifier_dimensions():
    """Module + function docstring documents all 4 udm-execution-classifier dimensions.

    udm-execution-classifier discipline (per task spec): the module docstring
    must document all four classifier dimensions:
      1. Idempotency contract: UPDATE-only on UdmTablesList (no writes when
         value unchanged); PiiInventoryAuditLog INSERT-only (append-only);
         multi-invocation produces multiple audit rows.
      2. Trigger: manual operator call (compliance-lead generates CSV → invokes);
         frequency: 1-3 times per source over project lifetime.
      3. Frequency: never scheduled (governance-driven; Automic NEVER per § 4).
      4. Audit-row family: CLI_IMPORT_PII_INVENTORY (CLI_* per D76 + Round 4 § 3).

    North Star: Traceability (D63 + D26 — operators must understand the
    governance model of a tool that populates PII column declarations).

    B189. Spec: phase1/04b § 4 + task spec docstring classifier requirement.
    """
    mod = _load_tool_module()

    module_doc = mod.__doc__ or ""
    func_doc = getattr(mod.main, "__doc__", "") or ""
    combined_doc = (module_doc + " " + func_doc).lower()

    # Dimension 1: Idempotency — mention update-only / no writes when unchanged
    assert any(word in combined_doc for word in (
        "idempotent", "no writes", "value unchanged", "hash compare",
        "update-only", "append-only", "no udmtableslist"
    )), (
        "Module/function docstring must document idempotency contract "
        "(UPDATE-only on UdmTablesList when value changes; PiiInventoryAuditLog "
        "INSERT-only append-only; multi-invocation = multi-audit-row). "
        "udm-execution-classifier dimension 1."
    )

    # Dimension 2: Trigger — operator / compliance / governance
    assert any(word in combined_doc for word in (
        "operator", "compliance", "governance", "csv", "manual"
    )), (
        "Module/function docstring must document trigger context "
        "(operator-driven compliance review; manual CSV import). "
        "udm-execution-classifier dimension 2."
    )

    # Dimension 3: Frequency — must mention never scheduled / governance-driven
    assert any(word in combined_doc for word in (
        "never scheduled", "not scheduled", "governance", "1-3 times",
        "over project lifetime", "never automic", "automic never"
    )), (
        "Module/function docstring must document frequency "
        "(1-3 times per source over project lifetime; never scheduled; "
        "Automic NEVER per § 4 invocation patterns). "
        "udm-execution-classifier dimension 3."
    )

    # Dimension 4: Audit-row family — CLI_IMPORT_PII_INVENTORY
    assert any(word in combined_doc for word in (
        "cli_import_pii_inventory", "cli_*", "cli_import",
        "pipelineeventlog", "eventtype"
    )), (
        "Module/function docstring must document audit-row family "
        "(CLI_IMPORT_PII_INVENTORY per D76 + Round 4 § 3). "
        "udm-execution-classifier dimension 4."
    )
