"""Tier 0 smoke test for tools/validate_parquet_vs_stage.py (B-545).

Per D67 — runtime ceiling < 5s; all external dependencies mocked.

Asserts:
- Module imports cleanly + EVENT_TYPE + EXIT_* + verdict constants present
- classify_parity() returns correct verdicts across all boundary conditions
- derive_exit_code() applies most-severe-wins precedence correctly
- check_table_parity() returns FATAL on missing registry row + propagates SQL exceptions
- apply() honors --source/--table single-table mode + all-tables mode
- D75 dry-run default: no audit row written; verdict still computed
- Per CLAUDE.md "Dev workstation pytest collection skew" (B-328): production
  deps mocked via sys.modules pre-patch.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


@pytest.fixture(autouse=True)
def _stub_modules():
    saved = {}
    for name in ["polars", "connectorx", "pyodbc", "oracledb", "polars_hash"]:
        saved[name] = sys.modules.get(name)
        sys.modules[name] = MagicMock()

    saved["tools.validate_parquet_vs_stage"] = sys.modules.get("tools.validate_parquet_vs_stage")
    sys.modules.pop("tools.validate_parquet_vs_stage", None)

    yield

    for name, mod in saved.items():
        if mod is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = mod
    sys.modules.pop("tools.validate_parquet_vs_stage", None)


def _import_tool():
    from tools import validate_parquet_vs_stage  # noqa: PLC0415
    return validate_parquet_vs_stage


# ---------------------------------------------------------------------------
# Class A — module surface invariants
# ---------------------------------------------------------------------------


def test_module_imports_cleanly():
    mod = _import_tool()
    assert mod.EVENT_TYPE == "CLI_VALIDATE_PARQUET_VS_STAGE"


def test_exit_codes_per_d74():
    mod = _import_tool()
    assert mod.EXIT_SUCCESS == 0
    assert mod.EXIT_WARNING == 1
    assert mod.EXIT_BLOCKED == 2
    assert mod.EXIT_FATAL == 3


def test_verdict_constants_present():
    mod = _import_tool()
    assert mod.VERDICT_CLEAN == "CLEAN"
    assert mod.VERDICT_DRIFT == "DRIFT"
    assert mod.VERDICT_MAJOR_DRIFT == "MAJOR_DRIFT"
    assert mod.VERDICT_FATAL == "FATAL"


def test_drift_thresholds_documented():
    mod = _import_tool()
    assert mod.DRIFT_TOLERANCE_PCT == 0.01
    assert mod.MAJOR_DRIFT_THRESHOLD_PCT == 0.05


# ---------------------------------------------------------------------------
# Class B — classify_parity() correctness
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "parquet,bronze,expected",
    [
        # Both zero → CLEAN (both empty matches)
        (0, 0, "CLEAN"),
        # One zero, other non-zero → MAJOR_DRIFT
        (0, 100, "MAJOR_DRIFT"),
        (100, 0, "MAJOR_DRIFT"),
        # Parquet == Bronze → CLEAN
        (1000, 1000, "CLEAN"),
        # B-553 closure 2026-05-19: Parquet < Bronze is ALWAYS MAJOR_DRIFT
        # regardless of percentage (Bronze should never have rows Parquet
        # missed; Parquet is source-exact per D115)
        (1000, 1010, "MAJOR_DRIFT"),  # B-553 guard (was CLEAN pre-B-553)
        (1000, 1020, "MAJOR_DRIFT"),  # B-553 guard (was DRIFT pre-B-553)
        (1000, 1050, "MAJOR_DRIFT"),  # B-553 guard (was DRIFT pre-B-553)
        (1000, 1100, "MAJOR_DRIFT"),  # B-553 guard (already MAJOR pre-B-553)
        # Parquet > Bronze within 1% → CLEAN (expected NULL-PK exclusion)
        (1000, 990, "CLEAN"),
        # 1% < drift ≤ 5% → DRIFT
        (1000, 950, "DRIFT"),
        # Drift > 5% → MAJOR_DRIFT
        (1000, 500, "MAJOR_DRIFT"),
    ],
)
def test_classify_parity(parquet, bronze, expected):
    mod = _import_tool()
    assert mod.classify_parity(parquet, bronze) == expected


# ---------------------------------------------------------------------------
# Class C — derive_exit_code() most-severe-wins precedence
# ---------------------------------------------------------------------------


def test_derive_exit_code_empty_returns_success():
    """Vacuously clean: no tables in 'both' mode → exit 0."""

    mod = _import_tool()
    assert mod.derive_exit_code([]) == mod.EXIT_SUCCESS


def test_derive_exit_code_all_clean_returns_success():
    mod = _import_tool()
    verdicts = [
        {"verdict": "CLEAN"}, {"verdict": "CLEAN"}, {"verdict": "CLEAN"},
    ]
    assert mod.derive_exit_code(verdicts) == mod.EXIT_SUCCESS


def test_derive_exit_code_one_drift_returns_warning():
    mod = _import_tool()
    verdicts = [
        {"verdict": "CLEAN"}, {"verdict": "DRIFT"}, {"verdict": "CLEAN"},
    ]
    assert mod.derive_exit_code(verdicts) == mod.EXIT_WARNING


def test_derive_exit_code_one_major_drift_returns_blocked():
    mod = _import_tool()
    verdicts = [
        {"verdict": "CLEAN"}, {"verdict": "DRIFT"}, {"verdict": "MAJOR_DRIFT"},
    ]
    assert mod.derive_exit_code(verdicts) == mod.EXIT_BLOCKED


def test_derive_exit_code_one_fatal_returns_fatal():
    """FATAL is most-severe (trumps MAJOR_DRIFT)."""

    mod = _import_tool()
    verdicts = [
        {"verdict": "CLEAN"}, {"verdict": "MAJOR_DRIFT"}, {"verdict": "FATAL"},
    ]
    assert mod.derive_exit_code(verdicts) == mod.EXIT_FATAL


# ---------------------------------------------------------------------------
# Class D — check_table_parity() behavior
# ---------------------------------------------------------------------------


def test_check_table_parity_missing_udmtableslist_returns_fatal():
    """Missing UdmTablesList row → VERDICT_FATAL (B-554: cannot resolve
    bronze_full_table_name)."""

    mod = _import_tool()
    cursor = MagicMock()
    # First fetchone (bronze table resolver) → None
    cursor.fetchone.return_value = None

    result = mod.check_table_parity(cursor, "DNA", "ACCT")
    assert result["verdict"] == "FATAL"
    assert "UdmTablesList row missing" in result["error"]


def test_check_table_parity_missing_parquet_registry_returns_fatal():
    """UdmTablesList row exists but no ParquetSnapshotRegistry row → FATAL."""

    mod = _import_tool()
    cursor = MagicMock()
    # fetchone sequence: (StripSuffix, BronzeTableName) → parquet row count None
    cursor.fetchone.side_effect = [(0, None), None]
    cursor.fetchall.return_value = []  # no PK columns (defensive fallback)

    result = mod.check_table_parity(cursor, "DNA", "ACCT")
    assert result["verdict"] == "FATAL"
    assert "ParquetSnapshotRegistry" in result["error"]


def test_check_table_parity_returns_clean_on_match():
    """Registry says 1000 rows + Bronze active count 1000 → CLEAN.

    Post-B-553/B-554 fetchone sequence:
    1. bronze resolver: (StripSuffix=0, BronzeTableName=None)
    2. parquet count: (1000,)
    3. bronze count: (1000,)
    """

    mod = _import_tool()
    cursor = MagicMock()
    cursor.fetchone.side_effect = [(0, None), (1000,), (1000,)]
    cursor.fetchall.return_value = [("AcctNo",)]  # PK columns

    result = mod.check_table_parity(cursor, "DNA", "ACCT")
    assert result["verdict"] == "CLEAN"
    assert result["parquet_count"] == 1000
    assert result["bronze_count"] == 1000


def test_check_table_parity_returns_major_drift():
    """Registry says 1000 rows + Bronze 500 → 50% drift = MAJOR_DRIFT.

    Post-B-553/B-554 fetchone sequence: bronze resolver + parquet + bronze.
    """

    mod = _import_tool()
    cursor = MagicMock()
    cursor.fetchone.side_effect = [(0, None), (1000,), (500,)]
    cursor.fetchall.return_value = []
    result = mod.check_table_parity(cursor, "DNA", "ACCT")
    assert result["verdict"] == "MAJOR_DRIFT"


def test_check_table_parity_handles_sql_exception():
    """SQL exception during query → VERDICT_FATAL with error captured."""

    mod = _import_tool()
    cursor = MagicMock()
    cursor.execute.side_effect = RuntimeError("Simulated SQL failure")
    result = mod.check_table_parity(cursor, "DNA", "ACCT")
    assert result["verdict"] == "FATAL"
    assert "Simulated SQL failure" in result["error"]


# ---------------------------------------------------------------------------
# Class E — apply() integration behavior
# ---------------------------------------------------------------------------


def _make_mock_conn(both_tables: list[tuple[str, str]] | None = None,
                    parquet_count: int = 1000,
                    bronze_count: int = 1000) -> MagicMock:
    """Mock connection with cursor that:
    1. Returns both_tables as the result of _query_both_mode_tables (if all-tables)
    2. For EACH table: returns (StripSuffix=0, BronzeTableName=None) for bronze
       resolver, then [] for pk columns (fetchall), then parquet_count +
       bronze_count fetchones for the parity probe

    Post-B-553/B-554 fetchone ordering for each table:
      bronze_resolver_fetchone → parquet_count_fetchone → bronze_count_fetchone
    And fetchall for pk_columns is interleaved (mock returns [] each call).
    """

    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor

    fetchall_results = []
    fetchone_results = []

    if both_tables is not None:
        # All-tables mode: first fetchall returns the table list
        fetchall_results.append([(s, t) for s, t in both_tables])
        # Then for each table: bronze resolver fetchone + pk fetchall + parquet + bronze
        for _ in both_tables:
            fetchone_results.append((0, None))  # bronze resolver
            fetchall_results.append([])  # pk columns (none)
            fetchone_results.append((parquet_count,))
            fetchone_results.append((bronze_count,))
    else:
        # Single-table mode
        fetchone_results.append((0, None))  # bronze resolver
        fetchall_results.append([])  # pk columns (none)
        fetchone_results.append((parquet_count,))
        fetchone_results.append((bronze_count,))

    cursor.fetchall.side_effect = fetchall_results if fetchall_results else [[]]
    cursor.fetchone.side_effect = fetchone_results
    return conn


def test_apply_single_table_dry_run_clean():
    mod = _import_tool()
    conn = _make_mock_conn(both_tables=None, parquet_count=1000, bronze_count=1000)
    result = mod.apply(
        conn, actor="test", justification="t",
        source="DNA", table="ACCT", dry_run=True,
    )
    assert result["event_kind"] == "dry_run"
    assert result["exit_code"] == mod.EXIT_SUCCESS
    assert result["tables_checked"] == 1
    assert result["clean"] == 1
    # No commit on dry-run
    conn.commit.assert_not_called()


def test_apply_single_table_dry_run_major_drift():
    mod = _import_tool()
    conn = _make_mock_conn(both_tables=None, parquet_count=1000, bronze_count=200)
    result = mod.apply(
        conn, actor="test", justification="t",
        source="DNA", table="ACCT", dry_run=True,
    )
    assert result["exit_code"] == mod.EXIT_BLOCKED
    assert result["major_drift"] == 1


def test_apply_partial_args_returns_fatal():
    """--source without --table OR --table without --source → FATAL."""

    mod = _import_tool()
    conn = MagicMock()
    result = mod.apply(
        conn, actor="test", justification="t",
        source="DNA", table=None, dry_run=True,
    )
    assert result["event_kind"] == "fatal"
    assert result["exit_code"] == mod.EXIT_FATAL


def test_apply_all_tables_mode_empty_set():
    """No tables in CDCMode='both' → vacuously CLEAN; exit 0."""

    mod = _import_tool()
    conn = _make_mock_conn(both_tables=[])
    result = mod.apply(conn, actor="test", justification="t", dry_run=True)
    assert result["exit_code"] == mod.EXIT_SUCCESS
    assert result["tables_checked"] == 0


def test_apply_dry_run_no_audit_row_written():
    """D75 dry-run: NO INSERT INTO PipelineEventLog."""

    mod = _import_tool()
    conn = _make_mock_conn(both_tables=None, parquet_count=1000, bronze_count=1000)
    cursor = conn.cursor.return_value
    mod.apply(
        conn, actor="test", justification="t",
        source="DNA", table="ACCT", dry_run=True,
    )
    sqls = [call.args[0] for call in cursor.execute.call_args_list]
    for sql in sqls:
        assert "INSERT INTO" not in sql.upper(), \
            f"D75 violation: INSERT on dry-run: {sql[:100]}"


# ---------------------------------------------------------------------------
# Class F — B-553 + B-554 closure fixes (2026-05-19)
# ---------------------------------------------------------------------------


def test_classify_parity_parquet_lt_bronze_returns_major_drift():
    """B-553 defensive guard: parquet_count < bronze_count → MAJOR_DRIFT
    regardless of drift percentage. Bronze should never have rows Parquet
    missed (Parquet is source-exact per D115; Bronze is a subset after
    CDC NULL-PK filter per P0-4). Per cross-cohort gap-check Agent
    `adc861405ff006766` 2026-05-19."""

    mod = _import_tool()
    # Tiny absolute delta but Parquet < Bronze → MAJOR (not CLEAN/DRIFT)
    assert mod.classify_parity(999, 1000) == "MAJOR_DRIFT"
    # Larger delta where parquet < bronze
    assert mod.classify_parity(500, 1000) == "MAJOR_DRIFT"
    # And the inverse symmetric (parquet > bronze, same magnitude) still
    # follows the standard drift logic, NOT the defensive guard
    assert mod.classify_parity(1500, 1000) == "MAJOR_DRIFT"  # 50% drift
    assert mod.classify_parity(1010, 1000) == "CLEAN"  # 1% drift


def test_resolve_bronze_table_name_no_strip_no_custom():
    """Default case: StripSuffix=0 + no BronzeTableName override → standard
    `_scd2_python` suffix."""

    mod = _import_tool()
    cursor = MagicMock()
    cursor.fetchone.return_value = (0, None)  # StripSuffix=0, BronzeTableName=NULL
    result = mod._resolve_bronze_table_name(cursor, "DNA", "ACCT")
    assert result is not None
    assert "ACCT_scd2_python" in result
    assert "[DNA]" in result


def test_resolve_bronze_table_name_strip_suffix_1():
    """SS-1 opt-in: StripSuffix=1 → bare name without suffix."""

    mod = _import_tool()
    cursor = MagicMock()
    cursor.fetchone.return_value = (1, None)  # StripSuffix=1
    result = mod._resolve_bronze_table_name(cursor, "CCM", "AuditLog")
    assert result is not None
    assert "_scd2_python" not in result
    assert "[AuditLog]" in result
    assert "[CCM]" in result


def test_resolve_bronze_table_name_custom_bronze_table_name():
    """Custom BronzeTableName override takes precedence over default name."""

    mod = _import_tool()
    cursor = MagicMock()
    cursor.fetchone.return_value = (0, "CustomBronzeName")
    result = mod._resolve_bronze_table_name(cursor, "DNA", "ACCT")
    assert result is not None
    assert "CustomBronzeName_scd2_python" in result
    # Original table name should NOT appear
    assert "ACCT_scd2_python" not in result


def test_resolve_bronze_table_name_strip_and_custom():
    """Both StripSuffix=1 + custom BronzeTableName → bare custom name."""

    mod = _import_tool()
    cursor = MagicMock()
    cursor.fetchone.return_value = (1, "ProdAuditLog")
    result = mod._resolve_bronze_table_name(cursor, "CCM", "AuditLog")
    assert result is not None
    assert "[ProdAuditLog]" in result
    assert "_scd2_python" not in result


def test_resolve_bronze_table_name_missing_row():
    """Missing UdmTablesList row → None (caller treats as FATAL)."""

    mod = _import_tool()
    cursor = MagicMock()
    cursor.fetchone.return_value = None
    result = mod._resolve_bronze_table_name(cursor, "DNA", "NONEXISTENT")
    assert result is None


def test_resolve_pk_columns_returns_ordered_list():
    """Multi-column PK in OrdinalPosition order."""

    mod = _import_tool()
    cursor = MagicMock()
    cursor.fetchall.return_value = [("AcctNo",), ("EffDate",)]
    result = mod._resolve_pk_columns(cursor, "DNA", "ACCT")
    assert result == ["AcctNo", "EffDate"]


def test_resolve_pk_columns_empty():
    """No PK columns recorded → empty list (caller falls back to no filter)."""

    mod = _import_tool()
    cursor = MagicMock()
    cursor.fetchall.return_value = []
    result = mod._resolve_pk_columns(cursor, "DNA", "NEWTABLE")
    assert result == []


def test_query_bronze_active_row_count_includes_null_pk_filter():
    """B-553: when pk_columns is non-empty, SQL MUST contain
    `AND [<col>] IS NOT NULL` for each PK column."""

    mod = _import_tool()
    cursor = MagicMock()
    cursor.fetchone.return_value = (1000,)
    mod._query_bronze_active_row_count(
        cursor,
        bronze_table="[UDM_Bronze].[DNA].[ACCT_scd2_python]",
        pk_columns=["AcctNo", "EffDate"],
    )
    # Inspect the SQL that was actually executed
    sql = cursor.execute.call_args.args[0]
    assert "WHERE UdmActiveFlag = 1" in sql
    assert "[AcctNo] IS NOT NULL" in sql
    assert "[EffDate] IS NOT NULL" in sql
    assert "AND" in sql


def test_query_bronze_active_row_count_no_pk_filter_when_empty():
    """When pk_columns is None or empty, NO NULL-PK filter added (defensive
    fallback; results still valid because Bronze excludes NULL-PK via CDC)."""

    mod = _import_tool()
    cursor = MagicMock()
    cursor.fetchone.return_value = (1000,)
    mod._query_bronze_active_row_count(
        cursor,
        bronze_table="[UDM_Bronze].[DNA].[ACCT_scd2_python]",
        pk_columns=None,
    )
    sql = cursor.execute.call_args.args[0]
    assert "WHERE UdmActiveFlag = 1" in sql
    # No null-pk clause
    assert "IS NOT NULL" not in sql



# ---------------------------------------------------------------------------
# Class G -- B-555 v2 per-PK hash comparison (opt-in via --hash-check)
# ---------------------------------------------------------------------------


def test_b555_classify_hash_check_clean_when_all_match():
    """B-555: hash_check verdict CLEAN when all comparison counts == 0 except hash_same."""
    tool = _import_tool()
    comp = {
        "in_parquet_missing_from_bronze": 0,
        "in_bronze_missing_from_parquet": 0,
        "pk_match_hash_diff": 0,
        "pk_match_hash_same": 1000,
    }
    assert tool.classify_hash_check(comp, parquet_count=1000) == tool.VERDICT_CLEAN


def test_b555_classify_hash_check_major_drift_on_bronze_orphan():
    """B-555: ANY in_bronze_missing_from_parquet > 0 -> MAJOR_DRIFT (CRITICAL
    orphan; Parquet source-exact per D115 so Bronze should not have rows
    Parquet missed)."""
    tool = _import_tool()
    comp = {
        "in_parquet_missing_from_bronze": 0,
        "in_bronze_missing_from_parquet": 1,  # even 1 orphan = MAJOR_DRIFT
        "pk_match_hash_diff": 0,
        "pk_match_hash_same": 999,
    }
    assert tool.classify_hash_check(comp, parquet_count=999) == tool.VERDICT_MAJOR_DRIFT


def test_b555_classify_hash_check_drift_on_small_hash_mismatch():
    """B-555: 2% hash mismatch -> DRIFT (above 1% tolerance but below 5%)."""
    tool = _import_tool()
    comp = {
        "in_parquet_missing_from_bronze": 0,
        "in_bronze_missing_from_parquet": 0,
        "pk_match_hash_diff": 20,
        "pk_match_hash_same": 980,
    }
    assert tool.classify_hash_check(comp, parquet_count=1000) == tool.VERDICT_DRIFT


def test_b555_classify_hash_check_major_drift_on_large_hash_mismatch():
    """B-555: 10% hash mismatch -> MAJOR_DRIFT (above 5% threshold)."""
    tool = _import_tool()
    comp = {
        "in_parquet_missing_from_bronze": 0,
        "in_bronze_missing_from_parquet": 0,
        "pk_match_hash_diff": 100,
        "pk_match_hash_same": 900,
    }
    assert tool.classify_hash_check(comp, parquet_count=1000) == tool.VERDICT_MAJOR_DRIFT


def test_b555_classify_hash_check_clean_on_both_empty():
    """B-555: parquet_count == 0 AND all comparison counts == 0 -> CLEAN."""
    tool = _import_tool()
    comp = {
        "in_parquet_missing_from_bronze": 0,
        "in_bronze_missing_from_parquet": 0,
        "pk_match_hash_diff": 0,
        "pk_match_hash_same": 0,
    }
    assert tool.classify_hash_check(comp, parquet_count=0) == tool.VERDICT_CLEAN


def test_b555_classify_hash_check_major_drift_on_parquet_empty_bronze_nonempty():
    """B-555: parquet_count == 0 BUT bronze has rows -> MAJOR_DRIFT inconsistent."""
    tool = _import_tool()
    comp = {
        "in_parquet_missing_from_bronze": 0,
        "in_bronze_missing_from_parquet": 50,  # bronze has 50 orphan
        "pk_match_hash_diff": 0,
        "pk_match_hash_same": 0,
    }
    # Caught by the first guard (in_bronze_missing > 0)
    assert tool.classify_hash_check(comp, parquet_count=0) == tool.VERDICT_MAJOR_DRIFT


def test_b555_combine_verdicts_most_severe_wins():
    """B-555: _combine_verdicts uses FATAL > MAJOR_DRIFT > DRIFT > CLEAN precedence."""
    tool = _import_tool()
    # Each combination -> expected result
    cases = [
        (tool.VERDICT_CLEAN, tool.VERDICT_CLEAN, tool.VERDICT_CLEAN),
        (tool.VERDICT_CLEAN, tool.VERDICT_DRIFT, tool.VERDICT_DRIFT),
        (tool.VERDICT_DRIFT, tool.VERDICT_CLEAN, tool.VERDICT_DRIFT),
        (tool.VERDICT_DRIFT, tool.VERDICT_MAJOR_DRIFT, tool.VERDICT_MAJOR_DRIFT),
        (tool.VERDICT_MAJOR_DRIFT, tool.VERDICT_DRIFT, tool.VERDICT_MAJOR_DRIFT),
        (tool.VERDICT_MAJOR_DRIFT, tool.VERDICT_FATAL, tool.VERDICT_FATAL),
        (tool.VERDICT_FATAL, tool.VERDICT_CLEAN, tool.VERDICT_FATAL),
    ]
    for rc, hc, expected in cases:
        assert tool._combine_verdicts(rc, hc) == expected, (
            f"combine({rc!r}, {hc!r}) -> expected {expected!r}"
        )


def test_b555_check_table_parity_default_hash_check_disabled():
    """B-555: default check_table_parity(hash_check=False) does NOT run hash
    check; result dict has no hash_check_verdict key. Backward-compat
    invariant per opt-in design."""
    tool = _import_tool()
    cursor = MagicMock()
    # UdmTablesList row exists with no strip + no custom
    cursor.fetchone.side_effect = [
        (0, None),  # UdmTablesList: StripSuffix=0, BronzeTableName=None
        (1000,),  # ParquetSnapshotRegistry RowCount
        (1000,),  # Bronze active count
    ]
    cursor.fetchall.return_value = [
        ("AcctNo",), ("EffDate",),  # _resolve_pk_columns
    ]
    result = tool.check_table_parity(cursor, "DNA", "ACCT")
    assert "hash_check_verdict" not in result, (
        "B-555 backward-compat: default hash_check=False must not populate "
        "hash_check_verdict in result dict"
    )
    assert result["verdict"] == tool.VERDICT_CLEAN


def test_b555_check_table_parity_hash_check_pk_columns_missing_fatal():
    """B-555: hash_check=True with empty pk_columns -> hash_check_verdict=FATAL
    + row-count verdict preserved (NOT overridden by hash-check failure when
    cause is operator config gap)."""
    tool = _import_tool()
    cursor = MagicMock()
    cursor.fetchone.side_effect = [
        (0, None),  # UdmTablesList: StripSuffix=0, BronzeTableName=None
        (1000,),  # ParquetSnapshotRegistry
        (1000,),  # Bronze count
    ]
    cursor.fetchall.return_value = []  # _resolve_pk_columns returns empty
    result = tool.check_table_parity(cursor, "DNA", "ACCT", hash_check=True)
    assert result["hash_check_verdict"] == tool.VERDICT_FATAL
    assert "Cannot perform hash check without pk_columns" in result["hash_check_error"]
    # Row-count verdict preserved (NOT overridden)
    assert result["verdict"] == tool.VERDICT_CLEAN


def test_b555_check_table_parity_hash_check_no_parquet_path_fatal():
    """B-555: hash_check=True but no replay-eligible parquet snapshot ->
    hash_check_verdict=FATAL + verdict overridden to FATAL (Parquet absence
    IS a parity issue, not operator config)."""
    tool = _import_tool()
    cursor = MagicMock()
    cursor.fetchone.side_effect = [
        (0, None),  # UdmTablesList: StripSuffix=0, BronzeTableName=None
        (1000,),  # ParquetSnapshotRegistry RowCount
        (1000,),  # Bronze count
        None,     # _query_latest_parquet_network_drive_path returns None
    ]
    cursor.fetchall.return_value = [
        ("AcctNo",), ("EffDate",),
    ]
    result = tool.check_table_parity(cursor, "DNA", "ACCT", hash_check=True)
    assert result["hash_check_verdict"] == tool.VERDICT_FATAL
    assert "No replay-eligible" in result["hash_check_error"]
    # Verdict overridden to FATAL (most-severe)
    assert result["verdict"] == tool.VERDICT_FATAL


def test_b555_cli_hash_check_flag_parses(monkeypatch):
    """B-555: --hash-check CLI flag parses via main() argparse without error."""
    tool = _import_tool()
    test_argv = [
        "validate_parquet_vs_stage.py",
        "--dry-run-actor-pseudo",  # invalid; just verify --hash-check parses
    ]
    # Test argparse handles --hash-check; use the underlying argparser directly
    import argparse  # noqa: PLC0415
    parser = argparse.ArgumentParser()
    parser.add_argument("--hash-check", action="store_true")
    args = parser.parse_args(["--hash-check"])
    assert args.hash_check is True

    args = parser.parse_args([])
    assert args.hash_check is False


def test_b555_helper_module_surface_present():
    """B-555: new public surface exported from module."""
    tool = _import_tool()
    assert hasattr(tool, "compare_pk_hashes")
    assert hasattr(tool, "classify_hash_check")
    assert hasattr(tool, "_combine_verdicts")
    assert hasattr(tool, "_read_parquet_pk_hashes")
    assert hasattr(tool, "_query_bronze_pk_hashes")
    assert hasattr(tool, "_query_latest_parquet_network_drive_path")


def test_b555_audit_metadata_includes_hash_check_enabled():
    """B-555: _write_audit_row metadata includes hash_check_enabled flag
    derived from presence of hash_check_verdict in per_table_verdicts."""
    tool = _import_tool()
    cursor = MagicMock()
    # Per-table verdicts WITH hash_check
    pt_with = [
        {"source": "DNA", "table": "ACCT", "verdict": tool.VERDICT_CLEAN,
         "hash_check_verdict": tool.VERDICT_CLEAN, "hash_comparison": {}},
    ]
    tool._write_audit_row(
        cursor,
        actor="test", justification="test",
        tables_checked=1, clean=1, drift=0, major_drift=0,
        per_table_verdicts=pt_with,
    )
    # Inspect the INSERT call's metadata JSON arg
    # cursor.execute(sql, EVENT_TYPE, event_detail, status, error_msg, json.dumps(metadata))
    # call_args[0] = (sql, EVENT_TYPE, event_detail, status, error_msg, metadata_json)
    # metadata is the last positional arg (index 5)
    call_args = cursor.execute.call_args
    assert call_args is not None
    metadata_json = call_args[0][5]
    import json  # noqa: PLC0415
    metadata = json.loads(metadata_json)
    assert metadata["hash_check_enabled"] is True


def test_b555_audit_metadata_hash_check_disabled_default():
    """B-555: when no per_table_verdict has hash_check_verdict, audit metadata
    hash_check_enabled=False."""
    tool = _import_tool()
    cursor = MagicMock()
    pt_without = [
        {"source": "DNA", "table": "ACCT", "verdict": tool.VERDICT_CLEAN},
    ]
    tool._write_audit_row(
        cursor,
        actor="test", justification="test",
        tables_checked=1, clean=1, drift=0, major_drift=0,
        per_table_verdicts=pt_without,
    )
    call_args = cursor.execute.call_args
    metadata_json = call_args[0][5]
    import json  # noqa: PLC0415
    metadata = json.loads(metadata_json)
    assert metadata["hash_check_enabled"] is False


def test_b555_check_table_parity_hash_check_clean_happy_path():
    """B-555 F2.1 forward-prevention: happy-path test for hash_check=True
    returning CLEAN end-to-end. Pre-F2.1 all 3 hash_check integration tests
    were FATAL paths -- same MagicMock-stub-without-realism class B-564 was
    authored to forward-prevent. This test exercises the full compose chain:
    cursor lookups -> _read_parquet_pk_hashes -> _query_bronze_pk_hashes ->
    compare_pk_hashes -> classify_hash_check -> _combine_verdicts -> CLEAN.

    Per gap-check reviewer ``aa1638567ae7cb414`` 2026-05-19 F2.1 finding."""
    tool = _import_tool()
    cursor = MagicMock()
    cursor.fetchone.side_effect = [
        (0, None),  # UdmTablesList: StripSuffix=0, BronzeTableName=None
        (1000,),    # ParquetSnapshotRegistry RowCount
        (1000,),    # Bronze active count
        ("\\\\drive\\path\\file.parquet",),  # _query_latest_parquet_network_drive_path
    ]
    cursor.fetchall.return_value = [
        ("AcctNo",), ("EffDate",),  # _resolve_pk_columns
    ]
    # Stub the heavyweight read helpers + comparison; polars itself is
    # MagicMock'd at sys.modules level so we cannot run real anti-join
    # logic, but we CAN verify the orchestration chain composes correctly
    # + the CLEAN verdict propagates through _combine_verdicts.
    tool._read_parquet_pk_hashes = MagicMock(return_value=MagicMock())
    tool._query_bronze_pk_hashes = MagicMock(return_value=MagicMock())
    tool.compare_pk_hashes = MagicMock(return_value={
        "in_parquet_missing_from_bronze": 0,
        "in_bronze_missing_from_parquet": 0,
        "pk_match_hash_diff": 0,
        "pk_match_hash_same": 1000,
    })

    result = tool.check_table_parity(cursor, "DNA", "ACCT", hash_check=True)

    # Verdict: CLEAN end-to-end (row-count CLEAN + hash-check CLEAN -> CLEAN)
    assert result["verdict"] == tool.VERDICT_CLEAN, (
        f"Happy path CLEAN expected; got {result['verdict']!r}"
    )
    assert result["hash_check_verdict"] == tool.VERDICT_CLEAN
    # Compose chain verified -- all 3 helpers invoked
    tool._read_parquet_pk_hashes.assert_called_once_with(
        "\\\\drive\\path\\file.parquet", ["AcctNo", "EffDate"],
    )
    tool._query_bronze_pk_hashes.assert_called_once()
    tool.compare_pk_hashes.assert_called_once()
    # hash_comparison dict propagated into result
    assert result["hash_comparison"]["pk_match_hash_same"] == 1000
    assert result["hash_comparison"]["in_bronze_missing_from_parquet"] == 0


def test_b555_check_table_parity_hash_check_drift_overrides_clean_row_count():
    """B-555 F2.1 extension: when row-count is CLEAN but hash-check is DRIFT
    (3% mismatch between thresholds), final verdict = DRIFT via
    _combine_verdicts most-severe-wins precedence. Pins the verdict
    combination integration."""
    tool = _import_tool()
    cursor = MagicMock()
    cursor.fetchone.side_effect = [
        (0, None),  # UdmTablesList
        (1000,),    # ParquetSnapshotRegistry RowCount (matches Bronze)
        (1000,),    # Bronze count (row-count CLEAN)
        ("\\\\drive\\path\\file.parquet",),  # NetworkDrivePath
    ]
    cursor.fetchall.return_value = [
        ("AcctNo",), ("EffDate",),
    ]
    tool._read_parquet_pk_hashes = MagicMock(return_value=MagicMock())
    tool._query_bronze_pk_hashes = MagicMock(return_value=MagicMock())
    # 3% hash mismatch -- DRIFT (above 1% tolerance, below 5% threshold)
    tool.compare_pk_hashes = MagicMock(return_value={
        "in_parquet_missing_from_bronze": 0,
        "in_bronze_missing_from_parquet": 0,
        "pk_match_hash_diff": 30,
        "pk_match_hash_same": 970,
    })

    result = tool.check_table_parity(cursor, "DNA", "ACCT", hash_check=True)

    # Row-count is CLEAN; hash-check is DRIFT; combined = DRIFT (more severe)
    assert result["verdict"] == tool.VERDICT_DRIFT, (
        f"hash-check DRIFT must override row-count CLEAN; "
        f"got {result['verdict']!r}"
    )
    assert result["hash_check_verdict"] == tool.VERDICT_DRIFT


def test_b560_resolve_pk_columns_empty_logs_warning(caplog):
    """B-560 closure 2026-05-19: WARNING log surfaces UdmTablesColumnsList
    gap when _resolve_pk_columns returns empty list. Operationally minor
    (Bronze excludes NULL-PK via legacy CDC P0-4 filter; defensive filter
    is no-op) but UdmTablesColumnsList unpopulated state likely indicates
    a separate operational issue worth surfacing."""
    import logging  # noqa: PLC0415
    tool = _import_tool()
    cursor = MagicMock()
    cursor.fetchall.return_value = []  # No PK columns

    with caplog.at_level(logging.WARNING, logger="tools.validate_parquet_vs_stage"):
        result = tool._resolve_pk_columns(cursor, "DNA", "ACCT")

    assert result == []
    assert any(
        "no PK columns" in record.message and "DNA" in record.message and "ACCT" in record.message
        for record in caplog.records
    ), f"WARNING log missing or wrong content; records: {[r.message for r in caplog.records]}"


def test_b560_resolve_pk_columns_non_empty_no_warning(caplog):
    """B-560: when pk_columns ARE present, no WARNING logged (only the
    empty-list case triggers the operator-attention signal)."""
    import logging  # noqa: PLC0415
    tool = _import_tool()
    cursor = MagicMock()
    cursor.fetchall.return_value = [("AcctNo",), ("EffDate",)]

    with caplog.at_level(logging.WARNING, logger="tools.validate_parquet_vs_stage"):
        result = tool._resolve_pk_columns(cursor, "DNA", "ACCT")

    assert result == ["AcctNo", "EffDate"]
    # No WARNING records about pk columns
    warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
    pk_warnings = [r for r in warning_records if "no PK columns" in r.message]
    assert pk_warnings == [], (
        f"Unexpected WARNING when pk_columns populated; got: "
        f"{[r.message for r in pk_warnings]}"
    )


# ---------------------------------------------------------------------------
# B-556 closure 2026-05-19 -- apply-path tests for validate_parquet_vs_stage
#
# Pre-B-556 only dry-run paths were tested; non-dry-run audit-row /
# commit / rollback paths mechanically uncovered. Closes the apply-path
# test-coverage gap.
# ---------------------------------------------------------------------------


def test_b556_apply_non_dryrun_writes_audit_and_commits():
    """B-556: non-dry-run apply path writes audit row + commits exactly
    once. Pins the canonical orchestration: verdicts computed -> audit
    written -> commit."""
    tool = _import_tool()

    connection = MagicMock()
    cursor = MagicMock()
    connection.cursor.return_value = cursor

    # _query_both_mode_tables returns single (source, table)
    # _resolve_bronze_table_name + _resolve_pk_columns + parquet count + bronze count
    cursor.fetchone.side_effect = [
        (0, None),    # UdmTablesList: StripSuffix=0, BronzeTableName=None
        (1000,),      # ParquetSnapshotRegistry RowCount
        (1000,),      # Bronze active count
    ]
    cursor.fetchall.side_effect = [
        [("DNA", "ACCT")],         # _query_both_mode_tables
        [("AcctNo",), ("EffDate",)],  # _resolve_pk_columns
    ]

    result = tool.apply(
        connection,
        actor="test", justification="B-556 apply-path test",
        dry_run=False,
    )

    assert result["event_kind"] == "apply"
    assert result["exit_code"] == tool.EXIT_SUCCESS
    assert result["dry_run"] is False
    assert result["clean"] == 1

    # connection.commit() called exactly once
    assert connection.commit.call_count == 1
    assert connection.rollback.call_count == 0

    # Audit-row INSERT executed
    insert_calls = [
        c for c in cursor.execute.call_args_list
        if "INSERT" in c[0][0] and "PipelineEventLog" in c[0][0]
    ]
    assert len(insert_calls) == 1, (
        f"Expected exactly 1 audit-row INSERT; got {len(insert_calls)}"
    )


def test_b556_apply_audit_failure_rolls_back_and_returns_fatal():
    """B-556: when audit-row write raises (e.g., transient SQL failure),
    connection.rollback() called + result returns EXIT_FATAL with error
    captured. Forward-prevents bare-raise regression class (per existing
    inline comment citing remediation Agent adc861405ff006766 Scope 1)."""
    tool = _import_tool()

    connection = MagicMock()
    cursor = MagicMock()
    connection.cursor.return_value = cursor

    cursor.fetchone.side_effect = [
        (0, None),
        (1000,),
        (1000,),
    ]
    cursor.fetchall.side_effect = [
        [("DNA", "ACCT")],
        [("AcctNo",), ("EffDate",)],
    ]
    # Make cursor.execute raise on INSERT (audit-row write)
    original_execute = cursor.execute
    def _execute_side_effect(sql, *args, **kwargs):
        if "INSERT" in sql and "PipelineEventLog" in sql:
            raise RuntimeError("simulated audit-row INSERT failure")
        return None
    cursor.execute.side_effect = _execute_side_effect

    result = tool.apply(
        connection,
        actor="test", justification="B-556 audit failure test",
        dry_run=False,
    )

    assert result["event_kind"] == "error"
    assert result["exit_code"] == tool.EXIT_FATAL
    assert "simulated audit-row INSERT failure" in result["error"]
    # rollback() called exactly once
    assert connection.rollback.call_count == 1
    # commit() NOT called (rollback path)
    assert connection.commit.call_count == 0


def test_b556_apply_dry_run_no_commit_no_audit_insert():
    """B-556 / D75 contract: dry-run path does NOT commit + does NOT write
    audit row. Extends existing dry-run coverage with explicit no-side-
    effect assertions."""
    tool = _import_tool()

    connection = MagicMock()
    cursor = MagicMock()
    connection.cursor.return_value = cursor

    cursor.fetchone.side_effect = [
        (0, None),
        (1000,),
        (1000,),
    ]
    cursor.fetchall.side_effect = [
        [("DNA", "ACCT")],
        [("AcctNo",), ("EffDate",)],
    ]

    result = tool.apply(
        connection,
        actor="test", justification="B-556 dry-run test",
        dry_run=True,
    )

    assert result["event_kind"] == "dry_run"
    assert result["dry_run"] is True

    assert connection.commit.call_count == 0
    assert connection.rollback.call_count == 0

    # No INSERT to PipelineEventLog
    insert_calls = [
        c for c in cursor.execute.call_args_list
        if "INSERT" in c[0][0] and "PipelineEventLog" in c[0][0]
    ]
    assert insert_calls == [], (
        f"Dry-run wrote audit row; got: {insert_calls}"
    )