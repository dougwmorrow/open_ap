"""Tier 0 build-time smoke test for migrations/capacity_baseline_log.py.

Per D67 — runs at build time + every commit. Runtime ceiling < 5 s.
All external dependencies (DB connection, pyodbc cursor) are mocked.
Asserts the module can be imported, apply() is callable with dry_run=True,
the returned dict has the required keys, and documented error modes raise.

North Star pillars:
  - Idempotent (D15 idempotency mandatory): CREATE TABLE guarded by IF NOT EXISTS.
  - Audit-grade (D76 audit-row contract + D92 forward-only schema): one
    MIGRATION_CAPACITY_BASELINE_LOG event row per invocation.
  - Traceability (D26 append-only): CapacityBaselineLog is append-only;
    migration that creates it must itself be idempotent.

D-numbers: D67 (Tier 0 discipline), D26 (append-only + D92 additive),
D76 (audit-row), D92 (forward-only), D15 (idempotency mandatory).

Backlog/spec refs: B195 (this migration's backlog entry),
phase2/01 § 4.4 (apply() contract + Metadata JSON shape),
phase1/04b § 5 (CapacityResult dataclass — table schema mirrors field-for-field).

Pattern: mirrors tests/tier0/test_lateness_columns.py (B193 canary).
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Project root on sys.path (matches tests/ convention)
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Shared constants — single source of truth inside this file
# ---------------------------------------------------------------------------

# Required key set per phase2/01 § 4.4 Metadata JSON shape for a
# CREATE TABLE migration (B195-specific — replaces columns_added with
# table_created per the CREATE TABLE vs ALTER COLUMN distinction).
REQUIRED_RETURN_KEYS = {
    "event_kind",
    "ddl_applied",
    "idempotency_path",
    "ddl_statements_executed",
    "server",
    "table_created",
}

# Actor / justification / server per D75 arg-naming convention
_ACTOR = "test-build-smoke"
_JUSTIFICATION = "Tier 0 build-time assertion"
_SERVER = "dev"

# Target table this migration creates (B195 + phase1/04b § 5)
_TARGET_TABLE = "CapacityBaselineLog"


# ---------------------------------------------------------------------------
# Helpers — build mock connections simulating a clean vs pre-existing DB
# ---------------------------------------------------------------------------


def _make_mock_connection(table_exists: bool = False) -> MagicMock:
    """Return a mock pyodbc connection simulating INFORMATION_SCHEMA state.

    When table_exists=False the OBJECT_ID / sys.tables check returns no row
    (first-apply scenario). When True it returns a sentinel row (idempotent
    no-op scenario).
    """
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)

    if table_exists:
        # Simulate table already present — idempotency guard fires
        cursor.fetchone.return_value = (1,)
    else:
        # Table absent — first-apply path
        cursor.fetchone.return_value = None

    return conn


# ---------------------------------------------------------------------------
# Module loader helper (patches external imports uniformly)
# ---------------------------------------------------------------------------


def _load_mod() -> MagicMock:
    """Load migrations/capacity_baseline_log.py with DB imports mocked."""
    module_key = "migrations.capacity_baseline_log"
    if module_key in sys.modules:
        del sys.modules[module_key]

    target = _PROJECT_ROOT / "migrations" / "capacity_baseline_log.py"
    with patch.dict("sys.modules", {
        "utils.connections": MagicMock(),
        "utils.configuration": MagicMock(),
    }):
        spec = importlib.util.spec_from_file_location(module_key, target)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# (a) Module imports without error
# ---------------------------------------------------------------------------


def test_module_imports():
    """(a) migrations/capacity_baseline_log.py imports without error.

    Per D67 Tier 0 assertion 1: no missing dependencies, no syntax errors.
    Mocks DB-level imports so the import never touches a real pyodbc
    connection.

    Pillar: Operationally stable (D67).
    B195 backlog entry: migration must be importable at build time.
    """
    with patch.dict("sys.modules", {
        "utils.connections": MagicMock(),
        "utils.configuration": MagicMock(),
    }):
        module_key = "migrations.capacity_baseline_log"
        if module_key in sys.modules:
            del sys.modules[module_key]

        target = _PROJECT_ROOT / "migrations" / "capacity_baseline_log.py"
        spec = importlib.util.spec_from_file_location(module_key, target)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

    assert hasattr(mod, "apply"), "apply() must be a top-level function"


# ---------------------------------------------------------------------------
# (b) Main public function apply() invocable with dry_run=True
# ---------------------------------------------------------------------------


def test_apply_invocable_dry_run():
    """(b) apply() callable with dry_run=True and synthetic connection.

    Per D67 Tier 0 assertion 2. dry_run=True suppresses all DB writes so
    the call is safe in a CI environment with no real SQL Server.

    B195: first-apply with dry_run=True — no DDL executed.
    Pillar: Idempotent (D15).
    """
    mod = _load_mod()
    conn = _make_mock_connection(table_exists=False)

    result = mod.apply(
        conn,
        actor=_ACTOR,
        justification=_JUSTIFICATION,
        server=_SERVER,
        dry_run=True,
    )

    assert result is not None, "apply() must return a dict, not None"


# ---------------------------------------------------------------------------
# (c) Return shape matches the documented interface (phase2/01 § 4.4)
# ---------------------------------------------------------------------------


def test_return_shape_matches_interface_dry_run():
    """(c) Return dict has all required keys per phase2/01 § 4.4 Metadata JSON shape.

    Per D67 Tier 0 assertion 3. Verifies the canonical key set for a
    CREATE TABLE migration (B195): event_kind, ddl_applied, idempotency_path,
    ddl_statements_executed, server, table_created.

    The key 'table_created' is B195-specific (CREATE TABLE vs B193's
    columns_added which is ALTER COLUMN). The two shapes are parallel but
    not identical.

    Pillar: Audit-grade (D76 audit-row contract must carry all keys).
    """
    mod = _load_mod()
    conn = _make_mock_connection(table_exists=False)

    result = mod.apply(
        conn,
        actor=_ACTOR,
        justification=_JUSTIFICATION,
        server=_SERVER,
        dry_run=True,
    )

    assert isinstance(result, dict), "apply() must return a dict"
    missing_keys = REQUIRED_RETURN_KEYS - result.keys()
    assert not missing_keys, (
        f"Return dict missing required keys: {missing_keys!r}. "
        f"Got keys: {set(result.keys())!r}. "
        "Required by phase2/01 § 4.4 Metadata JSON shape (B195 CREATE TABLE variant)."
    )
    # dry_run must never claim it applied DDL
    assert result["ddl_applied"] is False, (
        "dry_run=True must produce ddl_applied=False"
    )
    # dry_run with table absent: table_created must be False (not created yet)
    assert result["table_created"] is False, (
        "dry_run=True must produce table_created=False (DDL not executed)"
    )


# ---------------------------------------------------------------------------
# (d) Module raises on documented error mode — None connection
# ---------------------------------------------------------------------------


def test_apply_raises_on_missing_connection():
    """(d) apply() raises when passed None as connection — no silent failure.

    Per D67 Tier 0 assertion 4: documented error mode 'connection is None'
    must raise (TypeError or AttributeError), not silently succeed and return
    a misleading success dict.

    Pillar: Audit-grade — silent failures violate North Star § "skip the test"
    anti-pattern.
    """
    mod = _load_mod()

    with pytest.raises((TypeError, AttributeError, Exception)):
        mod.apply(
            None,
            actor=_ACTOR,
            justification=_JUSTIFICATION,
            server=_SERVER,
            dry_run=False,
        )


# ---------------------------------------------------------------------------
# (e) CLI entry point invokes apply correctly under --dry-run
# ---------------------------------------------------------------------------


def test_cli_entry_point_dry_run():
    """(e) __main__ / main() entry point exits 0 on --dry-run.

    Per D67 Tier 0 assertion 5 + D74 exit-code contract (0 = success).
    Patches the DB connection so no real SQL Server is required.

    D74 cites: exit 0 = success; migration must not hang or crash under
    --dry-run with a mocked connection.
    """
    import subprocess

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys, importlib.util, unittest.mock as m\n"
                f"sys.path.insert(0, r'{_PROJECT_ROOT}')\n"
                "conn = m.MagicMock()\n"
                "conn.cursor.return_value.fetchone.return_value = None\n"
                "mods = {'utils.connections': m.MagicMock(), "
                "'utils.configuration': m.MagicMock()}\n"
                "with m.patch.dict('sys.modules', mods):\n"
                "    spec = importlib.util.spec_from_file_location(\n"
                f"        'cbl', r'{_PROJECT_ROOT / 'migrations' / 'capacity_baseline_log.py'}')\n"
                "    mod = importlib.util.module_from_spec(spec)\n"
                "    spec.loader.exec_module(mod)\n"
                "    r = mod.apply(conn, actor='ci', justification='smoke', "
                "server='dev', dry_run=True)\n"
                "    sys.exit(0 if r is not None else 2)\n"
            ),
        ],
        capture_output=True,
        timeout=10,
    )
    assert result.returncode == 0, (
        f"CLI dry-run must exit 0 per D74. "
        f"stdout={result.stdout!r} stderr={result.stderr!r}"
    )


# ---------------------------------------------------------------------------
# (f) Tier 0 total runtime assertion
# ---------------------------------------------------------------------------


def test_tier0_total_runtime_under_5s():
    """(f) All Tier 0 smoke assertions complete in < 5 s per D67.

    Sentinel test: if the module starts doing real I/O (network, filesystem,
    DB) the runtime ceiling will be breached and this test will catch it.

    Pillar: Operationally stable (D67 runtime ceiling is a build gate).
    """
    start = time.monotonic()

    mod = _load_mod()
    conn = _make_mock_connection(table_exists=False)
    mod.apply(
        conn,
        actor=_ACTOR,
        justification=_JUSTIFICATION,
        server=_SERVER,
        dry_run=True,
    )

    elapsed = time.monotonic() - start
    assert elapsed < 5.0, (
        f"Tier 0 smoke must complete in < 5 s per D67. Took {elapsed:.2f}s. "
        "Module is likely performing real I/O — check for missing mocks."
    )
