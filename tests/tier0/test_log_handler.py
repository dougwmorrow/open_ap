"""Tier 0 smoke test for observability/log_handler.py per D67 + section 6.2.

<5 s runtime, pure / no external deps (utils.connections stubbed before import).

Per section 6.2 D67 Tier 0 contract:
  (a) module imports
  (b) handler accepts a LogRecord and writes via mocked cursor
  (c) WARNING record flushes immediately (mocked commit called)
  (d) set_log_context / clear_log_context affect subsequent emits

D-numbers: D67 (Tier 0), D31 (PipelineLog as audit-trail target),
P5 (SensitiveDataFilter installed by default), OBS-4, OBS-5.
B-numbers: M15 v2 cutover.
"""
from __future__ import annotations

import logging
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# utils.connections stub installed BEFORE observability.log_handler imports
# it. The real utils.connections requires pyodbc + configuration which
# Tier 0 isn't allowed to depend on. We DO NOT override the utils package
# itself -- only utils.connections -- so utils.errors / utils.cli_common /
# etc. remain importable from disk.
#
# The handler imports get_general_connection lazily inside _flush_buffer,
# so stubbing at sys.modules level is sufficient.
# ---------------------------------------------------------------------------

_MISSING = object()


def _snapshot_utils_connections_state():
    """Capture (sys.modules['utils.connections'], utils.connections attr) so
    they can be restored on test teardown. Sentinel `_MISSING` marks slots
    not present pre-install. Restoration is mandatory: M15 v1 left the stub
    in place across tests, breaking `patch('utils.connections.get_connection',
    ...)` in later tests because the stub module lacks the attribute the
    later tests need. Per B214 sys.modules registration discipline."""
    import utils  # noqa: F401  -- triggers real package init
    mod_before = sys.modules.get("utils.connections", _MISSING)
    attr_before = getattr(sys.modules["utils"], "connections", _MISSING)
    return mod_before, attr_before


def _restore_utils_connections_state(snapshot):
    """Restore sys.modules + utils package attr to the pre-install state."""
    mod_before, attr_before = snapshot
    if mod_before is _MISSING:
        sys.modules.pop("utils.connections", None)
    else:
        sys.modules["utils.connections"] = mod_before
    utils_pkg = sys.modules.get("utils")
    if utils_pkg is not None:
        if attr_before is _MISSING:
            try:
                delattr(utils_pkg, "connections")
            except AttributeError:
                pass
        else:
            utils_pkg.connections = attr_before


def _install_utils_connections_stub():
    """Replace utils.connections with a MagicMock module.

    Returns (mock_conn, mock_cursor) for assertion on captured calls.

    NOTE: Caller is responsible for restoring sys.modules state via
    _snapshot_utils_connections_state() / _restore_utils_connections_state()
    or via the `stub_connections` fixture which does this automatically.
    Direct test-method calls without restoration leak the stub into later
    tests and break their import-time patching (M15 v1 regression).
    """
    import utils  # noqa: F401  -- triggers real package init

    stub = types.ModuleType("utils.connections")
    mock_conn = MagicMock(name="general_conn")
    mock_cursor = MagicMock(name="cursor")
    mock_conn.cursor.return_value = mock_cursor
    stub.get_general_connection = MagicMock(return_value=mock_conn)
    stub._test_mock_conn = mock_conn
    stub._test_mock_cursor = mock_cursor
    sys.modules["utils.connections"] = stub
    # Bind as an attribute on the real utils package so
    # `from utils.connections import ...` resolves to the stub.
    sys.modules["utils"].connections = stub
    return mock_conn, mock_cursor


# ---------------------------------------------------------------------------
# Helpers.
# ---------------------------------------------------------------------------


def _make_record(msg="smoke", level=logging.INFO, *, name="test.module", func="test_func"):
    """Build a stand-in LogRecord for the handler's emit() input."""
    return logging.LogRecord(
        name=name,
        level=level,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=None,
        exc_info=None,
        func=func,
    )


@pytest.fixture
def clean_contextvars():
    """Reset contextvars before and after each test."""
    from observability.log_handler import clear_log_context

    clear_log_context()
    yield
    clear_log_context()


@pytest.fixture
def stub_connections():
    """Install / refresh the utils.connections stub for each test.

    Snapshots the pre-existing sys.modules state and restores it on teardown
    so the stub does not leak into later tests (M15 v1 regression fix per
    B214 sys.modules registration discipline)."""
    snapshot = _snapshot_utils_connections_state()
    mock_conn, mock_cursor = _install_utils_connections_stub()
    try:
        yield mock_conn, mock_cursor
    finally:
        _restore_utils_connections_state(snapshot)


# ---------------------------------------------------------------------------
# (a) module imports.
# ---------------------------------------------------------------------------


def test_module_imports():
    """D67 Tier 0 (a): module imports without error."""
    import observability.log_handler as mod

    assert mod is not None
    assert hasattr(mod, "SqlServerLogHandler")
    assert hasattr(mod, "set_log_context")
    assert hasattr(mod, "clear_log_context")


# ---------------------------------------------------------------------------
# (b) emit() writes via stubbed cursor.
# ---------------------------------------------------------------------------


def test_emit_writes_via_mocked_cursor(clean_contextvars, stub_connections):
    """D67 Tier 0 (b): buffer_size INFO records trigger one flush.

    One executemany call with buffer_size rows; one commit. Rows include
    BatchId / TableName / SourceName from contextvars.
    """
    from observability.log_handler import SqlServerLogHandler, set_log_context

    mock_conn, mock_cursor = stub_connections
    handler = SqlServerLogHandler()
    set_log_context(batch_id=42, table_name="ACCT", source_name="DNA")

    for i in range(handler._buffer_size):
        handler.emit(_make_record(msg=f"smoke {i}"))

    assert mock_cursor.executemany.call_count == 1
    args, _ = mock_cursor.executemany.call_args
    sql, rows = args
    assert "INSERT INTO ops.PipelineLog" in sql
    assert len(rows) == handler._buffer_size
    assert rows[0][0] == 42
    assert rows[0][1] == "ACCT"
    assert rows[0][2] == "DNA"
    assert rows[0][3] == "INFO"
    assert mock_conn.commit.call_count == 1


# ---------------------------------------------------------------------------
# (c) WARNING flushes immediately.
# ---------------------------------------------------------------------------


def test_warning_flushes_immediately(clean_contextvars, stub_connections):
    """D67 Tier 0 (c): A single WARNING record flushes immediately (OBS-4)."""
    from observability.log_handler import SqlServerLogHandler, set_log_context

    mock_conn, mock_cursor = stub_connections
    handler = SqlServerLogHandler()
    set_log_context(batch_id=7, table_name="X", source_name="Y")

    handler.emit(_make_record(msg="warn me", level=logging.WARNING))

    assert mock_cursor.executemany.call_count == 1
    args, _ = mock_cursor.executemany.call_args
    _sql, rows = args
    assert len(rows) == 1
    assert rows[0][3] == "WARNING"
    assert mock_conn.commit.call_count == 1


# ---------------------------------------------------------------------------
# (d) set_log_context / clear_log_context affect subsequent emits.
# ---------------------------------------------------------------------------


def test_context_set_and_clear_affect_emit(clean_contextvars):
    """D67 Tier 0 (d): clear_log_context() makes subsequent emits drop."""
    from observability.log_handler import (
        SqlServerLogHandler,
        clear_log_context,
        set_log_context,
    )

    handler = SqlServerLogHandler()

    handler.emit(_make_record(msg="orphan"))
    assert handler._buffer == []

    set_log_context(batch_id=1)
    handler.emit(_make_record(msg="kept"))
    assert len(handler._buffer) == 1
    assert handler._buffer[0][0] == 1

    handler._buffer.clear()

    clear_log_context()
    handler.emit(_make_record(msg="orphan-again"))
    assert handler._buffer == []


# ---------------------------------------------------------------------------
# P5 default-filter installation.
# ---------------------------------------------------------------------------


def test_default_filter_installed():
    """P5 invariant: SensitiveDataFilter (M14) is installed by default."""
    from observability.log_handler import SqlServerLogHandler
    from observability.sensitive_data_filter import SensitiveDataFilter

    handler = SqlServerLogHandler()
    assert any(isinstance(f, SensitiveDataFilter) for f in handler.filters), (
        "P5 invariant: SensitiveDataFilter must be installed by default"
    )


def test_install_default_filter_false_opts_out():
    """install_default_filter=False skips the M14 filter (advanced use)."""
    from observability.log_handler import SqlServerLogHandler
    from observability.sensitive_data_filter import SensitiveDataFilter

    handler = SqlServerLogHandler(install_default_filter=False)
    assert not any(
        isinstance(f, SensitiveDataFilter) for f in handler.filters
    ), "install_default_filter=False must skip M14 install"
