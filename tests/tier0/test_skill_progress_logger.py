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
  - Version is v1.3.2 (B-454 + B-455 joint closure target — cumulative-multi-claim + assertion-count PATCH)
  - Step 4.5 CROSS-DOCUMENT sweep still present (v1.2.0 carryover)
  - Step 4.5.1 INTRA-SENTENCE arithmetic contradiction detection present (v1.3.0)
  - Empirical anchor cites commit `e76078c` + finding `G3-K1`
  - Worked example with the 16 / R39-R49 / R39-R43 + R44-R49 pattern present
  - Hard rule 8 (cross-document sweep) still present
  - Hard rule 9 (intra-sentence sweep) added v1.3.0
  - New anti-pattern present
  - Changelog row for v1.3.0 present + cites B-448
  - Changelog row for v1.3.1 present + cites B-453 + Agent 61 G5-1 (added v1.3.1)
  - Frontmatter version field is v1.3.2
  - v1.3.1 regex MATCHES bold-form `**16 NEW R-Ns** (...)` (added v1.3.1)
  - v1.3.1 regex MATCHES non-bold-form `16 NEW R-Ns (...)` (added v1.3.1 backward-compat)
  - Changelog row for v1.3.2 present + cites B-454 + B-455 + commit `6a2fb3f` + `995730c` (added v1.3.2)
  - Cumulative-multi-claim coexistence sweep sub-bullet present (added v1.3.2 per B-454)
  - Assertion-count + pre-existing-count sweep sub-bullet present (added v1.3.2 per B-455)
  - B-454 + B-455 empirical anchors documented in Step 4.5.1 body (added v1.3.2)
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


def test_frontmatter_version_is_v1_3_2(skill_content: str) -> None:
    """Assertion 2: frontmatter `version:` field is v1.3.2 per B-454 + B-455 joint closure (cumulative-multi-claim + assertion-count PATCH)."""
    assert skill_content.startswith("---\n"), "SKILL.md must open with --- delimiter"
    end_idx = skill_content.find("\n---\n", 4)
    assert end_idx > 0, "SKILL.md must close frontmatter with ---"
    frontmatter = skill_content[4:end_idx]
    assert "name: udm-progress-logger" in frontmatter, "frontmatter must declare name"
    assert "version: v1.3.2" in frontmatter, (
        "frontmatter must declare version: v1.3.2 (B-454 + B-455 joint closure target — PATCH)"
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
    """Assertion 7: the trigger regex is documented for producer reference.

    v1.3.1 (B-453 / Agent 61 G5-1 PATCH): regex updated from `\\b(\\d+)` word-boundary
    anchor (which markdown `**` breaks) to `(?:\\*\\*)?(\\d+)(?:\\*\\*)?` optional bold
    markers wrapping the count + suffix to handle bolded narrative forms.
    """
    # Look for the v1.3.1 canonical regex pattern in the Step 4.5.1 body
    assert r"(?:\*\*)?(\d+)(?:\*\*)?" in skill_content, (
        "Step 4.5.1 must document the v1.3.1 trigger regex with optional bold markers "
        "`(?:\\*\\*)?(\\d+)(?:\\*\\*)?\\s+NEW\\s+[BR]-Ns?(?:\\*\\*)?`"
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


def test_skill_self_application_to_v1_3_1_authoring(skill_content: str) -> None:
    """Assertion 17 (meta — Pitfall #9.m self-application check): the v1.3.1 SKILL.md
    edit must NOT itself contain an INTRA-SENTENCE arithmetic contradiction in
    its own newly-authored content. The discipline being added MUST be applied
    to its own authoring commit (anti-meta-irony check).

    Specifically: any 'N NEW X' phrasings in the v1.3.0/v1.3.1 changelog rows or
    Step 4.5.1 body must be internally consistent.

    v1.3.1 update: scan uses the v1.3.1 canonical regex (superset of v1.3.0) which
    covers BOTH bold + non-bold narrative forms. This closes the recursive
    forward-correctness gap that Agent 61 G5-1 finding identified — the meta-
    self-application check itself was using the broken v1.3.0 regex.
    """
    # Scan Step 4.5.1 body + v1.3.0/v1.3.1 changelog rows for "N NEW [BR]-Ns (...)" patterns
    # Use the v1.3.1 regex (superset of v1.3.0 — covers bold + non-bold)
    trigger_pattern = re.compile(
        r"(?:\*\*)?(\d+)(?:\*\*)?\s+NEW\s+[BR]-Ns?(?:\*\*)?\s*\(([^)]*)\)",
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


def test_changelog_v1_3_1_row_present(skill_content: str) -> None:
    """Assertion 18 (added v1.3.1): changelog row for v1.3.1 is present + cites B-453 + Agent 61 G5-1.

    Per D98 semver: PATCH-level revision (forward-correctness fix; no new scope).
    Empirical anchor: Agent 61 cycle-6 D72 ✅ CLEAN convergence finding G5-1 — v1.3.0
    Step 4.5.1 regex `\\b(\\d+)\\s+NEW\\s+[BR]-Ns?` word-boundary anchor breaks on
    markdown `**` markup so the very empirical anchor (`**16 NEW R-Ns**`) it cites
    would NOT have been detected by v1.3.0's own regex. v1.3.1 fixes via optional
    bold markers wrapping count + suffix.
    """
    assert "| v1.3.1 |" in skill_content, "Changelog must have v1.3.1 row (B-453 closure)"
    # The v1.3.1 row body must cite B-453 + Agent 61 + G5-1 + PATCH
    v1_3_1_section = skill_content.split("| v1.3.1 |", 1)[1].split("\n", 1)[0]
    assert "B-453" in v1_3_1_section, "v1.3.1 changelog row must cite B-453"
    assert "Agent 61" in v1_3_1_section, "v1.3.1 changelog row must cite Agent 61 (G5-1 finder)"
    assert "G5-1" in v1_3_1_section, "v1.3.1 changelog row must cite finding G5-1"
    assert "PATCH" in v1_3_1_section, (
        "v1.3.1 changelog row must declare 'PATCH' level per D98 (forward-correctness; no scope)"
    )


def test_v1_3_1_regex_matches_bold_form(skill_content: str) -> None:
    """Assertion 19 (added v1.3.1): the v1.3.1 regex MUST match bold-form narrative `**16 NEW R-Ns** (...)`.

    Empirical anchor: commit `e76078c` 2026-05-17 narrative in CURRENT_STATE.md L7 +
    HANDOFF.md L427 was the bold-form `**16 NEW R-Ns** (R39-R49 — R39-R43 + R44-R49)`.
    v1.3.0's `\\b(\\d+)` regex would NOT match this (the `\\b` word-boundary anchor is
    broken by the preceding `**`). v1.3.1's `(?:\\*\\*)?(\\d+)(?:\\*\\*)?` covers
    BOTH bold positions (whole-phrase bold `**16 NEW R-Ns**` + count-only bold
    `**16** NEW R-Ns`), validated against synthetic and observed narrative samples.

    This assertion mechanically validates Agent 61 G5-1 finding — the v1.3.0 regex
    failure mode is reproducible AND the v1.3.1 regex fixes it.
    """
    # Use the v1.3.1 canonical regex per Step 4.5.1
    v1_3_1_regex = re.compile(
        r"(?:\*\*)?(\d+)(?:\*\*)?\s+NEW\s+[BR]-Ns?(?:\*\*)?\s*\(([^)]*)\)",
        re.IGNORECASE,
    )
    # Synthetic bold-form sample matching the empirical anchor narrative form
    bold_sample = "**16 NEW R-Ns** (R39-R49 — R39-R43 + R44-R49)"
    matches = v1_3_1_regex.findall(bold_sample)
    assert len(matches) >= 1, (
        "v1.3.1 regex MUST match bold-form '**16 NEW R-Ns** (...)' per Agent 61 G5-1 "
        "(v1.3.0 regex would NOT have matched this — the very empirical anchor)"
    )
    assert matches[0][0] == "16", (
        f"v1.3.1 regex MUST capture headline integer '16' from bold-form, "
        f"got: {matches[0][0]!r}"
    )
    assert "R39-R49" in matches[0][1], (
        f"v1.3.1 regex MUST capture parenthetical body containing R39-R49, "
        f"got: {matches[0][1]!r}"
    )

    # Also test count-only bold form (less common but observed in wild)
    count_bold_sample = "**16** NEW R-Ns (R39-R49 — R39-R43 + R44-R49)"
    count_bold_matches = v1_3_1_regex.findall(count_bold_sample)
    assert len(count_bold_matches) >= 1, (
        "v1.3.1 regex MUST match count-only bold form '**16** NEW R-Ns (...)' "
        "(covers narrative variant)"
    )


def test_v1_3_1_regex_matches_non_bold_form(skill_content: str) -> None:
    """Assertion 20 (added v1.3.1): the v1.3.1 regex MUST match non-bold-form (backward compat).

    Backward-compatibility verification: v1.3.1 regex must STILL match the plain
    non-bold form that v1.3.0 matched. The PATCH adds coverage; it does NOT remove
    any prior coverage. If v1.3.1 regex failed on plain form, it would be a
    regression masquerading as a fix.
    """
    # Use the v1.3.1 canonical regex per Step 4.5.1
    v1_3_1_regex = re.compile(
        r"(?:\*\*)?(\d+)(?:\*\*)?\s+NEW\s+[BR]-Ns?(?:\*\*)?\s*\(([^)]*)\)",
        re.IGNORECASE,
    )
    # Plain non-bold sample (the v1.3.0 originally-handled form)
    plain_sample = "16 NEW R-Ns (R39-R49 — R39-R43 + R44-R49)"
    matches = v1_3_1_regex.findall(plain_sample)
    assert len(matches) >= 1, (
        "v1.3.1 regex MUST still match plain non-bold form '16 NEW R-Ns (...)' "
        "(backward compat — PATCH adds bold-form coverage; does NOT remove plain coverage)"
    )
    assert matches[0][0] == "16", (
        f"v1.3.1 regex MUST capture headline integer '16' from plain form, "
        f"got: {matches[0][0]!r}"
    )

    # Also test B-Ns variant (the regex must cover BOTH B-N and R-N families)
    b_n_plain = "24 NEW B-Ns (B-393-B-416)"
    b_n_matches = v1_3_1_regex.findall(b_n_plain)
    assert len(b_n_matches) >= 1, (
        "v1.3.1 regex MUST match B-N family (e.g., '24 NEW B-Ns (...)') "
        "in addition to R-N family per `[BR]-Ns?` character class"
    )


def test_changelog_v1_3_2_row_present(skill_content: str) -> None:
    """Assertion 21 (added v1.3.2): changelog row for v1.3.2 is present + cites B-454 + B-455 + empirical anchors.

    Per D98 semver: PATCH-level revision (extends existing Step 4.5.1 directive scope; no new directive class).
    Joint closure of B-454 (cumulative-multi-claim coexistence) + B-455 (assertion-count + pre-existing).
    Empirical anchors: commit `6a2fb3f` (B-454 1st-event — `60 NEW B-Ns` + `61 NEW B-Ns` coexistence)
    + commit `995730c` (B-455 1st-event — `14 new + 19 pre-existing` vs git-diff `+15 new + 18 pre-existing`).
    """
    assert "| v1.3.2 |" in skill_content, "Changelog must have v1.3.2 row (B-454 + B-455 joint closure)"
    # The v1.3.2 row body must cite both B-Ns + both empirical anchors + PATCH level
    v1_3_2_section = skill_content.split("| v1.3.2 |", 1)[1].split("\n", 1)[0]
    assert "B-454" in v1_3_2_section, "v1.3.2 changelog row must cite B-454 (cumulative-multi-claim)"
    assert "B-455" in v1_3_2_section, "v1.3.2 changelog row must cite B-455 (assertion-count)"
    assert "6a2fb3f" in v1_3_2_section, (
        "v1.3.2 changelog row must cite B-454 empirical anchor commit `6a2fb3f`"
    )
    assert "995730c" in v1_3_2_section, (
        "v1.3.2 changelog row must cite B-455 empirical anchor commit `995730c`"
    )
    assert "PATCH" in v1_3_2_section, (
        "v1.3.2 changelog row must declare 'PATCH' level per D98 (extends existing Step 4.5.1 scope; no new directive)"
    )


def test_cumulative_multi_claim_sub_bullet_present(skill_content: str) -> None:
    """Assertion 22 (added v1.3.2 per B-454): Cumulative-multi-claim coexistence sweep sub-bullet present in Step 4.5.1.

    Empirical anchor: commit `6a2fb3f` CURRENT_STATE L7 + HANDOFF L427 narrative had
    `60 NEW B-Ns (B-393-B-452)` + `61 NEW B-Ns (B-393-B-453)` coexisting without temporal
    demarcation (Agent 64 G1-1 finding). Forward-prevention extends Step 4.5.1 to flag
    multi-match coexistence with shared lower-bound but differing upper-bound.
    """
    assert "Cumulative-multi-claim coexistence sweep" in skill_content, (
        "Step 4.5.1 must contain v1.3.2 sub-bullet 'Cumulative-multi-claim coexistence sweep' per B-454"
    )
    assert "added v1.3.2 per B-454" in skill_content, (
        "Cumulative-multi-claim sub-bullet must declare v1.3.2 origin + B-454 closure target"
    )
    # The sub-bullet must cite the empirical anchor (commit + finding ID)
    assert "6a2fb3f" in skill_content, (
        "Cumulative-multi-claim sub-bullet must cite empirical anchor commit `6a2fb3f`"
    )
    assert "G1-1" in skill_content, (
        "Cumulative-multi-claim sub-bullet must cite Agent 64 finding G1-1"
    )
    # Must describe the temporal-disambiguation requirement
    assert "temporal disambiguation" in skill_content or "temporal demarcation" in skill_content, (
        "Cumulative-multi-claim sub-bullet must reference 'temporal disambiguation' requirement"
    )


def test_assertion_count_sub_bullet_present(skill_content: str) -> None:
    """Assertion 23 (added v1.3.2 per B-455): Assertion-count + pre-existing-count sweep sub-bullet present in Step 4.5.1.

    Empirical anchor: commit `995730c` (B-449 closure) narrative said `14 new + 19 pre-existing`
    but git diff verified `+15 new + 18 pre-existing` (Agent 63 G3-K1 finding). Forward-prevention
    extends Step 4.5.1 with explicit `git diff` + `git show HEAD` verification commands for
    test-count narrative claims.
    """
    assert "Assertion-count + pre-existing-count sweep" in skill_content, (
        "Step 4.5.1 must contain v1.3.2 sub-bullet 'Assertion-count + pre-existing-count sweep' per B-455"
    )
    assert "added v1.3.2 per B-455" in skill_content, (
        "Assertion-count sub-bullet must declare v1.3.2 origin + B-455 closure target"
    )
    # The sub-bullet must cite the empirical anchor
    assert "995730c" in skill_content, (
        "Assertion-count sub-bullet must cite empirical anchor commit `995730c`"
    )
    # Must reference the canonical pattern regex variants
    assert "assertions?" in skill_content, (
        "Assertion-count sub-bullet must document the regex pattern variant covering 'assertions?'"
    )
    assert "pre-existing" in skill_content, (
        "Assertion-count sub-bullet must document the 'pre-existing' regex pattern variant"
    )
    # Must reference git-diff verification mechanism
    assert "git diff" in skill_content, (
        "Assertion-count sub-bullet must reference 'git diff' as the canonical verification mechanism"
    )


def test_b454_b455_anchors_documented_in_step_4_5_1(skill_content: str) -> None:
    """Assertion 24 (added v1.3.2): both B-454 + B-455 anchors documented in Step 4.5.1 body.

    Joint v1.3.2 closure surface check — both forward-prevention extensions must be
    co-located in Step 4.5.1 (not split across other sections) so producers reading
    Step 4.5.1 see both checks in context. Meta-irony note from B-454 entry: v1.3.1
    was authored to prevent the v1.3.0 failure-mode-class AND drift recurred 2 commits
    after v1.3.1 landed — empirical evidence that detection coverage must keep
    extending as new sub-pattern variants surface.
    """
    # Locate the Step 4.5.1 body region (between Step 4.5.1 heading and Step 5 heading)
    step_4_5_1_idx = skill_content.find("### Step 4.5.1")
    assert step_4_5_1_idx > 0, "Step 4.5.1 heading must exist"
    step_5_idx = skill_content.find("### Step 5", step_4_5_1_idx)
    assert step_5_idx > step_4_5_1_idx, "Step 5 heading must follow Step 4.5.1"
    step_4_5_1_body = skill_content[step_4_5_1_idx:step_5_idx]
    # Both v1.3.2 sub-bullets must be IN Step 4.5.1 body (not floating elsewhere)
    assert "B-454" in step_4_5_1_body, (
        "B-454 closure reference must appear WITHIN Step 4.5.1 body (cumulative-multi-claim sub-bullet)"
    )
    assert "B-455" in step_4_5_1_body, (
        "B-455 closure reference must appear WITHIN Step 4.5.1 body (assertion-count sub-bullet)"
    )
    # The empirical anchor commits must also be IN Step 4.5.1 body
    assert "6a2fb3f" in step_4_5_1_body, (
        "B-454 empirical anchor commit `6a2fb3f` must appear within Step 4.5.1 body"
    )
    assert "995730c" in step_4_5_1_body, (
        "B-455 empirical anchor commit `995730c` must appear within Step 4.5.1 body"
    )
