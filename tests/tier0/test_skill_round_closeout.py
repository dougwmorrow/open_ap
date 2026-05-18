"""Tier 0 build-time smoke tests for `.claude/skills/udm-round-closeout/SKILL.md`.

Per D67 — runs at build time + every commit; runtime ceiling < 5 s; no DB / network.

Pins the canonical content of the udm-round-closeout SKILL.md against silent
regression. Specifically locks the 4-skill B-408 cohort canonicalization:
  - Series list = M/S/I/N/P/G/D/F/V/DP/T/SI/SE/PL (14 canonical series)
  - Pitfall #9 scan range = 9.a-9.o (15 sub-classes)
  - HANDOFF §14 update bullet (B-415 closure)
  - Stage 2.5 POLISH_QUEUE skim (D113)
  - Section 9 Pattern F audit + Section 10 self-improvement loop

B-457 closure: same prevent-silent-regression pattern as `test_skill_progress_logger.py`
that pins v1.2.0/v1.3.0/v1.3.1 directives.

This file's assertions cover:
  - File exists at canonical path + YAML frontmatter parses
  - Frontmatter declares name: udm-round-closeout
  - Section 3 series list contains the canonical 14-series enumeration
  - Section 10.3 Pitfall #9 scan range contains canonical 9.a-9.o
  - Section 6 HANDOFF §14 update bullet present (B-415)
  - Stage 2.5 POLISH_QUEUE skim present (D113)
  - Section 9 Pattern F audit + Section 10 self-improvement loop present
  - B-408 closure citation present (anchors the canonicalization to its B-N)
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILL_PATH = REPO_ROOT / ".claude" / "skills" / "udm-round-closeout" / "SKILL.md"


@pytest.fixture(scope="module")
def skill_content() -> str:
    """Load SKILL.md content once per module run."""
    assert SKILL_PATH.is_file(), f"SKILL.md not found at {SKILL_PATH}"
    return SKILL_PATH.read_text(encoding="utf-8")


def test_skill_file_exists() -> None:
    """Assertion 1: SKILL.md exists at the canonical path."""
    assert SKILL_PATH.is_file(), f"Expected SKILL.md at {SKILL_PATH}"


def test_frontmatter_name(skill_content: str) -> None:
    """Assertion 2: frontmatter declares `name: udm-round-closeout`."""
    assert skill_content.startswith("---\n"), "SKILL.md must open with --- delimiter"
    end_idx = skill_content.find("\n---\n", 4)
    assert end_idx > 0, "SKILL.md must close frontmatter with ---"
    frontmatter = skill_content[4:end_idx]
    assert "name: udm-round-closeout" in frontmatter, (
        "frontmatter must declare name: udm-round-closeout"
    )


def test_section_3_series_list_canonical_14_series(skill_content: str) -> None:
    """Assertion 3 (B-408 canonicalization): Section 3 series list contains all 14 canonical series.

    Per B-408 atomic 4-skill fix 2026-05-17 — was stale at 9 since Round 6 DP series addition.
    Canonical enumeration: M/S/I/N/P/G/D/F/V/DP/T/SI/SE/PL.
    """
    # Section 3 header
    assert "### Section 3 — Edge case register updates" in skill_content, (
        "Section 3 header must be present"
    )
    # The canonical series list must appear verbatim (parenthetical enumeration form)
    canonical_series_list = "(M/S/I/N/P/G/D/F/V/DP/T/SI/SE/PL)"
    assert canonical_series_list in skill_content, (
        f"Section 3 must cite canonical series list {canonical_series_list} "
        "(B-408 atomic 4-skill series-list fix 2026-05-17)"
    )
    # The "14 canonical series total" assertion must be present
    assert "14 canonical series" in skill_content, (
        "Section 3 must explicitly state '14 canonical series total' "
        "(per B-408; was stale at 9 since Round 6)"
    )


def test_section_3_b_408_closure_citation_present(skill_content: str) -> None:
    """Assertion 4: B-408 closure citation present in Section 3 (anchors the canonicalization).

    Empirical anchor — without the B-N citation, the canonicalization is detached from
    its closure mechanism and silent removal is undetectable. The B-408 reference is the
    audit trail back to the closure commit `895ae59`.
    """
    assert "B-408" in skill_content, (
        "Section 3 must cite B-408 (atomic 4-skill series-list fix anchor)"
    )


def test_section_10_3_pitfall_9_scan_range_9_a_to_9_o(skill_content: str) -> None:
    """Assertion 5 (B-408 canonicalization): Section 10.3 Pitfall #9 scan range covers 9.a-9.o.

    Per B-408 atomic fix — udm-subclass-accumulator scans this round's findings against
    the full 9.a-9.o range (15 sub-classes total), not the stale 9.a-9.j range that
    missed 9.k/9.l/9.m/9.n/9.o.
    """
    # Section 10.3 header
    assert "Sub-section 10.3 — udm-subclass-accumulator" in skill_content, (
        "Section 10.3 header must be present"
    )
    # The canonical scan-range citation
    assert "9.a-9.o" in skill_content, (
        "Section 10.3 must cite canonical Pitfall #9 scan range 9.a-9.o "
        "(15 sub-classes total per B-408 atomic 4-skill fix)"
    )
    # The "15 sub-classes total" assertion
    assert "15 sub-classes" in skill_content, (
        "Section 10.3 must explicitly state '15 sub-classes total' "
        "(per B-408; was stale at 9.a-9.j missing 9.k/9.l/9.m/9.n/9.o)"
    )


def test_section_6_handoff_section_14_update_bullet(skill_content: str) -> None:
    """Assertion 6: Section 6 HANDOFF §14 update bullet present (B-415 closure).

    Per B-415 + Cohort A Agent 54 RC-7 finding (forward-motion cascade enforced HANDOFF §14
    update but round-closeout omitted; asymmetry was a discipline gap).
    """
    # The §14 update directive must be present in the HANDOFF.md sub-section
    assert "§14" in skill_content, "Section 6 must reference §14 narrative update"
    assert "B-415" in skill_content, (
        "Section 6 §14 update must cite B-415 closure (Cohort A Agent 54 RC-7 anchor)"
    )
    # The forward-motion-cascade composition phrasing
    assert "forward-motion" in skill_content.lower(), (
        "Section 6 §14 update bullet must reference forward-motion cascade discipline"
    )


def test_stage_2_5_polish_queue_skim_present(skill_content: str) -> None:
    """Assertion 7: Stage 2.5 POLISH_QUEUE skim present (D113 introduction)."""
    assert "Stage 2.5" in skill_content, (
        "CCL must include Stage 2.5 POLISH_QUEUE skim sub-stage"
    )
    assert "POLISH_QUEUE.md" in skill_content, (
        "Stage 2.5 must reference POLISH_QUEUE.md"
    )
    assert "D113" in skill_content, (
        "Stage 2.5 must cite D113 (POLISH_QUEUE.md introduction decision)"
    )


def test_section_9_pattern_f_post_cascade_audit_present(skill_content: str) -> None:
    """Assertion 8: Section 9 Pattern F post-cascade audit present (D89-D91 substrate).

    Section 9 is load-bearing — it is the round-level Gate-equivalent that
    Pattern F doctrine relies on. Silent removal would break D89-D91 enforcement.
    """
    assert "### Section 9 — Post-cascade audit" in skill_content, (
        "Section 9 Pattern F header must be present"
    )
    assert "Pattern F" in skill_content, (
        "Section 9 must explicitly reference Pattern F doctrine"
    )
    assert "D89" in skill_content, "Section 9 must cite D89 (Pattern F locking decision)"


def test_section_10_self_improvement_loop_present(skill_content: str) -> None:
    """Assertion 9: Section 10 self-improvement loop present (D95-D99 substrate).

    Section 10 is the canonical entry point for the 7-skill self-improvement cascade
    per D95-D99. Silent removal would break the entire skill suite invocation chain.
    """
    assert "### Section 10 — Self-improvement loop invocation" in skill_content, (
        "Section 10 self-improvement header must be present"
    )
    assert "D95" in skill_content, "Section 10 must cite D95 (umbrella self-improvement decision)"
    # All 7 sub-section skills must be referenced
    for skill_name in [
        "udm-retrospective-collector",
        "udm-specialty-tuner",
        "udm-subclass-accumulator",
        "udm-producer-checklist-evolver",
        "udm-cycle-cadence-optimizer",
        "udm-cascade-audit-evolver",
        "udm-agent-prompt-versioner",
    ]:
        assert skill_name in skill_content, (
            f"Section 10 must reference self-improvement skill {skill_name}"
        )
