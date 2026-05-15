"""Tier 1 unit tests for ``data_load/snowflake_uploader.py``.

Tests run on every commit. No live Snowflake, no live DB, no live network
required. All external dependencies mocked with ``unittest.mock``.

North Star pillars addressed:
  - Idempotent (D15): re-COPY after success — Snowflake dedups by file
    (mocked) + :func:`mark_replicated` no-ops on already-replicated
    (composed via M3 — mocked).
  - Audit-grade (D26 + D76): PipelineEventLog row written with canonical
    EventType='SNOWFLAKE_COPY_INTO' (best-effort; observability never fatal).
  - Operationally stable (D69): single Snowflake CONNECTION per process;
    cursor_for('General') context for registry read + event-log write.
  - Compliant (D6 + D71): RSA private key materialized to /dev/shm by
    M7 (mocked); :func:`release_snowflake_key` called in finally on every
    code path; key path never logged.

Edge case IDs (per ``04_EDGE_CASES.md`` — closest applicable series):
  - N-series (Parquet network drive) — N1: file path absence is the
    operator's responsibility (this module does NOT re-verify the
    SHA-256; that's M3's job). N3 concurrent verify race — covered by
    M3's UPDATE CHECK predicate (out of scope here).

Decision citations:
  D5 (Snowflake-managed Iceberg), D23 (budget alert at 80%),
  D67 (Tier 0 discipline), D68 (error class hierarchy), D69 (cursor
  ownership), D71 (RSA key per-process), D92 (forward-only additive),
  D103 (Claude Code security — no PEM bytes in module memory).

Spec: ``docs/migration/phase1/03_core_modules.md`` § 7.1.
"""
from __future__ import annotations

import importlib
import json
import logging
import re
import sys
import types
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Project root on sys.path
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_MODULE_KEY = "data_load.snowflake_uploader"


# ---------------------------------------------------------------------------
# Autouse fixture: snowflake.connector stub in sys.modules (B214 pattern)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _stub_snowflake_connector(monkeypatch):
    """Install ``snowflake.connector`` MagicMock with autouse cleanup.

    The connector is not installed in the test venv; tests mock at the
    import level. Per B214, use ``monkeypatch.setitem`` so cleanup is
    automatic.
    """
    snowflake_module = types.ModuleType("snowflake")
    connector_module = types.ModuleType("snowflake.connector")
    connector_module.connect = MagicMock()  # type: ignore[attr-defined]
    snowflake_module.connector = connector_module  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "snowflake", snowflake_module)
    monkeypatch.setitem(sys.modules, "snowflake.connector", connector_module)
    yield


@pytest.fixture
def mod():
    """Load data_load.snowflake_uploader fresh for each test."""
    if _MODULE_KEY in sys.modules:
        del sys.modules[_MODULE_KEY]
    m = importlib.import_module(_MODULE_KEY)
    yield m
    if _MODULE_KEY in sys.modules:
        del sys.modules[_MODULE_KEY]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _canonical_row(**overrides) -> dict:
    base = {
        "RegistryId": 42,
        "SourceName": "DNA",
        "TableName": "ACCT",
        "BatchId": 12345,
        "NetworkDrivePath": "/mnt/parquet/DNA/ACCT/2026/05/12345_0001.parquet",
        "Status": "verified",
        "RowCount": 1000,
    }
    base.update(overrides)
    return base


def _make_cursor_for(row_dict: dict | None, *, rowcount: int = 1):
    """Build a cursor_for mock factory."""
    cursor = MagicMock()
    if row_dict is None:
        cursor.fetchone.return_value = None
        cursor.description = []
    else:
        cursor.fetchone.return_value = tuple(row_dict.values())
        cursor.description = [(k,) for k in row_dict.keys()]
    cursor.rowcount = rowcount

    def _factory(_db: str):
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=cursor)
        cm.__exit__ = MagicMock(return_value=False)
        return cm

    return _factory, cursor


def _set_env(monkeypatch, **extra):
    """Set canonical Snowflake env vars + optional overrides."""
    defaults = {
        "SNOWFLAKE_ACCOUNT": "acme-test",
        "SNOWFLAKE_USER": "pipeline_svc",
        "SNOWFLAKE_WAREHOUSE": "UDM_BRONZE_WH",
        "SNOWFLAKE_DATABASE": "UDM_BRONZE_MIRROR",
        "SNOWFLAKE_SCHEMA": "DNA",
        "SNOWFLAKE_MONTHLY_CREDIT_CAP": "10000",
    }
    defaults.update(extra)
    for k, v in defaults.items():
        monkeypatch.setenv(k, str(v))


def _make_sf_conn(
    *,
    sfqid: str = "01b6-c123",
    rows_loaded: int = 1000,
    copy_raises: Exception | None = None,
    budget_credits: float = 100.0,
    cursor_open_raises: Exception | None = None,
):
    """Build a MagicMock Snowflake connection.

    The cursor's ``execute`` is called multiple times — first for the
    budget query (SELECT), then ALTER SESSION SET STATEMENT_TIMEOUT, then
    COPY INTO. The ``fetchone`` and ``fetchall`` return values are
    different for each call sequence; we use ``side_effect`` lists to
    keep them disambiguated.
    """
    conn = MagicMock()
    if cursor_open_raises is not None:
        conn.cursor.side_effect = cursor_open_raises
        return conn

    # Budget cursor + COPY cursor are SEPARATE cursor() calls because
    # _check_snowflake_budget opens its own cursor and closes it. Make
    # conn.cursor() return a fresh MagicMock each call so .execute()
    # call sequence is independent.
    budget_cursor = MagicMock()
    budget_cursor.fetchone.return_value = (budget_credits,)

    copy_cursor = MagicMock()
    copy_cursor.sfqid = sfqid
    copy_cursor.fetchall.return_value = [
        ("file.parquet", "LOADED", rows_loaded, rows_loaded, 0, 0, None, None, None, None)
    ]

    if copy_raises is not None:
        # _execute_copy_into makes 2 execute calls: ALTER SESSION + COPY INTO.
        # The COPY INTO is the second one, so use side_effect to raise on
        # the second invocation.
        copy_cursor.execute.side_effect = [None, copy_raises]

    # Two cursor() calls: first is budget, second is COPY. Return them
    # in order.
    conn.cursor.side_effect = [budget_cursor, copy_cursor]
    return conn


# ===========================================================================
# Module surface + constants
# ===========================================================================


class TestModuleSurface:
    """Public API + constants align with spec § 7.1."""

    def test_public_surface(self, mod):
        for name in (
            "copy_parquet_to_snowflake",
            "SnowflakeCopyResult",
            "EVENT_TYPE_SNOWFLAKE_COPY_INTO",
            "COPY_REQUIRED_STATUS",
            "DEFAULT_COPY_TIMEOUT_SECONDS",
            "DEFAULT_BUDGET_ALERT_THRESHOLD",
        ):
            assert hasattr(mod, name), f"missing {name!r}"

    def test_event_type_is_canonical(self, mod):
        assert mod.EVENT_TYPE_SNOWFLAKE_COPY_INTO == "SNOWFLAKE_COPY_INTO"

    def test_copy_required_status(self, mod):
        assert mod.COPY_REQUIRED_STATUS == "verified"

    def test_default_timeout(self, mod):
        assert mod.DEFAULT_COPY_TIMEOUT_SECONDS == 300

    def test_default_threshold(self, mod):
        assert mod.DEFAULT_BUDGET_ALERT_THRESHOLD == 0.80

    def test_result_dataclass_is_frozen(self, mod):
        result = mod.SnowflakeCopyResult(
            registry_id=1, snowflake_table="a.b.c",
            rows_copied=10, copy_history_id="qid", duration_ms=100,
        )
        with pytest.raises((AttributeError, Exception)):
            result.registry_id = 2  # type: ignore[misc]

    def test_errors_not_in_all(self, mod):
        # Per B-228: error classes are bound but NOT re-exported.
        assert "SnowflakeAuthFailed" not in mod.__all__
        assert "SnowflakeBudgetAlert" not in mod.__all__
        assert "SnowflakeCopyTimeout" not in mod.__all__
        assert "RegistryStatusInvalid" not in mod.__all__

    def test_errors_imported_from_utils(self, mod):
        from utils.errors import (
            RegistryNotFound,
            RegistryStatusInvalid,
            SnowflakeAuthFailed,
            SnowflakeBudgetAlert,
            SnowflakeCopyTimeout,
        )
        # Module's internal names alias to utils.errors (B-228).
        assert mod.SnowflakeAuthFailed is SnowflakeAuthFailed
        assert mod.SnowflakeBudgetAlert is SnowflakeBudgetAlert
        assert mod.SnowflakeCopyTimeout is SnowflakeCopyTimeout
        assert mod.RegistryStatusInvalid is RegistryStatusInvalid
        assert mod.RegistryNotFound is RegistryNotFound


# ===========================================================================
# Registry row read
# ===========================================================================


class TestRegistryRowRead:
    """``_read_registry_row`` projection + RegistryNotFound handling."""

    def test_row_found_returns_dict(self, mod):
        factory, _ = _make_cursor_for(_canonical_row())
        with patch.object(mod, "_get_cursor_for", return_value=factory):
            row = mod._read_registry_row(42)
        assert row["RegistryId"] == 42
        assert row["Status"] == "verified"
        assert row["NetworkDrivePath"].endswith(".parquet")

    def test_row_absent_raises_registry_not_found(self, mod):
        from utils.errors import RegistryNotFound

        factory, _ = _make_cursor_for(None)
        with patch.object(mod, "_get_cursor_for", return_value=factory):
            with pytest.raises(RegistryNotFound) as excinfo:
                mod._read_registry_row(99999)
        assert excinfo.value.metadata["registry_id"] == 99999

    def test_projection_includes_required_columns(self, mod):
        factory, cursor = _make_cursor_for(_canonical_row())
        with patch.object(mod, "_get_cursor_for", return_value=factory):
            mod._read_registry_row(42)
        # Verify the SELECT projection has all required columns.
        sql = cursor.execute.call_args[0][0]
        for col in ("RegistryId", "SourceName", "TableName", "BatchId",
                    "NetworkDrivePath", "Status", "RowCount"):
            assert col in sql, f"missing column {col!r} in SELECT"


# ===========================================================================
# Default snowflake_table mapping
# ===========================================================================


class TestDefaultMapping:
    """``_default_snowflake_table`` env-var composition per § 2.1.8."""

    def test_default_uses_env(self, mod, monkeypatch):
        monkeypatch.setenv("SNOWFLAKE_DATABASE", "MY_DB")
        monkeypatch.setenv("SNOWFLAKE_SCHEMA", "MY_SCHEMA")
        result = mod._default_snowflake_table(table_name="ACCT")
        assert result == "MY_DB.MY_SCHEMA.ACCT"

    def test_default_falls_back_to_canonical_when_env_absent(self, mod, monkeypatch):
        monkeypatch.delenv("SNOWFLAKE_DATABASE", raising=False)
        monkeypatch.delenv("SNOWFLAKE_SCHEMA", raising=False)
        result = mod._default_snowflake_table(table_name="ACCT")
        assert result == "UDM_BRONZE_MIRROR.PUBLIC.ACCT"


# ===========================================================================
# Budget pre-check
# ===========================================================================


class TestBudgetPrecheck:
    """``_check_snowflake_budget`` D23 enforcement."""

    def test_budget_under_threshold_returns(self, mod, monkeypatch):
        monkeypatch.setenv("SNOWFLAKE_MONTHLY_CREDIT_CAP", "10000")
        conn = _make_sf_conn(budget_credits=100.0)
        # Pop the budget cursor (first cursor() call) for direct test.
        # Re-attach to be reusable.
        mod._check_snowflake_budget(conn)  # Should not raise.

    def test_budget_over_threshold_raises_alert(self, mod, monkeypatch):
        from utils.errors import SnowflakeBudgetAlert

        monkeypatch.setenv("SNOWFLAKE_MONTHLY_CREDIT_CAP", "1000")
        # 850 credits / 1000 cap = 85% > 80% threshold
        conn = _make_sf_conn(budget_credits=850.0)
        with pytest.raises(SnowflakeBudgetAlert) as excinfo:
            mod._check_snowflake_budget(conn)
        assert excinfo.value.metadata["fraction_used"] == pytest.approx(0.85, rel=1e-3)
        assert excinfo.value.metadata["monthly_cap"] == 1000.0

    def test_budget_invalid_cap_skipped(self, mod, monkeypatch, caplog):
        """Non-numeric cap is logged and skipped (best-effort)."""
        monkeypatch.setenv("SNOWFLAKE_MONTHLY_CREDIT_CAP", "not-a-number")
        conn = _make_sf_conn()
        with caplog.at_level(logging.WARNING):
            mod._check_snowflake_budget(conn)  # No raise.
        assert any("not a number" in r.message for r in caplog.records)

    def test_budget_zero_cap_skipped(self, mod, monkeypatch, caplog):
        monkeypatch.setenv("SNOWFLAKE_MONTHLY_CREDIT_CAP", "0")
        conn = _make_sf_conn()
        with caplog.at_level(logging.WARNING):
            mod._check_snowflake_budget(conn)
        assert any("non-positive" in r.message for r in caplog.records)

    def test_budget_query_failure_skipped(self, mod, monkeypatch, caplog):
        """Query failure logs WARNING and returns — best-effort."""
        monkeypatch.setenv("SNOWFLAKE_MONTHLY_CREDIT_CAP", "10000")
        conn = MagicMock()
        bad_cursor = MagicMock()
        bad_cursor.execute.side_effect = RuntimeError("connection lost")
        conn.cursor.return_value = bad_cursor
        with caplog.at_level(logging.WARNING):
            mod._check_snowflake_budget(conn)
        assert any("budget pre-check query failed" in r.message for r in caplog.records)

    def test_budget_no_rows_returned_skipped(self, mod, monkeypatch, caplog):
        monkeypatch.setenv("SNOWFLAKE_MONTHLY_CREDIT_CAP", "10000")
        conn = MagicMock()
        empty_cursor = MagicMock()
        empty_cursor.fetchone.return_value = None
        conn.cursor.return_value = empty_cursor
        with caplog.at_level(logging.WARNING):
            mod._check_snowflake_budget(conn)
        assert any("returned no rows" in r.message for r in caplog.records)

    def test_budget_threshold_param_overridable(self, mod, monkeypatch):
        """Caller can pass a non-default threshold."""
        from utils.errors import SnowflakeBudgetAlert
        monkeypatch.setenv("SNOWFLAKE_MONTHLY_CREDIT_CAP", "1000")
        # 600 / 1000 = 60% — under default 80% but over 50%
        conn = _make_sf_conn(budget_credits=600.0)
        with pytest.raises(SnowflakeBudgetAlert):
            mod._check_snowflake_budget(conn, threshold=0.50)


# ===========================================================================
# Snowflake connection open
# ===========================================================================


class TestSnowflakeConnection:
    """``_open_snowflake_connection`` auth + env validation."""

    def test_missing_env_raises_auth_failed(self, mod, monkeypatch):
        from utils.errors import SnowflakeAuthFailed

        monkeypatch.delenv("SNOWFLAKE_ACCOUNT", raising=False)
        monkeypatch.setenv("SNOWFLAKE_USER", "u")
        monkeypatch.setenv("SNOWFLAKE_WAREHOUSE", "w")
        monkeypatch.setenv("SNOWFLAKE_DATABASE", "d")
        monkeypatch.setenv("SNOWFLAKE_SCHEMA", "s")

        creds = {"SNOWFLAKE_PRIVATE_KEY_PATH": "/tmp/key"}
        with pytest.raises(SnowflakeAuthFailed) as excinfo:
            mod._open_snowflake_connection(creds)
        assert "SNOWFLAKE_ACCOUNT" in excinfo.value.metadata["missing_env_vars"]

    def test_missing_key_raises_auth_failed(self, mod, monkeypatch):
        from utils.errors import SnowflakeAuthFailed

        _set_env(monkeypatch)
        creds = {"ORACLE_DNA_PASSWORD": "redacted"}  # No key path/PEM
        with pytest.raises(SnowflakeAuthFailed) as excinfo:
            mod._open_snowflake_connection(creds)
        # The error metadata MUST only list key NAMES — never values.
        assert "available_key_names" in excinfo.value.metadata
        assert "ORACLE_DNA_PASSWORD" in excinfo.value.metadata["available_key_names"]
        # The metadata MUST NOT contain the value 'redacted'.
        assert "redacted" not in json.dumps(excinfo.value.metadata)

    def test_key_path_open_failure_wraps(self, mod, monkeypatch):
        from utils.errors import SnowflakeAuthFailed

        _set_env(monkeypatch)
        creds = {"SNOWFLAKE_PRIVATE_KEY_PATH": "/dev/shm/nonexistent"}
        with pytest.raises(SnowflakeAuthFailed) as excinfo:
            mod._open_snowflake_connection(creds)
        # CRITICAL: actual path must NOT appear in error message OR metadata.
        assert "/dev/shm/nonexistent" not in str(excinfo.value)
        assert "/dev/shm/nonexistent" not in json.dumps(excinfo.value.metadata)
        # The placeholder "ephemeral_key_path" should appear instead.
        assert "ephemeral_key_path" in str(excinfo.value)

    def test_connector_raises_wrapped_as_auth_failed(self, mod, monkeypatch, tmp_path):
        from utils.errors import SnowflakeAuthFailed

        _set_env(monkeypatch)
        key_file = tmp_path / "key.pem"
        key_file.write_bytes(b"-----BEGIN PRIVATE KEY-----\nFAKE\n-----END PRIVATE KEY-----")
        creds = {"SNOWFLAKE_PRIVATE_KEY_PATH": str(key_file)}

        def _connect_raises(**_kwargs):
            raise RuntimeError("ProgrammingError: invalid credentials")

        fake_connector = types.SimpleNamespace(connect=_connect_raises)
        with patch.object(mod, "_get_snowflake_connector", return_value=fake_connector):
            with pytest.raises(SnowflakeAuthFailed) as excinfo:
                mod._open_snowflake_connection(creds)
        assert "Snowflake CONNECT failed" in str(excinfo.value)
        assert excinfo.value.metadata["error_type"] == "RuntimeError"

    def test_pem_in_dict_used_when_no_path(self, mod, monkeypatch):
        """On non-Linux dev workstation, PEM-in-dict is the fallback."""
        _set_env(monkeypatch)
        creds = {"SNOWFLAKE_PRIVATE_KEY_PEM": "-----BEGIN PRIVATE KEY-----\nXX\n-----END PRIVATE KEY-----"}
        conn_sentinel = MagicMock(name="open_connection_sentinel")
        fake_connector = types.SimpleNamespace(connect=MagicMock(return_value=conn_sentinel))
        with patch.object(mod, "_get_snowflake_connector", return_value=fake_connector):
            result = mod._open_snowflake_connection(creds)
        assert result is conn_sentinel
        # connect() was called with private_key as the encoded PEM bytes.
        call_kwargs = fake_connector.connect.call_args.kwargs
        assert call_kwargs["private_key"] == b"-----BEGIN PRIVATE KEY-----\nXX\n-----END PRIVATE KEY-----"

    def test_connect_called_with_expected_params(self, mod, monkeypatch, tmp_path):
        """connect() receives account / user / warehouse / database / schema."""
        _set_env(monkeypatch,
                 SNOWFLAKE_ACCOUNT="acct-xyz",
                 SNOWFLAKE_USER="svc-user",
                 SNOWFLAKE_WAREHOUSE="WH_A",
                 SNOWFLAKE_DATABASE="DB_B",
                 SNOWFLAKE_SCHEMA="SCH_C")
        key_file = tmp_path / "key.pem"
        key_file.write_bytes(b"PEM-BYTES")
        creds = {"SNOWFLAKE_PRIVATE_KEY_PATH": str(key_file)}
        fake_connector = types.SimpleNamespace(connect=MagicMock(return_value=MagicMock()))
        with patch.object(mod, "_get_snowflake_connector", return_value=fake_connector):
            mod._open_snowflake_connection(creds)
        kw = fake_connector.connect.call_args.kwargs
        assert kw["account"] == "acct-xyz"
        assert kw["user"] == "svc-user"
        assert kw["warehouse"] == "WH_A"
        assert kw["database"] == "DB_B"
        assert kw["schema"] == "SCH_C"
        assert kw["private_key"] == b"PEM-BYTES"


# ===========================================================================
# Connector unavailable
# ===========================================================================


class TestConnectorUnavailable:
    """``_get_snowflake_connector`` wraps ImportError per D68."""

    def test_import_error_wraps_as_auth_failed(self, mod, monkeypatch):
        from utils.errors import SnowflakeAuthFailed

        # Patch the import to raise ImportError.
        monkeypatch.delitem(sys.modules, "snowflake.connector", raising=False)
        monkeypatch.delitem(sys.modules, "snowflake", raising=False)

        def _raise_import(name, *args, **kwargs):
            if name.startswith("snowflake"):
                raise ImportError("No module named 'snowflake'")
            return original_import(name, *args, **kwargs)

        original_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__
        with patch("builtins.__import__", side_effect=_raise_import):
            with pytest.raises(SnowflakeAuthFailed) as excinfo:
                mod._get_snowflake_connector()
        assert "snowflake-connector-python is not installed" in str(excinfo.value)


# ===========================================================================
# COPY INTO execution
# ===========================================================================


class TestCopyIntoExecution:
    """``_execute_copy_into`` parses Snowflake response correctly."""

    def test_copy_returns_rows_and_qid(self, mod):
        conn, _ = _build_sf_conn_for_copy()
        rows, qid = mod._execute_copy_into(
            conn,
            snowflake_table="DB.SCHEMA.TABLE",
            network_drive_path="/mnt/parquet/foo.parquet",
            timeout_seconds=300,
        )
        assert rows == 1000
        assert qid == "01b6-c123"

    def test_copy_timeout_wraps_as_snowflake_copy_timeout(self, mod):
        from utils.errors import SnowflakeCopyTimeout

        conn = MagicMock()
        cursor = MagicMock()
        cursor.execute.side_effect = [
            None,  # ALTER SESSION SET STATEMENT_TIMEOUT
            RuntimeError("Statement reached its statement timeout"),
        ]
        conn.cursor.return_value = cursor
        with pytest.raises(SnowflakeCopyTimeout) as excinfo:
            mod._execute_copy_into(
                conn,
                snowflake_table="DB.SCHEMA.TABLE",
                network_drive_path="/mnt/foo.parquet",
                timeout_seconds=60,
            )
        assert excinfo.value.metadata["timeout_seconds"] == 60

    def test_copy_with_timeout_in_message_caught(self, mod):
        from utils.errors import SnowflakeCopyTimeout

        conn = MagicMock()
        cursor = MagicMock()
        cursor.execute.side_effect = [
            None,
            RuntimeError("query timeout exceeded"),
        ]
        conn.cursor.return_value = cursor
        with pytest.raises(SnowflakeCopyTimeout):
            mod._execute_copy_into(
                conn, snowflake_table="X.Y.Z",
                network_drive_path="/mnt/foo.parquet",
                timeout_seconds=300,
            )

    def test_copy_non_timeout_error_wraps_auth_failed(self, mod):
        from utils.errors import SnowflakeAuthFailed

        conn = MagicMock()
        cursor = MagicMock()
        cursor.execute.side_effect = [
            None,
            RuntimeError("ProgrammingError: stage not found"),
        ]
        conn.cursor.return_value = cursor
        with pytest.raises(SnowflakeAuthFailed) as excinfo:
            mod._execute_copy_into(
                conn, snowflake_table="X.Y.Z",
                network_drive_path="/mnt/foo.parquet",
                timeout_seconds=300,
            )
        assert "COPY INTO failed" in str(excinfo.value)

    def test_copy_cursor_open_failure_wraps(self, mod):
        from utils.errors import SnowflakeAuthFailed

        conn = MagicMock()
        conn.cursor.side_effect = RuntimeError("session expired")
        with pytest.raises(SnowflakeAuthFailed):
            mod._execute_copy_into(
                conn, snowflake_table="X.Y.Z",
                network_drive_path="/mnt/foo.parquet",
                timeout_seconds=300,
            )

    def test_copy_uses_stage_env_var(self, mod, monkeypatch):
        monkeypatch.setenv("SNOWFLAKE_STAGE_NAME", "@CUSTOM_STAGE")
        conn, copy_cursor = _build_sf_conn_for_copy()
        mod._execute_copy_into(
            conn, snowflake_table="DB.SCHEMA.TABLE",
            network_drive_path="/mnt/foo.parquet",
            timeout_seconds=300,
        )
        # Second execute call is the COPY; first is ALTER SESSION.
        copy_call = copy_cursor.execute.call_args_list[1]
        sql = copy_call[0][0]
        assert "@CUSTOM_STAGE" in sql

    def test_copy_aggregates_multiple_files(self, mod):
        conn = MagicMock()
        cursor = MagicMock()
        cursor.sfqid = "qid-multi"
        cursor.fetchall.return_value = [
            ("a.parquet", "LOADED", 500, 500, 0, 0, None, None, None, None),
            ("b.parquet", "LOADED", 300, 300, 0, 0, None, None, None, None),
        ]
        conn.cursor.return_value = cursor
        rows, qid = mod._execute_copy_into(
            conn, snowflake_table="X.Y.Z",
            network_drive_path="/mnt/foo.parquet",
            timeout_seconds=300,
        )
        assert rows == 800
        assert qid == "qid-multi"

    def test_copy_handles_empty_fetchall(self, mod):
        """Idempotent re-copy returns 0 rows."""
        conn = MagicMock()
        cursor = MagicMock()
        cursor.sfqid = "qid-noop"
        cursor.fetchall.return_value = []
        conn.cursor.return_value = cursor
        rows, qid = mod._execute_copy_into(
            conn, snowflake_table="X.Y.Z",
            network_drive_path="/mnt/foo.parquet",
            timeout_seconds=300,
        )
        assert rows == 0
        assert qid == "qid-noop"

    def test_copy_handles_malformed_row(self, mod):
        """Defensive: short row shape doesn't crash."""
        conn = MagicMock()
        cursor = MagicMock()
        cursor.sfqid = "qid"
        cursor.fetchall.return_value = [("a.parquet",)]  # Too short
        conn.cursor.return_value = cursor
        rows, _ = mod._execute_copy_into(
            conn, snowflake_table="X.Y.Z",
            network_drive_path="/mnt/foo.parquet",
            timeout_seconds=300,
        )
        assert rows == 0


def _build_sf_conn_for_copy(*, sfqid: str = "01b6-c123", rows_loaded: int = 1000):
    """Helper for COPY tests — single-cursor mode (no budget cursor)."""
    conn = MagicMock()
    cursor = MagicMock()
    cursor.sfqid = sfqid
    cursor.fetchall.return_value = [
        ("file.parquet", "LOADED", rows_loaded, rows_loaded, 0, 0, None, None, None, None)
    ]
    conn.cursor.return_value = cursor
    return conn, cursor


# ===========================================================================
# Happy path end-to-end
# ===========================================================================


class TestHappyPath:
    """``copy_parquet_to_snowflake`` end-to-end with all mocks."""

    def test_happy_path_returns_canonical_result(self, mod, monkeypatch):
        _set_env(monkeypatch)
        cursor_factory, _ = _make_cursor_for(_canonical_row())
        sf_conn = _make_sf_conn()
        mark_replicated_mock = MagicMock()
        release_mock = MagicMock()
        creds = {"SNOWFLAKE_PRIVATE_KEY_PATH": "/dev/shm/snowflake_pk_99"}

        with patch.object(mod, "_get_cursor_for", return_value=cursor_factory), \
             patch.object(mod, "_get_load_credentials", return_value=lambda: creds), \
             patch.object(mod, "_get_release_snowflake_key", return_value=release_mock), \
             patch.object(mod, "_get_mark_replicated", return_value=mark_replicated_mock), \
             patch.object(mod, "_open_snowflake_connection", return_value=sf_conn):
            result = mod.copy_parquet_to_snowflake(
                registry_id=42,
                snowflake_table="UDM_BRONZE_MIRROR.DNA.ACCT",
            )

        assert isinstance(result, mod.SnowflakeCopyResult)
        assert result.registry_id == 42
        assert result.snowflake_table == "UDM_BRONZE_MIRROR.DNA.ACCT"
        assert result.rows_copied == 1000
        assert result.copy_history_id == "01b6-c123"
        assert result.duration_ms >= 0

    def test_happy_path_calls_mark_replicated(self, mod, monkeypatch):
        _set_env(monkeypatch)
        cursor_factory, _ = _make_cursor_for(_canonical_row())
        sf_conn = _make_sf_conn()
        mark_replicated_mock = MagicMock()
        release_mock = MagicMock()
        creds = {"SNOWFLAKE_PRIVATE_KEY_PATH": "/dev/shm/snowflake_pk_99"}

        with patch.object(mod, "_get_cursor_for", return_value=cursor_factory), \
             patch.object(mod, "_get_load_credentials", return_value=lambda: creds), \
             patch.object(mod, "_get_release_snowflake_key", return_value=release_mock), \
             patch.object(mod, "_get_mark_replicated", return_value=mark_replicated_mock), \
             patch.object(mod, "_open_snowflake_connection", return_value=sf_conn):
            mod.copy_parquet_to_snowflake(
                registry_id=42,
                snowflake_table="UDM_BRONZE_MIRROR.DNA.ACCT",
            )

        mark_replicated_mock.assert_called_once()
        call_kwargs = mark_replicated_mock.call_args.kwargs
        assert call_kwargs["registry_id"] == 42
        assert call_kwargs["replica_target"].startswith("snowflake:")
        assert "UDM_BRONZE_MIRROR.DNA.ACCT" in call_kwargs["replica_target"]

    def test_default_snowflake_table_used_when_no_override(self, mod, monkeypatch):
        _set_env(monkeypatch, SNOWFLAKE_DATABASE="DB_X", SNOWFLAKE_SCHEMA="SCH_Y")
        cursor_factory, _ = _make_cursor_for(_canonical_row(TableName="MYTABLE"))
        sf_conn = _make_sf_conn()
        mark_replicated_mock = MagicMock()
        release_mock = MagicMock()
        creds = {"SNOWFLAKE_PRIVATE_KEY_PATH": "/tmp/key"}

        with patch.object(mod, "_get_cursor_for", return_value=cursor_factory), \
             patch.object(mod, "_get_load_credentials", return_value=lambda: creds), \
             patch.object(mod, "_get_release_snowflake_key", return_value=release_mock), \
             patch.object(mod, "_get_mark_replicated", return_value=mark_replicated_mock), \
             patch.object(mod, "_open_snowflake_connection", return_value=sf_conn):
            result = mod.copy_parquet_to_snowflake(registry_id=42)

        assert result.snowflake_table == "DB_X.SCH_Y.MYTABLE"

    def test_release_key_called_in_finally_on_success(self, mod, monkeypatch):
        _set_env(monkeypatch)
        cursor_factory, _ = _make_cursor_for(_canonical_row())
        sf_conn = _make_sf_conn()
        mark_replicated_mock = MagicMock()
        release_mock = MagicMock()
        creds = {"SNOWFLAKE_PRIVATE_KEY_PATH": "/tmp/key"}

        with patch.object(mod, "_get_cursor_for", return_value=cursor_factory), \
             patch.object(mod, "_get_load_credentials", return_value=lambda: creds), \
             patch.object(mod, "_get_release_snowflake_key", return_value=release_mock), \
             patch.object(mod, "_get_mark_replicated", return_value=mark_replicated_mock), \
             patch.object(mod, "_open_snowflake_connection", return_value=sf_conn):
            mod.copy_parquet_to_snowflake(registry_id=42)

        release_mock.assert_called_once()

    def test_snowflake_conn_closed_in_finally(self, mod, monkeypatch):
        _set_env(monkeypatch)
        cursor_factory, _ = _make_cursor_for(_canonical_row())
        sf_conn = _make_sf_conn()
        mark_replicated_mock = MagicMock()
        release_mock = MagicMock()
        creds = {"SNOWFLAKE_PRIVATE_KEY_PATH": "/tmp/key"}

        with patch.object(mod, "_get_cursor_for", return_value=cursor_factory), \
             patch.object(mod, "_get_load_credentials", return_value=lambda: creds), \
             patch.object(mod, "_get_release_snowflake_key", return_value=release_mock), \
             patch.object(mod, "_get_mark_replicated", return_value=mark_replicated_mock), \
             patch.object(mod, "_open_snowflake_connection", return_value=sf_conn):
            mod.copy_parquet_to_snowflake(registry_id=42)

        sf_conn.close.assert_called_once()


# ===========================================================================
# Error paths
# ===========================================================================


class TestErrorPaths:
    """Each documented error raises with the correct class + metadata."""

    def test_registry_not_found(self, mod, monkeypatch):
        from utils.errors import RegistryNotFound

        _set_env(monkeypatch)
        cursor_factory, _ = _make_cursor_for(None)
        with patch.object(mod, "_get_cursor_for", return_value=cursor_factory):
            with pytest.raises(RegistryNotFound) as excinfo:
                mod.copy_parquet_to_snowflake(registry_id=99999)
        assert excinfo.value.metadata["registry_id"] == 99999

    @pytest.mark.parametrize("bad_status", [
        "created",
        "replicated",
        "archived",
        "missing",
        "purged",
        "replication_failed",
    ])
    def test_non_verified_status_raises(self, mod, monkeypatch, bad_status):
        from utils.errors import RegistryStatusInvalid

        _set_env(monkeypatch)
        cursor_factory, _ = _make_cursor_for(_canonical_row(Status=bad_status))
        with patch.object(mod, "_get_cursor_for", return_value=cursor_factory):
            with pytest.raises(RegistryStatusInvalid) as excinfo:
                mod.copy_parquet_to_snowflake(registry_id=42)
        assert excinfo.value.metadata["current_status"] == bad_status
        assert excinfo.value.metadata["required_status"] == "verified"

    def test_budget_alert_raises_before_copy(self, mod, monkeypatch):
        """Budget alert raised; mark_replicated NOT called."""
        from utils.errors import SnowflakeBudgetAlert

        _set_env(monkeypatch, SNOWFLAKE_MONTHLY_CREDIT_CAP="1000")
        cursor_factory, _ = _make_cursor_for(_canonical_row())
        sf_conn = _make_sf_conn(budget_credits=900.0)  # 90% > 80%
        mark_replicated_mock = MagicMock()
        release_mock = MagicMock()
        creds = {"SNOWFLAKE_PRIVATE_KEY_PATH": "/tmp/key"}

        with patch.object(mod, "_get_cursor_for", return_value=cursor_factory), \
             patch.object(mod, "_get_load_credentials", return_value=lambda: creds), \
             patch.object(mod, "_get_release_snowflake_key", return_value=release_mock), \
             patch.object(mod, "_get_mark_replicated", return_value=mark_replicated_mock), \
             patch.object(mod, "_open_snowflake_connection", return_value=sf_conn):
            with pytest.raises(SnowflakeBudgetAlert):
                mod.copy_parquet_to_snowflake(registry_id=42)

        mark_replicated_mock.assert_not_called()
        # release_snowflake_key MUST still be called (finally cleanup).
        release_mock.assert_called_once()

    def test_auth_failed_raises_release_still_called(self, mod, monkeypatch):
        """SnowflakeAuthFailed from open_connection — release in finally."""
        from utils.errors import SnowflakeAuthFailed

        _set_env(monkeypatch)
        cursor_factory, _ = _make_cursor_for(_canonical_row())
        mark_replicated_mock = MagicMock()
        release_mock = MagicMock()
        creds = {"SNOWFLAKE_PRIVATE_KEY_PATH": "/tmp/key"}

        def _open_raises(*_args, **_kwargs):
            raise SnowflakeAuthFailed("simulated auth fail", metadata={})

        with patch.object(mod, "_get_cursor_for", return_value=cursor_factory), \
             patch.object(mod, "_get_load_credentials", return_value=lambda: creds), \
             patch.object(mod, "_get_release_snowflake_key", return_value=release_mock), \
             patch.object(mod, "_get_mark_replicated", return_value=mark_replicated_mock), \
             patch.object(mod, "_open_snowflake_connection", side_effect=_open_raises):
            with pytest.raises(SnowflakeAuthFailed):
                mod.copy_parquet_to_snowflake(registry_id=42)

        mark_replicated_mock.assert_not_called()
        release_mock.assert_called_once()

    def test_copy_timeout_raises_release_still_called(self, mod, monkeypatch):
        from utils.errors import SnowflakeCopyTimeout

        _set_env(monkeypatch)
        cursor_factory, _ = _make_cursor_for(_canonical_row())
        sf_conn = _make_sf_conn(
            copy_raises=RuntimeError("Statement reached its statement timeout"),
        )
        mark_replicated_mock = MagicMock()
        release_mock = MagicMock()
        creds = {"SNOWFLAKE_PRIVATE_KEY_PATH": "/tmp/key"}

        with patch.object(mod, "_get_cursor_for", return_value=cursor_factory), \
             patch.object(mod, "_get_load_credentials", return_value=lambda: creds), \
             patch.object(mod, "_get_release_snowflake_key", return_value=release_mock), \
             patch.object(mod, "_get_mark_replicated", return_value=mark_replicated_mock), \
             patch.object(mod, "_open_snowflake_connection", return_value=sf_conn):
            with pytest.raises(SnowflakeCopyTimeout):
                mod.copy_parquet_to_snowflake(registry_id=42)

        mark_replicated_mock.assert_not_called()
        release_mock.assert_called_once()

    def test_release_failure_in_finally_does_not_mask_original(self, mod, monkeypatch):
        """release_snowflake_key raising in finally doesn't mask the COPY error."""
        from utils.errors import SnowflakeCopyTimeout

        _set_env(monkeypatch)
        cursor_factory, _ = _make_cursor_for(_canonical_row())
        sf_conn = _make_sf_conn(
            copy_raises=RuntimeError("Statement reached its statement timeout"),
        )
        mark_replicated_mock = MagicMock()
        release_mock = MagicMock(side_effect=RuntimeError("shm unmount"))
        creds = {"SNOWFLAKE_PRIVATE_KEY_PATH": "/tmp/key"}

        with patch.object(mod, "_get_cursor_for", return_value=cursor_factory), \
             patch.object(mod, "_get_load_credentials", return_value=lambda: creds), \
             patch.object(mod, "_get_release_snowflake_key", return_value=release_mock), \
             patch.object(mod, "_get_mark_replicated", return_value=mark_replicated_mock), \
             patch.object(mod, "_open_snowflake_connection", return_value=sf_conn):
            # The original SnowflakeCopyTimeout should propagate, not the
            # release_snowflake_key inner exception.
            with pytest.raises(SnowflakeCopyTimeout):
                mod.copy_parquet_to_snowflake(registry_id=42)


# ===========================================================================
# Idempotency
# ===========================================================================


class TestIdempotency:
    """Idempotency contract: re-call after success is safe."""

    def test_mark_replicated_handles_already_replicated(self, mod, monkeypatch):
        """If mark_replicated short-circuits (already 'replicated'), COPY still
        succeeds; M3 handles the idempotent no-op internally."""
        _set_env(monkeypatch)
        cursor_factory, _ = _make_cursor_for(_canonical_row())
        sf_conn = _make_sf_conn(rows_loaded=0)  # Snowflake dedup'd
        # mark_replicated as no-op (M3 internally handles already-replicated case)
        mark_replicated_mock = MagicMock()
        release_mock = MagicMock()
        creds = {"SNOWFLAKE_PRIVATE_KEY_PATH": "/tmp/key"}

        with patch.object(mod, "_get_cursor_for", return_value=cursor_factory), \
             patch.object(mod, "_get_load_credentials", return_value=lambda: creds), \
             patch.object(mod, "_get_release_snowflake_key", return_value=release_mock), \
             patch.object(mod, "_get_mark_replicated", return_value=mark_replicated_mock), \
             patch.object(mod, "_open_snowflake_connection", return_value=sf_conn):
            result = mod.copy_parquet_to_snowflake(registry_id=42)

        # rows_copied=0 is the canonical idempotent-re-COPY signal.
        assert result.rows_copied == 0
        mark_replicated_mock.assert_called_once()

    def test_replica_target_format(self, mod, monkeypatch):
        """Replica target is 'snowflake:<DB>.<SCHEMA>.<TABLE>' for audit."""
        _set_env(monkeypatch)
        cursor_factory, _ = _make_cursor_for(_canonical_row())
        sf_conn = _make_sf_conn()
        mark_replicated_mock = MagicMock()
        release_mock = MagicMock()
        creds = {"SNOWFLAKE_PRIVATE_KEY_PATH": "/tmp/key"}

        with patch.object(mod, "_get_cursor_for", return_value=cursor_factory), \
             patch.object(mod, "_get_load_credentials", return_value=lambda: creds), \
             patch.object(mod, "_get_release_snowflake_key", return_value=release_mock), \
             patch.object(mod, "_get_mark_replicated", return_value=mark_replicated_mock), \
             patch.object(mod, "_open_snowflake_connection", return_value=sf_conn):
            mod.copy_parquet_to_snowflake(
                registry_id=42,
                snowflake_table="UDM_BRONZE_MIRROR.DNA.ACCT",
            )

        target = mark_replicated_mock.call_args.kwargs["replica_target"]
        assert target == "snowflake:UDM_BRONZE_MIRROR.DNA.ACCT"


# ===========================================================================
# Audit row writing
# ===========================================================================


class TestEventLogWriting:
    """``_write_event_log_row`` writes correct EventType + Metadata."""

    def test_event_log_row_written_on_success(self, mod, monkeypatch):
        _set_env(monkeypatch)
        # Track BOTH the registry-read cursor AND the event-log INSERT cursor.
        # _make_cursor_for returns ONE cursor that's reused across calls;
        # for this test we need to capture all SQL calls.
        cursor_factory, captured_cursor = _make_cursor_for(_canonical_row())
        sf_conn = _make_sf_conn()
        mark_replicated_mock = MagicMock()
        release_mock = MagicMock()
        creds = {"SNOWFLAKE_PRIVATE_KEY_PATH": "/tmp/key"}

        with patch.object(mod, "_get_cursor_for", return_value=cursor_factory), \
             patch.object(mod, "_get_load_credentials", return_value=lambda: creds), \
             patch.object(mod, "_get_release_snowflake_key", return_value=release_mock), \
             patch.object(mod, "_get_mark_replicated", return_value=mark_replicated_mock), \
             patch.object(mod, "_open_snowflake_connection", return_value=sf_conn):
            mod.copy_parquet_to_snowflake(registry_id=42)

        # Look through captured execute calls for the event-log INSERT.
        all_calls = captured_cursor.execute.call_args_list
        event_inserts = [
            c for c in all_calls
            if c[0] and isinstance(c[0][0], str) and "PipelineEventLog" in c[0][0]
        ]
        assert len(event_inserts) >= 1, "PipelineEventLog INSERT not executed"
        # EventType is positional param 4 (per the INSERT statement order:
        # BatchId, TableName, SourceName, EventType, ...).
        # Args structure: (sql, batch_id, table_name, source_name, event_type, ...)
        args = event_inserts[0][0]
        # First arg is SQL, then positional params follow.
        assert "SNOWFLAKE_COPY_INTO" in args, (
            "EventType SNOWFLAKE_COPY_INTO not in INSERT params"
        )

    def test_event_log_row_includes_metadata_json(self, mod, monkeypatch):
        _set_env(monkeypatch)
        cursor_factory, captured_cursor = _make_cursor_for(_canonical_row())
        sf_conn = _make_sf_conn()
        mark_replicated_mock = MagicMock()
        release_mock = MagicMock()
        creds = {"SNOWFLAKE_PRIVATE_KEY_PATH": "/tmp/key"}

        with patch.object(mod, "_get_cursor_for", return_value=cursor_factory), \
             patch.object(mod, "_get_load_credentials", return_value=lambda: creds), \
             patch.object(mod, "_get_release_snowflake_key", return_value=release_mock), \
             patch.object(mod, "_get_mark_replicated", return_value=mark_replicated_mock), \
             patch.object(mod, "_open_snowflake_connection", return_value=sf_conn):
            mod.copy_parquet_to_snowflake(
                registry_id=42,
                snowflake_table="UDM_BRONZE_MIRROR.DNA.ACCT",
            )

        all_calls = captured_cursor.execute.call_args_list
        event_inserts = [
            c for c in all_calls
            if c[0] and isinstance(c[0][0], str) and "PipelineEventLog" in c[0][0]
        ]
        assert event_inserts
        # Find the Metadata JSON in args (last positional arg before binding).
        args = event_inserts[0][0]
        # The Metadata JSON should be a JSON string somewhere in args.
        json_args = [a for a in args if isinstance(a, str) and a.startswith("{")]
        assert json_args, "no JSON metadata in INSERT params"
        metadata = json.loads(json_args[0])
        assert metadata["snowflake_table"] == "UDM_BRONZE_MIRROR.DNA.ACCT"
        assert "copy_history_id" in metadata
        assert metadata["registry_id"] == 42

    def test_event_log_write_failure_does_not_raise(self, mod, monkeypatch, caplog):
        """Best-effort: event-log INSERT failure logged but not raised."""
        _set_env(monkeypatch)

        # First call (registry read) succeeds; second call (event-log INSERT)
        # raises. Use a stateful factory.
        registry_cursor = MagicMock()
        registry_cursor.fetchone.return_value = tuple(_canonical_row().values())
        registry_cursor.description = [(k,) for k in _canonical_row().keys()]

        event_cursor = MagicMock()
        event_cursor.execute.side_effect = RuntimeError("DB unreachable")

        call_count = {"n": 0}

        def _factory(_db: str):
            call_count["n"] += 1
            cur = registry_cursor if call_count["n"] == 1 else event_cursor
            cm = MagicMock()
            cm.__enter__ = MagicMock(return_value=cur)
            cm.__exit__ = MagicMock(return_value=False)
            return cm

        sf_conn = _make_sf_conn()
        mark_replicated_mock = MagicMock()
        release_mock = MagicMock()
        creds = {"SNOWFLAKE_PRIVATE_KEY_PATH": "/tmp/key"}

        with patch.object(mod, "_get_cursor_for", return_value=_factory), \
             patch.object(mod, "_get_load_credentials", return_value=lambda: creds), \
             patch.object(mod, "_get_release_snowflake_key", return_value=release_mock), \
             patch.object(mod, "_get_mark_replicated", return_value=mark_replicated_mock), \
             patch.object(mod, "_open_snowflake_connection", return_value=sf_conn), \
             caplog.at_level(logging.WARNING):
            # Should NOT raise.
            result = mod.copy_parquet_to_snowflake(registry_id=42)

        assert result.rows_copied == 1000
        assert any("event-row write failed" in r.message for r in caplog.records)


# ===========================================================================
# Security discipline (D103)
# ===========================================================================


class TestSecurityDiscipline:
    """D103 — RSA key path NEVER logged; PEM bytes NEVER in error messages."""

    _RSA_KEY_PATH = "/dev/shm/snowflake_pk_99999"

    def test_key_path_never_in_log_records(self, mod, monkeypatch, caplog):
        """The /dev/shm path is not logged at INFO+ level."""
        _set_env(monkeypatch)
        cursor_factory, _ = _make_cursor_for(_canonical_row())
        sf_conn = _make_sf_conn()
        mark_replicated_mock = MagicMock()
        release_mock = MagicMock()
        creds = {"SNOWFLAKE_PRIVATE_KEY_PATH": self._RSA_KEY_PATH}

        with patch.object(mod, "_get_cursor_for", return_value=cursor_factory), \
             patch.object(mod, "_get_load_credentials", return_value=lambda: creds), \
             patch.object(mod, "_get_release_snowflake_key", return_value=release_mock), \
             patch.object(mod, "_get_mark_replicated", return_value=mark_replicated_mock), \
             patch.object(mod, "_open_snowflake_connection", return_value=sf_conn), \
             caplog.at_level(logging.INFO):
            mod.copy_parquet_to_snowflake(registry_id=42)

        # Walk every log record for the RSA key path value.
        for record in caplog.records:
            assert self._RSA_KEY_PATH not in record.getMessage(), (
                f"RSA key path leaked into log: {record.getMessage()!r}"
            )

    def test_key_open_failure_does_not_leak_path(self, mod, monkeypatch):
        """OSError on key file read — error message + metadata must not expose path."""
        from utils.errors import SnowflakeAuthFailed

        _set_env(monkeypatch)
        creds = {"SNOWFLAKE_PRIVATE_KEY_PATH": self._RSA_KEY_PATH}
        with pytest.raises(SnowflakeAuthFailed) as excinfo:
            mod._open_snowflake_connection(creds)
        full_text = str(excinfo.value) + json.dumps(excinfo.value.metadata)
        assert self._RSA_KEY_PATH not in full_text, (
            "RSA key path leaked into SnowflakeAuthFailed"
        )
        # The placeholder MUST appear in the message.
        assert "ephemeral_key_path" in str(excinfo.value)

    def test_sensitive_filter_would_redact_pem(self):
        """Defense-in-depth: M14 SensitiveDataFilter catches PEM blocks in logs."""
        from observability.sensitive_data_filter import SENSITIVE_PATTERNS

        pem_block = (
            "-----BEGIN PRIVATE KEY-----\n"
            "MIIBVwIBADANBgkqhkiG9w0BAQEFAASC...\n"
            "-----END PRIVATE KEY-----"
        )
        rsa_pattern = SENSITIVE_PATTERNS["rsa_private_key"]
        assert rsa_pattern.search(pem_block), (
            "RSA PEM block not matched by SensitiveDataFilter — defense in depth broken"
        )

    def test_release_key_called_even_on_copy_failure(self, mod, monkeypatch):
        """try/finally: release_snowflake_key invoked on every exit path."""
        from utils.errors import SnowflakeCopyTimeout

        _set_env(monkeypatch)
        cursor_factory, _ = _make_cursor_for(_canonical_row())
        sf_conn = _make_sf_conn(
            copy_raises=RuntimeError("Statement reached its statement timeout"),
        )
        release_mock = MagicMock()
        creds = {"SNOWFLAKE_PRIVATE_KEY_PATH": self._RSA_KEY_PATH}

        with patch.object(mod, "_get_cursor_for", return_value=cursor_factory), \
             patch.object(mod, "_get_load_credentials", return_value=lambda: creds), \
             patch.object(mod, "_get_release_snowflake_key", return_value=release_mock), \
             patch.object(mod, "_get_mark_replicated", return_value=MagicMock()), \
             patch.object(mod, "_open_snowflake_connection", return_value=sf_conn):
            with pytest.raises(SnowflakeCopyTimeout):
                mod.copy_parquet_to_snowflake(registry_id=42)

        release_mock.assert_called_once()

    def test_missing_key_metadata_only_has_key_names(self, mod, monkeypatch):
        """Missing-key SnowflakeAuthFailed metadata lists key NAMES, never VALUES."""
        from utils.errors import SnowflakeAuthFailed

        _set_env(monkeypatch)
        secret_value = "this-must-not-leak-xyz123"
        creds = {"ORACLE_DNA_PASSWORD": secret_value}
        with pytest.raises(SnowflakeAuthFailed) as excinfo:
            mod._open_snowflake_connection(creds)
        full_text = str(excinfo.value) + json.dumps(excinfo.value.metadata)
        assert secret_value not in full_text, "Secret value leaked into metadata"

    def test_pem_string_processing_does_not_log_bytes(self, mod, monkeypatch, caplog):
        """Open connection with PEM string — no PEM bytes in logs."""
        _set_env(monkeypatch)
        # Use a PEM-shape string that the sensitive_data_filter would match
        # to ensure defense in depth, but ALSO assert our module doesn't
        # log it in the first place.
        pem = "-----BEGIN PRIVATE KEY-----\nSECRETKEY12345\n-----END PRIVATE KEY-----"
        creds = {"SNOWFLAKE_PRIVATE_KEY_PEM": pem}
        fake_connector = types.SimpleNamespace(connect=MagicMock(return_value=MagicMock()))
        with patch.object(mod, "_get_snowflake_connector", return_value=fake_connector), \
             caplog.at_level(logging.DEBUG):
            mod._open_snowflake_connection(creds)
        for record in caplog.records:
            assert "SECRETKEY12345" not in record.getMessage()


# ===========================================================================
# Timing + result correctness
# ===========================================================================


class TestTimingAndResult:
    """duration_ms is non-negative; UTC times are naive millisecond."""

    def test_duration_ms_is_non_negative(self, mod, monkeypatch):
        _set_env(monkeypatch)
        cursor_factory, _ = _make_cursor_for(_canonical_row())
        sf_conn = _make_sf_conn()
        creds = {"SNOWFLAKE_PRIVATE_KEY_PATH": "/tmp/key"}

        with patch.object(mod, "_get_cursor_for", return_value=cursor_factory), \
             patch.object(mod, "_get_load_credentials", return_value=lambda: creds), \
             patch.object(mod, "_get_release_snowflake_key", return_value=MagicMock()), \
             patch.object(mod, "_get_mark_replicated", return_value=MagicMock()), \
             patch.object(mod, "_open_snowflake_connection", return_value=sf_conn):
            result = mod.copy_parquet_to_snowflake(registry_id=42)
        assert result.duration_ms >= 0
        assert isinstance(result.duration_ms, int)

    def test_utcnow_ms_is_naive_and_ms_precision(self, mod):
        now = mod._utcnow_ms()
        assert isinstance(now, datetime)
        assert now.tzinfo is None, "datetime must be naive (no tzinfo)"
        assert now.microsecond % 1000 == 0, "microsecond must be ms-aligned"


# ===========================================================================
# Replica target format
# ===========================================================================


class TestReplicaTarget:
    """Replica target prefix matches the spec audit format."""

    def test_replica_target_prefix(self, mod):
        assert mod._REPLICA_TARGET_PREFIX == "snowflake:"


# ===========================================================================
# Connection close on success + failure
# ===========================================================================


class TestConnectionLifecycle:
    """Snowflake CONNECTION is closed on every exit path (resource leak guard)."""

    def test_connection_closed_on_success(self, mod, monkeypatch):
        _set_env(monkeypatch)
        cursor_factory, _ = _make_cursor_for(_canonical_row())
        sf_conn = _make_sf_conn()
        creds = {"SNOWFLAKE_PRIVATE_KEY_PATH": "/tmp/key"}

        with patch.object(mod, "_get_cursor_for", return_value=cursor_factory), \
             patch.object(mod, "_get_load_credentials", return_value=lambda: creds), \
             patch.object(mod, "_get_release_snowflake_key", return_value=MagicMock()), \
             patch.object(mod, "_get_mark_replicated", return_value=MagicMock()), \
             patch.object(mod, "_open_snowflake_connection", return_value=sf_conn):
            mod.copy_parquet_to_snowflake(registry_id=42)
        sf_conn.close.assert_called_once()

    def test_connection_closed_on_copy_failure(self, mod, monkeypatch):
        from utils.errors import SnowflakeCopyTimeout

        _set_env(monkeypatch)
        cursor_factory, _ = _make_cursor_for(_canonical_row())
        sf_conn = _make_sf_conn(
            copy_raises=RuntimeError("Statement reached its statement timeout"),
        )
        creds = {"SNOWFLAKE_PRIVATE_KEY_PATH": "/tmp/key"}

        with patch.object(mod, "_get_cursor_for", return_value=cursor_factory), \
             patch.object(mod, "_get_load_credentials", return_value=lambda: creds), \
             patch.object(mod, "_get_release_snowflake_key", return_value=MagicMock()), \
             patch.object(mod, "_get_mark_replicated", return_value=MagicMock()), \
             patch.object(mod, "_open_snowflake_connection", return_value=sf_conn):
            with pytest.raises(SnowflakeCopyTimeout):
                mod.copy_parquet_to_snowflake(registry_id=42)
        sf_conn.close.assert_called_once()

    def test_connection_close_failure_swallowed(self, mod, monkeypatch):
        """conn.close() raising in finally must not mask anything."""
        _set_env(monkeypatch)
        cursor_factory, _ = _make_cursor_for(_canonical_row())
        sf_conn = _make_sf_conn()
        sf_conn.close.side_effect = RuntimeError("network drop on close")
        creds = {"SNOWFLAKE_PRIVATE_KEY_PATH": "/tmp/key"}

        with patch.object(mod, "_get_cursor_for", return_value=cursor_factory), \
             patch.object(mod, "_get_load_credentials", return_value=lambda: creds), \
             patch.object(mod, "_get_release_snowflake_key", return_value=MagicMock()), \
             patch.object(mod, "_get_mark_replicated", return_value=MagicMock()), \
             patch.object(mod, "_open_snowflake_connection", return_value=sf_conn):
            # Should NOT raise — successful COPY result is preserved.
            result = mod.copy_parquet_to_snowflake(registry_id=42)
        assert result.rows_copied == 1000
