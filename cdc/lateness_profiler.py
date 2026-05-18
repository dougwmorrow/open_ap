"""Empirical L_99 lateness profiler per Round 3 § 5.2.

This module measures the historical (business_date → first_observed_in_pipeline)
lag distribution for a ``(SourceName, TableName)`` pair, returning percentile
statistics that drive the ``UdmTablesList.LookbackDays`` operator-set
configuration (per D11 — empirical L_99 lookback).

Canonical DDLs (per ``phase1/01_database_schema.md`` § 3 + § 10 — re-read at
build time per Pitfall #9.l discipline)::

    CREATE TABLE General.ops.PipelineExtraction (
        ExtractionId         BIGINT IDENTITY(1,1) NOT NULL,
        BatchId              BIGINT          NOT NULL,
        SourceName           NVARCHAR(50)    NOT NULL,
        TableName            NVARCHAR(255)   NOT NULL,
        DateValue            DATE            NOT NULL,
        Status               NVARCHAR(20)    NOT NULL DEFAULT 'IN_PROGRESS',
        StartedAt            DATETIME2(3)    NOT NULL,
        CompletedAt          DATETIME2(3)    NULL,
        EvaluatedAt          DATETIME2(3)    NOT NULL DEFAULT SYSUTCDATETIME(),
        RowsExtracted        BIGINT          NULL,
        IsReExtraction       BIT             NOT NULL DEFAULT 0,
        ExtractionAttempt    INT             NOT NULL DEFAULT 1,
        FailureReason        NVARCHAR(MAX)   NULL,
        CONSTRAINT PK_PipelineExtraction PRIMARY KEY CLUSTERED (ExtractionId),
        CONSTRAINT CK_PipelineExtraction_Status CHECK
            (Status IN ('IN_PROGRESS', 'SUCCESS', 'FAILED'))
    );

    CREATE TABLE General.ops.LatenessProfile (
        ProfileId          BIGINT IDENTITY(1,1) NOT NULL,
        SourceName         NVARCHAR(50)    NOT NULL,
        TableName          NVARCHAR(255)   NOT NULL,
        MeasuredAt         DATETIME2(3)    NOT NULL DEFAULT SYSUTCDATETIME(),
        MeasurementWindowDays INT          NOT NULL,
        BusinessDateColumn NVARCHAR(255)   NOT NULL,
        LastModifiedColumn NVARCHAR(255)   NOT NULL,
        LatenessP50        DECIMAL(10,2)   NULL,
        LatenessP90        DECIMAL(10,2)   NULL,
        LatenessP95        DECIMAL(10,2)   NULL,
        LatenessP99        DECIMAL(10,2)   NULL,
        LatenessP999       DECIMAL(10,2)   NULL,
        LatenessMax        DECIMAL(10,2)   NULL,
        RecommendedLookback INT            NULL,
        SafetyFactor        DECIMAL(5,2)   NOT NULL DEFAULT 1.5,
        CurrentConfiguredLookback INT      NULL,
        PreviousP99         DECIMAL(10,2)  NULL,
        DriftPct            DECIMAL(5,2)   NULL,
        SampleRowCount      BIGINT         NOT NULL,
        CONSTRAINT PK_LatenessProfile PRIMARY KEY CLUSTERED (ProfileId)
    );

Lateness definition (per § 5.2)
===============================

For each ``Status='SUCCESS'`` row within the trailing ``window_days``, the
sample's lateness in days is::

    lateness_days = (CompletedAt - end_of_business_day(DateValue)) / 86400 seconds

Where ``end_of_business_day(DateValue) = DateValue at 23:59:59.999 UTC``. This
encodes "how many days after the business day's calendar boundary did the
pipeline complete the extraction?" — the value drives ``LookbackDays`` setting
(operator: ``LookbackDays = ceil(p99) + safety_margin``).

A lateness sample of 0.5 means the extraction completed 12 hours after the
business day ended; 1.0 means a full day late; 2.7 means almost three days.
Negative values (extraction completed before the business day ended — only
possible if ``DateValue`` is a future-tagged date with an early ``CompletedAt``)
are clamped to 0 — that scenario is a configuration error, not a real
lateness sample, and we don't let it depress the percentile.

Percentile algorithm
====================

We use ``statistics.quantiles(samples, n=100, method='inclusive')`` (NumPy /
Python stdlib match for inclusive linear interpolation, identical to NumPy's
``np.percentile(..., method='linear')``). The inclusive method is the standard
"empirical distribution function" interpolation — for sample size N, the
i-th of N samples sits at quantile ``i/(N-1)``. This is the convention used
by NumPy, R's type=7, and most spreadsheet ``PERCENTILE.INC`` functions.

Choice rationale: percentile semantics need to be stable + reproducible
across operator workstations; ``statistics.quantiles`` is pure-stdlib (no
NumPy build dependency on RHEL), deterministic, and matches the convention
operators expect from Excel + R.

Confidence tier mapping
=======================

The ``confidence`` field on :class:`LatenessReport` is a soft signal for the
operator:

- ``'high'`` — ``sample_count >= 100``. The 99th percentile of >= 100 samples
  is statistically meaningful (at p99, ~1% of samples sit above the headline
  number; 100 samples ⇒ ≥1 sample defines the tail).
- ``'medium'`` — ``30 <= sample_count < 100``. Sufficient to compute a p99
  but the tail is sparsely populated; operators should re-run with a wider
  window before locking ``LookbackDays``.
- ``'low'`` — ``sample_count < 30``. Reserved for the ``min_sample_days``
  override path (default ``min_sample_days=30`` raises
  :class:`InsufficientHistory` before this code path runs; operators who
  explicitly lower the threshold get the ``'low'`` confidence tag).

The :class:`InsufficientHistory` short-circuit prevents accidental
``'low'`` confidence reports under the default contract.

Error classes (per D68)
=======================

- :class:`InsufficientHistory` (``PipelineFatalError``) — fewer SUCCESS rows
  than ``min_sample_days`` in the window. Operator can override ``min_sample_days``
  for an exploratory probe.
- :class:`ExtractionStateUnavailable` (``PipelineRetryableError``) — transient
  DB-connection failure during the query. Retryable per B-7.

Concurrency (per D69)
=====================

- Stateless; ``cursor_for('General')`` acquired per call from the per-database
  connection pool (Item-18).
- Multi-call safe — same inputs produce the same ``LatenessReport``
  (deterministic; no side effects in :func:`profile_lateness`).
- The optional :func:`persist_lateness_report` writer appends a row to
  ``General.ops.LatenessProfile``; concurrent persisters produce multiple
  rows (intentional per § 3.3 — trend tracking).

D-numbers consumed
==================

D11 (empirical L_99 lookback), D67 (Tier 0 smoke), D68 (error class hierarchy),
D69 (cursor_for ownership), D92 (forward-only additive — new module).

B-numbers
=========

- Closes **B-244** (M12 ``cdc/lateness_profiler.py`` build).
- Depends on **B85** via the ``utils.errors`` import surface.
"""

from __future__ import annotations

import logging
import math
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import pyodbc

try:
    from utils.connections import cursor_for
except ImportError:
    # Fallback for legacy callers that placed ``connections`` at project root.
    from connections import cursor_for  # type: ignore[no-redef]

from utils.errors import (
    ExtractionStateUnavailable,
    InsufficientHistory,
)

logger = logging.getLogger(__name__)

__all__ = [
    "LatenessReport",
    "profile_lateness",
    "persist_lateness_report",
]


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LatenessReport:
    """Empirical lateness percentile report per § 5.2.

    Returned by :func:`profile_lateness`. All percentile fields are days
    (fractional) of lateness after the business-day boundary.

    :param source_name: e.g. ``'DNA'``, ``'CCM'``, ``'EPICOR'``.
    :param table_name: source object name (e.g. ``'ACCT'``).
    :param window_start: inclusive lower bound of the historical window
        (``today_utc - window_days``).
    :param window_end: inclusive upper bound (``today_utc``).
    :param sample_count: count of ``Status='SUCCESS'`` rows in the window.
    :param p50_days: 50th-percentile lateness in days (median).
    :param p90_days: 90th-percentile lateness in days.
    :param p95_days: 95th-percentile lateness in days.
    :param p99_days: 99th-percentile lateness in days — the **headline**
        number. ``UdmTablesList.LookbackDays`` should be set to
        ``ceil(p99_days) + safety_margin`` (operator-tuned).
    :param max_observed_days: maximum observed lateness in days (int — the
        canonical DDL declares ``LatenessMax`` semantically as an upper
        bound, and we round up to the nearest whole day per the
        ``MeasurementWindowDays`` integer convention).
    :param confidence: ``'high'`` / ``'medium'`` / ``'low'`` per the
        sample-count tiers documented in the module docstring.
    :param as_of: timestamp the report was computed (naive UTC ms per
        SCD2-P1-f / CDC-NOW-MS — the same invariant ``PipelineExtraction``
        rows are stored under).
    """

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
    confidence: str = field(default="medium")
    as_of: datetime = field(default_factory=lambda: _utcnow_ms())


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _utcnow_ms() -> datetime:
    """Naive UTC datetime truncated to milliseconds.

    Matches SCD2-P1-f / CDC-NOW-MS invariant — naive (tzinfo stripped),
    ms precision. Required for any parameter-bound comparison against
    ``DATETIME2(3)`` columns to avoid the implicit ``DATETIMEOFFSET``
    timezone conversion that SQL Server performs on a non-UTC server.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return now.replace(microsecond=(now.microsecond // 1000) * 1000)


def _utc_today() -> date:
    """UTC calendar date (naive). Boundary for the historical window."""
    return datetime.now(timezone.utc).date()


def _validate_identity(source_name: str, table_name: str) -> None:
    """Reject empty / wrong-type identity inputs at the function boundary."""
    if not source_name or not isinstance(source_name, str):
        raise ExtractionStateUnavailable(
            "source_name must be a non-empty string",
            metadata={"source_name_repr": repr(source_name)},
        )
    if not table_name or not isinstance(table_name, str):
        raise ExtractionStateUnavailable(
            "table_name must be a non-empty string",
            metadata={"table_name_repr": repr(table_name)},
        )


def _validate_window(window_days: int, min_sample_days: int) -> None:
    """Reject pathological window / threshold inputs."""
    if not isinstance(window_days, int) or window_days <= 0:
        raise ExtractionStateUnavailable(
            f"window_days must be a positive integer (received {window_days!r})",
            metadata={"window_days_repr": repr(window_days)},
        )
    if not isinstance(min_sample_days, int) or min_sample_days < 0:
        raise ExtractionStateUnavailable(
            "min_sample_days must be a non-negative integer "
            f"(received {min_sample_days!r})",
            metadata={"min_sample_days_repr": repr(min_sample_days)},
        )
    if min_sample_days > window_days:
        # The threshold cannot meaningfully exceed the window — the only
        # samples that can exist live inside the window.
        raise ExtractionStateUnavailable(
            f"min_sample_days ({min_sample_days}) must not exceed "
            f"window_days ({window_days})",
            metadata={
                "min_sample_days": min_sample_days,
                "window_days": window_days,
            },
        )


def _coerce_datetime(value: Any) -> datetime | None:
    """Coerce a pyodbc-returned cell to a naive ms-precision ``datetime``."""
    if value is None:
        return None
    if isinstance(value, datetime):
        naive = value.replace(tzinfo=None) if value.tzinfo is not None else value
        return naive.replace(microsecond=(naive.microsecond // 1000) * 1000)
    raise ExtractionStateUnavailable(
        f"Unexpected datetime-column value type {type(value).__name__!r} "
        "from PipelineExtraction.CompletedAt",
        metadata={"value_repr": repr(value)},
    )


def _coerce_date(value: Any) -> date | None:
    """Coerce a pyodbc-returned cell to ``date | None``."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise ExtractionStateUnavailable(
        f"Unexpected date-column value type {type(value).__name__!r} "
        "from PipelineExtraction.DateValue",
        metadata={"value_repr": repr(value)},
    )


def _end_of_day(business_date: date) -> datetime:
    """Return the end-of-day boundary for a business-day calendar date.

    ``2025-01-15`` -> ``2025-01-15 23:59:59.999`` (naive, ms precision).
    Lateness samples are ``CompletedAt - end_of_day(DateValue)``.
    """
    return datetime.combine(business_date, time(23, 59, 59, 999_000))


def _lateness_days(
    *,
    completed_at: datetime,
    business_date: date,
) -> float:
    """Compute lateness in days for one PipelineExtraction sample.

    Negative values (extraction completed before the business-day boundary)
    are clamped to 0 — that scenario is a configuration error rather than a
    real lateness sample, and including it would silently depress the
    percentile.
    """
    delta = completed_at - _end_of_day(business_date)
    days = delta.total_seconds() / 86_400.0
    return max(0.0, days)


def _classify_confidence(sample_count: int) -> str:
    """Map sample count → confidence tier per module docstring.

    - ``sample_count >= 100`` → ``'high'``
    - ``30 <= sample_count < 100`` → ``'medium'``
    - ``sample_count < 30`` → ``'low'`` (reached only via ``min_sample_days``
      override)
    """
    if sample_count >= 100:
        return "high"
    if sample_count >= 30:
        return "medium"
    return "low"


def _compute_percentile(samples: list[float], percentile: float) -> float:
    """Compute a percentile from a list of floats using inclusive linear
    interpolation (matches NumPy ``np.percentile(..., method='linear')``).

    Uses ``statistics.quantiles(samples, n=100, method='inclusive')`` which
    returns the 99 cut-points dividing the data into 100 quantiles. The
    p-th percentile is the (p-1)-th cut-point (0-indexed).

    Monotonicity invariant: ``statistics.quantiles()`` can produce
    non-monotonic cuts when the input distribution clusters tightly
    (multiple samples within a few ULPs of each other) due to floating-
    point arithmetic order. Empirically observed at sample distributions
    like ``[0.0]*27 + [29.7...]*3`` where cut[95] > cut[96] by ~7e-15
    (~4 ULPs at value 29.7). The monotonicity-clip below enforces
    ``cuts[i] >= cuts[i-1]`` so downstream LatenessReport invariants
    (``p50 <= p90 <= p95 <= p99``) hold under any input distribution.

    The clip is conservative — it pins each cut to the running max,
    which IS the correct semantics for non-decreasing percentiles
    (a higher quantile cannot mathematically be lower than a lower
    quantile in a sorted distribution). The "drift" comes from FP
    arithmetic, not from the underlying mathematics.

    :param samples: non-empty list of float lateness samples.
    :param percentile: one of ``50``, ``90``, ``95``, ``99``.
    """
    if not samples:
        raise ValueError("samples list must be non-empty for percentile computation")

    # Special-case: a single sample is the value itself at every percentile.
    if len(samples) == 1:
        return float(samples[0])

    # statistics.quantiles requires at least 2 samples.
    cuts = statistics.quantiles(samples, n=100, method="inclusive")
    # cuts has 99 elements: cuts[0] = p1, cuts[49] = p50, cuts[98] = p99.

    # Monotonicity-clip: enforce cuts[i] >= cuts[i-1] to defend against
    # FP precision violations in statistics.quantiles. See docstring above
    # for empirical evidence + rationale. Mutates the local list in place;
    # statistics.quantiles returns a fresh list each call so no shared
    # state risk.
    for i in range(1, len(cuts)):
        if cuts[i] < cuts[i - 1]:
            cuts[i] = cuts[i - 1]

    idx = int(percentile) - 1
    if idx < 0 or idx >= len(cuts):
        raise ValueError(
            f"percentile {percentile} must yield an index in [0, {len(cuts) - 1}]"
        )
    return float(cuts[idx])


def _fetch_lateness_samples(
    *,
    source_name: str,
    table_name: str,
    window_start: date,
    window_end: date,
) -> list[tuple[date, datetime]]:
    """Pull ``(DateValue, CompletedAt)`` pairs from PipelineExtraction.

    Filters: ``Status='SUCCESS'`` and ``CompletedAt IS NOT NULL`` and
    ``DateValue BETWEEN window_start AND window_end``. Each row contributes
    one lateness sample.

    Wraps DB failures in :class:`ExtractionStateUnavailable` per D68.
    """
    try:
        with cursor_for("General") as cur:
            cur.execute(
                """
                SELECT DateValue, CompletedAt
                FROM General.ops.PipelineExtraction
                WHERE SourceName = ?
                  AND TableName = ?
                  AND Status = 'SUCCESS'
                  AND CompletedAt IS NOT NULL
                  AND DateValue BETWEEN ? AND ?
                """,
                source_name,
                table_name,
                window_start,
                window_end,
            )
            rows = cur.fetchall()
    except pyodbc.OperationalError as exc:
        raise ExtractionStateUnavailable(
            "Connection failure during PipelineExtraction lateness lookup",
            metadata={
                "source_name": source_name,
                "table_name": table_name,
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
            },
        ) from exc

    samples: list[tuple[date, datetime]] = []
    for raw_date, raw_completed_at in rows:
        dv = _coerce_date(raw_date)
        ca = _coerce_datetime(raw_completed_at)
        if dv is None or ca is None:
            # Filter excludes NULL CompletedAt already; this is defense in
            # depth against driver / type-coercion surprises.
            continue
        samples.append((dv, ca))
    return samples


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def profile_lateness(
    *,
    source_name: str,
    table_name: str,
    window_days: int = 90,
    min_sample_days: int = 30,
) -> LatenessReport:
    """Compute empirical lateness percentiles per § 5.2.

    Reads ``General.ops.PipelineExtraction`` for ``Status='SUCCESS'`` rows
    in the trailing ``window_days`` and returns p50 / p90 / p95 / p99 + max
    lateness in days. The p99 value drives ``UdmTablesList.LookbackDays``
    setting per D11.

    Operator usage::

        LookbackDays = ceil(report.p99_days) + safety_margin   # typically + 1

    :param source_name: e.g. ``'DNA'``, ``'CCM'``, ``'EPICOR'``.
    :param table_name: source object name (e.g. ``'ACCT'``).
    :param window_days: trailing historical window in days. Default 90.
    :param min_sample_days: minimum required SUCCESS-row count before the
        percentiles are computed. Default 30. Below this threshold
        :class:`InsufficientHistory` is raised — percentiles are unstable
        with fewer than ~30 samples. Operator can override to a lower
        threshold for one-off probes (the report's ``confidence`` field
        downgrades to ``'low'``).

    :returns: :class:`LatenessReport` with percentile statistics.

    :raises InsufficientHistory: fewer than ``min_sample_days`` SUCCESS rows
        in the window. ``PipelineFatalError`` per D68.
    :raises ExtractionStateUnavailable: transient DB-connection failure.
        ``PipelineRetryableError`` per D68 (retry per B-7).
    """
    _validate_identity(source_name, table_name)
    _validate_window(window_days, min_sample_days)

    window_end = _utc_today()
    window_start = window_end - timedelta(days=window_days)

    raw_samples = _fetch_lateness_samples(
        source_name=source_name,
        table_name=table_name,
        window_start=window_start,
        window_end=window_end,
    )
    sample_count = len(raw_samples)

    if sample_count < min_sample_days:
        raise InsufficientHistory(
            f"profile_lateness({source_name}/{table_name}) requires "
            f">= {min_sample_days} SUCCESS rows in the last {window_days} "
            f"days; found {sample_count}",
            metadata={
                "source_name": source_name,
                "table_name": table_name,
                "window_days": window_days,
                "min_sample_days": min_sample_days,
                "sample_count": sample_count,
                "window_start": window_start.isoformat(),
                "window_end": window_end.isoformat(),
            },
        )

    lateness_samples: list[float] = [
        _lateness_days(completed_at=ca, business_date=dv)
        for dv, ca in raw_samples
    ]

    p50 = _compute_percentile(lateness_samples, 50)
    p90 = _compute_percentile(lateness_samples, 90)
    p95 = _compute_percentile(lateness_samples, 95)
    p99 = _compute_percentile(lateness_samples, 99)
    max_observed = max(lateness_samples)
    # max_observed_days reports an upper-bound integer for the LookbackDays
    # arithmetic; ceil to honor "at least this many days" semantics.
    max_observed_days = int(math.ceil(max_observed)) if max_observed > 0 else 0

    confidence = _classify_confidence(sample_count)

    report = LatenessReport(
        source_name=source_name,
        table_name=table_name,
        window_start=window_start,
        window_end=window_end,
        sample_count=sample_count,
        p50_days=p50,
        p90_days=p90,
        p95_days=p95,
        p99_days=p99,
        max_observed_days=max_observed_days,
        confidence=confidence,
        as_of=_utcnow_ms(),
    )

    logger.info(
        "profile_lateness(%s/%s, window=%d) -> samples=%d p50=%.2f p90=%.2f "
        "p95=%.2f p99=%.2f max=%d confidence=%s",
        source_name, table_name, window_days, sample_count,
        p50, p90, p95, p99, max_observed_days, confidence,
    )
    return report


def persist_lateness_report(
    report: LatenessReport,
    *,
    business_date_column: str = "",
    last_modified_column: str = "",
    safety_factor: float = 1.5,
    current_configured_lookback: int | None = None,
    previous_p99: float | None = None,
) -> int:
    """Optional INSERT of a :class:`LatenessReport` into ``General.ops.LatenessProfile``.

    Called by the Round 4 § 3.3 CLI shim (``tools/lateness_profile.py``)
    when ``--persist`` is enabled; the canonical module function
    :func:`profile_lateness` does NOT persist — keeping it read-only per
    the § 5.2 idempotency claim.

    :param report: the report to persist (computed by
        :func:`profile_lateness`).
    :param business_date_column: ``UdmTablesList.SourceAggregateColumnName``
        for the table (logged for trend context). Empty string acceptable if
        the caller doesn't have the metadata handy.
    :param last_modified_column: ``UdmTablesList.LastModifiedColumn`` for
        the table (logged for trend context). Empty string acceptable.
    :param safety_factor: multiplier applied to p99 to derive the
        recommended ``LookbackDays``. Default 1.5 per § 10 DDL default.
    :param current_configured_lookback: current
        ``UdmTablesList.LookbackDays`` for the table — populates the
        ``CurrentConfiguredLookback`` column for at-write drift visibility.
    :param previous_p99: optional prior-run p99 value — populates the
        ``PreviousP99`` column + computes ``DriftPct`` for trend tracking.

    :returns: the new ``ProfileId`` (``BIGINT IDENTITY``).
    :raises ExtractionStateUnavailable: transient DB-connection failure.
    """
    recommended_lookback = int(math.ceil(report.p99_days * safety_factor))
    drift_pct: float | None = None
    if previous_p99 is not None and previous_p99 != 0.0:
        drift_pct = ((report.p99_days - previous_p99) / previous_p99) * 100.0

    try:
        with cursor_for("General") as cur:
            cur.execute(
                """
                INSERT INTO General.ops.LatenessProfile (
                    SourceName, TableName, MeasuredAt,
                    MeasurementWindowDays, BusinessDateColumn, LastModifiedColumn,
                    LatenessP50, LatenessP90, LatenessP95, LatenessP99,
                    LatenessP999, LatenessMax,
                    RecommendedLookback, SafetyFactor,
                    CurrentConfiguredLookback,
                    PreviousP99, DriftPct,
                    SampleRowCount
                )
                OUTPUT INSERTED.ProfileId
                VALUES (
                    ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?,
                    ?, ?,
                    ?,
                    ?, ?,
                    ?
                )
                """,
                report.source_name,
                report.table_name,
                report.as_of,
                (report.window_end - report.window_start).days,
                business_date_column,
                last_modified_column,
                report.p50_days,
                report.p90_days,
                report.p95_days,
                report.p99_days,
                None,
                float(report.max_observed_days),
                recommended_lookback,
                safety_factor,
                current_configured_lookback,
                previous_p99,
                drift_pct,
                report.sample_count,
            )
            row = cur.fetchone()
    except pyodbc.OperationalError as exc:
        raise ExtractionStateUnavailable(
            "Connection failure during LatenessProfile INSERT",
            metadata={
                "source_name": report.source_name,
                "table_name": report.table_name,
            },
        ) from exc

    if row is None or row[0] is None:
        raise ExtractionStateUnavailable(
            "INSERT...OUTPUT returned no ProfileId for LatenessProfile row",
            metadata={
                "source_name": report.source_name,
                "table_name": report.table_name,
            },
        )
    return int(row[0])
