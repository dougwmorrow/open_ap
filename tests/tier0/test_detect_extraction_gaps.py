"""Tier 0 build-time smoke test for tools/detect_extraction_gaps.py.

Per D67 — runs at build time + every commit. Runtime ceiling < 5 s.
All external dependencies mocked. No live DB, no live network required.

6-assertion D77 Tier-0 scaffold per phase1/04_tools.md § 3.5 L825:
  (a) Module imports without error.
  (b) --help exits 0 per D77 Tier 0 scaffold assertion 2.
  (c) Mocked detect_extraction_gaps returning empty list -> exit 0 +
      stdout contains 'No gaps' (spec § 3.5 L820 clean-state message).
  (d) Mocked returning one GapReport with missing_dates non-empty -> exit 1
      + stdout contains the source.table label (spec § 3.5 L820-823
      per-table block).
  (e) --alert + --actor automic + non-empty gaps -> mocked alert_dispatcher
      invoked once (spec § 3.5 L767 + L804 alert-default semantics).
  (f) --json produces parseable JSON (spec § 3.5 L826 JSON output).
  Plus runtime assertion: total wall time < 5 s per D67.

North Star pillars (NORTH_STAR.md):
  - Audit-grade (D76): ONE CLI_DETECT_EXTRACTION_GAPS PipelineEventLog row
    per invocation; Metadata JSON carries as_of_date, source_filter,
    tables_with_gaps, total_missing_dates, affected_tables, alert_fired,
    event_kind='gap_detection', actor, exit_code, dry_run=False.
  - Operationally stable (D67 / D74): import + invoke + shape + error-modes
    in < 5 s with zero external I/O; exit-code contract 0/1/2 enforced.
  - Idempotent (D15 / D22): read-only on PipelineExtraction; multi-call
    returns identical reports for unchanged historical data.
  - Traceability (D26): every invocation writes ONE PipelineEventLog row
    with EventType='CLI_DETECT_EXTRACTION_GAPS' (§ 3.5 L766) DISTINCT
    from the wrapped module's GAP_DETECT row (spec § 3.5 L766-769).

Canonical references (Pitfall #9.l — re-read DDL + Round 3 module before
authoring):
  Round 3 § 5.3 detect_extraction_gaps signature (tools/gap_detector.py L674):
    detect_extraction_gaps(*, source_filter: str | None = None,
                             as_of_date: date | None = None) -> list[GapReport]
    Keyword-only; both args optional.
  GapReport dataclass (tools/gap_detector.py L233-272):
    source_name (str), table_name (str), expected_range (tuple[date, date]),
    missing_dates (list[date]), recommended_action (str). Frozen.
  Recommended-action values (tools/gap_detector.py L201-204; Pitfall #9.c
  strict):
    'backfill' | 'investigate-source' | 'within-lookback-no-action'.
  PipelineEventLog DDL (01_database_schema.md § 2):
    BatchId, TableName, SourceName, EventType, EventDetail, StartedAt,
    CompletedAt, Status, ErrorMessage, Metadata. INSERT pattern per
    sibling enforce_retention + promote_test_to_prod.

D-numbers cited: D22 (hourly gap detector), D67 (Tier 0 discipline), D68
  (error class hierarchy — GapDetectorTimeout / ExtractionStateUnavailable
  both PipelineRetryableError), D74 (exit-code contract 0/1/2), D75
  (canonical arg naming: source/as-of-date/alert/include-recommendation/
  actor/json/verbose/quiet/no-audit-event), D76 (audit-row contract
  CLI_DETECT_EXTRACTION_GAPS), D77 (Tier 0 6-canonical scaffold per
  § 3.5 L825), D92 (forward-only additive — new CLI).

Edge cases cited:
  G1-G5 (gap-detection series — operator review path on missing dates).
  I1 (same BatchId retry — gap detection is read-only and idempotent).
  I3 (concurrent same-key — no sp_getapplock per § 3.5 L785-786;
       reports are reproducible).

B-numbers:
  B228 (utils.errors canonical exception module — GapDetectorTimeout +
        ExtractionStateUnavailable imported from there).
  B214 (sys.modules pre-registration before exec_module — applied below).
  B218 (stash _test_sys_modules_patch for _call_main re-patch — applied below).

Independence note: tests/tier0/test_detect_extraction_gaps.py is authored
INDEPENDENTLY from tools/detect_extraction_gaps.py per D55 (5-gate
validation discipline — test author ≠ code author). Tests pin the spec
contract per phase1/04_tools.md § 3.5 L751-833 WITHOUT reading the
implementation.

Spec: phase1/04_tools.md § 3.5 (canonical spec L751-833).
M13 engine: tools/gap_detector.py.
"""
from __future__ import annotations

import importlib
import importlib.util
import io
import json
import sys
import time
from contextlib import redirect_stdout
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
# Constants — single source of truth
# ---------------------------------------------------------------------------

# D76 EventType per CLI_* family (§ 3.5 L766)
EXPECTED_EVENT_TYPE = "CLI_DETECT_EXTRACTION_GAPS"

# D74 exit codes (§ 3.5 L829-832)
EXIT_SUCCESS = 0
EXIT_OPERATIONAL = 1
EXIT_FATAL = 2

# Canonical defaults
_ACTOR_OPERATOR = "test-author"
_ACTOR_AUTOMIC = "automic"
_AS_OF_DATE_DEFAULT = "2026-05-12"


# ---------------------------------------------------------------------------
# GapReport stand-in — mirrors tools/gap_detector.py canonical shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _GapReportStub:
    """Minimal stand-in for tools.gap_detector.GapReport.

    Per gap_detector.py L233-272 — frozen dataclass with the canonical
    fields. Stand-in so tier 0 test does NOT need to import the real
    dataclass (preserves Tier 0 < 5 s discipline + isolation from
    Round 3 engine module).
    """

    source_name: str = "DNA"
    table_name: str = "ACCT"
    expected_range: tuple = (date(2026, 1, 1), date(2026, 5, 10))
    missing_dates: list = field(default_factory=lambda: [date(2026, 3, 15), date(2026, 3, 16)])
    recommended_action: str = "backfill"


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
    """Load tools/detect_extraction_gaps.py with all external imports mocked.

    Parameters
    ----------
    gap_reports:
        Simulated return value from gap_detector.detect_extraction_gaps.
        ``None`` -> empty list (clean state). A list of GapReport
        instances simulates the gap-detected path.
    raise_timeout:
        If True, the mocked detect_extraction_gaps raises
        GapDetectorTimeout (-> exit 1 per D68 retryable).
    raise_state_unavailable:
        If True, the mocked detect_extraction_gaps raises
        ExtractionStateUnavailable (-> exit 1 per D68 retryable).
    raise_unexpected:
        If True, the mocked detect_extraction_gaps raises a generic
        Exception (-> exit 2 per § 1.8 fatal).

    Applies B214 (pre-register sys.modules before exec_module), B218
    (stash _test_sys_modules_patch + _test_executed_sql + _test_executed_params
    on mod), B228 (real exception classes from utils.errors).
    """
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
    # SCOPE_IDENTITY pattern for audit-row INSERT.
    _audit_event_id_seq = [77001, 77002, 77003]

    def _smart_fetchone():
        last_sql = executed_sql[-1] if executed_sql else ""
        if "SCOPE_IDENTITY" in last_sql.upper():
            return (_audit_event_id_seq.pop(0) if _audit_event_id_seq else 99999,)
        return None

    mock_cursor.fetchone.side_effect = _smart_fetchone
    mock_cursor.fetchall.return_value = []
    mock_cursor.rowcount = 0

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

    # Resolve canonical exception classes from utils.errors (B228).
    # NEVER mock utils.errors — the module is dependency-free + tests
    # need the real classes for ``except`` blocks to work.
    from utils.errors import (
        ExtractionStateUnavailable,
        GapDetectorTimeout,
    )

    # Build the gap_detector mock — wraps Round 3 § 5.3.
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
    # Expose the GapReport class through the mocked module so any code
    # path that does `tools.gap_detector.GapReport(...)` resolves.
    mock_gap_detector.GapReport = _GapReportStub

    # alert_dispatcher mock — tracks invocations for assertion (e).
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
        # B214: pre-register BEFORE exec_module
        sys.modules[_TOOL_MODULE_KEY] = mod
        spec.loader.exec_module(mod)

    # B218: stash for _call_main re-patch
    mod._test_sys_modules_patch = sys_modules_patch
    mod._test_cursor = mock_cursor
    mod._test_executed_sql = executed_sql
    mod._test_executed_params = executed_params
    mod._test_gap_detector = mock_gap_detector
    mod._test_alert_dispatcher = mock_alert_dispatcher
    return mod


def _call_main(mod: Any, *, capture_stdout: bool = True, **overrides: Any):
    """Call tool main() with canonical defaults + overrides.

    Canonical signature per pre-specified B219 block + spec § 3.5:
      main(*, actor, as_of_date, source, alert, include_recommendation,
           json_output, verbose, quiet, no_audit_event,
           gap_detector, alert_dispatcher, audit_cursor_factory,
           general_db) -> dict

    Re-applies sys.modules patch per B218 lesson.

    Returns (result_dict, stdout_text) when capture_stdout=True, else
    just result_dict.
    """
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
        # Inject the mocked gap_detector so module-level resolver is
        # bypassed (avoids importlib.import_module branch).
        gap_detector=_make_injection_detector(mod),
        alert_dispatcher=_make_injection_alert(mod),
    )
    defaults.update(overrides)
    sys_modules_patch = getattr(mod, "_test_sys_modules_patch", {})

    buf = io.StringIO() if capture_stdout else None
    try:
        with patch.dict("sys.modules", sys_modules_patch):
            if buf is not None:
                with redirect_stdout(buf):
                    result = mod.main(**defaults)
            else:
                result = mod.main(**defaults)
    except SystemExit as exc:
        result = {"exit_code": exc.code, "_raised_system_exit": True}
    except Exception as exc:
        result = {"exit_code": EXIT_FATAL, "_exception": str(exc), "_raised_system_exit": False}

    if capture_stdout:
        return result, (buf.getvalue() if buf is not None else "")
    return result


def _make_injection_detector(mod: Any):
    """Return a callable that bridges the mock to the tool's gap_detector kwarg."""
    test_mock = mod._test_gap_detector

    def _detect(*, source_filter, as_of_date):
        return test_mock.detect_extraction_gaps(
            source_filter=source_filter,
            as_of_date=as_of_date,
        )

    return _detect


def _make_injection_alert(mod: Any):
    """Return a callable that bridges the mock to the tool's alert_dispatcher kwarg."""
    test_mock = mod._test_alert_dispatcher

    def _dispatch(*, severity, source_tool, message, details=None):
        return test_mock.dispatch_alert(
            severity=severity,
            source_tool=source_tool,
            message=message,
            details=details or {},
        )

    return _dispatch


# ===========================================================================
# Tier 0 assertion (a): module imports without error
# ===========================================================================


def test_a_module_imports():
    """(a) Module imports without error.

    D67 Tier 0 assertion 1: the module must be importable with all
    external dependencies mocked. A failed import means a missing
    dependency or syntax error that blocks every subsequent build step.

    North Star: Operationally stable (D67). Spec: § 3.5 L825(a).
    """
    _t0 = time.monotonic()

    mod = _load_tool_module()

    assert mod is not None, (
        "tools/detect_extraction_gaps.py must load without error. "
        "Check for missing imports or syntax errors. D67 Tier 0 (a)."
    )
    assert hasattr(mod, "main"), (
        "tools/detect_extraction_gaps.py must expose a top-level 'main' "
        "function per § 3.5 CLI interface. D67 Tier 0 (a)."
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
    discoverability path for all CLI tools per D75 argument naming
    discipline. argparse emits SystemExit(0) on --help.

    North Star: Operationally stable (D77 Tier 0 scaffold).
    Spec: § 3.5 L825(b).
    """
    mod = _load_tool_module()

    assert hasattr(mod, "_build_arg_parser"), (
        "tools/detect_extraction_gaps.py must expose _build_arg_parser "
        "for Tier 0 (b) assertion. D77."
    )
    parser = mod._build_arg_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["--help"])
    assert exc_info.value.code == 0, (
        f"--help must exit 0. Got: {exc_info.value.code!r}. "
        "D74 (exit 0 = success / informational). Spec: § 3.5 L825(b)."
    )


# ===========================================================================
# Tier 0 assertion (c): empty list -> exit 0 + stdout contains 'No gaps'
# ===========================================================================


def test_c_empty_list_exits_zero_with_no_gaps_message():
    """(c) Mocked detect_extraction_gaps returning empty list -> exit 0 + 'No gaps' in stdout.

    Per spec § 3.5 L820: ``Stdout`` (success, no gaps): ``No gaps
    detected (N tables checked).``

    Verifies the clean-state path: when no gaps are found, the tool
    exits 0 (success) and renders the canonical no-gaps message to
    stdout. This is the load-bearing distinction between clean state
    (exit 0) and gap-detected state (exit 1) that drives the simple
    Automic ``if exit==1 then alert`` rule per spec § 3.5 L830-832.

    North Star: Operationally stable + Audit-grade. Spec: § 3.5 L825(c) + L820.
    """
    mod = _load_tool_module(gap_reports=[])

    result, stdout = _call_main(mod)

    exit_code = result.get("exit_code") if isinstance(result, dict) else None
    assert exit_code == EXIT_SUCCESS, (
        f"Empty gap list must exit {EXIT_SUCCESS}. Got: {exit_code!r}. "
        "D74 (exit 0 = no gaps / clean state). Spec: § 3.5 L829 + L825(c)."
    )

    # The "No gaps" message is the canonical clean-state signal.
    assert "No gaps" in stdout, (
        f"Clean-state stdout must contain 'No gaps' per spec § 3.5 L820. "
        f"Got stdout: {stdout!r}"
    )


# ===========================================================================
# Tier 0 assertion (d): non-empty gaps -> exit 1 + source.table label in stdout
# ===========================================================================


def test_d_gaps_detected_exits_one_with_source_table_label():
    """(d) Mocked returning one GapReport with missing_dates non-empty -> exit 1 + source.table label.

    Per spec § 3.5 L820 (gap-detected stdout) + § 3.5 L830 (exit 1 on
    gaps detected): each affected (source, table) renders a per-block
    section starting with the canonical ``SOURCE.TABLE`` header.

    Verifies the gap-detected path: when one or more GapReport instances
    are returned, the tool exits 1 (operational; Automic should alert)
    and the source.table label surfaces in stdout for operator review.

    North Star: Operationally stable + Traceability. Spec: § 3.5 L825(d) + L820-823 + L830.
    """
    report = _GapReportStub(
        source_name="DNA",
        table_name="ACCT",
        expected_range=(date(2026, 1, 1), date(2026, 5, 10)),
        missing_dates=[date(2026, 3, 15), date(2026, 3, 16)],
        recommended_action="backfill",
    )
    mod = _load_tool_module(gap_reports=[report])

    result, stdout = _call_main(mod)

    exit_code = result.get("exit_code") if isinstance(result, dict) else None
    assert exit_code == EXIT_OPERATIONAL, (
        f"Gap-detected state must exit {EXIT_OPERATIONAL}. "
        f"Got: {exit_code!r}. D74 (exit 1 = gaps detected; "
        "operator review). Spec: § 3.5 L830 + L825(d)."
    )

    # Canonical source.table label per spec § 3.5 L820.
    assert "DNA.ACCT" in stdout, (
        f"Per-table block must surface 'DNA.ACCT' label per spec § 3.5 L820. "
        f"Got stdout: {stdout!r}"
    )


# ===========================================================================
# Tier 0 assertion (e): --alert + automic + gaps -> alert_dispatcher invoked
# ===========================================================================


def test_e_alert_with_automic_invokes_alert_dispatcher_once():
    """(e) --alert + --actor automic + non-empty gaps -> alert_dispatcher invoked once.

    Per spec § 3.5 L767: 'Alert dispatch via tools/alert_dispatcher.py
    (§ 3.11) IF any gap detected and --alert flag set (default ON when
    --actor automic).'
    Per spec § 3.5 L804: '--alert | flag | True when --actor automic,
    False otherwise'.

    Verifies the alert-dispatch wiring: when actor=automic AND alert
    resolves True AND gaps are detected, the alert_dispatcher is invoked
    exactly once. The dispatcher returning True/False does NOT affect
    the verdict (gap-detection success is independent of alert dispatch
    success per spec § 3.5 narrative).

    North Star: Operationally stable + Traceability. Spec: § 3.5 L825(e) + L767 + L804.
    """
    report = _GapReportStub()
    mod = _load_tool_module(gap_reports=[report])

    result, _stdout = _call_main(
        mod,
        actor=_ACTOR_AUTOMIC,
        alert=True,
    )

    exit_code = result.get("exit_code") if isinstance(result, dict) else None
    assert exit_code == EXIT_OPERATIONAL, (
        f"Gap-detected + automic + alert must exit {EXIT_OPERATIONAL}. "
        f"Got: {exit_code!r}. Spec: § 3.5 L830."
    )

    # alert_dispatcher.dispatch_alert MUST be invoked exactly once when
    # gaps detected AND alert resolves True.
    dispatcher_mock = mod._test_alert_dispatcher
    assert dispatcher_mock.dispatch_alert.call_count == 1, (
        f"alert_dispatcher.dispatch_alert must be invoked exactly once "
        f"when actor=automic + alert=True + gaps detected. "
        f"Got call_count={dispatcher_mock.dispatch_alert.call_count}. "
        f"Spec: § 3.5 L767 + L804 + L825(e)."
    )


# ===========================================================================
# Tier 0 assertion (f): --json produces parseable JSON
# ===========================================================================


def test_f_json_output_is_parseable():
    """(f) --json produces parseable JSON.

    Per spec § 3.5 L826: '``Stdout`` (``--json``): ``[{"source_name":
    "...", "table_name": "...", "expected_range": [...],
    "missing_dates": [...], "recommended_action": "..."}]``.'

    Verifies the machine-readable output path: with --json, stdout MUST
    be parseable as JSON (json.loads succeeds). The schema is asserted
    in Tier 1 (presence of canonical keys); Tier 0 only asserts
    parseability.

    North Star: Operationally stable + Traceability. Spec: § 3.5 L825(f) + L826.
    """
    report = _GapReportStub()
    mod = _load_tool_module(gap_reports=[report])

    result, stdout = _call_main(mod, json_output=True)

    exit_code = result.get("exit_code") if isinstance(result, dict) else None
    assert exit_code == EXIT_OPERATIONAL, (
        f"Gap-detected + json must exit {EXIT_OPERATIONAL}. "
        f"Got: {exit_code!r}. Spec: § 3.5 L830."
    )

    # The JSON output must be parseable.
    try:
        parsed = json.loads(stdout)
    except json.JSONDecodeError as exc:
        pytest.fail(
            f"--json stdout must be parseable JSON per spec § 3.5 L826. "
            f"Got JSONDecodeError: {exc}. Raw stdout: {stdout!r}"
        )

    assert isinstance(parsed, list), (
        f"--json output must be a JSON array per spec § 3.5 L826. "
        f"Got type: {type(parsed).__name__}"
    )


# ===========================================================================
# Tier 0 assertion: total wall time < 5 s per D67
# ===========================================================================


def test_total_runtime_under_five_seconds():
    """Aggregate D67 runtime ceiling for the full Tier 0 surface.

    Tier 0 < 5 s per D67. Individual assertions are quick; this test
    re-runs the heaviest assertions back-to-back to catch any
    regression that pushes the suite past the ceiling.
    """
    _t0 = time.monotonic()
    mod = _load_tool_module(gap_reports=[_GapReportStub()])
    _result1, _stdout1 = _call_main(mod, actor=_ACTOR_AUTOMIC, alert=True)
    _result2, _stdout2 = _call_main(mod, json_output=True)
    mod_empty = _load_tool_module(gap_reports=[])
    _result3, _stdout3 = _call_main(mod_empty)
    elapsed = time.monotonic() - _t0
    assert elapsed < 5.0, (
        f"Tier 0 aggregate must complete in < 5 s. Took {elapsed:.2f} s. D67."
    )
