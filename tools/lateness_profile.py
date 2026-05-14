"""Round 4 § 3.3 — ``tools/lateness_profile.py``.

Per **Round 4 § 3.3** at ``docs/migration/phase1/04_tools.md`` L577-663
(canonical spec) + **Round 3 § 5.2** ``cdc/lateness_profiler.py``
(M12 — wraps ``profile_lateness()`` per L1143-1148 canonical signature).

CLI wrapper for ``cdc.lateness_profiler.profile_lateness()``. Operator
runs this ad-hoc to measure empirical L_99 lateness (per D11) for a
given ``(source, table)``; the report drives ``UdmTablesList.LookbackDays``
operator-set configuration.

What this tool does
-------------------

1. Parse ``--source`` / ``--table`` (both REQUIRED — the wrapped
   ``profile_lateness()`` requires both per Round 3 § 5.2) +
   ``--window-days`` (default 90 per spec § 3.3) +
   ``--min-sample-days`` (default 30 per spec § 3.3) +
   ``--persist`` (default ON per spec § 3.3 default-True; ``--no-persist``
   suppresses) + ``--recommend-lookback`` (default ON; ``--no-recommend-
   lookback`` suppresses) + canonical D75 args (``--actor`` /
   ``--justification`` / ``--json`` / ``--verbose`` / ``--quiet`` /
   ``--no-audit-event``).
2. Invoke ``profile_lateness(*, source_name, table_name, window_days,
   min_sample_days)`` per Round 3 § 5.2 keyword-only signature, returning
   ``LatenessReport``.
3. If ``--persist`` (default), invoke
   ``persist_lateness_report(report, ...)`` to append a row to
   ``General.ops.LatenessProfile`` per spec § 3.3 "Optional".
4. Render stdout per spec § 3.3 L646-657 (human-readable table OR JSON
   via ``--json``).
5. Write ONE ``CLI_LATENESS_PROFILE`` audit row to
   ``General.ops.PipelineEventLog`` per D76 — ``Metadata`` JSON contains
   the report payload + ``actor`` / ``justification`` / ``dry_run`` (
   always False — read-only tool per spec § 1.2) / ``persist`` /
   ``exit_code`` / ``event_kind='lateness_profile'``.
6. Exit 0 / 1 / 2 per D74 + spec § 3.3 L659-662.

Spec § 3.3 "Idempotency" — this tool is read-only on historical data
(per Round 3 § 5.2 docstring: "read-only on historical data; report is
reproducible from same input window"); ``--persist`` is the only side
effect and is append-only (D26 audit posture).

CLI contract (per spec § 3.3 L632-643)
--------------------------------------

::

    # Default 90-day window (spec § 3.3 L634-635)
    python3 tools/lateness_profile.py --source DNA --table ACCT

    # Custom window for large tables with longer history (L637-638)
    python3 tools/lateness_profile.py --source DNA --table CARDTXN \\
        --window-days 180

    # Force run with lower minimum sample threshold (L640-641)
    python3 tools/lateness_profile.py --source DNA --table NEWLOOKBACK \\
        --min-sample-days 14

    # JSON output for downstream consumption
    python3 tools/lateness_profile.py --source DNA --table ACCT --json

Exit codes (per D74 + spec § 3.3 L659-662)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* **0** — report produced successfully
* **1** — connection / vault retryable error during query
  (``ExtractionStateUnavailable`` ⇒ ``PipelineRetryableError`` per D68);
  operator can re-run; not page-able
* **2** — fatal: ``InsufficientHistory`` (Round 3 § 5.2
  ``PipelineFatalError`` per § 1.8 mapping; operator re-runs when more
  data accumulates AND ``min_sample_days`` threshold met) OR config /
  connection setup failure OR unexpected exception

Audit row (per D76 + spec § 3.3 L617)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* ``General.ops.PipelineEventLog.EventType = 'CLI_LATENESS_PROFILE'``
  (one of the 11 R4 canonical CLI_* family values per CLAUDE.md)
* ONE row per INVOCATION
* ``Status in {SUCCESS, FAILED}`` (SUCCESS for exit 0; FAILED for exit
  1 / 2)
* ``Metadata`` JSON shape::

    {
        "event_kind": "lateness_profile",
        "actor": "<operator>",
        "justification": "<text or null>",
        "source_name": "<S>",
        "table_name": "<T>",
        "window_days": <int>,
        "min_sample_days": <int>,
        "persist": <bool>,
        "recommend_lookback": <bool>,
        "exit_code": <int>,
        "report": {
            "source_name": "...",
            "table_name": "...",
            "window_start": "<ISO-8601 date>",
            "window_end": "<ISO-8601 date>",
            "sample_count": N,
            "p50_days": <float>, "p90_days": <float>,
            "p95_days": <float>, "p99_days": <float>,
            "max_observed_days": <int>,
            "confidence": "high|medium|low",
            "recommended_lookback_days": <int>,
        },
        "profile_id": <int or null>,        # ProfileId when --persist
        "started_at": "<ISO-8601 naive-UTC>",
        "completed_at": "<ISO-8601 naive-UTC>"
    }

Classification per ``udm-execution-classifier`` skill
-----------------------------------------------------

* **Trigger**: PRIMARY Manual (operator ad-hoc CLI per spec § 3.3 L621
  "operator ad-hoc"). SECONDARY future ``JOB_LATENESS_PROFILE_WEEKLY``
  BACKLOG candidate per spec § 3.3 L622 (not in Round 2 § 5.1 frozen
  inventory).
* **Frequency**: PRIMARY Manual-Adhoc; SECONDARY Scheduled-Recurring
  (deferred to Round 6).
* **Idempotency**: YES per spec § 3.3 L624-627 — multi-call returns
  identical ``LatenessReport`` for identical inputs. ``--persist`` writes
  are append-only (multiple invocations produce trend rows; intentional
  per D26).
* **Concurrency**: stateless per spec § 3.3 L631; ``--workers`` NOT
  supported (single ``profile_lateness()`` call per invocation).
* **Audit-row family**: ``CLI_LATENESS_PROFILE`` per D76 + CLAUDE.md
  CLI_* family registry (one of the 11 R4 canonical values).
* **Routing**: PRIMARY tracker ``ONE_OFF_SCRIPTS.md`` operator tools
  table (manual ad-hoc invocations).

D-numbers consumed
------------------

D11 (empirical L_99 lookback — the canonical decision this tool
implements per spec § 3.3 L579),
D26 (append-only audit — ``LatenessProfile`` INSERT is append-only),
D67 (Tier 0 smoke discipline),
D68 (error class hierarchy — ``InsufficientHistory`` ⇒
``PipelineFatalError`` exit 2; ``ExtractionStateUnavailable`` ⇒
``PipelineRetryableError`` exit 1),
D74-D77 (CLI exit-code contract + argument naming + audit-row contract
+ Tier 0 7-canonical-assertion scaffold per spec § 3.3 L664),
D92 (forward-only additive — new tool; no rename of existing API).

Canonical references cited (per Pitfall #9.l producer self-check)
-----------------------------------------------------------------

* Round 3 § 5.2 ``profile_lateness()`` signature (KEYWORD-ONLY per
  canonical L1143-1148):
  ``profile_lateness(*, source_name, table_name, window_days,
  min_sample_days) -> LatenessReport``. The trailing-``*`` is
  load-bearing; positional invocation would TypeError. The task brief
  showed the four arg names without the ``*`` — verified against the
  canonical at ``cdc/lateness_profiler.py:profile_lateness`` and matched.
* Round 3 § 5.2 ``LatenessReport`` dataclass fields per
  ``cdc/lateness_profiler.py``:
  ``source_name`` / ``table_name`` / ``window_start`` (``date``) /
  ``window_end`` (``date``) / ``sample_count`` (``int``) /
  ``p50_days`` (``float``) / ``p90_days`` (``float``) /
  ``p95_days`` (``float``) / ``p99_days`` (``float``) /
  ``max_observed_days`` (``int``) / ``confidence`` (``str``,
  ``'high'|'medium'|'low'``) / ``as_of`` (``datetime``).
* Round 3 § 5.2 ``persist_lateness_report()`` signature:
  ``persist_lateness_report(report, *, business_date_column,
  last_modified_column, safety_factor, current_configured_lookback,
  previous_p99) -> int (ProfileId)``.
* Round 1 ``LatenessProfile`` table (``phase1/01_database_schema.md``
  § 10): canonical name is ``General.ops.LatenessProfile`` — NOT
  ``LatenessProfileLog`` (Pitfall #9 cross-table column-name lift
  caught at Round 3 cycle 4 per spec § 3.3 L619).
* CLI conventions: ``phase1/04_tools.md`` § 1.4 (canonical args) +
  § 1.7 (invocation-pattern heuristic) + § 1.8 (exit-code mapping) +
  § 1.9 (boilerplate template).

See also
--------

* ``cdc/lateness_profiler.py`` — wrapped module (M12 build).
* ``utils/errors.py`` — ``InsufficientHistory`` /
  ``ExtractionStateUnavailable`` canonical exception classes per D68
  (B85 closure; B228 canonical surface).
* ``tools/measure_lateness.py`` — adjacent Tool 14 (different module
  wrap — wraps ``data_load.lateness_measurement.measure_lateness()``);
  this tool wraps a DIFFERENT module (``cdc.lateness_profiler``) per
  spec § 3.3 L580.
* ``tools/enforce_retention.py`` / ``tools/log_retention_cleanup.py`` —
  sibling Round 4 R4 tools; this tool follows the same author pattern
  (Tier 0-friendly structure; canonical exception imports; argparse
  scaffold).
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
import traceback
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

# Project root on sys.path so we can reach cdc/utils/data_load.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Canonical exception classes from utils.errors (B85 + B228 canonical
# surface per D68). The wrapped module raises these from utils.errors;
# importing here lets the CLI catch them in main() with the right
# subclass-aware semantics.
try:
    from utils.errors import (  # noqa: E402
        ExtractionStateUnavailable,
        InsufficientHistory,
    )
except ImportError:
    # Defensive fallback — define stand-ins so the tool still imports
    # when utils.errors hasn't been authored yet (parallels the
    # data_load._exceptions fallback in tools/enforce_retention.py).
    import importlib.util as _importlib_util  # noqa: E402

    _err_path = Path(__file__).resolve().parent.parent / "utils" / "errors.py"
    if _err_path.exists():
        _spec = _importlib_util.spec_from_file_location(
            "utils.errors_lateness_profile", _err_path
        )
        _err_mod = _importlib_util.module_from_spec(_spec)
        _spec.loader.exec_module(_err_mod)
        InsufficientHistory = _err_mod.InsufficientHistory
        ExtractionStateUnavailable = _err_mod.ExtractionStateUnavailable
    else:
        class InsufficientHistory(Exception):  # type: ignore[no-redef]
            """Stand-in until utils.errors.InsufficientHistory is authored."""

        class ExtractionStateUnavailable(Exception):  # type: ignore[no-redef]
            """Stand-in until utils.errors.ExtractionStateUnavailable is authored."""


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exit-code constants (per D74 + spec § 3.3 L659-662)
# ---------------------------------------------------------------------------

EXIT_SUCCESS = 0
EXIT_WARNING = 1
EXIT_FATAL = 2

# D76 EventType registered in CLAUDE.md CLI_* family registry (one of the
# 11 R4 canonical values per CLI_* family at spec § 3.3 L617).
EVENT_TYPE = "CLI_LATENESS_PROFILE"


# ---------------------------------------------------------------------------
# Actor detection (per § 1.7 invocation pattern heuristic)
# ---------------------------------------------------------------------------


def _detect_actor() -> str:
    """Resolve ``--actor`` default per spec § 1.7 heuristic.

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
# profile_lateness() resolver — late-bound so tests can mock the wrapped module
# ---------------------------------------------------------------------------


def _resolve_profile_lateness() -> Callable:
    """Return the live ``cdc.lateness_profiler.profile_lateness`` callable.

    Resolved at CALL TIME so test patches of ``sys.modules`` after tool
    import are honored. Mirrors the resolver-pattern in
    ``tools/enforce_retention.py::_resolve_default_vault_cursor_factory``.
    """
    try:
        from cdc.lateness_profiler import profile_lateness  # type: ignore
    except ImportError as exc:
        raise ExtractionStateUnavailable(
            "cdc.lateness_profiler.profile_lateness import failed; module "
            "may not be deployed yet",
            metadata={"error": str(exc)},
        ) from exc
    return profile_lateness


def _resolve_persist_lateness_report() -> Callable:
    """Return the live ``cdc.lateness_profiler.persist_lateness_report`` callable.

    Same late-binding pattern as ``_resolve_profile_lateness()``.
    """
    try:
        from cdc.lateness_profiler import persist_lateness_report  # type: ignore
    except ImportError as exc:
        raise ExtractionStateUnavailable(
            "cdc.lateness_profiler.persist_lateness_report import failed",
            metadata={"error": str(exc)},
        ) from exc
    return persist_lateness_report


# ---------------------------------------------------------------------------
# Report -> dict serializer (for audit row + JSON output)
# ---------------------------------------------------------------------------


def _recommended_lookback_days(p99_days: float) -> int:
    """Compute the recommended ``LookbackDays`` value per spec § 3.3 L615.

    Per spec: ``recommended LookbackDays value = ceil(p99) + 1`` (safety
    margin). Matches the Round 3 § 5.2 docstring convention
    ``LookbackDays = ceil(p99_days) + safety_margin`` (typically + 1).
    """
    return int(math.ceil(p99_days)) + 1


def _report_to_dict(report: Any, *, recommend_lookback: bool) -> dict[str, Any]:
    """Serialize a ``LatenessReport`` dataclass to JSON-safe dict.

    Used for both ``--json`` stdout and the audit-row Metadata payload.
    All datetime / date fields are ISO-8601 strings (naive-UTC for
    datetimes per SCD2-P1-f / CDC-NOW-MS invariant).
    """
    payload: dict[str, Any] = {
        "source_name": getattr(report, "source_name", None),
        "table_name": getattr(report, "table_name", None),
        "window_start": _date_to_iso(getattr(report, "window_start", None)),
        "window_end": _date_to_iso(getattr(report, "window_end", None)),
        "sample_count": int(getattr(report, "sample_count", 0)),
        "p50_days": float(getattr(report, "p50_days", 0.0)),
        "p90_days": float(getattr(report, "p90_days", 0.0)),
        "p95_days": float(getattr(report, "p95_days", 0.0)),
        "p99_days": float(getattr(report, "p99_days", 0.0)),
        "max_observed_days": int(getattr(report, "max_observed_days", 0)),
        "confidence": getattr(report, "confidence", "medium"),
        "as_of": _datetime_to_iso(getattr(report, "as_of", None)),
    }
    if recommend_lookback:
        payload["recommended_lookback_days"] = _recommended_lookback_days(
            payload["p99_days"]
        )
    return payload


def _date_to_iso(value: Any) -> str | None:
    """ISO-8601 string for a ``date`` (or ``datetime`` truncated to date)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _datetime_to_iso(value: Any) -> str | None:
    """ISO-8601 string for a naive datetime (no tz suffix)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        naive = value.replace(tzinfo=None) if value.tzinfo is not None else value
        return naive.strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


# ---------------------------------------------------------------------------
# Audit-row writer (one CLI_LATENESS_PROFILE row per invocation)
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
    """INSERT one ``CLI_LATENESS_PROFILE`` row into PipelineEventLog.

    Per D76 + spec § 3.3 L617. ONE row per invocation. Best-effort:
    failures are logged but do not affect the verdict exit code
    (parity with B188 / B189 / B190 / B218 audit-row patterns).

    Returns the IDENTITY of the inserted row via SCOPE_IDENTITY() so the
    JSON ``audit_event_id`` key can be populated. Returns None on
    failure (the JSON key is then null).

    When ``skip=True`` (``--no-audit-event``), returns None immediately
    without writing.
    """
    if skip:
        return None

    metadata_json = json.dumps(metadata, separators=(",", ":"), default=str)
    event_detail = (
        f"lateness_profile / "
        f"source={metadata.get('source_name')} "
        f"table={metadata.get('table_name')} "
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
                f"        ?, ?, ?, ?, ?, SYSUTCDATETIME(), ?, ?, ?); "
                f"SELECT CAST(SCOPE_IDENTITY() AS BIGINT) AS AuditEventId;",
                metadata.get("table_name"),
                metadata.get("source_name"),
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
        logger.exception("Failed to write CLI_LATENESS_PROFILE audit row")
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
    report_dict: dict[str, Any],
    recommend_lookback: bool,
    window_days: int,
) -> None:
    """Print the spec § 3.3 L646-657 stdout block.

    Example (canonical from spec)::

        Lateness profile for DNA.ACCT (window: 2026-02-09 -> 2026-05-10,
            90 days, 87 samples)
          p50  : 0.2 days
          p90  : 0.8 days
          p95  : 1.3 days
          p99  : 2.7 days
          max  : 4.1 days
        Recommended UdmTablesList.LookbackDays = 4 (ceil(p99) + 1 safety
            margin)
    """
    source_name = report_dict.get("source_name", "")
    table_name = report_dict.get("table_name", "")
    window_start = report_dict.get("window_start", "")
    window_end = report_dict.get("window_end", "")
    sample_count = report_dict.get("sample_count", 0)
    p50 = report_dict.get("p50_days", 0.0)
    p90 = report_dict.get("p90_days", 0.0)
    p95 = report_dict.get("p95_days", 0.0)
    p99 = report_dict.get("p99_days", 0.0)
    max_obs = report_dict.get("max_observed_days", 0)
    confidence = report_dict.get("confidence", "medium")

    print(
        f"Lateness profile for {source_name}.{table_name} "
        f"(window: {window_start} -> {window_end}, {window_days} days, "
        f"{sample_count:,} samples, confidence={confidence})"
    )
    print(f"  p50  : {p50:.2f} days")
    print(f"  p90  : {p90:.2f} days")
    print(f"  p95  : {p95:.2f} days")
    print(f"  p99  : {p99:.2f} days")
    print(f"  max  : {max_obs:.1f} days")
    if recommend_lookback:
        recommended = _recommended_lookback_days(p99)
        print(
            f"Recommended UdmTablesList.LookbackDays = {recommended} "
            f"(ceil(p99) + 1 safety margin)"
        )


def _emit_json(payload: dict) -> None:
    """Emit canonical JSON payload per spec § 3.3 L658.

    Shape: ``{source_name, table_name, window_start, window_end,
    sample_count, p50_days, p90_days, p95_days, p99_days,
    max_observed_days, confidence, as_of, recommended_lookback_days?,
    profile_id?, audit_event_id?}``. ``recommended_lookback_days`` is
    present unless ``--no-recommend-lookback`` set. ``profile_id`` is the
    ``LatenessProfile.ProfileId`` IDENTITY when ``--persist``, else null.
    ``audit_event_id`` is the SCOPE_IDENTITY() of the
    ``CLI_LATENESS_PROFILE`` row, or null on write failure /
    ``--no-audit-event``.
    """
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


# ---------------------------------------------------------------------------
# Top-level main() — programmatic entry point
# ---------------------------------------------------------------------------


def main(
    *,
    source: str,
    table: str,
    actor: str,
    window_days: int = 90,
    min_sample_days: int = 30,
    persist: bool = True,
    recommend_lookback: bool = True,
    json_output: bool = False,
    verbose: bool = False,
    quiet: bool = False,
    justification: str | None = None,
    no_audit_event: bool = False,
    # ---- Injection hooks (test path) ----
    profile_lateness_fn: Callable | None = None,
    persist_lateness_report_fn: Callable | None = None,
    audit_cursor_factory: Callable | None = None,
    general_db: str | None = None,
) -> dict:
    """Programmatic entry — invokes ``profile_lateness()`` per D11.

    Returns a dict matching the D76 audit-row Metadata shape (see module
    docstring for the canonical schema). Exit-code derivation per D74 +
    spec § 3.3 L659-662:

    * 0: report produced successfully
    * 1: ``ExtractionStateUnavailable`` retryable error during query OR
      connection / vault retryable failure
    * 2: fatal — ``InsufficientHistory`` / config / unexpected exception

    Parameters
    ----------
    source:
        SourceName filter (REQUIRED — wrapped ``profile_lateness()``
        requires a non-empty source_name per Round 3 § 5.2).
    table:
        TableName filter (REQUIRED — same as source).
    actor:
        Operator identity (per D75 + D76). REQUIRED.
    window_days:
        Maps to Round 3 § 5.2 ``window_days`` parameter. Default 90 per
        spec § 3.3.
    min_sample_days:
        Maps to Round 3 § 5.2 ``min_sample_days``. Default 30 per spec
        § 3.3.
    persist:
        When True (default per spec § 3.3 ``--persist`` default-True),
        invoke ``persist_lateness_report()`` to append a row to
        ``General.ops.LatenessProfile``. When False (``--no-persist``),
        skip.
    recommend_lookback:
        Include "recommended LookbackDays = ceil(p99) + 1" in stdout
        + JSON payload. Default True per spec § 3.3.
    justification:
        Operator justification recorded in audit-row Metadata per D75.
    no_audit_event:
        When True, skip the CLI-level PipelineEventLog write (pipeline-
        programmatic callers per D75 + D76).
    profile_lateness_fn / persist_lateness_report_fn / audit_cursor_factory:
        Test-injection hooks. Defaults resolve to live infrastructure.
    general_db:
        Override the canonical General DB name (defaults to
        ``utils.configuration.GENERAL_DB``, fallback ``'General'``).
    """
    started_at = datetime.now(timezone.utc).replace(tzinfo=None)

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
        "event_kind": "lateness_profile",
        "actor": actor,
        "justification": justification,
        "source_name": source,
        "table_name": table,
        "window_days": window_days,
        "min_sample_days": min_sample_days,
        "persist": persist,
        "recommend_lookback": recommend_lookback,
        "dry_run": False,  # read-only tool — always False per spec § 1.2
        "exit_code": EXIT_SUCCESS,
        "report": None,
        "profile_id": None,
        "started_at": started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "started_at_dt": started_at,
        "completed_at": None,
        "audit_event_id": None,
        "errors": [],
    }

    # ---- Validate inputs at the CLI boundary ----
    if not source or not isinstance(source, str):
        result["exit_code"] = EXIT_FATAL
        result["error_type"] = "InvalidArgs"
        result["error_message"] = "--source is required and must be non-empty"
        result["errors"].append(result["error_message"])
        result["completed_at"] = datetime.now(
            timezone.utc
        ).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%SZ")
        if not quiet:
            print(f"FATAL: {result['error_message']}", file=sys.stderr)
        result["audit_event_id"] = _write_audit_row(
            result,
            status="FAILED",
            error_message=result["error_message"],
            cursor_factory=audit_cursor_factory,
            general_db=general_db,
            skip=no_audit_event,
        )
        return result

    if not table or not isinstance(table, str):
        result["exit_code"] = EXIT_FATAL
        result["error_type"] = "InvalidArgs"
        result["error_message"] = "--table is required and must be non-empty"
        result["errors"].append(result["error_message"])
        result["completed_at"] = datetime.now(
            timezone.utc
        ).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%SZ")
        if not quiet:
            print(f"FATAL: {result['error_message']}", file=sys.stderr)
        result["audit_event_id"] = _write_audit_row(
            result,
            status="FAILED",
            error_message=result["error_message"],
            cursor_factory=audit_cursor_factory,
            general_db=general_db,
            skip=no_audit_event,
        )
        return result

    # ---- Resolve profile_lateness callable ----
    if profile_lateness_fn is None:
        try:
            profile_lateness_fn = _resolve_profile_lateness()
        except ExtractionStateUnavailable as exc:
            # Module-import failure — treat as retryable per D68.
            result["exit_code"] = EXIT_WARNING
            result["error_type"] = "ExtractionStateUnavailable"
            result["error_message"] = str(exc)[:4000]
            result["errors"].append(f"ExtractionStateUnavailable: {exc}")
            logger.warning("profile_lateness resolver failed: %s", exc)
            if not quiet:
                print(
                    f"WARNING: profile_lateness module unavailable: {exc}",
                    file=sys.stderr,
                )
            result["completed_at"] = datetime.now(
                timezone.utc
            ).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%SZ")
            result["audit_event_id"] = _write_audit_row(
                result,
                status="FAILED",
                error_message=str(exc)[:4000],
                cursor_factory=audit_cursor_factory,
                general_db=general_db,
                skip=no_audit_event,
            )
            return result

    # ---- Invoke profile_lateness() per Round 3 § 5.2 keyword-only sig ----
    try:
        report = profile_lateness_fn(
            source_name=source,
            table_name=table,
            window_days=window_days,
            min_sample_days=min_sample_days,
        )
    except InsufficientHistory as exc:
        # PipelineFatalError per Round 3 § 5.2 -> exit 2 per § 1.8 +
        # spec § 3.3 L660-662.
        result["exit_code"] = EXIT_FATAL
        result["error_type"] = "InsufficientHistory"
        msg = str(exc)
        # Stderr message per spec § 3.3 L629:
        # "needs more history; run when >= N days of SUCCESS data
        # available".
        helpful = (
            f"InsufficientHistory: {msg}. "
            f"needs more history; run when >= {min_sample_days} days of "
            f"SUCCESS data available."
        )
        result["error_message"] = helpful[:4000]
        result["errors"].append(helpful)
        logger.error("InsufficientHistory: %s", msg)
        if not quiet:
            print(f"FATAL: {helpful}", file=sys.stderr)
    except ExtractionStateUnavailable as exc:
        # PipelineRetryableError per Round 3 § 5.2 -> exit 1.
        result["exit_code"] = EXIT_WARNING
        result["error_type"] = "ExtractionStateUnavailable"
        result["error_message"] = str(exc)[:4000]
        result["errors"].append(f"ExtractionStateUnavailable: {exc}")
        logger.warning("ExtractionStateUnavailable: %s", exc)
        if not quiet:
            print(
                f"WARNING: connection issue (operator can re-run): {exc}",
                file=sys.stderr,
            )
    except Exception as exc:  # noqa: BLE001
        # Unexpected exception -> exit 2 per § 1.8 mapping (bare-except
        # branch is FATAL per § 1.8 wrapper).
        result["exit_code"] = EXIT_FATAL
        result["error_type"] = type(exc).__name__
        result["error_message"] = str(exc)[:4000]
        result["errors"].append(f"{type(exc).__name__}: {exc}")
        logger.exception("Unexpected error during profile_lateness invocation")
        if not quiet:
            print(
                f"FATAL: unexpected error during profile_lateness: {exc}",
                file=sys.stderr,
            )
    else:
        # Happy path — serialize report + maybe persist.
        report_dict = _report_to_dict(
            report,
            recommend_lookback=recommend_lookback,
        )
        result["report"] = report_dict

        # ---- Optional --persist branch ----
        if persist:
            try:
                if persist_lateness_report_fn is None:
                    persist_lateness_report_fn = _resolve_persist_lateness_report()
                profile_id = persist_lateness_report_fn(report)
                result["profile_id"] = (
                    int(profile_id) if profile_id is not None else None
                )
            except ExtractionStateUnavailable as exc:
                # Persistence is best-effort — warn but don't fail the
                # report. Operator can re-run with --persist later.
                logger.warning(
                    "LatenessProfile persistence failed (non-fatal): %s", exc
                )
                result["errors"].append(
                    f"persist_lateness_report unavailable: {exc}"
                )
            except Exception as exc:  # noqa: BLE001
                # Defensive — same posture as ExtractionStateUnavailable.
                logger.warning(
                    "LatenessProfile persistence raised unexpected (non-fatal): %s",
                    exc,
                )
                result["errors"].append(
                    f"persist_lateness_report unexpected: "
                    f"{type(exc).__name__}: {exc}"
                )

        # ---- Render stdout ----
        if json_output:
            json_payload = dict(report_dict)
            json_payload["profile_id"] = result["profile_id"]
        elif not quiet:
            _emit_human_summary(
                report_dict=report_dict,
                recommend_lookback=recommend_lookback,
                window_days=window_days,
            )
        else:
            json_payload = None

    result["completed_at"] = datetime.now(
        timezone.utc
    ).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%SZ")

    # ---- Invocation-level audit row (D76 — ONE per invocation) ----
    status = "SUCCESS" if result["exit_code"] == EXIT_SUCCESS else "FAILED"
    audit_event_id = _write_audit_row(
        result,
        status=status,
        error_message=result.get("error_message"),
        cursor_factory=audit_cursor_factory,
        general_db=general_db,
        skip=no_audit_event,
    )
    result["audit_event_id"] = audit_event_id

    # ---- Render JSON output AFTER audit_event_id is known ----
    if (
        json_output
        and not quiet
        and result["exit_code"] == EXIT_SUCCESS
        and result["report"] is not None
    ):
        json_payload = dict(result["report"])
        json_payload["profile_id"] = result["profile_id"]
        json_payload["audit_event_id"] = result["audit_event_id"]
        _emit_json(json_payload)
    elif json_output and not quiet and result["exit_code"] != EXIT_SUCCESS:
        # On failure paths, emit a minimal JSON envelope so machine
        # consumers can still parse (per spec § 3.3 L658 contract).
        failure_payload = {
            "source_name": source,
            "table_name": table,
            "exit_code": result["exit_code"],
            "error_type": result.get("error_type"),
            "error_message": result.get("error_message"),
            "audit_event_id": result["audit_event_id"],
        }
        _emit_json(failure_payload)

    return result


# ---------------------------------------------------------------------------
# CLI argv entry point
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    """Alias for :func:`_build_parser` — Tier 0 scaffold contract."""
    return _build_parser()


def _build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser per spec § 3.3 + § 1.4 canonical args.

    Per Pitfall #9.b invented-parameter rule (HANDOFF §8): this parser
    accepts ONLY the args documented in spec § 3.3 L645-651. No
    ``--registry-id`` / ``--archive-location`` / ``--cycle`` etc. (those
    belong to other tools per spec § 3.1 / § 3.6).
    """
    parser = argparse.ArgumentParser(
        description=(
            "CLI wrapper for cdc/lateness_profiler.py per Round 4 § 3.3. "
            "Computes empirical L_99 lateness percentiles for one "
            "(source, table) per D11; the report drives "
            "UdmTablesList.LookbackDays. Emits one CLI_LATENESS_PROFILE "
            "audit row per invocation."
        ),
    )

    # ---- Spec § 3.3 tool-specific args (canonical L645-651) ----
    parser.add_argument(
        "--source",
        required=True,
        help=(
            "REQUIRED. SourceName filter per spec § 1.4 + § 3.3. "
            "E.g. 'DNA', 'CCM', 'EPICOR'."
        ),
    )
    parser.add_argument(
        "--table",
        required=True,
        help=(
            "REQUIRED. TableName filter per spec § 1.4 + § 3.3. "
            "E.g. 'ACCT', 'CARDTXN'."
        ),
    )
    parser.add_argument(
        "--window-days",
        type=int,
        default=90,
        help=(
            "Trailing historical window in days per spec § 3.3 L647 + "
            "Round 3 § 5.2 ``window_days`` parameter. Default 90."
        ),
    )
    parser.add_argument(
        "--min-sample-days",
        type=int,
        default=30,
        help=(
            "Minimum SUCCESS-row sample threshold before percentiles are "
            "computed (Round 3 § 5.2 ``min_sample_days``). Default 30 "
            "per spec § 3.3 L648. Below this, InsufficientHistory raises."
        ),
    )

    # ---- --persist / --no-persist mutex (default ON per spec § 3.3 L649) ----
    persist_group = parser.add_mutually_exclusive_group()
    persist_group.add_argument(
        "--persist",
        action="store_true",
        default=True,
        dest="persist",
        help=(
            "Write a row to General.ops.LatenessProfile for trend tracking "
            "(default ON per spec § 3.3 L649)."
        ),
    )
    persist_group.add_argument(
        "--no-persist",
        action="store_false",
        dest="persist",
        help=(
            "Suppress LatenessProfile INSERT (spec § 3.3 L649 "
            "``--no-persist suppresses``)."
        ),
    )

    # ---- --recommend-lookback / --no-recommend-lookback (default ON per spec L650) ----
    recommend_group = parser.add_mutually_exclusive_group()
    recommend_group.add_argument(
        "--recommend-lookback",
        action="store_true",
        default=True,
        dest="recommend_lookback",
        help=(
            "Include 'recommended LookbackDays = ceil(p99) + 1' in stdout. "
            "Default ON per spec § 3.3 L650."
        ),
    )
    recommend_group.add_argument(
        "--no-recommend-lookback",
        action="store_false",
        dest="recommend_lookback",
        help="Suppress the recommendation line.",
    )

    # ---- D75 canonical args (per spec § 1.4) ----
    parser.add_argument(
        "--actor",
        default=None,
        help=(
            "Operator identity (per D75 + D76). One of operator / automic "
            "/ pipeline / reconciliation. Auto-detected via TTY / "
            "AUTOMIC_RUN_ID env when omitted."
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
            "Emit canonical JSON output per spec § 3.3 L658 instead of "
            "human summary."
        ),
    )
    parser.add_argument(
        "--no-audit-event",
        action="store_true",
        dest="no_audit_event",
        help=(
            "Skip the CLI-level PipelineEventLog write (pipeline-"
            "programmatic callers per D76)."
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


def cli_main() -> int:
    """Argv entry point — argparse + main() + return exit code per D74.

    Exit codes (always one of 0 / 1 / 2 per D74 + spec § 3.3 L659-662):
        - 0: report produced successfully
        - 1: ExtractionStateUnavailable retryable / connection failure
        - 2: fatal (InsufficientHistory / config / unexpected exception)
    """
    parser = _build_parser()
    args = parser.parse_args()

    actor = args.actor or _detect_actor()

    try:
        result = main(
            source=args.source,
            table=args.table,
            actor=actor,
            window_days=args.window_days,
            min_sample_days=args.min_sample_days,
            persist=args.persist,
            recommend_lookback=args.recommend_lookback,
            json_output=args.json_output,
            verbose=args.verbose,
            quiet=args.quiet,
            justification=args.justification,
            no_audit_event=args.no_audit_event,
        )
    except SystemExit as exc:
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
            f"FATAL: lateness_profile unexpected exception:\n{tb[:1000]}",
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
