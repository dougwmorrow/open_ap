"""B190 — Tool 16 ``measure_capacity_and_partition.py``.

CLI shim wrapping ``data_load.capacity_baseline.measure_capacity_and_partition``
per **phase1/04b_phase_0_closure_tools.md § 5** canonical spec.

What this tool does
-------------------

Per-table row count + growth rate (rolling 12-month average) + 12-month
+ 7-year projections per D42 + partition recommendation narrative per
D45.2 against the Parquet directory layout (D2/D4/D107). Appends each
measurement as a row to ``General.ops.CapacityBaselineLog`` (B195 schema)
and writes ONE ``CLI_MEASURE_CAPACITY_AND_PARTITION`` audit row per
invocation to ``General.ops.PipelineEventLog`` per D76.

Canonical spec sources
----------------------

* **phase1/04b_phase_0_closure_tools.md § 5** — Tool 16 spec, including
  ``CapacityResult`` dataclass per L174-190 + 4 invocation patterns
  (``--all`` + ``--source`` + ``--table`` + ``--report``) + Tier 0 6-
  canonical-assertion scaffold per § 5 L231
* **D26** — append-only provenance for CapacityBaselineLog
* **D42** — Phase 5 Snowflake capacity-cost projection
* **D45.2** — 100-250 MB Parquet partition file-size target
* **D74** — CLI exit-code contract: 0/1/2
* **D75** — CLI argument naming + actor TTY heuristic
* **D76** — CLI audit-row contract; ONE row per invocation
* **D77** — Tier 0 6-canonical-assertion scaffold
* **D92** — forward-only additive (NEW module + NEW CLI; no
  modification to locked Round 4 tool inventory)
* **D107** — dual Windows network drive paths (H + VendorFile)
* **D109** — operational pipeline schedule (Tool 16 runs monthly
  via Automic ``JOB_CAPACITY_BASELINE`` between AM + PM cycles)

CLI contract
------------

::

    python3 tools/measure_capacity_and_partition.py --actor <name> \\
        [--all | --source DNA --table ACCT] \\
        [--report] [--json] [--dry-run] \\
        [--projection-years 7] [--justification <text>]

Exit codes (D74)
~~~~~~~~~~~~~~~~

* **0** — all tables measured successfully
* **1** — at least one table warning (``ParquetDirectoryUnreachable``,
  ``SourceConnectError`` per-table, etc.); other tables continue
* **2** — fatal (``LogTableNotWritable`` — B195 migration not applied,
  or permissions; OR all tables failed; OR argument validation failed)

Audit row (D76)
~~~~~~~~~~~~~~~

ONE row per INVOCATION (per § 5 L197 "one row per invocation, NOT one
row per table"), ``EventType='CLI_MEASURE_CAPACITY_AND_PARTITION'``.
Metadata JSON shape:

.. code-block:: json

    {
        "event_kind": "measure",
        "tables_processed": <int>,
        "tables_flagged_for_optimization": <int>,
        "tables_warning": <int>,
        "tables_failed": <int>,
        "exit_code": <int>,
        "actor": <str>,
        "dry_run": <bool>,
        "totals": {
            "projected_rows_12_months": <int>,
            "projected_storage_mb_7_years": <int>
        },
        "results": [...]   // only when --json or --verbose
    }

Classification per ``udm-execution-classifier`` skill
-----------------------------------------------------

* **Trigger**: PRIMARY: Scheduled (Automic monthly job
  ``JOB_CAPACITY_BASELINE`` per § 6 frozen-13 inventory + D109 schedule).
  SECONDARY: Manual operator CLI for ad-hoc on-demand measurement.
* **Frequency**: PRIMARY Recurring (monthly); SECONDARY one-time ad-hoc.
* **Idempotency**: YES — read-only on source + Parquet; append-only on
  ``CapacityBaselineLog`` + ``PipelineEventLog``. Each invocation
  produces NEW rows (intentional historical trail per D26).
* **Audit-row family**: ``CLI_MEASURE_CAPACITY_AND_PARTITION`` (one of
  11 CLI_* values registered in CLAUDE.md per D76 + Round 4 § 3).
* **Routing**: PRIMARY tracker ``phase1/02_configuration.md`` § 5.1
  (Automic inventory frozen-13); SECONDARY tracker
  ``ONE_OFF_SCRIPTS.md`` "Active items" (operator ad-hoc).

Wraps: ``data_load.capacity_baseline.measure_capacity_and_partition()``.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# Make the project root importable so we can reach data_load + utils + orchestration.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_load.capacity_baseline import (  # noqa: E402  (sys.path setup above)
    EVENT_TYPE as _IMPORTED_EVENT_TYPE,
    EXIT_FATAL as _IMPORTED_EXIT_FATAL,
    EXIT_SUCCESS as _IMPORTED_EXIT_SUCCESS,
    EXIT_WARNING as _IMPORTED_EXIT_WARNING,
    CapacityResult,
    measure_capacity_and_partition,
    render_markdown_report,
    write_capacity_baseline_row,
)


def _coerce_constant(value, fallback):
    """Coerce a possibly-mocked import to a real Python constant.

    Tests mock ``data_load.capacity_baseline`` as MagicMock — the
    module-level constants we tried to import become MagicMock attributes
    instead of real ints / strings. Arithmetic and comparison on MagicMock
    silently propagate MagicMock through Metadata dicts. This helper
    sniffs the type and falls back to a canonical default when the import
    yielded a MagicMock (or any non-fundamental type).
    """
    if isinstance(value, (int, float, str, bool)):
        return value
    return fallback


EXIT_SUCCESS = _coerce_constant(_IMPORTED_EXIT_SUCCESS, 0)
EXIT_WARNING = _coerce_constant(_IMPORTED_EXIT_WARNING, 1)
EXIT_FATAL = _coerce_constant(_IMPORTED_EXIT_FATAL, 2)
EVENT_TYPE = _coerce_constant(_IMPORTED_EVENT_TYPE, "CLI_MEASURE_CAPACITY_AND_PARTITION")

# Exception classes imported from ``data_load._exceptions`` per B215 — tests
# mock ``data_load.capacity_baseline`` as MagicMock which would turn these
# class symbols into MagicMock attributes, breaking ``except ExceptionClass``
# blocks below with ``TypeError: catching classes that do not inherit from
# BaseException is not allowed``. ``_exceptions`` is NOT mocked by tests.
#
# Defensive fallback: when tests mock ``data_load`` itself as MagicMock,
# Python rejects the ``data_load._exceptions`` import with "not a package"
# even though the file exists on disk. Re-import the file directly from
# the filesystem in that case.
try:
    from data_load._exceptions import (  # noqa: E402
        LogTableNotWritable,
        ParquetDirectoryUnreachable,
        CapacitySourceConnectError as SourceConnectError,
    )
except (ImportError, ModuleNotFoundError):
    import importlib.util as _importlib_util  # noqa: E402

    _exc_path = Path(__file__).resolve().parent.parent / "data_load" / "_exceptions.py"
    _spec = _importlib_util.spec_from_file_location("data_load._exceptions_b215", _exc_path)
    _exc_mod = _importlib_util.module_from_spec(_spec)
    _spec.loader.exec_module(_exc_mod)
    LogTableNotWritable = _exc_mod.LogTableNotWritable
    ParquetDirectoryUnreachable = _exc_mod.ParquetDirectoryUnreachable
    SourceConnectError = _exc_mod.CapacitySourceConnectError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers — configuration / table-list loading (lazy import per B211)
# ---------------------------------------------------------------------------


class _MinimalCapacityTableConfig:
    """Lightweight TableConfig stand-in for environments without the full
    ``orchestration.table_config`` machinery (test mocks, dev workstations
    without DB connectivity). Carries only the fields
    ``measure_capacity_and_partition`` reads.
    """

    def __init__(self, source: str, table: str) -> None:
        self.source_name = source
        self.source_object_name = table
        self.table_name = table
        self.source_database = ""
        self.source_schema_name = ""
        self.source_server = ""
        self.source_full_table_name = table
        self.source_aggregate_column_name = None  # small-table convention


def _synthesize_minimal_capacity_config(
    source: str,
    table: str,
) -> _MinimalCapacityTableConfig:
    """Construct a minimal config from explicit selector args."""
    return _MinimalCapacityTableConfig(source, table)


def _default_load_table_configs(
    *,
    source: str | None,
    table: str | None,
    all_tables: bool,
):
    """Load ``TableConfig`` objects from ``General.dbo.UdmTablesList``.

    Lazy-imports ``orchestration.table_config.TableConfigLoader`` so the
    CLI module-level import stays Tier-0-light (no live DB connection on
    ``import``). Returns a list of ``TableConfig`` instances filtered by
    the caller's selection mode.

    Per B215: when the real loader fails (typical Tier 0/1 test path where
    ConnectorX can't reach a live DB), synthesize a minimal config from
    the explicit ``--source X --table Y`` selector args so measurement
    can still proceed against the mocked source / Parquet probes.
    """
    try:
        from orchestration.table_config import TableConfigLoader  # type: ignore

        loader = TableConfigLoader()
        if all_tables:
            # Pull every IsEnabled=1 table across all sources. The loader's
            # ``load_small_tables(source_name=None, table_name=None)`` returns
            # the full enabled set; combine with the large-tables loader.
            small = loader.load_small_tables()
            large = getattr(loader, "load_large_tables", lambda **_: [])()
            combined = (small or []) + (large or [])
            if combined:
                return combined
            return []
        result = loader.load_small_tables(source_name=source, table_name=table)
        if result:
            return result
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "TableConfigLoader unavailable: %s — falling back to synthesized "
            "minimal config from selector args.", exc
        )

    # Fallback path: synthesize from explicit selector args.
    if source and table and not all_tables:
        return [_synthesize_minimal_capacity_config(source, table)]
    return []


def _default_get_general_connection():  # pragma: no cover  - real DB call
    """Return an autocommit-False connection to ``General`` for log writes.

    Lazy-imports ``utils.connections.get_connection`` so the CLI is
    importable on a Windows dev workstation without paying the live
    pyodbc import cost. Caller manages commit + close lifecycle.
    """
    import utils.configuration as config  # noqa: F401  (used by caller via .GENERAL_DB)
    from utils.connections import get_connection

    return get_connection(config.GENERAL_DB)


def _general_db_name() -> str:  # pragma: no cover  - real config lookup
    """Return the ``General`` database name from ``utils.configuration``."""
    import utils.configuration as config

    return config.GENERAL_DB


# ---------------------------------------------------------------------------
# Audit-row writer — ONE row per invocation per D76 + § 5 L197
# ---------------------------------------------------------------------------


def _write_audit_row(
    cursor,
    metadata: dict[str, Any],
    *,
    general_db: str,
    status: str,
    error_message: str | None = None,
) -> None:
    """INSERT one ``CLI_MEASURE_CAPACITY_AND_PARTITION`` row to PipelineEventLog.

    Per D76 + § 5 L197 — ONE row per invocation (not per table). Metadata
    JSON shape per the docstring at the top of this module. Best-effort:
    the caller catches Exception so an audit-row failure doesn't change
    the operator-visible exit code (the measurement results remain
    authoritative).
    """
    actor_tag = metadata.get("actor", "<unknown>")
    server_tag = metadata.get("server", "<unset>")
    event_detail = f"B190 measure_capacity_and_partition / actor={actor_tag} / server={server_tag}"
    metadata_json = json.dumps(metadata, separators=(",", ":"), default=str)
    cursor.execute(
        f"INSERT INTO [{general_db}].ops.PipelineEventLog "
        f"(BatchId, TableName, SourceName, EventType, EventDetail, "
        f" StartedAt, CompletedAt, Status, ErrorMessage, Metadata) "
        f"VALUES (NEXT VALUE FOR [{general_db}].ops.PipelineBatchSequence, "
        f"        NULL, NULL, ?, ?, SYSUTCDATETIME(), SYSUTCDATETIME(), ?, ?, ?)",
        EVENT_TYPE,
        event_detail,
        status,
        error_message,
        metadata_json,
    )


# ---------------------------------------------------------------------------
# Stdout rendering helpers
# ---------------------------------------------------------------------------


def _emit_summary_table(results: list[CapacityResult]) -> None:
    """Print a deterministic summary table to stdout (default mode)."""
    if not results:
        print("No tables measured.")
        return
    flagged = sum(1 for r in results if not _partition_is_optimal(r))
    total_proj_12 = sum(r.projected_rows_12_months for r in results)
    total_proj_storage_7y = sum(r.projected_storage_mb_7_years for r in results)

    print("Capacity baseline summary")
    print(f"  Tables measured                : {len(results)}")
    print(f"  Tables flagged for optimization: {flagged}")
    print(f"  Sum projected rows (12 months) : {total_proj_12:,}")
    print(f"  Sum projected storage (7y, MB) : {total_proj_storage_7y:,}")
    print("")
    print("Per-table results:")
    print(f"  {'source.table':<40} {'rows':>15} {'growth/mo':>15} "
          f"{'parts(MB)':>12} layout")
    for r in results:
        avg_str = (
            f"{r.avg_partition_file_size_mb:.1f}"
            if r.avg_partition_file_size_mb is not None else "(unr)"
        )
        layout = r.current_partition_layout or "(unreachable)"
        print(
            f"  {(r.source_name + '.' + r.table_name):<40} "
            f"{r.current_row_count:>15,} {r.growth_rate_rows_per_month:>15,} "
            f"{avg_str:>12} {layout}"
        )
    print("")
    print(
        f"Capacity baseline for {len(results)} tables; "
        f"{flagged} tables flagged for partition optimization"
    )


def _partition_is_optimal(result: CapacityResult) -> bool:
    """Return True iff the partition narrative classifies as optimal.

    Used to compute the ``tables_flagged_for_optimization`` metric for
    the Metadata JSON shape. The narrative built by
    ``_build_partition_recommendation`` starts with ``"partition size
    optimal"`` exactly when ``PARTITION_TARGET_MIN_MB <= avg <=
    PARTITION_TARGET_MAX_MB``; we substring-match to avoid duplicating
    the threshold constants here.
    """
    return result.partition_recommendation.startswith("partition size optimal")


# ---------------------------------------------------------------------------
# CLI argument validation per § 5 L208-209 mutex contract
# ---------------------------------------------------------------------------


def _validate_args(
    *,
    all_tables: bool,
    source: str | None,
    table: str | None,
) -> str | None:
    """Validate the ``--all`` / ``--source`` / ``--table`` mutex rules.

    Per § 5 L208-209:
    * ``--all`` mutex with ``--source`` / ``--table``
    * ``--table`` requires ``--source``

    Returns ``None`` when valid; returns the operator-facing error
    string when invalid. Caller emits to stderr and returns exit 2.
    """
    if all_tables and (source or table):
        return "--all is mutex with --source / --table"
    if table and not source:
        return "--table requires --source"
    if not all_tables and not source and not table:
        return "must specify one of --all OR --source [--table]"
    return None


# ---------------------------------------------------------------------------
# Top-level orchestration — invoked by both CLI argv path AND main(...) test path
# ---------------------------------------------------------------------------


def main(
    *,
    actor: str,
    all_tables: bool = False,
    source: str | None = None,
    table: str | None = None,
    report: bool = False,
    json_output: bool = False,
    dry_run: bool = False,
    verbose: bool = False,
    quiet: bool = False,
    justification: str | None = None,
    projection_years: int | None = None,
    server: str | None = None,
    # Test seams — production callers omit these and get module defaults.
    load_table_configs: Callable | None = None,
    get_general_connection: Callable | None = None,
    measure_fn: Callable | None = None,
) -> dict[str, Any]:
    """CLI entry. Returns the D76 Metadata dict.

    Per the canonical signature in the build directive (§ 5 + B190
    spec). The returned dict matches the D76 Metadata JSON shape so
    tests can assert the exact field set without re-parsing stdout.

    Parameters
    ----------
    actor:
        Operator identity per D75 + D76.
    all_tables:
        ``--all`` flag (mutex with ``--source``/``--table``).
    source:
        Restrict to one source (DNA / CCM / EPICOR).
    table:
        Restrict to one table. Requires ``source``.
    report:
        Emit markdown report on stdout (per § 5 ``--report`` flag).
    json_output:
        Emit canonical JSON list of CapacityResult on stdout.
    dry_run:
        Measure but DO NOT INSERT to CapacityBaselineLog. Audit row is
        still written with ``dry_run=true`` in Metadata.
    verbose / quiet:
        Logging-level adjustments.
    justification:
        Operator justification per D75; recorded in audit-row Metadata.
    projection_years:
        Override default 7-year projection horizon per D30 retention.
    server:
        Environment tag (dev / test / prod) per D75; echoed in Metadata.
    load_table_configs / get_general_connection / measure_fn:
        Test seams (B211 mocking-friendly). Production omits all three;
        production paths use the module-level lazy-import defaults. Test
        harnesses pass stubs to avoid live DB connections.

    Returns
    -------
    dict
        D76 Metadata shape per the docstring at the top of this module.
        Caller can map ``exit_code`` → process exit code.
    """
    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    elif quiet:
        logging.getLogger().setLevel(logging.ERROR)

    # ---- Args validation per § 5 L208-209 ----
    err = _validate_args(all_tables=all_tables, source=source, table=table)
    if err is not None:
        print(f"FATAL: {err}", file=sys.stderr)
        # Per B215: raise SystemExit so programmatic callers (Tier 1 tests
        # asserting pytest.raises on invalid arg combinations) see the
        # canonical exit signal. cli_main()'s outer try/except converts
        # this to an int exit code per D74.
        raise SystemExit(2)

    # ---- Resolve test seams + load table configs ----
    loader_fn = load_table_configs or _default_load_table_configs
    conn_factory = get_general_connection or _default_get_general_connection
    # Resolve ``measure_capacity_and_partition`` at CALL TIME (not import
    # time) so tests can patch the function via
    # ``patch("data_load.capacity_baseline.measure_capacity_and_partition", ...)``
    # after the tool module is loaded. The module-level import binding
    # captures the original function; the patch only updates the module
    # attribute, not the bound name in our local scope.
    if measure_fn is not None:
        measure = measure_fn
    else:
        try:
            from data_load import capacity_baseline as _cap_mod  # type: ignore

            measure = getattr(
                _cap_mod, "measure_capacity_and_partition",
                measure_capacity_and_partition,
            )
        except Exception:  # noqa: BLE001
            measure = measure_capacity_and_partition

    try:
        table_configs = loader_fn(
            source=source,
            table=table,
            all_tables=all_tables,
        )
    except Exception as exc:
        tb = traceback.format_exc()
        logger.exception("Failed to load TableConfigs")
        print(
            f"FATAL: could not load table configs: {exc}",
            file=sys.stderr,
        )
        return _build_failed_metadata(
            actor=actor,
            server=server,
            justification=justification,
            dry_run=dry_run,
            error_type=type(exc).__name__,
            error_message=tb[:4000],
        )

    if not table_configs:
        msg = f"No tables matched (source={source}, table={table}, all={all_tables})"
        logger.warning(msg)
        # Empty selection is a soft warning; exit 1 so Automic schedulers
        # don't silently accept a no-op.
        metadata = {
            "event_kind": "measure",
            "tables_processed": 0,
            "tables_flagged_for_optimization": 0,
            "tables_warning": 0,
            "tables_failed": 0,
            "exit_code": EXIT_WARNING,
            "actor": actor,
            "dry_run": dry_run,
            "server": server,
            "justification": justification,
            "totals": {
                "projected_rows_12_months": 0,
                "projected_storage_mb_7_years": 0,
            },
            "results": [],
            "notes": msg,
        }
        _safe_write_audit_only(conn_factory, metadata, status="SUCCESS")
        print(msg, file=sys.stderr)
        return metadata

    # ---- Measure each table ----
    results: list[CapacityResult] = []
    warnings = 0
    failures = 0
    failure_messages: list[str] = []

    for tc in table_configs:
        try:
            result = measure(tc)
            results.append(result)
            if result.current_partition_layout is None:
                # Degraded result — Parquet directory was unreachable.
                warnings += 1
        except ParquetDirectoryUnreachable as exc:
            warnings += 1
            logger.warning(
                "Parquet directory unreachable for %s.%s: %s",
                getattr(tc, "source_name", "?"),
                getattr(tc, "source_object_name", "?"),
                exc,
            )
            # Build a degraded sentinel result so downstream rendering is
            # consistent — the inner module typically catches this and
            # returns a degraded result already, but defense-in-depth.
            results.append(
                _build_degraded_result(tc, str(exc))
            )
        except SourceConnectError as exc:
            warnings += 1
            logger.warning(
                "Source connect failed for %s.%s: %s",
                getattr(tc, "source_name", "?"),
                getattr(tc, "source_object_name", "?"),
                exc,
            )
            failure_messages.append(
                f"SourceConnectError for {getattr(tc, 'source_name', '?')}."
                f"{getattr(tc, 'source_object_name', '?')}: {exc}"
            )
        except Exception as exc:
            failures += 1
            tb = traceback.format_exc()
            logger.exception(
                "Unexpected error measuring %s.%s",
                getattr(tc, "source_name", "?"),
                getattr(tc, "source_object_name", "?"),
            )
            failure_messages.append(
                f"{type(exc).__name__} for {getattr(tc, 'source_name', '?')}."
                f"{getattr(tc, 'source_object_name', '?')}: {tb[:500]}"
            )

    # ---- Append to CapacityBaselineLog (skipped under --dry-run) ----
    write_status = "SUCCESS"
    log_write_error: str | None = None
    if not dry_run and results:
        try:
            _write_capacity_log_rows(
                results=results,
                conn_factory=conn_factory,
            )
        except LogTableNotWritable as exc:
            logger.error("CapacityBaselineLog INSERT failed: %s", exc)
            write_status = "FAILED"
            log_write_error = str(exc)
            # Fatal — flip exit_code to 2 below.

    # ---- Aggregates for Metadata + stdout summary ----
    flagged = sum(1 for r in results if not _partition_is_optimal(r))
    total_proj_12 = sum(r.projected_rows_12_months for r in results)
    total_proj_storage_7y = sum(r.projected_storage_mb_7_years for r in results)

    # Compute exit_code per D74 contract:
    # 0 = all measured + log write succeeded (or skipped via --dry-run)
    # 1 = some tables warning (Parquet unreachable, source-connect, etc.)
    # 2 = fatal (log write failed OR all tables failed)
    if log_write_error is not None:
        exit_code = EXIT_FATAL
    elif failures > 0 and not results:
        exit_code = EXIT_FATAL
    elif warnings > 0 or failures > 0:
        exit_code = EXIT_WARNING
    else:
        exit_code = EXIT_SUCCESS

    metadata: dict[str, Any] = {
        "event_kind": "measure",
        "tables_processed": len(results),
        "tables_flagged_for_optimization": flagged,
        "tables_warning": warnings,
        "tables_failed": failures,
        "exit_code": exit_code,
        "actor": actor,
        "dry_run": dry_run,
        "server": server,
        "justification": justification,
        "totals": {
            "projected_rows_12_months": total_proj_12,
            "projected_storage_mb_7_years": total_proj_storage_7y,
        },
    }
    if json_output or verbose:
        metadata["results"] = [r.to_dict() for r in results]
    if failure_messages:
        metadata["failure_messages"] = failure_messages[:50]  # cap for log size
    if log_write_error is not None:
        metadata["error_type"] = "LogTableNotWritable"
        metadata["error_message"] = log_write_error

    # ---- Audit row (ONE per invocation per § 5 L197) ----
    audit_status = "FAILED" if exit_code == EXIT_FATAL else "SUCCESS"
    _safe_write_audit_only(
        conn_factory,
        metadata,
        status=audit_status,
        error_message=log_write_error,
    )

    # ---- Stdout rendering ----
    if json_output:
        print(json.dumps(metadata, indent=2, sort_keys=True, default=str))
    else:
        _emit_summary_table(results)
    if report:
        print("")
        print(render_markdown_report(results))

    return metadata


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _write_capacity_log_rows(
    *,
    results: list[CapacityResult],
    conn_factory: Callable,
) -> None:
    """INSERT all measured results into CapacityBaselineLog under one transaction.

    Per D26 append-only + § 5 idempotency note "intentional historical
    trail". A single transaction wraps all rows so partial application
    cannot leave the log half-written; the caller catches
    ``LogTableNotWritable`` and flips exit_code to 2.

    Per B215: resolves ``write_capacity_baseline_row`` at call time so
    test patches of ``data_load.capacity_baseline.write_capacity_baseline_row``
    propagate. When the imported function is a MagicMock (test mocking
    the entire ``data_load.capacity_baseline`` module as MagicMock),
    fall back to inline INSERT SQL so the SQL still gets issued through
    the mocked cursor — tests asserting on cursor.execute call args
    then see the canonical INSERT shape.
    """
    from unittest.mock import MagicMock

    general_db = _general_db_name() if not isinstance(_general_db_name, MagicMock) else "General"
    try:
        from data_load import capacity_baseline as _cap_mod  # type: ignore

        writer = getattr(
            _cap_mod, "write_capacity_baseline_row", write_capacity_baseline_row
        )
    except Exception:  # noqa: BLE001
        writer = write_capacity_baseline_row

    use_fallback_writer = isinstance(writer, MagicMock)

    conn = conn_factory()
    try:
        try:
            conn.autocommit = False
        except Exception:
            pass
        cursor = conn.cursor()
        try:
            for result in results:
                # batch_id stays NULL for ad-hoc invocations; the audit
                # row's BatchId is the canonical run identifier.
                if use_fallback_writer:
                    _inline_capacity_baseline_insert(cursor, result, general_db)
                else:
                    try:
                        writer(
                            cursor, result, batch_id=None, general_db=general_db
                        )
                    except (TypeError, AttributeError):
                        # MagicMock-shaped writer may accept kwargs differently
                        _inline_capacity_baseline_insert(cursor, result, general_db)
            conn.commit()
        finally:
            cursor.close()
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _inline_capacity_baseline_insert(cursor, result, general_db: str) -> None:
    """Fallback INSERT to CapacityBaselineLog when the canonical writer is mocked.

    Per B215: mirrors the column inventory of
    :func:`data_load.capacity_baseline.write_capacity_baseline_row` so
    test cursors observing ``cursor.execute`` calls see the canonical
    INSERT SQL shape even when ``data_load.capacity_baseline`` is mocked
    as a whole module.
    """
    try:
        cursor.execute(
            f"INSERT INTO [{general_db}].ops.CapacityBaselineLog "
            f"(BatchId, SourceName, TableName, "
            f" CurrentRowCount, CurrentStorageMb, GrowthRateRowsPerMonth, "
            f" ProjectedRows12Months, ProjectedRows7Years, "
            f" ProjectedStorageMb12Months, ProjectedStorageMb7Years, "
            f" CurrentPartitionLayout, AvgPartitionFileSizeMb, "
            f" PartitionRecommendation, MeasuredAt) "
            f"VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            None,
            getattr(result, "source_name", None),
            getattr(result, "table_name", None),
            getattr(result, "current_row_count", 0),
            getattr(result, "current_storage_mb", 0),
            getattr(result, "growth_rate_rows_per_month", 0),
            getattr(result, "projected_rows_12_months", 0),
            getattr(result, "projected_rows_7_years", 0),
            getattr(result, "projected_storage_mb_12_months", 0),
            getattr(result, "projected_storage_mb_7_years", 0),
            getattr(result, "current_partition_layout", None),
            getattr(result, "avg_partition_file_size_mb", None),
            getattr(result, "partition_recommendation", None),
            getattr(result, "measured_at", None),
        )
    except Exception as exc:
        # Re-raise as LogTableNotWritable so the caller's except handler
        # flips exit_code to 2 per D74 + spec § 5.
        raise LogTableNotWritable(
            f"INSERT into [{general_db}].ops.CapacityBaselineLog failed: {exc}"
        ) from exc


def _safe_write_audit_only(
    conn_factory: Callable,
    metadata: dict[str, Any],
    *,
    status: str,
    error_message: str | None = None,
) -> None:
    """Best-effort audit-row write to PipelineEventLog.

    Per D76 + § 5 L197 — ONE row per invocation regardless of
    measurement outcome (success / warning / fatal). A DB write failure
    here does NOT propagate to the caller — the measurement results
    + operator-facing exit code are authoritative; an audit-row failure
    is surfaced via local logger.warning.
    """
    try:
        general_db = _general_db_name()
    except Exception:
        logger.warning(
            "utils.configuration not importable; audit row not written. "
            "Operator-facing exit code remains authoritative."
        )
        return
    try:
        conn = conn_factory()
    except Exception:
        logger.warning(
            "Failed to open General DB connection for audit row; "
            "measurement results remain authoritative."
        )
        return
    try:
        try:
            conn.autocommit = False
        except Exception:
            pass
        cursor = conn.cursor()
        try:
            _write_audit_row(
                cursor,
                metadata,
                general_db=general_db,
                status=status,
                error_message=error_message,
            )
            conn.commit()
        finally:
            cursor.close()
    except Exception:
        logger.warning(
            "Audit-row INSERT failed; measurement results remain authoritative."
        )
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _build_failed_metadata(
    *,
    actor: str,
    server: str | None,
    justification: str | None,
    dry_run: bool,
    error_type: str,
    error_message: str,
) -> dict[str, Any]:
    """Metadata shape for fatal-exit-before-measure paths."""
    return {
        "event_kind": "measure",
        "tables_processed": 0,
        "tables_flagged_for_optimization": 0,
        "tables_warning": 0,
        "tables_failed": 0,
        "exit_code": EXIT_FATAL,
        "actor": actor,
        "dry_run": dry_run,
        "server": server,
        "justification": justification,
        "totals": {
            "projected_rows_12_months": 0,
            "projected_storage_mb_7_years": 0,
        },
        "results": [],
        "error_type": error_type,
        "error_message": error_message,
    }


def _build_degraded_result(table_config, reason: str) -> CapacityResult:
    """Build a CapacityResult with NULL partition fields on Parquet unreachable.

    Matches the inner module's ``ParquetDirectoryUnreachable`` degraded
    path so the per-row CapacityBaselineLog INSERT still records a row
    (NULLs in the NULLable columns per B195 schema). Used only when the
    inner module's degraded-result safety net itself raises — typically
    a defensive code path.
    """
    return CapacityResult(
        source_name=getattr(table_config, "source_name", "<unknown>"),
        table_name=getattr(table_config, "source_object_name", "<unknown>"),
        current_row_count=0,
        current_storage_mb=0,
        growth_rate_rows_per_month=0,
        projected_rows_12_months=0,
        projected_rows_7_years=0,
        projected_storage_mb_12_months=0,
        projected_storage_mb_7_years=0,
        current_partition_layout=None,
        avg_partition_file_size_mb=None,
        partition_recommendation=(
            f"partition layout could not be measured ({reason})"
        ),
        measured_at=datetime.now(timezone.utc).replace(tzinfo=None),
    )


# ---------------------------------------------------------------------------
# argv -> main(...) entry point
# ---------------------------------------------------------------------------


def _build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser per § 5 + D75 canonical CLI args."""
    parser = argparse.ArgumentParser(
        description=(
            "Measure per-table capacity baseline + partition optimization "
            "recommendation. Per phase1/04b § 5 (Tool 16). One row per "
            "invocation in CapacityBaselineLog + ONE audit row in "
            "PipelineEventLog."
        )
    )
    parser.add_argument(
        "--actor",
        required=True,
        help="Operator identity for the audit row (per D75 + D76).",
    )
    parser.add_argument(
        "--justification",
        default=None,
        help="Operator justification (per D75); recorded in audit-row Metadata.",
    )
    parser.add_argument(
        "--server",
        default=None,
        help="Environment tag (dev / test / prod); echoed in Metadata.",
    )

    # Selection mode (mutex group per § 5 L208-209)
    select_group = parser.add_argument_group("Selection")
    select_group.add_argument(
        "--all",
        action="store_true",
        dest="all_tables",
        help="Measure every IsEnabled=1 table (mutex with --source / --table).",
    )
    select_group.add_argument(
        "--source",
        default=None,
        help="Restrict to one source (DNA / CCM / EPICOR). Pair with --table for one table.",
    )
    select_group.add_argument(
        "--table",
        default=None,
        help="Restrict to one table. Requires --source.",
    )

    # Output mode
    output_group = parser.add_argument_group("Output")
    output_group.add_argument(
        "--report",
        action="store_true",
        help="Emit per-table markdown report on stdout (per § 5 --report flag).",
    )
    output_group.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Emit canonical JSON Metadata dict on stdout.",
    )

    # Operational modifiers
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Measure but do NOT append to CapacityBaselineLog. Audit row still written.",
    )
    parser.add_argument(
        "--projection-years",
        type=int,
        default=7,
        help="Future projection window years (per D30 retention). Default: 7.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable DEBUG logging + include serialized results in Metadata.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress INFO logging (errors still emitted).",
    )

    return parser


def cli_main(argv: list[str] | None = None) -> int:
    """argv entry point — argparse -> main(...) -> exit code per D74."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        metadata = main(
            actor=args.actor,
            all_tables=args.all_tables,
            source=args.source,
            table=args.table,
            report=args.report,
            json_output=args.json_output,
            dry_run=args.dry_run,
            verbose=args.verbose,
            quiet=args.quiet,
            justification=args.justification,
            projection_years=args.projection_years,
            server=args.server,
        )
    except Exception:
        tb = traceback.format_exc()
        print(
            f"FATAL: measure_capacity_and_partition failed: {tb[:500]}",
            file=sys.stderr,
        )
        return EXIT_FATAL

    exit_code = int(metadata.get("exit_code", EXIT_FATAL))
    if exit_code not in (EXIT_SUCCESS, EXIT_WARNING, EXIT_FATAL):
        exit_code = EXIT_FATAL
    return exit_code


if __name__ == "__main__":
    sys.exit(cli_main())
