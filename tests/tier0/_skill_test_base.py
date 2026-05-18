"""Shared Tier 0 scaffolding for SKILL.md regression tests per B-461.

Forward-prevention infrastructure surfaced by Agent 68 architectural design review:
the 4 existing test_skill_*.py files (round_closeout / checks_and_balances /
edge_case_validator / gap_check) share substantial boilerplate (REPO_ROOT resolution,
SKILL_PATH pattern, skill_content fixture, test_skill_file_exists, test_frontmatter_*
assertions).

Usage pattern (callers — see `test_skill_round_closeout.py` etc. for live examples):

    from pathlib import Path
    import pytest

    from tests.tier0._skill_test_base import (
        CanonicalAssertion,
        assert_skill_contains_substrings,
        assert_skill_matches_regexes,
        get_skill_path,
        make_baseline_test_frontmatter_name,
        make_baseline_test_skill_exists,
        make_skill_content_fixture,
    )

    SKILL_NAME = "udm-round-closeout"
    SKILL_PATH = get_skill_path(SKILL_NAME)

    # Generate baseline fixture + 2 baseline tests via factory calls
    skill_content = make_skill_content_fixture(SKILL_NAME)
    test_skill_file_exists = make_baseline_test_skill_exists(SKILL_NAME)
    test_frontmatter_name = make_baseline_test_frontmatter_name(SKILL_NAME)

    # Skill-specific assertions on top
    def test_section_3_series_list_canonical_14_series(skill_content: str) -> None:
        assert_skill_contains_substrings(
            skill_content,
            ["(M/S/I/N/P/G/D/F/V/DP/T/SI/SE/PL)", "14 canonical series"],
            hint="B-408 atomic 4-skill series-list fix 2026-05-17",
        )

This module is INTERNAL test infrastructure — no public API surface added to
production code; no CLAUDE.md / GLOSSARY registration required per Step 10
canonical-public-surface registration discipline.

Pin-canonical-text discipline preserved — skill-specific assertions still pin the
exact canonical strings; only the shared boilerplate (fixture + frontmatter + file
existence) is factored.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import pytest


# Resolve repo root: tests/tier0/_skill_test_base.py → tests/tier0/ → tests/ → repo
REPO_ROOT: Path = Path(__file__).resolve().parent.parent.parent


def get_skill_path(skill_name: str) -> Path:
    """Return canonical path to SKILL.md for given skill name.

    Args:
        skill_name: Skill directory name (e.g. "udm-round-closeout").

    Returns:
        Path to `<REPO_ROOT>/.claude/skills/<skill_name>/SKILL.md`.
    """
    return REPO_ROOT / ".claude" / "skills" / skill_name / "SKILL.md"


def make_skill_content_fixture(skill_name: str) -> Callable:
    """Factory for module-scoped pytest fixture that reads the SKILL.md content.

    Per existing pattern in test_skill_*.py — fixture is module-scoped so the file
    is read once per test module rather than per-test.

    Args:
        skill_name: Skill directory name (e.g. "udm-round-closeout").

    Returns:
        A pytest fixture function. Caller assigns to a module-level name
        (typically `skill_content`) so pytest discovers it.
    """
    @pytest.fixture(scope="module")
    def _skill_content() -> str:
        skill_path = get_skill_path(skill_name)
        assert skill_path.is_file(), f"SKILL.md not found at {skill_path}"
        return skill_path.read_text(encoding="utf-8")
    return _skill_content


@dataclass(frozen=True)
class CanonicalAssertion:
    """Declarative spec for a SKILL.md content assertion.

    Forward-extensible per reviewer 🟡 IMPROVE — multi-substring / multi-regex
    cases handled in a single assertion entry without per-call duplication.

    Attributes:
        name: pytest test function name (must start with "test_").
        must_contain: substrings that MUST all be present in skill_content.
        must_match_regex: regex patterns that MUST all match against skill_content.
        failure_hint: human-readable hint for assertion error message.
    """
    name: str
    must_contain: list[str] = field(default_factory=list)
    must_match_regex: list[str] = field(default_factory=list)
    failure_hint: str = ""


def assert_skill_contains_substrings(
    skill_content: str,
    substrings: list[str],
    hint: str = "",
) -> None:
    """Assert all substrings are present in skill content.

    Args:
        skill_content: full SKILL.md content (typically from skill_content fixture).
        substrings: list of substrings that MUST all appear in skill_content.
        hint: optional human-readable hint appended to assertion failure message.

    Raises:
        AssertionError: if any substring is absent.
    """
    for substring in substrings:
        assert substring in skill_content, (
            f"SKILL.md missing canonical substring {substring!r}"
            + (f"; {hint}" if hint else "")
        )


def assert_skill_matches_regexes(
    skill_content: str,
    patterns: list[str],
    hint: str = "",
) -> None:
    """Assert all regex patterns match somewhere in skill content.

    Args:
        skill_content: full SKILL.md content (typically from skill_content fixture).
        patterns: list of regex patterns that MUST all match in skill_content.
        hint: optional human-readable hint appended to assertion failure message.

    Raises:
        AssertionError: if any pattern fails to match.
    """
    for pattern in patterns:
        assert re.search(pattern, skill_content), (
            f"SKILL.md missing canonical pattern {pattern!r}"
            + (f"; {hint}" if hint else "")
        )


def make_baseline_test_skill_exists(skill_name: str) -> Callable:
    """Factory for `test_skill_file_exists` assertion.

    Args:
        skill_name: Skill directory name (e.g. "udm-round-closeout").

    Returns:
        A pytest test function. Caller assigns to module-level
        `test_skill_file_exists` name so pytest discovers it.
    """
    skill_path = get_skill_path(skill_name)

    def test_skill_file_exists() -> None:
        """Assertion: SKILL.md exists at the canonical path."""
        assert skill_path.is_file(), (
            f"SKILL.md not found at expected canonical path: {skill_path}"
        )
    return test_skill_file_exists


def make_baseline_test_frontmatter_name(skill_name: str) -> Callable:
    """Factory for `test_frontmatter_name` assertion.

    Verifies that the YAML frontmatter declares `name: <skill_name>` and that the
    frontmatter delimiters are well-formed (opens with `---\\n`, closes with
    `\\n---\\n`).

    Args:
        skill_name: Skill directory name (e.g. "udm-round-closeout").

    Returns:
        A pytest test function. Caller assigns to module-level
        `test_frontmatter_name` name so pytest discovers it.
    """
    def test_frontmatter_name(skill_content: str) -> None:
        """Assertion: frontmatter declares `name: <skill_name>` between --- delimiters."""
        assert skill_content.startswith("---\n"), (
            "SKILL.md must open with --- delimiter"
        )
        end_idx = skill_content.find("\n---\n", 4)
        assert end_idx > 0, "SKILL.md must close frontmatter with ---"
        frontmatter = skill_content[4:end_idx]
        assert f"name: {skill_name}" in frontmatter, (
            f"frontmatter must declare name: {skill_name}"
        )
    return test_frontmatter_name
