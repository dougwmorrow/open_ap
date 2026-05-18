"""Tier 0 self-tests for `tests/tier0/_skill_test_base.py` shared scaffolding.

Per D67 — runs at build time + every commit; runtime ceiling < 5 s; no DB / network.

Validates the public surface of `_skill_test_base.py` per B-461 closure:
  - REPO_ROOT resolves to project root (contains CLAUDE.md)
  - get_skill_path() returns correct path for known skill
  - get_skill_path() returns Path objects (typed correctly)
  - make_skill_content_fixture() returns a callable usable by pytest
  - CanonicalAssertion dataclass shape (frozen + field defaults)
  - assert_skill_contains_substrings() positive + negative paths
  - assert_skill_matches_regexes() positive + negative paths
  - make_baseline_test_skill_exists() produces passing test for existing skill
  - make_baseline_test_frontmatter_name() produces passing test for valid skill

Pin-canonical-text discipline — assertions over the module's public surface so
silent removal/rename is detected at build time.
"""
from __future__ import annotations

from dataclasses import is_dataclass
from pathlib import Path

import pytest

from tests.tier0._skill_test_base import (
    CanonicalAssertion,
    REPO_ROOT,
    assert_skill_contains_substrings,
    assert_skill_matches_regexes,
    get_skill_path,
    make_baseline_test_frontmatter_name,
    make_baseline_test_skill_exists,
    make_skill_content_fixture,
)


def test_repo_root_resolves_to_project_root() -> None:
    """Assertion 1: REPO_ROOT resolves to project root containing CLAUDE.md.

    The resolver walks tests/tier0/_skill_test_base.py → tests/tier0/ → tests/ → repo.
    CLAUDE.md presence is the project-root sentinel.
    """
    assert isinstance(REPO_ROOT, Path), "REPO_ROOT must be a Path object"
    assert (REPO_ROOT / "CLAUDE.md").is_file(), (
        f"REPO_ROOT must contain CLAUDE.md (got {REPO_ROOT})"
    )
    # Also verify the .claude directory exists (canonical skill home)
    assert (REPO_ROOT / ".claude" / "skills").is_dir(), (
        f"REPO_ROOT must contain .claude/skills/ directory (got {REPO_ROOT})"
    )


def test_get_skill_path_returns_correct_path() -> None:
    """Assertion 2: get_skill_path() composes the canonical SKILL.md path.

    Uses udm-progress-logger (known to exist per recent build) as the test target.
    """
    path = get_skill_path("udm-progress-logger")
    assert isinstance(path, Path), "get_skill_path must return a Path object"
    # Canonical path components
    assert path.name == "SKILL.md", "Path must end in SKILL.md"
    assert path.parent.name == "udm-progress-logger", (
        "Path parent must match skill_name"
    )
    assert path.parent.parent.name == "skills", (
        "Path grandparent must be 'skills' (per .claude/skills/<name>/SKILL.md layout)"
    )
    # The SKILL.md should actually exist for this known skill
    assert path.is_file(), (
        f"get_skill_path('udm-progress-logger') must point to existing file ({path})"
    )


def test_get_skill_path_returns_path_for_nonexistent_skill() -> None:
    """Assertion 3: get_skill_path() returns a Path even for non-existent skill name.

    Per canonical contract — path composition is pure; file existence check is the
    caller's responsibility (typically via the baseline `test_skill_file_exists`).
    """
    path = get_skill_path("nonexistent-skill-xyz")
    assert isinstance(path, Path), "Must return Path even for non-existent skill"
    assert not path.is_file(), "Path should not actually exist on disk"


def test_make_skill_content_fixture_returns_callable() -> None:
    """Assertion 4: make_skill_content_fixture() returns a pytest-discoverable fixture object.

    Pytest's @pytest.fixture decorator wraps the function in a FixtureFunctionMarker /
    FixtureFunctionDefinition object (varies across pytest versions — older versions
    expose `_pytestfixturefunction` attribute on the function; newer versions wrap the
    function in a marker object). We check for either marker form OR repr text — robust
    against pytest version drift.
    """
    fixture = make_skill_content_fixture("udm-progress-logger")
    # Either it's callable (decorated function form) OR a fixture-marker object (wrapped form)
    is_decorated_function = callable(fixture) and hasattr(fixture, "_pytestfixturefunction")
    is_fixture_marker = "fixture" in repr(fixture).lower()
    assert is_decorated_function or is_fixture_marker, (
        f"make_skill_content_fixture must return a pytest fixture "
        f"(got {type(fixture).__name__}: {fixture!r})"
    )


def test_canonical_assertion_dataclass_shape() -> None:
    """Assertion 5: CanonicalAssertion is a frozen dataclass with expected fields.

    Verifies the forward-extensible declarative-spec shape per reviewer 🟡 IMPROVE.
    """
    assert is_dataclass(CanonicalAssertion), "CanonicalAssertion must be a dataclass"
    # Construct with minimal args (only `name` required)
    ca = CanonicalAssertion(name="test_example")
    assert ca.name == "test_example"
    assert ca.must_contain == [], "must_contain default must be empty list"
    assert ca.must_match_regex == [], "must_match_regex default must be empty list"
    assert ca.failure_hint == "", "failure_hint default must be empty string"

    # Construct with full args
    ca_full = CanonicalAssertion(
        name="test_full",
        must_contain=["foo", "bar"],
        must_match_regex=[r"\d+"],
        failure_hint="this is a hint",
    )
    assert ca_full.must_contain == ["foo", "bar"]
    assert ca_full.must_match_regex == [r"\d+"]
    assert ca_full.failure_hint == "this is a hint"

    # Frozen — attempting to mutate raises
    with pytest.raises((AttributeError, Exception)):
        ca_full.name = "mutated"  # type: ignore[misc]


def test_assert_skill_contains_substrings_positive() -> None:
    """Assertion 6 (positive path): assert_skill_contains_substrings passes when all substrings present."""
    content = "hello world foo bar baz"
    # Should not raise
    assert_skill_contains_substrings(content, ["hello", "foo", "baz"])
    assert_skill_contains_substrings(content, ["hello"], hint="single-substring case")
    # Empty list of substrings — vacuously true
    assert_skill_contains_substrings(content, [])


def test_assert_skill_contains_substrings_negative() -> None:
    """Assertion 7 (negative path): assert_skill_contains_substrings raises AssertionError on missing substring."""
    content = "hello world"
    with pytest.raises(AssertionError) as exc_info:
        assert_skill_contains_substrings(content, ["hello", "missing"])
    assert "missing" in str(exc_info.value), (
        "Error message must cite the missing substring"
    )
    # Hint propagation
    with pytest.raises(AssertionError) as exc_info:
        assert_skill_contains_substrings(content, ["absent"], hint="canonical-string-X")
    assert "canonical-string-X" in str(exc_info.value), (
        "Hint must appear in assertion failure message"
    )


def test_assert_skill_matches_regexes_positive() -> None:
    """Assertion 8 (positive path): assert_skill_matches_regexes passes when all patterns match."""
    content = "version 1.2.3 released on 2026-05-18"
    # Should not raise
    assert_skill_matches_regexes(content, [r"\d+\.\d+\.\d+", r"\d{4}-\d{2}-\d{2}"])
    # Empty list of patterns — vacuously true
    assert_skill_matches_regexes(content, [])


def test_assert_skill_matches_regexes_negative() -> None:
    """Assertion 9 (negative path): assert_skill_matches_regexes raises AssertionError on non-matching pattern."""
    content = "hello world"
    with pytest.raises(AssertionError) as exc_info:
        assert_skill_matches_regexes(content, [r"\d{4}"])
    err_msg = str(exc_info.value)
    assert "\\d{4}" in err_msg or "d{4}" in err_msg, (
        "Error message must cite the non-matching pattern"
    )
    # Hint propagation
    with pytest.raises(AssertionError) as exc_info:
        assert_skill_matches_regexes(
            content, [r"\d+"], hint="version-string-pattern-required"
        )
    assert "version-string-pattern-required" in str(exc_info.value), (
        "Hint must appear in assertion failure message"
    )


def test_make_baseline_test_skill_exists_passes_for_existing() -> None:
    """Assertion 10: make_baseline_test_skill_exists() produces passing test for existing skill."""
    test_fn = make_baseline_test_skill_exists("udm-progress-logger")
    assert callable(test_fn), "Must return a callable"
    # Should not raise
    test_fn()


def test_make_baseline_test_skill_exists_fails_for_nonexistent() -> None:
    """Assertion 11: make_baseline_test_skill_exists() produces failing test for non-existent skill."""
    test_fn = make_baseline_test_skill_exists("nonexistent-skill-xyz-b461")
    with pytest.raises(AssertionError) as exc_info:
        test_fn()
    assert "nonexistent-skill-xyz-b461" in str(exc_info.value), (
        "Failure message must cite the missing skill path"
    )


def test_make_baseline_test_frontmatter_name_passes_for_valid() -> None:
    """Assertion 12: make_baseline_test_frontmatter_name() produces passing test for valid SKILL.md."""
    test_fn = make_baseline_test_frontmatter_name("udm-progress-logger")
    assert callable(test_fn), "Must return a callable"
    # Provide valid SKILL.md content with matching frontmatter
    valid_content = (
        "---\n"
        "name: udm-progress-logger\n"
        "description: Test description\n"
        "---\n"
        "\n"
        "# Body content here\n"
    )
    # Should not raise
    test_fn(valid_content)


def test_make_baseline_test_frontmatter_name_fails_on_wrong_name() -> None:
    """Assertion 13: make_baseline_test_frontmatter_name() fails when frontmatter declares wrong name."""
    test_fn = make_baseline_test_frontmatter_name("udm-progress-logger")
    wrong_content = (
        "---\n"
        "name: udm-other-skill\n"
        "description: Test description\n"
        "---\n"
        "\n"
        "# Body\n"
    )
    with pytest.raises(AssertionError) as exc_info:
        test_fn(wrong_content)
    assert "udm-progress-logger" in str(exc_info.value), (
        "Failure message must cite the expected skill name"
    )


def test_make_baseline_test_frontmatter_name_fails_on_missing_delimiter() -> None:
    """Assertion 14: make_baseline_test_frontmatter_name() fails when --- delimiters absent."""
    test_fn = make_baseline_test_frontmatter_name("udm-progress-logger")
    # Missing opening delimiter
    no_open_delim = "name: udm-progress-logger\n# Body\n"
    with pytest.raises(AssertionError):
        test_fn(no_open_delim)
    # Missing closing delimiter (frontmatter never closes)
    no_close_delim = (
        "---\n"
        "name: udm-progress-logger\n"
        "description: never closes\n"
    )
    with pytest.raises(AssertionError):
        test_fn(no_close_delim)
