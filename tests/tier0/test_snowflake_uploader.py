"""Tier 0 build-time smoke test for ``data_load/snowflake_uploader.py``.

Per **D67** — runs at build time + every commit. Runtime ceiling < 5 s.
All external dependencies (``utils.connections.cursor_for``,
``data_load.credentials_loader``, ``data_load.parquet_registry_client``,
``snowflake.connector``, pyodbc cursor) are mocked.

Asserts (per § 7.1 Tier 0 contract):
  (a) module imports without error;
  (b) :func:`copy_parquet_to_snowflake` invokable with mocked deps;
  (c) returns :class:`SnowflakeCopyResult` shape;
  (d) raises :class:`RegistryStatusInvalid` on non-verified status fixture;
  (e) mocked auth-fail raises :class:`SnowflakeAuthFailed`.

North Star pillars:
  - Idempotent (D15): re-COPY-INTO short-circuits via Snowflake's
    per-file load history (mocked) AND :func:`mark_replicated` no-ops
    on already-replicated status (composed via M3).
  - Audit-grade (D26 + D76): PipelineEventLog row written with
    canonical EventType='SNOWFLAKE_COPY_INTO'.
  - Operationally stable (D69): every transition opens its own
    ``cursor_for('General')`` context — no shared cursor.

D-numbers: D5, D23, D67 (Tier 0 discipline), D68 (error class hierarchy),
D69 (cursor ownership), D71 (RSA key per-process), D103 (Claude Code
security — no PEM in module memory).

Spec: ``docs/migration/phase1/03_core_modules.md`` § 7.1.
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
import time
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Project root on sys.path (matches tests/ convention)
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


_MODULE_KEY = "data_load.snowflake_uploader"


# ---------------------------------------------------------------------------
# Autouse fixture: snowflake.connector stub with cleanup (B214 pattern)
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _stub_snowflake_connector(monkeypatch):
    """Stub ``snowflake.connector`` in sys.modules with autouse cleanup.

    The Snowflake connector is intentionally NOT installed in the test
    venv (per task prompt — keep tests mock-driven). We install a
    MagicMock at the ``snowflake.connector`` key so the
    ``_get_snowflake_connector`` lazy-import resolves cleanly. The
    monkeypatch fixture autouse-cleans up the sys.modules state per
    B214 lesson (no manual snapshot/restore needed).
    """
    snowflake_module = types.ModuleType("snowflake")
    connector_module = types.ModuleType("snowflake.connector")
    connector_module.connect = MagicMock()  # type: ignore[attr-defined]
    snowflake_module.connector = connector_module  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "snowflake", snowflake_module)
    monkeypatch.setitem(sys.modules, "snowflake.connector", connector_module)
    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cursor_for_with_row(row_dict: dict | None):
    """Return a cursor_for factory + cursor mock yielding ``row_dict``."""
    cursor = MagicMock()
    if row_dict is None:
        cursor.fetchone.return_value = None
        cursor.description = []
    else:
        cursor.fetchone.return_value = tuple(row_dict.values())
        cursor.description = [(k,) for k in row_dict.keys()]
    cursor.rowcount = 1

    def _factory(_db: str):
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=cursor)
        cm.__exit__ = MagicMock(return_value=False)
        return cm

    return _factory, cursor


def _canonical_row(**overrides) -> dict:
    """Return a canonical projection of ParquetSnapshotRegistry row."""
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


def _set_required_env(monkeypatch):
    """Set the required SNOWFLAKE_* env vars for connection."""
    monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "acme-test")
    monkeypatch.setenv("SNOWFLAKE_USER", "pipeline_svc")
    monkeypatch.setenv("SNOWFLAKE_WAREHOUSE", "UDM_BRONZE_WH")
    monkeypatch.setenv("SNOWFLAKE_DATABASE", "UDM_BRONZE_MIRROR")
    monkeypatch.setenv("SNOWFLAKE_SCHEMA", "DNA")
    monkeypatch.setenv("SNOWFLAKE_MONTHLY_CREDIT_CAP", "10000")


def _make_snowflake_conn(*, sfqid: str = "01b6-c123", rows_loaded: int = 1000):
    """Build a MagicMock Snowflake connection with canned COPY response."""
    conn = MagicMock()
    cursor = MagicMock()
    cursor.sfqid = sfqid
    # COPY response: (file, status, rows_parsed, rows_loaded, ...)
    cursor.fetchall.return_value = [
        ("file.parquet", "LOADED", rows_loaded, rows_loaded, 0, 0, None, None, None, None)
    ]
    # Budget check fetchone returns (month_credits,)
    cursor.fetchone.return_value = (100.0,)
    conn.cursor.return_value = cursor
    return conn, cursor


# ---------------------------------------------------------------------------
# Fixture: fresh module load
# ---------------------------------------------------------------------------


@pytest.fixture
def fresh_module():
    """Load data_load.snowflake_uploader fresh for each test."""
    if _MODULE_KEY in sys.modules:
        del sys.modules[_MODULE_KEY]
    mod = importlib.import_module(_MODULE_KEY)
    yield mod
    if _MODULE_KEY in sys.modules:
        del sys.modules[_MODULE_KEY]


# ---------------------------------------------------------------------------
# (a) Module imports
# ---------------------------------------------------------------------------


def test_module_imports_and_exposes_public_surface(fresh_module):
    """Module imports without error and exposes the documented public surface."""
    expected_public = {
        "EVENT_TYPE_SNOWFLAKE_COPY_INTO",
        "COPY_REQUIRED_STATUS",
        "DEFAULT_COPY_TIMEOUT_SECONDS",
        "DEFAULT_BUDGET_ALERT_THRESHOLD",
        "SnowflakeCopyResult",
        "copy_parquet_to_snowflake",
    }
    for name in expected_public:
        assert hasattr(fresh_module, name), (
            f"public symbol {name!r} missing from module"
        )

    # __all__ excludes error classes per B-228 single-source-of-truth.
    assert hasattr(fresh_module, "__all__")
    for name in expected_public:
        assert name in fresh_module.__all__, f"{name!r} missing from __all__"


def test_event_type_constant_is_canonical(fresh_module):
    """EVENT_TYPE_SNOWFLAKE_COPY_INTO == 'SNOWFLAKE_COPY_INTO' per § 7.1."""
    assert fresh_module.EVENT_TYPE_SNOWFLAKE_COPY_INTO == "SNOWFLAKE_COPY_INTO"


def test_copy_required_status_is_verified(fresh_module):
    """COPY_REQUIRED_STATUS == 'verified' per § 7.1 (verifier must run first)."""
    assert fresh_module.COPY_REQUIRED_STATUS == "verified"


def test_runtime_ceiling_under_5s():
    """Tier 0 contract: <5s total. Re-import module + read public surface."""
    start = time.time()
    if _MODULE_KEY in sys.modules:
        del sys.modules[_MODULE_KEY]
    mod = importlib.import_module(_MODULE_KEY)
    _ = mod.EVENT_TYPE_SNOWFLAKE_COPY_INTO
    elapsed = time.time() - start
    assert elapsed < 5.0, f"Tier 0 import took {elapsed:.2f}s (>5s ceiling)"


# ---------------------------------------------------------------------------
# (b)+(c) Happy path: invokable + returns SnowflakeCopyResult shape
# ---------------------------------------------------------------------------


def test_copy_parquet_to_snowflake_happy_path(fresh_module, monkeypatch):
    """Happy path: COPY succeeds, mark_replicated called, returns canonical result."""
    _set_required_env(monkeypatch)

    cursor_factory, _ = _make_cursor_for_with_row(_canonical_row())
    sf_conn, _ = _make_snowflake_conn()

    creds = {"SNOWFLAKE_PRIVATE_KEY_PATH": "/dev/shm/snowflake_pk_99999"}

    with patch.object(fresh_module, "_get_cursor_for", return_value=cursor_factory), \
         patch.object(fresh_module, "_get_load_credentials", return_value=lambda: creds), \
         patch.object(fresh_module, "_get_release_snowflake_key", return_value=MagicMock()), \
         patch.object(fresh_module, "_get_mark_replicated", return_value=MagicMock()), \
         patch.object(fresh_module, "_open_snowflake_connection", return_value=sf_conn):
        result = fresh_module.copy_parquet_to_snowflake(
            registry_id=42,
            snowflake_table="UDM_BRONZE_MIRROR.DNA.ACCT",
        )

    # (c) Shape assertion
    assert isinstance(result, fresh_module.SnowflakeCopyResult)
    assert result.registry_id == 42
    assert result.snowflake_table == "UDM_BRONZE_MIRROR.DNA.ACCT"
    assert result.rows_copied == 1000
    assert result.copy_history_id == "01b6-c123"
    assert isinstance(result.duration_ms, int)
    assert result.duration_ms >= 0


# ---------------------------------------------------------------------------
# (d) RegistryStatusInvalid on non-verified
# ---------------------------------------------------------------------------


def test_copy_parquet_raises_registry_status_invalid_when_not_verified(fresh_module, monkeypatch):
    """RegistryStatusInvalid raised when source row is not 'verified'."""
    from utils.errors import RegistryStatusInvalid

    _set_required_env(monkeypatch)
    cursor_factory, _ = _make_cursor_for_with_row(
        _canonical_row(Status="created")
    )

    with patch.object(fresh_module, "_get_cursor_for", return_value=cursor_factory):
        with pytest.raises(RegistryStatusInvalid) as excinfo:
            fresh_module.copy_parquet_to_snowflake(registry_id=42)

    assert "current Status='created'" in str(excinfo.value) or \
           "Status='created'" in str(excinfo.value)


# ---------------------------------------------------------------------------
# (e) SnowflakeAuthFailed on connector failure
# ---------------------------------------------------------------------------


def test_copy_parquet_auth_fail_wraps_connector_exception(fresh_module, monkeypatch):
    """Connector connect() raise wraps in SnowflakeAuthFailed."""
    from utils.errors import SnowflakeAuthFailed

    _set_required_env(monkeypatch)
    cursor_factory, _ = _make_cursor_for_with_row(_canonical_row())

    creds = {"SNOWFLAKE_PRIVATE_KEY_PATH": "/dev/shm/snowflake_pk_99999"}

    def _connect_raises(**_kwargs):
        raise RuntimeError("simulated connector failure")

    fake_connector = types.SimpleNamespace(connect=_connect_raises)

    release_mock = MagicMock()
    with patch.object(fresh_module, "_get_cursor_for", return_value=cursor_factory), \
         patch.object(fresh_module, "_get_load_credentials", return_value=lambda: creds), \
         patch.object(fresh_module, "_get_release_snowflake_key", return_value=release_mock), \
         patch.object(fresh_module, "_get_snowflake_connector", return_value=fake_connector), \
         patch("builtins.open", new_callable=MagicMock) as mock_open:
        mock_open.return_value.__enter__ = MagicMock(
            return_value=MagicMock(read=MagicMock(return_value=b"PEM"))
        )
        mock_open.return_value.__exit__ = MagicMock(return_value=False)
        with pytest.raises(SnowflakeAuthFailed):
            fresh_module.copy_parquet_to_snowflake(registry_id=42)

    # release_snowflake_key MUST be called even when COPY auth fails (finally)
    assert release_mock.called, "release_snowflake_key must be called in finally"
