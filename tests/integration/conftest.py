"""Tier 3 integration test fixtures per docs/migration/phase1/05_tests.md section 1.3.

Per section 1.6 Tier 0/1 boundary: this conftest is NOT loaded by Tier 0/1
tests (it lives under tests/integration/ which pytest only loads when
invoked with ``pytest tests/integration`` OR via marker filter).

Canonical container image: mcr.microsoft.com/mssql/server:2022-CU14-ubuntu-22.04
(version-pinned per Round 6 section 7.10 / 4.5 / 5.4 / 8.10).

State-leakage mitigation: each test wrapped in SQLAlchemy-style transactional
rollback (BEGIN at fixture entry; ROLLBACK at test exit) per section 1.3.

B-115 closure target: tests/fixtures/udm_test_fixtures/conftest.py per section
1.3 spec; this file is the canonical implementation living inside
tests/integration/ so pytest auto-discovers it.

Docker availability is probed once per session; tests skip gracefully when
Docker is unavailable (e.g., Windows dev workstation without Docker Desktop
or RHEL dev box without a running daemon).

Fixture inventory (per section 1.3)
====================================

  * ``_docker_available`` (session-scope, bool) - subprocess ``docker info``
    probe; cached for the session.
  * ``mssql_container`` (session-scope) - testcontainers.mssql.SqlServerContainer;
    yields the running container; stopped on session teardown.
  * ``mssql_connection`` (function-scope) - fresh pyodbc connection per test
    via ``container.get_connection_url()``.
  * ``mssql_cursor`` (function-scope) - cursor from ``mssql_connection``.
  * ``test_db_transaction`` (function-scope) - wraps the test body in
    BEGIN/ROLLBACK for state-leakage mitigation per section 1.3.
  * ``canonical_schema_loaded`` (session-scope) - applies
    tests/fixtures/udm_test_fixtures/schema.sql against the container at
    session start; falls back to skip when the file isn't authored yet.
  * ``docker_skip_marker`` (factory) - returns pytest.mark.skipif that
    test files import + apply at module level to skip the entire file
    when Docker is unavailable.

D-numbers consumed: D15 (idempotency at every layer; replayed by the
state-leakage transactional rollback fixture), D67 (Tier 0 smoke
discipline does NOT apply here - Tier 3 is real-DB by definition),
D70 (Tier 1 vs Tier 3 boundary), D81 (testing budget), D92 (forward-
only additive - new fixture set; no rename).

B-numbers: B-115 (this scaffold); follow-up B-Ns for schema.sql /
seed_data.sql / per-module fixture extensions.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterator

import pytest

if TYPE_CHECKING:  # pragma: no cover - type-only imports
    import pyodbc


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Canonical container image - version-pinned per Round 6 section 7.10.
#
# DO NOT bump this without a corresponding decision (D-number) and updates
# to the spec doc (phase1/05_tests.md section 1.3 + section 4.5). Pinning
# the image ensures reproducible CI behavior; a "latest" tag could shift
# under us and silently change BCP / pyodbc / collation defaults.
# ---------------------------------------------------------------------------

CANONICAL_MSSQL_IMAGE = "mcr.microsoft.com/mssql/server:2022-CU14-ubuntu-22.04"

# Strong SA password for the container per Microsoft's SQL Server image
# requirements (>= 8 chars, mixed case, digit, symbol). Container-only;
# never read into pipeline code.
_TEST_SA_PASSWORD = "TestPassword!2026"  # noqa: S105 - test fixture constant

# Session-scope cache for the schema.sql resolution outcome so the load
# step does not re-stat the filesystem per test.
_SCHEMA_SQL_PATH = (
    Path(__file__).resolve().parent.parent
    / "fixtures"
    / "udm_test_fixtures"
    / "schema.sql"
)


# ---------------------------------------------------------------------------
# Module-level skip helper - test files import + apply this so collection
# does not even attempt fixture resolution when Docker is unavailable.
# ---------------------------------------------------------------------------


def docker_skip_marker() -> pytest.MarkDecorator:
    """Return a ``pytest.mark.skipif`` decorator that skips when Docker absent.

    Test files apply this at module level via::

        pytestmark = docker_skip_marker()

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
            "Tier 3 integration tests require Docker Desktop with a running "
            "daemon. Install Docker + restart shell to enable. "
            "Per docs/migration/phase1/05_tests.md section 1.3 + section 1.4 "
            "CI stage 3."
        ),
    )


# ---------------------------------------------------------------------------
# Session-scope: Docker availability probe.
#
# Returns the same bool the module-level marker uses; exposed as a fixture
# so individual tests can also condition on it (e.g., to skip rather than
# hard-fail when authoring a real-DB integration test on a machine without
# Docker).
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def _docker_available() -> bool:
    """Probe ``docker info`` once per session; cache the result.

    Returns:
        True iff (a) the ``docker`` binary is on PATH AND (b) ``docker info``
        returns exit code 0 within 10 seconds. False otherwise.

    The session-scope cache means subsequent ``mssql_container`` /
    ``canonical_schema_loaded`` fixture resolutions reuse the same probe
    outcome - we do NOT re-run ``docker info`` for every test.
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
# Session-scope: MSSQL container lifecycle.
#
# The testcontainers import is guarded - the package may NOT be installed
# in every dev environment (it is NOT a runtime dependency of the pipeline,
# only of integration tests). The guard short-circuits to a session-level
# skip so the rest of the suite can still collect + run.
#
# Container start-up uses testcontainers' built-in readiness wait - the
# Mssql module polls for SQL Server's listener acceptance before yielding
# the container to the test.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def mssql_container(_docker_available: bool) -> Iterator[Any]:
    """Yield a running SQL Server 2022 container for the session.

    Lifecycle (per section 1.3):
      1. Skip if ``_docker_available`` is False.
      2. Import ``testcontainers.mssql.SqlServerContainer``; skip if absent.
      3. Start the container with the canonical image; wait for readiness.
      4. Yield the container instance.
      5. On session teardown, ``container.stop()`` reclaims resources.

    Raises:
        pytest.skip: Docker unavailable OR testcontainers not installed.

    Yields:
        The ``SqlServerContainer`` instance; tests use
        ``container.get_connection_url()`` to obtain a pyodbc connection string.
    """
    if not _docker_available:
        pytest.skip(
            "Docker unavailable for mssql_container fixture. "
            "Per docs/migration/phase1/05_tests.md section 1.3."
        )

    try:
        from testcontainers.mssql import SqlServerContainer  # noqa: PLC0415
    except ImportError as exc:
        pytest.skip(
            f"testcontainers-python not installed ({exc!r}). "
            "Install via `uv pip install testcontainers[mssql]` to enable "
            "Tier 3 integration tests. Per docs/migration/phase1/05_tests.md "
            "section 1.3 fixture inventory."
        )
        return  # unreachable; pytest.skip raises; placates mypy

    logger.info("mssql_container: starting %s", CANONICAL_MSSQL_IMAGE)
    container = SqlServerContainer(
        image=CANONICAL_MSSQL_IMAGE,
        password=_TEST_SA_PASSWORD,
    )

    try:
        container.start()
    except Exception as exc:  # noqa: BLE001 - testcontainers wraps various errors
        logger.error("mssql_container: start failed (%s); skipping session", exc)
        pytest.skip(
            f"SqlServerContainer.start() failed: {exc!r}. "
            "Verify Docker daemon is healthy + has > 2 GB free RAM "
            "(SQL Server 2022 requires ~ 2 GB minimum)."
        )

    logger.info(
        "mssql_container: started (host=%s, port=%s)",
        container.get_container_host_ip(),
        container.get_exposed_port(1433),
    )

    try:
        yield container
    finally:
        logger.info("mssql_container: stopping session container")
        try:
            container.stop()
        except Exception as exc:  # noqa: BLE001
            logger.warning("mssql_container: stop failed (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# Function-scope: fresh pyodbc connection per test.
#
# Per section 1.3 - each test gets its own connection so connection-level
# state (autocommit, current database, session-scope locks) is isolated.
# Closes on teardown unconditionally; pyodbc.Connection.close() is
# idempotent so double-close is safe.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def mssql_connection(mssql_container: Any) -> Iterator["pyodbc.Connection"]:
    """Yield a fresh pyodbc connection to the session-scope container.

    Per section 1.3: each test gets its own connection so cursor state,
    transactions, and SET options do not leak between tests. The
    connection is closed unconditionally on test teardown.

    The connection string is sourced from the container's
    ``get_connection_url()`` method, which testcontainers builds in
    SQLAlchemy URL form. We translate to a pyodbc-friendly DSN using the
    container's exposed host / port / credentials.

    Yields:
        ``pyodbc.Connection`` with autocommit=False (default). Tests
        wanting BEGIN/ROLLBACK semantics should use ``test_db_transaction``
        instead.
    """
    import pyodbc  # noqa: PLC0415 - lazy import for graceful skip

    host = mssql_container.get_container_host_ip()
    port = mssql_container.get_exposed_port(1433)
    # ODBC Driver 18 per CLAUDE.md environment - matches production.
    # TrustServerCertificate=yes because the container ships a self-signed cert.
    conn_str = (
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={host},{port};"
        f"UID=sa;"
        f"PWD={_TEST_SA_PASSWORD};"
        f"TrustServerCertificate=yes;"
        f"Encrypt=yes;"
    )

    logger.debug("mssql_connection: opening connection to %s:%s", host, port)
    conn = pyodbc.connect(conn_str)
    try:
        yield conn
    finally:
        try:
            conn.close()
        except Exception as exc:  # noqa: BLE001
            logger.debug("mssql_connection: close error (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# Function-scope: fresh cursor per test.
#
# Convenience wrapper over ``mssql_connection`` so tests that only need
# a cursor (the common case) can take it directly. Closes the cursor
# on teardown; the underlying connection close is handled by
# ``mssql_connection``'s teardown.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def mssql_cursor(
    mssql_connection: "pyodbc.Connection",
) -> Iterator["pyodbc.Cursor"]:
    """Yield a fresh cursor from ``mssql_connection``; close on teardown."""
    cursor = mssql_connection.cursor()
    try:
        yield cursor
    finally:
        try:
            cursor.close()
        except Exception as exc:  # noqa: BLE001
            logger.debug("mssql_cursor: close error (non-fatal): %s", exc)


# ---------------------------------------------------------------------------
# Function-scope: transactional rollback for state-leakage mitigation.
#
# Per section 1.3: each test runs inside its own BEGIN/ROLLBACK so writes
# do not pollute the session-scope container's state. This is the
# SQLAlchemy-style pattern referenced in the spec.
#
# Important: pyodbc connections default to autocommit=False, so each
# statement on a fresh cursor is implicitly inside a transaction. The
# explicit BEGIN here is for clarity + to ensure rollback unwinds the
# WHOLE test body (not just the latest statement). On test exit, ROLLBACK
# discards every write the test issued.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="function")
def test_db_transaction(
    mssql_connection: "pyodbc.Connection",
) -> Iterator["pyodbc.Connection"]:
    """Wrap the test body in BEGIN/ROLLBACK; yield the connection.

    Per section 1.3 state-leakage mitigation. Tests that mutate the
    session-scope container's state SHOULD use this fixture so writes
    are rolled back on test exit.

    Yields:
        The pyodbc connection, with an open transaction. Test code uses
        ``connection.cursor()`` (or the ``mssql_cursor`` fixture) for
        statement execution.

    Teardown: ``connection.rollback()`` discards all writes from this test.
    If the test raises, the rollback still fires (try/finally semantics).
    """
    # pyodbc opens an implicit transaction on the first statement; we
    # explicitly disable autocommit + issue rollback on teardown to make
    # the contract explicit.
    prior_autocommit = mssql_connection.autocommit
    mssql_connection.autocommit = False

    try:
        yield mssql_connection
    finally:
        try:
            mssql_connection.rollback()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "test_db_transaction: rollback failed (non-fatal): %s", exc
            )
        # Restore the prior autocommit setting so subsequent tests see
        # the default.
        try:
            mssql_connection.autocommit = prior_autocommit
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "test_db_transaction: autocommit restore failed: %s", exc
            )


# ---------------------------------------------------------------------------
# Session-scope: canonical schema loader.
#
# Per section 1.3: schema.sql lives at
# ``tests/fixtures/udm_test_fixtures/schema.sql`` and contains the canonical
# UDM DDL subset the integration tests need (General.ops tables, indexes,
# and minimal seed rows for UdmTablesList / PipelineBatchSequence).
#
# For the B-115 scaffold landing, ``schema.sql`` is NOT yet authored - the
# fixture detects its absence and skips with an explicit reason so the
# downstream B-N tracking the schema authoring is visible to the operator.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def canonical_schema_loaded(mssql_container: Any) -> Iterator[None]:
    """Apply the canonical schema.sql to the session container.

    Per section 1.3: the canonical fixture loads
    ``tests/fixtures/udm_test_fixtures/schema.sql`` (a subset of
    ``phase1/01_database_schema.md`` containing the General.ops tables +
    indexes the integration tests reference).

    B-115 scaffold caveat: ``schema.sql`` is NOT yet authored. When the
    file is absent, this fixture skips with an explicit reason so the
    operator sees "schema.sql not yet authored; B-115 next iteration"
    in the pytest output rather than a confusing AttributeError.

    Authoring schema.sql is a downstream B-N tracked in BACKLOG.md; once
    landed, this fixture's body will execute the SQL via pyodbc against
    the container BEFORE any test runs.

    Yields:
        None - tests do not consume the return value; the side effect
        (schema loaded) is the contract.
    """
    if not _SCHEMA_SQL_PATH.exists():
        pytest.skip(
            f"schema.sql not yet authored at {_SCHEMA_SQL_PATH}. "
            "B-115 next iteration: author the canonical schema DDL "
            "subset per docs/migration/phase1/05_tests.md section 1.3 + "
            "phase1/01_database_schema.md."
        )
        return  # unreachable; pytest.skip raises

    import pyodbc  # noqa: PLC0415

    host = mssql_container.get_container_host_ip()
    port = mssql_container.get_exposed_port(1433)
    conn_str = (
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={host},{port};"
        f"UID=sa;"
        f"PWD={_TEST_SA_PASSWORD};"
        f"TrustServerCertificate=yes;"
        f"Encrypt=yes;"
    )

    logger.info(
        "canonical_schema_loaded: applying %s to container",
        _SCHEMA_SQL_PATH,
    )
    schema_sql = _SCHEMA_SQL_PATH.read_text(encoding="utf-8")

    # SQL Server batches separated by GO; pyodbc executes one batch per
    # cursor.execute() call. Split on GO statements (case-insensitive,
    # line-anchored) and execute each batch in sequence.
    batches = _split_sql_batches(schema_sql)

    conn = pyodbc.connect(conn_str, autocommit=True)
    try:
        cursor = conn.cursor()
        try:
            for i, batch in enumerate(batches):
                if not batch.strip():
                    continue
                try:
                    cursor.execute(batch)
                except pyodbc.Error as exc:
                    # Re-raise with batch context so test failures point
                    # to the offending DDL statement.
                    raise RuntimeError(
                        f"canonical_schema_loaded: batch {i} failed: "
                        f"{exc!r}\n--- SQL ---\n{batch[:500]}"
                    ) from exc
        finally:
            cursor.close()
    finally:
        conn.close()

    logger.info(
        "canonical_schema_loaded: applied %d batches from %s",
        len(batches),
        _SCHEMA_SQL_PATH.name,
    )

    yield None


# ---------------------------------------------------------------------------
# Helper: SQL batch splitter (private; not a fixture).
#
# SQL Server uses GO as the batch separator (not standard SQL).
# pyodbc cannot execute GO-separated scripts directly so we split client-
# side on GO statements that appear on their own line (or with trailing
# whitespace). String literals containing the word "go" are NOT affected
# because we anchor on line boundaries.
# ---------------------------------------------------------------------------


def _split_sql_batches(sql: str) -> list[str]:
    """Split a SQL Server script into batches on standalone GO statements.

    Per SQL Server convention, GO is the batch separator (not a T-SQL
    statement). Recognizes ``GO`` (case-insensitive) on its own line,
    optionally followed by an integer repeat count which we ignore for
    test scripts.

    Args:
        sql: Multi-batch SQL Server script.

    Returns:
        List of individual batch strings (whitespace-trimmed; empty
        batches preserved at index positions for traceability but the
        caller filters them).
    """
    import re  # noqa: PLC0415

    # Split on lines that contain ONLY "GO" (case-insensitive) possibly
    # followed by whitespace + optional repeat count.
    pattern = re.compile(r"^\s*GO\s*(?:\d+)?\s*$", re.IGNORECASE | re.MULTILINE)
    return pattern.split(sql)
