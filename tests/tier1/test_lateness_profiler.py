"""Tier 1 unit test for cdc/lateness_profiler.py.

Per D70 Tier 1 — per-function + per-error-path coverage; mocks pyodbc
cursor; no live SQL Server.

Tested surface:
  - Identity-input validation (empty source / table → typed error).
  - Window-validation (window_days <= 0; min_sample_days < 0;
    min_sample_days > window_days).
  - Lateness arithmetic (end_of_day vs CompletedAt; clamp on negative;
    naive UTC ms precision per SCD2-P1-f).
  - Percentile algorithm (known data sets with hand-computed expected
    p50 / p90 / p95 / p99; monotonic ordering invariant).
  - InsufficientHistory raise at the min_sample_days threshold (boundary
    test at exactly N-1, N, N+1).
  - Confidence tier mapping (low / medium / high boundaries).
  - DB failure paths → ExtractionStateUnavailable (PipelineRetryableError).
  - Status='FAILED' rows + CompletedAt IS NULL rows excluded (query-level).
  - persist_lateness_report INSERT contract (column list, OUTPUT clause,
    drift % computation).

North Star pillars:
  - Operationally stable (every error path surfaces the documented base
    type per D68 — InsufficientHistory is PipelineFatalError,
    ExtractionStateUnavailable is PipelineRetryableError).
  - Audit-grade (every error metadata dict carries the documented keys for
    PipelineEventLog forwarding per D76).
  - Traceability (window boundaries echoed in metadata so operators can
    reproduce a report from any prior run's audit row).

Spec: phase1/03_core_modules.md § 5.2 + phase1/01_database_schema.md § 3 + § 10.

B-numbers: B-244 (M12 build); depends on B85 (utils.errors).
"""
from __future__ import annotations

import math
import sys
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pyodbc
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


def _make_cursor(fetchall_returns=None, fetchone_returns=None) -> MagicMock:
    cur = MagicMock()
    if fetchall_returns is not None:
        cur.fetchall.return_value = fetchall_returns
    if fetchone_returns is not None:
        cur.fetchone.return_value = fetchone_returns
    return cur


def _make_cursor_for(cur: MagicMock):
    @contextmanager
    def _cm(_db: str):
        yield cur

    return _cm


def _end_of_day(d: date) -> datetime:
    """Mirror the module's _end_of_day helper for test arithmetic."""
    return datetime.combine(d, time(23, 59, 59, 999_000))


def _synth_rows(*, days_late_list: list[float], base_date: date | None = None) -> list[tuple[date, datetime]]:
    """Build (DateValue, CompletedAt) tuples with pinned lateness."""
    base = base_date or (datetime.now(timezone.utc).date() - timedelta(days=10))
    rows: list[tuple[date, datetime]] = []
    for i, d in enumerate(days_late_list):
        dv = base - timedelta(days=i)
        completed = _end_of_day(dv) + timedelta(days=d)
        rows.append((dv, completed))
    return rows


# ===========================================================================
# Identity + window validation
# ===========================================================================


class TestInputValidation:

    def test_empty_source_name_raises(self):
        from cdc.lateness_profiler import profile_lateness
        from utils.errors import ExtractionStateUnavailable

        with pytest.raises(ExtractionStateUnavailable) as exc_info:
            profile_lateness(source_name="", table_name="ACCT")
        assert "source_name" in exc_info.value.metadata or "source_name_repr" in exc_info.value.metadata

    def test_empty_table_name_raises(self):
        from cdc.lateness_profiler import profile_lateness
        from utils.errors import ExtractionStateUnavailable

        with pytest.raises(ExtractionStateUnavailable):
            profile_lateness(source_name="DNA", table_name="")

    def test_non_string_source_name_raises(self):
        from cdc.lateness_profiler import profile_lateness
        from utils.errors import ExtractionStateUnavailable

        with pytest.raises(ExtractionStateUnavailable):
            profile_lateness(source_name=42, table_name="ACCT")  # type: ignore[arg-type]

    def test_zero_window_days_raises(self):
        from cdc.lateness_profiler import profile_lateness
        from utils.errors import ExtractionStateUnavailable

        with pytest.raises(ExtractionStateUnavailable):
            profile_lateness(source_name="DNA", table_name="ACCT", window_days=0)

    def test_negative_window_days_raises(self):
        from cdc.lateness_profiler import profile_lateness
        from utils.errors import ExtractionStateUnavailable

        with pytest.raises(ExtractionStateUnavailable):
            profile_lateness(source_name="DNA", table_name="ACCT", window_days=-5)

    def test_negative_min_sample_days_raises(self):
        from cdc.lateness_profiler import profile_lateness
        from utils.errors import ExtractionStateUnavailable

        with pytest.raises(ExtractionStateUnavailable):
            profile_lateness(
                source_name="DNA", table_name="ACCT", min_sample_days=-1
            )

    def test_min_sample_days_exceeding_window_raises(self):
        from cdc.lateness_profiler import profile_lateness
        from utils.errors import ExtractionStateUnavailable

        with pytest.raises(ExtractionStateUnavailable):
            profile_lateness(
                source_name="DNA",
                table_name="ACCT",
                window_days=10,
                min_sample_days=20,
            )


# ===========================================================================
# Lateness arithmetic
# ===========================================================================


class TestLatenessArithmetic:
    """Spot-check the per-sample lateness computation against pinned values."""

    def test_zero_lateness_when_completed_at_equals_end_of_day(self):
        """Extraction completing exactly at the business-day boundary
        yields lateness = 0 (rounding caveat: the boundary is 23:59:59.999
        not midnight, so this asserts 0.0 to machine precision)."""
        from cdc.lateness_profiler import _lateness_days

        dv = date(2025, 1, 15)
        completed = _end_of_day(dv)
        assert _lateness_days(completed_at=completed, business_date=dv) == pytest.approx(0.0)

    def test_one_day_late_yields_one(self):
        from cdc.lateness_profiler import _lateness_days

        dv = date(2025, 1, 15)
        completed = _end_of_day(dv) + timedelta(days=1)
        assert _lateness_days(completed_at=completed, business_date=dv) == pytest.approx(1.0)

    def test_fractional_lateness_in_hours(self):
        """12 hours late = 0.5 days."""
        from cdc.lateness_profiler import _lateness_days

        dv = date(2025, 1, 15)
        completed = _end_of_day(dv) + timedelta(hours=12)
        assert _lateness_days(completed_at=completed, business_date=dv) == pytest.approx(0.5)

    def test_negative_lateness_clamped_to_zero(self):
        """Extraction completing BEFORE the business-day boundary clamps to 0.

        This scenario is a configuration error (DateValue tagged in the future
        relative to CompletedAt) and we don't let it depress the percentile.
        """
        from cdc.lateness_profiler import _lateness_days

        dv = date(2025, 1, 15)
        completed = _end_of_day(dv) - timedelta(hours=2)
        assert _lateness_days(completed_at=completed, business_date=dv) == 0.0


# ===========================================================================
# Percentile algorithm — known data sets with hand-computed expected values
# ===========================================================================


class TestPercentileAlgorithm:
    """Spot-check the percentile computation against hand-computed values."""

    def test_uniform_lateness_all_percentiles_equal(self):
        """If every sample has the same lateness, every percentile = that value."""
        from cdc.lateness_profiler import _compute_percentile

        samples = [1.0] * 50
        for p in (50, 90, 95, 99):
            assert _compute_percentile(samples, p) == pytest.approx(1.0), (
                f"Uniform sample set should produce uniform p{p}"
            )

    def test_p50_of_zero_to_hundred_is_median(self):
        """statistics.quantiles inclusive method: p50 of [0..100] is 50."""
        from cdc.lateness_profiler import _compute_percentile

        samples = [float(i) for i in range(101)]  # 0..100
        assert _compute_percentile(samples, 50) == pytest.approx(50.0)

    def test_p99_above_p95_above_p90_above_p50_on_skewed_data(self):
        """Right-skewed distribution should produce strictly ordered percentiles."""
        from cdc.lateness_profiler import _compute_percentile

        samples = [0.0] * 90 + [1.0] * 7 + [5.0] * 2 + [50.0]
        p50 = _compute_percentile(samples, 50)
        p90 = _compute_percentile(samples, 90)
        p95 = _compute_percentile(samples, 95)
        p99 = _compute_percentile(samples, 99)
        assert p50 <= p90 <= p95 <= p99

    def test_single_sample_returns_the_sample(self):
        """A single sample yields itself at any percentile (degenerate case)."""
        from cdc.lateness_profiler import _compute_percentile

        for p in (50, 90, 95, 99):
            assert _compute_percentile([7.5], p) == pytest.approx(7.5)

    def test_empty_samples_raises_value_error(self):
        from cdc.lateness_profiler import _compute_percentile

        with pytest.raises(ValueError):
            _compute_percentile([], 99)

    def test_percentile_matches_statistics_quantiles_inclusive(self):
        """End-to-end: _compute_percentile should equal
        statistics.quantiles(..., method='inclusive') cut-points."""
        import statistics

        from cdc.lateness_profiler import _compute_percentile

        samples = [float(i) * 0.1 for i in range(1, 51)]  # 0.1..5.0
        cuts = statistics.quantiles(samples, n=100, method="inclusive")
        assert _compute_percentile(samples, 50) == pytest.approx(cuts[49])
        assert _compute_percentile(samples, 90) == pytest.approx(cuts[89])
        assert _compute_percentile(samples, 95) == pytest.approx(cuts[94])
        assert _compute_percentile(samples, 99) == pytest.approx(cuts[98])

    def test_clustered_distribution_preserves_monotonicity(self):
        """Hypothesis-discovered counter-example: 27 zeros + 3 large
        clustered floats produce non-monotonic statistics.quantiles cuts
        (cut[95] > cut[96] by ~7e-15 / ~4 ULPs at value 29.7).

        This pins the counter-example surfaced 2026-05-15 by
        ``test_lateness_percentiles_monotonic`` (Hypothesis Tier 2 property
        test) — the production-side monotonicity-clip in
        ``_compute_percentile`` MUST yield p50 <= p90 <= p95 <= p99 even
        when the underlying ``statistics.quantiles`` violates monotonicity.

        Without the clip, this test fails (regression guard).
        Tier 1 ↔ Tier 2 feedback-loop precedent: B-262 NFC-before-Categorical-
        cast hash bug pinned via Tier 1 regression tests in
        ``tests/unit/test_hash_determinism.py`` 2026-05-14.
        """
        from cdc.lateness_profiler import _compute_percentile

        # Exact Hypothesis-shrunk counter-example from the 2026-05-15 surface
        samples = [0.0] * 27 + [29.709847256413088] * 3

        p50 = _compute_percentile(samples, 50)
        p90 = _compute_percentile(samples, 90)
        p95 = _compute_percentile(samples, 95)
        p99 = _compute_percentile(samples, 99)

        # Non-strict monotonicity invariant per docstring + § 5.6 spec
        assert p50 <= p90, f"p50={p50!r} > p90={p90!r} (clustered-distribution regression)"
        assert p90 <= p95, f"p90={p90!r} > p95={p95!r} (clustered-distribution regression)"
        assert p95 <= p99, f"p95={p95!r} > p99={p99!r} (clustered-distribution regression)"

    def test_monotonicity_clip_is_idempotent(self):
        """Running _compute_percentile twice on the same input yields
        bit-identical results (the clip is deterministic + idempotent —
        re-applying max() over already-monotonic cuts is a no-op).
        """
        from cdc.lateness_profiler import _compute_percentile

        samples = [0.0] * 27 + [29.709847256413088] * 3

        # 4 percentiles × 2 calls = 8 results; pairs must be bit-equal
        for p in (50, 90, 95, 99):
            first = _compute_percentile(samples, p)
            second = _compute_percentile(samples, p)
            assert first == second, (
                f"p{p}: first={first!r} != second={second!r} (non-deterministic clip)"
            )


# ===========================================================================
# InsufficientHistory threshold boundary
# ===========================================================================


class TestInsufficientHistoryBoundary:

    def test_exactly_min_sample_days_passes(self):
        """At sample_count == min_sample_days, the function MUST succeed
        (the threshold is inclusive — "fewer than" is strict <)."""
        from cdc.lateness_profiler import profile_lateness

        rows = _synth_rows(days_late_list=[0.5] * 30)
        cur = _make_cursor(fetchall_returns=rows)
        with patch("cdc.lateness_profiler.cursor_for", _make_cursor_for(cur)):
            report = profile_lateness(
                source_name="DNA",
                table_name="ACCT",
                min_sample_days=30,
            )
        assert report.sample_count == 30

    def test_one_below_min_sample_days_raises(self):
        from cdc.lateness_profiler import profile_lateness
        from utils.errors import InsufficientHistory

        rows = _synth_rows(days_late_list=[0.5] * 29)
        cur = _make_cursor(fetchall_returns=rows)
        with patch("cdc.lateness_profiler.cursor_for", _make_cursor_for(cur)):
            with pytest.raises(InsufficientHistory) as exc_info:
                profile_lateness(
                    source_name="DNA",
                    table_name="ACCT",
                    min_sample_days=30,
                )
        assert exc_info.value.metadata["sample_count"] == 29

    def test_zero_rows_raises_insufficient_history(self):
        from cdc.lateness_profiler import profile_lateness
        from utils.errors import InsufficientHistory

        cur = _make_cursor(fetchall_returns=[])
        with patch("cdc.lateness_profiler.cursor_for", _make_cursor_for(cur)):
            with pytest.raises(InsufficientHistory):
                profile_lateness(source_name="DNA", table_name="ACCT")

    def test_min_sample_days_override_allows_smaller_sample(self):
        """Operator can lower min_sample_days for an exploratory probe."""
        from cdc.lateness_profiler import profile_lateness

        rows = _synth_rows(days_late_list=[0.5] * 5)
        cur = _make_cursor(fetchall_returns=rows)
        with patch("cdc.lateness_profiler.cursor_for", _make_cursor_for(cur)):
            report = profile_lateness(
                source_name="DNA",
                table_name="ACCT",
                min_sample_days=5,
            )
        assert report.sample_count == 5


# ===========================================================================
# Confidence tier mapping
# ===========================================================================


class TestConfidenceTier:

    def test_high_confidence_at_100_samples(self):
        from cdc.lateness_profiler import profile_lateness

        rows = _synth_rows(days_late_list=[0.5] * 100)
        cur = _make_cursor(fetchall_returns=rows)
        with patch("cdc.lateness_profiler.cursor_for", _make_cursor_for(cur)):
            report = profile_lateness(source_name="DNA", table_name="ACCT")
        assert report.confidence == "high"
        assert report.sample_count == 100

    def test_high_confidence_above_100_samples(self):
        from cdc.lateness_profiler import profile_lateness

        rows = _synth_rows(days_late_list=[0.5] * 150)
        cur = _make_cursor(fetchall_returns=rows)
        with patch("cdc.lateness_profiler.cursor_for", _make_cursor_for(cur)):
            report = profile_lateness(source_name="DNA", table_name="ACCT")
        assert report.confidence == "high"

    def test_medium_confidence_at_30_to_99_samples(self):
        from cdc.lateness_profiler import profile_lateness

        rows = _synth_rows(days_late_list=[0.5] * 50)
        cur = _make_cursor(fetchall_returns=rows)
        with patch("cdc.lateness_profiler.cursor_for", _make_cursor_for(cur)):
            report = profile_lateness(source_name="DNA", table_name="ACCT")
        assert report.confidence == "medium"

    def test_medium_confidence_at_exactly_99(self):
        from cdc.lateness_profiler import profile_lateness

        rows = _synth_rows(days_late_list=[0.5] * 99)
        cur = _make_cursor(fetchall_returns=rows)
        with patch("cdc.lateness_profiler.cursor_for", _make_cursor_for(cur)):
            report = profile_lateness(source_name="DNA", table_name="ACCT")
        assert report.confidence == "medium"

    def test_low_confidence_via_min_sample_days_override(self):
        """sample_count < 30 (reachable only by lowering min_sample_days)."""
        from cdc.lateness_profiler import profile_lateness

        rows = _synth_rows(days_late_list=[0.5] * 10)
        cur = _make_cursor(fetchall_returns=rows)
        with patch("cdc.lateness_profiler.cursor_for", _make_cursor_for(cur)):
            report = profile_lateness(
                source_name="DNA",
                table_name="ACCT",
                min_sample_days=5,
            )
        assert report.confidence == "low"
        assert report.sample_count == 10

    def test_classify_confidence_helper_directly(self):
        """Spot-check the helper at each boundary in isolation."""
        from cdc.lateness_profiler import _classify_confidence

        assert _classify_confidence(0) == "low"
        assert _classify_confidence(29) == "low"
        assert _classify_confidence(30) == "medium"
        assert _classify_confidence(99) == "medium"
        assert _classify_confidence(100) == "high"
        assert _classify_confidence(10_000) == "high"


# ===========================================================================
# Datetime / type coercion (SCD2-P1-f invariant)
# ===========================================================================


class TestDatetimeCoercion:
    """The module returns naive ms-precision datetimes per SCD2-P1-f."""

    def test_report_as_of_is_naive_ms_precision(self):
        from cdc.lateness_profiler import profile_lateness

        rows = _synth_rows(days_late_list=[0.5] * 30)
        cur = _make_cursor(fetchall_returns=rows)
        with patch("cdc.lateness_profiler.cursor_for", _make_cursor_for(cur)):
            report = profile_lateness(source_name="DNA", table_name="ACCT")
        # Naive (no tzinfo) per SCD2-P1-f / CDC-NOW-MS.
        assert report.as_of.tzinfo is None
        # ms precision — microsecond field is a multiple of 1000.
        assert report.as_of.microsecond % 1000 == 0

    def test_tz_aware_completed_at_gets_stripped(self):
        """If pyodbc returns a tz-aware datetime, the coercion strips tzinfo."""
        from cdc.lateness_profiler import _coerce_datetime

        aware = datetime(2025, 1, 15, 14, 30, 0, 123_456, tzinfo=timezone.utc)
        coerced = _coerce_datetime(aware)
        assert coerced is not None
        assert coerced.tzinfo is None
        assert coerced.microsecond % 1000 == 0

    def test_unexpected_type_raises_extraction_state_unavailable(self):
        from cdc.lateness_profiler import _coerce_datetime
        from utils.errors import ExtractionStateUnavailable

        with pytest.raises(ExtractionStateUnavailable):
            _coerce_datetime("not-a-datetime")  # type: ignore[arg-type]

    def test_coerce_date_accepts_datetime(self):
        """pyodbc may return a DATE column as datetime; helper returns date."""
        from cdc.lateness_profiler import _coerce_date

        result = _coerce_date(datetime(2025, 1, 15, 12, 0, 0))
        assert result == date(2025, 1, 15)
        assert not isinstance(result, datetime)


# ===========================================================================
# SQL query shape — Status='SUCCESS' filter + CompletedAt IS NOT NULL filter
# ===========================================================================


class TestSqlQueryShape:
    """The SELECT query MUST filter on Status='SUCCESS' AND CompletedAt IS NOT NULL.

    These filters are the engine's protection against pulling FAILED /
    IN_PROGRESS rows or rows whose CompletedAt was never recorded; we
    verify the SQL text directly (rather than relying on the DB to filter
    correctly — the test mocks pyodbc, so the test needs to check that
    the SQL would produce the correct filter against a real DB).
    """

    def test_query_filters_status_success(self):
        from cdc.lateness_profiler import profile_lateness

        rows = _synth_rows(days_late_list=[0.5] * 30)
        cur = _make_cursor(fetchall_returns=rows)
        with patch("cdc.lateness_profiler.cursor_for", _make_cursor_for(cur)):
            profile_lateness(source_name="DNA", table_name="ACCT")
        sql = cur.execute.call_args.args[0]
        assert "Status = 'SUCCESS'" in sql or "Status='SUCCESS'" in sql

    def test_query_filters_completed_at_not_null(self):
        from cdc.lateness_profiler import profile_lateness

        rows = _synth_rows(days_late_list=[0.5] * 30)
        cur = _make_cursor(fetchall_returns=rows)
        with patch("cdc.lateness_profiler.cursor_for", _make_cursor_for(cur)):
            profile_lateness(source_name="DNA", table_name="ACCT")
        sql = cur.execute.call_args.args[0]
        assert "CompletedAt IS NOT NULL" in sql

    def test_query_filters_date_value_in_window(self):
        from cdc.lateness_profiler import profile_lateness

        rows = _synth_rows(days_late_list=[0.5] * 30)
        cur = _make_cursor(fetchall_returns=rows)
        with patch("cdc.lateness_profiler.cursor_for", _make_cursor_for(cur)):
            profile_lateness(
                source_name="DNA",
                table_name="ACCT",
                window_days=45,
            )
        sql = cur.execute.call_args.args[0]
        assert "DateValue BETWEEN" in sql
        # Bind values: source, table, window_start, window_end.
        params = cur.execute.call_args.args[1:]
        assert params[0] == "DNA"
        assert params[1] == "ACCT"
        assert (params[3] - params[2]).days == 45  # window_end - window_start

    def test_query_against_general_ops_pipelineextraction(self):
        from cdc.lateness_profiler import profile_lateness

        rows = _synth_rows(days_late_list=[0.5] * 30)
        cur = _make_cursor(fetchall_returns=rows)
        with patch("cdc.lateness_profiler.cursor_for", _make_cursor_for(cur)):
            profile_lateness(source_name="DNA", table_name="ACCT")
        sql = cur.execute.call_args.args[0]
        assert "General.ops.PipelineExtraction" in sql


# ===========================================================================
# DB connectivity failure paths
# ===========================================================================


class TestDbConnectivityFailures:

    def test_operational_error_on_execute_wraps_to_extraction_state_unavailable(self):
        from cdc import lateness_profiler as mod
        from utils.errors import ExtractionStateUnavailable, PipelineRetryableError

        @contextmanager
        def _cursor_raises_on_execute(_db):
            cur = MagicMock()
            cur.execute.side_effect = pyodbc.OperationalError("08S01", "connection lost")
            yield cur

        with patch.object(mod, "cursor_for", _cursor_raises_on_execute):
            with pytest.raises(ExtractionStateUnavailable) as exc_info:
                mod.profile_lateness(source_name="DNA", table_name="ACCT")
        assert isinstance(exc_info.value, PipelineRetryableError)
        assert exc_info.value.metadata["source_name"] == "DNA"
        assert exc_info.value.metadata["table_name"] == "ACCT"

    def test_operational_error_on_fetchall_wraps_to_extraction_state_unavailable(self):
        from cdc import lateness_profiler as mod
        from utils.errors import ExtractionStateUnavailable

        @contextmanager
        def _cursor_raises_on_fetch(_db):
            cur = MagicMock()
            cur.fetchall.side_effect = pyodbc.OperationalError("08S01", "lost mid-fetch")
            yield cur

        with patch.object(mod, "cursor_for", _cursor_raises_on_fetch):
            with pytest.raises(ExtractionStateUnavailable):
                mod.profile_lateness(source_name="DNA", table_name="ACCT")


# ===========================================================================
# Report shape
# ===========================================================================


class TestReportShape:

    def test_window_boundaries_consistent_with_window_days(self):
        from cdc.lateness_profiler import profile_lateness

        rows = _synth_rows(days_late_list=[0.5] * 30)
        cur = _make_cursor(fetchall_returns=rows)
        with patch("cdc.lateness_profiler.cursor_for", _make_cursor_for(cur)):
            report = profile_lateness(
                source_name="DNA",
                table_name="ACCT",
                window_days=60,
            )
        assert (report.window_end - report.window_start).days == 60

    def test_max_observed_days_is_integer_ceiling(self):
        """max_observed_days is reported as an integer (ceiling)."""
        from cdc.lateness_profiler import profile_lateness

        # One outlier at 4.3 days; the rest at 0.5.
        days = [0.5] * 29 + [4.3]
        rows = _synth_rows(days_late_list=days)
        cur = _make_cursor(fetchall_returns=rows)
        with patch("cdc.lateness_profiler.cursor_for", _make_cursor_for(cur)):
            report = profile_lateness(source_name="DNA", table_name="ACCT")
        assert isinstance(report.max_observed_days, int)
        assert report.max_observed_days == 5  # ceil(4.3) = 5

    def test_zero_lateness_max_observed_days_is_zero(self):
        """If every sample completed at the boundary, max = 0 (not 1 from ceil)."""
        from cdc.lateness_profiler import profile_lateness

        rows = _synth_rows(days_late_list=[0.0] * 30)
        cur = _make_cursor(fetchall_returns=rows)
        with patch("cdc.lateness_profiler.cursor_for", _make_cursor_for(cur)):
            report = profile_lateness(source_name="DNA", table_name="ACCT")
        assert report.max_observed_days == 0

    def test_report_carries_source_and_table_identity(self):
        from cdc.lateness_profiler import profile_lateness

        rows = _synth_rows(days_late_list=[0.5] * 30)
        cur = _make_cursor(fetchall_returns=rows)
        with patch("cdc.lateness_profiler.cursor_for", _make_cursor_for(cur)):
            report = profile_lateness(source_name="CCM", table_name="StatementHistory")
        assert report.source_name == "CCM"
        assert report.table_name == "StatementHistory"


# ===========================================================================
# Default parameter values
# ===========================================================================


class TestDefaults:

    def test_default_window_days_is_90(self):
        from cdc.lateness_profiler import profile_lateness

        rows = _synth_rows(days_late_list=[0.5] * 30)
        cur = _make_cursor(fetchall_returns=rows)
        with patch("cdc.lateness_profiler.cursor_for", _make_cursor_for(cur)):
            report = profile_lateness(source_name="DNA", table_name="ACCT")
        assert (report.window_end - report.window_start).days == 90

    def test_default_min_sample_days_is_30(self):
        """29 samples should fail; 30 should pass under default min."""
        from cdc.lateness_profiler import profile_lateness
        from utils.errors import InsufficientHistory

        # 29 -> fail
        rows29 = _synth_rows(days_late_list=[0.5] * 29)
        cur29 = _make_cursor(fetchall_returns=rows29)
        with patch("cdc.lateness_profiler.cursor_for", _make_cursor_for(cur29)):
            with pytest.raises(InsufficientHistory):
                profile_lateness(source_name="DNA", table_name="ACCT")

        # 30 -> pass
        rows30 = _synth_rows(days_late_list=[0.5] * 30)
        cur30 = _make_cursor(fetchall_returns=rows30)
        with patch("cdc.lateness_profiler.cursor_for", _make_cursor_for(cur30)):
            report = profile_lateness(source_name="DNA", table_name="ACCT")
            assert report.sample_count == 30


# ===========================================================================
# persist_lateness_report — optional INSERT path used by Round 4 CLI shim
# ===========================================================================


class TestPersistLatenessReport:

    def _make_report(self, **overrides):
        from cdc.lateness_profiler import LatenessReport

        defaults = dict(
            source_name="DNA",
            table_name="ACCT",
            window_start=date(2025, 1, 1),
            window_end=date(2025, 3, 31),
            sample_count=87,
            p50_days=0.2,
            p90_days=0.8,
            p95_days=1.3,
            p99_days=2.7,
            max_observed_days=5,
            confidence="medium",
        )
        defaults.update(overrides)
        return LatenessReport(**defaults)

    def test_returns_profile_id(self):
        from cdc import lateness_profiler as mod

        cur = _make_cursor(fetchone_returns=(12345,))
        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            pid = mod.persist_lateness_report(self._make_report())
        assert pid == 12345

    def test_inserts_into_general_ops_latenessprofile(self):
        from cdc import lateness_profiler as mod

        cur = _make_cursor(fetchone_returns=(1,))
        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            mod.persist_lateness_report(self._make_report())
        sql = cur.execute.call_args.args[0]
        assert "INSERT INTO General.ops.LatenessProfile" in sql
        assert "OUTPUT INSERTED.ProfileId" in sql

    def test_recommended_lookback_is_ceil_p99_times_safety_factor(self):
        from cdc import lateness_profiler as mod

        cur = _make_cursor(fetchone_returns=(1,))
        rpt = self._make_report(p99_days=2.7)
        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            mod.persist_lateness_report(rpt, safety_factor=1.5)
        params = cur.execute.call_args.args[1:]
        # SafetyFactor and RecommendedLookback are positional in the INSERT.
        # We don't pin exact positional indices (DDL is wide); we verify the
        # value is present in the parameter tuple.
        assert math.ceil(2.7 * 1.5) in params

    def test_drift_pct_computed_when_previous_p99_provided(self):
        from cdc import lateness_profiler as mod

        cur = _make_cursor(fetchone_returns=(1,))
        rpt = self._make_report(p99_days=4.0)
        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            mod.persist_lateness_report(rpt, previous_p99=2.0)
        params = cur.execute.call_args.args[1:]
        # DriftPct = (4.0 - 2.0) / 2.0 * 100 = 100.0
        assert pytest.approx(100.0) in [p for p in params if isinstance(p, float)]

    def test_drift_pct_none_when_no_previous_p99(self):
        from cdc import lateness_profiler as mod

        cur = _make_cursor(fetchone_returns=(1,))
        with patch.object(mod, "cursor_for", _make_cursor_for(cur)):
            mod.persist_lateness_report(self._make_report())
        params = cur.execute.call_args.args[1:]
        # DriftPct should be None in the parameter list.
        assert None in params

    def test_db_failure_wraps_to_extraction_state_unavailable(self):
        from cdc import lateness_profiler as mod
        from utils.errors import ExtractionStateUnavailable

        @contextmanager
        def _cursor_raises(_db):
            cur = MagicMock()
            cur.execute.side_effect = pyodbc.OperationalError("08S01", "lost")
            yield cur

        with patch.object(mod, "cursor_for", _cursor_raises):
            with pytest.raises(ExtractionStateUnavailable):
                mod.persist_lateness_report(self._make_report())
