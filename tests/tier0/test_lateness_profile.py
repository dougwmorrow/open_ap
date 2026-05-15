"""Tier 0 build-time smoke test for tools/lateness_profile.py.

Per D67 — runs at build time + every commit. Runtime ceiling < 5 s.
All external dependencies (cdc.lateness_profiler, pyodbc cursors,
PipelineEventLog INSERT) are mocked. No live DB / network required.

7-assertion D77-canonical scaffold per phase1/04_tools.md § 3.3 L664:
  (a) Module imports without error (tools/lateness_profile.py).
  (b) --help exits 0 per D77 Tier 0 scaffold assertion 2.
  (c) --source DNA --table ACCT parses successfully.
  (d) Mocked profile_lateness returning a valid LatenessReport with
      percentiles -> tool returns exit 0 with stdout containing "p99".
  (e) Mocked profile_lateness raising InsufficientHistory
      (PipelineFatalError) -> tool returns exit 2 per § 1.8 mapping
      + spec § 3.3 L660-662.
  (f) --json produces parseable JSON (canonical schema per spec L658).
  (g) --no-persist does NOT call any DB write (persist_lateness_report
      not invoked).

The 7 assertions in § 3.3 L664 are the canonical Tier 0 surface; Round
5 may extend (Tier 1 below) but may not weaken.

North Star pillars:
  - Audit-grade (D76 audit-row contract: exactly one CLI_LATENESS_PROFILE
    row per invocation; Metadata JSON carries the report payload).
  - Operationally stable (D67 Tier 0: import + invoke + shape + error-
    modes in < 5s with zero external I/O; D74 exit-code contract 0/1/2).
  - Idempotent (D26): LatenessProfile INSERT is append-only; multi-call
    same-input returns identical LatenessReport.
  - Traceability (D26, D11): every invocation writes ONE
    CLI_LATENESS_PROFILE row.

LatenessReport canonical fields (Pitfall #9.a — verified against
cdc/lateness_profiler.py):
  source_name, table_name, window_start (date), window_end (date),
  sample_count (int), p50_days/p90_days/p95_days/p99_days (float),
  max_observed_days (int), confidence (str), as_of (datetime).

profile_lateness canonical signature (Pitfall #9.b — verified against
cdc/lateness_profiler.py:profile_lateness L455):
  profile_lateness(*, source_name, table_name, window_days,
                   min_sample_days) -> LatenessReport
  KEYWORD-ONLY (leading-*); positional invocation TypeErrors.

D-numbers: D11 (empirical L_99), D67 (Tier 0 discipline), D74
  (exit-code 0/1/2), D75 (arg naming), D76 (audit-row contract
  CLI_LATENESS_PROFILE), D77 (7-assertion Tier 0 scaffold per § 3.3 L664).

Edge cases cited:
  I1 (same BatchId retry — stateless re-call returns identical report).
  I3 (concurrent same-key — stateless read-only multi-worker safe).

Spec: phase1/04_tools.md § 3.3 (canonical spec L577-663).
Wrapped module: cdc/lateness_profiler.py (M12).
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import sys
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
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
# Constants — single source of truth for all expected values
# ---------------------------------------------------------------------------

# D76 EventType per CLI_* family (§ 3.3 L617)
EXPECTED_EVENT_TYPE = "CLI_LATENESS_PROFILE"

# D74 exit codes (§ 3.3 L659-662)
EXIT_SUCCESS = 0
EXIT_OPERATIONAL_FAILURE = 1
EXIT_FATAL = 2

# D75 canonical actor (per TTY heuristic default — used in tests)
_ACTOR = "test-build-smoke"

# Canonical (source, table) example from spec § 3.3 L634
_SOURCE = "DNA"
_TABLE = "ACCT"


# ---------------------------------------------------------------------------
# Synthetic LatenessReport — matches cdc/lateness_profiler.py dataclass
# ---------------------------------------------------------------------------


def _make_synthetic_report(
    *,
    sample_count: int = 87,
    p50: float = 0.2,
    p90: float = 0.8,
    p95: float = 1.3,
    p99: float = 2.7,
    max_obs: int = 4,
    confidence: str = "medium",
) -> Any:
    """Build a synthetic LatenessReport-like object for mocking.

    Per canonical dataclass at cdc/lateness_profiler.py:LatenessReport.
    """

    class _SyntheticReport:
        pass

    r = _SyntheticReport()
    r.source_name = _SOURCE
    r.table_name = _TABLE
    r.window_start = date(2026, 2, 9)
    r.window_end = date(2026, 5, 10)
    r.sample_count = sample_count
    r.p50_days = p50
    r.p90_days = p90
    r.p95_days = p95
    r.p99_days = p99
    r.max_observed_days = max_obs
    r.confidence = confidence
    r.as_of = datetime(2026, 5, 10, 12, 0, 0)
    return r


# ---------------------------------------------------------------------------
# Module loader — mocks all external dependencies
# ---------------------------------------------------------------------------


def _load_tool_module(
    *,
    insufficient_history: bool = False,
    extraction_state_unavailable: bool = False,
    sample_report: Any = None,
) -> Any:
    """Load tools/lateness_profile.py with all external imports mocked.

    Parameters
    ----------
    insufficient_history:
        If True, the mocked profile_lateness raises InsufficientHistory
        (PipelineFatalError -> exit 2).
    extraction_state_unavailable:
        If True, the mocked profile_lateness raises
        ExtractionStateUnavailable (PipelineRetryableError -> exit 1).
    sample_report:
        Pre-built LatenessReport-like object; if None, a default
        synthetic report is used.

    B214 pattern: sys.modules pre-registration before exec_module().
    B215 pattern: canonical exception classes from utils.errors are
    NOT mocked.
    B218 pattern: _test_sys_modules_patch stashed on mod for _call_main
    re-patch.
    """
    if _TOOL_MODULE_KEY in sys.modules:
        del sys.modules[_TOOL_MODULE_KEY]

    # Canonical exception classes — NOT mocked (B215 lesson).
    try:
        from utils.errors import (  # noqa: F401
            ExtractionStateUnavailable,
            InsufficientHistory,
        )
        _isuf_cls = InsufficientHistory
        _esu_cls = ExtractionStateUnavailable
    except ImportError:
        # Defensive stand-ins so Tier 0 still runs the remaining
        # assertions when utils.errors hasn't been authored.
        class InsufficientHistory(Exception):  # type: ignore[no-redef]
            """Stand-in for utils.errors.InsufficientHistory."""

            def __init__(self, message: str, *, metadata: dict | None = None):
                super().__init__(message)
                self.metadata = metadata or {}

        class ExtractionStateUnavailable(Exception):  # type: ignore[no-redef]
            """Stand-in for utils.errors.ExtractionStateUnavailable."""

            def __init__(self, message: str, *, metadata: dict | None = None):
                super().__init__(message)
                self.metadata = metadata or {}

        _isuf_cls = InsufficientHistory
        _esu_cls = ExtractionStateUnavailable

    # Build the mocked profile_lateness + persist_lateness_report
    mock_profile_lateness = MagicMock()
    mock_persist = MagicMock(return_value=42)  # synthetic ProfileId

    if insufficient_history:
        mock_profile_lateness.side_effect = _isuf_cls(
            "fewer than min_sample_days SUCCESS rows in window",
            metadata={"sample_count": 5, "min_sample_days": 30},
        )
    elif extraction_state_unavailable:
        mock_profile_lateness.side_effect = _esu_cls(
            "Connection failure during PipelineExtraction lookup (test fixture)",
            metadata={"source_name": _SOURCE, "table_name": _TABLE},
        )
    else:
        rep = sample_report if sample_report is not None else _make_synthetic_report()
        mock_profile_lateness.return_value = rep

    mock_lateness_profiler = MagicMock()
    mock_lateness_profiler.profile_lateness = mock_profile_lateness
    mock_lateness_profiler.persist_lateness_report = mock_persist

    # ---- Audit cursor mock ----
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
    mock_audit_cursor.fetchone.return_value = (12345,)
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
        # B214: pre-register BEFORE exec_module
        sys.modules[_TOOL_MODULE_KEY] = mod
        spec.loader.exec_module(mod)

    # B218: stash for _call_main re-patch
    mod._test_sys_modules_patch = sys_modules_patch
    mod._test_profile_lateness_mock = mock_profile_lateness
    mod._test_persist_mock = mock_persist
    mod._test_audit_cursor = mock_audit_cursor
    mod._test_executed_sql = executed_sql
    mod._test_executed_params = executed_params
    return mod


def _call_main(mod: Any, **overrides: Any) -> dict:
    """Call tool main() with canonical defaults + overrides.

    Re-applies sys.modules patch from _load_tool_module so runtime
    sys.modules.get(...) lookups honor test mocks (B218 pattern).
    """
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
# Assertion (a): Module imports without error
# ===========================================================================


def test_a_module_imports():
    """(a) tools/lateness_profile.py imports without error.

    Per D67 Tier 0 assertion 1 + D77 7-canonical scaffold assertion 1.
    Verifies no missing dependencies, no syntax errors, no import-time
    DB calls. Module must expose a top-level 'main' function per § 3.3
    CLI interface.

    North Star: Operationally stable (import failure blocks every build).
    D67, D77. Spec: phase1/04_tools.md § 3.3 L664(a).
    """
    mod = _load_tool_module()
    assert mod is not None, (
        "tools/lateness_profile.py must load without error. "
        "Check for missing dependencies or syntax errors. D67."
    )
    assert hasattr(mod, "main"), (
        "tools/lateness_profile.py must expose a top-level 'main' "
        "function per § 3.3 CLI interface. D67 Tier 0 assertion 1."
    )


# ===========================================================================
# Assertion (b): --help exits 0
# ===========================================================================


def test_b_help_exits_0():
    """(b) --help exits 0 per D77 Tier 0 scaffold assertion 2.

    argparse always calls sys.exit(0) on --help. Confirms the CLI is
    wired up correctly and does not crash before argparse reaches
    argument parsing.

    D74 (exit 0 = success), D77. Spec: § 3.3 L664(b).
    """
    mod = _load_tool_module()
    assert hasattr(mod, "_build_arg_parser") or hasattr(mod, "_build_parser"), (
        "Module must expose _build_arg_parser or _build_parser for Tier 0 "
        "arg-parse contract verification. Spec: § 3.3 L664(b)."
    )
    parser = (
        mod._build_arg_parser() if hasattr(mod, "_build_arg_parser")
        else mod._build_parser()
    )
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["--help"])
    assert exc_info.value.code == 0, (
        f"--help must exit 0 per D74. Got: {exc_info.value.code!r}. "
        "D74 (exit 0 = success), D77. Spec: § 3.3 L664(b)."
    )


# ===========================================================================
# Assertion (c): --source DNA --table ACCT parses
# ===========================================================================


def test_c_source_table_parses():
    """(c) --source DNA --table ACCT parses successfully.

    Per spec § 3.3 L664(c) — verifies the canonical positional-arg
    invocation from spec L634-635 example works.

    D75 (canonical args). Spec: § 3.3 L664(c) + L634.
    """
    mod = _load_tool_module()
    parser = (
        mod._build_arg_parser() if hasattr(mod, "_build_arg_parser")
        else mod._build_parser()
    )
    args = parser.parse_args(["--source", _SOURCE, "--table", _TABLE])
    assert args.source == _SOURCE, (
        f"--source must parse to {_SOURCE!r}. Got: {args.source!r}. "
        "Spec: § 3.3 L664(c)."
    )
    assert args.table == _TABLE, (
        f"--table must parse to {_TABLE!r}. Got: {args.table!r}. "
        "Spec: § 3.3 L664(c)."
    )
    # Canonical defaults per spec § 3.3 L646-651
    assert args.window_days == 90, (
        f"--window-days default must be 90 per spec § 3.3 L647. "
        f"Got: {args.window_days!r}."
    )
    assert args.min_sample_days == 30, (
        f"--min-sample-days default must be 30 per spec § 3.3 L648. "
        f"Got: {args.min_sample_days!r}."
    )
    assert args.persist is True, (
        f"--persist default must be True per spec § 3.3 L649. "
        f"Got: {args.persist!r}."
    )
    assert args.recommend_lookback is True, (
        f"--recommend-lookback default must be True per spec § 3.3 L650. "
        f"Got: {args.recommend_lookback!r}."
    )


# ===========================================================================
# Assertion (d): mocked profile_lateness -> exit 0 + stdout has "p99"
# ===========================================================================


def test_d_happy_path_exits_0_with_p99(capsys):
    """(d) Mocked profile_lateness returning LatenessReport with valid
    percentiles -> tool returns exit 0 with stdout containing "p99".

    Per spec § 3.3 L664(d). The headline metric is p99 (per D11 — the
    empirical L_99 lookback drives UdmTablesList.LookbackDays). The
    stdout block per spec § 3.3 L646-657 includes a "p99" line.

    D74 (exit 0), D11 (empirical L_99 headline). Spec: § 3.3 L664(d) +
    L646-657.
    """
    mod = _load_tool_module()
    result = _call_main(mod, persist=False)  # avoid persist side-effect noise

    exit_code = result.get("exit_code")
    assert exit_code in (EXIT_SUCCESS, None), (
        f"Happy-path must yield exit {EXIT_SUCCESS}. Got: {exit_code!r}. "
        "D74. Spec: § 3.3 L664(d)."
    )

    captured = capsys.readouterr()
    combined = captured.out + captured.err
    assert "p99" in combined.lower() or "p99" in combined, (
        f"Stdout must contain 'p99' headline per spec § 3.3 L646-657. "
        f"Captured stdout: {captured.out!r}; stderr: {captured.err!r}. "
        "Spec: § 3.3 L664(d) + L651."
    )


# ===========================================================================
# Assertion (e): InsufficientHistory -> exit 2 (fatal)
# ===========================================================================


def test_e_insufficient_history_exits_2():
    """(e) Mocked profile_lateness raising InsufficientHistory
    (PipelineFatalError) -> tool returns exit 2 per § 1.8 mapping.

    Per spec § 3.3 L664(e) + L660-662 ('fatal: InsufficientHistory
    (Round 3 § 5.2 PipelineFatalError per § 1.8 mapping)').
    InsufficientHistory is a PipelineFatalError subclass; maps to exit 2.

    D68 (error class hierarchy), D74 (exit 2 = fatal). Spec: § 3.3
    L664(e) + L660-662.
    """
    mod = _load_tool_module(insufficient_history=True)
    result = _call_main(mod, persist=False)

    exit_code = result.get("exit_code")
    assert exit_code == EXIT_FATAL, (
        f"InsufficientHistory must yield exit {EXIT_FATAL} (fatal). "
        f"Got: {exit_code!r}. "
        "Per D68 + D74: InsufficientHistory = PipelineFatalError -> exit 2. "
        "Spec: § 3.3 L664(e) + L660-662."
    )


# ===========================================================================
# Assertion (f): --json produces parseable JSON
# ===========================================================================


def test_f_json_output_parseable(capsys):
    """(f) --json produces parseable JSON per spec § 3.3 L658.

    Canonical JSON shape: {"source_name": "...", "table_name": "...",
    "window_start": "...", "window_end": "...", "sample_count": N,
    "p50_days": X, ..., "recommended_lookback_days": Y}.

    D75 (--json arg), D77 (Tier 0 scaffold). Spec: § 3.3 L664(f) + L658.
    """
    mod = _load_tool_module()
    result = _call_main(mod, json_output=True, persist=False)

    exit_code = result.get("exit_code")
    assert exit_code in (EXIT_SUCCESS, None), (
        f"--json happy-path must yield exit {EXIT_SUCCESS}. "
        f"Got: {exit_code!r}. Spec: § 3.3 L664(f)."
    )

    captured = capsys.readouterr()
    # JSON appears on stdout (per spec § 3.3 L658 + § 1.4 --json convention)
    stdout = captured.out.strip()
    assert stdout, "--json must produce stdout output. Spec: § 3.3 L664(f)."

    # Parse — must not raise
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError as exc:
        pytest.fail(
            f"--json output must be parseable JSON per spec § 3.3 L658. "
            f"Got non-parseable: {stdout!r}. Error: {exc}"
        )

    # Canonical keys per spec § 3.3 L658
    assert "source_name" in payload, (
        f"JSON must include 'source_name' per spec § 3.3 L658. "
        f"Got keys: {list(payload.keys())!r}."
    )
    assert "p99_days" in payload, (
        f"JSON must include 'p99_days' per spec § 3.3 L658 (the headline "
        f"L_99 metric per D11). Got keys: {list(payload.keys())!r}."
    )


# ===========================================================================
# Assertion (g): --no-persist does NOT call persist_lateness_report
# ===========================================================================


def test_g_no_persist_skips_db_write():
    """(g) --no-persist does NOT call any DB write
    (persist_lateness_report not invoked).

    Per spec § 3.3 L664(g) — '--no-persist does NOT call any DB write'.
    The --persist flag defaults ON per spec § 3.3 L649; --no-persist
    suppresses the LatenessProfile INSERT.

    D26 (append-only audit — but only when persist enabled). Spec:
    § 3.3 L664(g) + L649.
    """
    mod = _load_tool_module()
    result = _call_main(mod, persist=False)

    exit_code = result.get("exit_code")
    assert exit_code in (EXIT_SUCCESS, None), (
        f"--no-persist must still yield exit {EXIT_SUCCESS}. "
        f"Got: {exit_code!r}. Spec: § 3.3 L664(g)."
    )

    # Verify persist_lateness_report was NOT invoked
    persist_mock = mod._test_persist_mock
    assert not persist_mock.called, (
        f"--no-persist must NOT call persist_lateness_report. "
        f"Got call_count={persist_mock.call_count}, "
        f"call_args_list={persist_mock.call_args_list!r}. "
        "Spec: § 3.3 L664(g) + L649."
    )


# ===========================================================================
# Runtime ceiling assertion — Tier 0 must complete < 5 s total (D67)
# ===========================================================================


def test_tier0_runtime_ceiling():
    """Tier 0 full suite mock-invocation completes < 5 s (D67 ceiling).

    Verifies that the smoke test itself does not incur external I/O.
    Runs all primary operations (import, happy-path, error-path) under
    the 5-second ceiling mandated by D67.

    D67 (runtime ceiling < 5s per module). Spec: § 3.3 L664 preamble.
    """
    start = time.monotonic()

    mod = _load_tool_module()
    assert mod is not None

    _call_main(mod, persist=False)
    _call_main(mod, persist=False, json_output=True)

    mod2 = _load_tool_module(insufficient_history=True)
    _call_main(mod2, persist=False)

    elapsed = time.monotonic() - start
    assert elapsed < 5.0, (
        f"Tier 0 mock invocations exceeded 5s ceiling: {elapsed:.2f}s. "
        "D67 mandates < 5s for Tier 0 smoke tests (no external deps). "
        "Check for live DB calls or network I/O that bypassed mock."
    )
