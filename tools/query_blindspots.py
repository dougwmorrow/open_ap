#!/usr/bin/env python3
"""Query the UDM blindspot ledger against a candidate artifact / commit / cohort.

Implements the executable form of HANDOFF.md §8 Pitfall #9 sub-classes per
docs/migration/blindspots/ledger.yml. Per D74/D75/D76 CLI contract: exit codes,
dry-run default, audit row.

Surface:
    main, cli_main
    query_blindspots
    Match, QueryReport
    EVENT_TYPE = "CLI_QUERY_BLINDSPOTS"
    EXIT_SUCCESS, EXIT_WARNING, EXIT_OPERATIONAL_FAILURE, EXIT_FATAL
    CHECKS (registry)
    SEVERITY_RANK

Usage:
    python3 tools/query_blindspots.py                       # scan staged files (default)
    python3 tools/query_blindspots.py --file <path>         # scan one file
    python3 tools/query_blindspots.py --commit <hash>       # scan a commit
    python3 tools/query_blindspots.py --since-main          # scan diff since main
    python3 tools/query_blindspots.py --severity p0,p1      # filter by severity
    python3 tools/query_blindspots.py --tag schema,sp-body  # filter by tag
    python3 tools/query_blindspots.py --live                # exit 2 on p0 match
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

EVENT_TYPE = "CLI_QUERY_BLINDSPOTS"
EXIT_SUCCESS = 0
EXIT_WARNING = 1
EXIT_OPERATIONAL_FAILURE = 2
EXIT_FATAL = 3

SEVERITY_RANK = {"p0": 3, "p1": 2, "p2": 1}

REPO_ROOT = Path(__file__).resolve().parent.parent
LEDGER_PATH = REPO_ROOT / "docs" / "migration" / "blindspots" / "ledger.yml"


@dataclass
class Match:
    entry_id: str
    severity: str
    location: str
    snippet: str
    diagnostic: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class QueryReport:
    scanned_files: list[str] = field(default_factory=list)
    entries_checked: int = 0
    matches: list[Match] = field(default_factory=list)
    skipped_checks: list[str] = field(default_factory=list)
    exit_code: int = EXIT_SUCCESS

    def add(self, m: Match) -> None:
        self.matches.append(m)

    def by_severity(self, severity: str) -> list[Match]:
        return [m for m in self.matches if m.severity == severity]

    def to_dict(self) -> dict:
        return {
            "scanned_files": self.scanned_files,
            "entries_checked": self.entries_checked,
            "matches": [m.to_dict() for m in self.matches],
            "skipped_checks": self.skipped_checks,
            "exit_code": self.exit_code,
        }


def _load_ledger(ledger_path: Path = LEDGER_PATH) -> dict:
    """Load ledger.yml. Prefer pyyaml; fall back to minimal parser if unavailable."""
    if not ledger_path.is_file():
        raise FileNotFoundError(f"ledger not found at {ledger_path}")
    text = ledger_path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text)
    except ImportError:
        return _minimal_yaml_parse(text)


def _minimal_yaml_parse(text: str) -> dict:
    """Minimal YAML parser for ledger.yml structure.

    Sufficient for the ledger's specific shape: top-level keys + entries list.
    Does NOT handle full YAML — pyyaml is preferred. Falls back to extracting
    entries via id/severity/tags/agents regex.
    """
    entries = []
    entry_pattern = re.compile(
        r"-\s+id:\s+([0-9a-z][\w-]*)\s*\n"
        r"(?:\s+\w+:\s+.*?\n)*?"
        r"\s+severity:\s+(p[012])\s*\n"
        r"(?:\s+\w+:\s+.*?\n)*?"
        r"\s+agents:\s+\[([^\]]*)\]\s*\n"
        r"(?:\s+\w+:\s+.*?\n)*?"
        r"\s+tags:\s+\[([^\]]*)\]",
        re.MULTILINE,
    )
    for m in entry_pattern.finditer(text):
        entries.append({
            "id": m.group(1),
            "severity": m.group(2),
            "agents": [a.strip() for a in m.group(3).split(",") if a.strip()],
            "tags": [t.strip() for t in m.group(4).split(",") if t.strip()],
        })
    return {"version": 1, "entries": entries}


def _read_text_safe(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _git_show(rev: str, path: str | None = None) -> str:
    args = ["git", "show", rev] if path is None else ["git", "show", f"{rev}:{path}"]
    try:
        result = subprocess.run(args, capture_output=True, text=True, cwd=str(REPO_ROOT))
        if result.returncode == 0:
            return result.stdout
    except (OSError, subprocess.SubprocessError):
        pass
    return ""


def _git_diff_files(base: str, head: str = "HEAD") -> list[str]:
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{base}...{head}"],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
        if result.returncode == 0:
            return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except (OSError, subprocess.SubprocessError):
        pass
    return []


def _git_staged_files() -> list[str]:
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only"],
            capture_output=True, text=True, cwd=str(REPO_ROOT),
        )
        if result.returncode == 0:
            return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except (OSError, subprocess.SubprocessError):
        pass
    return []


# ---------------------------------------------------------------------------
# Check functions — one per ledger entry that has implementable detection_rule.
#
# Each check function signature:
#   def check_<id>(content: str, file_path: str) -> list[Match]
# ---------------------------------------------------------------------------

def check_9j_b_item_status_render(content: str, file_path: str) -> list[Match]:
    """Detect B-item rows with stale leading badge vs canonical inline annotation.

    Per B-295 sub-item 8 (2026-05-16 reviewer recommendation): regex tolerates
    optional hyphen in B-N format (`**B-294**` newer convention vs `**B270**`
    older convention); strikethrough-wrapped lines (`~~**B-N**~~`) are skipped
    as already-rendered-closed entries.
    """
    matches = []
    badge_open_re = re.compile(
        r"\*\*B-?(\d+)\*\*\s*\((?:🟡|🟠|⬜)\s*(?:Open|Noticeable|Deferred)",
        re.IGNORECASE,
    )
    closed_inline_re = re.compile(r"\*\*CLOSED\s+\d{4}-\d{2}-\d{2}\*\*", re.IGNORECASE)
    for lineno, line in enumerate(content.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith("~~") or stripped.startswith("- ~~"):
            continue
        badge = badge_open_re.search(line)
        closed = closed_inline_re.search(line)
        if badge and closed:
            matches.append(Match(
                entry_id="9j-b-item-status-render-discipline",
                severity="p2",
                location=f"{file_path}:{lineno}",
                snippet=line[:120],
                diagnostic=(
                    f"B{badge.group(1)}: leading badge says Open but inline says CLOSED. "
                    "Inline is canonical; flip leading badge."
                ),
            ))
    return matches


def check_9o_recursive_exemption(content: str, file_path: str) -> list[Match]:
    """Detect recursive-exemption rationalization phrases in commit messages.

    Per B-295 sub-item 9 (2026-05-16 reviewer recommendation): scope check to
    commit messages + non-descriptive content. The phrases canonically appear
    in DESCRIPTIVE context within BACKLOG / decisions / handoff docs (documenting
    the pattern as a known anti-pattern) which produced 3 p0 false-positives on
    BACKLOG.md in the tool's first production run. The fix: in docs with item-
    bullet structure (BACKLOG / DECISIONS / HANDOFF / CURRENT_STATE / VALIDATION_LOG
    / POLISH_QUEUE), suppress matches that fall inside a `**B-N**` / `**D-N**` /
    `**R-N**` item-bullet block. Commit messages + other content remain fully
    scanned.
    """
    matches = []
    suspicious_phrases = [
        r"triple-counted review",
        r"recursive[ -]exemption",
        r"Gate 2 covers META",
        r"paired-judgment IS gap-check",
        r"by analogy",
        r"recursive coverage",
    ]
    norm_path = file_path.replace("\\", "/").lower()

    # B-304 closure (2026-05-16): hardcoded allowlist of known trigger-phrase
    # substrate files where phrases appear as STRING DATA in Python list literals
    # / test assertions / SKILL.md trigger-phrase enumeration, NOT as exemption
    # CLAIMS. Closes chicken-and-egg false-positive pattern surfaced at B-301
    # authoring commit `75cdda3` Step 2.1 self-application.
    trigger_phrase_substrate_files = (
        ".githooks/pre-commit",
        ".githooks/commit-msg",
        "tests/tier0/test_pre_commit_hook.py",
        "tests/tier0/test_skill_exemption_verifier.py",
        "tests/tier0/test_exemption_phrases.py",
        "tests/tier0/test_commit_msg_hook.py",
        "tests/tier0/test_cascade_classifier.py",
        "tests/tier0/test_query_blindspots.py",
        "tools/exemption_phrases.py",
        "tools/check_commit_msg.py",
        "tools/cascade_classifier.py",
        # The detector itself contains the suspicious phrases as data (in this
        # allowlist + suspicious_phrases regex list); self-allowlist closes the
        # chicken-and-egg false-positive at detector authoring commits.
        "tools/query_blindspots.py",
        "udm-exemption-verifier/skill.md",
        # CLAUDE.md is the canonical narrative source for the discipline patterns
        # that 9o detects; appearances of these phrases there are descriptive
        # (documenting the anti-pattern) not claims.
        "claude.md",
        # SESSION_RESUME.md is the session-handoff narrative; descriptive
        # discussion of Pitfall #9.o pattern is expected content.
        "session_resume.md",
    )
    if any(substrate in norm_path for substrate in trigger_phrase_substrate_files):
        return matches  # chicken-and-egg false-positive suppression per B-304

    is_descriptive_context_doc = any(
        marker in norm_path for marker in (
            "backlog.md",
            "03_decisions.md",
            "handoff.md",
            "current_state.md",
            "_validation_log.md",
            "polish_queue.md",
            "checks_and_balances.md",
            "north_star.md",
            "claude.md",
            "planning_discipline.md",
            "self_improvement_discipline.md",
            "session_resume.md",
        )
    )
    lines = content.splitlines()
    for lineno, line in enumerate(lines, start=1):
        for phrase_pattern in suspicious_phrases:
            if not re.search(phrase_pattern, line, re.IGNORECASE):
                continue
            if is_descriptive_context_doc and _is_in_item_bullet_block(lines, lineno - 1):
                continue
            if _has_termination_citation(content):
                continue
            matches.append(Match(
                entry_id="9o-recursive-exemption-rationalization",
                severity="p0",
                location=f"{file_path}:{lineno}",
                snippet=line[:120],
                diagnostic=(
                    f"Suspicious phrase '{phrase_pattern}' found without explicit "
                    "termination citation (Layer N+1 + 4-step pre-commit checklist). "
                    "Per CLAUDE.md hard rule 14 anti-rationalization clause."
                ),
            ))
    return matches


def _has_termination_citation(content: str) -> bool:
    """Heuristic: does the content cite Layer N+1 termination + 4-step checklist?"""
    layer_re = re.compile(r"Layer\s+N\s*\+\s*1|recursion[ -]depth", re.IGNORECASE)
    checklist_re = re.compile(r"4[ -]step|pre[ -]commit\s+verification", re.IGNORECASE)
    return bool(layer_re.search(content) and checklist_re.search(content))


def _is_in_item_bullet_block(lines: list[str], idx: int, lookback: int = 40) -> bool:
    """Detect whether line at `idx` is inside a `**B-N**` / `**D-N**` / `**R-N**`
    / `**P-N**` item-bullet block.

    Walks backward from idx looking for an item-bullet marker that begins a
    bulleted entry. Stops at section boundary (markdown heading at column 0).
    Returns True if a marker is found before a section boundary.
    """
    item_marker_re = re.compile(
        r"^\s*-\s+(?:~~)?\*\*[BDRP]-?\d+\*\*", re.IGNORECASE,
    )
    heading_re = re.compile(r"^#{1,6}\s+", re.MULTILINE)
    for back in range(min(idx + 1, lookback)):
        check_idx = idx - back
        if check_idx < 0:
            break
        check_line = lines[check_idx]
        if item_marker_re.search(check_line):
            return True
        if heading_re.match(check_line):
            return False
    return False


_CLAUDE_MD_CACHE: str | None = None
_GLOSSARY_MD_CACHE: str | None = None


def _claude_md_content() -> str:
    """Cache-read CLAUDE.md to avoid repeat reads when scanning multiple files."""
    global _CLAUDE_MD_CACHE
    if _CLAUDE_MD_CACHE is None:
        claude_path = Path(__file__).resolve().parent.parent / "CLAUDE.md"
        try:
            _CLAUDE_MD_CACHE = claude_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            _CLAUDE_MD_CACHE = ""
    return _CLAUDE_MD_CACHE


def _glossary_md_content() -> str:
    """Cache-read GLOSSARY.md to avoid repeat reads (per 2026-05-17 9n
    extension: GLOSSARY parity check in addition to CLAUDE.md Structure)."""
    global _GLOSSARY_MD_CACHE
    if _GLOSSARY_MD_CACHE is None:
        glossary_path = (
            Path(__file__).resolve().parent.parent / "docs" / "migration" / "GLOSSARY.md"
        )
        try:
            _GLOSSARY_MD_CACHE = glossary_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            _GLOSSARY_MD_CACHE = ""
    return _GLOSSARY_MD_CACHE


def check_9n_convention_registration(content: str, file_path: str) -> list[Match]:
    """Detect new public surface in source files missing from CLAUDE.md Structure.

    Only fires when scanning a Python source file under tools/ data_load/ cdc/
    scd2/ orchestration/ schema/ extract/.

    Per 2026-05-16 false-positive fix: NOW reads CLAUDE.md and suppresses the
    match if the file's basename appears in the file (proxy for Structure-row
    registration). Was REMINDER-only previously (always fired); produced
    false-positive p1 BLOCKS on commits that had ALREADY registered the file.
    """
    matches = []
    source_dirs = ("tools/", "data_load/", "cdc/", "scd2/", "orchestration/",
                   "schema/", "extract/", "observability/", "utils/", "migrations/")
    norm = file_path.replace("\\", "/")
    if not any(norm.startswith(d) or f"/{d}" in norm for d in source_dirs):
        return matches
    if not norm.endswith(".py"):
        return matches
    if "/tests/" in norm or norm.startswith("tests/"):
        return matches

    public_def_re = re.compile(r"^def\s+([a-z][a-z0-9_]*)\s*\(", re.MULTILINE)
    public_class_re = re.compile(r"^class\s+([A-Z][A-Za-z0-9_]*)\s*[\(:]", re.MULTILINE)
    public_const_re = re.compile(r"^([A-Z][A-Z0-9_]+)\s*=\s*", re.MULTILINE)

    surfaces = []
    for m in public_def_re.finditer(content):
        name = m.group(1)
        if not name.startswith("_"):
            surfaces.append(("function", name))
    for m in public_class_re.finditer(content):
        surfaces.append(("class", m.group(1)))
    for m in public_const_re.finditer(content):
        surfaces.append(("constant", m.group(1)))

    if not surfaces:
        return matches

    # Suppress if BOTH CLAUDE.md AND GLOSSARY.md already reference this file
    # (per 2026-05-17 extension after recent gap-check finding: GLOSSARY parity
    # gap for 3 new B-317 tools went undetected by the prior CLAUDE.md-only
    # check; GLOSSARY entries are required per Step 10 + Pitfall #9.n).
    # Soft check — basename substring match — could miss content-changed-but-
    # name-same edits but eliminates the dominant false-positive class.
    #
    # Per 2026-05-17 reviewer feedback (avoid false-positive cascade): trivial
    # wrapper scripts with only `main`/`cli_main` public surface DON'T warrant
    # GLOSSARY entries (15+ existing operator-helper tools would false-positive
    # without this). Only require GLOSSARY parity when NON-TRIVIAL public
    # surface count >= GLOSSARY_PARITY_SURFACE_THRESHOLD.
    basename = Path(file_path).name
    if not basename:
        return matches
    claude_content = _claude_md_content()
    glossary_content = _glossary_md_content()
    in_claude = basename in claude_content
    in_glossary = basename in glossary_content

    # Filter trivial wrapper surfaces for GLOSSARY-requirement threshold
    trivial_names = frozenset(("main", "cli_main"))
    non_trivial_surfaces = [
        (t, n) for t, n in surfaces if n not in trivial_names
    ]
    glossary_required = len(non_trivial_surfaces) >= 3

    if in_claude and (in_glossary or not glossary_required):
        # CLAUDE.md present + either GLOSSARY present OR not required → compliant
        return matches

    # Determine specific gap for diagnostic
    if not in_claude:
        if glossary_required and not in_glossary:
            gap = f"NEITHER CLAUDE.md NOR GLOSSARY.md references `{basename}`"
        else:
            gap = f"CLAUDE.md has NO Structure row for `{basename}`"
    else:
        # in_claude True; gap must be in_glossary False with glossary_required True
        gap = (
            f"CLAUDE.md has Structure row but GLOSSARY.md has NO entries "
            f"({len(non_trivial_surfaces)} non-trivial surfaces ≥ threshold 3)"
        )

    surface_names = ", ".join(f"{n} ({t})" for t, n in surfaces[:10])
    matches.append(Match(
        entry_id="9n-convention-registration-not-applied-to-new-build-artifacts",
        severity="p1",
        location=file_path,
        snippet=surface_names,
        diagnostic=(
            f"File has {len(surfaces)} public surface element(s) "
            f"({len(non_trivial_surfaces)} non-trivial beyond main/cli_main); {gap}. "
            "Add row in CLAUDE.md Structure section "
            + ("AND public-surface entries in GLOSSARY.md " if glossary_required else "")
            + "(Per Step 10 / Pitfall #9.n; extended 2026-05-17 with surface-"
            "count threshold + GLOSSARY parity check after empirical gap-check "
            "finding on 3 B-317 tools)."
        ),
    ))
    return matches


def check_9h_off_by_n_line_citation(content: str, file_path: str) -> list[Match]:
    """Detect L-range citations that may be off-by-N.

    Conservative: only surfaces if cited L-range has format ``L\\d+-L\\d+``
    AND target file is referenceable. Does NOT verify the actual content
    match (too expensive); just flags the pattern for human review.
    """
    matches = []
    citation_re = re.compile(r"L(\d+)[-–—]L?(\d+)")
    skip_diagnostic = (
        "Citation found; verify range fully contains the cited canonical "
        "content. Off-by-1 / off-by-N drift is a common 9.h subclass."
    )
    for lineno, line in enumerate(content.splitlines(), start=1):
        for cit in citation_re.finditer(line):
            start, end = int(cit.group(1)), int(cit.group(2))
            if end - start > 100 or end < start:
                matches.append(Match(
                    entry_id="9h-wrong-section-number-invented-description",
                    severity="p2",
                    location=f"{file_path}:{lineno}",
                    snippet=line[:120],
                    diagnostic=skip_diagnostic + f" (range L{start}-L{end} flagged for review)",
                ))
    return matches


# Registry: entry_id -> check function
CHECKS: dict[str, Callable[[str, str], list[Match]]] = {
    "9j-b-item-status-render-discipline": check_9j_b_item_status_render,
    "9o-recursive-exemption-rationalization": check_9o_recursive_exemption,
    "9n-convention-registration-not-applied-to-new-build-artifacts": check_9n_convention_registration,
    "9h-wrong-section-number-invented-description": check_9h_off_by_n_line_citation,
    # 9.a-9.g (canonical-source-drift) require schema parsing — Phase 2 work
    # 9.i, 9.k, 9.l, 9.m require multi-doc cross-reference — Phase 2 work
}


def query_blindspots(
    *,
    files: Iterable[str] | None = None,
    commit: str | None = None,
    since_main: bool = False,
    severity_filter: list[str] | None = None,
    tag_filter: list[str] | None = None,
    class_filter: list[str] | None = None,
    agent_filter: list[str] | None = None,
    live: bool = False,
    ledger_path: Path = LEDGER_PATH,
) -> QueryReport:
    """Run blindspot ledger queries against the specified scope.

    Returns a QueryReport with matches + exit_code.
    """
    report = QueryReport()
    try:
        ledger = _load_ledger(ledger_path)
    except FileNotFoundError as e:
        report.exit_code = EXIT_FATAL
        report.skipped_checks.append(str(e))
        return report

    ledger_entries = {e["id"]: e for e in ledger.get("entries", [])}
    report.entries_checked = len(ledger_entries)

    if commit is not None:
        commit_content = _git_show(commit)
        scopes = [("<commit-message-and-diff>", commit_content)]
    elif since_main:
        diff_files = _git_diff_files("main")
        scopes = [(f, _read_text_safe(f)) for f in diff_files if f]
    elif files is not None:
        # Explicit files (possibly empty list); do NOT fall back to staged
        scopes = [(f, _read_text_safe(f)) for f in files]
    else:
        staged = _git_staged_files()
        scopes = [(f, _read_text_safe(f)) for f in staged] if staged else []

    report.scanned_files = [s[0] for s in scopes]

    for entry_id, entry in ledger_entries.items():
        if severity_filter and entry.get("severity") not in severity_filter:
            continue
        if tag_filter:
            entry_tags = set(entry.get("tags", []))
            if not entry_tags.intersection(tag_filter):
                continue
        if class_filter and entry.get("class") not in class_filter:
            continue
        if agent_filter:
            entry_agents = set(entry.get("agents", []))
            if not entry_agents.intersection(agent_filter):
                continue
        check_fn = CHECKS.get(entry_id)
        if check_fn is None:
            report.skipped_checks.append(entry_id)
            continue
        for file_path, content in scopes:
            if not content:
                continue
            try:
                for match in check_fn(content, file_path):
                    report.add(match)
            except Exception as exc:
                report.skipped_checks.append(f"{entry_id}: {exc}")

    has_p0 = bool(report.by_severity("p0"))
    has_p1 = bool(report.by_severity("p1"))
    has_p2 = bool(report.by_severity("p2"))
    if live and has_p0:
        report.exit_code = EXIT_OPERATIONAL_FAILURE
    elif has_p0 or has_p1 or has_p2:
        report.exit_code = EXIT_WARNING
    else:
        report.exit_code = EXIT_SUCCESS
    return report


def _emit_audit_row(report: QueryReport, args: argparse.Namespace) -> None:
    """Write audit row to session log (DB unavailable on dev workstation)."""
    audit_dir = REPO_ROOT / "_session_logs"
    audit_dir.mkdir(exist_ok=True)
    log_path = audit_dir / f"cli_query_blindspots_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.log"
    payload = {
        "event_type": EVENT_TYPE,
        "ts": datetime.now(timezone.utc).isoformat(),
        "args": {k: v for k, v in vars(args).items() if k != "func"},
        "ledger_version": 1,
        "ledger_entries_checked": report.entries_checked,
        "matches": [m.to_dict() for m in report.matches],
        "exit_code": report.exit_code,
        "skipped_checks": report.skipped_checks,
    }
    try:
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload) + "\n")
    except OSError:
        pass


def _safe_print(s: str) -> None:
    """Print with Windows-safe fallback (cp1252 stdout can't encode emoji)."""
    try:
        print(s)
    except UnicodeEncodeError:
        sys.stdout.buffer.write((s + "\n").encode("utf-8", errors="replace"))
        sys.stdout.flush()


def _print_report(report: QueryReport, json_output: bool) -> None:
    if json_output:
        _safe_print(json.dumps(report.to_dict(), indent=2))
        return
    _safe_print(f"Scanned: {len(report.scanned_files)} file(s); checked {report.entries_checked} ledger entries.")
    if report.skipped_checks:
        _safe_print(f"Skipped checks ({len(report.skipped_checks)}): {', '.join(report.skipped_checks)}")
    if not report.matches:
        _safe_print("No matches.")
        return
    _safe_print(f"\nMatches ({len(report.matches)}):\n")
    for severity in ("p0", "p1", "p2"):
        sev_matches = report.by_severity(severity)
        if not sev_matches:
            continue
        _safe_print(f"  [{severity.upper()}] {len(sev_matches)} match(es):")
        for m in sev_matches:
            _safe_print(f"    - {m.entry_id}")
            _safe_print(f"      Location: {m.location}")
            _safe_print(f"      Snippet:  {m.snippet}")
            _safe_print(f"      Diagnostic: {m.diagnostic}\n")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Query the UDM blindspot ledger against candidate artifacts.",
    )
    src = parser.add_mutually_exclusive_group()
    src.add_argument("--file", action="append", dest="files", help="Scan specific file(s).")
    src.add_argument("--commit", help="Scan a commit hash.")
    src.add_argument("--since-main", action="store_true", help="Scan diff since main branch.")
    parser.add_argument("--severity", help="Comma-separated severity filter (p0,p1,p2).")
    parser.add_argument("--tag", help="Comma-separated tag filter.")
    parser.add_argument("--class", dest="cls", help="Comma-separated class filter.")
    parser.add_argument("--agent", help="Comma-separated agent filter.")
    parser.add_argument("--live", action="store_true", help="Exit 2 on p0 match (blocks pre-commit).")
    parser.add_argument("--dry-run", action="store_true", default=True,
                       help="Report matches but do not block (default).")
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    parser.add_argument("--ledger", default=str(LEDGER_PATH), help="Override ledger path.")
    parser.add_argument("--no-audit", action="store_true", help="Skip audit-row write.")
    return parser.parse_args(argv)


def cli_main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    severity_filter = [s.strip() for s in args.severity.split(",")] if args.severity else None
    tag_filter = [t.strip() for t in args.tag.split(",")] if args.tag else None
    class_filter = [c.strip() for c in args.cls.split(",")] if args.cls else None
    agent_filter = [a.strip() for a in args.agent.split(",")] if args.agent else None
    try:
        report = query_blindspots(
            files=args.files,
            commit=args.commit,
            since_main=args.since_main,
            severity_filter=severity_filter,
            tag_filter=tag_filter,
            class_filter=class_filter,
            agent_filter=agent_filter,
            live=args.live,
            ledger_path=Path(args.ledger),
        )
    except Exception as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return EXIT_FATAL
    _print_report(report, args.json)
    if not args.no_audit:
        _emit_audit_row(report, args)
    return report.exit_code


def main() -> None:
    sys.exit(cli_main())


if __name__ == "__main__":
    main()
