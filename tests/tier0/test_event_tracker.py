"""Tier 0 smoke test for observability/event_tracker.py per D67 + section 6.3.

Runtime under 5 s, pure / no external deps (utils.connections stubbed
before import via sys.modules manipulation; observability
sensitive_data_filter left in place so the M14 happy-path import
succeeds and the redactor loads cleanly).

Per section 6.3 D67 Tier 0 contract:
  (a) module imports
  (b) track context manager is invokable (mocked cursor)
  (c) clean exit writes Status=SUCCESS via mocked INSERT
  (d) exception inside the with-block writes Status=FAILED AND re-raises
  (e) Status values match the Round 1 enum per Pitfall 9
  (f) set_event_context / clear_event_context affect subsequent emits

D-numbers: D67 (Tier 0), D31 (PipelineEventLog as audit-trail target),
D33 (cooperative cancellation), P5 (SensitiveDataFilter on Metadata),
OBS-3, OBS-5, OBS-7.
B-numbers: M16 v2 cutover.
"""
from __future__ import annotations

import sys
import types
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


_MISSING = object()


def _snapshot_utils_connections_state():
    """Snapshot sys.modules entry + utils.connections attribute.

    Returned tuple is the restoration handle; teardown via
    _restore_utils_connections_state. Per B214 sys.modules discipline:
    direct sys.modules write without cleanup leaks the stub into later
    tests and breaks their import-time patching.
    """
    import utils  # noqa: F401
    mod_before = sys.modules.get("utils.connections", _MISSING)
    attr_before = getattr(sys.modules["utils"], "connections", _MISSING)
    return mod_before, attr_before


def _restore_utils_connections_state(snapshot):
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


def _install_utils_connections_stub():
    """Install a MagicMock utils.connections supporting both
    get_general_connection() (for INSERTs) and cursor_for() (for the
    cancellation check).

    Returns (mock_conn, mock_cursor, cancel_cursor) so tests can assert
    on either path calls.
    """
    import utils  # noqa: F401

    stub = types.ModuleType("utils.connections")
    mock_conn = MagicMock(name="general_conn")
    mock_cursor = MagicMock(name="cursor")
    # Default fetchone returns batch_id 12345 for the
    # _get_next_batch_id path; tests that exercise the cancellation
    # poll override the cancel_cursor.fetchone instead.
    mock_cursor.fetchone.return_value = (12345,)
    mock_conn.cursor.return_value = mock_cursor
    stub.get_general_connection = MagicMock(return_value=mock_conn)

    cancel_cursor = MagicMock(name="cancel_cursor")
    cancel_cursor.fetchone.return_value = (0,)  # not cancelled

    @contextmanager
    def _cursor_for(_db):
        yield cancel_cursor

    stub.cursor_for = _cursor_for
    stub._test_mock_conn = mock_conn
    stub._test_mock_cursor = mock_cursor
    stub._test_cancel_cursor = cancel_cursor

    sys.modules["utils.connections"] = stub
    sys.modules["utils"].connections = stub
    return mock_conn, mock_cursor, cancel_cursor


@pytest.fixture
def clean_eventvars():
    """Reset event-tracker contextvars before + after each test."""
    from observability.event_tracker import clear_event_context

    clear_event_context()
    yield
    clear_event_context()


@pytest.fixture
def stub_connections():
    """Per B214: snapshot + install stub; restore on teardown."""
    snapshot = _snapshot_utils_connections_state()
    mock_conn, mock_cursor, cancel_cursor = _install_utils_connections_stub()
    try:
        yield mock_conn, mock_cursor, cancel_cursor
    finally:
        _restore_utils_connections_state(snapshot)


def _make_table_config(table="ACCT", source="DNA"):
    cfg = MagicMock()
    cfg.source_object_name = table
    cfg.source_name = source
    return cfg


def test_module_imports():
    """D67 Tier 0 (a): module imports without error."""
    import observability.event_tracker as mod

    assert mod is not None
    assert hasattr(mod, "PipelineEventTracker")
    assert hasattr(mod, "PipelineEvent")
    assert hasattr(mod, "set_event_context")
    assert hasattr(mod, "clear_event_context")
    assert hasattr(mod, "skip")


def test_clean_exit_writes_success(clean_eventvars, stub_connections):
    """D67 Tier 0 (b/c): clean exit writes a SUCCESS row via mocked INSERT."""
    from observability.event_tracker import PipelineEventTracker

    mock_conn, mock_cursor, _ = stub_connections
    tracker = PipelineEventTracker()
    tc = _make_table_config()

    with tracker.track("EXTRACT", tc) as event:
        event.rows_processed = 42

    # Two cursor.execute() calls: one for batch_id allocation, one for
    # the PipelineEventLog INSERT.
    assert mock_cursor.execute.call_count == 2
    insert_call = mock_cursor.execute.call_args_list[1].args
    insert_sql = insert_call[0]
    insert_args = insert_call[1:]
    assert "INSERT INTO ops.PipelineEventLog" in insert_sql
    # Status arg is at index 8 (after BatchId, TableName, SourceName,
    # EventType, EventDetail, StartedAt, CompletedAt, DurationMs).
    assert insert_args[8] == "SUCCESS"
    # Explicit commit per OBS-5 (twice: batch_id + event).
    assert mock_conn.commit.call_count == 2


def test_exception_writes_failed_and_reraises(clean_eventvars, stub_connections):
    """D67 Tier 0 (d): exception in the with-block writes FAILED + re-raises."""
    from observability.event_tracker import PipelineEventTracker

    _, mock_cursor, _ = stub_connections
    tracker = PipelineEventTracker()
    tc = _make_table_config()

    with pytest.raises(RuntimeError, match="boom"):
        with tracker.track("EXTRACT", tc):
            raise RuntimeError("boom")

    insert_call = mock_cursor.execute.call_args_list[1].args
    insert_sql = insert_call[0]
    insert_args = insert_call[1:]
    assert "INSERT INTO ops.PipelineEventLog" in insert_sql
    assert insert_args[8] == "FAILED"
    assert "boom" in str(insert_args[9])


def test_status_values_in_enum(clean_eventvars, stub_connections):
    """D67 Tier 0 (e): every Status value written is in the Round 1 enum."""
    from observability.event_tracker import PipelineEventTracker

    _, mock_cursor, _ = stub_connections
    tracker = PipelineEventTracker()
    tc = _make_table_config()

    # SUCCESS path
    with tracker.track("EXTRACT", tc):
        pass

    # SKIPPED path (OBS-3 explicit caller flag)
    with tracker.track("EXTRACT", tc) as event:
        event.status = "SKIPPED"

    # FAILED path
    with pytest.raises(ValueError):
        with tracker.track("EXTRACT", tc):
            raise ValueError("x")

    written_statuses = []
    valid_enum = {"IN_PROGRESS", "SUCCESS", "FAILED", "SKIPPED"}
    for call in mock_cursor.execute.call_args_list:
        sql = call.args[0]
        if "INSERT INTO ops.PipelineEventLog" in sql:
            # Status is at call.args[1+8] = call.args[9] (after the SQL).
            written_statuses.append(call.args[9])
    assert len(written_statuses) == 3
    for s in written_statuses:
        assert s in valid_enum, f"Status {s!r} not in CK_PipelineEventLog_Status enum"


def test_context_set_and_clear_affect_track(clean_eventvars, stub_connections):
    """D67 Tier 0 (f): contextvars resolve table_name / source_name when
    table_config arg is None.
    """
    from observability.event_tracker import (
        PipelineEventTracker,
        clear_event_context,
        set_event_context,
    )

    _, _mock_cursor, _ = stub_connections

    tracker = PipelineEventTracker()
    set_event_context(batch_id=99, table_name="CTX_TABLE", source_name="CTX_SRC")

    with tracker.track("EXTRACT") as event:
        # table identity resolved from contextvars when table_config=None.
        assert event.table_name == "CTX_TABLE"
        assert event.source_name == "CTX_SRC"
    # batch_id property reads from contextvar so we did NOT call
    # _get_next_batch_id.
    assert tracker.batch_id == 99

    clear_event_context()
    # After clear: contextvars are None again.
    with tracker.track("EXTRACT") as event:
        assert event.table_name is None
        assert event.source_name is None


def test_cancellation_flag_marks_skipped(clean_eventvars, stub_connections):
    """D33: when CancellationRequested = 1 on the gate row, the event is
    marked SKIPPED and event.cancellation_requested=True.
    """
    from observability.event_tracker import PipelineEventTracker, set_event_context

    _, mock_cursor, cancel_cursor = stub_connections
    # Configure the cancellation poll to return 1 (cancelled).
    cancel_cursor.fetchone.return_value = (1,)

    set_event_context(batch_id=77, table_name="ACCT", source_name="DNA", gate_id=5)
    tracker = PipelineEventTracker()

    with tracker.track("EXTRACT") as event:
        # Inside the with-block, the caller can observe the flag and
        # short-circuit subsequent work.
        assert event.cancellation_requested is True
        assert event.status == "SKIPPED"

    # The audit row was still written (SKIPPED).
    insert_calls = [
        c for c in mock_cursor.execute.call_args_list
        if "INSERT INTO ops.PipelineEventLog" in c.args[0]
    ]
    assert len(insert_calls) == 1
    assert insert_calls[0].args[9] == "SKIPPED"
