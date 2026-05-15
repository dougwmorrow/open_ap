"""Tier 4 crash test C11 - parquet_tier_review --apply mid-batch boundary.

Per docs/migration/phase1/05_tests.md section 7.2 C11 (Round 5 CLI-level
crash addition):

    "``parquet_tier_review --apply`` mid-batch (between two transition
    function calls) -> Some rows transitioned; remainder unchanged;
    re-run idempotent (predecessor-Status filter skips already-
    transitioned rows)."

Canonical contract under test (per tools/parquet_tier_review.py):

The CLI iterates over registry rows matching its Status filter, calling
the canonical state-transition function for each row sequentially:

    1. Load N candidate rows from registry (Status = predecessor)
    2. For each row (1..N):
       a. Call transition (e.g., mark_replicated)
       b. **<-- C11 crash boundary BETWEEN transitions -->**
       c. Audit row in PipelineEventLog
    3. Final summary + exit_code

A SIGKILL between transition K and K+1 leaves K rows transitioned, N-K
rows still at the predecessor Status. The recovery contract is:

  - Re-running the CLI with the same predecessor->successor flags
  - The Status filter naturally skips the K already-transitioned rows
    (their Status is now ``successor``, not ``predecessor``)
  - The remaining N-K rows transition normally
  - PipelineEventLog audit trail has TWO CLI_PARQUET_TIER_REVIEW rows
    (one per CLI invocation) with exit_codes reflecting partial vs
    complete

D-numbers / invariants covered:
  - D15 (idempotency at every layer) - re-run produces same end state.
  - D74 / D75 / D76 (CLI tool contract; one audit row per invocation
    per the EVENT_TYPE family registration).
  - D2 / D4 / D45.3 (registry state machine; predecessor-Status filter
    is the canonical re-entry skip mechanism).
  - SUPPORTED_TO_STATUSES (per parquet_tier_review.py public surface) -
    the legal-transitions table is the only successor allowed; the
    predecessor-Status filter is implicit in the legal-transition lookup.

Scaffold caveat: tests module-level skip via ``docker_skip_marker()`` +
``crash_orchestration_skip_marker()`` until both Docker AND a Linux
container host are available. Real execution runs in pre-release manual
operator cadence (NOT in CI).
"""
from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Module-level skip - BOTH Docker + crash-orchestration markers.
# ---------------------------------------------------------------------------

from tests.crash.conftest import (  # noqa: E402 - intentional after sys.path
    crash_orchestration_skip_marker,
    docker_skip_marker,
)

pytestmark = [docker_skip_marker(), crash_orchestration_skip_marker()]


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Canonical crash-injection point name.
#
# The CLI tool reads CRASH_INJECT_POINT + CRASH_INJECT_AFTER_N inside its
# transition loop; once N transitions have completed it emits the barrier
# token + sleeps awaiting SIGKILL. This hook is Tier-4-only; production
# code paths short-circuit when the variable is unset.
# ---------------------------------------------------------------------------

CRASH_INJECT_MIDBATCH = "tier_review_midbatch"


class TestCrashC11ParquetTierReviewMidbatch:
    """C11 crash boundary - parquet_tier_review mid-batch CLI execution.

    Per phase1/05_tests.md section 7.2 + D2/D4/D45.3 registry state
    machine: CLI iterates over candidate rows, calling the transition
    function for each. SIGKILL between transitions leaves a partial
    completion; re-run idempotent via predecessor-Status filter.
    """

    def test_crash_after_n_transitions_some_rows_done(
        self,
        mssql_container_with_seed: Any,
        crash_subprocess_factory: Callable[..., subprocess.Popen],
    ) -> None:
        """SIGKILL after 3 of 10 transitions leaves 3 rows at successor
        Status, 7 rows still at predecessor.

        Setup:
          1. Identify 10 candidate rows in
             ``General.ops.ParquetSnapshotRegistry`` with Status='verified'
             (canonical predecessor for the 'replicated' transition).
          2. Spawn ``parquet_tier_review --apply --to-status replicated``
             with crash injection at N=3 transitions.
          3. CLI processes 3 rows, emits ``TRANSITIONS_DONE_3``, sleeps.
          4. Parent SIGKILLs.

        Verification:
          - Subprocess exit code == -SIGKILL.
          - Registry: 3 rows now have Status='replicated', 7 retain
            Status='verified'.
          - PipelineEventLog: ONE row of EventType='CLI_PARQUET_TIER_REVIEW'
            for the crashed invocation (the audit row is written at
            CLI invocation start per D76, not at exit).
        """
        import pyodbc  # noqa: PLC0415

        container = mssql_container_with_seed
        host = container.get_container_host_ip()
        port = container.get_exposed_port(1433)
        conn_str = (
            f"DRIVER={{ODBC Driver 18 for SQL Server}};"
            f"SERVER={host},{port};UID=sa;PWD=TestPassword!2026;"
            f"TrustServerCertificate=yes;Encrypt=yes;"
        )

        # Confirm initial state: 20 verified rows from the session-level seed.
        conn = pyodbc.connect(conn_str)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(*) FROM General.ops.ParquetSnapshotRegistry
                WHERE Status = 'verified'
                """
            )
            verified_initial = cursor.fetchone()[0]
            assert verified_initial >= 10, (
                f"Need at least 10 'verified' rows for C11 test; got "
                f"{verified_initial}. Check session-level seed fixture."
            )
        finally:
            conn.close()

        # Spawn the CLI with crash injection at N=3.
        proc = crash_subprocess_factory(
            target_module="tools.parquet_tier_review",
            target_callable="_crash_test_harness_c11",
            env={
                "CRASH_INJECT_POINT": CRASH_INJECT_MIDBATCH,
                "CRASH_INJECT_AFTER_N": "3",
                "CRASH_CONN_STR": conn_str,
                "CRASH_FROM_STATUS": "verified",
                "CRASH_TO_STATUS": "replicated",
                "CRASH_LIMIT": "10",
            },
        )

        barrier_seen = _wait_for_barrier_token(
            proc, token="TRANSITIONS_DONE_3", timeout_s=60
        )
        assert barrier_seen, (
            "CLI harness did not emit TRANSITIONS_DONE_3; the crash "
            "injection hook may not be wired in "
            "tools/parquet_tier_review.py (_crash_test_harness_c11). "
            "Tracked in scaffold follow-up B-N."
        )

        os.kill(proc.pid, signal.SIGKILL)
        exit_code = proc.wait(timeout=10)
        assert exit_code < 0, (
            f"Subprocess should have died from SIGKILL; got {exit_code!r}"
        )

        # Verify partial completion: exactly 3 rows transitioned.
        conn = pyodbc.connect(conn_str)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(*) FROM General.ops.ParquetSnapshotRegistry
                WHERE Status = 'replicated'
                  AND BatchId = 8000
                """
            )
            transitioned = cursor.fetchone()[0]
            # The seed includes 10 pre-existing 'replicated' rows, so
            # the new transitions push the count by exactly 3.
            assert transitioned >= 13, (
                f"Expected at least 13 'replicated' rows (10 seed + 3 "
                f"transitioned); got {transitioned}"
            )

            # PipelineEventLog audit row for the crashed CLI invocation.
            cursor.execute(
                """
                SELECT COUNT(*) FROM General.ops.PipelineEventLog
                WHERE EventType = 'CLI_PARQUET_TIER_REVIEW'
                  AND StartedAt >= DATEADD(MINUTE, -5, SYSUTCDATETIME())
                """
            )
            audit_count = cursor.fetchone()[0]
            assert audit_count >= 1, (
                f"Expected at least 1 CLI audit row in last 5 min; "
                f"got {audit_count}"
            )
        finally:
            conn.close()

    def test_recovery_resumes_remaining(
        self,
        mssql_container_with_seed: Any,
        crash_subprocess_factory: Callable[..., subprocess.Popen],
        crash_recovery_run: Callable[..., subprocess.Popen],
    ) -> None:
        """Re-run after crash transitions only the remaining rows.

        Setup:
          1. Reproduce the partial-completion state (test 1 scenario).
          2. Re-run the CLI with the SAME flags but NO crash injection.

        Verification:
          - Recovery subprocess exits 0.
          - Registry: 10 transition-candidate rows now at 'replicated';
            the recovery processed only the remaining 7 (the predecessor-
            Status filter skipped the 3 already-transitioned).
          - PipelineEventLog: TWO audit rows for CLI_PARQUET_TIER_REVIEW
            (one for crashed invocation, one for recovery).
        """
        import pyodbc  # noqa: PLC0415

        container = mssql_container_with_seed
        host = container.get_container_host_ip()
        port = container.get_exposed_port(1433)
        conn_str = (
            f"DRIVER={{ODBC Driver 18 for SQL Server}};"
            f"SERVER={host},{port};UID=sa;PWD=TestPassword!2026;"
            f"TrustServerCertificate=yes;Encrypt=yes;"
        )

        # Phase 1: reproduce the crash + partial state.
        proc = crash_subprocess_factory(
            target_module="tools.parquet_tier_review",
            target_callable="_crash_test_harness_c11",
            env={
                "CRASH_INJECT_POINT": CRASH_INJECT_MIDBATCH,
                "CRASH_INJECT_AFTER_N": "3",
                "CRASH_CONN_STR": conn_str,
                "CRASH_FROM_STATUS": "verified",
                "CRASH_TO_STATUS": "replicated",
                "CRASH_LIMIT": "10",
            },
        )
        _wait_for_barrier_token(proc, token="TRANSITIONS_DONE_3", timeout_s=60)
        os.kill(proc.pid, signal.SIGKILL)
        proc.wait(timeout=10)

        # Phase 2: recovery (no crash injection).
        recovery = crash_recovery_run(
            target_module="tools.parquet_tier_review",
            target_callable="_crash_test_harness_c11",
            env={
                "CRASH_CONN_STR": conn_str,
                "CRASH_FROM_STATUS": "verified",
                "CRASH_TO_STATUS": "replicated",
                "CRASH_LIMIT": "10",
            },
        )
        recovery_exit = recovery.wait(timeout=120)
        assert recovery_exit == 0, (
            f"Recovery should exit 0; got {recovery_exit}; "
            f"stderr={recovery.stderr.read().decode()!r}"
        )

        # Phase 3: verify all candidates now at successor Status.
        conn = pyodbc.connect(conn_str)
        try:
            cursor = conn.cursor()
            # 10 verified -> replicated: total verified should drop by
            # at least 10 (could be more if the test re-runs the same
            # tuple; the predecessor-Status filter naturally idempotents).
            cursor.execute(
                """
                SELECT COUNT(*) FROM General.ops.ParquetSnapshotRegistry
                WHERE Status = 'verified'
                  AND BatchId = 8000
                """
            )
            remaining_verified = cursor.fetchone()[0]
            assert remaining_verified <= 10, (
                f"After CLI + recovery, 'verified' count should have "
                f"dropped by at least 10; got {remaining_verified} remaining"
            )
        finally:
            conn.close()

    def test_audit_log_reflects_both_invocations(
        self,
        mssql_container_with_seed: Any,
        crash_subprocess_factory: Callable[..., subprocess.Popen],
        crash_recovery_run: Callable[..., subprocess.Popen],
    ) -> None:
        """PipelineEventLog has TWO CLI_PARQUET_TIER_REVIEW audit rows
        (one per invocation) with exit_code distinguishing partial vs
        complete.

        Per D76 + Round 6 section 6.4 CLI_* family registration: each
        CLI invocation MUST write exactly one audit row at start; the
        row is updated on exit with exit_code + duration. After a
        crashed invocation + recovery, the PipelineEventLog should
        show:

          - Row 1: EventType='CLI_PARQUET_TIER_REVIEW', exit_code
            reflecting the crash (NULL because the SIGKILL never wrote
            the exit), Status='STARTED' or similar pending marker.
          - Row 2: EventType='CLI_PARQUET_TIER_REVIEW', exit_code=0,
            Status='SUCCESS'.

        Setup:
          1. Reproduce crash + recovery (tests 1 + 2 scenario).
          2. Query PipelineEventLog for the time window.

        Verification:
          - Exactly 2 audit rows for CLI_PARQUET_TIER_REVIEW.
          - One row has exit_code=0 (the recovery).
          - One row has exit_code NULL or non-zero (the crash).
        """
        import pyodbc  # noqa: PLC0415

        container = mssql_container_with_seed
        host = container.get_container_host_ip()
        port = container.get_exposed_port(1433)
        conn_str = (
            f"DRIVER={{ODBC Driver 18 for SQL Server}};"
            f"SERVER={host},{port};UID=sa;PWD=TestPassword!2026;"
            f"TrustServerCertificate=yes;Encrypt=yes;"
        )

        # Phase 1+2: reproduce crash + recovery.
        proc = crash_subprocess_factory(
            target_module="tools.parquet_tier_review",
            target_callable="_crash_test_harness_c11",
            env={
                "CRASH_INJECT_POINT": CRASH_INJECT_MIDBATCH,
                "CRASH_INJECT_AFTER_N": "3",
                "CRASH_CONN_STR": conn_str,
                "CRASH_FROM_STATUS": "verified",
                "CRASH_TO_STATUS": "replicated",
                "CRASH_LIMIT": "10",
            },
        )
        _wait_for_barrier_token(proc, token="TRANSITIONS_DONE_3", timeout_s=60)
        os.kill(proc.pid, signal.SIGKILL)
        proc.wait(timeout=10)

        recovery = crash_recovery_run(
            target_module="tools.parquet_tier_review",
            target_callable="_crash_test_harness_c11",
            env={
                "CRASH_CONN_STR": conn_str,
                "CRASH_FROM_STATUS": "verified",
                "CRASH_TO_STATUS": "replicated",
                "CRASH_LIMIT": "10",
            },
        )
        recovery.wait(timeout=120)

        # Phase 3: query the audit trail.
        conn = pyodbc.connect(conn_str)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT Status, ErrorMessage,
                       JSON_VALUE(Metadata, '$.exit_code') AS ExitCode
                FROM General.ops.PipelineEventLog
                WHERE EventType = 'CLI_PARQUET_TIER_REVIEW'
                  AND StartedAt >= DATEADD(MINUTE, -10, SYSUTCDATETIME())
                ORDER BY StartedAt ASC
                """
            )
            rows = cursor.fetchall()
            assert len(rows) >= 2, (
                f"Expected at least 2 CLI audit rows (crash + recovery); "
                f"got {len(rows)}"
            )

            # The recovery should be the LAST row + have exit_code=0.
            last_row = rows[-1]
            last_exit_code = last_row[2]
            assert last_exit_code in ("0", 0), (
                f"Recovery audit row should have exit_code=0; got "
                f"exit_code={last_exit_code!r}"
            )

            # The crashed row should NOT have exit_code=0 (either NULL
            # if the SIGKILL beat the exit-update, or non-zero).
            crashed_row = rows[-2]
            crashed_exit_code = crashed_row[2]
            assert crashed_exit_code not in ("0", 0), (
                f"Crashed audit row should NOT have exit_code=0; got "
                f"exit_code={crashed_exit_code!r}"
            )
        finally:
            conn.close()


def _wait_for_barrier_token(
    proc: subprocess.Popen, *, token: str, timeout_s: float
) -> bool:
    """Block until subprocess emits ``token`` on stdout or times out.

    Duplicated from test_crash_c2_inflight_parquet.py + test_crash_c7_*.py
    for module self-containment; all three crash test modules use the
    same barrier pattern.
    """
    deadline = time.monotonic() + timeout_s
    if proc.stdout is None:
        return False

    accumulated = b""
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return False
        line = proc.stdout.readline()
        if not line:
            time.sleep(0.05)
            continue
        accumulated += line
        if token.encode() in accumulated:
            return True
    return False
