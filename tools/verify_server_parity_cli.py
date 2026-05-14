"""Round 4 § 3.7 — ``tools/verify_server_parity_cli.py`` (CLI shim for M8).

Per **Round 4 § 3.7** at ``docs/migration/phase1/04_tools.md`` L951-1024
(canonical spec) wrapping **Round 3 § 3.2** ``verify_server_parity()`` at
``tools/verify_server_parity.py`` (M8 Wave 5 module body).

This is the **CLI shim**: argparse + exit-code mapping + audit-row writer +
stdout rendering + ``--alert`` integration. The actual parity computation
lives in M8 (``tools/verify_server_parity.py``); this file ONLY wraps the
operator surface per Round 4 § 3.7.

Why a separate file (not a CLI surface added to M8)
---------------------------------------------------

M8 (``tools/verify_server_parity.py``) was authored at Wave 5 as a pure
module body — no ``if __name__ == '__main__':`` guard, no argparse, no
audit-row writer (M8 module body explicitly delegates the audit row to
the CLI shim per spec § 3.7 "ONE PARITY_VERIFY event row in
PipelineEventLog per Round 3 § 3.2 (event_tracker writes)" — but § 3.7
CLI is the operator-facing event-writer per D76 CLI_* family discipline).

Extending M8 in-place would (a) co-mingle library code with operator-CLI
code in a single file, breaking the M8 import surface that other modules
(``tools/promote_test_to_prod.py``, ``main_small_tables.py``,
``main_large_tables.py``) consume; (b) risk Pitfall #9.l "canonical-schema
working-memory drift" by reshaping M8 mid-stream; (c) collide with the
existing 49-test M8 test suite at ``tests/{tier0,tier1}/test_verify_
server_parity.py`` that pins the M8 module contract today.

Per D92 (forward-only additive): NEW separate file leaves M8 untouched.

What this CLI shim does
-----------------------

1. Parse argv via argparse with canonical D75 args + § 3.7 tool-specific
   args (``--baseline-path``, ``--fail-on-warning``, ``--alert``).
2. Resolve ``--actor`` per § 1.7 invocation-pattern heuristic
   (AUTOMIC_RUN_ID env / sys.stdin.isatty() / fallback ``pipeline``).
3. Resolve ``--alert`` default: True when actor in {automic, pipeline},
   False otherwise per § 3.7 L996.
4. Call M8 ``verify_server_parity(baseline_path, server_name,
   fail_on_warning)`` — canonical signature per R2 § 4.2 L957-961.
5. Map return value / exception to D74 exit code:
   - ``ParityReport.overall == 'pass'`` -> exit 0
   - ``ParityReport.overall == 'warn'`` -> exit 1 (unless
     ``--fail-on-warning``, then exit 2 via raise)
   - ``ParityReport.overall == 'fail'`` -> raise/caught: exit 2
   - ``ParityFatalError`` (raised by M8 on fatal) -> exit 2
   - ``ParityBaselineMissing`` -> exit 2; stderr message
   - ``ParityProbeError`` -> exit 2
6. Write ONE ``CLI_VERIFY_SERVER_PARITY`` row to
   ``General.ops.PipelineEventLog`` per D76 + CLAUDE.md CLI_* family
   registry. Metadata JSON contains the full ``ParityReport.to_dict()``.
7. Render stdout per § 3.7:
   - default human format: per-check table + summary line
   - ``--json``: canonical ``ParityReport`` dataclass dict (no invented
     fields; no canonical field dropped per § 3.7 L1009)
   - ``--quiet``: only exit code communicates result
8. Fire ``tools/alert_dispatcher.py`` (§ 3.11) on warning or fatal
   drift when ``--alert`` is set.

CLI contract (per § 3.7 L971-986)
---------------------------------

::

    # Automic-invoked pre-cycle parity verify
    python3 tools/verify_server_parity_cli.py --actor automic --alert

    # Operator ad-hoc
    python3 tools/verify_server_parity_cli.py

    # Verify against alternate baseline (e.g. pre-deployment check)
    python3 tools/verify_server_parity_cli.py \\
        --baseline-path /tmp/new_baseline.json

    # Strict pre-deployment validation: warning -> fatal
    python3 tools/verify_server_parity_cli.py --fail-on-warning

Exit codes (per D74 + § 3.7 L1011-1014)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* **0** — all ``match`` OR only ``informational``-tier drift
* **1** — ``warning``-tier drift (operator review; pipeline can proceed)
* **2** — ``fatal``-tier drift OR ``ParityBaselineMissing`` OR
  ``ParityProbeError`` (pipeline MUST NOT proceed)

Audit row (per D76 + CLAUDE.md CLI_* family registry)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* ``General.ops.PipelineEventLog.EventType = 'CLI_VERIFY_SERVER_PARITY'``
  (one of the 11 R4 canonical CLI_* family values per CLAUDE.md)
* ONE row per INVOCATION (spec § 3.7 L993 — ONE row, full report in
  Metadata)
* ``Status in {SUCCESS, FAILED}`` (SUCCESS for exit 0/1; FAILED for 2)
* ``Metadata`` JSON shape::

    {
        "event_kind": "parity_verify",
        "actor": "<operator>",
        "justification": "<text or null>",
        "baseline_path": "<resolved path>",
        "fail_on_warning": <bool>,
        "alert": <bool>,
        "report": {<ParityReport.to_dict() — full canonical dataclass>},
        "exit_code": <int>,
        "started_at": "<ISO-8601 naive-UTC>",
        "completed_at": "<ISO-8601 naive-UTC>"
    }

Note on EventType naming
~~~~~~~~~~~~~~~~~~~~~~~~

Spec § 3.7 L993 references the EventType as ``'PARITY_VERIFY'`` (the
Round 3 module-level naming; M8's ``EVENT_TYPE`` constant uses that
value). CLAUDE.md D76 CLI_* family registry uses
``'CLI_VERIFY_SERVER_PARITY'`` (the post-D76-freeze canonical name).
This CLI shim writes ``'CLI_VERIFY_SERVER_PARITY'`` per the D76 family
discipline. The spec/registry naming tension is captured as a Round 7
governance B-N candidate (see "Spec ambiguities" in the build report).

Classification per ``udm-execution-classifier`` skill
-----------------------------------------------------

* **Trigger**: PRIMARY: Scheduled (Automic ``JOB_PARITY_VERIFY`` daily
  AM/PM pre-cycle per Round 2 § 5.1). SECONDARY: Pipeline programmatic
  precondition at startup (per spec § 3.7 L989 + Round 3 § 3.2).
  TERTIARY: Manual operator ad-hoc.
* **Frequency**: PRIMARY Recurring (daily AM + PM); SECONDARY per
  pipeline run; TERTIARY one-time ad-hoc.
* **Idempotency**: YES per spec § 3.7 L991 + Round 3 § 3.2 — read-only
  on filesystem; INSERT-only on PipelineEventLog. Re-invocation produces
  a NEW report row (intentional — each pipeline startup is its own
  audit moment).
* **Concurrency**: synchronous prerequisite at process start (spec
  § 3.7 L999). Single-threaded. No sp_getapplock — parity verify is
  inherently parallel-safe (read-only).
* **Audit-row family**: ``CLI_VERIFY_SERVER_PARITY`` per D76 + CLAUDE.md
  CLI_* family registry.
* **Routing**: PRIMARY tracker ``phase1/02_configuration.md`` § 5.1
  Automic inventory (frozen-11 includes ``JOB_PARITY_VERIFY``).
  SECONDARY tracker ``ONE_OFF_SCRIPTS.md`` operator tools table.

D-numbers consumed
------------------

D27 (cross-server parity baseline contract),
D62-D65 (drift severity classification — fatal / warning / informational /
match),
D67 (Tier 0 smoke discipline),
D68 (error class hierarchy — utils.errors per B228),
D74 (CLI exit-code contract 0/1/2),
D75 (CLI argument naming — actor / apply / dry-run / json / verbose /
quiet / justification / no-audit-event),
D76 (CLI audit-row contract — CLI_VERIFY_SERVER_PARITY family value),
D77 (Tier 0 6-canonical scaffold + § 3.7 8-assertion extension),
D85 (module startup sequence stage 3 — parity check),
D92 (forward-only additive — new CLI file leaves M8 untouched),
D103 (Claude Code security model — baseline outside /debi).

Canonical references cited (per Pitfall #9.l producer self-check)
-----------------------------------------------------------------

* M8 module: ``tools/verify_server_parity.py`` canonical signature at
  L100-113 — ``verify_server_parity(baseline_path, server_name,
  fail_on_warning, *, server, json_output, _runner)`` returning
  ``ParityReport``. Re-read at producer Gate 1 self-check per HANDOFF
  §8 Pitfall #9.l.
* Spec § 3.7 L951-1024 ``phase1/04_tools.md`` — CLI contract.
* CLI conventions: ``phase1/04_tools.md`` § 1.4 (canonical args) +
  § 1.7 (invocation-pattern heuristic — AUTOMIC_RUN_ID env + isatty) +
  § 1.8 (exit-code mapping) + § 1.9 (boilerplate template).
* utils.errors: ``ParityFatalError``, ``ParityBaselineMissing``,
  ``ParityProbeError`` per B228 canonical exception module.
* CLAUDE.md CLI_* family registry: ``CLI_VERIFY_SERVER_PARITY``
  (11 R4 canonical CLI_* values).

See also
--------

* ``tools/verify_server_parity.py`` — M8 module body (the parity
  computation this shim wraps).
* ``utils/errors.py`` — canonical exception classes per B228.
* ``tools/alert_dispatcher.py`` — § 3.11 (alert fan-out, not yet
  authored at the time of this CLI's first build; import is best-
  effort + fail-silent per § 3.7 L996 "default ON when --actor automic
  or --actor pipeline" but failure to import does NOT block the CLI).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import traceback
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# Project root on sys.path so we can reach utils.* + the M8 module sibling.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Canonical exception imports per B228 — DO NOT define local classes.
from utils.errors import (  # noqa: E402
    ParityBaselineMissing,
    ParityFatalError,
    ParityProbeError,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exit-code constants (per D74 + spec § 3.7 L1011-1014)
# ---------------------------------------------------------------------------

EXIT_SUCCESS = 0
EXIT_WARNING = 1
EXIT_FATAL = 2

# D76 EventType for the CLI_* family audit row per CLAUDE.md registry.
# Note: M8's module-level EVENT_TYPE is 'PARITY_VERIFY' (legacy R3 naming
# pre-D76 freeze). The CLI shim writes the D76 CLI_* family value.
EVENT_TYPE = "CLI_VERIFY_SERVER_PARITY"

# D103 canonical baseline path (outside /debi; root:root 0644 per R2 § 4.1).
DEFAULT_BASELINE_PATH = "/etc/pipeline/parity_baseline.json"

# Per § 3.7 L996: --alert default ON when --actor in {automic, pipeline}.
_ALERT_AUTO_ON_ACTORS = frozenset({"automic", "pipeline"})


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
# Alert dispatcher integration (best-effort; § 3.7 L996)
# ---------------------------------------------------------------------------


def _fire_alert(
    *,
    report_dict: dict[str, Any],
    severity: str,
    actor: str,
    baseline_path: str,
) -> bool:
    """Fire an alert via ``tools/alert_dispatcher.py`` when ``--alert`` is set.

    Per § 3.7 L996 — on warning or fatal drift the CLI fires an ops-channel
    alert. The alert_dispatcher (§ 3.11) is not yet authored at the time
    of this CLI's first build; we attempt an import and gracefully no-op
    on ImportError (fail-silent — the audit row is the source of truth).

    Returns True if the alert was attempted (importable + invoked);
    False otherwise. Logs at WARNING on failure but does NOT affect the
    exit-code path.
    """
    try:
        # § 3.11 alert_dispatcher import — best-effort. Imported lazily so
        # missing module doesn't break the CLI's primary surface.
        from tools import alert_dispatcher  # type: ignore  # noqa: I001

        # Conventional alert payload — actual signature is defined by § 3.11
        # author. We pass a structured dict; alert_dispatcher chooses the
        # transport (Slack / email / PagerDuty).
        if hasattr(alert_dispatcher, "dispatch"):
            alert_dispatcher.dispatch(  # type: ignore[attr-defined]
                event_type="parity_drift",
                severity=severity,
                actor=actor,
                baseline_path=baseline_path,
                report=report_dict,
            )
            return True
        # Module exists but no dispatch() — log + skip.
        logger.warning(
            "alert_dispatcher imported but lacks dispatch(); skipping alert"
        )
        return False
    except (ImportError, ModuleNotFoundError):
        logger.warning(
            "alert_dispatcher unavailable (§ 3.11 not yet authored); "
            "audit row is the source of truth for this %s drift",
            severity,
        )
        return False
    except Exception as exc:  # noqa: BLE001
        logger.warning("alert_dispatcher.dispatch() raised: %s", exc)
        return False


# ---------------------------------------------------------------------------
# M8 module-function resolution (test-friendly indirection)
# ---------------------------------------------------------------------------


def _resolve_verify_fn() -> Callable:
    """Return the M8 ``verify_server_parity`` callable.

    Resolved at CALL TIME so tests patching ``sys.modules`` after this
    CLI shim's import are honored. Matches B218 pattern from the
    sibling Round 4 CLI tools.
    """
    # Prefer the already-imported module (avoids double-execution).
    m8 = sys.modules.get("tools.verify_server_parity")
    if m8 is None:
        from tools import verify_server_parity as m8  # type: ignore  # noqa: PLC0415
    return getattr(m8, "verify_server_parity")


# ---------------------------------------------------------------------------
# ParityReport -> dict (canonical JSON shape per spec § 3.7 L1009)
# ---------------------------------------------------------------------------


def _report_to_dict(report: Any) -> dict[str, Any]:
    """Serialize ``ParityReport`` to the canonical dict shape per § 3.7 L1009.

    Uses ``dataclasses.asdict`` to round-trip every field — per Round 8
    WORKER-SERIALIZE lesson, hand-enumerated dicts silently drop fields.
    asdict() handles nested ``ParityCheck`` dataclasses automatically.

    Per § 3.7 L1009 the JSON shape is::

        {"server_name": "...", "baseline_name": "...",
         "baseline_pinned_at": "...", "checks": [...],
         "fatal_count": N, "warning_count": N,
         "informational_count": N, "match_count": N,
         "overall": "pass|warn|fail"}

    No invented fields; no canonical field dropped per § 3.7 L1009
    + Pitfall #9.b invented-field-name guard.
    """
    # M8 ParityReport exposes ``to_dict()`` per its module body; prefer it
    # so any field-renaming in M8 is picked up automatically.
    if hasattr(report, "to_dict"):
        try:
            return report.to_dict()
        except Exception:  # noqa: BLE001
            pass
    # Fallback: dataclasses.asdict (works on any @dataclass)
    try:
        return asdict(report)
    except Exception:  # noqa: BLE001
        # Last-resort: build the canonical dict manually using the spec
        # field list. This branch should never run in practice.
        return {
            "server_name": getattr(report, "server_name", None),
            "baseline_name": getattr(report, "baseline_name", None),
            "baseline_pinned_at": getattr(report, "baseline_pinned_at", None),
            "checks": [
                {
                    "key": getattr(c, "key", None),
                    "expected": getattr(c, "expected", None),
                    "actual": getattr(c, "actual", None),
                    "severity": getattr(c, "severity", None),
                    "exception_match": getattr(c, "exception_match", None),
                    "note": getattr(c, "note", None),
                }
                for c in getattr(report, "checks", [])
            ],
            "fatal_count": getattr(report, "fatal_count", 0),
            "warning_count": getattr(report, "warning_count", 0),
            "informational_count": getattr(report, "informational_count", 0),
            "match_count": getattr(report, "match_count", 0),
            "overall": getattr(report, "overall", "fail"),
        }


# ---------------------------------------------------------------------------
# Stdout rendering
# ---------------------------------------------------------------------------

_SEV_GLYPH = {
    "match": "v",  # ascii fallback; spec uses ✓ — switch to ascii for
    "informational": "i",  # Windows-console safety (cp1252 default)
    "warning": "!",  # spec uses ⚠
    "fatal": "x",  # spec uses ✗
}


def _emit_human_summary(report_dict: dict[str, Any], *, baseline_path: str) -> None:
    """Print the spec § 3.7 L1000-1008 stdout block.

    Two modes per spec:
    - success + all-match: ``Parity: all N checks pass.`` (L1000)
    - success + warnings/failures: per-check table + Overall line (L1002-1008)
    """
    overall = str(report_dict.get("overall", "fail")).lower()
    checks = report_dict.get("checks", []) or []
    n = len(checks)

    if overall == "pass" and all(
        str(c.get("severity")) == "match" for c in checks
    ):
        # All-match success — single-line per spec L1000.
        print(f"Parity: all {n} checks pass.")
        return

    server_name = report_dict.get("server_name", "<unknown>")
    print(
        f"Parity report -- server: {server_name} -- baseline: {baseline_path}"
    )
    for c in checks:
        sev = str(c.get("severity", "match"))
        glyph = _SEV_GLYPH.get(sev, "?")
        key = c.get("key", "<missing_key>")
        actual = c.get("actual", "")
        expected = c.get("expected", "")
        if sev == "match":
            print(f"  {glyph} {str(key):<24} : {actual}")
        else:
            tier_label = sev.upper() + " tier per D65"
            print(
                f"  {glyph} {str(key):<24} : {actual} "
                f"(baseline: {expected})  [{tier_label}]"
            )
    print(f"Overall: {overall}")
    fatal_n = int(report_dict.get("fatal_count", 0))
    warning_n = int(report_dict.get("warning_count", 0))
    info_n = int(report_dict.get("informational_count", 0))
    match_n = int(report_dict.get("match_count", 0))
    parts = []
    if fatal_n:
        parts.append(f"{fatal_n} fatal")
    if warning_n:
        parts.append(f"{warning_n} warning")
    if info_n:
        parts.append(f"{info_n} informational")
    if match_n:
        parts.append(f"{match_n} match")
    if parts:
        print(", ".join(parts))


def _emit_json(report_dict: dict[str, Any]) -> None:
    """Emit the canonical JSON payload per spec § 3.7 L1009.

    Shape: canonical ``ParityReport`` dataclass serialized verbatim —
    see ``_report_to_dict`` for the exact field list.
    """
    print(json.dumps(report_dict, indent=2, sort_keys=True, default=str))


# ---------------------------------------------------------------------------
# Audit-row writer — one CLI_VERIFY_SERVER_PARITY row per invocation
# ---------------------------------------------------------------------------


def _write_audit_row(
    metadata: dict[str, Any],
    *,
    status: str,
    error_message: str | None = None,
    cursor_factory: Callable | None = None,
    general_db: str = "General",
    skip: bool = False,
) -> int | None:
    """INSERT one ``CLI_VERIFY_SERVER_PARITY`` row into PipelineEventLog.

    Per D76 + spec § 3.7 L993. ONE row per invocation. Best-effort:
    failures are logged but do not affect the verdict exit code (parity
    with B188 / B189 / B190 / B218 audit-row patterns).

    Returns the IDENTITY value of the inserted row via SCOPE_IDENTITY().
    Returns None on failure (the JSON ``audit_event_id`` key is null).

    When ``skip=True`` (test path; main()'s ``no_audit_event``), the
    function returns None immediately without writing.
    """
    if skip:
        return None
    metadata_json = json.dumps(metadata, separators=(",", ":"), default=str)
    event_detail = (
        f"verify_server_parity / overall="
        f"{metadata.get('report', {}).get('overall', '?')} "
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
        logger.exception("Failed to write CLI_VERIFY_SERVER_PARITY audit row")
        return None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Top-level main() — programmatic entry point
# ---------------------------------------------------------------------------


def main(
    *,
    actor: str,
    baseline_path: str | None = None,
    server_name: str | None = None,
    fail_on_warning: bool = False,
    alert: bool | None = None,
    json_output: bool = False,
    verbose: bool = False,
    quiet: bool = False,
    justification: str | None = None,
    no_audit_event: bool = False,
    # ---- Injection hooks (test path) ----
    verify_fn: Callable | None = None,
    alert_fn: Callable | None = None,
    audit_cursor_factory: Callable | None = None,
    general_db: str | None = None,
) -> dict[str, Any]:
    """Programmatic entry — wraps M8 ``verify_server_parity()`` per § 3.7.

    Returns a dict matching the D76 audit-row Metadata shape (see module
    docstring for the canonical schema). Exit-code derivation per D74 +
    spec § 3.7 L1011-1014.

    Parameters
    ----------
    actor:
        Operator identity (per D75 + D76). REQUIRED.
    baseline_path:
        Override the baseline JSON path. Default ``DEFAULT_BASELINE_PATH``.
    server_name:
        Override the server identifier (defaults to $SERVER_NAME env or
        socket.gethostname() via M8).
    fail_on_warning:
        When True, warning-tier drift maps to exit 2 (fatal) per § 3.7.
    alert:
        When True/False, override the actor-based default. When None,
        use the § 3.7 L996 heuristic (True for actor in {automic, pipeline}).
    justification:
        Operator justification recorded in audit-row Metadata per D75.
    no_audit_event:
        When True, skip the CLI-level PipelineEventLog write (pipeline-
        programmatic callers per D75 + D76).
    verify_fn:
        Test-injection hook — override the M8 callable. Default resolves
        ``tools.verify_server_parity.verify_server_parity`` at call time.
    alert_fn:
        Test-injection hook — override the alert dispatcher callable.
        Default uses ``_fire_alert`` (which lazy-imports § 3.11).
    audit_cursor_factory:
        Test-injection hook — override the connection factory for the
        audit-row INSERT.
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

    resolved_baseline_path = baseline_path or DEFAULT_BASELINE_PATH

    # --alert default per § 3.7 L996: True when actor in {automic, pipeline}
    if alert is None:
        alert = actor in _ALERT_AUTO_ON_ACTORS

    # ---- Pre-populate result with input echoes for early-exit paths ----
    result: dict[str, Any] = {
        "event_kind": "parity_verify",
        "actor": actor,
        "justification": justification,
        "baseline_path": resolved_baseline_path,
        "fail_on_warning": bool(fail_on_warning),
        "alert": bool(alert),
        "server_name": server_name,
        "report": None,
        "exit_code": EXIT_SUCCESS,
        "started_at": started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "started_at_dt": started_at,
        "completed_at": None,
        "audit_event_id": None,
        "alert_fired": False,
        "errors": [],
    }

    # ---- Resolve the M8 verify_server_parity callable ----
    if verify_fn is None:
        try:
            verify_fn = _resolve_verify_fn()
        except Exception as exc:  # noqa: BLE001
            result["exit_code"] = EXIT_FATAL
            result["error_type"] = type(exc).__name__
            result["error_message"] = f"M8 module unavailable: {exc}"
            result["errors"].append(f"{type(exc).__name__}: {exc}")
            logger.error("Could not resolve verify_server_parity callable: %s", exc)
            if not quiet:
                print(
                    f"FATAL: M8 verify_server_parity unavailable: {exc}",
                    file=sys.stderr,
                )
            result["completed_at"] = datetime.now(
                timezone.utc
            ).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%SZ")
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

    # ---- Invoke M8 ----
    report_obj: Any = None
    try:
        report_obj = verify_fn(
            baseline_path=resolved_baseline_path,
            server_name=server_name,
            fail_on_warning=fail_on_warning,
        )
    except ParityBaselineMissing as exc:
        result["exit_code"] = EXIT_FATAL
        result["error_type"] = "ParityBaselineMissing"
        result["error_message"] = str(exc)[:4000]
        result["errors"].append(f"ParityBaselineMissing: {exc}")
        logger.error("Baseline JSON missing or malformed: %s", exc)
        if not quiet:
            # Per § 3.7 L982: "stderr message 'baseline JSON missing or malformed'"
            print(
                f"FATAL: baseline JSON missing or malformed: {exc}",
                file=sys.stderr,
            )
    except ParityProbeError as exc:
        result["exit_code"] = EXIT_FATAL
        result["error_type"] = "ParityProbeError"
        result["error_message"] = str(exc)[:4000]
        result["errors"].append(f"ParityProbeError: {exc}")
        logger.error("System probe failed: %s", exc)
        if not quiet:
            print(f"FATAL: parity probe failed: {exc}", file=sys.stderr)
        # Attach metadata if available (F21 probe diagnostics)
        if hasattr(exc, "metadata") and isinstance(exc.metadata, dict):
            result["probe_metadata"] = exc.metadata
    except ParityFatalError as exc:
        result["exit_code"] = EXIT_FATAL
        result["error_type"] = "ParityFatalError"
        result["error_message"] = str(exc)[:4000]
        result["errors"].append(f"ParityFatalError: {exc}")
        logger.error("Fatal-tier parity drift: %s", exc)
        if not quiet:
            print(f"FATAL: parity drift: {exc}", file=sys.stderr)
        # ParityFatalError carries metadata including the report counts;
        # fish out what we can for the audit row.
        if hasattr(exc, "metadata") and isinstance(exc.metadata, dict):
            result["fatal_metadata"] = exc.metadata
    except Exception as exc:  # noqa: BLE001
        # Unexpected -> exit 2 (fatal) per § 1.8 default for non-typed errors.
        result["exit_code"] = EXIT_FATAL
        result["error_type"] = type(exc).__name__
        result["error_message"] = str(exc)[:4000]
        result["errors"].append(f"{type(exc).__name__}: {exc}")
        logger.exception("Unexpected exception in verify_server_parity")
        if not quiet:
            print(
                f"FATAL: unexpected exception in verify_server_parity: {exc}",
                file=sys.stderr,
            )

    # ---- Map ParityReport -> exit code per § 3.7 L1011-1014 ----
    report_dict: dict[str, Any] | None = None
    if report_obj is not None:
        report_dict = _report_to_dict(report_obj)
        result["report"] = report_dict
        overall = str(report_dict.get("overall", "fail")).lower()
        if overall == "pass":
            result["exit_code"] = EXIT_SUCCESS
        elif overall == "warn":
            # Per § 3.7 L1012: warning-tier drift -> exit 1
            # fail_on_warning=True case: M8 already raised ParityFatalError
            # before we got here (verify_server_parity body raises when
            # fail_on_warning AND warning_count > 0).
            result["exit_code"] = EXIT_WARNING
        elif overall == "fail":
            # Defensive — M8 typically raises ParityFatalError on fatal,
            # but if a caller injects a report dict directly with
            # overall='fail', we still honor the exit-code contract.
            result["exit_code"] = EXIT_FATAL
        else:
            # Unknown overall value -> fatal per § 3.7 L1013-1014 default.
            logger.warning(
                "Unknown ParityReport.overall=%r; defaulting to exit 2", overall
            )
            result["exit_code"] = EXIT_FATAL

    # ---- Fire alert if warranted (§ 3.7 L996) ----
    if alert and result["exit_code"] in (EXIT_WARNING, EXIT_FATAL):
        severity_label = "fatal" if result["exit_code"] == EXIT_FATAL else "warning"
        fire = alert_fn if alert_fn is not None else _fire_alert
        try:
            fired = bool(
                fire(
                    report_dict=report_dict or {},
                    severity=severity_label,
                    actor=actor,
                    baseline_path=resolved_baseline_path,
                )
            )
        except Exception:  # noqa: BLE001
            logger.exception("alert_fn raised during fire-and-forget")
            fired = False
        result["alert_fired"] = fired

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
        # Spec § 3.7 L1009 canonical shape: the ParityReport dict ONLY.
        # Internal bookkeeping (started_at, errors, etc.) stays in the
        # programmatic return dict but is NOT exposed via --json per spec.
        if report_dict is not None:
            _emit_json(report_dict)
        else:
            # No report (error path before M8 returned) — emit a minimal
            # JSON shape that surfaces the error.
            _emit_json(
                {
                    "overall": "fail",
                    "fatal_count": 0,
                    "warning_count": 0,
                    "informational_count": 0,
                    "match_count": 0,
                    "checks": [],
                    "server_name": server_name,
                    "baseline_name": None,
                    "baseline_pinned_at": None,
                    "error_type": result.get("error_type"),
                    "error_message": result.get("error_message"),
                }
            )
    elif not quiet and report_dict is not None:
        _emit_human_summary(report_dict, baseline_path=resolved_baseline_path)

    return result


# ---------------------------------------------------------------------------
# CLI argv entry point
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    """Alias for :func:`_build_parser` — Tier 0 scaffold contract."""
    return _build_parser()


def _build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser per spec § 3.7 + § 1.4 canonical args.

    Per Pitfall #9.b invented-parameter rule (HANDOFF §8): this parser
    does NOT accept ``--server`` (handled via $SERVER_NAME env / hostname
    inside M8) nor invented args. Tier 0 assertion (h) verifies argparse
    REJECTS the spec-listed invented arg names.
    """
    parser = argparse.ArgumentParser(
        description=(
            "CLI shim for M8 verify_server_parity() per Round 4 § 3.7. "
            "Reads parity_baseline.json + probes the server state + emits "
            "ONE CLI_VERIFY_SERVER_PARITY audit row. Exit code 0/1/2 per "
            "D65 severity tier (match/warn/fatal)."
        ),
    )

    # ---- D75 canonical args (per spec § 1.4) ----
    parser.add_argument(
        "--actor",
        default=None,
        help=(
            "Operator identity (per D75 + D76). One of operator / automic / "
            "pipeline. Auto-detected via TTY / AUTOMIC_RUN_ID env when omitted."
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
            "Emit canonical ParityReport dict per spec § 3.7 L1009 "
            "(server_name, baseline_name, baseline_pinned_at, checks, "
            "fatal_count, warning_count, informational_count, match_count, "
            "overall) instead of human summary."
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
    parser.add_argument(
        "--no-audit-event",
        action="store_true",
        dest="no_audit_event",
        help=(
            "Skip the CLI-level PipelineEventLog write. Pipeline-programmatic "
            "callers set this when the parent operation has its own audit row "
            "(per D75 + D76)."
        ),
    )

    # ---- § 3.7 tool-specific args (per L987-997) ----
    parser.add_argument(
        "--baseline-path",
        default=None,
        help=(
            f"Override the baseline JSON path. Default {DEFAULT_BASELINE_PATH!r} "
            "(per Round 2 § 4.1). Useful for pre-deployment baseline validation."
        ),
    )
    parser.add_argument(
        "--fail-on-warning",
        action="store_true",
        dest="fail_on_warning",
        help=(
            "Map warning-tier drift to fatal exit (2 instead of 1). Useful "
            "for strict pre-deployment validation. Default OFF (warning is "
            "exit 1; alert-only)."
        ),
    )
    parser.add_argument(
        "--alert",
        action="store_true",
        dest="alert_explicit",
        help=(
            "Fire ops-channel alert via tools/alert_dispatcher.py (§ 3.11) on "
            "warning or fatal drift. Default ON when --actor automic or "
            "--actor pipeline; explicit --alert overrides to ON regardless of "
            "actor."
        ),
    )
    parser.add_argument(
        "--no-alert",
        action="store_true",
        dest="no_alert",
        help=(
            "Suppress alert dispatch even when --actor is automic/pipeline. "
            "Useful for ops dry-runs."
        ),
    )

    return parser


def _validate_args(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    """Validate --alert / --no-alert mutex per § 3.7 L996."""
    if args.alert_explicit and args.no_alert:
        parser.error(
            "--alert and --no-alert are mutually exclusive — pick one"
        )
    return None


def cli_main() -> int:
    """Argv entry point — argparse + main() + return exit code per D74.

    Exit codes (always one of 0 / 1 / 2 per D74 + spec § 3.7 L1011-1014):
        - 0: all match OR only informational-tier drift
        - 1: warning-tier drift
        - 2: fatal-tier drift OR ParityBaselineMissing OR ParityProbeError
    """
    parser = _build_parser()
    args = parser.parse_args()
    _validate_args(args, parser)

    actor = args.actor or _detect_actor()

    # Resolve --alert per § 3.7 L996 heuristic + flag overrides
    if args.no_alert:
        alert: bool | None = False
    elif args.alert_explicit:
        alert = True
    else:
        alert = None  # main() applies the actor heuristic

    try:
        result = main(
            actor=actor,
            baseline_path=args.baseline_path,
            server_name=None,
            fail_on_warning=args.fail_on_warning,
            alert=alert,
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
            f"FATAL: verify_server_parity_cli unexpected exception:\n{tb[:1000]}",
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


__all__ = [
    "EXIT_SUCCESS",
    "EXIT_WARNING",
    "EXIT_FATAL",
    "EVENT_TYPE",
    "DEFAULT_BASELINE_PATH",
    "main",
    "cli_main",
    "_build_parser",
    "_build_arg_parser",
    "_detect_actor",
]


if __name__ == "__main__":
    sys.exit(cli_main())
