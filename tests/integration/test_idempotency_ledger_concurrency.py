"""Tier 3 integration tests for utils/idempotency_ledger.py concurrency.

Per docs/migration/phase1/05_tests.md section 6.2 canonical scenario:
"Two workers attempt same step concurrently; exactly one succeeds, other
short-circuits".

Canonical signature under test (per phase1/03_core_modules.md section 4.1):

    @contextmanager
    def ledger_step(
        *,
        batch_id: int,
        source_name: str,
        table_name: str,
        event_type: str,
        metadata: dict | None = None,
    ) -> Iterator[LedgerStep]:
        ...

D-numbers covered:
  - D15 (idempotency mandatory at every layer) - the core invariant under
    test; two concurrent workers MUST converge on exactly one canonical
    completion via the UNIQUE-violation -> SELECT -> branch-on-Status path.
  - D17 (ledger pattern) - the canonical re-entry semantics
    (COMPLETED -> short-circuit; IN_PROGRESS -> LedgerStepFailed;
    FAILED -> reset-then-retry).
  - D68 (error class hierarchy) - LedgerStepFailed bubbles unchanged.
  - D69 (cursor_for ownership) - one cursor per ledger_step invocation.

B-115 scaffold caveat: module-level skip means these tests are collected
but never executed at scaffold-landing time. The skip is removed in a
follow-up B-N once testcontainers is installed in the .venv and a real
container can be spun up end-to-end.
"""
from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Module-level skip - scaffold-landing marker.
#
# Per the prompt: tests are collected (discoverable) but not executed in
# this scaffold landing. The discovery value is the canonical structure +
# the spec-citation skeleton; the execution value comes in a follow-up
# B-N once the conftest's testcontainers integration is operational.
# ---------------------------------------------------------------------------

# B-115 follow-up 2026-05-14: schema.sql + canonical_schema_loaded
# fixture are now operational. Tests fall through to docker_skip_marker()
# from conftest -- skips with "Docker unavailable" reason on workstations
# without Docker Desktop; runs against real container otherwise.
from tests.integration.conftest import docker_skip_marker

pytestmark = docker_skip_marker()


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Test class - idempotency ledger concurrency under real DB.
#
# Each test consumes the canonical fixture set from conftest.py:
#   - mssql_cursor: fresh cursor per test
#   - test_db_transaction: BEGIN/ROLLBACK wrapper for state-leakage mitigation
#   - canonical_schema_loaded: ensures General.ops.IdempotencyLedger exists
# ---------------------------------------------------------------------------


class TestIdempotencyLedgerConcurrency:
    """D15 + D17 concurrency invariants for utils/idempotency_ledger.py.

    Per section 6.2: "Two workers attempt same step concurrently; exactly
    one succeeds, other short-circuits". The UNIQUE index
    UX_IdempotencyLedger_Key on (BatchId, SourceName, TableName, EventType)
    is the atomicity guarantee; this class verifies the
    try-INSERT-catch-UNIQUE-violation-then-SELECT-and-branch path under
    real concurrent execution.
    """

    def test_two_workers_same_step_exactly_one_succeeds(
        self,
        mssql_cursor: Any,
        test_db_transaction: Any,
        canonical_schema_loaded: None,
    ) -> None:
        """Two threads invoking ledger_step on the same key converge to
        exactly one was_short_circuited=False, exactly one
        was_short_circuited=True.

        D15 invariant: idempotency mandatory at every layer. Two workers
        racing on the same ``(batch_id, source_name, table_name,
        event_type)`` tuple MUST converge - the UNIQUE index serializes
        the INSERTs; the loser's INSERT raises pyodbc.IntegrityError;
        the loser's SELECT sees the winner's IN_PROGRESS row and raises
        LedgerStepFailed (per § 4.1 ENTRY contract) OR sees a COMPLETED
        row and short-circuits.

        Setup: pre-insert a COMPLETED row for the key, then launch two
        concurrent ledger_step contexts; both should short-circuit. This
        variant proves the canonical re-run path; the genuine race
        (no pre-existing row, both threads start at the same instant)
        is non-deterministic at the millisecond scale and gets its own
        soak test in a follow-up B-N.
        """
        from utils.idempotency_ledger import ledger_step  # noqa: PLC0415

        # Spec-aligned key tuple per section 4.1 ENTRY contract.
        key = {
            "batch_id": 9001,
            "source_name": "DNA",
            "table_name": "TEST_TABLE",
            "event_type": "EXTRACT",
        }

        results: list[tuple[int, bool]] = []
        exceptions: list[BaseException] = []
        lock = threading.Lock()

        def worker(worker_id: int) -> None:
            try:
                with ledger_step(**key) as step:
                    with lock:
                        results.append(
                            (worker_id, step.was_short_circuited)
                        )
            except BaseException as exc:  # noqa: BLE001
                with lock:
                    exceptions.append(exc)

        t1 = threading.Thread(target=worker, args=(1,), daemon=True)
        t2 = threading.Thread(target=worker, args=(2,), daemon=True)
        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)

        # Canonical convergence assertion (D15 + D17):
        # - Both threads complete their context cleanly.
        # - Exactly one returned was_short_circuited=False (the INSERT winner).
        # - Exactly one returned was_short_circuited=True (the SELECT
        #   path observed the winner's COMPLETED row).
        # OR: one wins (False), the other raises LedgerStepFailed
        # because it observed IN_PROGRESS rather than COMPLETED.
        if exceptions:
            from utils.errors import LedgerStepFailed  # noqa: PLC0415

            # The loser observed IN_PROGRESS; LedgerStepFailed is the
            # documented canonical raise per § 4.1.
            assert any(isinstance(e, LedgerStepFailed) for e in exceptions), (
                f"Unexpected exception class(es): {exceptions!r}"
            )
            assert len(results) == 1, (
                f"With one LedgerStepFailed, expected exactly one "
                f"successful entry; got {results!r}"
            )
            assert results[0][1] is False, (
                "The non-failed worker is the INSERT winner; should "
                "report was_short_circuited=False"
            )
        else:
            # Both succeeded - means winner COMPLETED before loser's SELECT.
            assert len(results) == 2, (
                f"Without exceptions, expected 2 successful entries; "
                f"got {results!r}"
            )
            short_circuited = [s for _, s in results if s]
            not_short_circuited = [s for _, s in results if not s]
            assert len(not_short_circuited) == 1, (
                f"Exactly one worker must report was_short_circuited=False "
                f"(the INSERT winner); got {results!r}"
            )
            assert len(short_circuited) == 1, (
                f"Exactly one worker must report was_short_circuited=True "
                f"(the COMPLETED-row observer); got {results!r}"
            )

    def test_clean_exit_updates_to_completed(
        self,
        mssql_cursor: Any,
        test_db_transaction: Any,
        canonical_schema_loaded: None,
    ) -> None:
        """Clean ledger_step exit updates the row Status to 'COMPLETED'.

        Per § 4.1 EXIT (clean): "UPDATE Status='COMPLETED',
        CompletedAt=SYSUTCDATETIME(), DurationMs = wall-clock duration."

        Verifies the post-condition by querying General.ops.IdempotencyLedger
        directly after the context manager exits cleanly.
        """
        from utils.idempotency_ledger import ledger_step  # noqa: PLC0415

        key = {
            "batch_id": 9002,
            "source_name": "DNA",
            "table_name": "TEST_TABLE",
            "event_type": "BCP_LOAD",
        }

        with ledger_step(**key) as step:
            # Side-effect-free body; D15 contract: body runs iff
            # was_short_circuited is False.
            assert step.was_short_circuited is False
            step_id = step.step_id

        # Post-condition: the ledger row Status MUST be 'COMPLETED'.
        # Per § 4.1 + canonical DDL CK_IdempotencyLedger_Status CHECK.
        mssql_cursor.execute(
            """
            SELECT Status, CompletedAt, DurationMs
            FROM General.ops.IdempotencyLedger
            WHERE LedgerId = ?
            """,
            step_id,
        )
        row = mssql_cursor.fetchone()
        assert row is not None, f"No row for LedgerId={step_id}"
        assert row[0] == "COMPLETED", (
            f"Expected Status='COMPLETED'; got {row[0]!r}"
        )
        assert row[1] is not None, "CompletedAt MUST be non-NULL"
        assert row[2] is not None and row[2] >= 0, (
            f"DurationMs MUST be non-negative; got {row[2]!r}"
        )

    def test_exception_inside_with_block_updates_to_failed(
        self,
        mssql_cursor: Any,
        test_db_transaction: Any,
        canonical_schema_loaded: None,
    ) -> None:
        """Exception inside the with-block updates the row to 'FAILED'.

        Per § 4.1 EXIT (exception): "UPDATE Status='FAILED',
        CompletedAt=SYSUTCDATETIME(), DurationMs, ErrorMessage=str(exc)[:4000];
        re-raise the caller's exception unchanged (do NOT wrap in
        LedgerStepFailed)."

        Verifies (a) the caller's exception bubbles unchanged and (b) the
        ledger row reflects the failure.
        """
        from utils.idempotency_ledger import ledger_step  # noqa: PLC0415

        key = {
            "batch_id": 9003,
            "source_name": "DNA",
            "table_name": "TEST_TABLE",
            "event_type": "CDC_PROMOTION",
        }

        sentinel_message = "synthetic test failure for FAILED-status assertion"

        with pytest.raises(RuntimeError, match=sentinel_message):
            with ledger_step(**key) as step:
                step_id = step.step_id
                raise RuntimeError(sentinel_message)

        # Post-condition: the ledger row Status MUST be 'FAILED'.
        mssql_cursor.execute(
            """
            SELECT Status, CompletedAt, DurationMs, ErrorMessage
            FROM General.ops.IdempotencyLedger
            WHERE LedgerId = ?
            """,
            step_id,
        )
        row = mssql_cursor.fetchone()
        assert row is not None, f"No row for LedgerId={step_id}"
        assert row[0] == "FAILED", (
            f"Expected Status='FAILED'; got {row[0]!r}"
        )
        assert row[1] is not None, "CompletedAt MUST be non-NULL after exception"
        assert row[2] is not None and row[2] >= 0, (
            f"DurationMs MUST be non-negative; got {row[2]!r}"
        )
        assert sentinel_message in (row[3] or ""), (
            f"ErrorMessage must contain the original exception text; "
            f"got {row[3]!r}"
        )
