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


def test_run_parquet_write_step_propagates_exception():
    """CRITICAL CLAUDE.md Do-NOT rule (Parquet-before-CDC failure propagation):
    if write_parquet_snapshot raises, run_parquet_write_step MUST NOT catch +
    swallow the exception. Orchestrator control-flow then exits the function
    BEFORE run_cdc_promotion is reached, preserving the audit-substrate-before-
    Bronze-change invariant. Pinned by cohort-review Agent ad50cb5cceda3f90c
    2026-05-19 Scope 2 IMPROVE finding."""

    ps = _import_ps()

    tracker = MagicMock()
    track_cm = MagicMock()
    tracker.track.return_value = track_cm
    track_cm.__enter__ = MagicMock(return_value=track_cm)
    track_cm.__exit__ = MagicMock(return_value=False)
    tracker.batch_id = 99

    tc = MagicMock()
    tc.source_name = "DNA"
    tc.source_object_name = "ACCT"

    # write_parquet_snapshot raises — helper MUST NOT swallow it
    ps.write_parquet_snapshot = MagicMock(
        side_effect=RuntimeError("Simulated Parquet write failure")
    )

    from datetime import date
    df = MagicMock()
    with pytest.raises(RuntimeError, match="Simulated Parquet write failure"):
        ps.run_parquet_write_step(
            tc, df, tracker,
            business_date=date(2026, 5, 19),
        )

    # Event tracking SHOULD have been entered (event_tracker.track() context
    # manager wraps the call); the __exit__ propagates the exception by
    # returning False (not suppressing).
    tracker.track.assert_called_once_with("PARQUET_WRITE", tc)


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


def test_large_tables_parquet_snapshot_invokes_replay_step():
    """B-552 v1 closure 2026-05-19: 'parquet_snapshot' mode in large_tables.py
    invokes run_parquet_replay_step() + run_scd2_promotion(targeted=False) +
    early-return; NO longer raises NotImplementedError."""

    src = Path("orchestration/large_tables.py").read_text(encoding="utf-8")
    # B-552 v1 replaces the NotImplementedError stub with replay+SCD2 dispatch
    assert "run_parquet_replay_step(" in src, \
        "B-552 v1 closure: large_tables.py MUST invoke run_parquet_replay_step for 'parquet_snapshot' mode"
    assert "B-552" in src, "B-552 reference must be preserved in dispatch comments"
    # NotImplementedError stub from B-544 v1 should be REMOVED
    assert "raise NotImplementedError" not in src, \
        "B-552 v1 closure: large_tables.py should NOT raise NotImplementedError anymore"


def test_small_tables_parquet_snapshot_invokes_replay_step():
    """B-552 v1 closure 2026-05-19: 'parquet_snapshot' mode in small_tables.py
    invokes run_parquet_replay_step() + run_scd2_promotion() + early-return;
    NO longer raises NotImplementedError."""

    src = Path("orchestration/small_tables.py").read_text(encoding="utf-8")
    assert "run_parquet_replay_step(" in src, \
        "B-552 v1 closure: small_tables.py MUST invoke run_parquet_replay_step for 'parquet_snapshot' mode"
    assert "B-552" in src, "B-552 reference must be preserved in dispatch comments"
    assert "raise NotImplementedError" not in src, \
        "B-552 v1 closure: small_tables.py should NOT raise NotImplementedError anymore"


def test_orchestrator_dispatch_blocks_legacy_string():
    """Pitfall #9.k forward-prevention: dispatch must reject the stale
    'legacy' value (canonical is 'change_detect')."""

    ps = _import_ps()
    src_ps = Path("orchestration/pipeline_steps.py").read_text(encoding="utf-8")
    # The validator emits a ValueError that cites VALID_CDC_MODES — this
    # implicitly rejects 'legacy'. Verify VALID_CDC_MODES does not include it.
    assert "'legacy'" not in str(ps.VALID_CDC_MODES)
    assert "legacy" not in src_ps.split("VALID_CDC_MODES = ")[1].split(")")[0]


# ---------------------------------------------------------------------------
# Class E — B-552 v1 closure tests (run_parquet_replay_step + replay→SCD2 ordering)
# ---------------------------------------------------------------------------


def test_pipeline_steps_exports_run_parquet_replay_step():
    """B-552 v1: run_parquet_replay_step exported alongside existing helpers."""

    ps = _import_ps()
    assert hasattr(ps, "run_parquet_replay_step"), \
        "B-552 v1: run_parquet_replay_step must be exported from pipeline_steps"


def test_run_parquet_replay_step_returns_cdc_result_compatible_shape():
    """B-552 v1: run_parquet_replay_step adapts ReplayResult → CDCResult shape
    so run_scd2_promotion can consume it without further transformation."""

    ps = _import_ps()

    tracker = MagicMock()
    track_cm = MagicMock()
    tracker.track.return_value = track_cm
    track_cm.__enter__ = MagicMock(return_value=track_cm)
    track_cm.__exit__ = MagicMock(return_value=False)
    tracker.batch_id = 999

    tc = MagicMock()
    tc.source_name = "DNA"
    tc.source_object_name = "ACCT"
    tc.pk_columns = ["AcctNo", "EffDate"]

    parquet_write_result = MagicMock()
    parquet_write_result.registry_id = 42

    mock_df = MagicMock()
    mock_replay_result = MagicMock()
    mock_replay_result.df = mock_df
    mock_replay_result.row_count = 5000

    # Patch replay_parquet_snapshot at module level
    ps.replay_parquet_snapshot = MagicMock(return_value=mock_replay_result)
    # Use the real CDCResult dataclass (already imported by pipeline_steps)
    from datetime import date
    target = date(2026, 5, 19)

    cdc_result = ps.run_parquet_replay_step(
        tc, parquet_write_result, tracker,
        business_date=target,
    )

    # REPLAY event tracked
    tracker.track.assert_called_once_with("REPLAY", tc)
    # replay_parquet_snapshot called with registry_id + replay_batch_id
    ps.replay_parquet_snapshot.assert_called_once()
    call_kwargs = ps.replay_parquet_snapshot.call_args.kwargs
    assert call_kwargs["registry_id"] == 42
    assert call_kwargs["replay_batch_id"] == 999
    # CDCResult adapter shape verified via constructor call args (CDCResult
    # class is mocked at module-import time via cdc.engine sys.modules stub;
    # asserting on the returned cdc_result.<attr> tests the MagicMock not the
    # adapter logic. Instead verify what kwargs CDCResult() was called with).
    ps.CDCResult.assert_called_once()
    cdc_kwargs = ps.CDCResult.call_args.kwargs
    assert cdc_kwargs["df_current"] is mock_df
    assert cdc_kwargs["pk_columns"] == ["AcctNo", "EffDate"]
    # B-552 v1 scope: deleted_pks=None; counts=0; verify_before_close=None
    assert cdc_kwargs["deleted_pks"] is None
    assert cdc_kwargs["inserts"] == 0
    assert cdc_kwargs["verify_before_close"] is None
    # Event detail tagged with business_date + registry_id
    assert "2026-05-19" in str(track_cm.event_detail)
    assert "registry_id=42" in str(track_cm.event_detail)
    # rows_processed populated from replay result
    assert track_cm.rows_processed == 5000


def test_large_tables_replay_before_scd2_per_b552_v1_ordering():
    """B-552 v1 source-text ordering: run_parquet_replay_step MUST appear
    BEFORE the run_scd2_promotion in the 'parquet_snapshot' dispatch block.
    Per D2 + D115 source-exactness invariants — Parquet is canonical source;
    SCD2 consumes the replayed materialized state, not the original df."""

    src = Path("orchestration/large_tables.py").read_text(encoding="utf-8")
    replay_pos = src.find("cdc_result = run_parquet_replay_step(")
    assert replay_pos >= 0, "run_parquet_replay_step call site missing in 'parquet_snapshot' branch"
    # Find the run_scd2_promotion call AFTER the replay invocation
    scd2_after_replay_pos = src.find("run_scd2_promotion(", replay_pos)
    assert scd2_after_replay_pos >= 0, (
        "run_scd2_promotion call after replay missing — 'parquet_snapshot' branch incomplete"
    )
    # Verify they're in the same dispatch block (no intervening other dispatch)
    # (replay_pos < scd2_after_replay_pos is guaranteed since find() is forward)
    assert scd2_after_replay_pos > replay_pos


def test_small_tables_replay_before_scd2_per_b552_v1_ordering():
    """Same B-552 v1 ordering invariant for small_tables.py."""

    src = Path("orchestration/small_tables.py").read_text(encoding="utf-8")
    replay_pos = src.find("run_parquet_replay_step(")
    # small_tables.py uses run_scd2_promotion() without targeted= (default targeted=False)
    # Anchor on the parquet_snapshot branch's SCD2 call which uses cdc_result from replay
    scd2_after_replay_pos = src.find('cdc_result = run_parquet_replay_step(')
    # Find run_scd2_promotion AFTER that point
    if scd2_after_replay_pos >= 0:
        scd2_after_replay_pos = src.find('run_scd2_promotion(', scd2_after_replay_pos)
    assert replay_pos >= 0, "run_parquet_replay_step call site missing in small_tables.py"
    assert scd2_after_replay_pos >= 0, "Post-replay SCD2 call site missing in small_tables.py"
    assert replay_pos < scd2_after_replay_pos, (
        "B-552 v1 ordering invariant: run_parquet_replay_step MUST appear before "
        "post-replay run_scd2_promotion in small_tables.py source order"
    )


def test_orchestrators_b552_v1_use_targeted_false_for_parquet_snapshot_mode():
    """B-552 v1 routes ALL parquet_snapshot mode through run_scd2_promotion(targeted=False)
    regardless of table size. Large-table delete-detection via day-N vs day-N-1
    Parquet diff deferred to B-563 follow-up. Pin the v1 scope via source-text."""

    lt_src = Path("orchestration/large_tables.py").read_text(encoding="utf-8")
    # In large_tables.py 'parquet_snapshot' branch should explicitly say targeted=False
    # (the other run_scd2_promotion call elsewhere uses targeted=True for legacy windowed CDC)
    assert "targeted=False" in lt_src, \
        "B-552 v1: large_tables.py 'parquet_snapshot' branch MUST use targeted=False"
    # small_tables.py only has run_scd2_promotion() default-args (targeted=False is default)
    # so we don't pin the targeted=False keyword for small_tables specifically


def test_b552_v1_does_not_break_classify_parity_or_dispatch():
    """Regression check: B-552 v1 closure should NOT change dispatch logic
    for 'change_detect' or 'both' modes; only 'parquet_snapshot' path changes."""

    ps = _import_ps()
    # All 3 modes still valid
    assert ps.VALID_CDC_MODES == ("change_detect", "parquet_snapshot", "both")
    # Constants unchanged
    assert ps.CDC_MODE_CHANGE_DETECT == "change_detect"
    assert ps.CDC_MODE_PARQUET_SNAPSHOT == "parquet_snapshot"
    assert ps.CDC_MODE_BOTH == "both"
    # dispatch_check_cdc_mode unchanged
    tc = MagicMock()
    tc.source_name = "DNA"
    tc.source_object_name = "ACCT"
    tc.cdc_mode = "change_detect"
    assert ps.dispatch_check_cdc_mode(tc) == "change_detect"

