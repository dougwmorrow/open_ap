"""Round 4 § 3.8 — ``tools/enforce_retention.py``.

Per **Round 4 § 3.8** at ``docs/migration/phase1/04_tools.md`` L1037-1125
(canonical spec) + **Round 1 SP-10 ``EnforceRetention``** canonical DDL
at ``docs/migration/phase1/01_database_schema.md`` L1953-1985.

Invoke SP-10 ``General.ops.EnforceRetention(@DryRun BIT = 1)`` per D30 —
sweeps ``General.ops.PiiVault`` rows where ``RetentionExpiresAt <
SYSUTCDATETIME() AND LegalHold = 0 AND Status = 'active'`` (per SP-10
body L1965-1972 / L1976-1983) and flips qualifying rows to
``Status='purged_for_retention'``. Driven by ``JOB_RETENTION_MONTHLY``
per Round 2 § 5.1 (monthly Automic cadence).

What this tool does
-------------------

1. Acquire ``sp_getapplock`` on resource
   ``'job_RETENTION_MONTHLY_<month-start>'`` (`@LockOwner='Session'`)
   per spec § 3.8 L1072 + Round 2 § 5.1 L1047 + § 5.3.6 L1181 canonical
   idiom (same as ``orchestration/table_lock.py`` per W-8).
2. Invoke SP-10 with ``@DryRun`` matching ``--apply`` flag (default
   ``@DryRun=1`` read-only per spec § 1.2 dry-run-default).
3. Capture SP-10's returned scalar:
   - ``@DryRun=1`` returns ``WouldBeFlipped`` count (per L1968-1972)
   - ``@DryRun=0`` returns ``Flipped`` count via ``@Affected`` (L1984-1986)
4. Write ONE ``CLI_ENFORCE_RETENTION`` audit row to
   ``General.ops.PipelineEventLog`` per D76 — ``Metadata`` JSON includes
   per-category counts (vault / provenance / orphanedtokenlog), dry_run,
   actor, justification, event_kind='retention_enforcement', exit_code.
5. Render stdout per spec § 3.8 L1098-1109 (human or JSON via ``--json``).
6. Exit 0 / 1 / 2 per D74 + spec § 3.8 L1113-1116.

CLI contract
------------

::

    # Automic-invoked monthly retention sweep (apply mode)
    python3 tools/enforce_retention.py --actor automic --apply

    # Operator dry-run (default behavior)
    python3 tools/enforce_retention.py

    # Apply with verbose progress + justification
    python3 tools/enforce_retention.py --apply -v \\
        --actor pipeline-lead \\
        --justification "month-end retention sweep per RB-11 review"

Exit codes (per D74 + spec § 3.8 L1113-1116)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* **0** — retention enforcement completed (or dry-run preview); includes
  zero-rows-qualified (legal-hold silently filtered + no expired-
  retention rows = operationally normal)
* **1** — vault connection drop OR retryable error during SP-10 invocation
  OR sp_getapplock lock-contention (operator can re-run; SP-10 is
  single-statement transactional UPDATE — partial-row-state cannot occur)
* **2** — fatal — :class:`VaultConfigError` (env keys missing/unreachable
  at startup per Round 3 § 2.3) or unexpected exception. **NOT a legal-
  hold-conflict exit code** — SP-10 silently filters ``LegalHold = 1``
  rows per L1971 / L1982; no exception raised on legal-hold encounter

Audit row (per D76 + spec § 3.8 L1054)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* ``General.ops.PipelineEventLog.EventType = 'CLI_ENFORCE_RETENTION'``
  (one of the 11 R4 canonical CLI_* family values per CLAUDE.md)
* ONE row per INVOCATION (spec § 3.8 produces — per-category counts
  surface in Metadata JSON, NOT separate event rows)
* ``Status in {SUCCESS, FAILED}`` (SUCCESS for exit 0/1 dry-run + apply
  + lock-contention; FAILED for exit 2 fatal)
* ``Metadata`` JSON shape::

    {
        "event_kind": "retention_enforcement",
        "actor": "<operator>",
        "justification": "<text or null>",
        "dry_run": <bool>,
        "counts": {"vault": N, "provenance": M, "orphanedtokenlog": Q},
        "exit_code": <int>,
        "lock_acquired": <bool>,
        "lock_resource": "job_RETENTION_MONTHLY_<YYYY-MM-01>",
        "started_at": "<ISO-8601 naive-UTC>",
        "completed_at": "<ISO-8601 naive-UTC>"
    }

Classification per ``udm-execution-classifier`` skill
-----------------------------------------------------

* **Trigger**: PRIMARY: Scheduled (Automic ``JOB_RETENTION_MONTHLY``
  per Round 2 § 5.1 — frozen-11 inventory). SECONDARY: Manual operator
  CLI for ad-hoc dry-run preview / pre-CCPA-deletion review.
* **Frequency**: PRIMARY Recurring monthly; SECONDARY one-time ad-hoc.
* **Idempotency**: YES per spec § 3.8 L1061-1064 — SP-10's @DryRun=1
  is read-only; @DryRun=0 is row-level idempotent (Status flip
  ``purged_for_retention`` -> ``purged_for_retention`` is a no-op via
  the WHERE clause filtering ``Status = 'active'``). Multi-invocation
  in the same month produces multiple audit rows (intentional per D26).
* **Concurrency**: ``sp_getapplock`` on
  ``('job_RETENTION_MONTHLY_<month-start>',)`` per Round 2 § 5.3.6
  L1181 ensures one retention sweep at a time. ``--workers`` NOT
  supported (single SP execution; serial is correct).
* **Audit-row family**: ``CLI_ENFORCE_RETENTION`` per D76 + CLAUDE.md
  CLI_* family registry.
* **Routing**: PRIMARY tracker ``phase1/02_configuration.md`` § 5.1
  Automic inventory (frozen-11 includes ``JOB_RETENTION_MONTHLY``).
  SECONDARY tracker ``ONE_OFF_SCRIPTS.md`` operator tools table.

D-numbers consumed
------------------

D6 (in-house tokenization vault),
D15 (idempotency invariant — re-runs produce zero net writes when no
new rows have expired),
D26 (append-only audit trail — the retention purge is the deliberate
exception to D26 per D30 retention policy),
D30 (7-year retention with legal-hold override — the canonical decision
this tool implements),
D67 (Tier 0 smoke discipline),
D74-D77 (CLI exit-code contract + argument naming + audit-row contract +
Tier 0 6-canonical-assertion scaffold),
D92 (forward-only additive — exception module extension preserves
backward compatibility).

Canonical references cited (per Pitfall #9.l producer self-check)
-----------------------------------------------------------------

* SP-10 DDL: ``phase1/01_database_schema.md`` L1953-1985 (re-read at
  producer Gate 1 self-check per HANDOFF §8 Pitfall #9.l).
  Real parameters: ``@DryRun BIT = 1`` ONLY (L1957). NO ``@RetentionDate``;
  NO ``@ActorName``; NO ``@CategoryFilter`` (B93 / B94 proposed but not
  yet schema-locked — invented-parameter drift is Pitfall #9.b, caught
  + corrected at spec first-pass per L1041).
  SP body: SELECT branch L1966-1972 returns ``WouldBeFlipped`` column;
  UPDATE branch L1974-1983 returns ``Flipped`` column (== ``@Affected``).
* PiiVault DDL: ``phase1/01_database_schema.md`` § 16 L849-923 (re-read
  at producer Gate 1 self-check per Pitfall #9.l).
  Real columns referenced by SP-10 body (L1969-1972 + L1976-1983):
  ``Status NVARCHAR(20) NOT NULL DEFAULT 'active'`` (L875),
  ``StatusReason NVARCHAR(MAX) NULL`` (L876),
  ``StatusChangedAt DATETIME2(3) NULL`` (L877),
  ``StatusChangedBy NVARCHAR(128) NULL`` (L878),
  ``LegalHold BIT NOT NULL DEFAULT 0`` (L879),
  ``RetentionExpiresAt DATETIME2(3) NULL`` (L882).
  CHECK constraint ``CK_PiiVault_Status`` (L887-888) restricts Status to
  ``('active', 'deleted_per_request', 'purged_for_retention',
  'legal_hold_only')`` — SP-10 flips to ``'purged_for_retention'``.
* CLI conventions: ``phase1/04_tools.md`` § 1.4 (canonical args) +
  § 1.7 (invocation-pattern heuristic — AUTOMIC_RUN_ID env + isatty) +
  § 1.8 (exit-code mapping) + § 1.9 (boilerplate template).
* Round 2 § 5.3.6 L1181 ``sp_getapplock`` Resource-string format
  ``job_<JOB_NAME>_<cycle_date>`` — for monthly retention, ``<cycle_date>``
  is the canonical YYYY-MM-01 month-start date per spec § 3.8 L1072.

See also
--------

* ``data_load/_exceptions.py`` — ``VaultUnavailable`` /
  ``VaultConfigError`` / ``VaultError`` (per B215 canonical exception
  module pattern; per spec § 3.8 L1067-1068 canonical names).
* ``orchestration/table_lock.py`` — ``sp_getapplock`` Session-owned
  pattern (`@LockOwner='Session'` per W-8 RCSI analysis).
* ``tools/log_retention_cleanup.py`` — sibling Round 4 § 3.10 tool;
  this tool follows the same author pattern (Tier 0-friendly structure).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import traceback
from datetime import datetime, timezone
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
        VaultConfigError,
        VaultError,
        VaultUnavailable,
    )
except (ImportError, ModuleNotFoundError):
    # Defensive fallback for environments where ``data_load`` is mocked
    # as MagicMock — re-import the file directly from the filesystem.
    import importlib.util as _importlib_util  # noqa: E402

    _exc_path = Path(__file__).resolve().parent.parent / "data_load" / "_exceptions.py"
    _spec = _importlib_util.spec_from_file_location(
        "data_load._exceptions_enforce_retention", _exc_path
    )
    _exc_mod = _importlib_util.module_from_spec(_spec)
    _spec.loader.exec_module(_exc_mod)
    VaultUnavailable = _exc_mod.VaultUnavailable
    VaultConfigError = _exc_mod.VaultConfigError
    VaultError = _exc_mod.VaultError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exit-code constants (per D74 + spec § 3.8 L1113-1116)
# ---------------------------------------------------------------------------

EXIT_SUCCESS = 0
EXIT_WARNING = 1
EXIT_FATAL = 2

# D76 EventType registered in CLAUDE.md CLI_* family registry (one of the
# 11 R4 canonical values).
EVENT_TYPE = "CLI_ENFORCE_RETENTION"

# Round 2 § 5.3.6 L1181 Resource-string format ``job_<JOB_NAME>_<cycle_date>``
# — for monthly retention, ``<cycle_date>`` is YYYY-MM-01 per spec § 3.8 L1072.
LOCK_RESOURCE_PREFIX = "job_RETENTION_MONTHLY_"

# SP-10 canonical signature per phase1/01_database_schema.md L1957:
# CREATE PROCEDURE General.ops.EnforceRetention @DryRun BIT = 1
SP_OBJECT_NAME = "ops.EnforceRetention"


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
# Lock-resource name (per spec § 3.8 L1072 + Round 2 § 5.3.6 L1181)
# ---------------------------------------------------------------------------


def _month_start_for(now_dt: datetime) -> str:
    """Return YYYY-MM-01 string for the month containing ``now_dt``.

    Per spec § 3.8 L1072 — the ``<cycle_date>`` component of the
    sp_getapplock resource name. Monthly retention sweeps share a
    resource string within the same calendar month so a re-invocation
    inside the same month contends on the same lock.
    """
    return now_dt.strftime("%Y-%m-01")


def _build_lock_resource(now_dt: datetime) -> str:
    """Build the canonical Resource string per spec § 3.8 L1072."""
    return f"{LOCK_RESOURCE_PREFIX}{_month_start_for(now_dt)}"


# ---------------------------------------------------------------------------
# Lock acquisition / release (per spec § 3.8 L1072 + W-8 Session-owned)
# ---------------------------------------------------------------------------


def _acquire_applock(connection, *, resource: str) -> bool:
    """Acquire ``sp_getapplock`` on the monthly retention resource.

    Returns True if acquired; False if another session holds it. Uses
    ``@LockOwner='Session'`` per W-8 RCSI analysis. Spec § 3.8 L1072
    canonical timeout is ``@LockTimeout = 5000`` (5s wait — different
    from log_retention_cleanup's 0/no-wait). The longer wait accommodates
    Automic's monthly cadence where a near-simultaneous operator dry-run
    isn't unusual.

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
            "  @LockTimeout = 5000; "
            "SELECT @result;",
            resource,
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


def _release_applock(connection, *, resource: str) -> None:
    """Release ``sp_getapplock`` on the retention resource.

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
            resource,
        )
    except Exception:  # noqa: BLE001
        logger.exception("Failed to release sp_getapplock for %s", resource)
    finally:
        try:
            cursor.close()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# SP-10 invocation — canonical signature ``EnforceRetention(@DryRun BIT)``
# ---------------------------------------------------------------------------


def _invoke_sp10(connection, *, dry_run: bool, general_db: str) -> int:
    """Invoke ``General.ops.EnforceRetention(@DryRun = ?)`` and return count.

    Per SP-10 canonical body at ``phase1/01_database_schema.md``
    L1957-1985 (re-read per Pitfall #9.l):

    * ``@DryRun=1`` (SELECT branch L1966-1972) — returns one row with
      column ``WouldBeFlipped`` (count of rows that match the WHERE
      clause: ``RetentionExpiresAt < SYSUTCDATETIME() AND LegalHold = 0
      AND Status = 'active'``).
    * ``@DryRun=0`` (UPDATE branch L1974-1986) — runs the UPDATE then
      returns one row with column ``Flipped`` (== ``@Affected`` =
      ``@@ROWCOUNT`` from the UPDATE).

    Both branches return a single integer scalar via SELECT. We use
    ``cursor.fetchone()`` to grab the count. The SP is invoked via
    ``EXEC`` with a single positional parameter (the @DryRun BIT — 0 or 1).

    Parameters
    ----------
    connection:
        Open pyodbc connection to General DB.
    dry_run:
        When True, sends ``@DryRun=1`` (read-only); when False, sends
        ``@DryRun=0`` (apply UPDATE).
    general_db:
        General DB name for the EXEC target (default ``'General'``).

    Returns
    -------
    int
        The count of rows that matched (dry-run) OR were flipped (apply).

    Raises
    ------
    VaultUnavailable
        On connection drop or transient SQL error (mapped to exit 1).
    VaultConfigError
        On config / permission / SP-not-found errors (mapped to exit 2).
    """
    cursor = connection.cursor()
    try:
        # NOTE: @DryRun is BIT — SQL Server accepts integer 0/1. Sending
        # as int (not bool) matches pyodbc's BIT marshalling convention.
        dry_run_bit = 1 if dry_run else 0
        cursor.execute(
            f"EXEC [{general_db}].{SP_OBJECT_NAME} @DryRun = ?;",
            dry_run_bit,
        )
        row = cursor.fetchone()
        if row is None or row[0] is None:
            # SP returned nothing — treat as zero rows. SP-10 ALWAYS
            # returns a SELECT (either branch), so this is defensive.
            return 0
        return int(row[0])
    finally:
        try:
            cursor.close()
        except Exception:  # noqa: BLE001
            pass


def _read_provenance_count(
    connection,
    *,
    dry_run: bool,
    general_db: str,
) -> int:
    """Reflect PiiTokenProvenance row-count that follows the retention sweep.

    Per spec § 3.8 stdout L1104 ``PiiTokenProvenance rows reflecting``.
    Provenance follows token Status — when a vault row flips to
    ``purged_for_retention``, downstream provenance rows are implicitly
    affected via the cascade narrative described in spec L1046
    "PiiTokenProvenance cascade (provenance follows token Status)".

    The actual cascade is NOT inside SP-10's body (re-read per Pitfall
    #9.l — SP-10 only touches ``PiiVault``); the reflection count surfaces
    for operator visibility on stdout. We compute it as the count of
    provenance rows where the parent vault row would purge / has purged.

    Best-effort: failures log a warning but do not affect the exit code.
    Returns 0 when the count can't be retrieved (e.g. provenance table
    not yet deployed in dev / test environments).
    """
    cursor = connection.cursor()
    try:
        if dry_run:
            # Count provenance rows whose parent vault row is eligible for
            # purge in the same predicate as SP-10 body L1969-1972.
            sql = (
                f"SELECT COUNT_BIG(*) "
                f"FROM [{general_db}].ops.PiiTokenProvenance p "
                f"WHERE EXISTS ( "
                f"  SELECT 1 FROM [{general_db}].ops.PiiVault v "
                f"  WHERE v.Token = p.Token "
                f"    AND v.RetentionExpiresAt < SYSUTCDATETIME() "
                f"    AND v.LegalHold = 0 "
                f"    AND v.Status = 'active' "
                f");"
            )
        else:
            # After apply: provenance rows whose parent vault row was
            # just purged (Status='purged_for_retention' + StatusChangedBy
            # = 'retention_job' per SP-10 body L1980).
            sql = (
                f"SELECT COUNT_BIG(*) "
                f"FROM [{general_db}].ops.PiiTokenProvenance p "
                f"WHERE EXISTS ( "
                f"  SELECT 1 FROM [{general_db}].ops.PiiVault v "
                f"  WHERE v.Token = p.Token "
                f"    AND v.Status = 'purged_for_retention' "
                f"    AND v.StatusChangedBy = 'retention_job' "
                f");"
            )
        cursor.execute(sql)
        row = cursor.fetchone()
        if row is None or row[0] is None:
            return 0
        return int(row[0])
    except Exception as exc:  # noqa: BLE001
        # Provenance table not yet deployed OR permission denied — log
        # WARNING but don't fail the verdict. The vault count from SP-10
        # is the authoritative number per spec § 3.8 L1054.
        logger.warning(
            "PiiTokenProvenance reflection count unavailable (non-fatal): %s",
            exc,
        )
        return 0
    finally:
        try:
            cursor.close()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Audit-row writer — one CLI_ENFORCE_RETENTION row per invocation
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
    """INSERT one ``CLI_ENFORCE_RETENTION`` row into PipelineEventLog.

    Per D76 + spec § 3.8 L1054. ONE row per invocation (NOT one row per
    PiiVault row — per-category counts surface in Metadata JSON). Best-
    effort: failures are logged but do not affect the verdict exit code
    (parity with B188 / B189 / B190 / B218 audit-row patterns).

    Returns the IDENTITY value of the inserted row via SCOPE_IDENTITY()
    so the JSON ``audit_event_id`` key (per spec § 3.8 L1111) can be
    populated. Returns None on failure (the JSON key is then null).

    When ``cursor_factory`` is injected (test path), the live
    ``utils.connections`` resolution is skipped.

    When ``skip=True`` (test path; main()'s ``no_audit_event``), the
    function returns None immediately without writing.
    """
    if skip:
        return None
    metadata_json = json.dumps(metadata, separators=(",", ":"), default=str)
    event_detail = (
        f"enforce_retention / "
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
            # Capture the SCOPE_IDENTITY() of the inserted row so we
            # can surface it as audit_event_id in JSON output per spec
            # § 3.8 L1111. The two statements run on the same connection
            # so SCOPE_IDENTITY() reflects this INSERT.
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
        logger.exception("Failed to write CLI_ENFORCE_RETENTION audit row")
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


def _emit_human_summary(
    *,
    counts: dict[str, int],
    dry_run: bool,
    audit_event_id: int | None,
) -> None:
    """Print the spec § 3.8 L1100-1109 stdout block."""
    header = (
        "Retention enforcement — dry run"
        if dry_run
        else "Retention enforcement — apply"
    )
    print(header)
    print(
        f"  Cutoff source: PiiVault.RetentionExpiresAt column "
        f"(per-row; D30 retention policy)"
    )
    verb = "eligible for purge" if dry_run else "purged"
    print(
        f"  PiiVault rows {verb:<24}: {counts.get('vault', 0):,} "
        f"(RetentionExpiresAt < now AND LegalHold = 0 AND Status='active')"
    )
    reflect_verb = "reflecting" if dry_run else "reflected"
    print(
        f"  PiiTokenProvenance rows {reflect_verb:<14}: "
        f"{counts.get('provenance', 0):,}"
    )
    create_verb = "would create" if dry_run else "created"
    print(
        f"  OrphanedTokenLog rows {create_verb:<16}: "
        f"{counts.get('orphanedtokenlog', 0):,}"
    )
    vault_count = counts.get("vault", 0)
    if dry_run:
        print(
            f"Would flip {vault_count:,} PiiVault rows to "
            f"Status='purged_for_retention'. Re-run with --apply to commit."
        )
    else:
        suffix = (
            f" Audit event: PipelineEventLog row {audit_event_id}."
            if audit_event_id is not None
            else ""
        )
        print(
            f"Purge complete. Flipped {vault_count:,} rows to "
            f"Status='purged_for_retention'.{suffix}"
        )


def _emit_json(payload: dict) -> None:
    """Emit the canonical JSON payload per spec § 3.8 L1111.

    Shape: ``{"dry_run": bool, "counts": {"vault": N, "provenance": M,
    "orphanedtokenlog": Q}, "audit_event_id": N}``. ``audit_event_id``
    is the SCOPE_IDENTITY() of the CLI_ENFORCE_RETENTION row written by
    ``_write_audit_row()``, or null on write failure / ``--no-audit-event``.
    """
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


# ---------------------------------------------------------------------------
# General DB connection factory (test-friendly resolution)
# ---------------------------------------------------------------------------


def _resolve_default_vault_cursor_factory() -> Callable:
    """Return a callable that opens a connection to the General DB.

    Resolves at CALL TIME so tests patching ``sys.modules['pyodbc']``
    after tool import are honored. Production path uses Round 3 § 2.3
    ``vault_client.call_vault_sp()`` indirectly via
    ``utils.connections.get_connection('General')``; if that raises (no
    DSN / no driver), we fall back to ``sys.modules['pyodbc'].connect``.

    Raises :class:`VaultConfigError` (mapped to exit 2 by main()) if
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
                raise VaultConfigError(
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
    json_output: bool = False,
    verbose: bool = False,
    quiet: bool = False,
    justification: str | None = None,
    no_audit_event: bool = False,
    # ---- Injection hooks (test path) ----
    vault_cursor_factory: Callable | None = None,
    audit_cursor_factory: Callable | None = None,
    general_db: str | None = None,
) -> dict:
    """Programmatic entry — invokes SP-10 ``EnforceRetention`` per D30.

    Returns a dict matching the D76 audit-row Metadata shape (see module
    docstring for the canonical schema). Exit-code derivation per D74 +
    spec § 3.8 L1113-1116:

    * 0: retention enforcement completed (or dry-run preview produced);
      includes zero-rows-qualified
    * 1: vault connection drop / retryable / lock contention
    * 2: fatal — VaultConfigError / unexpected exception

    Parameters
    ----------
    actor:
        Operator identity (per D75 + D76). REQUIRED.
    apply:
        When True, SP-10 invoked with ``@DryRun=0`` (apply); when False
        (default per spec § 1.2 dry-run-default), ``@DryRun=1`` (preview).
    dry_run:
        B88 mutex bridge — tests pass ``dry_run`` paralleling ``apply``.
        If True AND ``apply=True`` -> exit 2 (mutex violation). If True
        alone -> override ``apply=False``.
    justification:
        Operator justification recorded in audit-row Metadata per D75.
    no_audit_event:
        When True, skip the CLI-level PipelineEventLog write (pipeline-
        programmatic callers per D75 + D76).
    vault_cursor_factory / audit_cursor_factory:
        Test-injection hooks. Defaults resolve to live infrastructure.
    general_db:
        Override the canonical General DB name (defaults to
        ``utils.configuration.GENERAL_DB``, fallback ``'General'``).
    """
    started_at = datetime.now(timezone.utc).replace(tzinfo=None)

    # B88 dry-run/apply mutex bridge: tests pass `dry_run` as a kwarg paralleling
    # `apply`. Canonical semantic: --apply makes it real; --dry-run forces preview.
    # If both True -> mutex violation (exit 2). If `dry_run=True` -> override
    # apply=False.
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

    lock_resource = _build_lock_resource(started_at)

    # ---- Pre-populate result with input echoes for early-exit paths ----
    result: dict[str, Any] = {
        "event_kind": "retention_enforcement",
        "actor": actor,
        "justification": justification,
        "dry_run": (not apply),
        "counts": {"vault": 0, "provenance": 0, "orphanedtokenlog": 0},
        "exit_code": EXIT_SUCCESS,
        "lock_acquired": False,
        "lock_resource": lock_resource,
        "started_at": started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "started_at_dt": started_at,
        "completed_at": None,
        "audit_event_id": None,
        "errors": [],
    }

    # ---- Resolve connection factory ----
    if vault_cursor_factory is None:
        try:
            vault_cursor_factory = _resolve_default_vault_cursor_factory()
        except VaultConfigError as exc:
            result["exit_code"] = EXIT_FATAL
            result["error_type"] = "VaultConfigError"
            result["error_message"] = str(exc)
            result["errors"].append(f"VaultConfigError: {exc}")
            result["completed_at"] = datetime.now(
                timezone.utc
            ).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%SZ")
            if not quiet:
                print(
                    f"FATAL: vault config unavailable for enforce_retention: {exc}",
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
            return result

    # ---- Open connection + acquire lock + invoke SP-10 ----
    conn = None
    try:
        try:
            conn = vault_cursor_factory()
        except VaultConfigError as exc:
            # Explicit config error from the factory -> exit 2 fatal.
            result["exit_code"] = EXIT_FATAL
            result["error_type"] = "VaultConfigError"
            result["error_message"] = str(exc)[:4000]
            result["errors"].append(f"VaultConfigError: {exc}")
            logger.error("VaultConfigError during connection setup: %s", exc)
            if not quiet:
                print(
                    f"FATAL: vault config error: {exc}",
                    file=sys.stderr,
                )
            result["completed_at"] = datetime.now(
                timezone.utc
            ).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%SZ")
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
            # Generic connection failure -> exit 1 (retryable per spec
            # § 3.8 L1115 — "SP-10 is single-statement transactional ...
            # operator can re-run").
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

        # autocommit=True is the canonical pattern from
        # utils.connections.get_connection() L221 + W-8 RCSI analysis.
        try:
            conn.autocommit = True
        except Exception:  # noqa: BLE001
            pass

        # ---- Acquire the retention lock ----
        try:
            lock_acquired = _acquire_applock(conn, resource=lock_resource)
        except Exception as exc:  # noqa: BLE001
            result["exit_code"] = EXIT_WARNING
            result["error_type"] = type(exc).__name__
            result["error_message"] = f"sp_getapplock error: {exc}"
            result["errors"].append(f"sp_getapplock error: {exc}")
            logger.warning("sp_getapplock invocation failed: %s", exc)
            result["completed_at"] = datetime.now(
                timezone.utc
            ).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%SZ")
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

        result["lock_acquired"] = bool(lock_acquired)
        if not lock_acquired:
            # Another retention sweep is in flight -> exit 1 per spec
            # § 3.8 L1115 retryable.
            result["exit_code"] = EXIT_WARNING
            result["error_type"] = "RetentionLockContention"
            msg = (
                f"sp_getapplock contention on resource {lock_resource!r}; "
                f"another retention sweep is in flight. Re-run after it "
                f"completes (typically within minutes for SP-10's single-"
                f"statement UPDATE)."
            )
            result["error_message"] = msg
            result["errors"].append(msg)
            logger.warning(msg)
            if not quiet:
                print(f"WARNING: {msg}", file=sys.stderr)
            result["completed_at"] = datetime.now(
                timezone.utc
            ).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%SZ")
            audit_id = _write_audit_row(
                result,
                status="FAILED",
                error_message=msg,
                cursor_factory=audit_cursor_factory,
                general_db=general_db,
                skip=no_audit_event,
            )
            result["audit_event_id"] = audit_id
            return result

        # ---- Lock acquired — invoke SP-10 ----
        try:
            vault_count = _invoke_sp10(
                conn,
                dry_run=(not apply),
                general_db=general_db,
            )
            provenance_count = _read_provenance_count(
                conn,
                dry_run=(not apply),
                general_db=general_db,
            )
            # OrphanedTokenLog wiring is B01-tracked (per spec § 3.8 L1046
            # "wired into SP-10 per B01"). Until B01 lands, the count is
            # zero — surface honestly rather than inventing a number.
            orphaned_count = 0

            result["counts"] = {
                "vault": vault_count,
                "provenance": provenance_count,
                "orphanedtokenlog": orphaned_count,
            }
            result["exit_code"] = EXIT_SUCCESS

        except VaultConfigError as exc:
            # Fatal config / permission / SP-not-found -> exit 2.
            result["exit_code"] = EXIT_FATAL
            result["error_type"] = "VaultConfigError"
            result["error_message"] = str(exc)[:4000]
            result["errors"].append(f"VaultConfigError: {exc}")
            logger.error("VaultConfigError during SP-10 invocation: %s", exc)
            if not quiet:
                print(f"FATAL: {exc}", file=sys.stderr)
        except VaultUnavailable as exc:
            # Retryable -> exit 1.
            result["exit_code"] = EXIT_WARNING
            result["error_type"] = "VaultUnavailable"
            result["error_message"] = str(exc)[:4000]
            result["errors"].append(f"VaultUnavailable: {exc}")
            logger.warning("VaultUnavailable during SP-10 invocation: %s", exc)
            if not quiet:
                print(
                    f"WARNING: vault unavailable (operator can re-run): {exc}",
                    file=sys.stderr,
                )
        except VaultError as exc:
            # Vault base class catch — treat as retryable (defensive
            # default; new sub-classes inherit the right exit code).
            result["exit_code"] = EXIT_WARNING
            result["error_type"] = type(exc).__name__
            result["error_message"] = str(exc)[:4000]
            result["errors"].append(f"{type(exc).__name__}: {exc}")
            logger.warning("Vault error during SP-10 invocation: %s", exc)
            if not quiet:
                print(
                    f"WARNING: vault error (operator can re-run): {exc}",
                    file=sys.stderr,
                )
        except Exception as exc:  # noqa: BLE001
            # Unexpected -> exit 1 (retryable) per spec § 3.8 L1115.
            # Per spec: SP-10's single-statement UPDATE is transactional;
            # partial-row-state cannot occur, so retryable is correct.
            result["exit_code"] = EXIT_WARNING
            result["error_type"] = type(exc).__name__
            result["error_message"] = str(exc)[:4000]
            result["errors"].append(f"{type(exc).__name__}: {exc}")
            logger.exception("Error during SP-10 invocation")
            if not quiet:
                print(
                    f"WARNING: SP-10 invocation error (operator can re-run): {exc}",
                    file=sys.stderr,
                )

    finally:
        if conn is not None:
            if result.get("lock_acquired"):
                try:
                    _release_applock(conn, resource=lock_resource)
                except Exception:  # noqa: BLE001
                    logger.exception("Failed to release sp_getapplock")
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass

    result["completed_at"] = datetime.now(
        timezone.utc
    ).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ---- Invocation-level audit row (D76 — ONE per invocation) ----
    status = (
        "SUCCESS"
        if result["exit_code"] in (EXIT_SUCCESS, EXIT_WARNING)
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
        # Spec § 3.8 L1111 canonical shape — emit ONLY the 3 canonical
        # keys (dry_run / counts / audit_event_id). Internal bookkeeping
        # (started_at_dt, errors, lock_resource, etc.) stays in the
        # programmatic return dict but is NOT exposed via --json per spec.
        json_payload = {
            "dry_run": result["dry_run"],
            "counts": result["counts"],
            "audit_event_id": result["audit_event_id"],
        }
        _emit_json(json_payload)
    elif not quiet:
        _emit_human_summary(
            counts=result["counts"],
            dry_run=result["dry_run"],
            audit_event_id=result["audit_event_id"],
        )

    return result


# ---------------------------------------------------------------------------
# CLI argv entry point
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    """Alias for :func:`_build_parser` — Tier 0 scaffold contract."""
    return _build_parser()


def _build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser per spec § 3.8 + § 1.4 canonical args.

    Per Pitfall #9.b invented-parameter rule (HANDOFF §8): this parser
    does NOT accept ``--retention-date`` / ``--actor-name`` / ``--categories``
    (canonical SP-10 takes only ``@DryRun``; B93 + B94 schema-evolution
    proposals are NOT yet locked). Tier 0 assertion (h) per spec L1118
    explicitly verifies argparse REJECTS these invented args.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Invoke Round 1 SP-10 General.ops.EnforceRetention per D30. "
            "Sweeps PiiVault rows where RetentionExpiresAt < SYSUTCDATETIME() "
            "AND LegalHold = 0 AND Status = 'active' and flips them to "
            "Status='purged_for_retention'. Emits one CLI_ENFORCE_RETENTION "
            "audit row per invocation."
        ),
    )

    # ---- D75 canonical args (per spec § 1.4) ----
    # --apply / --dry-run are mutually exclusive per B88 (apply opt-in,
    # dry-run default). Spec § 1.2 — side-effecting tools default to dry-run.
    apply_group = parser.add_mutually_exclusive_group()
    apply_group.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Apply: invoke SP-10 with @DryRun=0 (commit the Status flip). "
            "Default is dry-run (SP-10 with @DryRun=1; preview only)."
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
            "pipeline / pipeline-lead / reconciliation. Auto-detected via "
            "TTY / AUTOMIC_RUN_ID env when omitted."
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
        help=(
            "Emit canonical JSON output per spec § 3.8 L1111 "
            "({dry_run, counts, audit_event_id}) instead of human summary."
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


def _validate_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    """Enforce --apply/--dry-run mutex + actor presence.

    argparse's mutually_exclusive_group already enforces the mutex; this
    function is a placeholder for future tool-specific validations that
    can't be expressed declaratively (kept for symmetry with
    log_retention_cleanup.py's structure).
    """
    # No additional validations required — argparse handles the mutex
    # + the canonical actor heuristic in main() resolves None defaults.
    return None


def cli_main() -> int:
    """Argv entry point — argparse + main() + return exit code per D74.

    Exit codes (always one of 0 / 1 / 2 per D74 + spec § 3.8 L1113-1116):
        - 0: retention enforcement completed (or dry-run preview)
        - 1: vault connection drop / retryable / lock contention
        - 2: fatal (VaultConfigError / unexpected exception)
    """
    parser = _build_parser()
    args = parser.parse_args()
    _validate_args(args, parser)

    actor = args.actor or _detect_actor()

    try:
        result = main(
            actor=actor,
            apply=args.apply,
            json_output=args.json_output,
            verbose=args.verbose,
            quiet=args.quiet,
            justification=args.justification,
        )
    except SystemExit as exc:
        # B88 mutex violation (dry_run + apply both True) -> code 2 already
        # in the SystemExit. argparse-style validation also routes here.
        code = exc.code if isinstance(exc.code, int) else EXIT_FATAL
        if code not in (EXIT_SUCCESS, EXIT_WARNING, EXIT_FATAL):
            code = EXIT_FATAL
        return code
    except KeyboardInterrupt:
        logger.warning("Interrupted by operator")
        return EXIT_WARNING
    except Exception:  # noqa: BLE001
        tb = traceback.format_exc()
        print(
            f"FATAL: enforce_retention unexpected exception:\n{tb[:1000]}",
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
