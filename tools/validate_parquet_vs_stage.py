"""B-545 — Operator CLI: parity check between Parquet snapshot row counts + Bronze.

Per D125 plan §7 B-NEW-4 + §8.3 R2 sequence. For tables in `CDCMode='both'`
shadow-write mode (per D63 + D125 dispatch), compares the per-snapshot row
count recorded by `parquet_writer.write_parquet_snapshot()` against the
current Bronze active-row count for the same (source, table). Surfaces
drift before operators decide to flip to `parquet_snapshot` mode.

**v1 scope (this implementation)**: row-count parity check using metadata
already in `ParquetSnapshotRegistry.RowCount` + a Bronze `SELECT COUNT(*) WHERE
UdmActiveFlag=1` query per table. NO Parquet file I/O; NO per-PK hash
comparison. Operationally useful as a fast nightly sanity check during the
30-day shadow-write validation period per RB-16 (B-547).

**v2 scope (deferred; track as new B-N if needed)**: per-PK hash comparison
(read Parquet via polars + extract `_row_hash` + join against Bronze
`UdmHash` for active rows). Requires polars dep + heavyweight test mocks.

What this tool does
-------------------

For each table where `UdmTablesList.CDCMode = 'both'`:

1. Query latest `ParquetSnapshotRegistry` row count for (source, table,
   latest BusinessDate)
2. Query Bronze active-row count: `SELECT COUNT(*) FROM
   UDM_Bronze.{source}.{table}_scd2_python WHERE UdmActiveFlag = 1`
3. Compute drift: `abs(parquet_count - bronze_count) / parquet_count`
4. Verdict per drift threshold:

   - **CLEAN** (drift ≤ tolerance; default 1%): parity looks good
   - **DRIFT** (tolerance < drift ≤ 5%): minor drift; investigation recommended
   - **MAJOR_DRIFT** (drift > 5%): significant divergence; cutover should be
     held pending root-cause analysis

CLI contract
------------

::

    python3 tools/validate_parquet_vs_stage.py --dry-run \\
        --actor pipeline-lead --justification "B-545 nightly parity sanity"

    python3 tools/validate_parquet_vs_stage.py --apply \\
        --actor pipeline-lead --justification "B-545 nightly parity sanity"

    # Single-table mode for targeted investigation:
    python3 tools/validate_parquet_vs_stage.py --apply \\
        --source DNA --table ACCT \\
        --actor pipeline-lead --justification "B-545 ACCT investigation"

Exit codes (D74)
----------------

* 0 — SUCCESS (all in-scope tables parity CLEAN)
* 1 — WARNING (at least one table DRIFT but no MAJOR_DRIFT)
* 2 — BLOCKED (at least one table MAJOR_DRIFT; cutover should not proceed)
* 3 — FATAL (SQL error; registry query failure; etc.)

Audit-row family (D76)
----------------------

``CLI_VALIDATE_PARQUET_VS_STAGE`` (next CLI_* family slot; registered in
CLAUDE.md L209+). One audit row per invocation summarizing all tables
checked + their verdicts. Metadata: ``tables_checked`` / ``clean`` /
``drift`` / ``major_drift`` / ``actor`` / ``justification`` / ``dry_run`` /
``per_table_verdicts`` (JSON-serialized list of per-table results).

Per-call invariants
-------------------

* Read-only against Bronze + registry (no UPDATE / DELETE / INSERT to those
  tables). Only writes are: PipelineEventLog audit row (skipped on dry-run).
* `--dry-run` default per D75: parity verdict is COMPUTED + LOGGED but the
  audit row is NOT written.
* `--apply` writes the audit row.
* `--source` + `--table` flags scope to a single table; without them, all
  tables with `CDCMode='both'` are checked.

Execution classification (per ``udm-execution-classifier``)
-----------------------------------------------------------

* **Trigger**: Manual CLI (operator-driven) OR scheduled nightly during
  shadow-write validation periods (per RB-16 30-day shadow period)
* **Frequency**: Daily during validation; on-demand for investigation
* **Audit-row family**: ``CLI_VALIDATE_PARQUET_VS_STAGE``
* **Idempotency**: YES (read-only check; safe to re-run any frequency)

Source: B-545 (D125 plan §7 B-NEW-4). Closure target: Phase 2 R2.
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


EVENT_TYPE = "CLI_VALIDATE_PARQUET_VS_STAGE"

# Exit codes per D74
EXIT_SUCCESS = 0
EXIT_WARNING = 1
EXIT_BLOCKED = 2
EXIT_FATAL = 3

# Parity verdict thresholds
DRIFT_TOLERANCE_PCT = 0.01  # 1% — anything below is CLEAN
MAJOR_DRIFT_THRESHOLD_PCT = 0.05  # 5% — anything above is MAJOR_DRIFT

# Parity verdicts
VERDICT_CLEAN = "CLEAN"
VERDICT_DRIFT = "DRIFT"
VERDICT_MAJOR_DRIFT = "MAJOR_DRIFT"
VERDICT_FATAL = "FATAL"


def classify_parity(parquet_count: int, bronze_count: int) -> str:
    """Return parity verdict given Parquet + Bronze row counts.

    Computes |parquet - bronze| / parquet and compares against
    DRIFT_TOLERANCE_PCT + MAJOR_DRIFT_THRESHOLD_PCT.

    Edge cases:
    - parquet_count == 0 AND bronze_count == 0 → CLEAN (both empty; matches)
    - parquet_count == 0 AND bronze_count > 0 → MAJOR_DRIFT (Bronze has data
      Parquet doesn't capture)
    - parquet_count > 0 AND bronze_count == 0 → MAJOR_DRIFT (Parquet has data
      Bronze doesn't have; likely cutover-in-progress edge case)
    """

    if parquet_count == 0 and bronze_count == 0:
        return VERDICT_CLEAN
    if parquet_count == 0 or bronze_count == 0:
        return VERDICT_MAJOR_DRIFT

    drift = abs(parquet_count - bronze_count) / parquet_count
    if drift <= DRIFT_TOLERANCE_PCT:
        return VERDICT_CLEAN
    if drift <= MAJOR_DRIFT_THRESHOLD_PCT:
        return VERDICT_DRIFT
    return VERDICT_MAJOR_DRIFT


def _query_both_mode_tables(cursor) -> list[tuple[str, str]]:
    """Return [(SourceName, SourceObjectName), ...] for all tables in
    `'both'` mode per D125 dispatch.
    """

    cursor.execute(
        f"SELECT SourceName, SourceObjectName "
        f"FROM [{config.GENERAL_DB}].dbo.UdmTablesList "
        f"WHERE CDCMode = 'both'"
    )
    return [(row[0], row[1]) for row in cursor.fetchall()]


def _query_latest_parquet_row_count(cursor, source: str, table: str) -> int | None:
    """Return the RowCount of the latest `ParquetSnapshotRegistry` row for
    (source, table); None if no registry row exists."""

    cursor.execute(
        f"SELECT TOP 1 RowCount "
        f"FROM [{config.GENERAL_DB}].ops.ParquetSnapshotRegistry "
        f"WHERE SourceName = ? AND TableName = ? "
        f"ORDER BY BusinessDate DESC, CreatedAt DESC",
        source, table,
    )
    row = cursor.fetchone()
    return int(row[0]) if row is not None else None


def _query_bronze_active_row_count(cursor, source: str, table: str) -> int:
    """Return Bronze active-row count for (source, table). Bronze table name
    follows the canonical `UDM_Bronze.{source}.{table}_scd2_python` convention."""

    bronze_table = (
        f"[{config.BRONZE_DB}].[{source}].[{table}_scd2_python]"
    )
    cursor.execute(f"SELECT COUNT(*) FROM {bronze_table} WHERE UdmActiveFlag = 1")
    row = cursor.fetchone()
    return int(row[0]) if row is not None else 0


def check_table_parity(cursor, source: str, table: str) -> dict:
    """Run parity check for a single (source, table). Returns dict with
    verdict + per-table metrics.

    Catches per-table SQL exceptions + emits VERDICT_FATAL with error
    captured rather than propagating (so a single table failure doesn't
    block parity checks for other tables in a multi-table run).
    """

    try:
        parquet_count = _query_latest_parquet_row_count(cursor, source, table)
        if parquet_count is None:
            return {
                "source": source, "table": table,
                "verdict": VERDICT_FATAL,
                "error": "No ParquetSnapshotRegistry row found — table may not "
                         "have been processed in 'both' mode yet",
                "parquet_count": None, "bronze_count": None, "drift_pct": None,
            }
        bronze_count = _query_bronze_active_row_count(cursor, source, table)
        verdict = classify_parity(parquet_count, bronze_count)
        drift_pct = (
            abs(parquet_count - bronze_count) / parquet_count
            if parquet_count > 0 else None
        )
        return {
            "source": source, "table": table,
            "verdict": verdict,
            "parquet_count": parquet_count,
            "bronze_count": bronze_count,
            "drift_pct": drift_pct,
        }
    except Exception as exc:  # noqa: BLE001 — defensive per-table guard
        return {
            "source": source, "table": table,
            "verdict": VERDICT_FATAL,
            "error": str(exc)[:1000],
            "parquet_count": None, "bronze_count": None, "drift_pct": None,
        }


def _write_audit_row(cursor, *, actor: str, justification: str,
                     tables_checked: int, clean: int, drift: int,
                     major_drift: int, per_table_verdicts: list[dict],
                     status: str = "SUCCESS",
                     error_message: str | None = None) -> None:
    metadata = {
        "tables_checked": tables_checked,
        "clean": clean,
        "drift": drift,
        "major_drift": major_drift,
        "actor": actor,
        "justification": justification,
        "dry_run": False,
        "per_table_verdicts": per_table_verdicts,
    }
    cursor.execute(
        f"INSERT INTO [{config.GENERAL_DB}].ops.PipelineEventLog "
        f"(BatchId, TableName, SourceName, EventType, EventDetail, "
        f" StartedAt, CompletedAt, Status, ErrorMessage, Metadata) "
        f"VALUES (NEXT VALUE FOR [{config.GENERAL_DB}].ops.PipelineBatchSequence, "
        f"        NULL, NULL, ?, ?, SYSUTCDATETIME(), SYSUTCDATETIME(), ?, ?, ?)",
        EVENT_TYPE,
        f"{tables_checked} tables / {clean} clean / {drift} drift / {major_drift} major",
        status, error_message, json.dumps(metadata),
    )


def derive_exit_code(per_table_verdicts: list[dict]) -> int:
    """Compute overall exit code from per-table verdicts.

    Rules (most-severe-wins):
    - Any FATAL → EXIT_FATAL
    - Any MAJOR_DRIFT → EXIT_BLOCKED (cutover should be held)
    - Any DRIFT → EXIT_WARNING (investigation recommended)
    - All CLEAN → EXIT_SUCCESS
    """

    if not per_table_verdicts:
        # No tables in 'both' mode — vacuously clean
        return EXIT_SUCCESS

    if any(v["verdict"] == VERDICT_FATAL for v in per_table_verdicts):
        return EXIT_FATAL
    if any(v["verdict"] == VERDICT_MAJOR_DRIFT for v in per_table_verdicts):
        return EXIT_BLOCKED
    if any(v["verdict"] == VERDICT_DRIFT for v in per_table_verdicts):
        return EXIT_WARNING
    return EXIT_SUCCESS


def apply(connection, *, actor: str, justification: str,
          source: str | None = None, table: str | None = None,
          dry_run: bool = True) -> dict:
    """Run the parity check.

    When source + table provided: check that single table.
    When omitted: check ALL tables with `CDCMode='both'`.

    Returns result dict with `exit_code`, `per_table_verdicts`, and counts.
    """

    cursor = connection.cursor()

    # Build list of tables to check
    if source and table:
        tables = [(source, table)]
    elif source or table:
        cursor.close()
        return {
            "event_kind": "fatal",
            "exit_code": EXIT_FATAL,
            "error": "--source and --table must be provided together (single-table mode) OR neither (all-tables mode)",
            "tables_checked": 0, "clean": 0, "drift": 0, "major_drift": 0,
            "per_table_verdicts": [], "dry_run": dry_run,
        }
    else:
        try:
            tables = _query_both_mode_tables(cursor)
        except Exception as exc:  # noqa: BLE001 — query failure is fatal
            cursor.close()
            return {
                "event_kind": "fatal",
                "exit_code": EXIT_FATAL,
                "error": f"UdmTablesList query failed: {str(exc)[:500]}",
                "tables_checked": 0, "clean": 0, "drift": 0, "major_drift": 0,
                "per_table_verdicts": [], "dry_run": dry_run,
            }

    # Run per-table parity checks
    per_table_verdicts = [
        check_table_parity(cursor, src, tbl) for src, tbl in tables
    ]

    # Aggregate counts
    clean = sum(1 for v in per_table_verdicts if v["verdict"] == VERDICT_CLEAN)
    drift = sum(1 for v in per_table_verdicts if v["verdict"] == VERDICT_DRIFT)
    major_drift = sum(
        1 for v in per_table_verdicts if v["verdict"] == VERDICT_MAJOR_DRIFT
    )
    exit_code = derive_exit_code(per_table_verdicts)

    if dry_run:
        logger.info(
            "[DRY RUN] parity check: %d tables / %d clean / %d drift / %d major; exit_code=%d",
            len(tables), clean, drift, major_drift, exit_code,
        )
        cursor.close()
        return {
            "event_kind": "dry_run",
            "exit_code": exit_code,
            "tables_checked": len(tables),
            "clean": clean, "drift": drift, "major_drift": major_drift,
            "per_table_verdicts": per_table_verdicts,
            "dry_run": True,
        }

    # Apply: write audit row + commit
    try:
        status = "SUCCESS" if exit_code <= EXIT_WARNING else "FAILED"
        error_msg = (
            None if exit_code <= EXIT_WARNING
            else f"Parity check exit_code={exit_code} (drift={drift} major={major_drift})"
        )
        _write_audit_row(
            cursor,
            actor=actor, justification=justification,
            tables_checked=len(tables), clean=clean, drift=drift,
            major_drift=major_drift, per_table_verdicts=per_table_verdicts,
            status=status, error_message=error_msg,
        )
        connection.commit()
    except Exception as exc:
        connection.rollback()
        cursor.close()
        raise

    cursor.close()
    return {
        "event_kind": "apply",
        "exit_code": exit_code,
        "tables_checked": len(tables),
        "clean": clean, "drift": drift, "major_drift": major_drift,
        "per_table_verdicts": per_table_verdicts,
        "dry_run": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="B-545 Parquet vs Bronze parity check (D125 §7 B-NEW-4)"
    )
    parser.add_argument("--apply", action="store_true",
                        help="Execute + write audit row (default is dry-run per D75)")
    parser.add_argument("--source", default=None,
                        help="Single-table mode: source name (must pair with --table)")
    parser.add_argument("--table", default=None,
                        help="Single-table mode: source object name (must pair with --source)")
    parser.add_argument("--actor", required=True, help="Auth principal (D75)")
    parser.add_argument("--justification", required=True, help="Why running (D75)")
    args = parser.parse_args()

    dry_run = not args.apply
    conn = get_connection(config.GENERAL_DB)
    conn.autocommit = False
    try:
        result = apply(
            conn,
            actor=args.actor, justification=args.justification,
            source=args.source, table=args.table,
            dry_run=dry_run,
        )
        logger.info("validate_parquet_vs_stage result: %s",
                    json.dumps(result, indent=2, default=str))
        return int(result["exit_code"])
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
