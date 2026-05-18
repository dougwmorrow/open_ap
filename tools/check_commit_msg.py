#!/usr/bin/env python3
"""Commit-msg check logic — Mechanism C-1 exemption-phrase detection.

Extracted from `.githooks/commit-msg` per B-310 cross-platform shebang fix
(2026-05-16): Windows git-bash lacks `python3` in PATH, so the previous
direct-Python-script hook failed. The git hook is now a bash wrapper
(`.githooks/commit-msg`) that detects an available Python interpreter and
invokes this module.

Per B-306 (2026-05-16): writes per-invocation audit row to
`_session_logs/cli_check_commit_msg_<date>.log` per D76 audit-row contract.
Mirrors `tools/pre_commit_checks.py` `_emit_audit_row` pattern.

Per B-449 closure (2026-05-18; Agent 59 cycle-3 D72 convergence finding G3-K2):
adds `check_pytest_count_disambiguation` — WARN-only check that scans the
commit-msg TEST section for pytest counts cited without scope-disambiguation.
Empirical anchor commit `e76078c` cited "2418 pass" (actually tier0+tier1
scope but no scope-indicator next to the count); established baseline was
2471 from full-suite. The 53-test discrepancy was opaque to external readers
without cross-referencing prior baseline messages. Closure target:
Mechanism C-1 Phase 2 extension; warn-only per WSJF MEDIUM (escalation to
BLOCK reserved for pipeline-lead after false-positive baseline period).

Per B-451 closure (2026-05-18; Agent 59 cycle-3 D72 convergence finding G2-A):
adds `check_unresolved_forward_prevention_candidates` — WARN-only check that
scans GAP ANALYSIS + REVIEW + body for orphan-candidate phrasings (e.g.
"deferred (B-N candidate for X)" / "tracked as B-N TBD") and verifies either
(a) BACKLOG.md staged diff opens a NEW B-N entry, OR (b) commit-msg cites
explicit dismissal/deferral target. Empirical anchor commit `e76078c` GAP
ANALYSIS mentioned "B-409 + B-414 commit-message cascade-evidence audit"
deferred candidate without corresponding BACKLOG opening (Agent 59 G2-A
finding). Closure target: Mechanism C-1 Phase 2 extension; warn-only per
WSJF MEDIUM. NOTE: home-file choice rationale — although BACKLOG B-451 text
named `tools/pre_commit_checks.py`, that orchestrator runs BEFORE commit-msg
is finalized (cannot read COMMIT_EDITMSG). The check NEEDS commit-msg
content + BACKLOG.md staged diff; commit-msg hook timing satisfies both.

Usage (invoked by `.githooks/commit-msg` wrapper):
    python check_commit_msg.py <commit-msg-path> [--no-audit]

Exit codes:
- 0: no exemption-claim phrases detected (pass; pytest-count check is WARN-only)
- 1: exemption-claim phrases detected (BLOCK) OR cascade-evidence missing
- 0: COMMIT_EDITMSG missing or unreadable (graceful fallback)
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

EVENT_TYPE = "CLI_CHECK_COMMIT_MSG"
EXIT_SUCCESS = 0
EXIT_BLOCKED = 1

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

try:
    from tools.exemption_phrases import contains_exemption_phrase
except ImportError as _exc:
    print(f"[commit-msg WARN] cannot import tools.exemption_phrases ({_exc}); "
          "exemption-phrase check skipped.", file=sys.stderr)
    contains_exemption_phrase = None  # type: ignore[assignment]

try:
    from tools.cascade_classifier import classify_commit, has_cascade_evidence
except ImportError as _exc:
    print(f"[commit-msg WARN] cannot import tools.cascade_classifier ({_exc}); "
          "hard rule 14 cascade-evidence check skipped.", file=sys.stderr)
    classify_commit = None  # type: ignore[assignment]
    has_cascade_evidence = None  # type: ignore[assignment]

try:
    from tools.cascade_classifier import _extract_section_bodies
except ImportError:
    _extract_section_bodies = None  # type: ignore[assignment]


# -------------------------------------------------------------------------
# B-449 closure: pytest-count disambiguation check
# -------------------------------------------------------------------------
# Empirical anchor commit `e76078c` (Agent 59 cycle-3 D72 convergence finding
# G3-K2): TEST section cited "2418 pass" with tier0+tier1 scope but baseline
# was 2471 from full-suite — the 53-test discrepancy was opaque without
# cross-referencing prior baseline messages. Forward-prevention: WARN on
# pytest counts in TEST section that lack a co-located scope indicator.
#
# Counts are 3-5 digits (covers small Tier 0 subset like "39/39 PASS" through
# full suites like "2589 passed"); avoids matching unrelated 2-digit / 6+ digit
# numbers in prose.
_PYTEST_COUNT_RE = re.compile(
    r"\b(\d{2,5})\s*(?:/\s*\d{1,5})?\s*(?:pass(?:ed|ing)?|PASS(?:ED)?)\b",
)

# Scope indicators that disambiguate WHICH pytest scope produced a count.
# Order matters for diagnostic; full-suite synonyms first.
_SCOPE_INDICATORS = (
    "full-suite", "full suite", "full_suite",
    "tier0+tier1", "tier0 + tier1", "tier0,tier1", "tier0 tier1",
    "tier 0+tier 1", "tier0+tier1+", "tier0+",
    "tier0", "tier 0", "tier-0",
    "tier1", "tier 1", "tier-1",
    "tier2", "tier 2", "tier-2",
    "tier3", "tier 3", "tier-3",
    "tier4", "tier 4", "tier-4",
    "tests/tier0", "tests/tier1", "tests/tier2", "tests/tier3", "tests/tier4",
    "tests/unit", "tests/property", "tests/regression", "tests/integration", "tests/crash",
    "unit+property", "unit + property",
    "authoritative",  # canonical "full-suite authoritative" pattern
    "baseline preserved",  # canonical "no scope change vs prior baseline" pattern
    "from prior verification",  # references prior verified baseline scope
    "python -m pytest", ".venv/scripts/python.exe -m pytest", ".venv/bin/python -m pytest",
    "-m pytest tests/",
    "scope:",
)


def _has_scope_indicator(text: str) -> bool:
    """True if `text` contains a recognized pytest scope-indicator substring
    (case-insensitive). Used to scope-disambiguate pytest counts per B-449."""
    lower = text.lower()
    return any(ind in lower for ind in _SCOPE_INDICATORS)


def _extract_test_section_text(commit_msg: str) -> str | None:
    """Extract the TEST section body as a single joined string. Returns None
    if cascade_classifier helper unavailable OR no TEST section present."""
    if _extract_section_bodies is None:
        return None
    sections = _extract_section_bodies(commit_msg)
    if "TEST" not in sections:
        return None
    return "\n".join(sections["TEST"])


def _strip_code_blocks(text: str) -> str:
    """Remove fenced code blocks (```...```) from `text`. Pytest counts inside
    code blocks are verbatim quoted output — never trigger WARN on those."""
    return re.sub(r"```[\s\S]*?```", "", text)


def check_pytest_count_disambiguation(commit_msg: str) -> tuple[bool, list[str]]:
    """Per B-449 closure (Agent 59 cycle-3 D72 convergence finding G3-K2):
    scan TEST section for pytest counts cited WITHOUT scope disambiguation.

    Detection logic:
    1. Extract TEST section body via cascade_classifier._extract_section_bodies
    2. Strip fenced code blocks (verbatim quoted pytest output is acceptable)
    3. For each pytest count match (e.g., "2418 pass" / "39/39 PASS"):
       - Get the surrounding line context
       - Verify a scope-indicator substring appears in same line OR within
         ±3 lines (e.g., a count on one line + "scope: tier0+tier1" nearby)
    4. WARN (not BLOCK) on each unpaired count match

    Returns (passed: bool, findings: list[str]) tuple — mirrors the
    has_cascade_evidence() signature for caller convenience.

    Anti-patterns (acceptable; do NOT WARN):
    - "pytest tier0+tier1: 2418 pass" (scope on same line)
    - "Pytest baseline preserved (2471 pass / 10 skip / 0 fail from prior verification)"
      ("baseline preserved" + "from prior verification" both scope-equivalent)
    - "pytest tests/tier0: 510/510 PASS" (explicit test-dir cite)
    - Counts inside ``` code blocks (verbatim output)

    Bad patterns (WARN):
    - "pytest 2471 pass" (no scope; ambiguous)
    - "Pytest: 2471/10/0 (unchanged)" ("unchanged" is too soft; could mean
      unchanged scope OR unchanged count of different scope)
    - Multiple distinct counts with no scope attribution per count
    """
    test_text = _extract_test_section_text(commit_msg)
    if test_text is None:
        return True, []  # No TEST section OR helper unavailable → no check

    sanitized = _strip_code_blocks(test_text)
    if not sanitized.strip():
        return True, []

    lines = sanitized.splitlines()
    findings: list[str] = []
    seen_lines: set[int] = set()

    for i, line in enumerate(lines):
        matches = list(_PYTEST_COUNT_RE.finditer(line))
        if not matches:
            continue
        if i in seen_lines:
            continue
        # Per-line check: gather ±3 line context around this line
        lo, hi = max(0, i - 3), min(len(lines), i + 4)
        window = "\n".join(lines[lo:hi])
        if _has_scope_indicator(window):
            continue
        # Bare count without scope-indicator nearby
        for m in matches:
            count_str = m.group(1)
            snippet = line.strip()[:120]
            findings.append(
                f"pytest count {count_str!r} cited without scope indicator "
                f"(line {i+1}): {snippet!r}"
            )
        seen_lines.add(i)

    if findings:
        return False, findings[:10]
    return True, []


# -------------------------------------------------------------------------
# B-451 closure: unresolved forward-prevention candidate tracking check
# -------------------------------------------------------------------------
# Empirical anchor commit `e76078c` (Agent 59 cycle-3 D72 convergence finding
# G2-A): commit GAP ANALYSIS section mentioned "B-409 + B-414 commit-message
# cascade-evidence audit" deferred candidate but no corresponding BACKLOG.md
# entry was opened in same commit. Forward-prevention: scan commit-msg for
# orphan-candidate trigger phrases + verify BACKLOG.md staged diff opens
# corresponding B-N OR explicit dismissal cited.
#
# Patterns chosen to match real-history orphan phrasing without false-positive
# on retrospective citation context (e.g., quoting prior B-N closure
# annotation). Each pattern anchored to forward-deferral verb phrasing
# ("deferred (B-N candidate" / "tracked as B-N TBD" / "future B-N candidate").
# Bare "B-NEW-1 candidate" / "deferred candidate" forms covered by a separate
# lower-precision regex; reviewer can extend tuple at maintenance.

_ORPHAN_CANDIDATE_PHRASE_PATTERNS = (
    # Form: "deferred (B-N candidate for X)" or "deferred (B-NEW-1 candidate)"
    re.compile(r"\bdeferred\s*\(\s*B-(?:NEW-)?N?\d*\s*candidate\b", re.IGNORECASE),
    # Form: "tracked as B-N TBD" or "tracked as B-NEW-1 TBD"
    re.compile(r"\btracked\s+as\s+B-(?:NEW-)?N?\d*\s+TBD\b", re.IGNORECASE),
    # Form: "B-N TBD" / "B-NEW-N TBD" (bare TBD form)
    re.compile(r"\bB-(?:NEW-)?N\d*\s+TBD\b", re.IGNORECASE),
    # Form: "tracked via .* B-N opening" (forward-cite without B-N number)
    re.compile(r"\btracked\s+via\s+.*\bB-N\s+opening\b", re.IGNORECASE),
    # Form: "forward-prevention B-N candidate"
    re.compile(r"\bforward-?prevention\s+B-N\s+candidate\b", re.IGNORECASE),
    # Form: "future B-N candidate" (future-cycle orphan)
    re.compile(r"\bfuture\s+B-N\s+candidate\b", re.IGNORECASE),
    # Form: "BNcand-N" (explicit cand syntax per project history at `e76078c`)
    re.compile(r"\bBNcand-\d+\b"),
    # Form: "B-N candidate for X" (generic candidate phrasing without explicit number)
    re.compile(r"\bB-N\s+candidate\s+for\b", re.IGNORECASE),
)

# Detect NEW B-N entries added in BACKLOG.md staged diff. Match lines like:
#   +- **B-451** (🟡 Open; ...
#   +**B-451** (🟡 Open; ...
# Conservative: require the leading-badge "Open" status indicator so we only
# count actual B-N OPENINGS (not strikethrough closures or retrospective edits).
_BACKLOG_BN_OPEN_RE = re.compile(
    r"^\+\s*(?:[-*]\s*)?\*\*B-(\d+)\*\*\s*\([^)]*?Open\b",
    re.MULTILINE,
)

# Explicit-dismissal phrases — when commit-msg cites WHY a candidate is NOT
# being opened, the check passes for that candidate. Order matters for
# diagnostic specificity.
_DISMISSAL_PHRASES = (
    "dismissed because",
    "dismissed per",
    "no b-n needed because",
    "no B-N needed because",
    "no B-N required because",
    "deferred to commit",  # explicit deferral target
    "deferred to <commit",
    "deferred to next commit",
    "out of scope per",
    "already tracked by b-",  # references existing B-N opening
    "already tracked at b-",
    "already opened at b-",
    "supersedes b-",
)


def _has_explicit_dismissal(text: str) -> bool:
    """True if `text` contains a recognized dismissal / deferral-target phrase
    (case-insensitive). When present, orphan-candidate matches in same scope
    are PASS (not WARN)."""
    lower = text.lower()
    return any(phrase in lower for phrase in _DISMISSAL_PHRASES)


def _is_inside_blockquote(lines: list[str], idx: int) -> bool:
    """True if `lines[idx]` is inside a markdown blockquote context (line starts
    with `>` or the immediately preceding line does and current is continuation).
    Used to suppress false-positive on quoted verbatim Agent reviewer output."""
    if idx >= len(lines):
        return False
    if lines[idx].lstrip().startswith(">"):
        return True
    return False


def check_unresolved_forward_prevention_candidates(
    commit_msg: str,
    staged_backlog_diff: str | None = None,
) -> tuple[bool, list[str]]:
    """Per B-451 closure (Agent 59 cycle-3 D72 convergence finding G2-A):
    scan commit-msg GAP ANALYSIS + REVIEW + body for orphan-candidate
    phrasings + verify corresponding BACKLOG.md staged diff opens a NEW B-N
    OR explicit dismissal cited.

    Args:
        commit_msg: full commit-message text
        staged_backlog_diff: optional pre-fetched git diff --cached output for
            docs/migration/BACKLOG.md; if None, attempts subprocess call.
            Pass empty string "" to indicate no BACKLOG.md staged.

    Returns (passed: bool, findings: list[str]) tuple — mirrors the
    has_cascade_evidence() signature for caller convenience.

    Detection logic:
    1. Strip fenced code blocks (verbatim Agent output is acceptable)
    2. Scan GAP ANALYSIS + REVIEW + commit body for orphan-candidate patterns
    3. Suppress matches inside blockquote (`> ...`) lines — those are
       retrospective citations of prior commits, not new orphan claims
    4. For each unsuppressed orphan-candidate match, verify EITHER:
       (a) BACKLOG.md staged diff opens at least one NEW B-N entry, OR
       (b) commit-msg cites explicit dismissal / deferral-target phrasing
    5. WARN (not BLOCK) on each unmatched orphan-candidate phrase
    """
    sanitized = _strip_code_blocks(commit_msg)
    if not sanitized.strip():
        return True, []

    lines = sanitized.splitlines()
    orphan_matches: list[tuple[int, str, str]] = []  # (line_idx, snippet, pattern)

    for i, line in enumerate(lines):
        if _is_inside_blockquote(lines, i):
            continue
        for pat in _ORPHAN_CANDIDATE_PHRASE_PATTERNS:
            m = pat.search(line)
            if m:
                snippet = line.strip()[:120]
                orphan_matches.append((i, snippet, pat.pattern))
                break  # one match per line suffices

    if not orphan_matches:
        return True, []

    # Check for explicit dismissal in whole commit-msg
    if _has_explicit_dismissal(sanitized):
        # Dismissal phrasing globally satisfies — no per-match BACKLOG opening required
        return True, []

    # Check BACKLOG.md staged diff for NEW B-N openings
    backlog_opens_count = 0
    if staged_backlog_diff is None:
        try:
            result = subprocess.run(
                ["git", "diff", "--cached", "docs/migration/BACKLOG.md"],
                capture_output=True, text=True, timeout=10, cwd=REPO_ROOT,
            )
            staged_backlog_diff = result.stdout if result.returncode == 0 else ""
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            staged_backlog_diff = ""

    if staged_backlog_diff:
        backlog_opens_count = len(_BACKLOG_BN_OPEN_RE.findall(staged_backlog_diff))

    if backlog_opens_count >= len(orphan_matches):
        # Sufficient BACKLOG openings for all orphan-candidates
        return True, []

    # Some orphans are unmatched — WARN
    findings: list[str] = []
    unmatched = len(orphan_matches) - backlog_opens_count
    for idx, (line_idx, snippet, _pat) in enumerate(orphan_matches[:10]):
        findings.append(
            f"orphan-candidate phrase cited (line {line_idx+1}): {snippet!r} "
            f"— {unmatched} unresolved (found {backlog_opens_count} new B-N "
            f"opening(s) in staged BACKLOG diff vs {len(orphan_matches)} "
            "candidate(s); no explicit dismissal cited)"
        )
    return False, findings


def _emit_audit_row(
    commit_msg_path: Path,
    matched_phrases: list[str],
    exit_code: int,
    classification: str | None = None,
    missing_sections: list[str] | None = None,
    pytest_count_findings: list[str] | None = None,
    orphan_candidate_findings: list[str] | None = None,
) -> None:
    """Per-invocation audit row per D76 + B-306 + B-317 + B-449.

    Per reviewer 🟡 IMPROVE: cascade verdict (classification + missing_sections)
    included in audit payload — forensic audit of cascade-skip BLOCK can now
    identify the BLOCK cause without re-running the classifier.

    Per B-449 (2026-05-18): pytest_count_findings included so forensic audit
    can trace WARN-only discipline-drift events even though they do not affect
    exit_code (escalation to BLOCK reserved for pipeline-lead).

    Per B-451 (2026-05-18): orphan_candidate_findings included so forensic
    audit can trace unresolved-forward-prevention-candidate WARN events.
    Same WARN-only semantic as B-449 — does NOT affect exit_code.
    """
    audit_dir = REPO_ROOT / "_session_logs"
    try:
        audit_dir.mkdir(exist_ok=True)
    except OSError:
        return
    log_path = audit_dir / f"cli_check_commit_msg_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.log"
    payload = {
        "event_type": EVENT_TYPE,
        "ts": datetime.now(timezone.utc).isoformat(),
        "commit_msg_path": str(commit_msg_path),
        "matched_phrases": matched_phrases,
        "classification": classification,
        "missing_sections": missing_sections or [],
        "pytest_count_findings": pytest_count_findings or [],
        "orphan_candidate_findings": orphan_candidate_findings or [],
        "exit_code": exit_code,
    }
    try:
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload) + "\n")
    except OSError:
        pass


def main(argv: list[str]) -> int:
    no_audit = "--no-audit" in argv
    positional = [a for a in argv[1:] if not a.startswith("--")]
    if not positional:
        return EXIT_SUCCESS
    commit_msg_path = Path(positional[0])
    if not commit_msg_path.is_file():
        return EXIT_SUCCESS
    try:
        commit_msg = commit_msg_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return EXIT_SUCCESS
    if contains_exemption_phrase is None:
        return EXIT_SUCCESS

    # Strip git-comment lines ("# <text>" or bare "#") but preserve markdown
    # multi-hash headers ("## TEST" / "### Section"). Per B-317 Phase 1A: the
    # cascade-evidence section detector requires markdown headers to survive
    # comment stripping.
    def _is_git_comment(line: str) -> bool:
        stripped = line.lstrip()
        if not stripped.startswith("#"):
            return False
        # Bare `#` line (rare)
        if stripped.rstrip() == "#":
            return True
        # `# <space>...` = git comment; `##...` = markdown header
        return stripped.startswith("# ")
    non_comment_lines = [
        line for line in commit_msg.splitlines() if not _is_git_comment(line)
    ]
    actual_msg = "\n".join(non_comment_lines)

    matched_phrases = contains_exemption_phrase(actual_msg)
    exemption_exit_code = EXIT_BLOCKED if matched_phrases else EXIT_SUCCESS

    # Per B-317 Phase 1A: hard rule 14 cascade-evidence check.
    # Closes the silent-omission class that all 6 prior defense layers missed
    # (they fire on phrase presence; this fires on section absence).
    # Per reviewer 🟡 IMPROVE: wrap classify_commit() call with try/except
    # so unexpected git/subprocess failures degrade gracefully (don't block
    # the commit with a traceback) rather than aborting the hook hard.
    cascade_exit_code = EXIT_SUCCESS
    cascade_diag = ""
    cls = None
    cascade_findings: list[str] = []  # per reviewer 🟡 #4 rename: was `missing_sections`
    if classify_commit is not None and has_cascade_evidence is not None:
        try:
            cls = classify_commit()
        except Exception as exc:  # noqa: BLE001 — degrade gracefully on unexpected errors
            print(f"[commit-msg WARN] cascade-classifier raised ({exc}); "
                  "cascade-evidence check skipped this commit.", file=sys.stderr)
            cls = None
        if cls is not None and cls.cascade_required:
            # Per B-321 closure: pass classification for substrate-stricter check
            # + body-content validation (no more header-only false-PASS). Findings
            # now include BOTH missing-headers AND body-validation failures.
            has_ev, cascade_findings = has_cascade_evidence(
                actual_msg, classification=cls.classification,
            )
            if not has_ev:
                cascade_exit_code = EXIT_BLOCKED
                cascade_diag = (
                    f"hard rule 14 cascade-evidence missing or invalid per B-317 + B-321 "
                    f"(commit classified as {cls.classification}: {cls.rationale}); "
                    f"findings: {'; '.join(cascade_findings)}"
                )

    # Per B-449 (2026-05-18; Agent 59 cycle-3 D72 convergence finding G3-K2):
    # pytest-count disambiguation — WARN-only (does NOT contribute to BLOCK
    # exit code per WSJF MEDIUM; pipeline-lead can escalate later if
    # false-positive rate is low after baseline period). Findings emitted to
    # stderr + included in audit-row for forensic correlation.
    pytest_count_findings: list[str] = []
    try:
        _pytest_count_ok, pytest_count_findings = check_pytest_count_disambiguation(actual_msg)
    except Exception as exc:  # noqa: BLE001 — degrade gracefully
        print(f"[commit-msg WARN] pytest-count disambiguation check raised ({exc}); "
              "WARN-only check skipped this commit.", file=sys.stderr)

    # Per B-451 (2026-05-18; Agent 59 cycle-3 D72 convergence finding G2-A):
    # orphan-candidate forward-prevention tracking — WARN-only (same WSJF
    # MEDIUM rationale as B-449; pipeline-lead can escalate after baseline).
    orphan_candidate_findings: list[str] = []
    try:
        _orphan_ok, orphan_candidate_findings = check_unresolved_forward_prevention_candidates(actual_msg)
    except Exception as exc:  # noqa: BLE001 — degrade gracefully
        print(f"[commit-msg WARN] orphan-candidate tracking check raised ({exc}); "
              "WARN-only check skipped this commit.", file=sys.stderr)

    final_exit_code = EXIT_BLOCKED if (
        exemption_exit_code == EXIT_BLOCKED or cascade_exit_code == EXIT_BLOCKED
    ) else EXIT_SUCCESS

    if not no_audit:
        _emit_audit_row(
            commit_msg_path, matched_phrases, final_exit_code,
            classification=cls.classification if cls else None,
            missing_sections=cascade_findings,
            pytest_count_findings=pytest_count_findings,
            orphan_candidate_findings=orphan_candidate_findings,
        )

    if matched_phrases:
        print("[commit-msg BLOCKED] commit message contains exemption-claim "
              "trigger phrases:", file=sys.stderr)
        for p in matched_phrases:
            print(f"  - {p!r}", file=sys.stderr)
        print("\nPer Mechanism C-1 + udm-exemption-verifier SKILL.md: spawn "
              "udm-exemption-verifier reviewer (via Claude Code session) BEFORE "
              "committing. Reviewer verdict VALID -> proceed; INVALID -> spawn "
              "udm-gap-check per D56 second-pass; address findings; re-attempt "
              "commit.", file=sys.stderr)
        print("\nBypass with --no-verify is self-flagging exemption-claim that "
              "reviewers should treat as quasi-audit-question trigger.",
              file=sys.stderr)

    if cascade_exit_code == EXIT_BLOCKED:
        print(f"\n[commit-msg BLOCKED] {cascade_diag}", file=sys.stderr)
        print("\nRequired structure per hard rule 14 + B-318 tri-section discipline:", file=sys.stderr)
        print("  ## TEST", file=sys.stderr)
        print("  <pytest verdict / orchestrator smoke / behavioral test results>", file=sys.stderr)
        print("  ## GAP ANALYSIS", file=sys.stderr)
        print("  <udm-gap-check verdict OR inline G1-G6 audit OR SKIPPED: <specific anti-trigger reason>>", file=sys.stderr)
        print("  ## REVIEW", file=sys.stderr)
        print("  <udm-design-reviewer verdict OR inline self-review OR SKIPPED: <specific reason>>", file=sys.stderr)
        print(f"\nIf this is an anti-trigger commit, include explicit 'SKIPPED: <anti-trigger>' "
              "in each missing section. Bypass with --no-verify is self-flagging cascade-skip "
              "that reviewers should treat as quasi-audit-question trigger.", file=sys.stderr)

    # Per B-449: pytest-count disambiguation WARN block (NOT a BLOCK; informational
    # only). Helps producer catch ambiguous count citations like "2418 pass" before
    # the commit lands; pipeline-lead can escalate to BLOCK after baseline period.
    if pytest_count_findings:
        print(f"\n[commit-msg WARN] {len(pytest_count_findings)} pytest count(s) "
              "cited without scope disambiguation in TEST section "
              "(per B-449; Agent 59 cycle-3 G3-K2 empirical anchor commit `e76078c`):",
              file=sys.stderr)
        for f in pytest_count_findings:
            print(f"  - {f}", file=sys.stderr)
        print("\nDisambiguate by citing scope alongside count, e.g.:", file=sys.stderr)
        print("  - 'pytest tier0+tier1: 2418 pass / 10 skip / 0 fail'", file=sys.stderr)
        print("  - 'pytest tests/tier0: 510/510 PASS'", file=sys.stderr)
        print("  - 'pytest full-suite authoritative: 2471 pass / 10 skip / 0 fail'", file=sys.stderr)
        print("  - 'pytest baseline preserved (2471 pass / 10 skip / 0 fail "
              "from prior verification)'", file=sys.stderr)
        print("This is a WARN (not BLOCK); commit will still proceed. "
              "Escalation to BLOCK reserved for pipeline-lead post-baseline period.",
              file=sys.stderr)

    # Per B-451: orphan-candidate forward-prevention WARN block (NOT a BLOCK).
    # Helps producer notice when GAP ANALYSIS / REVIEW cites a deferred
    # candidate without corresponding BACKLOG opening — closes the orphan
    # tracking class surfaced by Agent 59 G2-A at commit `e76078c`.
    if orphan_candidate_findings:
        print(f"\n[commit-msg WARN] {len(orphan_candidate_findings)} orphan "
              "forward-prevention candidate(s) cited in commit-msg without "
              "matching BACKLOG.md staged entry "
              "(per B-451; Agent 59 cycle-3 G2-A empirical anchor commit `e76078c`):",
              file=sys.stderr)
        for f in orphan_candidate_findings:
            print(f"  - {f}", file=sys.stderr)
        print("\nResolution options:", file=sys.stderr)
        print("  - Open a corresponding B-N entry in docs/migration/BACKLOG.md "
              "(add to staged diff)", file=sys.stderr)
        print("  - Cite explicit dismissal in commit-msg ('dismissed because X' / "
              "'no B-N needed because Y' / 'deferred to commit abc1234')", file=sys.stderr)
        print("This is a WARN (not BLOCK); commit will still proceed. "
              "Escalation to BLOCK reserved for pipeline-lead post-baseline period.",
              file=sys.stderr)

    return final_exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
