"""B-546 — Operator CLI: flip ``UdmTablesList.CDCMode`` per RB-16 procedure.

Per D63 + D125 (3-mode CDCMode dispatch) + the canonical transition matrix at
``docs/migration/UDM_PIPELINE_CDC_MODE_3WAY_DISPATCH_PLAN_2026-05-19.md`` §2.3.

What this tool does
-------------------

Atomic per-table CDCMode flip:

  BEGIN TRAN
    INSERT PipelineEventLog (EventType='CLI_FLIP_CDC_MODE', ...)
    UPDATE UdmTablesList SET CDCMode=<target> WHERE SourceName=<x> AND ...
  COMMIT

Validates transitions per the canonical matrix (plan §2.3):

* `change_detect` → `parquet_snapshot` — ALLOWED but FLAGGED as RISKY (no
  shadow validation period; operator MUST acknowledge via --force)
* `change_detect` → `both` — ALLOWED (safe; RB-16 step 1)
* `both` → `parquet_snapshot` — ALLOWED (RB-16 step 2; canonical cutover
  after ≥30-day shadow-write validation)
* `parquet_snapshot` → `both` — ALLOWED (defensive rollback; RB-16 rollback)
* `parquet_snapshot` → `change_detect` — ALLOWED (full rollback)
* `both` → `change_detect` — ALLOWED (rollback during shadow period)
* Same-mode "flip" (e.g., `both` → `both`) — BLOCKED (no-op exit code 2)

CLI contract
------------

::

    python3 tools/flip_cdc_mode.py --dry-run \\
        --source DNA --table ACCT --mode both \\
        --actor pipeline-lead --justification "B-546 ACCT shadow-write start"

    python3 tools/flip_cdc_mode.py --apply \\
        --source DNA --table ACCT --mode both \\
        --actor pipeline-lead --justification "B-546 ACCT shadow-write start"

    # Risky direct cutover requires --force (skips shadow validation period):
    python3 tools/flip_cdc_mode.py --apply --force \\
        --source DNA --table SOMETABLE --mode parquet_snapshot \\
        --actor pipeline-lead --justification "Direct cutover; risk acknowledged"

Exit codes (D74)
----------------

* 0 — SUCCESS (flip applied OR dry-run completed cleanly)
* 1 — WARNING (risky direct change_detect→parquet_snapshot transition without
  --force; OR target mode same as current; etc.)
* 2 — BLOCKED (no-op: target == current OR invalid transition without --force)
* 3 — FATAL (UdmTablesList row missing for source.table; SQL error)

Audit-row family (D76)
----------------------

``CLI_FLIP_CDC_MODE`` (registered in CLAUDE.md L209+ CLI_* family registry).
Metadata: ``current_mode`` / ``target_mode`` / ``source_name`` / ``table_name``
/ ``transition_risk`` / ``actor`` / ``justification`` / ``dry_run``.

Per-call invariants
-------------------

* Dry-run (default per D75): no UPDATE, no INSERT, no DB state change. Audit
  row NOT written on dry-run (preserves the no-side-effects contract).
* Atomic: UPDATE + INSERT in single transaction. Either both commit or
  both rollback. No partial-state risk.
* Idempotent: re-running with same target mode is a no-op (exit code 2);
  re-running with different target mode performs a fresh flip with fresh
  audit row.

Execution classification (per ``udm-execution-classifier``)
-----------------------------------------------------------

* **Trigger**: Manual CLI (operator-driven; never scheduled)
* **Frequency**: Per-table per-cutover-step (typically once per table during
  the 30-day shadow-write period + once again at production cutover)
* **Audit-row family**: ``CLI_FLIP_CDC_MODE``
* **Idempotency**: YES via no-op exit code 2

Source: B-546 (D125 plan §7 B-NEW-5). Closure target: Phase 2 R2.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import utils.configuration as config
from utils.connections import get_connection

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# Canonical D63 + D125 CDCMode values — mirrors
# `migrations/cdc_mode_column.py::ALLOWED_CDC_MODE_VALUES` byte-identical.
EVENT_TYPE = "CLI_FLIP_CDC_MODE"
ALLOWED_MODES = ("change_detect", "parquet_snapshot", "both")

# Exit codes per D74
EXIT_SUCCESS = 0
EXIT_WARNING = 1
EXIT_BLOCKED = 2
EXIT_FATAL = 3


# Transition matrix per plan §2.3 — maps (from, to) → "ALLOWED" / "RISKY" / "BLOCKED"
# (Same-mode entries are implicitly BLOCKED via no-op detection earlier.)
_TRANSITION_MATRIX = {
    ("change_detect", "parquet_snapshot"): "RISKY",  # Requires --force
    ("change_detect", "both"): "ALLOWED",
    ("both", "parquet_snapshot"): "ALLOWED",
    ("parquet_snapshot", "both"): "ALLOWED",
    ("parquet_snapshot", "change_detect"): "ALLOWED",
    ("both", "change_detect"): "ALLOWED",
}


def classify_transition(current: str, target: str) -> str:
    """Return one of {'NOOP', 'ALLOWED', 'RISKY', 'UNKNOWN'}.

    'NOOP' — current == target (idempotency short-circuit)
    'ALLOWED' — canonical transition per plan §2.3
    'RISKY' — direct change_detect→parquet_snapshot (skips shadow period)
    'UNKNOWN' — pair not in the canonical matrix (defensive default; should
        not happen if both values are in ALLOWED_MODES)
    """
    if current == target:
        return "NOOP"
    return _TRANSITION_MATRIX.get((current, target), "UNKNOWN")


def _get_current_mode(cursor, source: str, table: str) -> str | None:
    """Return the current CDCMode for (source, table) OR None if row missing."""

    cursor.execute(
        f"SELECT CDCMode FROM [{config.GENERAL_DB}].dbo.UdmTablesList "
        f"WHERE SourceName = ? AND SourceObjectName = ?",
        source, table,
    )
    row = cursor.fetchone()
    return row[0] if row else None


def _write_audit_row(cursor, *, source: str, table: str, current_mode: str,
                     target_mode: str, transition_risk: str, actor: str,
                     justification: str, status: str = "SUCCESS",
                     error_message: str | None = None) -> None:
    metadata = {
        "source_name": source,
        "table_name": table,
        "current_mode": current_mode,
        "target_mode": target_mode,
        "transition_risk": transition_risk,
        "actor": actor,
        "justification": justification,
        "dry_run": False,
    }
    cursor.execute(
        f"INSERT INTO [{config.GENERAL_DB}].ops.PipelineEventLog "
        f"(BatchId, TableName, SourceName, EventType, EventDetail, "
        f" StartedAt, CompletedAt, Status, ErrorMessage, Metadata) "
        f"VALUES (NEXT VALUE FOR [{config.GENERAL_DB}].ops.PipelineBatchSequence, "
        f"        ?, ?, ?, ?, SYSUTCDATETIME(), SYSUTCDATETIME(), ?, ?, ?)",
        table, source, EVENT_TYPE,
        f"flip {current_mode} -> {target_mode}",
        status, error_message, json.dumps(metadata),
    )


def apply(connection, *, source: str, table: str, target_mode: str,
          actor: str, justification: str, dry_run: bool = True,
          force: bool = False) -> dict:
    """Apply or dry-run a CDCMode flip for (source, table).

    Preconditions: ``connection`` MUST have ``autocommit=False`` —
    ``apply()`` controls the transaction so UPDATE + audit row commit
    atomically.

    Returns a result dict with keys: ``event_kind`` / ``exit_code`` /
    ``current_mode`` / ``target_mode`` / ``transition_risk`` /
    ``source`` / ``table`` / ``dry_run``.
    """

    if target_mode not in ALLOWED_MODES:
        return {
            "event_kind": "fatal",
            "exit_code": EXIT_FATAL,
            "error": f"Invalid target_mode {target_mode!r}; must be one of "
                     f"{ALLOWED_MODES}",
            "source": source, "table": table,
            "current_mode": None, "target_mode": target_mode,
            "transition_risk": "UNKNOWN", "dry_run": dry_run,
        }

    cursor = connection.cursor()
    current_mode = _get_current_mode(cursor, source, table)

    if current_mode is None:
        cursor.close()
        return {
            "event_kind": "fatal",
            "exit_code": EXIT_FATAL,
            "error": f"UdmTablesList row missing for {source}.{table} — "
                     f"run `python3 -m discover_pks --source {source} "
                     f"--table {table}` OR verify the row exists",
            "source": source, "table": table,
            "current_mode": None, "target_mode": target_mode,
            "transition_risk": "UNKNOWN", "dry_run": dry_run,
        }

    transition_risk = classify_transition(current_mode, target_mode)

    if transition_risk == "NOOP":
        cursor.close()
        return {
            "event_kind": "noop",
            "exit_code": EXIT_BLOCKED,
            "message": f"CDCMode for {source}.{table} is already "
                       f"{current_mode!r}; no flip needed",
            "source": source, "table": table,
            "current_mode": current_mode, "target_mode": target_mode,
            "transition_risk": transition_risk, "dry_run": dry_run,
        }

    if transition_risk == "RISKY" and not force:
        cursor.close()
        return {
            "event_kind": "blocked",
            "exit_code": EXIT_BLOCKED,
            "message": (
                f"Direct {current_mode} -> {target_mode} cutover SKIPS the "
                f"≥30-day shadow-write validation period per RB-16. Re-run "
                f"with --force to acknowledge the risk + bypass this check, "
                f"OR follow the safer 2-step path: change_detect -> both "
                f"(for ≥30 days) -> parquet_snapshot."
            ),
            "source": source, "table": table,
            "current_mode": current_mode, "target_mode": target_mode,
            "transition_risk": transition_risk, "dry_run": dry_run,
        }

    if transition_risk == "UNKNOWN":
        cursor.close()
        return {
            "event_kind": "fatal",
            "exit_code": EXIT_FATAL,
            "error": (
                f"Transition {current_mode!r} -> {target_mode!r} is NOT in "
                f"the canonical matrix per plan §2.3. Check CDCMode value "
                f"integrity in UdmTablesList for {source}.{table}."
            ),
            "source": source, "table": table,
            "current_mode": current_mode, "target_mode": target_mode,
            "transition_risk": "UNKNOWN", "dry_run": dry_run,
        }

    # ALLOWED or (RISKY + --force) — proceed
    if dry_run:
        logger.info(
            "[DRY RUN] Would flip CDCMode for %s.%s: %s -> %s "
            "(risk=%s, actor=%s)",
            source, table, current_mode, target_mode, transition_risk, actor,
        )
        cursor.close()
        return {
            "event_kind": "dry_run",
            "exit_code": EXIT_SUCCESS,
            "source": source, "table": table,
            "current_mode": current_mode, "target_mode": target_mode,
            "transition_risk": transition_risk, "dry_run": True,
            "would_flip": True,
        }

    # Apply path — atomic UPDATE + audit row
    try:
        cursor.execute(
            f"UPDATE [{config.GENERAL_DB}].dbo.UdmTablesList "
            f"SET CDCMode = ? "
            f"WHERE SourceName = ? AND SourceObjectName = ?",
            target_mode, source, table,
        )
        _write_audit_row(
            cursor,
            source=source, table=table,
            current_mode=current_mode, target_mode=target_mode,
            transition_risk=transition_risk,
            actor=actor, justification=justification,
        )
        connection.commit()
        result = {
            "event_kind": "apply",
            "exit_code": EXIT_WARNING if transition_risk == "RISKY" else EXIT_SUCCESS,
            "source": source, "table": table,
            "current_mode": current_mode, "target_mode": target_mode,
            "transition_risk": transition_risk, "dry_run": False,
            "flipped": True,
        }
    except Exception as exc:
        connection.rollback()
        result = {
            "event_kind": "error",
            "exit_code": EXIT_FATAL,
            "error": str(exc)[:4000],
            "source": source, "table": table,
            "current_mode": current_mode, "target_mode": target_mode,
            "transition_risk": transition_risk, "dry_run": False,
        }
        try:
            _write_audit_row(
                cursor,
                source=source, table=table,
                current_mode=current_mode, target_mode=target_mode,
                transition_risk=transition_risk,
                actor=actor, justification=justification,
                status="FAILED", error_message=str(exc)[:4000],
            )
            connection.commit()
        except Exception:
            pass
        cursor.close()
        raise

    cursor.close()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="B-546 CDCMode flip CLI (D63 + D125)")
    parser.add_argument("--apply", action="store_true",
                        help="Execute the flip (default is dry-run per D75)")
    parser.add_argument("--source", required=True,
                        help="Source name (e.g., DNA, CCM, EPICOR)")
    parser.add_argument("--table", required=True,
                        help="Source object name (e.g., ACCT)")
    parser.add_argument("--mode", required=True, choices=list(ALLOWED_MODES),
                        help="Target CDCMode value per D125 3-value enum")
    parser.add_argument("--actor", required=True, help="Auth principal (D75)")
    parser.add_argument("--justification", required=True, help="Why running (D75)")
    parser.add_argument("--force", action="store_true",
                        help="Acknowledge + bypass risky-transition guard "
                             "(direct change_detect->parquet_snapshot)")
    args = parser.parse_args()

    dry_run = not args.apply
    conn = get_connection(config.GENERAL_DB)
    conn.autocommit = False
    try:
        result = apply(
            conn,
            source=args.source, table=args.table, target_mode=args.mode,
            actor=args.actor, justification=args.justification,
            dry_run=dry_run, force=args.force,
        )
        logger.info("flip_cdc_mode result: %s", json.dumps(result, indent=2))
        return int(result["exit_code"])
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
