"""Tier 3 integration tests for tools/gap_detector.py against synthetic gaps.

Per docs/migration/phase1/05_tests.md § 6.2 canonical scenario:
"Inject gap into PipelineExtraction; verify GapReport correctly
identifies it".

Canonical signature under test (per phase1/03_core_modules.md § 5.3):

    def detect_extraction_gaps(
        *,
        source_filter: str | None = None,
        as_of_date: date | None = None,
    ) -> list[GapReport]: ...

    @dataclass(frozen=True)
    class GapReport:
        source_name: str
        table_name: str
        expected_range: tuple[date, date]
        missing_dates: list[date]
        recommended_action: str

D-numbers covered:
  - D11 (empirical L_99 lookback) - the expected range honors
    UdmTablesList.LookbackDays which derives from L_99.
  - D22 (hourly gap detector Automic job) - canonical caller; this
    module IS the engine half driving the JOB_GAP_DETECT Automic job.
  - D67 (Tier 0 smoke required).
  - D68 (error class hierarchy) - GapDetectorTimeout +
    ExtractionStateUnavailable carry metadata kwargs.
  - D76 (audit-row contract) - one GAP_DETECT row per invocation
    regardless of whether gaps were found.

Recommended-action enum per § 5.3:
  - ACTION_BACKFILL = "backfill"
  - ACTION_INVESTIGATE = "investigate-source"
  - ACTION_NO_ACTION = "within-lookback-no-action" (sentinel; never
    returned in the list - clean tables are OMITTED).

Setup overhead per test: gap_detector reads UdmTablesList for large
tables. The canonical schema fixture (schema.sql) does NOT include
UdmTablesList (deferred per the fixture's header comment). Each test
creates a minimal UdmTablesList table inline (CREATE TABLE inside the
test_db_transaction-rolled-back block) so the test is self-contained
without modifying the session-scope schema.

Module-level skip pattern per scaffold pattern.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# Module-level skip via the canonical conftest helper.
from tests.integration.conftest import docker_skip_marker  # noqa: E402

pytestmark = docker_skip_marker()


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers - create / populate minimal UdmTablesList for the test scope.
#
# Per the schema.sql header comment, UdmTablesList is DEFERRED to a
# follow-up B-N. These tests create it inline using a minimal DDL that
# only carries the columns gap_detector reads:
#   SourceName, SourceObjectName, FirstLoadDate, LookbackDays,
#   SourceAggregateColumnName
#
# Inside test_db_transaction, the table creation rolls back at test
# exit so the session-scope schema is unaffected.
# ---------------------------------------------------------------------------


def _ensure_udmtableslist_minimal(cursor: Any) -> None:
    """Create dbo.UdmTablesList if absent, with the columns gap_detector reads.

    The full UdmTablesList has ~40 columns. gap_detector only needs:
    SourceName, SourceObjectName, FirstLoadDate, LookbackDays,
    SourceAggregateColumnName. Create the minimal subset; the rollback
    at test exit will drop the table.

    Idempotent: a re-run inside the same test transaction is a no-op
    (the OBJECT_ID guard short-circuits). Tests within the same session
    share the table after the first test's rollback discards it - so
    each test re-creates it.
    """
    cursor.execute(
        """
        IF OBJECT_ID('General.dbo.UdmTablesList') IS NULL
        BEGIN
            CREATE TABLE General.dbo.UdmTablesList (
                SourceName                  NVARCHAR(50)  NOT NULL,
                SourceObjectName            NVARCHAR(255) NOT NULL,
                SourceAggregateColumnName   NVARCHAR(255) NULL,
                FirstLoadDate               DATE          NULL,
                LookbackDays                INT           NULL,
                CONSTRAINT PK_UdmTablesList_Tier3 PRIMARY KEY
                    (SourceName, SourceObjectName)
            );
        END
        """
    )


def _insert_table_config(
    cursor: Any,
    *,
    source_name: str,
    table_name: str,
    first_load_date: date,
    lookback_days: int,
    aggregate_column: str = "DATEVAL",
) -> None:
    """Insert one UdmTablesList row for the test's table.

    aggregate_column defaults to a non-NULL value so the row qualifies
    as a "large table" per § 5.3 (SourceAggregateColumnName IS NOT NULL).
    """
    cursor.execute(
        """
        INSERT INTO General.dbo.UdmTablesList
            (SourceName, SourceObjectName, SourceAggregateColumnName,
             FirstLoadDate, LookbackDays)
        VALUES (?, ?, ?, ?, ?)
        """,
        source_name,
        table_name,
        aggregate_column,
        first_load_date,
        lookback_days,
    )


def _insert_extraction_success(
    cursor: Any,
    *,
    batch_id: int,
    source_name: str,
    table_name: str,
    business_date: date,
) -> None:
    """Insert one SUCCESS PipelineExtraction row for the given date.

    Mirrors the production INSERT shape: Status='SUCCESS', RowsExtracted
    populated, completed_at within seconds of started_at.
    """
    cursor.execute(
        """
        INSERT INTO General.ops.PipelineExtraction
            (BatchId, SourceName, TableName, DateValue, Status,
             StartedAt, CompletedAt, RowsExtracted, ExtractionAttempt)
        VALUES (?, ?, ?, ?, 'SUCCESS',
                SYSUTCDATETIME(), SYSUTCDATETIME(), ?, 1)
        """,
        batch_id,
        source_name,
        table_name,
        business_date,
        100,
    )


# ---------------------------------------------------------------------------
# Test class - gap detector against synthetic UdmTablesList + PipelineExtraction.
# ---------------------------------------------------------------------------


class TestGapDetectorSyntheticGaps:
    """D22 gap-detection invariants for tools/gap_detector.py.

    Each test seeds UdmTablesList + PipelineExtraction inside the
    test_db_transaction-rolled-back block, calls detect_extraction_gaps,
    and asserts the returned list of GapReport matches the synthetic
    setup. The rollback at test exit discards all seeded rows so tests
    are isolated.

    The as_of_date parameter is critical: every test passes an explicit
    as_of_date so the expected-range computation is deterministic across
    calendar drift (especially around month boundaries).
    """

    def test_detect_no_gaps_when_continuous_extraction(
        self,
        mssql_cursor: Any,
        test_db_transaction: Any,
        canonical_schema_loaded: None,
    ) -> None:
        """10 days SUCCESS extraction -> empty GapReport list.

        Per § 5.3: tables with no missing dates in the expected range
        are OMITTED from the returned list entirely. A continuous
        10-day SUCCESS history produces no GapReport.
        """
        from tools.gap_detector import detect_extraction_gaps  # noqa: PLC0415

        _ensure_udmtableslist_minimal(mssql_cursor)

        # Configure: table starts 2026-01-01, LookbackDays=3, so the
        # expected range for as_of_date=2026-01-14 is [2026-01-01, 2026-01-11].
        first_load = date(2026, 1, 1)
        lookback = 3
        as_of = date(2026, 1, 14)
        _insert_table_config(
            mssql_cursor,
            source_name="DNA",
            table_name="CONTINUOUS_TEST",
            first_load_date=first_load,
            lookback_days=lookback,
        )

        # Insert SUCCESS for every day in the expected range: 11 days
        # (Jan 1 through Jan 11 inclusive).
        for offset in range(0, 11):
            _insert_extraction_success(
                mssql_cursor,
                batch_id=30001 + offset,
                source_name="DNA",
                table_name="CONTINUOUS_TEST",
                business_date=first_load + timedelta(days=offset),
            )
        mssql_cursor.commit()

        reports = detect_extraction_gaps(
            source_filter="DNA",
            as_of_date=as_of,
        )

        # Filter to the table-under-test (the synthetic schema may carry
        # other UdmTablesList rows from prior tests; transactional
        # rollback usually clears them, but be defensive).
        relevant = [r for r in reports if r.table_name == "CONTINUOUS_TEST"]
        assert relevant == [], (
            f"Continuous extraction must produce NO GapReport; got {relevant!r}"
        )

    def test_detect_single_day_gap(
        self,
        mssql_cursor: Any,
        test_db_transaction: Any,
        canonical_schema_loaded: None,
    ) -> None:
        """9 days SUCCESS + 1 day missing -> GapReport.missing_dates = [day].

        The expected range is [first_load, as_of - lookback]. Insert
        SUCCESS for every date in that range EXCEPT one. The returned
        GapReport.missing_dates must contain exactly that one date.
        """
        from tools.gap_detector import (  # noqa: PLC0415
            ACTION_BACKFILL,
            detect_extraction_gaps,
        )

        _ensure_udmtableslist_minimal(mssql_cursor)

        first_load = date(2026, 2, 1)
        lookback = 2
        as_of = date(2026, 2, 13)  # Expected range: [2026-02-01, 2026-02-11]
        missing_date = date(2026, 2, 5)  # The deliberately-omitted day

        _insert_table_config(
            mssql_cursor,
            source_name="DNA",
            table_name="SINGLE_GAP_TEST",
            first_load_date=first_load,
            lookback_days=lookback,
        )

        # Insert SUCCESS for every date in [2026-02-01, 2026-02-11]
        # EXCEPT missing_date.
        expected_range_end = as_of - timedelta(days=lookback)
        cursor_date = first_load
        offset = 0
        while cursor_date <= expected_range_end:
            if cursor_date != missing_date:
                _insert_extraction_success(
                    mssql_cursor,
                    batch_id=30100 + offset,
                    source_name="DNA",
                    table_name="SINGLE_GAP_TEST",
                    business_date=cursor_date,
                )
            cursor_date += timedelta(days=1)
            offset += 1
        mssql_cursor.commit()

        reports = detect_extraction_gaps(
            source_filter="DNA",
            as_of_date=as_of,
        )

        relevant = [r for r in reports if r.table_name == "SINGLE_GAP_TEST"]
        assert len(relevant) == 1, (
            f"Expected exactly 1 GapReport for SINGLE_GAP_TEST; got {relevant!r}"
        )
        report = relevant[0]
        assert report.source_name == "DNA"
        assert report.missing_dates == [missing_date], (
            f"Expected missing_dates=[{missing_date}]; got {report.missing_dates!r}"
        )
        # SUCCESS rows exist in the range, so recommended_action is BACKFILL.
        assert report.recommended_action == ACTION_BACKFILL
        # expected_range bounds match what the engine computed.
        assert report.expected_range == (first_load, expected_range_end)

    def test_detect_multiple_consecutive_day_gaps(
        self,
        mssql_cursor: Any,
        test_db_transaction: Any,
        canonical_schema_loaded: None,
    ) -> None:
        """3-day consecutive gap in middle of 14-day window -> 3 missing dates.

        Asserts the engine identifies a multi-day contiguous gap range
        correctly. The returned missing_dates list is sorted ascending
        per § 5.3 contract.
        """
        from tools.gap_detector import (  # noqa: PLC0415
            ACTION_BACKFILL,
            detect_extraction_gaps,
        )

        _ensure_udmtableslist_minimal(mssql_cursor)

        first_load = date(2026, 3, 1)
        lookback = 0  # no lookback exclusion - every day through as_of expected
        as_of = date(2026, 3, 14)
        # Expected range: [2026-03-01, 2026-03-14]
        missing_dates_expected = [
            date(2026, 3, 6),
            date(2026, 3, 7),
            date(2026, 3, 8),
        ]

        _insert_table_config(
            mssql_cursor,
            source_name="DNA",
            table_name="MULTI_GAP_TEST",
            first_load_date=first_load,
            lookback_days=lookback,
        )

        # Insert SUCCESS for every date EXCEPT the 3-day gap.
        cursor_date = first_load
        offset = 0
        while cursor_date <= as_of:
            if cursor_date not in missing_dates_expected:
                _insert_extraction_success(
                    mssql_cursor,
                    batch_id=30200 + offset,
                    source_name="DNA",
                    table_name="MULTI_GAP_TEST",
                    business_date=cursor_date,
                )
            cursor_date += timedelta(days=1)
            offset += 1
        mssql_cursor.commit()

        reports = detect_extraction_gaps(
            source_filter="DNA",
            as_of_date=as_of,
        )
        relevant = [r for r in reports if r.table_name == "MULTI_GAP_TEST"]
        assert len(relevant) == 1
        report = relevant[0]
        # missing_dates is sorted ascending per § 5.3.
        assert report.missing_dates == missing_dates_expected, (
            f"Expected missing_dates={missing_dates_expected}; "
            f"got {report.missing_dates!r}"
        )
        assert report.recommended_action == ACTION_BACKFILL
        # 3 consecutive missing days within a 14-day history.
        assert len(report.missing_dates) == 3

    def test_detect_recommends_investigate_when_no_success_rows(
        self,
        mssql_cursor: Any,
        test_db_transaction: Any,
        canonical_schema_loaded: None,
    ) -> None:
        """Zero SUCCESS rows in expected range -> recommended_action='investigate-source'.

        Per § 5.3: ACTION_INVESTIGATE fires when the table has been
        registered (FirstLoadDate set) but has ZERO SUCCESS rows in
        the expected range. The operator must inspect (source down?
        table never activated?) before a blind backfill stacks up FAILED
        rows. This is distinct from ACTION_BACKFILL where some SUCCESS
        rows exist and a targeted backfill closes the missing dates.

        Synthetic setup: register a table; insert NO PipelineExtraction
        rows. The engine should classify as investigate-source.
        """
        from tools.gap_detector import (  # noqa: PLC0415
            ACTION_INVESTIGATE,
            detect_extraction_gaps,
        )

        _ensure_udmtableslist_minimal(mssql_cursor)

        first_load = date(2026, 4, 1)
        lookback = 1
        as_of = date(2026, 4, 10)  # Expected range: [2026-04-01, 2026-04-09]

        _insert_table_config(
            mssql_cursor,
            source_name="DNA",
            table_name="INVESTIGATE_TEST",
            first_load_date=first_load,
            lookback_days=lookback,
        )
        # Deliberately insert NO PipelineExtraction SUCCESS rows.
        mssql_cursor.commit()

        reports = detect_extraction_gaps(
            source_filter="DNA",
            as_of_date=as_of,
        )
        relevant = [r for r in reports if r.table_name == "INVESTIGATE_TEST"]
        assert len(relevant) == 1, (
            f"Expected 1 GapReport for INVESTIGATE_TEST; got {relevant!r}"
        )
        report = relevant[0]
        assert report.recommended_action == ACTION_INVESTIGATE, (
            f"Zero SUCCESS rows must produce ACTION_INVESTIGATE; "
            f"got recommended_action={report.recommended_action!r}"
        )
        # Every day in the expected range is missing.
        expected_range_end = as_of - timedelta(days=lookback)
        expected_total = (expected_range_end - first_load).days + 1
        assert len(report.missing_dates) == expected_total

    def test_detect_skips_table_when_only_lookback_window_unfilled(
        self,
        mssql_cursor: Any,
        test_db_transaction: Any,
        canonical_schema_loaded: None,
    ) -> None:
        """Missing dates inside LookbackDays window -> NO GapReport emitted.

        Per § 5.3: the rolling lookback window
        ``(as_of_date - LookbackDays, as_of_date]`` is intentionally
        excluded from gap analysis - any missing day there is expected
        to fill in within the next normal run. Only dates inside
        ``[first_load, as_of - lookback]`` are checked.

        Synthetic setup: lookback=5 days; insert SUCCESS for every day
        EXCEPT the 3 most recent (which fall inside the lookback window).
        The engine MUST classify as clean and emit no GapReport.
        """
        from tools.gap_detector import detect_extraction_gaps  # noqa: PLC0415

        _ensure_udmtableslist_minimal(mssql_cursor)

        first_load = date(2026, 5, 1)
        lookback = 5
        as_of = date(2026, 5, 14)
        # Expected range: [2026-05-01, 2026-05-09] (14 - 5 = 9)
        # Lookback window: 2026-05-10 through 2026-05-14 (excluded)

        _insert_table_config(
            mssql_cursor,
            source_name="DNA",
            table_name="LOOKBACK_TEST",
            first_load_date=first_load,
            lookback_days=lookback,
        )

        # Fill every date in the EXPECTED range (May 1 through May 9).
        # Deliberately omit dates inside the lookback window (May 10-14).
        cursor_date = first_load
        offset = 0
        expected_range_end = as_of - timedelta(days=lookback)
        while cursor_date <= expected_range_end:
            _insert_extraction_success(
                mssql_cursor,
                batch_id=30300 + offset,
                source_name="DNA",
                table_name="LOOKBACK_TEST",
                business_date=cursor_date,
            )
            cursor_date += timedelta(days=1)
            offset += 1
        mssql_cursor.commit()

        reports = detect_extraction_gaps(
            source_filter="DNA",
            as_of_date=as_of,
        )
        relevant = [r for r in reports if r.table_name == "LOOKBACK_TEST"]
        assert relevant == [], (
            f"Lookback-window-only missing dates must NOT produce a "
            f"GapReport; got {relevant!r}"
        )
