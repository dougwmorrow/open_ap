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


# ---------------------------------------------------------------------------
# B-451 closure: unresolved forward-prevention candidate tracking check
# (Agent 59 cycle-3 D72 convergence finding G2-A; empirical anchor commit
# `e76078c` GAP ANALYSIS section mentioned "B-409 + B-414 commit-message
# cascade-evidence audit" deferred candidate without corresponding BACKLOG
# opening)
# ---------------------------------------------------------------------------

def test_orphan_candidate_check_function_exists():
    """B-451 Assertion 32: check_unresolved_forward_prevention_candidates present."""
    import tools.check_commit_msg as ccm
    assert hasattr(ccm, "check_unresolved_forward_prevention_candidates")
    assert callable(ccm.check_unresolved_forward_prevention_candidates)


def test_orphan_candidate_check_module_level_constants_present():
    """B-451 Assertion 33: module-level patterns + dismissal phrases exposed
    as public-surface for inspection + extensibility."""
    import tools.check_commit_msg as ccm
    assert hasattr(ccm, "_ORPHAN_CANDIDATE_PHRASE_PATTERNS")
    assert hasattr(ccm, "_BACKLOG_BN_OPEN_RE")
    assert hasattr(ccm, "_DISMISSAL_PHRASES")
    assert hasattr(ccm, "_has_explicit_dismissal")
    # Spot-check dismissal phrases
    assert "dismissed because" in ccm._DISMISSAL_PHRASES
    assert "deferred to commit" in ccm._DISMISSAL_PHRASES
    assert "no B-N needed because" in ccm._DISMISSAL_PHRASES


def test_orphan_candidate_with_backlog_opening_passes():
    """B-451 Assertion 34: orphan-candidate phrase + matching BACKLOG diff
    opening B-N → PASS."""
    from tools.check_commit_msg import check_unresolved_forward_prevention_candidates
    msg = (
        "feat: change\n\n"
        "## GAP ANALYSIS\n"
        "- deferred (B-NEW-1 candidate for orphan tracking)\n"
    )
    backlog_diff = (
        "+- **B-451** (🟡 Open; MEDIUM; WSJF 1.5): orphan tracking check\n"
    )
    passed, findings = check_unresolved_forward_prevention_candidates(msg, backlog_diff)
    assert passed, f"Expected pass; findings: {findings}"
    assert findings == []


def test_orphan_candidate_without_backlog_warns():
    """B-451 Assertion 35: orphan-candidate phrase + NO BACKLOG diff → WARN."""
    from tools.check_commit_msg import check_unresolved_forward_prevention_candidates
    msg = (
        "feat: change\n\n"
        "## GAP ANALYSIS\n"
        "- deferred (B-NEW-1 candidate for orphan tracking)\n"
    )
    passed, findings = check_unresolved_forward_prevention_candidates(msg, "")
    assert not passed, "Expected WARN"
    assert len(findings) >= 1
    assert "orphan-candidate" in findings[0]


def test_orphan_candidate_tracked_as_tbd_with_backlog_passes():
    """B-451 Assertion 36: 'tracked as B-N TBD' phrase + BACKLOG diff → PASS."""
    from tools.check_commit_msg import check_unresolved_forward_prevention_candidates
    msg = (
        "build: extension\n\n"
        "## REVIEW\n"
        "- tracked as B-NEW-1 TBD pending validation\n"
    )
    backlog_diff = (
        "+- **B-452** (🟡 Open; LOW; WSJF 1.0): validation tracking\n"
    )
    passed, findings = check_unresolved_forward_prevention_candidates(msg, backlog_diff)
    assert passed, f"Expected pass; findings: {findings}"


def test_orphan_candidate_multiple_with_only_one_backlog_warns():
    """B-451 Assertion 37: 2 orphan phrases + only 1 BACKLOG opening → WARN
    (insufficient coverage)."""
    from tools.check_commit_msg import check_unresolved_forward_prevention_candidates
    msg = (
        "feat: cohort\n\n"
        "## GAP ANALYSIS\n"
        "- deferred (B-NEW-1 candidate for foo)\n"
        "- deferred (B-NEW-2 candidate for bar)\n"
    )
    backlog_diff = (
        "+- **B-451** (🟡 Open; MEDIUM; WSJF 1.5): foo check\n"
    )
    passed, findings = check_unresolved_forward_prevention_candidates(msg, backlog_diff)
    assert not passed
    assert len(findings) >= 1
    assert "unresolved" in findings[0].lower()


def test_orphan_candidate_explicit_dismissal_passes():
    """B-451 Assertion 38: orphan phrase + explicit 'dismissed because X' → PASS."""
    from tools.check_commit_msg import check_unresolved_forward_prevention_candidates
    msg = (
        "feat: change\n\n"
        "## GAP ANALYSIS\n"
        "- deferred (B-NEW-1 candidate for X) — dismissed because superseded by D-99\n"
    )
    passed, findings = check_unresolved_forward_prevention_candidates(msg, "")
    assert passed, f"Expected pass; findings: {findings}"


def test_orphan_candidate_explicit_deferral_target_passes():
    """B-451 Assertion 39: orphan phrase + explicit 'deferred to commit abc1234' → PASS."""
    from tools.check_commit_msg import check_unresolved_forward_prevention_candidates
    msg = (
        "feat: change\n\n"
        "## GAP ANALYSIS\n"
        "- deferred (B-NEW-1 candidate for Y); deferred to commit abc1234 next sprint\n"
    )
    passed, findings = check_unresolved_forward_prevention_candidates(msg, "")
    assert passed, f"Expected pass; findings: {findings}"


def test_orphan_candidate_inside_code_block_passes():
    """B-451 Assertion 40: orphan phrase INSIDE fenced code block → PASS
    (verbatim Agent reviewer output is acceptable; not a producer-authored claim)."""
    from tools.check_commit_msg import check_unresolved_forward_prevention_candidates
    msg = (
        "feat: change\n\n"
        "## REVIEW\n"
        "Quoting Agent A reviewer output:\n"
        "```\n"
        "deferred (B-NEW-1 candidate for X)\n"
        "```\n"
    )
    passed, findings = check_unresolved_forward_prevention_candidates(msg, "")
    assert passed, f"Expected pass for code-block orphan; findings: {findings}"


def test_orphan_candidate_inside_blockquote_passes():
    """B-451 Assertion 41: orphan phrase inside markdown blockquote (`> ...`)
    → PASS (retrospective citation of prior commit's text, not new orphan)."""
    from tools.check_commit_msg import check_unresolved_forward_prevention_candidates
    msg = (
        "feat: change\n\n"
        "## REVIEW\n"
        "> deferred (B-NEW-1 candidate for X) — prior commit text\n"
    )
    passed, findings = check_unresolved_forward_prevention_candidates(msg, "")
    assert passed, f"Expected pass for blockquote orphan; findings: {findings}"


def test_orphan_candidate_empirical_anchor_e76078c_warns():
    """B-451 Assertion 42 (EMPIRICAL ANCHOR per Agent 59 cycle-3 G2-A):
    reproduces the actual GAP ANALYSIS section pattern from commit `e76078c`
    that mentioned 'B-409 + B-414 commit-message cascade-evidence audit'
    deferred candidate without corresponding BACKLOG opening → WARN."""
    from tools.check_commit_msg import check_unresolved_forward_prevention_candidates
    msg = (
        "remediation(round-6): close Agent 58 gap-check 5 findings\n\n"
        "## GAP ANALYSIS\n\n"
        "G5: B-409 + B-414 commit-message cascade-evidence audit "
        "tracked as B-N TBD pending validation cycle.\n"
    )
    passed, findings = check_unresolved_forward_prevention_candidates(msg, "")
    assert not passed
    assert len(findings) >= 1


def test_orphan_candidate_no_phrases_passes():
    """B-451 Assertion 43: commit-msg with NO orphan-candidate phrases → PASS."""
    from tools.check_commit_msg import check_unresolved_forward_prevention_candidates
    msg = (
        "feat: clean change\n\n"
        "## GAP ANALYSIS\n"
        "All checks PASS; no orphans.\n"
    )
    passed, findings = check_unresolved_forward_prevention_candidates(msg, "")
    assert passed
    assert findings == []


def test_orphan_candidate_warn_does_not_block(tmp_path, monkeypatch):
    """B-451 Assertion 44 (CRITICAL): WARN-only contract — orphan-candidate
    finding must NOT cause exit BLOCK. Verifies WSJF MEDIUM warn-only spec."""
    import tools.check_commit_msg as ccm
    from tools.cascade_classifier import CommitClassification, CLASS_TYPO
    monkeypatch.setattr(ccm, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(ccm, "classify_commit",
                        lambda: CommitClassification(CLASS_TYPO, "test", True, False, 1, 2))
    # Force empty BACKLOG diff so subprocess returns "" deterministically
    monkeypatch.setattr(
        ccm.subprocess, "run",
        lambda *a, **kw: type("R", (), {"returncode": 0, "stdout": ""})(),
    )

    msg_path = tmp_path / "COMMIT_EDITMSG"
    msg_path.write_text(
        "docs: minor edit\n\n"
        "## GAP ANALYSIS\n"
        "- deferred (B-NEW-1 candidate for X)\n",
        encoding="utf-8",
    )
    rc = ccm.main(["check_commit_msg.py", str(msg_path), "--no-audit"])
    assert rc == ccm.EXIT_SUCCESS, "Orphan-candidate WARN must NOT block exit"


def test_orphan_candidate_audit_row_includes_findings(tmp_path, monkeypatch):
    """B-451 Assertion 45: orphan_candidate_findings included in audit-row
    JSON for forensic correlation (matches pytest_count_findings pattern)."""
    import tools.check_commit_msg as ccm
    from tools.cascade_classifier import CommitClassification, CLASS_TYPO
    monkeypatch.setattr(ccm, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(ccm, "classify_commit",
                        lambda: CommitClassification(CLASS_TYPO, "test", True, False, 1, 2))
    monkeypatch.setattr(
        ccm.subprocess, "run",
        lambda *a, **kw: type("R", (), {"returncode": 0, "stdout": ""})(),
    )

    msg_path = tmp_path / "COMMIT_EDITMSG"
    msg_path.write_text(
        "docs: minor edit\n\n"
        "## GAP ANALYSIS\n"
        "- deferred (B-NEW-1 candidate for X)\n",
        encoding="utf-8",
    )
    rc = ccm.main(["check_commit_msg.py", str(msg_path)])
    assert rc == ccm.EXIT_SUCCESS  # WARN does not block
    log_files = list((tmp_path / "_session_logs").glob("cli_check_commit_msg_*.log"))
    assert len(log_files) == 1
    content = log_files[0].read_text(encoding="utf-8")
    assert "orphan_candidate_findings" in content


def test_orphan_candidate_bncand_n_pattern_warns():
    """B-451 Assertion 46: 'BNcand-N' explicit cand syntax (per project history
    at commit `e76078c`) → WARN when no BACKLOG opening + no dismissal."""
    from tools.check_commit_msg import check_unresolved_forward_prevention_candidates
    msg = (
        "feat: change\n\n"
        "## REVIEW\n"
        "- BNcand-1 for future tracker enhancement\n"
    )
    passed, findings = check_unresolved_forward_prevention_candidates(msg, "")
    assert not passed
    assert len(findings) >= 1


# ---------------------------------------------------------------------------
# B-459 closure: CommitMsgCheck ABC abstraction
# (Agent 68 architectural design review 2026-05-18 Scope 2 Concern 2.1;
# extracted ABC + CheckResult dataclass + 4 subclass migrations + unified
# audit-row findings dict field)
# ---------------------------------------------------------------------------


def test_commit_msg_check_abc_class_present():
    """B-459 Assertion 49: CommitMsgCheck ABC class is exported + is abstract."""
    import tools.check_commit_msg as ccm
    from abc import ABC
    assert hasattr(ccm, "CommitMsgCheck")
    assert issubclass(ccm.CommitMsgCheck, ABC)


def test_commit_msg_check_is_abstract_cannot_instantiate():
    """B-459 Assertion 50: CommitMsgCheck cannot be instantiated directly
    (abstract scan() prevents instantiation per Python ABC contract)."""
    import tools.check_commit_msg as ccm
    with pytest.raises(TypeError):
        ccm.CommitMsgCheck()  # type: ignore[abstract]


def test_check_result_dataclass_shape():
    """B-459 Assertion 51: CheckResult dataclass has passed + findings fields."""
    import tools.check_commit_msg as ccm
    assert hasattr(ccm, "CheckResult")
    res = ccm.CheckResult(passed=True, findings=[])
    assert res.passed is True
    assert res.findings == []
    res2 = ccm.CheckResult(passed=False, findings=["finding 1", "finding 2"])
    assert res2.passed is False
    assert res2.findings == ["finding 1", "finding 2"]


def test_checks_registry_present():
    """B-459 Assertion 52 (updated B-470 2026-05-18): CHECKS registry list
    present + at least 4 check instances (B-470 cohort adds
    `inline_fix_claim` to bring count to 5)."""
    import tools.check_commit_msg as ccm
    assert hasattr(ccm, "CHECKS")
    assert isinstance(ccm.CHECKS, list)
    assert len(ccm.CHECKS) >= 4
    for check in ccm.CHECKS:
        assert isinstance(check, ccm.CommitMsgCheck)


def test_each_check_has_unique_name():
    """B-459 Assertion 53 (updated B-470 + B-458 + B-464 2026-05-18): each
    CHECKS entry has a unique name. Canonical name set evolved 4 → 5 → 6 → 7
    via B-470 (`inline_fix_claim`) + B-458 (`closure_annotation`) + B-464
    (`narrative_pytest_claim`) closures."""
    import tools.check_commit_msg as ccm
    names = [c.name for c in ccm.CHECKS]
    assert len(names) == len(set(names)), f"Duplicate check names: {names}"
    canonical_b464_names = {
        "exemption_phrase", "cascade_evidence", "pytest_count", "orphan_candidate",
        "inline_fix_claim", "closure_annotation", "narrative_pytest_claim",
    }
    assert set(names) == canonical_b464_names, (
        f"CHECKS names must equal {canonical_b464_names}; got {set(names)}"
    )


def test_each_check_has_severity_attribute():
    """B-459 Assertion 54: each CHECKS entry declares severity as WARN or BLOCK."""
    import tools.check_commit_msg as ccm
    for check in ccm.CHECKS:
        assert check.severity in ("WARN", "BLOCK"), (
            f"{check.name} severity {check.severity!r} not WARN or BLOCK"
        )


def test_each_check_has_requires_backlog_diff_attribute():
    """B-459 Assertion 55: each CHECKS entry declares requires_backlog_diff as bool."""
    import tools.check_commit_msg as ccm
    for check in ccm.CHECKS:
        assert isinstance(check.requires_backlog_diff, bool)


def test_block_checks_are_exemption_and_cascade():
    """B-459 Assertion 56 (updated B-470 + B-458 2026-05-18): BLOCK severity
    is exemption_phrase + cascade_evidence (preserves pre-B-459 BLOCK
    contract). WARN severity expanded 2 → 3 → 4 across B-470 + B-458
    closures."""
    import tools.check_commit_msg as ccm
    by_severity = {"BLOCK": set(), "WARN": set()}
    for check in ccm.CHECKS:
        by_severity[check.severity].add(check.name)
    assert by_severity["BLOCK"] == {"exemption_phrase", "cascade_evidence"}
    assert by_severity["WARN"] == {
        "pytest_count", "orphan_candidate", "inline_fix_claim",
        "closure_annotation", "narrative_pytest_claim",
    }


def test_only_orphan_check_requires_backlog_diff():
    """B-459 Assertion 57 (updated B-458 2026-05-18): checks needing BACKLOG
    staged-diff are now BOTH orphan_candidate (B-451) AND closure_annotation
    (B-458) — both batch through `_collect_staged_diffs`."""
    import tools.check_commit_msg as ccm
    needs_backlog = {c.name for c in ccm.CHECKS if c.requires_backlog_diff}
    assert needs_backlog == {"orphan_candidate", "closure_annotation"}


def test_exemption_phrase_check_scan_block_on_match():
    """B-459 Assertion 58: ExemptionPhraseCheck.scan() returns BLOCK CheckResult
    on exemption-phrase match (preserves B-303 trigger-phrase BLOCK contract).

    Per B-467 (2026-05-18): scan() now accepts OrchestrationContext instead
    of bare staged_diffs dict; this check ignores ctx (no external state needed)."""
    import tools.check_commit_msg as ccm
    check = ccm.ExemptionPhraseCheck()
    ctx = ccm.OrchestrationContext(staged_diffs={}, classification=None)
    result = check.scan("docs: applying Layer N+1 termination\n", ctx)
    assert not result.passed
    assert any("Layer N+1 termination" in f for f in result.findings)


def test_exemption_phrase_check_scan_pass_on_clean_msg():
    """B-459 Assertion 59: ExemptionPhraseCheck.scan() returns PASS on
    clean commit message with no exemption phrase.

    Per B-467 (2026-05-18): scan() now accepts OrchestrationContext."""
    import tools.check_commit_msg as ccm
    check = ccm.ExemptionPhraseCheck()
    ctx = ccm.OrchestrationContext(staged_diffs={}, classification=None)
    result = check.scan("feat: clean message\n", ctx)
    assert result.passed
    assert result.findings == []


def test_pytest_count_check_scan_pass_on_scoped_count():
    """B-459 Assertion 60: PytestCountDisambiguationCheck.scan() PASS on
    scoped pytest count (preserves B-449 pass behavior post-migration).

    Per B-467 (2026-05-18): scan() now accepts OrchestrationContext."""
    import tools.check_commit_msg as ccm
    check = ccm.PytestCountDisambiguationCheck()
    msg = (
        "feat: change\n\n"
        "## TEST\n"
        "- pytest tier0+tier1: 2418 pass / 10 skip / 0 fail (baseline preserved)\n"
    )
    ctx = ccm.OrchestrationContext(staged_diffs={}, classification=None)
    result = check.scan(msg, ctx)
    assert result.passed, f"Expected pass; findings: {result.findings}"


def test_pytest_count_check_scan_warn_on_bare_count():
    """B-459 Assertion 61: PytestCountDisambiguationCheck.scan() WARN on
    bare count (preserves B-449 WARN behavior post-migration).

    Per B-467 (2026-05-18): scan() now accepts OrchestrationContext."""
    import tools.check_commit_msg as ccm
    check = ccm.PytestCountDisambiguationCheck()
    msg = "feat: change\n\n## TEST\n- pytest 2418 pass\n"
    ctx = ccm.OrchestrationContext(staged_diffs={}, classification=None)
    result = check.scan(msg, ctx)
    assert not result.passed
    assert any("2418" in f for f in result.findings)


def test_orphan_check_scan_pass_with_backlog_opening_in_staged_diffs():
    """B-459 Assertion 62: UnresolvedForwardPreventionCandidatesCheck.scan()
    reads staged_diffs from OrchestrationContext for BACKLOG.md content
    (preserves B-451 PASS behavior when BACKLOG opening is present in
    staged diffs).

    Per B-467 (2026-05-18): scan() now reads ctx.staged_diffs instead of bare
    dict parameter; same lookup-by-key contract is preserved."""
    import tools.check_commit_msg as ccm
    check = ccm.UnresolvedForwardPreventionCandidatesCheck()
    msg = (
        "feat: change\n\n"
        "## GAP ANALYSIS\n"
        "- deferred (B-NEW-1 candidate for orphan tracking)\n"
    )
    ctx = ccm.OrchestrationContext(
        staged_diffs={
            "docs/migration/BACKLOG.md": (
                "+- **B-451** (🟡 Open; MEDIUM; WSJF 1.5): orphan tracking check\n"
            )
        },
        classification=None,
    )
    result = check.scan(msg, ctx)
    assert result.passed, f"Expected pass; findings: {result.findings}"


def test_orphan_check_scan_warn_without_backlog_in_staged_diffs():
    """B-459 Assertion 63: UnresolvedForwardPreventionCandidatesCheck.scan()
    WARN when BACKLOG.md not in staged_diffs and orphan-candidate cited
    (preserves B-451 WARN behavior post-migration).

    Per B-467 (2026-05-18): scan() reads ctx.staged_diffs."""
    import tools.check_commit_msg as ccm
    check = ccm.UnresolvedForwardPreventionCandidatesCheck()
    msg = (
        "feat: change\n\n"
        "## GAP ANALYSIS\n"
        "- deferred (B-NEW-1 candidate for orphan tracking)\n"
    )
    ctx = ccm.OrchestrationContext(
        staged_diffs={"docs/migration/BACKLOG.md": ""},
        classification=None,
    )
    result = check.scan(msg, ctx)
    assert not result.passed
    assert any("orphan-candidate" in f for f in result.findings)


def test_audit_row_unified_findings_dict_present(tmp_path, monkeypatch):
    """B-459 Assertion 64: audit-row JSON contains unified `findings` dict
    field keyed by check.name (NEW B-459 contract)."""
    import tools.check_commit_msg as ccm
    from tools.cascade_classifier import CommitClassification, CLASS_TYPO
    monkeypatch.setattr(ccm, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(ccm, "classify_commit",
                        lambda: CommitClassification(CLASS_TYPO, "test", True, False, 1, 2))
    monkeypatch.setattr(
        ccm.subprocess, "run",
        lambda *a, **kw: type("R", (), {"returncode": 0, "stdout": ""})(),
    )

    msg_path = tmp_path / "COMMIT_EDITMSG"
    msg_path.write_text(
        "docs: minor edit\n\n"
        "## TEST\n"
        "- pytest 2471 pass\n",
        encoding="utf-8",
    )
    rc = ccm.main(["check_commit_msg.py", str(msg_path)])
    assert rc == ccm.EXIT_SUCCESS  # WARN-only finding does not block
    log_files = list((tmp_path / "_session_logs").glob("cli_check_commit_msg_*.log"))
    assert len(log_files) == 1
    content = log_files[0].read_text(encoding="utf-8")
    # Unified findings dict is present per B-459 contract
    assert '"findings":' in content
    import json as _json
    # Parse the JSON line and verify findings dict shape
    parsed = _json.loads(content.strip().splitlines()[0])
    assert isinstance(parsed["findings"], dict)
    assert "pytest_count" in parsed["findings"]
    assert any("2471" in f for f in parsed["findings"]["pytest_count"])


def test_audit_row_per_check_top_level_mirrors_preserved(tmp_path, monkeypatch):
    """B-459 Assertion 65: per-check top-level mirror fields PRESERVED for
    backward compatibility (Tier 0 tests at assertions 30 + 45 already pin
    pytest_count_findings + orphan_candidate_findings top-level fields;
    those must still appear). B-459 is additive — adds `findings` dict
    without removing top-level mirrors."""
    import tools.check_commit_msg as ccm
    from tools.cascade_classifier import CommitClassification, CLASS_TYPO
    monkeypatch.setattr(ccm, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(ccm, "classify_commit",
                        lambda: CommitClassification(CLASS_TYPO, "test", True, False, 1, 2))
    monkeypatch.setattr(
        ccm.subprocess, "run",
        lambda *a, **kw: type("R", (), {"returncode": 0, "stdout": ""})(),
    )

    msg_path = tmp_path / "COMMIT_EDITMSG"
    msg_path.write_text(
        "docs: minor edit\n\n"
        "## GAP ANALYSIS\n"
        "- deferred (B-NEW-1 candidate for X)\n"
        "\n## TEST\n"
        "- pytest 2471 pass\n",
        encoding="utf-8",
    )
    rc = ccm.main(["check_commit_msg.py", str(msg_path)])
    assert rc == ccm.EXIT_SUCCESS
    log_files = list((tmp_path / "_session_logs").glob("cli_check_commit_msg_*.log"))
    assert len(log_files) == 1
    content = log_files[0].read_text(encoding="utf-8")
    # Per-check top-level mirrors must still appear for backward compatibility
    assert "matched_phrases" in content
    assert "missing_sections" in content
    assert "pytest_count_findings" in content
    assert "orphan_candidate_findings" in content


def test_warn_only_severity_does_not_block_exit_code(tmp_path, monkeypatch):
    """B-459 Assertion 66: orchestrator only flips exit code on severity=BLOCK
    findings (WARN findings present + cleanly classified anti-trigger commit
    -> EXIT_SUCCESS)."""
    import tools.check_commit_msg as ccm
    from tools.cascade_classifier import CommitClassification, CLASS_TYPO
    monkeypatch.setattr(ccm, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(ccm, "classify_commit",
                        lambda: CommitClassification(CLASS_TYPO, "test", True, False, 1, 2))
    monkeypatch.setattr(
        ccm.subprocess, "run",
        lambda *a, **kw: type("R", (), {"returncode": 0, "stdout": ""})(),
    )

    msg_path = tmp_path / "COMMIT_EDITMSG"
    msg_path.write_text(
        "docs: minor edit\n\n"
        "## TEST\n"
        "- pytest 2471 pass\n"
        "## GAP ANALYSIS\n"
        "- deferred (B-NEW-1 candidate for Y)\n",
        encoding="utf-8",
    )
    # Both pytest_count + orphan_candidate are WARN; no BLOCK findings
    rc = ccm.main(["check_commit_msg.py", str(msg_path), "--no-audit"])
    assert rc == ccm.EXIT_SUCCESS


def test_block_severity_check_flips_exit_code(tmp_path, monkeypatch):
    """B-459 Assertion 67: orchestrator flips exit code on severity=BLOCK
    finding (exemption-phrase BLOCK -> EXIT_BLOCKED)."""
    import tools.check_commit_msg as ccm
    msg_path = tmp_path / "COMMIT_EDITMSG"
    msg_path.write_text(
        "docs: applying Layer N+1 termination\n",
        encoding="utf-8",
    )
    rc = ccm.main(["check_commit_msg.py", str(msg_path), "--no-audit"])
    assert rc == ccm.EXIT_BLOCKED


def test_collect_staged_diffs_only_fetches_for_required_checks():
    """B-459 Assertion 68: `_collect_staged_diffs(checks)` only fetches files
    declared via `requires_backlog_diff=True` (avoids redundant subprocess
    calls when no check needs BACKLOG diff)."""
    import tools.check_commit_msg as ccm
    # Subset with NO check requiring backlog diff -> empty dict
    no_backlog_checks: list[ccm.CommitMsgCheck] = [
        ccm.ExemptionPhraseCheck(),
        ccm.PytestCountDisambiguationCheck(),
    ]
    diffs = ccm._collect_staged_diffs(no_backlog_checks)
    assert diffs == {}
    # Subset WITH orphan check -> fetches BACKLOG.md key (value may be empty
    # string if git unavailable in test env; key itself is the contract)
    with_backlog_checks: list[ccm.CommitMsgCheck] = [
        ccm.UnresolvedForwardPreventionCandidatesCheck(),
    ]
    diffs2 = ccm._collect_staged_diffs(with_backlog_checks)
    assert "docs/migration/BACKLOG.md" in diffs2


def test_top_level_compat_wrappers_preserved():
    """B-459 Assertion 69: top-level compatibility wrappers (the pre-B-459
    public-surface functions) are preserved + delegate to subclass scan().

    Per B-467 (2026-05-18): scan() now accepts OrchestrationContext, and the
    top-level wrappers construct an empty context for delegation."""
    import tools.check_commit_msg as ccm
    # Top-level wrappers must still exist
    assert callable(ccm.check_pytest_count_disambiguation)
    assert callable(ccm.check_unresolved_forward_prevention_candidates)
    # Top-level wrapper output must match subclass scan() output for the
    # same input (back-compat verification)
    msg = "feat: change\n\n## TEST\n- pytest 2471 pass\n"
    p1, f1 = ccm.check_pytest_count_disambiguation(msg)
    ctx = ccm.OrchestrationContext(staged_diffs={}, classification=None)
    res = ccm.PytestCountDisambiguationCheck().scan(msg, ctx)
    assert p1 == res.passed
    assert f1 == res.findings


def test_audit_row_findings_dict_omits_passed_checks(tmp_path, monkeypatch):
    """B-459 Assertion 70: audit-row `findings` dict only contains keys for
    checks that produced findings; PASSED checks omitted (lean payload)."""
    import tools.check_commit_msg as ccm
    from tools.cascade_classifier import CommitClassification, CLASS_TYPO
    monkeypatch.setattr(ccm, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(ccm, "classify_commit",
                        lambda: CommitClassification(CLASS_TYPO, "test", True, False, 1, 2))
    monkeypatch.setattr(
        ccm.subprocess, "run",
        lambda *a, **kw: type("R", (), {"returncode": 0, "stdout": ""})(),
    )

    msg_path = tmp_path / "COMMIT_EDITMSG"
    msg_path.write_text("feat: completely clean commit\n", encoding="utf-8")
    rc = ccm.main(["check_commit_msg.py", str(msg_path)])
    assert rc == ccm.EXIT_SUCCESS
    log_files = list((tmp_path / "_session_logs").glob("cli_check_commit_msg_*.log"))
    assert len(log_files) == 1
    import json as _json
    parsed = _json.loads(log_files[0].read_text(encoding="utf-8").strip().splitlines()[0])
    # No checks produced findings -> findings dict is empty
    assert parsed["findings"] == {}


def test_check_result_is_frozen_dataclass():
    """B-459 Assertion 71: CheckResult is a frozen dataclass (immutability
    prevents accidental mutation of orchestrator-collected results)."""
    import tools.check_commit_msg as ccm
    res = ccm.CheckResult(passed=True, findings=[])
    with pytest.raises((AttributeError, Exception)):
        # frozen=True -> attempting to mutate raises FrozenInstanceError
        # (which is a subclass of AttributeError in stdlib dataclasses)
        res.passed = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# B-466 closure: CommitMsgCheck.__init_subclass__ mechanical attribute validation
# (Agent 72 design review 2026-05-18 Concern 1.1; closes opaque AttributeError
# failure mode when subclass omits required class attribute)
# ---------------------------------------------------------------------------


def test_init_subclass_raises_on_missing_name():
    """B-466 Assertion 72: subclass omitting `name` class attribute raises
    TypeError at class-definition time (fail-fast)."""
    import tools.check_commit_msg as ccm
    with pytest.raises(TypeError) as exc_info:
        class BrokenNoName(ccm.CommitMsgCheck):  # type: ignore[misc]
            severity = "WARN"
            requires_backlog_diff = False
            def scan(self, commit_msg, ctx):
                return ccm.CheckResult(passed=True, findings=[])
    assert "name" in str(exc_info.value)


def test_init_subclass_raises_on_missing_severity():
    """B-466 Assertion 73: subclass omitting `severity` class attribute raises
    TypeError at class-definition time."""
    import tools.check_commit_msg as ccm
    with pytest.raises(TypeError) as exc_info:
        class BrokenNoSeverity(ccm.CommitMsgCheck):  # type: ignore[misc]
            name = "broken_severity"
            requires_backlog_diff = False
            def scan(self, commit_msg, ctx):
                return ccm.CheckResult(passed=True, findings=[])
    assert "severity" in str(exc_info.value)


def test_init_subclass_raises_on_missing_requires_backlog_diff():
    """B-466 Assertion 74: subclass omitting `requires_backlog_diff` class
    attribute raises TypeError at class-definition time."""
    import tools.check_commit_msg as ccm
    with pytest.raises(TypeError) as exc_info:
        class BrokenNoBacklog(ccm.CommitMsgCheck):  # type: ignore[misc]
            name = "broken_backlog"
            severity = "WARN"
            def scan(self, commit_msg, ctx):
                return ccm.CheckResult(passed=True, findings=[])
    assert "requires_backlog_diff" in str(exc_info.value)


def test_init_subclass_error_message_cites_all_missing_attrs():
    """B-466 Assertion 75: subclass omitting ALL 3 attrs has error message
    listing all 3 missing attribute names (not just the first)."""
    import tools.check_commit_msg as ccm
    with pytest.raises(TypeError) as exc_info:
        class BrokenAll(ccm.CommitMsgCheck):  # type: ignore[misc]
            def scan(self, commit_msg, ctx):
                return ccm.CheckResult(passed=True, findings=[])
    err_text = str(exc_info.value)
    assert "name" in err_text
    assert "severity" in err_text
    assert "requires_backlog_diff" in err_text
    assert "BrokenAll" in err_text


def test_init_subclass_passes_on_complete_subclass():
    """B-466 Assertion 76 (updated B-472 2026-05-18): valid subclass with
    all 4 class attributes (name + severity + requires_backlog_diff +
    requires_classification) instantiates cleanly (no TypeError raised)."""
    import tools.check_commit_msg as ccm

    class ValidCheck(ccm.CommitMsgCheck):
        name = "valid_check"
        severity: "Literal['WARN', 'BLOCK']" = "WARN"  # type: ignore[name-defined]  # noqa: F821
        requires_backlog_diff = False
        requires_classification = False
        def scan(self, commit_msg, ctx):
            return ccm.CheckResult(passed=True, findings=[])

    instance = ValidCheck()
    assert instance.name == "valid_check"
    assert instance.severity == "WARN"
    assert instance.requires_backlog_diff is False
    assert instance.requires_classification is False


def test_init_subclass_canonical_4_subclasses_have_all_attrs():
    """B-466 Assertion 77 (updated B-472 2026-05-18): the canonical 4 CHECKS
    subclasses each declare all 4 required class attributes (sanity check
    that B-459 migrations + B-466 + B-471 + B-472 validation co-exist;
    CHECKS instantiation does not raise).

    Per B-470 cohort (2026-05-18) — if InlineFixClaimVerificationCheck has
    been appended to CHECKS, len(ccm.CHECKS) increases to 5. Test pins
    the lower bound (>= 4) to remain compatible across B-470 landing."""
    import tools.check_commit_msg as ccm
    assert len(ccm.CHECKS) >= 4
    for check in ccm.CHECKS:
        assert hasattr(check, "name")
        assert hasattr(check, "severity")
        assert hasattr(check, "requires_backlog_diff")
        assert hasattr(check, "requires_classification")
        assert check.name  # non-empty string
        assert check.severity in ("WARN", "BLOCK")  # B-471 severity-value pin
        assert isinstance(check.requires_classification, bool)


# ---------------------------------------------------------------------------
# B-467 closure: OrchestrationContext dataclass — batch classify_commit() once
# (Agent 72 design review 2026-05-18 Concern 1.2; eliminates duplicate
# git-subprocess invocation in main() + CascadeEvidenceCheck.scan())
# ---------------------------------------------------------------------------


def test_orchestration_context_is_frozen_dataclass():
    """B-467 Assertion 78: OrchestrationContext is a frozen dataclass
    (immutability prevents accidental mutation during check iteration)."""
    import tools.check_commit_msg as ccm
    ctx = ccm.OrchestrationContext(staged_diffs={}, classification=None)
    with pytest.raises((AttributeError, Exception)):
        # frozen=True -> attempting to mutate raises FrozenInstanceError
        ctx.staged_diffs = {"foo": "bar"}  # type: ignore[misc]


def test_orchestration_context_has_staged_diffs_and_classification():
    """B-467 Assertion 79: OrchestrationContext has staged_diffs (dict) +
    classification (CommitClassification | None) fields."""
    import tools.check_commit_msg as ccm
    from tools.cascade_classifier import CommitClassification, CLASS_TYPO
    cls = CommitClassification(CLASS_TYPO, "test", True, False, 1, 2)
    ctx = ccm.OrchestrationContext(
        staged_diffs={"docs/migration/BACKLOG.md": "+ B-X opened"},
        classification=cls,
    )
    assert ctx.staged_diffs == {"docs/migration/BACKLOG.md": "+ B-X opened"}
    assert ctx.classification is cls


def test_orchestration_context_default_classification_is_none():
    """B-467 Assertion 80: classification defaults to None when not provided
    (back-compat for callers that only need staged_diffs)."""
    import tools.check_commit_msg as ccm
    ctx = ccm.OrchestrationContext(staged_diffs={})
    assert ctx.classification is None


def test_build_orchestration_context_skips_classify_when_no_cascade_check(monkeypatch):
    """B-467 Assertion 81: `_build_orchestration_context()` does NOT call
    `classify_commit()` when no CascadeEvidenceCheck is in the checks list."""
    import tools.check_commit_msg as ccm
    call_count = {"n": 0}

    def counting_classify():
        call_count["n"] += 1
        from tools.cascade_classifier import CommitClassification, CLASS_TYPO
        return CommitClassification(CLASS_TYPO, "test", True, False, 1, 2)
    monkeypatch.setattr(ccm, "classify_commit", counting_classify)

    # checks list WITHOUT CascadeEvidenceCheck -> classify_commit NOT called
    no_cascade_checks = [
        ccm.ExemptionPhraseCheck(),
        ccm.PytestCountDisambiguationCheck(),
    ]
    ctx = ccm._build_orchestration_context(no_cascade_checks)
    assert call_count["n"] == 0
    assert ctx.classification is None


def test_build_orchestration_context_calls_classify_when_cascade_check_present(monkeypatch):
    """B-467 Assertion 82: `_build_orchestration_context()` DOES call
    `classify_commit()` exactly ONCE when CascadeEvidenceCheck is in checks."""
    import tools.check_commit_msg as ccm
    from tools.cascade_classifier import CommitClassification, CLASS_TYPO
    call_count = {"n": 0}

    def counting_classify():
        call_count["n"] += 1
        return CommitClassification(CLASS_TYPO, "test", True, False, 1, 2)
    monkeypatch.setattr(ccm, "classify_commit", counting_classify)

    cascade_aware_checks = [
        ccm.ExemptionPhraseCheck(),
        ccm.CascadeEvidenceCheck(),
    ]
    ctx = ccm._build_orchestration_context(cascade_aware_checks)
    assert call_count["n"] == 1, "classify_commit should be called exactly once"
    assert ctx.classification is not None
    assert ctx.classification.classification == CLASS_TYPO


def test_build_orchestration_context_handles_classify_exception_gracefully(monkeypatch):
    """B-467 Assertion 83: `_build_orchestration_context()` swallows
    classify_commit exceptions and returns classification=None."""
    import tools.check_commit_msg as ccm

    def failing_classify():
        raise RuntimeError("simulated classifier failure")
    monkeypatch.setattr(ccm, "classify_commit", failing_classify)

    cascade_aware_checks = [ccm.CascadeEvidenceCheck()]
    ctx = ccm._build_orchestration_context(cascade_aware_checks)
    assert ctx.classification is None


def test_cascade_evidence_check_reads_classification_from_ctx(monkeypatch):
    """B-467 Assertion 84: CascadeEvidenceCheck.scan() reads ctx.classification
    and does NOT recompute via classify_commit()."""
    import tools.check_commit_msg as ccm
    from tools.cascade_classifier import CommitClassification, CLASS_SUBSTANTIVE

    call_count = {"n": 0}
    def counting_classify():
        call_count["n"] += 1
        return CommitClassification(
            CLASS_SUBSTANTIVE, "test", False, True, 5, 100
        )
    monkeypatch.setattr(ccm, "classify_commit", counting_classify)

    # Construct ctx with classification pre-cached; scan() should read from ctx
    # and NOT call counting_classify again
    cls = CommitClassification(CLASS_SUBSTANTIVE, "test", False, True, 5, 100)
    ctx = ccm.OrchestrationContext(staged_diffs={}, classification=cls)
    check = ccm.CascadeEvidenceCheck()
    # cascade missing on bare commit msg -> WARN/BLOCK finding
    result = check.scan("build: change\n\nNo cascade sections.\n", ctx)
    assert not result.passed
    # classify_commit should NOT have been called inside scan()
    assert call_count["n"] == 0, (
        "CascadeEvidenceCheck.scan should read ctx.classification, "
        "not call classify_commit redundantly"
    )


def test_main_calls_classify_commit_only_once(tmp_path, monkeypatch):
    """B-467 Assertion 85: main() invocation calls classify_commit() at most
    ONCE (was 2 pre-B-467: once in main() for audit-row + once in
    CascadeEvidenceCheck.scan())."""
    import tools.check_commit_msg as ccm
    from tools.cascade_classifier import CommitClassification, CLASS_SUBSTANTIVE
    monkeypatch.setattr(ccm, "REPO_ROOT", tmp_path)

    call_count = {"n": 0}
    def counting_classify():
        call_count["n"] += 1
        return CommitClassification(
            CLASS_SUBSTANTIVE, "test", False, True, 5, 100
        )
    monkeypatch.setattr(ccm, "classify_commit", counting_classify)

    msg_path = tmp_path / "COMMIT_EDITMSG"
    msg_path.write_text(
        "build: substantive\n\n"
        "## TEST\npytest passed\n\n"
        "## GAP ANALYSIS\ninline G1-G6 CLEAN\n\n"
        "## REVIEW\nSOUND\n",
        encoding="utf-8",
    )
    ccm.main(["check_commit_msg.py", str(msg_path), "--no-audit"])
    assert call_count["n"] == 1, (
        f"classify_commit should be called exactly once per main() invocation; "
        f"got {call_count['n']} calls"
    )


# ---------------------------------------------------------------------------
# B-468 closure: CommitMsgCheck.render_findings_to_stderr() method
# (Agent 72 design review 2026-05-18 Concern 1.3; eliminates per-check
# stderr-emission copy-paste in main())
# ---------------------------------------------------------------------------


def test_render_findings_to_stderr_method_exists_on_abc():
    """B-468 Assertion 86: render_findings_to_stderr is a public method on
    CommitMsgCheck ABC (base class default)."""
    import tools.check_commit_msg as ccm
    assert hasattr(ccm.CommitMsgCheck, "render_findings_to_stderr")
    assert callable(ccm.CommitMsgCheck.render_findings_to_stderr)


def test_render_findings_default_emits_severity_prefix(capsys):
    """B-468 Assertion 87: base class default render_findings_to_stderr emits
    `[<severity>] <name>: <finding>` to stderr."""
    import tools.check_commit_msg as ccm

    class TestCheck(ccm.CommitMsgCheck):
        name = "test_default_render"
        severity: "Literal['WARN', 'BLOCK']" = "WARN"  # type: ignore[name-defined]  # noqa: F821
        requires_backlog_diff = False
        requires_classification = False
        def scan(self, commit_msg, ctx):
            return ccm.CheckResult(passed=True, findings=[])

    TestCheck().render_findings_to_stderr(["finding 1", "finding 2"])
    captured = capsys.readouterr()
    assert "[WARN] test_default_render: finding 1" in captured.err
    assert "[WARN] test_default_render: finding 2" in captured.err


def test_render_findings_each_subclass_overrides_with_footer(capsys):
    """B-468 Assertion 88: each of the 4 canonical subclasses overrides
    render_findings_to_stderr to emit check-specific recommendation footer
    text (preserves pre-B-468 main() L650-714 verbatim stderr output)."""
    import tools.check_commit_msg as ccm

    # ExemptionPhraseCheck — must emit "exemption-claim trigger phrases" header
    ccm.ExemptionPhraseCheck().render_findings_to_stderr(["Layer N+1 termination"])
    err1 = capsys.readouterr().err
    assert "exemption-claim trigger phrases" in err1
    assert "udm-exemption-verifier" in err1

    # CascadeEvidenceCheck — must emit "Required structure" header
    ccm.CascadeEvidenceCheck().render_findings_to_stderr(["cascade-evidence missing"])
    err2 = capsys.readouterr().err
    assert "Required structure" in err2
    assert "## TEST" in err2
    assert "## GAP ANALYSIS" in err2
    assert "## REVIEW" in err2

    # PytestCountDisambiguationCheck — must emit "Disambiguate" footer
    ccm.PytestCountDisambiguationCheck().render_findings_to_stderr(
        ["pytest count '2418' cited without scope indicator"]
    )
    err3 = capsys.readouterr().err
    assert "Disambiguate" in err3
    assert "tier0+tier1" in err3
    assert "WARN (not BLOCK)" in err3

    # UnresolvedForwardPreventionCandidatesCheck — must emit "Resolution options"
    ccm.UnresolvedForwardPreventionCandidatesCheck().render_findings_to_stderr(
        ["orphan-candidate phrase cited"]
    )
    err4 = capsys.readouterr().err
    assert "Resolution options" in err4
    assert "BACKLOG.md" in err4


def test_main_iterates_render_findings_per_check_with_findings(tmp_path, monkeypatch, capsys):
    """B-468 Assertion 89: main() iterates CHECKS registry calling
    render_findings_to_stderr per check with findings (preserves stderr UX
    while eliminating per-check copy-paste in main())."""
    import tools.check_commit_msg as ccm
    from tools.cascade_classifier import CommitClassification, CLASS_TYPO
    monkeypatch.setattr(ccm, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(ccm, "classify_commit",
                        lambda: CommitClassification(CLASS_TYPO, "test", True, False, 1, 2))
    monkeypatch.setattr(
        ccm.subprocess, "run",
        lambda *a, **kw: type("R", (), {"returncode": 0, "stdout": ""})(),
    )

    msg_path = tmp_path / "COMMIT_EDITMSG"
    # Commit with pytest_count WARN finding
    msg_path.write_text(
        "docs: minor edit\n\n## TEST\n- pytest 2471 pass\n",
        encoding="utf-8",
    )
    rc = ccm.main(["check_commit_msg.py", str(msg_path), "--no-audit"])
    captured = capsys.readouterr()
    # The pytest-count check WARN footer should be emitted (per
    # PytestCountDisambiguationCheck.render_findings_to_stderr override)
    assert "Disambiguate by citing scope" in captured.err
    assert "2471" in captured.err
    assert rc == ccm.EXIT_SUCCESS  # WARN does not block


def test_main_omits_render_findings_for_passed_checks(tmp_path, monkeypatch, capsys):
    """B-468 Assertion 90: main() does NOT call render_findings_to_stderr for
    checks that returned PASS (lean stderr output; no empty per-check noise)."""
    import tools.check_commit_msg as ccm
    from tools.cascade_classifier import CommitClassification, CLASS_TYPO
    monkeypatch.setattr(ccm, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(ccm, "classify_commit",
                        lambda: CommitClassification(CLASS_TYPO, "test", True, False, 1, 2))
    monkeypatch.setattr(
        ccm.subprocess, "run",
        lambda *a, **kw: type("R", (), {"returncode": 0, "stdout": ""})(),
    )

    msg_path = tmp_path / "COMMIT_EDITMSG"
    msg_path.write_text("feat: completely clean commit\n", encoding="utf-8")
    rc = ccm.main(["check_commit_msg.py", str(msg_path), "--no-audit"])
    captured = capsys.readouterr()
    # No findings -> no per-check stderr emission
    assert "Disambiguate" not in captured.err
    assert "Resolution options" not in captured.err
    assert "Required structure" not in captured.err
    assert "exemption-claim trigger" not in captured.err
    assert rc == ccm.EXIT_SUCCESS


def test_block_severity_check_render_emits_blocked_header(tmp_path, monkeypatch, capsys):
    """B-468 Assertion 91: BLOCK-severity check (exemption_phrase) renders
    its [commit-msg BLOCKED] header via render_findings_to_stderr override
    (preserves the user-visible BLOCK stderr signal)."""
    import tools.check_commit_msg as ccm
    monkeypatch.setattr(ccm, "REPO_ROOT", tmp_path)
    msg_path = tmp_path / "COMMIT_EDITMSG"
    msg_path.write_text(
        "docs: applying Layer N+1 termination\n",
        encoding="utf-8",
    )
    rc = ccm.main(["check_commit_msg.py", str(msg_path), "--no-audit"])
    captured = capsys.readouterr()
    assert "commit-msg BLOCKED" in captured.err
    assert "Layer N+1 termination" in captured.err
    assert rc == ccm.EXIT_BLOCKED


# ---------------------------------------------------------------------------
# B-471 closure: __init_subclass__ severity-VALUE validation
# (Agent 76 design review 2026-05-18 Concern 1A; closes typo-class failure
# mode where misdeclared severity literal silently degrades to WARN)
# ---------------------------------------------------------------------------


def test_init_subclass_raises_on_invalid_severity_typo():
    """B-471 Assertion 92: subclass with severity='BLCK' (typo of 'BLOCK')
    raises TypeError at class-definition time (fail-fast). Pre-B-471 this
    would silently pass B-466 hasattr() check + silently degrade at
    main() `if check.severity == 'BLOCK'` (intended BLOCK becomes WARN)."""
    import tools.check_commit_msg as ccm
    with pytest.raises(TypeError) as exc_info:
        class BadSeverityTypo(ccm.CommitMsgCheck):  # type: ignore[misc]
            name = "bad_typo"
            severity = "BLCK"  # typo of "BLOCK"
            requires_backlog_diff = False
            requires_classification = False
            def scan(self, commit_msg, ctx):
                return ccm.CheckResult(passed=True, findings=[])
    err = str(exc_info.value)
    assert "BLCK" in err
    assert "valid severity literal" in err
    assert "B-471" in err  # cites closure


def test_init_subclass_raises_on_invalid_severity_case():
    """B-471 Assertion 93: subclass with severity='warn' (lowercase) raises
    TypeError. Severity values are case-sensitive literals; the orchestrator
    uses exact match `if check.severity == 'BLOCK'`, so lowercase silently
    degrades."""
    import tools.check_commit_msg as ccm
    with pytest.raises(TypeError) as exc_info:
        class BadSeverityCase(ccm.CommitMsgCheck):  # type: ignore[misc]
            name = "bad_case"
            severity = "warn"  # should be "WARN"
            requires_backlog_diff = False
            requires_classification = False
            def scan(self, commit_msg, ctx):
                return ccm.CheckResult(passed=True, findings=[])
    err = str(exc_info.value)
    assert "warn" in err
    assert "valid severity literal" in err


def test_init_subclass_accepts_canonical_severity_values():
    """B-471 Assertion 94: subclasses with severity='WARN' OR 'BLOCK' (the
    canonical Literal values) instantiate cleanly."""
    import tools.check_commit_msg as ccm

    class WarnCheck(ccm.CommitMsgCheck):
        name = "warn_canonical"
        severity = "WARN"
        requires_backlog_diff = False
        requires_classification = False
        def scan(self, commit_msg, ctx):
            return ccm.CheckResult(passed=True, findings=[])

    class BlockCheck(ccm.CommitMsgCheck):
        name = "block_canonical"
        severity = "BLOCK"
        requires_backlog_diff = False
        requires_classification = False
        def scan(self, commit_msg, ctx):
            return ccm.CheckResult(passed=True, findings=[])

    assert WarnCheck().severity == "WARN"
    assert BlockCheck().severity == "BLOCK"


# ---------------------------------------------------------------------------
# B-472 closure: declarative requires_classification attribute (replaces
# brittle isinstance(c, CascadeEvidenceCheck) dispatch in
# _build_orchestration_context)
# ---------------------------------------------------------------------------


def test_init_subclass_raises_on_missing_requires_classification():
    """B-472 Assertion 95: subclass omitting `requires_classification`
    attribute raises TypeError at class-definition time (fail-fast). Closes
    the failure mode where a future check needing classification ambient
    forgets to declare it + the brittle isinstance dispatch silently
    skips classify_commit()."""
    import tools.check_commit_msg as ccm
    with pytest.raises(TypeError) as exc_info:
        class BrokenNoReqClass(ccm.CommitMsgCheck):  # type: ignore[misc]
            name = "broken_req_class"
            severity = "WARN"
            requires_backlog_diff = False
            # requires_classification deliberately omitted
            def scan(self, commit_msg, ctx):
                return ccm.CheckResult(passed=True, findings=[])
    assert "requires_classification" in str(exc_info.value)


def test_cascade_evidence_check_declares_requires_classification_true():
    """B-472 Assertion 96: the canonical CascadeEvidenceCheck declares
    requires_classification=True (the ONLY current subclass that reads
    ctx.classification). Other 3 subclasses declare False."""
    import tools.check_commit_msg as ccm
    assert ccm.CascadeEvidenceCheck.requires_classification is True
    assert ccm.ExemptionPhraseCheck.requires_classification is False
    assert ccm.PytestCountDisambiguationCheck.requires_classification is False
    assert ccm.UnresolvedForwardPreventionCandidatesCheck.requires_classification is False


def test_build_orchestration_context_dispatches_on_requires_classification_attr(monkeypatch):
    """B-472 Assertion 97: _build_orchestration_context dispatches on the
    declarative requires_classification attribute, NOT on
    isinstance(c, CascadeEvidenceCheck). Verifies a non-CascadeEvidenceCheck
    subclass with requires_classification=True triggers classify_commit()."""
    import tools.check_commit_msg as ccm
    from tools.cascade_classifier import CommitClassification, CLASS_TYPO

    call_count = {"n": 0}
    def fake_classify():
        call_count["n"] += 1
        return CommitClassification(CLASS_TYPO, "test", True, False, 1, 2)
    monkeypatch.setattr(ccm, "classify_commit", fake_classify)

    # Hypothetical future check that needs classification but is NOT an
    # instance of CascadeEvidenceCheck — pre-B-472 isinstance dispatch
    # would silently skip classify_commit() for this check.
    class FutureClassificationCheck(ccm.CommitMsgCheck):
        name = "future_class_check"
        severity = "WARN"
        requires_backlog_diff = False
        requires_classification = True
        def scan(self, commit_msg, ctx):
            return ccm.CheckResult(passed=True, findings=[])

    ctx = ccm._build_orchestration_context([FutureClassificationCheck()])
    assert call_count["n"] == 1, (
        "classify_commit should fire when ANY check declares "
        "requires_classification=True, regardless of isinstance"
    )
    assert ctx.classification is not None
    assert ctx.classification.classification == CLASS_TYPO


def test_build_orchestration_context_skips_classify_when_no_check_needs_it(monkeypatch):
    """B-472 Assertion 98: when NO check in the list declares
    requires_classification=True, _build_orchestration_context does NOT
    call classify_commit() (avoids unnecessary git-subprocess invocation)."""
    import tools.check_commit_msg as ccm

    call_count = {"n": 0}
    def fake_classify():
        call_count["n"] += 1
        return None
    monkeypatch.setattr(ccm, "classify_commit", fake_classify)

    class NoClassNeeded(ccm.CommitMsgCheck):
        name = "no_class_needed"
        severity = "WARN"
        requires_backlog_diff = False
        requires_classification = False
        def scan(self, commit_msg, ctx):
            return ccm.CheckResult(passed=True, findings=[])

    ctx = ccm._build_orchestration_context([NoClassNeeded()])
    assert call_count["n"] == 0
    assert ctx.classification is None


# ---------------------------------------------------------------------------
# B-470 closure: InlineFixClaimVerificationCheck — claim-vs-reality drift
# forward-prevention (Agent 75 + Agent 71 2-event evidence base at commits
# 2a33efa + 20d998f; PRE-COMMIT reviewer inline-fix claims that did not land)
# ---------------------------------------------------------------------------


def test_inline_fix_claim_check_registered_in_checks():
    """B-470 Assertion 99: InlineFixClaimVerificationCheck registered in
    CHECKS list as the 5th check + severity is WARN (per WSJF MEDIUM)."""
    import tools.check_commit_msg as ccm
    names = [c.name for c in ccm.CHECKS]
    assert "inline_fix_claim" in names
    inline_check = next(c for c in ccm.CHECKS if c.name == "inline_fix_claim")
    assert inline_check.severity == "WARN"
    assert inline_check.requires_backlog_diff is False
    assert inline_check.requires_classification is False


def test_extract_reviewer_block_returns_empty_on_no_header():
    """B-470 Assertion 100: _extract_reviewer_block returns empty string
    when commit-msg has no reviewer-block header (no false claims to verify)."""
    import tools.check_commit_msg as ccm
    msg = "feat: ordinary commit\n\nNo reviewer block here.\n"
    assert ccm._extract_reviewer_block(msg) == ""


def test_extract_reviewer_block_finds_header():
    """B-470 Assertion 101: _extract_reviewer_block returns text starting
    at the reviewer-block header line."""
    import tools.check_commit_msg as ccm
    msg = (
        "feat: work\n\n"
        "Body text.\n\n"
        "Independent pre-commit reviewer Agent 74 (a7843efac4f1bd92d) "
        "per hard rule 14: fixes applied.\n"
        "1. fix one\n"
    )
    block = ccm._extract_reviewer_block(msg)
    assert "Agent 74" in block
    assert "1. fix one" in block
    assert "Body text" not in block  # block starts at header, prose excluded


def test_parse_inline_fix_claims_recognizes_badge_flip():
    """B-470 Assertion 102: parser classifies Pitfall #9.j numbered item as
    badge_flip kind with extracted B-N anchor + target file path."""
    import tools.check_commit_msg as ccm
    block = (
        "Independent pre-commit reviewer Agent 74 (a7843efac4f1bd92d):\n"
        "1. Pitfall #9.j: B-465 BACKLOG L492 leading badge \"X Open\" -> \"Y CLOSED 2026-05-18\"\n"
    )
    claims = ccm._parse_inline_fix_claims(block)
    assert len(claims) == 1
    assert claims[0]["kind"] == "badge_flip"
    assert claims[0]["bn"] == "B-465"
    assert claims[0]["target_path"] == "docs/migration/BACKLOG.md"
    assert claims[0]["fix_num"] == 1


def test_parse_inline_fix_claims_recognizes_transition():
    """B-470 Assertion 103: parser classifies Pitfall #9.l numbered item as
    transition kind with extracted before/after patterns (prose between
    closing quote and arrow is tolerated)."""
    import tools.check_commit_msg as ccm
    block = (
        "Independent pre-commit reviewer Agent 74 (a7843efac4f1bd92d):\n"
        "2. Pitfall #9.l: GLOSSARY L769 CommitMsgCheck signature description "
        "updated pre-B-467 \"scan(commit_msg, staged_diffs)\" -> post-B-467 "
        "\"scan(commit_msg, ctx: OrchestrationContext)\" + cite B-467 closure\n"
    )
    claims = ccm._parse_inline_fix_claims(block)
    assert len(claims) == 1
    assert claims[0]["kind"] == "transition"
    assert claims[0]["before"] == "scan(commit_msg, staged_diffs)"
    assert claims[0]["after"] == "scan(commit_msg, ctx: OrchestrationContext)"
    assert claims[0]["target_path"] == "docs/migration/GLOSSARY.md"


def test_parse_inline_fix_claims_handles_multiple_numbered_items():
    """B-470 Assertion 104: parser returns all numbered fix items in
    reviewer-block (each separated by newline + next number)."""
    import tools.check_commit_msg as ccm
    block = (
        "Independent pre-commit reviewer Agent 74 (a7843efac4f1bd92d):\n"
        "1. Pitfall #9.j: B-465 BACKLOG leading badge \"X Open\" -> \"Y CLOSED 2026-05-18\"\n"
        "2. Pitfall #9.l: GLOSSARY \"old-sig\" -> \"new-sig\"\n"
        "3. Pitfall #9.n: GLOSSARY missing 2 NEW B-467 surfaces\n"
    )
    claims = ccm._parse_inline_fix_claims(block)
    assert len(claims) == 3
    assert claims[0]["fix_num"] == 1
    assert claims[1]["fix_num"] == 2
    assert claims[2]["fix_num"] == 3
    assert {c["kind"] for c in claims} >= {"badge_flip", "transition", "missing_entries"}


def test_inline_fix_check_warns_on_unlanded_badge_flip(tmp_path, monkeypatch):
    """B-470 Assertion 105: when commit-msg claims B-NNN leading-badge
    flipped to ⚫ CLOSED but staged BACKLOG still contains the OLD `🟡 Open`
    leading-badge form for that B-N, the check returns WARN finding.

    Empirical anchor: commit 2a33efa Agent 70 B-459 leading-badge fix +
    commit 20d998f Agent 74 B-465 leading-badge fix BOTH cited but did NOT
    land in staged content."""
    import tools.check_commit_msg as ccm
    # Mock git show :BACKLOG.md to return staged content where B-465 leading
    # badge is still 🟡 Open (simulating the Agent 74 drift at commit 20d998f).
    staged_content = (
        "- **B-464** (⚫ CLOSED 2026-05-18; ...): work\n"
        "- **B-465** (🟡 Open; HIGH; WSJF 3.0): description\n"
    )
    monkeypatch.setattr(
        ccm, "_fetch_staged_content",
        lambda path: staged_content if "BACKLOG" in path else "",
    )
    commit_msg = (
        "build: substantive work\n\n"
        "Independent pre-commit reviewer Agent 74 (a7843efac4f1bd92d):\n"
        "1. Pitfall #9.j: B-465 BACKLOG L492 leading badge \"X Open\" -> "
        "\"Y CLOSED 2026-05-18\"\n"
    )
    check = ccm.InlineFixClaimVerificationCheck()
    ctx = ccm.OrchestrationContext(staged_diffs={}, classification=None)
    result = check.scan(commit_msg, ctx)
    assert result.passed is False
    assert any("B-465" in f for f in result.findings)
    assert any("Edit-overwrite drift" in f for f in result.findings)


def test_inline_fix_check_passes_when_badge_flip_landed(tmp_path, monkeypatch):
    """B-470 Assertion 106: when staged BACKLOG.md no longer contains the
    OLD `**B-NNN** (🟡 Open` leading-badge form (i.e., the fix LANDED), the
    check passes silently."""
    import tools.check_commit_msg as ccm
    staged_content = (
        "- **B-465** (⚫ CLOSED 2026-05-18; HIGH; WSJF 3.0): description\n"
    )
    monkeypatch.setattr(
        ccm, "_fetch_staged_content",
        lambda path: staged_content if "BACKLOG" in path else "",
    )
    commit_msg = (
        "build: substantive work\n\n"
        "Independent pre-commit reviewer Agent 74 (a7843efac4f1bd92d):\n"
        "1. Pitfall #9.j: B-465 BACKLOG L492 leading badge \"X Open\" -> "
        "\"Y CLOSED 2026-05-18\"\n"
    )
    check = ccm.InlineFixClaimVerificationCheck()
    ctx = ccm.OrchestrationContext(staged_diffs={}, classification=None)
    result = check.scan(commit_msg, ctx)
    assert result.passed is True
    assert result.findings == []


def test_inline_fix_check_warns_on_unlanded_transition(monkeypatch):
    """B-470 Assertion 107: when commit-msg cites a Pitfall #9.l transition
    "<old>" -> "<new>" but the staged target file does not contain "<new>",
    the check returns WARN finding.

    Empirical anchor: commit 20d998f Agent 74 GLOSSARY L769 signature
    description update cited but staged content still showed pre-B-467 sig."""
    import tools.check_commit_msg as ccm
    # Staged GLOSSARY content still shows the pre-B-467 signature
    staged_content = (
        "**CommitMsgCheck** | ABC for commit-msg check subclasses | "
        "`scan(commit_msg, staged_diffs) -> CheckResult` |\n"
    )
    monkeypatch.setattr(
        ccm, "_fetch_staged_content",
        lambda path: staged_content if "GLOSSARY" in path else "",
    )
    commit_msg = (
        "build: substantive work\n\n"
        "Independent pre-commit reviewer Agent 74 (a7843efac4f1bd92d):\n"
        "2. Pitfall #9.l: GLOSSARY L769 CommitMsgCheck signature description "
        "updated pre-B-467 \"scan(commit_msg, staged_diffs)\" -> post-B-467 "
        "\"scan(commit_msg, ctx: OrchestrationContext)\"\n"
    )
    check = ccm.InlineFixClaimVerificationCheck()
    ctx = ccm.OrchestrationContext(staged_diffs={}, classification=None)
    result = check.scan(commit_msg, ctx)
    assert result.passed is False
    # "after" pattern should appear in finding text
    assert any("scan(commit_msg, ctx: OrchestrationContext)" in f for f in result.findings)


def test_inline_fix_check_passes_when_transition_landed(monkeypatch):
    """B-470 Assertion 108: when staged target file contains the cited
    "<new>" pattern, the check passes."""
    import tools.check_commit_msg as ccm
    staged_content = (
        "**CommitMsgCheck** | ABC for commit-msg check subclasses | "
        "`scan(commit_msg, ctx: OrchestrationContext) -> CheckResult` |\n"
    )
    monkeypatch.setattr(
        ccm, "_fetch_staged_content",
        lambda path: staged_content if "GLOSSARY" in path else "",
    )
    commit_msg = (
        "build: substantive work\n\n"
        "Independent pre-commit reviewer Agent 74 (a7843efac4f1bd92d):\n"
        "2. Pitfall #9.l: GLOSSARY L769 CommitMsgCheck signature description "
        "updated pre-B-467 \"scan(commit_msg, staged_diffs)\" -> post-B-467 "
        "\"scan(commit_msg, ctx: OrchestrationContext)\"\n"
    )
    check = ccm.InlineFixClaimVerificationCheck()
    ctx = ccm.OrchestrationContext(staged_diffs={}, classification=None)
    result = check.scan(commit_msg, ctx)
    assert result.passed is True
    assert result.findings == []


def test_inline_fix_check_passes_silently_without_reviewer_block():
    """B-470 Assertion 109: commits with no reviewer-block header are not
    subject to the check (passes silently regardless of commit content)."""
    import tools.check_commit_msg as ccm
    commit_msg = (
        "fix: bug fix\n\nOrdinary commit with no PRE-COMMIT reviewer cited.\n"
    )
    check = ccm.InlineFixClaimVerificationCheck()
    ctx = ccm.OrchestrationContext(staged_diffs={}, classification=None)
    result = check.scan(commit_msg, ctx)
    assert result.passed is True
    assert result.findings == []


def test_inline_fix_check_render_findings_emits_warn_footer(capsys):
    """B-470 Assertion 110: render_findings_to_stderr emits WARN header +
    grep-verify recommendation footer (matches B-449/B-451 contract style)."""
    import tools.check_commit_msg as ccm
    check = ccm.InlineFixClaimVerificationCheck()
    check.render_findings_to_stderr([
        "Fix #1 (badge_flip) claims B-465 leading badge flipped...",
    ])
    err = capsys.readouterr().err
    assert "[commit-msg WARN]" in err
    assert "B-470" in err
    assert "Re-apply" in err
    assert "WARN (not BLOCK)" in err


def test_inline_fix_check_resolves_canonical_file_paths():
    """B-470 Assertion 111: _resolve_target_path maps canonical filenames
    in fix-body text to repo paths."""
    import tools.check_commit_msg as ccm
    # ".md" form preferred when both present
    assert ccm._resolve_target_path(
        "BACKLOG.md L492 leading badge"
    ) == "docs/migration/BACKLOG.md"
    assert ccm._resolve_target_path(
        "GLOSSARY L769 signature"
    ) == "docs/migration/GLOSSARY.md"
    assert ccm._resolve_target_path(
        "CURRENT_STATE.md L7 narrative"
    ) == "docs/migration/CURRENT_STATE.md"
    assert ccm._resolve_target_path(
        "CLAUDE.md hard rule 14"
    ) == "CLAUDE.md"
    # Returns None for unknown filename token
    assert ccm._resolve_target_path("unrelated prose with no canonical file") is None


def test_inline_fix_check_unknown_kind_skipped_silently(monkeypatch):
    """B-470 Assertion 112: numbered items with no parseable Pitfall marker
    AND no transition pattern are kind=unknown — skipped silently from
    verification (heuristic-parser conservative on unparseable claims;
    avoids false-positive WARN flood)."""
    import tools.check_commit_msg as ccm
    monkeypatch.setattr(ccm, "_fetch_staged_content", lambda path: "")
    commit_msg = (
        "build: work\n\n"
        "Independent pre-commit reviewer Agent 99 (deadbeef123):\n"
        "1. Some narrative without quoted transition or pitfall marker.\n"
    )
    check = ccm.InlineFixClaimVerificationCheck()
    ctx = ccm.OrchestrationContext(staged_diffs={}, classification=None)
    result = check.scan(commit_msg, ctx)
    assert result.passed is True
    assert result.findings == []


def test_inline_fix_check_passes_silently_on_missing_staged_content(monkeypatch):
    """B-475 Assertion 113: when `_fetch_staged_content` returns "" (file not
    in git index OR git unavailable), `scan()` skips the claim silently and
    returns PASS. Closes B-470 coverage gap surfaced by PRE-COMMIT reviewer
    `a7677c73928581c43` 2026-05-18 Scope 3.

    Pins conservative WARN heuristic intent (per scan() L997-998 graceful
    skip) against future refactor that could elevate "missing staged content"
    to a false-positive finding."""
    import tools.check_commit_msg as ccm
    # Mock _fetch_staged_content to ALWAYS return "" (file not staged)
    monkeypatch.setattr(ccm, "_fetch_staged_content", lambda path: "")
    commit_msg = (
        "build: substantive work\n\n"
        "Independent pre-commit reviewer Agent 99 (deadbeef123):\n"
        "1. Pitfall #9.j: B-999 BACKLOG L100 leading badge \"X Open\" -> "
        "\"Y CLOSED 2026-05-18\"\n"
        "2. Pitfall #9.l: GLOSSARY \"old-sig\" -> \"new-sig\"\n"
    )
    check = ccm.InlineFixClaimVerificationCheck()
    ctx = ccm.OrchestrationContext(staged_diffs={}, classification=None)
    result = check.scan(commit_msg, ctx)
    # Both claims would normally trigger findings if staged content showed
    # mismatch — but missing staged content means scan() cannot verify;
    # falls through to PASS per WARN heuristic intent.
    assert result.passed is True
    assert result.findings == []


# ---------------------------------------------------------------------------
# B-458 closure: ClosureAnnotationConsistencyCheck — retrospective B-N
# CLOSED claims without BACKLOG.md staged-diff closure annotation
# (1st-event empirical anchor commit `20fe33a`; orthogonal-failure-mode
# complement to B-451 forward-prevention)
# ---------------------------------------------------------------------------


def test_closure_annotation_check_registered_in_checks():
    """B-458 Assertion 114: ClosureAnnotationConsistencyCheck registered in
    CHECKS list as the 6th check + severity is WARN + requires_backlog_diff
    True (composes with orphan-candidate check via shared _collect_staged_diffs
    BACKLOG fetch)."""
    import tools.check_commit_msg as ccm
    names = [c.name for c in ccm.CHECKS]
    assert "closure_annotation" in names
    closure_check = next(c for c in ccm.CHECKS if c.name == "closure_annotation")
    assert closure_check.severity == "WARN"
    assert closure_check.requires_backlog_diff is True
    assert closure_check.requires_classification is False
    assert len(ccm.CHECKS) >= 6  # forward-compat lower bound


def test_closure_annotation_check_passes_on_no_closure_claims():
    """B-458 Assertion 115: commits with no B-N CLOSED claims in commit-msg
    return PASS regardless of BACKLOG diff state."""
    import tools.check_commit_msg as ccm
    commit_msg = "fix: bug fix\n\nOrdinary commit with no closure claims.\n"
    backlog_diff = "diff text containing **B-100** (⚫ CLOSED ..."
    ctx = ccm.OrchestrationContext(
        staged_diffs={"docs/migration/BACKLOG.md": backlog_diff},
        classification=None,
    )
    check = ccm.ClosureAnnotationConsistencyCheck()
    result = check.scan(commit_msg, ctx)
    assert result.passed is True
    assert result.findings == []


def test_closure_annotation_check_warns_on_unannotated_claim():
    """B-458 Assertion 116: commit-msg claiming `**B-409 CLOSED**` without
    corresponding BACKLOG.md staged-diff `**B-409** (⚫ CLOSED` annotation
    returns WARN finding (the EXACT 20fe33a empirical pattern)."""
    import tools.check_commit_msg as ccm
    commit_msg = (
        "docs(round-6): B-409 + B-414 CLOSED + B-408 closure annotation\n\n"
        "**B-409 CLOSED**: anti-trigger contradiction resolution.\n"
        "**B-414 CLOSED**: CARVE-OUT Tier 0 assertion.\n"
    )
    # BACKLOG diff has only B-408 annotation (B-409 + B-414 missing)
    backlog_diff = (
        "diff --git a/docs/migration/BACKLOG.md b/docs/migration/BACKLOG.md\n"
        "@@ -100,1 +100,1 @@\n"
        "+- **B-408** (⚫ CLOSED 2026-05-17; ...): ~~foo~~ **⚫ CLOSED**\n"
    )
    ctx = ccm.OrchestrationContext(
        staged_diffs={"docs/migration/BACKLOG.md": backlog_diff},
        classification=None,
    )
    check = ccm.ClosureAnnotationConsistencyCheck()
    result = check.scan(commit_msg, ctx)
    assert result.passed is False
    assert len(result.findings) == 2
    # Findings sorted by B-N numerically (B-409 first, B-414 second)
    assert "B-409" in result.findings[0]
    assert "B-414" in result.findings[1]
    assert all("20fe33a" in f for f in result.findings)


def test_closure_annotation_check_passes_when_all_annotated():
    """B-458 Assertion 117: commit-msg claiming `B-N CLOSED` for B-N values
    that ALL have corresponding BACKLOG.md `**B-N** (⚫ CLOSED` annotations
    returns PASS (positive case)."""
    import tools.check_commit_msg as ccm
    commit_msg = (
        "docs(round-6): B-408 + B-409 + B-414 CLOSED\n\n"
        "**B-408 CLOSED** + **B-409 CLOSED** + **B-414 CLOSED**\n"
    )
    backlog_diff = (
        "diff --git a/docs/migration/BACKLOG.md b/docs/migration/BACKLOG.md\n"
        "@@ -100,3 +100,3 @@\n"
        "+- **B-408** (⚫ CLOSED 2026-05-17; ...): ~~foo~~\n"
        "+- **B-409** (⚫ CLOSED 2026-05-17; ...): ~~bar~~\n"
        "+- **B-414** (⚫ CLOSED 2026-05-17; ...): ~~baz~~\n"
    )
    ctx = ccm.OrchestrationContext(
        staged_diffs={"docs/migration/BACKLOG.md": backlog_diff},
        classification=None,
    )
    check = ccm.ClosureAnnotationConsistencyCheck()
    result = check.scan(commit_msg, ctx)
    assert result.passed is True
    assert result.findings == []


def test_closure_annotation_check_recognizes_bare_form():
    """B-458 Assertion 118: bare form `B-NNN CLOSED` (no `**` bold) triggers
    claim detection PLUS conservative-fallback "no BACKLOG staged → PASS".

    Coverage scope (per PRE-COMMIT reviewer `a56030f11be41025b` 2026-05-18):
    `_CLOSURE_CLAIM_RE` bare-form alternation `\\bB-(\\d+)\\s+(?:⚫\\s*)?CLOSED\\b`
    only extracts the LAST B-N adjacent to CLOSED — so for shared-CLOSED
    patterns like `B-409 + B-414 CLOSED`, ONLY `B-414` is captured (B-409 is
    not adjacent to CLOSED). This test exercises BOTH the bare-form regex
    (matches B-414) AND the fallback path (no BACKLOG.md staged → return PASS
    before annotation checking). Full shared-CLOSED capture is tracked as
    B-478 LOW WSJF 0.5 (extend regex with lookahead/multi-BN-prefix branch)."""
    import tools.check_commit_msg as ccm
    commit_msg = "docs: B-409 + B-414 CLOSED\n\nBody text.\n"
    backlog_diff = ""  # No BACKLOG.md staged → cannot verify
    ctx = ccm.OrchestrationContext(
        staged_diffs={"docs/migration/BACKLOG.md": backlog_diff},
        classification=None,
    )
    check = ccm.ClosureAnnotationConsistencyCheck()
    result = check.scan(commit_msg, ctx)
    # No BACKLOG.md staged → silently pass (conservative WARN heuristic)
    assert result.passed is True


def test_closure_annotation_check_skips_blockquote_lines():
    """B-458 Assertion 119: B-NNN CLOSED phrases inside markdown blockquotes
    (lines starting with `>`) are NOT treated as claims (quoted reviewer
    output should not trigger false positives)."""
    import tools.check_commit_msg as ccm
    commit_msg = (
        "build: substantive work\n\n"
        "Reviewer cited:\n"
        "> Per prior commit history: B-409 CLOSED at commit abc123.\n"
        "> Per prior reviewer: **B-414 CLOSED** at commit def456.\n"
        "\n"
        "Body without any actual closure claims.\n"
    )
    ctx = ccm.OrchestrationContext(
        staged_diffs={"docs/migration/BACKLOG.md": "some diff text"},
        classification=None,
    )
    check = ccm.ClosureAnnotationConsistencyCheck()
    result = check.scan(commit_msg, ctx)
    # Claims inside `>` blockquote lines are filtered out → no claims to
    # verify → PASS.
    assert result.passed is True
    assert result.findings == []


def test_closure_annotation_check_skips_code_blocks():
    """B-458 Assertion 120: B-NNN CLOSED phrases inside fenced code blocks
    are stripped via `_strip_code_blocks` and do NOT trigger claim detection
    (preserves the canonical pattern shared with B-449 + B-451 checks)."""
    import tools.check_commit_msg as ccm
    commit_msg = (
        "build: work\n\n"
        "Example output from prior commit:\n"
        "```\n"
        "**B-409 CLOSED** + **B-414 CLOSED** — historical reference\n"
        "```\n"
        "Body without claims.\n"
    )
    ctx = ccm.OrchestrationContext(
        staged_diffs={"docs/migration/BACKLOG.md": "some diff text"},
        classification=None,
    )
    check = ccm.ClosureAnnotationConsistencyCheck()
    result = check.scan(commit_msg, ctx)
    assert result.passed is True


def test_closure_annotation_check_passes_with_no_backlog_staged():
    """B-458 Assertion 121: commit-msg has CLOSED claims but BACKLOG.md is
    NOT in staged diffs — cannot verify; conservative WARN heuristic passes
    silently (per `if not backlog_diff: return PASS` graceful fallback)."""
    import tools.check_commit_msg as ccm
    commit_msg = "docs: **B-409 CLOSED**\n\nBody.\n"
    ctx = ccm.OrchestrationContext(staged_diffs={}, classification=None)
    check = ccm.ClosureAnnotationConsistencyCheck()
    result = check.scan(commit_msg, ctx)
    assert result.passed is True


def test_closure_annotation_check_render_findings_emits_warn_footer(capsys):
    """B-458 Assertion 122: render_findings_to_stderr emits `[commit-msg WARN]`
    header + 20fe33a empirical-anchor reference + resolution-options footer
    (matches B-449/B-451/B-470 contract style)."""
    import tools.check_commit_msg as ccm
    check = ccm.ClosureAnnotationConsistencyCheck()
    check.render_findings_to_stderr([
        "B-409 CLOSED claim cited in commit-msg (line 2) but BACKLOG.md "
        "staged diff does NOT contain corresponding annotation...",
    ])
    err = capsys.readouterr().err
    assert "[commit-msg WARN]" in err
    assert "B-458" in err
    assert "20fe33a" in err
    assert "Stage the BACKLOG.md closure annotation" in err
    assert "WARN (not BLOCK)" in err


def test_closure_annotation_check_via_main_orchestrator(tmp_path, monkeypatch, capsys):
    """B-458 Assertion 123: end-to-end via `main()` orchestrator — commit-msg
    with unannotated CLOSED claim + BACKLOG.md staged-diff missing the
    annotation produces stderr WARN finding but does NOT BLOCK (exit code 0).

    Verifies B-459 abstraction + B-468 render_findings + new check integrate
    cleanly end-to-end."""
    import tools.check_commit_msg as ccm
    from tools.cascade_classifier import CommitClassification, CLASS_TYPO
    monkeypatch.setattr(ccm, "classify_commit",
                        lambda: CommitClassification(CLASS_TYPO, "test", True, False, 1, 2))
    backlog_diff = (
        "diff --git a/docs/migration/BACKLOG.md b/docs/migration/BACKLOG.md\n"
        "+- **B-408** (⚫ CLOSED 2026-05-17; ...): ~~foo~~\n"
    )
    def fake_subprocess_run(cmd, *args, **kwargs):
        r = type("R", (), {})()
        r.returncode = 0
        r.stdout = backlog_diff if "BACKLOG.md" in " ".join(cmd) else ""
        return r
    monkeypatch.setattr(ccm.subprocess, "run", fake_subprocess_run)

    msg_path = tmp_path / "COMMIT_EDITMSG"
    msg_path.write_text(
        "docs: B-409 CLOSED + B-414 CLOSED\n\n"
        "**B-409 CLOSED**: foo\n**B-414 CLOSED**: bar\n",
        encoding="utf-8",
    )
    rc = ccm.main(["check_commit_msg.py", str(msg_path), "--no-audit"])
    captured = capsys.readouterr()
    # WARN-only, does NOT block (exit code 0)
    assert rc == ccm.EXIT_SUCCESS
    # Stderr contains B-458 WARN footer + B-409 + B-414 mentions
    assert "B-458" in captured.err
    assert "B-409" in captured.err
    assert "B-414" in captured.err


# ---------------------------------------------------------------------------
# B-464 closure: NarrativePytestClaimVerificationCheck — anomalously high
# skip-count detection (META-IRONY pattern 1f74b72: 62 cited / 10 actual)
# ---------------------------------------------------------------------------


def test_narrative_pytest_check_registered_in_checks():
    """B-464 Assertion 124: NarrativePytestClaimVerificationCheck registered
    in CHECKS list as the 7th check + severity=WARN + requires_backlog_diff
    False + requires_classification False."""
    import tools.check_commit_msg as ccm
    names = [c.name for c in ccm.CHECKS]
    assert "narrative_pytest_claim" in names
    check = next(c for c in ccm.CHECKS if c.name == "narrative_pytest_claim")
    assert check.severity == "WARN"
    assert check.requires_backlog_diff is False
    assert check.requires_classification is False
    assert len(ccm.CHECKS) >= 7  # forward-compat lower bound


def test_narrative_pytest_check_passes_on_no_triplet():
    """B-464 Assertion 125: commits with no pytest count claims return PASS."""
    import tools.check_commit_msg as ccm
    commit_msg = "feat: ordinary commit\n\nNo pytest count narrative.\n"
    check = ccm.NarrativePytestClaimVerificationCheck()
    ctx = ccm.OrchestrationContext(staged_diffs={}, classification=None)
    result = check.scan(commit_msg, ctx)
    assert result.passed is True
    assert result.findings == []


def test_narrative_pytest_check_passes_on_normal_skip_count():
    """B-464 Assertion 126: commits citing `N pass / M skip` where M is
    within project baseline range return PASS (no anomaly)."""
    import tools.check_commit_msg as ccm
    commit_msg = "build: cohort closure\n\npytest 2763 pass / 10 skip / 0 fail.\n"
    check = ccm.NarrativePytestClaimVerificationCheck()
    ctx = ccm.OrchestrationContext(staged_diffs={}, classification=None)
    result = check.scan(commit_msg, ctx)
    assert result.passed is True
    assert result.findings == []


def test_narrative_pytest_check_warns_on_anomalous_skip_count():
    """B-464 Assertion 127: commits citing `N pass / M skip` where M exceeds
    anomaly threshold (20) return WARN finding (the EXACT 1f74b72 META-IRONY
    pattern: 62 skip cited / 10 actual)."""
    import tools.check_commit_msg as ccm
    commit_msg = "docs: cohort closure\n\npytest 2664 pass / 62 skip / 0 fail.\n"
    check = ccm.NarrativePytestClaimVerificationCheck()
    ctx = ccm.OrchestrationContext(staged_diffs={}, classification=None)
    result = check.scan(commit_msg, ctx)
    assert result.passed is False
    assert len(result.findings) == 1
    # Finding cites the anomalous count + empirical anchor
    assert "62" in result.findings[0]
    assert "1f74b72" in result.findings[0]
    assert "B-464" in result.findings[0]


def test_narrative_pytest_check_threshold_boundary_at_20():
    """B-464 Assertion 128: threshold is exclusive (skip=20 PASSES, skip=21
    triggers WARN). Pins the boundary against silent threshold drift."""
    import tools.check_commit_msg as ccm
    check = ccm.NarrativePytestClaimVerificationCheck()
    ctx = ccm.OrchestrationContext(staged_diffs={}, classification=None)

    msg_at_threshold = "build: \n\npytest 1000 pass / 20 skip / 0 fail.\n"
    result_at = check.scan(msg_at_threshold, ctx)
    assert result_at.passed is True, "skip=20 should NOT trigger (boundary)"

    msg_above_threshold = "build: \n\npytest 1000 pass / 21 skip / 0 fail.\n"
    result_above = check.scan(msg_above_threshold, ctx)
    assert result_above.passed is False, "skip=21 should trigger WARN"


def test_narrative_pytest_check_skips_code_blocks():
    """B-464 Assertion 129: pytest triplets inside fenced code blocks are
    stripped via `_strip_code_blocks` and do NOT trigger WARN (preserves
    canonical pattern shared with B-449 + B-451 + B-458 checks)."""
    import tools.check_commit_msg as ccm
    commit_msg = (
        "build: work\n\n"
        "Example output from prior commit:\n"
        "```\n"
        "pytest 1000 pass / 100 skip / 0 fail (verbatim historical output)\n"
        "```\n"
        "Body without anomalous claim.\n"
    )
    check = ccm.NarrativePytestClaimVerificationCheck()
    ctx = ccm.OrchestrationContext(staged_diffs={}, classification=None)
    result = check.scan(commit_msg, ctx)
    assert result.passed is True


def test_narrative_pytest_check_skips_blockquote_lines():
    """B-464 Assertion 130: pytest triplets inside markdown blockquote lines
    (`>` prefix) are NOT treated as new claims — quoted reviewer-output of
    historical counts should not trigger false positives."""
    import tools.check_commit_msg as ccm
    commit_msg = (
        "build: substantive work\n\n"
        "Reviewer cited:\n"
        "> Per prior cycle: pytest 2664 pass / 62 skip / 0 fail (historical).\n"
        "\n"
        "Body without anomalous claims.\n"
    )
    check = ccm.NarrativePytestClaimVerificationCheck()
    ctx = ccm.OrchestrationContext(staged_diffs={}, classification=None)
    result = check.scan(commit_msg, ctx)
    assert result.passed is True
    assert result.findings == []


def test_narrative_pytest_check_render_findings_emits_warn_footer(capsys):
    """B-464 Assertion 131: render_findings_to_stderr emits `[commit-msg WARN]`
    header + 1f74b72 empirical-anchor reference + re-verify recommendation."""
    import tools.check_commit_msg as ccm
    check = ccm.NarrativePytestClaimVerificationCheck()
    check.render_findings_to_stderr([
        "pytest skip-count 62 (line 3) exceeds anomaly threshold 20...",
    ])
    err = capsys.readouterr().err
    assert "[commit-msg WARN]" in err
    assert "B-464" in err
    assert "1f74b72" in err
    assert "Re-verify pytest counts" in err
    assert "WARN (not BLOCK)" in err


def test_narrative_pytest_check_via_main_orchestrator(tmp_path, monkeypatch, capsys):
    """B-464 Assertion 132: end-to-end via main() — commit-msg with anomalous
    skip-count produces WARN finding but does NOT BLOCK (exit code 0)."""
    import tools.check_commit_msg as ccm
    from tools.cascade_classifier import CommitClassification, CLASS_TYPO
    monkeypatch.setattr(ccm, "classify_commit",
                        lambda: CommitClassification(CLASS_TYPO, "test", True, False, 1, 2))
    monkeypatch.setattr(
        ccm.subprocess, "run",
        lambda *a, **kw: type("R", (), {"returncode": 0, "stdout": ""})(),
    )

    msg_path = tmp_path / "COMMIT_EDITMSG"
    # NOTE per B-488 closure 2026-05-18: commit-msg subject avoids anchor
    # markers (META-IRONY / empirical anchor / etc.) which would now correctly
    # trigger anchor-context suppression. This test verifies end-to-end
    # WARN-fire on a clean commit-msg (no empirical-anchor context); the
    # B-488 suppression behavior has dedicated tests below.
    msg_path.write_text(
        "docs: anomalous count pattern\n\npytest 2664 pass / 62 skip / 0 fail.\n",
        encoding="utf-8",
    )
    rc = ccm.main(["check_commit_msg.py", str(msg_path), "--no-audit"])
    captured = capsys.readouterr()
    # WARN-only; does NOT block (exit 0)
    assert rc == ccm.EXIT_SUCCESS
    assert "B-464" in captured.err
    assert "62" in captured.err


# ---------------------------------------------------------------------------
# B-488 closure: shared _is_empirical_anchor_context helper consolidates
# B-480 + B-487 (absorbed). Suppresses self-reference meta-pattern across
# ClosureAnnotationConsistencyCheck + NarrativePytestClaimVerificationCheck.
# ---------------------------------------------------------------------------


def test_is_empirical_anchor_context_helper_exported():
    """B-488 Assertion 133: `_is_empirical_anchor_context` is exported from
    `tools/check_commit_msg.py` for shared use across heuristic checks.
    Also verifies `_EMPIRICAL_ANCHOR_MARKERS` constant present."""
    import tools.check_commit_msg as ccm
    assert hasattr(ccm, "_is_empirical_anchor_context")
    assert callable(ccm._is_empirical_anchor_context)
    assert hasattr(ccm, "_EMPIRICAL_ANCHOR_MARKERS")
    assert isinstance(ccm._EMPIRICAL_ANCHOR_MARKERS, tuple)
    assert len(ccm._EMPIRICAL_ANCHOR_MARKERS) >= 10  # canonical marker set


def test_is_empirical_anchor_context_detects_5line_lookback():
    """B-488 Assertion 134: helper returns True when a marker line is within
    5-line lookback window of target index. Pins canonical 5-line scope."""
    import tools.check_commit_msg as ccm
    lines = [
        "body line 0",
        "empirical anchor commit `1f74b72`",  # marker at i=1
        "body line 2",
        "body line 3",
        "body line 4",
        "body line 5",  # at distance 4 from marker — within lookback
        "body line 6",  # at distance 5 from marker — within lookback (inclusive)
        "body line 7",  # at distance 6 from marker — OUTSIDE lookback
    ]
    assert ccm._is_empirical_anchor_context(lines, 5) is True
    assert ccm._is_empirical_anchor_context(lines, 6) is True
    assert ccm._is_empirical_anchor_context(lines, 7) is False


def test_is_empirical_anchor_context_detects_marker_on_target_line():
    """B-488 Assertion 135: helper returns True when target line itself
    contains a marker (lookback window includes target line)."""
    import tools.check_commit_msg as ccm
    lines = [
        "body line 0",
        "META-IRONY pattern: pytest 2664 pass / 62 skip / 0 fail",
    ]
    assert ccm._is_empirical_anchor_context(lines, 1) is True


def test_is_empirical_anchor_context_false_on_no_marker():
    """B-488 Assertion 136: helper returns False when no marker found in
    lookback window."""
    import tools.check_commit_msg as ccm
    lines = ["body 0", "body 1", "pytest 2664 pass / 62 skip / 0 fail"]
    assert ccm._is_empirical_anchor_context(lines, 2) is False


def test_is_empirical_anchor_context_marker_set_canonical():
    """B-488 Assertion 137: canonical marker set includes core terms
    derived from empirical false-positive events (B-480 + B-487 commits)."""
    import tools.check_commit_msg as ccm
    canonical_subset = {
        "empirical anchor commit",
        "1st-event empirical anchor",
        "META-IRONY",
        "historical reference",
        "Quote-cite from reviewer",
    }
    actual_markers = set(ccm._EMPIRICAL_ANCHOR_MARKERS)
    missing = canonical_subset - actual_markers
    assert not missing, f"Missing canonical markers: {missing}"


def test_closure_annotation_check_absorbs_b480_false_positive():
    """B-488 Assertion 138 (B-480 absorbed): ClosureAnnotationConsistencyCheck
    skips B-N CLOSED claims within empirical-anchor citation context.
    Empirical anchor: commit 133b212 (B-458 closure) fired WARN on quoted
    "B-414 CLOSED" inside REVIEW-section reviewer-output citation."""
    import tools.check_commit_msg as ccm
    commit_msg = (
        "build: substantive work\n"
        "\n"
        "## REVIEW\n"
        "Quote-cite from reviewer: per Mechanism A step 5 self-evidence:\n"
        "B-414 CLOSED claim at commit 20fe33a — historical context.\n"
    )
    backlog_diff = (
        "diff --git a/docs/migration/BACKLOG.md\n"
        "+- **B-999** (⚫ CLOSED 2026-05-18; ...): something else.\n"
    )
    ctx = ccm.OrchestrationContext(
        staged_diffs={"docs/migration/BACKLOG.md": backlog_diff},
        classification=None,
    )
    check = ccm.ClosureAnnotationConsistencyCheck()
    result = check.scan(commit_msg, ctx)
    # B-414 CLOSED claim is INSIDE empirical-anchor context (Quote-cite from reviewer marker)
    # → SUPPRESSED → result PASSES
    assert result.passed is True
    assert result.findings == []


def test_closure_annotation_check_fires_outside_anchor_context():
    """B-488 Assertion 139 (negative case for absorbed B-480): a B-N CLOSED
    claim OUTSIDE empirical-anchor context still fires WARN (existing B-458
    behavior preserved)."""
    import tools.check_commit_msg as ccm
    commit_msg = (
        "docs(round-6): B-409 CLOSED in current commit\n"
        "\n"
        "**B-409 CLOSED**: substantive fix landed.\n"
    )
    backlog_diff = (
        "diff --git a/docs/migration/BACKLOG.md\n"
        "+- **B-408** (⚫ CLOSED 2026-05-18; ...): other.\n"
    )
    ctx = ccm.OrchestrationContext(
        staged_diffs={"docs/migration/BACKLOG.md": backlog_diff},
        classification=None,
    )
    check = ccm.ClosureAnnotationConsistencyCheck()
    result = check.scan(commit_msg, ctx)
    # B-409 CLOSED outside anchor context → fires WARN (no annotation found)
    assert result.passed is False
    assert any("B-409" in f for f in result.findings)


def test_narrative_pytest_check_absorbs_b487_false_positive():
    """B-488 Assertion 140 (B-487 absorbed): NarrativePytestClaimVerificationCheck
    skips anomalous skip-counts within empirical-anchor citation context.
    Empirical anchor: commit c6ba969 (B-464 closure) fired WARN on quoted
    "62 skip" inside empirical-anchor prose citing 1f74b72 META-IRONY."""
    import tools.check_commit_msg as ccm
    commit_msg = (
        "build: cohort closure\n"
        "\n"
        "Empirical anchor commit `1f74b72` META-IRONY pattern:\n"
        "pytest 2664 pass / 62 skip / 0 fail (historical reference; the bug)\n"
    )
    check = ccm.NarrativePytestClaimVerificationCheck()
    ctx = ccm.OrchestrationContext(staged_diffs={}, classification=None)
    result = check.scan(commit_msg, ctx)
    # 62 skip is INSIDE empirical-anchor context → SUPPRESSED → PASSES
    assert result.passed is True
    assert result.findings == []


def test_narrative_pytest_check_fires_outside_anchor_context():
    """B-488 Assertion 141 (negative case for absorbed B-487): an anomalous
    skip-count OUTSIDE empirical-anchor context still fires WARN (existing
    B-464 behavior preserved)."""
    import tools.check_commit_msg as ccm
    commit_msg = (
        "build: current cohort\n"
        "\n"
        "pytest 2664 pass / 62 skip / 0 fail\n"
    )
    check = ccm.NarrativePytestClaimVerificationCheck()
    ctx = ccm.OrchestrationContext(staged_diffs={}, classification=None)
    result = check.scan(commit_msg, ctx)
    # 62 skip outside anchor context → fires WARN
    assert result.passed is False
    assert any("62" in f for f in result.findings)
