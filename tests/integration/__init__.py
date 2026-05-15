"""Tier 3 integration tests - require Docker SQL Server fixture.

Per docs/migration/phase1/05_tests.md section 1.3 + section 6.2 + section 1.6
Tier 0/1 boundary discipline (Tier 0 = no Docker; Tier 3 = requires Docker).

Module-level skip pattern: each test file checks Docker availability via
the conftest fixture and skips with explicit reason when Docker unavailable.

Canonical container image (pinned per Round 6 section 7.10 / 4.5 / 5.4 / 8.10):
    mcr.microsoft.com/mssql/server:2022-CU14-ubuntu-22.04

State-leakage mitigation per section 1.3: SQLAlchemy-style transactional
rollback (BEGIN at fixture entry; ROLLBACK at test exit). Each function-
scope test runs inside its own transaction so concurrent reads of the
session-scope ``mssql_container`` do not see cross-test schema mutations.

B-115 closure: this package directory exists so pytest recognizes it
as a Python package; the canonical fixture set lives in
``tests/integration/conftest.py`` per section 1.3 spec.
"""
from __future__ import annotations
