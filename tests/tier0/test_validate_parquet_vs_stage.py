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
        # Within 1% tolerance → CLEAN
        (1000, 1000, "CLEAN"),
        (1000, 1010, "CLEAN"),
        (1000, 990, "CLEAN"),
        # 1% < drift ≤ 5% → DRIFT
        (1000, 1020, "DRIFT"),
        (1000, 1050, "DRIFT"),
        (1000, 950, "DRIFT"),
        # Drift > 5% → MAJOR_DRIFT
        (1000, 1100, "MAJOR_DRIFT"),
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


def test_check_table_parity_missing_registry_returns_fatal():
    """No ParquetSnapshotRegistry row for (source, table) → VERDICT_FATAL."""

    mod = _import_tool()
    cursor = MagicMock()
    # First fetchone (parquet count) → None (no registry row)
    cursor.fetchone.return_value = None

    result = mod.check_table_parity(cursor, "DNA", "ACCT")
    assert result["verdict"] == "FATAL"
    assert "No ParquetSnapshotRegistry" in result["error"]


def test_check_table_parity_returns_clean_on_match():
    """Registry says 1000 rows + Bronze active count 1000 → CLEAN."""

    mod = _import_tool()
    cursor = MagicMock()
    # 1st fetchone (parquet count): (1000,); 2nd (bronze count): (1000,)
    cursor.fetchone.side_effect = [(1000,), (1000,)]

    result = mod.check_table_parity(cursor, "DNA", "ACCT")
    assert result["verdict"] == "CLEAN"
    assert result["parquet_count"] == 1000
    assert result["bronze_count"] == 1000


def test_check_table_parity_returns_major_drift():
    """Registry says 1000 rows + Bronze 500 → 50% drift = MAJOR_DRIFT."""

    mod = _import_tool()
    cursor = MagicMock()
    cursor.fetchone.side_effect = [(1000,), (500,)]
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
    1. Returns both_tables as the result of _query_both_mode_tables
    2. Returns parquet_count + bronze_count for each table's parity probe
    """

    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor

    fetchall_results = []
    fetchone_results = []

    if both_tables is not None:
        # All-tables mode: first fetchall returns the table list
        fetchall_results.append([(s, t) for s, t in both_tables])
        # Then 2 fetchone calls per table (parquet count + bronze count)
        for _ in both_tables:
            fetchone_results.append((parquet_count,))
            fetchone_results.append((bronze_count,))
    else:
        # Single-table mode: 2 fetchone calls
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
