"""PipelineEventTracker v2: per-step audit rows to General.ops.PipelineEventLog.

This is the v2 of the tracker per phase1/03_core_modules.md section 6.3.
It REPLACES the pre-Phase-1 v1 module while preserving the v1 public API
so every existing caller (main_small_tables / main_large_tables /
main_file_extract / orchestration / tools/backfill) continues working
unchanged.

What changed v1 to v2
=====================

- Context source: v2 exposes module-level contextvars (_batch_id_ctx /
  _table_name_ctx / _source_name_ctx) and helper APIs set_event_context /
  clear_event_context. These parallel observability.log_handler so a
  pipeline-step boundary that calls both set_log_context and
  set_event_context gets consistent BatchId / TableName / SourceName
  across PipelineLog AND PipelineEventLog rows.
- Cooperative cancellation (D33): heartbeat-frequency polling against
  PipelineExecutionGate.CancellationRequested. The v2 tracker queries
  the gate flag once per track() invocation (i.e. once per step, NOT
  once per log line per the spec note that poll-per-step is reasonable
  for event_tracker which runs per-step, not per-log-line). When set,
  the in-progress event status flips to SKIPPED with EventDetail of
  cancellation_acked on exit; pipeline orchestrators inspect
  event.cancellation_requested to decide whether to abort the run.
- M14 SensitiveDataFilter applied to event.metadata JSON (P5
  enforcement on the audit row). The redaction runs at write time on
  the serialized JSON string, so all metadata fields including ones
  serialized lazily inside the with-block are redacted before
  reaching the PipelineEventLog row.
- Explicit conn.commit() per OBS-5 on every write (preserved from v1;
  documented as load-bearing here for forward-compat).
- PipelineEventLog INSERT uses the canonical column shape (the v1 INSERT
  shape continues to work: DEFAULTs on Round 1 DDL fill CycleType /
  CycleDate / ServerRole / CreatedAt) but v2 explicitly threads cycle
  context if set on the event.

What stayed v1 to v2 (load-bearing invariants: DO NOT REGRESS)
==============================================================

- Public class name + constructor signature: PipelineEventTracker() with
  no required arguments continues to work. Callers that obtained the
  batch id via tracker.batch_id still get a lazy-allocated
  PipelineBatchSequence id.
- Track API: with tracker.track(event_type, table_config) as event:
  yields a mutable PipelineEvent dataclass with the original v1
  attribute surface (rows_processed / rows_inserted / rows_updated /
  rows_deleted / rows_unchanged / rows_before / rows_after /
  table_created / metadata / event_detail / status / error_message).
- OBS-3 SKIPPED status preservation: when caller sets
  event.status = SKIPPED inside the with-block, the tracker writes
  SKIPPED on clean exit (v1 logic preserved). v2 ADDS automatic SKIPPED
  on cancellation acknowledgment.
- OBS-5 explicit conn.commit() after the INSERT.
- OBS-7 JSON-merge pattern: callers use json.loads(event.metadata) if
  event.metadata else dict, merge, json.dumps and assign back to
  event.metadata. v2 preserves this: the M14 redaction is applied on
  top of whatever JSON the caller produced, so the merge contract is
  unchanged.
- Failure of the audit-write does NOT raise into the caller exception
  handling: log to stderr + module logger (per D68 + OBS-4 pattern
  from M15).

D-numbers consumed
==================

- D31 Power BI dashboards read PipelineEventLog directly (this
  tracker is the only writer)
- D33 cooperative cancellation (gate flag polling at heartbeat)
- D62 CCL audit-trail (every event row IS a CCL compliance trace)
- D67 Tier 0 smoke required
- D68 tracker-side errors logged to stderr; never raise into the
  caller exception path
- P5  SensitiveDataFilter applied to event.metadata JSON

References
==========

- phase1/03_core_modules.md section 6.3 (v2 canonical interface)
- phase1/03_core_modules.md section 6.1 (M14 SensitiveDataFilter)
- phase1/01_database_schema.md section 1 (PipelineEventLog DDL + Status
  enum IN_PROGRESS / SUCCESS / FAILED / SKIPPED)
- phase1/01_database_schema.md section 4 (PipelineExecutionGate
  CancellationRequested column)
- CLAUDE.md OBS-1 through OBS-7 (existing observability invariants)

Threading
=========

- contextvars.ContextVar propagates through asyncio tasks AND
  multiprocessing-worker copies seen in main_tables.py. Per-instance
  state on PipelineEventTracker is per-process (multiprocessing workers
  spawn separate processes per D69) so cross-thread state is not a
  concern; the contextvars layer handles the per-task scoping.
"""

from __future__ import annotations

import logging
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Iterator

if TYPE_CHECKING:
    from orchestration.table_config import TableConfig

logger = logging.getLogger(__name__)

__all__ = [
    "PipelineEvent",
    "PipelineEventTracker",
    "set_event_context",
    "clear_event_context",
    "skip",
]


# ---------------------------------------------------------------------------
# Module-level context vars per spec section 6.3 (parallel to M15
# log_handler.set_log_context). Pipeline orchestrators set these at each
# step boundary; the tracker track() context manager reads them so the
# audit row carries consistent BatchId / TableName / SourceName.
# ---------------------------------------------------------------------------


_batch_id_ctx: ContextVar[int | None] = ContextVar("event_batch_id", default=None)
_table_name_ctx: ContextVar[str | None] = ContextVar("event_table_name", default=None)
_source_name_ctx: ContextVar[str | None] = ContextVar(
    "event_source_name", default=None
)
_gate_id_ctx: ContextVar[int | None] = ContextVar("event_gate_id", default=None)


def set_event_context(
    *,
    batch_id: int,
    table_name: str | None = None,
    source_name: str | None = None,
    gate_id: int | None = None,
) -> None:
    """Set the per-thread / per-async-task event-tracker context.

    Subsequent calls to PipelineEventTracker.track resolve BatchId /
    TableName / SourceName from these contextvars when the explicit
    table_config arg leaves them unset (v1 callers still pass
    table_config; v2 callers can rely on the contextvars).

    gate_id is the PipelineExecutionGate row id (per Round 2 section 5.3).
    When set, cooperative cancellation polling (D33) is enabled: the
    tracker queries CancellationRequested on the gate row at the start
    of each track() invocation. When None (the default), the
    cancellation poll is skipped; pipelines that are not gate-managed
    (e.g. one-off ad-hoc reconciliation) do not pay the query cost.
    """
    _batch_id_ctx.set(batch_id)
    _table_name_ctx.set(table_name)
    _source_name_ctx.set(source_name)
    _gate_id_ctx.set(gate_id)


def clear_event_context() -> None:
    """Clear the event context.

    Call at pipeline-step exit so subsequent unrelated track() calls do
    not carry stale BatchId / TableName / SourceName / gate_id values.
    """
    _batch_id_ctx.set(None)
    _table_name_ctx.set(None)
    _source_name_ctx.set(None)
    _gate_id_ctx.set(None)


# ---------------------------------------------------------------------------
# Default filter wiring: M14 SensitiveDataFilter applied to metadata JSON
# at write time. Per P5: do not let plaintext PII reach PipelineEventLog
# rows via the Metadata column. Failure to install is logged to stderr
# (operator visibility) but is non-fatal: the event still writes.
# ---------------------------------------------------------------------------


def _make_metadata_redactor():
    """Return a callable redactor(text: str) -> str from M14 patterns.

    Falls back to identity (no-op) if the M14 module cannot be imported
    (early-boot / test isolation / dependency hiccup). The fallback is
    logged to stderr once per process so operators see the gap: P5 is
    a hard invariant but losing the audit row entirely would be worse
    than emitting it un-redacted (cf. the M15 SensitiveDataFilter
    fallback rationale).
    """
    try:
        from observability.sensitive_data_filter import _redact

        return _redact
    except Exception as exc:  # noqa: BLE001
        print(
            f"[PipelineEventTracker] WARNING: failed to install metadata "
            f"redactor (M14): {exc!r}. Event Metadata JSON is NOT being "
            f"P5-redacted on this process: install manually if needed.",
            file=sys.stderr,
        )

        def _identity(text: str) -> str:
            return text

        return _identity


# ---------------------------------------------------------------------------
# Event dataclass: mutable surface the caller populates inside the
# with block.
# ---------------------------------------------------------------------------


@dataclass
class PipelineEvent:
    """Mutable event row: pipeline code sets counters inside the with block.

    v1 attribute surface preserved verbatim (every field that v1 callers
    set continues to work). v2 additions are appended at the bottom; v1
    callers ignore them.

    Status values MUST be in the Round 1 CK_PipelineEventLog_Status enum
    per Pitfall 9 (IN_PROGRESS / SUCCESS / FAILED / SKIPPED).
    """

    # v1 surface (DO NOT REGRESS)
    event_type: str
    table_name: str | None
    source_name: str | None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: float = 0.0
    status: str = "IN_PROGRESS"
    error_message: str | None = None
    event_detail: str | None = None
    rows_processed: int = 0
    rows_inserted: int = 0
    rows_updated: int = 0
    rows_deleted: int = 0
    rows_unchanged: int = 0
    rows_before: int = 0
    rows_after: int = 0
    table_created: bool = False
    metadata: str | None = None
    rows_per_second: float = 0.0

    # v2 additions (callers may inspect but defaults preserve v1
    # behavior verbatim)
    cycle_type: str | None = None
    cycle_date: Any | None = None  # date or datetime per call-site
    server_role: str | None = None

    # Set to True by the cooperative cancellation poll (D33) when the
    # gate flag is observed. Callers inspect this AFTER the with-block
    # to decide whether to abort the rest of the pipeline.
    cancellation_requested: bool = False


# ---------------------------------------------------------------------------
# Cancellation polling (D33).
# ---------------------------------------------------------------------------


def _check_cancellation(gate_id: int | None) -> bool:
    """Return True if the gate row has CancellationRequested = 1.

    Best-effort: any failure to query the gate table returns False so a
    transient DB drop does NOT cause every event to flip to SKIPPED.
    The query is a single row read against an indexed PK so the lookup
    is O(1). gate_id is None for ad-hoc pipelines not managed by
    PipelineExecutionGate: skip the query entirely.

    Per spec section 6.3: poll-per-step is REASONABLE for event_tracker
    (not per-log-line, which would multiply DB load). Each track()
    invocation does one query.
    """
    if gate_id is None:
        return False
    try:
        from utils.connections import cursor_for

        with cursor_for("General") as cur:
            cur.execute(
                "SELECT CancellationRequested "
                "FROM General.ops.PipelineExecutionGate "
                "WHERE GateId = ?",
                gate_id,
            )
            row = cur.fetchone()
            if row is None:
                return False
            return bool(row[0])
    except Exception:  # noqa: BLE001
        logger.debug(
            "Cancellation check failed for GateId=%s (treating as no-cancel)",
            gate_id,
            exc_info=True,
        )
        return False


# ---------------------------------------------------------------------------
# Tracker class.
# ---------------------------------------------------------------------------


class PipelineEventTracker:
    """Write per-step audit rows to General.ops.PipelineEventLog.

    v1 usage (still supported via table_config positional arg):

        tracker = PipelineEventTracker()
        with tracker.track("EXTRACT", table_config) as event:
            df = extract_from_source(table_config)
            event.rows_processed = len(df)

    v2 usage (preferred: contextvars + optional table_config=None):

        from observability.event_tracker import (
            PipelineEventTracker, set_event_context, clear_event_context,
        )

        tracker = PipelineEventTracker()
        set_event_context(
            batch_id=tracker.batch_id,
            table_name="ACCT",
            source_name="DNA",
            gate_id=gate_row_id,
        )
        try:
            with tracker.track("EXTRACT") as event:
                event.rows_processed = ...
        finally:
            clear_event_context()

    Both code paths read the table identity from table_config when
    provided; if table_config is None (v2 path), the tracker reads
    BatchId / TableName / SourceName from contextvars.

    Per OBS-3: callers may set event.status = SKIPPED inside the
    with-block; the tracker preserves the explicit status. Per D33: if
    the gate flag is set BEFORE the with-block enters, the tracker
    automatically marks the event SKIPPED with EventDetail set to
    cancellation_acked and sets event.cancellation_requested=True so
    the caller can short-circuit subsequent steps.
    """

    def __init__(self) -> None:
        self._batch_id: int | None = None
        # Metadata redactor lazily constructed at first event write so
        # module import does not trigger sensitive_data_filter side effects.
        self._metadata_redactor = None

    @property
    def batch_id(self) -> int:
        """Return the BatchId; allocate from PipelineBatchSequence on first read."""
        if self._batch_id is None:
            ctx_batch_id = _batch_id_ctx.get()
            if ctx_batch_id is not None:
                # v2: if a caller set the batch_id via set_event_context,
                # prefer that over allocating a fresh one (e.g. a tool
                # that is part of an enclosing pipeline run).
                self._batch_id = ctx_batch_id
            else:
                self._batch_id = self._get_next_batch_id()
        return self._batch_id

    @staticmethod
    def _get_next_batch_id() -> int:
        """Allocate a fresh BatchId from General.ops.PipelineBatchSequence.

        Mirrors v1 implementation. Explicit commit per OBS-5.
        """
        from utils.connections import get_general_connection

        conn = get_general_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SET NOCOUNT ON; "
                "INSERT INTO ops.PipelineBatchSequence DEFAULT VALUES; "
                "SELECT SCOPE_IDENTITY();"
            )
            row = cursor.fetchone()
            batch_id = int(row[0])
            cursor.close()
            conn.commit()
            return batch_id
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    @staticmethod
    def _resolve_table_identity(
        table_config: "TableConfig | None",
    ) -> tuple[str | None, str | None]:
        """Resolve (table_name, source_name): prefer table_config, fall
        back to contextvars set via set_event_context.
        """
        if table_config is not None:
            return (
                getattr(table_config, "source_object_name", None),
                getattr(table_config, "source_name", None),
            )
        return (_table_name_ctx.get(), _source_name_ctx.get())

    @contextmanager
    def track(
        self,
        event_type: str,
        table_config: "TableConfig | None" = None,
        *,
        event_detail: str | None = None,
    ) -> Iterator[PipelineEvent]:
        """Wrap a pipeline step; yield a mutable PipelineEvent.

        On entry: starts a wall-clock timer; checks D33 cancellation
        flag (if gate_id is set in contextvars). On clean exit: status
        becomes SUCCESS (unless the caller explicitly set SKIPPED).
        On exception: status becomes FAILED; the caller exception is
        re-raised verbatim.

        Per OBS-5: a single PipelineEventLog INSERT happens after the
        with-block exits, with explicit conn.commit(). Failure of the
        audit-write does NOT raise: it is logged to module logger +
        stderr (D68 + OBS-4 pattern).

        Per P5: event.metadata (when set) is run through the M14
        SensitiveDataFilter at write time. The redaction is applied to
        the FINAL serialized JSON string; callers continue to use the
        OBS-7 json.loads / json.dumps merge pattern as before.
        """
        table_name, source_name = self._resolve_table_identity(table_config)
        gate_id = _gate_id_ctx.get()

        event = PipelineEvent(
            event_type=event_type,
            table_name=table_name,
            source_name=source_name,
            event_detail=event_detail,
        )
        event.started_at = datetime.now(timezone.utc)

        # D33 cancellation poll (entry).
        # If the gate already shows CancellationRequested = 1 BEFORE the
        # step begins, we mark the event SKIPPED and skip the work. The
        # gate write to the gate row CancellationAcknowledgedAt is the
        # responsibility of SP-6 (gate-level acknowledge): the
        # event_tracker only records the SKIPPED audit row + sets the
        # event.cancellation_requested flag for the caller.
        if _check_cancellation(gate_id):
            event.cancellation_requested = True
            event.status = "SKIPPED"
            event.event_detail = event.event_detail or "cancellation_acked"
            try:
                yield event
            finally:
                event.completed_at = datetime.now(timezone.utc)
                event.duration_ms = (
                    event.completed_at - event.started_at
                ).total_seconds() * 1000
                self._write_event(event)
            return

        # Normal path.
        try:
            yield event
            # OBS-3: preserve explicitly-set non-SUCCESS statuses.
            if event.status == "IN_PROGRESS":
                event.status = "SUCCESS"
            elif event.status not in ("SUCCESS", "FAILED", "SKIPPED"):
                # Defensive: a caller that set an out-of-enum status
                # gets corrected to SUCCESS so the row passes
                # CK_PipelineEventLog_Status. Log a warning so the bug
                # is visible.
                logger.warning(
                    "PipelineEvent.status=%r is not in the Round 1 enum "
                    "(IN_PROGRESS/SUCCESS/FAILED/SKIPPED); forcing SUCCESS",
                    event.status,
                )
                event.status = "SUCCESS"
        except BaseException as exc:
            event.status = "FAILED"
            event.error_message = str(exc)[:4000]
            raise
        finally:
            event.completed_at = datetime.now(timezone.utc)
            event.duration_ms = (
                event.completed_at - event.started_at
            ).total_seconds() * 1000
            if event.duration_ms > 0 and event.rows_processed > 0:
                event.rows_per_second = event.rows_processed / (
                    event.duration_ms / 1000
                )
            self._write_event(event)

    def _write_event(self, event: PipelineEvent) -> None:
        """INSERT a PipelineEventLog row for the populated event.

        Per OBS-5: explicit conn.commit() after the INSERT. Per OBS-4
        pattern (M15 precedent): write failures print to stderr + log
        but NEVER raise into the caller exception path: observability
        must not crash the pipeline.

        Per P5: event.metadata is redacted via M14 SensitiveDataFilter
        before being written. Redaction is best-effort: if the M14
        module is unavailable, the metadata writes un-redacted with a
        single stderr warning per process (see _make_metadata_redactor).
        """
        try:
            from utils.connections import get_general_connection

            if self._metadata_redactor is None:
                self._metadata_redactor = _make_metadata_redactor()

            metadata_to_write: str | None = event.metadata
            if metadata_to_write:
                try:
                    metadata_to_write = self._metadata_redactor(metadata_to_write)
                except Exception:  # noqa: BLE001
                    # M14 contract says return-always but defense-in-depth:
                    # preserve the un-redacted metadata if the call blows up.
                    logger.exception(
                        "M14 SensitiveDataFilter raised during event "
                        "metadata redaction; writing un-redacted metadata"
                    )

            conn = get_general_connection()
            try:
                cursor = conn.cursor()
                if (
                    event.cycle_type is not None
                    or event.cycle_date is not None
                    or event.server_role is not None
                ):
                    cursor.execute(
                        """
                        INSERT INTO ops.PipelineEventLog (
                            BatchId, TableName, SourceName, EventType, EventDetail,
                            StartedAt, CompletedAt, DurationMs, Status, ErrorMessage,
                            RowsProcessed, RowsInserted, RowsUpdated, RowsDeleted,
                            RowsUnchanged, RowsBefore, RowsAfter, TableCreated,
                            Metadata, RowsPerSecond,
                            CycleType, CycleDate, ServerRole
                        ) VALUES (
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            ?, ?, ?, ?, ?
                        )
                        """,
                        self.batch_id,
                        event.table_name,
                        event.source_name,
                        event.event_type,
                        event.event_detail,
                        event.started_at,
                        event.completed_at,
                        int(event.duration_ms),
                        event.status,
                        event.error_message,
                        event.rows_processed,
                        event.rows_inserted,
                        event.rows_updated,
                        event.rows_deleted,
                        event.rows_unchanged,
                        event.rows_before,
                        event.rows_after,
                        1 if event.table_created else 0,
                        metadata_to_write,
                        round(event.rows_per_second, 2),
                        event.cycle_type,
                        event.cycle_date,
                        event.server_role,
                    )
                else:
                    # v1 INSERT shape: preserved verbatim for callers
                    # that do not thread cycle context.
                    cursor.execute(
                        """
                        INSERT INTO ops.PipelineEventLog (
                            BatchId, TableName, SourceName, EventType, EventDetail,
                            StartedAt, CompletedAt, DurationMs, Status, ErrorMessage,
                            RowsProcessed, RowsInserted, RowsUpdated, RowsDeleted,
                            RowsUnchanged, RowsBefore, RowsAfter, TableCreated,
                            Metadata, RowsPerSecond
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        self.batch_id,
                        event.table_name,
                        event.source_name,
                        event.event_type,
                        event.event_detail,
                        event.started_at,
                        event.completed_at,
                        int(event.duration_ms),
                        event.status,
                        event.error_message,
                        event.rows_processed,
                        event.rows_inserted,
                        event.rows_updated,
                        event.rows_deleted,
                        event.rows_unchanged,
                        event.rows_before,
                        event.rows_after,
                        1 if event.table_created else 0,
                        metadata_to_write,
                        round(event.rows_per_second, 2),
                    )
                cursor.close()
                conn.commit()
            finally:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass
        except Exception as write_err:  # noqa: BLE001
            # OBS-4 pattern (M15 precedent): surface failure to stderr +
            # logger.exception. NEVER raise into the caller exception
            # path: observability must not crash the pipeline.
            logger.exception("Failed to write event to PipelineEventLog")
            try:
                print(
                    f"[PipelineEventTracker] WRITE FAILED (event_type="
                    f"{event.event_type!r}, table={event.table_name!r}): "
                    f"{write_err}",
                    file=sys.stderr,
                )
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Stand-alone helper: kept for symmetry with the section 6.3 spec.
# Operational tools that emit a single SKIPPED row WITHOUT entering a
# tracker can go through this path.
# ---------------------------------------------------------------------------


def skip(
    *,
    event_type: str,
    table_name: str | None,
    source_name: str | None,
    batch_id: int,
    reason: str,
) -> None:
    """Write a single SKIPPED PipelineEventLog row (OBS-3 standalone path).

    Used when a step is skipped BEFORE the with-block can be entered
    (e.g. lock not acquired: the orchestrator wants the audit row but
    never runs the work). Single INSERT; explicit commit per OBS-5.
    Errors are logged + printed to stderr; never raised.
    """
    now = datetime.now(timezone.utc)
    try:
        from utils.connections import get_general_connection

        conn = get_general_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO ops.PipelineEventLog (
                    BatchId, TableName, SourceName, EventType, EventDetail,
                    StartedAt, CompletedAt, DurationMs, Status,
                    RowsProcessed, RowsInserted, RowsUpdated, RowsDeleted,
                    RowsUnchanged, RowsBefore, RowsAfter, TableCreated,
                    Metadata, RowsPerSecond
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                batch_id,
                table_name,
                source_name,
                event_type,
                reason,
                now,
                now,
                0,
                "SKIPPED",
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                None,
                0.0,
            )
            cursor.close()
            conn.commit()
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "Failed to write SKIPPED event for %s/%s", table_name, event_type
        )
        try:
            print(
                f"[PipelineEventTracker.skip] WRITE FAILED ({event_type!r}, "
                f"table={table_name!r}): {exc}",
                file=sys.stderr,
            )
        except Exception:  # noqa: BLE001
            pass
