"""Tier 0 build-time smoke test for data_load/parquet_writer.py.

Per **D67** — runs at build time + every commit. Runtime ceiling < 5 s.
All external dependencies (``utils.connections.cursor_for``, pyodbc cursor)
are mocked. polars + filesystem are real (writing tiny in-memory frames
to ``tmp_path``).

Asserts (per § 1.1 Tier 0 contract):
  (a) module imports without error;
  (b) ``write_parquet_snapshot`` invokable with a synthetic DataFrame +
      mocked pyodbc cursor + tmp_path output_dir;
  (c) returns :class:`ParquetWriteResult` with all 6 fields populated
      and correct types (Path / int / int / str / int / str);
  (d) raises :class:`RegistryInsertConflict` on mocked UNIQUE violation;
  (e) <5 s, no real network drive / no real DB.

North Star pillars:
  - Idempotent (D15): UNIQUE constraint serializes write-side correctness;
    re-call same key -> RegistryInsertConflict (retryable).
  - Audit-grade (D26 + D76): registry row is written with
    Status='created'; M3 verification flips to 'verified'.
  - Operationally stable (D69): cursor_for('General') per call.

D-numbers: D67 (Tier 0 discipline), D15 (idempotency), D16 (inflight-rename),
D26 (append-only audit), D45.2 (Parquet config), D45.3 (BatchId source),
D68 (error class hierarchy), D69 (cursor ownership).

B-1: SHA-256 stored as full 64-char hex (VARCHAR(64)).
W-12: shrink_to_fit on large DataFrames (not exercised at Tier 0 — synthetic
  frames are tiny).

Spec: ``docs/migration/phase1/03_core_modules.md`` § 1.1.
"""
from __future__ import annotations

import importlib
import sys
import time
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock, patch

import polars as pl
import pyodbc
import pytest

# ---------------------------------------------------------------------------
# Project root on sys.path
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


_MODULE_KEY = "data_load.parquet_writer"
_MODULE_PATH = _PROJECT_ROOT / "data_load" / "parquet_writer.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cursor_for_with_output(registry_id: int):
    """Return a cursor_for factory whose execute() yields ``registry_id``.

    Mimics the ``INSERT ... OUTPUT INSERTED.RegistryId`` round-trip.
    """
    cursor = MagicMock()
    cursor.fetchone.return_value = (registry_id,)
    cursor.rowcount = 1

    def _factory(_db: str):
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=cursor)
        cm.__exit__ = MagicMock(return_value=False)
        return cm

    return _factory, cursor


def _make_cursor_for_unique_violation():
    """Return a cursor_for factory whose execute() raises a UNIQUE violation."""
    cursor = MagicMock()
    # Construct a pyodbc.IntegrityError with the canonical message phrasing
    # that the _is_unique_violation discriminator recognizes.
    exc = pyodbc.IntegrityError(
        "23000",
        "[23000] [Microsoft][ODBC Driver 18 for SQL Server]"
        "[SQL Server]Violation of UNIQUE KEY constraint "
        "'UX_ParquetSnapshotRegistry_Identity'. Cannot insert duplicate key "
        "in object 'General.ops.ParquetSnapshotRegistry'. (2601)",
    )
    cursor.execute.side_effect = exc

    def _factory(_db: str):
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=cursor)
        cm.__exit__ = MagicMock(return_value=False)
        return cm

    return _factory, cursor


def _synthetic_df() -> pl.DataFrame:
    """Tiny in-memory DataFrame for smoke tests."""
    return pl.DataFrame(
        {
            "pk_id": [1, 2, 3],
            "value": ["a", "b", "c"],
        }
    )


# ---------------------------------------------------------------------------
# Fixture: fresh module load
# ---------------------------------------------------------------------------


@pytest.fixture
def mod():
    """Load data_load.parquet_writer fresh for each test."""
    if _MODULE_KEY in sys.modules:
        del sys.modules[_MODULE_KEY]
    m = importlib.import_module(_MODULE_KEY)
    yield m
    if _MODULE_KEY in sys.modules:
        del sys.modules[_MODULE_KEY]


# ---------------------------------------------------------------------------
# (a) Module imports
# ---------------------------------------------------------------------------


def test_module_imports(mod):
    """Module imports without error and exposes the documented public surface."""
    expected_public = {"write_parquet_snapshot", "ParquetWriteResult"}
    for name in expected_public:
        assert hasattr(mod, name), f"public symbol {name!r} missing"

    assert hasattr(mod, "__all__")
    for name in expected_public:
        assert name in mod.__all__, f"{name!r} missing from __all__"


def test_canonical_errors_resolve_via_utils_errors(mod):
    """Per B-228 single-source-of-truth — error classes live in utils.errors."""
    from utils.errors import ParquetWriteCrash, RegistryInsertConflict
    # The module's raise sites import from utils.errors directly; no local
    # re-export expected. This test pins the import-source contract.
    assert ParquetWriteCrash is not None
    assert RegistryInsertConflict is not None


# ---------------------------------------------------------------------------
# (b) Invokable end-to-end with mocked cursor
# ---------------------------------------------------------------------------


def test_write_parquet_snapshot_invokable(mod, tmp_path):
    """write_parquet_snapshot completes without error; returns ParquetWriteResult."""
    cursor_factory, cursor = _make_cursor_for_with_output(registry_id=999)
    with patch.object(mod, "_get_cursor_for", return_value=cursor_factory):
        result = mod.write_parquet_snapshot(
            _synthetic_df(),
            source_name="TEST",
            table_name="T",
            business_date=date(2026, 1, 1),
            batch_id=999,
            output_dir=tmp_path,
        )
    # File materialized at the Hive-partitioned path.
    expected_path = (
        tmp_path / "TEST" / "T" / "year=2026" / "month=01" / "day=01"
        / "999.parquet"
    )
    assert result.file_path == expected_path
    assert expected_path.exists()
    # Cursor was used to INSERT the registry row.
    assert cursor.execute.call_count == 1


# ---------------------------------------------------------------------------
# (c) ParquetWriteResult shape — all 6 fields with correct types
# ---------------------------------------------------------------------------


def test_parquet_write_result_shape(mod, tmp_path):
    """All 6 fields populated with correct types per § 1.1 dataclass."""
    cursor_factory, _ = _make_cursor_for_with_output(registry_id=42)
    with patch.object(mod, "_get_cursor_for", return_value=cursor_factory):
        result = mod.write_parquet_snapshot(
            _synthetic_df(),
            source_name="DNA",
            table_name="ACCT",
            business_date=date(2026, 5, 13),
            batch_id=12345,
            output_dir=tmp_path,
        )
    assert isinstance(result.file_path, Path)
    assert isinstance(result.file_size_bytes, int) and result.file_size_bytes > 0
    assert isinstance(result.row_count, int) and result.row_count == 3
    assert isinstance(result.sha256, str) and len(result.sha256) == 64
    assert isinstance(result.registry_id, int) and result.registry_id == 42
    assert result.status == "created"


# ---------------------------------------------------------------------------
# (d) UNIQUE violation -> RegistryInsertConflict
# ---------------------------------------------------------------------------


def test_unique_violation_raises_registry_insert_conflict(mod, tmp_path):
    """Mocked UNIQUE violation on INSERT raises RegistryInsertConflict."""
    from utils.errors import RegistryInsertConflict
    cursor_factory, _ = _make_cursor_for_unique_violation()
    with patch.object(mod, "_get_cursor_for", return_value=cursor_factory):
        with pytest.raises(RegistryInsertConflict) as exc_info:
            mod.write_parquet_snapshot(
                _synthetic_df(),
                source_name="DNA",
                table_name="ACCT",
                business_date=date(2026, 5, 13),
                batch_id=12345,
                output_dir=tmp_path,
            )
    # Metadata carries the identity tuple for retry-side query.
    assert exc_info.value.metadata["source_name"] == "DNA"
    assert exc_info.value.metadata["table_name"] == "ACCT"
    assert exc_info.value.metadata["batch_id"] == 12345


# ---------------------------------------------------------------------------
# (e) Tier 0 runtime ceiling — <5 s for the full module import + invoke
# ---------------------------------------------------------------------------


def test_runtime_ceiling_under_5s(tmp_path):
    """Tier 0 contract: <5 s total. Import + invoke."""
    start = time.time()
    if _MODULE_KEY in sys.modules:
        del sys.modules[_MODULE_KEY]
    m = importlib.import_module(_MODULE_KEY)
    cursor_factory, _ = _make_cursor_for_with_output(registry_id=1)
    with patch.object(m, "_get_cursor_for", return_value=cursor_factory):
        m.write_parquet_snapshot(
            _synthetic_df(),
            source_name="X",
            table_name="Y",
            business_date=date(2026, 1, 1),
            batch_id=1,
            output_dir=tmp_path,
        )
    elapsed = time.time() - start
    assert elapsed < 5.0, f"Tier 0 import+invoke took {elapsed:.2f}s (>5s ceiling)"
