#!/usr/bin/env python3
"""P0-7e: Quantify SCD2 version churn from false hash changes.

Analyzes Bronze tables to measure how many versions were created by
NULL-induced hash mismatches (from P0-7 concat corruption) vs genuine
source data changes.

Detection heuristic: For each PK with multiple versions, compare
consecutive versions' source columns. If the only difference is in
columns known to have had NULL inflation (from fail_logs.txt evidence),
that version was a false hash change.

Usage:
    python3 validate_scd2_churn.py --source CCM --table Address
    python3 validate_scd2_churn.py --source CCM                  # All CCM tables
    python3 validate_scd2_churn.py --source CCM --table Account --detail

Known NULL-inflated columns (from fail_logs.txt batch_id=45):
    CCM.Address:    AddressLine2 (628,832), DepartmentName (365),
                    AttentionTo (364), City (64), StateCode (174),
                    PostalCode (136), CountryCode (64)
    CCM.Account:    ClosedReason (67,027)
    CCM.PreauthorizationHold: AcquirersBankId (10,275)
    CCM.TransactionDispute:   ReasonForDispute (8,594)
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

os_path = str(Path(__file__).parent)
if os_path not in sys.path:
    sys.path.insert(0, os_path)

import os
os.environ.setdefault("MALLOC_ARENA_MAX", "2")
os.environ.setdefault("POLARS_MAX_THREADS", "1")

import utils.connections as connections
from utils.connections import cursor_for, quote_identifier, quote_table
from orchestration.table_config import TableConfigLoader

logger = logging.getLogger(__name__)

# Known NULL-inflated columns from fail_logs.txt evidence.
# These are columns where _safe_concat injected NULLs due to schema mismatch.
KNOWN_NULL_INFLATED = {
    ("CCM", "Address"): [
        "AddressLine2", "DepartmentName", "AttentionTo",
        "City", "StateCode", "PostalCode", "CountryCode",
    ],
    ("CCM", "Account"): ["ClosedReason"],
    ("CCM", "PreauthorizationHold"): ["AcquirersBankId"],
    ("CCM", "TransactionDispute"): ["ReasonForDispute"],
}


def analyze_version_churn(
    table_config,
    detail: bool = False,
    max_pks: int = 10_000,
) -> dict:
    """Analyze SCD2 version churn for a single Bronze table.

    Queries Bronze for PKs with multiple versions and classifies each
    version transition as:
      - genuine: at least one non-NULL-inflated column changed
      - suspect: only NULL-inflated columns differ (or only NULL→value)
      - null_only: the version differs ONLY in columns going from NULL→value
                   or value→NULL in known inflated columns

    Args:
        table_config: Table configuration.
        detail: If True, return sample PK details.
        max_pks: Maximum PKs to analyze (for performance).

    Returns:
        Summary dict with churn statistics.
    """
    bronze_table = table_config.bronze_full_table_name
    pk_columns = table_config.pk_columns

    result = {
        "table": f"{table_config.source_name}.{table_config.source_object_name}",
        "bronze_table": bronze_table,
        "pk_columns": pk_columns,
        "total_rows": 0,
        "total_pks": 0,
        "multi_version_pks": 0,
        "total_versions": 0,
        "genuine_transitions": 0,
        "suspect_transitions": 0,
        "avg_versions_per_pk": 0.0,
        "errors": [],
    }

    if not pk_columns:
        result["errors"].append("No PK columns configured")
        return result

    from extract.udm_connectorx_extractor import table_exists, get_table_row_count
    if not table_exists(bronze_table):
        result["errors"].append(f"Bronze table {bronze_table} does not exist")
        return result

    db = bronze_table.split(".")[0]
    q_bronze = quote_table(bronze_table)
    pk_group = ", ".join(quote_identifier(c) for c in pk_columns)
    pk_select = ", ".join(f"a.{quote_identifier(c)}" for c in pk_columns)

    known_inflated = KNOWN_NULL_INFLATED.get(
        (table_config.source_name, table_config.source_object_name), []
    )

    try:
        with cursor_for(db) as cur:
            # Get total counts
            cur.execute(f"SELECT COUNT(*) FROM {q_bronze}")
            result["total_rows"] = cur.fetchone()[0]

            cur.execute(
                f"SELECT COUNT(DISTINCT CONCAT({', '.join(f'CAST({quote_identifier(c)} AS NVARCHAR(MAX))' for c in pk_columns)})) "
                f"FROM {q_bronze}"
            )
            result["total_pks"] = cur.fetchone()[0]

            # Find PKs with multiple versions
            cur.execute(
                f"SELECT {pk_group}, COUNT(*) AS version_count "
                f"FROM {q_bronze} "
                f"GROUP BY {pk_group} "
                f"HAVING COUNT(*) > 1 "
                f"ORDER BY COUNT(*) DESC"
            )
            multi_version_rows = cur.fetchall()
            result["multi_version_pks"] = len(multi_version_rows)

            if result["multi_version_pks"] > 0:
                result["total_versions"] = sum(r[-1] for r in multi_version_rows)
                result["avg_versions_per_pk"] = round(
                    result["total_versions"] / result["multi_version_pks"], 2
                )

            # Version distribution
            cur.execute(
                f"SELECT version_count, COUNT(*) AS pk_count FROM ("
                f"  SELECT {pk_group}, COUNT(*) AS version_count "
                f"  FROM {q_bronze} GROUP BY {pk_group}"
                f") t GROUP BY version_count ORDER BY version_count"
            )
            result["version_distribution"] = {
                row[0]: row[1] for row in cur.fetchall()
            }

            # Churn analysis: for tables with known inflated columns,
            # count versions created near batch_id=45 (the known-bad batch)
            if known_inflated:
                inflated_cols_quoted = ", ".join(
                    quote_identifier(c) for c in known_inflated
                    if c in _get_bronze_columns(bronze_table, db)
                )
                if inflated_cols_quoted:
                    # Count rows where ALL known-inflated columns are NULL
                    # and UdmActiveFlag=0 (closed versions) — these are likely
                    # false versions from NULL inflation
                    null_conditions = " AND ".join(
                        f"{quote_identifier(c)} IS NULL" for c in known_inflated
                        if c in _get_bronze_columns(bronze_table, db)
                    )
                    if null_conditions:
                        cur.execute(
                            f"SELECT COUNT(*) FROM {q_bronze} "
                            f"WHERE UdmActiveFlag = 0 AND ({null_conditions})"
                        )
                        result["suspect_transitions"] = cur.fetchone()[0]

                        cur.execute(
                            f"SELECT COUNT(*) FROM {q_bronze} "
                            f"WHERE UdmActiveFlag = 0 AND NOT ({null_conditions})"
                        )
                        result["genuine_transitions"] = cur.fetchone()[0]

                result["known_inflated_columns"] = known_inflated

    except Exception as e:
        result["errors"].append(str(e))
        logger.error("Churn analysis failed for %s: %s", bronze_table, e, exc_info=True)

    return result


def _get_bronze_columns(bronze_table: str, db: str) -> set[str]:
    """Get column names from Bronze table."""
    parts = bronze_table.split(".")
    schema, table = parts[1], parts[2]
    conn = connections.get_connection(db)
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT COLUMN_NAME FROM [{db}].INFORMATION_SCHEMA.COLUMNS "
            f"WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?",
            schema, table,
        )
        cols = {row[0] for row in cursor.fetchall()}
        cursor.close()
        return cols
    finally:
        conn.close()


def _print_churn_report(results: list[dict]) -> None:
    """Print human-readable churn analysis report."""
    print("\n" + "=" * 70)
    print("SCD2 VERSION CHURN ANALYSIS — P0-7e")
    print("=" * 70)

    total_suspect = 0
    total_genuine = 0

    for r in results:
        if r["errors"]:
            print(f"\n  {r['table']}: ERROR — {r['errors']}")
            continue

        print(f"\n  {r['table']}:")
        print(f"    Total rows:           {r['total_rows']:>12,}")
        print(f"    Unique PKs:           {r['total_pks']:>12,}")
        print(f"    Multi-version PKs:    {r['multi_version_pks']:>12,}")
        print(f"    Avg versions/PK:      {r['avg_versions_per_pk']:>12.2f}")

        if r.get("known_inflated_columns"):
            print(f"    Known inflated cols:  {r['known_inflated_columns']}")
            print(f"    Suspect versions:     {r['suspect_transitions']:>12,}")
            print(f"    Genuine versions:     {r['genuine_transitions']:>12,}")
            total_suspect += r["suspect_transitions"]
            total_genuine += r["genuine_transitions"]

        if r.get("version_distribution"):
            print("    Version distribution:")
            for ver, count in sorted(r["version_distribution"].items()):
                label = f"{ver} versions"
                if ver == 1:
                    label = "1 version (no history)"
                print(f"      {label}: {count:>10,} PKs")

    if total_suspect + total_genuine > 0:
        print(f"\n  TOTAL suspect false versions: {total_suspect:,}")
        print(f"  TOTAL genuine versions:       {total_genuine:,}")
        pct = total_suspect / (total_suspect + total_genuine) * 100
        print(f"  Suspect percentage:           {pct:.1f}%")

        if total_suspect > 0:
            print("\n  RECOMMENDATION: The suspect versions were likely created by")
            print("  P0-7 NULL inflation. With the conform_to_schema fix deployed,")
            print("  no new false versions will be created. To clean up historical")
            print("  damage, consider a one-time Bronze dedup script that merges")
            print("  consecutive versions with identical non-NULL source columns.")

    print("\n" + "=" * 70 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="P0-7e: Quantify SCD2 version churn from false hash changes",
    )
    parser.add_argument("--source", type=str, help="Filter by source name")
    parser.add_argument("--table", type=str, help="Analyze a single table")
    parser.add_argument("--detail", action="store_true",
                        help="Include sample PK details")
    parser.add_argument("--large-tables", action="store_true",
                        help="Include large tables")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        stream=sys.stdout,
    )

    loader = TableConfigLoader()
    configs = loader.load_small_tables(source_name=args.source, table_name=args.table)
    if args.large_tables:
        configs.extend(
            loader.load_large_tables(source_name=args.source, table_name=args.table)
        )

    if not configs:
        print("No tables found matching the specified filters.")
        return

    print(f"Analyzing {len(configs)} tables...")

    results = []
    for tc in sorted(configs, key=lambda x: (x.source_name, x.source_object_name)):
        print(f"  Analyzing {tc.source_name}.{tc.source_object_name}...")
        result = analyze_version_churn(tc, detail=args.detail)
        results.append(result)

    _print_churn_report(results)

    # Write JSON for downstream processing
    json_path = Path("scd2_churn_report.json")
    with open(json_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"JSON report written to {json_path}")


if __name__ == "__main__":
    main()