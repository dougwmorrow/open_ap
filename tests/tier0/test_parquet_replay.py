"""Tier 0 build-time smoke test for data_load/parquet_replay.py.

Per **D67** — runs at build time + every commit. Runtime ceiling < 5 s.
All external dependencies (M3's ``query_snapshot``, M9's ``ledger_step``)
are mocked.

Asserts (per § 1.2 Tier 0 contract):
  (a) module imports without error;
  (b) ``replay_parquet_snapshot(...)`` invokable with mocked registry +
      fixture Parquet file;
  (c) returns ``ReplayResult`` shape with ``df`` + ``sha256_verified`` +
      ``extracted_at`` + ``batch_id``;
  (d) raises ``ParquetReplayError`` on simulated SHA-256 mismatch;
  (e) raises ``RegistryStatusInvalid`` on ``Status='created'`` fixture;
  (f) < 5 s, no real network drive / no real DB.

North Star pillars:
  - Idempotent (D15): replay composes ledger_step keyed by
    ``replay_batch_id``; re-call is short-circuit-safe.
  - Audit-grade (D26 + D76): per-replay metadata (registry_id,
    file_path, sha256, row_count) travels in exception metadata + ledger.
  - Operationally stable (D69): sibling modules are imported through
    lazy getters, so the harness can swap them via ``patch.object``.

D-numbers: D67 (Tier 0 discipline), D15 (idempotency), D17 (ledger),
D25 (canonical Parquet index), D26 (append-only audit), D68 (error
class hierarchy), D69 (cursor ownership).

Spec: ``docs/migration/phase1/03_core_modules.md`` § 1.2.
"""
from __future__ import annotations

import hashlib
import importlib
import sys
import time
from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import polars as pl
import pytest

# ---------------------------------------------------------------------------
# Project root on sys.path (matches tests/ convention)
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


_MODULE_KEY = "data_load.parquet_replay"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _canonical_row(**overrides) -> dict:
    """Return a canonical ParquetSnapshotRegistry row dict for tests."""
    base = {
        "RegistryId": 42,
        "SourceName": "DNA",
        "TableName": "ACCT",
        "BatchId": 12345,
        "BusinessDate": date(2026, 1, 1),
        "NetworkDrivePath": "/mnt/parquet/DNA/ACCT/2026/01/01/12345.parquet",
        "SnowflakeStagePath": None,
        "SnowflakeUploadedAt": None,
        "RowCount": 3,
        "UncompressedBytes": 4_000_000,
        "CompressedBytes": 800_000,
        "SchemaHash": "a" * 64,
        "ContentChecksum": "b" * 64,
        "StorageTier": "hot",
        "Status": "verified",
        "CreatedAt": datetime(2026, 1, 1, 12, 0, 0),
        "LastVerifiedAt": datetime(2026, 1, 1, 12, 5, 0),
        "LastAccessedAt": None,
        "PurgedAt": None,
        "PurgedReason": None,
    }
    base.update(overrides)
    return base


def _make_query_snapshot(row: dict | None):
    """Build a mock query_snapshot callable that returns ``row``."""
    def _query(**_kwargs):
        return row
    return _query


def _make_ledger_step(was_short_circuited: bool = False):
    """Build a mock ledger_step context-manager factory."""
    step = MagicMock()
    step.was_short_circuited = was_short_circuited
    step.step_id = 1
    step.prior_result = None

    def _factory(**_kwargs):
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=step)
        cm.__exit__ = MagicMock(return_value=False)
        return cm

    return _factory


def _write_parquet_fixture(tmp_path: Path, df: pl.DataFrame) -> tuple[Path, str]:
    """Write df to tmp_path/test.parquet; return (path, sha256_hex)."""
    file_path = tmp_path / "test.parquet"
    df.write_parquet(file_path)
    sha = hashlib.sha256(file_path.read_bytes()).hexdigest()
    return file_path, sha


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fresh_module():
    """Load data_load.parquet_replay fresh for each test."""
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
        "EVENT_TYPE_REPLAY",
        "REPLAY_ELIGIBLE_STATUSES",
        "ReplayResult",
        "replay_parquet_snapshot",
    }
    for name in expected_public:
        assert hasattr(fresh_module, name), (
            f"public symbol {name!r} missing from module"
        )

    assert hasattr(fresh_module, "__all__"), "module has no __all__"
    for name in expected_public:
        assert name in fresh_module.__all__, (
            f"{name!r} missing from __all__"
        )


def test_event_type_replay_constant(fresh_module):
    """EVENT_TYPE_REPLAY is the canonical 'REPLAY' string."""
    assert fresh_module.EVENT_TYPE_REPLAY == "REPLAY"


def test_replay_eligible_statuses(fresh_module):
    """REPLAY_ELIGIBLE_STATUSES matches the § 1.2 spec ('verified', 'replicated', 'archived')."""
    assert fresh_module.REPLAY_ELIGIBLE_STATUSES == frozenset(
        {"verified", "replicated", "archived"}
    )


def test_runtime_ceiling_under_5s():
    """Tier 0 contract: < 5 s total. Re-import the module + read public surface."""
    start = time.time()
    if _MODULE_KEY in sys.modules:
        del sys.modules[_MODULE_KEY]
    mod = importlib.import_module(_MODULE_KEY)
    _ = mod.REPLAY_ELIGIBLE_STATUSES
    elapsed = time.time() - start
    assert elapsed < 5.0, f"Tier 0 import took {elapsed:.2f}s (>5s ceiling)"


# ---------------------------------------------------------------------------
# (b) replay_parquet_snapshot invokable with mocked registry + fixture file
# ---------------------------------------------------------------------------


def test_replay_invokable_happy_path(fresh_module, tmp_path):
    """replay_parquet_snapshot(...) invokable with mocked registry + fixture file."""
    df = pl.DataFrame({"id": [1, 2, 3], "value": ["a", "b", "c"]})
    file_path, sha = _write_parquet_fixture(tmp_path, df)

    row = _canonical_row(
        Status="verified",
        NetworkDrivePath=str(file_path),
        ContentChecksum=sha,
        RowCount=3,
    )

    with patch.object(
        fresh_module, "_get_query_snapshot",
        return_value=_make_query_snapshot(row),
    ), patch.object(
        fresh_module, "_get_ledger_step",
        return_value=_make_ledger_step(),
    ):
        result = fresh_module.replay_parquet_snapshot(
            source_name="DNA",
            table_name="ACCT",
            business_date=date(2026, 1, 1),
            original_batch_id=12345,
            replay_batch_id=99999,
        )

    assert result is not None


# ---------------------------------------------------------------------------
# (c) Returns ReplayResult shape with required fields
# ---------------------------------------------------------------------------


def test_replay_result_shape(fresh_module, tmp_path):
    """ReplayResult has df, registry_id, source_file, row_count, sha256_verified,
    extracted_at, batch_id."""
    df = pl.DataFrame({"id": [1, 2, 3]})
    file_path, sha = _write_parquet_fixture(tmp_path, df)
    row = _canonical_row(
        NetworkDrivePath=str(file_path), ContentChecksum=sha, RowCount=3,
    )

    with patch.object(
        fresh_module, "_get_query_snapshot",
        return_value=_make_query_snapshot(row),
    ), patch.object(
        fresh_module, "_get_ledger_step",
        return_value=_make_ledger_step(),
    ):
        result = fresh_module.replay_parquet_snapshot(
            source_name="DNA",
            table_name="ACCT",
            business_date=date(2026, 1, 1),
            original_batch_id=12345,
            replay_batch_id=99999,
        )

    assert isinstance(result.df, pl.DataFrame)
    assert result.df.height == 3
    assert result.registry_id == 42
    assert result.source_file == file_path
    assert result.row_count == 3
    assert result.sha256_verified.lower() == sha.lower()
    assert isinstance(result.extracted_at, datetime)
    assert result.batch_id == 12345


# ---------------------------------------------------------------------------
# (d) Raises ParquetReplayError on simulated SHA-256 mismatch
# ---------------------------------------------------------------------------


def test_replay_raises_on_sha_mismatch(fresh_module, tmp_path):
    """SHA-256 mismatch raises ParquetReplayError."""
    df = pl.DataFrame({"id": [1, 2, 3]})
    file_path, _real_sha = _write_parquet_fixture(tmp_path, df)
    row = _canonical_row(
        NetworkDrivePath=str(file_path),
        ContentChecksum="0" * 64,  # deliberately wrong
        RowCount=3,
    )

    from utils.errors import ParquetReplayError

    with patch.object(
        fresh_module, "_get_query_snapshot",
        return_value=_make_query_snapshot(row),
    ), patch.object(
        fresh_module, "_get_ledger_step",
        return_value=_make_ledger_step(),
    ):
        with pytest.raises(ParquetReplayError):
            fresh_module.replay_parquet_snapshot(
                source_name="DNA",
                table_name="ACCT",
                business_date=date(2026, 1, 1),
                original_batch_id=12345,
                replay_batch_id=99999,
            )


# ---------------------------------------------------------------------------
# (e) Raises RegistryStatusInvalid on Status='created' fixture
# ---------------------------------------------------------------------------


def test_replay_raises_on_status_created(fresh_module):
    """Status='created' (verifier not yet run) raises RegistryStatusInvalid."""
    row = _canonical_row(Status="created")

    from utils.errors import RegistryStatusInvalid

    with patch.object(
        fresh_module, "_get_query_snapshot",
        return_value=_make_query_snapshot(row),
    ), patch.object(
        fresh_module, "_get_ledger_step",
        return_value=_make_ledger_step(),
    ):
        with pytest.raises(RegistryStatusInvalid):
            fresh_module.replay_parquet_snapshot(
                source_name="DNA",
                table_name="ACCT",
                business_date=date(2026, 1, 1),
                original_batch_id=12345,
                replay_batch_id=99999,
            )


# ---------------------------------------------------------------------------
# Extra: RegistryNotFound when query_snapshot returns None
# ---------------------------------------------------------------------------


def test_replay_raises_when_registry_row_absent(fresh_module):
    """When query_snapshot returns None, RegistryNotFound is raised."""
    from utils.errors import RegistryNotFound

    with patch.object(
        fresh_module, "_get_query_snapshot",
        return_value=_make_query_snapshot(None),
    ), patch.object(
        fresh_module, "_get_ledger_step",
        return_value=_make_ledger_step(),
    ):
        with pytest.raises(RegistryNotFound):
            fresh_module.replay_parquet_snapshot(
                source_name="DNA",
                table_name="ACCT",
                business_date=date(2026, 1, 1),
                original_batch_id=999_999,
                replay_batch_id=99999,
            )
