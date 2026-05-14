"""Tier 1 unit tests for tools/scd2_replay_smoke.py.

Tests run on every commit. No live DB, no live network required.
All external dependencies mocked with unittest.mock.

North Star pillars addressed:
  - Audit-grade (D76): exactly one CLI_SCD2_REPLAY_SMOKE PipelineEventLog
    row per invocation; Metadata JSON shape verified.
  - Operationally stable (D74/D75): exit-code contract (0/1/2) and
    argument naming discipline; dry-run as safe default per D75.
  - Idempotent (D15): M2 ledger gate + run_scd2 INSERT-first contract
    (re-replaying unchanged data produces zero inserts).
  - Traceability (D26): per-invocation audit row in PipelineEventLog.

M2 canonical signature (per data_load/parquet_replay.py L436-460):
  replay_parquet_snapshot(*, source_name, table_name, business_date,
                          original_batch_id, replay_batch_id)
  -> ReplayResult(df, registry_id, source_file, row_count,
                  sha256_verified, extracted_at, batch_id)

run_scd2 canonical signature (per scd2/engine.py L190-217):
  run_scd2(table_config, df_current, pk_columns, output_dir,
           *, source_begin_date=None) -> SCD2Result

Naive-UTC datetime invariant (SCD2-P1-f + CDC-NOW-MS): every datetime
in audit row Metadata MUST be tzinfo=None + ms-precision.

D-numbers: D2 (Stage dropped), D4 (network drive Parquet), D15
  (idempotency), D26 (append-only audit), D67 (Tier 0 — Tier 1 extends),
  D68 (canonical exception hierarchy), D74 (exit-code contract 0/1/2),
  D75 (arg naming: --source / --table / --business-date /
       --original-batch-id / --apply / --dry-run / --actor /
       --json-output / --no-audit-event / --verbose / --quiet),
  D76 (audit-row CLI_SCD2_REPLAY_SMOKE).

B-numbers:
  B88 (--apply + --dry-run mutex),
  B214 (test-injection hooks — replay_fn / scd2_fn / table_config_loader /
        batch_seq_fn / audit_cursor_factory),
  B228 (utils.errors canonical surface).

Spec: M2 ``data_load/parquet_replay.py`` (Round 3 § 1.2) +
``scd2/engine.py::run_scd2()``.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
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

_TOOL_PATH = _PROJECT_ROOT / "tools" / "scd2_replay_smoke.py"
_TOOL_MODULE_KEY = "tools.scd2_replay_smoke"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXPECTED_EVENT_TYPE = "CLI_SCD2_REPLAY_SMOKE"

EXIT_SUCCESS = 0
EXIT_OPERATIONAL_FAILURE = 1
EXIT_FATAL = 2

_ACTOR = "test-tier1-author"

_SOURCE = "DNA"
_TABLE = "ACCT"
_BUSINESS_DATE = date(2026, 5, 13)
_ORIGINAL_BATCH_ID = 12345
_REPLAY_BATCH_ID = 99999


# ---------------------------------------------------------------------------
# Mock factories — shared with Tier 0; duplicated here so Tier 1 stays
# self-contained (per D67 — Tier 1 must run independently of Tier 0).
# ---------------------------------------------------------------------------


def _make_table_config(
    *,
    bronze_table: str = "UDM_Bronze.DNA.ACCT_scd2_python",
    pk_columns: list[str] | None = None,
    scd2_mode: str = "incremental",
) -> Any:
    """Build a MagicMock that quacks like TableConfig."""
    tc = MagicMock()
    tc.source_name = _SOURCE
    tc.source_object_name = _TABLE
    tc.bronze_full_table_name = bronze_table
    tc.pk_columns = pk_columns if pk_columns is not None else ["ACCTNBR"]
    tc.scd2_mode = scd2_mode
    return tc


def _make_replay_result(
    *,
    row_count: int = 1000,
    registry_id: int = 42,
    sha256: str = "a" * 64,
) -> Any:
    """Build a MagicMock that quacks like ReplayResult."""
    rr = MagicMock()
    rr.df = MagicMock()
    rr.registry_id = registry_id
    rr.source_file = Path(f"/mnt/parquet/DNA/ACCT/2026/05/13/{registry_id}.parquet")
    rr.row_count = row_count
    rr.sha256_verified = sha256
    rr.extracted_at = datetime(2026, 5, 13, 12, 0, 0)
    rr.batch_id = _ORIGINAL_BATCH_ID
    return rr


def _make_scd2_result(
    *,
    inserts: int = 100,
    new_versions: int = 5,
    closes: int = 3,
    unchanged: int = 892,
) -> Any:
    """Build a MagicMock that quacks like SCD2Result."""
    sr = MagicMock()
    sr.inserts = inserts
    sr.new_versions = new_versions
    sr.closes = closes
    sr.unchanged = unchanged
    sr.resurrections = 0
    return sr


def _load_tool_module() -> Any:
    """Load the tool module fresh."""
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
    dry_run: bool | None = None,
    table_config: Any = None,
    replay_fn: Any = None,
    scd2_fn: Any = None,
    batch_seq_fn: Any = None,
    table_config_loader: Any = None,
    audit_cursor_factory: Any = None,
    bronze_count_cursor_factory: Any = None,
    json_output: bool = False,
    no_audit_event: bool = True,
    source: str = _SOURCE,
    table: str = _TABLE,
    business_date: date = _BUSINESS_DATE,
    original_batch_id: int = _ORIGINAL_BATCH_ID,
) -> dict:
    """Call main() with default mocks + per-test overrides."""
    if table_config_loader is None:
        tc = table_config or _make_table_config()
        def table_config_loader(_s, _t):  # type: ignore[no-redef]
            return [tc]

    if batch_seq_fn is None:
        def batch_seq_fn():  # type: ignore[no-redef]
            return _REPLAY_BATCH_ID

    if replay_fn is None:
        replay_fn = MagicMock(return_value=_make_replay_result())

    if scd2_fn is None:
        scd2_fn = MagicMock(return_value=_make_scd2_result())

    kwargs = dict(
        source=source,
        table=table,
        business_date=business_date,
        original_batch_id=original_batch_id,
        actor=_ACTOR,
        apply=apply,
        quiet=True,
        no_audit_event=no_audit_event,
        json_output=json_output,
        replay_fn=replay_fn,
        scd2_fn=scd2_fn,
        table_config_loader=table_config_loader,
        batch_seq_fn=batch_seq_fn,
        output_dir="/tmp",
    )
    if dry_run is not None:
        kwargs["dry_run"] = dry_run
    if audit_cursor_factory is not None:
        kwargs["audit_cursor_factory"] = audit_cursor_factory
    if bronze_count_cursor_factory is not None:
        kwargs["bronze_count_cursor_factory"] = bronze_count_cursor_factory

    try:
        return mod.main(**kwargs)
    except SystemExit as exc:
        return {"exit_code": exc.code, "_raised_system_exit": True}


# ===========================================================================
# TestModuleSurface — public exports
# ===========================================================================


class TestModuleSurface:
    """Verify the canonical module exports."""

    def test_main_exported(self):
        mod = _load_tool_module()
        assert callable(mod.main), "main() must be callable."

    def test_cli_main_exported(self):
        mod = _load_tool_module()
        assert callable(mod.cli_main), "cli_main() must be callable."

    def test_event_type_constant(self):
        mod = _load_tool_module()
        assert mod.EVENT_TYPE == EXPECTED_EVENT_TYPE

    def test_exit_code_constants(self):
        mod = _load_tool_module()
        assert mod.EXIT_SUCCESS == 0
        assert mod.EXIT_OPERATIONAL_FAILURE == 1
        assert mod.EXIT_FATAL == 2

    def test_build_arg_parser_exported(self):
        mod = _load_tool_module()
        assert callable(mod._build_arg_parser)
        parser = mod._build_arg_parser()
        assert parser is not None


# ===========================================================================
# TestArgParser — argparse coverage
# ===========================================================================


class TestArgParser:
    """Verify argparse contract per D75."""

    def test_required_args_present(self):
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        args = parser.parse_args([
            "--source", "DNA",
            "--table", "ACCT",
            "--business-date", "2026-05-13",
            "--original-batch-id", "12345",
        ])
        assert args.source == "DNA"
        assert args.table == "ACCT"
        assert args.business_date == date(2026, 5, 13)
        assert args.original_batch_id == 12345

    def test_business_date_parses_as_date_type(self):
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        args = parser.parse_args([
            "--source", "DNA",
            "--table", "ACCT",
            "--business-date", "2026-05-13",
            "--original-batch-id", "12345",
        ])
        assert isinstance(args.business_date, date), (
            f"--business-date must yield a date instance. "
            f"Got: {type(args.business_date)!r}."
        )

    def test_business_date_invalid_format_errors(self):
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([
                "--source", "DNA",
                "--table", "ACCT",
                "--business-date", "not-a-date",
                "--original-batch-id", "12345",
            ])

    def test_apply_default_false(self):
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        args = parser.parse_args([
            "--source", "DNA",
            "--table", "ACCT",
            "--business-date", "2026-05-13",
            "--original-batch-id", "12345",
        ])
        assert args.apply is False, (
            "--apply must default to False (dry-run is default per D75)."
        )

    def test_apply_dry_run_mutex_via_argparse(self):
        """--apply + --dry-run together must be rejected at argparse level."""
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        with pytest.raises(SystemExit):
            parser.parse_args([
                "--source", "DNA",
                "--table", "ACCT",
                "--business-date", "2026-05-13",
                "--original-batch-id", "12345",
                "--apply",
                "--dry-run",
            ])

    def test_help_includes_required_arg_names(self, capsys):
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--help"])
        assert exc_info.value.code == 0
        captured = capsys.readouterr()
        for token in ("--source", "--table", "--business-date", "--original-batch-id"):
            assert token in captured.out, (
                f"--help must mention {token!r}; got: {captured.out!r}"
            )


# ===========================================================================
# TestActorDetection — 3 invocation paths per § 1.7
# ===========================================================================


class TestActorDetection:
    """Verify _detect_actor() heuristic."""

    def test_automic_env_returns_automic(self, monkeypatch):
        mod = _load_tool_module()
        monkeypatch.setenv("AUTOMIC_RUN_ID", "RUN-123")
        assert mod._detect_actor() == "automic"

    def test_tty_returns_operator(self, monkeypatch):
        mod = _load_tool_module()
        monkeypatch.delenv("AUTOMIC_RUN_ID", raising=False)
        with patch.object(sys, "stdin") as mock_stdin:
            mock_stdin.isatty.return_value = True
            assert mod._detect_actor() == "operator"

    def test_else_returns_pipeline(self, monkeypatch):
        mod = _load_tool_module()
        monkeypatch.delenv("AUTOMIC_RUN_ID", raising=False)
        with patch.object(sys, "stdin") as mock_stdin:
            mock_stdin.isatty.return_value = False
            assert mod._detect_actor() == "pipeline"


# ===========================================================================
# TestDryRunPath — defaults to dry-run; no replay/SCD2 calls
# ===========================================================================


class TestDryRunPath:
    """Verify dry-run is safe default + skips replay/SCD2 invocation."""

    def test_dry_run_default_returns_exit_zero(self):
        mod = _load_tool_module()
        result = _call_main(mod, apply=False)
        assert result.get("exit_code") == EXIT_SUCCESS

    def test_dry_run_does_not_call_replay_fn(self):
        mod = _load_tool_module()
        replay_fn = MagicMock()
        scd2_fn = MagicMock()
        result = _call_main(mod, apply=False, replay_fn=replay_fn, scd2_fn=scd2_fn)
        assert result.get("exit_code") == EXIT_SUCCESS
        assert replay_fn.call_count == 0, (
            f"Dry-run must NOT call replay_fn. Got {replay_fn.call_count} calls."
        )
        assert scd2_fn.call_count == 0, (
            f"Dry-run must NOT call scd2_fn. Got {scd2_fn.call_count} calls."
        )

    def test_dry_run_loads_table_config(self):
        """Dry-run still resolves TableConfig (for preview output)."""
        mod = _load_tool_module()
        loader = MagicMock(return_value=[_make_table_config()])
        result = _call_main(mod, apply=False, table_config_loader=loader)
        assert result.get("exit_code") == EXIT_SUCCESS
        assert loader.call_count == 1, (
            "Dry-run must call table_config_loader once for preview."
        )

    def test_dry_run_allocates_batch_id(self):
        """Dry-run still allocates a replay_batch_id (audit-trail completeness)."""
        mod = _load_tool_module()
        batch_seq = MagicMock(return_value=_REPLAY_BATCH_ID)
        result = _call_main(mod, apply=False, batch_seq_fn=batch_seq)
        assert result.get("exit_code") == EXIT_SUCCESS
        assert batch_seq.call_count == 1
        assert result.get("replay_batch_id") == _REPLAY_BATCH_ID

    def test_dry_run_dry_run_kwarg_True_apply_True_exits_two(self):
        """B88 mutex: dry_run=True + apply=True must raise SystemExit(2)."""
        mod = _load_tool_module()
        with pytest.raises(SystemExit) as exc_info:
            mod.main(
                source=_SOURCE,
                table=_TABLE,
                business_date=_BUSINESS_DATE,
                original_batch_id=_ORIGINAL_BATCH_ID,
                actor=_ACTOR,
                apply=True,
                dry_run=True,
                quiet=True,
                no_audit_event=True,
            )
        assert exc_info.value.code == EXIT_FATAL


# ===========================================================================
# TestApplyPath — calls replay_fn THEN scd2_fn; threads result.df through
# ===========================================================================


class TestApplyPath:
    """Verify the live composition order + DataFrame threading."""

    def test_apply_calls_replay_fn_with_correct_kwargs(self):
        mod = _load_tool_module()
        replay_fn = MagicMock(return_value=_make_replay_result())
        result = _call_main(mod, apply=True, replay_fn=replay_fn)
        assert result.get("exit_code") == EXIT_SUCCESS
        replay_fn.assert_called_once()
        kwargs = replay_fn.call_args.kwargs
        assert kwargs["source_name"] == _SOURCE
        assert kwargs["table_name"] == _TABLE
        assert kwargs["business_date"] == _BUSINESS_DATE
        assert kwargs["original_batch_id"] == _ORIGINAL_BATCH_ID
        assert kwargs["replay_batch_id"] == _REPLAY_BATCH_ID

    def test_apply_calls_scd2_fn_with_replay_result_df(self):
        mod = _load_tool_module()
        replay_result = _make_replay_result()
        replay_fn = MagicMock(return_value=replay_result)
        scd2_fn = MagicMock(return_value=_make_scd2_result())

        result = _call_main(mod, apply=True, replay_fn=replay_fn, scd2_fn=scd2_fn)
        assert result.get("exit_code") == EXIT_SUCCESS
        scd2_fn.assert_called_once()
        # run_scd2 positional contract: (table_config, df_current, pk_columns, output_dir)
        args = scd2_fn.call_args.args
        assert len(args) >= 2, (
            f"scd2_fn must receive at least (table_config, df_current). "
            f"Got args: {args!r}."
        )
        # The DataFrame from replay_result must be threaded into df_current arg
        assert args[1] is replay_result.df, (
            "scd2_fn's df_current arg must be the ReplayResult.df. "
            "Threading is the core invariant of this smoke script."
        )

    def test_apply_threads_pk_columns_from_table_config(self):
        mod = _load_tool_module()
        tc = _make_table_config(pk_columns=["KEY1", "KEY2"])
        scd2_fn = MagicMock(return_value=_make_scd2_result())
        result = _call_main(mod, apply=True, table_config=tc, scd2_fn=scd2_fn)
        assert result.get("exit_code") == EXIT_SUCCESS
        args = scd2_fn.call_args.args
        # Positional pk_columns is args[2]
        assert args[2] == ["KEY1", "KEY2"]

    def test_apply_calls_in_order_replay_then_scd2(self):
        """Verify call order: replay_fn before scd2_fn (smoke contract)."""
        mod = _load_tool_module()
        call_order = []

        replay_fn = MagicMock(side_effect=lambda **_: (
            call_order.append("replay") or _make_replay_result()
        ))
        scd2_fn = MagicMock(side_effect=lambda *_a, **_k: (
            call_order.append("scd2") or _make_scd2_result()
        ))
        result = _call_main(mod, apply=True, replay_fn=replay_fn, scd2_fn=scd2_fn)
        assert result.get("exit_code") == EXIT_SUCCESS
        assert call_order == ["replay", "scd2"], (
            f"Call order must be [replay, scd2]. Got: {call_order!r}."
        )

    def test_apply_surfaces_replay_provenance(self):
        mod = _load_tool_module()
        rr = _make_replay_result(row_count=2500, registry_id=77, sha256="b" * 64)
        replay_fn = MagicMock(return_value=rr)
        result = _call_main(mod, apply=True, replay_fn=replay_fn)
        assert result.get("exit_code") == EXIT_SUCCESS
        assert result.get("registry_id") == 77
        assert result.get("rows_replayed") == 2500
        assert result.get("sha256_verified") == "b" * 64
        assert result.get("source_file") == str(rr.source_file)

    def test_apply_surfaces_scd2_counts(self):
        mod = _load_tool_module()
        sr = _make_scd2_result(
            inserts=10, new_versions=20, closes=5, unchanged=100,
        )
        scd2_fn = MagicMock(return_value=sr)
        result = _call_main(mod, apply=True, scd2_fn=scd2_fn)
        assert result.get("exit_code") == EXIT_SUCCESS
        assert result.get("rows_inserted") == 10
        assert result.get("rows_new_versions") == 20
        assert result.get("rows_closed") == 5
        assert result.get("rows_unchanged") == 100


# ===========================================================================
# TestErrorPaths — each error class maps to its canonical exit code
# ===========================================================================


class TestErrorPaths:
    """Verify D68 → D74 error-to-exit-code mapping."""

    def test_registry_not_found_returns_exit_two(self):
        from utils.errors import RegistryNotFound

        mod = _load_tool_module()
        err = RegistryNotFound(
            "no registry row",
            metadata={"source_name": _SOURCE, "table_name": _TABLE},
        )
        replay_fn = MagicMock(side_effect=err)
        result = _call_main(mod, apply=True, replay_fn=replay_fn)
        assert result.get("exit_code") == EXIT_FATAL
        assert result.get("error_class") == "RegistryNotFound"

    def test_registry_status_invalid_returns_exit_two(self):
        from utils.errors import RegistryStatusInvalid

        mod = _load_tool_module()
        err = RegistryStatusInvalid(
            "Status='created'",
            metadata={"current_status": "created"},
        )
        replay_fn = MagicMock(side_effect=err)
        result = _call_main(mod, apply=True, replay_fn=replay_fn)
        assert result.get("exit_code") == EXIT_FATAL
        assert result.get("error_class") == "RegistryStatusInvalid"

    def test_parquet_replay_error_returns_exit_two(self):
        from utils.errors import ParquetReplayError

        mod = _load_tool_module()
        err = ParquetReplayError(
            "SHA-256 mismatch",
            metadata={"file_path": "/mnt/parquet/x.parquet"},
        )
        replay_fn = MagicMock(side_effect=err)
        result = _call_main(mod, apply=True, replay_fn=replay_fn)
        assert result.get("exit_code") == EXIT_FATAL
        assert result.get("error_class") == "ParquetReplayError"

    def test_ledger_lock_timeout_returns_exit_one(self):
        """LedgerLockTimeout is PipelineRetryableError → exit 1."""
        from utils.errors import LedgerLockTimeout

        mod = _load_tool_module()
        err = LedgerLockTimeout(
            "sp_getapplock contention",
            metadata={"batch_id": _REPLAY_BATCH_ID},
        )
        replay_fn = MagicMock(side_effect=err)
        result = _call_main(mod, apply=True, replay_fn=replay_fn)
        assert result.get("exit_code") == EXIT_OPERATIONAL_FAILURE
        assert result.get("error_class") == "LedgerLockTimeout"

    def test_scd2_fatal_returns_exit_two(self):
        """A PipelineFatalError from run_scd2 maps to exit 2."""
        from utils.errors import PipelineFatalError

        mod = _load_tool_module()
        err = PipelineFatalError(
            "Bronze schema mismatch",
            metadata={"step": "scd2_promote"},
        )
        scd2_fn = MagicMock(side_effect=err)
        result = _call_main(mod, apply=True, scd2_fn=scd2_fn)
        assert result.get("exit_code") == EXIT_FATAL
        assert result.get("error_class") == "PipelineFatalError"

    def test_unexpected_exception_in_replay_returns_exit_two(self):
        """A non-PipelineError exception from replay_fn maps to exit 2."""
        mod = _load_tool_module()
        replay_fn = MagicMock(side_effect=RuntimeError("network drive unreachable"))
        result = _call_main(mod, apply=True, replay_fn=replay_fn)
        assert result.get("exit_code") == EXIT_FATAL
        assert result.get("error_class") == "RuntimeError"

    def test_missing_table_config_returns_exit_two(self):
        """Empty configs list → exit 2 with TableConfigNotFound class."""
        mod = _load_tool_module()
        loader = MagicMock(return_value=[])  # no rows
        result = _call_main(mod, apply=True, table_config_loader=loader)
        assert result.get("exit_code") == EXIT_FATAL
        assert result.get("error_class") == "TableConfigNotFound"

    def test_missing_pk_columns_returns_exit_two(self):
        """TableConfig with empty pk_columns → exit 2."""
        mod = _load_tool_module()
        tc = _make_table_config(pk_columns=[])
        result = _call_main(mod, apply=True, table_config=tc)
        assert result.get("exit_code") == EXIT_FATAL
        assert result.get("error_class") == "MissingPrimaryKey"


# ===========================================================================
# TestAuditRow — one row per invocation; Metadata JSON shape
# ===========================================================================


class TestAuditRow:
    """Verify D76 audit-row contract."""

    def _setup_audit_capture(self, mod):
        """Build a cursor_factory that captures audit-row INSERTs."""
        captured = {"sql": None, "params": None}
        mock_cursor = MagicMock()

        def _execute(sql, *params):
            captured["sql"] = sql
            captured["params"] = params
            # Simulate SCOPE_IDENTITY result
            mock_cursor.fetchone.return_value = (12345,)
            mock_cursor.description = [("AuditEventId",)]

        mock_cursor.execute.side_effect = _execute
        mock_cursor.fetchone.return_value = (12345,)
        mock_cursor.description = [("AuditEventId",)]
        mock_conn = MagicMock()
        mock_conn.cursor.return_value = mock_cursor

        def factory():
            return mock_conn

        return factory, captured

    def test_one_audit_row_per_apply_invocation(self):
        mod = _load_tool_module()
        factory, captured = self._setup_audit_capture(mod)
        result = _call_main(
            mod, apply=True,
            audit_cursor_factory=factory,
            no_audit_event=False,
        )
        assert result.get("exit_code") == EXIT_SUCCESS
        assert captured["sql"] is not None, (
            "Audit-row INSERT must have been executed."
        )
        assert "PipelineEventLog" in captured["sql"]
        assert "CLI_SCD2_REPLAY_SMOKE" in captured["params"], (
            f"Audit row must carry EventType=CLI_SCD2_REPLAY_SMOKE. "
            f"Params: {captured['params']!r}."
        )

    def test_one_audit_row_per_dry_run_invocation(self):
        """Dry-run still writes an audit row (D76 — one row per invocation)."""
        mod = _load_tool_module()
        factory, captured = self._setup_audit_capture(mod)
        result = _call_main(
            mod, apply=False,
            audit_cursor_factory=factory,
            no_audit_event=False,
        )
        assert result.get("exit_code") == EXIT_SUCCESS
        assert captured["sql"] is not None, (
            "Dry-run audit row must still be written per D76."
        )

    def test_audit_event_id_surfaces_in_result(self):
        mod = _load_tool_module()
        factory, _ = self._setup_audit_capture(mod)
        result = _call_main(
            mod, apply=True,
            audit_cursor_factory=factory,
            no_audit_event=False,
        )
        assert result.get("audit_event_id") == 12345

    def test_audit_metadata_carries_canonical_keys(self):
        """Verify the Metadata JSON payload includes all canonical keys."""
        mod = _load_tool_module()
        factory, captured = self._setup_audit_capture(mod)
        result = _call_main(
            mod, apply=True,
            audit_cursor_factory=factory,
            no_audit_event=False,
        )
        assert result.get("exit_code") == EXIT_SUCCESS
        # Find the JSON payload param — it'll be the last str-like param
        # containing braces.
        json_params = [
            p for p in captured["params"]
            if isinstance(p, str) and p.startswith("{") and p.endswith("}")
        ]
        assert json_params, (
            f"Audit row params must include a JSON Metadata payload. "
            f"Params: {captured['params']!r}."
        )
        metadata = json.loads(json_params[0])
        for key in (
            "event_kind", "actor", "source_name", "table_name",
            "business_date", "original_batch_id", "replay_batch_id",
            "dry_run", "exit_code",
        ):
            assert key in metadata, (
                f"Audit Metadata must include key {key!r}. Got keys: {list(metadata)!r}."
            )
        assert metadata["event_kind"] == "scd2_replay_smoke"
        assert metadata["source_name"] == _SOURCE
        assert metadata["table_name"] == _TABLE
        assert metadata["business_date"] == _BUSINESS_DATE.isoformat()

    def test_audit_metadata_carries_replay_and_scd2_counts(self):
        mod = _load_tool_module()
        factory, captured = self._setup_audit_capture(mod)
        result = _call_main(
            mod, apply=True,
            audit_cursor_factory=factory,
            no_audit_event=False,
        )
        json_params = [
            p for p in captured["params"]
            if isinstance(p, str) and p.startswith("{")
        ]
        metadata = json.loads(json_params[0])
        # rows_replayed comes from ReplayResult.row_count = 1000 in mock
        assert metadata["rows_replayed"] == 1000
        # rows_inserted comes from SCD2Result.inserts = 100 in mock
        assert metadata["rows_inserted"] == 100
        assert metadata["rows_new_versions"] == 5
        assert metadata["rows_closed"] == 3
        assert metadata["rows_unchanged"] == 892

    def test_audit_row_on_failure_path(self):
        """Failure path still writes ONE audit row with Status=FAILED."""
        from utils.errors import RegistryNotFound

        mod = _load_tool_module()
        factory, captured = self._setup_audit_capture(mod)
        err = RegistryNotFound("not found", metadata={})
        replay_fn = MagicMock(side_effect=err)
        result = _call_main(
            mod, apply=True,
            audit_cursor_factory=factory,
            replay_fn=replay_fn,
            no_audit_event=False,
        )
        assert result.get("exit_code") == EXIT_FATAL
        assert captured["sql"] is not None
        # Status=FAILED should be in the params
        assert "FAILED" in captured["params"]


# ===========================================================================
# TestJsonOutput — --json-output emits valid JSON
# ===========================================================================


class TestJsonOutput:
    """Verify --json-output emits parseable canonical JSON."""

    def test_json_output_is_valid_json(self, capsys):
        mod = _load_tool_module()
        result = _call_main(mod, apply=True, json_output=True)
        assert result.get("exit_code") == EXIT_SUCCESS
        captured = capsys.readouterr()
        # Parse stdout as JSON — must not raise
        payload = json.loads(captured.out)
        assert isinstance(payload, dict)

    def test_json_output_contains_canonical_keys(self, capsys):
        mod = _load_tool_module()
        result = _call_main(mod, apply=True, json_output=True)
        assert result.get("exit_code") == EXIT_SUCCESS
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        for key in (
            "event_kind", "actor", "source_name", "table_name",
            "business_date", "original_batch_id", "replay_batch_id",
            "dry_run", "exit_code", "rows_replayed", "rows_inserted",
        ):
            assert key in payload, (
                f"JSON payload must include {key!r}. Got: {list(payload)!r}."
            )

    def test_json_output_on_dry_run(self, capsys):
        mod = _load_tool_module()
        result = _call_main(mod, apply=False, json_output=True)
        assert result.get("exit_code") == EXIT_SUCCESS
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert payload.get("dry_run") is True


# ===========================================================================
# TestTableConfigLoad — loader invoked with (source, table)
# ===========================================================================


class TestTableConfigLoad:
    """Verify table_config_loader contract."""

    def test_loader_invoked_with_source_and_table(self):
        mod = _load_tool_module()
        loader = MagicMock(return_value=[_make_table_config()])
        _call_main(mod, apply=False, table_config_loader=loader)
        loader.assert_called_once()
        # Loader accepts positional (source, table) per the canonical signature
        args = loader.call_args.args
        kwargs = loader.call_args.kwargs
        if args:
            assert args[0] == _SOURCE
            assert args[1] == _TABLE
        else:
            # Defensive — if some implementation routes via kwargs
            assert kwargs.get("source") == _SOURCE or kwargs.get("source_name") == _SOURCE
            assert kwargs.get("table") == _TABLE or kwargs.get("table_name") == _TABLE

    def test_loader_failure_exits_two(self):
        mod = _load_tool_module()
        loader = MagicMock(side_effect=RuntimeError("DB unreachable"))
        result = _call_main(mod, apply=True, table_config_loader=loader)
        assert result.get("exit_code") == EXIT_FATAL
        assert result.get("error_class") == "RuntimeError"

    def test_table_config_summary_populated(self):
        mod = _load_tool_module()
        tc = _make_table_config(bronze_table="UDM_Bronze.DNA.ACCT_scd2_python")
        result = _call_main(mod, apply=False, table_config=tc)
        assert result.get("exit_code") == EXIT_SUCCESS
        summary = result.get("table_config_summary")
        assert summary is not None
        assert "DNA" in summary
        assert "ACCT" in summary


# ===========================================================================
# TestBatchSequence — batch_seq_fn invoked once; threaded into replay_fn
# ===========================================================================


class TestBatchSequence:
    """Verify batch_seq_fn allocation + threading per M2 contract."""

    def test_batch_seq_invoked_once(self):
        mod = _load_tool_module()
        batch_seq = MagicMock(return_value=_REPLAY_BATCH_ID)
        _call_main(mod, apply=True, batch_seq_fn=batch_seq)
        assert batch_seq.call_count == 1, (
            f"batch_seq_fn must be invoked exactly once. "
            f"Got {batch_seq.call_count} calls."
        )

    def test_batch_seq_result_threaded_into_replay_fn(self):
        """The fresh replay_batch_id must reach replay_fn per M2 contract."""
        mod = _load_tool_module()
        batch_seq = MagicMock(return_value=88888)
        replay_fn = MagicMock(return_value=_make_replay_result())
        _call_main(mod, apply=True, batch_seq_fn=batch_seq, replay_fn=replay_fn)
        assert replay_fn.call_args.kwargs["replay_batch_id"] == 88888

    def test_batch_seq_failure_exits_two(self):
        mod = _load_tool_module()
        batch_seq = MagicMock(side_effect=RuntimeError("sequence unavailable"))
        result = _call_main(mod, apply=True, batch_seq_fn=batch_seq)
        assert result.get("exit_code") == EXIT_FATAL


# ===========================================================================
# TestB228UtilsErrorsImport — canonical exception import per B228
# ===========================================================================


class TestB228UtilsErrorsImport:
    """Verify exception classes lift from utils.errors (B228 single-source)."""

    def test_tool_uses_canonical_exception_classes(self):
        mod = _load_tool_module()
        from utils.errors import (
            LedgerLockTimeout,
            ParquetReplayError,
            PipelineFatalError,
            PipelineRetryableError,
            RegistryNotFound,
            RegistryStatusInvalid,
        )
        # The tool's exception identity MUST be the canonical class.
        assert mod.RegistryNotFound is RegistryNotFound, (
            "B228: tool must import RegistryNotFound from utils.errors, "
            "not redefine locally."
        )
        assert mod.RegistryStatusInvalid is RegistryStatusInvalid
        assert mod.ParquetReplayError is ParquetReplayError
        assert mod.LedgerLockTimeout is LedgerLockTimeout
        assert mod.PipelineFatalError is PipelineFatalError
        assert mod.PipelineRetryableError is PipelineRetryableError


# ===========================================================================
# TestCliMainArgv — cli_main argv parsing + exit-code mapping
# ===========================================================================


class TestCliMainArgv:
    """Verify cli_main argv → exit-code path."""

    def test_cli_main_missing_args_exits_two(self):
        mod = _load_tool_module()
        with pytest.raises(SystemExit) as exc_info:
            mod.cli_main(argv=[])
        # argparse exits with code 2 for missing required args
        assert exc_info.value.code == 2

    def test_cli_main_dry_run_returns_zero(self):
        mod = _load_tool_module()
        # cli_main with full args + dry-run default should exit 0,
        # but it'll try to load TableConfig from real DB; we patch main()
        # to short-circuit via a stub.
        with patch.object(mod, "main", return_value={"exit_code": EXIT_SUCCESS}):
            code = mod.cli_main(argv=[
                "--source", "DNA",
                "--table", "ACCT",
                "--business-date", "2026-05-13",
                "--original-batch-id", "12345",
            ])
        assert code == EXIT_SUCCESS

    def test_cli_main_clamps_non_canonical_exit_code(self):
        """cli_main must clamp unknown exit codes to EXIT_FATAL per D74."""
        mod = _load_tool_module()
        with patch.object(mod, "main", return_value={"exit_code": 99}):
            code = mod.cli_main(argv=[
                "--source", "DNA",
                "--table", "ACCT",
                "--business-date", "2026-05-13",
                "--original-batch-id", "12345",
            ])
        assert code == EXIT_FATAL


# ===========================================================================
# TestNaiveUtcDatetimeInvariant — SCD2-P1-f / CDC-NOW-MS
# ===========================================================================


class TestNaiveUtcDatetimeInvariant:
    """Verify _now_naive_utc returns naive (no tzinfo) + ms-precision datetime."""

    def test_now_returns_naive_datetime(self):
        mod = _load_tool_module()
        now = mod._now_naive_utc()
        assert now.tzinfo is None, (
            "SCD2-P1-f: audit datetimes must be naive (no tzinfo). "
            f"Got tzinfo={now.tzinfo!r}."
        )

    def test_now_truncated_to_millisecond(self):
        mod = _load_tool_module()
        now = mod._now_naive_utc()
        # Microseconds must be a multiple of 1000 (i.e. zero in the units below ms)
        assert now.microsecond % 1000 == 0, (
            f"CDC-NOW-MS: datetime must be ms-precision. "
            f"Got microsecond={now.microsecond}."
        )
