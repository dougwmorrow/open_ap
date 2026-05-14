"""Hypothesis configuration for Tier 2 property tests per D81 + § 5.10.

Canonical reference (read verbatim per Step 11 — DELTA-B2 elevation 2026-05-14):
  docs/migration/phase1/05_tests.md § 5.10 — "Property-test budget (per D81 proposed)":
    - Default: ``max_examples=200`` per ``pytest.fixture(scope='session')``
      (consistent with pandas test suite which uses 100, slightly above
      SQLAlchemy's 50; per R5C1-5 advisory finding)
    - Combinatorial-heavy modules (CDC engine, SCD2 engine, transition state
      graphs): ``max_examples=1000`` (consistent with numpy test suite ceiling)
    - Shrinkage budget: ``deadline=timedelta(seconds=10)`` per example to
      prevent runaway
    - Pre-release: bump to ``max_examples=5000`` for the master idempotence
      property to find rare edge cases
    - **CI determinism**: Hypothesis profile in ``tests/conftest.py`` uses
      ``settings.register_profile('ci', derandomize=True, max_examples=200)``
      per R5C1-5 advisory — CI runs use derandomized profile so failures are
      reproducible across CI runs (avoids the "passed yesterday but failed
      today on the same code" Hypothesis trap); local dev uses default
      randomized profile for broader coverage

D-numbers: D81 (property-test budget), D67 (Tier 0 smoke discipline does not
apply here — Tier 2 may take longer per § 5.10), D92 (forward-only additive).
"""
from __future__ import annotations

from datetime import timedelta

from hypothesis import settings

# Default profile per D81 § 5.10: max_examples=200, deadline=10s
settings.register_profile(
    "default",
    max_examples=200,
    deadline=timedelta(seconds=10),
)

# CI profile per § 5.10 R5C1-5 advisory: derandomized for reproducibility
settings.register_profile(
    "ci",
    max_examples=200,
    deadline=timedelta(seconds=10),
    derandomize=True,
)

# Combinatorial-heavy modules (CDC engine, SCD2 engine, state graphs) per D81
settings.register_profile(
    "combinatorial",
    max_examples=1000,
    deadline=timedelta(seconds=10),
)

# Pre-release master invariant per D81 — exhaustive search for rare edges
settings.register_profile(
    "pre_release",
    max_examples=5000,
    deadline=timedelta(seconds=10),
)

# Default to 'default' profile; CI overrides via HYPOTHESIS_PROFILE env var.
settings.load_profile("default")
