"""Tier 1 unit tests for data_load/parquet_replay.py.

Tests run on every commit. No live DB, no live network. All external
dependencies mocked with unittest.mock + lazy-getter patching.

North Star pillars addressed:
  - Idempotent (D15): re-call with same replay_batch_id short-circuits
    via the ledger; the side effect (ledger row INSERT) is not
    duplicated. The DataFrame IS re-materialized — it's the return
    value, not a side effect.
  - Audit-grade (D26 + D76): per-replay metadata (registry_id, file_path,
    sha256, row counts) travels in exception metadata + ledger row.
  - Operationally stable (D69): sibling modules accessed via lazy
    getters; the harness can swap them without sys.modules hackery.
  - Traceability (D25): the replay's ReplayResult.batch_id is the
    ORIGINAL snapshot's BatchId (carried forward into Bronze provenance).

Edge case IDs covered:
  - N5 (verify of file-absent row): ParquetReplayError raised with
    registry_id + file_path in metadata for forensic reconstruction.
  - N7 (hash mismatch): ParquetReplayError raised with both
    expected + computed values in metadata.
  - N8-adjacent (status not eligible): RegistryStatusInvalid raised
    with current_status + eligible_statuses in metadata.

Decision citations:
  D2 (Stage dropped), D4 (network drive Parquet), D15 (idempotency),
  D17 (ledger), D25 (canonical Parquet index), D26 (append-only),
  D45.2 (Parquet config), D67 (Tier 0 disc), D68 (error class hierarchy),
  D69 (cursor ownership), D92 (forward-only).

Spec: ``docs/migration/phase1/03_core_modules.md`` § 1.2.
"""
from __future__ import annotations

import hashlib
import importlib
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import polars as pl
import pytest

# ---------------------------------------------------------------------------
# Project root on sys.path
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_MODULE_KEY = "data_load.parquet_replay"


# ---------------------------------------------------------------------------
# Fixture: fresh module load
# ---------------------------------------------------------------------------


@pytest.fixture
def mod():
    """Load data_load.parquet_replay fresh for each test."""
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


def _make_query_snapshot(row: dict | None, *, capture_calls: list | None = None):
    """Build a mock query_snapshot callable that returns ``row``.

    If ``capture_calls`` is provided, every invocation appends a kwargs
    dict to it (for assertions about what was looked up).
    """
    def _query(**kwargs):
        if capture_calls is not None:
            capture_calls.append(dict(kwargs))
        return row
    return _query


def _make_ledger_step(
    was_short_circuited: bool = False,
    *,
    capture_calls: list | None = None,
    raise_exc: Exception | None = None,
):
    """Build a mock ledger_step context-manager factory."""
    step = MagicMock()
    step.was_short_circuited = was_short_circuited
    step.step_id = 1
    step.prior_result = None

    def _factory(**kwargs):
        if capture_calls is not None:
            capture_calls.append(dict(kwargs))
        cm = MagicMock()
        if raise_exc is not None:
            cm.__enter__ = MagicMock(side_effect=raise_exc)
        else:
            cm.__enter__ = MagicMock(return_value=step)
        cm.__exit__ = MagicMock(return_value=False)
        return cm

    return _factory


def _write_parquet_fixture(
    tmp_path: Path,
    df: pl.DataFrame,
    *,
    filename: str = "test.parquet",
) -> tuple[Path, str]:
    """Write df to ``tmp_path/<filename>``; return (path, sha256_hex)."""
    file_path = tmp_path / filename
    df.write_parquet(file_path)
    sha = hashlib.sha256(file_path.read_bytes()).hexdigest()
    return file_path, sha


def _patches(mod, query_snapshot=None, ledger_step=None):
    """Build the context-manager pair for both lazy-getter patches."""
    if query_snapshot is None:
        query_snapshot = _make_query_snapshot(None)
    if ledger_step is None:
        ledger_step = _make_ledger_step()
    return (
        patch.object(mod, "_get_query_snapshot", return_value=query_snapshot),
        patch.object(mod, "_get_ledger_step", return_value=ledger_step),
    )


# ---------------------------------------------------------------------------
# Public surface — sanity checks
# ---------------------------------------------------------------------------


class TestPublicSurface:

    def test_replay_eligible_statuses_immutable(self, mod):
        """REPLAY_ELIGIBLE_STATUSES is a frozenset (cannot be mutated)."""
        assert isinstance(mod.REPLAY_ELIGIBLE_STATUSES, frozenset)
        with pytest.raises(AttributeError):
            mod.REPLAY_ELIGIBLE_STATUSES.add("created")

    def test_event_type_replay_canonical(self, mod):
        """EVENT_TYPE_REPLAY is the canonical 'REPLAY' string."""
        assert mod.EVENT_TYPE_REPLAY == "REPLAY"

    def test_replay_result_is_frozen(self, mod):
        """ReplayResult is a frozen dataclass — mutation raises."""
        df = pl.DataFrame({"id": [1]})
        result = mod.ReplayResult(
            df=df,
            registry_id=1,
            source_file=Path("/tmp/x.parquet"),
            row_count=1,
            sha256_verified="a" * 64,
            extracted_at=datetime(2026, 1, 1),
            batch_id=100,
        )
        with pytest.raises(Exception):  # FrozenInstanceError or dataclass equivalent
            result.row_count = 99

    def test_replay_result_fields(self, mod):
        """ReplayResult exposes all 7 documented fields."""
        df = pl.DataFrame({"id": [1]})
        result = mod.ReplayResult(
            df=df,
            registry_id=1,
            source_file=Path("/tmp/x.parquet"),
            row_count=1,
            sha256_verified="a" * 64,
            extracted_at=datetime(2026, 1, 1),
            batch_id=100,
        )
        assert result.df.height == 1
        assert result.registry_id == 1
        assert result.source_file == Path("/tmp/x.parquet")
        assert result.row_count == 1
        assert result.sha256_verified == "a" * 64
        assert result.extracted_at == datetime(2026, 1, 1)
        assert result.batch_id == 100


# ---------------------------------------------------------------------------
# Happy path — registry lookup + file read + SHA verify + materialize
# ---------------------------------------------------------------------------


class TestHappyPath:

    def test_replay_happy_path_status_verified(self, mod, tmp_path):
        """Status='verified' + matching SHA + matching row count: returns DataFrame."""
        df = pl.DataFrame({"id": [1, 2, 3], "value": ["a", "b", "c"]})
        file_path, sha = _write_parquet_fixture(tmp_path, df)
        row = _canonical_row(
            Status="verified",
            NetworkDrivePath=str(file_path),
            ContentChecksum=sha,
            RowCount=3,
        )

        p1, p2 = _patches(
            mod,
            query_snapshot=_make_query_snapshot(row),
            ledger_step=_make_ledger_step(),
        )
        with p1, p2:
            result = mod.replay_parquet_snapshot(
                source_name="DNA",
                table_name="ACCT",
                business_date=date(2026, 1, 1),
                original_batch_id=12345,
                replay_batch_id=99999,
            )

        assert result.df.height == 3
        assert result.df.columns == ["id", "value"]
        assert result.sha256_verified.lower() == sha.lower()
        assert result.registry_id == 42
        assert result.batch_id == 12345

    def test_replay_happy_path_status_replicated(self, mod, tmp_path):
        """Status='replicated' is also replay-eligible."""
        df = pl.DataFrame({"id": [1]})
        file_path, sha = _write_parquet_fixture(tmp_path, df)
        row = _canonical_row(
            Status="replicated",
            NetworkDrivePath=str(file_path),
            ContentChecksum=sha,
            RowCount=1,
        )

        p1, p2 = _patches(
            mod, query_snapshot=_make_query_snapshot(row),
        )
        with p1, p2:
            result = mod.replay_parquet_snapshot(
                source_name="DNA",
                table_name="ACCT",
                business_date=date(2026, 1, 1),
                original_batch_id=12345,
                replay_batch_id=99999,
            )
        assert result.row_count == 1

    def test_replay_happy_path_status_archived(self, mod, tmp_path):
        """Status='archived' is also replay-eligible (D30 cold-storage rebuild)."""
        df = pl.DataFrame({"id": [1, 2]})
        file_path, sha = _write_parquet_fixture(tmp_path, df)
        row = _canonical_row(
            Status="archived",
            NetworkDrivePath=str(file_path),
            ContentChecksum=sha,
            RowCount=2,
        )

        p1, p2 = _patches(
            mod, query_snapshot=_make_query_snapshot(row),
        )
        with p1, p2:
            result = mod.replay_parquet_snapshot(
                source_name="DNA",
                table_name="ACCT",
                business_date=date(2026, 1, 1),
                original_batch_id=12345,
                replay_batch_id=99999,
            )
        assert result.row_count == 2

    def test_replay_preserves_df_schema(self, mod, tmp_path):
        """The materialized DataFrame's schema matches the source DataFrame's."""
        df = pl.DataFrame({
            "pk": pl.Series([1, 2], dtype=pl.Int64),
            "name": pl.Series(["x", "y"], dtype=pl.Utf8),
            "flag": pl.Series([True, False], dtype=pl.Boolean),
        })
        file_path, sha = _write_parquet_fixture(tmp_path, df)
        row = _canonical_row(
            NetworkDrivePath=str(file_path),
            ContentChecksum=sha,
            RowCount=2,
        )

        p1, p2 = _patches(
            mod, query_snapshot=_make_query_snapshot(row),
        )
        with p1, p2:
            result = mod.replay_parquet_snapshot(
                source_name="DNA",
                table_name="ACCT",
                business_date=date(2026, 1, 1),
                original_batch_id=12345,
                replay_batch_id=99999,
            )

        assert result.df.schema["pk"] == pl.Int64
        assert result.df.schema["name"] == pl.Utf8
        assert result.df.schema["flag"] == pl.Boolean

    def test_replay_preserves_df_content(self, mod, tmp_path):
        """The materialized DataFrame's content matches the source DataFrame's."""
        df = pl.DataFrame({"id": [10, 20, 30], "value": ["alpha", "beta", "gamma"]})
        file_path, sha = _write_parquet_fixture(tmp_path, df)
        row = _canonical_row(
            NetworkDrivePath=str(file_path),
            ContentChecksum=sha,
            RowCount=3,
        )

        p1, p2 = _patches(
            mod, query_snapshot=_make_query_snapshot(row),
        )
        with p1, p2:
            result = mod.replay_parquet_snapshot(
                source_name="DNA",
                table_name="ACCT",
                business_date=date(2026, 1, 1),
                original_batch_id=12345,
                replay_batch_id=99999,
            )

        assert result.df.to_dicts() == df.to_dicts()


# ---------------------------------------------------------------------------
# SHA-256 verification
# ---------------------------------------------------------------------------


class TestSHA256Verification:

    def test_sha_mismatch_raises_parquet_replay_error(self, mod, tmp_path):
        """Wrong ContentChecksum raises ParquetReplayError."""
        df = pl.DataFrame({"id": [1, 2, 3]})
        file_path, _real_sha = _write_parquet_fixture(tmp_path, df)
        row = _canonical_row(
            NetworkDrivePath=str(file_path),
            ContentChecksum="0" * 64,  # deliberately wrong
            RowCount=3,
        )

        from utils.errors import ParquetReplayError

        p1, p2 = _patches(
            mod, query_snapshot=_make_query_snapshot(row),
        )
        with p1, p2:
            with pytest.raises(ParquetReplayError) as exc_info:
                mod.replay_parquet_snapshot(
                    source_name="DNA",
                    table_name="ACCT",
                    business_date=date(2026, 1, 1),
                    original_batch_id=12345,
                    replay_batch_id=99999,
                )

        # Metadata carries forensic detail per D76
        assert exc_info.value.metadata["registry_id"] == 42
        assert exc_info.value.metadata["expected_sha256"] == "0" * 64
        assert len(exc_info.value.metadata["computed_sha256"]) == 64

    def test_sha_match_uses_content_checksum_first(self, mod, tmp_path):
        """When ContentChecksum is present, it (not SchemaHash) is the comparison target."""
        df = pl.DataFrame({"id": [1]})
        file_path, sha = _write_parquet_fixture(tmp_path, df)
        row = _canonical_row(
            NetworkDrivePath=str(file_path),
            ContentChecksum=sha,
            SchemaHash="0" * 64,  # different from the actual SHA — must be ignored
            RowCount=1,
        )

        p1, p2 = _patches(
            mod, query_snapshot=_make_query_snapshot(row),
        )
        with p1, p2:
            result = mod.replay_parquet_snapshot(
                source_name="DNA",
                table_name="ACCT",
                business_date=date(2026, 1, 1),
                original_batch_id=12345,
                replay_batch_id=99999,
            )
        assert result.sha256_verified.lower() == sha.lower()

    def test_sha_null_content_falls_back_to_schema_hash(self, mod, tmp_path):
        """When ContentChecksum is NULL, falls back to SchemaHash (defense-in-depth)."""
        df = pl.DataFrame({"id": [1]})
        file_path, sha = _write_parquet_fixture(tmp_path, df)
        row = _canonical_row(
            NetworkDrivePath=str(file_path),
            ContentChecksum=None,
            SchemaHash=sha,
            RowCount=1,
        )

        p1, p2 = _patches(
            mod, query_snapshot=_make_query_snapshot(row),
        )
        with p1, p2:
            result = mod.replay_parquet_snapshot(
                source_name="DNA",
                table_name="ACCT",
                business_date=date(2026, 1, 1),
                original_batch_id=12345,
                replay_batch_id=99999,
            )
        assert result.sha256_verified.lower() == sha.lower()

    def test_sha_both_null_raises_parquet_replay_error(self, mod, tmp_path):
        """When BOTH ContentChecksum AND SchemaHash are NULL, raises ParquetReplayError."""
        df = pl.DataFrame({"id": [1]})
        file_path, _sha = _write_parquet_fixture(tmp_path, df)
        row = _canonical_row(
            NetworkDrivePath=str(file_path),
            ContentChecksum=None,
            SchemaHash=None,
            RowCount=1,
        )

        from utils.errors import ParquetReplayError

        p1, p2 = _patches(
            mod, query_snapshot=_make_query_snapshot(row),
        )
        with p1, p2:
            with pytest.raises(ParquetReplayError) as exc_info:
                mod.replay_parquet_snapshot(
                    source_name="DNA",
                    table_name="ACCT",
                    business_date=date(2026, 1, 1),
                    original_batch_id=12345,
                    replay_batch_id=99999,
                )
        assert exc_info.value.metadata["expected_sha256"] is None

    def test_sha_comparison_is_case_insensitive(self, mod, tmp_path):
        """SHA comparison is case-insensitive (hex digits)."""
        df = pl.DataFrame({"id": [1]})
        file_path, sha = _write_parquet_fixture(tmp_path, df)
        row = _canonical_row(
            NetworkDrivePath=str(file_path),
            ContentChecksum=sha.upper(),  # registry stored uppercase — uncommon but legal
            RowCount=1,
        )

        p1, p2 = _patches(
            mod, query_snapshot=_make_query_snapshot(row),
        )
        with p1, p2:
            result = mod.replay_parquet_snapshot(
                source_name="DNA",
                table_name="ACCT",
                business_date=date(2026, 1, 1),
                original_batch_id=12345,
                replay_batch_id=99999,
            )
        # Match succeeded — no exception raised
        assert result.sha256_verified.lower() == sha.lower()

    def test_compute_file_sha256_helper_matches_hashlib(self, mod, tmp_path):
        """_compute_file_sha256 helper produces hashlib-equivalent output."""
        file_path = tmp_path / "test.bin"
        payload = b"\x00\x01\x02" * 1000
        file_path.write_bytes(payload)
        expected = hashlib.sha256(payload).hexdigest()
        actual = mod._compute_file_sha256(file_path)
        assert actual == expected

    def test_compute_file_sha256_streams_large_files(self, mod, tmp_path):
        """_compute_file_sha256 handles files >1 MiB without OOM."""
        file_path = tmp_path / "big.bin"
        # Write 2.5 MiB to exercise the multi-chunk read path
        payload = b"x" * (2 * 1024 * 1024 + 512 * 1024)
        file_path.write_bytes(payload)
        expected = hashlib.sha256(payload).hexdigest()
        actual = mod._compute_file_sha256(file_path)
        assert actual == expected


# ---------------------------------------------------------------------------
# File-missing path
# ---------------------------------------------------------------------------


class TestFileMissing:

    def test_file_missing_raises_parquet_replay_error(self, mod, tmp_path):
        """When NetworkDrivePath doesn't exist on disk, raises ParquetReplayError."""
        row = _canonical_row(
            NetworkDrivePath=str(tmp_path / "does_not_exist.parquet"),
        )

        from utils.errors import ParquetReplayError

        p1, p2 = _patches(
            mod, query_snapshot=_make_query_snapshot(row),
        )
        with p1, p2:
            with pytest.raises(ParquetReplayError) as exc_info:
                mod.replay_parquet_snapshot(
                    source_name="DNA",
                    table_name="ACCT",
                    business_date=date(2026, 1, 1),
                    original_batch_id=12345,
                    replay_batch_id=99999,
                )

        assert exc_info.value.metadata["registry_id"] == 42
        assert "does_not_exist" in exc_info.value.metadata["file_path"]
        assert exc_info.value.metadata["replay_batch_id"] == 99999

    def test_file_missing_does_not_attempt_sha(self, mod, tmp_path):
        """File-missing path raises BEFORE SHA computation (no FileNotFoundError leakage)."""
        row = _canonical_row(
            NetworkDrivePath=str(tmp_path / "nope.parquet"),
        )

        from utils.errors import ParquetReplayError

        p1, p2 = _patches(
            mod, query_snapshot=_make_query_snapshot(row),
        )
        with p1, p2:
            # The exception type is ParquetReplayError, not FileNotFoundError.
            # If the file-missing check came AFTER SHA computation, we'd see
            # FileNotFoundError leak through.
            with pytest.raises(ParquetReplayError):
                mod.replay_parquet_snapshot(
                    source_name="DNA",
                    table_name="ACCT",
                    business_date=date(2026, 1, 1),
                    original_batch_id=12345,
                    replay_batch_id=99999,
                )


# ---------------------------------------------------------------------------
# Status eligibility — exhaustive over all 7 enum values
# ---------------------------------------------------------------------------


class TestStatusEligibility:

    @pytest.mark.parametrize(
        "status,eligible",
        [
            ("created", False),
            ("verified", True),
            ("replicated", True),
            ("archived", True),
            ("missing", False),
            ("purged", False),
            ("replication_failed", False),
        ],
    )
    def test_status_eligibility(self, mod, tmp_path, status, eligible):
        """Exhaustive matrix over the 7 registry statuses — verifies eligibility."""
        df = pl.DataFrame({"id": [1]})
        file_path, sha = _write_parquet_fixture(tmp_path, df)
        row = _canonical_row(
            Status=status,
            NetworkDrivePath=str(file_path),
            ContentChecksum=sha,
            RowCount=1,
        )

        from utils.errors import RegistryStatusInvalid

        p1, p2 = _patches(
            mod, query_snapshot=_make_query_snapshot(row),
        )
        with p1, p2:
            if eligible:
                # Should NOT raise
                result = mod.replay_parquet_snapshot(
                    source_name="DNA",
                    table_name="ACCT",
                    business_date=date(2026, 1, 1),
                    original_batch_id=12345,
                    replay_batch_id=99999,
                )
                assert result.row_count == 1
            else:
                with pytest.raises(RegistryStatusInvalid):
                    mod.replay_parquet_snapshot(
                        source_name="DNA",
                        table_name="ACCT",
                        business_date=date(2026, 1, 1),
                        original_batch_id=12345,
                        replay_batch_id=99999,
                    )

    def test_status_invalid_carries_metadata(self, mod):
        """RegistryStatusInvalid metadata includes current_status + eligible_statuses."""
        row = _canonical_row(Status="created")

        from utils.errors import RegistryStatusInvalid

        p1, p2 = _patches(
            mod, query_snapshot=_make_query_snapshot(row),
        )
        with p1, p2:
            with pytest.raises(RegistryStatusInvalid) as exc_info:
                mod.replay_parquet_snapshot(
                    source_name="DNA",
                    table_name="ACCT",
                    business_date=date(2026, 1, 1),
                    original_batch_id=12345,
                    replay_batch_id=99999,
                )

        assert exc_info.value.metadata["current_status"] == "created"
        assert "verified" in exc_info.value.metadata["eligible_statuses"]
        assert exc_info.value.metadata["registry_id"] == 42


# ---------------------------------------------------------------------------
# Registry lookup — RegistryNotFound
# ---------------------------------------------------------------------------


class TestRegistryNotFound:

    def test_registry_not_found_raises(self, mod):
        """When query_snapshot returns None, RegistryNotFound is raised."""
        from utils.errors import RegistryNotFound

        p1, p2 = _patches(
            mod, query_snapshot=_make_query_snapshot(None),
        )
        with p1, p2:
            with pytest.raises(RegistryNotFound):
                mod.replay_parquet_snapshot(
                    source_name="DNA",
                    table_name="ACCT",
                    business_date=date(2026, 1, 1),
                    original_batch_id=999_999,
                    replay_batch_id=99999,
                )

    def test_registry_not_found_metadata(self, mod):
        """RegistryNotFound carries the lookup-key tuple in metadata."""
        from utils.errors import RegistryNotFound

        p1, p2 = _patches(
            mod, query_snapshot=_make_query_snapshot(None),
        )
        with p1, p2:
            with pytest.raises(RegistryNotFound) as exc_info:
                mod.replay_parquet_snapshot(
                    source_name="CCM",
                    table_name="Transactions",
                    business_date=date(2025, 12, 31),
                    original_batch_id=12345,
                    replay_batch_id=99999,
                )

        assert exc_info.value.metadata["source_name"] == "CCM"
        assert exc_info.value.metadata["table_name"] == "Transactions"
        assert exc_info.value.metadata["business_date"] == "2025-12-31"
        assert exc_info.value.metadata["original_batch_id"] == 12345

    def test_registry_lookup_uses_correct_key(self, mod):
        """The registry lookup passes the lookup-key tuple unchanged."""
        capture: list[dict] = []

        from utils.errors import RegistryNotFound

        p1, p2 = _patches(
            mod, query_snapshot=_make_query_snapshot(None, capture_calls=capture),
        )
        with p1, p2:
            with pytest.raises(RegistryNotFound):
                mod.replay_parquet_snapshot(
                    source_name="EPICOR",
                    table_name="OrderLines",
                    business_date=date(2026, 3, 15),
                    original_batch_id=7777,
                    replay_batch_id=99999,
                )

        assert len(capture) == 1
        assert capture[0]["source_name"] == "EPICOR"
        assert capture[0]["table_name"] == "OrderLines"
        assert capture[0]["business_date"] == date(2026, 3, 15)
        assert capture[0]["batch_id"] == 7777


# ---------------------------------------------------------------------------
# Row-count guard
# ---------------------------------------------------------------------------


class TestRowCountGuard:

    def test_row_count_mismatch_raises(self, mod, tmp_path):
        """When file row count differs from registry RowCount, raises ParquetReplayError."""
        df = pl.DataFrame({"id": [1, 2, 3]})
        file_path, sha = _write_parquet_fixture(tmp_path, df)
        row = _canonical_row(
            NetworkDrivePath=str(file_path),
            ContentChecksum=sha,
            RowCount=99,  # lie about the count
        )

        from utils.errors import ParquetReplayError

        p1, p2 = _patches(
            mod, query_snapshot=_make_query_snapshot(row),
        )
        with p1, p2:
            with pytest.raises(ParquetReplayError) as exc_info:
                mod.replay_parquet_snapshot(
                    source_name="DNA",
                    table_name="ACCT",
                    business_date=date(2026, 1, 1),
                    original_batch_id=12345,
                    replay_batch_id=99999,
                )
        assert exc_info.value.metadata["actual_row_count"] == 3
        assert exc_info.value.metadata["expected_row_count"] == 99

    def test_row_count_zero_match_succeeds(self, mod, tmp_path):
        """Zero-row Parquet file with RowCount=0 returns an empty DataFrame."""
        df = pl.DataFrame({"id": pl.Series([], dtype=pl.Int64)})
        file_path, sha = _write_parquet_fixture(tmp_path, df)
        row = _canonical_row(
            NetworkDrivePath=str(file_path),
            ContentChecksum=sha,
            RowCount=0,
        )

        p1, p2 = _patches(
            mod, query_snapshot=_make_query_snapshot(row),
        )
        with p1, p2:
            result = mod.replay_parquet_snapshot(
                source_name="DNA",
                table_name="ACCT",
                business_date=date(2026, 1, 1),
                original_batch_id=12345,
                replay_batch_id=99999,
            )
        assert result.df.height == 0
        assert result.row_count == 0


# ---------------------------------------------------------------------------
# Ledger composition
# ---------------------------------------------------------------------------


class TestLedgerComposition:

    def test_ledger_step_keyed_by_replay_batch_id(self, mod, tmp_path):
        """ledger_step is invoked with batch_id=replay_batch_id (NOT original)."""
        df = pl.DataFrame({"id": [1]})
        file_path, sha = _write_parquet_fixture(tmp_path, df)
        row = _canonical_row(
            NetworkDrivePath=str(file_path),
            ContentChecksum=sha,
            RowCount=1,
        )

        capture: list[dict] = []
        ledger = _make_ledger_step(capture_calls=capture)

        p1, p2 = _patches(
            mod,
            query_snapshot=_make_query_snapshot(row),
            ledger_step=ledger,
        )
        with p1, p2:
            mod.replay_parquet_snapshot(
                source_name="DNA",
                table_name="ACCT",
                business_date=date(2026, 1, 1),
                original_batch_id=12345,
                replay_batch_id=99999,
            )

        assert len(capture) == 1
        assert capture[0]["batch_id"] == 99999  # replay_batch_id, not 12345
        assert capture[0]["source_name"] == "DNA"
        assert capture[0]["table_name"] == "ACCT"
        assert capture[0]["event_type"] == "REPLAY"

    def test_ledger_step_metadata_carries_provenance(self, mod, tmp_path):
        """ledger_step metadata kwarg carries registry_id + provenance keys."""
        df = pl.DataFrame({"id": [1]})
        file_path, sha = _write_parquet_fixture(tmp_path, df)
        row = _canonical_row(
            NetworkDrivePath=str(file_path),
            ContentChecksum=sha,
            RowCount=1,
        )

        capture: list[dict] = []
        ledger = _make_ledger_step(capture_calls=capture)

        p1, p2 = _patches(
            mod,
            query_snapshot=_make_query_snapshot(row),
            ledger_step=ledger,
        )
        with p1, p2:
            mod.replay_parquet_snapshot(
                source_name="DNA",
                table_name="ACCT",
                business_date=date(2026, 1, 1),
                original_batch_id=12345,
                replay_batch_id=99999,
            )

        md = capture[0]["metadata"]
        assert md["registry_id"] == 42
        assert md["original_batch_id"] == 12345
        assert md["replay_batch_id"] == 99999
        assert md["source_name"] == "DNA"
        assert md["table_name"] == "ACCT"
        assert md["business_date"] == "2026-01-01"

    def test_short_circuit_still_returns_df(self, mod, tmp_path):
        """Even on idempotent short-circuit, the DataFrame is re-materialized."""
        df = pl.DataFrame({"id": [1, 2]})
        file_path, sha = _write_parquet_fixture(tmp_path, df)
        row = _canonical_row(
            NetworkDrivePath=str(file_path),
            ContentChecksum=sha,
            RowCount=2,
        )

        p1, p2 = _patches(
            mod,
            query_snapshot=_make_query_snapshot(row),
            ledger_step=_make_ledger_step(was_short_circuited=True),
        )
        with p1, p2:
            result = mod.replay_parquet_snapshot(
                source_name="DNA",
                table_name="ACCT",
                business_date=date(2026, 1, 1),
                original_batch_id=12345,
                replay_batch_id=99999,
            )

        # Short-circuit means the ledger row already existed — but the
        # caller's return value is the DataFrame, so we re-read the file.
        assert result.df.height == 2

    def test_ledger_lock_timeout_propagates(self, mod, tmp_path):
        """LedgerLockTimeout from ledger_step bubbles up to the caller."""
        df = pl.DataFrame({"id": [1]})
        file_path, sha = _write_parquet_fixture(tmp_path, df)
        row = _canonical_row(
            NetworkDrivePath=str(file_path),
            ContentChecksum=sha,
            RowCount=1,
        )

        from utils.errors import LedgerLockTimeout

        p1, p2 = _patches(
            mod,
            query_snapshot=_make_query_snapshot(row),
            ledger_step=_make_ledger_step(
                raise_exc=LedgerLockTimeout("contention", metadata={}),
            ),
        )
        with p1, p2:
            with pytest.raises(LedgerLockTimeout):
                mod.replay_parquet_snapshot(
                    source_name="DNA",
                    table_name="ACCT",
                    business_date=date(2026, 1, 1),
                    original_batch_id=12345,
                    replay_batch_id=99999,
                )


# ---------------------------------------------------------------------------
# extracted_at coercion helper
# ---------------------------------------------------------------------------


class TestExtractedAtCoercion:

    def test_naive_datetime_passes_through(self, mod):
        """A naive datetime (no tzinfo) passes through unchanged."""
        dt = datetime(2026, 1, 15, 10, 30, 0)
        assert mod._coerce_extracted_at(dt) == dt
        assert mod._coerce_extracted_at(dt).tzinfo is None

    def test_aware_datetime_converted_to_utc_naive(self, mod):
        """A tz-aware datetime is converted to UTC and stripped of tzinfo."""
        # 10:30 in UTC+4 == 06:30 UTC
        from datetime import timedelta
        tz_plus_4 = timezone(timedelta(hours=4))
        dt = datetime(2026, 1, 15, 10, 30, 0, tzinfo=tz_plus_4)
        result = mod._coerce_extracted_at(dt)
        assert result.tzinfo is None
        assert result.hour == 6  # 10:30 - 4 = 06:30 UTC

    def test_none_yields_current_utc_ms_precision(self, mod):
        """None falls back to a naive UTC datetime at millisecond precision."""
        result = mod._coerce_extracted_at(None)
        assert isinstance(result, datetime)
        assert result.tzinfo is None
        # microsecond must be a multiple of 1000 (ms precision)
        assert result.microsecond % 1000 == 0

    def test_extracted_at_sourced_from_created_at(self, mod, tmp_path):
        """ReplayResult.extracted_at comes from registry's CreatedAt column."""
        df = pl.DataFrame({"id": [1]})
        file_path, sha = _write_parquet_fixture(tmp_path, df)
        canonical_created = datetime(2025, 11, 30, 23, 59, 59, 999000)
        row = _canonical_row(
            NetworkDrivePath=str(file_path),
            ContentChecksum=sha,
            RowCount=1,
            CreatedAt=canonical_created,
        )

        p1, p2 = _patches(
            mod, query_snapshot=_make_query_snapshot(row),
        )
        with p1, p2:
            result = mod.replay_parquet_snapshot(
                source_name="DNA",
                table_name="ACCT",
                business_date=date(2026, 1, 1),
                original_batch_id=12345,
                replay_batch_id=99999,
            )
        assert result.extracted_at == canonical_created


# ---------------------------------------------------------------------------
# Polars DataFrame shape preservation — additional invariants
# ---------------------------------------------------------------------------


class TestDataFrameShapePreservation:

    def test_int64_preserved(self, mod, tmp_path):
        """Int64 columns survive the write-read round-trip."""
        df = pl.DataFrame({
            "big": pl.Series([2**40, 2**50], dtype=pl.Int64),
        })
        file_path, sha = _write_parquet_fixture(tmp_path, df)
        row = _canonical_row(
            NetworkDrivePath=str(file_path), ContentChecksum=sha, RowCount=2,
        )
        p1, p2 = _patches(mod, query_snapshot=_make_query_snapshot(row))
        with p1, p2:
            result = mod.replay_parquet_snapshot(
                source_name="DNA",
                table_name="ACCT",
                business_date=date(2026, 1, 1),
                original_batch_id=12345,
                replay_batch_id=99999,
            )
        assert result.df.schema["big"] == pl.Int64
        assert result.df["big"].to_list() == [2**40, 2**50]

    def test_utf8_preserved(self, mod, tmp_path):
        """Utf8 columns including unicode survive round-trip."""
        df = pl.DataFrame({"name": ["alpha", "héllo", "日本語"]})
        file_path, sha = _write_parquet_fixture(tmp_path, df)
        row = _canonical_row(
            NetworkDrivePath=str(file_path), ContentChecksum=sha, RowCount=3,
        )
        p1, p2 = _patches(mod, query_snapshot=_make_query_snapshot(row))
        with p1, p2:
            result = mod.replay_parquet_snapshot(
                source_name="DNA",
                table_name="ACCT",
                business_date=date(2026, 1, 1),
                original_batch_id=12345,
                replay_batch_id=99999,
            )
        assert result.df["name"].to_list() == ["alpha", "héllo", "日本語"]

    def test_nulls_preserved(self, mod, tmp_path):
        """NULL values survive round-trip."""
        df = pl.DataFrame({
            "id": [1, 2, 3],
            "value": ["a", None, "c"],
        })
        file_path, sha = _write_parquet_fixture(tmp_path, df)
        row = _canonical_row(
            NetworkDrivePath=str(file_path), ContentChecksum=sha, RowCount=3,
        )
        p1, p2 = _patches(mod, query_snapshot=_make_query_snapshot(row))
        with p1, p2:
            result = mod.replay_parquet_snapshot(
                source_name="DNA",
                table_name="ACCT",
                business_date=date(2026, 1, 1),
                original_batch_id=12345,
                replay_batch_id=99999,
            )
        assert result.df["value"].to_list() == ["a", None, "c"]

    def test_column_order_preserved(self, mod, tmp_path):
        """Column order survives round-trip (critical for BCP CSV positional contract)."""
        df = pl.DataFrame({
            "z_col": [1],
            "a_col": [2],
            "m_col": [3],
        })
        file_path, sha = _write_parquet_fixture(tmp_path, df)
        row = _canonical_row(
            NetworkDrivePath=str(file_path), ContentChecksum=sha, RowCount=1,
        )
        p1, p2 = _patches(mod, query_snapshot=_make_query_snapshot(row))
        with p1, p2:
            result = mod.replay_parquet_snapshot(
                source_name="DNA",
                table_name="ACCT",
                business_date=date(2026, 1, 1),
                original_batch_id=12345,
                replay_batch_id=99999,
            )
        assert result.df.columns == ["z_col", "a_col", "m_col"]


# ---------------------------------------------------------------------------
# Public-surface invariants on ReplayResult
# ---------------------------------------------------------------------------


class TestReplayResultInvariants:

    def test_batch_id_is_original_not_replay(self, mod, tmp_path):
        """ReplayResult.batch_id is the ORIGINAL snapshot's BatchId."""
        df = pl.DataFrame({"id": [1]})
        file_path, sha = _write_parquet_fixture(tmp_path, df)
        row = _canonical_row(
            BatchId=55555,  # original snapshot
            NetworkDrivePath=str(file_path),
            ContentChecksum=sha,
            RowCount=1,
        )

        p1, p2 = _patches(mod, query_snapshot=_make_query_snapshot(row))
        with p1, p2:
            result = mod.replay_parquet_snapshot(
                source_name="DNA",
                table_name="ACCT",
                business_date=date(2026, 1, 1),
                original_batch_id=55555,
                replay_batch_id=88888,  # different from BatchId on the registry row
            )
        assert result.batch_id == 55555  # not 88888

    def test_source_file_is_path_object(self, mod, tmp_path):
        """ReplayResult.source_file is a Path, not a string."""
        df = pl.DataFrame({"id": [1]})
        file_path, sha = _write_parquet_fixture(tmp_path, df)
        row = _canonical_row(
            NetworkDrivePath=str(file_path), ContentChecksum=sha, RowCount=1,
        )

        p1, p2 = _patches(mod, query_snapshot=_make_query_snapshot(row))
        with p1, p2:
            result = mod.replay_parquet_snapshot(
                source_name="DNA",
                table_name="ACCT",
                business_date=date(2026, 1, 1),
                original_batch_id=12345,
                replay_batch_id=99999,
            )
        assert isinstance(result.source_file, Path)

    def test_sha256_is_lowercase_64_hex(self, mod, tmp_path):
        """ReplayResult.sha256_verified is lowercase 64-char hex (B-1 contract)."""
        df = pl.DataFrame({"id": [1]})
        file_path, sha = _write_parquet_fixture(tmp_path, df)
        row = _canonical_row(
            NetworkDrivePath=str(file_path), ContentChecksum=sha, RowCount=1,
        )

        p1, p2 = _patches(mod, query_snapshot=_make_query_snapshot(row))
        with p1, p2:
            result = mod.replay_parquet_snapshot(
                source_name="DNA",
                table_name="ACCT",
                business_date=date(2026, 1, 1),
                original_batch_id=12345,
                replay_batch_id=99999,
            )
        assert len(result.sha256_verified) == 64
        assert result.sha256_verified == result.sha256_verified.lower()
        # Verify it's hex
        int(result.sha256_verified, 16)


# ---------------------------------------------------------------------------
# Lazy getter discipline — sibling imports go through getters
# ---------------------------------------------------------------------------


class TestLazyGetterDiscipline:

    def test_get_query_snapshot_returns_callable(self, mod):
        """_get_query_snapshot returns a callable (deferred sibling import)."""
        fn = mod._get_query_snapshot()
        assert callable(fn)

    def test_get_ledger_step_returns_callable(self, mod):
        """_get_ledger_step returns a callable (deferred sibling import)."""
        fn = mod._get_ledger_step()
        assert callable(fn)
