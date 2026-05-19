"""B-545 — Operator CLI: parity check between Parquet snapshot row counts + Bronze.

Per D125 plan §7 B-NEW-4 + §8.3 R2 sequence. For tables in `CDCMode='both'`
shadow-write mode (per D63 + D125 dispatch), compares the per-snapshot row
count recorded by `parquet_writer.write_parquet_snapshot()` against the
current Bronze active-row count for the same (source, table). Surfaces
drift before operators decide to flip to `parquet_snapshot` mode.

**v1 scope (default; fast nightly sanity)**: row-count parity check using
metadata already in `ParquetSnapshotRegistry.RowCount` + a Bronze
`SELECT COUNT(*) WHERE UdmActiveFlag=1` query per table. NO Parquet file
I/O; NO per-PK hash comparison. Operationally useful as a fast nightly
sanity check during the 30-day shadow-write validation period per RB-16
(B-547).

**v2 scope (B-555 closure 2026-05-19; opt-in via `--hash-check`)**: per-PK
hash comparison via polars Parquet read + Bronze `SELECT pk_columns, UdmHash`
query + polars anti-join + hash-equality filter. Closes the row-count-only
parity-check structural gap (rows match but contents differ silent failure)
+ the NULL-PK interpretation gap (Parquet > Bronze row-count drift
attributable to NULL-PK noise vs. actual row content drift). Opt-in via CLI
flag because: (a) requires polars dep at tool level; (b) full Parquet I/O
+ Bronze SELECT can be heavy for 3B+ row tables; (c) row-count check
remains the canonical fast nightly sanity. Operators run `--hash-check` for
deep investigation OR pre-cutover validation; not every nightly run.

**Memory note (B-555)**: per-PK hash comparison is in-memory (both Parquet
+ Bronze active rows held in polars DataFrames simultaneously). For 3B+
row tables this would OOM. Document as known limitation. Sampling-based
comparison for very large tables deferred to follow-up B-N.

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

    B-553 closure 2026-05-19: added defensive CRITICAL-class guard —
    if parquet_count < bronze_count, return MAJOR_DRIFT regardless of
    drift percentage. Bronze should never contain rows that Parquet
    doesn't capture (Parquet is source-exact per D115; Bronze is a
    subset after CDC NULL-PK filter per P0-4). Parquet < Bronze indicates
    data loss between extraction + Parquet write — CRITICAL operational
    signal. Per cross-cohort gap-check Agent `adc861405ff006766` 2026-05-19.

    NOTE: Parquet > Bronze drift may legitimately be due to NULL-PK rows
    in Parquet (D115 source-exactness captures source-exact rows; legacy
    CDC filters NULL-PK per P0-4). Operators should subtract known
    NULL-PK count when interpreting Parquet > Bronze drift; B-555 v2
    per-PK hash comparison will close this interpretation gap definitively.
    """

    if parquet_count == 0 and bronze_count == 0:
        return VERDICT_CLEAN
    if parquet_count == 0 or bronze_count == 0:
        return VERDICT_MAJOR_DRIFT

    # B-553 defensive guard: Parquet missed data → CRITICAL regardless of %
    if parquet_count < bronze_count:
        return VERDICT_MAJOR_DRIFT

    drift = abs(parquet_count - bronze_count) / parquet_count
    if drift <= DRIFT_TOLERANCE_PCT:
        return VERDICT_CLEAN
    if drift <= MAJOR_DRIFT_THRESHOLD_PCT:
        return VERDICT_DRIFT
    return VERDICT_MAJOR_DRIFT


def _resolve_bronze_table_name(cursor, source: str, table: str) -> str | None:
    """B-554 closure 2026-05-19 — resolve bronze full table name honoring
    SS-1 / StripSuffix=1 + per-table BronzeTableName custom override.

    Reads UdmTablesList for the per-table flags + composes the canonical
    Bronze fully-qualified name following the same logic as
    `orchestration.table_config.TableConfig.bronze_full_table_name`:

      - Effective name = BronzeTableName (custom override) OR SourceObjectName
      - Suffix = "" if StripSuffix=1 else "_scd2_python" (SS-1 semantic)
      - Result = `[{BRONZE_DB}].[{source}].[{effective}{suffix}]`

    Returns None if the UdmTablesList row is missing (caller handles as
    FATAL verdict).
    """

    cursor.execute(
        f"SELECT StripSuffix, BronzeTableName "
        f"FROM [{config.GENERAL_DB}].dbo.UdmTablesList "
        f"WHERE SourceName = ? AND SourceObjectName = ?",
        source, table,
    )
    row = cursor.fetchone()
    if row is None:
        return None
    strip_suffix = bool(row[0]) if row[0] is not None else False
    custom_name = row[1]
    effective = custom_name if custom_name else table
    suffix = "" if strip_suffix else "_scd2_python"
    return f"[{config.BRONZE_DB}].[{source}].[{effective}{suffix}]"


def _resolve_pk_columns(cursor, source: str, table: str) -> list[str]:
    """B-553 closure 2026-05-19 — resolve PK columns for the table.

    Reads UdmTablesColumnsList ordered by OrdinalPosition. Returns the
    list of column names that have IsPrimaryKey=1. Returns empty list
    if no PK columns are recorded (caller falls back to no NULL-PK
    filter; verdict may be less precise but not incorrect).
    """

    cursor.execute(
        f"SELECT ColumnName "
        f"FROM [{config.GENERAL_DB}].dbo.UdmTablesColumnsList "
        f"WHERE SourceName = ? AND TableName = ? AND IsPrimaryKey = 1 "
        f"ORDER BY OrdinalPosition",
        source, table,
    )
    pk_columns = [row[0] for row in cursor.fetchall()]
    if not pk_columns:
        # B-560 closure 2026-05-19: WARNING surfaces the UdmTablesColumnsList
        # gap (PK columns absent for this table). Operationally minor since
        # Bronze excludes NULL-PK via legacy CDC P0-4 filter, but operator
        # config issue worth surfacing. Hash-check verdict will FATAL on
        # empty pk_columns per check_table_parity defensive guard.
        logger.warning(
            "_resolve_pk_columns: no PK columns for %s.%s in UdmTablesColumnsList "
            "(IsPrimaryKey=1 query returned 0 rows). Bronze NULL-PK defensive "
            "filter will be a no-op; hash-check would FATAL. Investigate "
            "UdmTablesColumnsList population for this table.",
            source, table,
        )
    return pk_columns


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


def _query_bronze_active_row_count(cursor, bronze_table: str,
                                  pk_columns: list[str] | None = None) -> int:
    """Return Bronze active-row count for the resolved bronze table.

    B-553 closure 2026-05-19: extends WHERE clause with `AND {pk} IS NOT NULL`
    per PK column when `pk_columns` is non-empty. Defensive per B-550 NULL-PK
    exclusion semantics — Bronze NEVER stores NULL-PK rows in practice (legacy
    CDC's `_filter_null_pks()` (P0-4) removes them before write), so the
    additional filter is functionally a no-op. The explicit filter makes the
    semantic legible + future-proofs against any Bronze schema change that
    might allow NULL-PK rows.

    B-554 closure 2026-05-19: `bronze_table` is now caller-provided (resolved
    via `_resolve_bronze_table_name()` honoring SS-1 + BronzeTableName custom
    override) rather than hardcoded `[BRONZE_DB].[source].[table_scd2_python]`.
    """

    sql = f"SELECT COUNT(*) FROM {bronze_table} WHERE UdmActiveFlag = 1"
    if pk_columns:
        null_pk_clause = " AND ".join(f"[{col}] IS NOT NULL" for col in pk_columns)
        sql += f" AND {null_pk_clause}"
    cursor.execute(sql)
    row = cursor.fetchone()
    return int(row[0]) if row is not None else 0


# ---------------------------------------------------------------------------
# B-555 v2 per-PK hash comparison (opt-in via --hash-check)
# ---------------------------------------------------------------------------

# Hash-check verdict reuses VERDICT_* constants above.
# Threshold semantics:
# - in_bronze_missing_from_parquet > 0 -> MAJOR_DRIFT (orphan; CRITICAL)
# - (in_parquet_missing_from_bronze + pk_match_hash_diff) / parquet_count > 5% -> MAJOR_DRIFT
# - same metric > 1% -> DRIFT
# - else CLEAN


def _query_latest_parquet_network_drive_path(cursor, source: str, table: str) -> str | None:
    """Query latest ParquetSnapshotRegistry.NetworkDrivePath for (source, table).

    Returns path to the latest replay-eligible snapshot (Status IN verified
    / replicated / archived), or None if no eligible row exists.
    """
    sql = """
        SELECT TOP 1 NetworkDrivePath
        FROM General.ops.ParquetSnapshotRegistry
        WHERE SourceName = ? AND TableName = ?
          AND Status IN ('verified', 'replicated', 'archived')
        ORDER BY CreatedAt DESC, BatchId DESC
    """
    cursor.execute(sql, (source, table))
    row = cursor.fetchone()
    return str(row[0]) if row is not None else None


def _read_parquet_pk_hashes(network_drive_path: str, pk_columns: list[str]):
    """Read parquet file via polars + return DataFrame with pk_columns + _row_hash.

    Requires polars dep. Lazy-imports so the tool can fall back gracefully
    on platforms without polars (the hash-check path is opt-in via
    --hash-check CLI flag).

    Raises ImportError if polars is not installed.
    """
    import polars as pl  # noqa: PLC0415
    df = pl.read_parquet(network_drive_path)
    cols_to_select = [*pk_columns, "_row_hash"]
    return df.select(cols_to_select)


def _query_bronze_pk_hashes(cursor, bronze_table: str, pk_columns: list[str]):
    """Query Bronze active rows + return polars DataFrame with pk_columns + UdmHash.

    Lazy-imports polars; raises ImportError if not installed.
    """
    import polars as pl  # noqa: PLC0415

    pk_cols_sql = ", ".join(f"[{c}]" for c in pk_columns)
    not_null_filter = " AND ".join(f"[{c}] IS NOT NULL" for c in pk_columns)
    where_clause = "WHERE UdmActiveFlag = 1"
    if not_null_filter:
        where_clause += f" AND {not_null_filter}"
    sql = f"SELECT {pk_cols_sql}, [UdmHash] FROM {bronze_table} {where_clause}"

    cursor.execute(sql)
    rows = cursor.fetchall()
    cols = [c[0] for c in cursor.description]
    # Convert rows (list of tuples) to list of dicts for polars DataFrame
    data = [dict(zip(cols, r)) for r in rows]
    return pl.DataFrame(data) if data else pl.DataFrame(schema={c: pl.Utf8 for c in cols})


def compare_pk_hashes(parquet_df, bronze_df, pk_columns: list[str]) -> dict:
    """Compare per-PK hashes between Parquet + Bronze via polars joins.

    :param parquet_df: polars DataFrame with pk_columns + ``_row_hash`` column
        (from :func:`_read_parquet_pk_hashes`).
    :param bronze_df: polars DataFrame with pk_columns + ``UdmHash`` column
        (from :func:`_query_bronze_pk_hashes`).
    :param pk_columns: list of PK column names for the join keys.
    :returns: dict with keys:

        - ``in_parquet_missing_from_bronze``: rows in Parquet but not Bronze
          (inserts not yet promoted; expected during shadow mode)
        - ``in_bronze_missing_from_parquet``: rows in Bronze but not Parquet
          (ORPHAN -- Bronze has rows Parquet missed; CRITICAL per D115
          source-exactness invariant)
        - ``pk_match_hash_diff``: same PK in both but different hash
          (content drift -- the silent failure class B-555 closes)
        - ``pk_match_hash_same``: same PK + matching hash (clean rows)

    Lazy-imports polars; raises ImportError if not installed.
    """
    import polars as pl  # noqa: PLC0415

    # Anti-join: PKs in Parquet but not Bronze
    parquet_only = parquet_df.join(
        bronze_df.select(pk_columns), on=pk_columns, how="anti"
    )
    # Anti-join reverse: PKs in Bronze but not Parquet (orphan; CRITICAL)
    bronze_only = bronze_df.join(
        parquet_df.select(pk_columns), on=pk_columns, how="anti"
    )
    # Inner join: matching PKs -- compare hashes
    joined = parquet_df.join(bronze_df, on=pk_columns, how="inner", suffix="_bronze")
    hash_diff_df = joined.filter(pl.col("_row_hash") != pl.col("UdmHash"))
    hash_same_df = joined.filter(pl.col("_row_hash") == pl.col("UdmHash"))

    return {
        "in_parquet_missing_from_bronze": len(parquet_only),
        "in_bronze_missing_from_parquet": len(bronze_only),
        "pk_match_hash_diff": len(hash_diff_df),
        "pk_match_hash_same": len(hash_same_df),
    }


def classify_hash_check(comparison: dict, parquet_count: int) -> str:
    """Verdict from hash-comparison results.

    Independent of row-count verdict (both verdicts computed when --hash-check
    enabled; final verdict = most-severe).

    Returns VERDICT_CLEAN / VERDICT_DRIFT / VERDICT_MAJOR_DRIFT.

    Rules:

    - in_bronze_missing_from_parquet > 0 -> MAJOR_DRIFT (CRITICAL orphan;
      Parquet is source-exact per D115 so Bronze should never have rows
      Parquet missed)
    - parquet_count == 0:
        * if all comparison counts == 0 -> CLEAN (both empty)
        * else -> MAJOR_DRIFT (inconsistent state)
    - drift_pct = (in_parquet_missing_from_bronze + pk_match_hash_diff) / parquet_count:
        * > MAJOR_DRIFT_THRESHOLD_PCT (5%) -> MAJOR_DRIFT
        * > DRIFT_TOLERANCE_PCT (1%) -> DRIFT
        * else -> CLEAN
    """
    if comparison["in_bronze_missing_from_parquet"] > 0:
        return VERDICT_MAJOR_DRIFT
    if parquet_count == 0:
        all_zero = all(comparison[k] == 0 for k in (
            "in_parquet_missing_from_bronze",
            "pk_match_hash_diff",
            "pk_match_hash_same",
        ))
        return VERDICT_CLEAN if all_zero else VERDICT_MAJOR_DRIFT
    drift_pct = (
        comparison["in_parquet_missing_from_bronze"]
        + comparison["pk_match_hash_diff"]
    ) / parquet_count
    if drift_pct > MAJOR_DRIFT_THRESHOLD_PCT:
        return VERDICT_MAJOR_DRIFT
    if drift_pct > DRIFT_TOLERANCE_PCT:
        return VERDICT_DRIFT
    return VERDICT_CLEAN


def _combine_verdicts(row_count_verdict: str, hash_check_verdict: str) -> str:
    """Most-severe-wins precedence: FATAL > MAJOR_DRIFT > DRIFT > CLEAN.

    When --hash-check enabled, the per-table verdict is the most-severe of:
    - row-count check (always computed)
    - hash-check (computed when opt-in)
    """
    severity_order = {
        VERDICT_FATAL: 4,
        VERDICT_MAJOR_DRIFT: 3,
        VERDICT_DRIFT: 2,
        VERDICT_CLEAN: 1,
    }
    rc_sev = severity_order.get(row_count_verdict, 0)
    hc_sev = severity_order.get(hash_check_verdict, 0)
    return row_count_verdict if rc_sev >= hc_sev else hash_check_verdict


def check_table_parity(cursor, source: str, table: str, *, hash_check: bool = False) -> dict:
    """Run parity check for a single (source, table). Returns dict with
    verdict + per-table metrics.

    Resolution sequence (per B-553 + B-554 closure 2026-05-19):

      1. Resolve bronze full-table-name via `_resolve_bronze_table_name()` —
         honors SS-1 / StripSuffix=1 + per-table BronzeTableName custom
         override (B-554).
      2. Resolve PK columns via `_resolve_pk_columns()` — for the Bronze
         NULL-PK defensive filter (B-553).
      3. Query latest ParquetSnapshotRegistry row count.
      4. Query Bronze active-row count with NULL-PK exclusion filter.
      5. Classify parity via `classify_parity()` — includes the B-553
         Parquet-missed-data guard (parquet < bronze → MAJOR_DRIFT).

    Catches per-table SQL exceptions + emits VERDICT_FATAL with error
    captured rather than propagating (so a single table failure doesn't
    block parity checks for other tables in a multi-table run).
    """

    try:
        # B-554: resolve bronze table name BEFORE parquet probe — if
        # UdmTablesList row missing, fail fast with explicit error
        bronze_table = _resolve_bronze_table_name(cursor, source, table)
        if bronze_table is None:
            return {
                "source": source, "table": table,
                "verdict": VERDICT_FATAL,
                "error": f"UdmTablesList row missing for {source}.{table} — "
                         f"cannot resolve bronze_full_table_name per B-554",
                "parquet_count": None, "bronze_count": None, "drift_pct": None,
            }

        # B-553: resolve PK columns for NULL-PK defensive filter
        pk_columns = _resolve_pk_columns(cursor, source, table)

        parquet_count = _query_latest_parquet_row_count(cursor, source, table)
        if parquet_count is None:
            return {
                "source": source, "table": table,
                "verdict": VERDICT_FATAL,
                "error": "No ParquetSnapshotRegistry row found — table may not "
                         "have been processed in 'both' mode yet",
                "parquet_count": None, "bronze_count": None, "drift_pct": None,
                "bronze_table": bronze_table, "pk_columns": pk_columns,
            }
        bronze_count = _query_bronze_active_row_count(cursor, bronze_table, pk_columns)
        verdict = classify_parity(parquet_count, bronze_count)
        drift_pct = (
            abs(parquet_count - bronze_count) / parquet_count
            if parquet_count > 0 else None
        )
        result = {
            "source": source, "table": table,
            "verdict": verdict,
            "parquet_count": parquet_count,
            "bronze_count": bronze_count,
            "drift_pct": drift_pct,
            "bronze_table": bronze_table,
            "pk_columns": pk_columns,
        }

        # B-555 v2: optional per-PK hash comparison (opt-in via hash_check=True)
        if hash_check and pk_columns:
            try:
                network_drive_path = _query_latest_parquet_network_drive_path(
                    cursor, source, table,
                )
                if network_drive_path is None:
                    result["hash_check_verdict"] = VERDICT_FATAL
                    result["hash_check_error"] = (
                        "No replay-eligible ParquetSnapshotRegistry row for "
                        f"{source}.{table} -- cannot read parquet for hash check"
                    )
                    result["verdict"] = _combine_verdicts(
                        result["verdict"], VERDICT_FATAL,
                    )
                else:
                    parquet_df = _read_parquet_pk_hashes(network_drive_path, pk_columns)
                    bronze_df = _query_bronze_pk_hashes(cursor, bronze_table, pk_columns)
                    comparison = compare_pk_hashes(parquet_df, bronze_df, pk_columns)
                    hash_verdict = classify_hash_check(comparison, parquet_count)
                    result["hash_check_verdict"] = hash_verdict
                    result["hash_comparison"] = comparison
                    result["verdict"] = _combine_verdicts(
                        result["verdict"], hash_verdict,
                    )
            except ImportError as exc:
                # polars not installed; warn but don't fail row-count verdict
                result["hash_check_verdict"] = VERDICT_FATAL
                result["hash_check_error"] = (
                    f"polars not installed; --hash-check skipped: {str(exc)[:200]}"
                )
                # Do NOT override row-count verdict (polars-missing is operator
                # config issue, not parity drift)
            except Exception as exc:  # noqa: BLE001
                result["hash_check_verdict"] = VERDICT_FATAL
                result["hash_check_error"] = str(exc)[:500]
                result["verdict"] = _combine_verdicts(
                    result["verdict"], VERDICT_FATAL,
                )
        elif hash_check and not pk_columns:
            result["hash_check_verdict"] = VERDICT_FATAL
            result["hash_check_error"] = (
                "Cannot perform hash check without pk_columns -- "
                "UdmTablesColumnsList may be unpopulated for this table"
            )
            # Do NOT override row-count verdict (pk_columns absence is
            # operator config issue, not parity drift)

        return result
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
    hash_check_enabled = any(
        ("hash_check_verdict" in v) for v in per_table_verdicts
    )
    metadata = {
        "tables_checked": tables_checked,
        "clean": clean,
        "drift": drift,
        "major_drift": major_drift,
        "hash_check_enabled": hash_check_enabled,
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
          dry_run: bool = True, hash_check: bool = False) -> dict:
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

    # Run per-table parity checks (hash_check=True opts in to B-555 v2 per-PK hash)
    per_table_verdicts = [
        check_table_parity(cursor, src, tbl, hash_check=hash_check) for src, tbl in tables
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
        # B-N remediation per cross-cohort review Agent adc861405ff006766
        # 2026-05-19 Scope 1: replaced bare `raise` with FATAL-return so
        # main() honors D74 contract via result dict. Parity verdicts
        # already computed survive; audit-row write-failure overrides exit
        # to FATAL so operator is signaled to investigate via logs.
        result = {
            "event_kind": "error",
            "exit_code": EXIT_FATAL,
            "error": f"Audit row write failed: {str(exc)[:500]}",
            "tables_checked": len(tables),
            "clean": clean, "drift": drift, "major_drift": major_drift,
            "per_table_verdicts": per_table_verdicts,
            "dry_run": False,
        }
        return result

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
    parser.add_argument(
        "--hash-check", action="store_true",
        help=(
            "B-555 v2: enable per-PK hash comparison (polars Parquet read + Bronze "
            "UdmHash join). Closes silent-content-drift gap that row-count check "
            "misses. Heavier I/O; not for every nightly run. Requires polars dep."
        ),
    )
    args = parser.parse_args()

    dry_run = not args.apply
    conn = get_connection(config.GENERAL_DB)
    conn.autocommit = False
    try:
        result = apply(
            conn,
            actor=args.actor, justification=args.justification,
            source=args.source, table=args.table,
            dry_run=dry_run, hash_check=args.hash_check,
        )
        logger.info("validate_parquet_vs_stage result: %s",
                    json.dumps(result, indent=2, default=str))
        return int(result["exit_code"])
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
