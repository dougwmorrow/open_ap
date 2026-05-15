"""Tier 1 unit tests for data_load/parquet_registry_client.py.

Tests run on every commit. No live DB, no live network required. All
external dependencies mocked with unittest.mock.

North Star pillars addressed:
  - Idempotent (D15): re-call after success is a no-op (the idempotency
    ledger short-circuits AND the row-level status check is a no-op).
  - Audit-grade (D26 + D76): per-transition audit columns
    (LastVerifiedAt / SnowflakeUploadedAt / PurgedAt / etc) written
    field-for-field per Round 1 DDL.
  - Operationally stable (D69): each transition opens its own
    cursor_for('General') context — no shared cursor across boundaries.
  - Traceability (D25): ParquetSnapshotRegistry is the canonical Parquet
    index; this client centralizes the lifecycle.

Edge case IDs (per 04_EDGE_CASES.md N-series — N1..N8 ParquetSnapshotRegistry):
  - N3 (concurrent verify on same row): UPDATE has CHECK predicate on
    prior status; lost race re-fetches.
  - N5 (verify of file-absent row): RegistryFileNotFound raised; caller
    follows with mark_missing.
  - N7 (hash mismatch on verification): RegistryHashMismatch raised with
    expected + computed values for forensic reconstruction.
  - N8 (purged is terminal): mark_missing from Status='purged' rejected
    (D26 append-only).

Decision citations:
  D2 (Stage dropped), D4 (network drive Parquet), D15 (idempotency),
  D17 (ledger), D25 (canonical Parquet index), D26 (append-only),
  D30 (7-year retention), D45.2 (Parquet config), D67 (Tier 0 disc),
  D68 (error class hierarchy), D69 (cursor ownership), D92 (forward-only).

Spec: ``docs/migration/phase1/03_core_modules.md`` § 1.3.
"""
from __future__ import annotations

import importlib
import sys
from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Project root on sys.path
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_MODULE_KEY = "data_load.parquet_registry_client"


# ---------------------------------------------------------------------------
# Fixture: fresh module load
# ---------------------------------------------------------------------------


@pytest.fixture
def mod():
    """Load data_load.parquet_registry_client fresh for each test."""
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


def _make_cursor_for(row_dict: dict | None, *, rowcount: int = 1):
    """Build a cursor_for mock factory that yields canonical-row tuples."""
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


def _make_ledger_step(was_short_circuited: bool = False):
    step = MagicMock()
    step.was_short_circuited = was_short_circuited
    step.step_id = 1
    step.prior_result = None

    def _factory(**_kwargs):
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=step)
        cm.__exit__ = MagicMock(return_value=False)
        return cm

    return _factory, step


def _patches(mod, cursor_factory, ledger_factory):
    return (
        patch.object(mod, "_get_cursor_for", return_value=cursor_factory),
        patch.object(mod, "_get_ledger_step", return_value=ledger_factory),
    )


# ---------------------------------------------------------------------------
# State-machine: exhaustive legal + illegal transition pairs
# ---------------------------------------------------------------------------


def _all_pairs(statuses):
    for a in statuses:
        for b in statuses:
            yield a, b


def test_state_machine_exhaustive_legal_set(mod):
    """Every legal transition in _LEGAL_TRANSITIONS returns True."""
    for current, allowed in mod._LEGAL_TRANSITIONS.items():
        for attempted in allowed:
            assert mod.is_legal_transition(current, attempted), (
                f"declared-legal {current} -> {attempted} returned False"
            )


def test_state_machine_exhaustive_illegal_set(mod):
    """Every (current, attempted) NOT in the graph + NOT a self-loop returns False."""
    for current, attempted in _all_pairs(mod.ALL_STATUSES):
        if current == attempted:
            continue  # self-loops handled separately
        if attempted in mod._LEGAL_TRANSITIONS.get(current, frozenset()):
            continue  # legal — covered by other test
        assert not mod.is_legal_transition(current, attempted), (
            f"undeclared {current} -> {attempted} returned True (should be False)"
        )


def test_state_machine_purged_is_terminal(mod):
    """purged -> any non-purged status is forbidden (D26 append-only)."""
    assert mod._LEGAL_TRANSITIONS["purged"] == frozenset()


def test_state_machine_missing_is_terminal_under_automated_flow(mod):
    """missing has no automated transitions out (recovery is manual operator)."""
    assert mod._LEGAL_TRANSITIONS["missing"] == frozenset()


def test_state_machine_replication_failed_can_retry(mod):
    """replication_failed -> replicated allowed (operator retry path)."""
    assert "replicated" in mod._LEGAL_TRANSITIONS["replication_failed"]


def test_state_machine_any_non_purged_can_go_missing(mod):
    """Every non-terminal status has 'missing' as a legal target."""
    for status in mod.ALL_STATUSES:
        if status in ("missing", "purged"):
            continue
        assert "missing" in mod._LEGAL_TRANSITIONS.get(status, frozenset()), (
            f"{status} -> missing should be legal"
        )


# ---------------------------------------------------------------------------
# verify_parquet_snapshot — happy path, file-missing, hash-mismatch, idempotent
# ---------------------------------------------------------------------------


def test_verify_happy_path(mod, tmp_path):
    """verify_parquet_snapshot on Status='created' with valid file: flips to verified."""
    # Write a real Parquet stand-in so the SHA computation succeeds
    payload = b"PAR1" + b"\x00" * 100 + b"PAR1"
    file_path = tmp_path / "test.parquet"
    file_path.write_bytes(payload)
    import hashlib
    sha = hashlib.sha256(payload).hexdigest()

    row = _canonical_row(
        Status="created",
        NetworkDrivePath=str(file_path),
        ContentChecksum=sha,
    )
    cursor_factory, cursor = _make_cursor_for(row)
    ledger_factory, step = _make_ledger_step(was_short_circuited=False)

    p1, p2 = _patches(mod, cursor_factory, ledger_factory)
    with p1, p2:
        result = mod.verify_parquet_snapshot(registry_id=42, actor="pipeline")

    assert result.status == "verified"
    assert result.sha256_verified.lower() == sha.lower()
    assert result.row_count_verified == 1000
    # UPDATE was issued (not just SELECT)
    update_calls = [c for c in cursor.execute.call_args_list
                    if "UPDATE" in (c.args[0] if c.args else "")]
    assert len(update_calls) >= 1


def test_verify_file_not_found_raises(mod, tmp_path):
    """verify_parquet_snapshot on missing file raises RegistryFileNotFound."""
    row = _canonical_row(
        Status="created",
        NetworkDrivePath=str(tmp_path / "does_not_exist.parquet"),
    )
    cursor_factory, _ = _make_cursor_for(row)
    p1, p2 = _patches(mod, cursor_factory, lambda **_kw: None)
    with p1, p2:
        with pytest.raises(mod.RegistryFileNotFound) as exc_info:
            mod.verify_parquet_snapshot(registry_id=42)
    assert exc_info.value.metadata["registry_id"] == 42
    assert "does_not_exist" in exc_info.value.metadata["file_path"]


def test_verify_hash_mismatch_raises(mod, tmp_path):
    """verify_parquet_snapshot with hash mismatch raises RegistryHashMismatch."""
    payload = b"PAR1" + b"\x00" * 100 + b"PAR1"
    file_path = tmp_path / "test.parquet"
    file_path.write_bytes(payload)

    row = _canonical_row(
        Status="created",
        NetworkDrivePath=str(file_path),
        ContentChecksum="0" * 64,  # deliberately wrong
    )
    cursor_factory, _ = _make_cursor_for(row)
    p1, p2 = _patches(mod, cursor_factory, lambda **_kw: None)
    with p1, p2:
        with pytest.raises(mod.RegistryHashMismatch) as exc_info:
            mod.verify_parquet_snapshot(registry_id=42)
    assert exc_info.value.metadata["expected_sha256"] == "0" * 64
    assert len(exc_info.value.metadata["computed_sha256"]) == 64


def test_verify_idempotent_already_verified(mod):
    """verify_parquet_snapshot on already-verified row returns cached result, no UPDATE."""
    row = _canonical_row(
        Status="verified",
        LastVerifiedAt=datetime(2026, 5, 12, 14, 30, 0),
    )
    cursor_factory, cursor = _make_cursor_for(row)
    p1, p2 = _patches(mod, cursor_factory, lambda **_kw: None)
    with p1, p2:
        result = mod.verify_parquet_snapshot(registry_id=42)

    assert result.status == "verified"
    # Only the SELECT executed (no UPDATE since already verified)
    update_calls = [c for c in cursor.execute.call_args_list
                    if "UPDATE" in (c.args[0] if c.args else "")]
    assert len(update_calls) == 0


def test_verify_short_circuit_via_ledger(mod, tmp_path):
    """When ledger short-circuits, no UPDATE is issued even on 'created' row."""
    payload = b"PAR1"
    file_path = tmp_path / "test.parquet"
    file_path.write_bytes(payload)
    import hashlib
    sha = hashlib.sha256(payload).hexdigest()

    row = _canonical_row(
        Status="created",
        NetworkDrivePath=str(file_path),
        ContentChecksum=sha,
    )
    cursor_factory, cursor = _make_cursor_for(row)
    ledger_factory, _ = _make_ledger_step(was_short_circuited=True)
    p1, p2 = _patches(mod, cursor_factory, ledger_factory)

    with p1, p2:
        result = mod.verify_parquet_snapshot(registry_id=42)

    assert result.status == "verified"
    update_calls = [c for c in cursor.execute.call_args_list
                    if "UPDATE" in (c.args[0] if c.args else "")]
    assert len(update_calls) == 0


def test_verify_null_content_checksum_falls_back_to_schema_hash(mod, tmp_path):
    """When ContentChecksum is NULL, the function tries SchemaHash but it must match."""
    payload = b"PAR1" + b"\x00" * 50
    file_path = tmp_path / "test.parquet"
    file_path.write_bytes(payload)
    import hashlib
    sha = hashlib.sha256(payload).hexdigest()

    row = _canonical_row(
        Status="created",
        NetworkDrivePath=str(file_path),
        ContentChecksum=None,
        SchemaHash=sha,  # the SchemaHash happens to match — verification passes
    )
    cursor_factory, _ = _make_cursor_for(row)
    ledger_factory, _ = _make_ledger_step()
    p1, p2 = _patches(mod, cursor_factory, ledger_factory)
    with p1, p2:
        result = mod.verify_parquet_snapshot(registry_id=42)
    assert result.status == "verified"


def test_verify_both_hashes_null_raises_hash_mismatch(mod, tmp_path):
    """When BOTH ContentChecksum AND SchemaHash are NULL, raises RegistryHashMismatch."""
    file_path = tmp_path / "test.parquet"
    file_path.write_bytes(b"x")

    row = _canonical_row(
        Status="created",
        NetworkDrivePath=str(file_path),
        ContentChecksum=None,
        SchemaHash=None,
    )
    cursor_factory, _ = _make_cursor_for(row)
    p1, p2 = _patches(mod, cursor_factory, lambda **_kw: None)
    with p1, p2:
        with pytest.raises(mod.RegistryHashMismatch):
            mod.verify_parquet_snapshot(registry_id=42)


# ---------------------------------------------------------------------------
# mark_replicated — happy path + idempotent + retry from replication_failed
# ---------------------------------------------------------------------------


def test_mark_replicated_from_verified(mod):
    """mark_replicated on Status='verified' issues SnowflakeStagePath UPDATE."""
    row = _canonical_row(Status="verified")
    cursor_factory, cursor = _make_cursor_for(row)
    ledger_factory, _ = _make_ledger_step()
    p1, p2 = _patches(mod, cursor_factory, ledger_factory)
    with p1, p2:
        mod.mark_replicated(
            registry_id=42, replica_target="snowflake:UDM_BRONZE_MIRROR"
        )
    update_calls = [c for c in cursor.execute.call_args_list
                    if "UPDATE" in (c.args[0] if c.args else "")]
    assert len(update_calls) == 1
    # Replica target appears in the UPDATE params
    update_params = update_calls[0].args[1]
    assert "snowflake:UDM_BRONZE_MIRROR" in update_params


def test_mark_replicated_retry_from_replication_failed(mod):
    """mark_replicated on Status='replication_failed' is allowed (retry path)."""
    row = _canonical_row(Status="replication_failed")
    cursor_factory, _ = _make_cursor_for(row)
    ledger_factory, _ = _make_ledger_step()
    p1, p2 = _patches(mod, cursor_factory, ledger_factory)
    with p1, p2:
        mod.mark_replicated(registry_id=42, replica_target="snowflake:X")


def test_mark_replicated_idempotent_already_replicated(mod):
    """mark_replicated on already-replicated row is a no-op (no UPDATE)."""
    row = _canonical_row(Status="replicated")
    cursor_factory, cursor = _make_cursor_for(row)
    p1, p2 = _patches(mod, cursor_factory, lambda **_kw: None)
    with p1, p2:
        mod.mark_replicated(registry_id=42, replica_target="X")
    update_calls = [c for c in cursor.execute.call_args_list
                    if "UPDATE" in (c.args[0] if c.args else "")]
    assert len(update_calls) == 0


def test_mark_replicated_from_created_raises(mod):
    """mark_replicated on Status='created' raises RegistryStatusInvalid."""
    row = _canonical_row(Status="created")
    cursor_factory, _ = _make_cursor_for(row)
    p1, p2 = _patches(mod, cursor_factory, lambda **_kw: None)
    with p1, p2:
        with pytest.raises(mod.RegistryStatusInvalid) as exc_info:
            mod.mark_replicated(registry_id=42, replica_target="X")
    assert exc_info.value.metadata["current_status"] == "created"


# ---------------------------------------------------------------------------
# mark_archived — happy path + idempotent + invalid predecessor
# ---------------------------------------------------------------------------


def test_mark_archived_from_replicated(mod):
    """mark_archived on Status='replicated' flips StorageTier to cold."""
    row = _canonical_row(Status="replicated")
    cursor_factory, cursor = _make_cursor_for(row)
    ledger_factory, _ = _make_ledger_step()
    p1, p2 = _patches(mod, cursor_factory, ledger_factory)
    with p1, p2:
        mod.mark_archived(
            registry_id=42, archive_location="cold:azure-cool-tier"
        )
    update_calls = [c for c in cursor.execute.call_args_list
                    if "UPDATE" in (c.args[0] if c.args else "")]
    assert len(update_calls) == 1
    update_params = update_calls[0].args[1]
    # Tier 'cold' is part of the params
    assert "cold" in update_params


def test_mark_archived_idempotent(mod):
    """mark_archived on already-archived row is a no-op."""
    row = _canonical_row(Status="archived")
    cursor_factory, cursor = _make_cursor_for(row)
    p1, p2 = _patches(mod, cursor_factory, lambda **_kw: None)
    with p1, p2:
        mod.mark_archived(registry_id=42, archive_location="X")
    update_calls = [c for c in cursor.execute.call_args_list
                    if "UPDATE" in (c.args[0] if c.args else "")]
    assert len(update_calls) == 0


def test_mark_archived_from_created_raises(mod):
    """mark_archived on Status='created' raises (must be replicated first)."""
    row = _canonical_row(Status="created")
    cursor_factory, _ = _make_cursor_for(row)
    p1, p2 = _patches(mod, cursor_factory, lambda **_kw: None)
    with p1, p2:
        with pytest.raises(mod.RegistryStatusInvalid):
            mod.mark_archived(registry_id=42, archive_location="X")


# ---------------------------------------------------------------------------
# mark_missing — from each non-purged status; rejected from purged
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "from_status",
    ["created", "verified", "replicated", "archived", "replication_failed"],
)
def test_mark_missing_from_any_non_purged(mod, from_status):
    """mark_missing is permitted from every non-purged status."""
    row = _canonical_row(Status=from_status)
    cursor_factory, _ = _make_cursor_for(row)
    ledger_factory, _ = _make_ledger_step()
    p1, p2 = _patches(mod, cursor_factory, ledger_factory)
    with p1, p2:
        mod.mark_missing(registry_id=42, detected_by="test")


def test_mark_missing_from_purged_raises(mod):
    """mark_missing from purged raises (D26 append-only — purged is terminal)."""
    row = _canonical_row(Status="purged")
    cursor_factory, _ = _make_cursor_for(row)
    p1, p2 = _patches(mod, cursor_factory, lambda **_kw: None)
    with p1, p2:
        with pytest.raises(mod.RegistryStatusInvalid):
            mod.mark_missing(registry_id=42, detected_by="test")


def test_mark_missing_idempotent(mod):
    """mark_missing on already-missing row is a no-op."""
    row = _canonical_row(Status="missing")
    cursor_factory, cursor = _make_cursor_for(row)
    p1, p2 = _patches(mod, cursor_factory, lambda **_kw: None)
    with p1, p2:
        mod.mark_missing(registry_id=42, detected_by="X")
    update_calls = [c for c in cursor.execute.call_args_list
                    if "UPDATE" in (c.args[0] if c.args else "")]
    assert len(update_calls) == 0


# ---------------------------------------------------------------------------
# mark_purged — happy path + idempotent + invalid predecessor
# ---------------------------------------------------------------------------


def test_mark_purged_from_archived(mod):
    """mark_purged on Status='archived' writes PurgedAt + PurgedReason."""
    row = _canonical_row(Status="archived")
    cursor_factory, cursor = _make_cursor_for(row)
    ledger_factory, _ = _make_ledger_step()
    p1, p2 = _patches(mod, cursor_factory, ledger_factory)
    with p1, p2:
        mod.mark_purged(registry_id=42, retention_batch_id=99999)
    update_calls = [c for c in cursor.execute.call_args_list
                    if "UPDATE" in (c.args[0] if c.args else "")]
    assert len(update_calls) == 1
    # PurgedReason includes the retention_batch_id (JSON-encoded)
    update_sql = update_calls[0].args[0]
    update_params = update_calls[0].args[1]
    assert "PurgedAt" in update_sql
    assert "PurgedReason" in update_sql
    # retention_batch_id is serialized into PurgedReason JSON
    purged_reason = next(
        (p for p in update_params if isinstance(p, str) and "retention_batch_id" in p),
        None,
    )
    assert purged_reason is not None
    import json
    parsed = json.loads(purged_reason)
    assert parsed["retention_batch_id"] == 99999


def test_mark_purged_idempotent(mod):
    """mark_purged on already-purged row is a no-op."""
    row = _canonical_row(Status="purged")
    cursor_factory, cursor = _make_cursor_for(row)
    p1, p2 = _patches(mod, cursor_factory, lambda **_kw: None)
    with p1, p2:
        mod.mark_purged(registry_id=42, retention_batch_id=1)
    update_calls = [c for c in cursor.execute.call_args_list
                    if "UPDATE" in (c.args[0] if c.args else "")]
    assert len(update_calls) == 0


@pytest.mark.parametrize(
    "from_status",
    ["created", "verified", "replicated", "missing", "replication_failed"],
)
def test_mark_purged_invalid_predecessor_raises(mod, from_status):
    """mark_purged from any non-archived status raises."""
    row = _canonical_row(Status=from_status)
    cursor_factory, _ = _make_cursor_for(row)
    p1, p2 = _patches(mod, cursor_factory, lambda **_kw: None)
    with p1, p2:
        with pytest.raises(mod.RegistryStatusInvalid):
            mod.mark_purged(registry_id=42, retention_batch_id=1)


# ---------------------------------------------------------------------------
# mark_replication_failed — happy path + idempotent
# ---------------------------------------------------------------------------


def test_mark_replication_failed_from_verified(mod):
    """mark_replication_failed on Status='verified' flips to replication_failed."""
    row = _canonical_row(Status="verified")
    cursor_factory, cursor = _make_cursor_for(row)
    ledger_factory, _ = _make_ledger_step()
    p1, p2 = _patches(mod, cursor_factory, ledger_factory)
    with p1, p2:
        mod.mark_replication_failed(
            registry_id=42, failure_reason="COPY INTO timeout"
        )
    update_calls = [c for c in cursor.execute.call_args_list
                    if "UPDATE" in (c.args[0] if c.args else "")]
    assert len(update_calls) == 1


def test_mark_replication_failed_idempotent(mod):
    """mark_replication_failed on already-failed row is a no-op."""
    row = _canonical_row(Status="replication_failed")
    cursor_factory, cursor = _make_cursor_for(row)
    p1, p2 = _patches(mod, cursor_factory, lambda **_kw: None)
    with p1, p2:
        mod.mark_replication_failed(registry_id=42, failure_reason="X")
    update_calls = [c for c in cursor.execute.call_args_list
                    if "UPDATE" in (c.args[0] if c.args else "")]
    assert len(update_calls) == 0


# ---------------------------------------------------------------------------
# query_snapshot — variant signatures + NULL BusinessDate handling
# ---------------------------------------------------------------------------


def test_query_snapshot_business_date_null_uses_is_null(mod):
    """When business_date is None, the SQL uses 'IS NULL' not '= NULL'."""
    row = _canonical_row(BusinessDate=None)
    cursor_factory, cursor = _make_cursor_for(row)
    p1, p2 = _patches(mod, cursor_factory, lambda **_kw: None)
    with p1, p2:
        result = mod.query_snapshot(
            source_name="DNA",
            table_name="ACCT",
            business_date=None,
            batch_id=12345,
        )
    assert result is not None
    # Confirm 'IS NULL' is in the SQL (not '= NULL')
    select_calls = [c for c in cursor.execute.call_args_list
                    if "SELECT" in (c.args[0] if c.args else "")]
    assert any("IS NULL" in c.args[0] for c in select_calls)


def test_query_snapshot_with_business_date(mod):
    """When business_date is set, the SQL uses '= ?' equality."""
    biz_date = date(2026, 5, 12)
    row = _canonical_row(BusinessDate=biz_date)
    cursor_factory, cursor = _make_cursor_for(row)
    p1, p2 = _patches(mod, cursor_factory, lambda **_kw: None)
    with p1, p2:
        result = mod.query_snapshot(
            source_name="DNA",
            table_name="ACCT",
            business_date=biz_date,
            batch_id=12345,
        )
    assert result is not None
    select_calls = [c for c in cursor.execute.call_args_list
                    if "SELECT" in (c.args[0] if c.args else "")]
    sql = select_calls[0].args[0]
    assert "BusinessDate = ?" in sql
    assert "BusinessDate IS NULL" not in sql


def test_query_snapshot_returns_none_on_absent(mod):
    """query_snapshot returns None when no row matches."""
    cursor_factory, _ = _make_cursor_for(None)
    p1, p2 = _patches(mod, cursor_factory, lambda **_kw: None)
    with p1, p2:
        result = mod.query_snapshot(
            source_name="DNA",
            table_name="NONEXISTENT",
            business_date=None,
            batch_id=99999,
        )
    assert result is None


def test_query_snapshot_last_accessed_update_failure_is_fire_and_forget(mod):
    """A LastAccessedAt UPDATE failure does NOT fail the lookup."""
    row = _canonical_row()
    cursor = MagicMock()
    cursor.fetchone.return_value = tuple(row.values())
    cursor.description = [(k,) for k in row.keys()]
    # First call (SELECT) succeeds; second (UPDATE) raises
    cursor.execute.side_effect = [None, RuntimeError("simulated db drop")]

    def _factory(_db: str):
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=cursor)
        cm.__exit__ = MagicMock(return_value=False)
        return cm

    p1 = patch.object(mod, "_get_cursor_for", return_value=_factory)
    with p1:
        # Must NOT raise — best-effort access-time update
        result = mod.query_snapshot(
            source_name="DNA",
            table_name="ACCT",
            business_date=None,
            batch_id=12345,
        )
    assert result is not None


# ---------------------------------------------------------------------------
# RegistryNotFound — every transition surfaces it for nonexistent registry_id
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "transition_name,kwargs",
    [
        ("mark_replicated", {"replica_target": "X"}),
        ("mark_archived", {"archive_location": "X"}),
        ("mark_missing", {"detected_by": "X"}),
        ("mark_purged", {"retention_batch_id": 1}),
        ("mark_replication_failed", {"failure_reason": "X"}),
        ("verify_parquet_snapshot", {}),
    ],
)
def test_registry_not_found_for_missing_id(mod, transition_name, kwargs):
    """Every transition function raises RegistryNotFound for a missing id."""
    cursor_factory, _ = _make_cursor_for(None)
    p1, p2 = _patches(mod, cursor_factory, lambda **_kw: None)
    with p1, p2:
        with pytest.raises(mod.RegistryNotFound):
            func = getattr(mod, transition_name)
            func(registry_id=999_999, **kwargs)


# ---------------------------------------------------------------------------
# Datetime + audit-column invariants
# ---------------------------------------------------------------------------


def test_utcnow_ms_is_naive_and_millisecond_precision(mod):
    """_utcnow_ms returns a naive datetime truncated to ms precision (SCD2-P1-f)."""
    dt = mod._utcnow_ms()
    assert dt.tzinfo is None, "must be naive (no tzinfo) per pyodbc DATETIME2(3) contract"
    assert dt.microsecond % 1000 == 0, "must be millisecond-precision (no sub-ms drift)"


def test_verify_writes_last_verified_at(mod, tmp_path):
    """verify writes LastVerifiedAt naive + ms-precision datetime."""
    payload = b"PAR1"
    file_path = tmp_path / "test.parquet"
    file_path.write_bytes(payload)
    import hashlib
    sha = hashlib.sha256(payload).hexdigest()

    row = _canonical_row(
        Status="created",
        NetworkDrivePath=str(file_path),
        ContentChecksum=sha,
    )
    cursor_factory, cursor = _make_cursor_for(row)
    ledger_factory, _ = _make_ledger_step()
    p1, p2 = _patches(mod, cursor_factory, ledger_factory)
    with p1, p2:
        mod.verify_parquet_snapshot(registry_id=42)

    update_calls = [c for c in cursor.execute.call_args_list
                    if "UPDATE" in (c.args[0] if c.args else "")]
    assert len(update_calls) == 1
    sql = update_calls[0].args[0]
    params = update_calls[0].args[1]
    assert "LastVerifiedAt" in sql
    # The datetime param should be naive
    dt_param = next((p for p in params if isinstance(p, datetime)), None)
    assert dt_param is not None
    assert dt_param.tzinfo is None
    assert dt_param.microsecond % 1000 == 0


# ---------------------------------------------------------------------------
# Ledger-step composition: every mutating transition composes ledger_step
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "transition_name,from_status,kwargs",
    [
        ("mark_replicated", "verified", {"replica_target": "X"}),
        ("mark_archived", "replicated", {"archive_location": "X"}),
        ("mark_missing", "verified", {"detected_by": "X"}),
        ("mark_purged", "archived", {"retention_batch_id": 1}),
        ("mark_replication_failed", "verified", {"failure_reason": "X"}),
    ],
)
def test_ledger_step_composed_for_each_mutating_transition(
    mod, transition_name, from_status, kwargs
):
    """Every mutating transition composes utils.idempotency_ledger.ledger_step."""
    row = _canonical_row(Status=from_status)
    cursor_factory, _ = _make_cursor_for(row)
    ledger_factory = MagicMock()
    step = MagicMock()
    step.was_short_circuited = False

    def _ledger_cm(**kw):
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=step)
        cm.__exit__ = MagicMock(return_value=False)
        return cm

    ledger_factory.side_effect = _ledger_cm

    p1, p2 = _patches(mod, cursor_factory, ledger_factory)
    with p1, p2:
        func = getattr(mod, transition_name)
        func(registry_id=42, **kwargs)

    # ledger_factory was invoked at least once
    assert ledger_factory.call_count >= 1
    # The ledger key includes BatchId / SourceName / TableName from the row
    call_kwargs = ledger_factory.call_args.kwargs
    assert call_kwargs["batch_id"] == 12345
    assert call_kwargs["source_name"] == "DNA"
    assert call_kwargs["table_name"] == "ACCT"


# ---------------------------------------------------------------------------
# Error class semantics
# ---------------------------------------------------------------------------


def test_error_classes_inherit_from_canonical_utils_errors(mod):
    """All concrete errors inherit from the canonical D68 utils.errors hierarchy.

    Per B-228 (refactor 2026-05-13) — local ``ParquetRegistryError`` base
    class removed; the 5 concrete error classes are now subclasses of
    :class:`utils.errors.PipelineFatalError` /
    :class:`utils.errors.PipelineRetryableError`, not of any
    module-local base. The names are still resolvable via
    ``data_load.parquet_registry_client`` (via ``from utils.errors import
    ...`` at module top) so existing callers do not break.
    """
    from utils.errors import (
        PipelineError,
        PipelineFatalError,
        PipelineRetryableError,
    )
    # Per utils/errors.py: D68 two-tier hierarchy. Fatal vs Retryable.
    expected_tier = {
        "RegistryStatusInvalid": PipelineFatalError,
        "RegistryFileNotFound": PipelineRetryableError,  # remount can rescue
        "RegistryHashMismatch": PipelineFatalError,
        "RegistryInsertConflict": PipelineRetryableError,
        "RegistryNotFound": PipelineFatalError,
    }
    for cls_name, base in expected_tier.items():
        cls = getattr(mod, cls_name)
        assert issubclass(cls, base), (
            f"{cls_name} should subclass {base.__name__} per D68 + B-228"
        )
        assert issubclass(cls, PipelineError)  # transitively
        assert issubclass(cls, Exception)
    # ParquetRegistryError local base is removed (B-228)
    assert not hasattr(mod, "ParquetRegistryError"), (
        "local ParquetRegistryError base class should be removed per B-228"
    )


def test_registry_status_invalid_carries_context(mod):
    """RegistryStatusInvalid carries registry_id + current_status + attempted_status."""
    row = _canonical_row(Status="created")
    cursor_factory, _ = _make_cursor_for(row)
    p1, p2 = _patches(mod, cursor_factory, lambda **_kw: None)
    with p1, p2:
        with pytest.raises(mod.RegistryStatusInvalid) as exc_info:
            mod.mark_replicated(registry_id=42, replica_target="X")
    assert exc_info.value.metadata["registry_id"] == 42
    assert exc_info.value.metadata["current_status"] == "created"
    assert exc_info.value.metadata["attempted_status"] == "replicated"


def test_registry_hash_mismatch_carries_both_hashes(mod, tmp_path):
    """RegistryHashMismatch exposes both expected + computed hashes for forensics."""
    file_path = tmp_path / "test.parquet"
    file_path.write_bytes(b"hello")

    row = _canonical_row(
        Status="created",
        NetworkDrivePath=str(file_path),
        ContentChecksum="0" * 64,
    )
    cursor_factory, _ = _make_cursor_for(row)
    p1, p2 = _patches(mod, cursor_factory, lambda **_kw: None)
    with p1, p2:
        with pytest.raises(mod.RegistryHashMismatch) as exc_info:
            mod.verify_parquet_snapshot(registry_id=42)
    assert exc_info.value.metadata["expected_sha256"] == "0" * 64
    # Computed hash is the sha256 of "hello"
    import hashlib
    assert exc_info.value.metadata["computed_sha256"] == hashlib.sha256(b"hello").hexdigest()


# ---------------------------------------------------------------------------
# Sanity: state-machine constants match canonical CK constraint
# ---------------------------------------------------------------------------


def test_canonical_status_set_matches_check_constraint_values(mod):
    """ALL_STATUSES must exactly match the CK_ParquetSnapshotRegistry_Status enum."""
    # Derived from phase1/01_database_schema.md § 8 CK constraint
    canonical = frozenset({
        "created", "verified", "replicated",
        "archived", "missing", "purged", "replication_failed",
    })
    assert mod.ALL_STATUSES == canonical


def test_tier_constants_match_check_constraint_values(mod):
    """Tier constants must match CK_ParquetSnapshotRegistry_Tier enum."""
    assert mod.TIER_HOT == "hot"
    assert mod.TIER_WARM == "warm"
    assert mod.TIER_COLD == "cold"
    assert mod.TIER_FROZEN == "frozen"
