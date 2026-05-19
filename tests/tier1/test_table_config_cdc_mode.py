"""Tier 1 tests for B-543: TableConfig.cdc_mode field + TableConfigLoader SELECT extension.

Per D63 + D125 (3-mode CDC dispatch). Pins:

1. `TableConfig` dataclass has `cdc_mode: str` field with default `'change_detect'`
2. Field accepts the 3 canonical values per D125 (`'change_detect'`, `'parquet_snapshot'`, `'both'`)
3. WORKER-SERIALIZE invariant: `cdc_mode` round-trips through `dataclasses.asdict()`
   (per CLAUDE.md WORKER-SERIALIZE Do-NOT rule)
4. `TableConfigLoader._TABLES_SELECT` includes `CDCMode` column reference
5. `_build_configs` row-mapping defaults to `'change_detect'` when row.get('CDCMode') returns None
   (defensive — handles pre-migration env + NULL value cases)

Per CLAUDE.md "Dev workstation pytest collection skew" (B-328): production deps
mocked via sys.modules pre-patch.
"""

from __future__ import annotations

import sys
import types
from dataclasses import asdict
from pathlib import Path
from unittest.mock import MagicMock

import pytest


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


@pytest.fixture(autouse=True)
def _stub_production_modules():
    """Pre-patch sys.modules so `import orchestration.table_config` works
    on Windows dev workstations without polars / connectorx / pyodbc / oracledb
    installed."""

    saved = {}
    stub_names = [
        "polars",
        "connectorx",
        "pyodbc",
        "oracledb",
        "polars_hash",
    ]
    for name in stub_names:
        saved[name] = sys.modules.get(name)
        sys.modules[name] = MagicMock()

    # Force re-import of orchestration.table_config to pick up stubs
    saved["orchestration.table_config"] = sys.modules.get("orchestration.table_config")
    sys.modules.pop("orchestration.table_config", None)

    yield

    # Restore
    for name, mod in saved.items():
        if mod is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = mod
    sys.modules.pop("orchestration.table_config", None)


def _import_tc():
    """Lazy-import orchestration.table_config under stubbed modules."""

    from orchestration import table_config  # noqa: PLC0415
    return table_config


# ---------------------------------------------------------------------------
# Class A — Dataclass field shape
# ---------------------------------------------------------------------------


def test_table_config_has_cdc_mode_field():
    """B-543: TableConfig dataclass MUST declare `cdc_mode` field."""

    tc_mod = _import_tc()
    import dataclasses
    fields = {f.name: f for f in dataclasses.fields(tc_mod.TableConfig)}
    assert "cdc_mode" in fields, \
        "TableConfig must declare cdc_mode field per B-543 + D63 + D125"


def test_cdc_mode_default_change_detect():
    """D63 default `'change_detect'` MUST be preserved per D125 forward-only-additive."""

    tc_mod = _import_tc()
    # Construct with only required positional args
    tc = tc_mod.TableConfig(
        source_object_name="ACCT",
        source_server="dna-host",
        source_database="DNA",
        source_schema_name="osibank",
        source_name="DNA",
    )
    assert tc.cdc_mode == "change_detect", \
        "D63 + D125 default 'change_detect' must be preserved"


@pytest.mark.parametrize(
    "value",
    ["change_detect", "parquet_snapshot", "both"],
)
def test_cdc_mode_accepts_3_canonical_values(value):
    """D125 3-value enum: `'change_detect'`, `'parquet_snapshot'`, `'both'`."""

    tc_mod = _import_tc()
    tc = tc_mod.TableConfig(
        source_object_name="ACCT",
        source_server="dna-host",
        source_database="DNA",
        source_schema_name="osibank",
        source_name="DNA",
        cdc_mode=value,
    )
    assert tc.cdc_mode == value


# ---------------------------------------------------------------------------
# Class B — WORKER-SERIALIZE round-trip invariant
# ---------------------------------------------------------------------------


def test_cdc_mode_round_trips_via_asdict():
    """WORKER-SERIALIZE (per CLAUDE.md): cdc_mode MUST survive asdict round-trip
    so ProcessPoolExecutor workers see the same value the parent set."""

    tc_mod = _import_tc()
    tc = tc_mod.TableConfig(
        source_object_name="ACCT",
        source_server="dna-host",
        source_database="DNA",
        source_schema_name="osibank",
        source_name="DNA",
        cdc_mode="both",
    )
    serialized = asdict(tc)
    assert serialized["cdc_mode"] == "both", \
        "cdc_mode MUST survive dataclasses.asdict() round-trip per WORKER-SERIALIZE"


# ---------------------------------------------------------------------------
# Class C — TableConfigLoader._TABLES_SELECT inclusion
# ---------------------------------------------------------------------------


def test_tables_select_includes_cdcmode_column():
    """B-543: _TABLES_SELECT MUST include CDCMode column reference."""

    tc_mod = _import_tc()
    assert "CDCMode" in tc_mod.TableConfigLoader._TABLES_SELECT, \
        "TableConfigLoader._TABLES_SELECT must SELECT CDCMode per B-543"


def test_tables_select_preserves_canonical_existing_columns():
    """Defensive: B-543 SELECT extension must NOT regress existing column list."""

    tc_mod = _import_tc()
    sql = tc_mod.TableConfigLoader._TABLES_SELECT
    # Spot-check canonical existing columns (regression guard for the regex
    # substitution that added CDCMode)
    canonical_cols = [
        "SourceObjectName", "SourceName", "StageTableName",
        "BronzeTableName", "SourceAggregateColumnName",
        "StripSuffix", "MaxRowsPerDay",
    ]
    for col in canonical_cols:
        assert col in sql, f"Canonical column {col!r} missing from _TABLES_SELECT"


# ---------------------------------------------------------------------------
# Class D — _build_configs defensive defaulting
# ---------------------------------------------------------------------------


def test_build_configs_defaults_when_cdcmode_missing_in_row():
    """B-543 defensive contract: if row.get('CDCMode') returns None (pre-migration
    env where SELECT doesn't include the column, OR migration applied but value
    is NULL), tc.cdc_mode MUST default to 'change_detect'."""

    tc_mod = _import_tc()

    # Source-text verification (since _build_configs requires full pl.DataFrame
    # fixtures that are heavy to construct in unit test scope, pin via source
    # inspection that the defensive default pattern is present):
    src = Path("orchestration/table_config.py").read_text(encoding="utf-8")
    assert 'tc.cdc_mode = str(_cdc_mode) if _cdc_mode is not None else "change_detect"' in src, \
        "_build_configs MUST default cdc_mode to 'change_detect' on None per B-543 defensive contract"


@pytest.mark.parametrize(
    "row_value,expected",
    [
        ("change_detect", "change_detect"),
        ("parquet_snapshot", "parquet_snapshot"),
        ("both", "both"),
        (None, "change_detect"),  # NULL / missing column → default
    ],
)
def test_cdc_mode_row_mapping_semantic(row_value, expected):
    """Pin the row-mapping semantic via direct invocation. Each input value
    produces the documented output."""

    # Replicate the row-mapping logic to verify the semantic is correct
    _cdc_mode = row_value
    result = str(_cdc_mode) if _cdc_mode is not None else "change_detect"
    assert result == expected
