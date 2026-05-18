"""Tier 0 smoke tests for tools/pre_commit_checks.py per D67 + B-308 closure.

Quality-checks orchestrator (8 checks: query_blindspots + pytest_changed +
lint_security_types + markdown_cross_refs + cli_compliance_d74_d75_d76 +
gap_accountability + planning_provenance + cli_registry_sync). Per user-direction
2026-05-16 "update it to be a code quality layer as well" + BLOCK on failures +
BLOCK on new public surface without tests + B-275-class planning-discipline
forward-prevention + B189 closure cohort CLI_* registry sync mechanical
enforcement (2026-05-17 — 3rd instance of documentation-but-not-mechanically-
enforced gap pattern; closes empirical drift class structurally).
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
    """Assertion 5 (per B-309 Cycle 1 + B-315 + B-275-class + B189 + B-481 closure
    cohort): CHECKS registry has 9 Phase 1 checks. B-481 closure 2026-05-18 adds
    check_wc_line_count_claims as 9th check; Pitfall #9.h forward-prevention
    against stale `N lines per actual wc -l` claims (empirical anchor: CLAUDE.md
    L98 cited 127/117 stale post-refactor; actual 68/41)."""
    from tools.pre_commit_checks import (
        CHECKS,
        check_query_blindspots,
        check_pytest_changed_python_files,
        check_lint_security_types_changed_python_files,
        check_markdown_cross_refs,
        check_cli_compliance_d74_d75_d76,
        check_gap_accountability,
        check_planning_provenance,
        check_cli_registry_sync,
        check_wc_line_count_claims,
    )
    assert check_query_blindspots in CHECKS
    assert check_pytest_changed_python_files in CHECKS
    assert check_lint_security_types_changed_python_files in CHECKS
    assert check_markdown_cross_refs in CHECKS
    assert check_cli_compliance_d74_d75_d76 in CHECKS
    assert check_gap_accountability in CHECKS
    assert check_planning_provenance in CHECKS
    assert check_cli_registry_sync in CHECKS
    assert check_wc_line_count_claims in CHECKS
    assert len(CHECKS) == 9


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
    """Assertion 7 (per B-481 closure cohort): with no staged files, all 9 checks
    return passed (info severity)."""
    from tools.pre_commit_checks import run_all_checks
    results = run_all_checks(staged=[])
    assert len(results) == 9
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


def test_check_query_blindspots_no_basename_collision(monkeypatch):
    """Assertion 26 (per B-316 fix-cycle 2; review 🔴 BLOCK closure): same-basename
    files in different directories must NOT collide in temp file naming.
    Original bug: `DIFF_{Path(f).name}` produced silent content substitution +
    wrong-file diagnostic attribution. Hash-based naming fixes."""
    import tools.pre_commit_checks as pcc

    monkeypatch.setattr(pcc, "_staged_added_files", lambda: set())  # all MODIFIED
    monkeypatch.setattr(pcc, "_staged_diff_added_lines",
                        lambda f: f"diff content for {f}")

    captured_args: list[list[str]] = []
    def fake_run(args, **kwargs):
        captured_args.append(list(args))
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
    monkeypatch.setattr(pcc.subprocess, "run", fake_run)

    pcc.check_query_blindspots(staged=["tests/foo.py", "docs/foo.py"])
    assert len(captured_args) == 1
    file_paths = [a for a in captured_args[0] if "DIFF_" in str(a)]
    assert len(file_paths) == 2, f"Expected 2 distinct temp file paths; got {len(file_paths)}"
    assert file_paths[0] != file_paths[1], (
        "Temp file paths must NOT collide on basename "
        f"(got {file_paths[0]} == {file_paths[1]})"
    )


def test_check_query_blindspots_filters_binary_extensions(monkeypatch):
    """Assertion 27 (per B-316 fix-cycle 2; review 🟡 IMPROVE closure): binary
    extensions (.png/.pdf/.exe/etc) filtered before scan loop. Prevents scanning
    binary blobs that produce garbled output."""
    import tools.pre_commit_checks as pcc

    monkeypatch.setattr(pcc, "_staged_added_files", lambda: {"image.png", "doc.md"})
    captured_args: list[list[str]] = []
    def fake_run(args, **kwargs):
        captured_args.append(list(args))
        return type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
    monkeypatch.setattr(pcc.subprocess, "run", fake_run)

    pcc.check_query_blindspots(staged=["image.png", "doc.md"])
    if captured_args:
        args = captured_args[0]
        assert "image.png" not in args, "Binary file should not be scanned"
        assert "doc.md" in args, "Text file should be scanned"


def test_check_query_blindspots_all_binary_returns_info(monkeypatch):
    """Assertion 28 (per B-316 fix-cycle 2): all-binary staged scope returns info pass
    (no scan invoked)."""
    import tools.pre_commit_checks as pcc

    def should_not_run(*a, **kw):
        raise AssertionError("subprocess.run should NOT be invoked when all files are binary")
    monkeypatch.setattr(pcc.subprocess, "run", should_not_run)

    result = pcc.check_query_blindspots(staged=["x.png", "y.exe", "z.zip"])
    assert result.passed
    assert result.severity == "info"
    assert "binary" in result.diagnostic.lower()


def test_check_query_blindspots_binary_extensions_constant_present():
    """Assertion 29 (per B-316 fix-cycle 2): module exports binary-extension allowlist."""
    import tools.pre_commit_checks as pcc
    assert hasattr(pcc, "QUERY_BLINDSPOTS_BINARY_EXTENSIONS")
    bins = pcc.QUERY_BLINDSPOTS_BINARY_EXTENSIONS
    assert ".png" in bins
    assert ".pdf" in bins
    assert ".exe" in bins
    assert ".md" not in bins
    assert ".py" not in bins


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


# ---------------------------------------------------------------------------
# Check 7: planning-provenance section in *PLAN*.md files (B-275-class)
# ---------------------------------------------------------------------------

def test_check_planning_provenance_no_plan_files_staged_returns_info():
    """Assertion 30 (per B-275-class): no *PLAN*.md staged → info pass (skip)."""
    from tools.pre_commit_checks import check_planning_provenance
    result = check_planning_provenance(staged_files=[
        "tools/foo.py",
        "docs/migration/some_doc.md",
        "CLAUDE.md",
    ])
    assert result.passed
    assert result.severity == "info"
    assert "no *PLAN*.md files staged" in result.diagnostic


def test_check_planning_provenance_plan_file_with_provenance_passes(tmp_path, monkeypatch):
    """Assertion 31 (per B-275-class): plan file with §0 provenance header → PASS."""
    import tools.pre_commit_checks as pcc

    plan_file = tmp_path / "NEXT_STEPS_PLAN_2026-05-17.md"
    plan_file.write_text(
        "# Next Steps Plan\n\n"
        "## §0. Planning session provenance\n\n"
        "Trigger: 'Let's plan the next round'\n"
        "Scope: PS-1 (architectural change)\n"
        "Skills applied: udm-planning-session-startup, udm-decision-recorder\n\n"
        "## §1. Scope\n\nFoo bar.\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(pcc, "REPO_ROOT", tmp_path)
    result = pcc.check_planning_provenance(staged_files=["NEXT_STEPS_PLAN_2026-05-17.md"])
    assert result.passed, f"Expected pass; got: {result.diagnostic}"
    assert result.severity == "info"
    assert "§0 Planning session provenance" in result.diagnostic


def test_check_planning_provenance_plan_file_missing_provenance_blocks(tmp_path, monkeypatch):
    """Assertion 32 (per B-275-class): plan file without §0 provenance header → BLOCK."""
    import tools.pre_commit_checks as pcc

    plan_file = tmp_path / "MARKDOWN_REFACTOR_PLAN.md"
    plan_file.write_text(
        "# Markdown Refactor Plan\n\n"
        "## §1. Scope\n\n"
        "Some content but no provenance section.\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(pcc, "REPO_ROOT", tmp_path)
    result = pcc.check_planning_provenance(staged_files=["MARKDOWN_REFACTOR_PLAN.md"])
    assert not result.passed
    assert result.severity == "block"
    assert "MARKDOWN_REFACTOR_PLAN.md" in result.diagnostic
    assert "§0. Planning session provenance" in result.diagnostic
    assert "1b00755" in result.diagnostic  # empirical anchor cited


def test_check_planning_provenance_glob_case_insensitive(tmp_path, monkeypatch):
    """Assertion 33 (per B-275-class): glob matches *plan*.md / *PLAN*.md / *Plan*.md."""
    import tools.pre_commit_checks as pcc
    from tools.pre_commit_checks import _is_planning_doc

    # Direct helper test — basename case-insensitive substring match
    assert _is_planning_doc("MARKDOWN_REFACTOR_PLAN.md")
    assert _is_planning_doc("next_steps_plan_2026-05-17.md")
    assert _is_planning_doc("My-Refactor-Plan.md")
    assert _is_planning_doc("docs/migration/PHASE_X_DEEP_DIVE_PLAN.md")
    assert _is_planning_doc("tools/migration-plan-2026.md")
    # Non-matches
    assert not _is_planning_doc("CLAUDE.md")
    assert not _is_planning_doc("docs/migration/HANDOFF.md")
    assert not _is_planning_doc("tools/foo.py")
    assert not _is_planning_doc("plan.txt")  # not .md

    # End-to-end: 3 case variants, all without provenance → all blocked
    (tmp_path / "FOO_PLAN.md").write_text("# Foo Plan\n## Stuff\n", encoding="utf-8")
    (tmp_path / "bar_plan.md").write_text("# Bar Plan\n## Stuff\n", encoding="utf-8")
    (tmp_path / "Baz-Plan.md").write_text("# Baz Plan\n## Stuff\n", encoding="utf-8")

    monkeypatch.setattr(pcc, "REPO_ROOT", tmp_path)
    result = pcc.check_planning_provenance(
        staged_files=["FOO_PLAN.md", "bar_plan.md", "Baz-Plan.md"]
    )
    assert not result.passed
    assert result.severity == "block"
    # All three files surfaced as missing
    assert "FOO_PLAN.md" in result.diagnostic
    assert "bar_plan.md" in result.diagnostic
    assert "Baz-Plan.md" in result.diagnostic


def test_check_planning_provenance_in_checks_registry():
    """Assertion 34 (per B-275-class; updated B-481 closure cohort 2026-05-18):
    CHECKS registry contains check_planning_provenance."""
    from tools.pre_commit_checks import CHECKS, check_planning_provenance
    assert check_planning_provenance in CHECKS
    # 9th entry per B-481 closure cohort (added check_wc_line_count_claims as 9th)
    assert len(CHECKS) == 9


# ---------------------------------------------------------------------------
# Check 8: CLI_* registry sync for staged tools/*.py (B189 closure cohort
# empirical anchor; B-317 cascade-tools drift class)
# ---------------------------------------------------------------------------

def test_check_cli_registry_sync_no_tools_files_returns_info():
    """Assertion 35 (per B189 closure cohort): no tools/*.py staged → info pass (skip)."""
    from tools.pre_commit_checks import check_cli_registry_sync
    result = check_cli_registry_sync(staged_files=[
        "docs/migration/some_doc.md",
        "CLAUDE.md",
        "tests/tier0/test_foo.py",
    ])
    assert result.passed
    assert result.severity == "info"
    assert "no tools/*.py files staged" in result.diagnostic


def test_check_cli_registry_sync_tool_with_event_type_in_registry_passes(tmp_path, monkeypatch):
    """Assertion 36 (per B189 closure cohort): tool declaring CLI_* EVENT_TYPE
    that IS present in CLAUDE.md L207 registry → PASS."""
    import tools.pre_commit_checks as pcc

    # Synthetic tools/ directory + tool file
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    tool_file = tools_dir / "fake_tool.py"
    tool_file.write_text(
        '"""Fake tool."""\n'
        'EVENT_TYPE = "CLI_FAKE_TOOL"\n'
        'EXIT_SUCCESS = 0\n',
        encoding="utf-8",
    )

    # Synthetic CLAUDE.md with L207 region containing the CLI_FAKE_TOOL token
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text(
        "Some preamble.\n\n"
        "**EventType families registered**:\n"
        "- **CLI_\\*** (1 tools) — one row per CLI invocation. "
        "CLI_FAKE_TOOL (1; per `tools/fake_tool.py` test).\n"
        "- **CYCLE_\\*** — pipeline cycle lifecycle.\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(pcc, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(pcc, "CLAUDE_MD_PATH", claude_md)

    result = pcc.check_cli_registry_sync(staged_files=["tools/fake_tool.py"])
    assert result.passed, f"Expected pass; got: {result.diagnostic}"
    assert result.severity == "info"


def test_check_cli_registry_sync_tool_with_event_type_missing_blocks(tmp_path, monkeypatch):
    """Assertion 37 (per B189 closure cohort): tool declaring CLI_* EVENT_TYPE
    NOT present in CLAUDE.md L207 registry → BLOCK."""
    import tools.pre_commit_checks as pcc

    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    tool_file = tools_dir / "missing_tool.py"
    tool_file.write_text(
        '"""Missing tool."""\n'
        'EVENT_TYPE = "CLI_MISSING_TOOL"\n'
        'EXIT_SUCCESS = 0\n',
        encoding="utf-8",
    )

    # CLAUDE.md has the CLI_* family bullet but CLI_MISSING_TOOL not listed
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text(
        "Some preamble.\n\n"
        "**EventType families**:\n"
        "- **CLI_\\*** (1 tools) — CLI_OTHER_TOOL (1; per `tools/other.py`).\n"
        "- **CYCLE_\\*** — pipeline cycle lifecycle.\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(pcc, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(pcc, "CLAUDE_MD_PATH", claude_md)

    result = pcc.check_cli_registry_sync(staged_files=["tools/missing_tool.py"])
    assert not result.passed
    assert result.severity == "block"
    assert "missing_tool.py" in result.diagnostic
    assert "CLI_MISSING_TOOL" in result.diagnostic
    assert "L207" in result.diagnostic
    assert "B189" in result.diagnostic  # empirical anchor cited


def test_check_cli_registry_sync_non_cli_event_type_skipped(tmp_path, monkeypatch):
    """Assertion 38 (per B189 closure cohort): tool with EVENT_TYPE that is NOT
    CLI_* prefix → silently skipped (only CLI_* enforced)."""
    import tools.pre_commit_checks as pcc

    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    tool_file = tools_dir / "library_module.py"
    # Library module declares non-CLI EVENT_TYPE; should be skipped
    tool_file.write_text(
        '"""Library module."""\n'
        'EVENT_TYPE = "PARQUET_VERIFY"\n'
        'EXIT_SUCCESS = 0\n',
        encoding="utf-8",
    )

    # CLAUDE.md without any registry that lists PARQUET_VERIFY in CLI_* region
    claude_md = tmp_path / "CLAUDE.md"
    claude_md.write_text(
        "Some preamble.\n\n"
        "- **CLI_\\*** (0 tools) — empty.\n"
        "- **CYCLE_\\*** — pipeline cycle lifecycle.\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(pcc, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(pcc, "CLAUDE_MD_PATH", claude_md)

    result = pcc.check_cli_registry_sync(staged_files=["tools/library_module.py"])
    # Non-CLI_* EVENT_TYPE is treated as "no declaration to verify" → info pass
    assert result.passed, f"Expected pass for non-CLI EVENT_TYPE; got: {result.diagnostic}"
    assert result.severity == "info"


def test_check_cli_registry_sync_in_checks_registry():
    """Assertion 39 (per B189 closure cohort; updated B-481 cohort 2026-05-18):
    CHECKS registry contains check_cli_registry_sync; verify helper functions +
    module-level regex constants public-surface present."""
    import tools.pre_commit_checks as pcc
    from tools.pre_commit_checks import CHECKS, check_cli_registry_sync
    assert check_cli_registry_sync in CHECKS
    # 9th entry per B-481 closure cohort 2026-05-18 (was 8th pre-B-481)
    assert len(CHECKS) == 9
    # Module-level regex constants + helper functions present in public surface
    assert hasattr(pcc, "_EVENT_TYPE_DECLARATION_RE")
    assert hasattr(pcc, "_CLI_REGISTRY_REGION_START_RE")
    assert hasattr(pcc, "_extract_cli_event_type_from_file")
    assert hasattr(pcc, "_claude_md_l207_region_contains")
    assert hasattr(pcc, "CLAUDE_MD_PATH")
    # Helper roundtrip — extraction works on canonical pattern
    extracted = pcc._extract_cli_event_type_from_file(
        'EVENT_TYPE = "CLI_PRE_COMMIT_CHECKS"\n'
    )
    assert extracted == "CLI_PRE_COMMIT_CHECKS"
    # Function-scoped EVENT_TYPE NOT matched (line-anchored regex)
    nested = pcc._extract_cli_event_type_from_file(
        'def foo():\n    EVENT_TYPE = "CLI_NESTED"\n'
    )
    assert nested is None
    # Non-CLI prefix NOT matched
    non_cli = pcc._extract_cli_event_type_from_file(
        'EVENT_TYPE = "PARQUET_VERIFY"\n'
    )
    assert non_cli is None
