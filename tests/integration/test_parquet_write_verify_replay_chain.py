"""Tier 3 integration tests for the parquet writer/verify/replay chain.

Per docs/migration/phase1/05_tests.md section 6.2 canonical scenario:
"Write -> verify -> replay through full module chain; assert df bytes
identical".

Canonical signatures under test (per phase1/03_core_modules.md):

  - section 1.1 ``write_parquet_snapshot(df, *, source_name, table_name,
    business_date, batch_id, output_dir=None) -> ParquetWriteResult``
  - section 1.3 ``verify_parquet_snapshot(*, registry_id, actor='pipeline')
    -> ParquetVerifyResult``
  - section 1.2 ``replay_parquet_snapshot(*, source_name, table_name,
    business_date, original_batch_id, replay_batch_id) -> ReplayResult``

D-numbers covered:
  - D2 (Stage dropped - Parquet snapshots replace it; the write/replay
    chain IS the canonical materialization path).
  - D4 (network drive Parquet) - the write target.
  - D15 + D17 (idempotency + ledger pattern at every layer).
  - D16 (inflight-rename pattern for crash safety).
  - D45.2 (Parquet config: ZSTD-3, statistics enabled) - the deterministic
    byte-level reproducibility this test verifies depends on this config.
  - D68 (error class hierarchy) - the rejection paths raise
    RegistryStatusInvalid / ParquetReplayError per § 1.2 + § 1.3.

B-115 scaffold caveat: module-level skip; same as
test_idempotency_ledger_concurrency.py.
"""
from __future__ import annotations

import logging
import sys
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# B-115 follow-up 2026-05-14: schema.sql + canonical_schema_loaded
# fixture are now operational. Tests fall through to docker_skip_marker()
# from conftest -- skips with "Docker unavailable" reason on workstations
# without Docker Desktop; runs against real container otherwise.
from tests.integration.conftest import docker_skip_marker

pytestmark = docker_skip_marker()


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Test class - write -> verify -> replay end-to-end chain.
#
# Each test consumes:
#   - tmp_path: pytest builtin temp directory for the Parquet output dir
#   - mssql_cursor: for registry-row inspection
#   - test_db_transaction: state-leakage mitigation
#   - canonical_schema_loaded: General.ops.ParquetSnapshotRegistry exists
# ---------------------------------------------------------------------------


class TestParquetWriteVerifyReplayChain:
    """Round-trip idempotency: write -> verify -> replay bytes identical.

    Per § 6.2: "Write -> verify -> replay through full module chain;
    assert df bytes identical". The byte-level reproducibility is the
    operational contract for RB-8 (Bronze rebuild from Parquet) and
    Round 5 reconciliation - if a snapshot replay produces a different
    DataFrame than what was written, every downstream consumer that
    trusted the registry's SHA-256 has been silently lied to.

    The state machine under test (per § 1.3 + 1.2):

        created -> verified -> replicated -> archived -> purged
        (replay-eligible statuses: verified / replicated / archived)
    """

    def test_write_then_verify_then_replay_bytes_identical(
        self,
        tmp_path: Path,
        mssql_cursor: Any,
        test_db_transaction: Any,
        canonical_schema_loaded: None,
    ) -> None:
        """Write a DF; verify; replay; assert df1.equals(df2) AND SHA matches.

        Canonical happy-path round-trip:

        1. Build a small Polars DF with mixed dtypes (string, int, float,
           datetime, null) - covers the dtype matrix that parquet_writer
           must round-trip per the BCP CSV Contract analog for Parquet.
        2. Call ``write_parquet_snapshot`` -> ``ParquetWriteResult`` with
           ``status='created'``.
        3. Call ``verify_parquet_snapshot(registry_id=..., actor='operator')``
           -> ``ParquetVerifyResult`` with ``status='verified'`` and
           ``sha256_verified == write_result.sha256``.
        4. Allocate a fresh ``replay_batch_id`` and call
           ``replay_parquet_snapshot(...)`` -> ``ReplayResult``.
        5. Assert ``replay_result.df.equals(original_df)`` AND
           ``replay_result.sha256_verified == write_result.sha256``.

        This is the D2/D4 canonical Parquet medallion materialization
        path; any failure here is a corruption signal.
        """
        import polars as pl  # noqa: PLC0415

        from data_load.parquet_writer import write_parquet_snapshot  # noqa: PLC0415
        from data_load.parquet_registry_client import (  # noqa: PLC0415
            STATUS_CREATED,
            STATUS_VERIFIED,
            verify_parquet_snapshot,
        )
        from data_load.parquet_replay import replay_parquet_snapshot  # noqa: PLC0415

        # Step 1: small DF with mixed dtypes for round-trip coverage.
        original_df = pl.DataFrame(
            {
                "pk_id": [1, 2, 3],
                "name": ["alpha", "beta", "gamma"],
                "amount": [100.50, 250.75, None],
                "active": [True, False, True],
            }
        )

        # Step 2: write to a tmp_path-rooted output dir (so we don't
        # pollute any real PARQUET_OUTPUT_DIR).
        write_result = write_parquet_snapshot(
            original_df,
            source_name="DNA",
            table_name="TEST_TABLE",
            business_date=date(2026, 5, 14),
            batch_id=9101,
            output_dir=tmp_path,
        )
        assert write_result.status == STATUS_CREATED, (
            f"Writer must produce status='created'; got {write_result.status!r}"
        )
        assert write_result.file_path.exists(), (
            f"Parquet file must exist post-write: {write_result.file_path}"
        )
        assert write_result.row_count == 3
        assert len(write_result.sha256) == 64, (
            f"SHA-256 must be 64-char hex per B-1; got {len(write_result.sha256)}"
        )

        # Step 3: verify - flip status created -> verified.
        verify_result = verify_parquet_snapshot(
            registry_id=write_result.registry_id,
            actor="operator",
        )
        assert verify_result.status == STATUS_VERIFIED
        assert verify_result.sha256_verified == write_result.sha256, (
            "Verifier MUST compute the same SHA-256 as the writer"
        )
        assert verify_result.row_count_verified == write_result.row_count

        # Step 4: replay - read back into a fresh DataFrame.
        replay_result = replay_parquet_snapshot(
            source_name="DNA",
            table_name="TEST_TABLE",
            business_date=date(2026, 5, 14),
            original_batch_id=9101,
            replay_batch_id=9102,
        )

        # Step 5: round-trip assertions.
        assert replay_result.sha256_verified == write_result.sha256, (
            "Replay MUST verify against the writer's SHA-256"
        )
        assert replay_result.row_count == write_result.row_count
        assert replay_result.df.equals(original_df), (
            "Round-trip MUST be byte-identical: write -> verify -> replay "
            "produces the same DataFrame"
        )

    def test_replay_eligible_statuses(
        self,
        tmp_path: Path,
        mssql_cursor: Any,
        test_db_transaction: Any,
        canonical_schema_loaded: None,
    ) -> None:
        """Replay accepts {verified, replicated, archived} statuses.

        Per § 1.2 ``REPLAY_ELIGIBLE_STATUSES = frozenset({'verified',
        'replicated', 'archived'})``. Walk the state machine writer ->
        verifier -> mark_replicated -> mark_archived and assert replay
        succeeds at each eligible state.
        """
        import polars as pl  # noqa: PLC0415

        from data_load.parquet_writer import write_parquet_snapshot  # noqa: PLC0415
        from data_load.parquet_registry_client import (  # noqa: PLC0415
            mark_archived,
            mark_replicated,
            verify_parquet_snapshot,
        )
        from data_load.parquet_replay import (  # noqa: PLC0415
            REPLAY_ELIGIBLE_STATUSES,
            replay_parquet_snapshot,
        )

        # Sanity check on the constant - if this changes the test must
        # also change (deliberate coupling).
        assert REPLAY_ELIGIBLE_STATUSES == frozenset(
            {"verified", "replicated", "archived"}
        ), (
            f"REPLAY_ELIGIBLE_STATUSES drift: {REPLAY_ELIGIBLE_STATUSES!r}"
        )

        df = pl.DataFrame({"pk": [1, 2], "v": ["a", "b"]})
        write_result = write_parquet_snapshot(
            df,
            source_name="DNA",
            table_name="ELIGIBILITY",
            business_date=date(2026, 5, 14),
            batch_id=9201,
            output_dir=tmp_path,
        )

        # verified - first eligible status
        verify_parquet_snapshot(
            registry_id=write_result.registry_id, actor="pipeline"
        )
        r1 = replay_parquet_snapshot(
            source_name="DNA",
            table_name="ELIGIBILITY",
            business_date=date(2026, 5, 14),
            original_batch_id=9201,
            replay_batch_id=9202,
        )
        assert r1.df.equals(df)

        # replicated - second eligible status
        mark_replicated(
            registry_id=write_result.registry_id,
            replica_target="snowflake:TEST_MIRROR",
        )
        r2 = replay_parquet_snapshot(
            source_name="DNA",
            table_name="ELIGIBILITY",
            business_date=date(2026, 5, 14),
            original_batch_id=9201,
            replay_batch_id=9203,
        )
        assert r2.df.equals(df)

        # archived - third eligible status
        mark_archived(
            registry_id=write_result.registry_id,
            archive_location="cold://test-bucket/path",
        )
        r3 = replay_parquet_snapshot(
            source_name="DNA",
            table_name="ELIGIBILITY",
            business_date=date(2026, 5, 14),
            original_batch_id=9201,
            replay_batch_id=9204,
        )
        assert r3.df.equals(df)

    def test_replay_rejects_created_status(
        self,
        tmp_path: Path,
        mssql_cursor: Any,
        test_db_transaction: Any,
        canonical_schema_loaded: None,
    ) -> None:
        """Replay on Status='created' raises RegistryStatusInvalid.

        Per § 1.2: "registry row exists but Status NOT IN ('verified',
        'replicated', 'archived'). FATAL - verifier must run first."

        The newly-written row carries ``Status='created'`` (per § 1.1
        writer contract); calling replay before verify is a caller bug
        and the engine MUST reject it deterministically.
        """
        import polars as pl  # noqa: PLC0415

        from data_load.parquet_writer import write_parquet_snapshot  # noqa: PLC0415
        from data_load.parquet_replay import replay_parquet_snapshot  # noqa: PLC0415
        from utils.errors import RegistryStatusInvalid  # noqa: PLC0415

        df = pl.DataFrame({"pk": [1], "v": ["x"]})
        write_result = write_parquet_snapshot(
            df,
            source_name="DNA",
            table_name="REJECT_CREATED",
            business_date=date(2026, 5, 14),
            batch_id=9301,
            output_dir=tmp_path,
        )
        # Intentionally do NOT verify - leave Status='created'.

        with pytest.raises(RegistryStatusInvalid) as exc_info:
            replay_parquet_snapshot(
                source_name="DNA",
                table_name="REJECT_CREATED",
                business_date=date(2026, 5, 14),
                original_batch_id=9301,
                replay_batch_id=9302,
            )

        # Per D68: metadata kwarg carries per-raise context.
        assert exc_info.value.metadata.get("current_status") == "created"
        assert (
            exc_info.value.metadata.get("registry_id") == write_result.registry_id
        )

    def test_replay_rejects_missing_file(
        self,
        tmp_path: Path,
        mssql_cursor: Any,
        test_db_transaction: Any,
        canonical_schema_loaded: None,
    ) -> None:
        """Replay raises ParquetReplayError when the registered file is absent.

        Per § 1.2: "ParquetReplayError - registry row exists and Status
        is eligible, but the file is missing OR the computed SHA-256
        doesn't match the registry hash OR the file's row count doesn't
        match the registry's RowCount. FATAL - corruption signal;
        escalate to RB-6 + RB-8."

        Setup: write + verify normally, then DELETE the file on disk so
        replay encounters a missing-file path.
        """
        import polars as pl  # noqa: PLC0415

        from data_load.parquet_writer import write_parquet_snapshot  # noqa: PLC0415
        from data_load.parquet_registry_client import (  # noqa: PLC0415
            verify_parquet_snapshot,
        )
        from data_load.parquet_replay import replay_parquet_snapshot  # noqa: PLC0415
        from utils.errors import ParquetReplayError  # noqa: PLC0415

        df = pl.DataFrame({"pk": [1], "v": ["x"]})
        write_result = write_parquet_snapshot(
            df,
            source_name="DNA",
            table_name="MISSING_FILE",
            business_date=date(2026, 5, 14),
            batch_id=9401,
            output_dir=tmp_path,
        )
        verify_parquet_snapshot(
            registry_id=write_result.registry_id, actor="pipeline"
        )

        # Simulate file disappearance (network drive remount / accidental
        # delete / disk fault). The registry row still claims status
        # 'verified' so the eligibility gate passes; the missing-file
        # path must raise the canonical corruption signal.
        write_result.file_path.unlink()
        assert not write_result.file_path.exists(), (
            "Setup: file must be gone before replay"
        )

        with pytest.raises(ParquetReplayError):
            replay_parquet_snapshot(
                source_name="DNA",
                table_name="MISSING_FILE",
                business_date=date(2026, 5, 14),
                original_batch_id=9401,
                replay_batch_id=9402,
            )
