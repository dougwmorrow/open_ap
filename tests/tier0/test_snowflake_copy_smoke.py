"""Tier 0 build-time smoke test for ``tools/snowflake_copy_smoke.py``.

Per **D67** — runs at build time + every commit. Runtime ceiling < 5 s.
All external dependencies (M17 ``copy_parquet_to_snowflake``, audit-row
cursor) are mocked. No live DB, no live Snowflake required.

6-assertion D77 scaffold (descriptive names per B-266 lesson; B214
test-injection pattern via ``copy_fn`` + ``audit_cursor_factory`` kwargs):

  - test_module_imports — module imports without error; surface exposed.
  - test_help_exits_zero_with_nonempty_stdout — argparse ``--help`` works.
  - test_dry_run_default_exits_zero — default DRY-RUN does NOT call M17.
  - test_apply_without_registry_id_exits_two — argparse error -> exit 2.
  - test_apply_with_mock_success_returns_zero — M17 success -> exit 0.
  - test_apply_with_mock_pipeline_fatal_error_returns_two — fatal -> exit 2.

North Star pillars:
  - Audit-grade (D76): one ``CLI_SNOWFLAKE_COPY_SMOKE`` row per invoke.
  - Operationally stable (D67): < 5 s with zero external I/O.
  - Idempotent (D15): M17's COPY-INTO file-load history + M3
    ``mark_replicated`` no-op chain.
  - Traceability (D26): every invocation writes audit row.

D-numbers: D5, D15, D26, D67 (Tier 0 discipline), D68 (canonical
exception hierarchy), D74 (exit-code 0/1/2), D75 (arg naming, dry-run
default), D76 (audit-row contract), D77 (Tier 0 scaffold), D92
(forward-only additive), D103 (Claude Code security).

Spec: M17 ``data_load/snowflake_uploader.py`` (Round 3 § 7.1) wrap.
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Project root on sys.path
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_TOOL_PATH = _PROJECT_ROOT / "tools" / "snowflake_copy_smoke.py"
_TOOL_MODULE_KEY = "tools.snowflake_copy_smoke"

# Constants — single source of truth
EXPECTED_EVENT_TYPE = "CLI_SNOWFLAKE_COPY_SMOKE"
EXIT_SUCCESS = 0
EXIT_OPERATIONAL_FAILURE = 1
EXIT_FATAL = 2

_REGISTRY_ID_OK = 12345


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_copy_result(
    *,
    registry_id: int = _REGISTRY_ID_OK,
    snowflake_table: str = "UDM_BRONZE_MIRROR.DNA.ACCT",
    rows_copied: int = 100_000,
    copy_history_id: str = "01abcdef-0000-0000-0000-000000000000",
    duration_ms: int = 1234,
) -> Any:
    """Build a SnowflakeCopyResult-like SimpleNamespace."""
    return SimpleNamespace(
        registry_id=registry_id,
        snowflake_table=snowflake_table,
        rows_copied=rows_copied,
        copy_history_id=copy_history_id,
        duration_ms=duration_ms,
    )


def _load_tool_module() -> Any:
    """Load ``tools/snowflake_copy_smoke.py`` with external imports mocked.

    Mocks ``data_load.snowflake_uploader`` (so the module-level import
    chain doesn't try to reach pyodbc / snowflake-connector) +
    ``utils.connections`` (so the audit-row factory doesn't try to
    connect to General DB at import time).

    Canonical ``utils.errors`` classes are NOT mocked (B215 + B228).
    """
    if _TOOL_MODULE_KEY in sys.modules:
        del sys.modules[_TOOL_MODULE_KEY]

    # Mock M17 snowflake_uploader — copy_parquet_to_snowflake is what
    # the tool wraps.
    mock_snowflake_uploader = MagicMock()
    mock_snowflake_uploader.copy_parquet_to_snowflake = MagicMock(
        return_value=_make_copy_result()
    )

    # Mock utils.connections — audit-row factory.
    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = (42,)  # SCOPE_IDENTITY() value
    mock_cursor.description = [("AuditEventId",)]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_connections = MagicMock()
    mock_connections.get_connection = MagicMock(return_value=mock_conn)

    mock_pyodbc = MagicMock()
    mock_pyodbc.connect = MagicMock(return_value=mock_conn)

    sys_modules_patch: dict[str, Any] = {
        "data_load.snowflake_uploader": mock_snowflake_uploader,
        "utils.connections": mock_connections,
        "connections": mock_connections,
        "pyodbc": mock_pyodbc,
    }

    with patch.dict("sys.modules", sys_modules_patch):
        spec = importlib.util.spec_from_file_location(
            _TOOL_MODULE_KEY, _TOOL_PATH
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[_TOOL_MODULE_KEY] = mod
        spec.loader.exec_module(mod)

    mod._test_snowflake_uploader = mock_snowflake_uploader
    mod._test_cursor = mock_cursor
    mod._test_sys_modules_patch = sys_modules_patch
    return mod


def _build_args(
    *,
    registry_id: int = _REGISTRY_ID_OK,
    snowflake_table: str | None = None,
    copy_timeout: int = 300,
    apply: bool = False,
    dry_run: bool = False,
    json_output: bool = False,
    verbose: bool = False,
    quiet: bool = True,
    actor: str | None = "test-tier0",
    no_audit_event: bool = True,
) -> SimpleNamespace:
    """Build an argparse Namespace-like object for direct ``main()`` calls."""
    return SimpleNamespace(
        registry_id=registry_id,
        snowflake_table=snowflake_table,
        copy_timeout=copy_timeout,
        apply=apply,
        dry_run=dry_run,
        json_output=json_output,
        verbose=verbose,
        quiet=quiet,
        actor=actor,
        no_audit_event=no_audit_event,
    )


# ===========================================================================
# (1) Module imports without error
# ===========================================================================


def test_module_imports():
    """Module imports cleanly; required public surface exposed.

    Per D67 Tier 0 assertion 1 + D77 scaffold. Verifies no missing
    dependencies, no syntax errors, no import-time DB calls. Public
    surface (``main`` / ``cli_main`` / ``EVENT_TYPE`` / exit codes)
    must be accessible.

    North Star: Operationally stable. D67, D77.
    """
    mod = _load_tool_module()
    assert mod is not None, (
        "tools/snowflake_copy_smoke.py must load without error. D67."
    )
    assert hasattr(mod, "main"), "main() public surface required (D77)"
    assert hasattr(mod, "cli_main"), "cli_main() public surface required (D77)"
    assert mod.EVENT_TYPE == EXPECTED_EVENT_TYPE, (
        f"EVENT_TYPE must be {EXPECTED_EVENT_TYPE!r} per D76 CLI_* family. "
        f"Got: {mod.EVENT_TYPE!r}."
    )
    assert mod.EXIT_SUCCESS == EXIT_SUCCESS
    assert mod.EXIT_OPERATIONAL_FAILURE == EXIT_OPERATIONAL_FAILURE
    assert mod.EXIT_FATAL == EXIT_FATAL


# ===========================================================================
# (2) --help exits 0
# ===========================================================================


def test_help_exits_zero_with_nonempty_stdout(capsys):
    """``--help`` exits 0 and prints non-empty stdout.

    argparse always sys.exit(0) on --help. Verifies the CLI is wired up
    correctly and prints meaningful description.

    D74 (exit 0 = success / preview), D77.
    """
    mod = _load_tool_module()
    with pytest.raises(SystemExit) as exc_info:
        mod._build_parser().parse_args(["--help"])
    assert exc_info.value.code == 0, (
        f"--help must exit 0 per D74. Got: {exc_info.value.code!r}."
    )
    captured = capsys.readouterr()
    assert captured.out, "--help must print non-empty stdout per D77"
    # Spot-check the description mentions Snowflake.
    assert "Snowflake" in captured.out or "snowflake" in captured.out.lower(), (
        "Help text must mention Snowflake target system per D77."
    )


# ===========================================================================
# (3) Dry-run default does NOT call M17
# ===========================================================================


def test_dry_run_default_exits_zero():
    """Default DRY-RUN path does NOT call M17 ``copy_parquet_to_snowflake``.

    Per D75 dry-run-default safety for cost-sensitive operations
    (Snowflake credits). When neither ``--apply`` nor ``--dry-run`` is
    set, the tool must default to DRY-RUN and skip the M17 call.

    D75 (dry-run default), D77 scaffold. North Star: Operationally
    stable + audit-grade (audit row still written even in dry-run).
    """
    mod = _load_tool_module()
    sys_modules_patch = mod._test_sys_modules_patch

    with patch.dict("sys.modules", sys_modules_patch):
        args = _build_args(apply=False, dry_run=False)
        copy_mock = MagicMock(return_value=_make_copy_result())
        exit_code = mod.main(args=args, copy_fn=copy_mock)

    assert exit_code == EXIT_SUCCESS, (
        f"Default dry-run path must exit {EXIT_SUCCESS}. Got: {exit_code!r}."
    )
    assert copy_mock.call_count == 0, (
        f"Default dry-run must NOT call M17 copy_parquet_to_snowflake. "
        f"Got {copy_mock.call_count} calls. Per D75 + B88 mutex pattern."
    )


# ===========================================================================
# (4) --apply without --registry-id -> exit 2
# ===========================================================================


def test_apply_without_registry_id_exits_two():
    """``--apply`` without ``--registry-id`` -> argparse error -> exit 2.

    ``--registry-id`` is REQUIRED per the parser (``required=True``).
    argparse exits with code 2 on missing required arg; ``cli_main()``
    catches the SystemExit + maps non-zero to EXIT_FATAL.

    D74 (exit 2 = fatal / caller error), D77.
    """
    mod = _load_tool_module()
    exit_code = mod.cli_main(["--apply"])  # missing --registry-id
    assert exit_code == EXIT_FATAL, (
        f"--apply without --registry-id must exit {EXIT_FATAL} (fatal). "
        f"Got: {exit_code!r}."
    )


# ===========================================================================
# (5) --apply + mock success -> exit 0
# ===========================================================================


def test_apply_with_mock_success_returns_zero(capsys):
    """Mocked ``copy_fn`` returning ``SnowflakeCopyResult`` -> exit 0.

    Verifies the wrapper correctly classifies a successful M17 return
    and prints success output (RegistryId / rows / copy_history_id /
    duration_ms).

    D74 (exit 0 = success), D77.
    """
    mod = _load_tool_module()
    sys_modules_patch = mod._test_sys_modules_patch

    copy_result = _make_copy_result(rows_copied=42, duration_ms=999)
    copy_mock = MagicMock(return_value=copy_result)

    with patch.dict("sys.modules", sys_modules_patch):
        args = _build_args(apply=True, quiet=False)
        exit_code = mod.main(args=args, copy_fn=copy_mock)

    assert exit_code == EXIT_SUCCESS, (
        f"Mocked successful COPY must yield exit {EXIT_SUCCESS}. "
        f"Got: {exit_code!r}."
    )
    assert copy_mock.call_count == 1, (
        "Apply path must call M17 copy_parquet_to_snowflake exactly once."
    )
    captured = capsys.readouterr()
    # Spot-check stdout — operator-readable summary fields present.
    assert "42" in captured.out, "rows_copied must surface in stdout"
    assert "999" in captured.out, "duration_ms must surface in stdout"


# ===========================================================================
# (6) --apply + PipelineFatalError -> exit 2
# ===========================================================================


def test_apply_with_mock_pipeline_fatal_error_returns_two():
    """Mocked ``copy_fn`` raising ``PipelineFatalError`` -> exit 2.

    Per D68 + D74: PipelineFatalError subclasses (RegistryNotFound,
    RegistryStatusInvalid, SnowflakeAuthFailed, SnowflakeBudgetAlert)
    map to exit 2 (FATAL). Verifies the wrapper classifies the
    exception correctly.

    D68 (PipelineFatalError -> exit 2), D74, D77.
    """
    mod = _load_tool_module()
    sys_modules_patch = mod._test_sys_modules_patch

    from utils.errors import RegistryStatusInvalid

    err = RegistryStatusInvalid(
        f"RegistryId {_REGISTRY_ID_OK} Status='created' (test fixture)",
        metadata={
            "registry_id": _REGISTRY_ID_OK,
            "current_status": "created",
            "required_status": "verified",
        },
    )
    copy_mock = MagicMock(side_effect=err)

    with patch.dict("sys.modules", sys_modules_patch):
        args = _build_args(apply=True)
        exit_code = mod.main(args=args, copy_fn=copy_mock)

    assert exit_code == EXIT_FATAL, (
        f"PipelineFatalError must yield exit {EXIT_FATAL} (fatal). "
        f"Got: {exit_code!r}. Per D68 + D74: PipelineFatalError -> exit 2."
    )


# ===========================================================================
# Runtime ceiling assertion — Tier 0 must complete < 5 s (D67)
# ===========================================================================


def test_tier0_runtime_ceiling():
    """All Tier 0 invocations complete < 5 s (D67 ceiling).

    Verifies the smoke test itself does not incur external I/O.

    D67 (runtime ceiling < 5s per module).
    """
    start = time.monotonic()

    mod = _load_tool_module()
    sys_modules_patch = mod._test_sys_modules_patch

    with patch.dict("sys.modules", sys_modules_patch):
        mod.main(
            args=_build_args(apply=False, dry_run=False),
            copy_fn=MagicMock(return_value=_make_copy_result()),
        )
        mod.main(
            args=_build_args(apply=True),
            copy_fn=MagicMock(return_value=_make_copy_result()),
        )

    elapsed = time.monotonic() - start
    assert elapsed < 5.0, (
        f"Tier 0 mock invocations exceeded 5s ceiling: {elapsed:.2f}s. "
        "D67 mandates < 5s for Tier 0 smoke tests."
    )
