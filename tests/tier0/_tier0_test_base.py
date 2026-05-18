"""Shared Tier 0 scaffolding for CLI tool regression tests per B-469.

Forward-prevention infrastructure parallel to `_skill_test_base.py` (B-461).
Surfaced by `_skill_test_base.py` architectural design review:

> "Generalize `_skill_test_base.py` factory pattern → `_tier0_test_base.py`
>  for CLI tool baseline assertions. B-461 `_skill_test_base.py` factory
>  pattern (make_baseline_test_skill_exists + make_baseline_test_frontmatter_name)
>  is generic test-scaffolding infrastructure that could apply to other Tier 0
>  domains: `make_baseline_test_module_imports(module_name)` — pin module
>  import for all `tests/tier0/test_<tool>.py`; `make_baseline_test_event_type_constant
>  (module_name, expected)` — pin `EVENT_TYPE = "CLI_..."` per D76;
>  `make_baseline_test_exit_codes(module_name)` — pin `EXIT_SUCCESS/EXIT_FATAL`
>  per D74. Currently 24+ CLI tools each repeat these baseline assertions;
>  generalizing yields real LOC savings AND prevents silent drift (e.g., tool
>  dropping EXIT_FATAL constant silently)."

Usage pattern (callers — see future bulk-pin cohort for live examples):

    from tests.tier0._tier0_test_base import (
        make_baseline_test_module_imports,
        make_baseline_test_event_type_constant,
        make_baseline_test_exit_codes,
    )

    TOOL_MODULE = "tools.parquet_verify"
    EXPECTED_EVENT_TYPE = "CLI_PARQUET_VERIFY"

    # Generate baseline tests via factory calls
    test_module_imports = make_baseline_test_module_imports(TOOL_MODULE)
    test_event_type_constant = make_baseline_test_event_type_constant(
        TOOL_MODULE, EXPECTED_EVENT_TYPE,
    )
    test_exit_codes_canonical = make_baseline_test_exit_codes(TOOL_MODULE)

    # Tool-specific assertions on top
    def test_dry_run_short_circuits():
        ...

This module is INTERNAL test infrastructure — no public PRODUCTION API surface.
HOWEVER, per B-465 precedent applied to B-461 `_skill_test_base.py` (which IS
registered in GLOSSARY despite no production-code imports), the cross-test-module
public surface (REPO_ROOT + 3 factory functions) IS registered in `docs/migration/GLOSSARY.md`
per the B-474 cross-module-consumed criterion. The criterion REQUIRES registration
when the surface is intended for cross-test-module consumption (as docstring's
"Usage pattern" section above explicitly demonstrates).

Pin-canonical-text discipline preserved — tool-specific assertions still pin the
exact canonical strings; only the shared boilerplate (import + EVENT_TYPE +
EXIT_* constants) is factored.

Composes with `_skill_test_base.py` (B-461) as orthogonal domain scaffolding:
- `_skill_test_base.py` — SKILL.md regression tests (frontmatter + section pins)
- `_tier0_test_base.py` — CLI tool regression tests (module + EVENT_TYPE + exit codes)
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Callable


# Resolve repo root: tests/tier0/_tier0_test_base.py → tests/tier0/ → tests/ → repo
REPO_ROOT: Path = Path(__file__).resolve().parent.parent.parent

# Ensure repo root is importable (some pytest configurations don't add it)
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def make_baseline_test_module_imports(module_name: str) -> Callable:
    """Factory for `test_module_imports` baseline assertion per D67.

    Pins that the CLI tool module can be imported without error. Catches
    silent regressions where a tool module accumulates import-time
    dependencies that break collection on dev workstations OR where a
    module gets accidentally renamed/moved.

    Args:
        module_name: Fully-qualified dotted module path (e.g.
            "tools.parquet_verify"). Must be importable via importlib.

    Returns:
        A pytest test function. Caller assigns to module-level
        `test_module_imports` name so pytest discovers it.
    """
    def test_module_imports() -> None:
        """Assertion: CLI tool module imports cleanly (Tier 0 baseline)."""
        try:
            importlib.import_module(module_name)
        except Exception as exc:
            raise AssertionError(
                f"CLI tool module {module_name!r} failed to import: "
                f"{type(exc).__name__}: {exc}. "
                f"This is a Tier 0 baseline contract — module must be "
                f"importable without external dependencies (no live DB, "
                f"no live network, no production secrets)."
            ) from exc
    return test_module_imports


def make_baseline_test_event_type_constant(
    module_name: str,
    expected_event_type: str,
) -> Callable:
    """Factory for `test_event_type_constant` baseline assertion per D76.

    Pins the `EVENT_TYPE` module-level constant matches expected value.
    Per D76 audit-row contract — every CLI tool invocation writes exactly
    one PipelineEventLog row with `EventType=EVENT_TYPE`. Silent rename
    of the constant would break audit-trail consistency.

    Args:
        module_name: Fully-qualified dotted module path.
        expected_event_type: Canonical EVENT_TYPE string (e.g. "CLI_PARQUET_VERIFY").
            Must match the canonical CLI_* family registry at CLAUDE.md
            (per `check_cli_registry_sync` pre-commit check).

    Returns:
        A pytest test function. Caller assigns to module-level
        `test_event_type_constant` name so pytest discovers it.
    """
    def test_event_type_constant() -> None:
        """Assertion: EVENT_TYPE constant matches expected canonical value."""
        mod = importlib.import_module(module_name)
        assert hasattr(mod, "EVENT_TYPE"), (
            f"CLI tool module {module_name!r} must declare module-level "
            f"EVENT_TYPE constant per D76 audit-row contract."
        )
        actual = mod.EVENT_TYPE
        assert actual == expected_event_type, (
            f"CLI tool module {module_name!r} EVENT_TYPE drift detected: "
            f"actual={actual!r} expected={expected_event_type!r}. "
            f"D76 audit-row contract requires exact canonical value match "
            f"with CLAUDE.md CLI_* family registry."
        )
    return test_event_type_constant


def make_baseline_test_exit_codes(
    module_name: str,
    expected_exit_success: int = 0,
    expected_exit_fatal: int = 2,
) -> Callable:
    """Factory for `test_exit_codes_canonical` baseline assertion per D74.

    Pins that EXIT_SUCCESS and EXIT_FATAL module-level constants are declared
    with expected canonical values per D74 exit-code contract. Defaults
    match D74 canonical (SUCCESS=0; FATAL=2) but the parameters allow
    per-tool override since the project empirically has VARIANCE in
    EXIT_FATAL value across tools (e.g., `tools.query_blindspots` uses
    EXIT_FATAL=3 not 2). EXIT_OPERATIONAL_FAILURE (=1 for warning tier) is
    optional per-tool semantic and not pinned by this factory.

    Args:
        module_name: Fully-qualified dotted module path.
        expected_exit_success: Expected EXIT_SUCCESS value (default 0 per D74).
        expected_exit_fatal: Expected EXIT_FATAL value (default 2 per D74;
            override to 3 for tools.query_blindspots-style tools that use
            EXIT_FATAL=3 to disambiguate from EXIT_OPERATIONAL_FAILURE=1
            and EXIT_WARNING=2).

    Returns:
        A pytest test function. Caller assigns to module-level
        `test_exit_codes_canonical` name so pytest discovers it.
    """
    def test_exit_codes_canonical() -> None:
        """Assertion: EXIT_SUCCESS + EXIT_FATAL declared at expected values."""
        mod = importlib.import_module(module_name)
        assert hasattr(mod, "EXIT_SUCCESS"), (
            f"CLI tool module {module_name!r} must declare EXIT_SUCCESS "
            f"module-level constant per D74 exit-code contract."
        )
        assert mod.EXIT_SUCCESS == expected_exit_success, (
            f"CLI tool module {module_name!r} EXIT_SUCCESS drift: "
            f"actual={mod.EXIT_SUCCESS!r} expected={expected_exit_success!r} per D74."
        )
        assert hasattr(mod, "EXIT_FATAL"), (
            f"CLI tool module {module_name!r} must declare EXIT_FATAL "
            f"module-level constant per D74 exit-code contract."
        )
        assert mod.EXIT_FATAL == expected_exit_fatal, (
            f"CLI tool module {module_name!r} EXIT_FATAL drift: "
            f"actual={mod.EXIT_FATAL!r} expected={expected_exit_fatal!r} per D74."
        )
    return test_exit_codes_canonical
