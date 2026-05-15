"""Tier 0 build-time smoke test for tools/diagnose_stage_bronze_gap.py.

Per D67 — runs at build time + every commit. Runtime ceiling < 5 s.
All external dependencies (Stage / Bronze cursors, Polars, TableConfigLoader,
PipelineEventLog) are injected via the test-injection surface. No live DB
required.

6-assertion descriptive-name scaffold (B-266 / D77 — descriptive names map
to the verify_tier0_drift semantic-keyword detector for drift reporting).

The bug class diagnosed: ``_cdc_is_current=1`` in
``UDM_Stage.{schema}.{table}_cdc`` AND no ``UdmActiveFlag=1`` row in
``UDM_Bronze.{schema}.{table}_scd2_python`` (CLAUDE.md DIAG-1 + SCD2-P1-c/e +
SCD2-R4 invariants).

D-numbers: D67 (Tier 0 discipline), D74 (exit codes 0/1/2), D75 (arg naming),
D76 (audit-row CLI_DIAGNOSE_STAGE_BRONZE_GAP).
B-numbers: B214 (sys.modules pre-registration), B228 (utils.errors canonical
single source), B-266 (descriptive test-name semantic-keyword match).
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Project root on sys.path
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_TOOL_PATH = _PROJECT_ROOT / "tools" / "diagnose_stage_bronze_gap.py"
_TOOL_MODULE_KEY = "tools.diagnose_stage_bronze_gap"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EXPECTED_EVENT_TYPE = "CLI_DIAGNOSE_STAGE_BRONZE_GAP"
EXIT_SUCCESS = 0
EXIT_OPERATIONAL = 1
EXIT_FATAL = 2

_ACTOR = "test-tier0-smoke"
_SOURCE = "DNA"
_TABLE = "ACCT"
_PK_COL = "AcctNumber"


# ---------------------------------------------------------------------------
# Mock factory
# ---------------------------------------------------------------------------


def _make_table_config(pk_columns: list[str], *, strip_suffix: bool = False) -> Any:
    """Build a MagicMock that quacks like a TableConfig with PK columns."""
    cfg = MagicMock()
    cfg.source_name = _SOURCE
    cfg.source_object_name = _TABLE
    cfg.stage_table_name = None
    cfg.bronze_table_name = None
    cfg.strip_suffix = strip_suffix
    cfg.pk_columns = pk_columns
    cfg._resolved_stage_schema = _SOURCE
    cfg._resolved_bronze_schema = _SOURCE
    return cfg


def _make_table_config_loader(
    pk_columns: list[str], *, strip_suffix: bool = False, no_configs: bool = False
):
    """Return a callable that returns a TableConfigLoader factory."""
    cfg = _make_table_config(pk_columns, strip_suffix=strip_suffix)

    class _Loader:
        def load_small_tables(self, **kwargs):
            if no_configs:
                return []
            return [cfg]

        def load_large_tables(self, **kwargs):
            return []

    def _factory():
        return _Loader()

    return _factory


def _make_cursor_factory(
    *,
    stage_rows: list[tuple] | None = None,
    bronze_active_rows: list[tuple] | None = None,
    bronze_pk_lookup: dict | None = None,
    audit_id: int = 12345,
):
    """Cursor factory whose result depends on the SQL.

    Routes queries by inspecting the SQL string:
      - "_cdc_is_current" -> stage_rows
      - "UdmActiveFlag] = 1" -> bronze_active_rows
      - Specific PK lookup (per-PK characterization) -> bronze_pk_lookup
      - INSERT INTO PipelineEventLog -> audit row INSERT
    """
    stage_rows = stage_rows or []
    bronze_active_rows = bronze_active_rows or []
    bronze_pk_lookup = bronze_pk_lookup or {}

    executed_sql: list[str] = []
    executed_params: list[Any] = []

    def _factory():
        conn = MagicMock()
        conn.autocommit = False

        def _make_cursor():
            cur = MagicMock()
            cur.description = None
            cur._last_query = None

            def _execute(sql, *args):
                executed_sql.append(str(sql))
                if args:
                    executed_params.append(args)
                cur._last_query = str(sql)
                # Route by content
                if "PipelineEventLog" in sql:
                    cur.description = [("AuditEventId",)]
                elif "_cdc_is_current" in sql:
                    cur.description = [
                        (col, ) for col in ["pk_col_placeholder"]
                    ]
                elif "UdmActiveFlag] = 1" in sql or "[UdmActiveFlag] = 1" in sql:
                    cur.description = [("pk_col_placeholder",)]
                else:
                    # Per-PK Bronze characterization
                    cur.description = [
                        ("_scd2_key",),
                        ("UdmActiveFlag",),
                        ("UdmScd2Operation",),
                        ("UdmEffectiveDateTime",),
                        ("UdmEndDateTime",),
                        ("UdmSourceEndDate",),
                    ]
                return None

            def _fetchall():
                last = cur._last_query or ""
                if "_cdc_is_current" in last:
                    return stage_rows
                if "UdmActiveFlag] = 1" in last or "[UdmActiveFlag] = 1" in last:
                    return bronze_active_rows
                # Per-PK characterization — pull params off executed_params
                if executed_params:
                    pk_params = executed_params[-1]
                    pk_key = tuple(pk_params)
                    return bronze_pk_lookup.get(pk_key, [])
                return []

            def _fetchone():
                last = cur._last_query or ""
                if "PipelineEventLog" in last:
                    return (audit_id,)
                rows = _fetchall()
                return rows[0] if rows else None

            cur.execute.side_effect = _execute
            cur.fetchall.side_effect = _fetchall
            cur.fetchone.side_effect = _fetchone
            return cur

        conn.cursor.side_effect = _make_cursor
        return conn

    _factory._executed_sql = executed_sql
    _factory._executed_params = executed_params
    return _factory


def _load_tool_module() -> Any:
    """Load tool with all sibling-module imports mocked or live (Polars live)."""
    if _TOOL_MODULE_KEY in sys.modules:
        del sys.modules[_TOOL_MODULE_KEY]

    spec = importlib.util.spec_from_file_location(_TOOL_MODULE_KEY, _TOOL_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_TOOL_MODULE_KEY] = mod
    spec.loader.exec_module(mod)
    return mod


# ===========================================================================
# Assertion 1: Module imports
# ===========================================================================


def test_module_imports():
    """(1) tools/diagnose_stage_bronze_gap.py imports without error.

    Per D67 Tier 0 assertion 1. Verifies no missing dependencies, no syntax
    errors, no import-time DB calls. Module must expose top-level main +
    cli_main + EVENT_TYPE + exit constants + theory constants.
    """
    mod = _load_tool_module()
    assert mod is not None
    assert hasattr(mod, "main"), "Module must expose main()"
    assert hasattr(mod, "cli_main"), "Module must expose cli_main()"
    assert hasattr(mod, "EVENT_TYPE"), "Module must expose EVENT_TYPE"
    assert mod.EVENT_TYPE == EXPECTED_EVENT_TYPE, (
        f"EVENT_TYPE must be {EXPECTED_EVENT_TYPE!r}; got {mod.EVENT_TYPE!r}."
    )
    assert hasattr(mod, "EXIT_SUCCESS")
    assert hasattr(mod, "EXIT_OPERATIONAL")
    assert hasattr(mod, "EXIT_FATAL")
    assert mod.EXIT_SUCCESS == EXIT_SUCCESS
    assert mod.EXIT_OPERATIONAL == EXIT_OPERATIONAL
    assert mod.EXIT_FATAL == EXIT_FATAL
    # Theory constants
    assert hasattr(mod, "THEORY_T1_IN_FLIGHT_ORPHAN")
    assert hasattr(mod, "THEORY_T2_DELETED_FROM_SOURCE")
    assert hasattr(mod, "THEORY_T3_NEVER_INSERTED")
    assert hasattr(mod, "THEORY_T4_ALL_CLOSED")
    assert hasattr(mod, "THEORY_T5_RESURRECTED_AS_INACTIVE")
    assert hasattr(mod, "THEORY_UNKNOWN")


# ===========================================================================
# Assertion 2: --help exits 0 with non-empty stdout
# ===========================================================================


def test_help_exits_zero_with_nonempty_stdout():
    """(2) --help exits 0 and prints non-empty help text.

    argparse contract: --help raises SystemExit(0) after printing.
    """
    mod = _load_tool_module()
    parser = mod._build_arg_parser()
    help_text = parser.format_help()
    assert help_text, "--help must produce non-empty text"
    assert "source" in help_text.lower()
    assert "table" in help_text.lower()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["--help"])
    assert exc_info.value.code == 0


# ===========================================================================
# Assertion 3: Invocation with mock empty gap exits zero
# ===========================================================================


def test_invocation_with_mock_empty_gap_exits_zero():
    """(3) Mock cursor returns matching Stage + Bronze PK sets → exit 0 healthy.

    Equal sets = no gap; tool reports HEALTHY and exit 0.
    """
    mod = _load_tool_module()
    loader = _make_table_config_loader([_PK_COL])

    # Both sides have the same single PK row → empty gap
    cursor_factory = _make_cursor_factory(
        stage_rows=[("PK001",)],
        bronze_active_rows=[("PK001",)],
    )

    result = mod.main(
        source=_SOURCE,
        table=_TABLE,
        limit=10,
        actor=_ACTOR,
        no_audit_event=True,  # skip audit write in Tier 0
        cursor_factory=cursor_factory,
        table_config_loader=loader,
    )
    assert result["exit_code"] == EXIT_SUCCESS, (
        f"Empty gap must exit {EXIT_SUCCESS}; got {result['exit_code']}: "
        f"{result.get('error_message')}"
    )
    assert result["gap_count"] == 0
    assert result["stage_current_count"] == 1
    assert result["bronze_active_count"] == 1


# ===========================================================================
# Assertion 4: Invocation with mock gap exits one
# ===========================================================================


def test_invocation_with_mock_gap_exits_one():
    """(4) Mock cursor returns Stage with extra PK → exit 1 (gap found).

    Stage has PK001+PK002; Bronze only has PK001. Gap = {PK002}; tool
    characterizes the missing PK via per-PK Bronze query (no rows → T3
    NEVER_INSERTED) and exits 1.
    """
    mod = _load_tool_module()
    loader = _make_table_config_loader([_PK_COL])
    cursor_factory = _make_cursor_factory(
        stage_rows=[("PK001",), ("PK002",)],
        bronze_active_rows=[("PK001",)],
        bronze_pk_lookup={("PK002",): []},  # T3 NEVER_INSERTED
    )
    result = mod.main(
        source=_SOURCE,
        table=_TABLE,
        limit=10,
        actor=_ACTOR,
        no_audit_event=True,
        cursor_factory=cursor_factory,
        table_config_loader=loader,
    )
    assert result["exit_code"] == EXIT_OPERATIONAL, (
        f"Gap found must exit {EXIT_OPERATIONAL}; got {result['exit_code']}: "
        f"{result.get('error_message')}"
    )
    assert result["gap_count"] == 1
    assert len(result["diagnoses"]) == 1
    assert result["diagnoses"][0]["theory"] == mod.THEORY_T3_NEVER_INSERTED


# ===========================================================================
# Assertion 5: Missing required args exits two
# ===========================================================================


def test_missing_required_args_exits_two():
    """(5) Missing --source or --table → argparse error → exit 2.

    argparse's required=True triggers SystemExit(2) when a required flag
    is omitted.
    """
    mod = _load_tool_module()
    parser = mod._build_arg_parser()
    # Missing both
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args([])
    assert exc_info.value.code == 2
    # Missing --source
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["--table", "ACCT"])
    assert exc_info.value.code == 2
    # Missing --table
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["--source", "DNA"])
    assert exc_info.value.code == 2


# ===========================================================================
# Assertion 6: Unresolved PK columns exits two
# ===========================================================================


def test_unresolved_pk_columns_exits_two():
    """(6) Mocked table_config_loader returns empty configs OR empty PK → exit 2.

    Two fatal cases per CLAUDE.md SCD2-P1-d + column-sync contract:
      (a) No row in UdmTablesList for (source, table)
      (b) Row exists but UdmTablesColumnsList has no IsPrimaryKey=1 rows
    """
    mod = _load_tool_module()
    # Case (a) — no configs returned
    loader_no_configs = _make_table_config_loader([], no_configs=True)
    cursor_factory = _make_cursor_factory()
    result = mod.main(
        source=_SOURCE,
        table=_TABLE,
        limit=10,
        actor=_ACTOR,
        no_audit_event=True,
        cursor_factory=cursor_factory,
        table_config_loader=loader_no_configs,
    )
    assert result["exit_code"] == EXIT_FATAL, (
        f"No-config-row case must exit {EXIT_FATAL}; got {result['exit_code']}"
    )
    # Case (b) — config row exists but PK list empty
    loader_no_pk = _make_table_config_loader([])
    result2 = mod.main(
        source=_SOURCE,
        table=_TABLE,
        limit=10,
        actor=_ACTOR,
        no_audit_event=True,
        cursor_factory=cursor_factory,
        table_config_loader=loader_no_pk,
    )
    assert result2["exit_code"] == EXIT_FATAL, (
        f"No-PK-columns case must exit {EXIT_FATAL}; got {result2['exit_code']}"
    )
