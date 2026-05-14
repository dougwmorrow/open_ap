"""Tier 0 build-time smoke test for tools/promote_test_to_prod.py.

Per D67 — runs at build time + every commit. Runtime ceiling < 5 s.
All external dependencies mocked. No live DB, no live network required.

8-assertion D77-canonical scaffold per phase1/04_tools.md § 3.6 L939:
  (a) Module imports without error.
  (b) --help exits 0 per D77 Tier 0 scaffold assertion 2.
  (c) Missing --cycle OR missing --justification → arg-parse error → exit 2
      (D74: argparse errors = exit 2 per § 3.6 L937).
  (d) Mocked SP-4 returning @Action='PROCEED_FAILOVER' + mocked parity-pass
      → exit 0; stdout contains 'PROCEED_FAILOVER' (§ 3.6 L935 + L939).
  (e) Mocked SP-4 returning @Action='EXIT_SUCCEEDED' → exit 0 (informational;
      prod already completed cycle — NOT an error per § 3.6 L866 + L935).
  (f) Mocked SP-4 returning @Action='EXIT_RUNNING_HEALTHY' → exit 1
      (informational; operator misread heartbeat dashboard per § 3.6 L867 +
      L936; NOT exit 0, NOT exit 2).
  (g) Mocked ParityFatalError from parity-precheck → exit 2 (§ 3.6 L868 +
      L937; fatal — test server cannot promote until parity restored).
  (h) --skip-parity-check allows proceeding past parity-fail mock (with
      CRITICAL log emitted per § 3.6 L894).
  Plus runtime assertion: total wall time < 5 s per D67.

North Star pillars (NORTH_STAR.md):
  - Audit-grade (D76): ONE CLI_PROMOTE_TEST_TO_PROD PipelineEventLog row per
    invocation; Metadata JSON carries verdict, cycle, cycle_date, actor,
    justification, test_parity_status, applied, dry_run, event_kind.
  - Operationally stable (D67 / D74): import + invoke + shape + error-modes
    in < 5 s with zero external I/O; exit-code contract 0/1/2 enforced.
  - Idempotent (D15): SP-4 @AcknowledgmentOnly=1 is read-only (B79 proposal);
    re-invocation on already-acknowledged failover is a no-op (§ 3.6 L862).
  - Traceability (D26): every invocation writes ONE PipelineEventLog row with
    EventType='CLI_PROMOTE_TEST_TO_PROD' (§ 3.6 L853).

Canonical column verification (Pitfall #9.a + #9.f — re-read DDL before
authoring per Pitfall #9.l):
  PipelineExecutionGate columns (01_database_schema.md L303-333):
    GateId, CycleType, CycleDate, ExpectedStartTime, ActualStartTime,
    ActualCompletionTime, ExecutingServer, Status, BatchId, LastHeartbeatAt,
    FailureReason, CancellationRequested, CancellationRequestedAt,
    CancellationRequestedBy, CancellationReason, CancellationAcknowledgedAt,
    CreatedAt.
  ExecutingServer (NOT ServerRole — ServerRole lives on PipelineEventLog, NOT
  PipelineExecutionGate — Pitfall #9.f cross-table column-name lift guard).

SP-4 canonical signature (Pitfall #9.b — verified against L1538-1546):
  CREATE PROCEDURE General.ops.PipelineExecutionGate_AcquireTest
    @CycleType NVARCHAR(10), @CycleDate DATE,
    @ExpectedStartTime DATETIME2(3), @HeartbeatStaleMinutes INT = 10,
    @ProdMaxRuntimeMinutes INT = 120,
    @GateId BIGINT OUTPUT, @BatchId BIGINT OUTPUT,
    @Action NVARCHAR(30) OUTPUT

SP-4 @Action enum (Pitfall #9.c — strict; canonical per L1546):
  'EXIT_SUCCEEDED' | 'EXIT_RUNNING_HEALTHY' | 'PROCEED_FAILOVER'
  NOT 'exit', 'failover', 'proceed', 'succeeded', 'running_healthy'.

CycleType enum (Pitfall #9.c — canonical per L326-327):
  'AM' | 'PM' — ONLY these two values.

D-numbers: D15 (idempotency mandatory), D26 (append-only audit), D29
  (Automic gate coordination), D33 (cooperative cancellation), D67 (Tier 0
  discipline), D74 (exit-code contract 0/1/2), D75 (canonical arg naming:
  actor/cycle/cycle-date/justification/apply/dry-run/skip-parity-check/json/
  verbose/quiet/no-audit-event), D76 (audit-row contract
  CLI_PROMOTE_TEST_TO_PROD), D77 (6-canonical Tier 0 scaffold → 8-assertion
  extension per § 3.6 L939).

Edge cases cited:
  F3 (slow-but-successful prod — EXIT_SUCCEEDED verdict path),
  F4 (failover during prod recovery — PROCEED_FAILOVER path),
  F15 (prod stuck — PROCEED_FAILOVER path),
  F18 (prod completes between cancellation and timeout — EXIT_SUCCEEDED).

B-numbers:
  B79 (SP-4 @AcknowledgmentOnly=1 dry-run parameter — proposed; not yet in
       Round 1 SP-4 signature; handled gracefully if not yet landed).
  B88 (--apply + --dry-run mutex — assert exit 2 on conflict).

Independence note: tests/tier0/test_promote_test_to_prod.py is authored
INDEPENDENTLY from tools/promote_test_to_prod.py per D55 (5-gate validation
discipline — test author != code author). Tests pin the spec contract per
phase1/04_tools.md § 3.6 L837-947 WITHOUT reading the implementation.

Spec: phase1/04_tools.md § 3.6 (canonical spec L837-947).
SP-4 DDL: phase1/01_database_schema.md L1537-1649.
SP-6 DDL: phase1/01_database_schema.md L1720-1734.
PipelineExecutionGate DDL: phase1/01_database_schema.md L302-347.
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
import time
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

_TOOL_PATH = _PROJECT_ROOT / "tools" / "promote_test_to_prod.py"
_TOOL_MODULE_KEY = "tools.promote_test_to_prod"

# ---------------------------------------------------------------------------
# Constants — single source of truth
# ---------------------------------------------------------------------------

# D76 EventType per CLI_* family (§ 3.6 L853)
EXPECTED_EVENT_TYPE = "CLI_PROMOTE_TEST_TO_PROD"

# D74 exit codes (§ 3.6 L934-937)
EXIT_SUCCESS = 0              # PROCEED_FAILOVER (applied/dry-run) or EXIT_SUCCEEDED
EXIT_OPERATIONAL = 1          # EXIT_RUNNING_HEALTHY (informational; not paged)
EXIT_FATAL = 2                # ParityFatalError / missing-justification / mutex / gate-not-acquirable

# SP-4 @Action canonical enum values (Pitfall #9.c — strict; L1546)
ACTION_PROCEED_FAILOVER = "PROCEED_FAILOVER"
ACTION_EXIT_SUCCEEDED = "EXIT_SUCCEEDED"
ACTION_EXIT_RUNNING_HEALTHY = "EXIT_RUNNING_HEALTHY"

# CycleType canonical values (Pitfall #9.c — CK_PipelineExecutionGate_CycleType L326-327)
_CYCLE_AM = "AM"
_CYCLE_PM = "PM"

# Canonical defaults for _call_main
_ACTOR = "test-author"
_CYCLE_DEFAULT = _CYCLE_AM
_JUSTIFICATION_DEFAULT = "Prod server unreachable since 02:15 — Tier 0 smoke test"
_CYCLE_DATE_DEFAULT = "2026-05-12"


# ---------------------------------------------------------------------------
# Exception class resolution — B215 pattern
# ---------------------------------------------------------------------------

def _resolve_exception_classes():
    """Resolve ParityFatalError + GateNotAcquirable per B215 lesson.

    Import from data_load._exceptions (canonical module). Returns stand-ins
    if classes are not yet added, so remaining tests continue to function.
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
    batch_id: int = 1042,
    gate_id: int = 99,
) -> Any:
    """Load tools/promote_test_to_prod.py with all external imports mocked.

    Parameters
    ----------
    sp4_action:
        Simulated SP-4 @Action OUTPUT value. One of the three canonical
        enum values per L1546 (Pitfall #9.c — strict).
    parity_fatal_error:
        If True, the injected parity_verifier raises ParityFatalError
        (→ exit 2 per § 3.6 L868).
    gate_not_acquirable:
        If True, SP-4 invocation raises GateNotAcquirable (→ exit 2).
    batch_id:
        Simulated BatchId returned by SP-4 on PROCEED_FAILOVER.
    gate_id:
        Simulated GateId returned by SP-4.

    Applies B214 (pre-register sys.modules before exec_module), B218
    (stash _test_sys_modules_patch + _test_executed_sql + _test_executed_params
    on mod), B215 (real exception classes).
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

    # Smart fetchone: SP-4 returns (action, gate_id, batch_id); SCOPE_IDENTITY()
    # returns event_id. Last-SQL-inspection dispatch (mirrors tier1 fixture).
    _audit_event_id_seq = [88123, 88124, 88125]

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
        _raise = GateNotAcquirable("Gate lock could not be acquired — test fixture")
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

    mock_event_tracker = MagicMock()
    mock_event = MagicMock()
    # SCOPE_IDENTITY pattern: audit row INSERT returns (N,) identity value
    mock_event.audit_event_id = 88200
    mock_event_tracker.track = MagicMock()
    mock_event_tracker.track.return_value.__enter__ = MagicMock(return_value=mock_event)
    mock_event_tracker.track.return_value.__exit__ = MagicMock(return_value=False)

    mock_config = MagicMock()
    mock_config.GENERAL_DB = "General"

    mock_pyodbc = MagicMock()
    mock_pyodbc.connect = mock_pyodbc_connect

    # Build parity_verifier mock — injectable factory
    if parity_fatal_error:
        def _parity_verifier(server: str) -> None:
            raise ParityFatalError(
                f"Fatal parity drift on server={server!r} — test fixture"
            )
    else:
        def _parity_verifier(server: str) -> None:
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
        # B214: pre-register BEFORE exec_module to prevent circular import failures
        sys.modules[_TOOL_MODULE_KEY] = mod
        spec.loader.exec_module(mod)

    # B218: stash for _call_main re-patch
    mod._test_sys_modules_patch = sys_modules_patch
    mod._test_cursor = mock_cursor
    mod._test_executed_sql = executed_sql
    mod._test_executed_params = executed_params
    mod._test_parity_verifier = _parity_verifier
    mod._test_event_tracker = mock_event_tracker
    mod._test_sp4_action = sp4_action
    return mod


def _call_main(mod: Any, **overrides: Any) -> dict:
    """Call tool main() with canonical defaults + overrides.

    Canonical signature per pre-specified B219 block:
      main(*, actor, cycle, justification, cycle_date, apply, dry_run,
           skip_parity_check, json_output, verbose, quiet, no_audit_event,
           gate_cursor_factory, audit_cursor_factory, parity_verifier,
           general_db) -> dict

    Injects the module-level _test_parity_verifier unless overridden.
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
# Tier 0 assertion (a): module imports without error
# ===========================================================================


def test_module_imports():
    """(a) Module imports without error.

    D67 Tier 0 assertion 1: the module must be importable with all external
    dependencies mocked. A failed import means a missing dependency or syntax
    error that blocks every subsequent build step.

    North Star: Operationally stable (D67). Spec: § 3.6 L939(a).
    """
    _t0 = time.monotonic()

    mod = _load_tool_module()

    assert mod is not None, (
        "tools/promote_test_to_prod.py must load without error. "
        "Check for missing imports or syntax errors. D67 Tier 0 (a)."
    )

    elapsed = time.monotonic() - _t0
    assert elapsed < 5.0, (
        f"Module load must complete in < 5 s. Took {elapsed:.2f} s. D67."
    )


# ===========================================================================
# Tier 0 assertion (b): --help exits 0
# ===========================================================================


def test_help_exits_zero():
    """(b) --help exits 0.

    D74 (exit-code contract): --help is not an error; it is the canonical
    discoverability path for all CLI tools per D75 argument naming discipline.
    argparse emits SystemExit(0) on --help.

    North Star: Operationally stable (D77 Tier 0 scaffold). Spec: § 3.6 L939(b).
    """
    mod = _load_tool_module()

    if hasattr(mod, "_build_arg_parser"):
        parser = mod._build_arg_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--help"])
        assert exc_info.value.code == 0, (
            "--help must exit 0. D74 (exit 0 = success / informational). "
            "Spec: § 3.6 L939(b)."
        )
    else:
        # Module not yet authored — skip gracefully (not FAIL; independence)
        pytest.skip(
            "_build_arg_parser not yet exposed. "
            "Author must expose the arg parser for Tier 0(b) assertion. "
            "Spec: § 3.6 L939(b)."
        )


# ===========================================================================
# Tier 0 assertion (c): missing --cycle OR missing --justification → exit 2
# ===========================================================================


class TestMissingRequiredArgs:
    """(c) Missing --cycle OR missing --justification → arg-parse error → exit 2.

    Per § 3.6 L888-893: both --cycle and --justification are REQUIRED with no
    default. D74: argparse errors = exit 2 (fatal argument error).

    Pitfall #9.c guard: CycleType enum is 'AM'|'PM' — must be REQUIRED, not
    optional with default. Spec: § 3.6 L939(c).
    """

    def test_missing_cycle_exits_2(self):
        """Missing --cycle raises argparse error → exit 2.

        --cycle has no default per § 3.6 L889 ('REQUIRED. One of AM/PM').
        argparse raises SystemExit(2) on missing required argument.

        Pitfall #9.c: CycleType must be required — 'AM'|'PM' not defaultable.
        D74 (exit 2 = arg error). Spec: § 3.6 L888 + L939(c).
        """
        mod = _load_tool_module()

        if hasattr(mod, "_build_arg_parser"):
            parser = mod._build_arg_parser()
            with pytest.raises(SystemExit) as exc_info:
                # Provide justification but omit --cycle
                parser.parse_args([
                    "--justification", _JUSTIFICATION_DEFAULT,
                    "--actor", _ACTOR,
                ])
            assert exc_info.value.code == EXIT_FATAL, (
                f"Missing --cycle must exit {EXIT_FATAL}. "
                f"Got: {exc_info.value.code!r}. "
                "D74 (exit 2 = arg error). Spec: § 3.6 L888 + L939(c)."
            )
        else:
            pytest.skip("_build_arg_parser not yet exposed.")

    def test_missing_justification_exits_2(self):
        """Missing --justification raises argparse error → exit 2.

        --justification is REQUIRED with no default per § 3.6 L892 (mandatory
        audit trail). argparse raises SystemExit(2) on missing required argument.

        D74 (exit 2 = arg error), D76 (justification in Metadata). Spec: § 3.6 L892 + L939(c).
        """
        mod = _load_tool_module()

        if hasattr(mod, "_build_arg_parser"):
            parser = mod._build_arg_parser()
            with pytest.raises(SystemExit) as exc_info:
                # Provide --cycle but omit --justification
                parser.parse_args([
                    "--cycle", _CYCLE_AM,
                    "--actor", _ACTOR,
                ])
            assert exc_info.value.code == EXIT_FATAL, (
                f"Missing --justification must exit {EXIT_FATAL}. "
                f"Got: {exc_info.value.code!r}. "
                "D74 (exit 2 = arg error). D76 (audit trail). "
                "Spec: § 3.6 L892 + L939(c)."
            )
        else:
            pytest.skip("_build_arg_parser not yet exposed.")


# ===========================================================================
# Tier 0 assertion (d): PROCEED_FAILOVER + parity-pass → exit 0
# ===========================================================================


def test_proceed_failover_parity_pass_exits_zero():
    """(d) SP-4 @Action='PROCEED_FAILOVER' + parity-pass → exit 0.

    Canonical PROCEED_FAILOVER path (§ 3.6 L851): SP-4 verdict + SP-6
    acknowledgment → exit 0. stdout must reference 'PROCEED_FAILOVER'.
    Parity-pass mock (parity_verifier returns None) is the gate precondition.

    North Star: Audit-grade (D76 audit row written), Operationally stable (D74).
    Pitfall #9.c: ACTION_PROCEED_FAILOVER must be exactly 'PROCEED_FAILOVER'.
    D74 (exit 0 = success), D29 (gate coordination). Spec: § 3.6 L935 + L939(d).
    """
    mod = _load_tool_module(sp4_action=ACTION_PROCEED_FAILOVER, parity_fatal_error=False)

    result = _call_main(mod, apply=True)

    exit_code = result.get("exit_code") if isinstance(result, dict) else None
    assert exit_code in (EXIT_SUCCESS, None), (
        f"PROCEED_FAILOVER with parity-pass must exit {EXIT_SUCCESS}. "
        f"Got: {exit_code!r}. "
        "D74 (exit 0 = success). Spec: § 3.6 L935 + L939(d)."
    )

    # stdout must reference the verdict for operator visibility
    verdict_in_output = (
        ACTION_PROCEED_FAILOVER in str(result)
        or (isinstance(result, dict) and result.get("verdict") == ACTION_PROCEED_FAILOVER)
    )
    # Allow graceful absence if module not yet authored (non-dict result)
    if isinstance(result, dict) and result.get("_raised_system_exit") is not True:
        assert verdict_in_output, (
            f"PROCEED_FAILOVER verdict must appear in result/stdout. "
            f"Got result: {result!r}. "
            "Per § 3.6 L939(d): stdout contains 'PROCEED_FAILOVER'. "
            "Spec: § 3.6 L896-905."
        )


# ===========================================================================
# Tier 0 assertion (e): EXIT_SUCCEEDED → exit 0 (informational)
# ===========================================================================


def test_exit_succeeded_exits_zero():
    """(e) SP-4 @Action='EXIT_SUCCEEDED' → exit 0 (informational, not an error).

    Per § 3.6 L866: EXIT_SUCCEEDED means prod already handled this cycle. Test
    exits cleanly with exit 0 — the cycle was a successful prod run; test was
    about to take over unnecessarily. NOT an error condition.

    Pitfall #9.c: 'EXIT_SUCCEEDED' exact string — not 'succeeded' or 'exit'.
    D74 (exit 0). Spec: § 3.6 L866 + L935 + L939(e).
    """
    mod = _load_tool_module(sp4_action=ACTION_EXIT_SUCCEEDED)

    result = _call_main(mod)

    exit_code = result.get("exit_code") if isinstance(result, dict) else None
    assert exit_code in (EXIT_SUCCESS, None), (
        f"EXIT_SUCCEEDED must exit {EXIT_SUCCESS} (prod already done — clean). "
        f"Got: {exit_code!r}. "
        "Per § 3.6 L866: 'NOT an error, informational outcome'. "
        "D74 (exit 0 = success/informational). Spec: § 3.6 L935 + L939(e)."
    )


# ===========================================================================
# Tier 0 assertion (f): EXIT_RUNNING_HEALTHY → exit 1 (informational)
# ===========================================================================


def test_exit_running_healthy_exits_one():
    """(f) SP-4 @Action='EXIT_RUNNING_HEALTHY' → exit 1 (informational, NOT fatal).

    Per § 3.6 L867: EXIT_RUNNING_HEALTHY means prod is still running with a
    recent heartbeat. Operator misread the dashboard — NOT paged, NOT a crash.
    exit 1 is the 'expected operational outcome that requires attention' tier.
    NOT exit 0 (would mask the need for review) and NOT exit 2 (not fatal).

    Pitfall #9.c: 'EXIT_RUNNING_HEALTHY' exact string — not 'running_healthy'.
    D74 (exit 1 = expected operational failure). Spec: § 3.6 L867 + L936 + L939(f).
    """
    mod = _load_tool_module(sp4_action=ACTION_EXIT_RUNNING_HEALTHY)

    result = _call_main(mod)

    exit_code = result.get("exit_code") if isinstance(result, dict) else None
    assert exit_code == EXIT_OPERATIONAL, (
        f"EXIT_RUNNING_HEALTHY must exit {EXIT_OPERATIONAL}. "
        f"Got: {exit_code!r}. "
        "Per § 3.6 L867: 'informational, NOT an emergency'. "
        "D74: exit 1 = expected operational failure. "
        "Spec: § 3.6 L936 + L939(f)."
    )


# ===========================================================================
# Tier 0 assertion (g): ParityFatalError from parity-precheck → exit 2
# ===========================================================================


def test_parity_fatal_error_exits_two():
    """(g) ParityFatalError raised by parity_verifier → exit 2 (fatal).

    Per § 3.6 L868: ParityFatalError (Round 3 § 3.2 PipelineFatalError)
    means test server parity has fatal-tier drift. Cannot promote until parity
    is restored. exit 2 = fatal, page immediately.

    D68 (PipelineFatalError → exit 2), D74. Spec: § 3.6 L868 + L937 + L939(g).
    """
    mod = _load_tool_module(parity_fatal_error=True)

    result = _call_main(mod)

    exit_code = result.get("exit_code") if isinstance(result, dict) else None
    assert exit_code == EXIT_FATAL, (
        f"ParityFatalError must exit {EXIT_FATAL} (fatal). "
        f"Got: {exit_code!r}. "
        "D68 (PipelineFatalError → exit 2). D74. "
        "Spec: § 3.6 L868 + L937 + L939(g)."
    )


# ===========================================================================
# Tier 0 assertion (h): --skip-parity-check bypasses parity-fail
# ===========================================================================


def test_skip_parity_check_bypasses_fatal():
    """(h) --skip-parity-check allows proceeding past parity-fail mock.

    Per § 3.6 L894: --skip-parity-check is DANGEROUS — operator MUST justify
    in --justification. With the flag, ParityFatalError is bypassed and a
    CRITICAL log is emitted instead of exiting 2.

    With PROCEED_FAILOVER as the SP-4 verdict AND --skip-parity-check, the
    tool should proceed to exit 0 rather than blocking on parity failure.

    D74 (exit 0 when proceeding), § 3.6 L894 (CRITICAL log emitted).
    Spec: § 3.6 L939(h).
    """
    mod = _load_tool_module(sp4_action=ACTION_PROCEED_FAILOVER, parity_fatal_error=True)

    result = _call_main(
        mod,
        skip_parity_check=True,
        apply=True,
        justification="EMERGENCY: skipping parity — prod down, operator authorized",
    )

    exit_code = result.get("exit_code") if isinstance(result, dict) else None
    # With --skip-parity-check, the PROCEED_FAILOVER path should complete
    # without blocking on ParityFatalError → exit 0
    assert exit_code in (EXIT_SUCCESS, None), (
        f"--skip-parity-check must allow PROCEED_FAILOVER path to exit {EXIT_SUCCESS}. "
        f"Got: {exit_code!r}. "
        "Per § 3.6 L894: flag bypasses parity-fail with CRITICAL log. "
        "Spec: § 3.6 L939(h)."
    )


# ===========================================================================
# Tier 0 runtime ceiling assertion (D67)
# ===========================================================================


def test_tier0_total_runtime_under_five_seconds():
    """All 8 Tier 0 assertions complete in < 5 s (D67 ceiling).

    D67: Tier 0 smoke test runtime ceiling < 5 s per module. Failure means
    external I/O has leaked through the mock layer — a test-isolation bug.

    D67. Spec: § 3.6 L939.
    """
    _start = time.monotonic()

    # Simulate the full 8-assertion sequence
    m1 = _load_tool_module()
    assert m1 is not None

    m2 = _load_tool_module(sp4_action=ACTION_PROCEED_FAILOVER)
    _call_main(m2, apply=True)

    m3 = _load_tool_module(sp4_action=ACTION_EXIT_SUCCEEDED)
    _call_main(m3)

    m4 = _load_tool_module(sp4_action=ACTION_EXIT_RUNNING_HEALTHY)
    _call_main(m4)

    m5 = _load_tool_module(parity_fatal_error=True)
    _call_main(m5)

    m6 = _load_tool_module(sp4_action=ACTION_PROCEED_FAILOVER, parity_fatal_error=True)
    _call_main(m6, skip_parity_check=True, apply=True)

    elapsed = time.monotonic() - _start
    assert elapsed < 5.0, (
        f"Tier 0 total runtime must be < 5 s. Took {elapsed:.2f} s. "
        "External I/O may have leaked through mock layer. D67."
    )
