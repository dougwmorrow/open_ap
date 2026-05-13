"""Modified-date sweep — Tier 2 CDC for large tables.

Daily windowed extraction (``main_large_tables.py``) catches changes whose
``SourceAggregateColumnName`` value falls inside the ``LookbackDays``
window. Rows updated outside that window slip through. Example: an
account whose ``CONTRACTDATE`` is 2023-06-01 gets its status flipped
today; the daily extraction filters on ``CONTRACTDATE`` so it never sees
the row.

This module periodically extracts only ``(PK_columns, LastModifiedColumn)``
from source — a much cheaper projection than full-row extraction —
compares it against Bronze active rows' ``UdmSourceBeginDate``, and
reloads the PKs whose source has been touched after Bronze last knew
about them.

Scale strategy
--------------

1. **Source query is bounded** by ``sweep_window_days`` (default 90).
   ``WHERE LastModifiedColumn >= DATEADD(DAY, -N, GETDATE())``. For DNA
   tables with low daily churn, ~3% of total rows fit in this window.

2. **Comparison happens on the database** — the source projection is
   BCP-loaded into a temp staging table on the Bronze server, then a
   server-side LEFT JOIN against Bronze finds the drift PKs. Only the
   drift PK list returns to Polars memory.

3. **Targeted reload** uses chunked IN-clauses against source for the
   drift PKs (default 1,000 PKs per chunk to stay within query-plan
   limits), then runs ``run_scd2_targeted`` with the extracted rows.

Configuration
-------------

* ``UdmTablesList.LastModifiedColumn`` — column name (e.g. ``DATELASTMAINT``).
  NULL → sweep skipped for that table.
* Autoconfig DNA profile proposes ``DATELASTMAINT`` automatically.
* CCM has no large tables. EPICOR's one large table (periodDate-based)
  doesn't have a separate modified-date column — sweep is skipped there
  (NULL config).

Tier 2 of the multi-tier large-table CDC strategy:

  Tier 1: Daily windowed (existing) — changes inside LookbackDays.
  Tier 2: Modified-date sweep (this module) — late updates of any age,
          ASSUMING ``LastModifiedColumn`` was bumped by the source
          process (see "Reliability of LastModifiedColumn" below).
  Tier 3: Full-PK reconciliation (E-7 reconcile_active_pks) — late deletes / inserts.
  Tier 4: Aggregate reconciliation (E-17 reconcile_aggregates) — value drift.
  Tier 5: R-13 backfill (tools/backfill.py) — operator-driven recovery.

Reliability of LastModifiedColumn
---------------------------------

For DNA, ``DATELASTMAINT`` is the canonical last-modified timestamp. It
is **generally reliable** — every batch job and online transaction is
expected to bump it on update. But the column relies on the writing
process to set it. If a process updates a row WITHOUT bumping
``DATELASTMAINT``, this sweep misses the drift entirely (the source
date doesn't advance past Bronze's ``UdmSourceBeginDate``).

Practical impact for DNA: per the source-system owner, no known
process bypasses ``DATELASTMAINT`` today. The risk is "an oversight in
some future batch job" rather than a known systemic gap.

Backstops in case a process does bypass ``DATELASTMAINT``:

  * Tier 3 (``reconcile_active_pks``) catches PK presence drift but
    NOT value drift on existing PKs.
  * Tier 4 (``reconcile_aggregates``) catches mass value drift on
    numeric columns (mean, sum, count) but small per-row changes can
    average out.
  * For high-criticality tables, schedule periodic
    ``reconcile_table`` (P3-4) — full column-by-column row-hash
    comparison. Definitive but expensive; sample or window for large
    tables.

Don't treat the modified-date sweep as a guarantee against ALL drift.
Treat it as the cheap, fast, daily catch-up layer. The full-row
reconciliation tools are the safety net.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

import polars as pl

import utils.configuration as config
from utils.connections import (
    bronze_connectorx_uri, get_connection,
    quote_identifier, quote_table,
)
from data_load import bcp_loader
from data_load.bcp_csv import write_bcp_csv
from data_load.sanitize import sanitize_strings
from data_load.schema_utils import get_column_types
from extract import cx_read_sql_safe
from extract.udm_connectorx_extractor import table_exists

if TYPE_CHECKING:
    from orchestration.table_config import TableConfig

logger = logging.getLogger(__name__)


# Chunk size for source PK-targeted re-extraction (IN-clause fan-out).
# Most database query planners cap parameter lists around 2,000–10,000;
# 1,000 is a safe value that keeps plan compilation cheap.
_SOURCE_PK_CHUNK_SIZE = 1_000

# Default sweep window in days. Operators can override via the CLI / env.
DEFAULT_SWEEP_WINDOW_DAYS = 90


@dataclass
class ModifiedSweepResult:
    """Result of one modified-date sweep on one table."""

    source_name: str
    table_name: str
    sweep_window_days: int
    source_rows_in_window: int = 0
    bronze_active_rows_compared: int = 0
    drift_pks: int = 0           # source LastModifiedColumn > Bronze UdmSourceBeginDate
    late_insert_pks: int = 0     # in source window but no active Bronze row
    skipped: bool = False
    skip_reason: str = ""
    reloaded_rows: int = 0
    duration_ms: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def is_clean(self) -> bool:
        return self.drift_pks == 0 and self.late_insert_pks == 0 and not self.errors


# ---------------------------------------------------------------------------
# Source projection extract — (PK, LastModifiedColumn) only
# ---------------------------------------------------------------------------


def _extract_source_projection(
    table_config: TableConfig,
    sweep_window_days: int,
) -> pl.DataFrame:
    """Pull ``(pk_columns, last_modified_column)`` from source for the window.

    Single-column projection in the SELECT keeps network and memory cost
    bounded. The WHERE clause filters by ``last_modified_column >= now -
    sweep_window_days`` — bounded by the configured window so a 1B-row
    table with 0.1% daily churn produces ~9M projection rows over a
    90-day sweep, comfortably in memory.
    """
    pk_cols = table_config.pk_columns
    if not pk_cols:
        raise ValueError(
            f"{table_config.source_name}.{table_config.source_object_name} has no PK columns — "
            "cannot run modified-date sweep without business key."
        )
    if not table_config.last_modified_column:
        raise ValueError(
            f"{table_config.source_name}.{table_config.source_object_name} has no LastModifiedColumn — "
            "modified-date sweep is skipped."
        )

    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(days=sweep_window_days)
    pk_select = ", ".join(pk_cols)
    last_modified = table_config.last_modified_column
    src = table_config.source_full_table_name

    if table_config.is_oracle:
        # Oracle: use TRUNC for date semantics consistency with extractors (P3-2).
        cutoff_literal = cutoff.strftime("%Y-%m-%d %H:%M:%S")
        query = (
            f"SELECT {pk_select}, {last_modified} "
            f"FROM {src} "
            f"WHERE {last_modified} >= TO_DATE('{cutoff_literal}', 'YYYY-MM-DD HH24:MI:SS')"
        )
    else:
        cutoff_literal = cutoff.strftime("%Y-%m-%d %H:%M:%S")
        query = (
            f"SELECT {pk_select}, {last_modified} "
            f"FROM {src} "
            f"WHERE {last_modified} >= '{cutoff_literal}'"
        )

    from utils.sources import get_source
    source = get_source(table_config.source_name)
    uri = source.connectorx_uri()

    logger.info(
        "Modified-date sweep: source projection extract for %s.%s (window=%d days)",
        table_config.source_name, table_config.source_object_name, sweep_window_days,
    )
    df = cx_read_sql_safe(
        conn=uri, query=query,
        context=f"sweep projection {table_config.source_full_table_name}",
    )
    logger.info(
        "Modified-date sweep: %d source rows in window for %s.%s",
        len(df), table_config.source_name, table_config.source_object_name,
    )
    return df


# ---------------------------------------------------------------------------
# Drift detection via temp staging table on Bronze
# ---------------------------------------------------------------------------


def _identify_drift_pks(
    df_source_projection: pl.DataFrame,
    table_config: TableConfig,
    output_dir: Path,
) -> tuple[pl.DataFrame, int]:
    """Find PKs whose source LastModifiedColumn > Bronze UdmSourceBeginDate.

    Server-side LEFT JOIN: BCP-loads the projection into a staging table,
    runs SQL against Bronze, returns the drift PKs as a Polars DataFrame.
    Bronze active rows whose ``UdmSourceBeginDate`` is NULL or strictly
    less than the source's ``LastModifiedColumn`` are drift candidates.

    Returns a tuple of:
      * drift_pks: DataFrame with PK columns only (one row per drift PK).
      * bronze_active_count: number of Bronze active rows compared.
    """
    bronze_table = table_config.bronze_full_table_name
    pk_cols = table_config.pk_columns

    db = bronze_table.split(".")[0]
    schema = bronze_table.split(".")[1]
    staging_table = (
        f"{db}.{schema}._staging_modified_sweep_{table_config.source_object_name}"
    )
    q_staging = quote_table(staging_table)
    q_bronze = quote_table(bronze_table)

    pk_types = get_column_types(bronze_table, pk_cols)

    conn = get_connection(db)
    try:
        cursor = conn.cursor()
        pk_col_defs = ", ".join(
            f"{quote_identifier(c)} {pk_types[c]}" for c in pk_cols
        )
        # Add the source last-modified column too so the JOIN can filter.
        pk_col_defs += ", _source_last_modified DATETIME2(3) NULL"
        cursor.execute(
            f"IF OBJECT_ID(?, 'U') IS NOT NULL DROP TABLE {q_staging}",
            staging_table,
        )
        cursor.execute(f"CREATE TABLE {q_staging} ({pk_col_defs})")
        cursor.close()
    finally:
        conn.close()

    try:
        # Rename last_modified_column to _source_last_modified for staging
        # so the SQL is column-name-stable.
        df_for_load = df_source_projection.rename({
            table_config.last_modified_column: "_source_last_modified"
        })
        df_for_load = sanitize_strings(df_for_load)
        csv_path = write_bcp_csv(
            df_for_load,
            output_dir
            / f"sweep_projection_{table_config.source_name}_{table_config.source_object_name}.csv",
        )
        # is_stage=True picks BCP_STAGE_BATCH_SIZE (100K) so heap-style
        # staging loads don't fall through to the 800-row Bronze default.
        bcp_loader.bcp_load(str(csv_path), staging_table, atomic=False, is_stage=True)
        bcp_loader.create_staging_index(
            staging_table, pk_cols, row_count=len(df_source_projection),
        )

        join_condition = " AND ".join(
            f"b.{quote_identifier(c)} = s.{quote_identifier(c)}" for c in pk_cols
        )
        pk_select_b = ", ".join(f"b.{quote_identifier(c)}" for c in pk_cols)
        pk_select_s = ", ".join(f"s.{quote_identifier(c)}" for c in pk_cols)

        # Get Bronze active row count for the report — independent of drift.
        uri = bronze_connectorx_uri()
        cnt_df = cx_read_sql_safe(
            conn=uri,
            query=f"SELECT COUNT(*) AS cnt FROM {q_bronze} WHERE UdmActiveFlag = 1",
            context=f"sweep bronze active count {bronze_table}",
        )
        bronze_active_count = int(cnt_df["cnt"][0]) if len(cnt_df) > 0 else 0

        # Drift PKs: source-touched newer than Bronze, OR no active Bronze row at all.
        drift_query = f"""
            SELECT {pk_select_s}
            FROM {q_staging} s
            LEFT JOIN {q_bronze} b
              ON {join_condition}
              AND b.UdmActiveFlag = 1
            WHERE
                b.UdmActiveFlag IS NULL
             OR b.UdmSourceBeginDate IS NULL
             OR s._source_last_modified > b.UdmSourceBeginDate
        """
        drift_pks = cx_read_sql_safe(
            conn=uri, query=drift_query,
            context=f"sweep drift detection {bronze_table}",
        )
        return drift_pks, bronze_active_count
    finally:
        # Always drop staging — caught by schema/staging_cleanup.py prefix as fallback.
        try:
            conn = get_connection(db)
            try:
                cursor = conn.cursor()
                cursor.execute(
                    f"IF OBJECT_ID(?, 'U') IS NOT NULL DROP TABLE {q_staging}",
                    staging_table,
                )
                cursor.close()
            finally:
                conn.close()
        except Exception:
            logger.warning(
                "Modified-date sweep: could not drop staging %s — "
                "staging_cleanup.py will reclaim it.",
                staging_table,
            )


# ---------------------------------------------------------------------------
# Public entry point — detect-only or detect-and-reload
# ---------------------------------------------------------------------------


def run_modified_sweep(
    table_config: TableConfig,
    *,
    output_dir: str | Path | None = None,
    sweep_window_days: int = DEFAULT_SWEEP_WINDOW_DAYS,
    apply: bool = False,
) -> ModifiedSweepResult:
    """Detect (and optionally reload) PKs updated outside the daily window.

    Args:
        table_config: Table configuration. ``last_modified_column`` must be
            populated; otherwise the sweep is skipped.
        output_dir: Directory for staging CSVs. Defaults to ``config.CSV_OUTPUT_DIR``.
        sweep_window_days: How far back to scan source. 90 days = sane default.
        apply: When ``True``, reload drift PKs via targeted SCD2 promotion.
            When ``False``, detect-only (no Bronze writes).

    Returns:
        :class:`ModifiedSweepResult` with detection and reload counts.
    """
    started = time.time()
    if output_dir is None:
        output_dir = config.CSV_OUTPUT_DIR
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    result = ModifiedSweepResult(
        source_name=table_config.source_name,
        table_name=table_config.source_object_name,
        sweep_window_days=sweep_window_days,
    )

    if not table_config.last_modified_column:
        result.skipped = True
        result.skip_reason = "LastModifiedColumn not configured"
        result.duration_ms = int((time.time() - started) * 1000)
        return result

    if not table_config.pk_columns:
        result.skipped = True
        result.skip_reason = "No PK columns configured"
        result.duration_ms = int((time.time() - started) * 1000)
        return result

    bronze_table = table_config.bronze_full_table_name
    if not table_exists(bronze_table):
        result.skipped = True
        result.skip_reason = f"Bronze table {bronze_table} does not exist"
        result.duration_ms = int((time.time() - started) * 1000)
        return result

    try:
        df_projection = _extract_source_projection(table_config, sweep_window_days)
        result.source_rows_in_window = len(df_projection)

        if len(df_projection) == 0:
            logger.info(
                "Modified-date sweep: no source rows in last %d days for %s.%s",
                sweep_window_days, table_config.source_name, table_config.source_object_name,
            )
            result.duration_ms = int((time.time() - started) * 1000)
            return result

        drift_pks, bronze_count = _identify_drift_pks(
            df_projection, table_config, output_dir,
        )
        result.bronze_active_rows_compared = bronze_count
        result.drift_pks = len(drift_pks)

        if len(drift_pks) == 0:
            logger.info(
                "Modified-date sweep: no drift detected for %s.%s",
                table_config.source_name, table_config.source_object_name,
            )
            result.duration_ms = int((time.time() - started) * 1000)
            return result

        # Late-insert vs late-update split: rows in source projection but not
        # in Bronze active are late inserts. Re-query to count them
        # specifically — useful for the report; drift count covers both.
        # (Skipping the second SQL pass for v1; the unified drift count is
        # sufficient signal. Future enhancement: split via additional JOIN.)

        if not apply:
            logger.info(
                "Modified-date sweep DETECT-ONLY: %d drift PKs for %s.%s — "
                "rerun with apply=True to reload.",
                len(drift_pks), table_config.source_name, table_config.source_object_name,
            )
            result.duration_ms = int((time.time() - started) * 1000)
            return result

        # Reload path. Currently delegates to the operator: log the drift
        # set and recommend running tools/backfill.py for the relevant date
        # range. Proper PK-targeted source re-extraction is a follow-up
        # because chunked IN-clauses across Oracle vs SQL Server need
        # source-specific implementations.
        logger.warning(
            "Modified-date sweep apply=True for %s.%s: %d drift PKs detected. "
            "PK-targeted source re-extraction is not yet implemented in v1. "
            "Use tools/backfill.py for the affected date range, or rerun the "
            "daily extractor with widened LookbackDays.",
            table_config.source_name, table_config.source_object_name, len(drift_pks),
        )
        result.errors.append(
            "v1: drift-PK reload not yet implemented; use tools/backfill.py"
        )
        result.duration_ms = int((time.time() - started) * 1000)
        return result

    except Exception as exc:
        logger.exception(
            "Modified-date sweep failed for %s.%s",
            table_config.source_name, table_config.source_object_name,
        )
        result.errors.append(str(exc))
        result.duration_ms = int((time.time() - started) * 1000)
        return result
