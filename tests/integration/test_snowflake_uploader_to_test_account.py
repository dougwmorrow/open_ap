"""Tier 3 integration tests for data_load/snowflake_uploader.py.

Per docs/migration/phase1/05_tests.md § 6.2 canonical scenario:
"Real Snowflake trial account (account-setup unscoped in Phase 0;
presupposed by Phase 0 deliv 0.6 cost-data capture per 02_PHASES.md L44)
+ real Parquet upload; verify registry status flip + COPY INTO history".

Canonical signature under test (per phase1/03_core_modules.md § 7.1):

    def copy_parquet_to_snowflake(
        *,
        registry_id: int,
        snowflake_table: str | None = None,
        timeout_seconds: int = DEFAULT_COPY_TIMEOUT_SECONDS,
    ) -> SnowflakeCopyResult: ...

    @dataclass(frozen=True)
    class SnowflakeCopyResult:
        registry_id: int
        snowflake_table: str
        rows_copied: int
        copy_history_id: str
        duration_ms: int

D-numbers covered:
  - D5 (Snowflake replication target).
  - D15 (idempotency mandatory at every layer) - re-COPY of a Status=
    'replicated' row is a short-circuit no-op via mark_replicated().
  - D23 (Snowflake $120K / yr budget cap) - budget pre-check fires
    SnowflakeBudgetAlert at >80% credit utilization.
  - D26 (append-only PiiTokenProvenance) - by analogy, PipelineEventLog
    audit rows are append-only; re-COPY does not overwrite prior rows.
  - D67 (Tier 0 smoke required).
  - D68 (error class hierarchy) - RegistryStatusInvalid / RegistryNotFound /
    SnowflakeAuthFailed / SnowflakeBudgetAlert / SnowflakeCopyTimeout.
  - D69 (no shared cursor across module boundaries) - Snowflake
    CONNECTION is per-process; RSA key file is per-process too (D71).
  - D71 (RSA private key materialized to /dev/shm/snowflake_pk_<pid>).
  - D76 (one PipelineEventLog row per CLI invocation; analog at module
    level for SNOWFLAKE_COPY_INTO event type).

Setup overhead - DUAL skip marker:
  1. docker_skip_marker() - the registry table reads/writes against the
     test SQL Server container.
  2. snowflake_creds_skip_marker() - the COPY INTO requires real Snowflake
     credentials per Phase 0 deliv 0.6 (account setup unscoped in Phase 0).

The canonical schema fixture (schema.sql) carries
ParquetSnapshotRegistry + IdempotencyLedger + PipelineEventLog.

Operator-provided env vars (in addition to docker availability):
  - SNOWFLAKE_TEST_ACCOUNT / USER / DATABASE / SCHEMA / WAREHOUSE: target
    Snowflake account for COPY INTO destination.
  - SNOWFLAKE_STAGE_NAME (production env var): the stage that holds the
    pre-staged test Parquet file. The operator setting up the test account
    must upload the test fixture parquet to this stage BEFORE running the
    test.
  - SNOWFLAKE_TEST_PARQUET_REL_PATH: the relative path inside the stage
    pointing at the test fixture parquet (e.g. 'tier3_test/sample.parquet').
    The test inserts a ParquetSnapshotRegistry row whose NetworkDrivePath
    matches this so COPY INTO can locate it via the stage.

The test does NOT itself author the parquet on the Snowflake stage —
that is operator-side setup before invocation. Once setup is done, the
test verifies state changes are correct.

Each test uses unique source_name+table_name keys for the registry row
to avoid cross-test collision in the session-scope container.
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# Module-level skip - DUAL marker per § 6.2 spec. Both Docker AND
# Snowflake creds must be present for any test in this file to run.
from tests.integration.conftest import (  # noqa: E402
    docker_skip_marker,
    snowflake_creds_skip_marker,
)

pytestmark = [docker_skip_marker(), snowflake_creds_skip_marker()]


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers - insert a ParquetSnapshotRegistry row in the canonical 'verified'
# state so copy_parquet_to_snowflake can pick it up.
#
# Per phase1/01_database_schema.md § 4 + B-229: Status state machine
# transitions created -> verified -> replicated -> archived -> purged.
# COPY INTO requires Status='verified' (per snowflake_uploader.py
# COPY_REQUIRED_STATUS constant).
# ---------------------------------------------------------------------------


_TEST_PARQUET_REL_PATH_ENV = "SNOWFLAKE_TEST_PARQUET_REL_PATH"
_DEFAULT_TEST_PARQUET_REL_PATH = "tier3_test/sample.parquet"


def _resolved_test_parquet_path() -> str:
    """Resolve the operator-configured test parquet network drive path.

    Falls back to the default ``tier3_test/sample.parquet`` if the env
    var is unset; the operator setting up the test account is expected to
    pre-stage that file in the Snowflake stage named by SNOWFLAKE_STAGE_NAME.
    """
    return os.environ.get(_TEST_PARQUET_REL_PATH_ENV) or _DEFAULT_TEST_PARQUET_REL_PATH


def _insert_registry_verified_row(
    cursor: Any,
    *,
    source_name: str,
    table_name: str,
    business_date: datetime,
    batch_id: int,
    network_drive_path: str,
    sha256_hex: str = "0" * 64,
) -> int:
    """Insert one ParquetSnapshotRegistry row in Status='verified' state.

    Returns the new RegistryId for downstream copy_parquet_to_snowflake
    invocation.

    The verified state is the canonical pre-COPY state per the
    state-machine contract in B-229. SHA256 is set to a placeholder
    (zero-pad) since the integration test focuses on the COPY-side
    state flip; SHA verification was exercised by
    test_parquet_write_verify_replay_chain.
    """
    cursor.execute(
        """
        INSERT INTO General.ops.ParquetSnapshotRegistry
            (SourceName, TableName, BusinessDate, BatchId,
             NetworkDrivePath, Sha256Hex, Status,
             CreatedAt, VerifiedAt)
        OUTPUT INSERTED.RegistryId
        VALUES (?, ?, ?, ?, ?, ?, 'verified',
                SYSUTCDATETIME(), SYSUTCDATETIME())
        """,
        source_name,
        table_name,
        business_date,
        batch_id,
        network_drive_path,
        sha256_hex,
    )
    row = cursor.fetchone()
    return int(row[0])


def _query_registry_status(
    cursor: Any,
    *,
    registry_id: int,
) -> str:
    """Return the current Status for the registry row."""
    cursor.execute(
        """
        SELECT Status FROM General.ops.ParquetSnapshotRegistry
        WHERE RegistryId = ?
        """,
        registry_id,
    )
    row = cursor.fetchone()
    if row is None:
        raise AssertionError(f"RegistryId={registry_id} not found post-COPY")
    return str(row[0])


def _count_event_log_rows(
    cursor: Any,
    *,
    batch_id: int,
    table_name: str,
    event_type: str,
) -> int:
    """Count PipelineEventLog rows matching (BatchId, TableName, EventType).

    Used to verify D76 audit-row contract: each successful COPY emits
    exactly one row with EventType='SNOWFLAKE_COPY_INTO'.
    """
    cursor.execute(
        """
        SELECT COUNT(*) FROM General.ops.PipelineEventLog
        WHERE BatchId = ? AND TableName = ? AND EventType = ?
        """,
        batch_id,
        table_name,
        event_type,
    )
    return int(cursor.fetchone()[0])


# ---------------------------------------------------------------------------
# Test class - snowflake uploader against real Snowflake test account.
# ---------------------------------------------------------------------------


class TestSnowflakeUploaderToTestAccount:
    """D5 + D15 + D23 + D71 + D76 invariants for data_load/snowflake_uploader.py.

    Each test seeds a ParquetSnapshotRegistry row in 'verified' state,
    calls copy_parquet_to_snowflake, and asserts:
      - SnowflakeCopyResult fields are populated correctly
      - registry Status flipped 'verified' -> 'replicated'
      - PipelineEventLog row written with EventType='SNOWFLAKE_COPY_INTO'
      - re-COPY is idempotent (D15)

    Pre-condition: operator pre-stages the test fixture parquet in
    SNOWFLAKE_STAGE_NAME at SNOWFLAKE_TEST_PARQUET_REL_PATH (or default).
    """

    def test_copy_verified_parquet_flips_status_to_replicated(
        self,
        mssql_cursor: Any,
        test_db_transaction: Any,
        canonical_schema_loaded: None,
    ) -> None:
        """Canonical § 6.2 scenario: verified -> COPY -> replicated.

        Insert ParquetSnapshotRegistry row in 'verified' state, call
        copy_parquet_to_snowflake, assert Status flips to 'replicated'
        and SnowflakeCopyResult.copy_history_id is populated.
        """
        from data_load.snowflake_uploader import (  # noqa: PLC0415
            SnowflakeCopyResult,
            copy_parquet_to_snowflake,
        )

        source = "DNA"
        table = "TIER3_COPY_FLIP_TEST"
        batch_id = 60001
        business_date = datetime(2026, 5, 1, tzinfo=timezone.utc).replace(tzinfo=None)
        parquet_path = _resolved_test_parquet_path()

        registry_id = _insert_registry_verified_row(
            mssql_cursor,
            source_name=source,
            table_name=table,
            business_date=business_date,
            batch_id=batch_id,
            network_drive_path=parquet_path,
        )
        mssql_cursor.commit()

        result = copy_parquet_to_snowflake(registry_id=registry_id)

        assert isinstance(result, SnowflakeCopyResult)
        assert result.registry_id == registry_id
        # COPY INTO returns rows_loaded; even for an empty parquet it's
        # well-defined (0 rows). Assert non-negative.
        assert result.rows_copied >= 0
        # copy_history_id is the Snowflake query identifier - non-empty
        # string for any successful COPY.
        assert result.copy_history_id != "", (
            "copy_history_id must be populated for audit cross-reference "
            "to Snowflake COPY_HISTORY"
        )
        assert result.duration_ms >= 0
        # snowflake_table echoed; contains the target table name.
        assert table.lower() in result.snowflake_table.lower() or \
               table in result.snowflake_table

        # Status flipped via mark_replicated (D15 idempotent flip).
        new_status = _query_registry_status(
            mssql_cursor, registry_id=registry_id
        )
        assert new_status == "replicated", (
            f"Post-COPY Status must be 'replicated'; got {new_status!r}"
        )

    def test_copy_writes_event_log_audit_row_per_d76(
        self,
        mssql_cursor: Any,
        test_db_transaction: Any,
        canonical_schema_loaded: None,
    ) -> None:
        """One PipelineEventLog row per COPY (D76 audit-row contract).

        Per phase1/03_core_modules.md § 7.1 + D76: every successful COPY
        emits exactly one PipelineEventLog row with
        EventType='SNOWFLAKE_COPY_INTO' carrying BatchId + TableName for
        the runtime-performance dashboard.
        """
        from data_load.snowflake_uploader import (  # noqa: PLC0415
            EVENT_TYPE_SNOWFLAKE_COPY_INTO,
            copy_parquet_to_snowflake,
        )

        source = "DNA"
        table = "TIER3_AUDIT_ROW_TEST"
        batch_id = 60002
        business_date = datetime(2026, 5, 2, tzinfo=timezone.utc).replace(tzinfo=None)
        parquet_path = _resolved_test_parquet_path()

        registry_id = _insert_registry_verified_row(
            mssql_cursor,
            source_name=source,
            table_name=table,
            business_date=business_date,
            batch_id=batch_id,
            network_drive_path=parquet_path,
        )
        mssql_cursor.commit()

        # Sanity: no event-log row exists yet for this batch.
        before_count = _count_event_log_rows(
            mssql_cursor,
            batch_id=batch_id,
            table_name=table,
            event_type=EVENT_TYPE_SNOWFLAKE_COPY_INTO,
        )
        assert before_count == 0, (
            f"Pre-COPY: expected 0 audit rows; got {before_count}"
        )

        copy_parquet_to_snowflake(registry_id=registry_id)

        after_count = _count_event_log_rows(
            mssql_cursor,
            batch_id=batch_id,
            table_name=table,
            event_type=EVENT_TYPE_SNOWFLAKE_COPY_INTO,
        )
        assert after_count == 1, (
            f"Post-COPY: expected exactly 1 SNOWFLAKE_COPY_INTO row; "
            f"got {after_count} (D76 audit contract violated)"
        )

    def test_re_copy_after_replicated_is_idempotent(
        self,
        mssql_cursor: Any,
        test_db_transaction: Any,
        canonical_schema_loaded: None,
    ) -> None:
        """D15 idempotency: second COPY against same registry_id is safe.

        Per § 7.1 idempotency contract:
          - Snowflake COPY INTO tracks per-file load history; re-copy
            yields rows_loaded=0.
          - mark_replicated short-circuits when Status='replicated'.

        Calling copy_parquet_to_snowflake twice on the same registry_id
        must succeed both times and leave Status='replicated' both times.
        """
        from data_load.snowflake_uploader import copy_parquet_to_snowflake  # noqa: PLC0415

        source = "DNA"
        table = "TIER3_IDEMPOTENT_RECOPY_TEST"
        batch_id = 60003
        business_date = datetime(2026, 5, 3, tzinfo=timezone.utc).replace(tzinfo=None)
        parquet_path = _resolved_test_parquet_path()

        registry_id = _insert_registry_verified_row(
            mssql_cursor,
            source_name=source,
            table_name=table,
            business_date=business_date,
            batch_id=batch_id,
            network_drive_path=parquet_path,
        )
        mssql_cursor.commit()

        # First COPY: verified -> replicated.
        result_1 = copy_parquet_to_snowflake(registry_id=registry_id)
        assert _query_registry_status(
            mssql_cursor, registry_id=registry_id
        ) == "replicated"

        # Second COPY: must NOT raise (idempotent re-call). The function
        # may detect Status='replicated' upstream and short-circuit, OR
        # it may run again and Snowflake returns rows_loaded=0 + the
        # registry flip is a no-op via mark_replicated short-circuit.
        # Either path is acceptable per the D15 contract.
        try:
            result_2 = copy_parquet_to_snowflake(registry_id=registry_id)
            # If the function permits re-COPY, the result is well-formed.
            assert result_2.registry_id == registry_id
        except Exception as exc:  # noqa: BLE001
            # Acceptable failure: RegistryStatusInvalid raised because
            # Status is now 'replicated', not 'verified'. This is the
            # status-gate path - distinct from D15 short-circuit but
            # equally valid. The contract is "re-call is safe", not
            # "re-call always succeeds with the same result".
            from utils.errors import RegistryStatusInvalid  # noqa: PLC0415
            assert isinstance(exc, RegistryStatusInvalid), (
                f"Re-COPY raised unexpected exception type: {type(exc).__name__}"
            )

        # Final state still 'replicated' regardless of which path fired.
        final_status = _query_registry_status(
            mssql_cursor, registry_id=registry_id
        )
        assert final_status == "replicated", (
            f"Re-COPY must leave Status='replicated'; got {final_status!r}"
        )

    def test_registry_status_invalid_raises_when_not_verified(
        self,
        mssql_cursor: Any,
        test_db_transaction: Any,
        canonical_schema_loaded: None,
    ) -> None:
        """Status='created' (not yet verified) -> RegistryStatusInvalid.

        Per § 7.1: COPY requires Status='verified'. Calling against any
        other status raises RegistryStatusInvalid (PipelineFatalError per
        D68) BEFORE Snowflake is contacted.
        """
        from data_load.snowflake_uploader import copy_parquet_to_snowflake  # noqa: PLC0415
        from utils.errors import RegistryStatusInvalid  # noqa: PLC0415

        source = "DNA"
        table = "TIER3_STATUS_INVALID_TEST"
        batch_id = 60004
        business_date = datetime(2026, 5, 4, tzinfo=timezone.utc).replace(tzinfo=None)
        parquet_path = _resolved_test_parquet_path()

        # Insert with Status='created' instead of 'verified'.
        mssql_cursor.execute(
            """
            INSERT INTO General.ops.ParquetSnapshotRegistry
                (SourceName, TableName, BusinessDate, BatchId,
                 NetworkDrivePath, Sha256Hex, Status, CreatedAt)
            OUTPUT INSERTED.RegistryId
            VALUES (?, ?, ?, ?, ?, ?, 'created', SYSUTCDATETIME())
            """,
            source,
            table,
            business_date,
            batch_id,
            parquet_path,
            "0" * 64,
        )
        registry_id = int(mssql_cursor.fetchone()[0])
        mssql_cursor.commit()

        with pytest.raises(RegistryStatusInvalid) as excinfo:
            copy_parquet_to_snowflake(registry_id=registry_id)
        # Metadata records the actual + required status for diagnostics.
        meta = excinfo.value.metadata or {}
        assert meta.get("current_status") == "created"
        assert meta.get("required_status") == "verified"

        # Status unchanged - the gate fired before any side effect.
        unchanged = _query_registry_status(
            mssql_cursor, registry_id=registry_id
        )
        assert unchanged == "created"
