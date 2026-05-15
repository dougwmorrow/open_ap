"""Tier 1 unit tests for observability/event_tracker.py.

Per D70 Tier 1: per-edge-case + per-error-path coverage; mocks pyodbc
cursor + utils.connections stub; no live SQL Server. Mirrors the
M15 SqlServerLogHandler Tier 1 layout (class-organized; per-class
fixtures via the autouse stub_connections + clean_eventvars).

North Star pillars:
  - Audit-grade (D31 + D62: every track() invocation writes exactly
    one PipelineEventLog row; the Status enum + 24-column canonical DDL
    are pinned)
  - Operationally stable (D68: every error path surfaces the documented
    semantics; write failures NEVER crash the caller; cancellation poll
    failures are best-effort)
  - Traceability (D33: cancellation flag honored; SKIPPED row written;
    event.cancellation_requested exposed to caller)

Spec: phase1/03_core_modules.md section 6.3 + phase1/01_database_schema.md
section 1 (PipelineEventLog DDL) + section 4 (PipelineExecutionGate DDL).

B-numbers: M16 v2 cutover; carries forward B214 sys.modules discipline +
B228 utils.errors canonical hierarchy (event_tracker imports NO local
exception classes; all error semantics live on the caller side).
"""
from __future__ import annotations

import json
import sys
import types
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


_MISSING = object()


def _snapshot_utils_connections_state():
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


def _install_utils_connections_stub(
    *,
    cancel_returns=(0,),
    batch_id_value=1234,
):
    """Install a stub utils.connections module.

    Parameters:
        cancel_returns: tuple returned by cursor_for cancel cursor
            fetchone(). Default (0,) = not cancelled.
        batch_id_value: value returned by get_general_connection cursor
            fetchone() (used by _get_next_batch_id).
    """
    import utils  # noqa: F401

    stub = types.ModuleType("utils.connections")
    mock_conn = MagicMock(name="general_conn")
    mock_cursor = MagicMock(name="cursor")
    mock_cursor.fetchone.return_value = (batch_id_value,)
    mock_conn.cursor.return_value = mock_cursor
    stub.get_general_connection = MagicMock(return_value=mock_conn)

    cancel_cursor = MagicMock(name="cancel_cursor")
    cancel_cursor.fetchone.return_value = cancel_returns

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
    from observability.event_tracker import clear_event_context

    clear_event_context()
    yield
    clear_event_context()


@pytest.fixture
def stub_connections():
    snapshot = _snapshot_utils_connections_state()
    handles = _install_utils_connections_stub()
    try:
        yield handles
    finally:
        _restore_utils_connections_state(snapshot)


@pytest.fixture
def stub_connections_with_cancel():
    """Variant that pre-configures CancellationRequested=1."""
    snapshot = _snapshot_utils_connections_state()
    handles = _install_utils_connections_stub(cancel_returns=(1,))
    try:
        yield handles
    finally:
        _restore_utils_connections_state(snapshot)


def _make_table_config(table="ACCT", source="DNA"):
    cfg = MagicMock()
    cfg.source_object_name = table
    cfg.source_name = source
    return cfg


def _insert_calls(mock_cursor):
    return [
        c for c in mock_cursor.execute.call_args_list
        if "INSERT INTO ops.PipelineEventLog" in c.args[0]
    ]


def _insert_args(call):
    # Each cursor.execute call is .args = (sql, *positional_params).
    return call.args[1:]


# ---------------------------------------------------------------------------
# Public API surface (v1 preservation per cutover contract).
# ---------------------------------------------------------------------------


class TestPublicSurface:
    """v1 API preservation: every name v1 callers depend on still exists."""

    def test_pipeline_event_tracker_class_exists(self):
        from observability.event_tracker import PipelineEventTracker
        assert callable(PipelineEventTracker)

    def test_pipeline_event_dataclass_exists(self):
        from observability.event_tracker import PipelineEvent
        # All v1 fields present.
        v1_fields = [
            "event_type", "table_name", "source_name", "started_at",
            "completed_at", "duration_ms", "status", "error_message",
            "event_detail", "rows_processed", "rows_inserted", "rows_updated",
            "rows_deleted", "rows_unchanged", "rows_before", "rows_after",
            "table_created", "metadata", "rows_per_second",
        ]
        e = PipelineEvent(event_type="X", table_name="T", source_name="S")
        for f in v1_fields:
            assert hasattr(e, f), f"v1 PipelineEvent missing attribute {f!r}"

    def test_v2_additions_present(self):
        from observability.event_tracker import PipelineEvent
        e = PipelineEvent(event_type="X", table_name="T", source_name="S")
        # v2 additions: cycle context + cancellation flag.
        assert hasattr(e, "cycle_type")
        assert hasattr(e, "cycle_date")
        assert hasattr(e, "server_role")
        assert hasattr(e, "cancellation_requested")
        # Defaults preserve v1 behavior.
        assert e.cycle_type is None
        assert e.cycle_date is None
        assert e.server_role is None
        assert e.cancellation_requested is False

    def test_helper_functions_exist(self):
        import observability.event_tracker as mod
        assert callable(mod.set_event_context)
        assert callable(mod.clear_event_context)
        assert callable(mod.skip)

    def test_default_status_is_in_progress(self):
        from observability.event_tracker import PipelineEvent
        e = PipelineEvent(event_type="X", table_name="T", source_name="S")
        # Per spec: entry status is IN_PROGRESS so the row would pass the
        # CK_PipelineEventLog_Status enum even if write happened mid-flight.
        assert e.status == "IN_PROGRESS"


# ---------------------------------------------------------------------------
# batch_id allocation.
# ---------------------------------------------------------------------------


class TestBatchIdAllocation:

    def test_batch_id_lazy_allocates_from_sequence(
        self, clean_eventvars, stub_connections
    ):
        from observability.event_tracker import PipelineEventTracker
        _mock_conn, mock_cursor, _ = stub_connections
        # Set the batch_id sequence fetchone return value.
        mock_cursor.fetchone.return_value = (4242,)
        tracker = PipelineEventTracker()
        # First read triggers allocation.
        assert tracker.batch_id == 4242
        # Second read is cached.
        assert tracker.batch_id == 4242
        # Only one sequence allocation.
        sequence_calls = [
            c for c in mock_cursor.execute.call_args_list
            if "PipelineBatchSequence" in c.args[0]
        ]
        assert len(sequence_calls) == 1

    def test_batch_id_prefers_contextvar(
        self, clean_eventvars, stub_connections
    ):
        from observability.event_tracker import (
            PipelineEventTracker,
            set_event_context,
        )
        _mock_conn, mock_cursor, _ = stub_connections
        set_event_context(batch_id=999, table_name="X", source_name="Y")
        tracker = PipelineEventTracker()
        assert tracker.batch_id == 999
        # No sequence allocation happened.
        sequence_calls = [
            c for c in mock_cursor.execute.call_args_list
            if "PipelineBatchSequence" in c.args[0]
        ]
        assert len(sequence_calls) == 0

    def test_batch_id_commit_per_obs5(
        self, clean_eventvars, stub_connections
    ):
        from observability.event_tracker import PipelineEventTracker
        mock_conn, _, _ = stub_connections
        tracker = PipelineEventTracker()
        _ = tracker.batch_id  # trigger allocation
        # OBS-5: explicit commit after the sequence INSERT.
        assert mock_conn.commit.call_count >= 1


# ---------------------------------------------------------------------------
# context manager: status transitions per Round 1 enum.
# ---------------------------------------------------------------------------


class TestStatusTransitions:
    """Per Pitfall 9: Status must always be in CK_PipelineEventLog_Status."""

    def test_clean_exit_writes_success(self, clean_eventvars, stub_connections):
        from observability.event_tracker import PipelineEventTracker
        _, mock_cursor, _ = stub_connections
        tracker = PipelineEventTracker()
        with tracker.track("EXTRACT", _make_table_config()):
            pass
        ins = _insert_calls(mock_cursor)[0]
        assert _insert_args(ins)[8] == "SUCCESS"

    def test_exception_writes_failed(self, clean_eventvars, stub_connections):
        from observability.event_tracker import PipelineEventTracker
        _, mock_cursor, _ = stub_connections
        tracker = PipelineEventTracker()
        with pytest.raises(KeyError):
            with tracker.track("EXTRACT", _make_table_config()):
                raise KeyError("missing")
        ins = _insert_calls(mock_cursor)[0]
        assert _insert_args(ins)[8] == "FAILED"

    def test_caller_set_skipped_preserved(
        self, clean_eventvars, stub_connections
    ):
        """OBS-3: explicit SKIPPED status from the caller is preserved."""
        from observability.event_tracker import PipelineEventTracker
        _, mock_cursor, _ = stub_connections
        tracker = PipelineEventTracker()
        with tracker.track("TABLE_TOTAL", _make_table_config()) as event:
            event.status = "SKIPPED"
            event.event_detail = "Lock held by another run"
        ins = _insert_calls(mock_cursor)[0]
        args = _insert_args(ins)
        assert args[8] == "SKIPPED"
        # EventDetail at index 4.
        assert args[4] == "Lock held by another run"

    def test_invalid_status_coerced_to_success(
        self, clean_eventvars, stub_connections
    ):
        """Defensive: out-of-enum status is logged + corrected to SUCCESS."""
        from observability.event_tracker import PipelineEventTracker
        _, mock_cursor, _ = stub_connections
        tracker = PipelineEventTracker()
        with tracker.track("EXTRACT", _make_table_config()) as event:
            event.status = "SUCCEEDED"  # typo: not in enum
        ins = _insert_calls(mock_cursor)[0]
        # Coerced to SUCCESS so the INSERT passes
        # CK_PipelineEventLog_Status.
        assert _insert_args(ins)[8] == "SUCCESS"

    def test_exception_error_message_truncated(
        self, clean_eventvars, stub_connections
    ):
        """ErrorMessage is truncated to 4000 chars per v1 contract."""
        from observability.event_tracker import PipelineEventTracker
        _, mock_cursor, _ = stub_connections
        tracker = PipelineEventTracker()
        huge = "x" * 10000
        with pytest.raises(ValueError):
            with tracker.track("EXTRACT", _make_table_config()):
                raise ValueError(huge)
        ins = _insert_calls(mock_cursor)[0]
        # ErrorMessage at index 9.
        err = _insert_args(ins)[9]
        assert err is not None
        assert len(err) <= 4000


# ---------------------------------------------------------------------------
# context manager: timing + row counts.
# ---------------------------------------------------------------------------


class TestTimingAndRowCounts:

    def test_duration_ms_populated_on_exit(
        self, clean_eventvars, stub_connections
    ):
        from observability.event_tracker import PipelineEventTracker
        _, mock_cursor, _ = stub_connections
        tracker = PipelineEventTracker()
        with tracker.track("EXTRACT", _make_table_config()):
            pass
        ins = _insert_calls(mock_cursor)[0]
        # DurationMs at index 7.
        assert isinstance(_insert_args(ins)[7], int)
        assert _insert_args(ins)[7] >= 0

    def test_row_counts_threaded_through_insert(
        self, clean_eventvars, stub_connections
    ):
        from observability.event_tracker import PipelineEventTracker
        _, mock_cursor, _ = stub_connections
        tracker = PipelineEventTracker()
        with tracker.track("CDC_PROMOTION", _make_table_config()) as event:
            event.rows_processed = 100
            event.rows_inserted = 30
            event.rows_updated = 25
            event.rows_deleted = 5
            event.rows_unchanged = 40
            event.rows_before = 200
            event.rows_after = 230
        args = _insert_args(_insert_calls(mock_cursor)[0])
        # Field mapping: RowsProcessed=10, RowsInserted=11, RowsUpdated=12,
        # RowsDeleted=13, RowsUnchanged=14, RowsBefore=15, RowsAfter=16.
        assert args[10] == 100
        assert args[11] == 30
        assert args[12] == 25
        assert args[13] == 5
        assert args[14] == 40
        assert args[15] == 200
        assert args[16] == 230

    def test_rows_per_second_calculated(
        self, clean_eventvars, stub_connections
    ):
        from observability.event_tracker import PipelineEventTracker
        _, mock_cursor, _ = stub_connections
        tracker = PipelineEventTracker()
        with tracker.track("EXTRACT", _make_table_config()) as event:
            event.rows_processed = 100
        args = _insert_args(_insert_calls(mock_cursor)[0])
        # RowsPerSecond at index 19; populated whenever duration > 0
        # and rows_processed > 0.
        rps = args[19]
        assert rps >= 0

    def test_table_created_serialized_to_bit(
        self, clean_eventvars, stub_connections
    ):
        from observability.event_tracker import PipelineEventTracker
        _, mock_cursor, _ = stub_connections
        tracker = PipelineEventTracker()
        with tracker.track("EXTRACT", _make_table_config()) as event:
            event.table_created = True
        args = _insert_args(_insert_calls(mock_cursor)[0])
        # TableCreated at index 17, serialized to 0/1.
        assert args[17] == 1


# ---------------------------------------------------------------------------
# context manager: identity resolution (table_config vs contextvars).
# ---------------------------------------------------------------------------


class TestIdentityResolution:

    def test_table_config_resolved_into_event(
        self, clean_eventvars, stub_connections
    ):
        from observability.event_tracker import PipelineEventTracker
        _, mock_cursor, _ = stub_connections
        tracker = PipelineEventTracker()
        tc = _make_table_config(table="TXN", source="CCM")
        with tracker.track("EXTRACT", tc) as event:
            assert event.table_name == "TXN"
            assert event.source_name == "CCM"

    def test_contextvars_used_when_table_config_none(
        self, clean_eventvars, stub_connections
    ):
        from observability.event_tracker import (
            PipelineEventTracker, set_event_context,
        )
        _, _, _ = stub_connections
        tracker = PipelineEventTracker()
        set_event_context(
            batch_id=1, table_name="CTX_T", source_name="CTX_S"
        )
        with tracker.track("EXTRACT") as event:
            assert event.table_name == "CTX_T"
            assert event.source_name == "CTX_S"

    def test_table_config_overrides_contextvars(
        self, clean_eventvars, stub_connections
    ):
        """Explicit table_config arg wins over contextvars."""
        from observability.event_tracker import (
            PipelineEventTracker, set_event_context,
        )
        _, _, _ = stub_connections
        tracker = PipelineEventTracker()
        set_event_context(
            batch_id=1, table_name="CTX_TABLE", source_name="CTX_SOURCE"
        )
        with tracker.track("EXTRACT", _make_table_config("OVR", "OVS")) as event:
            assert event.table_name == "OVR"
            assert event.source_name == "OVS"

    def test_clear_event_context_resets_all(self):
        from observability.event_tracker import (
            clear_event_context,
            set_event_context,
            _batch_id_ctx,
            _table_name_ctx,
            _source_name_ctx,
            _gate_id_ctx,
        )
        set_event_context(
            batch_id=1, table_name="T", source_name="S", gate_id=10
        )
        clear_event_context()
        assert _batch_id_ctx.get() is None
        assert _table_name_ctx.get() is None
        assert _source_name_ctx.get() is None
        assert _gate_id_ctx.get() is None


# ---------------------------------------------------------------------------
# D33 cooperative cancellation.
# ---------------------------------------------------------------------------


class TestCancellation:

    def test_no_gate_id_skips_cancel_poll(
        self, clean_eventvars, stub_connections
    ):
        """gate_id=None means no cursor_for() call for the cancel check."""
        from observability.event_tracker import PipelineEventTracker
        _, _, cancel_cursor = stub_connections
        tracker = PipelineEventTracker()
        with tracker.track("EXTRACT", _make_table_config()):
            pass
        # cancel_cursor.execute should NOT have been called (gate_id=None).
        assert cancel_cursor.execute.call_count == 0

    def test_gate_id_triggers_cancel_poll(
        self, clean_eventvars, stub_connections
    ):
        """gate_id set means cursor_for() runs the cancellation query."""
        from observability.event_tracker import (
            PipelineEventTracker, set_event_context,
        )
        _, _, cancel_cursor = stub_connections
        set_event_context(
            batch_id=10, table_name="X", source_name="Y", gate_id=5
        )
        tracker = PipelineEventTracker()
        with tracker.track("EXTRACT"):
            pass
        # cancel_cursor.execute called once for the cancellation poll.
        assert cancel_cursor.execute.call_count == 1
        sql = cancel_cursor.execute.call_args.args[0]
        assert "CancellationRequested" in sql
        assert "PipelineExecutionGate" in sql

    def test_cancel_flag_set_marks_event_skipped(
        self, clean_eventvars, stub_connections_with_cancel
    ):
        from observability.event_tracker import (
            PipelineEventTracker, set_event_context,
        )
        _, mock_cursor, _ = stub_connections_with_cancel
        set_event_context(
            batch_id=10, table_name="X", source_name="Y", gate_id=5
        )
        tracker = PipelineEventTracker()
        with tracker.track("EXTRACT") as event:
            assert event.cancellation_requested is True
            assert event.status == "SKIPPED"
        # SKIPPED row written.
        assert _insert_args(_insert_calls(mock_cursor)[0])[8] == "SKIPPED"

    def test_cancel_event_detail_default(
        self, clean_eventvars, stub_connections_with_cancel
    ):
        from observability.event_tracker import (
            PipelineEventTracker, set_event_context,
        )
        _, mock_cursor, _ = stub_connections_with_cancel
        set_event_context(
            batch_id=10, table_name="X", source_name="Y", gate_id=5
        )
        tracker = PipelineEventTracker()
        with tracker.track("EXTRACT") as event:
            assert event.event_detail == "cancellation_acked"
        # event_detail at index 4.
        args = _insert_args(_insert_calls(mock_cursor)[0])
        assert args[4] == "cancellation_acked"

    def test_cancel_caller_event_detail_wins(
        self, clean_eventvars, stub_connections_with_cancel
    ):
        """Explicit event_detail arg is preserved on cancellation path."""
        from observability.event_tracker import (
            PipelineEventTracker, set_event_context,
        )
        _, mock_cursor, _ = stub_connections_with_cancel
        set_event_context(
            batch_id=10, table_name="X", source_name="Y", gate_id=5
        )
        tracker = PipelineEventTracker()
        with tracker.track(
            "EXTRACT", event_detail="caller-supplied"
        ) as event:
            # Caller-supplied event_detail preserved (not overwritten).
            assert event.event_detail == "caller-supplied"

    def test_cancel_poll_failure_treated_as_no_cancel(
        self, clean_eventvars
    ):
        """Best-effort: gate-table query failure does NOT flip the event
        to SKIPPED. Returns False so the step proceeds normally."""
        snapshot = _snapshot_utils_connections_state()
        try:
            import utils  # noqa: F401
            stub = types.ModuleType("utils.connections")
            mock_conn = MagicMock(name="general_conn")
            mock_cursor = MagicMock(name="cursor")
            mock_cursor.fetchone.return_value = (4242,)
            mock_conn.cursor.return_value = mock_cursor
            stub.get_general_connection = MagicMock(return_value=mock_conn)

            @contextmanager
            def _broken_cursor_for(_db):
                raise RuntimeError("DB down")
                yield  # unreachable

            stub.cursor_for = _broken_cursor_for
            sys.modules["utils.connections"] = stub
            sys.modules["utils"].connections = stub

            from observability.event_tracker import (
                PipelineEventTracker, set_event_context,
            )
            set_event_context(
                batch_id=10, table_name="X", source_name="Y", gate_id=5
            )
            tracker = PipelineEventTracker()
            with tracker.track("EXTRACT") as event:
                assert event.cancellation_requested is False
                assert event.status == "IN_PROGRESS"
            # The step proceeded and wrote SUCCESS.
            ins = _insert_calls(mock_cursor)[0]
            assert _insert_args(ins)[8] == "SUCCESS"
        finally:
            _restore_utils_connections_state(snapshot)


# ---------------------------------------------------------------------------
# P5 + OBS-7: metadata redaction (v2 addition).
# ---------------------------------------------------------------------------


class TestMetadataRedaction:

    def test_metadata_passed_through_when_no_secrets(
        self, clean_eventvars, stub_connections
    ):
        """Plain JSON metadata makes it to PipelineEventLog unchanged."""
        from observability.event_tracker import PipelineEventTracker
        _, mock_cursor, _ = stub_connections
        tracker = PipelineEventTracker()
        with tracker.track("CDC_PROMOTION", _make_table_config()) as event:
            event.metadata = json.dumps({"update_ratio": 0.05, "inserts": 10})
        args = _insert_args(_insert_calls(mock_cursor)[0])
        # Metadata at index 18.
        meta = args[18]
        assert "update_ratio" in meta
        assert "0.05" in meta
        # No REDACTED marker injected by M14.
        assert "REDACTED" not in meta

    def test_password_pattern_redacted(
        self, clean_eventvars, stub_connections
    ):
        """M14 default pattern: password=value redacted in metadata."""
        from observability.event_tracker import PipelineEventTracker
        _, mock_cursor, _ = stub_connections
        tracker = PipelineEventTracker()
        with tracker.track("EXTRACT", _make_table_config()) as event:
            # M14 password pattern matches "*password = <value>". Construct
            # a string outside JSON since JSON-escaped values won't match
            # the bare password=... regex.
            event.metadata = "user_password=secret123"
        args = _insert_args(_insert_calls(mock_cursor)[0])
        meta = args[18]
        # M14 substitutes the matched span with the REDACTED marker.
        assert "REDACTED" in meta
        assert "secret123" not in meta

    def test_passphrase_pattern_redacted(
        self, clean_eventvars, stub_connections
    ):
        from observability.event_tracker import PipelineEventTracker
        _, mock_cursor, _ = stub_connections
        tracker = PipelineEventTracker()
        with tracker.track("EXTRACT", _make_table_config()) as event:
            event.metadata = "passphrase=correct-horse-battery-staple"
        args = _insert_args(_insert_calls(mock_cursor)[0])
        meta = args[18]
        assert "REDACTED" in meta
        assert "correct-horse-battery-staple" not in meta

    def test_empty_metadata_left_as_none(
        self, clean_eventvars, stub_connections
    ):
        from observability.event_tracker import PipelineEventTracker
        _, mock_cursor, _ = stub_connections
        tracker = PipelineEventTracker()
        with tracker.track("EXTRACT", _make_table_config()):
            pass
        args = _insert_args(_insert_calls(mock_cursor)[0])
        # Metadata stays None when caller didn't set it.
        assert args[18] is None

    def test_obs7_json_merge_pattern_preserved(
        self, clean_eventvars, stub_connections
    ):
        """OBS-7: load -> merge -> dumps. The redaction runs on the final
        serialized form, so callers can mutate metadata mid-flight."""
        from observability.event_tracker import PipelineEventTracker
        _, mock_cursor, _ = stub_connections
        tracker = PipelineEventTracker()
        with tracker.track("SCD2_PROMOTION", _make_table_config()) as event:
            existing = json.loads(event.metadata) if event.metadata else {}
            existing["active_ratio"] = 0.05
            event.metadata = json.dumps(existing)
            existing2 = json.loads(event.metadata)
            existing2["active_count"] = 100
            event.metadata = json.dumps(existing2)
        args = _insert_args(_insert_calls(mock_cursor)[0])
        parsed = json.loads(args[18])
        assert parsed["active_ratio"] == 0.05
        assert parsed["active_count"] == 100

    def test_redactor_failure_writes_unredacted(
        self, clean_eventvars, stub_connections
    ):
        """If the M14 redactor raises, the event still writes (defense in
        depth: prefer un-redacted audit row to no audit row)."""
        from observability import event_tracker as mod
        _, mock_cursor, _ = stub_connections
        tracker = mod.PipelineEventTracker()

        # Force the redactor to raise.
        def _exploding_redactor(_text):
            raise RuntimeError("regex blew up")

        tracker._metadata_redactor = _exploding_redactor

        with tracker.track("EXTRACT", _make_table_config()) as event:
            event.metadata = "user_password=xxx"
        args = _insert_args(_insert_calls(mock_cursor)[0])
        # Event still written. The metadata is the un-redacted original
        # (redactor never produced a replacement).
        assert args[18] == "user_password=xxx"


# ---------------------------------------------------------------------------
# OBS-5 explicit commit + write resilience.
# ---------------------------------------------------------------------------


class TestWriteResilience:

    def test_explicit_commit_on_event_write(
        self, clean_eventvars, stub_connections
    ):
        """OBS-5: every PipelineEventLog INSERT is followed by conn.commit()."""
        from observability.event_tracker import PipelineEventTracker
        mock_conn, _, _ = stub_connections
        tracker = PipelineEventTracker()
        with tracker.track("EXTRACT", _make_table_config()):
            pass
        # Two commits: one for batch_id allocation, one for the event row.
        assert mock_conn.commit.call_count == 2

    def test_write_failure_does_not_raise(
        self, clean_eventvars
    ):
        """OBS-4 pattern (M15 precedent): write failure goes to stderr +
        logger; the caller exception path is untouched."""
        snapshot = _snapshot_utils_connections_state()
        try:
            import utils  # noqa: F401
            stub = types.ModuleType("utils.connections")
            mock_conn = MagicMock(name="general_conn")
            mock_cursor = MagicMock(name="cursor")
            mock_cursor.fetchone.return_value = (777,)
            # First execute(): batch_id allocation succeeds.
            # Subsequent execute(): event INSERT raises.
            call_log = {"n": 0}

            def _execute(*args, **kwargs):
                call_log["n"] += 1
                if call_log["n"] >= 2:
                    raise RuntimeError("DB drop")
                return None

            mock_cursor.execute.side_effect = _execute
            mock_conn.cursor.return_value = mock_cursor
            stub.get_general_connection = MagicMock(return_value=mock_conn)

            @contextmanager
            def _cursor_for(_db):
                yield MagicMock(name="cancel_cursor", fetchone=MagicMock(return_value=(0,)))

            stub.cursor_for = _cursor_for
            sys.modules["utils.connections"] = stub
            sys.modules["utils"].connections = stub

            from observability.event_tracker import PipelineEventTracker
            tracker = PipelineEventTracker()
            # The track() context should NOT raise even though the
            # INSERT fails.
            with tracker.track("EXTRACT", _make_table_config()):
                pass  # caller code is unaffected
        finally:
            _restore_utils_connections_state(snapshot)

    def test_caller_exception_takes_priority_over_write_failure(
        self, clean_eventvars
    ):
        """If both the caller raises AND the audit write fails, the
        caller exception wins (must not be swallowed)."""
        snapshot = _snapshot_utils_connections_state()
        try:
            import utils  # noqa: F401
            stub = types.ModuleType("utils.connections")
            mock_conn = MagicMock(name="general_conn")
            mock_cursor = MagicMock(name="cursor")
            mock_cursor.fetchone.return_value = (777,)
            call_log = {"n": 0}

            def _execute(*args, **kwargs):
                call_log["n"] += 1
                if call_log["n"] >= 2:
                    raise RuntimeError("DB drop")
                return None

            mock_cursor.execute.side_effect = _execute
            mock_conn.cursor.return_value = mock_cursor
            stub.get_general_connection = MagicMock(return_value=mock_conn)

            @contextmanager
            def _cursor_for(_db):
                yield MagicMock(name="cc", fetchone=MagicMock(return_value=(0,)))

            stub.cursor_for = _cursor_for
            sys.modules["utils.connections"] = stub
            sys.modules["utils"].connections = stub

            from observability.event_tracker import PipelineEventTracker
            tracker = PipelineEventTracker()
            with pytest.raises(ValueError, match="caller-error"):
                with tracker.track("EXTRACT", _make_table_config()):
                    raise ValueError("caller-error")
        finally:
            _restore_utils_connections_state(snapshot)


# ---------------------------------------------------------------------------
# v2 INSERT shape variants.
# ---------------------------------------------------------------------------


class TestInsertShape:

    def test_v1_shape_when_no_cycle_context(
        self, clean_eventvars, stub_connections
    ):
        """No cycle_type / cycle_date / server_role -> 20-arg v1 INSERT."""
        from observability.event_tracker import PipelineEventTracker
        _, mock_cursor, _ = stub_connections
        tracker = PipelineEventTracker()
        with tracker.track("EXTRACT", _make_table_config()):
            pass
        ins = _insert_calls(mock_cursor)[0]
        sql = ins.args[0]
        # v1 INSERT lists 20 columns (no CycleType/CycleDate/ServerRole).
        assert "CycleType" not in sql
        assert "CycleDate" not in sql
        assert "ServerRole" not in sql
        # 20 positional args.
        assert len(ins.args) - 1 == 20

    def test_v2_shape_when_cycle_context_set(
        self, clean_eventvars, stub_connections
    ):
        """cycle_type / cycle_date / server_role set -> 23-arg extended
        INSERT with the new columns threaded through."""
        from observability.event_tracker import PipelineEventTracker
        _, mock_cursor, _ = stub_connections
        tracker = PipelineEventTracker()
        cd = date(2026, 5, 13)
        with tracker.track("EXTRACT", _make_table_config()) as event:
            event.cycle_type = "AM"
            event.cycle_date = cd
            event.server_role = "production"
        ins = _insert_calls(mock_cursor)[0]
        sql = ins.args[0]
        assert "CycleType" in sql
        assert "CycleDate" in sql
        assert "ServerRole" in sql
        # 23 positional args.
        args = _insert_args(ins)
        assert len(args) == 23
        assert args[20] == "AM"
        assert args[21] == cd
        assert args[22] == "production"

    def test_v2_shape_with_only_server_role(
        self, clean_eventvars, stub_connections
    ):
        """Even one of the three v2 fields triggers the extended INSERT."""
        from observability.event_tracker import PipelineEventTracker
        _, mock_cursor, _ = stub_connections
        tracker = PipelineEventTracker()
        with tracker.track("EXTRACT", _make_table_config()) as event:
            event.server_role = "test"
        ins = _insert_calls(mock_cursor)[0]
        sql = ins.args[0]
        assert "ServerRole" in sql


# ---------------------------------------------------------------------------
# skip() standalone helper.
# ---------------------------------------------------------------------------


class TestSkipHelper:

    def test_skip_writes_skipped_row(self, clean_eventvars, stub_connections):
        from observability.event_tracker import skip
        _, mock_cursor, _ = stub_connections
        skip(
            event_type="TABLE_TOTAL",
            table_name="ACCT",
            source_name="DNA",
            batch_id=100,
            reason="Lock held by another run",
        )
        ins = _insert_calls(mock_cursor)
        assert len(ins) == 1
        args = _insert_args(ins[0])
        # BatchId / TableName / SourceName / EventType / EventDetail
        assert args[0] == 100
        assert args[1] == "ACCT"
        assert args[2] == "DNA"
        assert args[3] == "TABLE_TOTAL"
        assert args[4] == "Lock held by another run"
        # Status (index 8) == SKIPPED.
        assert args[8] == "SKIPPED"

    def test_skip_commits_per_obs5(
        self, clean_eventvars, stub_connections
    ):
        from observability.event_tracker import skip
        mock_conn, _, _ = stub_connections
        skip(
            event_type="EXTRACT",
            table_name="X",
            source_name="Y",
            batch_id=1,
            reason="reason",
        )
        # One INSERT + one commit.
        assert mock_conn.commit.call_count == 1

    def test_skip_failure_does_not_raise(self, clean_eventvars):
        """skip() failures are swallowed so a busted observability layer
        does not crash the caller."""
        snapshot = _snapshot_utils_connections_state()
        try:
            import utils  # noqa: F401
            stub = types.ModuleType("utils.connections")
            stub.get_general_connection = MagicMock(
                side_effect=RuntimeError("DB down")
            )
            sys.modules["utils.connections"] = stub
            sys.modules["utils"].connections = stub
            from observability.event_tracker import skip
            # Should not raise.
            skip(
                event_type="EXTRACT",
                table_name="X",
                source_name="Y",
                batch_id=1,
                reason="reason",
            )
        finally:
            _restore_utils_connections_state(snapshot)


# ---------------------------------------------------------------------------
# Spec assertions: D33 / D67 / OBS-3 / OBS-5 / OBS-7 invariants pinned.
# ---------------------------------------------------------------------------


class TestSpecInvariants:

    def test_event_log_id_not_in_insert_columns(
        self, clean_eventvars, stub_connections
    ):
        """EventLogId is IDENTITY: must NOT be in the INSERT column list."""
        from observability.event_tracker import PipelineEventTracker
        _, mock_cursor, _ = stub_connections
        tracker = PipelineEventTracker()
        with tracker.track("EXTRACT", _make_table_config()):
            pass
        ins_sql = _insert_calls(mock_cursor)[0].args[0]
        # EventLogId is the IDENTITY PK; never explicitly inserted.
        assert "EventLogId" not in ins_sql

    def test_created_at_not_in_insert_columns(
        self, clean_eventvars, stub_connections
    ):
        """CreatedAt has DDL DEFAULT SYSUTCDATETIME(): never explicitly inserted."""
        from observability.event_tracker import PipelineEventTracker
        _, mock_cursor, _ = stub_connections
        tracker = PipelineEventTracker()
        with tracker.track("EXTRACT", _make_table_config()):
            pass
        ins_sql = _insert_calls(mock_cursor)[0].args[0]
        # CreatedAt should not appear in the INSERT column list (DEFAULT
        # SYSUTCDATETIME() handles it server-side).
        assert "CreatedAt" not in ins_sql

    def test_insert_targets_ops_schema(
        self, clean_eventvars, stub_connections
    ):
        from observability.event_tracker import PipelineEventTracker
        _, mock_cursor, _ = stub_connections
        tracker = PipelineEventTracker()
        with tracker.track("EXTRACT", _make_table_config()):
            pass
        ins_sql = _insert_calls(mock_cursor)[0].args[0]
        # Per CLAUDE.md: PipelineEventLog lives in General.ops schema.
        # Module uses two-part name (ops.PipelineEventLog) so it works
        # against whatever database the connection landed in (General
        # via get_general_connection).
        assert "ops.PipelineEventLog" in ins_sql

    def test_status_in_progress_initial_default(
        self, clean_eventvars, stub_connections
    ):
        """Pitfall 9 + Round 1 enum: default status is IN_PROGRESS so
        any mid-flight write still satisfies CK_PipelineEventLog_Status."""
        from observability.event_tracker import PipelineEvent
        e = PipelineEvent(event_type="X", table_name=None, source_name=None)
        assert e.status == "IN_PROGRESS"

    def test_started_at_is_utc(self, clean_eventvars, stub_connections):
        from observability.event_tracker import PipelineEventTracker
        _, _, _ = stub_connections
        tracker = PipelineEventTracker()
        with tracker.track("EXTRACT", _make_table_config()) as event:
            assert event.started_at is not None
            # Per spec: started_at is timezone-aware UTC.
            assert event.started_at.tzinfo is not None
            # And the timezone is UTC (offset 0).
            assert event.started_at.utcoffset().total_seconds() == 0

    def test_completed_at_is_after_started_at(
        self, clean_eventvars, stub_connections
    ):
        from observability.event_tracker import PipelineEventTracker
        _, mock_cursor, _ = stub_connections
        tracker = PipelineEventTracker()
        with tracker.track("EXTRACT", _make_table_config()) as event:
            pass
        # After the with block exits, completed_at is set.
        assert event.completed_at is not None
        assert event.completed_at >= event.started_at
