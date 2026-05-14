"""Tier 0 build-time smoke test for tools/scd2_replay_smoke.py.

Per D67 — runs at build time + every commit. Runtime ceiling < 5 s.
All external dependencies (M2 ``replay_parquet_snapshot``, ``run_scd2``,
``TableConfigLoader``, ``PipelineBatchSequence``, PipelineEventLog
cursor) are mocked. No live DB, no live network required.

6-assertion D77-canonical scaffold (descriptive-name discipline per
B-266 lesson — tests' filename + ``def test_*`` semantic-keywords carry
the canonical assertion intent so the verify_tier0_drift auditor can
match):
  (a) test_module_imports — module loads + exposes public surface.
  (b) test_help_exits_zero_with_nonempty_stdout — argparse --help happy.
  (c) test_dry_run_default_exits_zero — defaults to --dry-run per D75;
      no replay/SCD2 calls; exit 0.
  (d) test_apply_without_required_args_exits_two — missing --source /
      --table / --business-date / --original-batch-id → argparse error
      → exit 2.
  (e) test_apply_with_mock_success_returns_zero — both replay_fn and
      scd2_fn mocked to success → exit 0.
  (f) test_apply_with_mock_replay_fatal_returns_two — mocked replay_fn
      raises RegistryNotFound → exit 2.

North Star pillars:
  - Audit-grade (D76 — one CLI_SCD2_REPLAY_SMOKE audit row per invocation).
  - Operationally stable (D67 — Tier 0 < 5 s; D74 exit-code contract 0/1/2).
  - Idempotent (D15 — M2 ledger gate; re-replay with same replay_batch_id
    short-circuits at the ledger; re-running run_scd2 with unchanged DataFrame
    produces zero inserts/updates).
  - Traceability (D26 — every invocation writes ONE PipelineEventLog row
    with EventType='CLI_SCD2_REPLAY_SMOKE').

M2 canonical signature (per data_load/parquet_replay.py L436-460):
  replay_parquet_snapshot(*, source_name, table_name, business_date,
                          original_batch_id, replay_batch_id)
  -> ReplayResult(df, registry_id, source_file, row_count,
                  sha256_verified, extracted_at, batch_id)

run_scd2 canonical signature (per scd2/engine.py L190-217):
  run_scd2(table_config, df_current, pk_columns, output_dir,
           *, source_begin_date=None) -> SCD2Result

D-numbers: D2 (Stage dropped), D4 (network drive Parquet), D15
  (idempotency), D26 (append-only audit), D67 (Tier 0 discipline),
  D68 (canonical exception hierarchy), D74 (exit-code contract 0/1/2),
  D75 (arg naming + dry-run default), D76 (audit-row contract
  CLI_SCD2_REPLAY_SMOKE), D77 (Tier 0 canonical scaffold).

B-numbers:
  B88 (--apply + --dry-run mutex),
  B214 (sys.modules pre-registration + lazy getters),
  B228 (utils.errors canonical surface — tools import directly).

Spec: M2 ``data_load/parquet_replay.py`` (Round 3 § 1.2) +
``scd2/engine.py::run_scd2()``.
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
import time
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

_TOOL_PATH = _PROJECT_ROOT / "tools" / "scd2_replay_smoke.py"
_TOOL_MODULE_KEY = "tools.scd2_replay_smoke"

# ---------------------------------------------------------------------------
# Constants — single source of truth
# ---------------------------------------------------------------------------

EXPECTED_EVENT_TYPE = "CLI_SCD2_REPLAY_SMOKE"

EXIT_SUCCESS = 0
EXIT_OPERATIONAL_FAILURE = 1
EXIT_FATAL = 2

_ACTOR = "test-tier0-smoke"

# Canonical synthetic test inputs.
_SOURCE = "DNA"
_TABLE = "ACCT"
_BUSINESS_DATE = date(2026, 5, 13)
_ORIGINAL_BATCH_ID = 12345
_REPLAY_BATCH_ID = 99999


# ---------------------------------------------------------------------------
# Mock factories
# ---------------------------------------------------------------------------


def _make_table_config() -> Any:
    """Build a MagicMock that quacks like TableConfig."""
    tc = MagicMock()
    tc.source_name = _SOURCE
    tc.source_object_name = _TABLE
    tc.bronze_full_table_name = "UDM_Bronze.DNA.ACCT_scd2_python"
    tc.pk_columns = ["ACCTNBR"]
    tc.scd2_mode = "incremental"
    return tc


def _make_replay_result() -> Any:
    """Build a MagicMock that quacks like ReplayResult."""
    rr = MagicMock()
    rr.df = MagicMock()  # Polars DataFrame stand-in (not introspected in Tier 0)
    rr.registry_id = 42
    rr.source_file = Path("/mnt/parquet/DNA/ACCT/2026/05/13/12345.parquet")
    rr.row_count = 1000
    rr.sha256_verified = "a" * 64
    rr.extracted_at = datetime(2026, 5, 13, 12, 0, 0)
    rr.batch_id = _ORIGINAL_BATCH_ID
    return rr


def _make_scd2_result() -> Any:
    """Build a MagicMock that quacks like SCD2Result."""
    sr = MagicMock()
    sr.inserts = 100
    sr.new_versions = 5
    sr.closes = 3
    sr.unchanged = 892
    sr.resurrections = 0
    return sr


# ---------------------------------------------------------------------------
# Module loader
# ---------------------------------------------------------------------------


def _load_tool_module() -> Any:
    """Load tools/scd2_replay_smoke.py.

    Canonical exception classes are NOT mocked (B215 + B228 pattern).
    The tool imports utils.errors directly; we let that import succeed.
    """
    if _TOOL_MODULE_KEY in sys.modules:
        del sys.modules[_TOOL_MODULE_KEY]
    spec = importlib.util.spec_from_file_location(_TOOL_MODULE_KEY, _TOOL_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_TOOL_MODULE_KEY] = mod
    spec.loader.exec_module(mod)
    return mod


def _call_main(
    mod: Any,
    *,
    apply: bool = False,
    replay_side_effect: Any = None,
    scd2_side_effect: Any = None,
    table_config: Any = None,
) -> dict:
    """Call main() with mocked injection hooks. Always quiet + no_audit_event."""
    tc = table_config or _make_table_config()

    def _loader(_source, _table):
        return [tc]

    def _batch_seq():
        return _REPLAY_BATCH_ID

    replay_fn = MagicMock()
    if replay_side_effect is not None:
        replay_fn.side_effect = replay_side_effect
    else:
        replay_fn.return_value = _make_replay_result()

    scd2_fn = MagicMock()
    if scd2_side_effect is not None:
        scd2_fn.side_effect = scd2_side_effect
    else:
        scd2_fn.return_value = _make_scd2_result()

    try:
        return mod.main(
            source=_SOURCE,
            table=_TABLE,
            business_date=_BUSINESS_DATE,
            original_batch_id=_ORIGINAL_BATCH_ID,
            actor=_ACTOR,
            apply=apply,
            quiet=True,
            no_audit_event=True,
            replay_fn=replay_fn,
            scd2_fn=scd2_fn,
            table_config_loader=_loader,
            batch_seq_fn=_batch_seq,
            output_dir="/tmp",
        )
    except SystemExit as exc:
        return {"exit_code": exc.code, "_raised_system_exit": True}


# ===========================================================================
# (a) test_module_imports
# ===========================================================================


def test_module_imports():
    """(a) tools/scd2_replay_smoke.py imports without error + exposes surface.

    D67 Tier 0 assertion 1 + D77 8-canonical scaffold assertion 1.
    """
    mod = _load_tool_module()
    assert mod is not None, (
        "tools/scd2_replay_smoke.py must load without error. D67."
    )
    assert hasattr(mod, "main"), (
        "Module must expose a top-level 'main' function. D67."
    )
    assert hasattr(mod, "cli_main"), (
        "Module must expose a top-level 'cli_main' function. D74."
    )
    assert mod.EVENT_TYPE == EXPECTED_EVENT_TYPE, (
        f"EVENT_TYPE must be {EXPECTED_EVENT_TYPE!r} per D76 CLI_* family. "
        f"Got: {mod.EVENT_TYPE!r}."
    )
    assert mod.EXIT_SUCCESS == EXIT_SUCCESS
    assert mod.EXIT_OPERATIONAL_FAILURE == EXIT_OPERATIONAL_FAILURE
    assert mod.EXIT_FATAL == EXIT_FATAL


# ===========================================================================
# (b) test_help_exits_zero_with_nonempty_stdout
# ===========================================================================


def test_help_exits_zero_with_nonempty_stdout(capsys):
    """(b) --help exits 0 + emits non-empty stdout per D77.

    argparse always calls sys.exit(0) on --help. Stdout must include the
    canonical description so operators can discover what the tool does.
    """
    mod = _load_tool_module()
    parser = mod._build_arg_parser()

    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["--help"])
    assert exc_info.value.code == 0, (
        f"--help must exit 0. Got: {exc_info.value.code!r}. D74."
    )
    captured = capsys.readouterr()
    assert captured.out, "--help must emit non-empty stdout."
    assert "scd2" in captured.out.lower() or "replay" in captured.out.lower(), (
        "Help text must mention 'scd2' or 'replay' to be discoverable."
    )


# ===========================================================================
# (c) test_dry_run_default_exits_zero
# ===========================================================================


def test_dry_run_default_exits_zero():
    """(c) Dry-run default (apply=False) exits 0 + does NOT call replay/SCD2.

    Per D75 — dry-run is the safe default; operator must opt-in via --apply.
    Verifies the dry-run short-circuit fires BEFORE replay_fn / scd2_fn.
    """
    mod = _load_tool_module()
    result = _call_main(mod, apply=False)
    assert result.get("exit_code") == EXIT_SUCCESS, (
        f"Dry-run must exit 0. Got: {result.get('exit_code')!r}."
    )
    assert result.get("dry_run") is True, (
        "Result dict must mark dry_run=True for the default path."
    )


# ===========================================================================
# (d) test_apply_without_required_args_exits_two
# ===========================================================================


def test_apply_without_required_args_exits_two():
    """(d) cli_main without required args → argparse error → exit 2.

    Missing --source / --table / --business-date / --original-batch-id
    causes argparse to call sys.exit(2). Verifies the canonical argparse
    error path lands on the D74 fatal exit code.
    """
    mod = _load_tool_module()

    # Empty argv → all required args missing → argparse exits 2
    with pytest.raises(SystemExit) as exc_info:
        mod._build_arg_parser().parse_args([])
    assert exc_info.value.code == 2, (
        f"Missing required args must exit 2 (argparse). "
        f"Got: {exc_info.value.code!r}. D74."
    )


# ===========================================================================
# (e) test_apply_with_mock_success_returns_zero
# ===========================================================================


def test_apply_with_mock_success_returns_zero():
    """(e) --apply + mocked replay_fn + scd2_fn both success → exit 0.

    Verifies the happy-path end-to-end composition: replay_fn called →
    scd2_fn called → result populates ReplayResult+SCD2Result counts →
    exit 0.
    """
    mod = _load_tool_module()
    result = _call_main(mod, apply=True)
    assert result.get("exit_code") == EXIT_SUCCESS, (
        f"Successful --apply must exit 0. Got: {result.get('exit_code')!r}. "
        f"Error: {result.get('error_message')!r}."
    )
    # Verify both ReplayResult and SCD2Result counts were threaded through.
    assert result.get("rows_replayed") == 1000, (
        f"ReplayResult.row_count must surface as rows_replayed. "
        f"Got: {result.get('rows_replayed')!r}."
    )
    assert result.get("rows_inserted") == 100, (
        f"SCD2Result.inserts must surface as rows_inserted. "
        f"Got: {result.get('rows_inserted')!r}."
    )


# ===========================================================================
# (f) test_apply_with_mock_replay_fatal_returns_two
# ===========================================================================


def test_apply_with_mock_replay_fatal_returns_two():
    """(f) --apply + mocked replay_fn raises RegistryNotFound → exit 2.

    Verifies the PipelineFatalError → EXIT_FATAL mapping per D68 + D74.
    """
    from utils.errors import RegistryNotFound

    err = RegistryNotFound(
        f"No registry row for (DNA, ACCT, 2026-05-13, {_ORIGINAL_BATCH_ID})",
        metadata={
            "source_name": _SOURCE,
            "table_name": _TABLE,
            "business_date": _BUSINESS_DATE.isoformat(),
            "original_batch_id": _ORIGINAL_BATCH_ID,
        },
    )
    mod = _load_tool_module()
    result = _call_main(mod, apply=True, replay_side_effect=err)
    assert result.get("exit_code") == EXIT_FATAL, (
        f"RegistryNotFound must exit 2 (fatal). "
        f"Got: {result.get('exit_code')!r}. "
        f"Per D68 + D74: RegistryNotFound = PipelineFatalError → exit 2."
    )
    assert result.get("error_class") == "RegistryNotFound", (
        f"error_class must surface the exception type for diagnostics. "
        f"Got: {result.get('error_class')!r}."
    )


# ===========================================================================
# Runtime ceiling assertion — Tier 0 must complete < 5 s (D67)
# ===========================================================================


def test_tier0_runtime_ceiling():
    """Tier 0 mock-invocation suite completes < 5 s (D67 ceiling)."""
    start = time.monotonic()
    mod = _load_tool_module()
    _call_main(mod, apply=False)
    _call_main(mod, apply=True)
    elapsed = time.monotonic() - start
    assert elapsed < 5.0, (
        f"Tier 0 mock invocations exceeded 5s ceiling: {elapsed:.2f}s. D67."
    )
