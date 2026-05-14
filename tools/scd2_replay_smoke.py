"""Round 6 follow-up — ``tools/scd2_replay_smoke.py``.

Per **M2** ``data_load/parquet_replay.py`` (Round 3 § 1.2; Wave 3.3 build
2026-05-13) + **``scd2/engine.py::run_scd2()``**. End-to-end smoke script
for operator-driven SCD2-from-Parquet replay testing.

What this tool does
-------------------

The user's question: *"do Parquet snapshots actually re-hydrate into
SCD2 versions in Bronze?"* This script answers it for one
``(source, table, business_date, original_batch_id)`` tuple.

1. Loads the ``TableConfig`` via :class:`TableConfigLoader` (from
   ``orchestration/table_config.py``) — the same loader the production
   pipeline uses, so the smoke test exercises the canonical metadata path.
2. Allocates a fresh ``replay_batch_id`` from
   ``General.ops.PipelineBatchSequence`` (the M2 contract requires this
   to be distinct from the original snapshot's batch).
3. Calls :func:`data_load.parquet_replay.replay_parquet_snapshot` —
   reads the registered Parquet file off the network drive, SHA-256
   verifies, and returns a :class:`ReplayResult` carrying the in-memory
   Polars DataFrame.
4. Counts Bronze rows BEFORE SCD2 (so we have a delta baseline).
5. Calls :func:`scd2.engine.run_scd2` with the replay result DataFrame
   threaded through as ``df_current``. SCD2 walks the canonical
   INSERT-first / close-old / activate-new dance per SCD2-P1-c.
6. Counts Bronze rows AFTER SCD2 + reads ``SCD2Result`` (inserts,
   new_versions, closes, unchanged).
7. Prints the audit summary + writes one ``CLI_SCD2_REPLAY_SMOKE``
   row to ``General.ops.PipelineEventLog`` per D76.

Dry-run mode (default — D75 safe-default per B88 mutex) prints the
resolved registry-lookup tuple + ``TableConfig`` summary + a "would
replay; would run SCD2" preview WITHOUT calling :func:`replay_parquet_snapshot`
OR :func:`run_scd2`. Use ``--apply`` for the live composition.

CLI contract
------------

::

    # Preview — no live work; default
    python -m tools.scd2_replay_smoke --source DNA --table ACCT \\
        --business-date 2026-05-13 --original-batch-id 12345 --dry-run

    # Live end-to-end: replay → SCD2 → audit
    python -m tools.scd2_replay_smoke --source DNA --table ACCT \\
        --business-date 2026-05-13 --original-batch-id 12345 --apply

    # JSON output for machine consumption
    python -m tools.scd2_replay_smoke --source DNA --table ACCT \\
        --business-date 2026-05-13 --original-batch-id 12345 --apply --json-output

Exit codes (per D74)
~~~~~~~~~~~~~~~~~~~~

* **0** — dry-run preview OR live composition completed successfully
* **1** — :class:`PipelineRetryableError` (e.g. :class:`LedgerLockTimeout`)
* **2** — :class:`PipelineFatalError` (e.g. :class:`RegistryNotFound` /
  :class:`RegistryStatusInvalid` / :class:`ParquetReplayError`) OR
  configuration / connection failure OR B88 mutex violation

Audit row (per D76)
~~~~~~~~~~~~~~~~~~~

* ``General.ops.PipelineEventLog.EventType = 'CLI_SCD2_REPLAY_SMOKE'``
  (new canonical CLI_* family value per D76)
* ONE row per INVOCATION (dry-run + apply both write one row)
* ``Status in {SUCCESS, FAILED}``
* ``Metadata`` JSON shape::

    {
        "event_kind": "scd2_replay_smoke",
        "actor": "<operator|automic|pipeline>",
        "source_name": "DNA",
        "table_name": "ACCT",
        "business_date": "2026-05-13",
        "original_batch_id": 12345,
        "replay_batch_id": 99999,
        "dry_run": <bool>,
        "registry_id": <int|null>,
        "rows_replayed": <int|null>,
        "rows_inserted": <int|null>,
        "rows_new_versions": <int|null>,
        "rows_closed": <int|null>,
        "rows_unchanged": <int|null>,
        "bronze_rows_before": <int|null>,
        "bronze_rows_after": <int|null>,
        "sha256_verified": "<hex|null>",
        "exit_code": <int>,
        "error_class": <str|null>,
        "started_at": "<ISO-8601 naive-UTC>",
        "completed_at": "<ISO-8601 naive-UTC>",
        "duration_ms": <int>
    }

Classification per ``udm-execution-classifier`` skill
-----------------------------------------------------

* **Trigger**: PRIMARY: Manual operator CLI for ad-hoc smoke testing
  (operator verifies the replay→SCD2 path end-to-end after Bronze
  rebuild or after a change to either M2 or ``scd2/engine.py``).
  SECONDARY: Not pipeline-programmatic — the pipeline NEVER invokes
  this script; replay is composed directly by RB-8 Bronze rebuild.
  TERTIARY: Not scheduled.
* **Frequency**: Ad-hoc / event-driven (post-deployment, post-rebuild).
* **Idempotency**: YES — M2 :func:`replay_parquet_snapshot` is
  idempotent (re-call with the same ``replay_batch_id`` short-circuits
  via the ledger). ``run_scd2`` is idempotent under the canonical
  INSERT-first contract (re-replaying the same DataFrame produces zero
  inserts/updates because hashes are unchanged).
* **Concurrency**: Single-threaded; ``cursor_for('General')`` per
  invocation. No worker pool.
* **Audit-row family**: ``CLI_SCD2_REPLAY_SMOKE`` per D76 + CLAUDE.md
  CLI_* family registry (NEW addition).
* **Routing**: PRIMARY tracker ``ONE_OFF_SCRIPTS.md`` operator tools
  table (manual + event-driven). NO scheduled tracker entry (no
  Automic job — operator-only).

D-numbers consumed
------------------

D2 (Stage dropped — Parquet snapshots replace it), D4 (network drive
Parquet), D15 (idempotency mandatory — replay composes ledger_step),
D67 (Tier 0 smoke discipline), D68 (canonical exception hierarchy —
utils.errors), D74 (exit-code contract 0/1/2), D75 (canonical args
+ dry-run default), D76 (audit-row contract CLI_SCD2_REPLAY_SMOKE),
D77 (Tier 0 scaffold canonical), D92 (forward-only additive — new
tool; M2 + run_scd2 signatures unmodified).

Canonical references cited (per Pitfall #9.l producer self-check)
-----------------------------------------------------------------

* M2 ``replay_parquet_snapshot`` signature: ``data_load/parquet_replay.py``
  L436-460 (keyword-only ``(*, source_name, table_name, business_date,
  original_batch_id, replay_batch_id)`` returning :class:`ReplayResult`).
* ``run_scd2`` signature: ``scd2/engine.py`` L190-217 (positional
  ``(table_config, df_current, pk_columns, output_dir)`` +
  keyword-only ``source_begin_date`` returning :class:`SCD2Result`).
* :class:`TableConfigLoader` signature: ``orchestration/table_config.py``
  — ``load_small_tables(source_name=..., table_name=...)`` /
  ``load_large_tables(source_name=..., table_name=...)`` returning
  ``list[TableConfig]``.
* utils.errors canonical classes per D68 + B-228.

See also
--------

* ``tools/parquet_verify.py`` — sibling Round 4 § 3.2 tool (closest
  analog; same author pattern).
* ``data_load/parquet_replay.py`` — M2; wrapped by this script.
* ``scd2/engine.py`` — engine; ``run_scd2`` composed by this script.
* RB-8 (Bronze rebuild via replay — full operational procedure;
  this script is the smoke-test subset).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import traceback
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

# Project root on sys.path so we can reach data_load + orchestration +
# scd2 + utils. Mirrors the M2-CLI sibling-import pattern.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Canonical exception hierarchy per D68 + B-228 (utils.errors single
# source of truth; tools import directly).
try:
    from utils.errors import (  # noqa: E402
        LedgerLockTimeout,
        ParquetReplayError,
        PipelineFatalError,
        PipelineRetryableError,
        RegistryNotFound,
        RegistryStatusInvalid,
    )
except (ImportError, ModuleNotFoundError):
    # Defensive fallback for test environments where utils.errors is
    # mocked as MagicMock; re-import from filesystem.
    import importlib.util as _importlib_util  # noqa: E402

    _err_path = Path(__file__).resolve().parent.parent / "utils" / "errors.py"
    _spec = _importlib_util.spec_from_file_location(
        "utils._errors_scd2_replay_smoke", _err_path
    )
    _err_mod = _importlib_util.module_from_spec(_spec)
    _spec.loader.exec_module(_err_mod)
    LedgerLockTimeout = _err_mod.LedgerLockTimeout
    ParquetReplayError = _err_mod.ParquetReplayError
    PipelineFatalError = _err_mod.PipelineFatalError
    PipelineRetryableError = _err_mod.PipelineRetryableError
    RegistryNotFound = _err_mod.RegistryNotFound
    RegistryStatusInvalid = _err_mod.RegistryStatusInvalid

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exit-code constants (per D74)
# ---------------------------------------------------------------------------

EXIT_SUCCESS = 0
EXIT_OPERATIONAL_FAILURE = 1
EXIT_FATAL = 2

# D76 EventType — NEW CLI_* family value registered in CLAUDE.md.
EVENT_TYPE = "CLI_SCD2_REPLAY_SMOKE"


# ---------------------------------------------------------------------------
# Lazy sibling-module resolvers (B214 — testability)
# ---------------------------------------------------------------------------


def _get_replay_fn() -> Callable:
    """Resolve :func:`data_load.parquet_replay.replay_parquet_snapshot`.

    Lazy at call-time so tests patching ``sys.modules`` after import
    are honored (B214 pattern). Wrapping a fatal-import error into
    :class:`PipelineFatalError` keeps the exception surface uniform.
    """
    try:
        from data_load.parquet_replay import replay_parquet_snapshot  # type: ignore

        return replay_parquet_snapshot
    except Exception as exc:  # noqa: BLE001
        raise PipelineFatalError(
            f"M2 data_load.parquet_replay unavailable: {exc}",
            metadata={"step": "resolve_replay_fn"},
        ) from exc


def _get_scd2_fn() -> Callable:
    """Resolve :func:`scd2.engine.run_scd2`.

    Lazy at call-time per B214. Operators expect this CLI to fail
    with a clear message if the engine is unimportable.
    """
    try:
        from scd2.engine import run_scd2  # type: ignore

        return run_scd2
    except Exception as exc:  # noqa: BLE001
        raise PipelineFatalError(
            f"scd2.engine.run_scd2 unavailable: {exc}",
            metadata={"step": "resolve_scd2_fn"},
        ) from exc


def _get_table_config_loader() -> Callable:
    """Resolve a callable that returns a list[TableConfig] for the source+table.

    Wraps :class:`TableConfigLoader` so tests can swap the entire
    loader via the ``table_config_loader`` kwarg without touching the
    class import surface.

    The returned callable accepts ``(source: str, table: str) ->
    list[TableConfig]`` and tries small-tables first, then large-tables.
    """
    try:
        from orchestration.table_config import TableConfigLoader  # type: ignore

        def _load(source: str, table: str) -> list:
            loader = TableConfigLoader()
            configs = loader.load_small_tables(source_name=source, table_name=table)
            if not configs:
                configs = loader.load_large_tables(source_name=source, table_name=table)
            return configs

        return _load
    except Exception as exc:  # noqa: BLE001
        raise PipelineFatalError(
            f"orchestration.table_config.TableConfigLoader unavailable: {exc}",
            metadata={"step": "resolve_table_config_loader"},
        ) from exc


def _get_batch_seq_fn() -> Callable:
    """Resolve a callable that allocates the next ``BatchId``.

    Composes ``cursor_for('General')`` + ``SELECT NEXT VALUE FOR
    General.ops.PipelineBatchSequence`` (the canonical batch-id source
    per CLAUDE.md observability section).
    """
    try:
        from utils.connections import cursor_for  # type: ignore

        def _next_batch_id() -> int:
            with cursor_for("General") as cur:
                cur.execute(
                    "SELECT NEXT VALUE FOR General.ops.PipelineBatchSequence;"
                )
                row = cur.fetchone()
                if row is None or row[0] is None:
                    raise PipelineFatalError(
                        "PipelineBatchSequence returned no value",
                        metadata={"step": "allocate_batch_id"},
                    )
                return int(row[0])

        return _next_batch_id
    except Exception as exc:  # noqa: BLE001
        raise PipelineFatalError(
            f"utils.connections.cursor_for unavailable: {exc}",
            metadata={"step": "resolve_batch_seq_fn"},
        ) from exc


# ---------------------------------------------------------------------------
# Actor detection (per § 1.7 invocation pattern heuristic)
# ---------------------------------------------------------------------------


def _detect_actor() -> str:
    """Resolve ``--actor`` default per spec § 1.7 invocation-pattern heuristic.

    1. AUTOMIC_RUN_ID env var present -> 'automic'
    2. sys.stdin.isatty() -> 'operator'
    3. Else -> 'pipeline'
    """
    if os.environ.get("AUTOMIC_RUN_ID"):
        return "automic"
    try:
        if sys.stdin.isatty():
            return "operator"
    except (AttributeError, ValueError):
        # ValueError: I/O operation on closed file (pytest -s pipe)
        pass
    return "pipeline"


# ---------------------------------------------------------------------------
# Datetime helpers (SCD2-P1-f naive-UTC + ms-precision invariant)
# ---------------------------------------------------------------------------


def _now_naive_utc() -> datetime:
    """Return a naive-UTC, ms-precision datetime per SCD2-P1-f.

    The audit row Metadata datetimes MUST be naive (no tzinfo) so
    pyodbc serializes them as ``DATETIME2(3)`` (not ``DATETIMEOFFSET``)
    — matches the audit-table column type. Microseconds are truncated
    to milliseconds for parity with BCP-written values per CDC-NOW-MS.
    """
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    micros = now.microsecond
    millis = micros - (micros % 1000)
    return now.replace(microsecond=millis)


def _now_iso_naive() -> str:
    """ISO-8601 naive-UTC timestamp string per SCD2-P1-f."""
    return _now_naive_utc().strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Bronze row-count helper
# ---------------------------------------------------------------------------


def _count_bronze_rows(table_config, *, cursor_factory: Callable | None = None) -> int | None:
    """Return ``COUNT(*)`` of the Bronze table for ``table_config``.

    Defensive: returns None on any failure (table doesn't exist,
    connection failed, etc.). The smoke script proceeds anyway —
    bronze counts are diagnostic, not load-bearing.

    ``cursor_factory`` (test injection): a no-arg callable returning
    an open pyodbc-compatible connection. Defaults to
    ``utils.connections.cursor_for(bronze_db)``.
    """
    bronze_table = getattr(table_config, "bronze_full_table_name", None)
    if not bronze_table:
        return None

    parts = bronze_table.split(".")
    if len(parts) < 1:
        return None
    bronze_db = parts[0]

    try:
        if cursor_factory is None:
            from utils.connections import cursor_for as _cursor_for  # type: ignore

            with _cursor_for(bronze_db) as cur:
                cur.execute(f"SELECT COUNT(*) FROM {bronze_table};")
                row = cur.fetchone()
                return int(row[0]) if row and row[0] is not None else 0
        else:
            conn = cursor_factory()
            try:
                cur = conn.cursor()
                cur.execute(f"SELECT COUNT(*) FROM {bronze_table};")
                row = cur.fetchone()
                return int(row[0]) if row and row[0] is not None else 0
            finally:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass
    except Exception:  # noqa: BLE001
        logger.debug(
            "Bronze row-count failed for %s — continuing", bronze_table,
            exc_info=True,
        )
        return None


# ---------------------------------------------------------------------------
# Audit row writer (per D76)
# ---------------------------------------------------------------------------


def _write_audit_row(
    metadata: dict,
    *,
    status: str,
    error_message: str | None = None,
    cursor_factory: Callable | None = None,
    general_db: str = "General",
    skip: bool = False,
) -> int | None:
    """INSERT one ``CLI_SCD2_REPLAY_SMOKE`` row into PipelineEventLog.

    Per D76. ONE row per invocation (dry-run + apply both write one).
    Best-effort: failures are logged but do not affect the verdict
    exit code (parity with sibling Round 4 tools).

    Returns the ``SCOPE_IDENTITY()`` of the inserted row so the JSON
    ``audit_event_id`` key can be populated. Returns None on failure.

    When ``skip=True`` (test path), returns None immediately without
    writing.
    """
    if skip:
        return None

    metadata_json = json.dumps(metadata, separators=(",", ":"), default=str)
    event_detail = (
        f"scd2_replay_smoke / dry_run={metadata.get('dry_run')} / "
        f"{metadata.get('source_name')}.{metadata.get('table_name')}"
    )

    if cursor_factory is None:
        try:
            from utils.connections import get_connection  # type: ignore

            def cursor_factory():  # type: ignore[no-redef]
                return get_connection(general_db)
        except Exception:  # noqa: BLE001
            logger.warning(
                "Audit-row write skipped: utils.connections unavailable; "
                "verdict exit code is authoritative."
            )
            return None

    conn = None
    try:
        conn = cursor_factory()
        try:
            conn.autocommit = True
        except Exception:  # noqa: BLE001
            pass
        cursor = conn.cursor()
        try:
            cursor.execute(
                f"INSERT INTO [{general_db}].ops.PipelineEventLog "
                f"(BatchId, TableName, SourceName, EventType, EventDetail, "
                f" StartedAt, CompletedAt, Status, ErrorMessage, Metadata) "
                f"VALUES (NEXT VALUE FOR [{general_db}].ops.PipelineBatchSequence, "
                f"        ?, ?, ?, ?, ?, SYSUTCDATETIME(), ?, ?, ?); "
                f"SELECT CAST(SCOPE_IDENTITY() AS BIGINT) AS AuditEventId;",
                metadata.get("table_name"),
                metadata.get("source_name"),
                EVENT_TYPE,
                event_detail,
                metadata.get("started_at_dt"),
                status,
                error_message,
                metadata_json,
            )
            row = cursor.fetchone() if cursor.description is not None else None
            if row is None or row[0] is None:
                return None
            return int(row[0])
        finally:
            try:
                cursor.close()
            except Exception:  # noqa: BLE001
                pass
    except Exception:  # noqa: BLE001
        logger.exception("Failed to write CLI_SCD2_REPLAY_SMOKE audit row")
        return None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Stdout rendering
# ---------------------------------------------------------------------------


def _summarize_table_config(tc) -> str:
    """Render a one-line TableConfig summary for dry-run preview.

    Surfaces the fields most-relevant to the SCD2-from-Parquet path:
    source / table / Bronze table / pk_columns / SCD2 mode.
    """
    pk_cols = getattr(tc, "pk_columns", None) or []
    return (
        f"source={getattr(tc, 'source_name', None)!r} / "
        f"table={getattr(tc, 'source_object_name', None)!r} / "
        f"bronze={getattr(tc, 'bronze_full_table_name', None)!r} / "
        f"pk_columns={pk_cols!r} / "
        f"scd2_mode={getattr(tc, 'scd2_mode', None)!r}"
    )


def _emit_human_summary(result: dict, audit_event_id: int | None) -> None:
    """Print human-readable summary per the operator-UX contract.

    Stdout schema:
      Line 1: invocation echo (source/table/business_date/batch_id)
      Line 2: TableConfig summary
      Line 3: Bronze rows before / after
      Line 4: ReplayResult summary (rows replayed + sha256 + source_file)
      Line 5: SCD2Result summary (inserts / new_versions / closes / unchanged)
      Final:  audit event id
    """
    print(
        f"scd2_replay_smoke: source={result.get('source_name')!r} "
        f"table={result.get('table_name')!r} "
        f"business_date={result.get('business_date')!r} "
        f"original_batch_id={result.get('original_batch_id')} "
        f"replay_batch_id={result.get('replay_batch_id')}"
    )
    if result.get("table_config_summary"):
        print(f"  TableConfig: {result['table_config_summary']}")
    if result.get("dry_run"):
        print("  [dry-run] would replay; would run SCD2; would write audit row")
    else:
        print(
            f"  Bronze rows before: {result.get('bronze_rows_before')!r} "
            f"after: {result.get('bronze_rows_after')!r}"
        )
        print(
            f"  Replay: rows={result.get('rows_replayed')!r} "
            f"sha256={result.get('sha256_verified')!r} "
            f"source_file={result.get('source_file')!r}"
        )
        print(
            f"  SCD2: inserts={result.get('rows_inserted')!r} "
            f"new_versions={result.get('rows_new_versions')!r} "
            f"closes={result.get('rows_closed')!r} "
            f"unchanged={result.get('rows_unchanged')!r}"
        )
    if result.get("error_message"):
        print(f"  ERROR: {result['error_message']}", file=sys.stderr)
    if audit_event_id is not None:
        print(f"  audit event {audit_event_id}")


def _emit_json(payload: dict) -> None:
    """Emit JSON payload for machine consumers."""
    print(json.dumps(payload, indent=2, sort_keys=True, default=str))


def _build_json_payload(result: dict) -> dict:
    """Build the canonical JSON output payload."""
    keys = [
        "event_kind",
        "actor",
        "source_name",
        "table_name",
        "business_date",
        "original_batch_id",
        "replay_batch_id",
        "dry_run",
        "registry_id",
        "rows_replayed",
        "rows_inserted",
        "rows_new_versions",
        "rows_closed",
        "rows_unchanged",
        "bronze_rows_before",
        "bronze_rows_after",
        "sha256_verified",
        "source_file",
        "table_config_summary",
        "exit_code",
        "error_class",
        "error_message",
        "started_at",
        "completed_at",
        "duration_ms",
        "audit_event_id",
    ]
    return {k: result.get(k) for k in keys}


# ---------------------------------------------------------------------------
# Top-level main() — programmatic entry
# ---------------------------------------------------------------------------


def main(
    *,
    source: str,
    table: str,
    business_date: date,
    original_batch_id: int,
    actor: str | None = None,
    apply: bool = False,
    dry_run: bool | None = None,
    json_output: bool = False,
    quiet: bool = False,
    verbose: bool = False,
    no_audit_event: bool = False,
    # ---- Injection hooks (B214 test path) ----
    replay_fn: Callable | None = None,
    scd2_fn: Callable | None = None,
    table_config_loader: Callable | None = None,
    batch_seq_fn: Callable | None = None,
    audit_cursor_factory: Callable | None = None,
    bronze_count_cursor_factory: Callable | None = None,
    general_db: str = "General",
    output_dir: str | Path | None = None,
) -> dict:
    """Programmatic entry — composes M2 replay + scd2.run_scd2 end-to-end.

    Returns a dict matching the D76 audit-row Metadata shape. Exit-code
    derivation per D74:

    * 0: dry-run preview OR live composition completed successfully
    * 1: :class:`PipelineRetryableError` (e.g. LedgerLockTimeout)
    * 2: :class:`PipelineFatalError` (RegistryNotFound, RegistryStatusInvalid,
         ParquetReplayError) OR config / connection failure OR
         B88 mutex violation

    Parameters
    ----------
    source / table / business_date / original_batch_id:
        Lookup-key tuple for ``ParquetSnapshotRegistry``. REQUIRED.
    actor:
        Operator identity (per D75 + D76). Auto-detected if omitted.
    apply:
        When True, calls :func:`replay_parquet_snapshot` + :func:`run_scd2`
        for real. Default False (dry-run preview only).
    dry_run:
        B88 mutex bridge. If True AND ``apply=True`` -> exit 2.
    no_audit_event:
        Skip the CLI-level PipelineEventLog write (test path).
    replay_fn / scd2_fn / table_config_loader / batch_seq_fn:
        Test-injection hooks (B214). Defaults resolve to live infra.
    audit_cursor_factory / bronze_count_cursor_factory:
        Test-injection hooks for DB cursors. Defaults resolve to
        ``utils.connections``.
    general_db:
        Override the General DB name (defaults to ``'General'``).
    output_dir:
        Staging-CSV directory for ``run_scd2``. Defaults to
        ``config.CSV_OUTPUT_DIR`` if available, else ``/tmp``.
    """
    started_at = _now_naive_utc()

    # B88 dry-run/apply mutex bridge — parity with sibling tools.
    if dry_run is True and apply is True:
        raise SystemExit(2)
    if dry_run is True:
        apply = False

    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    elif quiet:
        logging.getLogger().setLevel(logging.ERROR)

    if actor is None:
        actor = _detect_actor()

    # Pre-populate result dict with input echoes
    result: dict[str, Any] = {
        "event_kind": "scd2_replay_smoke",
        "actor": actor,
        "source_name": source,
        "table_name": table,
        "business_date": business_date.isoformat() if business_date is not None else None,
        "original_batch_id": original_batch_id,
        "replay_batch_id": None,
        "dry_run": (not apply),
        "registry_id": None,
        "rows_replayed": None,
        "rows_inserted": None,
        "rows_new_versions": None,
        "rows_closed": None,
        "rows_unchanged": None,
        "bronze_rows_before": None,
        "bronze_rows_after": None,
        "sha256_verified": None,
        "source_file": None,
        "table_config_summary": None,
        "exit_code": EXIT_SUCCESS,
        "error_class": None,
        "error_message": None,
        "started_at": started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "started_at_dt": started_at,
        "completed_at": None,
        "duration_ms": None,
        "audit_event_id": None,
    }

    def _finalize(status: str) -> dict:
        end_at = _now_naive_utc()
        result["completed_at"] = end_at.strftime("%Y-%m-%dT%H:%M:%SZ")
        result["duration_ms"] = int(
            (end_at - started_at).total_seconds() * 1000
        )
        audit_id = _write_audit_row(
            result,
            status=status,
            error_message=(result.get("error_message") or None),
            cursor_factory=audit_cursor_factory,
            general_db=general_db,
            skip=no_audit_event,
        )
        result["audit_event_id"] = audit_id
        if json_output:
            _emit_json(_build_json_payload(result))
        elif not quiet:
            _emit_human_summary(result, audit_id)
        return result

    # ---- Step 1: Resolve TableConfig ----
    if table_config_loader is None:
        try:
            table_config_loader = _get_table_config_loader()
        except PipelineFatalError as exc:
            result["exit_code"] = EXIT_FATAL
            result["error_class"] = type(exc).__name__
            result["error_message"] = str(exc)[:4000]
            return _finalize("FAILED")

    try:
        configs = table_config_loader(source, table)
    except PipelineFatalError as exc:
        result["exit_code"] = EXIT_FATAL
        result["error_class"] = type(exc).__name__
        result["error_message"] = str(exc)[:4000]
        return _finalize("FAILED")
    except Exception as exc:  # noqa: BLE001
        result["exit_code"] = EXIT_FATAL
        result["error_class"] = type(exc).__name__
        result["error_message"] = f"TableConfigLoader failed: {exc}"[:4000]
        return _finalize("FAILED")

    if not configs:
        result["exit_code"] = EXIT_FATAL
        result["error_class"] = "TableConfigNotFound"
        result["error_message"] = (
            f"No TableConfig found for source={source!r} table={table!r} — "
            f"check UdmTablesList for the row."
        )
        return _finalize("FAILED")

    table_config = configs[0]
    result["table_config_summary"] = _summarize_table_config(table_config)

    # ---- Step 2: Allocate replay_batch_id ----
    if batch_seq_fn is None:
        try:
            batch_seq_fn = _get_batch_seq_fn()
        except PipelineFatalError as exc:
            result["exit_code"] = EXIT_FATAL
            result["error_class"] = type(exc).__name__
            result["error_message"] = str(exc)[:4000]
            return _finalize("FAILED")

    try:
        replay_batch_id = int(batch_seq_fn())
    except PipelineFatalError as exc:
        result["exit_code"] = EXIT_FATAL
        result["error_class"] = type(exc).__name__
        result["error_message"] = str(exc)[:4000]
        return _finalize("FAILED")
    except Exception as exc:  # noqa: BLE001
        result["exit_code"] = EXIT_FATAL
        result["error_class"] = type(exc).__name__
        result["error_message"] = f"Batch-id allocation failed: {exc}"[:4000]
        return _finalize("FAILED")

    result["replay_batch_id"] = replay_batch_id

    # ---- Dry-run short-circuit ----
    if not apply:
        # Preview only — do NOT call replay_fn or scd2_fn.
        return _finalize("SUCCESS")

    # ---- Step 3: Bronze rows BEFORE ----
    result["bronze_rows_before"] = _count_bronze_rows(
        table_config, cursor_factory=bronze_count_cursor_factory,
    )

    # ---- Step 4: Resolve replay_fn + invoke ----
    if replay_fn is None:
        try:
            replay_fn = _get_replay_fn()
        except PipelineFatalError as exc:
            result["exit_code"] = EXIT_FATAL
            result["error_class"] = type(exc).__name__
            result["error_message"] = str(exc)[:4000]
            return _finalize("FAILED")

    try:
        replay_result = replay_fn(
            source_name=source,
            table_name=table,
            business_date=business_date,
            original_batch_id=original_batch_id,
            replay_batch_id=replay_batch_id,
        )
    except PipelineFatalError as exc:
        result["exit_code"] = EXIT_FATAL
        result["error_class"] = type(exc).__name__
        result["error_message"] = str(exc)[:4000]
        return _finalize("FAILED")
    except PipelineRetryableError as exc:
        result["exit_code"] = EXIT_OPERATIONAL_FAILURE
        result["error_class"] = type(exc).__name__
        result["error_message"] = str(exc)[:4000]
        return _finalize("FAILED")
    except Exception as exc:  # noqa: BLE001
        result["exit_code"] = EXIT_FATAL
        result["error_class"] = type(exc).__name__
        result["error_message"] = f"replay_parquet_snapshot failed: {exc}"[:4000]
        return _finalize("FAILED")

    # Surface ReplayResult provenance into result
    result["registry_id"] = getattr(replay_result, "registry_id", None)
    result["rows_replayed"] = getattr(replay_result, "row_count", None)
    result["sha256_verified"] = getattr(replay_result, "sha256_verified", None)
    _src_file = getattr(replay_result, "source_file", None)
    result["source_file"] = str(_src_file) if _src_file is not None else None

    df_current = getattr(replay_result, "df", None)
    if df_current is None:
        result["exit_code"] = EXIT_FATAL
        result["error_class"] = "ReplayResultMissingDataFrame"
        result["error_message"] = (
            "ReplayResult.df is None — replay returned without a DataFrame "
            "payload. Fix M2 before re-running."
        )
        return _finalize("FAILED")

    # ---- Step 5: Resolve scd2_fn + invoke ----
    if scd2_fn is None:
        try:
            scd2_fn = _get_scd2_fn()
        except PipelineFatalError as exc:
            result["exit_code"] = EXIT_FATAL
            result["error_class"] = type(exc).__name__
            result["error_message"] = str(exc)[:4000]
            return _finalize("FAILED")

    # PK columns: surfaced by TableConfig (populated from UdmTablesColumnsList)
    pk_columns = getattr(table_config, "pk_columns", None) or []
    if not pk_columns:
        result["exit_code"] = EXIT_FATAL
        result["error_class"] = "MissingPrimaryKey"
        result["error_message"] = (
            f"TableConfig for {source}.{table} has no Stage-layer primary key "
            f"columns. SCD2 requires PKs — populate "
            f"UdmTablesColumnsList.IsPrimaryKey before re-running."
        )
        return _finalize("FAILED")

    # Resolve output_dir for staging CSV files. ``run_scd2`` writes CSVs
    # for the UPDATE staging tables (closes + activations).
    if output_dir is None:
        try:
            import utils.configuration as _config  # type: ignore

            output_dir = getattr(_config, "CSV_OUTPUT_DIR", None) or "/tmp"
        except Exception:  # noqa: BLE001
            output_dir = "/tmp"

    # source_begin_date — for the smoke script we use business_date as
    # the R-1 batch business date (matches the large-table convention).
    # ``run_scd2`` truncates to ms / strips tz internally per
    # ``_as_source_datetime``; no pre-normalization needed.
    try:
        scd2_result = scd2_fn(
            table_config,
            df_current,
            pk_columns,
            output_dir,
            source_begin_date=business_date,
        )
    except PipelineFatalError as exc:
        result["exit_code"] = EXIT_FATAL
        result["error_class"] = type(exc).__name__
        result["error_message"] = str(exc)[:4000]
        return _finalize("FAILED")
    except PipelineRetryableError as exc:
        result["exit_code"] = EXIT_OPERATIONAL_FAILURE
        result["error_class"] = type(exc).__name__
        result["error_message"] = str(exc)[:4000]
        return _finalize("FAILED")
    except Exception as exc:  # noqa: BLE001
        result["exit_code"] = EXIT_FATAL
        result["error_class"] = type(exc).__name__
        result["error_message"] = f"run_scd2 failed: {exc}"[:4000]
        return _finalize("FAILED")

    # Surface SCD2Result counts (with defensive getattr — different
    # versions of the engine may expose different attrs)
    result["rows_inserted"] = getattr(scd2_result, "inserts", None)
    result["rows_new_versions"] = getattr(scd2_result, "new_versions", None)
    result["rows_closed"] = getattr(scd2_result, "closes", None)
    result["rows_unchanged"] = getattr(scd2_result, "unchanged", None)

    # ---- Step 6: Bronze rows AFTER ----
    result["bronze_rows_after"] = _count_bronze_rows(
        table_config, cursor_factory=bronze_count_cursor_factory,
    )

    return _finalize("SUCCESS")


# ---------------------------------------------------------------------------
# CLI argv entry point
# ---------------------------------------------------------------------------


def _parse_iso_date(value: str) -> date:
    """argparse type adapter for ISO-8601 date strings (YYYY-MM-DD)."""
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(
            f"Invalid ISO-8601 date {value!r}; expected YYYY-MM-DD."
        ) from exc


def _build_arg_parser() -> argparse.ArgumentParser:
    """Alias for :func:`_build_parser` — Tier 0 scaffold contract."""
    return _build_parser()


def _build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser per D75 canonical args + B88 mutex.

    Required: ``--source``, ``--table``, ``--business-date``,
    ``--original-batch-id``.
    Optional: ``--apply`` / ``--dry-run`` (mutex per B88; dry-run default).
    """
    parser = argparse.ArgumentParser(
        description=(
            "End-to-end smoke script for SCD2-from-Parquet replay. "
            "Wraps M2 replay_parquet_snapshot + scd2.engine.run_scd2; "
            "writes one CLI_SCD2_REPLAY_SMOKE audit row per invocation."
        ),
    )
    parser.add_argument(
        "--source",
        required=True,
        help="UdmTablesList.SourceName (e.g. DNA, CCM, EPICOR).",
    )
    parser.add_argument(
        "--table",
        required=True,
        help="UdmTablesList.SourceObjectName (e.g. ACCT).",
    )
    parser.add_argument(
        "--business-date",
        type=_parse_iso_date,
        required=True,
        help=(
            "Hive-partition business date of the snapshot "
            "(ISO-8601 YYYY-MM-DD)."
        ),
    )
    parser.add_argument(
        "--original-batch-id",
        type=int,
        required=True,
        help=(
            "BatchId of the ORIGINAL snapshot in ParquetSnapshotRegistry "
            "(NOT the replay's; the replay's batch_id is allocated fresh "
            "via PipelineBatchSequence at run-time)."
        ),
    )

    # --apply / --dry-run mutex per B88 (apply opt-in; dry-run default).
    apply_group = parser.add_mutually_exclusive_group()
    apply_group.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Apply: call replay_parquet_snapshot + run_scd2 for real "
            "(live composition). Default is dry-run preview."
        ),
    )
    apply_group.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Explicit dry-run opt-in (redundant — dry-run is the default; "
            "useful for scripting clarity)."
        ),
    )

    parser.add_argument(
        "--actor",
        default=None,
        help=(
            "Operator identity (per D75 + D76). One of operator / automic / "
            "pipeline. Auto-detected via TTY / AUTOMIC_RUN_ID when omitted."
        ),
    )
    parser.add_argument(
        "--json-output",
        action="store_true",
        help=(
            "Emit canonical JSON output instead of human summary."
        ),
    )
    parser.add_argument(
        "--no-audit-event",
        action="store_true",
        help=(
            "Skip CLI-level PipelineEventLog write (for "
            "pipeline-programmatic callers per D75 + D76)."
        ),
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable DEBUG logging.",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Suppress stdout summary (errors still emitted to stderr).",
    )
    return parser


def cli_main(argv: Optional[list[str]] = None) -> int:
    """Argv entry point — argparse + main() + return exit code per D74.

    Exit codes (always one of 0 / 1 / 2 per D74):
        - 0: dry-run preview OR live composition succeeded
        - 1: PipelineRetryableError
        - 2: PipelineFatalError OR config / connection failure OR
             B88 mutex violation
    """
    parser = _build_parser()
    args = parser.parse_args(argv)

    actor = args.actor or _detect_actor()

    try:
        result = main(
            source=args.source,
            table=args.table,
            business_date=args.business_date,
            original_batch_id=args.original_batch_id,
            actor=actor,
            apply=args.apply,
            json_output=args.json_output,
            verbose=args.verbose,
            quiet=args.quiet,
            no_audit_event=args.no_audit_event,
        )
    except SystemExit as exc:
        # B88 mutex violation routes through SystemExit(2).
        code = exc.code if isinstance(exc.code, int) else EXIT_FATAL
        if code not in (EXIT_SUCCESS, EXIT_OPERATIONAL_FAILURE, EXIT_FATAL):
            code = EXIT_FATAL
        return code
    except KeyboardInterrupt:
        logger.warning("Interrupted by operator")
        return EXIT_OPERATIONAL_FAILURE
    except Exception:  # noqa: BLE001
        tb = traceback.format_exc()
        print(
            f"FATAL: scd2_replay_smoke unexpected exception:\n{tb[:1000]}",
            file=sys.stderr,
        )
        return EXIT_FATAL

    exit_code = int(result.get("exit_code", EXIT_FATAL))
    if exit_code not in (EXIT_SUCCESS, EXIT_OPERATIONAL_FAILURE, EXIT_FATAL):
        logger.error(
            "Non-canonical exit_code %r returned from main(); "
            "clamping to EXIT_FATAL",
            exit_code,
        )
        exit_code = EXIT_FATAL
    return exit_code


if __name__ == "__main__":
    sys.exit(cli_main())
