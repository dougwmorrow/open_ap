#!/usr/bin/env python3
"""Hard rule 14 cascade classifier — Phase 1B per B-317.

Mechanically classifies a staged commit scope along the anti-trigger axis
defined by CLAUDE.md hard rule 14. Used by `tools/check_commit_msg.py` to
determine whether the commit-message MUST contain cascade-evidence section
(TEST + GAP ANALYSIS + REVIEW) or qualifies for auto-anti-trigger.

Per B-317 + Phase 2A substrate-edit clause: enforcement-discipline substrate
edits are NEVER anti-triggers (high-risk by definition; producer judgment of
"internal refactor" is the failure mode that surfaced at commit `0a0ff49`
where hard rule 14 was silently skipped on a substrate refactor).

Closes the silent-omission class of cascade-skip that all 6 prior defense
layers (AppLaunchpad ledger / Mechanism C-1 hook / udm-exemption-verifier /
hard rule 14 directive / check_gap_accountability) failed to detect because
they fire on phrase presence, not section absence.

Per D74 — exit codes (when invoked as CLI):
- 0: classification successful (prints JSON to stdout)
- 3: fatal error

Per D75: read-only; no --dry-run needed.
Per D76: caller emits audit row (this is a pure library + helper CLI).

Public surface:
- `classify_commit(staged: list[str] | None) -> CommitClassification`
- `has_cascade_evidence(commit_msg: str) -> tuple[bool, list[str]]`
- `CommitClassification` dataclass
- `SUBSTRATE_FILES`, `SUBSTRATE_DIR_PREFIXES` constants
- Classification constants `CLASS_*`
- `EVENT_TYPE` (for caller audit composition)
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, asdict
from pathlib import Path

EVENT_TYPE = "CLI_CASCADE_CLASSIFIER"
EXIT_SUCCESS = 0
EXIT_FATAL = 3

REPO_ROOT = Path(__file__).resolve().parent.parent

# Enforcement-discipline substrate files — NEVER anti-trigger per Phase 2A
# substrate-edit clause (CLAUDE.md hard rule 14 amendment 2026-05-16).
# These files ARE the discipline-enforcement layer; if broken they break
# discipline. Empirical: 2 retroactive cascades in 2026-05-16 session both
# found 🔴 BLOCK findings in substrate refactors.
SUBSTRATE_FILES = frozenset((
    "tools/pre_commit_checks.py",
    "tools/query_blindspots.py",
    "tools/check_commit_msg.py",
    "tools/exemption_phrases.py",
    "tools/install_pre_commit_hook.py",
    "tools/cascade_classifier.py",
    "tools/verify_cascade.py",
    "tools/cli_common.py",
    ".githooks/pre-commit",
    ".githooks/commit-msg",
    ".github/workflows/pre-commit-mirror.yml",
    "docs/migration/blindspots/ledger.yml",
    "docs/migration/CHECKS_AND_BALANCES.md",
    "docs/migration/PLANNING_DISCIPLINE.md",
    "docs/migration/SELF_IMPROVEMENT_DISCIPLINE.md",
    "CLAUDE.md",
))

SUBSTRATE_DIR_PREFIXES = (
    ".claude/skills/udm-",
    ".claude/agents/udm-",
    ".claude/hooks/",
    "docs/migration/blindspots/",
)

# Per Phase 1B + reviewer 🟡 IMPROVE: canonical source files where small
# edits (≤5 lines) often add D-N / B-N / R-N / RB-N substance — NOT typos.
# Excluded from TYPO_ONLY auto-anti-trigger classification.
CANONICAL_SOURCE_FILES = frozenset((
    "docs/migration/03_DECISIONS.md",
    "docs/migration/BACKLOG.md",
    "docs/migration/RISKS.md",
    "docs/migration/05_RUNBOOKS.md",
    "docs/migration/04_EDGE_CASES.md",
    "docs/migration/02_PHASES.md",
))

# Anti-trigger classification labels
CLASS_SUBSTRATE = "SUBSTRATE_EDIT"
CLASS_TYPO = "TYPO_ONLY"
CLASS_WHITESPACE = "WHITESPACE_ONLY"
CLASS_BADGE_FLIP = "BADGE_FLIP_ONLY"
CLASS_POLISH = "POLISH_QUEUE_ONLY"
CLASS_SUBSTANTIVE = "SUBSTANTIVE"

ANTI_TRIGGER_CLASSES = frozenset((
    CLASS_TYPO,
    CLASS_WHITESPACE,
    CLASS_BADGE_FLIP,
    CLASS_POLISH,
))


@dataclass
class CommitClassification:
    classification: str
    rationale: str
    is_anti_trigger: bool
    cascade_required: bool
    staged_count: int
    total_lines_changed: int

    def to_dict(self) -> dict:
        return asdict(self)


def is_substrate_path(file_path: str) -> bool:
    """True if file_path is enumerated substrate (NEVER anti-trigger)."""
    norm = file_path.replace("\\", "/")
    if norm in SUBSTRATE_FILES:
        return True
    return any(norm.startswith(prefix) for prefix in SUBSTRATE_DIR_PREFIXES)


def _staged_files() -> list[str]:
    """Get staged file paths. Per reviewer 🟡 IMPROVE: include renames (R) and
    deletes (D) since rename/delete of substrate file is high-risk."""
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMRD"],
            capture_output=True, text=True, cwd=str(REPO_ROOT), check=False,
            encoding="utf-8", errors="replace",
        )
        if result.returncode != 0:
            return []
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except (OSError, subprocess.SubprocessError):
        return []


def _diff_numstat() -> tuple[int, int]:
    """Returns (added_lines_total, removed_lines_total) for staged changes."""
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--numstat"],
            capture_output=True, text=True, cwd=str(REPO_ROOT), check=False,
            encoding="utf-8", errors="replace",
        )
        added = removed = 0
        for line in result.stdout.splitlines():
            parts = line.split("\t")
            if len(parts) >= 2:
                try:
                    added += int(parts[0])
                    removed += int(parts[1])
                except ValueError:
                    pass
        return added, removed
    except (OSError, subprocess.SubprocessError):
        return 0, 0


def _staged_diff_content() -> str:
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "-U0"],
            capture_output=True, text=True, cwd=str(REPO_ROOT), check=False,
            encoding="utf-8", errors="replace",
        )
        return result.stdout or ""
    except (OSError, subprocess.SubprocessError):
        return ""


_BADGE_FLIP_RE = re.compile(r"^[+-]- (?:~~)?\*\*B-\d+\*\*")
_STRIKETHROUGH_WRAP_RE = re.compile(r"^[+-]- ~~\*\*[BDPR]-\d+\*\*")


def classify_commit(staged: list[str] | None = None) -> CommitClassification:
    """Classify staged scope per hard rule 14 anti-trigger axis.

    Substrate-edits ALWAYS classify as SUBSTRATE_EDIT (cascade required).
    Otherwise auto-detects TYPO_ONLY / WHITESPACE_ONLY / BADGE_FLIP_ONLY /
    POLISH_QUEUE_ONLY anti-triggers; everything else classifies as SUBSTANTIVE
    (cascade required).
    """
    if staged is None:
        staged = _staged_files()

    if not staged:
        return CommitClassification(
            classification=CLASS_SUBSTANTIVE,
            rationale="no staged files; default to substantive",
            is_anti_trigger=False,
            cascade_required=True,
            staged_count=0,
            total_lines_changed=0,
        )

    # Substrate check (highest priority; overrides all anti-trigger detection)
    substrate_hits = [f for f in staged if is_substrate_path(f)]
    if substrate_hits:
        added, removed = _diff_numstat()
        return CommitClassification(
            classification=CLASS_SUBSTRATE,
            rationale=(
                f"substrate edit (enforcement-discipline files): "
                f"{', '.join(sorted(substrate_hits)[:5])}"
                f"{'...' if len(substrate_hits) > 5 else ''}; "
                "cascade REQUIRED per hard rule 14 substrate-edit clause "
                "(Phase 2A; B-317)"
            ),
            is_anti_trigger=False,
            cascade_required=True,
            staged_count=len(staged),
            total_lines_changed=added + removed,
        )

    added, removed = _diff_numstat()
    total = added + removed

    # POLISH_QUEUE-only edits
    if all("POLISH_QUEUE.md" in f.replace("\\", "/") for f in staged):
        return CommitClassification(
            classification=CLASS_POLISH,
            rationale=f"POLISH_QUEUE.md only ({len(staged)} file(s); {total} lines)",
            is_anti_trigger=True,
            cascade_required=False,
            staged_count=len(staged),
            total_lines_changed=total,
        )

    diff_content = _staged_diff_content()

    # Whitespace-only check (per reviewer 🔴 BLOCK fix: explicit parens around
    # the diff-line predicate; previous code had operator-precedence bug where
    # `+` lines bypassed the has-content check due to `and` binding tighter
    # than `or` — pure-whitespace + lines counted as non-whitespace).
    def _is_diff_content_line(line: str) -> bool:
        if line.startswith("+") and not line.startswith("+++"):
            return True
        if line.startswith("-") and not line.startswith("---"):
            return True
        return False

    non_ws_lines = [
        line[1:] for line in diff_content.splitlines()
        if _is_diff_content_line(line) and line[1:].strip()
    ]
    if not non_ws_lines and total > 0:
        return CommitClassification(
            classification=CLASS_WHITESPACE,
            rationale=f"only whitespace changes detected ({total} lines)",
            is_anti_trigger=True,
            cascade_required=False,
            staged_count=len(staged),
            total_lines_changed=total,
        )

    # Badge-flip-only check (BACKLOG.md only + strikethrough pattern dominant)
    if all(f.replace("\\", "/") == "docs/migration/BACKLOG.md" for f in staged):
        diff_lines = [
            line for line in diff_content.splitlines()
            if (line.startswith(("+", "-")) and not line.startswith(("+++", "---")))
        ]
        relevant = [l for l in diff_lines if l[1:].strip()]
        if relevant:
            badge_lines = sum(
                1 for l in relevant
                if _BADGE_FLIP_RE.match(l) or _STRIKETHROUGH_WRAP_RE.match(l)
            )
            ratio = badge_lines / len(relevant)
            if ratio >= 0.8:
                return CommitClassification(
                    classification=CLASS_BADGE_FLIP,
                    rationale=(
                        f"BACKLOG.md badge-flip dominant "
                        f"({badge_lines}/{len(relevant)} lines = {ratio:.0%})"
                    ),
                    is_anti_trigger=True,
                    cascade_required=False,
                    staged_count=len(staged),
                    total_lines_changed=total,
                )

    # Typo-only check (markdown-only AND ≤5 lines net AND no canonical-source
    # files per reviewer 🟡 IMPROVE: D-N / B-N / R-N edits are substantive even
    # at low line count; exclude from TYPO classification).
    md_only = all(f.endswith(".md") for f in staged)
    touches_canonical = any(
        f.replace("\\", "/") in CANONICAL_SOURCE_FILES for f in staged
    )
    if md_only and total <= 5 and not touches_canonical:
        return CommitClassification(
            classification=CLASS_TYPO,
            rationale=(
                f"small markdown edit ({total} lines net; ≤5 threshold; "
                "no canonical-source files; typo-class anti-trigger)"
            ),
            is_anti_trigger=True,
            cascade_required=False,
            staged_count=len(staged),
            total_lines_changed=total,
        )

    # Default: SUBSTANTIVE — cascade required
    return CommitClassification(
        classification=CLASS_SUBSTANTIVE,
        rationale=(
            f"substantive edit ({total} lines across {len(staged)} file(s); "
            "no anti-trigger pattern matched)"
        ),
        is_anti_trigger=False,
        cascade_required=True,
        staged_count=len(staged),
        total_lines_changed=total,
    )


# Cascade-evidence section detection per hard rule 14 + B-318 tri-section
TEST_SECTION_RE = re.compile(
    r"^##+\s*(?:TEST\b|Verification\s*[-—:]?\s*TEST\b|Tests?\b|Test plan\b|Pytest\b)",
    re.IGNORECASE | re.MULTILINE,
)
GAP_SECTION_RE = re.compile(
    r"^##+\s*(?:GAP\s*ANALYSIS\b|Gap[- ]?check\b|GAP\b|Gap\s*reflection\b)",
    re.IGNORECASE | re.MULTILINE,
)
REVIEW_SECTION_RE = re.compile(
    r"^##+\s*(?:REVIEW\b|Design\s*review\b|Reviewer\b|Independent\s*review\b)",
    re.IGNORECASE | re.MULTILINE,
)


def has_cascade_evidence(commit_msg: str) -> tuple[bool, list[str]]:
    """Verify commit message has all 3 cascade sections per hard rule 14 + B-318.

    Returns (all_present, list_of_missing_section_names).
    """
    missing: list[str] = []
    if not TEST_SECTION_RE.search(commit_msg):
        missing.append("TEST")
    if not GAP_SECTION_RE.search(commit_msg):
        missing.append("GAP ANALYSIS")
    if not REVIEW_SECTION_RE.search(commit_msg):
        missing.append("REVIEW")
    return (len(missing) == 0, missing)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Classify staged commit scope per hard rule 14 anti-trigger axis.",
    )
    parser.add_argument("--json", action="store_true", help="Emit JSON output.")
    return parser.parse_args(argv)


def cli_main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    try:
        cls = classify_commit()
    except Exception as exc:  # noqa: BLE001
        print(f"cascade_classifier FATAL: {exc}", file=sys.stderr)
        return EXIT_FATAL
    if args.json:
        print(json.dumps(cls.to_dict(), indent=2))
    else:
        print(f"Classification: {cls.classification}")
        print(f"Rationale: {cls.rationale}")
        print(f"Anti-trigger: {cls.is_anti_trigger}")
        print(f"Cascade required: {cls.cascade_required}")
        print(f"Staged files: {cls.staged_count}; lines changed: {cls.total_lines_changed}")
    return EXIT_SUCCESS


def main() -> None:
    sys.exit(cli_main())


if __name__ == "__main__":
    main()
