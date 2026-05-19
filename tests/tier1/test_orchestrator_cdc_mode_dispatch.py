"""Tier 1 tests for B-544 v1 orchestrator 3-mode dispatch per D63 + D125.

v1 scope:
- 'change_detect' mode: no Parquet write; legacy CDC path; current behavior preserved
- 'both' mode: Parquet write FIRST, then legacy CDC path; CLAUDE.md Do-NOT rule
  (Parquet-before-CDC invariant) verified via source-text inspection
- 'parquet_snapshot' mode: raises NotImplementedError after Parquet write succeeds

Pins:
1. `dispatch_check_cdc_mode()` validates D125 3-value enum + defaults to
   'change_detect' on missing field + raises ValueError on invalid string
2. `run_parquet_write_step()` is exported from `orchestration/pipeline_steps`
3. Source-text invariants: dispatch logic present in both orchestrators with
   correct Parquet-before-CDC sequencing

Per CLAUDE.md "Dev workstation pytest collection skew" (B-328): production deps
mocked via sys.modules pre-patch.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


@pytest.fixture(autouse=True)
def _stub_production_modules():
    """Pre-patch sys.modules so `import orchestration.pipeline_steps` works
    on Windows dev workstations without polars / connectorx / pyodbc /
    oracledb / data_load deps available."""

    saved = {}
    stub_names = [
        "polars",
        "connectorx",
        "pyodbc",
        "oracledb",
        "polars_hash",
        "cdc.engine",
        "data_load.bcp_loader",
        "data_load.index_management",
        "data_load.parquet_writer",
        "extract.udm_connectorx_extractor",
        "scd2.engine",
    ]
    for name in stub_names:
        saved[name] = sys.modules.get(name)
        sys.modules[name] = MagicMock()

    # Force re-import of orchestration.pipeline_steps
    saved["orchestration.pipeline_steps"] = sys.modules.get("orchestration.pipeline_steps")
    sys.modules.pop("orchestration.pipeline_steps", None)

    yield

    for name, mod in saved.items():
        if mod is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = mod
    sys.modules.pop("orchestration.pipeline_steps", None)


def _import_ps():
    from orchestration import pipeline_steps  # noqa: PLC0415
    return pipeline_steps


# ---------------------------------------------------------------------------
# Class A — Module surface invariants
# ---------------------------------------------------------------------------


def test_pipeline_steps_exports_dispatch_helpers():
    ps = _import_ps()
    assert hasattr(ps, "dispatch_check_cdc_mode"), \
        "B-544: dispatch_check_cdc_mode must be exported from pipeline_steps"
    assert hasattr(ps, "run_parquet_write_step"), \
        "B-544: run_parquet_write_step must be exported from pipeline_steps"


def test_pipeline_steps_exports_3_cdc_mode_constants():
    ps = _import_ps()
    assert ps.CDC_MODE_CHANGE_DETECT == "change_detect"
    assert ps.CDC_MODE_PARQUET_SNAPSHOT == "parquet_snapshot"
    assert ps.CDC_MODE_BOTH == "both"
    assert ps.VALID_CDC_MODES == (
        "change_detect", "parquet_snapshot", "both",
    )


# ---------------------------------------------------------------------------
# Class B — dispatch_check_cdc_mode behavior
# ---------------------------------------------------------------------------


def _make_table_config_stub(cdc_mode=None):
    """Mock TableConfig with required attrs for error messages."""

    tc = MagicMock()
    tc.source_name = "DNA"
    tc.source_object_name = "ACCT"
    if cdc_mode is not None:
        tc.cdc_mode = cdc_mode
    else:
        # Simulate missing attr — use spec to disallow auto-mock
        del tc.cdc_mode
    return tc


@pytest.mark.parametrize(
    "mode",
    ["change_detect", "parquet_snapshot", "both"],
)
def test_dispatch_accepts_3_canonical_values(mode):
    ps = _import_ps()
    tc = MagicMock()
    tc.source_name = "DNA"
    tc.source_object_name = "ACCT"
    tc.cdc_mode = mode
    assert ps.dispatch_check_cdc_mode(tc) == mode


def test_dispatch_defaults_to_change_detect_on_missing_attr():
    """Defensive: if TableConfig somehow lacks cdc_mode field (pre-migration
    code path), default to 'change_detect' preserving current behavior."""

    ps = _import_ps()
    tc = MagicMock(spec=["source_name", "source_object_name"])
    tc.source_name = "DNA"
    tc.source_object_name = "ACCT"
    assert ps.dispatch_check_cdc_mode(tc) == "change_detect"


def test_dispatch_defaults_to_change_detect_on_none_value():
    ps = _import_ps()
    tc = MagicMock()
    tc.source_name = "DNA"
    tc.source_object_name = "ACCT"
    tc.cdc_mode = None
    assert ps.dispatch_check_cdc_mode(tc) == "change_detect"


def test_dispatch_defaults_to_change_detect_on_empty_string():
    ps = _import_ps()
    tc = MagicMock()
    tc.source_name = "DNA"
    tc.source_object_name = "ACCT"
    tc.cdc_mode = ""
    assert ps.dispatch_check_cdc_mode(tc) == "change_detect"


def test_dispatch_raises_on_invalid_string():
    ps = _import_ps()
    tc = MagicMock()
    tc.source_name = "DNA"
    tc.source_object_name = "ACCT"
    tc.cdc_mode = "legacy"  # Pitfall #9.k stale-value drift class — must reject
    with pytest.raises(ValueError) as exc_info:
        ps.dispatch_check_cdc_mode(tc)
    assert "invalid cdc_mode" in str(exc_info.value)
    assert "'legacy'" in str(exc_info.value)
    assert "DNA.ACCT" in str(exc_info.value)


def test_dispatch_raises_on_typo():
    """E.g., 'parquet' instead of 'parquet_snapshot'."""

    ps = _import_ps()
    tc = MagicMock()
    tc.source_name = "DNA"
    tc.source_object_name = "ACCT"
    tc.cdc_mode = "parquet"
    with pytest.raises(ValueError):
        ps.dispatch_check_cdc_mode(tc)


# ---------------------------------------------------------------------------
# Class C — run_parquet_write_step behavior
# ---------------------------------------------------------------------------


def test_run_parquet_write_step_calls_write_parquet_snapshot():
    """Helper composes correctly: emits PARQUET_WRITE event + calls
    write_parquet_snapshot with table_config-derived args."""

    ps = _import_ps()

    # Mock event_tracker.track() context manager
    tracker = MagicMock()
    track_cm = MagicMock()
    tracker.track.return_value = track_cm
    track_cm.__enter__ = MagicMock(return_value=track_cm)
    track_cm.__exit__ = MagicMock(return_value=False)
    tracker.batch_id = 42

    tc = MagicMock()
    tc.source_name = "DNA"
    tc.source_object_name = "ACCT"

    # Patch write_parquet_snapshot at the module level
    mock_result = MagicMock()
    mock_result.row_count = 1000
    ps.write_parquet_snapshot = MagicMock(return_value=mock_result)

    from datetime import date
    target = date(2026, 5, 19)
    df = MagicMock()
    result = ps.run_parquet_write_step(
        tc, df, tracker,
        business_date=target,
    )

    # Verify PARQUET_WRITE event tracked
    tracker.track.assert_called_once_with("PARQUET_WRITE", tc)
    # Verify write_parquet_snapshot called with correct kwargs
    ps.write_parquet_snapshot.assert_called_once()
    call_kwargs = ps.write_parquet_snapshot.call_args.kwargs
    assert call_kwargs["source_name"] == "DNA"
    assert call_kwargs["table_name"] == "ACCT"
    assert call_kwargs["business_date"] == target
    assert call_kwargs["batch_id"] == 42
    # Verify event detail tagged
    assert track_cm.event_detail == "2026-05-19"
    # Verify rows_processed populated from result
    assert track_cm.rows_processed == 1000
    assert result is mock_result


# ---------------------------------------------------------------------------
# Class D — Source-text invariants for orchestrator dispatch
# ---------------------------------------------------------------------------


def test_large_tables_imports_dispatch_helpers():
    src = Path("orchestration/large_tables.py").read_text(encoding="utf-8")
    assert "dispatch_check_cdc_mode" in src
    assert "run_parquet_write_step" in src
    assert "CDC_MODE_BOTH" in src


def test_small_tables_imports_dispatch_helpers():
    src = Path("orchestration/small_tables.py").read_text(encoding="utf-8")
    assert "dispatch_check_cdc_mode" in src
    assert "run_parquet_write_step" in src
    assert "CDC_MODE_BOTH" in src


def test_large_tables_parquet_before_cdc_per_donot_rule():
    """CLAUDE.md Do-NOT rule (added at remediation commit a53c50a 2026-05-19):
    in 'both' mode, write_parquet_snapshot MUST be called BEFORE
    run_cdc_promotion(). Source-text invariant: the dispatch's
    `if cdc_mode in (CDC_MODE_PARQUET_SNAPSHOT, CDC_MODE_BOTH)` block calling
    `run_parquet_write_step` MUST appear BEFORE the `run_cdc_promotion` call
    in the source."""

    src = Path("orchestration/large_tables.py").read_text(encoding="utf-8")
    parquet_pos = src.find("run_parquet_write_step(")
    cdc_pos = src.find("cdc_result = run_cdc_promotion(")
    assert parquet_pos >= 0, "run_parquet_write_step call site missing in large_tables.py"
    assert cdc_pos >= 0, "run_cdc_promotion call site missing in large_tables.py"
    assert parquet_pos < cdc_pos, (
        "CLAUDE.md Do-NOT rule violation: run_parquet_write_step MUST be "
        "before run_cdc_promotion in large_tables.py source order"
    )


def test_small_tables_parquet_before_cdc_per_donot_rule():
    src = Path("orchestration/small_tables.py").read_text(encoding="utf-8")
    parquet_pos = src.find("run_parquet_write_step(")
    cdc_pos = src.find("cdc_result = run_cdc_promotion(")
    assert parquet_pos >= 0
    assert cdc_pos >= 0
    assert parquet_pos < cdc_pos, (
        "CLAUDE.md Do-NOT rule violation: run_parquet_write_step MUST be "
        "before run_cdc_promotion in small_tables.py source order"
    )


def test_large_tables_parquet_snapshot_raises_notimplemented():
    src = Path("orchestration/large_tables.py").read_text(encoding="utf-8")
    assert "raise NotImplementedError" in src
    assert "B-544 v1" in src
    assert "B-552" in src


def test_small_tables_parquet_snapshot_raises_notimplemented():
    src = Path("orchestration/small_tables.py").read_text(encoding="utf-8")
    assert "raise NotImplementedError" in src
    assert "B-544 v1" in src
    assert "B-552" in src


def test_orchestrator_dispatch_blocks_legacy_string():
    """Pitfall #9.k forward-prevention: dispatch must reject the stale
    'legacy' value (canonical is 'change_detect')."""

    ps = _import_ps()
    src_ps = Path("orchestration/pipeline_steps.py").read_text(encoding="utf-8")
    # The validator emits a ValueError that cites VALID_CDC_MODES — this
    # implicitly rejects 'legacy'. Verify VALID_CDC_MODES does not include it.
    assert "'legacy'" not in str(ps.VALID_CDC_MODES)
    assert "legacy" not in src_ps.split("VALID_CDC_MODES = ")[1].split(")")[0]
