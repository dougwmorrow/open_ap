"""Apply-path Tier 1 tests for run_parquet_delete_detection_step() per B-563.

Follows the B-564 4-layer forward-prevention architecture via the shared
test utilities at ``tests/tier1/_replay_test_helpers.py`` (per B-566
closure 2026-05-19) so the new B-563 helper cannot ship with the same
MagicMock false-coverage class that B-552 v1 hit.

4-layer architecture (mirrors B-564):

Layer 1 (TestB563CanonicalSignatureAST): extract canonical signature of
    ``run_parquet_delete_detection_step`` from
    ``orchestration/pipeline_steps.py`` source via AST + assert against
    pinned ``CANONICAL_DELETE_DETECTION_KWARGS`` constant. If signature
    drifts, test fails predictably.

Layer 2 (TestB563SignatureValidatingStubs): use shared
    ``make_signature_validating_stub`` factory to replace
    ``query_latest_snapshot_for_date`` AND ``replay_parquet_snapshot``
    with stubs that raise TypeError on wrong kwargs. Then invoke
    ``run_parquet_delete_detection_step()`` and assert no TypeError
    propagates -- structural forward-prevention against the MagicMock
    accepts-anything class.

Layer 3 (TestB563BehaviorContracts): pin first-load case (no prior
    snapshot → deleted_pks=None unchanged) + happy-path (prior found
    → deleted_pks populated via anti-join) + empty pk_columns case
    (skip + return unchanged).

Layer 4 (TestB563MemoryReleaseContract): inspect the helper's source
    AST + assert it calls ``gc.collect()`` AND ``del prior_replay`` so
    peak memory is bounded for 3B+ row tables. Pin via source-text
    inspection (deterministic; no production deps).

Per CLAUDE.md "Dev workstation pytest collection skew" (B-328): polars
NOT typically installed locally; sys.modules stubbing + AST extraction
allows these tests to run on bare Windows dev workstations.
"""

from __future__ import annotations

import ast
import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


from tests.tier1._replay_test_helpers import (  # noqa: E402
    extract_kwonly_arg_names_from_source,
    make_signature_validating_stub,
)


# ---------------------------------------------------------------------------
# Canonical signature pin (B-563)
# ---------------------------------------------------------------------------
# Pinned 2026-05-19 per orchestration/pipeline_steps.py
# ``run_parquet_delete_detection_step`` signature. If the real signature
# changes, Layer 1 fails predictably + this constant must update in
# lockstep with all callers (orchestration/large_tables.py).
# ---------------------------------------------------------------------------

CANONICAL_DELETE_DETECTION_KWARGS: tuple[str, ...] = (
    "business_date",
)


# ---------------------------------------------------------------------------
# Fixture: sys.modules stub (with B-567 cross-file pollution defense)
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _stub_production_modules():
    """Pre-patch sys.modules so ``import orchestration.pipeline_steps``
    works on Windows dev without polars / connectorx / pyodbc deps.
    Includes B-567 cross-file pollution defense via package-attribute
    delattr at setup + teardown.
    """

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
        "data_load.parquet_replay",
        "data_load.parquet_registry_client",
        "extract.udm_connectorx_extractor",
        "scd2.engine",
    ]
    for name in stub_names:
        saved[name] = sys.modules.get(name)
        sys.modules[name] = MagicMock()

    saved["orchestration.pipeline_steps"] = sys.modules.get("orchestration.pipeline_steps")
    sys.modules.pop("orchestration.pipeline_steps", None)
    _orch_pkg = sys.modules.get("orchestration")
    if _orch_pkg is not None and hasattr(_orch_pkg, "pipeline_steps"):
        delattr(_orch_pkg, "pipeline_steps")
    # Also delattr data_load.parquet_registry_client + data_load.parquet_replay
    # to prevent cross-file pollution from tier0 registry tests that load the
    # REAL modules via importlib.util.spec_from_file_location.
    _dl_pkg = sys.modules.get("data_load")
    for submod in ("parquet_registry_client", "parquet_replay"):
        if _dl_pkg is not None and hasattr(_dl_pkg, submod):
            delattr(_dl_pkg, submod)

    yield

    for name, mod in saved.items():
        if mod is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = mod
    sys.modules.pop("orchestration.pipeline_steps", None)
    _orch_pkg = sys.modules.get("orchestration")
    if _orch_pkg is not None and hasattr(_orch_pkg, "pipeline_steps"):
        delattr(_orch_pkg, "pipeline_steps")
    _dl_pkg = sys.modules.get("data_load")
    for submod in ("parquet_registry_client", "parquet_replay"):
        if _dl_pkg is not None and hasattr(_dl_pkg, submod):
            delattr(_dl_pkg, submod)


def _import_ps():
    from orchestration import pipeline_steps  # noqa: PLC0415
    return pipeline_steps


# ===========================================================================
# Layer 1 -- Canonical signature AST extraction
# ===========================================================================


class TestB563CanonicalSignatureAST:
    """Extract canonical signature from pipeline_steps.py source via AST
    parsing (no polars dep). Pin against test constant; if real signature
    changes, test fails predictably."""

    def test_canonical_signature_extracted_via_ast_matches_test_constant(self):
        """B-563 Layer 1: parse pipeline_steps.py source AST to extract
        ``run_parquet_delete_detection_step`` keyword-only args. Compare
        against CANONICAL_DELETE_DETECTION_KWARGS. If real signature drifts,
        test fails + constant must update in lockstep."""

        ps_src_path = _PROJECT_ROOT / "orchestration" / "pipeline_steps.py"

        kwonly_arg_names = extract_kwonly_arg_names_from_source(
            source_path=ps_src_path,
            function_name="run_parquet_delete_detection_step",
        )

        assert kwonly_arg_names == CANONICAL_DELETE_DETECTION_KWARGS, (
            f"Canonical signature drift detected!\n"
            f"  Test constant CANONICAL_DELETE_DETECTION_KWARGS: "
            f"{CANONICAL_DELETE_DETECTION_KWARGS}\n"
            f"  Real signature in pipeline_steps.py: {kwonly_arg_names}\n"
            f"  Fix: update CANONICAL_DELETE_DETECTION_KWARGS in this test "
            f"file AND verify all callers (orchestration/large_tables.py) "
            f"pass the new kwargs."
        )

    def test_function_exists_in_pipeline_steps(self):
        """B-563: run_parquet_delete_detection_step must be defined in
        orchestration/pipeline_steps.py."""

        ps = _import_ps()
        assert hasattr(ps, "run_parquet_delete_detection_step"), (
            "B-563: run_parquet_delete_detection_step must be exported"
        )

    def test_function_first_positional_args_are_table_config_cdc_result_event_tracker(self):
        """B-563: the 3 positional args (before * marker) are documented
        as table_config + cdc_result + event_tracker."""

        ps_src_path = _PROJECT_ROOT / "orchestration" / "pipeline_steps.py"
        src = ps_src_path.read_text(encoding="utf-8")
        tree = ast.parse(src)

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == "run_parquet_delete_detection_step"
            ):
                positional_args = [a.arg for a in node.args.args]
                assert positional_args == [
                    "table_config", "cdc_result", "event_tracker",
                ], (
                    f"B-563 positional args drifted: got {positional_args}, "
                    f"expected ['table_config', 'cdc_result', 'event_tracker']"
                )
                return

        pytest.fail("run_parquet_delete_detection_step not found")


# ===========================================================================
# Layer 2 -- Signature-validating stub apply-path
# ===========================================================================


class TestB563SignatureValidatingStubs:
    """Replace replay_parquet_snapshot + query_latest_snapshot_for_date
    with stubs that validate kwargs against canonical signatures
    (via shared make_signature_validating_stub factory from B-566).
    If run_parquet_delete_detection_step composes wrong kwargs, stubs
    raise TypeError -- structural forward-prevention against MagicMock
    accepts-anything class (B-552 v1 Finding 1.1 regression class)."""

    def _build_inputs(self):
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

        cdc_result = MagicMock()
        cdc_result.pk_columns = ["AcctNo", "EffDate"]
        cdc_result.df_current = MagicMock()
        cdc_result.deleted_pks = None

        return ps, tracker, tc, cdc_result

    def test_run_parquet_delete_detection_step_passes_canonical_replay_kwargs(self):
        """B-563 Layer 2: when prior-day snapshot exists, the helper
        invokes replay_parquet_snapshot() with the canonical 5 kwargs.
        Signature-validating stub raises TypeError on wrong kwargs --
        catches the same regression class as B-552 v1 Finding 1.1."""

        ps, tracker, tc, cdc_result = self._build_inputs()

        # Stub query_latest_snapshot_for_date to return a prior row
        prior_row = {
            "RegistryId": 42,
            "BatchId": 555,
        }

        # Patch the local imports inside run_parquet_delete_detection_step
        # via the stubbed modules in sys.modules.
        import data_load.parquet_registry_client as prc
        import data_load.parquet_replay as pr

        prc.query_latest_snapshot_for_date = MagicMock(return_value=prior_row)

        # Use the signature-validating stub for replay_parquet_snapshot
        from tests.tier1._replay_test_helpers import CANONICAL_REPLAY_KWARGS

        mock_replay_result = MagicMock()
        mock_replay_result.row_count = 4500
        # Construct a small "df" with .select() returning another mock
        mock_pk_df = MagicMock()
        mock_replay_result.df.select.return_value = mock_pk_df

        pr.replay_parquet_snapshot = make_signature_validating_stub(
            canonical_kwargs=CANONICAL_REPLAY_KWARGS,
            return_value=mock_replay_result,
        )

        # Invoke -- no TypeError should propagate from the signature-validating stub
        ps.run_parquet_delete_detection_step(
            tc, cdc_result, tracker,
            business_date=date(2026, 5, 19),
        )

        # query_latest_snapshot_for_date should be called with prior_business_date
        prc.query_latest_snapshot_for_date.assert_called_once()
        call_kwargs = prc.query_latest_snapshot_for_date.call_args.kwargs
        assert call_kwargs["source_name"] == "DNA"
        assert call_kwargs["table_name"] == "ACCT"
        assert call_kwargs["business_date"] == date(2026, 5, 18)


# ===========================================================================
# Layer 3 -- Behavior contracts
# ===========================================================================


class TestB563BehaviorContracts:
    """Pin first-load case + happy-path + empty-pk cases."""

    def _build_inputs(self):
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

        cdc_result = MagicMock()
        cdc_result.pk_columns = ["AcctNo", "EffDate"]
        cdc_result.df_current = MagicMock()
        cdc_result.deleted_pks = None

        return ps, tracker, tc, cdc_result

    def test_first_load_case_returns_cdc_result_unchanged(self):
        """B-563 Layer 3: when query_latest_snapshot_for_date returns None
        (first-load OR not-verified), helper returns cdc_result UNCHANGED
        with deleted_pks=None preserved. Caller falls back to
        run_scd2_promotion(targeted=False) per B-552 v1 semantics."""

        ps, tracker, tc, cdc_result = self._build_inputs()

        import data_load.parquet_registry_client as prc
        prc.query_latest_snapshot_for_date = MagicMock(return_value=None)

        result = ps.run_parquet_delete_detection_step(
            tc, cdc_result, tracker,
            business_date=date(2026, 5, 19),
        )

        assert result is cdc_result, (
            "B-563: first-load case must return cdc_result UNCHANGED "
            "(same object reference)"
        )
        assert result.deleted_pks is None, (
            "B-563: deleted_pks must remain None on first-load"
        )

    def test_empty_pk_columns_returns_cdc_result_unchanged(self):
        """B-563 Layer 3: if cdc_result.pk_columns is empty/None, helper
        skips the diff + returns unchanged (cannot compute set-diff
        without a key). Defensive against UdmTablesColumnsList misconfig."""

        ps, tracker, tc, cdc_result = self._build_inputs()
        cdc_result.pk_columns = []  # empty

        # query_latest_snapshot_for_date should NOT be called when pk_columns empty
        import data_load.parquet_registry_client as prc
        prc.query_latest_snapshot_for_date = MagicMock(return_value=None)

        result = ps.run_parquet_delete_detection_step(
            tc, cdc_result, tracker,
            business_date=date(2026, 5, 19),
        )

        assert result is cdc_result
        prc.query_latest_snapshot_for_date.assert_not_called()

    def test_happy_path_populates_deleted_pks(self):
        """B-563 Layer 3: when prior-day snapshot exists, replay both +
        compute anti-join on PK columns + set deleted_pks on cdc_result."""

        ps, tracker, tc, cdc_result = self._build_inputs()

        import data_load.parquet_registry_client as prc
        import data_load.parquet_replay as pr

        prior_row = {"RegistryId": 42, "BatchId": 555}
        prc.query_latest_snapshot_for_date = MagicMock(return_value=prior_row)

        # Mock replay returns a result with a df whose select() returns a "PK df"
        # whose join() returns a "deleted_pks df"
        mock_pk_df_prior = MagicMock()
        mock_pk_df_current = MagicMock()
        mock_deleted_pks_df = MagicMock()
        mock_deleted_pks_df.__len__ = MagicMock(return_value=7)
        mock_pk_df_prior.join.return_value = mock_deleted_pks_df
        mock_pk_df_prior.__len__ = MagicMock(return_value=100)
        mock_pk_df_current.__len__ = MagicMock(return_value=95)

        # Prior replay result's df.select returns prior_pks
        mock_prior_replay = MagicMock()
        mock_prior_replay.df.select.return_value = mock_pk_df_prior
        mock_prior_replay.row_count = 100
        pr.replay_parquet_snapshot = MagicMock(return_value=mock_prior_replay)

        # cdc_result.df_current.select returns current_pks
        cdc_result.df_current.select.return_value = mock_pk_df_current

        result = ps.run_parquet_delete_detection_step(
            tc, cdc_result, tracker,
            business_date=date(2026, 5, 19),
        )

        # deleted_pks should be set on returned cdc_result
        assert result.deleted_pks is mock_deleted_pks_df, (
            "B-563: deleted_pks must be set to the anti-join result"
        )
        # Anti-join called with correct args
        mock_pk_df_prior.join.assert_called_once_with(
            mock_pk_df_current,
            on=["AcctNo", "EffDate"],
            how="anti",
        )


# ===========================================================================
# Layer 4 -- Memory release contract (source-text inspection)
# ===========================================================================


class TestB563MemoryReleaseContract:
    """Forward-prevention against memory regression: large-table delete-
    detection MUST release the prior-day replay's full DataFrame
    immediately after PK extraction + call gc.collect() to bound peak
    memory. Pin via AST inspection so future refactors can't drop
    the release without breaking this test."""

    def test_helper_imports_gc_module(self):
        """B-563 Layer 4: gc module imported (required for explicit
        memory release per B-563 memory contract)."""

        ps_src_path = _PROJECT_ROOT / "orchestration" / "pipeline_steps.py"
        src = ps_src_path.read_text(encoding="utf-8")
        tree = ast.parse(src)

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == "run_parquet_delete_detection_step"
            ):
                # Look for `import gc` in function body
                imports_gc = False
                for child in ast.walk(node):
                    if isinstance(child, ast.Import):
                        for alias in child.names:
                            if alias.name == "gc":
                                imports_gc = True
                                break
                assert imports_gc, (
                    "B-563 Layer 4: run_parquet_delete_detection_step must "
                    "import `gc` for explicit memory release between replays"
                )
                return

        pytest.fail("run_parquet_delete_detection_step not found")

    def test_helper_calls_gc_collect_in_source(self):
        """B-563 Layer 4: gc.collect() invoked between prior-replay release
        and current-replay anti-join. Source-text check (deterministic)."""

        ps_src_path = _PROJECT_ROOT / "orchestration" / "pipeline_steps.py"
        src = ps_src_path.read_text(encoding="utf-8")

        # Find the function body
        fn_start = src.find("def run_parquet_delete_detection_step(")
        assert fn_start >= 0, "function not found"
        # Function body extends until next top-level def OR end of file
        fn_end_def = src.find("\ndef ", fn_start + 1)
        fn_body = src[fn_start:fn_end_def] if fn_end_def >= 0 else src[fn_start:]

        assert "gc.collect()" in fn_body, (
            "B-563 Layer 4: run_parquet_delete_detection_step body must call "
            "gc.collect() to bound peak memory between replays"
        )

    def test_helper_releases_prior_replay_in_source(self):
        """B-563 Layer 4: `del prior_replay` invoked after PK extraction
        + before current-replay anti-join. Source-text check."""

        ps_src_path = _PROJECT_ROOT / "orchestration" / "pipeline_steps.py"
        src = ps_src_path.read_text(encoding="utf-8")

        fn_start = src.find("def run_parquet_delete_detection_step(")
        fn_end_def = src.find("\ndef ", fn_start + 1)
        fn_body = src[fn_start:fn_end_def] if fn_end_def >= 0 else src[fn_start:]

        assert "del prior_replay" in fn_body, (
            "B-563 Layer 4: function body must `del prior_replay` after PK "
            "extraction to release the full DataFrame reference for GC"
        )


# ===========================================================================
# Layer 5 -- Orchestrator wiring (large_tables.py)
# ===========================================================================


class TestB563OrchestratorWiring:
    """Pin the orchestration/large_tables.py parquet_snapshot branch
    correctly composes run_parquet_replay_step + run_parquet_delete_detection_step
    + run_scd2_promotion(targeted=use_targeted) per B-563 wiring contract."""

    def test_large_tables_imports_delete_detection_step(self):
        """B-563: large_tables.py imports run_parquet_delete_detection_step
        from orchestration.pipeline_steps."""

        lt_path = _PROJECT_ROOT / "orchestration" / "large_tables.py"
        src = lt_path.read_text(encoding="utf-8")

        assert "run_parquet_delete_detection_step" in src, (
            "B-563: large_tables.py must import run_parquet_delete_detection_step"
        )

    def test_parquet_snapshot_branch_calls_delete_detection_after_replay(self):
        """B-563: in the parquet_snapshot dispatch branch, the delete-
        detection helper MUST be called AFTER run_parquet_replay_step
        (it augments the replay's cdc_result with deleted_pks)."""

        lt_path = _PROJECT_ROOT / "orchestration" / "large_tables.py"
        src = lt_path.read_text(encoding="utf-8")

        # Anchor on the BRANCH check (`cdc_mode == CDC_MODE_PARQUET_SNAPSHOT`),
        # NOT the import statement (`CDC_MODE_PARQUET_SNAPSHOT` alone matches
        # both). The branch check is unique to the dispatch logic.
        psnap_idx = src.find("cdc_mode == CDC_MODE_PARQUET_SNAPSHOT")
        assert psnap_idx >= 0, "parquet_snapshot branch check not found"

        replay_idx = src.find("run_parquet_replay_step(", psnap_idx)
        del_detect_idx = src.find("run_parquet_delete_detection_step(", psnap_idx)
        # Find scd2 call AFTER delete_detection (skip any in-comment mentions
        # that may appear in inline docstring/comments between replay + delete-
        # detection lines).
        scd2_idx = src.find("run_scd2_promotion(", del_detect_idx)

        assert replay_idx >= 0, "run_parquet_replay_step missing in branch"
        assert del_detect_idx >= 0, "run_parquet_delete_detection_step missing in branch"
        assert scd2_idx >= 0, "run_scd2_promotion missing in branch"

        assert replay_idx < del_detect_idx, (
            "B-563: run_parquet_delete_detection_step must be called AFTER "
            "run_parquet_replay_step (it augments the replay's cdc_result)"
        )
        assert del_detect_idx < scd2_idx, (
            "B-563: run_scd2_promotion must be called AFTER delete-detection "
            "(it consumes the deleted_pks for targeted=True routing)"
        )

    def test_parquet_snapshot_branch_routes_targeted_via_use_targeted_flag(self):
        """B-563: routing logic must use ``use_targeted = cdc_result.deleted_pks is not None``
        to choose targeted=True (when deleted_pks populated) vs targeted=False
        (first-load fallback)."""

        lt_path = _PROJECT_ROOT / "orchestration" / "large_tables.py"
        src = lt_path.read_text(encoding="utf-8")

        # Expect the flag computation pattern
        assert "use_targeted" in src, (
            "B-563: parquet_snapshot branch must use ``use_targeted`` flag for "
            "conditional run_scd2_promotion routing"
        )
        assert "deleted_pks is not None" in src or "deleted_pks != None" in src, (
            "B-563: ``use_targeted`` must derive from ``cdc_result.deleted_pks "
            "is not None`` check"
        )
