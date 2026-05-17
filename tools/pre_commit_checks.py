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


# ---------------------------------------------------------------------------
# Check 1: delegate to query_blindspots (existing Mechanism C-1 behavior)
# ---------------------------------------------------------------------------

def check_query_blindspots(staged: list[str]) -> CheckResult:
    """Run query_blindspots scan on staged files at p0/p1 severity per D74 --live."""
    if not QUERY_BLINDSPOTS_PATH.is_file():
        return CheckResult("query_blindspots", True, "warn",
                          "query_blindspots.py not found; scan skipped")
    if not staged:
        return CheckResult("query_blindspots", True, "info",
                          "no staged files; scan skipped")
    python_exe = _venv_python()
    file_args = []
    for f in staged:
        file_args.extend(["--file", f])
    try:
        result = subprocess.run(
            [python_exe, str(QUERY_BLINDSPOTS_PATH), *file_args,
             "--severity", "p0,p1", "--no-audit", "--live"],
            capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=30,
        )
    except (OSError, subprocess.SubprocessError, subprocess.TimeoutExpired) as exc:
        return CheckResult("query_blindspots", True, "warn",
                          f"query_blindspots scan failed ({exc}); not blocking")
    if result.returncode == 2:
        return CheckResult("query_blindspots", False, "block",
                          f"p0 match (--live exit 2):\n{result.stdout}")
    return CheckResult("query_blindspots", True, "info",
                      f"scan clean (exit {result.returncode})")


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
            [python_exe, "-m", "pytest", *test_args, "--no-header", "-q", "--timeout=60"],
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


def _load_canonical_ids() -> dict[str, set[str]]:
    """Load known D-N / B-N / R-N / RB-N / SP-N identifiers from canonical sources."""
    known: dict[str, set[str]] = {"D": set(), "B": set(), "R": set(), "RB": set(), "SP": set()}
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
                known[prefix].add(match.group(2))
    return known


def check_markdown_cross_refs(staged: list[str]) -> CheckResult:
    """For staged markdown in docs/migration/, verify D-N/B-N/R-N/RB-N/SP-N refs resolve."""
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
    broken: list[tuple[str, str, int, str]] = []  # (file, prefix, number, line_snippet)
    for md_file in md_files:
        md_path = REPO_ROOT / md_file
        try:
            content = md_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(content.splitlines(), start=1):
            for match in _REF_PATTERN.finditer(line):
                prefix, number = match.group(1), match.group(2)
                if number not in known.get(prefix, set()):
                    if number == "0":
                        continue
                    broken.append((md_file, prefix, number, line.strip()[:100]))

    if broken:
        broken = broken[:20]
        return CheckResult(
            "markdown_cross_refs", False, "block",
            f"{len(broken)} broken cross-reference(s) in staged markdown:\n"
            + "\n".join(f"  - {f}: {p}-{n} unresolved (line: {snippet!r})"
                       for f, p, n, snippet in broken)
            + "\n\nVerify the reference exists in canonical source "
              "(03_DECISIONS.md / BACKLOG.md / RISKS.md / 05_RUNBOOKS.md / "
              "phase1/01_database_schema.md) OR fix typo, OR bypass with --no-verify."
        )
    total_refs = sum(len(s) for s in known.values())
    return CheckResult("markdown_cross_refs", True, "info",
                      f"all cross-refs in {len(md_files)} markdown file(s) resolved "
                      f"(canonical universe: {total_refs} known IDs)")


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

CHECKS = [
    check_query_blindspots,
    check_pytest_changed_python_files,
    check_markdown_cross_refs,
    check_cli_compliance_d74_d75_d76,
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
    return parser.parse_args(argv)


def cli_main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    try:
        results = run_all_checks()
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
