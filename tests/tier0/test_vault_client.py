"""Tier 0 build-time smoke test for data_load/vault_client.py.

Per D67 — runs at build time + every commit. Runtime ceiling < 5 s. All
external dependencies (pyodbc connection + cursor, env vars) are mocked.
No live SQL Server required.

North Star pillars:
  - Audit-grade (D103 security model — wrapper logs SP NAME + arg-key
    NAMES + arg COUNT; NEVER argument values; smoke verifies the SP-1
    success path returns the canned OUTPUT params).
  - Operationally stable (D67 Tier 0 discipline: import + ctor + happy-path
    + retry-exhaustion path in < 5 s with zero external I/O).
  - Idempotent (D17: wrapper is thin pass-through; retry on transient
    errors per B-7; smoke asserts the retry loop fires the expected
    number of attempts before final failure).

D-numbers: D6, D17, D67, D68, D69, D103.
B-numbers: M6 (build-tracker entry — closed by authoring this module +
its tests); B85 (utils/errors.py dependency closed); B-222 (open
naming collision — informational note in module docstring).

Spec: phase1/03_core_modules.md § 2.3 + phase1/01_database_schema.md
SP-1 / SP-2 / SP-10 (re-read at build time per Pitfall #9.l).
"""
from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock, patch

import pyodbc
import pytest

# ---------------------------------------------------------------------------
# Project root on sys.path (matches tests/ convention)
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Fixtures — clear pool between tests; mock pyodbc.connect uniformly
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_vault_pool():
    """Reset the per-process vault pool so each test starts clean."""
    from data_load import vault_client as vc
    vc.release_vault_connection_pool()
    yield
    vc.release_vault_connection_pool()


@pytest.fixture(autouse=True)
def _patch_sleep(monkeypatch):
    """Patch time.sleep so retry tests run sub-second (Tier 0 < 5 s)."""
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    # Also patch the module-level binding so the wrapper picks up the no-op.
    from data_load import vault_client as vc
    monkeypatch.setattr(vc.time, "sleep", lambda _seconds: None)
    yield


@pytest.fixture
def vault_env(monkeypatch):
    """Set the VAULT_DB_* env keys to synthetic values."""
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
    fetchall_side_effect=None,
    execute_side_effect=None,
):
    """Build a mock pyodbc.Cursor."""
    cur = MagicMock()
    cur.description = description
    if fetchall_side_effect is not None:
        cur.fetchall.side_effect = fetchall_side_effect
    else:
        cur.fetchall.return_value = rows or []
    if execute_side_effect is not None:
        cur.execute.side_effect = execute_side_effect
    cur.nextset.return_value = False
    cur.rowcount = 1
    return cur


def _make_connection(cur):
    """Build a mock pyodbc.Connection that yields the given cursor."""
    conn = MagicMock()
    conn.cursor.return_value = cur
    return conn


# ---------------------------------------------------------------------------
# (a) Module imports cleanly
# ---------------------------------------------------------------------------


def test_module_imports():
    """credentials_loader imports without side effects on a non-RHEL host."""
    from data_load import vault_client as vc

    assert hasattr(vc, "call_vault_sp")
    assert hasattr(vc, "configure_vault_connection_pool")
    assert hasattr(vc, "release_vault_connection_pool")
    assert hasattr(vc, "is_pool_configured")
    assert hasattr(vc, "VAULT_SP_REGISTRY")
    # Registry must include the Round 1 SPs the spec calls out.
    assert "PiiVault_GetOrCreateToken" in vc.VAULT_SP_REGISTRY
    assert "PiiVault_Decrypt" in vc.VAULT_SP_REGISTRY
    assert "EnforceRetention" in vc.VAULT_SP_REGISTRY


# ---------------------------------------------------------------------------
# (b) + (c) call_vault_sp invokable with mocked cursor returning canned OUTPUT
# ---------------------------------------------------------------------------


def test_call_vault_sp_get_or_create_token_returns_dict(vault_env):
    """SP-1 happy path returns the canned OUTPUT params as a dict."""
    from data_load import vault_client as vc

    # Canned OUTPUT params per the spec § 2.3 test-surface assertion.
    canned_row = ("test-token", 1)
    description = (
        ("Token", str, None, None, None, None, True),
        ("WasNew", int, None, None, None, None, True),
    )
    # Attach description to the row tuple as pyodbc rows carry
    # `cursor_description`. The wrapper has a description-attached fast
    # path AND a fallback to OUTPUT param names; either way the result
    # should be {Token, WasNew}.
    cur = _make_cursor(description=description, rows=[canned_row])
    conn = _make_connection(cur)

    vc.configure_vault_connection_pool(max_connections=4)
    with patch.object(vc.pyodbc, "connect", return_value=conn) as connect_spy:
        result = vc.call_vault_sp(
            "PiiVault_GetOrCreateToken",
            sp_args={"Plaintext": "test", "PiiType": "SSN", "SourceName": "DNA"},
        )

    assert isinstance(result, dict)
    assert result.get("Token") == "test-token"
    assert result.get("WasNew") == 1
    # Connect was called exactly once (lazy connect on first call_vault_sp).
    assert connect_spy.call_count == 1


# ---------------------------------------------------------------------------
# (d) configure_vault_connection_pool invokable; second call raises
# ---------------------------------------------------------------------------


def test_configure_pool_idempotency_guard():
    """First configure succeeds; second call raises VaultConfigError."""
    from data_load import vault_client as vc
    from utils.errors import VaultConfigError

    vc.configure_vault_connection_pool(max_connections=4)
    assert vc.is_pool_configured() is True

    with pytest.raises(VaultConfigError) as excinfo:
        vc.configure_vault_connection_pool(max_connections=8)
    assert "already configured" in str(excinfo.value).lower()


# ---------------------------------------------------------------------------
# (e) mocked SQL deadlock (error 1205) triggers retry per B-7
# ---------------------------------------------------------------------------


def test_deadlock_triggers_retry(vault_env):
    """3 attempts total before failure on persistent deadlock (1205)."""
    from data_load import vault_client as vc
    from utils.errors import VaultUnavailable

    # Build an exception that the wrapper classifies as retryable: a
    # pyodbc.Error subclass with SQL error code 1205 in the message.
    deadlock_exc = pyodbc.OperationalError(
        "40001",
        "[40001] Transaction was deadlocked on lock resources (1205)",
    )

    # The wrapper invokes a fresh cursor per attempt; we make execute raise
    # the deadlock on every attempt to drive the retry loop.
    cur = _make_cursor(execute_side_effect=deadlock_exc)
    conn = _make_connection(cur)

    vc.configure_vault_connection_pool(max_connections=4)
    with patch.object(vc.pyodbc, "connect", return_value=conn):
        with pytest.raises(VaultUnavailable) as excinfo:
            vc.call_vault_sp(
                "PiiVault_GetOrCreateToken",
                sp_args={"Plaintext": "x", "PiiType": "SSN", "SourceName": "DNA"},
                max_retries=3,
            )

    # Mock asserts 3 cursor execute invocations before final failure.
    assert cur.execute.call_count == 3
    # Metadata records the attempt count.
    assert excinfo.value.metadata.get("attempts") == 3


# ---------------------------------------------------------------------------
# (f) VaultUnavailable raised on retry exhaustion
# ---------------------------------------------------------------------------


def test_vault_unavailable_on_exhaustion(vault_env):
    """Final retry raises VaultUnavailable with cause attached."""
    from data_load import vault_client as vc
    from utils.errors import VaultUnavailable

    # Connection-drop on every attempt.
    op_err = pyodbc.OperationalError(
        "08S01",
        "[08S01] Communication link failure",
    )
    cur = _make_cursor(execute_side_effect=op_err)
    conn = _make_connection(cur)

    vc.configure_vault_connection_pool(max_connections=4)
    with patch.object(vc.pyodbc, "connect", return_value=conn):
        with pytest.raises(VaultUnavailable) as excinfo:
            vc.call_vault_sp(
                "PiiVault_GetOrCreateToken",
                sp_args={"Plaintext": "x", "PiiType": "SSN", "SourceName": "DNA"},
                max_retries=2,
            )

    # __cause__ chain attaches the original pyodbc.OperationalError.
    assert isinstance(excinfo.value.__cause__, pyodbc.OperationalError)
    # Metadata captures error class for postmortem.
    assert excinfo.value.metadata.get("error_class") == "OperationalError"


# ---------------------------------------------------------------------------
# Performance gate — runtime ceiling < 5 s for the full Tier 0 suite
# (enforced implicitly by patching time.sleep + mocking pyodbc).
# ---------------------------------------------------------------------------


def test_runtime_under_5s(vault_env):
    """Sanity check: all Tier 0 paths complete sub-second with mocks."""
    from data_load import vault_client as vc

    cur = _make_cursor(description=(("WouldBeFlipped", int, None, None, None, None, True),), rows=[(42,)])
    conn = _make_connection(cur)

    vc.configure_vault_connection_pool(max_connections=4)
    started = time.monotonic()
    with patch.object(vc.pyodbc, "connect", return_value=conn):
        result = vc.call_vault_sp("EnforceRetention", sp_args={"DryRun": 1})
    elapsed = time.monotonic() - started
    assert elapsed < 1.0  # < 1 s for a single mocked call; 5 s budget is plenty
    assert isinstance(result, dict)
    assert result.get("WouldBeFlipped") == 42


# ---------------------------------------------------------------------------
# call_vault_sp rejects an unknown sp_name pre-flight (typo guard)
# ---------------------------------------------------------------------------


def test_unknown_sp_name_rejected_locally(vault_env):
    """Per Pitfall #9 — unknown sp_name fails FAST locally (no round-trip)."""
    from data_load import vault_client as vc
    from utils.errors import VaultConfigError

    vc.configure_vault_connection_pool(max_connections=4)
    with pytest.raises(VaultConfigError) as excinfo:
        vc.call_vault_sp("PiiVault_Bogus", sp_args={"X": 1})
    assert "PiiVault_Bogus" in str(excinfo.value)
    assert "Known SPs" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Pool-not-configured → VaultConfigError (lazy-connect contract)
# ---------------------------------------------------------------------------


def test_pool_not_configured_raises_on_call(vault_env):
    """call_vault_sp without prior configure raises VaultConfigError."""
    from data_load import vault_client as vc
    from utils.errors import VaultConfigError

    # No configure_vault_connection_pool() — fresh process state.
    with pytest.raises(VaultConfigError) as excinfo:
        vc.call_vault_sp(
            "PiiVault_GetOrCreateToken",
            sp_args={"Plaintext": "x", "PiiType": "SSN", "SourceName": "DNA"},
        )
    assert "not configured" in str(excinfo.value).lower()
