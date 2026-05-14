"""Round 6 section 4.7 -- ``tools/verify_tier0_drift.py`` full impl (closes B58).

Per **Round 6 section 4.7** at ``docs/migration/phase1/06_deployment.md``
L856-875 (canonical spec -- replaces the Round 3 INTERFACE STUB at the
same path that raised ``NotImplementedError``) + **D77** canonical
6-assertion Tier 0 scaffold + **D74** exit-code contract.

Per spec section 4.7 verbatim (L859-873):

    1. Read every Round 3 section 1-7 Tier 0 sketch + Round 4 section
       3.1-3.11 Tier 0 sketch from the spec docs (regex-extract
       assertions per the canonical 6-assertion contract per D77)
    2. Read every tests/smoke/test_<X>.py file's assertion set
    3. Compute per-file diff:
       - Missing assertion in test file -> RED drift
       - Extra assertion in test file -> YELLOW (Tier 1 bloat per D80;
         flag for Tier 1 promotion)
       - Assertion type mismatch (e.g., spec says PipelineFatalError,
         test catches generic Exception) -> RED drift
    4. Output report at tests/audit_reports/tier0_drift_<date>.md
    5. CI integration: run weekly per Q7 audit drill (Round 5 sec 8.2)
    6. Exit code: 0 clean / 1 yellow drift / 2 red drift per D74

Project-convention note (POLISH_QUEUE candidate)
------------------------------------------------

Spec section 4.7 step 2 references ``tests/smoke/test_<X>.py``; the
actual project layout uses ``tests/tier0/test_<X>.py`` (the Tier 0
directory). The tool walks the actual on-disk layout -- ``tests/tier0/``
is the canonical home for Tier 0 smoke tests in this repo. A future P-N
cosmetic cleanup may reconcile the spec wording with the directory
name; the tool's behavior is unaffected.

What this tool does
-------------------

1. Walks the canonical spec docs (``docs/migration/phase1/03_core_modules.md``
   sections 1-7, ``docs/migration/phase1/04_tools.md`` sections 3.1-3.11)
   and extracts every Tier 0 sketch -- a sketch is the bullet-list of
   letter-prefixed assertions associated with a module / tool name.
2. For each extracted module / tool, locates the corresponding test file
   at ``tests/tier0/test_<X>.py`` (or ``tests/smoke/test_<X>.py`` as a
   fallback per spec wording). Reads the test file via AST and extracts
   the set of letter-prefixed assertions implemented as test functions
   (e.g. ``test_a_module_imports``, ``test_b_help_exits_0``).
3. Computes the per-file diff:
     - SPEC minus TESTS (in spec, missing in tests) -> RED drift
     - TESTS minus SPEC (in tests, not in spec) -> YELLOW (candidate
       Tier 1 promotion)
     - File entirely absent -> RED MISSING_TEST_FILE
     - Exception-type mismatch (spec says ``PipelineFatalError``, test
       catches generic ``Exception``) -> RED TYPE_MISMATCH
4. Renders a Markdown report at
   ``tests/audit_reports/tier0_drift_<YYYY-MM-DD>.md`` (configurable via
   ``--report-path``).
5. Writes a ``CLI_VERIFY_TIER0_DRIFT`` audit row to
   ``General.ops.PipelineEventLog`` per D76 (skippable via
   ``--no-audit-event`` for pipeline-programmatic invocations).
6. Exits per D74:
     * 0 -- no drift OR only ``match`` outcomes (clean)
     * 1 -- yellow drift (Tier 1 bloat -- extras present)
     * 2 -- red drift (missing assertion / file / type mismatch present)

CLI contract
------------

::

    # Weekly CI audit drill (Round 5 section 8.2)
    python3 tools/verify_tier0_drift.py --actor automic

    # Operator dry-run preview (default behavior)
    python3 tools/verify_tier0_drift.py

    # Restrict to a single module (fast dev feedback)
    python3 tools/verify_tier0_drift.py --module enforce_retention

    # Override report destination
    python3 tools/verify_tier0_drift.py --report-path /tmp/drift_today.md

    # Emit machine-readable JSON to stdout (still writes report file)
    python3 tools/verify_tier0_drift.py --json

Exit codes (per D74 + spec section 4.7 L873)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* **0** -- no drift detected (or only ``match`` outcomes)
* **1** -- yellow drift (Tier 1 bloat -- extras present)
* **2** -- red drift (missing assertion / file / type mismatch)

Audit row (per D76 + CLAUDE.md CLI_* family registration)
---------------------------------------------------------

* ``General.ops.PipelineEventLog.EventType = 'CLI_VERIFY_TIER0_DRIFT'``
* ONE row per INVOCATION; ``Status`` mapped from exit code
  (0/1 -> 'SUCCESS', 2 -> 'FAILED')
* ``Metadata`` JSON shape::

    {
        "event_kind": "tier0_drift_audit",
        "actor": "<operator>",
        "report_path": "<absolute path>",
        "modules_checked": <int>,
        "files_red": <int>,
        "files_yellow": <int>,
        "files_clean": <int>,
        "missing_assertions": <int>,
        "extra_assertions": <int>,
        "type_mismatches": <int>,
        "missing_test_files": <int>,
        "exit_code": <int>,
        "started_at": "<ISO-8601 naive-UTC>",
        "completed_at": "<ISO-8601 naive-UTC>"
    }

Classification per ``udm-execution-classifier`` skill
-----------------------------------------------------

* **Trigger**: PRIMARY: Scheduled (Q7 audit drill per Round 5 section
  8.2 -- weekly cadence). SECONDARY: Manual operator dev feedback
  (``--module`` subset).
* **Frequency**: PRIMARY Recurring weekly; SECONDARY ad-hoc.
* **Idempotency**: YES -- read-only on filesystem and spec docs; the
  only side-effect is the audit row INSERT + the report file write
  (overwrite by date). Multi-invocation on the same day overwrites the
  report and produces multiple audit rows (intentional per D26
  append-only audit).
* **Concurrency**: No sp_getapplock -- read-only on spec/test files. Two
  concurrent invocations produce two report-file overwrites which is
  benign (idempotent given identical inputs).
* **Audit-row family**: ``CLI_VERIFY_TIER0_DRIFT`` per D76 + CLAUDE.md
  CLI_* family registry (one of the canonical CLI_* family values).
* **Routing**: PRIMARY tracker ``phase1/02_configuration.md`` section
  5.1 (proposed JOB_TIER0_DRIFT_VERIFY weekly job, NOT in frozen-11 --
  added via amendment per Round 7 governance). SECONDARY tracker
  ``ONE_OFF_SCRIPTS.md`` operator tools.

D-numbers consumed
------------------

D67 (Tier 0 build-time smoke discipline),
D68 (error class hierarchy),
D74 (CLI exit-code contract 0/1/2),
D75 (CLI argument naming -- actor/apply/dry-run/json/verbose/quiet/
no-audit-event),
D76 (audit-row contract CLI_VERIFY_TIER0_DRIFT),
D77 (Tier 0 6-canonical assertion scaffold),
D80 (Tier 0 vs Tier 1 boundary -- extras are Tier 1 promotion candidates,
not Tier 0 failures),
D92 (forward-only additive -- replaces stub with full impl; preserves
public surface of ``verify_tier0_drift()`` + ``TierZeroDriftReport``).

B-numbers closed
----------------

B58 (this tool -- Round 3 INTERFACE STUB -> Round 6 full implementation).

Cross-references
----------------

* R19 (Tier 0 drift risk -- this tool is the mitigation),
* B85 (utils.errors -- canonical exception module imports),
* B214 (test injection points -- no bare sys.modules writes),
* B228 (canonical utils.errors imports -- this tool uses them).
"""

from __future__ import annotations

import argparse
import ast
import json
import logging
import os
import re
import sys
import textwrap
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

# Project root on sys.path so we can reach utils.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Canonical exception module per B228 (utils.errors is the project surface).
# Import a base class for fatal config errors; fall through to defensive
# fallback if utils is unavailable (matches sibling-tool defensive idiom).
try:
    from utils.errors import PipelineFatalError  # noqa: E402,F401
except (ImportError, ModuleNotFoundError):  # pragma: no cover - defensive
    class PipelineFatalError(Exception):  # type: ignore[no-redef]
        """Fallback when utils.errors is unavailable."""

        def __init__(self, message: str, *, metadata: dict | None = None) -> None:
            super().__init__(message)
            self.metadata = metadata or {}

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exit-code constants (per D74 + spec section 4.7 L873)
# ---------------------------------------------------------------------------

EXIT_SUCCESS = 0  # No drift (or match-only)
EXIT_YELLOW = 1  # Yellow drift only (Tier 1 bloat extras)
EXIT_RED = 2  # Red drift (missing / type mismatch / missing file)

# D76 EventType per CLI_* family (CLAUDE.md registration).
EVENT_TYPE = "CLI_VERIFY_TIER0_DRIFT"

# Canonical spec doc paths (per spec section 4.7 step 1).
DEFAULT_SPEC_DOC_PATHS = (
    "docs/migration/phase1/03_core_modules.md",
    "docs/migration/phase1/04_tools.md",
)

# Default Tier 0 test directories -- project uses tests/tier0/; spec text
# mentions tests/smoke/ (POLISH_QUEUE candidate). We walk both and prefer
# tests/tier0/ when both exist.
DEFAULT_TIER0_DIRS = ("tests/tier0", "tests/smoke")

# Default report output directory.
DEFAULT_REPORT_DIR = "tests/audit_reports"


# ---------------------------------------------------------------------------
# Datetime helper (per CDC-NOW-MS / SCD2-P1-f invariant)
# ---------------------------------------------------------------------------


def _now_naive_utc_ms() -> datetime:
    """Return tz-naive UTC datetime truncated to milliseconds.

    Per CDC-NOW-MS / SCD2-P1-f invariant -- naive + ms precision matches
    the BCP/pyodbc storage format on both sides.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return now.replace(microsecond=(now.microsecond // 1000) * 1000)


def _format_iso(dt: datetime) -> str:
    """Render a naive-UTC datetime as a canonical ISO-8601 'Z' string."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Actor detection (per section 1.7 invocation-pattern heuristic)
# ---------------------------------------------------------------------------


def _detect_actor() -> str:
    """Resolve ``--actor`` default per spec section 1.7."""
    if os.environ.get("AUTOMIC_RUN_ID"):
        return "automic"
    try:
        if sys.stdin.isatty():
            return "operator"
    except (AttributeError, ValueError):
        pass
    return "pipeline"


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

# Drift severity per spec section 4.7 + D80.
DriftSeverity = Literal["red", "yellow", "match"]


@dataclass(frozen=True)
class AssertionSpec:
    """One spec-level Tier 0 assertion extracted from a sketch.

    ``letter`` is the bullet-letter ('a', 'b', ...); ``description`` is
    the verbatim text after the letter. ``exception_class`` is populated
    when the assertion explicitly names a raised exception class (e.g.
    'raises PipelineFatalError', 'raises VaultConfigError') so we can
    detect the type-mismatch drift class.
    """

    letter: str
    description: str
    exception_class: str | None = None


@dataclass(frozen=True)
class TestAssertion:
    """One assertion extracted from a Tier 0 test file."""

    letter: str
    function_name: str
    exception_classes: tuple[str, ...] = ()


@dataclass(frozen=True)
class DriftFinding:
    """One drift finding for one module / test-file pair."""

    module_name: str
    spec_doc: str
    spec_line: int
    test_file: str | None
    drift_type: Literal[
        "match",
        "missing_assertion",
        "extra_assertion",
        "type_mismatch",
        "missing_test_file",
    ]
    severity: DriftSeverity
    detail: str
    letter: str | None = None


@dataclass
class TierZeroDriftReport:
    """Aggregate drift report across all modules / tools.

    Mutable to allow incremental population during the walk.
    """

    findings: list[DriftFinding] = field(default_factory=list)
    modules_checked: int = 0
    files_red: int = 0
    files_yellow: int = 0
    files_clean: int = 0
    missing_assertions: int = 0
    extra_assertions: int = 0
    type_mismatches: int = 0
    missing_test_files: int = 0
    overall: DriftSeverity = "match"
    started_at: datetime = field(default_factory=_now_naive_utc_ms)
    completed_at: datetime | None = None
    report_path: str | None = None

    def aggregate(self) -> None:
        """Compute aggregate counts + overall severity from findings."""
        files_red: set[str] = set()
        files_yellow: set[str] = set()
        files_clean: set[str] = set()
        for f in self.findings:
            key = f.module_name
            if f.severity == "red":
                files_red.add(key)
            elif f.severity == "yellow":
                files_yellow.add(key)
            else:
                files_clean.add(key)
            if f.drift_type == "missing_assertion":
                self.missing_assertions += 1
            elif f.drift_type == "extra_assertion":
                self.extra_assertions += 1
            elif f.drift_type == "type_mismatch":
                self.type_mismatches += 1
            elif f.drift_type == "missing_test_file":
                self.missing_test_files += 1
        # A module is "red" if ANY of its findings are red; "yellow" if
        # all non-match findings are yellow.
        files_yellow -= files_red
        files_clean -= files_red | files_yellow
        self.files_red = len(files_red)
        self.files_yellow = len(files_yellow)
        self.files_clean = len(files_clean)
        if self.files_red > 0:
            self.overall = "red"
        elif self.files_yellow > 0:
            self.overall = "yellow"
        else:
            self.overall = "match"


# ---------------------------------------------------------------------------
# Tier 0 sketch extraction from spec docs
# ---------------------------------------------------------------------------

# Match the "Tier 0 smoke" sketch headers in 03_core_modules.md and
# 04_tools.md. Two patterns observed in the corpus:
#   1. "**Tier 0 smoke test** (per section 1.6 + D67): `tests/smoke/test_X.py` --
#      runs in <5s ... Asserts: (a) ...; (b) ...; (c) ..."
#   2. "**Tier 0 smoke (per D67 -- backfilled at Round 3 close-out per B55)**:
#      assert (a) ...; (b) ...; (c) ..."
# The bullet letters appear inline, parenthesized: (a), (b), ... up through
# (h) typically. We capture the full sentence after each letter up to the
# next "(<letter>)" or the end of the paragraph.
_SKETCH_HEADER_RE = re.compile(
    r"\*\*Tier 0[^*]*\*\*[^`]*?(?:`tests/(?:smoke|tier0)/test_(?P<module_a>[a-zA-Z0-9_]+)\.py`|"
    r"assert\b)",
    re.IGNORECASE,
)

# Bullet-letter assertion match: "(a) ...", "(b) ...".
_ASSERTION_RE = re.compile(
    r"\(([a-z])\)\s+([^()]+?)(?=\s*\([a-z]\)|;\s*\([a-z]\)|\Z|\n\n)",
    re.DOTALL,
)

# Section heading discovery. Matches lines like:
#   ### section 3.8 `tools/enforce_retention.py`
#   ### Module: `parquet_writer`
#   ### 3.6 `tools/promote_test_to_prod.py`
_SECTION_HEADING_RE = re.compile(
    r"^###\s+(?:section\s+)?(?:[§]\s+)?([\d.]+)?\s*(?:Module:\s+)?`(?:tools/)?([a-zA-Z0-9_/.]+?)(?:\.py)?`",
    re.MULTILINE,
)

# Exception-class name reference inside an assertion description.
_EXCEPTION_NAME_RE = re.compile(
    r"\b(?:raise[sd]?|raising|catches?|catching)\s+`?([A-Z][A-Za-z0-9_]+(?:Error|Exception|Conflict|Missing|Mismatch|NotFound|Crash|Timeout|Denied|Unavailable|Failed|Stuck|Invalid))`?",
)


def _resolve_module_name(section_path: str, sketch_file_hint: str | None) -> str:
    """Pick the canonical module name for a Tier 0 sketch.

    Prefer the explicit test-file hint from the sketch header (e.g.
    'test_parquet_writer.py' -> 'parquet_writer'); fall back to the
    last path component of the section heading reference (e.g.
    'tools/enforce_retention' -> 'enforce_retention').
    """
    if sketch_file_hint:
        return sketch_file_hint
    base = section_path.rsplit("/", 1)[-1]
    if base.endswith(".py"):
        base = base[:-3]
    return base


def _extract_exception_class(description: str) -> str | None:
    """Return the first exception-class name referenced in the description.

    Conservative: only return a name when the description explicitly says
    'raise(s)' / 'raising' / 'catch(es)' nearby. Avoids false-positive
    name lifts like 'returns ParquetWriteResult'.
    """
    match = _EXCEPTION_NAME_RE.search(description)
    if match:
        return match.group(1)
    return None


def _extract_sketches_from_doc(
    doc_path: Path,
    *,
    file_reader: Callable[[Path], str] | None = None,
) -> dict[str, dict]:
    """Walk a spec doc and return ``{module_name: {spec_line, assertions, ...}}``.

    Parameters
    ----------
    doc_path:
        Spec document path (relative or absolute).
    file_reader:
        Injection point -- defaults to ``Path.read_text``. Tests inject a
        synthetic reader to avoid filesystem dependencies (per B214).
    """
    if file_reader is None:
        def _default_reader(p: Path) -> str:
            return p.read_text(encoding="utf-8")

        file_reader = _default_reader
    try:
        text = file_reader(doc_path)
    except FileNotFoundError:
        logger.warning("Spec doc not found: %s", doc_path)
        return {}

    # Walk section headings to associate sketches with section paths.
    headings: list[tuple[int, str, str]] = []
    for m in _SECTION_HEADING_RE.finditer(text):
        line_idx = text.count("\n", 0, m.start()) + 1
        headings.append((line_idx, m.group(1) or "", m.group(2)))

    def _section_for(line_idx: int) -> tuple[str, str]:
        section_id = ""
        section_path = ""
        for hl, sid, spath in headings:
            if hl <= line_idx:
                section_id = sid
                section_path = spath
            else:
                break
        return section_id, section_path

    sketches: dict[str, dict] = {}
    for m in _SKETCH_HEADER_RE.finditer(text):
        line_idx = text.count("\n", 0, m.start()) + 1
        section_id, section_path = _section_for(line_idx)
        sketch_file_hint = m.group("module_a")
        module_name = _resolve_module_name(section_path, sketch_file_hint)

        body_start = m.start()
        body_end_candidates = [
            text.find("\n\n", body_start + 1),
            text.find("\n### ", body_start + 1),
            text.find("\n---", body_start + 1),
        ]
        body_end_candidates = [c for c in body_end_candidates if c != -1]
        body_end = min(body_end_candidates) if body_end_candidates else len(text)
        body = text[body_start:body_end]

        assertions: list[AssertionSpec] = []
        seen_letters: set[str] = set()
        for am in _ASSERTION_RE.finditer(body):
            letter = am.group(1)
            desc = am.group(2).strip().rstrip(";.")
            if letter in seen_letters:
                continue
            seen_letters.add(letter)
            assertions.append(
                AssertionSpec(
                    letter=letter,
                    description=desc,
                    exception_class=_extract_exception_class(desc),
                )
            )

        if not assertions:
            continue

        # Only keep the FIRST sketch per module (forward-only -- first
        # mention wins; later mentions are typically Round 5 expansions).
        if module_name not in sketches:
            sketches[module_name] = {
                "spec_doc": str(doc_path),
                "spec_line": line_idx,
                "section_id": section_id,
                "assertions": assertions,
            }
    return sketches


def extract_spec_assertions(
    *,
    spec_doc_paths: tuple[str, ...] = DEFAULT_SPEC_DOC_PATHS,
    project_root: Path | None = None,
    file_reader: Callable[[Path], str] | None = None,
) -> dict[str, dict]:
    """Extract Tier 0 sketch assertions from all spec docs.

    Returns ``{module_name: {spec_doc, spec_line, section_id, assertions}}``.
    Modules with no sketches are absent from the result.
    """
    if project_root is None:
        project_root = Path(__file__).resolve().parent.parent
    combined: dict[str, dict] = {}
    for relative in spec_doc_paths:
        doc_path = project_root / relative
        sketches = _extract_sketches_from_doc(doc_path, file_reader=file_reader)
        for module_name, info in sketches.items():
            combined.setdefault(module_name, info)
    return combined


# ---------------------------------------------------------------------------
# Test-file assertion extraction (via ast)
# ---------------------------------------------------------------------------

# Match test functions whose name encodes a letter prefix, e.g.
# 'test_a_module_imports', 'test_b_help_exits_0', 'test_d_sp10_...'.
_TEST_FUNC_LETTER_RE = re.compile(r"^test_([a-z])_")

# Pattern to discover exception classes referenced inside test bodies
# (used for type-mismatch detection). We look for `pytest.raises(X)`,
# `raises X`, or `except X as`.
_RAISES_RE = re.compile(
    r"(?:pytest\.raises|\braises\b|\bexcept\b)\s*\(?\s*([A-Z][A-Za-z0-9_]+)",
)


def _extract_assertions_from_test_file(
    test_path: Path,
    *,
    file_reader: Callable[[Path], str] | None = None,
) -> list[TestAssertion]:
    """Parse a Tier 0 test file and return its letter-prefixed test assertions."""
    if file_reader is None:
        def _default_reader(p: Path) -> str:
            return p.read_text(encoding="utf-8")

        file_reader = _default_reader
    try:
        source = file_reader(test_path)
    except FileNotFoundError:
        return []
    try:
        tree = ast.parse(source, filename=str(test_path))
    except SyntaxError as exc:
        logger.error("Test file %s has SyntaxError: %s", test_path, exc)
        return []

    assertions: list[TestAssertion] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if not node.name.startswith("test_"):
            continue
        match = _TEST_FUNC_LETTER_RE.match(node.name)
        if match is None:
            continue
        letter = match.group(1)
        # Extract referenced exception class names from the function body.
        body_source = ast.unparse(node) if hasattr(ast, "unparse") else ""
        exception_classes: list[str] = []
        for rm in _RAISES_RE.finditer(body_source):
            cls_name = rm.group(1)
            if cls_name not in exception_classes:
                exception_classes.append(cls_name)
        assertions.append(
            TestAssertion(
                letter=letter,
                function_name=node.name,
                exception_classes=tuple(exception_classes),
            )
        )
    return assertions


def _resolve_test_file(
    module_name: str,
    *,
    project_root: Path,
    tier0_dirs: tuple[str, ...] = DEFAULT_TIER0_DIRS,
    file_exists: Callable[[Path], bool] | None = None,
) -> Path | None:
    """Locate the Tier 0 test file for ``module_name``."""
    if file_exists is None:
        def _default_exists(p: Path) -> bool:
            return p.exists()

        file_exists = _default_exists
    for d in tier0_dirs:
        candidate = project_root / d / f"test_{module_name}.py"
        if file_exists(candidate):
            return candidate
    return None


# ---------------------------------------------------------------------------
# Drift computation (per spec section 4.7 step 3)
# ---------------------------------------------------------------------------


def _compute_drift_for_module(
    module_name: str,
    spec_info: dict,
    *,
    project_root: Path,
    tier0_dirs: tuple[str, ...] = DEFAULT_TIER0_DIRS,
    file_reader: Callable[[Path], str] | None = None,
    file_exists: Callable[[Path], bool] | None = None,
) -> list[DriftFinding]:
    """Compute drift findings for one module's spec assertions vs test file.

    Drift verdicts per spec section 4.7 step 3:
      - SPEC minus TESTS -> RED missing_assertion
      - TESTS minus SPEC -> YELLOW extra_assertion (Tier 1 promotion candidate)
      - Exception-class mismatch -> RED type_mismatch
      - Test file absent entirely -> RED missing_test_file
    """
    spec_doc = spec_info["spec_doc"]
    spec_line = spec_info["spec_line"]
    spec_assertions: list[AssertionSpec] = spec_info["assertions"]

    test_path = _resolve_test_file(
        module_name,
        project_root=project_root,
        tier0_dirs=tier0_dirs,
        file_exists=file_exists,
    )
    if test_path is None:
        searched = [
            str(project_root / d / f"test_{module_name}.py") for d in tier0_dirs
        ]
        return [
            DriftFinding(
                module_name=module_name,
                spec_doc=spec_doc,
                spec_line=spec_line,
                test_file=None,
                drift_type="missing_test_file",
                severity="red",
                detail=(
                    f"No Tier 0 test file found for module {module_name!r}. "
                    f"Searched: {searched}"
                ),
            )
        ]

    test_assertions = _extract_assertions_from_test_file(
        test_path, file_reader=file_reader
    )
    spec_by_letter = {a.letter: a for a in spec_assertions}
    tests_by_letter = {a.letter: a for a in test_assertions}

    findings: list[DriftFinding] = []

    # SPEC minus TESTS -- missing assertions in test file.
    for letter, spec_a in spec_by_letter.items():
        if letter not in tests_by_letter:
            findings.append(
                DriftFinding(
                    module_name=module_name,
                    spec_doc=spec_doc,
                    spec_line=spec_line,
                    test_file=str(test_path),
                    drift_type="missing_assertion",
                    severity="red",
                    detail=(
                        f"Assertion ({letter}) in spec but no matching "
                        f"test_{letter}_* function in {test_path.name}. "
                        f"Spec text: {spec_a.description[:200]!r}"
                    ),
                    letter=letter,
                )
            )
            continue
        test_a = tests_by_letter[letter]
        spec_exc = spec_a.exception_class
        if spec_exc and test_a.exception_classes:
            if (
                spec_exc not in test_a.exception_classes
                and "Exception" in test_a.exception_classes
            ):
                # Test catches generic Exception when spec names a specific
                # subclass -- explicit type mismatch.
                findings.append(
                    DriftFinding(
                        module_name=module_name,
                        spec_doc=spec_doc,
                        spec_line=spec_line,
                        test_file=str(test_path),
                        drift_type="type_mismatch",
                        severity="red",
                        detail=(
                            f"Spec ({letter}) names {spec_exc!r} but test "
                            f"{test_a.function_name!r} catches generic "
                            f"'Exception' (caught: {list(test_a.exception_classes)})."
                        ),
                        letter=letter,
                    )
                )
                continue
            if spec_exc not in test_a.exception_classes:
                # Spec names a specific exception but test references a
                # different exception entirely -- red mismatch.
                findings.append(
                    DriftFinding(
                        module_name=module_name,
                        spec_doc=spec_doc,
                        spec_line=spec_line,
                        test_file=str(test_path),
                        drift_type="type_mismatch",
                        severity="red",
                        detail=(
                            f"Spec ({letter}) names {spec_exc!r} but test "
                            f"{test_a.function_name!r} references "
                            f"{list(test_a.exception_classes)} -- type mismatch."
                        ),
                        letter=letter,
                    )
                )
                continue
        # Otherwise -- match.
        findings.append(
            DriftFinding(
                module_name=module_name,
                spec_doc=spec_doc,
                spec_line=spec_line,
                test_file=str(test_path),
                drift_type="match",
                severity="match",
                detail=(
                    f"Assertion ({letter}) matches between spec and "
                    f"{test_a.function_name}."
                ),
                letter=letter,
            )
        )

    # TESTS minus SPEC -- extras (Tier 1 promotion candidates per D80).
    for letter, test_a in tests_by_letter.items():
        if letter not in spec_by_letter:
            findings.append(
                DriftFinding(
                    module_name=module_name,
                    spec_doc=spec_doc,
                    spec_line=spec_line,
                    test_file=str(test_path),
                    drift_type="extra_assertion",
                    severity="yellow",
                    detail=(
                        f"Test {test_a.function_name!r} (letter {letter!r}) "
                        f"has no matching ({letter}) in spec -- Tier 1 promotion "
                        f"candidate per D80."
                    ),
                    letter=letter,
                )
            )
    return findings


# ---------------------------------------------------------------------------
# Top-level drift verification (per spec section 4.7 step 4)
# ---------------------------------------------------------------------------


def verify_tier0_drift(
    *,
    project_root: Path | str | None = None,
    spec_doc_paths: tuple[str, ...] = DEFAULT_SPEC_DOC_PATHS,
    tier0_dirs: tuple[str, ...] = DEFAULT_TIER0_DIRS,
    module_filter: list[str] | None = None,
    file_reader: Callable[[Path], str] | None = None,
    file_exists: Callable[[Path], bool] | None = None,
) -> TierZeroDriftReport:
    """Walk spec docs + Tier 0 test files and emit a drift report.

    Parameters
    ----------
    project_root:
        Project root path. Defaults to the parent of this module's
        directory.
    spec_doc_paths:
        Relative paths to spec docs containing Tier 0 sketches.
    tier0_dirs:
        Relative paths to Tier 0 test directories.
    module_filter:
        Optional list of module names to restrict the audit to.
    file_reader / file_exists:
        Test-injection hooks. Defaults to live filesystem access.

    Returns
    -------
    TierZeroDriftReport with all findings + aggregated counts + overall.
    """
    if project_root is None:
        project_root = Path(__file__).resolve().parent.parent
    elif isinstance(project_root, str):
        project_root = Path(project_root)

    report = TierZeroDriftReport()

    spec_modules = extract_spec_assertions(
        spec_doc_paths=spec_doc_paths,
        project_root=project_root,
        file_reader=file_reader,
    )
    if module_filter:
        spec_modules = {k: v for k, v in spec_modules.items() if k in module_filter}

    for module_name in sorted(spec_modules.keys()):
        report.modules_checked += 1
        findings = _compute_drift_for_module(
            module_name,
            spec_modules[module_name],
            project_root=project_root,
            tier0_dirs=tier0_dirs,
            file_reader=file_reader,
            file_exists=file_exists,
        )
        report.findings.extend(findings)

    report.completed_at = _now_naive_utc_ms()
    report.aggregate()
    return report


# ---------------------------------------------------------------------------
# Markdown report rendering (per spec section 4.7 step 4)
# ---------------------------------------------------------------------------


def _severity_badge(severity: DriftSeverity) -> str:
    if severity == "red":
        return "RED"
    if severity == "yellow":
        return "YELLOW"
    return "GREEN"


def render_markdown_report(report: TierZeroDriftReport) -> str:
    """Render the drift report as Markdown.

    Layout per spec section 4.7 step 4:
      - Header: date + overall verdict + aggregate counts
      - Per-module section: spec-doc link + per-finding rows
      - Trailing: legend + exit-code mapping reference
    """
    started = _format_iso(report.started_at)
    completed = (
        _format_iso(report.completed_at) if report.completed_at else "--"
    )
    overall = _severity_badge(report.overall)
    lines: list[str] = []
    lines.append(f"# Tier 0 Drift Audit Report -- {date.today().isoformat()}")
    lines.append("")
    lines.append("Generated by `tools/verify_tier0_drift.py` (closes B58).")
    lines.append("")
    lines.append(f"- Started: {started}")
    lines.append(f"- Completed: {completed}")
    lines.append(f"- Overall verdict: **{overall}**")
    lines.append(f"- Modules checked: {report.modules_checked}")
    lines.append(f"- Files red: {report.files_red}")
    lines.append(f"- Files yellow: {report.files_yellow}")
    lines.append(f"- Files clean: {report.files_clean}")
    lines.append(f"- Missing assertions: {report.missing_assertions}")
    lines.append(f"- Extra assertions: {report.extra_assertions}")
    lines.append(f"- Type mismatches: {report.type_mismatches}")
    lines.append(f"- Missing test files: {report.missing_test_files}")
    lines.append("")
    lines.append("## Legend")
    lines.append("")
    lines.append(
        "- **RED**: missing assertion in test file, missing test file, or "
        "exception-type mismatch (exit 2 per D74)"
    )
    lines.append(
        "- **YELLOW**: extra assertion in test file -- Tier 1 promotion "
        "candidate per D80 (exit 1 per D74)"
    )
    lines.append(
        "- **GREEN**: spec assertion matches test (no drift) (exit 0 per D74)"
    )
    lines.append("")
    lines.append("## Findings")
    lines.append("")

    if not report.findings:
        lines.append("_No Tier 0 sketches were extracted. Check spec doc paths._")
        lines.append("")
        return "\n".join(lines)

    by_module: dict[str, list[DriftFinding]] = {}
    for f in report.findings:
        by_module.setdefault(f.module_name, []).append(f)

    sev_order = {"red": 2, "yellow": 1, "match": 0}
    for module_name in sorted(by_module.keys()):
        findings = by_module[module_name]
        worst = max(findings, key=lambda f: sev_order.get(f.severity, 0)).severity
        worst_badge = _severity_badge(worst)
        lines.append(f"### `{module_name}` -- {worst_badge}")
        lines.append("")
        for f in findings:
            badge = _severity_badge(f.severity)
            letter = f"({f.letter})" if f.letter else ""
            lines.append(
                f"- **{badge}** {letter} `{f.drift_type}` -- {f.detail}"
            )
            lines.append(f"  - spec: `{f.spec_doc}` L{f.spec_line}")
            if f.test_file:
                lines.append(f"  - test: `{f.test_file}`")
        lines.append("")
    return "\n".join(lines)


def write_report_file(
    report: TierZeroDriftReport,
    report_path: Path,
    *,
    file_writer: Callable[[Path, str], None] | None = None,
) -> Path:
    """Write the rendered report to ``report_path``.

    ``file_writer`` is an injection hook for tests; defaults to
    ``Path.write_text`` (creating parent dirs if missing).
    """
    if file_writer is None:
        def _default_writer(p: Path, content: str) -> None:
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")

        file_writer = _default_writer

    content = render_markdown_report(report)
    file_writer(report_path, content)
    report.report_path = str(report_path)
    return report_path


# ---------------------------------------------------------------------------
# Audit-row writer
# ---------------------------------------------------------------------------


def _write_audit_row(
    metadata: dict,
    *,
    status: str,
    error_message: str | None = None,
    cursor_factory: Callable | None = None,
    general_db: str = "General",
    skip: bool = False,
) -> int | None:
    """INSERT one ``CLI_VERIFY_TIER0_DRIFT`` row into PipelineEventLog.

    Per D76. Best-effort: failures logged but do not affect verdict. When
    ``skip=True`` (test path / ``--no-audit-event``), returns None without
    writing. ``cursor_factory`` is an injection hook for tests.
    """
    if skip:
        return None

    metadata_json = json.dumps(metadata, separators=(",", ":"), default=str)
    event_detail = (
        f"verify_tier0_drift / "
        f"overall={metadata.get('overall')} "
        f"modules={metadata.get('modules_checked')}"
    )

    if cursor_factory is None:
        try:
            from utils.connections import get_connection  # type: ignore

            def cursor_factory():  # type: ignore[no-redef]
                return get_connection(general_db)
        except Exception:  # noqa: BLE001
            logger.warning(
                "Audit-row write skipped: utils.connections unavailable; "
                "verdict exit code is authoritative."
            )
            return None

    conn = None
    try:
        conn = cursor_factory()
        try:
            conn.autocommit = True
        except Exception:  # noqa: BLE001
            pass
        cursor = conn.cursor()
        try:
            cursor.execute(
                f"INSERT INTO [{general_db}].ops.PipelineEventLog "
                f"(BatchId, TableName, SourceName, EventType, EventDetail, "
                f" StartedAt, CompletedAt, Status, ErrorMessage, Metadata) "
                f"VALUES (NULL, NULL, NULL, ?, ?, ?, SYSUTCDATETIME(), ?, ?, ?); "
                f"SELECT CAST(SCOPE_IDENTITY() AS BIGINT) AS AuditEventId;",
                EVENT_TYPE,
                event_detail,
                metadata.get("started_at_dt"),
                status,
                error_message,
                metadata_json,
            )
            row = cursor.fetchone() if cursor.description is not None else None
            if row is None or row[0] is None:
                return None
            return int(row[0])
        finally:
            try:
                cursor.close()
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        logger.exception("Failed to write %s audit row", EVENT_TYPE)
        return None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Stdout rendering
# ---------------------------------------------------------------------------


def _emit_human_summary(report: TierZeroDriftReport, *, report_path: Path) -> None:
    """Render a concise human-readable summary."""
    badge = _severity_badge(report.overall)
    print(f"Tier 0 drift audit: {badge}")
    print(f"  modules checked:    {report.modules_checked}")
    print(f"  files red:          {report.files_red}")
    print(f"  files yellow:       {report.files_yellow}")
    print(f"  files clean:        {report.files_clean}")
    print(f"  missing assertions: {report.missing_assertions}")
    print(f"  extra assertions:   {report.extra_assertions}")
    print(f"  type mismatches:    {report.type_mismatches}")
    print(f"  missing test files: {report.missing_test_files}")
    print(f"  report:             {report_path}")


def _emit_json(
    report: TierZeroDriftReport,
    *,
    report_path: Path,
    exit_code: int,
) -> None:
    """Render the canonical JSON payload."""
    payload = {
        "overall": report.overall,
        "modules_checked": report.modules_checked,
        "files_red": report.files_red,
        "files_yellow": report.files_yellow,
        "files_clean": report.files_clean,
        "missing_assertions": report.missing_assertions,
        "extra_assertions": report.extra_assertions,
        "type_mismatches": report.type_mismatches,
        "missing_test_files": report.missing_test_files,
        "report_path": str(report_path),
        "exit_code": exit_code,
        "started_at": _format_iso(report.started_at),
        "completed_at": (
            _format_iso(report.completed_at) if report.completed_at else None
        ),
    }
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


# ---------------------------------------------------------------------------
# Argument parser (per D75 canonical naming)
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    """Build the canonical CLI arg parser (per D75)."""
    parser = argparse.ArgumentParser(
        prog="verify_tier0_drift.py",
        description=textwrap.dedent(
            """\
            Verify Tier 0 smoke tests have not drifted from their spec sketches.

            Per Round 6 section 4.7 (closes B58). Walks the canonical spec
            docs, extracts Tier 0 sketches per D77 6-canonical-assertion
            scaffold, compares to actual tests/tier0/test_<X>.py files,
            and produces a Markdown drift report at
            tests/audit_reports/tier0_drift_<date>.md.
            Exits per D74: 0 clean / 1 yellow / 2 red.
            """
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--actor",
        default=None,
        help="Operator identity (default: auto-detect via TTY / AUTOMIC_RUN_ID).",
    )
    parser.add_argument(
        "--module",
        action="append",
        default=None,
        help=(
            "Restrict audit to one or more module names (repeatable). "
            "Default: walks every module with a Tier 0 sketch."
        ),
    )
    parser.add_argument(
        "--report-path",
        default=None,
        help=(
            "Override report file path. Default: "
            "tests/audit_reports/tier0_drift_<YYYY-MM-DD>.md"
        ),
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        help=(
            "Emit canonical JSON payload to stdout "
            "(still writes the report file)."
        ),
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Increase logging verbosity.",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress stdout summary output.",
    )
    parser.add_argument(
        "--no-audit-event",
        action="store_true",
        help=(
            "Skip the CLI_VERIFY_TIER0_DRIFT PipelineEventLog audit-row write "
            "(intended for pipeline-programmatic invocations per D75)."
        ),
    )
    parser.add_argument(
        "--fail-on-yellow",
        action="store_true",
        help=(
            "Treat yellow drift as fatal (exit 2 instead of exit 1). "
            "Use in strict CI mode."
        ),
    )
    return parser


# ---------------------------------------------------------------------------
# Top-level main()
# ---------------------------------------------------------------------------


def main(
    *,
    actor: str | None = None,
    module: list[str] | None = None,
    report_path: str | None = None,
    json_output: bool = False,
    verbose: bool = False,
    quiet: bool = False,
    no_audit_event: bool = False,
    fail_on_yellow: bool = False,
    # ---- Injection hooks ----
    project_root: Path | str | None = None,
    spec_doc_paths: tuple[str, ...] = DEFAULT_SPEC_DOC_PATHS,
    tier0_dirs: tuple[str, ...] = DEFAULT_TIER0_DIRS,
    file_reader: Callable[[Path], str] | None = None,
    file_exists: Callable[[Path], bool] | None = None,
    file_writer: Callable[[Path, str], None] | None = None,
    audit_cursor_factory: Callable | None = None,
    general_db: str | None = None,
) -> dict:
    """Programmatic entry -- verify Tier 0 drift across spec docs + test files.

    Returns a dict with the canonical audit-row shape (see module docstring).
    Exit-code derivation per D74:
      * 0 -- no drift (or match-only)
      * 1 -- yellow drift only
      * 2 -- red drift (or fail_on_yellow + yellow drift)
    """
    started_at_dt = _now_naive_utc_ms()

    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    elif quiet:
        logging.getLogger().setLevel(logging.ERROR)

    if actor is None:
        actor = _detect_actor()

    if general_db is None:
        try:
            import utils.configuration as config  # type: ignore

            general_db = getattr(config, "GENERAL_DB", "General")
        except Exception:  # noqa: BLE001
            general_db = "General"

    if project_root is None:
        project_root = Path(__file__).resolve().parent.parent
    elif isinstance(project_root, str):
        project_root = Path(project_root)

    # Resolve default report path
    if report_path is None:
        today = date.today().isoformat()
        resolved_report_path = (
            project_root / DEFAULT_REPORT_DIR / f"tier0_drift_{today}.md"
        )
    else:
        resolved_report_path = Path(report_path)
        if not resolved_report_path.is_absolute():
            resolved_report_path = project_root / resolved_report_path

    # Run the audit
    try:
        report = verify_tier0_drift(
            project_root=project_root,
            spec_doc_paths=spec_doc_paths,
            tier0_dirs=tier0_dirs,
            module_filter=module,
            file_reader=file_reader,
            file_exists=file_exists,
        )
    except Exception as exc:  # noqa: BLE001
        # Unexpected -- never silently fail; surface as red drift exit 2.
        logger.exception("Unexpected exception during drift audit")
        result: dict[str, Any] = {
            "event_kind": "tier0_drift_audit",
            "actor": actor,
            "report_path": str(resolved_report_path),
            "modules_checked": 0,
            "overall": "red",
            "files_red": 0,
            "files_yellow": 0,
            "files_clean": 0,
            "missing_assertions": 0,
            "extra_assertions": 0,
            "type_mismatches": 0,
            "missing_test_files": 0,
            "exit_code": EXIT_RED,
            "error_type": type(exc).__name__,
            "error_message": str(exc)[:4000],
            "started_at": _format_iso(started_at_dt),
            "completed_at": _format_iso(_now_naive_utc_ms()),
            "started_at_dt": started_at_dt,
        }
        if not quiet:
            print(f"FATAL: drift audit failed: {exc}", file=sys.stderr)
        audit_id = _write_audit_row(
            result,
            status="FAILED",
            error_message=str(exc)[:4000],
            cursor_factory=audit_cursor_factory,
            general_db=general_db,
            skip=no_audit_event,
        )
        result["audit_event_id"] = audit_id
        return result

    # Write the report file
    try:
        write_report_file(report, resolved_report_path, file_writer=file_writer)
    except Exception:  # noqa: BLE001
        logger.exception("Failed to write report file: %s", resolved_report_path)
        # Continue -- the verdict is still authoritative even without the
        # report file.

    # Derive exit code
    if report.overall == "red":
        exit_code = EXIT_RED
    elif report.overall == "yellow":
        exit_code = EXIT_RED if fail_on_yellow else EXIT_YELLOW
    else:
        exit_code = EXIT_SUCCESS

    # Render stdout
    if not quiet:
        if json_output:
            _emit_json(
                report, report_path=resolved_report_path, exit_code=exit_code
            )
        else:
            _emit_human_summary(report, report_path=resolved_report_path)

    # Build audit-row metadata
    result = {
        "event_kind": "tier0_drift_audit",
        "actor": actor,
        "report_path": str(resolved_report_path),
        "modules_checked": report.modules_checked,
        "overall": report.overall,
        "files_red": report.files_red,
        "files_yellow": report.files_yellow,
        "files_clean": report.files_clean,
        "missing_assertions": report.missing_assertions,
        "extra_assertions": report.extra_assertions,
        "type_mismatches": report.type_mismatches,
        "missing_test_files": report.missing_test_files,
        "exit_code": exit_code,
        "started_at": _format_iso(started_at_dt),
        "completed_at": _format_iso(report.completed_at or _now_naive_utc_ms()),
        "started_at_dt": started_at_dt,
    }

    status = "SUCCESS" if exit_code in (EXIT_SUCCESS, EXIT_YELLOW) else "FAILED"
    err_msg = (
        None if status == "SUCCESS" else f"Red drift: {report.files_red} files"
    )
    audit_id = _write_audit_row(
        result,
        status=status,
        error_message=err_msg,
        cursor_factory=audit_cursor_factory,
        general_db=general_db,
        skip=no_audit_event,
    )
    result["audit_event_id"] = audit_id
    return result


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def cli_main(argv: list[str] | None = None) -> int:
    """CLI wrapper -- parse argv + call main() + return exit code."""
    parser = _build_arg_parser()
    args = parser.parse_args(argv)

    result = main(
        actor=args.actor,
        module=args.module,
        report_path=args.report_path,
        json_output=args.json_output,
        verbose=args.verbose,
        quiet=args.quiet,
        no_audit_event=args.no_audit_event,
        fail_on_yellow=args.fail_on_yellow,
    )

    return int(result.get("exit_code", EXIT_RED))


if __name__ == "__main__":
    sys.exit(cli_main())
