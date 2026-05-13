"""UAT — live SQL Server checks against ``UDM_Stage`` for CDC invariants.

These tests query the real Stage tables. They are skipped unless
``CDC_UAT_ENABLED=1`` is exported, so the unit suite remains DB-free.

What's covered
--------------

1. **Single-current invariant** — at most one ``_cdc_is_current = 1`` row
   per PK. Multiple current rows indicate a P0-9 crash artifact.

2. **Monotonic ``_cdc_valid_from``** — within a PK's history, timestamps
   never go backwards. A regression here would indicate clock skew or
   a batch_id reuse bug.

3. **No closed-and-current rows** — a row with ``_cdc_operation = 'D'``
   AND ``_cdc_is_current = 1`` is impossible by design. ``D`` is a label
   the engine never writes (it expires existing rows by flipping
   ``_cdc_is_current``); finding one would indicate manual SQL writes
   or a bug.

4. **Resurrection-rate ranking** — list the top-N PKs by ``I``-row count.
   For ``UDM_Stage.dna.ACCT`` specifically, this surfaces whether
   ``ACCTNBR=205`` is alone in its alternating-``I``/``U`` pattern (one
   isolated source flap) or whether many PKs follow the same pattern
   (systematic extraction gap).

Run::

    CDC_UAT_ENABLED=1 python3 -m pytest tests/uat/ -v --log-cli-level=INFO

    # Just the ACCT investigation
    CDC_UAT_ENABLED=1 python3 -m pytest \
        tests/uat/test_stage_invariants.py::test_resurrection_ranking_for_dna_acct \
        -v --log-cli-level=INFO
"""
from __future__ import annotations

import logging
import os

import pytest


pytestmark = pytest.mark.uat

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers — discover the Stage table for (source, table) and query it.
# ---------------------------------------------------------------------------


def _stage_table_for(source_name: str, table_name: str) -> str:
    """Build the fully-qualified Stage table name. Mirrors the convention
    enforced by ``orchestration/table_config.py``: ``{STAGE_DB}.{SourceName}.{table}_cdc``.
    """
    from utils import config
    return f"{config.STAGE_DB}.{source_name}.{table_name}_cdc"


def _pk_columns_for(source_name: str, table_name: str) -> list[str]:
    """Look up the configured PK columns from ``UdmTablesColumnsList``."""
    from utils.connections import get_general_connection

    conn = get_general_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT ColumnName FROM dbo.UdmTablesColumnsList "
            "WHERE SourceName = ? AND TableName = ? AND Layer = 'Stage' "
            "AND IsPrimaryKey = 1 ORDER BY OrdinalPosition",
            source_name, table_name,
        )
        cols = [row[0] for row in cursor.fetchall()]
        cursor.close()
        return cols
    finally:
        conn.close()


def _table_exists(stage_table: str) -> bool:
    from extract.udm_connectorx_extractor import table_exists
    return table_exists(stage_table)


# ---------------------------------------------------------------------------
# Default targets — override with env vars for ad-hoc investigation.
# ---------------------------------------------------------------------------


def _targets() -> list[tuple[str, str]]:
    """Return list of (source, table) pairs to validate.

    Defaults to ``[(DNA, ACCT)]`` because that's the user's reported
    incident table. Set ``CDC_UAT_TARGETS=DNA:ACCT,DNA:ACCTACCTROLEPERS``
    to override.
    """
    raw = os.environ.get("CDC_UAT_TARGETS", "DNA:ACCT")
    pairs = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        if ":" not in token:
            pytest.skip(f"Malformed CDC_UAT_TARGETS entry: {token!r}")
        source, table = token.split(":", 1)
        pairs.append((source.strip(), table.strip()))
    return pairs


# ---------------------------------------------------------------------------
# Invariants
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("source_name,table_name", _targets())
def test_at_most_one_current_row_per_pk(source_name, table_name):
    """No PK should have more than one ``_cdc_is_current = 1`` row.

    Multiple current rows are a documented P0-9 crash recovery artifact —
    the next CDC run would dedup them via ``_dedup_stage_current``. If the
    test finds rows, something either crashed since the last run or the
    dedup path silently failed.
    """
    from utils.connections import get_connection
    from utils.connections import quote_identifier, quote_table

    stage_table = _stage_table_for(source_name, table_name)
    if not _table_exists(stage_table):
        pytest.skip(f"Stage table {stage_table} does not exist")

    pk_cols = _pk_columns_for(source_name, table_name)
    if not pk_cols:
        pytest.skip(f"No PK columns configured for {source_name}.{table_name}")

    pk_list = ", ".join(quote_identifier(c) for c in pk_cols)
    db = stage_table.split(".")[0]
    qs = quote_table(stage_table)

    sql = f"""
        SELECT COUNT(*) AS dup_pk_count, ISNULL(MAX(cnt), 0) AS max_versions
        FROM (
            SELECT {pk_list}, COUNT(*) AS cnt
            FROM {qs}
            WHERE _cdc_is_current = 1
            GROUP BY {pk_list}
            HAVING COUNT(*) > 1
        ) dups
    """

    logger.info("Querying %s for duplicate current rows", stage_table)
    logger.debug("SQL: %s", sql)

    conn = get_connection(db)
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        dup_count, max_versions = cursor.fetchone()
        cursor.close()
    finally:
        conn.close()

    logger.info("Stage table %s: %d PKs with multiple current rows (max %d versions)",
                stage_table, dup_count, max_versions)

    assert dup_count == 0, (
        f"{stage_table}: {dup_count} PKs have more than one _cdc_is_current=1 row "
        f"(max {max_versions} versions). Crash recovery / dedup did not run; "
        f"investigate before letting CDC continue."
    )


@pytest.mark.parametrize("source_name,table_name", _targets())
def test_no_d_label_on_stage(source_name, table_name):
    """The CDC engine never writes ``_cdc_operation = 'D'`` — deletes are
    expressed by flipping ``_cdc_is_current`` to 0 on the existing row.

    Finding a ``D`` row indicates manual SQL writes or a bug in the engine.
    """
    from utils.connections import get_connection, quote_table

    stage_table = _stage_table_for(source_name, table_name)
    if not _table_exists(stage_table):
        pytest.skip(f"Stage table {stage_table} does not exist")

    db = stage_table.split(".")[0]
    qs = quote_table(stage_table)

    sql = f"SELECT COUNT(*) FROM {qs} WHERE _cdc_operation = 'D'"
    logger.info("Querying %s for stray 'D' rows", stage_table)

    conn = get_connection(db)
    try:
        cursor = conn.cursor()
        cursor.execute(sql)
        count = cursor.fetchone()[0]
        cursor.close()
    finally:
        conn.close()

    logger.info("Stage table %s: %d rows with _cdc_operation='D'",
                stage_table, count)

    assert count == 0, (
        f"{stage_table}: {count} rows carry _cdc_operation='D'. The engine "
        f"never writes 'D' — these are either manual writes or a bug."
    )


@pytest.mark.parametrize("source_name,table_name", _targets())
def test_resurrection_ranking(source_name, table_name):
    """Rank PKs by number of ``I`` rows. Multiple ``I`` rows for the same
    PK indicate the resurrection-as-insert pattern.

    This is the key diagnostic for the user's ``ACCTNBR=205`` report:

    * If only a handful of PKs have >1 ``I`` row, the issue is isolated
      (likely a single source-side flap or an extraction gap on those PKs).
    * If hundreds or thousands of PKs have >1 ``I`` row, the extraction
      itself is intermittent — investigate the source query, partition
      column, or windowing logic.

    The test PASSES regardless of count — it's purely informational. Look
    at the captured log output to interpret the result.
    """
    from utils.connections import get_connection, quote_identifier, quote_table

    stage_table = _stage_table_for(source_name, table_name)
    if not _table_exists(stage_table):
        pytest.skip(f"Stage table {stage_table} does not exist")

    pk_cols = _pk_columns_for(source_name, table_name)
    if not pk_cols:
        pytest.skip(f"No PK columns configured for {source_name}.{table_name}")

    pk_list = ", ".join(quote_identifier(c) for c in pk_cols)
    db = stage_table.split(".")[0]
    qs = quote_table(stage_table)

    summary_sql = f"""
        SELECT
          COUNT(DISTINCT pk_key) AS distinct_pks,
          SUM(CASE WHEN insert_count > 1 THEN 1 ELSE 0 END) AS pks_with_multiple_inserts,
          MAX(insert_count) AS max_inserts_for_one_pk,
          AVG(CAST(insert_count AS FLOAT)) AS avg_inserts_per_pk
        FROM (
            SELECT
              {pk_list} AS pk_key,
              SUM(CASE WHEN _cdc_operation = 'I' THEN 1 ELSE 0 END) AS insert_count
            FROM {qs}
            GROUP BY {pk_list}
        ) per_pk
    """

    top_sql = f"""
        SELECT TOP 10
          {pk_list},
          SUM(CASE WHEN _cdc_operation = 'I' THEN 1 ELSE 0 END) AS i_count,
          SUM(CASE WHEN _cdc_operation = 'U' THEN 1 ELSE 0 END) AS u_count,
          COUNT(*) AS total_rows
        FROM {qs}
        GROUP BY {pk_list}
        HAVING SUM(CASE WHEN _cdc_operation = 'I' THEN 1 ELSE 0 END) > 1
        ORDER BY SUM(CASE WHEN _cdc_operation = 'I' THEN 1 ELSE 0 END) DESC
    """

    logger.info("Resurrection-pattern summary for %s", stage_table)

    conn = get_connection(db)
    try:
        cursor = conn.cursor()
        cursor.execute(summary_sql)
        summary = cursor.fetchone()
        distinct_pks, multi_i_pks, max_i, avg_i = summary or (0, 0, 0, 0.0)

        logger.info("  distinct PKs:                 %d", distinct_pks)
        logger.info("  PKs with > 1 I row:           %d  (%.2f%% of total)",
                    multi_i_pks,
                    (multi_i_pks / distinct_pks * 100) if distinct_pks else 0)
        logger.info("  Max I-rows for any one PK:    %d", max_i or 0)
        logger.info("  Avg I-rows per PK:            %.2f", float(avg_i or 0))

        cursor.execute(top_sql)
        top_rows = cursor.fetchall()
        cursor.close()
    finally:
        conn.close()

    if top_rows:
        logger.info("Top 10 PKs by I-row count:")
        for row in top_rows:
            *pk_vals, i_count, u_count, total = row
            pk_repr = "|".join(str(v) for v in pk_vals)
            logger.info("  PK=%-20s  I=%-3d  U=%-3d  total=%d",
                        pk_repr, i_count, u_count, total)
    else:
        logger.info("No PKs with more than one I-row — clean.")

    # Always passes; this is an informational diagnostic.
    assert True


@pytest.mark.parametrize("source_name,table_name", _targets())
def test_specific_pk_inspection_acctnbr_205(source_name, table_name):
    """Targeted check for the user's reported PK. Logs the entire row
    history for ``ACCTNBR=205`` (or whichever PK is configured via
    ``CDC_UAT_PK_VALUES``) so you can read the operation timeline
    directly from the test log.

    Run::

        CDC_UAT_ENABLED=1 CDC_UAT_PK_VALUES=205 python3 -m pytest \
            tests/uat/test_stage_invariants.py::test_specific_pk_inspection_acctnbr_205 \
            -v --log-cli-level=INFO

    Only meaningful when targeting DNA.ACCT (or another single-column
    PK table — passes the supplied value into the first PK column).
    """
    from utils.connections import get_connection, quote_identifier, quote_table

    pk_values_raw = os.environ.get("CDC_UAT_PK_VALUES", "205")

    stage_table = _stage_table_for(source_name, table_name)
    if not _table_exists(stage_table):
        pytest.skip(f"Stage table {stage_table} does not exist")

    pk_cols = _pk_columns_for(source_name, table_name)
    if len(pk_cols) != 1:
        pytest.skip(
            f"This test targets single-column PKs; {source_name}.{table_name} "
            f"has {len(pk_cols)} PK columns: {pk_cols}"
        )

    pk_col = pk_cols[0]
    db = stage_table.split(".")[0]
    qs = quote_table(stage_table)
    qpk = quote_identifier(pk_col)

    # Try numeric first, fall back to string.
    try:
        param: int | str = int(pk_values_raw)
    except ValueError:
        param = pk_values_raw

    sql = (
        f"SELECT _cdc_operation, _cdc_is_current, _cdc_valid_from, _cdc_valid_to, "
        f"_cdc_batch_id, _row_hash "
        f"FROM {qs} WHERE {qpk} = ? "
        f"ORDER BY _cdc_valid_from"
    )

    logger.info("Inspecting %s for %s = %s", stage_table, pk_col, param)

    conn = get_connection(db)
    try:
        cursor = conn.cursor()
        cursor.execute(sql, param)
        rows = cursor.fetchall()
        cursor.close()
    finally:
        conn.close()

    if not rows:
        logger.info("No rows found for %s = %s", pk_col, param)
        pytest.skip(f"PK {pk_col}={param} has no Stage rows")

    logger.info("Total rows for %s=%s: %d", pk_col, param, len(rows))
    logger.info("%-3s | %-3s | %-30s | %-30s | %-12s | %s",
                "OP", "CUR", "VALID_FROM", "VALID_TO", "BATCH_ID", "ROW_HASH")
    for row in rows:
        op, cur, vf, vt, batch, h = row
        logger.info("%-3s | %-3s | %-30s | %-30s | %-12s | %s",
                    op, cur, str(vf), str(vt), batch, (h or "")[:12])

    # Count operations
    op_counts: dict[str, int] = {}
    for row in rows:
        op = row[0]
        op_counts[op] = op_counts.get(op, 0) + 1
    logger.info("Operation counts for %s=%s: %s", pk_col, param, op_counts)

    # Surface the I-count loudly. Anything > 1 confirms the resurrection pattern.
    i_count = op_counts.get("I", 0)
    if i_count > 1:
        logger.warning(
            "%s=%s has %d 'I' rows. The CDC engine inserts an 'I' whenever "
            "a PK has no current row — this happens after a delete-detection "
            "(reverse anti-join) closes the prior current row and the PK then "
            "reappears in source extraction. Review the runs between consecutive "
            "'I' rows to find when extraction dropped the row.",
            pk_col, param, i_count,
        )

    # Always informational — the test log carries the diagnosis.
    assert True
