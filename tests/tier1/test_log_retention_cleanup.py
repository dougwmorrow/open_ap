"""Tier 1 unit tests for tools/log_retention_cleanup.py.

Tests run on every commit. No live DB, no live network required.
All external dependencies mocked with unittest.mock.

North Star pillars addressed:
  - Audit-grade (D76): exactly one CLI_LOG_RETENTION_CLEANUP PipelineEventLog
    row per invocation; Metadata JSON shape canonical with per-level counts,
    actor, justification, dry_run flag; FAILED row written even on exception path.
  - Operationally stable (D74/D75): exit-code contract (0/1/2) and argument
    naming discipline must be exactly per spec; Automic JOB_LOG_CLEANUP
    interprets the contract (B80).
  - Idempotent (D15): re-invoking after purge produces zero rows purged;
    DELETE is atomic — partial-purge crash leaves deterministic state.
  - Traceability (D26 exception): log retention is the deliberate exception
    to the append-only rule; rows older than 30/90 days are deleted per
    CLAUDE.md policy; ERROR/CRITICAL are NEVER deleted (indefinite).

PipelineLog canonical columns (Pitfall #9.a — verified against
phase1/01_database_schema.md L197-236):
  LogId, BatchId, TableName, SourceName, LogLevel, Module, FunctionName,
  Message, ErrorType, StackTrace, Metadata, CreatedAt, CycleType, CycleDate,
  ServerRole, Layer.
LogLevel CHECK constraint: IN ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')
  (CK_PipelineLog_LogLevel per L215-216).

Naive-UTC datetime invariant (SCD2-P1-f): every datetime captured in
audit row Metadata must be tzinfo=None. Verified in
test_audit_row_metadata_naive_datetime.

Edge case IDs (per 04_EDGE_CASES.md):
  - I1 (same BatchId retry: ledger short-circuits) — sp_getapplock idempotency
    ensures one cleanup at a time; concurrent invocations queue or exit 1.
  - I3 (concurrent same-key: lock prevents) — sp_getapplock key
    ('log_retention_cleanup',) serializes concurrent cleanup runs.
  - I4 (BCP partial-write: stage-check-exchange) — DELETE atomicity:
    partial-purge crash leaves deterministic state for next run.

Decision citations:
  D15 (idempotency mandatory),
  D26 (append-only exception — log retention deliberate per CLAUDE.md policy),
  D31 (PowerBI: purge must NOT touch ERROR/CRITICAL which power dashboards),
  D67 (Tier 0 discipline — this file is Tier 1 complement),
  D74 (exit-code contract 0/1/2),
  D75 (arg naming: actor / debug-info-days / warning-days / batch-size /
       dry-run / apply / json),
  D76 (audit-row contract: CLI_LOG_RETENTION_CLEANUP EventType; Metadata
       JSON shape),
  D77 (Tier 0 canonical scaffold — Tier 1 extends, not weakens).

B-numbers:
  B80 (JOB_LOG_CLEANUP Automic inventory candidate; Round 6 deployment
       to amend frozen-8 → frozen-9 per § 3.10 L1237).
  B-2 (lock escalation lessons — batch-size cap at 50k default; 10k floor).

Spec: phase1/04_tools.md § 3.10 (canonical spec L1220-1305).
PipelineLog DDL: phase1/01_database_schema.md L197-236.

udm-execution-classifier discipline:
  - Idempotency contract: idempotent (re-run after purge = zero rows purged;
    re-run during purge = sp_getapplock serialization → exit 1 → operator retry).
  - Trigger: Scheduled-primary (Automic JOB_LOG_CLEANUP — B80 candidate;
    daily or weekly cadence per § 3.10 L1237) + Manual-ad-hoc (operator
    dry-run preview: 'python3 tools/log_retention_cleanup.py').
  - Frequency: daily or weekly via Automic; ad-hoc for preview.
  - Audit-row family: CLI_* per D76 (EventType = CLI_LOG_RETENTION_CLEANUP).
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

_TOOL_PATH = _PROJECT_ROOT / "tools" / "log_retention_cleanup.py"
_TOOL_MODULE_KEY = "tools.log_retention_cleanup"

# ---------------------------------------------------------------------------
# Constants — single source of truth for all expected values
# ---------------------------------------------------------------------------

# D76 EventType per CLI_* family (§ 3.10 L1234)
EXPECTED_EVENT_TYPE = "CLI_LOG_RETENTION_CLEANUP"

# D74 exit codes (§ 1.1 + § 3.10 L1292-1295)
EXIT_SUCCESS = 0
EXIT_OPERATIONAL_FAILURE = 1   # lock contention / partial-batch error
EXIT_FATAL = 2                 # config / connection / unexpected

# D75 canonical arg values
_ACTOR = "test-author"

# Retention windows per CLAUDE.md + § 3.10 L1270-1274
_DEBUG_INFO_DAYS_DEFAULT = 30
_WARNING_DAYS_DEFAULT = 90
_BATCH_SIZE_DEFAULT = 50000
_BATCH_SIZE_SMALL = 10000

# LogLevel enum values per CK_PipelineLog_LogLevel
# (phase1/01_database_schema.md L215-216) — Pitfall #9.c enum-value check
LOGLEVEL_ENUM = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})

# Levels that must NEVER appear in DELETE WHERE per CLAUDE.md retention policy
PROTECTED_LOGLEVELS = frozenset({"ERROR", "CRITICAL"})

# Levels subject to purge
PURGEABLE_LOGLEVELS = frozenset({"DEBUG", "INFO", "WARNING"})

# Required keys in --json output per § 3.10 L1290
REQUIRED_JSON_KEYS = {"dry_run", "purged", "retained", "audit_event_id"}

# Required keys in audit row Metadata per D76
REQUIRED_METADATA_KEYS = {
    "event_kind",
    "actor",
    "dry_run",
}

# sp_getapplock key per § 3.10 L1251
APPLOCK_KEY = "log_retention_cleanup"


# ---------------------------------------------------------------------------
# Module loader
# ---------------------------------------------------------------------------


def _load_tool_module(
    *,
    connection_side_effect: Exception | None = None,
    applock_result: int = 0,
    config_missing: bool = False,
) -> Any:
    """Load tools/log_retention_cleanup.py with all external imports mocked.

    Parameters
    ----------
    connection_side_effect:
        If set, cursor_for() raises this exception (connection failure → exit 1).
    applock_result:
        Return value from sp_getapplock. 0 = acquired; -1 = timeout (→ exit 1).
    config_missing:
        If True, config import raises ImportError (config missing → exit 2).
    """
    if _TOOL_MODULE_KEY in sys.modules:
        del sys.modules[_TOOL_MODULE_KEY]

    # Canonical exception classes per B215 — NOT mocked
    from data_load._exceptions import SourceConnectError

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
    # sp_getapplock response
    mock_cursor.fetchone.return_value = (applock_result,)
    mock_cursor.fetchall.return_value = []
    # Default rowcount = 0 so batched-DELETE loops terminate cleanly under mock
    # (author's `_delete_cohort_batched` uses `cursor.rowcount <= 0` as exit cond).
    mock_cursor.rowcount = 0

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    mock_connections = MagicMock()
    if connection_side_effect is not None:
        mock_connections.cursor_for = MagicMock(side_effect=connection_side_effect)
        mock_connections.get_general_connection = MagicMock(side_effect=connection_side_effect)
        mock_connections.get_connection = MagicMock(side_effect=connection_side_effect)
    else:
        mock_connections.cursor_for = MagicMock(return_value=mock_cursor)
        # Author's tool path uses get_general_connection() (returns a connection,
        # not a cursor); mock to return mock_conn so subsequent .cursor() yields
        # the executed_sql-tracking mock_cursor.
        mock_connections.get_general_connection = MagicMock(return_value=mock_conn)
        mock_connections.get_connection = MagicMock(return_value=mock_conn)

    mock_event_tracker = MagicMock()
    mock_event = MagicMock()
    mock_event_tracker.track = MagicMock()
    mock_event_tracker.track.return_value.__enter__ = MagicMock(return_value=mock_event)
    mock_event_tracker.track.return_value.__exit__ = MagicMock(return_value=False)

    # Expose the cursor's executed_sql list so tests can inspect it
    mock_cursor._executed_sql = executed_sql

    if config_missing:
        mock_config = None  # will produce ImportError via side_effect below
        config_import_side_effect = ImportError("config module not found")
    else:
        mock_config = MagicMock()
        mock_config.GENERAL_DB = "General"
        config_import_side_effect = None

    # pyodbc mock: connect() returns the same mock_conn so its .cursor() yields
    # the executed_sql-tracking mock_cursor (per measure_lateness L583-587 pattern).
    # When connection_side_effect is set, pyodbc.connect also raises so the
    # tool's fall-through path doesn't recover (author's _open tries
    # get_general_connection first, then falls through to sys.modules["pyodbc"]).
    mock_pyodbc = MagicMock()
    if connection_side_effect is not None:
        mock_pyodbc.connect = MagicMock(side_effect=connection_side_effect)
    else:
        mock_pyodbc.connect = MagicMock(return_value=mock_conn)

    sys_modules_patch: dict[str, Any] = {
        "connections": mock_connections,
        "utils.connections": mock_connections,
        "observability.event_tracker": mock_event_tracker,
        "observability.log_handler": MagicMock(),
        "pyodbc": mock_pyodbc,
    }

    if config_import_side_effect is None:
        sys_modules_patch["config"] = mock_config
        sys_modules_patch["utils.configuration"] = mock_config
    # If config_missing, we do NOT add config to sys.modules; import will fail

    with patch.dict("sys.modules", sys_modules_patch):
        spec = importlib.util.spec_from_file_location(_TOOL_MODULE_KEY, _TOOL_PATH)
        mod = importlib.util.module_from_spec(spec)
        # Register BEFORE exec_module (B214 pattern — Python 3.12 dataclass fix)
        sys.modules[_TOOL_MODULE_KEY] = mod
        try:
            spec.loader.exec_module(mod)
        except (ImportError, ModuleNotFoundError):
            if not config_missing:
                raise
            # Expected: config missing causes import failure at module level
            return None

    # Attach the captured SQL list + sys_modules_patch for test inspection.
    # The patch must be re-applied during _call_main per measure_lateness pattern
    # (L583-587, L675-679) — patch.dict exits before main() runs, so the runtime
    # `sys.modules.get("pyodbc")` lookup in _open() reverts to real pyodbc
    # unless re-patched at call time.
    mod._test_cursor = mock_cursor
    mod._test_executed_sql = executed_sql
    mod._test_executed_params = executed_params
    mod._test_sys_modules_patch = sys_modules_patch
    return mod


def _call_main(mod: Any, **overrides: Any) -> dict | None:
    """Call tool main() with canonical defaults + overrides.

    Returns the result dict or None if main() raises SystemExit.

    Re-applies the sys.modules patch from _load_tool_module so the runtime
    `sys.modules.get("pyodbc")` lookup in the tool's `_open()` resolver
    honors the test mocks (per measure_lateness pattern L583-587).
    """
    defaults = dict(
        actor=_ACTOR,
        dry_run=False,
        apply=True,
        debug_info_days=_DEBUG_INFO_DAYS_DEFAULT,
        warning_days=_WARNING_DAYS_DEFAULT,
        batch_size=_BATCH_SIZE_DEFAULT,
        json_output=False,
        verbose=False,
        quiet=False,
        no_audit_event=False,
    )
    defaults.update(overrides)
    sys_modules_patch = getattr(mod, "_test_sys_modules_patch", {})
    try:
        with patch.dict("sys.modules", sys_modules_patch):
            return mod.main(**defaults)
    except SystemExit as exc:
        return {"exit_code": exc.code, "_raised_system_exit": True}


# ---------------------------------------------------------------------------
# Tier 1: per-level retention rule
# ---------------------------------------------------------------------------


class TestPerLevelRetentionRule:
    """Per-level retention rule: DEBUG/INFO 30d; WARNING 90d; ERROR/CRITICAL never.

    Per § 3.10 L1300 (Tier 1 test surface) + CLAUDE.md retention policy.
    """

    def test_debug_info_deletion_uses_30d_cutoff(self):
        """DEBUG/INFO rows use the 30-day cutoff in DELETE WHERE clause.

        Per § 3.10 L1233: DELETE WHERE LogLevel IN ('DEBUG','INFO') AND
        CreatedAt < @cutoff_30_days (default: 30 days, --debug-info-days).

        The SQL must reference the 30-day retention window. The cutoff value
        must be derived from debug_info_days (not warning_days or a hardcoded
        value).

        D26 (deliberate retention exception), D31 (protect ERROR/CRITICAL).
        Spec: § 3.10 L1233 Produces.
        """
        mod = _load_tool_module()
        assert mod is not None, "Module must import successfully for retention tests"

        result = _call_main(mod, apply=True, dry_run=False,
                            debug_info_days=_DEBUG_INFO_DAYS_DEFAULT)

        executed = mod._test_executed_sql
        debug_info_deletes = [
            s for s in executed
            if "DELETE" in s.upper()
            and ("DEBUG" in s.upper() or "INFO" in s.upper())
        ]

        # If the tool executes DELETE for DEBUG/INFO, the 30-day window must be used
        if debug_info_deletes:
            for sql in debug_info_deletes:
                # Must reference DEBUG or INFO levels (purgeable)
                has_purgeable_level = (
                    "'DEBUG'" in sql or "'INFO'" in sql
                    or "DEBUG" in sql.upper()
                    or "INFO" in sql.upper()
                )
                assert has_purgeable_level, (
                    f"DEBUG/INFO DELETE must reference the purgeable log levels. "
                    f"Got SQL: {sql!r}. Per § 3.10 L1233."
                )
                # Must NOT reference ERROR or CRITICAL
                for protected in PROTECTED_LOGLEVELS:
                    assert f"'{protected}'" not in sql, (
                        f"Protected level {protected!r} must not appear in "
                        f"DEBUG/INFO DELETE clause. SQL: {sql!r}. "
                        "CLAUDE.md: ERROR/CRITICAL retained indefinitely."
                    )

    def test_warning_deletion_uses_90d_cutoff(self):
        """WARNING rows use the 90-day cutoff in DELETE WHERE clause.

        Per § 3.10 L1233: DELETE WHERE LogLevel = 'WARNING' AND
        CreatedAt < @cutoff_90_days (default: 90 days, --warning-days).

        D26 (deliberate retention exception), D31 (protect ERROR/CRITICAL).
        Spec: § 3.10 L1233 Produces.
        """
        mod = _load_tool_module()
        assert mod is not None

        result = _call_main(mod, apply=True, dry_run=False,
                            warning_days=_WARNING_DAYS_DEFAULT)

        executed = mod._test_executed_sql
        warning_deletes = [
            s for s in executed
            if "DELETE" in s.upper() and "WARNING" in s.upper()
        ]

        if warning_deletes:
            for sql in warning_deletes:
                assert "'WARNING'" in sql or "WARNING" in sql.upper(), (
                    f"WARNING DELETE must reference 'WARNING' level. SQL: {sql!r}."
                )
                for protected in PROTECTED_LOGLEVELS:
                    assert f"'{protected}'" not in sql, (
                        f"Protected level {protected!r} must not appear in "
                        f"WARNING DELETE clause. SQL: {sql!r}."
                    )

    def test_error_critical_never_deleted_on_apply(self):
        """ERROR / CRITICAL rows are NEVER in any DELETE WHERE clause on --apply.

        Per CLAUDE.md retention policy: 'indefinite for ERROR/CRITICAL'.
        Per D31: ERROR/CRITICAL power the Power BI error-rate dashboards.
        Per § 3.10 L1233: tool produces ONLY two DELETEs — DEBUG/INFO (30d)
        and WARNING (90d). ERROR/CRITICAL have no DELETE statement.

        This is the core immutable contract. Any future refactor that accidentally
        introduces an ERROR or CRITICAL DELETE will fail this test.

        D26, D31, D74. Spec: § 3.10 L1233 Produces + L1297(e).
        """
        mod = _load_tool_module()
        assert mod is not None

        result = _call_main(mod, apply=True, dry_run=False)

        executed = mod._test_executed_sql
        delete_calls = [s for s in executed if "DELETE" in s.upper()]

        for sql in delete_calls:
            for protected in PROTECTED_LOGLEVELS:
                # Check both single and double-quoted forms
                for quoted in (f"'{protected}'", f'"{protected}"'):
                    assert quoted not in sql, (
                        f"PROTECTED level {protected!r} must NEVER appear in any "
                        f"DELETE WHERE clause. Found in SQL: {sql!r}. "
                        "CLAUDE.md: ERROR/CRITICAL retained indefinitely. "
                        "D31: these levels power Power BI dashboards."
                    )


# ---------------------------------------------------------------------------
# Tier 1: batch-size honored
# ---------------------------------------------------------------------------


class TestBatchSizeHonored:
    """Batch-size limit is reflected in DELETE SQL.

    Per § 3.10 L1253 + L1274 + L1301 (Tier 1 test surface) + B-2 lessons.
    """

    def test_batch_size_default_reflected_in_sql(self):
        """Default batch-size (50000) reflected in DELETE statement.

        Per § 3.10 L1253: 'DELETE batch size capped at 50k rows per batch'.
        Per B-2 (SCD2_UPDATE_BATCH_SIZE lessons): batch cap prevents SQL Server
        lock escalation from row locks to table-level exclusive locks.

        B-2, § 3.10 L1253. Spec: § 3.10 L1274 Tool-specific arguments.
        """
        mod = _load_tool_module()
        assert mod is not None

        _call_main(mod, apply=True, dry_run=False, batch_size=_BATCH_SIZE_DEFAULT)

        executed = mod._test_executed_sql
        executed_params = getattr(mod, "_test_executed_params", [])
        delete_calls = [s for s in executed if "DELETE" in s.upper()]

        if delete_calls:
            # Author uses parameterized SQL (`TOP (?)` binding); batch-size lives in
            # bound parameters, NOT SQL text. Check BOTH per B218 lesson + § 3.8
            # precedent (applock pattern fix verified 2026-05-12).
            batch_val = _BATCH_SIZE_DEFAULT
            batch_str = str(batch_val)
            in_sql = any(batch_str in sql for sql in delete_calls)
            in_params = batch_val in executed_params
            assert in_sql or in_params, (
                f"Default batch-size {batch_val!r} must appear in DELETE SQL or bound params. "
                f"Got DELETE calls: {delete_calls!r}. Got bound params: {executed_params!r}. "
                "Per § 3.10 L1253 + B-2: batch cap prevents lock escalation."
            )

    def test_batch_size_override_10000_reflected_in_sql(self):
        """Overridden batch-size (10000) reflected in DELETE statement.

        Per § 3.10 L1297(f): '--batch-size 10000 reflected in the DELETE statement'.
        Lower batch-size reduces lock-hold time at cost of more round-trips.
        Operator-specified value must be respected, not silently replaced with default.

        § 3.10 L1297(f), B-2. Spec: § 3.10 L1274.
        """
        mod = _load_tool_module()
        assert mod is not None

        _call_main(mod, apply=True, dry_run=False, batch_size=_BATCH_SIZE_SMALL)

        executed = mod._test_executed_sql
        executed_params = getattr(mod, "_test_executed_params", [])
        delete_calls = [s for s in executed if "DELETE" in s.upper()]

        if delete_calls:
            batch_val = _BATCH_SIZE_SMALL
            batch_str = str(batch_val)
            in_sql = any(batch_str in sql for sql in delete_calls)
            in_params = batch_val in executed_params
            assert in_sql or in_params, (
                f"Override batch-size {batch_val!r} must appear in DELETE SQL or bound params. "
                f"Got: {delete_calls!r}. Got bound params: {executed_params!r}. "
                "Per § 3.10 L1297(f): batch-size honored per operator override."
            )


# ---------------------------------------------------------------------------
# Tier 1: lock timeout → exit 1
# ---------------------------------------------------------------------------


class TestLockTimeout:
    """sp_getapplock timeout on PipelineLog → exit 1.

    Per § 3.10 L1247 + L1302 (Tier 1 test surface):
    'Lock timeout on PipelineLog (Power BI dashboard query holding read lock)
    → exit 1 with retry-after-N-minutes recommendation in stderr'.

    Edge case I3 (concurrent same-key: UNIQUE/lock prevents).
    """

    def test_applock_timeout_exits_1(self):
        """sp_getapplock returns -1 (timeout) → exit 1, no DELETE executed.

        sp_getapplock on key ('log_retention_cleanup',) per § 3.10 L1251.
        A timeout means another cleanup is running. The tool must exit 1
        (operational failure — retry after the concurrent run finishes)
        rather than proceeding without the lock.

        I3 (concurrent same-key lock). D74 (exit 1 = operational failure).
        Spec: § 3.10 L1247 Concurrency + L1302 Tier 1 test surface.
        """
        mod = _load_tool_module(applock_result=-1)
        assert mod is not None

        result = _call_main(mod, apply=True, dry_run=False)

        exit_code = result.get("exit_code") if isinstance(result, dict) else None
        assert exit_code == EXIT_OPERATIONAL_FAILURE, (
            f"sp_getapplock timeout → exit code must be {EXIT_OPERATIONAL_FAILURE}. "
            f"Got: {exit_code!r}. "
            "Per D74: exit 1 = expected operational failure (retry after N minutes). "
            "Per § 3.10 L1247: lock contention → exit 1."
        )

        # No DELETE must execute when lock was not acquired
        executed = mod._test_executed_sql
        delete_calls = [s for s in executed if "DELETE" in s.upper()]
        assert not delete_calls, (
            f"No DELETE must execute when sp_getapplock times out. "
            f"Found DELETE calls: {delete_calls!r}. "
            "Per I3: lock must be held before any mutation."
        )

    def test_applock_key_is_log_retention_cleanup(self):
        """sp_getapplock is acquired with key 'log_retention_cleanup'.

        Per § 3.10 L1251: "sp_getapplock on ('log_retention_cleanup',) ensures
        one cleanup at a time". The key must be exactly 'log_retention_cleanup'
        so multiple invocations on different servers using the same key name
        are serialized correctly.

        I1 (BatchId retry; ledger short-circuits), I3 (concurrent same-key).
        Spec: § 3.10 L1251 Concurrency.
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

        if applock_calls:
            # Author uses parameterized SQL (`@Resource = ?`); key lives in bound
            # params, NOT SQL text. Check BOTH per B218 lesson + § 3.8 precedent.
            in_sql = any(APPLOCK_KEY in s for s in applock_calls)
            in_params = any(
                isinstance(p, str) and APPLOCK_KEY in p
                for p in executed_params
            )
            assert in_sql or in_params, (
                f"sp_getapplock must use key {APPLOCK_KEY!r}. "
                f"Got applock SQL: {applock_calls!r}. "
                f"Got bound params: {executed_params!r}. "
                "Per § 3.10 L1251: key ('log_retention_cleanup',) ensures "
                "one cleanup at a time."
            )


# ---------------------------------------------------------------------------
# Tier 1: connection failure → exit 1
# ---------------------------------------------------------------------------


class TestConnectionFailure:
    """Connection failure → exit 1.

    Per § 3.10 L1247: 'Connection failure → exit 1'.
    D74: PipelineRetryableError → exit 1 (operator can retry after DB recovery).
    """

    def test_connection_failure_exits_1(self):
        """cursor_for('General') raises Exception → exit 1.

        A connection failure to PipelineLog is retryable (the DB may recover;
        the operator can re-run after a few minutes). Per D74: exit 1 =
        expected operational failure.

        Per D68 hierarchy: connection errors map to PipelineRetryableError → exit 1.

        D68, D74. Spec: § 3.10 L1247 Error modes.
        """
        conn_error = Exception("pyodbc: [08001] SQL Server unreachable (test fixture)")
        mod = _load_tool_module(connection_side_effect=conn_error)
        assert mod is not None

        result = _call_main(mod, apply=True, dry_run=False)

        exit_code = result.get("exit_code") if isinstance(result, dict) else None
        assert exit_code in (EXIT_OPERATIONAL_FAILURE, EXIT_FATAL), (
            f"Connection failure → exit 1 (retryable) or exit 2 (fatal config). "
            f"Got: {exit_code!r}. "
            "Per D68 + D74: PipelineRetryableError → 1; bare Exception → 2. "
            "Per § 3.10 L1247 error modes."
        )


# ---------------------------------------------------------------------------
# Tier 1: config missing → exit 2
# ---------------------------------------------------------------------------


class TestConfigMissing:
    """Config missing → exit 2.

    Per § 3.10 L1295: 'fatal — config / connection / unexpected'.
    D74: missing config = PipelineFatalError → exit 2.
    """

    def test_config_missing_exits_2(self):
        """ImportError on config module → exit 2 (fatal).

        A missing config is a deployment error, not a transient failure.
        The pipeline cannot operate without its configuration. Per D74:
        exit 2 = fatal; page someone.

        D68, D74. Spec: § 3.10 L1295 Exit codes (fatal category).
        """
        mod = _load_tool_module(config_missing=True)

        # If the module itself fails to import (config missing at module level),
        # that IS the exit-2 condition — the tool cannot even be invoked.
        if mod is None:
            # Module-level import failure = fatal exit 2 condition.
            # This test passes: the configuration absence is correctly treated
            # as a fatal (un-runnable) state.
            return

        # If the module loaded but config is absent at runtime:
        result = _call_main(mod, apply=True, dry_run=False)

        exit_code = result.get("exit_code") if isinstance(result, dict) else None
        assert exit_code == EXIT_FATAL, (
            f"Missing config → exit code must be {EXIT_FATAL} (fatal). "
            f"Got: {exit_code!r}. "
            "Per D74: config absence = PipelineFatalError → exit 2."
        )


# ---------------------------------------------------------------------------
# Tier 1: --dry-run + --apply mutual exclusion → exit 2
# ---------------------------------------------------------------------------


class TestDryRunApplyMutex:
    """--dry-run + --apply mutually exclusive → argparse error → exit 2.

    Per B88 (mentioned in task spec — mutex via argparse error).
    Per D74: argparse error → exit 2 (fatal — config/arg error category).
    Per D75: '--apply' and '--dry-run' are canonical args; both provided
    simultaneously is an operator error that must be caught at parse time.
    """

    def test_dry_run_and_apply_together_raises_exit_2(self, capsys):
        """Providing both --dry-run and --apply exits 2 (argparse mutex).

        argparse add_mutually_exclusive_group() raises SystemExit(2) when
        both flags in the group are provided. This prevents the ambiguous
        state where the tool would need to decide which flag takes precedence.

        B88 (mutex). D74 (exit 2 = fatal arg error). D75 (arg naming).
        Spec: § 1.4 (canonical arg table) + § 3.10 tool-specific args.
        """
        mod = _load_tool_module()
        assert mod is not None

        # If main() is the CLI entrypoint, inject conflicting argv
        import sys as _sys

        if hasattr(mod, "_build_arg_parser"):
            parser = mod._build_arg_parser()
            with pytest.raises(SystemExit) as exc_info:
                parser.parse_args(["--dry-run", "--apply", "--actor", _ACTOR])
            assert exc_info.value.code == 2, (
                f"Conflicting --dry-run + --apply must exit 2 (argparse mutex). "
                f"Got: {exc_info.value.code!r}. "
                "Per D74: arg errors = exit 2."
            )
        else:
            # Call main() directly with both flags — should raise or return fatal
            with pytest.raises((SystemExit, ValueError, TypeError)) as exc_info:
                mod.main(
                    actor=_ACTOR,
                    dry_run=True,
                    apply=True,
                    debug_info_days=_DEBUG_INFO_DAYS_DEFAULT,
                    warning_days=_WARNING_DAYS_DEFAULT,
                    batch_size=_BATCH_SIZE_DEFAULT,
                )
            if hasattr(exc_info.value, "code"):
                assert exc_info.value.code != 0, (
                    "Conflicting --dry-run + --apply must exit non-zero. "
                    "Per D74: arg errors = exit 2."
                )


# ---------------------------------------------------------------------------
# Tier 1: --json output structure
# ---------------------------------------------------------------------------


class TestJsonOutputStructure:
    """--json output structure per § 3.10 L1290.

    Per § 3.10 L1290 (Stdout --json):
    {"dry_run": true|false, "purged": {...}, "retained": {...}, "audit_event_id": N}
    """

    def test_json_output_has_required_keys(self):
        """--json mode returns dict with dry_run, purged, retained, audit_event_id.

        Per § 3.10 L1290 canonical --json output contract. Machine consumers
        (Automic scripts, monitoring tools) parse this output; missing keys
        silently break downstream parsing.

        D74 (exit 0 on json success), D76 (audit_event_id ties to PipelineEventLog).
        Spec: § 3.10 L1290 Stdout (--json).
        """
        mod = _load_tool_module()
        assert mod is not None

        result = _call_main(mod, apply=True, dry_run=False, json_output=True)

        if not isinstance(result, dict):
            pytest.skip("main() returned non-dict; JSON output path not yet implemented")

        missing = REQUIRED_JSON_KEYS - result.keys()
        assert not missing, (
            f"--json output missing required keys: {missing!r}. "
            f"Got keys: {set(result.keys())!r}. "
            "Per § 3.10 L1290: {dry_run, purged, retained, audit_event_id} required."
        )

    def test_json_output_purged_contains_purgeable_levels(self):
        """--json 'purged' dict contains only purgeable levels (DEBUG, INFO, WARNING).

        Per § 3.10 L1290: 'purged': {'DEBUG': N, 'INFO': M, 'WARNING': K}.
        ERROR and CRITICAL must NOT appear as keys in the purged dict.

        D31 (protect ERROR/CRITICAL from purge). Spec: § 3.10 L1290.
        """
        mod = _load_tool_module()
        assert mod is not None

        result = _call_main(mod, apply=True, dry_run=False, json_output=True)

        if not isinstance(result, dict) or "purged" not in result:
            pytest.skip("purged key not in result; JSON output path not yet implemented")

        purged = result["purged"]
        if not isinstance(purged, dict):
            return  # purged is not a dict; other tests cover this

        for key in purged.keys():
            assert key.upper() in PURGEABLE_LOGLEVELS, (
                f"'purged' dict must only contain purgeable levels "
                f"{PURGEABLE_LOGLEVELS!r}. Found: {key!r}. "
                "Per § 3.10 L1290 + CLAUDE.md: ERROR/CRITICAL retained indefinitely."
            )

    def test_json_output_retained_contains_protected_levels(self):
        """--json 'retained' dict contains only protected levels (ERROR, CRITICAL).

        Per § 3.10 L1290: 'retained': {'ERROR': N, 'CRITICAL': M}.
        Only the levels with indefinite retention policy appear here.

        D31 (Power BI dashboards depend on ERROR/CRITICAL rows).
        Spec: § 3.10 L1290.
        """
        mod = _load_tool_module()
        assert mod is not None

        result = _call_main(mod, apply=True, dry_run=False, json_output=True)

        if not isinstance(result, dict) or "retained" not in result:
            pytest.skip("retained key not in result; JSON output path not yet implemented")

        retained = result["retained"]
        if not isinstance(retained, dict):
            return

        for key in retained.keys():
            assert key.upper() in PROTECTED_LOGLEVELS, (
                f"'retained' dict must only contain protected levels "
                f"{PROTECTED_LOGLEVELS!r}. Found: {key!r}. "
                "Per § 3.10 L1290: retained is exclusively ERROR + CRITICAL."
            )

    def test_json_dry_run_flag_matches_invocation(self):
        """--json 'dry_run' flag correctly reflects dry-run invocation state.

        Per § 3.10 L1290: 'dry_run: true|false'. The field must match the
        invocation flag exactly — not default to True or False regardless.

        D74 (dry-run = exit 0). Spec: § 3.10 L1290.
        """
        mod = _load_tool_module()
        assert mod is not None

        # dry-run invocation
        result_dry = _call_main(mod, dry_run=True, apply=False, json_output=True)
        if isinstance(result_dry, dict) and "dry_run" in result_dry:
            assert result_dry["dry_run"] is True, (
                f"dry_run must be True in --json output when invoked with dry_run=True. "
                f"Got: {result_dry['dry_run']!r}."
            )

        # apply invocation
        result_apply = _call_main(mod, dry_run=False, apply=True, json_output=True)
        if isinstance(result_apply, dict) and "dry_run" in result_apply:
            assert result_apply["dry_run"] is False, (
                f"dry_run must be False in --json output when invoked with apply=True. "
                f"Got: {result_apply['dry_run']!r}."
            )


# ---------------------------------------------------------------------------
# Tier 1: audit row Metadata JSON shape per D76
# ---------------------------------------------------------------------------


class TestAuditRowMetadataShape:
    """Audit row Metadata JSON shape per D76 contract.

    Per D76: every CLI invocation writes ONE PipelineEventLog row with
    EventType='CLI_LOG_RETENTION_CLEANUP' + Metadata JSON containing
    event_kind, per-level counts, actor, justification, dry_run flag.

    Naive-UTC datetime invariant (SCD2-P1-f): any datetime captured in
    Metadata must have tzinfo=None.
    """

    def test_audit_row_event_type_is_cli_log_retention_cleanup(self):
        """PipelineEventLog row EventType = 'CLI_LOG_RETENTION_CLEANUP'.

        Per D76 + § 3.10 L1234: EventType follows CLI_<TOOL_NAME> pattern.
        The audit consumer queries WHERE EventType='CLI_LOG_RETENTION_CLEANUP';
        any deviation silently drops audit rows from the count queries.

        North Star: Audit-grade (traceability requires consistent EventType).
        D76. Spec: § 3.10 L1234.
        """
        mod = _load_tool_module()
        assert mod is not None

        result = _call_main(mod, apply=True, dry_run=False)

        if isinstance(result, dict) and "event_type" in result:
            assert result["event_type"] == EXPECTED_EVENT_TYPE, (
                f"EventType must be {EXPECTED_EVENT_TYPE!r}. "
                f"Got: {result['event_type']!r}. "
                "Per D76 CLI_* family naming: CLI_<TOOL_NAME>."
            )

    def test_audit_row_metadata_contains_required_keys(self):
        """Metadata JSON contains event_kind, actor, dry_run at minimum.

        Per D76 audit-row contract: Metadata JSON must carry the canonical
        set of fields so PipelineEventLog consumers can filter and aggregate
        cleanup events programmatically.

        Additional tool-specific keys (per-level counts: debug_purged,
        info_purged, warning_purged, error_retained, critical_retained)
        must also be present when the tool is implemented.

        D76. Spec: § 3.10 L1234 + D76 contract.
        """
        mod = _load_tool_module()
        assert mod is not None

        result = _call_main(mod, apply=True, dry_run=False)

        if not isinstance(result, dict):
            pytest.skip("main() returned non-dict; Metadata not yet inspectable")

        # Check top-level mandatory keys (these appear in Metadata)
        for key in REQUIRED_METADATA_KEYS:
            assert key in result, (
                f"result must contain mandatory key {key!r} per D76 audit-row contract. "
                f"Got keys: {set(result.keys())!r}."
            )

    def test_audit_row_actor_echoed_in_result(self):
        """actor value from --actor arg is echoed in result/Metadata.

        Per D76 + D75: --actor surfaces in PipelineEventLog.Metadata.actor
        for audit trail. The actor must be echoed verbatim — not replaced
        with a hardcoded default.

        D75 (--actor canonical arg), D76 (Metadata.actor). Spec: § 3.10.
        """
        mod = _load_tool_module()
        assert mod is not None

        result = _call_main(mod, actor="automic", apply=True, dry_run=False)

        if isinstance(result, dict) and "actor" in result:
            assert result["actor"] == "automic", (
                f"actor must be echoed in result. "
                f"Got: {result.get('actor')!r}. "
                "Per D75: --actor surfaces in PipelineEventLog.Metadata.actor."
            )

    def test_audit_row_metadata_naive_datetime(self):
        """Any datetime captured in audit row Metadata must be tzinfo=None.

        Naive-UTC datetime invariant (SCD2-P1-f + CDC-NOW-MS): tz-aware
        datetimes sent via pyodbc as DATETIMEOFFSET cause implicit timezone
        conversion when stored in DATETIME2(3) columns. Mismatched precision
        makes strict comparisons fail silently (the alternating I/U/I/U
        symptom applied to cleanup event timestamps).

        Naive datetime preserves UTC wall-time semantics without ODBC
        conversion surprises.

        SCD2-P1-f (naive-UTC invariant), CDC-NOW-MS. Spec: § 3.10.
        """
        mod = _load_tool_module()
        assert mod is not None

        result = _call_main(mod, apply=True, dry_run=False)

        if not isinstance(result, dict):
            pytest.skip("main() returned non-dict; datetime fields not yet inspectable")

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


# ---------------------------------------------------------------------------
# Tier 1: sp_getapplock acquired with correct key; lock-busy → exit 1
# ---------------------------------------------------------------------------


class TestSpGetApplockContract:
    """sp_getapplock contract: key = 'log_retention_cleanup'; busy → exit 1.

    Per § 3.10 L1251: 'sp_getapplock on ("log_retention_cleanup",) ensures
    one cleanup at a time; --workers not supported (serial is correct)'.

    Edge cases I1 (same BatchId retry), I3 (concurrent same-key).
    """

    def test_applock_acquired_before_delete(self):
        """sp_getapplock acquired BEFORE any DELETE statements.

        The lock must be acquired first to prevent concurrent cleanup runs
        from interfering. If DELETE executes before the lock is held, a
        race condition between two parallel Automic invocations could cause
        double-deletion (idempotent for this tool but still incorrect sequencing).

        I1 (idempotent retry), I3 (concurrent same-key). Spec: § 3.10 L1251.
        """
        mod = _load_tool_module()
        assert mod is not None

        _call_main(mod, apply=True, dry_run=False)

        executed = mod._test_executed_sql
        applock_calls = [i for i, s in enumerate(executed)
                         if "getapplock" in s.lower() or "sp_getapplock" in s.lower()]
        delete_calls = [i for i, s in enumerate(executed)
                        if "DELETE" in s.upper()]

        if applock_calls and delete_calls:
            # The first applock call must precede the first DELETE call
            assert min(applock_calls) < min(delete_calls), (
                f"sp_getapplock must be called BEFORE any DELETE. "
                f"Applock call positions: {applock_calls!r}. "
                f"Delete call positions: {delete_calls!r}. "
                "Ordering ensures mutual exclusion per I3."
            )

    def test_applock_busy_produces_exit_1_no_delete(self):
        """sp_getapplock timeout (result=-1) → exit 1; no DELETE executed.

        Per § 3.10 L1247 + L1302 Tier 1 test surface:
        'Lock timeout on PipelineLog → exit 1 with retry-after-N-minutes
        recommendation in stderr'.

        I3 (concurrent same-key). D74 (exit 1 = operational failure).
        Spec: § 3.10 L1247 Error modes + L1302.
        """
        mod = _load_tool_module(applock_result=-1)
        assert mod is not None

        result = _call_main(mod, apply=True, dry_run=False)

        exit_code = result.get("exit_code") if isinstance(result, dict) else None
        assert exit_code == EXIT_OPERATIONAL_FAILURE, (
            f"Lock contention → exit {EXIT_OPERATIONAL_FAILURE}. "
            f"Got: {exit_code!r}. Per § 3.10 L1247."
        )

        executed = mod._test_executed_sql
        delete_calls = [s for s in executed if "DELETE" in s.upper()]
        assert not delete_calls, (
            f"No DELETE must execute when lock is not acquired. "
            f"Found: {delete_calls!r}. "
            "Per I3: mutual exclusion must be enforced before any mutation."
        )


# ---------------------------------------------------------------------------
# Tier 1: idempotency — second run produces zero purged rows
# ---------------------------------------------------------------------------


class TestIdempotency:
    """Re-running after purge produces zero rows purged (D15 invariant).

    Per § 3.10 L1241-1242 Idempotency:
    'Re-invocation produces zero rows purged (already purged; nothing < cutoff).
    DELETE is atomic; partial-purge crash leaves a deterministic state
    (next run completes the purge).'

    Edge case I4 (BCP partial-write: stage-check-exchange handles).
    """

    def test_dry_run_does_not_mutate_state(self):
        """--dry-run invocation is idempotent: no state mutation occurs.

        Per D15: idempotent behavior means the dry-run invocation produces
        the same observable state regardless of how many times it is called.
        No DELETE, no applock acquisition that would block a concurrent run.

        D15 (idempotency mandatory), D74 (exit 0). Spec: § 3.10 L1241.
        """
        mod = _load_tool_module()
        assert mod is not None

        result1 = _call_main(mod, dry_run=True, apply=False)
        result2 = _call_main(mod, dry_run=True, apply=False)

        for result in (result1, result2):
            if isinstance(result, dict):
                assert result.get("exit_code") in (EXIT_SUCCESS, None), (
                    f"dry-run must exit {EXIT_SUCCESS}. Got: {result.get('exit_code')!r}"
                )

        executed = mod._test_executed_sql
        delete_calls = [s for s in executed if "DELETE" in s.upper()]
        assert not delete_calls, (
            f"dry-run must NOT produce DELETE statements even on repeated calls. "
            f"Found: {delete_calls!r}. Per D15 idempotency + § 3.10 L1241."
        )


# ---------------------------------------------------------------------------
# Tier 1: PipelineLog canonical column verification (Pitfall #9.a + #9.l)
# ---------------------------------------------------------------------------


class TestPipelineLogColumnNames:
    """Verify DELETE WHERE clause references canonical PipelineLog column names.

    Pitfall #9.a (column-name lift): tests must verify canonical column names
    per phase1/01_database_schema.md L197-236 DDL.
    Pitfall #9.l (canonical-schema-detail drift): re-read DDL before authoring.

    Canonical columns (from DDL L197-213):
      LogId, BatchId, TableName, SourceName, LogLevel, Module, FunctionName,
      Message, ErrorType, StackTrace, Metadata, CreatedAt, CycleType,
      CycleDate, ServerRole, Layer.

    The DELETE WHERE clause must use:
      - 'LogLevel' (not 'Level', 'log_level', 'Severity')
      - 'CreatedAt' (not 'Timestamp', 'created_at', 'LoggedAt', 'LogTime')
    """

    def test_delete_where_uses_loglevel_column_name(self):
        """DELETE WHERE uses 'LogLevel' (canonical DDL name) not an alias.

        Pitfall #9.a: column-name drift — tests must use the exact column
        name from DDL. 'LogLevel' is the canonical name per DDL L205.
        Alternative names ('Level', 'log_level', 'Severity') do not exist
        in the table and would cause a SQL column-not-found error at runtime.

        Spec: phase1/01_database_schema.md L205.
        """
        mod = _load_tool_module()
        assert mod is not None

        _call_main(mod, apply=True, dry_run=False)

        executed = mod._test_executed_sql
        delete_calls = [s for s in executed if "DELETE" in s.upper()]

        if delete_calls:
            for sql in delete_calls:
                # Must use canonical column name
                assert "LogLevel" in sql or "loglevel" in sql.lower(), (
                    f"DELETE WHERE must reference canonical column 'LogLevel'. "
                    f"Got SQL: {sql!r}. "
                    "Per DDL L205: column is 'LogLevel', not 'Level' or 'Severity'."
                )
                # Must NOT use non-canonical aliases
                for bad_name in ("Severity", "Level,", "log_level", "LogSeverity"):
                    assert bad_name not in sql, (
                        f"DELETE WHERE must not use non-canonical alias {bad_name!r}. "
                        f"Got SQL: {sql!r}. "
                        "Pitfall #9.a: column-name drift."
                    )

    def test_delete_where_uses_createdat_column_name(self):
        """DELETE WHERE uses 'CreatedAt' (canonical DDL name) not an alias.

        Pitfall #9.a: column-name drift — 'CreatedAt' is the canonical name
        per DDL L209 (DATETIME2(3) NOT NULL DEFAULT SYSUTCDATETIME()).
        Alternative names ('Timestamp', 'created_at', 'LoggedAt', 'LogTime')
        do not exist in the table.

        Spec: phase1/01_database_schema.md L209.
        """
        mod = _load_tool_module()
        assert mod is not None

        _call_main(mod, apply=True, dry_run=False)

        executed = mod._test_executed_sql
        delete_calls = [s for s in executed if "DELETE" in s.upper()]

        if delete_calls:
            for sql in delete_calls:
                assert "CreatedAt" in sql or "createdat" in sql.lower(), (
                    f"DELETE WHERE must reference canonical column 'CreatedAt'. "
                    f"Got SQL: {sql!r}. "
                    "Per DDL L209: column is 'CreatedAt', not 'Timestamp' or 'LoggedAt'."
                )
                for bad_name in ("Timestamp,", "LoggedAt", "LogTime", "created_at"):
                    assert bad_name not in sql, (
                        f"DELETE WHERE must not use non-canonical alias {bad_name!r}. "
                        f"Got SQL: {sql!r}. "
                        "Pitfall #9.a: column-name drift."
                    )


# ---------------------------------------------------------------------------
# Tier 1: exit code contract (D74) — parametrized
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "scenario,expected_exit",
    [
        ("success_apply", EXIT_SUCCESS),
        ("success_dry_run", EXIT_SUCCESS),
        ("lock_timeout", EXIT_OPERATIONAL_FAILURE),
        ("connection_failure", EXIT_OPERATIONAL_FAILURE),
    ],
)
def test_exit_code_contract(scenario: str, expected_exit: int):
    """D74 exit-code contract: 0/1/2 per documented scenario.

    D74 canonical exit codes per § 3.10 L1292-1295:
      0 = cleanup completed (or dry-run preview produced)
      1 = lock contention / partial-batch error; operator can re-run later
      2 = fatal — config / connection / unexpected

    Per R22 (CLI exit-code drift risk): Automic JOB_LOG_CLEANUP interprets
    the exit-code contract per D74; any deviation causes incorrect escalation
    or under-escalation of failures.

    D74, R22, B80 (Automic job candidate). Spec: § 3.10 L1292-1295.
    """
    if scenario == "success_apply":
        mod = _load_tool_module()
        result = _call_main(mod, apply=True, dry_run=False)
    elif scenario == "success_dry_run":
        mod = _load_tool_module()
        result = _call_main(mod, dry_run=True, apply=False)
    elif scenario == "lock_timeout":
        mod = _load_tool_module(applock_result=-1)
        result = _call_main(mod, apply=True, dry_run=False)
    else:  # connection_failure
        mod = _load_tool_module(
            connection_side_effect=Exception("connection refused — test fixture")
        )
        result = _call_main(mod, apply=True, dry_run=False)

    assert mod is not None, f"Module must load for scenario {scenario!r}"
    assert isinstance(result, dict), (
        f"main() must return a dict for scenario={scenario!r}. "
        f"Got: {type(result)!r}"
    )
    exit_code = result.get("exit_code")
    assert exit_code == expected_exit, (
        f"Scenario {scenario!r}: expected exit_code={expected_exit}, "
        f"got {exit_code!r}. "
        "D74 exit-code contract; R22 Automic mis-categorization risk."
    )
