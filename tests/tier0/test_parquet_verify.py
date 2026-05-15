"""Tier 0 build-time smoke test for tools/parquet_verify.py.

Per D67 — runs at build time + every commit. Runtime ceiling < 5 s.
All external dependencies (pyodbc cursors, PipelineEventLog, M3
verify_parquet_snapshot) are mocked. No live DB, no live network required.

8-assertion D77-canonical scaffold per phase1/04_tools.md § 3.2 L562:
  (a) Module imports without error (tools/parquet_verify.py).
  (b) ``--help`` exits 0 per D77 Tier 0 scaffold assertion 2.
  (c) ``--registry-id 12345`` parses without error.
  (d) ``--registry-id 12345 --source DNA`` together raises arg-parse error
      (mutual exclusion per spec § 3.2 L520-522).
  (e) Mocked verify_parquet_snapshot returning successful ParquetVerifyResult
      -> tool returns exit 0.
  (f) Mocked verify_parquet_snapshot raising RegistryStatusInvalid -> exit 2.
  (g) Mocked verify_parquet_snapshot raising RegistryFileNotFound -> exit 1.
  (h) ``--dry-run`` does NOT call verify_parquet_snapshot (only SHA + file
      existence check, then exits).

North Star pillars:
  - Audit-grade (D76 audit-row contract: exactly one CLI_PARQUET_VERIFY row
    per invocation; Metadata JSON carries verdict counts + per-row verdicts).
  - Operationally stable (D67 Tier 0: import + invoke + shape + error-modes
    in < 5s with zero external I/O; D74 exit-code contract 0/1/2 verified).
  - Idempotent (D15): M3 verify_parquet_snapshot is idempotent at the row
    level; re-invoking on already-verified rows returns SKIPPED.
  - Traceability (D26): every invocation writes ONE PipelineEventLog row
    with EventType='CLI_PARQUET_VERIFY'.

ParquetSnapshotRegistry canonical columns (Pitfall #9.a per Round 1):
  RegistryId, SourceName, TableName, BatchId, BusinessDate,
  NetworkDrivePath, RowCount, ContentChecksum, SchemaHash, Status,
  CreatedAt, LastVerifiedAt.
ParquetSnapshotRegistry.Status enum (per M3 § 1.3 ParquetSnapshotStatus):
  'created', 'verified', 'replicated', 'archived', 'missing', 'purged',
  'replication_failed'.
M3 verify_parquet_snapshot canonical signature (per data_load/
parquet_registry_client.py L523-528):
  verify_parquet_snapshot(*, registry_id: int, actor: str = 'pipeline')
  -> ParquetVerifyResult

D-numbers: D2 (Stage dropped), D4 (network drive Parquet), D15
  (idempotency), D16 (inflight-rename), D26 (append-only audit), D67
  (Tier 0 discipline), D68 (canonical exception hierarchy), D74
  (exit-code contract 0/1/2), D75 (arg naming), D76 (audit-row contract
  CLI_PARQUET_VERIFY), D77 (8-canonical Tier 0 scaffold).

Edge cases cited:
  N4 (idempotent re-call short-circuits per M3 § 1.3 ledger).
  F3 (file absent vs corrupted — distinct verdicts: MISSING vs HASH_MISMATCH).

Spec: phase1/04_tools.md § 3.2 (canonical spec L493-575).
M3 module: data_load/parquet_registry_client.py § 1.3.
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
import time
from datetime import datetime
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

_TOOL_PATH = _PROJECT_ROOT / "tools" / "parquet_verify.py"
_TOOL_MODULE_KEY = "tools.parquet_verify"

# ---------------------------------------------------------------------------
# Constants — single source of truth
# ---------------------------------------------------------------------------

# D76 EventType per CLI_* family
EXPECTED_EVENT_TYPE = "CLI_PARQUET_VERIFY"

# D74 exit codes (§ 1.1 + § 3.2 L557-560)
EXIT_SUCCESS = 0
EXIT_OPERATIONAL_FAILURE = 1
EXIT_FATAL = 2

# D75 canonical actor
_ACTOR = "test-tier0-smoke"

# Synthetic registry IDs
_REGISTRY_ID_OK = 12345
_REGISTRY_ID_MISSING = 67890
_REGISTRY_ID_BAD_STATUS = 99999


# ---------------------------------------------------------------------------
# Mock factory: ParquetVerifyResult-like for success path
# ---------------------------------------------------------------------------


def _make_verify_result(registry_id: int = _REGISTRY_ID_OK) -> Any:
    """Build a MagicMock that quacks like ParquetVerifyResult."""
    result = MagicMock()
    result.registry_id = registry_id
    result.file_path = Path(f"/mnt/parquet/dna/acct/{registry_id}.parquet")
    result.sha256_verified = "a" * 64
    result.row_count_verified = 100_000
    result.last_verified_at = datetime(2026, 5, 14, 10, 0, 0)
    result.status = "verified"
    return result


# ---------------------------------------------------------------------------
# Module loader — mocks all external dependencies
# ---------------------------------------------------------------------------


def _load_tool_module(
    *,
    verify_side_effect: Any = None,
    verify_return_value: Any = None,
) -> Any:
    """Load tools/parquet_verify.py with all external imports mocked.

    Parameters
    ----------
    verify_side_effect:
        Exception to raise when M3 verify_parquet_snapshot is called.
        Mutually exclusive with verify_return_value.
    verify_return_value:
        ParquetVerifyResult-like object to return when verify_parquet_snapshot
        is called. Defaults to a successful result if neither is provided.

    B214 pattern: pre-register sys.modules before exec_module().
    B215 pattern: canonical utils.errors exception classes are NOT mocked.
    B228 pattern: tools import utils.errors directly (canonical surface).
    """
    if _TOOL_MODULE_KEY in sys.modules:
        del sys.modules[_TOOL_MODULE_KEY]

    # Canonical exception classes — NOT mocked (B215 + B228 pattern).
    try:
        from utils.errors import (  # noqa: F401
            PipelineFatalError,
            PipelineRetryableError,
            RegistryFileNotFound,
            RegistryHashMismatch,
            RegistryNotFound,
            RegistryStatusInvalid,
        )
    except ImportError:
        # Defensive minimal stand-ins if utils.errors is unavailable.
        class PipelineFatalError(Exception):  # type: ignore[no-redef]
            def __init__(self, msg, *, metadata=None):
                super().__init__(msg)
                self.metadata = metadata or {}
        class PipelineRetryableError(Exception):  # type: ignore[no-redef]
            def __init__(self, msg, *, metadata=None):
                super().__init__(msg)
                self.metadata = metadata or {}
        class RegistryFileNotFound(PipelineRetryableError):  # type: ignore[no-redef]
            pass
        class RegistryHashMismatch(PipelineFatalError):  # type: ignore[no-redef]
            pass
        class RegistryNotFound(PipelineFatalError):  # type: ignore[no-redef]
            pass
        class RegistryStatusInvalid(PipelineFatalError):  # type: ignore[no-redef]
            pass

    # Build cursor that simulates the registry filter query
    mock_cursor = MagicMock()
    executed_sql: list[str] = []
    executed_params: list[Any] = []

    def _capture_execute(sql, *args, **kwargs):
        executed_sql.append(str(sql))
        if args:
            for a in args:
                if isinstance(a, (list, tuple)):
                    executed_params.extend(a)
                else:
                    executed_params.append(a)

    mock_cursor.execute.side_effect = _capture_execute
    # Default: row summary for dry-run path:
    # (NetworkDrivePath, Status, ContentChecksum, SchemaHash, RowCount)
    mock_cursor.fetchone.return_value = (
        "/mnt/parquet/dna/acct/12345.parquet",
        "created",
        "b" * 64,
        "c" * 64,
        100_000,
    )
    mock_cursor.fetchall.return_value = []  # empty filter result
    mock_cursor.rowcount = 0
    mock_cursor.description = [("col",)]
    mock_cursor._executed_sql = executed_sql
    mock_cursor._executed_params = executed_params

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    mock_connections = MagicMock()
    mock_connections.get_connection = MagicMock(return_value=mock_conn)

    mock_config = MagicMock()
    mock_config.GENERAL_DB = "General"

    mock_pyodbc = MagicMock()
    mock_pyodbc.connect = MagicMock(return_value=mock_conn)

    # Mock M3 verify_parquet_snapshot
    mock_registry_client = MagicMock()
    if verify_side_effect is not None:
        mock_registry_client.verify_parquet_snapshot = MagicMock(
            side_effect=verify_side_effect
        )
    elif verify_return_value is not None:
        mock_registry_client.verify_parquet_snapshot = MagicMock(
            return_value=verify_return_value
        )
    else:
        mock_registry_client.verify_parquet_snapshot = MagicMock(
            return_value=_make_verify_result()
        )

    sys_modules_patch: dict[str, Any] = {
        "connections": mock_connections,
        "utils.connections": mock_connections,
        "config": mock_config,
        "utils.configuration": mock_config,
        "pyodbc": mock_pyodbc,
        "data_load.parquet_registry_client": mock_registry_client,
    }

    with patch.dict("sys.modules", sys_modules_patch):
        spec = importlib.util.spec_from_file_location(_TOOL_MODULE_KEY, _TOOL_PATH)
        mod = importlib.util.module_from_spec(spec)
        # B214: pre-register before exec_module
        sys.modules[_TOOL_MODULE_KEY] = mod
        spec.loader.exec_module(mod)

    # B218: stash patch dict so _call_main can re-apply at invocation time
    mod._test_sys_modules_patch = sys_modules_patch
    mod._test_cursor = mock_cursor
    mod._test_executed_sql = executed_sql
    mod._test_executed_params = executed_params
    mod._test_registry_client = mock_registry_client
    return mod


def _call_main(mod: Any, **overrides: Any) -> dict:
    """Call tool main() with canonical defaults + overrides.

    Per the canonical signature from spec § 3.2:
      main(*, actor, registry_ids, source, table, business_date_from,
           business_date_to, apply, dry_run, continue_on_error,
           json_output, verbose, quiet, justification, no_audit_event,
           cursor_factory, audit_cursor_factory, verify_fn,
           general_db) -> dict

    Re-applies sys.modules patch from _load_tool_module per B218.
    """
    defaults = dict(
        actor=_ACTOR,
        registry_ids=[_REGISTRY_ID_OK],
        source=None,
        table=None,
        business_date_from=None,
        business_date_to=None,
        apply=False,
        dry_run=False,
        continue_on_error=False,
        json_output=False,
        verbose=False,
        quiet=True,  # suppress stdout in test
        justification=None,
        no_audit_event=True,  # skip audit-row write in test
    )
    defaults.update(overrides)
    sys_modules_patch = getattr(mod, "_test_sys_modules_patch", {})
    try:
        with patch.dict("sys.modules", sys_modules_patch):
            return mod.main(**defaults)
    except SystemExit as exc:
        return {"exit_code": exc.code, "_raised_system_exit": True}
    except Exception as exc:
        return {"exit_code": EXIT_FATAL, "_exception": str(exc), "_raised_system_exit": False}


# ===========================================================================
# Assertion (a): Module imports without error
# ===========================================================================


def test_a_module_imports():
    """(a) tools/parquet_verify.py imports without error.

    Per D67 Tier 0 assertion 1 + D77 8-canonical scaffold assertion 1.
    Verifies no missing dependencies, no syntax errors, no import-time DB
    calls. Module must expose top-level 'main' + '_build_arg_parser'.

    North Star: Operationally stable. D67, D77. Spec: phase1/04_tools.md § 3.2.
    """
    mod = _load_tool_module()
    assert mod is not None, (
        "tools/parquet_verify.py must load without error. D67."
    )
    assert hasattr(mod, "main"), (
        "tools/parquet_verify.py must expose a top-level 'main' function "
        "per § 3.2 CLI interface. D67 Tier 0 assertion 1."
    )
    assert mod.EVENT_TYPE == EXPECTED_EVENT_TYPE, (
        f"EVENT_TYPE must be {EXPECTED_EVENT_TYPE!r} per D76 CLI_* family. "
        f"Got: {mod.EVENT_TYPE!r}."
    )


# ===========================================================================
# Assertion (b): --help exits 0
# ===========================================================================


def test_b_help_exits_0():
    """(b) --help exits 0 per D77 Tier 0 scaffold assertion 2.

    argparse always calls sys.exit(0) on --help. Confirms CLI is wired
    up correctly and does not crash before argparse reaches argument parsing.

    D74 (exit 0 = success / preview), D77. Spec: § 3.2 L562(b).
    """
    mod = _load_tool_module()
    assert hasattr(mod, "_build_arg_parser"), (
        "Module must expose _build_arg_parser per Tier 0 scaffold."
    )

    parser = mod._build_arg_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["--help"])
    assert exc_info.value.code == 0, (
        f"--help must exit 0 per D74. Got: {exc_info.value.code!r}. "
        "D77. Spec: § 3.2 L562(b)."
    )


# ===========================================================================
# Assertion (c): --registry-id 12345 parses
# ===========================================================================


def test_c_registry_id_parses():
    """(c) --registry-id 12345 parses without error.

    Per § 3.2 L540: --registry-id int (repeatable). The canonical args
    must accept a single integer registry ID + return a Namespace with
    registry_id == [12345] (action='append').

    D75 (canonical args), D77 Tier 0 assertion 3. Spec: § 3.2 L539-541.
    """
    mod = _load_tool_module()
    parser = mod._build_arg_parser()

    args = parser.parse_args(["--registry-id", "12345"])
    assert args.registry_id == [12345], (
        f"--registry-id 12345 must yield registry_id=[12345] (action=append). "
        f"Got: {args.registry_id!r}. Spec: § 3.2 L539-541."
    )
    # Verify --apply is False by default per § 1.2 dry-run-default
    assert args.apply is False, (
        f"--apply must default to False (dry-run is default per § 1.2). "
        f"Got: {args.apply!r}."
    )


# ===========================================================================
# Assertion (d): --registry-id + --source mutex
# ===========================================================================


def test_d_registry_id_plus_source_mutex():
    """(d) --registry-id + --source together raises arg-parse error.

    Per § 3.2 L520-522: '--registry-id Mutually exclusive with --source /
    --table filters'. argparse cannot express this declaratively (multi-
    arg vs single-arg), so _validate_args() enforces it.

    D75 (canonical args), D77 Tier 0 assertion 4 + 'mutually exclusive'
    contract. Spec: § 3.2 L520-522 + L562(d).
    """
    mod = _load_tool_module()
    parser = mod._build_arg_parser()

    # First parse should succeed at argparse level
    args = parser.parse_args([
        "--registry-id", "12345",
        "--source", "DNA",
        "--table", "ACCT",
    ])
    # Now _validate_args should raise SystemExit (parser.error())
    with pytest.raises(SystemExit) as exc_info:
        mod._validate_args(args, parser)
    assert exc_info.value.code != 0, (
        f"--registry-id + --source must exit non-zero (mutex). "
        f"Got: {exc_info.value.code!r}. Spec: § 3.2 L520-522 + L562(d)."
    )


# ===========================================================================
# Assertion (e): Successful verify -> exit 0
# ===========================================================================


def test_e_success_returns_exit_0():
    """(e) Mocked verify_parquet_snapshot returning ParquetVerifyResult -> exit 0.

    Per § 3.2 L499 + L557: VERIFIED verdict -> exit 0 success. Verifies
    the wrapper correctly classifies a successful M3 return.

    D74 (exit 0 = success), D77 Tier 0 assertion 5. Spec: § 3.2 L562(e).
    """
    mod = _load_tool_module(verify_return_value=_make_verify_result())
    assert mod is not None

    result = _call_main(
        mod,
        registry_ids=[_REGISTRY_ID_OK],
        apply=True,
    )

    exit_code = result.get("exit_code") if isinstance(result, dict) else None
    assert exit_code == EXIT_SUCCESS, (
        f"Successful verify must yield exit {EXIT_SUCCESS}. "
        f"Got: {exit_code!r}. Spec: § 3.2 L562(e)."
    )


# ===========================================================================
# Assertion (f): RegistryStatusInvalid -> exit 2
# ===========================================================================


def test_f_status_invalid_returns_exit_2():
    """(f) Mocked verify_parquet_snapshot raising RegistryStatusInvalid -> exit 2.

    Per § 3.2 L535: 'RegistryStatusInvalid -> exit 2 (FATAL — caller passed
    a registry_id in the wrong state)'.

    D68 (PipelineFatalError -> exit 2), D74, D77 Tier 0 assertion 6.
    Spec: § 3.2 L535 + L562(f).
    """
    from utils.errors import RegistryStatusInvalid

    err = RegistryStatusInvalid(
        f"RegistryId {_REGISTRY_ID_BAD_STATUS} status mismatch (test fixture)",
        metadata={
            "registry_id": _REGISTRY_ID_BAD_STATUS,
            "current_status": "purged",
            "attempted_status": "verified",
        },
    )
    mod = _load_tool_module(verify_side_effect=err)
    assert mod is not None

    result = _call_main(
        mod,
        registry_ids=[_REGISTRY_ID_BAD_STATUS],
        apply=True,
    )

    exit_code = result.get("exit_code") if isinstance(result, dict) else None
    assert exit_code == EXIT_FATAL, (
        f"RegistryStatusInvalid must yield exit {EXIT_FATAL} (fatal). "
        f"Got: {exit_code!r}. "
        "Per D68 + D74: RegistryStatusInvalid = PipelineFatalError -> exit 2. "
        "Spec: § 3.2 L535 + L562(f)."
    )


# ===========================================================================
# Assertion (g): RegistryFileNotFound -> exit 1
# ===========================================================================


def test_g_file_not_found_returns_exit_1():
    """(g) Mocked verify_parquet_snapshot raising RegistryFileNotFound -> exit 1.

    Per § 3.2 L534: 'RegistryFileNotFound -> exit 1 (file is missing;
    operator should call separate mark_missing workflow)'.

    D68 (PipelineRetryableError -> exit 1), D74, D77 Tier 0 assertion 7.
    Spec: § 3.2 L534 + L562(g).
    """
    from utils.errors import RegistryFileNotFound

    err = RegistryFileNotFound(
        f"Parquet file absent for RegistryId {_REGISTRY_ID_MISSING} (test fixture)",
        metadata={
            "registry_id": _REGISTRY_ID_MISSING,
            "file_path": "/mnt/parquet/dna/acct/missing.parquet",
        },
    )
    mod = _load_tool_module(verify_side_effect=err)
    assert mod is not None

    result = _call_main(
        mod,
        registry_ids=[_REGISTRY_ID_MISSING],
        apply=True,
    )

    exit_code = result.get("exit_code") if isinstance(result, dict) else None
    assert exit_code == EXIT_OPERATIONAL_FAILURE, (
        f"RegistryFileNotFound must yield exit {EXIT_OPERATIONAL_FAILURE} "
        f"(retryable). Got: {exit_code!r}. "
        "Per D68 + D74: RegistryFileNotFound = PipelineRetryableError -> exit 1. "
        "Spec: § 3.2 L534 + L562(g)."
    )


# ===========================================================================
# Assertion (h): --dry-run does NOT call verify_parquet_snapshot
# ===========================================================================


def test_h_dry_run_does_not_call_verify_snapshot():
    """(h) --dry-run does NOT call verify_parquet_snapshot.

    Per § 3.2 L562(h): '--dry-run does NOT call verify_parquet_snapshot
    (verifies via mocked SHA-256 + file existence only, then exits)'.

    The tool computes SHA + checks file existence itself in dry-run mode.
    M3's verify_parquet_snapshot is only invoked in --apply mode (it has
    the side effect of flipping Status). This separation is critical for
    the dry-run contract per § 1.2.

    D75 (dry-run default for side-effecting tools), D77 Tier 0 assertion 8.
    Spec: § 3.2 L562(h).
    """
    mod = _load_tool_module()
    assert mod is not None

    # Configure registry row read to return a row that doesn't exist on disk
    # so the dry-run path emits a MISSING verdict (no SHA needed).
    mod._test_cursor.fetchone.return_value = (
        "/nonexistent/path/12345.parquet",
        "created",
        "b" * 64,
        "c" * 64,
        100_000,
    )

    result = _call_main(
        mod,
        registry_ids=[_REGISTRY_ID_OK],
        apply=False,  # dry-run
    )

    # M3 verify_parquet_snapshot must NOT have been called
    verify_mock = mod._test_registry_client.verify_parquet_snapshot
    assert verify_mock.call_count == 0, (
        f"--dry-run must NOT call M3 verify_parquet_snapshot. "
        f"Got {verify_mock.call_count} calls: "
        f"{verify_mock.call_args_list!r}. "
        "Spec: § 3.2 L562(h)."
    )
    # Tool should still return a result with a verdict
    assert isinstance(result, dict), (
        f"Dry-run must return a result dict. Got: {type(result)!r}."
    )


# ===========================================================================
# Runtime ceiling assertion — Tier 0 must complete < 5 s (D67)
# ===========================================================================


def test_tier0_runtime_ceiling():
    """Tier 0 full suite mock-invocation completes < 5 s (D67 ceiling).

    Verifies that the smoke test itself does not incur external I/O.
    Runs all primary operations (import + dry-run + apply + error) under
    the 5-second ceiling mandated by D67.

    D67 (runtime ceiling < 5s per module). Spec: § 3.2 L562 preamble.
    """
    start = time.monotonic()

    mod = _load_tool_module()
    assert mod is not None

    _call_main(mod, registry_ids=[_REGISTRY_ID_OK], apply=False)
    _call_main(mod, registry_ids=[_REGISTRY_ID_OK], apply=True)

    elapsed = time.monotonic() - start
    assert elapsed < 5.0, (
        f"Tier 0 mock invocations exceeded 5s ceiling: {elapsed:.2f}s. "
        "D67 mandates < 5s for Tier 0 smoke tests (no external deps). "
        "Check for live DB calls or network I/O that bypassed mock."
    )
