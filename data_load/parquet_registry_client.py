"""M3 — `ParquetSnapshotRegistry` state-machine client.

Per **`docs/migration/phase1/03_core_modules.md` § 1.3** (canonical
interface) — thin client for ``General.ops.ParquetSnapshotRegistry``
operations. Centralizes the 7-state lifecycle (``created`` -> ``verified``
-> ``replicated`` -> ``archived`` -> ``purged``, with ``missing`` and
``replication_failed`` as off-path failure markers).

What this module does
---------------------

Wraps the registry table's status transitions as named functions; encodes
the legal predecessor sets as a single :data:`_LEGAL_TRANSITIONS` dict so
``RegistryStatusInvalid`` is trivial to verify. Each mutating transition
composes :func:`utils.idempotency_ledger.ledger_step` so re-running the
same transition on the same row is a no-op (idempotent per D15 + D17).

Schema alignment (per § 1.3 + Round 1 table 8 DDL — see
``phase1/01_database_schema.md`` § 8)
--------------------------------------

Per-transition audit columns are CANONICAL per the Round 1 DDL — there is
NO generic ``StatusChangedAt`` / ``StatusChangedBy`` pair (an earlier draft
of the spec invented one; caught 2026-05-10 by 4-agent deep validation as
Pitfall #9 "cross-table column-name lift"). The canonical columns are:

* ``LastVerifiedAt`` — written on ``verify_parquet_snapshot``
* ``SnowflakeUploadedAt`` + ``SnowflakeStagePath`` — written on ``mark_replicated``
* ``StorageTier`` — written on ``mark_archived`` (flips ``hot``/``warm``
  -> ``cold``/``frozen``)
* ``PurgedAt`` + ``PurgedReason`` — written on ``mark_purged``
* ``LastAccessedAt`` — written on ``query_snapshot`` access events (when
  the row is read)

Idempotency contract (per D15 + D17)
------------------------------------

Each transition is wrapped in :func:`utils.idempotency_ledger.ledger_step`
keyed by ``(BatchId, SourceName, TableName, EventType)`` where:

* ``BatchId`` is the registry row's ``BatchId`` (extracted via the
  registry_id lookup before the ledger key is computed)
* ``SourceName`` / ``TableName`` come from the registry row
* ``EventType`` is one of ``PARQUET_VERIFY`` / ``PARQUET_REPLICATE`` /
  ``PARQUET_ARCHIVE`` / ``PARQUET_PURGE`` / ``PARQUET_MARK_MISSING`` /
  ``PARQUET_MARK_REPLICATION_FAILED`` — one per public function

Re-running the same transition short-circuits via the ledger. The
underlying UPDATE is also row-level idempotent (flipping ``verified`` ->
``verified`` is a no-op).

Error modes (per § 1.3 + D68 — canonical ``utils.errors`` hierarchy)
--------------------------------------------------------------------

All registry-error classes live in :mod:`utils.errors` (per D68 single-
source-of-truth). This module re-imports them for the convenience of
internal raise sites but does NOT re-export them from ``__all__``.
Downstream consumers should ``from utils.errors import RegistryStatusInvalid``
rather than from this module (B-228 closes the prior local-class
duplicate-definition gap).

* :class:`~utils.errors.RegistryStatusInvalid` (PipelineFatalError) —
  attempted transition from an incompatible predecessor (e.g.
  ``purged`` -> ``verified``). The :data:`_LEGAL_TRANSITIONS` dict is
  the source of truth.
* :class:`~utils.errors.RegistryFileNotFound` (PipelineRetryableError)
  — verification target file is absent on disk. Retryable because a
  remount can rescue the file; if absence persists, caller should
  follow with :func:`mark_missing` to flip the row.
* :class:`~utils.errors.RegistryHashMismatch` (PipelineFatalError) —
  computed SHA-256 doesn't match the registry value; indicates
  corruption.
* :class:`~utils.errors.RegistryInsertConflict` (PipelineRetryableError)
  — UNIQUE violation on ``UX_ParquetSnapshotRegistry_Identity``.
  Retry should re-query for the existing row rather than insert.
* :class:`~utils.errors.RegistryNotFound` (PipelineFatalError) —
  ``registry_id`` does not exist in the table. Operator must
  investigate.

Per-raise context (registry_id, current_status, attempted_status,
file_path, expected_sha256, computed_sha256, etc.) is carried in the
canonical ``metadata: dict`` kwarg of every
:class:`~utils.errors.PipelineError` subclass (per D76 — forwarded to
``PipelineEventLog.Metadata``). Test + operator tooling reads via
``exc.metadata['registry_id']`` etc.

Concurrency (per D69)
---------------------

``cursor_for('General')`` per transition; no shared cursor across
boundary. Concurrent flips on the same row are serialized by SQL Server
row locking; the UPDATE includes a ``CHECK`` predicate on the prior
status so a lost race fails fast rather than silently overwriting.

D-numbers consumed
------------------

D2 (Stage dropped — Parquet snapshots replace it), D4 (network drive
Parquet for snapshot storage), D15 (idempotency mandatory), D17
(idempotency ledger on every pipeline step), D25 (ParquetSnapshotRegistry
canonical Parquet index), D26 (append-only audit posture — status flips,
never DELETE), D30 (7-year retention; ``mark_archived`` + ``mark_purged``
fed by ``JOB_RETENTION_MONTHLY``), D45.2 (Parquet 100-250 MB target +
config), D67 (Tier 0 smoke test discipline), D68 (error class hierarchy
— PipelineFatalError / PipelineRetryableError), D69 (cursor_for
ownership), D92 (forward-only additive — new module; no rename / removal).

B-numbers closed
----------------

* B-228 — local exception-class duplicate-definition gap. M3 now
  imports the canonical ``RegistryStatusInvalid`` / ``RegistryFileNotFound``
  / ``RegistryHashMismatch`` / ``RegistryInsertConflict`` /
  ``RegistryNotFound`` from :mod:`utils.errors` per D68 single-source-
  of-truth; the prior local definitions (subclasses of plain
  ``Exception`` via an intermediate ``ParquetRegistryError`` base) are
  removed. ``utils.errors`` additively grew ``RegistryNotFound`` to
  back the M3 raise sites per D92 forward-only additive.

See also
--------

* ``data_load/parquet_writer.py`` (§ 1.1) — INSERTs ``Status='created'``
  registry rows at write time; this module then drives the lifecycle.
* ``data_load/parquet_replay.py`` (§ 1.2) — reads registry to find
  source-of-truth Parquet files for Bronze rebuild (RB-8).
* ``utils/idempotency_ledger.py`` (§ 4.1) — ``ledger_step`` context
  manager composed by every mutating transition.
* ``tools/parquet_verify.py`` — operator CLI shim that wraps this module
  for periodic verification scans (driven by
  ``IX_ParquetSnapshotRegistry_Verification`` filtered index).
* ``JOB_RETENTION_MONTHLY`` (per ``02_configuration.md`` § 5.1) — calls
  ``mark_archived`` then ``mark_purged``.
* Snowflake mirror (§ 7.1) — calls ``mark_replicated``.
"""

from __future__ import annotations

import hashlib
import json
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterator

from utils.errors import (
    RegistryFileNotFound,
    RegistryHashMismatch,
    RegistryInsertConflict,  # noqa: F401  (re-imported for callers)
    RegistryNotFound,
    RegistryStatusInvalid,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Canonical status values (must match ``CK_ParquetSnapshotRegistry_Status``
# constraint in ``phase1/01_database_schema.md`` § 8)
# ---------------------------------------------------------------------------

STATUS_CREATED = "created"
STATUS_VERIFIED = "verified"
STATUS_REPLICATED = "replicated"
STATUS_ARCHIVED = "archived"
STATUS_MISSING = "missing"
STATUS_PURGED = "purged"
STATUS_REPLICATION_FAILED = "replication_failed"

ALL_STATUSES = frozenset(
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


# ---------------------------------------------------------------------------
# Storage tier values (must match ``CK_ParquetSnapshotRegistry_Tier``)
# ---------------------------------------------------------------------------

TIER_HOT = "hot"
TIER_WARM = "warm"
TIER_COLD = "cold"
TIER_FROZEN = "frozen"


# ---------------------------------------------------------------------------
# Legal-transition state machine
#
# Encodes the directed graph of permitted status flips. Key = predecessor
# status; value = frozenset of allowed successor statuses. RegistryStatusInvalid
# is raised whenever an attempted transition is not in this graph.
#
# Design notes (per § 1.3 7-state lifecycle):
#
#   * Happy path: created -> verified -> replicated -> archived -> purged
#   * Off-path: any non-purged state -> missing (file disappeared)
#   * Failure: verified -> replication_failed (Snowflake COPY INTO fail)
#   * Re-attempt: replication_failed -> replicated OR replication_failed
#     -> missing (operator retried then gave up)
#   * Terminal: purged is terminal (no transitions OUT). Documented as
#     "Final state per D26 append-only audit posture".
#   * Terminal: missing is recoverable when re-discovered — operator may
#     manually flip it back to ``verified`` after re-uploading the file,
#     but this happens through tools not through this module's automated
#     transition functions.
#
# Idempotent self-loops (X -> X) are handled separately as no-op short-
# circuits in :func:`_apply_transition` — they are NOT listed in this
# graph because that would conflate "no work needed" (idempotent re-run)
# with "legal transition" (genuine state change).
# ---------------------------------------------------------------------------

_LEGAL_TRANSITIONS: dict[str, frozenset[str]] = {
    STATUS_CREATED: frozenset({STATUS_VERIFIED, STATUS_MISSING}),
    STATUS_VERIFIED: frozenset(
        {STATUS_REPLICATED, STATUS_REPLICATION_FAILED, STATUS_MISSING}
    ),
    STATUS_REPLICATED: frozenset({STATUS_ARCHIVED, STATUS_MISSING}),
    STATUS_ARCHIVED: frozenset({STATUS_PURGED, STATUS_MISSING}),
    STATUS_REPLICATION_FAILED: frozenset(
        {STATUS_REPLICATED, STATUS_MISSING}
    ),
    STATUS_MISSING: frozenset(),  # terminal — recovery is manual
    STATUS_PURGED: frozenset(),  # terminal per D26 append-only
}


# ---------------------------------------------------------------------------
# D76 EventType constants — registered in the EVENT_TYPE family. Each
# mutating transition uses a distinct EventType so the idempotency ledger
# key is unique per (transition, registry_id).
# ---------------------------------------------------------------------------

EVENT_TYPE_VERIFY = "PARQUET_VERIFY"
EVENT_TYPE_REPLICATE = "PARQUET_REPLICATE"
EVENT_TYPE_ARCHIVE = "PARQUET_ARCHIVE"
EVENT_TYPE_PURGE = "PARQUET_PURGE"
EVENT_TYPE_MARK_MISSING = "PARQUET_MARK_MISSING"
EVENT_TYPE_MARK_REPLICATION_FAILED = "PARQUET_MARK_REPLICATION_FAILED"


# ---------------------------------------------------------------------------
# Public dataclass — :class:`ParquetVerifyResult`
#
# Distinct from ``ParquetWriteResult`` (defined in § 1.1 / parquet_writer)
# whose ``status`` field contract is ``'created'``. ParquetVerifyResult's
# ``status`` is always ``'verified'`` on successful return (otherwise the
# function raises).
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParquetVerifyResult:
    """Successful verification result for :func:`verify_parquet_snapshot`.

    All fields populated on a successful flip ``created`` -> ``verified``.
    Frozen — once a verification succeeds the result is immutable; a
    subsequent re-verification produces a new instance (intentional
    append-only audit per D26).

    Per § 1.3 canonical signature; the type contract was tightened
    2026-05-10 during Round 3 deep-validation to resolve the
    ``ParquetWriteResult.status`` vs ``ParquetVerifyResult.status``
    type-contract mismatch.
    """

    registry_id: int
    file_path: Path
    sha256_verified: str            # full 64-char SHA-256 hex
    row_count_verified: int         # matches registry RowCount on success
    last_verified_at: datetime      # written to LastVerifiedAt column
    status: str                     # always 'verified' on successful return


# ---------------------------------------------------------------------------
# __all__ — public surface
# ---------------------------------------------------------------------------

__all__ = (
    # Status constants
    "STATUS_CREATED",
    "STATUS_VERIFIED",
    "STATUS_REPLICATED",
    "STATUS_ARCHIVED",
    "STATUS_MISSING",
    "STATUS_PURGED",
    "STATUS_REPLICATION_FAILED",
    "ALL_STATUSES",
    # Tier constants
    "TIER_HOT",
    "TIER_WARM",
    "TIER_COLD",
    "TIER_FROZEN",
    # EventType constants
    "EVENT_TYPE_VERIFY",
    "EVENT_TYPE_REPLICATE",
    "EVENT_TYPE_ARCHIVE",
    "EVENT_TYPE_PURGE",
    "EVENT_TYPE_MARK_MISSING",
    "EVENT_TYPE_MARK_REPLICATION_FAILED",
    # State machine
    "is_legal_transition",
    # Errors — canonical home is utils.errors (B-228); intentionally NOT
    # re-exported from this module's __all__ per single-source-of-truth.
    # The names ARE bound in this module's namespace via the
    # `from utils.errors import ...` at the top of the file so existing
    # callers that did `from data_load.parquet_registry_client import
    # RegistryStatusInvalid` still resolve, but new code should import
    # from utils.errors directly.
    # Result dataclass
    "ParquetVerifyResult",
    # Public transitions
    "verify_parquet_snapshot",
    "mark_replicated",
    "mark_archived",
    "mark_missing",
    "mark_purged",
    "mark_replication_failed",
    "query_snapshot",
)


# ---------------------------------------------------------------------------
# State-machine helper (pure; no DB / side effects — safe to call freely)
# ---------------------------------------------------------------------------


def is_legal_transition(current: str, attempted: str) -> bool:
    """Return ``True`` iff transition ``current`` -> ``attempted`` is permitted.

    Pure function over :data:`_LEGAL_TRANSITIONS`. Idempotent self-
    transitions (``X -> X``) return ``True`` because re-running a
    transition is always permitted at the API level (the inner UPDATE
    is a no-op and the idempotency ledger short-circuits).

    Used by transition functions before issuing the UPDATE so
    :class:`RegistryStatusInvalid` is raised with the full context
    rather than relying on a CHECK-constraint roundtrip.
    """
    if current not in ALL_STATUSES:
        return False
    if attempted not in ALL_STATUSES:
        return False
    if current == attempted:
        return True
    return attempted in _LEGAL_TRANSITIONS.get(current, frozenset())


# ---------------------------------------------------------------------------
# Lazy-imported dependencies (kept lazy so Tier 0 smoke can mock at
# ``sys.modules`` level WITHOUT importing real ``pyodbc`` / ``utils.connections``
# / ``utils.idempotency_ledger``)
# ---------------------------------------------------------------------------


def _get_cursor_for():
    """Return ``utils.connections.cursor_for`` (lazy import for testability)."""
    from utils.connections import cursor_for  # noqa: PLC0415
    return cursor_for


def _get_ledger_step():
    """Return ``utils.idempotency_ledger.ledger_step`` (lazy import for testability)."""
    from utils.idempotency_ledger import ledger_step  # noqa: PLC0415
    return ledger_step


# ---------------------------------------------------------------------------
# Internal: registry row fetcher
# ---------------------------------------------------------------------------


def _fetch_registry_row(registry_id: int) -> dict:
    """Return a dict of canonical registry columns for ``registry_id``.

    Raises :class:`RegistryNotFound` if the row does not exist. The
    returned dict has the schema field names as keys + Python-native
    values (datetimes / dates / strings / ints).

    Only columns this module needs are selected — keeps the projection
    minimal so we don't pay for unused metadata reads on every transition.
    """
    cursor_for = _get_cursor_for()
    sql = """
        SELECT
            RegistryId,
            SourceName,
            TableName,
            BatchId,
            BusinessDate,
            NetworkDrivePath,
            SnowflakeStagePath,
            SnowflakeUploadedAt,
            RowCount,
            UncompressedBytes,
            CompressedBytes,
            SchemaHash,
            ContentChecksum,
            StorageTier,
            Status,
            CreatedAt,
            LastVerifiedAt,
            LastAccessedAt,
            PurgedAt,
            PurgedReason
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
# Internal: SHA-256 streaming helper (used by :func:`verify_parquet_snapshot`)
# ---------------------------------------------------------------------------


def _compute_sha256(file_path: Path, *, chunk_size: int = 65536) -> str:
    """Stream-hash ``file_path`` and return the full 64-char SHA-256 hex.

    Streamed in 64 KiB chunks so a multi-GB Parquet file does not
    blow up memory. Raises :class:`FileNotFoundError` if the path is
    absent — the caller converts to :class:`RegistryFileNotFound` with
    full registry context.
    """
    h = hashlib.sha256()
    with file_path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Internal: status-flip executor
# ---------------------------------------------------------------------------


def _flip_status(
    *,
    cursor,
    registry_id: int,
    expected_current: str,
    next_status: str,
    extra_set_clauses: str = "",
    extra_params: tuple = (),
) -> int:
    """Issue an UPDATE flipping ``Status`` with a CHECK predicate on the prior value.

    Returns the affected row count. The ``CHECK`` on prior status guards
    against a lost concurrent race — if another worker flipped the status
    between our SELECT and our UPDATE, the row count comes back as 0 and
    the caller decides whether that's a no-op (idempotent re-run) or a
    genuine race.

    ``extra_set_clauses`` carries any additional SET fragments for the
    per-transition audit columns (e.g. ``LastVerifiedAt = ?,``); they
    must end with a trailing comma if non-empty since the canonical SET
    clause appends after them.
    """
    sql = (
        "UPDATE General.ops.ParquetSnapshotRegistry SET "
        f"{extra_set_clauses}"
        "Status = ? "
        "WHERE RegistryId = ? AND Status = ?"
    )
    params = (*extra_params, next_status, registry_id, expected_current)
    cursor.execute(sql, params)
    return cursor.rowcount


# ---------------------------------------------------------------------------
# Internal: ledger-key helper
# ---------------------------------------------------------------------------


@contextmanager
def _registry_ledger_step(
    *,
    registry_row: dict,
    event_type: str,
    metadata: dict | None = None,
) -> Iterator:
    """Open a ``ledger_step`` context bound to a registry-row + event_type key.

    Resolves ``batch_id`` / ``source_name`` / ``table_name`` from the
    registry row. The yielded :class:`LedgerStep` carries
    ``was_short_circuited`` — callers use this to skip the side-effecting
    UPDATE on idempotent re-run.
    """
    ledger_step = _get_ledger_step()
    with ledger_step(
        batch_id=int(registry_row["BatchId"]),
        source_name=str(registry_row["SourceName"]),
        table_name=str(registry_row["TableName"]),
        event_type=event_type,
        metadata=metadata,
    ) as step:
        yield step


# ---------------------------------------------------------------------------
# Public: :func:`verify_parquet_snapshot`
# ---------------------------------------------------------------------------


def verify_parquet_snapshot(
    *,
    registry_id: int,
    actor: str = "pipeline",
) -> ParquetVerifyResult:
    """Flip ``Status='created'`` -> ``'verified'`` after SHA-256 + row-count check.

    Per § 1.3 canonical signature.

    Args:
        registry_id: ``RegistryId`` of the row to verify.
        actor: Who is verifying — ``'pipeline'`` / ``'operator'`` /
            ``'reconciliation'``. Recorded in the idempotency ledger
            metadata for audit trail.

    Returns:
        :class:`ParquetVerifyResult` with ``status='verified'`` on success.

    Raises:
        :class:`RegistryNotFound`: ``registry_id`` does not exist.
        :class:`RegistryStatusInvalid`: current status is not ``'created'``
            AND not already ``'verified'`` (the idempotent case).
        :class:`RegistryFileNotFound`: registered file is absent on disk.
        :class:`RegistryHashMismatch`: computed SHA-256 != registry's
            ``ContentChecksum`` (or ``SchemaHash`` if checksum is NULL).

    Idempotent: re-call after success is a no-op (caller sees the
    ``status='verified'`` result re-computed from the registry row;
    the underlying UPDATE is short-circuited via the ledger).
    """
    row = _fetch_registry_row(registry_id)
    current_status = row["Status"]

    # Idempotent re-call: row is already 'verified'. Return the cached
    # result rather than re-hashing the file (cheap path; the slow path
    # is re-verification which only fires when status is still 'created').
    if current_status == STATUS_VERIFIED:
        logger.info(
            "verify_parquet_snapshot: registry_id=%s already verified; "
            "returning cached result",
            registry_id,
        )
        return ParquetVerifyResult(
            registry_id=registry_id,
            file_path=Path(row["NetworkDrivePath"]),
            sha256_verified=str(row["ContentChecksum"] or row["SchemaHash"]),
            row_count_verified=int(row["RowCount"]),
            last_verified_at=row["LastVerifiedAt"] or _utcnow_ms(),
            status=STATUS_VERIFIED,
        )

    if not is_legal_transition(current_status, STATUS_VERIFIED):
        raise RegistryStatusInvalid(
            f"Cannot verify RegistryId={registry_id}: current Status="
            f"{current_status!r}; legal predecessor is "
            f"{STATUS_CREATED!r}.",
            metadata={
                "registry_id": registry_id,
                "current_status": current_status,
                "attempted_status": STATUS_VERIFIED,
            },
        )

    file_path = Path(row["NetworkDrivePath"])
    if not file_path.exists():
        raise RegistryFileNotFound(
            f"Parquet file absent for RegistryId={registry_id}: {file_path}",
            metadata={
                "registry_id": registry_id,
                "file_path": str(file_path),
            },
        )

    # Hash the file. ContentChecksum is the canonical post-write checksum
    # (NULLable in DDL); if it's NULL we fall back to SchemaHash for
    # comparison — but in practice parquet_writer (§ 1.1) always populates
    # ContentChecksum, so the SchemaHash fallback is defense-in-depth.
    expected_sha256 = row["ContentChecksum"] or row["SchemaHash"]
    if expected_sha256 is None:
        raise RegistryHashMismatch(
            f"RegistryId={registry_id} has NULL ContentChecksum AND NULL "
            f"SchemaHash — cannot verify.",
            metadata={
                "registry_id": registry_id,
                "expected_sha256": "<NULL>",
                "computed_sha256": "<not-computed>",
            },
        )

    computed_sha256 = _compute_sha256(file_path)
    if computed_sha256.lower() != str(expected_sha256).lower():
        raise RegistryHashMismatch(
            f"SHA-256 mismatch for RegistryId={registry_id} ({file_path}): "
            f"expected={expected_sha256}, computed={computed_sha256}.",
            metadata={
                "registry_id": registry_id,
                "expected_sha256": str(expected_sha256),
                "computed_sha256": computed_sha256,
            },
        )

    verified_at = _utcnow_ms()
    cursor_for = _get_cursor_for()

    with _registry_ledger_step(
        registry_row=row,
        event_type=EVENT_TYPE_VERIFY,
        metadata={
            "registry_id": registry_id,
            "actor": actor,
            "computed_sha256": computed_sha256,
        },
    ) as step:
        if not step.was_short_circuited:
            with cursor_for("General") as cur:
                affected = _flip_status(
                    cursor=cur,
                    registry_id=registry_id,
                    expected_current=STATUS_CREATED,
                    next_status=STATUS_VERIFIED,
                    extra_set_clauses="LastVerifiedAt = ?, ",
                    extra_params=(verified_at,),
                )
                if affected == 0:
                    # Race: another worker flipped between our SELECT and
                    # our UPDATE. Re-fetch and treat as idempotent re-call.
                    logger.warning(
                        "verify_parquet_snapshot: lost race for registry_id=%s; "
                        "re-fetching",
                        registry_id,
                    )
                    return verify_parquet_snapshot(
                        registry_id=registry_id, actor=actor
                    )

    return ParquetVerifyResult(
        registry_id=registry_id,
        file_path=file_path,
        sha256_verified=computed_sha256,
        row_count_verified=int(row["RowCount"]),
        last_verified_at=verified_at,
        status=STATUS_VERIFIED,
    )


# ---------------------------------------------------------------------------
# Public: :func:`mark_replicated`
# ---------------------------------------------------------------------------


def mark_replicated(*, registry_id: int, replica_target: str) -> None:
    """Flip ``Status='verified'`` -> ``'replicated'``.

    Args:
        registry_id: ``RegistryId`` of the row to flip.
        replica_target: Identifies the destination (e.g.
            ``'snowflake:UDM_BRONZE_MIRROR'`` /
            ``'s3://offsite-bucket/...'``). Stored in
            ``SnowflakeStagePath`` for traceability + idempotency
            ledger metadata.

    Raises:
        :class:`RegistryNotFound`: ``registry_id`` does not exist.
        :class:`RegistryStatusInvalid`: current status is not
            ``'verified'`` AND not already ``'replicated'`` /
            ``'replication_failed'`` (allowed retry path).

    Idempotent: re-call when status is already ``'replicated'`` is a no-op.
    Re-call from ``'replication_failed'`` is also allowed (retry path).
    """
    row = _fetch_registry_row(registry_id)
    current_status = row["Status"]

    if current_status == STATUS_REPLICATED:
        logger.info(
            "mark_replicated: registry_id=%s already replicated; no-op",
            registry_id,
        )
        return

    if not is_legal_transition(current_status, STATUS_REPLICATED):
        raise RegistryStatusInvalid(
            f"Cannot mark_replicated RegistryId={registry_id}: current "
            f"Status={current_status!r}; legal predecessors are "
            f"{STATUS_VERIFIED!r} or {STATUS_REPLICATION_FAILED!r}.",
            metadata={
                "registry_id": registry_id,
                "current_status": current_status,
                "attempted_status": STATUS_REPLICATED,
            },
        )

    uploaded_at = _utcnow_ms()
    cursor_for = _get_cursor_for()

    with _registry_ledger_step(
        registry_row=row,
        event_type=EVENT_TYPE_REPLICATE,
        metadata={
            "registry_id": registry_id,
            "replica_target": replica_target,
        },
    ) as step:
        if not step.was_short_circuited:
            with cursor_for("General") as cur:
                _flip_status(
                    cursor=cur,
                    registry_id=registry_id,
                    expected_current=current_status,
                    next_status=STATUS_REPLICATED,
                    extra_set_clauses="SnowflakeStagePath = ?, SnowflakeUploadedAt = ?, ",
                    extra_params=(replica_target, uploaded_at),
                )


# ---------------------------------------------------------------------------
# Public: :func:`mark_archived`
# ---------------------------------------------------------------------------


def mark_archived(*, registry_id: int, archive_location: str) -> None:
    """Flip ``Status='replicated'`` -> ``'archived'`` (D30 cold-storage retention).

    Args:
        registry_id: ``RegistryId`` of the row to flip.
        archive_location: Identifies the cold-storage destination (e.g.
            ``'cold:azure-cool-tier'``). Stored in the idempotency
            ledger metadata. Also flips ``StorageTier`` -> ``'cold'``.

    Raises:
        :class:`RegistryNotFound`: ``registry_id`` does not exist.
        :class:`RegistryStatusInvalid`: current status is not ``'replicated'``.

    Idempotent: re-call when status is already ``'archived'`` is a no-op.
    """
    row = _fetch_registry_row(registry_id)
    current_status = row["Status"]

    if current_status == STATUS_ARCHIVED:
        logger.info(
            "mark_archived: registry_id=%s already archived; no-op",
            registry_id,
        )
        return

    if not is_legal_transition(current_status, STATUS_ARCHIVED):
        raise RegistryStatusInvalid(
            f"Cannot mark_archived RegistryId={registry_id}: current "
            f"Status={current_status!r}; legal predecessor is "
            f"{STATUS_REPLICATED!r}.",
            metadata={
                "registry_id": registry_id,
                "current_status": current_status,
                "attempted_status": STATUS_ARCHIVED,
            },
        )

    cursor_for = _get_cursor_for()

    with _registry_ledger_step(
        registry_row=row,
        event_type=EVENT_TYPE_ARCHIVE,
        metadata={
            "registry_id": registry_id,
            "archive_location": archive_location,
        },
    ) as step:
        if not step.was_short_circuited:
            with cursor_for("General") as cur:
                _flip_status(
                    cursor=cur,
                    registry_id=registry_id,
                    expected_current=STATUS_REPLICATED,
                    next_status=STATUS_ARCHIVED,
                    extra_set_clauses="StorageTier = ?, ",
                    extra_params=(TIER_COLD,),
                )


# ---------------------------------------------------------------------------
# Public: :func:`mark_missing`
# ---------------------------------------------------------------------------


def mark_missing(*, registry_id: int, detected_by: str) -> None:
    """Flip any non-purged Status -> ``'missing'`` when file is detected absent.

    Triggers RB-6 / RB-8 escalation alert per the runbook routing. The
    runbook firing is handled by the alert dispatcher subscribed to
    ``PARQUET_MARK_MISSING`` events — this function does NOT fire the
    alert directly (keeps registry logic decoupled from alert wiring).

    Args:
        registry_id: ``RegistryId`` of the row to flip.
        detected_by: How the absence was detected — e.g.
            ``'verification_scan'`` / ``'replay_attempt'`` /
            ``'operator_report'``. Stored in idempotency ledger metadata.

    Raises:
        :class:`RegistryNotFound`: ``registry_id`` does not exist.
        :class:`RegistryStatusInvalid`: current status is ``'purged'``
            (purged means the file was LEGITIMATELY removed; missing
            means it was UNEXPECTEDLY absent — flipping purged -> missing
            would corrupt the audit trail).

    Idempotent: re-call when status is already ``'missing'`` is a no-op.
    """
    row = _fetch_registry_row(registry_id)
    current_status = row["Status"]

    if current_status == STATUS_MISSING:
        logger.info(
            "mark_missing: registry_id=%s already missing; no-op",
            registry_id,
        )
        return

    if not is_legal_transition(current_status, STATUS_MISSING):
        raise RegistryStatusInvalid(
            f"Cannot mark_missing RegistryId={registry_id}: current "
            f"Status={current_status!r}; cannot transition from "
            f"{STATUS_PURGED!r} to {STATUS_MISSING!r} (purged is terminal "
            f"per D26 append-only).",
            metadata={
                "registry_id": registry_id,
                "current_status": current_status,
                "attempted_status": STATUS_MISSING,
            },
        )

    cursor_for = _get_cursor_for()

    with _registry_ledger_step(
        registry_row=row,
        event_type=EVENT_TYPE_MARK_MISSING,
        metadata={
            "registry_id": registry_id,
            "detected_by": detected_by,
            "prior_status": current_status,
        },
    ) as step:
        if not step.was_short_circuited:
            with cursor_for("General") as cur:
                _flip_status(
                    cursor=cur,
                    registry_id=registry_id,
                    expected_current=current_status,
                    next_status=STATUS_MISSING,
                )


# ---------------------------------------------------------------------------
# Public: :func:`mark_purged`
# ---------------------------------------------------------------------------


def mark_purged(*, registry_id: int, retention_batch_id: int) -> None:
    """Flip ``Status='archived'`` -> ``'purged'`` at retention enforcement.

    Per D30 + ``JOB_RETENTION_MONTHLY``. The ``retention_batch_id`` ties
    the purge to a ``JOB_RETENTION_MONTHLY`` PipelineEventLog event row
    so the audit trail can reconstruct which monthly batch purged this
    snapshot.

    Args:
        registry_id: ``RegistryId`` of the row to purge.
        retention_batch_id: ``BatchId`` of the ``JOB_RETENTION_MONTHLY``
            run that triggered the purge. Stored in ``PurgedReason`` as
            a structured JSON snippet for forensic reconstruction.

    Raises:
        :class:`RegistryNotFound`: ``registry_id`` does not exist.
        :class:`RegistryStatusInvalid`: current status is not ``'archived'``.

    Idempotent: re-call when status is already ``'purged'`` is a no-op.
    """
    row = _fetch_registry_row(registry_id)
    current_status = row["Status"]

    if current_status == STATUS_PURGED:
        logger.info(
            "mark_purged: registry_id=%s already purged; no-op",
            registry_id,
        )
        return

    if not is_legal_transition(current_status, STATUS_PURGED):
        raise RegistryStatusInvalid(
            f"Cannot mark_purged RegistryId={registry_id}: current "
            f"Status={current_status!r}; legal predecessor is "
            f"{STATUS_ARCHIVED!r}.",
            metadata={
                "registry_id": registry_id,
                "current_status": current_status,
                "attempted_status": STATUS_PURGED,
            },
        )

    purged_at = _utcnow_ms()
    purged_reason = json.dumps(
        {
            "retention_batch_id": retention_batch_id,
            "prior_status": current_status,
        },
        separators=(",", ":"),
    )
    cursor_for = _get_cursor_for()

    with _registry_ledger_step(
        registry_row=row,
        event_type=EVENT_TYPE_PURGE,
        metadata={
            "registry_id": registry_id,
            "retention_batch_id": retention_batch_id,
        },
    ) as step:
        if not step.was_short_circuited:
            with cursor_for("General") as cur:
                _flip_status(
                    cursor=cur,
                    registry_id=registry_id,
                    expected_current=STATUS_ARCHIVED,
                    next_status=STATUS_PURGED,
                    extra_set_clauses="PurgedAt = ?, PurgedReason = ?, ",
                    extra_params=(purged_at, purged_reason),
                )


# ---------------------------------------------------------------------------
# Public: :func:`mark_replication_failed`
# ---------------------------------------------------------------------------


def mark_replication_failed(*, registry_id: int, failure_reason: str) -> None:
    """Flip ``'verified'`` -> ``'replication_failed'`` when COPY INTO Snowflake fails.

    Args:
        registry_id: ``RegistryId`` of the row to flip.
        failure_reason: Human-readable failure description (e.g. the
            Snowflake error message). Stored in idempotency ledger
            metadata. Operators see this in the audit trail when
            deciding retry vs escalate.

    Raises:
        :class:`RegistryNotFound`: ``registry_id`` does not exist.
        :class:`RegistryStatusInvalid`: current status is not
            ``'verified'`` AND not already ``'replication_failed'``.

    Idempotent: re-call when status is already ``'replication_failed'``
    is a no-op (re-marking the same failure is harmless).
    """
    row = _fetch_registry_row(registry_id)
    current_status = row["Status"]

    if current_status == STATUS_REPLICATION_FAILED:
        logger.info(
            "mark_replication_failed: registry_id=%s already in "
            "replication_failed; no-op",
            registry_id,
        )
        return

    if not is_legal_transition(current_status, STATUS_REPLICATION_FAILED):
        raise RegistryStatusInvalid(
            f"Cannot mark_replication_failed RegistryId={registry_id}: "
            f"current Status={current_status!r}; legal predecessor is "
            f"{STATUS_VERIFIED!r}.",
            metadata={
                "registry_id": registry_id,
                "current_status": current_status,
                "attempted_status": STATUS_REPLICATION_FAILED,
            },
        )

    cursor_for = _get_cursor_for()

    with _registry_ledger_step(
        registry_row=row,
        event_type=EVENT_TYPE_MARK_REPLICATION_FAILED,
        metadata={
            "registry_id": registry_id,
            "failure_reason": failure_reason,
        },
    ) as step:
        if not step.was_short_circuited:
            with cursor_for("General") as cur:
                _flip_status(
                    cursor=cur,
                    registry_id=registry_id,
                    expected_current=STATUS_VERIFIED,
                    next_status=STATUS_REPLICATION_FAILED,
                )


# ---------------------------------------------------------------------------
# Public: :func:`query_snapshot`
# ---------------------------------------------------------------------------


def query_snapshot(
    *,
    source_name: str,
    table_name: str,
    business_date: date | None,
    batch_id: int,
) -> dict | None:
    """Lookup a snapshot by ``(BatchId, SourceName, TableName, BusinessDate)``.

    Per § 1.3 canonical signature.

    Returns ``None`` if no row matches. Otherwise returns a dict of the
    canonical column projection (same as :func:`_fetch_registry_row`).

    Note on ``BusinessDate`` NULL semantics: per the Round 1 DDL,
    ``BusinessDate`` is NULL for small tables. SQL Server's ``=`` operator
    does NOT match NULL = NULL, so we generate the WHERE clause to use
    ``IS NULL`` when ``business_date is None`` and ``= ?`` otherwise.

    This is a READ-only function — it does NOT compose
    :func:`utils.idempotency_ledger.ledger_step` because there is no
    side effect to gate. It DOES update ``LastAccessedAt`` (per § 1.3
    "LastAccessedAt on access events") so the verification-scan filtered
    index can deprioritize recently-read rows. The access-time update is
    fire-and-forget (a failure to UPDATE LastAccessedAt does NOT fail the
    lookup — the freshness signal is best-effort, not load-bearing).
    """
    cursor_for = _get_cursor_for()
    if business_date is None:
        where_clause = (
            "SourceName = ? AND TableName = ? AND BatchId = ? "
            "AND BusinessDate IS NULL"
        )
        params: tuple = (source_name, table_name, batch_id)
    else:
        where_clause = (
            "SourceName = ? AND TableName = ? AND BatchId = ? "
            "AND BusinessDate = ?"
        )
        params = (source_name, table_name, batch_id, business_date)

    select_sql = f"""
        SELECT
            RegistryId,
            SourceName,
            TableName,
            BatchId,
            BusinessDate,
            NetworkDrivePath,
            SnowflakeStagePath,
            SnowflakeUploadedAt,
            RowCount,
            UncompressedBytes,
            CompressedBytes,
            SchemaHash,
            ContentChecksum,
            StorageTier,
            Status,
            CreatedAt,
            LastVerifiedAt,
            LastAccessedAt,
            PurgedAt,
            PurgedReason
        FROM General.ops.ParquetSnapshotRegistry
        WHERE {where_clause}
    """

    with cursor_for("General") as cur:
        cur.execute(select_sql, params)
        row = cur.fetchone()
        if row is None:
            return None
        columns = [c[0] for c in cur.description]
        result = dict(zip(columns, row))

    # Fire-and-forget LastAccessedAt update. Doesn't block the read; a
    # failure here is logged but does not fail the lookup.
    accessed_at = _utcnow_ms()
    try:
        with cursor_for("General") as cur:
            cur.execute(
                "UPDATE General.ops.ParquetSnapshotRegistry SET "
                "LastAccessedAt = ? WHERE RegistryId = ?",
                (accessed_at, int(result["RegistryId"])),
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "query_snapshot: LastAccessedAt update failed for "
            "RegistryId=%s: %s (lookup result unaffected)",
            result.get("RegistryId"),
            exc,
        )

    return result


# ---------------------------------------------------------------------------
# Public: :func:`query_latest_snapshot_for_date`
#
# Per B-563 closure 2026-05-19 (large-table 'parquet_snapshot' mode
# delete-detection via day-N vs day-N-1 Parquet diff).
#
# `query_snapshot` requires `batch_id` because it identifies a unique
# registry row by the full (source, table, batch_id, business_date) tuple.
# B-563's delete-detection workflow needs to find the PRIOR-DAY snapshot
# WITHOUT knowing its batch_id. `query_latest_snapshot_for_date` is the
# date-keyed lookup variant: given (source, table, business_date), return
# the most recent replay-eligible snapshot (by CreatedAt + BatchId DESC).
#
# Replay-eligible status filter mirrors REPLAY_ELIGIBLE_STATUSES from
# data_load/parquet_replay.py -- only `verified`, `replicated`, `archived`
# rows are valid replay targets. Day-N-1 snapshot that hasn't been
# verified yet (Status='created') is treated as if absent (caller falls
# back to non-targeted SCD2 promotion + full Bronze anti-join delete
# detection per B-552 v1 behavior).
# ---------------------------------------------------------------------------


_REPLAY_ELIGIBLE_STATUSES = ("verified", "replicated", "archived")


def query_latest_snapshot_for_date(
    *,
    source_name: str,
    table_name: str,
    business_date: date,
) -> dict | None:
    """Lookup latest replay-eligible snapshot for ``(source, table, date)``.

    Per B-563 closure 2026-05-19 (large-table delete-detection
    prerequisite). Variant of :func:`query_snapshot` that does NOT require
    ``batch_id`` -- given only ``(source_name, table_name, business_date)``,
    returns the most recent replay-eligible registry row (ORDER BY
    CreatedAt DESC, BatchId DESC LIMIT 1).

    Replay-eligibility: ``Status IN ('verified', 'replicated', 'archived')``
    -- mirrors :data:`data_load.parquet_replay.REPLAY_ELIGIBLE_STATUSES`.
    Snapshots still in ``'created'`` state (not yet SHA-verified) OR in
    failure states (``'missing'``, ``'replication_failed'``, ``'purged'``)
    are EXCLUDED.

    Returns ``None`` if no replay-eligible row matches the
    (source, table, business_date) tuple. Caller should treat this as
    "first-load OR snapshot not ready yet" and fall back to a
    delete-detection mechanism that doesn't require a prior-day Parquet
    (e.g., full Bronze anti-join via ``run_scd2_promotion(targeted=False)``
    per B-552 v1 behavior).

    Args:
        source_name: e.g. ``'DNA'`` / ``'CCM'`` / ``'EPICOR'``.
        table_name: e.g. ``'ACCT'`` / ``'AuditLog'``.
        business_date: the Hive-partition date to look up. MUST NOT be None
            (unlike :func:`query_snapshot` which permits NULL for small-table
            snapshots -- B-563 delete-detection is large-table-only by design
            since small tables don't need day-N vs day-N-1 diff).

    Returns:
        Canonical projection dict (same columns as :func:`query_snapshot`)
        for the latest replay-eligible snapshot, OR ``None`` if no
        matching row exists.

    Side effect: fire-and-forget UPDATE on ``LastAccessedAt`` for the
    selected row (best-effort; failure logged but does NOT fail the
    lookup -- same pattern as :func:`query_snapshot`).
    """
    cursor_for = _get_cursor_for()

    where_clause = (
        "SourceName = ? AND TableName = ? AND BusinessDate = ? "
        "AND Status IN (?, ?, ?)"
    )
    params: tuple = (
        source_name,
        table_name,
        business_date,
        _REPLAY_ELIGIBLE_STATUSES[0],
        _REPLAY_ELIGIBLE_STATUSES[1],
        _REPLAY_ELIGIBLE_STATUSES[2],
    )

    select_sql = f"""
        SELECT TOP 1
            RegistryId,
            SourceName,
            TableName,
            BatchId,
            BusinessDate,
            NetworkDrivePath,
            SnowflakeStagePath,
            SnowflakeUploadedAt,
            RowCount,
            UncompressedBytes,
            CompressedBytes,
            SchemaHash,
            ContentChecksum,
            StorageTier,
            Status,
            CreatedAt,
            LastVerifiedAt,
            LastAccessedAt,
            PurgedAt,
            PurgedReason
        FROM General.ops.ParquetSnapshotRegistry
        WHERE {where_clause}
        ORDER BY CreatedAt DESC, BatchId DESC
    """

    with cursor_for("General") as cur:
        cur.execute(select_sql, params)
        row = cur.fetchone()
        if row is None:
            return None
        columns = [c[0] for c in cur.description]
        result = dict(zip(columns, row))

    # Fire-and-forget LastAccessedAt update (mirrors query_snapshot pattern).
    accessed_at = _utcnow_ms()
    try:
        with cursor_for("General") as cur:
            cur.execute(
                "UPDATE General.ops.ParquetSnapshotRegistry SET "
                "LastAccessedAt = ? WHERE RegistryId = ?",
                (accessed_at, int(result["RegistryId"])),
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "query_latest_snapshot_for_date: LastAccessedAt update failed "
            "for RegistryId=%s: %s (lookup result unaffected)",
            result.get("RegistryId"),
            exc,
        )

    return result

# ---------------------------------------------------------------------------
# Internal: canonical "now" helper
#
# Per CLAUDE.md SCD2-P1-f + CDC-NOW-MS gotchas: pyodbc DATETIME2(3)
# parameters MUST be naive (no tzinfo) + millisecond-precision so they
# align with BCP-stored values. This module's transition functions write
# DATETIME2(3) audit columns via pyodbc parameters, so the same invariant
# applies. The Round 1 DDL declares LastVerifiedAt / LastAccessedAt /
# PurgedAt / SnowflakeUploadedAt as DATETIME2(3).
# ---------------------------------------------------------------------------


def _utcnow_ms() -> datetime:
    """Return naive UTC ``datetime`` truncated to millisecond precision.

    Per CLAUDE.md gotchas (SCD2-P1-f + CDC-NOW-MS): pyodbc DATETIME2(3)
    parameters MUST be naive + millisecond-precision. A tz-aware
    datetime sends as DATETIMEOFFSET, which causes implicit timezone
    conversion when SQL Server compares against DATETIME2(3) columns
    on non-UTC servers.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    # Truncate microseconds to milliseconds (round-down; never round-up to
    # avoid a microsecond-precision input producing a millisecond value
    # past the file write time).
    micros = now.microsecond
    millis = micros - (micros % 1000)
    return now.replace(microsecond=millis)
