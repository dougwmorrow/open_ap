"""Tier 1 test for B-498 + B-334 R1.3 — `source_verifier_fn` parameter.

Per Phase 2 large-tables plan v5 §5.1 R1.3 + D18 + CLAUDE.md Do-NOT rule
"Do NOT change CDC_VERIFY_STRICT_ON_FAILURE default from 1 to 0":

`scd2/engine.run_scd2{,_targeted}` accept an optional `source_verifier_fn`
keyword parameter. When provided, the closure is invoked on candidate
delete PKs BEFORE the Bronze delete-close UPDATE. STRICT-on-failure
semantic preserved: verifier raises + STRICT=1 → block ALL closes;
verifier raises + STRICT=0 → fallthrough (proceed with original set).

This test covers the helper `_apply_source_verifier_or_block` directly —
the verifier-hook insertion point in both run_scd2 + run_scd2_targeted
calls this helper, so testing it at the helper boundary covers both
public surfaces without needing to mock the entire SCD2 promotion path.

D-numbers consumed: D18 (verify-before-close moves to SCD2), D67 (Tier 1
discipline), D92 (forward-only additive — the parameter is new keyword
arg with None default, all existing callers compatible).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _import_scd2_engine():
    """Lazy import with sys.modules pre-patch for dev workstation isolation.

    `scd2/engine.py` transitively imports `polars`, `pyodbc`, etc. which
    may not be installed on Windows dev workstations (per CLAUDE.md
    B-328). Pre-patch sys.modules so the import succeeds + we can test
    the helper directly.
    """
    for missing in ("polars", "pyodbc", "configuration", "connectorx",
                    "oracledb", "polars_hash"):
        if missing not in sys.modules:
            sys.modules[missing] = MagicMock()
    # MagicMock chained attribute access provides what scd2.engine needs at
    # import time without requiring real polars to be installed.
    from scd2 import engine  # noqa: PLC0415
    return engine


# -----------------------------------------------------------------------------
# Fixture: minimal mock TableConfig for logger context (per helper docstring)
# -----------------------------------------------------------------------------


@pytest.fixture
def mock_table_config():
    tc = MagicMock()
    tc.source_name = "CCM"
    tc.source_object_name = "AuditLog"
    return tc


@pytest.fixture
def mock_pks_nonempty():
    """Mock Polars DataFrame with len()=3 + clear() method returning empty mock."""
    df = MagicMock()
    df.__len__ = lambda self: 3

    # When .clear() is called (STRICT-block path), return empty mock
    empty = MagicMock()
    empty.__len__ = lambda self: 0
    df.clear = MagicMock(return_value=empty)
    return df


@pytest.fixture
def mock_pks_empty():
    df = MagicMock()
    df.__len__ = lambda self: 0
    return df


# -----------------------------------------------------------------------------
# Helper contract — parameter signature
# -----------------------------------------------------------------------------


def test_run_scd2_accepts_source_verifier_fn_parameter():
    """B-498: run_scd2 signature includes source_verifier_fn keyword-only param."""
    engine = _import_scd2_engine()
    import inspect
    sig = inspect.signature(engine.run_scd2)
    assert "source_verifier_fn" in sig.parameters, (
        "run_scd2 must accept source_verifier_fn keyword parameter per B-498"
    )
    param = sig.parameters["source_verifier_fn"]
    assert param.kind == inspect.Parameter.KEYWORD_ONLY, (
        "source_verifier_fn must be KEYWORD_ONLY (after *,) per D92 additive"
    )
    assert param.default is None, (
        "source_verifier_fn must default to None per backward-compat contract"
    )


def test_run_scd2_targeted_accepts_source_verifier_fn_parameter():
    """B-498: run_scd2_targeted signature includes source_verifier_fn parameter."""
    engine = _import_scd2_engine()
    import inspect
    sig = inspect.signature(engine.run_scd2_targeted)
    assert "source_verifier_fn" in sig.parameters
    param = sig.parameters["source_verifier_fn"]
    assert param.kind == inspect.Parameter.KEYWORD_ONLY
    assert param.default is None


def test_helper_exists_with_canonical_name():
    """Helper `_apply_source_verifier_or_block` must exist for both engine paths to share."""
    engine = _import_scd2_engine()
    assert hasattr(engine, "_apply_source_verifier_or_block")


# -----------------------------------------------------------------------------
# Helper contract — semantic preservation
# -----------------------------------------------------------------------------


def test_helper_none_verifier_returns_input_unchanged(mock_pks_nonempty, mock_table_config):
    """When source_verifier_fn=None, helper is a no-op (returns input)."""
    engine = _import_scd2_engine()
    result = engine._apply_source_verifier_or_block(
        mock_pks_nonempty, None, ["ID"], mock_table_config,
    )
    assert result is mock_pks_nonempty


def test_helper_empty_input_skipped(mock_pks_empty, mock_table_config):
    """When candidate-delete-PKs is empty, helper returns it (no verifier call)."""
    engine = _import_scd2_engine()
    verifier = MagicMock()
    result = engine._apply_source_verifier_or_block(
        mock_pks_empty, verifier, ["ID"], mock_table_config,
    )
    assert result is mock_pks_empty
    verifier.assert_not_called()


def test_helper_verifier_called_with_candidate_pks(mock_pks_nonempty, mock_table_config):
    """When verifier provided + PKs non-empty, verifier IS called once with the PK DataFrame."""
    engine = _import_scd2_engine()
    verifier = MagicMock(return_value=None)  # None = caller uses original set
    engine._apply_source_verifier_or_block(
        mock_pks_nonempty, verifier, ["ID"], mock_table_config,
    )
    verifier.assert_called_once_with(mock_pks_nonempty)


def test_helper_verifier_returns_subset_used(mock_pks_nonempty, mock_table_config):
    """When verifier returns a DataFrame, helper uses the returned subset."""
    engine = _import_scd2_engine()
    subset = MagicMock()
    subset.__len__ = lambda self: 1
    verifier = MagicMock(return_value=subset)
    result = engine._apply_source_verifier_or_block(
        mock_pks_nonempty, verifier, ["ID"], mock_table_config,
    )
    assert result is subset


def test_helper_verifier_raises_strict_default_blocks_all(mock_pks_nonempty, mock_table_config, monkeypatch):
    """STRICT=1 (default) + verifier raises → block all closes (return empty df)."""
    engine = _import_scd2_engine()
    monkeypatch.delenv("CDC_VERIFY_STRICT_ON_FAILURE", raising=False)  # default is 1
    verifier = MagicMock(side_effect=RuntimeError("network failure"))
    result = engine._apply_source_verifier_or_block(
        mock_pks_nonempty, verifier, ["ID"], mock_table_config,
    )
    # STRICT-block path returns df.clear() which is mocked to len()=0
    assert len(result) == 0
    mock_pks_nonempty.clear.assert_called_once()


def test_helper_verifier_raises_strict_off_proceeds(mock_pks_nonempty, mock_table_config, monkeypatch):
    """STRICT=0 (explicit opt-out) + verifier raises → proceed with original set."""
    engine = _import_scd2_engine()
    monkeypatch.setenv("CDC_VERIFY_STRICT_ON_FAILURE", "0")
    verifier = MagicMock(side_effect=RuntimeError("network failure"))
    result = engine._apply_source_verifier_or_block(
        mock_pks_nonempty, verifier, ["ID"], mock_table_config,
    )
    # STRICT=0 fallthrough: original df unchanged
    assert result is mock_pks_nonempty
    # df.clear() NOT called per the STRICT=0 branch
    mock_pks_nonempty.clear.assert_not_called()


@pytest.mark.parametrize(
    "strict_value,expect_block",
    [
        ("1", True),     # canonical STRICT=1 → block
        ("true", True),  # alternate truthy
        ("TRUE", True),
        ("True", True),
        ("0", False),    # explicit opt-out → proceed
        ("false", False),
        ("False", False),
        ("FALSE", False),
        ("", False),     # empty string → opt-out per helper semantic
    ],
)
def test_helper_strict_env_var_parsing(
    mock_pks_nonempty, mock_table_config, monkeypatch, strict_value, expect_block,
):
    """STRICT env var parsing matches CLAUDE.md Do-NOT rule canonical semantic."""
    engine = _import_scd2_engine()
    monkeypatch.setenv("CDC_VERIFY_STRICT_ON_FAILURE", strict_value)
    verifier = MagicMock(side_effect=RuntimeError("network failure"))
    result = engine._apply_source_verifier_or_block(
        mock_pks_nonempty, verifier, ["ID"], mock_table_config,
    )
    if expect_block:
        assert len(result) == 0, f"STRICT={strict_value!r} should BLOCK all closes"
    else:
        assert result is mock_pks_nonempty, f"STRICT={strict_value!r} should PROCEED"


# -----------------------------------------------------------------------------
# Forward-prevention marker — extend when D2 cutover lands at R2
# -----------------------------------------------------------------------------
#
# When D2 cutover lands at R2 (per Phase 2 v5 plan §5.2 R2 deliverables):
#   * Orchestrator wires a real closure that calls
#     `cdc/source_verifier.py::verify_deletes_against_source`
#   * Closure receives candidate-delete PK list; queries source for each PK;
#     returns subset confirmed-deleted-on-source
#   * SCD2 uses the returned subset as the close set (false-positive deletes
#     filtered out)
#
# Extend this test file with:
#   * test_helper_with_real_verifier_closure: integration test via
#     subprocess against a Docker SQL Server fixture (Tier 3 boundary)
#   * test_e12_phantom_update_ratio_emission: per D18, E-12 phantom-update
#     ratio also moves to SCD2 layer; verify the metric lands in SCD2Result
#
# Until R2 ships, the tests above pin the helper's STRICT semantic.
