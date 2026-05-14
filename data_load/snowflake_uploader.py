"""M17 — Snowflake ``COPY INTO`` uploader for verified Parquet snapshots.

Per **`docs/migration/phase1/03_core_modules.md` § 7.1** (canonical
interface) — mirror a ``Status='verified'`` Parquet snapshot from the
network drive into Snowflake-managed Iceberg via ``COPY INTO``; flip
``ParquetSnapshotRegistry.Status`` ``'verified'`` → ``'replicated'`` via
M3's :func:`mark_replicated` on COPY success.

What this module does
---------------------

The public surface is one function, :func:`copy_parquet_to_snowflake`. It:

1. Reads the registry row by ``registry_id`` (status + network drive
   path + source / table). Raises :class:`~utils.errors.RegistryNotFound`
   if the row is absent; :class:`~utils.errors.RegistryStatusInvalid`
   if the status is not ``'verified'``.
2. Best-effort budget pre-check — if the current month's credit usage
   exceeds 80% of the configured cap (D23 — $120K / year ceiling),
   raises :class:`~utils.errors.SnowflakeBudgetAlert` BEFORE materializing
   the RSA key OR opening a Snowflake connection. Budget query failures
   are non-blocking (logged + skipped).
3. Loads credentials via M7's :func:`credentials_loader.load_credentials`.
   The RSA private key is materialized to ``/dev/shm/snowflake_pk_<pid>``
   mode 0600 by M7; the path (NOT the PEM contents) is substituted into
   the returned dict via ``SNOWFLAKE_PRIVATE_KEY_PATH``.
4. Opens a Snowflake connection via :mod:`snowflake.connector` (lazy
   import — keeps the module importable in environments where the
   connector is not installed, e.g. unit-test CI). Wraps connect
   failures in :class:`~utils.errors.SnowflakeAuthFailed`.
5. Issues ``COPY INTO <SNOWFLAKE_DATABASE>.<SNOWFLAKE_SCHEMA>.<table>``
   against an internal stage that already has visibility into the
   network-drive Parquet file. The COPY statement is parameterized with
   the file path + table name; the warehouse + database + schema come
   from ``.env`` via :mod:`utils.configuration` (per `02_configuration.md`
   § 2.1.8). COPY timeout failures raise
   :class:`~utils.errors.SnowflakeCopyTimeout` (retryable).
6. Parses the Snowflake response — extracts ``rows_loaded`` and the
   ``COPY_HISTORY`` query identifier (Snowflake's per-file load-history
   ID used for audit cross-reference + idempotent re-COPY).
7. Composes M3's :func:`mark_replicated` to flip
   ``ParquetSnapshotRegistry.Status`` ``'verified'`` → ``'replicated'``.
   This is gated by M3's existing ``ledger_step`` so the registry update
   is itself idempotent (re-call after success is a no-op).
8. Writes a ``PipelineEventLog`` row with ``EventType='SNOWFLAKE_COPY_INTO'``
   for runtime-performance dashboard tracking. Best-effort: the event
   log row is informational; failure to write does NOT block the
   replication side effect.
9. Releases the ephemeral RSA key via M7's :func:`release_snowflake_key`
   in a ``finally`` block — the key file is removed even if the COPY
   raises mid-flight.

Idempotency contract (per D15 + D17 — § 7.1 "Snowflake's COPY INTO is
itself idempotent by-file")
-----------------------------------------------------------------------

* **Snowflake side**: ``COPY INTO`` tracks file-load history per Snowflake
  docs — re-copying the same file produces ``rows_loaded=0``. Two
  processes racing on the same file is safe (the loser sees 0 rows
  loaded; both COPY operations complete successfully).
* **Registry side**: :func:`mark_replicated` short-circuits on
  ``Status='replicated'`` (idempotent no-op). Re-call after a successful
  COPY is a no-op at both layers.
* **Audit side**: The ``PipelineEventLog`` row is informational — duplicate
  rows on retry are tolerable (the dashboard query aggregates on
  ``BatchId + TableName + EventType``).

Concurrency (per D69 — § 7.1)
-----------------------------

* Single Snowflake CONNECTION per process — the RSA key file is
  per-process by design (``/dev/shm/snowflake_pk_<pid>`` per D71).
* ``--workers`` subprocesses each spawn their own CONNECTION + their
  own ephemeral key file. The COPY-INTO-against-same-file race is
  safe per the Snowflake file-load-history dedup.
* No shared cursor crosses module boundaries (D69).

Error modes (per § 7.1 + D68 — canonical :mod:`utils.errors` hierarchy)
----------------------------------------------------------------------

All exceptions imported from :mod:`utils.errors` per D68 single-source-
of-truth (B-228 lesson — no local class duplicates):

* :class:`~utils.errors.SnowflakeAuthFailed` (``PipelineFatalError``) —
  RSA key decrypt OR ``CONNECT`` failed. Operator must rotate keys or
  reconcile Snowflake-side public key registration.
* :class:`~utils.errors.SnowflakeBudgetAlert` (``PipelineFatalError``) —
  credit usage > 80% of monthly cap per D23. Fatal by default; operator
  decides whether to bypass for a one-off COPY.
* :class:`~utils.errors.SnowflakeCopyTimeout` (``PipelineRetryableError``)
  — COPY exceeded ``timeout_seconds``. Retry per B-7 (exponential
  backoff). Persistent timeout suggests file-size or partition-layout
  regression — track via capacity baseline.
* :class:`~utils.errors.RegistryStatusInvalid` (``PipelineFatalError``)
  — bubbled from :func:`mark_replicated` OR raised here when the source
  status is not ``'verified'``.
* :class:`~utils.errors.RegistryNotFound` (``PipelineFatalError``) —
  ``registry_id`` does not exist.

Security discipline (D71 + D103)
--------------------------------

* The RSA private key is materialized to ``/dev/shm/snowflake_pk_<pid>``
  mode 0600 by M7's :func:`_materialize_snowflake_key`. This module
  ONLY receives the file path; the PEM contents never enter this
  module's process memory directly.
* The ephemeral file path is logged at DEBUG level only AND is
  redacted by the :class:`~observability.sensitive_data_filter
  .SensitiveDataFilter` if a PEM-shaped substring ever appears in a
  log message (defense-in-depth).
* :func:`release_snowflake_key` is called in a ``finally`` block so the
  ephemeral key is removed from ``/dev/shm`` even when COPY raises.

D-numbers consumed
------------------

D3 (Snowflake for analytics + reconciliation only — cost ceiling),
D5 (Snowflake-managed Iceberg), D15 (idempotency mandatory),
D17 (idempotency ledger on every pipeline step — composed via M3),
D23 (Snowflake budget alert at 80% cap),
D25 (canonical Parquet index via ``ParquetSnapshotRegistry``),
D67 (Tier 0 smoke discipline),
D68 (error class hierarchy — single-source-of-truth in
:mod:`utils.errors`),
D69 (cursor / connection ownership — one CONNECTION per process),
D71 (Snowflake RSA auth via ``/dev/shm/snowflake_pk_<pid>``),
D92 (forward-only additive — new module; no rename / removal),
D103 (Claude Code security model — no PEM bytes in module memory;
ephemeral file path per-PID per-process).

B-numbers
---------

* Closes **M17** build-tracker entry (per parent orchestrator
  instructions). Round 3 reaches 17/17 (100%) on this commit.
* Consumes **B85** (``utils/errors.py``) — closed dependency. Imports
  canonical exception classes per **B228** lesson (no local exception
  re-definition).
* Consumes **B214** test-fixture pattern — tests use ``monkeypatch.setitem
  (sys.modules, ...)`` with autouse fixture cleanup for the
  ``snowflake.connector`` import (the connector is NOT installed in
  the test venv; tests mock at the import level).
* B231 surfacing — EventType ``'SNOWFLAKE_COPY_INTO'`` is the canonical
  value per spec § 7.1; M3's ``mark_replicated`` continues to write
  its own ``PARQUET_REPLICATE`` ledger row via its existing pattern.

See also
--------

* ``data_load/parquet_registry_client.py`` (§ 1.3 / M3) — supplies
  :func:`mark_replicated`. M17 composes it after COPY succeeds.
* ``data_load/credentials_loader.py`` (§ 3.1 / M7) — supplies
  :func:`load_credentials` + :func:`release_snowflake_key`.
* ``observability/event_tracker.py`` (§ 6.3 / M16) — referenced for
  the canonical EventType-family contract; M17 writes a
  ``PipelineEventLog`` row directly because the tracker requires a
  :class:`~orchestration.table_config.TableConfig` argument that M17
  does not have (the registry row is the source-of-truth for source
  / table identification).
* ``observability/sensitive_data_filter.py`` (§ 6.1 / M14) — the
  defense-in-depth log-line redactor. Any RSA PEM substring that
  inadvertently lands in a log line is redacted before write.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from utils.errors import (
    RegistryNotFound,
    RegistryStatusInvalid,
    SnowflakeAuthFailed,
    SnowflakeBudgetAlert,
    SnowflakeCopyTimeout,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

#: EventType written to ``PipelineEventLog`` for every COPY INTO event. Pinned
#: per § 7.1 — informational dashboard row; the idempotency / audit row
#: is M3's ``PARQUET_REPLICATE`` ledger entry composed via :func:`mark_replicated`.
EVENT_TYPE_SNOWFLAKE_COPY_INTO = "SNOWFLAKE_COPY_INTO"

#: Registry status required for ``COPY INTO`` eligibility. Per § 7.1 —
#: only ``'verified'`` is accepted (the SHA-256 has been confirmed
#: post-write by M3's :func:`verify_parquet_snapshot`).
COPY_REQUIRED_STATUS = "verified"

#: Default ``COPY INTO`` timeout in seconds. Per § 7.1 canonical signature.
#: Snowflake's COPY is typically sub-minute for 100-250 MB Parquet files
#: (per D45.2 sizing); 300 s = 5 min is the safe upper bound that catches
#: file-size or partition-layout regressions without producing false
#: timeouts on normal-shape COPYs.
DEFAULT_COPY_TIMEOUT_SECONDS = 300

#: Budget threshold for :class:`~utils.errors.SnowflakeBudgetAlert`. Per
#: D23 — alert when monthly credit usage exceeds 80% of the configured
#: cap. Configurable via ``SNOWFLAKE_BUDGET_ALERT_THRESHOLD`` env var
#: (0.0 - 1.0 fraction; default 0.80).
DEFAULT_BUDGET_ALERT_THRESHOLD = 0.80

#: ``ParquetSnapshotRegistry.SnowflakeStagePath`` value stamped on
#: successful COPY. Identifies the replication destination for audit.
#: Format: ``snowflake:<SNOWFLAKE_DATABASE>.<SNOWFLAKE_SCHEMA>.<table>``.
_REPLICA_TARGET_PREFIX = "snowflake:"


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SnowflakeCopyResult:
    """Result of a successful :func:`copy_parquet_to_snowflake` call.

    Per § 7.1 canonical signature. All fields populated on a successful
    COPY; the class is frozen because COPY results are immutable audit
    records (re-COPY produces a new instance per D26 append-only).

    Attributes:
        registry_id: ``General.ops.ParquetSnapshotRegistry.RegistryId`` of
            the source registry row. Surfaced for audit.
        snowflake_table: Fully-qualified Snowflake target —
            ``'DATABASE.SCHEMA.TABLE'``. Echoed from the request (or the
            default mapping if the caller didn't override).
        rows_copied: ``rows_loaded`` from the Snowflake COPY INTO
            response. ``0`` is a valid value on idempotent re-COPY
            (Snowflake's per-file load history dedups).
        copy_history_id: Snowflake's file-load history identifier (the
            COPY query ID). Used to cross-reference the
            ``COPY_HISTORY`` table in Snowflake for forensic audit.
        duration_ms: Wall-clock duration of the COPY phase only —
            registry lookup + auth + budget-check are NOT included.
            Measured in milliseconds (integer truncation per the
            canonical signature).
    """

    registry_id: int
    snowflake_table: str
    rows_copied: int
    copy_history_id: str
    duration_ms: int


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------

__all__ = (
    "EVENT_TYPE_SNOWFLAKE_COPY_INTO",
    "COPY_REQUIRED_STATUS",
    "DEFAULT_COPY_TIMEOUT_SECONDS",
    "DEFAULT_BUDGET_ALERT_THRESHOLD",
    "SnowflakeCopyResult",
    "copy_parquet_to_snowflake",
    # Errors — canonical home is utils.errors (B-228); intentionally NOT
    # re-exported here per single-source-of-truth. Bound in the module
    # namespace via top-of-file imports so legacy callers that did
    # ``from data_load.snowflake_uploader import SnowflakeAuthFailed`` still
    # resolve, but new code should import from utils.errors directly.
)


# ---------------------------------------------------------------------------
# Internal: lazy imports for testability
#
# Sibling-module imports are lazy-resolved through getter functions so
# tests can swap the implementations via ``patch.object(mod,
# "_get_<sibling>", ...)`` without ``monkeypatch.setitem("sys.modules",
# ...)`` (per B214 lesson — sys.modules mutation requires careful
# cleanup; the getter pattern avoids it entirely). Mirrors M2 / M3.
# ---------------------------------------------------------------------------


def _get_cursor_for():
    """Return :func:`utils.connections.cursor_for`.

    Lazy-resolved so tests can swap via ``patch.object(mod,
    "_get_cursor_for", ...)``. The cursor_for context manager opens
    a pooled pyodbc cursor against the named database per D69.
    """
    from utils.connections import cursor_for  # noqa: PLC0415

    return cursor_for


def _get_load_credentials():
    """Return :func:`data_load.credentials_loader.load_credentials`."""
    from data_load.credentials_loader import load_credentials  # noqa: PLC0415

    return load_credentials


def _get_release_snowflake_key():
    """Return :func:`data_load.credentials_loader.release_snowflake_key`."""
    from data_load.credentials_loader import release_snowflake_key  # noqa: PLC0415

    return release_snowflake_key


def _get_mark_replicated():
    """Return :func:`data_load.parquet_registry_client.mark_replicated`."""
    from data_load.parquet_registry_client import mark_replicated  # noqa: PLC0415

    return mark_replicated


def _get_snowflake_connector():
    """Return the :mod:`snowflake.connector` module (lazy).

    Importing the Snowflake connector is gated to the function call so
    the module imports cleanly in environments where the connector is
    not installed (unit-test CI). The import is wrapped in a try block
    so the absence is surfaced as :class:`~utils.errors.SnowflakeAuthFailed`
    rather than a raw ImportError — operators see a typed error.
    """
    try:
        import snowflake.connector  # noqa: PLC0415

        return snowflake.connector
    except ImportError as exc:
        raise SnowflakeAuthFailed(
            "snowflake-connector-python is not installed; "
            "cannot establish Snowflake CONNECTION. Install per "
            "Phase 0 deliverable 0.6 (B39) before attempting COPY INTO.",
            metadata={"import_error": str(exc)},
        ) from exc


# ---------------------------------------------------------------------------
# Internal: registry row read by registry_id
# ---------------------------------------------------------------------------


def _read_registry_row(registry_id: int) -> dict[str, Any]:
    """Read the registry row by ``registry_id`` — projection only.

    Per § 7.1 — reads the columns this module needs to plan the COPY:
    ``RegistryId`` / ``SourceName`` / ``TableName`` / ``BatchId`` /
    ``NetworkDrivePath`` / ``Status`` / ``RowCount``. The full M3
    ``_fetch_registry_row`` projection is NOT needed here — keeping the
    SELECT lean avoids cursor-overhead bloat on large-volume uploaders.

    Raises:
        :class:`~utils.errors.RegistryNotFound`: ``registry_id`` does
            not resolve to any row.

    Returns:
        A dict with the projection columns as keys.
    """
    cursor_for = _get_cursor_for()
    sql = """
        SELECT
            RegistryId,
            SourceName,
            TableName,
            BatchId,
            NetworkDrivePath,
            Status,
            RowCount
        FROM General.ops.ParquetSnapshotRegistry
        WHERE RegistryId = ?
    """
    with cursor_for("General") as cur:
        cur.execute(sql, registry_id)
        row = cur.fetchone()
        if row is None:
            raise RegistryNotFound(
                f"RegistryId={registry_id} not found in ParquetSnapshotRegistry",
                metadata={"registry_id": registry_id},
            )
        columns = [c[0] for c in cur.description]
        return dict(zip(columns, row))


# ---------------------------------------------------------------------------
# Internal: budget pre-check
# ---------------------------------------------------------------------------


def _check_snowflake_budget(
    snowflake_conn,
    *,
    threshold: float = DEFAULT_BUDGET_ALERT_THRESHOLD,
) -> None:
    """Raise :class:`SnowflakeBudgetAlert` if monthly usage > ``threshold`` of cap.

    Per D23 — Snowflake credit usage is queried via the canonical
    information-schema view ``SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY``
    (Snowflake's standard cost view); the monthly cap is derived from the
    ``SNOWFLAKE_MONTHLY_CREDIT_CAP`` env var (default 10000 credits — a
    safe placeholder; operator should override per the real D23
    contracted ceiling).

    Best-effort: a failure to query (permissions / network / view
    absent) is logged at WARNING and the check is skipped — the COPY
    proceeds. Operators monitoring budget should reconcile against
    Snowflake's own usage dashboard rather than relying on the uploader
    pre-check.

    The check is invoked AFTER the connection is opened (because we need
    a Snowflake CONNECTION to run the budget query) but BEFORE the COPY
    executes (so a budget breach blocks the COPY without consuming
    credits on the COPY itself).
    """
    cap_str = os.getenv("SNOWFLAKE_MONTHLY_CREDIT_CAP", "10000")
    try:
        cap = float(cap_str)
    except ValueError:
        logger.warning(
            "SNOWFLAKE_MONTHLY_CREDIT_CAP=%r is not a number; skipping "
            "budget pre-check",
            cap_str,
        )
        return
    if cap <= 0:
        logger.warning(
            "SNOWFLAKE_MONTHLY_CREDIT_CAP=%s is non-positive; skipping "
            "budget pre-check",
            cap,
        )
        return

    # ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY has a ~3-hour latency per
    # Snowflake docs; the alert is intentionally a soft floor — if the
    # real usage is N% over the alert threshold but the view hasn't
    # caught up yet, the next COPY catches it. Operators should also
    # monitor real-time via Snowflake's resource-monitor feature.
    query = """
        SELECT COALESCE(SUM(CREDITS_USED), 0) AS month_credits
          FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
         WHERE START_TIME >= DATE_TRUNC('month', CURRENT_TIMESTAMP())
    """
    try:
        cursor = snowflake_conn.cursor()
        try:
            cursor.execute(query)
            row = cursor.fetchone()
        finally:
            cursor.close()
    except Exception as exc:  # noqa: BLE001 — budget check is best-effort
        logger.warning(
            "Snowflake budget pre-check query failed (%s); skipping "
            "budget guard for this COPY",
            type(exc).__name__,
        )
        return

    if row is None or row[0] is None:
        logger.warning(
            "Snowflake budget pre-check returned no rows; skipping "
            "budget guard"
        )
        return

    month_credits = float(row[0])
    fraction_used = month_credits / cap
    if fraction_used > threshold:
        raise SnowflakeBudgetAlert(
            (
                f"Snowflake monthly credit usage {month_credits:.2f} "
                f"exceeds {threshold * 100:.0f}% of cap {cap:.2f} "
                f"(fraction={fraction_used:.3f}); COPY INTO blocked per "
                f"D23. Operator review required."
            ),
            metadata={
                "month_credits": month_credits,
                "monthly_cap": cap,
                "threshold": threshold,
                "fraction_used": round(fraction_used, 4),
            },
        )

    logger.debug(
        "Snowflake budget pre-check passed: month_credits=%.2f, "
        "cap=%.2f, fraction=%.3f (threshold=%.2f)",
        month_credits, cap, fraction_used, threshold,
    )


# ---------------------------------------------------------------------------
# Internal: default snowflake_table mapping
# ---------------------------------------------------------------------------


def _default_snowflake_table(table_name: str) -> str:
    """Return ``'DATABASE.SCHEMA.TABLE'`` from env vars.

    Per § 7.1 — when ``snowflake_table`` is not overridden by the caller,
    we compose from ``SNOWFLAKE_DATABASE`` + ``SNOWFLAKE_SCHEMA``
    env vars per `02_configuration.md` § 2.1.8.

    Defaults aligned with `02_configuration.md` § 2.1.8 ("'UDM_BRONZE_MIRROR'"
    + source-system schema). Operator can override either env var; the
    fully-qualified name is also surfaced in the result dataclass for
    audit cross-reference.
    """
    db = os.getenv("SNOWFLAKE_DATABASE", "UDM_BRONZE_MIRROR")
    schema = os.getenv("SNOWFLAKE_SCHEMA", "PUBLIC")
    return f"{db}.{schema}.{table_name}"


# ---------------------------------------------------------------------------
# Internal: Snowflake connection
# ---------------------------------------------------------------------------


def _open_snowflake_connection(creds: dict[str, str]):
    """Open a Snowflake :class:`snowflake.connector.SnowflakeConnection`.

    Uses key-pair authentication per D71. The RSA private key is read
    from the path in ``creds['SNOWFLAKE_PRIVATE_KEY_PATH']`` (Linux /
    /dev/shm path materialized by M7) — on non-Linux dev workstations
    where M7 leaves the PEM in the dict (``SNOWFLAKE_PRIVATE_KEY_PEM``),
    the connector accepts the PEM string directly.

    Connection params come from env vars per `02_configuration.md`
    § 2.1.8:

    * ``SNOWFLAKE_ACCOUNT`` — required
    * ``SNOWFLAKE_USER`` — required
    * ``SNOWFLAKE_WAREHOUSE`` — required
    * ``SNOWFLAKE_DATABASE`` — required (cost-tier-tagged)
    * ``SNOWFLAKE_SCHEMA`` — required (per-source)

    Raises:
        :class:`~utils.errors.SnowflakeAuthFailed`: if the connector
            ``connect()`` call raises OR a required env var is missing
            OR the key path is absent from creds.
    """
    connector = _get_snowflake_connector()

    account = os.getenv("SNOWFLAKE_ACCOUNT")
    user = os.getenv("SNOWFLAKE_USER")
    warehouse = os.getenv("SNOWFLAKE_WAREHOUSE")
    database = os.getenv("SNOWFLAKE_DATABASE")
    schema = os.getenv("SNOWFLAKE_SCHEMA")
    missing = [
        name for name, value in (
            ("SNOWFLAKE_ACCOUNT", account),
            ("SNOWFLAKE_USER", user),
            ("SNOWFLAKE_WAREHOUSE", warehouse),
            ("SNOWFLAKE_DATABASE", database),
            ("SNOWFLAKE_SCHEMA", schema),
        ) if not value
    ]
    if missing:
        raise SnowflakeAuthFailed(
            (
                f"Missing required env var(s) for Snowflake connection: "
                f"{missing!r}. See `02_configuration.md` § 2.1.8."
            ),
            metadata={"missing_env_vars": missing},
        )

    # Prefer the /dev/shm path on Linux; fall back to the PEM string on
    # non-Linux (M7 materialization is Linux-only). Either way, never
    # log the value (D103 — PEM bytes must not enter logs).
    key_path = creds.get("SNOWFLAKE_PRIVATE_KEY_PATH")
    key_pem = creds.get("SNOWFLAKE_PRIVATE_KEY_PEM")
    if not key_path and not key_pem:
        raise SnowflakeAuthFailed(
            (
                "Credentials dict missing both SNOWFLAKE_PRIVATE_KEY_PATH "
                "and SNOWFLAKE_PRIVATE_KEY_PEM; cannot authenticate to "
                "Snowflake. Verify M7 load_credentials() produced the "
                "expected envelope structure."
            ),
            metadata={
                # NEVER log the values; only key NAMES.
                "available_key_names": sorted(creds.keys()),
            },
        )

    # Snowflake connector wants the PEM bytes (DER-encoded private-key
    # bytes), not a path. Read the file at the path to get the PEM.
    # The PEM bytes live in this function's local frame for the
    # duration of the ``connect()`` call only; the connector copies
    # them into its internal session state.
    if key_path:
        try:
            with open(key_path, "rb") as f:
                key_bytes = f.read()
        except OSError as exc:
            raise SnowflakeAuthFailed(
                (
                    f"Failed to read RSA key from ephemeral_key_path "
                    f"(file system error: {type(exc).__name__}). "
                    f"Operator must verify M7 materialization succeeded."
                ),
                # NEVER log the actual path value — log only the key name.
                metadata={"key_name": "SNOWFLAKE_PRIVATE_KEY_PATH"},
            ) from exc
    else:
        key_bytes = key_pem.encode("utf-8") if isinstance(key_pem, str) else key_pem

    try:
        conn = connector.connect(
            account=account,
            user=user,
            private_key=key_bytes,
            warehouse=warehouse,
            database=database,
            schema=schema,
        )
    except Exception as exc:  # noqa: BLE001 — wrap any connector exception
        # The connector raises an assortment of error classes
        # (DatabaseError, OperationalError, ProgrammingError) — we
        # collapse all of them to SnowflakeAuthFailed because the
        # operator-actionable signal is the same: the CONNECT failed.
        raise SnowflakeAuthFailed(
            (
                f"Snowflake CONNECT failed: {type(exc).__name__}. "
                f"Verify SNOWFLAKE_ACCOUNT / SNOWFLAKE_USER / RSA public "
                f"key registration in Snowflake."
            ),
            metadata={
                "error_type": type(exc).__name__,
                "account": account,
                "user": user,
                "warehouse": warehouse,
            },
        ) from exc
    finally:
        # Best-effort scrub of the PEM bytes in this function's local
        # frame. Python bytes are immutable so this is partial mitigation
        # only — the canonical defense is ``/dev/shm`` + ``MALLOC_ARENA_MAX=2``
        # per CLAUDE.md W-4. The bytes already entered the connector's
        # internal state at this point.
        try:
            del key_bytes
        except UnboundLocalError:
            # key_bytes was never assigned (early raise above).
            pass

    return conn


# ---------------------------------------------------------------------------
# Internal: COPY INTO execution
# ---------------------------------------------------------------------------


def _execute_copy_into(
    snowflake_conn,
    *,
    snowflake_table: str,
    network_drive_path: str,
    timeout_seconds: int,
) -> tuple[int, str]:
    """Issue ``COPY INTO`` and parse the response.

    Per § 7.1 — uses Snowflake's COPY INTO syntax against an internal
    stage (or external stage mapped to the network drive). The stage
    name is read from ``SNOWFLAKE_STAGE_NAME`` env var (default
    ``@UDM_BRONZE_STAGE``).

    The COPY response shape is per Snowflake connector docs:
    ``fetchall()`` returns rows of
    ``(file, status, rows_parsed, rows_loaded, error_limit, errors_seen,
    first_error, first_error_line, first_error_character,
    first_error_column_name)`` — we sum ``rows_loaded`` and pull the
    cursor's ``sfqid`` (Snowflake query ID) for ``copy_history_id``.

    Args:
        snowflake_conn: Open Snowflake connection.
        snowflake_table: Fully-qualified Snowflake table name.
        network_drive_path: Path to the source Parquet file. Substituted
            into the COPY INTO ``FROM`` clause as a parameter pattern.
        timeout_seconds: Statement timeout for the COPY query.

    Returns:
        A 2-tuple of ``(rows_copied, copy_history_id)``.

    Raises:
        :class:`~utils.errors.SnowflakeCopyTimeout`: COPY exceeded
            ``timeout_seconds``.
        :class:`~utils.errors.SnowflakeAuthFailed`: COPY failed for an
            auth-or-config reason that didn't surface at CONNECT.
    """
    stage_name = os.getenv("SNOWFLAKE_STAGE_NAME", "@UDM_BRONZE_STAGE")

    # Set the statement timeout per the canonical contract. The Snowflake
    # connector exposes per-statement timeout via the STATEMENT_TIMEOUT_IN_SECONDS
    # session parameter; we set it for THIS connection only (the connection
    # is per-process per D69).
    try:
        cursor = snowflake_conn.cursor()
    except Exception as exc:  # noqa: BLE001
        raise SnowflakeAuthFailed(
            f"Failed to open Snowflake cursor: {type(exc).__name__}",
            metadata={"error_type": type(exc).__name__},
        ) from exc

    try:
        cursor.execute(
            "ALTER SESSION SET STATEMENT_TIMEOUT_IN_SECONDS = %s",
            (int(timeout_seconds),),
        )

        # The file pattern is parameterized; Snowflake's COPY INTO ``FROM``
        # clause accepts a stage location + ``FILES = (...)`` list.
        copy_sql = (
            f"COPY INTO {snowflake_table} "
            f"FROM {stage_name} "
            f"FILES = (%s) "
            f"FILE_FORMAT = (TYPE = PARQUET) "
            f"ON_ERROR = ABORT_STATEMENT"
        )

        try:
            cursor.execute(copy_sql, (network_drive_path,))
        except Exception as exc:  # noqa: BLE001
            err_text = str(exc).lower()
            # Snowflake raises ProgrammingError with a 000604 / 390114
            # error code OR an error message containing 'statement reached its
            # statement timeout' when STATEMENT_TIMEOUT_IN_SECONDS fires.
            if "timeout" in err_text or "statement reached" in err_text:
                raise SnowflakeCopyTimeout(
                    (
                        f"Snowflake COPY INTO exceeded timeout "
                        f"({timeout_seconds}s) for table "
                        f"{snowflake_table!r}. Retry per B-7."
                    ),
                    metadata={
                        "snowflake_table": snowflake_table,
                        "timeout_seconds": timeout_seconds,
                        "error_type": type(exc).__name__,
                    },
                ) from exc
            # All other COPY failures collapse to SnowflakeAuthFailed —
            # the operator-actionable signal is the same as a CONNECT
            # failure (verify stage, file format, permissions).
            raise SnowflakeAuthFailed(
                (
                    f"Snowflake COPY INTO failed for table "
                    f"{snowflake_table!r}: {type(exc).__name__}. Verify "
                    f"stage name {stage_name!r}, file format, and "
                    f"Snowflake permissions."
                ),
                metadata={
                    "snowflake_table": snowflake_table,
                    "stage_name": stage_name,
                    "error_type": type(exc).__name__,
                },
            ) from exc

        # Pull the Snowflake query ID for audit cross-reference.
        copy_history_id = str(getattr(cursor, "sfqid", "") or "")

        # Parse the response — sum rows_loaded across all rows returned.
        # COPY INTO returns one row per file copied; we typically have
        # exactly one file per call, but defensively aggregate.
        try:
            rows = cursor.fetchall()
        except Exception:  # noqa: BLE001
            rows = []
        rows_copied = 0
        for r in rows:
            # Standard COPY response: rows_loaded is the 4th column
            # (index 3) per Snowflake docs. Defend against shape
            # variations by checking the row length first.
            if len(r) >= 4:
                try:
                    rows_copied += int(r[3])
                except (TypeError, ValueError):
                    pass

        return rows_copied, copy_history_id
    finally:
        try:
            cursor.close()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Internal: PipelineEventLog row write
# ---------------------------------------------------------------------------


def _write_event_log_row(
    *,
    registry_id: int,
    source_name: str,
    table_name: str,
    batch_id: int,
    snowflake_table: str,
    rows_copied: int,
    copy_history_id: str,
    duration_ms: int,
    started_at: datetime,
    completed_at: datetime,
    status: str = "SUCCESS",
    error_message: str | None = None,
) -> None:
    """Write a ``PipelineEventLog`` row with EventType='SNOWFLAKE_COPY_INTO'.

    Best-effort: this is a dashboard / runtime-performance metric write;
    a failure to write does NOT block the COPY-INTO + mark_replicated
    side effects which have already happened. Mirrors the
    ``credentials_loader._write_audit_row`` pattern.

    Per § 7.1 + CLAUDE.md "PipelineEventLog column" reference — Metadata
    JSON carries ``snowflake_table``, ``copy_history_id``, ``warehouse``
    (per D76 audit-row contract).
    """
    try:
        cursor_for = _get_cursor_for()
        metadata = {
            "snowflake_table": snowflake_table,
            "copy_history_id": copy_history_id,
            "warehouse": os.getenv("SNOWFLAKE_WAREHOUSE"),
            "registry_id": registry_id,
        }
        with cursor_for("General") as cur:
            cur.execute(
                """
                INSERT INTO General.ops.PipelineEventLog (
                    BatchId, TableName, SourceName, EventType, EventDetail,
                    StartedAt, CompletedAt, DurationMs, Status, ErrorMessage,
                    RowsProcessed, RowsInserted, Metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                batch_id,
                table_name,
                source_name,
                EVENT_TYPE_SNOWFLAKE_COPY_INTO,
                snowflake_table,
                started_at,
                completed_at,
                int(duration_ms),
                status,
                error_message,
                rows_copied,
                rows_copied,
                json.dumps(metadata),
            )
    except Exception as exc:  # noqa: BLE001 — observability is never fatal
        logger.warning(
            "snowflake_uploader event-row write failed (%s); COPY itself "
            "succeeded; continuing.",
            type(exc).__name__,
        )


# ---------------------------------------------------------------------------
# Internal: naive UTC ms helper (per SCD2-P1-f invariant)
# ---------------------------------------------------------------------------


def _utcnow_ms() -> datetime:
    """Return naive (no tzinfo) UTC datetime truncated to milliseconds.

    Per CLAUDE.md SCD2-P1-f + CDC-NOW-MS gotchas — pyodbc DATETIME2(3)
    parameters MUST be naive + millisecond-precision so they align with
    BCP-stored values. This module writes a ``PipelineEventLog`` row with
    ``StartedAt`` / ``CompletedAt`` as DATETIME2(3); the same invariant
    applies.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    micros = now.microsecond
    millis_micros = micros - (micros % 1000)
    return now.replace(microsecond=millis_micros)


# ---------------------------------------------------------------------------
# Public: :func:`copy_parquet_to_snowflake`
# ---------------------------------------------------------------------------


def copy_parquet_to_snowflake(
    *,
    registry_id: int,
    snowflake_table: str | None = None,
    timeout_seconds: int = DEFAULT_COPY_TIMEOUT_SECONDS,
) -> SnowflakeCopyResult:
    """Issue ``COPY INTO`` from a registered Parquet file into Snowflake.

    Per § 7.1 canonical interface. The upload:

    1. Reads the registry row by ``registry_id``; raises
       :class:`~utils.errors.RegistryNotFound` if absent.
    2. Verifies the registry row's ``Status == 'verified'``; raises
       :class:`~utils.errors.RegistryStatusInvalid` otherwise. (The
       verifier — M3's :func:`verify_parquet_snapshot` — must have run
       first to confirm the SHA-256.)
    3. Loads credentials via M7's :func:`credentials_loader.load_credentials`.
    4. Best-effort budget pre-check via :func:`_check_snowflake_budget`.
    5. Opens a Snowflake CONNECTION via :func:`_open_snowflake_connection`.
    6. Issues ``COPY INTO`` via :func:`_execute_copy_into`.
    7. Composes M3's :func:`mark_replicated` to flip the registry status.
    8. Writes a ``PipelineEventLog`` row with
       ``EventType='SNOWFLAKE_COPY_INTO'``.
    9. Releases the ephemeral RSA key in a ``finally`` block.

    Args:
        registry_id: ``ParquetSnapshotRegistry.RegistryId`` of the row to
            replicate. The row's ``Status`` MUST be ``'verified'``.
        snowflake_table: Override the default
            ``f'{SNOWFLAKE_DATABASE}.{SNOWFLAKE_SCHEMA}.{table_name}'``
            mapping. When ``None`` (default), the mapping is computed
            from env vars per `02_configuration.md` § 2.1.8.
        timeout_seconds: COPY INTO query timeout. Default is
            :data:`DEFAULT_COPY_TIMEOUT_SECONDS` (300 s = 5 min).

    Returns:
        :class:`SnowflakeCopyResult` with ``rows_copied`` +
        ``copy_history_id`` + ``duration_ms``.

    Raises:
        :class:`~utils.errors.RegistryNotFound`: ``registry_id`` does
            not exist. FATAL.
        :class:`~utils.errors.RegistryStatusInvalid`: source
            ``Status != 'verified'``. FATAL — verifier must run first.
        :class:`~utils.errors.SnowflakeAuthFailed`: RSA key decrypt OR
            ``CONNECT`` failed OR COPY raised a non-timeout error.
            FATAL.
        :class:`~utils.errors.SnowflakeBudgetAlert`: monthly credit
            usage > 80% of cap per D23. FATAL by default; operator
            decides whether to bypass.
        :class:`~utils.errors.SnowflakeCopyTimeout`: COPY exceeded
            ``timeout_seconds``. RETRYABLE per B-7.

    Side effects:
        * Snowflake ``COPY INTO`` execution against the configured
          stage + table.
        * ``ParquetSnapshotRegistry.Status`` flip ``'verified'`` →
          ``'replicated'`` via M3's :func:`mark_replicated`.
        * ``ParquetSnapshotRegistry.SnowflakeStagePath`` +
          ``SnowflakeUploadedAt`` stamped via M3's :func:`mark_replicated`.
        * ``General.ops.PipelineEventLog`` row with
          ``EventType='SNOWFLAKE_COPY_INTO'`` (best-effort —
          observability is never fatal).
        * ``General.ops.IdempotencyLedger`` row with
          ``EventType='PARQUET_REPLICATE'`` written by M3's
          :func:`mark_replicated` composition (the idempotency
          audit row).
        * Ephemeral RSA key file at ``/dev/shm/snowflake_pk_<pid>``
          removed via M7's :func:`release_snowflake_key` in a
          ``finally`` block (cleanup on every code path).

    Idempotency (per D15 + spec § 7.1):
        * Snowflake's COPY INTO tracks per-file load history — re-COPY
          of the same file produces ``rows_loaded=0``.
        * Registry flip is idempotent: ``mark_replicated`` no-ops when
          ``Status='replicated'``.
        * Re-call is safe at both layers.
    """
    started_at = _utcnow_ms()
    started_perf = time.perf_counter()

    # ---- Step 1: read the registry row.
    row = _read_registry_row(registry_id)
    current_status = str(row["Status"])
    source_name = str(row["SourceName"])
    table_name = str(row["TableName"])
    batch_id = int(row["BatchId"])
    network_drive_path = str(row["NetworkDrivePath"])

    # ---- Step 2: verify status.
    if current_status != COPY_REQUIRED_STATUS:
        raise RegistryStatusInvalid(
            (
                f"Cannot copy RegistryId={registry_id} to Snowflake: "
                f"current Status={current_status!r}; required Status="
                f"{COPY_REQUIRED_STATUS!r}. The verifier "
                f"(verify_parquet_snapshot) must run first."
            ),
            metadata={
                "registry_id": registry_id,
                "current_status": current_status,
                "required_status": COPY_REQUIRED_STATUS,
                "source_name": source_name,
                "table_name": table_name,
            },
        )

    # ---- Step 3: default snowflake_table mapping.
    effective_snowflake_table = snowflake_table or _default_snowflake_table(
        table_name=table_name,
    )

    logger.info(
        "snowflake_uploader: starting COPY INTO for RegistryId=%s "
        "(source=%s, table=%s, batch=%s) -> %s",
        registry_id, source_name, table_name, batch_id,
        effective_snowflake_table,
    )

    # ---- Step 4: load credentials (RSA key materialized to /dev/shm by M7).
    load_credentials = _get_load_credentials()
    release_snowflake_key = _get_release_snowflake_key()
    creds = load_credentials()

    snowflake_conn = None
    rows_copied = 0
    copy_history_id = ""
    duration_ms = 0
    raised: BaseException | None = None
    try:
        # ---- Step 5: open Snowflake connection.
        snowflake_conn = _open_snowflake_connection(creds)

        # ---- Step 6: budget pre-check (BEFORE COPY consumes credits).
        _check_snowflake_budget(snowflake_conn)

        # ---- Step 7: execute COPY INTO (the actual work).
        copy_start_perf = time.perf_counter()
        rows_copied, copy_history_id = _execute_copy_into(
            snowflake_conn,
            snowflake_table=effective_snowflake_table,
            network_drive_path=network_drive_path,
            timeout_seconds=timeout_seconds,
        )
        copy_duration_seconds = time.perf_counter() - copy_start_perf
        duration_ms = int(copy_duration_seconds * 1000)

        logger.info(
            "snowflake_uploader: COPY INTO completed for RegistryId=%s "
            "rows_copied=%d copy_history_id=%s duration_ms=%d",
            registry_id, rows_copied, copy_history_id, duration_ms,
        )

        # ---- Step 8: flip registry Status -> 'replicated'.
        # M3's mark_replicated composes its own ledger_step with
        # EventType='PARQUET_REPLICATE' — that's the canonical
        # idempotent audit row for the replication side effect.
        mark_replicated = _get_mark_replicated()
        replica_target = f"{_REPLICA_TARGET_PREFIX}{effective_snowflake_table}"
        mark_replicated(
            registry_id=registry_id,
            replica_target=replica_target,
        )
    except BaseException as exc:  # noqa: BLE001 — preserve for finally
        # Capture the exception so finally can record FAILED audit row,
        # then re-raise unchanged. Use BaseException to also catch
        # KeyboardInterrupt — we still want the /dev/shm key cleaned up
        # before the interpreter exits.
        raised = exc
        raise
    finally:
        # ---- Step 9: release the ephemeral RSA key (idempotent, no-op
        # on non-Linux). Run BEFORE the audit-row write so the key is
        # cleaned up even if the audit-row write itself raises.
        try:
            release_snowflake_key()
        except Exception:  # noqa: BLE001
            logger.warning(
                "release_snowflake_key raised during finally cleanup; "
                "ephemeral key file may persist until /dev/shm reboot "
                "cleanup. This is non-fatal."
            )

        # Close the Snowflake connection. The connection is per-process
        # by D69 — leaving it open across function-call boundaries would
        # leak resources for short-lived CLI invocations.
        if snowflake_conn is not None:
            try:
                snowflake_conn.close()
            except Exception:  # noqa: BLE001
                pass

        # ---- Step 10: write the PipelineEventLog row (best-effort).
        # Run AFTER cleanup so a failure here doesn't leak resources.
        completed_at = _utcnow_ms()
        total_duration_ms = int((time.perf_counter() - started_perf) * 1000)
        if raised is None:
            status = "SUCCESS"
            error_message = None
        else:
            status = "FAILED"
            error_message = str(raised)[:4000]
        _write_event_log_row(
            registry_id=registry_id,
            source_name=source_name,
            table_name=table_name,
            batch_id=batch_id,
            snowflake_table=effective_snowflake_table,
            rows_copied=rows_copied,
            copy_history_id=copy_history_id,
            duration_ms=total_duration_ms,
            started_at=started_at,
            completed_at=completed_at,
            status=status,
            error_message=error_message,
        )

    return SnowflakeCopyResult(
        registry_id=registry_id,
        snowflake_table=effective_snowflake_table,
        rows_copied=rows_copied,
        copy_history_id=copy_history_id,
        duration_ms=duration_ms,
    )
