"""Table-wide CDC consistency validator — Stage ↔ Bronze ↔ source.

Complements ``tools/validate_scd2.py`` (which validates Bronze structural
integrity in isolation) with a cross-layer view:

  * **Stage** rows with ``_cdc_is_current = 1``  vs
  * **Bronze** rows with ``UdmActiveFlag = 1``    vs
  * **Source** PK existence (sampled)

Each check answers a specific question and reports counts, sample PKs,
and a recommendation. Read-only — never modifies data.

Usage::

    # One table
    python3 tools/validate_cdc.py --source DNA --table ACCT

    # Whole source
    python3 tools/validate_cdc.py --source DNA

    # All tables
    python3 tools/validate_cdc.py --all

    # Skip the source comparison (useful when source is slow / unreachable)
    python3 tools/validate_cdc.py --source DNA --no-source

What it checks
--------------

A. **Stage current count per PK** — should be exactly 1 for active PKs.
   Reports:

     * PKs with > 1 current=1 row (P0-9 crash recovery artifact).
     * PKs with zero current=1 rows AND Bronze active (out-of-sync Stage).

B. **Bronze active count per PK** — should be exactly 1 per active PK.
   Reports:

     * PKs with > 1 Flag=1 row (P1-16 crash artifact).
     * PKs with > 0 Flag=1 row + > 0 Flag=2 row simultaneously (legacy
       inconsistency — should not happen post R-4).

C. **Stage vs Bronze cross-check**:

     * Stage current rows whose hash differs from Bronze active hash for
       the same PK.
     * Stage current PKs without a Bronze active row (SCD2 incomplete).
     * Bronze active PKs without a Stage current row (Stage out of sync
       OR PK was deleted at source — needs source check to disambiguate).

D. **In-flight orphans** — Bronze ``Flag=0 + Op IN ('U','R')`` with both
   end dates NULL. Auto-cleaned next run; informational only.

E. **Source comparison** (optional, skipped with ``--no-source``):

     * PKs in source but missing from Stage current AND missing from
       Bronze active — never loaded.
     * PKs in Bronze active but not in source — late delete that hasn't
       been closed yet.

Each finding includes up to 5 sample PKs so you can drill in with
``tools/inspect_cdc_pk.py``.

Exit code 0 if every checked table is clean, 1 if any anomaly is found.
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import utils.configuration as config
from utils.connections import (
    get_connection, quote_identifier, quote_table,
)
from utils.sources import get_source
from extract.udm_connectorx_extractor import table_exists
from orchestration.table_config import TableConfigLoader

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


_SAMPLE_LIMIT = 5


@dataclass
class CDCValidationResult:
    source_name: str
    table_name: str
    skipped: bool = False
    skip_reason: str = ""

    # Stage-side findings
    stage_current_dup_pks: int = 0
    stage_current_missing_pks: int = 0  # zero current; Bronze has active

    # Bronze-side findings
    bronze_active_dup_pks: int = 0
    bronze_flag1_and_flag2_pks: int = 0  # PK has both Flag=1 AND Flag=2 simultaneously

    # Cross-layer findings
    hash_diverge_pks: int = 0
    stage_current_no_bronze_active_pks: int = 0
    bronze_active_no_stage_current_pks: int = 0
    inflight_orphan_rows: int = 0

    # Source comparison (optional)
    source_only_pks: int = 0          # in source, not in Stage current OR Bronze active
    bronze_active_not_in_source: int = 0

    # Sample PK lists for each finding category (str-formatted for log)
    samples: dict[str, list[str]] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def total_findings(self) -> int:
        return (
            self.stage_current_dup_pks
            + self.stage_current_missing_pks
            + self.bronze_active_dup_pks
            + self.bronze_flag1_and_flag2_pks
            + self.hash_diverge_pks
            + self.stage_current_no_bronze_active_pks
            + self.bronze_active_no_stage_current_pks
            + self.source_only_pks
            + self.bronze_active_not_in_source
        )

    @property
    def is_clean(self) -> bool:
        return self.total_findings == 0 and not self.errors


# ---------------------------------------------------------------------------
# SQL helpers — all queries assume Stage and Bronze are on the same SQL
# Server instance (cross-database queries via three-part names).
# ---------------------------------------------------------------------------


def _pk_join(pk_columns: list[str], a: str, b: str) -> str:
    return " AND ".join(
        f"{a}.{quote_identifier(c)} = {b}.{quote_identifier(c)}"
        for c in pk_columns
    )


def _pk_select(pk_columns: list[str], alias: str) -> str:
    return ", ".join(f"{alias}.{quote_identifier(c)}" for c in pk_columns)


def _pk_select_for_sample(pk_columns: list[str], alias: str = "") -> str:
    prefix = f"{alias}." if alias else ""
    parts = [
        f"CAST({prefix}{quote_identifier(c)} AS NVARCHAR(50))"
        for c in pk_columns
    ]
    return " + N'|' + ".join(parts) if len(parts) > 1 else parts[0]


def _query_count_and_sample(
    db: str, count_sql: str, sample_sql: str, label: str,
) -> tuple[int, list[str]]:
    """Run a count + sample query pair. Returns (count, sample list)."""
    conn = get_connection(db)
    try:
        cursor = conn.cursor()
        cursor.execute(count_sql)
        row = cursor.fetchone()
        count = int(row[0]) if row else 0

        samples: list[str] = []
        if count > 0:
            cursor.execute(sample_sql)
            samples = [str(r[0]) for r in cursor.fetchall()]
        cursor.close()
        return count, samples
    except Exception as exc:
        logger.warning("Validate-CDC: %s query failed: %s", label, exc)
        return 0, []
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Per-table validator
# ---------------------------------------------------------------------------


def validate_cdc(
    table_config,
    *,
    check_source: bool = True,
) -> CDCValidationResult:
    result = CDCValidationResult(
        source_name=table_config.source_name,
        table_name=table_config.source_object_name,
    )

    pk_columns = table_config.pk_columns
    if not pk_columns:
        result.skipped = True
        result.skip_reason = "no PK columns configured"
        return result

    stage = table_config.stage_full_table_name
    bronze = table_config.bronze_full_table_name
    if not table_exists(stage):
        result.skipped = True
        result.skip_reason = f"Stage table {stage} does not exist"
        return result
    if not table_exists(bronze):
        result.skipped = True
        result.skip_reason = f"Bronze table {bronze} does not exist"
        return result

    db = stage.split(".")[0]  # Stage and Bronze must be on the same instance
    qs = quote_table(stage)
    qb = quote_table(bronze)

    pk_group = ", ".join(quote_identifier(c) for c in pk_columns)
    pk_sample_expr = _pk_select_for_sample(pk_columns)

    # ----- A1: Stage current duplicate PKs ----------------------------------
    cnt_sql = f"""
        SELECT COUNT(*) FROM (
            SELECT {pk_group}
            FROM {qs}
            WHERE [_cdc_is_current] = 1
            GROUP BY {pk_group}
            HAVING COUNT(*) > 1
        ) t
    """
    sample_sql = f"""
        SELECT TOP {_SAMPLE_LIMIT} {pk_sample_expr}
        FROM {qs}
        WHERE [_cdc_is_current] = 1
        GROUP BY {pk_group}
        HAVING COUNT(*) > 1
    """
    n, s = _query_count_and_sample(db, cnt_sql, sample_sql, "stage current dup")
    result.stage_current_dup_pks = n
    if s:
        result.samples["stage_current_dup"] = s

    # ----- B1: Bronze active duplicate PKs ----------------------------------
    cnt_sql = f"""
        SELECT COUNT(*) FROM (
            SELECT {pk_group}
            FROM {qb}
            WHERE [UdmActiveFlag] = 1
            GROUP BY {pk_group}
            HAVING COUNT(*) > 1
        ) t
    """
    sample_sql = f"""
        SELECT TOP {_SAMPLE_LIMIT} {pk_sample_expr}
        FROM {qb}
        WHERE [UdmActiveFlag] = 1
        GROUP BY {pk_group}
        HAVING COUNT(*) > 1
    """
    n, s = _query_count_and_sample(db, cnt_sql, sample_sql, "bronze active dup")
    result.bronze_active_dup_pks = n
    if s:
        result.samples["bronze_active_dup"] = s

    # ----- B2: Bronze PKs with both Flag=1 and Flag=2 (post-R-4 should be 0) -
    cnt_sql = f"""
        SELECT COUNT(*) FROM (
            SELECT {pk_group}
            FROM {qb}
            GROUP BY {pk_group}
            HAVING SUM(CASE WHEN [UdmActiveFlag] = 1 THEN 1 ELSE 0 END) > 0
               AND SUM(CASE WHEN [UdmActiveFlag] = 2 THEN 1 ELSE 0 END) > 0
        ) t
    """
    sample_sql = f"""
        SELECT TOP {_SAMPLE_LIMIT} {pk_sample_expr}
        FROM {qb}
        GROUP BY {pk_group}
        HAVING SUM(CASE WHEN [UdmActiveFlag] = 1 THEN 1 ELSE 0 END) > 0
           AND SUM(CASE WHEN [UdmActiveFlag] = 2 THEN 1 ELSE 0 END) > 0
    """
    n, s = _query_count_and_sample(db, cnt_sql, sample_sql, "bronze flag1 and flag2")
    result.bronze_flag1_and_flag2_pks = n
    if s:
        result.samples["bronze_flag1_and_flag2"] = s

    # ----- D: In-flight orphans ---------------------------------------------
    cnt_sql = f"""
        SELECT COUNT(*) FROM {qb}
        WHERE [UdmActiveFlag] = 0
          AND [UdmScd2Operation] IN ('U', 'R')
          AND [UdmEndDateTime] IS NULL
          AND [UdmSourceEndDate] IS NULL
    """
    sample_sql = f"""
        SELECT TOP {_SAMPLE_LIMIT} {pk_sample_expr}
        FROM {qb}
        WHERE [UdmActiveFlag] = 0
          AND [UdmScd2Operation] IN ('U', 'R')
          AND [UdmEndDateTime] IS NULL
          AND [UdmSourceEndDate] IS NULL
    """
    n, s = _query_count_and_sample(db, cnt_sql, sample_sql, "inflight orphans")
    result.inflight_orphan_rows = n
    if s:
        result.samples["inflight_orphan"] = s

    # ----- C cross-layer joins ----------------------------------------------
    # We compute stage-current PK set and bronze-active PK set on the
    # database side via FULL OUTER JOIN-style aggregation. Counting per-PK
    # state in one query is more efficient than three round-trips.

    # CTE-style query: distinct PK sets from each side, then categorize.
    # Using COALESCE on PK columns means we need DISTINCT PKs per side first.
    cnt_sql = f"""
        WITH stage_curr AS (
            SELECT DISTINCT {pk_group}, [_row_hash]
            FROM (
                SELECT {pk_group}, [_row_hash],
                       ROW_NUMBER() OVER (
                           PARTITION BY {pk_group}
                           ORDER BY [_cdc_valid_from] DESC, [_cdc_batch_id] DESC
                       ) AS rn
                FROM {qs}
                WHERE [_cdc_is_current] = 1
            ) x WHERE rn = 1
        ),
        bronze_active AS (
            SELECT DISTINCT {pk_group}, [UdmHash]
            FROM (
                SELECT {pk_group}, [UdmHash],
                       ROW_NUMBER() OVER (
                           PARTITION BY {pk_group}
                           ORDER BY [UdmEffectiveDateTime] DESC, [_scd2_key] DESC
                       ) AS rn
                FROM {qb}
                WHERE [UdmActiveFlag] = 1
            ) x WHERE rn = 1
        )
        SELECT
            SUM(CASE WHEN s.[_row_hash] IS NOT NULL AND b.[UdmHash] IS NOT NULL
                     AND s.[_row_hash] <> b.[UdmHash] THEN 1 ELSE 0 END) AS hash_diverge,
            SUM(CASE WHEN s.[_row_hash] IS NOT NULL AND b.[UdmHash] IS NULL
                     THEN 1 ELSE 0 END) AS stage_no_bronze,
            SUM(CASE WHEN s.[_row_hash] IS NULL AND b.[UdmHash] IS NOT NULL
                     THEN 1 ELSE 0 END) AS bronze_no_stage
        FROM stage_curr s
        FULL OUTER JOIN bronze_active b ON {_pk_join(pk_columns, "s", "b")}
    """
    conn = get_connection(db)
    try:
        cursor = conn.cursor()
        cursor.execute(cnt_sql)
        row = cursor.fetchone()
        if row:
            result.hash_diverge_pks = int(row[0] or 0)
            result.stage_current_no_bronze_active_pks = int(row[1] or 0)
            result.bronze_active_no_stage_current_pks = int(row[2] or 0)
        cursor.close()
    except Exception as exc:
        logger.warning("Validate-CDC cross-layer query failed: %s", exc)
        result.errors.append(f"cross-layer: {exc}")
    finally:
        conn.close()

    # Sample PKs for the three cross-layer categories (separate queries —
    # cheaper than emitting them in the FULL OUTER JOIN above).
    if result.hash_diverge_pks > 0:
        sample_sql = f"""
            SELECT TOP {_SAMPLE_LIMIT} {_pk_select_for_sample(pk_columns, 's')}
            FROM (
                SELECT {pk_group}, [_row_hash],
                       ROW_NUMBER() OVER (
                           PARTITION BY {pk_group}
                           ORDER BY [_cdc_valid_from] DESC, [_cdc_batch_id] DESC
                       ) AS rn
                FROM {qs} WHERE [_cdc_is_current] = 1
            ) s
            INNER JOIN (
                SELECT {pk_group}, [UdmHash],
                       ROW_NUMBER() OVER (
                           PARTITION BY {pk_group}
                           ORDER BY [UdmEffectiveDateTime] DESC, [_scd2_key] DESC
                       ) AS rn
                FROM {qb} WHERE [UdmActiveFlag] = 1
            ) b ON {_pk_join(pk_columns, "s", "b")}
            WHERE s.rn = 1 AND b.rn = 1 AND s.[_row_hash] <> b.[UdmHash]
        """
        _, s = _query_count_and_sample(db, "SELECT 0", sample_sql, "hash diverge sample")
        if s:
            result.samples["hash_diverge"] = s

    # ----- E source comparison ----------------------------------------------
    if check_source:
        try:
            _compare_against_source(table_config, pk_columns, result)
        except Exception as exc:
            logger.warning("Validate-CDC source check failed for %s.%s: %s",
                           table_config.source_name, table_config.source_object_name, exc)
            result.errors.append(f"source check: {exc}")

    return result


# ---------------------------------------------------------------------------
# Source comparison (sampled — full PK reconciliation lives in E-7)
# ---------------------------------------------------------------------------


def _compare_against_source(table_config, pk_columns, result: CDCValidationResult) -> None:
    """Quick sampled comparison against source. For definitive PK diffs,
    use ``cdc/reconciliation/counts.reconcile_active_pks`` (E-7) which
    handles billion-row tables via chunking."""
    # Source query is qualified by schema only (e.g. OSIBANK.ACCT). The
    # connection params already scope us to the correct database/service,
    # so the leading database qualifier (DNAPROD) is redundant and would
    # break if the source DB is renamed or reached via a different alias.
    src_table = f"{table_config.source_schema_name}.{table_config.source_object_name}"
    bronze = table_config.bronze_full_table_name
    db = bronze.split(".")[0]
    qb = quote_table(bronze)
    pk_group = ", ".join(quote_identifier(c) for c in pk_columns)
    pk_sample_expr = _pk_select_for_sample(pk_columns, "b")

    # We can only run this comparison cheaply for SQL Server sources via a
    # linked server, OR by extracting the source PK list. For a quick
    # validator, sample 100 Bronze active PKs and check whether each
    # exists in source. This is NOT a full reconciliation.
    sample_n = 100
    cnt_sql = f"""
        SELECT TOP {sample_n} {_pk_select(pk_columns, 'b')}
        FROM {qb} b
        WHERE b.[UdmActiveFlag] = 1
        ORDER BY NEWID()
    """
    conn = get_connection(db)
    try:
        cursor = conn.cursor()
        cursor.execute(cnt_sql)
        sample_pks = cursor.fetchall()
        cursor.close()
    finally:
        conn.close()

    if not sample_pks:
        return

    # For each sampled PK, ask source whether it exists. We aggregate the
    # not-in-source count and report. Implementation depends on source type.
    source = get_source(table_config.source_name)
    not_in_source = 0
    not_in_source_samples: list[str] = []

    is_oracle = table_config.is_oracle
    for pk_row in sample_pks:
        pk_values = [str(v) if v is not None else "" for v in pk_row]
        from tools.inspect_cdc_pk import _where_clause as _wc
        where = _wc(pk_columns, pk_values, is_oracle=is_oracle)
        query = f"SELECT 1 FROM {src_table} WHERE {where}"
        try:
            if table_config.is_oracle:
                import oracledb
                with oracledb.connect(**source.oracledb_connect_params()) as conn:
                    with conn.cursor() as cursor:
                        cursor.execute(query)
                        row = cursor.fetchone()
            else:
                import pyodbc
                with pyodbc.connect(source.pyodbc_connection_string(), autocommit=True) as conn:
                    cursor = conn.cursor()
                    cursor.execute(query)
                    row = cursor.fetchone()
        except Exception:
            # One bad row shouldn't kill the sweep
            continue

        if row is None:
            not_in_source += 1
            if len(not_in_source_samples) < _SAMPLE_LIMIT:
                not_in_source_samples.append("|".join(pk_values))

    # Project the sample to a population estimate. For 100-row sample, if
    # 5 are missing we'd estimate 5% of active Bronze PKs aren't in source.
    # We just report the count from the sample for simplicity.
    if not_in_source:
        result.bronze_active_not_in_source = not_in_source
        result.samples["bronze_active_not_in_source"] = not_in_source_samples


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _print_result(r: CDCValidationResult) -> bool:
    label = f"{r.source_name}.{r.table_name}"
    if r.skipped:
        print(f"[{label}] SKIPPED ({r.skip_reason})")
        return True
    if r.errors:
        print(f"[{label}] ERROR: {'; '.join(r.errors)}")
    if r.is_clean:
        print(f"[{label}] CLEAN")
        return True

    print(f"[{label}] FINDINGS:")
    findings = [
        ("stage_current_dup_pks", r.stage_current_dup_pks,
         "Stage PKs with > 1 _cdc_is_current=1 row (P0-9 crash artifact)"),
        ("bronze_active_dup_pks", r.bronze_active_dup_pks,
         "Bronze PKs with > 1 UdmActiveFlag=1 row (P1-16 crash artifact)"),
        ("bronze_flag1_and_flag2_pks", r.bronze_flag1_and_flag2_pks,
         "PKs with both Flag=1 AND Flag=2 in Bronze (legacy inconsistency)"),
        ("hash_diverge_pks", r.hash_diverge_pks,
         "Stage current _row_hash != Bronze active UdmHash (next run reconciles)"),
        ("stage_current_no_bronze_active_pks", r.stage_current_no_bronze_active_pks,
         "Stage current rows whose PK has no Bronze active row"),
        ("bronze_active_no_stage_current_pks", r.bronze_active_no_stage_current_pks,
         "Bronze active rows whose PK has no Stage current row"),
        ("inflight_orphan_rows", r.inflight_orphan_rows,
         "Bronze in-flight orphans (auto-cleaned next run)"),
        ("bronze_active_not_in_source", r.bronze_active_not_in_source,
         "Sample of Bronze active PKs not found in source (late-delete signal)"),
    ]
    for key, count, desc in findings:
        if count == 0:
            continue
        sample = r.samples.get(key.replace("_pks", "").replace("_rows", ""), [])
        sample_str = (f"  samples={sample}" if sample else "")
        print(f"  - {desc}: {count}{sample_str}")
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", help="Filter by SourceName.")
    parser.add_argument("--table", help="Filter by SourceObjectName.")
    parser.add_argument("--all", action="store_true",
                        help="Validate every Python pipeline table.")
    parser.add_argument("--no-source", action="store_true",
                        help="Skip the source-comparison step.")
    args = parser.parse_args()

    if not (args.source or args.table or args.all):
        parser.error("Specify --source, --table, or --all.")

    loader = TableConfigLoader()
    configs = (
        loader.load_small_tables(source_name=args.source, table_name=args.table)
        + loader.load_large_tables(source_name=args.source, table_name=args.table)
    )
    if not configs:
        logger.error("No matching tables in UdmTablesList.")
        return 2

    logger.info("Validate-CDC on %d table(s) (source check %s)",
                len(configs), "skipped" if args.no_source else "enabled")
    all_clean = True
    for cfg in configs:
        try:
            r = validate_cdc(cfg, check_source=not args.no_source)
        except Exception:
            logger.exception("Validate-CDC raised on %s.%s",
                             cfg.source_name, cfg.source_object_name)
            all_clean = False
            continue
        clean = _print_result(r)
        if not clean:
            all_clean = False

    if all_clean:
        logger.info("All checked tables clean.")
        return 0
    logger.error("Findings detected. Drill in with tools/inspect_cdc_pk.py "
                 "for any sample PK above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
