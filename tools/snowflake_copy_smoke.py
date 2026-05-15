"""End-to-end Snowflake COPY INTO smoke script (operator-facing).

Per **M17** ``data_load/snowflake_uploader.py`` (Round 3 § 7.1; Wave 4
build 2026-05-13). End-to-end smoke script for operator-driven
Snowflake COPY INTO testing during the trial period.

What this tool does
-------------------

The operator runs this script with a ``--registry-id`` pointing at a
``ParquetSnapshotRegistry`` row already verified by M3's
:func:`verify_parquet_snapshot`. The tool composes M17's
:func:`copy_parquet_to_snowflake` to:

1. Read the registry row + confirm ``Status='verified'`` (M17 raises
   :class:`~utils.errors.RegistryStatusInvalid` otherwise).
2. Load credentials via M7 (RSA key materialized to
   ``/dev/shm/snowflake_pk_<pid>`` mode 0600 — never enters this
   tool's process memory).
3. Open a Snowflake CONNECTION + issue ``COPY INTO`` against the
   configured stage + table.
4. Flip ``ParquetSnapshotRegistry.Status`` ``'verified' -> 'replicated'``
   via M3's :func:`mark_replicated` composition inside M17.
5. Emit a ``CLI_SNOWFLAKE_COPY_SMOKE`` audit row to
   ``General.ops.PipelineEventLog`` per D76 (one row per invocation).

The script is intentionally narrow — it wraps a single M17 call. For
the comprehensive M3 -> M17 -> Snowflake walk, use M17 directly from
pipeline orchestration. This tool exists for the trial-period
"confirm data actually lands in Snowflake" smoke loop.

CLI contract
------------

::

    # Dry-run preview (DEFAULT — no Snowflake credits consumed)
    python -m tools.snowflake_copy_smoke --registry-id 12345

    # Real invocation — opt-in via --apply (B88 mutex pattern)
    python -m tools.snowflake_copy_smoke --registry-id 12345 --apply

    # Override the default Snowflake target table
    python -m tools.snowflake_copy_smoke --registry-id 12345 --apply \\
        --snowflake-table UDM_BRONZE_MIRROR.DNA.ACCT_SMOKE

    # JSON output for machine consumers
    python -m tools.snowflake_copy_smoke --registry-id 12345 --apply --json

Exit codes (per D74)
~~~~~~~~~~~~~~~~~~~~

* **0** — COPY succeeded (or dry-run preview rendered cleanly).
* **1** — operational failure (e.g.
  :class:`~utils.errors.VaultUnavailable`,
  :class:`~utils.errors.SnowflakeCopyTimeout` — retry-eligible).
* **2** — fatal (e.g.
  :class:`~utils.errors.RegistryNotFound`,
  :class:`~utils.errors.RegistryStatusInvalid`,
  :class:`~utils.errors.SnowflakeBudgetAlert`,
  :class:`~utils.errors.SnowflakeAuthFailed`, mutually-exclusive arg
  violation, unexpected exception).

Audit row (per D76)
~~~~~~~~~~~~~~~~~~~

* ``General.ops.PipelineEventLog.EventType = 'CLI_SNOWFLAKE_COPY_SMOKE'``
  — a **NEW** ``CLI_*`` family value beyond the 11 Round 4 originals;
  registered in CLAUDE.md Structure list at the same time as this
  module is registered.
* ONE row per INVOCATION (the per-registry ``PARQUET_REPLICATE``
  audit row is written separately by M17's M3-composition; this row
  is the operator-CLI invocation receipt).
* ``Metadata`` JSON shape::

    {
        "event_kind": "invoke",
        "actor": "<operator|automic|pipeline>",
        "registry_id": <int>,
        "snowflake_table": "<DB.SCHEMA.TABLE or null>",
        "copy_timeout_seconds": <int>,
        "dry_run": <bool>,
        "rows_copied": <int or null>,
        "copy_history_id": "<str or null>",
        "duration_ms": <int or null>,
        "error_class": "<class name or null>",
        "error_message": "<str or null>",
        "exit_code": <int>,
        "started_at": "<ISO-8601 naive-UTC ms-precision>",
        "completed_at": "<ISO-8601 naive-UTC ms-precision>"
    }

Classification per ``udm-execution-classifier`` skill
-----------------------------------------------------

* **Trigger**: Manual operator CLI for trial-period validation. NOT
  scheduled — this is a one-off / event-driven script invoked when the
  operator wants to confirm the M17 path works end-to-end against a
  real Snowflake account (the trial period).
* **Frequency**: ad-hoc. Pipeline-programmatic callers invoke M17
  :func:`copy_parquet_to_snowflake` directly, not via this CLI shell.
* **Idempotency**: YES per M17 § 7.1 — Snowflake's COPY INTO tracks
  per-file load history (re-COPY produces ``rows_loaded=0``); M3's
  :func:`mark_replicated` short-circuits on ``Status='replicated'``.
  Re-invoking on a row already replicated is a safe no-op at both
  layers.
* **Audit-row family**: ``CLI_SNOWFLAKE_COPY_SMOKE`` per D76 + this
  module's CLAUDE.md Structure registration.
* **Routing**: ``ONE_OFF_SCRIPTS.md`` operator tools table (manual +
  event-driven).

D-numbers consumed
------------------

D5 (Snowflake-managed Iceberg),
D15 (idempotency mandatory — M17 + M3 chain),
D17 (idempotency ledger via M3),
D23 (Snowflake budget alert — M17 enforces),
D26 (append-only audit — one CLI row + one PARQUET_REPLICATE row),
D67 (Tier 0 smoke discipline),
D68 (canonical exception hierarchy — utils.errors),
D69 (cursor / connection ownership — per-process),
D71 (Snowflake RSA auth via /dev/shm/snowflake_pk_<pid>),
D74-D77 (CLI exit-code contract + arg naming + audit-row contract +
Tier 0 6-canonical-assertion scaffold per descriptive-name conv),
D92 (forward-only additive — new tool; no M-module signature change),
D103 (Claude Code security model — PEM bytes never enter this module).

Canonical references cited (per Pitfall #9.l producer self-check)
-----------------------------------------------------------------

* M17 :func:`copy_parquet_to_snowflake` signature:
  ``data_load/snowflake_uploader.py`` —
  ``(*, registry_id: int, snowflake_table: str | None = None,
  timeout_seconds: int = DEFAULT_COPY_TIMEOUT_SECONDS)
  -> SnowflakeCopyResult``.
* ``SnowflakeCopyResult`` fields: ``registry_id`` /
  ``snowflake_table`` / ``rows_copied`` / ``copy_history_id`` /
  ``duration_ms``.
* ``utils.errors`` canonical classes used (imported directly per
  B228): :class:`~utils.errors.PipelineFatalError`,
  :class:`~utils.errors.PipelineRetryableError`,
  :class:`~utils.errors.RegistryNotFound`,
  :class:`~utils.errors.RegistryStatusInvalid`,
  :class:`~utils.errors.SnowflakeAuthFailed`,
  :class:`~utils.errors.SnowflakeBudgetAlert`,
  :class:`~utils.errors.SnowflakeCopyTimeout`,
  :class:`~utils.errors.VaultUnavailable`,
  :class:`~utils.errors.CredentialsLoadError`.
* CLI conventions: ``phase1/04_tools.md`` § 1.4 (canonical args) +
  § 1.7 (invocation-pattern heuristic — AUTOMIC_RUN_ID env + isatty) +
  § 1.8 (exit-code mapping).

See also
--------

* ``data_load/snowflake_uploader.py`` (M17 § 7.1) — the canonical
  M-module wrapped here.
* ``tools/parquet_verify.py`` (Round 4 § 3.2) — sibling tool the
  operator runs BEFORE this one (verify must precede COPY per M17's
  ``Status='verified'`` precondition).
* RB-12 (Snowflake replication runbook) — operational guidance for
  trial-period validation.
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

# Canonical exception hierarchy per D68 + B-228 (utils.errors single
# source of truth; tools import directly).
try:
    from utils.errors import (  # noqa: E402
        CredentialsLoadError,
        PipelineFatalError,
        PipelineRetryableError,
        RegistryNotFound,
        RegistryStatusInvalid,
        SnowflakeAuthFailed,
        SnowflakeBudgetAlert,
        SnowflakeCopyTimeout,
        VaultUnavailable,
    )
except (ImportError, ModuleNotFoundError):
    # Defensive fallback for test environments where utils.errors may
    # be mocked as MagicMock — re-import from the filesystem directly.
    import importlib.util as _importlib_util  # noqa: E402

    _err_path = Path(__file__).resolve().parent.parent / "utils" / "errors.py"
    _spec = _importlib_util.spec_from_file_location(
        "utils._errors_snowflake_smoke", _err_path
    )
    _err_mod = _importlib_util.module_from_spec(_spec)
    _spec.loader.exec_module(_err_mod)
    CredentialsLoadError = _err_mod.CredentialsLoadError
    PipelineFatalError = _err_mod.PipelineFatalError
    PipelineRetryableError = _err_mod.PipelineRetryableError
    RegistryNotFound = _err_mod.RegistryNotFound
    RegistryStatusInvalid = _err_mod.RegistryStatusInvalid
    SnowflakeAuthFailed = _err_mod.SnowflakeAuthFailed
    SnowflakeBudgetAlert = _err_mod.SnowflakeBudgetAlert
    SnowflakeCopyTimeout = _err_mod.SnowflakeCopyTimeout
    VaultUnavailable = _err_mod.VaultUnavailable

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Module-level public constants (per D74 + D76)
# ---------------------------------------------------------------------------

#: D76 EventType — NEW ``CLI_*`` family value beyond the 11 R4 originals.
#: Registered in CLAUDE.md Structure list at the same time as this module.
EVENT_TYPE = "CLI_SNOWFLAKE_COPY_SMOKE"

#: D74 canonical exit-code contract.
EXIT_SUCCESS = 0
EXIT_OPERATIONAL_FAILURE = 1
EXIT_FATAL = 2

#: M17 default COPY-INTO timeout (300 s = 5 min per spec § 7.1).
_DEFAULT_COPY_TIMEOUT_SECONDS = 300

#: Retryable exception classes — surface as exit 1.
_RETRYABLE_ERROR_CLASSES: tuple[type, ...] = (
    SnowflakeCopyTimeout,
    VaultUnavailable,
)
#: Fatal exception classes — surface as exit 2.
_FATAL_ERROR_CLASSES: tuple[type, ...] = (
    RegistryNotFound,
    RegistryStatusInvalid,
    SnowflakeAuthFailed,
    SnowflakeBudgetAlert,
    CredentialsLoadError,
)


# ---------------------------------------------------------------------------
# Actor detection (per § 1.7 invocation-pattern heuristic)
# ---------------------------------------------------------------------------


def _detect_actor() -> str:
    """Resolve actor identity per spec § 1.7 invocation-pattern heuristic.

    Order:

    1. ``AUTOMIC_RUN_ID`` env var present -> 'automic'
    2. ``sys.stdin.isatty()`` -> 'operator'
    3. Else -> 'pipeline'

    The actor string lands in audit-row Metadata + the M17 call (M17
    forwards to M3's :func:`mark_replicated` which records the actor
    in ``IdempotencyLedger.Actor``).
    """
    if os.environ.get("AUTOMIC_RUN_ID"):
        return "automic"
    try:
        if sys.stdin.isatty():
            return "operator"
    except (AttributeError, ValueError):
        # ValueError: I/O operation on closed file (pytest -s pipe path)
        pass
    return "pipeline"


# ---------------------------------------------------------------------------
# Lazy resolvers — sibling-module test injection per B214
# ---------------------------------------------------------------------------


def _get_copy_parquet_to_snowflake() -> Callable:
    """Return M17 :func:`copy_parquet_to_snowflake` (lazy).

    Lazy-resolved so tests can swap via
    ``patch.object(mod, "_get_copy_parquet_to_snowflake", ...)`` without
    ``sys.modules`` mutation (per B214 lesson — sys.modules patches
    require careful cleanup; the getter pattern avoids it entirely).
    Mirrors M17's own ``_get_*`` pattern used for sibling-module imports.
    """
    try:
        from data_load.snowflake_uploader import (  # type: ignore  # noqa: PLC0415
            copy_parquet_to_snowflake,
        )

        return copy_parquet_to_snowflake
    except Exception as exc:  # noqa: BLE001
        raise PipelineFatalError(
            f"M17 snowflake_uploader unavailable: {exc}",
            metadata={"step": "resolve_copy_parquet_to_snowflake"},
        ) from exc


def _resolve_default_cursor_factory() -> Callable:
    """Return a callable that opens a connection to the General DB.

    Resolves at CALL TIME so tests patching ``sys.modules['pyodbc']``
    after tool import are honored. Production path uses
    ``utils.connections.get_connection('General')``; falls back to
    ``sys.modules['pyodbc'].connect`` if connections isn't importable.
    """

    def _open():
        try:
            from utils.connections import get_connection  # type: ignore  # noqa: PLC0415

            return get_connection("General")
        except Exception:  # noqa: BLE001
            pass
        pyodbc_mod = sys.modules.get("pyodbc")
        if pyodbc_mod is None:
            try:
                import pyodbc as pyodbc_mod  # type: ignore  # noqa: F401, PLC0415
            except Exception as exc:  # noqa: BLE001
                raise PipelineFatalError(
                    f"pyodbc / utils.connections both unavailable: {exc}",
                    metadata={"step": "resolve_default_cursor_factory"},
                ) from exc
        return pyodbc_mod.connect("DRIVER={ODBC Driver 18 for SQL Server};")

    return _open


# ---------------------------------------------------------------------------
# Time helpers — ms-precision naive-UTC per SCD2-P1-f / CDC-NOW-MS
# ---------------------------------------------------------------------------


def _now_naive_ms() -> datetime:
    """Return naive (no tzinfo) UTC datetime truncated to millisecond.

    Per SCD2-P1-f / CDC-NOW-MS invariant — BCP/pyodbc datetime parity
    with the ``DATETIME2(3)`` storage column. The ``replace`` strips
    sub-millisecond precision so a round-trip through BCP CSV (which
    writes ``'%Y-%m-%d %H:%M:%S.%3f'``) yields the same value.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    # Truncate sub-millisecond precision.
    ms = now.microsecond // 1000
    return now.replace(microsecond=ms * 1000)


def _format_iso_naive_ms(dt: datetime) -> str:
    """Format a naive-UTC ms-precision datetime as ISO-8601 with millis."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


# ---------------------------------------------------------------------------
# Audit row writer (per D76)
# ---------------------------------------------------------------------------


def _write_audit_row(
    *,
    metadata: dict,
    status: str,
    error_message: str | None,
    cursor_factory: Callable | None,
    general_db: str,
    skip: bool = False,
) -> int | None:
    """INSERT one ``CLI_SNOWFLAKE_COPY_SMOKE`` row into PipelineEventLog.

    Per D76. ONE row per invocation. Best-effort — failures are logged
    but do not affect the verdict exit code (parity with B188 / B189 /
    B190 / B218 audit-row patterns).

    Returns the ``SCOPE_IDENTITY()`` of the inserted row so the JSON
    payload's ``audit_event_id`` key can be populated. Returns ``None``
    on failure or when ``skip=True``.
    """
    if skip:
        return None

    started_at_dt = metadata.get("started_at_dt") or _now_naive_ms()

    # Build the audit metadata JSON (without the internal datetime obj).
    payload = {k: v for k, v in metadata.items() if k != "started_at_dt"}
    metadata_json = json.dumps(payload, separators=(",", ":"), default=str)

    event_detail = (
        f"snowflake_copy_smoke / dry_run={metadata.get('dry_run')} / "
        f"registry_id={metadata.get('registry_id')} / "
        f"rows_copied={metadata.get('rows_copied', 0) or 0}"
    )

    if cursor_factory is None:
        try:
            from utils.connections import get_connection  # type: ignore  # noqa: PLC0415

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
                f"VALUES ("
                f"  NEXT VALUE FOR [{general_db}].ops.PipelineBatchSequence, "
                f"  NULL, NULL, ?, ?, ?, SYSUTCDATETIME(), ?, ?, ?); "
                f"SELECT CAST(SCOPE_IDENTITY() AS BIGINT) AS AuditEventId;",
                EVENT_TYPE,
                event_detail,
                started_at_dt,
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
        logger.exception("Failed to write CLI_SNOWFLAKE_COPY_SMOKE audit row")
        return None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Classification helpers
# ---------------------------------------------------------------------------


def _classify_exception(exc: BaseException) -> int:
    """Return the canonical exit code for an exception.

    Per D68 retryable-vs-fatal tier separation:

    * Members of :data:`_RETRYABLE_ERROR_CLASSES` -> ``EXIT_OPERATIONAL_FAILURE``
    * Members of :data:`_FATAL_ERROR_CLASSES` -> ``EXIT_FATAL``
    * Generic :class:`PipelineRetryableError` -> ``EXIT_OPERATIONAL_FAILURE``
    * Generic :class:`PipelineFatalError` -> ``EXIT_FATAL``
    * Everything else -> ``EXIT_FATAL`` (safer default — operator
      diagnoses via traceback, then retries / fixes).
    """
    if isinstance(exc, _RETRYABLE_ERROR_CLASSES):
        return EXIT_OPERATIONAL_FAILURE
    if isinstance(exc, _FATAL_ERROR_CLASSES):
        return EXIT_FATAL
    if isinstance(exc, PipelineRetryableError):
        return EXIT_OPERATIONAL_FAILURE
    if isinstance(exc, PipelineFatalError):
        return EXIT_FATAL
    return EXIT_FATAL


# ---------------------------------------------------------------------------
# Stdout rendering
# ---------------------------------------------------------------------------


def _emit_human_dry_run(
    *,
    registry_id: int,
    snowflake_table: str | None,
    copy_timeout_seconds: int,
    audit_event_id: int | None,
) -> None:
    """Render the dry-run preview block (default mode)."""
    target = snowflake_table or "<default: $SNOWFLAKE_DATABASE.$SNOWFLAKE_SCHEMA.<table>>"
    lines = [
        "Snowflake COPY INTO smoke — DRY RUN PREVIEW",
        f"  RegistryId:           {registry_id}",
        f"  Snowflake target:     {target}",
        f"  COPY timeout (s):     {copy_timeout_seconds}",
        "  Action:               NO COPY issued (pass --apply to invoke).",
    ]
    if audit_event_id is not None:
        lines.append(f"  Audit event:          {audit_event_id}")
    print("\n".join(lines))


def _emit_human_success(
    *,
    registry_id: int,
    snowflake_table: str,
    rows_copied: int,
    copy_history_id: str,
    duration_ms: int,
    audit_event_id: int | None,
) -> None:
    """Render the post-COPY success block."""
    lines = [
        "Snowflake COPY INTO smoke — SUCCESS",
        f"  RegistryId:           {registry_id}",
        f"  Snowflake target:     {snowflake_table}",
        f"  Rows copied:          {rows_copied:,}",
        f"  Copy history ID:      {copy_history_id}",
        f"  Duration (ms):        {duration_ms:,}",
    ]
    if audit_event_id is not None:
        lines.append(f"  Audit event:          {audit_event_id}")
    print("\n".join(lines))


def _emit_human_failure(
    *,
    registry_id: int,
    error_class: str,
    error_message: str,
    exit_code: int,
    audit_event_id: int | None,
) -> None:
    """Render the post-COPY failure block to stderr."""
    tier = (
        "OPERATIONAL FAILURE (retryable)"
        if exit_code == EXIT_OPERATIONAL_FAILURE
        else "FATAL"
    )
    lines = [
        f"Snowflake COPY INTO smoke — {tier}",
        f"  RegistryId:           {registry_id}",
        f"  Error class:          {error_class}",
        f"  Error message:        {error_message[:500]}",
        f"  Exit code:            {exit_code}",
    ]
    if audit_event_id is not None:
        lines.append(f"  Audit event:          {audit_event_id}")
    print("\n".join(lines), file=sys.stderr)


def _emit_json(payload: dict) -> None:
    """Emit the canonical JSON payload."""
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def _build_json_payload(metadata: dict, *, audit_event_id: int | None) -> dict:
    """Build the JSON output payload for ``--json``.

    Strips the internal ``started_at_dt`` field; surfaces ISO strings
    + result fields.
    """
    payload = {k: v for k, v in metadata.items() if k != "started_at_dt"}
    payload["audit_event_id"] = audit_event_id
    return payload


# ---------------------------------------------------------------------------
# Top-level main() — programmatic entry
# ---------------------------------------------------------------------------


def main(
    *,
    args: argparse.Namespace | None = None,
    copy_fn: Callable | None = None,
    audit_cursor_factory: Callable | None = None,
    general_db: str = "General",
) -> int:
    """Programmatic entry — wraps M17 :func:`copy_parquet_to_snowflake`.

    Parameters
    ----------
    args:
        Parsed argparse Namespace. When ``None``, ``cli_main()`` parses
        ``sys.argv`` and constructs it. Required keys (from
        :func:`_build_parser`): ``registry_id`` / ``snowflake_table`` /
        ``copy_timeout`` / ``dry_run`` / ``apply`` / ``json_output`` /
        ``quiet`` / ``verbose`` / ``actor`` / ``no_audit_event``.
    copy_fn:
        Override the M17 :func:`copy_parquet_to_snowflake` callable.
        Production path resolves via :func:`_get_copy_parquet_to_snowflake`
        at call time. Test injection per B214 — pass a mock here.
    audit_cursor_factory:
        Override the audit-row connection factory. Test injection per
        B214.
    general_db:
        Override the General DB name (defaults to ``'General'``).

    Returns
    -------
    int
        Canonical D74 exit code (0 / 1 / 2). The caller (``cli_main``)
        propagates this to ``sys.exit``.
    """
    if args is None:
        # Defensive default — operators normally come through cli_main.
        parser = _build_parser()
        args = parser.parse_args([])

    # Logging level
    if getattr(args, "verbose", False):
        logging.getLogger().setLevel(logging.DEBUG)
    elif getattr(args, "quiet", False):
        logging.getLogger().setLevel(logging.ERROR)

    # B88 mutex bridge — argparse mutex group enforces, but cross-check
    # defensively (callers via main() bypass argparse).
    dry_run_flag = bool(getattr(args, "dry_run", False))
    apply_flag = bool(getattr(args, "apply", False))
    if dry_run_flag and apply_flag:
        print(
            "FATAL: --dry-run and --apply are mutually exclusive.",
            file=sys.stderr,
        )
        return EXIT_FATAL

    # D75 dry-run-default safety: default is DRY-RUN unless --apply.
    is_dry_run = not apply_flag

    registry_id = getattr(args, "registry_id", None)
    if registry_id is None:
        print(
            "FATAL: --registry-id is required.",
            file=sys.stderr,
        )
        return EXIT_FATAL

    snowflake_table = getattr(args, "snowflake_table", None)
    copy_timeout = int(
        getattr(args, "copy_timeout", _DEFAULT_COPY_TIMEOUT_SECONDS)
    )
    json_output = bool(getattr(args, "json_output", False))
    quiet = bool(getattr(args, "quiet", False))
    no_audit_event = bool(getattr(args, "no_audit_event", False))
    actor = getattr(args, "actor", None) or _detect_actor()

    started_at = _now_naive_ms()

    metadata: dict[str, Any] = {
        "event_kind": "invoke",
        "actor": actor,
        "registry_id": int(registry_id),
        "snowflake_table": snowflake_table,
        "copy_timeout_seconds": copy_timeout,
        "dry_run": is_dry_run,
        "rows_copied": None,
        "copy_history_id": None,
        "duration_ms": None,
        "error_class": None,
        "error_message": None,
        "exit_code": EXIT_SUCCESS,
        "started_at": _format_iso_naive_ms(started_at),
        "started_at_dt": started_at,
        "completed_at": None,
    }

    # ---- Dry-run path: don't call M17. Emit preview + audit + exit 0.
    if is_dry_run:
        completed_at = _now_naive_ms()
        metadata["completed_at"] = _format_iso_naive_ms(completed_at)
        metadata["exit_code"] = EXIT_SUCCESS
        audit_event_id = _write_audit_row(
            metadata=metadata,
            status="SUCCESS",
            error_message=None,
            cursor_factory=audit_cursor_factory,
            general_db=general_db,
            skip=no_audit_event,
        )
        if json_output:
            _emit_json(_build_json_payload(metadata, audit_event_id=audit_event_id))
        elif not quiet:
            _emit_human_dry_run(
                registry_id=int(registry_id),
                snowflake_table=snowflake_table,
                copy_timeout_seconds=copy_timeout,
                audit_event_id=audit_event_id,
            )
        return EXIT_SUCCESS

    # ---- Apply path: invoke M17 copy_parquet_to_snowflake.
    if copy_fn is None:
        try:
            copy_fn = _get_copy_parquet_to_snowflake()
        except PipelineFatalError as exc:
            completed_at = _now_naive_ms()
            metadata["completed_at"] = _format_iso_naive_ms(completed_at)
            metadata["exit_code"] = EXIT_FATAL
            metadata["error_class"] = type(exc).__name__
            metadata["error_message"] = str(exc)
            audit_event_id = _write_audit_row(
                metadata=metadata,
                status="FAILED",
                error_message=str(exc)[:4000],
                cursor_factory=audit_cursor_factory,
                general_db=general_db,
                skip=no_audit_event,
            )
            if json_output:
                _emit_json(
                    _build_json_payload(metadata, audit_event_id=audit_event_id)
                )
            elif not quiet:
                _emit_human_failure(
                    registry_id=int(registry_id),
                    error_class=type(exc).__name__,
                    error_message=str(exc),
                    exit_code=EXIT_FATAL,
                    audit_event_id=audit_event_id,
                )
            return EXIT_FATAL

    try:
        result = copy_fn(
            registry_id=int(registry_id),
            snowflake_table=snowflake_table,
            timeout_seconds=copy_timeout,
        )
    except KeyboardInterrupt:
        # Surface as operational failure — operator interrupted.
        logger.warning("Interrupted by operator")
        completed_at = _now_naive_ms()
        metadata["completed_at"] = _format_iso_naive_ms(completed_at)
        metadata["exit_code"] = EXIT_OPERATIONAL_FAILURE
        metadata["error_class"] = "KeyboardInterrupt"
        metadata["error_message"] = "Operator interrupted"
        audit_event_id = _write_audit_row(
            metadata=metadata,
            status="FAILED",
            error_message="Operator interrupted",
            cursor_factory=audit_cursor_factory,
            general_db=general_db,
            skip=no_audit_event,
        )
        return EXIT_OPERATIONAL_FAILURE
    except Exception as exc:  # noqa: BLE001
        exit_code = _classify_exception(exc)
        completed_at = _now_naive_ms()
        metadata["completed_at"] = _format_iso_naive_ms(completed_at)
        metadata["exit_code"] = exit_code
        metadata["error_class"] = type(exc).__name__
        metadata["error_message"] = str(exc)
        # Log traceback at DEBUG (operator can re-run with --verbose).
        logger.debug("M17 copy_parquet_to_snowflake raised", exc_info=True)
        status_text = (
            "FAILED" if exit_code == EXIT_FATAL else "FAILED"
        )  # both surfaces are non-success at the audit-row layer
        audit_event_id = _write_audit_row(
            metadata=metadata,
            status=status_text,
            error_message=traceback.format_exc()[:4000],
            cursor_factory=audit_cursor_factory,
            general_db=general_db,
            skip=no_audit_event,
        )
        if json_output:
            _emit_json(_build_json_payload(metadata, audit_event_id=audit_event_id))
        elif not quiet:
            _emit_human_failure(
                registry_id=int(registry_id),
                error_class=type(exc).__name__,
                error_message=str(exc),
                exit_code=exit_code,
                audit_event_id=audit_event_id,
            )
        return exit_code

    # ---- Success path ----
    completed_at = _now_naive_ms()
    rows_copied = int(getattr(result, "rows_copied", 0) or 0)
    copy_history_id = str(getattr(result, "copy_history_id", "") or "")
    effective_snowflake_table = str(
        getattr(result, "snowflake_table", "") or (snowflake_table or "")
    )
    duration_ms = int(getattr(result, "duration_ms", 0) or 0)

    metadata["completed_at"] = _format_iso_naive_ms(completed_at)
    metadata["exit_code"] = EXIT_SUCCESS
    metadata["rows_copied"] = rows_copied
    metadata["copy_history_id"] = copy_history_id
    metadata["duration_ms"] = duration_ms
    metadata["snowflake_table"] = effective_snowflake_table or snowflake_table

    audit_event_id = _write_audit_row(
        metadata=metadata,
        status="SUCCESS",
        error_message=None,
        cursor_factory=audit_cursor_factory,
        general_db=general_db,
        skip=no_audit_event,
    )

    if json_output:
        _emit_json(_build_json_payload(metadata, audit_event_id=audit_event_id))
    elif not quiet:
        _emit_human_success(
            registry_id=int(registry_id),
            snowflake_table=effective_snowflake_table or "<unknown>",
            rows_copied=rows_copied,
            copy_history_id=copy_history_id,
            duration_ms=duration_ms,
            audit_event_id=audit_event_id,
        )
    return EXIT_SUCCESS


# ---------------------------------------------------------------------------
# CLI argv entry point
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser per spec + D75 conventions."""
    parser = argparse.ArgumentParser(
        prog="snowflake_copy_smoke",
        description=(
            "End-to-end Snowflake COPY INTO smoke script — wraps M17 "
            "data_load/snowflake_uploader.py::copy_parquet_to_snowflake. "
            "Default is DRY-RUN (no Snowflake credits consumed); pass "
            "--apply to issue a real COPY INTO. Emits one "
            "CLI_SNOWFLAKE_COPY_SMOKE audit row per invocation."
        ),
    )

    parser.add_argument(
        "--registry-id",
        type=int,
        required=True,
        help=(
            "ParquetSnapshotRegistry.RegistryId of the verified row to "
            "replicate. The row's Status MUST be 'verified' (run "
            "tools/parquet_verify.py first if needed). REQUIRED."
        ),
    )
    parser.add_argument(
        "--snowflake-table",
        default=None,
        help=(
            "Override the default 'DATABASE.SCHEMA.TABLE' Snowflake "
            "target. Omit to use the default mapping from "
            "$SNOWFLAKE_DATABASE.$SNOWFLAKE_SCHEMA.<table_name>."
        ),
    )
    parser.add_argument(
        "--copy-timeout",
        type=int,
        default=_DEFAULT_COPY_TIMEOUT_SECONDS,
        help=(
            f"COPY INTO query timeout in seconds. Default: "
            f"{_DEFAULT_COPY_TIMEOUT_SECONDS} (per M17 spec § 7.1)."
        ),
    )
    parser.add_argument(
        "--actor",
        default=None,
        help=(
            "Operator identity (per D75 + D76). One of operator / "
            "automic / pipeline. Auto-detected via TTY / "
            "AUTOMIC_RUN_ID env when omitted."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help=(
            "Emit canonical JSON output (full audit-row Metadata "
            "shape) instead of human summary."
        ),
    )
    parser.add_argument(
        "--no-audit-event",
        action="store_true",
        help=(
            "Skip CLI-level PipelineEventLog write (for testing OR "
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
        help=(
            "Suppress stdout summary (errors still emitted to stderr)."
        ),
    )

    # --apply / --dry-run mutex per B88 (apply opt-in, dry-run default).
    # Default behavior is DRY-RUN since COPY INTO consumes real
    # Snowflake credits (trial-period cost-control).
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Apply: issue a real COPY INTO via M17. CONSUMES SNOWFLAKE "
            "CREDITS. Default is dry-run (no credits)."
        ),
    )
    mode_group.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Explicit dry-run opt-in (redundant — this is the default; "
            "useful for scripting clarity)."
        ),
    )
    return parser


def cli_main(argv: list[str] | None = None) -> int:
    """Argv entry point — argparse + main() + return exit code per D74.

    Parameters
    ----------
    argv:
        Optional argv list (for in-process testing). When ``None``,
        defaults to ``sys.argv[1:]`` via argparse.

    Returns
    -------
    int
        Canonical D74 exit code (0 / 1 / 2).
    """
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # argparse error -> exit 2 (FATAL — caller misuse).
        # --help is exit 0 (argparse default); preserve.
        code = exc.code if isinstance(exc.code, int) else EXIT_FATAL
        if code == 0:
            return EXIT_SUCCESS
        return EXIT_FATAL

    try:
        return int(main(args=args))
    except SystemExit as exc:
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
            f"FATAL: snowflake_copy_smoke unexpected exception:\n{tb[:1000]}",
            file=sys.stderr,
        )
        return EXIT_FATAL


if __name__ == "__main__":
    sys.exit(cli_main())
