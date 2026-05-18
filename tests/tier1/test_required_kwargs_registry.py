"""Tier 1 behavioral tests for tools/required_kwargs_registry.py per D67 + B-326.

Tier 1 (not Tier 0) because tests do directory traversal + file IO across
enforcement directories. Closes B-330 implicitly: the prior hardcoded test
`test_has_cascade_evidence_all_callers_pass_classification` in Tier 0 was
mis-tiered; this generalized version lives correctly in Tier 1.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))


def test_module_imports():
    """Assertion 1: module imports cleanly."""
    import tools.required_kwargs_registry  # noqa: F401


def test_public_surface_exports():
    """Assertion 2: public surface present."""
    import tools.required_kwargs_registry as rk
    assert hasattr(rk, "REQUIRED_KWARGS")
    assert hasattr(rk, "ENFORCEMENT_DIRS")
    assert hasattr(rk, "ScanResult")
    assert hasattr(rk, "scan_callers")
    assert hasattr(rk, "scan_all_registry_functions")


def test_required_kwargs_initial_entry():
    """Assertion 3: registry has expected initial entry (has_cascade_evidence)."""
    from tools.required_kwargs_registry import REQUIRED_KWARGS
    assert "has_cascade_evidence" in REQUIRED_KWARGS
    assert REQUIRED_KWARGS["has_cascade_evidence"] == ["classification"]


def test_enforcement_dirs_initial():
    """Assertion 4: enforcement dirs include tools/ + .claude/hooks/."""
    from tools.required_kwargs_registry import ENFORCEMENT_DIRS
    assert "tools" in ENFORCEMENT_DIRS
    assert ".claude/hooks" in ENFORCEMENT_DIRS


def test_scan_result_dataclass_shape():
    """Assertion 5: ScanResult dataclass has expected fields + is_clean()."""
    from tools.required_kwargs_registry import ScanResult
    r = ScanResult(function_name="foo", required_kwargs=["bar"])
    assert r.function_name == "foo"
    assert r.required_kwargs == ["bar"]
    assert r.violations == []
    assert r.files_scanned == 0
    assert r.is_clean() is True


def test_scan_callers_has_cascade_evidence_clean():
    """Assertion 6: scan_callers on has_cascade_evidence returns clean
    (no violations) — confirms the architectural contract B-326 enforces."""
    from tools.required_kwargs_registry import scan_callers
    result = scan_callers("has_cascade_evidence")
    assert result.is_clean(), (
        "has_cascade_evidence callers MUST pass classification= kwarg "
        f"per B-326 + B-321 architectural composition. Violations: {result.violations}"
    )
    assert result.files_scanned >= 2  # at minimum check_commit_msg + audit_cascade_compliance


def test_scan_callers_unknown_function_returns_empty():
    """Assertion 7: scan for function not in registry returns clean ScanResult."""
    from tools.required_kwargs_registry import scan_callers
    result = scan_callers("nonexistent_function_xyz")
    assert result.is_clean()
    assert result.required_kwargs == []


def test_scan_all_registry_functions_clean():
    """Assertion 8: every registered function passes scan_callers (compositional
    contract enforced across full registry)."""
    from tools.required_kwargs_registry import scan_all_registry_functions
    results = scan_all_registry_functions()
    violations_by_fn = {r.function_name: r.violations for r in results if not r.is_clean()}
    assert violations_by_fn == {}, (
        f"Compositional contract violations: {violations_by_fn}. "
        "All enforcement-pathway callers MUST pass required kwargs per registry."
    )


def test_scan_callers_skips_definer_module():
    """Assertion 9: scan_callers skips cascade_classifier.py (definer of
    has_cascade_evidence) — function definition + internal tests don't count
    as enforcement callers."""
    from tools.required_kwargs_registry import scan_callers
    result = scan_callers("has_cascade_evidence")
    for v in result.violations:
        assert "cascade_classifier.py" not in v.file


def test_scan_callers_skips_test_files():
    """Assertion 10: scan_callers skips test_*.py files (legitimate unit-test
    calls don't require enforcement kwargs)."""
    from tools.required_kwargs_registry import scan_callers
    result = scan_callers("has_cascade_evidence")
    for v in result.violations:
        assert "test_" not in v.file


def test_kwarg_violation_dataclass_shape():
    """Assertion 12 (per reviewer 🟡 IMPROVE): KwargViolation dataclass has
    expected fields for forward-extensibility (multi-kwarg cases)."""
    from tools.required_kwargs_registry import KwargViolation
    v = KwargViolation(file="x.py", line=42, function="foo", missing_kwarg="bar")
    assert v.file == "x.py"
    assert v.line == 42
    assert v.function == "foo"
    assert v.missing_kwarg == "bar"


@pytest.mark.parametrize("function_name", list(__import__("tools.required_kwargs_registry").required_kwargs_registry.REQUIRED_KWARGS.keys()))
def test_parametrized_registry_function_callers_clean(function_name):
    """Assertion 11+: per-registry-entry parametrized test (pytest reports
    per-function pass/fail visibility instead of monolithic batch result)."""
    from tools.required_kwargs_registry import scan_callers
    result = scan_callers(function_name)
    assert result.is_clean(), (
        f"Function `{function_name}` has compositional-drift violations: "
        f"{result.violations}. All enforcement-pathway callers in {result.enforcement_dirs} "
        f"MUST pass required kwargs {result.required_kwargs} per B-326 registry."
    )
