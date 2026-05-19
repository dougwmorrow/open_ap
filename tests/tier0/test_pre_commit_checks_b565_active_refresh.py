"""Tier 0 tests for `check_session_resume_active_refresh` per B-565 closure 2026-05-19.

Forward-prevention for Pitfall #9.m recursive self-violation class.
2-event empirical anchor 2026-05-19: cross-cohort reviewer `ae0e5ea9c1b3851c0`
caught instance N at `c8bb55b..372e982`; remediation at `977514e` explicitly
called out the meta-irony + recursion-termination claim; very next substantive
commit `739eab1` REPEATED the violation; gap-check reviewer `a7f466490e1f64dc5`
caught instance N+1.

Per D67 — runs at build time + every commit; runtime ceiling < 5 s.
"""
from __future__ import annotations

from unittest.mock import patch

from tools.pre_commit_checks import (
    CHECKS,
    CheckResult,
    _BACKLOG_CLOSURE_FLIP_RE,
    _SESSION_RESUME_ACTIVE_PATTERN,
    check_session_resume_active_refresh,
)


def test_module_imports_and_check_registered() -> None:
    """Assertion 1: check_session_resume_active_refresh registered as CHECKS tail."""
    assert callable(check_session_resume_active_refresh)
    assert check_session_resume_active_refresh in CHECKS
    # MUST be the last entry per B-565 closure plan (append to registry);
    # pins against accidental reorder. Future check additions should land
    # as CHECKS[-1] and bump this assertion.
    assert CHECKS[-1] is check_session_resume_active_refresh
    assert _SESSION_RESUME_ACTIVE_PATTERN == "SESSION_RESUME/active/"
    assert _BACKLOG_CLOSURE_FLIP_RE is not None


def test_backlog_not_staged_returns_info() -> None:
    """Assertion 2: BACKLOG.md not in staged-files list → INFO skip."""
    result = check_session_resume_active_refresh([
        "tools/pre_commit_checks.py",
        "tests/tier0/test_something.py",
    ])
    assert isinstance(result, CheckResult)
    assert result.passed is True
    assert result.severity == "info"
    assert "BACKLOG.md not in staged files" in result.diagnostic


def test_closure_flip_regex_matches_canonical_format() -> None:
    """Assertion 3: regex captures B-N integers from diff-format closure lines."""
    diff_sample = (
        "+- ~~**B-558**~~ (⚫ CLOSED 2026-05-19; HIGH; WSJF 3.5)\n"
        "+- ~~**B-559**~~ (⚫ CLOSED 2026-05-19; MEDIUM; WSJF 2.0)\n"
        " (unchanged context line)\n"
        "-- old line removed\n"
    )
    matches = _BACKLOG_CLOSURE_FLIP_RE.findall(diff_sample)
    assert sorted(matches, key=int) == ["558", "559"]


def test_backlog_staged_with_closure_AND_active_refresh_passes() -> None:
    """Assertion 4: BACKLOG.md + closure annotation + active/ refresh → PASS."""
    staged = [
        "docs/migration/BACKLOG.md",
        "SESSION_RESUME/active/meta-discipline.md",
        "docs/migration/_validation_log.md",
    ]
    fake_diff = "+- ~~**B-999**~~ (⚫ CLOSED 2026-05-19; LOW; WSJF 1.0)\n"
    with patch("tools.pre_commit_checks._get_staged_diff", return_value=fake_diff):
        result = check_session_resume_active_refresh(staged)
    assert result.passed is True
    assert result.severity == "info"
    assert "discipline satisfied" in result.diagnostic


def test_backlog_staged_with_closure_WITHOUT_active_refresh_warns() -> None:
    """Assertion 5: BACKLOG.md + closure annotation but NO active/ refresh → WARN."""
    staged = [
        "docs/migration/BACKLOG.md",
        "docs/migration/_validation_log.md",
        # NO SESSION_RESUME/active/*.md
    ]
    fake_diff = "+- ~~**B-999**~~ (⚫ CLOSED 2026-05-19; LOW; WSJF 1.0)\n"
    with patch("tools.pre_commit_checks._get_staged_diff", return_value=fake_diff):
        result = check_session_resume_active_refresh(staged)
    assert result.passed is False
    assert result.severity == "warn"
    assert "B-999" in result.diagnostic
    assert "WITHOUT corresponding SESSION_RESUME/active" in result.diagnostic


def test_backlog_staged_but_no_closure_returns_info() -> None:
    """Assertion 6: BACKLOG.md staged but no closure annotation in diff → INFO."""
    staged = ["docs/migration/BACKLOG.md"]
    # Diff that adds a NEW B-N open entry (not a closure)
    fake_diff = "+- **B-999** (🟡 Open; LOW; WSJF 1.0): NEW B-N body\n"
    with patch("tools.pre_commit_checks._get_staged_diff", return_value=fake_diff):
        result = check_session_resume_active_refresh(staged)
    assert result.passed is True
    assert result.severity == "info"
    assert "no B-N closure annotations" in result.diagnostic


def test_multiple_closures_enumerated_in_warn_diagnostic() -> None:
    """Assertion 7: multiple closures → all B-Ns cited in WARN (up to cap 10)."""
    staged = ["docs/migration/BACKLOG.md"]
    fake_diff = (
        "+- ~~**B-100**~~ (⚫ CLOSED 2026-05-19)\n"
        "+- ~~**B-200**~~ (⚫ CLOSED 2026-05-19)\n"
        "+- ~~**B-300**~~ (⚫ CLOSED 2026-05-19)\n"
    )
    with patch("tools.pre_commit_checks._get_staged_diff", return_value=fake_diff):
        result = check_session_resume_active_refresh(staged)
    assert result.passed is False
    assert result.severity == "warn"
    for bn in ("B-100", "B-200", "B-300"):
        assert bn in result.diagnostic
    assert "3 B-N closure annotation(s)" in result.diagnostic
