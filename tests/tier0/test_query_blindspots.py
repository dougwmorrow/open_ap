"""Tier 0 smoke tests for tools/query_blindspots.py per D67.

Verifies:
- module imports
- public surface (main / cli_main / query_blindspots / Match / QueryReport / CHECKS / EVENT_TYPE / EXIT_*)
- EVENT_TYPE = "CLI_QUERY_BLINDSPOTS"
- exit codes per D74
- empty-input cases return SUCCESS

Per Round 5 § 3.4 Tier 0 6-assertion contract: covers (a) module imports +
(b) main function invocable + (c) return shape + (d) no silent failure paths.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))


def test_module_imports():
    """Assertion 1: module imports cleanly."""
    import tools.query_blindspots  # noqa: F401


def test_public_surface_exports():
    """Assertion 2: public surface present."""
    import tools.query_blindspots as qb
    assert hasattr(qb, "main")
    assert hasattr(qb, "cli_main")
    assert hasattr(qb, "query_blindspots")
    assert hasattr(qb, "Match")
    assert hasattr(qb, "QueryReport")
    assert hasattr(qb, "CHECKS")
    assert hasattr(qb, "EVENT_TYPE")
    assert hasattr(qb, "EXIT_SUCCESS")
    assert hasattr(qb, "EXIT_WARNING")
    assert hasattr(qb, "EXIT_OPERATIONAL_FAILURE")
    assert hasattr(qb, "EXIT_FATAL")


def test_event_type_constant():
    """Assertion 3: EVENT_TYPE matches D76 audit-row contract."""
    from tools.query_blindspots import EVENT_TYPE
    assert EVENT_TYPE == "CLI_QUERY_BLINDSPOTS"


def test_exit_codes_per_d74():
    """Assertion 4: exit codes follow D74 convention."""
    from tools.query_blindspots import (
        EXIT_SUCCESS, EXIT_WARNING, EXIT_OPERATIONAL_FAILURE, EXIT_FATAL,
    )
    assert EXIT_SUCCESS == 0
    assert EXIT_WARNING == 1
    assert EXIT_OPERATIONAL_FAILURE == 2
    assert EXIT_FATAL == 3


def test_empty_input_returns_success():
    """Assertion 5: no files + no commit + no since-main = SUCCESS exit."""
    from tools.query_blindspots import query_blindspots, EXIT_SUCCESS
    report = query_blindspots(files=[])
    assert report.exit_code == EXIT_SUCCESS
    assert report.matches == []


def test_query_returns_query_report_shape():
    """Assertion 6: query_blindspots returns QueryReport with expected fields."""
    from tools.query_blindspots import query_blindspots, QueryReport
    report = query_blindspots(files=[])
    assert isinstance(report, QueryReport)
    assert hasattr(report, "scanned_files")
    assert hasattr(report, "entries_checked")
    assert hasattr(report, "matches")
    assert hasattr(report, "skipped_checks")
    assert hasattr(report, "exit_code")


def test_checks_registry_nonempty():
    """Assertion 7: CHECKS registry has at least the 4 Phase 1 entries."""
    from tools.query_blindspots import CHECKS
    expected_keys = {
        "9j-b-item-status-render-discipline",
        "9o-recursive-exemption-rationalization",
        "9n-convention-registration-not-applied-to-new-build-artifacts",
        "9h-wrong-section-number-invented-description",
    }
    assert expected_keys.issubset(CHECKS.keys())


def test_ledger_loadable():
    """Assertion 8: ledger.yml loadable (file exists + parses)."""
    from tools.query_blindspots import _load_ledger
    ledger = _load_ledger()
    assert isinstance(ledger, dict)
    assert "entries" in ledger
    assert len(ledger["entries"]) >= 15  # 9.a through 9.o = 15 entries


def test_cli_main_help_invocable():
    """Assertion 9: --help exits 0 (argparse default)."""
    from tools.query_blindspots import cli_main
    with pytest.raises(SystemExit) as excinfo:
        cli_main(["--help"])
    assert excinfo.value.code == 0
