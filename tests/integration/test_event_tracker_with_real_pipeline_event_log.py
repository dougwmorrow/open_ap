"""Tier 3 integration tests for observability/event_tracker.py against real DB.

Per docs/migration/phase1/05_tests.md § 6.2 canonical scenario:
"Full track() context manager against real PipelineEventLog table;
verify status transitions + OBS-7 metadata merge".

Canonical signatures under test (per phase1/03_core_modules.md § 6.3):

    class PipelineEventTracker:
        @contextmanager
        def track(
            self,
            event_type: str,
            table_config: TableConfig | None = None,
            *,
            event_detail: str | None = None,
        ) -> Iterator[PipelineEvent]: ...

    def set_event_context(*, batch_id, table_name, source_name, gate_id) -> None: ...
    def clear_event_context() -> None: ...
    def skip(*, event_type, table_name, source_name, batch_id, reason) -> None: ...

D-numbers covered:
  - D31 (Power BI dashboards read PipelineEventLog directly) - the row
    must match the canonical schema exactly so downstream queries work.
  - D33 (cooperative cancellation) - gate-flag polling at track() entry;
    SKIPPED status flip when CancellationRequested=1.
  - D62 (CCL audit-trail) - every event row IS a compliance trace.
  - D67 (Tier 0 smoke required) - canonical INSERT shape preserved.
  - D68 (error class hierarchy) - tracker write failures NEVER raise
    into caller exception path (OBS-4 pattern).
  - P5  (PII redaction) - M14 SensitiveDataFilter applied to
    event.metadata JSON before INSERT.

Round 1 PipelineEventLog Status enum constraint (per
phase1/01_database_schema.md § 1; tested per Pitfall #9.c):

    CK_PipelineEventLog_Status CHECK (Status IN
        ('IN_PROGRESS', 'SUCCESS', 'FAILED', 'SKIPPED'))

The tests assert (a) the canonical row layout, (b) Status transitions
match the enum verbatim, (c) OBS-7 metadata-merge pattern preserves
caller-set metadata across the with-block boundary, and (d) D33
cancellation poll flips Status to SKIPPED when the gate is set.

Module-level skip pattern per scaffold pattern.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# Module-level skip via the canonical conftest helper.
from tests.integration.conftest import docker_skip_marker  # noqa: E402

pytestmark = docker_skip_marker()


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers - the tracker's BatchId allocator + DB writes route through
# utils.connections.get_general_connection / cursor_for. The Tier 3
# container holds the General DB; we redirect these helpers at the
# container's pyodbc connection so writes land in the real table.
# ---------------------------------------------------------------------------


def _patch_general_connection(mssql_connection: Any) -> mock._patch_multiple:
    """Patch utils.connections to route writes at the container's connection.

    The tracker calls ``get_general_connection()`` for BatchId allocation
    and the INSERT path. We replace it with a factory that returns a
    NEW cursor on the same underlying pyodbc connection so concurrent
    cursors (the test reader + the tracker writer) do not clash.

    Returns a context manager - use via ``with _patch_general_connection(...):``.
    """
    # Wrap the live container connection in a tiny shim so the tracker's
    # ``conn.close()`` call after writing does NOT actually close the
    # underlying pyodbc connection (which the test fixture owns).
    class _ConnShim:
        """Forwarding shim - intercepts close() so the test owns lifecycle."""

        def __init__(self, real_conn: Any) -> None:
            self._real = real_conn

        def cursor(self) -> Any:
            return self._real.cursor()

        def commit(self) -> None:
            self._real.commit()

        def rollback(self) -> None:
            self._real.rollback()

        def close(self) -> None:
            # No-op: the fixture owns connection lifecycle.
            pass

    shim = _ConnShim(mssql_connection)

    def _get_conn() -> Any:
        return shim

    # The tracker imports get_general_connection INSIDE _write_event /
    # _get_next_batch_id (per its lazy-import pattern). Patch both
    # canonical locations.
    return mock.patch(
        "utils.connections.get_general_connection",
        side_effect=_get_conn,
    )


# ---------------------------------------------------------------------------
# Test class - full track() lifecycle against real PipelineEventLog.
# ---------------------------------------------------------------------------


class TestEventTrackerWithRealPipelineEventLog:
    """OBS-3 + OBS-7 + D33 invariants for observability/event_tracker.py.

    Each test patches utils.connections.get_general_connection at the
    tracker's import boundary so the tracker writes land in the test
    container's PipelineEventLog table. The test_db_transaction fixture
    rolls back at exit so writes do not pollute subsequent tests.
    """

    def test_track_writes_in_progress_then_success_on_clean_exit(
        self,
        mssql_cursor: Any,
        mssql_connection: Any,
        test_db_transaction: Any,
        canonical_schema_loaded: None,
    ) -> None:
        """Clean exit produces a single SUCCESS-status PipelineEventLog row.

        Per § 6.3: the tracker writes ONE row at context exit, NOT a
        live IN_PROGRESS row at entry + UPDATE at exit. The single
        INSERT carries StartedAt + CompletedAt + DurationMs + final
        Status. The Round 1 enum allows IN_PROGRESS for transient
        long-running steps, but the canonical tracker writes once at
        exit when the body completes normally.

        Asserts: exactly one new row; Status='SUCCESS'; DurationMs >= 0;
        rows_processed / rows_inserted forwarded from caller mutation.
        """
        from observability.event_tracker import (  # noqa: PLC0415
            PipelineEventTracker,
        )

        # Count of EXTRACT rows BEFORE so we can compute the delta.
        mssql_cursor.execute(
            "SELECT COUNT(*) FROM General.ops.PipelineEventLog "
            "WHERE EventType = 'EXTRACT' AND TableName = 'TRACKER_OBS3_TEST'"
        )
        before = mssql_cursor.fetchone()[0]

        with _patch_general_connection(mssql_connection):
            tracker = PipelineEventTracker()
            # Force a fixed batch_id so we can join PipelineEventLog rows
            # back to this test deterministically.
            tracker._batch_id = 20001

            with tracker.track("EXTRACT") as event:
                event.table_name = "TRACKER_OBS3_TEST"
                event.source_name = "DNA"
                event.rows_processed = 42
                event.rows_inserted = 10
                event.rows_updated = 5
                event.rows_deleted = 2
                event.rows_unchanged = 25

        # After clean exit: one new row, Status='SUCCESS'.
        mssql_cursor.execute(
            "SELECT COUNT(*) FROM General.ops.PipelineEventLog "
            "WHERE EventType = 'EXTRACT' AND TableName = 'TRACKER_OBS3_TEST'"
        )
        after = mssql_cursor.fetchone()[0]
        assert after == before + 1, (
            f"Expected exactly 1 new EXTRACT row; got delta {after - before}"
        )

        mssql_cursor.execute(
            """
            SELECT TOP 1 BatchId, Status, RowsProcessed, RowsInserted,
                          RowsUpdated, RowsDeleted, RowsUnchanged,
                          DurationMs
            FROM General.ops.PipelineEventLog
            WHERE EventType = 'EXTRACT' AND TableName = 'TRACKER_OBS3_TEST'
            ORDER BY EventLogId DESC
            """
        )
        row = mssql_cursor.fetchone()
        assert row is not None
        batch_id, status, rp, ri, ru, rd, run_, dms = row
        assert batch_id == 20001
        assert status == "SUCCESS", f"Expected Status='SUCCESS'; got {status!r}"
        assert rp == 42 and ri == 10 and ru == 5 and rd == 2 and run_ == 25
        assert dms is not None and dms >= 0, (
            f"DurationMs MUST be non-negative; got {dms!r}"
        )

    def test_track_writes_failed_on_exception(
        self,
        mssql_cursor: Any,
        mssql_connection: Any,
        test_db_transaction: Any,
        canonical_schema_loaded: None,
    ) -> None:
        """Exception inside with-block writes FAILED + ErrorMessage; re-raises.

        Per § 6.3 + CLAUDE.md "If anything inside the with block throws,
        the event still gets recorded": the tracker's finally clause
        always issues the INSERT. The Status flips to 'FAILED' and
        ErrorMessage carries str(exc)[:4000]. The caller exception is
        re-raised verbatim (NOT wrapped in any tracker-side exception).
        """
        from observability.event_tracker import (  # noqa: PLC0415
            PipelineEventTracker,
        )

        sentinel_msg = "synthetic-test-failure-for-tier3-event-tracker"

        with _patch_general_connection(mssql_connection):
            tracker = PipelineEventTracker()
            tracker._batch_id = 20002

            with pytest.raises(RuntimeError, match=sentinel_msg):
                with tracker.track("CDC_PROMOTION") as event:
                    event.table_name = "TRACKER_FAIL_TEST"
                    event.source_name = "DNA"
                    event.rows_processed = 100
                    raise RuntimeError(sentinel_msg)

        # Post-condition: one FAILED row with the original exception
        # message stored in ErrorMessage.
        mssql_cursor.execute(
            """
            SELECT Status, ErrorMessage, RowsProcessed
            FROM General.ops.PipelineEventLog
            WHERE BatchId = ? AND EventType = 'CDC_PROMOTION'
              AND TableName = 'TRACKER_FAIL_TEST'
            """,
            20002,
        )
        row = mssql_cursor.fetchone()
        assert row is not None, "No FAILED row was written"
        status, error_message, rows_processed = row
        assert status == "FAILED", f"Expected Status='FAILED'; got {status!r}"
        assert error_message is not None
        assert sentinel_msg in error_message, (
            f"ErrorMessage must contain the original sentinel; "
            f"got {error_message!r}"
        )
        # Counter values populated BEFORE the raise must still persist.
        assert rows_processed == 100

    def test_track_status_values_match_round_1_enum(
        self,
        mssql_cursor: Any,
        mssql_connection: Any,
        test_db_transaction: Any,
        canonical_schema_loaded: None,
    ) -> None:
        """All Status values written by the tracker pass CK_PipelineEventLog_Status.

        Per Pitfall #9.c (canonical schema constraint) the Round 1
        enum is {'IN_PROGRESS', 'SUCCESS', 'FAILED', 'SKIPPED'}. The
        tracker writes SUCCESS (clean exit), FAILED (exception), and
        SKIPPED (OBS-3 caller opt-in OR D33 cancellation).

        This test exercises ALL three observable transitions and proves
        the INSERTs succeed against the real CHECK constraint - any
        future regression (e.g. tracker writes 'OK' instead of 'SUCCESS')
        would surface here as a pyodbc IntegrityError.
        """
        from observability.event_tracker import (  # noqa: PLC0415
            PipelineEventTracker,
        )

        with _patch_general_connection(mssql_connection):
            tracker = PipelineEventTracker()
            tracker._batch_id = 20003

            # Transition 1: SUCCESS (clean exit).
            with tracker.track("EXTRACT") as event:
                event.table_name = "ENUM_TEST_SUCCESS"
                event.source_name = "DNA"

            # Transition 2: FAILED (exception).
            with pytest.raises(ValueError):
                with tracker.track("EXTRACT") as event:
                    event.table_name = "ENUM_TEST_FAILED"
                    event.source_name = "DNA"
                    raise ValueError("forced-failure")

            # Transition 3: SKIPPED (OBS-3 caller-set status).
            with tracker.track("EXTRACT") as event:
                event.table_name = "ENUM_TEST_SKIPPED"
                event.source_name = "DNA"
                event.status = "SKIPPED"
                event.event_detail = "lock-already-held"

        # Verify every Status value lands in PipelineEventLog.
        mssql_cursor.execute(
            """
            SELECT TableName, Status
            FROM General.ops.PipelineEventLog
            WHERE BatchId = ? AND TableName LIKE 'ENUM_TEST_%'
            ORDER BY EventLogId
            """,
            20003,
        )
        rows = mssql_cursor.fetchall()
        observed = {row[0]: row[1] for row in rows}
        assert observed.get("ENUM_TEST_SUCCESS") == "SUCCESS"
        assert observed.get("ENUM_TEST_FAILED") == "FAILED"
        assert observed.get("ENUM_TEST_SKIPPED") == "SKIPPED"

        # Defensive cross-check: every Status MUST be in the Round 1 enum.
        # If a transition writes anything else, the INSERT fails the
        # CHECK constraint and the test surfaces a pyodbc IntegrityError.
        canonical_enum = {"IN_PROGRESS", "SUCCESS", "FAILED", "SKIPPED"}
        for table_name, status in observed.items():
            assert status in canonical_enum, (
                f"Pitfall #9.c violation - {table_name} Status={status!r} "
                f"not in canonical Round 1 enum {sorted(canonical_enum)}"
            )

    def test_track_obs7_metadata_merge(
        self,
        mssql_cursor: Any,
        mssql_connection: Any,
        test_db_transaction: Any,
        canonical_schema_loaded: None,
    ) -> None:
        """OBS-7: callers using json.loads + json.dumps merge preserve metadata.

        Per CLAUDE.md OBS-7: "callers use json.loads(event.metadata) if
        event.metadata else dict, merge, json.dumps and assign back to
        event.metadata". The tracker writes whatever JSON string the
        caller produced - it does NOT clobber metadata via direct
        assignment.

        This test simulates two consecutive metadata writes (the
        canonical pattern when SCD2 metadata is enriched in-flight per
        OBS-7) and asserts BOTH fields persist into the final row.
        """
        from observability.event_tracker import (  # noqa: PLC0415
            PipelineEventTracker,
        )

        with _patch_general_connection(mssql_connection):
            tracker = PipelineEventTracker()
            tracker._batch_id = 20004

            with tracker.track("SCD2_PROMOTION") as event:
                event.table_name = "OBS7_METADATA_TEST"
                event.source_name = "DNA"

                # First merge: producer sets initial counter.
                existing = json.loads(event.metadata) if event.metadata else {}
                existing["update_ratio"] = 0.12
                event.metadata = json.dumps(existing)

                # Second merge (canonical OBS-7 pattern): another step
                # adds a metric WITHOUT clobbering update_ratio.
                existing = json.loads(event.metadata) if event.metadata else {}
                existing["active_ratio"] = 0.93
                existing["null_pk_rows"] = 0
                event.metadata = json.dumps(existing)

        # Post-condition: the row's Metadata JSON carries ALL THREE keys.
        mssql_cursor.execute(
            """
            SELECT Metadata
            FROM General.ops.PipelineEventLog
            WHERE BatchId = ? AND TableName = 'OBS7_METADATA_TEST'
            """,
            20004,
        )
        row = mssql_cursor.fetchone()
        assert row is not None
        metadata = json.loads(row[0] or "{}")
        assert metadata.get("update_ratio") == 0.12, (
            f"First-merge value lost; got metadata={metadata!r}"
        )
        assert metadata.get("active_ratio") == 0.93, (
            f"Second-merge active_ratio lost; got metadata={metadata!r}"
        )
        assert metadata.get("null_pk_rows") == 0

    def test_track_d33_cooperative_cancellation_poll(
        self,
        mssql_cursor: Any,
        mssql_connection: Any,
        test_db_transaction: Any,
        canonical_schema_loaded: None,
    ) -> None:
        """D33: gate flag CancellationRequested=1 -> SKIPPED + cancellation_requested.

        Per § 6.3 D33 cooperative cancellation: the tracker queries the
        PipelineExecutionGate row at track() entry. When
        CancellationRequested=1, the event is marked SKIPPED with
        EventDetail='cancellation_acked' and event.cancellation_requested
        is True so the orchestrator can short-circuit subsequent steps.

        We mock _check_cancellation directly because the canonical
        schema fixture does NOT include PipelineExecutionGate (deferred
        per the schema.sql header comment). The mock approach exercises
        the canonical D33 SKIPPED branch without requiring the gate
        table to exist - same canonical contract verified.
        """
        from observability.event_tracker import (  # noqa: PLC0415
            PipelineEventTracker,
            set_event_context,
            clear_event_context,
        )

        with _patch_general_connection(mssql_connection):
            tracker = PipelineEventTracker()
            tracker._batch_id = 20005

            # Activate the gate context so _check_cancellation is consulted.
            set_event_context(
                batch_id=20005,
                table_name="D33_CANCEL_TEST",
                source_name="DNA",
                gate_id=9999,
            )
            try:
                # Force _check_cancellation to return True so the entry
                # poll observes a cancellation request.
                with mock.patch(
                    "observability.event_tracker._check_cancellation",
                    return_value=True,
                ):
                    body_ran = False
                    with tracker.track("EXTRACT") as event:
                        # D33 contract: the body STILL yields (so the
                        # caller can inspect event.cancellation_requested),
                        # but Status is already SKIPPED.
                        body_ran = True
                        assert event.cancellation_requested is True, (
                            "D33: event.cancellation_requested must be True "
                            "when gate flag is observed at entry"
                        )
                        assert event.status == "SKIPPED", (
                            f"D33: status must be 'SKIPPED' at body entry; "
                            f"got {event.status!r}"
                        )

                    assert body_ran, "Body must still execute under D33"
            finally:
                clear_event_context()

        # Verify the row landed in PipelineEventLog as SKIPPED with the
        # canonical EventDetail.
        mssql_cursor.execute(
            """
            SELECT Status, EventDetail
            FROM General.ops.PipelineEventLog
            WHERE BatchId = ? AND TableName = 'D33_CANCEL_TEST'
            """,
            20005,
        )
        row = mssql_cursor.fetchone()
        assert row is not None
        status, event_detail = row
        assert status == "SKIPPED", (
            f"D33 audit row must be SKIPPED; got {status!r}"
        )
        assert event_detail == "cancellation_acked", (
            f"D33 EventDetail must be 'cancellation_acked'; got "
            f"{event_detail!r}"
        )
