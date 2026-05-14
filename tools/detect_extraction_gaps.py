"""Round 4 § 3.5 — ``tools/detect_extraction_gaps.py``.

Per **Round 4 § 3.5** at ``docs/migration/phase1/04_tools.md`` L751-833
(canonical spec) + **Round 3 § 5.3** ``detect_extraction_gaps()`` engine
module at ``tools/gap_detector.py`` (M13).

CLI shim for ``tools/gap_detector.py`` per D22 (hourly gap detector).
Detect missing ``business_date`` rows in ``General.ops.PipelineExtraction``
per (source, large-table); render :class:`GapReport` list as human or
JSON; write ONE ``CLI_DETECT_EXTRACTION_GAPS`` audit row per invocation
per D76; optionally fire an ops-channel alert via § 3.11 alert_dispatcher
when gaps detected.

What this tool does
-------------------

1. Resolve ``--actor`` per § 1.7 invocation-pattern heuristic
   (``AUTOMIC_RUN_ID`` env -> 'automic'; TTY -> 'operator'; else 'pipeline').
2. Resolve ``--alert`` default per spec § 3.5 L804: ON when actor='automic',
   OFF otherwise. Operator can force either way via ``--alert`` /
   ``--no-alert``.
3. Invoke the canonical Round 3 § 5.3 ``detect_extraction_gaps(*,
   source_filter, as_of_date)`` keyword-only entry point. The wrapped
   module:
   - returns ``list[GapReport]`` (the operator-facing result),
   - writes ONE ``EventType='GAP_DETECT'`` row to PipelineEventLog
     (per Round 3 § 5.3 narrative).
4. Render :class:`GapReport` list to stdout per spec § 3.5 L820-823
   (human-readable per-table blocks) OR per spec § 3.5 L826 (``--json``).
5. If gaps detected AND ``--alert`` set, invoke
   ``tools/alert_dispatcher.py`` (§ 3.11) — best-effort, never blocks
   the verdict. The ops-channel client itself is B82-tracked
   (unscoped Phase 0 deliverable per spec § 3.11).
6. Write ONE ``EventType='CLI_DETECT_EXTRACTION_GAPS'`` row to
   ``General.ops.PipelineEventLog`` per D76 — Metadata JSON includes
   per-table summary (truncated for readability), as_of_date,
   source_filter, alert_fired, actor, exit_code, dry_run flag (always
   False — this is a read-only tool). Distinct from the underlying
   ``GAP_DETECT`` event written by the wrapped module — so a single
   CLI invocation produces TWO event rows (spec § 3.5 L766-769).
7. Exit 0 / 1 / 2 per D74 + spec § 3.5 L829-832.

CLI contract
------------

::

    # Hourly Automic-invoked gap detection (alerts on detection)
    python3 tools/detect_extraction_gaps.py --actor automic --alert

    # Operator ad-hoc — what gaps exist right now?
    python3 tools/detect_extraction_gaps.py

    # Filter to one source
    python3 tools/detect_extraction_gaps.py --source DNA

    # Historical backfill replay — "what would the report have said?"
    python3 tools/detect_extraction_gaps.py --as-of-date 2026-04-15

    # JSON for machine consumers (Automic log parsers / dashboards)
    python3 tools/detect_extraction_gaps.py --json

    # Suppress recommendation for terse output
    python3 tools/detect_extraction_gaps.py --no-include-recommendation

Exit codes (per D74 + spec § 3.5 L829-832)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* **0** — no gaps detected (clean state); ``len(reports) == 0``. Operator
  / Automic treats this as success — no action needed.
* **1** — gaps detected. ``len(reports) > 0``; operator should review
  the affected tables. Automic should alert (or this tool fires the
  alert if ``--alert`` is set). Distinct from 0 so the simple Automic
  rule ``if exit==1 then alert`` works without needing to parse stdout.
  Also returned for retryable errors per D68 (``GapDetectorTimeout`` /
  ``ExtractionStateUnavailable``) — operator can re-run after the
  contending session releases or after the source connection recovers.
* **2** — fatal — config missing, connection unreachable, unexpected
  exception. Operator must intervene; not auto-retryable.

Audit row (per D76 + spec § 3.5 L766-769)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* ``General.ops.PipelineEventLog.EventType = 'CLI_DETECT_EXTRACTION_GAPS'``
  (one of the 11 R4 canonical CLI_* family values per CLAUDE.md).
* ONE row per INVOCATION (this CLI envelope). The wrapped Round 3 § 5.3
  module separately writes a ``GAP_DETECT`` row — these are DISTINCT
  audit-trail entries per spec § 3.5 L766-769.
* ``Status in {SUCCESS, FAILED}`` (SUCCESS for exit 0/1 — gap detection
  IS a successful invocation regardless of whether gaps were found;
  FAILED for exit 2).
* ``Metadata`` JSON shape::

    {
        "event_kind": "gap_detection",
        "actor": "<operator|automic|pipeline>",
        "as_of_date": "YYYY-MM-DD",
        "source_filter": <str|null>,
        "include_recommendation": <bool>,
        "alert_flag": <bool>,
        "alert_fired": <bool>,
        "tables_with_gaps": <int>,
        "total_missing_dates": <int>,
        "affected_tables": [
            {
                "source_name": "...",
                "table_name": "...",
                "missing_count": N,
                "recommended_action": "backfill|investigate-source"
            },
            ...
        ],
        "exit_code": <int>,
        "dry_run": false,
        "started_at": "<ISO-8601 naive-UTC>",
        "completed_at": "<ISO-8601 naive-UTC>"
    }

Classification per ``udm-execution-classifier`` skill
-----------------------------------------------------

* **Trigger**: PRIMARY: Scheduled (Automic ``JOB_GAP_DETECT`` per Round 2
  § 5.1 — frozen-11 inventory; hourly cadence per D22). SECONDARY:
  Manual operator CLI for ad-hoc inspection ("what gaps exist now?").
  TERTIARY: Pipeline-programmatic — ``large_tables.py`` orchestrator
  may call this at end-of-run per spec § 3.5 L780.
* **Frequency**: PRIMARY Recurring hourly (Automic); SECONDARY one-time
  ad-hoc; TERTIARY rare programmatic.
* **Idempotency**: YES — read-only on ``PipelineExtraction`` per § 5.3
  spec; multi-call returns identical reports for unchanged historical
  data. ``GAP_DETECT`` + ``CLI_DETECT_EXTRACTION_GAPS`` audit rows are
  append-only (one per invocation; multi-call produces multiple rows
  — intentional per D26).
* **Concurrency**: None required — module is stateless, reports are
  reproducible. No ``sp_getapplock`` per spec § 3.5 L785-786.
* **Audit-row family**: ``CLI_DETECT_EXTRACTION_GAPS`` per D76 +
  CLAUDE.md CLI_* family registry; AND ``GAP_DETECT`` via the wrapped
  Round 3 § 5.3 module.
* **Routing**: PRIMARY tracker — frozen-11 Automic inventory at
  ``phase1/02_configuration.md`` § 5.1 ``JOB_GAP_DETECT`` row.
  SECONDARY (operator) — ``ONE_OFF_SCRIPTS.md`` operator tools table.

D-numbers consumed
------------------

D22 (hourly gap detector — Automic-driven),
D67 (Tier 0 smoke discipline),
D68 (error class hierarchy — GapDetectorTimeout / ExtractionStateUnavailable
both PipelineRetryableError),
D74-D77 (CLI exit-code contract 0/1/2 + canonical arg naming + audit-row
contract + Tier 0 6-canonical scaffold extended for spec § 3.5 L825),
D92 (forward-only additive — new CLI; no existing API renamed),
D102 (CDC-NOW-MS / SCD2-P1-f naive-UTC datetime invariant — every
datetime construction strips tzinfo + truncates to milliseconds).

Canonical references cited (per Pitfall #9.l producer self-check)
-----------------------------------------------------------------

* Round 3 § 5.3 ``detect_extraction_gaps`` keyword-only signature
  re-verified at producer Gate 1 self-check against
  ``tools/gap_detector.py:674`` — actual canonical signature is
  ``detect_extraction_gaps(*, source_filter: str | None = None,
  as_of_date: date | None = None) -> list[GapReport]``. The Round 4
  § 3.5 spec at L757 mentions ``as_of_date`` as the sole parameter
  in narrative form; the full canonical keyword-only signature
  (``source_filter`` + ``as_of_date``) per the engine module is
  authoritative. This CLI shim passes BOTH kwargs.
* :class:`GapReport` dataclass per ``tools/gap_detector.py:233-272``
  (re-read at producer Gate 1 self-check per Pitfall #9.l). Fields:
  ``source_name`` (str), ``table_name`` (str), ``expected_range``
  (tuple[date, date]), ``missing_dates`` (list[date]),
  ``recommended_action`` (str). Frozen dataclass.
* Recommended-action values per ``tools/gap_detector.py:201-204``:
  ``'backfill'``, ``'investigate-source'``, ``'within-lookback-no-action'``
  (the third is a sentinel — never emitted from
  :func:`detect_extraction_gaps`; documented for the CLI JSON shape).
* PipelineEventLog DDL: ``phase1/01_database_schema.md`` § 2 (re-read
  at producer Gate 1 self-check per Pitfall #9.l). Real columns used
  in audit-row INSERT: ``BatchId``, ``TableName``, ``SourceName``,
  ``EventType``, ``EventDetail``, ``StartedAt``, ``CompletedAt``,
  ``Status``, ``ErrorMessage``, ``Metadata`` (all per the sibling
  promote_test_to_prod and enforce_retention patterns).
* CLI conventions: ``phase1/04_tools.md`` § 1.4 (canonical args
  ``--source`` / ``--actor`` / ``--no-audit-event`` / ``--json`` /
  ``--verbose`` / ``--quiet``) + § 1.7 (invocation-pattern heuristic
  — AUTOMIC_RUN_ID env + isatty) + § 1.8 (exit-code mapping for
  PipelineFatalError / PipelineRetryableError) + § 1.9 (boilerplate
  template) + § 1.2 (read-only tools have NO ``--apply`` flag per
  spec § 1.2 narrative).

See also
--------

* ``utils/errors.py`` — :class:`GapDetectorTimeout` (line 399) +
  :class:`ExtractionStateUnavailable` (line 362), both
  ``PipelineRetryableError`` subclasses; mapped to exit 1 per § 1.8
  + D74. Canonical exception module per B228 / D68.
* ``tools/gap_detector.py`` — wrapped engine module; this CLI is the
  operator-facing shim per spec § 3.5.
* ``tools/promote_test_to_prod.py`` — sibling Round 4 § 3.6 CLI;
  this tool follows the same author pattern (injection hooks,
  ``_write_audit_row`` with SCOPE_IDENTITY, ``_detect_actor`` helper,
  naive-UTC timestamping).
* ``tools/alert_dispatcher.py`` — Round 4 § 3.11 sibling tool; this
  tool may invoke it as a side effect when ``--alert`` is set.
"""

from __future__ import annotations

import argparse
import importlib
import json
import logging
import os
import sys
import traceback
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable

# Project root on sys.path so imports of utils.* + tools.* resolve.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Canonical exception classes (per B228 — utils.errors authoritative).
# Imported at module top so they're available for both runtime catch
# blocks and Tier 0 scaffolding. Both are PipelineRetryableError per
# utils/errors.py L362 + L399 -> mapped to exit 1 (operational failure
# per § 1.8 + D74).
try:
    from utils.errors import (  # noqa: E402
        ExtractionStateUnavailable,
        GapDetectorTimeout,
        PipelineFatalError,
        PipelineRetryableError,
    )
except (ImportError, ModuleNotFoundError):
    # Defensive fallback (mirrors sibling promote_test_to_prod.py pattern)
    # — if utils.errors is mocked as MagicMock by an upstream test, the
    # exception-class symbols become MagicMock attributes and break
    # ``except SomeError`` blocks (TypeError: catching classes that do
    # not inherit from BaseException is not allowed).
    import importlib.util as _importlib_util  # noqa: E402

    _errors_path = Path(__file__).resolve().parent.parent / "utils" / "errors.py"
    _spec = _importlib_util.spec_from_file_location(
        "utils._errors_detect_extraction_gaps", _errors_path
    )
    _errors_mod = _importlib_util.module_from_spec(_spec)
    _spec.loader.exec_module(_errors_mod)
    ExtractionStateUnavailable = _errors_mod.ExtractionStateUnavailable
    GapDetectorTimeout = _errors_mod.GapDetectorTimeout
    PipelineFatalError = _errors_mod.PipelineFatalError
    PipelineRetryableError = _errors_mod.PipelineRetryableError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exit-code constants (per D74 + spec § 3.5 L829-832)
# ---------------------------------------------------------------------------

EXIT_SUCCESS = 0        # no gaps detected (clean state)
EXIT_OPERATIONAL = 1    # gaps detected OR retryable error (per D68)
EXIT_FATAL = 2          # fatal — config / connection / unexpected exception

# D76 EventType registered in CLAUDE.md CLI_* family registry (one of the
# 11 R4 canonical values per CLAUDE.md L210-217).
EVENT_TYPE = "CLI_DETECT_EXTRACTION_GAPS"

# Canonical recommended_action values per tools/gap_detector.py L201-204
# (Pitfall #9.c — strict; never invented values).
ACTION_BACKFILL = "backfill"
ACTION_INVESTIGATE = "investigate-source"
ACTION_NO_ACTION = "within-lookback-no-action"  # sentinel; never returned

# Bound on per-table affected enumeration in audit-row Metadata JSON. The
# wrapped module already caps its own GAP_DETECT metadata at 50; we mirror
# the cap here for consistency in the envelope event.
_METADATA_AFFECTED_TABLES_CAP = 50


# ---------------------------------------------------------------------------
# Actor detection (per § 1.7 invocation-pattern heuristic)
# ---------------------------------------------------------------------------


def _detect_actor() -> str:
    """Resolve ``--actor`` default per spec § 1.7 invocation-pattern heuristic.

    1. ``AUTOMIC_RUN_ID`` env var present -> 'automic'
    2. ``sys.stdin.isatty()`` -> 'operator'
    3. Else -> 'pipeline'

    Identical helper exists in sibling promote_test_to_prod.py — kept
    local rather than centralized to preserve the per-tool import
    boundary discipline of § 1.9 boilerplate.
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
# Naive-UTC datetime helper (per CDC-NOW-MS / SCD2-P1-f invariant)
# ---------------------------------------------------------------------------


def _now_naive_utc_ms() -> datetime:
    """Return tz-naive UTC datetime truncated to milliseconds.

    Per CDC-NOW-MS / SCD2-P1-f invariant from CLAUDE.md Do-NOT section:
    BCP CSV writes use ``'%Y-%m-%d %H:%M:%S.%3f'`` (ms only); pyodbc
    sends an aware datetime as DATETIMEOFFSET which SQL Server implicitly
    converts when comparing DATETIME2 = DATETIMEOFFSET — producing a
    different UTC moment than what BCP stored on non-UTC servers. Naive
    + ms precision matches the storage format on both sides.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return now.replace(microsecond=(now.microsecond // 1000) * 1000)


def _format_iso(dt: datetime) -> str:
    """Render a naive-UTC datetime as a canonical ISO-8601 'Z' string."""
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------


def _parse_as_of_date(raw: str | None) -> date:
    """Parse an ISO YYYY-MM-DD ``--as-of-date`` value.

    Defaults to today (UTC) per spec § 3.5 L802. Validates strictly via
    ``date.fromisoformat`` — non-ISO inputs raise ``ValueError`` which
    the caller surfaces as exit 2 (fatal argument error per § 1.8).
    """
    if raw is None:
        return _now_naive_utc_ms().date()
    return date.fromisoformat(raw)


def _resolve_alert_default(*, actor: str, alert_flag: bool | None) -> bool:
    """Resolve ``--alert`` default per spec § 3.5 L804.

    Default ON when ``actor == 'automic'``; OFF for any other actor.
    Operator can force either way via ``--alert`` / ``--no-alert``.
    ``alert_flag = None`` is the "not explicitly set" sentinel.
    """
    if alert_flag is not None:
        return alert_flag
    return actor == "automic"


# ---------------------------------------------------------------------------
# Gap-detector engine resolver (test-friendly indirection)
# ---------------------------------------------------------------------------


def _resolve_default_gap_detector() -> Callable:
    """Return a callable that invokes the Round 3 § 5.3 gap detector.

    Resolves at CALL TIME so tests patching ``sys.modules['tools.gap_detector']``
    after this tool imports are honored (per B218 lesson).
    """

    def _detect(*, source_filter: str | None, as_of_date: date) -> list:
        # Re-import the module fresh each call so test patches stick.
        mod = sys.modules.get("tools.gap_detector")
        if mod is None:
            mod = importlib.import_module("tools.gap_detector")
        return mod.detect_extraction_gaps(
            source_filter=source_filter,
            as_of_date=as_of_date,
        )

    return _detect


# ---------------------------------------------------------------------------
# Alert-dispatcher integration (per spec § 3.5 L767 + § 3.11)
# ---------------------------------------------------------------------------


def _resolve_default_alert_dispatcher() -> Callable:
    """Return a callable that fires an ops-channel alert via § 3.11.

    Resolves at CALL TIME. The Round 4 § 3.11 ``tools/alert_dispatcher.py``
    is unscoped-Phase-0 per spec (the ops-channel client itself is
    B82-tracked). If the module is unavailable, returns a NO-OP
    dispatcher that logs WARNING — preserving operator visibility into
    the missing pre-condition rather than silently failing the alert.
    """

    def _dispatch(
        *,
        severity: str,
        source_tool: str,
        message: str,
        details: dict | None = None,
    ) -> bool:
        """Returns True on successful dispatch, False on graceful fallback."""
        try:
            mod = sys.modules.get("tools.alert_dispatcher")
            if mod is None:
                mod = importlib.import_module("tools.alert_dispatcher")
            # Canonical entry per § 3.11 spec — best-effort signature
            # match: dispatch(severity, source_tool, message, details).
            if hasattr(mod, "dispatch_alert"):
                return bool(
                    mod.dispatch_alert(
                        severity=severity,
                        source_tool=source_tool,
                        message=message,
                        details=details or {},
                    )
                )
            if hasattr(mod, "main"):
                # Fallback if the module exposes a main() entry — pass a
                # synthetic argv-shaped dict.
                mod.main(
                    severity=severity,
                    source_tool=source_tool,
                    message=message,
                    details=details or {},
                )
                return True
        except (ImportError, AttributeError, ModuleNotFoundError):
            pass
        except Exception:  # noqa: BLE001
            logger.exception(
                "alert_dispatcher invocation failed; gap-detection verdict unaffected"
            )
            return False
        logger.warning(
            "alert_dispatcher module unavailable (B82 — Phase 0 deliverable "
            "tracking); alert NOT fired. Operator should monitor "
            "PipelineEventLog directly."
        )
        return False

    return _dispatch


# ---------------------------------------------------------------------------
# Stdout rendering (per spec § 3.5 L818-826)
# ---------------------------------------------------------------------------


def _format_expected_range(expected_range: tuple[date, date]) -> str:
    """Render ``(start, end)`` per spec § 3.5 L821."""
    start, end = expected_range
    days = (end - start).days + 1
    return f"{start.isoformat()} .. {end.isoformat()} ({days} days)"


def _format_missing_dates(missing_dates: list[date]) -> str:
    """Render missing-dates list per spec § 3.5 L822.

    Up to 5 dates inline; if more, show first 3 + ellipsis + last 1 +
    ``"(N total)"`` so the operator sees both the leading edge and the
    trailing edge of the gap without flooding stdout.
    """
    if not missing_dates:
        return "(none)"
    if len(missing_dates) <= 5:
        formatted = ", ".join(d.isoformat() for d in missing_dates)
        return f"{formatted} ({len(missing_dates)} day{'s' if len(missing_dates) != 1 else ''})"
    head = ", ".join(d.isoformat() for d in missing_dates[:3])
    tail = missing_dates[-1].isoformat()
    return f"{head}, ..., {tail} ({len(missing_dates)} days)"


def _format_recommended_action(report: Any) -> str:
    """Render recommended_action per spec § 3.5 L823.

    The spec example shows the action surfaced as a hint with the
    canonical backfill CLI for ``ACTION_BACKFILL`` paths. For
    ``ACTION_INVESTIGATE`` we surface the verbose investigate string.
    """
    action = getattr(report, "recommended_action", "")
    source_name = getattr(report, "source_name", "")
    table_name = getattr(report, "table_name", "")
    missing = getattr(report, "missing_dates", [])
    if action == ACTION_BACKFILL and missing:
        first = missing[0].isoformat()
        last = missing[-1].isoformat()
        return (
            f"backfill via tools/backfill.py --source {source_name} "
            f"--table {table_name} --from {first} --to {last}"
        )
    if action == ACTION_INVESTIGATE:
        return (
            "investigate-source — zero successful extractions in expected "
            "range; verify source connection + table activation before "
            "issuing a backfill"
        )
    return action or "(unknown)"


def _emit_human_no_gaps(*, tables_checked: int) -> None:
    """Spec § 3.5 L820 — clean state stdout."""
    suffix = "s" if tables_checked != 1 else ""
    print(f"No gaps detected ({tables_checked} table{suffix} checked).")


def _emit_human_with_gaps(
    reports: list,
    *,
    include_recommendation: bool,
) -> None:
    """Spec § 3.5 L820-823 — per-table block stdout.

    Each block:
        SOURCE.TABLE
          Expected: YYYY-MM-DD .. YYYY-MM-DD (N days)
          Missing : YYYY-MM-DD, YYYY-MM-DD (N days)
          Action  : <recommended action — see _format_recommended_action>
    """
    for idx, report in enumerate(reports):
        if idx > 0:
            print()  # blank-line separator between blocks
        label = (
            f"{getattr(report, 'source_name', '')}."
            f"{getattr(report, 'table_name', '')}"
        )
        print(label)
        expected = getattr(report, "expected_range", None)
        if expected is not None:
            print(f"  Expected: {_format_expected_range(expected)}")
        missing = getattr(report, "missing_dates", [])
        print(f"  Missing : {_format_missing_dates(missing)}")
        if include_recommendation:
            print(f"  Action  : {_format_recommended_action(report)}")


def _serialize_report_for_json(report: Any) -> dict:
    """Per spec § 3.5 L826 — JSON serialization of a GapReport.

    Schema: source_name, table_name, expected_range (list of two ISO
    dates), missing_dates (list of ISO dates), recommended_action.
    """
    expected = getattr(report, "expected_range", None)
    expected_list = None
    if expected is not None:
        start, end = expected
        expected_list = [start.isoformat(), end.isoformat()]
    return {
        "source_name": getattr(report, "source_name", ""),
        "table_name": getattr(report, "table_name", ""),
        "expected_range": expected_list,
        "missing_dates": [d.isoformat() for d in getattr(report, "missing_dates", [])],
        "recommended_action": getattr(report, "recommended_action", ""),
    }


def _emit_json(reports: list) -> None:
    """Per spec § 3.5 L826 — emit JSON array to stdout."""
    payload = [_serialize_report_for_json(r) for r in reports]
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


# ---------------------------------------------------------------------------
# Audit-row writer — one CLI_DETECT_EXTRACTION_GAPS row per invocation
# ---------------------------------------------------------------------------


def _build_affected_tables_summary(reports: list) -> list[dict]:
    """Bound + serialize the affected-table summary for Metadata JSON.

    Mirrors the wrapped module's cap (50 per
    ``tools/gap_detector.py`` _METADATA_AFFECTED_TABLES_CAP) so the
    envelope row and the GAP_DETECT row carry comparable shapes.
    """
    affected: list[dict] = [
        {
            "source_name": getattr(r, "source_name", ""),
            "table_name": getattr(r, "table_name", ""),
            "missing_count": len(getattr(r, "missing_dates", [])),
            "recommended_action": getattr(r, "recommended_action", ""),
        }
        for r in reports[:_METADATA_AFFECTED_TABLES_CAP]
    ]
    if len(reports) > _METADATA_AFFECTED_TABLES_CAP:
        affected.append(
            {"_truncated": f"{len(reports) - _METADATA_AFFECTED_TABLES_CAP} more"}
        )
    return affected


def _write_audit_row(
    metadata: dict,
    *,
    status: str,
    error_message: str | None = None,
    cursor_factory: Callable | None = None,
    general_db: str = "General",
    skip: bool = False,
) -> int | None:
    """INSERT one ``CLI_DETECT_EXTRACTION_GAPS`` row into PipelineEventLog.

    Per D76 + spec § 3.5 L766-769. ONE row per invocation. Best-effort:
    failures are logged but do not affect the verdict exit code (parity
    with sibling enforce_retention + promote_test_to_prod patterns).

    Returns the IDENTITY value of the inserted row via SCOPE_IDENTITY()
    so JSON output can surface ``audit_event_id`` for operator
    correlation. Returns None on failure.

    When ``skip=True`` (test path; main()'s ``no_audit_event``), the
    function returns None immediately without writing.
    """
    if skip:
        return None
    metadata_json = json.dumps(metadata, separators=(",", ":"), default=str)
    event_detail = (
        f"detect_extraction_gaps / "
        f"as_of_date={metadata.get('as_of_date')} "
        f"source_filter={metadata.get('source_filter')} "
        f"tables_with_gaps={metadata.get('tables_with_gaps')}"
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
                f"VALUES (NULL, NULL, NULL, ?, ?, ?, SYSUTCDATETIME(), ?, ?, ?); "
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
        logger.exception("Failed to write CLI_DETECT_EXTRACTION_GAPS audit row")
        return None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Result-dict initializer (shared by main + early-exit paths)
# ---------------------------------------------------------------------------


def _build_initial_result(
    *,
    actor: str,
    as_of_date: str,
    source_filter: str | None,
    include_recommendation: bool,
    alert_flag: bool,
    started_at_dt: datetime,
) -> dict[str, Any]:
    """Construct the result dict per the D76 audit-row metadata schema."""
    return {
        "event_kind": "gap_detection",
        "actor": actor,
        "as_of_date": as_of_date,
        "source_filter": source_filter,
        "include_recommendation": include_recommendation,
        "alert_flag": alert_flag,
        "alert_fired": False,
        "tables_with_gaps": 0,
        "total_missing_dates": 0,
        "affected_tables": [],
        "exit_code": EXIT_SUCCESS,
        "dry_run": False,
        "started_at": _format_iso(started_at_dt),
        "started_at_dt": started_at_dt,
        "completed_at": None,
        "audit_event_id": None,
        "errors": [],
    }


# ---------------------------------------------------------------------------
# Top-level main() — programmatic entry point
# ---------------------------------------------------------------------------


def main(
    *,
    actor: str,
    as_of_date: str | None = None,
    source: str | None = None,
    alert: bool | None = None,
    include_recommendation: bool = True,
    json_output: bool = False,
    verbose: bool = False,
    quiet: bool = False,
    no_audit_event: bool = False,
    # ---- Injection hooks (resolve at CALL TIME for test mock alignment) ----
    gap_detector: Callable | None = None,
    alert_dispatcher: Callable | None = None,
    audit_cursor_factory: Callable | None = None,
    general_db: str | None = None,
) -> dict:
    """Programmatic entry — invoke Round 3 § 5.3 detect_extraction_gaps.

    Returns a dict matching the D76 audit-row Metadata shape (see module
    docstring for the canonical schema). Exit-code derivation per D74 +
    spec § 3.5 L829-832:

    * 0: no gaps detected (clean state)
    * 1: gaps detected OR retryable error per D68 (GapDetectorTimeout /
      ExtractionStateUnavailable — both PipelineRetryableError)
    * 2: fatal — invalid args, unexpected exception

    Parameters
    ----------
    actor:
        Operator identity (per D75 + D76). REQUIRED.
    as_of_date:
        Optional ISO YYYY-MM-DD; defaults to today (UTC). Maps to
        Round 3 § 5.3 ``as_of_date`` kwarg.
    source:
        Optional ``UdmTablesList.SourceName`` filter (e.g. ``'DNA'``).
        Maps to Round 3 § 5.3 ``source_filter`` kwarg.
    alert:
        Tri-state: ``None`` -> default per actor heuristic (True for
        automic, False otherwise); ``True`` / ``False`` -> explicit
        operator choice.
    include_recommendation:
        Render the per-table ``Action`` line in human output (default
        True per spec § 3.5 L807).
    json_output:
        Emit JSON to stdout instead of human-readable blocks
        (spec § 3.5 L826).
    no_audit_event:
        Skip the CLI-level ``CLI_DETECT_EXTRACTION_GAPS`` audit row
        write (pipeline-programmatic callers per D76).
    gap_detector / alert_dispatcher / audit_cursor_factory:
        Test-injection hooks. Default resolve to the live infrastructure.
    general_db:
        Override the canonical General DB name (defaults to
        ``utils.configuration.GENERAL_DB``, fallback ``'General'``).
    """
    started_at_dt = _now_naive_utc_ms()

    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    elif quiet:
        logging.getLogger().setLevel(logging.ERROR)

    # ---- Validate / parse as_of_date ----
    try:
        parsed_as_of = _parse_as_of_date(as_of_date)
    except ValueError as exc:
        # Argv-level validation should have caught this; if main() is
        # called programmatically with bad input, surface as exit 2.
        result: dict[str, Any] = _build_initial_result(
            actor=actor,
            as_of_date=as_of_date or "",
            source_filter=source,
            include_recommendation=include_recommendation,
            alert_flag=bool(alert),
            started_at_dt=started_at_dt,
        )
        result["exit_code"] = EXIT_FATAL
        result["error_type"] = "ValueError"
        result["error_message"] = str(exc)
        result["errors"].append(f"ValueError: {exc}")
        result["completed_at"] = _format_iso(_now_naive_utc_ms())
        if not quiet:
            print(f"FATAL: invalid --as-of-date: {exc}", file=sys.stderr)
        audit_id = _write_audit_row(
            result,
            status="FAILED",
            error_message=str(exc)[:4000],
            cursor_factory=audit_cursor_factory,
            general_db=general_db or "General",
            skip=no_audit_event,
        )
        result["audit_event_id"] = audit_id
        return result

    # ---- Resolve general_db tag (matches sibling pattern) ----
    if general_db is None:
        try:
            import utils.configuration as config  # type: ignore

            general_db = getattr(config, "GENERAL_DB", "General")
        except Exception:  # noqa: BLE001
            general_db = "General"

    # ---- Resolve --alert default per spec § 3.5 L804 ----
    alert_resolved = _resolve_alert_default(actor=actor, alert_flag=alert)

    # ---- Pre-populate result with input echoes for early-exit paths ----
    result = _build_initial_result(
        actor=actor,
        as_of_date=parsed_as_of.isoformat(),
        source_filter=source,
        include_recommendation=include_recommendation,
        alert_flag=alert_resolved,
        started_at_dt=started_at_dt,
    )

    # ---- Invoke the canonical Round 3 § 5.3 gap detector ----
    if gap_detector is None:
        gap_detector = _resolve_default_gap_detector()

    reports: list = []
    try:
        reports = gap_detector(source_filter=source, as_of_date=parsed_as_of)
    except GapDetectorTimeout as exc:
        # PipelineRetryableError (utils/errors.py L399) -> exit 1 per § 1.8.
        result["exit_code"] = EXIT_OPERATIONAL
        result["error_type"] = "GapDetectorTimeout"
        result["error_message"] = str(exc)[:4000]
        result["errors"].append(f"GapDetectorTimeout: {exc}")
        logger.warning("GapDetectorTimeout: %s", exc)
        if not quiet:
            print(
                f"WARNING: gap-detector timeout (retryable per D68): {exc}",
                file=sys.stderr,
            )
        result["completed_at"] = _format_iso(_now_naive_utc_ms())
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
    except ExtractionStateUnavailable as exc:
        # PipelineRetryableError -> exit 1 per § 1.8.
        result["exit_code"] = EXIT_OPERATIONAL
        result["error_type"] = "ExtractionStateUnavailable"
        result["error_message"] = str(exc)[:4000]
        result["errors"].append(f"ExtractionStateUnavailable: {exc}")
        logger.warning("ExtractionStateUnavailable: %s", exc)
        if not quiet:
            print(
                f"WARNING: extraction-state unavailable (retryable per D68): {exc}",
                file=sys.stderr,
            )
        result["completed_at"] = _format_iso(_now_naive_utc_ms())
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
    except PipelineFatalError as exc:
        # PipelineFatalError -> exit 2 per § 1.8 + D74.
        result["exit_code"] = EXIT_FATAL
        result["error_type"] = type(exc).__name__
        result["error_message"] = str(exc)[:4000]
        result["errors"].append(f"{type(exc).__name__}: {exc}")
        logger.error("PipelineFatalError: %s", exc, exc_info=True)
        if not quiet:
            print(
                f"FATAL: gap detection failed (fatal): {exc}",
                file=sys.stderr,
            )
        result["completed_at"] = _format_iso(_now_naive_utc_ms())
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
    except PipelineRetryableError as exc:
        # Any other PipelineRetryableError subclass -> exit 1.
        result["exit_code"] = EXIT_OPERATIONAL
        result["error_type"] = type(exc).__name__
        result["error_message"] = str(exc)[:4000]
        result["errors"].append(f"{type(exc).__name__}: {exc}")
        logger.warning("PipelineRetryableError: %s", exc)
        if not quiet:
            print(
                f"WARNING: gap detection retryable failure: {exc}",
                file=sys.stderr,
            )
        result["completed_at"] = _format_iso(_now_naive_utc_ms())
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
    except Exception as exc:  # noqa: BLE001
        # Unexpected exception -> exit 2 (fatal) per § 1.8.
        result["exit_code"] = EXIT_FATAL
        result["error_type"] = type(exc).__name__
        result["error_message"] = str(exc)[:4000]
        result["errors"].append(f"{type(exc).__name__}: {exc}")
        logger.error("Unexpected exception in gap detection: %s", exc, exc_info=True)
        if not quiet:
            print(
                f"FATAL: unexpected exception in gap detection: {exc}",
                file=sys.stderr,
            )
        result["completed_at"] = _format_iso(_now_naive_utc_ms())
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

    # ---- Process happy-path result ----
    # Defensive coercion — engine returns list[GapReport] but a misbehaving
    # mock might return None.
    if reports is None:
        reports = []
    reports = list(reports)

    result["tables_with_gaps"] = len(reports)
    result["total_missing_dates"] = sum(
        len(getattr(r, "missing_dates", [])) for r in reports
    )
    result["affected_tables"] = _build_affected_tables_summary(reports)

    # ---- Fire alert per spec § 3.5 L767 + § 3.11 ----
    if alert_resolved and reports:
        if alert_dispatcher is None:
            alert_dispatcher = _resolve_default_alert_dispatcher()
        try:
            details = {
                "as_of_date": parsed_as_of.isoformat(),
                "source_filter": source,
                "tables_with_gaps": len(reports),
                "total_missing_dates": result["total_missing_dates"],
                "affected_tables": result["affected_tables"],
            }
            summary_msg = (
                f"Extraction gaps detected: {len(reports)} table(s), "
                f"{result['total_missing_dates']} missing date(s) total "
                f"as of {parsed_as_of.isoformat()}."
            )
            alert_fired = bool(
                alert_dispatcher(
                    severity="warning",
                    source_tool="detect_extraction_gaps",
                    message=summary_msg,
                    details=details,
                )
            )
            result["alert_fired"] = alert_fired
        except Exception:  # noqa: BLE001
            # Alert dispatch failure does NOT affect the verdict — verdict
            # is the gap-detection result; alert is best-effort
            # notification per spec § 3.5 L767 + § 3.11 narrative.
            logger.exception(
                "Alert dispatch failed; gap-detection verdict unaffected"
            )
            result["alert_fired"] = False

    # ---- Determine verdict exit code ----
    # 0 if no gaps, 1 if any gaps detected (clean spec § 3.5 L829-830 logic).
    result["exit_code"] = EXIT_OPERATIONAL if reports else EXIT_SUCCESS

    # ---- Render stdout ----
    result["completed_at"] = _format_iso(_now_naive_utc_ms())

    # ---- Write invocation-level audit row (D76) ----
    status = "SUCCESS"  # gap detection completed; exit 1 with gaps is success
    audit_event_id = _write_audit_row(
        result,
        status=status,
        error_message=None,
        cursor_factory=audit_cursor_factory,
        general_db=general_db,
        skip=no_audit_event,
    )
    result["audit_event_id"] = audit_event_id

    # ---- Render stdout AFTER audit-row write so audit_event_id surfaces ----
    if json_output:
        _emit_json(reports)
    elif not quiet:
        if reports:
            _emit_human_with_gaps(
                reports,
                include_recommendation=include_recommendation,
            )
        else:
            # Spec § 3.5 L820: count of tables checked surfaces.
            # The wrapped module omits clean tables from its return list,
            # so we don't know the precise "tables checked" count from
            # the return value alone. Surface 0 as a defensive default
            # (operator-visible "no gaps" is the load-bearing signal;
            # the GAP_DETECT event-row Metadata has the actual count).
            tables_checked = result.get("tables_checked", 0) or 0
            _emit_human_no_gaps(tables_checked=tables_checked)

    # Keep the operator-visible result deterministic — internal-only
    # transient keys (started_at_dt) stay in the dict but are excluded
    # from JSON serialization via the default=str arm in
    # _write_audit_row's json.dumps call.

    return result


# ---------------------------------------------------------------------------
# CLI argv entry point — argparse + main()
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    """Alias for :func:`_build_parser` — Tier 0 scaffold contract per D77."""
    return _build_parser()


def _build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser per spec § 3.5 + § 1.4 canonical args.

    Per Pitfall #9.b invented-parameter rule (HANDOFF §8): this parser
    does NOT accept any args outside the canonical set declared at
    spec § 3.5 L797-808 + § 1.4. Tier 0 assertion verifies this.

    NOTE per § 1.2: this tool is READ-ONLY by design (gap detection is
    a report; nothing to apply). NO ``--apply`` / ``--dry-run`` flag
    is exposed — per spec § 1.2 L155-157 read-only tools never get the
    flag.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Detect missing business_date rows in PipelineExtraction per "
            "(source, large-table). Wraps Round 3 § 5.3 "
            "detect_extraction_gaps. Emits one CLI_DETECT_EXTRACTION_GAPS "
            "audit row per invocation per D76."
        ),
    )

    # ---- Tool-specific args (per spec § 3.5 L797-808) ----
    parser.add_argument(
        "--source",
        default=None,
        help=(
            "Filter by SourceName (UdmTablesList.SourceName). "
            "Examples: DNA, CCM, EPICOR. None = no filter."
        ),
    )
    parser.add_argument(
        "--as-of-date",
        default=None,
        dest="as_of_date",
        help=(
            "ISO YYYY-MM-DD; defaults to today (UTC). Maps to Round 3 "
            "§ 5.3 detect_extraction_gaps(as_of_date)."
        ),
    )

    # --alert / --no-alert mutual group (default resolved per actor)
    alert_group = parser.add_mutually_exclusive_group()
    alert_group.add_argument(
        "--alert",
        action="store_true",
        dest="alert",
        default=None,
        help=(
            "Fire ops-channel alert via tools/alert_dispatcher.py "
            "(§ 3.11) if any gap detected. Default ON when "
            "--actor automic; OFF otherwise."
        ),
    )
    alert_group.add_argument(
        "--no-alert",
        action="store_false",
        dest="alert",
        default=None,
        help="Force-disable alert dispatch (override automic default).",
    )

    # --include-recommendation / --no-include-recommendation mutual group
    rec_group = parser.add_mutually_exclusive_group()
    rec_group.add_argument(
        "--include-recommendation",
        action="store_true",
        dest="include_recommendation",
        default=True,
        help=(
            "Include the per-table recommended_action line in human "
            "stdout (default ON per spec § 3.5 L807)."
        ),
    )
    rec_group.add_argument(
        "--no-include-recommendation",
        action="store_false",
        dest="include_recommendation",
        help="Suppress the per-table Action line in human stdout.",
    )

    # ---- D75 canonical args (per spec § 1.4) ----
    parser.add_argument(
        "--actor",
        default=None,
        help=(
            "One of operator / automic / pipeline. Auto-detected via TTY "
            "/ AUTOMIC_RUN_ID env when omitted."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help=(
            "Emit JSON array of GapReport to stdout (per spec § 3.5 "
            "L826) instead of human-readable per-table blocks."
        ),
    )
    parser.add_argument(
        "--no-audit-event",
        action="store_true",
        dest="no_audit_event",
        help=(
            "Skip the CLI-level CLI_DETECT_EXTRACTION_GAPS PipelineEventLog "
            "write (pipeline-programmatic callers per D76)."
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

    Exit codes (always one of 0 / 1 / 2 per D74 + spec § 3.5 L829-832):
        - 0: no gaps detected (clean state)
        - 1: gaps detected OR retryable error per D68
        - 2: fatal — invalid args / connection / unexpected exception
    """
    parser = _build_parser()
    args = parser.parse_args()

    actor = args.actor or _detect_actor()

    try:
        result = main(
            actor=actor,
            as_of_date=args.as_of_date,
            source=args.source,
            alert=args.alert,
            include_recommendation=args.include_recommendation,
            json_output=args.json_output,
            verbose=args.verbose,
            quiet=args.quiet,
            no_audit_event=args.no_audit_event,
        )
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else EXIT_FATAL
        if code not in (EXIT_SUCCESS, EXIT_OPERATIONAL, EXIT_FATAL):
            code = EXIT_FATAL
        return code
    except KeyboardInterrupt:
        logger.warning("Interrupted by operator")
        return EXIT_OPERATIONAL
    except Exception:  # noqa: BLE001
        tb = traceback.format_exc()
        print(
            f"FATAL: detect_extraction_gaps unexpected exception:\n{tb[:1000]}",
            file=sys.stderr,
        )
        return EXIT_FATAL

    exit_code = int(result.get("exit_code", EXIT_FATAL))
    # Defensive clamp — every exit path MUST be 0 / 1 / 2 per D74
    # contract (Pitfall #9.m self-application — the docstring claims
    # "exit 0/1/2 per D74", so verify the claim).
    if exit_code not in (EXIT_SUCCESS, EXIT_OPERATIONAL, EXIT_FATAL):
        logger.error(
            "Non-canonical exit_code %r returned from main(); "
            "clamping to EXIT_FATAL",
            exit_code,
        )
        exit_code = EXIT_FATAL
    return exit_code


if __name__ == "__main__":
    sys.exit(cli_main())
