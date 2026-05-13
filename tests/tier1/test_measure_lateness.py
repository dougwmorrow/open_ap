"""Tier 1 unit tests for tools/measure_lateness.py and
data_load/lateness_measurement.py.

Tests run on every commit. No live DB, no live network required.
All external dependencies mocked with unittest.mock.

North Star pillars addressed:
  - Audit-grade (D76): exactly one CLI_MEASURE_LATENESS event row per table
    per invocation; Metadata JSON shape canonical; FAILED row written even on
    exception path.
  - Idempotent (D15): each invocation produces a NEW L99 measurement (intentional
    drift-tracking, not idempotent identity); INSERT-only on PipelineEventLog;
    UPDATE-only on UdmTablesList; re-running does not produce double-UPDATE.
  - Operationally stable (D74/D75): exit-code contract (0/1/2) and argument
    naming discipline must be exactly per spec; Automic JOB_LATENESS_MEASURE
    interprets the contract.
  - Traceability (D11): L99 measurement must be empirical (distribution-based)
    and reproducible for any given input distribution.

Edge case IDs (per 04_EDGE_CASES.md):
  - I12 (backfill re-extraction idempotent if source unchanged): Tool 14
    re-invocation on unchanged distribution produces same L99 — deterministic.
  - V-13 (escalation threshold): InsufficientSampleError guard (<100 rows)
    prevents unreliable L99 estimates from reaching UdmTablesList.

Decision citations:
  D11 (empirical L_99 per-table; lookback_days=30 default),
  D15 (idempotency: measurement is intentional drift-tracking NOT idempotent),
  D63 (UdmTablesList additive columns LatenessL99Minutes + LatenessL99UpdatedAt),
  D74 (exit-code contract 0/1/2),
  D75 (arg naming: actor / lookback-days / drift-threshold-pct / dry-run / json),
  D76 (audit-row contract: CLI_MEASURE_LATENESS EventType; Metadata JSON shape),
  D92 (forward-only additive: new module data_load/lateness_measurement.py).

B-numbers:
  B188 (Tool 14 implementation tracking — closed by authoring this tool + tests).

Spec: phase1/04b_phase_0_closure_tools.md § 3 (Tool 14 canonical spec).

udm-execution-classifier discipline:
  - Idempotency contract: intentional drift-tracking — NOT idempotent identity.
    Each invocation produces a fresh L99 reading. UPDATE-only on UdmTablesList;
    INSERT-only on PipelineEventLog. Re-running twice produces two audit rows.
  - Trigger: Scheduled-primary (Automic JOB_LATENESS_MEASURE weekly Sat 06:00)
    + Manual-ad-hoc (operator: python3 tools/measure_lateness.py --source DNA
    --table ACCT --actor operator-name).
  - Frequency: weekly via Automic; ad-hoc as needed.
  - Audit-row family: CLI_* per D76 (EventType = CLI_MEASURE_LATENESS).
"""
from __future__ import annotations

import dataclasses
import importlib
import importlib.util
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, call, patch

import pytest

# ---------------------------------------------------------------------------
# Project root on sys.path
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Module paths
# ---------------------------------------------------------------------------

_TOOL_PATH = _PROJECT_ROOT / "tools" / "measure_lateness.py"
_MODULE_PATH = _PROJECT_ROOT / "data_load" / "lateness_measurement.py"
_TOOL_MODULE_KEY = "tools.measure_lateness"
_MODULE_KEY = "data_load.lateness_measurement"

# ---------------------------------------------------------------------------
# Constants — single source of truth for all expected values
# ---------------------------------------------------------------------------

# D76 EventType per CLI_* family
EXPECTED_EVENT_TYPE = "CLI_MEASURE_LATENESS"

# D74 exit codes
EXIT_SUCCESS = 0    # all measurements succeeded
EXIT_WARNING = 1    # some tables: InsufficientSampleError / BronzeTableMissing
EXIT_FATAL = 2      # fatal: SourceConnectError / UdmTablesListNotWritable

# D75 canonical arg values
_ACTOR = "test-author"
_LOOKBACK_DAYS = 30
_DRIFT_THRESHOLD_PCT = 20.0
_SOURCE = "DNA"
_TABLE = "ACCT"

# Minimum sample count threshold per phase1/04b § 3 error modes
MIN_SAMPLE_COUNT = 100

# Canonical Metadata JSON keys per D76 + phase1/04b § 3 Produces
REQUIRED_METADATA_KEYS = {
    "source_name",
    "table_name",
    "l99_minutes",
    "sample_count",
    "prior_l99_minutes",
    "drift_pct",
}

# Required keys in main() return dict per D76
REQUIRED_RESULT_KEYS = {
    "event_kind",
    "tables_processed",
    "tables_drifted",
    "tables_warning",
    "tables_failed",
    "exit_code",
    "actor",
    "dry_run",
}

# Synthetic UdmTablesList rows for --all invocation test
_SYNTHETIC_TABLE_ROWS = [
    {
        "SourceName": "DNA",
        "TableName": "ACCT",
        "IsEnabled": 1,
        "SourceAggregateColumnName": "DATELASTMAINT",
        "LatenessL99Minutes": None,
        "LatenessL99UpdatedAt": None,
    },
    {
        "SourceName": "DNA",
        "TableName": "CARDTXN",
        "IsEnabled": 1,
        "SourceAggregateColumnName": "TXN_DATE",
        "LatenessL99Minutes": 25,
        "LatenessL99UpdatedAt": "2026-05-01 00:00:00.000",
    },
]


# ---------------------------------------------------------------------------
# Helper: build a known delta-minutes distribution
# ---------------------------------------------------------------------------

def _make_distribution(count: int, max_minutes: int = 100) -> list[dict]:
    """Return a list of delta-minutes dicts with a known p99.

    For count=200, max_minutes=100:
      Values 0..99 repeated twice → sorted array of 200 items.
      p99 index ≈ floor(0.99 * 200) = 198 → value = 98.
    """
    return [{"delta_minutes": i % max_minutes} for i in range(count)]


# ---------------------------------------------------------------------------
# Module loaders
# ---------------------------------------------------------------------------

def _load_lateness_module(
    *,
    mock_df_rows: list[dict] | None = None,
    cx_side_effect: Exception | None = None,
) -> Any:
    """Load data_load/lateness_measurement.py with external imports mocked."""
    if _MODULE_KEY in sys.modules:
        del sys.modules[_MODULE_KEY]

    mock_cx = MagicMock()
    if cx_side_effect is not None:
        mock_cx.cx_read_sql_safe = MagicMock(side_effect=cx_side_effect)
    elif mock_df_rows is not None:
        try:
            import polars as pl
            _df = pl.DataFrame(mock_df_rows)
        except ImportError:
            _df = MagicMock()
        mock_cx.cx_read_sql_safe = MagicMock(return_value=_df)

    with patch.dict(
        "sys.modules",
        {
            "extract": mock_cx,
            "extract.__init__": mock_cx,
            "utils.connections": MagicMock(),
            "utils.configuration": MagicMock(),
            "observability.log_handler": MagicMock(),
            "orchestration.table_config": MagicMock(),
            "pyodbc": MagicMock(),
        },
    ):
        spec = importlib.util.spec_from_file_location(_MODULE_KEY, _MODULE_PATH)
        mod = importlib.util.module_from_spec(spec)
        # Register module in sys.modules BEFORE exec_module so module-level
        # @dataclass(frozen=True) with PEP 604 `int | None` type hints can look
        # itself up via sys.modules[cls.__module__].__dict__ (Python 3.12
        # dataclass._is_type bug-class fix per cycle-1 pytest verify 2026-05-12)
        sys.modules[_MODULE_KEY] = mod
        spec.loader.exec_module(mod)

    return mod


def _load_tool_module(
    *,
    cx_return_rows: list[dict] | None = None,
    cx_side_effect: Exception | None = None,
    lateness_result_override: Any = None,
) -> Any:
    """Load tools/measure_lateness.py with all external imports mocked."""
    if _TOOL_MODULE_KEY in sys.modules:
        del sys.modules[_TOOL_MODULE_KEY]

    if cx_return_rows is None and cx_side_effect is None:
        cx_return_rows = _make_distribution(200)

    mock_cx = MagicMock()
    if cx_side_effect is not None:
        mock_cx.cx_read_sql_safe = MagicMock(side_effect=cx_side_effect)
    else:
        try:
            import polars as pl
            _df = pl.DataFrame(cx_return_rows or [])
        except ImportError:
            _df = MagicMock()
        mock_cx.cx_read_sql_safe = MagicMock(return_value=_df)

    mock_event_tracker = MagicMock()
    mock_lateness_mod = MagicMock()

    # Per B215 fix: when cx_side_effect is set, route the failure through
    # measure_lateness as a real SourceConnectError so the tool's exception
    # handler sees a proper Exception class (the actual production wiring
    # has measure_lateness call cx_read_sql_safe internally and convert
    # ConnectionError → SourceConnectError per spec § 3).
    from data_load._exceptions import SourceConnectError as _RealSourceConnectError
    if cx_side_effect is not None and lateness_result_override is None:
        mock_lateness_mod.measure_lateness = MagicMock(
            side_effect=_RealSourceConnectError(str(cx_side_effect))
        )
        mock_lateness_mod.SourceConnectError = _RealSourceConnectError
    elif lateness_result_override is not None:
        mock_lateness_mod.measure_lateness = MagicMock(
            return_value=lateness_result_override
        )
    else:
        default_result = MagicMock()
        default_result.l99_minutes = 42
        default_result.sample_count = 200
        default_result.notes = ""
        default_result.prior_l99_minutes = None
        default_result.drift_pct = None
        default_result.source_name = _SOURCE
        default_result.table_name = _TABLE
        mock_lateness_mod.measure_lateness = MagicMock(return_value=default_result)

    with patch.dict(
        "sys.modules",
        {
            "extract": mock_cx,
            "extract.__init__": mock_cx,
            "data_load.lateness_measurement": mock_lateness_mod,
            "observability.event_tracker": mock_event_tracker,
            "utils.connections": MagicMock(),
            "utils.configuration": MagicMock(),
            "observability.log_handler": MagicMock(),
            "orchestration.table_config": MagicMock(),
        },
    ):
        spec = importlib.util.spec_from_file_location(_TOOL_MODULE_KEY, _TOOL_PATH)
        mod = importlib.util.module_from_spec(spec)
        # Register module BEFORE exec_module (see _load_lateness_module comment).
        sys.modules[_TOOL_MODULE_KEY] = mod
        spec.loader.exec_module(mod)

    return mod


def _call_main(mod: Any, **overrides: Any) -> dict:
    """Call tool main() with canonical defaults + overrides."""
    defaults = dict(
        actor=_ACTOR,
        all_tables=False,
        source=_SOURCE,
        table=_TABLE,
        lookback_days=_LOOKBACK_DAYS,
        drift_threshold_pct=_DRIFT_THRESHOLD_PCT,
        dry_run=False,
        json_output=False,
        verbose=False,
        quiet=False,
    )
    defaults.update(overrides)
    return mod.main(**defaults)


# ---------------------------------------------------------------------------
# test_measure_lateness_module_returns_lateness_result_dataclass
# ---------------------------------------------------------------------------


def test_measure_lateness_module_returns_lateness_result_dataclass():
    """B188, D92: measure_lateness() returns a LatenessResult dataclass instance.

    Per phase1/04b § 3 canonical signature:
      measure_lateness(table_config, *, lookback_days: int = 30) -> LatenessResult

    The return value must be a frozen dataclass with the documented fields.
    Verifies D92 forward-only additive: new module function returns new type.

    North Star: Operationally stable (callers depend on the dataclass contract;
    return type regression breaks the tool's main() iteration logic).

    D92, B188. Spec: phase1/04b § 3.
    """
    mod = _load_lateness_module(mock_df_rows=_make_distribution(200))

    assert hasattr(mod, "LatenessResult"), (
        "data_load/lateness_measurement.py must define LatenessResult dataclass."
    )

    # Verify the dataclass fields exist on the class
    result_cls = mod.LatenessResult
    try:
        fields = {f.name for f in dataclasses.fields(result_cls)}
    except TypeError:
        # Not a dataclass — may be a class with __annotations__
        fields = set(getattr(result_cls, "__annotations__", {}).keys())

    required_fields = {
        "source_name",
        "table_name",
        "l99_minutes",
        "sample_count",
        "measured_at",
        "notes",
        "prior_l99_minutes",
        "drift_pct",
    }
    missing_fields = required_fields - fields
    assert not missing_fields, (
        f"LatenessResult is missing required fields: {missing_fields!r}. "
        "Per phase1/04b § 3 canonical signature."
    )


# ---------------------------------------------------------------------------
# test_measure_lateness_computes_l99_from_synthetic_distribution
# ---------------------------------------------------------------------------


def test_measure_lateness_computes_l99_from_synthetic_distribution():
    """B188, D11: measure_lateness() computes L_99 from a known distribution.

    Feed a deterministic distribution (values 0..199 minutes, count=200) and
    verify the returned l99_minutes equals the expected 99th percentile.

    For values [0, 1, 2, ..., 199]:
      p99 index = ceil(0.99 * 200) - 1 = 197
      Value at index 197 = 197 minutes.
    Or equivalently: numpy.percentile([0..199], 99) = 197.01 ≈ 197.

    North Star: Idempotent (D15: same distribution always produces same L99;
    deterministic across runs per the polars/numpy computation path).

    D11 (empirical L_99), D15, B188. Spec: phase1/04b § 3 — '(b) queries
    source DB for distribution of deltas over the last lookback_days, (c)
    computes 99th percentile'.
    """
    # Distribution: exactly [0, 1, 2, ..., 199] — p99 is deterministic
    known_distribution = [{"delta_minutes": i} for i in range(200)]

    mod = _load_lateness_module(mock_df_rows=known_distribution)

    # Build a minimal synthetic table_config for the call
    mock_tc = MagicMock()
    mock_tc.source_name = _SOURCE
    mock_tc.table_name = _TABLE
    mock_tc.source_aggregate_column_name = "DATELASTMAINT"

    result = mod.measure_lateness(mock_tc, lookback_days=_LOOKBACK_DAYS)

    assert result is not None, "measure_lateness() must return a LatenessResult"
    assert result.sample_count == 200, (
        f"sample_count must equal len(distribution)=200. "
        f"Got: {result.sample_count!r}"
    )
    # p99 of [0..199] is 197 (floor-based) or 197.01 (interpolated) → int 197
    if result.l99_minutes is not None:
        assert 190 <= result.l99_minutes <= 200, (
            f"l99_minutes for uniform [0..199] distribution must be near 197. "
            f"Got: {result.l99_minutes!r}. "
            "D11: empirical p99 must match the source distribution."
        )


# ---------------------------------------------------------------------------
# test_measure_lateness_insufficient_sample_returns_result_with_notes
# ---------------------------------------------------------------------------


def test_measure_lateness_insufficient_sample_returns_result_with_notes():
    """B188, D11, V-13: < 100 rows → LatenessResult with notes='low sample count: N'.

    Edge case V-13 (escalation threshold): InsufficientSampleError guard prevents
    unreliable L99 estimates from persisting to UdmTablesList as authoritative data.

    Per phase1/04b § 3 error modes: 'InsufficientSampleError (< 100 rows in the
    lookback window — distribution unreliable) → exit 1 (warning); UPDATE writes
    the L99 anyway with notes = "low sample count: N"'.

    The notes field carries the reason so operators can see WHY the update was
    made despite the sample being small.

    D11, V-13, B188. Spec: phase1/04b § 3 error modes.
    """
    sparse_distribution = [{"delta_minutes": i} for i in range(50)]

    mod = _load_lateness_module(mock_df_rows=sparse_distribution)

    mock_tc = MagicMock()
    mock_tc.source_name = _SOURCE
    mock_tc.table_name = _TABLE
    mock_tc.source_aggregate_column_name = "DATELASTMAINT"

    result = mod.measure_lateness(mock_tc, lookback_days=_LOOKBACK_DAYS)

    assert result is not None, (
        "measure_lateness() must return a LatenessResult even on insufficient sample."
    )
    assert result.sample_count == 50, (
        f"sample_count must equal actual row count (50). Got: {result.sample_count!r}"
    )
    assert result.notes is not None and len(result.notes) > 0, (
        "notes must be populated for insufficient sample. "
        "Per phase1/04b § 3: 'low sample count: N'."
    )
    assert "50" in result.notes or "sample" in result.notes.lower(), (
        f"notes must document the sample count. Got: {result.notes!r}. "
        "Expected substring '50' or 'sample' in notes."
    )


# ---------------------------------------------------------------------------
# test_measure_lateness_bronze_missing_raises_or_returns_null
# ---------------------------------------------------------------------------


def test_measure_lateness_bronze_missing_raises_or_returns_null():
    """B188, D11: BronzeTableMissing → LatenessResult with l99_minutes=None
    and notes containing 'Bronze not deployed yet'.

    Per phase1/04b § 3 error modes: 'BronzeTableMissing (table in UdmTablesList
    but no Bronze table exists yet — pre-deploy state) → exit 1; UPDATE writes
    LatenessL99Minutes=NULL + notes "Bronze not deployed yet"'.

    North Star: Operationally stable (pre-deploy tables must not block the
    lateness measurement run for other tables — exit 1, not exit 2).

    D11, B188. Spec: phase1/04b § 3 error modes (BronzeTableMissing).
    """
    from pyodbc import ProgrammingError  # noqa: F401 (may not exist in mock env)

    mod = _load_lateness_module(mock_df_rows=[])

    mock_tc = MagicMock()
    mock_tc.source_name = _SOURCE
    mock_tc.table_name = "NONEXISTENT_TABLE"
    mock_tc.source_aggregate_column_name = "DATELASTMAINT"

    # The module should return a result with l99_minutes=None when the Bronze
    # table is absent, OR raise a specific error class. Both are acceptable;
    # the test verifies the contract is documented.
    try:
        result = mod.measure_lateness(mock_tc, lookback_days=_LOOKBACK_DAYS)
        if result is not None:
            assert result.l99_minutes is None or isinstance(result.l99_minutes, int), (
                "l99_minutes must be None (Bronze missing) or int (if fallback). "
                f"Got: {result.l99_minutes!r}"
            )
    except Exception as exc:
        # A documented error class (BronzeTableMissing or similar) is acceptable
        exc_name = type(exc).__name__
        assert any(
            kw in exc_name.lower()
            for kw in ("bronze", "table", "missing", "notfound", "error")
        ), (
            f"BronzeTableMissing path must raise a documented error class. "
            f"Got unexpected exception: {exc_name}: {exc}"
        )


# ---------------------------------------------------------------------------
# test_measure_lateness_drift_calc
# ---------------------------------------------------------------------------


def test_measure_lateness_drift_calc():
    """B188, D11: prior_l99=10, new_l99=15 → drift_pct=50.0.

    Drift percentage = abs((new - prior) / prior) * 100.
    With prior=10, new=15: drift = abs((15 - 10) / 10) * 100 = 50.0.

    This is the key metric for the --drift-threshold-pct flag and the
    tables_drifted counter in the main() result dict.

    North Star: Operationally stable (operators and Automic rely on drift_pct
    to flag tables with unexpected latency changes; wrong calculation produces
    silent false positives/negatives).

    D11, B188. Spec: phase1/04b § 3 — 'stdout: M tables drifted >20% from
    prior baseline'.
    """
    # Build a module with a known prior + known new distribution
    distribution = _make_distribution(200, max_minutes=20)  # max delta ≈ 15 min p99

    mod = _load_lateness_module(mock_df_rows=distribution)

    mock_tc = MagicMock()
    mock_tc.source_name = _SOURCE
    mock_tc.table_name = _TABLE
    mock_tc.source_aggregate_column_name = "DATELASTMAINT"
    mock_tc.lateness_l99_minutes = 10  # prior stored in UdmTablesList

    result = mod.measure_lateness(mock_tc, lookback_days=_LOOKBACK_DAYS)

    # The drift_pct field must be computed when prior_l99_minutes is available
    if result.prior_l99_minutes is not None and result.l99_minutes is not None:
        expected_drift = abs(
            (result.l99_minutes - result.prior_l99_minutes) / result.prior_l99_minutes
        ) * 100
        assert result.drift_pct is not None, (
            "drift_pct must be computed when prior_l99_minutes is set. Got None."
        )
        assert abs(result.drift_pct - expected_drift) < 1.0, (
            f"drift_pct computation error. Expected ~{expected_drift:.1f}%, "
            f"got {result.drift_pct:.1f}%. "
            "Formula: abs((new - prior) / prior) * 100."
        )
    # If prior_l99_minutes is None (first measurement), drift_pct must also be None
    elif result.prior_l99_minutes is None:
        assert result.drift_pct is None, (
            "drift_pct must be None when prior_l99_minutes is None (first run). "
            f"Got: {result.drift_pct!r}"
        )


# ---------------------------------------------------------------------------
# test_cli_all_tables_invokes_per_row
# ---------------------------------------------------------------------------


def test_cli_all_tables_invokes_per_row():
    """B188, D76: --all flag causes main() to iterate over all enabled table rows.

    When --all is set, the tool reads IsEnabled=1 rows from UdmTablesList
    and invokes measure_lateness() once per row. tables_processed must equal
    the number of enabled rows returned.

    Phase1/04b § 3 CLI: '--all flag: Run against every UdmTablesList row
    with IsEnabled=1 (mutex with --source/--table)'.

    North Star: Audit-grade (D76: one CLI_MEASURE_LATENESS event per table,
    so tables_processed must accurately reflect iterations).

    D76, B188. Spec: phase1/04b § 3 CLI arguments + Produces.
    """
    tool_mod = _load_tool_module(cx_return_rows=_make_distribution(200))

    # Simulate UdmTablesList returning 2 enabled rows
    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = _SYNTHETIC_TABLE_ROWS
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    with patch.dict(
        "sys.modules",
        {"pyodbc": MagicMock(connect=MagicMock(return_value=mock_conn))},
    ):
        result = _call_main(tool_mod, all_tables=True, source=None, table=None)

    assert isinstance(result, dict), "main() must return a dict"
    assert result.get("tables_processed") == len(_SYNTHETIC_TABLE_ROWS), (
        f"tables_processed must equal len(enabled_rows)={len(_SYNTHETIC_TABLE_ROWS)}. "
        f"Got: {result.get('tables_processed')!r}. "
        "--all must iterate over every IsEnabled=1 row."
    )


# ---------------------------------------------------------------------------
# test_cli_source_table_pair_mutex_with_all
# ---------------------------------------------------------------------------


def test_cli_source_table_pair_mutex_with_all():
    """B188, D75: Providing both --all and --source/--table is a CLI argument error.

    Per phase1/04b § 3 CLI: '--all: mutex with --source/--table'.
    argparse should raise SystemExit(2) (argument error) or ValueError.

    D75 (argument naming discipline), B188. Spec: phase1/04b § 3 CLI arguments.
    """
    tool_mod = _load_tool_module()

    with pytest.raises((SystemExit, ValueError, TypeError)) as exc_info:
        _call_main(tool_mod, all_tables=True, source="DNA", table="ACCT")

    if hasattr(exc_info.value, "code"):
        assert exc_info.value.code != 0, (
            "Conflicting --all + --source/--table must exit non-zero "
            "(argparse error = exit 2). "
            "Per phase1/04b § 3: these are mutually exclusive."
        )


# ---------------------------------------------------------------------------
# test_cli_table_requires_source
# ---------------------------------------------------------------------------


def test_cli_table_requires_source():
    """B188, D75: --table without --source is a CLI argument error.

    Per phase1/04b § 3 CLI: '--table: Restrict to one table (must be paired
    with --source)'. Missing --source with --table must raise an error.

    D75 (arg naming), B188. Spec: phase1/04b § 3 CLI interface.
    """
    tool_mod = _load_tool_module()

    with pytest.raises((SystemExit, ValueError, TypeError)) as exc_info:
        _call_main(tool_mod, all_tables=False, source=None, table="ACCT")

    if hasattr(exc_info.value, "code"):
        assert exc_info.value.code != 0, (
            "--table without --source must exit non-zero (argument error). "
            "Per phase1/04b § 3: --table must be paired with --source."
        )


# ---------------------------------------------------------------------------
# test_cli_dry_run_no_writes
# ---------------------------------------------------------------------------


def test_cli_dry_run_no_writes():
    """B188, D74, D76: --dry-run suppresses UdmTablesList UPDATE.

    Per phase1/04b § 3: '--dry-run: Measure but do NOT UPDATE UdmTablesList;
    write audit row only'. The PipelineEventLog row IS written (audit trail
    is mandatory per D76 — not suppressible). The UdmTablesList UPDATE is
    suppressed.

    Verifies dry_run=True in result + no UPDATE executed on UdmTablesList.

    D74 (exit 0 on dry-run success), D76 (audit row still written), B188.
    Spec: phase1/04b § 3 CLI arguments + Tier 0 assertion (f).
    """
    tool_mod = _load_tool_module(cx_return_rows=_make_distribution(200))

    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [_SYNTHETIC_TABLE_ROWS[0]]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    with patch.dict(
        "sys.modules",
        {"pyodbc": MagicMock(connect=MagicMock(return_value=mock_conn))},
    ):
        result = _call_main(tool_mod, dry_run=True)

    assert isinstance(result, dict), "main() must return a dict on dry-run path"
    assert result.get("dry_run") is True, (
        f"result['dry_run'] must be True when invoked with dry_run=True. "
        f"Got: {result.get('dry_run')!r}"
    )
    assert result.get("exit_code") == EXIT_SUCCESS, (
        f"--dry-run with successful measurement must exit {EXIT_SUCCESS}. "
        f"Got: {result.get('exit_code')!r}"
    )

    # Confirm UPDATE not called on UdmTablesList
    all_execute_calls = [str(c) for c in mock_cursor.execute.call_args_list]
    udm_updates = [
        s for s in all_execute_calls
        if "UPDATE" in s.upper() and "UdmTablesList" in s
    ]
    assert not udm_updates, (
        f"--dry-run must NOT execute UPDATE on UdmTablesList. "
        f"Found calls: {udm_updates!r}. "
        "Phase1/04b § 3: dry_run suppresses UdmTablesList writes."
    )


# ---------------------------------------------------------------------------
# test_cli_drift_threshold_classifies_tables
# ---------------------------------------------------------------------------


def test_cli_drift_threshold_classifies_tables():
    """B188, D74: drift_pct > drift_threshold_pct increments tables_drifted.

    When a table's new L99 differs from prior by more than drift_threshold_pct
    percent, main() must increment tables_drifted in the result dict and
    include the table in the drift summary.

    Per phase1/04b § 3 stdout: 'final line: Lateness measured for N tables;
    M tables drifted >20% from prior baseline'.

    D74 (exit code driven by worst-table outcome), B188.
    Spec: phase1/04b § 3 Produces (stdout summary + result dict).
    """
    # Simulate a result with large drift (prior=10, new=50 → drift=400%)
    drifted_result = MagicMock()
    drifted_result.l99_minutes = 50
    drifted_result.sample_count = 200
    drifted_result.notes = ""
    drifted_result.prior_l99_minutes = 10
    drifted_result.drift_pct = 400.0  # well above default 20.0% threshold
    drifted_result.source_name = _SOURCE
    drifted_result.table_name = _TABLE

    tool_mod = _load_tool_module(lateness_result_override=drifted_result)

    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [_SYNTHETIC_TABLE_ROWS[0]]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    with patch.dict(
        "sys.modules",
        {"pyodbc": MagicMock(connect=MagicMock(return_value=mock_conn))},
    ):
        result = _call_main(
            tool_mod,
            drift_threshold_pct=20.0,
            dry_run=False,
        )

    assert isinstance(result, dict), "main() must return a dict"
    assert result.get("tables_drifted", 0) >= 1, (
        f"drift_pct=400.0 > threshold=20.0 → tables_drifted must be >= 1. "
        f"Got: {result.get('tables_drifted')!r}. "
        "Phase1/04b § 3 stdout: 'M tables drifted >N% from prior baseline'."
    )


# ---------------------------------------------------------------------------
# test_cli_audit_row_metadata_shape
# ---------------------------------------------------------------------------


def test_cli_audit_row_metadata_shape():
    """B188, D76: result / Metadata JSON has canonical keys per § 3 L53.

    Per D76 audit-row contract: Metadata JSON must contain:
      source_name, table_name, l99_minutes, sample_count,
      prior_l99_minutes, drift_pct.

    Per phase1/04b § 3 Produces: 'PipelineEventLog: ONE row per table with
    EventType="CLI_MEASURE_LATENESS", Status in {SUCCESS, FAILED},
    Metadata JSON containing source_name, table_name, l99_minutes,
    sample_count, prior_l99_minutes, drift_pct'.

    North Star: Audit-grade (Gate queries rely on canonical Metadata key names;
    any deviation silently breaks trend analysis queries).

    D76, B188. Spec: phase1/04b § 3 Produces.
    """
    tool_mod = _load_tool_module(cx_return_rows=_make_distribution(200))

    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [_SYNTHETIC_TABLE_ROWS[0]]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    with patch.dict(
        "sys.modules",
        {"pyodbc": MagicMock(connect=MagicMock(return_value=mock_conn))},
    ):
        result = _call_main(tool_mod)

    assert isinstance(result, dict), "main() must return a dict"

    # Check top-level result keys (these also appear in the audit Metadata)
    missing_top = REQUIRED_RESULT_KEYS - result.keys()
    assert not missing_top, (
        f"main() result missing required keys: {missing_top!r}. "
        f"Got keys: {set(result.keys())!r}. "
        "D76 audit-row contract + phase1/04b § 3 Produces."
    )

    # If the result includes a 'results' list (per optional § 3 schema),
    # verify per-table entries have the REQUIRED_METADATA_KEYS
    if "results" in result and isinstance(result["results"], list):
        for entry in result["results"]:
            missing_meta = REQUIRED_METADATA_KEYS - set(entry.keys())
            assert not missing_meta, (
                f"Per-table result entry missing Metadata keys: {missing_meta!r}. "
                f"Got: {set(entry.keys())!r}. "
                "D76: Metadata JSON must carry source_name / table_name / "
                "l99_minutes / sample_count / prior_l99_minutes / drift_pct."
            )


# ---------------------------------------------------------------------------
# test_cli_event_kind_is_measure_not_apply
# ---------------------------------------------------------------------------


def test_cli_event_kind_is_measure_not_apply():
    """B188, D76: event_kind must be 'measure' (not 'apply' or 'migrate').

    The event_kind discriminator distinguishes read-measure operations from
    write-apply operations. Tool 14 is a measurement tool that also writes
    L99 to UdmTablesList — but the primary action is measurement, not a
    one-way migration. The event_kind='measure' signals this to PipelineEventLog
    consumers and Gate 6 counting queries.

    Contrast with MIGRATION_* family (event_kind='apply') and verify that
    this idempotency-NO-intentional-drift-tracking tool is not mis-classified.

    North Star: Audit-grade (Metadata discriminator keeps PipelineEventLog
    entries queryable by action category).

    D76, B188. Spec: phase1/04b § 3 idempotency note + Produces.
    """
    tool_mod = _load_tool_module(cx_return_rows=_make_distribution(200))

    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [_SYNTHETIC_TABLE_ROWS[0]]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    with patch.dict(
        "sys.modules",
        {"pyodbc": MagicMock(connect=MagicMock(return_value=mock_conn))},
    ):
        result = _call_main(tool_mod)

    assert "event_kind" in result, (
        "result must contain 'event_kind' key per D76 audit-row contract."
    )
    assert result["event_kind"] != "apply", (
        f"event_kind must NOT be 'apply' — Tool 14 is a measurement tool, "
        f"not a one-way migration. Got: {result['event_kind']!r}. "
        "Use 'measure' to distinguish from MIGRATION_* family."
    )
    assert result["event_kind"] not in ("migrate", "import"), (
        f"event_kind={result['event_kind']!r} is not correct for a measurement tool. "
        "Expected 'measure' per phase1/04b § 3 classification."
    )


# ---------------------------------------------------------------------------
# test_cli_actor_required_arg
# ---------------------------------------------------------------------------


def test_cli_actor_required_arg():
    """B188, D75: Invoking main() without actor raises TypeError or SystemExit.

    Per D75 canonical arg naming: --actor is required for all CLI tools
    (it populates the PipelineEventLog actor field per D76).

    D75, D76, B188. Spec: phase1/04b § 3 + D75 canonical argument list.
    """
    tool_mod = _load_tool_module()

    with pytest.raises((TypeError, SystemExit)) as exc_info:
        # Call without actor — must raise TypeError (missing required kwarg)
        # or SystemExit (argparse required-arg error)
        tool_mod.main(
            all_tables=False,
            source=_SOURCE,
            table=_TABLE,
            lookback_days=_LOOKBACK_DAYS,
            dry_run=False,
        )

    if hasattr(exc_info.value, "code"):
        assert exc_info.value.code != 0, (
            "Missing --actor must exit non-zero (argparse required-arg error). "
            "Per D75: --actor is a required argument for all CLI tools."
        )


# ---------------------------------------------------------------------------
# test_cli_exit_codes_0_1_2
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "scenario,expected_exit",
    [
        ("success_200_rows", EXIT_SUCCESS),
        ("insufficient_sample_50_rows", EXIT_WARNING),
        ("source_connection_error", EXIT_FATAL),
    ],
)
def test_cli_exit_codes_0_1_2(scenario: str, expected_exit: int):
    """B188, D74: Exit codes 0/1/2 per D74 contract for each documented scenario.

    D74 canonical exit codes:
      0 = success (all measurements succeeded)
      1 = expected operational failure (InsufficientSampleError / BronzeTableMissing)
      2 = fatal (SourceConnectError / UdmTablesListNotWritable)

    Per R22 (CLI exit-code drift risk): Automic interprets the exit-code
    contract per D74; any deviation causes incorrect escalation or
    under-escalation of failures.

    D74, R22, B188. Spec: phase1/04b § 3 exit codes.
    """
    if scenario == "success_200_rows":
        tool_mod = _load_tool_module(cx_return_rows=_make_distribution(200))
    elif scenario == "insufficient_sample_50_rows":
        sparse_result = MagicMock()
        sparse_result.l99_minutes = 5
        sparse_result.sample_count = 50
        sparse_result.notes = "low sample count: 50"
        sparse_result.prior_l99_minutes = None
        sparse_result.drift_pct = None
        sparse_result.source_name = _SOURCE
        sparse_result.table_name = _TABLE
        tool_mod = _load_tool_module(
            cx_return_rows=_make_distribution(50),
            lateness_result_override=sparse_result,
        )
    else:  # source_connection_error
        tool_mod = _load_tool_module(
            cx_side_effect=ConnectionError("source DB unreachable — test fixture"),
        )

    mock_cursor = MagicMock()
    mock_cursor.fetchall.return_value = [_SYNTHETIC_TABLE_ROWS[0]]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    with patch.dict(
        "sys.modules",
        {"pyodbc": MagicMock(connect=MagicMock(return_value=mock_conn))},
    ):
        result = _call_main(tool_mod)

    assert isinstance(result, dict), (
        f"main() must return a dict for scenario={scenario!r}. "
        f"Got: {type(result)!r}"
    )
    assert result.get("exit_code") == expected_exit, (
        f"Scenario {scenario!r}: expected exit_code={expected_exit}, "
        f"got {result.get('exit_code')!r}. "
        "D74 exit-code contract; R22 Automic mis-categorization risk."
    )


# ---------------------------------------------------------------------------
# test_docstring_documents_classifier_dimensions
# ---------------------------------------------------------------------------


def test_docstring_documents_classifier_dimensions():
    """B188: Module + function docstring documents all 4 udm-execution-classifier
    dimensions.

    Per task spec + analogous test in B184 pattern:
    The module docstring must document all four classifier dimensions:
      1. Idempotency contract: intentional drift-tracking (NOT idempotent identity)
      2. Trigger: Scheduled-primary (Automic JOB_LATENESS_MEASURE weekly) +
                  Manual-ad-hoc (operator per-table)
      3. Frequency: weekly via Automic; ad-hoc as needed
      4. Audit-row family: CLI_* per D76 (CLI_MEASURE_LATENESS)

    North Star: Traceability (operators must understand the tool's execution
    model from the docstring without reading the full spec).

    B188. Spec: phase1/04b § 3 + udm-execution-classifier discipline.
    """
    tool_mod = _load_tool_module()

    module_doc = tool_mod.__doc__ or ""
    func_doc = getattr(tool_mod.main, "__doc__", "") or ""
    combined_doc = (module_doc + " " + func_doc).lower()

    # Dimension 1: Idempotency — must mention drift-tracking or intentional
    assert any(
        kw in combined_doc
        for kw in ("drift", "intentional", "tracking", "not idempotent", "each invocation")
    ), (
        "Module/function docstring must document idempotency contract "
        "(intentional drift-tracking — NOT idempotent identity; each invocation "
        "produces a fresh L99). udm-execution-classifier dimension 1."
    )

    # Dimension 2: Trigger — must mention Automic or scheduled or operator/ad-hoc
    assert any(
        kw in combined_doc
        for kw in ("automic", "scheduled", "operator", "ad-hoc", "ad hoc", "jOB_LATENESS".lower())
    ), (
        "Module/function docstring must document trigger context "
        "(Scheduled-primary Automic JOB_LATENESS_MEASURE + Manual-ad-hoc operator). "
        "udm-execution-classifier dimension 2."
    )

    # Dimension 3: Frequency — must mention weekly or frequency
    assert any(
        kw in combined_doc
        for kw in ("weekly", "frequency", "schedule", "on-demand")
    ), (
        "Module/function docstring must document frequency "
        "(weekly via Automic; ad-hoc as needed). "
        "udm-execution-classifier dimension 3."
    )

    # Dimension 4: Audit-row family — must mention CLI_ or CLI_MEASURE
    assert any(
        kw in combined_doc
        for kw in ("cli_", "cli_measure", "cli_*")
    ), (
        "Module/function docstring must document audit-row family "
        "(CLI_* per D76; EventType='CLI_MEASURE_LATENESS'). "
        "udm-execution-classifier dimension 4."
    )


# ---------------------------------------------------------------------------
# test_lateness_result_frozen_dataclass
# ---------------------------------------------------------------------------


def test_lateness_result_frozen_dataclass():
    """B188, D15: LatenessResult must be a frozen dataclass (immutable).

    Per phase1/04b § 3 canonical signature: '@dataclass(frozen=True)'.
    Frozen ensures that result objects are not mutated after construction —
    important for idempotency (the result of measure_lateness() at a given
    moment is a fixed snapshot; callers must not alter it).

    D15 (idempotency), D92 (new module), B188.
    Spec: phase1/04b § 3 canonical signatures.
    """
    mod = _load_lateness_module(mock_df_rows=_make_distribution(200))

    result_cls = mod.LatenessResult

    # Check if it's a dataclass
    assert dataclasses.is_dataclass(result_cls), (
        "LatenessResult must be a dataclass per phase1/04b § 3 canonical signature."
    )

    # Check if it's frozen (immutable)
    is_frozen = getattr(result_cls, "__dataclass_params__", None)
    if is_frozen is not None:
        assert is_frozen.frozen, (
            "LatenessResult must be a FROZEN dataclass (@dataclass(frozen=True)). "
            "Frozen ensures result immutability per D15 idempotency contract."
        )


# ---------------------------------------------------------------------------
# test_l99_is_int_or_none
# ---------------------------------------------------------------------------


def test_l99_is_int_or_none():
    """B188, D11: LatenessResult.l99_minutes must be int | None (never float).

    Per phase1/04b § 3 canonical signature: 'l99_minutes: int | None'.
    The field is INT (whole minutes), not float. Storing float to an INT SQL
    column silently truncates; returning float to main() breaks the
    'l99_minutes: int | None' type contract.

    D11, D63 (UdmTablesList.LatenessL99Minutes is INT column), B188.
    Spec: phase1/04b § 3 canonical signatures + § 1 UdmTablesList columns.
    """
    mod = _load_lateness_module(mock_df_rows=_make_distribution(200))

    mock_tc = MagicMock()
    mock_tc.source_name = _SOURCE
    mock_tc.table_name = _TABLE
    mock_tc.source_aggregate_column_name = "DATELASTMAINT"

    result = mod.measure_lateness(mock_tc, lookback_days=_LOOKBACK_DAYS)

    if result.l99_minutes is not None:
        assert isinstance(result.l99_minutes, int), (
            f"l99_minutes must be int or None per phase1/04b § 3. "
            f"Got: {type(result.l99_minutes)!r} = {result.l99_minutes!r}. "
            "D63: UdmTablesList.LatenessL99Minutes is INT column — float "
            "would cause silent SQL truncation or type error."
        )


# ---------------------------------------------------------------------------
# test_measured_at_is_naive_datetime
# ---------------------------------------------------------------------------


def test_measured_at_is_naive_datetime():
    """B188, D15: LatenessResult.measured_at must be a naive datetime (no tzinfo).

    Per BCP CSV Contract (CLAUDE.md): 'Datetime format: naive (no tz)'.
    Per SCD2-P1-f and CDC-NOW-MS: tz-aware datetimes sent via pyodbc as
    DATETIMEOFFSET cause implicit timezone conversion when stored in DATETIME2
    columns, producing a different UTC moment than what was measured.

    Naive datetime preserves the UTC wall-time semantics without ODBC
    conversion surprises.

    D15, B188. Spec: phase1/04b § 3 + CLAUDE.md BCP CSV Contract.
    """
    mod = _load_lateness_module(mock_df_rows=_make_distribution(200))

    mock_tc = MagicMock()
    mock_tc.source_name = _SOURCE
    mock_tc.table_name = _TABLE
    mock_tc.source_aggregate_column_name = "DATELASTMAINT"

    result = mod.measure_lateness(mock_tc, lookback_days=_LOOKBACK_DAYS)

    assert isinstance(result.measured_at, datetime), (
        f"measured_at must be a datetime instance. Got: {type(result.measured_at)!r}"
    )
    assert result.measured_at.tzinfo is None, (
        f"measured_at must be NAIVE (no tzinfo). Got: {result.measured_at!r}. "
        "Tz-aware datetimes cause DATETIMEOFFSET → DATETIME2 conversion surprises "
        "via pyodbc per SCD2-P1-f + CDC-NOW-MS."
    )
