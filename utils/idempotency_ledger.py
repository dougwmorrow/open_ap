"""Idempotency ledger — central D15 enforcer per Round 3 § 4.1.

This module IS the canonical pipeline idempotency mechanism per D15 + D17.
Every Round 3 module composes through it. The pattern is analogous to SP-1's
``UPDLOCK + HOLDLOCK + catch-on-UNIQUE-violation`` for the vault, scoped to
step-level rather than row-level.

Canonical DDL (per ``phase1/01_database_schema.md`` § 7 — re-read at build
time per Pitfall #9.l discipline)::

    CREATE TABLE General.ops.IdempotencyLedger (
        LedgerId        BIGINT IDENTITY(1,1) NOT NULL,
        BatchId         BIGINT          NOT NULL,
        SourceName      NVARCHAR(50)    NOT NULL,
        TableName       NVARCHAR(255)   NOT NULL,
        EventType       NVARCHAR(50)    NOT NULL,
        Status          NVARCHAR(20)    NOT NULL DEFAULT 'IN_PROGRESS',
        StartedAt       DATETIME2(3)    NOT NULL DEFAULT SYSUTCDATETIME(),
        CompletedAt     DATETIME2(3)    NULL,
        DurationMs      BIGINT          NULL,
        ErrorMessage    NVARCHAR(MAX)   NULL,
        RecoveryAction  NVARCHAR(50)    NULL,
        CONSTRAINT PK_IdempotencyLedger PRIMARY KEY CLUSTERED (LedgerId),
        CONSTRAINT CK_IdempotencyLedger_Status CHECK
            (Status IN ('IN_PROGRESS', 'COMPLETED', 'FAILED'))
    );
    CREATE UNIQUE INDEX UX_IdempotencyLedger_Key
        ON General.ops.IdempotencyLedger
        (BatchId, SourceName, TableName, EventType);

Note the UNIQUE index is the atomicity guarantee — try-INSERT with
catch-on-violation drives the short-circuit branch.

B-223 caveat (Round 3 deep-validation 2026-05-10)
================================================

The canonical DDL has **no Metadata JSON column**. The ``metadata`` parameter
on :func:`ledger_step` is accepted for forward-compatibility but is NOT
written to the ledger row in the current implementation. Step authors who
need metadata persistence should write to ``PipelineEventLog.Metadata`` via
``event_tracker`` (§ 6.3). B-223 tracks the future enhancement: either ALTER
add a ``Metadata`` column OR formalize the join-via-PipelineEventLog pattern.

The :class:`LedgerStep` ``prior_result`` field is correspondingly ``None``
in every current short-circuit case. Once B-223 lands, the field will be
populated from either the new ``Metadata`` column or a joined PipelineEventLog
row.

Idempotency contract (D15 + D17)
================================

Re-entry semantics by prior ``Status``:

- ``'COMPLETED'`` → yield ``LedgerStep(was_short_circuited=True)`` and skip
  the side-effecting work. This is the canonical recovery path.
- ``'IN_PROGRESS'`` → raise :class:`LedgerStepFailed` (concurrent worker OR
  stale row — startup-recovery-sweep handles staleness in the next process).
- ``'FAILED'`` → reset the row back to ``IN_PROGRESS`` and yield normally.
  The caller is retrying the step; the new attempt either ``COMPLETE``s
  (overwriting ``FAILED``) or fails again.

Startup recovery sweep (I19)
============================

:func:`startup_recovery_sweep` runs at process start. It finds
``IN_PROGRESS`` rows older than ``stale_threshold_minutes`` (default 60),
marks them ``FAILED`` with ``RecoveryAction='STARTUP_SWEEP_FAILED'`` and
``ErrorMessage='Stale on startup recovery sweep'``. If the sweep finds more
than ``max_stale_count`` (default 10) stale rows it raises
:class:`LedgerStuck` — a systemic-crash signal requiring operator review.

D-numbers consumed
==================

D15 (idempotency mandatory at every layer), D17 (ledger pattern), D67
(Tier 0 smoke), D68 (error class hierarchy), D69 (cursor_for ownership),
B-7 (retry pattern referenced by error classes), W-8 (Session-owned lock
auto-release — applies to any future sp_getapplock around the sweep).

B-numbers
=========

- Closes **B85** dependent via the ``utils.errors`` import surface.
- B-223 (open) — Metadata column absence + ``prior_result`` always-None caveat.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterator

import pyodbc

try:
    from utils.connections import cursor_for
except ImportError:
    # Fallback for legacy callers that placed ``connections`` at project root.
    from connections import cursor_for  # type: ignore[no-redef]

from utils.errors import (
    LedgerConfigError,
    LedgerStepFailed,
    LedgerStuck,
)

logger = logging.getLogger(__name__)

__all__ = [
    "LedgerStep",
    "ledger_step",
    "startup_recovery_sweep",
]


_VALID_STATUSES = frozenset({"IN_PROGRESS", "COMPLETED", "FAILED"})

# Maximum length of an ErrorMessage written to the ledger row. The column
# itself is NVARCHAR(MAX) but truncating defends against catastrophically
# large exception messages flooding the audit table.
_ERROR_MESSAGE_MAX_LEN = 4000

# pyodbc native error codes for UNIQUE / PK violation on SQL Server.
# 2627 = PK violation; 2601 = UNIQUE index violation.
_UNIQUE_VIOLATION_CODES = frozenset({2627, 2601})


@dataclass(frozen=True)
class LedgerStep:
    """Result of entering a :func:`ledger_step` context.

    :param step_id: ``General.ops.IdempotencyLedger.LedgerId`` of the row
        currently representing this step (may be a freshly-inserted row OR
        the existing row on short-circuit).
    :param was_short_circuited: ``True`` if a prior ``Status='COMPLETED'``
        row existed for this key. The caller MUST skip the side-effecting
        work when this is ``True``; the prior completion's outcome is the
        canonical result. ``False`` for fresh inserts AND for ``FAILED``
        retry resets (i.e. the work runs in both cases).
    :param prior_result: ``None`` until B-223 lands (Metadata column absence
        per § 4.1 + module docstring). Currently always ``None`` regardless
        of short-circuit. Future: JSON dict reconstructed from either a
        new ``Metadata`` column OR a joined ``PipelineEventLog.Metadata`` row.
    """

    step_id: int
    was_short_circuited: bool
    prior_result: dict[str, Any] | None


def _is_unique_violation(exc: pyodbc.IntegrityError) -> bool:
    """Return True if a pyodbc IntegrityError represents a UNIQUE violation.

    pyodbc maps SQL Server error 2627 (PK) / 2601 (UNIQUE index) to
    IntegrityError. Other IntegrityError variants (FK violation, CHECK
    failure) bubble up unchanged — those are caller bugs, not
    short-circuit signals.

    Heuristic uses the canonical SQL Server error phrases ("Violation of
    UNIQUE KEY constraint", "Violation of PRIMARY KEY constraint", "Cannot
    insert duplicate key") plus the parenthesized native codes 2627 / 2601.
    A bare "UNIQUE" substring (which can appear in FK violations like "FK
    references a UNIQUE index") is NOT sufficient.
    """
    args = exc.args
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


def _utcnow_ms() -> datetime:
    """Naive UTC datetime truncated to milliseconds.

    Matches the SCD2-P1-f invariant (naive, ms precision) so any future
    parameter binding against ``StartedAt`` / ``CompletedAt`` (both
    DATETIME2(3)) does not silently shift through DATETIMEOFFSET coercion.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    # Truncate microseconds → milliseconds to match DATETIME2(3) precision.
    return now.replace(microsecond=(now.microsecond // 1000) * 1000)


@contextmanager
def ledger_step(
    *,
    batch_id: int,
    source_name: str,
    table_name: str,
    event_type: str,
    metadata: dict[str, Any] | None = None,  # B-223 — accepted but not persisted
) -> Iterator[LedgerStep]:
    """Idempotent step gate per D15 + D17.

    Entry: ``INSERT`` ``IdempotencyLedger`` row with ``Status='IN_PROGRESS'``.
    On UNIQUE violation, ``SELECT`` the existing row and branch on its
    ``Status``:

    - ``'COMPLETED'`` — yield :class:`LedgerStep` with
      ``was_short_circuited=True``; caller skips side effects.
    - ``'IN_PROGRESS'`` — raise :class:`LedgerStepFailed` (concurrent worker
      OR stale row from a crash; the startup-recovery-sweep handles staleness
      in the next process invocation, so during a single run this is treated
      as a real concurrent attempt).
    - ``'FAILED'`` — ``UPDATE`` the row back to ``IN_PROGRESS`` (clearing
      ``CompletedAt``, ``ErrorMessage``, ``DurationMs``) and yield with
      ``was_short_circuited=False``. The caller retries the step.

    Exit (clean):
        ``UPDATE`` ``Status='COMPLETED'``, ``CompletedAt=SYSUTCDATETIME()``,
        ``DurationMs`` = wall-clock duration.

    Exit (exception):
        ``UPDATE`` ``Status='FAILED'``, ``CompletedAt=SYSUTCDATETIME()``,
        ``DurationMs``, ``ErrorMessage=str(exc)[:4000]``; re-raise the
        caller's exception unchanged (do NOT wrap in
        :class:`LedgerStepFailed` — see § 4.1 Error modes).

    :param batch_id: From :class:`PipelineBatchSequence` (D45.3). Must be a
        positive integer; ``0`` and negatives are rejected at the DB level
        but caller-side validation here catches the common
        ``BatchId is None`` typo before the round-trip.
    :param source_name: e.g. ``'DNA'``, ``'CCM'``, ``'EPICOR'``. Pipeline-
        wide ``SourceName`` enum from ``UdmTablesList``.
    :param table_name: e.g. ``'ACCT'``. Source table name; not the UDM
        derived names.
    :param event_type: Canonical values: ``'EXTRACT'``, ``'BCP_LOAD'``,
        ``'CDC_PROMOTION'``, ``'SCD2_PROMOTION'``, ``'PARQUET_WRITE'``,
        ``'REPLAY'``. Non-AM/PM jobs use their canonical JOB_NAME (see
        ``02_configuration.md`` § 5.3.6).
    :param metadata: Reserved for B-223. Accepted but NOT persisted to the
        ledger row. Pass ``None`` until B-223 lands. Per **B70 closure
        (2026-05-14, Round 6 § 7.2)**: passing a non-None value emits
        a :class:`DeprecationWarning` directing callers to
        ``event_tracker.track()`` for canonical metadata persistence.

    :raises LedgerStepFailed: concurrent ``IN_PROGRESS`` row exists.
    :raises LedgerConfigError: table missing / schema mismatch / unexpected
        ``Status`` value in the existing row.
    """
    # B70 closure (2026-05-14, Round 6 § 7.2) — DeprecationWarning on
    # non-None metadata. Until B-223 lands (Metadata column persistence),
    # the metadata kwarg is accept-and-discard, a "traceability beats
    # convenience" violation per pillar rubric. The warning routes
    # callers to event_tracker.track() for metadata persistence.
    if metadata is not None:
        import warnings
        warnings.warn(
            "ledger_step(metadata=...) is accept-and-discard until B-223 "
            "lands. Use event_tracker.track() to persist Metadata. The "
            "metadata kwarg will be removed in a future version.",
            DeprecationWarning,
            stacklevel=2,
        )
    if batch_id is None or batch_id <= 0:
        raise LedgerConfigError(
            "batch_id must be a positive integer (received {!r})".format(batch_id),
            metadata={"batch_id": batch_id},
        )
    if not source_name or not table_name or not event_type:
        raise LedgerConfigError(
            "source_name / table_name / event_type must all be non-empty strings",
            metadata={
                "source_name": source_name,
                "table_name": table_name,
                "event_type": event_type,
            },
        )

    started = _utcnow_ms()
    key_metadata = {
        "batch_id": batch_id,
        "source_name": source_name,
        "table_name": table_name,
        "event_type": event_type,
    }

    # ---- ENTRY: try INSERT, catch UNIQUE violation, branch on existing Status
    step_id: int
    was_short_circuited: bool

    try:
        with cursor_for("General") as cur:
            cur.execute(
                """
                INSERT INTO General.ops.IdempotencyLedger
                    (BatchId, SourceName, TableName, EventType, Status, StartedAt)
                OUTPUT INSERTED.LedgerId
                VALUES (?, ?, ?, ?, 'IN_PROGRESS', SYSUTCDATETIME())
                """,
                batch_id,
                source_name,
                table_name,
                event_type,
            )
            row = cur.fetchone()
            if row is None:
                raise LedgerConfigError(
                    "INSERT to IdempotencyLedger returned no row from OUTPUT clause; "
                    "table may be misconfigured or driver mis-bound.",
                    metadata=key_metadata,
                )
            step_id = int(row[0])
            was_short_circuited = False
            logger.debug(
                "ledger_step entry: inserted LedgerId=%d for %s/%s/%s",
                step_id, source_name, table_name, event_type,
            )
    except pyodbc.IntegrityError as exc:
        if not _is_unique_violation(exc):
            # Some other IntegrityError (FK, CHECK) — caller bug; bubble up.
            raise
        # UNIQUE violation: existing row owns this key. SELECT it.
        with cursor_for("General") as cur:
            cur.execute(
                """
                SELECT LedgerId, Status
                FROM General.ops.IdempotencyLedger
                WHERE BatchId = ? AND SourceName = ?
                  AND TableName = ? AND EventType = ?
                """,
                batch_id,
                source_name,
                table_name,
                event_type,
            )
            existing = cur.fetchone()
        if existing is None:
            # UNIQUE-violation-but-row-not-found is a phantom-write race
            # (rare; the DB indexer saw the row briefly but a concurrent
            # delete already removed it). Retryable per B-7.
            raise LedgerStepFailed(
                "UNIQUE violation but no row found on follow-up SELECT — "
                "phantom-write race",
                metadata=key_metadata,
            ) from exc
        existing_id = int(existing[0])
        existing_status = str(existing[1]).strip()

        if existing_status == "COMPLETED":
            # Short-circuit. Yield with the existing LedgerId; caller skips.
            logger.info(
                "ledger_step short-circuit: prior COMPLETED row LedgerId=%d "
                "for %s/%s/%s",
                existing_id, source_name, table_name, event_type,
            )
            yield LedgerStep(
                step_id=existing_id,
                was_short_circuited=True,
                prior_result=None,  # B-223 caveat
            )
            return  # do NOT UPDATE on clean exit; the prior COMPLETED is canonical
        elif existing_status == "IN_PROGRESS":
            raise LedgerStepFailed(
                "Concurrent IN_PROGRESS row exists for this key — another "
                "worker is in flight OR a stale row predates the startup sweep",
                metadata={**key_metadata, "existing_step_id": existing_id},
            )
        elif existing_status == "FAILED":
            # Retry path: reset row to IN_PROGRESS.
            with cursor_for("General") as cur:
                cur.execute(
                    """
                    UPDATE General.ops.IdempotencyLedger
                    SET Status = 'IN_PROGRESS',
                        StartedAt = SYSUTCDATETIME(),
                        CompletedAt = NULL,
                        DurationMs = NULL,
                        ErrorMessage = NULL,
                        RecoveryAction = NULL
                    WHERE LedgerId = ? AND Status = 'FAILED'
                    """,
                    existing_id,
                )
            step_id = existing_id
            was_short_circuited = False
            logger.info(
                "ledger_step retry: reset FAILED → IN_PROGRESS for "
                "LedgerId=%d, %s/%s/%s",
                step_id, source_name, table_name, event_type,
            )
        else:
            # CK_IdempotencyLedger_Status guarantees one of the three values
            # we already handled, so this branch is theoretically unreachable
            # unless the check constraint was disabled. Treat as fatal.
            raise LedgerConfigError(
                f"Unexpected Status {existing_status!r} on existing ledger row "
                f"(LedgerId={existing_id}). Check constraint may be disabled.",
                metadata={**key_metadata, "existing_status": existing_status},
            )

    # ---- YIELD to caller; metadata stashed in payload but not yet persisted (B-223)
    payload = LedgerStep(
        step_id=step_id,
        was_short_circuited=False,
        prior_result=None,
    )
    try:
        yield payload
    except BaseException as exc:
        # ---- EXIT (exception): mark FAILED, re-raise caller's exception verbatim
        duration_ms = int((_utcnow_ms() - started).total_seconds() * 1000)
        error_message = str(exc)[:_ERROR_MESSAGE_MAX_LEN]
        try:
            with cursor_for("General") as cur:
                cur.execute(
                    """
                    UPDATE General.ops.IdempotencyLedger
                    SET Status = 'FAILED',
                        CompletedAt = SYSUTCDATETIME(),
                        DurationMs = ?,
                        ErrorMessage = ?
                    WHERE LedgerId = ?
                    """,
                    duration_ms,
                    error_message,
                    step_id,
                )
        except Exception:
            # Never let a ledger-side cleanup failure hide the caller's
            # original exception. Log + continue to re-raise.
            logger.exception(
                "Failed to UPDATE LedgerId=%d to FAILED; caller's exception "
                "will be re-raised regardless.",
                step_id,
            )
        raise
    else:
        # ---- EXIT (clean): mark COMPLETED
        duration_ms = int((_utcnow_ms() - started).total_seconds() * 1000)
        with cursor_for("General") as cur:
            cur.execute(
                """
                UPDATE General.ops.IdempotencyLedger
                SET Status = 'COMPLETED',
                    CompletedAt = SYSUTCDATETIME(),
                    DurationMs = ?
                WHERE LedgerId = ?
                """,
                duration_ms,
                step_id,
            )
        logger.debug(
            "ledger_step clean exit: COMPLETED LedgerId=%d (%d ms) for %s/%s/%s",
            step_id, duration_ms, source_name, table_name, event_type,
        )

    # The unused metadata reference silences linters that flag unused params.
    # The parameter is part of the public contract per § 4.1 and will be
    # persisted once B-223 lands. The non-None case has already emitted
    # a DeprecationWarning at function entry per B70 (Round 6 § 7.2).
    del metadata


def startup_recovery_sweep(
    *,
    stale_threshold_minutes: int = 60,
    max_stale_count: int = 10,
) -> int:
    """Mark stale ``IN_PROGRESS`` ledger rows as ``FAILED`` per I19.

    At process start, scan ``General.ops.IdempotencyLedger`` for rows whose
    ``Status='IN_PROGRESS'`` AND ``StartedAt`` is older than the threshold.
    UPDATE each row to ``Status='FAILED'`` with
    ``ErrorMessage='Stale on startup recovery sweep'`` and
    ``RecoveryAction='STARTUP_SWEEP_FAILED'`` so the audit trail distinguishes
    sweep-induced FAILED rows from in-band caller failures.

    Returns the number of rows swept. Raises :class:`LedgerStuck` if the
    count exceeds ``max_stale_count`` — a signal the prior process crashed
    pathologically; operator review required before proceeding.

    Idempotent: re-running the sweep on already-swept rows is a no-op
    (the row's Status is already ``FAILED`` and the WHERE clause excludes it).

    :param stale_threshold_minutes: How old (in minutes) an ``IN_PROGRESS``
        row must be before it qualifies for sweeping. Default 60. Tune
        upward if long-running steps legitimately exceed this duration.
    :param max_stale_count: Maximum stale rows tolerated before raising
        :class:`LedgerStuck`. Default 10 per § 4.1.

    :raises LedgerStuck: more than ``max_stale_count`` stale rows found.
    :raises LedgerConfigError: table missing / schema mismatch.
    """
    if stale_threshold_minutes <= 0:
        raise LedgerConfigError(
            f"stale_threshold_minutes must be positive (received "
            f"{stale_threshold_minutes})",
        )
    if max_stale_count < 0:
        raise LedgerConfigError(
            f"max_stale_count must be non-negative (received {max_stale_count})",
        )

    with cursor_for("General") as cur:
        # Use the filtered IX_IdempotencyLedger_Stuck index per § 7 DDL.
        cur.execute(
            """
            SELECT COUNT(*)
            FROM General.ops.IdempotencyLedger
            WHERE Status = 'IN_PROGRESS'
              AND StartedAt < DATEADD(MINUTE, -?, SYSUTCDATETIME())
            """,
            stale_threshold_minutes,
        )
        row = cur.fetchone()
        stale_count = int(row[0]) if row else 0

    if stale_count == 0:
        logger.info("startup_recovery_sweep: no stale rows")
        return 0

    if stale_count > max_stale_count:
        logger.error(
            "startup_recovery_sweep: %d stale rows exceeds max_stale_count=%d "
            "— raising LedgerStuck (operator intervention required)",
            stale_count, max_stale_count,
        )
        raise LedgerStuck(
            f"Startup sweep found {stale_count} stale IN_PROGRESS rows "
            f"(threshold {stale_threshold_minutes} min, max tolerated "
            f"{max_stale_count}). Pathological prior-process crash signal.",
            metadata={
                "stale_count": stale_count,
                "stale_threshold_minutes": stale_threshold_minutes,
                "max_stale_count": max_stale_count,
            },
        )

    # Stale count > 0 and <= max — proceed with sweep.
    with cursor_for("General") as cur:
        cur.execute(
            """
            UPDATE General.ops.IdempotencyLedger
            SET Status = 'FAILED',
                CompletedAt = SYSUTCDATETIME(),
                ErrorMessage = 'Stale on startup recovery sweep',
                RecoveryAction = 'STARTUP_SWEEP_FAILED'
            WHERE Status = 'IN_PROGRESS'
              AND StartedAt < DATEADD(MINUTE, -?, SYSUTCDATETIME())
            """,
            stale_threshold_minutes,
        )
        rows_affected = cur.rowcount

    logger.warning(
        "startup_recovery_sweep: marked %d stale IN_PROGRESS row(s) as FAILED "
        "with RecoveryAction='STARTUP_SWEEP_FAILED' (threshold %d min)",
        rows_affected, stale_threshold_minutes,
    )
    return int(rows_affected)
