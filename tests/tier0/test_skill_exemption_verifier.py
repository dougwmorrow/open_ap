"""Tier 0 smoke tests for `.claude/skills/udm-exemption-verifier/SKILL.md` per D67.

Verifies the skill SKILL.md is parseable + has expected structure (frontmatter,
trigger phrases, procedure steps, examples covering 3 prior Pitfall #9.o instances,
hard-rule list).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILL_PATH = REPO_ROOT / ".claude" / "skills" / "udm-exemption-verifier" / "SKILL.md"


@pytest.fixture
def skill_content() -> str:
    """Load SKILL.md content."""
    assert SKILL_PATH.is_file(), f"SKILL.md not found at {SKILL_PATH}"
    return SKILL_PATH.read_text(encoding="utf-8")


def test_skill_file_exists():
    """Assertion 1: SKILL.md file exists at canonical path."""
    assert SKILL_PATH.is_file()


def test_frontmatter_parseable(skill_content: str):
    """Assertion 2: YAML frontmatter present + parseable."""
    assert skill_content.startswith("---\n"), "SKILL.md must start with --- frontmatter delimiter"
    end_marker_idx = skill_content.find("\n---\n", 4)
    assert end_marker_idx > 0, "SKILL.md must close frontmatter with ---"
    frontmatter = skill_content[4:end_marker_idx]
    assert "name: udm-exemption-verifier" in frontmatter, "frontmatter must declare name"
    assert "description:" in frontmatter, "frontmatter must include description"


def test_description_cites_b296_and_instance_7(skill_content: str):
    """Assertion 3: description cites B-296 + Pitfall #9.o instance 7 empirical anchor."""
    assert "B-296" in skill_content
    assert "instance 7" in skill_content
    assert "01d32c0" in skill_content


def test_trigger_phrases_enumerated(skill_content: str):
    """Assertion 4: skill enumerates all 12 mandatory trigger phrases (8 original + 4 B-303 structured extensions)."""
    trigger_phrases = [
        # Original 8 from SKILL.md L29-36
        "Layer N+1 termination",
        "recursive-exemption",
        "verbatim implementation",
        "100% overlap on architectural-decision-substance",
        "specific scope-justified exemption",
        "REVIEW: SKIPPED",
        "no new architecture introduced",
        "implementing prior reviewer's recommendation",
        # B-303 structured-pattern extensions per Q5 instance-9 finding
        "EXEMPTION VALID",
        "step 6: N/A",
        "cannot fire on commits modifying its own SKILL.md",
        "self-exemption clause applies",
    ]
    for phrase in trigger_phrases:
        assert phrase in skill_content, f"trigger phrase missing: {phrase}"
    assert len(trigger_phrases) == 12, "expected exactly 12 trigger phrases per SKILL.md + B-303 extension"


def test_5_step_procedure_present(skill_content: str):
    """Assertion 5: skill has 5-step procedure (Steps 1-5)."""
    step_pattern = re.compile(r"^### Step [1-5]\b", re.MULTILINE)
    matches = step_pattern.findall(skill_content)
    assert len(matches) >= 5, f"expected ≥5 procedure steps; found {len(matches)}"


def test_3_prior_pitfall_9o_instances_referenced(skill_content: str):
    """Assertion 6: examples section references 3 prior Pitfall #9.o instances."""
    assert "Instance 5" in skill_content or "instance 5" in skill_content
    assert "Instance 6" in skill_content or "instance 6" in skill_content
    assert "Instance 7" in skill_content or "instance 7" in skill_content
    assert "4112e92" in skill_content
    assert "570ac67" in skill_content
    assert "01d32c0" in skill_content


def test_self_exemption_clause_present(skill_content: str):
    """Assertion 7: skill self-exemption clause (no recursion on the verifier itself)."""
    assert "exempt from its own recursion" in skill_content
    assert "Single-purpose" in skill_content or "single-purpose" in skill_content


def test_binary_verdict_output_contract(skill_content: str):
    """Assertion 8: skill output is binary VALID/INVALID."""
    assert "VALID" in skill_content
    assert "INVALID-with-specific-files" in skill_content or "INVALID" in skill_content
    assert "Default-INVALID" in skill_content


def test_5_min_budget_cap(skill_content: str):
    """Assertion 9: skill has 5-min budget cap discipline."""
    assert "5-min budget" in skill_content or "5-minute" in skill_content or "5 min" in skill_content


def test_hard_rules_list_non_empty(skill_content: str):
    """Assertion 10: skill enumerates hard rules (≥4 distinct rules)."""
    hard_rules_section = skill_content.split("## Hard rules")
    assert len(hard_rules_section) == 2, "Hard rules section must exist exactly once"
    rules_body = hard_rules_section[1].split("##")[0]
    rule_pattern = re.compile(r"^\d+\.\s+\*\*", re.MULTILINE)
    rules = rule_pattern.findall(rules_body)
    assert len(rules) >= 4, f"expected ≥4 hard rules; found {len(rules)}"


def test_composition_with_other_skills_documented(skill_content: str):
    """Assertion 11: skill documents composition with udm-post-edit-verification + udm-gap-check."""
    assert "udm-post-edit-verification" in skill_content
    assert "udm-gap-check" in skill_content
    assert "Step 2.5" in skill_content


def test_anti_triggers_enumerated(skill_content: str):
    """Assertion 12 (per B-302 coverage gap closure): skill enumerates anti-triggers
    (cases where skill does NOT fire). Must include trivial commits + full reviewer
    evidence + commit-message-doesnt-claim-exemption."""
    assert "Anti-triggers" in skill_content or "anti-triggers" in skill_content
    assert "typo" in skill_content.lower() or "trivial" in skill_content.lower()
    assert ("full independent reviewer evidence" in skill_content
            or "NOT firing" in skill_content
            or "does NOT fire" in skill_content)


def test_cost_discipline_ceiling_documented(skill_content: str):
    """Assertion 13 (per B-302 coverage gap closure): skill documents cost-discipline
    ceiling for cumulative session usage (~25 min per skill cost-discipline section)."""
    assert "Cost discipline" in skill_content or "cost discipline" in skill_content
    assert "25 min" in skill_content or "ceiling" in skill_content
    assert "single-shot" in skill_content.lower() or "per commit" in skill_content.lower()


def test_cross_references_resolve(skill_content: str):
    """Assertion 14 (per B-302 coverage gap closure): cited cross-references in
    SKILL.md (paths to other skills + canonical sources) exist on disk."""
    cited_paths = [
        ".claude/skills/udm-post-edit-verification/SKILL.md",
        ".claude/skills/udm-gap-check/SKILL.md",
        "docs/migration/HANDOFF.md",
    ]
    for path_str in cited_paths:
        if path_str in skill_content:
            full_path = REPO_ROOT / path_str
            assert full_path.is_file(), (
                f"SKILL.md cites {path_str} but file doesn't exist on disk"
            )


def test_carve_out_distinguishes_output_from_authoring(skill_content: str):
    """Assertion 15 (per B-302 coverage gap closure): CRITICAL CARVE-OUT (added at
    instance-8 closure) must SEMANTICALLY distinguish 'verifier OUTPUT exemption'
    from 'SKILL.md AUTHORING commit exemption'. Catches the failure mode where
    parent misreads the clause as exempting authoring commits from cascade."""
    assert "CRITICAL CARVE-OUT" in skill_content
    assert ("ONLY to verifier OUTPUT" in skill_content
            or "ONLY to the verifier OUTPUT" in skill_content
            or "only to verifier OUTPUT" in skill_content), (
        "CARVE-OUT must explicitly state exemption applies ONLY to verifier OUTPUT"
    )
    assert ("NOT exempt" in skill_content or "does NOT exempt" in skill_content), (
        "CARVE-OUT must explicitly state SKILL.md authoring commit is NOT exempt"
    )
    assert "SKILL.md AUTHORING commit" in skill_content or "SKILL.md authoring commit" in skill_content
    assert ("FULL independent gap-check" in skill_content
            or "FULL hard-rule-14 cascade" in skill_content
            or "FULL hard rule 14 cascade" in skill_content), (
        "CARVE-OUT must specify the requirement is FULL cascade (not partial)"
    )
