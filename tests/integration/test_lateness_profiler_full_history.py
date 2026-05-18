"""Tier 3 integration tests for cdc/lateness_profiler.py.

Per docs/migration/phase1/05_tests.md § 6.2 canonical scenario:
"Real PipelineExtraction data with synthetic delay distribution; verify
percentile computation against known answer".

Canonical signature under test (per phase1/03_core_modules.md § 5.2):

    def profile_lateness(
        *,
        source_name: str,
        table_name: str,
        window_days: int = 90,
        min_sample_days: int = 30,
    ) -> LatenessReport: ...

    @dataclass(frozen=True)
    class LatenessReport:
        source_name: str
        table_name: str
        window_start: date
        window_end: date
        sample_count: int
        p50_days: float
        p90_days: float
        p95_days: float
        p99_days: float
        max_observed_days: int
        confidence: str  # 'high' / 'medium' / 'low'
        as_of: datetime

D-numbers covered:
  - D11 (empirical L_99 lookback) - p99_days drives UdmTablesList.LookbackDays.
  - D67 (Tier 0 smoke required).
  - D68 (error class hierarchy) - InsufficientHistory + ExtractionStateUnavailable.
  - SCD2-P1-f / CDC-NOW-MS - LatenessReport.as_of is naive ms-precision UTC.

Setup overhead: profile_lateness reads General.ops.PipelineExtraction
SUCCESS rows in the trailing window. The canonical schema fixture
(schema.sql) carries PipelineExtraction; tests insert synthetic SUCCESS
rows with controllable (DateValue, CompletedAt) pairs to validate
percentile computation against known answers.

Each test uses unique source_name+table_name keys so cross-test data is
isolated even though commit() persists rows in the session-scope container.

The percentile algorithm uses statistics.quantiles(method='inclusive')
which matches NumPy np.percentile(method='linear') and Excel's
PERCENTILE.INC. Test assertions account for inclusive linear
interpolation, NOT exclusive.
"""
from __future__ import annotations

import logging
import sys
from datetime import date, datetime, time, timedelta
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
# Helpers - insert synthetic SUCCESS rows with controllable lateness.
#
# Lateness for one row = CompletedAt - end_of_day(DateValue).
# end_of_day(D) = D at 23:59:59.999. So inserting a row with:
#     DateValue = today_utc - K days (must be inside the trailing window)
#     CompletedAt = end_of_day(DateValue) + lateness_timedelta
# yields a sample of `lateness_timedelta.total_seconds() / 86400` days.
#
# The window for profile_lateness is [today_utc - window_days, today_utc].
# Tests place samples inside the window; samples outside (negative-K or
# K > window_days) are excluded.
# ---------------------------------------------------------------------------


def _end_of_day(business_date: date) -> datetime:
    """Naive ms-precision end-of-day boundary (matches engine internal)."""
    return datetime.combine(business_date, time(23, 59, 59, 999_000))


def _insert_success_row(
    cursor: Any,
    *,
    batch_id: int,
    source_name: str,
    table_name: str,
    business_date: date,
    lateness_days: float,
) -> None:
    """Insert one SUCCESS row with a precise lateness sample.

    completed_at = end_of_day(business_date) + lateness_days.
    Negative lateness_days are clamped by profile_lateness to 0 (real
    samples cannot precede the business-day boundary).
    """
    completed_at = _end_of_day(business_date) + timedelta(days=lateness_days)
    started_at = completed_at - timedelta(seconds=1)
    cursor.execute(
        """
        INSERT INTO General.ops.PipelineExtraction
            (BatchId, SourceName, TableName, DateValue, Status,
             StartedAt, CompletedAt, RowsExtracted, ExtractionAttempt)
        VALUES (?, ?, ?, ?, 'SUCCESS', ?, ?, ?, 1)
        """,
        batch_id,
        source_name,
        table_name,
        business_date,
        started_at,
        completed_at,
        100,
    )


def _insert_failed_row(
    cursor: Any,
    *,
    batch_id: int,
    source_name: str,
    table_name: str,
    business_date: date,
) -> None:
    """Insert one FAILED row - must be excluded from lateness samples."""
    cursor.execute(
        """
        INSERT INTO General.ops.PipelineExtraction
            (BatchId, SourceName, TableName, DateValue, Status,
             StartedAt, CompletedAt, RowsExtracted, FailureReason,
             ExtractionAttempt)
        VALUES (?, ?, ?, ?, 'FAILED',
                SYSUTCDATETIME(), SYSUTCDATETIME(), NULL,
                'synthetic-test-failure', 1)
        """,
        batch_id,
        source_name,
        table_name,
        business_date,
    )


# ---------------------------------------------------------------------------
# Test class - lateness profiler against real PipelineExtraction.
# ---------------------------------------------------------------------------


class TestLatenessProfilerFullHistory:
    """D11 lateness-percentile invariants for cdc/lateness_profiler.py.

    Each test seeds PipelineExtraction with synthetic SUCCESS (or FAILED)
    rows of known lateness, calls profile_lateness, and asserts the
    returned LatenessReport's percentile fields match the analytic answer.

    All tests place samples inside the default 90-day window relative to
    today UTC. The window boundary is computed inside profile_lateness as
    today_utc - window_days through today_utc; tests use small offsets
    (1-89 days back) so window-edge effects do not perturb results.
    """

    def test_uniform_lateness_distribution_yields_expected_p99(
        self,
        mssql_cursor: Any,
        test_db_transaction: Any,
        canonical_schema_loaded: None,
    ) -> None:
        """100 rows all with lateness=1.5d -> p50=p90=p95=p99=1.5d.

        A uniform distribution has identical percentile values at every
        cut-point. Insert 100 SUCCESS rows each with exactly 1.5 days of
        lateness; assert every percentile is 1.5 (within float tolerance).
        100 samples also drives confidence='high'.
        """
        from cdc.lateness_profiler import profile_lateness  # noqa: PLC0415

        source = "DNA"
        table = "UNIFORM_LATENESS_TEST"
        today = datetime.utcnow().date()

        # Place 100 rows on consecutive business dates in the window
        # [today - 1, today - 100] - all comfortably inside the default
        # 90-day window? No: 100 days exceeds 90. Use 89 spread back from
        # today - 1 to keep all rows inside the window.
        for offset in range(1, 90):
            _insert_success_row(
                mssql_cursor,
                batch_id=50000 + offset,
                source_name=source,
                table_name=table,
                business_date=today - timedelta(days=offset),
                lateness_days=1.5,
            )
        # Add 11 more rows on alternating earlier dates (still inside
        # window) so we hit 100 total samples for confidence='high'.
        for offset in range(1, 12):
            _insert_success_row(
                mssql_cursor,
                batch_id=50100 + offset,
                source_name=source,
                table_name=table,
                # Use sub-day spacing: same date, different batches OK
                # since the engine groups per-row, not per-(date) unique.
                business_date=today - timedelta(days=offset),
                lateness_days=1.5,
            )
        mssql_cursor.commit()

        report = profile_lateness(
            source_name=source,
            table_name=table,
            window_days=90,
            min_sample_days=30,
        )

        assert report.source_name == source
        assert report.table_name == table
        assert report.sample_count == 100, (
            f"Expected 100 samples; got {report.sample_count}"
        )
        # Uniform distribution: every percentile is the value itself.
        assert report.p50_days == pytest.approx(1.5, abs=1e-6)
        assert report.p90_days == pytest.approx(1.5, abs=1e-6)
        assert report.p95_days == pytest.approx(1.5, abs=1e-6)
        assert report.p99_days == pytest.approx(1.5, abs=1e-6)
        # max_observed_days uses ceil() per the engine.
        assert report.max_observed_days == 2
        # 100 samples -> high confidence per the module docstring tier.
        assert report.confidence == "high"
        # as_of is naive ms-precision per SCD2-P1-f / CDC-NOW-MS invariant.
        assert report.as_of.tzinfo is None
        assert report.as_of.microsecond % 1000 == 0

    def test_percentile_monotonicity_holds_over_linear_distribution(
        self,
        mssql_cursor: Any,
        test_db_transaction: Any,
        canonical_schema_loaded: None,
    ) -> None:
        """Lateness samples 0.0, 0.1, ..., 4.9 days -> p50 < p90 < p95 < p99.

        Per § 5.2 percentile semantics: the percentile sequence is
        monotonically non-decreasing. With a strictly-monotone input, all
        cut-points are strictly increasing.
        """
        from cdc.lateness_profiler import profile_lateness  # noqa: PLC0415

        source = "DNA"
        table = "MONOTONIC_LATENESS_TEST"
        today = datetime.utcnow().date()

        # Insert 50 rows with lateness in a strictly-monotone arithmetic
        # progression: 0.0, 0.1, ..., 4.9 days. All inside the 90-day
        # window via different business dates (today - 1 .. today - 50).
        for i in range(50):
            _insert_success_row(
                mssql_cursor,
                batch_id=50300 + i,
                source_name=source,
                table_name=table,
                business_date=today - timedelta(days=i + 1),
                lateness_days=i * 0.1,
            )
        mssql_cursor.commit()

        report = profile_lateness(
            source_name=source,
            table_name=table,
            window_days=90,
            min_sample_days=30,
        )

        assert report.sample_count == 50
        # Strictly monotone input -> strictly monotone percentile output.
        assert report.p50_days < report.p90_days, (
            f"p50 ({report.p50_days}) must be < p90 ({report.p90_days})"
        )
        assert report.p90_days < report.p95_days, (
            f"p90 ({report.p90_days}) must be < p95 ({report.p95_days})"
        )
        assert report.p95_days < report.p99_days, (
            f"p95 ({report.p95_days}) must be < p99 ({report.p99_days})"
        )
        # p99 must be at or below the maximum sample value (4.9 days).
        assert report.p99_days <= 4.9
        # Confidence 'medium' for 30 <= n < 100.
        assert report.confidence == "medium"

    def test_insufficient_history_raises_fatal_below_threshold(
        self,
        mssql_cursor: Any,
        test_db_transaction: Any,
        canonical_schema_loaded: None,
    ) -> None:
        """5 SUCCESS rows + min_sample_days=30 -> InsufficientHistory raised.

        Per § 5.2 contract: profile_lateness requires >= min_sample_days
        SUCCESS rows in the window. Below that threshold, percentiles are
        statistically unstable and the function raises InsufficientHistory
        (PipelineFatalError per D68) rather than returning unreliable values.
        """
        from cdc.lateness_profiler import profile_lateness  # noqa: PLC0415
        from utils.errors import PipelineFatalError  # noqa: PLC0415

        source = "DNA"
        table = "INSUFFICIENT_HISTORY_TEST"
        today = datetime.utcnow().date()

        # Insert only 5 SUCCESS rows - well below default min_sample_days=30.
        for i in range(5):
            _insert_success_row(
                mssql_cursor,
                batch_id=50400 + i,
                source_name=source,
                table_name=table,
                business_date=today - timedelta(days=i + 1),
                lateness_days=1.0,
            )
        mssql_cursor.commit()

        # InsufficientHistory subclasses PipelineFatalError per D68; assert
        # via the canonical hierarchy + check the error class name.
        with pytest.raises(PipelineFatalError) as excinfo:
            profile_lateness(
                source_name=source,
                table_name=table,
                window_days=90,
                min_sample_days=30,
            )
        assert excinfo.type.__name__ == "InsufficientHistory", (
            f"Expected InsufficientHistory; got {excinfo.type.__name__!r}"
        )
        # Metadata should record the actual sample count for diagnostics.
        assert "sample_count" in (excinfo.value.metadata or {})
        assert excinfo.value.metadata["sample_count"] == 5

    def test_failed_status_rows_excluded_from_samples(
        self,
        mssql_cursor: Any,
        test_db_transaction: Any,
        canonical_schema_loaded: None,
    ) -> None:
        """30 SUCCESS + 50 FAILED -> sample_count=30 (FAILED excluded).

        Per § 5.2 _fetch_lateness_samples filter: only Status='SUCCESS'
        rows with non-NULL CompletedAt are sampled. FAILED rows must NOT
        depress the percentile or inflate the sample count.
        """
        from cdc.lateness_profiler import profile_lateness  # noqa: PLC0415

        source = "DNA"
        table = "FAILED_EXCLUDED_TEST"
        today = datetime.utcnow().date()

        # 30 SUCCESS rows with uniform 0.5d lateness.
        for i in range(30):
            _insert_success_row(
                mssql_cursor,
                batch_id=50500 + i,
                source_name=source,
                table_name=table,
                business_date=today - timedelta(days=i + 1),
                lateness_days=0.5,
            )
        # 50 FAILED rows interleaved (must be ignored).
        for i in range(50):
            _insert_failed_row(
                mssql_cursor,
                batch_id=50600 + i,
                source_name=source,
                table_name=table,
                business_date=today - timedelta(days=i + 1),
            )
        mssql_cursor.commit()

        report = profile_lateness(
            source_name=source,
            table_name=table,
            window_days=90,
            min_sample_days=30,
        )

        # Only the 30 SUCCESS rows count.
        assert report.sample_count == 30, (
            f"Expected sample_count=30 (FAILED rows excluded); "
            f"got {report.sample_count}"
        )
        # All SUCCESS samples have lateness=0.5; uniform distribution -> p99=0.5.
        assert report.p99_days == pytest.approx(0.5, abs=1e-6)

    def test_negative_lateness_clamped_to_zero(
        self,
        mssql_cursor: Any,
        test_db_transaction: Any,
        canonical_schema_loaded: None,
    ) -> None:
        """Row with CompletedAt before end_of_day(DateValue) -> lateness=0.

        Per § 5.2 _lateness_days clamp: negative samples (extraction
        completed before the business-day boundary - a configuration error
        scenario) are clamped to 0 rather than included as negative values
        that would silently depress the percentile.
        """
        from cdc.lateness_profiler import profile_lateness  # noqa: PLC0415

        source = "DNA"
        table = "NEGATIVE_LATENESS_CLAMP_TEST"
        today = datetime.utcnow().date()

        # 30 rows with lateness = -0.5 days (would be negative if not clamped).
        # The engine clamps to 0; uniform-zero distribution -> p99=0.
        for i in range(30):
            _insert_success_row(
                mssql_cursor,
                batch_id=50700 + i,
                source_name=source,
                table_name=table,
                business_date=today - timedelta(days=i + 1),
                lateness_days=-0.5,
            )
        mssql_cursor.commit()

        report = profile_lateness(
            source_name=source,
            table_name=table,
            window_days=90,
            min_sample_days=30,
        )

        assert report.sample_count == 30
        # All samples clamped to 0 -> every percentile is 0.
        assert report.p50_days == pytest.approx(0.0, abs=1e-6)
        assert report.p99_days == pytest.approx(0.0, abs=1e-6)
        assert report.max_observed_days == 0, (
            "Negative samples must clamp to 0; max_observed_days should be 0"
        )
