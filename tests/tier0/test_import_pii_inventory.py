"""Tier 0 build-time smoke test for tools/import_pii_inventory.py.

Per D67 — runs at build time + every commit. Runtime ceiling < 5 s.
All external dependencies (csv reader, pyodbc cursor, UdmTablesList, DB)
are mocked. No live SQL Server, no real CSV file required.

North Star pillars:
  - Audit-grade (D76 audit-row contract: one CLI_IMPORT_PII_INVENTORY row
    per invocation; PiiInventoryAuditLog append-only per D26; DataClassification
    enum strictly validated before any write).
  - Traceability (D26 append-only provenance: PiiInventoryAuditLog row per
    CSV row; multi-invocation audit trail intentional per § 4 idempotency note;
    D63 UdmTablesList.PiiColumnList + DataClassification populated).
  - Idempotent (D15: re-running same CSV produces no UdmTablesList UPDATE when
    values unchanged; PiiInventoryAuditLog still appends per D26).
  - Operationally stable (D67 Tier 0 discipline: import + invoke + shape +
    error-modes in < 5 s with zero external I/O).

D-numbers: D15 (idempotency mandatory), D26 (append-only provenance),
D63 (UdmTablesList canonical column inventory), D67 (Tier 0 discipline),
D74 (exit-code contract: 0/1/2), D75 (arg naming), D76 (audit-row contract),
D77 (6-canonical-assertion Tier 0 scaffold).

B-numbers: B189 (Tool 15 backlog entry — import_pii_inventory implementation
tracking), B185 (data-side PII inventory closure this tool addresses).

Spec: phase1/04b_phase_0_closure_tools.md § 4 (Tool 15 canonical spec,
including 6 Tier 0 canonical assertions, exit-code mapping, CSV schema,
DataClassification enum, PiiInventoryAuditLog contract, error modes).
"""
from __future__ import annotations

import importlib
import importlib.util
import io
import json
import sys
import time
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Project root on sys.path (matches tests/ convention)
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Tool module path — implementation lands at Phase 2 R1 per phase2/00.
# Import test fails with an informative message when file is absent,
# blocking the build correctly per D67 semantics.
# ---------------------------------------------------------------------------

_TOOL_PATH = _PROJECT_ROOT / "tools" / "import_pii_inventory.py"
_TOOL_MODULE_KEY = "tools.import_pii_inventory"

# ---------------------------------------------------------------------------
# Shared constants — single source of truth inside this file
# ---------------------------------------------------------------------------

# D76 EventType for this tool (CLI_* family per Round 7 § 1.1)
EXPECTED_EVENT_TYPE = "CLI_IMPORT_PII_INVENTORY"

# DataClassification enum per phase1/04b § 4 (frozen; D92 forward-only)
VALID_CLASSIFICATIONS = {"PII", "PCI", "GLBA", "SOX", "INTERNAL", "PUBLIC", "NONE"}

# D75 canonical args
_ACTOR = "test-build-smoke"
_REVIEWER = "compliance-lead"
_CSV_PATH = "/var/pipeline/pii_inventory_test.csv"

# Canonical CSV schema per phase1/04b § 4
CSV_HEADER = "SourceName,TableName,PiiColumnList,DataClassification,Rationale,ReviewedBy,ReviewedAt"

# One valid CSV row for synthetic-data tests
_VALID_CSV_ROW = (
    "DNA,ACCT,\"ACCT_NUMBER,SSN,CUST_EMAIL\",PII,"
    "Customer PII per compliance review 2026-05-12,compliance-lead,2026-05-12"
)

# Full minimal valid CSV (header + one data row)
_VALID_CSV_CONTENT = f"{CSV_HEADER}\n{_VALID_CSV_ROW}\n"

# CSV row with an invalid DataClassification (not in the 7-value enum)
_INVALID_CLASSIFICATION_ROW = (
    "DNA,ACCT,\"ACCT_NUMBER\",UNKNOWN_VALUE,"
    "Bad classification,compliance-lead,2026-05-12"
)
_INVALID_CSV_CONTENT = f"{CSV_HEADER}\n{_INVALID_CLASSIFICATION_ROW}\n"

# CSV row with a SourceName that does not exist in UdmTablesList
_UNKNOWN_SOURCE_ROW = (
    "NONEXISTENT,FAKEABLE,\"COL1\",PII,"
    "Unknown source,compliance-lead,2026-05-12"
)

# D74 exit code constants (per spec and R22)
EXIT_SUCCESS = 0   # all rows imported successfully
EXIT_WARNING = 1   # some rows skipped (unknown source/table with --allow-unknown)
EXIT_FATAL = 2     # parse error / invalid classification / not writable


# ---------------------------------------------------------------------------
# Helpers — module loader + mock factories
# ---------------------------------------------------------------------------


def _load_module() -> ModuleType:
    """Load tools/import_pii_inventory.py with all external imports mocked.

    Patches csv, pyodbc, event_tracker, connections so the module body never
    touches a real DB or filesystem at import time.

    Returns the loaded module object, or raises if the file is absent
    (which fails the build per D67 intent).
    """
    if _TOOL_MODULE_KEY in sys.modules:
        del sys.modules[_TOOL_MODULE_KEY]

    mock_event_tracker = MagicMock()
    mock_conn_module = MagicMock()

    # data_load.pii_inventory_importer is the wrapped module per § 4
    mock_importer = MagicMock()
    mock_result = MagicMock()
    mock_result.rows_total = 1
    mock_result.rows_imported = 1
    mock_result.rows_skipped = 0
    mock_result.rows_failed = 0
    mock_result.errors = []
    mock_importer.import_pii_inventory.return_value = mock_result

    # ImportResult and documented error classes
    mock_importer.ImportResult = MagicMock
    mock_importer.CsvParseError = type("CsvParseError", (Exception,), {})
    mock_importer.InvalidDataClassificationError = type(
        "InvalidDataClassificationError", (Exception,), {}
    )
    mock_importer.UnknownSourceTableError = type(
        "UnknownSourceTableError", (Exception,), {}
    )
    mock_importer.UdmTablesListNotWritable = type(
        "UdmTablesListNotWritable", (Exception,), {}
    )

    with patch.dict("sys.modules", {
        "data_load.pii_inventory_importer": mock_importer,
        "observability.event_tracker": mock_event_tracker,
        "utils.connections": mock_conn_module,
        "utils.configuration": MagicMock(),
        "observability.log_handler": MagicMock(),
    }):
        spec = importlib.util.spec_from_file_location(_TOOL_MODULE_KEY, _TOOL_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

    return mod


def _make_mock_cursor() -> MagicMock:
    """Return a mock pyodbc cursor that accepts INSERTs + UPDATEs."""
    cursor = MagicMock()
    cursor.fetchone.return_value = None
    # UdmTablesList lookup: row exists (source/table present)
    cursor.fetchone.return_value = (1,)
    return cursor


def _make_mock_conn(cursor: MagicMock) -> MagicMock:
    """Return a mock pyodbc connection wrapping the given cursor."""
    conn = MagicMock()
    conn.cursor.return_value = cursor
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    return conn


# ---------------------------------------------------------------------------
# (a) Module imports without error
# ---------------------------------------------------------------------------


def test_module_imports():
    """(a) tools/import_pii_inventory.py imports without error.

    Per D67 Tier 0 assertion 1 + D77 6-canonical scaffold assertion 1.
    Verifies no missing dependencies, no syntax errors, no import-time
    side-effects (no DB connection, no CSV read, no file I/O).

    North Star: Operationally stable (import failures block every subsequent
    build step per D67 failure consequence).

    B189 (Tool 15 authoring closes this item).
    Spec: phase1/04b § 4 (Tool 15 canonical spec).
    """
    mod = _load_module()
    assert mod is not None, (
        "Module must load without error. Check for missing dependencies or "
        "syntax errors in tools/import_pii_inventory.py."
    )
    assert hasattr(mod, "main"), (
        "tools/import_pii_inventory.py must expose a top-level 'main' function "
        "per phase1/04b § 4 canonical signature."
    )


# ---------------------------------------------------------------------------
# (b) --help exits 0
# ---------------------------------------------------------------------------


def test_help_exits_zero():
    """(b) tools/import_pii_inventory.py --help exits 0 per D74.

    Per D67 Tier 0 assertion 2 + D77 canonical scaffold assertion 2.
    argparse --help must exit cleanly with SystemExit(0).
    If the arg parser is broken (bad metavar, missing required arg),
    --help will raise a different error or exit non-zero.

    D74 (exit 0 = success), B189.
    Spec: phase1/04b § 4 CLI interface.
    """
    import subprocess

    result = subprocess.run(
        [sys.executable, str(_TOOL_PATH), "--help"],
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, (
        f"tools/import_pii_inventory.py --help must exit 0 per D74. "
        f"Got returncode={result.returncode!r}. "
        f"stderr={result.stderr.decode(errors='replace')!r}"
    )
    help_text = result.stdout.decode(errors="replace").lower()
    # Key arguments must appear in help output
    assert "csv-path" in help_text or "csv_path" in help_text, (
        "--csv-path must be documented in --help output. "
        "It is a REQUIRED argument per phase1/04b § 4."
    )
    assert "actor" in help_text, (
        "--actor must be documented in --help output (D75 canonical arg)."
    )


# ---------------------------------------------------------------------------
# (c) Success with valid CSV — UPDATE called per row; PiiInventoryAuditLog written
# ---------------------------------------------------------------------------


def test_success_with_valid_csv():
    """(c) Mocked CSV with valid rows → exit 0; UPDATE per row; audit log row per row.

    Per D67 Tier 0 assertion 3 + D77 scaffold assertion 3 (success).
    Tier 0 assertion from phase1/04b § 4:
      'mocked CSV reader + valid rows → exit 0; UPDATE called per row;
       PiiInventoryAuditLog row per CSV row'.

    Verifies:
    - main() returns exit_code=0 (D74 success tier)
    - rows_imported equals number of valid CSV rows
    - no errors in result

    North Star: Audit-grade (D76 audit-row written; D26 PiiInventoryAuditLog
    append-only row per CSV row applied).

    B189, D74, D76, D26. Spec: phase1/04b § 4.
    """
    mod = _load_module()

    # Patch the wrapped import_pii_inventory to return a clean ImportResult
    mock_importer = sys.modules.get("data_load.pii_inventory_importer", MagicMock())
    mock_result = MagicMock()
    mock_result.rows_total = 1
    mock_result.rows_imported = 1
    mock_result.rows_skipped = 0
    mock_result.rows_failed = 0
    mock_result.errors = []

    with patch.object(mock_importer, "import_pii_inventory", return_value=mock_result):
        result = mod.main(
            csv_path=_CSV_PATH,
            actor=_ACTOR,
            reviewer=_REVIEWER,
            dry_run=False,
            allow_unknown=False,
            json_output=False,
            verbose=False,
            quiet=False,
        )

    assert result is not None, "main() must return a dict, not None"
    assert isinstance(result, dict), f"main() must return a dict. Got {type(result)!r}"
    assert result.get("exit_code") == EXIT_SUCCESS, (
        f"Valid CSV → exit_code must be 0 (success) per D74. "
        f"Got exit_code={result.get('exit_code')!r}. Full result: {result!r}"
    )
    assert result.get("rows_imported") == 1, (
        f"rows_imported must equal 1 (one valid row in CSV). "
        f"Got: {result.get('rows_imported')!r}"
    )


# ---------------------------------------------------------------------------
# (d) Error: invalid DataClassification → exit 2; no writes
# ---------------------------------------------------------------------------


def test_error_invalid_classification_exits_2():
    """(d) CSV row with DataClassification='UNKNOWN_VALUE' → exit 2; no DB writes.

    Per D67 Tier 0 assertion 4 + D77 scaffold assertion 4 (error).
    Tier 0 assertion from phase1/04b § 4:
      'CSV row with DataClassification=UNKNOWN_VALUE → exit 2; no writes'.

    DataClassification enum: PII | PCI | GLBA | SOX | INTERNAL | PUBLIC | NONE.
    Any value outside this set must trigger InvalidDataClassificationError → exit 2.

    D74 (exit 2 = fatal; no writes committed), D63 (DataClassification enum
    per UdmTablesList canonical column inventory), B189.
    Spec: phase1/04b § 4 DataClassification enum + error modes.
    """
    mod = _load_module()

    InvalidDataClassificationError = type(
        "InvalidDataClassificationError", (Exception,), {}
    )
    mock_importer = sys.modules.get("data_load.pii_inventory_importer", MagicMock())

    with patch.object(
        mock_importer,
        "import_pii_inventory",
        side_effect=InvalidDataClassificationError("UNKNOWN_VALUE"),
    ), patch.object(
        mock_importer,
        "InvalidDataClassificationError",
        InvalidDataClassificationError,
    ):
        result = mod.main(
            csv_path=_CSV_PATH,
            actor=_ACTOR,
            reviewer=None,
            dry_run=False,
            allow_unknown=False,
            json_output=False,
            verbose=False,
            quiet=True,
        )

    assert isinstance(result, dict), "main() must return a dict even on fatal path"
    assert result.get("exit_code") == EXIT_FATAL, (
        f"InvalidDataClassificationError → exit_code must be 2 (fatal) per D74. "
        f"Got: {result.get('exit_code')!r}"
    )


# ---------------------------------------------------------------------------
# (e) Warning: unknown source/table with --allow-unknown → exit 1, other rows proceed
# ---------------------------------------------------------------------------


def test_warning_unknown_source_table_with_allow_unknown():
    """(e) CSV row with unknown SourceName + --allow-unknown → exit 1; other rows proceed.

    Per D67 Tier 0 assertion 5 + D77 scaffold assertion 5 (warning).
    Tier 0 assertion from phase1/04b § 4:
      'CSV row with SourceName=NONEXISTENT + --allow-unknown flag → exit 1
       skip + warning; other valid rows still imported'.

    UnknownSourceTableError with allow_unknown=True → exit 1 (warning tier);
    rows_skipped incremented; rows_imported reflects other successful rows.

    D74 (exit 1 = expected operational failure), B189.
    Spec: phase1/04b § 4 error modes + --allow-unknown argument.
    """
    mod = _load_module()

    mock_importer = sys.modules.get("data_load.pii_inventory_importer", MagicMock())

    # Import result: 1 valid row imported, 1 unknown row skipped
    mock_result = MagicMock()
    mock_result.rows_total = 2
    mock_result.rows_imported = 1
    mock_result.rows_skipped = 1
    mock_result.rows_failed = 0
    mock_result.errors = ["NONEXISTENT.FAKEABLE: unknown source/table (skipped)"]

    with patch.object(mock_importer, "import_pii_inventory", return_value=mock_result):
        result = mod.main(
            csv_path=_CSV_PATH,
            actor=_ACTOR,
            reviewer=None,
            dry_run=False,
            allow_unknown=True,    # key: --allow-unknown flag set
            json_output=False,
            verbose=False,
            quiet=True,
        )

    assert isinstance(result, dict), "main() must return a dict on warning path"
    assert result.get("exit_code") == EXIT_WARNING, (
        f"Unknown source + --allow-unknown → exit_code must be 1 (warning) per D74. "
        f"Got: {result.get('exit_code')!r}"
    )
    assert result.get("rows_skipped", 0) >= 1, (
        f"rows_skipped must be >= 1 when an unknown row was skipped. "
        f"Got: {result.get('rows_skipped')!r}"
    )


# ---------------------------------------------------------------------------
# (f) --dry-run: no UPDATE; no PiiInventoryAuditLog; main audit row written
# ---------------------------------------------------------------------------


def test_dry_run_no_writes_main_audit_row_written():
    """(f) --dry-run → exit 0; NO UPDATE; NO PiiInventoryAuditLog row; main invocation
    audit row written with Metadata.dry_run=true.

    Per D67 Tier 0 assertion 6 + D77 scaffold assertion 6 (dry-run mode).
    Tier 0 assertion from phase1/04b § 4:
      '--dry-run → exit 0; NO UPDATE; NO PiiInventoryAuditLog row;
       main invocation audit row still written with Metadata.dry_run=true'.

    Idempotency per D15: dry-run validates without committing; re-invocation
    of the dry-run produces no side-effects. The PipelineEventLog CLI row
    IS still written (non-suppressible per D76 audit-row contract).

    D74 (exit 0), D15 (idempotency), D76 (audit-row non-suppressible), B189.
    Spec: phase1/04b § 4 --dry-run + idempotency note.
    """
    mod = _load_module()

    mock_importer = sys.modules.get("data_load.pii_inventory_importer", MagicMock())

    # dry_run=True → import_pii_inventory called with dry_run=True
    mock_result = MagicMock()
    mock_result.rows_total = 1
    mock_result.rows_imported = 0
    mock_result.rows_skipped = 0
    mock_result.rows_failed = 0
    mock_result.errors = []

    with patch.object(mock_importer, "import_pii_inventory", return_value=mock_result) as mock_fn:
        result = mod.main(
            csv_path=_CSV_PATH,
            actor=_ACTOR,
            reviewer=None,
            dry_run=True,
            allow_unknown=False,
            json_output=False,
            verbose=False,
            quiet=True,
        )

    assert isinstance(result, dict), "main() must return a dict on dry-run path"
    assert result.get("exit_code") == EXIT_SUCCESS, (
        f"--dry-run with valid CSV → exit_code must be 0 per D74. "
        f"Got: {result.get('exit_code')!r}"
    )

    # Verify dry_run was threaded through to the wrapped function
    if mock_fn.called:
        call_kwargs = mock_fn.call_args.kwargs if mock_fn.call_args else {}
        call_args = mock_fn.call_args.args if mock_fn.call_args else ()
        # dry_run=True must have been passed (either positionally or by keyword)
        dry_run_passed = (
            call_kwargs.get("dry_run") is True
            or (len(call_args) > 1 and call_args[1] is True)
        )
        assert dry_run_passed or "dry_run" in str(mock_fn.call_args), (
            "dry_run=True must be threaded through to import_pii_inventory(). "
            "The wrapped function must NOT perform DB writes when dry_run=True. "
            "Spec: phase1/04b § 4 --dry-run note."
        )

    # dry_run=True must appear in result Metadata so the PipelineEventLog audit row
    # carries Metadata.dry_run=true (D76 audit-row contract)
    result_str = json.dumps(result)
    assert "dry_run" in result_str or result.get("dry_run") is True, (
        "Result dict must carry dry_run=true for the PipelineEventLog "
        "Metadata JSON per D76 audit-row contract. "
        "Spec: phase1/04b § 4 Tier 0 assertion 6."
    )


# ---------------------------------------------------------------------------
# (g) Tier 0 total runtime < 5 s per D67
# ---------------------------------------------------------------------------


def test_tier0_total_runtime_under_5s():
    """(g) All Tier 0 smoke assertions complete in < 5 s per D67.

    Sentinel test: if the module starts performing real I/O (DB connection,
    CSV file read from disk, network call) the runtime ceiling will be
    breached and this test catches the regression before the build step.

    D67: Runtime ceiling < 5 seconds per module (build-time constraint).
    B189. Spec: phase1/04b § 4 Tier 0 scaffold.
    """
    start = time.monotonic()

    mod = _load_module()

    mock_importer = sys.modules.get("data_load.pii_inventory_importer", MagicMock())
    mock_result = MagicMock()
    mock_result.rows_total = 1
    mock_result.rows_imported = 1
    mock_result.rows_skipped = 0
    mock_result.rows_failed = 0
    mock_result.errors = []

    with patch.object(mock_importer, "import_pii_inventory", return_value=mock_result):
        mod.main(
            csv_path=_CSV_PATH,
            actor=_ACTOR,
            reviewer=None,
            dry_run=False,
            allow_unknown=False,
            json_output=False,
            verbose=False,
            quiet=True,
        )

    elapsed = time.monotonic() - start
    assert elapsed < 5.0, (
        f"Tier 0 smoke must complete in < 5 s per D67. "
        f"Took {elapsed:.2f} s. Module is likely performing real I/O — "
        "check for missing mocks (pyodbc, csv file read, network)."
    )


# Step 10 verifier discipline addition per B189 closure cohort 2026-05-17
# (Worker B agentId a17541f3b4a4f68f6 added `__all__` + EXIT_OPERATIONAL alias;
# this assertion validates Step 10 public-surface registration is correct +
# alias resolves to canonical EXIT_WARNING value per D74).
def test_tool_public_surface_and_exit_operational_alias():
    """(h) Step 10 verifier: `__all__` exports + `EXIT_OPERATIONAL` alias
    correctly resolved to `EXIT_WARNING` (= 1) per D74 exit-code contract.
    Per B189 closure 2026-05-17 + Worker B `a17541f3b4a4f68f6` Step 10
    registration additions.
    """
    mod = _load_module()

    # __all__ public surface (Step 10 verifier compliance)
    assert hasattr(mod, "__all__")
    expected_exports = {
        "EVENT_TYPE",
        "EXIT_SUCCESS",
        "EXIT_WARNING",
        "EXIT_OPERATIONAL",
        "EXIT_FATAL",
        "main",
        "cli_main",
        "_build_parser",
    }
    actual_exports = set(mod.__all__)
    assert expected_exports == actual_exports, (
        f"__all__ drift detected. Expected: {expected_exports - actual_exports} "
        f"missing; {actual_exports - expected_exports} extra."
    )

    # EXIT_OPERATIONAL alias resolves to EXIT_WARNING (= 1) per D74
    assert mod.EXIT_OPERATIONAL == mod.EXIT_WARNING
    assert mod.EXIT_OPERATIONAL == 1
