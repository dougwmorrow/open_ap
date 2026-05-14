"""SqlServerLogHandler v2: custom logging.Handler -> General.ops.PipelineLog.

This is the v2 of the handler per phase1/03_core_modules.md section 6.2. It
REPLACES the pre-Phase-1 v1 module while preserving the v1 public API so
existing callers continue working unchanged.

What changed v1 -> v2
=====================

- Context source: v2 reads BatchId / TableName / SourceName from
  module-level contextvars.ContextVar instances (set via set_log_context /
  clear_log_context). v1 stored them on threading.local via
  handler.set_context(...). v2 preserves the v1 set_context instance
  method so v1 callers still work -- the emit path reads contextvars
  first, falls back to the v1 thread-local.
- Filter wiring: v2 installs observability.sensitive_data_filter.
  SensitiveDataFilter (M14) on the handler by default. Disable only with
  explicit install_default_filter=False and a P5 review.
- Module import resilience: M14 install is best-effort -- if the filter
  module is unavailable (early-boot, test isolation), the handler still
  constructs and emits raw records. Operators should see the M14 module
  load before any pipeline log lines emit; the resilience is defense-in-
  depth, not the contract.

What stayed v1 -> v2 (load-bearing invariants -- DO NOT REGRESS)
================================================================

- Public class name + constructor signature: SqlServerLogHandler(level=
  logging.INFO) continues to work.
- OBS-4 buffer size = 10: WARNING+ records flush immediately regardless
  of buffer fill. Narrow crash-loss window: at most 9 INFO/DEBUG entries
  can be lost on SIGKILL.
- OBS-4 stderr on flush failure: conn.commit failures, transient DB
  drops, or any flush exception is printed to sys.stderr -- NEVER
  silently swallowed. Operator must see the loss count.
- OBS-5 explicit conn.commit(): _flush_buffer calls commit after the
  executemany. Do not rely on autocommit configuration -- future config
  drift must not break observability.
- handleError fallback: emit() never raises into the logging machinery;
  self.handleError(record) is the catch-all per logging.Handler contract.

D-numbers consumed
==================

- D31 -- Power BI dashboards read PipelineLog directly (this handler is
  the only writer)
- D67 -- Tier 0 smoke required
- D68 -- handler-side errors logged to stderr; never raise into emit()
- P5  -- SensitiveDataFilter installed by default

References
==========

- phase1/03_core_modules.md section 6.2 (v2 canonical interface)
- phase1/03_core_modules.md section 6.1 (M14 SensitiveDataFilter)
- phase1/01_database_schema.md PipelineLog DDL (the insert target)
- CLAUDE.md OBS-4 / OBS-5 / OBS-6 / OBS-7 (existing invariants)

Threading
=========

- contextvars.ContextVar propagates through asyncio tasks AND the
  multiprocessing-worker copies seen in main_*_tables.py. The per-buffer
  lock (self._buffer_lock) is a threading.Lock so concurrent emits
  within a process are serialized.
- v1's threading.local is preserved for back-compat: callers using
  handler.set_context(...) continue to read their per-thread value via
  the same instance attribute.
"""

from __future__ import annotations

import logging
import sys
import threading
import traceback
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Optional

# Connections is imported lazily inside _flush_buffer so that constructing
# the handler does NOT require the connections module to be importable
# (early-boot / unit-test isolation). See OBS-4 / OBS-5.

__all__ = [
    "SqlServerLogHandler",
    "set_log_context",
    "clear_log_context",
]


# ---------------------------------------------------------------------------
# Module-level context vars per spec section 6.2.
# ---------------------------------------------------------------------------

_batch_id_ctx: ContextVar[Optional[int]] = ContextVar("batch_id", default=None)
_table_name_ctx: ContextVar[Optional[str]] = ContextVar("table_name", default=None)
_source_name_ctx: ContextVar[Optional[str]] = ContextVar("source_name", default=None)


def set_log_context(
    *,
    batch_id: int,
    table_name: str | None = None,
    source_name: str | None = None,
) -> None:
    """Set the per-thread / per-async-task log context.

    Subsequent log records emitted by handlers in this context include the
    BatchId / TableName / SourceName in their PipelineLog rows. Callers
    should call this at the start of each pipeline-step boundary (e.g.
    when a table begins processing) and clear_log_context() at the exit.

    Per spec section 6.2 -- batch_id is REQUIRED; the handler skips records
    whose batch_id is None (defensive against an early-startup log line
    emitting before a batch is allocated).
    """
    _batch_id_ctx.set(batch_id)
    _table_name_ctx.set(table_name)
    _source_name_ctx.set(source_name)


def clear_log_context() -> None:
    """Clear the log context.

    Call at pipeline-step exit so subsequent unrelated log lines do not
    carry stale BatchId / TableName / SourceName values.
    """
    _batch_id_ctx.set(None)
    _table_name_ctx.set(None)
    _source_name_ctx.set(None)


# ---------------------------------------------------------------------------
# Default filter wiring -- M14 SensitiveDataFilter.
# ---------------------------------------------------------------------------


def _make_default_filter() -> Optional[logging.Filter]:
    """Return a freshly-constructed SensitiveDataFilter from M14, or None
    if the module can't be imported (early-boot / test isolation).

    Failure to install the filter is logged to stderr -- operators should
    investigate immediately because P5 (no plaintext in logs) is the
    canonical invariant. A handler without the filter is a defense-in-
    depth gap, NOT a hard fault -- log lines still emit.
    """
    try:
        from observability.sensitive_data_filter import SensitiveDataFilter

        return SensitiveDataFilter()
    except Exception as exc:  # noqa: BLE001
        print(
            f"[SqlServerLogHandler] WARNING: failed to install default "
            f"SensitiveDataFilter (M14): {exc!r}. P5 redaction is NOT "
            f"active on this handler -- install manually via .addFilter().",
            file=sys.stderr,
        )
        return None


# ---------------------------------------------------------------------------
# Handler.
# ---------------------------------------------------------------------------


class SqlServerLogHandler(logging.Handler):
    """Custom logging handler that writes log records to General.ops.PipelineLog.

    v2 usage (preferred -- contextvars):

        from observability.log_handler import (
            SqlServerLogHandler, set_log_context, clear_log_context,
        )

        handler = SqlServerLogHandler()
        logging.getLogger().addHandler(handler)

        set_log_context(batch_id=42, table_name="ACCT", source_name="DNA")
        try:
            logger.info("processing started")
        finally:
            clear_log_context()

    v1 usage (still supported -- thread-local set_context):

        handler = SqlServerLogHandler()
        handler.set_context(batch_id=42, table_name="ACCT", source_name="DNA")
        logging.getLogger().addHandler(handler)
        logger.info("processing started")

    The emit() path reads contextvars FIRST; if batch_id is still None
    (the v2 contextvars default), it falls back to the v1 thread-local
    set via handler.set_context(...).

    Buffering (OBS-4): up to buffer_size (default 10) records buffered
    before flush. WARNING+ records flush immediately regardless of buffer
    state -- the most diagnostically valuable lines and the most likely
    to be lost on crash.

    Flush failures (OBS-4): printed to sys.stderr with the lost-row
    count. Never silently swallowed; never raised into the logging
    machinery (would crash the calling code via logging's defaults).

    Explicit commit (OBS-5): every flush calls conn.commit(). Do not
    rely on autocommit -- future config drift must not break observability.

    Default filter (P5): observability.sensitive_data_filter.
    SensitiveDataFilter (M14) is installed unless
    install_default_filter=False. Disable only with explicit P5 review.
    """

    def __init__(
        self,
        level: int = logging.INFO,
        *,
        buffer_size: int = 10,
        install_default_filter: bool = True,
    ) -> None:
        """Construct the handler.

        :param level: minimum log level to handle (records below are
            dropped before emit is called by the logging machinery).
            Default INFO retains the v1 default.
        :param buffer_size: maximum buffered records before flush.
            Default 10 per OBS-4 (reduced from 50 to narrow crash-loss
            window). The buffer is bypassed on WARNING+ regardless of
            this value.
        :param install_default_filter: whether to install the M14
            SensitiveDataFilter on this handler at construction. Default
            True. Disable only with explicit P5 review.
        """
        super().__init__(level)

        # v1 backward-compat: keep thread-local for set_context() callers.
        self._context = threading.local()

        # Buffer + lock -- preserves v1 OBS-4 invariants.
        self._buffer: list[tuple] = []
        self._buffer_lock = threading.Lock()
        # OBS-4: kept at 10 to narrow the crash-loss window.
        # On SIGKILL/OOM, at most (buffer_size-1) entries are lost.
        self._buffer_size = buffer_size

        # P5: install M14 SensitiveDataFilter by default. Disable only
        # with explicit reviewer sign-off.
        if install_default_filter:
            default_filter = _make_default_filter()
            if default_filter is not None:
                self.addFilter(default_filter)

    # ------------------------------------------------------------------
    # v1 backward-compat: thread-local set_context() API.
    # ------------------------------------------------------------------

    def set_context(
        self,
        batch_id: int | None = None,
        table_name: str | None = None,
        source_name: str | None = None,
    ) -> None:
        """v1 API: set the per-thread context.

        Preserved for backward compatibility. New callers should use the
        module-level set_log_context (contextvars) which propagates
        through asyncio tasks. Both code paths read from contextvars
        first and fall back to this thread-local.

        Matches v1 semantics exactly:
            * batch_id only updates the thread-local if non-None.
            * table_name / source_name overwrite to None if not provided
              (v1's null-out behavior is preserved).
        """
        if batch_id is not None:
            self._context.batch_id = batch_id
        if table_name is not None:
            self._context.table_name = table_name
        else:
            self._context.table_name = None
        if source_name is not None:
            self._context.source_name = source_name
        else:
            self._context.source_name = None

    def _get_context(self) -> tuple[int | None, str | None, str | None]:
        """Resolve effective context -- contextvars first, thread-local fallback.

        Returns (batch_id, table_name, source_name). batch_id=None
        signals the handler to skip the record (no batch allocated yet).
        """
        # v2 contextvars path.
        batch_id = _batch_id_ctx.get()
        table_name = _table_name_ctx.get()
        source_name = _source_name_ctx.get()

        # v1 thread-local fallback if contextvars not set.
        if batch_id is None:
            batch_id = getattr(self._context, "batch_id", None)
        if table_name is None:
            table_name = getattr(self._context, "table_name", None)
        if source_name is None:
            source_name = getattr(self._context, "source_name", None)

        return batch_id, table_name, source_name

    # ------------------------------------------------------------------
    # logging.Handler interface.
    # ------------------------------------------------------------------

    def emit(self, record: logging.LogRecord) -> None:
        """Format and buffer a record; flush if buffer full or WARNING+.

        Per OBS-4 + OBS-5:
            * Records with no active batch_id are silently dropped.
            * Buffer flushes when size >= buffer_size OR record is
              WARNING+ severity.
            * Flush failures print to stderr; never raise.

        Per logging.Handler contract: self.handleError(record) catches
        any unexpected exception so the logging machinery itself does not
        propagate observability errors into the caller.
        """
        try:
            batch_id, table_name, source_name = self._get_context()
            if batch_id is None:
                return

            error_type = None
            stack_trace = None
            if record.exc_info and record.exc_info[1]:
                error_type = type(record.exc_info[1]).__name__
                stack_trace = "".join(
                    traceback.format_exception(*record.exc_info)
                )[:4000]

            metadata = None
            if hasattr(record, "metadata"):
                metadata = str(record.metadata)

            row = (
                batch_id,
                table_name,
                source_name,
                record.levelname,
                record.name,
                record.funcName,
                self.format(record)[:4000],
                error_type,
                stack_trace,
                metadata,
                datetime.now(timezone.utc),
            )

            with self._buffer_lock:
                self._buffer.append(row)
                # OBS-4: Flush immediately on WARNING+ -- diagnostic value
                # is highest, and crash-loss risk is unacceptable.
                if (
                    len(self._buffer) >= self._buffer_size
                    or record.levelno >= logging.WARNING
                ):
                    self._flush_buffer()
        except Exception:  # noqa: BLE001 -- handler must never raise
            self.handleError(record)

    def _flush_buffer(self) -> None:
        """Insert all buffered rows into PipelineLog via executemany.

        Per OBS-5: explicit conn.commit() after the insert. Per OBS-4:
        flush failures print to stderr (lost-row count visible) and never
        raise -- observability failure must not crash the pipeline.

        Caller holds self._buffer_lock; this method does NOT re-acquire.
        """
        if not self._buffer:
            return
        rows = self._buffer[:]
        self._buffer.clear()

        try:
            # Lazy import -- handler construction must not depend on
            # connections module being importable (early-boot, test
            # isolation, mock injection).
            from utils.connections import get_general_connection

            conn = get_general_connection()
            try:
                cursor = conn.cursor()
                cursor.executemany(
                    """
                    INSERT INTO ops.PipelineLog (
                        BatchId, TableName, SourceName, LogLevel, Module,
                        FunctionName, Message, ErrorType, StackTrace,
                        Metadata, CreatedAt
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    rows,
                )
                cursor.close()
                # OBS-5: Explicit commit -- don't rely on autocommit default.
                conn.commit()
            finally:
                try:
                    conn.close()
                except Exception:
                    pass
        except Exception as flush_err:  # noqa: BLE001
            # OBS-4: surface flush failures to stderr instead of silently
            # swallowing. If the General DB connection drops, this makes
            # the failure visible in systemd journal / console output.
            print(
                f"[SqlServerLogHandler] FLUSH FAILED ({len(rows)} entries lost): "
                f"{flush_err}",
                file=sys.stderr,
            )

    def flush(self) -> None:
        """Force-flush the buffer to PipelineLog.

        Idempotent -- calling flush() with an empty buffer is a no-op.
        The Python logging machinery calls this at shutdown via
        logging.shutdown().
        """
        with self._buffer_lock:
            self._flush_buffer()

    def close(self) -> None:
        """Flush buffered records and close the handler.

        Called by logging.shutdown(). The flush attempt is the last
        chance to land buffered records before the process exits;
        failures still surface via stderr per OBS-4.
        """
        self.flush()
        super().close()
