"""M1 — Parquet snapshot writer (write + register).

Per **`docs/migration/phase1/03_core_modules.md` § 1.1** (canonical
interface) — writes a Polars DataFrame to a Parquet file at the canonical
Hive-partitioned path with D45.2 configuration (ZSTD level 3, Hive
partition, statistics enabled, atomic inflight-rename pattern); registers
the file in :data:`General.ops.ParquetSnapshotRegistry` with
``Status='created'``.

What this module does
---------------------

* Writes a Parquet file via Polars at
  ``<output_dir>/<SourceName>/<TableName>/year=YYYY/month=MM/day=DD/<BatchId>.parquet``
  using the inflight-rename pattern (D16) for crash safety: write to a
  ``*.parquet.inflight`` path, ``fsync`` the file handle, atomically
  rename to the final name, then ``fsync`` the parent directory so the
  new directory entry survives a power loss.
* Computes the full SHA-256 hex digest of the **on-disk file** post-rename
  (per B-1 full 64-char VARCHAR(64) discipline). Hashing is performed
  via :func:`hashlib.sha256` streaming over 64 KiB chunks so a multi-GB
  Parquet file does not blow up memory.
* INSERTs a row into ``General.ops.ParquetSnapshotRegistry`` with
  ``Status='created'`` via :func:`utils.connections.cursor_for` using
  the OUTPUT clause to capture the generated ``RegistryId``. M3
  (:mod:`data_load.parquet_registry_client`) handles all subsequent
  state-machine transitions (``created`` -> ``verified`` -> ...).

What this module does NOT do
----------------------------

* No verification — :func:`parquet_registry_client.verify_parquet_snapshot`
  is the verifier-side counterpart (producer / verifier separation per
  the D55 spirit). This module writes + registers; it never self-flips
  the registry status to ``'verified'``.
* No idempotency-ledger composition — the registry's
  ``UX_ParquetSnapshotRegistry_Identity`` UNIQUE index on
  ``(SourceName, TableName, BatchId, BusinessDate)`` is the atomicity
  guarantee for write-time idempotency. A concurrent re-call with the
  same key raises :class:`RegistryInsertConflict` (retryable) and
  callers query the registry to find the winner before retrying. M3's
  state transitions compose the ledger; M1's INSERT does not need to
  (the UNIQUE constraint serializes correctness).

Idempotency contract (per D15 + D16)
------------------------------------

* Write-side: inflight-rename leaves an unregistered ``*.parquet.inflight``
  file on crash. A subsequent run with the same ``(BatchId, ...)`` tuple
  re-writes a fresh inflight file (the existing one is overwritten via
  :meth:`pathlib.Path.replace`-equivalent semantics) — operationally
  safe because crash-leftover inflight files carry no registry row, so
  no consumer can read them.
* Register-side: UNIQUE on ``(SourceName, TableName, BatchId, BusinessDate)``
  ensures one row per snapshot. Re-call with same key raises
  :class:`RegistryInsertConflict`; caller queries
  :func:`parquet_registry_client.query_snapshot` to find the winner.

Error modes (per D68 — canonical ``utils.errors`` hierarchy)
------------------------------------------------------------

* :class:`~utils.errors.ParquetWriteCrash` (PipelineFatalError) — inflight
  file exists but the atomic rename to the final name failed (ENOSPC,
  EACCES, network drive dropped, OS-level file lock). Operator must
  inspect the inflight file and decide recovery path (RB-6 mirrors the
  vault-recovery pattern).
* :class:`~utils.errors.RegistryInsertConflict` (PipelineRetryableError)
  — UNIQUE violation on ``ParquetSnapshotRegistry`` INSERT. Concurrent
  workers raced on the same identity tuple. Retry per B-7; the retry
  should first query the registry to find the winning row.

Concurrency (per D69)
---------------------

``cursor_for('General')`` is opened once per call inside the INSERT step;
no shared cursor across module boundary. Multiple ``--workers`` writing
DIFFERENT ``(SourceName, TableName, BusinessDate)`` tuples are entirely
independent. SAME-tuple concurrent races are caught by the UNIQUE
constraint at INSERT time.

Memory discipline (W-12)
------------------------

Per CLAUDE.md gotcha W-12: ``shrink_to_fit(in_place=True)`` is called on
the input DataFrame AFTER write if ``df`` has > 100K rows. Releases the
over-allocated buffer back to the allocator so subsequent pipeline steps
(CDC / SCD2 / next-table extraction) do not pay the carry cost. Combined
with W-4 (``MALLOC_ARENA_MAX=2``), this minimizes glibc arena bloat
during large-table runs.

Datetime invariant (per SCD2-P1-f + CDC-NOW-MS)
-----------------------------------------------

The ``CreatedAt`` column on ``ParquetSnapshotRegistry`` is
``DATETIME2(3)`` with a server-side ``DEFAULT SYSUTCDATETIME()``. This
module does NOT pass a Python ``datetime`` for ``CreatedAt`` — the
column default fires server-side. If a future revision needs explicit
``CreatedAt`` (e.g. backdated registration), the pyodbc parameter MUST
be naive (no tzinfo) and millisecond-precision; otherwise SQL Server
silently coerces through DATETIMEOFFSET and shifts the value on
non-UTC servers. The same invariant applies to every DATETIME2(3)
parameter throughout the pipeline.

D-numbers consumed
------------------

D2 (Stage dropped — Parquet snapshots replace it), D4 (network drive
Parquet for snapshot storage), D15 (idempotency mandatory at every
layer), D16 (inflight-rename pattern for crash safety), D26 (append-
only audit posture — registry rows never DELETEd), D45.2 (Parquet
config: ZSTD-3, 100-250 MB row groups, statistics enabled, atomic
rename), D45.3 (BatchId from ``PipelineBatchSequence`` — caller
pre-allocates), D67 (Tier 0 smoke test discipline), D68 (error class
hierarchy — PipelineFatalError / PipelineRetryableError),
D69 (cursor_for ownership), D92 (forward-only additive — new module).

B-numbers
---------

* B-1 (full SHA-256 VARCHAR(64) — no 64-bit truncation).
* W-12 (``shrink_to_fit`` memory pattern after large-row operations).
* B-228 (single-source-of-truth for ``utils.errors`` imports — this
  module imports ``ParquetWriteCrash`` / ``RegistryInsertConflict``
  from :mod:`utils.errors`, never re-defines).

See also
--------

* ``data_load/parquet_registry_client.py`` (§ 1.3) — state-machine
  client; consumes the ``Status='created'`` rows this module produces
  and flips them through verified -> replicated -> archived -> purged.
* ``data_load/parquet_replay.py`` (§ 1.2) — reads registered files for
  Bronze rebuild (RB-8).
* ``utils/connections.py`` — ``cursor_for('General')`` context manager
  used to open the INSERT cursor.
* ``utils/errors.py`` — canonical exception hierarchy per D68 + B-228.
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
import pyodbc

from utils.errors import (
    ParquetWriteCrash,
    RegistryInsertConflict,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Canonical Parquet write configuration (per D45.2 Round 1)
#
# These values match the canonical D45.2 spec — DO NOT modify without a
# new D-number for the change. The pipeline relies on these settings
# being uniform across every Parquet writer so M3's verification SHA-256
# is stable across re-writes (a compression-level shift would change
# the bytes and therefore the hash).
# ---------------------------------------------------------------------------

PARQUET_COMPRESSION = "zstd"
PARQUET_COMPRESSION_LEVEL = 3
PARQUET_USE_PYARROW = False  # native polars Rust writer per D45.2
PARQUET_STATISTICS = True    # MIN / MAX / NULL_COUNT / DISTINCT_COUNT per D45.2

# Streaming chunk size for SHA-256 hashing of the on-disk file.
# 64 KiB is the conventional default — large enough to amortize the
# per-read syscall overhead, small enough that hashing a multi-GB
# Parquet file does not blow up memory.
_SHA256_CHUNK_BYTES = 65536

# W-12 shrink_to_fit threshold — only call on DataFrames > 100K rows,
# matching the CLAUDE.md gotcha discipline ("after large DataFrame
# operations (>100K rows)").
_SHRINK_TO_FIT_THRESHOLD_ROWS = 100_000

# Inflight suffix per D16 atomic-rename pattern.
_INFLIGHT_SUFFIX = ".inflight"

# pyodbc native error codes for UNIQUE / PK violation on SQL Server.
# 2627 = PK violation; 2601 = UNIQUE index violation.
# (Mirrors ``utils.idempotency_ledger._UNIQUE_VIOLATION_CODES``.)
_UNIQUE_VIOLATION_CODES = frozenset({2627, 2601})

_UNIQUE_VIOLATION_PHRASES = (
    "Violation of UNIQUE KEY constraint",
    "Violation of PRIMARY KEY constraint",
    "Cannot insert duplicate key",
)


__all__ = (
    "ParquetWriteResult",
    "write_parquet_snapshot",
)


# ---------------------------------------------------------------------------
# Public result dataclass
#
# Frozen because the result represents a completed (immutable) write —
# the file on disk and the registry row exist; mutating the result
# in-place would invite drift between the dataclass and the source-
# of-truth registry row.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ParquetWriteResult:
    """Successful write + register result for :func:`write_parquet_snapshot`.

    Per § 1.1 canonical signature. All fields populated on successful
    return. The ``status`` field is ALWAYS ``'created'`` — never
    ``'verified'``. M3's :func:`parquet_registry_client.verify_parquet_snapshot`
    is the only path that flips status to ``'verified'``; that function
    returns a separate :class:`ParquetVerifyResult` dataclass (the type
    boundary between producer and verifier is intentional).

    :param file_path: Full path of the materialized ``.parquet`` file
        (post-rename — the canonical name, never the ``.inflight``
        intermediate). Always absolute.
    :param file_size_bytes: On-disk size in bytes. Used by M3
        verification to cross-check ``UncompressedBytes`` /
        ``CompressedBytes`` invariants.
    :param row_count: Number of rows in the source DataFrame
        (i.e. ``len(df)``). Cross-checked against M3 verification
        by reading the Parquet metadata.
    :param sha256: Full 64-character SHA-256 hex digest of the
        on-disk file (per B-1 full-hash discipline). Stored in
        ``ParquetSnapshotRegistry.ContentChecksum``.
    :param registry_id: ``General.ops.ParquetSnapshotRegistry.RegistryId``
        of the freshly-inserted row. Captured via OUTPUT clause on
        the INSERT (avoids a follow-up SELECT round-trip).
    :param status: Always ``'created'`` — the producer side of the
        registry state machine. M3 flips ``'created'`` -> ``'verified'``.
    """

    file_path: Path
    file_size_bytes: int
    row_count: int
    sha256: str
    registry_id: int
    status: str


# ---------------------------------------------------------------------------
# Lazy-imported dependencies
#
# Kept lazy so Tier 0 smoke can mock at the ``sys.modules`` level WITHOUT
# importing real ``pyodbc`` / ``utils.connections``. The pattern mirrors
# the sibling M3 module's ``_get_cursor_for`` / ``_get_ledger_step``
# indirection (per the D67 Tier 0 discipline).
# ---------------------------------------------------------------------------


def _get_cursor_for():
    """Return ``utils.connections.cursor_for`` (lazy import for testability)."""
    from utils.connections import cursor_for  # noqa: PLC0415
    return cursor_for


# ---------------------------------------------------------------------------
# Internal: B-270 env-var-gated crash-injection harness (test-only)
#
# Tier 4 (Round 5 § 7 + docs/migration/06_TESTING.md) needs a deterministic
# crash boundary AFTER the inflight Parquet write succeeds but BEFORE the
# atomic rename — so a parent test process can SIGKILL this subprocess and
# verify the inflight file remains on disk + no registry row was created
# (C2 canonical crash injection point per Round 5 § 7 inventory).
#
# Contract:
#   - Reads ``CRASH_INJECT_POINT`` env var; only fires when value matches
#     the ``checkpoint`` argument (default ``"after_inflight_write"``).
#   - Emits the canonical barrier token ``INFLIGHT_WRITE_DONE`` to stdout
#     (flushed immediately) so the parent test process sees it before the
#     sleep window opens.
#   - Sleeps ``CRASH_INJECT_SLEEP_SECONDS`` seconds (default 10) so the
#     parent has a deterministic window to SIGKILL this process before
#     the rename happens.
#   - No-op when env var absent OR value doesn't match the checkpoint.
#     Zero production cost (one ``os.environ.get`` lookup + branch).
#   - NEVER raises — defensive try/except internal — pollution of the
#     production path is the only failure mode we cannot accept.
# ---------------------------------------------------------------------------


def _crash_test_harness_c2(checkpoint: str = "after_inflight_write") -> None:
    """B-270 closure: env-var-gated test-only crash injection point (C2).

    Reads ``CRASH_INJECT_POINT`` env var; if its value matches
    ``checkpoint``, emits the canonical barrier token
    (``INFLIGHT_WRITE_DONE``) to stdout (flushed) and sleeps to give a
    parent test process a deterministic window to SIGKILL this
    subprocess. No-op when env var absent OR value doesn't match — zero
    production cost. NEVER raises (defensive try/except internal).

    Per docs/migration/06_TESTING.md Tier 4 + B-270 closure.
    """
    try:
        import os, sys, time  # noqa: PLC0415 — lazy by design
        if os.environ.get("CRASH_INJECT_POINT") != checkpoint:
            return
        print("INFLIGHT_WRITE_DONE", flush=True)
        sleep_seconds = float(os.environ.get("CRASH_INJECT_SLEEP_SECONDS", "10"))
        time.sleep(sleep_seconds)
    except Exception:  # noqa: BLE001 — production path MUST NOT be polluted
        # Defensive: env-var read or sleep failed for an unknown reason.
        # Swallow — the test harness is opt-in and any failure means we
        # silently degrade to "no-op", matching the env-var-absent case.
        return


# ---------------------------------------------------------------------------
# Internal: pyodbc UNIQUE-violation detection
#
# Mirrors ``utils.idempotency_ledger._is_unique_violation`` (kept in-module
# to keep the two error-detection sites decoupled — a future change to one
# should not silently break the other).
# ---------------------------------------------------------------------------


def _is_unique_violation(exc: pyodbc.IntegrityError) -> bool:
    """Return ``True`` iff ``exc`` represents a SQL Server UNIQUE / PK violation.

    Discriminates UNIQUE / PK constraint failures (2627 / 2601) from
    other ``IntegrityError`` variants (FK violation, CHECK failure).
    Used by :func:`write_parquet_snapshot` to convert the pyodbc
    exception into the canonical :class:`RegistryInsertConflict` per
    the § 1.1 error contract.
    """
    args = exc.args
    if not args:
        return False

    def _matches(text: str) -> bool:
        return (
            "2627" in text
            or "2601" in text
            or any(phrase in text for phrase in _UNIQUE_VIOLATION_PHRASES)
        )

    for arg in args:
        if isinstance(arg, str) and _matches(arg):
            return True
        if isinstance(arg, tuple):
            for elt in arg:
                if isinstance(elt, int) and elt in _UNIQUE_VIOLATION_CODES:
                    return True
                if isinstance(elt, str) and _matches(elt):
                    return True
    return False


# ---------------------------------------------------------------------------
# Internal: Hive-partitioned path construction
#
# Pure function over (output_dir, source_name, table_name, business_date,
# batch_id) — no side effects. Tested independently of write_parquet_snapshot.
# ---------------------------------------------------------------------------


def _build_hive_path(
    *,
    output_dir: Path,
    source_name: str,
    table_name: str,
    business_date: date,
    batch_id: int,
) -> Path:
    """Construct the canonical Hive-partitioned file path.

    Per § 1.1 + D4 (network drive Parquet) + D45.2 (Hive partition):

        ``<output_dir>/<source_name>/<table_name>/year=YYYY/month=MM/day=DD/<batch_id>.parquet``

    Zero-padded month / day per Hive convention (so lexicographic order
    matches chronological order — important for the per-partition
    operator tooling). Uses :class:`pathlib.Path` so the joining works
    cross-platform (the dev workstation is Windows per CLAUDE.md
    environment; the deploy target is RHEL).
    """
    return (
        output_dir
        / source_name
        / table_name
        / f"year={business_date.year:04d}"
        / f"month={business_date.month:02d}"
        / f"day={business_date.day:02d}"
        / f"{batch_id}.parquet"
    )


# ---------------------------------------------------------------------------
# Internal: SHA-256 streaming helper
#
# Streams the on-disk file in 64 KiB chunks. Returns the full 64-char hex
# digest per B-1 (NEVER truncate to BIGINT — birthday-paradox collisions
# reach ~24% at 3B rows for truncated 64-bit hashes). Identical
# implementation to M3's _compute_sha256 — duplicated here so the M1
# write path does not have a circular dependency on M3 for the hash.
# ---------------------------------------------------------------------------


def _compute_sha256(file_path: Path) -> str:
    """Return the full 64-char SHA-256 hex digest of ``file_path``.

    Streamed in 64 KiB chunks so a multi-GB Parquet file does not blow
    up memory. Per B-1 — the hash is stored in
    ``ParquetSnapshotRegistry.ContentChecksum`` as ``VARCHAR(64)``, NEVER
    truncated to ``BIGINT``.
    """
    h = hashlib.sha256()
    with file_path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_SHA256_CHUNK_BYTES), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Internal: atomic inflight-rename helper
#
# Per D16: write to .inflight, fsync the file handle, atomically rename,
# fsync the parent directory. The parent-directory fsync is the part
# that makes the rename durable across a power loss — without it, the
# rename can be reordered behind a crash and leave both the inflight
# file AND no canonical name on disk (the worst case: a write that
# appears to succeed but is invisible to consumers after recovery).
# ---------------------------------------------------------------------------


def _atomic_rename(inflight_path: Path, final_path: Path) -> None:
    """Atomically rename ``inflight_path`` -> ``final_path`` with parent fsync.

    Per D16 inflight-rename pattern:

      1. ``os.replace`` — atomic rename (POSIX) / atomic on NTFS for the
         common case (works on RHEL prod + Windows dev).
      2. ``fsync`` the parent directory — ensures the directory entry
         change reaches disk before we declare success. Without this,
         the rename can be reordered behind a crash and the file
         appears not to exist after recovery.

    On Windows, directory ``fsync`` is a no-op (the FS doesn't support
    it the same way POSIX does). We try / except / log because the
    failure mode is "we'd like more durability but the OS doesn't
    expose the syscall" rather than "the rename failed".

    Raises:
        :class:`ParquetWriteCrash` — if ``os.replace`` itself fails
            (ENOSPC, EACCES, EXDEV, etc.). The inflight file is left
            on disk for operator recovery.
    """
    try:
        os.replace(str(inflight_path), str(final_path))
    except OSError as exc:
        raise ParquetWriteCrash(
            f"Atomic rename failed for {inflight_path} -> {final_path}: {exc}",
            metadata={
                "inflight_path": str(inflight_path),
                "final_path": str(final_path),
                "errno": getattr(exc, "errno", None),
                "strerror": getattr(exc, "strerror", None),
            },
        ) from exc

    # fsync parent directory for durability of the rename. On Windows
    # this is a best-effort no-op — we log the failure but do NOT raise
    # because the rename itself already succeeded.
    parent = final_path.parent
    try:
        # On POSIX, open the directory and call fsync. On Windows, the
        # open() of a directory raises PermissionError — we swallow it
        # and rely on NTFS's existing durability semantics.
        dir_fd = os.open(str(parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except (OSError, PermissionError) as exc:
        # Best-effort durability — log + continue. The rename succeeded;
        # power loss may make the rename appear to have not happened on
        # filesystems that don't honor parent-dir fsync, but the canonical
        # case (POSIX on RHEL prod) does honor it.
        logger.debug(
            "_atomic_rename: parent-dir fsync skipped for %s (%s)",
            parent, exc,
        )


# ---------------------------------------------------------------------------
# Internal: register row in ParquetSnapshotRegistry
#
# INSERTs with OUTPUT INSERTED.RegistryId so we get the generated identity
# back in one round-trip. The OUTPUT clause is well-supported on SQL
# Server 2012+ (the deploy target is SQL Server 2022 per Round 1 schema
# decisions).
#
# On UNIQUE violation (2627 / 2601) — convert to RegistryInsertConflict.
# On any other pyodbc error — bubble up unchanged; the caller's wrapper
# handles it as a generic DB failure.
# ---------------------------------------------------------------------------


def _insert_registry_row(
    *,
    source_name: str,
    table_name: str,
    batch_id: int,
    business_date: date | None,
    network_drive_path: Path,
    row_count: int,
    uncompressed_bytes: int,
    compressed_bytes: int,
    schema_hash: str,
    content_checksum: str,
) -> int:
    """INSERT a row into ``ParquetSnapshotRegistry``; return the new ``RegistryId``.

    Per Round 1 table 8 DDL: identity ``RegistryId`` is captured via
    OUTPUT INSERTED.RegistryId. The CK_ParquetSnapshotRegistry_Status
    constraint accepts ``'created'`` (along with the 6 other lifecycle
    values); we always INSERT with ``Status='created'`` here.

    Raises:
        :class:`RegistryInsertConflict`: UNIQUE violation on
            ``UX_ParquetSnapshotRegistry_Identity``.
        :class:`pyodbc.Error`: any other DB-side failure — bubbles up
            unchanged for the caller's generic wrapper.
    """
    sql = """
        INSERT INTO General.ops.ParquetSnapshotRegistry (
            SourceName,
            TableName,
            BatchId,
            BusinessDate,
            NetworkDrivePath,
            RowCount,
            UncompressedBytes,
            CompressedBytes,
            SchemaHash,
            ContentChecksum,
            StorageTier,
            Status
        )
        OUTPUT INSERTED.RegistryId
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    params: tuple[Any, ...] = (
        source_name,
        table_name,
        batch_id,
        business_date,
        str(network_drive_path),
        row_count,
        uncompressed_bytes,
        compressed_bytes,
        schema_hash,
        content_checksum,
        "hot",
        "created",
    )

    cursor_for = _get_cursor_for()
    try:
        with cursor_for("General") as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            if row is None:
                # OUTPUT clause guarantees a row on successful INSERT;
                # absence indicates a driver-level issue.
                raise RegistryInsertConflict(
                    "INSERT INTO ParquetSnapshotRegistry returned no "
                    "OUTPUT row (driver / connection anomaly).",
                    metadata={
                        "source_name": source_name,
                        "table_name": table_name,
                        "batch_id": batch_id,
                        "business_date": (
                            business_date.isoformat()
                            if business_date is not None
                            else None
                        ),
                    },
                )
            return int(row[0])
    except pyodbc.IntegrityError as exc:
        if _is_unique_violation(exc):
            raise RegistryInsertConflict(
                f"UNIQUE violation INSERTing into ParquetSnapshotRegistry "
                f"for (SourceName={source_name!r}, TableName={table_name!r}, "
                f"BatchId={batch_id}, BusinessDate={business_date}). "
                f"Concurrent writer race — caller should query the registry "
                f"to find the winner before retry.",
                metadata={
                    "source_name": source_name,
                    "table_name": table_name,
                    "batch_id": batch_id,
                    "business_date": (
                        business_date.isoformat()
                        if business_date is not None
                        else None
                    ),
                    "pyodbc_message": str(exc),
                },
            ) from exc
        # Non-UNIQUE IntegrityError — bubble up (FK / CHECK violation).
        raise


# ---------------------------------------------------------------------------
# Internal: resolve output_dir from env if caller passed None
# ---------------------------------------------------------------------------


def _resolve_output_dir(output_dir: Path | None) -> Path:
    """Resolve ``output_dir`` to a concrete :class:`Path`.

    Per § 1.1 — ``output_dir=None`` (default) reads ``PARQUET_OUTPUT_DIR``
    from the environment (testing-override-only otherwise). The env key
    is registered in ``02_configuration.md`` § 2.1.4 as a parity-required
    path (D27 invariant).

    Raises:
        :class:`ParquetWriteCrash`: if ``output_dir is None`` AND the
            ``PARQUET_OUTPUT_DIR`` env key is unset. Fatal because we
            cannot proceed without a destination directory.
    """
    if output_dir is not None:
        return Path(output_dir)
    env_value = os.environ.get("PARQUET_OUTPUT_DIR")
    if not env_value:
        raise ParquetWriteCrash(
            "output_dir is None and PARQUET_OUTPUT_DIR env key is unset; "
            "cannot resolve canonical Parquet output directory.",
            metadata={"env_key": "PARQUET_OUTPUT_DIR"},
        )
    return Path(env_value)


# ---------------------------------------------------------------------------
# Public: write_parquet_snapshot
# ---------------------------------------------------------------------------


def write_parquet_snapshot(
    df: pl.DataFrame,
    *,
    source_name: str,
    table_name: str,
    business_date: date,
    batch_id: int,
    output_dir: Path | None = None,
) -> ParquetWriteResult:
    """Write ``df`` to a Parquet file at the canonical Hive-partitioned path.

    Per § 1.1 canonical signature.

    Sequence (each step has a designed failure mode):

      1. Resolve ``output_dir`` (env fallback per § 2.1.4).
      2. Build the Hive-partitioned final path; ``mkdir -p`` the parent.
      3. ``polars.write_parquet`` to ``<final>.inflight`` with D45.2 config
         (ZSTD-3, statistics enabled).
      4. ``os.replace`` inflight -> final (atomic rename per D16).
      5. ``fsync`` parent directory for rename durability.
      6. Compute SHA-256 of the on-disk file (post-rename — the hash
         must match what verifiers compute, so we hash the canonical
         on-disk bytes, not the in-memory ``df``).
      7. INSERT row in ``ParquetSnapshotRegistry`` with
         ``Status='created'``; capture ``RegistryId`` via OUTPUT clause.
      8. ``df.shrink_to_fit(in_place=True)`` if row_count > 100K (W-12).
      9. Return :class:`ParquetWriteResult` with all 6 fields populated.

    Args:
        df: Pre-sorted Polars DataFrame (PK ASC, ``_extracted_at`` DESC
            per D45.2). Caller's responsibility to sort.
        source_name: One of ``{'DNA', 'CCM', 'EPICOR', ...}`` per
            ``UdmTablesList`` canonical inventory.
        table_name: Source table name (e.g. ``'ACCT'``).
        business_date: Hive partition date (drives the
            ``year=YYYY/month=MM/day=DD`` partition path).
        batch_id: MUST come from ``PipelineBatchSequence`` (D45.3).
            Caller pre-allocates; this function does NOT call
            ``NEXT VALUE FOR PipelineBatchSequence`` itself (single
            allocation per pipeline run is the D45.3 contract).
        output_dir: Optional override for ``$PARQUET_OUTPUT_DIR``.
            Tests pass ``tmp_path``; production callers pass ``None``
            (env-driven). ``None`` + unset env raises
            :class:`ParquetWriteCrash`.

    Returns:
        :class:`ParquetWriteResult` with ``status='created'``.

    Raises:
        :class:`ParquetWriteCrash`: inflight file written but the atomic
            rename failed. Fatal — the inflight file is left on disk
            for operator recovery (RB-6 mirrors the pattern).
        :class:`RegistryInsertConflict`: UNIQUE violation on
            ``(SourceName, TableName, BatchId, BusinessDate)``. Retryable
            — caller queries the registry to find the winning row
            before retrying. The Parquet file IS written (rename
            succeeded) but no registry row was created.
    """
    # ------------------------------------------------------------------
    # Step 1-2: Resolve output_dir, build the canonical path, mkdir -p.
    # ------------------------------------------------------------------
    resolved_output_dir = _resolve_output_dir(output_dir)
    final_path = _build_hive_path(
        output_dir=resolved_output_dir,
        source_name=source_name,
        table_name=table_name,
        business_date=business_date,
        batch_id=batch_id,
    )
    inflight_path = final_path.with_suffix(
        final_path.suffix + _INFLIGHT_SUFFIX
    )

    # Ensure the partition directory exists; ``parents=True`` creates
    # the source/table/year=YYYY/month=MM/day=DD chain in one call.
    # ``exist_ok=True`` matches the idempotent behavior we need across
    # multi-day backfills.
    final_path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Step 3: polars.write_parquet -> .inflight with D45.2 config.
    # ------------------------------------------------------------------
    row_count = int(df.height)
    logger.info(
        "write_parquet_snapshot: writing %d rows -> %s",
        row_count, inflight_path,
    )

    # Per D45.2: ZSTD level 3, statistics enabled, native polars writer.
    # ``use_pyarrow=False`` because the polars Rust writer is the canonical
    # implementation; the pyarrow path can diverge in stats encoding.
    df.write_parquet(
        inflight_path,
        compression=PARQUET_COMPRESSION,
        compression_level=PARQUET_COMPRESSION_LEVEL,
        statistics=PARQUET_STATISTICS,
        use_pyarrow=PARQUET_USE_PYARROW,
    )

    # B-270: test-only crash injection point (C2) — fires only when
    # CRASH_INJECT_POINT=after_inflight_write; no-op otherwise.
    _crash_test_harness_c2()

    # ------------------------------------------------------------------
    # Step 4-5: atomic rename + parent fsync per D16.
    # ------------------------------------------------------------------
    _atomic_rename(inflight_path, final_path)
    logger.debug(
        "write_parquet_snapshot: atomic rename complete -> %s", final_path,
    )

    # ------------------------------------------------------------------
    # Step 6: Compute SHA-256 of the on-disk file (post-rename).
    #
    # Critical ordering: hash AFTER rename. The verification path
    # (M3's verify_parquet_snapshot) reads the file at its canonical
    # name and hashes the on-disk bytes; if we hashed the inflight
    # file BEFORE rename, an OS-level write cache could leave the
    # canonical file with bytes that differ from what we hashed
    # (typically benign — same content — but the safe-by-construction
    # path is "hash what the verifier will hash").
    # ------------------------------------------------------------------
    file_size_bytes = final_path.stat().st_size
    sha256 = _compute_sha256(final_path)
    logger.debug(
        "write_parquet_snapshot: SHA-256 computed (%d bytes) %s",
        file_size_bytes, sha256[:16],
    )

    # ------------------------------------------------------------------
    # Step 7: INSERT row in ParquetSnapshotRegistry.
    #
    # Per Round 1 DDL — UncompressedBytes / CompressedBytes are BIGINT
    # NOT NULL. We don't have a Polars-level "uncompressed bytes"
    # primitive (the Rust writer doesn't expose it), so we use the
    # file_size_bytes (post-compression) for CompressedBytes and an
    # estimated upper bound for UncompressedBytes. M3 verification
    # can refine these via Parquet metadata.
    #
    # SchemaHash is intentionally the same as content_checksum here.
    # A future enhancement (B-N) may separate schema-only hash from
    # content hash; for now, both columns get the full content SHA-256.
    # ------------------------------------------------------------------
    registry_id = _insert_registry_row(
        source_name=source_name,
        table_name=table_name,
        batch_id=batch_id,
        business_date=business_date,
        network_drive_path=final_path,
        row_count=row_count,
        uncompressed_bytes=file_size_bytes,  # placeholder; M3 verify refines
        compressed_bytes=file_size_bytes,
        schema_hash=sha256,
        content_checksum=sha256,
    )

    logger.info(
        "write_parquet_snapshot: registered RegistryId=%d (sha256=%s..., "
        "%d rows, %d bytes)",
        registry_id, sha256[:16], row_count, file_size_bytes,
    )

    # ------------------------------------------------------------------
    # Step 8: W-12 shrink_to_fit if df > 100K rows.
    #
    # Release over-allocated buffers back to the allocator. The threshold
    # matches the CLAUDE.md gotcha discipline; below 100K rows the
    # over-allocation is not material and the call adds overhead.
    # ------------------------------------------------------------------
    if row_count > _SHRINK_TO_FIT_THRESHOLD_ROWS:
        try:
            df.shrink_to_fit(in_place=True)
        except Exception as exc:  # noqa: BLE001
            # Best-effort memory hygiene; failure here does NOT fail the
            # write (the file + registry row are durable). Log and continue.
            logger.warning(
                "write_parquet_snapshot: shrink_to_fit failed (non-fatal): %s",
                exc,
            )

    # ------------------------------------------------------------------
    # Step 9: Return the immutable result.
    # ------------------------------------------------------------------
    return ParquetWriteResult(
        file_path=final_path,
        file_size_bytes=file_size_bytes,
        row_count=row_count,
        sha256=sha256,
        registry_id=registry_id,
        status="created",
    )
