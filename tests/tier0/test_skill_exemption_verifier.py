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
    """Assertion 4: skill enumerates ≥6 mandatory trigger phrases."""
    trigger_phrases = [
        "Layer N+1 termination",
        "recursive-exemption",
        "verbatim implementation",
        "100% overlap on architectural-decision-substance",
        "specific scope-justified exemption",
        "REVIEW: SKIPPED",
    ]
    for phrase in trigger_phrases:
        assert phrase in skill_content, f"trigger phrase missing: {phrase}"


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
