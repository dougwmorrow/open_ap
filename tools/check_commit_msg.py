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

Per B-451 closure (2026-05-18; Agent 59 cycle-3 D72 convergence finding G2-A):
adds `check_unresolved_forward_prevention_candidates` — WARN-only check that
scans GAP ANALYSIS + REVIEW + body for orphan-candidate phrasings.

Per B-459 closure (2026-05-18; Agent 68 architectural design review Scope 2
Concern 2.1): extracted `CommitMsgCheck` ABC + `CheckResult` dataclass. 4
pre-existing checks (exemption-phrase + cascade-evidence + pytest-count B-449
+ orphan-candidate B-451) migrated to `CommitMsgCheck` subclass instances
collected in `CHECKS` registry. Orchestrator iterates over registry +
collects findings into unified `findings: dict[str, list[str]]` audit-row
field (replaces per-check `pytest_count_findings` + `orphan_candidate_findings`
top-level fields). Triggered BEFORE B-458 implementation to avoid 4th
copy-paste of `_strip_code_blocks` + WARN-only + try/except + audit-row
extension patterns. Adding new checks (e.g., closure-annotation-consistency
per B-458) now requires only authoring a new `CommitMsgCheck` subclass +
appending to `CHECKS`; orchestrator + audit-row + exit-code logic unchanged.
The pre-existing top-level check functions (`check_pytest_count_disambiguation`
+ `check_unresolved_forward_prevention_candidates`) are PRESERVED as thin
delegations to the underlying subclass `scan()` calls for backward
compatibility with existing Tier 0 test callers + any external imports.

Per B-466 closure (2026-05-18; Agent 72 design review Concern 1.1):
`CommitMsgCheck.__init_subclass__` mechanical attribute validation —
verifies subclass declares `name` + `severity` + `requires_backlog_diff`
class attributes at class-definition time (fail-fast). Closes the failure
mode where a subclass omitting one of these attributes instantiates cleanly
but raises opaque `AttributeError` at first orchestrator-iteration access.

Per B-467 closure (2026-05-18; Agent 72 design review Concern 1.2):
introduced `OrchestrationContext` frozen dataclass — batches both
`staged_diffs` + `classification` once at orchestrator entry. Each
`scan(commit_msg, ctx)` call reads `ctx.classification` instead of
recomputing via `classify_commit()`. Generalizes `_collect_staged_diffs()`
into clean abstraction; future checks (B-458 + B-464) compose cleanly
without redundant subprocess invocations.

Per B-468 closure (2026-05-18; Agent 72 design review Concern 1.3):
`CommitMsgCheck.render_findings_to_stderr()` method — eliminates 4-way
copy-paste of per-check stderr-emission boilerplate. Base default emits
severity-prefixed findings; each subclass overrides with check-specific
recommendation footer text. `main()` becomes `for check in CHECKS: if
findings: check.render_findings_to_stderr(findings)`. Adding new checks
(B-458 + B-464) no longer copy-pastes ~14 LOC stderr boilerplate per check.

Usage (invoked by `.githooks/commit-msg` wrapper):
    python check_commit_msg.py <commit-msg-path> [--no-audit]

Exit codes:
- 0: no BLOCK findings (clean OR WARN-only findings present)
- 1: BLOCK findings present (exemption-phrase OR cascade-evidence missing)
- 0: COMMIT_EDITMSG missing or unreadable (graceful fallback)
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

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


# =========================================================================
# B-459 closure: CommitMsgCheck ABC abstraction
# =========================================================================
# Per Agent 68 design review Scope 2 Concern 2.1: 4 commit-msg checks share
# (1) `_strip_code_blocks` invocation, (2) WARN-only contract, (3) try/except
# graceful-degradation, (4) audit-row JSON extension. Extracting an ABC
# eliminates copy-paste pattern and enables new checks (B-458 pending) to
# land via a single subclass + CHECKS registry append.
#
# Severity semantics:
#   - "BLOCK": check failure contributes to EXIT_BLOCKED (used by exemption +
#     cascade-evidence checks per hard rule 14)
#   - "WARN":  check failure emits stderr finding + audit-row entry but
#     does NOT contribute to BLOCK exit code (per WSJF MEDIUM contract)
#
# Audit-row contract (changed in B-459):
#   OLD: per-check top-level fields `pytest_count_findings` + `orphan_candidate_findings`
#   NEW: single unified `findings: dict[str, list[str]]` field keyed by `check.name`
#   Rationale: future checks (B-458 closure-annotation; further extensions)
#   do not require ad-hoc top-level field additions per check; auditors look
#   up findings under a stable key.
# =========================================================================


@dataclass(frozen=True)
class CheckResult:
    """Result of a single CommitMsgCheck.scan() invocation per B-459.

    Attributes:
        passed: True when no findings; False when findings present.
        findings: human-readable strings (empty list when passed=True).
    """
    passed: bool
    findings: list[str] = field(default_factory=list)


class CommitMsgCheck(ABC):
    """Abstract base class for commit-msg orchestrator checks per B-459.

    Subclass contract:
        - Define class attributes:
            * `name` (str; unique identifier; used as audit-row JSON
              findings dict key)
            * `severity` (Literal["WARN", "BLOCK"]; resolved value validated
              by B-471 __init_subclass__ extension)
            * `requires_backlog_diff` (bool; whether scan() reads
              `staged_diffs` for BACKLOG.md content)
            * `requires_classification` (bool; B-472 declarative replacement
              for brittle `isinstance(c, CascadeEvidenceCheck)` dispatch —
              whether scan() reads `ctx.classification`)
        - Implement `scan(commit_msg, ctx)` returning a CheckResult.
        - Optionally override `render_findings_to_stderr(findings)` to emit
          check-specific recommendation footer (default emits findings with
          severity prefix).

    Orchestrator contract:
        - Iterate `CHECKS` registry; pass commit_msg + OrchestrationContext
          to each subclass instance's scan() method; collect findings under
          check.name key in the audit-row findings dict; only severity=BLOCK
          contributes to final exit code.

    Per B-466 (2026-05-18; Agent 72 Concern 1.1): `__init_subclass__`
    validates required class attributes at class-definition time (fail-fast
    instead of opaque runtime `AttributeError`).

    Per B-471 (2026-05-18; Agent 76 Concern 1A): `__init_subclass__`
    additionally validates resolved `severity` VALUE is in
    {"WARN", "BLOCK"} — closes typo-class failure mode (e.g., "BLCK").

    Per B-472 (2026-05-18; Agent 76 Concern 2B): `requires_classification`
    declarative bool attribute replaces brittle `isinstance` dispatch in
    `_build_orchestration_context` — future checks (B-458 + B-464) compose
    cleanly without modifying the orchestrator helper.
    """
    name: str
    severity: Literal["WARN", "BLOCK"]
    requires_backlog_diff: bool
    requires_classification: bool

    def __init_subclass__(cls, **kwargs):
        """Per B-466 (2026-05-18; Agent 72 Concern 1.1): validate every
        `CommitMsgCheck` subclass declares all required class attributes
        at class-definition time, NOT at first orchestrator access.

        Per B-471 (2026-05-18; Agent 76 Concern 1A): additionally validate
        the resolved `severity` VALUE is one of the canonical literals
        ("WARN" or "BLOCK"). Closes the typo-class failure mode where a
        subclass author writing `severity = "BLCK"` or `severity = "warn"`
        would silently pass B-466 attribute-presence validation + silently
        degrade at `main()` `if check.severity == "BLOCK"` (intended BLOCK
        becomes WARN with no diagnostic — EXACTLY the failure mode B-466
        was designed to prevent at a different layer).

        Per B-472 (2026-05-18; Agent 76 Concern 2B): `requires_classification`
        added to the required-attribute set; declarative replacement for
        the brittle `isinstance(c, CascadeEvidenceCheck)` dispatch in
        `_build_orchestration_context`.

        Without this hook, Python treats bare annotations as documentation
        only — a broken subclass omitting `name = "..."` declaration would
        instantiate cleanly but raise opaque `AttributeError: type object
        '<X>' has no attribute 'name'` at first `check.name` access inside
        `findings_by_check[check.name]` or `_collect_orchestration_context(checks)`.

        Fail-fast at class-defn time gives the broken subclass author a
        clear error message identifying which attribute is missing or
        what severity value is invalid.
        """
        super().__init_subclass__(**kwargs)
        required = (
            "name", "severity", "requires_backlog_diff", "requires_classification",
        )
        missing = [attr for attr in required if not hasattr(cls, attr)]
        if missing:
            raise TypeError(
                f"{cls.__name__} subclass of CommitMsgCheck missing required "
                f"class attribute(s): {', '.join(missing)}. All "
                f"CommitMsgCheck subclasses MUST declare name (str) + severity "
                f"(Literal['WARN','BLOCK']) + requires_backlog_diff (bool) + "
                f"requires_classification (bool)."
            )
        # B-471: validate severity VALUE — catches typo like "BLCK" or
        # mis-case like "warn" that pre-B-471 would silently degrade to WARN
        # at `main()` BLOCK-comparison time.
        valid_severities = ("WARN", "BLOCK")
        if cls.severity not in valid_severities:
            raise TypeError(
                f"{cls.__name__}.severity = {cls.severity!r} is not a valid "
                f"severity literal. Must be one of: {valid_severities}. "
                f"Typo-class failure prevented per B-471 closure 2026-05-18."
            )

    @abstractmethod
    def scan(self, commit_msg: str, ctx: "OrchestrationContext") -> CheckResult:
        """Execute check against commit message + orchestration context.

        Args:
            commit_msg: full commit-message text (TEST + GAP + REVIEW + body).
            ctx: OrchestrationContext carrying batched external state
                (staged_diffs dict + cached classification per B-467).

        Returns:
            CheckResult(passed=True, findings=[]) on clean; CheckResult(
            passed=False, findings=[...]) on WARN/BLOCK findings.
        """
        ...

    def render_findings_to_stderr(self, findings: list[str]) -> None:
        """Per B-468 (2026-05-18; Agent 72 Concern 1.3): emit findings to
        stderr with WARN/BLOCK-aware formatting.

        Eliminates 4-way per-check stderr-emission copy-paste in `main()`.
        Each subclass MAY override for check-specific recommendation footers;
        default emits findings line-by-line with severity prefix.

        Args:
            findings: non-empty list of finding strings from scan().
        """
        for finding in findings:
            print(f"[{self.severity}] {self.name}: {finding}", file=sys.stderr)


@dataclass(frozen=True)
class OrchestrationContext:
    """Per B-467 (2026-05-18; Agent 72 Concern 1.2): shared context passed
    to each `CommitMsgCheck.scan()` invocation.

    Batches expensive external state (staged diffs + cascade classification)
    ONCE at orchestrator entry; pass to all checks instead of having each
    check independently recompute. Each `classify_commit()` call spawns a
    `git diff --cached --name-status` subprocess; pre-B-467 main() called
    classify_commit() twice per run (once for audit-row metadata; once
    inside CascadeEvidenceCheck.scan()).

    Generalizes `_collect_staged_diffs()` into a clean abstraction for future
    checks (B-458 + B-464) that also need classification ambient.

    Fields:
        staged_diffs: dict mapping relative file path -> `git diff --cached`
            output text. Only populated for files declared by checks via
            `requires_backlog_diff=True` (currently just BACKLOG.md).
        classification: cached result of `classify_commit()`; None if either
            (a) no cascade-aware check is registered OR (b) classify failed.
    """
    staged_diffs: dict[str, str]
    classification: "CommitClassification | None" = None  # noqa: F821 — forward ref


def _collect_staged_diffs(checks: list[CommitMsgCheck]) -> dict[str, str]:
    """Collect `git diff --cached` for files required by enabled checks.

    Per B-459 — used by orchestrator before iterating checks; avoids
    redundant subprocess calls when multiple checks need the same diff.

    Currently the only diff-needing file is `docs/migration/BACKLOG.md`
    (used by orphan-candidate check + future closure-annotation check).

    Per B-467 (2026-05-18) — PRESERVED as public helper for back-compat
    with Tier 0 assertion 68 (`test_collect_staged_diffs_only_fetches_for_required_checks`).
    The B-467 `_build_orchestration_context()` orchestrator helper delegates
    to this function for the staged_diffs portion.
    """
    needed_files: set[str] = set()
    if any(c.requires_backlog_diff for c in checks):
        needed_files.add("docs/migration/BACKLOG.md")
    diffs: dict[str, str] = {}
    for path in needed_files:
        try:
            result = subprocess.run(
                ["git", "diff", "--cached", "--", path],
                capture_output=True, text=True, check=False, timeout=10,
                cwd=REPO_ROOT,
                encoding="utf-8",  # B-479: explicit UTF-8 for Windows-dev safety (else system codepage CP1252 default would mangle Unicode markers like ⚫)
            )
            diffs[path] = result.stdout if result.returncode == 0 else ""
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            diffs[path] = ""
    return diffs


def _build_orchestration_context(
    checks: list[CommitMsgCheck],
) -> OrchestrationContext:
    """Per B-467 (2026-05-18; Agent 72 Concern 1.2): build the canonical
    `OrchestrationContext` passed to each `check.scan()` invocation.

    Batches:
        - staged_diffs (delegates to `_collect_staged_diffs()`)
        - classification (single `classify_commit()` call IF any check is
          cascade-aware; None otherwise)

    Both subprocess calls (git-diff + classify_commit) happen ONCE here
    rather than per-check + per-audit-row-build, eliminating redundant
    git subprocess fan-out as more checks land.

    Per B-472 (2026-05-18; Agent 76 Concern 2B): dispatch on declarative
    `requires_classification: bool` ABC attribute rather than brittle
    `isinstance(c, CascadeEvidenceCheck)`. Future checks (B-458 + B-464)
    that need classification ambient compose by declaring
    `requires_classification = True`; the helper does not require
    modification when new checks land.

    If `classify_commit` is unavailable (import failed) OR raises, the
    classification field is None — `CascadeEvidenceCheck.scan()` degrades
    gracefully when classification is None (returns PASS per pre-existing
    `classify_commit is None` guard).
    """
    diffs = _collect_staged_diffs(checks)
    classification = None
    if classify_commit is not None and any(
        getattr(c, "requires_classification", False) for c in checks
    ):
        try:
            classification = classify_commit()
        except Exception:  # noqa: BLE001 — degrade gracefully
            classification = None
    return OrchestrationContext(
        staged_diffs=diffs,
        classification=classification,
    )


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
    """Per B-449 closure: scan TEST section for pytest counts cited WITHOUT
    scope disambiguation.

    Per B-459 (2026-05-18) this is a thin compatibility wrapper that
    delegates to `PytestCountDisambiguationCheck().scan()`. Preserved
    as a top-level function for backward compatibility with existing
    Tier 0 tests + any external callers.

    Per B-467 (2026-05-18) — wrapper constructs an empty OrchestrationContext
    for the subclass call. The check ignores ctx fields (no external state
    needed), so any empty context is equivalent.
    """
    ctx = OrchestrationContext(staged_diffs={}, classification=None)
    result = PytestCountDisambiguationCheck().scan(commit_msg, ctx)
    return result.passed, result.findings


# -------------------------------------------------------------------------
# B-451 closure: unresolved forward-prevention candidate tracking check
# -------------------------------------------------------------------------
_ORPHAN_CANDIDATE_PHRASE_PATTERNS = (
    re.compile(r"\bdeferred\s*\(\s*B-(?:NEW-)?N?\d*\s*candidate\b", re.IGNORECASE),
    re.compile(r"\btracked\s+as\s+B-(?:NEW-)?N?\d*\s+TBD\b", re.IGNORECASE),
    re.compile(r"\bB-(?:NEW-)?N\d*\s+TBD\b", re.IGNORECASE),
    re.compile(r"\btracked\s+via\s+.*\bB-N\s+opening\b", re.IGNORECASE),
    re.compile(r"\bforward-?prevention\s+B-N\s+candidate\b", re.IGNORECASE),
    re.compile(r"\bfuture\s+B-N\s+candidate\b", re.IGNORECASE),
    re.compile(r"\bBNcand-\d+\b"),
    re.compile(r"\bB-N\s+candidate\s+for\b", re.IGNORECASE),
)

_BACKLOG_BN_OPEN_RE = re.compile(
    r"^\+\s*(?:[-*]\s*)?\*\*B-(\d+)\*\*\s*\([^)]*?Open\b",
    re.MULTILINE,
)

_DISMISSAL_PHRASES = (
    "dismissed because",
    "dismissed per",
    "no b-n needed because",
    "no B-N needed because",
    "no B-N required because",
    "deferred to commit",
    "deferred to <commit",
    "deferred to next commit",
    "out of scope per",
    "already tracked by b-",
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


# Per B-488 closure 2026-05-18: shared context-sensitive false-positive
# suppression helper. Markers below were derived from empirical false-positive
# events at commits 133b212 (B-458 fired on quoted "B-414 CLOSED" empirical
# anchor → B-480 candidate) + c6ba969 (B-464 fired on quoted "62 skip"
# empirical anchor → B-487 candidate). Both events involved producer authoring
# commit-msg about a check whose canonical-anchor citation triggered the
# very pattern the check detects (self-reference meta-pattern).
_EMPIRICAL_ANCHOR_MARKERS: tuple[str, ...] = (
    "empirical anchor commit",
    "empirical anchor",
    "1st-event empirical anchor",
    "1st-event",
    "META-IRONY",
    "meta-irony",
    "historical reference",
    "historical context",
    "historical anchor",
    "Quote-cite from reviewer",
    "quote-cite from reviewer",
    "Mechanism A step 5",
    "per Cohort",
    "per cohort",
    "verbatim quote",
    "reviewer quote",
    "Reviewer cited",
    "reviewer cited",
)


def _is_empirical_anchor_context(
    lines: list[str], idx: int, lookback: int = 5,
) -> bool:
    """Per B-488 closure 2026-05-18: True if `lines[idx]` is within an
    empirical-anchor citation context (within `lookback` lines after a marker
    phrase like `empirical anchor commit`, `META-IRONY`, `Quote-cite from
    reviewer`, etc.).

    Used to suppress false-positive WARNs across heuristic checks
    (ClosureAnnotationConsistencyCheck + NarrativePytestClaimVerificationCheck
    + InlineFixClaimVerificationCheck) when commit-msg cites historical
    pattern instances rather than asserting current-commit claims.

    Empirical evidence base (3-event 2026-05-18):
        - commit 133b212: B-458 fired on `**B-414 CLOSED**` inside REVIEW-section
          quote-cite of prior reviewer's verdict (B-480 candidate)
        - commit c6ba969: B-464 fired on `2664 pass / 62 skip / 0 fail` inside
          empirical-anchor prose citing 1f74b72 META-IRONY (B-487 candidate)
        - latent: B-470 InlineFixClaimVerificationCheck has same vulnerability
          if commit-msg quotes a historical reviewer block

    Args:
        lines: split commit-msg lines (already sanitized via _strip_code_blocks).
        idx: target line index to evaluate.
        lookback: number of lines BEFORE idx to scan for markers (default 5).

    Returns:
        True if any line in `lines[idx-lookback:idx+1]` contains an empirical
        anchor marker (case-sensitive match against `_EMPIRICAL_ANCHOR_MARKERS`).
        False otherwise. Note: case-sensitive — `_EMPIRICAL_ANCHOR_MARKERS`
        includes both common case variants explicitly.
    """
    if idx < 0 or idx >= len(lines):
        return False
    lo = max(0, idx - lookback)
    window = lines[lo:idx + 1]
    for line in window:
        for marker in _EMPIRICAL_ANCHOR_MARKERS:
            if marker in line:
                return True
    return False


def check_unresolved_forward_prevention_candidates(
    commit_msg: str,
    staged_backlog_diff: str | None = None,
) -> tuple[bool, list[str]]:
    """Per B-451 closure: scan commit-msg for orphan-candidate phrasings +
    verify either matching BACKLOG opening OR explicit dismissal cited.

    Per B-459 (2026-05-18) this is a thin compatibility wrapper that
    delegates to `UnresolvedForwardPreventionCandidatesCheck().scan()`.
    Preserved as a top-level function for backward compatibility with
    existing Tier 0 tests (assertion 32) + external callers.

    Args:
        commit_msg: full commit-message text.
        staged_backlog_diff: optional pre-fetched git diff --cached output for
            docs/migration/BACKLOG.md; if None, attempts subprocess call.
            Pass empty string "" to indicate no BACKLOG.md staged.
    """
    if staged_backlog_diff is None:
        try:
            result = subprocess.run(
                ["git", "diff", "--cached", "docs/migration/BACKLOG.md"],
                capture_output=True, text=True, timeout=10, cwd=REPO_ROOT,
                encoding="utf-8",  # B-479: explicit UTF-8 for Windows-dev safety
            )
            staged_backlog_diff = result.stdout if result.returncode == 0 else ""
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            staged_backlog_diff = ""

    check = UnresolvedForwardPreventionCandidatesCheck()
    ctx = OrchestrationContext(
        staged_diffs={"docs/migration/BACKLOG.md": staged_backlog_diff},
        classification=None,
    )
    res = check.scan(commit_msg, ctx)
    return res.passed, res.findings


# =========================================================================
# B-459 closure: CommitMsgCheck subclass implementations
# =========================================================================


class ExemptionPhraseCheck(CommitMsgCheck):
    """Mechanism C-1 exemption-phrase detection per B-303 trigger-phrase list.

    Per `udm-exemption-verifier` SKILL.md L29-46: 12 trigger phrases that
    BLOCK the commit unless paired with reviewer-spawn.
    """
    name = "exemption_phrase"
    severity: Literal["WARN", "BLOCK"] = "BLOCK"
    requires_backlog_diff = False
    requires_classification = False  # per B-472: declares scan() does not read ctx.classification

    def scan(self, commit_msg: str, ctx: OrchestrationContext) -> CheckResult:
        if contains_exemption_phrase is None:
            return CheckResult(passed=True, findings=[])
        matched = contains_exemption_phrase(commit_msg)
        if matched:
            return CheckResult(passed=False, findings=list(matched))
        return CheckResult(passed=True, findings=[])

    def render_findings_to_stderr(self, findings: list[str]) -> None:
        """Per B-468: emit exemption-phrase BLOCK boilerplate with reviewer-spawn
        instruction footer (preserves pre-B-468 main() L650-663 verbatim text)."""
        print("[commit-msg BLOCKED] commit message contains exemption-claim "
              "trigger phrases:", file=sys.stderr)
        for p in findings:
            print(f"  - {p!r}", file=sys.stderr)
        print("\nPer Mechanism C-1 + udm-exemption-verifier SKILL.md: spawn "
              "udm-exemption-verifier reviewer (via Claude Code session) BEFORE "
              "committing. Reviewer verdict VALID -> proceed; INVALID -> spawn "
              "udm-gap-check per D56 second-pass; address findings; re-attempt "
              "commit.", file=sys.stderr)
        print("\nBypass with --no-verify is self-flagging exemption-claim that "
              "reviewers should treat as quasi-audit-question trigger.",
              file=sys.stderr)


class CascadeEvidenceCheck(CommitMsgCheck):
    """Hard rule 14 cascade-evidence detection per B-317 Phase 1A + B-321.

    Classifies commit; if cascade_required=True, verifies presence of
    `## TEST` + `## GAP ANALYSIS` + `## REVIEW` sections + body validation.

    Per B-467 (2026-05-18): reads `ctx.classification` instead of calling
    `classify_commit()` redundantly inside scan(). The orchestrator
    `_build_orchestration_context()` calls classify_commit() ONCE per main()
    invocation (when CascadeEvidenceCheck is in CHECKS registry).
    """
    name = "cascade_evidence"
    severity: Literal["WARN", "BLOCK"] = "BLOCK"
    requires_backlog_diff = False
    requires_classification = True  # per B-472: reads ctx.classification for cascade-required dispatch

    def scan(self, commit_msg: str, ctx: OrchestrationContext) -> CheckResult:
        if has_cascade_evidence is None:
            return CheckResult(passed=True, findings=[])
        cls = ctx.classification
        if cls is None or not cls.cascade_required:
            return CheckResult(passed=True, findings=[])
        has_ev, findings = has_cascade_evidence(
            commit_msg, classification=cls.classification,
        )
        if not has_ev:
            return CheckResult(
                passed=False,
                findings=[
                    f"hard rule 14 cascade-evidence missing or invalid per B-317 + B-321 "
                    f"(commit classified as {cls.classification}: {cls.rationale})"
                ] + list(findings),
            )
        return CheckResult(passed=True, findings=[])

    def render_findings_to_stderr(self, findings: list[str]) -> None:
        """Per B-468: emit cascade-evidence BLOCK boilerplate with required
        structure footer (preserves pre-B-468 main() L666-678 verbatim text)."""
        cascade_diag = findings[0] if findings else "cascade-evidence missing"
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


class PytestCountDisambiguationCheck(CommitMsgCheck):
    """B-449 pytest-count disambiguation WARN-only check.

    Scans TEST section for pytest counts cited WITHOUT a scope indicator
    (e.g., "tier0+tier1" / "full-suite" / "baseline preserved" / a pytest
    command line) within +/- 3 lines.
    """
    name = "pytest_count"
    severity: Literal["WARN", "BLOCK"] = "WARN"
    requires_backlog_diff = False
    requires_classification = False  # per B-472: scan() reads only TEST section text

    def scan(self, commit_msg: str, ctx: OrchestrationContext) -> CheckResult:
        test_text = _extract_test_section_text(commit_msg)
        if test_text is None:
            return CheckResult(passed=True, findings=[])

        sanitized = _strip_code_blocks(test_text)
        if not sanitized.strip():
            return CheckResult(passed=True, findings=[])

        lines = sanitized.splitlines()
        findings: list[str] = []
        seen_lines: set[int] = set()

        for i, line in enumerate(lines):
            matches = list(_PYTEST_COUNT_RE.finditer(line))
            if not matches:
                continue
            if i in seen_lines:
                continue
            lo, hi = max(0, i - 3), min(len(lines), i + 4)
            window = "\n".join(lines[lo:hi])
            if _has_scope_indicator(window):
                continue
            for m in matches:
                count_str = m.group(1)
                snippet = line.strip()[:120]
                findings.append(
                    f"pytest count {count_str!r} cited without scope indicator "
                    f"(line {i+1}): {snippet!r}"
                )
            seen_lines.add(i)

        if findings:
            return CheckResult(passed=False, findings=findings[:10])
        return CheckResult(passed=True, findings=[])

    def render_findings_to_stderr(self, findings: list[str]) -> None:
        """Per B-468: emit pytest-count WARN boilerplate with disambiguation
        examples footer (preserves pre-B-468 main() L681-696 verbatim text)."""
        print(f"\n[commit-msg WARN] {len(findings)} pytest count(s) "
              "cited without scope disambiguation in TEST section "
              "(per B-449; Agent 59 cycle-3 G3-K2 empirical anchor commit `e76078c`):",
              file=sys.stderr)
        for f in findings:
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


class UnresolvedForwardPreventionCandidatesCheck(CommitMsgCheck):
    """B-451 orphan forward-prevention candidate tracking WARN-only check.

    Scans GAP ANALYSIS + REVIEW + body for orphan-candidate phrases.
    For each unsuppressed match (code-block / blockquote exclusions), verifies
    EITHER (a) BACKLOG.md staged diff opens a NEW B-N OR (b) commit-msg
    cites explicit dismissal phrasing.
    """
    name = "orphan_candidate"
    severity: Literal["WARN", "BLOCK"] = "WARN"
    requires_backlog_diff = True
    requires_classification = False  # per B-472: reads BACKLOG staged-diff via ctx.staged_diffs, not classification

    def scan(self, commit_msg: str, ctx: OrchestrationContext) -> CheckResult:
        sanitized = _strip_code_blocks(commit_msg)
        if not sanitized.strip():
            return CheckResult(passed=True, findings=[])

        lines = sanitized.splitlines()
        orphan_matches: list[tuple[int, str, str]] = []

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
            return CheckResult(passed=True, findings=[])

        if _has_explicit_dismissal(sanitized):
            return CheckResult(passed=True, findings=[])

        staged_backlog_diff = ctx.staged_diffs.get("docs/migration/BACKLOG.md", "")
        backlog_opens_count = 0
        if staged_backlog_diff:
            backlog_opens_count = len(_BACKLOG_BN_OPEN_RE.findall(staged_backlog_diff))

        if backlog_opens_count >= len(orphan_matches):
            return CheckResult(passed=True, findings=[])

        findings: list[str] = []
        unmatched = len(orphan_matches) - backlog_opens_count
        for idx, (line_idx, snippet, _pat) in enumerate(orphan_matches[:10]):
            findings.append(
                f"orphan-candidate phrase cited (line {line_idx+1}): {snippet!r} "
                f"— {unmatched} unresolved (found {backlog_opens_count} new B-N "
                f"opening(s) in staged BACKLOG diff vs {len(orphan_matches)} "
                "candidate(s); no explicit dismissal cited)"
            )
        return CheckResult(passed=False, findings=findings)

    def render_findings_to_stderr(self, findings: list[str]) -> None:
        """Per B-468: emit orphan-candidate WARN boilerplate with resolution-options
        footer (preserves pre-B-468 main() L699-714 verbatim text)."""
        print(f"\n[commit-msg WARN] {len(findings)} orphan "
              "forward-prevention candidate(s) cited in commit-msg without "
              "matching BACKLOG.md staged entry "
              "(per B-451; Agent 59 cycle-3 G2-A empirical anchor commit `e76078c`):",
              file=sys.stderr)
        for f in findings:
            print(f"  - {f}", file=sys.stderr)
        print("\nResolution options:", file=sys.stderr)
        print("  - Open a corresponding B-N entry in docs/migration/BACKLOG.md "
              "(add to staged diff)", file=sys.stderr)
        print("  - Cite explicit dismissal in commit-msg ('dismissed because X' / "
              "'no B-N needed because Y' / 'deferred to commit abc1234')", file=sys.stderr)
        print("This is a WARN (not BLOCK); commit will still proceed. "
              "Escalation to BLOCK reserved for pipeline-lead post-baseline period.",
              file=sys.stderr)


# -------------------------------------------------------------------------
# B-470 closure: PRE-COMMIT reviewer inline-fix claim verification
# -------------------------------------------------------------------------
# Empirical evidence base (2-event 2026-05-18):
#   - Commit 2a33efa: Agent 70 cited B-459 leading-badge fix applied; file
#     state still rendered "🟡 Open" inside strikethrough (Agent 71 catch at
#     7eef2ef). Root cause: prior Edit overwritten by subsequent re-Read+
#     re-Edit cycles in producer workflow.
#   - Commit 20d998f: Agent 74 cited 3 inline fixes; 2 of 3 did NOT land
#     (B-465 leading-badge + GLOSSARY L769 signature update; Agent 75 catch
#     at 9775340).
# Forward-prevention: parse reviewer-block numbered-fix claims + verify each
# claim's "after" pattern in staged content of target file. WARN-only per
# WSJF MEDIUM contract (matches B-449 + B-451). Escalation to BLOCK reserved
# for pipeline-lead post-baseline period.

# Reviewer-block header. Tolerant: optional "Independent" prefix; optional
# "pre-commit" / "PRE-COMMIT" qualifier; optional parenthesized hex agentId.
_REVIEWER_BLOCK_HEADER_RE = re.compile(
    r"(?:Independent\s+)?(?:pre-commit\s+|PRE-COMMIT\s+)?(?:independent\s+)?"
    r"reviewer\s+Agent\s+\d+(?:\s*\([0-9a-fA-F]{6,}\))?",
    re.IGNORECASE,
)

_NUMBERED_FIX_RE = re.compile(r"^\s*(?P<num>\d+)\.\s+(?P<body>.+)$")

_PITFALL_MARKER_RE = re.compile(
    r"Pitfall\s+#?9\.(?P<letter>[a-o])",
    re.IGNORECASE,
)

_BN_REF_RE = re.compile(r"B-(\d+)")

# Generic transition pattern with → arrow + quoted before/after (curly+straight
# quotes). The lazy prose-matchers between quote-closes and the arrow allow
# patterns like `pre-B-467 "old" → post-B-467 "new"` (canonical form per
# forensic analysis of commits 2a33efa + 20d998f).
_TRANSITION_RE = re.compile(
    r"[\"“‘`](?P<old>[^\"”’`\n]+?)[\"”’`]"
    r"[^\"”’`\n]*?"
    r"(?:→|->)"
    r"[^\"”’`\n]*?"
    r"[\"“‘`](?P<new>[^\"”’`\n]+?)[\"”’`]"
)

# Per B-477 closure 2026-05-18: missing_entries kind verification (Pitfall #9.n
# claim class). Canonical claim format extracted from forensic analysis of
# commit 20d998f Fix #3: "GLOSSARY missing 2 NEW B-467 surfaces (OrchestrationContext
# + _build_orchestration_context) — added 2 entries after REPO_ROOT row".
# Regex captures the parenthesized ident-list. Identifiers separated by
# whitespace + "+" / "," / ";" / " and ". Tolerates Unicode dash "—" / "–".
_MISSING_ENTRIES_RE = re.compile(
    r"missing\s+\d+\s+(?:NEW\s+)?(?:[\w-]+\s+)?surfaces?\s*"
    r"\((?P<ident_list>[^)]+)\)",
    re.IGNORECASE,
)

# Per B-477: split identifier list into individual identifier tokens.
# Accepts " + " / " , " / " ; " / " and " separators; strips backticks.
_IDENT_SEPARATOR_RE = re.compile(r"\s*(?:[+,;]|\band\b)\s*")

# Canonical filename → repo path. Longer (".md") forms first so they win
# substring match before bare name.
_CANONICAL_FILE_PATHS: tuple[tuple[str, str], ...] = (
    ("BACKLOG.md", "docs/migration/BACKLOG.md"),
    ("GLOSSARY.md", "docs/migration/GLOSSARY.md"),
    ("CURRENT_STATE.md", "docs/migration/CURRENT_STATE.md"),
    ("HANDOFF.md", "docs/migration/HANDOFF.md"),
    ("SESSION_RESUME.md", "SESSION_RESUME.md"),
    ("CLAUDE.md", "CLAUDE.md"),
    ("BACKLOG", "docs/migration/BACKLOG.md"),
    ("GLOSSARY", "docs/migration/GLOSSARY.md"),
    ("CURRENT_STATE", "docs/migration/CURRENT_STATE.md"),
    ("HANDOFF", "docs/migration/HANDOFF.md"),
    ("SESSION_RESUME", "SESSION_RESUME.md"),
    ("CLAUDE", "CLAUDE.md"),
)


def _extract_reviewer_block(commit_msg: str) -> str:
    """Return the substring of `commit_msg` starting at the first reviewer-
    block header. Empty string if no header found."""
    match = _REVIEWER_BLOCK_HEADER_RE.search(commit_msg)
    if not match:
        return ""
    return commit_msg[match.start():]


def _resolve_target_path(fix_body: str) -> str | None:
    """Identify the canonical target file referenced in a fix-body line.

    Longest filename token wins (".md" form preferred over bare name)."""
    for name, path in _CANONICAL_FILE_PATHS:
        if name in fix_body:
            return path
    return None


def _fetch_staged_content(path: str) -> str:
    """Fetch staged-content for `path` via `git show :<path>`. Returns ""
    on failure (file not staged OR git unavailable). Caller MUST cache;
    each call spawns a subprocess."""
    try:
        result = subprocess.run(
            ["git", "show", f":{path}"],
            capture_output=True, text=True, check=False, timeout=10,
            cwd=REPO_ROOT,
            encoding="utf-8",  # B-479: explicit UTF-8 for Windows-dev safety (else system codepage CP1252 default would mangle Unicode markers in target file content)
        )
        return result.stdout if result.returncode == 0 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


def _parse_inline_fix_claims(reviewer_block: str) -> list[dict]:
    """Parse numbered fix items from reviewer-block. Returns a list of dicts
    keyed by:
        fix_num: int — 1-based numbered item index
        raw_body: str — concatenated fix-body lines
        kind: str — "badge_flip" | "transition" | "missing_entries" | "unknown"
        before: str | None — parsed "before" pattern (transition kind only)
        after: str | None — parsed "after" pattern (transition kind only)
        bn: str | None — B-N identifier referenced in fix-body (e.g., "B-465")
        target_path: str | None — canonical repo path inferred from fix-body
    """
    claims: list[dict] = []
    current: dict | None = None
    current_body_lines: list[str] = []

    def _finalize() -> None:
        nonlocal current, current_body_lines
        if current is None:
            return
        joined = " ".join(current_body_lines)
        current["raw_body"] = joined
        # Parse "before → after" transition (first match)
        m = _TRANSITION_RE.search(joined)
        if m:
            current["before"] = m.group("old")
            current["after"] = m.group("new")
        else:
            current["before"] = None
            current["after"] = None
        # Classify by Pitfall marker
        pit = _PITFALL_MARKER_RE.search(joined)
        if pit:
            letter = pit.group("letter").lower()
            if letter == "j":
                current["kind"] = "badge_flip"
            elif letter == "n":
                current["kind"] = "missing_entries"
            elif letter in ("k", "l"):
                current["kind"] = "transition"
            else:
                current["kind"] = "transition" if current["after"] else "unknown"
        elif "leading badge" in joined.lower():
            current["kind"] = "badge_flip"
        elif current.get("after"):
            current["kind"] = "transition"
        else:
            current["kind"] = "unknown"
        # B-N reference (for badge_flip anchoring)
        bn_m = _BN_REF_RE.search(joined)
        current["bn"] = ("B-" + bn_m.group(1)) if bn_m else None
        # Target file path
        current["target_path"] = _resolve_target_path(joined)
        claims.append(current)
        current = None
        current_body_lines = []

    lines = reviewer_block.splitlines()
    for line in lines:
        m = _NUMBERED_FIX_RE.match(line)
        if m:
            _finalize()
            current = {"fix_num": int(m.group("num"))}
            current_body_lines = [m.group("body")]
        else:
            stripped = line.strip()
            if current is not None and stripped:
                current_body_lines.append(stripped)
            elif current is not None and not stripped:
                # Blank line ends the current fix block
                _finalize()
    _finalize()
    return claims


class InlineFixClaimVerificationCheck(CommitMsgCheck):
    """B-470 closure (2026-05-18; 2-event evidence base): verify each
    PRE-COMMIT reviewer inline-fix claim in commit-msg actually landed in
    staged file content.

    Empirical anchors:
        - Commit 2a33efa (Agent 70 claim; Agent 71 catch at 7eef2ef)
        - Commit 20d998f (Agent 74 claim; Agent 75 catch at 9775340)

    Detection logic (heuristic; WARN-only):
        - Find reviewer-block by header regex.
        - Parse numbered fix items + classify by Pitfall #9.X letter.
        - For Pitfall #9.j badge_flip: verify staged BACKLOG.md does NOT
          contain `**B-NNN** (🟡 Open` for the cited B-N.
        - For Pitfall #9.k / #9.l transition: verify "after" pattern is
          present in staged target file (basic substring check).

    Severity: WARN per WSJF MEDIUM (matches B-449 + B-451 contract).
    """
    name = "inline_fix_claim"
    severity: Literal["WARN", "BLOCK"] = "WARN"
    requires_backlog_diff = False
    requires_classification = False

    def scan(self, commit_msg: str, ctx: OrchestrationContext) -> CheckResult:
        reviewer_block = _extract_reviewer_block(commit_msg)
        if not reviewer_block:
            return CheckResult(passed=True, findings=[])
        claims = _parse_inline_fix_claims(reviewer_block)
        if not claims:
            return CheckResult(passed=True, findings=[])

        findings: list[str] = []
        staged_cache: dict[str, str] = {}

        for claim in claims:
            target = claim.get("target_path")
            kind = claim.get("kind")
            if kind == "unknown" or target is None:
                # Unverifiable claim — skip silently per WARN heuristic.
                continue
            if target not in staged_cache:
                staged_cache[target] = _fetch_staged_content(target)
            content = staged_cache[target]
            if not content:
                # File not in staged index — cannot verify; skip silently.
                continue

            if kind == "badge_flip":
                bn = claim.get("bn")
                if not bn:
                    continue
                # Pitfall #9.j: leading-badge stale. Check `**B-NNN** (🟡 Open`
                # is NOT present in staged file (the fix should have flipped
                # it to ⚫ CLOSED).
                old_leading_badge = f"**{bn}** (🟡 Open"
                if old_leading_badge in content:
                    findings.append(
                        f"Fix #{claim['fix_num']} (badge_flip) claims "
                        f"{bn} leading badge flipped to ⚫ CLOSED in {target}, "
                        f"but staged content still contains '{old_leading_badge}'. "
                        f"Likely Edit-overwrite drift per B-470 closure 2026-05-18 "
                        f"(2-event evidence base: commits 2a33efa + 20d998f). "
                        f"Re-apply via Edit + verify via grep BEFORE staging."
                    )
            elif kind == "transition":
                after = claim.get("after")
                if not after or len(after) < 4:
                    # Skip very short "after" patterns (high false-positive risk)
                    continue
                if after not in content:
                    findings.append(
                        f"Fix #{claim['fix_num']} (transition) claims "
                        f"'{after}' applied to {target} but staged content "
                        f"does not contain this pattern. "
                        f"Likely Edit-overwrite drift per B-470 closure 2026-05-18 "
                        f"(2-event evidence base: commits 2a33efa + 20d998f). "
                        f"Re-apply via Edit + verify via grep BEFORE staging."
                    )
            elif kind == "missing_entries":
                # Per B-477 closure 2026-05-18: Pitfall #9.n claim class
                # verification. Parse ident-list from raw_body via
                # `_MISSING_ENTRIES_RE`; verify each identifier appears in
                # staged target file content. WARN per missing identifier.
                raw_body = claim.get("raw_body", "")
                m = _MISSING_ENTRIES_RE.search(raw_body)
                if not m:
                    # No parseable ident-list — silently skip per WARN heuristic
                    continue
                ident_list_str = m.group("ident_list")
                # Split on common separators; strip backticks/whitespace.
                idents = [
                    tok.strip().strip("`").strip()
                    for tok in _IDENT_SEPARATOR_RE.split(ident_list_str)
                    if tok.strip()
                ]
                missing_idents: list[str] = []
                for ident in idents:
                    if not ident or len(ident) < 3:
                        # Skip very short tokens (high false-positive risk)
                        continue
                    if ident not in content:
                        missing_idents.append(ident)
                if missing_idents:
                    findings.append(
                        f"Fix #{claim['fix_num']} (missing_entries) claims "
                        f"{len(idents)} identifier(s) added to {target} "
                        f"but {len(missing_idents)} are NOT present in staged "
                        f"content: {missing_idents!r}. "
                        f"Likely Edit-overwrite drift per B-477 closure 2026-05-18 "
                        f"(Pitfall #9.n claim class; empirical 1-event anchor: "
                        f"commit 20d998f Fix #3 GLOSSARY 2 NEW B-467 surfaces). "
                        f"Re-apply via Edit + verify via grep BEFORE staging."
                    )

        if findings:
            return CheckResult(passed=False, findings=findings[:10])
        return CheckResult(passed=True, findings=[])

    def render_findings_to_stderr(self, findings: list[str]) -> None:
        """Per B-468: emit inline-fix WARN boilerplate with grep-verify
        recommendation footer."""
        print(
            f"\n[commit-msg WARN] {len(findings)} inline-fix claim(s) in "
            "commit-msg do NOT match staged file content "
            "(per B-470; 2-event evidence base: Agent 70 + Agent 74 at "
            "commits 2a33efa + 20d998f):",
            file=sys.stderr,
        )
        for f in findings:
            print(f"  - {f}", file=sys.stderr)
        print("\nResolution options:", file=sys.stderr)
        print(
            "  - Re-apply the cited fix via Edit + verify via grep BEFORE re-staging",
            file=sys.stderr,
        )
        print(
            "  - Update the commit-msg claim wording to match the actual diff state",
            file=sys.stderr,
        )
        print(
            "  - Cite explicit dismissal if the claim was withdrawn",
            file=sys.stderr,
        )
        print(
            "This is a WARN (not BLOCK); commit will still proceed. "
            "Escalation to BLOCK reserved for pipeline-lead post-baseline period.",
            file=sys.stderr,
        )


# -------------------------------------------------------------------------
# B-458 closure: retrospective closure-annotation-consistency check
# -------------------------------------------------------------------------
# Empirical anchor commit `20fe33a` (Phase 1 R1 R3 audit retrospective):
# subject + body claimed `**B-409 CLOSED**` + `**B-414 CLOSED**` but staged
# BACKLOG.md diff applied closure annotation ONLY to B-408. Required Agent
# 58 gap-check + e76078c remediation cycle to backfill the missing B-409
# and B-414 closure annotations.
#
# Composes with B-451 as orthogonal failure-mode coverage:
#   - B-451 catches FORWARD-LOOKING orphan-candidate phrasings
#     (e.g., "deferred (B-N candidate for X)") that need new B-N openings
#   - B-458 catches RETROSPECTIVE "B-N CLOSED" claims that need existing
#     B-N closure annotations
# Both are WARN-only Mechanism C-1 extensions per WSJF MEDIUM contract.

# Claim regex: matches either bold form `**B-NNN CLOSED**` OR bare form
# `B-NNN CLOSED` / `B-NNN ⚫ CLOSED`. Case-insensitive on CLOSED literal.
_CLOSURE_CLAIM_RE = re.compile(
    r"\*\*B-(\d+)\s+CLOSED\*\*"
    r"|"
    r"\bB-(\d+)\s+(?:⚫\s*)?CLOSED\b",
    re.IGNORECASE,
)

# BACKLOG closure-annotation regex: matches `+ ` diff line containing the
# canonical leading-badge form `**B-NNN** (⚫ CLOSED`. The `+` prefix marks
# git-diff additions; MULTILINE mode anchors `^\+` per line in the full diff.
_BACKLOG_CLOSURE_ANNOTATION_RE = re.compile(
    r"^\+.*\*\*B-(\d+)\*\*\s*\(\s*⚫\s*CLOSED",
    re.MULTILINE,
)

# Per B-478 closure 2026-05-18: shared-CLOSED chain detection regex.
# Matches a single B-N reference (e.g., "B-409") for back-walk through
# prefix when shared-CLOSED pattern like "B-409 + B-414 CLOSED" is detected.
_BN_REFERENCE_RE = re.compile(r"\bB-(\d+)\b")

# Per B-478 closure 2026-05-18: valid chain separators between B-N references
# in a shared-CLOSED pattern. Supports `+` / `,` / `;` / `&` / ` and ` /
# ` AND `. Whitespace-flexible. Empirical anchor commit `20fe33a` used `+`.
_SHARED_CLOSED_SEPARATOR_RE = re.compile(
    r"^\s*(?:[+,;&]|\band\b)\s*$",
    re.IGNORECASE,
)


class ClosureAnnotationConsistencyCheck(CommitMsgCheck):
    """B-458 closure (2026-05-18): retrospective-closure-without-BACKLOG-
    annotation drift detection.

    Empirical anchor: commit `20fe33a` claimed `**B-409 CLOSED**` +
    `**B-414 CLOSED**` in subject + body but staged BACKLOG.md diff
    applied closure annotation ONLY to B-408. Required Agent 58
    gap-check + e76078c remediation cycle to backfill.

    Detection logic (heuristic; WARN-only):
        - Sanitize commit-msg (strip code blocks via `_strip_code_blocks`;
          skip blockquote lines via `_is_inside_blockquote`).
        - Find all `B-NNN CLOSED` claims via `_CLOSURE_CLAIM_RE`.
        - Find all `**B-NNN** (⚫ CLOSED` annotations in BACKLOG.md staged
          diff via `_BACKLOG_CLOSURE_ANNOTATION_RE`.
        - WARN per claimed B-N that lacks corresponding staged annotation.

    Severity: WARN per WSJF MEDIUM (matches B-449 + B-451 + B-470 contract).
    Orthogonal-failure-mode complement to B-451 orphan-candidate forward-
    prevention — composes via shared `_collect_staged_diffs` BACKLOG-diff
    batching (requires_backlog_diff=True).
    """
    name = "closure_annotation"
    severity: Literal["WARN", "BLOCK"] = "WARN"
    requires_backlog_diff = True
    requires_classification = False

    def scan(self, commit_msg: str, ctx: OrchestrationContext) -> CheckResult:
        sanitized = _strip_code_blocks(commit_msg)
        if not sanitized.strip():
            return CheckResult(passed=True, findings=[])

        # Extract claimed B-N closures from commit-msg (skip blockquote lines
        # to avoid quoted-reviewer-output false positives).
        lines = sanitized.splitlines()
        claimed: dict[str, int] = {}  # bn -> 1-based line number
        for i, line in enumerate(lines):
            if _is_inside_blockquote(lines, i):
                continue
            # Per B-488 closure 2026-05-18: skip claims within empirical-anchor
            # citation context (closes self-reference meta-pattern; absorbs
            # B-480 candidate)
            if _is_empirical_anchor_context(lines, i):
                continue
            for m in _CLOSURE_CLAIM_RE.finditer(line):
                bn_num = m.group(1) or m.group(2)
                if bn_num:
                    bn = f"B-{bn_num}"
                    if bn not in claimed:
                        claimed[bn] = i + 1
                    # Per B-478 closure 2026-05-18: shared-CLOSED chain
                    # detection. When bare-form matches "B-414 CLOSED" but the
                    # commit-msg cites "B-409 + B-414 CLOSED" (canonical
                    # 20fe33a pattern), the bare-form regex only catches the
                    # B-N adjacent to "CLOSED" (B-414). Walk backward through
                    # the prefix to capture preceding B-N references that are
                    # separated from the matched B-N by canonical chain
                    # separators (+ / , / ; / & / and). Bold-form `**B-NNN
                    # CLOSED**` does not chain (each is independently bolded).
                    if m.group(2):  # bare-form match (group 2 = bare B-N)
                        prefix = line[: m.start()]
                        prev_matches = list(_BN_REFERENCE_RE.finditer(prefix))
                        last_pos = m.start()
                        for prev_match in reversed(prev_matches):
                            between = line[prev_match.end() : last_pos]
                            if _SHARED_CLOSED_SEPARATOR_RE.match(between):
                                prev_bn = f"B-{prev_match.group(1)}"
                                if prev_bn not in claimed:
                                    claimed[prev_bn] = i + 1
                                last_pos = prev_match.start()
                            else:
                                break  # chain broken; stop walking back

        if not claimed:
            return CheckResult(passed=True, findings=[])

        # Fetch BACKLOG.md staged diff from ctx (collected by
        # _collect_staged_diffs since requires_backlog_diff=True).
        backlog_diff = ctx.staged_diffs.get("docs/migration/BACKLOG.md", "")
        if not backlog_diff:
            # No BACKLOG.md staged — cannot verify; silently skip per
            # conservative WARN heuristic.
            return CheckResult(passed=True, findings=[])

        annotated: set[str] = set()
        for m in _BACKLOG_CLOSURE_ANNOTATION_RE.finditer(backlog_diff):
            annotated.add(f"B-{m.group(1)}")

        unannotated = sorted(
            set(claimed) - annotated, key=lambda x: int(x.split("-")[1]),
        )
        if not unannotated:
            return CheckResult(passed=True, findings=[])

        findings: list[str] = []
        for bn in unannotated[:10]:
            line_num = claimed[bn]
            findings.append(
                f"{bn} CLOSED claim cited in commit-msg (line {line_num}) "
                f"but BACKLOG.md staged diff does NOT contain corresponding "
                f"`**{bn}** (⚫ CLOSED` closure annotation. "
                f"Empirical anchor commit `20fe33a` per B-458 closure 2026-05-18. "
                f"Either (a) stage the BACKLOG.md closure annotation for {bn} "
                f"OR (b) remove the CLOSED claim if premature."
            )
        return CheckResult(passed=False, findings=findings)

    def render_findings_to_stderr(self, findings: list[str]) -> None:
        """Per B-468: emit closure-annotation WARN boilerplate with
        resolution-options footer."""
        print(
            f"\n[commit-msg WARN] {len(findings)} retrospective B-N CLOSED "
            "claim(s) in commit-msg without corresponding BACKLOG.md closure "
            "annotation in staged diff "
            "(per B-458; 1st-event empirical anchor commit `20fe33a`):",
            file=sys.stderr,
        )
        for f in findings:
            print(f"  - {f}", file=sys.stderr)
        print("\nResolution options:", file=sys.stderr)
        print(
            "  - Stage the BACKLOG.md closure annotation "
            "(~~strikethrough~~ + `**B-NNN** (⚫ CLOSED YYYY-MM-DD; ...)`) "
            "for each cited B-N",
            file=sys.stderr,
        )
        print(
            "  - Remove the CLOSED claim from commit-msg if premature "
            "(reverts to pending-state phrasing)",
            file=sys.stderr,
        )
        print(
            "This is a WARN (not BLOCK); commit will still proceed. "
            "Escalation to BLOCK reserved for pipeline-lead post-baseline period.",
            file=sys.stderr,
        )


# -------------------------------------------------------------------------
# B-464 closure: narrative pytest-claim verification (skip-count anomaly)
# -------------------------------------------------------------------------
# Empirical anchor commit `1f74b72` (META-IRONY surfaced by Agent 69 2026-05-18):
# narrative cited "2664 pass / 62 skip" in 4 locations but actual cascade
# scope (tier0+tier1+unit+property+regression) returns "2664 pass / 10 skip".
# The PASS count was correct; the SKIP count was wrong by 6.2x. Root cause:
# copy-paste of stale narrative from prior commit before the test suite's
# skip-count baseline changed.
#
# This check composes with B-449 (pytest-count scope-disambiguation) as
# orthogonal failure-mode coverage:
#   - B-449 catches pytest counts WITHOUT scope-indicator (ambiguity)
#   - B-464 catches pytest counts WITH anomalous skip-count (accuracy)
#
# Heuristic strategy: hardcoded skip-count threshold = 20 (2x current
# baseline 10). False-positive rate near zero since project's actual skip
# count grows slowly. Future B-N may add subprocess-baseline verification
# (run `pytest --collect-only -q` at commit time + parse "N collected").
# Current heuristic is bounded-cost (regex-only); subprocess approach has
# ~5-10s overhead per commit which exceeds reasonable hook latency.

# Regex extracts `N pass / M skip [/ K fail]` patterns. The "/" separator
# is canonical per project convention; tolerates whitespace variation.
# Captures pass-count + skip-count for threshold check.
_PYTEST_FULL_TRIPLET_RE = re.compile(
    r"\b(?P<pass>\d{2,5})\s*(?:pass(?:ed)?|PASS(?:ED)?)"
    r"\s*[/,]\s*"
    r"(?P<skip>\d{1,4})\s*(?:skip(?:ped)?|SKIP(?:PED)?)"
    r"(?:\s*[/,]\s*(?P<fail>\d{1,3})\s*(?:fail(?:ed|ing)?|FAIL(?:ED)?))?",
    re.IGNORECASE,
)

# Skip-count anomaly threshold. Project's actual baseline at 2026-05-18 is
# 10 skipped (tier0+tier1+unit+property+regression scope). Threshold = 20
# permits 2x baseline before WARN; catches 1f74b72-class drift (62 cited).
#
# Per B-486 closure 2026-05-18: env-configurable via PYTEST_SKIP_ANOMALY_THRESHOLD
# operator-override. Defaults to canonical 20; allows accommodation of organic
# project growth (e.g., Tier 4 crash-tests landing on Linux CI add ~52 skips)
# without code edit. Invalid env values (non-int) silently fall back to default.
def _resolve_pytest_skip_threshold() -> int:
    """Per B-486 closure 2026-05-18: parse PYTEST_SKIP_ANOMALY_THRESHOLD env
    var with graceful fallback. Returns canonical 20 on absent / invalid value."""
    raw = os.environ.get("PYTEST_SKIP_ANOMALY_THRESHOLD", "20")
    try:
        value = int(raw)
        if value < 0:
            return 20  # negative threshold nonsensical; fall back to canonical
        return value
    except (ValueError, TypeError):
        return 20


_PYTEST_SKIP_ANOMALY_THRESHOLD = _resolve_pytest_skip_threshold()


class NarrativePytestClaimVerificationCheck(CommitMsgCheck):
    """B-464 closure (2026-05-18): narrative pytest-claim verification —
    catches anomalously high skip-counts indicating copy-paste-stale
    narrative or arithmetic error.

    Empirical anchor: commit `1f74b72` cited `2664 pass / 62 skip` in 4
    locations but actual cascade Step 3.1 scope returned `2664 pass /
    10 skip`. The 62 was a copy-paste from a prior pytest run with
    different scope (likely including Tier 4 crash-tests which add ~52
    module-level skips on dev workstations).

    Detection logic (heuristic; WARN-only):
        - Sanitize commit-msg via `_strip_code_blocks` (preserves canonical
          B-449/B-451/B-458 pattern).
        - Find `N pass / M skip [/ K fail]` triplet patterns.
        - WARN per match where `M > _PYTEST_SKIP_ANOMALY_THRESHOLD` (20).
        - Cite empirical anchor + suggest re-verification.

    Severity: WARN per WSJF MEDIUM (matches B-449 + B-451 + B-470 + B-458
    contract). Conservative threshold (2x baseline) keeps false-positive
    rate near zero; project's actual skip count is stable at ~10.

    Composes orthogonally with B-449 PytestCountDisambiguationCheck —
    B-449 catches missing-scope; B-464 catches anomalous-value.
    """
    name = "narrative_pytest_claim"
    severity: Literal["WARN", "BLOCK"] = "WARN"
    requires_backlog_diff = False
    requires_classification = False

    def scan(self, commit_msg: str, ctx: OrchestrationContext) -> CheckResult:
        sanitized = _strip_code_blocks(commit_msg)
        if not sanitized.strip():
            return CheckResult(passed=True, findings=[])

        # Iterate per-line so we can report line numbers (helpful diagnostic)
        lines = sanitized.splitlines()
        findings: list[str] = []
        seen_lines: set[int] = set()

        for i, line in enumerate(lines):
            if _is_inside_blockquote(lines, i):
                continue
            # Per B-488 closure 2026-05-18: skip claims within empirical-anchor
            # citation context (closes self-reference meta-pattern; absorbs
            # B-487 candidate)
            if _is_empirical_anchor_context(lines, i):
                continue
            for m in _PYTEST_FULL_TRIPLET_RE.finditer(line):
                skip_count = int(m.group("skip"))
                if skip_count <= _PYTEST_SKIP_ANOMALY_THRESHOLD:
                    continue
                if i in seen_lines:
                    continue
                seen_lines.add(i)
                snippet = line.strip()[:120]
                findings.append(
                    f"pytest skip-count {skip_count!r} (line {i+1}) exceeds "
                    f"anomaly threshold {_PYTEST_SKIP_ANOMALY_THRESHOLD} "
                    f"(project baseline ~10 for full-suite scope). "
                    f"Empirical anchor commit `1f74b72` per B-464 closure "
                    f"2026-05-18 — META-IRONY pattern (62 skip cited / 10 "
                    f"actual). Re-verify via `pytest -q --no-header | tail -3` "
                    f"on cited scope OR update narrative to match actual count. "
                    f"Snippet: {snippet!r}"
                )

        if findings:
            return CheckResult(passed=False, findings=findings[:10])
        return CheckResult(passed=True, findings=[])

    def render_findings_to_stderr(self, findings: list[str]) -> None:
        """Per B-468: emit narrative-pytest-claim WARN boilerplate with
        re-verification recommendation footer."""
        print(
            f"\n[commit-msg WARN] {len(findings)} pytest count claim(s) with "
            "anomalously high skip-count in commit-msg "
            "(per B-464; 1st-event empirical anchor commit `1f74b72`):",
            file=sys.stderr,
        )
        for f in findings:
            print(f"  - {f}", file=sys.stderr)
        print("\nResolution options:", file=sys.stderr)
        print(
            "  - Re-verify pytest counts: "
            "`.venv/Scripts/python.exe -m pytest tests/tier0 tests/tier1 "
            "tests/unit tests/property tests/regression -q --no-header 2>&1 "
            "| tail -3`",
            file=sys.stderr,
        )
        print(
            "  - Update narrative to match actual count (likely copy-paste "
            "from prior commit before suite grew)",
            file=sys.stderr,
        )
        print(
            "  - If skip-count is legitimately high (e.g., Tier 4 crash-tests "
            "included), cite explicit scope (e.g., 'with-crash-tier')",
            file=sys.stderr,
        )
        print(
            "This is a WARN (not BLOCK); commit will still proceed. "
            "Escalation to BLOCK reserved for pipeline-lead post-baseline period.",
            file=sys.stderr,
        )


# CHECKS registry per B-459 — single point of registration for orchestrator.
# Order matters only for stderr-emission deterministic display; audit-row
# JSON keys are independent.
CHECKS: list[CommitMsgCheck] = [
    ExemptionPhraseCheck(),
    CascadeEvidenceCheck(),
    PytestCountDisambiguationCheck(),
    UnresolvedForwardPreventionCandidatesCheck(),
    InlineFixClaimVerificationCheck(),  # B-470 closure 2026-05-18
    ClosureAnnotationConsistencyCheck(),  # B-458 closure 2026-05-18
    NarrativePytestClaimVerificationCheck(),  # B-464 closure 2026-05-18
]


def _emit_audit_row(
    commit_msg_path: Path,
    findings_by_check: dict[str, list[str]],
    exit_code: int,
    classification: str | None = None,
) -> None:
    """Per-invocation audit row per D76 + B-306 + B-317 + B-449 + B-459.

    Per B-459 (2026-05-18; Agent 68 design review Scope 2 Concern 2.1):
    audit-row payload uses unified `findings: dict[str, list[str]]` field
    keyed by check.name (replaces per-check top-level fields
    `pytest_count_findings` + `orphan_candidate_findings`). For backward-
    compatibility with forensic-audit tooling + Tier 0 tests that grep on
    pre-existing top-level keys, the per-check keys are ALSO mirrored at
    top-level — the unified `findings` dict is additive, not breaking.

    Audit-row schema:
        event_type: str  (CLI_CHECK_COMMIT_MSG per D76)
        ts: ISO8601 UTC
        commit_msg_path: str
        matched_phrases: list[str]  (mirror of findings["exemption_phrase"])
        classification: str | None  (commit classification per cascade_classifier)
        missing_sections: list[str]  (mirror of findings["cascade_evidence"])
        pytest_count_findings: list[str]  (mirror of findings["pytest_count"])
        orphan_candidate_findings: list[str]  (mirror of findings["orphan_candidate"])
        findings: dict[str, list[str]]  (unified B-459 keyed-by-check-name)
        exit_code: int
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
        # Per-check top-level mirrors preserved for backward compatibility:
        "matched_phrases": findings_by_check.get("exemption_phrase", []),
        "classification": classification,
        "missing_sections": findings_by_check.get("cascade_evidence", []),
        "pytest_count_findings": findings_by_check.get("pytest_count", []),
        "orphan_candidate_findings": findings_by_check.get("orphan_candidate", []),
        # B-459 unified field — primary lookup-by-check-name:
        "findings": findings_by_check,
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

    # Strip git-comment lines ("# <text>" or bare "#") but preserve markdown
    # multi-hash headers ("## TEST" / "### Section"). Per B-317 Phase 1A: the
    # cascade-evidence section detector requires markdown headers to survive
    # comment stripping.
    def _is_git_comment(line: str) -> bool:
        stripped = line.lstrip()
        if not stripped.startswith("#"):
            return False
        if stripped.rstrip() == "#":
            return True
        return stripped.startswith("# ")
    non_comment_lines = [
        line for line in commit_msg.splitlines() if not _is_git_comment(line)
    ]
    actual_msg = "\n".join(non_comment_lines)

    # Per B-459 — orchestrator iterates CHECKS registry rather than calling
    # each check function inline. Findings collected by check.name; only
    # severity=BLOCK contributes to final exit code.
    #
    # Per B-467 (2026-05-18) — `_build_orchestration_context()` batches both
    # staged_diffs + classification ONCE per main() invocation. Previously
    # main() called classify_commit() separately for audit-row metadata AND
    # CascadeEvidenceCheck.scan() called it again — 2 subprocess invocations
    # per run. Now both share the cached classification via ctx.classification.
    ctx = _build_orchestration_context(CHECKS)

    findings_by_check: dict[str, list[str]] = {}
    block_exit = EXIT_SUCCESS

    for check in CHECKS:
        try:
            result = check.scan(actual_msg, ctx)
        except Exception as exc:  # noqa: BLE001 — degrade gracefully on any check failure
            print(f"[commit-msg WARN] {check.name} check raised ({exc}); "
                  "check skipped this commit.", file=sys.stderr)
            continue
        if not result.passed:
            findings_by_check[check.name] = result.findings
            if check.severity == "BLOCK":
                block_exit = EXIT_BLOCKED

    if not no_audit:
        _emit_audit_row(
            commit_msg_path,
            findings_by_check,
            block_exit,
            classification=ctx.classification.classification if ctx.classification else None,
        )

    # Per-check stderr emission per B-468 (2026-05-18; Agent 72 Concern 1.3):
    # registry-iteration pattern replaces 4-way copy-paste. Each subclass owns
    # its WARN/BLOCK boilerplate via `render_findings_to_stderr()`. Adding a
    # new check (B-458 + B-464) requires NO main() edit — just append to CHECKS
    # + override render_findings_to_stderr in the subclass.
    for check in CHECKS:
        findings = findings_by_check.get(check.name, [])
        if findings:
            check.render_findings_to_stderr(findings)

    return block_exit


if __name__ == "__main__":
    sys.exit(main(sys.argv))
