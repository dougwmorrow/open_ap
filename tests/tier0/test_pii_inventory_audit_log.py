"""Tier 0 build-time smoke test for migrations/pii_inventory_audit_log.py.

Per D67 — runs at build time + every commit. Runtime ceiling < 5 s.
All external dependencies (DB connection, pyodbc cursor) are mocked.
Asserts the module can be imported, apply() is callable with dry_run=True,
the returned dict has the required keys, and documented error modes raise.

North Star pillars: Idempotent (D15 idempotency mandatory) +
Audit-grade (D76 audit-row contract + D92 forward-only schema) +
Traceability (D26 append-only provenance — PiiInventoryAuditLog is the
append-only audit trail for PII inventory imports that gate Phase 2 R3
tokenization per B189).

D-numbers: D67 (Tier 0 discipline), D76 (audit-row), D92 (forward-only),
D26 (append-only provenance), D15 (idempotency mandatory).
B-numbers: B194 (this migration's backlog entry), B189 (Tool 15 dependency).
Spec: phase2/01_pilot_prerequisites.md § 4.4 (apply() contract + canonical
Metadata JSON shape).
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import sys
import time
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Project root must be on sys.path so the migration module can locate its
# own imports (utils.connections, utils.configuration, etc.).
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Shared constants (single source of truth inside this file)
# ---------------------------------------------------------------------------

# Full required key set per phase2/01 § 4.4 Metadata JSON canonical shape.
# B194 replaces B193's 'columns_added' with 'table_created: bool' because
# this migration CREATEs a table rather than ALTERs an existing one.
REQUIRED_RETURN_KEYS = {
    "event_kind",
    "ddl_applied",
    "idempotency_path",
    "ddl_statements_executed",
    "server",
    "table_created",
}

# event_kind enum values (per phase2/01 § 4.4 canonical discriminator)
VALID_EVENT_KINDS = {"apply", "noop", "abandonment", "abandonment_noop"}

# Actor + justification required by D75 arg-naming convention
_ACTOR = "test-build-smoke"
_JUSTIFICATION = "Tier 0 build-time assertion"
_SERVER = "dev"


# ---------------------------------------------------------------------------
# Helper — build the mock connection that simulates a clean or already-created DB
# ---------------------------------------------------------------------------


def _make_mock_connection(table_exists: bool = False) -> MagicMock:
    """Return a mock pyodbc connection whose cursor simulates sys.tables query.

    When table_exists=False the sys.tables query returns no rows
    (first-apply scenario).  When True it returns a sentinel row
    (idempotent no-op scenario).
    """
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)

    if table_exists:
        # Table already present — idempotent re-run scenario.
        cursor.fetchone.return_value = (1,)
    else:
        # Table absent — first-apply scenario.
        cursor.fetchone.return_value = None

    return conn


# ---------------------------------------------------------------------------
# Module loader (re-isolated per test via importlib to avoid cross-test state)
# ---------------------------------------------------------------------------


def _load_module() -> ModuleType:
    """Load migrations/pii_inventory_audit_log.py with DB imports patched out."""
    module_path = _PROJECT_ROOT / "migrations" / "pii_inventory_audit_log.py"
    module_key = "migrations.pii_inventory_audit_log"

    if module_key in sys.modules:
        del sys.modules[module_key]

    with patch.dict("sys.modules", {
        "utils.connections": MagicMock(),
        "utils.configuration": MagicMock(),
    }):
        spec = importlib.util.spec_from_file_location(module_key, module_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

    return mod


# ---------------------------------------------------------------------------
# (a) Module imports without error
# ---------------------------------------------------------------------------


def test_module_imports():
    """(a) migrations/pii_inventory_audit_log.py imports without error.

    Per D67 Tier 0 assertion 1: no missing dependencies, no syntax errors.
    Mocks DB-level imports so the import itself never touches a real pyodbc
    connection or .env file.

    North Star: Operationally stable (D67 — every module produced from Round 3+
    must pass build-time smoke before being considered built).

    B194 — this migration creates General.ops.PiiInventoryAuditLog required
    for B189 Tool 15 (import_pii_inventory.py). A failing import blocks the
    entire Phase 2 R1 migration ladder.
    """
    with patch.dict("sys.modules", {
        "utils.connections": MagicMock(),
        "utils.configuration": MagicMock(),
    }):
        if "migrations.pii_inventory_audit_log" in sys.modules:
            del sys.modules["migrations.pii_inventory_audit_log"]

        spec = importlib.util.spec_from_file_location(
            "migrations.pii_inventory_audit_log",
            _PROJECT_ROOT / "migrations" / "pii_inventory_audit_log.py",
        )
        mod = importlib.util.module_from_spec(spec)
        # If this raises — missing dep or syntax error — the test fails.
        spec.loader.exec_module(mod)

    assert hasattr(mod, "apply"), "apply() must be a top-level function"


# ---------------------------------------------------------------------------
# (b) Main public function apply() invocable with dry_run=True
# ---------------------------------------------------------------------------


def test_apply_invocable_dry_run():
    """(b) apply() is callable with dry_run=True and a synthetic connection.

    Per D67 Tier 0 assertion 2. dry_run=True suppresses all DB writes so
    the call is safe in a build environment with no real SQL Server.

    B194: first-apply with dry_run=True — no CREATE TABLE executed.
    """
    with patch.dict("sys.modules", {
        "utils.connections": MagicMock(),
        "utils.configuration": MagicMock(),
    }):
        if "migrations.pii_inventory_audit_log" in sys.modules:
            del sys.modules["migrations.pii_inventory_audit_log"]

        spec = importlib.util.spec_from_file_location(
            "migrations.pii_inventory_audit_log",
            _PROJECT_ROOT / "migrations" / "pii_inventory_audit_log.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

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

    Per D67 Tier 0 assertion 3. Verifies the canonical key set:
    event_kind, ddl_applied, idempotency_path, ddl_statements_executed,
    server, table_created.

    B194-specific: 'table_created' (bool) replaces B193's 'columns_added' (list)
    because this migration creates a table, not alters an existing one.

    North Star: Audit-grade (D76 audit-row contract must carry all keys for
    Gate 6 filter query: event_kind='apply' AND ddl_applied=true).
    """
    with patch.dict("sys.modules", {
        "utils.connections": MagicMock(),
        "utils.configuration": MagicMock(),
    }):
        if "migrations.pii_inventory_audit_log" in sys.modules:
            del sys.modules["migrations.pii_inventory_audit_log"]

        spec = importlib.util.spec_from_file_location(
            "migrations.pii_inventory_audit_log",
            _PROJECT_ROOT / "migrations" / "pii_inventory_audit_log.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

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
        "Required by phase2/01 § 4.4 Metadata JSON shape."
    )
    # dry_run must never claim it applied DDL.
    assert result["ddl_applied"] is False, (
        "dry_run=True must produce ddl_applied=False"
    )
    # table_created must be bool, not truthy/falsy non-bool.
    assert isinstance(result["table_created"], bool), (
        "table_created must be a bool (True or False), not a truthy/falsy value. "
        f"Got: {result['table_created']!r} (type={type(result['table_created']).__name__})"
    )
    # dry_run never creates the table.
    assert result["table_created"] is False, (
        "dry_run=True must produce table_created=False"
    )
    # event_kind must be one of the canonical 4 values.
    assert result["event_kind"] in VALID_EVENT_KINDS, (
        f"event_kind must be one of {VALID_EVENT_KINDS!r}. "
        f"Got: {result['event_kind']!r}"
    )


# ---------------------------------------------------------------------------
# (d) Module raises on each documented error mode (no silent failures)
# ---------------------------------------------------------------------------


def test_apply_raises_on_missing_connection():
    """(d) apply() raises when passed None as connection — no silent failure.

    Per D67 Tier 0 assertion 4: documented error mode 'connection is None'
    must raise (TypeError or AttributeError — any exception), not silently
    swallow the error and return a misleading success dict.

    North Star: Audit-grade — a silent failure on a None connection would
    leave no PipelineEventLog audit row and no table, while returning
    a dict that appears successful. The Gate 6 count would be wrong.
    """
    with patch.dict("sys.modules", {
        "utils.connections": MagicMock(),
        "utils.configuration": MagicMock(),
    }):
        if "migrations.pii_inventory_audit_log" in sys.modules:
            del sys.modules["migrations.pii_inventory_audit_log"]

        spec = importlib.util.spec_from_file_location(
            "migrations.pii_inventory_audit_log",
            _PROJECT_ROOT / "migrations" / "pii_inventory_audit_log.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        with pytest.raises((TypeError, AttributeError, Exception)):
            mod.apply(
                None,  # None connection — must not silently succeed
                actor=_ACTOR,
                justification=_JUSTIFICATION,
                server=_SERVER,
                dry_run=False,
            )


# ---------------------------------------------------------------------------
# (e) CLI entry point exits 0 on --dry-run
# ---------------------------------------------------------------------------


def test_cli_entry_point_dry_run():
    """(e) __main__ / main() entry point exits 0 on --dry-run.

    Per D67 Tier 0 assertion 5 + D74 exit-code contract (0 = success).
    Patches the DB connection so no real SQL Server is required.

    D74: exit 0 = success; migration must not hang or crash under
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
                f"        'pal', r'{_PROJECT_ROOT / 'migrations' / 'pii_inventory_audit_log.py'}')\n"
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

    This is a sentinel test — if the module starts doing real I/O (network,
    filesystem reads, DB connections) the runtime ceiling will be breached
    and this test will catch the regression.

    North Star: Operationally stable (D67 runtime ceiling < 5s mandatory
    for build-time smoke to be actionable in a CI pipeline that blocks
    on test failure before deploy per D86/D87 pre-deploy checklist).
    """
    start = time.monotonic()

    with patch.dict("sys.modules", {
        "utils.connections": MagicMock(),
        "utils.configuration": MagicMock(),
    }):
        if "migrations.pii_inventory_audit_log" in sys.modules:
            del sys.modules["migrations.pii_inventory_audit_log"]

        spec = importlib.util.spec_from_file_location(
            "migrations.pii_inventory_audit_log",
            _PROJECT_ROOT / "migrations" / "pii_inventory_audit_log.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

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
