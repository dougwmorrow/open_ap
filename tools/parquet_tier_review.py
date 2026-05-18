"""Round 4 § 3.1 — ``tools/parquet_tier_review.py``.

Per **Round 4 § 3.1** at ``docs/migration/phase1/04_tools.md`` (canonical
spec) + **Round 3 § 1.3** ``data_load/parquet_registry_client.py``
canonical 7-state registry lifecycle.

Walk all ``General.ops.ParquetSnapshotRegistry`` rows in a given Status;
report ages, sizes, and recommended next transition. Operator-facing
aid for the registry status state machine. In ``--apply`` mode, drives
the per-row transition (``mark_replicated`` / ``mark_archived`` /
``mark_purged``) for every row that matches the filter.

What this tool does
-------------------

1. SELECT rows from ``General.ops.ParquetSnapshotRegistry`` filtered by
   ``--from-status`` (default ``'verified'``). Optional ``--age-days``
   bounds rows by ``LastVerifiedAt`` (or ``CreatedAt`` for
   ``Status='created'``) older than N days.
2. Render the per-row report — table with columns
   ``(RegistryId, SourceName, TableName, BusinessDate, BatchId, AgeDays,
   CompressedMB, RecommendedAction)`` — same column set + same order in
   both human and JSON modes.
3. In ``--apply`` mode with ``--to-status`` set, invoke the proper
   Round 3 § 1.3 transition function for every row. Transitions
   supported:

   * ``verified`` -> ``replicated`` via ``mark_replicated(replica_target=...)``
     (REQUIRES ``--replica-target``)
   * ``replicated`` -> ``archived`` via ``mark_archived(archive_location=...)``
     (REQUIRES ``--archive-location``)
   * ``archived`` -> ``purged`` via ``mark_purged(retention_batch_id=...)``
     (REQUIRES ``--retention-batch-id``)

4. Write ONE ``CLI_PARQUET_TIER_REVIEW`` row to
   ``General.ops.PipelineEventLog`` per D76 — ``Metadata`` JSON carries
   ``args``, ``actor``, ``justification``, ``from_status``, ``to_status``,
   ``age_days``, ``applied`` flag, ``dry_run`` flag, ``rows_matched``,
   ``rows_transitioned``, ``rows_failed``, ``exit_code``, ``started_at``,
   ``completed_at``.
5. Per-row transitions ALSO produce their own Round 3 § 1.3 event-emit
   pattern rows (e.g. ``PARQUET_REPLICATE`` for ``mark_replicated``).
   The CLI-level audit row is a SEPARATE invocation event per D76.
6. Exit 0 / 1 / 2 per D74 (see Exit codes below).

CLI contract
------------

::

    # Read-only review of all 'verified' rows ready for replication
    python3 tools/parquet_tier_review.py \\
        --from-status verified \\
        --actor operator \\
        --justification "weekly tier review"

    # Apply: archive all 'replicated' rows older than 30 days
    python3 tools/parquet_tier_review.py \\
        --from-status replicated --to-status archived \\
        --age-days 30 \\
        --archive-location 's3://offsite-bucket/udm-archive/' \\
        --actor operator \\
        --justification "monthly cold-tier flip" \\
        --apply

    # Apply: purge all 'archived' rows older than 7 years (Automic-driven)
    python3 tools/parquet_tier_review.py \\
        --from-status archived --to-status purged \\
        --age-days 2555 \\
        --retention-batch-id 12345 \\
        --actor automic \\
        --apply

Exit codes (per D74 + spec § 3.1)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* **0** — rows transitioned successfully OR dry-run completed OR zero rows
  matched the filter (idempotent no-op — normal)
* **1** — at least one row failed transition with a retryable error;
  operator can re-run
* **2** — fatal — config missing, registry unreachable, invalid predecessor
  (bug class), or arg-parse failure

Audit row (per D76 + spec § 3.1)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* ``General.ops.PipelineEventLog.EventType = 'CLI_PARQUET_TIER_REVIEW'``
  (one of the 11 R4 canonical CLI_* family values per CLAUDE.md)
* ONE row per INVOCATION (separate from the per-row registry transition
  events emitted by Round 3 § 1.3 functions)
* ``Status in {SUCCESS, FAILED}`` (SUCCESS for exit 0/1; FAILED for exit 2)
* ``Metadata`` JSON shape::

    {
        "event_kind": "tier_review",
        "actor": "<operator>",
        "justification": "<text or null>",
        "from_status": "verified" | "replicated" | "archived" | ...,
        "to_status": "replicated" | "archived" | "purged" | null,
        "age_days": <int or null>,
        "applied": <bool>,
        "dry_run": <bool>,
        "rows_matched": <int>,
        "rows_transitioned": <int>,
        "rows_failed": <int>,
        "exit_code": <int>,
        "started_at": "<ISO-8601 naive-UTC>",
        "completed_at": "<ISO-8601 naive-UTC>"
    }

Classification per ``udm-execution-classifier`` skill
-----------------------------------------------------

* **Trigger**: PRIMARY: Manual operator CLI (weekly / monthly tier reviews).
  SECONDARY: Automic ``JOB_RETENTION_MONTHLY`` invokes this tool with
  ``--from-status archived --to-status purged --age-days 2555 --apply``
  at month-end per Round 2 § 5.1 frozen-N inventory.
* **Frequency**: PRIMARY ad-hoc; SECONDARY monthly Automic.
* **Idempotency**: YES per spec § 3.1 — Round 3 § 1.3 transition functions
  are idempotent at the row level (re-flip ``verified`` -> ``verified`` is
  a no-op). Re-running on the same Status set returns identical
  recommendation list (read-only path). ``--apply`` re-run: rows already
  in target Status are filtered out by predecessor-Status SELECT — no
  double-INSERT to event log.
* **Concurrency**: Single-process; ``cursor_for('General')`` per call.
  ``--workers`` NOT supported (operator-facing; serial is fine; per-row
  WRITEs are independent + UNIQUE-guarded at the registry level).
  Concurrent runs of this tool: same row may be touched twice; second
  tool's predecessor-Status filter naturally skips it; no race.
* **Audit-row family**: ``CLI_PARQUET_TIER_REVIEW`` per D76 + CLAUDE.md
  CLI_* family registry; per-row transitions emit their own Round 3 § 1.3
  events (``PARQUET_REPLICATE``, ``PARQUET_ARCHIVE``, ``PARQUET_PURGE``).
* **Routing**: PRIMARY tracker ``ONE_OFF_SCRIPTS.md`` operator tools
  table (manual + event-driven). ALSO referenced from
  ``02_configuration.md`` § 5.1 frozen-N Automic inventory under
  ``JOB_RETENTION_MONTHLY``.

D-numbers consumed
------------------

D2 (Stage dropped — Parquet replaces it),
D4 (network-drive Parquet),
D5 (Snowflake mirror — replicated state's destination),
D15 (idempotency mandatory),
D17 (idempotency ledger composed by Round 3 § 1.3 transition fns),
D25 (ParquetSnapshotRegistry canonical Parquet index),
D26 (append-only audit posture — Status flips, never DELETE),
D30 (7-year retention — archived -> purged flow),
D67 (Tier 0 smoke discipline),
D68 (PipelineFatalError -> exit 2; PipelineRetryableError -> exit 1),
D69 (cursor_for('General') ownership),
D74-D77 (CLI exit-code contract + argument naming + audit-row contract +
Tier 0 6-canonical scaffold).

Canonical references cited (per Pitfall #9.l producer self-check)
-----------------------------------------------------------------

* Round 3 § 1.3 ``data_load/parquet_registry_client.py``:
    * ``query_snapshot(*, source_name, table_name, business_date, batch_id)``
      keyword-only — single-row lookup
    * ``mark_replicated(*, registry_id, replica_target)`` keyword-only
    * ``mark_archived(*, registry_id, archive_location)`` keyword-only
    * ``mark_purged(*, registry_id, retention_batch_id)`` keyword-only
    * Status enum: ``created`` / ``verified`` / ``replicated`` /
      ``archived`` / ``missing`` / ``purged`` / ``replication_failed`` —
      7 states per ``ParquetSnapshotStatus`` StrEnum / module-level
      ``STATUS_*`` constants
    * Canonical columns: ``RegistryId``, ``SourceName``, ``TableName``,
      ``BatchId``, ``BusinessDate``, ``CompressedBytes``,
      ``UncompressedBytes``, ``Status``, ``CreatedAt``,
      ``LastVerifiedAt``, ``LastAccessedAt``, ``PurgedAt``,
      ``PurgedReason`` (verified against Round 1 DDL per Pitfall #9.a)
* Round 1 ``ParquetSnapshotRegistry`` DDL — ``CompressedBytes BIGINT
  NOT NULL`` per canonical schema; ``UncompressedBytes BIGINT NOT NULL``
* CLAUDE.md CLI_* family registry — ``CLI_PARQUET_TIER_REVIEW`` is one
  of the 11 R4 canonical CLI_* values

Spec ambiguity note
-------------------

The spec says **Wraps** ``query_snapshot()``, but ``query_snapshot()``
in Round 3 § 1.3 is a single-row lookup keyed by ``(BatchId, SourceName,
TableName, BusinessDate)``. To filter the registry by ``Status`` (the
tool's primary need), we issue a direct SELECT against the registry
table — there is no public list-by-status function in Round 3 § 1.3.
The status-filtered SELECT (``_list_registry_rows_by_status``) is
modest enough to live inside this tool; if a future caller needs the
same list-by-status surface, the BACKLOG item to extract a
``list_snapshots(*, status, age_days, ...)`` helper into
``parquet_registry_client.py`` would compose cleanly without changing
this tool's public CLI contract. (Surfaced as Spec ambiguity in the
build report — not a B-N opening because the SELECT body here is
narrow, read-only, and uses the canonical column projection.)

See also
--------

* ``data_load/parquet_registry_client.py`` — Round 3 § 1.3 canonical
  transition functions
* ``tools/parquet_verify.py`` — Round 4 § 3.2 ``created -> verified``
  CLI (complementary tool)
* ``02_configuration.md`` § 5.1 ``JOB_RETENTION_MONTHLY`` — Automic
  invocation pattern
* ``data_load/_exceptions.py`` — canonical exception classes
* ``utils/errors.py`` — ``RegistryStatusInvalid`` / ``RegistryFileNotFound``
  / ``RegistryNotFound`` (registry layer error classes per D68 + B228)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import traceback
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

# Project root on sys.path so we can reach data_load + utils.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Canonical Round 3 § 1.3 registry-layer error classes per D68 + B228 single-
# source-of-truth. Imported via try/except fallback per B215 pattern (tests
# may mock data_load.* engine modules as MagicMock, replacing class symbols
# with MagicMock attributes and breaking `except SomeError as exc:` blocks).
try:
    from utils.errors import (  # noqa: E402
        RegistryFileNotFound,
        RegistryNotFound,
        RegistryStatusInvalid,
    )
except (ImportError, ModuleNotFoundError):
    # Defensive fallback for environments where utils is mocked as MagicMock —
    # re-import the file directly from the filesystem.
    import importlib.util as _importlib_util  # noqa: E402

    _err_path = Path(__file__).resolve().parent.parent / "utils" / "errors.py"
    _spec = _importlib_util.spec_from_file_location(
        "utils._errors_parquet_tier_review", _err_path
    )
    _err_mod = _importlib_util.module_from_spec(_spec)
    _spec.loader.exec_module(_err_mod)
    RegistryFileNotFound = _err_mod.RegistryFileNotFound
    RegistryNotFound = _err_mod.RegistryNotFound
    RegistryStatusInvalid = _err_mod.RegistryStatusInvalid

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exit-code constants (per D74 + spec § 3.1)
# ---------------------------------------------------------------------------

EXIT_SUCCESS = 0
EXIT_WARNING = 1
EXIT_FATAL = 2

# D76 EventType registered in CLAUDE.md CLI_* family registry (one of the
# 11 R4 canonical values).
EVENT_TYPE = "CLI_PARQUET_TIER_REVIEW"

# Canonical status values — must match CK_ParquetSnapshotRegistry_Status
# constraint per phase1/01_database_schema.md § 8. Mirrors Round 3 § 1.3
# STATUS_* module-level constants (re-declared here so this tool does not
# need to import the registry-client module to validate args).
STATUS_CREATED = "created"
STATUS_VERIFIED = "verified"
STATUS_REPLICATED = "replicated"
STATUS_ARCHIVED = "archived"
STATUS_MISSING = "missing"
STATUS_PURGED = "purged"
STATUS_REPLICATION_FAILED = "replication_failed"

ALL_STATUSES: frozenset[str] = frozenset(
    {
        STATUS_CREATED,
        STATUS_VERIFIED,
        STATUS_REPLICATED,
        STATUS_ARCHIVED,
        STATUS_MISSING,
        STATUS_PURGED,
        STATUS_REPLICATION_FAILED,
    }
)

# Legal target Status values for --to-status. Sub-set of ALL_STATUSES that
# can be the DESTINATION of a transition this tool drives. Targets like
# 'created' / 'verified' / 'missing' / 'replication_failed' have their own
# dedicated tools or are reached organically by the pipeline, NOT through
# this CLI (per spec § 3.1).
SUPPORTED_TO_STATUSES: frozenset[str] = frozenset(
    {STATUS_REPLICATED, STATUS_ARCHIVED, STATUS_PURGED}
)

# Canonical recommended next-action per current Status (drives stdout
# RecommendedAction column when --to-status is not provided). Aligned with
# the 7-state happy-path lifecycle: created -> verified -> replicated ->
# archived -> purged.
RECOMMENDED_NEXT: dict[str, str] = {
    STATUS_CREATED: "verify (tools/parquet_verify.py)",
    STATUS_VERIFIED: "replicate (--to-status replicated)",
    STATUS_REPLICATED: "archive (--to-status archived)",
    STATUS_ARCHIVED: "purge (--to-status purged)",
    STATUS_MISSING: "investigate (file absent — see RB-6 / RB-8)",
    STATUS_PURGED: "(terminal — no action)",
    STATUS_REPLICATION_FAILED: "retry replicate OR mark_missing",
}


# ---------------------------------------------------------------------------
# Custom exception class (local to this tool — does not pollute
# data_load._exceptions because this is a CLI argv-validation class, not
# an engine-level fault). Inherits from plain Exception so it is mock-safe
# regardless of MagicMock import order.
# ---------------------------------------------------------------------------


class TierReviewConfigError(Exception):
    """Configuration / argument-shape error specific to this CLI.

    Distinct from :class:`utils.errors.RegistryStatusInvalid` (which is
    raised by Round 3 § 1.3 transition functions for INVALID state-machine
    edges). This class covers tool-side validation (e.g. ``--to-status
    archived`` without ``--archive-location``).

    Mapped to exit 2 by ``main()``.
    """


# ---------------------------------------------------------------------------
# Actor detection (per § 1.7 invocation-pattern heuristic)
# ---------------------------------------------------------------------------


def _detect_actor() -> str:
    """Resolve ``--actor`` default per spec § 1.7 invocation-pattern heuristic.

    1. AUTOMIC_RUN_ID env var present -> 'automic'
    2. sys.stdin.isatty() -> 'operator'
    3. Else -> 'pipeline'
    """
    if os.environ.get("AUTOMIC_RUN_ID"):
        return "automic"
    try:
        if sys.stdin.isatty():
            return "operator"
    except (AttributeError, ValueError):
        # ValueError: I/O operation on closed file (pytest -s pipe)
        pass
    return "pipeline"


# ---------------------------------------------------------------------------
# Canonical "now" helper — naive UTC, ms precision (CDC-NOW-MS / SCD2-P1-f
# invariant; pyodbc DATETIME2(3) values must be naive + millisecond-precision)
# ---------------------------------------------------------------------------


def _now_naive_utc_ms() -> datetime:
    """Return naive UTC ``datetime`` truncated to millisecond precision.

    Per CLAUDE.md gotchas (SCD2-P1-f + CDC-NOW-MS): pyodbc DATETIME2(3)
    parameters MUST be naive + millisecond-precision. A tz-aware
    datetime sends as DATETIMEOFFSET, which causes implicit timezone
    conversion when SQL Server compares against DATETIME2(3) columns
    on non-UTC servers.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    micros = now.microsecond
    millis = micros - (micros % 1000)
    return now.replace(microsecond=millis)


# ---------------------------------------------------------------------------
# Registry list query — status-filtered + optional age filter
#
# Spec ambiguity (documented in module docstring): Round 3 § 1.3 does NOT
# expose a list-by-status function. ``query_snapshot()`` is a single-row
# lookup keyed by (BatchId, SourceName, TableName, BusinessDate). The
# status-filtered list is narrow enough to live in the tool layer; a
# future extraction into a Round 3 § 1.3 ``list_snapshots`` helper would
# compose cleanly.
# ---------------------------------------------------------------------------


def _list_registry_rows_by_status(
    connection,
    *,
    from_status: str,
    age_days: int | None,
    source_filter: str | None,
    table_filter: str | None,
    general_db: str,
) -> list[dict]:
    """SELECT registry rows matching ``from_status`` (+ optional filters).

    Returns a list of dicts keyed on the canonical Round 3 § 1.3 column
    projection. Used by both dry-run preview and ``--apply`` mode.

    The age filter compares against ``CreatedAt`` for ``Status='created'``
    (no LastVerifiedAt yet on a created row), against ``LastVerifiedAt``
    for every other status. Per spec § 3.1 Tool-specific arguments:
    ``--age-days`` — "Filter rows where LastVerifiedAt (or CreatedAt for
    'created') is older than N days".

    Source / table filters compose AND-style with the status filter.
    """
    # ORDER BY oldest first so retention-style workflows (archived -> purged)
    # naturally process the oldest rows first — operator sees a stable order.
    order_col = "CreatedAt" if from_status == STATUS_CREATED else "LastVerifiedAt"

    where_clauses = ["Status = ?"]
    params: list[Any] = [from_status]

    if age_days is not None:
        # Cutoff is "older than N days from now" — rows where the age column
        # is < cutoff_dt are eligible.
        cutoff_dt = _now_naive_utc_ms() - timedelta(days=age_days)
        # For 'created', age is against CreatedAt; otherwise LastVerifiedAt.
        # LastVerifiedAt may be NULL for very recently transitioned rows that
        # skipped verification — those rows do NOT match the age filter (they
        # are too young; conservative + explicit).
        if from_status == STATUS_CREATED:
            where_clauses.append("CreatedAt < ?")
        else:
            where_clauses.append(
                "LastVerifiedAt IS NOT NULL AND LastVerifiedAt < ?"
            )
        params.append(cutoff_dt)

    if source_filter is not None:
        where_clauses.append("SourceName = ?")
        params.append(source_filter)

    if table_filter is not None:
        where_clauses.append("TableName = ?")
        params.append(table_filter)

    where_clause = " AND ".join(where_clauses)

    # Canonical column projection — matches Round 3 § 1.3
    # ``_fetch_registry_row`` / ``query_snapshot`` projections so per-row
    # dicts have the same shape regardless of caller path.
    select_sql = (
        f"SELECT "
        f"RegistryId, SourceName, TableName, BatchId, BusinessDate, "
        f"NetworkDrivePath, SnowflakeStagePath, SnowflakeUploadedAt, "
        f"RowCount, UncompressedBytes, CompressedBytes, SchemaHash, "
        f"ContentChecksum, StorageTier, Status, CreatedAt, "
        f"LastVerifiedAt, LastAccessedAt, PurgedAt, PurgedReason "
        f"FROM [{general_db}].ops.ParquetSnapshotRegistry "
        f"WHERE {where_clause} "
        f"ORDER BY {order_col} ASC, RegistryId ASC"
    )

    cursor = connection.cursor()
    try:
        cursor.execute(select_sql, *params)
        rows = cursor.fetchall()
        if not rows:
            return []
        columns = [c[0] for c in cursor.description]
        return [dict(zip(columns, row)) for row in rows]
    finally:
        try:
            cursor.close()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Per-row recommendation derivation
# ---------------------------------------------------------------------------


def _compute_age_days(row: dict, *, now_dt: datetime) -> int | None:
    """Return age in days from ``LastVerifiedAt`` (or ``CreatedAt`` for created).

    Returns None if the relevant column is NULL.
    """
    status = row.get("Status")
    if status == STATUS_CREATED:
        age_source = row.get("CreatedAt")
    else:
        age_source = row.get("LastVerifiedAt") or row.get("CreatedAt")
    if age_source is None:
        return None
    if not isinstance(age_source, datetime):
        return None
    delta = now_dt - age_source
    return max(0, int(delta.total_seconds() // 86400))


def _compressed_mb(row: dict) -> float:
    """Return ``CompressedBytes / 1024 / 1024`` rounded to 2 decimals.

    Per spec § 3.1 Produces: ``CompressedMB`` is the operator-readable
    column. Canonical ``CompressedBytes BIGINT NOT NULL`` per
    ``01_database_schema.md`` L492 (re-verified per Pitfall #9.l).
    """
    raw = row.get("CompressedBytes")
    if raw is None:
        return 0.0
    try:
        return round(int(raw) / 1024.0 / 1024.0, 2)
    except (TypeError, ValueError):
        return 0.0


def _recommended_action_for(row: dict, *, to_status: str | None) -> str:
    """Per-row RecommendedAction string for the report.

    If ``--to-status`` is provided, every row's recommendation is that
    transition (the operator is intentionally driving a tier flip). If
    no ``--to-status``, look up the natural next-status from the
    happy-path lifecycle per :data:`RECOMMENDED_NEXT`.
    """
    if to_status is not None:
        return f"-> {to_status}"
    status = row.get("Status")
    return RECOMMENDED_NEXT.get(status, "(no canonical next action)")


# ---------------------------------------------------------------------------
# Per-row transition dispatch
# ---------------------------------------------------------------------------


def _apply_transition(
    *,
    row: dict,
    to_status: str,
    replica_target: str | None,
    archive_location: str | None,
    retention_batch_id: int | None,
    transition_fn_overrides: dict[str, Callable] | None,
) -> tuple[bool, str | None]:
    """Invoke the proper Round 3 § 1.3 transition function for one row.

    Returns ``(success_bool, error_message_or_None)``. ``success`` is True
    on a clean transition; False on any registry-layer error.

    ``transition_fn_overrides`` is a test-injection point — production
    path resolves the functions lazily from
    ``data_load.parquet_registry_client``.
    """
    registry_id = int(row["RegistryId"])

    fns = _resolve_transition_fns(transition_fn_overrides)

    try:
        if to_status == STATUS_REPLICATED:
            assert replica_target is not None  # caller validated upstream
            fns["mark_replicated"](
                registry_id=registry_id,
                replica_target=replica_target,
            )
        elif to_status == STATUS_ARCHIVED:
            assert archive_location is not None
            fns["mark_archived"](
                registry_id=registry_id,
                archive_location=archive_location,
            )
        elif to_status == STATUS_PURGED:
            assert retention_batch_id is not None
            fns["mark_purged"](
                registry_id=registry_id,
                retention_batch_id=retention_batch_id,
            )
        else:
            # Defense-in-depth — should be caught by _validate_args.
            return (
                False,
                f"Unsupported --to-status {to_status!r}; "
                f"supported: {sorted(SUPPORTED_TO_STATUSES)!r}.",
            )
        return (True, None)
    except RegistryStatusInvalid as exc:
        # Fatal at the row level; the run-level outcome is still
        # determined by the caller (one bad row may not abort the rest;
        # `--continue-on-error` is the spec's stance for batch flows).
        return (False, f"RegistryStatusInvalid: {exc}")
    except RegistryFileNotFound as exc:
        return (False, f"RegistryFileNotFound: {exc}")
    except RegistryNotFound as exc:
        return (False, f"RegistryNotFound: {exc}")
    except Exception as exc:  # noqa: BLE001
        return (False, f"{type(exc).__name__}: {exc}")


def _resolve_transition_fns(
    overrides: dict[str, Callable] | None,
) -> dict[str, Callable]:
    """Return the dict of transition functions, honoring overrides.

    Lazy import at CALL TIME so tests that patch
    ``sys.modules['data_load.parquet_registry_client']`` after tool
    import are honored. Mirrors enforce_retention's pattern.
    """
    if overrides is not None:
        return overrides
    from data_load.parquet_registry_client import (  # type: ignore
        mark_archived,
        mark_purged,
        mark_replicated,
    )

    return {
        "mark_replicated": mark_replicated,
        "mark_archived": mark_archived,
        "mark_purged": mark_purged,
    }


# ---------------------------------------------------------------------------
# Audit-row writer — one CLI_PARQUET_TIER_REVIEW row per invocation
# ---------------------------------------------------------------------------


def _write_audit_row(
    metadata: dict,
    *,
    status: str,
    error_message: str | None = None,
    cursor_factory: Callable | None = None,
    general_db: str = "General",
    skip: bool = False,
) -> int | None:
    """INSERT one ``CLI_PARQUET_TIER_REVIEW`` row into PipelineEventLog.

    Per D76 + spec § 3.1. ONE row per invocation (per-row transition
    events are emitted separately by Round 3 § 1.3 functions). Best-
    effort: failures are logged but do not affect the verdict exit code
    (parity with B188/B189/B190 audit-row patterns).

    Returns the IDENTITY value of the inserted row via SCOPE_IDENTITY()
    so the JSON ``audit_event_id`` key can be populated. Returns None
    on failure.

    When ``cursor_factory`` is injected (test path), the live
    ``utils.connections`` resolution is skipped. When ``skip=True``
    (main()'s ``no_audit_event``), the function returns None
    immediately without writing.
    """
    if skip:
        return None
    metadata_json = json.dumps(metadata, separators=(",", ":"), default=str)
    event_detail = (
        f"parquet_tier_review / "
        f"from_status={metadata.get('from_status')} "
        f"to_status={metadata.get('to_status')} "
        f"dry_run={metadata.get('dry_run')} "
        f"actor={metadata.get('actor')}"
    )

    if cursor_factory is None:
        try:
            from utils.connections import get_connection  # type: ignore

            def cursor_factory():  # type: ignore[no-redef]
                return get_connection(general_db)
        except Exception:  # noqa: BLE001
            logger.warning(
                "Audit-row write skipped: utils.connections unavailable; "
                "verdict exit code is authoritative."
            )
            return None

    conn = None
    try:
        conn = cursor_factory()
        try:
            conn.autocommit = True
        except Exception:  # noqa: BLE001
            pass
        cursor = conn.cursor()
        try:
            cursor.execute(
                f"INSERT INTO [{general_db}].ops.PipelineEventLog "
                f"(BatchId, TableName, SourceName, EventType, EventDetail, "
                f" StartedAt, CompletedAt, Status, ErrorMessage, Metadata) "
                f"VALUES (NEXT VALUE FOR [{general_db}].ops.PipelineBatchSequence, "
                f"        NULL, NULL, ?, ?, ?, SYSUTCDATETIME(), ?, ?, ?); "
                f"SELECT CAST(SCOPE_IDENTITY() AS BIGINT) AS AuditEventId;",
                EVENT_TYPE,
                event_detail,
                metadata.get("started_at_dt"),
                status,
                error_message,
                metadata_json,
            )
            row = cursor.fetchone() if cursor.description is not None else None
            if row is None or row[0] is None:
                return None
            return int(row[0])
        finally:
            try:
                cursor.close()
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        logger.exception("Failed to write CLI_PARQUET_TIER_REVIEW audit row")
        return None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Stdout rendering
# ---------------------------------------------------------------------------


def _format_business_date(value: Any) -> str:
    """Format BusinessDate (date or None) for the report."""
    if value is None:
        return "<NULL>"
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _emit_human_table(rows_with_meta: list[dict], *, to_status: str | None) -> None:
    """Print the spec § 3.1 stdout table — same columns as JSON.

    Columns: RegistryId / SourceName / TableName / BusinessDate / BatchId /
    AgeDays / CompressedMB / RecommendedAction. Tab-separated for parity
    with the spec's "tab-separated table" requirement.
    """
    header = (
        "RegistryId\tSourceName\tTableName\tBusinessDate\t"
        "BatchId\tAgeDays\tCompressedMB\tRecommendedAction"
    )
    print(header)
    if not rows_with_meta:
        print("(no rows matched)")
        return

    for r in rows_with_meta:
        age_str = "<NULL>" if r.get("AgeDays") is None else str(r.get("AgeDays"))
        print(
            f"{r.get('RegistryId')}\t"
            f"{r.get('SourceName')}\t"
            f"{r.get('TableName')}\t"
            f"{_format_business_date(r.get('BusinessDate'))}\t"
            f"{r.get('BatchId')}\t"
            f"{age_str}\t"
            f"{r.get('CompressedMB'):.2f}\t"
            f"{r.get('RecommendedAction')}"
        )

    if to_status is not None:
        print(
            f"\n{len(rows_with_meta)} rows matched; "
            f"would transition to {to_status}."
        )
    else:
        print(f"\n{len(rows_with_meta)} rows matched (report-only).")


def _emit_json(payload: dict) -> None:
    """Emit the canonical JSON payload per spec § 3.1."""
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


# ---------------------------------------------------------------------------
# General DB connection factory (test-friendly resolution)
# ---------------------------------------------------------------------------


def _resolve_default_general_cursor_factory() -> Callable:
    """Return a callable that opens a connection to the General DB.

    Resolves at CALL TIME so tests patching ``sys.modules['pyodbc']``
    after tool import are honored. Production path uses
    ``utils.connections.get_connection('General')``; if that raises
    (no DSN / no driver), we fall back to
    ``sys.modules['pyodbc'].connect``.

    Raises :class:`TierReviewConfigError` (mapped to exit 2 by main())
    if neither path succeeds.
    """

    def _open():
        try:
            from utils.connections import get_connection  # type: ignore

            return get_connection("General")
        except Exception:  # noqa: BLE001
            pass
        pyodbc_mod = sys.modules.get("pyodbc")
        if pyodbc_mod is None:
            try:
                import pyodbc as pyodbc_mod  # type: ignore  # noqa: F401
            except Exception as exc:  # noqa: BLE001
                raise TierReviewConfigError(
                    f"pyodbc / utils.connections both unavailable: {exc}"
                ) from exc
        return pyodbc_mod.connect("DRIVER={ODBC Driver 18 for SQL Server};")

    return _open


# ---------------------------------------------------------------------------
# Argument validation (cross-cutting beyond argparse's declarative checks)
# ---------------------------------------------------------------------------


def _validate_args_main(
    *,
    from_status: str,
    to_status: str | None,
    age_days: int | None,
    apply: bool,
    replica_target: str | None,
    archive_location: str | None,
    retention_batch_id: int | None,
) -> None:
    """Cross-field argument validation. Raises :class:`TierReviewConfigError`.

    Argparse can't enforce these declaratively. Called by :func:`main`
    before any I/O.
    """
    if from_status not in ALL_STATUSES:
        raise TierReviewConfigError(
            f"--from-status {from_status!r} is not a valid registry status. "
            f"Valid: {sorted(ALL_STATUSES)!r}."
        )

    if to_status is not None:
        if to_status not in SUPPORTED_TO_STATUSES:
            raise TierReviewConfigError(
                f"--to-status {to_status!r} is not a tier-review-driven "
                f"transition. Supported: {sorted(SUPPORTED_TO_STATUSES)!r}. "
                f"(Other transitions — verified, missing, replication_failed "
                f"— are handled by dedicated tools or by the pipeline.)"
            )
        # Validate the state-graph edge — operator can't ask for a transition
        # the registry won't accept.
        legal_edges = {
            STATUS_REPLICATED: {STATUS_VERIFIED, STATUS_REPLICATION_FAILED},
            STATUS_ARCHIVED: {STATUS_REPLICATED},
            STATUS_PURGED: {STATUS_ARCHIVED},
        }
        legal_predecessors = legal_edges.get(to_status, frozenset())
        if from_status not in legal_predecessors:
            raise TierReviewConfigError(
                f"Transition {from_status!r} -> {to_status!r} is not a "
                f"legal registry state-machine edge. Legal predecessors "
                f"for --to-status {to_status!r}: "
                f"{sorted(legal_predecessors)!r}."
            )

    if apply and to_status is None:
        raise TierReviewConfigError(
            "--apply requires --to-status. (Report-only mode is the default "
            "without --to-status.)"
        )

    if to_status == STATUS_REPLICATED and apply and not replica_target:
        raise TierReviewConfigError(
            "--to-status replicated --apply requires --replica-target."
        )
    if to_status == STATUS_ARCHIVED and apply and not archive_location:
        raise TierReviewConfigError(
            "--to-status archived --apply requires --archive-location."
        )
    if to_status == STATUS_PURGED and apply and retention_batch_id is None:
        raise TierReviewConfigError(
            "--to-status purged --apply requires --retention-batch-id."
        )

    if age_days is not None and age_days < 0:
        raise TierReviewConfigError(
            f"--age-days must be >= 0 (got {age_days})."
        )


# ---------------------------------------------------------------------------
# Internal: B-270 env-var-gated crash-injection harness (test-only)
#
# Tier 4 (Round 5 § 7 + docs/migration/06_TESTING.md) needs a deterministic
# crash boundary BETWEEN consecutive ``_apply_transition`` calls in the
# main --apply batch loop — so a parent test process can SIGKILL this
# subprocess after N transitions have completed and verify that the
# already-transitioned rows are durable in the registry while the
# remaining rows are untouched (registry state-machine atomicity per
# Round 3 § 1.3 ParquetSnapshotRegistry state machine). C11 canonical
# crash injection point per Round 5 § 7 inventory.
#
# Contract:
#   - Reads ``CRASH_INJECT_POINT`` env var; only fires when value matches
#     ``f"after_n_transitions_{n}"`` where ``n`` is the running count of
#     transitions completed in the loop.
#   - Emits the canonical barrier token ``f"TRANSITIONS_DONE_{n}"`` to
#     stdout (flushed immediately) so the parent test process sees the
#     specific N before the sleep window opens.
#   - Sleeps ``CRASH_INJECT_SLEEP_SECONDS`` seconds (default 10) so the
#     parent has a deterministic window to SIGKILL this process before
#     the next transition runs.
#   - No-op when env var absent OR value does not match the per-N
#     checkpoint. Zero production cost (one ``os.environ.get`` lookup +
#     one f-string format + branch).
#   - NEVER raises — defensive try/except internal — pollution of the
#     production path is the only failure mode we cannot accept.
# ---------------------------------------------------------------------------


def _crash_test_harness_c11(n: int) -> None:
    """B-270 closure: env-var-gated test-only crash injection point (C11).

    Reads ``CRASH_INJECT_POINT`` env var; if its value matches
    ``f"after_n_transitions_{n}"``, emits the canonical barrier token
    ``f"TRANSITIONS_DONE_{n}"`` to stdout (flushed) and sleeps to give a
    parent test process a deterministic window to SIGKILL this
    subprocess after N transitions have completed. No-op when env var
    absent OR value does not match the per-N checkpoint — zero production
    cost. NEVER raises (defensive try/except internal).

    :param n: Running count of transitions completed in the loop. The
        first call passes ``n=1``, second ``n=2``, etc. Both the
        checkpoint name and the barrier token incorporate this value
        so the parent test process can pick a specific transition
        boundary to crash at.

    Per docs/migration/06_TESTING.md Tier 4 + B-270 closure.
    """
    try:
        import os, sys, time  # noqa: PLC0415 — lazy by design
        expected_checkpoint = "after_n_transitions_" + str(n)
        if os.environ.get("CRASH_INJECT_POINT") != expected_checkpoint:
            return
        print("TRANSITIONS_DONE_" + str(n), flush=True)
        sleep_seconds = float(os.environ.get("CRASH_INJECT_SLEEP_SECONDS", "10"))
        time.sleep(sleep_seconds)
    except Exception:  # noqa: BLE001 — production path MUST NOT be polluted
        # Defensive: env-var read or sleep failed for an unknown reason.
        # Swallow — the test harness is opt-in and any failure means we
        # silently degrade to "no-op", matching the env-var-absent case.
        return


# ---------------------------------------------------------------------------
# Top-level main() — programmatic entry point
# ---------------------------------------------------------------------------


def main(
    *,
    actor: str,
    from_status: str = STATUS_VERIFIED,
    to_status: str | None = None,
    age_days: int | None = None,
    source: str | None = None,
    table: str | None = None,
    replica_target: str | None = None,
    archive_location: str | None = None,
    retention_batch_id: int | None = None,
    apply: bool = False,
    dry_run: bool | None = None,
    json_output: bool = False,
    verbose: bool = False,
    quiet: bool = False,
    justification: str | None = None,
    no_audit_event: bool = False,
    # ---- Injection hooks (test path) ----
    general_cursor_factory: Callable | None = None,
    audit_cursor_factory: Callable | None = None,
    transition_fn_overrides: dict[str, Callable] | None = None,
    general_db: str | None = None,
) -> dict:
    """Programmatic entry — walk the registry by status and (optionally) transition.

    Returns a dict matching the D76 audit-row Metadata shape (see module
    docstring for the canonical schema). Exit-code derivation per D74 +
    spec § 3.1:

    * 0: dry-run produced (or zero rows matched, or all rows transitioned)
    * 1: at least one row failed a transition with a retryable error
    * 2: fatal — config / connection / RegistryStatusInvalid / arg mutex

    Parameters
    ----------
    actor:
        Operator identity (per D75 + D76). REQUIRED.
    from_status:
        Source Status filter. Default ``'verified'`` (most common operator
        review surface). One of the 7 canonical Status values.
    to_status:
        Target Status for ``--apply`` mode. None = report-only. Validated
        against state-machine edges via :func:`_validate_args_main`.
    age_days:
        Filter rows where LastVerifiedAt (or CreatedAt for ``created``) is
        older than N days. None = no age filter.
    source / table:
        Optional ``UdmTablesList`` filters per D75 canonical args.
    replica_target / archive_location / retention_batch_id:
        Per-transition required arguments per spec § 3.1.
    apply:
        When True, drive the per-row transition. When False (default per
        spec § 1.2 dry-run-default), only report.
    dry_run:
        B88 mutex bridge — if True AND ``apply=True`` -> exit 2.
    justification:
        Operator justification recorded in audit-row Metadata per D75.
    no_audit_event:
        When True, skip the CLI-level PipelineEventLog write (pipeline-
        programmatic callers per D75 + D76).
    general_cursor_factory / audit_cursor_factory / transition_fn_overrides:
        Test-injection hooks. Defaults resolve to live infrastructure.
    general_db:
        Override the canonical General DB name (defaults to
        ``utils.configuration.GENERAL_DB``, fallback ``'General'``).
    """
    started_at_dt = _now_naive_utc_ms()

    # B88 dry-run/apply mutex bridge: tests pass `dry_run` as a kwarg
    # paralleling `apply`. Canonical semantic: --apply makes it real;
    # --dry-run forces preview. If both True -> mutex violation (exit 2).
    # If `dry_run=True` -> override apply=False.
    if dry_run is True and apply is True:
        raise SystemExit(2)
    if dry_run is True:
        apply = False

    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    elif quiet:
        logging.getLogger().setLevel(logging.ERROR)

    # Resolve general_db tag (matches B188 / B189 / B190 / B218 pattern).
    if general_db is None:
        try:
            import utils.configuration as config  # type: ignore

            general_db = getattr(config, "GENERAL_DB", "General")
        except Exception:  # noqa: BLE001
            general_db = "General"

    # ---- Pre-populate result with input echoes for early-exit paths ----
    result: dict[str, Any] = {
        "event_kind": "tier_review",
        "actor": actor,
        "justification": justification,
        "from_status": from_status,
        "to_status": to_status,
        "age_days": age_days,
        "source": source,
        "table": table,
        "applied": bool(apply),
        "dry_run": (not apply),
        "rows_matched": 0,
        "rows_transitioned": 0,
        "rows_failed": 0,
        "exit_code": EXIT_SUCCESS,
        "started_at": started_at_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "started_at_dt": started_at_dt,
        "completed_at": None,
        "audit_event_id": None,
        "errors": [],
        "rows": [],
    }

    # ---- Cross-field arg validation ----
    try:
        _validate_args_main(
            from_status=from_status,
            to_status=to_status,
            age_days=age_days,
            apply=apply,
            replica_target=replica_target,
            archive_location=archive_location,
            retention_batch_id=retention_batch_id,
        )
    except TierReviewConfigError as exc:
        result["exit_code"] = EXIT_FATAL
        result["error_type"] = "TierReviewConfigError"
        result["error_message"] = str(exc)
        result["errors"].append(f"TierReviewConfigError: {exc}")
        if not quiet:
            print(f"FATAL: {exc}", file=sys.stderr)
        audit_id = _write_audit_row(
            result,
            status="FAILED",
            error_message=str(exc)[:4000],
            cursor_factory=audit_cursor_factory,
            general_db=general_db,
            skip=no_audit_event,
        )
        result["audit_event_id"] = audit_id
        result["completed_at"] = _now_naive_utc_ms().strftime("%Y-%m-%dT%H:%M:%SZ")
        return result

    # ---- Resolve connection factory ----
    if general_cursor_factory is None:
        try:
            general_cursor_factory = _resolve_default_general_cursor_factory()
        except TierReviewConfigError as exc:
            result["exit_code"] = EXIT_FATAL
            result["error_type"] = "TierReviewConfigError"
            result["error_message"] = str(exc)
            result["errors"].append(f"TierReviewConfigError: {exc}")
            if not quiet:
                print(
                    f"FATAL: config unavailable for parquet_tier_review: {exc}",
                    file=sys.stderr,
                )
            audit_id = _write_audit_row(
                result,
                status="FAILED",
                error_message=str(exc)[:4000],
                cursor_factory=audit_cursor_factory,
                general_db=general_db,
                skip=no_audit_event,
            )
            result["audit_event_id"] = audit_id
            result["completed_at"] = _now_naive_utc_ms().strftime("%Y-%m-%dT%H:%M:%SZ")
            return result

    # ---- Open connection + list rows + (optional) apply per-row transitions ----
    conn = None
    try:
        try:
            conn = general_cursor_factory()
        except Exception as exc:  # noqa: BLE001
            # Connection failure → exit 1 (retryable).
            result["exit_code"] = EXIT_WARNING
            result["error_type"] = type(exc).__name__
            result["error_message"] = str(exc)[:4000]
            result["errors"].append(f"{type(exc).__name__}: {exc}")
            logger.warning("Connection to General DB failed: %s", exc)
            if not quiet:
                print(
                    f"WARNING: connection failed (operator can re-run): {exc}",
                    file=sys.stderr,
                )
            audit_id = _write_audit_row(
                result,
                status="FAILED",
                error_message=traceback.format_exc()[:4000],
                cursor_factory=audit_cursor_factory,
                general_db=general_db,
                skip=no_audit_event,
            )
            result["audit_event_id"] = audit_id
            result["completed_at"] = _now_naive_utc_ms().strftime("%Y-%m-%dT%H:%M:%SZ")
            return result

        try:
            conn.autocommit = True
        except Exception:  # noqa: BLE001
            pass

        # ---- SELECT matching rows ----
        try:
            registry_rows = _list_registry_rows_by_status(
                conn,
                from_status=from_status,
                age_days=age_days,
                source_filter=source,
                table_filter=table,
                general_db=general_db,
            )
        except Exception as exc:  # noqa: BLE001
            # Registry table unreachable mid-query → exit 1 (retryable).
            result["exit_code"] = EXIT_WARNING
            result["error_type"] = type(exc).__name__
            result["error_message"] = str(exc)[:4000]
            result["errors"].append(f"SELECT failure: {exc}")
            logger.warning("Registry SELECT failed: %s", exc)
            if not quiet:
                print(
                    f"WARNING: registry query failed: {exc}",
                    file=sys.stderr,
                )
            audit_id = _write_audit_row(
                result,
                status="FAILED",
                error_message=traceback.format_exc()[:4000],
                cursor_factory=audit_cursor_factory,
                general_db=general_db,
                skip=no_audit_event,
            )
            result["audit_event_id"] = audit_id
            result["completed_at"] = _now_naive_utc_ms().strftime("%Y-%m-%dT%H:%M:%SZ")
            return result

        result["rows_matched"] = len(registry_rows)

        # ---- Build per-row report payload ----
        now_dt = _now_naive_utc_ms()
        report_rows: list[dict] = []
        for row in registry_rows:
            report_rows.append(
                {
                    "RegistryId": row.get("RegistryId"),
                    "SourceName": row.get("SourceName"),
                    "TableName": row.get("TableName"),
                    "BusinessDate": row.get("BusinessDate"),
                    "BatchId": row.get("BatchId"),
                    "Status": row.get("Status"),
                    "AgeDays": _compute_age_days(row, now_dt=now_dt),
                    "CompressedMB": _compressed_mb(row),
                    "CompressedBytes": row.get("CompressedBytes"),
                    "UncompressedBytes": row.get("UncompressedBytes"),
                    "RecommendedAction": _recommended_action_for(
                        row, to_status=to_status
                    ),
                    "error_message": None,
                }
            )

        # ---- Apply per-row transitions in --apply mode ----
        if apply and to_status is not None and report_rows:
            # B-270: running counter of successful transitions for the
            # C11 crash-injection harness. Increments after EACH success;
            # the harness only fires when CRASH_INJECT_POINT matches the
            # per-N checkpoint (no-op in production runs).
            _transition_count = 0
            for report_row in report_rows:
                row_id = report_row["RegistryId"]
                # Find the matching raw row dict (carries the canonical
                # fields the transition fns need, e.g. Status).
                raw_row = next(
                    (
                        r
                        for r in registry_rows
                        if int(r.get("RegistryId", -1)) == int(row_id)
                    ),
                    None,
                )
                if raw_row is None:
                    report_row["error_message"] = (
                        "internal: missing raw row for transition dispatch"
                    )
                    result["rows_failed"] += 1
                    continue

                success, err = _apply_transition(
                    row=raw_row,
                    to_status=to_status,
                    replica_target=replica_target,
                    archive_location=archive_location,
                    retention_batch_id=retention_batch_id,
                    transition_fn_overrides=transition_fn_overrides,
                )
                if success:
                    result["rows_transitioned"] += 1
                    _transition_count += 1
                    # B-270: test-only crash injection point (C11) —
                    # fires only when CRASH_INJECT_POINT matches
                    # f"after_n_transitions_{_transition_count}"; no-op
                    # otherwise.
                    _crash_test_harness_c11(_transition_count)
                else:
                    result["rows_failed"] += 1
                    report_row["error_message"] = err
                    result["errors"].append(
                        f"RegistryId={row_id}: {err}"
                    )

        result["rows"] = report_rows

        # ---- Determine exit code based on transition outcomes ----
        if apply and result["rows_failed"] > 0:
            # Distinguish fatal from retryable based on the error class
            # carried in the row error_message.
            any_fatal = any(
                ("RegistryStatusInvalid" in (r.get("error_message") or ""))
                or ("RegistryNotFound" in (r.get("error_message") or ""))
                for r in report_rows
            )
            result["exit_code"] = EXIT_FATAL if any_fatal else EXIT_WARNING

    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    result["completed_at"] = _now_naive_utc_ms().strftime("%Y-%m-%dT%H:%M:%SZ")

    # ---- Render stdout ----
    if json_output:
        emit_dict = {k: v for k, v in result.items() if k != "started_at_dt"}
        # Coerce non-serializable types (datetime / date) through default=str.
        _emit_json(emit_dict)
    elif not quiet:
        _emit_human_table(result["rows"], to_status=to_status)

    # ---- Invocation-level audit row (D76 — ONE per invocation) ----
    audit_status = (
        "SUCCESS"
        if result["exit_code"] in (EXIT_SUCCESS, EXIT_WARNING)
        else "FAILED"
    )
    audit_id = _write_audit_row(
        result,
        status=audit_status,
        error_message=result.get("error_message"),
        cursor_factory=audit_cursor_factory,
        general_db=general_db,
        skip=no_audit_event,
    )
    result["audit_event_id"] = audit_id

    return result


# ---------------------------------------------------------------------------
# CLI argv entry point
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    """Alias for :func:`_build_parser` — Tier 0 scaffold contract."""
    return _build_parser()


def _build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser per spec § 3.1 + § 1.4 canonical args."""
    parser = argparse.ArgumentParser(
        description=(
            "Walk General.ops.ParquetSnapshotRegistry rows in a given Status; "
            "report ages, sizes, and recommended next transition. With "
            "--apply + --to-status, drive the per-row transition via "
            "Round 3 § 1.3 registry-client functions. Emits one "
            "CLI_PARQUET_TIER_REVIEW audit row per invocation."
        ),
    )

    # ---- Tool-specific args (per spec § 3.1 Tool-specific arguments) ----
    parser.add_argument(
        "--from-status",
        default=STATUS_VERIFIED,
        choices=sorted(ALL_STATUSES),
        help=(
            f"Source Status filter (default: {STATUS_VERIFIED!r} — the most "
            f"common operator review surface). One of the 7 canonical "
            f"ParquetSnapshotRegistry Status values."
        ),
    )
    parser.add_argument(
        "--to-status",
        default=None,
        choices=sorted(SUPPORTED_TO_STATUSES),
        help=(
            "Target Status for --apply mode (default: report-only). "
            "Supported transitions: verified -> replicated, replicated -> "
            "archived, archived -> purged. Other transitions are driven "
            "by dedicated tools or by the pipeline."
        ),
    )
    parser.add_argument(
        "--age-days",
        type=int,
        default=None,
        help=(
            "Filter rows where LastVerifiedAt (or CreatedAt for 'created') "
            "is older than N days. Default: no age filter."
        ),
    )
    parser.add_argument(
        "--replica-target",
        default=None,
        help=(
            "Required when --to-status replicated. Maps to Round 3 § 1.3 "
            "mark_replicated(replica_target). Typical: "
            "'snowflake:UDM_BRONZE_MIRROR'."
        ),
    )
    parser.add_argument(
        "--archive-location",
        default=None,
        help=(
            "Required when --to-status archived. Maps to Round 3 § 1.3 "
            "mark_archived(archive_location). Typical: "
            "'s3://offsite-bucket/udm-archive/'."
        ),
    )
    parser.add_argument(
        "--retention-batch-id",
        type=int,
        default=None,
        help=(
            "Required when --to-status purged. Maps to Round 3 § 1.3 "
            "mark_purged(retention_batch_id). Ties the purge to a "
            "JOB_RETENTION_MONTHLY event row."
        ),
    )

    # ---- D75 canonical args (per spec § 1.4) ----
    parser.add_argument(
        "--source",
        default=None,
        help=(
            "Filter by SourceName (UdmTablesList.SourceName). Optional. "
            "Examples: DNA, CCM, EPICOR."
        ),
    )
    parser.add_argument(
        "--table",
        default=None,
        help="Filter by TableName / SourceObjectName. Optional.",
    )

    apply_group = parser.add_mutually_exclusive_group()
    apply_group.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Apply per-row transitions via Round 3 § 1.3 mark_* functions. "
            "Default is dry-run (report-only)."
        ),
    )
    apply_group.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Explicit dry-run opt-in (redundant — this is the default; "
            "useful for scripting clarity)."
        ),
    )

    parser.add_argument(
        "--actor",
        default=None,
        help=(
            "Operator identity (per D75 + D76). One of operator / automic / "
            "pipeline / reconciliation. Auto-detected via TTY / "
            "AUTOMIC_RUN_ID env when omitted."
        ),
    )
    parser.add_argument(
        "--justification",
        default=None,
        help=(
            "Operator justification (per D75); written to audit row "
            "Metadata."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Emit canonical JSON output to stdout instead of human table.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable DEBUG logging.",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress stdout summary (errors still emitted to stderr).",
    )
    parser.add_argument(
        "--no-audit-event",
        action="store_true",
        help=(
            "Skip CLI-level PipelineEventLog write (pipeline-programmatic "
            "callers per D75 + D76)."
        ),
    )
    return parser


def cli_main() -> int:
    """Argv entry point — argparse + main() + return exit code per D74.

    Exit codes (always one of 0 / 1 / 2 per D74 + spec § 3.1):
        - 0: dry-run preview / zero rows matched / all rows transitioned
        - 1: at least one row failed with a retryable error
        - 2: fatal — config / connection / invalid predecessor
    """
    parser = _build_parser()
    args = parser.parse_args()

    actor = args.actor or _detect_actor()

    try:
        result = main(
            actor=actor,
            from_status=args.from_status,
            to_status=args.to_status,
            age_days=args.age_days,
            source=args.source,
            table=args.table,
            replica_target=args.replica_target,
            archive_location=args.archive_location,
            retention_batch_id=args.retention_batch_id,
            apply=args.apply,
            dry_run=args.dry_run,
            json_output=args.json_output,
            verbose=args.verbose,
            quiet=args.quiet,
            justification=args.justification,
            no_audit_event=args.no_audit_event,
        )
    except SystemExit as exc:
        # Argparse-style validation error already printed by parser.error,
        # OR B88 mutex violation from main(). Either way -> fatal.
        return EXIT_FATAL if exc.code != 0 else EXIT_SUCCESS
    except KeyboardInterrupt:
        logger.warning("Interrupted by operator")
        return EXIT_WARNING
    except Exception:  # noqa: BLE001
        tb = traceback.format_exc()
        print(
            f"FATAL: parquet_tier_review unexpected exception:\n{tb[:1000]}",
            file=sys.stderr,
        )
        return EXIT_FATAL

    exit_code = int(result.get("exit_code", EXIT_FATAL))
    # Defensive clamp — every exit path MUST be 0 / 1 / 2 per D74
    # contract (Pitfall #9.m self-application — the docstring claims
    # "exit 0/1/2 per D74", so verify the claim).
    if exit_code not in (EXIT_SUCCESS, EXIT_WARNING, EXIT_FATAL):
        logger.error(
            "Non-canonical exit_code %r returned from main(); clamping to EXIT_FATAL",
            exit_code,
        )
        exit_code = EXIT_FATAL
    return exit_code


if __name__ == "__main__":
    sys.exit(cli_main())
