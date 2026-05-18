"""Tier 0 self-test for `tests/tier0/_tier0_test_base.py` per B-469 closure.

Verifies the 3 CLI-tool factory functions produce pytest test functions that
correctly pin canonical baseline assertions (module imports + EVENT_TYPE
constant + EXIT_* constants per D74/D76).

Parallels `tests/tier0/test_skill_test_base.py` (B-461) for SKILL.md factory
pattern. Both modules are internal test infrastructure with no production
public API surface.
"""
from __future__ import annotations

import pytest

from tests.tier0._tier0_test_base import (
    REPO_ROOT,
    make_baseline_test_exit_codes,
    make_baseline_test_event_type_constant,
    make_baseline_test_module_imports,
)


# ---------------------------------------------------------------------------
# REPO_ROOT module constant
# ---------------------------------------------------------------------------


def test_repo_root_resolves_to_repo_directory():
    """B-469 Assertion 1: REPO_ROOT resolves to the repo root directory.

    Pins that the path-resolution logic (tests/tier0/_tier0_test_base.py →
    tests/tier0/ → tests/ → repo) produces a directory containing the
    canonical project markers (CLAUDE.md + docs/migration/)."""
    assert REPO_ROOT.is_dir()
    assert (REPO_ROOT / "CLAUDE.md").is_file()
    assert (REPO_ROOT / "docs" / "migration").is_dir()


# ---------------------------------------------------------------------------
# make_baseline_test_module_imports factory
# ---------------------------------------------------------------------------


def test_make_baseline_test_module_imports_returns_callable():
    """B-469 Assertion 2: factory returns a callable test function."""
    test_fn = make_baseline_test_module_imports("tools.check_commit_msg")
    assert callable(test_fn)


def test_make_baseline_test_module_imports_passes_on_real_module():
    """B-469 Assertion 3: generated test PASSES when invoked on a real
    importable module (using tools.check_commit_msg as canonical-known-good)."""
    test_fn = make_baseline_test_module_imports("tools.check_commit_msg")
    # Test passes when no AssertionError raised
    test_fn()  # Should not raise


def test_make_baseline_test_module_imports_fails_on_missing_module():
    """B-469 Assertion 4: generated test RAISES AssertionError when module
    cannot be imported (catches silent rename/move regression)."""
    test_fn = make_baseline_test_module_imports("tools.nonexistent_module_xyz")
    with pytest.raises(AssertionError) as exc_info:
        test_fn()
    assert "failed to import" in str(exc_info.value)
    assert "nonexistent_module_xyz" in str(exc_info.value)


# ---------------------------------------------------------------------------
# make_baseline_test_event_type_constant factory
# ---------------------------------------------------------------------------


def test_make_baseline_test_event_type_constant_returns_callable():
    """B-469 Assertion 5: factory returns a callable test function."""
    test_fn = make_baseline_test_event_type_constant(
        "tools.check_commit_msg", "CLI_CHECK_COMMIT_MSG",
    )
    assert callable(test_fn)


def test_make_baseline_test_event_type_constant_passes_on_correct_value():
    """B-469 Assertion 6: generated test PASSES when module declares correct
    EVENT_TYPE matching expected (using tools.check_commit_msg as canonical)."""
    test_fn = make_baseline_test_event_type_constant(
        "tools.check_commit_msg", "CLI_CHECK_COMMIT_MSG",
    )
    test_fn()  # Should not raise


def test_make_baseline_test_event_type_constant_fails_on_drift():
    """B-469 Assertion 7: generated test RAISES AssertionError when actual
    EVENT_TYPE drifts from expected (catches silent rename regression)."""
    test_fn = make_baseline_test_event_type_constant(
        "tools.check_commit_msg", "CLI_WRONG_NAME",
    )
    with pytest.raises(AssertionError) as exc_info:
        test_fn()
    assert "drift detected" in str(exc_info.value)
    assert "CLI_WRONG_NAME" in str(exc_info.value)


# ---------------------------------------------------------------------------
# make_baseline_test_exit_codes factory
# ---------------------------------------------------------------------------


def test_make_baseline_test_exit_codes_returns_callable():
    """B-469 Assertion 8: factory returns a callable test function."""
    test_fn = make_baseline_test_exit_codes("tools.check_commit_msg")
    assert callable(test_fn)


def test_make_baseline_test_exit_codes_passes_on_canonical_values():
    """B-469 Assertion 9: generated test PASSES when module declares EXIT_SUCCESS
    + EXIT_FATAL with expected values. Uses tools.query_blindspots which has
    canonical EXIT_SUCCESS=0 + EXIT_FATAL=3 (D74-variant per project empirical
    distribution); passes `expected_exit_fatal=3` to match."""
    test_fn = make_baseline_test_exit_codes(
        "tools.query_blindspots", expected_exit_fatal=3,
    )
    test_fn()  # Should not raise


def test_make_baseline_test_exit_codes_fails_on_value_drift():
    """B-469 Assertion 10: generated test RAISES AssertionError when actual
    EXIT_FATAL value drifts from expected (catches silent value-change
    regression). Uses tools.query_blindspots with expected_exit_fatal=2
    (wrong; actual is 3) to trigger the drift detection."""
    test_fn = make_baseline_test_exit_codes(
        "tools.query_blindspots", expected_exit_fatal=2,
    )
    with pytest.raises(AssertionError) as exc_info:
        test_fn()
    assert "EXIT_FATAL drift" in str(exc_info.value)
    assert "actual=3" in str(exc_info.value)
    assert "expected=2" in str(exc_info.value)


def test_make_baseline_test_exit_codes_fails_on_missing_constant():
    """B-469 Assertion 11: generated test RAISES AssertionError when module
    lacks EXIT_FATAL constant (catches silent drop regression). Uses
    tools.check_commit_msg which has EXIT_SUCCESS=0 + EXIT_BLOCKED=1 but NOT
    EXIT_FATAL — perfect negative test."""
    test_fn = make_baseline_test_exit_codes("tools.check_commit_msg")
    with pytest.raises(AssertionError) as exc_info:
        test_fn()
    assert "EXIT_FATAL" in str(exc_info.value)
