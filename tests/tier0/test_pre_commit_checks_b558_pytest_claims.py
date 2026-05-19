"""Tier 0 smoke tests for `check_snapshot_pytest_claims` per B-558 Phase 2.1 Component C.

Per D67 — runs at build time + every commit; runtime ceiling < 5 s.
Pins pytest-claim-scope-ambiguity forward-prevention at snapshot scope.

Plan reference: `docs/migration/UDM_SESSION_COMPACTOR_PHASE_2_1_PLAN_2026-05-19.md` §3.3 (Option B).
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from tools.pre_commit_checks import (
    CHECKS,
    CheckResult,
    check_snapshot_pytest_claims,
)


def test_module_imports_and_check_registered() -> None:
    """Assertion 1: check_snapshot_pytest_claims importable + registered in CHECKS."""
    assert callable(check_snapshot_pytest_claims)
    assert check_snapshot_pytest_claims in CHECKS
    # Was CHECKS[-1] at Component C landing; now at CHECKS[-2] after B-565
    # appended at B-565 closure 2026-05-19 — pins by membership not position-tail
    # since future checks will continue to append
    assert CHECKS.index(check_snapshot_pytest_claims) >= 0


def test_no_staged_snapshot_files_returns_info() -> None:
    """Assertion 2: empty staged-files list returns INFO (skip)."""
    result = check_snapshot_pytest_claims([])
    assert isinstance(result, CheckResult)
    assert result.passed is True
    assert result.severity == "info"
    assert "no staged snapshot files" in result.diagnostic


def test_pytest_claim_with_scope_indicator_passes(tmp_path: Path) -> None:
    """Assertion 3: pytest claim with co-located scope indicator → PASS."""
    snapshot_dir = tmp_path / "docs" / "migration" / "_session_snapshots"
    snapshot_dir.mkdir(parents=True)
    snapshot_file = snapshot_dir / "2026-05-19-abc1234.md"
    snapshot_file.write_text(
        "---\n"
        "snapshot_date: 2026-05-19\n"
        "commit_hash: abc1234\n"
        "---\n"
        "\n"
        "## §1 Active work context\n"
        "\n"
        "Latest pytest tier0+tier1 baseline: 2471 pass / 10 skip / 0 fail.\n",
        encoding="utf-8",
    )
    with patch("tools.pre_commit_checks.REPO_ROOT", tmp_path):
        result = check_snapshot_pytest_claims([
            "docs/migration/_session_snapshots/2026-05-19-abc1234.md",
        ])
    assert result.passed is True
    assert result.severity == "info"


def test_unscoped_pytest_claim_warns(tmp_path: Path) -> None:
    """Assertion 4: pytest claim WITHOUT scope indicator → WARN."""
    snapshot_dir = tmp_path / "docs" / "migration" / "_session_snapshots"
    snapshot_dir.mkdir(parents=True)
    snapshot_file = snapshot_dir / "2026-05-19-def5678.md"
    snapshot_file.write_text(
        "---\n"
        "snapshot_date: 2026-05-19\n"
        "commit_hash: def5678\n"
        "---\n"
        "\n"
        "## §1 Active work context\n"
        "\n"
        "Pytest result: 2471 pass.\n",  # no scope indicator
        encoding="utf-8",
    )
    with patch("tools.pre_commit_checks.REPO_ROOT", tmp_path):
        result = check_snapshot_pytest_claims([
            "docs/migration/_session_snapshots/2026-05-19-def5678.md",
        ])
    assert result.passed is False
    assert result.severity == "warn"
    assert "without co-located scope indicator" in result.diagnostic
