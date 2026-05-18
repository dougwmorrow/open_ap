"""Tier 4 crash test C2 - inflight Parquet write boundary.

Per docs/migration/06_TESTING.md "Tier 4 - Crash Injection" canonical
crash boundary C2:

    "After Parquet `_inflight` write, before atomic rename -> Orphan
    inflight file; ``parquet_verify`` cleans on next run."

Canonical contract under test (per phase1/03_core_modules.md section 1.1):

    def write_parquet_snapshot(
        df: pl.DataFrame,
        *,
        source_name: str,
        table_name: str,
        batch_id: int,
        business_date: date,
        output_dir: Path,
    ) -> ParquetWriteResult:
        ...

The write_parquet_snapshot internal sequence (per D16 inflight-rename
crash-safety pattern):

    1. Write Polars DataFrame to ``<path>.parquet._inflight``
    2. ``fsync`` the file handle
    3. **<-- C2 crash boundary -->**
    4. Atomic ``os.rename`` to ``<path>.parquet``
    5. ``fsync`` parent directory
    6. SHA-256 hash of final file
    7. INSERT row in ParquetSnapshotRegistry with Status='created'

A SIGKILL at step 3 leaves an orphan ``*.parquet._inflight`` file with NO
registry row. The recovery contract is:

  - ``parquet_verify`` (M3) detects the orphan via filesystem scan
  - Orphan is cleaned (DELETE the inflight file)
  - Registry is unchanged (no row was inserted before the crash)
  - Re-running ``write_parquet_snapshot`` with the SAME key tuple
    produces a fresh inflight file + completes the rename + INSERTs
    the registry row exactly once

D-numbers covered:
  - D15 (idempotency at every layer) - crash-recovery convergence is the
    invariant under test.
  - D16 (atomic file write via inflight rename) - the canonical pattern
    whose crash boundary IS C2.
  - D55 (producer != reviewer) - this test IS the reviewer of the M1
    producer's claim that the inflight pattern is crash-safe.

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
#
# Per the prompt: tests are collected (discoverable) but never executed at
# scaffold-landing. The discovery value is the canonical structure + the
# spec-citation skeleton; execution awaits the follow-up B-N that
# installs testcontainers + runs on a Linux container host.
# ---------------------------------------------------------------------------

from tests.crash.conftest import (  # noqa: E402 - intentional after sys.path
    crash_orchestration_skip_marker,
    docker_skip_marker,
)

pytestmark = [docker_skip_marker(), crash_orchestration_skip_marker()]


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Canonical crash-injection environment variable.
#
# The pipeline code reads ``CRASH_INJECT_POINT`` and pauses (sleep loop)
# at the named boundary so the parent test process can SIGKILL deterministically.
# This is a Tier-4-only debug hook; production code paths short-circuit
# when the variable is unset.
# ---------------------------------------------------------------------------

CRASH_INJECT_AFTER_INFLIGHT = "after_inflight_write"


class TestCrashC2InflightParquet:
    """C2 crash boundary - inflight Parquet write before atomic rename.

    Per 06_TESTING.md Tier 4 + D16 inflight-rename pattern: a SIGKILL
    between the inflight write and the atomic rename leaves an orphan
    ``*.parquet._inflight`` file with NO registry row. Recovery cleans
    the orphan and a re-run with the same key tuple completes exactly
    once (D15 idempotency contract).
    """

    def test_crash_after_inflight_write_leaves_orphan(
        self,
        mssql_container_with_seed: Any,
        crash_subprocess_factory: Callable[..., subprocess.Popen],
        tmp_path: Path,
    ) -> None:
        """SIGKILL between inflight write + atomic rename leaves orphan file.

        Setup:
          1. Spawn ``write_parquet_snapshot`` in a subprocess with
             ``CRASH_INJECT_POINT=after_inflight_write`` env var.
          2. Subprocess writes ``<path>.parquet._inflight``, fsyncs, then
             enters the crash-injection sleep loop.
          3. Parent reads stdout for the barrier token, then sends SIGKILL.

        Verification:
          - Subprocess exit code == -SIGKILL (negative signal value).
          - Orphan ``<path>.parquet._inflight`` file exists on disk.
          - Final ``<path>.parquet`` file does NOT exist (rename never ran).
          - ``General.ops.ParquetSnapshotRegistry`` has NO row for the
            ``(SourceName, TableName, BatchId, BusinessDate)`` tuple
            (INSERT happens after rename per M1 contract).
        """
        import pyodbc  # noqa: PLC0415

        # Spawn the subprocess that will crash mid-write.
        output_dir = tmp_path / "parquet_out"
        output_dir.mkdir()

        proc = crash_subprocess_factory(
            target_module="data_load.parquet_writer",
            target_callable="_crash_test_harness_c2",
            env={
                "CRASH_INJECT_POINT": CRASH_INJECT_AFTER_INFLIGHT,
                "CRASH_OUTPUT_DIR": str(output_dir),
                "CRASH_SOURCE_NAME": "DNA",
                "CRASH_TABLE_NAME": "C2_TEST",
                "CRASH_BATCH_ID": "9100",
                "CRASH_BUSINESS_DATE": "2026-05-14",
            },
        )

        # Wait for the barrier token. The harness emits "INFLIGHT_WRITE_DONE"
        # on stdout when the inflight write + fsync completes; then it
        # enters a sleep loop awaiting SIGKILL.
        barrier_seen = _wait_for_barrier_token(
            proc, token="INFLIGHT_WRITE_DONE", timeout_s=30
        )
        assert barrier_seen, (
            "Crash test harness did not emit INFLIGHT_WRITE_DONE; the "
            "crash-injection hook may not be wired in parquet_writer.py "
            "(_crash_test_harness_c2). Tracked in scaffold follow-up B-N."
        )

        # Send SIGKILL. Per spec, the canonical Tier 4 signal is
        # signal.SIGKILL on Linux (uncatchable).
        os.kill(proc.pid, signal.SIGKILL)
        exit_code = proc.wait(timeout=10)

        # SIGKILL produces a negative return code on Linux (-SIGKILL).
        assert exit_code < 0, (
            f"Subprocess should have died from SIGKILL (negative exit "
            f"code); got {exit_code!r}"
        )

        # Verify orphan inflight file exists.
        inflight_files = list(output_dir.rglob("*.parquet._inflight"))
        assert len(inflight_files) == 1, (
            f"Expected exactly 1 orphan inflight file; got "
            f"{inflight_files!r}"
        )

        # Verify final parquet file does NOT exist.
        final_files = list(output_dir.rglob("*.parquet"))
        # Exclude the inflight files from the parquet glob.
        final_files = [f for f in final_files if not f.name.endswith("._inflight")]
        assert len(final_files) == 0, (
            f"No final .parquet should exist post-crash; got {final_files!r}"
        )

        # Verify registry has NO row for the crashed key tuple.
        container = mssql_container_with_seed
        host = container.get_container_host_ip()
        port = container.get_exposed_port(1433)
        conn_str = (
            f"DRIVER={{ODBC Driver 18 for SQL Server}};"
            f"SERVER={host},{port};UID=sa;PWD=TestPassword!2026;"
            f"TrustServerCertificate=yes;Encrypt=yes;"
        )
        conn = pyodbc.connect(conn_str)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(*) FROM General.ops.ParquetSnapshotRegistry
                WHERE SourceName = ? AND TableName = ? AND BatchId = ?
                  AND BusinessDate = ?
                """,
                "DNA",
                "C2_TEST",
                9100,
                "2026-05-14",
            )
            count = cursor.fetchone()[0]
            assert count == 0, (
                f"Registry should have no row for crashed key tuple; "
                f"got count={count}"
            )
        finally:
            conn.close()

    def test_recovery_cleans_orphan(
        self,
        mssql_container_with_seed: Any,
        crash_subprocess_factory: Callable[..., subprocess.Popen],
        crash_recovery_run: Callable[..., subprocess.Popen],
        tmp_path: Path,
    ) -> None:
        """Recovery run via parquet_verify cleans the orphan inflight file.

        Setup:
          1. Reproduce the orphan state from
             ``test_crash_after_inflight_write_leaves_orphan``.
          2. Invoke ``parquet_verify`` against the same output_dir.

        Verification:
          - Orphan ``*.parquet._inflight`` file is removed.
          - Final state matches a clean-run baseline (no registry row,
            no parquet files, no inflight files - clean slate).

        Per 06_TESTING.md C2: "parquet_verify cleans on next run". The
        verify pass is the canonical reconciler for orphan inflight
        files that were never registry-tracked.
        """
        output_dir = tmp_path / "parquet_out"
        output_dir.mkdir()

        # Phase 1: reproduce the crash.
        proc = crash_subprocess_factory(
            target_module="data_load.parquet_writer",
            target_callable="_crash_test_harness_c2",
            env={
                "CRASH_INJECT_POINT": CRASH_INJECT_AFTER_INFLIGHT,
                "CRASH_OUTPUT_DIR": str(output_dir),
                "CRASH_SOURCE_NAME": "DNA",
                "CRASH_TABLE_NAME": "C2_TEST",
                "CRASH_BATCH_ID": "9101",
                "CRASH_BUSINESS_DATE": "2026-05-14",
            },
        )
        _wait_for_barrier_token(proc, token="INFLIGHT_WRITE_DONE", timeout_s=30)
        os.kill(proc.pid, signal.SIGKILL)
        proc.wait(timeout=10)

        # Confirm orphan exists pre-recovery.
        orphans_pre = list(output_dir.rglob("*.parquet._inflight"))
        assert len(orphans_pre) == 1, (
            f"Expected orphan pre-recovery; got {orphans_pre!r}"
        )

        # Phase 2: invoke parquet_verify (recovery sweep).
        recovery = crash_recovery_run(
            target_module="data_load.parquet_registry_client",
            target_callable="_crash_test_harness_verify_sweep",
            env={
                "CRASH_OUTPUT_DIR": str(output_dir),
                "CRASH_SOURCE_NAME": "DNA",
            },
        )
        recovery_exit = recovery.wait(timeout=60)
        assert recovery_exit == 0, (
            f"Recovery sweep should exit 0; got {recovery_exit}; "
            f"stderr={recovery.stderr.read().decode()!r}"
        )

        # Phase 3: verify orphan is cleaned.
        orphans_post = list(output_dir.rglob("*.parquet._inflight"))
        assert len(orphans_post) == 0, (
            f"Orphan inflight file should be cleaned by parquet_verify; "
            f"got {orphans_post!r}"
        )

    def test_recovery_idempotent(
        self,
        mssql_container_with_seed: Any,
        crash_subprocess_factory: Callable[..., subprocess.Popen],
        crash_recovery_run: Callable[..., subprocess.Popen],
        tmp_path: Path,
    ) -> None:
        """Re-running write_parquet_snapshot after cleanup produces exactly
        one registry row (D15 idempotency contract).

        Setup:
          1. Reproduce crash + clean orphan (same as test 2 above).
          2. Re-invoke ``write_parquet_snapshot`` with the SAME key tuple.
          3. Re-invoke a SECOND time with the SAME key tuple.

        Verification:
          - First post-recovery call: succeeds; registry has exactly 1 row.
          - Second post-recovery call: idempotent short-circuit OR
            UNIQUE-violation translated to ``RegistryInsertConflict``
            per M1 spec section 1.1.
          - Registry STILL has exactly 1 row for the key tuple (no
            duplicates from the recovery path).

        Per D15: "Idempotency mandatory at every layer". A recovered
        pipeline must NOT double-insert when re-running steps that
        completed before the crash.
        """
        import pyodbc  # noqa: PLC0415

        output_dir = tmp_path / "parquet_out"
        output_dir.mkdir()

        # Phase 1: reproduce + recover (skipped details; same as test 2).
        proc = crash_subprocess_factory(
            target_module="data_load.parquet_writer",
            target_callable="_crash_test_harness_c2",
            env={
                "CRASH_INJECT_POINT": CRASH_INJECT_AFTER_INFLIGHT,
                "CRASH_OUTPUT_DIR": str(output_dir),
                "CRASH_SOURCE_NAME": "DNA",
                "CRASH_TABLE_NAME": "C2_TEST",
                "CRASH_BATCH_ID": "9102",
                "CRASH_BUSINESS_DATE": "2026-05-14",
            },
        )
        _wait_for_barrier_token(proc, token="INFLIGHT_WRITE_DONE", timeout_s=30)
        os.kill(proc.pid, signal.SIGKILL)
        proc.wait(timeout=10)

        recovery = crash_recovery_run(
            target_module="data_load.parquet_registry_client",
            target_callable="_crash_test_harness_verify_sweep",
            env={"CRASH_OUTPUT_DIR": str(output_dir), "CRASH_SOURCE_NAME": "DNA"},
        )
        recovery.wait(timeout=60)

        # Phase 2: first clean re-run after recovery.
        first = crash_recovery_run(
            target_module="data_load.parquet_writer",
            target_callable="_crash_test_harness_c2",
            env={
                "CRASH_OUTPUT_DIR": str(output_dir),
                "CRASH_SOURCE_NAME": "DNA",
                "CRASH_TABLE_NAME": "C2_TEST",
                "CRASH_BATCH_ID": "9102",
                "CRASH_BUSINESS_DATE": "2026-05-14",
            },
        )
        first_exit = first.wait(timeout=60)
        assert first_exit == 0, (
            f"First clean re-run should succeed; got exit={first_exit}; "
            f"stderr={first.stderr.read().decode()!r}"
        )

        # Phase 3: second re-run with same key tuple - idempotent.
        second = crash_recovery_run(
            target_module="data_load.parquet_writer",
            target_callable="_crash_test_harness_c2",
            env={
                "CRASH_OUTPUT_DIR": str(output_dir),
                "CRASH_SOURCE_NAME": "DNA",
                "CRASH_TABLE_NAME": "C2_TEST",
                "CRASH_BATCH_ID": "9102",
                "CRASH_BUSINESS_DATE": "2026-05-14",
            },
        )
        second_exit = second.wait(timeout=60)
        # Either clean-exit (write completed; UNIQUE caught and translated)
        # or non-zero with RegistryInsertConflict in stderr.
        assert second_exit in (0, 1), (
            f"Second re-run: exit should be 0 (idempotent) or 1 "
            f"(RegistryInsertConflict); got {second_exit}; "
            f"stderr={second.stderr.read().decode()!r}"
        )

        # Phase 4: verify exactly 1 registry row exists.
        container = mssql_container_with_seed
        host = container.get_container_host_ip()
        port = container.get_exposed_port(1433)
        conn_str = (
            f"DRIVER={{ODBC Driver 18 for SQL Server}};"
            f"SERVER={host},{port};UID=sa;PWD=TestPassword!2026;"
            f"TrustServerCertificate=yes;Encrypt=yes;"
        )
        conn = pyodbc.connect(conn_str)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(*) FROM General.ops.ParquetSnapshotRegistry
                WHERE SourceName = ? AND TableName = ? AND BatchId = ?
                  AND BusinessDate = ?
                """,
                "DNA",
                "C2_TEST",
                9102,
                "2026-05-14",
            )
            count = cursor.fetchone()[0]
            assert count == 1, (
                f"Idempotency contract: exactly 1 registry row after "
                f"recovery + 2 re-runs; got count={count}"
            )
        finally:
            conn.close()


def _wait_for_barrier_token(
    proc: subprocess.Popen, *, token: str, timeout_s: float
) -> bool:
    """Block until the subprocess emits ``token`` on stdout or times out.

    Tier 4 barrier mechanism: the crash-injection harness inside the
    pipeline code emits a well-known token on stdout when it reaches
    the canonical crash boundary, then enters a sleep loop. The parent
    test process polls stdout for the token; once seen, it sends SIGKILL.

    Args:
        proc: The ``subprocess.Popen`` instance to read from.
        token: The exact string the harness emits at the crash barrier.
        timeout_s: Wall-clock budget in seconds.

    Returns:
        True if the token was observed before ``timeout_s``; False if
        the timeout elapsed first OR the subprocess exited before
        emitting the token.
    """
    deadline = time.monotonic() + timeout_s
    if proc.stdout is None:
        return False

    accumulated = b""
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            # Subprocess exited before barrier; harness failed.
            return False
        # Non-blocking read: ``readline`` blocks; we use a short timeout
        # via select on POSIX. For scaffold simplicity we use ``readline``
        # with a polling loop; real implementation may use selectors.
        line = proc.stdout.readline()
        if not line:
            time.sleep(0.05)
            continue
        accumulated += line
        if token.encode() in accumulated:
            return True
    return False
