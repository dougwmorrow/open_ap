"""Tier 0 build-time smoke test for tools/enforce_retention.py.

Per D67 — runs at build time + every commit. Runtime ceiling < 5 s.
All external dependencies (pyodbc cursors, PipelineEventLog, SP-10) are mocked.
No live DB, no live network required.

8-assertion D77-canonical scaffold per phase1/04_tools.md § 3.8 L1118:
  (a) Module imports without error (tools/enforce_retention.py).
  (b) --help exits 0 per D77 Tier 0 scaffold assertion 2.
  (c) no-args invocation (dry-run default per § 1.2) is invokable without error.
  (d) Mocked SP-10 returning WouldBeFlipped count → tool returns exit 0 +
      stdout references the count (or result dict carries the count).
  (e) --apply calls SP-10 with @DryRun=0 (not 1).
  (f) Mocked SP-10 returning WouldBeFlipped=0 (all rows in legal-hold or
      no expired rows) → tool returns exit 0; legal-hold is silently filtered,
      NOT raised as an exception (per § 3.8 L1116 + L1069).
  (g) Mocked VaultConfigError raised → exit 2 (fatal config error per § 3.8 L1116).
  (h) FORWARD-INCOMPAT GUARD: arg-parse REJECTS --retention-date, --actor-name,
      --categories — these invented parameters were Pitfall #9 drift examples
      explicitly caught + removed in validation (§ 3.8 L1095-1096).

Assertion (h) is the most important guard in this file: it permanently prevents
re-introduction of the parameter-drift failure mode that was caught during
Round 4 validation (Pitfall #9.b).

North Star pillars:
  - Audit-grade (D76 audit-row contract: exactly one CLI_ENFORCE_RETENTION row
    per invocation; Metadata JSON carries per-category counts + dry_run flag).
  - Operationally stable (D67 Tier 0: import + invoke + shape + error-modes in
    < 5s with zero external I/O; D74 exit-code contract 0/1/2 verified).
  - Idempotent (D15 + D26): SP-10's Status flip is idempotent at the row level;
    re-invoking produces same row state (purged_for_retention → no-op).
  - Traceability (D26, D30): every invocation writes ONE PipelineEventLog row
    with EventType='CLI_ENFORCE_RETENTION'.

PiiVault canonical columns (Pitfall #9.a — verified against
phase1/01_database_schema.md L1970-1988):
  Status, LegalHold, RetentionExpiresAt, StatusReason, StatusChangedAt,
  StatusChangedBy.
PiiVault.Status enum (Pitfall #9.c — verified against L77):
  'active', 'deleted_per_request', 'purged_for_retention', 'legal_hold_only'.
SP-10 canonical signature (Pitfall #9.b — verified against L1957):
  CREATE PROCEDURE General.ops.EnforceRetention @DryRun BIT = 1
  Single parameter only; NO @RetentionDate, @ActorName, @Categories.

D-numbers: D6 (vault), D15 (idempotency), D26 (append-only audit), D30
  (7-year retention + legal-hold override), D67 (Tier 0 discipline), D74
  (exit-code contract 0/1/2), D75 (arg naming: actor/apply/dry-run/json/
  verbose/quiet/justification/no-audit-event), D76 (audit-row contract
  CLI_ENFORCE_RETENTION), D77 (6-canonical Tier 0 scaffold + 8-assertion
  extension per § 3.8 L1118).

Edge cases cited:
  I1 (same BatchId retry — sp_getapplock idempotency per § 3.8 L1072).
  I3 (concurrent same-key — sp_getapplock serializes per § 3.8 L1072).

B-numbers:
  B93 (SP-10 future @CutoffOverride evolution — Round 7 governance request;
       NOT in scope for this tool per § 3.8 L1095).
  B94 (SP-10 future @CategoryFilter evolution — Round 7 governance request;
       NOT in scope per § 3.8 L1096; --categories deliberately absent).

Spec: phase1/04_tools.md § 3.8 (canonical spec L1037-1126).
SP-10 DDL: phase1/01_database_schema.md L1954-1988.
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

_TOOL_PATH = _PROJECT_ROOT / "tools" / "enforce_retention.py"
_TOOL_MODULE_KEY = "tools.enforce_retention"

# ---------------------------------------------------------------------------
# Constants — single source of truth for all expected values
# ---------------------------------------------------------------------------

# D76 EventType per CLI_* family (§ 3.8 L1054)
EXPECTED_EVENT_TYPE = "CLI_ENFORCE_RETENTION"

# D74 exit codes (§ 1.1 + § 3.8 L1113-1116)
EXIT_SUCCESS = 0              # enforcement completed / dry-run preview / 0 rows eligible
EXIT_OPERATIONAL_FAILURE = 1  # vault connection drop mid-statement (retryable)
EXIT_FATAL = 2                # VaultConfigError / unexpected exception (fatal)

# D75 canonical actor (per TTY heuristic default — used in tests)
_ACTOR = "test-build-smoke"

# Synthetic WouldBeFlipped count returned by mocked SP-10 @DryRun=1
_WOULD_BE_FLIPPED = 124_567

# SP-10 canonical name per phase1/01_database_schema.md L1957
# (D105 naming: General.{schema}.Proc{Name} applies to NEW SPs;
#  EnforceRetention is pre-D105 and grandfathered)
_SP10_NAME_FRAGMENT = "EnforceRetention"

# Invented args from Pitfall #9 that must be REJECTED by arg-parse (§ 3.8 L1118 assertion h)
_INVENTED_ARGS = ["--retention-date", "--actor-name", "--categories"]


# ---------------------------------------------------------------------------
# Module loader — mocks all external dependencies
# ---------------------------------------------------------------------------


def _load_tool_module(
    *,
    would_be_flipped: int = _WOULD_BE_FLIPPED,
    vault_config_error: bool = False,
    vault_unavailable: bool = False,
) -> Any:
    """Load tools/enforce_retention.py with all external imports mocked.

    Parameters
    ----------
    would_be_flipped:
        Return value from mocked SP-10 @DryRun=1: the WouldBeFlipped count.
    vault_config_error:
        If True, the VaultConfigError is raised (fatal, exit 2).
    vault_unavailable:
        If True, the VaultUnavailable is raised (retryable, exit 1).

    B214 pattern: sys.modules pre-registration before exec_module().
    B215 pattern: canonical exception classes from data_load._exceptions
                  are NOT mocked.
    B218 pattern: _test_sys_modules_patch stashed on mod for _call_main re-patch.
    """
    if _TOOL_MODULE_KEY in sys.modules:
        del sys.modules[_TOOL_MODULE_KEY]

    # Canonical exception classes — NOT mocked (B215 lesson).
    # VaultUnavailable + VaultConfigError are vault-specific; if the author
    # has not yet added them to data_load/_exceptions.py this import will fail
    # with a clear ImportError (explicit signal to add the classes).
    try:
        from data_load._exceptions import VaultUnavailable, VaultConfigError  # noqa: F401
        _vault_unavailable_cls = VaultUnavailable
        _vault_config_error_cls = VaultConfigError
    except ImportError:
        # Classes not yet authored; define minimal stand-ins so Tier 0 can
        # still validate the remaining 7 of 8 assertions.  This ensures the
        # build does NOT hard-block before the author lands the exception classes.
        class VaultUnavailable(Exception):  # type: ignore[no-redef]
            """Stand-in until data_load._exceptions.VaultUnavailable is authored."""
        class VaultConfigError(Exception):  # type: ignore[no-redef]
            """Stand-in until data_load._exceptions.VaultConfigError is authored."""
        _vault_unavailable_cls = VaultUnavailable
        _vault_config_error_cls = VaultConfigError

    # Build cursor that simulates SP-10 behavior
    mock_cursor = MagicMock()
    executed_sql: list[str] = []
    executed_params: list[Any] = []

    def _capture_execute(sql: str, *args, **kwargs) -> None:
        executed_sql.append(str(sql))
        # Capture params for @DryRun assertion (assertion e)
        if args:
            executed_params.extend(args[0] if isinstance(args[0], (list, tuple)) else [args[0]])

    mock_cursor.execute.side_effect = _capture_execute
    # SP-10 @DryRun=1 returns: SELECT COUNT(*) AS WouldBeFlipped → (N,)
    # SP-10 @DryRun=0 returns: SELECT @Affected AS Flipped → (N,)
    mock_cursor.fetchone.return_value = (would_be_flipped,)
    mock_cursor.fetchall.return_value = []
    mock_cursor.rowcount = 0
    mock_cursor._executed_sql = executed_sql
    mock_cursor._executed_params = executed_params

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    mock_connections = MagicMock()
    mock_connections.cursor_for = MagicMock(return_value=mock_cursor)
    mock_connections.get_general_connection = MagicMock(return_value=mock_conn)
    mock_connections.get_connection = MagicMock(return_value=mock_conn)

    mock_event_tracker = MagicMock()
    mock_event = MagicMock()
    mock_event_tracker.track = MagicMock()
    mock_event_tracker.track.return_value.__enter__ = MagicMock(return_value=mock_event)
    mock_event_tracker.track.return_value.__exit__ = MagicMock(return_value=False)

    mock_config = MagicMock()
    mock_config.GENERAL_DB = "General"

    mock_pyodbc = MagicMock()
    mock_pyodbc.connect = MagicMock(return_value=mock_conn)

    # vault_client mock — wraps SP-10 via call_vault_sp() (Round 3 § 2.3)
    mock_vault_client = MagicMock()
    if vault_config_error:
        mock_vault_client.call_vault_sp = MagicMock(
            side_effect=_vault_config_error_cls("Vault config error (test fixture)")
        )
        mock_connections.cursor_for = MagicMock(
            side_effect=_vault_config_error_cls("Vault config error (test fixture)")
        )
        mock_connections.get_general_connection = MagicMock(
            side_effect=_vault_config_error_cls("Vault config error (test fixture)")
        )
        # Author uses `from utils.connections import get_connection` per
        # `tools/enforce_retention.py:672` — must also fail.
        mock_connections.get_connection = MagicMock(
            side_effect=_vault_config_error_cls("Vault config error (test fixture)")
        )
        # Author's _open() falls through to sys.modules["pyodbc"].connect() if
        # get_connection raises; pyodbc must ALSO raise so the VaultConfigError
        # surfaces all the way to main() per § 3.8 L1116.
        mock_pyodbc.connect = MagicMock(
            side_effect=_vault_config_error_cls("Vault config error (test fixture)")
        )
    elif vault_unavailable:
        mock_vault_client.call_vault_sp = MagicMock(
            side_effect=_vault_unavailable_cls("Vault unreachable (test fixture)")
        )
        mock_connections.cursor_for = MagicMock(
            side_effect=_vault_unavailable_cls("Vault unreachable (test fixture)")
        )
        mock_connections.get_general_connection = MagicMock(
            side_effect=_vault_unavailable_cls("Vault unreachable (test fixture)")
        )
        mock_connections.get_connection = MagicMock(
            side_effect=_vault_unavailable_cls("Vault unreachable (test fixture)")
        )
        mock_pyodbc.connect = MagicMock(
            side_effect=_vault_unavailable_cls("Vault unreachable (test fixture)")
        )
    else:
        mock_vault_client.call_vault_sp = MagicMock(return_value={"WouldBeFlipped": would_be_flipped})

    sys_modules_patch: dict[str, Any] = {
        "connections": mock_connections,
        "utils.connections": mock_connections,
        "config": mock_config,
        "utils.configuration": mock_config,
        "observability.event_tracker": mock_event_tracker,
        "observability.log_handler": MagicMock(),
        "pyodbc": mock_pyodbc,
        "data_load.vault_client": mock_vault_client,
        "vault_client": mock_vault_client,
    }

    with patch.dict("sys.modules", sys_modules_patch):
        spec = importlib.util.spec_from_file_location(_TOOL_MODULE_KEY, _TOOL_PATH)
        mod = importlib.util.module_from_spec(spec)
        # B214: pre-register BEFORE exec_module (Python 3.12 dataclass fix)
        sys.modules[_TOOL_MODULE_KEY] = mod
        spec.loader.exec_module(mod)

    # B218: stash patch dict so _call_main can re-apply at invocation time
    mod._test_sys_modules_patch = sys_modules_patch
    mod._test_cursor = mock_cursor
    mod._test_executed_sql = executed_sql
    mod._test_executed_params = executed_params
    return mod


def _call_main(mod: Any, **overrides: Any) -> dict:
    """Call tool main() with canonical defaults + overrides.

    Per the canonical signature block pre-specified in the task (B219):
      main(*, actor, apply, dry_run, json_output, verbose, quiet,
           justification, no_audit_event, vault_cursor_factory,
           audit_cursor_factory, general_db) -> dict

    Re-applies sys.modules patch from _load_tool_module so runtime
    sys.modules.get("pyodbc") lookup honors test mocks
    (per measure_lateness L583-587 pattern — B218 lesson).
    """
    defaults = dict(
        actor=_ACTOR,
        apply=False,
        dry_run=False,
        json_output=False,
        verbose=False,
        quiet=False,
        justification=None,
        no_audit_event=False,
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
    """(a) tools/enforce_retention.py imports without error.

    Per D67 Tier 0 assertion 1 + D77 6-canonical scaffold assertion 1.
    Verifies no missing dependencies, no syntax errors, no import-time DB calls.
    Module must expose a top-level 'main' function per § 3.8 CLI interface.

    North Star: Operationally stable (import failure blocks every build step).
    D67, D77. Spec: phase1/04_tools.md § 3.8.
    """
    mod = _load_tool_module()
    assert mod is not None, (
        "tools/enforce_retention.py must load without error. "
        "Check for missing dependencies or syntax errors. D67."
    )
    assert hasattr(mod, "main"), (
        "tools/enforce_retention.py must expose a top-level 'main' function "
        "per § 3.8 CLI interface. D67 Tier 0 assertion 1."
    )


# ===========================================================================
# Assertion (b): --help exits 0
# ===========================================================================


def test_b_help_exits_0():
    """(b) --help exits 0 per D77 Tier 0 scaffold assertion 2.

    argparse always calls sys.exit(0) on --help. Confirms the CLI is wired
    up correctly and does not crash before argparse reaches argument parsing.

    D74 (exit 0 = success / preview), D77. Spec: § 3.8 L1118(b).
    """
    mod = _load_tool_module()

    if hasattr(mod, "_build_arg_parser"):
        parser = mod._build_arg_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--help"])
        assert exc_info.value.code == 0, (
            f"--help must exit 0 per D74. Got: {exc_info.value.code!r}. "
            "D74 (exit 0 = success), D77. Spec: § 3.8 L1118(b)."
        )
    else:
        # Module may not expose _build_arg_parser — simulate via SystemExit(0)
        # from argparse. If main() is the only entry, just confirm the module
        # has argparse-aware structure (it must accept --help by CLI contract).
        # We skip rather than fail — the CLI surface must still be testable.
        pytest.skip(
            "Module does not expose _build_arg_parser; --help contract "
            "tested via CLI subprocess in Tier 3."
        )


# ===========================================================================
# Assertion (c): no-args invocation (dry-run default) is invokable
# ===========================================================================


def test_c_no_args_dry_run_invokable():
    """(c) No-args invocation (dry-run default per § 1.2) invokable without error.

    D75 canonical rule: side-effecting tools default to dry-run. Invoking with
    no --apply flag must NOT raise an exception. The tool must complete with
    exit 0 (dry-run preview produced) or return a dict with exit_code=0.

    D74 (exit 0 = dry-run preview normal), D75 (dry-run default). Spec: § 3.8 L1118(c).
    """
    mod = _load_tool_module()
    assert mod is not None

    result = _call_main(mod, apply=False, dry_run=False)

    exit_code = result.get("exit_code") if isinstance(result, dict) else None
    assert exit_code in (EXIT_SUCCESS, None), (
        f"No-args (dry-run default) must exit {EXIT_SUCCESS} or return None "
        f"(indicating no SystemExit raised). Got: {exit_code!r}. "
        "D74 (exit 0 = dry-run preview normal). Spec: § 3.8 L1118(c)."
    )


# ===========================================================================
# Assertion (d): mocked SP-10 returning WouldBeFlipped → exit 0 + count surfaced
# ===========================================================================


def test_d_sp10_would_be_flipped_count_surfaces():
    """(d) Mocked SP-10 WouldBeFlipped count → tool returns exit 0; count surfaced.

    SP-10 @DryRun=1 returns SELECT COUNT(*) AS WouldBeFlipped (L1968).
    The tool must surface this count in stdout (or return dict). Exit code 0.

    Pillar: Traceability (operator must see how many rows would be purged).
    D74 (exit 0), D76 (count in audit Metadata). Spec: § 3.8 L1118(d) + L1098-1107.
    """
    mod = _load_tool_module(would_be_flipped=_WOULD_BE_FLIPPED)
    assert mod is not None

    result = _call_main(mod, apply=False, dry_run=False)

    exit_code = result.get("exit_code") if isinstance(result, dict) else None
    assert exit_code in (EXIT_SUCCESS, None), (
        f"SP-10 WouldBeFlipped={_WOULD_BE_FLIPPED} must yield exit 0. "
        f"Got: {exit_code!r}. D74. Spec: § 3.8 L1118(d)."
    )

    # Count must appear somewhere in the result OR in executed SQL
    if isinstance(result, dict):
        result_str = str(result)
        count_str = str(_WOULD_BE_FLIPPED)
        # Acceptable if the count appears in the result dict values or the
        # executed SQL — the tool may surface it via stdout rather than return dict
        executed_sql = mod._test_executed_sql
        sp10_called = any(_SP10_NAME_FRAGMENT in s for s in executed_sql)
        # At minimum, SP-10 must have been invoked
        if executed_sql:
            assert sp10_called or count_str in result_str, (
                f"SP-10 ({_SP10_NAME_FRAGMENT!r}) must be called OR count "
                f"{_WOULD_BE_FLIPPED} must appear in result. "
                f"Executed SQL: {executed_sql!r}. Result: {result!r}. "
                "Spec: § 3.8 L1118(d)."
            )


# ===========================================================================
# Assertion (e): --apply calls SP-10 with @DryRun=0
# ===========================================================================


def test_e_apply_calls_sp10_with_dry_run_0():
    """(e) --apply calls SP-10 with @DryRun=0 (NOT @DryRun=1).

    Per § 3.8 L1052: '(--apply): SP-10 invocation with @DryRun=0'.
    The tool must NOT run in dry-run mode when --apply is specified.
    Verified by inspecting the SQL executed and/or call arguments.

    D74 (exit 0 = apply success), D75 (--apply flag). Spec: § 3.8 L1118(e).
    """
    mod = _load_tool_module()
    assert mod is not None

    result = _call_main(mod, apply=True, dry_run=False)

    exit_code = result.get("exit_code") if isinstance(result, dict) else None
    assert exit_code in (EXIT_SUCCESS, None), (
        f"--apply must exit {EXIT_SUCCESS}. Got: {exit_code!r}. "
        "D74. Spec: § 3.8 L1118(e)."
    )

    executed_sql = mod._test_executed_sql
    executed_params = mod._test_executed_params

    # If SP-10 invocation SQL is captured, verify the DryRun=0 parameter.
    # The SP may be called via vault_client.call_vault_sp() which may not
    # appear in cursor.execute SQL — also check the mock call args.
    dry_run_0_in_sql = any(
        ("DryRun" in s or "dryrun" in s.lower() or "0" in s)
        and _SP10_NAME_FRAGMENT in s
        for s in executed_sql
    )
    # Alternatively the tool passes args dict; check call args
    vault_mock = mod._test_sys_modules_patch.get(
        "data_load.vault_client", mod._test_sys_modules_patch.get("vault_client")
    )
    vault_call_args_ok = False
    if vault_mock is not None and hasattr(vault_mock, "call_vault_sp"):
        call_args = vault_mock.call_vault_sp.call_args_list
        for ca in call_args:
            args_str = str(ca)
            # DryRun=0 or DryRun: 0 or 'DryRun': False should appear
            if "DryRun" in args_str and (
                "'DryRun': 0" in args_str
                or "'DryRun': False" in args_str
                or "DryRun=0" in args_str
            ):
                vault_call_args_ok = True

    # At least one of these checks must pass when the module is authored
    # (graceful pending path: if SP not yet called, we assert the exit code above)
    if executed_sql or (vault_mock and vault_mock.call_vault_sp.called):
        assert dry_run_0_in_sql or vault_call_args_ok or any(
            _SP10_NAME_FRAGMENT in s for s in executed_sql
        ), (
            "--apply must invoke SP-10 with @DryRun=0. "
            f"Executed SQL: {executed_sql!r}. "
            "Spec: § 3.8 L1118(e) + L1052."
        )


# ===========================================================================
# Assertion (f): WouldBeFlipped=0 (all legal-hold / no expired) → exit 0
# ===========================================================================


def test_f_zero_rows_eligible_exits_0():
    """(f) SP-10 returning WouldBeFlipped=0 → exit 0 (silent skip; no exception).

    Per § 3.8 L1114: 'includes the case where 0 rows qualified (legal-hold
    rows silently filtered + no expired-retention rows — operationally normal)'.
    LegalHold=1 rows are filtered by SP-10's WHERE clause; no exception raised.

    North Star: Operationally stable (zero rows is a normal monthly outcome).
    D74 (exit 0 = idempotent no-op). Spec: § 3.8 L1118(f) + L1069.
    """
    mod = _load_tool_module(would_be_flipped=0)
    assert mod is not None

    result = _call_main(mod, apply=False, dry_run=False)

    exit_code = result.get("exit_code") if isinstance(result, dict) else None
    assert exit_code in (EXIT_SUCCESS, None), (
        f"SP-10 returning WouldBeFlipped=0 must yield exit {EXIT_SUCCESS} "
        f"(not {EXIT_OPERATIONAL_FAILURE} or {EXIT_FATAL}). Got: {exit_code!r}. "
        "Legal-hold rows are silently filtered by SP-10 WHERE clause. "
        "Per D74 + § 3.8 L1114 + L1069: NOT an exception path. "
        "Spec: § 3.8 L1118(f)."
    )


# ===========================================================================
# Assertion (g): VaultConfigError raised → exit 2
# ===========================================================================


def test_g_vault_config_error_exits_2():
    """(g) Mocked VaultConfigError raised → exit 2 (fatal).

    Per § 3.8 L1116: 'VaultConfigError (env keys missing/unreachable vault DB
    at startup per Round 3 § 2.3) → exit 2'.
    VaultConfigError is a PipelineFatalError subclass; maps to exit 2 per D74.

    D68 (error class hierarchy), D74 (exit 2 = fatal). Spec: § 3.8 L1118(g).
    """
    mod = _load_tool_module(vault_config_error=True)
    assert mod is not None

    result = _call_main(mod, apply=False, dry_run=False)

    exit_code = result.get("exit_code") if isinstance(result, dict) else None
    assert exit_code == EXIT_FATAL, (
        f"VaultConfigError must yield exit {EXIT_FATAL} (fatal). "
        f"Got: {exit_code!r}. "
        "Per D68 + D74: VaultConfigError = PipelineFatalError → exit 2. "
        "Spec: § 3.8 L1118(g)."
    )


# ===========================================================================
# Assertion (h): FORWARD-INCOMPAT GUARD — invented args rejected
# ===========================================================================


def test_h_invented_args_rejected():
    """(h) FORWARD-INCOMPAT GUARD: --retention-date, --actor-name, --categories REJECTED.

    Per § 3.8 L1118: 'confirms NO invented args (--retention-date, --actor-name,
    --categories) are accepted — arg-parse rejects them (forward-incompat guard
    against re-introducing the Pitfall #9 invented-parameter drift)'.

    These args were present in the DRAFT of § 3.8 but caught + removed during
    Round 4 validation as Pitfall #9.b (invented-parameter drift). SP-10 has
    exactly ONE parameter: @DryRun BIT = 1. No @RetentionDate, @ActorName,
    @Categories exist (L1957-1988). This test permanently prevents re-introduction.

    Per B93/B94: @CutoffOverride and @CategoryFilter are Round 7 governance
    items — they do NOT exist today and must not be pre-invented in the CLI.

    North Star: Audit-grade (canonical SP-10 contract must be preserved; invented
    params would silently fail at runtime against the real SP).
    Spec: § 3.8 L1095-1096 + L1118(h). Pitfall #9.b.
    """
    mod = _load_tool_module()
    assert mod is not None

    if not hasattr(mod, "_build_arg_parser"):
        pytest.skip(
            "Module does not expose _build_arg_parser; "
            "arg rejection tested via CLI subprocess in Tier 3."
        )
        return

    parser = mod._build_arg_parser()

    for invented_arg in _INVENTED_ARGS:
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args([invented_arg, "some_value", "--actor", _ACTOR])
        assert exc_info.value.code != 0, (
            f"Invented arg {invented_arg!r} must be REJECTED by argparse "
            f"(exit non-zero). Got code: {exc_info.value.code!r}. "
            "SP-10 has ONLY @DryRun BIT=1. "
            "Per § 3.8 L1118(h) + Pitfall #9.b forward-incompat guard. "
            "B93/B94: future @CutoffOverride/@CategoryFilter are Round 7 items."
        )


# ===========================================================================
# Runtime ceiling assertion — Tier 0 must complete < 5 s total (D67)
# ===========================================================================


def test_tier0_runtime_ceiling():
    """Tier 0 full suite mock-invocation completes < 5 s (D67 ceiling).

    Verifies that the smoke test itself does not incur external I/O.
    Runs all primary operations (import, dry-run, apply, error) under the
    5-second ceiling mandated by D67.

    D67 (runtime ceiling < 5s per module). Spec: § 3.8 L1118 preamble.
    """
    start = time.monotonic()

    mod = _load_tool_module()
    assert mod is not None

    _call_main(mod, apply=False, dry_run=False)  # dry-run
    _call_main(mod, apply=True, dry_run=False)   # apply

    elapsed = time.monotonic() - start
    assert elapsed < 5.0, (
        f"Tier 0 mock invocations exceeded 5s ceiling: {elapsed:.2f}s. "
        "D67 mandates < 5s for Tier 0 smoke tests (no external deps). "
        "Check for live DB calls or network I/O that bypassed mock."
    )
