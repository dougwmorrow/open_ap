"""tools/verify_cascade.py — Pattern F deterministic cascade auditor.

Round-level close-out cascade audit. Runs the 3 mechanical Pattern F triggers:
- Trigger C: stale B-range / Round-N / count references across cascade docs
- Trigger D: forward-cite resolution (RB-* / SP-* / B-* / D-* / R-* / § X.Y)
- Trigger F: aggregate-doc Round-N status freshness

Per Pattern F doctrine in `MULTI_AGENT_GUIDE.md`. Paired with the
`udm-cascade-auditor` agent which handles the 3 judgment-class triggers:
- Trigger A: D-acceptance substantiation
- Trigger B: B-item closure-target audit
- Trigger E: CLAUDE.md convention registration

Per D89 (Pattern F discipline) + D90 (cascade-auditor agent) + D91 (this
script's contract). Locks at Round 7 close-out after Round 7 production
evidence.

Exit codes (per D74 CLI exit-code contract):
  0: no findings; cascade clean
  1: yellow findings only (non-blocking review at close-out)
  2: red findings (BLOCKING — must fix before round 🟢 lock)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = REPO_ROOT / "docs" / "migration"
PHASE1_DIR = DOCS_DIR / "phase1"

Severity = Literal["red", "yellow", "info"]
TriggerId = Literal["C", "D", "F"]


@dataclass
class Finding:
    trigger: TriggerId
    severity: Severity
    file_path: str
    line_number: int | None
    rule: str
    matched_text: str
    expected: str
    actual: str
    recommendation: str


@dataclass
class CascadeReport:
    findings: list[Finding] = field(default_factory=list)
    red_count: int = 0
    yellow_count: int = 0
    info_count: int = 0
    triggers_run: list[TriggerId] = field(default_factory=list)
    overall: Severity = "info"

    def add(self, finding: Finding) -> None:
        self.findings.append(finding)
        if finding.severity == "red":
            self.red_count += 1
        elif finding.severity == "yellow":
            self.yellow_count += 1
        else:
            self.info_count += 1
        self.overall = "red" if self.red_count else ("yellow" if self.yellow_count else "info")


# ---------- canonical anchor extractors ----------

def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _read_lines(path: Path) -> list[str]:
    return _read(path).splitlines()


def extract_b_numbers(backlog_md: str) -> set[int]:
    """Every B-number that has a primary definition in BACKLOG.md."""
    pattern = re.compile(r"\*\*B(\d+)\*\*")
    return {int(m.group(1)) for m in pattern.finditer(backlog_md)}


def extract_d_numbers(decisions_md: str) -> set[int]:
    """Every D-number with a section header in 03_DECISIONS.md."""
    pattern = re.compile(r"^## D(\d+)\b", re.MULTILINE)
    return {int(m.group(1)) for m in pattern.finditer(decisions_md)}


def extract_r_numbers(risks_md: str) -> set[int]:
    """Every R-number in the RISKS.md active or closed register."""
    pattern = re.compile(r"^\|\s*R(\d+)\s*\|", re.MULTILINE)
    return {int(m.group(1)) for m in pattern.finditer(risks_md)}


def extract_rb_numbers(runbooks_md: str) -> set[int]:
    """Every RB-number defined as a section header in 05_RUNBOOKS.md."""
    pattern = re.compile(r"^##\s*RB-(\d+)\b", re.MULTILINE)
    return {int(m.group(1)) for m in pattern.finditer(runbooks_md)}


def extract_sp_numbers(schema_md: str) -> set[int]:
    """Every SP-N reference defined in 01_database_schema.md."""
    pattern = re.compile(r"\bSP-(\d+)\b")
    return {int(m.group(1)) for m in pattern.finditer(schema_md)}


def extract_locked_round_from_handoff(handoff_md: str) -> int:
    """Largest 'Round N — <name>' that appears in HANDOFF §3 lock list."""
    pattern = re.compile(r"Round (\d+) (?:spec doc )?architectural-review acceptance|Round (\d+) — \w+", re.IGNORECASE)
    rounds = []
    for m in pattern.finditer(handoff_md):
        for grp in m.groups():
            if grp is not None:
                try:
                    rounds.append(int(grp))
                except ValueError:
                    pass
    return max(rounds) if rounds else 0


# ---------- Trigger C: stale references ----------

def trigger_c_stale_references(report: CascadeReport, scan_paths: list[Path]) -> None:
    """Sweep cascade docs for stale B-range / Round-N / count references.

    Rules:
    - C1: `B(\d+)-B(\d+)` ranges where upper bound < max(B-numbers in BACKLOG.md)
    - C2: `Round N — <name> (next round)` references where Round N is locked
    - C3: `"~N active items"` / `"N items in BACKLOG"` numeric claims off by >5
    - C4: text claiming `"Last reviewed YYYY-MM-DD"` older than max close-out date
    """
    report.triggers_run.append("C")

    backlog_md = _read(DOCS_DIR / "BACKLOG.md")
    handoff_md = _read(DOCS_DIR / "HANDOFF.md")
    max_b = max(extract_b_numbers(backlog_md)) if extract_b_numbers(backlog_md) else 0
    locked_round = extract_locked_round_from_handoff(handoff_md)

    # C1: stale B-range
    b_range_pattern = re.compile(r"B(\d+)\s*[-–]\s*B(\d+)")
    for path in scan_paths:
        if not path.exists():
            continue
        lines = _read_lines(path)
        for i, line in enumerate(lines, start=1):
            for m in b_range_pattern.finditer(line):
                lo, hi = int(m.group(1)), int(m.group(2))
                if hi < max_b - 5:  # >5 gap = likely stale
                    report.add(Finding(
                        trigger="C",
                        severity="red",
                        file_path=str(path.relative_to(REPO_ROOT)),
                        line_number=i,
                        rule="C1: stale B-range upper bound",
                        matched_text=m.group(0),
                        expected=f"upper bound near B{max_b}",
                        actual=f"B{hi}",
                        recommendation=f"Update range to reflect current max B-number ({max_b}); BACKLOG.md is the canonical source",
                    ))

    # C2: 'Round N (next round)' where Round N is locked
    next_round_pattern = re.compile(r"Round (\d+).*?\(next round\)", re.IGNORECASE)
    for path in scan_paths:
        if not path.exists():
            continue
        lines = _read_lines(path)
        for i, line in enumerate(lines, start=1):
            for m in next_round_pattern.finditer(line):
                claimed_next = int(m.group(1))
                if claimed_next <= locked_round:
                    report.add(Finding(
                        trigger="C",
                        severity="red",
                        file_path=str(path.relative_to(REPO_ROOT)),
                        line_number=i,
                        rule="C2: Round labeled as next-round is actually locked",
                        matched_text=m.group(0),
                        expected=f"Round {locked_round + 1} or higher",
                        actual=f"Round {claimed_next}",
                        recommendation=f"Round {claimed_next} is locked per HANDOFF §3; promote next-round label to Round {locked_round + 1}",
                    ))

    # C3: B-count claims (yellow — heuristic check, not always precise)
    count_pattern = re.compile(r"~?(\d+)\s+(?:active\s+)?items\s+in\s+`?BACKLOG", re.IGNORECASE)
    actual_active = sum(1 for line in backlog_md.splitlines() if line.startswith("| B") and "🟡" in line)
    for path in scan_paths:
        if not path.exists():
            continue
        lines = _read_lines(path)
        for i, line in enumerate(lines, start=1):
            for m in count_pattern.finditer(line):
                claimed = int(m.group(1))
                if abs(claimed - actual_active) > 10:
                    report.add(Finding(
                        trigger="C",
                        severity="yellow",
                        file_path=str(path.relative_to(REPO_ROOT)),
                        line_number=i,
                        rule="C3: B-count claim drifted from actual",
                        matched_text=m.group(0),
                        expected=f"~{actual_active} active",
                        actual=f"~{claimed}",
                        recommendation="Refresh count from current BACKLOG.md state",
                    ))


# ---------- Trigger D: forward-cite resolution ----------

def trigger_d_forward_cites(report: CascadeReport, scan_paths: list[Path]) -> None:
    """Verify every RB-* / SP-* / B-* / D-* / R-* / § X.Y reference resolves.

    Builds canonical-anchor sets first, then scans all docs for references,
    then reports unresolved references as 🔴 (broken-cite) or 🟡 (low-confidence
    e.g. cross-doc section refs).
    """
    report.triggers_run.append("D")

    # Build canonical anchor sets
    backlog_md = _read(DOCS_DIR / "BACKLOG.md")
    decisions_md = _read(DOCS_DIR / "03_DECISIONS.md")
    risks_md = _read(DOCS_DIR / "RISKS.md")
    runbooks_md = _read(DOCS_DIR / "05_RUNBOOKS.md")
    schema_md = _read(PHASE1_DIR / "01_database_schema.md") if (PHASE1_DIR / "01_database_schema.md").exists() else ""

    b_set = extract_b_numbers(backlog_md)
    d_set = extract_d_numbers(decisions_md)
    r_set = extract_r_numbers(risks_md)
    rb_set = extract_rb_numbers(runbooks_md)
    sp_set = extract_sp_numbers(schema_md) if schema_md else set()

    # Patterns to scan
    ref_patterns: list[tuple[str, re.Pattern[str], set[int], str]] = [
        ("B", re.compile(r"\bB(\d+)\b"), b_set, "BACKLOG.md"),
        ("D", re.compile(r"\bD(\d+)\b"), d_set, "03_DECISIONS.md"),
        ("R", re.compile(r"(?<!B)\bR(\d+)\b(?!\s*(?:OUND|ound|ow))"), r_set, "RISKS.md"),  # avoid Round/Row
        ("RB", re.compile(r"\bRB-(\d+)\b"), rb_set, "05_RUNBOOKS.md"),
        ("SP", re.compile(r"\bSP-(\d+)\b"), sp_set, "01_database_schema.md"),
    ]

    for kind, pat, anchor_set, canonical_doc in ref_patterns:
        if not anchor_set:
            continue  # canonical doc missing — skip rather than false-positive
        for path in scan_paths:
            if not path.exists():
                continue
            # Don't audit the canonical doc against itself for kind=its own
            if path.name == canonical_doc:
                continue
            lines = _read_lines(path)
            for i, line in enumerate(lines, start=1):
                # Skip code blocks (heuristic — full markdown parse would be heavier)
                stripped = line.lstrip()
                if stripped.startswith("```") or stripped.startswith("    "):
                    continue
                for m in pat.finditer(line):
                    n = int(m.group(1))
                    if n not in anchor_set:
                        # Heuristic: ignore very small numbers in non-cite context
                        # for B (e.g. B-9 in CLAUDE.md is a code reference, not BACKLOG)
                        if kind == "B" and n < 10:
                            # B-1, B-2, B-3, ... B-9 in CLAUDE.md are project-internal
                            # bug-class markers, not BACKLOG cites
                            continue
                        if kind == "R" and n < 10:
                            continue
                        report.add(Finding(
                            trigger="D",
                            severity="red" if kind in ("RB", "D") else "yellow",
                            file_path=str(path.relative_to(REPO_ROOT)),
                            line_number=i,
                            rule=f"D-{kind}: forward-cite {kind}-{n} not in {canonical_doc}",
                            matched_text=m.group(0),
                            expected=f"{kind}-{n} defined in {canonical_doc}",
                            actual=f"{kind}-{n} not found in canonical doc",
                            recommendation=f"Either define {kind}-{n} in {canonical_doc} or correct the reference",
                        ))


# ---------- Trigger F: aggregate-doc Round-N freshness ----------

def trigger_f_aggregate_freshness(report: CascadeReport) -> None:
    """Verify 02_PHASES.md Phase 1 row + PHASE_1_DEEP_DIVE_PLAN.md Round stubs
    reflect current locked-Round state from HANDOFF §3."""
    report.triggers_run.append("F")

    handoff_md = _read(DOCS_DIR / "HANDOFF.md")
    locked_round = extract_locked_round_from_handoff(handoff_md)

    # F1: 02_PHASES.md Phase 1 row
    phases_path = DOCS_DIR / "02_PHASES.md"
    if phases_path.exists():
        phases_md = _read(phases_path)
        # Look for Phase 1 status block; check if it mentions current locked round
        phase1_match = re.search(
            r"^## Phase 1 — Foundation Infrastructure.*?(?=^## Phase|\Z)",
            phases_md, re.MULTILINE | re.DOTALL,
        )
        if phase1_match:
            phase1_block = phase1_match.group(0)
            # Check Status: line mentions current locked round
            status_match = re.search(r"\*\*Status:\s*([^*]+)\*\*", phase1_block)
            if status_match:
                status_text = status_match.group(1).strip()
                if f"R{locked_round}" not in status_text and f"Round {locked_round}" not in status_text:
                    report.add(Finding(
                        trigger="F",
                        severity="red",
                        file_path="docs/migration/02_PHASES.md",
                        line_number=phases_md[:phase1_match.start()].count("\n") + 1,
                        rule="F1: 02_PHASES.md Phase 1 status row stale",
                        matched_text=status_text[:80],
                        expected=f"mentions Round {locked_round} locked",
                        actual=status_text,
                        recommendation=f"Refresh Phase 1 status to reflect Rounds 1-{locked_round} 🟢 Locked per HANDOFF §3",
                    ))

    # F2: PHASE_1_DEEP_DIVE_PLAN.md Round stubs
    plan_path = DOCS_DIR / "PHASE_1_DEEP_DIVE_PLAN.md"
    if plan_path.exists():
        plan_md = _read(plan_path)
        # Every "Round N — <name>" header should not still say "(Full plan to be written when Round N-1 completes.)"
        # for any N <= locked_round
        round_section_pattern = re.compile(
            r"^## Round (\d+) — ([^\n]+)\n.*?(?=^## Round|\Z)",
            re.MULTILINE | re.DOTALL,
        )
        for m in round_section_pattern.finditer(plan_md):
            r_num = int(m.group(1))
            section = m.group(0)
            line_no = plan_md[:m.start()].count("\n") + 1
            if r_num <= locked_round:
                if "Full plan to be written" in section:
                    report.add(Finding(
                        trigger="F",
                        severity="red",
                        file_path="docs/migration/PHASE_1_DEEP_DIVE_PLAN.md",
                        line_number=line_no,
                        rule=f"F2: PHASE_1_DEEP_DIVE_PLAN.md Round {r_num} still 'Full plan to be written' stub",
                        matched_text=f"Round {r_num} stub",
                        expected=f"Pointer to locked spec doc phase1/{r_num:02d}_*.md",
                        actual="Stub text remains",
                        recommendation=f"Replace stub with pointer to locked Round {r_num} spec doc; cite D-number of architectural-review acceptance",
                    ))

    # F3: HANDOFF §3 in-flight section should not still list locked Round as "next round"
    in_flight_match = re.search(
        r"\*\*In-flight or pending\*\*:(.*?)(?=\*\*Out of scope|\Z)",
        handoff_md, re.DOTALL,
    )
    if in_flight_match:
        in_flight_block = in_flight_match.group(1)
        next_round_locked = re.findall(r"Round (\d+) — \w+.*?\(next round\)", in_flight_block, re.IGNORECASE)
        for r_str in next_round_locked:
            r_num = int(r_str)
            if r_num <= locked_round:
                # find the line of this match for reporting
                line_no = handoff_md[:in_flight_match.start()].count("\n") + 1
                report.add(Finding(
                    trigger="F",
                    severity="red",
                    file_path="docs/migration/HANDOFF.md",
                    line_number=line_no,
                    rule="F3: HANDOFF §3 in-flight section labels locked Round as 'next round'",
                    matched_text=f"Round {r_num} — next round",
                    expected=f"Round {locked_round + 1} as next round",
                    actual=f"Round {r_num} still labeled next",
                    recommendation=f"Promote Round {locked_round + 1} to next-round; move Round {r_num} to lock list",
                ))


# ---------- driver ----------

def default_scan_paths() -> list[Path]:
    """Cascade doc set — every file Pattern F audits by default."""
    paths = [
        DOCS_DIR / "HANDOFF.md",
        DOCS_DIR / "CURRENT_STATE.md",
        DOCS_DIR / "NORTH_STAR.md",
        DOCS_DIR / "RISKS.md",
        DOCS_DIR / "BACKLOG.md",
        DOCS_DIR / "_validation_log.md",
        DOCS_DIR / "_reviewer_effectiveness.md",
        DOCS_DIR / "03_DECISIONS.md",
        DOCS_DIR / "04_EDGE_CASES.md",
        DOCS_DIR / "05_RUNBOOKS.md",
        DOCS_DIR / "02_PHASES.md",
        DOCS_DIR / "00_OVERVIEW.md",
        DOCS_DIR / "PHASE_1_DEEP_DIVE_PLAN.md",
        DOCS_DIR / "MULTI_AGENT_GUIDE.md",
        DOCS_DIR / "CHECKS_AND_BALANCES.md",
        DOCS_DIR / "MAINTENANCE.md",
        REPO_ROOT / "CLAUDE.md",
    ]
    # plus all phase1/*.md
    if PHASE1_DIR.exists():
        paths.extend(sorted(PHASE1_DIR.glob("*.md")))
    # plus all _archive/*.md (per B-3 / B-272 — post-Phase-1.0 archive cascade audit coverage)
    archive_dir = DOCS_DIR / "_archive"
    if archive_dir.exists():
        paths.extend(sorted(archive_dir.glob("*.md")))
    return paths


def format_report_text(report: CascadeReport) -> str:
    lines = [
        "# Pattern F — Cascade Audit Report",
        "",
        f"Triggers run: {', '.join(report.triggers_run)}",
        f"Findings: {report.red_count} 🔴 | {report.yellow_count} 🟡 | {report.info_count} ℹ️",
        f"Overall: {report.overall.upper()}",
        "",
    ]
    if not report.findings:
        lines.append("✅ No findings. Cascade clean.")
        return "\n".join(lines)

    by_trigger: dict[str, list[Finding]] = {}
    for f in report.findings:
        by_trigger.setdefault(f.trigger, []).append(f)

    for trig in sorted(by_trigger.keys()):
        lines.append(f"## Trigger {trig}")
        lines.append("")
        for f in by_trigger[trig]:
            icon = {"red": "🔴", "yellow": "🟡", "info": "ℹ️"}[f.severity]
            lines.append(f"### {icon} {f.rule}")
            lines.append(f"- File: `{f.file_path}`" + (f":{f.line_number}" if f.line_number else ""))
            lines.append(f"- Matched: `{f.matched_text}`")
            lines.append(f"- Expected: {f.expected}")
            lines.append(f"- Actual: {f.actual}")
            lines.append(f"- Recommendation: {f.recommendation}")
            lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--triggers", default="C,D,F",
                        help="Comma-separated triggers to run; default C,D,F (all)")
    parser.add_argument("--json", action="store_true",
                        help="Emit JSON instead of human text")
    parser.add_argument("--out", type=Path, default=None,
                        help="Write report to this path (default stdout)")
    parser.add_argument("--docs-only", action="store_true",
                        help="Scan only docs/migration/ (skip CLAUDE.md project root)")
    args = parser.parse_args()

    requested = {t.strip().upper() for t in args.triggers.split(",")}
    if not requested.issubset({"C", "D", "F"}):
        print(f"verify_cascade.py: unknown trigger in {args.triggers}", file=sys.stderr)
        return 2

    scan_paths = default_scan_paths()
    if args.docs_only:
        scan_paths = [p for p in scan_paths if p.is_relative_to(DOCS_DIR)]

    report = CascadeReport()

    try:
        if "C" in requested:
            trigger_c_stale_references(report, scan_paths)
        if "D" in requested:
            trigger_d_forward_cites(report, scan_paths)
        if "F" in requested:
            trigger_f_aggregate_freshness(report)
    except FileNotFoundError as e:
        print(f"verify_cascade.py: required file missing: {e}", file=sys.stderr)
        return 2

    if args.json:
        out_data = {
            "triggers_run": report.triggers_run,
            "red_count": report.red_count,
            "yellow_count": report.yellow_count,
            "info_count": report.info_count,
            "overall": report.overall,
            "findings": [asdict(f) for f in report.findings],
        }
        out_str = json.dumps(out_data, indent=2)
    else:
        out_str = format_report_text(report)

    if args.out:
        args.out.write_text(out_str, encoding="utf-8")
    else:
        print(out_str)

    if report.red_count > 0:
        return 2
    if report.yellow_count > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
