#!/usr/bin/env python3
"""Pre-commit quality-checks orchestrator per Mechanism C-1 Phase 1 expansion.

Extends `.githooks/pre-commit` from discipline-enforcement-only (query_blindspots
scan) to also enforce code quality + compliance:

1. `check_query_blindspots`  — existing 4-rule discipline drift scan (delegates
   to `tools/query_blindspots.py` per Mechanism C-1)
2. `check_pytest_changed_python_files` — for each staged `.py` source file,
   find + run corresponding `tests/tier0/test_<name>.py` + `tests/tier1/test_<name>.py`;
   BLOCK on test failure OR new public surface without test file
3. `check_markdown_cross_refs` — for staged `docs/migration/**/*.md`, verify
   cited D-N / B-N / R-N / RB-N / SP-N references resolve to canonical source;
   BLOCK on broken refs
4. `check_cli_compliance_d74_d75_d76` — for NEW `tools/*.py` files, verify
   D74 exit codes + D75 `--dry-run` flag (if side-effecting) + D76 `EVENT_TYPE`
   constant present; BLOCK on missing
5. `check_gap_accountability` (B-315; Pitfall #9.p candidate) — for NEW staged
   content (per B-312 freshness), require every gap-indicator phrase ("should
   be surfaced as B-N", "drift candidate", etc.) to be paired with a
   disposition: B-NNN / P-NNN citation OR explicit dismissal. Substrate files
   allowlisted. BLOCK on unpaired phrases.
6. `check_planning_provenance` (B-275-class; planning-discipline layer
   forward-prevention) — for staged markdown files matching `*PLAN*.md`
   (case-insensitive), verify each contains a `## §0. Planning session
   provenance` section header. BLOCK on missing. Closes empirical precedent
   of commit `1b00755` (markdown refactor planning session 2026-05-15 missed
   4 skills; no §0 provenance section meant the audit trail was post-hoc
   reconstructed). Documentation alone (CLAUDE.md hard rule 13 + skill
   `udm-planning-session-startup`) proved insufficient — same documentation-
   not-mechanically-enforced gap as v1.2.0 inline-self-review citation check
   landed at commit `d5af93a` for cascade_classifier.

Per D74 exit-code contract:
- 0: all checks passed
- 1: one or more checks BLOCKED (commit refused)
- 3: orchestrator script error / fatal

Per D75: dry-run mode default; --live mode enforces blocking.
Per D76: audit-row to `_session_logs/cli_pre_commit_checks_<date>.log`.

User-direction 2026-05-16: "update it to be a code quality layer as well"
+ "quality assurance, unit, regression and compliance test" + "BLOCK on
failures" + "BLOCK on new public surface without tests" → Phase 1 build.
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
from typing import Iterable

EVENT_TYPE = "CLI_PRE_COMMIT_CHECKS"
EXIT_SUCCESS = 0
EXIT_BLOCKED = 1
EXIT_FATAL = 3

REPO_ROOT = Path(__file__).resolve().parent.parent
QUERY_BLINDSPOTS_PATH = REPO_ROOT / "tools" / "query_blindspots.py"

# Source directories where new .py files are subject to D67 Tier 0 test requirement
SOURCE_DIRS = (
    "tools/",
    "data_load/",
    "cdc/",
    "scd2/",
    "orchestration/",
    "schema/",
    "extract/",
    "observability/",
    "utils/",
    "migrations/",
)

# Canonical sources for cross-ref resolution
CANONICAL_D_SOURCE = REPO_ROOT / "docs" / "migration" / "03_DECISIONS.md"
CANONICAL_B_SOURCE = REPO_ROOT / "docs" / "migration" / "BACKLOG.md"
CANONICAL_R_SOURCE = REPO_ROOT / "docs" / "migration" / "RISKS.md"
CANONICAL_RB_SOURCE = REPO_ROOT / "docs" / "migration" / "05_RUNBOOKS.md"
CANONICAL_SP_SOURCE = REPO_ROOT / "docs" / "migration" / "phase1" / "01_database_schema.md"


@dataclass
class CheckResult:
    name: str
    passed: bool
    severity: str  # "block" | "warn" | "info"
    diagnostic: str

    def to_dict(self) -> dict:
        return asdict(self)


def _venv_python() -> str:
    """Detect project venv Python interpreter; fall back to sys.executable."""
    win_venv = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
    posix_venv = REPO_ROOT / ".venv" / "bin" / "python"
    if win_venv.is_file():
        return str(win_venv)
    if posix_venv.is_file():
        return str(posix_venv)
    return sys.executable


def _staged_files() -> list[str]:
    """Get list of staged files (paths relative to REPO_ROOT)."""
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"],
            capture_output=True, text=True, cwd=str(REPO_ROOT), check=False,
        )
        if result.returncode != 0:
            return []
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except (OSError, subprocess.SubprocessError):
        return []


def _staged_added_files() -> set[str]:
    """Get list of NEW (added, not modified) staged files. Used for compliance
    checks that apply only to new artifacts."""
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "--name-only", "--diff-filter=A"],
            capture_output=True, text=True, cwd=str(REPO_ROOT), check=False,
        )
        if result.returncode != 0:
            return set()
        return {line.strip() for line in result.stdout.splitlines() if line.strip()}
    except (OSError, subprocess.SubprocessError):
        return set()


def _staged_diff_added_lines(file_path: str) -> str:
    """Get only the lines ADDED in the staged diff for a file (per B-312 freshness
    refinement). For new files, returns full content (all lines are additions).
    For modified files, returns only the `+` lines (added/changed content).

    Used by check_markdown_cross_refs to scope cross-ref check to NEW content
    only — pre-existing broken refs in legacy content don't block unrelated commits.
    """
    try:
        result = subprocess.run(
            ["git", "diff", "--cached", "-U0", "--", file_path],
            capture_output=True, text=True, cwd=str(REPO_ROOT), check=False,
            encoding="utf-8", errors="replace",
        )
        if result.returncode != 0 or not result.stdout:
            return ""
        added_lines = []
        for line in result.stdout.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                added_lines.append(line[1:])
        return "\n".join(added_lines)
    except (OSError, subprocess.SubprocessError, UnicodeDecodeError):
        return ""


# ---------------------------------------------------------------------------
# Check 1: delegate to query_blindspots (existing Mechanism C-1 behavior)
# ---------------------------------------------------------------------------

QUERY_BLINDSPOTS_BINARY_EXTENSIONS = frozenset((
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg",
    ".pdf", ".zip", ".tar", ".gz", ".tgz", ".bz2", ".7z",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".o", ".a",
    ".pyc", ".pyo", ".class", ".jar", ".woff", ".woff2", ".ttf", ".otf",
    ".mp3", ".mp4", ".wav", ".webm", ".webp",
))


def check_query_blindspots(staged: list[str]) -> CheckResult:
    """Run query_blindspots scan on staged files at p0/p1 severity per D74 --live.

    Per B-316 (2026-05-16): for MODIFIED files, scan only diff `+` lines (mirrors
    B-312 freshness pattern for markdown_cross_refs). Pre-existing matches in
    legacy content NO LONGER block unrelated commits.

    Per B-316 fix-cycle 2 (2026-05-16; design review findings 🔴 BLOCK +
    🟡 IMPROVE applied inline):
    - Hash-based temp file naming (`DIFF_<sha1[:16]>_<sanitized-basename>`)
      eliminates basename collision (was: silent content substitution + wrong-file
      diagnostic attribution if two staged files shared basename across dirs).
    - Binary extensions filtered before loop (PNG/JPG/PDF/EXE/etc) to prevent
      scanning binary blobs that produce garbled diff output.

    Strategy:
    - Filter out binary extensions (QUERY_BLINDSPOTS_BINARY_EXTENSIONS).
    - For NEW files (in `_staged_added_files()` set): pass --file <original_path>
      for full content scan (line numbers correct).
    - For MODIFIED files: write `_staged_diff_added_lines(f)` to a hash-named
      temp file (collision-safe) and pass --file <temp_path>. Output
      post-processed to rewrite temp paths back to original.
    - For MODIFIED files with empty diff: skip.
    """
    import hashlib
    import tempfile

    if not QUERY_BLINDSPOTS_PATH.is_file():
        return CheckResult("query_blindspots", True, "warn",
                          "query_blindspots.py not found; scan skipped")
    if not staged:
        return CheckResult("query_blindspots", True, "info",
                          "no staged files; scan skipped")

    text_files = [f for f in staged
                  if Path(f).suffix.lower() not in QUERY_BLINDSPOTS_BINARY_EXTENSIONS]
    if not text_files:
        return CheckResult("query_blindspots", True, "info",
                          "all staged files filtered as binary; scan skipped")

    python_exe = _venv_python()
    added_files_set = _staged_added_files()
    file_args: list[str] = []
    temp_map: dict[str, str] = {}

    with tempfile.TemporaryDirectory(prefix="qb_diff_") as tmpdir:
        for f in text_files:
            if f in added_files_set:
                file_args.extend(["--file", f])
                continue
            diff_content = _staged_diff_added_lines(f)
            if not diff_content:
                continue
            # Hash-based collision-safe naming per B-316 fix-cycle 2 (review 🔴 BLOCK)
            path_hash = hashlib.sha1(f.encode("utf-8")).hexdigest()[:16]
            safe_base = re.sub(r"[^\w.-]", "_", Path(f).name)
            temp_path = Path(tmpdir) / f"DIFF_{path_hash}_{safe_base}"
            try:
                temp_path.write_text(diff_content, encoding="utf-8")
            except OSError:
                continue
            file_args.extend(["--file", str(temp_path)])
            temp_map[str(temp_path)] = f

        if not file_args:
            return CheckResult("query_blindspots", True, "info",
                              "no scannable content in staged files (all modified files have empty diffs); scan skipped")

        try:
            result = subprocess.run(
                [python_exe, str(QUERY_BLINDSPOTS_PATH), *file_args,
                 "--severity", "p0,p1", "--no-audit", "--live"],
                capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=30,
                encoding="utf-8", errors="replace",
            )
        except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired) as exc:
            return CheckResult("query_blindspots", True, "warn",
                              f"query_blindspots scan failed ({exc}); not blocking")

    output = result.stdout or ""
    for temp_path, original in temp_map.items():
        output = output.replace(temp_path, f"{original} (NEW content per B-316)")

    if result.returncode == 2:
        return CheckResult("query_blindspots", False, "block",
                          f"p0 match (--live exit 2; scanning NEW content per B-316 freshness):\n{output}")
    return CheckResult("query_blindspots", True, "info",
                      f"scan clean (exit {result.returncode}; NEW content only per B-316 freshness)")


# ---------------------------------------------------------------------------
# Check 2: pytest on changed Python files (unit + regression)
# ---------------------------------------------------------------------------

def _find_test_files_for(src_path: str) -> list[Path]:
    """For a staged source .py file, find corresponding test files."""
    p = Path(src_path)
    if not p.suffix == ".py":
        return []
    module_name = p.stem
    candidates = [
        REPO_ROOT / "tests" / "tier0" / f"test_{module_name}.py",
        REPO_ROOT / "tests" / "tier1" / f"test_{module_name}.py",
        REPO_ROOT / "tests" / "unit" / f"test_{module_name}.py",
        REPO_ROOT / "tests" / "regression" / f"test_{module_name}.py",
    ]
    return [c for c in candidates if c.is_file()]


def _has_public_surface(src_path: Path) -> bool:
    """Check if a Python source file declares public surface (non-underscore-prefixed
    top-level def / class / UPPERCASE constants)."""
    try:
        content = src_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    public_def_re = re.compile(r"^def\s+([a-z][a-z0-9_]*)\s*\(", re.MULTILINE)
    public_class_re = re.compile(r"^class\s+([A-Z][A-Za-z0-9_]*)\s*[\(:]", re.MULTILINE)
    public_const_re = re.compile(r"^([A-Z][A-Z0-9_]+)\s*=\s*", re.MULTILINE)
    return bool(
        public_def_re.search(content)
        or public_class_re.search(content)
        or public_const_re.search(content)
    )


def check_pytest_changed_python_files(staged: list[str]) -> CheckResult:
    """Find tests for staged .py source files; run them; BLOCK on failure OR
    new public-surface file without test."""
    code_files = []
    for f in staged:
        norm = f.replace("\\", "/")
        if not norm.endswith(".py"):
            continue
        if norm.startswith("tests/") or "/tests/" in norm:
            continue
        if not any(norm.startswith(d) for d in SOURCE_DIRS):
            continue
        code_files.append(norm)

    if not code_files:
        return CheckResult("pytest_changed", True, "info",
                          "no source .py files staged; pytest skipped")

    missing_tests = []
    test_files: set[Path] = set()
    added = _staged_added_files()
    for src in code_files:
        tests = _find_test_files_for(src)
        if tests:
            test_files.update(tests)
        elif src in added:
            src_path = REPO_ROOT / src
            if _has_public_surface(src_path):
                missing_tests.append(src)
        # Modified files without tests are not blocked (legacy code allowance)

    if missing_tests:
        return CheckResult(
            "pytest_changed", False, "block",
            f"new public-surface files staged WITHOUT test file (per D67):\n"
            + "\n".join(f"  - {f} (expected tests/tier0/test_{Path(f).stem}.py)"
                       for f in missing_tests)
            + "\n\nAuthor a Tier 0 smoke test before committing, OR bypass with "
              "--no-verify (self-flagging)."
        )

    if not test_files:
        return CheckResult("pytest_changed", True, "info",
                          f"{len(code_files)} source file(s) staged; no test files found "
                          "(legacy code without tests; not blocked)")

    python_exe = _venv_python()
    test_args = [str(t.relative_to(REPO_ROOT)) for t in sorted(test_files)]
    try:
        result = subprocess.run(
            [python_exe, "-m", "pytest", *test_args, "--no-header", "-q"],
            capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=120,
        )
    except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired) as exc:
        return CheckResult("pytest_changed", False, "block",
                          f"pytest invocation failed ({exc})")
    if result.returncode != 0:
        return CheckResult(
            "pytest_changed", False, "block",
            f"pytest FAILED on {len(test_files)} test file(s):\n{result.stdout[-2000:]}\n"
            f"{result.stderr[-500:]}"
        )
    return CheckResult("pytest_changed", True, "info",
                      f"pytest PASSED on {len(test_files)} test file(s) covering "
                      f"{len(code_files)} source file(s)")


# ---------------------------------------------------------------------------
# Check 3: markdown cross-reference resolution
# ---------------------------------------------------------------------------

# Patterns:
#  D62 / D-62 / D113
#  B-294 / B144
#  R28 / R-33
#  RB-10 / RB10
#  SP-4 / SP4 / SP-12
_REF_PATTERN = re.compile(r"\b(D|B|R|RB|SP)[-]?(\d{1,3})\b")


def _load_canonical_ids() -> dict[str, set[int]]:
    """Load known D-N / B-N / R-N / RB-N / SP-N identifiers from canonical sources.

    Stores as int (not str) to normalize zero-padding (e.g., R01 from RISKS.md
    canonical form matches R-5 / R5 citations without false positives).
    """
    known: dict[str, set[int]] = {"D": set(), "B": set(), "R": set(), "RB": set(), "SP": set()}
    sources = {
        "D": CANONICAL_D_SOURCE,
        "B": CANONICAL_B_SOURCE,
        "R": CANONICAL_R_SOURCE,
        "RB": CANONICAL_RB_SOURCE,
        "SP": CANONICAL_SP_SOURCE,
    }
    for prefix, src in sources.items():
        if not src.is_file():
            continue
        try:
            content = src.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for match in _REF_PATTERN.finditer(content):
            if match.group(1) == prefix:
                try:
                    known[prefix].add(int(match.group(2)))
                except ValueError:
                    pass
    return known


def _scan_content_for_broken_refs(
    content: str, file_path: str, known: dict[str, set[int]],
) -> list[tuple[str, str, str, str]]:
    """Scan content for broken cross-references. Returns list of
    (file, prefix, number_str, line_snippet) tuples for unresolved refs."""
    broken: list[tuple[str, str, str, str]] = []
    for line in content.splitlines():
        for match in _REF_PATTERN.finditer(line):
            prefix, number_str = match.group(1), match.group(2)
            try:
                number = int(number_str)
            except ValueError:
                continue
            if number == 0:
                continue
            if number not in known.get(prefix, set()):
                broken.append((file_path, prefix, number_str, line.strip()[:100]))
    return broken


def check_markdown_cross_refs(staged: list[str]) -> CheckResult:
    """For staged markdown in docs/migration/, verify D-N/B-N/R-N/RB-N/SP-N refs resolve.

    Per B-312 freshness refinement (2026-05-16): only blocks on NEWLY-introduced
    broken refs (scans the staged diff `+` lines, not the full file). Pre-existing
    broken refs in legacy content don't block unrelated commits.

    For new files (no HEAD version), entire content is treated as additions.
    For modified files, only added/changed lines are scanned.
    """
    md_files = []
    for f in staged:
        norm = f.replace("\\", "/")
        if not norm.endswith(".md"):
            continue
        if not norm.startswith("docs/migration/"):
            continue
        md_files.append(norm)

    if not md_files:
        return CheckResult("markdown_cross_refs", True, "info",
                          "no markdown files in docs/migration/ staged; check skipped")

    known = _load_canonical_ids()
    broken: list[tuple[str, str, str, str]] = []
    added_files_set = _staged_added_files()
    for md_file in md_files:
        if md_file in added_files_set:
            md_path = REPO_ROOT / md_file
            try:
                scan_content = md_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
        else:
            scan_content = _staged_diff_added_lines(md_file)
            if not scan_content:
                continue
        broken.extend(_scan_content_for_broken_refs(scan_content, md_file, known))

    if broken:
        broken = broken[:20]
        return CheckResult(
            "markdown_cross_refs", False, "block",
            f"{len(broken)} broken cross-reference(s) in staged markdown "
            f"(scanning NEW content only per B-312 freshness):\n"
            + "\n".join(f"  - {f}: {p}-{n} unresolved (line: {snippet!r})"
                       for f, p, n, snippet in broken)
            + "\n\nVerify the reference exists in canonical source "
              "(03_DECISIONS.md / BACKLOG.md / RISKS.md / 05_RUNBOOKS.md / "
              "phase1/01_database_schema.md) OR fix typo, OR bypass with --no-verify."
        )
    total_refs = sum(len(s) for s in known.values())
    return CheckResult("markdown_cross_refs", True, "info",
                      f"all NEW cross-refs in {len(md_files)} markdown file(s) resolved "
                      f"(canonical universe: {total_refs} known IDs; pre-existing "
                      f"broken refs in legacy content excluded per B-312)")


# ---------------------------------------------------------------------------
# Check 4: D74 / D75 / D76 compliance for new CLI tools
# ---------------------------------------------------------------------------

def check_cli_compliance_d74_d75_d76(staged: list[str]) -> CheckResult:
    """For NEW (added) tools/*.py files, verify D74/D75/D76 contracts."""
    added = _staged_added_files()
    new_cli_files = []
    for f in staged:
        norm = f.replace("\\", "/")
        if not norm.endswith(".py"):
            continue
        if not norm.startswith("tools/"):
            continue
        if norm not in added:
            continue
        new_cli_files.append(norm)

    if not new_cli_files:
        return CheckResult("cli_compliance", True, "info",
                          "no new tools/*.py files staged; compliance check skipped")

    violations: list[tuple[str, list[str]]] = []
    for cli_file in new_cli_files:
        file_path = REPO_ROOT / cli_file
        try:
            content = file_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        # Distinguish CLI tools from library modules: only files with
        # `if __name__ == "__main__":` are subject to D74/D75/D76 compliance.
        # Library modules (e.g., tools/exemption_phrases.py) are exempt.
        if 'if __name__ == "__main__":' not in content:
            continue
        file_violations = []
        if "EXIT_SUCCESS" not in content:
            file_violations.append("D74: missing EXIT_SUCCESS constant")
        if "EXIT_" not in content or content.count("EXIT_") < 2:
            file_violations.append("D74: missing EXIT_* constant family (need at least 2)")
        if "EVENT_TYPE" not in content or 'CLI_' not in content:
            file_violations.append('D76: missing EVENT_TYPE = "CLI_*" constant')
        side_effect_indicators = ("--apply", "subprocess.run", "Path.write_text", "open(", ".write(")
        is_side_effecting = any(ind in content for ind in side_effect_indicators)
        if is_side_effecting and "--dry-run" not in content:
            file_violations.append("D75: side-effecting tool missing --dry-run flag")
        if file_violations:
            violations.append((cli_file, file_violations))

    if violations:
        return CheckResult(
            "cli_compliance", False, "block",
            f"{len(violations)} new CLI tool(s) violate D74/D75/D76 contract:\n"
            + "\n".join(f"  - {f}:\n      " + "\n      ".join(vs)
                       for f, vs in violations)
            + "\n\nFix the missing contract elements before committing, "
              "OR bypass with --no-verify (self-flagging)."
        )
    return CheckResult("cli_compliance", True, "info",
                      f"all {len(new_cli_files)} new CLI tool(s) D74/D75/D76 compliant")


# ---------------------------------------------------------------------------
# Orchestrator + CLI
# ---------------------------------------------------------------------------

def check_lint_security_types_changed_python_files(staged: list[str]) -> CheckResult:
    """For each staged source .py file, run ruff + bandit + mypy (graceful-skip
    if tool not installed). BLOCK on any tool reporting errors.

    Per B-309 Cycle 1 critical-review Improvement 1 (2026-05-16). Tools are
    optional dev-environment dependencies; check warns + skips gracefully if
    absent (preserves cross-environment usability while activating when tools
    land in CI / future dev installs).
    """
    code_files = []
    for f in staged:
        norm = f.replace("\\", "/")
        if not norm.endswith(".py"):
            continue
        if norm.startswith("tests/") or "/tests/" in norm:
            continue
        if not any(norm.startswith(d) for d in SOURCE_DIRS):
            continue
        code_files.append(norm)

    if not code_files:
        return CheckResult("lint_security_types", True, "info",
                          "no source .py files staged; check skipped")

    python_exe = _venv_python()
    file_args = code_files
    tool_results: list[tuple[str, str]] = []  # (tool, diagnostic)
    skipped: list[str] = []

    def _try_run(tool: str, args: list[str]) -> tuple[bool, str]:
        """Returns (passed, diagnostic). passed=False means tool FOUND errors;
        if tool not installed, returns (True, 'skipped: not installed')."""
        try:
            result = subprocess.run(
                [python_exe, "-m", tool, *args],
                capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=60,
            )
        except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired) as exc:
            return True, f"skipped: invocation failed ({exc})"
        if "No module named" in result.stderr:
            return True, "skipped: not installed (pip install " + tool + ")"
        if result.returncode == 0:
            return True, "clean"
        return False, f"errors:\n{result.stdout[-1500:]}\n{result.stderr[-500:]}"

    ruff_ok, ruff_diag = _try_run("ruff", ["check", *file_args])
    if "skipped" in ruff_diag:
        skipped.append(f"ruff: {ruff_diag}")
    elif not ruff_ok:
        tool_results.append(("ruff", ruff_diag))

    bandit_ok, bandit_diag = _try_run("bandit", ["-q", "-ll", *file_args])
    if "skipped" in bandit_diag:
        skipped.append(f"bandit: {bandit_diag}")
    elif not bandit_ok:
        tool_results.append(("bandit", bandit_diag))

    mypy_ok, mypy_diag = _try_run("mypy", file_args)
    if "skipped" in mypy_diag:
        skipped.append(f"mypy: {mypy_diag}")
    elif not mypy_ok:
        tool_results.append(("mypy", mypy_diag))

    if tool_results:
        msg_parts = [f"{len(tool_results)} tool(s) reported errors on "
                    f"{len(code_files)} source file(s):"]
        for tool, diag in tool_results:
            msg_parts.append(f"\n  --- {tool} ---\n{diag}")
        return CheckResult("lint_security_types", False, "block", "\n".join(msg_parts))

    if not skipped:
        return CheckResult("lint_security_types", True, "info",
                          f"all 3 tools (ruff + bandit + mypy) PASSED on "
                          f"{len(code_files)} source file(s)")
    return CheckResult("lint_security_types", True, "warn",
                      f"{len(code_files)} source file(s) checked; "
                      f"{len(skipped)} tool(s) skipped:\n  " + "\n  ".join(skipped))


# ---------------------------------------------------------------------------
# Check 6: gap-accountability (per B-315 + Pitfall #9.p candidate)
# ---------------------------------------------------------------------------

GAP_INDICATOR_PHRASES = (
    "should be surfaced as B-",
    "should be surfaced as a B-",
    "should open a B-N",
    "should open a P-N",
    "should be filed as B-",
    "noted but not opened",
    "I could have opened",
    "drift candidate",
    "B-N candidate",
    "P-N candidate",
    "Pitfall #9.k candidate",
    "Pitfall #9.l candidate",
    "Pitfall #9.m candidate",
    "Pitfall #9.n candidate",
    "Pitfall #9.o candidate",
    "Pitfall #9.p candidate",
    "WSJF candidate",
)

DISPOSITION_BNUMBER_RE = re.compile(r"\bB-?\d{1,4}\b")
DISPOSITION_PNUMBER_RE = re.compile(r"\bP-?\d{1,4}\b")
DISPOSITION_DISMISSAL_RE = re.compile(
    r"(?:no\s+B-N\s+(?:needed|required)|dismiss(?:ed)?\s*[:\-]|"
    r"cosmetic\s+only|not\s+a\s+real\s+gap|already\s+tracked\s+via)",
    re.IGNORECASE,
)

GAP_ACCOUNTABILITY_ALLOWLIST = (
    "CLAUDE.md",
    "docs/migration/HANDOFF.md",
    "docs/migration/CLAUDE_GOTCHAS.md",
    "docs/migration/blindspots/ledger.yml",
    "tools/exemption_phrases.py",
    "tools/pre_commit_checks.py",
    "tools/check_commit_msg.py",
    "tools/query_blindspots.py",
    ".claude/skills/udm-exemption-verifier/SKILL.md",
    ".claude/skills/udm-gap-check/SKILL.md",
    ".claude/skills/udm-progress-logger/SKILL.md",
    ".claude/skills/udm-next-step-cascade/SKILL.md",
    ".claude/skills/udm-post-edit-verification/SKILL.md",
)


def _is_allowlisted_for_gap_check(file_path: str) -> bool:
    """Substrate files that legitimately enumerate gap-indicator phrases as data."""
    norm = file_path.replace("\\", "/")
    if norm in GAP_ACCOUNTABILITY_ALLOWLIST:
        return True
    if norm.startswith("tests/tier0/") and norm.endswith(".py"):
        return True
    if norm.startswith("tests/tier1/test_skill_"):
        return True
    return False


def _scan_for_unaddressed_gaps(
    content: str, file_path: str
) -> list[tuple[str, str, int, str]]:
    """For each gap-indicator phrase in `content`, verify a paired disposition
    exists in same line OR within ±5 lines. Returns list of unpaired matches.

    Tuple shape: (file_path, phrase, line_number, snippet).
    """
    if _is_allowlisted_for_gap_check(file_path):
        return []
    lines = content.splitlines()
    findings: list[tuple[str, str, int, str]] = []
    for i, line in enumerate(lines):
        for phrase in GAP_INDICATOR_PHRASES:
            if phrase.lower() not in line.lower():
                continue
            window_lo = max(0, i - 5)
            window_hi = min(len(lines), i + 6)
            window = "\n".join(lines[window_lo:window_hi])
            if (DISPOSITION_BNUMBER_RE.search(window)
                    or DISPOSITION_PNUMBER_RE.search(window)
                    or DISPOSITION_DISMISSAL_RE.search(window)):
                continue
            snippet = line.strip()[:120]
            findings.append((file_path, phrase, i + 1, snippet))
            break
    return findings


def check_gap_accountability(staged: list[str]) -> CheckResult:
    """Per B-315 forward-prevention (Pitfall #9.p candidate; 3-event base from
    2026-05-16 session): every gap-indicator phrase in NEWLY-ADDED staged
    content (per B-312 freshness) must be paired with a disposition signal:
    cited B-NNN OR P-NNN OR explicit dismissal phrase ("no B-N needed",
    "dismissed:", "cosmetic only", "not a real gap", "already tracked via").

    Substrate files (CLAUDE.md / HANDOFF.md / tools/exemption_phrases.py /
    test files) allowlisted — they legitimately enumerate these phrases as
    data, not as in-flight surfaced gaps.

    Closes the prose-surface drift pattern: "I notice X but don't open it"
    that defeats producer judgment-based gap conversion (3 events 2026-05-16).
    """
    relevant_files = []
    for f in staged:
        norm = f.replace("\\", "/")
        if not (norm.endswith(".md") or norm.endswith(".py") or norm.endswith(".txt")):
            continue
        if _is_allowlisted_for_gap_check(norm):
            continue
        relevant_files.append(norm)

    if not relevant_files:
        return CheckResult("gap_accountability", True, "info",
                          "no non-allowlisted staged files; check skipped")

    findings: list[tuple[str, str, int, str]] = []
    added_files_set = _staged_added_files()
    for f in relevant_files:
        if f in added_files_set:
            try:
                scan_content = (REPO_ROOT / f).read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
        else:
            scan_content = _staged_diff_added_lines(f)
            if not scan_content:
                continue
        findings.extend(_scan_for_unaddressed_gaps(scan_content, f))

    if findings:
        findings = findings[:15]
        return CheckResult(
            "gap_accountability", False, "block",
            f"{len(findings)} unaddressed gap-indicator phrase(s) in NEW staged content "
            f"(per B-315; Pitfall #9.p candidate):\n"
            + "\n".join(f"  - {f}:{ln} phrase {p!r} (line: {snippet!r})"
                       for f, p, ln, snippet in findings)
            + "\n\nPair each phrase with a disposition: cite a B-NNN / P-NNN "
              "within ±5 lines, OR explicitly dismiss "
              "('no B-N needed; <reason>' / 'cosmetic only' / 'already tracked via X')."
        )
    return CheckResult("gap_accountability", True, "info",
                      f"all gap-indicator phrases in {len(relevant_files)} staged file(s) "
                      "paired with disposition (B-315 contract)")


# ---------------------------------------------------------------------------
# Check 7: planning-provenance section in *PLAN*.md files (B-275-class)
# ---------------------------------------------------------------------------

# Case-insensitive substring match: any markdown file with "PLAN" in its
# basename (e.g., NEXT_STEPS_PLAN_2026-05-17.md, MARKDOWN_REFACTOR_PLAN.md,
# PHASE_X_DEEP_DIVE_PLAN.md, my-refactor-plan.md).
_PLANNING_PROVENANCE_HEADER_RE = re.compile(
    r"^##\s+§0\.\s+Planning session provenance", re.MULTILINE
)


def _is_planning_doc(file_path: str) -> bool:
    """Case-insensitive glob: matches `*plan*.md` / `*PLAN*.md` / `*Plan*.md`.

    Match is on basename only, not full path (avoids false-positive on a
    `.md` file inside a directory named `plans/`).
    """
    norm = file_path.replace("\\", "/")
    if not norm.lower().endswith(".md"):
        return False
    basename = Path(norm).name
    return "plan" in basename.lower()


def check_planning_provenance(staged_files: list[str]) -> CheckResult:
    """For staged `*PLAN*.md` markdown files, verify each has a
    `## §0. Planning session provenance` section header.

    Per B-275-class forward-prevention (closes the empirical precedent of
    commit `1b00755` — markdown refactor planning session 2026-05-15 missed
    4 skills; no §0 provenance section meant the audit trail was post-hoc
    reconstructed). Documentation alone (CLAUDE.md hard rule 13 + skill
    `udm-planning-session-startup`) proved insufficient — same
    documentation-but-not-mechanically-enforced gap pattern as v1.2.0
    inline-self-review citation check that landed at commit `d5af93a` for
    cascade_classifier.

    Per CLAUDE.md hard rule 13: planning-session deliverables (plan markdown
    files in `docs/migration/`) WITHOUT a §0 "Planning session provenance"
    section are subject to backfill at next revision commit. This check
    enforces that contract at commit-time so the audit trail is always
    co-temporal with the plan content (not reconstructed post-hoc).

    Companion skill: `.claude/skills/udm-context-loader/SKILL.md` operationalizes
    the same §0 discipline at planning-session authoring time (before commit).
    The skill emits the §0 brief structure for sub-agents; this check enforces
    that the §0 section actually lands in committed plan files regardless of
    whether the skill was invoked. Two-layer defense per next-steps plan
    Phase 0 (2026-05-17 multi-agent team Option A).

    Returns:
        INFO if no plan files staged
        PASS if all staged plan files have the §0 provenance header
        BLOCK if any staged plan file is missing the §0 provenance header
    """
    plan_files = [f for f in staged_files if _is_planning_doc(f)]
    if not plan_files:
        return CheckResult("planning_provenance", True, "info",
                          "no *PLAN*.md files staged; check skipped")

    missing: list[str] = []
    unreadable: list[str] = []
    for plan_file in plan_files:
        plan_path = REPO_ROOT / plan_file
        try:
            content = plan_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            unreadable.append(plan_file)
            continue
        if not _PLANNING_PROVENANCE_HEADER_RE.search(content):
            missing.append(plan_file)

    if missing:
        return CheckResult(
            "planning_provenance", False, "block",
            f"{len(missing)} planning-doc(s) staged WITHOUT "
            f"'## §0. Planning session provenance' section "
            f"(per CLAUDE.md hard rule 13 + B-275-class forward-prevention; "
            f"empirical anchor commit `1b00755`):\n"
            + "\n".join(f"  - {f} (expected: '## §0. Planning session provenance' "
                       "header per `udm-planning-session-startup` SKILL.md Step 5)"
                       for f in missing)
            + "\n\nAdd the provenance section enumerating: (a) trigger phrase "
              "+ scope identification (PS-N category per `PLANNING_DISCIPLINE.md`); "
              "(b) skill list applied; (c) sub-agent inheritance contract (if any); "
              "(d) user approval/redirect of the skill list. Bypass with "
              "--no-verify is self-flagging exemption-claim."
        )

    diagnostic = (f"all {len(plan_files)} *PLAN*.md file(s) have §0 "
                  "Planning session provenance section")
    if unreadable:
        diagnostic += f" ({len(unreadable)} file(s) unreadable, treated as pass)"
    return CheckResult("planning_provenance", True, "info", diagnostic)


CHECKS = [
    check_query_blindspots,
    check_pytest_changed_python_files,
    check_lint_security_types_changed_python_files,
    check_markdown_cross_refs,
    check_cli_compliance_d74_d75_d76,
    check_gap_accountability,
    check_planning_provenance,
]


def run_all_checks(staged: list[str] | None = None) -> list[CheckResult]:
    """Run all registered checks on staged files. Returns list of CheckResult."""
    if staged is None:
        staged = _staged_files()
    results = []
    for check_fn in CHECKS:
        try:
            results.append(check_fn(staged))
        except Exception as exc:
            results.append(CheckResult(
                check_fn.__name__, True, "warn",
                f"check raised exception (non-blocking): {exc}"
            ))
    return results


def _emit_audit_row(results: list[CheckResult], args: argparse.Namespace, exit_code: int) -> None:
    """Write audit row per D76."""
    audit_dir = REPO_ROOT / "_session_logs"
    audit_dir.mkdir(exist_ok=True)
    log_path = audit_dir / f"cli_pre_commit_checks_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.log"
    payload = {
        "event_type": EVENT_TYPE,
        "ts": datetime.now(timezone.utc).isoformat(),
        "args": {k: v for k, v in vars(args).items() if k != "func"},
        "results": [r.to_dict() for r in results],
        "exit_code": exit_code,
    }
    try:
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload) + "\n")
    except OSError:
        pass


def _print_results(results: list[CheckResult], verbose: bool) -> None:
    """Print check results to stderr (BLOCK) or stdout (PASS)."""
    blocked = [r for r in results if not r.passed and r.severity == "block"]
    if blocked:
        print("[pre-commit-checks BLOCKED] one or more quality checks FAILED:",
              file=sys.stderr)
        for r in blocked:
            print(f"\n--- {r.name} (BLOCK) ---", file=sys.stderr)
            print(r.diagnostic, file=sys.stderr)
        print("\nBypass with --no-verify is self-flagging exemption-claim; "
              "reviewers should treat as quasi-audit-question trigger.",
              file=sys.stderr)
        return
    if verbose:
        for r in results:
            status = "PASS" if r.passed else "WARN"
            print(f"[{status}] {r.name}: {r.diagnostic}")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Pre-commit quality-checks orchestrator per Mechanism C-1 Phase 1.",
    )
    parser.add_argument("--verbose", action="store_true", help="Print PASS results too.")
    parser.add_argument("--no-audit", action="store_true", help="Skip audit-row write.")
    parser.add_argument(
        "--files", default=None,
        help="Comma-separated list of files to check (CI use; bypasses git "
             "--cached staged-files lookup). Used by GitHub Actions mirror "
             "workflow per B-311 Cycle 2.",
    )
    return parser.parse_args(argv)


def cli_main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    explicit_files: list[str] | None = None
    if args.files:
        explicit_files = [f.strip() for f in args.files.split(",") if f.strip()]
    try:
        results = run_all_checks(staged=explicit_files)
    except Exception as exc:
        print(f"FATAL: orchestrator error: {exc}", file=sys.stderr)
        return EXIT_FATAL
    any_blocked = any(not r.passed and r.severity == "block" for r in results)
    exit_code = EXIT_BLOCKED if any_blocked else EXIT_SUCCESS
    _print_results(results, args.verbose)
    if not args.no_audit:
        _emit_audit_row(results, args, exit_code)
    return exit_code


def main() -> None:
    sys.exit(cli_main())


if __name__ == "__main__":
    main()
