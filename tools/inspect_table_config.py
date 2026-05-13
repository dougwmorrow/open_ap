"""Inspect the runtime ``TableConfig`` for a given source/table.

Diagnostic for "the value is set in UdmTablesList but the pipeline
isn't honoring it" symptoms — e.g. ``StripSuffix = 1`` set but Stage
table still gets the ``_cdc`` suffix; ``MaxRowsPerDay`` set but the
P1-13 guard still uses the multiplier check.

Runs the same code path the pipeline uses
(``TableConfigLoader.load_large_tables`` /
``load_small_tables``) and prints:

* The raw row from ``UdmTablesList`` (every column the loader SELECTs).
* The ``TableConfig`` fields the orchestrator will consult.
* Resolved Stage / Bronze table names.
* What the P1-13 guard threshold will resolve to with the current
  ``MaxRowsPerDay`` value.

If a field is wrong here, the bug is in either the UPDATE statement or
the loader. If the field is right here but the pipeline still
misbehaves, the bug is downstream of the loader.

Read-only — no writes anywhere.

Usage
-----

::

    python3 tools/inspect_table_config.py --source DNA --table CARDTXN
    python3 tools/inspect_table_config.py --source CCM --table AuditLog
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import polars as pl

import utils.configuration as config
from utils.connections import get_general_connection
from orchestration.table_config import TableConfigLoader

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _print_section(title: str) -> None:
    print()
    print("=" * 70)
    print(title)
    print("=" * 70)


def _raw_row(source_name: str, table_name: str) -> dict | None:
    """Direct pyodbc fetch of every column on the row — bypasses the
    loader entirely. Lets us see what's actually in the DB independent
    of any loader bug."""
    conn = get_general_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT * FROM [{config.GENERAL_DB}].dbo.UdmTablesList "
            f"WHERE SourceName = ? AND SourceObjectName = ?",
            source_name, table_name,
        )
        cols = [d[0] for d in cursor.description]
        rows = cursor.fetchall()
        cursor.close()
    finally:
        conn.close()

    if not rows:
        return None
    if len(rows) > 1:
        logger.warning(
            "Found %d rows for %s.%s — expected 1. Loader will use the first.",
            len(rows), source_name, table_name,
        )
    return dict(zip(cols, rows[0]))


def _format_value(v: object) -> str:
    if v is None:
        return "NULL"
    if isinstance(v, str):
        return f"'{v}'"
    return repr(v)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--source", required=True, help="SourceName, e.g. DNA")
    parser.add_argument("--table", required=True, help="SourceObjectName, e.g. CARDTXN")
    parser.add_argument(
        "--mode", choices=("auto", "small", "large"), default="auto",
        help="Which loader path to invoke. 'auto' picks based on "
             "SourceAggregateColumnName.",
    )
    args = parser.parse_args()

    # --- Step 1: raw DB row, bypass loader ---
    _print_section(f"1. Raw row in {config.GENERAL_DB}.dbo.UdmTablesList")
    raw = _raw_row(args.source, args.table)
    if raw is None:
        print(f"  No row for SourceName='{args.source}' AND SourceObjectName='{args.table}'.")
        print("  Either the row doesn't exist, or your UPDATE targeted a different row.")
        return 1

    width = max(len(c) for c in raw)
    for col, val in raw.items():
        print(f"  {col:<{width}}  {_format_value(val)}")

    # --- Step 2: load through the same path the pipeline uses ---
    _print_section("2. TableConfig via the same loader the pipeline calls")
    loader = TableConfigLoader()

    is_large = raw.get("SourceAggregateColumnName") is not None
    if args.mode == "auto":
        large = is_large
    else:
        large = args.mode == "large"

    if large:
        print(f"  Mode: load_large_tables(source_name={args.source!r}, table_name={args.table!r})")
        configs = loader.load_large_tables(source_name=args.source, table_name=args.table)
    else:
        print(f"  Mode: load_small_tables(source_name={args.source!r}, table_name={args.table!r})")
        configs = loader.load_small_tables(source_name=args.source, table_name=args.table)

    if not configs:
        print("  Loader returned 0 configs.")
        if large and raw.get("StageLoadTool") not in ("Python", "Python-AppendOnly"):
            print(
                f"  StageLoadTool is {raw.get('StageLoadTool')!r} — large-table "
                f"loader requires 'Python' or 'Python-AppendOnly'. That's why "
                f"the row was filtered out.",
            )
        return 1

    tc = configs[0]

    # --- Step 3: the fields downstream code consults ---
    _print_section("3. TableConfig fields (what the orchestrator sees)")
    field_pairs = [
        ("source_object_name", tc.source_object_name),
        ("source_name", tc.source_name),
        ("source_database", tc.source_database),
        ("source_schema_name", tc.source_schema_name),
        ("stage_table_name", tc.stage_table_name),
        ("bronze_table_name", tc.bronze_table_name),
        ("strip_suffix", tc.strip_suffix),
        ("max_rows_per_day", tc.max_rows_per_day),
        ("source_aggregate_column_name", tc.source_aggregate_column_name),
        ("first_load_date", tc.first_load_date),
        ("lookback_days", tc.lookback_days),
        ("stage_load_tool", tc.stage_load_tool),
    ]
    width = max(len(k) for k, _ in field_pairs)
    for key, val in field_pairs:
        print(f"  {key:<{width}}  {_format_value(val)}")

    # --- Step 4: resolved table names ---
    _print_section("4. Resolved Stage / Bronze table names")
    print(f"  stage_full_table_name   {tc.stage_full_table_name}")
    print(f"  bronze_full_table_name  {tc.bronze_full_table_name}")

    # --- Step 5: what the P1-13 guard will compute ---
    if large:
        _print_section("5. P1-13 daily-extraction guard preview")
        if tc.max_rows_per_day:
            print(f"  max_rows_per_day_override   {tc.max_rows_per_day:,}")
            print(f"  growth check at baseline=N  max(5*N, {tc.max_rows_per_day:,})")
            print(
                f"  → for baseline=529 (CARDTXN-style), threshold = "
                f"max(2645, {tc.max_rows_per_day:,}) = {max(2645, tc.max_rows_per_day):,}"
            )
        else:
            print("  max_rows_per_day_override   None  (using default 5x multiplier)")
            print("  growth check at baseline=N  5 * N")
            print("  → for baseline=529 (CARDTXN-style), threshold = 2645")
            print()
            print("  IF you expected an override here, the value is not")
            print("  flowing through. Check raw row in section 1: is")
            print("  MaxRowsPerDay actually set on this row?")

    # --- Step 6: cross-check ---
    _print_section("6. Cross-check: raw row vs TableConfig")
    mismatches = []
    if _bool_norm(raw.get("StripSuffix")) != tc.strip_suffix:
        mismatches.append(
            f"StripSuffix in DB = {raw.get('StripSuffix')!r} but "
            f"tc.strip_suffix = {tc.strip_suffix}"
        )
    db_max = raw.get("MaxRowsPerDay")
    db_max_int = int(db_max) if db_max is not None else None
    if db_max_int != tc.max_rows_per_day:
        mismatches.append(
            f"MaxRowsPerDay in DB = {db_max!r} but "
            f"tc.max_rows_per_day = {tc.max_rows_per_day!r}"
        )
    if mismatches:
        print("  MISMATCHES — loader is dropping values that exist in the DB:")
        for m in mismatches:
            print(f"    - {m}")
        print()
        print("  This is a loader bug. Open an issue with this output attached.")
        return 2

    print("  All loader-relevant fields match the DB row.")
    return 0


def _bool_norm(v: object) -> bool:
    if v is None:
        return False
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    text = str(v).strip().lower()
    return text in {"1", "true", "t", "yes", "y"}


if __name__ == "__main__":
    sys.exit(main())
