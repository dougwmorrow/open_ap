"""Tier 4 crash-injection tests - require Docker + multiprocessing-based SIGKILL orchestration.

Per docs/migration/06_TESTING.md "Tier 4 - Crash Injection" + docs/migration/phase1/05_tests.md
section 7 (Round 5 spec adds C11-C15 CLI-level crash boundaries).

Module-level skip pattern: each test file gates via ``docker_skip_marker()``
and ``crash_orchestration_skip_marker()`` from tests/crash/conftest.py -
skips with explicit reason on dev workstations without Docker Desktop OR
without crash-injection orchestration tooling (SIGKILL semantics on
Linux container; Windows ``signal.SIGTERM`` differs).

Tier 4 budget: 2 hours pre-release. NOT run in CI. Operator-driven manual cadence.

Canonical crash boundaries (per 06_TESTING.md):
  - C1-C10: module-level crash points (e.g., C2 = inflight Parquet, C7 = SCD2
    activation gap).
  - C11-C15: CLI-level crash boundaries added at Round 5 (per
    phase1/05_tests.md section 7.2).

Scaffold scope: 3 representative tests modules (C2, C7, C11) at scaffold-
landing; remaining 12 boundaries (C1, C3-C6, C8-C10, C12-C15) tracked in
follow-up B-N work.
"""
from __future__ import annotations
