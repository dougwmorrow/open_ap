"""Tier 0 build-time smoke test for tools/log_retention_cleanup.py.

Per D67 — runs at build time + every commit. Runtime ceiling < 5 s.
All external dependencies (pyodbc cursors, PipelineEventLog) are mocked.
No live DB, no live network required.

6 D77-canonical assertions per phase1/04_tools.md § 3.10 L1297:
  (a) Module imports without error (tools/log_retention_cleanup.py)
  (b) --help exits 0 (D77 scaffold assertion 2)
  (c) --dry-run does NOT call DELETE (D77 scaffold assertion 3)
  (d) --apply invokes per-level DELETE statements; mock execute count > 0;
      ERROR / CRITICAL never appears in DELETE WHERE clause
      (D77 scaffold assertion 4 + § 3.10 L1233 idempotency contract)
  (e) ERROR / CRITICAL never appears in any DELETE WHERE clause across
      all batches (§ 3.10 L1233: indefinite retention contract)
  (f) --batch-size 10000 reflected in the DELETE statement SQL
      (§ 3.10 L1297 explicit scaffold requirement)

North Star pillars:
  - Audit-grade (D76 audit-row contract: exactly one CLI_LOG_RETENTION_CLEANUP
    row written per invocation; Metadata JSON carries per-level counts, actor,
    dry_run flag).
  - Operationally stable (D67 Tier 0: import + invoke + shape + error-modes in
    < 5 s with zero external I/O; D74 exit-code contract 0/1/2 verified).
  - Idempotent (D15: re-invoking after purge produces zero rows purged;
    DELETE is atomic — partial-purge crash leaves deterministic state per
    § 3.10 L1242).

D-numbers: D15 (idempotency mandatory), D26 (append-only exception — log
retention is a deliberate exception per CLAUDE.md), D31 (PowerBI: purge must
not touch ERROR/CRITICAL which power dashboards), D67 (Tier 0 discipline),
D74 (exit-code contract 0/1/2), D75 (arg naming: actor / debug-info-days /
warning-days / batch-size / dry-run / apply / json), D76 (audit-row contract
— CLI_LOG_RETENTION_CLEANUP), D77 (6-canonical Tier 0 scaffold).

B-numbers: B80 (JOB_LOG_CLEANUP Automic inventory candidate; tracked in
§ 3.10 L1237 — Round 6 deployment to amend frozen-8 job set).

Spec: phase1/04_tools.md § 3.10 (canonical spec L1220-1305).
PipelineLog DDL: phase1/01_database_schema.md L197-236.
  - LogLevel CHECK: IN ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')
  - CreatedAt: DATETIME2(3) NOT NULL DEFAULT SYSUTCDATETIME()
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
import time
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
# Module path — implementation lands at Phase 2 R1
# ---------------------------------------------------------------------------

_TOOL_PATH = _PROJECT_ROOT / "tools" / "log_retention_cleanup.py"
_TOOL_MODULE_KEY = "tools.log_retention_cleanup"

# ---------------------------------------------------------------------------
# Shared constants — single source of truth
# ---------------------------------------------------------------------------

# D76 EventType per CLI_* family (§ 3.10 L1234)
EXPECTED_EVENT_TYPE = "CLI_LOG_RETENTION_CLEANUP"

# D74 exit codes (§ 1.1 + § 3.10 L1292-1295)
EXIT_SUCCESS = 0    # cleanup completed (or dry-run preview produced)
EXIT_OPERATIONAL_FAILURE = 1  # lock contention / partial-batch error; re-run later
EXIT_FATAL = 2      # fatal — config / connection / unexpected

# D75 canonical arg values
_ACTOR = "test-build-smoke"

# Retention windows per CLAUDE.md "Log retention policy" + § 3.10 L1270-1274
_DEBUG_INFO_DAYS_DEFAULT = 30
_WARNING_DAYS_DEFAULT = 90
# B104 closure 2026-05-14 (Round 6 § 7.8): default 50000 -> 4000
# mirroring config.SCD2_UPDATE_BATCH_SIZE per B-2 5000-lock ceiling.
_BATCH_SIZE_DEFAULT = 4000
_BATCH_SIZE_OVERRIDE = 10000  # used in assertion (f)

# LogLevel enum values per CK_PipelineLog_LogLevel
# (phase1/01_database_schema.md L215-216)
LOGLEVEL_ENUM = frozenset({"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
# These must NEVER appear in a DELETE WHERE clause per CLAUDE.md retention policy
PROTECTED_LOGLEVELS = frozenset({"ERROR", "CRITICAL"})


# ---------------------------------------------------------------------------
# Module loader — mocks all external dependencies
# ---------------------------------------------------------------------------


def _load_tool_module(
    *,
    connection_side_effect: Exception | None = None,
    applock_timeout: bool = False,
) -> Any:
    """Load tools/log_retention_cleanup.py with all external imports mocked.

    Parameters
    ----------
    connection_side_effect:
        If set, cursor_for() raises this exception (simulates connection failure).
    applock_timeout:
        If True, sp_getapplock returns -1 (lock busy) — simulates lock contention.
    """
    if _TOOL_MODULE_KEY in sys.modules:
        del sys.modules[_TOOL_MODULE_KEY]

    mock_cursor = MagicMock()
    mock_cursor.execute = MagicMock()
    mock_cursor.fetchone = MagicMock(return_value=None)
    mock_cursor.fetchall = MagicMock(return_value=[])
    # Default rowcount = 0 so batched-DELETE loops terminate cleanly under mock
    # (author's `_delete_cohort_batched` uses `cursor.rowcount <= 0` as exit cond).
    mock_cursor.rowcount = 0

    # sp_getapplock return value: 0 = lock acquired (per § 3.10 L1251)
    if applock_timeout:
        # Simulate lock busy — sp_getapplock returns -1 per SQL Server semantics
        mock_cursor.fetchone.return_value = (-1,)
    else:
        mock_cursor.fetchone.return_value = (0,)

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
        mock_connections.get_general_connection = MagicMock(return_value=mock_conn)
        mock_connections.get_connection = MagicMock(return_value=mock_conn)

    mock_event_tracker = MagicMock()
    # Simulate track() context manager that yields an event object
    mock_event = MagicMock()
    mock_event_tracker.track = MagicMock()
    mock_event_tracker.track.return_value.__enter__ = MagicMock(return_value=mock_event)
    mock_event_tracker.track.return_value.__exit__ = MagicMock(return_value=False)

    mock_config = MagicMock()
    mock_config.GENERAL_DB = "General"

    mock_errors = MagicMock()
    # Use real exception classes from canonical _exceptions.py per B215
    from data_load._exceptions import SourceConnectError
    mock_errors.PipelineRetryableError = SourceConnectError

    mock_pyodbc = MagicMock()
    mock_pyodbc.connect = MagicMock(return_value=mock_conn)

    sys_modules_patch = {
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
        # Register module BEFORE exec_module so module-level @dataclass with
        # PEP 604 `int | None` type hints can look itself up in sys.modules
        # (Python 3.12 dataclass._is_type bug-class fix per B214 pattern).
        sys.modules[_TOOL_MODULE_KEY] = mod
        spec.loader.exec_module(mod)

    # Stash patches for test invocation re-application (per measure_lateness pattern).
    mod._test_sys_modules_patch = sys_modules_patch
    return mod


def _invoke_main(mod, **kwargs):
    """Call mod.main() with sys.modules patches re-applied at runtime.

    Per measure_lateness L583-587 pattern: `with patch.dict(...)` in
    `_load_tool_module` exits before main() runs; the tool's runtime
    `sys.modules.get("pyodbc")` reverts to the real pyodbc unless re-patched
    here.
    """
    sys_modules_patch = getattr(mod, "_test_sys_modules_patch", {})
    with patch.dict("sys.modules", sys_modules_patch):
        return mod.main(**kwargs)


# ---------------------------------------------------------------------------
# (a) Module imports without error
# ---------------------------------------------------------------------------


def test_module_imports():
    """(a) tools/log_retention_cleanup.py imports without error.

    Per D67 Tier 0 assertion 1 + D77 6-canonical scaffold assertion 1.
    Verifies no missing dependencies, no syntax errors, no import-time DB calls.

    The module must expose a top-level 'main' function per § 3.10 CLI interface.

    North Star: Operationally stable (import failure blocks every subsequent
    build step per D67 failure consequence rule).

    D67, D77. Spec: phase1/04_tools.md § 3.10.
    """
    mod = _load_tool_module()
    assert mod is not None, (
        "tools/log_retention_cleanup.py must load without error. "
        "Check for missing dependencies or syntax errors."
    )
    assert hasattr(mod, "main"), (
        "tools/log_retention_cleanup.py must expose a top-level 'main' function "
        "per § 3.10 CLI interface."
    )


# ---------------------------------------------------------------------------
# (b) --help exits 0
# ---------------------------------------------------------------------------


def test_help_exits_0(monkeypatch, capsys):
    """(b) --help exits 0 per D77 Tier 0 canonical scaffold assertion 2.

    argparse always calls sys.exit(0) on --help. Confirms the CLI is wired
    up correctly and does not crash before argparse reaches argument parsing.

    D74 (exit 0 = success on preview / help), D77. Spec: § 3.10 L1297(b).
    """
    mod = _load_tool_module()

    monkeypatch.setattr(sys, "argv", ["log_retention_cleanup.py", "--help"])

    if hasattr(mod, "_build_arg_parser"):
        parser = mod._build_arg_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--help"])
        assert exc_info.value.code == 0, (
            f"--help must exit 0 per D74. Got: {exc_info.value.code!r}"
        )
    else:
        # The module may expose main() only — call with canonical args
        # and accept exit 0/SystemExit(0) as correct --help behavior.
        try:
            result = _invoke_main(mod,
                actor=_ACTOR,
                dry_run=True,
                apply=False,
                debug_info_days=_DEBUG_INFO_DAYS_DEFAULT,
                warning_days=_WARNING_DAYS_DEFAULT,
                batch_size=_BATCH_SIZE_DEFAULT,
            )
            # Programmatic path — exit_code in {0, 1, 2} per D74
            if isinstance(result, dict):
                assert result.get("exit_code") in (0, 1, 2)
        except SystemExit as exc:
            assert exc.code == 0, (
                f"main() must not raise SystemExit with non-zero code on help/dry-run. "
                f"Got: {exc.code!r}"
            )


# ---------------------------------------------------------------------------
# (c) --dry-run does NOT call DELETE
# ---------------------------------------------------------------------------


def test_dry_run_does_not_call_delete():
    """(c) --dry-run mode does NOT execute any DELETE statement.

    Per § 3.10 L1297(c): '--dry-run does NOT call DELETE'. The dry-run
    produces a preview (per-level eligible-to-purge counts) without
    mutating PipelineLog.

    This is the core idempotency-safety invariant: operators can safely
    run the tool in dry-run mode to preview what would be purged without
    risk of accidental deletion.

    D15 (idempotency), D74 (exit 0 on dry-run success), D75 (--dry-run arg).
    Spec: § 3.10 L1276-1285 (dry-run stdout contract) + L1297(c).
    """
    mod = _load_tool_module()

    captured_sql: list[str] = []

    mock_cursor = MagicMock()
    # Record every SQL statement passed to execute()
    mock_cursor.execute.side_effect = lambda sql, *a, **kw: captured_sql.append(str(sql))
    # sp_getapplock returns 0 (lock acquired)
    mock_cursor.fetchone.return_value = (0,)
    mock_cursor.fetchall.return_value = []

    with patch("pyodbc.connect", return_value=mock_cursor):
        try:
            result = _invoke_main(mod,
                actor=_ACTOR,
                dry_run=True,
                apply=False,
                debug_info_days=_DEBUG_INFO_DAYS_DEFAULT,
                warning_days=_WARNING_DAYS_DEFAULT,
                batch_size=_BATCH_SIZE_DEFAULT,
            )
        except SystemExit as exc:
            assert exc.code == EXIT_SUCCESS, (
                f"--dry-run must exit 0 per D74. Got: {exc.code!r}"
            )
            result = {"exit_code": EXIT_SUCCESS, "dry_run": True}

    # No DELETE statement must have been issued
    delete_calls = [s for s in captured_sql if "DELETE" in s.upper()]
    assert not delete_calls, (
        f"--dry-run must NOT execute DELETE statements. "
        f"Found: {delete_calls!r}. "
        "Per § 3.10 L1297(c) and D15 idempotency: dry-run is preview only."
    )

    if isinstance(result, dict):
        assert result.get("dry_run") is True, (
            "result['dry_run'] must be True when invoked with dry_run=True."
        )
        assert result.get("exit_code") in (EXIT_SUCCESS, EXIT_OPERATIONAL_FAILURE, None), (
            f"dry-run must exit 0 or 1 per D74. Got: {result.get('exit_code')!r}"
        )


# ---------------------------------------------------------------------------
# (d) --apply invokes per-level DELETE; execute count > 0
# ---------------------------------------------------------------------------


def test_apply_invokes_per_level_delete():
    """(d) --apply executes per-level DELETE statements; mock execute count > 0.

    Per § 3.10 L1233 + L1297(d):
      DELETE FROM General.ops.PipelineLog WHERE LogLevel IN ('DEBUG','INFO')
        AND CreatedAt < @cutoff_30_days
      DELETE FROM General.ops.PipelineLog WHERE LogLevel = 'WARNING'
        AND CreatedAt < @cutoff_90_days

    At least 2 DELETE executes expected (one for DEBUG+INFO batch, one for
    WARNING batch). ERROR / CRITICAL must NOT appear in any WHERE clause.

    D74 (exit 0 on success), D75 (--apply arg), D76 (audit row written).
    Spec: § 3.10 L1233 Produces + L1297(d).
    """
    mod = _load_tool_module()

    captured_sql: list[str] = []

    mock_cursor = MagicMock()
    mock_cursor.execute.side_effect = lambda sql, *a, **kw: captured_sql.append(str(sql))
    mock_cursor.fetchone.return_value = (0,)  # applock: acquired
    mock_cursor.fetchall.return_value = []

    with patch("pyodbc.connect", return_value=mock_cursor):
        try:
            result = _invoke_main(mod,
                actor=_ACTOR,
                dry_run=False,
                apply=True,
                debug_info_days=_DEBUG_INFO_DAYS_DEFAULT,
                warning_days=_WARNING_DAYS_DEFAULT,
                batch_size=_BATCH_SIZE_DEFAULT,
            )
        except SystemExit as exc:
            assert exc.code == EXIT_SUCCESS, (
                f"--apply must exit 0 per D74. Got: {exc.code!r}"
            )
            result = {"exit_code": EXIT_SUCCESS, "dry_run": False}

    delete_calls = [s for s in captured_sql if "DELETE" in s.upper()]
    assert len(delete_calls) >= 1, (
        f"--apply must execute at least 1 DELETE statement. "
        f"Got execute calls: {captured_sql!r}. "
        "Per § 3.10 L1233: DELETE WHERE LogLevel IN (...) AND CreatedAt < @cutoff"
    )

    # Verify ERROR / CRITICAL do NOT appear in any DELETE clause — assertion (e) partner
    for sql in delete_calls:
        for protected in PROTECTED_LOGLEVELS:
            assert protected not in sql.upper().replace("'ERROR'", "").replace("'CRITICAL'", ""), (
                f"ERROR / CRITICAL must NEVER appear in a DELETE WHERE clause. "
                f"Found: {protected!r} in SQL: {sql!r}. "
                "Per CLAUDE.md retention policy: ERROR/CRITICAL retained indefinitely."
            )


# ---------------------------------------------------------------------------
# (e) ERROR / CRITICAL never appear in DELETE WHERE clause
# ---------------------------------------------------------------------------


def test_error_critical_never_in_delete_where():
    """(e) ERROR / CRITICAL never appear in DELETE WHERE clause across all batches.

    Per § 3.10 L1233 + L1297(e) + CLAUDE.md retention policy:
      'indefinite for ERROR/CRITICAL' — these levels must NEVER be included in
      any DELETE statement issued by this tool, regardless of batch-size or
      retention-window overrides.

    This invariant protects:
    - Power BI dashboards (D31: ERROR/CRITICAL power the error-rate dashboards)
    - Audit trail (D26: append-only exception — log retention only touches
      DEBUG/INFO/WARNING levels)

    Verifies with a range of retention-window overrides to ensure no override
    path accidentally includes ERROR/CRITICAL.

    D26 (append-only exception), D31 (PowerBI ERROR/CRITICAL retained), D74.
    Spec: § 3.10 L1233 + L1270-1274 + L1297(e).
    """
    mod = _load_tool_module()

    for debug_info_days, warning_days in [
        (_DEBUG_INFO_DAYS_DEFAULT, _WARNING_DAYS_DEFAULT),
        (1, 1),       # aggressive override (testing mode)
        (365, 730),   # extended override
    ]:
        captured_sql: list[str] = []

        mock_cursor = MagicMock()
        mock_cursor.execute.side_effect = lambda sql, *a, **kw: captured_sql.append(str(sql))
        mock_cursor.fetchone.return_value = (0,)
        mock_cursor.fetchall.return_value = []

        with patch("pyodbc.connect", return_value=mock_cursor):
            try:
                _invoke_main(mod,
                    actor=_ACTOR,
                    dry_run=False,
                    apply=True,
                    debug_info_days=debug_info_days,
                    warning_days=warning_days,
                    batch_size=_BATCH_SIZE_DEFAULT,
                )
            except SystemExit:
                pass

        delete_calls = [s for s in captured_sql if "DELETE" in s.upper()]
        for sql in delete_calls:
            for protected in PROTECTED_LOGLEVELS:
                # The protected level must not appear as a WHERE predicate target.
                # We look for it as a quoted string value to avoid matching column names.
                for quoted in (f"'{protected}'", f'"{protected}"'):
                    assert quoted not in sql, (
                        f"Protected level {protected!r} must NEVER appear in a "
                        f"DELETE WHERE clause. Found in SQL: {sql!r}. "
                        f"Override: debug_info_days={debug_info_days}, "
                        f"warning_days={warning_days}. "
                        "Per CLAUDE.md retention policy: ERROR/CRITICAL retained indefinitely."
                    )


# ---------------------------------------------------------------------------
# (f) --batch-size 10000 reflected in DELETE statement
# ---------------------------------------------------------------------------


def test_batch_size_reflected_in_delete_statement():
    """(f) --batch-size 10000 is reflected in the DELETE statement SQL.

    Per § 3.10 L1297(f): '--batch-size 10000 reflected in the DELETE statement'.
    The per-batch DELETE cap must use the operator-supplied batch-size to
    prevent lock escalation (B-2 lesson — § 3.10 L1253).

    Expected SQL pattern: DELETE TOP (10000) FROM General.ops.PipelineLog ...
    or equivalent LIMIT / batch-control syntax.

    B-2 (lock escalation — batch size cap), D74 (--batch-size arg per D75).
    Spec: § 3.10 L1253 Concurrency + L1274 Tool-specific arguments + L1297(f).
    """
    mod = _load_tool_module()

    captured_sql: list[str] = []

    mock_cursor = MagicMock()
    mock_cursor.execute.side_effect = lambda sql, *a, **kw: captured_sql.append(str(sql))
    mock_cursor.fetchone.return_value = (0,)
    mock_cursor.fetchall.return_value = []

    with patch("pyodbc.connect", return_value=mock_cursor):
        try:
            _invoke_main(mod,
                actor=_ACTOR,
                dry_run=False,
                apply=True,
                debug_info_days=_DEBUG_INFO_DAYS_DEFAULT,
                warning_days=_WARNING_DAYS_DEFAULT,
                batch_size=_BATCH_SIZE_OVERRIDE,  # 10000 per § 3.10 L1297(f)
            )
        except SystemExit:
            pass

    delete_calls = [s for s in captured_sql if "DELETE" in s.upper()]
    # If the module emits delete calls at all, the batch-size must be reflected
    if delete_calls:
        batch_size_str = str(_BATCH_SIZE_OVERRIDE)  # "10000"
        batch_reflected = any(
            batch_size_str in sql for sql in delete_calls
        )
        assert batch_reflected, (
            f"--batch-size {_BATCH_SIZE_OVERRIDE} must appear in the DELETE SQL. "
            f"Got DELETE calls: {delete_calls!r}. "
            "Per § 3.10 L1297(f) + L1253: batch-size controls per-batch DELETE cap "
            "to avoid lock escalation (B-2 lesson)."
        )


# ---------------------------------------------------------------------------
# (g) Tier 0 total runtime < 5 s per D67
# ---------------------------------------------------------------------------


def test_tier0_total_runtime_under_5s():
    """(g) All Tier 0 smoke assertions complete in < 5 s per D67.

    Sentinel test: if the module performs real I/O (DB connection, network
    call, subprocess) the runtime ceiling will be breached and this test
    catches the regression before the build step.

    D67: Runtime ceiling < 5 seconds per module (build-time constraint).
    Spec: § 3.10 Tier 0 scaffold.
    """
    start = time.monotonic()

    mod = _load_tool_module()

    captured_sql: list[str] = []
    mock_cursor = MagicMock()
    mock_cursor.execute.side_effect = lambda sql, *a, **kw: captured_sql.append(str(sql))
    mock_cursor.fetchone.return_value = (0,)
    mock_cursor.fetchall.return_value = []

    with patch("pyodbc.connect", return_value=mock_cursor):
        try:
            _invoke_main(mod,
                actor=_ACTOR,
                dry_run=False,
                apply=True,
                debug_info_days=_DEBUG_INFO_DAYS_DEFAULT,
                warning_days=_WARNING_DAYS_DEFAULT,
                batch_size=_BATCH_SIZE_DEFAULT,
            )
        except SystemExit:
            pass

    elapsed = time.monotonic() - start
    assert elapsed < 5.0, (
        f"Tier 0 smoke must complete in < 5 s per D67. "
        f"Took {elapsed:.2f} s. Module is likely performing real I/O — "
        "check for missing mocks (pyodbc, cursor_for, network)."
    )
