"""Per-date extraction state for large tables per Round 3 § 4.2.

This module encapsulates the trust gate (D13 — :func:`is_date_trusted`),
lookback decisions (D11 — empirical L_99), and re-extraction tracking
(D14 — ``IsReExtraction`` / ``ExtractionAttempt``) for the windowed
large-table extraction path. It is the Round-3 successor / refactor of
the pre-Phase-1 ``orchestration/pipeline_state.py`` module — same
operational role (per-date state machine), tighter contract.

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
        IsReExtraction       BIT             NOT NULL DEFAULT 0,    -- D14
        ExtractionAttempt    INT             NOT NULL DEFAULT 1,    -- D14
        FailureReason        NVARCHAR(MAX)   NULL,
        CONSTRAINT PK_PipelineExtraction PRIMARY KEY CLUSTERED (ExtractionId),
        CONSTRAINT CK_PipelineExtraction_Status CHECK
            (Status IN ('IN_PROGRESS', 'SUCCESS', 'FAILED'))
    );
    CREATE UNIQUE INDEX UX_PipelineExtraction_Identity
        ON General.ops.PipelineExtraction
        (SourceName, TableName, DateValue, ExtractionAttempt);
    CREATE INDEX IX_PipelineExtraction_TrustGate
        ON General.ops.PipelineExtraction
        (SourceName, TableName, DateValue, Status, EvaluatedAt DESC)
        INCLUDE (BatchId, IsReExtraction, ExtractionAttempt);

The ``UX_PipelineExtraction_Identity`` UNIQUE index is the idempotency
gate for :func:`record_extraction_attempt` — same ``(SourceName,
TableName, DateValue, ExtractionAttempt)`` re-insert raises
``pyodbc.IntegrityError`` and the helper UPDATEs the existing row
instead of failing.

D11 / D13 / D14 — what each function answers
============================================

- D13 trust gate (:func:`is_date_trusted`): the CDC engine only triggers
  delete detection for dates that have a prior ``Status='SUCCESS'`` row.
  Untrusted dates extract normally but DO NOT participate in delete
  inference (a missing row on an untrusted date is treated as
  "we never saw a definitive prior state" — not "the source dropped it").
- D11 empirical L_99 lookback (:func:`most_recent_success`): the
  orchestration layer composes this with ``UdmTablesList.LookbackDays``
  to compute the starting boundary of the rolling extraction window.
- D14 re-extraction tracking (:func:`is_reextraction` +
  :func:`get_extraction_attempt`): every retry increments the
  ``ExtractionAttempt`` counter and sets ``IsReExtraction=1`` so the
  audit trail distinguishes a clean first pass from a recovery loop.

Date validation contract (per § 4.2 + D68)
==========================================

:func:`is_date_trusted` validates the input date against two boundaries:

1. Future dates — ``business_date > today (UTC)`` — raise
   :class:`InvalidTrustGate`. There is no defensible interpretation of
   "did extraction succeed for tomorrow?"; this is always a caller bug.
2. Pre-``FirstLoadDate`` — ``business_date < UdmTablesList.FirstLoadDate``
   for the table — raises :class:`InvalidTrustGate`. The table's
   historical floor is configured per-table; dates older than that
   floor were never in scope for extraction.

``FirstLoadDate`` is resolved by querying ``General.dbo.UdmTablesList``
(``SourceName`` + ``SourceObjectName`` key). If the column is NULL the
floor check is skipped (table has no historical floor configured). If
the table is not in ``UdmTablesList`` at all the lookup returns NULL
and the floor check is skipped — the trust gate downgrades to
future-only validation. This is intentional: making the trust gate
depend on tables-list presence would couple two independent failure
modes.

Error classes (per D68)
=======================

- :class:`ExtractionStateUnavailable` (``PipelineRetryableError``) —
  transient DB-connection failure during any lookup. Retryable per B-7.
- :class:`InvalidTrustGate` (``PipelineFatalError``) — future date OR
  date before ``FirstLoadDate``. Configuration error; operator must
  reconcile.

Concurrency (per D69)
=====================

- All reads stateless; ``cursor_for('General')`` acquired per call from
  the per-database connection pool (Item-18).
- :func:`record_extraction_attempt` is serialized by the UNIQUE index
  on ``(SourceName, TableName, DateValue, ExtractionAttempt)`` — two
  concurrent workers with the same key are guaranteed to produce
  exactly one row (the loser UPDATEs).
- Naive-UTC datetimes per the SCD2-P1-f / CDC-NOW-MS invariant —
  ``StartedAt`` / ``CompletedAt`` are written via
  ``SYSUTCDATETIME()`` server-side, but any future client-side
  datetime parameter binding against these columns must strip tzinfo
  and truncate to milliseconds.

D-numbers consumed
==================

D11 (empirical L_99 lookback), D13 (trust gate for delete detection),
D14 (IsReExtraction / ExtractionAttempt columns), D67 (Tier 0 smoke),
D68 (error class hierarchy), D69 (cursor_for ownership), D92
(forward-only additive — new module; predecessor
``orchestration/pipeline_state.py`` left in place).

B-numbers
=========

- Closes **B85** dependent via the ``utils.errors`` import surface
  (consumes :class:`ExtractionStateUnavailable` + :class:`InvalidTrustGate`).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Iterable

import pyodbc

try:
    from utils.connections import cursor_for
except ImportError:
    # Fallback for legacy callers that placed ``connections`` at project root.
    from connections import cursor_for  # type: ignore[no-redef]

from utils.errors import (
    ExtractionStateUnavailable,
    InvalidTrustGate,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ExtractionState",
    "is_date_trusted",
    "most_recent_success",
    "is_reextraction",
    "get_extraction_attempt",
    "record_extraction_attempt",
]


_VALID_STATUSES = frozenset({"IN_PROGRESS", "SUCCESS", "FAILED"})

# Maximum length of a FailureReason written to PipelineExtraction. The
# column itself is NVARCHAR(MAX) but bounding defends against
# catastrophically large exception messages flooding the audit table.
_FAILURE_REASON_MAX_LEN = 4000


@dataclass(frozen=True)
class ExtractionState:
    """One row's worth of canonical state from ``PipelineExtraction``.

    Returned by lookups that need the full row context (callers that
    only need a single field use the scalar helpers).

    Field-to-column mapping per § 4.2 + canonical DDL (L253-271):

    :param source_name: ``PipelineExtraction.SourceName``.
    :param table_name: ``PipelineExtraction.TableName``.
    :param business_date: ``PipelineExtraction.DateValue``.
    :param status: ``PipelineExtraction.Status`` —
        one of ``'IN_PROGRESS'`` / ``'SUCCESS'`` / ``'FAILED'``.
    :param extraction_attempt: ``PipelineExtraction.ExtractionAttempt``
        (1-indexed).
    :param is_reextraction: ``PipelineExtraction.IsReExtraction`` —
        boolean coerced from the BIT column.
    :param started_at: ``PipelineExtraction.StartedAt`` —
        naive (no tzinfo) ms-precision datetime in UTC wall time
        per SCD2-P1-f. ``None`` if the row was never written
        (sentinel for the "no prior row" case).
    :param batch_id: ``PipelineExtraction.BatchId``. ``None`` if no
        row was found.
    """

    source_name: str
    table_name: str
    business_date: date
    status: str
    extraction_attempt: int
    is_reextraction: bool
    started_at: datetime | None
    batch_id: int | None


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _utcnow_ms() -> datetime:
    """Naive UTC datetime truncated to milliseconds.

    Matches the SCD2-P1-f / CDC-NOW-MS invariant (naive, ms precision)
    so any client-side parameter binding against ``StartedAt`` /
    ``CompletedAt`` (both ``DATETIME2(3)``) does not silently shift
    through ``DATETIMEOFFSET`` coercion on a non-UTC server.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return now.replace(microsecond=(now.microsecond // 1000) * 1000)


def _utc_today() -> date:
    """UTC calendar date (naive). Boundary for the future-date trust check."""
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
        "from PipelineExtraction lookup",
        metadata={"value_repr": repr(value)},
    )


def _coerce_datetime(value: Any) -> datetime | None:
    """Coerce a pyodbc-returned cell to a naive ms-precision ``datetime``."""
    if value is None:
        return None
    if isinstance(value, datetime):
        # Strip tzinfo + truncate to milliseconds per SCD2-P1-f.
        naive = value.replace(tzinfo=None) if value.tzinfo is not None else value
        return naive.replace(microsecond=(naive.microsecond // 1000) * 1000)
    raise ExtractionStateUnavailable(
        f"Unexpected datetime-column value type {type(value).__name__!r} "
        "from PipelineExtraction lookup",
        metadata={"value_repr": repr(value)},
    )


def _validate_identity(
    source_name: str,
    table_name: str,
    business_date: date,
) -> None:
    """Reject empty / wrong-type identity inputs at the function boundary."""
    if not isinstance(business_date, date) or isinstance(business_date, datetime):
        # ``datetime`` IS a subclass of ``date``; we want pure ``date`` only,
        # so the bool-shape of the type check is intentional.
        raise InvalidTrustGate(
            "business_date must be a datetime.date (received "
            f"{type(business_date).__name__})",
            metadata={"business_date_repr": repr(business_date)},
        )
    if not source_name or not isinstance(source_name, str):
        raise InvalidTrustGate(
            "source_name must be a non-empty string",
            metadata={"source_name_repr": repr(source_name)},
        )
    if not table_name or not isinstance(table_name, str):
        raise InvalidTrustGate(
            "table_name must be a non-empty string",
            metadata={"table_name_repr": repr(table_name)},
        )


def _lookup_first_load_date(
    *,
    source_name: str,
    table_name: str,
) -> date | None:
    """Resolve ``UdmTablesList.FirstLoadDate`` for the (source, table).

    Keyed on ``SourceName`` + ``SourceObjectName`` per Round 2 § 1.1.5.
    Returns ``None`` if the row is missing OR ``FirstLoadDate`` is NULL —
    either case downgrades the trust-gate floor check to a no-op.

    Wraps DB failures in :class:`ExtractionStateUnavailable` per D68.
    """
    try:
        with cursor_for("General") as cur:
            cur.execute(
                """
                SELECT FirstLoadDate
                FROM dbo.UdmTablesList
                WHERE SourceName = ? AND SourceObjectName = ?
                """,
                source_name,
                table_name,
            )
            row = cur.fetchone()
    except pyodbc.OperationalError as exc:
        raise ExtractionStateUnavailable(
            "Connection failure during UdmTablesList.FirstLoadDate lookup",
            metadata={
                "source_name": source_name,
                "table_name": table_name,
            },
        ) from exc
    if row is None:
        return None
    return _coerce_date(row[0])


# ---------------------------------------------------------------------------
# Public read functions — pure (no side effects)
# ---------------------------------------------------------------------------


def is_date_trusted(
    *,
    source_name: str,
    table_name: str,
    business_date: date,
) -> bool:
    """D13 trust gate — was ``business_date`` previously extracted with
    ``Status='SUCCESS'`` for this ``(source, table)``?

    The CDC engine consults this before it triggers delete detection:
    delete inference REQUIRES a successful prior extraction of the
    same date as the comparison baseline. Untrusted dates extract
    normally but do not participate in delete inference (the absence
    of a row on an untrusted date is interpreted as "no prior
    definitive state", not "the source dropped it").

    :param source_name: e.g. ``'DNA'``, ``'CCM'``, ``'EPICOR'``.
    :param table_name: source object name (e.g. ``'ACCT'``).
    :param business_date: the business-day boundary in question.

    :returns: ``True`` iff at least one ``PipelineExtraction`` row exists
        with ``Status='SUCCESS'`` for the key. ``False`` otherwise.

    :raises InvalidTrustGate: ``business_date`` is in the future (UTC)
        OR strictly before ``UdmTablesList.FirstLoadDate`` for this
        table. Both indicate caller-side configuration error.
    :raises ExtractionStateUnavailable: transient DB connectivity
        failure during the lookup. Retryable per B-7.
    """
    _validate_identity(source_name, table_name, business_date)

    today_utc = _utc_today()
    if business_date > today_utc:
        raise InvalidTrustGate(
            f"is_date_trusted invoked with future date {business_date.isoformat()} "
            f"(today UTC = {today_utc.isoformat()})",
            metadata={
                "source_name": source_name,
                "table_name": table_name,
                "business_date": business_date.isoformat(),
                "today_utc": today_utc.isoformat(),
            },
        )

    first_load = _lookup_first_load_date(
        source_name=source_name,
        table_name=table_name,
    )
    if first_load is not None and business_date < first_load:
        raise InvalidTrustGate(
            f"is_date_trusted invoked with date {business_date.isoformat()} "
            f"before FirstLoadDate {first_load.isoformat()} "
            f"for {source_name}.{table_name}",
            metadata={
                "source_name": source_name,
                "table_name": table_name,
                "business_date": business_date.isoformat(),
                "first_load_date": first_load.isoformat(),
            },
        )

    try:
        with cursor_for("General") as cur:
            # The IX_PipelineExtraction_TrustGate index is keyed on
            # (SourceName, TableName, DateValue, Status, EvaluatedAt DESC)
            # so this lookup hits the index directly.
            cur.execute(
                """
                SELECT TOP 1 1
                FROM General.ops.PipelineExtraction
                WHERE SourceName = ?
                  AND TableName = ?
                  AND DateValue = ?
                  AND Status = 'SUCCESS'
                """,
                source_name,
                table_name,
                business_date,
            )
            row = cur.fetchone()
    except pyodbc.OperationalError as exc:
        raise ExtractionStateUnavailable(
            "Connection failure during PipelineExtraction trust-gate lookup",
            metadata={
                "source_name": source_name,
                "table_name": table_name,
                "business_date": business_date.isoformat(),
            },
        ) from exc

    trusted = row is not None
    logger.debug(
        "is_date_trusted(%s/%s/%s) -> %s",
        source_name, table_name, business_date.isoformat(), trusted,
    )
    return trusted


def most_recent_success(
    *,
    source_name: str,
    table_name: str,
) -> date | None:
    """Return the most recent ``DateValue`` with ``Status='SUCCESS'``.

    Used by the orchestration layer to compute the starting boundary
    of the rolling lookback window per D11. Returns ``None`` if the
    pipeline has never recorded a successful extraction for this
    ``(source, table)`` — the caller falls back to
    ``UdmTablesList.FirstLoadDate``.

    No date validation here — the caller is asking "what's the
    historical record?", which is well-defined for any
    ``(source, table)`` regardless of today's calendar.

    :raises ExtractionStateUnavailable: transient DB connectivity
        failure. Retryable per B-7.
    """
    if not source_name or not table_name:
        # Don't raise InvalidTrustGate here — this isn't the trust gate;
        # an empty identifier is a caller bug at a different layer.
        # Surface as the retryable class so existing retry plumbing
        # logs it; orchestration validates identifiers upstream.
        raise ExtractionStateUnavailable(
            "most_recent_success requires non-empty source_name + table_name",
            metadata={
                "source_name": source_name,
                "table_name": table_name,
            },
        )

    try:
        with cursor_for("General") as cur:
            cur.execute(
                """
                SELECT MAX(DateValue)
                FROM General.ops.PipelineExtraction
                WHERE SourceName = ?
                  AND TableName = ?
                  AND Status = 'SUCCESS'
                """,
                source_name,
                table_name,
            )
            row = cur.fetchone()
    except pyodbc.OperationalError as exc:
        raise ExtractionStateUnavailable(
            "Connection failure during most_recent_success lookup",
            metadata={
                "source_name": source_name,
                "table_name": table_name,
            },
        ) from exc

    if row is None or row[0] is None:
        return None
    return _coerce_date(row[0])


def is_reextraction(
    *,
    source_name: str,
    table_name: str,
    business_date: date,
) -> bool:
    """Has any prior attempt been recorded for this ``(source, table, date)``?

    Drives the D14 ``IsReExtraction`` flag on the new attempt's row.
    Returns ``True`` if at least one row already exists for the
    ``(source, table, date)`` regardless of its ``Status`` — a prior
    ``FAILED`` row still counts as a prior attempt.

    :raises ExtractionStateUnavailable: transient DB connectivity
        failure. Retryable per B-7.
    """
    if not source_name or not table_name:
        raise ExtractionStateUnavailable(
            "is_reextraction requires non-empty source_name + table_name",
            metadata={
                "source_name": source_name,
                "table_name": table_name,
                "business_date": business_date.isoformat()
                if isinstance(business_date, date) else repr(business_date),
            },
        )
    if not isinstance(business_date, date) or isinstance(business_date, datetime):
        raise ExtractionStateUnavailable(
            "business_date must be a datetime.date",
            metadata={"business_date_repr": repr(business_date)},
        )

    try:
        with cursor_for("General") as cur:
            cur.execute(
                """
                SELECT TOP 1 1
                FROM General.ops.PipelineExtraction
                WHERE SourceName = ?
                  AND TableName = ?
                  AND DateValue = ?
                """,
                source_name,
                table_name,
                business_date,
            )
            row = cur.fetchone()
    except pyodbc.OperationalError as exc:
        raise ExtractionStateUnavailable(
            "Connection failure during is_reextraction lookup",
            metadata={
                "source_name": source_name,
                "table_name": table_name,
                "business_date": business_date.isoformat(),
            },
        ) from exc

    return row is not None


def get_extraction_attempt(
    *,
    source_name: str,
    table_name: str,
    business_date: date,
) -> int:
    """Return the next ``ExtractionAttempt`` number for this key.

    Computed as ``1 + MAX(ExtractionAttempt)`` over prior rows for the
    ``(source, table, date)``. First-time keys return ``1``. Strictly
    monotone for any sequence of calls on the same key in the same
    process (between calls, the value depends on whether another worker
    has committed a row in between — the UNIQUE index ultimately
    serializes :func:`record_extraction_attempt`).

    :raises ExtractionStateUnavailable: transient DB connectivity
        failure. Retryable per B-7.
    """
    if not source_name or not table_name:
        raise ExtractionStateUnavailable(
            "get_extraction_attempt requires non-empty source_name + table_name",
            metadata={
                "source_name": source_name,
                "table_name": table_name,
            },
        )
    if not isinstance(business_date, date) or isinstance(business_date, datetime):
        raise ExtractionStateUnavailable(
            "business_date must be a datetime.date",
            metadata={"business_date_repr": repr(business_date)},
        )

    try:
        with cursor_for("General") as cur:
            cur.execute(
                """
                SELECT MAX(ExtractionAttempt)
                FROM General.ops.PipelineExtraction
                WHERE SourceName = ?
                  AND TableName = ?
                  AND DateValue = ?
                """,
                source_name,
                table_name,
                business_date,
            )
            row = cur.fetchone()
    except pyodbc.OperationalError as exc:
        raise ExtractionStateUnavailable(
            "Connection failure during get_extraction_attempt lookup",
            metadata={
                "source_name": source_name,
                "table_name": table_name,
                "business_date": business_date.isoformat(),
            },
        ) from exc

    if row is None or row[0] is None:
        return 1
    return int(row[0]) + 1


# ---------------------------------------------------------------------------
# Public write helper — INSERT-then-UPDATE-on-collision
# ---------------------------------------------------------------------------


def record_extraction_attempt(
    *,
    source_name: str,
    table_name: str,
    business_date: date,
    batch_id: int,
    status: str,
    rows_extracted: int | None = None,
    failure_reason: str | None = None,
    extraction_attempt: int | None = None,
) -> int:
    """INSERT a new ``PipelineExtraction`` row OR UPDATE the existing
    row by ``(SourceName, TableName, DateValue, ExtractionAttempt)``.

    Idempotent: re-call with the same key (same
    ``extraction_attempt``) is a no-op-then-UPDATE, returning the same
    ``ExtractionId`` each time. The caller's outer ``ledger_step``
    gates the higher-level extraction operation per D15; this helper
    is the persistence half of that contract.

    Auto-assigns ``ExtractionAttempt`` when ``extraction_attempt`` is
    ``None`` — uses :func:`get_extraction_attempt` to compute the next
    number, then INSERTs. Pass an explicit ``extraction_attempt`` if
    you want to update a previously-known row (the canonical pattern
    for ``'IN_PROGRESS' → 'SUCCESS'`` transitions during a run).

    :param source_name: ``UdmTablesList.SourceName``.
    :param table_name: source object name.
    :param business_date: the business-day boundary.
    :param batch_id: from :class:`PipelineBatchSequence` (D45.3). Must
        be a positive integer.
    :param status: one of ``'IN_PROGRESS'`` / ``'SUCCESS'`` / ``'FAILED'``
        per the canonical CHECK constraint.
    :param rows_extracted: optional row count for the attempt;
        populates ``RowsExtracted``.
    :param failure_reason: optional ``Status='FAILED'`` audit detail;
        populates ``FailureReason`` (truncated to 4000 chars).
    :param extraction_attempt: optional explicit attempt number. When
        ``None``, computed as ``1 + MAX(prior attempts)``; when set,
        the caller is updating a previously-known row.

    :returns: ``PipelineExtraction.ExtractionId`` of the row touched.

    :raises InvalidTrustGate: ``status`` is not a canonical value OR
        ``batch_id`` is non-positive OR ``business_date`` is the wrong
        type. These are configuration-error class failures per D68.
    :raises ExtractionStateUnavailable: transient DB connectivity
        failure. Retryable per B-7.
    """
    if not isinstance(business_date, date) or isinstance(business_date, datetime):
        raise InvalidTrustGate(
            "business_date must be a datetime.date",
            metadata={"business_date_repr": repr(business_date)},
        )
    if not source_name or not table_name:
        raise InvalidTrustGate(
            "source_name and table_name must be non-empty strings",
            metadata={
                "source_name": source_name,
                "table_name": table_name,
            },
        )
    if batch_id is None or not isinstance(batch_id, int) or batch_id <= 0:
        raise InvalidTrustGate(
            f"batch_id must be a positive integer (received {batch_id!r})",
            metadata={"batch_id": batch_id},
        )
    if status not in _VALID_STATUSES:
        raise InvalidTrustGate(
            f"status must be one of {sorted(_VALID_STATUSES)!r} "
            f"(received {status!r}) per PipelineExtraction CHECK constraint",
            metadata={"status": status},
        )
    if extraction_attempt is not None and (
        not isinstance(extraction_attempt, int) or extraction_attempt < 1
    ):
        raise InvalidTrustGate(
            "extraction_attempt must be a positive integer when supplied",
            metadata={"extraction_attempt": extraction_attempt},
        )

    truncated_reason: str | None
    if failure_reason is None:
        truncated_reason = None
    else:
        truncated_reason = str(failure_reason)[:_FAILURE_REASON_MAX_LEN]

    # Resolve the attempt number outside the INSERT block so the UPDATE
    # path on UNIQUE collision can see the same value.
    resolved_attempt: int
    if extraction_attempt is None:
        resolved_attempt = get_extraction_attempt(
            source_name=source_name,
            table_name=table_name,
            business_date=business_date,
        )
    else:
        resolved_attempt = extraction_attempt

    is_reextraction_flag = 1 if resolved_attempt > 1 else 0

    # Naive-UTC ms-precision wall time per SCD2-P1-f / CDC-NOW-MS.
    started_at = _utcnow_ms()
    completed_at: datetime | None
    if status in ("SUCCESS", "FAILED"):
        completed_at = started_at
    else:
        completed_at = None

    # ---- Try INSERT first. On UNIQUE collision, UPDATE the existing row.
    try:
        with cursor_for("General") as cur:
            cur.execute(
                """
                INSERT INTO General.ops.PipelineExtraction
                    (BatchId, SourceName, TableName, DateValue, Status,
                     StartedAt, CompletedAt, RowsExtracted,
                     IsReExtraction, ExtractionAttempt, FailureReason)
                OUTPUT INSERTED.ExtractionId
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                batch_id,
                source_name,
                table_name,
                business_date,
                status,
                started_at,
                completed_at,
                rows_extracted,
                is_reextraction_flag,
                resolved_attempt,
                truncated_reason,
            )
            row = cur.fetchone()
            if row is None:
                raise ExtractionStateUnavailable(
                    "INSERT to PipelineExtraction returned no row from OUTPUT "
                    "clause; table may be misconfigured or driver mis-bound.",
                    metadata={
                        "source_name": source_name,
                        "table_name": table_name,
                        "business_date": business_date.isoformat(),
                        "extraction_attempt": resolved_attempt,
                    },
                )
            extraction_id = int(row[0])
            logger.debug(
                "record_extraction_attempt INSERT: ExtractionId=%d for "
                "%s/%s/%s attempt=%d status=%s",
                extraction_id, source_name, table_name,
                business_date.isoformat(), resolved_attempt, status,
            )
            return extraction_id
    except pyodbc.IntegrityError as exc:
        # UNIQUE violation on (SourceName, TableName, DateValue,
        # ExtractionAttempt). Existing row owns this key — UPDATE it.
        if not _is_unique_violation(exc):
            # Some other IntegrityError (FK, CHECK) — surface as
            # configuration error so the caller does not interpret it
            # as a transient retryable failure.
            raise InvalidTrustGate(
                f"PipelineExtraction INSERT raised non-UNIQUE "
                f"IntegrityError: {exc!s}",
                metadata={
                    "source_name": source_name,
                    "table_name": table_name,
                    "business_date": business_date.isoformat(),
                    "extraction_attempt": resolved_attempt,
                    "status": status,
                },
            ) from exc
        try:
            with cursor_for("General") as cur:
                cur.execute(
                    """
                    UPDATE General.ops.PipelineExtraction
                    SET BatchId = ?,
                        Status = ?,
                        CompletedAt = ?,
                        EvaluatedAt = SYSUTCDATETIME(),
                        RowsExtracted = COALESCE(?, RowsExtracted),
                        IsReExtraction = ?,
                        FailureReason = ?
                    OUTPUT INSERTED.ExtractionId
                    WHERE SourceName = ?
                      AND TableName = ?
                      AND DateValue = ?
                      AND ExtractionAttempt = ?
                    """,
                    batch_id,
                    status,
                    completed_at,
                    rows_extracted,
                    is_reextraction_flag,
                    truncated_reason,
                    source_name,
                    table_name,
                    business_date,
                    resolved_attempt,
                )
                row = cur.fetchone()
        except pyodbc.OperationalError as op_exc:
            raise ExtractionStateUnavailable(
                "Connection failure during PipelineExtraction UPDATE",
                metadata={
                    "source_name": source_name,
                    "table_name": table_name,
                    "business_date": business_date.isoformat(),
                    "extraction_attempt": resolved_attempt,
                },
            ) from op_exc
        if row is None:
            # UNIQUE-violation-but-no-row-on-follow-up is a phantom-write
            # race — extremely rare; another worker DELETEd between our
            # INSERT and UPDATE. Retryable per B-7.
            raise ExtractionStateUnavailable(
                "UNIQUE violation on INSERT but no row found on follow-up "
                "UPDATE — phantom-write race",
                metadata={
                    "source_name": source_name,
                    "table_name": table_name,
                    "business_date": business_date.isoformat(),
                    "extraction_attempt": resolved_attempt,
                },
            ) from exc
        extraction_id = int(row[0])
        logger.info(
            "record_extraction_attempt UPDATE (UNIQUE collision): "
            "ExtractionId=%d for %s/%s/%s attempt=%d status=%s",
            extraction_id, source_name, table_name,
            business_date.isoformat(), resolved_attempt, status,
        )
        return extraction_id
    except pyodbc.OperationalError as exc:
        raise ExtractionStateUnavailable(
            "Connection failure during PipelineExtraction INSERT",
            metadata={
                "source_name": source_name,
                "table_name": table_name,
                "business_date": business_date.isoformat(),
                "extraction_attempt": resolved_attempt,
                "status": status,
            },
        ) from exc


# ---------------------------------------------------------------------------
# pyodbc UNIQUE-violation detection (mirrors utils.idempotency_ledger
# heuristic — kept module-local to avoid the cross-module import).
# ---------------------------------------------------------------------------


_UNIQUE_VIOLATION_CODES = frozenset({2627, 2601})


def _is_unique_violation(exc: pyodbc.IntegrityError) -> bool:
    """Return True if a pyodbc IntegrityError represents a UNIQUE violation.

    pyodbc maps SQL Server error 2627 (PK) / 2601 (UNIQUE index) to
    ``IntegrityError``. Other ``IntegrityError`` variants (FK, CHECK
    failure) bubble up unchanged — those are caller bugs, not
    short-circuit signals.

    Heuristic uses the canonical SQL Server error phrases ("Violation
    of UNIQUE KEY constraint", "Violation of PRIMARY KEY constraint",
    "Cannot insert duplicate key") plus the parenthesized native
    codes 2627 / 2601.
    """
    args: Iterable[Any] = exc.args
    if not args:
        return False

    _UNIQUE_PHRASES = (
        "Violation of UNIQUE KEY constraint",
        "Violation of PRIMARY KEY constraint",
        "Cannot insert duplicate key",
    )

    def _matches(text: str) -> bool:
        return (
            "2627" in text
            or "2601" in text
            or any(phrase in text for phrase in _UNIQUE_PHRASES)
        )

    for arg in args:
        if isinstance(arg, str) and _matches(arg):
            return True
        if isinstance(arg, tuple):
            for elt in arg:
                if isinstance(elt, int) and elt in _UNIQUE_VIOLATION_CODES:
                    return True
                if isinstance(elt, str) and _matches(elt):
                    return True
    return False
