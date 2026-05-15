"""Shared test fixtures for Tier 3 + Tier 4 integration tests.

Canonical home per docs/migration/phase1/05_tests.md section 1.3 fixture
inventory.

Lives outside tests/integration/ + tests/crash/ so fixtures are reusable
across both tiers without duplication. Future contents will include:

  * ``schema.sql`` - canonical UDM DDL (subset of phase1/01_database_schema.md
    needed for integration tests; authored as a follow-up B-N).
  * ``seed_data.sql`` - canonical fixture row inserts (UdmTablesList, a small
    set of source tables, registry rows for replay tests; authored as a
    follow-up B-N).
  * Polars DataFrames + helper factories for synthetic data generation
    consumable by both Tier 3 (real DB) and Tier 4 (crash recovery).

For the B-115 scaffold landing, only this package marker exists; schema /
seed authoring is a downstream B-N tracked in BACKLOG.md.
"""
from __future__ import annotations
