"""Tier 0 build-time smoke test for `.claude/skills/udm-context-loader/SKILL.md`.

Per D67 — runs at build time + every commit; runtime ceiling < 5 s; no DB / network.
Verifies the SKILL.md file structure as authored per MARKDOWN_REFACTOR_PLAN.md §4.5
+ §15.2 F5.1 mitigation + B-275 closure 2026-05-17.

Asserts:
  - File exists at the canonical path
  - YAML frontmatter parses + carries `name`, `description`, `version`
  - The 9 required SKILL.md sections are present
  - Trigger-phrase enumeration present (≥5 mandatory triggers; ≥3 anti-triggers)
  - Sub-agent inheritance contract section present (per CLAUDE.md hard rule 13)
  - Output-contract schema example present (markdown code fence with brief schema)
  - F5.1 verbatim-excerpts categories cited per §15.2 Pattern d
  - Empirical anchor + B-275 reference present
"""
from __future__ import annotations

from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_SKILL_PATH = _PROJECT_ROOT / ".claude" / "skills" / "udm-context-loader" / "SKILL.md"


@pytest.fixture(scope="module")
def skill_text() -> str:
    """Read SKILL.md once per module run."""
    assert _SKILL_PATH.exists(), f"SKILL.md not found at {_SKILL_PATH}"
    return _SKILL_PATH.read_text(encoding="utf-8")


def test_skill_file_exists() -> None:
    """SKILL.md exists at the canonical .claude/skills/udm-context-loader/ path."""
    assert _SKILL_PATH.exists(), f"Expected SKILL.md at {_SKILL_PATH}"
    assert _SKILL_PATH.is_file(), f"{_SKILL_PATH} exists but is not a file"


def test_frontmatter_parses(skill_text: str) -> None:
    """Frontmatter opens + closes with `---` lines + carries name / description / version."""
    lines = skill_text.splitlines()
    assert lines[0].strip() == "---", "SKILL.md must open with --- frontmatter delimiter"
    # Find closing ---
    closing_idx = None
    for i in range(1, min(20, len(lines))):
        if lines[i].strip() == "---":
            closing_idx = i
            break
    assert closing_idx is not None, "SKILL.md frontmatter must close with --- within first 20 lines"
    frontmatter_block = "\n".join(lines[1:closing_idx])
    assert "name: udm-context-loader" in frontmatter_block, "Frontmatter missing `name: udm-context-loader`"
    assert "description:" in frontmatter_block, "Frontmatter missing `description:` key"
    assert "version: 1.0.0" in frontmatter_block, "Frontmatter missing `version: 1.0.0`"


def test_required_sections_present(skill_text: str) -> None:
    """The 9 required SKILL.md sections are present as ## (level-2) headings."""
    required_sections = [
        "## When to invoke",
        "## Why this skill exists",
        "## Canonical Context Load",
        "## Procedure",
        "## Output contract",
        "## Composition",
        "## Sub-agent inheritance contract",
        "## Tier 0 stub reference",
        "## Cross-references",
    ]
    missing = [s for s in required_sections if s not in skill_text]
    assert not missing, f"SKILL.md missing required sections: {missing}"


def test_trigger_phrase_enumeration_present(skill_text: str) -> None:
    """At least 5 mandatory trigger phrases + at least 3 anti-triggers present."""
    # Mandatory trigger phrases — count under "Mandatory trigger phrases" subsection
    mandatory_markers = [
        "Spawn N parallel sub-agents",
        "multi-agent team",
        "independent reviewer",
        "Pattern E review cohort",
        "Wave N build cohort",
    ]
    found_mandatory = [m for m in mandatory_markers if m in skill_text]
    assert len(found_mandatory) >= 5, (
        f"Expected ≥5 mandatory trigger-phrase markers; found {len(found_mandatory)}: {found_mandatory}"
    )

    # Anti-triggers — count under "Anti-triggers" subsection
    anti_trigger_markers = [
        "Single-agent fix-only",
        "Read-only exploration",
        "trivial cosmetic edits",
    ]
    found_anti = [m for m in anti_trigger_markers if m.lower() in skill_text.lower()]
    assert len(found_anti) >= 3, (
        f"Expected ≥3 anti-trigger markers; found {len(found_anti)}: {found_anti}"
    )


def test_sub_agent_inheritance_contract_present(skill_text: str) -> None:
    """Sub-agent inheritance contract section cites CLAUDE.md hard rule 13."""
    assert "## Sub-agent inheritance contract" in skill_text, (
        "SKILL.md must have ## Sub-agent inheritance contract section"
    )
    assert "hard rule 13" in skill_text, (
        "Sub-agent inheritance section must cite CLAUDE.md hard rule 13"
    )


def test_output_contract_schema_example_present(skill_text: str) -> None:
    """Output-contract section contains a markdown code fence with brief schema example.

    Note: we don't slice the section out (the schema's `## Sub-agent context brief — ...`
    line inside the ```markdown code fence would prematurely end a naive `\\n## ` split).
    Instead we verify the section opens at "## Output contract", a code fence follows
    within ~20 lines, and the canonical brief-schema markers are anywhere in the file.
    """
    output_idx = skill_text.find("## Output contract")
    assert output_idx >= 0, "## Output contract section missing"
    # The opening ```markdown code fence must follow within ~20 lines of the header
    post_header = skill_text[output_idx : output_idx + 2000]
    assert "```markdown" in post_header, (
        "Output contract section must open a ```markdown code fence within ~20 lines"
    )
    # Brief schema must enumerate the canonical required sections (anywhere in SKILL.md
    # is acceptable; in practice they live inside the code fence under Output contract)
    assert "### Scope header" in skill_text, "Brief schema must include ### Scope header section"
    assert "Stage 1+2 canonical-source excerpts" in skill_text, (
        "Brief schema must include `Stage 1+2 canonical-source excerpts` section"
    )
    assert "Use these skills" in skill_text, "Brief schema must include `Use these skills` section"


def test_f5_1_verbatim_excerpts_categories_cited(skill_text: str) -> None:
    """F5.1 verbatim-excerpt categories per MARKDOWN_REFACTOR_PLAN.md §15.2 Pattern d enumerated."""
    # The 4 non-distillable categories
    categories = [
        "Do-NOT rule",
        "Pitfall #9",
        "D-N",
        "R-N",
    ]
    missing = [c for c in categories if c not in skill_text]
    assert not missing, (
        f"SKILL.md must cite F5.1 verbatim-excerpt categories; missing: {missing}"
    )
    # F5.1 itself must be cited
    assert "F5.1" in skill_text, "SKILL.md must cite F5.1 mitigation"


def test_empirical_anchor_and_b275_reference_present(skill_text: str) -> None:
    """SKILL.md cites MARKDOWN_REFACTOR_PLAN.md §4.5 + B-275 + empirical baseline."""
    assert "MARKDOWN_REFACTOR_PLAN.md" in skill_text, (
        "SKILL.md must cite MARKDOWN_REFACTOR_PLAN.md"
    )
    assert "§4.5" in skill_text, "SKILL.md must cite §4.5 Option T5 design rationale"
    assert "B-275" in skill_text, "SKILL.md must cite B-275 closure target"
    # CCL baseline empirical anchor
    assert "362" in skill_text or "362K" in skill_text or "362,154" in skill_text, (
        "SKILL.md must cite CCL Stage 1+2 token baseline (362K tokens) per §15.4"
    )


def test_procedure_has_at_least_5_steps(skill_text: str) -> None:
    """Procedure section enumerates at least 5 steps per the SKILL.md schema."""
    proc_idx = skill_text.find("## Procedure")
    assert proc_idx >= 0, "## Procedure section missing"
    section_text = skill_text[proc_idx:]
    next_section = section_text.find("\n## ", 1)
    if next_section > 0:
        section_text = section_text[:next_section]
    # Count "### Step N —" patterns
    step_count = sum(
        1
        for line in section_text.splitlines()
        if line.startswith("### Step ") and " — " in line
    )
    assert step_count >= 5, (
        f"Procedure section must enumerate ≥5 steps (found {step_count}); SKILL.md target 5-7 steps"
    )


def test_cross_references_section_cites_canonical_decisions(skill_text: str) -> None:
    """Cross-references section cites D62 + D55 + D56 + CLAUDE.md hard rules."""
    cross_idx = skill_text.find("## Cross-references")
    assert cross_idx >= 0, "## Cross-references section missing"
    section_text = skill_text[cross_idx:]
    next_section = section_text.find("\n## ", 1)
    if next_section > 0:
        section_text = section_text[:next_section]
    required_refs = ["D62", "D55", "D56", "CLAUDE.md", "PLANNING_DISCIPLINE.md", "HANDOFF.md"]
    missing = [r for r in required_refs if r not in section_text]
    assert not missing, (
        f"Cross-references section must cite canonical refs; missing: {missing}"
    )
