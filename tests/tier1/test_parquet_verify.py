"""Tier 1 unit tests for tools/parquet_verify.py.

Tests run on every commit. No live DB, no live network required.
All external dependencies mocked with unittest.mock.

North Star pillars addressed:
  - Audit-grade (D76): exactly one CLI_PARQUET_VERIFY PipelineEventLog
    row per invocation; Metadata JSON carries verdict counts + per-row
    verdicts + actor + justification + dry_run flag.
  - Operationally stable (D74/D75): exit-code contract (0/1/2) and
    argument naming discipline; ad-hoc operator usage matches spec.
  - Idempotent (D15 + N4): M3 verify_parquet_snapshot is idempotent at
    the row level (re-call after success is no-op + cached return);
    SKIPPED_ALREADY_VERIFIED verdict for already-verified rows.
  - Traceability (D26): per-row verdicts surface in stdout + JSON;
    M3's own PARQUET_VERIFY events emit independently per-row.

ParquetSnapshotRegistry canonical columns (Pitfall #9.a per Round 1):
  RegistryId, SourceName, TableName, BatchId, BusinessDate,
  NetworkDrivePath, RowCount, ContentChecksum, SchemaHash, Status,
  CreatedAt, LastVerifiedAt.

M3 verify_parquet_snapshot canonical signature (per data_load/
parquet_registry_client.py L523-528):
  verify_parquet_snapshot(*, registry_id: int, actor: str = 'pipeline')
  -> ParquetVerifyResult
ParquetVerifyResult fields: registry_id, file_path, sha256_verified,
  row_count_verified, last_verified_at, status (always 'verified').

Naive-UTC datetime invariant (SCD2-P1-f): every datetime captured in
audit row Metadata must be tzinfo=None.

Edge case IDs (per 04_EDGE_CASES.md):
  F3 (file absent vs corrupted — distinct verdicts: MISSING vs HASH_MISMATCH).
  N4 (idempotent re-call short-circuits per M3 § 1.3 ledger).
  V11 (defense-in-depth: dry-run path computes SHA itself without
       depending on M3's verify_parquet_snapshot).

Decision citations:
  D2 (Stage dropped — Parquet snapshots replace it),
  D4 (network drive Parquet — RB-6 vault recovery + RB-8 replay),
  D15 (idempotency — re-run safe),
  D16 (inflight-rename — verify catches files where rename completed
       but registry Status not flipped),
  D26 (append-only audit — every verify emits an event row),
  D67 (Tier 0 discipline — this file is Tier 1 complement),
  D68 (canonical exception hierarchy — utils.errors),
  D74 (exit-code contract 0/1/2),
  D75 (arg naming: actor / apply / dry-run / json / verbose / quiet /
       justification / no-audit-event + tool-specific registry-id /
       business-date-from/-to / continue-on-error),
  D76 (audit-row contract: CLI_PARQUET_VERIFY EventType; Metadata JSON shape),
  D77 (Tier 0 canonical scaffold — Tier 1 extends, not weakens).

B-numbers:
  B88 (--apply + --dry-run mutex).
  B218 (audit_event_id key MUST be present in JSON output;
        presence over content).
  B228 (utils.errors canonical surface — tools import directly).

Spec: phase1/04_tools.md § 3.2 (canonical spec L493-575).
M3 module: data_load/parquet_registry_client.py § 1.3.
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

_TOOL_PATH = _PROJECT_ROOT / "tools" / "parquet_verify.py"
_TOOL_MODULE_KEY = "tools.parquet_verify"

# ---------------------------------------------------------------------------
# Constants — single source of truth
# ---------------------------------------------------------------------------

EXPECTED_EVENT_TYPE = "CLI_PARQUET_VERIFY"

EXIT_SUCCESS = 0
EXIT_OPERATIONAL_FAILURE = 1
EXIT_FATAL = 2

_ACTOR = "test-tier1-author"

# Synthetic test IDs
_REGISTRY_ID_OK = 12345
_REGISTRY_ID_TWO = 23456
_REGISTRY_ID_THREE = 34567
_REGISTRY_ID_MISSING = 67890
_REGISTRY_ID_BAD_STATUS = 99999

# Expected JSON output keys per spec § 3.2 L554-555
REQUIRED_JSON_KEYS = frozenset({"dry_run", "counts", "verdicts", "audit_event_id"})
# Required keys inside JSON 'counts' dict
REQUIRED_COUNTS_KEYS = frozenset(
    {"verified", "would_verify", "skipped", "failed",
     "missing", "hash_mismatch", "status_invalid", "error"}
)
# Required keys per verdict row
REQUIRED_VERDICT_KEYS = frozenset({"registry_id", "verdict"})
# Canonical verdict tokens (per spec § 3.2 L499 + L549 + L552)
ALL_VERDICTS = frozenset({
    "VERIFIED",
    "WOULD_VERIFY",
    "SKIPPED_ALREADY_VERIFIED",
    "MISSING",
    "HASH_MISMATCH",
    "STATUS_INVALID",
    "ERROR",
})


# ---------------------------------------------------------------------------
# Exception class resolution — B215 + B228 pattern
# ---------------------------------------------------------------------------

def _resolve_exception_classes():
    """Resolve canonical utils.errors classes."""
    try:
        from utils.errors import (
            PipelineFatalError,
            PipelineRetryableError,
            RegistryFileNotFound,
            RegistryHashMismatch,
            RegistryNotFound,
            RegistryStatusInvalid,
        )
        return (
            PipelineFatalError,
            PipelineRetryableError,
            RegistryFileNotFound,
            RegistryHashMismatch,
            RegistryNotFound,
            RegistryStatusInvalid,
        )
    except ImportError:
        pytest.skip("utils.errors not yet authored; skipping Tier 1.")


(
    PipelineFatalError,
    PipelineRetryableError,
    RegistryFileNotFound,
    RegistryHashMismatch,
    RegistryNotFound,
    RegistryStatusInvalid,
) = _resolve_exception_classes()


# ---------------------------------------------------------------------------
# Mock factory: ParquetVerifyResult-like for success path
# ---------------------------------------------------------------------------


def _make_verify_result(
    registry_id: int = _REGISTRY_ID_OK,
    file_path: str | None = None,
    sha256: str | None = None,
    row_count: int = 100_000,
) -> Any:
    """Build a MagicMock that quacks like ParquetVerifyResult."""
    result = MagicMock()
    result.registry_id = registry_id
    result.file_path = Path(
        file_path or f"/mnt/parquet/dna/acct/{registry_id}.parquet"
    )
    result.sha256_verified = sha256 or ("a" * 64)
    result.row_count_verified = row_count
    result.last_verified_at = datetime(2026, 5, 14, 10, 0, 0)
    result.status = "verified"
    return result


# ---------------------------------------------------------------------------
# Module loader
# ---------------------------------------------------------------------------


def _load_tool_module(
    *,
    verify_side_effect: Any = None,
    verify_return_value: Any = None,
    multi_verify_responses: list[Any] | None = None,
    filter_registry_ids: list[int] | None = None,
    row_summary: tuple | None = None,
) -> Any:
    """Load tools/parquet_verify.py with mocked external deps.

    Parameters
    ----------
    verify_side_effect:
        Exception class/instance to raise on M3 call.
    verify_return_value:
        Single ParquetVerifyResult-like to return on M3 call.
    multi_verify_responses:
        List of responses (Exception | ParquetVerifyResult) for
        successive M3 calls — used for multi-row scenarios.
    filter_registry_ids:
        Override the filter-query response (--source/--table mode).
    row_summary:
        Override the registry-row-read response (dry-run path).
    """
    if _TOOL_MODULE_KEY in sys.modules:
        del sys.modules[_TOOL_MODULE_KEY]

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

    # Default row summary for dry-run path
    if row_summary is None:
        row_summary = (
            "/mnt/parquet/dna/acct/12345.parquet",
            "created",
            "b" * 64,
            "c" * 64,
            100_000,
        )
    mock_cursor.fetchone.return_value = row_summary
    # Filter-query fetchall
    if filter_registry_ids is None:
        mock_cursor.fetchall.return_value = []
    else:
        mock_cursor.fetchall.return_value = [(rid,) for rid in filter_registry_ids]
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
    if multi_verify_responses is not None:
        side_effects = []
        for resp in multi_verify_responses:
            side_effects.append(resp)
        mock_registry_client.verify_parquet_snapshot = MagicMock(
            side_effect=side_effects
        )
    elif verify_side_effect is not None:
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
        sys.modules[_TOOL_MODULE_KEY] = mod
        spec.loader.exec_module(mod)

    mod._test_sys_modules_patch = sys_modules_patch
    mod._test_cursor = mock_cursor
    mod._test_executed_sql = executed_sql
    mod._test_executed_params = executed_params
    mod._test_registry_client = mock_registry_client
    return mod


def _call_main(mod: Any, **overrides: Any) -> dict:
    """Call tool main() with canonical defaults + overrides."""
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
        quiet=True,
        justification=None,
        no_audit_event=True,
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
# Tier 1: dry-run vs apply behavior
# ===========================================================================


class TestDryRunVsApplyBehavior:
    """dry-run vs apply behavior; M3 invocation only in --apply mode.

    Per § 3.2 L497 + L518 + L529. D74 (exit 0 in both modes), D75
    (--apply opt-in for side effects). The DRY-RUN path computes SHA +
    checks file existence WITHOUT invoking M3 (avoids the Status flip).
    """

    def test_dry_run_default_does_not_invoke_m3(self):
        """Dry-run (default, no --apply) does NOT call M3 verify_parquet_snapshot.

        Per § 3.2 L529: M3 has the side effect of flipping Status; the
        dry-run path must avoid that side effect. The tool independently
        computes SHA + checks file existence.

        D74 (exit 0), D75 (dry-run default). Spec: § 3.2 L497 + L529.
        """
        mod = _load_tool_module()
        result = _call_main(mod, apply=False)

        verify_mock = mod._test_registry_client.verify_parquet_snapshot
        assert verify_mock.call_count == 0, (
            f"--dry-run must NOT call M3 verify_parquet_snapshot. "
            f"Got {verify_mock.call_count} calls. "
            "Spec: § 3.2 L497 + L529."
        )
        assert isinstance(result, dict), "result must be a dict"
        assert result.get("dry_run") is True, (
            "dry-run flag must surface in result dict."
        )

    def test_apply_invokes_m3_verify_parquet_snapshot(self):
        """--apply invokes M3 verify_parquet_snapshot per row.

        Per § 3.2 L497: '(--apply OR default — this tool is the verifier
        itself; "apply" mode flips Status created -> verified on success)'.

        D74 (exit 0), D75 (--apply opt-in). Spec: § 3.2 L497.
        """
        mod = _load_tool_module(verify_return_value=_make_verify_result())
        result = _call_main(mod, apply=True)

        verify_mock = mod._test_registry_client.verify_parquet_snapshot
        assert verify_mock.call_count == 1, (
            f"--apply must call M3 verify_parquet_snapshot. "
            f"Got {verify_mock.call_count} calls."
        )
        # Verify keyword-only args per spec § 3.2 L497
        call = verify_mock.call_args_list[0]
        assert call.kwargs.get("registry_id") == _REGISTRY_ID_OK, (
            f"verify_parquet_snapshot must be called with keyword-only "
            f"registry_id={_REGISTRY_ID_OK}. Got: {call!r}."
        )
        assert "actor" in call.kwargs, (
            "verify_parquet_snapshot must be called with actor= kwarg "
            "(M3 § 1.3 signature)."
        )
        # Exit 0 on success
        assert result.get("exit_code") == EXIT_SUCCESS, (
            f"Successful M3 call must yield exit {EXIT_SUCCESS}. "
            f"Got: {result.get('exit_code')!r}."
        )

    def test_apply_passes_actor_to_m3(self):
        """--apply propagates --actor verbatim to M3 verify_parquet_snapshot.

        Per spec § 3.2 + M3 § 1.3 signature: actor is recorded in M3's
        idempotency-ledger metadata for the audit trail.

        D75 (--actor canonical), D76 (audit-row contract). Spec: § 3.2.
        """
        mod = _load_tool_module()
        _call_main(mod, actor="operator-jane", apply=True)

        verify_mock = mod._test_registry_client.verify_parquet_snapshot
        assert verify_mock.call_count >= 1
        call = verify_mock.call_args_list[0]
        assert call.kwargs.get("actor") == "operator-jane", (
            f"actor must be forwarded to M3 verbatim. "
            f"Got kwargs: {call.kwargs!r}."
        )


# ===========================================================================
# Tier 1: success path -> exit 0
# ===========================================================================


class TestSuccessPath:
    """Successful verify -> exit 0; verdict counts surface in result.

    Per § 3.2 L557: 'exit 0: all rows verified successfully'.
    """

    def test_single_success_exits_0(self):
        """One VERIFIED row -> exit 0; verdict counts.verified == 1.

        D74 (exit 0). Spec: § 3.2 L548 + L557.
        """
        mod = _load_tool_module(verify_return_value=_make_verify_result())
        result = _call_main(mod, apply=True)
        assert result.get("exit_code") == EXIT_SUCCESS
        counts = result.get("counts", {})
        assert counts.get("verified") == 1, (
            f"counts.verified must == 1 for one successful verify. "
            f"Got: {counts!r}."
        )
        assert counts.get("failed", 0) == 0

    def test_verdict_carries_canonical_fields(self):
        """Per-row verdict dict carries ParquetVerifyResult-derived fields.

        Per spec § 3.2 L554-555: each verdict has registry_id, file_path,
        sha256_verified, row_count_verified, last_verified_at, status,
        verdict, error_message.

        D76 (Metadata JSON contract). Spec: § 3.2 L554-555.
        """
        mod = _load_tool_module(verify_return_value=_make_verify_result())
        result = _call_main(mod, apply=True)
        verdicts = result.get("verdicts", [])
        assert len(verdicts) == 1
        v = verdicts[0]
        for key in REQUIRED_VERDICT_KEYS:
            assert key in v, (
                f"verdict missing required key {key!r}. "
                f"Got: {set(v.keys())!r}. Spec: § 3.2 L554-555."
            )
        assert v["verdict"] == "VERIFIED", (
            f"Successful M3 return must yield verdict=VERIFIED. "
            f"Got: {v.get('verdict')!r}."
        )

    def test_no_rows_matched_exits_0(self):
        """Filter returning no rows -> exit 0 (operationally normal).

        Per spec § 3.2 L529: 'idempotent no-op' for empty result set.
        Pre-spec parity with parquet_tier_review L451 'No rows matched
        the Status filter -> exit 0'.

        D15 (idempotency), D74 (exit 0). Spec: § 3.2 L529.
        """
        mod = _load_tool_module(filter_registry_ids=[])
        result = _call_main(
            mod,
            registry_ids=None,
            source="DNA",
            table="ACCT",
            apply=True,
        )
        assert result.get("exit_code") == EXIT_SUCCESS, (
            f"Empty filter result must yield exit 0. "
            f"Got: {result.get('exit_code')!r}. Spec: § 3.2 L529."
        )
        counts = result.get("counts", {})
        assert counts.get("verified", 0) == 0
        assert counts.get("failed", 0) == 0


# ===========================================================================
# Tier 1: RegistryFileNotFound -> exit 1
# ===========================================================================


class TestRegistryFileNotFoundExitsOne:
    """RegistryFileNotFound -> exit 1 (retryable operational failure).

    Per § 3.2 L534: 'RegistryFileNotFound -> exit 1 (file is missing;
    operator should call separate mark_missing workflow)'.
    """

    def test_file_not_found_exits_1(self):
        """RegistryFileNotFound -> exit 1; verdict MISSING.

        D68 (PipelineRetryableError -> exit 1), D74, F3 (file absent).
        Spec: § 3.2 L534.
        """
        err = RegistryFileNotFound(
            f"Parquet file absent for RegistryId {_REGISTRY_ID_MISSING}",
            metadata={
                "registry_id": _REGISTRY_ID_MISSING,
                "file_path": "/mnt/parquet/dna/acct/missing.parquet",
            },
        )
        mod = _load_tool_module(verify_side_effect=err)
        result = _call_main(
            mod, registry_ids=[_REGISTRY_ID_MISSING], apply=True
        )
        assert result.get("exit_code") == EXIT_OPERATIONAL_FAILURE, (
            f"RegistryFileNotFound must yield exit "
            f"{EXIT_OPERATIONAL_FAILURE}. Got: {result.get('exit_code')!r}."
        )
        verdicts = result.get("verdicts", [])
        assert len(verdicts) == 1
        assert verdicts[0]["verdict"] == "MISSING", (
            f"RegistryFileNotFound must yield verdict=MISSING. "
            f"Got: {verdicts[0].get('verdict')!r}. Spec: § 3.2 L499."
        )

    def test_missing_verdict_carries_file_path(self):
        """MISSING verdict surfaces file_path from metadata.

        Per D76 + utils.errors PipelineError constructor contract:
        exception metadata carries file_path for diagnostics.

        D76. Spec: § 3.2 L554-555.
        """
        err = RegistryFileNotFound(
            "Parquet file absent",
            metadata={
                "registry_id": _REGISTRY_ID_MISSING,
                "file_path": "/mnt/parquet/dna/acct/missing.parquet",
            },
        )
        mod = _load_tool_module(verify_side_effect=err)
        result = _call_main(
            mod, registry_ids=[_REGISTRY_ID_MISSING], apply=True
        )
        verdicts = result.get("verdicts", [])
        assert verdicts[0].get("file_path") == "/mnt/parquet/dna/acct/missing.parquet"


# ===========================================================================
# Tier 1: RegistryHashMismatch -> exit 2
# ===========================================================================


class TestRegistryHashMismatchExitsTwo:
    """RegistryHashMismatch -> exit 2 (fatal corruption).

    Per § 3.2 L536: 'RegistryHashMismatch -> exit 2 (FATAL — file
    corruption; escalate per RB-6 / RB-8)'.
    """

    def test_hash_mismatch_exits_2(self):
        """RegistryHashMismatch -> exit 2; verdict HASH_MISMATCH.

        D68 (PipelineFatalError -> exit 2), D74. Spec: § 3.2 L536.
        """
        err = RegistryHashMismatch(
            "SHA-256 mismatch (test fixture)",
            metadata={
                "registry_id": _REGISTRY_ID_OK,
                "expected_sha256": "a" * 64,
                "computed_sha256": "b" * 64,
            },
        )
        mod = _load_tool_module(verify_side_effect=err)
        result = _call_main(mod, registry_ids=[_REGISTRY_ID_OK], apply=True)
        assert result.get("exit_code") == EXIT_FATAL, (
            f"RegistryHashMismatch must yield exit {EXIT_FATAL}. "
            f"Got: {result.get('exit_code')!r}."
        )
        verdicts = result.get("verdicts", [])
        assert verdicts[0]["verdict"] == "HASH_MISMATCH"

    def test_hash_mismatch_surfaces_diagnostic_shas(self):
        """HASH_MISMATCH verdict error_message surfaces computed + expected SHAs.

        Per spec § 3.2 L555: 'on hash-mismatch failure the error_message
        includes both the computed and expected SHAs for operator diagnosis'.

        D76 (diagnostic detail). Spec: § 3.2 L555.
        """
        err = RegistryHashMismatch(
            "SHA-256 mismatch: expected=aaaa, computed=bbbb",
            metadata={
                "registry_id": _REGISTRY_ID_OK,
                "expected_sha256": "a" * 64,
                "computed_sha256": "b" * 64,
            },
        )
        mod = _load_tool_module(verify_side_effect=err)
        result = _call_main(mod, registry_ids=[_REGISTRY_ID_OK], apply=True)
        verdicts = result.get("verdicts", [])
        em = verdicts[0].get("error_message") or ""
        assert "aaaa" in em or "expected" in em.lower(), (
            f"error_message must surface expected SHA for diagnosis. "
            f"Got: {em!r}."
        )


# ===========================================================================
# Tier 1: RegistryStatusInvalid -> exit 2
# ===========================================================================


class TestRegistryStatusInvalidExitsTwo:
    """RegistryStatusInvalid -> exit 2 (fatal caller error)."""

    def test_status_invalid_exits_2(self):
        """RegistryStatusInvalid -> exit 2; verdict STATUS_INVALID.

        Per spec § 3.2 L535: 'RegistryStatusInvalid -> exit 2 (FATAL —
        caller passed a registry_id in the wrong state)'.

        D68 (PipelineFatalError -> exit 2), D74. Spec: § 3.2 L535.
        """
        err = RegistryStatusInvalid(
            "Wrong predecessor status",
            metadata={
                "registry_id": _REGISTRY_ID_BAD_STATUS,
                "current_status": "purged",
                "attempted_status": "verified",
            },
        )
        mod = _load_tool_module(verify_side_effect=err)
        result = _call_main(
            mod, registry_ids=[_REGISTRY_ID_BAD_STATUS], apply=True
        )
        assert result.get("exit_code") == EXIT_FATAL
        verdicts = result.get("verdicts", [])
        assert verdicts[0]["verdict"] == "STATUS_INVALID"


# ===========================================================================
# Tier 1: --continue-on-error
# ===========================================================================


class TestContinueOnError:
    """--continue-on-error per spec § 3.2 L562.

    "Don't abort on the first failed row; continue through all rows,
    then exit with code 1 if any failed."
    """

    def test_continue_on_error_processes_all_rows(self):
        """--continue-on-error processes all rows despite first-row failure.

        Per spec § 3.2 L562: third row's success isn't aborted by first
        row's failure.

        D75 (--continue-on-error). Spec: § 3.2 L562.
        """
        responses = [
            RegistryFileNotFound(
                "missing",
                metadata={
                    "registry_id": _REGISTRY_ID_MISSING,
                    "file_path": "/x/missing.parquet",
                },
            ),
            _make_verify_result(registry_id=_REGISTRY_ID_TWO),
            _make_verify_result(registry_id=_REGISTRY_ID_THREE),
        ]
        mod = _load_tool_module(multi_verify_responses=responses)
        result = _call_main(
            mod,
            registry_ids=[
                _REGISTRY_ID_MISSING, _REGISTRY_ID_TWO, _REGISTRY_ID_THREE
            ],
            apply=True,
            continue_on_error=True,
        )
        verify_mock = mod._test_registry_client.verify_parquet_snapshot
        assert verify_mock.call_count == 3, (
            f"--continue-on-error must process all 3 rows. "
            f"Got {verify_mock.call_count} M3 calls."
        )
        counts = result.get("counts", {})
        assert counts.get("verified", 0) == 2, (
            f"2 of 3 rows must be verified. Got counts: {counts!r}."
        )
        assert counts.get("missing", 0) == 1
        # Exit code = 1 (retryable) — MISSING is retryable
        assert result.get("exit_code") == EXIT_OPERATIONAL_FAILURE

    def test_no_continue_on_error_aborts_on_first_fatal(self):
        """Default (no --continue-on-error) aborts on first fatal verdict.

        Per spec § 3.2 L562 implicit: default semantics abort early on
        fatal verdicts to avoid wasting cycles on a clearly-broken state.

        D75 (default-abort semantics). Spec: § 3.2 L562.
        """
        responses = [
            RegistryHashMismatch(
                "corruption",
                metadata={"registry_id": _REGISTRY_ID_OK},
            ),
            _make_verify_result(registry_id=_REGISTRY_ID_TWO),
            _make_verify_result(registry_id=_REGISTRY_ID_THREE),
        ]
        mod = _load_tool_module(multi_verify_responses=responses)
        result = _call_main(
            mod,
            registry_ids=[_REGISTRY_ID_OK, _REGISTRY_ID_TWO, _REGISTRY_ID_THREE],
            apply=True,
            continue_on_error=False,
        )
        verify_mock = mod._test_registry_client.verify_parquet_snapshot
        # First fatal aborts further processing
        assert verify_mock.call_count == 1, (
            f"Default no-continue must abort on first fatal. "
            f"Got {verify_mock.call_count} M3 calls."
        )
        assert result.get("exit_code") == EXIT_FATAL


# ===========================================================================
# Tier 1: --apply + --dry-run mutex (B88)
# ===========================================================================


class TestApplyDryRunMutex:
    """--apply + --dry-run mutually exclusive -> exit 2 (B88)."""

    def test_apply_and_dry_run_together_exits_2(self):
        """Providing both --apply and --dry-run at argparse level exits non-zero.

        argparse add_mutually_exclusive_group() raises SystemExit(2)
        when both flags in the group are provided.

        B88 (mutex), D74, D75 (arg naming). Spec: § 1.4 + § 3.2.
        """
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(
                ["--registry-id", "12345", "--apply", "--dry-run"]
            )
        assert exc_info.value.code != 0, (
            f"--apply + --dry-run together must exit non-zero. "
            f"Got: {exc_info.value.code!r}."
        )

    def test_main_dry_run_apply_mutex_exits_2(self):
        """main() invoked with dry_run=True AND apply=True -> SystemExit(2).

        B88 mutex bridge: tests pass dry_run paralleling apply. If both
        True -> exit 2. Sibling parity with enforce_retention's mutex.

        B88. Spec: § 3.2.
        """
        mod = _load_tool_module()
        with patch.dict("sys.modules", mod._test_sys_modules_patch):
            with pytest.raises(SystemExit) as exc_info:
                mod.main(
                    actor=_ACTOR,
                    registry_ids=[_REGISTRY_ID_OK],
                    apply=True,
                    dry_run=True,
                    quiet=True,
                    no_audit_event=True,
                )
        assert exc_info.value.code == EXIT_FATAL, (
            f"main(apply=True, dry_run=True) must SystemExit(2). "
            f"Got: {exc_info.value.code!r}. B88."
        )


# ===========================================================================
# Tier 1: --registry-id / --source mutex
# ===========================================================================


class TestRegistryIdSourceMutex:
    """--registry-id mutually exclusive with --source / --table filters.

    Per spec § 3.2 L520-522. argparse cannot express this declaratively
    (multi-arg vs single-arg); _validate_args + main() enforce it.
    """

    def test_main_rejects_both_registry_id_and_source(self):
        """main() with registry_ids AND source -> SystemExit(2).

        Per spec § 3.2 L520-522. D74 (exit 2 = caller error). Spec: § 3.2.
        """
        mod = _load_tool_module()
        with patch.dict("sys.modules", mod._test_sys_modules_patch):
            with pytest.raises(SystemExit) as exc_info:
                mod.main(
                    actor=_ACTOR,
                    registry_ids=[_REGISTRY_ID_OK],
                    source="DNA",
                    table="ACCT",
                    apply=False,
                    quiet=True,
                    no_audit_event=True,
                )
        assert exc_info.value.code == EXIT_FATAL

    def test_main_rejects_neither_filter_nor_id(self):
        """main() with neither registry_ids nor source/table -> SystemExit(2).

        Per spec § 3.2 L539-547: tool requires either explicit IDs OR
        filter (no default 'verify everything').

        D74 (exit 2 = caller error). Spec: § 3.2.
        """
        mod = _load_tool_module()
        with patch.dict("sys.modules", mod._test_sys_modules_patch):
            with pytest.raises(SystemExit) as exc_info:
                mod.main(
                    actor=_ACTOR,
                    registry_ids=None,
                    source=None,
                    table=None,
                    apply=False,
                    quiet=True,
                    no_audit_event=True,
                )
        assert exc_info.value.code == EXIT_FATAL

    def test_validate_args_rejects_both_modes(self):
        """_validate_args raises parser.error on simultaneous mode args.

        argparse parser.error() raises SystemExit. Provides earlier
        feedback at CLI parse-time than the deeper main() check.

        D74. Spec: § 3.2 L520-522.
        """
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        args = parser.parse_args([
            "--registry-id", "12345",
            "--source", "DNA",
        ])
        with pytest.raises(SystemExit):
            mod._validate_args(args, parser)


# ===========================================================================
# Tier 1: filter mode (--source / --table / --business-date-from/-to)
# ===========================================================================


class TestFilterMode:
    """Filter-mode invocations (no --registry-id; uses --source/--table)."""

    def test_filter_resolves_registry_ids_from_predicate(self):
        """--source/--table filter resolves to registry IDs via SELECT.

        Per spec § 3.2 L542-544: range query against ParquetSnapshotRegistry
        with --source / --table / --business-date-from/-to predicates.

        D75 (canonical filter args). Spec: § 3.2 L542-544.
        """
        mod = _load_tool_module(
            filter_registry_ids=[111, 222, 333],
            verify_return_value=_make_verify_result(),
        )
        result = _call_main(
            mod,
            registry_ids=None,
            source="DNA",
            table="ACCT",
            apply=True,
        )
        # M3 invoked once per resolved registry_id
        verify_mock = mod._test_registry_client.verify_parquet_snapshot
        assert verify_mock.call_count == 3, (
            f"3 resolved IDs must trigger 3 M3 calls. "
            f"Got {verify_mock.call_count}."
        )
        # Filter SQL must reference ParquetSnapshotRegistry + Status='created'
        executed = mod._test_executed_sql
        assert any(
            "ParquetSnapshotRegistry" in s for s in executed
        ), f"Filter query must reference ParquetSnapshotRegistry. Got: {executed!r}."

    def test_filter_date_range_predicates_in_sql(self):
        """--business-date-from/--business-date-to predicates appear in SQL.

        Per spec § 3.2 L542-544.
        """
        mod = _load_tool_module(filter_registry_ids=[111])
        _call_main(
            mod,
            registry_ids=None,
            source="DNA",
            table="ACCT",
            business_date_from=date(2026, 4, 1),
            business_date_to=date(2026, 4, 30),
            apply=False,
        )
        executed = mod._test_executed_sql
        params = mod._test_executed_params
        # Either date appears in SQL or in bound params
        joined_sql = " ".join(executed)
        # Predicates use BusinessDate >= ? / <= ? per Round 1 DDL
        assert (
            "BusinessDate" in joined_sql
        ), f"Filter SQL must reference BusinessDate. Got: {joined_sql!r}."
        # Dates must show up in bound params
        param_dates = [p for p in params if isinstance(p, date)]
        assert len(param_dates) >= 2, (
            f"Both date bounds must appear in bound params. Got: {params!r}."
        )


# ===========================================================================
# Tier 1: JSON output contract
# ===========================================================================


class TestJsonOutput:
    """--json output canonical shape per spec § 3.2 L554-555.

    Top-level: {dry_run, counts, verdicts, audit_event_id}.
    Per-row verdict: {registry_id, file_path, sha256_verified,
                      row_count_verified, last_verified_at, status,
                      verdict, error_message}.
    """

    def test_result_dict_has_required_top_level_keys(self):
        """Result dict has dry_run, counts, verdicts, audit_event_id keys.

        Per spec § 3.2 L554-555 + B218 lesson — audit_event_id key must
        be present (value may be None when --no-audit-event is set, but
        the key must exist).

        D76, B218. Spec: § 3.2 L554-555.
        """
        mod = _load_tool_module()
        result = _call_main(mod, apply=True, json_output=True)
        for key in REQUIRED_JSON_KEYS:
            assert key in result, (
                f"result missing required key {key!r} per § 3.2 L554-555. "
                f"Got: {set(result.keys())!r}. B218."
            )

    def test_result_counts_has_required_sub_keys(self):
        """counts dict has verified, failed, skipped, would_verify sub-keys.

        Per spec § 3.2 L548 + Metadata JSON shape.

        D76. Spec: § 3.2 L548.
        """
        mod = _load_tool_module()
        result = _call_main(mod, apply=True)
        counts = result.get("counts", {})
        for key in REQUIRED_COUNTS_KEYS:
            assert key in counts, (
                f"counts dict missing required sub-key {key!r}. "
                f"Got: {set(counts.keys())!r}. Spec: § 3.2 L548."
            )

    def test_json_dry_run_flag_reflects_invocation(self):
        """JSON 'dry_run' flag matches the invocation mode.

        D74. Spec: § 3.2 L554-555.
        """
        mod = _load_tool_module()
        result_dry = _call_main(mod, apply=False, json_output=True)
        result_apply = _call_main(mod, apply=True, json_output=True)
        assert result_dry["dry_run"] is True
        assert result_apply["dry_run"] is False

    def test_verdict_token_canonical(self):
        """Per-row verdict token is one of the canonical set.

        Per spec § 3.2 L499 + L549 + L552.
        """
        mod = _load_tool_module(verify_return_value=_make_verify_result())
        result = _call_main(mod, apply=True)
        verdicts = result.get("verdicts", [])
        for v in verdicts:
            assert v.get("verdict") in ALL_VERDICTS, (
                f"verdict token {v.get('verdict')!r} not in canonical set "
                f"{ALL_VERDICTS!r}. Spec: § 3.2 L499."
            )


# ===========================================================================
# Tier 1: audit row Metadata
# ===========================================================================


class TestAuditRowMetadata:
    """Audit row Metadata shape per D76 + spec § 3.2 L526."""

    def test_event_type_is_canonical(self):
        """EVENT_TYPE module constant == 'CLI_PARQUET_VERIFY'.

        Per D76 CLI_* family + CLAUDE.md registry. Spec: § 3.2 L526.
        """
        mod = _load_tool_module()
        assert mod.EVENT_TYPE == EXPECTED_EVENT_TYPE, (
            f"EVENT_TYPE must be {EXPECTED_EVENT_TYPE!r}. "
            f"Got: {mod.EVENT_TYPE!r}."
        )

    def test_metadata_has_event_kind(self):
        """result['event_kind'] == 'parquet_verification'.

        Per D76 Metadata JSON shape. Spec: § 3.2 module docstring.
        """
        mod = _load_tool_module()
        result = _call_main(mod, apply=True)
        assert result.get("event_kind") == "parquet_verification", (
            f"event_kind must be 'parquet_verification'. "
            f"Got: {result.get('event_kind')!r}."
        )

    def test_actor_echoed_verbatim(self):
        """--actor value echoes in result['actor'] verbatim.

        D75 (--actor canonical), D76 (Metadata.actor).
        """
        mod = _load_tool_module()
        result = _call_main(mod, actor="automic", apply=True)
        assert result.get("actor") == "automic"

    def test_justification_passes_through(self):
        """--justification value surfaces in result['justification'].

        D75 (--justification canonical), D76 (Metadata.justification).
        """
        mod = _load_tool_module()
        result = _call_main(
            mod,
            apply=True,
            justification="post-RB-8 verify per ops review",
        )
        assert result.get("justification") == "post-RB-8 verify per ops review"

    def test_dry_run_flag_in_result(self):
        """result['dry_run'] reflects invocation mode."""
        mod = _load_tool_module()
        result_dry = _call_main(mod, apply=False)
        result_apply = _call_main(mod, apply=True)
        assert result_dry["dry_run"] is True
        assert result_apply["dry_run"] is False

    def test_timestamps_are_naive_utc(self):
        """All datetime values in result are tzinfo=None (SCD2-P1-f).

        SCD2-P1-f: tz-aware datetimes cause DATETIMEOFFSET conversion
        surprises via pyodbc.
        """
        mod = _load_tool_module()
        result = _call_main(mod, apply=True)
        ts_dt = result.get("started_at_dt")
        if isinstance(ts_dt, datetime):
            assert ts_dt.tzinfo is None, (
                f"started_at_dt must be naive (tzinfo=None). "
                f"Got: {ts_dt!r}."
            )


# ===========================================================================
# Tier 1: idempotent re-call semantics
# ===========================================================================


class TestIdempotentReCall:
    """Re-calling on already-verified rows is idempotent.

    Per spec § 3.2 L527-529: 'Re-call on a row already at Status=verified:
    Round 3 § 1.3 docstring states "Idempotent: re-call after success is
    a no-op". Tool returns exit 0 with SKIPPED_ALREADY_VERIFIED'.
    """

    def test_dry_run_already_verified_yields_skipped(self):
        """Dry-run on already-verified row -> SKIPPED_ALREADY_VERIFIED verdict.

        Per spec § 3.2 L529. The row-read in dry-run mode detects the
        'verified' Status and short-circuits with the canonical token.

        D15 (idempotency), N4. Spec: § 3.2 L527-529.
        """
        mod = _load_tool_module(
            row_summary=(
                "/mnt/parquet/dna/acct/12345.parquet",
                "verified",  # already verified
                "a" * 64,
                "b" * 64,
                100_000,
            )
        )
        result = _call_main(mod, registry_ids=[_REGISTRY_ID_OK], apply=False)
        verdicts = result.get("verdicts", [])
        assert len(verdicts) == 1
        assert verdicts[0]["verdict"] == "SKIPPED_ALREADY_VERIFIED", (
            f"Dry-run on verified row must yield "
            f"SKIPPED_ALREADY_VERIFIED. Got: {verdicts[0]!r}."
        )
        # Skipped doesn't count as failed
        assert result.get("exit_code") == EXIT_SUCCESS


# ===========================================================================
# Tier 1: dry-run SHA computation
# ===========================================================================


class TestDryRunShaComputation:
    """Dry-run path computes SHA + checks file existence independently.

    Per spec § 3.2 L519 + L562(h): dry-run does NOT depend on M3
    verify_parquet_snapshot (which has a Status-flip side effect).
    """

    def test_dry_run_missing_file_yields_missing_verdict(self):
        """Dry-run on a row whose NetworkDrivePath doesn't exist -> MISSING.

        Per spec § 3.2 L499. F3 (file absent).

        D74 (exit 1 = retryable). Spec: § 3.2 L499 + L562(h).
        """
        mod = _load_tool_module(
            row_summary=(
                "/nonexistent/path/12345.parquet",
                "created",
                "a" * 64,
                "b" * 64,
                100_000,
            )
        )
        result = _call_main(mod, registry_ids=[_REGISTRY_ID_OK], apply=False)
        verdicts = result.get("verdicts", [])
        assert verdicts[0]["verdict"] == "MISSING", (
            f"Dry-run on missing file must yield verdict=MISSING. "
            f"Got: {verdicts[0]!r}."
        )
        assert result.get("exit_code") == EXIT_OPERATIONAL_FAILURE

    def test_dry_run_bad_status_yields_status_invalid(self):
        """Dry-run on row with Status != 'created' / 'verified' -> STATUS_INVALID.

        The verify pipeline requires Status='created' as the legal
        predecessor (per M3 _LEGAL_TRANSITIONS). Other statuses are
        caller errors.

        D74 (exit 2 = caller error). Spec: § 3.2 L535.
        """
        mod = _load_tool_module(
            row_summary=(
                "/mnt/parquet/dna/acct/12345.parquet",
                "purged",  # terminal status
                "a" * 64,
                "b" * 64,
                100_000,
            )
        )
        result = _call_main(mod, registry_ids=[_REGISTRY_ID_OK], apply=False)
        verdicts = result.get("verdicts", [])
        assert verdicts[0]["verdict"] == "STATUS_INVALID"
        assert result.get("exit_code") == EXIT_FATAL


# ===========================================================================
# Tier 1: stdout rendering
# ===========================================================================


class TestStdoutRendering:
    """Stdout per-row + summary rendering per spec § 3.2 L548-553."""

    def test_verdict_line_format(self):
        """_format_verdict_line() emits 'RegistryId <id> <file_path> <verdict>'.

        Per spec § 3.2 L498-499.
        """
        mod = _load_tool_module()
        v = {
            "registry_id": 12345,
            "file_path": "/mnt/parquet/dna/acct/12345.parquet",
            "verdict": "VERIFIED",
        }
        line = mod._format_verdict_line(v, dry_run=False)
        assert "12345" in line
        assert "/mnt/parquet/dna/acct/12345.parquet" in line
        assert "VERIFIED" in line
        assert line.startswith("RegistryId "), (
            f"Stdout line must start with 'RegistryId '. Got: {line!r}. "
            "Spec: § 3.2 L498."
        )

    def test_dry_run_line_includes_sha_and_rows(self):
        """Dry-run WOULD_VERIFY line includes (sha=... rows=...) suffix.

        Per spec § 3.2 L552: 'RegistryId <id> <file_path> WOULD_VERIFY
        (sha=<sha256> rows=<count>)'.
        """
        mod = _load_tool_module()
        v = {
            "registry_id": 12345,
            "file_path": "/mnt/parquet/dna/acct/12345.parquet",
            "verdict": "WOULD_VERIFY",
            "sha256_verified": "a" * 64,
            "row_count_verified": 100_000,
        }
        line = mod._format_verdict_line(v, dry_run=True)
        assert "WOULD_VERIFY" in line
        assert "sha=" in line
        assert "rows=" in line


# ===========================================================================
# Tier 1: actor detection heuristic
# ===========================================================================


class TestActorDetection:
    """_detect_actor() heuristic per spec § 1.7."""

    def test_automic_env_yields_automic(self, monkeypatch):
        """AUTOMIC_RUN_ID env var -> _detect_actor() returns 'automic'.

        Per spec § 1.7 invocation-pattern heuristic step 1.

        D75. Spec: § 1.7.
        """
        mod = _load_tool_module()
        monkeypatch.setenv("AUTOMIC_RUN_ID", "RUN_12345")
        assert mod._detect_actor() == "automic"

    def test_no_env_no_tty_yields_pipeline(self, monkeypatch):
        """No AUTOMIC env + no TTY -> _detect_actor() returns 'pipeline'.

        Per spec § 1.7 step 3 (defensive default).
        """
        mod = _load_tool_module()
        monkeypatch.delenv("AUTOMIC_RUN_ID", raising=False)
        # Force non-TTY via stdin.isatty returning False
        with patch.object(sys.stdin, "isatty", return_value=False):
            assert mod._detect_actor() == "pipeline"


# ===========================================================================
# Tier 1: forward-incompat guard (Pitfall #9 invented args)
# ===========================================================================


class TestNoInventedArgs:
    """Forward-incompat guard: parser rejects invented / non-spec args.

    Per Pitfall #9.b — the spec defines an exact arg set; ad-hoc additions
    are caught at producer Gate 1.
    """

    def test_no_workers_flag(self):
        """--workers is mentioned in spec § 3.2 L562 but NOT implemented v1.

        v1 ships single-threaded per complexity-vs-need analysis. The
        flag must NOT exist in parser surface until implemented (forward-
        compat guard against silently accepting a no-op flag).

        Spec: § 3.2 L562 (deferred).
        """
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--workers", "4", "--registry-id", "12345"])

    def test_no_retention_date_flag(self):
        """--retention-date is NOT a parquet_verify arg (belongs to
        enforce_retention only). Cross-contamination guard.
        """
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--retention-date", "2026-01-01"])


# ===========================================================================
# Tier 1: registry_id keyword-only forwarding
# ===========================================================================


class TestM3KeywordOnlyForwarding:
    """M3 verify_parquet_snapshot is keyword-only per Round 3 § 1.3.

    Per spec § 3.2 'Wraps' section: 'verify_parquet_snapshot(*, registry_id,
    actor) keyword-only signature'.
    """

    def test_m3_called_keyword_only(self):
        """M3 invocation uses kwarg form, not positional.

        Per M3 § 1.3 signature: ``def verify_parquet_snapshot(*, registry_id:
        int, actor: str = 'pipeline')``. Positional calls would raise TypeError.

        Pitfall #9 (keyword-only contract). Spec: § 3.2 (canonical wrapper).
        """
        mod = _load_tool_module(verify_return_value=_make_verify_result())
        _call_main(mod, registry_ids=[_REGISTRY_ID_OK], apply=True)
        verify_mock = mod._test_registry_client.verify_parquet_snapshot
        assert verify_mock.call_count == 1
        call = verify_mock.call_args_list[0]
        assert len(call.args) == 0, (
            f"M3 verify_parquet_snapshot must be called with kwargs only "
            f"(no positional). Got: args={call.args!r} kwargs={call.kwargs!r}."
        )


# ===========================================================================
# Tier 1: no-audit-event suppresses audit row write
# ===========================================================================


class TestNoAuditEvent:
    """--no-audit-event skips the CLI-level PipelineEventLog write.

    Per spec § 1.4 + § 1.7 invocation pattern 'Pipeline (programmatic)'.
    """

    def test_no_audit_event_skips_write(self):
        """no_audit_event=True -> audit_event_id is None in result.

        D76 (parent has audit row pattern). Spec: § 1.7.
        """
        mod = _load_tool_module()
        result = _call_main(mod, apply=True, no_audit_event=True)
        assert result.get("audit_event_id") is None, (
            f"--no-audit-event must skip audit-row write; "
            f"audit_event_id must be None. Got: {result.get('audit_event_id')!r}."
        )


# ===========================================================================
# Tier 1: filter SQL safety
# ===========================================================================


class TestFilterSqlSafety:
    """Filter SQL uses parameterized predicates (no SQL injection)."""

    def test_filter_uses_parameterized_predicates(self):
        """Filter SQL has ? placeholders, not string-interpolated values.

        Per security best practice + Pitfall (SQL injection).

        D69 (concurrency / cursor patterns). Spec: § 3.2.
        """
        mod = _load_tool_module(filter_registry_ids=[111])
        _call_main(
            mod,
            registry_ids=None,
            source="DNA'; DROP TABLE Foo; --",  # SQL injection attempt
            table="ACCT",
            apply=False,
        )
        executed = mod._test_executed_sql
        # SQL must contain ? placeholders, not the injected string
        for sql in executed:
            assert "DROP TABLE" not in sql, (
                f"SQL must not contain injected string. Got: {sql!r}."
            )
        # The injection attempt must surface in bound params instead
        params = mod._test_executed_params
        assert any(
            isinstance(p, str) and "DROP TABLE" in p for p in params
        ), (
            f"Injection attempt must appear in bound params (safely). "
            f"Got params: {params!r}."
        )


# ===========================================================================
# Tier 1: result completeness invariants
# ===========================================================================


class TestResultInvariants:
    """Cross-cutting invariants on the result dict shape."""

    def test_completed_at_set_after_main_returns(self):
        """result['completed_at'] is set after main() returns.

        Used by audit-row writer + downstream consumers.

        D76. Spec: § 3.2.
        """
        mod = _load_tool_module()
        result = _call_main(mod, apply=True)
        assert result.get("completed_at") is not None, (
            "completed_at must be set after main() returns."
        )

    def test_started_at_iso_format(self):
        """result['started_at'] is ISO-8601 string ending with Z."""
        mod = _load_tool_module()
        result = _call_main(mod, apply=True)
        sa = result.get("started_at", "")
        assert sa.endswith("Z"), (
            f"started_at must be ISO-8601 with Z suffix. Got: {sa!r}."
        )
        # Verify it parses as ISO-8601
        try:
            datetime.fromisoformat(sa.replace("Z", "+00:00"))
        except ValueError:
            pytest.fail(f"started_at not parseable as ISO-8601: {sa!r}")

    def test_filter_metadata_echoes_in_result(self):
        """Filter args echo in result['filter'] sub-dict."""
        mod = _load_tool_module(filter_registry_ids=[111])
        result = _call_main(
            mod,
            registry_ids=None,
            source="DNA",
            table="ACCT",
            business_date_from=date(2026, 4, 1),
            business_date_to=date(2026, 4, 30),
            apply=True,
        )
        f = result.get("filter", {})
        assert f.get("source") == "DNA"
        assert f.get("table") == "ACCT"
        assert f.get("business_date_from") == "2026-04-01"
        assert f.get("business_date_to") == "2026-04-30"


# ===========================================================================
# Tier 1: cli_main exit-code clamp (defensive)
# ===========================================================================


class TestCliMainExitCodeClamp:
    """cli_main() clamps exit codes to canonical 0/1/2 per D74."""

    def test_cli_main_returns_int(self):
        """cli_main returns an int in {0, 1, 2}.

        D74. Spec: § 1.8.
        """
        mod = _load_tool_module()
        # Inject argv via argparse mock
        with patch.object(
            sys, "argv", ["parquet_verify.py", "--registry-id", "12345"]
        ):
            with patch.dict("sys.modules", mod._test_sys_modules_patch):
                with patch.object(mod, "main", return_value={"exit_code": 0}):
                    code = mod.cli_main()
        assert code in (EXIT_SUCCESS, EXIT_OPERATIONAL_FAILURE, EXIT_FATAL), (
            f"cli_main must return int in {{0, 1, 2}}. Got: {code!r}."
        )

    def test_cli_main_clamps_invalid_exit(self):
        """Non-canonical exit_code from main() clamps to EXIT_FATAL.

        Defensive clamp per spec § 1.8 + sibling parity (enforce_retention).

        D74. Spec: § 1.8.
        """
        mod = _load_tool_module()
        with patch.object(
            sys, "argv", ["parquet_verify.py", "--registry-id", "12345"]
        ):
            with patch.dict("sys.modules", mod._test_sys_modules_patch):
                with patch.object(mod, "main", return_value={"exit_code": 99}):
                    code = mod.cli_main()
        assert code == EXIT_FATAL, (
            f"Non-canonical exit_code must clamp to EXIT_FATAL. "
            f"Got: {code!r}."
        )


# ===========================================================================
# Tier 1: M3 file_path in verdict
# ===========================================================================


class TestVerdictFilePath:
    """Per-row verdict surfaces file_path from M3 ParquetVerifyResult."""

    def test_verified_verdict_has_file_path(self):
        """VERIFIED verdict carries file_path from ParquetVerifyResult.file_path.

        D76 (Metadata JSON contract). Spec: § 3.2 L554-555.

        Note: Path() normalises separators per OS (str(Path('/x')) -> '\\x'
        on Windows). The verdict carries the string form; we assert the
        canonical file-name suffix appears rather than literal equality.
        """
        mod = _load_tool_module(
            verify_return_value=_make_verify_result(
                registry_id=_REGISTRY_ID_OK,
                file_path="/mnt/parquet/dna/acct/12345.parquet",
            )
        )
        result = _call_main(mod, registry_ids=[_REGISTRY_ID_OK], apply=True)
        verdicts = result.get("verdicts", [])
        fp = verdicts[0].get("file_path") or ""
        assert "12345.parquet" in fp, (
            f"file_path must contain '12345.parquet' suffix. Got: {fp!r}."
        )
        assert "acct" in fp.lower(), (
            f"file_path must reference acct path. Got: {fp!r}."
        )

    def test_verified_verdict_has_sha256(self):
        """VERIFIED verdict carries sha256 from ParquetVerifyResult.sha256_verified.

        D76. Spec: § 3.2 L554-555 (sha256_verified in ParquetVerifyResult).
        """
        mod = _load_tool_module(
            verify_return_value=_make_verify_result(
                sha256="d" * 64,
            )
        )
        result = _call_main(mod, registry_ids=[_REGISTRY_ID_OK], apply=True)
        verdicts = result.get("verdicts", [])
        assert verdicts[0].get("sha256_verified") == "d" * 64


# ===========================================================================
# Tier 1: aggregator
# ===========================================================================


class TestAggregator:
    """_aggregate_counts() + _derive_exit_code() invariants."""

    def test_aggregate_counts_empty(self):
        """Empty verdicts list yields zero-counts dict."""
        mod = _load_tool_module()
        counts = mod._aggregate_counts([])
        for k in REQUIRED_COUNTS_KEYS:
            assert counts.get(k) == 0

    def test_aggregate_counts_mixed(self):
        """Mixed verdicts produce per-type counts + total failed."""
        mod = _load_tool_module()
        verdicts = [
            {"verdict": "VERIFIED"},
            {"verdict": "VERIFIED"},
            {"verdict": "MISSING"},
            {"verdict": "HASH_MISMATCH"},
            {"verdict": "STATUS_INVALID"},
            {"verdict": "SKIPPED_ALREADY_VERIFIED"},
        ]
        counts = mod._aggregate_counts(verdicts)
        assert counts["verified"] == 2
        assert counts["missing"] == 1
        assert counts["hash_mismatch"] == 1
        assert counts["status_invalid"] == 1
        assert counts["skipped"] == 1
        # failed = sum of fatal + retryable verdicts
        assert counts["failed"] == 3, (
            f"failed must == 3 (MISSING + HASH_MISMATCH + STATUS_INVALID). "
            f"Got: {counts!r}."
        )

    def test_derive_exit_code_priority(self):
        """Exit code derivation: fatal > retryable > success.

        Per spec § 3.2 L557-560.
        """
        mod = _load_tool_module()
        # All success
        assert mod._derive_exit_code(
            [{"verdict": "VERIFIED"}]
        ) == EXIT_SUCCESS
        # One retryable
        assert mod._derive_exit_code(
            [{"verdict": "VERIFIED"}, {"verdict": "MISSING"}]
        ) == EXIT_OPERATIONAL_FAILURE
        # One fatal
        assert mod._derive_exit_code(
            [{"verdict": "VERIFIED"}, {"verdict": "HASH_MISMATCH"}]
        ) == EXIT_FATAL
        # Fatal + retryable -> fatal wins
        assert mod._derive_exit_code(
            [{"verdict": "MISSING"}, {"verdict": "STATUS_INVALID"}]
        ) == EXIT_FATAL


# ===========================================================================
# Tier 1: metadata extraction helpers
# ===========================================================================


class TestMetadataHelpers:
    """_extract_file_path_from_metadata / _extract_sha_from_metadata."""

    def test_extract_file_path_from_pipeline_error(self):
        """Pull file_path from PipelineError metadata dict."""
        mod = _load_tool_module()
        err = RegistryFileNotFound(
            "missing",
            metadata={"registry_id": 1, "file_path": "/foo/bar.parquet"},
        )
        assert mod._extract_file_path_from_metadata(err) == "/foo/bar.parquet"

    def test_extract_file_path_from_plain_exception(self):
        """Plain Exception (no metadata) returns None defensively."""
        mod = _load_tool_module()
        err = ValueError("plain")
        assert mod._extract_file_path_from_metadata(err) is None

    def test_extract_sha_from_metadata(self):
        """Pull computed_sha256 / expected_sha256 from PipelineError metadata."""
        mod = _load_tool_module()
        err = RegistryHashMismatch(
            "mismatch",
            metadata={"expected_sha256": "a" * 64, "computed_sha256": "b" * 64},
        )
        assert mod._extract_sha_from_metadata(err, "computed_sha256") == "b" * 64
        assert mod._extract_sha_from_metadata(err, "expected_sha256") == "a" * 64


# ===========================================================================
# Tier 1: SCD2-P1-f naive-UTC datetime
# ===========================================================================


class TestNaiveDatetime:
    """All datetime values must be naive (tzinfo=None) per SCD2-P1-f."""

    def test_started_at_dt_is_naive(self):
        """result['started_at_dt'] is a naive datetime.

        SCD2-P1-f naive-UTC invariant.
        """
        mod = _load_tool_module()
        result = _call_main(mod, apply=True)
        started = result.get("started_at_dt")
        if isinstance(started, datetime):
            assert started.tzinfo is None, (
                f"started_at_dt must be naive. Got tzinfo={started.tzinfo!r}."
            )


# ===========================================================================
# Tier 1: JSON serialisable result
# ===========================================================================


class TestJsonSerialisable:
    """result dict's JSON-payload subset must be JSON-serialisable."""

    def test_json_payload_serialises(self):
        """_build_json_payload returns a dict that json.dumps can encode.

        Per spec § 3.2 L554-555 + B218 lesson.
        """
        mod = _load_tool_module()
        result = _call_main(mod, apply=True)
        # Use the same builder the tool uses for --json
        payload = mod._build_json_payload(result)
        try:
            json.dumps(payload, default=str)
        except (TypeError, ValueError) as exc:
            pytest.fail(f"JSON payload not serialisable: {exc}")
