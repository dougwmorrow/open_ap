"""Tier 0 build-time smoke test for cdc/lateness_profiler.py.

Per D67 — runs at build time + every commit. Runtime ceiling < 5 s. All
external dependencies (pyodbc cursor, ``utils.connections.cursor_for``)
are mocked. No live SQL Server required.

6 D67-canonical assertions:
  (a) Module imports without error + public surface present.
  (b) profile_lateness returns LatenessReport on happy-path mocked data.
  (c) LatenessReport is a frozen dataclass with the documented fields.
  (d) Percentiles preserve monotonic ordering: p50 <= p90 <= p95 <= p99
      <= max_observed_days (the same property the CLI shim asserts in
      stdout per § 3.3 Tier 1).
  (e) InsufficientHistory raised on fewer than min_sample_days SUCCESS rows.
  (f) ExtractionStateUnavailable raised on transient DB-connection failure.

North Star pillars:
  - Operationally stable (D67 Tier 0 discipline: import + invocability +
    happy-path + failure-path in < 5 s with zero external I/O).
  - Audit-grade (error classes consume utils.errors canonical types per
    D68 — InsufficientHistory is PipelineFatalError,
    ExtractionStateUnavailable is PipelineRetryableError).
  - Traceability (LatenessReport carries window_start/window_end/sample_count
    so operators can trace which historical window produced the headline p99).

D-numbers: D11 (empirical L_99), D67 (Tier 0), D68 (error hierarchy),
D69 (cursor_for ownership), D92 (forward-only additive).

B-numbers: B-244 (M12 lateness_profiler build).

Spec: phase1/03_core_modules.md § 5.2 + phase1/01_database_schema.md § 3 + § 10.
"""
from __future__ import annotations

import sys
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pyodbc
import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Shared fixtures — mock cursor_for context manager
# ---------------------------------------------------------------------------


def _make_cursor(fetchall_returns=None) -> MagicMock:
    """Build a mock pyodbc cursor with a canned ``fetchall`` return."""
    cur = MagicMock()
    cur.fetchall.return_value = fetchall_returns or []
    return cur


def _make_cursor_for(cur: MagicMock):
    """Return a cursor_for-shaped context manager yielding the given cursor."""

    @contextmanager
    def _cm(_db: str):
        yield cur

    return _cm


def _synth_rows(*, days_late_list: list[float], base_date: date | None = None) -> list[tuple[date, datetime]]:
    """Build canned PipelineExtraction rows with the given lateness profile.

    Each entry produces a (DateValue, CompletedAt) tuple where CompletedAt
    is exactly ``end_of_day(DateValue) + days_late`` so the test pins the
    expected lateness value.
    """
    base = base_date or (datetime.now(timezone.utc).date() - timedelta(days=10))
    rows: list[tuple[date, datetime]] = []
    for i, d in enumerate(days_late_list):
        dv = base - timedelta(days=i)
        # end_of_day(dv) + d days
        completed = datetime.combine(dv, datetime.min.time()).replace(
            hour=23, minute=59, second=59, microsecond=999_000
        ) + timedelta(days=d)
        rows.append((dv, completed))
    return rows


# ---------------------------------------------------------------------------
# (a) Module imports without error + public surface present
# ---------------------------------------------------------------------------


def test_module_imports_and_exposes_public_api():
    """(a) cdc.lateness_profiler imports cleanly per D67 assertion 1.

    Asserts the canonical public surface from § 5.2 + the optional
    persistence helper used by the Round 4 CLI shim.
    """
    import cdc.lateness_profiler as mod

    assert mod is not None
    assert hasattr(mod, "profile_lateness"), "Canonical § 5.2 function"
    assert hasattr(mod, "LatenessReport"), "Canonical § 5.2 dataclass"
    assert hasattr(mod, "persist_lateness_report"), (
        "Optional persistence helper per § 5.2 'Produces' clause"
    )


# ---------------------------------------------------------------------------
# (b) profile_lateness returns LatenessReport on happy-path mocked data
# ---------------------------------------------------------------------------


def test_profile_lateness_happy_path_returns_report():
    """(b) profile_lateness returns a LatenessReport with the documented fields.

    Mocks PipelineExtraction to return 30 SUCCESS rows with varied
    lateness; verifies the report shape + sample_count.
    """
    from cdc.lateness_profiler import LatenessReport, profile_lateness

    # 30 samples (exactly at min_sample_days threshold) with simple distribution
    rows = _synth_rows(days_late_list=[float(i % 5) for i in range(30)])
    cur = _make_cursor(fetchall_returns=rows)

    with patch("cdc.lateness_profiler.cursor_for", _make_cursor_for(cur)):
        report = profile_lateness(
            source_name="DNA",
            table_name="ACCT",
            window_days=90,
            min_sample_days=30,
        )

    assert isinstance(report, LatenessReport)
    assert report.source_name == "DNA"
    assert report.table_name == "ACCT"
    assert report.sample_count == 30
    # Confidence at exactly 30 samples is 'medium' per docstring tiers.
    assert report.confidence == "medium"


# ---------------------------------------------------------------------------
# (c) LatenessReport is a frozen dataclass with the documented fields
# ---------------------------------------------------------------------------


def test_lateness_report_dataclass_shape():
    """(c) LatenessReport is a frozen dataclass with the canonical fields."""
    from dataclasses import FrozenInstanceError

    from cdc.lateness_profiler import LatenessReport

    report = LatenessReport(
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
    assert report.source_name == "DNA"
    assert report.p99_days == 2.7
    assert report.max_observed_days == 5
    assert report.confidence == "medium"

    # Frozen: cannot reassign.
    with pytest.raises(FrozenInstanceError):
        report.p99_days = 99.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# (d) Percentiles preserve monotonic ordering
# ---------------------------------------------------------------------------


def test_profile_lateness_percentile_monotonic_ordering():
    """(d) p50 <= p90 <= p95 <= p99 <= max_observed_days for any sample set.

    Matches the § 3.3 Tier 1 invariant the CLI shim asserts in stdout.
    Uses 100 samples with a deliberately skewed distribution.
    """
    from cdc.lateness_profiler import profile_lateness

    # 100 samples; mostly 0-2 days, a few outliers at 5+ days.
    days_late = [0.5] * 80 + [2.0] * 15 + [5.0] * 4 + [10.0]
    rows = _synth_rows(days_late_list=days_late)
    cur = _make_cursor(fetchall_returns=rows)

    with patch("cdc.lateness_profiler.cursor_for", _make_cursor_for(cur)):
        r = profile_lateness(source_name="DNA", table_name="ACCT")

    assert r.p50_days <= r.p90_days <= r.p95_days <= r.p99_days, (
        f"Percentile monotonicity violated: "
        f"p50={r.p50_days} p90={r.p90_days} p95={r.p95_days} p99={r.p99_days}"
    )
    assert r.p99_days <= r.max_observed_days, (
        f"p99 ({r.p99_days}) must be <= max_observed_days ({r.max_observed_days})"
    )


# ---------------------------------------------------------------------------
# (e) InsufficientHistory raised on fewer than min_sample_days
# ---------------------------------------------------------------------------


def test_insufficient_history_raised_below_threshold():
    """(e) profile_lateness raises InsufficientHistory when sample_count
    is below min_sample_days (default 30).

    Per § 5.2 + D68 — fatal error, no retry; operator either waits for
    more data OR explicitly lowers min_sample_days.
    """
    from cdc.lateness_profiler import profile_lateness
    from utils.errors import InsufficientHistory, PipelineFatalError

    # Only 5 rows — far below the 30-row default threshold.
    rows = _synth_rows(days_late_list=[0.5, 1.0, 1.5, 2.0, 0.8])
    cur = _make_cursor(fetchall_returns=rows)

    with patch("cdc.lateness_profiler.cursor_for", _make_cursor_for(cur)):
        with pytest.raises(InsufficientHistory) as exc_info:
            profile_lateness(source_name="DNA", table_name="ACCT")

    # InsufficientHistory is a PipelineFatalError per D68.
    assert isinstance(exc_info.value, PipelineFatalError)
    # Error metadata names the source / table / sample_count / threshold.
    assert exc_info.value.metadata.get("sample_count") == 5
    assert exc_info.value.metadata.get("min_sample_days") == 30


# ---------------------------------------------------------------------------
# (f) ExtractionStateUnavailable raised on transient DB-connection failure
# ---------------------------------------------------------------------------


def test_extraction_state_unavailable_on_db_connection_failure():
    """(f) profile_lateness wraps pyodbc.OperationalError in
    ExtractionStateUnavailable per D68 (PipelineRetryableError).

    Transient connectivity failures must be retryable per B-7; surfacing
    as PipelineFatalError would prevent retry. Mocks cursor_for to raise
    pyodbc.OperationalError on the lateness query.
    """
    from cdc import lateness_profiler as mod
    from utils.errors import ExtractionStateUnavailable, PipelineRetryableError

    @contextmanager
    def _cursor_raises(_db):
        cur = MagicMock()
        cur.execute.side_effect = pyodbc.OperationalError("08S01", "connection lost")
        yield cur

    with patch.object(mod, "cursor_for", _cursor_raises):
        with pytest.raises(ExtractionStateUnavailable) as exc_info:
            mod.profile_lateness(source_name="DNA", table_name="ACCT")

    assert isinstance(exc_info.value, PipelineRetryableError)
