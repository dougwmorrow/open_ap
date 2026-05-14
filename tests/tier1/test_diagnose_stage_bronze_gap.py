"""Tier 1 unit tests for tools/diagnose_stage_bronze_gap.py.

Tests run on every commit. No live DB / network. All external deps mocked.

Test plan (~30-40 tests across 14-18 classes):
  TestModuleSurface        — public exports
  TestArgParser            — argparse coverage
  TestActorDetection       — 3 paths (AUTOMIC / TTY / else)
  TestPKResolution         — TableConfigLoader contract
  TestEmptyGapPath         — no gap → exit 0 + no per-PK queries
  TestGapDetection         — gap → exit 1 + characterization fires
  TestTheoryT1InFlightOrphan
  TestTheoryT2DeletedFromSource
  TestTheoryT3NeverInserted
  TestTheoryT4AllClosed
  TestTheoryT5Resurrected
  TestLimit                — --limit caps per-PK characterization
  TestStripSuffixTableName — strip_suffix=1 → no _cdc suffix; strip_suffix=0 → _cdc
  TestCustomTableNameOverride
  TestAuditRow             — D76 contract; Metadata JSON shape
  TestJsonOutput           — --json-output valid JSON
  TestOutputFile           — --output-file writes to path
  TestB228UtilsErrorsImport — canonical exception classes from utils.errors

D-numbers: D67 (Tier 0 discipline — this is Tier 1 complement), D68 (canonical
exception hierarchy), D70 (Tier 1 unit-test discipline), D74 (exit codes
0/1/2), D75 (arg naming), D76 (audit-row CLI_DIAGNOSE_STAGE_BRONZE_GAP).
B-numbers: B214 (sys.modules pre-registration), B228 (utils.errors single
source).
"""
from __future__ import annotations

import importlib
import importlib.util
import json
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

EXPECTED_EVENT_TYPE = "CLI_DIAGNOSE_STAGE_BRONZE_GAP"
EXIT_SUCCESS = 0
EXIT_OPERATIONAL = 1
EXIT_FATAL = 2

_ACTOR = "test-tier1"
_SOURCE = "DNA"
_TABLE = "ACCT"
_PK_COL = "AcctNumber"


# ---------------------------------------------------------------------------
# Fixtures + helpers
# ---------------------------------------------------------------------------


def _load_tool_module() -> Any:
    if _TOOL_MODULE_KEY in sys.modules:
        del sys.modules[_TOOL_MODULE_KEY]
    spec = importlib.util.spec_from_file_location(_TOOL_MODULE_KEY, _TOOL_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[_TOOL_MODULE_KEY] = mod
    spec.loader.exec_module(mod)
    return mod


def _make_table_config(
    pk_columns: list[str],
    *,
    strip_suffix: bool = False,
    stage_table_name: str | None = None,
    bronze_table_name: str | None = None,
):
    cfg = MagicMock()
    cfg.source_name = _SOURCE
    cfg.source_object_name = _TABLE
    cfg.stage_table_name = stage_table_name
    cfg.bronze_table_name = bronze_table_name
    cfg.strip_suffix = strip_suffix
    cfg.pk_columns = pk_columns
    cfg._resolved_stage_schema = _SOURCE
    cfg._resolved_bronze_schema = _SOURCE
    return cfg


def _make_table_config_loader(
    pk_columns: list[str],
    *,
    strip_suffix: bool = False,
    no_configs: bool = False,
    stage_table_name: str | None = None,
    bronze_table_name: str | None = None,
):
    cfg = _make_table_config(
        pk_columns,
        strip_suffix=strip_suffix,
        stage_table_name=stage_table_name,
        bronze_table_name=bronze_table_name,
    )

    class _Loader:
        def load_small_tables(self, **kwargs):
            return [] if no_configs else [cfg]

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
    audit_id: int | None = 12345,
):
    """Cursor factory whose result depends on the SQL text.

    Records executed SQL and parameters for assertion.
    """
    stage_rows = stage_rows or []
    bronze_active_rows = bronze_active_rows or []
    bronze_pk_lookup = bronze_pk_lookup or {}

    executed: dict = {"sql": [], "params": []}

    def _factory():
        conn = MagicMock()

        def _make_cursor():
            cur = MagicMock()
            cur.description = None
            cur._last_query = None

            def _execute(sql, *args):
                executed["sql"].append(str(sql))
                if args:
                    executed["params"].append(args)
                cur._last_query = str(sql)
                if "PipelineEventLog" in sql:
                    cur.description = [("AuditEventId",)]
                elif "_cdc_is_current" in sql:
                    cur.description = [("col",)]
                elif "[UdmActiveFlag] = 1" in sql or "UdmActiveFlag] = 1" in sql:
                    cur.description = [("col",)]
                else:
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
                if "UdmActiveFlag] = 1" in last:
                    return bronze_active_rows
                if executed["params"]:
                    pk_params = executed["params"][-1]
                    pk_key = tuple(pk_params)
                    return bronze_pk_lookup.get(pk_key, [])
                return []

            def _fetchone():
                last = cur._last_query or ""
                if "PipelineEventLog" in last:
                    if audit_id is None:
                        return None
                    return (audit_id,)
                rows = _fetchall()
                return rows[0] if rows else None

            cur.execute.side_effect = _execute
            cur.fetchall.side_effect = _fetchall
            cur.fetchone.side_effect = _fetchone
            return cur

        conn.cursor.side_effect = _make_cursor
        return conn

    _factory._executed = executed
    return _factory


# ===========================================================================
# TestModuleSurface
# ===========================================================================


class TestModuleSurface:
    def test_module_exposes_main(self):
        mod = _load_tool_module()
        assert callable(mod.main)

    def test_module_exposes_cli_main(self):
        mod = _load_tool_module()
        assert callable(mod.cli_main)

    def test_module_exposes_event_type_constant(self):
        mod = _load_tool_module()
        assert mod.EVENT_TYPE == EXPECTED_EVENT_TYPE

    def test_module_exposes_exit_code_triplet(self):
        mod = _load_tool_module()
        assert mod.EXIT_SUCCESS == 0
        assert mod.EXIT_OPERATIONAL == 1
        assert mod.EXIT_FATAL == 2

    def test_module_exposes_all_six_theory_constants(self):
        mod = _load_tool_module()
        assert mod.THEORY_T1_IN_FLIGHT_ORPHAN == "IN_FLIGHT_ORPHAN"
        assert mod.THEORY_T2_DELETED_FROM_SOURCE == "DELETED_FROM_SOURCE"
        assert mod.THEORY_T3_NEVER_INSERTED == "NEVER_INSERTED"
        assert mod.THEORY_T4_ALL_CLOSED == "ALL_CLOSED"
        assert mod.THEORY_T5_RESURRECTED_AS_INACTIVE == "RESURRECTED_AS_INACTIVE"
        assert mod.THEORY_UNKNOWN == "UNKNOWN"


# ===========================================================================
# TestArgParser
# ===========================================================================


class TestArgParser:
    def test_parser_requires_source(self):
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--table", _TABLE])

    def test_parser_requires_table(self):
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--source", _SOURCE])

    def test_parser_default_limit_is_100(self):
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        args = parser.parse_args(["--source", _SOURCE, "--table", _TABLE])
        assert args.limit == 100

    def test_parser_limit_coerced_to_int(self):
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        args = parser.parse_args(
            ["--source", _SOURCE, "--table", _TABLE, "--limit", "42"]
        )
        assert args.limit == 42 and isinstance(args.limit, int)

    def test_parser_limit_rejects_non_integer(self):
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(
                ["--source", _SOURCE, "--table", _TABLE, "--limit", "abc"]
            )

    def test_parser_json_output_flag(self):
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        args = parser.parse_args(
            ["--source", _SOURCE, "--table", _TABLE, "--json-output"]
        )
        assert args.json_output is True

    def test_parser_include_state_flag(self):
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        args = parser.parse_args(
            ["--source", _SOURCE, "--table", _TABLE, "--include-state"]
        )
        assert args.include_state is True

    def test_parser_output_file_path(self):
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        args = parser.parse_args(
            ["--source", _SOURCE, "--table", _TABLE,
             "--output-file", "/tmp/foo.txt"]
        )
        assert args.output_file == "/tmp/foo.txt"


# ===========================================================================
# TestActorDetection
# ===========================================================================


class TestActorDetection:
    def test_actor_detection_automic_via_env(self, monkeypatch):
        mod = _load_tool_module()
        monkeypatch.setenv("AUTOMIC_RUN_ID", "RUN-12345")
        assert mod._detect_actor() == "automic"

    def test_actor_detection_operator_via_tty(self, monkeypatch):
        mod = _load_tool_module()
        monkeypatch.delenv("AUTOMIC_RUN_ID", raising=False)
        fake_stdin = MagicMock()
        fake_stdin.isatty.return_value = True
        with patch.object(sys, "stdin", fake_stdin):
            assert mod._detect_actor() == "operator"

    def test_actor_detection_pipeline_fallback(self, monkeypatch):
        mod = _load_tool_module()
        monkeypatch.delenv("AUTOMIC_RUN_ID", raising=False)
        fake_stdin = MagicMock()
        fake_stdin.isatty.return_value = False
        with patch.object(sys, "stdin", fake_stdin):
            assert mod._detect_actor() == "pipeline"


# ===========================================================================
# TestPKResolution
# ===========================================================================


class TestPKResolution:
    def test_pk_resolution_returns_columns_from_table_config(self):
        mod = _load_tool_module()
        loader = _make_table_config_loader(["AcctNumber", "AcctType"])
        pk_cols, cfg = mod._resolve_pk_columns_via_loader(
            source_name=_SOURCE,
            table_name=_TABLE,
            table_config_loader=loader,
        )
        assert pk_cols == ["AcctNumber", "AcctType"]
        assert cfg.source_name == _SOURCE

    def test_pk_resolution_empty_configs_raises_fatal(self):
        mod = _load_tool_module()
        loader = _make_table_config_loader([], no_configs=True)
        with pytest.raises(mod.PipelineFatalError):
            mod._resolve_pk_columns_via_loader(
                source_name=_SOURCE,
                table_name=_TABLE,
                table_config_loader=loader,
            )

    def test_pk_resolution_empty_pk_columns_raises_fatal(self):
        mod = _load_tool_module()
        loader = _make_table_config_loader([])
        with pytest.raises(mod.PipelineFatalError):
            mod._resolve_pk_columns_via_loader(
                source_name=_SOURCE,
                table_name=_TABLE,
                table_config_loader=loader,
            )


# ===========================================================================
# TestEmptyGapPath
# ===========================================================================


class TestEmptyGapPath:
    def test_equal_pk_sets_exits_zero_no_diagnoses(self):
        mod = _load_tool_module()
        loader = _make_table_config_loader([_PK_COL])
        cursor_factory = _make_cursor_factory(
            stage_rows=[("PK001",), ("PK002",)],
            bronze_active_rows=[("PK001",), ("PK002",)],
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
        assert result["exit_code"] == EXIT_SUCCESS
        assert result["gap_count"] == 0
        assert result["diagnoses"] == []

    def test_empty_stage_and_empty_bronze_exits_zero(self):
        mod = _load_tool_module()
        loader = _make_table_config_loader([_PK_COL])
        cursor_factory = _make_cursor_factory(
            stage_rows=[],
            bronze_active_rows=[],
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
        assert result["exit_code"] == EXIT_SUCCESS
        assert result["gap_count"] == 0
        assert result["stage_current_count"] == 0
        assert result["bronze_active_count"] == 0


# ===========================================================================
# TestGapDetection
# ===========================================================================


class TestGapDetection:
    def test_stage_has_extra_pk_detects_gap(self):
        mod = _load_tool_module()
        loader = _make_table_config_loader([_PK_COL])
        cursor_factory = _make_cursor_factory(
            stage_rows=[("PK001",), ("PK002",), ("PK003",)],
            bronze_active_rows=[("PK001",)],
            bronze_pk_lookup={
                ("PK002",): [],
                ("PK003",): [],
            },
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
        assert result["exit_code"] == EXIT_OPERATIONAL
        assert result["gap_count"] == 2
        assert len(result["diagnoses"]) == 2

    def test_multi_column_pk_gap_detection(self):
        mod = _load_tool_module()
        loader = _make_table_config_loader(["AcctNumber", "AcctType"])
        cursor_factory = _make_cursor_factory(
            stage_rows=[("PK001", "CK"), ("PK002", "SV")],
            bronze_active_rows=[("PK001", "CK")],
            bronze_pk_lookup={
                ("PK002", "SV"): [],
            },
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
        assert result["exit_code"] == EXIT_OPERATIONAL
        assert result["gap_count"] == 1
        assert result["pk_columns"] == ["AcctNumber", "AcctType"]


# ===========================================================================
# TestTheoryT1InFlightOrphan
# ===========================================================================


class TestTheoryT1InFlightOrphan:
    def test_in_flight_orphan_signature_classifies_t1(self):
        mod = _load_tool_module()
        loader = _make_table_config_loader([_PK_COL])
        # In-flight: Flag=0, Op='U', UdmEndDateTime IS NULL, UdmSourceEndDate IS NULL
        bronze_pk_row = (98765, 0, "U", "2026-05-13 14:32:18", None, None)
        cursor_factory = _make_cursor_factory(
            stage_rows=[("PK002",)],
            bronze_active_rows=[],
            bronze_pk_lookup={("PK002",): [bronze_pk_row]},
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
        assert result["exit_code"] == EXIT_OPERATIONAL
        assert len(result["diagnoses"]) == 1
        diag = result["diagnoses"][0]
        assert diag["theory"] == mod.THEORY_T1_IN_FLIGHT_ORPHAN
        assert "repair_scd2" in diag["recommendation"]

    def test_in_flight_orphan_with_op_R(self):
        mod = _load_tool_module()
        loader = _make_table_config_loader([_PK_COL])
        bronze_pk_row = (1, 0, "R", "2026-05-13 14:32:18", None, None)
        cursor_factory = _make_cursor_factory(
            stage_rows=[("PK002",)],
            bronze_active_rows=[],
            bronze_pk_lookup={("PK002",): [bronze_pk_row]},
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
        assert result["diagnoses"][0]["theory"] == mod.THEORY_T1_IN_FLIGHT_ORPHAN


# ===========================================================================
# TestTheoryT2DeletedFromSource
# ===========================================================================


class TestTheoryT2DeletedFromSource:
    def test_bronze_flag2_only_classifies_t2(self):
        mod = _load_tool_module()
        loader = _make_table_config_loader([_PK_COL])
        # Flag=2 with non-null UdmEndDateTime (delete-close shape)
        bronze_pk_row = (
            123, 2, "D", "2026-05-10 00:00:00", "2026-05-12 00:00:00",
            "2026-05-12 00:00:00",
        )
        cursor_factory = _make_cursor_factory(
            stage_rows=[("PK002",)],
            bronze_active_rows=[],
            bronze_pk_lookup={("PK002",): [bronze_pk_row]},
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
        assert result["diagnoses"][0]["theory"] == mod.THEORY_T2_DELETED_FROM_SOURCE


# ===========================================================================
# TestTheoryT3NeverInserted
# ===========================================================================


class TestTheoryT3NeverInserted:
    def test_no_bronze_rows_classifies_t3(self):
        mod = _load_tool_module()
        loader = _make_table_config_loader([_PK_COL])
        cursor_factory = _make_cursor_factory(
            stage_rows=[("PK002",)],
            bronze_active_rows=[],
            bronze_pk_lookup={("PK002",): []},
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
        diag = result["diagnoses"][0]
        assert diag["theory"] == mod.THEORY_T3_NEVER_INSERTED
        assert "inspect_cdc_pk" in diag["recommendation"]


# ===========================================================================
# TestTheoryT4AllClosed
# ===========================================================================


class TestTheoryT4AllClosed:
    def test_all_flag0_no_inflight_classifies_t4(self):
        mod = _load_tool_module()
        loader = _make_table_config_loader([_PK_COL])
        # Two Flag=0 rows BOTH closed (UdmEndDateTime + UdmSourceEndDate set)
        # — partial activation failure
        row1 = (
            1, 0, "U", "2026-05-10 00:00:00",
            "2026-05-11 00:00:00", "2026-05-10 23:59:59.999",
        )
        row2 = (
            2, 0, "U", "2026-05-11 00:00:00",
            "2026-05-12 00:00:00", "2026-05-11 23:59:59.999",
        )
        cursor_factory = _make_cursor_factory(
            stage_rows=[("PK002",)],
            bronze_active_rows=[],
            bronze_pk_lookup={("PK002",): [row1, row2]},
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
        assert result["diagnoses"][0]["theory"] == mod.THEORY_T4_ALL_CLOSED


# ===========================================================================
# TestTheoryT5Resurrected
# ===========================================================================


class TestTheoryT5Resurrected:
    def test_mixed_flag0_flag2_no_flag1_classifies_t5(self):
        mod = _load_tool_module()
        loader = _make_table_config_loader([_PK_COL])
        # Mix of Flag=0 + Flag=2; no Flag=1
        row_closed = (
            1, 0, "U", "2026-04-01 00:00:00",
            "2026-04-15 00:00:00", "2026-04-14 23:59:59.999",
        )
        row_deleted = (
            2, 2, "D", "2026-04-15 00:00:00",
            "2026-05-01 00:00:00", "2026-05-01 00:00:00",
        )
        cursor_factory = _make_cursor_factory(
            stage_rows=[("PK002",)],
            bronze_active_rows=[],
            bronze_pk_lookup={("PK002",): [row_closed, row_deleted]},
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
        assert result["diagnoses"][0]["theory"] == mod.THEORY_T5_RESURRECTED_AS_INACTIVE


# ===========================================================================
# TestLimit
# ===========================================================================


class TestLimit:
    def test_limit_caps_per_pk_characterization(self):
        mod = _load_tool_module()
        loader = _make_table_config_loader([_PK_COL])
        # 10 stage rows, 1 bronze active → 9 in gap
        stage_rows = [(f"PK{i:04d}",) for i in range(10)]
        cursor_factory = _make_cursor_factory(
            stage_rows=stage_rows,
            bronze_active_rows=[("PK0000",)],
            bronze_pk_lookup={(f"PK{i:04d}",): [] for i in range(1, 10)},
        )
        result = mod.main(
            source=_SOURCE,
            table=_TABLE,
            limit=3,
            actor=_ACTOR,
            no_audit_event=True,
            cursor_factory=cursor_factory,
            table_config_loader=loader,
        )
        assert result["gap_count"] == 9
        # Only 3 per-PK characterizations performed
        assert len(result["diagnoses"]) == 3

    def test_limit_one_only_processes_one(self):
        mod = _load_tool_module()
        loader = _make_table_config_loader([_PK_COL])
        cursor_factory = _make_cursor_factory(
            stage_rows=[("PK001",), ("PK002",)],
            bronze_active_rows=[],
            bronze_pk_lookup={("PK001",): [], ("PK002",): []},
        )
        result = mod.main(
            source=_SOURCE,
            table=_TABLE,
            limit=1,
            actor=_ACTOR,
            no_audit_event=True,
            cursor_factory=cursor_factory,
            table_config_loader=loader,
        )
        assert result["gap_count"] == 2
        assert len(result["diagnoses"]) == 1


# ===========================================================================
# TestStripSuffixTableName
# ===========================================================================


class TestStripSuffixTableName:
    def test_strip_suffix_false_uses_cdc_and_scd2_python_suffix(self):
        mod = _load_tool_module()
        cfg = _make_table_config([_PK_COL], strip_suffix=False)
        assert mod._resolve_stage_table_name(cfg) == "ACCT_cdc"
        assert mod._resolve_bronze_table_name(cfg) == "ACCT_scd2_python"

    def test_strip_suffix_true_uses_bare_table_name(self):
        mod = _load_tool_module()
        cfg = _make_table_config([_PK_COL], strip_suffix=True)
        assert mod._resolve_stage_table_name(cfg) == "ACCT"
        assert mod._resolve_bronze_table_name(cfg) == "ACCT"

    def test_strip_suffix_appears_in_qualified_table_via_main(self):
        """End-to-end: strip_suffix=True should produce SQL against bare name."""
        mod = _load_tool_module()
        loader = _make_table_config_loader([_PK_COL], strip_suffix=True)
        cursor_factory = _make_cursor_factory(
            stage_rows=[("PK001",)],
            bronze_active_rows=[("PK001",)],
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
        # Verify executed SQL targets bare names (no `_cdc` suffix)
        executed_sql = "\n".join(cursor_factory._executed["sql"])
        assert "[UDM_Stage].[DNA].[ACCT]" in executed_sql
        assert "[UDM_Bronze].[DNA].[ACCT]" in executed_sql
        assert "[ACCT_cdc]" not in executed_sql


# ===========================================================================
# TestCustomTableNameOverride
# ===========================================================================


class TestCustomTableNameOverride:
    def test_stage_table_name_override_used(self):
        mod = _load_tool_module()
        cfg = _make_table_config(
            [_PK_COL],
            strip_suffix=False,
            stage_table_name="ACCT_LEGACY",
        )
        assert mod._resolve_stage_table_name(cfg) == "ACCT_LEGACY_cdc"

    def test_bronze_table_name_override_used(self):
        mod = _load_tool_module()
        cfg = _make_table_config(
            [_PK_COL],
            strip_suffix=False,
            bronze_table_name="ACCT_VNEXT",
        )
        assert mod._resolve_bronze_table_name(cfg) == "ACCT_VNEXT_scd2_python"

    def test_override_with_strip_suffix_combination(self):
        mod = _load_tool_module()
        cfg = _make_table_config(
            [_PK_COL],
            strip_suffix=True,
            stage_table_name="ACCT_NEW",
            bronze_table_name="ACCT_NEW",
        )
        assert mod._resolve_stage_table_name(cfg) == "ACCT_NEW"
        assert mod._resolve_bronze_table_name(cfg) == "ACCT_NEW"


# ===========================================================================
# TestAuditRow
# ===========================================================================


class TestAuditRow:
    def test_audit_row_written_when_no_audit_event_false(self):
        mod = _load_tool_module()
        loader = _make_table_config_loader([_PK_COL])
        cursor_factory = _make_cursor_factory(
            stage_rows=[("PK001",)],
            bronze_active_rows=[("PK001",)],
        )
        result = mod.main(
            source=_SOURCE,
            table=_TABLE,
            limit=10,
            actor=_ACTOR,
            no_audit_event=False,
            cursor_factory=cursor_factory,
            table_config_loader=loader,
            audit_cursor_factory=cursor_factory,
        )
        # Audit ID should be set per the mock fetchone (12345)
        assert result["audit_event_id"] == 12345
        # Verify an INSERT INTO PipelineEventLog was executed
        executed_sql = "\n".join(cursor_factory._executed["sql"])
        assert "PipelineEventLog" in executed_sql
        assert EXPECTED_EVENT_TYPE in str(cursor_factory._executed["params"])

    def test_audit_row_skipped_when_no_audit_event_true(self):
        mod = _load_tool_module()
        loader = _make_table_config_loader([_PK_COL])
        cursor_factory = _make_cursor_factory(
            stage_rows=[("PK001",)],
            bronze_active_rows=[("PK001",)],
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
        assert result["audit_event_id"] is None
        # No INSERT INTO PipelineEventLog
        executed_sql = "\n".join(cursor_factory._executed["sql"])
        assert "PipelineEventLog" not in executed_sql

    def test_audit_row_metadata_carries_required_keys(self):
        mod = _load_tool_module()
        loader = _make_table_config_loader([_PK_COL])
        cursor_factory = _make_cursor_factory(
            stage_rows=[("PK001",), ("PK002",)],
            bronze_active_rows=[("PK001",)],
            bronze_pk_lookup={("PK002",): []},
        )
        result = mod.main(
            source=_SOURCE,
            table=_TABLE,
            limit=10,
            actor=_ACTOR,
            no_audit_event=False,
            cursor_factory=cursor_factory,
            table_config_loader=loader,
            audit_cursor_factory=cursor_factory,
        )
        assert result["audit_event_id"] == 12345
        # Inspect Metadata JSON among executed params
        json_params = []
        for params in cursor_factory._executed["params"]:
            for p in params:
                if isinstance(p, str) and p.startswith("{"):
                    try:
                        decoded = json.loads(p)
                        json_params.append(decoded)
                    except (json.JSONDecodeError, ValueError):
                        pass
        assert json_params, "Metadata JSON parameter missing from audit row"
        metadata = json_params[-1]
        for key in (
            "event_kind", "actor", "source_name", "table_name",
            "stage_current_count", "bronze_active_count", "gap_count",
            "theories_breakdown", "exit_code", "started_at",
            "completed_at", "duration_ms",
        ):
            assert key in metadata, f"Required Metadata key {key!r} missing"
        assert metadata["event_kind"] == "diagnose_stage_bronze_gap"
        assert metadata["source_name"] == _SOURCE
        assert metadata["table_name"] == _TABLE
        assert metadata["gap_count"] == 1

    def test_audit_row_event_type_is_canonical(self):
        mod = _load_tool_module()
        loader = _make_table_config_loader([_PK_COL])
        cursor_factory = _make_cursor_factory(
            stage_rows=[],
            bronze_active_rows=[],
        )
        mod.main(
            source=_SOURCE,
            table=_TABLE,
            limit=10,
            actor=_ACTOR,
            no_audit_event=False,
            cursor_factory=cursor_factory,
            table_config_loader=loader,
            audit_cursor_factory=cursor_factory,
        )
        flat_params = []
        for params in cursor_factory._executed["params"]:
            flat_params.extend(params)
        assert EXPECTED_EVENT_TYPE in flat_params, (
            f"Expected {EXPECTED_EVENT_TYPE!r} in INSERT params"
        )


# ===========================================================================
# TestJsonOutput
# ===========================================================================


class TestJsonOutput:
    def test_json_output_renders_valid_json(self, capsys):
        mod = _load_tool_module()
        loader = _make_table_config_loader([_PK_COL])
        cursor_factory = _make_cursor_factory(
            stage_rows=[("PK001",), ("PK002",)],
            bronze_active_rows=[("PK001",)],
            bronze_pk_lookup={("PK002",): []},
        )
        result = mod.main(
            source=_SOURCE,
            table=_TABLE,
            limit=10,
            actor=_ACTOR,
            no_audit_event=True,
            json_output=True,
            cursor_factory=cursor_factory,
            table_config_loader=loader,
        )
        captured = capsys.readouterr()
        # Parse the stdout as JSON
        payload = json.loads(captured.out)
        assert payload["source_name"] == _SOURCE
        assert payload["table_name"] == _TABLE
        assert payload["gap_count"] == 1
        assert payload["pk_columns"] == [_PK_COL]
        assert len(payload["diagnoses"]) == 1
        assert payload["diagnoses"][0]["theory"] == mod.THEORY_T3_NEVER_INSERTED
        assert payload["exit_code"] == EXIT_OPERATIONAL

    def test_json_output_contains_required_top_level_keys(self, capsys):
        mod = _load_tool_module()
        loader = _make_table_config_loader([_PK_COL])
        cursor_factory = _make_cursor_factory(
            stage_rows=[("PK001",)],
            bronze_active_rows=[("PK001",)],
        )
        mod.main(
            source=_SOURCE,
            table=_TABLE,
            limit=10,
            actor=_ACTOR,
            no_audit_event=True,
            json_output=True,
            cursor_factory=cursor_factory,
            table_config_loader=loader,
        )
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        for key in (
            "source_name", "table_name", "pk_columns",
            "stage_current_count", "bronze_active_count", "gap_count",
            "limit", "theories_breakdown", "diagnoses",
            "audit_event_id", "exit_code",
        ):
            assert key in payload, f"JSON top-level key {key!r} missing"


# ===========================================================================
# TestOutputFile
# ===========================================================================


class TestOutputFile:
    def test_output_file_writes_human_summary(self, tmp_path):
        mod = _load_tool_module()
        loader = _make_table_config_loader([_PK_COL])
        cursor_factory = _make_cursor_factory(
            stage_rows=[("PK001",), ("PK002",)],
            bronze_active_rows=[("PK001",)],
            bronze_pk_lookup={("PK002",): []},
        )
        out_path = tmp_path / "gap_report.txt"
        result = mod.main(
            source=_SOURCE,
            table=_TABLE,
            limit=10,
            actor=_ACTOR,
            no_audit_event=True,
            output_file=str(out_path),
            cursor_factory=cursor_factory,
            table_config_loader=loader,
        )
        assert out_path.exists()
        content = out_path.read_text(encoding="utf-8")
        assert "Stage->Bronze Gap Diagnostic" in content
        assert _SOURCE in content
        assert _TABLE in content
        # gap_count line
        assert "GAP: 1 PKs" in content or "GAP: 1," in content

    def test_output_file_writes_json_when_json_flag_set(self, tmp_path):
        mod = _load_tool_module()
        loader = _make_table_config_loader([_PK_COL])
        cursor_factory = _make_cursor_factory(
            stage_rows=[("PK001",)],
            bronze_active_rows=[("PK001",)],
        )
        out_path = tmp_path / "gap_report.json"
        mod.main(
            source=_SOURCE,
            table=_TABLE,
            limit=10,
            actor=_ACTOR,
            no_audit_event=True,
            json_output=True,
            output_file=str(out_path),
            cursor_factory=cursor_factory,
            table_config_loader=loader,
        )
        assert out_path.exists()
        # File contents must be valid JSON
        payload = json.loads(out_path.read_text(encoding="utf-8"))
        assert payload["source_name"] == _SOURCE


# ===========================================================================
# TestRecommendationFormat
# ===========================================================================


class TestRecommendationFormat:
    def test_recommendation_includes_source_and_table_placeholders_filled(self, capsys):
        mod = _load_tool_module()
        loader = _make_table_config_loader([_PK_COL])
        cursor_factory = _make_cursor_factory(
            stage_rows=[("PK002",)],
            bronze_active_rows=[],
            bronze_pk_lookup={("PK002",): []},
        )
        mod.main(
            source=_SOURCE,
            table=_TABLE,
            limit=10,
            actor=_ACTOR,
            no_audit_event=True,
            cursor_factory=cursor_factory,
            table_config_loader=loader,
        )
        captured = capsys.readouterr()
        # Recommendation should have replaced {source} and {table} with literals
        assert "--source DNA" in captured.out
        assert "--table ACCT" in captured.out
        # And NOT leave the literal placeholders
        assert "{source}" not in captured.out
        assert "{table}" not in captured.out


# ===========================================================================
# TestExitCodeSemantics
# ===========================================================================


class TestExitCodeSemantics:
    def test_healthy_returns_zero(self):
        mod = _load_tool_module()
        loader = _make_table_config_loader([_PK_COL])
        cursor_factory = _make_cursor_factory(
            stage_rows=[("PK001",)],
            bronze_active_rows=[("PK001",)],
        )
        result = mod.main(
            source=_SOURCE, table=_TABLE,
            limit=10, actor=_ACTOR, no_audit_event=True,
            cursor_factory=cursor_factory, table_config_loader=loader,
        )
        assert result["exit_code"] == 0

    def test_gap_returns_one(self):
        mod = _load_tool_module()
        loader = _make_table_config_loader([_PK_COL])
        cursor_factory = _make_cursor_factory(
            stage_rows=[("PK001",)],
            bronze_active_rows=[],
            bronze_pk_lookup={("PK001",): []},
        )
        result = mod.main(
            source=_SOURCE, table=_TABLE,
            limit=10, actor=_ACTOR, no_audit_event=True,
            cursor_factory=cursor_factory, table_config_loader=loader,
        )
        assert result["exit_code"] == 1

    def test_config_error_returns_two(self):
        mod = _load_tool_module()
        loader_no_configs = _make_table_config_loader([], no_configs=True)
        cursor_factory = _make_cursor_factory()
        result = mod.main(
            source=_SOURCE, table=_TABLE,
            limit=10, actor=_ACTOR, no_audit_event=True,
            cursor_factory=cursor_factory,
            table_config_loader=loader_no_configs,
        )
        assert result["exit_code"] == 2

    def test_invalid_limit_returns_two(self):
        mod = _load_tool_module()
        loader = _make_table_config_loader([_PK_COL])
        cursor_factory = _make_cursor_factory()
        result = mod.main(
            source=_SOURCE, table=_TABLE,
            limit=0, actor=_ACTOR, no_audit_event=True,
            cursor_factory=cursor_factory, table_config_loader=loader,
        )
        assert result["exit_code"] == 2

    def test_empty_source_returns_two(self):
        mod = _load_tool_module()
        loader = _make_table_config_loader([_PK_COL])
        cursor_factory = _make_cursor_factory()
        result = mod.main(
            source="  ", table=_TABLE,
            limit=10, actor=_ACTOR, no_audit_event=True,
            cursor_factory=cursor_factory, table_config_loader=loader,
        )
        assert result["exit_code"] == 2


# ===========================================================================
# TestCliMainDispatch
# ===========================================================================


class TestCliMainDispatch:
    def test_cli_main_help_exits_zero(self):
        mod = _load_tool_module()
        # cli_main(['--help']) should return 0 (argparse handles --help)
        code = mod.cli_main(["--help"])
        assert code == 0

    def test_cli_main_missing_args_returns_two(self):
        mod = _load_tool_module()
        code = mod.cli_main([])
        assert code == 2


# ===========================================================================
# TestB228UtilsErrorsImport
# ===========================================================================


class TestB228UtilsErrorsImport:
    def test_pipeline_fatal_error_resolvable(self):
        """Per B228: tools import from utils.errors, not local definitions."""
        mod = _load_tool_module()
        assert hasattr(mod, "PipelineFatalError")
        # Should be the canonical class from utils.errors
        from utils.errors import PipelineFatalError as canonical
        assert mod.PipelineFatalError is canonical

    def test_pipeline_retryable_error_resolvable(self):
        mod = _load_tool_module()
        assert hasattr(mod, "PipelineRetryableError")
        from utils.errors import PipelineRetryableError as canonical
        assert mod.PipelineRetryableError is canonical

    def test_no_local_exception_classes_defined_in_tool(self):
        """The tool MUST NOT define exception classes locally per B228."""
        mod = _load_tool_module()
        # Walk module namespace for exception subclasses defined in THIS module
        local_exception_classes = []
        for name, obj in vars(mod).items():
            if (
                isinstance(obj, type)
                and issubclass(obj, Exception)
                and obj.__module__ == _TOOL_MODULE_KEY
            ):
                local_exception_classes.append(name)
        assert not local_exception_classes, (
            f"B228 violation: tool defines local exception classes: "
            f"{local_exception_classes}. Lift them to utils.errors."
        )


# ===========================================================================
# TestPolarsAntiJoinUsage
# ===========================================================================


class TestPolarsAntiJoinUsage:
    """Per CLAUDE.md B-2: set-diff happens client-side via Polars; no
    server-side LEFT JOIN ... NULL pattern in the executed SQL."""

    def test_executed_sql_has_no_server_side_left_join_not_null(self):
        mod = _load_tool_module()
        loader = _make_table_config_loader([_PK_COL])
        cursor_factory = _make_cursor_factory(
            stage_rows=[("PK001",), ("PK002",)],
            bronze_active_rows=[("PK001",)],
            bronze_pk_lookup={("PK002",): []},
        )
        mod.main(
            source=_SOURCE,
            table=_TABLE,
            limit=10,
            actor=_ACTOR,
            no_audit_event=True,
            cursor_factory=cursor_factory,
            table_config_loader=loader,
        )
        executed_sql = "\n".join(cursor_factory._executed["sql"]).upper()
        # B-2 guard: no NOT EXISTS or LEFT JOIN ... NULL set-diff in SQL.
        assert "LEFT JOIN" not in executed_sql, (
            "B-2 violation: server-side LEFT JOIN ... NULL set-diff "
            "can lock-escalate; use Polars anti-join client-side."
        )
        assert "NOT EXISTS" not in executed_sql, (
            "B-2 violation: server-side NOT EXISTS set-diff; use Polars."
        )


# ===========================================================================
# TestStdoutEmission
# ===========================================================================


class TestStdoutEmission:
    def test_healthy_path_emits_healthy_message(self, capsys):
        mod = _load_tool_module()
        loader = _make_table_config_loader([_PK_COL])
        cursor_factory = _make_cursor_factory(
            stage_rows=[("PK001",)],
            bronze_active_rows=[("PK001",)],
        )
        mod.main(
            source=_SOURCE, table=_TABLE,
            limit=10, actor=_ACTOR, no_audit_event=True,
            cursor_factory=cursor_factory, table_config_loader=loader,
        )
        captured = capsys.readouterr()
        assert "HEALTHY" in captured.out

    def test_gap_path_emits_theory_label(self, capsys):
        mod = _load_tool_module()
        loader = _make_table_config_loader([_PK_COL])
        cursor_factory = _make_cursor_factory(
            stage_rows=[("PK002",)],
            bronze_active_rows=[],
            bronze_pk_lookup={("PK002",): []},
        )
        mod.main(
            source=_SOURCE, table=_TABLE,
            limit=10, actor=_ACTOR, no_audit_event=True,
            cursor_factory=cursor_factory, table_config_loader=loader,
        )
        captured = capsys.readouterr()
        assert mod.THEORY_T3_NEVER_INSERTED in captured.out

    def test_quiet_suppresses_summary(self, capsys):
        mod = _load_tool_module()
        loader = _make_table_config_loader([_PK_COL])
        cursor_factory = _make_cursor_factory(
            stage_rows=[("PK001",)],
            bronze_active_rows=[("PK001",)],
        )
        mod.main(
            source=_SOURCE, table=_TABLE,
            limit=10, actor=_ACTOR, no_audit_event=True,
            quiet=True,
            cursor_factory=cursor_factory, table_config_loader=loader,
        )
        captured = capsys.readouterr()
        # Quiet should suppress the human summary block entirely
        assert "Stage->Bronze Gap Diagnostic" not in captured.out


# ===========================================================================
# TestIdempotency
# ===========================================================================


class TestIdempotency:
    """Two invocations against the same Stage/Bronze state must produce
    identical verdicts (per D15 + read-only contract — the tool does NOT
    mutate Stage/Bronze)."""

    def test_two_invocations_same_state_produce_same_gap_count(self):
        mod = _load_tool_module()
        loader = _make_table_config_loader([_PK_COL])
        cursor_factory1 = _make_cursor_factory(
            stage_rows=[("PK001",), ("PK002",)],
            bronze_active_rows=[("PK001",)],
            bronze_pk_lookup={("PK002",): []},
        )
        cursor_factory2 = _make_cursor_factory(
            stage_rows=[("PK001",), ("PK002",)],
            bronze_active_rows=[("PK001",)],
            bronze_pk_lookup={("PK002",): []},
        )
        r1 = mod.main(
            source=_SOURCE, table=_TABLE,
            limit=10, actor=_ACTOR, no_audit_event=True,
            cursor_factory=cursor_factory1, table_config_loader=loader,
        )
        r2 = mod.main(
            source=_SOURCE, table=_TABLE,
            limit=10, actor=_ACTOR, no_audit_event=True,
            cursor_factory=cursor_factory2, table_config_loader=loader,
        )
        assert r1["gap_count"] == r2["gap_count"]
        assert r1["exit_code"] == r2["exit_code"]
        assert (
            r1["diagnoses"][0]["theory"] == r2["diagnoses"][0]["theory"]
        )


# ===========================================================================
# TestReadOnlyContract
# ===========================================================================


class TestReadOnlyContract:
    """Per CLAUDE.md DIAG-1 + tool docstring: the tool issues NO writes to
    Stage / Bronze / source. The only write is the audit row INSERT in
    General. Verify executed SQL contains no UPDATE / DELETE / INSERT
    against Stage/Bronze."""

    def test_no_write_sql_against_stage_or_bronze(self):
        mod = _load_tool_module()
        loader = _make_table_config_loader([_PK_COL])
        cursor_factory = _make_cursor_factory(
            stage_rows=[("PK001",), ("PK002",)],
            bronze_active_rows=[("PK001",)],
            bronze_pk_lookup={("PK002",): []},
        )
        mod.main(
            source=_SOURCE, table=_TABLE,
            limit=10, actor=_ACTOR, no_audit_event=False,
            cursor_factory=cursor_factory, table_config_loader=loader,
            audit_cursor_factory=cursor_factory,
        )
        executed_sql = "\n".join(cursor_factory._executed["sql"])
        # No write SQL against Stage / Bronze tables
        for write_kw in ("UPDATE [UDM_Stage]", "UPDATE [UDM_Bronze]",
                         "DELETE FROM [UDM_Stage]", "DELETE FROM [UDM_Bronze]",
                         "INSERT INTO [UDM_Stage]", "INSERT INTO [UDM_Bronze]"):
            assert write_kw not in executed_sql, (
                f"Read-only contract violation: found {write_kw!r} in "
                f"executed SQL."
            )
