"""Tier 3 integration tests for orchestration/range_scheduler.py.

Per docs/migration/phase1/05_tests.md § 6.2 canonical scenario:
"Real ExtractionRangePolicy rows + real extraction_state history ->
produce ExtractionPlan".

Canonical signature under test (per phase1/03_core_modules.md § 5.1):

    def plan_extraction_range(
        *,
        source_name: str,
        table_name: str,
        as_of_date: date | None = None,
        max_dates: int = _DEFAULT_MAX_DATES,
    ) -> ExtractionPlan: ...

    @dataclass(frozen=True)
    class ExtractionPlan:
        source_name: str
        table_name: str
        dates: list[date]
        re_extraction_flags: dict[date, bool]
        policy_source: str  # 'ExtractionRangePolicy' | 'default-lookback'

D-numbers covered:
  - D11 (empirical L_99 lookback) - LookbackDays defines the rolling
    window in default-lookback mode.
  - D12 (ExtractionRangePolicy table) - per-row policy ranges drive
    plan when at least one Active=1 row exists.
  - D14 (re-extraction tracking) - re_extraction_flags map is composed
    via cdc.extraction_state.most_recent_success.
  - D67 (Tier 0 smoke required).
  - D68 (error class hierarchy) - RangePolicyMissing +
    ExtractionStateUnavailable carry metadata kwargs.

Setup overhead: range_scheduler reads UdmTablesList +
ExtractionRangePolicy + PipelineExtraction (via cdc.extraction_state).
The canonical schema fixture (schema.sql) carries PipelineExtraction;
UdmTablesList + ExtractionRangePolicy are inline-created per test
(rolled back / scoped via unique source_name+table_name keys to avoid
collision with sibling tests).

Each test uses unique table identifiers so cross-test data is isolated
even though commit() persists rows in the session-scope container.
"""
from __future__ import annotations

import logging
import sys
from datetime import date, timedelta
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
# Inline DDL helpers for the two tables the canonical schema.sql does NOT
# carry. Created idempotently inside test_db_transaction; uniqueness is
# preserved via per-test source_name + table_name keys.
# ---------------------------------------------------------------------------


def _ensure_udmtableslist_minimal(cursor: Any) -> None:
    """Create dbo.UdmTablesList with the columns range_scheduler reads.

    range_scheduler queries SourceName + SourceObjectName + FirstLoadDate
    + LookbackDays. The full UdmTablesList has ~40 columns; this minimal
    subset is sufficient for the planner.
    """
    cursor.execute(
        """
        IF OBJECT_ID('General.dbo.UdmTablesList') IS NULL
        BEGIN
            CREATE TABLE General.dbo.UdmTablesList (
                SourceName        NVARCHAR(50)  NOT NULL,
                SourceObjectName  NVARCHAR(255) NOT NULL,
                FirstLoadDate     DATE          NULL,
                LookbackDays      INT           NULL,
                CONSTRAINT PK_UdmTablesList_RangeSchedTier3 PRIMARY KEY
                    (SourceName, SourceObjectName)
            );
        END
        """
    )


def _ensure_extraction_range_policy(cursor: Any) -> None:
    """Create General.ops.ExtractionRangePolicy per phase1/01 § 9 DDL.

    range_scheduler queries SourceName + TableName + Active=1 rows for
    RangeStartDate + RangeEndDate. The minimal subset matches the
    canonical DDL columns the planner reads.
    """
    cursor.execute(
        """
        IF OBJECT_ID('General.ops.ExtractionRangePolicy') IS NULL
        BEGIN
            CREATE TABLE General.ops.ExtractionRangePolicy (
                RangeId           BIGINT IDENTITY(1,1) NOT NULL,
                SourceName        NVARCHAR(50)  NOT NULL,
                TableName         NVARCHAR(255) NOT NULL,
                RangeStartDate    DATE          NULL,
                RangeEndDate      DATE          NULL,
                RangeKind         NVARCHAR(20)  NOT NULL DEFAULT 'current',
                MaxStaleDays      INT           NOT NULL DEFAULT 7,
                Priority          INT           NOT NULL DEFAULT 50,
                Active            BIT           NOT NULL DEFAULT 1,
                CreatedAt         DATETIME2(3)  NOT NULL DEFAULT SYSUTCDATETIME(),
                UpdatedAt         DATETIME2(3)  NOT NULL DEFAULT SYSUTCDATETIME(),
                CONSTRAINT PK_ExtractionRangePolicy_Tier3 PRIMARY KEY (RangeId)
            );
        END
        """
    )


def _insert_udmtableslist_row(
    cursor: Any,
    *,
    source_name: str,
    table_name: str,
    first_load_date: date | None,
    lookback_days: int | None,
) -> None:
    """Insert one UdmTablesList row for the test's table."""
    cursor.execute(
        """
        INSERT INTO General.dbo.UdmTablesList
            (SourceName, SourceObjectName, FirstLoadDate, LookbackDays)
        VALUES (?, ?, ?, ?)
        """,
        source_name,
        table_name,
        first_load_date,
        lookback_days,
    )


def _insert_policy_row(
    cursor: Any,
    *,
    source_name: str,
    table_name: str,
    range_start: date | None,
    range_end: date | None,
    active: int = 1,
    range_kind: str = "current",
) -> None:
    """Insert one ExtractionRangePolicy row.

    NULL on either bound is interpreted by range_scheduler as "today"
    (per the DDL contract). active=0 rows must be ignored by the planner.
    """
    cursor.execute(
        """
        INSERT INTO General.ops.ExtractionRangePolicy
            (SourceName, TableName, RangeStartDate, RangeEndDate,
             RangeKind, Active)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        source_name,
        table_name,
        range_start,
        range_end,
        range_kind,
        active,
    )


def _insert_extraction_success(
    cursor: Any,
    *,
    batch_id: int,
    source_name: str,
    table_name: str,
    business_date: date,
) -> None:
    """Insert one SUCCESS PipelineExtraction row.

    Composed by re_extraction_flags via
    cdc.extraction_state.most_recent_success — every planned date <=
    most-recent SUCCESS gets is_reextraction=True.
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
# Test class - range scheduler against real UdmTablesList +
# ExtractionRangePolicy + PipelineExtraction.
# ---------------------------------------------------------------------------


class TestRangeSchedulerWithRealPolicies:
    """D12 + D11 + D14 invariants for orchestration/range_scheduler.py.

    Each test seeds UdmTablesList + (optionally) ExtractionRangePolicy +
    (optionally) PipelineExtraction inside the test_db_transaction-rolled-
    back block, calls plan_extraction_range, and asserts the returned
    ExtractionPlan matches the synthetic setup.

    Every test passes an explicit as_of_date so the planning boundary
    is deterministic across calendar drift.
    """

    def test_default_lookback_mode_yields_rolling_window(
        self,
        mssql_cursor: Any,
        test_db_transaction: Any,
        canonical_schema_loaded: None,
    ) -> None:
        """LookbackDays=5, FirstLoadDate=10 days ago -> rolling 5-day window.

        Per § 5.1 default-lookback mode: when no policy rows exist AND
        UdmTablesList.LookbackDays is populated, the schedule is
        [as_of_date - LookbackDays + 1, as_of_date] clipped to FirstLoadDate.
        """
        from orchestration.range_scheduler import plan_extraction_range  # noqa: PLC0415

        _ensure_udmtableslist_minimal(mssql_cursor)
        _ensure_extraction_range_policy(mssql_cursor)

        as_of = date(2026, 6, 14)
        first_load = date(2026, 6, 1)
        lookback = 5

        _insert_udmtableslist_row(
            mssql_cursor,
            source_name="DNA",
            table_name="DEFAULT_LOOKBACK_TEST",
            first_load_date=first_load,
            lookback_days=lookback,
        )
        mssql_cursor.commit()

        plan = plan_extraction_range(
            source_name="DNA",
            table_name="DEFAULT_LOOKBACK_TEST",
            as_of_date=as_of,
        )

        # Expected: [2026-06-10, 2026-06-11, 2026-06-12, 2026-06-13, 2026-06-14]
        expected_dates = [
            as_of - timedelta(days=offset)
            for offset in range(lookback - 1, -1, -1)
        ]
        assert plan.source_name == "DNA"
        assert plan.table_name == "DEFAULT_LOOKBACK_TEST"
        assert plan.dates == expected_dates, (
            f"Default-lookback should produce {expected_dates}; "
            f"got {plan.dates}"
        )
        assert plan.policy_source == "default-lookback"
        # No PipelineExtraction history -> all dates are first-pass.
        assert all(
            plan.re_extraction_flags[d] is False for d in plan.dates
        )

    def test_policy_mode_with_single_active_range(
        self,
        mssql_cursor: Any,
        test_db_transaction: Any,
        canonical_schema_loaded: None,
    ) -> None:
        """One Active=1 ExtractionRangePolicy row drives the plan.

        Per § 5.1 policy mode: any Active=1 policy row supersedes the
        default-lookback fallback. The plan dates are the explicit range
        clipped to FirstLoadDate.
        """
        from orchestration.range_scheduler import plan_extraction_range  # noqa: PLC0415

        _ensure_udmtableslist_minimal(mssql_cursor)
        _ensure_extraction_range_policy(mssql_cursor)

        as_of = date(2026, 7, 20)
        first_load = date(2026, 7, 1)

        _insert_udmtableslist_row(
            mssql_cursor,
            source_name="DNA",
            table_name="POLICY_SINGLE_TEST",
            first_load_date=first_load,
            lookback_days=2,  # would yield 2-day window if default-lookback
        )
        # Explicit policy: extract Jul 5 through Jul 9 (5 days).
        _insert_policy_row(
            mssql_cursor,
            source_name="DNA",
            table_name="POLICY_SINGLE_TEST",
            range_start=date(2026, 7, 5),
            range_end=date(2026, 7, 9),
        )
        mssql_cursor.commit()

        plan = plan_extraction_range(
            source_name="DNA",
            table_name="POLICY_SINGLE_TEST",
            as_of_date=as_of,
        )

        expected_dates = [
            date(2026, 7, 5),
            date(2026, 7, 6),
            date(2026, 7, 7),
            date(2026, 7, 8),
            date(2026, 7, 9),
        ]
        assert plan.dates == expected_dates, (
            f"Policy mode should yield explicit range {expected_dates}; "
            f"got {plan.dates}"
        )
        assert plan.policy_source == "ExtractionRangePolicy"

    def test_policy_mode_unions_multiple_active_ranges(
        self,
        mssql_cursor: Any,
        test_db_transaction: Any,
        canonical_schema_loaded: None,
    ) -> None:
        """Two Active=1 policy rows -> union of their date ranges.

        Per § 5.1: every Active=1 row contributes a closed range; the
        union is sorted ascending. Overlapping ranges deduplicate.
        """
        from orchestration.range_scheduler import plan_extraction_range  # noqa: PLC0415

        _ensure_udmtableslist_minimal(mssql_cursor)
        _ensure_extraction_range_policy(mssql_cursor)

        as_of = date(2026, 8, 31)
        first_load = date(2026, 8, 1)

        _insert_udmtableslist_row(
            mssql_cursor,
            source_name="DNA",
            table_name="POLICY_UNION_TEST",
            first_load_date=first_load,
            lookback_days=None,
        )
        # Range 1: Aug 5-7
        _insert_policy_row(
            mssql_cursor,
            source_name="DNA",
            table_name="POLICY_UNION_TEST",
            range_start=date(2026, 8, 5),
            range_end=date(2026, 8, 7),
        )
        # Range 2: Aug 10-12 (disjoint from range 1)
        _insert_policy_row(
            mssql_cursor,
            source_name="DNA",
            table_name="POLICY_UNION_TEST",
            range_start=date(2026, 8, 10),
            range_end=date(2026, 8, 12),
        )
        mssql_cursor.commit()

        plan = plan_extraction_range(
            source_name="DNA",
            table_name="POLICY_UNION_TEST",
            as_of_date=as_of,
        )

        expected_dates = [
            date(2026, 8, 5),
            date(2026, 8, 6),
            date(2026, 8, 7),
            date(2026, 8, 10),
            date(2026, 8, 11),
            date(2026, 8, 12),
        ]
        assert plan.dates == expected_dates, (
            f"Union should produce {expected_dates}; got {plan.dates}"
        )
        assert plan.policy_source == "ExtractionRangePolicy"

    def test_inactive_policy_rows_are_ignored(
        self,
        mssql_cursor: Any,
        test_db_transaction: Any,
        canonical_schema_loaded: None,
    ) -> None:
        """Active=0 policy rows must NOT influence the plan.

        Per the canonical DDL filter `AND Active = 1` in
        _lookup_active_policy_ranges. With only inactive policy rows AND
        a populated LookbackDays, the planner falls back to default-lookback.
        """
        from orchestration.range_scheduler import plan_extraction_range  # noqa: PLC0415

        _ensure_udmtableslist_minimal(mssql_cursor)
        _ensure_extraction_range_policy(mssql_cursor)

        as_of = date(2026, 9, 30)
        first_load = date(2026, 9, 1)
        lookback = 3

        _insert_udmtableslist_row(
            mssql_cursor,
            source_name="DNA",
            table_name="INACTIVE_POLICY_TEST",
            first_load_date=first_load,
            lookback_days=lookback,
        )
        # An inactive policy row that, if honored, would extend the range
        # backward to Sep 5. Active=0 -> must be ignored.
        _insert_policy_row(
            mssql_cursor,
            source_name="DNA",
            table_name="INACTIVE_POLICY_TEST",
            range_start=date(2026, 9, 5),
            range_end=date(2026, 9, 9),
            active=0,
        )
        mssql_cursor.commit()

        plan = plan_extraction_range(
            source_name="DNA",
            table_name="INACTIVE_POLICY_TEST",
            as_of_date=as_of,
        )

        # Default-lookback wins: 3-day rolling window through Sep 30.
        expected_dates = [
            date(2026, 9, 28),
            date(2026, 9, 29),
            date(2026, 9, 30),
        ]
        assert plan.dates == expected_dates
        assert plan.policy_source == "default-lookback", (
            "Inactive policy rows must NOT trigger policy mode; "
            f"got policy_source={plan.policy_source!r}"
        )

    def test_re_extraction_flags_match_pipeline_extraction_history(
        self,
        mssql_cursor: Any,
        test_db_transaction: Any,
        canonical_schema_loaded: None,
    ) -> None:
        """re_extraction_flags=True for dates <= most-recent SUCCESS date.

        Per § 5.1 D14 composition: the planner stamps is_reextraction=True
        on every planned date that has a prior SUCCESS row in
        PipelineExtraction (via cdc.extraction_state.most_recent_success).
        Dates with no prior SUCCESS get is_reextraction=False.
        """
        from orchestration.range_scheduler import plan_extraction_range  # noqa: PLC0415

        _ensure_udmtableslist_minimal(mssql_cursor)
        _ensure_extraction_range_policy(mssql_cursor)

        as_of = date(2026, 10, 31)
        first_load = date(2026, 10, 1)

        _insert_udmtableslist_row(
            mssql_cursor,
            source_name="DNA",
            table_name="REEXTR_FLAGS_TEST",
            first_load_date=first_load,
            lookback_days=5,
        )
        # Most-recent SUCCESS is Oct 28: any planned date <= Oct 28 is a
        # re-extraction; Oct 29-31 are first-pass.
        _insert_extraction_success(
            mssql_cursor,
            batch_id=40001,
            source_name="DNA",
            table_name="REEXTR_FLAGS_TEST",
            business_date=date(2026, 10, 25),
        )
        _insert_extraction_success(
            mssql_cursor,
            batch_id=40002,
            source_name="DNA",
            table_name="REEXTR_FLAGS_TEST",
            business_date=date(2026, 10, 28),
        )
        mssql_cursor.commit()

        plan = plan_extraction_range(
            source_name="DNA",
            table_name="REEXTR_FLAGS_TEST",
            as_of_date=as_of,
        )

        # Default-lookback mode: 5-day rolling window through Oct 31:
        # Oct 27, 28, 29, 30, 31.
        # Most-recent SUCCESS = Oct 28 -> Oct 27 + Oct 28 are
        # re-extractions; Oct 29 + Oct 30 + Oct 31 are first-pass.
        assert plan.re_extraction_flags[date(2026, 10, 27)] is True
        assert plan.re_extraction_flags[date(2026, 10, 28)] is True
        assert plan.re_extraction_flags[date(2026, 10, 29)] is False
        assert plan.re_extraction_flags[date(2026, 10, 30)] is False
        assert plan.re_extraction_flags[date(2026, 10, 31)] is False
        # Every planned date carries an explicit flag.
        assert set(plan.re_extraction_flags.keys()) == set(plan.dates)
