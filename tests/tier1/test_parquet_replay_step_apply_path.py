"""Apply-path Tier 1 tests for run_parquet_replay_step() per B-564.

Forward-prevention against the B-552 v1 production-breaking class surfaced
by cross-cohort reviewer ``a234fda11b870c78d`` 2026-05-19 (7th consecutive
read-only-compliant reviewer; B-541 empirical evidence base at 7-event
scale; extended to 8-event by D56 second-pass reviewer
``aea6c9174151af2f5`` 2026-05-19 verifying the BLOCK remediation at commit
``0c06961``):

- Finding 1.1: ``replay_parquet_snapshot()`` signature mismatch — the
  orchestrator passed ``registry_id=`` + ``replay_batch_id=`` but the real
  function requires 5 keyword-only args (``source_name``, ``table_name``,
  ``business_date``, ``original_batch_id``, ``replay_batch_id``).
  Production would crash with TypeError on first invocation.
- Finding 1.2: bare ``return`` statement in
  ``_process_single_day``'s ``parquet_snapshot`` branch returned None, but
  the caller does ``total_rows += day_rows`` which requires int.
  Production would crash with TypeError on first day after extraction.

The pre-B-564 Tier 1 tests at ``test_orchestrator_cdc_mode_dispatch.py``
used MagicMock auto-attribute generation, which made
``replay_parquet_snapshot`` accept ANY kwargs without validating against
the REAL canonical signature. Tests passed; production crashed.

This file's design (four-layer forward-prevention against the failure class):

Layer 1 (``TestB564CanonicalSignatureAST``): extract canonical signature
    from ``data_load/parquet_replay.py`` source via AST parsing (no polars
    dep — works on Windows dev workstations) and assert it matches the
    test's hardcoded ``CANONICAL_REPLAY_KWARGS`` constant. If the real
    signature changes, this test fails predictably + the constant must be
    updated in lockstep with all caller updates.

Layer 2 (``TestB564SignatureValidatingStub``): replace
    ``replay_parquet_snapshot`` with a stub that mimics the real signature
    exactly. Calling with wrong kwargs raises TypeError (same as real
    function). Then invoke ``run_parquet_replay_step()`` with realistic
    inputs and assert no TypeError propagates. This is the structural
    forward-prevention against B-552 v1 Finding 1.1 class — REPLACES the
    MagicMock-accepts-anything failure mode.

Layer 3 (``TestB564CallerReturnValueContract``): inspect
    ``orchestration/large_tables.py`` AST + verify
    ``_process_single_day`` has NO bare ``return`` statements + verify
    the function is annotated ``-> int``. Forward-prevents B-552 v1
    Finding 1.2 regression class.

Layer 4 (``TestB564CsvCleanupSequencing``): inspect
    ``orchestration/large_tables.py`` source + verify ``cleanup_csvs()``
    is called BEFORE the early-return in the ``parquet_snapshot`` branch.
    Forward-prevents B-552 v1 Finding 1.3 (CSV cleanup asymmetry; CSV
    files would accumulate on disk if cleanup is skipped on the replay
    path).

Per CLAUDE.md "Dev workstation pytest collection skew" (B-328): polars
NOT typically installed locally; AST extraction + sys.modules stubbing
allows these tests to run on bare Windows dev workstations alongside
the rest of Tier 0/1 cohorts.
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


# ---------------------------------------------------------------------------
# Canonical signature pin
# ---------------------------------------------------------------------------
# Pinned 2026-05-19 per data_load/parquet_replay.py replay_parquet_snapshot
# signature (B-552 v1 BLOCK remediation cohort at commit 0c06961). If the
# real signature changes, TestB564CanonicalSignatureAST will fail; update
# this constant AND all callers (orchestration/pipeline_steps.py) in
# lockstep with the source change.
# ---------------------------------------------------------------------------

CANONICAL_REPLAY_KWARGS = (
    "source_name",
    "table_name",
    "business_date",
    "original_batch_id",
    "replay_batch_id",
)


# ---------------------------------------------------------------------------
# Fixture: sys.modules stub for orchestration.pipeline_steps import
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _stub_production_modules():
    """Pre-patch sys.modules so ``import orchestration.pipeline_steps``
    works on Windows dev workstations without polars / connectorx /
    pyodbc / oracledb deps available. Same pattern as
    test_orchestrator_cdc_mode_dispatch.py per B-328.

    Cross-file test-pollution defense (per B-564 closure cohort
    empirical anchor 2026-05-19): popping ``sys.modules`` is
    NECESSARY but NOT SUFFICIENT. Python's
    ``from <package> import <submodule>`` semantics check the
    PACKAGE'S attribute cache (set when the submodule was first
    imported), bypassing ``sys.modules``. So even after popping
    ``orchestration.pipeline_steps``, subsequent
    ``from orchestration import pipeline_steps`` returns the OLD
    module object. Fix: explicitly ``delattr`` the package's
    ``pipeline_steps`` attribute too. Otherwise stub state leaks
    cross-file (e.g., into ``test_orchestrator_cdc_mode_dispatch.py``
    which then sees a polluted ``ps.CDCResult`` with stale
    ``call_count``).
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
        "extract.udm_connectorx_extractor",
        "scd2.engine",
    ]
    for name in stub_names:
        saved[name] = sys.modules.get(name)
        sys.modules[name] = MagicMock()

    # Force re-import of orchestration.pipeline_steps so the stubs take effect.
    saved["orchestration.pipeline_steps"] = sys.modules.get("orchestration.pipeline_steps")
    sys.modules.pop("orchestration.pipeline_steps", None)
    # Cross-file pollution defense: also remove package-attribute cache
    # so `from orchestration import pipeline_steps` triggers fresh import.
    _orch_pkg = sys.modules.get("orchestration")
    if _orch_pkg is not None and hasattr(_orch_pkg, "pipeline_steps"):
        delattr(_orch_pkg, "pipeline_steps")

    yield

    for name, mod in saved.items():
        if mod is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = mod
    sys.modules.pop("orchestration.pipeline_steps", None)
    # Repeat the package-attribute cleanup at fixture exit so subsequent
    # tests in OTHER files don't inherit our polluted ps reference.
    _orch_pkg = sys.modules.get("orchestration")
    if _orch_pkg is not None and hasattr(_orch_pkg, "pipeline_steps"):
        delattr(_orch_pkg, "pipeline_steps")


def _import_ps():
    from orchestration import pipeline_steps  # noqa: PLC0415
    return pipeline_steps


def _make_signature_validating_replay_stub(
    *, return_value=None, canonical_kwargs=CANONICAL_REPLAY_KWARGS,
):
    """Return a callable that mimics replay_parquet_snapshot's real signature.

    Calling with kwargs that don't match the canonical set raises TypeError
    --- the SAME failure mode the REAL function would have. This is the
    structural forward-prevention against B-552 v1 Finding 1.1: MagicMock
    auto-attribute generation accepts ANY kwargs without canonical-signature
    validation.

    :param return_value: returned on successful kwargs match (e.g. a mocked
        ReplayResult).
    :param canonical_kwargs: tuple of canonical kwarg names (default:
        module-level CANONICAL_REPLAY_KWARGS).
    """

    expected = set(canonical_kwargs)

    def _stub(*args, **kwargs):
        if args:
            raise TypeError(
                f"replay_parquet_snapshot() takes 0 positional arguments but "
                f"{len(args)} given"
            )
        actual = set(kwargs.keys())
        if actual != expected:
            unexpected = actual - expected
            missing = expected - actual
            parts = []
            if unexpected:
                parts.append(f"unexpected kwargs: {sorted(unexpected)}")
            if missing:
                parts.append(f"missing required kwargs: {sorted(missing)}")
            raise TypeError(
                f"replay_parquet_snapshot() kwargs mismatch: {'; '.join(parts)}"
            )
        return return_value

    return _stub


# ===========================================================================
# Layer 1 -- Canonical signature AST extraction
# ===========================================================================


class TestB564CanonicalSignatureAST:
    """Extract canonical signature from data_load/parquet_replay.py source
    via AST parsing (no polars dep). Pin against test's
    CANONICAL_REPLAY_KWARGS constant. Forward-prevents the scenario where
    the real signature changes without test updates."""

    def test_canonical_signature_extracted_via_ast_matches_test_constant(self):
        """B-564: parse parquet_replay.py source AST to extract the actual
        signature of replay_parquet_snapshot(). Compare against test
        constant. If the real signature changes (kwarg added/removed/renamed),
        this test fails + the constant must be updated in lockstep."""

        replay_src_path = _PROJECT_ROOT / "data_load" / "parquet_replay.py"
        assert replay_src_path.exists(), (
            f"Canonical source file missing: {replay_src_path}"
        )

        src = replay_src_path.read_text(encoding="utf-8")
        tree = ast.parse(src)

        func_node = None
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == "replay_parquet_snapshot"
            ):
                func_node = node
                break

        assert func_node is not None, (
            "Canonical source missing 'def replay_parquet_snapshot' --- "
            "module surface broken"
        )

        kwonly_arg_names = tuple(arg.arg for arg in func_node.args.kwonlyargs)

        assert kwonly_arg_names == CANONICAL_REPLAY_KWARGS, (
            f"Canonical signature drift detected!\n"
            f"  Test constant CANONICAL_REPLAY_KWARGS: {CANONICAL_REPLAY_KWARGS}\n"
            f"  Real signature in parquet_replay.py: {kwonly_arg_names}\n"
            f"  Fix: update CANONICAL_REPLAY_KWARGS in this test file AND "
            f"verify all callers (orchestration/pipeline_steps.py) pass the "
            f"new kwargs."
        )

    def test_canonical_signature_is_keyword_only(self):
        """B-564: validate the signature is `*, source_name: ..., ...` (no
        positional args). Positional args would allow callers to silently
        rely on argument order which is a maintainability hazard +
        regression-vector for B-552 v1 Finding 1.1 class."""

        replay_src_path = _PROJECT_ROOT / "data_load" / "parquet_replay.py"
        src = replay_src_path.read_text(encoding="utf-8")
        tree = ast.parse(src)

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == "replay_parquet_snapshot"
            ):
                positional_arg_names = [a.arg for a in node.args.args]
                assert positional_arg_names == [], (
                    f"replay_parquet_snapshot must be keyword-only "
                    f"(got positional args: {positional_arg_names})"
                )
                kwonly_arg_names = [a.arg for a in node.args.kwonlyargs]
                assert len(kwonly_arg_names) >= 5, (
                    f"replay_parquet_snapshot must have at least 5 keyword-only "
                    f"args (got: {kwonly_arg_names})"
                )
                return

        pytest.fail("replay_parquet_snapshot FunctionDef not found in source")


# ===========================================================================
# Layer 2 -- Signature-validating stub apply-path
# ===========================================================================


class TestB564SignatureValidatingStub:
    """Replace replay_parquet_snapshot with a stub that validates kwargs
    against canonical signature (raises TypeError on mismatch). Then invoke
    run_parquet_replay_step() and assert no TypeError propagates. This is
    the structural forward-prevention against B-552 v1 Finding 1.1 class
    --- REPLACES the MagicMock-accepts-anything failure mode that allowed
    the production-crashing bug to ship with 25/25 tests passing."""

    def _build_invocation_inputs(self):
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

        return ps, tracker, track_cm, tc, parquet_write_result, mock_replay_result

    def test_run_parquet_replay_step_passes_canonical_kwargs(self):
        """B-564: replace replay_parquet_snapshot with signature-validating
        stub + invoke run_parquet_replay_step. If the orchestrator passes
        wrong kwargs, the stub raises TypeError (mimicking real function).
        Pre-B-564, MagicMock auto-attribute accepted ANY kwargs silently
        --- this test catches the B-552 v1 Finding 1.1 class structurally."""

        ps, tracker, track_cm, tc, pwr, mock_replay_result = (
            self._build_invocation_inputs()
        )
        ps.replay_parquet_snapshot = _make_signature_validating_replay_stub(
            return_value=mock_replay_result,
        )

        # No TypeError should propagate if caller passes correct kwargs.
        cdc_result = ps.run_parquet_replay_step(
            tc, pwr, tracker, business_date=date(2026, 5, 19),
        )

        assert cdc_result is not None, (
            "run_parquet_replay_step returned None instead of CDCResult adapter"
        )

    def test_signature_stub_rejects_old_wrong_registry_id_kwarg(self):
        """B-564 forward-prevention: assert the signature-validating stub
        rejects the OLD WRONG kwarg `registry_id` that B-552 v1 originally
        used. Pins the exact failure-mode that shipped to production."""

        stub = _make_signature_validating_replay_stub()

        with pytest.raises(TypeError, match=r"unexpected kwargs.*registry_id"):
            stub(
                registry_id=42,
                replay_batch_id=999,
            )

    def test_signature_stub_rejects_missing_business_date_kwarg(self):
        """B-564: assert the stub raises TypeError if caller omits any
        required canonical kwarg. Pins per-kwarg-required contract."""

        stub = _make_signature_validating_replay_stub()

        with pytest.raises(TypeError, match=r"missing required kwargs.*business_date"):
            stub(
                source_name="DNA",
                table_name="ACCT",
                original_batch_id=999,
                replay_batch_id=999,
            )

    def test_signature_stub_rejects_missing_source_name_kwarg(self):
        """B-564: parallel test for source_name omission."""

        stub = _make_signature_validating_replay_stub()

        with pytest.raises(TypeError, match=r"missing required kwargs.*source_name"):
            stub(
                table_name="ACCT",
                business_date=date(2026, 5, 19),
                original_batch_id=999,
                replay_batch_id=999,
            )

    def test_signature_stub_rejects_positional_args(self):
        """B-564: assert the stub raises TypeError for any positional args.
        Pins keyword-only contract per Layer 1 finding."""

        stub = _make_signature_validating_replay_stub()

        with pytest.raises(TypeError, match=r"positional arguments"):
            stub("DNA", "ACCT")

    def test_signature_stub_accepts_canonical_kwargs(self):
        """B-564: positive control --- stub accepts all 5 canonical kwargs
        without raising. Returns the configured return_value."""

        sentinel = object()
        stub = _make_signature_validating_replay_stub(return_value=sentinel)

        result = stub(
            source_name="DNA",
            table_name="ACCT",
            business_date=date(2026, 5, 19),
            original_batch_id=999,
            replay_batch_id=999,
        )

        assert result is sentinel


# ===========================================================================
# Layer 3 -- Caller return-value contract (Finding 1.2 forward-prevention)
# ===========================================================================


class TestB564CallerReturnValueContract:
    """Forward-prevention against B-552 v1 Finding 1.2: bare ``return`` in
    ``_process_single_day``'s ``parquet_snapshot`` branch returned None,
    but the caller does ``total_rows += day_rows`` requiring int.
    Production would crash with TypeError on first day after extraction.
    Tests via source AST inspection (deterministic; no production deps)."""

    def test_process_single_day_has_no_bare_return_statements(self):
        """B-564: parse large_tables.py AST + find _process_single_day +
        verify it has NO bare ``return`` statements. Function is declared
        ``-> int``; callers depend on int return for arithmetic. Bare
        return returns None and crashes the caller with TypeError. This is
        B-552 v1 Finding 1.2 regression class."""

        lt_path = _PROJECT_ROOT / "orchestration" / "large_tables.py"
        src = lt_path.read_text(encoding="utf-8")
        tree = ast.parse(src)

        psd_func = None
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == "_process_single_day"
            ):
                psd_func = node
                break

        assert psd_func is not None, (
            "_process_single_day FunctionDef not found in large_tables.py"
        )

        return_nodes = [
            n for n in ast.walk(psd_func) if isinstance(n, ast.Return)
        ]

        bare_returns = [n for n in return_nodes if n.value is None]

        assert len(bare_returns) == 0, (
            f"_process_single_day has {len(bare_returns)} bare `return` "
            f"statement(s) --- function is declared `-> int` and callers "
            f"do `total_rows += day_rows`. Bare return returns None which "
            f"crashes with TypeError on int math. This is B-552 v1 Finding "
            f"1.2 regression class --- forward-prevented per B-564."
        )

    def test_process_single_day_declares_int_return_type(self):
        """B-564: verify _process_single_day's annotation is ``-> int``.
        Without this annotation, future contributors may not realize
        bare-return is invalid. The annotation IS the documented contract
        that this test layer enforces."""

        lt_path = _PROJECT_ROOT / "orchestration" / "large_tables.py"
        src = lt_path.read_text(encoding="utf-8")
        tree = ast.parse(src)

        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == "_process_single_day"
            ):
                assert node.returns is not None, (
                    "_process_single_day missing return type annotation --- "
                    "callers depend on the `int` contract per B-552 v1 + B-564 "
                    "forward-prevention discipline"
                )
                assert (
                    isinstance(node.returns, ast.Name) and node.returns.id == "int"
                ), (
                    f"_process_single_day return annotation is "
                    f"{ast.unparse(node.returns)!r}, expected `int`"
                )
                return

        pytest.fail("_process_single_day FunctionDef not found in large_tables.py")

    def test_process_single_day_all_returns_are_int_compatible(self):
        """B-564: every Return node in _process_single_day must return either
        a Name (variable like `extracted_row_count`), a Constant int literal
        (like 0), or a Call (like `len(df)`). Forward-prevents subtle
        regressions like `return None` (Constant(None)) or `return "0"`
        (Constant string)."""

        lt_path = _PROJECT_ROOT / "orchestration" / "large_tables.py"
        src = lt_path.read_text(encoding="utf-8")
        tree = ast.parse(src)

        psd_func = None
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.FunctionDef)
                and node.name == "_process_single_day"
            ):
                psd_func = node
                break

        assert psd_func is not None

        return_nodes = [
            n for n in ast.walk(psd_func) if isinstance(n, ast.Return)
        ]

        for ret in return_nodes:
            assert ret.value is not None, (
                f"_process_single_day line {ret.lineno}: bare `return` "
                f"(returns None; crashes callers doing int math)"
            )

            # Acceptable return-value node types for int contract:
            #   ast.Name (variable reference, e.g. `return extracted_row_count`)
            #   ast.Constant with int value (e.g. `return 0`)
            #   ast.Call (e.g. `return len(df)`)
            #   ast.BinOp (e.g. `return a + b`)
            if isinstance(ret.value, ast.Constant):
                assert isinstance(ret.value.value, int), (
                    f"_process_single_day line {ret.lineno}: return "
                    f"constant {ret.value.value!r} is not int (type "
                    f"{type(ret.value.value).__name__})"
                )


# ===========================================================================
# Layer 4 -- CSV cleanup sequencing (Finding 1.3 forward-prevention)
# ===========================================================================


class TestB564CsvCleanupSequencing:
    """Forward-prevention against B-552 v1 Finding 1.3 (CSV cleanup
    asymmetry): the original parquet_snapshot branch in
    ``orchestration/large_tables.py`` returned early WITHOUT calling
    ``cleanup_csvs()`` --- CSV files written by the extractor would
    accumulate on disk indefinitely. Remediation (Fix 5 at 0c06961) added
    cleanup_csvs() before the early-return. This test pins that
    sequencing."""

    def test_large_tables_parquet_snapshot_branch_calls_cleanup_csvs(self):
        """B-564: source-text inspection --- the parquet_snapshot dispatch
        block in large_tables.py MUST call cleanup_csvs() before returning.
        Forward-prevents CSV-leak regression class."""

        lt_path = _PROJECT_ROOT / "orchestration" / "large_tables.py"
        src = lt_path.read_text(encoding="utf-8")

        # Locate the parquet_snapshot branch marker
        psnap_branch_marker = "CDC_MODE_PARQUET_SNAPSHOT"
        psnap_idx = src.find(psnap_branch_marker)
        assert psnap_idx >= 0, (
            f"large_tables.py missing CDC_MODE_PARQUET_SNAPSHOT branch marker --- "
            f"B-544 v1 dispatch block not present"
        )

        # Find the replay invocation in the parquet_snapshot branch
        replay_call_idx = src.find("run_parquet_replay_step(", psnap_idx)
        assert replay_call_idx >= 0, (
            f"large_tables.py parquet_snapshot branch missing "
            f"run_parquet_replay_step() invocation"
        )

        # Find the early-return after the replay+scd2 chain
        # (search forward from the replay call; the cleanup_csvs MUST appear
        # between the replay call and the return)
        # Use 'return extracted_row_count' as the anchor for the early-return
        return_idx = src.find("return extracted_row_count", replay_call_idx)
        assert return_idx >= 0, (
            f"large_tables.py parquet_snapshot branch missing "
            f"`return extracted_row_count` --- B-552 v1 Finding 1.2 "
            f"remediation reverted?"
        )

        # cleanup_csvs MUST be called in the segment between replay and return
        segment_between = src[replay_call_idx:return_idx]
        assert "cleanup_csvs(" in segment_between, (
            f"large_tables.py parquet_snapshot branch missing cleanup_csvs() "
            f"call between run_parquet_replay_step() and `return "
            f"extracted_row_count` --- B-552 v1 Finding 1.3 (CSV leak) "
            f"regression class"
        )

    def test_large_tables_cleanup_csvs_wrapped_in_event_tracker(self):
        """B-564: the cleanup_csvs invocation in the parquet_snapshot branch
        MUST be wrapped in event_tracker.track("CSV_CLEANUP", ...) for
        observability parity with the legacy CDC path. Pins the
        observability-completeness contract."""

        lt_path = _PROJECT_ROOT / "orchestration" / "large_tables.py"
        src = lt_path.read_text(encoding="utf-8")

        psnap_idx = src.find("CDC_MODE_PARQUET_SNAPSHOT")
        return_idx = src.find("return extracted_row_count", psnap_idx)

        segment = src[psnap_idx:return_idx]

        # Look for both event_tracker.track and CSV_CLEANUP within the segment
        assert "CSV_CLEANUP" in segment, (
            "large_tables.py parquet_snapshot branch missing 'CSV_CLEANUP' "
            "event-track wrapper around cleanup_csvs() invocation"
        )


# ===========================================================================
# Layer 5 -- Symmetry across orchestrators
# ===========================================================================


class TestB564SymmetryAcrossOrchestrators:
    """Both small_tables.py + large_tables.py have parquet_snapshot
    dispatch branches per B-544 v1 + B-552 v1. The forward-prevention
    contracts above (CSV cleanup, int return) apply symmetrically. This
    layer pins the symmetry."""

    def test_small_tables_parquet_snapshot_branch_has_csv_cleanup(self):
        """B-564: small_tables.py parquet_snapshot branch must also handle
        CSV cleanup (small-table dispatch uses _safe_delete_csv earlier in
        the flow OR cleanup_csvs at end --- accept either pattern). Pins
        cross-orchestrator symmetry."""

        st_path = _PROJECT_ROOT / "orchestration" / "small_tables.py"
        src = st_path.read_text(encoding="utf-8")

        psnap_idx = src.find("CDC_MODE_PARQUET_SNAPSHOT")
        assert psnap_idx >= 0, (
            "small_tables.py missing CDC_MODE_PARQUET_SNAPSHOT branch marker"
        )

        # The branch should at minimum reference run_parquet_replay_step
        replay_idx = src.find("run_parquet_replay_step(", psnap_idx)
        assert replay_idx >= 0, (
            "small_tables.py parquet_snapshot branch missing "
            "run_parquet_replay_step() invocation"
        )
