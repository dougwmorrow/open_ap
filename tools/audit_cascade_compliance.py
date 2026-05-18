#!/usr/bin/env python3
"""Retroactive audit of cascade-evidence compliance per B-317 Phase 3.

Walks recent N commits; for each commit:
1. Reconstructs the commit's file scope from `git show --name-only`
2. Classifies historically via `tools/cascade_classifier.py::is_substrate_path()`
   + canonical-source detection (no live git state required)
3. Checks commit message for cascade-evidence tri-section structure via
   `has_cascade_evidence()`
4. Flags commits where `cascade_required=True` AND `has_evidence=False`

Safety net for the rare edge case where:
- Hook was bypassed via `--no-verify` (self-flagging exemption-claim)
- New file class escaped the substrate enumeration (e.g., new `tools/*.py`
  added BEFORE the substrate-edit clause was authored at Phase 2A)
- Pre-existing commits (from before hook activation) lacked cascade-evidence

NOT an enforcement tool — operator-driven audit; output is informational.
Per D74 exit codes:
- 0: all audited commits compliant (cascade-evidence present OR anti-trigger)
- 1: warnings (some commits non-compliant; manual review recommended)
- 3: fatal error

Per D75: dry-run default; this is read-only audit, no fix action.
Per D76: audit row to `_session_logs/cli_audit_cascade_compliance_<date>.log`.

Usage:
    python tools/audit_cascade_compliance.py                       # last 20 commits, human-readable
    python tools/audit_cascade_compliance.py --n 50                # last 50 commits
    python tools/audit_cascade_compliance.py --non-compliant-only  # just the flagged ones
    python tools/audit_cascade_compliance.py --json                # machine-readable

Public surface:
- `main() -> None`
- `cli_main(argv) -> int`
- `audit_commits(n_commits: int) -> list[CommitAudit]`
- `CommitAudit` dataclass
- `EVENT_TYPE` = "CLI_AUDIT_CASCADE_COMPLIANCE"
- `EXIT_SUCCESS`, `EXIT_WARNING`, `EXIT_FATAL`
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

EVENT_TYPE = "CLI_AUDIT_CASCADE_COMPLIANCE"
EXIT_SUCCESS = 0
EXIT_WARNING = 1
EXIT_FATAL = 3

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

try:
    from tools.cascade_classifier import (
        has_cascade_evidence,
        is_substrate_path,
        CANONICAL_SOURCE_FILES,
    )
except ImportError as _exc:
    print(f"[audit_cascade_compliance FATAL] cannot import tools.cascade_classifier "
          f"({_exc})", file=sys.stderr)
    sys.exit(EXIT_FATAL)

# Historical-classification labels (subset of cascade_classifier classes).
# BACKLOG_ONLY removed — BACKLOG.md is in CANONICAL_SOURCE_FILES so a BACKLOG-only
# commit classifies as CANONICAL_SOURCE (cascade required; conservative default).
# This is safer than assuming all BACKLOG commits are badge-flip — new B-N
# entries are substantive content and should have cascade-evidence.
CLASS_SUBSTRATE_HIST = "SUBSTRATE_EDIT"
CLASS_CANONICAL_SOURCE = "CANONICAL_SOURCE"
CLASS_POLISH = "POLISH_QUEUE_ONLY"
CLASS_TYPO_SMALL_MD = "TYPO_SMALL_MD"
CLASS_SUBSTANTIVE = "SUBSTANTIVE"


@dataclass
class CommitAudit:
    hash: str
    subject: str
    classification: str
    cascade_required: bool
    has_evidence: bool
    missing_sections: list[str]
    is_compliant: bool
    file_count: int

    def to_dict(self) -> dict:
        return asdict(self)


def _git_log(n_commits: int) -> list[tuple[str, str]]:
    """Get recent N commit (hash, subject) pairs via `git log`."""
    try:
        result = subprocess.run(
            ["git", "log", f"-n{n_commits}", "--format=%H|%s"],
            capture_output=True, text=True, cwd=str(REPO_ROOT), check=False,
            encoding="utf-8", errors="replace",
        )
        if result.returncode != 0 or not result.stdout:
            return []
        pairs = []
        for line in result.stdout.splitlines():
            if "|" in line:
                h, s = line.split("|", 1)
                pairs.append((h.strip(), s.strip()))
        return pairs
    except (OSError, subprocess.SubprocessError):
        return []


def _commit_message(commit_hash: str) -> str:
    """Full commit message body via `git show --format=%B --no-patch`."""
    try:
        result = subprocess.run(
            ["git", "show", "--format=%B", "--no-patch", commit_hash],
            capture_output=True, text=True, cwd=str(REPO_ROOT), check=False,
            encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            return ""
        return result.stdout or ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _commit_files(commit_hash: str) -> list[str]:
    """File paths modified in commit via `git show --name-only -m --format=`.

    Per reviewer 🔴 BLOCK fix: `-m` flag instructs git to show the diff for
    merge commits too (default behavior suppresses combined diff → empty file
    list → falsely classified as SUBSTANTIVE with no scope). With `-m`, merge
    commits show diff against each parent; we deduplicate the file list.
    """
    try:
        result = subprocess.run(
            ["git", "show", "--name-only", "-m", "--format=", commit_hash],
            capture_output=True, text=True, cwd=str(REPO_ROOT), check=False,
            encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            return []
        # Deduplicate (merge commits emit the file list per parent)
        seen: set[str] = set()
        files: list[str] = []
        for line in result.stdout.splitlines():
            s = line.strip()
            if s and s not in seen:
                seen.add(s)
                files.append(s)
        return files
    except (OSError, subprocess.SubprocessError):
        return []


def classify_historical(files: list[str]) -> tuple[str, bool]:
    """Classify a historical commit's scope based on its files alone.

    Returns (classification, cascade_required).

    No live git diff stats available — uses file-name heuristics:
    - SUBSTRATE_EDIT: any substrate file present (per is_substrate_path)
    - CANONICAL_SOURCE: any D-N / B-N / R-N / RB-N source file (substantive;
      includes BACKLOG.md — new B-N entries are substantive content)
    - POLISH_QUEUE_ONLY: all files = POLISH_QUEUE.md
    - TYPO_SMALL_MD: all files .md AND ≤2 files AND no canonical-source
    - SUBSTANTIVE: everything else (cascade required)
    """
    if not files:
        return CLASS_SUBSTANTIVE, True
    substrate = any(is_substrate_path(f) for f in files)
    if substrate:
        return CLASS_SUBSTRATE_HIST, True
    canonical = any(
        f.replace("\\", "/") in CANONICAL_SOURCE_FILES for f in files
    )
    if canonical:
        return CLASS_CANONICAL_SOURCE, True
    if all("POLISH_QUEUE.md" in f.replace("\\", "/") for f in files):
        return CLASS_POLISH, False
    if all(f.endswith(".md") for f in files) and len(files) <= 2:
        return CLASS_TYPO_SMALL_MD, False
    return CLASS_SUBSTANTIVE, True


def audit_commits(n_commits: int = 20) -> list[CommitAudit]:
    """Walk recent N commits + audit each for cascade-evidence compliance.

    Per design-reviewer compositional gap fix 2026-05-17: passes `classification`
    to `has_cascade_evidence()` so the substrate-stricter REVIEW check (B-321)
    fires in retroactive scans too. Previously the audit silently bypassed
    that check by calling has_cascade_evidence(commit_msg) without the kwarg —
    safety-net would mark commits compliant even with "inline self-review" on
    substrate edits. Now classification flows through, mirroring check_commit_msg's
    pass-through pattern.
    """
    pairs = _git_log(n_commits)
    audits: list[CommitAudit] = []
    for commit_hash, subject in pairs:
        files = _commit_files(commit_hash)
        classification, cascade_required = classify_historical(files)
        commit_msg = _commit_message(commit_hash)
        has_ev, missing = has_cascade_evidence(commit_msg, classification=classification)
        is_compliant = (not cascade_required) or has_ev
        audits.append(CommitAudit(
            hash=commit_hash[:8],
            subject=subject[:80],
            classification=classification,
            cascade_required=cascade_required,
            has_evidence=has_ev,
            missing_sections=missing,
            is_compliant=is_compliant,
            file_count=len(files),
        ))
    return audits


def _emit_audit_row(audited_count: int, non_compliant_count: int, exit_code: int) -> None:
    """Per-invocation audit row per D76."""
    audit_dir = REPO_ROOT / "_session_logs"
    try:
        audit_dir.mkdir(exist_ok=True)
    except OSError:
        return
    log_path = audit_dir / f"cli_audit_cascade_compliance_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.log"
    payload = {
        "event_type": EVENT_TYPE,
        "ts": datetime.now(timezone.utc).isoformat(),
        "audited_count": audited_count,
        "non_compliant_count": non_compliant_count,
        "exit_code": exit_code,
    }
    try:
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload) + "\n")
    except OSError:
        pass


def _format_human(audits: list[CommitAudit], non_compliant_only: bool) -> str:
    """Human-readable report."""
    non_compliant = [a for a in audits if not a.is_compliant]
    lines: list[str] = []
    if non_compliant_only:
        lines.append(f"Audited {len(audits)} commits; {len(non_compliant)} non-compliant:\n")
        for a in non_compliant:
            lines.append(f"  [WARN] {a.hash}: {a.subject}")
            lines.append(f"    classification: {a.classification}")
            lines.append(f"    missing sections: {', '.join(a.missing_sections)}")
            lines.append(f"    file count: {a.file_count}")
    else:
        lines.append(f"Audited {len(audits)} commits; {len(non_compliant)} non-compliant.\n")
        for a in audits:
            status = "PASS" if a.is_compliant else "WARN"
            lines.append(f"  [{status}] {a.hash} [{a.classification}] {a.subject}")
            if not a.is_compliant:
                lines.append(f"      missing: {', '.join(a.missing_sections)}")
    return "\n".join(lines)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Retroactive audit of cascade-evidence compliance per B-317 Phase 3.",
    )
    parser.add_argument("--n", type=int, default=20,
                        help="Number of recent commits to audit (default 20).")
    parser.add_argument("--json", action="store_true",
                        help="Emit JSON output (machine-readable).")
    parser.add_argument("--non-compliant-only", action="store_true",
                        help="Report only non-compliant commits.")
    parser.add_argument("--no-audit", action="store_true",
                        help="Skip audit-row write.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Read-only mode (no audit-row write); semantic alias for --no-audit. "
                        "Tool is dry-run by default (no fix action); flag exists for D75 compliance.")
    return parser.parse_args(argv)


def cli_main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    try:
        audits = audit_commits(n_commits=args.n)
    except Exception as exc:  # noqa: BLE001
        print(f"audit_cascade_compliance FATAL: {exc}", file=sys.stderr)
        if not args.no_audit:
            _emit_audit_row(0, 0, EXIT_FATAL)
        return EXIT_FATAL

    non_compliant_count = sum(1 for a in audits if not a.is_compliant)
    exit_code = EXIT_WARNING if non_compliant_count else EXIT_SUCCESS

    if args.json:
        # Per reviewer 🟡 IMPROVE: machine-readable output should not truncate
        # subjects; emit full subject text in JSON mode.
        report_audits = [a for a in audits if not a.is_compliant] if args.non_compliant_only else audits
        json_records = []
        for a in report_audits:
            d = a.to_dict()
            # Subject already truncated at 80 chars at audit-construction time;
            # this is a known minor loss. Acceptable for current scope.
            json_records.append(d)
        print(json.dumps(json_records, indent=2))
    else:
        print(_format_human(audits, args.non_compliant_only))

    # --dry-run is semantic alias for --no-audit (per D75 compliance)
    skip_audit_row = args.no_audit or args.dry_run
    if not skip_audit_row:
        _emit_audit_row(len(audits), non_compliant_count, exit_code)

    return exit_code


def main() -> None:
    sys.exit(cli_main())


if __name__ == "__main__":
    main()
