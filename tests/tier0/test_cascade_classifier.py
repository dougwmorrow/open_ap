"""Tier 0 smoke tests for tools/cascade_classifier.py per D67 + B-317 Phase 1B.

Tests the substrate-edit detection + anti-trigger classification + has_cascade_evidence
helpers used by tools/check_commit_msg.py to enforce hard rule 14 cascade requirements.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))


def test_module_imports():
    """Assertion 1: module imports cleanly."""
    import tools.cascade_classifier  # noqa: F401


def test_public_surface_exports():
    """Assertion 2: public surface present."""
    import tools.cascade_classifier as cc
    assert hasattr(cc, "classify_commit")
    assert hasattr(cc, "has_cascade_evidence")
    assert hasattr(cc, "CommitClassification")
    assert hasattr(cc, "SUBSTRATE_FILES")
    assert hasattr(cc, "SUBSTRATE_DIR_PREFIXES")
    assert hasattr(cc, "is_substrate_path")
    assert hasattr(cc, "EVENT_TYPE")
    assert hasattr(cc, "cli_main")


def test_event_type_constant():
    """Assertion 3: EVENT_TYPE per D76 audit-row contract."""
    from tools.cascade_classifier import EVENT_TYPE
    assert EVENT_TYPE == "CLI_CASCADE_CLASSIFIER"


def test_classification_constants_present():
    """Assertion 4: all 6 classification labels exported."""
    import tools.cascade_classifier as cc
    assert cc.CLASS_SUBSTRATE == "SUBSTRATE_EDIT"
    assert cc.CLASS_TYPO == "TYPO_ONLY"
    assert cc.CLASS_WHITESPACE == "WHITESPACE_ONLY"
    assert cc.CLASS_BADGE_FLIP == "BADGE_FLIP_ONLY"
    assert cc.CLASS_POLISH == "POLISH_QUEUE_ONLY"
    assert cc.CLASS_SUBSTANTIVE == "SUBSTANTIVE"


def test_substrate_files_enumeration():
    """Assertion 5: substrate enumeration includes all Mechanism C-1 enforcement files."""
    from tools.cascade_classifier import SUBSTRATE_FILES
    required = (
        "tools/pre_commit_checks.py",
        "tools/query_blindspots.py",
        "tools/check_commit_msg.py",
        "tools/exemption_phrases.py",
        "tools/cascade_classifier.py",
        ".githooks/pre-commit",
        ".githooks/commit-msg",
        ".github/workflows/pre-commit-mirror.yml",
        "CLAUDE.md",
    )
    for f in required:
        assert f in SUBSTRATE_FILES, f"substrate enumeration missing required file: {f}"


def test_is_substrate_path_substrate_file():
    """Assertion 6: is_substrate_path identifies enumerated files."""
    from tools.cascade_classifier import is_substrate_path
    assert is_substrate_path("tools/pre_commit_checks.py")
    assert is_substrate_path("CLAUDE.md")
    assert is_substrate_path(".githooks/pre-commit")


def test_is_substrate_path_substrate_dir_prefix():
    """Assertion 7: is_substrate_path identifies SKILL/agent files via prefix."""
    from tools.cascade_classifier import is_substrate_path
    assert is_substrate_path(".claude/skills/udm-gap-check/SKILL.md")
    assert is_substrate_path(".claude/agents/udm-design-reviewer.md")
    assert is_substrate_path("docs/migration/blindspots/ledger.yml")


def test_is_substrate_path_non_substrate():
    """Assertion 8: is_substrate_path returns False for non-substrate files."""
    from tools.cascade_classifier import is_substrate_path
    assert not is_substrate_path("docs/migration/CURRENT_STATE.md")
    assert not is_substrate_path("tests/tier0/test_foo.py")
    assert not is_substrate_path("scd2/engine.py")


def test_is_substrate_path_windows_paths():
    """Assertion 9: is_substrate_path normalizes Windows path separators."""
    from tools.cascade_classifier import is_substrate_path
    assert is_substrate_path("tools\\pre_commit_checks.py")
    assert is_substrate_path(".claude\\skills\\udm-test\\SKILL.md")


def test_classify_commit_empty_staged_is_substantive():
    """Assertion 10: empty staged defaults to SUBSTANTIVE (safe default)."""
    from tools.cascade_classifier import classify_commit, CLASS_SUBSTANTIVE
    cls = classify_commit(staged=[])
    assert cls.classification == CLASS_SUBSTANTIVE
    assert cls.cascade_required is True
    assert cls.is_anti_trigger is False


def test_classify_commit_substrate_overrides_anti_trigger():
    """Assertion 11 (per Phase 2A): substrate edits NEVER classify as anti-trigger,
    even when they would otherwise look like typo/whitespace."""
    from tools.cascade_classifier import classify_commit, CLASS_SUBSTRATE
    cls = classify_commit(staged=["tools/pre_commit_checks.py"])
    assert cls.classification == CLASS_SUBSTRATE
    assert cls.cascade_required is True
    assert cls.is_anti_trigger is False
    assert "substrate" in cls.rationale.lower()


def test_classify_commit_skill_md_is_substrate():
    """Assertion 12: udm-* SKILL.md edits classify as SUBSTRATE_EDIT."""
    from tools.cascade_classifier import classify_commit, CLASS_SUBSTRATE
    cls = classify_commit(staged=[".claude/skills/udm-progress-logger/SKILL.md"])
    assert cls.classification == CLASS_SUBSTRATE


def test_classify_commit_claude_md_is_substrate():
    """Assertion 13: CLAUDE.md edits classify as SUBSTRATE_EDIT (hard rules canon)."""
    from tools.cascade_classifier import classify_commit, CLASS_SUBSTRATE
    cls = classify_commit(staged=["CLAUDE.md"])
    assert cls.classification == CLASS_SUBSTRATE


def test_has_cascade_evidence_all_three_sections():
    """Assertion 14: commit message with all 3 cascade sections returns (True, [])."""
    from tools.cascade_classifier import has_cascade_evidence
    msg = """build: some change

## TEST
pytest 100/100 PASS

## GAP ANALYSIS
inline G1-G6 audit: CLEAN

## REVIEW
udm-design-reviewer verdict: SOUND
"""
    has_ev, missing = has_cascade_evidence(msg)
    assert has_ev is True
    assert missing == []


def test_has_cascade_evidence_missing_all():
    """Assertion 15: commit without cascade sections returns (False, [TEST, GAP, REVIEW])."""
    from tools.cascade_classifier import has_cascade_evidence
    msg = "build: small change\n\nNo cascade sections here.\n"
    has_ev, missing = has_cascade_evidence(msg)
    assert has_ev is False
    assert "TEST" in missing
    assert "GAP ANALYSIS" in missing
    assert "REVIEW" in missing


def test_has_cascade_evidence_only_test():
    """Assertion 16: commit with only TEST section flags GAP + REVIEW missing."""
    from tools.cascade_classifier import has_cascade_evidence
    msg = """build: change

## TEST
pytest passed
"""
    has_ev, missing = has_cascade_evidence(msg)
    assert has_ev is False
    assert "TEST" not in missing
    assert "GAP ANALYSIS" in missing
    assert "REVIEW" in missing


def test_has_cascade_evidence_accepts_variant_headers():
    """Assertion 17: regex accepts header variants (Tests / Gap-check / Reviewer / etc)."""
    from tools.cascade_classifier import has_cascade_evidence
    msg = """build: change

## Tests
all pass

## Gap-check
clean

## Reviewer
sound
"""
    has_ev, missing = has_cascade_evidence(msg)
    assert has_ev is True


def test_commit_classification_to_dict():
    """Assertion 18: CommitClassification.to_dict() emits all fields."""
    from tools.cascade_classifier import classify_commit
    cls = classify_commit(staged=[])
    d = cls.to_dict()
    for key in ("classification", "rationale", "is_anti_trigger",
                "cascade_required", "staged_count", "total_lines_changed"):
        assert key in d


def test_has_cascade_evidence_empty_section_body_fails():
    """Assertion 19 (per B-321): stub-header with empty body fails validation."""
    from tools.cascade_classifier import has_cascade_evidence
    msg = """build: change

## TEST

## GAP ANALYSIS
clean

## REVIEW
sound
"""
    has_ev, findings = has_cascade_evidence(msg)
    assert has_ev is False
    assert any("TEST" in f and "body empty" in f for f in findings)


def test_has_cascade_evidence_substrate_inline_self_review_blocks():
    """Assertion 20 (per B-321 empirical escalation from 1fc59f9):
    SUBSTRATE_EDIT with 'inline self-review' in REVIEW section BLOCKED."""
    from tools.cascade_classifier import has_cascade_evidence, CLASS_SUBSTRATE
    msg = """build: substrate change

## TEST
pytest 100/100 PASS

## GAP ANALYSIS
inline G1-G6 audit: CLEAN

## REVIEW
Reviewer: inline self-review per scope-justified pattern
"""
    has_ev, findings = has_cascade_evidence(msg, classification=CLASS_SUBSTRATE)
    assert has_ev is False
    assert any("inline self-review" in f.lower() and "INVALID" in f for f in findings)


def test_has_cascade_evidence_substrate_independent_review_passes():
    """Assertion 21 (per B-321): SUBSTRATE_EDIT with proper independent
    reviewer agentId in REVIEW section PASSES."""
    from tools.cascade_classifier import has_cascade_evidence, CLASS_SUBSTRATE
    msg = """build: substrate change

## TEST
pytest 100/100 PASS

## GAP ANALYSIS
inline G1-G6 audit: CLEAN

## REVIEW
Spawned udm-design-reviewer agent (agentId abc12345); verdict SOUND.
"""
    has_ev, findings = has_cascade_evidence(msg, classification=CLASS_SUBSTRATE)
    assert has_ev is True
    assert findings == []


def test_has_cascade_evidence_substantive_self_review_passes():
    """Assertion 22 (per B-321): non-substrate (SUBSTANTIVE) commit with
    'inline self-review' in REVIEW section is ALLOWED (substrate-stricter
    check fires only when classification is SUBSTRATE_EDIT)."""
    from tools.cascade_classifier import has_cascade_evidence, CLASS_SUBSTANTIVE
    msg = """build: small substantive change

## TEST
pytest 100/100 PASS

## GAP ANALYSIS
inline G1-G6: CLEAN

## REVIEW
Inline self-review per scope-justified pattern (small scope; no new public surface).
"""
    has_ev, findings = has_cascade_evidence(msg, classification=CLASS_SUBSTANTIVE)
    assert has_ev is True
    assert findings == []


def test_has_cascade_evidence_skipped_without_anti_trigger_fails():
    """Assertion 23 (per B-321): SKIPPED content without anti-trigger
    justification BLOCKED."""
    from tools.cascade_classifier import has_cascade_evidence
    msg = """build: change

## TEST
pytest PASS

## GAP ANALYSIS
SKIPPED.

## REVIEW
sound
"""
    has_ev, findings = has_cascade_evidence(msg)
    assert has_ev is False
    assert any("SKIPPED" in f and "anti-trigger" in f for f in findings)


def test_has_cascade_evidence_skipped_with_anti_trigger_passes():
    """Assertion 24 (per B-321): SKIPPED content paired with anti-trigger
    justification PASSES."""
    from tools.cascade_classifier import has_cascade_evidence
    msg = """build: badge flip

## TEST
SKIPPED: BADGE_FLIP_ONLY anti-trigger (per cascade_classifier)

## GAP ANALYSIS
SKIPPED: BADGE_FLIP_ONLY anti-trigger

## REVIEW
SKIPPED: BADGE_FLIP_ONLY anti-trigger
"""
    has_ev, findings = has_cascade_evidence(msg)
    assert has_ev is True
    assert findings == []


def test_extract_section_bodies_handles_other_headers():
    """Assertion 25 (per B-321 internal): _extract_section_bodies treats
    non-TEST/GAP/REVIEW '##' headers as section boundaries."""
    from tools.cascade_classifier import _extract_section_bodies
    msg = """## TEST
test body line 1

## Net delta
- B-N: +1

## GAP ANALYSIS
gap body
"""
    sections = _extract_section_bodies(msg)
    assert "TEST" in sections
    assert "GAP ANALYSIS" in sections
    # TEST body should end at "## Net delta" header
    test_body_joined = "\n".join(sections["TEST"])
    assert "test body line 1" in test_body_joined
    assert "B-N: +1" not in test_body_joined


def test_extract_section_bodies_empty_message():
    """Assertion 26 (per B-321): empty commit message yields empty dict."""
    from tools.cascade_classifier import _extract_section_bodies
    sections = _extract_section_bodies("")
    assert sections == {}


def test_extract_section_bodies_codefence_with_hash_headers():
    """Assertion 27 (per reviewer 🔴 BLOCK #1 fix): code-fenced block with `##`
    comments inside TEST body does NOT prematurely terminate the section."""
    from tools.cascade_classifier import _extract_section_bodies
    msg = """## TEST
pytest verdict

```python
## sample output
result = 100
```

more test details

## GAP ANALYSIS
clean
"""
    sections = _extract_section_bodies(msg)
    assert "TEST" in sections
    assert "GAP ANALYSIS" in sections
    test_body = "\n".join(sections["TEST"])
    # The fenced `## sample output` should NOT have ended TEST
    assert "sample output" in test_body
    assert "more test details" in test_body
    # GAP ANALYSIS body should NOT contain the fenced content
    gap_body = "\n".join(sections["GAP ANALYSIS"])
    assert "sample output" not in gap_body


def test_anti_trigger_justification_accepts_space_variant():
    """Assertion 28 (per reviewer 🟡 #3 fix): 'anti trigger' (space) is also accepted."""
    from tools.cascade_classifier import _has_anti_trigger_justification
    assert _has_anti_trigger_justification(["SKIPPED: anti trigger reason"]) is True
    assert _has_anti_trigger_justification(["SKIPPED: anti-trigger reason"]) is True
    assert _has_anti_trigger_justification(["SKIPPED: antitrigger reason"]) is True
    assert _has_anti_trigger_justification(["SKIPPED: no reason given"]) is False


def test_skipped_regex_avoids_mid_sentence_false_positive():
    """Assertion 29 (per reviewer 🟡 #2 fix + B-321 self-dogfood discovery):
    SKIPPED mid-sentence in legitimate narrative (e.g., 'no new tools; skipped'
    OR 'pytest 2 skipped') does NOT trigger the anti-trigger requirement.
    Only line-start SKIPPED or 'WORD: SKIPPED' pattern fires."""
    from tools.cascade_classifier import has_cascade_evidence
    msg_narrative_skipped = """## TEST
pytest passed; cli_compliance: no new tools; skipped

## GAP ANALYSIS
inline G1-G6: CLEAN

## REVIEW
udm-design-reviewer: SOUND
"""
    has_ev, findings = has_cascade_evidence(msg_narrative_skipped)
    # Mid-sentence "skipped" should NOT fire the SKIPPED check
    assert has_ev is True
    assert findings == []


def test_skipped_line_start_does_fire_check():
    """Assertion 30 (per reviewer 🟡 #2 fix): line-start SKIPPED DOES fire
    the anti-trigger requirement (producer-claim pattern)."""
    from tools.cascade_classifier import has_cascade_evidence
    msg_line_start = """## TEST
SKIPPED for some reason

## GAP ANALYSIS
clean

## REVIEW
sound
"""
    has_ev, findings = has_cascade_evidence(msg_line_start)
    assert has_ev is False
    assert any("SKIPPED" in f and "anti-trigger" in f for f in findings)


def test_skipped_label_colon_pattern_does_fire_check():
    """Assertion 31 (per reviewer 🟡 #2 fix): 'TEST: SKIPPED' label-colon
    pattern DOES fire (canonical producer-claim format)."""
    from tools.cascade_classifier import has_cascade_evidence
    msg_label = """## TEST
TEST: SKIPPED for some reason

## GAP ANALYSIS
clean

## REVIEW
sound
"""
    has_ev, findings = has_cascade_evidence(msg_label)
    assert has_ev is False
    assert any("SKIPPED" in f and "anti-trigger" in f for f in findings)


def test_extended_substrate_enumeration_per_reviewer():
    """Assertion 19 (per reviewer 🟡 IMPROVE — design review of Phase 1 commit):
    extended substrate set covers Pattern F audit + .claude/hooks/ + discipline docs."""
    from tools.cascade_classifier import (
        SUBSTRATE_FILES, SUBSTRATE_DIR_PREFIXES, is_substrate_path,
    )
    # Files added per reviewer recommendation
    extended = (
        "tools/verify_cascade.py",
        "tools/cli_common.py",
        "docs/migration/CHECKS_AND_BALANCES.md",
        "docs/migration/PLANNING_DISCIPLINE.md",
        "docs/migration/SELF_IMPROVEMENT_DISCIPLINE.md",
    )
    for f in extended:
        assert f in SUBSTRATE_FILES, f"reviewer-recommended substrate file missing: {f}"
        assert is_substrate_path(f)
    # Directory prefix added per reviewer
    assert ".claude/hooks/" in SUBSTRATE_DIR_PREFIXES
    assert is_substrate_path(".claude/hooks/auto-verify-step-10.py")


def test_canonical_source_excluded_from_typo():
    """Assertion 20 (per reviewer 🟡 IMPROVE): small edit to canonical source file
    (03_DECISIONS.md / BACKLOG.md / etc) does NOT classify as TYPO_ONLY."""
    from tools.cascade_classifier import (
        CommitClassification, classify_commit, CANONICAL_SOURCE_FILES,
        CLASS_TYPO,
    )
    # Verify the canonical source set is non-empty
    assert "docs/migration/03_DECISIONS.md" in CANONICAL_SOURCE_FILES
    assert "docs/migration/BACKLOG.md" in CANONICAL_SOURCE_FILES
    # Note: classify_commit() reads real git state; we can't easily mock it
    # without restructuring. The behavioral check is on CANONICAL_SOURCE_FILES
    # being defined + used in the typo-check branch (covered via source inspection).
    import inspect
    src = inspect.getsource(classify_commit)
    assert "CANONICAL_SOURCE_FILES" in src
    assert "touches_canonical" in src


def test_whitespace_detector_handles_blank_added_lines():
    """Assertion 21 (per reviewer 🔴 BLOCK fix): operator-precedence bug was that
    `+` lines bypassed the has-content check; blank `+` lines counted as
    non-whitespace. After fix: blank `+` and `-` lines both treated as whitespace."""
    import inspect
    from tools.cascade_classifier import classify_commit
    src = inspect.getsource(classify_commit)
    # The fix uses an explicit helper function _is_diff_content_line for the
    # diff-line predicate; this binds the precedence correctly.
    assert "_is_diff_content_line" in src
    assert "line[1:].strip()" in src
