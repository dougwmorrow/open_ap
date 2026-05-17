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
    """Assertion 5 (per B-309 Cycle 1 + B-315): CHECKS registry has 6 Phase 1 checks
    (B-315 adds check_gap_accountability as 6th check; Pitfall #9.p candidate)."""
    from tools.pre_commit_checks import (
        CHECKS,
        check_query_blindspots,
        check_pytest_changed_python_files,
        check_lint_security_types_changed_python_files,
        check_markdown_cross_refs,
        check_cli_compliance_d74_d75_d76,
        check_gap_accountability,
    )
    assert check_query_blindspots in CHECKS
    assert check_pytest_changed_python_files in CHECKS
    assert check_lint_security_types_changed_python_files in CHECKS
    assert check_markdown_cross_refs in CHECKS
    assert check_cli_compliance_d74_d75_d76 in CHECKS
    assert check_gap_accountability in CHECKS
    assert len(CHECKS) == 6


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
    """Assertion 7: with no staged files, all 6 checks return passed (info severity)."""
    from tools.pre_commit_checks import run_all_checks
    results = run_all_checks(staged=[])
    assert len(results) == 6
    for r in results:
        assert r.passed, f"{r.name} failed on empty input: {r.diagnostic}"


def test_check_gap_accountability_no_relevant_files():
    """Assertion 17 (per B-315): no .md/.py/.txt staged → info pass."""
    from tools.pre_commit_checks import check_gap_accountability
    result = check_gap_accountability(staged=["binary.bin"])
    assert result.passed
    assert result.severity == "info"


def test_scan_for_unaddressed_gaps_paired_with_bnumber():
    """Assertion 18 (per B-315): phrase paired with B-NNN within ±5 lines → no finding."""
    from tools.pre_commit_checks import _scan_for_unaddressed_gaps
    content = "We noticed a drift candidate here.\nFiled as B-315 in BACKLOG.\n"
    findings = _scan_for_unaddressed_gaps(content, "fake.md")
    assert findings == []


def test_scan_for_unaddressed_gaps_paired_with_dismissal():
    """Assertion 19 (per B-315): phrase paired with explicit dismissal → no finding."""
    from tools.pre_commit_checks import _scan_for_unaddressed_gaps
    content = "There's a B-N candidate here.\nDismissed: cosmetic only.\n"
    findings = _scan_for_unaddressed_gaps(content, "fake.md")
    assert findings == []


def test_scan_for_unaddressed_gaps_unpaired_blocks():
    """Assertion 20 (per B-315): phrase WITHOUT disposition within ±5 lines → finding."""
    from tools.pre_commit_checks import _scan_for_unaddressed_gaps
    content = "This is a drift candidate I noticed.\nMoving on to other work.\n"
    findings = _scan_for_unaddressed_gaps(content, "fake.md")
    assert len(findings) == 1
    assert findings[0][1] == "drift candidate"


def test_scan_for_unaddressed_gaps_allowlisted_file_skipped():
    """Assertion 21 (per B-315): allowlisted substrate files skipped entirely."""
    from tools.pre_commit_checks import _scan_for_unaddressed_gaps
    content = "This is a drift candidate with no disposition near it.\n"
    findings = _scan_for_unaddressed_gaps(content, "CLAUDE.md")
    assert findings == []


def test_scan_for_unaddressed_gaps_test_file_allowlisted():
    """Assertion 22 (per B-315): tests/tier0/*.py allowlisted (test data fixtures)."""
    from tools.pre_commit_checks import _scan_for_unaddressed_gaps
    content = "phrase = 'drift candidate'\n# no disposition\n"
    findings = _scan_for_unaddressed_gaps(content, "tests/tier0/test_something.py")
    assert findings == []


def test_check_query_blindspots_empty_staged_returns_info():
    """Assertion 23 (per B-316): empty staged list returns info pass without invoking subprocess."""
    from tools.pre_commit_checks import check_query_blindspots
    result = check_query_blindspots(staged=[])
    assert result.passed
    assert result.severity == "info"
    assert "no staged files" in result.diagnostic


def test_check_query_blindspots_docstring_cites_b316_freshness():
    """Assertion 24 (per B-316): wrapper docstring documents the freshness behavior."""
    from tools.pre_commit_checks import check_query_blindspots
    doc = check_query_blindspots.__doc__ or ""
    assert "B-316" in doc
    assert "B-312 freshness pattern" in doc
    assert "MODIFIED files" in doc
    assert "NEW files" in doc


def test_check_query_blindspots_uses_added_files_helper():
    """Assertion 25 (per B-316): implementation uses _staged_added_files to classify NEW vs MODIFIED."""
    import inspect
    from tools.pre_commit_checks import check_query_blindspots
    src = inspect.getsource(check_query_blindspots)
    assert "_staged_added_files" in src
    assert "_staged_diff_added_lines" in src
    assert "tempfile" in src


def test_check_lint_no_python_files():
    """Assertion 13: lint/security/types check passes (info) when no source .py staged."""
    from tools.pre_commit_checks import check_lint_security_types_changed_python_files
    result = check_lint_security_types_changed_python_files(staged=["docs/foo.md"])
    assert result.passed
    assert result.severity == "info"


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


def test_scan_content_for_broken_refs_helper():
    """Assertion 14 (per B-312): _scan_content_for_broken_refs detects unresolved refs."""
    from tools.pre_commit_checks import _scan_content_for_broken_refs
    known = {"D": {1, 2, 3}, "B": set(), "R": set(), "RB": set(), "SP": set()}
    content = "Per D62 this is a broken ref. Per D1 this resolves.\n"
    broken = _scan_content_for_broken_refs(content, "test.md", known)
    assert len(broken) == 1
    assert broken[0][1] == "D"  # prefix
    assert broken[0][2] == "62"  # number


def test_scan_content_resolves_zero_padded():
    """Assertion 15: int comparison normalizes zero-padding (R01 = R1)."""
    from tools.pre_commit_checks import _scan_content_for_broken_refs
    known = {"D": set(), "B": set(), "R": {1, 2, 5}, "RB": set(), "SP": set()}
    content = "Per R-5 this should resolve (canonical R05 -> int 5).\n"
    broken = _scan_content_for_broken_refs(content, "test.md", known)
    assert broken == []


def test_staged_diff_added_lines_function_exists():
    """Assertion 16 (per B-312): _staged_diff_added_lines helper function present."""
    from tools.pre_commit_checks import _staged_diff_added_lines
    assert callable(_staged_diff_added_lines)
    # When called outside git context OR for non-staged file, returns empty
    result = _staged_diff_added_lines("nonexistent-file-xyz.md")
    assert isinstance(result, str)
