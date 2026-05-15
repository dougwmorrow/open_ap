"""M2 — ``ParquetSnapshotRegistry`` replay reader.

Per **`docs/migration/phase1/03_core_modules.md` § 1.2** (canonical
interface) — read a registered Parquet snapshot, verify its SHA-256 against
the registry-recorded hash, and return a Polars DataFrame ready to feed
``scd2/engine.py``'s ``run_scd2()`` / ``run_scd2_targeted()``. Used by:

* **RB-8** (Bronze rebuild from Parquet) — the canonical use case.
* **Round 5 / Round 7 reconciliation** — when Bronze drift is detected
  against the registry-canonical snapshot, replay rebuilds the affected
  partition without re-extracting from the source system.

What this module does
---------------------

The public surface is one function, :func:`replay_parquet_snapshot`. It:

1. Looks up the registry row via M3's :func:`query_snapshot` keyed by
   ``(source_name, table_name, business_date, original_batch_id)``.
2. Verifies the row's ``Status`` is in the replay-eligible set
   (``verified`` / ``replicated`` / ``archived``); raises
   :class:`~utils.errors.RegistryStatusInvalid` otherwise.
3. Opens the file at the registry's ``NetworkDrivePath``; raises
   :class:`~utils.errors.ParquetReplayError` if absent.
4. Computes the file's SHA-256; raises
   :class:`~utils.errors.ParquetReplayError` if it does NOT match the
   registry-recorded hash (corruption signal — escalate to RB-6 vault
   recovery + RB-8 rebuild).
5. Reads the file via :func:`polars.read_parquet` into an in-memory
   DataFrame.
6. Wraps steps 3-5 in :func:`utils.idempotency_ledger.ledger_step`
   keyed by ``(replay_batch_id, source_name, table_name,
   EventType='REPLAY')`` so re-running the same replay short-circuits
   via the ledger (idempotency contract per D15 + D17).

The returned :class:`ReplayResult` carries the materialized DataFrame
plus provenance (``registry_id``, ``source_file``, ``row_count``,
``sha256_verified``, ``extracted_at``, ``batch_id``). Callers feed
``result.df`` into the SCD2 promotion path.

Schema alignment (per § 1.2 + Round 1 table 8 DDL)
--------------------------------------------------

The registry projection consumed by this module:

* ``RegistryId`` — surfaced in ``ReplayResult.registry_id`` for audit.
* ``NetworkDrivePath`` — the on-disk Parquet file location.
* ``ContentChecksum`` (fallback to ``SchemaHash``) — the expected
  SHA-256 hex. The fallback mirrors M3's :func:`verify_parquet_snapshot`
  pattern; in practice the writer (M1) always populates
  ``ContentChecksum`` post-write, but defense-in-depth covers schema-
  evolution-era rows where ``ContentChecksum`` may be NULL.
* ``RowCount`` — surfaced in ``ReplayResult.row_count`` for audit.
* ``CreatedAt`` — surfaced as ``ReplayResult.extracted_at`` per § 1.2
  "original extraction timestamp from snapshot". The registry has no
  separate ``ExtractedAt`` column; the row was INSERTed by the writer
  immediately post-write, so ``CreatedAt`` IS the canonical extraction
  timestamp.
* ``BatchId`` — surfaced as ``ReplayResult.batch_id`` (the ORIGINAL
  snapshot's BatchId, not the replay's).
* ``Status`` — gates the eligibility check; replay-eligible statuses
  are ``verified`` / ``replicated`` / ``archived``.

Idempotency contract (per D15 + D17)
------------------------------------

The replay is gated on :func:`utils.idempotency_ledger.ledger_step`
keyed by ``(replay_batch_id, source_name, table_name,
EventType='REPLAY')``. Re-call with the SAME ``replay_batch_id``
short-circuits via the ledger (``Status='COMPLETED'``) — the file is
re-read but the side effect (the ledger row INSERT) is not duplicated.

Re-call with a DIFFERENT ``replay_batch_id`` produces a NEW audit event
row (intentional — operator-triggered re-replays should be auditable,
distinct from accidental retries of the same replay).

Note on "re-read on short-circuit": short-circuit just means the
ledger row already exists with ``Status='COMPLETED'``; the DataFrame
materialization is part of the replay's return contract, so we ALWAYS
re-read the file (the read is the "result" the caller needs).
Idempotency is about not duplicating SIDE EFFECTS — and reading the
file is a side-effect-free read.

Error modes (per § 1.2 + D68 — canonical ``utils.errors`` hierarchy)
--------------------------------------------------------------------

All exceptions imported from :mod:`utils.errors` per D68 single-source-
of-truth (B-228 lesson — no local class duplicates):

* :class:`~utils.errors.ParquetReplayError` (PipelineFatalError) — file
  missing OR SHA-256 mismatch. Corruption signal; escalate to RB-6 +
  RB-8.
* :class:`~utils.errors.RegistryStatusInvalid` (PipelineFatalError) —
  caller passed an ``original_batch_id`` that resolves to a registry
  row with ``Status NOT IN ('verified', 'replicated', 'archived')``.
  The verifier hasn't run, the file is gone, or the registry row is
  in a non-replay-eligible state.
* :class:`~utils.errors.RegistryNotFound` (PipelineFatalError) — the
  ``(source_name, table_name, business_date, original_batch_id)``
  tuple does not resolve to any registry row. Operator must
  investigate (typically a typo or a stale audit reference).
* :class:`~utils.errors.LedgerLockTimeout` (PipelineRetryableError) —
  ``sp_getapplock`` contention on the ledger row. Retry per B-7.

Per-raise context (registry_id, source_name, table_name, business_date,
batch_id, current_status, file_path, expected_sha256, computed_sha256)
travels in the canonical ``metadata: dict`` kwarg of every
:class:`~utils.errors.PipelineError` subclass (forwarded to
``PipelineEventLog.Metadata`` per D76).

Concurrency (per D69 + W-8)
---------------------------

The ledger step's ``sp_getapplock`` (per M9's contract) ensures one
replay per ``(replay_batch_id, source_name, table_name, REPLAY)``
key. Concurrent replays for DIFFERENT batches are independent.
File reads do NOT take any lock — Parquet files are immutable
post-write (the writer's atomic-rename contract — § 1.1).

D-numbers consumed
------------------

D2 (Stage dropped — Parquet snapshots replace it), D4 (network drive
Parquet for snapshot storage), D15 (idempotency mandatory), D17
(idempotency ledger on every pipeline step), D25 (ParquetSnapshotRegistry
canonical Parquet index), D45.2 (Parquet 100-250 MB target + config),
D67 (Tier 0 smoke discipline), D68 (error class hierarchy —
PipelineFatalError / PipelineRetryableError), D69 (cursor_for
ownership), D92 (forward-only additive — new module; no rename /
removal).

B-numbers
---------

B-1 — full SHA-256 hex (VARCHAR(64)) is the contract; truncating or
substituting xxhash would defeat the SCD2 row-hash invariant.

See also
--------

* ``data_load/parquet_writer.py`` (§ 1.1) — INSERTs ``Status='created'``
  registry rows at write time. M2 consumes the registered files in
  reverse.
* ``data_load/parquet_registry_client.py`` (§ 1.3) — M2 composes
  ``query_snapshot`` to look up the registry row; uses M3's status
  constants for the eligibility check.
* ``utils/idempotency_ledger.py`` (§ 4.1) — ``ledger_step`` context
  manager. M2 composes it for replay idempotency.
* ``scd2/engine.py`` ``run_scd2()`` / ``run_scd2_targeted()`` — consume
  ``ReplayResult.df`` for SCD2 promotion.
* RB-8 (Bronze rebuild from Parquet) — operator runbook that orchestrates
  M2 calls + SCD2 promotion.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterator

import polars as pl

from utils.errors import (
    LedgerLockTimeout,  # noqa: F401  (re-imported for back-compat callers)
    ParquetReplayError,
    RegistryNotFound,
    RegistryStatusInvalid,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public constants
# ---------------------------------------------------------------------------

#: EventType written to the IdempotencyLedger row for every replay. Pinned
#: per § 1.2 ("Composes ledger_step with EventType='REPLAY'")
#: and aligns with the canonical event-type families documented in
#: ``CLAUDE.md`` under PipelineEventLog (the ``REPLAY`` event_type was
#: previously documented in § 4.1 as a canonical value).
EVENT_TYPE_REPLAY = "REPLAY"

#: Registry statuses for which replay is eligible. Per § 1.2 — the
#: verifier must have run (``verified``) OR the snapshot must be
#: mirrored (``replicated``) OR archived (``archived``). Replay against
#: ``created`` is forbidden because the SHA-256 has not been confirmed
#: post-write; replay against ``missing`` / ``purged`` /
#: ``replication_failed`` is forbidden because the file may not exist or
#: may be in a known-bad state.
REPLAY_ELIGIBLE_STATUSES = frozenset({"verified", "replicated", "archived"})


# ---------------------------------------------------------------------------
# Public dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReplayResult:
    """Result of a successful :func:`replay_parquet_snapshot` call.

    Per § 1.2 canonical signature. All fields populated on a successful
    replay; the class is frozen because replay results are immutable
    audit records (re-replay produces a new instance per D26 append-only).

    Attributes:
        df: Polars DataFrame materialized from the Parquet file. Schema
            matches the source-of-record at write time; SCD2 promotion
            consumes this directly. Read-only (Polars DataFrames are
            immutable by construction; the field's reference is also
            frozen via the dataclass).
        registry_id: ``General.ops.ParquetSnapshotRegistry.RegistryId`` of
            the source registry row. Surfaced for audit.
        source_file: Absolute path to the on-disk Parquet file. Surfaced
            for audit + diagnostic logging.
        row_count: Number of rows in ``df``. MUST match the registry's
            ``RowCount`` column (a mismatch raises
            :class:`~utils.errors.ParquetReplayError` — included as
            defense-in-depth alongside SHA-256 verification).
        sha256_verified: Full 64-char SHA-256 hex string of the file
            contents. Confirmed to match the registry's
            ``ContentChecksum`` (or ``SchemaHash`` fallback) on
            successful return.
        extracted_at: Original extraction timestamp from the snapshot —
            sourced from the registry row's ``CreatedAt`` column (the
            writer INSERTs the registry row immediately post-write, so
            ``CreatedAt`` IS the canonical extraction timestamp).
            ``datetime`` is naive UTC + millisecond precision per the
            ``DATETIME2(3)`` column semantics.
        batch_id: The ``BatchId`` of the ORIGINAL snapshot (i.e. the
            ``original_batch_id`` argument), NOT the replay's
            ``replay_batch_id``. Surfaced so SCD2 promotion can write
            the snapshot's original batch into Bronze provenance.
    """

    df: pl.DataFrame
    registry_id: int
    source_file: Path
    row_count: int
    sha256_verified: str
    extracted_at: datetime
    batch_id: int


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------

__all__ = (
    "EVENT_TYPE_REPLAY",
    "REPLAY_ELIGIBLE_STATUSES",
    "ReplayResult",
    "replay_parquet_snapshot",
)


# ---------------------------------------------------------------------------
# Internal: lazy imports for testability
#
# Both sibling-module imports are lazy-resolved through getter functions so
# tests can swap the implementations via ``patch.object(mod,
# "_get_query_snapshot", ...)`` without going through
# ``monkeypatch.setitem("sys.modules", ...)``. Mirrors the M3 pattern.
# ---------------------------------------------------------------------------


def _get_query_snapshot():
    """Return :func:`data_load.parquet_registry_client.query_snapshot`."""
    from data_load.parquet_registry_client import query_snapshot  # noqa: PLC0415
    return query_snapshot


def _get_ledger_step():
    """Return :func:`utils.idempotency_ledger.ledger_step`."""
    from utils.idempotency_ledger import ledger_step  # noqa: PLC0415
    return ledger_step


# ---------------------------------------------------------------------------
# Internal: SHA-256 hashing
# ---------------------------------------------------------------------------


# Read buffer for SHA-256 — chosen to balance memory footprint against
# syscall overhead. 1 MiB is the canonical buffer size for hashlib's
# update() loop on typical Linux filesystems; the registry's target
# Parquet file size is 100-250 MB per D45.2, so a 1 MiB buffer means
# ~100-250 update() calls per file.
_SHA256_BUFFER_SIZE = 1024 * 1024  # 1 MiB


def _compute_file_sha256(file_path: Path) -> str:
    """Return the SHA-256 hex digest of the file at ``file_path``.

    Streams the file in 1 MiB chunks to keep memory bounded. Raises
    :class:`FileNotFoundError` if the file is absent — caller maps to
    :class:`~utils.errors.ParquetReplayError`.

    Output is lowercase 64-char hex (matches hashlib.sha256().hexdigest()
    default), aligned with the M1 writer's hash format AND the
    registry's ``ContentChecksum`` column convention.
    """
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(_SHA256_BUFFER_SIZE)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Internal: extracted_at helper
# ---------------------------------------------------------------------------


def _coerce_extracted_at(value) -> datetime:
    """Coerce a registry ``CreatedAt`` column value to a naive UTC datetime.

    The registry's ``CreatedAt`` column is ``DATETIME2(3)`` (declared in
    Round 1 table 8 DDL); pyodbc returns it as a naive Python datetime
    per the SCD2-P1-f invariant in CLAUDE.md (DATETIME2(3) parameters
    MUST be naive — no tzinfo — to avoid implicit timezone conversion).

    Defensively handle:

    * ``None`` (rare — would only happen if the writer failed to
      populate CreatedAt, which the DEFAULT SYSUTCDATETIME() prevents)
      → fall back to ``datetime.now(timezone.utc).replace(tzinfo=None)``
      truncated to millisecond.
    * tz-aware datetime (impossible per pyodbc / DDL but defended for
      forward-compat) → strip tzinfo after converting to UTC.
    * Already-naive datetime → return as-is.
    """
    if value is None:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        micros = now.microsecond
        millis = micros - (micros % 1000)
        return now.replace(microsecond=millis)
    if isinstance(value, datetime) and value.tzinfo is not None:
        return value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


# ---------------------------------------------------------------------------
# Internal: ledger composition
# ---------------------------------------------------------------------------


def _replay_ledger_step(
    *,
    replay_batch_id: int,
    source_name: str,
    table_name: str,
    metadata: dict | None = None,
) -> Iterator:
    """Open a ``ledger_step`` context keyed for the replay event.

    Returns an Iterator yielding the ``LedgerStep`` (mirrors the M3
    ``_registry_ledger_step`` pattern). The yielded
    :class:`utils.idempotency_ledger.LedgerStep` carries
    ``was_short_circuited`` — callers use this for diagnostic logging
    (the replay's READ side has no side effect to skip; idempotency
    here is about not duplicating the LEDGER ROW).
    """
    ledger_step = _get_ledger_step()
    return ledger_step(
        batch_id=replay_batch_id,
        source_name=source_name,
        table_name=table_name,
        event_type=EVENT_TYPE_REPLAY,
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# Internal: registry lookup
# ---------------------------------------------------------------------------


def _lookup_registry_row(
    *,
    source_name: str,
    table_name: str,
    business_date: date | None,
    original_batch_id: int,
) -> dict:
    """Look up the registry row for ``(source, table, date, batch)``.

    Composes M3's :func:`query_snapshot`. Raises
    :class:`~utils.errors.RegistryNotFound` if no row matches — this is
    a FATAL error because the caller's tuple is part of the audit trail
    (a missing row means the caller has a stale or fabricated key).
    """
    query_snapshot = _get_query_snapshot()
    row = query_snapshot(
        source_name=source_name,
        table_name=table_name,
        business_date=business_date,
        batch_id=original_batch_id,
    )
    if row is None:
        raise RegistryNotFound(
            (
                f"No ParquetSnapshotRegistry row for "
                f"source={source_name!r}, table={table_name!r}, "
                f"business_date={business_date!r}, "
                f"batch_id={original_batch_id}"
            ),
            metadata={
                "source_name": source_name,
                "table_name": table_name,
                "business_date": (
                    business_date.isoformat()
                    if business_date is not None
                    else None
                ),
                "original_batch_id": original_batch_id,
            },
        )
    return row


# ---------------------------------------------------------------------------
# Public: :func:`replay_parquet_snapshot`
# ---------------------------------------------------------------------------


def replay_parquet_snapshot(
    *,
    source_name: str,
    table_name: str,
    business_date: date,
    original_batch_id: int,
    replay_batch_id: int,
) -> ReplayResult:
    """Read a registered Parquet snapshot; verify SHA-256; return DataFrame.

    Per § 1.2 canonical interface. The replay:

    1. Looks up the registry row by lookup-key tuple.
    2. Verifies ``Status IN ('verified', 'replicated', 'archived')``.
    3. Opens the file at ``NetworkDrivePath``; raises ParquetReplayError
       if absent.
    4. Computes the file's SHA-256; raises ParquetReplayError if it
       doesn't match the registry's expected hash.
    5. Reads the file via :func:`polars.read_parquet`.
    6. Gates steps 3-5 with :func:`utils.idempotency_ledger.ledger_step`
       so re-running the same ``replay_batch_id`` produces no duplicate
       ledger row.

    Args:
        source_name: e.g. ``'DNA'`` / ``'CCM'`` / ``'EPICOR'``. Together
            with ``table_name`` + ``business_date`` + ``original_batch_id``
            forms the UNIQUE lookup key into ``ParquetSnapshotRegistry``.
        table_name: e.g. ``'ACCT'``. Source-of-record table name.
        business_date: The Hive-partition date of the snapshot
            (``year=YYYY/month=MM/day=DD`` segment of the network drive
            path). NULL not accepted here — small-table snapshots
            without a business date use a separate code path (caller
            must adapt; § 1.2 spec specifies ``business_date: date``).
        original_batch_id: The ``BatchId`` of the ORIGINAL snapshot
            (NOT the replay's). This is the column written by the
            writer at write time.
        replay_batch_id: A FRESH ``BatchId`` (from
            ``General.ops.PipelineBatchSequence``) for the replay event
            itself. The idempotency ledger row is keyed on this; a
            different ``replay_batch_id`` for the same snapshot
            produces a new audit event (intentional — operator-triggered
            re-replays should be distinct from accidental retries).

    Returns:
        :class:`ReplayResult` with ``df``, ``registry_id``,
        ``source_file``, ``row_count``, ``sha256_verified``,
        ``extracted_at``, ``batch_id``.

    Raises:
        :class:`~utils.errors.RegistryNotFound`: ``(source_name,
            table_name, business_date, original_batch_id)`` tuple
            does not resolve to any registry row. FATAL.
        :class:`~utils.errors.RegistryStatusInvalid`: registry row
            exists but ``Status NOT IN ('verified', 'replicated',
            'archived')``. FATAL — verifier must run first, or the
            row is in a known-bad state.
        :class:`~utils.errors.ParquetReplayError`: registry row exists
            and Status is eligible, but the file is missing OR the
            computed SHA-256 doesn't match the registry hash OR the
            file's row count doesn't match the registry's RowCount.
            FATAL — corruption signal; escalate to RB-6 + RB-8.
        :class:`~utils.errors.LedgerLockTimeout`: ``sp_getapplock``
            contention on the ledger row. RETRYABLE per B-7.

    Side effects:
        * INSERTs :class:`General.ops.IdempotencyLedger` row with
          ``BatchId=replay_batch_id``, ``EventType='REPLAY'``,
          ``Status='IN_PROGRESS'`` → ``'COMPLETED'``.
        * Reads the Parquet file at the registry's ``NetworkDrivePath``;
          no writes to the file (Parquet is immutable post-write per § 1.1).

    Idempotency: re-call with same ``replay_batch_id`` short-circuits
    via the ledger (``Status='COMPLETED'`` lookup). The file is still
    re-read (the DataFrame is the return value); the side effect (ledger
    row) is not duplicated. Re-call with a different ``replay_batch_id``
    produces a new ledger row + new audit event.
    """
    # Step 1: registry lookup (FATAL on absence)
    row = _lookup_registry_row(
        source_name=source_name,
        table_name=table_name,
        business_date=business_date,
        original_batch_id=original_batch_id,
    )
    registry_id = int(row["RegistryId"])
    current_status = str(row["Status"])

    # Step 2: eligibility check (FATAL on incompatible status)
    if current_status not in REPLAY_ELIGIBLE_STATUSES:
        raise RegistryStatusInvalid(
            (
                f"Cannot replay RegistryId={registry_id}: current "
                f"Status={current_status!r}; eligible statuses are "
                f"{sorted(REPLAY_ELIGIBLE_STATUSES)!r}."
            ),
            metadata={
                "registry_id": registry_id,
                "current_status": current_status,
                "eligible_statuses": sorted(REPLAY_ELIGIBLE_STATUSES),
                "source_name": source_name,
                "table_name": table_name,
                "original_batch_id": original_batch_id,
            },
        )

    file_path = Path(row["NetworkDrivePath"])
    expected_sha256 = row["ContentChecksum"] or row["SchemaHash"]
    expected_row_count = int(row["RowCount"])
    extracted_at = _coerce_extracted_at(row.get("CreatedAt"))

    # Steps 3-5: gated under ledger_step. The READ + SHA verify + Polars
    # materialize all happen inside the gate so the ledger row marks
    # COMPLETED only after the result is reliably constructed (an
    # exception inside the gate marks the row FAILED per M9's contract,
    # and the caller can retry).
    metadata = {
        "registry_id": registry_id,
        "source_name": source_name,
        "table_name": table_name,
        "business_date": (
            business_date.isoformat() if business_date is not None else None
        ),
        "original_batch_id": original_batch_id,
        "replay_batch_id": replay_batch_id,
        "file_path": str(file_path),
        "expected_sha256": expected_sha256,
        "expected_row_count": expected_row_count,
    }

    with _replay_ledger_step(
        replay_batch_id=replay_batch_id,
        source_name=source_name,
        table_name=table_name,
        metadata=metadata,
    ) as step:
        # `was_short_circuited=True` means a prior COMPLETED ledger row
        # exists for this replay_batch_id. We STILL re-read the file —
        # the DataFrame is the return value and the caller needs it. The
        # ledger's job is to prevent duplicate AUDIT ROWS, not to cache
        # the DataFrame (we don't have a way to persist DataFrames
        # idempotently — the persisted result lives on the Parquet file).
        if step.was_short_circuited:
            logger.info(
                "replay_parquet_snapshot: idempotent re-call detected "
                "(replay_batch_id=%s, registry_id=%s); re-reading file "
                "without re-INSERTing ledger row",
                replay_batch_id,
                registry_id,
            )

        # Step 3: file presence check
        if not file_path.exists():
            raise ParquetReplayError(
                (
                    f"Parquet file missing for RegistryId={registry_id}: "
                    f"{file_path} — escalate to RB-6 vault recovery + "
                    f"RB-8 Bronze rebuild."
                ),
                metadata={
                    "registry_id": registry_id,
                    "file_path": str(file_path),
                    "source_name": source_name,
                    "table_name": table_name,
                    "original_batch_id": original_batch_id,
                    "replay_batch_id": replay_batch_id,
                },
            )

        # Step 4: SHA-256 verify. Hash FIRST so we catch corruption
        # BEFORE we deserialize potentially-tampered Parquet bytes into
        # the Polars engine. (Polars's Parquet reader will happily
        # consume a corrupted file and produce garbage; the SHA is the
        # ONLY corruption signal we have here.)
        computed_sha256 = _compute_file_sha256(file_path)
        if not expected_sha256:
            # Both ContentChecksum AND SchemaHash were NULL — registry
            # row is malformed. Defensive raise (M1 writer always
            # populates ContentChecksum post-write).
            raise ParquetReplayError(
                (
                    f"Registry row for RegistryId={registry_id} has NULL "
                    f"ContentChecksum AND NULL SchemaHash — cannot "
                    f"verify file integrity. Escalate to RB-6."
                ),
                metadata={
                    "registry_id": registry_id,
                    "file_path": str(file_path),
                    "computed_sha256": computed_sha256,
                    "expected_sha256": None,
                },
            )
        if computed_sha256.lower() != str(expected_sha256).lower():
            raise ParquetReplayError(
                (
                    f"SHA-256 mismatch for RegistryId={registry_id}: "
                    f"file={file_path}; computed={computed_sha256}; "
                    f"expected={expected_sha256}. Corruption signal — "
                    f"escalate to RB-6 vault recovery + RB-8 rebuild."
                ),
                metadata={
                    "registry_id": registry_id,
                    "file_path": str(file_path),
                    "computed_sha256": computed_sha256,
                    "expected_sha256": str(expected_sha256),
                    "source_name": source_name,
                    "table_name": table_name,
                    "original_batch_id": original_batch_id,
                    "replay_batch_id": replay_batch_id,
                },
            )

        # Step 5: materialize via Polars. ``read_parquet`` raises Polars-
        # native exceptions on malformed bytes; we let those bubble up
        # (the ledger's exit handler will mark the row FAILED). A
        # post-read row-count check guards against the (unlikely) case
        # where SHA matches but the registry's RowCount doesn't — this
        # would indicate registry-row tampering, NOT file corruption,
        # but the operator response is the same (escalate).
        df = pl.read_parquet(file_path)
        actual_row_count = df.height
        if actual_row_count != expected_row_count:
            raise ParquetReplayError(
                (
                    f"Row-count mismatch for RegistryId={registry_id}: "
                    f"file rows={actual_row_count}; registry "
                    f"RowCount={expected_row_count}. Registry-row "
                    f"tampering OR Parquet file regenerated without "
                    f"updating registry. Escalate."
                ),
                metadata={
                    "registry_id": registry_id,
                    "file_path": str(file_path),
                    "actual_row_count": actual_row_count,
                    "expected_row_count": expected_row_count,
                    "computed_sha256": computed_sha256,
                },
            )

        logger.info(
            "replay_parquet_snapshot: success registry_id=%s "
            "source=%s table=%s business_date=%s original_batch_id=%s "
            "replay_batch_id=%s rows=%s sha=%s",
            registry_id,
            source_name,
            table_name,
            business_date,
            original_batch_id,
            replay_batch_id,
            actual_row_count,
            computed_sha256,
        )

        return ReplayResult(
            df=df,
            registry_id=registry_id,
            source_file=file_path,
            row_count=actual_row_count,
            sha256_verified=computed_sha256,
            extracted_at=extracted_at,
            batch_id=int(row["BatchId"]),
        )
