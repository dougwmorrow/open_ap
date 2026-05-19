"""Tier 0 smoke test for utils/cli_common.py::write_cli_event_log_row (B-557).

Per D67 — runtime ceiling < 5s; all external dependencies mocked.

Asserts:
- Module imports cleanly + write_cli_event_log_row exported
- INSERT SQL matches canonical PipelineEventLog schema (per D76 audit-row contract)
- Optional kwargs (table_name + source_name) default to None for registry-wide invocations
- Metadata dict serialized as JSON (json.dumps)
- Status default = 'SUCCESS'; error_message default = None

Per CLAUDE.md "Dev workstation pytest collection skew" (B-328): production
deps mocked via sys.modules pre-patch.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest


_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


@pytest.fixture(autouse=True)
def _stub_modules():
    """Pre-patch sys.modules so ``import utils.cli_common`` works on Windows
    dev workstations without polars / connectorx / pyodbc / oracledb /
    observability deps available."""

    saved = {}
    stub_names = [
        "polars",
        "connectorx",
        "pyodbc",
        "oracledb",
        "polars_hash",
        "observability.log_handler",
    ]
    for name in stub_names:
        saved[name] = sys.modules.get(name)
        sys.modules[name] = MagicMock()

    saved["utils.cli_common"] = sys.modules.get("utils.cli_common")
    sys.modules.pop("utils.cli_common", None)
    # Cross-file pollution defense per B-567
    _utils_pkg = sys.modules.get("utils")
    if _utils_pkg is not None and hasattr(_utils_pkg, "cli_common"):
        delattr(_utils_pkg, "cli_common")

    yield

    for name, mod in saved.items():
        if mod is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = mod
    sys.modules.pop("utils.cli_common", None)
    _utils_pkg = sys.modules.get("utils")
    if _utils_pkg is not None and hasattr(_utils_pkg, "cli_common"):
        delattr(_utils_pkg, "cli_common")


def _import_cli_common():
    from utils import cli_common  # noqa: PLC0415
    return cli_common


# ---------------------------------------------------------------------------
# Class A — Module surface invariants
# ---------------------------------------------------------------------------


def test_b557_write_cli_event_log_row_exported():
    """B-557: write_cli_event_log_row must be exported from utils.cli_common."""
    cc = _import_cli_common()
    assert hasattr(cc, "write_cli_event_log_row")
    assert callable(cc.write_cli_event_log_row)


def test_b557_write_cli_event_log_row_is_keyword_only():
    """B-557: signature pin -- positional args (other than cursor) must raise."""
    cc = _import_cli_common()
    cursor = MagicMock()
    with pytest.raises(TypeError):
        # Try positional event_type (should be keyword-only)
        cc.write_cli_event_log_row(cursor, "CLI_TEST", "detail", {})


# ---------------------------------------------------------------------------
# Class B — INSERT execution behavior
# ---------------------------------------------------------------------------


def test_b557_writes_insert_to_pipeline_event_log():
    """B-557: helper executes a single INSERT into General.ops.PipelineEventLog
    with all canonical columns (BatchId / TableName / SourceName / EventType /
    EventDetail / StartedAt / CompletedAt / Status / ErrorMessage / Metadata)."""
    cc = _import_cli_common()
    cursor = MagicMock()
    cc.write_cli_event_log_row(
        cursor,
        event_type="CLI_TEST_TOOL",
        event_detail="test invocation",
        metadata={"actor": "test", "exit_code": 0},
    )
    cursor.execute.assert_called_once()
    call_args = cursor.execute.call_args
    sql = call_args[0][0]
    # Verify INSERT targets PipelineEventLog
    assert "INSERT INTO" in sql
    assert "ops.PipelineEventLog" in sql
    assert "PipelineBatchSequence" in sql  # BatchId auto-derived
    # Canonical column list present
    for col in ("BatchId", "TableName", "SourceName", "EventType",
                "EventDetail", "StartedAt", "CompletedAt", "Status",
                "ErrorMessage", "Metadata"):
        assert col in sql, f"Missing column {col!r} in INSERT SQL"


def test_b557_table_name_source_name_default_none():
    """B-557: optional table_name + source_name default to None for
    registry-wide invocations (per docstring contract)."""
    cc = _import_cli_common()
    cursor = MagicMock()
    cc.write_cli_event_log_row(
        cursor,
        event_type="CLI_TEST",
        event_detail="detail",
        metadata={},
    )
    # cursor.execute(sql, table_name, source_name, event_type, event_detail,
    #                status, error_message, metadata_json)
    call_args = cursor.execute.call_args
    args = call_args[0]
    # Position 1 = table_name; Position 2 = source_name
    assert args[1] is None
    assert args[2] is None


def test_b557_table_name_source_name_propagated_when_set():
    """B-557: when table_name + source_name provided, they propagate to
    INSERT parameters."""
    cc = _import_cli_common()
    cursor = MagicMock()
    cc.write_cli_event_log_row(
        cursor,
        event_type="CLI_TEST",
        event_detail="detail",
        metadata={},
        table_name="AuditLog",
        source_name="CCM",
    )
    args = cursor.execute.call_args[0]
    assert args[1] == "AuditLog"
    assert args[2] == "CCM"


def test_b557_metadata_serialized_as_json():
    """B-557: metadata dict serialized via json.dumps to Metadata column
    (last positional arg)."""
    cc = _import_cli_common()
    cursor = MagicMock()
    metadata = {"actor": "test", "exit_code": 0, "nested": {"k": "v"}}
    cc.write_cli_event_log_row(
        cursor,
        event_type="CLI_TEST",
        event_detail="detail",
        metadata=metadata,
    )
    args = cursor.execute.call_args[0]
    # Last positional arg = metadata JSON
    metadata_json = args[-1]
    parsed = json.loads(metadata_json)
    assert parsed == metadata


def test_b557_status_default_is_success():
    """B-557: status defaults to 'SUCCESS' when not provided."""
    cc = _import_cli_common()
    cursor = MagicMock()
    cc.write_cli_event_log_row(
        cursor,
        event_type="CLI_TEST",
        event_detail="detail",
        metadata={},
    )
    args = cursor.execute.call_args[0]
    # cursor.execute(sql, table_name, source_name, event_type, event_detail,
    #                status, error_message, metadata_json)
    # Position 5 = status (after table_name + source_name + event_type + event_detail)
    assert args[5] == "SUCCESS"


def test_b557_error_message_default_is_none():
    """B-557: error_message defaults to None when not provided."""
    cc = _import_cli_common()
    cursor = MagicMock()
    cc.write_cli_event_log_row(
        cursor,
        event_type="CLI_TEST",
        event_detail="detail",
        metadata={},
    )
    args = cursor.execute.call_args[0]
    # Position 6 = error_message
    assert args[6] is None


def test_b557_status_failed_with_error_message():
    """B-557: status='FAILED' + error_message both propagate."""
    cc = _import_cli_common()
    cursor = MagicMock()
    cc.write_cli_event_log_row(
        cursor,
        event_type="CLI_TEST",
        event_detail="detail",
        metadata={},
        status="FAILED",
        error_message="something broke",
    )
    args = cursor.execute.call_args[0]
    assert args[5] == "FAILED"
    assert args[6] == "something broke"
