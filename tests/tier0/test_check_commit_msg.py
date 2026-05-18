"""Tier 0 smoke tests for tools/check_commit_msg.py (extracted from commit-msg hook per B-310).

Verifies the Python module that does the commit-msg exemption-phrase check
when invoked by the bash wrapper at .githooks/commit-msg.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))


def test_module_imports():
    """Assertion 1: module imports cleanly."""
    import tools.check_commit_msg  # noqa: F401


def test_main_function_present():
    """Assertion 2: main(argv) function defined."""
    import tools.check_commit_msg as ccm
    assert hasattr(ccm, "main")
    assert callable(ccm.main)


def test_main_empty_argv_returns_zero():
    """Assertion 3: main(['script']) returns 0 (no COMMIT_EDITMSG path provided)."""
    from tools.check_commit_msg import main
    assert main(["check_commit_msg.py"]) == 0


def test_main_nonexistent_path_returns_zero(tmp_path):
    """Assertion 4: main with nonexistent COMMIT_EDITMSG path returns 0 (graceful)."""
    from tools.check_commit_msg import main
    fake_path = tmp_path / "does-not-exist"
    assert main(["check_commit_msg.py", str(fake_path)]) == 0


def test_main_clean_message_returns_zero(tmp_path, monkeypatch):
    """Assertion 5: main with clean commit message returns 0 (anti-trigger commit;
    cascade-evidence not required per Phase 1B classifier)."""
    import tools.check_commit_msg as ccm
    from tools.cascade_classifier import CommitClassification, CLASS_TYPO
    monkeypatch.setattr(ccm, "classify_commit",
                        lambda: CommitClassification(CLASS_TYPO, "test", True, False, 1, 2))
    msg_path = tmp_path / "COMMIT_EDITMSG"
    msg_path.write_text("feat: add new feature\n\nNormal commit body.\n", encoding="utf-8")
    assert ccm.main(["check_commit_msg.py", str(msg_path), "--no-audit"]) == 0


def test_main_blocks_on_exemption_phrase(tmp_path):
    """Assertion 6: main with exemption-phrase message returns 1 (BLOCK)."""
    from tools.check_commit_msg import main
    msg_path = tmp_path / "COMMIT_EDITMSG"
    msg_path.write_text("docs: applying Layer N+1 termination\n", encoding="utf-8")
    assert main(["check_commit_msg.py", str(msg_path)]) == 1


def test_main_strips_git_comment_lines(tmp_path, monkeypatch):
    """Assertion 7: main ignores git-comment lines ('# <text>' but NOT '## markdown')."""
    import tools.check_commit_msg as ccm
    from tools.cascade_classifier import CommitClassification, CLASS_TYPO
    monkeypatch.setattr(ccm, "classify_commit",
                        lambda: CommitClassification(CLASS_TYPO, "test", True, False, 1, 2))
    msg_path = tmp_path / "COMMIT_EDITMSG"
    # Exemption phrase only in a comment line — should NOT block
    msg_path.write_text(
        "feat: real commit message\n\n# Comment: Layer N+1 termination is forbidden\n",
        encoding="utf-8",
    )
    assert ccm.main(["check_commit_msg.py", str(msg_path), "--no-audit"]) == 0


def test_main_preserves_markdown_headers_through_comment_strip(tmp_path, monkeypatch):
    """Assertion 7b (per B-317 Phase 1A): comment-strip preserves '## TEST' markdown
    headers (only strips '# <text>' git comments)."""
    import tools.check_commit_msg as ccm
    from tools.cascade_classifier import CommitClassification, CLASS_SUBSTANTIVE
    monkeypatch.setattr(ccm, "classify_commit",
                        lambda: CommitClassification(CLASS_SUBSTANTIVE, "test", False, True, 5, 100))
    msg_path = tmp_path / "COMMIT_EDITMSG"
    msg_path.write_text(
        "build: substantive change\n\n"
        "## TEST\npytest passed\n\n"
        "## GAP ANALYSIS\ninline CLEAN\n\n"
        "## REVIEW\nSOUND\n\n"
        "# Please enter commit message (this is a git comment)\n",
        encoding="utf-8",
    )
    # Should PASS — cascade sections preserved through comment-strip
    assert ccm.main(["check_commit_msg.py", str(msg_path), "--no-audit"]) == 0


def test_main_uses_canonical_phrases():
    """Assertion 8: module imports contains_exemption_phrase from canonical source."""
    hook_path = REPO_ROOT / "tools" / "check_commit_msg.py"
    content = hook_path.read_text(encoding="utf-8")
    assert "from tools.exemption_phrases import contains_exemption_phrase" in content
    assert "EXEMPTION_TRIGGER_PHRASES = [" not in content, (
        "check_commit_msg must NOT embed its own list (B-309 dedupe)"
    )


def test_d74_exit_codes_present():
    """Assertion 9 (per B-306): D74 exit-code constants present."""
    import tools.check_commit_msg as ccm
    assert ccm.EXIT_SUCCESS == 0
    assert ccm.EXIT_BLOCKED == 1


def test_event_type_constant():
    """Assertion 10 (per B-306): EVENT_TYPE constant per D76 audit-row contract."""
    import tools.check_commit_msg as ccm
    assert ccm.EVENT_TYPE == "CLI_CHECK_COMMIT_MSG"


def test_audit_row_written_on_clean_message(tmp_path, monkeypatch):
    """Assertion 11 (per B-306): per-invocation audit row written when not --no-audit."""
    import tools.check_commit_msg as ccm
    from tools.cascade_classifier import CommitClassification, CLASS_TYPO
    audit_dir = tmp_path / "_session_logs"
    monkeypatch.setattr(ccm, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(ccm, "classify_commit",
                        lambda: CommitClassification(CLASS_TYPO, "test", True, False, 1, 2))

    msg_path = tmp_path / "COMMIT_EDITMSG"
    msg_path.write_text("feat: clean commit\n", encoding="utf-8")

    rc = ccm.main(["check_commit_msg.py", str(msg_path)])
    assert rc == ccm.EXIT_SUCCESS
    assert audit_dir.is_dir()
    log_files = list(audit_dir.glob("cli_check_commit_msg_*.log"))
    assert len(log_files) == 1
    content = log_files[0].read_text(encoding="utf-8")
    assert '"event_type": "CLI_CHECK_COMMIT_MSG"' in content
    assert '"exit_code": 0' in content
    assert '"matched_phrases": []' in content


def test_audit_row_written_on_blocked_message(tmp_path, monkeypatch):
    """Assertion 12 (per B-306): audit row captures matched phrases when BLOCKED."""
    import tools.check_commit_msg as ccm
    audit_dir = tmp_path / "_session_logs"
    monkeypatch.setattr(ccm, "REPO_ROOT", tmp_path)

    msg_path = tmp_path / "COMMIT_EDITMSG"
    msg_path.write_text("docs: applying Layer N+1 termination\n", encoding="utf-8")

    rc = ccm.main(["check_commit_msg.py", str(msg_path)])
    assert rc == ccm.EXIT_BLOCKED
    log_files = list(audit_dir.glob("cli_check_commit_msg_*.log"))
    assert len(log_files) == 1
    content = log_files[0].read_text(encoding="utf-8")
    assert '"exit_code": 1' in content
    assert "Layer N+1 termination" in content


def test_no_audit_flag_skips_audit_write(tmp_path, monkeypatch):
    """Assertion 13 (per B-306): --no-audit flag suppresses audit-row write."""
    import tools.check_commit_msg as ccm
    from tools.cascade_classifier import CommitClassification, CLASS_TYPO
    monkeypatch.setattr(ccm, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(ccm, "classify_commit",
                        lambda: CommitClassification(CLASS_TYPO, "test", True, False, 1, 2))

    msg_path = tmp_path / "COMMIT_EDITMSG"
    msg_path.write_text("feat: clean\n", encoding="utf-8")

    rc = ccm.main(["check_commit_msg.py", str(msg_path), "--no-audit"])
    assert rc == ccm.EXIT_SUCCESS
    audit_dir = tmp_path / "_session_logs"
    if audit_dir.is_dir():
        assert not list(audit_dir.glob("cli_check_commit_msg_*.log"))


def test_cascade_classifier_imported(monkeypatch):
    """Assertion 14 (per B-317 Phase 1A): check_commit_msg imports cascade_classifier."""
    import tools.check_commit_msg as ccm
    assert ccm.classify_commit is not None
    assert ccm.has_cascade_evidence is not None


def test_cascade_evidence_required_for_substantive_commit(tmp_path, monkeypatch):
    """Assertion 15 (per B-317 Phase 1A): cascade-evidence missing on cascade-required commit
    blocks (EXIT_BLOCKED). Mock classify_commit to return SUBSTANTIVE."""
    import tools.check_commit_msg as ccm
    from tools.cascade_classifier import CommitClassification, CLASS_SUBSTANTIVE
    monkeypatch.setattr(ccm, "REPO_ROOT", tmp_path)

    def fake_classify():
        return CommitClassification(
            classification=CLASS_SUBSTANTIVE,
            rationale="test fixture; forced substantive",
            is_anti_trigger=False,
            cascade_required=True,
            staged_count=5,
            total_lines_changed=100,
        )
    monkeypatch.setattr(ccm, "classify_commit", fake_classify)

    msg_path = tmp_path / "COMMIT_EDITMSG"
    msg_path.write_text(
        "build: substantial change\n\nNo cascade-evidence section.\n",
        encoding="utf-8",
    )
    rc = ccm.main(["check_commit_msg.py", str(msg_path), "--no-audit"])
    assert rc == ccm.EXIT_BLOCKED


def test_cascade_evidence_present_passes(tmp_path, monkeypatch):
    """Assertion 16: cascade-required commit WITH all 3 sections passes."""
    import tools.check_commit_msg as ccm
    from tools.cascade_classifier import CommitClassification, CLASS_SUBSTANTIVE
    monkeypatch.setattr(ccm, "REPO_ROOT", tmp_path)

    def fake_classify():
        return CommitClassification(
            classification=CLASS_SUBSTANTIVE,
            rationale="test",
            is_anti_trigger=False,
            cascade_required=True,
            staged_count=5,
            total_lines_changed=100,
        )
    monkeypatch.setattr(ccm, "classify_commit", fake_classify)

    msg_path = tmp_path / "COMMIT_EDITMSG"
    msg_path.write_text(
        "build: change\n\n"
        "## TEST\npytest passed\n\n"
        "## GAP ANALYSIS\ninline G1-G6 CLEAN\n\n"
        "## REVIEW\ndesign-reviewer SOUND\n",
        encoding="utf-8",
    )
    rc = ccm.main(["check_commit_msg.py", str(msg_path), "--no-audit"])
    assert rc == ccm.EXIT_SUCCESS


def test_anti_trigger_commit_skips_cascade_check(tmp_path, monkeypatch):
    """Assertion 17: anti-trigger commit (typo / whitespace / badge-flip) does NOT
    require cascade-evidence; passes even with bare commit message."""
    import tools.check_commit_msg as ccm
    from tools.cascade_classifier import CommitClassification, CLASS_BADGE_FLIP
    monkeypatch.setattr(ccm, "REPO_ROOT", tmp_path)

    def fake_classify():
        return CommitClassification(
            classification=CLASS_BADGE_FLIP,
            rationale="badge-flip only",
            is_anti_trigger=True,
            cascade_required=False,
            staged_count=1,
            total_lines_changed=2,
        )
    monkeypatch.setattr(ccm, "classify_commit", fake_classify)

    msg_path = tmp_path / "COMMIT_EDITMSG"
    msg_path.write_text("chore: badge flip on B-123\n", encoding="utf-8")
    rc = ccm.main(["check_commit_msg.py", str(msg_path), "--no-audit"])
    assert rc == ccm.EXIT_SUCCESS


# ---------------------------------------------------------------------------
# B-449 closure: pytest-count disambiguation check
# (Agent 59 cycle-3 D72 convergence finding G3-K2; empirical anchor commit
# `e76078c` cited "2418 pass" as tier0+tier1 scope but baseline was 2471 from
# full-suite — 53-test discrepancy opaque without cross-reference)
# ---------------------------------------------------------------------------

def test_pytest_count_disambiguation_function_exists():
    """B-449 Assertion 18: check_pytest_count_disambiguation function present."""
    import tools.check_commit_msg as ccm
    assert hasattr(ccm, "check_pytest_count_disambiguation")
    assert callable(ccm.check_pytest_count_disambiguation)


def test_pytest_count_disambiguation_scope_cited_inline_passes():
    """B-449 Assertion 19: TEST section with scope+count on same line → PASS."""
    from tools.check_commit_msg import check_pytest_count_disambiguation
    msg = (
        "feat: change\n\n"
        "## TEST\n"
        "- pytest tier0+tier1: 2418 pass / 10 skip / 0 fail (baseline preserved)\n"
    )
    passed, findings = check_pytest_count_disambiguation(msg)
    assert passed, f"Expected pass; findings: {findings}"
    assert findings == []


def test_pytest_count_disambiguation_full_suite_invocation_passes():
    """B-449 Assertion 20: TEST section with full-suite pytest invocation → PASS."""
    from tools.check_commit_msg import check_pytest_count_disambiguation
    msg = (
        "build: substantive\n\n"
        "## TEST\n"
        "- .venv/Scripts/python.exe -m pytest tests/tier0 tests/tier1 "
        "tests/unit tests/property tests/regression: 2592 pass / 10 skip / 0 fail\n"
    )
    passed, findings = check_pytest_count_disambiguation(msg)
    assert passed, f"Expected pass; findings: {findings}"
    assert findings == []


def test_pytest_count_disambiguation_bare_count_warns():
    """B-449 Assertion 21: TEST section with bare count, no scope → WARN (failed)."""
    from tools.check_commit_msg import check_pytest_count_disambiguation
    msg = (
        "feat: change\n\n"
        "## TEST\n"
        "- pytest 2418 pass\n"
    )
    passed, findings = check_pytest_count_disambiguation(msg)
    assert not passed, f"Expected WARN finding; got passed=True"
    assert len(findings) >= 1
    assert "2418" in findings[0]


def test_pytest_count_disambiguation_multiple_counts_with_disambiguation_passes():
    """B-449 Assertion 22: TEST section with delta notation + scope cited → PASS."""
    from tools.check_commit_msg import check_pytest_count_disambiguation
    msg = (
        "feat: change\n\n"
        "## TEST\n"
        "- pytest tier0+tier1: 2418 pass (was 2415; +3 baseline restored after fix)\n"
    )
    passed, findings = check_pytest_count_disambiguation(msg)
    assert passed, f"Expected pass; findings: {findings}"


def test_pytest_count_disambiguation_no_pytest_count_passes():
    """B-449 Assertion 23: TEST section with no pytest counts → PASS (nothing to check)."""
    from tools.check_commit_msg import check_pytest_count_disambiguation
    msg = (
        "feat: change\n\n"
        "## TEST\n"
        "- Orchestrator smoke run completed cleanly\n"
        "- Manual end-to-end verification PASS\n"
    )
    passed, findings = check_pytest_count_disambiguation(msg)
    assert passed
    assert findings == []


def test_pytest_count_disambiguation_count_inside_code_block_passes():
    """B-449 Assertion 24: pytest count INSIDE fenced code block → PASS (verbatim
    output is acceptable; not a producer-authored bare count claim)."""
    from tools.check_commit_msg import check_pytest_count_disambiguation
    msg = (
        "feat: change\n\n"
        "## TEST\n"
        "Output of test run:\n"
        "```\n"
        "2589 passed, 10 skipped in 47.32s\n"
        "```\n"
    )
    passed, findings = check_pytest_count_disambiguation(msg)
    assert passed, f"Expected pass for code-block count; findings: {findings}"


def test_pytest_count_disambiguation_empirical_anchor_e76078c_passes():
    """B-449 Assertion 25 (EMPIRICAL ANCHOR per Agent 59 cycle-3 G3-K2):
    the actual TEST section text from commit `e76078c` DOES disambiguate
    via the explicit 'tier0+tier1' scope-indicator on the same line as the
    count. The check should PASS on this (which is why Agent 59's finding
    was about discipline drift across many OTHER bare-count commits like
    'pytest 2471 pass' — not specifically e76078c itself)."""
    from tools.check_commit_msg import check_pytest_count_disambiguation
    msg = (
        "remediation(round-6): close Agent 58 gap-check 5 findings\n\n"
        "## TEST\n\n"
        "Pre-cascade verification:\n"
        "- pytest tier0+tier1: 2418 pass / 10 skip / 0 fail (baseline preserved; no\n"
        "  code touched in this remediation cohort)\n"
    )
    passed, findings = check_pytest_count_disambiguation(msg)
    assert passed, f"Expected pass for e76078c canonical pattern; findings: {findings}"


def test_pytest_count_disambiguation_bare_baseline_count_warns():
    """B-449 Assertion 25b (BARE bare-count failure case from grep over real
    commit history): 'pytest 2471 pass' with NO scope-indicator anywhere → WARN.

    This is the canonical drift-class Agent 59 G3-K2 surfaced — many commits
    in this project's history used this bare pattern without scope-indicator,
    making the 53-test count discrepancy opaque to readers."""
    from tools.check_commit_msg import check_pytest_count_disambiguation
    msg = (
        "docs: minor edit\n\n"
        "## TEST\n"
        "- pytest 2471 pass\n"
        "- nothing else\n"
    )
    passed, findings = check_pytest_count_disambiguation(msg)
    assert not passed
    assert len(findings) >= 1
    assert "2471" in findings[0]


def test_pytest_count_disambiguation_baseline_preserved_phrase_passes():
    """B-449 Assertion 26: 'baseline preserved' phrase paired with count → PASS
    (canonical scope-equivalence indicator; 'baseline' implies 'same scope as
    prior baseline' which is sufficient disambiguation per real commit-history
    grep over project's commit log)."""
    from tools.check_commit_msg import check_pytest_count_disambiguation
    msg = (
        "docs: minor edit\n\n"
        "## TEST\n"
        "- pytest 2471 pass / 10 skip / 0 fail baseline preserved\n"
    )
    passed, findings = check_pytest_count_disambiguation(msg)
    assert passed, f"Expected pass for baseline-preserved phrase; findings: {findings}"


def test_pytest_count_disambiguation_explicit_tests_dir_passes():
    """B-449 Assertion 27: explicit tests/tier0/test_<name>.py path → PASS."""
    from tools.check_commit_msg import check_pytest_count_disambiguation
    msg = (
        "feat: new tool\n\n"
        "## TEST\n"
        "- pytest tests/tier0/test_my_tool.py: 39/39 PASS in 0.37s\n"
    )
    passed, findings = check_pytest_count_disambiguation(msg)
    assert passed, f"Expected pass; findings: {findings}"


def test_pytest_count_disambiguation_no_test_section_passes():
    """B-449 Assertion 28: commit with NO TEST section → PASS (check skipped)."""
    from tools.check_commit_msg import check_pytest_count_disambiguation
    msg = "chore: minor cleanup\n\nNothing to test.\n"
    passed, findings = check_pytest_count_disambiguation(msg)
    assert passed
    assert findings == []


def test_pytest_count_disambiguation_warn_does_not_block(tmp_path, monkeypatch):
    """B-449 Assertion 29 (CRITICAL): WARN-only behavior — bare pytest count
    must NOT cause final exit BLOCK. Verifies the check's WSJF MEDIUM warn-only
    contract per spec."""
    import tools.check_commit_msg as ccm
    from tools.cascade_classifier import CommitClassification, CLASS_TYPO
    monkeypatch.setattr(ccm, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(ccm, "classify_commit",
                        lambda: CommitClassification(CLASS_TYPO, "test", True, False, 1, 2))

    msg_path = tmp_path / "COMMIT_EDITMSG"
    msg_path.write_text(
        "docs: minor edit\n\n"
        "## TEST\n"
        "- pytest 2471 pass\n",
        encoding="utf-8",
    )
    rc = ccm.main(["check_commit_msg.py", str(msg_path), "--no-audit"])
    # Should be EXIT_SUCCESS — warn does NOT block exit code
    assert rc == ccm.EXIT_SUCCESS


def test_pytest_count_disambiguation_audit_row_includes_findings(tmp_path, monkeypatch):
    """B-449 Assertion 30: pytest_count_findings included in audit-row JSON for
    forensic correlation (matches missing_sections / matched_phrases pattern)."""
    import tools.check_commit_msg as ccm
    from tools.cascade_classifier import CommitClassification, CLASS_TYPO
    monkeypatch.setattr(ccm, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(ccm, "classify_commit",
                        lambda: CommitClassification(CLASS_TYPO, "test", True, False, 1, 2))

    msg_path = tmp_path / "COMMIT_EDITMSG"
    msg_path.write_text(
        "docs: minor edit\n\n"
        "## TEST\n"
        "- pytest 2471 pass\n",
        encoding="utf-8",
    )
    rc = ccm.main(["check_commit_msg.py", str(msg_path)])
    assert rc == ccm.EXIT_SUCCESS  # WARN does not block
    log_files = list((tmp_path / "_session_logs").glob("cli_check_commit_msg_*.log"))
    assert len(log_files) == 1
    content = log_files[0].read_text(encoding="utf-8")
    assert "pytest_count_findings" in content
    assert "2471" in content


def test_pytest_count_disambiguation_module_level_regex_present():
    """B-449 Assertion 31: module-level regex + scope-indicator tuple exposed
    as public-surface for inspection + extensibility."""
    import tools.check_commit_msg as ccm
    assert hasattr(ccm, "_PYTEST_COUNT_RE")
    assert hasattr(ccm, "_SCOPE_INDICATORS")
    assert hasattr(ccm, "_has_scope_indicator")
    assert hasattr(ccm, "_strip_code_blocks")
    # Spot-check scope-indicators
    indicators = ccm._SCOPE_INDICATORS
    assert "tier0+tier1" in indicators
    assert "full-suite" in indicators
    assert "baseline preserved" in indicators
    assert "python -m pytest" in indicators
