"""Tier 4 crash-injection test fixtures per docs/migration/06_TESTING.md
"Tier 4 - Crash Injection" + docs/migration/phase1/05_tests.md section 7.

Tier 4 = crash-injection (SIGKILL) testing under a Dockerised SQL Server
fixture. The canonical approach (per 06_TESTING.md) runs the pipeline in a
real subprocess against a real container, sends SIGKILL at specific code
points (C1-C15), restarts the pipeline, and verifies convergence to the
clean-run end-state.

Per section 1.6 Tier 0/1 boundary: this conftest is NOT loaded by Tier 0/1
tests (it lives under tests/crash/ which pytest only loads when invoked
with ``pytest tests/crash`` OR via marker filter).

Canonical container image (reused from Tier 3 scaffold; pinned per Round 6
section 7.10 / 4.5 / 5.4 / 8.10):
    mcr.microsoft.com/mssql/server:2022-CU14-ubuntu-22.04

Pre-seed contract (Tier 4 specific): the ``mssql_container_with_seed``
fixture pre-loads 100 IdempotencyLedger rows + 50 ParquetSnapshotRegistry
rows so crash tests start from a realistic mid-pipeline state (not a
pristine schema). Tier 3 fixtures start from a clean schema; Tier 4 needs
realistic state for the recovery contract to be meaningful.

Crash-orchestration platform check: the SIGKILL primitive differs between
Linux (``signal.SIGKILL`` = uncatchable) and Windows (closest analogue is
``signal.SIGTERM`` which IS catchable). The canonical Tier 4 spec assumes
Linux container semantics; Windows dev workstations skip with explicit
reason.

Docker availability is probed once per session (reusing the Tier 3 probe);
tests skip gracefully when Docker is unavailable.

Fixture inventory (per section 7)
==================================

  * ``_docker_available`` (session-scope, bool) - subprocess ``docker info``
    probe; cached for the session. Mirrors Tier 3 conftest.
  * ``_crash_orchestration_available`` (session-scope, bool) - probes
    multiprocessing + signal modules; platform-gates SIGKILL semantics.
  * ``mssql_container_with_seed`` (session-scope) -
    testcontainers.mssql.SqlServerContainer pre-loaded with 100 ledger
    rows + 50 registry rows to simulate realistic mid-pipeline state.
  * ``crash_subprocess_factory`` (function-scope) - spawns a Python
    subprocess running a target function; returns the Popen handle so
    the test can SIGKILL at a barrier point.
  * ``crash_recovery_run`` (function-scope) - companion to
    ``crash_subprocess_factory``; runs the SAME target function in a
    fresh subprocess after the crash for convergence verification.
  * ``docker_skip_marker`` (factory) - returns pytest.mark.skipif that
    test files import + apply at module level for Docker availability.
  * ``crash_orchestration_skip_marker`` (factory) - second skipif for
    SIGKILL-platform-semantics; test files apply BOTH markers.

D-numbers consumed: D15 (idempotency at every layer; recovery convergence
is the whole point of Tier 4), D16 (atomic file write; inflight rename
under crash), D17 (ledger pattern under crash), D55 (producer != reviewer;
the crash-recovery test IS the reviewer of the producer's idempotency
claim), D67 (Tier 4 is NOT smoke - real SIGKILL, real container), D81
(testing budget - 2 hours pre-release).

B-numbers: this scaffold's tracking B-N (TBD at landing); follow-up B-Ns
for C1 / C3-C6 / C8-C10 / C12-C15 coverage extensions.
"""
from __future__ import annotations

import logging
import os
import platform
import shutil
import signal
import subprocess
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterator

import pytest

if TYPE_CHECKING:  # pragma: no cover - type-only imports
    import pyodbc


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Canonical container image - reused from Tier 3 scaffold per Round 6 7.10.
# DO NOT bump without a decision (D-number) + spec doc update.
# ---------------------------------------------------------------------------

CANONICAL_MSSQL_IMAGE = "mcr.microsoft.com/mssql/server:2022-CU14-ubuntu-22.04"

# Strong SA password matching the Tier 3 fixture; container-only.
_TEST_SA_PASSWORD = "TestPassword!2026"  # noqa: S105 - test fixture constant

# Tier 3 schema.sql is the canonical schema source; reused as-is.
_SCHEMA_SQL_PATH = (
    Path(__file__).resolve().parent.parent
    / "fixtures"
    / "udm_test_fixtures"
    / "schema.sql"
)

# Pre-seed row counts per the section 7 spec ("realistic mid-pipeline state").
_SEED_LEDGER_ROWS = 100
_SEED_REGISTRY_ROWS = 50


# ---------------------------------------------------------------------------
# Module-level skip helpers - test files import + apply BOTH markers so
# collection does not fire any fixture resolution when the platform cannot
# support real Tier 4 execution.
# ---------------------------------------------------------------------------


def docker_skip_marker() -> pytest.MarkDecorator:
    """Return a ``pytest.mark.skipif`` decorator that skips when Docker absent.

    Test files apply this at module level via::

        pytestmark = [docker_skip_marker(), crash_orchestration_skip_marker()]

    to gate the entire file at collection time. Two checks:

      1. ``shutil.which("docker")`` - is the binary on PATH?
      2. Subprocess ``docker info`` - is a daemon running?

    Both must pass for the marker to be a no-op. Either failure yields
    a skip with explicit reason citing the spec section.

    Returns:
        pytest.mark.skipif decorator; ``condition=True`` when skip should
        fire; ``condition=False`` when Docker is fully available.
    """
    has_docker_binary = shutil.which("docker") is not None
    has_running_daemon = False
    if has_docker_binary:
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=10,
                check=False,
            )
            has_running_daemon = result.returncode == 0
        except (subprocess.TimeoutExpired, OSError):
            has_running_daemon = False

    skip_condition = not (has_docker_binary and has_running_daemon)
    return pytest.mark.skipif(
        skip_condition,
        reason=(
            "Tier 4 crash tests require Docker Desktop with a running daemon. "
            "Install Docker + restart shell to enable. "
            "Per docs/migration/06_TESTING.md Tier 4 + "
            "docs/migration/phase1/05_tests.md section 7."
        ),
    )


def crash_orchestration_skip_marker() -> pytest.MarkDecorator:
    """Return a ``pytest.mark.skipif`` that gates on SIGKILL-platform-semantics.

    The canonical Tier 4 approach (per 06_TESTING.md) sends ``signal.SIGKILL``
    to a subprocess running the pipeline. SIGKILL semantics:

      - **Linux/Darwin** - SIGKILL is uncatchable and terminates the
        process immediately. Canonical Tier 4 behaviour.
      - **Windows** - Python maps ``signal.SIGTERM`` to ``TerminateProcess``;
        ``signal.SIGKILL`` is NOT defined on Windows. ``subprocess.kill()``
        on Windows uses ``TerminateProcess`` which IS catchable in some
        cases via SEH. NOT equivalent to canonical SIGKILL.

    Tests apply this marker to skip on Windows dev workstations even when
    Docker IS available; Tier 4 canonical behaviour is Linux-container only.

    Returns:
        pytest.mark.skipif decorator; condition fires on Windows OR when
        the multiprocessing module fails to import (e.g., minimal Python
        builds without forking support).
    """
    is_windows = platform.system() == "Windows"

    multiprocessing_available = True
    try:
        import multiprocessing  # noqa: F401, PLC0415
    except ImportError:
        multiprocessing_available = False

    has_sigkill = hasattr(signal, "SIGKILL")

    skip_condition = is_windows or not multiprocessing_available or not has_sigkill
    return pytest.mark.skipif(
        skip_condition,
        reason=(
            "Tier 4 crash tests require Linux SIGKILL semantics + "
            "multiprocessing module. SIGKILL is uncatchable on Linux; "
            "Windows TerminateProcess is NOT equivalent. "
            "Per docs/migration/06_TESTING.md Tier 4: 'container kill "
            "orchestration' assumes Linux-container execution. "
            f"Detected: platform={platform.system()!r}, "
            f"multiprocessing={multiprocessing_available}, "
            f"SIGKILL_defined={has_sigkill}."
        ),
    )


# ---------------------------------------------------------------------------
# Session-scope: Docker availability probe (mirrors Tier 3 conftest).
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def _docker_available() -> bool:
    """Probe ``docker info`` once per session; cache the result.

    Returns:
        True iff (a) the ``docker`` binary is on PATH AND (b) ``docker info``
        returns exit code 0 within 10 seconds. False otherwise.

    Mirrors the Tier 3 conftest probe; intentionally duplicated so the
    Tier 4 conftest is self-contained (Tier 4 can be invoked without
    Tier 3 collection).
    """
    if shutil.which("docker") is None:
        logger.debug("_docker_available: docker binary not on PATH")
        return False

    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.debug("_docker_available: subprocess error %r", exc)
        return False

    available = result.returncode == 0
    logger.debug("_docker_available: %s", available)
    return available


# ---------------------------------------------------------------------------
# Session-scope: crash-orchestration availability probe.
#
# Mirrors the marker logic but exposed as a fixture so tests can also
# condition on it dynamically (e.g., for assertions about expected skip
# reason).
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def _crash_orchestration_available() -> bool:
    """Probe SIGKILL-platform-semantics once per session.

    Returns:
        True iff (a) not running on Windows, (b) multiprocessing imports,
        AND (c) signal.SIGKILL is defined. False otherwise.

    The three sub-checks correspond directly to the three failure modes
    in ``crash_orchestration_skip_marker()``; keeping them as separate
    booleans makes the test-side diagnostic clearer.
    """
    is_windows = platform.system() == "Windows"

    multiprocessing_available = True
    try:
        import multiprocessing  # noqa: F401, PLC0415
    except ImportError:
        multiprocessing_available = False

    has_sigkill = hasattr(signal, "SIGKILL")

    available = (
        not is_windows and multiprocessing_available and has_sigkill
    )
    logger.debug(
        "_crash_orchestration_available: platform=%s, multiprocessing=%s, "
        "SIGKILL=%s -> %s",
        platform.system(),
        multiprocessing_available,
        has_sigkill,
        available,
    )
    return available


# ---------------------------------------------------------------------------
# Session-scope: MSSQL container with pre-seeded mid-pipeline state.
#
# Distinct from the Tier 3 ``mssql_container`` fixture - Tier 4 needs the
# container to start with 100 ledger rows + 50 registry rows so the
# crash-recovery convergence test has meaningful state to converge TO.
# A pristine schema would not surface idempotency bugs (every step would
# look like a clean first-run).
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def mssql_container_with_seed(_docker_available: bool) -> Iterator[Any]:
    """Yield a running SQL Server 2022 container pre-seeded with 100
    IdempotencyLedger rows + 50 ParquetSnapshotRegistry rows.

    Lifecycle (per section 7):
      1. Skip if ``_docker_available`` is False.
      2. Import ``testcontainers.mssql.SqlServerContainer``; skip if absent.
      3. Start the container with the canonical image; wait for readiness.
      4. Apply ``tests/fixtures/udm_test_fixtures/schema.sql`` (reused
         from Tier 3 scaffold).
      5. INSERT ``_SEED_LEDGER_ROWS`` rows into General.ops.IdempotencyLedger
         with Status='COMPLETED' across varying (BatchId, SourceName,
         TableName, EventType) tuples.
      6. INSERT ``_SEED_REGISTRY_ROWS`` rows into
         General.ops.ParquetSnapshotRegistry with mixed Status
         (created / verified / replicated) to exercise the state machine.
      7. Yield the container instance.
      8. On session teardown, ``container.stop()`` reclaims resources.

    Raises:
        pytest.skip: Docker unavailable OR testcontainers not installed
        OR schema.sql not yet authored.

    Yields:
        The ``SqlServerContainer`` instance with pre-seeded mid-pipeline
        state; tests use ``container.get_connection_url()`` to obtain a
        pyodbc connection string.
    """
    if not _docker_available:
        pytest.skip(
            "Docker unavailable for mssql_container_with_seed fixture. "
            "Per docs/migration/06_TESTING.md Tier 4."
        )

    try:
        from testcontainers.mssql import SqlServerContainer  # noqa: PLC0415
    except ImportError as exc:
        pytest.skip(
            f"testcontainers-python not installed ({exc!r}). "
            "Install via `uv pip install testcontainers[mssql]` to enable "
            "Tier 4 crash tests. Per docs/migration/06_TESTING.md Tier 4 + "
            "docs/migration/phase1/05_tests.md section 7."
        )
        return  # unreachable; placates type checker

    if not _SCHEMA_SQL_PATH.exists():
        pytest.skip(
            f"schema.sql not yet authored at {_SCHEMA_SQL_PATH}. "
            "Tier 4 reuses the Tier 3 schema fixture; author per "
            "docs/migration/phase1/05_tests.md section 1.3 first."
        )
        return  # unreachable

    logger.info(
        "mssql_container_with_seed: starting %s", CANONICAL_MSSQL_IMAGE
    )
    container = SqlServerContainer(
        image=CANONICAL_MSSQL_IMAGE,
        password=_TEST_SA_PASSWORD,
    )

    try:
        container.start()
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "mssql_container_with_seed: start failed (%s); skipping",
            exc,
        )
        pytest.skip(
            f"SqlServerContainer.start() failed: {exc!r}. "
            "Verify Docker daemon is healthy + has > 2 GB free RAM."
        )

    logger.info(
        "mssql_container_with_seed: started (host=%s, port=%s)",
        container.get_container_host_ip(),
        container.get_exposed_port(1433),
    )

    try:
        _apply_schema_and_seed(container)
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "mssql_container_with_seed: schema/seed failed (%s)", exc
        )
        try:
            container.stop()
        except Exception as stop_exc:  # noqa: BLE001
            logger.warning(
                "Stop after schema-failure failed: %s", stop_exc
            )
        pytest.skip(
            f"Schema apply or seed insert failed: {exc!r}. "
            "Verify schema.sql is well-formed + General.ops tables exist."
        )

    try:
        yield container
    finally:
        logger.info("mssql_container_with_seed: stopping session container")
        try:
            container.stop()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "mssql_container_with_seed: stop failed (non-fatal): %s",
                exc,
            )


def _apply_schema_and_seed(container: Any) -> None:
    """Apply schema.sql + INSERT the canonical pre-seed rows.

    Helper for the ``mssql_container_with_seed`` fixture; private to this
    module. Splits schema.sql on GO statements + executes each batch;
    then INSERTs the pre-seed rows in a single transaction.

    Args:
        container: Running ``SqlServerContainer`` instance.

    Raises:
        RuntimeError: schema apply or seed insert fails; wrapped with
            batch context for diagnosis.
    """
    import pyodbc  # noqa: PLC0415

    host = container.get_container_host_ip()
    port = container.get_exposed_port(1433)
    conn_str = (
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={host},{port};"
        f"UID=sa;"
        f"PWD={_TEST_SA_PASSWORD};"
        f"TrustServerCertificate=yes;"
        f"Encrypt=yes;"
    )

    schema_sql = _SCHEMA_SQL_PATH.read_text(encoding="utf-8")
    batches = _split_sql_batches(schema_sql)

    conn = pyodbc.connect(conn_str, autocommit=True)
    try:
        cursor = conn.cursor()
        try:
            # Phase 1: apply schema DDL.
            for i, batch in enumerate(batches):
                if not batch.strip():
                    continue
                try:
                    cursor.execute(batch)
                except pyodbc.Error as exc:
                    raise RuntimeError(
                        f"_apply_schema_and_seed: batch {i} failed: "
                        f"{exc!r}\n--- SQL ---\n{batch[:500]}"
                    ) from exc

            # Phase 2: pre-seed IdempotencyLedger.
            # The seed represents realistic mid-pipeline state: completed
            # steps for varying tables across one batch. Crash tests start
            # with this state and verify recovery does not double-process.
            for i in range(_SEED_LEDGER_ROWS):
                cursor.execute(
                    """
                    INSERT INTO General.ops.IdempotencyLedger (
                        BatchId, SourceName, TableName, EventType,
                        Status, StartedAt, CompletedAt, DurationMs
                    ) VALUES (?, ?, ?, ?, 'COMPLETED',
                              SYSUTCDATETIME(), SYSUTCDATETIME(), 100)
                    """,
                    8000,
                    "DNA",
                    f"SEED_TABLE_{i:03d}",
                    "EXTRACT",
                )

            # Phase 3: pre-seed ParquetSnapshotRegistry with mixed Status.
            # Status distribution: 20 created / 20 verified / 10 replicated
            # to exercise the state-machine transitions C2 / C11 walk.
            status_distribution = (
                [("created", i) for i in range(20)]
                + [("verified", i) for i in range(20, 40)]
                + [("replicated", i) for i in range(40, _SEED_REGISTRY_ROWS)]
            )
            for status, i in status_distribution:
                cursor.execute(
                    """
                    INSERT INTO General.ops.ParquetSnapshotRegistry (
                        SourceName, TableName, BatchId, BusinessDate,
                        FilePath, Sha256, FileSizeBytes, Status, CreatedAt
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, SYSUTCDATETIME())
                    """,
                    "DNA",
                    f"SEED_TABLE_{i:03d}",
                    8000,
                    "2026-05-14",
                    f"/tmp/seed/DNA/SEED_TABLE_{i:03d}/8000.parquet",
                    "0" * 64,
                    1024,
                    status,
                )
        finally:
            cursor.close()
    finally:
        conn.close()

    logger.info(
        "_apply_schema_and_seed: applied %d schema batches + "
        "seeded %d ledger rows + %d registry rows",
        len(batches),
        _SEED_LEDGER_ROWS,
        _SEED_REGISTRY_ROWS,
    )


def _split_sql_batches(sql: str) -> list[str]:
    """Split a SQL Server script into batches on standalone GO statements.

    Reused from Tier 3 conftest; duplicated here so Tier 4 conftest is
    self-contained (Tier 4 can run without Tier 3 collection).

    Args:
        sql: Multi-batch SQL Server script.

    Returns:
        List of individual batch strings; empty batches preserved at
        index positions for traceability.
    """
    import re  # noqa: PLC0415

    pattern = re.compile(
        r"^\s*GO\s*(?:\d+)?\s*$", re.IGNORECASE | re.MULTILINE
    )
    return pattern.split(sql)


# ---------------------------------------------------------------------------
# Function-scope: crash subprocess factory.
#
# Spawns a Python subprocess running a target function. Returns the
# Popen handle so the test can:
#   - Wait for the subprocess to reach a barrier (env var + signal token
#     emitted on stdout)
#   - Send SIGKILL at the canonical crash point
#   - Verify the subprocess exited non-zero (crash signature)
#
# The factory pattern is necessary because each crash test launches
# different target functions (parquet writer / scd2 engine / CLI tool).
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def crash_subprocess_factory(
    _crash_orchestration_available: bool,
) -> Iterator[Callable[..., subprocess.Popen]]:
    """Yield a factory that spawns a Python subprocess for crash injection.

    Per section 7 canonical pattern: each crash test spawns a worker
    subprocess that runs the target pipeline code, sets an environment
    variable signalling the crash injection point, then either:

      (a) calls back to a barrier via stdout/stderr (subprocess emits
          a known token when it reaches the crash boundary), OR
      (b) sleeps long enough for the parent to read the registry/ledger
          state, then proceeds.

    The parent test process reads the barrier signal, sends
    ``os.kill(pid, signal.SIGKILL)``, waits for ``subprocess.wait()`` to
    return non-zero, and queries the database to verify post-crash state.

    Args:
        _crash_orchestration_available: Session-scope precondition check;
            skips if SIGKILL semantics unavailable on current platform.

    Yields:
        Callable: factory function accepting ``target_module`` (str),
        ``target_callable`` (str), ``env`` (dict[str, str] for crash
        injection point + barrier configuration), and optional
        ``args`` (list[str]) - returns the ``subprocess.Popen`` handle.

    Cleanup: any subprocesses left running on test exit are killed via
    ``Popen.kill()`` + ``Popen.wait()`` to avoid leaking processes.
    """
    if not _crash_orchestration_available:
        pytest.skip(
            "crash_subprocess_factory requires SIGKILL-capable platform. "
            "Per docs/migration/06_TESTING.md Tier 4."
        )

    spawned: list[subprocess.Popen] = []

    def factory(
        target_module: str,
        target_callable: str,
        env: dict[str, str] | None = None,
        args: list[str] | None = None,
    ) -> subprocess.Popen:
        """Spawn a Python subprocess running ``module.callable``.

        Args:
            target_module: Fully-qualified module path (e.g.,
                "data_load.parquet_writer").
            target_callable: Callable name inside the module (e.g.,
                "write_parquet_snapshot").
            env: Extra environment variables for crash injection
                configuration. Merged with current ``os.environ``.
            args: Command-line args appended to the python command.

        Returns:
            The ``subprocess.Popen`` instance. Caller is responsible for
            sending signals + waiting for exit; the factory's cleanup
            handler kills any still-running children on test exit.
        """
        merged_env = dict(os.environ)
        if env:
            merged_env.update(env)

        # Spawn via ``python -c`` so we don't need a separate entrypoint
        # script for each crash boundary. The target callable is imported
        # + invoked inside the subprocess; any args are passed through.
        invocation = (
            f"import sys; "
            f"sys.path.insert(0, {str(Path(__file__).resolve().parent.parent.parent)!r}); "
            f"from {target_module} import {target_callable}; "
            f"{target_callable}()"
        )
        cmd = [sys.executable, "-c", invocation]
        if args:
            cmd.extend(args)

        logger.info(
            "crash_subprocess_factory: spawning %s with env keys %s",
            f"{target_module}.{target_callable}",
            sorted((env or {}).keys()),
        )
        proc = subprocess.Popen(  # noqa: S603 - intentional subprocess
            cmd,
            env=merged_env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        spawned.append(proc)
        return proc

    try:
        yield factory
    finally:
        # Cleanup: kill any subprocesses still running on test exit.
        for proc in spawned:
            if proc.poll() is None:
                logger.warning(
                    "crash_subprocess_factory: cleaning up still-running "
                    "pid=%s on test exit",
                    proc.pid,
                )
                try:
                    proc.kill()
                    proc.wait(timeout=5)
                except (OSError, subprocess.TimeoutExpired) as exc:
                    logger.warning("Cleanup kill failed: %s", exc)


# ---------------------------------------------------------------------------
# Function-scope: recovery run companion fixture.
#
# After a crash subprocess has been SIGKILL'd + verified to have produced
# the expected mid-state, the test runs the recovery via this fixture.
# Recovery uses the SAME target callable as the crashed run but with the
# crash-injection environment variable UNSET, so the run proceeds to
# completion.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def crash_recovery_run(
    crash_subprocess_factory: Callable[..., subprocess.Popen],
) -> Iterator[Callable[..., subprocess.Popen]]:
    """Yield a factory for the recovery (no-crash) run of the same target.

    Per section 7 convergence contract: a crashed pipeline restart must
    converge to the SAME end-state as a clean run. The recovery factory
    spawns the same target with ``CRASH_INJECT_POINT`` env var stripped
    out so the callable runs to completion. The test then queries the
    database to verify Bronze / Registry / Ledger end-state matches the
    expected clean-run baseline.

    Args:
        crash_subprocess_factory: The crash factory; recovery delegates
            to it with crash-injection env disabled.

    Yields:
        Callable: same signature as ``crash_subprocess_factory`` but
        guarantees the ``CRASH_INJECT_POINT`` env var is NOT in the
        subprocess environment regardless of caller intent.
    """

    def recovery_factory(
        target_module: str,
        target_callable: str,
        env: dict[str, str] | None = None,
        args: list[str] | None = None,
    ) -> subprocess.Popen:
        """Spawn the recovery run; ensures no crash injection."""
        clean_env = dict(env or {})
        # Strip ANY crash-injection key the caller may have passed.
        clean_env.pop("CRASH_INJECT_POINT", None)
        return crash_subprocess_factory(
            target_module=target_module,
            target_callable=target_callable,
            env=clean_env,
            args=args,
        )

    yield recovery_factory
