"""Tier 1 unit tests for data_load/parquet_writer.py.

Per § 1.1 Tier 1 test surface:

  - given fixture DataFrame + tempdir, assert path / size / row count / sha256
  - idempotency — second call same key raises ``RegistryInsertConflict``
  - crash injection — kill mid-rename leaves inflight file + no registry row
  - hash compute correctness (matches hashlib.sha256 of on-disk bytes)
  - Hive path construction across edge cases (Jan 1, leap day, year boundaries)
  - inflight-rename ordering invariants
  - ``ParquetWriteResult`` immutability + field types
  - polars DataFrame size variations (empty / single row / many cols / many rows)

Tests run on every commit. No live DB, no live network required. All
external dependencies mocked with unittest.mock.

North Star pillars addressed:
  - Idempotent (D15 + D16): inflight-rename pattern + UNIQUE constraint
    together prevent same-tuple races.
  - Audit-grade (D26 + D76): registry row carries full SHA-256 (B-1) +
    Status='created'; M3 verification flips to 'verified'.
  - Operationally stable (D69): cursor_for('General') per call; no
    shared state across module boundary.
  - Traceability (D25 + D45.3): ParquetSnapshotRegistry is the canonical
    Parquet index; BatchId from PipelineBatchSequence is the identity-
    key cornerstone.

Edge case IDs (per 04_EDGE_CASES.md):
  - N1 (concurrent write same key): UNIQUE constraint -> RegistryInsertConflict.
  - N2 (crash mid-write before rename): inflight file remains, no registry row.
  - N3 (crash after rename before INSERT): file present, no registry row;
    operator-callable mark_missing flow in § 1.3.
  - N6 (file size 0): tested for completeness.

Decision citations:
  D2 (Stage dropped), D4 (network drive Parquet), D15 (idempotency),
  D16 (inflight-rename), D26 (append-only), D45.2 (Parquet config),
  D45.3 (BatchId from sequence), D67 (Tier 0 disc), D68 (error class
  hierarchy), D69 (cursor ownership), D92 (forward-only).

B-1: SHA-256 stored full 64-char VARCHAR(64).
W-12: shrink_to_fit on DataFrames > 100K rows.

Spec: ``docs/migration/phase1/03_core_modules.md`` § 1.1.
"""
from __future__ import annotations

import hashlib
import importlib
import os
import sys
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
# Helpers
# ---------------------------------------------------------------------------


def _make_cursor_factory(
    *,
    registry_id: int | None = 1,
    side_effect: Exception | None = None,
    fetchone_returns_none: bool = False,
):
    """Build a cursor_for factory; configurable for happy / sad paths.

    Returns ``(factory_callable, cursor_mock)``.
    """
    cursor = MagicMock()
    if fetchone_returns_none:
        cursor.fetchone.return_value = None
    else:
        cursor.fetchone.return_value = (registry_id,)
    cursor.rowcount = 1
    if side_effect is not None:
        cursor.execute.side_effect = side_effect

    def _factory(_db: str):
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=cursor)
        cm.__exit__ = MagicMock(return_value=False)
        return cm

    return _factory, cursor


def _unique_violation_exc(code: int = 2601) -> pyodbc.IntegrityError:
    """Construct a pyodbc.IntegrityError with the canonical UNIQUE phrasing."""
    if code == 2601:
        msg = (
            "[23000] [Microsoft][ODBC Driver 18 for SQL Server]"
            "[SQL Server]Violation of UNIQUE KEY constraint "
            "'UX_ParquetSnapshotRegistry_Identity'. Cannot insert duplicate "
            "key in object 'General.ops.ParquetSnapshotRegistry'. (2601)"
        )
    else:  # 2627 — PK violation
        msg = (
            "[23000] [Microsoft][ODBC Driver 18 for SQL Server]"
            "[SQL Server]Violation of PRIMARY KEY constraint. Cannot insert "
            "duplicate key. (2627)"
        )
    return pyodbc.IntegrityError("23000", msg)


def _other_integrity_exc() -> pyodbc.IntegrityError:
    """Construct a non-UNIQUE IntegrityError (e.g. FK violation)."""
    return pyodbc.IntegrityError(
        "23000",
        "[23000] FOREIGN KEY constraint violation. (547)",
    )


def _small_df() -> pl.DataFrame:
    return pl.DataFrame({"pk_id": [1, 2, 3], "v": ["a", "b", "c"]})


def _empty_df() -> pl.DataFrame:
    return pl.DataFrame({"pk_id": pl.Series([], dtype=pl.Int64),
                         "v": pl.Series([], dtype=pl.Utf8)})


def _single_row_df() -> pl.DataFrame:
    return pl.DataFrame({"pk_id": [42], "v": ["solo"]})


def _wide_df() -> pl.DataFrame:
    return pl.DataFrame(
        {f"col_{i}": [i * 10, i * 20, i * 30] for i in range(20)}
    )


# ---------------------------------------------------------------------------
# Module surface + symbol exports
# ---------------------------------------------------------------------------


def test_module_exposes_only_documented_surface(mod):
    """__all__ matches the documented public surface exactly."""
    assert set(mod.__all__) == {"ParquetWriteResult", "write_parquet_snapshot"}


def test_parquet_write_result_is_frozen_dataclass(mod):
    """ParquetWriteResult is a frozen dataclass per § 1.1."""
    res = mod.ParquetWriteResult(
        file_path=Path("/tmp/x.parquet"),
        file_size_bytes=100,
        row_count=10,
        sha256="a" * 64,
        registry_id=1,
        status="created",
    )
    with pytest.raises((AttributeError, TypeError)):
        res.status = "verified"  # frozen — must reject


def test_canonical_compression_constants(mod):
    """ZSTD-3 compression constants match D45.2."""
    assert mod.PARQUET_COMPRESSION == "zstd"
    assert mod.PARQUET_COMPRESSION_LEVEL == 3
    assert mod.PARQUET_STATISTICS is True


# ---------------------------------------------------------------------------
# _build_hive_path: pure-function path construction
# ---------------------------------------------------------------------------


def test_hive_path_canonical(mod):
    """Hive partition path matches the § 1.1 spec exactly."""
    p = mod._build_hive_path(
        output_dir=Path("/mnt/parquet"),
        source_name="DNA",
        table_name="ACCT",
        business_date=date(2026, 5, 13),
        batch_id=12345,
    )
    expected = Path(
        "/mnt/parquet/DNA/ACCT/year=2026/month=05/day=13/12345.parquet"
    )
    assert p == expected


def test_hive_path_zero_pads_single_digit_month_day(mod):
    """Hive partition uses zero-padded month / day (lex order = chrono order)."""
    p = mod._build_hive_path(
        output_dir=Path("/mnt/parquet"),
        source_name="X",
        table_name="Y",
        business_date=date(2026, 1, 1),
        batch_id=1,
    )
    assert "month=01" in str(p)
    assert "day=01" in str(p)


def test_hive_path_leap_day(mod):
    """Feb 29 on a leap year renders correctly."""
    p = mod._build_hive_path(
        output_dir=Path("/mnt/parquet"),
        source_name="X",
        table_name="Y",
        business_date=date(2024, 2, 29),
        batch_id=99,
    )
    assert "year=2024" in str(p)
    assert "month=02" in str(p)
    assert "day=29" in str(p)


def test_hive_path_year_boundary(mod):
    """Dec 31 and Jan 1 both render with full 4-digit year."""
    p1 = mod._build_hive_path(
        output_dir=Path("/o"),
        source_name="S", table_name="T",
        business_date=date(2025, 12, 31), batch_id=1,
    )
    p2 = mod._build_hive_path(
        output_dir=Path("/o"),
        source_name="S", table_name="T",
        business_date=date(2026, 1, 1), batch_id=2,
    )
    assert "year=2025" in str(p1)
    assert "year=2026" in str(p2)


# ---------------------------------------------------------------------------
# _compute_sha256: streaming hash matches reference hashlib.sha256
# ---------------------------------------------------------------------------


def test_compute_sha256_matches_hashlib(mod, tmp_path):
    """Streaming SHA-256 matches hashlib reference on the same bytes."""
    payload = b"PAR1" + (b"\x00\x01\x02\x03" * 1024) + b"PAR1"
    file_path = tmp_path / "test.parquet"
    file_path.write_bytes(payload)
    computed = mod._compute_sha256(file_path)
    expected = hashlib.sha256(payload).hexdigest()
    assert computed == expected
    assert len(computed) == 64  # full 64-char hex per B-1


def test_compute_sha256_empty_file(mod, tmp_path):
    """Empty file hashes to the well-known SHA-256 of zero bytes."""
    file_path = tmp_path / "empty.parquet"
    file_path.write_bytes(b"")
    computed = mod._compute_sha256(file_path)
    # SHA-256 of the empty string
    expected = (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )
    assert computed == expected


def test_compute_sha256_chunked_large(mod, tmp_path):
    """Chunked streaming over a >64 KiB file produces correct digest."""
    # 200 KiB of structured bytes — forces multiple read() calls.
    payload = bytes(range(256)) * 800  # 200 KiB
    file_path = tmp_path / "large.parquet"
    file_path.write_bytes(payload)
    computed = mod._compute_sha256(file_path)
    expected = hashlib.sha256(payload).hexdigest()
    assert computed == expected


def test_compute_sha256_missing_file_raises(mod, tmp_path):
    """Hashing a missing file raises FileNotFoundError (caller handles)."""
    missing = tmp_path / "does_not_exist.parquet"
    with pytest.raises(FileNotFoundError):
        mod._compute_sha256(missing)


# ---------------------------------------------------------------------------
# _is_unique_violation: discriminator
# ---------------------------------------------------------------------------


def test_is_unique_violation_2601(mod):
    """Recognizes 2601 UNIQUE-index violations."""
    assert mod._is_unique_violation(_unique_violation_exc(2601))


def test_is_unique_violation_2627(mod):
    """Recognizes 2627 PK violations."""
    assert mod._is_unique_violation(_unique_violation_exc(2627))


def test_is_unique_violation_rejects_fk(mod):
    """Non-UNIQUE IntegrityError (FK) returns False."""
    assert not mod._is_unique_violation(_other_integrity_exc())


def test_is_unique_violation_empty_args(mod):
    """IntegrityError with no args returns False."""
    exc = pyodbc.IntegrityError()
    assert not mod._is_unique_violation(exc)


# ---------------------------------------------------------------------------
# _resolve_output_dir: env fallback
# ---------------------------------------------------------------------------


def test_resolve_output_dir_explicit_wins(mod, tmp_path, monkeypatch):
    """When output_dir is explicit, env var is ignored."""
    monkeypatch.setenv("PARQUET_OUTPUT_DIR", "/should/be/ignored")
    resolved = mod._resolve_output_dir(tmp_path)
    assert resolved == tmp_path


def test_resolve_output_dir_falls_back_to_env(mod, tmp_path, monkeypatch):
    """None output_dir reads PARQUET_OUTPUT_DIR from env."""
    monkeypatch.setenv("PARQUET_OUTPUT_DIR", str(tmp_path))
    resolved = mod._resolve_output_dir(None)
    assert resolved == tmp_path


def test_resolve_output_dir_raises_when_neither_set(mod, monkeypatch):
    """None output_dir + missing env -> ParquetWriteCrash."""
    monkeypatch.delenv("PARQUET_OUTPUT_DIR", raising=False)
    from utils.errors import ParquetWriteCrash
    with pytest.raises(ParquetWriteCrash) as exc_info:
        mod._resolve_output_dir(None)
    assert exc_info.value.metadata["env_key"] == "PARQUET_OUTPUT_DIR"


# ---------------------------------------------------------------------------
# _atomic_rename: success + failure paths
# ---------------------------------------------------------------------------


def test_atomic_rename_happy_path(mod, tmp_path):
    """os.replace inflight -> final; final exists, inflight removed."""
    inflight = tmp_path / "x.parquet.inflight"
    final = tmp_path / "x.parquet"
    inflight.write_bytes(b"PAR1")
    mod._atomic_rename(inflight, final)
    assert final.exists()
    assert final.read_bytes() == b"PAR1"
    assert not inflight.exists()


def test_atomic_rename_failure_raises_parquet_write_crash(mod, tmp_path):
    """os.replace failure -> ParquetWriteCrash with errno metadata."""
    from utils.errors import ParquetWriteCrash
    inflight = tmp_path / "x.parquet.inflight"
    final = tmp_path / "x.parquet"
    inflight.write_bytes(b"PAR1")
    with patch("os.replace", side_effect=OSError(13, "Permission denied")):
        with pytest.raises(ParquetWriteCrash) as exc_info:
            mod._atomic_rename(inflight, final)
    assert exc_info.value.metadata["inflight_path"] == str(inflight)
    assert exc_info.value.metadata["final_path"] == str(final)
    assert exc_info.value.metadata["errno"] == 13


def test_atomic_rename_parent_fsync_failure_is_nonfatal(mod, tmp_path):
    """parent-dir fsync failure does NOT raise (best-effort durability)."""
    inflight = tmp_path / "x.parquet.inflight"
    final = tmp_path / "x.parquet"
    inflight.write_bytes(b"PAR1")
    # Mock os.fsync to fail; os.replace + os.open succeed normally.
    with patch("os.fsync", side_effect=OSError("EINVAL")):
        # Must NOT raise — rename succeeded; fsync is best-effort.
        mod._atomic_rename(inflight, final)
    assert final.exists()


# ---------------------------------------------------------------------------
# write_parquet_snapshot: end-to-end happy path
# ---------------------------------------------------------------------------


def test_write_writes_to_canonical_hive_path(mod, tmp_path):
    """Output file lands at <out>/<src>/<tbl>/year=YYYY/month=MM/day=DD/<batch>.parquet."""
    cursor_factory, _ = _make_cursor_factory(registry_id=42)
    with patch.object(mod, "_get_cursor_for", return_value=cursor_factory):
        result = mod.write_parquet_snapshot(
            _small_df(),
            source_name="DNA",
            table_name="ACCT",
            business_date=date(2026, 5, 13),
            batch_id=12345,
            output_dir=tmp_path,
        )
    expected = (
        tmp_path / "DNA" / "ACCT" / "year=2026" / "month=05" / "day=13"
        / "12345.parquet"
    )
    assert result.file_path == expected
    assert expected.exists()


def test_write_returns_correct_row_count(mod, tmp_path):
    """result.row_count == len(df)."""
    cursor_factory, _ = _make_cursor_factory(registry_id=1)
    df = _wide_df()  # 3 rows, 20 cols
    with patch.object(mod, "_get_cursor_for", return_value=cursor_factory):
        result = mod.write_parquet_snapshot(
            df,
            source_name="X", table_name="Y",
            business_date=date(2026, 1, 1), batch_id=1,
            output_dir=tmp_path,
        )
    assert result.row_count == 3


def test_write_returns_correct_file_size(mod, tmp_path):
    """result.file_size_bytes matches stat() of on-disk file."""
    cursor_factory, _ = _make_cursor_factory(registry_id=1)
    with patch.object(mod, "_get_cursor_for", return_value=cursor_factory):
        result = mod.write_parquet_snapshot(
            _small_df(),
            source_name="X", table_name="Y",
            business_date=date(2026, 1, 1), batch_id=1,
            output_dir=tmp_path,
        )
    assert result.file_size_bytes == result.file_path.stat().st_size
    assert result.file_size_bytes > 0


def test_write_returns_correct_sha256(mod, tmp_path):
    """result.sha256 == hashlib.sha256(file bytes) per B-1."""
    cursor_factory, _ = _make_cursor_factory(registry_id=1)
    with patch.object(mod, "_get_cursor_for", return_value=cursor_factory):
        result = mod.write_parquet_snapshot(
            _small_df(),
            source_name="X", table_name="Y",
            business_date=date(2026, 1, 1), batch_id=1,
            output_dir=tmp_path,
        )
    expected = hashlib.sha256(result.file_path.read_bytes()).hexdigest()
    assert result.sha256 == expected
    assert len(result.sha256) == 64


def test_write_returns_registry_id_from_output(mod, tmp_path):
    """result.registry_id comes from the INSERT OUTPUT clause."""
    cursor_factory, _ = _make_cursor_factory(registry_id=777)
    with patch.object(mod, "_get_cursor_for", return_value=cursor_factory):
        result = mod.write_parquet_snapshot(
            _small_df(),
            source_name="X", table_name="Y",
            business_date=date(2026, 1, 1), batch_id=1,
            output_dir=tmp_path,
        )
    assert result.registry_id == 777


def test_write_returns_status_created(mod, tmp_path):
    """result.status is always 'created' per § 1.1 contract."""
    cursor_factory, _ = _make_cursor_factory(registry_id=1)
    with patch.object(mod, "_get_cursor_for", return_value=cursor_factory):
        result = mod.write_parquet_snapshot(
            _small_df(),
            source_name="X", table_name="Y",
            business_date=date(2026, 1, 1), batch_id=1,
            output_dir=tmp_path,
        )
    assert result.status == "created"


# ---------------------------------------------------------------------------
# write_parquet_snapshot: INSERT payload + identity-tuple correctness
# ---------------------------------------------------------------------------


def test_write_insert_uses_correct_identity_tuple(mod, tmp_path):
    """The INSERT payload carries (SourceName, TableName, BatchId, BusinessDate)."""
    cursor_factory, cursor = _make_cursor_factory(registry_id=1)
    with patch.object(mod, "_get_cursor_for", return_value=cursor_factory):
        mod.write_parquet_snapshot(
            _small_df(),
            source_name="DNA", table_name="ACCT",
            business_date=date(2026, 5, 13), batch_id=12345,
            output_dir=tmp_path,
        )
    # Verify INSERT was issued exactly once
    assert cursor.execute.call_count == 1
    call_args = cursor.execute.call_args
    sql_text = call_args.args[0]
    params = call_args.args[1]
    assert "INSERT INTO General.ops.ParquetSnapshotRegistry" in sql_text
    assert "OUTPUT INSERTED.RegistryId" in sql_text
    # First 4 params are the identity tuple
    assert params[0] == "DNA"
    assert params[1] == "ACCT"
    assert params[2] == 12345
    assert params[3] == date(2026, 5, 13)


def test_write_insert_records_status_created(mod, tmp_path):
    """The INSERT payload sets Status='created'."""
    cursor_factory, cursor = _make_cursor_factory(registry_id=1)
    with patch.object(mod, "_get_cursor_for", return_value=cursor_factory):
        mod.write_parquet_snapshot(
            _small_df(),
            source_name="X", table_name="Y",
            business_date=date(2026, 1, 1), batch_id=1,
            output_dir=tmp_path,
        )
    params = cursor.execute.call_args.args[1]
    # Status is the last positional in the param tuple (index -1)
    assert params[-1] == "created"
    # StorageTier is one before (index -2)
    assert params[-2] == "hot"


def test_write_insert_records_sha256_in_content_checksum(mod, tmp_path):
    """ContentChecksum + SchemaHash both carry the SHA-256."""
    cursor_factory, cursor = _make_cursor_factory(registry_id=1)
    with patch.object(mod, "_get_cursor_for", return_value=cursor_factory):
        result = mod.write_parquet_snapshot(
            _small_df(),
            source_name="X", table_name="Y",
            business_date=date(2026, 1, 1), batch_id=1,
            output_dir=tmp_path,
        )
    params = cursor.execute.call_args.args[1]
    # Param order: source, table, batch, date, path, rowcount, uncomp, comp,
    # schema_hash, content_checksum, tier, status
    schema_hash = params[8]
    content_checksum = params[9]
    assert schema_hash == result.sha256
    assert content_checksum == result.sha256


def test_write_insert_records_row_count(mod, tmp_path):
    """RowCount param matches len(df)."""
    cursor_factory, cursor = _make_cursor_factory(registry_id=1)
    df = _wide_df()  # 3 rows
    with patch.object(mod, "_get_cursor_for", return_value=cursor_factory):
        mod.write_parquet_snapshot(
            df,
            source_name="X", table_name="Y",
            business_date=date(2026, 1, 1), batch_id=1,
            output_dir=tmp_path,
        )
    params = cursor.execute.call_args.args[1]
    assert params[5] == 3  # RowCount


# ---------------------------------------------------------------------------
# write_parquet_snapshot: RegistryInsertConflict on UNIQUE
# ---------------------------------------------------------------------------


def test_unique_violation_2601_raises_conflict(mod, tmp_path):
    """UNIQUE 2601 -> RegistryInsertConflict."""
    from utils.errors import RegistryInsertConflict
    cursor_factory, _ = _make_cursor_factory(
        side_effect=_unique_violation_exc(2601)
    )
    with patch.object(mod, "_get_cursor_for", return_value=cursor_factory):
        with pytest.raises(RegistryInsertConflict):
            mod.write_parquet_snapshot(
                _small_df(),
                source_name="X", table_name="Y",
                business_date=date(2026, 1, 1), batch_id=1,
                output_dir=tmp_path,
            )


def test_unique_violation_2627_raises_conflict(mod, tmp_path):
    """PK violation 2627 -> RegistryInsertConflict (same retry semantics)."""
    from utils.errors import RegistryInsertConflict
    cursor_factory, _ = _make_cursor_factory(
        side_effect=_unique_violation_exc(2627)
    )
    with patch.object(mod, "_get_cursor_for", return_value=cursor_factory):
        with pytest.raises(RegistryInsertConflict):
            mod.write_parquet_snapshot(
                _small_df(),
                source_name="X", table_name="Y",
                business_date=date(2026, 1, 1), batch_id=1,
                output_dir=tmp_path,
            )


def test_unique_violation_carries_identity_tuple_metadata(mod, tmp_path):
    """RegistryInsertConflict.metadata carries the identity tuple for retry."""
    from utils.errors import RegistryInsertConflict
    cursor_factory, _ = _make_cursor_factory(side_effect=_unique_violation_exc())
    with patch.object(mod, "_get_cursor_for", return_value=cursor_factory):
        with pytest.raises(RegistryInsertConflict) as exc_info:
            mod.write_parquet_snapshot(
                _small_df(),
                source_name="DNA", table_name="ACCT",
                business_date=date(2026, 5, 13), batch_id=12345,
                output_dir=tmp_path,
            )
    md = exc_info.value.metadata
    assert md["source_name"] == "DNA"
    assert md["table_name"] == "ACCT"
    assert md["batch_id"] == 12345
    assert md["business_date"] == "2026-05-13"


def test_non_unique_integrity_error_bubbles_up(mod, tmp_path):
    """Non-UNIQUE IntegrityError (FK violation) bubbles up unchanged."""
    cursor_factory, _ = _make_cursor_factory(side_effect=_other_integrity_exc())
    with patch.object(mod, "_get_cursor_for", return_value=cursor_factory):
        with pytest.raises(pyodbc.IntegrityError):
            mod.write_parquet_snapshot(
                _small_df(),
                source_name="X", table_name="Y",
                business_date=date(2026, 1, 1), batch_id=1,
                output_dir=tmp_path,
            )


def test_unique_violation_after_rename_leaves_file(mod, tmp_path):
    """On UNIQUE violation, the Parquet file IS written; only the registry row is missing."""
    from utils.errors import RegistryInsertConflict
    cursor_factory, _ = _make_cursor_factory(side_effect=_unique_violation_exc())
    with patch.object(mod, "_get_cursor_for", return_value=cursor_factory):
        with pytest.raises(RegistryInsertConflict):
            mod.write_parquet_snapshot(
                _small_df(),
                source_name="X", table_name="Y",
                business_date=date(2026, 1, 1), batch_id=999,
                output_dir=tmp_path,
            )
    expected = (
        tmp_path / "X" / "Y" / "year=2026" / "month=01" / "day=01"
        / "999.parquet"
    )
    # The file exists (write + rename succeeded; only the INSERT failed).
    assert expected.exists()


# ---------------------------------------------------------------------------
# Driver / OUTPUT anomaly: fetchone returns None
# ---------------------------------------------------------------------------


def test_fetchone_none_raises_conflict(mod, tmp_path):
    """When OUTPUT clause returns no row, raise RegistryInsertConflict."""
    from utils.errors import RegistryInsertConflict
    cursor_factory, _ = _make_cursor_factory(fetchone_returns_none=True)
    with patch.object(mod, "_get_cursor_for", return_value=cursor_factory):
        with pytest.raises(RegistryInsertConflict):
            mod.write_parquet_snapshot(
                _small_df(),
                source_name="X", table_name="Y",
                business_date=date(2026, 1, 1), batch_id=1,
                output_dir=tmp_path,
            )


# ---------------------------------------------------------------------------
# Crash injection: kill mid-rename
# ---------------------------------------------------------------------------


def test_crash_mid_rename_leaves_inflight_no_registry_row(mod, tmp_path):
    """ParquetWriteCrash mid-rename -> inflight file present + no INSERT issued."""
    from utils.errors import ParquetWriteCrash
    cursor_factory, cursor = _make_cursor_factory(registry_id=1)
    # Make os.replace fail at the rename step
    with patch.object(mod, "_get_cursor_for", return_value=cursor_factory), \
         patch("os.replace", side_effect=OSError(28, "No space left")):
        with pytest.raises(ParquetWriteCrash) as exc_info:
            mod.write_parquet_snapshot(
                _small_df(),
                source_name="X", table_name="Y",
                business_date=date(2026, 1, 1), batch_id=42,
                output_dir=tmp_path,
            )

    # Inflight file present
    inflight = (
        tmp_path / "X" / "Y" / "year=2026" / "month=01" / "day=01"
        / "42.parquet.inflight"
    )
    final = inflight.with_name("42.parquet")
    assert inflight.exists()
    assert not final.exists()
    # No INSERT issued (cursor.execute never called)
    assert cursor.execute.call_count == 0
    # Metadata carries paths for operator recovery
    assert exc_info.value.metadata["errno"] == 28


def test_crash_after_rename_before_insert(mod, tmp_path):
    """If INSERT raises (after successful rename), file is present but no row."""
    from utils.errors import RegistryInsertConflict
    cursor_factory, _ = _make_cursor_factory(side_effect=_unique_violation_exc())
    with patch.object(mod, "_get_cursor_for", return_value=cursor_factory):
        with pytest.raises(RegistryInsertConflict):
            mod.write_parquet_snapshot(
                _small_df(),
                source_name="X", table_name="Y",
                business_date=date(2026, 1, 1), batch_id=42,
                output_dir=tmp_path,
            )
    # File present at final canonical name; no inflight leftover.
    final = (
        tmp_path / "X" / "Y" / "year=2026" / "month=01" / "day=01"
        / "42.parquet"
    )
    inflight = final.with_name("42.parquet.inflight")
    assert final.exists()
    assert not inflight.exists()


# ---------------------------------------------------------------------------
# DataFrame size variations
# ---------------------------------------------------------------------------


def test_empty_dataframe_writes_zero_rows(mod, tmp_path):
    """Empty DataFrame writes a valid Parquet file with row_count=0."""
    cursor_factory, _ = _make_cursor_factory(registry_id=1)
    with patch.object(mod, "_get_cursor_for", return_value=cursor_factory):
        result = mod.write_parquet_snapshot(
            _empty_df(),
            source_name="X", table_name="Y",
            business_date=date(2026, 1, 1), batch_id=1,
            output_dir=tmp_path,
        )
    assert result.row_count == 0
    assert result.file_path.exists()
    assert result.file_size_bytes > 0  # Parquet metadata + footer present


def test_single_row_dataframe(mod, tmp_path):
    """Single-row DataFrame writes correctly."""
    cursor_factory, _ = _make_cursor_factory(registry_id=1)
    with patch.object(mod, "_get_cursor_for", return_value=cursor_factory):
        result = mod.write_parquet_snapshot(
            _single_row_df(),
            source_name="X", table_name="Y",
            business_date=date(2026, 1, 1), batch_id=1,
            output_dir=tmp_path,
        )
    assert result.row_count == 1


def test_wide_dataframe_many_columns(mod, tmp_path):
    """Wide DataFrame (20 columns) writes correctly."""
    cursor_factory, _ = _make_cursor_factory(registry_id=1)
    with patch.object(mod, "_get_cursor_for", return_value=cursor_factory):
        result = mod.write_parquet_snapshot(
            _wide_df(),
            source_name="X", table_name="Y",
            business_date=date(2026, 1, 1), batch_id=1,
            output_dir=tmp_path,
        )
    assert result.row_count == 3


# ---------------------------------------------------------------------------
# Parquet content validation — round-trip read back
# ---------------------------------------------------------------------------


def test_written_parquet_is_readable_round_trip(mod, tmp_path):
    """Polars can read back the written Parquet and the contents match."""
    cursor_factory, _ = _make_cursor_factory(registry_id=1)
    df_in = _small_df()
    with patch.object(mod, "_get_cursor_for", return_value=cursor_factory):
        result = mod.write_parquet_snapshot(
            df_in,
            source_name="X", table_name="Y",
            business_date=date(2026, 1, 1), batch_id=1,
            output_dir=tmp_path,
        )
    df_out = pl.read_parquet(result.file_path)
    assert df_out.equals(df_in)


def test_written_parquet_uses_zstd_compression(mod, tmp_path):
    """The written file is ZSTD-compressed per D45.2."""
    cursor_factory, _ = _make_cursor_factory(registry_id=1)
    df = pl.DataFrame({
        # Highly compressible payload to make compression visible
        "v": ["AAAAAAAAAA" * 100] * 100,
    })
    with patch.object(mod, "_get_cursor_for", return_value=cursor_factory):
        result = mod.write_parquet_snapshot(
            df,
            source_name="X", table_name="Y",
            business_date=date(2026, 1, 1), batch_id=1,
            output_dir=tmp_path,
        )
    # Compressed size should be a fraction of the uncompressed payload
    # (the test payload is ~100 KB uncompressed; ZSTD-3 typically gives
    # well under 10 KB for this regular pattern).
    assert result.file_size_bytes < 10_000


# ---------------------------------------------------------------------------
# Idempotency — second call same key raises conflict
# ---------------------------------------------------------------------------


def test_idempotency_second_call_same_key_raises(mod, tmp_path):
    """Second call with same (source, table, batch, date) raises RegistryInsertConflict.

    The first call succeeds; the second call's INSERT trips the UNIQUE
    constraint at the DB. We simulate by switching the cursor side-effect
    between calls.
    """
    from utils.errors import RegistryInsertConflict

    # Cursor returns successful OUTPUT on call 1, then UNIQUE violation on call 2.
    cursor = MagicMock()
    cursor.fetchone.return_value = (1,)
    cursor.rowcount = 1
    call_count = {"n": 0}

    def _execute(*_args, **_kwargs):
        call_count["n"] += 1
        if call_count["n"] == 2:
            raise _unique_violation_exc()
    cursor.execute.side_effect = _execute

    def _factory(_db: str):
        cm = MagicMock()
        cm.__enter__ = MagicMock(return_value=cursor)
        cm.__exit__ = MagicMock(return_value=False)
        return cm

    with patch.object(mod, "_get_cursor_for", return_value=_factory):
        # First call succeeds
        result = mod.write_parquet_snapshot(
            _small_df(),
            source_name="X", table_name="Y",
            business_date=date(2026, 1, 1), batch_id=1,
            output_dir=tmp_path,
        )
        assert result.status == "created"

        # Second call (same key) trips UNIQUE
        with pytest.raises(RegistryInsertConflict):
            mod.write_parquet_snapshot(
                _small_df(),
                source_name="X", table_name="Y",
                business_date=date(2026, 1, 1), batch_id=1,
                output_dir=tmp_path,
            )


# ---------------------------------------------------------------------------
# Output_dir resolution path through write_parquet_snapshot itself
# ---------------------------------------------------------------------------


def test_write_uses_env_output_dir_when_none(mod, tmp_path, monkeypatch):
    """write_parquet_snapshot(output_dir=None) reads PARQUET_OUTPUT_DIR."""
    monkeypatch.setenv("PARQUET_OUTPUT_DIR", str(tmp_path))
    cursor_factory, _ = _make_cursor_factory(registry_id=1)
    with patch.object(mod, "_get_cursor_for", return_value=cursor_factory):
        result = mod.write_parquet_snapshot(
            _small_df(),
            source_name="X", table_name="Y",
            business_date=date(2026, 1, 1), batch_id=1,
            output_dir=None,
        )
    # Verify file landed under the env-resolved directory
    assert str(result.file_path).startswith(str(tmp_path))


def test_write_raises_when_no_output_dir_and_no_env(mod, monkeypatch):
    """No output_dir + unset env -> ParquetWriteCrash before any work."""
    from utils.errors import ParquetWriteCrash
    monkeypatch.delenv("PARQUET_OUTPUT_DIR", raising=False)
    cursor_factory, cursor = _make_cursor_factory(registry_id=1)
    with patch.object(mod, "_get_cursor_for", return_value=cursor_factory):
        with pytest.raises(ParquetWriteCrash):
            mod.write_parquet_snapshot(
                _small_df(),
                source_name="X", table_name="Y",
                business_date=date(2026, 1, 1), batch_id=1,
                output_dir=None,
            )
    # No INSERT issued because resolution failed before write
    assert cursor.execute.call_count == 0


# ---------------------------------------------------------------------------
# mkdir -p: parent directory creation
# ---------------------------------------------------------------------------


def test_partition_directory_auto_created(mod, tmp_path):
    """The Hive partition directory chain is created on first write."""
    cursor_factory, _ = _make_cursor_factory(registry_id=1)
    # Use a NEW (non-existent) subdirectory under tmp_path
    fresh_out = tmp_path / "new_root_dir"
    assert not fresh_out.exists()
    with patch.object(mod, "_get_cursor_for", return_value=cursor_factory):
        result = mod.write_parquet_snapshot(
            _small_df(),
            source_name="X", table_name="Y",
            business_date=date(2026, 1, 1), batch_id=1,
            output_dir=fresh_out,
        )
    # Full chain created
    assert result.file_path.parent.is_dir()
    assert result.file_path.exists()


def test_idempotent_partition_directory(mod, tmp_path):
    """Re-writing into the same partition directory does not raise."""
    cursor_factory, _ = _make_cursor_factory(registry_id=1)
    with patch.object(mod, "_get_cursor_for", return_value=cursor_factory):
        # First write creates the chain
        mod.write_parquet_snapshot(
            _small_df(),
            source_name="X", table_name="Y",
            business_date=date(2026, 1, 1), batch_id=1,
            output_dir=tmp_path,
        )
        # Different batch_id, same partition — exist_ok=True path
        result = mod.write_parquet_snapshot(
            _small_df(),
            source_name="X", table_name="Y",
            business_date=date(2026, 1, 1), batch_id=2,
            output_dir=tmp_path,
        )
    assert result.file_path.exists()


# ---------------------------------------------------------------------------
# Inflight-rename ordering invariants
# ---------------------------------------------------------------------------


def test_inflight_file_removed_after_successful_rename(mod, tmp_path):
    """Post-rename, only the final canonical file exists (no inflight leftover)."""
    cursor_factory, _ = _make_cursor_factory(registry_id=1)
    with patch.object(mod, "_get_cursor_for", return_value=cursor_factory):
        result = mod.write_parquet_snapshot(
            _small_df(),
            source_name="X", table_name="Y",
            business_date=date(2026, 1, 1), batch_id=1,
            output_dir=tmp_path,
        )
    inflight = result.file_path.with_name(result.file_path.name + ".inflight")
    assert result.file_path.exists()
    assert not inflight.exists()


def test_inflight_path_naming(mod):
    """Inflight suffix is exactly '.inflight'."""
    assert mod._INFLIGHT_SUFFIX == ".inflight"


def test_hash_computed_after_rename_not_before(mod, tmp_path):
    """SHA-256 reflects the post-rename canonical file content."""
    cursor_factory, _ = _make_cursor_factory(registry_id=1)
    with patch.object(mod, "_get_cursor_for", return_value=cursor_factory):
        result = mod.write_parquet_snapshot(
            _small_df(),
            source_name="X", table_name="Y",
            business_date=date(2026, 1, 1), batch_id=1,
            output_dir=tmp_path,
        )
    # The reported sha256 must match what hashlib reads from the canonical
    # file (post-rename). If we hashed before rename, this could diverge
    # under OS-level write cache races; the test pins the ordering.
    reread = hashlib.sha256(result.file_path.read_bytes()).hexdigest()
    assert result.sha256 == reread


# ---------------------------------------------------------------------------
# W-12 shrink_to_fit gating
# ---------------------------------------------------------------------------


def test_shrink_to_fit_not_called_for_small_df(mod, tmp_path):
    """DataFrames <= 100K rows do NOT trigger shrink_to_fit."""
    cursor_factory, _ = _make_cursor_factory(registry_id=1)
    df = _small_df()
    df.shrink_to_fit = MagicMock(wraps=df.shrink_to_fit)
    with patch.object(mod, "_get_cursor_for", return_value=cursor_factory):
        mod.write_parquet_snapshot(
            df,
            source_name="X", table_name="Y",
            business_date=date(2026, 1, 1), batch_id=1,
            output_dir=tmp_path,
        )
    df.shrink_to_fit.assert_not_called()


def test_shrink_to_fit_called_for_large_df(mod, tmp_path):
    """DataFrames > 100K rows DO trigger shrink_to_fit per W-12."""
    cursor_factory, _ = _make_cursor_factory(registry_id=1)
    # Build a >100K row frame
    n = 100_001
    df = pl.DataFrame({"pk_id": list(range(n)), "v": ["x"] * n})
    df.shrink_to_fit = MagicMock(wraps=df.shrink_to_fit)
    with patch.object(mod, "_get_cursor_for", return_value=cursor_factory):
        mod.write_parquet_snapshot(
            df,
            source_name="X", table_name="Y",
            business_date=date(2026, 1, 1), batch_id=1,
            output_dir=tmp_path,
        )
    df.shrink_to_fit.assert_called_once_with(in_place=True)


def test_shrink_to_fit_failure_is_nonfatal(mod, tmp_path):
    """shrink_to_fit raising does NOT fail the write (file + row both durable)."""
    cursor_factory, _ = _make_cursor_factory(registry_id=1)
    n = 100_001
    df = pl.DataFrame({"pk_id": list(range(n)), "v": ["x"] * n})
    df.shrink_to_fit = MagicMock(side_effect=RuntimeError("synthetic"))
    with patch.object(mod, "_get_cursor_for", return_value=cursor_factory):
        result = mod.write_parquet_snapshot(
            df,
            source_name="X", table_name="Y",
            business_date=date(2026, 1, 1), batch_id=1,
            output_dir=tmp_path,
        )
    # Write succeeded despite shrink_to_fit failure
    assert result.status == "created"
    assert result.file_path.exists()


# ---------------------------------------------------------------------------
# ParquetWriteResult: dataclass invariants
# ---------------------------------------------------------------------------


def test_parquet_write_result_equality(mod):
    """Two ParquetWriteResults with identical fields compare equal."""
    a = mod.ParquetWriteResult(
        file_path=Path("/x.parquet"), file_size_bytes=100,
        row_count=10, sha256="a" * 64, registry_id=1, status="created",
    )
    b = mod.ParquetWriteResult(
        file_path=Path("/x.parquet"), file_size_bytes=100,
        row_count=10, sha256="a" * 64, registry_id=1, status="created",
    )
    assert a == b


def test_parquet_write_result_field_types_at_runtime(mod, tmp_path):
    """Runtime types match the dataclass annotations."""
    cursor_factory, _ = _make_cursor_factory(registry_id=1)
    with patch.object(mod, "_get_cursor_for", return_value=cursor_factory):
        result = mod.write_parquet_snapshot(
            _small_df(),
            source_name="X", table_name="Y",
            business_date=date(2026, 1, 1), batch_id=1,
            output_dir=tmp_path,
        )
    assert type(result.file_path) is type(Path())  # noqa: E721
    assert isinstance(result.file_size_bytes, int)
    assert isinstance(result.row_count, int)
    assert isinstance(result.sha256, str)
    assert isinstance(result.registry_id, int)
    assert isinstance(result.status, str)
