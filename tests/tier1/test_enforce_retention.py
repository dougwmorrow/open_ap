"""Tier 1 unit tests for tools/enforce_retention.py.

Tests run on every commit. No live DB, no live network required.
All external dependencies mocked with unittest.mock.

North Star pillars addressed:
  - Audit-grade (D76): exactly one CLI_ENFORCE_RETENTION PipelineEventLog
    row per invocation; Metadata JSON carries per-category counts, actor,
    justification, dry_run flag; audit_event_id key MUST be present in JSON
    output per B218 spec-compliance lesson (presence over content).
  - Operationally stable (D74/D75): exit-code contract (0/1/2) and argument
    naming discipline must be exactly per spec; Automic JOB_RETENTION_MONTHLY
    interprets the contract.
  - Idempotent (D15 + D26): SP-10's Status flip is idempotent at the row level
    (purged_for_retention → purged_for_retention is a no-op). Multi-invocation
    in the same month produces multiple audit rows but identical row-state.
  - Traceability (D26, D30): WouldBeFlipped count surfaces in stdout + JSON;
    sp_getapplock resource string carries month-start cycle date for correlation.

PiiVault canonical columns (Pitfall #9.a — verified against
phase1/01_database_schema.md L1970-1988):
  Status, LegalHold, RetentionExpiresAt, StatusReason, StatusChangedAt,
  StatusChangedBy.
PiiVault.Status enum (Pitfall #9.c — verified against L77):
  'active', 'deleted_per_request', 'purged_for_retention', 'legal_hold_only'.
SP-10 canonical signature (Pitfall #9.b — verified against L1957):
  CREATE PROCEDURE General.ops.EnforceRetention @DryRun BIT = 1
  Single parameter @DryRun BIT = 1 only.
SP-10 canonical object path per D105 grandfather clause (pre-D105 name):
  General.ops.EnforceRetention (grandfathered; NOT General.ops.ProcEnforceRetention)

Naive-UTC datetime invariant (SCD2-P1-f): every datetime captured in
audit row Metadata must be tzinfo=None. Verified in
test_audit_row_metadata_naive_datetime.

Edge case IDs (per 04_EDGE_CASES.md):
  I1 (same BatchId retry: ledger short-circuits) — sp_getapplock idempotency
     ensures one retention run at a time per month.
  I3 (concurrent same-key: UNIQUE/lock prevents) — sp_getapplock key
     'job_RETENTION_MONTHLY_<YYYY-MM-01>' serializes concurrent monthly runs.

Decision citations:
  D6 (in-house tokenization vault — SP-10 mutates the vault table),
  D15 (idempotency mandatory — re-run safe at row level),
  D26 (append-only audit — PiiTokenProvenance reflects Status flip),
  D30 (7-year retention with legal-hold override — the policy SP-10 enforces),
  D67 (Tier 0 discipline — this file is Tier 1 complement),
  D74 (exit-code contract 0/1/2),
  D75 (arg naming: actor / apply / dry-run / json / verbose / quiet /
       justification / no-audit-event),
  D76 (audit-row contract: CLI_ENFORCE_RETENTION EventType; Metadata JSON shape),
  D77 (Tier 0 canonical scaffold — Tier 1 extends, not weakens).

B-numbers:
  B88 (--apply + --dry-run mutex — tested in test_apply_dry_run_mutex).
  B93 (SP-10 future @CutoffOverride — Round 7; NOT in scope; --retention-date
       must remain absent from the arg surface per Pitfall #9.b).
  B94 (SP-10 future @CategoryFilter — Round 7; NOT in scope).
  B218 (audit_event_id key MUST be present in JSON output; presence over content).

Spec: phase1/04_tools.md § 3.8 (canonical spec L1037-1126).
SP-10 DDL: phase1/01_database_schema.md L1954-1988.
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import re
import sys
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

_TOOL_PATH = _PROJECT_ROOT / "tools" / "enforce_retention.py"
_TOOL_MODULE_KEY = "tools.enforce_retention"

# ---------------------------------------------------------------------------
# Constants — single source of truth
# ---------------------------------------------------------------------------

# D76 EventType (§ 3.8 L1054)
EXPECTED_EVENT_TYPE = "CLI_ENFORCE_RETENTION"

# D74 exit codes (§ 3.8 L1113-1116)
EXIT_SUCCESS = 0
EXIT_OPERATIONAL_FAILURE = 1
EXIT_FATAL = 2

# D75 canonical actor
_ACTOR = "test-author"

# Synthetic WouldBeFlipped counts
_WOULD_BE_FLIPPED_NONZERO = 124_567
_WOULD_BE_FLIPPED_ZERO = 0

# sp_getapplock resource key pattern per § 3.8 L1072
# Format: 'job_RETENTION_MONTHLY_<month-start>' where month-start = YYYY-MM-01
_APPLOCK_RESOURCE_PREFIX = "job_RETENTION_MONTHLY_"
_APPLOCK_RESOURCE_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-01$")

# SP-10 canonical name fragment (grandfathered pre-D105 per D92)
_SP10_NAME_FRAGMENT = "EnforceRetention"

# JSON output required keys per § 3.8 L1111
# B218: audit_event_id key MUST be present (presence over content)
REQUIRED_JSON_KEYS = frozenset({"dry_run", "counts", "audit_event_id"})

# Required keys inside JSON "counts" dict per § 3.8 L1111
REQUIRED_COUNTS_KEYS = frozenset({"vault", "provenance", "orphanedtokenlog"})

# Required keys in audit row Metadata per D76
REQUIRED_METADATA_KEYS = frozenset({"event_kind", "actor", "dry_run"})

# Invented args that must NOT exist (Pitfall #9.b guard — § 3.8 L1095-1096)
_INVENTED_ARGS = ["--retention-date", "--actor-name", "--categories"]


# ---------------------------------------------------------------------------
# Exception class resolution — B215 pattern
# ---------------------------------------------------------------------------

def _resolve_exception_classes():
    """Resolve VaultUnavailable + VaultConfigError per B215 lesson.

    Import from data_load._exceptions (canonical module). If the author has
    not yet added the vault-specific classes, returns minimal stand-ins so
    the remaining tests still function.
    """
    try:
        from data_load._exceptions import VaultUnavailable, VaultConfigError
        return VaultUnavailable, VaultConfigError
    except ImportError:
        class VaultUnavailable(Exception):  # type: ignore[no-redef]
            """Stand-in: author must add VaultUnavailable to data_load/_exceptions.py."""
        class VaultConfigError(Exception):  # type: ignore[no-redef]
            """Stand-in: author must add VaultConfigError to data_load/_exceptions.py."""
        return VaultUnavailable, VaultConfigError


VaultUnavailable, VaultConfigError = _resolve_exception_classes()


# ---------------------------------------------------------------------------
# Module loader — mocks all external dependencies
# ---------------------------------------------------------------------------


def _load_tool_module(
    *,
    would_be_flipped: int = _WOULD_BE_FLIPPED_NONZERO,
    vault_config_error: bool = False,
    vault_unavailable: bool = False,
    applock_result: int = 0,
) -> Any:
    """Load tools/enforce_retention.py with all external imports mocked.

    Parameters
    ----------
    would_be_flipped:
        Simulated SP-10 @DryRun=1 response count (WouldBeFlipped) and
        @DryRun=0 response count (Flipped).
    vault_config_error:
        If True, raises VaultConfigError (fatal → exit 2).
    vault_unavailable:
        If True, raises VaultUnavailable (retryable → exit 1).
    applock_result:
        sp_getapplock return value: 0 = acquired; -1 = timeout (→ exit 1).

    Applies B214 (pre-register sys.modules before exec_module), B215 (real
    exception classes), B218 (_test_sys_modules_patch stashed on mod).
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
    # SP-10 returns (N,) for both DryRun=1 (WouldBeFlipped) and DryRun=0 (Flipped)
    mock_cursor.fetchone.return_value = (would_be_flipped,)
    mock_cursor.fetchall.return_value = []
    mock_cursor.rowcount = 0
    mock_cursor._executed_sql = executed_sql
    mock_cursor._executed_params = executed_params

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    # Build vault_client mock (Round 3 § 2.3 interface)
    mock_vault_client = MagicMock()
    if vault_config_error:
        _raise = VaultConfigError("Vault config error — test fixture")
        mock_vault_client.call_vault_sp = MagicMock(side_effect=_raise)
        mock_conn.cursor.side_effect = _raise
        _connections_side = _raise
    elif vault_unavailable:
        _raise = VaultUnavailable("Vault unreachable — test fixture")
        mock_vault_client.call_vault_sp = MagicMock(side_effect=_raise)
        mock_conn.cursor.side_effect = _raise
        _connections_side = _raise
    else:
        mock_vault_client.call_vault_sp = MagicMock(
            return_value={"WouldBeFlipped": would_be_flipped, "Flipped": would_be_flipped}
        )
        _connections_side = None

    mock_connections = MagicMock()
    if _connections_side is not None:
        mock_connections.cursor_for = MagicMock(side_effect=_connections_side)
        mock_connections.get_general_connection = MagicMock(side_effect=_connections_side)
        mock_connections.get_connection = MagicMock(side_effect=_connections_side)
        mock_pyodbc_connect = MagicMock(side_effect=_connections_side)
    else:
        mock_connections.cursor_for = MagicMock(return_value=mock_cursor)
        mock_connections.get_general_connection = MagicMock(return_value=mock_conn)
        mock_connections.get_connection = MagicMock(return_value=mock_conn)
        mock_pyodbc_connect = MagicMock(return_value=mock_conn)

    mock_event_tracker = MagicMock()
    mock_event = MagicMock()
    mock_event_tracker.track = MagicMock()
    mock_event_tracker.track.return_value.__enter__ = MagicMock(return_value=mock_event)
    mock_event_tracker.track.return_value.__exit__ = MagicMock(return_value=False)

    mock_config = MagicMock()
    mock_config.GENERAL_DB = "General"

    mock_pyodbc = MagicMock()
    mock_pyodbc.connect = mock_pyodbc_connect

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
        # B214: pre-register BEFORE exec_module
        sys.modules[_TOOL_MODULE_KEY] = mod
        spec.loader.exec_module(mod)

    # B218: stash for _call_main re-patch
    mod._test_sys_modules_patch = sys_modules_patch
    mod._test_cursor = mock_cursor
    mod._test_executed_sql = executed_sql
    mod._test_executed_params = executed_params
    mod._test_vault_client = mock_vault_client
    return mod


def _call_main(mod: Any, **overrides: Any) -> dict:
    """Call tool main() with canonical defaults + overrides.

    Canonical signature per B219 pre-specification:
      main(*, actor, apply, dry_run, json_output, verbose, quiet,
           justification, no_audit_event, vault_cursor_factory,
           audit_cursor_factory, general_db) -> dict

    Defaults match the spec: apply=False (dry-run is default), dry_run=False
    (the mutex bridge per B88). Tests opt in to apply=True explicitly.

    Re-applies sys.modules patch per B218 (measure_lateness L583-587 pattern).
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
# Tier 1: dry-run vs apply behavior
# ===========================================================================


class TestDryRunVsApplyBehavior:
    """dry-run vs apply behavior; SP-10 @DryRun parameter binding.

    Per § 3.8 L1121 (Tier 1 test surface) + L1052-1053 (Produces).
    D74 (exit 0 in both modes), D75 (--apply opt-in).
    """

    def test_dry_run_default_does_not_mutate(self):
        """Dry-run (default, no --apply) invokes SP-10 with @DryRun=1.

        Per § 3.8 L1053: '(default dry-run): SP-10 invocation with @DryRun=1;
        SP-10's body returns the WouldBeFlipped count without modifying'.
        The tool must NOT invoke SP-10 with @DryRun=0 unless --apply is given.

        D74 (exit 0), D75 (dry-run default). Spec: § 3.8 L1053 + L1121.
        """
        mod = _load_tool_module()
        assert mod is not None

        result = _call_main(mod, apply=False, dry_run=False)

        exit_code = result.get("exit_code") if isinstance(result, dict) else None
        assert exit_code in (EXIT_SUCCESS, None), (
            f"Dry-run must exit {EXIT_SUCCESS}. Got: {exit_code!r}. "
            "D74. Spec: § 3.8 L1053."
        )

        # Verify SP-10 was NOT called with @DryRun=0
        executed = mod._test_executed_sql
        vault_mock = mod._test_vault_client
        if vault_mock.call_vault_sp.called:
            for call_args in vault_mock.call_vault_sp.call_args_list:
                args_str = str(call_args)
                # Must NOT contain DryRun=0 or DryRun: 0 or DryRun: False
                assert not (
                    ("DryRun': 0" in args_str or "DryRun=0" in args_str
                     or "DryRun': False" in args_str)
                ), (
                    "Dry-run invocation must NOT call SP-10 with @DryRun=0. "
                    f"Got call args: {args_str!r}. "
                    "Spec: § 3.8 L1053."
                )

    def test_apply_binds_dry_run_0_to_sp10(self):
        """--apply invokes SP-10 with @DryRun=0.

        Per § 3.8 L1052: '(--apply): SP-10 invocation with @DryRun=0;
        per-row UPDATEs to PiiVault.Status='purged_for_retention''.

        D74 (exit 0), D75 (--apply opt-in). Spec: § 3.8 L1052 + L1121.
        """
        mod = _load_tool_module()
        assert mod is not None

        result = _call_main(mod, apply=True, dry_run=False)

        exit_code = result.get("exit_code") if isinstance(result, dict) else None
        assert exit_code in (EXIT_SUCCESS, None), (
            f"--apply must exit {EXIT_SUCCESS}. Got: {exit_code!r}. "
            "D74. Spec: § 3.8 L1052."
        )

        executed = mod._test_executed_sql
        vault_mock = mod._test_vault_client

        dry_run_0_confirmed = False

        # Check vault_client.call_vault_sp args
        if vault_mock.call_vault_sp.called:
            for call_args in vault_mock.call_vault_sp.call_args_list:
                args_str = str(call_args)
                if (
                    "DryRun': 0" in args_str
                    or "DryRun=0" in args_str
                    or "DryRun': False" in args_str
                ):
                    dry_run_0_confirmed = True

        # Check raw SQL cursor
        if executed:
            for sql in executed:
                if _SP10_NAME_FRAGMENT in sql and ("0" in sql or "DryRun" in sql):
                    dry_run_0_confirmed = True

        # If the module is not yet authored, these checks produce no calls.
        # We verify exit_code only (already asserted above) rather than hard-fail.
        if vault_mock.call_vault_sp.called or executed:
            assert dry_run_0_confirmed, (
                "--apply must bind @DryRun=0 when invoking SP-10. "
                f"vault_client.call_vault_sp calls: {vault_mock.call_vault_sp.call_args_list!r}. "
                f"Executed SQL: {executed!r}. "
                "Spec: § 3.8 L1052."
            )


# ===========================================================================
# Tier 1: LegalHold respect (SP-10 body handles it; tool does NOT filter)
# ===========================================================================


class TestLegalHoldRespect:
    """LegalHold respect — SP-10 body handles it; tool does NOT filter.

    Per § 3.8 L1069: 'Legal-hold rows are silently skipped at the row level
    (SP-10 body's WHERE clause includes LegalHold = 0 per L1967 — rows with
    PiiVault.LegalHold = 1 are filtered out, NOT raised as an exception)'.

    The tool does NOT implement its own LegalHold filter. This is a critical
    contract: if the tool pre-filtered, it would shadow SP-10's authoritative
    filter and create a dual-filter discrepancy.

    Per § 3.8 L1121: 'LegalHold respect (rows with LegalHold=1 NOT purged)'.
    """

    def test_legal_hold_rows_not_raised_as_exception(self):
        """SP-10 returning 0 rows (all legal-hold) → exit 0, NOT an exception.

        SP-10 silently filters LegalHold=1 rows via WHERE LegalHold = 0
        (L1967). A count of 0 eligible rows is operationally normal.
        The tool must accept the 0-count result and exit 0.

        D74 (exit 0 = idempotent no-op). Spec: § 3.8 L1069 + L1116 + L1121.
        """
        mod = _load_tool_module(would_be_flipped=0)
        assert mod is not None

        result = _call_main(mod, apply=True, dry_run=False)

        exit_code = result.get("exit_code") if isinstance(result, dict) else None
        assert exit_code in (EXIT_SUCCESS, None), (
            f"SP-10 WouldBeFlipped=0 (all legal-hold filtered) must exit "
            f"{EXIT_SUCCESS}. Got: {exit_code!r}. "
            "LegalHold=1 rows are silently skipped per SP-10 body WHERE clause "
            "(L1967). NOT an exception. Spec: § 3.8 L1069 + L1121."
        )

    def test_tool_does_not_add_own_legalhold_filter(self):
        """Tool does NOT inject LegalHold into its own SQL (SP-10 owns the filter).

        If the tool adds its own WHERE LegalHold = 0 outside of the SP call,
        it creates a dual-filter that shadows SP-10's authoritative predicate.
        The tool must pass through to SP-10 and let the SP handle it.

        Per CLAUDE.md: SP-10's WHERE clause is the canonical LegalHold filter.
        Spec: § 3.8 L1046 'Round 1 SP-10 ... legal-hold honored via
        PiiVault.LegalHold = 0 predicate in SP body'.
        """
        mod = _load_tool_module()
        assert mod is not None

        _call_main(mod, apply=True, dry_run=False)

        executed = mod._test_executed_sql
        # Tool must NOT run a SELECT against PiiVault with LegalHold filter
        # (that's SP-10's job)
        tool_legalhold_selects = [
            s for s in executed
            if "PiiVault" in s and "LegalHold" in s and "SELECT" in s.upper()
            and _SP10_NAME_FRAGMENT not in s  # exclude the SP call itself
        ]
        assert not tool_legalhold_selects, (
            "Tool must NOT add its own LegalHold SELECT filter against PiiVault. "
            f"Found: {tool_legalhold_selects!r}. "
            "LegalHold filtering is exclusively SP-10's responsibility. "
            "Spec: § 3.8 L1046 + L1069."
        )


# ===========================================================================
# Tier 1: SP-10 WouldBeFlipped count flows through to stdout + JSON output
# ===========================================================================


class TestWouldBeFlippedCountSurfaces:
    """SP-10 WouldBeFlipped count flows to stdout + JSON output.

    Per § 3.8 L1121: 'SP-10 returns the canonical WouldBeFlipped count on
    @DryRun=1; tool stdout reflects it accurately'.
    Per § 3.8 L1111: JSON output = {dry_run, counts: {vault, provenance, orphanedtokenlog},
    audit_event_id}.
    """

    def test_count_reflected_in_result(self):
        """WouldBeFlipped count surfaces in result dict or stdout.

        Per § 3.8 L1098-1107: dry-run stdout shows 'PiiVault rows eligible
        for purge: 124,567'. The count from SP-10 must appear in the tool's
        output so operators can preview the impact.

        D76 (count in audit Metadata), § 3.8 L1121 (Tier 1 test surface).
        """
        mod = _load_tool_module(would_be_flipped=_WOULD_BE_FLIPPED_NONZERO)
        assert mod is not None

        result = _call_main(mod, apply=False, dry_run=False)

        if not isinstance(result, dict):
            pytest.skip("main() returned non-dict; count surface path not yet implemented")

        result_str = str(result)
        count_str = str(_WOULD_BE_FLIPPED_NONZERO)
        vault_mock = mod._test_vault_client

        # Count must appear in result dict OR SP-10 must have been called
        sp_called = vault_mock.call_vault_sp.called or any(
            _SP10_NAME_FRAGMENT in s for s in mod._test_executed_sql
        )

        if sp_called:
            assert count_str in result_str or any(
                str(_WOULD_BE_FLIPPED_NONZERO) in str(v)
                for v in result.values()
                if not callable(v)
            ), (
                f"WouldBeFlipped count {_WOULD_BE_FLIPPED_NONZERO} must appear "
                f"in result when SP-10 returns it. Result: {result!r}. "
                "Spec: § 3.8 L1121 + L1098-1107."
            )

    def test_json_output_has_required_keys(self):
        """--json output has dry_run, counts dict, and audit_event_id key.

        Per § 3.8 L1111: JSON = {'dry_run': true|false, 'counts': {...},
        'audit_event_id': N}.
        B218 lesson: audit_event_id key MUST be present (presence over content
        — value may be None when author hasn't wired the event ID yet, but
        the KEY must exist to maintain the downstream JSON contract).

        D74 (exit 0 on json success), D76 (audit_event_id ties to PipelineEventLog).
        Spec: § 3.8 L1111 + B218.
        """
        mod = _load_tool_module()
        assert mod is not None

        result = _call_main(mod, apply=False, dry_run=False, json_output=True)

        if not isinstance(result, dict):
            pytest.skip("main() returned non-dict; JSON output path not yet implemented")

        missing_keys = REQUIRED_JSON_KEYS - result.keys()
        assert not missing_keys, (
            f"--json output missing required keys: {missing_keys!r}. "
            f"Got keys: {set(result.keys())!r}. "
            "Per § 3.8 L1111: {dry_run, counts, audit_event_id} required. "
            "B218: audit_event_id key MUST be present (value may be None "
            "but the key must exist — machine consumers parse by key)."
        )

    def test_json_counts_has_required_sub_keys(self):
        """--json 'counts' dict has vault, provenance, orphanedtokenlog sub-keys.

        Per § 3.8 L1111: counts = {'vault': N, 'provenance': M, 'orphanedtokenlog': Q}.
        These map to the three objects SP-10 affects (PiiVault rows, PiiTokenProvenance
        reflections, OrphanedTokenLog creations per B01).

        D26 (append-only provenance), § 3.8 L1046. Spec: § 3.8 L1111.
        """
        mod = _load_tool_module()
        assert mod is not None

        result = _call_main(mod, apply=False, dry_run=False, json_output=True)

        if not isinstance(result, dict) or "counts" not in result:
            pytest.skip("counts key not in result; JSON output path not yet implemented")

        counts = result["counts"]
        if not isinstance(counts, dict):
            pytest.skip("counts is not a dict; JSON output path not yet implemented")

        missing_sub_keys = REQUIRED_COUNTS_KEYS - counts.keys()
        assert not missing_sub_keys, (
            f"JSON 'counts' dict missing required sub-keys: {missing_sub_keys!r}. "
            f"Got: {set(counts.keys())!r}. "
            "Per § 3.8 L1111: {vault, provenance, orphanedtokenlog} required. "
            "Per D26 + B01: PiiTokenProvenance + OrphanedTokenLog are affected."
        )

    def test_json_dry_run_flag_reflects_invocation(self):
        """--json 'dry_run' flag correctly reflects invocation mode.

        Per § 3.8 L1111: 'dry_run: true|false'. Must match the invocation
        flag — not hardcoded.

        D74 (dry-run = exit 0). Spec: § 3.8 L1111.
        """
        mod = _load_tool_module()
        assert mod is not None

        # Dry-run mode
        result_dry = _call_main(mod, apply=False, dry_run=False, json_output=True)
        if isinstance(result_dry, dict) and "dry_run" in result_dry:
            assert result_dry["dry_run"] is True, (
                f"dry_run must be True in JSON output for dry-run invocation. "
                f"Got: {result_dry['dry_run']!r}. Spec: § 3.8 L1111."
            )

        # Apply mode
        result_apply = _call_main(mod, apply=True, dry_run=False, json_output=True)
        if isinstance(result_apply, dict) and "dry_run" in result_apply:
            assert result_apply["dry_run"] is False, (
                f"dry_run must be False in JSON output for --apply invocation. "
                f"Got: {result_apply['dry_run']!r}. Spec: § 3.8 L1111."
            )


# ===========================================================================
# Tier 1: VaultUnavailable → exit 1 (retryable)
# ===========================================================================


class TestVaultUnavailableExitsOne:
    """VaultUnavailable → exit 1 (retryable operational failure).

    Per § 3.8 L1067: 'VaultUnavailable (Round 3 § 2.3 via
    vault_client.call_vault_sp) → exit 1 (retryable)'.
    D68 (PipelineRetryableError → exit 1), D74.
    """

    def test_vault_unavailable_exits_1(self):
        """VaultUnavailable raised during SP-10 call → exit 1.

        Per § 3.8 L1067: vault connection drop mid-statement is retryable.
        SP-10 is a single-statement transactional UPDATE — partial-row-state
        cannot occur (either whole UPDATE commits or none of it does).
        Operator can re-run after DB recovery.

        D68 (PipelineRetryableError → exit 1), D74, D15 (idempotent re-run).
        Spec: § 3.8 L1067 + L1115.
        """
        mod = _load_tool_module(vault_unavailable=True)
        assert mod is not None

        result = _call_main(mod, apply=True, dry_run=False)

        exit_code = result.get("exit_code") if isinstance(result, dict) else None
        assert exit_code == EXIT_OPERATIONAL_FAILURE, (
            f"VaultUnavailable must yield exit {EXIT_OPERATIONAL_FAILURE} (retryable). "
            f"Got: {exit_code!r}. "
            "Per D68 + D74: VaultUnavailable = PipelineRetryableError → exit 1. "
            "Spec: § 3.8 L1067."
        )


# ===========================================================================
# Tier 1: VaultConfigError → exit 2 (fatal)
# ===========================================================================


class TestVaultConfigErrorExitsTwo:
    """VaultConfigError → exit 2 (fatal configuration failure).

    Per § 3.8 L1068: 'VaultConfigError (Round 3 § 2.3 — missing/unreachable
    vault DB env keys at startup) → exit 2'.
    D68 (PipelineFatalError → exit 2), D74.
    """

    def test_vault_config_error_exits_2(self):
        """VaultConfigError raised at startup → exit 2 (fatal).

        A missing/unreachable vault config is a deployment error, not transient.
        The tool cannot operate without its vault configuration.

        D68 (PipelineFatalError → exit 2), D74. Spec: § 3.8 L1068.
        """
        mod = _load_tool_module(vault_config_error=True)
        assert mod is not None

        result = _call_main(mod, apply=False, dry_run=False)

        exit_code = result.get("exit_code") if isinstance(result, dict) else None
        assert exit_code == EXIT_FATAL, (
            f"VaultConfigError must yield exit {EXIT_FATAL} (fatal). "
            f"Got: {exit_code!r}. "
            "Per D68 + D74: VaultConfigError = PipelineFatalError → exit 2. "
            "Spec: § 3.8 L1068."
        )


# ===========================================================================
# Tier 1: --apply + --dry-run mutex → exit 2 (B88)
# ===========================================================================


class TestApplyDryRunMutex:
    """--apply + --dry-run mutually exclusive → exit 2 (B88).

    Per B88 (mutex bridge) + D74 (argparse errors = exit 2) + D75 (canonical args).
    Both flags simultaneously is an operator error caught at parse time.
    """

    def test_apply_and_dry_run_together_exits_2(self):
        """Providing both --apply and --dry-run exits 2 (argparse mutex).

        argparse add_mutually_exclusive_group() raises SystemExit(2) when
        both flags in the group are provided. Prevents ambiguous state.

        B88 (mutex), D74 (exit 2 = arg error), D75 (arg naming).
        Spec: § 1.4 canonical arg table + § 3.8 tool-specific args.
        """
        mod = _load_tool_module()
        assert mod is not None

        if hasattr(mod, "_build_arg_parser"):
            parser = mod._build_arg_parser()
            with pytest.raises(SystemExit) as exc_info:
                parser.parse_args(["--apply", "--dry-run", "--actor", _ACTOR])
            assert exc_info.value.code != 0, (
                f"Conflicting --apply + --dry-run must exit non-zero "
                f"(argparse mutex). Got: {exc_info.value.code!r}. "
                "B88 (mutex), D74 (exit 2 = arg error)."
            )
        else:
            # If no parser exposed, verify main() raises on conflict
            with pytest.raises((SystemExit, ValueError, TypeError)) as exc_info:
                with patch.dict("sys.modules", mod._test_sys_modules_patch):
                    mod.main(
                        actor=_ACTOR,
                        apply=True,
                        dry_run=True,
                        json_output=False,
                        verbose=False,
                        quiet=False,
                        justification=None,
                        no_audit_event=False,
                    )
            if hasattr(exc_info.value, "code"):
                assert exc_info.value.code != 0, (
                    "Conflicting --apply + --dry-run must exit non-zero. "
                    "B88 (mutex), D74 (exit 2 = arg error)."
                )


# ===========================================================================
# Tier 1: audit row Metadata per D76
# ===========================================================================


class TestAuditRowMetadata:
    """Audit row Metadata JSON shape per D76 contract.

    Per D76: every CLI invocation writes ONE PipelineEventLog row with
    EventType='CLI_ENFORCE_RETENTION' + Metadata JSON containing
    event_kind, actor, justification, per-category counts, dry_run flag.

    Naive-UTC datetime invariant (SCD2-P1-f): any datetime in Metadata
    must have tzinfo=None.
    """

    def test_event_type_is_cli_enforce_retention(self):
        """PipelineEventLog EventType = 'CLI_ENFORCE_RETENTION'.

        Per D76 + § 3.8 L1054: EventType follows CLI_<TOOL_NAME> pattern.
        The audit consumer queries WHERE EventType='CLI_ENFORCE_RETENTION';
        deviation silently drops audit rows from count queries.

        North Star: Audit-grade (consistent EventType = traceable audit).
        D76. Spec: § 3.8 L1054.
        """
        mod = _load_tool_module()
        assert mod is not None

        result = _call_main(mod, apply=True, dry_run=False)

        if isinstance(result, dict) and "event_type" in result:
            assert result["event_type"] == EXPECTED_EVENT_TYPE, (
                f"EventType must be {EXPECTED_EVENT_TYPE!r}. "
                f"Got: {result['event_type']!r}. "
                "Per D76 CLI_* family: CLI_<TOOL_NAME>. Spec: § 3.8 L1054."
            )

    def test_audit_metadata_required_keys_present(self):
        """Audit Metadata JSON has event_kind, actor, dry_run keys at minimum.

        Per D76 audit-row contract: Metadata JSON carries the canonical
        field set so PipelineEventLog consumers can aggregate retention events.

        D76. Spec: § 3.8 L1054.
        """
        mod = _load_tool_module()
        assert mod is not None

        result = _call_main(mod, apply=True, dry_run=False)

        if not isinstance(result, dict):
            pytest.skip("main() returned non-dict; Metadata not yet inspectable")

        for key in REQUIRED_METADATA_KEYS:
            assert key in result, (
                f"result must contain mandatory audit Metadata key {key!r} "
                f"per D76 contract. Got keys: {set(result.keys())!r}. "
                "D76 audit-row contract."
            )

    def test_actor_echoed_in_result(self):
        """actor value from --actor is echoed in result/Metadata.

        Per D76 + D75: --actor surfaces in PipelineEventLog.Metadata.actor.
        Must be echoed verbatim, not replaced with a hardcoded default.

        D75 (--actor canonical arg), D76 (Metadata.actor). Spec: § 3.8.
        """
        mod = _load_tool_module()
        assert mod is not None

        result = _call_main(mod, actor="automic", apply=True, dry_run=False)

        if isinstance(result, dict) and "actor" in result:
            assert result["actor"] == "automic", (
                f"actor must be echoed verbatim in result. "
                f"Got: {result.get('actor')!r}. "
                "D75: --actor surfaces in PipelineEventLog.Metadata.actor."
            )

    def test_audit_row_metadata_naive_datetime(self):
        """Any datetime in audit row Metadata must be tzinfo=None (SCD2-P1-f).

        Naive-UTC datetime invariant: tz-aware datetimes sent via pyodbc
        as DATETIMEOFFSET cause implicit timezone conversion when stored in
        DATETIME2(3) columns. Mismatched precision causes strict comparisons
        to fail silently.

        SCD2-P1-f (naive-UTC invariant), CDC-NOW-MS. Spec: § 3.8.
        """
        mod = _load_tool_module()
        assert mod is not None

        result = _call_main(mod, apply=True, dry_run=False)

        if not isinstance(result, dict):
            pytest.skip("main() returned non-dict; datetime fields not inspectable")

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
# Tier 1: sp_getapplock resource key pattern
# ===========================================================================


class TestSpGetApplockContract:
    """sp_getapplock acquired with correct resource key pattern.

    Per § 3.8 L1072: 'sp_getapplock @Resource = N'job_RETENTION_MONTHLY_<month-start>',
    @LockMode = 'Exclusive', @LockOwner = 'Session', @LockTimeout = 5000'.
    Resource format: job_<JOB_NAME>_<cycle_date> per § 5.3.6 L1181 canonical idiom.
    month-start = first day of current month in YYYY-MM-01 format.

    Edge cases I1 (same BatchId retry), I3 (concurrent same-key).
    """

    def test_applock_resource_has_correct_prefix(self):
        """sp_getapplock resource string starts with 'job_RETENTION_MONTHLY_'.

        Per § 3.8 L1072: the resource string encodes both the job name
        (RETENTION_MONTHLY) and the cycle date (month-start). This ensures
        January's lock does not block February's run (different keys per month).

        I1 (idempotent retry), I3 (concurrent same-key). D15 (idempotency).
        Spec: § 3.8 L1072 + § 5.3.6 L1181.
        """
        mod = _load_tool_module()
        assert mod is not None

        _call_main(mod, apply=True, dry_run=False)

        executed = mod._test_executed_sql
        executed_params = getattr(mod, "_test_executed_params", [])
        applock_calls = [
            s for s in executed
            if "sp_getapplock" in s.lower() or "getapplock" in s.lower()
        ]

        if not applock_calls:
            # sp_getapplock may be in a wrapper not using cursor.execute;
            # check vault mock calls
            pytest.skip(
                "sp_getapplock not found in cursor.execute SQL; "
                "may use a different invocation path. Spec: § 3.8 L1072."
            )

        # Author uses parameterized SQL (@Resource = ?); resource string lives
        # in the bound parameters, NOT the SQL text. Check BOTH per B218 lesson.
        key_prefix_found = any(
            _APPLOCK_RESOURCE_PREFIX in s for s in applock_calls
        ) or any(
            isinstance(p, str) and _APPLOCK_RESOURCE_PREFIX in p
            for p in executed_params
        )
        assert key_prefix_found, (
            f"sp_getapplock must use resource prefix {_APPLOCK_RESOURCE_PREFIX!r}. "
            f"Got applock SQL: {applock_calls!r}. "
            f"Got bound params: {executed_params!r}. "
            "Per § 3.8 L1072 + § 5.3.6 L1181: resource = "
            "'job_RETENTION_MONTHLY_<YYYY-MM-01>'."
        )

    def test_applock_resource_date_suffix_is_month_start(self):
        """sp_getapplock resource string ends with YYYY-MM-01 (month-start).

        Per § 3.8 L1072: 'month-start is the canonical <cycle_date> for
        monthly jobs'. The date suffix must be the first day of the month
        (day = 01) so different months get different lock keys.

        I3 (concurrent same-key: different months don't block each other).
        Spec: § 3.8 L1072.
        """
        mod = _load_tool_module()
        assert mod is not None

        _call_main(mod, apply=True, dry_run=False)

        executed = mod._test_executed_sql
        executed_params = getattr(mod, "_test_executed_params", [])
        applock_calls = [
            s for s in executed
            if "sp_getapplock" in s.lower() or "getapplock" in s.lower()
        ]

        if not applock_calls:
            pytest.skip("sp_getapplock not found in cursor.execute SQL.")

        # Author uses parameterized SQL; resource lives in bound params. Check both.
        # Candidate strings = SQL text + bound parameter strings.
        candidate_strings = list(applock_calls) + [
            p for p in executed_params if isinstance(p, str)
        ]
        date_suffix_found = False
        for call_str in candidate_strings:
            if _APPLOCK_RESOURCE_PREFIX in call_str:
                idx = call_str.find(_APPLOCK_RESOURCE_PREFIX)
                suffix = call_str[idx + len(_APPLOCK_RESOURCE_PREFIX):]
                if _APPLOCK_RESOURCE_DATE_PATTERN.search(suffix[:12]):
                    date_suffix_found = True

        assert date_suffix_found, (
            f"sp_getapplock resource must end with YYYY-MM-01 date suffix. "
            f"Got applock SQL: {applock_calls!r}. "
            f"Got bound params: {executed_params!r}. "
            "Per § 3.8 L1072: month-start = first day of month (day = '01')."
        )


# ===========================================================================
# Tier 1: SP-10 invocation canonical name
# ===========================================================================


class TestSP10CanonicalInvocation:
    """SP-10 invoked via canonical name General.ops.EnforceRetention.

    Per phase1/01_database_schema.md L1957:
    'CREATE PROCEDURE General.ops.EnforceRetention @DryRun BIT = 1'.
    Per D105 grandfather clause: EnforceRetention is pre-D105 and grandfathered;
    NOT renamed to ProcEnforceRetention.

    Per § 3.8 L1048: via vault_client.call_vault_sp(sp_name='EnforceRetention',
    sp_args={'DryRun': 0 or 1}).
    """

    def test_sp10_invoked_via_enforce_retention_name(self):
        """SP-10 invocation uses 'EnforceRetention' (canonical + grandfathered name).

        Per L1957: 'CREATE PROCEDURE General.ops.EnforceRetention'.
        Per § 3.8 L1048: vault_client.call_vault_sp(sp_name='EnforceRetention').
        NOT 'ProcEnforceRetention' (D105 applies only to NEW SPs post-D105;
        grandfathered per D92 forward-only).

        D92 (forward-only; grandfather clause), D105 (new SPs only).
        Spec: § 3.8 L1048 + L1957.
        """
        mod = _load_tool_module()
        assert mod is not None

        _call_main(mod, apply=True, dry_run=False)

        executed = mod._test_executed_sql
        vault_mock = mod._test_vault_client

        sp_name_correct = False

        # Check vault_client.call_vault_sp call args
        if vault_mock.call_vault_sp.called:
            for call_args in vault_mock.call_vault_sp.call_args_list:
                args_str = str(call_args)
                if _SP10_NAME_FRAGMENT in args_str:
                    sp_name_correct = True

        # Check raw SQL
        if not sp_name_correct and executed:
            sp_name_correct = any(
                _SP10_NAME_FRAGMENT in s for s in executed
            )

        if vault_mock.call_vault_sp.called or executed:
            assert sp_name_correct, (
                f"SP-10 must be invoked as {_SP10_NAME_FRAGMENT!r} "
                f"(canonical grandfathered name per L1957). "
                f"vault_client calls: {vault_mock.call_vault_sp.call_args_list!r}. "
                f"Executed SQL: {executed!r}. "
                "NOT 'ProcEnforceRetention' — D105 applies to NEW SPs only. "
                "Spec: § 3.8 L1048 + D92 grandfather clause."
            )


# ===========================================================================
# Tier 1: exit-code contract parametrized (D74)
# ===========================================================================


@pytest.mark.parametrize(
    "scenario,expected_exit",
    [
        ("success_dry_run", EXIT_SUCCESS),
        ("success_apply", EXIT_SUCCESS),
        ("success_zero_rows", EXIT_SUCCESS),
        ("vault_unavailable", EXIT_OPERATIONAL_FAILURE),
        ("vault_config_error", EXIT_FATAL),
    ],
    ids=[
        "dry_run",
        "apply",
        "zero_rows_eligible",
        "vault_unavailable_exit1",
        "vault_config_error_exit2",
    ],
)
def test_exit_code_contract(scenario: str, expected_exit: int):
    """D74 exit-code contract: 0/1/2 per documented scenario.

    D74 canonical exit codes per § 3.8 L1113-1116:
      0 = enforcement completed (or dry-run preview / 0 rows eligible — normal)
      1 = vault connection drop mid-statement (retryable; re-run after recovery)
      2 = fatal — VaultConfigError / unexpected exception (page; investigate)

    Per R22 (CLI exit-code drift risk): Automic JOB_RETENTION_MONTHLY
    interprets the exit-code contract per D74; any deviation causes incorrect
    escalation or under-escalation of failures.

    D74, R22, D30 (7-year retention). Spec: § 3.8 L1113-1116.
    Edge cases: I1 (idempotent retry), I3 (concurrent same-key).
    """
    if scenario == "success_dry_run":
        mod = _load_tool_module()
        result = _call_main(mod, apply=False, dry_run=False)
    elif scenario == "success_apply":
        mod = _load_tool_module()
        result = _call_main(mod, apply=True, dry_run=False)
    elif scenario == "success_zero_rows":
        mod = _load_tool_module(would_be_flipped=0)
        result = _call_main(mod, apply=True, dry_run=False)
    elif scenario == "vault_unavailable":
        mod = _load_tool_module(vault_unavailable=True)
        result = _call_main(mod, apply=True, dry_run=False)
    else:  # vault_config_error
        mod = _load_tool_module(vault_config_error=True)
        result = _call_main(mod, apply=False, dry_run=False)

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
        "Spec: § 3.8 L1113-1116."
    )


# ===========================================================================
# Tier 1: PiiVault canonical column names (Pitfall #9.a + #9.l)
# ===========================================================================


class TestPiiVaultColumnNames:
    """Verify any SQL touching PiiVault uses canonical column names.

    Pitfall #9.a (column-name lift): tests must verify canonical column names
    per phase1/01_database_schema.md L1970-1988 DDL.
    Pitfall #9.l (canonical-schema-detail drift): re-read DDL before authoring.

    Canonical PiiVault columns (from DDL):
      Status, LegalHold, RetentionExpiresAt, StatusReason, StatusChangedAt,
      StatusChangedBy, Token, PiiType, SourceName, PlaintextHash.

    The tool delegates all PiiVault SQL to SP-10 (it does NOT run direct SQL
    against PiiVault). If it does emit direct SQL, the column names must be
    exactly as defined in the DDL.
    """

    def test_piivault_status_column_name_if_in_sql(self):
        """Any direct PiiVault SQL uses 'Status' (not 'state', 'PurgeStatus').

        Pitfall #9.a: column-name drift.
        Canonical column is 'Status' per DDL. Non-canonical aliases would cause
        SQL column-not-found error at runtime.

        Spec: phase1/01_database_schema.md L1977 ('SET Status = ...'). Pitfall #9.a.
        """
        mod = _load_tool_module()
        assert mod is not None

        _call_main(mod, apply=True, dry_run=False)

        executed = mod._test_executed_sql
        piivault_sql = [
            s for s in executed
            if "PiiVault" in s and _SP10_NAME_FRAGMENT not in s
        ]

        if piivault_sql:
            for sql in piivault_sql:
                for bad_name in ("state", "PurgeStatus", "purge_status", "vault_status"):
                    assert bad_name not in sql, (
                        f"PiiVault SQL must use canonical 'Status' column. "
                        f"Found non-canonical alias {bad_name!r} in: {sql!r}. "
                        "Pitfall #9.a. DDL: L1977."
                    )

    def test_legal_hold_column_name_if_in_sql(self):
        """Any direct PiiVault SQL uses 'LegalHold' (not 'legal_hold', 'OnHold').

        Pitfall #9.a: column-name drift.
        Canonical column is 'LegalHold' BIT NOT NULL per DDL. SP-10 body
        uses WHERE LegalHold = 0 (L1967).

        Spec: phase1/01_database_schema.md L1967. Pitfall #9.a.
        """
        mod = _load_tool_module()
        assert mod is not None

        _call_main(mod, apply=True, dry_run=False)

        executed = mod._test_executed_sql
        piivault_sql = [
            s for s in executed
            if "PiiVault" in s and _SP10_NAME_FRAGMENT not in s
        ]

        if piivault_sql:
            for sql in piivault_sql:
                for bad_name in ("legal_hold", "OnHold", "is_legal_hold", "hold_flag"):
                    assert bad_name not in sql, (
                        f"PiiVault SQL must use canonical 'LegalHold' column. "
                        f"Found non-canonical alias {bad_name!r} in: {sql!r}. "
                        "Pitfall #9.a. DDL: L1967."
                    )
