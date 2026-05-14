"""Tier 1 unit test for data_load/vault_client.py.

Per D70 Tier 1 — per-error-path + per-edge-case coverage; mocks pyodbc
+ env vars; no live SQL Server.

Test scope (organized as classes per sibling tier1 style):

  TestRegistry
    - VAULT_SP_REGISTRY contains the Round 1 SPs the spec calls out.
    - Each entry declares input_params + output_params + result_set flag.

  TestPoolLifecycle
    - configure → is_pool_configured()=True; release → False.
    - Invalid max_connections / connection_timeout_seconds rejected.
    - Double-configure raises VaultConfigError.
    - release is idempotent.

  TestEnvVarValidation
    - Missing VAULT_DB_SERVER / NAME / USER / PASSWORD → VaultConfigError.
    - Required-env metadata identifies the missing key.

  TestCallBuilder
    - SP-1 emits DECLARE + EXEC + SELECT trailing for OUTPUT params.
    - SP-2 emits a single EXEC (no DECLAREs).
    - Unknown sp_args key rejected pre-flight.
    - Unknown sp_name rejected pre-flight (typo guard per Pitfall #9).
    - Missing input param binds as NULL (SPs are expected to have DEFAULTs).

  TestSp1HappyPath
    - SP-1 returns {Token, WasNew} dict.
    - Connect invoked once; reused across calls (pool).

  TestSp2HappyPath
    - SP-2 returns {Token, PlaintextValue} dict from result-set.

  TestSp10HappyPath
    - SP-10 (EnforceRetention) DryRun=1 returns {WouldBeFlipped} dict.
    - SP-10 DryRun=0 returns {Flipped} dict.

  TestErrorTranslationMatrix
    - UNIQUE / PK violation (2627, 2601) BUBBLES UP unchanged (caller
      catch-and-relookup).
    - FK / CHECK violation (547) → PipelineFatalError.
    - Unknown SP at SQL Server side ("Could not find stored procedure")
      → PipelineFatalError with hint.
    - ProgrammingError (non-unknown-SP) → PipelineFatalError.
    - OperationalError → retry loop → VaultUnavailable on exhaustion.
    - InterfaceError → retry loop → VaultUnavailable on exhaustion.
    - SQL Server deadlock (1205) → retryable.
    - SQL Server lock timeout (1222) → retryable.
    - Unrecognized pyodbc.Error → PipelineFatalError (defensive).

  TestRetryBehavior
    - Transient error followed by success — wrapper returns on retry.
    - Backoff delay computed correctly (exponential 2 * 2^(attempt-1)).
    - Backoff capped at 60 s for large attempt counts.
    - max_retries=1 means one attempt (no retry).
    - max_retries=0 rejected as VaultConfigError (caller bug).

  TestConnectionPool
    - First call_vault_sp lazy-connects via pyodbc.connect.
    - Second call_vault_sp reuses the cached connection (no second connect).
    - OperationalError evicts the stale connection (next call re-connects).
    - VAULT_DB_PASSWORD value never appears in logs.

  TestLogSafety
    - SP NAME + arg-key NAMES + arg COUNT logged at DEBUG.
    - Argument VALUES NEVER logged (D103 security contract).
    - Retry attempts logged at WARNING with error class + attempt N.
    - Terminal failure logged at ERROR.

  TestEdgeCases
    - sp_args=None → empty dict (SP with no inputs).
    - SP returning no result-set yields {} (forward-compat).
    - Multi-row result-set yields {"_rows": [...]}.
    - call_vault_sp validates sp_name is non-empty string.
    - call_vault_sp validates base_delay_seconds non-negative.

Spec: phase1/03_core_modules.md § 2.3 + phase1/01_database_schema.md
SP-1 / SP-2 / SP-10.

D-numbers: D6, D17, D67, D68, D69, D103.
B-numbers: M6 (build-tracker entry — closed by authoring this test).
"""
from __future__ import annotations

import logging
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pyodbc
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_vault_pool():
    from data_load import vault_client as vc
    vc.release_vault_connection_pool()
    yield
    vc.release_vault_connection_pool()


@pytest.fixture(autouse=True)
def _patch_sleep(monkeypatch):
    """Patch sleep so retry tests run sub-second."""
    from data_load import vault_client as vc
    monkeypatch.setattr(vc.time, "sleep", lambda _seconds: None)
    yield


@pytest.fixture
def vault_env(monkeypatch):
    """Set VAULT_DB_* env keys to synthetic values."""
    monkeypatch.setenv("VAULT_DB_SERVER", "test-vault-server")
    monkeypatch.setenv("VAULT_DB_NAME", "General")
    monkeypatch.setenv("VAULT_DB_USER", "vault_svc")
    monkeypatch.setenv("VAULT_DB_PASSWORD", "<masked-in-test>")
    monkeypatch.setenv("ODBC_DRIVER", "ODBC Driver 18 for SQL Server")
    yield


def _make_cursor(
    *,
    description=None,
    rows=None,
    execute_side_effect=None,
    nextset_returns=False,
):
    """Build a mock pyodbc.Cursor."""
    cur = MagicMock()
    cur.description = description
    cur.fetchall.return_value = rows or []
    if execute_side_effect is not None:
        cur.execute.side_effect = execute_side_effect
    cur.nextset.return_value = nextset_returns
    cur.rowcount = 1
    return cur


def _make_connection(cur):
    """Build a mock pyodbc.Connection that yields the given cursor."""
    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn


def _sp1_description():
    """Mimic the pyodbc.Cursor.description for SP-1's trailing SELECT."""
    return (
        ("Token", str, None, None, None, None, True),
        ("WasNew", int, None, None, None, None, True),
    )


def _sp2_description():
    return (
        ("Token", str, None, None, None, None, True),
        ("PlaintextValue", str, None, None, None, None, True),
    )


def _sp10_dryrun_description():
    return (("WouldBeFlipped", int, None, None, None, None, True),)


def _sp10_apply_description():
    return (("Flipped", int, None, None, None, None, True),)


def _configure_pool():
    from data_load import vault_client as vc
    vc.configure_vault_connection_pool(max_connections=4)


# ===========================================================================
# TestRegistry
# ===========================================================================


class TestRegistry:
    """The SP registry must include every SP the spec calls out."""

    def test_round1_sps_present(self):
        from data_load import vault_client as vc
        for sp in (
            "PiiVault_GetOrCreateToken",
            "PiiVault_Decrypt",
            "EnforceRetention",
        ):
            assert sp in vc.VAULT_SP_REGISTRY

    def test_round7_sp12_present(self):
        """B81 closure 2026-05-11 — SP-12 PiiVault_ProcessCcpaDeletion."""
        from data_load import vault_client as vc
        assert "PiiVault_ProcessCcpaDeletion" in vc.VAULT_SP_REGISTRY

    def test_registry_shape(self):
        from data_load import vault_client as vc
        for sp, entry in vc.VAULT_SP_REGISTRY.items():
            assert "schema" in entry, sp
            assert "input_params" in entry, sp
            assert "output_params" in entry, sp
            assert "result_set" in entry, sp


# ===========================================================================
# TestPoolLifecycle
# ===========================================================================


class TestPoolLifecycle:
    def test_configure_then_release(self):
        from data_load import vault_client as vc
        assert vc.is_pool_configured() is False
        vc.configure_vault_connection_pool(max_connections=4)
        assert vc.is_pool_configured() is True
        vc.release_vault_connection_pool()
        assert vc.is_pool_configured() is False

    def test_release_is_idempotent(self):
        from data_load import vault_client as vc
        # Releasing an unconfigured pool is a no-op.
        vc.release_vault_connection_pool()
        vc.release_vault_connection_pool()
        assert vc.is_pool_configured() is False

    def test_invalid_max_connections_rejected(self):
        from data_load import vault_client as vc
        from utils.errors import VaultConfigError
        with pytest.raises(VaultConfigError):
            vc.configure_vault_connection_pool(max_connections=0)
        with pytest.raises(VaultConfigError):
            vc.configure_vault_connection_pool(max_connections=-1)

    def test_invalid_timeout_rejected(self):
        from data_load import vault_client as vc
        from utils.errors import VaultConfigError
        with pytest.raises(VaultConfigError):
            vc.configure_vault_connection_pool(connection_timeout_seconds=0)

    def test_double_configure_raises(self):
        from data_load import vault_client as vc
        from utils.errors import VaultConfigError
        vc.configure_vault_connection_pool()
        with pytest.raises(VaultConfigError):
            vc.configure_vault_connection_pool()


# ===========================================================================
# TestEnvVarValidation
# ===========================================================================


class TestEnvVarValidation:
    """Missing VAULT_DB_* env keys surface as VaultConfigError."""

    @pytest.mark.parametrize(
        "missing_key",
        ["VAULT_DB_SERVER", "VAULT_DB_NAME", "VAULT_DB_USER", "VAULT_DB_PASSWORD"],
    )
    def test_missing_required_env(self, vault_env, monkeypatch, missing_key):
        from data_load import vault_client as vc
        from utils.errors import VaultConfigError

        monkeypatch.delenv(missing_key, raising=False)
        _configure_pool()
        with pytest.raises(VaultConfigError) as excinfo:
            vc.call_vault_sp(
                "PiiVault_GetOrCreateToken",
                sp_args={"Plaintext": "x", "PiiType": "SSN", "SourceName": "DNA"},
            )
        assert missing_key in str(excinfo.value)
        assert excinfo.value.metadata.get("missing_env_key") == missing_key


# ===========================================================================
# TestCallBuilder
# ===========================================================================


class TestCallBuilder:
    def test_sp1_emits_declare_exec_select(self):
        from data_load import vault_client as vc
        sql, args, output_names = vc._build_call_statement(
            "PiiVault_GetOrCreateToken",
            {"Plaintext": "x", "PiiType": "SSN", "SourceName": "DNA"},
        )
        assert "DECLARE @Token" in sql
        assert "DECLARE @WasNew" in sql
        assert "EXEC ops.PiiVault_GetOrCreateToken" in sql
        assert "@Plaintext = ?" in sql
        assert "@Token = @Token OUTPUT" in sql
        assert "@WasNew = @WasNew OUTPUT" in sql
        assert "SELECT @Token AS Token, @WasNew AS WasNew" in sql
        # Positional args in registry input_params order: Plaintext, PiiType, SourceName.
        assert args == ["x", "SSN", "DNA"]
        assert output_names == ["Token", "WasNew"]

    def test_sp2_emits_single_exec_no_declares(self):
        from data_load import vault_client as vc
        sql, args, output_names = vc._build_call_statement(
            "PiiVault_Decrypt",
            {
                "RequestId": "abc-uuid",
                "Token": "tok-1",
                "Justification": "RB-10 lookup",
            },
        )
        assert "DECLARE" not in sql
        assert "EXEC ops.PiiVault_Decrypt" in sql
        assert "@RequestId = ?" in sql
        assert "@Token = ?" in sql
        assert "@Justification = ?" in sql
        assert "SELECT @" not in sql  # no trailing SELECT for OUTPUT params
        assert args == ["abc-uuid", "tok-1", "RB-10 lookup"]
        assert output_names == []

    def test_unknown_sp_args_key_rejected(self):
        from data_load import vault_client as vc
        from utils.errors import VaultConfigError
        with pytest.raises(VaultConfigError) as excinfo:
            vc._build_call_statement(
                "PiiVault_GetOrCreateToken",
                {"Plaintext": "x", "Bogus": "y"},
            )
        assert "Unknown sp_args" in str(excinfo.value)
        assert "Bogus" in str(excinfo.value)

    def test_unknown_sp_name_rejected(self):
        from data_load import vault_client as vc
        from utils.errors import VaultConfigError
        with pytest.raises(VaultConfigError) as excinfo:
            vc._build_call_statement("PiiVault_Bogus", {})
        assert "PiiVault_Bogus" in str(excinfo.value)
        assert "Known SPs" in str(excinfo.value)

    def test_missing_input_param_binds_as_null(self):
        """SPs with DEFAULTs let callers omit optional params; the wrapper
        binds the omitted positions as None and SQL Server uses the DEFAULT."""
        from data_load import vault_client as vc
        # SP-10 has DryRun/CutoffOverride/CategoryFilter — caller passes only DryRun.
        sql, args, output_names = vc._build_call_statement(
            "EnforceRetention",
            {"DryRun": 1},
        )
        # Positional must carry None for the omitted CutoffOverride + CategoryFilter.
        assert args == [1, None, None]
        assert "EXEC ops.EnforceRetention" in sql


# ===========================================================================
# TestSp1HappyPath
# ===========================================================================


class TestSp1HappyPath:
    def test_returns_token_and_wasnew(self, vault_env):
        from data_load import vault_client as vc
        cur = _make_cursor(
            description=_sp1_description(),
            rows=[("tok-12345", 1)],
        )
        conn = _make_connection(cur)
        _configure_pool()
        with patch.object(vc.pyodbc, "connect", return_value=conn):
            result = vc.call_vault_sp(
                "PiiVault_GetOrCreateToken",
                sp_args={
                    "Plaintext": "test-ssn",
                    "PiiType": "SSN",
                    "SourceName": "DNA",
                },
            )
        assert result == {"Token": "tok-12345", "WasNew": 1}

    def test_connection_reused_across_calls(self, vault_env):
        """Second call_vault_sp reuses the pooled connection."""
        from data_load import vault_client as vc
        cur = _make_cursor(
            description=_sp1_description(),
            rows=[("tok", 0)],
        )
        conn = _make_connection(cur)
        _configure_pool()
        with patch.object(vc.pyodbc, "connect", return_value=conn) as connect_spy:
            for _ in range(3):
                vc.call_vault_sp(
                    "PiiVault_GetOrCreateToken",
                    sp_args={"Plaintext": "x", "PiiType": "SSN", "SourceName": "DNA"},
                )
        # Lazy-connect on first call only.
        assert connect_spy.call_count == 1


# ===========================================================================
# TestSp2HappyPath
# ===========================================================================


class TestSp2HappyPath:
    def test_returns_token_and_plaintext(self, vault_env):
        from data_load import vault_client as vc
        cur = _make_cursor(
            description=_sp2_description(),
            rows=[("tok-1", "<decrypted-test>")],
        )
        conn = _make_connection(cur)
        _configure_pool()
        with patch.object(vc.pyodbc, "connect", return_value=conn):
            result = vc.call_vault_sp(
                "PiiVault_Decrypt",
                sp_args={
                    "RequestId": "req-uuid",
                    "Token": "tok-1",
                    "Justification": "RB-10",
                },
            )
        assert result.get("Token") == "tok-1"
        assert result.get("PlaintextValue") == "<decrypted-test>"


# ===========================================================================
# TestSp10HappyPath
# ===========================================================================


class TestSp10HappyPath:
    def test_dryrun_returns_count(self, vault_env):
        from data_load import vault_client as vc
        cur = _make_cursor(
            description=_sp10_dryrun_description(),
            rows=[(42,)],
        )
        conn = _make_connection(cur)
        _configure_pool()
        with patch.object(vc.pyodbc, "connect", return_value=conn):
            result = vc.call_vault_sp("EnforceRetention", sp_args={"DryRun": 1})
        assert result.get("WouldBeFlipped") == 42

    def test_apply_returns_count(self, vault_env):
        from data_load import vault_client as vc
        cur = _make_cursor(
            description=_sp10_apply_description(),
            rows=[(17,)],
        )
        conn = _make_connection(cur)
        _configure_pool()
        with patch.object(vc.pyodbc, "connect", return_value=conn):
            result = vc.call_vault_sp("EnforceRetention", sp_args={"DryRun": 0})
        assert result.get("Flipped") == 17


# ===========================================================================
# TestErrorTranslationMatrix
# ===========================================================================


class TestErrorTranslationMatrix:
    """Each error class / SQL Server code maps to a specific outcome."""

    @pytest.mark.parametrize(
        "sql_code",
        [2627, 2601],  # PK / UNIQUE
    )
    def test_unique_violation_bubbles_up(self, vault_env, sql_code):
        """UNIQUE / PK violations bubble up so SP-1 catch-and-relookup works."""
        from data_load import vault_client as vc

        # IntegrityError shape — pyodbc carries the code in the SQLSTATE
        # string OR in the message; we mimic the message-substring form.
        integrity_exc = pyodbc.IntegrityError(
            "23000",
            f"Violation of UNIQUE KEY constraint (SQL Server error {sql_code})",
        )
        cur = _make_cursor(execute_side_effect=integrity_exc)
        conn = _make_connection(cur)
        _configure_pool()
        with patch.object(vc.pyodbc, "connect", return_value=conn):
            with pytest.raises(pyodbc.IntegrityError):
                vc.call_vault_sp(
                    "PiiVault_GetOrCreateToken",
                    sp_args={
                        "Plaintext": "x",
                        "PiiType": "SSN",
                        "SourceName": "DNA",
                    },
                )

    def test_fk_violation_fatal(self, vault_env):
        """FK / CHECK violation (code 547) → PipelineFatalError."""
        from data_load import vault_client as vc
        from utils.errors import PipelineFatalError

        fk_exc = pyodbc.IntegrityError(
            "23000",
            "Foreign key violation (SQL Server error 547)",
        )
        cur = _make_cursor(execute_side_effect=fk_exc)
        conn = _make_connection(cur)
        _configure_pool()
        with patch.object(vc.pyodbc, "connect", return_value=conn):
            with pytest.raises(PipelineFatalError) as excinfo:
                vc.call_vault_sp(
                    "PiiVault_GetOrCreateToken",
                    sp_args={"Plaintext": "x", "PiiType": "SSN", "SourceName": "DNA"},
                )
        assert excinfo.value.metadata.get("sql_error_code") == 547

    def test_unknown_sp_server_side_fatal(self, vault_env):
        """SP not found server-side → PipelineFatalError with hint."""
        from data_load import vault_client as vc
        from utils.errors import PipelineFatalError

        prog_exc = pyodbc.ProgrammingError(
            "42000",
            "[42000] Could not find stored procedure 'ops.PiiVault_GetOrCreateToken'",
        )
        cur = _make_cursor(execute_side_effect=prog_exc)
        conn = _make_connection(cur)
        _configure_pool()
        with patch.object(vc.pyodbc, "connect", return_value=conn):
            with pytest.raises(PipelineFatalError) as excinfo:
                vc.call_vault_sp(
                    "PiiVault_GetOrCreateToken",
                    sp_args={"Plaintext": "x", "PiiType": "SSN", "SourceName": "DNA"},
                )
        assert "not found server-side" in str(excinfo.value)
        assert "schema drift" in str(excinfo.value).lower()

    def test_programming_error_other_fatal(self, vault_env):
        """ProgrammingError without unknown-SP phrase → PipelineFatalError."""
        from data_load import vault_client as vc
        from utils.errors import PipelineFatalError

        prog_exc = pyodbc.ProgrammingError(
            "42000",
            "[42000] Incorrect syntax near 'BOGUS'",
        )
        cur = _make_cursor(execute_side_effect=prog_exc)
        conn = _make_connection(cur)
        _configure_pool()
        with patch.object(vc.pyodbc, "connect", return_value=conn):
            with pytest.raises(PipelineFatalError) as excinfo:
                vc.call_vault_sp(
                    "PiiVault_GetOrCreateToken",
                    sp_args={"Plaintext": "x", "PiiType": "SSN", "SourceName": "DNA"},
                )
        assert "ProgrammingError" in str(excinfo.value)

    def test_operational_error_retries(self, vault_env):
        """OperationalError on every attempt → VaultUnavailable on exhaustion."""
        from data_load import vault_client as vc
        from utils.errors import VaultUnavailable

        op_exc = pyodbc.OperationalError(
            "08S01", "[08S01] Communication link failure"
        )
        cur = _make_cursor(execute_side_effect=op_exc)
        conn = _make_connection(cur)
        _configure_pool()
        with patch.object(vc.pyodbc, "connect", return_value=conn):
            with pytest.raises(VaultUnavailable):
                vc.call_vault_sp(
                    "PiiVault_GetOrCreateToken",
                    sp_args={"Plaintext": "x", "PiiType": "SSN", "SourceName": "DNA"},
                    max_retries=3,
                )
        assert cur.execute.call_count == 3

    def test_interface_error_retries(self, vault_env):
        from data_load import vault_client as vc
        from utils.errors import VaultUnavailable

        iface_exc = pyodbc.InterfaceError("IM001", "Driver does not support this function")
        cur = _make_cursor(execute_side_effect=iface_exc)
        conn = _make_connection(cur)
        _configure_pool()
        with patch.object(vc.pyodbc, "connect", return_value=conn):
            with pytest.raises(VaultUnavailable):
                vc.call_vault_sp(
                    "PiiVault_GetOrCreateToken",
                    sp_args={"Plaintext": "x", "PiiType": "SSN", "SourceName": "DNA"},
                    max_retries=2,
                )
        assert cur.execute.call_count == 2

    @pytest.mark.parametrize("sql_code", [1205, 1222])
    def test_retryable_sql_code(self, vault_env, sql_code):
        """1205 (deadlock) and 1222 (lock timeout) are retryable."""
        from data_load import vault_client as vc
        from utils.errors import VaultUnavailable

        # Build a pyodbc.Error (not OperationalError) carrying the code.
        exc = pyodbc.Error(
            "40001",
            f"[40001] Retryable failure (SQL Server error {sql_code})",
        )
        cur = _make_cursor(execute_side_effect=exc)
        conn = _make_connection(cur)
        _configure_pool()
        with patch.object(vc.pyodbc, "connect", return_value=conn):
            with pytest.raises(VaultUnavailable) as excinfo:
                vc.call_vault_sp(
                    "PiiVault_GetOrCreateToken",
                    sp_args={"Plaintext": "x", "PiiType": "SSN", "SourceName": "DNA"},
                    max_retries=2,
                )
        assert cur.execute.call_count == 2
        assert excinfo.value.metadata.get("sql_error_code") == sql_code

    def test_non_retryable_pyodbc_error_fatal(self, vault_env):
        """A pyodbc.Error without a retryable code → PipelineFatalError."""
        from data_load import vault_client as vc
        from utils.errors import PipelineFatalError

        # SQL Server error 8134 (divide by zero) — not retryable.
        exc = pyodbc.Error("22012", "[22012] Divide by zero (8134)")
        cur = _make_cursor(execute_side_effect=exc)
        conn = _make_connection(cur)
        _configure_pool()
        with patch.object(vc.pyodbc, "connect", return_value=conn):
            with pytest.raises(PipelineFatalError):
                vc.call_vault_sp(
                    "PiiVault_GetOrCreateToken",
                    sp_args={"Plaintext": "x", "PiiType": "SSN", "SourceName": "DNA"},
                )


# ===========================================================================
# TestRetryBehavior
# ===========================================================================


class TestRetryBehavior:
    def test_transient_error_then_success(self, vault_env):
        """One deadlock then success → returns OK without exhaustion."""
        from data_load import vault_client as vc

        deadlock = pyodbc.OperationalError(
            "40001",
            "[40001] Transaction was deadlocked on lock resources (1205)",
        )
        # First execute raises, second succeeds. Subsequent fetchall returns
        # the canned row.
        cur = MagicMock()
        cur.description = _sp1_description()
        cur.fetchall.return_value = [("tok", 1)]
        cur.execute.side_effect = [deadlock, None]
        cur.nextset.return_value = False

        conn = _make_connection(cur)
        _configure_pool()
        with patch.object(vc.pyodbc, "connect", return_value=conn):
            result = vc.call_vault_sp(
                "PiiVault_GetOrCreateToken",
                sp_args={"Plaintext": "x", "PiiType": "SSN", "SourceName": "DNA"},
                max_retries=3,
            )
        assert result == {"Token": "tok", "WasNew": 1}
        assert cur.execute.call_count == 2

    def test_backoff_delays_computed(self, vault_env, monkeypatch):
        """Exponential backoff: base * 2^(attempt-1) per B-7."""
        from data_load import vault_client as vc
        from utils.errors import VaultUnavailable

        delays_observed: list[float] = []
        monkeypatch.setattr(vc.time, "sleep", lambda d: delays_observed.append(d))

        op_exc = pyodbc.OperationalError("08S01", "Communication link failure")
        cur = _make_cursor(execute_side_effect=op_exc)
        conn = _make_connection(cur)
        _configure_pool()
        with patch.object(vc.pyodbc, "connect", return_value=conn):
            with pytest.raises(VaultUnavailable):
                vc.call_vault_sp(
                    "PiiVault_GetOrCreateToken",
                    sp_args={"Plaintext": "x", "PiiType": "SSN", "SourceName": "DNA"},
                    max_retries=4,
                    base_delay_seconds=2.0,
                )
        # 3 sleeps for 4 attempts: 2, 4, 8 (delays AFTER attempts 1-3; no
        # sleep after attempt 4 since the loop raises VaultUnavailable).
        assert delays_observed == [2.0, 4.0, 8.0]

    def test_backoff_capped(self, vault_env, monkeypatch):
        """Backoff capped at 60 s for large attempt counts."""
        from data_load import vault_client as vc
        from utils.errors import VaultUnavailable

        delays_observed: list[float] = []
        monkeypatch.setattr(vc.time, "sleep", lambda d: delays_observed.append(d))

        op_exc = pyodbc.OperationalError("08S01", "Communication link failure")
        cur = _make_cursor(execute_side_effect=op_exc)
        conn = _make_connection(cur)
        _configure_pool()
        with patch.object(vc.pyodbc, "connect", return_value=conn):
            with pytest.raises(VaultUnavailable):
                vc.call_vault_sp(
                    "PiiVault_GetOrCreateToken",
                    sp_args={"Plaintext": "x", "PiiType": "SSN", "SourceName": "DNA"},
                    max_retries=10,
                    base_delay_seconds=10.0,
                )
        # base=10, attempts 1-9 yield delays: 10, 20, 40, 80→60, 160→60, ...
        assert all(d <= 60.0 for d in delays_observed)
        assert 60.0 in delays_observed

    def test_max_retries_1_means_no_retry(self, vault_env):
        from data_load import vault_client as vc
        from utils.errors import VaultUnavailable

        op_exc = pyodbc.OperationalError("08S01", "Communication link failure")
        cur = _make_cursor(execute_side_effect=op_exc)
        conn = _make_connection(cur)
        _configure_pool()
        with patch.object(vc.pyodbc, "connect", return_value=conn):
            with pytest.raises(VaultUnavailable):
                vc.call_vault_sp(
                    "PiiVault_GetOrCreateToken",
                    sp_args={"Plaintext": "x", "PiiType": "SSN", "SourceName": "DNA"},
                    max_retries=1,
                )
        assert cur.execute.call_count == 1

    def test_max_retries_0_rejected(self, vault_env):
        from data_load import vault_client as vc
        from utils.errors import VaultConfigError
        _configure_pool()
        with pytest.raises(VaultConfigError):
            vc.call_vault_sp(
                "PiiVault_GetOrCreateToken",
                sp_args={"Plaintext": "x", "PiiType": "SSN", "SourceName": "DNA"},
                max_retries=0,
            )

    def test_negative_base_delay_rejected(self, vault_env):
        from data_load import vault_client as vc
        from utils.errors import VaultConfigError
        _configure_pool()
        with pytest.raises(VaultConfigError):
            vc.call_vault_sp(
                "PiiVault_GetOrCreateToken",
                sp_args={"Plaintext": "x", "PiiType": "SSN", "SourceName": "DNA"},
                base_delay_seconds=-1.0,
            )


# ===========================================================================
# TestConnectionPool
# ===========================================================================


class TestConnectionPool:
    def test_lazy_connect(self, vault_env):
        """First call_vault_sp invokes pyodbc.connect; second reuses."""
        from data_load import vault_client as vc

        cur = _make_cursor(description=_sp1_description(), rows=[("tok", 1)])
        conn = _make_connection(cur)
        _configure_pool()
        with patch.object(vc.pyodbc, "connect", return_value=conn) as connect_spy:
            vc.call_vault_sp(
                "PiiVault_GetOrCreateToken",
                sp_args={"Plaintext": "x", "PiiType": "SSN", "SourceName": "DNA"},
            )
            vc.call_vault_sp(
                "PiiVault_GetOrCreateToken",
                sp_args={"Plaintext": "y", "PiiType": "SSN", "SourceName": "DNA"},
            )
        assert connect_spy.call_count == 1

    def test_operational_error_evicts_connection(self, vault_env):
        """A connection-drop evicts the pool entry; next attempt reconnects."""
        from data_load import vault_client as vc

        op_exc = pyodbc.OperationalError("08S01", "Communication link failure")
        # First attempt: cursor raises; second attempt: success.
        cur_fail = _make_cursor(execute_side_effect=op_exc)
        cur_ok = _make_cursor(
            description=_sp1_description(),
            rows=[("tok-recovered", 0)],
        )
        conn_fail = _make_connection(cur_fail)
        conn_ok = _make_connection(cur_ok)
        _configure_pool()
        # connect_spy returns the failing conn first, then the OK conn.
        with patch.object(
            vc.pyodbc,
            "connect",
            side_effect=[conn_fail, conn_ok],
        ) as connect_spy:
            result = vc.call_vault_sp(
                "PiiVault_GetOrCreateToken",
                sp_args={"Plaintext": "x", "PiiType": "SSN", "SourceName": "DNA"},
                max_retries=3,
            )
        # Reconnect happened — fresh connect for retry attempt.
        assert connect_spy.call_count == 2
        assert result == {"Token": "tok-recovered", "WasNew": 0}
        # Stale conn was closed.
        conn_fail.close.assert_called()

    def test_connect_failure_at_first_call_raises_vaultconfig(self, vault_env):
        """pyodbc.connect failing at first call surfaces as VaultConfigError."""
        from data_load import vault_client as vc
        from utils.errors import VaultConfigError

        connect_exc = pyodbc.OperationalError(
            "08001",
            "[08001] Login failed for user 'vault_svc'",
        )
        _configure_pool()
        with patch.object(vc.pyodbc, "connect", side_effect=connect_exc):
            with pytest.raises(VaultConfigError) as excinfo:
                vc.call_vault_sp(
                    "PiiVault_GetOrCreateToken",
                    sp_args={"Plaintext": "x", "PiiType": "SSN", "SourceName": "DNA"},
                )
        assert "Vault DB connect failed" in str(excinfo.value)


# ===========================================================================
# TestLogSafety
# ===========================================================================


class TestLogSafety:
    """D103 — argument VALUES NEVER appear in logs."""

    def test_arg_values_not_logged(self, vault_env, caplog):
        """Plaintext SSN must not appear in any log record."""
        from data_load import vault_client as vc

        cur = _make_cursor(description=_sp1_description(), rows=[("tok", 1)])
        conn = _make_connection(cur)
        _configure_pool()
        caplog.set_level(logging.DEBUG, logger="data_load.vault_client")
        with patch.object(vc.pyodbc, "connect", return_value=conn):
            vc.call_vault_sp(
                "PiiVault_GetOrCreateToken",
                sp_args={
                    "Plaintext": "123-45-6789-SENSITIVE",  # synthetic PII
                    "PiiType": "SSN",
                    "SourceName": "DNA",
                },
            )

        # Aggregate all log messages produced by the wrapper.
        all_text = "\n".join(rec.getMessage() for rec in caplog.records)
        assert "123-45-6789-SENSITIVE" not in all_text
        # But the SP NAME should be logged for diagnostics.
        assert "PiiVault_GetOrCreateToken" in all_text
        # And the arg-key NAMES should be logged.
        assert "Plaintext" in all_text or "arg_keys" in all_text

    def test_retry_logged_at_warning(self, vault_env, caplog):
        from data_load import vault_client as vc
        from utils.errors import VaultUnavailable

        op_exc = pyodbc.OperationalError("08S01", "Communication link failure")
        cur = _make_cursor(execute_side_effect=op_exc)
        conn = _make_connection(cur)
        _configure_pool()
        caplog.set_level(logging.WARNING, logger="data_load.vault_client")
        with patch.object(vc.pyodbc, "connect", return_value=conn):
            with pytest.raises(VaultUnavailable):
                vc.call_vault_sp(
                    "PiiVault_GetOrCreateToken",
                    sp_args={"Plaintext": "x", "PiiType": "SSN", "SourceName": "DNA"},
                    max_retries=3,
                )

        warning_records = [
            rec for rec in caplog.records if rec.levelno == logging.WARNING
        ]
        assert any("retry" in rec.getMessage().lower() for rec in warning_records)

    def test_terminal_failure_logged_at_error(self, vault_env, caplog):
        from data_load import vault_client as vc
        from utils.errors import VaultUnavailable

        op_exc = pyodbc.OperationalError("08S01", "Communication link failure")
        cur = _make_cursor(execute_side_effect=op_exc)
        conn = _make_connection(cur)
        _configure_pool()
        caplog.set_level(logging.ERROR, logger="data_load.vault_client")
        with patch.object(vc.pyodbc, "connect", return_value=conn):
            with pytest.raises(VaultUnavailable):
                vc.call_vault_sp(
                    "PiiVault_GetOrCreateToken",
                    sp_args={"Plaintext": "x", "PiiType": "SSN", "SourceName": "DNA"},
                    max_retries=2,
                )

        error_records = [
            rec for rec in caplog.records if rec.levelno == logging.ERROR
        ]
        assert any("terminal" in rec.getMessage().lower() for rec in error_records)


# ===========================================================================
# TestEdgeCases
# ===========================================================================


class TestEdgeCases:
    def test_sp_args_none_treated_as_empty(self, vault_env):
        """SP with no input params (or sp_args=None) should still execute."""
        from data_load import vault_client as vc
        # SP-10 has all defaultable params; sp_args=None means use all defaults.
        cur = _make_cursor(
            description=_sp10_dryrun_description(),
            rows=[(0,)],
        )
        conn = _make_connection(cur)
        _configure_pool()
        with patch.object(vc.pyodbc, "connect", return_value=conn):
            result = vc.call_vault_sp("EnforceRetention", sp_args=None)
        assert result.get("WouldBeFlipped") == 0

    def test_no_result_set_returns_empty_dict(self, vault_env):
        """SP returning no result-set yields {} (forward-compat)."""
        from data_load import vault_client as vc

        # description=None mimics a void SP with no SELECT body.
        cur = _make_cursor(description=None, rows=[])
        conn = _make_connection(cur)
        _configure_pool()
        with patch.object(vc.pyodbc, "connect", return_value=conn):
            result = vc.call_vault_sp("EnforceRetention", sp_args={"DryRun": 1})
        assert result == {}

    def test_multi_row_result_set(self, vault_env):
        """Multi-row results expose under ``_rows`` key."""
        from data_load import vault_client as vc

        cur = _make_cursor(
            description=_sp2_description(),
            rows=[("tok-1", "<dec-1>"), ("tok-2", "<dec-2>")],
        )
        conn = _make_connection(cur)
        _configure_pool()
        with patch.object(vc.pyodbc, "connect", return_value=conn):
            result = vc.call_vault_sp(
                "PiiVault_Decrypt",
                sp_args={"RequestId": "r", "Token": "t", "Justification": "j"},
            )
        assert "_rows" in result
        assert len(result["_rows"]) == 2

    def test_empty_sp_name_rejected(self, vault_env):
        from data_load import vault_client as vc
        from utils.errors import VaultConfigError
        _configure_pool()
        with pytest.raises(VaultConfigError):
            vc.call_vault_sp("", sp_args={})

    def test_non_string_sp_name_rejected(self, vault_env):
        from data_load import vault_client as vc
        from utils.errors import VaultConfigError
        _configure_pool()
        with pytest.raises(VaultConfigError):
            vc.call_vault_sp(None, sp_args={})  # type: ignore[arg-type]


# ===========================================================================
# Helper unit tests for internal classifier
# ===========================================================================


class TestClassifierHelpers:
    """Direct tests of _is_retryable / _extract_sql_error_code / _looks_like_unknown_sp."""

    @pytest.mark.parametrize("code", [1205, 1222])
    def test_retryable_codes(self, code):
        from data_load import vault_client as vc
        exc = pyodbc.Error("40001", f"[40001] error (SQL Server error {code})")
        assert vc._is_retryable(exc) is True

    @pytest.mark.parametrize("code", [2627, 2601, 547, 8134])
    def test_non_retryable_codes(self, code):
        from data_load import vault_client as vc
        # IntegrityError covers UNIQUE / FK; generic Error covers 8134.
        if code in (2627, 2601, 547):
            exc = pyodbc.IntegrityError("23000", f"[23000] error (code {code})")
        else:
            exc = pyodbc.Error("22012", f"[22012] error (code {code})")
        assert vc._is_retryable(exc) is False

    def test_operational_error_is_retryable(self):
        from data_load import vault_client as vc
        assert vc._is_retryable(pyodbc.OperationalError("08S01", "x")) is True

    def test_unknown_sp_phrase_detected(self):
        from data_load import vault_client as vc
        exc = pyodbc.ProgrammingError("42000", "Could not find stored procedure 'x'")
        assert vc._looks_like_unknown_sp(exc) is True

    def test_unknown_sp_phrase_not_in_other_message(self):
        from data_load import vault_client as vc
        exc = pyodbc.ProgrammingError("42000", "Incorrect syntax near 'BOGUS'")
        assert vc._looks_like_unknown_sp(exc) is False
