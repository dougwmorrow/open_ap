"""Tier 0 build-time smoke tests for `.claude/skills/udm-gap-check/SKILL.md`.

Per D67 — runs at build time + every commit; runtime ceiling < 5 s; no DB / network.

Pins the canonical content of the udm-gap-check SKILL.md against silent regression.
Specifically locks the 4-skill B-408 cohort canonicalization:
  - Category 3 Pitfall #9 walk header covers 9.a-9.o (15 sub-classes)
  - "15 sub-classes total" explicit narrative assertion
  - All 6 canonical categories present
  - All 15 sub-class entries enumerated (9.a through 9.o)
  - 9.n and 9.o sub-classes explicitly described (latest additions)

B-457 closure: same prevent-silent-regression pattern as `test_skill_progress_logger.py`
that pins v1.2.0/v1.3.0/v1.3.1 directives.

This file's assertions cover:
  - File exists at canonical path + YAML frontmatter parses
  - Frontmatter declares name: udm-gap-check
  - Category 3 Pitfall #9 walk header cites 9.a-9.o
  - "15 sub-classes total" explicit assertion present
  - All 6 canonical Categories present as section headers
  - All 15 sub-classes (9.a through 9.o) enumerated under Category 3
  - 9.n (convention-registration) explicitly described
  - 9.o (anti-rationalization-clause compliance) explicitly described
  - B-408 closure citation present (anchors the canonicalization)
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILL_PATH = REPO_ROOT / ".claude" / "skills" / "udm-gap-check" / "SKILL.md"


@pytest.fixture(scope="module")
def skill_content() -> str:
    """Load SKILL.md content once per module run."""
    assert SKILL_PATH.is_file(), f"SKILL.md not found at {SKILL_PATH}"
    return SKILL_PATH.read_text(encoding="utf-8")


def test_skill_file_exists() -> None:
    """Assertion 1: SKILL.md exists at the canonical path."""
    assert SKILL_PATH.is_file(), f"Expected SKILL.md at {SKILL_PATH}"


def test_frontmatter_name(skill_content: str) -> None:
    """Assertion 2: frontmatter declares `name: udm-gap-check`."""
    assert skill_content.startswith("---\n"), "SKILL.md must open with --- delimiter"
    end_idx = skill_content.find("\n---\n", 4)
    assert end_idx > 0, "SKILL.md must close frontmatter with ---"
    frontmatter = skill_content[4:end_idx]
    assert "name: udm-gap-check" in frontmatter, (
        "frontmatter must declare name: udm-gap-check"
    )


def test_category_3_pitfall_9_walk_range_9_a_to_9_o(skill_content: str) -> None:
    """Assertion 3 (B-408 canonicalization): Category 3 Pitfall #9 walk covers 9.a-9.o.

    Per B-408 atomic 4-skill fix 2026-05-17 — was stale at 9.a-9.m missing 9.n + 9.o.
    Category 3 is the canonical entry point for Pitfall sub-class scanning during
    gap-check; silent stale-range = silent gap in the audit walk.
    """
    # Category 3 header
    assert "### Category 3 — Pitfall #9 sub-class instances" in skill_content, (
        "Category 3 header must be present"
    )
    # The canonical scan-range citation
    assert "9.a-9.o" in skill_content, (
        "Category 3 must cite canonical Pitfall #9 scan range 9.a-9.o "
        "(15 sub-classes total per B-408 atomic 4-skill fix)"
    )


def test_15_sub_classes_total_explicit_assertion(skill_content: str) -> None:
    """Assertion 4: "15 sub-classes total" explicit narrative assertion present.

    Per B-408 — explicit narrative count anchors the discipline against silent sub-class
    additions/removals. The narrative must explicitly state "15 sub-classes total".
    """
    assert "15 sub-classes total" in skill_content, (
        "'15 sub-classes total' explicit narrative assertion must be present "
        "(per B-408; was stale at 9.a-9.m before atomic fix)"
    )


def test_all_15_sub_class_letters_enumerated(skill_content: str) -> None:
    """Assertion 5 (B-408 canonicalization): all 15 sub-classes (9.a-9.o) enumerated.

    Per B-408 — Category 3 walks each sub-class. Each sub-class must have an enumerated
    bullet under Category 3. Silent removal of any sub-class bullet = silent gap.
    """
    canonical_sub_classes = [
        "9.a", "9.b", "9.c", "9.d", "9.e", "9.f", "9.g", "9.h",
        "9.i", "9.j", "9.k", "9.l", "9.m", "9.n", "9.o",
    ]
    for sub_class in canonical_sub_classes:
        # Match `**9.a` (the canonical bold-bullet form) within Category 3 body
        pattern = re.compile(rf"\*\*{re.escape(sub_class)}\b")
        assert pattern.search(skill_content), (
            f"Category 3 must enumerate sub-class {sub_class!r} "
            f"as bold bullet `**{sub_class}<rest>**` (per B-408 canonicalization)"
        )


def test_sub_class_9_n_convention_registration_explicitly_described(skill_content: str) -> None:
    """Assertion 6: 9.n (convention-registration-not-applied) explicitly described.

    9.n was added per Step 10 + B-261 closure + 3-event evidence base from Round 3 build
    campaign Waves 3+4+5 gap-checks. Latest addition to the canonical sub-class set
    before 9.o.
    """
    assert "9.n convention-registration" in skill_content, (
        "9.n must be explicitly described as 'convention-registration-not-applied-to-new-build-artifacts'"
    )
    # Reference to Step 10 + B-261 closure
    assert "Step 10" in skill_content, "9.n description must reference Step 10"
    assert "B-261" in skill_content, "9.n description must cite B-261 closure"


def test_sub_class_9_o_anti_rationalization_explicitly_described(skill_content: str) -> None:
    """Assertion 7: 9.o (anti-rationalization-clause compliance) explicitly described.

    9.o was added per hard rule 14 + 9-event evidence base. Latest addition to the
    canonical sub-class set. Critical for forward-prevention of anti-rationalization-
    clause compliance failure pattern (per Pitfall #9.o sub-class formalization).
    """
    assert "9.o anti-rationalization" in skill_content, (
        "9.o must be explicitly described as 'anti-rationalization-clause compliance'"
    )
    # Reference to hard rule 14 + canonical mechanisms
    assert "hard rule 14" in skill_content, "9.o description must reference hard rule 14"
    # Either udm-exemption-verifier OR quote-cite mechanism must be referenced
    assert (
        "udm-exemption-verifier" in skill_content
        or "cite-by-quotation" in skill_content
    ), (
        "9.o description must reference udm-exemption-verifier skill OR cite-by-quotation mechanism"
    )


def test_all_6_canonical_categories_present(skill_content: str) -> None:
    """Assertion 8: all 6 canonical categories present as section headers.

    The 6-category audit is canonical (per Hard Rule 3). Silent removal of any category
    header would break the gap-check discipline structure.
    """
    canonical_category_headers = [
        "### Category 1 — Cross-tracker drift",
        "### Category 2 — Untracked dependencies",
        "### Category 3 — Pitfall #9 sub-class instances",
        "### Category 4 — Convention registration gaps",
        "### Category 5 — Untracked B-N opportunities",
        "### Category 6 — Just-noticed issues",
    ]
    for header in canonical_category_headers:
        assert header in skill_content, (
            f"Category header missing: {header!r}"
        )


def test_hard_rule_1_blocks_green_status_without_gap_check_log(skill_content: str) -> None:
    """Assertion 9: Hard Rule 1 (no 🟢 without gap-check log) present.

    Per user-direction 2026-05-12 — Hard Rule 1 is the canonical operationalization that
    enforces gap-check as a precondition for status claims. Silent removal would
    convert the discipline back to optional.
    """
    assert "## Hard rules" in skill_content, "Hard rules section must be present"
    # Hard Rule 1 — the canonical "No 🟢 status claim without gap-check log" rule
    # (the SKILL.md formats this with markdown bold; check for the key phrase)
    assert "No 🟢 status claim" in skill_content, (
        "Hard Rule 1 must include 'No 🟢 status claim WITHOUT a gap-check' "
        "(canonical hard rule per user-direction 2026-05-12)"
    )
    assert "_validation_log.md" in skill_content, (
        "Hard Rule 1 must reference _validation_log.md entry requirement"
    )
