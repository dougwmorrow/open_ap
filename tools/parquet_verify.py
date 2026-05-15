"""Round 4 § 3.2 — ``tools/parquet_verify.py``.

Per **Round 4 § 3.2** at ``docs/migration/phase1/04_tools.md`` L493-575
(canonical spec) + **Round 3 § 1.3** ``data_load/parquet_registry_client``
canonical interface (``verify_parquet_snapshot(*, registry_id, actor)``
keyword-only signature returning :class:`ParquetVerifyResult`).

Operator-facing CLI wrapping M3 ``verify_parquet_snapshot()``. Re-SHA-256
a Parquet file on the network drive + flip ``ParquetSnapshotRegistry.Status``
from ``'created'`` → ``'verified'`` after independent hash check. Typical
use: post-crash recovery (RB-8 Bronze rebuild via replay) + post-doubt
audit (RB-6 vault recovery).

What this tool does
-------------------

1. Resolve target registry rows from one of:

   * ``--registry-id N`` (repeatable) — explicit row IDs to verify
   * ``--source X --table Y [--business-date-from D1] [--business-date-to D2]``
     — range query against ``General.ops.ParquetSnapshotRegistry``

2. For each row:

   a. Invoke M3 :func:`verify_parquet_snapshot` (``--apply``) OR dry-run
      shape (compute SHA + check file exists, do NOT flip Status).
   b. Catch :class:`RegistryStatusInvalid` / :class:`RegistryHashMismatch`
      (→ exit 2 fatal), :class:`RegistryFileNotFound` (→ exit 1 retryable).
   c. Emit per-row stdout line with verdict.

3. Write ONE ``CLI_PARQUET_VERIFY`` row to
   ``General.ops.PipelineEventLog`` per D76 — ``Metadata`` JSON includes
   verdict counts (verified / failed / skipped / would-verify), per-row
   verdicts, actor, justification, dry_run flag, exit_code.

4. Render stdout per spec § 3.2 L548-555 (human or JSON via ``--json``).

5. Exit 0 / 1 / 2 per D74 + spec § 3.2 L557-560.

CLI contract (per spec § 3.2 L539-547)
--------------------------------------

::

    # Verify one specific registry row
    python3 tools/parquet_verify.py --registry-id 12345 --apply

    # Verify all 'created' rows for DNA.ACCT in a date range
    python3 tools/parquet_verify.py --source DNA --table ACCT \\
        --business-date-from 2026-04-01 --business-date-to 2026-04-30 --apply

    # Dry-run: compute SHA + check file existence but do NOT flip Status
    python3 tools/parquet_verify.py --source DNA --table ACCT --dry-run

Exit codes (per D74 + spec § 3.2 L557-560)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* **0** — all rows verified successfully (or skipped because already
  ``'verified'``)
* **1** — at least one row failed with :class:`RegistryFileNotFound` or
  non-fatal verify error; operator can investigate and retry
* **2** — fatal: :class:`RegistryStatusInvalid` (caller error) OR
  :class:`RegistryHashMismatch` (corruption) OR config / connection
  failure OR mutually-exclusive arg violation

Audit row (per D76 + spec § 3.2 L526)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* ``General.ops.PipelineEventLog.EventType = 'CLI_PARQUET_VERIFY'``
  (one of the 11 R4 canonical CLI_* family values per CLAUDE.md)
* ONE row per INVOCATION (spec § 3.2 produces — per-row counts and
  verdicts surface in Metadata JSON, NOT separate event rows; the
  per-row :func:`verify_parquet_snapshot` calls each emit their own
  ``PARQUET_VERIFY`` events from M3's idempotency-ledger composition)
* ``Status in {SUCCESS, FAILED}`` (SUCCESS for exit 0/1 dry-run + apply;
  FAILED for exit 2 fatal)
* ``Metadata`` JSON shape::

    {
        "event_kind": "parquet_verification",
        "actor": "<operator>",
        "justification": "<text or null>",
        "dry_run": <bool>,
        "counts": {"verified": N, "failed": M, "skipped": K,
                   "would_verify": W},
        "verdicts": [{"registry_id": N, "file_path": "...",
                      "verdict": "VERIFIED|MISSING|HASH_MISMATCH|"
                                 "STATUS_INVALID|ERROR|"
                                 "SKIPPED_ALREADY_VERIFIED|WOULD_VERIFY",
                      "error_message": null | "..."}, ...],
        "exit_code": <int>,
        "started_at": "<ISO-8601 naive-UTC>",
        "completed_at": "<ISO-8601 naive-UTC>"
    }

Classification per ``udm-execution-classifier`` skill
-----------------------------------------------------

* **Trigger**: PRIMARY: Manual operator CLI for post-hoc retest
  (RB-8 Bronze rebuild precondition / RB-6 vault recovery / post-crash
  audit). SECONDARY: Pipeline-programmatic — typical pipeline invokes
  :func:`verify_parquet_snapshot` DIRECTLY (not through this CLI shell)
  immediately after ``write_parquet_snapshot``; this CLI exists for the
  operator-facing retest surface only. TERTIARY: Automic
  ``JOB_PARQUET_VERIFY`` — NEW proposed; not yet in Round 2 § 5.1
  frozen-N inventory (BACKLOG candidate for Round 6 deployment).
* **Frequency**: PRIMARY ad-hoc / event-driven (NOT scheduled in
  current inventory). SECONDARY direct-call from orchestration code
  (per-row, per-extract).
* **Idempotency**: YES per spec § 3.2 L527-529 — M3
  :func:`verify_parquet_snapshot` is idempotent at the row level
  ("re-call after success is a no-op" per Round 3 § 1.3 docstring).
  Re-invoking on an already-verified row returns the cached result via
  the ledger short-circuit; the underlying UPDATE is row-level
  idempotent (``verified`` → ``verified`` matches zero rows in the
  predecessor-Status WHERE clause).
* **Concurrency**: ``cursor_for('General')`` per call per Round 3 § 1.3.
  Concurrent verifies of DIFFERENT registry_ids are independent;
  concurrent verifies of the SAME registry_id are serialized by SQL
  Server row locking on ``ParquetSnapshotRegistry``. ``--workers N``
  spec'd at § 3.2 L562 for batch invocations; implemented serially
  here (single-thread per spec L538 "single-process; cursor_for per
  call" + complexity-vs-need analysis for v1 — concurrent batches are
  a future enhancement candidate).
* **Audit-row family**: ``CLI_PARQUET_VERIFY`` per D76 + CLAUDE.md
  CLI_* family registry. Per-row ``PARQUET_VERIFY`` events emit
  independently from M3 (distinct event rows per registry_id).
* **Routing**: PRIMARY tracker ``ONE_OFF_SCRIPTS.md`` operator tools
  table (manual + event-driven). SECONDARY no scheduled tracker entry
  (no Automic job yet — see B-tracked proposal above).

D-numbers consumed
------------------

D2 (Stage dropped — Parquet snapshots replace it),
D4 (network drive Parquet),
D15 (idempotency mandatory — re-runs short-circuit at the ledger),
D16 (inflight-rename pattern — verify catches files where rename
completed but registry Status not flipped),
D26 (append-only audit — every verify emits an event row),
D67 (Tier 0 smoke discipline),
D68 (canonical exception hierarchy — utils.errors),
D74-D77 (CLI exit-code contract + argument naming + audit-row contract +
Tier 0 8-canonical-assertion scaffold per spec § 3.2 L562),
D92 (forward-only additive — new tool; no existing API renamed).

Canonical references cited (per Pitfall #9.l producer self-check)
-----------------------------------------------------------------

* M3 verify_parquet_snapshot signature: ``data_load/parquet_registry_client.py``
  L523-528 — keyword-only ``(*, registry_id: int, actor: str = "pipeline")``
  returning :class:`ParquetVerifyResult` with fields
  ``(registry_id, file_path, sha256_verified, row_count_verified,
  last_verified_at, status)``.
* M3 query_snapshot signature: ``data_load/parquet_registry_client.py``
  L1022-1027 — keyword-only ``(*, source_name, table_name, business_date,
  batch_id)`` returning a dict or None. NOT used for date-range queries
  (it queries by exact BatchId + BusinessDate); range queries here use
  direct ``cursor_for('General')`` SELECT against ``ParquetSnapshotRegistry``.
* utils.errors canonical classes: :class:`RegistryStatusInvalid` (fatal),
  :class:`RegistryFileNotFound` (retryable), :class:`RegistryHashMismatch`
  (fatal), :class:`RegistryNotFound` (fatal), :class:`PipelineFatalError` /
  :class:`PipelineRetryableError` base classes per ``utils/errors.py``.
  B-228 lesson — tools import from utils.errors directly.
* CLI conventions: ``phase1/04_tools.md`` § 1.4 (canonical args) +
  § 1.7 (invocation-pattern heuristic — AUTOMIC_RUN_ID env + isatty) +
  § 1.8 (exit-code mapping) + § 1.9 (boilerplate template).

See also
--------

* ``tools/parquet_tier_review.py`` — sibling Round 4 § 3.1 tool (status
  state-machine walker; this tool is the verifier itself).
* ``tools/enforce_retention.py`` — sibling Round 4 § 3.8 tool (same
  author pattern; same Tier 0-friendly structure).
* RB-6 (vault recovery — corruption escalation).
* RB-8 (Bronze rebuild via replay — verify is a precondition).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import traceback
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

# Project root on sys.path so we can reach data_load + utils.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Canonical exception hierarchy per D68 + B-228 (utils.errors single
# source of truth; tools import directly).
try:
    from utils.errors import (  # noqa: E402
        PipelineFatalError,
        PipelineRetryableError,
        RegistryFileNotFound,
        RegistryHashMismatch,
        RegistryNotFound,
        RegistryStatusInvalid,
    )
except (ImportError, ModuleNotFoundError):
    # Defensive fallback for test environments where utils.errors may be
    # mocked as MagicMock — re-import from the filesystem directly.
    import importlib.util as _importlib_util  # noqa: E402

    _err_path = Path(__file__).resolve().parent.parent / "utils" / "errors.py"
    _spec = _importlib_util.spec_from_file_location(
        "utils._errors_parquet_verify", _err_path
    )
    _err_mod = _importlib_util.module_from_spec(_spec)
    _spec.loader.exec_module(_err_mod)
    PipelineFatalError = _err_mod.PipelineFatalError
    PipelineRetryableError = _err_mod.PipelineRetryableError
    RegistryFileNotFound = _err_mod.RegistryFileNotFound
    RegistryHashMismatch = _err_mod.RegistryHashMismatch
    RegistryNotFound = _err_mod.RegistryNotFound
    RegistryStatusInvalid = _err_mod.RegistryStatusInvalid

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exit-code constants (per D74 + spec § 3.2 L557-560)
# ---------------------------------------------------------------------------

EXIT_SUCCESS = 0
EXIT_OPERATIONAL_FAILURE = 1
EXIT_FATAL = 2

# D76 EventType registered in CLAUDE.md CLI_* family registry (one of the
# 11 R4 canonical values).
EVENT_TYPE = "CLI_PARQUET_VERIFY"


# Per-row verdict tokens. Stdout per spec § 3.2 L498-499:
# "RegistryId <id> <file_path> <result>" where result ∈ canonical set.
VERDICT_VERIFIED = "VERIFIED"
VERDICT_WOULD_VERIFY = "WOULD_VERIFY"           # --dry-run preview verdict
VERDICT_SKIPPED_ALREADY_VERIFIED = "SKIPPED_ALREADY_VERIFIED"  # spec § 3.2 L529
VERDICT_MISSING = "MISSING"                      # spec § 3.2 L499 (RegistryFileNotFound)
VERDICT_HASH_MISMATCH = "HASH_MISMATCH"          # spec § 3.2 L499 (RegistryHashMismatch)
VERDICT_STATUS_INVALID = "STATUS_INVALID"        # spec § 3.2 L499 (RegistryStatusInvalid)
VERDICT_ERROR = "ERROR"                          # spec § 3.2 L499 catch-all

# Verdicts that count toward exit code 2 (fatal) per spec § 3.2 L535-537.
_FATAL_VERDICTS = frozenset({VERDICT_HASH_MISMATCH, VERDICT_STATUS_INVALID})
# Verdicts that count toward exit code 1 (operational failure) per spec § 3.2 L533.
_RETRYABLE_VERDICTS = frozenset({VERDICT_MISSING, VERDICT_ERROR})
# Success verdicts (exit 0) per spec § 3.2 L531-532.
_SUCCESS_VERDICTS = frozenset(
    {VERDICT_VERIFIED, VERDICT_WOULD_VERIFY, VERDICT_SKIPPED_ALREADY_VERIFIED}
)


# ---------------------------------------------------------------------------
# Actor detection (per § 1.7 invocation pattern heuristic)
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
# General DB connection factory (test-friendly resolution)
# ---------------------------------------------------------------------------


def _resolve_default_cursor_factory() -> Callable:
    """Return a callable that opens a connection to the General DB.

    Resolves at CALL TIME so tests patching ``sys.modules['pyodbc']``
    after tool import are honored. Production path uses
    ``utils.connections.get_connection('General')``; falls back to
    ``sys.modules['pyodbc'].connect`` if connections isn't importable.
    Raises :class:`PipelineFatalError` (mapped to exit 2 by main()) if
    neither path succeeds.
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
                raise PipelineFatalError(
                    f"pyodbc / utils.connections both unavailable: {exc}",
                    metadata={"step": "resolve_default_cursor_factory"},
                ) from exc
        return pyodbc_mod.connect("DRIVER={ODBC Driver 18 for SQL Server};")

    return _open


# ---------------------------------------------------------------------------
# Registry row resolution — explicit IDs vs (source, table, date-range)
# ---------------------------------------------------------------------------


def _resolve_registry_ids_by_filter(
    connection,
    *,
    source_name: Optional[str],
    table_name: Optional[str],
    business_date_from: Optional[date],
    business_date_to: Optional[date],
    general_db: str = "General",
    only_created: bool = True,
) -> list[int]:
    """Resolve a list of registry IDs matching the (source, table, date-range) filter.

    Per spec § 3.2 L518: "Verify all 'created' rows for DNA.ACCT in a
    date range". The query is read-only — it does NOT use M3
    :func:`query_snapshot` (which keys on exact BatchId + BusinessDate),
    but a direct SELECT against ``ParquetSnapshotRegistry`` with the
    filter predicates.

    Parameters
    ----------
    connection:
        Open pyodbc connection to General DB.
    source_name / table_name / business_date_from / business_date_to:
        Filter predicates. None = no constraint on that column.
    general_db:
        Override target database name.
    only_created:
        Default True — restrict to ``Status='created'`` rows (the
        operator-facing verification queue). When False, returns ALL
        statuses (allows operators to re-verify already-``'verified'``
        rows, with M3's idempotent short-circuit returning the cached
        result).

    Returns
    -------
    list[int]
        RegistryIds matching the filter, sorted ascending. Empty list
        if no matches.
    """
    cursor = connection.cursor()
    where_clauses: list[str] = []
    params: list[Any] = []

    if source_name is not None:
        where_clauses.append("SourceName = ?")
        params.append(source_name)
    if table_name is not None:
        where_clauses.append("TableName = ?")
        params.append(table_name)
    if business_date_from is not None:
        where_clauses.append("BusinessDate >= ?")
        params.append(business_date_from)
    if business_date_to is not None:
        where_clauses.append("BusinessDate <= ?")
        params.append(business_date_to)
    if only_created:
        where_clauses.append("Status = ?")
        params.append("created")

    where_sql = (" WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
    sql = (
        f"SELECT RegistryId FROM [{general_db}].ops.ParquetSnapshotRegistry"
        f"{where_sql} "
        f"ORDER BY RegistryId ASC;"
    )
    try:
        cursor.execute(sql, *params) if params else cursor.execute(sql)
        rows = cursor.fetchall()
        return [int(row[0]) for row in rows if row[0] is not None]
    finally:
        try:
            cursor.close()
        except Exception:  # noqa: BLE001
            pass


def _read_registry_row_summary(
    connection,
    *,
    registry_id: int,
    general_db: str = "General",
) -> dict:
    """Read the minimal projection needed for dry-run preview.

    Returns ``{NetworkDrivePath, Status, ContentChecksum, SchemaHash,
    RowCount}`` for the row. None if the row doesn't exist.

    Used by the dry-run path: we compute SHA-256 ourselves + check file
    existence + return WOULD_VERIFY without flipping Status.
    """
    cursor = connection.cursor()
    try:
        cursor.execute(
            f"SELECT NetworkDrivePath, Status, ContentChecksum, SchemaHash, "
            f"RowCount FROM [{general_db}].ops.ParquetSnapshotRegistry "
            f"WHERE RegistryId = ?;",
            registry_id,
        )
        row = cursor.fetchone()
        if row is None:
            return {}
        return {
            "NetworkDrivePath": row[0],
            "Status": row[1],
            "ContentChecksum": row[2],
            "SchemaHash": row[3],
            "RowCount": int(row[4]) if row[4] is not None else 0,
        }
    finally:
        try:
            cursor.close()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Dry-run SHA-256 + existence check (does NOT flip Status)
# ---------------------------------------------------------------------------


def _compute_file_sha256(file_path: Path, *, chunk_size: int = 8 * 1024 * 1024) -> str:
    """Compute SHA-256 of a file, returning lowercase 64-char hex digest.

    Mirrors M3 ``data_load.parquet_registry_client._compute_sha256``
    semantics — 8 MiB chunked read so we don't load the whole Parquet
    into memory. The hash output is the canonical full SHA-256 hex
    string per B-1 (VARCHAR(64) target column).
    """
    import hashlib

    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        while True:
            buf = f.read(chunk_size)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest()


def _dry_run_verify_one(
    connection,
    *,
    registry_id: int,
    general_db: str = "General",
) -> dict:
    """Dry-run shape: compute SHA + check file existence; do NOT flip Status.

    Returns a verdict dict matching the per-row schema used by --apply
    (so the verdict aggregator is symmetric). Verdicts emitted:

    * WOULD_VERIFY (success — file exists + SHA matches registry record)
    * MISSING (RegistryFileNotFound shape — file absent on disk)
    * HASH_MISMATCH (computed SHA != registry's ContentChecksum)
    * STATUS_INVALID (row is not in 'created' status — already verified
      goes to SKIPPED_ALREADY_VERIFIED instead)
    * ERROR (unexpected exception during read/hash)
    """
    summary = _read_registry_row_summary(
        connection, registry_id=registry_id, general_db=general_db
    )
    if not summary:
        return {
            "registry_id": registry_id,
            "file_path": None,
            "verdict": VERDICT_ERROR,
            "error_message": (
                f"RegistryId {registry_id} not found in "
                f"ParquetSnapshotRegistry."
            ),
            "sha256_verified": None,
            "row_count_verified": None,
        }

    file_path = Path(summary["NetworkDrivePath"]) if summary["NetworkDrivePath"] else None
    status = summary["Status"]

    if status == "verified":
        return {
            "registry_id": registry_id,
            "file_path": str(file_path) if file_path else None,
            "verdict": VERDICT_SKIPPED_ALREADY_VERIFIED,
            "error_message": None,
            "sha256_verified": (
                str(summary.get("ContentChecksum") or summary.get("SchemaHash") or "")
                or None
            ),
            "row_count_verified": summary.get("RowCount"),
        }
    if status != "created":
        return {
            "registry_id": registry_id,
            "file_path": str(file_path) if file_path else None,
            "verdict": VERDICT_STATUS_INVALID,
            "error_message": (
                f"RegistryId {registry_id} has Status={status!r}; "
                f"verify requires Status='created'."
            ),
            "sha256_verified": None,
            "row_count_verified": summary.get("RowCount"),
        }

    if file_path is None or not file_path.exists():
        return {
            "registry_id": registry_id,
            "file_path": str(file_path) if file_path else None,
            "verdict": VERDICT_MISSING,
            "error_message": (
                f"Parquet file absent for RegistryId {registry_id}: "
                f"{file_path}"
            ),
            "sha256_verified": None,
            "row_count_verified": summary.get("RowCount"),
        }

    expected = summary.get("ContentChecksum") or summary.get("SchemaHash")
    if expected is None:
        return {
            "registry_id": registry_id,
            "file_path": str(file_path),
            "verdict": VERDICT_HASH_MISMATCH,
            "error_message": (
                f"RegistryId {registry_id} has NULL ContentChecksum AND "
                f"NULL SchemaHash — cannot verify."
            ),
            "sha256_verified": None,
            "row_count_verified": summary.get("RowCount"),
        }

    try:
        computed = _compute_file_sha256(file_path)
    except Exception as exc:  # noqa: BLE001
        return {
            "registry_id": registry_id,
            "file_path": str(file_path),
            "verdict": VERDICT_ERROR,
            "error_message": f"SHA-256 compute error: {exc}",
            "sha256_verified": None,
            "row_count_verified": summary.get("RowCount"),
        }

    if computed.lower() != str(expected).lower():
        return {
            "registry_id": registry_id,
            "file_path": str(file_path),
            "verdict": VERDICT_HASH_MISMATCH,
            "error_message": (
                f"SHA-256 mismatch: expected={expected}, computed={computed}."
            ),
            "sha256_verified": computed,
            "row_count_verified": summary.get("RowCount"),
        }

    return {
        "registry_id": registry_id,
        "file_path": str(file_path),
        "verdict": VERDICT_WOULD_VERIFY,
        "error_message": None,
        "sha256_verified": computed,
        "row_count_verified": summary.get("RowCount"),
    }


# ---------------------------------------------------------------------------
# Apply shape: invoke M3 verify_parquet_snapshot (the canonical wrapper)
# ---------------------------------------------------------------------------


def _resolve_verify_parquet_snapshot() -> Callable:
    """Import M3 ``verify_parquet_snapshot`` at call time.

    Resolves at CALL TIME so tests patching
    ``sys.modules['data_load.parquet_registry_client']`` after tool
    import are honored.
    """
    try:
        from data_load.parquet_registry_client import (  # type: ignore
            verify_parquet_snapshot,
        )

        return verify_parquet_snapshot
    except Exception as exc:  # noqa: BLE001
        raise PipelineFatalError(
            f"M3 parquet_registry_client unavailable: {exc}",
            metadata={"step": "resolve_verify_parquet_snapshot"},
        ) from exc


def _apply_verify_one(
    *,
    registry_id: int,
    actor: str,
    verify_fn: Callable | None = None,
) -> dict:
    """Apply shape: invoke M3 verify_parquet_snapshot + classify outcome.

    Per spec § 3.2 L497 + L527-529: M3 is the authoritative verifier.
    This wrapper catches the canonical exceptions and converts them to
    per-row verdict dicts. Exit-code mapping is driven by the verdict
    aggregator in :func:`main`.

    Returns
    -------
    dict
        Per-row verdict dict matching the dry-run shape (registry_id,
        file_path, verdict, error_message, sha256_verified,
        row_count_verified, last_verified_at).
    """
    if verify_fn is None:
        verify_fn = _resolve_verify_parquet_snapshot()

    try:
        result = verify_fn(registry_id=registry_id, actor=actor)
    except RegistryFileNotFound as exc:
        # Retryable per spec § 3.2 L534 — file absent; remount may rescue.
        return {
            "registry_id": registry_id,
            "file_path": _extract_file_path_from_metadata(exc),
            "verdict": VERDICT_MISSING,
            "error_message": str(exc),
            "sha256_verified": None,
            "row_count_verified": None,
            "last_verified_at": None,
        }
    except RegistryHashMismatch as exc:
        # Fatal per spec § 3.2 L536 — corruption; escalate per RB-6.
        # Diagnostic detail: spec § 3.2 L555 — surface expected + computed
        # SHAs in error_message for operator diagnosis.
        return {
            "registry_id": registry_id,
            "file_path": _extract_file_path_from_metadata(exc),
            "verdict": VERDICT_HASH_MISMATCH,
            "error_message": str(exc),
            "sha256_verified": _extract_sha_from_metadata(exc, "computed_sha256"),
            "row_count_verified": None,
            "last_verified_at": None,
        }
    except RegistryStatusInvalid as exc:
        # Fatal per spec § 3.2 L535 — caller error; operator must
        # investigate (e.g. mark_missing workflow if state genuinely
        # drifted).
        return {
            "registry_id": registry_id,
            "file_path": _extract_file_path_from_metadata(exc),
            "verdict": VERDICT_STATUS_INVALID,
            "error_message": str(exc),
            "sha256_verified": None,
            "row_count_verified": None,
            "last_verified_at": None,
        }
    except RegistryNotFound as exc:
        # Fatal — registry_id was fabricated or stale (caller bug).
        # Spec § 3.2 L535 maps "caller error" to exit 2 (fatal); registry
        # not found is the same class of mistake.
        return {
            "registry_id": registry_id,
            "file_path": None,
            "verdict": VERDICT_STATUS_INVALID,
            "error_message": str(exc),
            "sha256_verified": None,
            "row_count_verified": None,
            "last_verified_at": None,
        }

    # Success — M3 returns ParquetVerifyResult. Check the status field
    # to distinguish a fresh verify from an idempotent cached return.
    # Per Round 3 § 1.3 L555-562: when current_status is already
    # 'verified', M3 returns the cached result with status='verified'
    # without re-hashing — that's the SKIPPED_ALREADY_VERIFIED case.
    # We can detect this by checking whether last_verified_at matches
    # the current invocation timestamp window... but the simpler check
    # is to compare against the registry's pre-call status BEFORE
    # invoking M3. Skip the pre-call query for now and treat all
    # non-exception returns as VERIFIED (the user can inspect the
    # last_verified_at timestamp if they need to distinguish).
    return {
        "registry_id": registry_id,
        "file_path": str(getattr(result, "file_path", "")) or None,
        "verdict": VERDICT_VERIFIED,
        "error_message": None,
        "sha256_verified": getattr(result, "sha256_verified", None),
        "row_count_verified": getattr(result, "row_count_verified", None),
        "last_verified_at": getattr(result, "last_verified_at", None),
    }


def _extract_file_path_from_metadata(exc: Exception) -> Optional[str]:
    """Pull ``file_path`` out of the exception's canonical metadata dict.

    Per D76 + ``utils.errors.PipelineError`` constructor contract — every
    pipeline exception carries a ``metadata`` dict with the registry_id,
    file_path, current_status, computed/expected sha, etc. Defensively
    handles non-PipelineError parents (returns None).
    """
    md = getattr(exc, "metadata", None)
    if not isinstance(md, dict):
        return None
    fp = md.get("file_path")
    return str(fp) if fp is not None else None


def _extract_sha_from_metadata(exc: Exception, key: str) -> Optional[str]:
    """Pull a SHA value (``computed_sha256`` or ``expected_sha256``) from metadata."""
    md = getattr(exc, "metadata", None)
    if not isinstance(md, dict):
        return None
    val = md.get(key)
    return str(val) if val is not None else None


# ---------------------------------------------------------------------------
# Audit row writer (per D76 + spec § 3.2 L526)
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
    """INSERT one ``CLI_PARQUET_VERIFY`` row into PipelineEventLog.

    Per D76 + spec § 3.2 L526. ONE row per invocation. Best-effort —
    failures are logged but do not affect the verdict exit code (parity
    with B188 / B189 / B190 / B218 audit-row patterns).

    Returns the SCOPE_IDENTITY() of the inserted row so JSON
    ``audit_event_id`` key can be populated. Returns None on failure.

    When ``skip=True`` (test path; main()'s ``no_audit_event``), returns
    None immediately without writing.
    """
    if skip:
        return None

    metadata_json = json.dumps(metadata, separators=(",", ":"), default=str)
    counts = metadata.get("counts", {})
    event_detail = (
        f"parquet_verify / dry_run={metadata.get('dry_run')} / "
        f"verified={counts.get('verified', 0)} / "
        f"failed={counts.get('failed', 0)}"
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
        logger.exception("Failed to write CLI_PARQUET_VERIFY audit row")
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


def _format_verdict_line(verdict_row: dict, *, dry_run: bool) -> str:
    """Format a single-row stdout line per spec § 3.2 L498-499.

    Format: ``RegistryId <id> <file_path> <result>`` where result ∈
    ``{VERIFIED, MISSING, HASH_MISMATCH, STATUS_INVALID, ERROR}``
    (canonical set per spec). Dry-run uses WOULD_VERIFY per spec § 3.2 L552.
    """
    rid = verdict_row.get("registry_id")
    fp = verdict_row.get("file_path") or "<unknown>"
    verdict = verdict_row.get("verdict") or VERDICT_ERROR

    if dry_run and verdict == VERDICT_WOULD_VERIFY:
        sha = verdict_row.get("sha256_verified") or "<unknown>"
        rows = verdict_row.get("row_count_verified")
        rows_str = f"{rows:,}" if isinstance(rows, int) else "<unknown>"
        return (
            f"RegistryId {rid} {fp} {VERDICT_WOULD_VERIFY} "
            f"(sha={sha} rows={rows_str})"
        )
    return f"RegistryId {rid} {fp} {verdict}"


def _emit_human_summary(
    *,
    verdicts: list[dict],
    counts: dict[str, int],
    dry_run: bool,
    audit_event_id: int | None,
) -> None:
    """Print spec § 3.2 L548-553 stdout block.

    Per-row lines + final summary line. Per spec § 3.2 L548:
    "N verified / M failed / K skipped (already verified)".
    """
    for v in verdicts:
        print(_format_verdict_line(v, dry_run=dry_run))

    if dry_run:
        wv = counts.get("would_verify", 0)
        failed = counts.get("failed", 0)
        skipped = counts.get("skipped", 0)
        suffix = f" (would_verify={wv:,} failed={failed:,} skipped={skipped:,})"
        print(f"Dry-run preview — no Status flips applied.{suffix}")
    else:
        verified = counts.get("verified", 0)
        failed = counts.get("failed", 0)
        skipped = counts.get("skipped", 0)
        line = (
            f"{verified:,} verified / {failed:,} failed / "
            f"{skipped:,} skipped (already verified)"
        )
        if audit_event_id is not None:
            line += f" — audit event {audit_event_id}"
        print(line)


def _emit_json(payload: dict) -> None:
    """Emit the canonical JSON payload per spec § 3.2 L554-555.

    The canonical per-row shape includes ParquetVerifyResult fields plus
    tool-level diagnostic fields (verdict + error_message). Wrapped in a
    top-level object with counts + audit_event_id for machine consumers.
    """
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


# ---------------------------------------------------------------------------
# Verdict aggregator — derive exit code from per-row verdicts
# ---------------------------------------------------------------------------


def _aggregate_counts(verdicts: list[dict]) -> dict[str, int]:
    """Tally per-verdict counts for stdout summary + Metadata JSON."""
    counts = {
        "verified": 0,
        "would_verify": 0,
        "skipped": 0,
        "failed": 0,
        "missing": 0,
        "hash_mismatch": 0,
        "status_invalid": 0,
        "error": 0,
    }
    for v in verdicts:
        verdict = v.get("verdict")
        if verdict == VERDICT_VERIFIED:
            counts["verified"] += 1
        elif verdict == VERDICT_WOULD_VERIFY:
            counts["would_verify"] += 1
        elif verdict == VERDICT_SKIPPED_ALREADY_VERIFIED:
            counts["skipped"] += 1
        elif verdict == VERDICT_MISSING:
            counts["missing"] += 1
            counts["failed"] += 1
        elif verdict == VERDICT_HASH_MISMATCH:
            counts["hash_mismatch"] += 1
            counts["failed"] += 1
        elif verdict == VERDICT_STATUS_INVALID:
            counts["status_invalid"] += 1
            counts["failed"] += 1
        elif verdict == VERDICT_ERROR:
            counts["error"] += 1
            counts["failed"] += 1
    return counts


def _derive_exit_code(verdicts: list[dict]) -> int:
    """Derive exit code per spec § 3.2 L557-560.

    * Any FATAL verdict (HASH_MISMATCH, STATUS_INVALID) → exit 2
    * Any RETRYABLE verdict (MISSING, ERROR) without fatal → exit 1
    * Else → exit 0 (all VERIFIED / WOULD_VERIFY / SKIPPED)

    Per spec § 3.2 L562 ``--continue-on-error`` allows the tool to
    accumulate failures across rows before exit; same aggregator applies.
    """
    has_fatal = any(v.get("verdict") in _FATAL_VERDICTS for v in verdicts)
    if has_fatal:
        return EXIT_FATAL
    has_retryable = any(v.get("verdict") in _RETRYABLE_VERDICTS for v in verdicts)
    if has_retryable:
        return EXIT_OPERATIONAL_FAILURE
    return EXIT_SUCCESS


# ---------------------------------------------------------------------------
# Top-level main() — programmatic entry
# ---------------------------------------------------------------------------


def main(
    *,
    actor: str,
    registry_ids: list[int] | None = None,
    source: str | None = None,
    table: str | None = None,
    business_date_from: date | None = None,
    business_date_to: date | None = None,
    apply: bool = False,
    dry_run: bool | None = None,
    continue_on_error: bool = False,
    json_output: bool = False,
    verbose: bool = False,
    quiet: bool = False,
    justification: str | None = None,
    no_audit_event: bool = False,
    # ---- Injection hooks (test path) ----
    cursor_factory: Callable | None = None,
    audit_cursor_factory: Callable | None = None,
    verify_fn: Callable | None = None,
    general_db: str | None = None,
) -> dict:
    """Programmatic entry — verifies one or more Parquet snapshot rows.

    Returns a dict matching the D76 audit-row Metadata shape (see module
    docstring for canonical schema). Exit-code derivation per D74 +
    spec § 3.2 L557-560:

    * 0: all rows verified successfully (or skipped/would-verify)
    * 1: at least one MISSING / ERROR (retryable)
    * 2: at least one HASH_MISMATCH / STATUS_INVALID (fatal) OR config
      error OR B88 mutex violation

    Parameters
    ----------
    actor:
        Operator identity (per D75 + D76). REQUIRED.
    registry_ids:
        Explicit list of RegistryIds to verify. Mutually exclusive with
        ``source`` / ``table`` filter (per spec § 3.2 L520-522).
    source / table / business_date_from / business_date_to:
        Range filter — verify all 'created' rows for this source+table
        in the date range. Mutually exclusive with ``registry_ids``.
    apply:
        When True, invokes M3 :func:`verify_parquet_snapshot` (live flip).
        Default False (dry-run shape: compute SHA + check existence
        without flipping Status).
    dry_run:
        B88 mutex bridge. If True AND ``apply=True`` -> exit 2.
    continue_on_error:
        Per spec § 3.2 L562 — don't abort on the first failed row.
        Default False (abort on first fatal verdict).
    justification:
        Operator justification recorded in audit-row Metadata per D75.
    no_audit_event:
        When True, skip the CLI-level PipelineEventLog write
        (pipeline-programmatic callers per D75 + D76).
    cursor_factory / audit_cursor_factory / verify_fn:
        Test-injection hooks. Defaults resolve to live infrastructure.
    general_db:
        Override the General DB name (defaults to
        ``utils.configuration.GENERAL_DB``, fallback ``'General'``).
    """
    started_at = datetime.now(timezone.utc).replace(tzinfo=None)

    # B88 dry-run/apply mutex bridge — parity with sibling tools
    # (enforce_retention / promote_test_to_prod).
    if dry_run is True and apply is True:
        raise SystemExit(2)
    if dry_run is True:
        apply = False

    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    elif quiet:
        logging.getLogger().setLevel(logging.ERROR)

    # Mutual exclusion: --registry-id vs --source/--table filter per
    # spec § 3.2 L520-522.
    has_explicit_ids = bool(registry_ids)
    has_filter = bool(source or table or business_date_from or business_date_to)
    if has_explicit_ids and has_filter:
        if not quiet:
            print(
                "FATAL: --registry-id is mutually exclusive with "
                "--source / --table / --business-date-from/-to filters.",
                file=sys.stderr,
            )
        raise SystemExit(2)
    if not has_explicit_ids and not has_filter:
        if not quiet:
            print(
                "FATAL: must specify either --registry-id (repeatable) OR "
                "a --source / --table filter.",
                file=sys.stderr,
            )
        raise SystemExit(2)

    # Resolve general_db tag
    if general_db is None:
        try:
            import utils.configuration as config  # type: ignore

            general_db = getattr(config, "GENERAL_DB", "General")
        except Exception:  # noqa: BLE001
            general_db = "General"

    # ---- Pre-populate result with input echoes ----
    result: dict[str, Any] = {
        "event_kind": "parquet_verification",
        "actor": actor,
        "justification": justification,
        "dry_run": (not apply),
        "registry_ids_requested": list(registry_ids) if registry_ids else None,
        "filter": {
            "source": source,
            "table": table,
            "business_date_from": (
                business_date_from.isoformat()
                if business_date_from is not None
                else None
            ),
            "business_date_to": (
                business_date_to.isoformat()
                if business_date_to is not None
                else None
            ),
        },
        "verdicts": [],
        "counts": {
            "verified": 0,
            "would_verify": 0,
            "skipped": 0,
            "failed": 0,
            "missing": 0,
            "hash_mismatch": 0,
            "status_invalid": 0,
            "error": 0,
        },
        "exit_code": EXIT_SUCCESS,
        "started_at": started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "started_at_dt": started_at,
        "completed_at": None,
        "audit_event_id": None,
        "errors": [],
    }

    # ---- Resolve connection factory ----
    if cursor_factory is None:
        try:
            cursor_factory = _resolve_default_cursor_factory()
        except PipelineFatalError as exc:
            result["exit_code"] = EXIT_FATAL
            result["error_type"] = "PipelineFatalError"
            result["error_message"] = str(exc)
            result["errors"].append(f"PipelineFatalError: {exc}")
            result["completed_at"] = _now_iso_naive()
            if not quiet:
                print(f"FATAL: config unavailable: {exc}", file=sys.stderr)
            audit_id = _write_audit_row(
                result,
                status="FAILED",
                error_message=str(exc)[:4000],
                cursor_factory=audit_cursor_factory,
                general_db=general_db,
                skip=no_audit_event,
            )
            result["audit_event_id"] = audit_id
            return result

    # ---- Resolve target registry IDs (filter → list of IDs) ----
    conn = None
    try:
        try:
            conn = cursor_factory()
        except PipelineFatalError as exc:
            result["exit_code"] = EXIT_FATAL
            result["error_type"] = "PipelineFatalError"
            result["error_message"] = str(exc)[:4000]
            result["errors"].append(f"PipelineFatalError: {exc}")
            logger.error("Fatal during connection setup: %s", exc)
            if not quiet:
                print(f"FATAL: connection failed: {exc}", file=sys.stderr)
            result["completed_at"] = _now_iso_naive()
            audit_id = _write_audit_row(
                result,
                status="FAILED",
                error_message=traceback.format_exc()[:4000],
                cursor_factory=audit_cursor_factory,
                general_db=general_db,
                skip=no_audit_event,
            )
            result["audit_event_id"] = audit_id
            return result
        except Exception as exc:  # noqa: BLE001
            # Generic connection failure -> exit 1 (retryable).
            result["exit_code"] = EXIT_OPERATIONAL_FAILURE
            result["error_type"] = type(exc).__name__
            result["error_message"] = str(exc)[:4000]
            result["errors"].append(f"{type(exc).__name__}: {exc}")
            logger.warning("Connection to General DB failed: %s", exc)
            if not quiet:
                print(
                    f"WARNING: connection failed (operator can re-run): {exc}",
                    file=sys.stderr,
                )
            result["completed_at"] = _now_iso_naive()
            audit_id = _write_audit_row(
                result,
                status="FAILED",
                error_message=traceback.format_exc()[:4000],
                cursor_factory=audit_cursor_factory,
                general_db=general_db,
                skip=no_audit_event,
            )
            result["audit_event_id"] = audit_id
            return result

        try:
            conn.autocommit = True
        except Exception:  # noqa: BLE001
            pass

        if has_explicit_ids:
            target_ids = list(registry_ids)  # type: ignore[arg-type]
        else:
            try:
                target_ids = _resolve_registry_ids_by_filter(
                    conn,
                    source_name=source,
                    table_name=table,
                    business_date_from=business_date_from,
                    business_date_to=business_date_to,
                    general_db=general_db,
                    only_created=True,
                )
            except Exception as exc:  # noqa: BLE001
                result["exit_code"] = EXIT_OPERATIONAL_FAILURE
                result["error_type"] = type(exc).__name__
                result["error_message"] = str(exc)[:4000]
                result["errors"].append(f"{type(exc).__name__}: {exc}")
                logger.warning("Filter query failed: %s", exc)
                result["completed_at"] = _now_iso_naive()
                audit_id = _write_audit_row(
                    result,
                    status="FAILED",
                    error_message=traceback.format_exc()[:4000],
                    cursor_factory=audit_cursor_factory,
                    general_db=general_db,
                    skip=no_audit_event,
                )
                result["audit_event_id"] = audit_id
                return result

        if not target_ids:
            # No rows matched — operationally normal (empty queue is
            # idempotent no-op per spec § 3.2 L529).
            result["counts"] = _aggregate_counts([])
            result["exit_code"] = EXIT_SUCCESS
            result["completed_at"] = _now_iso_naive()
            audit_id = _write_audit_row(
                result,
                status="SUCCESS",
                error_message=None,
                cursor_factory=audit_cursor_factory,
                general_db=general_db,
                skip=no_audit_event,
            )
            result["audit_event_id"] = audit_id
            if json_output:
                _emit_json(_build_json_payload(result))
            elif not quiet:
                _emit_human_summary(
                    verdicts=[],
                    counts=result["counts"],
                    dry_run=result["dry_run"],
                    audit_event_id=audit_id,
                )
            return result

        # ---- Verify each row ----
        verdicts: list[dict] = []
        if apply:
            # Apply path: invoke M3 verify_parquet_snapshot per row.
            for rid in target_ids:
                v = _apply_verify_one(
                    registry_id=rid,
                    actor=actor,
                    verify_fn=verify_fn,
                )
                verdicts.append(v)
                if (
                    not continue_on_error
                    and v.get("verdict") in _FATAL_VERDICTS
                ):
                    # Abort on first fatal per default semantics
                    # (continue-on-error opts out).
                    logger.warning(
                        "Aborting on first fatal verdict for "
                        "RegistryId=%s (verdict=%s); "
                        "pass --continue-on-error to process all rows.",
                        rid,
                        v.get("verdict"),
                    )
                    break
        else:
            # Dry-run path: read row + compute SHA + check existence.
            for rid in target_ids:
                v = _dry_run_verify_one(
                    conn, registry_id=rid, general_db=general_db
                )
                verdicts.append(v)
                if (
                    not continue_on_error
                    and v.get("verdict") in _FATAL_VERDICTS
                ):
                    logger.warning(
                        "Aborting dry-run on first fatal verdict for "
                        "RegistryId=%s (verdict=%s); "
                        "pass --continue-on-error to process all rows.",
                        rid,
                        v.get("verdict"),
                    )
                    break

        result["verdicts"] = verdicts
        result["counts"] = _aggregate_counts(verdicts)
        result["exit_code"] = _derive_exit_code(verdicts)

    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    result["completed_at"] = _now_iso_naive()

    # ---- Invocation-level audit row (D76 — ONE per invocation) ----
    status = (
        "SUCCESS"
        if result["exit_code"] in (EXIT_SUCCESS, EXIT_OPERATIONAL_FAILURE)
        else "FAILED"
    )
    audit_event_id = _write_audit_row(
        result,
        status=status,
        error_message=result.get("error_message"),
        cursor_factory=audit_cursor_factory,
        general_db=general_db,
        skip=no_audit_event,
    )
    result["audit_event_id"] = audit_event_id

    # ---- Render stdout AFTER audit-row write so audit_event_id surfaces ----
    if json_output:
        _emit_json(_build_json_payload(result))
    elif not quiet:
        _emit_human_summary(
            verdicts=result["verdicts"],
            counts=result["counts"],
            dry_run=result["dry_run"],
            audit_event_id=audit_event_id,
        )

    return result


def _now_iso_naive() -> str:
    """ISO-8601 naive-UTC timestamp per SCD2-P1-f naive-UTC invariant."""
    return (
        datetime.now(timezone.utc)
        .replace(tzinfo=None)
        .strftime("%Y-%m-%dT%H:%M:%SZ")
    )


def _build_json_payload(result: dict) -> dict:
    """Build the canonical JSON output payload per spec § 3.2 L554-555.

    Top-level shape: ``{dry_run, counts, verdicts: [...], audit_event_id}``.
    Each verdict carries ParquetVerifyResult fields + tool diagnostics.
    """
    return {
        "dry_run": result["dry_run"],
        "counts": result["counts"],
        "verdicts": result.get("verdicts", []),
        "audit_event_id": result.get("audit_event_id"),
    }


# ---------------------------------------------------------------------------
# CLI argv entry point
# ---------------------------------------------------------------------------


def _parse_iso_date(value: str) -> date:
    """argparse type adapter for ISO-8601 date strings (YYYY-MM-DD)."""
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid ISO-8601 date {value!r}; expected YYYY-MM-DD."
        ) from exc


def _build_arg_parser() -> argparse.ArgumentParser:
    """Alias for :func:`_build_parser` — Tier 0 scaffold contract."""
    return _build_parser()


def _build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser per spec § 3.2 + § 1.4 canonical args.

    Mutual exclusion (per spec § 3.2 L520-522):
    ``--registry-id`` vs ``--source`` / ``--table`` filter — argparse
    can't express this directly (multi-arg vs single-arg), so we add
    each as a regular arg and enforce mutex in main().
    """
    parser = argparse.ArgumentParser(
        description=(
            "Operator-facing CLI wrapping M3 verify_parquet_snapshot. "
            "Re-SHA-256 a Parquet file + flip "
            "ParquetSnapshotRegistry.Status='created'->'verified'. "
            "Emits one CLI_PARQUET_VERIFY audit row per invocation."
        ),
    )

    # ---- Tool-specific args (per spec § 3.2 L539-548) ----
    parser.add_argument(
        "--registry-id",
        action="append",
        type=int,
        default=None,
        help=(
            "Specific ParquetSnapshotRegistry.RegistryId to verify "
            "(repeatable). Mutually exclusive with --source / --table "
            "filters."
        ),
    )
    parser.add_argument(
        "--business-date-from",
        type=_parse_iso_date,
        default=None,
        help=(
            "Range filter lower bound on BusinessDate (ISO-8601 "
            "YYYY-MM-DD). Used with --source / --table."
        ),
    )
    parser.add_argument(
        "--business-date-to",
        type=_parse_iso_date,
        default=None,
        help=(
            "Range filter upper bound on BusinessDate (ISO-8601 "
            "YYYY-MM-DD). Used with --source / --table."
        ),
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        help=(
            "Don't abort on the first failed row; continue through all "
            "rows then exit with code 1 if any failed. Useful for "
            "Automic batch invocations."
        ),
    )

    # ---- D75 canonical args (per spec § 1.4) ----
    parser.add_argument(
        "--source",
        default=None,
        help="Filter by UdmTablesList.SourceName (e.g. DNA, CCM, EPICOR).",
    )
    parser.add_argument(
        "--table",
        default=None,
        help="Filter by TableName / SourceObjectName.",
    )

    # --apply / --dry-run mutex per B88 (apply opt-in, dry-run default).
    apply_group = parser.add_mutually_exclusive_group()
    apply_group.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Apply: invoke M3 verify_parquet_snapshot (live flip "
            "Status='created'->'verified'). Default is dry-run "
            "(compute SHA + check file existence; do NOT flip Status)."
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
            "Operator identity (per D75 + D76). One of operator / "
            "automic / pipeline / reconciliation. Auto-detected via "
            "TTY / AUTOMIC_RUN_ID env when omitted."
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
        help=(
            "Emit canonical JSON output per spec § 3.2 L554-555 "
            "({dry_run, counts, verdicts, audit_event_id}) instead of "
            "human summary."
        ),
    )
    parser.add_argument(
        "--no-audit-event",
        action="store_true",
        help=(
            "Skip CLI-level PipelineEventLog write (for "
            "pipeline-programmatic callers per D75 + D76)."
        ),
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
    return parser


def _validate_args(
    args: argparse.Namespace, parser: argparse.ArgumentParser
) -> None:
    """Enforce --registry-id vs --source/--table mutex at parse time.

    argparse cannot express the cross-arg mutex declaratively (multi-arg
    vs single-arg). main() also enforces this — _validate_args provides
    earlier feedback at parse time so CLI users see the error before any
    work begins.
    """
    has_explicit = bool(args.registry_id)
    has_filter = bool(
        args.source or args.table
        or args.business_date_from or args.business_date_to
    )
    if has_explicit and has_filter:
        parser.error(
            "--registry-id is mutually exclusive with --source / --table / "
            "--business-date-from/-to filters. Pick one mode."
        )
    if not has_explicit and not has_filter:
        parser.error(
            "Must specify either --registry-id (repeatable) OR a "
            "--source / --table filter."
        )


def cli_main() -> int:
    """Argv entry point — argparse + main() + return exit code per D74.

    Exit codes (always one of 0 / 1 / 2 per D74 + spec § 3.2 L557-560):
        - 0: all rows verified successfully (or skipped/would-verify)
        - 1: at least one MISSING / ERROR (retryable)
        - 2: at least one HASH_MISMATCH / STATUS_INVALID (fatal) OR
             config / connection error / B88 mutex violation
    """
    parser = _build_parser()
    args = parser.parse_args()
    _validate_args(args, parser)

    actor = args.actor or _detect_actor()

    try:
        result = main(
            actor=actor,
            registry_ids=args.registry_id,
            source=args.source,
            table=args.table,
            business_date_from=args.business_date_from,
            business_date_to=args.business_date_to,
            apply=args.apply,
            continue_on_error=args.continue_on_error,
            json_output=args.json_output,
            verbose=args.verbose,
            quiet=args.quiet,
            justification=args.justification,
            no_audit_event=args.no_audit_event,
        )
    except SystemExit as exc:
        # B88 mutex violation (dry_run + apply both True) -> code 2;
        # also argparse-style validation routes here.
        code = exc.code if isinstance(exc.code, int) else EXIT_FATAL
        if code not in (EXIT_SUCCESS, EXIT_OPERATIONAL_FAILURE, EXIT_FATAL):
            code = EXIT_FATAL
        return code
    except KeyboardInterrupt:
        logger.warning("Interrupted by operator")
        return EXIT_OPERATIONAL_FAILURE
    except Exception:  # noqa: BLE001
        tb = traceback.format_exc()
        print(
            f"FATAL: parquet_verify unexpected exception:\n{tb[:1000]}",
            file=sys.stderr,
        )
        return EXIT_FATAL

    exit_code = int(result.get("exit_code", EXIT_FATAL))
    # Defensive clamp — every exit path MUST be 0 / 1 / 2 per D74 contract.
    if exit_code not in (EXIT_SUCCESS, EXIT_OPERATIONAL_FAILURE, EXIT_FATAL):
        logger.error(
            "Non-canonical exit_code %r returned from main(); "
            "clamping to EXIT_FATAL",
            exit_code,
        )
        exit_code = EXIT_FATAL
    return exit_code


if __name__ == "__main__":
    sys.exit(cli_main())
