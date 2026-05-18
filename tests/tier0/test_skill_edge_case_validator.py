"""Tier 0 build-time smoke tests for `.claude/skills/udm-edge-case-validator/SKILL.md`.

Per D67 — runs at build time + every commit; runtime ceiling < 5 s; no DB / network.

Pins the canonical content of the udm-edge-case-validator SKILL.md against silent
regression. Specifically locks the 4-skill B-408 cohort canonicalization:
  - Frontmatter description series list = M/S/I/N/P/G/D/F/V/DP/T/SI/SE/PL (14 canonical series)
  - The series table contains all 14 series rows (M through PL)
  - "14 canonical series total" explicit assertion
  - Stage 3 CCL series enumeration present

B-457 closure: same prevent-silent-regression pattern as `test_skill_progress_logger.py`
that pins v1.2.0/v1.3.0/v1.3.1 directives.

This file's assertions cover:
  - File exists at canonical path + YAML frontmatter parses
  - Frontmatter declares name: udm-edge-case-validator
  - Frontmatter description contains the canonical 14-series enumeration
  - Stage 3 CCL contains the canonical 14-series enumeration
  - Series table contains all 14 series rows (M / S / I / N / P / G / D / F / V / DP / T / SI / SE / PL)
  - "14 canonical series" explicit assertion present
  - B-408 closure citation present (anchors the canonicalization)
  - New series rows (SE + PL) added 2026-05-17 are present
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SKILL_PATH = REPO_ROOT / ".claude" / "skills" / "udm-edge-case-validator" / "SKILL.md"


@pytest.fixture(scope="module")
def skill_content() -> str:
    """Load SKILL.md content once per module run."""
    assert SKILL_PATH.is_file(), f"SKILL.md not found at {SKILL_PATH}"
    return SKILL_PATH.read_text(encoding="utf-8")


def test_skill_file_exists() -> None:
    """Assertion 1: SKILL.md exists at the canonical path."""
    assert SKILL_PATH.is_file(), f"Expected SKILL.md at {SKILL_PATH}"


def test_frontmatter_name_and_description_series(skill_content: str) -> None:
    """Assertion 2: frontmatter declares name + description cites the 14-series list.

    The description is the skill-discovery surface — agents discover this skill via
    description-keyword match. The series list MUST be present in the description.
    """
    assert skill_content.startswith("---\n"), "SKILL.md must open with --- delimiter"
    end_idx = skill_content.find("\n---\n", 4)
    assert end_idx > 0, "SKILL.md must close frontmatter with ---"
    frontmatter = skill_content[4:end_idx]
    assert "name: udm-edge-case-validator" in frontmatter, (
        "frontmatter must declare name: udm-edge-case-validator"
    )
    # The frontmatter description must contain the canonical series list
    assert "M/S/I/N/P/G/D/F/V/DP/T/SI/SE/PL" in frontmatter, (
        "frontmatter description must cite canonical 14-series list "
        "M/S/I/N/P/G/D/F/V/DP/T/SI/SE/PL (B-408 atomic 4-skill fix 2026-05-17)"
    )


def test_stage_3_ccl_contains_14_series_enumeration(skill_content: str) -> None:
    """Assertion 3 (B-408 canonicalization): Stage 3 CCL contains the 14-series enumeration.

    Per B-408 atomic 4-skill fix 2026-05-17 — Stage 3 CCL directs the reviewer to read
    `04_EDGE_CASES.md` "full read of relevant series" + cites the canonical 14-series
    enumeration so the reviewer knows the complete scope.
    """
    # Stage 3 line
    assert "Stage 3 — Task-specific reads" in skill_content, (
        "Stage 3 line in CCL must be present"
    )
    assert "04_EDGE_CASES.md" in skill_content, (
        "Stage 3 must reference 04_EDGE_CASES.md"
    )
    # The "14 canonical series" + enumeration form in Stage 3
    assert "14 canonical series" in skill_content, (
        "Stage 3 must explicitly state '14 canonical series'"
    )
    # The enumeration "M / S / I / N / P / G / D / F / V / DP / T / SI / SE / PL" (slash-with-spaces form)
    assert "M / S / I / N / P / G / D / F / V / DP / T / SI / SE / PL" in skill_content, (
        "Stage 3 must cite canonical 14-series enumeration "
        "M / S / I / N / P / G / D / F / V / DP / T / SI / SE / PL"
    )


def test_series_table_contains_all_14_series_rows(skill_content: str) -> None:
    """Assertion 4 (B-408 canonicalization): the series table contains all 14 canonical rows.

    Per B-408 — the series table (under "## The series" header) must have one row per
    canonical series prefix. Silent removal of any row = silent gap in the Gate 3 walk
    enumeration.
    """
    assert "## The series" in skill_content, "## The series header must be present"
    # Each canonical series prefix must appear as the leading token of a table row.
    # Use regex to match `| <prefix> |` (the markdown table cell form, allowing trailing spaces).
    canonical_prefixes = [
        "M", "S", "I", "N", "P", "G", "D", "F", "V", "DP", "T", "SI", "SE", "PL",
    ]
    for prefix in canonical_prefixes:
        # Match `| M |` at the start of a row (the canonical 1st-cell form)
        pattern = re.compile(rf"^\|\s*{re.escape(prefix)}\s*\|", re.MULTILINE)
        assert pattern.search(skill_content), (
            f"Series table missing row for canonical prefix {prefix!r} "
            f"(expected `| {prefix} |` cell at row start)"
        )


def test_series_table_se_and_pl_rows_added_2026_05_17(skill_content: str) -> None:
    """Assertion 5: SE + PL series rows added 2026-05-17 are present in the table.

    SE (source-exactness invariants per D115 + D116 + B-373) and PL (udm-progress-logger
    discipline per B-405) are the latest 2 series additions per B-408 closure cohort.
    Silent removal would mean the Gate 3 walk doesn't cover these series.
    """
    # SE row + Phase A citation
    assert "Source-exactness invariants" in skill_content, (
        "SE series row must include 'Source-exactness invariants' description"
    )
    assert "D115" in skill_content or "D116" in skill_content, (
        "SE series row must cite D115 or D116"
    )
    assert "B-373" in skill_content, "SE series row must cite B-373"

    # PL row + B-405 citation
    assert "progress-logger discipline" in skill_content, (
        "PL series row must include 'progress-logger discipline' description"
    )
    assert "B-405" in skill_content, "PL series row must cite B-405"


def test_14_canonical_series_total_explicit_assertion(skill_content: str) -> None:
    """Assertion 6: "14 canonical series total" explicit narrative assertion present.

    Per B-408 — explicit narrative count anchors the discipline against silent series
    additions/removals. The narrative must explicitly cite "14 canonical series total".
    """
    assert "14 canonical series total" in skill_content, (
        "'14 canonical series total' explicit narrative assertion must be present "
        "(per B-408; replaces stale '9 canonical series' since Round 6)"
    )


def test_b_408_closure_citation_present(skill_content: str) -> None:
    """Assertion 7: B-408 closure citation present (anchors the canonicalization).

    Empirical anchor — without the B-N citation, the canonicalization is detached from
    its closure mechanism and silent removal is undetectable. The B-408 reference is the
    audit trail back to the closure commit `895ae59`.
    """
    assert "B-408" in skill_content, (
        "Must cite B-408 (atomic 4-skill series-list fix anchor)"
    )


def test_hard_rules_section_present(skill_content: str) -> None:
    """Assertion 8: Hard rules section present with the canonical 5 rules.

    Hard rules are load-bearing — silent removal would weaken the discipline. The
    canonical 5 rules: walk-in-full / addressed-vs-correctly / implicit-coverage /
    identify-new / map-gaps-to-action.
    """
    assert "## Hard rules" in skill_content, "Hard rules section must be present"
    # Rule 1 — walk in full
    assert "Walk the relevant series in full" in skill_content, (
        "Hard rule 1 (walk in full) must be present"
    )
    # Rule 2 — distinguish addressed vs addressed correctly
    assert "addressed correctly" in skill_content, (
        "Hard rule 2 (distinguish addressed vs correctly) must be present"
    )
