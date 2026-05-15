"""Tier 1 unit test for observability/log_handler.py v2.

Per D70 Tier 1: per-feature + per-error-path coverage; <5 min runtime;
no external deps.

Coverage:
  - Each severity level (DEBUG / INFO / WARNING / ERROR / CRITICAL)
  - Buffer flush at exactly buffer_size threshold
  - WARNING+ immediate flush (3 sub-cases: WARN / ERROR / CRITICAL)
  - SensitiveDataFilter applied (P5 -- plaintext password in msg redacted in row)
  - OBS-4 stderr fallback on flush failure
  - OBS-5 explicit commit per flush
  - flush() with empty buffer is a no-op
  - close() flushes
  - Multiple handlers in the same process do not collide
  - v1 backward-compat: set_context() still works (cutover regression)
  - Exception path: emit() with bad context doesn't raise
  - exc_info captured into ErrorType + StackTrace columns

Spec: phase1/03_core_modules.md section 6.2.
"""
from __future__ import annotations

import io
import logging
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Stub utils.connections per Tier 0 strategy.
# ---------------------------------------------------------------------------


_MISSING = object()


def _snapshot_utils_connections_state():
    """Capture (sys.modules['utils.connections'], utils.connections attr) so
    they can be restored on test teardown. Sentinel `_MISSING` marks slots
    not present pre-install. Restoration is mandatory: without it the stub
    leaks into later tests and breaks `patch('utils.connections.get_connection',
    ...)` because the stub module lacks the attribute. M15 v1 regression fix
    per B214 sys.modules registration discipline."""
    import utils  # noqa: F401  -- triggers real package init
    mod_before = sys.modules.get("utils.connections", _MISSING)
    attr_before = getattr(sys.modules["utils"], "connections", _MISSING)
    return mod_before, attr_before


def _restore_utils_connections_state(snapshot):
    """Restore sys.modules + utils package attr to the pre-install state."""
    mod_before, attr_before = snapshot
    if mod_before is _MISSING:
        sys.modules.pop("utils.connections", None)
    else:
        sys.modules["utils.connections"] = mod_before
    utils_pkg = sys.modules.get("utils")
    if utils_pkg is not None:
        if attr_before is _MISSING:
            try:
                delattr(utils_pkg, "connections")
            except AttributeError:
                pass
        else:
            utils_pkg.connections = attr_before


def _install_utils_connections_stub(commit_raises=False, connect_raises=False):
    """Install / refresh utils.connections stub.

    commit_raises=True -> conn.commit() raises (OBS-4 stderr path).
    connect_raises=True -> get_general_connection() raises (OBS-4 stderr path).
    """
    import utils  # noqa: F401

    stub = types.ModuleType("utils.connections")
    mock_conn = MagicMock(name="general_conn")
    mock_cursor = MagicMock(name="cursor")
    mock_conn.cursor.return_value = mock_cursor

    if commit_raises:
        mock_conn.commit.side_effect = RuntimeError("simulated commit failure")
    if connect_raises:
        stub.get_general_connection = MagicMock(
            side_effect=RuntimeError("simulated connection failure")
        )
    else:
        stub.get_general_connection = MagicMock(return_value=mock_conn)

    stub._test_mock_conn = mock_conn
    stub._test_mock_cursor = mock_cursor
    sys.modules["utils.connections"] = stub
    sys.modules["utils"].connections = stub
    return mock_conn, mock_cursor


def _make_record(msg="x", level=logging.INFO, *, args=None, exc_info=None):
    return logging.LogRecord(
        name="t",
        level=level,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args,
        exc_info=exc_info,
        func="f",
    )


@pytest.fixture(autouse=True)
def _clean_context_each_test():
    from observability.log_handler import clear_log_context

    clear_log_context()
    yield
    clear_log_context()


@pytest.fixture(autouse=True)
def _restore_utils_connections_after_test():
    """Snapshot sys.modules['utils.connections'] + utils.connections attr
    before each test and restore on teardown so the stub installed by
    _install_utils_connections_stub() does not leak into later tests.

    Without this autouse fixture, test_log_handler.py poisons every later
    test that does `patch('utils.connections.get_connection', ...)` --
    the stub module lacks that attribute and mock.patch raises
    AttributeError. M15 v1 regression fix per B214 sys.modules
    registration discipline."""
    snapshot = _snapshot_utils_connections_state()
    try:
        yield
    finally:
        _restore_utils_connections_state(snapshot)


# ---------------------------------------------------------------------------
# Each severity level: DEBUG / INFO / WARNING / ERROR / CRITICAL.
# ---------------------------------------------------------------------------


class TestSeverityLevels:

    def _setup(self, handler_level=logging.DEBUG):
        from observability.log_handler import SqlServerLogHandler, set_log_context

        mock_conn, mock_cursor = _install_utils_connections_stub()
        h = SqlServerLogHandler(level=handler_level)
        set_log_context(batch_id=1, table_name="T", source_name="S")
        return h, mock_conn, mock_cursor

    def test_debug_record_buffers_does_not_flush(self):
        h, mc, cur = self._setup(handler_level=logging.DEBUG)
        h.emit(_make_record("d", level=logging.DEBUG))
        # DEBUG below WARNING -> buffered, no flush yet
        assert cur.executemany.call_count == 0
        assert len(h._buffer) == 1
        assert h._buffer[0][3] == "DEBUG"

    def test_info_record_buffers_does_not_flush(self):
        h, mc, cur = self._setup()
        h.emit(_make_record("i", level=logging.INFO))
        assert cur.executemany.call_count == 0
        assert len(h._buffer) == 1
        assert h._buffer[0][3] == "INFO"

    def test_warning_record_flushes_immediately(self):
        h, mc, cur = self._setup()
        h.emit(_make_record("w", level=logging.WARNING))
        assert cur.executemany.call_count == 1
        assert mc.commit.call_count == 1
        # WARNING level recorded in row
        rows = cur.executemany.call_args[0][1]
        assert rows[0][3] == "WARNING"

    def test_error_record_flushes_immediately(self):
        h, mc, cur = self._setup()
        h.emit(_make_record("e", level=logging.ERROR))
        assert cur.executemany.call_count == 1
        rows = cur.executemany.call_args[0][1]
        assert rows[0][3] == "ERROR"

    def test_critical_record_flushes_immediately(self):
        h, mc, cur = self._setup()
        h.emit(_make_record("c", level=logging.CRITICAL))
        assert cur.executemany.call_count == 1
        rows = cur.executemany.call_args[0][1]
        assert rows[0][3] == "CRITICAL"


# ---------------------------------------------------------------------------
# Buffer behavior.
# ---------------------------------------------------------------------------


class TestBuffering:

    def test_buffer_flushes_at_size_threshold(self):
        """Exactly buffer_size INFO records -> one flush."""
        from observability.log_handler import SqlServerLogHandler, set_log_context

        mc, cur = _install_utils_connections_stub()
        h = SqlServerLogHandler(buffer_size=4)
        set_log_context(batch_id=1)

        for i in range(3):
            h.emit(_make_record(f"r{i}"))
        # 3 of 4 -- no flush yet
        assert cur.executemany.call_count == 0
        assert len(h._buffer) == 3

        # 4th triggers flush
        h.emit(_make_record("r3"))
        assert cur.executemany.call_count == 1
        rows = cur.executemany.call_args[0][1]
        assert len(rows) == 4
        # buffer drained
        assert h._buffer == []

    def test_buffer_does_not_double_flush(self):
        """Two flushes worth of INFO records produces exactly two executemany calls."""
        from observability.log_handler import SqlServerLogHandler, set_log_context

        mc, cur = _install_utils_connections_stub()
        h = SqlServerLogHandler(buffer_size=2)
        set_log_context(batch_id=1)

        for i in range(4):
            h.emit(_make_record(f"r{i}"))
        assert cur.executemany.call_count == 2
        assert mc.commit.call_count == 2

    def test_explicit_flush_with_empty_buffer_is_noop(self):
        from observability.log_handler import SqlServerLogHandler

        mc, cur = _install_utils_connections_stub()
        h = SqlServerLogHandler()
        h.flush()
        assert cur.executemany.call_count == 0
        assert mc.commit.call_count == 0

    def test_explicit_flush_drains_buffer(self):
        from observability.log_handler import SqlServerLogHandler, set_log_context

        mc, cur = _install_utils_connections_stub()
        h = SqlServerLogHandler(buffer_size=10)
        set_log_context(batch_id=1)
        h.emit(_make_record("r"))
        h.emit(_make_record("r2"))
        assert cur.executemany.call_count == 0
        h.flush()
        assert cur.executemany.call_count == 1
        assert h._buffer == []

    def test_close_flushes_buffer(self):
        from observability.log_handler import SqlServerLogHandler, set_log_context

        mc, cur = _install_utils_connections_stub()
        h = SqlServerLogHandler(buffer_size=10)
        set_log_context(batch_id=1)
        h.emit(_make_record("pre-close"))
        h.close()
        assert cur.executemany.call_count == 1


# ---------------------------------------------------------------------------
# OBS-5: explicit commit per flush.
# ---------------------------------------------------------------------------


class TestExplicitCommit:

    def test_commit_called_once_per_flush(self):
        from observability.log_handler import SqlServerLogHandler, set_log_context

        mc, cur = _install_utils_connections_stub()
        h = SqlServerLogHandler()
        set_log_context(batch_id=1)
        h.emit(_make_record("w", level=logging.WARNING))
        h.emit(_make_record("w2", level=logging.WARNING))
        # 2 WARNINGs -> 2 flushes -> 2 commits
        assert mc.commit.call_count == 2


# ---------------------------------------------------------------------------
# OBS-4: stderr fallback on flush failure.
# ---------------------------------------------------------------------------


class TestStderrOnFlushFailure:

    def test_connection_failure_prints_to_stderr_not_raise(self, capsys):
        """get_general_connection() raising propagates to flush -> stderr, not raise."""
        from observability.log_handler import SqlServerLogHandler, set_log_context

        _install_utils_connections_stub(connect_raises=True)
        h = SqlServerLogHandler()
        set_log_context(batch_id=1)

        # Should NOT raise -- WARNING flush triggers exception path.
        h.emit(_make_record("w", level=logging.WARNING))

        captured = capsys.readouterr()
        assert "FLUSH FAILED" in captured.err
        assert "1 entries lost" in captured.err

    def test_commit_failure_prints_to_stderr_not_raise(self, capsys):
        """conn.commit() raising propagates to flush -> stderr, not raise."""
        from observability.log_handler import SqlServerLogHandler, set_log_context

        _install_utils_connections_stub(commit_raises=True)
        h = SqlServerLogHandler()
        set_log_context(batch_id=1)

        h.emit(_make_record("w", level=logging.WARNING))

        captured = capsys.readouterr()
        assert "FLUSH FAILED" in captured.err

    def test_lost_rows_visible_in_stderr_message(self, capsys):
        """stderr message must include lost-row count for operator visibility."""
        from observability.log_handler import SqlServerLogHandler, set_log_context

        _install_utils_connections_stub(connect_raises=True)
        h = SqlServerLogHandler(buffer_size=3)
        set_log_context(batch_id=1)

        # Fill the buffer with INFO -- last one triggers flush via buffer threshold.
        for i in range(3):
            h.emit(_make_record(f"r{i}"))

        captured = capsys.readouterr()
        assert "3 entries lost" in captured.err


# ---------------------------------------------------------------------------
# P5: SensitiveDataFilter installed by default, applied to messages.
# ---------------------------------------------------------------------------


class TestSensitiveDataFilter:

    def test_default_filter_present(self):
        from observability.log_handler import SqlServerLogHandler
        from observability.sensitive_data_filter import SensitiveDataFilter

        h = SqlServerLogHandler()
        assert any(
            isinstance(f, SensitiveDataFilter) for f in h.filters
        ), "M14 default filter must be installed"

    def test_password_in_message_redacted_in_pipelinelog_row(self):
        """P5: plaintext password in log message must NOT appear in the
        row sent to PipelineLog -- the filter runs before emit() formats."""
        from observability.log_handler import SqlServerLogHandler, set_log_context

        mc, cur = _install_utils_connections_stub()
        h = SqlServerLogHandler()
        set_log_context(batch_id=1)

        # The logging framework's handle() runs filters BEFORE emit().
        record = _make_record("connecting with user_password=topsecret123")
        # Manually run handle() so filters are applied (matches real flow).
        h.handle(record)
        h.flush()

        rows = cur.executemany.call_args[0][1]
        message_col = rows[0][6]  # Message is column index 6
        assert "topsecret123" not in message_col
        assert "REDACTED" in message_col

    def test_install_default_filter_false_no_redaction(self):
        """Opting out of the default filter means no redaction (caller must
        install their own per P5 -- this branch is for advanced use)."""
        from observability.log_handler import SqlServerLogHandler, set_log_context

        mc, cur = _install_utils_connections_stub()
        h = SqlServerLogHandler(install_default_filter=False)
        set_log_context(batch_id=1)

        record = _make_record("connecting with user_password=topsecret123")
        h.handle(record)
        h.flush()

        rows = cur.executemany.call_args[0][1]
        message_col = rows[0][6]
        # No filter -> plaintext survives. This is the documented
        # opt-out semantics; downstream callers are expected to install
        # their own filter when opting out of the default.
        assert "topsecret123" in message_col


# ---------------------------------------------------------------------------
# v1 backward-compat regression: handler.set_context() still works.
# ---------------------------------------------------------------------------


class TestV1BackwardCompatRegression:
    """CRITICAL: this class is the v1->v2 cutover regression guard. Any
    test that fails here means a v1 caller broke. Do NOT loosen these
    assertions without a documented breaking-change decision."""

    def test_v1_set_context_no_contextvars(self):
        """v1 pattern: handler.set_context(batch_id, table_name, source_name).

        With contextvars unset, the emit path falls back to the thread-local
        set via set_context() and the record carries the v1 context.
        """
        from observability.log_handler import SqlServerLogHandler

        mc, cur = _install_utils_connections_stub()
        h = SqlServerLogHandler()
        # v1-style: set context on the handler directly.
        h.set_context(batch_id=99, table_name="V1_TABLE", source_name="V1_SRC")
        h.emit(_make_record("from v1 caller", level=logging.WARNING))

        assert cur.executemany.call_count == 1
        rows = cur.executemany.call_args[0][1]
        assert rows[0][0] == 99
        assert rows[0][1] == "V1_TABLE"
        assert rows[0][2] == "V1_SRC"

    def test_v1_set_context_batch_id_only(self):
        """v1 pattern with no table/source -- thread-local should still
        retain batch_id with table/source as None."""
        from observability.log_handler import SqlServerLogHandler

        mc, cur = _install_utils_connections_stub()
        h = SqlServerLogHandler()
        h.set_context(batch_id=5)
        h.emit(_make_record("only-batch", level=logging.WARNING))

        rows = cur.executemany.call_args[0][1]
        assert rows[0][0] == 5
        assert rows[0][1] is None
        assert rows[0][2] is None

    def test_v1_constructor_signature_unchanged(self):
        """SqlServerLogHandler(level=...) -- positional level still works."""
        from observability.log_handler import SqlServerLogHandler

        # v1 callers pass level positionally.
        h = SqlServerLogHandler(logging.WARNING)
        assert h.level == logging.WARNING

    def test_v1_default_buffer_size_matches_v1(self):
        """v1 had _buffer_size = 10 (post-OBS-4). v2 default must match."""
        from observability.log_handler import SqlServerLogHandler

        h = SqlServerLogHandler()
        assert h._buffer_size == 10

    def test_v1_set_context_then_v2_set_log_context_preference(self):
        """When BOTH v1 thread-local AND v2 contextvars are set, v2
        contextvars WINS (newer caller path takes precedence)."""
        from observability.log_handler import SqlServerLogHandler, set_log_context

        mc, cur = _install_utils_connections_stub()
        h = SqlServerLogHandler()
        h.set_context(batch_id=10, table_name="OLD", source_name="OLD_SRC")
        set_log_context(batch_id=20, table_name="NEW", source_name="NEW_SRC")

        h.emit(_make_record("w", level=logging.WARNING))

        rows = cur.executemany.call_args[0][1]
        assert rows[0][0] == 20  # contextvars win
        assert rows[0][1] == "NEW"
        assert rows[0][2] == "NEW_SRC"

    def test_v1_module_level_emit_no_batch_id_dropped(self):
        """v1 behavior: emit() with no batch_id silently returns. v2
        must preserve -- no error, no row written, no exception."""
        from observability.log_handler import SqlServerLogHandler

        mc, cur = _install_utils_connections_stub()
        h = SqlServerLogHandler()
        # No context set anywhere -- should drop silently.
        h.emit(_make_record("dropped"))
        h.flush()
        assert cur.executemany.call_count == 0
        assert h._buffer == []

    def test_v1_class_name_preserved(self):
        """Class name MUST remain SqlServerLogHandler -- v1 callers
        reference it by name in isinstance() checks, type() introspection,
        and module-level imports."""
        from observability.log_handler import SqlServerLogHandler

        assert SqlServerLogHandler.__name__ == "SqlServerLogHandler"
        assert issubclass(SqlServerLogHandler, logging.Handler)


# ---------------------------------------------------------------------------
# Exception info captured into ErrorType + StackTrace columns.
# ---------------------------------------------------------------------------


class TestExceptionCapture:

    def test_exc_info_captures_error_type_and_stacktrace(self):
        from observability.log_handler import SqlServerLogHandler, set_log_context

        mc, cur = _install_utils_connections_stub()
        h = SqlServerLogHandler()
        set_log_context(batch_id=1)

        try:
            raise ValueError("test failure")
        except ValueError:
            exc_info = sys.exc_info()

        h.emit(_make_record("error happened", level=logging.ERROR, exc_info=exc_info))

        rows = cur.executemany.call_args[0][1]
        # ErrorType is column index 7
        assert rows[0][7] == "ValueError"
        # StackTrace is column index 8
        assert "ValueError: test failure" in rows[0][8]

    def test_no_exc_info_leaves_error_columns_none(self):
        from observability.log_handler import SqlServerLogHandler, set_log_context

        mc, cur = _install_utils_connections_stub()
        h = SqlServerLogHandler()
        set_log_context(batch_id=1)
        h.emit(_make_record("plain", level=logging.WARNING))

        rows = cur.executemany.call_args[0][1]
        assert rows[0][7] is None  # ErrorType
        assert rows[0][8] is None  # StackTrace


# ---------------------------------------------------------------------------
# Metadata column: record.metadata attribute serialized into Metadata column.
# ---------------------------------------------------------------------------


class TestMetadataColumn:

    def test_metadata_attribute_serialized(self):
        from observability.log_handler import SqlServerLogHandler, set_log_context

        mc, cur = _install_utils_connections_stub()
        h = SqlServerLogHandler()
        set_log_context(batch_id=1)
        record = _make_record("with meta", level=logging.WARNING)
        record.metadata = {"key": "value", "count": 5}
        h.emit(record)

        rows = cur.executemany.call_args[0][1]
        # Metadata column index 9
        meta = rows[0][9]
        assert meta is not None
        assert "key" in meta
        assert "value" in meta

    def test_no_metadata_attribute_leaves_column_none(self):
        from observability.log_handler import SqlServerLogHandler, set_log_context

        mc, cur = _install_utils_connections_stub()
        h = SqlServerLogHandler()
        set_log_context(batch_id=1)
        h.emit(_make_record("no meta", level=logging.WARNING))

        rows = cur.executemany.call_args[0][1]
        assert rows[0][9] is None


# ---------------------------------------------------------------------------
# Multiple handlers in the same process do not collide.
# ---------------------------------------------------------------------------


class TestMultipleHandlers:

    def test_two_handlers_independent_buffers(self):
        from observability.log_handler import SqlServerLogHandler, set_log_context

        mc, cur = _install_utils_connections_stub()
        h1 = SqlServerLogHandler()
        h2 = SqlServerLogHandler()
        set_log_context(batch_id=1)

        h1.emit(_make_record("h1"))
        h2.emit(_make_record("h2"))

        assert len(h1._buffer) == 1
        assert len(h2._buffer) == 1
        # Buffers are independent objects.
        assert h1._buffer is not h2._buffer


# ---------------------------------------------------------------------------
# contextvars isolation per task (asyncio-style propagation).
# ---------------------------------------------------------------------------


class TestContextVarsIsolation:

    def test_contextvars_set_and_clear_roundtrip(self):
        from observability.log_handler import (
            clear_log_context,
            set_log_context,
            _batch_id_ctx,
            _table_name_ctx,
            _source_name_ctx,
        )

        set_log_context(batch_id=42, table_name="ACCT", source_name="DNA")
        assert _batch_id_ctx.get() == 42
        assert _table_name_ctx.get() == "ACCT"
        assert _source_name_ctx.get() == "DNA"

        clear_log_context()
        assert _batch_id_ctx.get() is None
        assert _table_name_ctx.get() is None
        assert _source_name_ctx.get() is None

    def test_set_log_context_table_name_optional(self):
        from observability.log_handler import (
            _batch_id_ctx,
            _table_name_ctx,
            set_log_context,
        )

        set_log_context(batch_id=1)
        assert _batch_id_ctx.get() == 1
        assert _table_name_ctx.get() is None


# ---------------------------------------------------------------------------
# Concurrent emit safety (smoke -- threading.Lock prevents data races).
# ---------------------------------------------------------------------------


class TestThreadSafety:

    def test_concurrent_emits_serialize_into_buffer(self):
        """Two threads emitting concurrently must produce a consistent
        buffer state (no lost entries, no half-rows).

        Uses the v1 thread-local set_context() because contextvars do NOT
        automatically propagate across threading.Thread targets without an
        explicit copy_context().run(...) wrapper. The per-thread fallback
        in handler._get_context() picks up the instance attribute.
        """
        import threading

        from observability.log_handler import SqlServerLogHandler

        mc, cur = _install_utils_connections_stub()
        h = SqlServerLogHandler(buffer_size=100)
        # v1 thread-local set_context: shared via the handler instance.
        # Each worker thread reads the same _context.batch_id since the
        # handler instance is shared.
        h._context.batch_id = 1
        h._context.table_name = None
        h._context.source_name = None

        def worker(n):
            # Each thread sees the same handler._context.batch_id via
            # the shared instance attribute (threading.local is per
            # main-thread; here we set the instance dict directly to
            # avoid the per-thread isolation -- legitimate because
            # _context isn't a true threading.local in this test).
            for i in range(n):
                h.emit(_make_record(f"r-{i}"))

        # Patch _get_context to return the constant we want -- the cleanest
        # way to test the lock under concurrent emit without fighting
        # contextvars/threading.local cross-thread propagation.
        orig_get_context = h._get_context
        h._get_context = lambda: (1, None, None)
        try:
            threads = [threading.Thread(target=worker, args=(20,)) for _ in range(3)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert len(h._buffer) == 60
        finally:
            h._get_context = orig_get_context


# ---------------------------------------------------------------------------
# Schema-row positional contract (matches PipelineLog DDL column order).
# ---------------------------------------------------------------------------


class TestRowPositionalContract:
    """The INSERT statement is positional. Column order must match
    PipelineLog DDL (phase1/01_database_schema.md). Any reordering of
    the row tuple is a BCP-style positional contract change."""

    EXPECTED_COLUMNS = [
        "BatchId",        # 0
        "TableName",      # 1
        "SourceName",     # 2
        "LogLevel",       # 3
        "Module",         # 4
        "FunctionName",   # 5
        "Message",        # 6
        "ErrorType",      # 7
        "StackTrace",     # 8
        "Metadata",       # 9
        "CreatedAt",      # 10
    ]

    def test_row_has_expected_column_count(self):
        from observability.log_handler import SqlServerLogHandler, set_log_context

        mc, cur = _install_utils_connections_stub()
        h = SqlServerLogHandler()
        set_log_context(batch_id=1, table_name="T", source_name="S")
        h.emit(_make_record("msg", level=logging.WARNING))

        rows = cur.executemany.call_args[0][1]
        assert len(rows[0]) == len(self.EXPECTED_COLUMNS)

    def test_module_column_carries_logger_name(self):
        from observability.log_handler import SqlServerLogHandler, set_log_context

        mc, cur = _install_utils_connections_stub()
        h = SqlServerLogHandler()
        set_log_context(batch_id=1)
        rec = _make_record("m", level=logging.WARNING)
        rec.name = "custom.module"
        h.emit(rec)

        rows = cur.executemany.call_args[0][1]
        assert rows[0][4] == "custom.module"

    def test_created_at_is_recent(self):
        import datetime as dt

        from observability.log_handler import SqlServerLogHandler, set_log_context

        mc, cur = _install_utils_connections_stub()
        h = SqlServerLogHandler()
        set_log_context(batch_id=1)
        before = dt.datetime.now(dt.timezone.utc)
        h.emit(_make_record("m", level=logging.WARNING))
        after = dt.datetime.now(dt.timezone.utc)

        rows = cur.executemany.call_args[0][1]
        created_at = rows[0][10]
        assert before <= created_at <= after


# ---------------------------------------------------------------------------
# INSERT SQL contract -- columns matter for PipelineLog DDL alignment.
# ---------------------------------------------------------------------------


class TestInsertSqlContract:

    def test_insert_targets_ops_pipelinelog(self):
        from observability.log_handler import SqlServerLogHandler, set_log_context

        mc, cur = _install_utils_connections_stub()
        h = SqlServerLogHandler()
        set_log_context(batch_id=1)
        h.emit(_make_record("m", level=logging.WARNING))

        sql = cur.executemany.call_args[0][0]
        assert "ops.PipelineLog" in sql

    def test_insert_uses_eleven_placeholders(self):
        """Must use exactly 11 ? placeholders -- column count alignment."""
        from observability.log_handler import SqlServerLogHandler, set_log_context

        mc, cur = _install_utils_connections_stub()
        h = SqlServerLogHandler()
        set_log_context(batch_id=1)
        h.emit(_make_record("m", level=logging.WARNING))

        sql = cur.executemany.call_args[0][0]
        assert sql.count("?") == 11
