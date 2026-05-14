"""Tier 2 property test for cdc/lateness_profiler.py percentile monotonicity.

Per phase1/05_tests.md § 5.6 (canonical, verbatim — re-read at build time
per Pitfall #9.l discipline)::

    ### § 5.6 Lateness percentile monotonicity

    ```python
    @given(samples=st.lists(st.floats(min_value=0, max_value=30), min_size=30, max_size=500))
    def test_lateness_percentiles_monotonic(samples):
        \"\"\"p50 <= p90 <= p95 <= p99 <= max for any sample distribution.\"\"\"
        report = profile_lateness_from_samples(samples)
        assert report.p50_days <= report.p90_days
        assert report.p90_days <= report.p95_days
        assert report.p95_days <= report.p99_days
        assert report.p99_days <= report.max_observed_days

§ 5.9 edge-case generators consumed:
  - Numeric: 0.0, very small (1e-9), large (30.0), repeating constants.

§ 5.10 property-test budget:
  - max_examples=200 per the default profile (matches canonical default
    for non-combinatorial-heavy modules — percentile arithmetic is a
    single-function path, not a state graph or CDC engine cycle).
  - deadline lifted to 5 seconds per example because each example
    invokes the full profile_lateness() path which builds a 30-500 row
    PipelineExtraction mock and runs statistics.quantiles().

Mock strategy
=============

M12's :func:`profile_lateness` reads from ``General.ops.PipelineExtraction``
via :func:`utils.connections.cursor_for`. Tier 2 properties test the
percentile arithmetic + monotonicity invariant — NOT the SQL layer.

We patch ``cdc.lateness_profiler.cursor_for`` with a context manager that
yields a ``MagicMock`` cursor whose ``fetchall()`` returns synthetic
``(DateValue, CompletedAt)`` rows. Each row is constructed so the per-row
lateness ``_lateness_days(completed_at=ca, business_date=dv)`` equals the
Hypothesis-generated sample exactly (subject to clamping at 0 — see
``_negative_samples_clamp_to_zero`` for that property).

Properties covered
==================

1. ``test_lateness_percentiles_monotonic`` — canonical § 5.6: p50 <= p90
   <= p95 <= p99 <= max for any sample distribution.

2. ``test_constant_samples_have_equal_percentiles`` — for samples all
   equal to a constant c, every percentile equals c. Catches off-by-one
   indexing in the inclusive-linear-interpolation algorithm.

3. ``test_negative_samples_clamp_to_zero`` — M12's ``_lateness_days``
   clamps negative deltas (CompletedAt before end-of-day) to 0 (per
   module docstring "negative values [...] are clamped to 0"). Verify
   that a sample distribution containing negative deltas produces
   non-negative percentiles.

4. ``test_outliers_increase_max_and_p99`` — appending a single very-large
   sample to a small-valued distribution must produce max_observed_days
   >= the smaller distribution's max, and p99 must also rise or stay
   equal.

5. ``test_insufficient_history_raised_below_min_sample_days`` — Hypothesis
   strategies that generate fewer than ``min_sample_days`` samples must
   raise the canonical :class:`utils.errors.InsufficientHistory` per
   B228 (canonical ``utils.errors``).

6. ``test_percentile_output_is_in_days`` — verifies the units contract:
   p99 of a 1-day-lateness sample equals 1.0 (not 86400 seconds, 24
   hours, or 1440 minutes). Static contract test — pinned input,
   pinned expected output.

D-numbers consumed
==================

- D11 (empirical L_99 lookback) — drives the LatenessReport invariants
  this test pins.
- D67 (Tier 0 smoke) — sibling tier provides import + happy-path
  smoke; this tier adds property-based monotonicity coverage.
- D68 (error hierarchy) — InsufficientHistory must be PipelineFatalError;
  test asserts the inheritance.
- D69 (cursor_for ownership) — test patches cursor_for at the
  ``cdc.lateness_profiler`` import surface (NOT
  ``utils.connections.cursor_for``) so the patch survives the lazy
  fallback import in M12.
- D81 (property-test budget per § 5.10) — max_examples=200 default.
- D92 (forward-only additive) — new test file; no existing API changed.

Closes / depends
================

- Authored under Round 5 Tier 2 property test wave (4 parallel agents).
- Depends on Agent A's ``tests/property/__init__.py`` + ``conftest.py``
  for the Hypothesis ``ci`` profile registration (per § 5.10) — this
  module uses the default profile if Agent A's conftest hasn't landed.
- Depends on **B85** transitively (uses :mod:`utils.errors` canonical
  exception classes per B228).

Spec: phase1/05_tests.md § 5.6 + § 5.9 + § 5.10.
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Mock helpers — mirror tier0/tier1 patterns so test maintenance is uniform.
# ---------------------------------------------------------------------------


def _end_of_day(d: date) -> datetime:
    """Mirror cdc.lateness_profiler._end_of_day for test arithmetic."""
    return datetime.combine(d, time(23, 59, 59, 999_000))


def _make_cursor(fetchall_returns):
    """Build a mock pyodbc cursor with a canned ``fetchall`` return."""
    cur = MagicMock()
    cur.fetchall.return_value = fetchall_returns
    return cur


def _make_cursor_for(cur):
    """Return a cursor_for-shaped context manager yielding the given cursor."""

    @contextmanager
    def _cm(_db: str):
        yield cur

    return _cm


def _synth_rows_from_samples(samples):
    """Convert a Hypothesis-generated sample list into PipelineExtraction rows.

    Each sample ``d`` produces a tuple ``(DateValue, CompletedAt)`` where
    ``CompletedAt = end_of_day(DateValue) + timedelta(days=d)``. M12's
    ``_lateness_days`` recovers the sample value modulo the 0-clamp.

    Distinct business dates are assigned per sample (today_utc - 1, -2, ...)
    so the WHERE clause filter never depends on the synthetic rows being
    inside the trailing window — the mock bypasses the SQL anyway.
    """
    base = datetime.now(timezone.utc).date() - timedelta(days=2)
    rows = []
    for i, d in enumerate(samples):
        dv = base - timedelta(days=i)
        completed = _end_of_day(dv) + timedelta(days=d)
        rows.append((dv, completed))
    return rows


def _le_or_close(a: float, b: float, *, rel_tol: float = 1e-12) -> bool:
    """Return True if ``a <= b`` or the two values are within ULP-tolerance.

    ``statistics.quantiles(..., method='inclusive')`` performs different
    float arithmetic for adjacent percentile cut-points (linear
    interpolation indices differ by 1). For samples that logically
    collapse to a single value (heavy clamping, all-constant input),
    adjacent percentiles can differ by a single ULP in the wrong
    direction. ``rel_tol=1e-12`` is generous enough to absorb 1-2 ULP
    drift on doubles up to ~30 (the strategy ceiling).
    """
    if a <= b:
        return True
    return abs(a - b) <= rel_tol * max(abs(a), abs(b), 1.0)


def _profile_from_samples(
    samples,
    *,
    source_name="DNA",
    table_name="ACCT",
    window_days=90,
    min_sample_days=30,
):
    """Drive ``profile_lateness`` with synthetic PipelineExtraction rows.

    Equivalent to a Hypothesis-driven ``profile_lateness_from_samples``
    helper per the § 5.6 spec sketch — except we exercise the full
    public-API path (matching the Tier 0 § 5.6 monotonicity smoke), not
    a private percentile function.
    """
    from cdc.lateness_profiler import profile_lateness

    rows = _synth_rows_from_samples(samples)
    cur = _make_cursor(fetchall_returns=rows)
    with patch("cdc.lateness_profiler.cursor_for", _make_cursor_for(cur)):
        return profile_lateness(
            source_name=source_name,
            table_name=table_name,
            window_days=window_days,
            min_sample_days=min_sample_days,
        )


# ---------------------------------------------------------------------------
# § 5.10 Hypothesis budget — default max_examples=200, generous deadline
# because every example invokes the full profile_lateness path.
# ---------------------------------------------------------------------------


_PROPERTY_SETTINGS = settings(
    max_examples=200,
    deadline=timedelta(seconds=5),
    # The mock cursor_for bypasses the project-wide
    # _disable_source_side_checks_by_default fixture concern; suppress
    # function-scoped fixture health-check warning for @given functions
    # since we don't depend on test-isolation fixtures.
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


# ---------------------------------------------------------------------------
# Property 1 — canonical § 5.6 monotonicity invariant
# ---------------------------------------------------------------------------


@_PROPERTY_SETTINGS
@given(
    samples=st.lists(
        st.floats(
            min_value=0.0,
            max_value=30.0,
            allow_nan=False,
            allow_infinity=False,
        ),
        min_size=30,
        max_size=500,
    )
)
def test_lateness_percentiles_monotonic(samples):
    """p50 <= p90 <= p95 <= p99 <= max for any sample distribution.

    Canonical § 5.6 invariant. The same property is asserted as a single
    smoke case in the Tier 0 test; here we sweep 200 randomly-generated
    distributions to ensure no edge case (skew, kurtosis, repetition,
    bi-modality) violates monotonicity.
    """
    report = _profile_from_samples(samples)

    assert report.p50_days <= report.p90_days, (
        f"p50={report.p50_days} > p90={report.p90_days} "
        f"with sample_count={report.sample_count}"
    )
    assert report.p90_days <= report.p95_days, (
        f"p90={report.p90_days} > p95={report.p95_days}"
    )
    assert report.p95_days <= report.p99_days, (
        f"p95={report.p95_days} > p99={report.p99_days}"
    )
    assert report.p99_days <= report.max_observed_days, (
        f"p99={report.p99_days} > max_observed_days={report.max_observed_days}"
    )


# ---------------------------------------------------------------------------
# Property 2 — constant samples ⇒ all percentiles equal the constant
# ---------------------------------------------------------------------------


@_PROPERTY_SETTINGS
@given(
    # min_value=1e-3 avoids the synthesis-precision artifact where
    # ``timedelta(days=d)`` rounds sub-microsecond constants to 0 in
    # CompletedAt, breaking the "constant => percentile == constant"
    # equivalence at the rounding boundary. 1e-3 days ~= 86 microseconds,
    # safely above pyodbc's DATETIME2(3) ms-resolution floor.
    constant=st.floats(
        min_value=1e-3,
        max_value=30.0,
        allow_nan=False,
        allow_infinity=False,
    ),
    n=st.integers(min_value=30, max_value=200),
)
def test_constant_samples_have_equal_percentiles(constant, n):
    """For samples all equal to c, every percentile equals c.

    Catches off-by-one indexing in the inclusive-linear-interpolation
    algorithm (``statistics.quantiles(..., method='inclusive')``).
    All percentile fields must equal each other (the value M12 actually
    computed from the round-tripped CompletedAt vs end_of_day(DateValue)
    delta — see ``_round_tripped_constant`` below for why we don't
    compare against the raw ``constant`` input).

    max_observed_days is the ``ceil()`` of the max sample per M12's
    docstring ("upper-bound integer for the LookbackDays arithmetic;
    ceil to honor 'at least this many days' semantics"), so it may be
    larger than the percentile values when ``constant`` is fractional.
    """
    import math

    samples = [constant] * n
    report = _profile_from_samples(samples)

    # All percentile fields equal each other (the canonical § 5.6
    # invariant collapses to equality for a constant distribution). We
    # use ``pytest.approx`` because ``statistics.quantiles`` performs
    # different float arithmetic at each percentile cut-point — values
    # may differ by a single ULP (~1e-15 relative) for the same input,
    # which is irrelevant for the operator's "days late" use case.
    assert report.p50_days == pytest.approx(report.p90_days), (
        f"p50 != p90 on constant samples: {report.p50_days} vs {report.p90_days}"
    )
    assert report.p90_days == pytest.approx(report.p95_days), (
        f"p90 != p95 on constant samples: {report.p90_days} vs {report.p95_days}"
    )
    assert report.p95_days == pytest.approx(report.p99_days), (
        f"p95 != p99 on constant samples: {report.p95_days} vs {report.p99_days}"
    )

    # The shared percentile value approximates the input constant. We
    # use ``rel=1e-6, abs=1e-6`` tolerance because the round-trip
    # through ``CompletedAt = end_of_day + timedelta(days=constant)``
    # rounds to microsecond precision per Python's ``datetime`` /
    # ``timedelta`` contract.
    assert report.p50_days == pytest.approx(constant, rel=1e-6, abs=1e-6), (
        f"Percentile {report.p50_days} != input constant {constant} "
        f"(round-trip tolerance violated)"
    )

    # max_observed_days is ceil(p99 round-tripped) per M12 docstring.
    expected_max = int(math.ceil(report.p99_days)) if report.p99_days > 0 else 0
    assert report.max_observed_days == expected_max, (
        f"max_observed_days={report.max_observed_days} != "
        f"ceil({report.p99_days})={expected_max}"
    )


# ---------------------------------------------------------------------------
# Property 3 — negative samples clamp to 0 (M12 docstring contract)
# ---------------------------------------------------------------------------


@_PROPERTY_SETTINGS
@given(
    samples=st.lists(
        st.floats(
            min_value=-30.0,
            max_value=30.0,
            allow_nan=False,
            allow_infinity=False,
        ),
        min_size=30,
        max_size=200,
    )
)
def test_negative_samples_clamp_to_zero(samples):
    """Negative samples clamp to 0 per M12 module docstring contract.

    Quote: "Negative values (extraction completed before the business
    day ended — only possible if DateValue is a future-tagged date with
    an early CompletedAt) are clamped to 0".

    Implication: every percentile + max_observed_days is >= 0 even when
    Hypothesis generates an all-negative or mostly-negative sample
    distribution. Also verifies monotonicity still holds (within ULP
    tolerance — heavy clamping creates many identical 0.0 values that
    can trigger ULP-level differences across percentile cut-points in
    ``statistics.quantiles``).
    """
    report = _profile_from_samples(samples)

    assert report.p50_days >= 0.0, f"p50={report.p50_days} (negative not clamped)"
    assert report.p90_days >= 0.0, f"p90={report.p90_days}"
    assert report.p95_days >= 0.0, f"p95={report.p95_days}"
    assert report.p99_days >= 0.0, f"p99={report.p99_days}"
    assert report.max_observed_days >= 0, (
        f"max_observed_days={report.max_observed_days} (negative not clamped)"
    )
    # Monotonicity holds across the clamp — within ULP tolerance for
    # adjacent percentiles that may collapse to the same logical value.
    assert _le_or_close(report.p50_days, report.p90_days), (
        f"p50={report.p50_days} not <= p90={report.p90_days}"
    )
    assert _le_or_close(report.p90_days, report.p95_days), (
        f"p90={report.p90_days} not <= p95={report.p95_days}"
    )
    assert _le_or_close(report.p95_days, report.p99_days), (
        f"p95={report.p95_days} not <= p99={report.p99_days}"
    )
    assert _le_or_close(report.p99_days, float(report.max_observed_days)), (
        f"p99={report.p99_days} not <= max_observed_days={report.max_observed_days}"
    )


# ---------------------------------------------------------------------------
# Property 4 — outliers strictly raise the max + p99 (or leave equal)
# ---------------------------------------------------------------------------


@_PROPERTY_SETTINGS
@given(
    base_samples=st.lists(
        st.floats(
            min_value=0.0,
            max_value=2.0,
            allow_nan=False,
            allow_infinity=False,
        ),
        min_size=30,
        max_size=200,
    ),
    outlier=st.floats(
        min_value=10.0,
        max_value=30.0,
        allow_nan=False,
        allow_infinity=False,
    ),
)
def test_outliers_increase_max_and_p99(base_samples, outlier):
    """Appending an outlier >= base_max must raise (or hold) max and p99.

    Specifically: if the outlier is larger than every base sample, then
    ``max_observed_days`` and ``p99_days`` from the augmented set must
    each be >= the corresponding value from the base set.

    Catches percentile algorithms that incorrectly "average away" tail
    outliers (a common bug when interpolation indices are computed
    against the un-augmented sample count instead of the augmented).
    """
    # Sanity — Hypothesis guaranteed outlier >= 10 > base_max (<= 2).
    base_report = _profile_from_samples(base_samples)
    augmented = base_samples + [outlier]
    augmented_report = _profile_from_samples(augmented)

    assert augmented_report.max_observed_days >= base_report.max_observed_days, (
        f"Outlier {outlier} lowered max: "
        f"base={base_report.max_observed_days} "
        f"-> augmented={augmented_report.max_observed_days}"
    )
    assert augmented_report.p99_days >= base_report.p99_days, (
        f"Outlier {outlier} lowered p99: "
        f"base={base_report.p99_days} -> augmented={augmented_report.p99_days}"
    )


# ---------------------------------------------------------------------------
# Property 5 — fewer than min_sample_days raises InsufficientHistory
# ---------------------------------------------------------------------------


@_PROPERTY_SETTINGS
@given(
    samples=st.lists(
        st.floats(
            min_value=0.0,
            max_value=30.0,
            allow_nan=False,
            allow_infinity=False,
        ),
        min_size=0,
        max_size=29,  # Strictly below the default min_sample_days=30
    )
)
def test_insufficient_history_raised_below_min_sample_days(samples):
    """Samples below ``min_sample_days`` (default 30) raise
    :class:`utils.errors.InsufficientHistory`.

    Per B228: the test uses the canonical exception from ``utils.errors``
    (not a per-module copy or a generic Exception class).

    Per D68: InsufficientHistory must inherit from PipelineFatalError
    (CLI exit code 2; no retry).
    """
    from utils.errors import InsufficientHistory, PipelineFatalError

    with pytest.raises(InsufficientHistory) as exc_info:
        _profile_from_samples(samples)

    # D68 — must be a PipelineFatalError.
    assert isinstance(exc_info.value, PipelineFatalError)
    # Metadata carries the sample_count + threshold for operator audit.
    assert exc_info.value.metadata.get("sample_count") == len(samples)
    assert exc_info.value.metadata.get("min_sample_days") == 30


# ---------------------------------------------------------------------------
# Property 6 — percentile output is in DAYS (units contract)
# ---------------------------------------------------------------------------


def test_percentile_output_is_in_days():
    """LatenessReport percentile fields are in DAYS (not seconds / minutes
    / hours).

    Static contract test (not @given) — pinned input, pinned expected
    output. Verifies M12's units contract per the module docstring:
    "All percentile fields are days (fractional) of lateness after the
    business-day boundary."

    A 1-day-late distribution must yield p99 = 1.0 (not 86400 for
    seconds, 1440 for minutes, 24 for hours). Catches future regressions
    where someone "fixes" the lateness arithmetic to return a different
    unit without updating the report contract.
    """
    samples = [1.0] * 50  # 50 samples all exactly 1 day late
    report = _profile_from_samples(samples)

    # p99 of fifty 1-day-late samples = 1.0 (in days).
    assert report.p99_days == pytest.approx(1.0), (
        f"Expected p99=1.0 days; got {report.p99_days}. "
        "If this is 86400, units are seconds. If 1440, minutes. "
        "If 24, hours. M12 contract is DAYS."
    )
    # All percentiles for the constant distribution equal 1.0 days.
    assert report.p50_days == pytest.approx(1.0)
    assert report.p90_days == pytest.approx(1.0)
    assert report.p95_days == pytest.approx(1.0)
    # max_observed_days is ceil(max), which for 1.0 is 1.
    assert report.max_observed_days == 1
