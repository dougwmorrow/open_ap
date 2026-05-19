"""Tier 0 build-time smoke tests for B-481 closure (wc -l line-count claim
forward-prevention check at tools/pre_commit_checks.py::check_wc_line_count_claims).

Pins regex pattern + canonical-filename resolution + mismatch detection +
graceful-skip semantics per D67 Tier 0 contract.

Empirical anchor: CLAUDE.md L98 cited "127 lines per actual wc -l after B-307
refactor" + "117 lines per actual wc -l per B-307 split" — both stale by
2026-05-18 (actual wc -l = 68 + 41 post-multiple-refactors). Detected by
cross-cohort reviewer aa320fb75f55a5471 §6 + remediated at commit 9e8291a.
B-481 forward-prevention closes the class mechanically.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def test_b481_module_imports():
    """B-481 Assertion 1: check_wc_line_count_claims importable."""
    from tools.pre_commit_checks import check_wc_line_count_claims  # noqa: F401


def test_b481_check_registered_in_checks_registry():
    """B-481 Assertion 2: check_wc_line_count_claims in CHECKS registry
    (9th check; appended after check_cli_registry_sync per B-481 closure;
    position updated to 2nd-to-last after B-495 closure appended
    check_file_path_existence as 10th)."""
    from tools.pre_commit_checks import CHECKS, check_wc_line_count_claims
    assert check_wc_line_count_claims in CHECKS
    # Position is 9th (index -2 after B-495 closure appended 10th check)
    assert CHECKS[-2] is check_wc_line_count_claims, (
        "check_wc_line_count_claims should be 9th (2nd-to-last) in CHECKS "
        "registry per B-481 closure 2026-05-18 + B-495 closure 2026-05-18"
    )


def test_b481_regex_matches_canonical_l98_pattern():
    """B-481 Assertion 3: regex matches the canonical CLAUDE.md L98 pattern
    `<filename>` (Python; N lines per actual `wc -l` ...)."""
    from tools.pre_commit_checks import _WC_LINE_COUNT_CLAIM_RE
    test_content = (
        "`pre-commit` (Python; 68 lines per actual `wc -l` 2026-05-18 ...)\n"
        "`commit-msg` (Python; 41 lines per actual wc -l ...)\n"
    )
    matches = list(_WC_LINE_COUNT_CLAIM_RE.finditer(test_content))
    assert len(matches) == 2
    assert matches[0].group("filename") == "pre-commit"
    assert matches[0].group("count") == "68"
    assert matches[1].group("filename") == "commit-msg"
    assert matches[1].group("count") == "41"


def test_b481_passes_when_claims_match_actual_wc_l():
    """B-481 Assertion 4: check returns PASS (info severity) when staged
    markdown wc -l claims match actual file line counts.

    Uses real CLAUDE.md as canonical-known-good — its L98 claims
    `68 lines` + `41 lines` match real wc -l values for .githooks/pre-commit
    + .githooks/commit-msg (verified empirically 2026-05-18)."""
    from tools.pre_commit_checks import check_wc_line_count_claims
    result = check_wc_line_count_claims(["CLAUDE.md"])
    assert result.passed is True
    assert result.severity == "info"
    assert "match actual line counts" in result.diagnostic


def test_b481_warns_on_mismatch(tmp_path, monkeypatch):
    """B-481 Assertion 5: check returns WARN (warn severity) when a staged
    markdown cites a wc -l line count that does NOT match actual wc -l of
    referenced file. Simulates the empirical 2026-05-18 drift class
    (CLAUDE.md cited 127 lines for pre-commit; actual was 68)."""
    from tools.pre_commit_checks import check_wc_line_count_claims
    # Create temp markdown with deliberately-stale claim
    temp_md = tmp_path / "stale_claim.md"
    temp_md.write_text(
        "Test content.\n"
        "`pre-commit` (Python; 999 lines per actual `wc -l` 2026-05-18 stale)\n",
        encoding="utf-8",
    )
    # Monkeypatch REPO_ROOT temporarily so the check reads our temp file
    # Actually simpler: just use absolute path to staged file
    import tools.pre_commit_checks as pcc
    monkeypatch.setattr(pcc, "REPO_ROOT", tmp_path)
    # Also need .githooks/pre-commit to exist in tmp_path for resolution
    githooks = tmp_path / ".githooks"
    githooks.mkdir()
    (githooks / "pre-commit").write_text("\n".join(["line"] * 68), encoding="utf-8")
    result = check_wc_line_count_claims(["stale_claim.md"])
    assert result.passed is False
    assert result.severity == "warn"
    assert "stale" in result.diagnostic.lower() or "wc -l" in result.diagnostic
    assert "999" in result.diagnostic  # claimed value cited
    assert "B-481" in result.diagnostic


def test_b481_silent_skip_when_filename_not_in_canonical_map(tmp_path, monkeypatch):
    """B-481 Assertion 6: when claim references a filename NOT in the canonical
    map AND not resolvable as a real path, the check silently skips that claim
    (defensive against future claim formats)."""
    from tools.pre_commit_checks import check_wc_line_count_claims
    import tools.pre_commit_checks as pcc
    monkeypatch.setattr(pcc, "REPO_ROOT", tmp_path)
    temp_md = tmp_path / "unknown_file_claim.md"
    temp_md.write_text(
        "`some-unknown-file-xyz` (Python; 100 lines per actual `wc -l` test)\n",
        encoding="utf-8",
    )
    result = check_wc_line_count_claims(["unknown_file_claim.md"])
    # Should PASS — filename not resolvable; silent skip
    assert result.passed is True
    assert result.severity == "info"


def test_b481_skips_check_when_no_markdown_staged():
    """B-481 Assertion 7: check returns INFO (skipped) when no markdown
    files staged (consistent with other pre_commit_checks.py check patterns)."""
    from tools.pre_commit_checks import check_wc_line_count_claims
    result = check_wc_line_count_claims(["tools/some_python_file.py"])
    assert result.passed is True
    assert result.severity == "info"
    assert "skipped" in result.diagnostic.lower() or "no" in result.diagnostic.lower()
