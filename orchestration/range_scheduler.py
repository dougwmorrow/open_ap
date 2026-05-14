"""Date-range scheduler for large-table windowed extraction per Round 3 § 5.1.

This module plans the ordered list of business dates a pipeline run will
extract for a (source, table) pair. It is the bridge between Round 2
configuration (``UdmTablesList.FirstLoadDate`` + ``LookbackDays``), Round 1
state (``General.ops.ExtractionRangePolicy`` per D12 + ``PipelineExtraction``
via ``cdc.extraction_state``), and the orchestration layer that drives
``orchestration/large_tables.py``.

Two scheduling modes
====================

1. **Policy mode** — when one or more ``Active=1`` rows exist in
   ``ExtractionRangePolicy`` for the (source, table), every row contributes
   a closed date range ``[RangeStartDate, RangeEndDate]`` to the union.
   ``NULL`` on either bound is interpreted as "today" (``as_of_date``).
   This is the explicit / D12 path — closer to Netflix Maestro / Uber Hudi
   incremental-job scheduling than fixed lookback.

2. **Default-lookback mode** — when no ``ExtractionRangePolicy`` rows exist
   AND ``UdmTablesList.LookbackDays`` is populated, the schedule is a
   rolling window ``[as_of_date - LookbackDays + 1, as_of_date]`` clipped
   to ``[FirstLoadDate, as_of_date]``. Bit-for-bit equivalent to
   pre-D12 behavior for tables not yet migrated to the policy table.

If NEITHER an explicit policy row NOR ``LookbackDays`` is configured the
caller has not yet finished configuring the table — :class:`RangePolicyMissing`
fires per § 5.1 error-modes contract.

Canonical DDL (per ``phase1/01_database_schema.md`` § 9 — re-read at build
time per Pitfall #9.l discipline)::

    CREATE TABLE General.ops.ExtractionRangePolicy (
        RangeId            BIGINT IDENTITY(1,1) NOT NULL,
        SourceName         NVARCHAR(50)    NOT NULL,
        TableName          NVARCHAR(255)   NOT NULL,
        RangeStartDate     DATE            NULL,        -- NULL = "today"
        RangeEndDate       DATE            NULL,        -- NULL = "today"
        RangeKind          NVARCHAR(20)    NOT NULL,    -- 'current' / 'lookback'
                                                        -- / 'backfill' / 'reconciliation'
        MaxStaleDays       INT             NOT NULL,
        Priority           INT             NOT NULL DEFAULT 50,
        LastExtractedAt    DATETIME2(3)    NULL,
        LastSuccessAt      DATETIME2(3)    NULL,
        Active             BIT             NOT NULL DEFAULT 1,
        Notes              NVARCHAR(MAX)   NULL,
        CreatedAt          DATETIME2(3)    NOT NULL DEFAULT SYSUTCDATETIME(),
        UpdatedAt          DATETIME2(3)    NOT NULL DEFAULT SYSUTCDATETIME(),
        CONSTRAINT PK_ExtractionRangePolicy PRIMARY KEY CLUSTERED (RangeId),
        CONSTRAINT CK_ExtractionRangePolicy_Kind CHECK
            (RangeKind IN ('current', 'lookback', 'backfill', 'reconciliation'))
    );
    CREATE INDEX IX_ExtractionRangePolicy_Table
        ON General.ops.ExtractionRangePolicy
        (SourceName, TableName, Active);

The ``IX_ExtractionRangePolicy_Table`` index satisfies the per-table policy
lookup directly.

Re-extraction flag derivation (D14)
===================================

Every planned date is tagged ``is_reextraction = True`` iff
``cdc.extraction_state.most_recent_success`` returns a date ``>=`` that
planned date — equivalent to "the pipeline has previously recorded a
SUCCESS for the same calendar day or later, so this is a re-extraction
rather than a first pass." Concretely: the very first date that has not
yet been extracted is the only date with ``is_reextraction = False`` for
fresh runs; on subsequent runs with lookback windows reaching back into
prior SUCCESS dates the older dates carry the flag.

This is a planner-side approximation of the canonical D14 flag set by
``cdc.extraction_state.record_extraction_attempt`` at INSERT time
(which uses ``ExtractionAttempt > 1``). The two converge once the
extraction actually runs; the planner's flag is purely informational for
operators previewing a plan.

Idempotency contract
====================

Pure function. Calling :func:`plan_extraction_range` multiple times with
the same inputs returns the same :class:`ExtractionPlan` content (modulo
the ``as_of_date`` default which uses today UTC — pass an explicit
``as_of_date`` for bit-identical determinism). No writes; no DB mutation.

Error modes (per D68)
=====================

- :class:`RangePolicyMissing` (``PipelineFatalError``) — neither a row in
  ``UdmTablesList`` (table not registered) NOR an active row in
  ``ExtractionRangePolicy`` (no explicit policy) AND ``LookbackDays`` is
  ``NULL``. Operator must INSERT either a ``LookbackDays`` value or an
  ``ExtractionRangePolicy`` row before the scheduler can plan.

- :class:`ExtractionStateUnavailable` (``PipelineRetryableError``) —
  transient DB connectivity failure during any of the three lookups
  (``UdmTablesList`` / ``ExtractionRangePolicy`` / ``most_recent_success``
  via :mod:`cdc.extraction_state`). Retryable per B-7.

Concurrency (per D69)
=====================

- Stateless; multi-worker safe.
- ``cursor_for('General')`` acquired per call from the per-database
  connection pool (Item-18).
- All datetimes (none currently surfaced, but any future client-side
  ``LastSuccessAt`` parameter bind) follow the SCD2-P1-f / CDC-NOW-MS
  invariant — naive ms-precision UTC wall time.

D-numbers consumed
==================

D11 (empirical L_99 lookback — informs ``LookbackDays`` choice but the
scheduler is agnostic to how the value was derived), D12
(``ExtractionRangePolicy`` infrastructure), D14
(``IsReExtraction`` / ``ExtractionAttempt`` semantics), D67 (Tier 0),
D68 (error class hierarchy), D69 (cursor_for ownership), D92
(forward-only additive; new module — predecessor logic in
``orchestration/pipeline_state.get_dates_to_process`` left in place).

B-numbers
=========

- Closes (dependent on) **B85** via the ``utils.errors`` import surface
  (consumes :class:`RangePolicyMissing` + :class:`ExtractionStateUnavailable`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pyodbc

try:
    from utils.connections import cursor_for
except ImportError:
    # Fallback for legacy callers that placed ``connections`` at project root.
    from connections import cursor_for  # type: ignore[no-redef]

from cdc.extraction_state import most_recent_success
from utils.errors import (
    ExtractionStateUnavailable,
    RangePolicyMissing,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ExtractionPlan",
    "plan_extraction_range",
]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


# Hard cap on the number of dates returned in a single plan. The default
# lookback path is unlikely to exceed a few hundred (L_99 ~ 30 typical);
# the policy path could in principle enumerate years of history if a
# backfill range is unbounded. Cap defends downstream orchestration
# against accidentally extracting decades when a configuration mistake
# leaves ``RangeStartDate`` as ``DATE '1970-01-01'``.
#
# Caller can override via the ``max_dates`` parameter; the default
# matches the largest currently-configured lookback window (CARDTXN at
# 90 days × buffer) with comfortable headroom.
_DEFAULT_MAX_DATES = 3650  # ~10 years; effectively unbounded for realistic configs

# Policy source identifiers (stamped on the ExtractionPlan for audit).
_POLICY_SOURCE_EXPLICIT = "ExtractionRangePolicy"
_POLICY_SOURCE_LOOKBACK = "default-lookback"


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExtractionPlan:
    """Output of :func:`plan_extraction_range`.

    Field-to-spec mapping per § 5.1 interface:

    :param source_name: ``UdmTablesList.SourceName`` (e.g. ``'DNA'``).
    :param table_name: ``UdmTablesList.SourceObjectName`` (e.g. ``'ACCT'``).
    :param dates: ordered ascending (oldest first) per § 5.1. Empty list
        is a valid plan ("nothing to extract; everything is already up to
        date or no scheduled ranges overlap today").
    :param re_extraction_flags: per-date ``IsReExtraction`` value
        composed from ``cdc.extraction_state.most_recent_success`` —
        ``True`` iff a prior SUCCESS exists on or after the planned
        date. The dict's keys are exactly the dates in ``dates``.
    :param policy_source: ``'ExtractionRangePolicy'`` if at least one
        active policy row drove the plan; ``'default-lookback'`` if the
        plan came from ``UdmTablesList.LookbackDays``.
    """

    source_name: str
    table_name: str
    dates: list[date]
    re_extraction_flags: dict[date, bool]
    policy_source: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _utc_today() -> date:
    """UTC calendar date (naive). Default ``as_of_date`` boundary."""
    return datetime.now(timezone.utc).date()


def _coerce_date(value: Any) -> date | None:
    """Coerce a pyodbc-returned cell to ``date | None``.

    pyodbc may return a ``DATE`` column as either ``datetime.date`` or
    ``datetime.datetime`` depending on driver / connection settings;
    callers always want ``date``.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise ExtractionStateUnavailable(
        f"Unexpected date-column value type {type(value).__name__!r} "
        "from ExtractionRangePolicy / UdmTablesList lookup",
        metadata={"value_repr": repr(value)},
    )


def _validate_inputs(
    source_name: str,
    table_name: str,
    as_of_date: date,
) -> None:
    """Reject empty / wrong-type inputs at the function boundary."""
    if not source_name or not isinstance(source_name, str):
        raise RangePolicyMissing(
            "source_name must be a non-empty string",
            metadata={"source_name_repr": repr(source_name)},
        )
    if not table_name or not isinstance(table_name, str):
        raise RangePolicyMissing(
            "table_name must be a non-empty string",
            metadata={"table_name_repr": repr(table_name)},
        )
    if not isinstance(as_of_date, date) or isinstance(as_of_date, datetime):
        # ``datetime`` IS a subclass of ``date``; we want pure ``date`` only.
        raise RangePolicyMissing(
            "as_of_date must be a datetime.date (received "
            f"{type(as_of_date).__name__})",
            metadata={"as_of_date_repr": repr(as_of_date)},
        )


def _lookup_udm_tables_config(
    *,
    source_name: str,
    table_name: str,
) -> tuple[date | None, int | None] | None:
    """Resolve ``UdmTablesList.FirstLoadDate`` + ``LookbackDays``.

    Keyed on ``SourceName`` + ``SourceObjectName`` per Round 2 § 1.1.
    Returns ``None`` if the row is missing entirely (table not
    registered in ``UdmTablesList``); otherwise returns
    ``(first_load_date, lookback_days)`` where either component may be
    ``None`` independently.

    Wraps DB failures in :class:`ExtractionStateUnavailable` per D68.
    """
    try:
        with cursor_for("General") as cur:
            cur.execute(
                """
                SELECT FirstLoadDate, LookbackDays
                FROM dbo.UdmTablesList
                WHERE SourceName = ? AND SourceObjectName = ?
                """,
                source_name,
                table_name,
            )
            row = cur.fetchone()
    except pyodbc.OperationalError as exc:
        raise ExtractionStateUnavailable(
            "Connection failure during UdmTablesList lookup for "
            "range_scheduler",
            metadata={
                "source_name": source_name,
                "table_name": table_name,
            },
        ) from exc
    if row is None:
        return None
    first_load = _coerce_date(row[0])
    lookback_days = int(row[1]) if row[1] is not None else None
    return (first_load, lookback_days)


def _lookup_active_policy_ranges(
    *,
    source_name: str,
    table_name: str,
) -> list[tuple[date | None, date | None]]:
    """Return the active ``[start, end]`` ranges for the (source, table).

    Each tuple is ``(RangeStartDate, RangeEndDate)`` — either bound may
    be ``None`` to mean "today" per the DDL contract. Empty list when no
    active rows exist.

    Wraps DB failures in :class:`ExtractionStateUnavailable` per D68.
    """
    try:
        with cursor_for("General") as cur:
            cur.execute(
                """
                SELECT RangeStartDate, RangeEndDate
                FROM General.ops.ExtractionRangePolicy
                WHERE SourceName = ?
                  AND TableName = ?
                  AND Active = 1
                """,
                source_name,
                table_name,
            )
            rows = cur.fetchall()
    except pyodbc.OperationalError as exc:
        raise ExtractionStateUnavailable(
            "Connection failure during ExtractionRangePolicy lookup",
            metadata={
                "source_name": source_name,
                "table_name": table_name,
            },
        ) from exc

    ranges: list[tuple[date | None, date | None]] = []
    for row in rows:
        start = _coerce_date(row[0])
        end = _coerce_date(row[1])
        ranges.append((start, end))
    return ranges


def _expand_range(
    *,
    start: date,
    end: date,
    floor: date | None,
    ceiling: date,
    max_dates: int,
) -> list[date]:
    """Expand ``[start, end]`` inclusive into a list of dates, clipped to
    ``[floor, ceiling]``.

    Returns an empty list if ``start > end`` after clipping. Hard-caps the
    expansion at ``max_dates`` to defend against unbounded ranges from
    misconfigured ``RangeStartDate=DATE '1970-01-01'`` rows.
    """
    effective_start = start
    if floor is not None and effective_start < floor:
        effective_start = floor
    effective_end = end
    if effective_end > ceiling:
        effective_end = ceiling

    if effective_start > effective_end:
        return []

    days = (effective_end - effective_start).days + 1
    if days > max_dates:
        logger.warning(
            "_expand_range: range [%s, %s] expanded to %d dates exceeds "
            "max_dates=%d; truncating to most recent %d dates "
            "(operator should review ExtractionRangePolicy configuration)",
            effective_start.isoformat(), effective_end.isoformat(),
            days, max_dates, max_dates,
        )
        # Keep the most recent N dates (truncate from the OLD end). The
        # operator likely cares about freshness, not 10-year backfills.
        effective_start = effective_end - timedelta(days=max_dates - 1)
        days = max_dates

    return [effective_start + timedelta(days=i) for i in range(days)]


def _compose_reextraction_flags(
    *,
    source_name: str,
    table_name: str,
    dates: list[date],
) -> dict[date, bool]:
    """For each date in ``dates``, return ``True`` iff a prior SUCCESS
    exists on or after that date.

    Single ``most_recent_success`` lookup; flag derivation is local.
    """
    if not dates:
        return {}

    prior_max = most_recent_success(
        source_name=source_name,
        table_name=table_name,
    )
    if prior_max is None:
        return {d: False for d in dates}

    return {d: d <= prior_max for d in dates}


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------


def plan_extraction_range(
    *,
    source_name: str,
    table_name: str,
    as_of_date: date | None = None,
    max_dates: int = _DEFAULT_MAX_DATES,
) -> ExtractionPlan:
    """Plan the ordered list of business dates this run will extract.

    Composes ``UdmTablesList.FirstLoadDate`` + ``LookbackDays`` with
    ``General.ops.ExtractionRangePolicy`` rows (per D12) and the
    most-recent successful extraction (per ``cdc.extraction_state``) to
    produce a :class:`ExtractionPlan` whose ``dates`` are ordered
    ascending and per-date ``is_reextraction`` flags compose with
    :func:`cdc.extraction_state.is_reextraction` semantics.

    Two scheduling modes (see module docstring for full semantics):

    1. **Policy mode** — any ``Active=1`` row in
       ``ExtractionRangePolicy`` for the table; ranges are unioned and
       clipped to ``[FirstLoadDate, as_of_date]``.

    2. **Default-lookback mode** — fallback when no policy rows exist;
       rolling window ``[as_of_date - LookbackDays + 1, as_of_date]``
       clipped to ``FirstLoadDate``.

    :param source_name: e.g. ``'DNA'``, ``'CCM'``, ``'EPICOR'`` —
        ``UdmTablesList.SourceName``.
    :param table_name: source object name (e.g. ``'ACCT'``) —
        ``UdmTablesList.SourceObjectName``.
    :param as_of_date: planning boundary; default is today UTC. The
        rolling lookback window and any ``NULL`` policy bound resolve
        to this date.
    :param max_dates: safety cap on expanded date count per range
        (default 3650 ~= 10 years). Truncates to the most-recent
        ``max_dates`` when exceeded; logs a WARNING.

    :returns: :class:`ExtractionPlan` with ordered dates + per-date
        ``is_reextraction`` flags. Empty ``dates`` is valid (nothing
        scheduled today).

    :raises RangePolicyMissing: neither an active policy row NOR a
        ``LookbackDays`` value is configured for this table — operator
        must INSERT either before the scheduler can plan.
    :raises ExtractionStateUnavailable: transient DB connectivity
        failure during any of the three lookups. Retryable per B-7.
    """
    resolved_as_of = as_of_date if as_of_date is not None else _utc_today()
    _validate_inputs(source_name, table_name, resolved_as_of)

    if not isinstance(max_dates, int) or max_dates < 1:
        raise RangePolicyMissing(
            f"max_dates must be a positive integer (received {max_dates!r})",
            metadata={"max_dates": max_dates},
        )

    # ---- Step 1: resolve UdmTablesList for FirstLoadDate + LookbackDays.
    udm_config = _lookup_udm_tables_config(
        source_name=source_name,
        table_name=table_name,
    )
    first_load_date: date | None = None
    lookback_days: int | None = None
    udm_row_present = udm_config is not None
    if udm_row_present:
        first_load_date, lookback_days = udm_config  # type: ignore[misc]

    # ---- Step 2: resolve any active ExtractionRangePolicy rows.
    policy_ranges = _lookup_active_policy_ranges(
        source_name=source_name,
        table_name=table_name,
    )

    # ---- Step 3: branch on policy vs default-lookback vs unconfigured.
    dates: list[date]
    policy_source: str

    if policy_ranges:
        # Policy mode — expand every range, union, dedupe, sort.
        all_dates: set[date] = set()
        for start, end in policy_ranges:
            effective_start = start if start is not None else resolved_as_of
            effective_end = end if end is not None else resolved_as_of
            # The DDL allows start > end if mis-entered; _expand_range
            # handles that by returning an empty list. No raise here —
            # the operator just authored a no-op range row.
            all_dates.update(
                _expand_range(
                    start=effective_start,
                    end=effective_end,
                    floor=first_load_date,
                    ceiling=resolved_as_of,
                    max_dates=max_dates,
                )
            )
        dates = sorted(all_dates)
        policy_source = _POLICY_SOURCE_EXPLICIT
        logger.debug(
            "plan_extraction_range(%s/%s): policy mode produced %d dates "
            "from %d active range(s)",
            source_name, table_name, len(dates), len(policy_ranges),
        )
    elif udm_row_present and lookback_days is not None and lookback_days >= 1:
        # Default-lookback mode — rolling window from as_of_date.
        window_start = resolved_as_of - timedelta(days=lookback_days - 1)
        dates = _expand_range(
            start=window_start,
            end=resolved_as_of,
            floor=first_load_date,
            ceiling=resolved_as_of,
            max_dates=max_dates,
        )
        policy_source = _POLICY_SOURCE_LOOKBACK
        logger.debug(
            "plan_extraction_range(%s/%s): default-lookback produced %d "
            "dates (LookbackDays=%d, FirstLoadDate=%s)",
            source_name, table_name, len(dates), lookback_days,
            first_load_date.isoformat() if first_load_date else "NULL",
        )
    else:
        # Neither a policy row nor a usable LookbackDays — operator must
        # configure one or the other.
        reason = (
            "UdmTablesList row missing"
            if not udm_row_present
            else "LookbackDays is NULL or non-positive"
        )
        raise RangePolicyMissing(
            f"No ExtractionRangePolicy row AND no usable LookbackDays "
            f"for {source_name}.{table_name} ({reason}). Operator must "
            f"INSERT a policy row OR set UdmTablesList.LookbackDays.",
            metadata={
                "source_name": source_name,
                "table_name": table_name,
                "udm_row_present": udm_row_present,
                "lookback_days": lookback_days,
                "active_policy_count": 0,
                "reason": reason,
            },
        )

    # ---- Step 4: compose per-date IsReExtraction flags.
    flags = _compose_reextraction_flags(
        source_name=source_name,
        table_name=table_name,
        dates=dates,
    )

    plan = ExtractionPlan(
        source_name=source_name,
        table_name=table_name,
        dates=dates,
        re_extraction_flags=flags,
        policy_source=policy_source,
    )
    logger.info(
        "plan_extraction_range(%s/%s) -> %d dates [%s..%s] via %s",
        source_name, table_name, len(dates),
        dates[0].isoformat() if dates else "(empty)",
        dates[-1].isoformat() if dates else "(empty)",
        policy_source,
    )
    return plan
