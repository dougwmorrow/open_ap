#!/usr/bin/env python3
"""Required-kwargs registry per B-326 closure — generalized compositional-drift
detector for functions with optional context-shaping kwargs that ALL enforcement
callers must pass.

Closes the pattern surfaced at the cascade meta-review (audit_cascade_compliance
initially missed passing `classification=` kwarg to `has_cascade_evidence` →
substrate-stricter B-321 check silently bypassed in retroactive scans). Same
pattern generalizes to ANY function with optional context-shaping kwarg —
this module provides the registry + scan helper so adding new enforcement
patterns is trivial (one dict entry + automatic test coverage via parametrized
Tier 1 test).

Composition:
- `REQUIRED_KWARGS` registry maps function name → list of kwarg names that
  ALL enforcement-pathway callers must pass
- `scan_callers(function_name, enforcement_dirs)` grep-walks enforcement
  directories for function calls + verifies required kwargs appear within
  ±5 lines (docstring/code-fence/triple-quote-string aware)
- `ScanResult` dataclass returned per scan (function name + violations list +
  files scanned)

Per D74 — library module; no CLI exit codes (no `main`/`cli_main`).
Per D75 — read-only static analysis; no `--dry-run` needed.
Per D76 — caller-side audit (test failure is the audit trail).

Public surface:
- `REQUIRED_KWARGS` dict
- `ENFORCEMENT_DIRS` tuple (default scan paths)
- `ScanResult` dataclass
- `scan_callers(function_name, enforcement_dirs)` function
- `scan_all_registry_functions()` function (parametrized over registry)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Function-name → required-kwarg-names registry.
# Adding a new entry automatically extends Tier 1 test coverage via the
# parametrized `test_all_registry_functions_callers_compliant` test.
#
# Initial entry per B-326 closure (the empirical pattern that prompted
# this registry; was previously hardcoded as a one-off Tier 0 test).
REQUIRED_KWARGS: dict[str, list[str]] = {
    "has_cascade_evidence": ["classification"],
}

# Default enforcement directories scanned for callers.
# ENFORCEMENT scope (callers must pass required kwargs); EXCLUDES test code
# (legitimate unit-testing of the functions doesn't require enforcement kwargs).
ENFORCEMENT_DIRS: tuple[str, ...] = (
    "tools",
    ".claude/hooks",
)

_TRIPLE_QUOTE_RE = re.compile(r'"""|' + r"'''")
_TRIPLE_QUOTE_CHARS = ('"""', "'''")


@dataclass
class KwargViolation:
    """Per-violation record per reviewer 🟡 IMPROVE: tuples lose info for
    multi-kwarg cases (current entries are single-kwarg but registry will
    grow). Forward-extensible dataclass over tuple unpacking."""
    file: str
    line: int
    function: str
    missing_kwarg: str


@dataclass
class ScanResult:
    function_name: str
    required_kwargs: list[str]
    violations: list[KwargViolation] = field(default_factory=list)
    files_scanned: int = 0
    enforcement_dirs: list[str] = field(default_factory=list)

    def is_clean(self) -> bool:
        return self.violations == []


def scan_callers(
    function_name: str,
    enforcement_dirs: tuple[str, ...] = ENFORCEMENT_DIRS,
    required_kwargs: list[str] | None = None,
) -> ScanResult:
    """Grep-walk enforcement directories for callers of `function_name`;
    verify each required kwarg appears within ±5 lines of the call.

    Docstring/code-fence/triple-quote-string aware (avoids false positives
    on code-citations inside docstrings). Skips test files (`test_*.py`).

    Args:
        function_name: Function whose callers to scan (e.g. "has_cascade_evidence")
        enforcement_dirs: Directories to scan (default per ENFORCEMENT_DIRS)
        required_kwargs: Required kwarg names (defaults to registry lookup)

    Returns ScanResult with violations list of (file_path, line_number) tuples.
    """
    if required_kwargs is None:
        required_kwargs = REQUIRED_KWARGS.get(function_name, [])
    if not required_kwargs:
        return ScanResult(
            function_name=function_name,
            required_kwargs=[],
            files_scanned=0,
            enforcement_dirs=list(enforcement_dirs),
        )

    call_re = re.compile(rf"{re.escape(function_name)}\s*\(")
    py_files: list[Path] = []
    for d in enforcement_dirs:
        dir_path = REPO_ROOT / d
        if dir_path.is_dir():
            py_files.extend(dir_path.rglob("*.py"))

    violations: list[KwargViolation] = []
    files_scanned = 0
    for py_file in py_files:
        # Skip the definer module itself (function definition + tests don't count)
        # Heuristic: skip files whose basename matches "cascade_classifier.py"
        # (since has_cascade_evidence lives there). Extend if other functions
        # added to registry that need similar self-exclusion.
        if py_file.name == "cascade_classifier.py":
            continue
        # Skip test files; test code legitimately calls the function for
        # unit-testing without enforcement semantics
        if "test_" in py_file.name or py_file.name.startswith("test"):
            continue
        try:
            content = py_file.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        files_scanned += 1
        lines = content.splitlines()
        in_string = False
        for i, line in enumerate(lines):
            # Triple-quote-string state toggle
            quote_count = len(_TRIPLE_QUOTE_RE.findall(line))
            if quote_count % 2 == 1:
                in_string = not in_string
                continue
            if in_string:
                continue
            # Skip lines that are backtick code-citation
            if f"`{function_name}" in line:
                continue
            if not call_re.search(line):
                continue
            # Check ±5 lines window for ALL required kwargs.
            # Per reviewer 🟡 IMPROVE: per-missing-kwarg KwargViolation (not
            # short-circuit on first missing) so all gaps surface at once.
            window_lo = max(0, i - 2)
            window_hi = min(len(lines), i + 6)
            window = "\n".join(lines[window_lo:window_hi])
            rel_path = str(py_file.relative_to(REPO_ROOT))
            for kwarg in required_kwargs:
                if f"{kwarg}=" not in window:
                    violations.append(KwargViolation(
                        file=rel_path,
                        line=i + 1,
                        function=function_name,
                        missing_kwarg=kwarg,
                    ))

    return ScanResult(
        function_name=function_name,
        required_kwargs=list(required_kwargs),
        violations=violations,
        files_scanned=files_scanned,
        enforcement_dirs=list(enforcement_dirs),
    )


def scan_all_registry_functions() -> list[ScanResult]:
    """Convenience: scan callers of every registered function. Used by
    parametrized Tier 1 test to verify ALL enforcement-pathway compositional
    contracts in one batch."""
    return [scan_callers(fn) for fn in REQUIRED_KWARGS]
