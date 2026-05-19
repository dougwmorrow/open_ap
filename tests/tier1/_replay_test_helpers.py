"""Shared Tier 1 test helpers for orchestration apply-path tests.

Extracted from ``test_parquet_replay_step_apply_path.py`` per B-566 closure
2026-05-19 (3rd-event empirical anchor: B-563 large-table delete-detection
will need the same pattern; preemptive extraction avoids copy-paste at
B-563 closure).

Public surface:

* :data:`CANONICAL_REPLAY_KWARGS` — frozen tuple of the canonical
  keyword-only arg names for :func:`data_load.parquet_replay.replay_parquet_snapshot`.
  Pinned per source AST at ``data_load/parquet_replay.py`` L433-440.
* :func:`make_signature_validating_stub` — generic stub factory that
  mimics a function's keyword-only signature exactly. Calling with kwargs
  that don't match the configured canonical set raises ``TypeError``
  (same failure-mode the REAL function would have). This is the
  structural forward-prevention against the B-552 v1 MagicMock
  auto-attribute-accepts-anything failure class.
* :func:`extract_kwonly_arg_names_from_source` — AST-extract a function's
  keyword-only argument names from a source file. Avoids importing the
  real module (works on Windows dev workstations without polars dep per
  B-328). Pair this with a hardcoded ``CANONICAL_*`` constant + assert
  match → if real signature drifts, tests fail predictably.

Why a shared module instead of conftest.py:

conftest.py is auto-discovered by pytest for fixtures/hooks but explicit
imports of helpers from conftest are discouraged by convention. A regular
``_underscored.py`` module signals "not a test file" to pytest's
collection logic while remaining importable via standard
``from tests.tier1._replay_test_helpers import ...`` syntax.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Callable


# ---------------------------------------------------------------------------
# Canonical-signature pins (single source of truth for tests)
# ---------------------------------------------------------------------------

# Pinned 2026-05-19 per data_load/parquet_replay.py::replay_parquet_snapshot
# signature (B-552 v1 BLOCK remediation cohort at commit 0c06961). If the
# real signature changes, AST-validating tests will fail; update this
# constant AND all callers (orchestration/pipeline_steps.py) in lockstep
# with the source change.
CANONICAL_REPLAY_KWARGS: tuple[str, ...] = (
    "source_name",
    "table_name",
    "business_date",
    "original_batch_id",
    "replay_batch_id",
)


# ---------------------------------------------------------------------------
# Generic signature-validating stub factory
# ---------------------------------------------------------------------------

def make_signature_validating_stub(
    *,
    canonical_kwargs: tuple[str, ...],
    return_value=None,
) -> Callable:
    """Return a callable that mimics a keyword-only function's signature.

    Calling the returned stub with kwargs that don't match
    ``canonical_kwargs`` raises ``TypeError`` --- the SAME failure mode
    the REAL function would have. This is the structural
    forward-prevention against the B-552 v1 production-crash class:
    MagicMock auto-attribute generation accepts ANY kwargs silently,
    making test coverage falsely-positive when callers pass wrong
    kwargs.

    Generalized from B-564 closure (replay-specific helper) to support
    B-563 + future apply-path tests for other orchestration wrappers.

    :param canonical_kwargs: tuple of expected keyword-only arg names.
        Calls with any other set of kwargs raise TypeError.
    :param return_value: value returned on successful kwargs match.
        Default None.
    :returns: A callable usable as a ``MagicMock``-replacement that
        validates kwargs against the canonical contract.
    """

    expected = set(canonical_kwargs)

    def _stub(*args, **kwargs):
        if args:
            raise TypeError(
                f"signature-validating stub takes 0 positional arguments "
                f"but {len(args)} given"
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
                f"signature-validating stub kwargs mismatch: "
                f"{'; '.join(parts)}"
            )
        return return_value

    return _stub


# ---------------------------------------------------------------------------
# AST-based canonical signature extractor (no production import needed)
# ---------------------------------------------------------------------------

def extract_kwonly_arg_names_from_source(
    *,
    source_path: Path,
    function_name: str,
) -> tuple[str, ...]:
    """Parse a Python source file and return a function's keyword-only arg names.

    Does NOT import the source module --- pure AST parse via stdlib
    ``ast``. Works on Windows dev workstations without polars / pyodbc /
    oracledb deps (per B-328). Pair this with a hardcoded ``CANONICAL_*``
    constant + ``assert extracted == CANONICAL_*`` so the test fails
    predictably if the real signature drifts.

    :param source_path: absolute path to the source ``.py`` file.
    :param function_name: name of the function to inspect.
    :returns: tuple of keyword-only arg names in declaration order.
    :raises FileNotFoundError: source file absent.
    :raises LookupError: function not found in source file.
    """

    if not source_path.exists():
        raise FileNotFoundError(
            f"AST-extract: source file missing at {source_path}"
        )

    src = source_path.read_text(encoding="utf-8")
    tree = ast.parse(src)

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.FunctionDef)
            and node.name == function_name
        ):
            return tuple(arg.arg for arg in node.args.kwonlyargs)

    raise LookupError(
        f"AST-extract: function {function_name!r} not found in "
        f"{source_path}"
    )
