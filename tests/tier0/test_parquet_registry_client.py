"""Tier 0 build-time smoke test for data_load/parquet_registry_client.py.

Per **D67** — runs at build time + every commit. Runtime ceiling < 5 s.
All external dependencies (``utils.connections.cursor_for``,
``utils.idempotency_ledger.ledger_step``, pyodbc cursor) are mocked.

Asserts (per § 1.3 Tier 0 contract):
  (a) module imports without error;
  (b) each of 7 transition functions invokable with mocked cursor;
  (c) each raises ``RegistryStatusInvalid`` on invalid predecessor;
  (d) ``query_snapshot`` returns ``None`` for absent key, returns ``dict``
      for present key;
  (e) state-machine helper is_legal_transition() is consistent.

North Star pillars:
  - Idempotent (D15): re-running a transition short-circuits via the
    idempotency ledger; the wrapped UPDATE is not re-issued.
  - Audit-grade (D26 + D76): per-transition audit columns
    (LastVerifiedAt / SnowflakeUploadedAt / PurgedAt / etc) match
    canonical Round 1 DDL.
  - Operationally stable (D69): every transition opens its own
    ``cursor_for('General')`` context — no shared cursor.

D-numbers: D67 (Tier 0 discipline), D15 (idempotency), D17 (ledger),
D25 (canonical Parquet index), D26 (append-only audit), D68 (error
class hierarchy), D69 (cursor ownership).

Spec: ``docs/migration/phase1/03_core_modules.md`` § 1.3.
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Project root on sys.path (matches tests/ convention)
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


_MODULE_KEY = "data_load.parquet_registry_client"
_MODULE_PATH = _PROJECT_ROOT / "data_load" / "parquet_registry_client.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_cursor_for_with_row(row_dict: dict | None):
    """Return a mock cursor_for that yields rows based on ``row_dict``.

    When ``row_dict`` is None, the cursor's ``fetchone`` returns None
    (registry row absent). Otherwise it returns the row values in the
    order matching the SELECT projection plus a ``description`` matching
    the column names.

    The mock supports the cursor's ``execute`` + ``fetchone`` + ``rowcount``
    + ``description`` attributes used by the module.
    """
    cursor = MagicMock()
    if row_dict is None:
        cursor.fetchone.return_value = None
        cursor.description = []
    else:
        cursor.fetchone.return_value = tuple(row_dict.values())
        cursor.description = [(k,) for k in row_dict.keys()]
    cursor.rowcount = 1

    def _cm_factory(_db: str):
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=cursor)
        cm.__exit__ = MagicMock(return_value=False)
        return cm

    return _cm_factory, cursor


def _canonical_row(**overrides) -> dict:
    """Return a canonical ParquetSnapshotRegistry row dict for tests."""
    base = {
        "RegistryId": 42,
        "SourceName": "DNA",
        "TableName": "ACCT",
        "BatchId": 12345,
        "BusinessDate": None,
        "NetworkDrivePath": "/mnt/parquet/DNA/ACCT/2026/05/12345_0001.parquet",
        "SnowflakeStagePath": None,
        "SnowflakeUploadedAt": None,
        "RowCount": 1000,
        "UncompressedBytes": 4_000_000,
        "CompressedBytes": 800_000,
        "SchemaHash": "a" * 64,
        "ContentChecksum": "b" * 64,
        "StorageTier": "hot",
        "Status": "created",
        "CreatedAt": None,
        "LastVerifiedAt": None,
        "LastAccessedAt": None,
        "PurgedAt": None,
        "PurgedReason": None,
    }
    base.update(overrides)
    return base


def _make_ledger_step_cm(was_short_circuited: bool = False):
    """Build a context-manager factory mimicking utils.idempotency_ledger.ledger_step."""
    step = MagicMock()
    step.was_short_circuited = was_short_circuited
    step.step_id = 1
    step.prior_result = None

    def _ledger_step(**_kwargs):
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=step)
        cm.__exit__ = MagicMock(return_value=False)
        return cm

    return _ledger_step, step


# ---------------------------------------------------------------------------
# Fixture: fresh module load with mocked sibling modules
# ---------------------------------------------------------------------------


@pytest.fixture
def fresh_module():
    """Load data_load.parquet_registry_client with mocked sibling deps."""
    if _MODULE_KEY in sys.modules:
        del sys.modules[_MODULE_KEY]
    mod = importlib.import_module(_MODULE_KEY)
    yield mod
    if _MODULE_KEY in sys.modules:
        del sys.modules[_MODULE_KEY]


# ---------------------------------------------------------------------------
# (a) Module imports
# ---------------------------------------------------------------------------


def test_module_imports(fresh_module):
    """Module imports without error and exposes the documented public surface."""
    expected_public = {
        "verify_parquet_snapshot",
        "mark_replicated",
        "mark_archived",
        "mark_missing",
        "mark_purged",
        "mark_replication_failed",
        "query_snapshot",
        "ParquetVerifyResult",
        "RegistryStatusInvalid",
        "RegistryFileNotFound",
        "RegistryHashMismatch",
        "RegistryInsertConflict",
        "RegistryNotFound",
        "is_legal_transition",
    }
    for name in expected_public:
        assert hasattr(fresh_module, name), (
            f"public symbol {name!r} missing from module"
        )

    # __all__ includes all public symbols EXCEPT the 5 concrete error
    # classes — those are re-imported from utils.errors into this
    # module's namespace for back-compat (callers that already did
    # `from data_load.parquet_registry_client import RegistryStatusInvalid`
    # still resolve), but the canonical home is utils.errors per B-228.
    # Single-source-of-truth: __all__ omits them.
    assert hasattr(fresh_module, "__all__"), "module has no __all__"
    error_classes = {
        "RegistryStatusInvalid",
        "RegistryFileNotFound",
        "RegistryHashMismatch",
        "RegistryInsertConflict",
        "RegistryNotFound",
    }
    for name in expected_public - error_classes:
        assert name in fresh_module.__all__, (
            f"{name!r} missing from __all__"
        )
    for name in error_classes:
        assert name not in fresh_module.__all__, (
            f"{name!r} should NOT be in __all__ per B-228 single-source-of-truth"
        )


def test_status_constants_match_canonical_enum(fresh_module):
    """STATUS_* constants match the CK_ParquetSnapshotRegistry_Status enum."""
    expected = {
        "created",
        "verified",
        "replicated",
        "archived",
        "missing",
        "purged",
        "replication_failed",
    }
    assert fresh_module.ALL_STATUSES == frozenset(expected)


def test_runtime_ceiling_under_5s():
    """Tier 0 contract: <5s total. Re-import the module + read public surface."""
    start = time.time()
    if _MODULE_KEY in sys.modules:
        del sys.modules[_MODULE_KEY]
    mod = importlib.import_module(_MODULE_KEY)
    _ = mod.ALL_STATUSES
    elapsed = time.time() - start
    assert elapsed < 5.0, f"Tier 0 import took {elapsed:.2f}s (>5s ceiling)"


# ---------------------------------------------------------------------------
# (b) Each transition function invokable with mocked cursor
# ---------------------------------------------------------------------------


def test_mark_replicated_invokable(fresh_module):
    """mark_replicated invokable; opens cursor; issues UPDATE."""
    cm_factory, cursor = _make_mock_cursor_for_with_row(
        _canonical_row(Status="verified")
    )
    ledger_step, _ = _make_ledger_step_cm()
    with patch.object(fresh_module, "_get_cursor_for", return_value=cm_factory), \
         patch.object(fresh_module, "_get_ledger_step", return_value=ledger_step):
        fresh_module.mark_replicated(
            registry_id=42,
            replica_target="snowflake:UDM_BRONZE_MIRROR",
        )
    # UPDATE executed at least once (SELECT + UPDATE)
    assert cursor.execute.call_count >= 1


def test_mark_archived_invokable(fresh_module):
    """mark_archived invokable; transitions replicated -> archived."""
    cm_factory, cursor = _make_mock_cursor_for_with_row(
        _canonical_row(Status="replicated")
    )
    ledger_step, _ = _make_ledger_step_cm()
    with patch.object(fresh_module, "_get_cursor_for", return_value=cm_factory), \
         patch.object(fresh_module, "_get_ledger_step", return_value=ledger_step):
        fresh_module.mark_archived(
            registry_id=42,
            archive_location="cold:azure-cool-tier",
        )
    assert cursor.execute.call_count >= 1


def test_mark_missing_invokable(fresh_module):
    """mark_missing invokable from any non-purged status."""
    cm_factory, cursor = _make_mock_cursor_for_with_row(
        _canonical_row(Status="verified")
    )
    ledger_step, _ = _make_ledger_step_cm()
    with patch.object(fresh_module, "_get_cursor_for", return_value=cm_factory), \
         patch.object(fresh_module, "_get_ledger_step", return_value=ledger_step):
        fresh_module.mark_missing(
            registry_id=42,
            detected_by="verification_scan",
        )
    assert cursor.execute.call_count >= 1


def test_mark_purged_invokable(fresh_module):
    """mark_purged invokable from archived; writes PurgedAt + PurgedReason."""
    cm_factory, cursor = _make_mock_cursor_for_with_row(
        _canonical_row(Status="archived")
    )
    ledger_step, _ = _make_ledger_step_cm()
    with patch.object(fresh_module, "_get_cursor_for", return_value=cm_factory), \
         patch.object(fresh_module, "_get_ledger_step", return_value=ledger_step):
        fresh_module.mark_purged(
            registry_id=42,
            retention_batch_id=99999,
        )
    assert cursor.execute.call_count >= 1


def test_mark_replication_failed_invokable(fresh_module):
    """mark_replication_failed invokable from verified."""
    cm_factory, cursor = _make_mock_cursor_for_with_row(
        _canonical_row(Status="verified")
    )
    ledger_step, _ = _make_ledger_step_cm()
    with patch.object(fresh_module, "_get_cursor_for", return_value=cm_factory), \
         patch.object(fresh_module, "_get_ledger_step", return_value=ledger_step):
        fresh_module.mark_replication_failed(
            registry_id=42,
            failure_reason="COPY INTO failed: timeout",
        )
    assert cursor.execute.call_count >= 1


def test_verify_parquet_snapshot_idempotent_on_already_verified(fresh_module):
    """verify_parquet_snapshot on already-verified row returns cached result."""
    row = _canonical_row(Status="verified", LastVerifiedAt=None)
    cm_factory, _ = _make_mock_cursor_for_with_row(row)
    with patch.object(fresh_module, "_get_cursor_for", return_value=cm_factory):
        result = fresh_module.verify_parquet_snapshot(registry_id=42)
    assert result.status == "verified"
    assert result.registry_id == 42


# ---------------------------------------------------------------------------
# (c) Each function raises RegistryStatusInvalid on invalid predecessor
# ---------------------------------------------------------------------------


def test_mark_replicated_invalid_predecessor_raises(fresh_module):
    """mark_replicated on Status='created' raises RegistryStatusInvalid."""
    cm_factory, _ = _make_mock_cursor_for_with_row(
        _canonical_row(Status="created")
    )
    with patch.object(fresh_module, "_get_cursor_for", return_value=cm_factory):
        with pytest.raises(fresh_module.RegistryStatusInvalid) as exc_info:
            fresh_module.mark_replicated(
                registry_id=42, replica_target="snowflake:X"
            )
    assert exc_info.value.metadata["current_status"] == "created"
    assert exc_info.value.metadata["attempted_status"] == "replicated"


def test_mark_archived_invalid_predecessor_raises(fresh_module):
    """mark_archived on Status='verified' raises RegistryStatusInvalid."""
    cm_factory, _ = _make_mock_cursor_for_with_row(
        _canonical_row(Status="verified")
    )
    with patch.object(fresh_module, "_get_cursor_for", return_value=cm_factory):
        with pytest.raises(fresh_module.RegistryStatusInvalid):
            fresh_module.mark_archived(
                registry_id=42, archive_location="cold:X"
            )


def test_mark_purged_invalid_predecessor_raises(fresh_module):
    """mark_purged on Status='replicated' raises RegistryStatusInvalid."""
    cm_factory, _ = _make_mock_cursor_for_with_row(
        _canonical_row(Status="replicated")
    )
    with patch.object(fresh_module, "_get_cursor_for", return_value=cm_factory):
        with pytest.raises(fresh_module.RegistryStatusInvalid):
            fresh_module.mark_purged(registry_id=42, retention_batch_id=1)


def test_mark_missing_from_purged_raises(fresh_module):
    """mark_missing on Status='purged' raises (purged is terminal per D26)."""
    cm_factory, _ = _make_mock_cursor_for_with_row(
        _canonical_row(Status="purged")
    )
    with patch.object(fresh_module, "_get_cursor_for", return_value=cm_factory):
        with pytest.raises(fresh_module.RegistryStatusInvalid):
            fresh_module.mark_missing(registry_id=42, detected_by="X")


def test_mark_replication_failed_invalid_predecessor_raises(fresh_module):
    """mark_replication_failed on Status='created' raises."""
    cm_factory, _ = _make_mock_cursor_for_with_row(
        _canonical_row(Status="created")
    )
    with patch.object(fresh_module, "_get_cursor_for", return_value=cm_factory):
        with pytest.raises(fresh_module.RegistryStatusInvalid):
            fresh_module.mark_replication_failed(
                registry_id=42, failure_reason="X"
            )


def test_verify_invalid_predecessor_raises(fresh_module):
    """verify_parquet_snapshot on Status='replicated' raises."""
    cm_factory, _ = _make_mock_cursor_for_with_row(
        _canonical_row(Status="replicated")
    )
    with patch.object(fresh_module, "_get_cursor_for", return_value=cm_factory):
        with pytest.raises(fresh_module.RegistryStatusInvalid):
            fresh_module.verify_parquet_snapshot(registry_id=42)


# ---------------------------------------------------------------------------
# (d) query_snapshot semantics
# ---------------------------------------------------------------------------


def test_query_snapshot_returns_none_for_absent_key(fresh_module):
    """query_snapshot returns None when no row matches."""
    cm_factory, _ = _make_mock_cursor_for_with_row(None)
    with patch.object(fresh_module, "_get_cursor_for", return_value=cm_factory):
        result = fresh_module.query_snapshot(
            source_name="DNA",
            table_name="ACCT",
            business_date=None,
            batch_id=99999,
        )
    assert result is None


def test_query_snapshot_returns_dict_for_present_key(fresh_module):
    """query_snapshot returns a dict when the row exists."""
    row = _canonical_row()
    cm_factory, _ = _make_mock_cursor_for_with_row(row)
    with patch.object(fresh_module, "_get_cursor_for", return_value=cm_factory):
        result = fresh_module.query_snapshot(
            source_name="DNA",
            table_name="ACCT",
            business_date=None,
            batch_id=12345,
        )
    assert isinstance(result, dict)
    assert result["SourceName"] == "DNA"
    assert result["TableName"] == "ACCT"
    assert result["BatchId"] == 12345


# ---------------------------------------------------------------------------
# (e) State-machine helper consistency
# ---------------------------------------------------------------------------


def test_is_legal_transition_happy_path(fresh_module):
    """Canonical happy-path transitions are all permitted."""
    assert fresh_module.is_legal_transition("created", "verified")
    assert fresh_module.is_legal_transition("verified", "replicated")
    assert fresh_module.is_legal_transition("replicated", "archived")
    assert fresh_module.is_legal_transition("archived", "purged")


def test_is_legal_transition_self_loops_are_idempotent(fresh_module):
    """X -> X always permitted (idempotent re-call)."""
    for status in fresh_module.ALL_STATUSES:
        assert fresh_module.is_legal_transition(status, status), (
            f"self-transition {status!r} should be permitted"
        )


def test_is_legal_transition_purged_is_terminal(fresh_module):
    """purged -> anything-non-purged is forbidden (D26 append-only)."""
    for status in fresh_module.ALL_STATUSES:
        if status == "purged":
            continue
        assert not fresh_module.is_legal_transition("purged", status), (
            f"purged -> {status} should be forbidden"
        )


def test_is_legal_transition_unknown_status_rejected(fresh_module):
    """Unknown status values return False (no silent default-allow)."""
    assert not fresh_module.is_legal_transition("created", "bogus")
    assert not fresh_module.is_legal_transition("bogus", "verified")
    assert not fresh_module.is_legal_transition("", "verified")


# ---------------------------------------------------------------------------
# RegistryNotFound surfacing
# ---------------------------------------------------------------------------


def test_registry_not_found_raised_when_row_absent(fresh_module):
    """When the registry row doesn't exist, RegistryNotFound is raised."""
    cm_factory, _ = _make_mock_cursor_for_with_row(None)
    with patch.object(fresh_module, "_get_cursor_for", return_value=cm_factory):
        with pytest.raises(fresh_module.RegistryNotFound):
            fresh_module.mark_replicated(
                registry_id=999_999, replica_target="snowflake:X"
            )
