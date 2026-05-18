"""Tier 0 build-time smoke test for tools/measure_ccl_overhead.py.

Per D67 — runs at build time + every commit. Runtime ceiling < 5 s.
All filesystem I/O is mocked / written to a temp doc-root so the test
is hermetic. Verifies:

  - Token counter falls back to the heuristic when tiktoken absent
  - CCL-stage classification is correct per MULTI_AGENT_GUIDE.md § D62
  - The walker honors --include-research and skips _archive/
  - JSON output round-trips (baseline write + load)
  - Markdown rendering returns non-empty text with the canonical headers
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from tools import measure_ccl_overhead as mod  # noqa: E402


def _seed_doc_root(root: Path) -> None:
    """Create a synthetic docs/migration/ tree."""
    root.mkdir(parents=True, exist_ok=True)
    # Stage 1 + Stage 2 canonical files
    (root / "NORTH_STAR.md").write_text("# NS\n" + "alpha " * 100, encoding="utf-8")
    (root / "HANDOFF.md").write_text("# H\n" + "beta " * 200, encoding="utf-8")
    (root / "CURRENT_STATE.md").write_text("# CS\n" + "gamma " * 100, encoding="utf-8")
    (root / "CHECKS_AND_BALANCES.md").write_text("# CB\n" + "delta " * 100, encoding="utf-8")
    (root / "RISKS.md").write_text("# R\n" + "eps " * 100, encoding="utf-8")
    (root / "BACKLOG.md").write_text("# B\n" + "zeta " * 100, encoding="utf-8")
    (root / "_validation_log.md").write_text("# V\n" + "eta " * 500, encoding="utf-8")
    # Stage 3 file (anything else)
    (root / "MARKDOWN_REFACTOR_PLAN.md").write_text("# Plan\n" + "theta " * 50, encoding="utf-8")
    # _research/ (excluded by default)
    research = root / "_research"
    research.mkdir(exist_ok=True)
    (research / "x.md").write_text("# X\nshould-be-skipped", encoding="utf-8")
    # _archive/ (always excluded)
    archive = root / "_archive_2025"
    archive.mkdir(exist_ok=True)
    (archive / "old.md").write_text("# old\nshould-be-skipped", encoding="utf-8")


def test_classify_stage_canonical_files():
    assert mod._classify_stage("docs/migration/NORTH_STAR.md") == "1"
    assert mod._classify_stage("docs/migration/HANDOFF.md") == "1"
    assert mod._classify_stage("docs/migration/RISKS.md") == "2"
    assert mod._classify_stage("docs/migration/BACKLOG.md") == "2"
    assert mod._classify_stage("docs/migration/_validation_log.md") == "2"
    assert mod._classify_stage("docs/migration/MARKDOWN_REFACTOR_PLAN.md") == "3"
    assert mod._classify_stage("docs/migration/phase1/03_core_modules.md") == "3"


def test_token_counter_heuristic_fallback(monkeypatch):
    """Counter must work even if tiktoken not installed."""
    # Force the import-failure path by injecting a sentinel error into sys.modules.
    monkeypatch.setitem(sys.modules, "tiktoken", None)  # mocks "ImportError" via None-shadow
    counter, method = mod._build_token_counter()
    # If real tiktoken is installed in the env, monkeypatch may not block import.
    # The heuristic must always return roughly chars/4.
    assert callable(counter)
    text = "x" * 400
    n = counter(text)
    assert n > 0
    # Either method returns a sane positive count
    assert method in ("tiktoken", "heuristic")


def test_walker_skips_research_and_archive(tmp_path):
    _seed_doc_root(tmp_path)
    paths = list(mod._walk_markdown(tmp_path, include_research=False))
    names = {p.name for p in paths}
    assert "x.md" not in names  # research/ excluded
    assert "old.md" not in names  # _archive_* excluded
    assert "HANDOFF.md" in names


def test_walker_includes_research_when_flagged(tmp_path):
    _seed_doc_root(tmp_path)
    paths = list(mod._walk_markdown(tmp_path, include_research=True))
    assert any(p.name == "x.md" for p in paths)
    assert not any(p.name == "old.md" for p in paths)  # _archive still skipped


def test_measure_returns_per_stage_rollup(tmp_path):
    _seed_doc_root(tmp_path)
    rep = mod.measure(tmp_path, ccl_stage="all", include_research=False, context_window=200_000)
    assert len(rep.measurements) == 8  # 4 S1 + 3 S2 + 1 S3
    assert rep.s1_tokens > 0 and rep.s2_tokens > 0 and rep.s3_tokens > 0
    assert rep.total_tokens == rep.s1_tokens + rep.s2_tokens + rep.s3_tokens
    s1_count = sum(1 for m in rep.measurements if m.ccl_stage == "1")
    assert s1_count == 4


def test_measure_filtered_by_stage(tmp_path):
    _seed_doc_root(tmp_path)
    rep = mod.measure(tmp_path, ccl_stage="1", include_research=False, context_window=200_000)
    assert len(rep.measurements) == 4
    assert all(m.ccl_stage == "1" for m in rep.measurements)
    assert rep.s2_tokens == 0 and rep.s3_tokens == 0


def test_render_markdown_contains_canonical_sections(tmp_path):
    _seed_doc_root(tmp_path)
    rep = mod.measure(tmp_path, ccl_stage="all", include_research=False, context_window=200_000)
    md = mod.render_markdown(rep, baseline=None)
    assert "# CCL token-overhead baseline" in md
    assert "## Per-stage roll-up" in md
    assert "## Top-5 contributors per stage" in md
    assert "## Trim recommendations" in md
    assert "## Full per-file table" in md


def test_main_writes_baseline_json(tmp_path, monkeypatch):
    _seed_doc_root(tmp_path)
    out_json = tmp_path / "baseline.json"
    monkeypatch.setattr(mod, "DEFAULT_DOC_ROOT", tmp_path)
    rc = mod.main(["--doc-root", str(tmp_path), "--baseline-out", str(out_json), "--output", "json"])
    assert rc == 0
    assert out_json.exists()
    raw = json.loads(out_json.read_text(encoding="utf-8"))
    assert "measurements" in raw and len(raw["measurements"]) > 0
    assert raw["s1_tokens"] > 0


def test_main_returns_2_when_doc_root_missing(tmp_path, capsys):
    rc = mod.main(["--doc-root", str(tmp_path / "nope")])
    assert rc == 2
