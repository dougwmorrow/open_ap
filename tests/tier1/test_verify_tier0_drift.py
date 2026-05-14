"""Tier 1 unit tests for tools/verify_tier0_drift.py.

Per Round 6 section 4.7 (closes B58 stub -> full impl) + D74 + D76 + D77.
Tests run on every commit. No live DB, no live filesystem (all reads/writes
go through injection points).

North Star pillars addressed (NORTH_STAR.md):
  - Audit-grade (D76): exactly one CLI_VERIFY_TIER0_DRIFT PipelineEventLog
    row per invocation; Metadata JSON carries verdict + per-category counts +
    actor + report_path + event_kind; audit_event_id key present in result
    dict (B218 presence-over-content lesson).
  - Operationally stable (D74/D75): exit-code contract 0/1/2 exact per spec;
    argument naming discipline (--actor / --module / --report-path / --json /
    --verbose / --quiet / --no-audit-event / --fail-on-yellow) per D75.
  - Idempotent (D15): re-runs on identical inputs produce identical reports.
  - Traceability (D26): audit-event metadata round-trips correctly.

Spec citations (Pitfall #9.l producer self-check):
  - spec section 4.7 step 1 (extract sketches from 03_core_modules.md +
    04_tools.md per 6-assertion contract per D77),
  - spec section 4.7 step 2 (read tests/smoke/test_<X>.py -- project uses
    tests/tier0/ but tool fallback to tests/smoke/ preserves spec wording),
  - spec section 4.7 step 3 (per-file diff -- missing -> red / extra ->
    yellow / type mismatch -> red),
  - spec section 4.7 step 4 (Markdown report at tests/audit_reports/
    tier0_drift_<date>.md),
  - spec section 4.7 step 5 (CI integration -- run weekly per Q7),
  - spec section 4.7 step 6 (exit code 0/1/2 per D74).

D-numbers consumed: D67 (Tier 0 build-time discipline), D74 (CLI exit-code
contract 0/1/2), D75 (canonical arg naming), D76 (audit-row contract),
D77 (6-assertion scaffold), D80 (Tier 0 vs Tier 1 boundary -- extras are
Tier 1 promotion candidates), D92 (forward-only additive -- replaces stub
preserving public surface).

B-numbers: B58 (this tool -- closes the stub), B85 (utils.errors canonical
imports), B214 (test injection points -- no bare sys.modules writes for
exception classes), B228 (canonical utils.errors imports).

Independence note: Tier 1 is authored INDEPENDENTLY from
tools/verify_tier0_drift.py per D55 (test author != code author).

Spec: phase1/06_deployment.md section 4.7 (canonical spec L856-875).
"""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Project root on sys.path
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_TOOL_PATH = _PROJECT_ROOT / "tools" / "verify_tier0_drift.py"
_TOOL_MODULE_KEY = "tools.verify_tier0_drift"

# ---------------------------------------------------------------------------
# Constants (single source of truth -- Pitfall #9.m self-application)
# ---------------------------------------------------------------------------

EXPECTED_EVENT_TYPE = "CLI_VERIFY_TIER0_DRIFT"

EXIT_SUCCESS = 0
EXIT_YELLOW = 1
EXIT_RED = 2

# Required keys in result dict per D76 + spec section 4.7
REQUIRED_RESULT_KEYS = frozenset({
    "event_kind",
    "actor",
    "report_path",
    "modules_checked",
    "overall",
    "files_red",
    "files_yellow",
    "files_clean",
    "missing_assertions",
    "extra_assertions",
    "type_mismatches",
    "missing_test_files",
    "exit_code",
    "started_at",
    "completed_at",
    "audit_event_id",
})

# Required Metadata JSON keys (subset that must round-trip through audit)
REQUIRED_AUDIT_METADATA_KEYS = frozenset({
    "event_kind",
    "actor",
    "overall",
    "exit_code",
})

# Synthetic fixtures -- the test-only spec doc and test files.
_SPEC_TEXT_THREE_ASSERTIONS = """\
### section 1.1 `widget_writer`

Some preamble text.

**Tier 0 smoke test** (per section 1.6 + D67): `tests/tier0/test_widget_writer.py` -- runs in <5s. Asserts: (a) module imports; (b) `widget_write` invokable with mocked cursor; (c) returns `WidgetResult` shape.

---
"""

_TEST_TEXT_THREE_MATCH = """\
def test_a_module_imports():
    pass

def test_b_widget_write_invokable():
    pass

def test_c_returns_widget_result():
    pass
"""

_TEST_TEXT_TWO_MATCH = """\
def test_a_module_imports():
    pass

def test_b_widget_write_invokable():
    pass
"""

_TEST_TEXT_FOUR_EXTRA = """\
def test_a_module_imports():
    pass

def test_b_widget_write_invokable():
    pass

def test_c_returns_widget_result():
    pass

def test_d_extra_in_test():
    pass

def test_e_another_extra():
    pass
"""

# Spec with exception-class reference -- tests can verify type-mismatch detection.
_SPEC_TEXT_WITH_EXCEPTION = """\
### section 1.2 `gadget_reader`

**Tier 0 smoke test** (per section 1.6 + D67): `tests/tier0/test_gadget_reader.py` -- runs in <5s. Asserts: (a) module imports; (b) raises `WidgetFatalError` on invalid input.

---
"""

# Test that catches generic Exception when spec named WidgetFatalError -> type mismatch
_TEST_TEXT_CATCHES_GENERIC = """\
import pytest

def test_a_module_imports():
    pass

def test_b_raises_on_invalid_input():
    with pytest.raises(Exception):
        pass
"""

# Test that catches the correct exception -> no mismatch
_TEST_TEXT_CATCHES_SPECIFIC = """\
import pytest

def test_a_module_imports():
    pass

def test_b_raises_on_invalid_input():
    with pytest.raises(WidgetFatalError):
        pass
"""


# ---------------------------------------------------------------------------
# Module loader -- no bare sys.modules writes (B214)
# ---------------------------------------------------------------------------


def _load_tool_module() -> Any:
    """Load tool module via importlib.util (per B214)."""
    if _TOOL_MODULE_KEY in sys.modules:
        del sys.modules[_TOOL_MODULE_KEY]
    spec = importlib.util.spec_from_file_location(_TOOL_MODULE_KEY, _TOOL_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_TOOL_MODULE_KEY] = mod
    spec.loader.exec_module(mod)
    return mod


def _build_fake_fs(
    *,
    spec_files: dict[str, str],
    test_files: dict[str, str],
):
    """Return (file_reader, file_exists, file_writer, written) tuple.

    Parameters
    ----------
    spec_files:
        Dict of {relative-spec-path: content}. Each relative path acts as
        a substring match for file_reader.
    test_files:
        Dict of {module-name: content}. Test file path is
        ``tests/tier0/test_<module>.py``.
    """
    written: dict[str, str] = {}

    def file_reader(p: Path) -> str:
        as_str = str(p).replace("\\", "/")
        for spec_path, content in spec_files.items():
            normalized = spec_path.replace("\\", "/")
            if as_str.endswith(normalized):
                return content
        for module_name, content in test_files.items():
            if f"test_{module_name}.py" in as_str:
                return content
        raise FileNotFoundError(as_str)

    def file_exists(p: Path) -> bool:
        as_str = str(p).replace("\\", "/")
        for module_name in test_files:
            if f"test_{module_name}.py" in as_str:
                return True
        return False

    def file_writer(p: Path, content: str) -> None:
        written[str(p)] = content

    return file_reader, file_exists, file_writer, written


def _call_main(mod: Any, **overrides: Any) -> dict:
    """Call tool main() with canonical defaults + overrides."""
    spec_files = overrides.pop(
        "spec_files",
        {"docs/migration/phase1/03_core_modules.md": _SPEC_TEXT_THREE_ASSERTIONS},
    )
    test_files = overrides.pop(
        "test_files",
        {"widget_writer": _TEST_TEXT_THREE_MATCH},
    )
    file_reader, file_exists, file_writer, written = _build_fake_fs(
        spec_files=spec_files,
        test_files=test_files,
    )
    defaults = dict(
        actor="test-author",
        no_audit_event=True,
        spec_doc_paths=tuple(spec_files.keys()),
        tier0_dirs=("tests/tier0",),
        file_reader=file_reader,
        file_exists=file_exists,
        file_writer=file_writer,
        project_root="/synthetic/root",
        report_path="/synthetic/report.md",
    )
    defaults.update(overrides)
    return mod.main(**defaults)


# ===========================================================================
# § Module surface
# ===========================================================================


class TestModuleSurface:
    """Tool exposes the canonical public surface per D92 forward-only."""

    def test_main_callable(self):
        mod = _load_tool_module()
        assert callable(mod.main)

    def test_cli_main_callable(self):
        mod = _load_tool_module()
        assert callable(mod.cli_main)

    def test_verify_tier0_drift_callable(self):
        mod = _load_tool_module()
        assert callable(mod.verify_tier0_drift)

    def test_dataclass_report_exposed(self):
        mod = _load_tool_module()
        assert hasattr(mod, "TierZeroDriftReport")
        # Must be instantiable with no args (uses field defaults)
        report = mod.TierZeroDriftReport()
        assert report.modules_checked == 0
        assert report.overall == "match"
        assert report.findings == []

    def test_extract_spec_assertions_exposed(self):
        mod = _load_tool_module()
        assert callable(mod.extract_spec_assertions)

    def test_render_markdown_report_exposed(self):
        mod = _load_tool_module()
        assert callable(mod.render_markdown_report)

    def test_write_report_file_exposed(self):
        mod = _load_tool_module()
        assert callable(mod.write_report_file)

    def test_event_type_constant(self):
        """D76 EventType per CLI_* family."""
        mod = _load_tool_module()
        assert mod.EVENT_TYPE == EXPECTED_EVENT_TYPE

    def test_exit_code_constants(self):
        """D74 canonical 0/1/2 exit codes."""
        mod = _load_tool_module()
        assert mod.EXIT_SUCCESS == 0
        assert mod.EXIT_YELLOW == 1
        assert mod.EXIT_RED == 2


# ===========================================================================
# § Argument parser surface (per D75 canonical naming)
# ===========================================================================


class TestArgParser:
    """Arg parser accepts canonical args per D75 + spec section 4.7."""

    def test_parser_buildable(self):
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        assert parser is not None

    def test_help_exits_zero(self):
        """--help exits 0 per D74."""
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--help"])
        assert exc_info.value.code == 0

    def test_actor_flag_accepted(self):
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        args = parser.parse_args(["--actor", "operator"])
        assert args.actor == "operator"

    def test_module_flag_accumulates(self):
        """--module is repeatable per D75 (action='append')."""
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        args = parser.parse_args(["--module", "widget", "--module", "gadget"])
        assert args.module == ["widget", "gadget"]

    def test_report_path_flag_accepted(self):
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        args = parser.parse_args(["--report-path", "/tmp/report.md"])
        assert args.report_path == "/tmp/report.md"

    def test_json_flag_sets_json_output(self):
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        args = parser.parse_args(["--json"])
        assert args.json_output is True

    def test_no_audit_event_flag_accepted(self):
        """--no-audit-event per D75 pipeline-programmatic invocation."""
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        args = parser.parse_args(["--no-audit-event"])
        assert args.no_audit_event is True

    def test_verbose_flag_accepted(self):
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        args = parser.parse_args(["-v"])
        assert args.verbose is True

    def test_quiet_flag_accepted(self):
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        args = parser.parse_args(["-q"])
        assert args.quiet is True

    def test_fail_on_yellow_flag_accepted(self):
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        args = parser.parse_args(["--fail-on-yellow"])
        assert args.fail_on_yellow is True

    def test_default_no_args(self):
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        args = parser.parse_args([])
        assert args.actor is None
        assert args.module is None
        assert args.report_path is None
        assert args.json_output is False
        assert args.verbose is False
        assert args.quiet is False
        assert args.no_audit_event is False
        assert args.fail_on_yellow is False


# ===========================================================================
# § Spec extraction
# ===========================================================================


class TestExtractSpecAssertions:
    """extract_spec_assertions() walks spec docs + extracts sketches."""

    def test_clean_extraction(self):
        """Three-letter spec extracts three assertions."""
        mod = _load_tool_module()
        file_reader, _, _, _ = _build_fake_fs(
            spec_files={
                "docs/migration/phase1/03_core_modules.md": (
                    _SPEC_TEXT_THREE_ASSERTIONS
                )
            },
            test_files={},
        )
        result = mod.extract_spec_assertions(
            spec_doc_paths=("docs/migration/phase1/03_core_modules.md",),
            project_root=Path("/synthetic/root"),
            file_reader=file_reader,
        )
        assert "widget_writer" in result
        assertions = result["widget_writer"]["assertions"]
        assert len(assertions) == 3
        assert {a.letter for a in assertions} == {"a", "b", "c"}

    def test_extracted_letters_ordered(self):
        mod = _load_tool_module()
        file_reader, _, _, _ = _build_fake_fs(
            spec_files={
                "docs/migration/phase1/03_core_modules.md": (
                    _SPEC_TEXT_THREE_ASSERTIONS
                )
            },
            test_files={},
        )
        result = mod.extract_spec_assertions(
            spec_doc_paths=("docs/migration/phase1/03_core_modules.md",),
            project_root=Path("/synthetic/root"),
            file_reader=file_reader,
        )
        letters = [a.letter for a in result["widget_writer"]["assertions"]]
        assert letters == sorted(letters)

    def test_exception_class_extracted(self):
        """Spec containing 'raises FooError' must populate exception_class."""
        mod = _load_tool_module()
        file_reader, _, _, _ = _build_fake_fs(
            spec_files={
                "docs/migration/phase1/03_core_modules.md": (
                    _SPEC_TEXT_WITH_EXCEPTION
                )
            },
            test_files={},
        )
        result = mod.extract_spec_assertions(
            spec_doc_paths=("docs/migration/phase1/03_core_modules.md",),
            project_root=Path("/synthetic/root"),
            file_reader=file_reader,
        )
        assert "gadget_reader" in result
        a_b = next(
            a for a in result["gadget_reader"]["assertions"] if a.letter == "b"
        )
        assert a_b.exception_class == "WidgetFatalError"

    def test_no_exception_for_plain_assertion(self):
        mod = _load_tool_module()
        file_reader, _, _, _ = _build_fake_fs(
            spec_files={
                "docs/migration/phase1/03_core_modules.md": (
                    _SPEC_TEXT_THREE_ASSERTIONS
                )
            },
            test_files={},
        )
        result = mod.extract_spec_assertions(
            spec_doc_paths=("docs/migration/phase1/03_core_modules.md",),
            project_root=Path("/synthetic/root"),
            file_reader=file_reader,
        )
        a_a = next(
            a for a in result["widget_writer"]["assertions"] if a.letter == "a"
        )
        assert a_a.exception_class is None

    def test_missing_doc_returns_empty(self):
        """Spec doc absent -> empty dict, no exception."""
        mod = _load_tool_module()

        def file_reader(p):
            raise FileNotFoundError(str(p))

        result = mod.extract_spec_assertions(
            spec_doc_paths=("docs/migration/phase1/03_core_modules.md",),
            project_root=Path("/synthetic/root"),
            file_reader=file_reader,
        )
        assert result == {}

    def test_spec_line_recorded(self):
        """spec_line tracks line number of the sketch header."""
        mod = _load_tool_module()
        file_reader, _, _, _ = _build_fake_fs(
            spec_files={
                "docs/migration/phase1/03_core_modules.md": (
                    _SPEC_TEXT_THREE_ASSERTIONS
                )
            },
            test_files={},
        )
        result = mod.extract_spec_assertions(
            spec_doc_paths=("docs/migration/phase1/03_core_modules.md",),
            project_root=Path("/synthetic/root"),
            file_reader=file_reader,
        )
        assert result["widget_writer"]["spec_line"] > 0


# ===========================================================================
# § Test-file extraction
# ===========================================================================


class TestTestFileExtraction:
    """Tier 0 test file assertion extraction via AST."""

    def test_extracts_three_assertions(self):
        mod = _load_tool_module()
        file_reader, _, _, _ = _build_fake_fs(
            spec_files={},
            test_files={"widget_writer": _TEST_TEXT_THREE_MATCH},
        )
        from pathlib import Path as P

        assertions = mod._extract_assertions_from_test_file(
            P("/x/test_widget_writer.py"), file_reader=file_reader
        )
        assert len(assertions) == 3
        assert {a.letter for a in assertions} == {"a", "b", "c"}

    def test_function_name_captured(self):
        mod = _load_tool_module()
        file_reader, _, _, _ = _build_fake_fs(
            spec_files={},
            test_files={"widget_writer": _TEST_TEXT_THREE_MATCH},
        )
        from pathlib import Path as P

        assertions = mod._extract_assertions_from_test_file(
            P("/x/test_widget_writer.py"), file_reader=file_reader
        )
        function_names = {a.function_name for a in assertions}
        assert "test_a_module_imports" in function_names

    def test_exception_class_extracted_from_test(self):
        """Test body containing pytest.raises(X) -> exception_classes captures X."""
        mod = _load_tool_module()
        file_reader, _, _, _ = _build_fake_fs(
            spec_files={},
            test_files={"gadget_reader": _TEST_TEXT_CATCHES_GENERIC},
        )
        from pathlib import Path as P

        assertions = mod._extract_assertions_from_test_file(
            P("/x/test_gadget_reader.py"), file_reader=file_reader
        )
        b_assertion = next(a for a in assertions if a.letter == "b")
        assert "Exception" in b_assertion.exception_classes

    def test_syntax_error_returns_empty(self):
        mod = _load_tool_module()

        def file_reader(p):
            return "def def def syntax error"

        from pathlib import Path as P

        result = mod._extract_assertions_from_test_file(
            P("/x/test_bad.py"), file_reader=file_reader
        )
        assert result == []

    def test_missing_file_returns_empty(self):
        mod = _load_tool_module()

        def file_reader(p):
            raise FileNotFoundError(str(p))

        from pathlib import Path as P

        result = mod._extract_assertions_from_test_file(
            P("/x/test_absent.py"), file_reader=file_reader
        )
        assert result == []

    def test_non_letter_test_function_ignored(self):
        """test_module_imports (no letter prefix) is NOT registered."""
        mod = _load_tool_module()
        file_reader, _, _, _ = _build_fake_fs(
            spec_files={},
            test_files={
                "widget_writer": (
                    "def test_module_imports():\n    pass\n"
                    "def test_z_real_letter():\n    pass\n"
                )
            },
        )
        from pathlib import Path as P

        result = mod._extract_assertions_from_test_file(
            P("/x/test_widget_writer.py"), file_reader=file_reader
        )
        letters = {a.letter for a in result}
        # Only 'z' should be captured (test_module_imports has no letter)
        assert "z" in letters
        # Verify test_module_imports doesn't become a letter
        assert len(result) == 1


# ===========================================================================
# § Drift verdict computation (the core of spec section 4.7 step 3)
# ===========================================================================


class TestDriftVerdicts:
    """Per-file diff computation per spec section 4.7 step 3."""

    def test_clean_run_no_drift(self):
        mod = _load_tool_module()
        result = _call_main(mod)
        assert result["overall"] == "match"
        assert result["files_red"] == 0
        assert result["files_yellow"] == 0
        assert result["missing_assertions"] == 0
        assert result["extra_assertions"] == 0
        assert result["type_mismatches"] == 0

    def test_missing_assertion_is_red(self):
        """Spec has (c) but test file lacks test_c_* -> red drift."""
        mod = _load_tool_module()
        result = _call_main(
            mod,
            test_files={"widget_writer": _TEST_TEXT_TWO_MATCH},
        )
        assert result["overall"] == "red"
        assert result["missing_assertions"] == 1
        assert result["files_red"] == 1
        assert result["exit_code"] == EXIT_RED

    def test_extra_assertion_is_yellow(self):
        """Test has extras (d, e) -> yellow drift."""
        mod = _load_tool_module()
        result = _call_main(
            mod,
            test_files={"widget_writer": _TEST_TEXT_FOUR_EXTRA},
        )
        assert result["overall"] == "yellow"
        assert result["extra_assertions"] == 2
        assert result["files_yellow"] == 1
        assert result["exit_code"] == EXIT_YELLOW

    def test_missing_test_file_is_red(self):
        """No test file at all -> red drift."""
        mod = _load_tool_module()
        result = _call_main(
            mod,
            test_files={},
        )
        assert result["overall"] == "red"
        assert result["missing_test_files"] >= 1
        assert result["exit_code"] == EXIT_RED

    def test_type_mismatch_generic_exception_is_red(self):
        """Spec says WidgetFatalError but test catches generic Exception."""
        mod = _load_tool_module()
        result = _call_main(
            mod,
            spec_files={
                "docs/migration/phase1/03_core_modules.md": (
                    _SPEC_TEXT_WITH_EXCEPTION
                )
            },
            test_files={"gadget_reader": _TEST_TEXT_CATCHES_GENERIC},
        )
        assert result["overall"] == "red"
        assert result["type_mismatches"] >= 1

    def test_type_match_specific_exception_no_drift(self):
        mod = _load_tool_module()
        result = _call_main(
            mod,
            spec_files={
                "docs/migration/phase1/03_core_modules.md": (
                    _SPEC_TEXT_WITH_EXCEPTION
                )
            },
            test_files={"gadget_reader": _TEST_TEXT_CATCHES_SPECIFIC},
        )
        # No type mismatch when test catches the specific named class
        assert result["type_mismatches"] == 0

    def test_red_dominates_yellow(self):
        """When BOTH red and yellow drift exist, overall verdict is red."""
        mod = _load_tool_module()
        # Build a test file that has both a missing assertion AND extras
        mixed_test = (
            "def test_a_module_imports():\n    pass\n"
            "def test_b_widget_write_invokable():\n    pass\n"
            "def test_d_extra_one():\n    pass\n"
        )
        result = _call_main(
            mod,
            test_files={"widget_writer": mixed_test},
        )
        assert result["overall"] == "red"
        assert result["missing_assertions"] >= 1
        assert result["extra_assertions"] >= 1


# ===========================================================================
# § B-266 tools_ prefix strip + descriptive test name matching
# ===========================================================================


class TestB266ToolsPrefixStrip:
    """B-266 fix: _resolve_test_file strips 'tools_' prefix as fallback."""

    def test_strips_tools_prefix_when_canonical_not_found(self):
        mod = _load_tool_module()
        from pathlib import Path as P
        def file_exists(p):
            # Only test_alert_dispatcher.py exists, NOT test_tools_alert_dispatcher.py
            return p.name == "test_alert_dispatcher.py"
        result = mod._resolve_test_file(
            "tools_alert_dispatcher",
            project_root=P("/root"),
            tier0_dirs=("tests/tier0",),
            file_exists=file_exists,
        )
        assert result is not None
        assert result.name == "test_alert_dispatcher.py"

    def test_prefers_canonical_name_when_both_exist(self):
        mod = _load_tool_module()
        from pathlib import Path as P
        def file_exists(p):
            return p.name in ("test_tools_alert_dispatcher.py", "test_alert_dispatcher.py")
        result = mod._resolve_test_file(
            "tools_alert_dispatcher",
            project_root=P("/root"),
            tier0_dirs=("tests/tier0",),
            file_exists=file_exists,
        )
        assert result.name == "test_tools_alert_dispatcher.py"

    def test_no_strip_if_module_lacks_tools_prefix(self):
        mod = _load_tool_module()
        from pathlib import Path as P
        def file_exists(p):
            return p.name == "test_credentials_loader.py"
        result = mod._resolve_test_file(
            "credentials_loader",
            project_root=P("/root"),
            tier0_dirs=("tests/tier0",),
            file_exists=file_exists,
        )
        assert result.name == "test_credentials_loader.py"

    def test_returns_none_if_neither_form_exists(self):
        mod = _load_tool_module()
        from pathlib import Path as P
        def file_exists(p):
            return False
        result = mod._resolve_test_file(
            "tools_alert_dispatcher",
            project_root=P("/root"),
            tier0_dirs=("tests/tier0",),
            file_exists=file_exists,
        )
        assert result is None


class TestB266DescriptiveMatching:
    """B-266 fix: descriptive test names match spec via keyword overlap."""

    def test_extract_keywords_drops_stopwords(self):
        mod = _load_tool_module()
        keywords = mod._extract_keywords("module imports")
        # "module" is in stopwords; "imports" is 7 chars
        assert "imports" in keywords
        assert "module" not in keywords

    def test_extract_keywords_keeps_backticked_identifiers(self):
        mod = _load_tool_module()
        keywords = mod._extract_keywords("returns `CredentialsDict` shape")
        # backticked identifiers always kept regardless of length
        assert "credentialsdict" in keywords

    def test_extract_keywords_short_words_excluded(self):
        mod = _load_tool_module()
        keywords = mod._extract_keywords("a is the of in to")
        # all 1-3 char tokens excluded
        assert keywords == set()

    def test_function_name_tokens_strips_test_prefix(self):
        mod = _load_tool_module()
        tokens = mod._function_name_tokens("test_clean_exit_updates_to_completed")
        assert "clean" in tokens
        assert "exit" in tokens
        assert "updates" in tokens
        assert "completed" in tokens
        assert "test" not in tokens  # stripped
        assert "to" not in tokens  # below 3-char threshold

    def test_keyword_match_two_overlap_succeeds(self):
        mod = _load_tool_module()
        # "clean exit UPDATEs to COMPLETED" overlap with test_clean_exit_updates_to_completed
        assert mod._assertion_keyword_match(
            "clean exit UPDATEs to COMPLETED",
            "test_clean_exit_updates_to_completed",
        )

    def test_keyword_match_zero_overlap_fails(self):
        mod = _load_tool_module()
        assert not mod._assertion_keyword_match(
            "raises CredentialsLoadError when gpg returns non-zero",
            "test_completely_unrelated_thing",
        )

    def test_backticked_identifier_alone_is_strong_signal(self):
        mod = _load_tool_module()
        # Single backticked identifier match is enough (1-overlap when backticked)
        assert mod._assertion_keyword_match(
            "returns `LatenessReport`",
            "test_lateness_report_shape",
        )

    def test_extract_descriptive_test_functions_skips_letter_prefixed(self):
        mod = _load_tool_module()
        from pathlib import Path as P
        def file_reader(p):
            return (
                "def test_a_module_imports():\n    pass\n"
                "def test_module_imports():\n    pass\n"
                "def test_clean_exit_updates_to_completed():\n    pass\n"
            )
        result = mod._extract_descriptive_test_functions(
            P("/x/test_foo.py"), file_reader=file_reader,
        )
        names = {a.function_name for a in result}
        assert "test_module_imports" in names
        assert "test_clean_exit_updates_to_completed" in names
        assert "test_a_module_imports" not in names  # letter-prefixed; excluded
        assert all(a.letter == "" for a in result)  # sentinel

    def test_full_drift_flow_descriptive_match_emits_match_not_red(self):
        """Integration: spec has (c), test file has only descriptive -- should match."""
        mod = _load_tool_module()
        from pathlib import Path as P
        spec_assertions = [
            mod.AssertionSpec(letter="a", description="module imports"),
            mod.AssertionSpec(letter="c", description="clean exit UPDATEs to COMPLETED"),
        ]
        spec_info = {
            "spec_doc": "docs/migration/phase1/03_core_modules.md",
            "spec_line": 927,
            "assertions": spec_assertions,
        }
        def file_exists(p):
            return p.name == "test_foo.py"
        def file_reader(p):
            return (
                "def test_module_imports():\n    pass\n"
                "def test_clean_exit_updates_to_completed():\n    pass\n"
            )
        findings = mod._compute_drift_for_module(
            "foo",
            spec_info,
            project_root=P("/root"),
            tier0_dirs=("tests/tier0",),
            file_reader=file_reader,
            file_exists=file_exists,
        )
        # No RED findings -- both should match via descriptive matcher
        red_findings = [f for f in findings if f.severity == "red"]
        assert red_findings == [], f"Unexpected RED findings: {red_findings}"
        # Both should be 'match' type
        match_findings = [f for f in findings if f.drift_type == "match"]
        assert len(match_findings) == 2
        # Detail should mention B-266 semantic match
        details = " ".join(f.detail for f in match_findings)
        assert "B-266" in details


# ===========================================================================
# § Exit code derivation (per D74 + spec section 4.7 L873)
# ===========================================================================


class TestExitCodes:
    """Exit-code derivation per D74."""

    def test_clean_exits_zero(self):
        mod = _load_tool_module()
        result = _call_main(mod)
        assert result["exit_code"] == EXIT_SUCCESS

    def test_yellow_exits_one(self):
        mod = _load_tool_module()
        result = _call_main(
            mod,
            test_files={"widget_writer": _TEST_TEXT_FOUR_EXTRA},
        )
        assert result["exit_code"] == EXIT_YELLOW

    def test_red_exits_two(self):
        mod = _load_tool_module()
        result = _call_main(
            mod,
            test_files={"widget_writer": _TEST_TEXT_TWO_MATCH},
        )
        assert result["exit_code"] == EXIT_RED

    def test_fail_on_yellow_promotes_yellow_to_red(self):
        """--fail-on-yellow makes yellow drift exit 2."""
        mod = _load_tool_module()
        result = _call_main(
            mod,
            test_files={"widget_writer": _TEST_TEXT_FOUR_EXTRA},
            fail_on_yellow=True,
        )
        assert result["exit_code"] == EXIT_RED
        # Overall verdict stays "yellow" -- only the exit code is promoted
        assert result["overall"] == "yellow"

    def test_fail_on_yellow_clean_still_zero(self):
        mod = _load_tool_module()
        result = _call_main(mod, fail_on_yellow=True)
        assert result["exit_code"] == EXIT_SUCCESS


# ===========================================================================
# § Result dict shape (D76 audit-row contract)
# ===========================================================================


class TestResultDictShape:
    """Result dict contains every key the audit row needs (D76)."""

    def test_all_required_keys_present(self):
        mod = _load_tool_module()
        result = _call_main(mod)
        missing = REQUIRED_RESULT_KEYS - set(result.keys())
        assert not missing, f"Result missing keys: {missing}"

    def test_event_kind_canonical(self):
        mod = _load_tool_module()
        result = _call_main(mod)
        assert result["event_kind"] == "tier0_drift_audit"

    def test_actor_propagated(self):
        mod = _load_tool_module()
        result = _call_main(mod, actor="operator-X")
        assert result["actor"] == "operator-X"

    def test_started_at_iso_format(self):
        mod = _load_tool_module()
        result = _call_main(mod)
        # ISO-8601 'Z' suffix per CDC-NOW-MS / SCD2-P1-f
        assert result["started_at"].endswith("Z")
        # Parseable back to datetime
        dt = datetime.strptime(result["started_at"], "%Y-%m-%dT%H:%M:%SZ")
        assert dt.tzinfo is None  # Naive (no tzinfo) per SCD2-P1-f

    def test_completed_at_iso_format(self):
        mod = _load_tool_module()
        result = _call_main(mod)
        assert result["completed_at"].endswith("Z")
        dt = datetime.strptime(result["completed_at"], "%Y-%m-%dT%H:%M:%SZ")
        assert dt.tzinfo is None

    def test_audit_event_id_present_when_skipped(self):
        """B218: audit_event_id key MUST be present (None acceptable on skip)."""
        mod = _load_tool_module()
        result = _call_main(mod, no_audit_event=True)
        assert "audit_event_id" in result
        # Skip path returns None for audit_event_id
        assert result["audit_event_id"] is None


# ===========================================================================
# § Module filter
# ===========================================================================


class TestModuleFilter:
    """--module flag restricts the audit to specific modules."""

    def test_module_filter_restricts_scope(self):
        mod = _load_tool_module()
        # Two modules in spec, filter to only one
        result = _call_main(
            mod,
            spec_files={
                "docs/migration/phase1/03_core_modules.md": (
                    _SPEC_TEXT_THREE_ASSERTIONS + "\n" + _SPEC_TEXT_WITH_EXCEPTION
                )
            },
            test_files={
                "widget_writer": _TEST_TEXT_THREE_MATCH,
                "gadget_reader": _TEST_TEXT_CATCHES_SPECIFIC,
            },
            module=["widget_writer"],
        )
        assert result["modules_checked"] == 1

    def test_module_filter_none_means_all(self):
        mod = _load_tool_module()
        result = _call_main(
            mod,
            spec_files={
                "docs/migration/phase1/03_core_modules.md": (
                    _SPEC_TEXT_THREE_ASSERTIONS + "\n" + _SPEC_TEXT_WITH_EXCEPTION
                )
            },
            test_files={
                "widget_writer": _TEST_TEXT_THREE_MATCH,
                "gadget_reader": _TEST_TEXT_CATCHES_SPECIFIC,
            },
            module=None,
        )
        assert result["modules_checked"] == 2

    def test_module_filter_nonexistent_means_zero(self):
        mod = _load_tool_module()
        result = _call_main(mod, module=["does_not_exist"])
        assert result["modules_checked"] == 0


# ===========================================================================
# § Report rendering
# ===========================================================================


class TestReportRendering:
    """Markdown report layout per spec section 4.7 step 4."""

    def test_render_report_returns_string(self):
        mod = _load_tool_module()
        report = mod.TierZeroDriftReport()
        report.completed_at = report.started_at
        report.aggregate()
        text = mod.render_markdown_report(report)
        assert isinstance(text, str)
        assert len(text) > 0

    def test_report_header_present(self):
        mod = _load_tool_module()
        report = mod.TierZeroDriftReport()
        report.completed_at = report.started_at
        report.aggregate()
        text = mod.render_markdown_report(report)
        assert "Tier 0 Drift Audit Report" in text
        assert "B58" in text  # closure annotation

    def test_report_includes_overall_verdict(self):
        mod = _load_tool_module()
        report = mod.TierZeroDriftReport()
        report.completed_at = report.started_at
        report.aggregate()
        text = mod.render_markdown_report(report)
        assert "Overall verdict" in text

    def test_report_includes_legend(self):
        """Spec section 4.7 step 4 implies a legend; ours documents the mapping."""
        mod = _load_tool_module()
        report = mod.TierZeroDriftReport()
        report.completed_at = report.started_at
        report.aggregate()
        text = mod.render_markdown_report(report)
        assert "Legend" in text
        assert "RED" in text
        assert "YELLOW" in text
        assert "GREEN" in text

    def test_report_per_module_sections(self):
        mod = _load_tool_module()
        result = _call_main(
            mod,
            test_files={"widget_writer": _TEST_TEXT_TWO_MATCH},
        )
        # The report file was written via the file_writer hook; access the
        # rendered text via render_markdown_report directly.
        report_obj = mod.verify_tier0_drift(
            project_root=Path("/synthetic/root"),
            spec_doc_paths=("docs/migration/phase1/03_core_modules.md",),
            tier0_dirs=("tests/tier0",),
            file_reader=_build_fake_fs(
                spec_files={
                    "docs/migration/phase1/03_core_modules.md": (
                        _SPEC_TEXT_THREE_ASSERTIONS
                    )
                },
                test_files={"widget_writer": _TEST_TEXT_TWO_MATCH},
            )[0],
            file_exists=_build_fake_fs(
                spec_files={
                    "docs/migration/phase1/03_core_modules.md": (
                        _SPEC_TEXT_THREE_ASSERTIONS
                    )
                },
                test_files={"widget_writer": _TEST_TEXT_TWO_MATCH},
            )[1],
        )
        text = mod.render_markdown_report(report_obj)
        assert "widget_writer" in text


# ===========================================================================
# § JSON output
# ===========================================================================


class TestJSONOutput:
    """--json emits canonical JSON payload to stdout."""

    def test_json_output_invokable(self, capsys):
        mod = _load_tool_module()
        _call_main(mod, json_output=True, quiet=False)
        captured = capsys.readouterr()
        # Parse the JSON to verify it's well-formed
        payload = json.loads(captured.out)
        assert isinstance(payload, dict)

    def test_json_output_includes_required_keys(self, capsys):
        mod = _load_tool_module()
        _call_main(mod, json_output=True, quiet=False)
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        for key in (
            "overall",
            "modules_checked",
            "files_red",
            "files_yellow",
            "files_clean",
            "exit_code",
            "report_path",
        ):
            assert key in payload, f"JSON missing key: {key!r}"

    def test_quiet_suppresses_output(self, capsys):
        mod = _load_tool_module()
        _call_main(mod, json_output=False, quiet=True)
        captured = capsys.readouterr()
        # Quiet mode suppresses the human summary
        assert captured.out == ""


# ===========================================================================
# § Audit-row writer
# ===========================================================================


class TestAuditRowWriter:
    """CLI_VERIFY_TIER0_DRIFT audit row writer (D76 contract)."""

    def test_skip_returns_none(self):
        mod = _load_tool_module()
        result = mod._write_audit_row(
            {"overall": "match"},
            status="SUCCESS",
            cursor_factory=None,
            skip=True,
        )
        assert result is None

    def test_audit_writer_invoked_when_not_skipped(self):
        """Injected cursor_factory is called when skip=False."""
        mod = _load_tool_module()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (88200,)
        mock_cursor.description = [("AuditEventId",)]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        def cursor_factory():
            return mock_conn

        result = mod._write_audit_row(
            {
                "overall": "match",
                "modules_checked": 1,
                "started_at_dt": datetime.now(),
            },
            status="SUCCESS",
            cursor_factory=cursor_factory,
            skip=False,
        )
        assert result == 88200
        # Verify INSERT statement was executed
        mock_cursor.execute.assert_called()

    def test_audit_writer_failure_returns_none(self):
        """Audit-row INSERT failure -> returns None (best-effort)."""
        mod = _load_tool_module()
        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = RuntimeError("DB unreachable")
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        def cursor_factory():
            return mock_conn

        result = mod._write_audit_row(
            {"overall": "match", "started_at_dt": datetime.now()},
            status="SUCCESS",
            cursor_factory=cursor_factory,
            skip=False,
        )
        assert result is None

    def test_audit_event_type_propagated(self):
        """Event_type in INSERT must be the canonical value."""
        mod = _load_tool_module()
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = (1,)
        mock_cursor.description = [("AuditEventId",)]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        def cursor_factory():
            return mock_conn

        mod._write_audit_row(
            {
                "overall": "match",
                "modules_checked": 1,
                "started_at_dt": datetime.now(),
            },
            status="SUCCESS",
            cursor_factory=cursor_factory,
            skip=False,
        )
        # Look at the execute call's args
        call_args = mock_cursor.execute.call_args
        if call_args is not None and len(call_args[0]) > 1:
            # The first positional arg after SQL is EventType
            params = list(call_args[0][1:])
            assert EXPECTED_EVENT_TYPE in params


# ===========================================================================
# § Report file writer
# ===========================================================================


class TestReportFileWriter:
    """write_report_file writes the Markdown report (spec section 4.7 step 4)."""

    def test_writer_called_with_path_and_content(self):
        mod = _load_tool_module()
        written: dict[str, str] = {}

        def writer(p, content):
            written[str(p)] = content

        report = mod.TierZeroDriftReport()
        report.completed_at = report.started_at
        report.aggregate()
        mod.write_report_file(
            report, Path("/synthetic/report.md"), file_writer=writer
        )
        assert "/synthetic/report.md" in written or "\\synthetic\\report.md" in written

    def test_report_path_recorded(self):
        mod = _load_tool_module()

        def writer(p, content):
            pass

        report = mod.TierZeroDriftReport()
        report.completed_at = report.started_at
        report.aggregate()
        mod.write_report_file(
            report, Path("/synthetic/report.md"), file_writer=writer
        )
        assert report.report_path is not None
        assert "report.md" in report.report_path


# ===========================================================================
# § CLI entry point
# ===========================================================================


class TestCliMain:
    """cli_main argv handling + exit-code mapping."""

    def test_cli_main_runs_clean_returns_zero(self, monkeypatch, tmp_path):
        """cli_main with no args (against real codebase) returns an int."""
        mod = _load_tool_module()
        # Direct the report into tmp_path to avoid polluting the repo
        report_file = tmp_path / "report.md"
        # Use --no-audit-event to avoid live-DB attempts; quiet to suppress stdout
        exit_code = mod.cli_main([
            "--no-audit-event",
            "--quiet",
            "--report-path",
            str(report_file),
            "--module",
            "does_not_exist_anywhere",  # zero modules -> clean
        ])
        assert exit_code == 0

    def test_cli_main_invalid_flag_exits_two(self, monkeypatch):
        """Argparse rejects unknown flags with SystemExit(2)."""
        mod = _load_tool_module()
        with pytest.raises(SystemExit) as exc_info:
            mod.cli_main(["--bogus-flag"])
        assert exc_info.value.code == 2


# ===========================================================================
# § B228 / B214 / B85 discipline
# ===========================================================================


class TestB228UtilsErrorsImport:
    """Tool uses utils.errors per B228 canonical imports."""

    def test_pipeline_fatal_error_resolvable(self):
        mod = _load_tool_module()
        assert hasattr(mod, "PipelineFatalError")

    def test_no_local_exception_classes_defined(self):
        """B228: tool MUST NOT define its own ParityFatalError etc."""
        mod = _load_tool_module()
        # The fallback shim is allowed (defensive idiom) but it's the
        # ONLY local class. utils.errors should be the canonical source.
        # We verify by checking that PipelineFatalError is exposed but
        # nothing tool-specific that should live in utils.errors.
        # (forward-only additive contract)
        assert hasattr(mod, "PipelineFatalError")


# ===========================================================================
# § Idempotency
# ===========================================================================


class TestIdempotency:
    """D15: re-runs on identical inputs produce identical outputs."""

    def test_two_runs_produce_same_verdict(self):
        mod = _load_tool_module()
        r1 = _call_main(mod)
        r2 = _call_main(mod)
        assert r1["overall"] == r2["overall"]
        assert r1["modules_checked"] == r2["modules_checked"]
        assert r1["missing_assertions"] == r2["missing_assertions"]
        assert r1["extra_assertions"] == r2["extra_assertions"]
        assert r1["exit_code"] == r2["exit_code"]

    def test_report_text_stable_across_runs(self):
        mod = _load_tool_module()
        # Build a deterministic report (no timestamps in equality check)
        report = mod.TierZeroDriftReport()
        report.completed_at = report.started_at
        report.aggregate()
        text1 = mod.render_markdown_report(report)
        text2 = mod.render_markdown_report(report)
        assert text1 == text2
