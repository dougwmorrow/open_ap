"""Tier 0 build-time smoke test for tools/parquet_tier_review.py.

Per D67 — runs at build time + every commit. Runtime ceiling < 5 s.
All external dependencies mocked. No live DB, no live network required.

7-assertion D77-canonical scaffold per phase1/04_tools.md § 3.1:
  (a) Module imports without error.
  (b) --help exits 0 per D77 Tier 0 scaffold.
  (c) parser.parse_args(['--from-status', 'verified']) returns expected
      Namespace.
  (d) --apply without --to-status raises validation -> exit 2 per D74.
  (e) Mocked cursor returning 3 synthetic 'verified' rows + dry-run
      (no --to-status) returns exit 0, calls SELECT once, calls NO
      mark_* function.
  (f) Mocked mark_replicated raising RegistryStatusInvalid -> exit 2.
  (g) Mocked successful --apply --to-status replicated calls
      mark_replicated exactly 3 times (matching row count).
  Plus runtime assertion: total wall time < 5 s per D67.

North Star pillars:
  - Audit-grade (D76): ONE CLI_PARQUET_TIER_REVIEW PipelineEventLog row
    per invocation; Metadata JSON carries args, actor, justification,
    from_status, to_status, age_days, rows_matched, rows_transitioned,
    rows_failed, exit_code.
  - Operationally stable (D67 / D74): import + invoke + shape + error-modes
    in < 5 s with zero external I/O; exit-code contract 0/1/2 enforced.
  - Idempotent (D15): Round 3 § 1.3 mark_* functions short-circuit when
    row is already at the target Status; re-running this tool produces
    identical row-level results.
  - Traceability (D26): every invocation writes ONE PipelineEventLog row
    with EventType='CLI_PARQUET_TIER_REVIEW'; per-row transitions emit
    their own Round 3 § 1.3 events (PARQUET_REPLICATE etc.).

Canonical column verification (Pitfall #9.a + #9.f):
  ParquetSnapshotRegistry columns (Round 1 § 8 DDL):
    RegistryId, SourceName, TableName, BatchId, BusinessDate,
    NetworkDrivePath, SnowflakeStagePath, SnowflakeUploadedAt, RowCount,
    UncompressedBytes, CompressedBytes, SchemaHash, ContentChecksum,
    StorageTier, Status, CreatedAt, LastVerifiedAt, LastAccessedAt,
    PurgedAt, PurgedReason.
  Status enum (CK_ParquetSnapshotRegistry_Status):
    'created' | 'verified' | 'replicated' | 'archived' | 'missing' |
    'purged' | 'replication_failed' — 7 values.

Round 3 § 1.3 canonical signatures (Pitfall #9.b — strict):
  mark_replicated(*, registry_id: int, replica_target: str) -> None
  mark_archived(*, registry_id: int, archive_location: str) -> None
  mark_purged(*, registry_id: int, retention_batch_id: int) -> None

D-numbers: D2 (Stage dropped — Parquet replaces), D4 (network drive),
  D5 (Snowflake mirror), D15 (idempotency), D17 (ledger), D25 (canonical
  index), D26 (append-only), D30 (7-year retention), D67 (Tier 0 disc),
  D68 (error class hierarchy), D69 (cursor ownership), D74 (exit codes),
  D75 (CLI args), D76 (audit row contract), D77 (Tier 0 scaffold).

Independence note: tests/tier0/test_parquet_tier_review.py is authored
INDEPENDENTLY from tools/parquet_tier_review.py per D55 (5-gate validation
discipline — test author != code author conceptually).

Spec: phase1/04_tools.md § 3.1 (canonical spec).
ParquetSnapshotRegistry DDL: phase1/01_database_schema.md § 8.
Round 3 § 1.3 canonical interface: phase1/03_core_modules.md.
"""
from __future__ import annotations

import importlib
import importlib.util
import sys
import time
from datetime import datetime, timedelta, timezone
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

# D76 EventType per CLI_* family registry (one of the 11 R4 canonical values)
EXPECTED_EVENT_TYPE = "CLI_PARQUET_TIER_REVIEW"

# D74 exit codes
EXIT_SUCCESS = 0
EXIT_OPERATIONAL = 1
EXIT_FATAL = 2

# Status enum values (Round 3 § 1.3 STATUS_* module-level constants)
STATUS_CREATED = "created"
STATUS_VERIFIED = "verified"
STATUS_REPLICATED = "replicated"
STATUS_ARCHIVED = "archived"
STATUS_MISSING = "missing"
STATUS_PURGED = "purged"
STATUS_REPLICATION_FAILED = "replication_failed"

# Canonical defaults for _call_main
_ACTOR = "test-author"
_JUSTIFICATION_DEFAULT = "Tier 0 smoke test"

# Replica targets / archive locations / retention batch ids used in tests
_REPLICA_TARGET = "snowflake:UDM_BRONZE_MIRROR"
_ARCHIVE_LOCATION = "s3://offsite-bucket/udm-archive/"
_RETENTION_BATCH_ID = 12345


# ---------------------------------------------------------------------------
# Canonical row builder — produces a dict matching Round 3 § 1.3 columns
# ---------------------------------------------------------------------------


def _canonical_row(
    *,
    registry_id: int,
    source_name: str = "DNA",
    table_name: str = "ACCT",
    batch_id: int = 1000,
    status: str = STATUS_VERIFIED,
    business_date_iso: str = "2026-05-01",
    compressed_bytes: int = 50 * 1024 * 1024,  # 50 MB
    uncompressed_bytes: int = 200 * 1024 * 1024,
    last_verified_offset_days: int = 5,
) -> tuple:
    """Return a tuple mirroring the SELECT column order in
    ``_list_registry_rows_by_status``.

    The tool's SELECT enumerates 20 canonical columns; this helper builds
    a tuple in that exact order so the mock cursor's fetchall() returns
    data the dict-zip step can consume.
    """
    last_verified_at = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(
        days=last_verified_offset_days
    )
    created_at = last_verified_at - timedelta(days=1)
    business_date = datetime.fromisoformat(business_date_iso).date()
    return (
        registry_id,
        source_name,
        table_name,
        batch_id,
        business_date,
        f"/parquet/{source_name}/{table_name}/{registry_id}.parquet",
        None,  # SnowflakeStagePath
        None,  # SnowflakeUploadedAt
        100000,  # RowCount
        uncompressed_bytes,
        compressed_bytes,
        "schema_hash_placeholder",
        "content_checksum_placeholder",
        "hot",  # StorageTier
        status,
        created_at,
        last_verified_at,
        last_verified_at,  # LastAccessedAt
        None,  # PurgedAt
        None,  # PurgedReason
    )


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
# Exception class resolution (B215 pattern)
# ---------------------------------------------------------------------------


def _resolve_exception_classes() -> tuple:
    """Resolve the canonical registry-error classes.

    Tools import from ``utils.errors`` per B228; tests resolve the SAME
    classes so isinstance checks line up.
    """
    try:
        from utils.errors import (
            RegistryFileNotFound,
            RegistryNotFound,
            RegistryStatusInvalid,
        )
        return RegistryStatusInvalid, RegistryFileNotFound, RegistryNotFound
    except (ImportError, AttributeError):
        class _RegistryStatusInvalid(Exception):  # type: ignore[no-redef]
            """Stand-in: utils.errors not yet authored."""

        class _RegistryFileNotFound(Exception):  # type: ignore[no-redef]
            """Stand-in: utils.errors not yet authored."""

        class _RegistryNotFound(Exception):  # type: ignore[no-redef]
            """Stand-in: utils.errors not yet authored."""

        return _RegistryStatusInvalid, _RegistryFileNotFound, _RegistryNotFound


RegistryStatusInvalid, RegistryFileNotFound, RegistryNotFound = _resolve_exception_classes()


# ---------------------------------------------------------------------------
# Module loader — mocks all external dependencies
# ---------------------------------------------------------------------------


def _load_tool_module(
    *,
    select_rows: list[tuple] | None = None,
    mark_replicated_side_effect: Exception | None = None,
    mark_archived_side_effect: Exception | None = None,
    mark_purged_side_effect: Exception | None = None,
    connection_side_effect: Exception | None = None,
) -> Any:
    """Load tools/parquet_tier_review.py with external imports mocked.

    Parameters
    ----------
    select_rows:
        Tuples returned by cursor.fetchall() for the status-filtered SELECT.
        Each tuple matches the column order in _SELECT_COLUMNS.
    mark_replicated_side_effect / mark_archived_side_effect / mark_purged_side_effect:
        Exception to raise when the corresponding transition fn is called.
        None = success (no-op return).
    connection_side_effect:
        If set, cursor_for / get_connection / pyodbc.connect raises this.
    """
    if _TOOL_MODULE_KEY in sys.modules:
        del sys.modules[_TOOL_MODULE_KEY]

    rows = select_rows if select_rows is not None else []
    executed_sql: list[str] = []
    executed_params: list[Any] = []

    mock_cursor = MagicMock()

    def _capture_execute(sql: str, *args, **kwargs) -> None:
        executed_sql.append(str(sql))
        if args:
            for a in args:
                if isinstance(a, (list, tuple)):
                    executed_params.extend(a)
                else:
                    executed_params.append(a)

    mock_cursor.execute.side_effect = _capture_execute
    mock_cursor.fetchall.return_value = rows
    # description shape — sequence of (name, ...) tuples per DBAPI
    mock_cursor.description = [(name, None) for name in _SELECT_COLUMNS]
    # For the audit row's SCOPE_IDENTITY() fetchone — return a small int
    mock_cursor.fetchone.return_value = (99001,)
    mock_cursor.rowcount = 0

    mock_conn = MagicMock()
    mock_conn.cursor.return_value = mock_cursor
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)

    mock_connections = MagicMock()
    if connection_side_effect is not None:
        mock_connections.cursor_for = MagicMock(side_effect=connection_side_effect)
        mock_connections.get_connection = MagicMock(side_effect=connection_side_effect)
    else:
        mock_connections.cursor_for = MagicMock(return_value=mock_cursor)
        mock_connections.get_connection = MagicMock(return_value=mock_conn)

    # Build mock registry-client module with transition fns we can spy on.
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

    # Stash test instrumentation
    mod._test_sys_modules_patch = sys_modules_patch
    mod._test_cursor = mock_cursor
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
    """Call tool main() with canonical defaults + overrides.

    Re-applies the sys.modules patch from _load_tool_module so the runtime
    `sys.modules.get(...)` resolution honors the test mocks.
    """
    defaults = dict(
        actor=_ACTOR,
        justification=_JUSTIFICATION_DEFAULT,
        from_status=STATUS_VERIFIED,
        to_status=None,
        apply=False,
        json_output=False,
        verbose=False,
        quiet=True,  # quiet by default so test stdout stays clean
        no_audit_event=True,  # tier0 default: skip audit write
        transition_fn_overrides=getattr(mod, "_test_transition_fn_overrides", None),
    )
    defaults.update(overrides)
    sys_modules_patch = getattr(mod, "_test_sys_modules_patch", {})
    try:
        with patch.dict("sys.modules", sys_modules_patch):
            # Inject general_cursor_factory so we control the connection
            cursor_mock = getattr(mod, "_test_cursor", None)
            mock_conn = MagicMock()
            mock_conn.cursor.return_value = cursor_mock
            mock_conn.autocommit = True
            mock_conn.close = MagicMock(return_value=None)
            defaults.setdefault(
                "general_cursor_factory",
                lambda: mock_conn,
            )
            return mod.main(**defaults)
    except SystemExit as exc:
        return {"exit_code": exc.code, "_raised_system_exit": True}


# ===========================================================================
# Tier 0 (a): module imports without error
# ===========================================================================


def test_module_imports():
    """(a) Module imports without error.

    D67 Tier 0 assertion: import with all external dependencies mocked.
    A failed import indicates a missing dep or syntax error.
    """
    _t0 = time.monotonic()
    mod = _load_tool_module()
    assert mod is not None, (
        "tools/parquet_tier_review.py must load without error. "
        "Check for missing imports or syntax errors. D67 Tier 0 (a)."
    )
    elapsed = time.monotonic() - _t0
    assert elapsed < 5.0, (
        f"Module load must complete in < 5 s. Took {elapsed:.2f} s. D67."
    )


# ===========================================================================
# Tier 0 (b): --help exits 0
# ===========================================================================


def test_help_exits_zero():
    """(b) --help exits 0.

    D74 (exit-code contract): --help is the canonical discoverability
    path. argparse emits SystemExit(0) on --help.
    """
    mod = _load_tool_module()
    parser = mod._build_arg_parser()
    with pytest.raises(SystemExit) as exc_info:
        parser.parse_args(["--help"])
    assert exc_info.value.code == 0, (
        "--help must exit 0. D74 (exit 0 = success / informational)."
    )


# ===========================================================================
# Tier 0 (c): canonical args parse correctly
# ===========================================================================


def test_canonical_args_parse():
    """(c) parser.parse_args(['--from-status', 'verified']) returns Namespace.

    Per spec § 3.1: --from-status default 'verified'; tool runs in
    report-only mode without --to-status; --apply is False by default.
    """
    mod = _load_tool_module()
    parser = mod._build_arg_parser()
    ns = parser.parse_args(["--from-status", "verified"])
    assert ns.from_status == STATUS_VERIFIED
    assert ns.to_status is None
    assert ns.apply is False
    assert ns.json_output is False


# ===========================================================================
# Tier 0 (d): --apply without --to-status -> exit 2
# ===========================================================================


def test_apply_without_to_status_exits_2():
    """(d) --apply without --to-status -> exit 2 (validation fatal).

    Per spec § 3.1: --apply only meaningful with --to-status. The tool
    validates this in _validate_args_main; missing --to-status -> exit 2.
    """
    mod = _load_tool_module(select_rows=[])
    result = _call_main(mod, apply=True, to_status=None)
    exit_code = result.get("exit_code") if isinstance(result, dict) else None
    assert exit_code == EXIT_FATAL, (
        f"--apply without --to-status must exit {EXIT_FATAL}. "
        f"Got: {exit_code!r}."
    )


# ===========================================================================
# Tier 0 (e): 3 'verified' rows + dry-run -> exit 0, no mark_* calls
# ===========================================================================


def test_dry_run_three_rows_exits_zero_no_mutations():
    """(e) 3 synthetic 'verified' rows + dry-run -> exit 0; no mark_* called.

    Per spec § 3.1 Idempotency: read-only path. SELECT runs; mark_* fns
    NEVER invoked in dry-run mode. Tool exits 0 with rows_matched = 3.
    """
    rows = [
        _canonical_row(registry_id=101, table_name="ACCT"),
        _canonical_row(registry_id=102, table_name="ACCT"),
        _canonical_row(registry_id=103, table_name="ACCT"),
    ]
    mod = _load_tool_module(select_rows=rows)
    result = _call_main(mod, apply=False, to_status=None)
    exit_code = result.get("exit_code")
    assert exit_code == EXIT_SUCCESS, (
        f"Dry-run with 3 rows must exit {EXIT_SUCCESS}. Got: {exit_code!r}."
    )
    assert result.get("rows_matched") == 3, (
        f"rows_matched must equal SELECT row count. "
        f"Got: {result.get('rows_matched')!r}."
    )
    assert mod._test_mark_replicated.call_count == 0, (
        "Dry-run must NEVER call mark_replicated. "
        f"Got {mod._test_mark_replicated.call_count} calls."
    )
    assert mod._test_mark_archived.call_count == 0
    assert mod._test_mark_purged.call_count == 0


# ===========================================================================
# Tier 0 (f): mark_replicated raising RegistryStatusInvalid -> exit 2
# ===========================================================================


def test_mark_replicated_status_invalid_exits_2():
    """(f) mark_replicated raising RegistryStatusInvalid -> exit 2 (FATAL).

    Per spec § 3.1 Error modes: RegistryStatusInvalid (PipelineFatalError)
    maps to exit 2. The tool catches the exception, records the failure
    per row, and propagates exit 2 at the run level.
    """
    rows = [_canonical_row(registry_id=201)]
    err = RegistryStatusInvalid("predecessor status invalid")
    mod = _load_tool_module(
        select_rows=rows,
        mark_replicated_side_effect=err,
    )
    result = _call_main(
        mod,
        apply=True,
        to_status=STATUS_REPLICATED,
        replica_target=_REPLICA_TARGET,
    )
    exit_code = result.get("exit_code")
    assert exit_code == EXIT_FATAL, (
        f"RegistryStatusInvalid must exit {EXIT_FATAL}. Got: {exit_code!r}."
    )
    assert result.get("rows_failed", 0) >= 1, (
        f"At least one row must record a transition failure. "
        f"Got rows_failed={result.get('rows_failed')!r}."
    )


# ===========================================================================
# Tier 0 (g): --apply --to-status replicated calls mark_replicated N times
# ===========================================================================


def test_apply_replicate_calls_mark_replicated_per_row():
    """(g) --apply --to-status replicated calls mark_replicated exactly N times.

    Per spec § 3.1: each matched row drives one mark_replicated() call.
    With 3 rows and no errors, the mock is called 3 times with the right
    keyword args.
    """
    rows = [
        _canonical_row(registry_id=301, table_name="ACCT"),
        _canonical_row(registry_id=302, table_name="LOAN"),
        _canonical_row(registry_id=303, table_name="CARDTXN"),
    ]
    mod = _load_tool_module(select_rows=rows)
    result = _call_main(
        mod,
        apply=True,
        to_status=STATUS_REPLICATED,
        replica_target=_REPLICA_TARGET,
    )
    exit_code = result.get("exit_code")
    assert exit_code == EXIT_SUCCESS, (
        f"Successful 3-row apply must exit {EXIT_SUCCESS}. Got: {exit_code!r}."
    )
    assert mod._test_mark_replicated.call_count == 3, (
        f"mark_replicated must be called exactly 3 times. "
        f"Got: {mod._test_mark_replicated.call_count}."
    )
    # Validate keyword-only signature contract
    for call_args in mod._test_mark_replicated.call_args_list:
        _, kwargs = call_args
        assert "registry_id" in kwargs, (
            "mark_replicated must be invoked with kwarg registry_id "
            "(Round 3 § 1.3 keyword-only signature)."
        )
        assert kwargs.get("replica_target") == _REPLICA_TARGET, (
            f"replica_target must be passed through from --replica-target. "
            f"Got: {kwargs.get('replica_target')!r}."
        )


# ===========================================================================
# Tier 0 runtime ceiling assertion (D67)
# ===========================================================================


def test_tier0_total_runtime_under_five_seconds():
    """All 7 Tier 0 assertions complete in < 5 s (D67 ceiling).

    D67: Tier 0 smoke test runtime ceiling < 5 s per module. Failure
    means external I/O has leaked through the mock layer — a test-
    isolation bug.
    """
    _start = time.monotonic()

    m1 = _load_tool_module()
    assert m1 is not None

    m2 = _load_tool_module(select_rows=[])
    _call_main(m2, apply=True, to_status=None)

    rows3 = [_canonical_row(registry_id=400 + i) for i in range(3)]
    m3 = _load_tool_module(select_rows=rows3)
    _call_main(m3, apply=False, to_status=None)

    err = RegistryStatusInvalid("status invalid")
    m4 = _load_tool_module(
        select_rows=[_canonical_row(registry_id=500)],
        mark_replicated_side_effect=err,
    )
    _call_main(
        m4,
        apply=True,
        to_status=STATUS_REPLICATED,
        replica_target=_REPLICA_TARGET,
    )

    rows5 = [_canonical_row(registry_id=600 + i) for i in range(3)]
    m5 = _load_tool_module(select_rows=rows5)
    _call_main(
        m5,
        apply=True,
        to_status=STATUS_REPLICATED,
        replica_target=_REPLICA_TARGET,
    )

    elapsed = time.monotonic() - _start
    assert elapsed < 5.0, (
        f"Tier 0 total runtime must be < 5 s. Took {elapsed:.2f} s. "
        "External I/O may have leaked through mock layer. D67."
    )
