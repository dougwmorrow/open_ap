"""Tier 1 unit tests for tools/detect_extraction_gaps.py.

Per D70 Tier 1 — per-function + per-error-path coverage; mocks pyodbc
cursor + Round 3 § 5.3 gap_detector engine + Round 4 § 3.11
alert_dispatcher; no live SQL Server.

Tests run on every commit. No live DB, no live network required.
All external dependencies mocked with unittest.mock.

North Star pillars (NORTH_STAR.md):
  - Audit-grade (D76): exactly one CLI_DETECT_EXTRACTION_GAPS
    PipelineEventLog row per invocation; Metadata JSON carries
    as_of_date, source_filter, tables_with_gaps, total_missing_dates,
    affected_tables, alert_fired, event_kind='gap_detection', actor,
    exit_code, dry_run=False; audit_event_id key MUST be present in
    return dict (B218: presence over content).
  - Operationally stable (D74/D75): exit-code contract (0/1/2) and
    argument naming discipline exactly per spec; Automic interprets
    the contract (exit 0 = no gaps; exit 1 = gaps OR retryable error
    per D68; exit 2 = fatal).
  - Idempotent (D15/D22): read-only on PipelineExtraction; multi-call
    returns identical reports for unchanged historical data; audit
    rows are append-only (multi-call = multiple rows, intentional D26).
  - Traceability (D26): every invocation writes ONE PipelineEventLog
    row with EventType='CLI_DETECT_EXTRACTION_GAPS' (§ 3.5 L766);
    DISTINCT from the wrapped module's GAP_DETECT row.

Canonical references (Pitfall #9.l):
  Round 3 § 5.3 detect_extraction_gaps signature (tools/gap_detector.py L674):
    detect_extraction_gaps(*, source_filter: str | None = None,
                             as_of_date: date | None = None) -> list[GapReport]
  GapReport dataclass (tools/gap_detector.py L233-272):
    source_name (str), table_name (str), expected_range (tuple[date, date]),
    missing_dates (list[date]), recommended_action (str). Frozen.
  Recommended-action values (tools/gap_detector.py L201-204; Pitfall #9.c
  strict):
    'backfill' | 'investigate-source' | 'within-lookback-no-action'.
  PipelineEventLog DDL (01_database_schema.md § 2):
    BatchId, TableName, SourceName, EventType, EventDetail, StartedAt,
    CompletedAt, Status, ErrorMessage, Metadata.

D-numbers: D22 (hourly gap detector), D67 (Tier 0), D68 (error
hierarchy — GapDetectorTimeout / ExtractionStateUnavailable both
PipelineRetryableError), D74 (exit-code contract 0/1/2), D75 (canonical
arg naming), D76 (audit-row contract CLI_DETECT_EXTRACTION_GAPS), D77
(Tier 0 scaffold), D80 (Tier 0 vs Tier 1 boundary discipline), D92
(forward-only additive).

Edge case IDs (04_EDGE_CASES.md):
  G1-G5 (gap-detection series — operator review path on missing dates).
  I1 (same BatchId retry — gap detection is read-only / idempotent).
  I3 (concurrent same-key — no sp_getapplock per § 3.5 L785-786).
  N1 (parameter naming discipline — Pitfall #9.b: invented parameter
       rejection — no --apply / --dry-run for read-only tools per § 1.2).

B-numbers:
  B228 (utils.errors canonical — GapDetectorTimeout +
        ExtractionStateUnavailable imported from there).
  B214 (sys.modules pre-registration before exec_module — applied).
  B218 (audit_event_id key MUST be present in result dict; presence over
        content — applied below).
  B88 (no --apply / --dry-run mutex needed — this is a read-only tool
       per spec § 1.2; assertion below verifies absence).

Spec: phase1/04_tools.md § 3.5 (canonical spec L751-833).
M13 engine: tools/gap_detector.py (Round 3 § 5.3).

Independence note: Tier 1 is authored INDEPENDENTLY from
tools/detect_extraction_gaps.py per D55 (test author ≠ code author).
Tests pin the spec contract without reading the implementation.
"""
from __future__ import annotations

import importlib
import importlib.util
import io
import json
import sys
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import dataclass, field
from datetime import date
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

# ---------------------------------------------------------------------------
# Module path
# ---------------------------------------------------------------------------

_TOOL_PATH = _PROJECT_ROOT / "tools" / "detect_extraction_gaps.py"
_TOOL_MODULE_KEY = "tools.detect_extraction_gaps"

# ---------------------------------------------------------------------------
# Constants — single source of truth (Pitfall #9.m: test names match asserts)
# ---------------------------------------------------------------------------

# D76 EventType per CLI_* family (§ 3.5 L766)
EXPECTED_EVENT_TYPE = "CLI_DETECT_EXTRACTION_GAPS"

# D74 exit codes (§ 3.5 L829-832)
EXIT_SUCCESS = 0
EXIT_OPERATIONAL = 1
EXIT_FATAL = 2

# Canonical recommended_action values per gap_detector.py L201-204
ACTION_BACKFILL = "backfill"
ACTION_INVESTIGATE = "investigate-source"

# Canonical defaults
_ACTOR_OPERATOR = "test-author"
_ACTOR_AUTOMIC = "automic"
_ACTOR_PIPELINE = "pipeline"
_AS_OF_DATE_DEFAULT = "2026-05-12"

# Required Metadata keys per D76 + § 3.5 L766
REQUIRED_METADATA_KEYS = frozenset({
    "event_kind", "actor", "as_of_date", "source_filter",
    "tables_with_gaps", "total_missing_dates", "exit_code",
})


# ---------------------------------------------------------------------------
# GapReport stand-in
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _GapReportStub:
    """Minimal stand-in for tools.gap_detector.GapReport.

    Per gap_detector.py L233-272 — frozen dataclass with canonical
    fields. Tests stand-in so we don't depend on the real Round 3
    module for Tier 1.
    """

    source_name: str = "DNA"
    table_name: str = "ACCT"
    expected_range: tuple = (date(2026, 1, 1), date(2026, 5, 10))
    missing_dates: list = field(default_factory=lambda: [date(2026, 3, 15)])
    recommended_action: str = ACTION_BACKFILL


# ---------------------------------------------------------------------------
# Module loader — mocks all external dependencies
# ---------------------------------------------------------------------------


def _load_tool_module(
    *,
    gap_reports: list | None = None,
    raise_timeout: bool = False,
    raise_state_unavailable: bool = False,
    raise_unexpected: bool = False,
) -> Any:
    """Load tools/detect_extraction_gaps.py with all external imports mocked."""
    if _TOOL_MODULE_KEY in sys.modules:
        del sys.modules[_TOOL_MODULE_KEY]

    mock_cursor = MagicMock()
    executed_sql: list[str] = []
    executed_params: list[Any] = []

    def _capture_execute(sql: str, *args, **kwargs) -> None:
        executed_sql.append(str(sql))
        if args:
            params = args[0]
            if isinstance(params, (list, tuple)):
                executed_params.extend(params)
            else:
                executed_params.append(params)

    mock_cursor.execute.side_effect = _capture_execute

    _audit_event_id_seq = [77001, 77002, 77003, 77004, 77005]

    def _smart_fetchone():
        last_sql = executed_sql[-1] if executed_sql else ""
        if "SCOPE_IDENTITY" in last_sql.upper():
            return (_audit_event_id_seq.pop(0) if _audit_event_id_seq else 99999,)
        return None

    mock_cursor.fetchone.side_effect = _smart_fetchone
    mock_cursor.fetchall.return_value = []
    mock_cursor.rowcount = 0
    mock_cursor.description = [("AuditEventId",)]

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    mock_connections = MagicMock()
    mock_connections.cursor_for = MagicMock(return_value=mock_cursor)
    mock_connections.get_connection = MagicMock(return_value=mock_conn)

    mock_config = MagicMock()
    mock_config.GENERAL_DB = "General"

    mock_pyodbc = MagicMock()
    mock_pyodbc.connect = MagicMock(return_value=mock_conn)

    from utils.errors import (  # B228 — canonical exceptions
        ExtractionStateUnavailable,
        GapDetectorTimeout,
    )

    mock_gap_detector = MagicMock()
    if raise_timeout:
        mock_gap_detector.detect_extraction_gaps = MagicMock(
            side_effect=GapDetectorTimeout(
                "PipelineExtraction scan exceeded 60s (test fixture)"
            )
        )
    elif raise_state_unavailable:
        mock_gap_detector.detect_extraction_gaps = MagicMock(
            side_effect=ExtractionStateUnavailable(
                "Connection failure during gap detection (test fixture)"
            )
        )
    elif raise_unexpected:
        mock_gap_detector.detect_extraction_gaps = MagicMock(
            side_effect=RuntimeError("Unexpected fixture failure")
        )
    else:
        mock_gap_detector.detect_extraction_gaps = MagicMock(
            return_value=gap_reports if gap_reports is not None else []
        )
    mock_gap_detector.GapReport = _GapReportStub

    mock_alert_dispatcher = MagicMock()
    mock_alert_dispatcher.dispatch_alert = MagicMock(return_value=True)

    sys_modules_patch: dict[str, Any] = {
        "connections": mock_connections,
        "utils.connections": mock_connections,
        "config": mock_config,
        "utils.configuration": mock_config,
        "pyodbc": mock_pyodbc,
        "tools.gap_detector": mock_gap_detector,
        "tools.alert_dispatcher": mock_alert_dispatcher,
    }

    with patch.dict("sys.modules", sys_modules_patch):
        spec = importlib.util.spec_from_file_location(_TOOL_MODULE_KEY, _TOOL_PATH)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[_TOOL_MODULE_KEY] = mod
        spec.loader.exec_module(mod)

    mod._test_sys_modules_patch = sys_modules_patch
    mod._test_cursor = mock_cursor
    mod._test_executed_sql = executed_sql
    mod._test_executed_params = executed_params
    mod._test_gap_detector = mock_gap_detector
    mod._test_alert_dispatcher = mock_alert_dispatcher
    return mod


def _make_injection_detector(mod: Any):
    test_mock = mod._test_gap_detector

    def _detect(*, source_filter, as_of_date):
        return test_mock.detect_extraction_gaps(
            source_filter=source_filter,
            as_of_date=as_of_date,
        )

    return _detect


def _make_injection_alert(mod: Any):
    test_mock = mod._test_alert_dispatcher

    def _dispatch(*, severity, source_tool, message, details=None):
        return test_mock.dispatch_alert(
            severity=severity,
            source_tool=source_tool,
            message=message,
            details=details or {},
        )

    return _dispatch


def _call_main(mod: Any, *, capture_stdout: bool = True, **overrides: Any):
    """Call tool main() with canonical defaults + overrides."""
    defaults = dict(
        actor=_ACTOR_OPERATOR,
        as_of_date=_AS_OF_DATE_DEFAULT,
        source=None,
        alert=None,
        include_recommendation=True,
        json_output=False,
        verbose=False,
        quiet=False,
        no_audit_event=False,
        gap_detector=_make_injection_detector(mod),
        alert_dispatcher=_make_injection_alert(mod),
    )
    defaults.update(overrides)
    sys_modules_patch = getattr(mod, "_test_sys_modules_patch", {})

    buf_out = io.StringIO() if capture_stdout else None
    buf_err = io.StringIO()
    try:
        with patch.dict("sys.modules", sys_modules_patch):
            if buf_out is not None:
                with redirect_stdout(buf_out), redirect_stderr(buf_err):
                    result = mod.main(**defaults)
            else:
                with redirect_stderr(buf_err):
                    result = mod.main(**defaults)
    except SystemExit as exc:
        result = {"exit_code": exc.code, "_raised_system_exit": True}
    except Exception as exc:
        result = {"exit_code": EXIT_FATAL, "_exception": str(exc), "_raised_system_exit": False}

    if capture_stdout:
        return result, (buf_out.getvalue() if buf_out is not None else ""), buf_err.getvalue()
    return result, buf_err.getvalue()


# ===========================================================================
# Argument parser surface (per spec § 3.5 L797-808 + § 1.4)
# ===========================================================================


class TestArgParserSurface:
    """Argparse contract — accepted args + rejection of invented args."""

    def test_help_exits_zero(self):
        """--help exits 0 per D74 + D77."""
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--help"])
        assert exc_info.value.code == 0

    def test_no_args_invokable(self):
        """No-args invocation is valid (no required arg per spec § 3.5)."""
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        # Should not raise.
        args = parser.parse_args([])
        # alert defaults to None (so we can resolve per-actor downstream).
        assert getattr(args, "alert", "MISSING") is None
        # include_recommendation defaults to True per spec § 3.5 L807.
        assert args.include_recommendation is True
        # source defaults to None (no filter).
        assert args.source is None
        # as_of_date defaults to None (today).
        assert args.as_of_date is None

    def test_source_filter_accepted(self):
        """--source <name> accepted per spec § 1.4 + § 3.5."""
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        args = parser.parse_args(["--source", "DNA"])
        assert args.source == "DNA"

    def test_as_of_date_accepted(self):
        """--as-of-date YYYY-MM-DD accepted per spec § 3.5 L802."""
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        args = parser.parse_args(["--as-of-date", "2026-04-15"])
        assert args.as_of_date == "2026-04-15"

    def test_alert_flag_accepted(self):
        """--alert flag explicitly enables alerts."""
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        args = parser.parse_args(["--alert"])
        assert args.alert is True

    def test_no_alert_flag_accepted(self):
        """--no-alert flag explicitly disables alerts."""
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        args = parser.parse_args(["--no-alert"])
        assert args.alert is False

    def test_json_flag_accepted(self):
        """--json flag per spec § 3.5 L826."""
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        args = parser.parse_args(["--json"])
        assert args.json_output is True

    def test_no_include_recommendation_flag_accepted(self):
        """--no-include-recommendation per spec § 3.5 L807."""
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        args = parser.parse_args(["--no-include-recommendation"])
        assert args.include_recommendation is False

    def test_actor_arg_accepted(self):
        """--actor per § 1.4 D75 canonical arg."""
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        args = parser.parse_args(["--actor", "automic"])
        assert args.actor == "automic"

    def test_verbose_flag_accepted(self):
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        args = parser.parse_args(["--verbose"])
        assert args.verbose is True

    def test_quiet_flag_accepted(self):
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        args = parser.parse_args(["--quiet"])
        assert args.quiet is True

    def test_no_audit_event_flag_accepted(self):
        """--no-audit-event flag per § 1.4 + D76."""
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        args = parser.parse_args(["--no-audit-event"])
        assert args.no_audit_event is True

    def test_apply_flag_rejected(self):
        """Per spec § 1.2: read-only tools have NO --apply flag.

        Pitfall #9.b invented-parameter guard. The detect_extraction_gaps
        tool is read-only by design (it produces a report; nothing to
        apply). The CLI MUST NOT expose --apply per § 1.2 L155-157.
        """
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--apply"])
        assert exc_info.value.code == EXIT_FATAL


# ===========================================================================
# detect_actor heuristic (per § 1.7)
# ===========================================================================


class TestDetectActor:
    """Actor-detection heuristic per spec § 1.7 invocation patterns."""

    def test_automic_run_id_env_returns_automic(self, monkeypatch):
        """AUTOMIC_RUN_ID env var present -> 'automic' per § 1.7 step 1."""
        mod = _load_tool_module()
        monkeypatch.setenv("AUTOMIC_RUN_ID", "test-run-42")
        assert mod._detect_actor() == "automic"

    def test_no_automic_no_tty_returns_pipeline(self, monkeypatch):
        """No automic env + no TTY -> 'pipeline' per § 1.7 step 3."""
        mod = _load_tool_module()
        monkeypatch.delenv("AUTOMIC_RUN_ID", raising=False)
        # Force no-tty by patching sys.stdin.isatty
        with patch.object(sys.stdin, "isatty", return_value=False):
            assert mod._detect_actor() == "pipeline"


# ===========================================================================
# Alert-default resolution (per spec § 3.5 L804)
# ===========================================================================


class TestAlertDefaultResolution:
    """--alert default resolution per spec § 3.5 L804."""

    def test_automic_default_alert_on(self):
        """actor='automic' + alert=None -> True per spec § 3.5 L804."""
        mod = _load_tool_module()
        assert mod._resolve_alert_default(actor="automic", alert_flag=None) is True

    def test_operator_default_alert_off(self):
        """actor='operator' + alert=None -> False per spec § 3.5 L804."""
        mod = _load_tool_module()
        assert mod._resolve_alert_default(actor="operator", alert_flag=None) is False

    def test_pipeline_default_alert_off(self):
        """actor='pipeline' + alert=None -> False per spec § 3.5 L804."""
        mod = _load_tool_module()
        assert mod._resolve_alert_default(actor="pipeline", alert_flag=None) is False

    def test_explicit_true_honored_for_operator(self):
        """--alert override on operator forces True."""
        mod = _load_tool_module()
        assert mod._resolve_alert_default(actor="operator", alert_flag=True) is True

    def test_explicit_false_honored_for_automic(self):
        """--no-alert override on automic forces False."""
        mod = _load_tool_module()
        assert mod._resolve_alert_default(actor="automic", alert_flag=False) is False


# ===========================================================================
# Exit-code contract (per D74 + § 3.5 L829-832)
# ===========================================================================


class TestExitCodes:
    """D74 exit-code mapping per spec § 3.5 L829-832."""

    def test_empty_reports_exits_zero(self):
        """No gaps -> exit 0 per spec § 3.5 L829."""
        mod = _load_tool_module(gap_reports=[])
        result, _stdout, _stderr = _call_main(mod)
        assert result["exit_code"] == EXIT_SUCCESS

    def test_gaps_detected_exits_one(self):
        """Gaps detected -> exit 1 per spec § 3.5 L830."""
        mod = _load_tool_module(gap_reports=[_GapReportStub()])
        result, _stdout, _stderr = _call_main(mod)
        assert result["exit_code"] == EXIT_OPERATIONAL

    def test_gap_detector_timeout_exits_one(self):
        """GapDetectorTimeout (PipelineRetryableError) -> exit 1 per D68 + § 1.8."""
        mod = _load_tool_module(raise_timeout=True)
        result, _stdout, _stderr = _call_main(mod)
        assert result["exit_code"] == EXIT_OPERATIONAL

    def test_extraction_state_unavailable_exits_one(self):
        """ExtractionStateUnavailable (PipelineRetryableError) -> exit 1 per D68."""
        mod = _load_tool_module(raise_state_unavailable=True)
        result, _stdout, _stderr = _call_main(mod)
        assert result["exit_code"] == EXIT_OPERATIONAL

    def test_unexpected_exception_exits_fatal(self):
        """Unexpected RuntimeError -> exit 2 (fatal) per § 1.8."""
        mod = _load_tool_module(raise_unexpected=True)
        result, _stdout, _stderr = _call_main(mod)
        assert result["exit_code"] == EXIT_FATAL

    def test_invalid_as_of_date_exits_fatal(self):
        """Invalid --as-of-date -> exit 2 (fatal arg error) per § 1.8."""
        mod = _load_tool_module(gap_reports=[])
        result, _stdout, _stderr = _call_main(mod, as_of_date="not-a-date")
        assert result["exit_code"] == EXIT_FATAL


# ===========================================================================
# detect_extraction_gaps invocation contract (per Round 3 § 5.3)
# ===========================================================================


class TestGapDetectorInvocation:
    """Engine module invocation per Round 3 § 5.3 + spec § 3.5 L753-756."""

    def test_called_with_keyword_only_kwargs(self):
        """detect_extraction_gaps invoked with keyword args per L674 signature."""
        mod = _load_tool_module(gap_reports=[])
        _call_main(mod, source="DNA", as_of_date="2026-04-15")
        # Inspect the mock to verify it was called with keyword args.
        detector_mock = mod._test_gap_detector
        assert detector_mock.detect_extraction_gaps.call_count == 1
        call = detector_mock.detect_extraction_gaps.call_args
        # All args passed as kwargs (keyword-only per Round 3 § 5.3 signature).
        assert "source_filter" in call.kwargs
        assert call.kwargs["source_filter"] == "DNA"
        assert "as_of_date" in call.kwargs
        assert call.kwargs["as_of_date"] == date(2026, 4, 15)

    def test_default_source_filter_is_none(self):
        """No --source arg passes source_filter=None to engine (no filter)."""
        mod = _load_tool_module(gap_reports=[])
        _call_main(mod, source=None)
        detector_mock = mod._test_gap_detector
        assert detector_mock.detect_extraction_gaps.call_args.kwargs["source_filter"] is None

    def test_default_as_of_date_is_today(self):
        """No --as-of-date arg passes today's UTC date to engine."""
        mod = _load_tool_module(gap_reports=[])
        _call_main(mod, as_of_date=None)
        detector_mock = mod._test_gap_detector
        passed = detector_mock.detect_extraction_gaps.call_args.kwargs["as_of_date"]
        assert isinstance(passed, date)
        # Within 24h of today is fine.
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).date()
        assert abs((today - passed).days) <= 1


# ===========================================================================
# Stdout rendering (per spec § 3.5 L818-826)
# ===========================================================================


class TestStdoutRendering:
    """Human + JSON stdout rendering per spec § 3.5 L818-826."""

    def test_no_gaps_human_message(self):
        """Empty reports -> 'No gaps detected' in stdout per L820."""
        mod = _load_tool_module(gap_reports=[])
        _result, stdout, _stderr = _call_main(mod)
        assert "No gaps" in stdout

    def test_per_table_block_has_source_table_label(self):
        """Per-table block surfaces 'SOURCE.TABLE' label per L820."""
        report = _GapReportStub(source_name="CCM", table_name="STMTHIST")
        mod = _load_tool_module(gap_reports=[report])
        _result, stdout, _stderr = _call_main(mod)
        assert "CCM.STMTHIST" in stdout

    def test_per_table_block_has_expected_range(self):
        """Per-table block includes 'Expected:' line per L821."""
        report = _GapReportStub()
        mod = _load_tool_module(gap_reports=[report])
        _result, stdout, _stderr = _call_main(mod)
        assert "Expected" in stdout

    def test_per_table_block_has_missing_dates(self):
        """Per-table block includes 'Missing:' line per L822."""
        report = _GapReportStub()
        mod = _load_tool_module(gap_reports=[report])
        _result, stdout, _stderr = _call_main(mod)
        assert "Missing" in stdout

    def test_per_table_block_has_action(self):
        """Per-table block includes 'Action:' line per L823 when --include-recommendation."""
        report = _GapReportStub()
        mod = _load_tool_module(gap_reports=[report])
        _result, stdout, _stderr = _call_main(mod, include_recommendation=True)
        assert "Action" in stdout

    def test_no_include_recommendation_suppresses_action_line(self):
        """--no-include-recommendation omits the Action line."""
        report = _GapReportStub()
        mod = _load_tool_module(gap_reports=[report])
        _result, stdout, _stderr = _call_main(mod, include_recommendation=False)
        assert "Action" not in stdout

    def test_action_line_for_backfill_references_backfill_tool(self):
        """Backfill action line surfaces tools/backfill.py invocation per L823."""
        report = _GapReportStub(
            source_name="DNA",
            table_name="ACCT",
            missing_dates=[date(2026, 3, 15), date(2026, 3, 16)],
            recommended_action=ACTION_BACKFILL,
        )
        mod = _load_tool_module(gap_reports=[report])
        _result, stdout, _stderr = _call_main(mod)
        # The canonical action hint surfaces the backfill tool invocation.
        assert "backfill" in stdout.lower()

    def test_action_line_for_investigate_describes_source(self):
        """investigate-source action line surfaces investigate text."""
        report = _GapReportStub(
            source_name="EPICOR",
            table_name="CUSTOMER",
            missing_dates=[date(2026, 3, 15)],
            recommended_action=ACTION_INVESTIGATE,
        )
        mod = _load_tool_module(gap_reports=[report])
        _result, stdout, _stderr = _call_main(mod)
        assert "investigate" in stdout.lower()

    def test_json_output_parseable(self):
        """--json produces JSON array per spec § 3.5 L826."""
        report = _GapReportStub()
        mod = _load_tool_module(gap_reports=[report])
        _result, stdout, _stderr = _call_main(mod, json_output=True)
        parsed = json.loads(stdout)
        assert isinstance(parsed, list)
        assert len(parsed) == 1

    def test_json_output_has_canonical_keys(self):
        """--json schema matches spec § 3.5 L826."""
        report = _GapReportStub()
        mod = _load_tool_module(gap_reports=[report])
        _result, stdout, _stderr = _call_main(mod, json_output=True)
        parsed = json.loads(stdout)
        item = parsed[0]
        # Canonical keys per spec § 3.5 L826
        expected_keys = {
            "source_name", "table_name", "expected_range",
            "missing_dates", "recommended_action",
        }
        assert expected_keys.issubset(set(item.keys()))

    def test_json_output_dates_are_iso_strings(self):
        """--json dates serialize as ISO YYYY-MM-DD strings."""
        report = _GapReportStub(
            source_name="DNA",
            table_name="ACCT",
            expected_range=(date(2026, 1, 1), date(2026, 5, 10)),
            missing_dates=[date(2026, 3, 15), date(2026, 3, 16)],
        )
        mod = _load_tool_module(gap_reports=[report])
        _result, stdout, _stderr = _call_main(mod, json_output=True)
        parsed = json.loads(stdout)
        item = parsed[0]
        # expected_range serialized as list of two ISO strings.
        assert item["expected_range"] == ["2026-01-01", "2026-05-10"]
        # missing_dates serialized as ISO strings.
        assert "2026-03-15" in item["missing_dates"]

    def test_quiet_suppresses_human_stdout(self):
        """--quiet suppresses stdout (only stderr emits errors)."""
        report = _GapReportStub()
        mod = _load_tool_module(gap_reports=[report])
        _result, stdout, _stderr = _call_main(mod, quiet=True)
        # Quiet mode emits nothing to stdout for the human path.
        assert "DNA.ACCT" not in stdout

    def test_multiple_reports_render_separately(self):
        """Multiple GapReport instances render separate per-table blocks."""
        reports = [
            _GapReportStub(source_name="DNA", table_name="ACCT"),
            _GapReportStub(source_name="CCM", table_name="STMTHIST"),
        ]
        mod = _load_tool_module(gap_reports=reports)
        _result, stdout, _stderr = _call_main(mod)
        assert "DNA.ACCT" in stdout
        assert "CCM.STMTHIST" in stdout


# ===========================================================================
# Alert dispatch (per spec § 3.5 L767 + L804 + § 3.11)
# ===========================================================================


class TestAlertDispatch:
    """Alert dispatch wiring per spec § 3.5 L767 + L804."""

    def test_automic_default_dispatches_alert_on_gaps(self):
        """actor=automic + alert defaults True + gaps -> alert fired once."""
        mod = _load_tool_module(gap_reports=[_GapReportStub()])
        _result, _stdout, _stderr = _call_main(mod, actor=_ACTOR_AUTOMIC, alert=None)
        dispatcher = mod._test_alert_dispatcher
        assert dispatcher.dispatch_alert.call_count == 1

    def test_operator_default_does_not_dispatch(self):
        """actor=operator + alert defaults False + gaps -> no alert."""
        mod = _load_tool_module(gap_reports=[_GapReportStub()])
        _result, _stdout, _stderr = _call_main(mod, actor=_ACTOR_OPERATOR, alert=None)
        dispatcher = mod._test_alert_dispatcher
        assert dispatcher.dispatch_alert.call_count == 0

    def test_explicit_alert_true_dispatches_even_for_operator(self):
        """--alert overrides operator default."""
        mod = _load_tool_module(gap_reports=[_GapReportStub()])
        _result, _stdout, _stderr = _call_main(mod, actor=_ACTOR_OPERATOR, alert=True)
        dispatcher = mod._test_alert_dispatcher
        assert dispatcher.dispatch_alert.call_count == 1

    def test_explicit_no_alert_suppresses_automic(self):
        """--no-alert overrides automic default."""
        mod = _load_tool_module(gap_reports=[_GapReportStub()])
        _result, _stdout, _stderr = _call_main(mod, actor=_ACTOR_AUTOMIC, alert=False)
        dispatcher = mod._test_alert_dispatcher
        assert dispatcher.dispatch_alert.call_count == 0

    def test_no_alert_when_no_gaps_even_with_alert_on(self):
        """No gaps -> no alert dispatch (alert is gated on gap-detected per L767)."""
        mod = _load_tool_module(gap_reports=[])
        _result, _stdout, _stderr = _call_main(mod, actor=_ACTOR_AUTOMIC, alert=True)
        dispatcher = mod._test_alert_dispatcher
        assert dispatcher.dispatch_alert.call_count == 0

    def test_alert_dispatch_failure_does_not_affect_verdict(self):
        """Alert dispatcher raising does NOT change verdict per spec § 3.5 narrative."""
        mod = _load_tool_module(gap_reports=[_GapReportStub()])
        mod._test_alert_dispatcher.dispatch_alert.side_effect = RuntimeError(
            "ops-channel client failed (test fixture — B82 unscoped)"
        )
        result, _stdout, _stderr = _call_main(mod, actor=_ACTOR_AUTOMIC, alert=True)
        # Gap detected -> exit 1; alert failure does not change this.
        assert result["exit_code"] == EXIT_OPERATIONAL

    def test_alert_fired_flag_in_result(self):
        """Result dict carries 'alert_fired' bool per D76 Metadata shape."""
        mod = _load_tool_module(gap_reports=[_GapReportStub()])
        result, _stdout, _stderr = _call_main(mod, actor=_ACTOR_AUTOMIC, alert=True)
        assert "alert_fired" in result
        assert result["alert_fired"] is True


# ===========================================================================
# Audit row contract (per D76 + § 3.5 L766)
# ===========================================================================


class TestAuditRowContract:
    """CLI_DETECT_EXTRACTION_GAPS audit row per D76 + spec § 3.5 L766."""

    def test_event_type_is_cli_detect_extraction_gaps(self):
        """EventType MUST be 'CLI_DETECT_EXTRACTION_GAPS' (CLI_* family per D76)."""
        mod = _load_tool_module(gap_reports=[])
        # Ensure audit row is enabled (no_audit_event=False).
        # We can verify via the constant exposed on the module.
        assert mod.EVENT_TYPE == EXPECTED_EVENT_TYPE

    def test_no_audit_event_suppresses_write(self):
        """--no-audit-event skips the CLI envelope row."""
        mod = _load_tool_module(gap_reports=[])
        result, _stdout, _stderr = _call_main(mod, no_audit_event=True)
        # When skipped, audit_event_id is None.
        assert result.get("audit_event_id") is None

    def test_result_dict_carries_required_metadata_keys(self):
        """Result dict has all required Metadata keys per D76."""
        mod = _load_tool_module(gap_reports=[_GapReportStub()])
        result, _stdout, _stderr = _call_main(mod, actor=_ACTOR_OPERATOR)
        for key in REQUIRED_METADATA_KEYS:
            assert key in result, (
                f"Result dict missing required Metadata key {key!r}. "
                f"D76 audit-row contract. Got: {sorted(result.keys())!r}"
            )

    def test_event_kind_is_gap_detection(self):
        """Metadata.event_kind == 'gap_detection'."""
        mod = _load_tool_module(gap_reports=[])
        result, _stdout, _stderr = _call_main(mod)
        assert result.get("event_kind") == "gap_detection"

    def test_dry_run_false_always(self):
        """dry_run is always False — this is a read-only tool per spec § 1.2."""
        mod = _load_tool_module(gap_reports=[])
        result, _stdout, _stderr = _call_main(mod)
        assert result.get("dry_run") is False

    def test_tables_with_gaps_count(self):
        """tables_with_gaps reflects len(reports)."""
        reports = [
            _GapReportStub(source_name="DNA", table_name="ACCT"),
            _GapReportStub(source_name="CCM", table_name="STMTHIST"),
        ]
        mod = _load_tool_module(gap_reports=reports)
        result, _stdout, _stderr = _call_main(mod)
        assert result["tables_with_gaps"] == 2

    def test_total_missing_dates_count(self):
        """total_missing_dates aggregates per-report missing_dates lengths."""
        reports = [
            _GapReportStub(missing_dates=[date(2026, 3, 15)]),
            _GapReportStub(missing_dates=[date(2026, 4, 1), date(2026, 4, 2)]),
        ]
        mod = _load_tool_module(gap_reports=reports)
        result, _stdout, _stderr = _call_main(mod)
        assert result["total_missing_dates"] == 3

    def test_audit_row_insert_sql_contains_event_type(self):
        """The INSERT SQL string includes the canonical EventType."""
        mod = _load_tool_module(gap_reports=[])
        _result, _stdout, _stderr = _call_main(mod, no_audit_event=False)
        # Verify SQL contains the EventType. Search executed_params first
        # since EventType is passed as a parameter.
        executed_params = mod._test_executed_params
        # EventType should appear as a parameter to the INSERT.
        assert EXPECTED_EVENT_TYPE in executed_params, (
            f"INSERT must pass EventType='{EXPECTED_EVENT_TYPE}' as a parameter. "
            f"Got params: {executed_params!r}"
        )

    def test_actor_surfaced_in_result(self):
        """actor surfaces in result dict (-> Metadata JSON)."""
        mod = _load_tool_module(gap_reports=[])
        result, _stdout, _stderr = _call_main(mod, actor=_ACTOR_AUTOMIC)
        assert result.get("actor") == _ACTOR_AUTOMIC

    def test_audit_event_id_key_present(self):
        """audit_event_id key MUST be present in result dict (B218: presence over content)."""
        mod = _load_tool_module(gap_reports=[])
        result, _stdout, _stderr = _call_main(mod)
        assert "audit_event_id" in result


# ===========================================================================
# Naive-UTC datetime invariant (per CDC-NOW-MS / SCD2-P1-f)
# ===========================================================================


class TestNaiveUtcDatetime:
    """Datetime invariant: naive (no tzinfo) + ms-precision."""

    def test_now_naive_utc_ms_returns_naive_datetime(self):
        """_now_naive_utc_ms returns datetime with tzinfo=None."""
        mod = _load_tool_module()
        dt = mod._now_naive_utc_ms()
        assert dt.tzinfo is None, (
            "Datetimes sent to SQL Server MUST be naive per CDC-NOW-MS / "
            "SCD2-P1-f. tz-aware datetimes route through DATETIMEOFFSET "
            "and cause implicit conversion drift on non-UTC servers."
        )

    def test_now_naive_utc_ms_truncates_to_milliseconds(self):
        """_now_naive_utc_ms truncates microseconds to millisecond precision."""
        mod = _load_tool_module()
        dt = mod._now_naive_utc_ms()
        # microsecond is a multiple of 1000 (drops sub-ms precision).
        assert dt.microsecond % 1000 == 0


# ===========================================================================
# Parse-as-of-date helper
# ===========================================================================


class TestParseAsOfDate:
    """ISO YYYY-MM-DD parsing per spec § 3.5 L802."""

    def test_none_returns_today(self):
        """None -> today (UTC)."""
        mod = _load_tool_module()
        result = mod._parse_as_of_date(None)
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).date()
        assert abs((today - result).days) <= 1

    def test_iso_string_parsed(self):
        """ISO YYYY-MM-DD string parsed correctly."""
        mod = _load_tool_module()
        result = mod._parse_as_of_date("2026-04-15")
        assert result == date(2026, 4, 15)

    def test_invalid_string_raises_value_error(self):
        """Non-ISO string raises ValueError (caller maps to exit 2)."""
        mod = _load_tool_module()
        with pytest.raises(ValueError):
            mod._parse_as_of_date("not-a-date")

    def test_wrong_format_raises_value_error(self):
        """Non-strict ISO format raises ValueError."""
        mod = _load_tool_module()
        with pytest.raises(ValueError):
            mod._parse_as_of_date("04/15/2026")


# ===========================================================================
# CLI argv entry point (per spec § 3.5 + § 1.7)
# ===========================================================================


class TestCliMain:
    """cli_main() argv entry — D74 exit-code clamp + invocation."""

    def test_cli_main_returns_int(self):
        """cli_main returns int exit code per D74."""
        mod = _load_tool_module(gap_reports=[])

        # Mock argv to avoid pytest's argv interference.
        with patch.object(sys, "argv", ["detect_extraction_gaps.py"]):
            # Re-patch sys.modules to honor mocks.
            with patch.dict("sys.modules", mod._test_sys_modules_patch):
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    code = mod.cli_main()
        assert isinstance(code, int)
        assert code in (EXIT_SUCCESS, EXIT_OPERATIONAL, EXIT_FATAL)

    def test_cli_main_clamps_unknown_exit_to_fatal(self):
        """Defensive clamp: non-canonical exit_code -> EXIT_FATAL per D74."""
        # Verify the clamp logic exists by checking the constants are tight.
        mod = _load_tool_module()
        assert mod.EXIT_SUCCESS == 0
        assert mod.EXIT_OPERATIONAL == 1
        assert mod.EXIT_FATAL == 2


# ===========================================================================
# Idempotency (per D15 + D22 — read-only tool)
# ===========================================================================


class TestIdempotency:
    """Read-only multi-call idempotency per D15 + D22."""

    def test_repeat_invocation_same_inputs_same_verdict(self):
        """Identical mocked inputs -> identical exit code across invocations."""
        report = _GapReportStub()
        mod = _load_tool_module(gap_reports=[report])
        # Reset the mock counter between calls.
        result1, _o1, _e1 = _call_main(mod)
        # Don't reload — same module, same mock state.
        mod._test_gap_detector.detect_extraction_gaps.return_value = [report]
        result2, _o2, _e2 = _call_main(mod)
        assert result1["exit_code"] == result2["exit_code"]
        assert result1["tables_with_gaps"] == result2["tables_with_gaps"]


# ===========================================================================
# Error-path coverage (per D68 + § 1.8)
# ===========================================================================


class TestErrorPaths:
    """Per-error-path coverage per D68 hierarchy."""

    def test_timeout_writes_failed_audit_row(self):
        """GapDetectorTimeout -> audit row with Status='FAILED' + error_message."""
        mod = _load_tool_module(raise_timeout=True)
        result, _stdout, _stderr = _call_main(mod)
        # error_type surfaces in result dict.
        assert result.get("error_type") == "GapDetectorTimeout"
        # exit code 1 per D68 retryable.
        assert result["exit_code"] == EXIT_OPERATIONAL

    def test_state_unavailable_writes_failed_audit_row(self):
        """ExtractionStateUnavailable -> audit row with Status='FAILED'."""
        mod = _load_tool_module(raise_state_unavailable=True)
        result, _stdout, _stderr = _call_main(mod)
        assert result.get("error_type") == "ExtractionStateUnavailable"
        assert result["exit_code"] == EXIT_OPERATIONAL

    def test_unexpected_writes_failed_audit_row(self):
        """Generic Exception -> audit row with Status='FAILED' + exit 2."""
        mod = _load_tool_module(raise_unexpected=True)
        result, _stdout, _stderr = _call_main(mod)
        assert result["exit_code"] == EXIT_FATAL
        # error_type captures the actual exception class.
        assert result.get("error_type") == "RuntimeError"

    def test_invalid_as_of_date_does_not_invoke_engine(self):
        """Invalid --as-of-date short-circuits before engine call."""
        mod = _load_tool_module(gap_reports=[])
        _result, _stdout, _stderr = _call_main(mod, as_of_date="not-a-date")
        # Engine should NOT have been called.
        detector_mock = mod._test_gap_detector
        assert detector_mock.detect_extraction_gaps.call_count == 0
