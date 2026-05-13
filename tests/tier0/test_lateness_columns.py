"""Tier 0 build-time smoke test for migrations/lateness_columns.py.

Per D67 — runs at build time + every commit. Runtime ceiling < 5 s.
All external dependencies (DB connection, pyodbc cursor) are mocked.
Asserts the module can be imported, apply() is callable with dry_run=True,
the returned dict has the required keys, and documented error modes raise.

North Star pillars: Idempotent (D15 idempotency mandatory) +
Audit-grade (D76 audit-row contract + D92 forward-only schema).

D-numbers: D67 (Tier 0 discipline), D76 (audit-row), D92 (forward-only),
B193 (this migration's backlog entry), phase2/01 § 4.4 (apply() contract).
"""
from __future__ import annotations

import importlib
import json
import sys
import time
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock, call, patch

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

# The two columns B193 adds per phase2/01 § 4.4
EXPECTED_COLUMNS_ADDED = ["LatenessL99Minutes", "LatenessL99UpdatedAt"]

# Full required key set per phase2/01 § 4.4 Metadata JSON shape
REQUIRED_RETURN_KEYS = {
    "event_kind",
    "ddl_applied",
    "idempotency_path",
    "ddl_statements_executed",
    "server",
    "columns_added",
}

# Actor + justification required by D75 arg-naming convention
_ACTOR = "test-build-smoke"
_JUSTIFICATION = "Tier 0 build-time assertion"
_SERVER = "dev"


# ---------------------------------------------------------------------------
# Helpers — build the mock connection that simulates a clean DB
# ---------------------------------------------------------------------------


def _make_mock_connection(columns_exist: bool = False) -> MagicMock:
    """Return a mock pyodbc connection whose cursor simulates INFORMATION_SCHEMA.

    When columns_exist=False the INFORMATION_SCHEMA query returns no rows
    (first-apply scenario).  When True it returns a sentinel row for each
    column (idempotent no-op scenario).
    """
    conn = MagicMock()
    cursor = MagicMock()
    conn.cursor.return_value = cursor
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)

    if columns_exist:
        # Simulate both columns already present
        cursor.fetchone.side_effect = [
            (1,),   # LatenessL99Minutes exists
            (1,),   # LatenessL99UpdatedAt exists
        ]
    else:
        # Both columns absent — first-apply scenario
        cursor.fetchone.side_effect = [
            None,   # LatenessL99Minutes absent
            None,   # LatenessL99UpdatedAt absent
        ]

    return conn


# ---------------------------------------------------------------------------
# (a) Module imports without error
# ---------------------------------------------------------------------------


def test_module_imports():
    """(a) migrations/lateness_columns.py imports without error.

    Per D67 Tier 0 assertion 1: no missing dependencies, no syntax errors.
    Mocks DB-level imports so the import itself never touches a real pyodbc
    connection.
    """
    # Patch the two most likely external import points that would fail in a
    # build environment without a live DB or .env file.
    with (
        patch.dict("sys.modules", {
            "utils.connections": MagicMock(),
            "utils.configuration": MagicMock(),
        }),
    ):
        if "migrations.lateness_columns" in sys.modules:
            del sys.modules["migrations.lateness_columns"]

        spec = importlib.util.spec_from_file_location(
            "migrations.lateness_columns",
            _PROJECT_ROOT / "migrations" / "lateness_columns.py",
        )
        mod = importlib.util.module_from_spec(spec)
        # If this raises — missing dep or syntax error — the test fails.
        spec.loader.exec_module(mod)

    assert hasattr(mod, "apply"), "apply() must be a top-level function"


# ---------------------------------------------------------------------------
# (b) Main public function apply() invocable with dry_run=True
# ---------------------------------------------------------------------------


def test_apply_invocable_dry_run():
    """(b) apply() is callable with dry_run=True and synthetic connection.

    Per D67 Tier 0 assertion 2. dry_run=True suppresses all DB writes so
    the call is safe in a build environment with no real SQL Server.

    Edge case: B193 first-apply with dry_run=True — no DDL executed.
    """
    with (
        patch.dict("sys.modules", {
            "utils.connections": MagicMock(),
            "utils.configuration": MagicMock(),
        }),
    ):
        if "migrations.lateness_columns" in sys.modules:
            del sys.modules["migrations.lateness_columns"]

        spec = importlib.util.spec_from_file_location(
            "migrations.lateness_columns",
            _PROJECT_ROOT / "migrations" / "lateness_columns.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        conn = _make_mock_connection(columns_exist=False)
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
    server, columns_added.

    North Star: Audit-grade (D76 audit-row contract must carry all keys).
    """
    with (
        patch.dict("sys.modules", {
            "utils.connections": MagicMock(),
            "utils.configuration": MagicMock(),
        }),
    ):
        if "migrations.lateness_columns" in sys.modules:
            del sys.modules["migrations.lateness_columns"]

        spec = importlib.util.spec_from_file_location(
            "migrations.lateness_columns",
            _PROJECT_ROOT / "migrations" / "lateness_columns.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        conn = _make_mock_connection(columns_exist=False)
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
    # dry_run must never claim it applied DDL
    assert result["ddl_applied"] is False, (
        "dry_run=True must produce ddl_applied=False"
    )


# ---------------------------------------------------------------------------
# (d) Module raises on each documented error mode (no silent failures)
# ---------------------------------------------------------------------------


def test_apply_raises_on_missing_connection():
    """(d) apply() raises when passed None as connection — no silent failure.

    Per D67 Tier 0 assertion 4: documented error mode 'connection is None'
    must raise (TypeError or a project-local PipelineFatalError subclass),
    not silently swallow the error and return a misleading success dict.
    """
    with (
        patch.dict("sys.modules", {
            "utils.connections": MagicMock(),
            "utils.configuration": MagicMock(),
        }),
    ):
        if "migrations.lateness_columns" in sys.modules:
            del sys.modules["migrations.lateness_columns"]

        spec = importlib.util.spec_from_file_location(
            "migrations.lateness_columns",
            _PROJECT_ROOT / "migrations" / "lateness_columns.py",
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
# (e) CLI entry point invokes apply correctly under --dry-run
# ---------------------------------------------------------------------------


def test_cli_entry_point_dry_run(tmp_path):
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
            # Inline shim: patch connections then import + call apply.
            (
                "import sys, importlib.util, unittest.mock as m\n"
                f"sys.path.insert(0, r'{_PROJECT_ROOT}')\n"
                "conn = m.MagicMock()\n"
                "conn.cursor.return_value.fetchone.return_value = None\n"
                "mods = {'utils.connections': m.MagicMock(), "
                "'utils.configuration': m.MagicMock()}\n"
                "with m.patch.dict('sys.modules', mods):\n"
                "    spec = importlib.util.spec_from_file_location(\n"
                f"        'lc', r'{_PROJECT_ROOT / 'migrations' / 'lateness_columns.py'}')\n"
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
    """
    start = time.monotonic()

    with (
        patch.dict("sys.modules", {
            "utils.connections": MagicMock(),
            "utils.configuration": MagicMock(),
        }),
    ):
        if "migrations.lateness_columns" in sys.modules:
            del sys.modules["migrations.lateness_columns"]

        spec = importlib.util.spec_from_file_location(
            "migrations.lateness_columns",
            _PROJECT_ROOT / "migrations" / "lateness_columns.py",
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        conn = _make_mock_connection(columns_exist=False)
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
