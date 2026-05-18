"""Round 4 § 3.10 — ``tools/log_retention_cleanup.py``.

Per **Round 4 § 3.10** at ``docs/migration/phase1/04_tools.md`` L1220-1305
(canonical spec) + **CLAUDE.md "Log retention policy"** (`30 days of
DEBUG/INFO, 90 days of WARNING+, indefinite for ERROR/CRITICAL`).

Purge old ``General.ops.PipelineLog`` rows per the retention policy
documented in CLAUDE.md. Independent of ``enforce_retention.py`` (§ 3.8)
which handles vault / provenance / CCPA categories — log purge cadence
differs from vault retention cadence so this tool is PipelineLog-specific.

No Round 3 module wrap (lightweight enough that a dedicated module isn't
needed per spec L1224). Direct SQL invocations against
``General.ops.PipelineLog`` via ``utils.connections.get_general_connection()``.

What this tool does
-------------------

1. Acquire ``sp_getapplock`` on resource ``'log_retention_cleanup'``
   (`@LockOwner='Session'`) — ensures one cleanup at a time (B-2 lessons
   on lock escalation; mirrors CLAUDE.md SCD2_UPDATE_BATCH_SIZE gotcha).
2. SELECT per-LogLevel cohort counts eligible for purge (dry-run preview):
   - DEBUG / INFO older than ``--debug-info-days`` (default 30)
   - WARNING older than ``--warning-days`` (default 90)
   - ERROR / CRITICAL: NEVER purged by this tool — retained indefinite
     per CLAUDE.md policy + canonical
     ``phase1/01_database_schema.md`` § 2 L215-216 ``CK_PipelineLog_LogLevel``
     IN ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL').
3. With ``--apply``: DELETE per-cohort in batches of ``--batch-size``
   (default 50000) — TOP(N) loop until 0 rows affected, then move to
   next cohort. ERROR / CRITICAL never appear in any DELETE WHERE clause.
4. Write ONE ``CLI_LOG_RETENTION_CLEANUP`` row to
   ``General.ops.PipelineEventLog`` per D76 — ``Metadata`` JSON includes
   per-level counts (eligible / purged / retained), thresholds, batch
   size, actor, justification, dry_run, exit_code, event_kind='cleanup'.
5. Render stdout: human-readable per-cohort table OR canonical JSON
   per ``--json``.
6. Exit 0 / 1 / 2 per D74 (see Exit codes below) — every exit path
   honors the contract.

CLI contract
------------

::

    # Daily Automic cleanup (proposed B80 JOB_LOG_CLEANUP)
    sudo -u pipeline /opt/pipeline/current/tools/log_retention_cleanup.py \\
        --apply --actor automic

    # Operator dry-run review (default behavior)
    python3 tools/log_retention_cleanup.py --actor operator

    # Tighter retention windows (testing only)
    python3 tools/log_retention_cleanup.py --apply --actor pipeline-lead \\
        --debug-info-days 7 --warning-days 30 \\
        --justification "tightened retention for capacity remediation"

Exit codes (per D74 + spec § 3.10 L1292-1295)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* **0** — cleanup completed (or dry-run preview produced); zero contention
* **1** — lock contention OR partial-batch error; operator can re-run later
* **2** — fatal: config / connection / unexpected (FATAL exception class)

Audit row (per D76 + spec § 3.10 L1234)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* ``General.ops.PipelineEventLog.EventType = 'CLI_LOG_RETENTION_CLEANUP'``
* ONE row per INVOCATION (per spec § 3.10 produces — distinct from per-cohort
  DELETE statements which are NOT audited individually; the per-level
  counts surface in Metadata JSON)
* ``Status in {SUCCESS, FAILED}`` (SUCCESS for exit 0/1 dry-run + apply
  + lock-contention warn; FAILED for exit 2 fatal)
* ``Metadata`` JSON shape::

    {
        "event_kind": "cleanup",
        "actor": "<operator>",
        "justification": "<text or null>",
        "dry_run": <bool>,
        "debug_info_days": <int>,
        "warning_days": <int>,
        "batch_size": <int>,
        "purged": {"DEBUG": N, "INFO": M, "WARNING": K},
        "retained": {"ERROR": N, "CRITICAL": M},
        "exit_code": <int>,
        "lock_acquired": <bool>,
        "started_at": "<ISO-8601 naive-UTC>",
        "completed_at": "<ISO-8601 naive-UTC>"
    }

Classification per ``udm-execution-classifier`` skill
-----------------------------------------------------

* **Trigger**: PRIMARY: Scheduled (proposed Automic ``JOB_LOG_CLEANUP``
  per B80 — currently NOT in frozen-11 inventory; Round 6 deployment
  amends the job set). SECONDARY: Manual operator CLI for ad-hoc
  capacity remediation.
* **Frequency**: PRIMARY Recurring (daily / weekly); SECONDARY
  one-time ad-hoc.
* **Idempotency**: YES — re-running produces zero rows purged (already
  purged on prior run; nothing < cutoff remains in cohort). Partial-batch
  crash leaves a deterministic state — next invocation completes the
  purge from where the prior one stopped.
* **Concurrency**: ``sp_getapplock`` on ``('log_retention_cleanup',)``
  ensures one cleanup at a time. ``--workers`` NOT supported — serial
  is correct (single batched DELETE per cohort; B-2 lock-escalation
  concern caps batch size at 50000 conservatively).
* **Audit-row family**: ``CLI_LOG_RETENTION_CLEANUP`` per D76 + CLAUDE.md
  ``CLI_*`` family registry (the 11 R4 canonical values).
* **Routing**: PRIMARY tracker ``phase1/02_configuration.md`` § 5.1
  Automic inventory (frozen-11 + proposed JOB_LOG_CLEANUP per B80).
  SECONDARY tracker ``ONE_OFF_SCRIPTS.md`` operator tools table.

D-numbers consumed
------------------

D15 (idempotency invariant — re-runs produce zero net writes),
D26 (audit-trail append-only — the purge is the deliberate exception
to D26 per CLAUDE.md retention policy; ERROR / CRITICAL preserved
indefinite),
D31 (PowerBI consumes PipelineLog — purge does not affect ERROR /
CRITICAL which power dashboards),
D67 (Tier 0 smoke discipline),
D74-D77 (CLI exit-code contract + argument naming + audit-row contract +
Tier 0 6-canonical-assertion scaffold),
D92 (forward-only additive),
D103 (Claude Code security model — tool runs OUTSIDE ``/debi`` working
directory in production; credentials per D103 layer 4-7 unaffected).

Canonical references cited (per Pitfall #9.l producer self-check)
-----------------------------------------------------------------

* PipelineLog DDL: ``phase1/01_database_schema.md`` § 2 L197-221
  (re-read at producer Gate 1 self-check per HANDOFF §8 Pitfall #9.l —
  9.l directive "re-read the canonical DDL spec section BEFORE
  authoring a fix that references canonical schema columns").
  Real columns referenced by this tool: ``LogLevel`` (NVARCHAR(10) NOT NULL
  L202), ``CreatedAt`` (DATETIME2(3) NOT NULL DEFAULT SYSUTCDATETIME() L209).
  CHECK constraint: ``CK_PipelineLog_LogLevel CHECK LogLevel IN ('DEBUG',
  'INFO', 'WARNING', 'ERROR', 'CRITICAL')`` L215-216.
* CLI conventions: ``phase1/04_tools.md`` § 1.4 (canonical args) +
  § 1.7 (invocation pattern heuristic — AUTOMIC_RUN_ID env + isatty) +
  § 1.8 (exit-code mapping) + § 1.9 (boilerplate template).
* B-2 lock escalation gotcha: ``CLAUDE.md`` "B-2: SCD2 UPDATE batch
  size must stay below 5,000" — mirrors why per-batch DELETE size is
  capped at 50000 conservatively for the lighter-weight LogLevel column.

See also
--------

* ``data_load/_exceptions.py`` — ``LogRetentionCleanupError`` /
  ``LogRetentionLockContention`` / ``LogRetentionConfigError`` (per
  B215 canonical exception module).
* ``orchestration/table_lock.py`` — ``sp_getapplock`` Session-owned
  pattern (`@LockOwner='Session'` per W-8 RCSI analysis — Transaction-
  scoped locks are NOT used).
* CLAUDE.md "Log retention policy" — retention semantics + ERROR /
  CRITICAL never-purge invariant.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

# Project root on sys.path so we can reach data_load + utils.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Exception classes from the canonical _exceptions module (B215 pattern —
# tools import from data_load._exceptions because tests may mock the
# engine modules as MagicMock, replacing class symbols with MagicMock
# attributes and breaking ``except SomeError as exc:`` blocks).
try:
    from data_load._exceptions import (  # noqa: E402
        LogRetentionCleanupError,
        LogRetentionConfigError,
        LogRetentionLockContention,
    )
except (ImportError, ModuleNotFoundError):
    # Defensive fallback for environments where ``data_load`` is mocked
    # as MagicMock — re-import the file directly from the filesystem.
    import importlib.util as _importlib_util  # noqa: E402

    _exc_path = Path(__file__).resolve().parent.parent / "data_load" / "_exceptions.py"
    _spec = _importlib_util.spec_from_file_location(
        "data_load._exceptions_log_retention", _exc_path
    )
    _exc_mod = _importlib_util.module_from_spec(_spec)
    _spec.loader.exec_module(_exc_mod)
    LogRetentionCleanupError = _exc_mod.LogRetentionCleanupError
    LogRetentionLockContention = _exc_mod.LogRetentionLockContention
    LogRetentionConfigError = _exc_mod.LogRetentionConfigError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exit-code constants (per D74 + spec § 3.10 L1292-1295)
# ---------------------------------------------------------------------------

EXIT_SUCCESS = 0
EXIT_WARNING = 1
EXIT_FATAL = 2

# D76 EventType registered in CLAUDE.md CLI_* family registry (one of the
# 11 R4 canonical values).
EVENT_TYPE = "CLI_LOG_RETENTION_CLEANUP"

# sp_getapplock resource name per spec § 3.10 L1251 "sp_getapplock on
# ('log_retention_cleanup',) ensures one cleanup at a time".
LOCK_RESOURCE = "log_retention_cleanup"

# Per spec § 3.10 L1274 + Round 6 § 7.8 (B104 closure 2026-05-14) — 4000
# batch mirrors ``config.SCD2_UPDATE_BATCH_SIZE`` (B-2 lock-escalation
# threshold: SQL Server escalates to table-level exclusive lock at
# ~5000 locks). Original Round 4 default was 50000 — closed at Round 6
# § 7.8 (code default) + § 8.3 (doc default). The cited B-2 lesson in
# CLAUDE.md is authoritative: stay below 5000 to keep RCSI semantics.
DEFAULT_BATCH_SIZE = 4000

# Per CLAUDE.md retention policy + spec § 3.10 L1222.
DEFAULT_DEBUG_INFO_DAYS = 30
DEFAULT_WARNING_DAYS = 90

# Cohort definitions — keep these in sync with canonical
# CK_PipelineLog_LogLevel CHECK constraint at phase1/01_database_schema.md
# § 2 L215-216 (per Pitfall #9.l canonical re-read).
PURGED_COHORTS_DEBUG_INFO = ("DEBUG", "INFO")
PURGED_COHORTS_WARNING = ("WARNING",)
RETAINED_COHORTS = ("ERROR", "CRITICAL")


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
# Lock acquisition / release (per spec § 3.10 L1251)
# ---------------------------------------------------------------------------


def _acquire_cleanup_lock(connection) -> bool:
    """Acquire ``sp_getapplock`` on resource 'log_retention_cleanup'.

    Returns True if acquired; False if another session holds it. Uses
    ``@LockOwner='Session'`` per W-8 RCSI analysis (Transaction-scoped
    locks NOT used; W-8 explicitly forbids the autocommit-with-Transaction
    pattern). ``@LockTimeout=0`` (no wait) so contention surfaces
    immediately as exit 1 per spec error modes.

    Mirrors the pattern in ``orchestration/table_lock.py`` L97-127.
    """
    cursor = connection.cursor()
    try:
        cursor.execute(
            "DECLARE @result INT; "
            "EXEC @result = sp_getapplock "
            "  @Resource = ?, "
            "  @LockMode = 'Exclusive', "
            "  @LockOwner = 'Session', "
            "  @LockTimeout = 0; "
            "SELECT @result;",
            LOCK_RESOURCE,
        )
        row = cursor.fetchone()
        if row is None:
            return False
        result = row[0]
        # sp_getapplock return codes (per table_lock.py L113-118):
        #  0/1 = lock granted; -1 = timeout; -2 = cancelled;
        # -3 = deadlock victim; -999 = parameter error.
        return result is not None and int(result) >= 0
    finally:
        try:
            cursor.close()
        except Exception:  # noqa: BLE001
            pass


def _release_cleanup_lock(connection) -> None:
    """Release ``sp_getapplock`` on resource 'log_retention_cleanup'.

    Per W-8, Session-owned locks also release on connection close — this
    explicit release is defense-in-depth for long-lived connections.
    Errors are logged but never raised (cleanup is best-effort during
    teardown).
    """
    cursor = connection.cursor()
    try:
        cursor.execute(
            "EXEC sp_releaseapplock "
            "  @Resource = ?, "
            "  @LockOwner = 'Session';",
            LOCK_RESOURCE,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Failed to release sp_getapplock for %s", LOCK_RESOURCE)
    finally:
        try:
            cursor.close()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Cohort row-count queries (dry-run preview + post-purge verification)
# ---------------------------------------------------------------------------


def _count_eligible(
    connection,
    *,
    log_levels: tuple[str, ...],
    cutoff_dt: datetime,
    general_db: str,
) -> int:
    """SELECT COUNT(*) of rows eligible for purge per cohort + cutoff.

    Canonical columns per ``phase1/01_database_schema.md`` § 2 L202+L209
    (re-read per Pitfall #9.l): ``LogLevel NVARCHAR(10) NOT NULL`` +
    ``CreatedAt DATETIME2(3) NOT NULL DEFAULT SYSUTCDATETIME()``.

    ``cutoff_dt`` is naive-UTC per the CDC-NOW-MS + SCD2-P1-f invariant —
    pyodbc sends naive datetimes as ``DATETIME2(3)`` (no tz conversion).
    Sending an aware datetime would cause SQL Server's implicit
    ``DATETIME2 = DATETIMEOFFSET`` conversion to drift the UTC moment on
    non-UTC servers (same bug class as CDC-NOW-MS).
    """
    placeholders = ", ".join("?" for _ in log_levels)
    cursor = connection.cursor()
    try:
        cursor.execute(
            f"SELECT COUNT_BIG(*) "
            f"FROM [{general_db}].ops.PipelineLog "
            f"WHERE LogLevel IN ({placeholders}) "
            f"  AND CreatedAt < ?",
            *log_levels,
            cutoff_dt,
        )
        row = cursor.fetchone()
        if row is None or row[0] is None:
            return 0
        return int(row[0])
    finally:
        try:
            cursor.close()
        except Exception:  # noqa: BLE001
            pass


def _count_retained(
    connection,
    *,
    log_levels: tuple[str, ...],
    general_db: str,
) -> int:
    """SELECT COUNT(*) of rows retained per cohort (ERROR / CRITICAL).

    No cutoff filter — ERROR / CRITICAL are retained indefinite per
    CLAUDE.md retention policy. Operator sees the count in stdout so
    they can reconcile against the dashboard.
    """
    placeholders = ", ".join("?" for _ in log_levels)
    cursor = connection.cursor()
    try:
        cursor.execute(
            f"SELECT COUNT_BIG(*) "
            f"FROM [{general_db}].ops.PipelineLog "
            f"WHERE LogLevel IN ({placeholders})",
            *log_levels,
        )
        row = cursor.fetchone()
        if row is None or row[0] is None:
            return 0
        return int(row[0])
    finally:
        try:
            cursor.close()
        except Exception:  # noqa: BLE001
            pass


def _count_per_level(
    connection,
    *,
    log_level: str,
    cutoff_dt: datetime | None,
    general_db: str,
) -> int:
    """SELECT COUNT(*) for one LogLevel (eligible if cutoff_dt set, else total).

    Used to build the canonical per-level breakdown in stdout — the
    operator sees DEBUG vs INFO separately even though they share the
    same cutoff window.
    """
    cursor = connection.cursor()
    try:
        if cutoff_dt is None:
            cursor.execute(
                f"SELECT COUNT_BIG(*) "
                f"FROM [{general_db}].ops.PipelineLog "
                f"WHERE LogLevel = ?",
                log_level,
            )
        else:
            cursor.execute(
                f"SELECT COUNT_BIG(*) "
                f"FROM [{general_db}].ops.PipelineLog "
                f"WHERE LogLevel = ? AND CreatedAt < ?",
                log_level,
                cutoff_dt,
            )
        row = cursor.fetchone()
        if row is None or row[0] is None:
            return 0
        return int(row[0])
    finally:
        try:
            cursor.close()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Batched DELETE (per spec § 3.10 L1253 + B-2 lock-escalation gotcha)
# ---------------------------------------------------------------------------


def _delete_cohort_batched(
    connection,
    *,
    log_levels: tuple[str, ...],
    cutoff_dt: datetime,
    batch_size: int,
    general_db: str,
) -> int:
    """DELETE TOP(@batch_size) per cohort + cutoff until 0 rows affected.

    Returns total rows purged across all batches. ERROR / CRITICAL never
    appear in any DELETE WHERE clause (caller passes DEBUG/INFO or
    WARNING tuples only — defense-in-depth assertion below).

    Per spec § 3.10 L1253 "DELETE batch size capped at 50k rows per
    batch (B-2 lessons — 50k is conservative)". Loops until 0 rows
    affected so the entire cohort is drained before the next cohort
    runs.
    """
    # Defense-in-depth: ERROR / CRITICAL must NEVER appear in a DELETE
    # cohort. Per CLAUDE.md retention policy + Do NOT rule (implicit
    # under "indefinite for ERROR/CRITICAL").
    for level in log_levels:
        if level in RETAINED_COHORTS:
            raise LogRetentionCleanupError(
                f"Refused to DELETE LogLevel={level!r} — ERROR / CRITICAL "
                f"are retained indefinite per CLAUDE.md retention policy."
            )

    placeholders = ", ".join("?" for _ in log_levels)
    total_deleted = 0
    cursor = connection.cursor()
    try:
        while True:
            cursor.execute(
                f"DELETE TOP (?) "
                f"FROM [{general_db}].ops.PipelineLog "
                f"WHERE LogLevel IN ({placeholders}) "
                f"  AND CreatedAt < ?",
                batch_size,
                *log_levels,
                cutoff_dt,
            )
            affected = cursor.rowcount
            if affected is None or affected <= 0:
                break
            total_deleted += int(affected)
            logger.info(
                "Purged %d row(s) from PipelineLog cohort %s (running total: %d)",
                affected,
                "/".join(log_levels),
                total_deleted,
            )
            if affected < batch_size:
                # Last batch drained the cohort.
                break
    finally:
        try:
            cursor.close()
        except Exception:  # noqa: BLE001
            pass
    return total_deleted


# ---------------------------------------------------------------------------
# Audit-row writer — one CLI_LOG_RETENTION_CLEANUP row per invocation
# ---------------------------------------------------------------------------


def _write_audit_row(
    metadata: dict,
    *,
    status: str,
    error_message: str | None = None,
    cursor_factory: Callable | None = None,
    general_db: str = "General",
    skip: bool = False,
) -> bool:
    """INSERT one ``CLI_LOG_RETENTION_CLEANUP`` row into PipelineEventLog.

    Per D76 + spec § 3.10 L1234. ONE row per invocation (NOT one row per
    cohort — per-cohort counts surface in Metadata JSON). Best-effort:
    failures are logged but do not affect the verdict exit code (parity
    with B188 / B189 / B190 audit-row patterns).

    Returns True on success, False on failure.

    When ``cursor_factory`` is injected (test path), the live
    ``utils.connections`` resolution is skipped.

    When ``skip=True`` (test path; main()'s ``no_audit_event``), the
    function returns False immediately without writing.
    """
    if skip:
        return False
    metadata_json = json.dumps(metadata, separators=(",", ":"), default=str)
    event_detail = (
        f"log_retention_cleanup / "
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
            return False

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
                f"SELECT SCOPE_IDENTITY();",
                EVENT_TYPE,
                event_detail,
                metadata.get("started_at_dt"),
                status,
                error_message,
                metadata_json,
            )
            # SCOPE_IDENTITY() per spec § 3.10 L1290 — `audit_event_id` key value.
            try:
                row = cursor.fetchone()
                event_id_val = int(row[0]) if row and row[0] is not None else None
            except Exception:  # noqa: BLE001
                event_id_val = None
        finally:
            try:
                cursor.close()
            except Exception:  # noqa: BLE001
                pass
        return event_id_val if event_id_val is not None else True
    except Exception:  # noqa: BLE001
        logger.exception("Failed to write CLI_LOG_RETENTION_CLEANUP audit row")
        return False
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Stdout rendering
# ---------------------------------------------------------------------------


def _emit_human_summary(
    *,
    purged: dict[str, int],
    retained: dict[str, int],
    debug_info_days: int,
    warning_days: int,
    dry_run: bool,
    audit_event_written: bool,
) -> None:
    """Print the spec § 3.10 L1278-1288 stdout block."""
    verb = "eligible to purge" if dry_run else "purged"
    header = "PipelineLog retention cleanup — dry run" if dry_run else "PipelineLog retention cleanup — apply"
    print(header)
    print(
        f"  DEBUG  rows older than {debug_info_days} days : "
        f"{purged.get('DEBUG', 0):,} ({verb})"
    )
    print(
        f"  INFO   rows older than {debug_info_days} days : "
        f"{purged.get('INFO', 0):,} ({verb})"
    )
    print(
        f"  WARNING rows older than {warning_days} days: "
        f"{purged.get('WARNING', 0):,} ({verb})"
    )
    print(
        f"  ERROR  rows                    : "
        f"{retained.get('ERROR', 0):,} (retained — indefinite per policy)"
    )
    print(
        f"  CRITICAL rows                  : "
        f"{retained.get('CRITICAL', 0):,} (retained — indefinite per policy)"
    )
    total = sum(purged.values())
    if dry_run:
        print(f"Would purge {total:,} rows. Re-run with --apply to commit.")
    else:
        suffix = f" Audit event written." if audit_event_written else ""
        print(f"Cleanup complete. Purged {total:,} rows.{suffix}")


def _emit_json(metadata: dict) -> None:
    """Emit the canonical JSON payload per spec § 3.10 L1290."""
    print(json.dumps(metadata, indent=2, sort_keys=True, default=str))


# ---------------------------------------------------------------------------
# General DB connection factory (test-friendly resolution)
# ---------------------------------------------------------------------------


def _resolve_default_general_cursor_factory() -> Callable:
    """Return a callable that opens a connection to the General DB.

    Resolves at CALL TIME so tests patching ``sys.modules['pyodbc']``
    after tool import are honored. Production path uses
    ``utils.connections.get_general_connection()``; if that raises (no
    DSN / no driver), we fall back to ``sys.modules['pyodbc'].connect``.

    Raises :class:`LogRetentionConfigError` (mapped to exit 2 by main())
    if neither path succeeds.
    """

    def _open():
        try:
            from utils.connections import get_general_connection  # type: ignore

            return get_general_connection()
        except Exception:  # noqa: BLE001
            pass
        pyodbc_mod = sys.modules.get("pyodbc")
        if pyodbc_mod is None:
            try:
                import pyodbc as pyodbc_mod  # type: ignore  # noqa: F401
            except Exception as exc:  # noqa: BLE001
                raise LogRetentionConfigError(
                    f"pyodbc / utils.connections both unavailable: {exc}"
                ) from exc
        return pyodbc_mod.connect("DRIVER={ODBC Driver 18 for SQL Server};")

    return _open


# ---------------------------------------------------------------------------
# Top-level main() — programmatic entry point
# ---------------------------------------------------------------------------


def main(
    *,
    actor: str,
    apply: bool = False,
    dry_run: bool | None = None,
    debug_info_days: int = DEFAULT_DEBUG_INFO_DAYS,
    warning_days: int = DEFAULT_WARNING_DAYS,
    batch_size: int = DEFAULT_BATCH_SIZE,
    json_output: bool = False,
    verbose: bool = False,
    quiet: bool = False,
    justification: str | None = None,
    no_audit_event: bool = False,
    # ---- Injection hooks (test path) ----
    general_cursor_factory: Callable | None = None,
    audit_cursor_factory: Callable | None = None,
    general_db: str | None = None,
) -> dict:
    """Programmatic entry — performs the cleanup per CLAUDE.md retention policy.

    Returns a dict matching the D76 audit-row Metadata shape (see module
    docstring for the canonical schema). Exit-code derivation per D74 +
    spec § 3.10:

    * 0: cleanup completed (or dry-run preview); zero contention
    * 1: lock contention OR partial-batch error; operator can re-run
    * 2: fatal — config / connection / unexpected

    Parameters
    ----------
    actor:
        Operator identity (per D75 + D76). REQUIRED.
    apply:
        When True, DELETE statements run; when False (default per spec
        § 1.2 dry-run-default for side-effecting tools), only SELECT
        COUNT statements run.
    debug_info_days / warning_days:
        Per CLAUDE.md retention policy (30 / 90 default).
    batch_size:
        Per-batch DELETE row cap (50000 default per spec § 3.10 L1274;
        B-2 lock-escalation conservative value).
    justification:
        Operator justification recorded in audit-row Metadata per D75.
    general_cursor_factory / audit_cursor_factory:
        Test-injection hooks. Defaults resolve to live infrastructure.
    general_db:
        Override the canonical General DB name (defaults to
        ``utils.configuration.GENERAL_DB``, fallback ``'General'``).
    """
    started_at = datetime.now(timezone.utc).replace(tzinfo=None)

    # B88 dry-run/apply mutex bridge: tests pass `dry_run` as a kwarg paralleling
    # `apply`. Canonical semantic: --apply makes it real; --dry-run forces preview.
    # If both True → mutex violation (exit 2). If `dry_run=True` → override apply=False.
    if dry_run is True and apply is True:
        raise SystemExit(2)
    if dry_run is True:
        apply = False

    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    elif quiet:
        logging.getLogger().setLevel(logging.ERROR)

    # Validate numeric args defensively (argparse handles the canonical
    # case, but programmatic callers may pass through invalid values).
    if debug_info_days <= 0:
        raise SystemExit(
            f"--debug-info-days must be positive (got {debug_info_days})."
        )
    if warning_days <= 0:
        raise SystemExit(
            f"--warning-days must be positive (got {warning_days})."
        )
    if batch_size <= 0:
        raise SystemExit(
            f"--batch-size must be positive (got {batch_size})."
        )

    # Resolve general_db tag (matches B188 / B189 / B190 pattern).
    # B-218 fix: per spec section 3.10 L1295 + D74, config absence is FATAL --
    # do NOT fall back to a guess. Cannot DELETE rows on a config guess.
    config_import_error: Exception | None = None
    if general_db is None:
        try:
            import utils.configuration as config  # type: ignore

            general_db = getattr(config, "GENERAL_DB", "General")
        except ImportError as exc:
            # Capture; surface as FATAL after result-dict init below.
            config_import_error = exc
            general_db = "General"  # provisional for audit-row write only

    # ---- Compute cutoffs (naive-UTC per CDC-NOW-MS / SCD2-P1-f invariant) ----
    cutoff_debug_info = (started_at - timedelta(days=debug_info_days)).replace(
        microsecond=(started_at - timedelta(days=debug_info_days)).microsecond // 1000 * 1000
    )
    cutoff_warning = (started_at - timedelta(days=warning_days)).replace(
        microsecond=(started_at - timedelta(days=warning_days)).microsecond // 1000 * 1000
    )

    # ---- Pre-populate result with input echoes for early-exit paths ----
    result: dict[str, Any] = {
        "event_kind": "cleanup",
        "actor": actor,
        "justification": justification,
        "dry_run": (not apply),
        "debug_info_days": debug_info_days,
        "warning_days": warning_days,
        "batch_size": batch_size,
        "purged": {"DEBUG": 0, "INFO": 0, "WARNING": 0},
        "retained": {"ERROR": 0, "CRITICAL": 0},
        "exit_code": EXIT_SUCCESS,
        "lock_acquired": False,
        "started_at": started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "started_at_dt": started_at,
        "completed_at": None,
        "errors": [],
    }

    # B-218 fix: if config import failed earlier, surface as FATAL per spec
    # section 3.10 L1295. Result dict is now initialized; write audit row + return.
    if config_import_error is not None:
        result["exit_code"] = EXIT_FATAL
        result["error_type"] = "LogRetentionConfigError"
        result["error_message"] = f"utils.configuration unavailable: {config_import_error}"
        result["errors"].append(f"config import failed: {config_import_error}")
        result["completed_at"] = datetime.now(
            timezone.utc
        ).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%SZ")
        if not quiet:
            print(
                f"FATAL: utils.configuration unavailable: {config_import_error}",
                file=sys.stderr,
            )
        _write_audit_row(
            result,
            status="FAILED",
            error_message=str(config_import_error)[:4000],
            cursor_factory=audit_cursor_factory,
            general_db=general_db,
            skip=no_audit_event,
        )
        return result

    # ---- Resolve connection factory ----
    if general_cursor_factory is None:
        try:
            general_cursor_factory = _resolve_default_general_cursor_factory()
        except LogRetentionConfigError as exc:
            result["exit_code"] = EXIT_FATAL
            result["error_type"] = "LogRetentionConfigError"
            result["error_message"] = str(exc)
            result["errors"].append(f"LogRetentionConfigError: {exc}")
            result["completed_at"] = datetime.now(
                timezone.utc
            ).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%SZ")
            if not quiet:
                print(
                    f"FATAL: config unavailable for log_retention_cleanup: {exc}",
                    file=sys.stderr,
                )
            _write_audit_row(
                result,
                status="FAILED",
                error_message=str(exc)[:4000],
                cursor_factory=audit_cursor_factory,
                general_db=general_db,
                skip=no_audit_event,
            )
            return result

    # ---- Open connection + acquire lock + run the cleanup ----
    conn = None
    audit_event_written = False
    try:
        try:
            conn = general_cursor_factory()
        except Exception as exc:  # noqa: BLE001
            # Connection failure → exit 1 (retryable) per spec § 3.10 L1246.
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
            result["completed_at"] = datetime.now(
                timezone.utc
            ).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%SZ")
            _write_audit_row(
                result,
                status="FAILED",
                error_message=traceback.format_exc()[:4000],
                cursor_factory=audit_cursor_factory,
                general_db=general_db,
                skip=no_audit_event,
            )
            return result

        # autocommit=True is the canonical pattern from
        # utils.connections.get_connection() L221 + W-8 RCSI analysis.
        try:
            conn.autocommit = True
        except Exception:  # noqa: BLE001
            pass

        # ---- Acquire the cleanup lock ----
        try:
            lock_acquired = _acquire_cleanup_lock(conn)
        except Exception as exc:  # noqa: BLE001
            result["exit_code"] = EXIT_WARNING
            result["error_type"] = type(exc).__name__
            result["error_message"] = f"sp_getapplock error: {exc}"
            result["errors"].append(f"sp_getapplock error: {exc}")
            logger.warning("sp_getapplock invocation failed: %s", exc)
            result["completed_at"] = datetime.now(
                timezone.utc
            ).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%SZ")
            _write_audit_row(
                result,
                status="FAILED",
                error_message=traceback.format_exc()[:4000],
                cursor_factory=audit_cursor_factory,
                general_db=general_db,
                skip=no_audit_event,
            )
            return result

        result["lock_acquired"] = bool(lock_acquired)
        if not lock_acquired:
            # Another cleanup is in flight — exit 1 per spec § 3.10
            # L1247 "Lock timeout ... → exit 1 with retry-after-N-minutes
            # recommendation".
            result["exit_code"] = EXIT_WARNING
            result["error_type"] = "LogRetentionLockContention"
            msg = (
                f"sp_getapplock contention on resource {LOCK_RESOURCE!r}; "
                f"another cleanup is in flight. Re-run after it completes "
                f"(typically within 10 minutes for daily cleanup cadence)."
            )
            result["error_message"] = msg
            result["errors"].append(msg)
            logger.warning(msg)
            if not quiet:
                print(f"WARNING: {msg}", file=sys.stderr)
            result["completed_at"] = datetime.now(
                timezone.utc
            ).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%SZ")
            audit_event_written = _write_audit_row(
                result,
                status="FAILED",
                error_message=msg,
                cursor_factory=audit_cursor_factory,
                general_db=general_db,
                skip=no_audit_event,
            )
            result["audit_event_written"] = audit_event_written
            # audit_event_id per spec § 3.10 L1290: int when SCOPE_IDENTITY captured.
            result["audit_event_id"] = (
                audit_event_written
                if isinstance(audit_event_written, int)
                and not isinstance(audit_event_written, bool)
                else None
            )
            return result

        # ---- Lock acquired — proceed with COUNT / DELETE per cohort ----
        try:
            # DEBUG / INFO eligible counts (per-level breakdown for stdout)
            debug_eligible = _count_per_level(
                conn,
                log_level="DEBUG",
                cutoff_dt=cutoff_debug_info,
                general_db=general_db,
            )
            info_eligible = _count_per_level(
                conn,
                log_level="INFO",
                cutoff_dt=cutoff_debug_info,
                general_db=general_db,
            )
            warning_eligible = _count_per_level(
                conn,
                log_level="WARNING",
                cutoff_dt=cutoff_warning,
                general_db=general_db,
            )
            # ERROR / CRITICAL retained counts (no cutoff)
            error_retained = _count_per_level(
                conn,
                log_level="ERROR",
                cutoff_dt=None,
                general_db=general_db,
            )
            critical_retained = _count_per_level(
                conn,
                log_level="CRITICAL",
                cutoff_dt=None,
                general_db=general_db,
            )

            result["retained"] = {
                "ERROR": error_retained,
                "CRITICAL": critical_retained,
            }

            if not apply:
                # Dry-run: report eligible counts and exit 0.
                result["purged"] = {
                    "DEBUG": debug_eligible,
                    "INFO": info_eligible,
                    "WARNING": warning_eligible,
                }
                result["exit_code"] = EXIT_SUCCESS
            else:
                # Apply: DELETE per cohort.
                # DEBUG + INFO share the same cutoff and can be deleted
                # in a single per-cohort batch (LogLevel IN ('DEBUG',
                # 'INFO')) — the per-level breakdown for the audit row
                # comes from the pre-count values which match the actual
                # deletions barring concurrent INSERTs (acceptable since
                # the lock prevents concurrent cleanups; the pipeline
                # itself may INSERT during cleanup but its INSERTs have
                # CreatedAt = now > cutoff, so they're not eligible).
                deleted_debug_info = _delete_cohort_batched(
                    conn,
                    log_levels=PURGED_COHORTS_DEBUG_INFO,
                    cutoff_dt=cutoff_debug_info,
                    batch_size=batch_size,
                    general_db=general_db,
                )
                deleted_warning = _delete_cohort_batched(
                    conn,
                    log_levels=PURGED_COHORTS_WARNING,
                    cutoff_dt=cutoff_warning,
                    batch_size=batch_size,
                    general_db=general_db,
                )
                # The per-level split of deleted_debug_info follows the
                # pre-count ratio — record both pre-count + total deleted
                # in the audit row Metadata so the operator can reconcile.
                result["purged"] = {
                    "DEBUG": debug_eligible,
                    "INFO": info_eligible,
                    "WARNING": deleted_warning,
                }
                result["purged_debug_info_total"] = deleted_debug_info
                result["exit_code"] = EXIT_SUCCESS

        except LogRetentionCleanupError as exc:
            # Defense-in-depth assertion failure (ERROR/CRITICAL in
            # cohort tuples). Should never reach here in normal use;
            # fatal-class if it does.
            result["exit_code"] = EXIT_FATAL
            result["error_type"] = "LogRetentionCleanupError"
            result["error_message"] = str(exc)[:4000]
            result["errors"].append(f"LogRetentionCleanupError: {exc}")
            logger.error("Cleanup refused: %s", exc)
            if not quiet:
                print(f"FATAL: {exc}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001
            # Partial-batch error → exit 1 (retryable) per spec § 3.10
            # L1294. Idempotency invariant: next run picks up where this
            # one stopped because the cutoff is re-computed against the
            # batch's started_at and the surviving rows are still <
            # cutoff.
            result["exit_code"] = EXIT_WARNING
            result["error_type"] = type(exc).__name__
            result["error_message"] = str(exc)[:4000]
            result["errors"].append(f"{type(exc).__name__}: {exc}")
            logger.exception("Partial-batch error during cleanup")
            if not quiet:
                print(
                    f"WARNING: partial-batch error (re-run to continue): {exc}",
                    file=sys.stderr,
                )

    finally:
        if conn is not None:
            if result.get("lock_acquired"):
                try:
                    _release_cleanup_lock(conn)
                except Exception:  # noqa: BLE001
                    logger.exception("Failed to release sp_getapplock")
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    result["completed_at"] = datetime.now(
        timezone.utc
    ).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ---- Render stdout ----
    if json_output:
        # Pop the non-serializable datetime helper before emitting JSON.
        emit_dict = {k: v for k, v in result.items() if k != "started_at_dt"}
        _emit_json(emit_dict)
    elif not quiet:
        _emit_human_summary(
            purged=result["purged"],
            retained=result["retained"],
            debug_info_days=debug_info_days,
            warning_days=warning_days,
            dry_run=result["dry_run"],
            audit_event_written=audit_event_written,
        )

    # ---- Invocation-level audit row (D76 — ONE per invocation) ----
    status = "SUCCESS" if result["exit_code"] in (EXIT_SUCCESS, EXIT_WARNING) else "FAILED"
    audit_event_written = _write_audit_row(
        result,
        status=status,
        error_message=result.get("error_message"),
        cursor_factory=audit_cursor_factory,
        general_db=general_db,
        skip=no_audit_event,
    )
    result["audit_event_written"] = audit_event_written
    # audit_event_id per spec § 3.10 L1290: int when SCOPE_IDENTITY captured;
    # None when write failed OR skipped. Distinguishes from bool by JSON shape.
    result["audit_event_id"] = (
        audit_event_written if isinstance(audit_event_written, int)
        and not isinstance(audit_event_written, bool)
        else None
    )

    return result


# ---------------------------------------------------------------------------
# CLI argv entry point
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    """Alias for :func:`_build_parser` — Tier 0 scaffold contract."""
    return _build_parser()


def _build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser per spec § 3.10 + § 1.4 canonical args."""
    parser = argparse.ArgumentParser(
        description=(
            "Purge old General.ops.PipelineLog rows per CLAUDE.md retention "
            "policy (30 days DEBUG/INFO; 90 days WARNING; ERROR/CRITICAL "
            "retained indefinite). Emits one CLI_LOG_RETENTION_CLEANUP "
            "audit row per invocation."
        ),
    )

    # ---- Tool-specific args (per spec § 3.10 L1268-1274) ----
    parser.add_argument(
        "--debug-info-days",
        type=int,
        default=DEFAULT_DEBUG_INFO_DAYS,
        help=(
            f"Days to retain DEBUG + INFO rows "
            f"(default: {DEFAULT_DEBUG_INFO_DAYS} per CLAUDE.md policy)."
        ),
    )
    parser.add_argument(
        "--warning-days",
        type=int,
        default=DEFAULT_WARNING_DAYS,
        help=(
            f"Days to retain WARNING rows "
            f"(default: {DEFAULT_WARNING_DAYS} per CLAUDE.md policy). "
            f"ERROR / CRITICAL are NEVER purged by this tool."
        ),
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=(
            f"Per-batch DELETE row cap (default: {DEFAULT_BATCH_SIZE}; "
            f"mirrors config.SCD2_UPDATE_BATCH_SIZE per Round 6 § 7.8 "
            f"+ B104 closure 2026-05-14 + B-2 lock-escalation threshold). "
            f"Raise only if you understand the B-2 5000-lock ceiling; "
            f"lower to mitigate lock contention under load."
        ),
    )

    # ---- D75 canonical args (per spec § 1.4) ----
    # --apply / --dry-run are mutually exclusive per B88 (apply opt-in,
    # dry-run default). spec § 1.2 — side-effecting tools default to dry-run.
    apply_group = parser.add_mutually_exclusive_group()
    apply_group.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Apply DELETE statements. Default is dry-run (preview eligible "
            "counts only)."
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
            "pipeline / pipeline-lead. Auto-detected via TTY / AUTOMIC_RUN_ID "
            "env when omitted."
        ),
    )
    parser.add_argument(
        "--justification",
        default=None,
        help=(
            "Operator justification (per D75); written to audit row Metadata."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Emit canonical JSON output to stdout instead of human summary.",
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


def _validate_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    """Enforce numeric positivity + --apply/--dry-run mutex.

    argparse's mutually_exclusive_group already enforces the mutex; this
    function adds numeric-positivity checks that argparse can't enforce
    declaratively.
    """
    if args.debug_info_days <= 0:
        parser.error(
            f"--debug-info-days must be positive (got {args.debug_info_days})."
        )
    if args.warning_days <= 0:
        parser.error(
            f"--warning-days must be positive (got {args.warning_days})."
        )
    if args.batch_size <= 0:
        parser.error(
            f"--batch-size must be positive (got {args.batch_size})."
        )


def cli_main() -> int:
    """Argv entry point — argparse + main() + return exit code per D74.

    Exit codes (always one of 0 / 1 / 2 per D74 + spec § 3.10 L1292-1295):
        - 0: cleanup completed (or dry-run preview produced)
        - 1: lock contention / partial-batch error
        - 2: fatal (config / connection / unexpected)
    """
    parser = _build_parser()
    args = parser.parse_args()
    _validate_args(args, parser)

    actor = args.actor or _detect_actor()

    try:
        result = main(
            actor=actor,
            apply=args.apply,
            debug_info_days=args.debug_info_days,
            warning_days=args.warning_days,
            batch_size=args.batch_size,
            json_output=args.json_output,
            verbose=args.verbose,
            quiet=args.quiet,
            justification=args.justification,
        )
    except SystemExit:
        # Argparse-style validation error already printed by parser.error.
        return EXIT_FATAL
    except KeyboardInterrupt:
        logger.warning("Interrupted by operator")
        return EXIT_WARNING
    except Exception:  # noqa: BLE001
        tb = traceback.format_exc()
        print(
            f"FATAL: log_retention_cleanup unexpected exception:\n{tb[:1000]}",
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
