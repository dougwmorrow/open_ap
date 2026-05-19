"""Tier 0 build-time smoke tests for `check_file_path_existence` (10th Phase 1 check).

Per D67 — runs at build time + every commit; runtime ceiling < 5 s; no DB / network.

Pins `check_file_path_existence` behavior against silent regression. Authored
2026-05-18 per B-495 closure (LLM file-path-confabulation forward-prevention).

Empirical anchor: udm-researcher artifact `_research/llm-handoffs-traceability-
hallucination-2026-05-18.md` Finding 3.1 (code hallucination systematic review;
arXiv 2511.00776; 60-paper meta-analysis 2025) identifies file-path confabulation
as the LEAST-MITIGATED sub-type in code-generation systems.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from tools.pre_commit_checks import (
    CHECKS,
    _BACKTICK_PATH_RE,
    _is_credible_path_candidate,
    check_file_path_existence,
)


def test_module_imports() -> None:
    """B-495 Assertion 1: function + regex + helper imports cleanly."""
    assert callable(check_file_path_existence)
    assert _BACKTICK_PATH_RE is not None
    assert callable(_is_credible_path_candidate)


def test_check_in_registry_as_10th_check() -> None:
    """B-495 Assertion 2: check registered as 10th in CHECKS registry.

    Pins position to detect silent reordering (existing tests at
    test_pre_commit_checks.py pin `len(CHECKS) == 10` after this commit).
    """
    assert check_file_path_existence in CHECKS
    assert CHECKS[-1] is check_file_path_existence
    assert len(CHECKS) == 10


def test_regex_matches_canonical_path_patterns() -> None:
    """B-495 Assertion 3: regex matches expected canonical paths in real text."""
    text = (
        "See `tools/pre_commit_checks.py` and `.claude/skills/udm-cohort-review/SKILL.md` "
        "and `tests/tier1/test_query_blindspots_checks.py`."
    )
    matches = [m.group(1) for m in _BACKTICK_PATH_RE.finditer(text)]
    assert "tools/pre_commit_checks.py" in matches
    assert ".claude/skills/udm-cohort-review/SKILL.md" in matches
    assert "tests/tier1/test_query_blindspots_checks.py" in matches


def test_credible_path_candidate_filters() -> None:
    """B-495 Assertion 4: _is_credible_path_candidate filter rejects non-paths.

    Per FP-policy: filter out tokens that match the regex but aren't real paths
    (e.g., `polars/series`, `iso/8601` — slashes but no whitelisted prefix).
    """
    # Accept: known prefix + known extension
    assert _is_credible_path_candidate("tools/pre_commit_checks.py")
    assert _is_credible_path_candidate(".claude/skills/foo/SKILL.md")
    assert _is_credible_path_candidate("tests/tier0/test_foo.py")
    # Accept: known prefix + directory (trailing slash)
    assert _is_credible_path_candidate("docs/migration/_session_snapshots/")
    # Reject: no known prefix
    assert not _is_credible_path_candidate("polars/series")
    assert not _is_credible_path_candidate("iso/8601")
    # Reject: known prefix but no known extension and no trailing slash
    assert not _is_credible_path_candidate("tools/somefile")


def test_regex_rejects_wildcards_and_placeholders() -> None:
    """B-495 Assertion 5: regex rejects wildcards (*), template placeholders (<>{}).

    Per FP-policy decision: pattern-citations like `tests/tier*/test_*.py` or
    `docs/migration/_session_snapshots/<YYYY-MM-DD>-*.md` should NOT be flagged
    as missing paths — they are pattern templates, not literal paths.
    """
    text = (
        "Pattern `tests/tier*/test_*.py` and `docs/<YYYY-MM-DD>.md` and "
        "`tools/{module}.py` should be skipped."
    )
    matches = [m.group(1) for m in _BACKTICK_PATH_RE.finditer(text)]
    assert "tests/tier*/test_*.py" not in matches
    assert "docs/<YYYY-MM-DD>.md" not in matches
    assert "tools/{module}.py" not in matches


def test_check_passes_when_all_paths_exist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """B-495 Assertion 6: PASS when all cited paths exist.

    Stages a synthetic markdown citing real repo paths; verifies INFO/PASS result.
    """
    md_file = tmp_path / "synthetic.md"
    md_file.write_text(
        "References `tools/pre_commit_checks.py` and `CLAUDE.md` (root file).",
        encoding="utf-8",
    )
    # Make the synthetic file relative to REPO_ROOT for the check to find it
    from tools import pre_commit_checks
    monkeypatch.setattr(pre_commit_checks, "REPO_ROOT", tmp_path)
    # Touch the cited paths in the temp tree
    (tmp_path / "tools").mkdir()
    (tmp_path / "tools" / "pre_commit_checks.py").touch()
    # Note: CLAUDE.md doesn't have a known prefix so it won't be flagged anyway
    result = check_file_path_existence(["synthetic.md"])
    assert result.passed is True
    assert result.severity == "info"


def test_check_warns_on_missing_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """B-495 Assertion 7: WARN when a cited path does not exist.

    Stages a synthetic markdown citing a non-existent path; verifies WARN result
    with diagnostic mentioning the missing path. CRITICAL: severity = warn (NOT
    block) per FP-policy resolution.
    """
    md_file = tmp_path / "synthetic.md"
    md_file.write_text(
        "References `tools/nonexistent_phantom_file.py` which does not exist.",
        encoding="utf-8",
    )
    from tools import pre_commit_checks
    monkeypatch.setattr(pre_commit_checks, "REPO_ROOT", tmp_path)
    (tmp_path / "tools").mkdir()
    result = check_file_path_existence(["synthetic.md"])
    assert result.passed is False
    assert result.severity == "warn"
    assert "nonexistent_phantom_file.py" in result.diagnostic


def test_no_staged_md_returns_info_skip() -> None:
    """B-495 Assertion 8: no markdown files staged → INFO/PASS skip."""
    result = check_file_path_existence(["tools/somefile.py", "tests/test_x.py"])
    assert result.passed is True
    assert result.severity == "info"
    assert "no staged markdown files" in result.diagnostic.lower()


def test_b496_empirical_anchor_suppression(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """B-496 Assertion 9 (added 2026-05-18 per B-491+B-496 bundled closure):
    check suppresses WARN on missing paths inside empirical-anchor context.

    Per shared `is_empirical_anchor_context` helper from tools/anchor_context.py
    (5-line lookback for canonical anchor markers). Closes the recurring
    false-positive class where check_file_path_existence fires on historical
    path citations in _validation_log.md narrative entries (paths that
    existed/were planned at original authoring but were renamed/moved/never-built
    in subsequent refactors).
    """
    md_file = tmp_path / "synthetic.md"
    md_file.write_text(
        "Per empirical anchor commit `abc123`, the historical pattern fired on "
        "`tools/nonexistent_phantom_file.py` which does not exist anymore.",
        encoding="utf-8",
    )
    from tools import pre_commit_checks
    monkeypatch.setattr(pre_commit_checks, "REPO_ROOT", tmp_path)
    (tmp_path / "tools").mkdir()
    result = check_file_path_existence(["synthetic.md"])
    # Suppression applied — check passes silently despite nonexistent path
    assert result.passed is True, (
        "Empirical-anchor context should suppress WARN per B-496 closure"
    )


def test_b496_no_suppression_outside_anchor_context(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """B-496 Assertion 10 (regression-pin): suppression does NOT apply when no
    empirical-anchor marker is present.

    Prevents over-broad suppression — only historical-context citations
    suppress; current-commit claims still WARN on missing paths.
    """
    md_file = tmp_path / "synthetic.md"
    md_file.write_text(
        "Current-commit claim: `tools/nonexistent_phantom_file.py` does not exist.",
        encoding="utf-8",
    )
    from tools import pre_commit_checks
    monkeypatch.setattr(pre_commit_checks, "REPO_ROOT", tmp_path)
    (tmp_path / "tools").mkdir()
    result = check_file_path_existence(["synthetic.md"])
    # No suppression — WARN should fire
    assert result.passed is False
    assert result.severity == "warn"
    assert "nonexistent_phantom_file.py" in result.diagnostic
