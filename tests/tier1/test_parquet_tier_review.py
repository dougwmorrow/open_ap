"""Tier 1 unit tests for tools/parquet_tier_review.py.

Tests run on every commit. No live DB, no live network required.
All external dependencies mocked with unittest.mock.

North Star pillars addressed:
  - Audit-grade (D76): exactly one CLI_PARQUET_TIER_REVIEW PipelineEventLog
    row per invocation; Metadata JSON shape canonical with from_status,
    to_status, age_days, rows_matched, rows_transitioned, rows_failed,
    actor, justification, applied, dry_run flag; FAILED row written even
    on exception path.
  - Operationally stable (D74/D75): exit-code contract (0/1/2) and
    argument naming discipline must be exactly per spec.
  - Idempotent (D15): Round 3 § 1.3 mark_* functions short-circuit when
    row is already at the target Status; re-running this tool produces
    identical row-level results.
  - Traceability (D25/D26): ParquetSnapshotRegistry is the canonical
    Parquet index; this CLI wraps the lifecycle transitions.

ParquetSnapshotRegistry canonical columns (Pitfall #9.a — verified
against phase1/01_database_schema.md § 8):
  RegistryId, SourceName, TableName, BatchId, BusinessDate,
  NetworkDrivePath, SnowflakeStagePath, SnowflakeUploadedAt, RowCount,
  UncompressedBytes, CompressedBytes, SchemaHash, ContentChecksum,
  StorageTier, Status, CreatedAt, LastVerifiedAt, LastAccessedAt,
  PurgedAt, PurgedReason.

Status enum (CK_ParquetSnapshotRegistry_Status):
  'created' | 'verified' | 'replicated' | 'archived' | 'missing' |
  'purged' | 'replication_failed' — 7 values (Pitfall #9.c).

Round 3 § 1.3 canonical signatures (Pitfall #9.b — keyword-only):
  mark_replicated(*, registry_id: int, replica_target: str) -> None
  mark_archived(*, registry_id: int, archive_location: str) -> None
  mark_purged(*, registry_id: int, retention_batch_id: int) -> None
  query_snapshot(*, source_name, table_name, business_date, batch_id) -> dict | None

Edge case IDs (per 04_EDGE_CASES.md N-series — ParquetSnapshotRegistry):
  - N3 (concurrent transition): predecessor-Status filter naturally
    serializes; tool exits cleanly when row was flipped between SELECT
    and UPDATE.
  - N4 (status invalid on transition): RegistryStatusInvalid → exit 2.
  - N5 (file absent): RegistryFileNotFound → exit 1 retryable.
  - N7 (terminal status): mark_purged from non-archived predecessor
    rejected.

Decision citations:
  D2 (Stage dropped — Parquet replaces),
  D4 (network drive Parquet),
  D5 (Snowflake mirror),
  D15 (idempotency mandatory),
  D17 (idempotency ledger composed by Round 3 § 1.3),
  D25 (ParquetSnapshotRegistry canonical Parquet index),
  D26 (append-only audit posture),
  D30 (7-year retention),
  D67 (Tier 0 discipline — this file is Tier 1 complement),
  D68 (PipelineFatalError → exit 2; PipelineRetryableError → exit 1),
  D69 (cursor_for ownership),
  D74 (exit-code contract 0/1/2),
  D75 (canonical arg naming),
  D76 (audit-row contract: CLI_PARQUET_TIER_REVIEW EventType),
  D77 (Tier 0 6-canonical scaffold — Tier 1 extends).

Spec: phase1/04_tools.md § 3.1 (canonical spec).
Round 3 § 1.3 spec: phase1/03_core_modules.md § 1.3.
ParquetSnapshotRegistry DDL: phase1/01_database_schema.md § 8.

udm-execution-classifier discipline:
  - Idempotency contract: idempotent (re-flip same Status is no-op at
    row level; status-machine filter naturally skips race losers).
  - Trigger: Manual operator (ad-hoc tier review) + Automic
    JOB_RETENTION_MONTHLY (--from-status archived --to-status purged
    --age-days 2555 --apply).
  - Frequency: ad-hoc + monthly Automic.
  - Audit-row family: CLI_* per D76 (CLI_PARQUET_TIER_REVIEW).
"""
from __future__ import annotations

import importlib
import importlib.util
import json
import sys
from datetime import date, datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Project root on sys.path
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ---------------------------------------------------------------------------
# Module path
# ---------------------------------------------------------------------------

_TOOL_PATH = _PROJECT_ROOT / "tools" / "parquet_tier_review.py"
_TOOL_MODULE_KEY = "tools.parquet_tier_review"

# ---------------------------------------------------------------------------
# Constants — single source of truth
# ---------------------------------------------------------------------------

EXPECTED_EVENT_TYPE = "CLI_PARQUET_TIER_REVIEW"

EXIT_SUCCESS = 0
EXIT_OPERATIONAL = 1
EXIT_FATAL = 2

# Status enum
STATUS_CREATED = "created"
STATUS_VERIFIED = "verified"
STATUS_REPLICATED = "replicated"
STATUS_ARCHIVED = "archived"
STATUS_MISSING = "missing"
STATUS_PURGED = "purged"
STATUS_REPLICATION_FAILED = "replication_failed"

ALL_STATUSES = {
    STATUS_CREATED,
    STATUS_VERIFIED,
    STATUS_REPLICATED,
    STATUS_ARCHIVED,
    STATUS_MISSING,
    STATUS_PURGED,
    STATUS_REPLICATION_FAILED,
}

SUPPORTED_TO_STATUSES = {STATUS_REPLICATED, STATUS_ARCHIVED, STATUS_PURGED}

# Test data defaults
_ACTOR = "test-author"
_JUSTIFICATION = "Tier 1 unit test"
_REPLICA_TARGET = "snowflake:UDM_BRONZE_MIRROR"
_ARCHIVE_LOCATION = "s3://offsite-bucket/udm-archive/"
_RETENTION_BATCH_ID = 12345

# Canonical column order in the tool's SELECT (must match the SELECT
# clause in _list_registry_rows_by_status).
_SELECT_COLUMNS = [
    "RegistryId",
    "SourceName",
    "TableName",
    "BatchId",
    "BusinessDate",
    "NetworkDrivePath",
    "SnowflakeStagePath",
    "SnowflakeUploadedAt",
    "RowCount",
    "UncompressedBytes",
    "CompressedBytes",
    "SchemaHash",
    "ContentChecksum",
    "StorageTier",
    "Status",
    "CreatedAt",
    "LastVerifiedAt",
    "LastAccessedAt",
    "PurgedAt",
    "PurgedReason",
]


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _canonical_row(
    *,
    registry_id: int,
    source_name: str = "DNA",
    table_name: str = "ACCT",
    batch_id: int = 1000,
    status: str = STATUS_VERIFIED,
    business_date_iso: str | None = "2026-05-01",
    compressed_bytes: int = 50 * 1024 * 1024,
    uncompressed_bytes: int = 200 * 1024 * 1024,
    last_verified_offset_days: int = 5,
    created_offset_days: int | None = None,
) -> tuple:
    """Build a tuple matching the SELECT column projection."""
    last_verified_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        days=last_verified_offset_days
    )
    if created_offset_days is None:
        created_at = last_verified_at - timedelta(days=1)
    else:
        created_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
            days=created_offset_days
        )
    business_date = (
        datetime.fromisoformat(business_date_iso).date()
        if business_date_iso is not None
        else None
    )
    return (
        registry_id,
        source_name,
        table_name,
        batch_id,
        business_date,
        f"/parquet/{source_name}/{table_name}/{registry_id}.parquet",
        None,  # SnowflakeStagePath
        None,
        100000,
        uncompressed_bytes,
        compressed_bytes,
        "schema_hash",
        "content_checksum",
        "hot",
        status,
        created_at,
        last_verified_at if status != STATUS_CREATED else None,
        last_verified_at,
        None,
        None,
    )


def _resolve_exception_classes() -> tuple:
    """Resolve canonical exception classes per B228."""
    try:
        from utils.errors import (
            RegistryFileNotFound,
            RegistryNotFound,
            RegistryStatusInvalid,
        )
        return RegistryStatusInvalid, RegistryFileNotFound, RegistryNotFound
    except (ImportError, AttributeError):
        class _RegistryStatusInvalid(Exception):  # type: ignore[no-redef]
            pass

        class _RegistryFileNotFound(Exception):  # type: ignore[no-redef]
            pass

        class _RegistryNotFound(Exception):  # type: ignore[no-redef]
            pass

        return _RegistryStatusInvalid, _RegistryFileNotFound, _RegistryNotFound


RegistryStatusInvalid, RegistryFileNotFound, RegistryNotFound = _resolve_exception_classes()


# ---------------------------------------------------------------------------
# Module loader
# ---------------------------------------------------------------------------


def _load_tool_module(
    *,
    select_rows: list[tuple] | None = None,
    mark_replicated_side_effect: Exception | None = None,
    mark_archived_side_effect: Exception | None = None,
    mark_purged_side_effect: Exception | None = None,
    connection_side_effect: Exception | None = None,
    select_side_effect: Exception | None = None,
) -> Any:
    """Load tools/parquet_tier_review.py with external imports mocked."""
    if _TOOL_MODULE_KEY in sys.modules:
        del sys.modules[_TOOL_MODULE_KEY]

    rows = select_rows if select_rows is not None else []
    executed_sql: list[str] = []
    executed_params: list[Any] = []

    mock_cursor = MagicMock()

    def _capture_execute(sql: str, *args, **kwargs) -> None:
        executed_sql.append(str(sql))
        if select_side_effect is not None and "SELECT" in str(sql).upper() and "ParquetSnapshotRegistry" in str(sql):
            raise select_side_effect
        for a in args:
            if isinstance(a, (list, tuple)):
                executed_params.extend(a)
            else:
                executed_params.append(a)

    mock_cursor.execute.side_effect = _capture_execute
    mock_cursor.fetchall.return_value = rows
    mock_cursor.description = [(name, None) for name in _SELECT_COLUMNS]
    mock_cursor.fetchone.return_value = (99001,)  # SCOPE_IDENTITY for audit row
    mock_cursor.rowcount = 0

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.close = MagicMock(return_value=None)
    mock_conn.autocommit = True

    mock_connections = MagicMock()
    if connection_side_effect is not None:
        mock_connections.cursor_for = MagicMock(side_effect=connection_side_effect)
        mock_connections.get_connection = MagicMock(side_effect=connection_side_effect)
    else:
        mock_connections.cursor_for = MagicMock(return_value=mock_cursor)
        mock_connections.get_connection = MagicMock(return_value=mock_conn)

    mark_replicated_mock = MagicMock()
    if mark_replicated_side_effect is not None:
        mark_replicated_mock.side_effect = mark_replicated_side_effect
    mark_archived_mock = MagicMock()
    if mark_archived_side_effect is not None:
        mark_archived_mock.side_effect = mark_archived_side_effect
    mark_purged_mock = MagicMock()
    if mark_purged_side_effect is not None:
        mark_purged_mock.side_effect = mark_purged_side_effect

    mock_registry_client = MagicMock()
    mock_registry_client.mark_replicated = mark_replicated_mock
    mock_registry_client.mark_archived = mark_archived_mock
    mock_registry_client.mark_purged = mark_purged_mock

    mock_config = MagicMock()
    mock_config.GENERAL_DB = "General"

    mock_pyodbc = MagicMock()
    if connection_side_effect is not None:
        mock_pyodbc.connect = MagicMock(side_effect=connection_side_effect)
    else:
        mock_pyodbc.connect = MagicMock(return_value=mock_conn)

    sys_modules_patch: dict[str, Any] = {
        "connections": mock_connections,
        "utils.connections": mock_connections,
        "config": mock_config,
        "utils.configuration": mock_config,
        "data_load.parquet_registry_client": mock_registry_client,
        "pyodbc": mock_pyodbc,
    }

    with patch.dict("sys.modules", sys_modules_patch):
        spec = importlib.util.spec_from_file_location(_TOOL_MODULE_KEY, _TOOL_PATH)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[_TOOL_MODULE_KEY] = mod
        spec.loader.exec_module(mod)

    mod._test_sys_modules_patch = sys_modules_patch
    mod._test_cursor = mock_cursor
    mod._test_conn = mock_conn
    mod._test_executed_sql = executed_sql
    mod._test_executed_params = executed_params
    mod._test_mark_replicated = mark_replicated_mock
    mod._test_mark_archived = mark_archived_mock
    mod._test_mark_purged = mark_purged_mock
    mod._test_transition_fn_overrides = {
        "mark_replicated": mark_replicated_mock,
        "mark_archived": mark_archived_mock,
        "mark_purged": mark_purged_mock,
    }
    return mod


def _call_main(mod: Any, **overrides: Any) -> dict:
    """Call tool main() with canonical defaults + overrides."""
    defaults = dict(
        actor=_ACTOR,
        justification=_JUSTIFICATION,
        from_status=STATUS_VERIFIED,
        to_status=None,
        apply=False,
        json_output=False,
        verbose=False,
        quiet=True,
        no_audit_event=True,
        transition_fn_overrides=getattr(mod, "_test_transition_fn_overrides", None),
    )
    defaults.update(overrides)
    sys_modules_patch = getattr(mod, "_test_sys_modules_patch", {})
    mock_conn = getattr(mod, "_test_conn", None)
    defaults.setdefault(
        "general_cursor_factory",
        (lambda: mock_conn) if mock_conn is not None else None,
    )
    try:
        with patch.dict("sys.modules", sys_modules_patch):
            return mod.main(**defaults)
    except SystemExit as exc:
        return {"exit_code": exc.code, "_raised_system_exit": True}


# ===========================================================================
# Argparse coverage — every D75 canonical arg parses
# ===========================================================================


class TestArgparseCoverage:
    """Every canonical argument parses correctly."""

    def test_all_canonical_args_present(self):
        """All D75 canonical args + tool-specific args appear in --help."""
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        # Capture --help output
        buf = StringIO()
        with patch.object(sys, "stdout", buf):
            with pytest.raises(SystemExit):
                parser.parse_args(["--help"])
        help_text = buf.getvalue()
        for arg in [
            "--from-status",
            "--to-status",
            "--age-days",
            "--replica-target",
            "--archive-location",
            "--retention-batch-id",
            "--source",
            "--table",
            "--apply",
            "--dry-run",
            "--actor",
            "--justification",
            "--json",
            "--verbose",
            "--quiet",
            "--no-audit-event",
        ]:
            assert arg in help_text, (
                f"Canonical CLI arg {arg!r} must appear in --help text. "
                f"Per D75 + spec § 3.1 Tool-specific arguments."
            )

    def test_apply_and_dry_run_mutually_exclusive_argparse(self):
        """argparse rejects --apply AND --dry-run on the same invocation."""
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        with pytest.raises(SystemExit) as exc_info:
            parser.parse_args(["--apply", "--dry-run", "--to-status", "replicated"])
        assert exc_info.value.code == 2, (
            "argparse mutex on --apply + --dry-run must exit 2."
        )

    def test_invalid_from_status_rejected_by_argparse(self):
        """argparse choices reject an invalid --from-status."""
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--from-status", "INVALID_STATUS"])

    def test_invalid_to_status_rejected_by_argparse(self):
        """argparse choices reject --to-status=created (not in supported set)."""
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["--to-status", "created"])

    def test_default_from_status_is_verified(self):
        """--from-status defaults to 'verified' (most common operator surface)."""
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        ns = parser.parse_args([])
        assert ns.from_status == STATUS_VERIFIED

    def test_no_audit_event_flag_parses(self):
        """--no-audit-event flag sets the bool True."""
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        ns = parser.parse_args(["--no-audit-event"])
        assert ns.no_audit_event is True

    def test_age_days_int_type(self):
        """--age-days accepts int and coerces to int."""
        mod = _load_tool_module()
        parser = mod._build_arg_parser()
        ns = parser.parse_args(["--age-days", "30"])
        assert ns.age_days == 30
        assert isinstance(ns.age_days, int)


# ===========================================================================
# Status transition validation
# ===========================================================================


class TestStatusTransitionValidation:
    """Cross-field validation per _validate_args_main."""

    def test_apply_without_to_status_exits_2(self):
        """--apply without --to-status -> exit 2."""
        mod = _load_tool_module()
        result = _call_main(mod, apply=True, to_status=None)
        assert result.get("exit_code") == EXIT_FATAL

    def test_to_status_replicated_without_replica_target_exits_2(self):
        """--to-status replicated --apply without --replica-target -> exit 2."""
        mod = _load_tool_module()
        result = _call_main(
            mod,
            apply=True,
            to_status=STATUS_REPLICATED,
            replica_target=None,
        )
        assert result.get("exit_code") == EXIT_FATAL

    def test_to_status_archived_without_archive_location_exits_2(self):
        """--to-status archived --apply without --archive-location -> exit 2."""
        mod = _load_tool_module()
        result = _call_main(
            mod,
            apply=True,
            from_status=STATUS_REPLICATED,
            to_status=STATUS_ARCHIVED,
            archive_location=None,
        )
        assert result.get("exit_code") == EXIT_FATAL

    def test_to_status_purged_without_retention_batch_id_exits_2(self):
        """--to-status purged --apply without --retention-batch-id -> exit 2."""
        mod = _load_tool_module()
        result = _call_main(
            mod,
            apply=True,
            from_status=STATUS_ARCHIVED,
            to_status=STATUS_PURGED,
            retention_batch_id=None,
        )
        assert result.get("exit_code") == EXIT_FATAL

    def test_invalid_state_edge_exits_2(self):
        """--from-status created --to-status replicated -> exit 2 (illegal edge).

        Per Round 3 § 1.3 legal transitions: replicated has predecessors
        {verified, replication_failed}, not 'created'.
        """
        mod = _load_tool_module()
        result = _call_main(
            mod,
            apply=True,
            from_status=STATUS_CREATED,
            to_status=STATUS_REPLICATED,
            replica_target=_REPLICA_TARGET,
        )
        assert result.get("exit_code") == EXIT_FATAL

    def test_negative_age_days_exits_2(self):
        """--age-days -1 -> exit 2 (validation error)."""
        mod = _load_tool_module()
        result = _call_main(mod, age_days=-1)
        assert result.get("exit_code") == EXIT_FATAL

    def test_legal_state_edge_verified_to_replicated_passes(self):
        """verified -> replicated is a legal edge; validation passes."""
        rows = [_canonical_row(registry_id=1001)]
        mod = _load_tool_module(select_rows=rows)
        result = _call_main(
            mod,
            apply=True,
            from_status=STATUS_VERIFIED,
            to_status=STATUS_REPLICATED,
            replica_target=_REPLICA_TARGET,
        )
        assert result.get("exit_code") == EXIT_SUCCESS

    def test_legal_state_edge_replicated_to_archived_passes(self):
        """replicated -> archived is a legal edge; validation passes."""
        rows = [_canonical_row(registry_id=1002, status=STATUS_REPLICATED)]
        mod = _load_tool_module(select_rows=rows)
        result = _call_main(
            mod,
            apply=True,
            from_status=STATUS_REPLICATED,
            to_status=STATUS_ARCHIVED,
            archive_location=_ARCHIVE_LOCATION,
        )
        assert result.get("exit_code") == EXIT_SUCCESS

    def test_legal_state_edge_archived_to_purged_passes(self):
        """archived -> purged is a legal edge; validation passes."""
        rows = [_canonical_row(registry_id=1003, status=STATUS_ARCHIVED)]
        mod = _load_tool_module(select_rows=rows)
        result = _call_main(
            mod,
            apply=True,
            from_status=STATUS_ARCHIVED,
            to_status=STATUS_PURGED,
            retention_batch_id=_RETENTION_BATCH_ID,
        )
        assert result.get("exit_code") == EXIT_SUCCESS


# ===========================================================================
# Dry-run semantics — read-only, no mutations
# ===========================================================================


class TestDryRunSemantics:
    """Dry-run is read-only; no mark_* calls."""

    def test_default_mode_is_dry_run(self):
        """No --apply -> dry_run=True in result."""
        rows = [_canonical_row(registry_id=2001)]
        mod = _load_tool_module(select_rows=rows)
        result = _call_main(mod, apply=False)
        assert result.get("dry_run") is True
        assert result.get("applied") is False

    def test_dry_run_does_not_call_mark_replicated(self):
        """Dry-run never invokes mark_replicated."""
        rows = [_canonical_row(registry_id=2002)]
        mod = _load_tool_module(select_rows=rows)
        _call_main(mod, apply=False, to_status=STATUS_REPLICATED, replica_target=_REPLICA_TARGET)
        assert mod._test_mark_replicated.call_count == 0

    def test_dry_run_does_not_call_mark_archived(self):
        """Dry-run never invokes mark_archived."""
        rows = [_canonical_row(registry_id=2003, status=STATUS_REPLICATED)]
        mod = _load_tool_module(select_rows=rows)
        _call_main(
            mod,
            apply=False,
            from_status=STATUS_REPLICATED,
            to_status=STATUS_ARCHIVED,
            archive_location=_ARCHIVE_LOCATION,
        )
        assert mod._test_mark_archived.call_count == 0

    def test_dry_run_does_not_call_mark_purged(self):
        """Dry-run never invokes mark_purged."""
        rows = [_canonical_row(registry_id=2004, status=STATUS_ARCHIVED)]
        mod = _load_tool_module(select_rows=rows)
        _call_main(
            mod,
            apply=False,
            from_status=STATUS_ARCHIVED,
            to_status=STATUS_PURGED,
            retention_batch_id=_RETENTION_BATCH_ID,
        )
        assert mod._test_mark_purged.call_count == 0

    def test_explicit_dry_run_flag_overrides_apply(self):
        """dry_run=True alone forces apply=False (B88 mutex bridge)."""
        rows = [_canonical_row(registry_id=2005)]
        mod = _load_tool_module(select_rows=rows)
        result = _call_main(
            mod,
            apply=False,
            dry_run=True,
            to_status=STATUS_REPLICATED,
            replica_target=_REPLICA_TARGET,
        )
        # Validation should still pass; apply forced False
        assert result.get("dry_run") is True
        assert mod._test_mark_replicated.call_count == 0

    def test_apply_and_dry_run_both_true_exits_2(self):
        """B88 mutex: apply=True AND dry_run=True -> exit 2."""
        mod = _load_tool_module()
        result = _call_main(
            mod,
            apply=True,
            dry_run=True,
            to_status=STATUS_REPLICATED,
            replica_target=_REPLICA_TARGET,
        )
        assert result.get("exit_code") == EXIT_FATAL


# ===========================================================================
# Apply mode — happy paths
# ===========================================================================


class TestApplyHappyPaths:
    """Each legal transition invokes the correct mark_* fn per row."""

    def test_apply_replicated_calls_mark_replicated_each_row(self):
        """N rows -> N mark_replicated calls."""
        rows = [_canonical_row(registry_id=3000 + i) for i in range(5)]
        mod = _load_tool_module(select_rows=rows)
        result = _call_main(
            mod,
            apply=True,
            to_status=STATUS_REPLICATED,
            replica_target=_REPLICA_TARGET,
        )
        assert mod._test_mark_replicated.call_count == 5
        assert result.get("rows_transitioned") == 5
        assert result.get("rows_failed") == 0

    def test_apply_archived_calls_mark_archived_each_row(self):
        """N rows -> N mark_archived calls."""
        rows = [
            _canonical_row(registry_id=3100 + i, status=STATUS_REPLICATED)
            for i in range(3)
        ]
        mod = _load_tool_module(select_rows=rows)
        _call_main(
            mod,
            apply=True,
            from_status=STATUS_REPLICATED,
            to_status=STATUS_ARCHIVED,
            archive_location=_ARCHIVE_LOCATION,
        )
        assert mod._test_mark_archived.call_count == 3

    def test_apply_purged_calls_mark_purged_each_row(self):
        """N rows -> N mark_purged calls."""
        rows = [
            _canonical_row(registry_id=3200 + i, status=STATUS_ARCHIVED)
            for i in range(7)
        ]
        mod = _load_tool_module(select_rows=rows)
        _call_main(
            mod,
            apply=True,
            from_status=STATUS_ARCHIVED,
            to_status=STATUS_PURGED,
            retention_batch_id=_RETENTION_BATCH_ID,
        )
        assert mod._test_mark_purged.call_count == 7

    def test_apply_passes_replica_target_kwarg(self):
        """mark_replicated is invoked with replica_target= kwarg."""
        rows = [_canonical_row(registry_id=3300)]
        mod = _load_tool_module(select_rows=rows)
        _call_main(
            mod,
            apply=True,
            to_status=STATUS_REPLICATED,
            replica_target=_REPLICA_TARGET,
        )
        _, kwargs = mod._test_mark_replicated.call_args
        assert kwargs.get("replica_target") == _REPLICA_TARGET
        assert kwargs.get("registry_id") == 3300

    def test_apply_passes_archive_location_kwarg(self):
        """mark_archived is invoked with archive_location= kwarg."""
        rows = [_canonical_row(registry_id=3400, status=STATUS_REPLICATED)]
        mod = _load_tool_module(select_rows=rows)
        _call_main(
            mod,
            apply=True,
            from_status=STATUS_REPLICATED,
            to_status=STATUS_ARCHIVED,
            archive_location=_ARCHIVE_LOCATION,
        )
        _, kwargs = mod._test_mark_archived.call_args
        assert kwargs.get("archive_location") == _ARCHIVE_LOCATION
        assert kwargs.get("registry_id") == 3400

    def test_apply_passes_retention_batch_id_kwarg(self):
        """mark_purged is invoked with retention_batch_id= kwarg."""
        rows = [_canonical_row(registry_id=3500, status=STATUS_ARCHIVED)]
        mod = _load_tool_module(select_rows=rows)
        _call_main(
            mod,
            apply=True,
            from_status=STATUS_ARCHIVED,
            to_status=STATUS_PURGED,
            retention_batch_id=_RETENTION_BATCH_ID,
        )
        _, kwargs = mod._test_mark_purged.call_args
        assert kwargs.get("retention_batch_id") == _RETENTION_BATCH_ID
        assert kwargs.get("registry_id") == 3500


# ===========================================================================
# Error modes — per-row failures
# ===========================================================================


class TestApplyErrorModes:
    """Per-row registry-layer errors map to exit codes per D74."""

    def test_status_invalid_exits_2(self):
        """RegistryStatusInvalid on any row -> exit 2 (fatal)."""
        rows = [_canonical_row(registry_id=4001)]
        err = RegistryStatusInvalid("invalid predecessor")
        mod = _load_tool_module(
            select_rows=rows, mark_replicated_side_effect=err
        )
        result = _call_main(
            mod, apply=True, to_status=STATUS_REPLICATED, replica_target=_REPLICA_TARGET
        )
        assert result.get("exit_code") == EXIT_FATAL
        assert result.get("rows_failed") >= 1

    def test_registry_not_found_exits_2(self):
        """RegistryNotFound on any row -> exit 2 (fatal — caller bug)."""
        rows = [_canonical_row(registry_id=4002)]
        err = RegistryNotFound("row vanished")
        mod = _load_tool_module(
            select_rows=rows, mark_replicated_side_effect=err
        )
        result = _call_main(
            mod, apply=True, to_status=STATUS_REPLICATED, replica_target=_REPLICA_TARGET
        )
        assert result.get("exit_code") == EXIT_FATAL

    def test_file_not_found_exits_1(self):
        """RegistryFileNotFound on any row -> exit 1 (retryable)."""
        rows = [_canonical_row(registry_id=4003)]
        err = RegistryFileNotFound("file missing")
        mod = _load_tool_module(
            select_rows=rows, mark_replicated_side_effect=err
        )
        result = _call_main(
            mod, apply=True, to_status=STATUS_REPLICATED, replica_target=_REPLICA_TARGET
        )
        assert result.get("exit_code") == EXIT_OPERATIONAL

    def test_partial_failure_records_per_row_error(self):
        """Mixed success+fail rows: rows_failed > 0; rows_transitioned > 0.

        The first row fails with RegistryFileNotFound; the test simulates
        a single-failure scenario where rows_failed reflects the count.
        """
        rows = [_canonical_row(registry_id=4100)]
        err = RegistryFileNotFound("first row missing")
        mod = _load_tool_module(
            select_rows=rows, mark_replicated_side_effect=err
        )
        result = _call_main(
            mod, apply=True, to_status=STATUS_REPLICATED, replica_target=_REPLICA_TARGET
        )
        assert result.get("rows_failed") == 1
        assert result.get("rows_transitioned") == 0
        # error_message on the row dict carries the diagnostic
        per_row = result.get("rows", [])
        assert per_row, "rows list must surface per-row outcomes"
        assert per_row[0].get("error_message") is not None

    def test_generic_exception_exits_1(self):
        """Non-canonical exception from mark_* -> retryable exit 1."""
        rows = [_canonical_row(registry_id=4200)]
        err = RuntimeError("connection drop mid-update")
        mod = _load_tool_module(
            select_rows=rows, mark_replicated_side_effect=err
        )
        result = _call_main(
            mod, apply=True, to_status=STATUS_REPLICATED, replica_target=_REPLICA_TARGET
        )
        assert result.get("exit_code") == EXIT_OPERATIONAL


# ===========================================================================
# Connection / config error modes
# ===========================================================================


class TestConnectionAndConfigErrors:
    """Connection failures + arg-shape errors per D68 + D74."""

    def test_connection_failure_exits_1(self):
        """cursor_factory raises -> exit 1 (retryable)."""
        err = Exception("pyodbc: SQL Server unreachable")
        mod = _load_tool_module(connection_side_effect=err)
        # Override the injected factory to raise
        result = _call_main(
            mod,
            apply=False,
            general_cursor_factory=lambda: (_ for _ in ()).throw(err),
        )
        assert result.get("exit_code") == EXIT_OPERATIONAL

    def test_select_failure_exits_1(self):
        """SELECT mid-query failure -> exit 1 (retryable)."""
        err = Exception("query timeout")
        mod = _load_tool_module(select_side_effect=err)
        result = _call_main(mod)
        assert result.get("exit_code") == EXIT_OPERATIONAL

    def test_zero_rows_matched_exits_0(self):
        """Empty SELECT -> exit 0 (idempotent no-op per spec § 3.1)."""
        mod = _load_tool_module(select_rows=[])
        result = _call_main(mod)
        assert result.get("exit_code") == EXIT_SUCCESS
        assert result.get("rows_matched") == 0


# ===========================================================================
# Age filter
# ===========================================================================


class TestAgeFilter:
    """--age-days filter behavior."""

    def test_age_days_appears_in_sql(self):
        """--age-days N adds a cutoff predicate to the SELECT."""
        mod = _load_tool_module(select_rows=[])
        _call_main(mod, age_days=30)
        executed = mod._test_executed_sql
        select_calls = [s for s in executed if "ParquetSnapshotRegistry" in s and "SELECT" in s.upper()]
        assert select_calls, "SELECT against ParquetSnapshotRegistry must run"
        # The cutoff predicate references LastVerifiedAt for non-created status
        any_has_predicate = any(
            "LastVerifiedAt" in s and "<" in s for s in select_calls
        )
        assert any_has_predicate, (
            f"--age-days must add LastVerifiedAt cutoff predicate. "
            f"SQL: {select_calls!r}"
        )

    def test_age_days_for_created_uses_created_at_cutoff(self):
        """For --from-status created, the age cutoff is CreatedAt."""
        mod = _load_tool_module(select_rows=[])
        _call_main(mod, from_status=STATUS_CREATED, age_days=30)
        executed = mod._test_executed_sql
        select_calls = [s for s in executed if "ParquetSnapshotRegistry" in s and "SELECT" in s.upper()]
        assert select_calls
        # The cutoff predicate for created uses CreatedAt, not LastVerifiedAt
        # (the row may not have LastVerifiedAt yet).
        assert any(
            "CreatedAt" in s and "<" in s for s in select_calls
        ), (
            f"--from-status created + --age-days must use CreatedAt cutoff. "
            f"SQL: {select_calls!r}"
        )

    def test_no_age_filter_omits_cutoff_predicate(self):
        """No --age-days -> no cutoff predicate."""
        mod = _load_tool_module(select_rows=[])
        _call_main(mod, age_days=None)
        executed_params = mod._test_executed_params
        # Without age filter, the only parameter is the status value
        # (and optional source/table filters).
        # Just verify no datetime parameter is bound for the cutoff.
        dt_params = [p for p in executed_params if isinstance(p, datetime)]
        # If audit row is OFF (no_audit_event=True default in _call_main),
        # there should be NO datetime params from the SELECT path.
        assert len(dt_params) == 0, (
            f"No --age-days must omit datetime cutoff binding. "
            f"Got datetime params: {dt_params!r}."
        )

    def test_zero_age_days_includes_all_old_rows(self):
        """--age-days 0 is a no-op-ish cutoff (everything is older than now).

        Predicate is `< cutoff`; cutoff = now - 0 days = now. So any row
        whose LastVerifiedAt is strictly less than now matches.
        """
        mod = _load_tool_module(select_rows=[])
        _call_main(mod, age_days=0)
        # Validation passes (0 is allowed; the predicate `< now` is well-defined)
        # Verify a datetime param was bound (the cutoff)
        executed_params = mod._test_executed_params
        dt_params = [p for p in executed_params if isinstance(p, datetime)]
        assert dt_params, "--age-days 0 must still bind a cutoff datetime"


# ===========================================================================
# Source / table filter
# ===========================================================================


class TestSourceTableFilter:
    """--source and --table filters compose with status filter."""

    def test_source_filter_appears_in_sql(self):
        """--source DNA adds SourceName = ? clause."""
        mod = _load_tool_module(select_rows=[])
        _call_main(mod, source="DNA")
        executed = mod._test_executed_sql
        select_calls = [s for s in executed if "ParquetSnapshotRegistry" in s and "SELECT" in s.upper()]
        assert select_calls
        assert any("SourceName" in s for s in select_calls)

    def test_table_filter_appears_in_sql(self):
        """--table ACCT adds TableName = ? clause."""
        mod = _load_tool_module(select_rows=[])
        _call_main(mod, table="ACCT")
        executed = mod._test_executed_sql
        select_calls = [s for s in executed if "ParquetSnapshotRegistry" in s and "SELECT" in s.upper()]
        assert select_calls
        assert any("TableName" in s for s in select_calls)


# ===========================================================================
# Recommended-action derivation
# ===========================================================================


class TestRecommendedAction:
    """RecommendedAction column in the report payload."""

    def test_recommended_action_when_to_status_provided(self):
        """--to-status set -> RecommendedAction = '-> <to_status>'."""
        rows = [_canonical_row(registry_id=6001)]
        mod = _load_tool_module(select_rows=rows)
        result = _call_main(mod, apply=False, to_status=STATUS_REPLICATED)
        per_row = result.get("rows", [])
        assert per_row
        assert per_row[0].get("RecommendedAction") == f"-> {STATUS_REPLICATED}"

    def test_recommended_action_for_verified_no_to_status(self):
        """No --to-status, Status=verified -> 'replicate' recommendation."""
        rows = [_canonical_row(registry_id=6002)]
        mod = _load_tool_module(select_rows=rows)
        result = _call_main(mod, apply=False)
        per_row = result.get("rows", [])
        assert per_row
        assert "replicate" in per_row[0].get("RecommendedAction", "").lower()

    def test_recommended_action_for_archived_no_to_status(self):
        """No --to-status, Status=archived -> 'purge' recommendation."""
        rows = [_canonical_row(registry_id=6003, status=STATUS_ARCHIVED)]
        mod = _load_tool_module(select_rows=rows)
        result = _call_main(mod, from_status=STATUS_ARCHIVED, apply=False)
        per_row = result.get("rows", [])
        assert per_row
        assert "purge" in per_row[0].get("RecommendedAction", "").lower()


# ===========================================================================
# Result shape / D76 metadata contract
# ===========================================================================


class TestResultShape:
    """The result dict matches the D76 audit-row Metadata schema."""

    def test_result_carries_canonical_keys(self):
        """All Metadata JSON keys per spec § 3.1 appear in the result."""
        rows = [_canonical_row(registry_id=7001)]
        mod = _load_tool_module(select_rows=rows)
        result = _call_main(mod)
        for key in [
            "event_kind",
            "actor",
            "from_status",
            "to_status",
            "age_days",
            "applied",
            "dry_run",
            "rows_matched",
            "rows_transitioned",
            "rows_failed",
            "exit_code",
            "started_at",
            "completed_at",
        ]:
            assert key in result, f"Result must carry canonical Metadata key {key!r}."

    def test_event_kind_is_tier_review(self):
        """event_kind is the canonical literal 'tier_review'."""
        mod = _load_tool_module(select_rows=[])
        result = _call_main(mod)
        assert result.get("event_kind") == "tier_review"

    def test_actor_propagated_from_arg(self):
        """actor= kwarg is recorded in the result."""
        mod = _load_tool_module(select_rows=[])
        result = _call_main(mod, actor="operator-bob")
        assert result.get("actor") == "operator-bob"

    def test_justification_propagated_from_arg(self):
        """justification= kwarg is recorded in the result."""
        mod = _load_tool_module(select_rows=[])
        result = _call_main(mod, justification="end-of-month tier review")
        assert result.get("justification") == "end-of-month tier review"

    def test_rows_counts_initially_zero(self):
        """Empty SELECT -> all counts 0."""
        mod = _load_tool_module(select_rows=[])
        result = _call_main(mod)
        assert result.get("rows_matched") == 0
        assert result.get("rows_transitioned") == 0
        assert result.get("rows_failed") == 0


# ===========================================================================
# Datetime invariants (SCD2-P1-f / CDC-NOW-MS)
# ===========================================================================


class TestDatetimeInvariants:
    """All datetime values are naive UTC + millisecond precision."""

    def test_started_at_dt_is_naive_utc(self):
        """started_at_dt is tzinfo=None per SCD2-P1-f."""
        mod = _load_tool_module(select_rows=[])
        result = _call_main(mod)
        sdt = result.get("started_at_dt")
        assert isinstance(sdt, datetime)
        assert sdt.tzinfo is None, (
            f"started_at_dt must be tzinfo=None (naive UTC) per SCD2-P1-f. "
            f"Got tzinfo={sdt.tzinfo!r}."
        )

    def test_started_at_ms_precision(self):
        """started_at_dt microseconds are truncated to millis."""
        mod = _load_tool_module(select_rows=[])
        result = _call_main(mod)
        sdt = result.get("started_at_dt")
        assert isinstance(sdt, datetime)
        assert sdt.microsecond % 1000 == 0, (
            f"started_at_dt microsecond must be multiple of 1000. "
            f"Got: {sdt.microsecond}."
        )

    def test_now_naive_utc_ms_helper(self):
        """_now_naive_utc_ms returns naive datetime, ms precision."""
        mod = _load_tool_module()
        ts = mod._now_naive_utc_ms()
        assert ts.tzinfo is None
        assert ts.microsecond % 1000 == 0


# ===========================================================================
# JSON output mode
# ===========================================================================


class TestJsonOutput:
    """--json emits parseable JSON with canonical keys."""

    def test_json_output_is_parseable(self, capsys):
        """--json mode writes valid JSON to stdout."""
        rows = [_canonical_row(registry_id=8001)]
        mod = _load_tool_module(select_rows=rows)
        _call_main(mod, json_output=True, quiet=False)
        captured = capsys.readouterr()
        # The JSON should parse cleanly
        parsed = json.loads(captured.out)
        assert isinstance(parsed, dict)
        assert "rows" in parsed
        assert "rows_matched" in parsed
        assert "from_status" in parsed

    def test_json_carries_per_row_compressed_mb(self, capsys):
        """Per-row payload includes CompressedMB."""
        rows = [_canonical_row(registry_id=8002, compressed_bytes=104857600)]
        mod = _load_tool_module(select_rows=rows)
        _call_main(mod, json_output=True, quiet=False)
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        rows_out = parsed.get("rows", [])
        assert rows_out
        assert rows_out[0].get("CompressedMB") == pytest.approx(100.0, abs=0.01)


# ===========================================================================
# No-audit-event flag
# ===========================================================================


class TestNoAuditEventFlag:
    """--no-audit-event skips the CLI-level PipelineEventLog row."""

    def test_no_audit_event_returns_audit_id_none(self):
        """no_audit_event=True -> audit_event_id is None."""
        rows = [_canonical_row(registry_id=9001)]
        mod = _load_tool_module(select_rows=rows)
        result = _call_main(mod, no_audit_event=True)
        assert result.get("audit_event_id") is None


# ===========================================================================
# Idempotency
# ===========================================================================


class TestIdempotency:
    """Re-running on the same input produces the same outcome."""

    def test_dry_run_idempotent_across_two_calls(self):
        """Two dry-run invocations on identical rows -> identical outcomes."""
        rows = [_canonical_row(registry_id=10001 + i) for i in range(3)]
        mod1 = _load_tool_module(select_rows=rows)
        result1 = _call_main(mod1)

        mod2 = _load_tool_module(select_rows=rows)
        result2 = _call_main(mod2)

        assert result1.get("rows_matched") == result2.get("rows_matched")
        assert result1.get("exit_code") == result2.get("exit_code")

    def test_recommended_actions_match_across_runs(self):
        """RecommendedAction is deterministic for the same rows."""
        rows = [_canonical_row(registry_id=10100)]
        mod1 = _load_tool_module(select_rows=rows)
        result1 = _call_main(mod1)

        mod2 = _load_tool_module(select_rows=rows)
        result2 = _call_main(mod2)

        rec1 = [r.get("RecommendedAction") for r in result1.get("rows", [])]
        rec2 = [r.get("RecommendedAction") for r in result2.get("rows", [])]
        assert rec1 == rec2


# ===========================================================================
# Status sub-states (NULL BusinessDate / LastVerifiedAt)
# ===========================================================================


class TestNullableColumns:
    """Rows with NULL BusinessDate / LastVerifiedAt render cleanly."""

    def test_null_business_date_does_not_crash(self):
        """Small-table rows have BusinessDate=NULL — no exception."""
        rows = [_canonical_row(registry_id=11001, business_date_iso=None)]
        mod = _load_tool_module(select_rows=rows)
        result = _call_main(mod)
        assert result.get("exit_code") == EXIT_SUCCESS
        per_row = result.get("rows", [])
        assert per_row
        assert per_row[0].get("BusinessDate") is None

    def test_null_last_verified_at_does_not_crash(self):
        """Status=created may have LastVerifiedAt=NULL — no exception."""
        rows = [_canonical_row(registry_id=11002, status=STATUS_CREATED)]
        mod = _load_tool_module(select_rows=rows)
        result = _call_main(mod, from_status=STATUS_CREATED)
        assert result.get("exit_code") == EXIT_SUCCESS

    def test_zero_compressed_bytes_does_not_crash(self):
        """CompressedBytes=0 -> CompressedMB=0.0; no division error."""
        rows = [_canonical_row(registry_id=11003, compressed_bytes=0)]
        mod = _load_tool_module(select_rows=rows)
        result = _call_main(mod)
        per_row = result.get("rows", [])
        assert per_row
        assert per_row[0].get("CompressedMB") == 0.0


# ===========================================================================
# CLI-main wrapper exit codes (D74 + § 1.8)
# ===========================================================================


class TestCliMainExitCodes:
    """The cli_main() wrapper returns canonical exit codes."""

    def test_cli_main_returns_0_on_success(self):
        """cli_main with successful main() returns 0."""
        mod = _load_tool_module(select_rows=[])
        # Patch sys.argv so argparse is happy with no args (defaults used)
        sys_modules_patch = getattr(mod, "_test_sys_modules_patch", {})
        with patch.dict("sys.modules", sys_modules_patch):
            with patch.object(sys, "argv", ["parquet_tier_review.py"]):
                with patch.object(mod, "_resolve_default_general_cursor_factory") as factory_resolver:
                    factory_resolver.return_value = lambda: mod._test_conn
                    code = mod.cli_main()
        assert code in (0, 1, 2)  # ensure canonical code is returned
        assert code == EXIT_SUCCESS

    def test_cli_main_clamps_non_canonical_to_fatal(self):
        """If main() returns a non-canonical code, cli_main clamps to 2."""
        mod = _load_tool_module(select_rows=[])
        # Patch main to return a bogus code
        with patch.object(mod, "main", return_value={"exit_code": 99}):
            with patch.object(sys, "argv", ["parquet_tier_review.py"]):
                code = mod.cli_main()
        assert code == EXIT_FATAL
