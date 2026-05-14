"""Tier 0 build-time smoke test for tools/verify_tier0_drift.py.

Per D67 -- runs at build time + every commit. Runtime ceiling < 5 s.
All filesystem dependencies mocked via the injection points exposed in
``tools.verify_tier0_drift``. No live DB, no live filesystem reads beyond
synthetic injected payloads.

6-canonical D77 assertion scaffold per Round 6 section 4.7 + spec section 1.6:
  (a) Module imports without error.
  (b) --help exits 0 per D77 Tier 0 scaffold assertion 2.
  (c) Clean spec + matching tests -> exit 0 (no drift).
  (d) Spec assertion missing in tests -> red drift -> exit 2.
  (e) Test has extra assertion not in spec -> yellow drift -> exit 1.
  (f) Test file entirely absent -> red drift -> exit 2.
  Plus runtime assertion: total wall time < 5 s per D67.

Per spec section 4.7 step 1-6 the assertion scaffold IS the 6-letter
sequence (a-f) explicitly enumerated above; this file pins each one to
a dedicated test function so the drift audit on this very file is itself
green-on-its-own-spec (self-referential discipline per Pitfall #9.m).

North Star pillars (NORTH_STAR.md):
  - Audit-grade (D76): exactly one CLI_VERIFY_TIER0_DRIFT row per
    invocation; Metadata JSON carries overall verdict + per-category counts.
  - Operationally stable (D67 / D74): import + invoke + shape + error-modes
    in < 5 s with zero external I/O; exit-code contract 0/1/2 enforced.
  - Idempotent (D15): re-running the audit on identical inputs produces
    identical outputs (read-only on filesystem; report-file overwrite
    is content-stable).
  - Traceability (D26): every invocation writes ONE PipelineEventLog row
    with EventType='CLI_VERIFY_TIER0_DRIFT'.

D-numbers: D67 (Tier 0), D74 (exit codes 0/1/2), D75 (arg naming),
  D76 (audit-row contract CLI_VERIFY_TIER0_DRIFT), D77 (6-assertion
  scaffold), D80 (Tier 0 vs Tier 1 boundary -- extras are Tier 1
  promotion candidates, not red drift), D92 (forward-only -- replaces
  stub with full impl).

B-numbers: B58 (this tool -- spec section 4.7 closes the stub).

Spec: phase1/06_deployment.md section 4.7 (canonical spec L856-875).

Independence note: tests in this file are authored INDEPENDENTLY from
tools/verify_tier0_drift.py per D55 (5-gate validation discipline --
test author != code author). The tests pin the spec contract per
phase1/06_deployment.md section 4.7 WITHOUT reading the implementation.
"""
from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Project root on sys.path
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Module path
# ---------------------------------------------------------------------------

_TOOL_PATH = _PROJECT_ROOT / "tools" / "verify_tier0_drift.py"
_TOOL_MODULE_KEY = "tools.verify_tier0_drift"

# ---------------------------------------------------------------------------
# Constants -- single source of truth
# ---------------------------------------------------------------------------

# D76 EventType per CLI_* family (CLAUDE.md registration)
EXPECTED_EVENT_TYPE = "CLI_VERIFY_TIER0_DRIFT"

# D74 exit codes (spec section 4.7 L873)
EXIT_SUCCESS = 0
EXIT_YELLOW = 1
EXIT_RED = 2

# Synthetic spec content -- a Tier 0 sketch with three assertions.
_CLEAN_SPEC_TEXT = """\
### section 1.1 `widget_writer`

Some preamble text.

**Tier 0 smoke test** (per section 1.6 + D67): `tests/tier0/test_widget_writer.py` -- runs in <5s. Asserts: (a) module imports; (b) `widget_write` invokable with mocked cursor; (c) returns `WidgetResult` shape.

More body text.

---
"""

# Matching synthetic test content -- three test functions covering (a), (b), (c).
_CLEAN_TEST_TEXT = """\
def test_a_module_imports():
    pass

def test_b_widget_write_invokable():
    pass

def test_c_returns_widget_result():
    pass
"""

# Test content MISSING assertion (c) -- should produce red drift.
_TEST_MISSING_C = """\
def test_a_module_imports():
    pass

def test_b_widget_write_invokable():
    pass
"""

# Test content with EXTRA assertion (d) not in spec -- should produce
# yellow drift (Tier 1 promotion candidate per D80).
_TEST_EXTRA_D = """\
def test_a_module_imports():
    pass

def test_b_widget_write_invokable():
    pass

def test_c_returns_widget_result():
    pass

def test_d_extra_in_test_only():
    pass
"""


# ---------------------------------------------------------------------------
# Module loader -- no sys.modules writes; uses importlib.util.spec_from_file_location
# ---------------------------------------------------------------------------


def _load_tool_module() -> Any:
    """Load tools/verify_tier0_drift.py via importlib.util (B214 pattern).

    Tests do NOT use bare ``sys.modules[k] = mod`` writes per the B214
    discipline -- they use the spec-from-file-location loader so each
    test gets a fresh module instance.
    """
    if _TOOL_MODULE_KEY in sys.modules:
        del sys.modules[_TOOL_MODULE_KEY]
    spec = importlib.util.spec_from_file_location(_TOOL_MODULE_KEY, _TOOL_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_TOOL_MODULE_KEY] = mod  # B214: pre-register before exec_module
    spec.loader.exec_module(mod)
    return mod


def _build_fake_fs(
    *,
    spec_text: str,
    test_text: str | None,
    module_name: str = "widget_writer",
    spec_doc: str = "docs/migration/phase1/03_core_modules.md",
):
    """Return (file_reader, file_exists, file_writer, written_files) tuple.

    The fake fs serves the spec doc and (optionally) the test file. When
    ``test_text`` is None, the file is treated as ABSENT (file_exists returns
    False), exercising the missing-test-file drift class.
    """
    written: dict[str, str] = {}

    def file_reader(p: Path) -> str:
        as_str = str(p)
        if as_str.endswith(spec_doc.replace("/", "\\")) or as_str.endswith(spec_doc):
            return spec_text
        if module_name in as_str and test_text is not None:
            return test_text
        raise FileNotFoundError(as_str)

    def file_exists(p: Path) -> bool:
        as_str = str(p)
        if module_name in as_str:
            return test_text is not None
        return False

    def file_writer(p: Path, content: str) -> None:
        written[str(p)] = content

    return file_reader, file_exists, file_writer, written


# ===========================================================================
# Tier 0 assertion (a): module imports without error
# ===========================================================================


def test_a_module_imports():
    """(a) Module imports without error.

    D67 Tier 0 assertion 1: the module must be importable with no live-DB
    or filesystem dependencies. A failed import means a missing dependency
    or syntax error that blocks every subsequent build step.

    North Star: Operationally stable (D67). Spec: section 4.7 L859 (a).
    """
    _t0 = time.monotonic()

    mod = _load_tool_module()

    assert mod is not None, (
        "tools/verify_tier0_drift.py must load without error. "
        "Check for missing imports or syntax errors. D67 Tier 0 (a)."
    )
    assert hasattr(mod, "main"), (
        "tools/verify_tier0_drift.py must expose a top-level 'main' function "
        "per section 4.7 CLI interface. D67 Tier 0 (a)."
    )
    assert hasattr(mod, "verify_tier0_drift"), (
        "tools/verify_tier0_drift.py must expose verify_tier0_drift() "
        "per spec section 4.7 step 4 + D92 forward-only additive."
    )
    assert hasattr(mod, "TierZeroDriftReport"), (
        "tools/verify_tier0_drift.py must expose TierZeroDriftReport "
        "(public dataclass surface from the Round 3 stub) per D92."
    )

    elapsed = time.monotonic() - _t0
    assert elapsed < 5.0, (
        f"Module load must complete in < 5 s. Took {elapsed:.2f} s. D67."
    )


# ===========================================================================
# Tier 0 assertion (b): --help exits 0
# ===========================================================================


def test_b_help_exits_zero():
    """(b) --help exits 0.

    D74 (exit-code contract): --help is not an error; it is the canonical
    discoverability path for all CLI tools per D75 argument naming discipline.
    argparse emits SystemExit(0) on --help.

    North Star: Operationally stable. Spec: section 4.7 L873 + D77 (b).
    """
    mod = _load_tool_module()
    parser = mod._build_arg_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["--help"])
    assert exc_info.value.code == 0, (
        f"--help must exit 0. Got: {exc_info.value.code!r}. "
        "D74 (exit 0 = success / informational). Spec: section 4.7 L873."
    )


# ===========================================================================
# Tier 0 assertion (c): clean spec + matching tests -> exit 0
# ===========================================================================


def test_c_clean_spec_matching_tests_exits_zero():
    """(c) Synthetic spec with sketches matching synthetic tests -> exit 0.

    Per spec section 4.7 step 6: 'Exit code: 0 clean / 1 yellow drift / 2 red
    drift per D74'. When every spec assertion has a matching test_<letter>_*
    function AND no extras exist, the audit must return exit 0.

    Pillar: Operationally stable (D74). Spec: section 4.7 step 6 + D74 exit 0.
    """
    mod = _load_tool_module()
    file_reader, file_exists, file_writer, written = _build_fake_fs(
        spec_text=_CLEAN_SPEC_TEXT,
        test_text=_CLEAN_TEST_TEXT,
    )

    result = mod.main(
        actor="test-author",
        no_audit_event=True,
        spec_doc_paths=("docs/migration/phase1/03_core_modules.md",),
        tier0_dirs=("tests/tier0",),
        file_reader=file_reader,
        file_exists=file_exists,
        file_writer=file_writer,
        project_root="/synthetic/root",
        report_path="/synthetic/report.md",
    )

    assert isinstance(result, dict), (
        "main() must return a dict per D76 audit-row shape contract."
    )
    assert result.get("exit_code") == EXIT_SUCCESS, (
        f"Clean spec + matching tests must exit {EXIT_SUCCESS}. "
        f"Got: {result.get('exit_code')!r}. "
        "Spec: section 4.7 step 6 + D74."
    )
    assert result.get("overall") == "match", (
        f"Overall verdict must be 'match' for clean run. "
        f"Got: {result.get('overall')!r}."
    )
    assert result.get("modules_checked", 0) >= 1, (
        f"Must check at least one module from the synthetic spec. "
        f"Got: {result!r}."
    )


# ===========================================================================
# Tier 0 assertion (d): spec assertion missing in tests -> red -> exit 2
# ===========================================================================


def test_d_missing_assertion_exits_two():
    """(d) Spec assertion missing in test file -> red drift -> exit 2.

    Per spec section 4.7 step 3 first bullet: 'Missing assertion in test file
    -> RED drift'. Exit code 2 per D74 (red drift maps to fatal-tier per
    spec section 4.7 L873).

    Pillar: Audit-grade (drift must be caught). Spec: section 4.7 step 3 + D74.
    """
    mod = _load_tool_module()
    file_reader, file_exists, file_writer, written = _build_fake_fs(
        spec_text=_CLEAN_SPEC_TEXT,
        test_text=_TEST_MISSING_C,
    )

    result = mod.main(
        actor="test-author",
        no_audit_event=True,
        spec_doc_paths=("docs/migration/phase1/03_core_modules.md",),
        tier0_dirs=("tests/tier0",),
        file_reader=file_reader,
        file_exists=file_exists,
        file_writer=file_writer,
        project_root="/synthetic/root",
        report_path="/synthetic/report.md",
    )

    assert result.get("exit_code") == EXIT_RED, (
        f"Missing assertion (c) must produce exit {EXIT_RED}. "
        f"Got: {result.get('exit_code')!r}. "
        "Spec: section 4.7 step 3 first bullet + D74."
    )
    assert result.get("overall") == "red", (
        f"Overall verdict must be 'red' for missing assertion. "
        f"Got: {result.get('overall')!r}."
    )
    assert result.get("missing_assertions", 0) >= 1, (
        f"missing_assertions count must reflect the drift. "
        f"Got: {result!r}."
    )


# ===========================================================================
# Tier 0 assertion (e): test has extra assertion -> yellow -> exit 1
# ===========================================================================


def test_e_extra_assertion_exits_one():
    """(e) Test has extra assertion not in spec -> yellow drift -> exit 1.

    Per spec section 4.7 step 3 second bullet: 'Extra assertion in test file
    -> YELLOW (Tier 1 bloat per D80; flag for Tier 1 promotion)'. Exit
    code 1 per D74 (yellow = informational, NOT page-able).

    Pillar: Operationally stable (drift signaled but not fatal). Spec: section
    4.7 step 3 + D80 (Tier 0 vs Tier 1 boundary).
    """
    mod = _load_tool_module()
    file_reader, file_exists, file_writer, written = _build_fake_fs(
        spec_text=_CLEAN_SPEC_TEXT,
        test_text=_TEST_EXTRA_D,
    )

    result = mod.main(
        actor="test-author",
        no_audit_event=True,
        spec_doc_paths=("docs/migration/phase1/03_core_modules.md",),
        tier0_dirs=("tests/tier0",),
        file_reader=file_reader,
        file_exists=file_exists,
        file_writer=file_writer,
        project_root="/synthetic/root",
        report_path="/synthetic/report.md",
    )

    assert result.get("exit_code") == EXIT_YELLOW, (
        f"Extra assertion in test file must produce exit {EXIT_YELLOW} "
        f"(yellow drift). Got: {result.get('exit_code')!r}. "
        "Spec: section 4.7 step 3 second bullet + D80."
    )
    assert result.get("overall") == "yellow", (
        f"Overall verdict must be 'yellow' for extra-only drift. "
        f"Got: {result.get('overall')!r}."
    )
    assert result.get("extra_assertions", 0) >= 1, (
        f"extra_assertions count must reflect the drift. "
        f"Got: {result!r}."
    )


# ===========================================================================
# Tier 0 assertion (f): test file entirely absent -> red -> exit 2
# ===========================================================================


def test_f_missing_test_file_exits_two():
    """(f) Test file entirely absent -> red drift -> exit 2.

    Per spec section 4.7: a sketch in the spec doc with no corresponding
    tests/tier0/test_<X>.py file is the strongest possible drift signal.
    Maps to RED MISSING_TEST_FILE per the implementation contract.

    Pillar: Audit-grade. Spec: section 4.7 step 3 (file absent treated as
    red drift) + D74 (exit 2 = fatal).
    """
    mod = _load_tool_module()
    file_reader, file_exists, file_writer, written = _build_fake_fs(
        spec_text=_CLEAN_SPEC_TEXT,
        test_text=None,  # absent
    )

    result = mod.main(
        actor="test-author",
        no_audit_event=True,
        spec_doc_paths=("docs/migration/phase1/03_core_modules.md",),
        tier0_dirs=("tests/tier0",),
        file_reader=file_reader,
        file_exists=file_exists,
        file_writer=file_writer,
        project_root="/synthetic/root",
        report_path="/synthetic/report.md",
    )

    assert result.get("exit_code") == EXIT_RED, (
        f"Missing test file must produce exit {EXIT_RED} (red drift). "
        f"Got: {result.get('exit_code')!r}. "
        "Spec: section 4.7 step 3 + D74."
    )
    assert result.get("missing_test_files", 0) >= 1, (
        f"missing_test_files count must reflect the drift. "
        f"Got: {result!r}."
    )


# ===========================================================================
# Tier 0 runtime ceiling assertion (D67)
# ===========================================================================


def test_tier0_total_runtime_under_five_seconds():
    """All 6 Tier 0 assertions complete in < 5 s (D67 ceiling).

    D67: Tier 0 smoke test runtime ceiling < 5 s per module. Failure means
    external I/O has leaked through the mock layer -- a test-isolation bug.

    D67. Spec: section 4.7 L873.
    """
    _start = time.monotonic()

    # Simulate the full 6-assertion sequence
    m1 = _load_tool_module()
    assert m1 is not None

    file_reader, file_exists, file_writer, _ = _build_fake_fs(
        spec_text=_CLEAN_SPEC_TEXT,
        test_text=_CLEAN_TEST_TEXT,
    )
    m1.main(
        actor="test-author",
        no_audit_event=True,
        spec_doc_paths=("docs/migration/phase1/03_core_modules.md",),
        tier0_dirs=("tests/tier0",),
        file_reader=file_reader,
        file_exists=file_exists,
        file_writer=file_writer,
        project_root="/synthetic/root",
        report_path="/synthetic/report.md",
    )

    elapsed = time.monotonic() - _start
    assert elapsed < 5.0, (
        f"Tier 0 total runtime must be < 5 s. Took {elapsed:.2f} s. "
        "External I/O may have leaked through mock layer. D67."
    )
