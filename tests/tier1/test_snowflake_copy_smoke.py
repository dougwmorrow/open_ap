"""Tier 1 comprehensive unit tests for ``tools/snowflake_copy_smoke.py``.

Per D67 Tier 1 discipline — broader coverage than Tier 0 smoke. Tests
public surface, argparse details, actor detection, dry-run / apply
paths, all error classifications, audit-row contract, JSON output,
B228 utils.errors single-source-of-truth import.

Test classes (8 + ancillaries):

* TestModuleSurface — public exports match expected.
* TestArgParser — argparse coverage (mutex --dry-run/--apply,
  --registry-id required, type coercion).
* TestActorDetection — AUTOMIC_RUN_ID -> 'automic'; isatty ->
  'operator'; else 'pipeline'.
* TestDryRunPath — does NOT call copy_fn; emits "would copy"; exit 0.
* TestApplyPath — calls copy_fn with kwargs; success -> exit 0; result
  fields surface.
* TestErrorPaths — every canonical exception class -> correct exit code.
* TestAuditRow — one row written; metadata JSON shape per D76;
  audit-write failure doesn't change exit code.
* TestJsonOutput — --json prints valid JSON with expected keys.
* TestB228UtilsErrorsImport — script imports exceptions from
  utils.errors (NOT local).

D-numbers: D67 (Tier 1 discipline), D68 (canonical exception
hierarchy), D74 (exit codes 0/1/2), D75 (arg naming, dry-run default),
D76 (audit-row contract), D77 (Tier 0 scaffold sibling), D92
(forward-only additive), D103 (Claude Code security).

Spec: M17 ``data_load/snowflake_uploader.py`` (Round 3 § 7.1).
"""
from __future__ import annotations

import importlib
import importlib.util
import io
import json
import os
import sys
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_copy_result(
    *,
    registry_id: int = 12345,
    snowflake_table: str = "UDM_BRONZE_MIRROR.DNA.ACCT",
    rows_copied: int = 100_000,
    copy_history_id: str = "01abcdef-0000-0000-0000-000000000000",
    duration_ms: int = 1234,
) -> Any:
    return SimpleNamespace(
        registry_id=registry_id,
        snowflake_table=snowflake_table,
        rows_copied=rows_copied,
        copy_history_id=copy_history_id,
        duration_ms=duration_ms,
    )


def _load_tool_module() -> Any:
    """Reload the tool with mocked sibling imports."""
    if _TOOL_MODULE_KEY in sys.modules:
        del sys.modules[_TOOL_MODULE_KEY]

    mock_snowflake_uploader = MagicMock()
    mock_snowflake_uploader.copy_parquet_to_snowflake = MagicMock(
        return_value=_make_copy_result()
    )

    mock_cursor = MagicMock()
    mock_cursor.fetchone.return_value = (777,)
    mock_cursor.description = [("AuditEventId",)]
    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_connections = MagicMock()
    mock_connections.get_connection = MagicMock(return_value=mock_conn)

    mock_pyodbc = MagicMock()
    mock_pyodbc.connect = MagicMock(return_value=mock_conn)

    sys_modules_patch = {
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
    mod._test_conn = mock_conn
    mod._test_sys_modules_patch = sys_modules_patch
    return mod


def _build_args(
    *,
    registry_id: int = 12345,
    snowflake_table: str | None = None,
    copy_timeout: int = 300,
    apply: bool = False,
    dry_run: bool = False,
    json_output: bool = False,
    verbose: bool = False,
    quiet: bool = True,
    actor: str | None = "test-tier1",
    no_audit_event: bool = True,
) -> SimpleNamespace:
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
# TestModuleSurface — public exports + constants
# ===========================================================================


class TestModuleSurface:
    """Verify public surface matches CLAUDE.md / GLOSSARY registration."""

    def test_public_callables_exposed(self):
        mod = _load_tool_module()
        assert callable(mod.main), "main() must be callable"
        assert callable(mod.cli_main), "cli_main() must be callable"
        assert callable(mod._build_parser), "_build_parser() must be callable"

    def test_canonical_event_type(self):
        mod = _load_tool_module()
        assert mod.EVENT_TYPE == "CLI_SNOWFLAKE_COPY_SMOKE", (
            "EVENT_TYPE must be CLI_SNOWFLAKE_COPY_SMOKE per D76"
        )

    def test_canonical_exit_codes(self):
        mod = _load_tool_module()
        assert mod.EXIT_SUCCESS == 0
        assert mod.EXIT_OPERATIONAL_FAILURE == 1
        assert mod.EXIT_FATAL == 2

    def test_detect_actor_callable(self):
        mod = _load_tool_module()
        assert callable(mod._detect_actor), "_detect_actor must be exposed"

    def test_classify_exception_callable(self):
        mod = _load_tool_module()
        assert callable(mod._classify_exception), (
            "_classify_exception helper must be exposed"
        )


# ===========================================================================
# TestArgParser — argparse coverage
# ===========================================================================


class TestArgParser:
    """argparse contract per D75 + spec § 1.4."""

    def test_registry_id_required(self):
        mod = _load_tool_module()
        parser = mod._build_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args([])
        # argparse exits with code 2 on missing required arg.
        assert exc_info.value.code == 2

    def test_registry_id_type_coercion(self):
        mod = _load_tool_module()
        parser = mod._build_parser()
        args = parser.parse_args(["--registry-id", "12345"])
        assert args.registry_id == 12345
        assert isinstance(args.registry_id, int)

    def test_apply_dry_run_mutex(self):
        """--apply and --dry-run are mutually exclusive per B88 pattern."""
        mod = _load_tool_module()
        parser = mod._build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--registry-id", "1", "--apply", "--dry-run"])

    def test_apply_default_false(self):
        """--apply defaults to False (DRY-RUN is default per D75)."""
        mod = _load_tool_module()
        parser = mod._build_parser()
        args = parser.parse_args(["--registry-id", "1"])
        assert args.apply is False

    def test_dry_run_default_false_flag(self):
        """--dry-run flag defaults to False — but mode is dry-run by default."""
        mod = _load_tool_module()
        parser = mod._build_parser()
        args = parser.parse_args(["--registry-id", "1"])
        # The flag defaults to False but the EFFECTIVE mode is dry-run
        # (computed in main() as: is_dry_run = not apply).
        assert args.dry_run is False
        assert args.apply is False

    def test_snowflake_table_default_none(self):
        mod = _load_tool_module()
        parser = mod._build_parser()
        args = parser.parse_args(["--registry-id", "1"])
        assert args.snowflake_table is None

    def test_snowflake_table_override(self):
        mod = _load_tool_module()
        parser = mod._build_parser()
        args = parser.parse_args(
            ["--registry-id", "1", "--snowflake-table", "DB.SCHEMA.TBL"]
        )
        assert args.snowflake_table == "DB.SCHEMA.TBL"

    def test_copy_timeout_default(self):
        mod = _load_tool_module()
        parser = mod._build_parser()
        args = parser.parse_args(["--registry-id", "1"])
        assert args.copy_timeout == 300

    def test_copy_timeout_override(self):
        mod = _load_tool_module()
        parser = mod._build_parser()
        args = parser.parse_args(
            ["--registry-id", "1", "--copy-timeout", "60"]
        )
        assert args.copy_timeout == 60

    def test_json_output_flag(self):
        mod = _load_tool_module()
        parser = mod._build_parser()
        args = parser.parse_args(["--registry-id", "1", "--json"])
        assert args.json_output is True

    def test_no_audit_event_flag(self):
        mod = _load_tool_module()
        parser = mod._build_parser()
        args = parser.parse_args(["--registry-id", "1", "--no-audit-event"])
        assert args.no_audit_event is True

    def test_verbose_quiet_flags(self):
        mod = _load_tool_module()
        parser = mod._build_parser()
        args_v = parser.parse_args(["--registry-id", "1", "--verbose"])
        assert args_v.verbose is True
        args_q = parser.parse_args(["--registry-id", "1", "--quiet"])
        assert args_q.quiet is True


# ===========================================================================
# TestActorDetection — § 1.7 heuristic
# ===========================================================================


class TestActorDetection:
    """Actor-string heuristic order: AUTOMIC_RUN_ID > isatty > pipeline."""

    def test_automic_run_id_yields_automic(self, monkeypatch):
        mod = _load_tool_module()
        monkeypatch.setenv("AUTOMIC_RUN_ID", "RUN-12345")
        assert mod._detect_actor() == "automic"

    def test_isatty_yields_operator(self, monkeypatch):
        mod = _load_tool_module()
        monkeypatch.delenv("AUTOMIC_RUN_ID", raising=False)
        with patch.object(sys.stdin, "isatty", return_value=True):
            assert mod._detect_actor() == "operator"

    def test_no_tty_no_env_yields_pipeline(self, monkeypatch):
        mod = _load_tool_module()
        monkeypatch.delenv("AUTOMIC_RUN_ID", raising=False)
        with patch.object(sys.stdin, "isatty", return_value=False):
            assert mod._detect_actor() == "pipeline"

    def test_isatty_attribute_error_falls_through(self, monkeypatch):
        """If isatty raises (closed file), fall through to 'pipeline'."""
        mod = _load_tool_module()
        monkeypatch.delenv("AUTOMIC_RUN_ID", raising=False)
        with patch.object(
            sys.stdin, "isatty", side_effect=ValueError("closed")
        ):
            assert mod._detect_actor() == "pipeline"


# ===========================================================================
# TestDryRunPath — does NOT call copy_fn
# ===========================================================================


class TestDryRunPath:
    """Dry-run path semantics: no M17 call, audit row optional."""

    def test_default_apply_false_is_dry_run(self):
        mod = _load_tool_module()
        copy_mock = MagicMock(return_value=_make_copy_result())
        with patch.dict("sys.modules", mod._test_sys_modules_patch):
            exit_code = mod.main(
                args=_build_args(apply=False),
                copy_fn=copy_mock,
            )
        assert exit_code == 0
        assert copy_mock.call_count == 0

    def test_explicit_dry_run_flag_also_skips_call(self):
        mod = _load_tool_module()
        copy_mock = MagicMock(return_value=_make_copy_result())
        # apply=False, dry_run=True is also dry-run.
        with patch.dict("sys.modules", mod._test_sys_modules_patch):
            exit_code = mod.main(
                args=_build_args(apply=False, dry_run=True),
                copy_fn=copy_mock,
            )
        assert exit_code == 0
        assert copy_mock.call_count == 0

    def test_dry_run_prints_preview_block(self, capsys):
        mod = _load_tool_module()
        with patch.dict("sys.modules", mod._test_sys_modules_patch):
            mod.main(
                args=_build_args(apply=False, quiet=False),
                copy_fn=MagicMock(),
            )
        out = capsys.readouterr().out
        assert "DRY RUN PREVIEW" in out
        assert "RegistryId" in out
        assert "12345" in out
        assert "--apply" in out  # operator hint

    def test_dry_run_with_snowflake_table_override_surfaces_target(
        self, capsys
    ):
        mod = _load_tool_module()
        with patch.dict("sys.modules", mod._test_sys_modules_patch):
            mod.main(
                args=_build_args(
                    apply=False,
                    quiet=False,
                    snowflake_table="MYDB.MYSCH.MYTBL",
                ),
                copy_fn=MagicMock(),
            )
        out = capsys.readouterr().out
        assert "MYDB.MYSCH.MYTBL" in out

    def test_dry_run_apply_mutex_check_in_main(self):
        """If both apply + dry_run somehow reach main(), exit 2."""
        mod = _load_tool_module()
        # We bypass argparse mutex by constructing the namespace directly.
        args = _build_args(apply=True, dry_run=True)
        with patch.dict("sys.modules", mod._test_sys_modules_patch):
            exit_code = mod.main(args=args, copy_fn=MagicMock())
        assert exit_code == 2


# ===========================================================================
# TestApplyPath — calls copy_fn with kwargs
# ===========================================================================


class TestApplyPath:
    """Apply path semantics: M17 invoked with kwargs; result surfaces."""

    def test_apply_invokes_copy_fn_with_kwargs(self):
        mod = _load_tool_module()
        copy_mock = MagicMock(return_value=_make_copy_result())
        with patch.dict("sys.modules", mod._test_sys_modules_patch):
            mod.main(
                args=_build_args(
                    apply=True,
                    registry_id=999,
                    snowflake_table="X.Y.Z",
                    copy_timeout=120,
                ),
                copy_fn=copy_mock,
            )
        assert copy_mock.call_count == 1
        # Verify keyword args per M17 signature
        kwargs = copy_mock.call_args.kwargs
        assert kwargs["registry_id"] == 999
        assert kwargs["snowflake_table"] == "X.Y.Z"
        assert kwargs["timeout_seconds"] == 120

    def test_apply_success_prints_result_fields(self, capsys):
        mod = _load_tool_module()
        result = _make_copy_result(
            rows_copied=42, duration_ms=999,
            copy_history_id="DEADBEEF-1234",
        )
        with patch.dict("sys.modules", mod._test_sys_modules_patch):
            exit_code = mod.main(
                args=_build_args(apply=True, quiet=False),
                copy_fn=MagicMock(return_value=result),
            )
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "SUCCESS" in out
        assert "42" in out
        assert "999" in out
        assert "DEADBEEF-1234" in out

    def test_apply_with_default_snowflake_table_passes_none(self):
        """snowflake_table=None means M17 uses its default mapping."""
        mod = _load_tool_module()
        copy_mock = MagicMock(return_value=_make_copy_result())
        with patch.dict("sys.modules", mod._test_sys_modules_patch):
            mod.main(
                args=_build_args(apply=True, snowflake_table=None),
                copy_fn=copy_mock,
            )
        assert copy_mock.call_args.kwargs["snowflake_table"] is None

    def test_apply_uses_default_copy_fn_resolver_when_omitted(self):
        """When copy_fn=None, _get_copy_parquet_to_snowflake() resolves M17."""
        mod = _load_tool_module()
        # The mocked M17 module's copy_parquet_to_snowflake should be called.
        with patch.dict("sys.modules", mod._test_sys_modules_patch):
            exit_code = mod.main(
                args=_build_args(apply=True),
                copy_fn=None,  # default — should resolve via getter
            )
        assert exit_code == 0
        assert (
            mod._test_snowflake_uploader.copy_parquet_to_snowflake.call_count
            == 1
        )


# ===========================================================================
# TestErrorPaths — exception classification matrix
# ===========================================================================


class TestErrorPaths:
    """Every canonical exception class -> correct exit code per D68 + D74."""

    def test_registry_not_found_yields_two(self):
        mod = _load_tool_module()
        from utils.errors import RegistryNotFound

        copy_mock = MagicMock(side_effect=RegistryNotFound(
            "registry_id 999 not found",
            metadata={"registry_id": 999},
        ))
        with patch.dict("sys.modules", mod._test_sys_modules_patch):
            exit_code = mod.main(
                args=_build_args(apply=True),
                copy_fn=copy_mock,
            )
        assert exit_code == 2

    def test_registry_status_invalid_yields_two(self):
        mod = _load_tool_module()
        from utils.errors import RegistryStatusInvalid

        copy_mock = MagicMock(side_effect=RegistryStatusInvalid(
            "wrong status",
            metadata={"registry_id": 1, "current_status": "created"},
        ))
        with patch.dict("sys.modules", mod._test_sys_modules_patch):
            exit_code = mod.main(
                args=_build_args(apply=True),
                copy_fn=copy_mock,
            )
        assert exit_code == 2

    def test_snowflake_auth_failed_yields_two(self):
        mod = _load_tool_module()
        from utils.errors import SnowflakeAuthFailed

        copy_mock = MagicMock(side_effect=SnowflakeAuthFailed(
            "RSA decrypt failed",
            metadata={"registry_id": 1},
        ))
        with patch.dict("sys.modules", mod._test_sys_modules_patch):
            exit_code = mod.main(
                args=_build_args(apply=True),
                copy_fn=copy_mock,
            )
        assert exit_code == 2

    def test_snowflake_budget_alert_yields_two(self):
        mod = _load_tool_module()
        from utils.errors import SnowflakeBudgetAlert

        copy_mock = MagicMock(side_effect=SnowflakeBudgetAlert(
            "82% of monthly cap",
            metadata={"usage_pct": 0.82},
        ))
        with patch.dict("sys.modules", mod._test_sys_modules_patch):
            exit_code = mod.main(
                args=_build_args(apply=True),
                copy_fn=copy_mock,
            )
        assert exit_code == 2

    def test_snowflake_copy_timeout_yields_one(self):
        """Retryable error -> exit 1."""
        mod = _load_tool_module()
        from utils.errors import SnowflakeCopyTimeout

        copy_mock = MagicMock(side_effect=SnowflakeCopyTimeout(
            "exceeded 300s",
            metadata={"timeout_seconds": 300},
        ))
        with patch.dict("sys.modules", mod._test_sys_modules_patch):
            exit_code = mod.main(
                args=_build_args(apply=True),
                copy_fn=copy_mock,
            )
        assert exit_code == 1

    def test_vault_unavailable_yields_one(self):
        """Retryable error -> exit 1."""
        mod = _load_tool_module()
        from utils.errors import VaultUnavailable

        copy_mock = MagicMock(side_effect=VaultUnavailable(
            "vault DB down",
            metadata={},
        ))
        with patch.dict("sys.modules", mod._test_sys_modules_patch):
            exit_code = mod.main(
                args=_build_args(apply=True),
                copy_fn=copy_mock,
            )
        assert exit_code == 1

    def test_credentials_load_error_yields_two(self):
        mod = _load_tool_module()
        from utils.errors import CredentialsLoadError

        copy_mock = MagicMock(side_effect=CredentialsLoadError(
            "gpg decrypt failed",
            metadata={},
        ))
        with patch.dict("sys.modules", mod._test_sys_modules_patch):
            exit_code = mod.main(
                args=_build_args(apply=True),
                copy_fn=copy_mock,
            )
        assert exit_code == 2

    def test_generic_exception_yields_two(self):
        """Untyped exceptions default to FATAL (safer)."""
        mod = _load_tool_module()
        copy_mock = MagicMock(side_effect=RuntimeError("unexpected"))
        with patch.dict("sys.modules", mod._test_sys_modules_patch):
            exit_code = mod.main(
                args=_build_args(apply=True),
                copy_fn=copy_mock,
            )
        assert exit_code == 2

    def test_pipeline_retryable_error_yields_one(self):
        """Generic PipelineRetryableError -> exit 1."""
        mod = _load_tool_module()
        from utils.errors import PipelineRetryableError

        copy_mock = MagicMock(side_effect=PipelineRetryableError(
            "transient",
            metadata={},
        ))
        with patch.dict("sys.modules", mod._test_sys_modules_patch):
            exit_code = mod.main(
                args=_build_args(apply=True),
                copy_fn=copy_mock,
            )
        assert exit_code == 1

    def test_pipeline_fatal_error_yields_two(self):
        """Generic PipelineFatalError -> exit 2."""
        mod = _load_tool_module()
        from utils.errors import PipelineFatalError

        copy_mock = MagicMock(side_effect=PipelineFatalError(
            "fatal generic",
            metadata={},
        ))
        with patch.dict("sys.modules", mod._test_sys_modules_patch):
            exit_code = mod.main(
                args=_build_args(apply=True),
                copy_fn=copy_mock,
            )
        assert exit_code == 2

    def test_keyboard_interrupt_yields_one(self):
        """KeyboardInterrupt -> exit 1 (operational)."""
        mod = _load_tool_module()
        copy_mock = MagicMock(side_effect=KeyboardInterrupt())
        with patch.dict("sys.modules", mod._test_sys_modules_patch):
            exit_code = mod.main(
                args=_build_args(apply=True),
                copy_fn=copy_mock,
            )
        assert exit_code == 1

    def test_failure_prints_to_stderr(self, capsys):
        mod = _load_tool_module()
        from utils.errors import RegistryStatusInvalid

        copy_mock = MagicMock(side_effect=RegistryStatusInvalid(
            "wrong status",
            metadata={},
        ))
        with patch.dict("sys.modules", mod._test_sys_modules_patch):
            mod.main(
                args=_build_args(apply=True, quiet=False),
                copy_fn=copy_mock,
            )
        err = capsys.readouterr().err
        assert "FATAL" in err
        assert "RegistryStatusInvalid" in err


# ===========================================================================
# TestAuditRow — D76 contract
# ===========================================================================


class TestAuditRow:
    """D76 audit-row contract — exactly one row per invocation."""

    def test_audit_row_written_on_success(self):
        mod = _load_tool_module()

        rows_captured: list[Any] = []

        def factory():
            conn = MagicMock()
            cursor = MagicMock()
            cursor.fetchone.return_value = (12345,)
            cursor.description = [("AuditEventId",)]

            def capture_execute(sql, *args):
                rows_captured.append((sql, args))

            cursor.execute.side_effect = capture_execute
            conn.cursor.return_value = cursor
            return conn

        with patch.dict("sys.modules", mod._test_sys_modules_patch):
            exit_code = mod.main(
                args=_build_args(apply=True, no_audit_event=False),
                copy_fn=MagicMock(return_value=_make_copy_result()),
                audit_cursor_factory=factory,
            )
        assert exit_code == 0
        # Exactly one INSERT was executed.
        assert len(rows_captured) == 1
        sql, args = rows_captured[0]
        assert "PipelineEventLog" in sql
        # EventType is the first parameter
        assert args[0] == "CLI_SNOWFLAKE_COPY_SMOKE"

    def test_audit_row_written_on_failure(self):
        mod = _load_tool_module()
        from utils.errors import RegistryNotFound

        rows_captured: list[Any] = []

        def factory():
            conn = MagicMock()
            cursor = MagicMock()
            cursor.fetchone.return_value = (456,)
            cursor.description = [("AuditEventId",)]

            def capture(sql, *args):
                rows_captured.append((sql, args))

            cursor.execute.side_effect = capture
            conn.cursor.return_value = cursor
            return conn

        with patch.dict("sys.modules", mod._test_sys_modules_patch):
            exit_code = mod.main(
                args=_build_args(apply=True, no_audit_event=False),
                copy_fn=MagicMock(
                    side_effect=RegistryNotFound("absent", metadata={})
                ),
                audit_cursor_factory=factory,
            )
        assert exit_code == 2
        assert len(rows_captured) == 1
        # Status field is the 4th positional param (after EventType + EventDetail + StartedAt)
        _, args = rows_captured[0]
        assert args[3] == "FAILED"

    def test_audit_row_skipped_when_no_audit_event(self):
        mod = _load_tool_module()
        factory = MagicMock()
        with patch.dict("sys.modules", mod._test_sys_modules_patch):
            mod.main(
                args=_build_args(apply=True, no_audit_event=True),
                copy_fn=MagicMock(return_value=_make_copy_result()),
                audit_cursor_factory=factory,
            )
        # factory must NOT be called when no_audit_event=True
        assert factory.call_count == 0

    def test_audit_row_metadata_json_contains_required_keys(self):
        mod = _load_tool_module()

        captured_metadata: list[str] = []

        def factory():
            conn = MagicMock()
            cursor = MagicMock()
            cursor.fetchone.return_value = (1,)
            cursor.description = [("AuditEventId",)]

            def capture(sql, *args):
                # Metadata JSON is the last parameter
                captured_metadata.append(args[-1])

            cursor.execute.side_effect = capture
            conn.cursor.return_value = cursor
            return conn

        with patch.dict("sys.modules", mod._test_sys_modules_patch):
            mod.main(
                args=_build_args(apply=True, no_audit_event=False),
                copy_fn=MagicMock(return_value=_make_copy_result()),
                audit_cursor_factory=factory,
            )
        assert len(captured_metadata) == 1
        metadata = json.loads(captured_metadata[0])
        # Required keys per D76 contract
        for key in [
            "event_kind",
            "actor",
            "registry_id",
            "snowflake_table",
            "copy_timeout_seconds",
            "dry_run",
            "rows_copied",
            "copy_history_id",
            "duration_ms",
            "exit_code",
            "started_at",
            "completed_at",
        ]:
            assert key in metadata, (
                f"D76 Metadata JSON missing required key: {key!r}"
            )
        assert metadata["event_kind"] == "invoke"
        assert metadata["dry_run"] is False
        assert metadata["exit_code"] == 0

    def test_audit_row_failure_does_not_change_exit_code(self):
        """Audit-write failure -> exit code stays SUCCESS per D76 best-effort."""
        mod = _load_tool_module()

        def factory():
            raise RuntimeError("audit DB down")

        with patch.dict("sys.modules", mod._test_sys_modules_patch):
            exit_code = mod.main(
                args=_build_args(apply=True, no_audit_event=False),
                copy_fn=MagicMock(return_value=_make_copy_result()),
                audit_cursor_factory=factory,
            )
        # Verdict exit code is authoritative — audit-write failure does
        # NOT propagate to exit code (D76 best-effort discipline).
        assert exit_code == 0

    def test_dry_run_also_writes_audit_row(self):
        """Dry-run path STILL writes one audit row per D76 contract."""
        mod = _load_tool_module()

        rows_captured: list[Any] = []

        def factory():
            conn = MagicMock()
            cursor = MagicMock()
            cursor.fetchone.return_value = (9,)
            cursor.description = [("AuditEventId",)]

            def capture(sql, *args):
                rows_captured.append((sql, args))

            cursor.execute.side_effect = capture
            conn.cursor.return_value = cursor
            return conn

        with patch.dict("sys.modules", mod._test_sys_modules_patch):
            mod.main(
                args=_build_args(apply=False, no_audit_event=False),
                copy_fn=MagicMock(),
                audit_cursor_factory=factory,
            )
        assert len(rows_captured) == 1


# ===========================================================================
# TestJsonOutput — --json contract
# ===========================================================================


class TestJsonOutput:
    """--json emits valid JSON with the canonical payload shape."""

    def test_json_output_success_is_valid(self, capsys):
        mod = _load_tool_module()
        with patch.dict("sys.modules", mod._test_sys_modules_patch):
            mod.main(
                args=_build_args(apply=True, json_output=True, quiet=False),
                copy_fn=MagicMock(return_value=_make_copy_result(
                    rows_copied=99, duration_ms=88
                )),
            )
        out = capsys.readouterr().out
        # Output must be valid JSON
        payload = json.loads(out)
        assert payload["rows_copied"] == 99
        assert payload["duration_ms"] == 88
        assert payload["exit_code"] == 0
        assert payload["event_kind"] == "invoke"

    def test_json_output_dry_run_is_valid(self, capsys):
        mod = _load_tool_module()
        with patch.dict("sys.modules", mod._test_sys_modules_patch):
            mod.main(
                args=_build_args(apply=False, json_output=True, quiet=False),
                copy_fn=MagicMock(),
            )
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload["dry_run"] is True
        assert payload["exit_code"] == 0
        assert payload["rows_copied"] is None

    def test_json_output_failure_is_valid(self, capsys):
        mod = _load_tool_module()
        from utils.errors import RegistryNotFound

        with patch.dict("sys.modules", mod._test_sys_modules_patch):
            mod.main(
                args=_build_args(apply=True, json_output=True, quiet=False),
                copy_fn=MagicMock(
                    side_effect=RegistryNotFound("absent", metadata={})
                ),
            )
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert payload["error_class"] == "RegistryNotFound"
        assert payload["exit_code"] == 2

    def test_json_output_contains_audit_event_id_key(self, capsys):
        """--json with audit row written -> audit_event_id surfaces."""
        mod = _load_tool_module()

        def factory():
            conn = MagicMock()
            cursor = MagicMock()
            cursor.fetchone.return_value = (4242,)
            cursor.description = [("AuditEventId",)]
            cursor.execute = MagicMock()
            conn.cursor.return_value = cursor
            return conn

        with patch.dict("sys.modules", mod._test_sys_modules_patch):
            mod.main(
                args=_build_args(
                    apply=True, json_output=True,
                    quiet=False, no_audit_event=False,
                ),
                copy_fn=MagicMock(return_value=_make_copy_result()),
                audit_cursor_factory=factory,
            )
        out = capsys.readouterr().out
        payload = json.loads(out)
        assert "audit_event_id" in payload
        assert payload["audit_event_id"] == 4242


# ===========================================================================
# TestB228UtilsErrorsImport — canonical exception import
# ===========================================================================


class TestB228UtilsErrorsImport:
    """B228: tools must import exception classes from utils.errors (NOT local)."""

    def test_module_imports_utils_errors_at_module_level(self):
        """Module loads utils.errors without raising."""
        # Force re-import to verify the import path works.
        if _TOOL_MODULE_KEY in sys.modules:
            del sys.modules[_TOOL_MODULE_KEY]
        # No mocks — let the canonical utils.errors load.
        spec = importlib.util.spec_from_file_location(
            _TOOL_MODULE_KEY, _TOOL_PATH
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[_TOOL_MODULE_KEY] = mod
        spec.loader.exec_module(mod)
        # Verify the canonical classes are bound in the module namespace
        for name in [
            "PipelineFatalError",
            "PipelineRetryableError",
            "RegistryNotFound",
            "RegistryStatusInvalid",
            "SnowflakeAuthFailed",
            "SnowflakeBudgetAlert",
            "SnowflakeCopyTimeout",
            "VaultUnavailable",
            "CredentialsLoadError",
        ]:
            assert hasattr(mod, name), (
                f"B228 — utils.errors.{name} must be bound in tool namespace"
            )

    def test_classes_are_canonical_utils_errors_classes(self):
        """The classes bound in the tool match those in utils.errors."""
        if _TOOL_MODULE_KEY in sys.modules:
            del sys.modules[_TOOL_MODULE_KEY]
        spec = importlib.util.spec_from_file_location(
            _TOOL_MODULE_KEY, _TOOL_PATH
        )
        mod = importlib.util.module_from_spec(spec)
        sys.modules[_TOOL_MODULE_KEY] = mod
        spec.loader.exec_module(mod)

        import utils.errors as canonical
        assert mod.RegistryNotFound is canonical.RegistryNotFound, (
            "B228 — RegistryNotFound must be the canonical class"
        )
        assert mod.SnowflakeAuthFailed is canonical.SnowflakeAuthFailed, (
            "B228 — SnowflakeAuthFailed must be the canonical class"
        )

    def test_classify_exception_matches_d68_tier_separation(self):
        """Retryable subclasses -> exit 1; Fatal subclasses -> exit 2."""
        mod = _load_tool_module()
        from utils.errors import (
            SnowflakeCopyTimeout,
            VaultUnavailable,
            RegistryNotFound,
            RegistryStatusInvalid,
            SnowflakeAuthFailed,
            SnowflakeBudgetAlert,
            CredentialsLoadError,
        )

        # Retryable -> exit 1
        assert mod._classify_exception(
            SnowflakeCopyTimeout("x", metadata={})
        ) == 1
        assert mod._classify_exception(
            VaultUnavailable("x", metadata={})
        ) == 1

        # Fatal -> exit 2
        assert mod._classify_exception(
            RegistryNotFound("x", metadata={})
        ) == 2
        assert mod._classify_exception(
            RegistryStatusInvalid("x", metadata={})
        ) == 2
        assert mod._classify_exception(
            SnowflakeAuthFailed("x", metadata={})
        ) == 2
        assert mod._classify_exception(
            SnowflakeBudgetAlert("x", metadata={})
        ) == 2
        assert mod._classify_exception(
            CredentialsLoadError("x", metadata={})
        ) == 2

        # Generic -> exit 2 (safer default)
        assert mod._classify_exception(RuntimeError("x")) == 2


# ===========================================================================
# TestCliMain — argv entry point
# ===========================================================================


class TestCliMain:
    """cli_main() argv-to-exit-code wiring."""

    def test_help_returns_zero(self):
        mod = _load_tool_module()
        exit_code = mod.cli_main(["--help"])
        assert exit_code == 0

    def test_missing_required_arg_returns_two(self):
        mod = _load_tool_module()
        exit_code = mod.cli_main([])
        assert exit_code == 2

    def test_mutex_violation_returns_two(self):
        mod = _load_tool_module()
        exit_code = mod.cli_main(
            ["--registry-id", "1", "--apply", "--dry-run"]
        )
        assert exit_code == 2

    def test_dry_run_default_via_cli_returns_zero(self):
        mod = _load_tool_module()
        # cli_main with only --registry-id -> default dry-run -> exit 0.
        # The M17 mock is bound in sys.modules so the resolver finds it.
        with patch.dict("sys.modules", mod._test_sys_modules_patch):
            exit_code = mod.cli_main(
                ["--registry-id", "999", "--no-audit-event", "--quiet"]
            )
        assert exit_code == 0


# ===========================================================================
# TestTimeHelpers — ms-precision naive-UTC invariant
# ===========================================================================


class TestTimeHelpers:
    """SCD2-P1-f / CDC-NOW-MS naive-UTC ms-precision invariant."""

    def test_now_naive_ms_returns_naive_datetime(self):
        mod = _load_tool_module()
        dt = mod._now_naive_ms()
        assert dt.tzinfo is None, (
            "datetime must be naive (no tzinfo) per SCD2-P1-f"
        )

    def test_now_naive_ms_truncates_to_millisecond(self):
        mod = _load_tool_module()
        dt = mod._now_naive_ms()
        # microsecond must be a multiple of 1000 (i.e. ms-precision).
        assert dt.microsecond % 1000 == 0, (
            "microsecond must be ms-truncated per BCP/pyodbc invariant"
        )

    def test_format_iso_naive_ms_renders_with_millis(self):
        mod = _load_tool_module()
        from datetime import datetime

        dt = datetime(2026, 5, 14, 10, 30, 45, 123000)
        formatted = mod._format_iso_naive_ms(dt)
        assert formatted == "2026-05-14T10:30:45.123Z"
