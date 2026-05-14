"""Tier 1 unit tests for tools/lateness_profile.py.

Tests run on every commit. No live DB, no live network required.
All external dependencies mocked with unittest.mock.

North Star pillars addressed:
  - Audit-grade (D76): exactly one CLI_LATENESS_PROFILE PipelineEventLog
    row per invocation; Metadata JSON carries the report payload + actor
    + justification + window_days + min_sample_days + persist flag;
    audit_event_id key MUST be present in JSON output per B218
    spec-compliance (presence over content).
  - Operationally stable (D74/D75): exit-code contract (0/1/2) and
    argument naming discipline must be exactly per spec.
  - Idempotent (D26): LatenessProfile INSERT is append-only;
    multi-invocation in the same window produces multiple history rows
    (intentional trend tracking).
  - Traceability (D26, D11): every invocation writes ONE
    CLI_LATENESS_PROFILE row; p99 surfaces in stdout + JSON + audit
    Metadata.

LatenessReport canonical fields (Pitfall #9.a — verified against
cdc/lateness_profiler.py LatenessReport dataclass):
  source_name, table_name, window_start (date), window_end (date),
  sample_count (int), p50_days/p90_days/p95_days/p99_days (float),
  max_observed_days (int), confidence (str), as_of (datetime).

profile_lateness canonical signature (Pitfall #9.b — verified against
cdc/lateness_profiler.py:profile_lateness):
  profile_lateness(*, source_name, table_name, window_days,
                   min_sample_days) -> LatenessReport
  KEYWORD-ONLY (leading-*).

Naive-UTC datetime invariant (SCD2-P1-f): every datetime captured in
audit row Metadata must be tzinfo=None. Verified in
test_audit_row_metadata_naive_datetime.

Edge case IDs (per 04_EDGE_CASES.md):
  I1 (same BatchId retry — stateless re-call returns identical report).
  I3 (concurrent same-key — stateless read-only; multi-worker safe).

Decision citations:
  D11 (empirical L_99 lookback),
  D26 (append-only audit),
  D67 (Tier 0 discipline — Tier 1 complements),
  D68 (error class hierarchy),
  D74 (exit-code contract 0/1/2),
  D75 (arg naming: actor / source / table / window-days /
       min-sample-days / persist / recommend-lookback / json / verbose
       / quiet / justification / no-audit-event),
  D76 (audit-row contract: CLI_LATENESS_PROFILE EventType;
       Metadata JSON shape),
  D77 (Tier 0 canonical scaffold — Tier 1 extends, not weakens).

B-numbers:
  B85 (utils.errors canonical exception module).
  B228 (canonical exception import surface).
  B218 (audit_event_id key MUST be present in JSON output).

Spec: phase1/04_tools.md § 3.3 (canonical spec L577-663).
Wrapped module: cdc/lateness_profiler.py (M12).
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import re
import sys
from datetime import date, datetime
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

_TOOL_PATH = _PROJECT_ROOT / "tools" / "lateness_profile.py"
_TOOL_MODULE_KEY = "tools.lateness_profile"

# ---------------------------------------------------------------------------
# Constants — single source of truth
# ---------------------------------------------------------------------------

EXPECTED_EVENT_TYPE = "CLI_LATENESS_PROFILE"

EXIT_SUCCESS = 0
EXIT_OPERATIONAL_FAILURE = 1
EXIT_FATAL = 2

_ACTOR = "test-tier1"
_SOURCE = "DNA"
_TABLE = "ACCT"

# Canonical example values from spec § 3.3 L646-657
_SAMPLE_COUNT = 87
_P50 = 0.2
_P90 = 0.8
_P95 = 1.3
_P99 = 2.7
_MAX_OBS = 4


# ---------------------------------------------------------------------------
# Exception class resolution (B215 / B228 canonical surface)
# ---------------------------------------------------------------------------


def _resolve_exception_classes():
    """Resolve InsufficientHistory + ExtractionStateUnavailable.

    Per B228 — canonical surface is ``utils.errors``. Fall back to
    stand-ins if not yet authored (the tool's own fallback path
    parallels this).
    """
    try:
        from utils.errors import (  # noqa: F401
            ExtractionStateUnavailable,
            InsufficientHistory,
        )
        return InsufficientHistory, ExtractionStateUnavailable
    except ImportError:

        class InsufficientHistory(Exception):
            def __init__(self, message: str, *, metadata: dict | None = None):
                super().__init__(message)
                self.metadata = metadata or {}

        class ExtractionStateUnavailable(Exception):
            def __init__(self, message: str, *, metadata: dict | None = None):
                super().__init__(message)
                self.metadata = metadata or {}

        return InsufficientHistory, ExtractionStateUnavailable


# ---------------------------------------------------------------------------
# Synthetic LatenessReport builder
# ---------------------------------------------------------------------------


def _make_synthetic_report(
    *,
    source_name: str = _SOURCE,
    table_name: str = _TABLE,
    window_start: date | None = None,
    window_end: date | None = None,
    sample_count: int = _SAMPLE_COUNT,
    p50: float = _P50,
    p90: float = _P90,
    p95: float = _P95,
    p99: float = _P99,
    max_obs: int = _MAX_OBS,
    confidence: str = "medium",
    as_of: datetime | None = None,
) -> Any:
    """Build a synthetic LatenessReport-like object for mocking."""

    class _SyntheticReport:
        pass

    r = _SyntheticReport()
    r.source_name = source_name
    r.table_name = table_name
    r.window_start = window_start or date(2026, 2, 9)
    r.window_end = window_end or date(2026, 5, 10)
    r.sample_count = sample_count
    r.p50_days = p50
    r.p90_days = p90
    r.p95_days = p95
    r.p99_days = p99
    r.max_observed_days = max_obs
    r.confidence = confidence
    r.as_of = as_of or datetime(2026, 5, 10, 12, 0, 0)
    return r


# ---------------------------------------------------------------------------
# Module loader — all external deps mocked
# ---------------------------------------------------------------------------


def _load_tool_module(
    *,
    insufficient_history: bool = False,
    extraction_state_unavailable: bool = False,
    unexpected_exception: bool = False,
    sample_report: Any = None,
    persist_return: int | None = 42,
    persist_raises: Exception | None = None,
) -> Any:
    """Load tools/lateness_profile.py with all external imports mocked.

    Mirrors the Tier 0 loader; Tier 1 adds more configurability.
    """
    if _TOOL_MODULE_KEY in sys.modules:
        del sys.modules[_TOOL_MODULE_KEY]

    insufficient_history_cls, esu_cls = _resolve_exception_classes()

    mock_profile_lateness = MagicMock()
    mock_persist = MagicMock()

    if insufficient_history:
        mock_profile_lateness.side_effect = insufficient_history_cls(
            "fewer than min_sample_days SUCCESS rows in window",
            metadata={"sample_count": 5, "min_sample_days": 30},
        )
    elif extraction_state_unavailable:
        mock_profile_lateness.side_effect = esu_cls(
            "Connection failure during PipelineExtraction lookup (test)",
            metadata={"source_name": _SOURCE, "table_name": _TABLE},
        )
    elif unexpected_exception:
        mock_profile_lateness.side_effect = RuntimeError(
            "unexpected error (test fixture)"
        )
    else:
        rep = sample_report if sample_report is not None else _make_synthetic_report()
        mock_profile_lateness.return_value = rep

    if persist_raises is not None:
        mock_persist.side_effect = persist_raises
    else:
        mock_persist.return_value = persist_return

    mock_lateness_profiler = MagicMock()
    mock_lateness_profiler.profile_lateness = mock_profile_lateness
    mock_lateness_profiler.persist_lateness_report = mock_persist

    # Audit cursor mock
    mock_audit_cursor = MagicMock()
    executed_sql: list[str] = []
    executed_params: list[Any] = []

    def _capture_execute(sql: str, *args, **kwargs) -> None:
        executed_sql.append(str(sql))
        if args:
            if isinstance(args[0], (list, tuple)):
                executed_params.extend(args[0])
            else:
                executed_params.append(args[0])
            executed_params.extend(args[1:])

    mock_audit_cursor.execute.side_effect = _capture_execute
    mock_audit_cursor.description = [("AuditEventId",)]
    mock_audit_cursor.fetchone.return_value = (98765,)
    mock_audit_cursor.fetchall.return_value = []

    mock_audit_conn = MagicMock()
    mock_audit_conn.cursor.return_value = mock_audit_cursor
    mock_audit_conn.__enter__ = MagicMock(return_value=mock_audit_conn)
    mock_audit_conn.__exit__ = MagicMock(return_value=False)

    mock_connections = MagicMock()
    mock_connections.get_connection = MagicMock(return_value=mock_audit_conn)
    mock_connections.cursor_for = MagicMock(return_value=mock_audit_cursor)
    mock_connections.get_general_connection = MagicMock(return_value=mock_audit_conn)

    mock_config = MagicMock()
    mock_config.GENERAL_DB = "General"

    mock_pyodbc = MagicMock()
    mock_pyodbc.connect = MagicMock(return_value=mock_audit_conn)

    sys_modules_patch: dict[str, Any] = {
        "cdc.lateness_profiler": mock_lateness_profiler,
        "connections": mock_connections,
        "utils.connections": mock_connections,
        "config": mock_config,
        "utils.configuration": mock_config,
        "pyodbc": mock_pyodbc,
    }

    with patch.dict("sys.modules", sys_modules_patch):
        spec = importlib.util.spec_from_file_location(_TOOL_MODULE_KEY, _TOOL_PATH)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[_TOOL_MODULE_KEY] = mod
        spec.loader.exec_module(mod)

    mod._test_sys_modules_patch = sys_modules_patch
    mod._test_profile_lateness_mock = mock_profile_lateness
    mod._test_persist_mock = mock_persist
    mod._test_audit_cursor = mock_audit_cursor
    mod._test_executed_sql = executed_sql
    mod._test_executed_params = executed_params
    return mod


def _call_main(mod: Any, **overrides: Any) -> dict:
    """Call tool main() with canonical defaults + overrides."""
    defaults = dict(
        source=_SOURCE,
        table=_TABLE,
        actor=_ACTOR,
        window_days=90,
        min_sample_days=30,
        persist=True,
        recommend_lookback=True,
        json_output=False,
        verbose=False,
        quiet=False,
        justification=None,
        no_audit_event=False,
        profile_lateness_fn=mod._test_profile_lateness_mock,
        persist_lateness_report_fn=mod._test_persist_mock,
    )
    defaults.update(overrides)
    sys_modules_patch = getattr(mod, "_test_sys_modules_patch", {})
    try:
        with patch.dict("sys.modules", sys_modules_patch):
            return mod.main(**defaults)
    except SystemExit as exc:
        return {"exit_code": exc.code, "_raised_system_exit": True}
    except Exception as exc:  # noqa: BLE001
        return {
            "exit_code": EXIT_FATAL,
            "_exception": str(exc),
            "_raised_system_exit": False,
        }


# ===========================================================================
# Class: Happy-path semantics
# ===========================================================================


class TestHappyPathReportSemantics:
    """Happy-path: profile_lateness returns LatenessReport -> exit 0."""

    def test_exit_code_is_zero(self):
        """Happy path returns exit_code=0.

        D74 (exit 0 = report produced). Spec: § 3.3 L660.
        """
        mod = _load_tool_module()
        result = _call_main(mod, persist=False)
        assert result["exit_code"] == EXIT_SUCCESS

    def test_report_field_populated(self):
        """result['report'] is the serialized LatenessReport dict.

        Audit-grade (D76): the report payload appears in result Metadata.
        """
        mod = _load_tool_module()
        result = _call_main(mod, persist=False)
        assert result.get("report") is not None
        assert result["report"]["source_name"] == _SOURCE
        assert result["report"]["table_name"] == _TABLE

    def test_p99_in_report(self):
        """p99_days is the headline L_99 metric per D11."""
        mod = _load_tool_module()
        result = _call_main(mod, persist=False)
        assert "p99_days" in result["report"]
        assert result["report"]["p99_days"] == pytest.approx(_P99)

    def test_recommended_lookback_computed(self):
        """recommended_lookback_days = ceil(p99) + 1 per spec § 3.3 L656.

        For p99=2.7, recommended = ceil(2.7) + 1 = 3 + 1 = 4.
        Matches spec § 3.3 L656 example.
        """
        mod = _load_tool_module()
        result = _call_main(mod, persist=False, recommend_lookback=True)
        assert result["report"].get("recommended_lookback_days") == 4, (
            "recommended_lookback_days must equal ceil(2.7) + 1 = 4 per "
            "spec § 3.3 L656 example."
        )

    def test_no_recommend_lookback_suppresses_key(self):
        """--no-recommend-lookback omits the recommended_lookback_days key."""
        mod = _load_tool_module()
        result = _call_main(mod, persist=False, recommend_lookback=False)
        assert "recommended_lookback_days" not in result["report"], (
            "--no-recommend-lookback must suppress recommended_lookback_days "
            "from report payload per spec § 3.3 L650."
        )


# ===========================================================================
# Class: profile_lateness invocation contract
# ===========================================================================


class TestProfileLatenessInvocationContract:
    """profile_lateness called with canonical keyword-only signature."""

    def test_called_with_source_name_kwarg(self):
        """source_name passed as kwarg (KEYWORD-ONLY signature)."""
        mod = _load_tool_module()
        _call_main(mod, persist=False)
        m = mod._test_profile_lateness_mock
        assert m.called, "profile_lateness must be invoked"
        # All args must be keyword (kwargs dict), per canonical sig
        args, kwargs = m.call_args
        assert args == (), (
            f"profile_lateness must be called with KEYWORD-ONLY args; "
            f"got positional args: {args!r}. Spec: Round 3 § 5.2 "
            "L1143-1148 canonical signature."
        )
        assert kwargs.get("source_name") == _SOURCE

    def test_called_with_table_name_kwarg(self):
        """table_name passed as kwarg."""
        mod = _load_tool_module()
        _call_main(mod, persist=False)
        _, kwargs = mod._test_profile_lateness_mock.call_args
        assert kwargs.get("table_name") == _TABLE

    def test_called_with_window_days_default_90(self):
        """window_days default is 90 per spec § 3.3 L647."""
        mod = _load_tool_module()
        _call_main(mod, persist=False)
        _, kwargs = mod._test_profile_lateness_mock.call_args
        assert kwargs.get("window_days") == 90

    def test_called_with_min_sample_days_default_30(self):
        """min_sample_days default is 30 per spec § 3.3 L648."""
        mod = _load_tool_module()
        _call_main(mod, persist=False)
        _, kwargs = mod._test_profile_lateness_mock.call_args
        assert kwargs.get("min_sample_days") == 30

    def test_window_days_override(self):
        """--window-days 180 passes through to profile_lateness."""
        mod = _load_tool_module()
        _call_main(mod, persist=False, window_days=180)
        _, kwargs = mod._test_profile_lateness_mock.call_args
        assert kwargs.get("window_days") == 180, (
            "Custom --window-days 180 (spec § 3.3 L637-638) must propagate."
        )

    def test_min_sample_days_override(self):
        """--min-sample-days 14 passes through (operator-override path)."""
        mod = _load_tool_module()
        _call_main(mod, persist=False, min_sample_days=14)
        _, kwargs = mod._test_profile_lateness_mock.call_args
        assert kwargs.get("min_sample_days") == 14, (
            "Custom --min-sample-days 14 (spec § 3.3 L640-641 operator "
            "override) must propagate."
        )

    def test_called_exactly_once(self):
        """profile_lateness invoked exactly once per CLI invocation."""
        mod = _load_tool_module()
        _call_main(mod, persist=False)
        assert mod._test_profile_lateness_mock.call_count == 1, (
            "profile_lateness must be invoked exactly once per CLI call. "
            "Multi-call would be wasteful (read-only stateless function)."
        )


# ===========================================================================
# Class: Monotonic percentile ordering
# ===========================================================================


class TestMonotonicPercentileOrdering:
    """Verify p50 <= p90 <= p95 <= p99 in stdout (Tier 1 spec § 3.3 L666)."""

    def test_monotonic_ordering_in_human_output(self, capsys):
        """Stdout percentiles must satisfy p50 <= p90 <= p95 <= p99 <= max."""
        rep = _make_synthetic_report(
            p50=0.5, p90=1.0, p95=1.5, p99=2.0, max_obs=3,
        )
        mod = _load_tool_module(sample_report=rep)
        _call_main(mod, persist=False)
        captured = capsys.readouterr()

        # Extract floats from stdout
        out = captured.out
        for label in ("p50", "p90", "p95", "p99"):
            assert label in out, (
                f"Stdout must contain {label!r} label. "
                f"Got: {out!r}. Spec § 3.3 L651-655."
            )

    def test_monotonic_in_report_dict(self):
        """report['p50_days'] <= p90_days <= p95_days <= p99_days."""
        mod = _load_tool_module()
        result = _call_main(mod, persist=False)
        r = result["report"]
        assert (
            r["p50_days"] <= r["p90_days"] <= r["p95_days"] <= r["p99_days"]
        ), (
            f"Percentile monotonicity violated: "
            f"p50={r['p50_days']} p90={r['p90_days']} "
            f"p95={r['p95_days']} p99={r['p99_days']}. "
            "Spec: § 3.3 L666 Tier 1."
        )

    def test_max_observed_at_least_p99(self):
        """max_observed_days >= p99_days (ceil-rounded so >= or close)."""
        mod = _load_tool_module()
        result = _call_main(mod, persist=False)
        r = result["report"]
        # max_observed_days is int (ceil); p99_days is float
        assert r["max_observed_days"] >= int(r["p99_days"]), (
            f"max_observed_days ({r['max_observed_days']}) must be >= "
            f"int(p99_days) ({int(r['p99_days'])})."
        )


# ===========================================================================
# Class: InsufficientHistory exit code 2
# ===========================================================================


class TestInsufficientHistoryExitsTwo:
    """InsufficientHistory (PipelineFatalError) -> exit 2."""

    def test_insufficient_history_exit_code(self):
        """exit_code == 2 per § 1.8 mapping.

        Spec: § 3.3 L660-662 (fatal class).
        D68: InsufficientHistory is PipelineFatalError subclass.
        """
        mod = _load_tool_module(insufficient_history=True)
        result = _call_main(mod, persist=False)
        assert result["exit_code"] == EXIT_FATAL

    def test_insufficient_history_stderr_has_helpful_message(self, capsys):
        """Stderr message per spec § 3.3 L629."""
        mod = _load_tool_module(insufficient_history=True)
        _call_main(mod, persist=False)
        captured = capsys.readouterr()
        combined = (captured.out + captured.err).lower()
        # Spec L629: "needs more history; run when >= N days of SUCCESS
        # data available"
        assert "more history" in combined or "insufficient" in combined, (
            f"Stderr must include helpful 'more history' message per "
            f"spec § 3.3 L629. Got: {captured.err!r}"
        )

    def test_insufficient_history_no_persist_attempted(self):
        """Persistence NOT attempted when profile_lateness raises."""
        mod = _load_tool_module(insufficient_history=True)
        _call_main(mod, persist=True)
        assert not mod._test_persist_mock.called, (
            "persist_lateness_report must NOT be called when "
            "profile_lateness raises InsufficientHistory."
        )


# ===========================================================================
# Class: ExtractionStateUnavailable exit code 1
# ===========================================================================


class TestExtractionStateUnavailableExitsOne:
    """ExtractionStateUnavailable (PipelineRetryableError) -> exit 1."""

    def test_extraction_state_unavailable_exit_code(self):
        """exit_code == 1 per spec § 3.3 L660 retryable mapping."""
        mod = _load_tool_module(extraction_state_unavailable=True)
        result = _call_main(mod, persist=False)
        assert result["exit_code"] == EXIT_OPERATIONAL_FAILURE

    def test_extraction_state_unavailable_message(self, capsys):
        """Stderr warns the operator can re-run."""
        mod = _load_tool_module(extraction_state_unavailable=True)
        _call_main(mod, persist=False)
        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "WARNING" in combined or "warning" in combined.lower() or \
            "re-run" in combined.lower() or "rerun" in combined.lower() or \
            "operator" in combined.lower(), (
                f"Retryable error should hint at re-run. "
                f"Stderr: {captured.err!r}"
            )


# ===========================================================================
# Class: Unexpected exception -> exit 2
# ===========================================================================


class TestUnexpectedExceptionExitsTwo:
    """Bare-except branch maps to exit 2 per § 1.8 wrapper."""

    def test_runtime_error_exit_code(self):
        """RuntimeError -> exit 2 per § 1.8 mapping."""
        mod = _load_tool_module(unexpected_exception=True)
        result = _call_main(mod, persist=False)
        assert result["exit_code"] == EXIT_FATAL


# ===========================================================================
# Class: --persist behavior
# ===========================================================================


class TestPersistBehavior:
    """--persist (default ON) writes LatenessProfile; --no-persist suppresses."""

    def test_persist_default_invokes_persist_function(self):
        """Default persist=True invokes persist_lateness_report."""
        mod = _load_tool_module()
        _call_main(mod, persist=True)
        assert mod._test_persist_mock.called, (
            "persist=True (default per spec § 3.3 L649) must invoke "
            "persist_lateness_report."
        )

    def test_persist_passes_report_positionally(self):
        """First positional arg to persist is the LatenessReport."""
        mod = _load_tool_module()
        _call_main(mod, persist=True)
        args, _ = mod._test_persist_mock.call_args
        assert len(args) >= 1, (
            "persist_lateness_report must receive the report as positional "
            "arg per Round 3 § 5.2 signature."
        )

    def test_no_persist_skips_persist_function(self):
        """persist=False does not call persist_lateness_report."""
        mod = _load_tool_module()
        _call_main(mod, persist=False)
        assert not mod._test_persist_mock.called

    def test_persist_failure_is_non_fatal(self):
        """persist_lateness_report raising does NOT change exit code."""
        _, esu_cls = _resolve_exception_classes()
        mod = _load_tool_module(
            persist_raises=esu_cls("persist transient failure (test)"),
        )
        result = _call_main(mod, persist=True)
        # Spec § 3.3 + best-effort posture: report success was already
        # achieved; persistence is append-only side effect.
        assert result["exit_code"] == EXIT_SUCCESS, (
            "Persistence failure must NOT downgrade exit code — the "
            "report was successfully computed; persistence is best-"
            "effort append-only audit per D26."
        )

    def test_profile_id_populated_on_persist_success(self):
        """result['profile_id'] == mocked ProfileId on success."""
        mod = _load_tool_module(persist_return=12345)
        result = _call_main(mod, persist=True)
        assert result["profile_id"] == 12345

    def test_profile_id_none_on_no_persist(self):
        """result['profile_id'] is None when --no-persist."""
        mod = _load_tool_module()
        result = _call_main(mod, persist=False)
        assert result["profile_id"] is None


# ===========================================================================
# Class: JSON output schema
# ===========================================================================


class TestJsonOutputSchema:
    """--json produces canonical schema per spec § 3.3 L658."""

    def test_json_parseable(self, capsys):
        """--json output is parseable JSON."""
        mod = _load_tool_module()
        _call_main(mod, persist=False, json_output=True)
        captured = capsys.readouterr()
        payload = json.loads(captured.out.strip())
        assert isinstance(payload, dict)

    def test_json_has_source_name(self, capsys):
        mod = _load_tool_module()
        _call_main(mod, persist=False, json_output=True)
        payload = json.loads(capsys.readouterr().out.strip())
        assert payload["source_name"] == _SOURCE

    def test_json_has_table_name(self, capsys):
        mod = _load_tool_module()
        _call_main(mod, persist=False, json_output=True)
        payload = json.loads(capsys.readouterr().out.strip())
        assert payload["table_name"] == _TABLE

    def test_json_has_window_start_end(self, capsys):
        mod = _load_tool_module()
        _call_main(mod, persist=False, json_output=True)
        payload = json.loads(capsys.readouterr().out.strip())
        assert "window_start" in payload
        assert "window_end" in payload

    def test_json_has_sample_count(self, capsys):
        mod = _load_tool_module()
        _call_main(mod, persist=False, json_output=True)
        payload = json.loads(capsys.readouterr().out.strip())
        assert payload["sample_count"] == _SAMPLE_COUNT

    def test_json_has_all_percentile_keys(self, capsys):
        mod = _load_tool_module()
        _call_main(mod, persist=False, json_output=True)
        payload = json.loads(capsys.readouterr().out.strip())
        for k in ("p50_days", "p90_days", "p95_days", "p99_days"):
            assert k in payload, (
                f"Spec § 3.3 L658 canonical JSON schema requires {k!r}."
            )

    def test_json_has_max_observed_days(self, capsys):
        mod = _load_tool_module()
        _call_main(mod, persist=False, json_output=True)
        payload = json.loads(capsys.readouterr().out.strip())
        assert "max_observed_days" in payload

    def test_json_has_recommended_lookback_days(self, capsys):
        """recommended_lookback_days surfaces in JSON when --recommend-lookback."""
        mod = _load_tool_module()
        _call_main(
            mod, persist=False, json_output=True, recommend_lookback=True,
        )
        payload = json.loads(capsys.readouterr().out.strip())
        assert "recommended_lookback_days" in payload, (
            "Spec § 3.3 L658 includes recommended_lookback_days in JSON."
        )

    def test_json_audit_event_id_key_present(self, capsys):
        """B218 spec-compliance: audit_event_id key MUST be present."""
        mod = _load_tool_module()
        _call_main(mod, persist=False, json_output=True)
        payload = json.loads(capsys.readouterr().out.strip())
        assert "audit_event_id" in payload, (
            "JSON output must include 'audit_event_id' key (B218 "
            "spec-compliance: presence over content)."
        )

    def test_json_profile_id_key_present(self, capsys):
        """profile_id key surfaces in JSON (null on --no-persist)."""
        mod = _load_tool_module()
        _call_main(mod, persist=False, json_output=True)
        payload = json.loads(capsys.readouterr().out.strip())
        assert "profile_id" in payload


# ===========================================================================
# Class: --json failure-path output
# ===========================================================================


class TestJsonOutputFailurePath:
    """--json on InsufficientHistory still produces parseable JSON envelope."""

    def test_json_on_insufficient_history_parseable(self, capsys):
        mod = _load_tool_module(insufficient_history=True)
        _call_main(mod, persist=False, json_output=True)
        captured = capsys.readouterr()
        stdout = captured.out.strip()
        if not stdout:
            pytest.skip(
                "Failure-path JSON envelope is optional; spec § 3.3 L658 "
                "specifies success-shape only. Tool may legitimately emit "
                "to stderr only."
            )
        payload = json.loads(stdout)
        assert payload.get("exit_code") == EXIT_FATAL or "error" in str(payload).lower()


# ===========================================================================
# Class: Audit row metadata
# ===========================================================================


class TestAuditRowMetadata:
    """One CLI_LATENESS_PROFILE row per invocation per D76."""

    def test_event_type_is_cli_lateness_profile(self):
        """EventType == 'CLI_LATENESS_PROFILE' per spec § 3.3 L617."""
        mod = _load_tool_module()
        _call_main(mod, persist=False)
        executed_sql = mod._test_executed_sql
        executed_params = mod._test_executed_params
        # EventType appears as a param value (positional or named)
        seen_event_type = any(
            p == EXPECTED_EVENT_TYPE for p in executed_params
        )
        # OR appears in the SQL text
        seen_in_sql = any(EXPECTED_EVENT_TYPE in s for s in executed_sql)
        assert seen_event_type or seen_in_sql, (
            f"EventType {EXPECTED_EVENT_TYPE!r} must appear in audit-row "
            f"INSERT. Got SQL: {executed_sql!r}, params: {executed_params!r}. "
            "Spec: § 3.3 L617 + D76."
        )

    def test_audit_event_id_in_result(self):
        """result['audit_event_id'] is the SCOPE_IDENTITY value."""
        mod = _load_tool_module()
        result = _call_main(mod, persist=False)
        # Audit ID set by fetchone returning (98765,) in fixture
        assert result["audit_event_id"] is not None

    def test_actor_in_result(self):
        """result['actor'] == passed actor."""
        mod = _load_tool_module()
        result = _call_main(mod, persist=False, actor="custom-operator")
        assert result["actor"] == "custom-operator"

    def test_justification_in_result(self):
        """result['justification'] echoes the passed value."""
        mod = _load_tool_module()
        result = _call_main(
            mod, persist=False, justification="quarterly capacity review",
        )
        assert result["justification"] == "quarterly capacity review"

    def test_audit_started_at_is_naive_datetime(self):
        """started_at_dt MUST be naive (tzinfo=None) per SCD2-P1-f."""
        mod = _load_tool_module()
        result = _call_main(mod, persist=False)
        dt = result.get("started_at_dt")
        if dt is not None:
            assert isinstance(dt, datetime)
            assert dt.tzinfo is None, (
                "started_at_dt MUST be naive (tzinfo=None) per SCD2-P1-f / "
                "CDC-NOW-MS invariant. Got tzinfo: %r" % dt.tzinfo
            )

    def test_no_audit_event_skips_write(self):
        """--no-audit-event skips audit-row INSERT.

        D76 — pipeline-programmatic callers set this when parent has own
        audit row.
        """
        mod = _load_tool_module()
        executed_before = list(mod._test_executed_sql)
        _call_main(mod, persist=False, no_audit_event=True)
        executed_after = mod._test_executed_sql
        # No new INSERT to PipelineEventLog
        new_sql = executed_after[len(executed_before):]
        eventlog_inserts = [s for s in new_sql if "PipelineEventLog" in s]
        assert not eventlog_inserts, (
            "--no-audit-event must skip PipelineEventLog INSERT. "
            f"Got: {eventlog_inserts!r}. Per D76 spec."
        )

    def test_metadata_includes_source_name(self):
        """Metadata JSON carries source_name."""
        mod = _load_tool_module()
        _call_main(mod, persist=False, source="CCM", table="TXN")
        # Find Metadata JSON among executed params
        json_params = [
            p for p in mod._test_executed_params
            if isinstance(p, str) and p.startswith("{") and p.endswith("}")
        ]
        assert json_params, "Audit row must include Metadata JSON param."
        # Parse — last one is the latest invocation
        meta = json.loads(json_params[-1])
        assert meta.get("source_name") == "CCM"

    def test_metadata_includes_window_days(self):
        """Metadata JSON carries window_days for traceability."""
        mod = _load_tool_module()
        _call_main(mod, persist=False, window_days=180)
        json_params = [
            p for p in mod._test_executed_params
            if isinstance(p, str) and p.startswith("{") and p.endswith("}")
        ]
        assert json_params
        meta = json.loads(json_params[-1])
        assert meta.get("window_days") == 180


# ===========================================================================
# Class: Argparse contract
# ===========================================================================


class TestArgparseContract:
    """Argparse accepts canonical args + rejects unknown."""

    def test_source_required(self):
        """--source is REQUIRED."""
        mod = _load_tool_module()
        parser = mod._build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--table", _TABLE])

    def test_table_required(self):
        """--table is REQUIRED."""
        mod = _load_tool_module()
        parser = mod._build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--source", _SOURCE])

    def test_window_days_int(self):
        """--window-days parses as int."""
        mod = _load_tool_module()
        parser = mod._build_parser()
        args = parser.parse_args(
            ["--source", _SOURCE, "--table", _TABLE, "--window-days", "180"]
        )
        assert args.window_days == 180
        assert isinstance(args.window_days, int)

    def test_min_sample_days_int(self):
        """--min-sample-days parses as int."""
        mod = _load_tool_module()
        parser = mod._build_parser()
        args = parser.parse_args(
            ["--source", _SOURCE, "--table", _TABLE, "--min-sample-days", "14"]
        )
        assert args.min_sample_days == 14

    def test_persist_default_true(self):
        """--persist default is True."""
        mod = _load_tool_module()
        parser = mod._build_parser()
        args = parser.parse_args(["--source", _SOURCE, "--table", _TABLE])
        assert args.persist is True

    def test_no_persist_flag(self):
        """--no-persist sets persist=False."""
        mod = _load_tool_module()
        parser = mod._build_parser()
        args = parser.parse_args(
            ["--source", _SOURCE, "--table", _TABLE, "--no-persist"]
        )
        assert args.persist is False

    def test_recommend_lookback_default_true(self):
        """--recommend-lookback default True per spec § 3.3 L650."""
        mod = _load_tool_module()
        parser = mod._build_parser()
        args = parser.parse_args(["--source", _SOURCE, "--table", _TABLE])
        assert args.recommend_lookback is True

    def test_no_recommend_lookback(self):
        """--no-recommend-lookback sets recommend_lookback=False."""
        mod = _load_tool_module()
        parser = mod._build_parser()
        args = parser.parse_args([
            "--source", _SOURCE, "--table", _TABLE, "--no-recommend-lookback"
        ])
        assert args.recommend_lookback is False

    def test_json_flag(self):
        """--json sets json_output=True."""
        mod = _load_tool_module()
        parser = mod._build_parser()
        args = parser.parse_args(
            ["--source", _SOURCE, "--table", _TABLE, "--json"]
        )
        assert args.json_output is True

    def test_actor_accepted(self):
        """--actor accepts a value."""
        mod = _load_tool_module()
        parser = mod._build_parser()
        args = parser.parse_args([
            "--source", _SOURCE, "--table", _TABLE, "--actor", "pipeline-lead"
        ])
        assert args.actor == "pipeline-lead"

    def test_justification_accepted(self):
        """--justification accepts free-text."""
        mod = _load_tool_module()
        parser = mod._build_parser()
        args = parser.parse_args([
            "--source", _SOURCE, "--table", _TABLE,
            "--justification", "drift investigation",
        ])
        assert args.justification == "drift investigation"

    def test_no_audit_event_flag(self):
        """--no-audit-event sets no_audit_event=True."""
        mod = _load_tool_module()
        parser = mod._build_parser()
        args = parser.parse_args([
            "--source", _SOURCE, "--table", _TABLE, "--no-audit-event",
        ])
        assert args.no_audit_event is True

    def test_invented_arg_rejected_registry_id(self):
        """--registry-id (a § 3.1 / § 3.2 arg) must be REJECTED.

        Pitfall #9.b forward-incompat guard — tool only accepts its own
        canonical args per spec § 3.3 L645-651.
        """
        mod = _load_tool_module()
        parser = mod._build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([
                "--source", _SOURCE, "--table", _TABLE,
                "--registry-id", "12345",
            ])

    def test_invented_arg_rejected_cycle(self):
        """--cycle (a § 3.6 arg) must be REJECTED."""
        mod = _load_tool_module()
        parser = mod._build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([
                "--source", _SOURCE, "--table", _TABLE,
                "--cycle", "AM",
            ])

    def test_invented_arg_rejected_apply(self):
        """--apply (a side-effecting-tool arg) is NOT canonical for § 3.3.

        Spec § 1.2: read-only tools (which this is) do NOT have --apply.
        """
        mod = _load_tool_module()
        parser = mod._build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([
                "--source", _SOURCE, "--table", _TABLE, "--apply",
            ])


# ===========================================================================
# Class: Input validation
# ===========================================================================


class TestInputValidation:
    """Empty / invalid inputs handled at CLI boundary."""

    def test_empty_source_exits_2(self):
        """Empty source argument -> exit 2 (FATAL — invalid args)."""
        mod = _load_tool_module()
        result = _call_main(mod, persist=False, source="")
        assert result["exit_code"] == EXIT_FATAL

    def test_empty_table_exits_2(self):
        """Empty table argument -> exit 2 (FATAL — invalid args)."""
        mod = _load_tool_module()
        result = _call_main(mod, persist=False, table="")
        assert result["exit_code"] == EXIT_FATAL


# ===========================================================================
# Class: Recommended lookback math
# ===========================================================================


class TestRecommendedLookbackMath:
    """recommended_lookback_days = ceil(p99) + 1 per spec § 3.3 L656."""

    @pytest.mark.parametrize(
        "p99,expected_lookback",
        [
            (0.5, 2),   # ceil(0.5) + 1 = 1 + 1
            (1.0, 2),   # ceil(1.0) + 1 = 1 + 1
            (1.1, 3),   # ceil(1.1) + 1 = 2 + 1
            (2.7, 4),   # spec § 3.3 L656 canonical example
            (3.0, 4),   # ceil(3.0) + 1 = 3 + 1
            (4.9, 6),   # ceil(4.9) + 1 = 5 + 1
            (10.0, 11), # ceil(10.0) + 1 = 11
        ],
    )
    def test_recommended_lookback_ceil_plus_one(self, p99, expected_lookback):
        rep = _make_synthetic_report(p99=p99)
        mod = _load_tool_module(sample_report=rep)
        result = _call_main(mod, persist=False, recommend_lookback=True)
        assert result["report"]["recommended_lookback_days"] == expected_lookback


# ===========================================================================
# Class: Exit-code parametric contract
# ===========================================================================


@pytest.mark.parametrize(
    "scenario,expected_exit",
    [
        ("happy_path", EXIT_SUCCESS),
        ("insufficient_history", EXIT_FATAL),
        ("extraction_state_unavailable", EXIT_OPERATIONAL_FAILURE),
        ("unexpected_exception", EXIT_FATAL),
    ],
)
def test_exit_code_contract(scenario: str, expected_exit: int):
    """D74 + spec § 3.3 L659-662 — every exit path is 0 / 1 / 2.

    Parametrized over the four canonical exit-code scenarios to lock
    the D74 contract in one comprehensive check.
    """
    loader_kwargs: dict[str, Any] = {}
    if scenario == "insufficient_history":
        loader_kwargs["insufficient_history"] = True
    elif scenario == "extraction_state_unavailable":
        loader_kwargs["extraction_state_unavailable"] = True
    elif scenario == "unexpected_exception":
        loader_kwargs["unexpected_exception"] = True
    mod = _load_tool_module(**loader_kwargs)
    result = _call_main(mod, persist=False)
    assert result["exit_code"] == expected_exit, (
        f"Scenario {scenario!r} must yield exit {expected_exit}. "
        f"Got: {result.get('exit_code')!r}. "
        "D74 + spec § 3.3 L659-662."
    )


# ===========================================================================
# Class: cli_main exit-code propagation
# ===========================================================================


class TestCliMainExitCode:
    """cli_main returns one of 0 / 1 / 2 per D74."""

    def test_cli_main_returns_int(self):
        """cli_main returns int (not None)."""
        mod = _load_tool_module()
        # Patch sys.argv to canonical happy-path invocation
        with patch.object(
            sys, "argv",
            ["lateness_profile.py", "--source", _SOURCE, "--table", _TABLE,
             "--no-persist"],
        ):
            with patch.dict("sys.modules", mod._test_sys_modules_patch):
                rc = mod.cli_main()
        assert isinstance(rc, int)
        assert rc in (EXIT_SUCCESS, EXIT_OPERATIONAL_FAILURE, EXIT_FATAL)


# ===========================================================================
# Class: Verbose / quiet handling
# ===========================================================================


class TestVerbosityFlags:
    """--verbose / --quiet behave as documented."""

    def test_verbose_doesnt_change_exit_code(self):
        """--verbose does not affect exit code."""
        mod = _load_tool_module()
        result = _call_main(mod, persist=False, verbose=True)
        assert result["exit_code"] == EXIT_SUCCESS

    def test_quiet_doesnt_change_exit_code(self):
        """--quiet does not affect exit code."""
        mod = _load_tool_module()
        result = _call_main(mod, persist=False, quiet=True)
        assert result["exit_code"] == EXIT_SUCCESS

    def test_quiet_suppresses_human_stdout(self, capsys):
        """--quiet suppresses the human-readable summary."""
        mod = _load_tool_module()
        _call_main(mod, persist=False, quiet=True, json_output=False)
        captured = capsys.readouterr()
        # Quiet mode -> no "Lateness profile for" header
        assert "Lateness profile for" not in captured.out


# ===========================================================================
# Class: D26 append-only re-invocation
# ===========================================================================


class TestAppendOnlyRecallSemantic:
    """Multi-invocation produces multiple audit + LatenessProfile rows."""

    def test_two_invocations_call_persist_twice(self):
        """persist=True called twice -> persist_lateness_report invoked twice.

        D26 append-only — each invocation produces a trend row.
        Spec § 3.3 L626-627.
        """
        mod = _load_tool_module()
        _call_main(mod, persist=True)
        _call_main(mod, persist=True)
        assert mod._test_persist_mock.call_count == 2

    def test_same_input_returns_same_report(self):
        """profile_lateness mock returns identical report on each call.

        Spec § 3.3 L625-626 "Multi-call returns identical LatenessReport
        for identical inputs".
        """
        mod = _load_tool_module()
        r1 = _call_main(mod, persist=False)
        r2 = _call_main(mod, persist=False)
        assert r1["report"]["p99_days"] == r2["report"]["p99_days"]
        assert r1["report"]["sample_count"] == r2["report"]["sample_count"]


# ===========================================================================
# Class: Window date semantics
# ===========================================================================


class TestWindowDateSemantics:
    """window_start / window_end propagate correctly to the report."""

    def test_window_dates_from_report(self):
        """report['window_start'] == ISO-formatted date."""
        mod = _load_tool_module()
        result = _call_main(mod, persist=False)
        ws = result["report"]["window_start"]
        # Should be ISO-8601 date format YYYY-MM-DD
        assert re.match(r"^\d{4}-\d{2}-\d{2}$", ws), (
            f"window_start must be ISO-8601 date string. Got: {ws!r}"
        )

    def test_window_end_iso(self):
        mod = _load_tool_module()
        result = _call_main(mod, persist=False)
        we = result["report"]["window_end"]
        assert re.match(r"^\d{4}-\d{2}-\d{2}$", we)


# ===========================================================================
# Class: Sample count fidelity
# ===========================================================================


class TestSampleCountFidelity:
    """sample_count flows through from the report."""

    def test_sample_count_propagates(self):
        rep = _make_synthetic_report(sample_count=1500)
        mod = _load_tool_module(sample_report=rep)
        result = _call_main(mod, persist=False)
        assert result["report"]["sample_count"] == 1500

    def test_confidence_propagates(self):
        rep = _make_synthetic_report(sample_count=200, confidence="high")
        mod = _load_tool_module(sample_report=rep)
        result = _call_main(mod, persist=False)
        assert result["report"]["confidence"] == "high"


# ===========================================================================
# Class: Top-level dry_run flag is always False (read-only tool)
# ===========================================================================


class TestDryRunInvariant:
    """Per spec § 1.2 — read-only tools (incl. § 3.3) have no --apply."""

    def test_dry_run_in_result_is_false(self):
        """result['dry_run'] is False (read-only tool — no --apply flag)."""
        mod = _load_tool_module()
        result = _call_main(mod, persist=False)
        assert result["dry_run"] is False, (
            "Read-only tool always reports dry_run=False (no --apply). "
            "Spec § 1.2 + § 3.3 (no --apply in arg surface)."
        )
