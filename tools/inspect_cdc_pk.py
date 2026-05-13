"""Per-PK CDC diagnostic — show every Stage and Bronze row for a primary key.

Usage::

    # Inspect ACCTNBR=12345 in DNA.ACCT
    python3 tools/inspect_cdc_pk.py --source DNA --table ACCT --pk-values 12345

    # Multi-column PK (comma-separated values, in PK ordinal order)
    python3 tools/inspect_cdc_pk.py --source DNA --table ACCTACCTROLEPERS \\
        --pk-values 12345,Owner,67890

    # Skip the source check (e.g. when source is unreachable)
    python3 tools/inspect_cdc_pk.py --source DNA --table ACCT --pk-values 12345 --no-source

What it shows
-------------

* **Source check** — does the PK exist in source today? (One quick `SELECT 1`.)
* **Stage history** — every row in ``UDM_Stage.<source>.<table>_cdc`` for the
  PK, ordered by ``_cdc_valid_from``. Highlights the current row(s) and the
  most recent close.
* **Bronze history** — every row in ``UDM_Bronze.<source>.<table>_scd2_python``
  for the PK, ordered by ``UdmEffectiveDateTime``. Includes the dual
  date-pair (load-time + source-date) and the SCD2 operation/flag.
* **Diagnostic interpretation** — based on the row patterns, classifies the
  PK's state as one of:

    * ``HEALTHY_ACTIVE``           — exactly one Stage current=1 row + one
                                     Bronze Flag=1 row, hashes match.
    * ``HEALTHY_DELETED``          — zero Stage current rows, Bronze
                                     Flag=2 (deleted at source). By design.
    * ``IN_FLIGHT_ORPHAN``         — Bronze Flag=0 + Op IN ('U','R') with
                                     both end dates NULL. Will auto-heal
                                     on next run via B-4 cleanup.
    * ``DUPLICATE_CURRENT_STAGE``  — Stage has >1 current=1 rows. P0-9
                                     crash recovery artifact; next run
                                     dedups via L-1 ``_dedup_stage_current``.
    * ``DUPLICATE_ACTIVE_BRONZE``  — Bronze has >1 Flag=1 rows. P1-16
                                     crash artifact; next SCD2 run
                                     dedups via ``_dedup_bronze_active``.
    * ``STAGE_BRONZE_HASH_DIVERGE`` — Stage current row's ``_row_hash``
                                     differs from Bronze active row's
                                     ``UdmHash``. Next run should reconcile
                                     via normal CDC + SCD2.
    * ``STAGE_CURRENT_NO_BRONZE_ACTIVE`` — Stage says current, Bronze
                                     has no active row. Bronze SCD2
                                     missed the PK; investigate.
    * ``BRONZE_ACTIVE_NO_STAGE_CURRENT`` — Bronze active, Stage no
                                     current. Stage out of sync;
                                     investigate.
    * ``UNKNOWN``                  — pattern doesn't match any rule.
                                     Output is dumped for manual review.

Read-only — does not modify data.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import utils.configuration as config
from utils.connections import (
    get_connection, quote_identifier, quote_table, stage_connectorx_uri,
    bronze_connectorx_uri,
)
from utils.sources import get_source
from orchestration.table_config import TableConfigLoader

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# Oracle connections use thin mode (default). Oracle Instant Client is not
# installed in the runtime environment, so any call to
# oracledb.init_oracle_client() raises DPI-1047. oracledb.connect() works
# directly against the listener without thick-mode initialization.


def _coerce_pk_values(raw_values: list[str], pk_columns: list[str]) -> list[str]:
    """Pair raw CLI values with PK column names. Returns the values list
    after a length check."""
    if len(raw_values) != len(pk_columns):
        raise SystemExit(
            f"--pk-values has {len(raw_values)} value(s) but the PK has "
            f"{len(pk_columns)} column(s): {pk_columns}. Pass the values "
            f"in the same order, comma-separated."
        )
    return raw_values


def _where_clause(
    pk_columns: list[str],
    pk_values: list[str],
    alias: str = "",
    *,
    is_oracle: bool = False,
) -> str:
    """Build a parameter-free WHERE clause for the PK. Values are inlined
    after a CAST/quote pass — fine for a read-only diagnostic CLI; do not
    reuse this pattern in production write paths.

    When ``is_oracle`` is True, column names are emitted unquoted (Oracle
    uppercases unquoted identifiers, which matches column names as stored
    in ``ALL_TAB_COLUMNS``), and string literals use plain ``'...'`` quoting
    (no ``N''`` prefix — that's SQL Server-only)."""
    parts = []
    prefix = f"{alias}." if alias else ""
    for col, val in zip(pk_columns, pk_values):
        col_ref = col if is_oracle else quote_identifier(col)
        # Quote string-y values; leave numeric values alone. Best-effort.
        try:
            int(val)
            parts.append(f"{prefix}{col_ref} = {val}")
        except ValueError:
            try:
                float(val)
                parts.append(f"{prefix}{col_ref} = {val}")
            except ValueError:
                # Treat as string. Escape single quotes.
                escaped = val.replace("'", "''")
                literal = f"'{escaped}'" if is_oracle else f"N'{escaped}'"
                parts.append(f"{prefix}{col_ref} = {literal}")
    return " AND ".join(parts)


def _print_separator(title: str) -> None:
    bar = "=" * 78
    print()
    print(bar)
    print(title)
    print(bar)


def _fmt_row(cols: list[str], row: tuple) -> str:
    return "  " + "  |  ".join(
        f"{c}={('NULL' if v is None else str(v))[:40]}"
        for c, v in zip(cols, row)
    )


# ---------------------------------------------------------------------------
# Source check
# ---------------------------------------------------------------------------


def _check_source(table_config, pk_columns: list[str], pk_values: list[str]) -> bool | None:
    """Return True if PK exists in source, False if not, None if unreachable.

    The source query is qualified by **schema only** — e.g.
    ``SELECT 1 FROM OSIBANK.ACCT`` (Oracle) — not by database. The
    connection parameters already scope us to the correct database
    (Oracle service name, SQL Server database), so prefixing with the
    database name is redundant and breaks if the source DB is renamed
    or reached through a different alias.
    """
    is_oracle = table_config.is_oracle
    schema = table_config.source_schema_name
    table = table_config.source_object_name
    where = _where_clause(pk_columns, pk_values, is_oracle=is_oracle)
    query = f"SELECT 1 FROM {schema}.{table} WHERE {where}"

    print(f"Source query: {query}")

    try:
        source = get_source(table_config.source_name)
    except Exception as exc:
        print(f"  Could not resolve source connection: {exc}")
        return None

    try:
        if table_config.is_oracle:
            import oracledb
            with oracledb.connect(**source.oracledb_connect_params()) as conn:
                with conn.cursor() as cursor:
                    cursor.execute(query)
                    row = cursor.fetchone()
                    return row is not None
        else:
            import pyodbc
            with pyodbc.connect(source.pyodbc_connection_string(), autocommit=True) as conn:
                cursor = conn.cursor()
                cursor.execute(query)
                row = cursor.fetchone()
                return row is not None
    except Exception as exc:
        print(f"  Source check failed: {exc}")
        return None


# ---------------------------------------------------------------------------
# Stage and Bronze pulls
# ---------------------------------------------------------------------------


_STAGE_AUDIT_COLS = [
    "_cdc_operation",
    "_cdc_valid_from",
    "_cdc_valid_to",
    "_cdc_is_current",
    "_cdc_batch_id",
    "_extracted_at",
    "_row_hash",
]

_BRONZE_AUDIT_COLS = [
    "_scd2_key",
    "UdmActiveFlag",
    "UdmScd2Operation",
    "UdmEffectiveDateTime",
    "UdmEndDateTime",
    "UdmSourceBeginDate",
    "UdmSourceEndDate",
    "UdmHash",
    "UdmModifiedBy",
]


def _fetch_rows(db: str, query: str) -> tuple[list[str], list[tuple]]:
    conn = get_connection(db)
    try:
        cursor = conn.cursor()
        cursor.execute(query)
        cols = [d[0] for d in cursor.description]
        rows = cursor.fetchall()
        cursor.close()
        return cols, [tuple(r) for r in rows]
    finally:
        conn.close()


def _fetch_stage_rows(table_config, pk_columns: list[str], pk_values: list[str]):
    full = table_config.stage_full_table_name
    db = full.split(".")[0]
    where = _where_clause(pk_columns, pk_values)
    cols_csv = ", ".join(quote_identifier(c) for c in pk_columns + _STAGE_AUDIT_COLS)
    query = (
        f"SELECT {cols_csv} FROM {quote_table(full)} "
        f"WHERE {where} "
        f"ORDER BY [_cdc_valid_from] ASC, [_cdc_batch_id] ASC"
    )
    return _fetch_rows(db, query)


def _fetch_bronze_rows(table_config, pk_columns: list[str], pk_values: list[str]):
    full = table_config.bronze_full_table_name
    db = full.split(".")[0]
    where = _where_clause(pk_columns, pk_values)
    cols_csv = ", ".join(quote_identifier(c) for c in pk_columns + _BRONZE_AUDIT_COLS)
    query = (
        f"SELECT {cols_csv} FROM {quote_table(full)} "
        f"WHERE {where} "
        f"ORDER BY [UdmEffectiveDateTime] ASC, [_scd2_key] ASC"
    )
    return _fetch_rows(db, query)


# ---------------------------------------------------------------------------
# Diagnosis
# ---------------------------------------------------------------------------


def _diagnose(
    in_source: bool | None,
    stage_cols: list[str],
    stage_rows: list[tuple],
    bronze_cols: list[str],
    bronze_rows: list[tuple],
) -> tuple[str, str]:
    """Classify the PK's state and produce a recommendation.

    Returns (verdict, recommendation).
    """
    # Index helpers — find column positions in the row tuples.
    si = {c: i for i, c in enumerate(stage_cols)}
    bi = {c: i for i, c in enumerate(bronze_cols)}

    stage_current = [r for r in stage_rows if r[si["_cdc_is_current"]] == 1]
    stage_current_count = len(stage_current)

    bronze_active = [r for r in bronze_rows if r[bi["UdmActiveFlag"]] == 1]
    bronze_deleted = [r for r in bronze_rows if r[bi["UdmActiveFlag"]] == 2]
    bronze_inflight = [
        r for r in bronze_rows
        if r[bi["UdmActiveFlag"]] == 0
        and r[bi["UdmScd2Operation"]] in ("U", "R")
        and r[bi["UdmEndDateTime"]] is None
        and r[bi["UdmSourceEndDate"]] is None
    ]

    # Pattern: one current + one active + matching hashes
    if stage_current_count == 1 and len(bronze_active) == 1:
        s_hash = stage_current[0][si["_row_hash"]]
        b_hash = bronze_active[0][bi["UdmHash"]]
        if s_hash == b_hash:
            return (
                "HEALTHY_ACTIVE",
                "PK is in source, Stage and Bronze agree, hashes match. "
                "No action needed."
            )
        return (
            "STAGE_BRONZE_HASH_DIVERGE",
            f"Stage current _row_hash ({s_hash[:16]}...) differs from "
            f"Bronze active UdmHash ({b_hash[:16]}...). Next CDC + SCD2 run "
            "should reconcile (Stage hash typically wins as the newer extract). "
            "If divergence persists across runs, investigate `add_row_hash` "
            "input differences (ExcludeFromHash, NULL handling, dtype "
            "coercion)."
        )

    # Pattern: zero current + Bronze Flag=2
    if stage_current_count == 0 and len(bronze_deleted) >= 1 and len(bronze_active) == 0:
        return (
            "HEALTHY_DELETED",
            "Zero Stage current rows + Bronze Flag=2 = the PK was deleted "
            "from source. By design, Stage doesn't keep a current=1 marker "
            "for deleted PKs (Bronze Flag=2 is the audit trail). "
            "If you need to query 'currently in source', use Stage WHERE "
            "_cdc_is_current=1. If you need 'ever existed including deleted',"
            " query Bronze WHERE UdmActiveFlag IN (1, 2)."
        )

    # Pattern: in-flight orphan
    if bronze_inflight:
        return (
            "IN_FLIGHT_ORPHAN",
            f"Bronze has {len(bronze_inflight)} in-flight row(s) (Flag=0, "
            f"Op IN ('U','R'), both EndDates NULL). The previous run "
            f"crashed between SCD2 INSERT and activation. Next run will "
            f"clean these up via _cleanup_orphaned_inactive_rows (B-4). "
            f"Or run `python3 tools/repair_scd2.py --source {{source}} "
            f"--table {{table}} --apply` now to reap them."
        )

    # Pattern: multiple Stage currents
    if stage_current_count > 1:
        return (
            "DUPLICATE_CURRENT_STAGE",
            f"Stage has {stage_current_count} _cdc_is_current=1 rows for "
            f"this PK. P0-9 INSERT-first crash recovery artifact. Next run "
            f"will dedup via _dedup_stage_current (L-1) before CDC compares. "
            f"Safe to leave; auto-heals."
        )

    # Pattern: multiple Bronze actives
    if len(bronze_active) > 1:
        return (
            "DUPLICATE_ACTIVE_BRONZE",
            f"Bronze has {len(bronze_active)} Flag=1 rows for this PK. "
            f"P1-16 crash recovery artifact. Next SCD2 run will dedup via "
            f"_dedup_bronze_active. Or run `tools/repair_scd2.py "
            f"--no-sentinel-fill --no-orphan-cleanup --apply` to dedup now."
        )

    # Pattern: Stage current exists but no Bronze active
    if stage_current_count == 1 and len(bronze_active) == 0 and len(bronze_deleted) == 0:
        if not bronze_rows:
            return (
                "STAGE_CURRENT_NO_BRONZE_ROWS",
                "Stage has a current row but Bronze has no rows for this "
                "PK at all. SCD2 promotion didn't reach this PK. Check "
                "PipelineEventLog for the most recent SCD2_PROMOTION event "
                "on this table. If the SCD2 step failed, fix and re-run; "
                "the next run will INSERT this PK into Bronze via the "
                "anti-join path."
            )
        return (
            "STAGE_CURRENT_NO_BRONZE_ACTIVE",
            "Stage current exists, Bronze has rows but none active. SCD2 "
            "may have closed all versions without inserting the new one. "
            "Investigate Bronze history (likely a series of Flag=0 closes "
            "without a matching activation). Re-running the table should "
            "produce a new INSERT. If it doesn't, escalate."
        )

    # Pattern: Bronze active exists but no Stage current
    if stage_current_count == 0 and len(bronze_active) >= 1:
        if in_source:
            return (
                "BRONZE_ACTIVE_NO_STAGE_CURRENT_PK_IN_SOURCE",
                "Bronze active row exists, Stage has no current row, AND "
                "the PK is currently in source. Stage is out of sync with "
                "source and Bronze. Re-run the table — the anti-join will "
                "see this PK as 'in source not in Stage current' and "
                "INSERT a fresh Stage row, which CDC will compare against "
                "no existing current and produce 'I'. Bronze will then see "
                "an unchanged hash and the row stays put. If after re-run "
                "the issue persists, the source extraction is dropping the "
                "PK — investigate the extractor's WHERE clause."
            )
        return (
            "BRONZE_ACTIVE_NO_STAGE_CURRENT_PK_NOT_IN_SOURCE",
            "Bronze active row exists, Stage has no current row, and the "
            "PK is NOT in source today. The PK was probably deleted at "
            "source AND Stage was already updated to reflect that, but "
            "Bronze SCD2 close hasn't run yet. Run the table — Bronze "
            "anti-join will close the active row to Flag=2."
        )

    # Pattern: zero current Stage AND zero Bronze AND in source
    if stage_current_count == 0 and not bronze_rows and in_source:
        return (
            "NEW_PK_NOT_YET_LOADED",
            "PK exists in source but neither Stage nor Bronze has any "
            "row. Has the table been run since the PK was created? "
            "Re-run the table; it should appear as a fresh INSERT."
        )

    # Pattern: zero everywhere AND not in source
    if stage_current_count == 0 and not bronze_rows and in_source is False:
        return (
            "NOT_FOUND",
            "PK doesn't exist in source, Stage, or Bronze. The PK value "
            "may be wrong, or the row was never loaded into the pipeline."
        )

    # Anything else
    return (
        "UNKNOWN",
        "Pattern doesn't match any documented case. Inspect the raw row "
        "dumps above and share with the engine team. Specifically note "
        "_cdc_is_current values, UdmActiveFlag values, and the order of "
        "events by _cdc_valid_from / UdmEffectiveDateTime."
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", required=True, help="SourceName (DNA / CCM / EPICOR / ...).")
    parser.add_argument("--table", required=True, help="SourceObjectName.")
    parser.add_argument(
        "--pk-values", required=True,
        help="Comma-separated PK values in PK ordinal order (e.g. '12345' or '12345,Owner,67890').",
    )
    parser.add_argument(
        "--no-source", action="store_true",
        help="Skip the source-system check (useful when source is unreachable or slow).",
    )
    args = parser.parse_args()

    raw_values = [v.strip() for v in args.pk_values.split(",")]

    loader = TableConfigLoader()
    configs = (
        loader.load_small_tables(source_name=args.source, table_name=args.table)
        + loader.load_large_tables(source_name=args.source, table_name=args.table)
    )
    if not configs:
        logger.error("No matching row in UdmTablesList for source=%s table=%s.",
                     args.source, args.table)
        return 2
    cfg = configs[0]

    pk_columns = cfg.pk_columns
    if not pk_columns:
        logger.error(
            "No PK columns configured for %s.%s. Run column-sync first.",
            args.source, args.table,
        )
        return 2

    pk_values = _coerce_pk_values(raw_values, pk_columns)

    print()
    print(f"Inspecting {cfg.source_name}.{cfg.source_object_name}  PK = "
          f"{dict(zip(pk_columns, pk_values))}")
    print(f"Stage : {cfg.stage_full_table_name}")
    print(f"Bronze: {cfg.bronze_full_table_name}")
    print(f"Source: {cfg.source_full_table_name}")

    # 1. Source check
    _print_separator("1. SOURCE CHECK")
    if args.no_source:
        in_source = None
        print("  Skipped (--no-source).")
    else:
        in_source = _check_source(cfg, pk_columns, pk_values)
        if in_source is True:
            print("  Result: PK IS in source today.")
        elif in_source is False:
            print("  Result: PK is NOT in source today.")
        else:
            print("  Result: source unreachable / inconclusive.")

    # 2. Stage history
    _print_separator(f"2. STAGE HISTORY  ({cfg.stage_full_table_name})")
    try:
        stage_cols, stage_rows = _fetch_stage_rows(cfg, pk_columns, pk_values)
        print(f"  {len(stage_rows)} row(s) in Stage for this PK:")
        for r in stage_rows:
            print(_fmt_row(stage_cols, r))
    except Exception as exc:
        print(f"  Stage read failed: {exc}")
        stage_cols, stage_rows = [], []

    # 3. Bronze history
    _print_separator(f"3. BRONZE HISTORY  ({cfg.bronze_full_table_name})")
    try:
        bronze_cols, bronze_rows = _fetch_bronze_rows(cfg, pk_columns, pk_values)
        print(f"  {len(bronze_rows)} row(s) in Bronze for this PK:")
        for r in bronze_rows:
            print(_fmt_row(bronze_cols, r))
    except Exception as exc:
        print(f"  Bronze read failed: {exc}")
        bronze_cols, bronze_rows = [], []

    # 4. Diagnosis
    _print_separator("4. DIAGNOSIS")
    verdict, recommendation = _diagnose(
        in_source, stage_cols, stage_rows, bronze_cols, bronze_rows,
    )
    recommendation = recommendation.format(
        source=cfg.source_name, table=cfg.source_object_name,
    )
    print(f"  Verdict       : {verdict}")
    print(f"  Recommendation: {recommendation}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
