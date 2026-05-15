"""Tier 1 unit tests for tools/verify_server_parity_cli.py.

Per § 1.6 + D67 — runs on every commit. No live DB / network / subprocess.

Covers the full operator surface per Round 5 test surface in spec § 3.7:
  - Tier 1: per-severity tier exit-code mapping
  - Tier 1: per-check coverage (Python, library SHA, env var, filesystem
    layout, systemd unit, TPM2 PCR, envelope SHA) -- via fixtures
  - Tier 1: --alert / --no-alert mutex + default heuristic
  - Tier 1: --baseline-path override + DEFAULT_BASELINE_PATH
  - Tier 1: argparse round-trip (all canonical + tool-specific args)
  - Tier 1: audit-row Metadata shape (D76 canonical)
  - Tier 1: ParityReport dict serialization (canonical shape, no
    invented fields, no canonical field dropped)
  - Tier 1: human-vs-JSON stdout dispatch
  - Tier 1: actor heuristic (TTY / AUTOMIC_RUN_ID env / fallback)
  - Tier 1: --quiet / --verbose log-level routing
  - Tier 1: cli_main() argv-driven path

D-numbers: D27, D62-D65, D67, D68, D74, D75, D76, D77, D85, D92, D103.
Edge case IDs: F21 (probe failure), F22 (severity), F23 (exceptions).
B-numbers: B228 (canonical errors), B243 (M8 build).
Spec: phase1/04_tools.md § 3.7 L951-1024.
"""
from __future__ import annotations

import argparse
import importlib
import importlib.util
import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Project root on sys.path
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_TOOL_PATH = _PROJECT_ROOT / "tools" / "verify_server_parity_cli.py"
_TOOL_MODULE_KEY = "tools.verify_server_parity_cli"

EXIT_SUCCESS = 0
EXIT_WARNING = 1
EXIT_FATAL = 2

EXPECTED_EVENT_TYPE = "CLI_VERIFY_SERVER_PARITY"
_DEFAULT_BASELINE = "/etc/pipeline/parity_baseline.json"


# ---------------------------------------------------------------------------
# Test doubles — ParityReport / ParityCheck shaped per R2 § 4.2 canonical
# ---------------------------------------------------------------------------


@dataclass
class FakeParityCheck:
    key: str
    expected: str
    actual: str
    severity: str
    exception_match: bool = False
    note: str | None = None


@dataclass
class FakeParityReport:
    server_name: str
    baseline_name: str
    baseline_pinned_at: str
    checks: list = field(default_factory=list)
    fatal_count: int = 0
    warning_count: int = 0
    informational_count: int = 0
    match_count: int = 0
    overall: str = "pass"

    def to_dict(self) -> dict[str, Any]:
        return {
            "server_name": self.server_name,
            "baseline_name": self.baseline_name,
            "baseline_pinned_at": self.baseline_pinned_at,
            "checks": [
                {
                    "key": c.key,
                    "expected": c.expected,
                    "actual": c.actual,
                    "severity": c.severity,
                    "exception_match": c.exception_match,
                    "note": c.note,
                }
                for c in self.checks
            ],
            "fatal_count": self.fatal_count,
            "warning_count": self.warning_count,
            "informational_count": self.informational_count,
            "match_count": self.match_count,
            "overall": self.overall,
        }


# ---------------------------------------------------------------------------
# Module loader (mirrors tier0 pattern; B214 sys.modules pre-register)
# ---------------------------------------------------------------------------


def _load_tool_module() -> Any:
    if _TOOL_MODULE_KEY in sys.modules:
        del sys.modules[_TOOL_MODULE_KEY]

    mock_connections = MagicMock()
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    executed_sql: list[str] = []
    executed_params: list[tuple] = []

    def _capture_execute(sql, *args, **kwargs):
        executed_sql.append(str(sql))
        executed_params.append(tuple(args))

    mock_cursor.execute.side_effect = _capture_execute
    mock_cursor.fetchone.return_value = (12345,)
    mock_cursor.description = [("AuditEventId",)]
    mock_conn.cursor.return_value = mock_cursor
    mock_connections.get_connection = MagicMock(return_value=mock_conn)

    mock_config = MagicMock()
    mock_config.GENERAL_DB = "General"

    sys_modules_patch: dict[str, Any] = {
        "connections": mock_connections,
        "utils.connections": mock_connections,
        "config": mock_config,
        "utils.configuration": mock_config,
    }

    with patch.dict("sys.modules", sys_modules_patch):
        spec = importlib.util.spec_from_file_location(
            _TOOL_MODULE_KEY, _TOOL_PATH
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[_TOOL_MODULE_KEY] = mod
        spec.loader.exec_module(mod)

    mod._test_sys_modules_patch = sys_modules_patch
    mod._test_cursor = mock_cursor
    mod._test_executed_sql = executed_sql
    mod._test_executed_params = executed_params
    return mod


def _call_main(mod, *, verify_fn=None, alert_fn=None, **overrides) -> dict:
    defaults = dict(
        actor="test-actor",
        baseline_path=None,
        server_name=None,
        fail_on_warning=False,
        alert=None,
        json_output=False,
        verbose=False,
        quiet=False,
        justification=None,
        no_audit_event=True,
    )
    defaults.update(overrides)
    sys_modules_patch = getattr(mod, "_test_sys_modules_patch", {})
    with patch.dict("sys.modules", sys_modules_patch):
        return mod.main(verify_fn=verify_fn, alert_fn=alert_fn, **defaults)


# ===========================================================================
# Class: TestExitCodeMapping — per § 3.7 L1011-1014
# ===========================================================================


class TestExitCodeMapping:
    """Per-severity tier exit-code mapping (Round 5 Tier 1 surface)."""

    def test_pass_overall_is_exit_0(self):
        mod = _load_tool_module()
        fv = MagicMock(
            return_value=FakeParityReport(
                server_name="s",
                baseline_name="b",
                baseline_pinned_at="t",
                match_count=5,
                overall="pass",
            )
        )
        result = _call_main(mod, verify_fn=fv)
        assert result["exit_code"] == EXIT_SUCCESS

    def test_warn_overall_is_exit_1(self):
        mod = _load_tool_module()
        fv = MagicMock(
            return_value=FakeParityReport(
                server_name="s",
                baseline_name="b",
                baseline_pinned_at="t",
                warning_count=2,
                overall="warn",
            )
        )
        result = _call_main(mod, verify_fn=fv)
        assert result["exit_code"] == EXIT_WARNING

    def test_fail_overall_is_exit_2(self):
        mod = _load_tool_module()
        fv = MagicMock(
            return_value=FakeParityReport(
                server_name="s",
                baseline_name="b",
                baseline_pinned_at="t",
                fatal_count=1,
                overall="fail",
            )
        )
        result = _call_main(mod, verify_fn=fv)
        assert result["exit_code"] == EXIT_FATAL

    def test_parity_fatal_error_is_exit_2(self):
        mod = _load_tool_module()
        from utils.errors import ParityFatalError

        fv = MagicMock(side_effect=ParityFatalError("fatal"))
        result = _call_main(mod, verify_fn=fv)
        assert result["exit_code"] == EXIT_FATAL
        assert result["error_type"] == "ParityFatalError"

    def test_parity_baseline_missing_is_exit_2(self):
        mod = _load_tool_module()
        from utils.errors import ParityBaselineMissing

        fv = MagicMock(side_effect=ParityBaselineMissing("missing"))
        result = _call_main(mod, verify_fn=fv)
        assert result["exit_code"] == EXIT_FATAL
        assert result["error_type"] == "ParityBaselineMissing"

    def test_parity_probe_error_is_exit_2(self):
        mod = _load_tool_module()
        from utils.errors import ParityProbeError

        fv = MagicMock(side_effect=ParityProbeError("probe failed"))
        result = _call_main(mod, verify_fn=fv)
        assert result["exit_code"] == EXIT_FATAL
        assert result["error_type"] == "ParityProbeError"

    def test_unknown_overall_value_is_exit_2(self):
        """Defensive — unknown overall value defaults to fatal exit code."""
        mod = _load_tool_module()
        fv = MagicMock(
            return_value=FakeParityReport(
                server_name="s",
                baseline_name="b",
                baseline_pinned_at="t",
                overall="bogus",
            )
        )
        result = _call_main(mod, verify_fn=fv)
        assert result["exit_code"] == EXIT_FATAL

    def test_unexpected_exception_is_exit_2(self):
        """Per § 1.8 default — unexpected exception -> fatal exit code."""
        mod = _load_tool_module()
        fv = MagicMock(side_effect=RuntimeError("unexpected!"))
        result = _call_main(mod, verify_fn=fv)
        assert result["exit_code"] == EXIT_FATAL


# ===========================================================================
# Class: TestFailOnWarning — per § 3.7 L988 + L1016(h)
# ===========================================================================


class TestFailOnWarning:
    """--fail-on-warning maps warning -> fatal."""

    def test_fail_on_warning_with_parity_fatal_error_is_exit_2(self):
        """M8 raises ParityFatalError when fail_on_warning=True + warnings."""
        mod = _load_tool_module()
        from utils.errors import ParityFatalError

        fv = MagicMock(
            side_effect=ParityFatalError(
                "Warning-tier parity drift with fail_on_warning=True"
            )
        )
        result = _call_main(mod, verify_fn=fv, fail_on_warning=True)
        assert result["exit_code"] == EXIT_FATAL

    def test_fail_on_warning_passes_through_to_m8(self):
        """fail_on_warning kwarg must reach M8 verify_server_parity()."""
        mod = _load_tool_module()
        fv = MagicMock(
            return_value=FakeParityReport(
                server_name="s",
                baseline_name="b",
                baseline_pinned_at="t",
                match_count=1,
                overall="pass",
            )
        )
        _call_main(mod, verify_fn=fv, fail_on_warning=True)
        call_kwargs = fv.call_args.kwargs
        assert call_kwargs.get("fail_on_warning") is True

    def test_default_fail_on_warning_is_false(self):
        mod = _load_tool_module()
        fv = MagicMock(
            return_value=FakeParityReport(
                server_name="s",
                baseline_name="b",
                baseline_pinned_at="t",
                match_count=1,
                overall="pass",
            )
        )
        _call_main(mod, verify_fn=fv)  # no fail_on_warning kwarg
        call_kwargs = fv.call_args.kwargs
        assert call_kwargs.get("fail_on_warning") is False


# ===========================================================================
# Class: TestAlertDispatch — per § 3.7 L996 + L1016(g)
# ===========================================================================


class TestAlertDispatch:
    """--alert default heuristic + explicit ON / OFF."""

    def test_alert_on_fatal_invokes_dispatcher_once(self):
        mod = _load_tool_module()
        from utils.errors import ParityFatalError

        fv = MagicMock(side_effect=ParityFatalError("fatal"))
        af = MagicMock(return_value=True)
        result = _call_main(mod, verify_fn=fv, alert_fn=af, alert=True)
        assert result["exit_code"] == EXIT_FATAL
        assert af.call_count == 1
        assert af.call_args.kwargs.get("severity") == "fatal"

    def test_alert_on_warning_invokes_dispatcher_once(self):
        mod = _load_tool_module()
        fv = MagicMock(
            return_value=FakeParityReport(
                server_name="s",
                baseline_name="b",
                baseline_pinned_at="t",
                warning_count=1,
                overall="warn",
            )
        )
        af = MagicMock(return_value=True)
        result = _call_main(mod, verify_fn=fv, alert_fn=af, alert=True)
        assert result["exit_code"] == EXIT_WARNING
        assert af.call_count == 1
        assert af.call_args.kwargs.get("severity") == "warning"

    def test_alert_on_pass_does_not_invoke_dispatcher(self):
        """No alert fires when overall='pass' (only on warn/fatal)."""
        mod = _load_tool_module()
        fv = MagicMock(
            return_value=FakeParityReport(
                server_name="s",
                baseline_name="b",
                baseline_pinned_at="t",
                match_count=10,
                overall="pass",
            )
        )
        af = MagicMock(return_value=True)
        result = _call_main(mod, verify_fn=fv, alert_fn=af, alert=True)
        assert result["exit_code"] == EXIT_SUCCESS
        assert af.call_count == 0

    def test_no_alert_does_not_invoke_dispatcher_on_fatal(self):
        mod = _load_tool_module()
        from utils.errors import ParityFatalError

        fv = MagicMock(side_effect=ParityFatalError("fatal"))
        af = MagicMock(return_value=True)
        result = _call_main(mod, verify_fn=fv, alert_fn=af, alert=False)
        assert result["exit_code"] == EXIT_FATAL
        assert af.call_count == 0

    def test_actor_automic_default_alert_on(self):
        """--alert default = True when actor='automic' per § 3.7 L996."""
        mod = _load_tool_module()
        fv = MagicMock(
            return_value=FakeParityReport(
                server_name="s",
                baseline_name="b",
                baseline_pinned_at="t",
                warning_count=1,
                overall="warn",
            )
        )
        af = MagicMock(return_value=True)
        result = _call_main(
            mod,
            verify_fn=fv,
            alert_fn=af,
            actor="automic",
            alert=None,  # let main() pick from actor
        )
        assert result["alert"] is True
        assert af.call_count == 1

    def test_actor_pipeline_default_alert_on(self):
        """--alert default = True when actor='pipeline' per § 3.7 L996."""
        mod = _load_tool_module()
        fv = MagicMock(
            return_value=FakeParityReport(
                server_name="s",
                baseline_name="b",
                baseline_pinned_at="t",
                warning_count=1,
                overall="warn",
            )
        )
        af = MagicMock(return_value=True)
        result = _call_main(
            mod,
            verify_fn=fv,
            alert_fn=af,
            actor="pipeline",
            alert=None,
        )
        assert result["alert"] is True
        assert af.call_count == 1

    def test_actor_operator_default_alert_off(self):
        """--alert default = False when actor='operator' per § 3.7 L996."""
        mod = _load_tool_module()
        fv = MagicMock(
            return_value=FakeParityReport(
                server_name="s",
                baseline_name="b",
                baseline_pinned_at="t",
                warning_count=1,
                overall="warn",
            )
        )
        af = MagicMock(return_value=True)
        result = _call_main(
            mod,
            verify_fn=fv,
            alert_fn=af,
            actor="operator",
            alert=None,
        )
        assert result["alert"] is False
        assert af.call_count == 0

    def test_alert_dispatcher_exception_does_not_break_cli(self):
        """alert_fn raising must not break the verdict exit code."""
        mod = _load_tool_module()
        from utils.errors import ParityFatalError

        fv = MagicMock(side_effect=ParityFatalError("fatal"))
        af = MagicMock(side_effect=RuntimeError("Slack 500"))
        result = _call_main(mod, verify_fn=fv, alert_fn=af, alert=True)
        assert result["exit_code"] == EXIT_FATAL
        assert result["alert_fired"] is False


# ===========================================================================
# Class: TestBaselinePathOverride — per § 3.7 L987
# ===========================================================================


class TestBaselinePathOverride:
    """--baseline-path overrides DEFAULT_BASELINE_PATH per § 3.7 L987."""

    def test_default_baseline_path_used_when_omitted(self):
        mod = _load_tool_module()
        fv = MagicMock(
            return_value=FakeParityReport(
                server_name="s",
                baseline_name="b",
                baseline_pinned_at="t",
                match_count=1,
                overall="pass",
            )
        )
        result = _call_main(mod, verify_fn=fv, baseline_path=None)
        call_kwargs = fv.call_args.kwargs
        assert call_kwargs.get("baseline_path") == _DEFAULT_BASELINE
        assert result["baseline_path"] == _DEFAULT_BASELINE

    def test_baseline_path_override_threads_through(self):
        mod = _load_tool_module()
        fv = MagicMock(
            return_value=FakeParityReport(
                server_name="s",
                baseline_name="b",
                baseline_pinned_at="t",
                match_count=1,
                overall="pass",
            )
        )
        custom = "/tmp/parity_baseline_test.json"
        result = _call_main(mod, verify_fn=fv, baseline_path=custom)
        call_kwargs = fv.call_args.kwargs
        assert call_kwargs.get("baseline_path") == custom
        assert result["baseline_path"] == custom


# ===========================================================================
# Class: TestArgparseSurface — D75 canonical args + § 3.7 tool-specific
# ===========================================================================


class TestArgparseSurface:
    """argparse round-trip for every canonical + tool-specific argument."""

    def test_help_exits_0(self):
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--help"])
        assert exc_info.value.code == 0

    def test_canonical_actor_accepted(self):
        mod = _load_tool_module()
        parser = mod._build_parser()
        for actor in ("operator", "automic", "pipeline"):
            ns = parser.parse_args(["--actor", actor])
            assert ns.actor == actor

    def test_baseline_path_arg_accepted(self):
        mod = _load_tool_module()
        parser = mod._build_parser()
        ns = parser.parse_args(["--baseline-path", "/tmp/x.json"])
        assert ns.baseline_path == "/tmp/x.json"

    def test_fail_on_warning_flag(self):
        mod = _load_tool_module()
        parser = mod._build_parser()
        ns = parser.parse_args(["--fail-on-warning"])
        assert ns.fail_on_warning is True
        ns2 = parser.parse_args([])
        assert ns2.fail_on_warning is False

    def test_alert_flag(self):
        mod = _load_tool_module()
        parser = mod._build_parser()
        ns = parser.parse_args(["--alert"])
        assert ns.alert_explicit is True

    def test_no_alert_flag(self):
        mod = _load_tool_module()
        parser = mod._build_parser()
        ns = parser.parse_args(["--no-alert"])
        assert ns.no_alert is True

    def test_alert_and_no_alert_mutex(self):
        """--alert + --no-alert -> SystemExit via parser.error()."""
        mod = _load_tool_module()
        parser = mod._build_parser()
        ns = parser.parse_args(["--alert", "--no-alert"])
        with pytest.raises(SystemExit):
            mod._validate_args(ns, parser)

    def test_json_flag(self):
        mod = _load_tool_module()
        parser = mod._build_parser()
        ns = parser.parse_args(["--json"])
        assert ns.json_output is True

    def test_verbose_flag(self):
        mod = _load_tool_module()
        parser = mod._build_parser()
        ns = parser.parse_args(["--verbose"])
        assert ns.verbose is True
        ns2 = parser.parse_args(["-v"])
        assert ns2.verbose is True

    def test_quiet_flag(self):
        mod = _load_tool_module()
        parser = mod._build_parser()
        ns = parser.parse_args(["--quiet"])
        assert ns.quiet is True
        ns2 = parser.parse_args(["-q"])
        assert ns2.quiet is True

    def test_no_audit_event_flag(self):
        mod = _load_tool_module()
        parser = mod._build_parser()
        ns = parser.parse_args(["--no-audit-event"])
        assert ns.no_audit_event is True

    def test_justification_arg(self):
        mod = _load_tool_module()
        parser = mod._build_parser()
        ns = parser.parse_args(["--justification", "pre-deploy check"])
        assert ns.justification == "pre-deploy check"

    def test_invented_arg_rejected(self):
        """Forward-incompat guard: invented args must be rejected.

        Truly invented arg names (no prefix collision with the canonical
        set --baseline-path / --fail-on-warning / --alert / --no-alert /
        --no-audit-event / canonical D75 args). argparse uses prefix
        matching by default, so '--baseline' would resolve to --baseline-
        path; that's intentional argparse behavior, not a Pitfall #9 risk.
        """
        mod = _load_tool_module()
        parser = mod._build_parser()
        # These names do NOT prefix-match any canonical arg.
        for invented in (
            "--retention-date",
            "--actor-name",
            "--categories",
            "--registry-id",
            "--cutoff-override",
            "--severity",
        ):
            with pytest.raises(SystemExit):
                # argparse.error() raises SystemExit(2) by default
                parser.parse_args([invented, "x"])


# ===========================================================================
# Class: TestActorHeuristic — per § 1.7 invocation-pattern heuristic
# ===========================================================================


class TestActorHeuristic:
    """_detect_actor() per § 1.7 (AUTOMIC_RUN_ID > isatty > pipeline)."""

    def test_automic_env_var_returns_automic(self, monkeypatch):
        mod = _load_tool_module()
        monkeypatch.setenv("AUTOMIC_RUN_ID", "12345")
        assert mod._detect_actor() == "automic"

    def test_tty_returns_operator(self, monkeypatch):
        mod = _load_tool_module()
        monkeypatch.delenv("AUTOMIC_RUN_ID", raising=False)
        with patch.object(sys.stdin, "isatty", return_value=True):
            assert mod._detect_actor() == "operator"

    def test_no_tty_no_env_returns_pipeline(self, monkeypatch):
        mod = _load_tool_module()
        monkeypatch.delenv("AUTOMIC_RUN_ID", raising=False)
        with patch.object(sys.stdin, "isatty", return_value=False):
            assert mod._detect_actor() == "pipeline"

    def test_isatty_value_error_falls_back(self, monkeypatch):
        """ValueError on closed stdin (pytest -s pipe) falls back to pipeline."""
        mod = _load_tool_module()
        monkeypatch.delenv("AUTOMIC_RUN_ID", raising=False)
        with patch.object(
            sys.stdin, "isatty", side_effect=ValueError("closed")
        ):
            assert mod._detect_actor() == "pipeline"


# ===========================================================================
# Class: TestStdoutDispatch — human vs JSON vs quiet
# ===========================================================================


class TestStdoutDispatch:
    """Stdout rendering: human / JSON / quiet."""

    def test_human_summary_emits_overall_line(self):
        mod = _load_tool_module()
        fv = MagicMock(
            return_value=FakeParityReport(
                server_name="s",
                baseline_name="b",
                baseline_pinned_at="t",
                checks=[
                    FakeParityCheck(
                        key="library_sha.polars",
                        expected="1.4.0",
                        actual="1.5.0",
                        severity="warning",
                    )
                ],
                warning_count=1,
                overall="warn",
            )
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            _call_main(mod, verify_fn=fv)
        out = buf.getvalue()
        assert "Overall: warn" in out
        assert "library_sha.polars" in out

    def test_human_summary_all_match_short_form(self):
        mod = _load_tool_module()
        fv = MagicMock(
            return_value=FakeParityReport(
                server_name="s",
                baseline_name="b",
                baseline_pinned_at="t",
                checks=[
                    FakeParityCheck(
                        key="python.version",
                        expected="3.12.11",
                        actual="3.12.11",
                        severity="match",
                    ),
                    FakeParityCheck(
                        key="malloc_arena_max",
                        expected="2",
                        actual="2",
                        severity="match",
                    ),
                ],
                match_count=2,
                overall="pass",
            )
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            _call_main(mod, verify_fn=fv)
        out = buf.getvalue()
        assert "Parity: all 2 checks pass." in out

    def test_json_output_emits_canonical_dict(self):
        mod = _load_tool_module()
        fv = MagicMock(
            return_value=FakeParityReport(
                server_name="srv",
                baseline_name="base",
                baseline_pinned_at="2026-01-01T00:00:00",
                checks=[
                    FakeParityCheck(
                        key="python.version",
                        expected="3.12.11",
                        actual="3.12.11",
                        severity="match",
                    ),
                ],
                match_count=1,
                overall="pass",
            )
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            _call_main(mod, verify_fn=fv, json_output=True)
        out = buf.getvalue().strip()
        payload = json.loads(out)
        # All canonical fields per § 3.7 L1009
        assert set(payload.keys()) == {
            "server_name",
            "baseline_name",
            "baseline_pinned_at",
            "checks",
            "fatal_count",
            "warning_count",
            "informational_count",
            "match_count",
            "overall",
        }
        assert payload["overall"] == "pass"
        assert payload["match_count"] == 1
        # ParityCheck fields canonical
        assert set(payload["checks"][0].keys()) == {
            "key",
            "expected",
            "actual",
            "severity",
            "exception_match",
            "note",
        }

    def test_quiet_suppresses_stdout(self):
        mod = _load_tool_module()
        fv = MagicMock(
            return_value=FakeParityReport(
                server_name="s",
                baseline_name="b",
                baseline_pinned_at="t",
                match_count=1,
                overall="pass",
            )
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            _call_main(mod, verify_fn=fv, quiet=True)
        out = buf.getvalue()
        # Quiet suppresses summary but stderr still allowed
        assert "Parity" not in out

    def test_baseline_missing_emits_stderr_message(self):
        mod = _load_tool_module()
        from utils.errors import ParityBaselineMissing

        fv = MagicMock(side_effect=ParityBaselineMissing("/etc/foo missing"))
        out_buf = io.StringIO()
        err_buf = io.StringIO()
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            _call_main(mod, verify_fn=fv)
        err = err_buf.getvalue()
        # Per § 3.7 L982: stderr message "baseline JSON missing or malformed"
        assert "baseline JSON missing or malformed" in err

    def test_probe_error_emits_stderr_message(self):
        mod = _load_tool_module()
        from utils.errors import ParityProbeError

        fv = MagicMock(side_effect=ParityProbeError("tpm2_getcap non-zero"))
        err_buf = io.StringIO()
        with redirect_stderr(err_buf):
            _call_main(mod, verify_fn=fv)
        err = err_buf.getvalue()
        assert "parity probe failed" in err.lower()


# ===========================================================================
# Class: TestAuditRowMetadata — D76 canonical shape
# ===========================================================================


class TestAuditRowMetadata:
    """Audit row Metadata dict structure per D76 + spec § 3.7 L993."""

    def test_result_carries_canonical_metadata_keys(self):
        mod = _load_tool_module()
        fv = MagicMock(
            return_value=FakeParityReport(
                server_name="s",
                baseline_name="b",
                baseline_pinned_at="t",
                match_count=1,
                overall="pass",
            )
        )
        result = _call_main(mod, verify_fn=fv, actor="operator")
        for key in (
            "event_kind",
            "actor",
            "justification",
            "baseline_path",
            "fail_on_warning",
            "alert",
            "report",
            "exit_code",
            "started_at",
            "completed_at",
            "audit_event_id",
            "alert_fired",
        ):
            assert key in result, f"Result must carry canonical key {key!r}"
        assert result["event_kind"] == "parity_verify"
        assert result["actor"] == "operator"

    def test_no_audit_event_skips_write(self):
        mod = _load_tool_module()
        fv = MagicMock(
            return_value=FakeParityReport(
                server_name="s",
                baseline_name="b",
                baseline_pinned_at="t",
                match_count=1,
                overall="pass",
            )
        )
        result = _call_main(mod, verify_fn=fv, no_audit_event=True)
        # no_audit_event=True means _write_audit_row returns None
        assert result["audit_event_id"] is None

    def test_started_at_format_iso8601_naive(self):
        mod = _load_tool_module()
        fv = MagicMock(
            return_value=FakeParityReport(
                server_name="s",
                baseline_name="b",
                baseline_pinned_at="t",
                match_count=1,
                overall="pass",
            )
        )
        result = _call_main(mod, verify_fn=fv)
        # ISO-8601 naive-UTC per D76 canonical
        assert result["started_at"].endswith("Z")
        assert "T" in result["started_at"]

    def test_justification_carried_through(self):
        mod = _load_tool_module()
        fv = MagicMock(
            return_value=FakeParityReport(
                server_name="s",
                baseline_name="b",
                baseline_pinned_at="t",
                match_count=1,
                overall="pass",
            )
        )
        result = _call_main(
            mod, verify_fn=fv, justification="pre-deploy check"
        )
        assert result["justification"] == "pre-deploy check"


# ===========================================================================
# Class: TestReportSerialization — canonical dict shape per § 3.7 L1009
# ===========================================================================


class TestReportSerialization:
    """ParityReport -> dict round-trip; no invented fields; no canonical dropped."""

    def test_to_dict_used_when_available(self):
        mod = _load_tool_module()
        report = FakeParityReport(
            server_name="s",
            baseline_name="b",
            baseline_pinned_at="t",
            match_count=1,
            overall="pass",
        )
        d = mod._report_to_dict(report)
        # Canonical 9 fields per R2 § 4.2 L948-955
        for field_name in (
            "server_name",
            "baseline_name",
            "baseline_pinned_at",
            "checks",
            "fatal_count",
            "warning_count",
            "informational_count",
            "match_count",
            "overall",
        ):
            assert field_name in d

    def test_invented_fields_not_present(self):
        """No 'generated_at' or 'baseline_sha256' (Pitfall #9 caught earlier)."""
        mod = _load_tool_module()
        report = FakeParityReport(
            server_name="s",
            baseline_name="b",
            baseline_pinned_at="t",
            match_count=1,
            overall="pass",
        )
        d = mod._report_to_dict(report)
        for invented in ("generated_at", "baseline_sha256", "name"):
            assert invented not in d, (
                f"Invented field {invented!r} must not appear in serialized "
                f"ParityReport dict. Got: {sorted(d.keys())}"
            )

    def test_check_uses_key_not_name(self):
        """ParityCheck uses 'key' (canonical) not 'name' (invented)."""
        mod = _load_tool_module()
        report = FakeParityReport(
            server_name="s",
            baseline_name="b",
            baseline_pinned_at="t",
            checks=[
                FakeParityCheck(
                    key="python.version",
                    expected="3.12.11",
                    actual="3.12.11",
                    severity="match",
                )
            ],
            match_count=1,
            overall="pass",
        )
        d = mod._report_to_dict(report)
        check_keys = set(d["checks"][0].keys())
        assert "key" in check_keys
        assert "name" not in check_keys

    def test_fallback_asdict_on_missing_to_dict(self):
        """Falls back to dataclasses.asdict if to_dict missing."""
        mod = _load_tool_module()

        @dataclass
        class MinimalReport:
            server_name: str = "x"
            baseline_name: str = "y"
            baseline_pinned_at: str = "z"
            checks: list = field(default_factory=list)
            fatal_count: int = 0
            warning_count: int = 0
            informational_count: int = 0
            match_count: int = 0
            overall: str = "pass"

        report = MinimalReport()
        d = mod._report_to_dict(report)
        assert d["overall"] == "pass"
        assert d["server_name"] == "x"


# ===========================================================================
# Class: TestCanonicalExceptionImports — B228 contract
# ===========================================================================


class TestCanonicalExceptionImports:
    """Exception classes imported from canonical utils.errors per B228."""

    def test_exceptions_imported_from_utils_errors(self):
        mod = _load_tool_module()
        # Exception names must resolve from utils.errors per B228
        from utils.errors import (
            ParityBaselineMissing as canonical_missing,
        )
        from utils.errors import (
            ParityFatalError as canonical_fatal,
        )
        from utils.errors import (
            ParityProbeError as canonical_probe,
        )

        # And the module must use them (identity check)
        # The CLI module imports them at top-level; verify via the
        # module's namespace.
        assert mod.ParityFatalError is canonical_fatal
        assert mod.ParityBaselineMissing is canonical_missing
        assert mod.ParityProbeError is canonical_probe

    def test_exceptions_are_pipeline_fatal_subclasses(self):
        from utils.errors import (
            ParityBaselineMissing,
            ParityFatalError,
            ParityProbeError,
            PipelineFatalError,
        )

        assert issubclass(ParityFatalError, PipelineFatalError)
        assert issubclass(ParityBaselineMissing, PipelineFatalError)
        assert issubclass(ParityProbeError, PipelineFatalError)


# ===========================================================================
# Class: TestCliMainArgv — argv-driven entry point
# ===========================================================================


class TestCliMainArgv:
    """cli_main() argv-driven path returns 0/1/2 only per D74."""

    def test_cli_main_returns_int_in_canonical_set(self, monkeypatch):
        mod = _load_tool_module()
        # We can't fully drive cli_main without mocking ALL of M8 + audit;
        # instead, test the exit-code clamp via the main() return path
        # using a direct call that simulates the argv layer.

        # Patch parse_args to return a known namespace
        ns = argparse.Namespace(
            actor="operator",
            justification=None,
            baseline_path=None,
            fail_on_warning=False,
            alert_explicit=False,
            no_alert=False,
            json_output=False,
            verbose=False,
            quiet=True,
            no_audit_event=True,
        )
        fv = MagicMock(
            return_value=FakeParityReport(
                server_name="s",
                baseline_name="b",
                baseline_pinned_at="t",
                match_count=1,
                overall="pass",
            )
        )

        # Patch the verify_fn resolution to return our fake
        with patch.object(mod, "_resolve_verify_fn", return_value=fv), \
             patch.object(
                 argparse.ArgumentParser, "parse_args", return_value=ns
             ):
            code = mod.cli_main()
        assert code in {EXIT_SUCCESS, EXIT_WARNING, EXIT_FATAL}
        assert code == EXIT_SUCCESS

    def test_cli_main_warn_returns_1(self):
        mod = _load_tool_module()
        ns = argparse.Namespace(
            actor="operator",
            justification=None,
            baseline_path=None,
            fail_on_warning=False,
            alert_explicit=False,
            no_alert=True,  # suppress alert so no external call
            json_output=False,
            verbose=False,
            quiet=True,
            no_audit_event=True,
        )
        fv = MagicMock(
            return_value=FakeParityReport(
                server_name="s",
                baseline_name="b",
                baseline_pinned_at="t",
                warning_count=1,
                overall="warn",
            )
        )
        with patch.object(mod, "_resolve_verify_fn", return_value=fv), \
             patch.object(
                 argparse.ArgumentParser, "parse_args", return_value=ns
             ):
            code = mod.cli_main()
        assert code == EXIT_WARNING

    def test_cli_main_fatal_returns_2(self):
        mod = _load_tool_module()
        from utils.errors import ParityFatalError

        ns = argparse.Namespace(
            actor="operator",
            justification=None,
            baseline_path=None,
            fail_on_warning=False,
            alert_explicit=False,
            no_alert=True,
            json_output=False,
            verbose=False,
            quiet=True,
            no_audit_event=True,
        )
        fv = MagicMock(side_effect=ParityFatalError("fatal"))
        with patch.object(mod, "_resolve_verify_fn", return_value=fv), \
             patch.object(
                 argparse.ArgumentParser, "parse_args", return_value=ns
             ):
            code = mod.cli_main()
        assert code == EXIT_FATAL


# ===========================================================================
# Class: TestModuleConstants
# ===========================================================================


class TestModuleConstants:
    """Module-level constants honor the canonical contract."""

    def test_exit_codes_are_canonical(self):
        mod = _load_tool_module()
        assert mod.EXIT_SUCCESS == 0
        assert mod.EXIT_WARNING == 1
        assert mod.EXIT_FATAL == 2

    def test_event_type_is_cli_family(self):
        mod = _load_tool_module()
        assert mod.EVENT_TYPE == "CLI_VERIFY_SERVER_PARITY"
        assert mod.EVENT_TYPE.startswith("CLI_")

    def test_default_baseline_path_d103_canonical(self):
        mod = _load_tool_module()
        # D103: baseline lives OUTSIDE /debi; mode 0644
        assert mod.DEFAULT_BASELINE_PATH == _DEFAULT_BASELINE
        assert not mod.DEFAULT_BASELINE_PATH.startswith("/debi")

    def test_alert_auto_on_actor_set(self):
        mod = _load_tool_module()
        # Per § 3.7 L996
        assert "automic" in mod._ALERT_AUTO_ON_ACTORS
        assert "pipeline" in mod._ALERT_AUTO_ON_ACTORS
        # operator NOT in set
        assert "operator" not in mod._ALERT_AUTO_ON_ACTORS


# ===========================================================================
# Class: TestPerCheckCoverage — Round 5 surface (Tier 1)
# ===========================================================================


class TestPerCheckCoverage:
    """Per-check coverage per § 3.7 L1019 Tier 1 surface.

    Round 5 surface mentions Python version, library SHA, env var,
    filesystem layout, systemd unit, TPM2 PCR, envelope SHA.
    """

    @pytest.mark.parametrize(
        "check_key, severity",
        [
            ("python.version", "match"),
            ("library_sha.polars", "warning"),
            ("env_vars_required.MALLOC_ARENA_MAX", "fatal"),
            ("filesystem_layout./etc/pipeline", "match"),
            ("systemd_unit.sha256", "warning"),
            ("tpm2.pcr_policy_hash", "informational"),
            ("credentials_envelope.sha256", "fatal"),
            ("udm_tables_list_schema.expected_columns_sha256", "match"),
        ],
    )
    def test_check_key_surfaces_in_json_payload(self, check_key, severity):
        """Each canonical check_key surfaces in the JSON output."""
        mod = _load_tool_module()
        # Construct a report with this single check
        report = FakeParityReport(
            server_name="s",
            baseline_name="b",
            baseline_pinned_at="t",
            checks=[
                FakeParityCheck(
                    key=check_key,
                    expected="X",
                    actual="Y" if severity != "match" else "X",
                    severity=severity,
                )
            ],
            fatal_count=1 if severity == "fatal" else 0,
            warning_count=1 if severity == "warning" else 0,
            informational_count=1 if severity == "informational" else 0,
            match_count=1 if severity == "match" else 0,
            overall=(
                "fail"
                if severity == "fatal"
                else "warn"
                if severity == "warning"
                else "pass"
            ),
        )

        # Use overall='fail' triggers exception-class M8 normally; here
        # we feed back the report directly, so the CLI maps overall='fail'
        # via the defensive path
        fv = MagicMock(return_value=report)
        buf = io.StringIO()
        with redirect_stdout(buf):
            _call_main(mod, verify_fn=fv, json_output=True)
        payload = json.loads(buf.getvalue().strip())
        check_keys = [c["key"] for c in payload["checks"]]
        assert check_key in check_keys


# ===========================================================================
# Class: TestExceptionMetadataPropagation
# ===========================================================================


class TestExceptionMetadataPropagation:
    """ParityFatalError + ParityProbeError carry metadata to audit row."""

    def test_fatal_metadata_propagated(self):
        mod = _load_tool_module()
        from utils.errors import ParityFatalError

        exc = ParityFatalError(
            "fatal drift",
            metadata={"server_name": "foo", "fatal_keys": ["envelope.sha256"]},
        )
        fv = MagicMock(side_effect=exc)
        result = _call_main(mod, verify_fn=fv)
        assert result["exit_code"] == EXIT_FATAL
        assert "fatal_metadata" in result
        assert result["fatal_metadata"]["server_name"] == "foo"

    def test_probe_metadata_propagated(self):
        mod = _load_tool_module()
        from utils.errors import ParityProbeError

        exc = ParityProbeError(
            "TPM2 hardware probe failed",
            metadata={"probe": "tpm2_getcap", "status": "non-zero (rc=1)"},
        )
        fv = MagicMock(side_effect=exc)
        result = _call_main(mod, verify_fn=fv)
        assert result["exit_code"] == EXIT_FATAL
        assert "probe_metadata" in result
        assert result["probe_metadata"]["probe"] == "tpm2_getcap"


# ===========================================================================
# Class: TestM8ResolutionFailure
# ===========================================================================


class TestM8ResolutionFailure:
    """If M8 module cannot be resolved -> exit 2 (defensive)."""

    def test_unresolvable_verify_fn_exits_2(self):
        mod = _load_tool_module()
        # Force the resolver to raise
        with patch.object(
            mod,
            "_resolve_verify_fn",
            side_effect=ImportError("M8 not installed"),
        ):
            result = _call_main(mod, verify_fn=None)
        assert result["exit_code"] == EXIT_FATAL
        assert "M8" in result["error_message"] or "verify_server_parity" in result[
            "error_message"
        ]
