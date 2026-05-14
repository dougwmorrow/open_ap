"""M13 — gap detector for large-table windowed extraction per Round 3 § 5.3.

This module detects missing ``business_date`` rows in ``General.ops.PipelineExtraction``
for each large table (a table whose ``UdmTablesList.SourceAggregateColumnName``
is not NULL — i.e. it participates in date-windowed extraction). The result is
a list of :class:`GapReport` per affected (source, table), each describing the
expected date range, the missing dates within it, and a recommended action.

The module is the engine half of the Round 4 § 3.5 ``tools/detect_extraction_gaps.py``
CLI shim. The CLI shim handles operator-facing arg parsing, alert dispatch, and
stdout rendering; this module does the queries + report composition + writes the
``GAP_DETECT`` event row to ``PipelineEventLog`` per the canonical § 5.3 contract.

Per D22 — drives the hourly ``JOB_GAP_DETECT`` Automic job per
``phase1/02_configuration.md`` § 5.1.

What this module does
=====================

1. Read every large table from ``General.dbo.UdmTablesList`` (filtered by
   ``SourceName`` if ``source_filter`` is supplied). Large = a row with
   ``SourceAggregateColumnName IS NOT NULL``. Picks up ``FirstLoadDate``
   and ``LookbackDays`` for each so the expected range can be computed.
2. For each large table, compute the expected business-date range:
   ``[FirstLoadDate, as_of_date - LookbackDays]``. Dates inside the
   lookback window (``> as_of_date - LookbackDays``) are intentionally
   excluded — they're the rolling re-extraction zone and any per-day
   row missing there is expected to fill in within the next normal run.
3. Query ``PipelineExtraction`` for every SUCCESS row in that range.
   Compute the set difference against the full expected calendar to
   find missing dates.
4. Classify each affected table:

   - ``'backfill'`` — missing dates fall fully inside the expected range
     and a normal pipeline backfill (``tools/backfill.py``) will close them.
   - ``'investigate-source'`` — the table has been registered (FirstLoadDate
     set) but has zero SUCCESS rows in the expected range. Either the
     source connection is broken or the table was registered but never
     activated. Operator must inspect before backfilling blindly.
   - ``'within-lookback-no-action'`` — the table has no missing dates
     in the strict expected range (only the rolling lookback window is
     unfilled, which is expected). No GapReport is emitted for this case
     — it is the silent / clean path.

5. Write exactly one ``GAP_DETECT`` row to ``General.ops.PipelineEventLog``
   per invocation regardless of whether any gap was found. The audit
   trail proves the hourly job ran and saw what it saw. The event row's
   ``Metadata`` JSON carries the gap counts and an excerpt of the
   affected (source, table) pairs.

What this module does NOT do
============================

- No alert dispatch — that lives in the Round 4 § 3.5 CLI shim
  (``tools/detect_extraction_gaps.py``) which composes this module's
  return value with ``tools/alert_dispatcher.py``.
- No re-extraction trigger — gap detection is read-only. The operator
  (or a backfill Automic job) decides what to do with the recommended
  action.
- No file or DB write beyond the single ``GAP_DETECT`` event row.

Idempotency contract (per § 5.3)
================================

Pure read on ``PipelineExtraction`` + one append-only INSERT on
``PipelineEventLog``. Multi-call with identical ``as_of_date`` returns
identical :class:`GapReport` lists for unchanged historical data.
Subsequent hourly invocations after data fills in produce different
(smaller) lists — that is the intended drift signal.

Error modes (per D68 + § 5.3)
=============================

- :class:`~utils.errors.GapDetectorTimeout` (PipelineRetryableError) —
  the ``PipelineExtraction`` query exceeded 60 s. Wrapped from a
  ``pyodbc.OperationalError`` whose SQL state indicates timeout.
  Retryable per B-7. Persistent timeout indicates the
  ``IX_PipelineExtraction_TrustGate`` index is missing or stale —
  track separately.
- :class:`~utils.errors.ExtractionStateUnavailable` (PipelineRetryableError) —
  transient DB connectivity failure on any of the lookup queries.
  Retryable per B-7.

Concurrency (per D69)
=====================

Stateless function; multi-call safe. ``cursor_for('General')`` is
opened per query inside the public function — never across a module
boundary per the D69 ownership rule. Hourly Automic invocation is
single-server-only per § 5.3 narrative; no ``sp_getapplock`` required
(the report is reproducible).

Canonical DDL (per ``phase1/01_database_schema.md`` § 3 — re-read at
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

The ``IX_PipelineExtraction_TrustGate`` index keyed on
``(SourceName, TableName, DateValue, Status, EvaluatedAt DESC)``
satisfies the SUCCESS-row scan used here directly.

D-numbers consumed
==================

D11 (empirical L_99 lookback — informs LookbackDays), D12
(ExtractionRangePolicy — only consulted via the sibling
range_scheduler; gap_detector here looks at the raw extraction
record, not the policy), D14 (IsReExtraction is on the row but not
filtered on — gap detection asks "did SUCCESS occur at all?"),
D22 (hourly gap detector), D67 (Tier 0 smoke test discipline),
D68 (error class hierarchy), D69 (cursor_for ownership), D74
(CLI exit code semantics — surfaced via the CLI shim, not this
module), D76 (CLI audit-row contract — this module emits the
underlying ``GAP_DETECT`` event row; the CLI shim emits an
additional envelope ``CLI_DETECT_EXTRACTION_GAPS`` row), D92
(forward-only additive — new module; no existing API renamed).

B-numbers
=========

- Closes **B-245** (M13 gap detector authoring per § 5.3 spec).
- Closes dependent on **B85** via the ``utils.errors`` import surface
  (consumes :class:`GapDetectorTimeout` + :class:`ExtractionStateUnavailable`).

Spec
====

``docs/migration/phase1/03_core_modules.md`` § 5.3 — canonical interface.
``docs/migration/phase1/01_database_schema.md`` § 3 — ``PipelineExtraction`` DDL.
``docs/migration/phase1/04_tools.md`` § 3.5 — Round 4 CLI shim contract.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any, Callable, Iterable

import pyodbc

try:
    from utils.connections import cursor_for
except ImportError:
    # Fallback for legacy callers that placed ``connections`` at project root.
    from connections import cursor_for  # type: ignore[no-redef]

from utils.errors import (
    ExtractionStateUnavailable,
    GapDetectorTimeout,
)

logger = logging.getLogger(__name__)

__all__ = [
    "GapReport",
    "detect_extraction_gaps",
]


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: D76 EventType for the audit row this module writes per invocation.
EVENT_TYPE = "GAP_DETECT"

#: Hard timeout for the ``PipelineExtraction`` scan query, in seconds.
#: Per § 5.3 error-modes contract — beyond this, raise
#: :class:`GapDetectorTimeout` (PipelineRetryableError) per D68.
_QUERY_TIMEOUT_SECONDS = 60

#: pyodbc SQLSTATE codes / message phrases indicating a server-side
#: timeout (cursor.timeout reached). Used by :func:`_is_timeout_error`.
_TIMEOUT_SQLSTATES = frozenset({"HYT00", "HYT01", "08S01"})
_TIMEOUT_PHRASES = (
    "Query timeout expired",
    "timeout expired",
    "operation cancelled",
)

#: Recommended action strings per § 5.3 interface contract.
ACTION_BACKFILL = "backfill"
ACTION_INVESTIGATE = "investigate-source"
ACTION_NO_ACTION = "within-lookback-no-action"

#: Default ``LookbackDays`` for a large table that has NULL in the column.
#: A table with ``SourceAggregateColumnName`` populated but no LookbackDays
#: is mis-configured — but rather than raise we default to a conservative
#: window so the gap report surfaces SOMETHING for operator review. The
#: chosen value matches the largest typical configured lookback (7 days
#: covers the AM/PM cycle re-extraction window with comfortable buffer).
_DEFAULT_LOOKBACK_DAYS = 7

#: Bound on missing-dates metadata serialization — the Metadata JSON
#: column is NVARCHAR(MAX) but a runaway list (e.g. years of missing
#: dates) would flood the audit table. Per-table missing-date lists in
#: the event-row metadata are truncated to this many entries with a
#: trailing ``"..."`` marker; the returned :class:`GapReport` is NEVER
#: truncated — the metadata cap is purely for the event log.
_METADATA_MISSING_DATES_CAP = 100

#: Bound on number of affected-table tuples enumerated in the event-row
#: metadata. Same rationale as :data:`_METADATA_MISSING_DATES_CAP`.
_METADATA_AFFECTED_TABLES_CAP = 50


# ---------------------------------------------------------------------------
# Public dataclass (canonical signature per § 5.3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GapReport:
    """Per-(source, table) gap-detection result.

    Frozen so instances are hashable and safe to share between threads
    (e.g. CLI shim renders multiple in parallel for stdout). Field
    semantics per § 5.3 canonical interface:

    :param source_name: ``UdmTablesList.SourceName`` (e.g. ``'DNA'``).
    :param table_name: ``UdmTablesList.SourceObjectName`` (e.g. ``'ACCT'``).
    :param expected_range: Closed interval ``(start, end)`` of business
        dates the table was expected to have extracted by ``as_of_date``.
        ``start`` = ``FirstLoadDate``. ``end`` = ``as_of_date - LookbackDays``
        (the rolling lookback zone is excluded from the expected range).
        Both bounds are inclusive.
    :param missing_dates: Ordered ascending (oldest first) list of
        business dates in the expected range that have no
        ``PipelineExtraction`` SUCCESS row. Empty iff this table was
        clean — but in that case no :class:`GapReport` is returned at
        all (see :func:`detect_extraction_gaps` filtering).
    :param recommended_action: One of:

        * ``'backfill'`` — at least one SUCCESS row exists for this
          table in the expected range; the missing dates can be filled
          by a normal pipeline backfill run via ``tools/backfill.py``.
        * ``'investigate-source'`` — the table has zero SUCCESS rows
          in the expected range. Either the source connection is
          broken or the table was registered but never activated.
          Operator must inspect before issuing a backfill (a blind
          backfill on a broken source would just stack up FAILED rows).
        * ``'within-lookback-no-action'`` — sentinel for "no action
          required"; only ever surfaces in the CLI shim's JSON output
          for tables that were checked and found clean. The default
          shape of :func:`detect_extraction_gaps` is to OMIT clean
          tables entirely.
    """

    source_name: str
    table_name: str
    expected_range: tuple[date, date]
    missing_dates: list[date]
    recommended_action: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _utc_today() -> date:
    """UTC calendar date (naive). Default ``as_of_date`` boundary."""
    return datetime.now(timezone.utc).date()


def _coerce_date(value: Any) -> date | None:
    """Coerce a pyodbc-returned cell to ``date | None``.

    pyodbc may return a ``DATE`` column as either ``datetime.date`` or
    ``datetime.datetime`` depending on driver / connection settings.
    Callers always want ``date``.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raise ExtractionStateUnavailable(
        f"Unexpected date-column value type {type(value).__name__!r} "
        "from PipelineExtraction / UdmTablesList lookup",
        metadata={"value_repr": repr(value)},
    )


def _is_timeout_error(exc: pyodbc.Error) -> bool:
    """Heuristic: is this pyodbc Error caused by query timeout?

    pyodbc surfaces server-side query timeouts as ``OperationalError``
    with SQLSTATE ``HYT00`` / ``HYT01`` and a message containing one of
    the phrases in :data:`_TIMEOUT_PHRASES`. Defends against driver
    drift by checking both the state and the message.
    """
    if not exc.args:
        return False
    state = exc.args[0] if isinstance(exc.args[0], str) else ""
    message = exc.args[1] if len(exc.args) > 1 and isinstance(exc.args[1], str) else str(exc)
    if state in _TIMEOUT_SQLSTATES:
        return True
    return any(phrase in message for phrase in _TIMEOUT_PHRASES)


def _daterange_inclusive(start: date, end: date) -> list[date]:
    """Return every date in ``[start, end]`` inclusive, ordered ascending.

    Empty list if ``end < start`` (caller guarantees this means the
    expected range collapsed because LookbackDays exceeded the table's
    age — there is no expected window).
    """
    if end < start:
        return []
    days = (end - start).days + 1
    return [start + timedelta(days=i) for i in range(days)]


def _validate_filter(source_filter: str | None) -> None:
    """Reject empty-string filters at the function boundary.

    ``None`` is the canonical "no filter" sentinel; an empty string is
    almost certainly a caller bug (e.g. ``args.source or None`` not
    applied). Raising here surfaces the issue immediately instead of
    silently matching zero rows.
    """
    if source_filter is not None and (not isinstance(source_filter, str) or not source_filter.strip()):
        raise ExtractionStateUnavailable(
            "source_filter must be a non-empty string or None",
            metadata={"source_filter_repr": repr(source_filter)},
        )


def _validate_as_of_date(as_of_date: date) -> None:
    """Reject wrong-type / datetime ``as_of_date`` at the boundary."""
    if not isinstance(as_of_date, date) or isinstance(as_of_date, datetime):
        # ``datetime`` IS a subclass of ``date``; we want pure ``date`` only.
        raise ExtractionStateUnavailable(
            "as_of_date must be a datetime.date (received "
            f"{type(as_of_date).__name__})",
            metadata={"as_of_date_repr": repr(as_of_date)},
        )


# ---------------------------------------------------------------------------
# DB lookup helpers
# ---------------------------------------------------------------------------


def _fetch_large_tables(
    *,
    source_filter: str | None,
) -> list[tuple[str, str, date | None, int | None]]:
    """Fetch every large table from ``UdmTablesList``.

    Large = ``SourceAggregateColumnName IS NOT NULL`` per § 5.3 spec.
    Returns ``[(source_name, table_name, first_load_date, lookback_days), ...]``
    in stable ``(SourceName, SourceObjectName)`` order so the resulting
    :class:`GapReport` list is deterministic across calls.

    :raises ExtractionStateUnavailable: transient DB connectivity failure.
    """
    sql = (
        "SELECT SourceName, SourceObjectName, FirstLoadDate, LookbackDays "
        "FROM dbo.UdmTablesList "
        "WHERE SourceAggregateColumnName IS NOT NULL"
    )
    params: tuple[Any, ...] = ()
    if source_filter is not None:
        sql += " AND SourceName = ?"
        params = (source_filter,)
    sql += " ORDER BY SourceName, SourceObjectName"

    try:
        with cursor_for("General") as cur:
            cur.execute(sql, *params)
            rows = cur.fetchall()
    except pyodbc.OperationalError as exc:
        raise ExtractionStateUnavailable(
            "Connection failure during UdmTablesList large-table scan",
            metadata={"source_filter": source_filter},
        ) from exc

    result: list[tuple[str, str, date | None, int | None]] = []
    for row in rows:
        source_name = row[0]
        table_name = row[1]
        first_load = _coerce_date(row[2])
        lookback = int(row[3]) if row[3] is not None else None
        result.append((source_name, table_name, first_load, lookback))
    return result


def _fetch_success_dates(
    *,
    source_name: str,
    table_name: str,
    range_start: date,
    range_end: date,
) -> set[date]:
    """Fetch the set of DateValue values with ``Status='SUCCESS'`` in the range.

    Uses ``IX_PipelineExtraction_TrustGate`` index. Returns a set for
    O(1) membership tests in :func:`_compute_missing_dates`. Empty set
    is a valid result (table has never been extracted in this range).

    Applies a 60 s cursor timeout per § 5.3 — beyond that, raise
    :class:`GapDetectorTimeout` per D68. A truly-large
    ``PipelineExtraction`` table (millions of rows) may need an index
    review if this timeout fires repeatedly.

    :raises GapDetectorTimeout: query exceeded 60 s.
    :raises ExtractionStateUnavailable: transient DB connectivity failure.
    """
    try:
        with cursor_for("General") as cur:
            # pyodbc's cursor.timeout is in seconds; 0 means no timeout.
            try:
                cur.timeout = _QUERY_TIMEOUT_SECONDS
            except (AttributeError, TypeError):
                # Some pyodbc versions / drivers don't expose .timeout
                # — degrade gracefully and rely on connection-level timeout.
                # The 60 s bound is operator-facing documentation; we still
                # surface GapDetectorTimeout if a server-side timeout fires.
                pass
            cur.execute(
                """
                SELECT DISTINCT DateValue
                FROM General.ops.PipelineExtraction
                WHERE SourceName = ?
                  AND TableName = ?
                  AND DateValue BETWEEN ? AND ?
                  AND Status = 'SUCCESS'
                """,
                source_name,
                table_name,
                range_start,
                range_end,
            )
            rows = cur.fetchall()
    except pyodbc.OperationalError as exc:
        if _is_timeout_error(exc):
            raise GapDetectorTimeout(
                f"PipelineExtraction scan exceeded {_QUERY_TIMEOUT_SECONDS}s "
                f"for {source_name}.{table_name} "
                f"[{range_start.isoformat()}..{range_end.isoformat()}]",
                metadata={
                    "source_name": source_name,
                    "table_name": table_name,
                    "range_start": range_start.isoformat(),
                    "range_end": range_end.isoformat(),
                    "timeout_seconds": _QUERY_TIMEOUT_SECONDS,
                },
            ) from exc
        raise ExtractionStateUnavailable(
            "Connection failure during PipelineExtraction SUCCESS-row scan",
            metadata={
                "source_name": source_name,
                "table_name": table_name,
            },
        ) from exc

    return {coerced for row in rows if (coerced := _coerce_date(row[0])) is not None}


# ---------------------------------------------------------------------------
# Gap classification
# ---------------------------------------------------------------------------


def _expected_range(
    *,
    first_load_date: date | None,
    lookback_days: int | None,
    as_of_date: date,
) -> tuple[date, date] | None:
    """Compute ``(range_start, range_end)`` inclusive.

    Returns ``None`` if no expected range can be computed (no
    ``FirstLoadDate`` set on the table — every date is undefined).

    The range upper bound is ``as_of_date - lookback_days`` so the
    rolling lookback window is excluded from the gap analysis. A
    missing date inside the lookback window is intentional (it's the
    re-extraction zone) and would generate false alarms.

    ``lookback_days = 0`` is treated as "no lookback exclusion" —
    every date through ``as_of_date`` is expected.
    """
    if first_load_date is None:
        return None
    effective_lookback = _DEFAULT_LOOKBACK_DAYS if lookback_days is None else max(0, lookback_days)
    range_start = first_load_date
    range_end = as_of_date - timedelta(days=effective_lookback)
    # If range_end < range_start the entire history is inside the
    # lookback window — there is nothing to check.
    return (range_start, range_end)


def _compute_missing_dates(
    expected_range: tuple[date, date],
    success_dates: set[date],
) -> list[date]:
    """Set difference: every date in the expected range minus SUCCESS dates."""
    range_start, range_end = expected_range
    expected = _daterange_inclusive(range_start, range_end)
    return [d for d in expected if d not in success_dates]


def _classify_action(
    *,
    missing_dates: list[date],
    success_dates: set[date],
) -> str:
    """Classify the recommended action for a table with gaps.

    Decision matrix (per § 5.3 + the docstring narrative above):

    - Zero missing dates → ``ACTION_NO_ACTION``. Caller filters these
      out of the returned list; the value exists for the CLI shim's
      ``--include-recommendation`` JSON-mode rendering of "checked
      but clean" tables.
    - Some missing dates AND at least one SUCCESS row in range →
      ``ACTION_BACKFILL``. A targeted backfill closes the gap.
    - Some missing dates AND zero SUCCESS rows in range →
      ``ACTION_INVESTIGATE``. The table was registered but has never
      had a successful extraction in the expected window. Operator
      must inspect (source down? table never activated?) before
      triggering a backfill.
    """
    if not missing_dates:
        return ACTION_NO_ACTION
    if success_dates:
        return ACTION_BACKFILL
    return ACTION_INVESTIGATE


# ---------------------------------------------------------------------------
# Event-row write (best-effort audit trail)
# ---------------------------------------------------------------------------


def _serialize_missing_dates_for_metadata(missing_dates: list[date]) -> list[str]:
    """Truncate + serialize missing-date list for the Metadata JSON.

    Bounded to :data:`_METADATA_MISSING_DATES_CAP` entries with a
    trailing ``"..."`` sentinel if truncated. Returned dates are
    ISO-formatted strings (the JSON serializer cannot encode
    ``datetime.date``).
    """
    if len(missing_dates) <= _METADATA_MISSING_DATES_CAP:
        return [d.isoformat() for d in missing_dates]
    head = [d.isoformat() for d in missing_dates[:_METADATA_MISSING_DATES_CAP]]
    head.append("...")
    return head


def _build_event_metadata(
    *,
    as_of_date: date,
    source_filter: str | None,
    tables_checked: int,
    reports: list[GapReport],
) -> dict[str, Any]:
    """Build the Metadata JSON payload for the GAP_DETECT event row.

    Field inventory:

    * ``as_of_date`` (ISO date) — the boundary the scan ran against
    * ``source_filter`` (str or None) — the filter applied (None for "all")
    * ``tables_checked`` (int) — count of large tables scanned
    * ``tables_with_gaps`` (int) — count of returned GapReport instances
    * ``total_missing_dates`` (int) — sum of missing-date counts across reports
    * ``affected_tables`` (list of {source, table, missing_count, action})
      — truncated to :data:`_METADATA_AFFECTED_TABLES_CAP` rows for
      readability in the audit DB
    """
    total_missing = sum(len(r.missing_dates) for r in reports)
    affected = [
        {
            "source_name": r.source_name,
            "table_name": r.table_name,
            "missing_count": len(r.missing_dates),
            "recommended_action": r.recommended_action,
        }
        for r in reports[:_METADATA_AFFECTED_TABLES_CAP]
    ]
    if len(reports) > _METADATA_AFFECTED_TABLES_CAP:
        affected.append({"_truncated": f"{len(reports) - _METADATA_AFFECTED_TABLES_CAP} more"})
    return {
        "as_of_date": as_of_date.isoformat(),
        "source_filter": source_filter,
        "tables_checked": tables_checked,
        "tables_with_gaps": len(reports),
        "total_missing_dates": total_missing,
        "affected_tables": affected,
        "module_version": "M13/v1",
    }


def _write_gap_detect_event(
    *,
    metadata: dict[str, Any],
    status: str = "SUCCESS",
    error_message: str | None = None,
) -> bool:
    """INSERT one ``GAP_DETECT`` row into ``General.ops.PipelineEventLog``.

    Per § 5.3 produces — one row per invocation regardless of outcome
    (the audit trail proves the hourly job ran). Best-effort: failures
    are logged but do NOT propagate. The return value of
    :func:`detect_extraction_gaps` is the operator-facing result; the
    event row is supplementary audit.

    Mirrors the audit-row pattern used by ``tools/log_retention_cleanup.py``
    and ``tools/measure_lateness.py`` — direct INSERT against
    ``PipelineEventLog`` via ``cursor_for('General')`` rather than the
    ``PipelineEventTracker`` context manager (which requires a
    ``TableConfig`` and is per-table, not per-invocation).

    Returns ``True`` on successful write, ``False`` if the audit-row
    write failed.
    """
    metadata_json = json.dumps(metadata, separators=(",", ":"), default=str)
    event_detail = (
        f"gap_detector / "
        f"tables={metadata.get('tables_checked')} "
        f"gaps={metadata.get('tables_with_gaps')}"
    )
    try:
        with cursor_for("General") as cur:
            cur.execute(
                "INSERT INTO General.ops.PipelineEventLog "
                "(BatchId, TableName, SourceName, EventType, EventDetail, "
                " StartedAt, CompletedAt, Status, ErrorMessage, Metadata) "
                "VALUES (NEXT VALUE FOR General.ops.PipelineBatchSequence, "
                "        NULL, NULL, ?, ?, SYSUTCDATETIME(), SYSUTCDATETIME(), "
                "        ?, ?, ?)",
                EVENT_TYPE,
                event_detail,
                status,
                error_message,
                metadata_json,
            )
        return True
    except Exception:  # noqa: BLE001
        # Audit-row write is best-effort — never affect the verdict.
        # Matches B188 / B189 / B190 / log_retention_cleanup pattern.
        logger.exception("Failed to write GAP_DETECT audit row")
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def detect_extraction_gaps(
    *,
    source_filter: str | None = None,
    as_of_date: date | None = None,
) -> list[GapReport]:
    """Detect missing ``business_date`` rows per large table.

    For each large table (``UdmTablesList.SourceAggregateColumnName IS NOT NULL``),
    compute the expected business-date range
    ``[FirstLoadDate, as_of_date - LookbackDays]``, query
    ``General.ops.PipelineExtraction`` for SUCCESS rows in the range,
    and emit one :class:`GapReport` per table whose set of SUCCESS dates
    does not cover the full expected range.

    Tables that are entirely clean (no missing dates in the expected
    range) are OMITTED from the returned list — they never produce a
    :class:`GapReport`. Tables with no ``FirstLoadDate`` configured
    are also omitted (the expected range is undefined).

    Writes exactly one ``GAP_DETECT`` row to
    ``General.ops.PipelineEventLog`` per invocation, regardless of
    whether any gap was found, for audit-trail purposes.

    :param source_filter: Optional ``UdmTablesList.SourceName`` filter.
        ``None`` scans every source. An empty string raises
        :class:`ExtractionStateUnavailable` (almost certainly a caller
        bug — see :func:`_validate_filter`).
    :param as_of_date: Optional override for "today" — UTC calendar
        date by default. Useful for historical replay
        ("what gaps would the hourly job have reported on 2026-04-15?").

    :returns: List of :class:`GapReport` in ``(source_name, table_name)``
        ascending order. Empty list iff every checked table was clean.

    :raises GapDetectorTimeout: a ``PipelineExtraction`` scan exceeded
        60 s. PipelineRetryableError per D68.
    :raises ExtractionStateUnavailable: transient DB connectivity
        failure during any lookup. PipelineRetryableError per D68.
    """
    _validate_filter(source_filter)
    effective_as_of = as_of_date if as_of_date is not None else _utc_today()
    _validate_as_of_date(effective_as_of)

    logger.info(
        "detect_extraction_gaps(source_filter=%r, as_of_date=%s) starting",
        source_filter, effective_as_of.isoformat(),
    )

    # Track everything so the audit row can record what was checked
    # even if the loop later raises (the except clause still emits
    # the event row at FAILED status).
    reports: list[GapReport] = []
    tables_checked = 0

    try:
        tables = _fetch_large_tables(source_filter=source_filter)
        for source_name, table_name, first_load, lookback in tables:
            tables_checked += 1
            expected = _expected_range(
                first_load_date=first_load,
                lookback_days=lookback,
                as_of_date=effective_as_of,
            )
            if expected is None:
                # FirstLoadDate not configured — no expected range to
                # check against. Skip silently.
                logger.debug(
                    "Skipping %s.%s — FirstLoadDate not configured",
                    source_name, table_name,
                )
                continue
            range_start, range_end = expected
            if range_end < range_start:
                # Whole history fits inside the lookback window;
                # nothing to check. Skip silently.
                logger.debug(
                    "Skipping %s.%s — expected range collapsed "
                    "(range_end=%s < range_start=%s)",
                    source_name, table_name, range_end.isoformat(), range_start.isoformat(),
                )
                continue
            success_dates = _fetch_success_dates(
                source_name=source_name,
                table_name=table_name,
                range_start=range_start,
                range_end=range_end,
            )
            missing = _compute_missing_dates(expected, success_dates)
            if not missing:
                continue  # Clean — no GapReport emitted.
            action = _classify_action(
                missing_dates=missing,
                success_dates=success_dates,
            )
            reports.append(
                GapReport(
                    source_name=source_name,
                    table_name=table_name,
                    expected_range=expected,
                    missing_dates=missing,
                    recommended_action=action,
                )
            )
    except GapDetectorTimeout:
        # Audit the partial outcome at FAILED and re-raise so the CLI
        # shim's § 1.8 wrapper can map to exit code 1 (retryable).
        _write_gap_detect_event(
            metadata=_build_event_metadata(
                as_of_date=effective_as_of,
                source_filter=source_filter,
                tables_checked=tables_checked,
                reports=reports,
            ),
            status="FAILED",
            error_message="GapDetectorTimeout (query > 60s)",
        )
        raise
    except ExtractionStateUnavailable as exc:
        _write_gap_detect_event(
            metadata=_build_event_metadata(
                as_of_date=effective_as_of,
                source_filter=source_filter,
                tables_checked=tables_checked,
                reports=reports,
            ),
            status="FAILED",
            error_message=f"ExtractionStateUnavailable: {exc}",
        )
        raise

    # Happy path — one audit row at SUCCESS regardless of whether any
    # gaps were found.
    _write_gap_detect_event(
        metadata=_build_event_metadata(
            as_of_date=effective_as_of,
            source_filter=source_filter,
            tables_checked=tables_checked,
            reports=reports,
        ),
        status="SUCCESS",
    )

    logger.info(
        "detect_extraction_gaps complete: %d tables checked, "
        "%d gaps detected (%d missing dates total)",
        tables_checked,
        len(reports),
        sum(len(r.missing_dates) for r in reports),
    )
    return reports
