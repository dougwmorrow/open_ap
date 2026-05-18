"""Tier 0 build-time smoke tests for `.claude/skills/udm-checks-and-balances/SKILL.md`.

Per D67 — runs at build time + every commit; runtime ceiling < 5 s; no DB / network.

Pins the canonical content of the udm-checks-and-balances SKILL.md against silent
regression. Specifically locks the 4-skill B-408 cohort canonicalization:
  - Gate 3 series list = M/S/I/N/P/G/D/F/V/DP/T/SI/SE/PL (14 canonical series)
  - Stage 2.5 POLISH_QUEUE skim (D113)
  - 5-gate structure preserved
  - D56 second-pass discipline preserved
  - D72 convergence rule preserved

B-457 closure: same prevent-silent-regression pattern as `test_skill_progress_logger.py`
that pins v1.2.0/v1.3.0/v1.3.1 directives.

This file's assertions cover:
  - File exists at canonical path + YAML frontmatter parses
  - Frontmatter declares name: udm-checks-and-balances
  - Gate 3 series list contains the canonical 14-series enumeration
  - B-408 closure citation present (anchors the canonicalization)
  - Stage 2.5 POLISH_QUEUE skim present (D113)
  - All 5 gates present as canonical headers
  - D56 second-pass section present
  - D72 convergence rule present
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILL_PATH = REPO_ROOT / ".claude" / "skills" / "udm-checks-and-balances" / "SKILL.md"


@pytest.fixture(scope="module")
def skill_content() -> str:
    """Load SKILL.md content once per module run."""
    assert SKILL_PATH.is_file(), f"SKILL.md not found at {SKILL_PATH}"
    return SKILL_PATH.read_text(encoding="utf-8")


def test_skill_file_exists() -> None:
    """Assertion 1: SKILL.md exists at the canonical path."""
    assert SKILL_PATH.is_file(), f"Expected SKILL.md at {SKILL_PATH}"


def test_frontmatter_name(skill_content: str) -> None:
    """Assertion 2: frontmatter declares `name: udm-checks-and-balances`."""
    assert skill_content.startswith("---\n"), "SKILL.md must open with --- delimiter"
    end_idx = skill_content.find("\n---\n", 4)
    assert end_idx > 0, "SKILL.md must close frontmatter with ---"
    frontmatter = skill_content[4:end_idx]
    assert "name: udm-checks-and-balances" in frontmatter, (
        "frontmatter must declare name: udm-checks-and-balances"
    )


def test_gate_3_series_list_canonical_14_series(skill_content: str) -> None:
    """Assertion 3 (B-408 canonicalization): Gate 3 series list contains all 14 canonical series.

    Per B-408 atomic 4-skill fix 2026-05-17 — was stale at 9 since Round 6 DP series addition;
    every Gate 3 walk silently incomplete since then. Canonical enumeration:
    M/S/I/N/P/G/D/F/V/DP/T/SI/SE/PL.
    """
    # Gate 3 header
    assert "### Gate 3: Edge case enumeration" in skill_content, (
        "Gate 3 header must be present"
    )
    # The canonical series list must appear verbatim (parenthetical enumeration form)
    canonical_series_list = "(M/S/I/N/P/G/D/F/V/DP/T/SI/SE/PL)"
    assert canonical_series_list in skill_content, (
        f"Gate 3 must cite canonical series list {canonical_series_list} "
        "(B-408 atomic 4-skill series-list fix 2026-05-17)"
    )
    # The "14 canonical series" assertion must be present
    assert "14 canonical series" in skill_content, (
        "Gate 3 must explicitly state '14 canonical series' "
        "(per B-408; was stale at 9 since Round 6)"
    )


def test_gate_3_b_408_closure_citation_present(skill_content: str) -> None:
    """Assertion 4: B-408 closure citation present in Gate 3 (anchors the canonicalization).

    Without the B-N citation, the canonicalization is detached from its closure mechanism
    and silent removal is undetectable. The B-408 reference is the audit trail back to
    the closure commit `895ae59`.
    """
    assert "B-408" in skill_content, (
        "Gate 3 must cite B-408 (atomic 4-skill series-list fix anchor)"
    )


def test_stage_2_5_polish_queue_skim_present(skill_content: str) -> None:
    """Assertion 5: Stage 2.5 POLISH_QUEUE skim present (D113 introduction).

    Stage 2.5 is the canonical hook for routing cosmetic-only findings to POLISH_QUEUE
    instead of polluting BACKLOG WSJF view per D113.
    """
    assert "Stage 2.5" in skill_content, (
        "CCL must include Stage 2.5 POLISH_QUEUE skim sub-stage"
    )
    assert "POLISH_QUEUE.md" in skill_content, (
        "Stage 2.5 must reference POLISH_QUEUE.md"
    )
    assert "D113" in skill_content, (
        "Stage 2.5 must cite D113 (POLISH_QUEUE.md introduction decision)"
    )


def test_all_5_gates_present_as_headers(skill_content: str) -> None:
    """Assertion 6: all 5 canonical gates present as section headers.

    The 5-gate structure is load-bearing — every gate must be invocable. Silent removal
    of any gate header would break the validation discipline.
    """
    canonical_gate_headers = [
        "### Gate 1: Cross-reference validation",
        "### Gate 2: Quality assurance",
        "### Gate 3: Edge case enumeration",
        "### Gate 4: Edge case validation",
        "### Gate 5: Idempotency",
    ]
    for header in canonical_gate_headers:
        assert header in skill_content, (
            f"Gate header missing: {header!r}"
        )


def test_d56_second_pass_validation_section_present(skill_content: str) -> None:
    """Assertion 7: D56 second-pass validation section present.

    Per D56 — when first-pass returns 🔴, second-pass by independent agent required
    before status flip. Silent removal would break the producer ≠ first-pass ≠ second-pass
    discipline.
    """
    assert "## Second-pass validation (D56)" in skill_content, (
        "Second-pass validation section (D56) must be present"
    )
    assert "D56" in skill_content, "D56 must be cited"
    # The independence-non-negotiable language
    assert "Independence is non-negotiable" in skill_content, (
        "D56 section must include 'Independence is non-negotiable' canonical phrasing"
    )


def test_d72_convergence_rule_present(skill_content: str) -> None:
    """Assertion 8: D72 convergence rule present in second-pass section.

    Per D72 (locked 2026-05-10) — convergence rule: 10-cycle ceiling + 3-consecutive-clean.
    Load-bearing for round close-out cycle ledger.
    """
    assert "D72" in skill_content, "D72 must be cited"
    # The canonical convergence rule phrasing
    assert "10 cycles" in skill_content, "D72 must cite 10-cycle ceiling"
    assert "3 consecutive" in skill_content, "D72 must cite 3-consecutive-clean rule"
