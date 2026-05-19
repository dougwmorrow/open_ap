"""Tier 0 smoke tests for `check_snapshot_claims` per B-558 Phase 2.1 Component A.

Per D67 — runs at build time + every commit; runtime ceiling < 5 s.
Pins snapshot-frontmatter-hallucination forward-prevention check behavior.

Plan reference: `docs/migration/UDM_SESSION_COMPACTOR_PHASE_2_1_PLAN_2026-05-19.md` §3.1.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from tools.pre_commit_checks import (
    CHECKS,
    CheckResult,
    _SNAPSHOT_COMMIT_HASH_RE,
    _SNAPSHOT_DIR_PREFIX,
    _git_log_contains_hash,
    check_snapshot_claims,
)


def test_module_imports_and_check_registered() -> None:
    """Assertion 1: check_snapshot_claims importable + registered in CHECKS list."""
    assert callable(check_snapshot_claims)
    assert check_snapshot_claims in CHECKS
    # MUST be the last entry per Phase 2.1 plan §3.1 ("append to CHECKS registry
    # at next available slot"); pins against accidental reorder
    assert CHECKS[-1] is check_snapshot_claims
    # Constants exported
    assert _SNAPSHOT_DIR_PREFIX == "docs/migration/_session_snapshots/"
    assert _SNAPSHOT_COMMIT_HASH_RE is not None


def test_no_staged_snapshot_files_returns_info() -> None:
    """Assertion 2: empty staged-files list returns INFO (skip)."""
    result = check_snapshot_claims([])
    assert isinstance(result, CheckResult)
    assert result.passed is True
    assert result.severity == "info"
    assert "no staged snapshot files" in result.diagnostic


def test_staged_non_snapshot_markdown_skipped() -> None:
    """Assertion 3: staged markdown OUTSIDE _session_snapshots/ filtered out."""
    result = check_snapshot_claims([
        "docs/migration/BACKLOG.md",
        "tests/tier0/test_something.py",
        "CLAUDE.md",
    ])
    assert result.passed is True
    assert result.severity == "info"
    assert "no staged snapshot files" in result.diagnostic


def test_frontmatter_regex_matches_canonical_format() -> None:
    """Assertion 4: regex matches the canonical snapshot frontmatter pattern."""
    content = (
        "---\n"
        "snapshot_date: 2026-05-19\n"
        "commit_hash: e3d8700\n"
        "session_arc_scope: B-558 Phase 2.1\n"
        "---\n"
    )
    matches = _SNAPSHOT_COMMIT_HASH_RE.findall(content)
    assert matches == ["e3d8700"]


def test_frontmatter_regex_matches_full_sha() -> None:
    """Assertion 5: regex accepts full 40-char SHA + 7-char short form."""
    content = (
        "commit_hash: abcdef0123456789abcdef0123456789abcdef01\n"
    )
    matches = _SNAPSHOT_COMMIT_HASH_RE.findall(content)
    assert len(matches) == 1
    assert len(matches[0]) == 40


def test_snapshot_with_valid_commit_hash_passes(tmp_path: Path) -> None:
    """Assertion 6: snapshot citing a real git hash → PASS verdict."""
    # Use a known-existing hash from this branch (HEAD) — we mock git_log_contains_hash
    # to avoid coupling to specific commit history.
    snapshot_dir = tmp_path / "docs" / "migration" / "_session_snapshots"
    snapshot_dir.mkdir(parents=True)
    snapshot_file = snapshot_dir / "2026-05-19-abc1234.md"
    snapshot_file.write_text(
        "---\n"
        "snapshot_date: 2026-05-19\n"
        "commit_hash: abc1234\n"
        "session_arc_scope: test\n"
        "---\n",
        encoding="utf-8",
    )
    # Patch git_log_contains_hash to return True (simulating valid hash)
    with patch("tools.pre_commit_checks._git_log_contains_hash", return_value=True), \
         patch("tools.pre_commit_checks.REPO_ROOT", tmp_path):
        result = check_snapshot_claims([
            "docs/migration/_session_snapshots/2026-05-19-abc1234.md",
        ])
    assert result.passed is True
    assert result.severity == "info"
    assert "1 commit_hash claim(s)" in result.diagnostic


def test_snapshot_with_unresolvable_commit_hash_warns(tmp_path: Path) -> None:
    """Assertion 7: snapshot citing a fake/typo hash → WARN with diagnostic."""
    snapshot_dir = tmp_path / "docs" / "migration" / "_session_snapshots"
    snapshot_dir.mkdir(parents=True)
    snapshot_file = snapshot_dir / "2026-05-19-deadbef.md"
    snapshot_file.write_text(
        "---\n"
        "snapshot_date: 2026-05-19\n"
        "commit_hash: deadbef\n"
        "session_arc_scope: hallucinated\n"
        "---\n",
        encoding="utf-8",
    )
    with patch("tools.pre_commit_checks._git_log_contains_hash", return_value=False), \
         patch("tools.pre_commit_checks.REPO_ROOT", tmp_path):
        result = check_snapshot_claims([
            "docs/migration/_session_snapshots/2026-05-19-deadbef.md",
        ])
    assert result.passed is False
    assert result.severity == "warn"
    assert "deadbef" in result.diagnostic
    assert "unresolvable commit_hash" in result.diagnostic


def test_git_log_contains_hash_real_git_smoke() -> None:
    """Assertion 8: _git_log_contains_hash actually queries git (real smoke).

    Verifies the helper is functional against the real repo — picks a known
    pattern that must exist (HEAD's hash) and a known-bogus pattern.
    """
    import subprocess
    # Get current HEAD hash
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        pytest.skip("git not available")
    head_hash = result.stdout.strip()
    assert _git_log_contains_hash(head_hash[:7]) is True
    assert _git_log_contains_hash("ffffff0deadbeef") is False
