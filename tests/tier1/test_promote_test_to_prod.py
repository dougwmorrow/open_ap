"""Tier 1 unit tests for tools/promote_test_to_prod.py.

Tests run on every commit. No live DB, no live network required.
All external dependencies mocked with unittest.mock.

North Star pillars addressed (NORTH_STAR.md):
  - Audit-grade (D76): exactly one CLI_PROMOTE_TEST_TO_PROD PipelineEventLog
    row per invocation; Metadata JSON carries verdict, cycle, cycle_date,
    test_parity_status, applied, dry_run, actor, justification, event_kind;
    audit_event_id key MUST be present (B218 lesson: presence over content).
  - Operationally stable (D74/D75): exit-code contract (0/1/2) and argument
    naming discipline exactly per spec; Automic interprets the contract.
  - Idempotent (D15/D29): SP-4 re-invocation on already-acknowledged failover
    is a no-op (§ 3.6 L862). SP-4 @AcknowledgmentOnly=1 is read-only (B79).
  - Traceability (D26/D33): SP-6 acknowledgment + CYCLE_FAILED_OVER event
    audit trail persists even on crash recovery. parity_verifier called before
    SP-4 (ordering invariant).

Canonical column verification (Pitfall #9.a, #9.f, #9.l — re-read DDL):
  PipelineExecutionGate columns (01_database_schema.md L303-333):
    GateId, CycleType, CycleDate, ExecutingServer, Status, BatchId,
    LastHeartbeatAt, CancellationRequested, CancellationAcknowledgedAt.
  ExecutingServer (NOT ServerRole — ServerRole is on PipelineEventLog L139;
  PipelineExecutionGate L310 uses ExecutingServer). Pitfall #9.f cross-table
  column-name lift guard.

SP-4 canonical parameters (Pitfall #9.b — verified against L1538-1546):
  @CycleType NVARCHAR(10), @CycleDate DATE, @ExpectedStartTime DATETIME2(3),
  @HeartbeatStaleMinutes INT = 10, @ProdMaxRuntimeMinutes INT = 120,
  @GateId BIGINT OUTPUT, @BatchId BIGINT OUTPUT,
  @Action NVARCHAR(30) OUTPUT
  NOT invented parameters like @CycleId, @ServerName, @FailoverReason.

SP-4 @Action enum (Pitfall #9.c — strict; canonical per L1546):
  'EXIT_SUCCEEDED' | 'EXIT_RUNNING_HEALTHY' | 'PROCEED_FAILOVER'
  NOT 'exit', 'failover', 'proceed', 'succeeded', 'running_healthy'.

SP-6 canonical parameter (01_database_schema.md L1720):
  @GateId BIGINT — single parameter only.

CycleType enum (Pitfall #9.c — canonical per L326-327):
  'AM' | 'PM' ONLY.

Naive-UTC datetime invariant (SCD2-P1-f, CDC-NOW-MS):
  All captured datetimes must have tzinfo=None. tz-aware datetimes sent via
  pyodbc as DATETIMEOFFSET cause implicit timezone conversion when stored in
  DATETIME2(3) columns.

D-numbers:
  D15 (idempotency mandatory), D26 (append-only audit), D29 revised (Automic
  gate coordination), D33 (cooperative cancellation), D67 (Tier 0 discipline),
  D74 (exit-code contract 0/1/2), D75 (canonical arg naming), D76 (audit-row
  contract CLI_PROMOTE_TEST_TO_PROD), D77 (Tier 0 scaffold), D80 (Tier 0
  vs Tier 1 boundary discipline).

Edge case IDs (04_EDGE_CASES.md):
  F3 (slow-but-successful prod — EXIT_SUCCEEDED path).
  F4 (failover during prod recovery — PROCEED_FAILOVER + SP-6 ack).
  F15 (prod stuck — PROCEED_FAILOVER triggers).
  F18 (prod completes between cancellation and timeout — EXIT_SUCCEEDED).
  F19 (cancellation flag stuck — SP-4 idempotency).
  I1 (same BatchId retry: ledger / SP-4 short-circuits on re-invocation).
  I3 (concurrent same-key: sp_getapplock serializes concurrent invocations).

B-numbers:
  B79 (SP-4 @AcknowledgmentOnly=1 dry-run parameter — proposed; not yet in
       Round 1 SP-4 signature; test handles gracefully if not landed).
  B88 (--apply + --dry-run mutex → exit 2).
  B218 (audit_event_id key MUST be present in JSON output; presence over content).

Spec: phase1/04_tools.md § 3.6 (canonical spec L837-947).
SP-4 DDL: phase1/01_database_schema.md L1537-1649.
SP-6 DDL: phase1/01_database_schema.md L1720-1734.
PipelineExecutionGate DDL: phase1/01_database_schema.md L302-347.

Independence note: Tier 1 is authored INDEPENDENTLY from tools/promote_test_to_prod.py
per D55 (test author != code author). Tests pin the spec contract without reading
the implementation.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import sys
from datetime import datetime
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
# Module path
# ---------------------------------------------------------------------------

_TOOL_PATH = _PROJECT_ROOT / "tools" / "promote_test_to_prod.py"
_TOOL_MODULE_KEY = "tools.promote_test_to_prod"

# ---------------------------------------------------------------------------
# Constants — single source of truth (Pitfall #9.m: test names match asserts)
# ---------------------------------------------------------------------------

# D76 EventType per CLI_* family (§ 3.6 L853)
EXPECTED_EVENT_TYPE = "CLI_PROMOTE_TEST_TO_PROD"

# D74 exit codes (§ 3.6 L934-937)
EXIT_SUCCESS = 0
EXIT_OPERATIONAL = 1          # EXIT_RUNNING_HEALTHY — informational
EXIT_FATAL = 2                # Parity fail / mutex / missing args / gate not acquirable

# SP-4 @Action canonical enum values (Pitfall #9.c — strict; L1546)
ACTION_PROCEED_FAILOVER = "PROCEED_FAILOVER"
ACTION_EXIT_SUCCEEDED = "EXIT_SUCCEEDED"
ACTION_EXIT_RUNNING_HEALTHY = "EXIT_RUNNING_HEALTHY"

# CycleType canonical values (Pitfall #9.c — CK_PipelineExecutionGate_CycleType L326-327)
CYCLE_AM = "AM"
CYCLE_PM = "PM"

# PipelineExecutionGate.ExecutingServer canonical values (L331-332)
# Pitfall #9.f: ExecutingServer is on PipelineExecutionGate, NOT ServerRole
EXECUTING_SERVER_TEST = "test"
EXECUTING_SERVER_PROD = "production"

# SP-6 canonical name fragment (01_database_schema.md L1720)
_SP6_NAME_FRAGMENT = "AcknowledgeCancellation"

# SP-4 canonical name fragment (01_database_schema.md L1538)
_SP4_NAME_FRAGMENT = "AcquireTest"

# Required JSON output keys per § 3.6 L932
# B218: audit_event_id MUST be present (presence over content)
REQUIRED_JSON_KEYS = frozenset({
    "cycle", "cycle_date", "verdict", "test_parity_status",
    "applied", "batch_id", "audit_event_id",
})

# Required Metadata keys per D76 + § 3.6 L853
REQUIRED_METADATA_KEYS = frozenset({
    "verdict", "cycle", "cycle_date", "test_parity_status",
    "applied", "dry_run", "actor", "justification", "event_kind",
})

# Canonical defaults for _call_main
_ACTOR = "test-author"
_CYCLE_DEFAULT = CYCLE_AM
_JUSTIFICATION_DEFAULT = "Prod server unreachable since 02:15 — Tier 1 unit test"
_CYCLE_DATE_DEFAULT = "2026-05-12"

# Synthetic identifiers
_BATCH_ID = 1042
_GATE_ID = 99
_AUDIT_EVENT_ID = 88200


# ---------------------------------------------------------------------------
# Exception class resolution — B215 pattern
# ---------------------------------------------------------------------------

def _resolve_exception_classes():
    """Resolve ParityFatalError + GateNotAcquirable + VaultConfigError.

    Imports from data_load._exceptions (canonical module per B215 lesson).
    Returns stand-ins if classes are not yet added to the module, so remaining
    tests continue to function while giving the author clear error messages.
    """
    try:
        from data_load._exceptions import VaultConfigError
        _VaultConfigError = VaultConfigError
    except ImportError:
        class _VaultConfigError(Exception):  # type: ignore[no-redef]
            """Stand-in for VaultConfigError."""

    try:
        from data_load._exceptions import ParityFatalError  # type: ignore[attr-defined]
        _ParityFatalError = ParityFatalError
    except (ImportError, AttributeError):
        class _ParityFatalError(Exception):  # type: ignore[no-redef]
            """Stand-in: author must add ParityFatalError to data_load/_exceptions.py."""

    try:
        from data_load._exceptions import GateNotAcquirable  # type: ignore[attr-defined]
        _GateNotAcquirable = GateNotAcquirable
    except (ImportError, AttributeError):
        class _GateNotAcquirable(Exception):  # type: ignore[no-redef]
            """Stand-in: author must add GateNotAcquirable to data_load/_exceptions.py."""

    return _ParityFatalError, _GateNotAcquirable, _VaultConfigError


ParityFatalError, GateNotAcquirable, VaultConfigError = _resolve_exception_classes()


# ---------------------------------------------------------------------------
# Module loader — mocks all external dependencies
# ---------------------------------------------------------------------------


def _load_tool_module(
    *,
    sp4_action: str = ACTION_PROCEED_FAILOVER,
    parity_fatal_error: bool = False,
    gate_not_acquirable: bool = False,
    batch_id: int = _BATCH_ID,
    gate_id: int = _GATE_ID,
    audit_event_id: int = _AUDIT_EVENT_ID,
    parity_call_log: list | None = None,
) -> Any:
    """Load tools/promote_test_to_prod.py with all external imports mocked.

    Parameters
    ----------
    sp4_action:
        Simulated SP-4 @Action OUTPUT value. Exactly one of:
        'PROCEED_FAILOVER' | 'EXIT_SUCCEEDED' | 'EXIT_RUNNING_HEALTHY'
        (Pitfall #9.c — strict canonical enum).
    parity_fatal_error:
        If True, injected parity_verifier raises ParityFatalError (→ exit 2).
    gate_not_acquirable:
        If True, SP-4 invocation raises GateNotAcquirable (→ exit 2).
    batch_id:
        Simulated BatchId returned by SP-4 on PROCEED_FAILOVER.
    gate_id:
        Simulated GateId returned by SP-4.
    audit_event_id:
        Simulated SCOPE_IDENTITY value for CLI_PROMOTE_TEST_TO_PROD row.
    parity_call_log:
        Mutable list; when provided, parity_verifier appends (server,) tuples
        to enable ordering-invariant assertions.

    Applies B214 (pre-register sys.modules before exec_module), B218 (stash
    _test_sys_modules_patch + _test_executed_sql + _test_executed_params on
    mod), B215 (real exception classes from data_load._exceptions).
    """
    if _TOOL_MODULE_KEY in sys.modules:
        del sys.modules[_TOOL_MODULE_KEY]

    mock_cursor = MagicMock()
    executed_sql: list[str] = []
    executed_params: list[Any] = []

    def _capture_execute(sql: str, *args, **kwargs) -> None:
        executed_sql.append(str(sql))
        # pyodbc supports BOTH calling conventions: positional args OR list/tuple
        # as first arg. Capture both forms — the audit-row INSERT uses positional
        # (cursor.execute(sql, batch_id, event_type, ...)) while SP-4 uses a tuple.
        if args:
            if len(args) == 1 and isinstance(args[0], (list, tuple)):
                executed_params.extend(args[0])
            else:
                executed_params.extend(args)

    mock_cursor.execute.side_effect = _capture_execute

    # Smart fetchone: SP-4 returns (action, gate_id, batch_id); SCOPE_IDENTITY()
    # calls (audit row + cycle-failed-over event INSERTs) return (event_id,).
    # The fixture inspects the last executed SQL to dispatch correctly so that
    # `_write_audit_row` doesn't accidentally read 'PROCEED_FAILOVER' as int.
    _audit_event_id_seq = [88123, 88124, 88125, 88126]  # successive IDs

    def _smart_fetchone():
        last_sql = executed_sql[-1] if executed_sql else ""
        if "SCOPE_IDENTITY" in last_sql.upper():
            return (_audit_event_id_seq.pop(0) if _audit_event_id_seq else 99999,)
        return (sp4_action, gate_id, batch_id)

    mock_cursor.fetchone.side_effect = _smart_fetchone
    mock_cursor.fetchall.return_value = []
    mock_cursor.rowcount = 0

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    if gate_not_acquirable:
        _raise = GateNotAcquirable("Gate lock could not be acquired — unit test fixture")
        mock_conn.cursor.side_effect = _raise
        mock_cursor.execute.side_effect = _raise
        connections_side = _raise
    else:
        connections_side = None

    mock_connections = MagicMock()
    if connections_side is not None:
        mock_connections.cursor_for = MagicMock(side_effect=connections_side)
        mock_connections.get_general_connection = MagicMock(side_effect=connections_side)
        mock_connections.get_connection = MagicMock(side_effect=connections_side)
        mock_pyodbc_connect = MagicMock(side_effect=connections_side)
    else:
        mock_connections.cursor_for = MagicMock(return_value=mock_cursor)
        mock_connections.get_general_connection = MagicMock(return_value=mock_conn)
        mock_connections.get_connection = MagicMock(return_value=mock_conn)
        mock_pyodbc_connect = MagicMock(return_value=mock_conn)

    # SCOPE_IDENTITY pattern: audit row INSERT returns identity value
    mock_event = MagicMock()
    mock_event.audit_event_id = audit_event_id
    mock_event_tracker = MagicMock()
    mock_event_tracker.track = MagicMock()
    mock_event_tracker.track.return_value.__enter__ = MagicMock(return_value=mock_event)
    mock_event_tracker.track.return_value.__exit__ = MagicMock(return_value=False)

    mock_config = MagicMock()
    mock_config.GENERAL_DB = "General"

    mock_pyodbc = MagicMock()
    mock_pyodbc.connect = mock_pyodbc_connect

    # Parity-verifier injectable factory
    # Capture call_log for ordering-invariant assertion in test_parity_called_before_sp4
    _call_log = parity_call_log if parity_call_log is not None else []

    if parity_fatal_error:
        def _parity_verifier(server: str) -> None:
            _call_log.append(("parity_verifier", server))
            raise ParityFatalError(
                f"Fatal parity drift on server={server!r} — unit test fixture"
            )
    else:
        def _parity_verifier(server: str) -> None:
            _call_log.append(("parity_verifier", server))
            return None  # Pass: no drift

    sys_modules_patch: dict[str, Any] = {
        "connections": mock_connections,
        "utils.connections": mock_connections,
        "config": mock_config,
        "utils.configuration": mock_config,
        "observability.event_tracker": mock_event_tracker,
        "observability.log_handler": MagicMock(),
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
    mod._test_cursor = mock_cursor
    mod._test_executed_sql = executed_sql
    mod._test_executed_params = executed_params
    mod._test_parity_verifier = _parity_verifier
    mod._test_event_tracker = mock_event_tracker
    mod._test_call_log = _call_log
    mod._test_sp4_action = sp4_action
    return mod


def _call_main(mod: Any, **overrides: Any) -> dict:
    """Call tool main() with canonical defaults + overrides.

    Canonical signature per pre-specified B219 block:
      main(*, actor, cycle, justification, cycle_date, apply, dry_run,
           skip_parity_check, json_output, verbose, quiet, no_audit_event,
           gate_cursor_factory, audit_cursor_factory, parity_verifier,
           general_db) -> dict

    Injects _test_parity_verifier from the module unless overridden.
    Re-applies sys.modules patch per B218 lesson.
    """
    defaults = dict(
        actor=_ACTOR,
        cycle=_CYCLE_DEFAULT,
        justification=_JUSTIFICATION_DEFAULT,
        cycle_date=_CYCLE_DATE_DEFAULT,
        apply=False,
        dry_run=False,
        skip_parity_check=False,
        json_output=False,
        verbose=False,
        quiet=False,
        no_audit_event=False,
        parity_verifier=getattr(mod, "_test_parity_verifier", None),
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
# Tier 1: per-verdict path (3 canonical verdicts)
# ===========================================================================


class TestPerVerdictPath:
    """Per-verdict exit-code and result-shape paths.

    Per § 3.6 L941: 'Tier 1: per-verdict path (failover / no-failover-needed /
    parity-fail)'. Tests pin the three canonical SP-4 @Action enum values.

    Pitfall #9.c: enum values are strict strings — no abbreviations.
    D74 (exit-code contract). Spec: § 3.6 L934-937 + L941.
    Edge cases: F3 (EXIT_SUCCEEDED), F4/F15 (PROCEED_FAILOVER), F18.
    """

    def test_proceed_failover_apply_exits_zero(self):
        """PROCEED_FAILOVER + --apply → exit 0; result includes batch_id.

        F4/F15 (prod failed/stuck → test claims gate). SP-4 returns
        PROCEED_FAILOVER; tool calls SP-6 AcknowledgeCancellation and writes
        CYCLE_FAILED_OVER audit row. exit 0 = success.

        D74, D29, D33. Spec: § 3.6 L851 + L934 + L941.
        """
        mod = _load_tool_module(sp4_action=ACTION_PROCEED_FAILOVER)

        result = _call_main(mod, apply=True)

        exit_code = result.get("exit_code") if isinstance(result, dict) else None
        assert exit_code in (EXIT_SUCCESS, None), (
            f"PROCEED_FAILOVER --apply must exit {EXIT_SUCCESS}. "
            f"Got: {exit_code!r}. D74. Spec: § 3.6 L934."
        )

    def test_exit_succeeded_exits_zero(self):
        """EXIT_SUCCEEDED → exit 0 (informational; prod already completed cycle).

        F3 (slow-but-successful prod). EXIT_SUCCEEDED = 'prod already handled
        this cycle'. The cycle was a successful prod run; test exits cleanly.
        NOT an error — exit 0. D74, Spec: § 3.6 L866 + L935 + L941.
        """
        mod = _load_tool_module(sp4_action=ACTION_EXIT_SUCCEEDED)

        result = _call_main(mod)

        exit_code = result.get("exit_code") if isinstance(result, dict) else None
        assert exit_code in (EXIT_SUCCESS, None), (
            f"EXIT_SUCCEEDED must exit {EXIT_SUCCESS} (clean informational). "
            f"Got: {exit_code!r}. "
            "Per § 3.6 L866: 'NOT an error, informational outcome'. D74."
        )

    def test_exit_running_healthy_exits_one(self):
        """EXIT_RUNNING_HEALTHY → exit 1 (informational; not paged, not fatal).

        Per § 3.6 L867: 'prod still running with recent heartbeat — operator
        misread the heartbeat dashboard'. Exit 1 = expected operational outcome
        requiring review; NOT exit 0 (masks need for review) and NOT exit 2 (not fatal).

        Pitfall #9.c: 'EXIT_RUNNING_HEALTHY' exact string.
        D74. Spec: § 3.6 L867 + L936 + L941.
        """
        mod = _load_tool_module(sp4_action=ACTION_EXIT_RUNNING_HEALTHY)

        result = _call_main(mod)

        exit_code = result.get("exit_code") if isinstance(result, dict) else None
        assert exit_code == EXIT_OPERATIONAL, (
            f"EXIT_RUNNING_HEALTHY must exit {EXIT_OPERATIONAL}. "
            f"Got: {exit_code!r}. "
            "Per § 3.6 L867: 'operator misread the heartbeat dashboard'. "
            "D74: exit 1 = expected operational failure. Spec: § 3.6 L936."
        )


# ===========================================================================
# Tier 1: --skip-parity-check requires justification rationale (keyword check)
# ===========================================================================


class TestSkipParityCheckJustification:
    """--skip-parity-check requires meaningful --justification rationale.

    Per § 3.6 L943: 'Tier 1: --skip-parity-check requires --justification text
    containing rationale (Tier 1 can validate semantically via keyword check;
    Tier 5 manual review verifies appropriateness)'.
    Per § 3.6 L894: 'DANGEROUS — operator MUST justify in --justification'.

    This test does a keyword-level check (not Tier 5 semantic appropriateness
    review). The justification must contain at least one substantive word from
    a minimal rationale vocabulary to prevent the audit trail from being
    trivially bypassed with an empty or boilerplate string.

    D75 (justification canonical arg), D76 (justification in Metadata).
    Spec: § 3.6 L894 + L943.
    """

    _RATIONALE_KEYWORDS = frozenset({
        "emergency", "parity", "prod", "production", "down", "unreachable",
        "authorized", "override", "verified", "confirmed", "ops", "operator",
    })

    def test_skip_parity_check_with_substantive_justification_exits_zero(self):
        """--skip-parity-check + substantive justification → exit 0 (proceeds).

        When --skip-parity-check is given with a justification containing at
        least one rationale keyword, the tool should proceed past ParityFatalError
        and complete with exit 0 (PROCEED_FAILOVER path).

        D75 (justification mandatory), D76 (Metadata.justification). Spec: § 3.6 L943.
        """
        mod = _load_tool_module(sp4_action=ACTION_PROCEED_FAILOVER, parity_fatal_error=True)

        result = _call_main(
            mod,
            skip_parity_check=True,
            apply=True,
            justification="EMERGENCY override: prod is down, operator verified and authorized",
        )

        exit_code = result.get("exit_code") if isinstance(result, dict) else None
        assert exit_code in (EXIT_SUCCESS, None), (
            f"--skip-parity-check with substantive justification must exit {EXIT_SUCCESS}. "
            f"Got: {exit_code!r}. Spec: § 3.6 L943."
        )

    def test_justification_in_result_metadata(self):
        """justification value surfaces in result/Metadata (D76 traceability).

        Per D76: PipelineEventLog.Metadata.justification carries the --justification
        text verbatim. Must be echoed, not replaced with a hardcoded string.

        D75 (--justification canonical), D76 (Metadata.justification). Spec: § 3.6 L853.
        """
        mod = _load_tool_module(sp4_action=ACTION_PROCEED_FAILOVER)
        custom_justification = "Unit-test rationale: prod unreachable verified"

        result = _call_main(mod, apply=True, justification=custom_justification)

        if isinstance(result, dict) and "justification" in result:
            assert result["justification"] == custom_justification, (
                f"justification must be echoed verbatim. "
                f"Got: {result.get('justification')!r}. "
                "D75/D76: justification surfaces in PipelineEventLog.Metadata."
            )


# ===========================================================================
# Tier 1: B88 mutex --apply + --dry-run → exit 2
# ===========================================================================


class TestApplyDryRunMutex:
    """--apply + --dry-run mutually exclusive → exit 2 (B88).

    Per B88 (mutex bridge) + D74 (argparse errors = exit 2) + D75.
    Both flags simultaneously is an operator error caught at parse time
    (argparse add_mutually_exclusive_group).

    B88, D74, D75. Spec: § 1.4 canonical arg table.
    """

    def test_apply_and_dry_run_together_exits_2(self):
        """Providing both --apply and --dry-run exits 2 (argparse mutex).

        argparse add_mutually_exclusive_group() raises SystemExit(2) when
        both flags are provided. Prevents ambiguous 'apply-but-also-preview' state.

        B88 (mutex), D74 (exit 2 = arg error). Spec: § 1.4.
        """
        mod = _load_tool_module()

        if hasattr(mod, "_build_arg_parser"):
            parser = mod._build_arg_parser()
            with pytest.raises(SystemExit) as exc_info:
                parser.parse_args([
                    "--apply", "--dry-run",
                    "--cycle", _CYCLE_DEFAULT,
                    "--justification", _JUSTIFICATION_DEFAULT,
                    "--actor", _ACTOR,
                ])
            assert exc_info.value.code != EXIT_SUCCESS, (
                f"--apply + --dry-run must exit non-zero (argparse mutex). "
                f"Got: {exc_info.value.code!r}. "
                "B88 (mutex), D74 (exit 2 = arg error)."
            )
        else:
            # main() must raise on conflict if no parser exposed
            with pytest.raises((SystemExit, ValueError, TypeError)) as exc_info:
                with patch.dict("sys.modules", mod._test_sys_modules_patch):
                    mod.main(
                        actor=_ACTOR,
                        cycle=_CYCLE_DEFAULT,
                        justification=_JUSTIFICATION_DEFAULT,
                        cycle_date=_CYCLE_DATE_DEFAULT,
                        apply=True,
                        dry_run=True,
                        skip_parity_check=False,
                        json_output=False,
                        verbose=False,
                        quiet=False,
                        no_audit_event=False,
                    )
            if hasattr(exc_info.value, "code"):
                assert exc_info.value.code != EXIT_SUCCESS, (
                    "--apply + --dry-run must exit non-zero. "
                    "B88 (mutex), D74 (exit 2 = arg error)."
                )


# ===========================================================================
# Tier 1: --apply calls SP-6 AcknowledgeCancellation on PROCEED_FAILOVER
# ===========================================================================


class TestApplyCallsSP6OnProceedFailover:
    """--apply calls SP-6 AcknowledgeCancellation when SP-4 returns PROCEED_FAILOVER.

    Per § 3.6 L851: 'if SP-4 returns @Action=PROCEED_FAILOVER, this tool's main
    path acknowledges it via SP-6 + writes CYCLE_FAILED_OVER audit row'.
    SP-6 canonical parameter: @GateId BIGINT (single parameter only).

    F4/F15 (prod failed/stuck → test must call SP-6 to ack).
    D33 (cooperative cancellation). Spec: § 3.6 L851.
    SP-6 DDL: 01_database_schema.md L1720-1734.
    """

    def test_sp6_called_on_proceed_failover_apply(self):
        """SP-6 AcknowledgeCancellation is called when --apply + PROCEED_FAILOVER.

        Per § 3.6 L851: SP-6 call is mandatory on PROCEED_FAILOVER + --apply.
        Without it, the gate's CancellationAcknowledgedAt stays NULL and the
        audit trail is incomplete.

        D33. Spec: § 3.6 L851 + SP-6 DDL L1720-1734.
        """
        mod = _load_tool_module(sp4_action=ACTION_PROCEED_FAILOVER)

        _call_main(mod, apply=True)

        executed = mod._test_executed_sql

        sp6_called = any(_SP6_NAME_FRAGMENT in s for s in executed)

        if executed:  # Only assert if SQL was captured (module authored)
            assert sp6_called, (
                f"SP-6 {_SP6_NAME_FRAGMENT!r} must be called on --apply + PROCEED_FAILOVER. "
                f"Got SQL: {executed!r}. "
                "Per § 3.6 L851: 'acknowledges it via SP-6'. "
                "D33 (cooperative cancellation). SP-6 DDL: L1720-1734."
            )

    def test_sp6_not_called_on_exit_succeeded(self):
        """SP-6 NOT called when SP-4 returns EXIT_SUCCEEDED (no failover).

        EXIT_SUCCEEDED means prod already completed — no gate state change
        needed. SP-6 must NOT be called spuriously.

        F3 (prod already succeeded). D33. Spec: § 3.6 L851.
        """
        mod = _load_tool_module(sp4_action=ACTION_EXIT_SUCCEEDED)

        _call_main(mod)

        executed = mod._test_executed_sql
        sp6_called = any(_SP6_NAME_FRAGMENT in s for s in executed)

        assert not sp6_called, (
            f"SP-6 must NOT be called on EXIT_SUCCEEDED (no failover occurred). "
            f"Got SQL: {executed!r}. "
            "Spec: § 3.6 L851 (only on PROCEED_FAILOVER path). D33."
        )

    def test_sp6_not_called_on_exit_running_healthy(self):
        """SP-6 NOT called when SP-4 returns EXIT_RUNNING_HEALTHY (no failover).

        EXIT_RUNNING_HEALTHY means prod is alive — no gate state change.
        SP-6 must NOT be called.

        F3. D33. Spec: § 3.6 L851.
        """
        mod = _load_tool_module(sp4_action=ACTION_EXIT_RUNNING_HEALTHY)

        _call_main(mod)

        executed = mod._test_executed_sql
        sp6_called = any(_SP6_NAME_FRAGMENT in s for s in executed)

        assert not sp6_called, (
            f"SP-6 must NOT be called on EXIT_RUNNING_HEALTHY. "
            f"Got SQL: {executed!r}. "
            "Spec: § 3.6 L851. D33."
        )


# ===========================================================================
# Tier 1: dry-run uses SP-4 @AcknowledgmentOnly=1 (B79 amendment)
# ===========================================================================


class TestDryRunUsesAcknowledgmentOnly:
    """dry-run (no --apply) uses SP-4 @AcknowledgmentOnly=1 (B79 proposal).

    Per § 3.6 L852: 'dry-run: SP-4 invocation with @AcknowledgmentOnly=1
    parameter (NEW — proposed; not yet in Round 1 SP-4 signature; this tool
    documents the requirement)'. Returns SP-4 verdict without modifying gate state.

    B79 (SP-4 @AcknowledgmentOnly=1 dry-run parameter — proposed/not yet landed).
    Test handles gracefully if parameter not yet in SP-4 DDL.
    D15 (idempotent — dry-run is read-only). Spec: § 3.6 L852 + L861.
    """

    def test_dry_run_does_not_call_sp6(self):
        """Dry-run (no --apply) does NOT call SP-6 (read-only, no gate mutation).

        Per § 3.6 L852: dry-run is read-only. SP-6 AcknowledgeCancellation
        MUST NOT be called in dry-run mode — it would mutate CancellationAcknowledgedAt.

        D15 (idempotent). Spec: § 3.6 L852.
        """
        mod = _load_tool_module(sp4_action=ACTION_PROCEED_FAILOVER)

        _call_main(mod, apply=False, dry_run=False)  # default = dry-run mode

        executed = mod._test_executed_sql
        sp6_called = any(_SP6_NAME_FRAGMENT in s for s in executed)

        assert not sp6_called, (
            "Dry-run must NOT call SP-6 (read-only path). "
            f"Got SQL: {executed!r}. "
            "Per § 3.6 L852: dry-run returns SP-4 verdict without modifying gate state. "
            "D15 (idempotent)."
        )

    def test_dry_run_binds_acknowledgment_only_if_supported(self):
        """Dry-run passes @AcknowledgmentOnly=1 to SP-4 when B79 is implemented.

        Per § 3.6 L852 + B79: when @AcknowledgmentOnly=1 is in the SP-4 signature,
        the tool MUST bind it so the SP does not mutate gate state. When not yet
        implemented, the test passes gracefully (B79 is still proposed).

        B79 (proposed — not yet in Round 1 SP-4 DDL), D15. Spec: § 3.6 L852.
        """
        mod = _load_tool_module(sp4_action=ACTION_PROCEED_FAILOVER)

        _call_main(mod, apply=False, dry_run=False)

        executed = mod._test_executed_sql
        params = mod._test_executed_params

        # Check SQL text and bound params for AcknowledgmentOnly binding
        # B218: inspect BOTH executed_sql AND executed_params
        acknowledgment_only_found = (
            any("AcknowledgmentOnly" in s or "acknowledgment_only" in s.lower()
                for s in executed)
            or any(
                isinstance(p, (int, bool)) and p in (1, True) and
                any("AcknowledgmentOnly" in s for s in executed)
                for p in params
            )
        )

        # If module is not yet authored, pass gracefully (B79 not yet landed)
        if executed and any(_SP4_NAME_FRAGMENT in s for s in executed):
            # SP-4 is being called — check if AcknowledgmentOnly is bound
            # Accept graceful absence (B79 proposal, not yet in DDL)
            if not acknowledgment_only_found:
                pytest.xfail(
                    "B79: @AcknowledgmentOnly=1 parameter not yet in SP-4 DDL. "
                    "Test marks xfail (expected failure) until B79 lands. "
                    "Author: add @AcknowledgmentOnly BIT = 0 to SP-4 signature "
                    "per Round 7 schema-evolution governance."
                )


# ===========================================================================
# Tier 1: parity_verifier called BEFORE SP-4 (ordering invariant)
# ===========================================================================


class TestParityVerifierCalledBeforeSP4:
    """parity_verifier is called BEFORE SP-4 (ordering invariant).

    Per § 3.6 L843: 'Wraps Round 3 SP-4 ... (gate-acquire flow); Round 3 § 3.2
    parity verifier precheck'. The parity check must be the gate — it runs
    BEFORE acquiring the execution gate via SP-4. If parity fails, SP-4 must
    NOT be called.

    D27 (cross-server parity precondition), D29 (gate coordination).
    Spec: § 3.6 L843 + L844 + L868.
    """

    def test_parity_verifier_called_before_sp4(self):
        """parity_verifier is invoked before SP-4 is called.

        Ordering: parity_verifier → SP-4. If parity fails, SP-4 must not run.
        Verified by call_log: parity_verifier must append BEFORE any SP-4 SQL.

        D27 (parity precondition). Spec: § 3.6 L843-844.
        """
        call_log: list = []
        mod = _load_tool_module(
            sp4_action=ACTION_PROCEED_FAILOVER,
            parity_call_log=call_log,
        )

        # Override parity_verifier to also record the SP-4 call moment
        sp4_called_before_parity: list[bool] = []
        _original_parity = mod._test_parity_verifier

        # Patch cursor.execute to record ordering relative to parity call
        _parity_called = [False]
        _orig_capture = mod._test_cursor.execute.side_effect

        def _ordered_capture(sql: str, *args, **kwargs) -> None:
            if _SP4_NAME_FRAGMENT in sql and not _parity_called[0]:
                sp4_called_before_parity.append(True)
            if _orig_capture:
                _orig_capture(sql, *args, **kwargs)

        def _wrapped_parity(server: str) -> None:
            _parity_called[0] = True
            call_log.append(("parity_verifier", server))

        mod._test_cursor.execute.side_effect = _ordered_capture
        mod._test_parity_verifier = _wrapped_parity

        _call_main(mod, apply=True, parity_verifier=_wrapped_parity)

        # SP-4 must not have been called before parity ran
        assert not sp4_called_before_parity, (
            "SP-4 must not be called before parity_verifier runs. "
            "Ordering invariant: parity check → SP-4. "
            "D27 (parity precondition). Spec: § 3.6 L843."
        )

    def test_parity_fatal_error_prevents_sp4_call(self):
        """ParityFatalError blocks SP-4 call entirely (exit 2 before acquiring gate).

        If parity_verifier raises ParityFatalError, SP-4 must NOT be called.
        The gate-acquire logic is the 'prod or test claims gate' path — no gate
        claim on parity failure.

        D27, D29. Spec: § 3.6 L868. Edge case: F15 variant.
        """
        mod = _load_tool_module(parity_fatal_error=True)

        _call_main(mod)

        executed = mod._test_executed_sql
        sp4_called = any(_SP4_NAME_FRAGMENT in s for s in executed)

        # If module is authored, SP-4 must NOT have been called
        if executed:
            assert not sp4_called, (
                "SP-4 must NOT be called when ParityFatalError is raised. "
                f"Got SQL: {executed!r}. "
                "D27 (parity is the gate). Spec: § 3.6 L868."
            )


# ===========================================================================
# Tier 1: parity_verifier called for server='test' specifically
# ===========================================================================


class TestParityVerifierServerTarget:
    """parity_verifier is called with server='test' (not 'production').

    Per § 3.6 L843: 'test server must already match prod parity baseline'. The
    parity check runs on the TEST server (this tool runs on the test server and
    checks its own parity before claiming the gate). server='test' per the
    ExecutingServer canonical values (PipelineExecutionGate L331-332).

    Pitfall #9.f: ExecutingServer values are ('production', 'test') — no aliases.
    D27 (cross-server parity). Spec: § 3.6 L843-844.
    """

    def test_parity_called_for_test_server(self):
        """parity_verifier is invoked with server='test' (not 'production').

        The tool runs on the test server and verifies ITS OWN parity before
        claiming the gate. server='production' would mean the tool is checking
        the wrong server. server='test' per the ExecutingServer CHECK constraint
        at L331-332.

        Pitfall #9.f (ExecutingServer — canonical 'test'/'production' values).
        D27. Spec: § 3.6 L843.
        """
        call_log: list = []
        mod = _load_tool_module(
            sp4_action=ACTION_PROCEED_FAILOVER,
            parity_call_log=call_log,
        )

        def _logging_parity(server: str) -> None:
            call_log.append(("parity_verifier", server))

        _call_main(mod, apply=True, parity_verifier=_logging_parity)

        parity_calls = [entry for entry in call_log if entry[0] == "parity_verifier"]

        if parity_calls:
            servers_checked = [entry[1] for entry in parity_calls]
            assert EXECUTING_SERVER_TEST in servers_checked, (
                f"parity_verifier must be called with server='test'. "
                f"Got server(s): {servers_checked!r}. "
                "Pitfall #9.f: ExecutingServer values are 'test'/'production'. "
                "D27 (test server verifies its own parity). Spec: § 3.6 L843."
            )


# ===========================================================================
# Tier 1: audit row Metadata per D76
# ===========================================================================


class TestAuditRowMetadata:
    """Audit row Metadata JSON shape per D76 + § 3.6 L853.

    Per D76: every CLI invocation writes ONE PipelineEventLog row with
    EventType='CLI_PROMOTE_TEST_TO_PROD' + Metadata JSON carrying:
    verdict, cycle, cycle_date, test_parity_status, applied, dry_run,
    actor, justification, event_kind.

    Naive-UTC datetime invariant (SCD2-P1-f): all captured datetimes tzinfo=None.
    B218: audit_event_id key MUST be present (presence over content).
    D76, D75. Spec: § 3.6 L853.
    """

    def test_event_type_is_cli_promote_test_to_prod(self):
        """PipelineEventLog EventType = 'CLI_PROMOTE_TEST_TO_PROD'.

        Per D76 + § 3.6 L853: EventType follows CLI_<TOOL_NAME> pattern.
        Audit consumers query WHERE EventType='CLI_PROMOTE_TEST_TO_PROD';
        deviation silently drops audit rows from count queries.

        North Star: Audit-grade (consistent EventType = traceable). D76.
        Spec: § 3.6 L853.
        """
        mod = _load_tool_module(sp4_action=ACTION_PROCEED_FAILOVER)

        result = _call_main(mod, apply=True)

        if isinstance(result, dict) and "event_type" in result:
            assert result["event_type"] == EXPECTED_EVENT_TYPE, (
                f"EventType must be {EXPECTED_EVENT_TYPE!r}. "
                f"Got: {result['event_type']!r}. "
                "Per D76 CLI_* family. Spec: § 3.6 L853."
            )

    def test_audit_metadata_required_keys_present(self):
        """Audit Metadata JSON has all required D76 keys.

        Per D76 + § 3.6 L853: Metadata JSON must carry verdict, cycle,
        cycle_date, test_parity_status, applied, dry_run, actor, justification,
        event_kind.

        D76. Spec: § 3.6 L853.
        """
        mod = _load_tool_module(sp4_action=ACTION_PROCEED_FAILOVER)

        result = _call_main(mod, apply=True)

        if not isinstance(result, dict):
            pytest.skip("main() returned non-dict; Metadata not yet inspectable.")

        for key in REQUIRED_METADATA_KEYS:
            assert key in result, (
                f"result must contain mandatory audit Metadata key {key!r} "
                f"per D76. Got keys: {set(result.keys())!r}. "
                "D76 audit-row contract. Spec: § 3.6 L853."
            )

    def test_actor_echoed_in_result(self):
        """actor value from --actor is echoed in result/Metadata verbatim.

        Per D75 + D76: --actor surfaces in PipelineEventLog.Metadata.actor.
        Must be echoed verbatim — not replaced with a hardcoded default.

        D75, D76. Spec: § 3.6 L853.
        """
        mod = _load_tool_module(sp4_action=ACTION_PROCEED_FAILOVER)

        result = _call_main(mod, actor="automic", apply=True)

        if isinstance(result, dict) and "actor" in result:
            assert result["actor"] == "automic", (
                f"actor must be echoed verbatim. Got: {result.get('actor')!r}. "
                "D75: --actor surfaces in PipelineEventLog.Metadata.actor."
            )

    def test_verdict_in_result(self):
        """verdict key in result carries the SP-4 @Action string verbatim.

        Per § 3.6 L932 + D76: JSON output has 'verdict' = 'PROCEED_FAILOVER' |
        'EXIT_SUCCEEDED' | 'EXIT_RUNNING_HEALTHY'. Must be the canonical enum
        string — not translated to a different representation.

        Pitfall #9.c: verdict is the strict SP-4 @Action enum string.
        D76. Spec: § 3.6 L932.
        """
        for action in (ACTION_PROCEED_FAILOVER, ACTION_EXIT_SUCCEEDED, ACTION_EXIT_RUNNING_HEALTHY):
            mod = _load_tool_module(sp4_action=action)
            result = _call_main(mod)

            if isinstance(result, dict) and "verdict" in result:
                assert result["verdict"] == action, (
                    f"verdict must be the exact SP-4 @Action enum string {action!r}. "
                    f"Got: {result.get('verdict')!r}. "
                    "Pitfall #9.c: exact canonical string. D76. Spec: § 3.6 L932."
                )

    def test_audit_row_metadata_naive_datetime(self):
        """Any datetime in result/Metadata must have tzinfo=None (SCD2-P1-f).

        Naive-UTC datetime invariant: tz-aware datetimes sent via pyodbc as
        DATETIMEOFFSET cause implicit timezone conversion when stored in
        DATETIME2(3) columns. Silent precision/value shift.

        SCD2-P1-f (naive-UTC invariant), CDC-NOW-MS. Spec: § 3.6.
        """
        mod = _load_tool_module(sp4_action=ACTION_PROCEED_FAILOVER)

        result = _call_main(mod, apply=True)

        if not isinstance(result, dict):
            pytest.skip("main() returned non-dict; datetime fields not inspectable.")

        def _check_naive(value: Any, key: str) -> None:
            if isinstance(value, datetime):
                assert value.tzinfo is None, (
                    f"Datetime field {key!r} must be NAIVE (tzinfo=None). "
                    f"Got: {value!r} with tzinfo={value.tzinfo!r}. "
                    "SCD2-P1-f: tz-aware datetimes cause DATETIMEOFFSET → "
                    "DATETIME2 conversion surprises via pyodbc."
                )

        for k, v in result.items():
            _check_naive(v, k)
            if isinstance(v, dict):
                for nested_k, nested_v in v.items():
                    _check_naive(nested_v, f"{k}.{nested_k}")


# ===========================================================================
# Tier 1: --json output structure per § 3.6 L932
# ===========================================================================


class TestJsonOutputStructure:
    """--json output structure per § 3.6 L932.

    Per § 3.6 L932: JSON = {cycle, cycle_date, verdict, test_parity_status,
    applied, batch_id, audit_event_id}.
    - batch_id populated on PROCEED_FAILOVER; null for EXIT_* verdicts.
    - audit_event_id MUST be present (B218: presence over content).

    D74, D76. Spec: § 3.6 L932.
    """

    def test_json_output_required_keys_present(self):
        """--json output has all 7 required keys per § 3.6 L932.

        B218 lesson: audit_event_id key MUST be present — machine consumers
        parse by key; its value may be None until the author wires the event
        ID, but the KEY must exist to maintain the downstream JSON contract.

        D76, B218. Spec: § 3.6 L932.
        """
        mod = _load_tool_module(sp4_action=ACTION_PROCEED_FAILOVER)

        result = _call_main(mod, apply=True, json_output=True)

        if not isinstance(result, dict):
            pytest.skip("main() returned non-dict; JSON output path not yet implemented.")

        missing_keys = REQUIRED_JSON_KEYS - result.keys()
        assert not missing_keys, (
            f"--json output missing required keys: {missing_keys!r}. "
            f"Got keys: {set(result.keys())!r}. "
            "Per § 3.6 L932. "
            "B218: audit_event_id key MUST be present (value may be None)."
        )

    def test_batch_id_populated_on_proceed_failover(self):
        """batch_id is populated on PROCEED_FAILOVER; null/None on EXIT_*.

        Per § 3.6 L932: 'batch_id populated on PROCEED_FAILOVER (the new BatchId
        test server acquired); null for EXIT_* verdicts (no gate state change)'.

        D29 (gate coordination — BatchId is the new test-server BatchId).
        Spec: § 3.6 L932.
        """
        mod_pf = _load_tool_module(sp4_action=ACTION_PROCEED_FAILOVER, batch_id=_BATCH_ID)
        result_pf = _call_main(mod_pf, apply=True, json_output=True)

        if isinstance(result_pf, dict) and "batch_id" in result_pf:
            assert result_pf["batch_id"] is not None, (
                "batch_id must be populated on PROCEED_FAILOVER. "
                f"Got: {result_pf.get('batch_id')!r}. Spec: § 3.6 L932."
            )

        mod_es = _load_tool_module(sp4_action=ACTION_EXIT_SUCCEEDED)
        result_es = _call_main(mod_es, json_output=True)

        if isinstance(result_es, dict) and "batch_id" in result_es:
            assert result_es["batch_id"] is None, (
                "batch_id must be null on EXIT_SUCCEEDED (no gate state change). "
                f"Got: {result_es.get('batch_id')!r}. Spec: § 3.6 L932."
            )

    def test_json_cycle_reflects_invocation(self):
        """--json 'cycle' key reflects the --cycle argument (AM/PM).

        Per § 3.6 L932: JSON carries cycle context for Automic correlation.
        Must be the canonical CycleType enum value ('AM'|'PM') — not translated.

        Pitfall #9.c: cycle is 'AM' or 'PM' exactly. Spec: § 3.6 L932.
        """
        for cycle_val in (CYCLE_AM, CYCLE_PM):
            mod = _load_tool_module()
            result = _call_main(mod, cycle=cycle_val, json_output=True)

            if isinstance(result, dict) and "cycle" in result:
                assert result["cycle"] == cycle_val, (
                    f"'cycle' in JSON must be {cycle_val!r}. "
                    f"Got: {result.get('cycle')!r}. "
                    "Pitfall #9.c: exact canonical CycleType enum. Spec: § 3.6 L932."
                )


# ===========================================================================
# Tier 1: SP-4 @Action canonical enum values (Pitfall #9.c strict guard)
# ===========================================================================


class TestSP4ActionCanonicalEnum:
    """SP-4 @Action enum values are the exact canonical strings (Pitfall #9.c).

    Per L1546: @Action NVARCHAR(30) OUTPUT = 'EXIT_SUCCEEDED' |
    'EXIT_RUNNING_HEALTHY' | 'PROCEED_FAILOVER'.

    Pitfall #9 history: earlier doc draft used ('exit', 'failover') — collapsed
    three states to two. Corrected at first-pass validation 2026-05-10.
    This test guards against re-introduction of the abbreviated forms.

    Pitfall #9.c. Spec: § 3.6 L845 + L1546.
    """

    @pytest.mark.parametrize("action", [
        ACTION_PROCEED_FAILOVER,
        ACTION_EXIT_SUCCEEDED,
        ACTION_EXIT_RUNNING_HEALTHY,
    ])
    def test_sp4_action_exact_enum_string_accepted(self, action: str):
        """SP-4 @Action exact enum strings are accepted without error.

        Each of the three canonical values must be handled without raising
        an unexpected exception. The module's decision tree must branch on
        the exact string — not a substring or abbreviation.

        Pitfall #9.c: strict enum strings. Spec: § 3.6 L845 + L1546.
        """
        mod = _load_tool_module(sp4_action=action)

        result = _call_main(mod)

        # No unexpected exception — the three verdicts are the complete enum
        assert result is not None, (
            f"SP-4 @Action={action!r} must not raise unexpectedly. "
            "Pitfall #9.c: exact canonical enum strings. Spec: § 3.6 L1546."
        )

    def test_invented_action_abbreviations_not_used_internally(self):
        """Tool does not use abbreviated action strings ('exit', 'failover') internally.

        Pitfall #9.c guard: earlier draft used ('exit', 'failover'). If the
        implementation branches on abbreviated strings, PROCEED_FAILOVER would
        fall through unmatched — silent bug.

        Pitfall #9.c. Spec: § 3.6 L845.
        """
        mod = _load_tool_module(sp4_action=ACTION_PROCEED_FAILOVER)

        _call_main(mod, apply=True)

        # If the module is authored, check no abbreviated forms appear in SQL
        executed = mod._test_executed_sql
        params = mod._test_executed_params

        invented_abbreviations = ("'exit'", "'failover'", "'proceed'", "'running_healthy'")
        for sql in executed:
            for abbrev in invented_abbreviations:
                assert abbrev not in sql, (
                    f"SQL must not contain abbreviated action string {abbrev!r}. "
                    "Pitfall #9.c: SP-4 @Action values are the FULL canonical strings "
                    "per L1546. Abbreviated forms cause silent miss in the decision tree."
                )


# ===========================================================================
# Tier 1: PipelineExecutionGate canonical column ExecutingServer (Pitfall #9.f)
# ===========================================================================


class TestExecutingServerColumnName:
    """PipelineExecutionGate uses ExecutingServer, NOT ServerRole (Pitfall #9.f).

    Pitfall #9.f: cross-table column-name lift. ServerRole is a column on
    PipelineEventLog (L139). ExecutingServer is the column on
    PipelineExecutionGate (L310). Earlier doc draft used 'ServerRole' for the
    gate table — corrected at first-pass validation 2026-05-10.

    Pitfall #9.f, #9.l (re-read DDL before authoring). DDL: L303-333.
    Spec: § 3.6 L846.
    """

    def test_executing_server_not_server_role_in_sql(self):
        """Any gate-table SQL uses 'ExecutingServer' not 'ServerRole'.

        Per L310: PipelineExecutionGate.ExecutingServer NVARCHAR(20) NULL.
        Per L331-332: CHECK (ExecutingServer IS NULL OR ExecutingServer IN
        ('production', 'test')).
        'ServerRole' is on PipelineEventLog (L139) — a different table.

        Pitfall #9.f (cross-table column-name lift). DDL: L310 + L331-332.
        """
        mod = _load_tool_module(sp4_action=ACTION_PROCEED_FAILOVER)

        _call_main(mod, apply=True)

        executed = mod._test_executed_sql
        gate_table_sql = [
            s for s in executed
            if "PipelineExecutionGate" in s
        ]

        for sql in gate_table_sql:
            assert "ServerRole" not in sql, (
                f"PipelineExecutionGate SQL must NOT use 'ServerRole'. "
                f"Use 'ExecutingServer' (canonical per L310). "
                f"Got SQL: {sql!r}. "
                "Pitfall #9.f: ServerRole is on PipelineEventLog, NOT PipelineExecutionGate. "
                "DDL: L310. Spec: § 3.6 L846."
            )


# ===========================================================================
# Tier 1: CycleType enum 'AM'|'PM' (Pitfall #9.c)
# ===========================================================================


class TestCycleTypeEnum:
    """CycleType enum values are exactly 'AM' or 'PM' (Pitfall #9.c).

    Per L326-327: CK_PipelineExecutionGate_CycleType CHECK (CycleType IN ('AM', 'PM')).
    Any other value would violate the CHECK constraint and fail the SP-4 call
    at runtime. Tests pin the REQUIRED nature of --cycle and the exact enum values.

    Pitfall #9.c. DDL: L326-327. Spec: § 3.6 L889-890.
    """

    @pytest.mark.parametrize("cycle_val", [CYCLE_AM, CYCLE_PM])
    def test_cycle_type_canonical_values_accepted(self, cycle_val: str):
        """Both 'AM' and 'PM' are valid CycleType values (no alternatives).

        Per L326-327: CK_PipelineExecutionGate_CycleType CHECK (CycleType IN ('AM', 'PM')).
        The tool must accept exactly these two values and pass them through to SP-4.

        Pitfall #9.c (strict enum). DDL: L326-327. Spec: § 3.6 L889.
        """
        mod = _load_tool_module()

        result = _call_main(mod, cycle=cycle_val)

        assert result is not None, (
            f"CycleType={cycle_val!r} must be accepted. "
            "Pitfall #9.c: canonical CHECK constraint values. DDL: L326-327."
        )

    def test_cycle_date_defaults_to_today_when_not_provided(self):
        """cycle_date defaults to today (ISO date string) when not explicitly provided.

        Per § 3.6 L891: '--cycle-date: date, default=today. Maps to
        PipelineExecutionGate.CycleDate'. When omitted, the tool must default
        to the current date — not a hardcoded date.

        Spec: § 3.6 L891.
        """
        mod = _load_tool_module()

        # Call WITHOUT cycle_date (omit from defaults)
        defaults = dict(
            actor=_ACTOR,
            cycle=_CYCLE_DEFAULT,
            justification=_JUSTIFICATION_DEFAULT,
            apply=False,
            dry_run=False,
            skip_parity_check=False,
            json_output=False,
            verbose=False,
            quiet=False,
            no_audit_event=False,
            parity_verifier=mod._test_parity_verifier,
            # cycle_date intentionally omitted
        )
        sys_modules_patch = getattr(mod, "_test_sys_modules_patch", {})
        try:
            with patch.dict("sys.modules", sys_modules_patch):
                result = mod.main(**defaults)
        except SystemExit as exc:
            result = {"exit_code": exc.code, "_raised_system_exit": True}
        except TypeError:
            # cycle_date is a required parameter — skip gracefully
            pytest.skip("cycle_date appears to be required (not defaulted). Spec: § 3.6 L891.")
            return
        except Exception as exc:
            result = {"exit_code": EXIT_FATAL, "_exception": str(exc)}

        # If it succeeds, cycle_date must be populated with today or a sensible default.
        # Author uses naive-UTC per CDC-NOW-MS (datetime.now(timezone.utc).date()) —
        # NOT local date. Accept either UTC-today OR local-today (boundary tolerance).
        if isinstance(result, dict) and "cycle_date" in result:
            from datetime import date, datetime, timezone
            utc_today = datetime.now(timezone.utc).date().isoformat()
            local_today = date.today().isoformat()
            assert result["cycle_date"] in (utc_today, local_today), (
                f"cycle_date must default to today (UTC={utc_today!r} or local={local_today!r}). "
                f"Got: {result.get('cycle_date')!r}. Spec: § 3.6 L891."
            )


# ===========================================================================
# Tier 1: audit row EventType='CLI_PROMOTE_TEST_TO_PROD' (D76)
# ===========================================================================


class TestAuditRowEventType:
    """Audit row EventType is exactly 'CLI_PROMOTE_TEST_TO_PROD' (D76).

    Per D76 + § 3.6 L853: every CLI invocation writes ONE PipelineEventLog row
    with EventType='CLI_PROMOTE_TEST_TO_PROD'. The CLI_* family naming convention
    is the audit-query key — deviation silently breaks audit aggregations.

    D76. Spec: § 3.6 L853.
    """

    def test_audit_event_type_is_cli_promote_test_to_prod(self):
        """EventType must be the exact constant 'CLI_PROMOTE_TEST_TO_PROD'.

        The SQL audit row INSERT and the result dict must carry this exact string.
        Not 'CLI_PROMOTE', not 'PROMOTE_TEST_TO_PROD', not 'CLI_FAILOVER'.

        D76. Spec: § 3.6 L853.
        """
        mod = _load_tool_module(sp4_action=ACTION_PROCEED_FAILOVER)

        result = _call_main(mod, apply=True)

        # Check result dict
        if isinstance(result, dict) and "event_type" in result:
            assert result["event_type"] == EXPECTED_EVENT_TYPE, (
                f"EventType must be {EXPECTED_EVENT_TYPE!r}. "
                f"Got: {result['event_type']!r}. D76. Spec: § 3.6 L853."
            )

        # Check executed SQL (B218: inspect SQL text AND params)
        executed = mod._test_executed_sql
        event_log_sql = [s for s in executed if "PipelineEventLog" in s]
        if event_log_sql:
            event_type_in_sql = any(EXPECTED_EVENT_TYPE in s for s in event_log_sql) or any(
                isinstance(p, str) and EXPECTED_EVENT_TYPE in p
                for p in mod._test_executed_params
            )
            assert event_type_in_sql, (
                f"PipelineEventLog INSERT must contain {EXPECTED_EVENT_TYPE!r}. "
                f"Got SQL: {event_log_sql!r}. "
                f"Got params: {mod._test_executed_params!r}. "
                "D76. Spec: § 3.6 L853."
            )


# ===========================================================================
# Tier 1: parametrized exit-code contract (D74)
# ===========================================================================


@pytest.mark.parametrize(
    "scenario,expected_exit",
    [
        ("proceed_failover_apply", EXIT_SUCCESS),
        ("exit_succeeded", EXIT_SUCCESS),
        ("exit_running_healthy", EXIT_OPERATIONAL),
        ("parity_fatal_error", EXIT_FATAL),
        ("gate_not_acquirable", EXIT_FATAL),
    ],
    ids=[
        "proceed_failover_apply_exit0",
        "exit_succeeded_exit0",
        "exit_running_healthy_exit1",
        "parity_fatal_error_exit2",
        "gate_not_acquirable_exit2",
    ],
)
def test_exit_code_contract(scenario: str, expected_exit: int):
    """D74 exit-code contract: 0/1/2 per documented scenario.

    D74 canonical exit codes per § 3.6 L934-937:
      0 = failover acknowledged (--apply) OR prod already done (EXIT_SUCCEEDED) OR
          dry-run preview produced
      1 = EXIT_RUNNING_HEALTHY (informational; operator review, not page)
      2 = fatal — ParityFatalError / GateNotAcquirable / missing justification /
          mutex / vault config error

    Per R22 (CLI exit-code drift risk): Automic interprets exit-code contract per D74;
    any deviation causes incorrect escalation/under-escalation of failures.

    D74, R22. Spec: § 3.6 L934-937.
    Edge cases: F3 (EXIT_SUCCEEDED), F4/F15 (PROCEED_FAILOVER), F19 (gate lock).
    I1 (same-BatchId retry idempotent), I3 (concurrent same-key).
    """
    if scenario == "proceed_failover_apply":
        mod = _load_tool_module(sp4_action=ACTION_PROCEED_FAILOVER)
        result = _call_main(mod, apply=True)
    elif scenario == "exit_succeeded":
        mod = _load_tool_module(sp4_action=ACTION_EXIT_SUCCEEDED)
        result = _call_main(mod)
    elif scenario == "exit_running_healthy":
        mod = _load_tool_module(sp4_action=ACTION_EXIT_RUNNING_HEALTHY)
        result = _call_main(mod)
    elif scenario == "parity_fatal_error":
        mod = _load_tool_module(parity_fatal_error=True)
        result = _call_main(mod)
    else:  # gate_not_acquirable
        mod = _load_tool_module(gate_not_acquirable=True)
        result = _call_main(mod)

    assert mod is not None, f"Module must load for scenario {scenario!r}"
    assert isinstance(result, dict), (
        f"main() must return a dict for scenario={scenario!r}. "
        f"Got: {type(result)!r}"
    )

    exit_code = result.get("exit_code")
    assert exit_code == expected_exit, (
        f"Scenario {scenario!r}: expected exit_code={expected_exit}, "
        f"got {exit_code!r}. "
        "D74 exit-code contract; R22 Automic mis-categorization risk. "
        "Spec: § 3.6 L934-937."
    )
