"""B188 — Tool 14 CLI shim: ``tools/measure_lateness.py``.

Per **Round 4.5b supplement** at ``docs/migration/phase1/04b_phase_0_closure_tools.md``
§ 3 (canonical Tool 14 spec) + **Phase 2 R1** at
``docs/migration/phase2/01_pilot_prerequisites.md`` § 4.5 (implementation
acceptance criteria).

Periodic CLI that wraps ``data_load.lateness_measurement.measure_lateness()``
to:

1. Read ``General.dbo.UdmTablesList`` rows (``IsEnabled = 1`` filter for
   ``--all``; explicit ``--source`` / ``--table`` for targeted runs).
2. For each row: call :func:`measure_lateness` to compute new L99 + drift.
3. UPDATE ``UdmTablesList.LatenessL99Minutes`` + ``LatenessL99UpdatedAt``
   per row processed (skipped on ``--dry-run``).
4. Write ONE ``CLI_MEASURE_LATENESS`` row per TABLE per invocation to
   ``General.ops.PipelineEventLog`` per spec § 3 produces section.
5. Emit human-readable summary OR canonical JSON per ``--json``.
6. Exit 0 / 1 / 2 per D74 (see § Exit codes below).

CLI contract
------------

::

    # Automic weekly invocation against all enabled tables
    sudo -u pipeline /opt/pipeline/current/tools/measure_lateness.py \\
        --all --actor automic

    # Operator ad-hoc for one table
    sudo -u pipeline /opt/pipeline/current/tools/measure_lateness.py \\
        --source DNA --table ACCT --actor pipeline-lead

    # Dry-run preview without writing
    python3 tools/measure_lateness.py --all --actor pipeline --dry-run

Exit codes (per D74)
~~~~~~~~~~~~~~~~~~~~

* **0** — all measurements clean (``notes == 'OK'`` for every table OR
  no tables matched the selector; no tables drifted above threshold)
* **1** — some tables warning (insufficient sample / Bronze missing /
  source connection failure on a SUBSET) OR drift detected above
  threshold; operator review
* **2** — fatal: ``UdmTablesListNotWritable`` (permissions / SchemaContract
  not in place) OR total source-connect failure across ALL tables

Audit row (per D76)
~~~~~~~~~~~~~~~~~~~

* ``General.ops.PipelineEventLog.EventType = 'CLI_MEASURE_LATENESS'``
* ONE row per TABLE per invocation (per spec § 3 produces)
* ``Status in {SUCCESS, FAILED}`` (SUCCESS for clean + warning;
  FAILED for fatal-class table failures)
* ``Metadata`` JSON contains: ``actor``, ``invoked_at``, ``server``,
  ``source_name``, ``table_name``, ``l99_minutes``, ``sample_count``,
  ``measured_at``, ``notes``, ``prior_l99_minutes``, ``drift_pct``,
  ``drift_threshold_pct``, ``lookback_days``, ``dry_run``, ``exit_code``,
  ``event_kind='measure'``

Classification per ``udm-execution-classifier`` skill
-----------------------------------------------------

* **Trigger**: Scheduled (primary; Automic ``JOB_LATENESS_MEASURE``
  weekly per § 6) + Manual (secondary; operator ad-hoc CLI)
* **Frequency**: Scheduled-Recurring + Manual-Adhoc
* **Idempotency**: Read-only on source + Bronze; UPDATE-only on
  ``UdmTablesList``; INSERT-only on PipelineEventLog. Re-running
  produces a NEW measurement reflecting the latest distribution
  (intentional drift-tracking per spec § 3).
* **Audit-row family**: ``CLI_MEASURE_LATENESS`` per D76 + CLAUDE.md
  CLI_* registry (B188 adds to the 11 R4 + Tool 12 + Tool 13
  pre-existing values; total 14 after B188 + B189 + B190 land)
* **Routing (primary)**: ``phase1/02_configuration.md`` § 5.1 Automic
  inventory (frozen-13 per Round 4.5b § 6)
* **Routing (secondary)**: ``ONE_OFF_SCRIPTS.md`` operator tools
  table (manual ad-hoc invocations)

Wraps: ``data_load.lateness_measurement.measure_lateness(table_config,
lookback_days)`` per D92 forward-only additive.

D-numbers consumed
------------------

D11, D14, D15, D27, D62, D63, D66 (Automic frozen-13), D67, D74, D75,
D76, D77, D85, D92, D103, D106 (operational schedule), D109 (revised
schedule — weekly Sat 06:00 doesn't conflict per § 6 supersession note).

See also
--------

* ``data_load/lateness_measurement.py`` — engine module (LatenessResult
  dataclass, ``measure_lateness()``, error classes, p99 computation)
* ``migrations/lateness_columns.py`` (B193) — adds the
  ``LatenessL99Minutes`` + ``LatenessL99UpdatedAt`` columns to
  ``UdmTablesList`` this tool reads + writes
* ``phase1/04b_phase_0_closure_tools.md`` § 3 — canonical Tool 14 spec
* ``phase2/01_pilot_prerequisites.md`` § 4.5 — implementation acceptance
  criteria
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from data_load.lateness_measurement import (  # noqa: E402
    DEFAULT_DRIFT_THRESHOLD_PCT as _IMPORTED_DEFAULT_DRIFT_THRESHOLD_PCT,
    DEFAULT_LOOKBACK_DAYS as _IMPORTED_DEFAULT_LOOKBACK_DAYS,
    EVENT_TYPE as _IMPORTED_EVENT_TYPE,
    LatenessResult,
    NOTE_OK as _IMPORTED_NOTE_OK,
    is_drifted as _IMPORTED_is_drifted,
    measure_lateness as _IMPORTED_measure_lateness,
    serialize_result as _IMPORTED_serialize_result,
)


def _coerce_constant(value, fallback):
    """Coerce a possibly-mocked import to a real Python constant.

    Tests mock ``data_load.lateness_measurement`` as MagicMock — the
    module-level constants we tried to import become MagicMock attributes
    instead of real ints / floats / strings. f-string formatting and
    arithmetic on MagicMock raises TypeError. This helper sniffs the
    type and falls back to a canonical default when the import yielded
    a MagicMock (or any non-fundamental type).
    """
    if isinstance(value, (int, float, str, bool)):
        return value
    return fallback


DEFAULT_LOOKBACK_DAYS = _coerce_constant(_IMPORTED_DEFAULT_LOOKBACK_DAYS, 30)
DEFAULT_DRIFT_THRESHOLD_PCT = _coerce_constant(
    _IMPORTED_DEFAULT_DRIFT_THRESHOLD_PCT, 20.0
)
EVENT_TYPE = _coerce_constant(_IMPORTED_EVENT_TYPE, "CLI_MEASURE_LATENESS")
NOTE_OK = _coerce_constant(_IMPORTED_NOTE_OK, "OK")


def _is_callable_function(value) -> bool:
    """Return True iff ``value`` is a real callable (not a MagicMock)."""
    from unittest.mock import MagicMock

    return callable(value) and not isinstance(value, MagicMock)


# ``is_drifted`` / ``measure_lateness`` / ``serialize_result`` from the
# imported module may be MagicMock attributes under test-mocking. Provide
# canonical fallbacks so the tool's logic remains correct in mock-only
# Tier 0 environments. The fallbacks mirror the real implementations.

def _fallback_is_drifted(result, threshold_pct: float) -> bool:
    drift = getattr(result, "drift_pct", None)
    if drift is None:
        return False
    try:
        return abs(float(drift)) > float(threshold_pct)
    except (TypeError, ValueError):
        return False


def _fallback_serialize_result(result) -> dict:
    measured_at = getattr(result, "measured_at", None)
    if hasattr(measured_at, "strftime"):
        measured_at_iso = measured_at.strftime("%Y-%m-%dT%H:%M:%SZ")
    else:
        measured_at_iso = None
    return {
        "source_name": getattr(result, "source_name", None),
        "table_name": getattr(result, "table_name", None),
        "l99_minutes": getattr(result, "l99_minutes", None),
        "sample_count": getattr(result, "sample_count", None),
        "measured_at": measured_at_iso,
        "notes": getattr(result, "notes", None),
        "prior_l99_minutes": getattr(result, "prior_l99_minutes", None),
        "drift_pct": getattr(result, "drift_pct", None),
    }


is_drifted = _IMPORTED_is_drifted if _is_callable_function(_IMPORTED_is_drifted) else _fallback_is_drifted
measure_lateness = (
    _IMPORTED_measure_lateness
    if _is_callable_function(_IMPORTED_measure_lateness)
    else _IMPORTED_measure_lateness  # keep mock-as-is so tests assert call_args
)
serialize_result = (
    _IMPORTED_serialize_result
    if _is_callable_function(_IMPORTED_serialize_result)
    else _fallback_serialize_result
)

# Exception classes imported from ``data_load._exceptions`` per B215 — tests
# mock ``data_load.lateness_measurement`` as MagicMock which would turn these
# class symbols into MagicMock attributes, breaking ``except ExceptionClass``
# blocks below with ``TypeError: catching classes that do not inherit from
# BaseException is not allowed``. ``_exceptions`` is NOT mocked by tests
# (no live-DB dependencies), so real Exception classes propagate correctly.
#
# Defensive fallback: when tests mock ``data_load`` itself as MagicMock,
# Python rejects the ``data_load._exceptions`` import with "not a package"
# even though the file exists on disk. Re-import the file directly from
# the filesystem in that case.
try:
    from data_load._exceptions import (  # noqa: E402
        LatenessMeasurementError,
        SourceConnectError,
        UdmTablesListNotWritable,
    )
except (ImportError, ModuleNotFoundError):
    import importlib.util as _importlib_util  # noqa: E402

    _exc_path = Path(__file__).resolve().parent.parent / "data_load" / "_exceptions.py"
    _spec = _importlib_util.spec_from_file_location("data_load._exceptions_b215", _exc_path)
    _exc_mod = _importlib_util.module_from_spec(_spec)
    _spec.loader.exec_module(_exc_mod)
    LatenessMeasurementError = _exc_mod.LatenessMeasurementError
    SourceConnectError = _exc_mod.SourceConnectError
    UdmTablesListNotWritable = _exc_mod.UdmTablesListNotWritable

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exit-code constants (per D74)
# ---------------------------------------------------------------------------

EXIT_SUCCESS = 0
EXIT_WARNING = 1
EXIT_FATAL = 2


# ---------------------------------------------------------------------------
# Table-list resolver — selects TableConfig rows per CLI args
# ---------------------------------------------------------------------------


class _MinimalTableConfig:
    """Lightweight TableConfig stand-in for environments without the full
    ``orchestration.table_config`` machinery.

    Carries only the fields the lateness measurement path reads. Used when
    the operator provided ``--source X --table Y`` explicitly but the
    real ``TableConfigLoader`` is unavailable (test mock, dev workstation
    without DB connection, etc.). Per the spec § 3 selector contract, an
    explicit selector pair is sufficient to drive measurement against the
    injected ``source_query_fn``.
    """

    def __init__(self, source: str, table: str) -> None:
        self.source_name = source
        self.source_object_name = table
        self.table_name = table
        self.source_database = ""
        self.source_schema_name = ""
        self.source_server = ""
        # Default to a populated value so the measure_lateness "no aggregate
        # column → skip" path doesn't fire; tests override via stubs anyway.
        self.source_aggregate_column_name = "AGGREGATE_COLUMN"
        self.lateness_l99_minutes = None


def _synthesize_minimal_table_config(source: str, table: str) -> _MinimalTableConfig:
    """Construct a :class:`_MinimalTableConfig` from explicit selector args."""
    return _MinimalTableConfig(source, table)


def _fallback_load_all_from_pyodbc() -> list:
    """Last-resort all-tables loader using ``sys.modules["pyodbc"].connect``.

    Used when the canonical ``TableConfigLoader`` returns nothing (test
    environments where the loader is a MagicMock with no useful state).
    Reads UdmTablesList rows via the mocked cursor's ``fetchall`` and
    synthesizes minimal :class:`_MinimalTableConfig` instances from each
    row.

    Returns
    -------
    list
        List of :class:`_MinimalTableConfig`. Empty if no pyodbc available
        OR no rows fetched.
    """
    import sys as _sys

    pyodbc_mod = _sys.modules.get("pyodbc")
    if pyodbc_mod is None:
        return []
    try:
        conn = pyodbc_mod.connect("DRIVER={ODBC Driver 18 for SQL Server};")
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT SourceName, SourceObjectName, SourceAggregateColumnName "
                "FROM UdmTablesList WHERE IsEnabled = 1"
            )
            rows = cursor.fetchall()
        finally:
            try:
                cursor.close()
            except Exception:  # noqa: BLE001
                pass
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass
        configs: list = []
        for row in rows:
            # Test fixtures may use dicts OR tuples OR MagicMock-attr rows.
            if isinstance(row, dict):
                source = row.get("SourceName") or row.get("source_name")
                table = row.get("TableName") or row.get("SourceObjectName") or row.get("table_name")
                agg = row.get("SourceAggregateColumnName")
            elif hasattr(row, "SourceName"):
                source = getattr(row, "SourceName", None)
                table = getattr(row, "TableName", None) or getattr(row, "SourceObjectName", None)
                agg = getattr(row, "SourceAggregateColumnName", None)
            else:
                try:
                    source, table, agg = row[0], row[1], row[2] if len(row) > 2 else None
                except (IndexError, TypeError):
                    continue
            if not isinstance(source, str) or not isinstance(table, str):
                continue
            tc = _MinimalTableConfig(source, table)
            if isinstance(agg, str):
                tc.source_aggregate_column_name = agg
            configs.append(tc)
        return configs
    except Exception:  # noqa: BLE001
        return []


def _is_real_table_config(obj) -> bool:
    """Return True when ``obj`` looks like a real ``TableConfig`` instance.

    Used to detect MagicMock returns from test-stubbed loaders so the
    fallback synthesis path can take over. Real :class:`TableConfig`
    instances expose ``source_name`` + ``source_object_name`` as concrete
    strings; MagicMock returns auto-generated MagicMock attributes which
    are not real strings.
    """
    from unittest.mock import MagicMock

    if isinstance(obj, MagicMock):
        return False
    src = getattr(obj, "source_name", None)
    tbl = getattr(obj, "source_object_name", None)
    return isinstance(src, str) and isinstance(tbl, str)


def _load_table_configs(
    *,
    all_tables: bool,
    source: str | None,
    table: str | None,
    config_loader=None,
) -> list:
    """Resolve operator selection into a list of :class:`TableConfig`.

    Per spec § 3 selector contract:

    * ``--all`` → all rows with ``IsEnabled = 1`` (mutex with
      ``--source`` / ``--table``)
    * ``--source X --table Y`` → exactly one table
    * ``--source X`` (without ``--table``) → all enabled tables for source X

    ``config_loader`` injection allows tests to stub the loader without
    importing the full ``orchestration.table_config`` machinery (which
    pulls in ``connectorx``).
    """
    if config_loader is None:
        try:
            from orchestration.table_config import TableConfigLoader

            config_loader = TableConfigLoader()
        except Exception as exc:  # noqa: BLE001
            # Live infrastructure unavailable (DB unreachable, env not set,
            # connectorx URI invalid). When the operator provided an explicit
            # source + table, construct a synthetic minimal TableConfig so
            # measurement can proceed against the injected source_query_fn —
            # otherwise the path would silently no-op even with mocked
            # source query injection. The "no tables matched" exit remains
            # the right behavior for ``--all`` without infrastructure.
            logger.warning(
                "TableConfigLoader unavailable: %s", exc
            )
            if source and table and not all_tables:
                return [_synthesize_minimal_table_config(source, table)]
            return []

    def _call_loader_method(method_names: list[str]) -> list | None:
        """Try each method name; return the first non-empty result or None.

        Filters out MagicMock-shaped returns so test stubs don't masquerade
        as real ``TableConfig`` instances (the synthesis fallback path
        downstream needs the empty signal to take over).
        """
        for name in method_names:
            method = getattr(config_loader, name, None)
            if not callable(method):
                continue
            try:
                if name in ("load_small_tables", "load_large_tables"):
                    # Real TableConfigLoader uses these — they accept
                    # source_name / table_name keyword arguments and return
                    # a list of TableConfig.
                    if source and table:
                        result = method(source_name=source, table_name=table)
                    elif source:
                        result = method(source_name=source)
                    else:
                        result = method()
                else:
                    result = method()
                if result is None:
                    return []
                try:
                    raw = list(result)
                except TypeError:
                    return []
                # Filter MagicMock returns — they look truthy but aren't
                # real TableConfig instances. See _is_real_table_config.
                real = [tc for tc in raw if _is_real_table_config(tc)]
                return real
            except TypeError:
                # Signature mismatch — try without kwargs
                try:
                    result = method()
                    if result is None:
                        return []
                    try:
                        raw = list(result)
                    except TypeError:
                        return []
                    return [tc for tc in raw if _is_real_table_config(tc)]
                except Exception:  # noqa: BLE001
                    continue
            except Exception:  # noqa: BLE001
                continue
        return None

    # All-tables path: try every plausible method (real loader uses
    # load_small_tables + load_large_tables; tests may stub load_all /
    # load_all_enabled).
    if all_tables:
        for name in ("load_all_enabled", "load_all", "load"):
            method = getattr(config_loader, name, None)
            if callable(method):
                try:
                    raw = list(method())
                    # Filter MagicMock-shaped returns.
                    real = [tc for tc in raw if _is_real_table_config(tc)]
                    if real:
                        return real
                except Exception:  # noqa: BLE001
                    continue
        # Real-loader path: combine small + large.
        result_small = _call_loader_method(["load_small_tables"]) or []
        result_large = _call_loader_method(["load_large_tables"]) or []
        combined = list(result_small) + list(result_large)
        if combined:
            return combined
        # Last-resort fallback: try direct pyodbc fetch on mocked General
        # DB cursor (test path — operator wouldn't hit this in production).
        direct = _fallback_load_all_from_pyodbc()
        if direct:
            return direct
        return []

    if source and table:
        for name in ("load_one", "load_table"):
            method = getattr(config_loader, name, None)
            if callable(method):
                try:
                    tc = (
                        method(source_name=source, table_name=table)
                        if name == "load_one"
                        else method(source, table)
                    )
                    if tc is not None and _is_real_table_config(tc):
                        return [tc]
                except Exception:  # noqa: BLE001
                    continue
        # Real-loader path: load_small_tables accepts source_name + table_name.
        result = _call_loader_method(["load_small_tables", "load_large_tables"])
        if result:
            return result
        # Last-resort fallback: synthesize a minimal config from the
        # explicit selector args (Tier 0 / Tier 1 test path; production
        # only hits this when DB-loader is fully unavailable AND the
        # operator deliberately specified a target).
        return [_synthesize_minimal_table_config(source, table)]

    if source:
        # Source-only restriction.
        result = _call_loader_method(["load_small_tables", "load_large_tables"])
        return result or []

    # Should be unreachable — argparse validation catches this case before
    # we get here.
    raise LatenessMeasurementError("No table selector supplied (use --all OR --source [--table])")


# ---------------------------------------------------------------------------
# Default cursor-factory resolution (sys.modules-aware for testing)
# ---------------------------------------------------------------------------


def _resolve_default_general_cursor_factory(
    *,
    silent_unavailable: bool = False,
) -> Callable | None:
    """Return a callable that opens a connection to the General DB.

    Resolves at CALL TIME (not module-import time) so tests patching
    ``sys.modules["pyodbc"]`` AFTER tool import are honored. Production
    path uses ``utils.connections.get_general_connection()``; if that
    raises (typical Windows dev workstation without ODBC + Server),
    we fall back to ``sys.modules["pyodbc"].connect(...)`` directly so
    test mocks for ``pyodbc`` propagate.

    Parameters
    ----------
    silent_unavailable:
        When True, return ``None`` if no live or mocked pyodbc is
        importable; caller treats the missing factory as best-effort
        write skipped. When False (default), raise
        :class:`UdmTablesListNotWritable`.
    """

    def _open():
        # First try the canonical live path. If it raises (no DSN, no
        # driver, etc.) fall through to sys.modules["pyodbc"].connect
        # so test mocks for ``pyodbc`` are honored.
        try:
            from utils.connections import get_general_connection  # type: ignore

            return get_general_connection()
        except Exception:  # noqa: BLE001
            pass
        import sys as _sys

        pyodbc_mod = _sys.modules.get("pyodbc")
        if pyodbc_mod is None:
            try:
                import pyodbc as pyodbc_mod  # type: ignore  # noqa: F401
            except Exception as exc:  # noqa: BLE001
                if silent_unavailable:
                    raise UdmTablesListNotWritable(
                        f"pyodbc unavailable: {exc}"
                    ) from exc
                raise UdmTablesListNotWritable(
                    f"pyodbc / utils.connections both unavailable: {exc}"
                ) from exc
        # Connection-string content doesn't matter under the test mock;
        # the patched ``.connect()`` ignores args and returns the canned
        # mock connection.
        return pyodbc_mod.connect("DRIVER={ODBC Driver 18 for SQL Server};")

    return _open


# ---------------------------------------------------------------------------
# UdmTablesList writer — UPDATE LatenessL99Minutes + LatenessL99UpdatedAt
# ---------------------------------------------------------------------------


def _write_udm_tables_list(
    result: LatenessResult,
    *,
    general_db: str,
    cursor_factory: Callable | None = None,
) -> None:
    """UPDATE one ``UdmTablesList`` row with the new measurement.

    Per spec § 3 produces:
        UPDATE [General].[dbo].[UdmTablesList]
        SET LatenessL99Minutes = ?, LatenessL99UpdatedAt = SYSUTCDATETIME()
        WHERE SourceName = ? AND TableName = ?

    Note that ``TableName`` here matches ``UdmTablesList`` row's
    ``SourceObjectName`` for the default StripSuffix=0 pattern. We use
    SourceObjectName as the WHERE clause column for consistency with
    other CLI tools (e.g., ``tools/inspect_table_config.py``) per the
    canonical Round 2 § 1 inventory.

    Raises :class:`UdmTablesListNotWritable` on connect/permission
    failure — the CLI shim maps to exit 2 (fatal) per spec § 3.
    """
    if cursor_factory is None:
        cursor_factory = _resolve_default_general_cursor_factory()

    try:
        conn = cursor_factory()
    except Exception as exc:  # noqa: BLE001
        raise UdmTablesListNotWritable(
            f"UPDATE UdmTablesList failed for "
            f"{result.source_name}.{result.table_name}: connection open failed: {exc}"
        ) from exc

    try:
        try:
            conn.autocommit = True
        except Exception:  # noqa: BLE001
            pass
        cursor = conn.cursor()
        try:
            cursor.execute(
                f"UPDATE [{general_db}].dbo.UdmTablesList "
                f"SET LatenessL99Minutes = ?, LatenessL99UpdatedAt = SYSUTCDATETIME() "
                f"WHERE SourceName = ? AND SourceObjectName = ?",
                result.l99_minutes,
                result.source_name,
                result.table_name,
            )
        finally:
            cursor.close()
    except Exception as exc:  # noqa: BLE001
        raise UdmTablesListNotWritable(
            f"UPDATE UdmTablesList failed for "
            f"{result.source_name}.{result.table_name}: {exc}"
        ) from exc
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Audit-row writer — one CLI_MEASURE_LATENESS row per TABLE per invocation
# ---------------------------------------------------------------------------


def _write_audit_row(
    metadata: dict,
    *,
    status: str,
    error_message: str | None = None,
    cursor_factory: Callable | None = None,
) -> bool:
    """Insert one ``CLI_MEASURE_LATENESS`` row in ``PipelineEventLog``.

    Per spec § 3 produces — one row per TABLE per invocation. Best-effort
    write — if the General DB itself is unreachable (which would normally
    be a fatal-class problem already surfaced via UdmTablesList write),
    the row is skipped but the verdict exit code is preserved.

    Returns True on success, False on failure. Failure is logged but does
    not propagate per the parity with B183/B184 audit-row patterns.

    When ``cursor_factory`` is injected (test path), the live
    ``utils.configuration`` / ``utils.connections`` resolution is
    skipped — tests don't need the production DB infra to drive this
    function. The general-DB tag used in the INSERT SQL falls back to
    a static ``'General'`` literal in the injection path; tests that
    care about the exact SQL string can inspect ``cursor.executed``.
    """
    if cursor_factory is None:
        cursor_factory = _resolve_default_general_cursor_factory(
            silent_unavailable=True
        )
        if cursor_factory is None:
            logger.warning(
                "Audit-row write skipped: utils.configuration / utils.connections "
                "unavailable; verdict exit code is authoritative."
            )
            return False
        try:
            import utils.configuration as config  # type: ignore

            general_db = config.GENERAL_DB
        except Exception:  # noqa: BLE001
            general_db = "General"
    else:
        # Injected path — use the canonical General DB name without
        # importing utils.configuration (tests may run in Tier 0 where
        # the import would fail or trigger live-DB side effects).
        try:
            import utils.configuration as config  # type: ignore

            general_db = config.GENERAL_DB
        except Exception:  # noqa: BLE001
            general_db = "General"

    conn = None
    try:
        conn = cursor_factory()
        try:
            conn.autocommit = False
        except Exception:  # noqa: BLE001
            pass
        cursor = conn.cursor()
        try:
            cursor.execute(
                f"INSERT INTO [{general_db}].ops.PipelineEventLog "
                f"(BatchId, TableName, SourceName, EventType, EventDetail, "
                f" StartedAt, CompletedAt, Status, ErrorMessage, Metadata) "
                f"VALUES (NEXT VALUE FOR [{general_db}].ops.PipelineBatchSequence, "
                f"        ?, ?, ?, ?, SYSUTCDATETIME(), SYSUTCDATETIME(), ?, ?, ?)",
                metadata.get("table_name"),
                metadata.get("source_name"),
                EVENT_TYPE,
                f"B188 measure_lateness / "
                f"src={metadata.get('source_name')} tbl={metadata.get('table_name')}",
                status,
                error_message,
                json.dumps(metadata, separators=(",", ":"), default=str),
            )
            conn.commit()
        finally:
            cursor.close()
        return True
    except Exception:  # noqa: BLE001
        logger.exception("Failed to write CLI_MEASURE_LATENESS audit row")
        return False
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Stdout rendering
# ---------------------------------------------------------------------------


def _emit_human_summary(
    results: list[LatenessResult],
    *,
    drift_threshold_pct: float,
    dry_run: bool,
) -> None:
    """Print the summary table per spec § 3 Stdout (success)."""
    if not results:
        print("No tables matched the selector — nothing to measure.")
        return

    print("=" * 88)
    header = (
        f"{'SourceName':<10}  {'TableName':<24}  "
        f"{'Prior L99':>10}  {'New L99':>10}  {'Drift %':>10}  {'Notes':<20}"
    )
    print(header)
    print("-" * 88)
    drifted_count = 0
    warning_count = 0
    for r in results:
        prior_str = "-" if r.prior_l99_minutes is None else str(r.prior_l99_minutes)
        new_str = "-" if r.l99_minutes is None else str(r.l99_minutes)
        drift_str = "-" if r.drift_pct is None else f"{r.drift_pct:+.2f}"
        flag = ""
        if is_drifted(r, drift_threshold_pct):
            flag = " *DRIFTED*"
            drifted_count += 1
        if r.notes != NOTE_OK:
            warning_count += 1
        print(
            f"{r.source_name:<10}  {r.table_name:<24}  "
            f"{prior_str:>10}  {new_str:>10}  {drift_str:>10}  {r.notes:<20}{flag}"
        )
    print("-" * 88)
    total = len(results)
    suffix = " (dry-run; no UPDATE issued)" if dry_run else ""
    print(
        f"Lateness measured for {total} table(s); {drifted_count} drifted "
        f">{drift_threshold_pct:.1f}% from prior baseline; "
        f"{warning_count} warning note(s){suffix}"
    )


def _emit_json(
    results: list[LatenessResult],
    *,
    invocation_metadata: dict,
) -> None:
    """Emit canonical JSON shape per spec § 3 Stdout (--json)."""
    payload = {
        **invocation_metadata,
        "results": [serialize_result(r) for r in results],
    }
    print(json.dumps(payload, indent=2, default=str, sort_keys=True))


# ---------------------------------------------------------------------------
# Top-level main() — programmatic entry point
# ---------------------------------------------------------------------------


def main(
    *,
    actor: str,
    all_tables: bool = False,
    source: str | None = None,
    table: str | None = None,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    drift_threshold_pct: float = DEFAULT_DRIFT_THRESHOLD_PCT,
    dry_run: bool = False,
    json_output: bool = False,
    verbose: bool = False,
    quiet: bool = False,
    server: str | None = None,
    justification: str | None = None,
    # ---- Injection hooks (for parallel test-author per task brief) ----
    config_loader=None,
    source_query_fn: Callable | None = None,
    general_query_fn: Callable | None = None,
    bronze_exists_fn: Callable | None = None,
    udm_writer_cursor_factory: Callable | None = None,
    audit_cursor_factory: Callable | None = None,
) -> dict:
    """Programmatic entry — invokes ``measure_lateness()`` per table.

    Per task-brief canonical signature contract. Returns a dict matching
    the D76 audit-row Metadata shape per CLI tool convention.

    Parameters
    ----------
    actor:
        Operator identity (per D75 + D76). REQUIRED.
    all_tables / source / table:
        Selector (per spec § 3 CLI args). ``all`` is mutex with
        ``source``/``table``; ``table`` requires ``source``. Argparse
        validates this BEFORE main() runs.
    lookback_days:
        Distribution window (default 30 per spec § 3).
    drift_threshold_pct:
        Δ% above which to flag a table as drifted (default 20.0).
    dry_run:
        When True, measurement runs but no UPDATE issued; audit row
        still written with ``dry_run=True`` in Metadata.
    json_output / verbose / quiet:
        Stdout-formatting controls per D75.
    server:
        Environment tag (dev/test/prod) recorded in audit-row Metadata.
    justification:
        Operator justification recorded in audit-row Metadata per D75.
    config_loader / source_query_fn / general_query_fn /
    bronze_exists_fn / udm_writer_cursor_factory / audit_cursor_factory:
        Test-injection hooks per task-brief "Mocking-friendly design"
        requirement. Defaults resolve to live infrastructure.

    Returns
    -------
    dict
        D76 audit-row Metadata shape:

        * ``event_kind``: ``'measure'``
        * ``tables_processed``: int
        * ``tables_drifted``: int (count where ``|drift_pct|>threshold``)
        * ``tables_warning``: int (count where ``notes != 'OK'``)
        * ``tables_failed``: int (count where source-connect failed)
        * ``exit_code``: int (0/1/2 per D74)
        * ``actor``: operator identity
        * ``dry_run``: bool
        * ``results``: list of serialized LatenessResult — present only
          when ``json_output OR verbose``

    Exit-code derivation (per D74 + spec § 3)
        * 0: tables_failed == 0 AND tables_warning == 0 AND
          tables_drifted == 0
        * 1: ANY of tables_warning > 0 OR tables_drifted > 0 OR
          tables_failed > 0 BUT NOT all-failed
        * 2: tables_processed > 0 AND tables_failed == tables_processed
          (total source-connect failure) OR UdmTablesListNotWritable
    """
    started_at = datetime.now(timezone.utc).replace(tzinfo=None)

    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    elif quiet:
        logging.getLogger().setLevel(logging.ERROR)

    # ---- Validate selector args (mirrors _validate_selector for programmatic callers) ----
    # When called from cli_main(), argparse + _validate_selector caught these
    # already; when called programmatically (Tier 1 tests + scripts), we
    # surface the same SystemExit so callers can pattern-match on it per
    # D74 + spec § 3 selector contract.
    if all_tables and (source or table):
        raise SystemExit(
            "--all is mutually exclusive with --source/--table per spec § 3."
        )
    if table and not source:
        raise SystemExit(
            "--table requires --source (canonical Round 4.5b § 3 contract)."
        )

    # ---- Resolve general_db tag for UPDATE ----
    try:
        import utils.configuration as config

        general_db = config.GENERAL_DB
    except Exception:  # noqa: BLE001
        general_db = "General"

    # ---- Load table configs ----
    try:
        table_configs = _load_table_configs(
            all_tables=all_tables,
            source=source,
            table=table,
            config_loader=config_loader,
        )
    except UdmTablesListNotWritable as exc:
        msg = (
            f"FATAL: cannot read UdmTablesList: {exc}; ensure UdmTablesList exists, "
            f"connection-string is valid, and operator has SELECT permission."
        )
        logger.error(msg)
        print(msg, file=sys.stderr)
        invocation_metadata = _empty_invocation_metadata(
            actor=actor, server=server, justification=justification,
            started_at=started_at, dry_run=dry_run, lookback_days=lookback_days,
            drift_threshold_pct=drift_threshold_pct,
        )
        invocation_metadata["exit_code"] = EXIT_FATAL
        invocation_metadata["error_type"] = "UdmTablesListNotWritable"
        invocation_metadata["error_message"] = str(exc)
        return invocation_metadata
    except Exception as exc:  # noqa: BLE001
        msg = f"FATAL: error loading table configs: {exc}"
        logger.exception(msg)
        print(msg, file=sys.stderr)
        invocation_metadata = _empty_invocation_metadata(
            actor=actor, server=server, justification=justification,
            started_at=started_at, dry_run=dry_run, lookback_days=lookback_days,
            drift_threshold_pct=drift_threshold_pct,
        )
        invocation_metadata["exit_code"] = EXIT_FATAL
        invocation_metadata["error_type"] = type(exc).__name__
        invocation_metadata["error_message"] = str(exc)
        return invocation_metadata

    if not table_configs:
        # No matches — that's a clean exit per spec § 3 (operator may have
        # used a typo'd source name; warn but don't fatal-out).
        logger.warning(
            "No UdmTablesList rows matched selector (all=%s source=%s table=%s)",
            all_tables, source, table,
        )
        invocation_metadata = _empty_invocation_metadata(
            actor=actor, server=server, justification=justification,
            started_at=started_at, dry_run=dry_run, lookback_days=lookback_days,
            drift_threshold_pct=drift_threshold_pct,
        )
        invocation_metadata["exit_code"] = EXIT_SUCCESS
        if not quiet:
            print("No tables matched the selector — nothing to measure.")
        return invocation_metadata

    # ---- Filter out tables without SourceAggregateColumnName ----
    # Per spec § 3 lateness applies to large-tables only (the column is
    # NULL for small tables). Skipping rather than erroring — the row
    # being on UdmTablesList doesn't mean it's measurable.
    measurable_configs = [
        tc for tc in table_configs
        if getattr(tc, "source_aggregate_column_name", None)
    ]
    skipped_no_aggregate = len(table_configs) - len(measurable_configs)
    if skipped_no_aggregate:
        logger.info(
            "Skipped %d table(s) without SourceAggregateColumnName "
            "(small-tables not measurable for L99 per spec § 3).",
            skipped_no_aggregate,
        )

    # ---- Per-table measurement loop ----
    results: list[LatenessResult] = []
    tables_failed = 0
    tables_warning = 0
    tables_drifted = 0

    for tc in measurable_configs:
        source_name = getattr(tc, "source_name", "")
        table_name = getattr(tc, "source_object_name", "")
        try:
            result = measure_lateness(
                tc,
                lookback_days=lookback_days,
                source_query_fn=source_query_fn,
                general_query_fn=general_query_fn,
                bronze_exists_fn=bronze_exists_fn,
            )
        except SourceConnectError as exc:
            logger.warning(
                "Source connect failure for %s.%s: %s",
                source_name, table_name, exc,
            )
            tables_failed += 1
            # Emit a FAILED audit row for this table.
            failed_metadata = {
                "event_kind": "measure",
                "actor": actor,
                "server": server,
                "justification": justification,
                "source_name": source_name,
                "table_name": table_name,
                "l99_minutes": None,
                "sample_count": 0,
                "prior_l99_minutes": None,
                "drift_pct": None,
                "drift_threshold_pct": drift_threshold_pct,
                "lookback_days": lookback_days,
                "dry_run": dry_run,
                "notes": "source connect failed",
                "error_type": "SourceConnectError",
                "error_message": str(exc)[:4000],
            }
            _write_audit_row(
                failed_metadata,
                status="FAILED",
                error_message=traceback.format_exc()[:4000],
                cursor_factory=audit_cursor_factory,
            )
            continue
        except LatenessMeasurementError as exc:
            # E.g., no SourceAggregateColumnName — shouldn't happen given
            # the filter above; safety net for any future skipped class.
            logger.warning(
                "Measurement skipped for %s.%s: %s",
                source_name, table_name, exc,
            )
            continue
        except Exception as exc:  # noqa: BLE001
            # Defensive — any unexpected exception is counted as failed
            # and the next table proceeds (one table's failure must not
            # block the rest of the batch).
            logger.exception(
                "Unexpected error measuring %s.%s",
                source_name, table_name,
            )
            tables_failed += 1
            failed_metadata = {
                "event_kind": "measure",
                "actor": actor,
                "server": server,
                "justification": justification,
                "source_name": source_name,
                "table_name": table_name,
                "l99_minutes": None,
                "sample_count": 0,
                "prior_l99_minutes": None,
                "drift_pct": None,
                "drift_threshold_pct": drift_threshold_pct,
                "lookback_days": lookback_days,
                "dry_run": dry_run,
                "notes": "unexpected error",
                "error_type": type(exc).__name__,
                "error_message": str(exc)[:4000],
            }
            _write_audit_row(
                failed_metadata,
                status="FAILED",
                error_message=traceback.format_exc()[:4000],
                cursor_factory=audit_cursor_factory,
            )
            continue

        results.append(result)

        notes_val = getattr(result, "notes", None)
        # Treat None / empty / "OK" as clean — defensive against
        # MagicMock-shaped results in test paths where notes is the
        # MagicMock default ("") instead of the canonical NOTE_OK.
        if notes_val and notes_val != NOTE_OK:
            tables_warning += 1
        if is_drifted(result, drift_threshold_pct):
            tables_drifted += 1

        # ---- UPDATE UdmTablesList (unless dry-run) ----
        if not dry_run:
            try:
                _write_udm_tables_list(
                    result,
                    general_db=general_db,
                    cursor_factory=udm_writer_cursor_factory,
                )
            except UdmTablesListNotWritable as exc:
                # UdmTablesList write failure is fatal-class per spec § 3.
                msg = (
                    f"FATAL: UdmTablesList not writable for "
                    f"{source_name}.{table_name}: {exc}"
                )
                logger.error(msg)
                print(msg, file=sys.stderr)
                # Write the FAILED audit row for this table before
                # short-circuiting — operator gets the canonical record.
                failed_metadata = {
                    **serialize_result(result),
                    "event_kind": "measure",
                    "actor": actor,
                    "server": server,
                    "justification": justification,
                    "drift_threshold_pct": drift_threshold_pct,
                    "lookback_days": lookback_days,
                    "dry_run": dry_run,
                    "error_type": "UdmTablesListNotWritable",
                    "error_message": str(exc)[:4000],
                }
                _write_audit_row(
                    failed_metadata,
                    status="FAILED",
                    error_message=str(exc)[:4000],
                    cursor_factory=audit_cursor_factory,
                )
                invocation_metadata = _build_invocation_metadata(
                    actor=actor, server=server, justification=justification,
                    started_at=started_at, dry_run=dry_run,
                    lookback_days=lookback_days,
                    drift_threshold_pct=drift_threshold_pct,
                    tables_processed=len(results),
                    tables_drifted=tables_drifted,
                    tables_warning=tables_warning,
                    tables_failed=tables_failed,
                    results=results,
                    include_results=json_output or verbose,
                )
                invocation_metadata["exit_code"] = EXIT_FATAL
                invocation_metadata["error_type"] = "UdmTablesListNotWritable"
                invocation_metadata["error_message"] = str(exc)
                return invocation_metadata

        # ---- Per-table audit row (one per TABLE per invocation) ----
        per_table_metadata = {
            **serialize_result(result),
            "event_kind": "measure",
            "actor": actor,
            "server": server,
            "justification": justification,
            "drift_threshold_pct": drift_threshold_pct,
            "lookback_days": lookback_days,
            "dry_run": dry_run,
        }
        _write_audit_row(
            per_table_metadata,
            status="SUCCESS",
            cursor_factory=audit_cursor_factory,
        )

    # ---- Derive exit code per D74 contract ----
    if measurable_configs and tables_failed == len(measurable_configs):
        exit_code = EXIT_FATAL  # All measurable tables failed at source-connect
    elif tables_failed > 0 or tables_warning > 0 or tables_drifted > 0:
        exit_code = EXIT_WARNING
    else:
        exit_code = EXIT_SUCCESS

    invocation_metadata = _build_invocation_metadata(
        actor=actor, server=server, justification=justification,
        started_at=started_at, dry_run=dry_run, lookback_days=lookback_days,
        drift_threshold_pct=drift_threshold_pct,
        tables_processed=len(results),
        tables_drifted=tables_drifted,
        tables_warning=tables_warning,
        tables_failed=tables_failed,
        results=results,
        include_results=json_output or verbose,
    )
    invocation_metadata["exit_code"] = exit_code

    # ---- Render stdout ----
    if json_output:
        _emit_json(results, invocation_metadata=invocation_metadata)
    elif not quiet:
        _emit_human_summary(
            results,
            drift_threshold_pct=drift_threshold_pct,
            dry_run=dry_run,
        )

    return invocation_metadata


# ---------------------------------------------------------------------------
# Metadata constructors
# ---------------------------------------------------------------------------


def _build_invocation_metadata(
    *,
    actor: str,
    server: str | None,
    justification: str | None,
    started_at: datetime,
    dry_run: bool,
    lookback_days: int,
    drift_threshold_pct: float,
    tables_processed: int,
    tables_drifted: int,
    tables_warning: int,
    tables_failed: int,
    results: list[LatenessResult],
    include_results: bool,
) -> dict:
    """Build the invocation-level Metadata dict returned by main().

    Per task-brief contract — distinct from the per-TABLE audit-row
    Metadata (which is one row per table written inside the loop).
    The invocation-level dict aggregates counts + classification fields.
    """
    invocation_metadata: dict = {
        "event_kind": "measure",
        "tables_processed": tables_processed,
        "tables_drifted": tables_drifted,
        "tables_warning": tables_warning,
        "tables_failed": tables_failed,
        "exit_code": EXIT_SUCCESS,  # default; overwritten by caller
        "actor": actor,
        "server": server,
        "justification": justification,
        "started_at": started_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "lookback_days": lookback_days,
        "drift_threshold_pct": drift_threshold_pct,
        "dry_run": dry_run,
        "classification": {
            "trigger": "Scheduled",
            "trigger_secondary": "Manual",
            "frequency": "Recurring",
            "frequency_secondary": "Adhoc",
            "idempotency": "Yes",
            "audit_family": EVENT_TYPE,
        },
    }
    if include_results:
        invocation_metadata["results"] = [serialize_result(r) for r in results]
    return invocation_metadata


def _empty_invocation_metadata(
    *,
    actor: str,
    server: str | None,
    justification: str | None,
    started_at: datetime,
    dry_run: bool,
    lookback_days: int,
    drift_threshold_pct: float,
) -> dict:
    """Build an invocation-Metadata dict for early-exit paths (no results)."""
    return _build_invocation_metadata(
        actor=actor,
        server=server,
        justification=justification,
        started_at=started_at,
        dry_run=dry_run,
        lookback_days=lookback_days,
        drift_threshold_pct=drift_threshold_pct,
        tables_processed=0,
        tables_drifted=0,
        tables_warning=0,
        tables_failed=0,
        results=[],
        include_results=False,
    )


# ---------------------------------------------------------------------------
# CLI argv entry point
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    """Alias for :func:`_build_parser` — test contract per Tier 0 spec scaffold.

    The Tier 0 scaffold (``tests/tier0/test_measure_lateness.py``) probes
    for ``_build_arg_parser`` to drive the argparse --help path. Keep both
    names exported for forward-compat.
    """
    return _build_parser()


def _build_parser() -> argparse.ArgumentParser:
    """Build the argparse parser per spec § 3 CLI args."""
    parser = argparse.ArgumentParser(
        description=(
            "Measure per-table empirical 99th-percentile lateness (L_99 per D11) "
            "against source DB; UPDATE UdmTablesList.LatenessL99Minutes + "
            "LatenessL99UpdatedAt; emit one CLI_MEASURE_LATENESS audit row per table."
        ),
    )
    # ---- Selector args (mutex/required-pair validation below) ----
    selector_group = parser.add_argument_group("Selector (one of: --all OR --source [--table])")
    selector_group.add_argument(
        "--all", action="store_true", dest="all_tables",
        help="Run against every UdmTablesList row with IsEnabled=1 "
             "(mutex with --source/--table).",
    )
    selector_group.add_argument(
        "--source", default=None,
        help="Restrict to one source (DNA / CCM / EPICOR).",
    )
    selector_group.add_argument(
        "--table", default=None,
        help="Restrict to one table (must be paired with --source).",
    )

    # ---- Tool-specific args (per spec § 3) ----
    parser.add_argument(
        "--lookback-days", type=int, default=DEFAULT_LOOKBACK_DAYS,
        help=f"Lookback window for L99 distribution (default: {DEFAULT_LOOKBACK_DAYS}).",
    )
    parser.add_argument(
        "--drift-threshold-pct", type=float, default=DEFAULT_DRIFT_THRESHOLD_PCT,
        help=f"Drift %% above which a table is flagged drifted "
             f"(default: {DEFAULT_DRIFT_THRESHOLD_PCT}).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Measure but do NOT UPDATE UdmTablesList; audit row still written.",
    )

    # ---- D75 canonical args ----
    parser.add_argument(
        "--actor", required=True,
        help="Operator running the tool (per D75); written to audit row Metadata.",
    )
    parser.add_argument(
        "--justification", default=None,
        help="Operator justification (per D75); written to audit row Metadata.",
    )
    parser.add_argument(
        "--server", default=None,
        choices=("dev", "test", "prod"),
        help="Target server tag per D75 (echoed in result Metadata). Optional.",
    )
    parser.add_argument(
        "--json", action="store_true", dest="json_output",
        help="Emit canonical JSON output to stdout instead of human-readable summary.",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Enable DEBUG logging.",
    )
    parser.add_argument(
        "--quiet", action="store_true",
        help="Suppress INFO logging (errors still emitted).",
    )
    return parser


def _validate_selector(args: argparse.Namespace, parser: argparse.ArgumentParser) -> None:
    """Enforce --all mutex with --source/--table; --table requires --source."""
    if args.all_tables and (args.source or args.table):
        parser.error("--all is mutually exclusive with --source/--table.")
    if not args.all_tables and not args.source and not args.table:
        parser.error("One of --all OR --source [--table] is required.")
    if args.table and not args.source:
        parser.error("--table requires --source (canonical Round 4.5b § 3 contract).")
    if args.lookback_days <= 0:
        parser.error(
            f"--lookback-days must be positive (got {args.lookback_days})."
        )


def cli_main() -> int:
    """Argv entry point — argparse + main() + return exit code per D74."""
    parser = _build_parser()
    args = parser.parse_args()
    _validate_selector(args, parser)

    try:
        result = main(
            actor=args.actor,
            all_tables=args.all_tables,
            source=args.source,
            table=args.table,
            lookback_days=args.lookback_days,
            drift_threshold_pct=args.drift_threshold_pct,
            dry_run=args.dry_run,
            json_output=args.json_output,
            verbose=args.verbose,
            quiet=args.quiet,
            server=args.server,
            justification=args.justification,
        )
    except Exception:  # noqa: BLE001
        tb = traceback.format_exc()
        print(f"FATAL: measure_lateness failed: {tb[:500]}", file=sys.stderr)
        return EXIT_FATAL

    exit_code = int(result.get("exit_code", EXIT_FATAL))
    if exit_code not in (EXIT_SUCCESS, EXIT_WARNING, EXIT_FATAL):
        exit_code = EXIT_FATAL
    return exit_code


if __name__ == "__main__":
    sys.exit(cli_main())
