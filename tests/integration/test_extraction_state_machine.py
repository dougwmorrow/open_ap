"""Tier 3 integration tests for cdc/extraction_state.py state machine.

Per docs/migration/phase1/05_tests.md section 6.2 canonical scenario:
"Per-day extraction state lifecycle (IN_PROGRESS -> SUCCESS / FAILED ->
re-extraction)".

Canonical signatures under test (per phase1/03_core_modules.md section 4.2):

  - ``record_extraction_attempt(*, source_name, table_name, business_date,
    batch_id, status, rows_extracted=None, failure_reason=None,
    extraction_attempt=None) -> int``
  - ``get_extraction_attempt(*, source_name, table_name, business_date) -> int``
  - ``is_date_trusted(*, source_name, table_name, business_date) -> bool``
  - ``most_recent_success(*, source_name, table_name) -> ExtractionState``
  - ``is_reextraction(*, source_name, table_name, business_date) -> bool``

D-numbers covered:
  - D11 (empirical L_99 lookback) - the orchestrator composes
    ``most_recent_success`` with UdmTablesList.LookbackDays.
  - D13 (trust gate) - ``is_date_trusted`` gates delete inference.
  - D14 (re-extraction tracking) - ``IsReExtraction`` BIT flag +
    ``ExtractionAttempt`` counter; monotone within a single
    (source, table, date) key.
  - D15 (idempotency) - re-record with same key UPDATEs vs duplicates.
  - D68 (error class hierarchy) - InvalidTrustGate for future-date /
    pre-FirstLoadDate / invalid-status arguments.

B-115 scaffold caveat: module-level skip; same as siblings.
"""
from __future__ import annotations

import logging
import sys
from datetime import date, datetime, timedelta, timezone
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
# Test class - extraction state machine under real DB.
#
# Each test consumes:
#   - mssql_cursor: for direct General.ops.PipelineExtraction inspection
#   - test_db_transaction: BEGIN/ROLLBACK isolation
#   - canonical_schema_loaded: ensures the table + UX_PipelineExtraction_Identity
# ---------------------------------------------------------------------------


class TestExtractionStateMachine:
    """D13 / D14 state-machine invariants for cdc/extraction_state.py.

    The canonical lifecycle per § 4.2:

        IN_PROGRESS -> SUCCESS   (clean completion; attempt 1)
        IN_PROGRESS -> FAILED    (transient failure; retry path)
        (retry)     -> IN_PROGRESS -> SUCCESS  (attempt 2; IsReExtraction=1)

    The UNIQUE index UX_PipelineExtraction_Identity on (SourceName, TableName,
    DateValue, ExtractionAttempt) ensures idempotent re-calls UPDATE the
    existing row rather than duplicate-insert.
    """

    def test_record_attempt_then_query_returns_attempt(
        self,
        mssql_cursor: Any,
        test_db_transaction: Any,
        canonical_schema_loaded: None,
    ) -> None:
        """record_extraction_attempt then get_extraction_attempt
        returns the recorded row's next attempt number.

        Round-trip the writer + reader: record an attempt, then call
        ``get_extraction_attempt`` to confirm the recorded row is
        discoverable via the canonical (source, table, date) key and
        the next-attempt counter is correctly incremented.

        Per § 4.2: ``get_extraction_attempt`` returns
        ``1 + MAX(ExtractionAttempt)`` over prior rows. After one
        recorded attempt, the next-attempt number is 2.
        """
        from cdc.extraction_state import (  # noqa: PLC0415
            get_extraction_attempt,
            record_extraction_attempt,
        )

        # Step 1: record a clean SUCCESS attempt.
        business_date = date(2026, 1, 15)
        extraction_id = record_extraction_attempt(
            source_name="DNA",
            table_name="STATE_MACHINE_TEST",
            business_date=business_date,
            batch_id=10001,
            status="SUCCESS",
            rows_extracted=42,
        )
        assert isinstance(extraction_id, int) and extraction_id > 0, (
            f"ExtractionId must be a positive integer; got {extraction_id!r}"
        )

        # Step 2: query for the next attempt number; must be 2 (one prior).
        next_attempt = get_extraction_attempt(
            source_name="DNA",
            table_name="STATE_MACHINE_TEST",
            business_date=business_date,
        )
        assert next_attempt == 2, (
            f"After one recorded attempt, next-attempt must be 2; "
            f"got {next_attempt}"
        )

        # Step 3: verify the row in the canonical table.
        mssql_cursor.execute(
            """
            SELECT ExtractionAttempt, Status, RowsExtracted, IsReExtraction
            FROM General.ops.PipelineExtraction
            WHERE ExtractionId = ?
            """,
            extraction_id,
        )
        row = mssql_cursor.fetchone()
        assert row is not None, f"Row missing for ExtractionId={extraction_id}"
        assert row[0] == 1, f"Expected ExtractionAttempt=1; got {row[0]}"
        assert row[1] == "SUCCESS", f"Expected Status='SUCCESS'; got {row[1]!r}"
        assert row[2] == 42, f"Expected RowsExtracted=42; got {row[2]}"
        # IsReExtraction is 0 for the first attempt per D14.
        assert row[3] == 0, f"First attempt must have IsReExtraction=0; got {row[3]}"

    def test_two_attempts_same_day_second_is_reextraction(
        self,
        mssql_cursor: Any,
        test_db_transaction: Any,
        canonical_schema_loaded: None,
    ) -> None:
        """First attempt FAILED + second attempt; second is_reextraction
        returns True; second row has IsReExtraction=1.

        D14 contract: every retry increments ExtractionAttempt and sets
        IsReExtraction=1 so the audit trail distinguishes clean first
        passes from recovery loops.

        ``is_reextraction(...)`` returns True iff at least one prior row
        exists for the key (regardless of status - FAILED rows count as
        prior attempts).
        """
        from cdc.extraction_state import (  # noqa: PLC0415
            is_reextraction,
            record_extraction_attempt,
        )

        business_date = date(2026, 1, 16)
        key = dict(
            source_name="DNA",
            table_name="REEXTRACTION_TEST",
            business_date=business_date,
        )

        # Step 1: first attempt FAILED. is_reextraction must be False
        # BEFORE the first record (no prior row yet).
        assert is_reextraction(**key) is False, (
            "Empty key must report is_reextraction=False"
        )
        first_id = record_extraction_attempt(
            **key,
            batch_id=10002,
            status="FAILED",
            failure_reason="synthetic transient connection error",
        )

        # Step 2: is_reextraction now True (one prior FAILED row counts
        # per D14).
        assert is_reextraction(**key) is True, (
            "After one prior attempt, is_reextraction MUST be True "
            "regardless of prior status"
        )

        # Step 3: second attempt SUCCESS; must auto-assign
        # ExtractionAttempt=2 and IsReExtraction=1.
        second_id = record_extraction_attempt(
            **key,
            batch_id=10003,
            status="SUCCESS",
            rows_extracted=100,
        )
        assert second_id != first_id, (
            "Second attempt must be a distinct row"
        )

        # Verify row state in the canonical table.
        mssql_cursor.execute(
            """
            SELECT ExtractionAttempt, IsReExtraction, Status
            FROM General.ops.PipelineExtraction
            WHERE ExtractionId = ?
            """,
            second_id,
        )
        row = mssql_cursor.fetchone()
        assert row is not None
        assert row[0] == 2, f"Expected ExtractionAttempt=2; got {row[0]}"
        assert row[1] == 1, (
            f"Second attempt MUST have IsReExtraction=1 per D14; got {row[1]}"
        )
        assert row[2] == "SUCCESS"

    def test_trust_gate_blocks_future_dates(
        self,
        mssql_cursor: Any,
        test_db_transaction: Any,
        canonical_schema_loaded: None,
    ) -> None:
        """is_date_trusted raises InvalidTrustGate for a future date.

        Per § 4.2 date-validation contract: "Future dates -
        business_date > today (UTC) - raise InvalidTrustGate. There is
        no defensible interpretation of 'did extraction succeed for
        tomorrow?'; this is always a caller bug."

        Verifies the InvalidTrustGate raise + metadata carry-through
        per D68.
        """
        from cdc.extraction_state import is_date_trusted  # noqa: PLC0415
        from utils.errors import InvalidTrustGate  # noqa: PLC0415

        # Today UTC + 30 days is unambiguously in the future regardless
        # of timezone drift between client + container.
        today_utc = datetime.now(timezone.utc).date()
        future_date = today_utc + timedelta(days=30)

        with pytest.raises(InvalidTrustGate) as exc_info:
            is_date_trusted(
                source_name="DNA",
                table_name="TRUST_GATE_TEST",
                business_date=future_date,
            )

        # Per D68: metadata kwarg carries per-raise context for
        # PipelineEventLog forwarding.
        meta = exc_info.value.metadata
        assert meta is not None
        assert meta.get("business_date") == future_date.isoformat()
        assert meta.get("today_utc") == today_utc.isoformat()

    def test_most_recent_success_walks_history(
        self,
        mssql_cursor: Any,
        test_db_transaction: Any,
        canonical_schema_loaded: None,
    ) -> None:
        """most_recent_success returns the latest SUCCESS for the key.

        Per § 4.2: ``most_recent_success`` is the lookback-base helper -
        the orchestration layer composes this with ``LookbackDays`` to
        compute the rolling extraction window's starting boundary.

        Setup: record three attempts with mixed Status across three
        dates. Assert ``most_recent_success`` returns the LATEST
        SUCCESS row (not the most recent attempt overall, which may be
        FAILED).
        """
        from cdc.extraction_state import (  # noqa: PLC0415
            ExtractionState,
            most_recent_success,
            record_extraction_attempt,
        )

        common = dict(
            source_name="DNA",
            table_name="MOST_RECENT_SUCCESS_TEST",
        )

        # Three dates: oldest SUCCESS / middle SUCCESS / newest FAILED.
        # most_recent_success must return the MIDDLE date because it is
        # the latest SUCCESS.
        d1 = date(2026, 1, 10)
        d2 = date(2026, 1, 11)
        d3 = date(2026, 1, 12)

        record_extraction_attempt(
            **common,
            business_date=d1,
            batch_id=10101,
            status="SUCCESS",
            rows_extracted=10,
        )
        record_extraction_attempt(
            **common,
            business_date=d2,
            batch_id=10102,
            status="SUCCESS",
            rows_extracted=20,
        )
        record_extraction_attempt(
            **common,
            business_date=d3,
            batch_id=10103,
            status="FAILED",
            failure_reason="synthetic later-failure",
        )

        result = most_recent_success(**common)
        assert isinstance(result, ExtractionState), (
            f"most_recent_success must return ExtractionState; got {type(result)}"
        )
        # Most-recent-SUCCESS is d2, NOT d3 (d3 is FAILED).
        assert result.business_date == d2, (
            f"Expected business_date={d2}; got {result.business_date}"
        )
        assert result.status == "SUCCESS"
        assert result.extraction_attempt == 1, (
            "Each date had one attempt; expected ExtractionAttempt=1"
        )
