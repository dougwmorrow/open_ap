"""Tier 0 smoke tests for tools/pre_commit_checks.py per D67 + B-308 closure.

Quality-checks orchestrator (4 checks: query_blindspots + pytest_changed +
markdown_cross_refs + cli_compliance_d74_d75_d76). Per user-direction
2026-05-16 "update it to be a code quality layer as well" + BLOCK on failures
+ BLOCK on new public surface without tests.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))


def test_module_imports():
    """Assertion 1: orchestrator module imports cleanly."""
    import tools.pre_commit_checks  # noqa: F401


def test_public_surface_exports():
    """Assertion 2: public surface present."""
    import tools.pre_commit_checks as pcc
    assert hasattr(pcc, "main")
    assert hasattr(pcc, "cli_main")
    assert hasattr(pcc, "run_all_checks")
    assert hasattr(pcc, "CheckResult")
    assert hasattr(pcc, "CHECKS")
    assert hasattr(pcc, "EVENT_TYPE")
    assert hasattr(pcc, "EXIT_SUCCESS")
    assert hasattr(pcc, "EXIT_BLOCKED")
    assert hasattr(pcc, "EXIT_FATAL")


def test_event_type_constant():
    """Assertion 3: EVENT_TYPE matches D76 audit-row contract."""
    from tools.pre_commit_checks import EVENT_TYPE
    assert EVENT_TYPE == "CLI_PRE_COMMIT_CHECKS"


def test_exit_codes_per_d74():
    """Assertion 4: exit codes follow D74 convention."""
    from tools.pre_commit_checks import EXIT_SUCCESS, EXIT_BLOCKED, EXIT_FATAL
    assert EXIT_SUCCESS == 0
    assert EXIT_BLOCKED == 1
    assert EXIT_FATAL == 3


def test_checks_registry_complete():
    """Assertion 5: CHECKS registry has all 4 Phase 1 checks."""
    from tools.pre_commit_checks import (
        CHECKS,
        check_query_blindspots,
        check_pytest_changed_python_files,
        check_markdown_cross_refs,
        check_cli_compliance_d74_d75_d76,
    )
    assert check_query_blindspots in CHECKS
    assert check_pytest_changed_python_files in CHECKS
    assert check_markdown_cross_refs in CHECKS
    assert check_cli_compliance_d74_d75_d76 in CHECKS
    assert len(CHECKS) == 4


def test_check_result_shape():
    """Assertion 6: CheckResult dataclass has expected fields."""
    from tools.pre_commit_checks import CheckResult
    r = CheckResult(name="test", passed=True, severity="info", diagnostic="ok")
    assert r.name == "test"
    assert r.passed is True
    assert r.severity == "info"
    assert r.diagnostic == "ok"
    assert hasattr(r, "to_dict")
    d = r.to_dict()
    assert d["name"] == "test"


def test_empty_staged_returns_passes():
    """Assertion 7: with no staged files, all checks return passed (info severity)."""
    from tools.pre_commit_checks import run_all_checks
    results = run_all_checks(staged=[])
    assert len(results) == 4
    for r in results:
        assert r.passed, f"{r.name} failed on empty input: {r.diagnostic}"


def test_check_markdown_cross_refs_no_md_files():
    """Assertion 8: markdown cross-ref check passes when no md files staged."""
    from tools.pre_commit_checks import check_markdown_cross_refs
    result = check_markdown_cross_refs(staged=["tools/foo.py"])
    assert result.passed
    assert result.severity == "info"


def test_check_cli_compliance_no_new_tools():
    """Assertion 9: CLI compliance check passes when no new tools/*.py."""
    from tools.pre_commit_checks import check_cli_compliance_d74_d75_d76
    result = check_cli_compliance_d74_d75_d76(staged=["docs/foo.md"])
    assert result.passed
    assert result.severity == "info"


def test_check_pytest_no_python_files():
    """Assertion 10: pytest check passes when no source .py files staged."""
    from tools.pre_commit_checks import check_pytest_changed_python_files
    result = check_pytest_changed_python_files(staged=["docs/foo.md"])
    assert result.passed
    assert result.severity == "info"


def test_cli_main_help_invocable():
    """Assertion 11: --help exits 0."""
    from tools.pre_commit_checks import cli_main
    with pytest.raises(SystemExit) as excinfo:
        cli_main(["--help"])
    assert excinfo.value.code == 0


def test_find_test_files_for_existing_module():
    """Assertion 12: _find_test_files_for finds tests when they exist."""
    from tools.pre_commit_checks import _find_test_files_for
    tests = _find_test_files_for("tools/query_blindspots.py")
    assert len(tests) >= 1
    assert any("test_query_blindspots" in str(t) for t in tests)
