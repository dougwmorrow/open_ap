"""Verify Tier 0 smoke tests have not drifted from their target module interfaces.

Per D67 (build-time Tier 0 dummy-data smoke test) + R19 mitigation (Tier 0
drift risk) + B58 (this tool — Round 3 close-out spec).

This is a Round 3 INTERFACE SPEC (stub). The full implementation lands at
Round 6 deployment. Round 5 (Tests) authors the Tier 0 smoke tests themselves;
this tool keeps them aligned with module signatures as the modules evolve.

## What "drift" means

A Tier 0 smoke test imports a module function and invokes it with synthetic
dummy data. If the module's signature changes (parameter renamed, parameter
removed, return type changed) and the smoke test isn't updated, the smoke
test will either:
  1. Fail at import-time (broken reference) — caught immediately
  2. Pass against an old shape — silently masking the drift (the real R19)

This tool detects case (2): the smoke test still passes, but the module's
current signature doesn't match what the smoke test expects.

## Algorithm (interface; full impl in Round 6)

For each module in {data_load, cdc, scd2, schema, orchestration, observability,
extract, utils, tools}/*.py:
  1. Parse module source via ast.parse(); enumerate public functions /
     classes / their signatures
  2. Locate the corresponding tests/smoke/test_<module>.py
  3. If smoke test file absent: drift = MISSING_SMOKE (FATAL if module is
     post-D67-lock; INFO if pre-D67-lock per B55 backfill plan)
  4. Parse smoke test source; enumerate which module functions it imports +
     invokes
  5. For each smoke-test invocation:
       a. Confirm the function still exists in the module
       b. Confirm the smoke test's positional + keyword argument count + names
          align with the module's current signature
       c. Confirm the return-type assertion (if present) names a type that
          still exists in the module
  6. Aggregate drifts per module; emit ParityReport-style summary

## Exit codes
  0: no drift detected
  1: drift detected (one or more modules have smoke tests that no longer
     align with the module signature)
  2: tool error (file not parsable, etc.)

## Usage

  # Run in CI before Tier 1 stage:
  python3 tools/verify_tier0_drift.py

  # Run against a specific module subset (for fast feedback during dev):
  python3 tools/verify_tier0_drift.py --modules data_load/parquet_writer.py

  # Generate a JSON drift report for trend analysis:
  python3 tools/verify_tier0_drift.py --format json --out drift_report.json

## Integration with R19 mitigation

This tool's quarterly invocation feeds the R19 risk-register status (per
RISKS.md L26-27). Drift detected → R19 still 🟡; zero drift for 1+ quarter →
R19 candidate for closure.

## Stub status

This file is the Round 3 INTERFACE SPEC only. The full implementation includes:
  - ast.parse() for both module + smoke test
  - signature.bind() for argument validation
  - ParityReport dataclass for structured drift output
  - CLI argparse + JSON formatter
  - Per-module exemption list for pre-D67-lock backfill (B55 tracking)

Full implementation lands at Round 6 deployment as part of the CI tooling.
Until then, Tier 0 drift is honor-system + ad-hoc dev review.

## Cross-references

- D67: Tier 0 mandate
- D70: Test fixture strategy (Tier 0 is the first tier)
- R19: Tier 0 drift risk
- B55: Tier 0 backfill for § 1 + § 2 modules (close-out task — verifies these
  tests once authored)
- B57: udm-test-author skill template extended for Tier 0
- B58: This tool
- `phase1/03_core_modules.md` § 8.4: build-time discipline
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Literal


# Drift severity per check. Aligns with D65 parity drift classification.
DriftSeverity = Literal["fatal", "warning", "informational", "match"]


@dataclass(frozen=True)
class TierZeroDriftCheck:
    """One check result for one module / smoke-test pair."""

    module_path: str
    smoke_test_path: str | None  # None if missing
    function_name: str
    drift_type: Literal[
        "missing_smoke",
        "missing_function",
        "signature_mismatch",
        "return_type_mismatch",
        "match",
    ]
    severity: DriftSeverity
    detail: str  # human-readable explanation


@dataclass(frozen=True)
class TierZeroDriftReport:
    """Aggregate drift report across all modules."""

    checks: list[TierZeroDriftCheck]
    fatal_count: int
    warning_count: int
    informational_count: int
    match_count: int
    overall: Literal["pass", "warn", "fail"]


def verify_tier0_drift(
    *,
    module_root: str = ".",
    smoke_root: str = "tests/smoke",
    module_filter: list[str] | None = None,
    fail_on_warning: bool = False,
) -> TierZeroDriftReport:
    """Walk all modules; verify their Tier 0 smoke tests are still aligned.

    Args:
        module_root: root dir to walk for module .py files
        smoke_root: root dir for tests/smoke/test_*.py files
        module_filter: optional subset of module paths (for fast dev feedback)
        fail_on_warning: when True, warnings count as fatal

    Returns:
        TierZeroDriftReport with per-check drift status + overall verdict.

    Side effects:
        - Reads all module source files; no writes
        - Writes one ROW to PipelineEventLog when invoked from CI (EventType='TIER0_DRIFT_CHECK')

    Raises:
        FileNotFoundError: module_root doesn't exist
        SyntaxError: a module file has unparsable Python (genuine bug, not drift)
    """
    raise NotImplementedError(
        "Round 3 stub. Full implementation in Round 6 deployment. "
        "Until then, Tier 0 drift is verified ad-hoc during dev review. "
        "See B58 in BACKLOG.md."
    )


if __name__ == "__main__":
    import sys

    print("verify_tier0_drift.py: Round 3 stub (per B58).", file=sys.stderr)
    print("Full implementation deferred to Round 6 deployment.", file=sys.stderr)
    print("See phase1/03_core_modules.md § 8 + R19 + B58.", file=sys.stderr)
    sys.exit(2)
