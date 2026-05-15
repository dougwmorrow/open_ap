"""tools/measure_ccl_overhead.py — empirical token-cost baseline for the CCL.

Measures actual token cost per markdown file + per Canonical Context Load (CCL)
stage so that `docs/migration/MARKDOWN_REFACTOR_PLAN.md` can ground its
optimization target empirically (its current "12K-16K lines per CCL invocation"
claim is an estimate, not a measurement).

CCL stages per `MULTI_AGENT_GUIDE.md` § Canonical Context Load (D62):
  Stage 1 — NORTH_STAR / HANDOFF / CURRENT_STATE / CHECKS_AND_BALANCES
  Stage 2 — RISKS / BACKLOG / _validation_log
  Stage 3 — task-specific (everything else)

Usage:
  py tools/measure_ccl_overhead.py
  py tools/measure_ccl_overhead.py --baseline-out _research/ccl-baseline-2026-05-15.json
  py tools/measure_ccl_overhead.py --output json --ccl-stage 1
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DOC_ROOT = REPO_ROOT / "docs" / "migration"

# Canonical CCL Stage 1 + Stage 2 file lists per MULTI_AGENT_GUIDE.md § D62.
STAGE_1_FILES = ("NORTH_STAR.md", "HANDOFF.md", "CURRENT_STATE.md", "CHECKS_AND_BALANCES.md")
STAGE_2_FILES = ("RISKS.md", "BACKLOG.md", "_validation_log.md")

# Anthropic Claude context-window size used to compute the "% of context" column.
# Opus 4.7 1M-context model would use 1_000_000; default to the standard 200K.
DEFAULT_CONTEXT_WINDOW = 200_000

# Plan §9 metric: median CCL Stage 1+2 read budget post-Phase-1.
TARGET_CCL_LINES = 2_000

# Approximate tiktoken-fallback ratio (4 chars/token; conservative for EN prose).
HEURISTIC_CHARS_PER_TOKEN = 4.0


@dataclass
class FileMeasurement:
    path: str
    lines: int
    chars: int
    tokens: int
    ccl_stage: str  # "1" / "2" / "3"


@dataclass
class Report:
    method: str  # "tiktoken" or "heuristic"
    context_window: int
    measurements: list[FileMeasurement] = field(default_factory=list)
    s1_tokens: int = 0
    s2_tokens: int = 0
    s3_tokens: int = 0
    total_tokens: int = 0


def _classify_stage(rel_path: str) -> str:
    name = Path(rel_path).name
    if name in STAGE_1_FILES:
        return "1"
    if name in STAGE_2_FILES:
        return "2"
    return "3"


def _build_token_counter():
    """Return (counter_callable, method_name). Falls back to char-ratio heuristic."""
    try:
        import tiktoken  # type: ignore[import-not-found]
        enc = tiktoken.get_encoding("cl100k_base")
        return (lambda text: len(enc.encode(text)), "tiktoken")
    except Exception:
        return (lambda text: int(round(len(text) / HEURISTIC_CHARS_PER_TOKEN)), "heuristic")


def _walk_markdown(doc_root: Path, include_research: bool) -> Iterable[Path]:
    for p in sorted(doc_root.rglob("*.md")):
        rel_parts = p.relative_to(doc_root).parts
        if any(part.startswith("_archive") for part in rel_parts):
            continue
        if not include_research and "_research" in rel_parts:
            continue
        yield p


def _safe_rel(path: Path) -> str:
    """Best-effort relative path against REPO_ROOT; falls back to absolute when outside."""
    try:
        return str(path.relative_to(REPO_ROOT)).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def measure(doc_root: Path, ccl_stage: str, include_research: bool, context_window: int) -> Report:
    counter, method = _build_token_counter()
    report = Report(method=method, context_window=context_window)
    for path in _walk_markdown(doc_root, include_research):
        rel = _safe_rel(path)
        stage = _classify_stage(rel)
        if ccl_stage != "all" and stage != ccl_stage:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        m = FileMeasurement(path=rel, lines=text.count("\n") + 1, chars=len(text), tokens=counter(text), ccl_stage=stage)
        report.measurements.append(m)
        if stage == "1":
            report.s1_tokens += m.tokens
        elif stage == "2":
            report.s2_tokens += m.tokens
        else:
            report.s3_tokens += m.tokens
        report.total_tokens += m.tokens
    return report


def _format_pct(tokens: int, window: int) -> str:
    return f"{(tokens / window) * 100:.2f}%" if window else "n/a"


def _top_n_by_tokens(measurements: list[FileMeasurement], stage: str, n: int = 5) -> list[FileMeasurement]:
    return sorted([m for m in measurements if m.ccl_stage == stage], key=lambda m: m.tokens, reverse=True)[:n]


def _trim_recommendation(m: FileMeasurement) -> str | None:
    """Return a 'trim to <2000 lines' recommendation if the file exceeds the plan §9 budget."""
    if m.ccl_stage in ("1", "2") and m.lines > TARGET_CCL_LINES:
        excess_pct = ((m.lines - TARGET_CCL_LINES) / m.lines) * 100
        return f"Trim `{m.path}` by {excess_pct:.0f}% ({m.lines} -> {TARGET_CCL_LINES} lines) to hit plan §9 CCL budget"
    return None


def render_markdown(report: Report, baseline: Report | None) -> str:
    out: list[str] = ["# CCL token-overhead baseline", ""]
    method_note = "exact" if report.method == "tiktoken" else "approx ~4 chars/token"
    out += [
        f"- Token method: **{report.method}** ({method_note})",
        f"- Context window assumed: {report.context_window:,} tokens",
        f"- Files measured: {len(report.measurements)}",
        "",
        "## Per-stage roll-up", "",
        "| Stage | Files | Tokens | % of context |", "|---|---:|---:|---:|",
    ]
    for stage_id, label, tokens in (("1", "Stage 1", report.s1_tokens), ("2", "Stage 2", report.s2_tokens), ("3", "Stage 3", report.s3_tokens)):
        n = sum(1 for m in report.measurements if m.ccl_stage == stage_id)
        out.append(f"| {label} | {n} | {tokens:,} | {_format_pct(tokens, report.context_window)} |")
    out.append(f"| **Total** | **{len(report.measurements)}** | **{report.total_tokens:,}** | **{_format_pct(report.total_tokens, report.context_window)}** |")
    ccl_s12 = report.s1_tokens + report.s2_tokens
    out += ["", f"**CCL Stage 1+2 cost**: {ccl_s12:,} tokens ({_format_pct(ccl_s12, report.context_window)} of context window). Plan §9 target: <{TARGET_CCL_LINES:,} lines per invocation.", "", "## Top-5 contributors per stage", ""]
    for stage_id in ("1", "2", "3"):
        top = _top_n_by_tokens(report.measurements, stage_id)
        if not top:
            continue
        out += [f"### Stage {stage_id}", "", "| File | Lines | Chars | Tokens | % of context |", "|---|---:|---:|---:|---:|"]
        out += [f"| `{m.path}` | {m.lines:,} | {m.chars:,} | {m.tokens:,} | {_format_pct(m.tokens, report.context_window)} |" for m in top]
        out.append("")
    out += ["## Trim recommendations (plan §9 metric: <2,000 lines per CCL invocation)", ""]
    recs = [r for r in (_trim_recommendation(m) for m in report.measurements) if r]
    out += [f"- {r}" for r in recs] if recs else ["- No CCL Stage 1+2 file exceeds the 2,000-line budget."]
    out += ["", "## Full per-file table", "", "| File | Stage | Lines | Chars | Tokens | % of context |", "|---|:-:|---:|---:|---:|---:|"]
    out += [f"| `{m.path}` | {m.ccl_stage} | {m.lines:,} | {m.chars:,} | {m.tokens:,} | {_format_pct(m.tokens, report.context_window)} |" for m in sorted(report.measurements, key=lambda x: x.tokens, reverse=True)]
    if baseline is not None:
        delta_total = report.total_tokens - baseline.total_tokens
        delta_ccl = (report.s1_tokens + report.s2_tokens) - (baseline.s1_tokens + baseline.s2_tokens)
        out += ["", "## Diff vs prior baseline", "",
                f"- Total tokens: {baseline.total_tokens:,} -> {report.total_tokens:,} (delta {delta_total:+,})",
                f"- CCL S1+S2 tokens: {baseline.s1_tokens + baseline.s2_tokens:,} -> {report.s1_tokens + report.s2_tokens:,} (delta {delta_ccl:+,})"]
    return "\n".join(out) + "\n"


def _load_baseline(path: Path) -> Report | None:
    if not path.exists():
        return None
    raw = json.loads(path.read_text(encoding="utf-8"))
    return Report(
        method=raw["method"],
        context_window=raw.get("context_window", DEFAULT_CONTEXT_WINDOW),
        measurements=[FileMeasurement(**m) for m in raw["measurements"]],
        s1_tokens=raw["s1_tokens"], s2_tokens=raw["s2_tokens"],
        s3_tokens=raw["s3_tokens"], total_tokens=raw["total_tokens"],
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Measure CCL markdown token overhead.")
    p.add_argument("--doc-root", type=Path, default=DEFAULT_DOC_ROOT)
    p.add_argument("--ccl-stage", choices=("1", "2", "3", "all"), default="all")
    p.add_argument("--output", choices=("markdown", "json"), default="markdown")
    p.add_argument("--baseline-out", type=Path, default=None, help="Write JSON baseline here for future diffing.")
    p.add_argument("--include-research", action="store_true", help="Include _research/ artifacts (excluded by default).")
    p.add_argument("--context-window", type=int, default=DEFAULT_CONTEXT_WINDOW)
    args = p.parse_args(argv)
    if not args.doc_root.exists():
        print(f"ERROR: doc-root does not exist: {args.doc_root}", file=sys.stderr)
        return 2
    baseline = _load_baseline(args.baseline_out) if args.baseline_out else None
    report = measure(args.doc_root, args.ccl_stage, args.include_research, args.context_window)
    if args.baseline_out:
        args.baseline_out.parent.mkdir(parents=True, exist_ok=True)
        args.baseline_out.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")
    # Force UTF-8 stdout so § / em-dash render correctly on Windows consoles.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    if args.output == "json":
        print(json.dumps(asdict(report), indent=2))
    else:
        print(render_markdown(report, baseline))
    return 0


if __name__ == "__main__":
    sys.exit(main())
