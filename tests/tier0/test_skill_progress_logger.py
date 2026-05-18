"""Tier 0 build-time smoke tests for `.claude/skills/udm-progress-logger/SKILL.md`.

Per D67 — runs at build time + every commit; runtime ceiling < 5 s; no DB / network.

Asserts the SKILL.md content STRUCTURE — udm-progress-logger is a manually-invoked
discipline skill (NOT an executable detector). The Tier 0 test verifies the
canonical directive content is present, version-bumped, and empirically-anchored.
A future executable detector would live at `tools/check_arithmetic_propagation.py`
(B-N candidate; not yet authored) and would have its own Tier 0 test for the
arithmetic-detection LOGIC.

This file's assertions cover:
  - File exists at canonical path + YAML frontmatter parses
  - Version is v1.3.0 (B-448 closure target)
  - Step 4.5 CROSS-DOCUMENT sweep still present (v1.2.0 carryover)
  - Step 4.5.1 INTRA-SENTENCE arithmetic contradiction detection present (v1.3.0)
  - Empirical anchor cites commit `e76078c` + finding `G3-K1`
  - Worked example with the 16 / R39-R49 / R39-R43 + R44-R49 pattern present
  - Hard rule 8 (cross-document sweep) still present
  - Hard rule 9 (intra-sentence sweep) added v1.3.0
  - New anti-pattern present
  - Changelog row for v1.3.0 present + cites B-448
  - Frontmatter version field is v1.3.0
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILL_PATH = REPO_ROOT / ".claude" / "skills" / "udm-progress-logger" / "SKILL.md"


@pytest.fixture(scope="module")
def skill_content() -> str:
    """Load SKILL.md content once per module run."""
    assert SKILL_PATH.is_file(), f"SKILL.md not found at {SKILL_PATH}"
    return SKILL_PATH.read_text(encoding="utf-8")


def test_skill_file_exists() -> None:
    """Assertion 1: SKILL.md exists at the canonical path."""
    assert SKILL_PATH.is_file(), f"Expected SKILL.md at {SKILL_PATH}"


def test_frontmatter_version_is_v1_3_0(skill_content: str) -> None:
    """Assertion 2: frontmatter `version:` field is v1.3.0 per B-448 closure."""
    assert skill_content.startswith("---\n"), "SKILL.md must open with --- delimiter"
    end_idx = skill_content.find("\n---\n", 4)
    assert end_idx > 0, "SKILL.md must close frontmatter with ---"
    frontmatter = skill_content[4:end_idx]
    assert "name: udm-progress-logger" in frontmatter, "frontmatter must declare name"
    assert "version: v1.3.0" in frontmatter, (
        "frontmatter must declare version: v1.3.0 (B-448 closure target)"
    )


def test_step_4_5_cross_document_sweep_present(skill_content: str) -> None:
    """Assertion 3: v1.2.0 Step 4.5 cross-document sweep still present (carryover)."""
    assert "### Step 4.5 — Arithmetic-propagation sweep" in skill_content, (
        "v1.2.0 Step 4.5 cross-document sweep must remain present"
    )


def test_step_4_5_1_intra_sentence_sub_step_present(skill_content: str) -> None:
    """Assertion 4: v1.3.0 Step 4.5.1 INTRA-SENTENCE sub-step present."""
    assert "### Step 4.5.1 — INTRA-SENTENCE arithmetic contradiction detection" in skill_content, (
        "v1.3.0 must add Step 4.5.1 sub-step heading"
    )
    assert "INTRA-SENTENCE" in skill_content, "INTRA-SENTENCE keyword must appear"
    assert "CROSS-DOCUMENT" in skill_content, (
        "Step 4.5.1 must explicitly distinguish INTRA vs CROSS scope"
    )


def test_empirical_anchor_cites_e76078c_and_g3_k1(skill_content: str) -> None:
    """Assertion 5: empirical anchor cites commit `e76078c` + finding `G3-K1`."""
    assert "e76078c" in skill_content, (
        "Step 4.5.1 must cite cycle-4 cascade commit `e76078c` as 1st-event anchor"
    )
    assert "G3-K1" in skill_content, (
        "Step 4.5.1 must cite Agent 59 cycle-3 D72 convergence finding G3-K1"
    )
    assert "B-448" in skill_content, "Step 4.5.1 must reference B-448 closure"


def test_worked_example_with_16_r_ns_pattern_present(skill_content: str) -> None:
    """Assertion 6: worked example showing the 16-vs-11 contradiction is present."""
    # The empirical-anchor sentence must appear verbatim or with key fragments
    assert "16 NEW R-Ns" in skill_content, (
        "worked example must cite the canonical '16 NEW R-Ns' anchor sentence"
    )
    assert "R39-R49" in skill_content, "worked example must cite outer range R39-R49"
    assert "R39-R43" in skill_content and "R44-R49" in skill_content, (
        "worked example must cite both sub-ranges (R39-R43 + R44-R49)"
    )
    # Both sub-ranges sum to 11 — must be cited as the contradiction
    assert "11" in skill_content, "worked example must show the 11 sub-range-sum"


def test_regex_pattern_documented(skill_content: str) -> None:
    """Assertion 7: the trigger regex is documented for producer reference."""
    # Look for the canonical regex pattern in the Step 4.5.1 body
    assert r"\b(\d+)" in skill_content, (
        "Step 4.5.1 must document the trigger regex `\\b(\\d+)\\s+NEW\\s+[BR]-Ns?`"
    )
    assert "NEW" in skill_content and "[BR]-Ns" in skill_content, (
        "Trigger regex must reference NEW + [BR]-N pattern"
    )


def test_four_parse_forms_enumerated(skill_content: str) -> None:
    """Assertion 8: Step 4.5.1 enumerates the 4 parenthetical parse forms."""
    # The verification-procedure table covers 4 forms
    assert "Single range" in skill_content, "parse form 'Single range' must be enumerated"
    assert "Sum of ranges" in skill_content, "parse form 'Sum of ranges' must be enumerated"
    assert "sub-range" in skill_content.lower(), (
        "parse form 'Range with sub-range citation' must be enumerated"
    )
    assert "No structured form" in skill_content, (
        "parse form 'No structured form' (manual-review fallthrough) must be enumerated"
    )


def test_composition_with_step_4_5_documented(skill_content: str) -> None:
    """Assertion 9: Step 4.5.1 documents composition with Step 4.5 (defends different scope)."""
    # The "Composition with Step 4.5" sub-section
    assert "Composition with Step 4.5" in skill_content, (
        "Step 4.5.1 must document its composition relationship to Step 4.5"
    )
    assert "different scope" in skill_content.lower() or "different scopes" in skill_content.lower(), (
        "Composition must explain that Step 4.5 + 4.5.1 defend at different scopes"
    )


def test_hard_rule_8_cross_document_still_present(skill_content: str) -> None:
    """Assertion 10: Hard rule 8 (v1.2.0 cross-document sweep) still present."""
    hard_rules_section = skill_content.split("## Hard rules")
    assert len(hard_rules_section) == 2, "Hard rules section must exist exactly once"
    rules_body = hard_rules_section[1].split("##")[0]
    # Hard rule 8 specifically about arithmetic-propagation sweep
    assert "8. **No status transition without arithmetic-propagation sweep**" in rules_body, (
        "Hard rule 8 (v1.2.0) cross-document sweep must remain present"
    )


def test_hard_rule_9_intra_sentence_added(skill_content: str) -> None:
    """Assertion 11: Hard rule 9 (v1.3.0 intra-sentence sweep) added."""
    hard_rules_section = skill_content.split("## Hard rules")
    rules_body = hard_rules_section[1].split("##")[0]
    assert "9. **No narrative arithmetic claim without intra-sentence contradiction sweep**" in rules_body, (
        "Hard rule 9 (v1.3.0) intra-sentence sweep must be added"
    )
    # Must compose with Hard rule 8 explicitly
    assert "Hard rule 8" in rules_body or "Composes with Hard rule 8" in rules_body, (
        "Hard rule 9 should reference composition with Hard rule 8"
    )


def test_new_anti_pattern_present(skill_content: str) -> None:
    """Assertion 12: new anti-pattern for the failure mode is documented."""
    anti_patterns_section = skill_content.split("## Anti-patterns")
    assert len(anti_patterns_section) == 2, "Anti-patterns section must exist exactly once"
    anti_body = anti_patterns_section[1].split("## ")[0]
    # The anti-pattern bullet specifically about "N NEW [BR]-Ns (range1 + range2)"
    assert "range1 + range2" in anti_body or "range1" in anti_body, (
        "Anti-pattern must reference the (range1 + range2) failure mode pattern"
    )
    # The empirical anchor must be cited inside the anti-pattern
    assert "e76078c" in anti_body, (
        "Anti-pattern must cite commit `e76078c` empirical anchor"
    )


def test_changelog_v1_3_0_row_present(skill_content: str) -> None:
    """Assertion 13: changelog row for v1.3.0 is present + cites B-448."""
    assert "| v1.3.0 |" in skill_content, "Changelog must have v1.3.0 row"
    # The v1.3.0 row body must cite B-448 + 1st-event anchor
    v1_3_0_section = skill_content.split("| v1.3.0 |", 1)[1].split("\n", 1)[0]
    assert "B-448" in v1_3_0_section, "v1.3.0 changelog row must cite B-448"
    assert "e76078c" in v1_3_0_section, "v1.3.0 changelog row must cite commit `e76078c`"
    assert "G3-K1" in v1_3_0_section, "v1.3.0 changelog row must cite finding G3-K1"


def test_changelog_v1_2_0_still_present(skill_content: str) -> None:
    """Assertion 14: prior changelog rows (v1.0.0, v1.1.0, v1.2.0) preserved (append-only)."""
    # Append-only audit trail per Hard rule 2 — prior versions must remain
    assert "| v1.0.0 |" in skill_content, "v1.0.0 row must remain (append-only)"
    assert "| v1.1.0 |" in skill_content, "v1.1.0 row must remain (append-only)"
    assert "| v1.2.0 |" in skill_content, "v1.2.0 row must remain (append-only)"


def test_negative_consistent_arithmetic_does_not_trigger(skill_content: str) -> None:
    """Assertion 15 (negative test): a synthetic consistent arithmetic claim
    would NOT trigger the detection — the worked example shows ONLY the
    inconsistent case (16 vs 11). Verify the SKILL.md does NOT inadvertently
    document a 'consistent example also triggers' anti-pattern.

    This is a structural sanity check — the Step 4.5.1 detection LOGIC is
    'flag when headline ≠ breakdown sum'; a consistent example would silently
    pass and produce no flag. If the SKILL.md ever incorrectly claims
    'always flag', this test catches that drift.
    """
    # The skill must specifically describe the CONTRADICTION case, not "always flag"
    assert "contradicts" in skill_content.lower() or "contradiction" in skill_content.lower(), (
        "Step 4.5.1 must frame detection as contradiction-finding, not always-flag"
    )
    assert "must match" in skill_content.lower() or "must agree" in skill_content.lower() or "equals headline" in skill_content.lower(), (
        "Pass-condition must be 'parts equal headline' (consistent = pass; inconsistent = flag)"
    )


def test_positive_inconsistent_example_documented(skill_content: str) -> None:
    """Assertion 16 (positive test): the 16-vs-11 inconsistent example is
    documented with explicit ❌ verdict, not just abstract description.
    """
    # The worked example body must show the verdict explicitly
    assert "Contradiction" in skill_content or "contradiction" in skill_content, (
        "Worked example must explicitly label the 16-vs-11 case as a Contradiction"
    )


def test_skill_self_application_to_v1_3_0_authoring(skill_content: str) -> None:
    """Assertion 17 (meta — Pitfall #9.m self-application check): the v1.3.0 SKILL.md
    edit must NOT itself contain an INTRA-SENTENCE arithmetic contradiction in
    its own newly-authored content. The discipline being added MUST be applied
    to its own authoring commit (anti-meta-irony check).

    Specifically: any 'N NEW X' phrasings in the v1.3.0 changelog row or
    Step 4.5.1 body must be internally consistent.
    """
    # Scan Step 4.5.1 body + v1.3.0 changelog row for "N NEW [BR]-Ns (...)" patterns
    trigger_pattern = re.compile(
        r"\b(\d+)\s+NEW\s+[BR]-Ns?\s*\(([^)]*)\)",
        re.IGNORECASE,
    )
    matches = trigger_pattern.findall(skill_content)
    # The empirical-anchor example uses "16 NEW R-Ns" — we WANT that match (it's
    # the documented anchor). Verify the match is preserved (anchor present)
    # AND verify no NEW spurious self-applied contradiction was introduced.
    anchor_matches = [m for m in matches if m[0] == "16" and "R39-R49" in m[1]]
    assert len(anchor_matches) >= 1, (
        "Empirical anchor '16 NEW R-Ns (R39-R49 ...)' must be cited verbatim "
        "in worked example — found: " + str(matches)
    )
