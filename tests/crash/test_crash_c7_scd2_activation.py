"""Tier 4 crash test C7 - SCD2 activation gap boundary.

Per docs/migration/06_TESTING.md "Tier 4 - Crash Injection" canonical
crash boundary C7:

    "After SCD2 close-old, before activate-new -> Zero active for affected
    PKs (B-14 transient window); next run recovers via E-2."

Canonical contract under test (per scd2/engine.py + B-14 / E-2 invariants):

The SCD2 INSERT-first activation sequence (per E-2 contract):

    1. INSERT new versions with UdmActiveFlag=0 for operation='U'
    2. **<-- C7 crash boundary BEFORE activation -->**
    3. UPDATE old active versions to close (UdmActiveFlag=0,
       UdmEndDateTime=batch_now, UdmSourceEndDate=successor_begin-1day)
    4. **<-- C7 crash boundary AFTER close, BEFORE activation -->**
    5. UPDATE new versions to activate (UdmActiveFlag=1,
       UdmSourceEndDate='2999-12-31') via _activate_new_versions()

A SIGKILL between steps 3 and 5 leaves the affected PKs in the B-14
transient zero-active window: old versions closed (Flag=0), new versions
inserted but un-activated (Flag=0, UdmSourceEndDate IS NULL). Downstream
``WHERE UdmActiveFlag = 1`` queries see ZERO active rows for these PKs
during the transient window.

The recovery contract is:

  - Next SCD2 run invokes ``_activate_new_versions()`` first
  - The two-predicate orphan filter ``UdmActiveFlag = 0 AND
    UdmSourceEndDate IS NULL AND UdmScd2Operation IN ('U','R')`` matches
    exactly the in-flight inserted-but-un-activated rows
  - PK-staging join (R-2 update per SCD2-P1-c) activates them
  - Final state: exactly 1 active row per PK; UdmSourceEndDate='2999-12-31'

D-numbers / invariants covered:
  - D15 (idempotency at every layer) - recovery converges to clean state.
  - B-14 (transient zero-active window documented) - this test PROVES
    the window exists post-SIGKILL.
  - E-2 (3-step INSERT-first SCD2 pattern + activation recovery) - the
    canonical recovery path under test.
  - SCD2-P1-c / SCD2-P1-e (in-flight orphan marker; BOTH predicates
    required) - the recovery filter must match the orphan marker exactly.
  - SCD2-P1-f (PK-staging activation match) - activation no longer uses
    scalar UdmSourceBeginDate = @dt predicate.

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
# Canonical crash-injection point names.
# ---------------------------------------------------------------------------

CRASH_INJECT_BEFORE_ACTIVATE = "scd2_before_activate_new_versions"


class TestCrashC7Scd2Activation:
    """C7 crash boundary - SCD2 between close-old and activate-new.

    Per 06_TESTING.md Tier 4 C7 + B-14 transient window contract + E-2
    INSERT-first activation pattern: a SIGKILL after close-old but
    before activate-new leaves PKs with zero active rows (Flag=1) and
    instead inserted-but-un-activated rows (Flag=0, UdmSourceEndDate
    IS NULL, Op IN ('U','R')). Recovery via the next SCD2 run's
    ``_activate_new_versions()`` matches the two-predicate orphan
    filter and activates them.
    """

    def test_crash_between_close_and_activate_leaves_zero_active(
        self,
        mssql_container_with_seed: Any,
        crash_subprocess_factory: Callable[..., subprocess.Popen],
        tmp_path: Path,
    ) -> None:
        """SIGKILL between close-old + activate-new leaves zero active rows
        per affected PK (B-14 transient window confirmed).

        Setup:
          1. Pre-populate Bronze with N PKs each having 1 active row
             (Flag=1, UdmSourceEndDate='2999-12-31').
          2. Spawn SCD2 promotion subprocess with crash injection at
             the canonical boundary (after close-old, before activate-new).
          3. Subprocess writes the close UPDATE + the INSERT-with-Flag=0,
             then enters the crash-injection sleep loop.
          4. Parent SIGKILLs.

        Verification:
          - Subprocess exit code == -SIGKILL.
          - Bronze has ZERO rows with ``UdmActiveFlag = 1`` for affected PKs.
          - Bronze has N rows with the orphan marker
            (Flag=0 AND UdmSourceEndDate IS NULL AND Op IN ('U','R')).
          - Bronze has N rows with the close-old marker
            (Flag=0 AND UdmEndDateTime IS NOT NULL).
        """
        import pyodbc  # noqa: PLC0415

        # Pre-populate Bronze with 5 active PKs via direct INSERT.
        container = mssql_container_with_seed
        host = container.get_container_host_ip()
        port = container.get_exposed_port(1433)
        conn_str = (
            f"DRIVER={{ODBC Driver 18 for SQL Server}};"
            f"SERVER={host},{port};UID=sa;PWD=TestPassword!2026;"
            f"TrustServerCertificate=yes;Encrypt=yes;"
        )
        n_pks = 5
        _prepopulate_bronze_active_rows(conn_str, n_pks=n_pks)

        # Spawn SCD2 promotion with crash injection.
        proc = crash_subprocess_factory(
            target_module="scd2.engine",
            target_callable="_crash_test_harness_c7",
            env={
                "CRASH_INJECT_POINT": CRASH_INJECT_BEFORE_ACTIVATE,
                "CRASH_CONN_STR": conn_str,
                "CRASH_N_PKS": str(n_pks),
                "CRASH_BATCH_ID": "9200",
            },
        )

        barrier_seen = _wait_for_barrier_token(
            proc, token="CLOSE_OLD_COMPLETE", timeout_s=60
        )
        assert barrier_seen, (
            "Crash harness did not emit CLOSE_OLD_COMPLETE; the crash "
            "injection hook may not be wired in scd2/engine.py "
            "(_crash_test_harness_c7). Tracked in scaffold follow-up B-N."
        )

        os.kill(proc.pid, signal.SIGKILL)
        exit_code = proc.wait(timeout=10)
        assert exit_code < 0, (
            f"Subprocess should have died from SIGKILL; got {exit_code!r}"
        )

        # Verify the transient B-14 zero-active window.
        conn = pyodbc.connect(conn_str)
        try:
            cursor = conn.cursor()

            # Active rows for affected PKs: must be ZERO.
            cursor.execute(
                """
                SELECT COUNT(*) FROM UDM_Bronze.DNA.C7_TEST_scd2_python
                WHERE UdmActiveFlag = 1
                """
            )
            active_count = cursor.fetchone()[0]
            assert active_count == 0, (
                f"B-14 transient window: zero active rows expected "
                f"post-crash; got {active_count}"
            )

            # Orphan markers: Flag=0 AND UdmSourceEndDate IS NULL AND
            # Op IN ('U','R'). Per SCD2-P1-e the BOTH-predicate hardened form.
            cursor.execute(
                """
                SELECT COUNT(*) FROM UDM_Bronze.DNA.C7_TEST_scd2_python
                WHERE UdmActiveFlag = 0
                  AND UdmSourceEndDate IS NULL
                  AND UdmEndDateTime IS NULL
                  AND UdmScd2Operation IN ('U','R')
                """
            )
            orphan_count = cursor.fetchone()[0]
            assert orphan_count == n_pks, (
                f"Expected {n_pks} orphan markers (in-flight inserts); "
                f"got {orphan_count}"
            )

            # Close-old markers: Flag=0, UdmEndDateTime IS NOT NULL.
            cursor.execute(
                """
                SELECT COUNT(*) FROM UDM_Bronze.DNA.C7_TEST_scd2_python
                WHERE UdmActiveFlag = 0 AND UdmEndDateTime IS NOT NULL
                """
            )
            closed_count = cursor.fetchone()[0]
            assert closed_count == n_pks, (
                f"Expected {n_pks} closed-old rows; got {closed_count}"
            )
        finally:
            conn.close()

    def test_recovery_via_e2_runs_activate_new_versions(
        self,
        mssql_container_with_seed: Any,
        crash_subprocess_factory: Callable[..., subprocess.Popen],
        crash_recovery_run: Callable[..., subprocess.Popen],
    ) -> None:
        """Recovery run invokes _activate_new_versions; matches orphans by
        PK-staging join + flips Flag=0 -> Flag=1.

        Per E-2 + SCD2-P1-c / SCD2-P1-f: recovery uses the two-predicate
        orphan filter to find in-flight inserts and activates them via
        PK-staging join. Post-recovery, Bronze has exactly 1 active row
        per affected PK with UdmSourceEndDate='2999-12-31' (active sentinel).

        Setup:
          1. Reproduce the crash from test 1 above.
          2. Invoke the SCD2 recovery path (re-run SCD2 promotion with
             crash injection DISABLED).

        Verification:
          - Recovery subprocess exits 0.
          - Bronze has exactly N active rows (Flag=1).
          - Each active row has UdmSourceEndDate='2999-12-31'.
          - The orphan marker count is now 0.
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
        n_pks = 5
        _prepopulate_bronze_active_rows(conn_str, n_pks=n_pks)

        # Phase 1: reproduce the crash.
        proc = crash_subprocess_factory(
            target_module="scd2.engine",
            target_callable="_crash_test_harness_c7",
            env={
                "CRASH_INJECT_POINT": CRASH_INJECT_BEFORE_ACTIVATE,
                "CRASH_CONN_STR": conn_str,
                "CRASH_N_PKS": str(n_pks),
                "CRASH_BATCH_ID": "9201",
            },
        )
        _wait_for_barrier_token(proc, token="CLOSE_OLD_COMPLETE", timeout_s=60)
        os.kill(proc.pid, signal.SIGKILL)
        proc.wait(timeout=10)

        # Phase 2: invoke recovery (re-run SCD2 with NO crash injection).
        recovery = crash_recovery_run(
            target_module="scd2.engine",
            target_callable="_crash_test_harness_c7",
            env={
                "CRASH_CONN_STR": conn_str,
                "CRASH_N_PKS": str(n_pks),
                "CRASH_BATCH_ID": "9201",
                # CRASH_INJECT_POINT intentionally omitted.
            },
        )
        recovery_exit = recovery.wait(timeout=120)
        assert recovery_exit == 0, (
            f"Recovery should exit 0; got {recovery_exit}; "
            f"stderr={recovery.stderr.read().decode()!r}"
        )

        # Phase 3: verify clean post-recovery state.
        conn = pyodbc.connect(conn_str)
        try:
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT COUNT(*) FROM UDM_Bronze.DNA.C7_TEST_scd2_python
                WHERE UdmActiveFlag = 1
                """
            )
            active_count = cursor.fetchone()[0]
            assert active_count == n_pks, (
                f"Post-recovery: exactly {n_pks} active rows expected; "
                f"got {active_count}"
            )

            # Active sentinel verification per SCD2-P1-c.
            cursor.execute(
                """
                SELECT COUNT(*) FROM UDM_Bronze.DNA.C7_TEST_scd2_python
                WHERE UdmActiveFlag = 1
                  AND UdmSourceEndDate = '2999-12-31'
                """
            )
            sentinel_count = cursor.fetchone()[0]
            assert sentinel_count == n_pks, (
                f"All active rows must carry the '2999-12-31' sentinel "
                f"per SCD2-P1-c; got {sentinel_count}/{n_pks}"
            )

            # Orphan markers cleared.
            cursor.execute(
                """
                SELECT COUNT(*) FROM UDM_Bronze.DNA.C7_TEST_scd2_python
                WHERE UdmActiveFlag = 0
                  AND UdmSourceEndDate IS NULL
                  AND UdmEndDateTime IS NULL
                  AND UdmScd2Operation IN ('U','R')
                """
            )
            orphan_count = cursor.fetchone()[0]
            assert orphan_count == 0, (
                f"Post-recovery: orphan markers must be cleared; "
                f"got {orphan_count}"
            )
        finally:
            conn.close()

    def test_in_flight_orphan_marker_cleaned_up(
        self,
        mssql_container_with_seed: Any,
        crash_subprocess_factory: Callable[..., subprocess.Popen],
        crash_recovery_run: Callable[..., subprocess.Popen],
    ) -> None:
        """_cleanup_orphaned_inactive_rows clears any leftover B-4 markers.

        Per the B-4 contract + SCD2-P1-e BOTH-predicate hardening:
        ``_cleanup_orphaned_inactive_rows`` runs at the START of every
        SCD2 invocation; it DELETEs rows matching the orphan marker
        predicate that were left in a half-committed state across
        multiple crash cycles.

        This test simulates a worst-case: crash + partial recovery +
        another crash. The B-4 cleanup must still reach a consistent
        end state on the third (clean) run.

        Setup:
          1. Crash (test 1 scenario): leaves orphan markers.
          2. SECOND crash before recovery completes - still has orphans.
          3. Final clean recovery run.

        Verification:
          - Final state has exactly N active rows (Flag=1).
          - Zero orphan markers remain.
          - PipelineLog has a log entry for ``_cleanup_orphaned_inactive_rows``
            confirming the cleanup ran.
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
        n_pks = 5
        _prepopulate_bronze_active_rows(conn_str, n_pks=n_pks)

        # Phase 1: first crash.
        proc1 = crash_subprocess_factory(
            target_module="scd2.engine",
            target_callable="_crash_test_harness_c7",
            env={
                "CRASH_INJECT_POINT": CRASH_INJECT_BEFORE_ACTIVATE,
                "CRASH_CONN_STR": conn_str,
                "CRASH_N_PKS": str(n_pks),
                "CRASH_BATCH_ID": "9202",
            },
        )
        _wait_for_barrier_token(proc1, token="CLOSE_OLD_COMPLETE", timeout_s=60)
        os.kill(proc1.pid, signal.SIGKILL)
        proc1.wait(timeout=10)

        # Phase 2: second crash (recovery aborted partway).
        proc2 = crash_subprocess_factory(
            target_module="scd2.engine",
            target_callable="_crash_test_harness_c7",
            env={
                "CRASH_INJECT_POINT": CRASH_INJECT_BEFORE_ACTIVATE,
                "CRASH_CONN_STR": conn_str,
                "CRASH_N_PKS": str(n_pks),
                "CRASH_BATCH_ID": "9202",
            },
        )
        _wait_for_barrier_token(proc2, token="CLOSE_OLD_COMPLETE", timeout_s=60)
        os.kill(proc2.pid, signal.SIGKILL)
        proc2.wait(timeout=10)

        # Phase 3: final clean recovery.
        recovery = crash_recovery_run(
            target_module="scd2.engine",
            target_callable="_crash_test_harness_c7",
            env={
                "CRASH_CONN_STR": conn_str,
                "CRASH_N_PKS": str(n_pks),
                "CRASH_BATCH_ID": "9202",
            },
        )
        recovery_exit = recovery.wait(timeout=120)
        assert recovery_exit == 0, (
            f"Final recovery should exit 0; got {recovery_exit}"
        )

        # Phase 4: verify clean state + cleanup log entry.
        conn = pyodbc.connect(conn_str)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(*) FROM UDM_Bronze.DNA.C7_TEST_scd2_python
                WHERE UdmActiveFlag = 0
                  AND UdmSourceEndDate IS NULL
                  AND UdmEndDateTime IS NULL
                  AND UdmScd2Operation IN ('U','R')
                """
            )
            assert cursor.fetchone()[0] == 0, (
                "B-4 cleanup must clear all orphan markers"
            )

            # PipelineLog cleanup-mention check (advisory).
            cursor.execute(
                """
                SELECT COUNT(*) FROM General.ops.PipelineLog
                WHERE FunctionName = '_cleanup_orphaned_inactive_rows'
                  AND CreatedAt >= DATEADD(MINUTE, -5, SYSUTCDATETIME())
                """
            )
            cleanup_log_count = cursor.fetchone()[0]
            assert cleanup_log_count >= 1, (
                "Expected at least one cleanup log entry in last 5 min; "
                f"got {cleanup_log_count}"
            )
        finally:
            conn.close()


def _prepopulate_bronze_active_rows(conn_str: str, *, n_pks: int) -> None:
    """Seed the Bronze test table with ``n_pks`` active rows pre-SCD2-run.

    Helper for the C7 test class; creates the test Bronze table on demand
    (idempotent CREATE TABLE IF NOT EXISTS) and INSERTs N active rows
    with UdmActiveFlag=1, UdmSourceEndDate='2999-12-31' sentinel.

    Args:
        conn_str: pyodbc connection string to the seeded container.
        n_pks: Number of distinct PKs to seed.
    """
    import pyodbc  # noqa: PLC0415

    conn = pyodbc.connect(conn_str, autocommit=True)
    try:
        cursor = conn.cursor()

        # Ensure the test Bronze table exists.
        cursor.execute(
            """
            IF NOT EXISTS (
                SELECT 1 FROM UDM_Bronze.INFORMATION_SCHEMA.TABLES
                WHERE TABLE_SCHEMA = 'DNA' AND TABLE_NAME = 'C7_TEST_scd2_python'
            )
            BEGIN
                EXEC('CREATE SCHEMA DNA')
            END
            """
        )
        cursor.execute(
            """
            IF OBJECT_ID('UDM_Bronze.DNA.C7_TEST_scd2_python', 'U') IS NULL
            BEGIN
                CREATE TABLE UDM_Bronze.DNA.C7_TEST_scd2_python (
                    _scd2_key BIGINT IDENTITY(1,1) PRIMARY KEY,
                    AccountId BIGINT NOT NULL,
                    Balance DECIMAL(18,2) NULL,
                    UdmHash VARCHAR(64) NOT NULL,
                    UdmEffectiveDateTime DATETIME2(3) NOT NULL,
                    UdmEndDateTime DATETIME2(3) NULL,
                    UdmActiveFlag TINYINT NOT NULL,
                    UdmScd2Operation CHAR(1) NOT NULL,
                    UdmSourceBeginDate DATETIME2(3) NULL,
                    UdmSourceEndDate DATETIME2(3) NULL
                )
            END
            """
        )

        # Insert N active rows.
        for i in range(n_pks):
            cursor.execute(
                """
                INSERT INTO UDM_Bronze.DNA.C7_TEST_scd2_python (
                    AccountId, Balance, UdmHash,
                    UdmEffectiveDateTime, UdmEndDateTime, UdmActiveFlag,
                    UdmScd2Operation, UdmSourceBeginDate, UdmSourceEndDate
                ) VALUES (?, ?, ?, SYSUTCDATETIME(), NULL, 1, 'I',
                          SYSUTCDATETIME(), '2999-12-31')
                """,
                10000 + i,
                1000.00 + i,
                f"{i:064x}",
            )
    finally:
        conn.close()


def _wait_for_barrier_token(
    proc: subprocess.Popen, *, token: str, timeout_s: float
) -> bool:
    """Block until subprocess emits ``token`` on stdout or times out.

    Duplicated from test_crash_c2_inflight_parquet.py for module
    self-containment; both files use the same barrier pattern.
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
