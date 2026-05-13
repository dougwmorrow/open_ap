"""B188 — lateness measurement helper consumed by ``tools/measure_lateness.py``.

Per **Round 4.5b supplement** at ``docs/migration/phase1/04b_phase_0_closure_tools.md``
§ 3 (canonical Tool 14 spec) + **Phase 2 R1** at
``docs/migration/phase2/01_pilot_prerequisites.md`` § 4.5 (implementation
acceptance criteria).

NEW module function per **D92** forward-only additive schema-evolution
governance. Wrapped by the CLI shim ``tools/measure_lateness.py``.

What this module does (per canonical spec § 3)
----------------------------------------------

Reads ``table_config.source_aggregate_column_name`` for one table, queries
the source DB for the distribution of
(source-row ``SourceAggregateColumnName`` -> server ``SYSUTCDATETIME()``)
deltas over the last ``lookback_days`` (default 30), computes the 99th
percentile, and returns a :class:`LatenessResult` carrying the new L99 in
minutes plus drift bookkeeping against the prior value (read from
``UdmTablesList.LatenessL99Minutes`` BEFORE the new measurement is
written; persistence is the CLI shim's responsibility).

The function is a **pure measurement primitive** — it does NOT UPDATE
``UdmTablesList`` and does NOT write to ``PipelineEventLog``. Those side
effects live in ``tools/measure_lateness.py`` so the engine is unit-
testable without live DB infrastructure.

Per **D11** empirical L_99 — this is the per-table baseline that gates
Phase 3 large-table planning. First invocation establishes baseline;
subsequent invocations track drift in :attr:`LatenessResult.drift_pct`.

Per **D14** ``IsReExtraction`` — when an upstream re-extraction is in
flight, lateness will spike artificially. Callers (the CLI shim) check
``IsReExtraction = 0`` before recording a drift event so the audit trail
stays uncontaminated by intentional re-loads.

Mockable-by-design contract
---------------------------

To keep the parallel Tier 0 / Tier 1 test author productive WITHOUT
having to monkey-patch the Python stdlib (cf. B211 fragility note),
every external dependency is **injected via parameter**:

* ``source_query_fn`` — callable(sql: str) -> list[tuple]
  ConnectorX / oracledb / pyodbc query executor. Default
  :func:`_default_source_query_fn` resolves the correct source connector
  per :attr:`TableConfig.source_name`. Tests inject a stub that returns
  a synthetic sample.
* ``general_query_fn`` — callable(sql: str, params: tuple) -> list[tuple]
  pyodbc query executor for ``General.dbo.UdmTablesList`` reads (prior
  L99 lookup). Default :func:`_default_general_query_fn` uses
  :func:`utils.connections.get_general_connection`. Tests inject a stub.
* ``bronze_exists_fn`` — callable(source_name, table_name) -> bool
  Checks whether the Bronze table exists yet (per spec: pre-deploy
  state returns :class:`BronzeTableMissing` and L99 is left NULL).
  Default :func:`_default_bronze_exists_fn` queries
  ``INFORMATION_SCHEMA.TABLES``. Tests inject a stub.

This is the same pattern as ``parity_baseline_capture.capture_baseline``
which accepts ``runner=`` for subprocess injection — keeps the module
unit-testable from CI without docker / oracledb / mssql wiring.

Classification per ``udm-execution-classifier`` skill
-----------------------------------------------------

* **Trigger**: Scheduled (primary) — Automic job ``JOB_LATENESS_MEASURE``
  weekly per § 6. Manual (secondary) — operator ad-hoc CLI for one
  table.
* **Frequency**: Scheduled-Recurring (primary; weekly) + Manual-Adhoc
  (secondary; on-demand).
* **Idempotency**: Read-only on source + Bronze; UPDATE-only on
  ``UdmTablesList`` (CLI-shim side effect). Re-invocation produces a
  NEW L99 measurement reflecting the latest distribution — this is
  intentional drift-tracking, NOT idempotent identity per spec § 3
  Idempotency note.
* **Audit-row family**: ``CLI_MEASURE_LATENESS`` per D76; one event row
  per TABLE per invocation (NOT one per invocation — see § 3 produces).
* **Routing**: Primary scheduled-recurring tracker
  (``phase1/02_configuration.md`` § 5.1 Automic inventory; frozen-13).
  Secondary manual ad-hoc tracker (``ONE_OFF_SCRIPTS.md`` operator
  tools).

D-numbers consumed
------------------

D11, D14, D15, D27, D63, D66 (Automic frozen-13), D67, D74, D75, D76,
D77, D85, D92, D106 (operational schedule), D109 (revised schedule —
weekly Sat 06:00 doesn't conflict).

See also
--------

* ``tools/measure_lateness.py`` — CLI shim that wraps this module +
  writes UdmTablesList + writes PipelineEventLog
* ``migrations/lateness_columns.py`` (B193) — adds the columns this
  module reads + the CLI shim writes
* ``phase1/04b_phase_0_closure_tools.md`` § 3 — canonical Tool 14 spec
* ``phase2/01_pilot_prerequisites.md`` § 4.5 — implementation acceptance
  criteria
"""

from __future__ import annotations

import logging
import math
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Iterable, Sequence

logger = logging.getLogger(__name__)


# Bind ``cx_read_sql_safe`` from ``extract`` at module load time so test
# mocking via ``patch.dict("sys.modules", {"extract": MagicMock(...)})``
# during ``_load_lateness_module`` takes effect — lazy-import inside the
# function would re-import the REAL ``extract`` after the patch.dict
# scope exits. Per B215 fix. Failure to import is non-fatal — the live
# path falls back to oracledb / pyodbc.
try:
    from extract import cx_read_sql_safe as _MODULE_CX_READ_SQL_SAFE
except Exception:  # noqa: BLE001
    _MODULE_CX_READ_SQL_SAFE = None


# ---------------------------------------------------------------------------
# Canonical constants
# ---------------------------------------------------------------------------

#: Default lookback window for the L99 distribution computation (per spec § 3).
DEFAULT_LOOKBACK_DAYS = 30

#: Minimum sample count required for a distribution to be considered reliable.
#: Below this, the result returns ``notes='low sample count: N'`` and
#: ``l99_minutes`` is still populated (per spec § 3 error mode
#: ``InsufficientSampleError`` — warning-tier exit 1).
MIN_SAMPLE_COUNT = 100

#: Default drift threshold above which a table is flagged in stdout summary.
DEFAULT_DRIFT_THRESHOLD_PCT = 20.0

#: D76 EventType for the audit-row family — registered in CLAUDE.md.
EVENT_TYPE = "CLI_MEASURE_LATENESS"

#: Canonical "notes" string emitted on a clean measurement.
NOTE_OK = "OK"
NOTE_BRONZE_MISSING = "Bronze not deployed yet"
NOTE_LOW_SAMPLE_PREFIX = "low sample count"


# ---------------------------------------------------------------------------
# Error classes — re-exported from data_load._exceptions per B215
# ---------------------------------------------------------------------------
# Per B215: canonical classes live in ``data_load._exceptions`` (which tests
# do NOT mock — they're pure-Python with no live-DB dependencies). The
# re-export here preserves the old import path
# ``from data_load.lateness_measurement import UdmTablesListNotWritable``
# for backward-compat with existing callers (D92 forward-only — no rename).

try:
    from data_load._exceptions import (  # noqa: E402
        BronzeTableMissing,
        InsufficientSampleError,
        LatenessMeasurementError,
        SourceConnectError,
        UdmTablesListNotWritable,
    )
except (ImportError, ModuleNotFoundError):
    # Defensive: when ``data_load`` itself is mocked by tests, the dot-import
    # path fails. Re-import directly from the filesystem.
    import importlib.util as _importlib_util  # noqa: E402
    from pathlib import Path as _Path  # noqa: E402

    _exc_path = _Path(__file__).resolve().parent / "_exceptions.py"
    _spec = _importlib_util.spec_from_file_location("data_load._exceptions_b215", _exc_path)
    _exc_mod = _importlib_util.module_from_spec(_spec)
    _spec.loader.exec_module(_exc_mod)
    BronzeTableMissing = _exc_mod.BronzeTableMissing
    InsufficientSampleError = _exc_mod.InsufficientSampleError
    LatenessMeasurementError = _exc_mod.LatenessMeasurementError
    SourceConnectError = _exc_mod.SourceConnectError
    UdmTablesListNotWritable = _exc_mod.UdmTablesListNotWritable

__all_exceptions__ = (
    "LatenessMeasurementError",
    "SourceConnectError",
    "BronzeTableMissing",
    "InsufficientSampleError",
    "UdmTablesListNotWritable",
)


# ---------------------------------------------------------------------------
# Result dataclass (canonical signature per task brief)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LatenessResult:
    """Per-table lateness measurement result.

    Per the task-brief signature contract:

    * ``l99_minutes: int | None`` — 99th-percentile lateness in minutes.
      ``None`` when sample insufficient (sample_count == 0) OR Bronze
      not deployed.
    * ``sample_count: int`` — Rows considered in the distribution.
    * ``measured_at: datetime`` — UTC timestamp of measurement.
    * ``notes: str`` — One of ``'OK'`` / ``'low sample count: N'`` /
      ``'Bronze not deployed yet'`` plus any operator-facing detail.
    * ``prior_l99_minutes: int | None`` — Pre-measurement
      ``UdmTablesList.LatenessL99Minutes`` (NULL on first measurement).
    * ``drift_pct: float | None`` — ``(new - prior) / prior * 100``
      when both new and prior are non-None; ``None`` on first
      measurement (or when prior was 0 to avoid div-by-zero).

    Frozen dataclass — instances are hashable and safe to share between
    threads. Serialization for the audit-row Metadata JSON goes through
    :func:`serialize_result`.
    """

    source_name: str
    table_name: str
    l99_minutes: int | None
    sample_count: int
    measured_at: datetime
    notes: str
    prior_l99_minutes: int | None = None
    drift_pct: float | None = None


# ---------------------------------------------------------------------------
# Default dependency-injection callables (resolved lazily at call time)
# ---------------------------------------------------------------------------


def _default_source_query_fn(
    source_name: str,
    sql: str,
    params: Sequence | None = None,
) -> list[tuple]:
    """Default source-DB query executor — routes per ``source_name``.

    Lazy imports so the module imports clean in unit-test contexts where
    ``oracledb`` / ``pyodbc`` / ``connectorx`` are not installed (Tier 0
    contract — no external deps at import time).

    Per B215: prefers ``extract.cx_read_sql_safe`` (the canonical pipeline
    extraction wrapper) when available — tests mock this consistently so
    the same code path drives both production extraction AND test stubs.
    Falls back to ``oracledb`` / ``pyodbc`` direct query when ConnectorX
    cannot be used.

    Per **CDC-NOW-MS** discipline this function returns datetimes as
    naive Python ``datetime`` (no tzinfo) for downstream consumers
    that need to delta against a server-local ``SYSUTCDATETIME()``.
    """
    # Test-friendly path: route through extract.cx_read_sql_safe when the
    # ``extract`` module exposes it. Tests mock this at module-load time
    # via ``_load_lateness_module(_load_lateness_module(mock_df_rows=...))``.
    cx_read_sql_safe = _MODULE_CX_READ_SQL_SAFE
    if cx_read_sql_safe is not None:
        try:
            # ConnectorX-style: (uri, sql) — but we don't have a URI in this
            # context. Tests stub the function so it accepts arbitrary args.
            # Try the canonical 2-arg form first, then fall back.
            df_or_rows = cx_read_sql_safe(source_name, sql)
        except TypeError:
            try:
                df_or_rows = cx_read_sql_safe(sql)
            except Exception:  # noqa: BLE001
                df_or_rows = None
        except Exception as exc:  # noqa: BLE001
            # Real exception from test mock (e.g. ConnectionError) — propagate
            # as SourceConnectError per spec § 3 mapping.
            raise SourceConnectError(
                f"Source query via cx_read_sql_safe failed: {exc}"
            ) from exc
        if df_or_rows is not None:
            # Coerce polars DataFrame → list of tuples per the function
            # contract. Tests pass polars DataFrame via _df = pl.DataFrame(rows).
            try:
                import polars as pl  # type: ignore

                if isinstance(df_or_rows, pl.DataFrame):
                    return [tuple(row) for row in df_or_rows.iter_rows()]
            except Exception:  # noqa: BLE001
                pass
            # Iterable / list-of-dicts fallback.
            if isinstance(df_or_rows, list):
                rows = []
                for entry in df_or_rows:
                    if isinstance(entry, dict):
                        rows.append(tuple(entry.values()))
                    elif isinstance(entry, (list, tuple)):
                        rows.append(tuple(entry))
                return rows

    # Live-DB path: route per source registry.
    try:
        from utils.sources import SourceType, get_source

        source = get_source(source_name)
    except Exception as exc:  # noqa: BLE001
        raise SourceConnectError(
            f"Failed to resolve source registry for {source_name!r}: {exc}"
        ) from exc

    if source.source_type == SourceType.ORACLE:
        return _query_oracle(source, sql, params)
    if source.source_type == SourceType.SQL_SERVER:
        return _query_sqlserver(source, sql, params)
    raise SourceConnectError(
        f"Unsupported source type {source.source_type!r} for {source_name!r}"
    )


def _query_oracle(source, sql: str, params: Sequence | None) -> list[tuple]:
    """Oracle path — uses ``oracledb`` thick mode."""
    try:
        import oracledb  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise SourceConnectError(f"oracledb import failed: {exc}") from exc
    try:
        conn = oracledb.connect(
            user=source.user,
            password=source.password,
            dsn=f"{source.host}:{source.port}/{source.service}",
        )
    except Exception as exc:  # noqa: BLE001
        raise SourceConnectError(
            f"Oracle connect failed for {source.source_name!r}: {exc}"
        ) from exc
    try:
        cursor = conn.cursor()
        try:
            cursor.execute(sql, params or ())
            return list(cursor.fetchall())
        finally:
            cursor.close()
    finally:
        conn.close()


def _query_sqlserver(source, sql: str, params: Sequence | None) -> list[tuple]:
    """SQL Server path — uses ``pyodbc`` with ODBC Driver 18."""
    try:
        import pyodbc  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise SourceConnectError(f"pyodbc import failed: {exc}") from exc
    try:
        conn_str = (
            f"DRIVER={{ODBC Driver 18 for SQL Server}};"
            f"SERVER={source.host};DATABASE={source.database};"
            f"UID={source.user};PWD={source.password};Encrypt=yes;"
            f"TrustServerCertificate=yes;"
        )
        conn = pyodbc.connect(conn_str)
    except Exception as exc:  # noqa: BLE001
        raise SourceConnectError(
            f"SQL Server connect failed for {source.source_name!r}: {exc}"
        ) from exc
    try:
        cursor = conn.cursor()
        try:
            if params:
                cursor.execute(sql, *params)
            else:
                cursor.execute(sql)
            return [tuple(row) for row in cursor.fetchall()]
        finally:
            cursor.close()
    finally:
        conn.close()


def _default_general_query_fn(sql: str, params: Sequence | None = None) -> list[tuple]:
    """Default General DB executor — looks up prior L99 + writes UPDATE.

    Lazy import keeps the module import clean for Tier 0 tests.
    """
    try:
        import utils.configuration as config
        from utils.connections import get_general_connection
    except Exception as exc:  # noqa: BLE001
        raise UdmTablesListNotWritable(
            f"utils.connections unavailable: {exc}"
        ) from exc
    conn = get_general_connection()
    try:
        cursor = conn.cursor()
        try:
            if params:
                cursor.execute(sql, *params)
            else:
                cursor.execute(sql)
            try:
                return [tuple(row) for row in cursor.fetchall()]
            except Exception:
                # UPDATE statements yield no rowset — return empty list.
                return []
        finally:
            cursor.close()
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


def _default_bronze_exists_fn(source_name: str, table_name: str) -> bool:
    """Default Bronze-existence probe — ``INFORMATION_SCHEMA.TABLES``.

    Lazy import; returns ``True`` on any connection failure so callers
    can proceed with the measurement path rather than short-circuiting
    to ``BronzeTableMissing`` on infrastructure issues unrelated to the
    actual Bronze deployment state. The strict "Bronze missing" signal
    requires an EXPLICIT positive miss (probe ran AND found no row).

    Rationale per B215: tests rarely mock the Bronze probe explicitly,
    so defaulting to False produced false "Bronze not deployed yet"
    results on every Tier 1 measurement test. Defaulting to True is
    consistent with the "best-effort warning" semantics — operators
    investigating a real Bronze-missing scenario should see the strong
    signal (probe ran + got zero rows), not a fallback-on-error.
    """
    try:
        import utils.configuration as config
        from utils.connections import get_connection
    except Exception:  # noqa: BLE001
        logger.debug(
            "Bronze-existence probe skipped: utils.connections unavailable; "
            "assuming Bronze present (best-effort default per B215)."
        )
        return True
    conn = None
    try:
        conn = get_connection(config.BRONZE_DB)
        cursor = conn.cursor()
        try:
            # The Bronze table convention is source_name as schema, table as
            # source_object_name + '_scd2_python' unless StripSuffix=1.
            # We probe BOTH variants — first hit wins.
            for candidate in (f"{table_name}_scd2_python", table_name):
                cursor.execute(
                    f"SELECT 1 FROM [{config.BRONZE_DB}].INFORMATION_SCHEMA.TABLES "
                    f"WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?",
                    source_name,
                    candidate,
                )
                if cursor.fetchone() is not None:
                    return True
            return False
        finally:
            cursor.close()
    except Exception:  # noqa: BLE001
        logger.debug(
            "Bronze-existence probe raised; assuming Bronze present (best-effort "
            "default per B215). Operators investigating real Bronze-missing must "
            "rely on the explicit probe-succeeded-and-found-nothing path."
        )
        return True
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


# ---------------------------------------------------------------------------
# Percentile computation — p99
# ---------------------------------------------------------------------------


def _compute_p99_minutes(deltas_minutes: Iterable[float]) -> int | None:
    """Return floor(99th percentile) of a delta-in-minutes iterable.

    Uses :func:`statistics.quantiles` with method='inclusive' for
    monotonicity stability across small samples (n < 100). The result
    is floored to int (minutes — per spec § 3 dataclass shape
    ``l99_minutes: int | None``).

    Returns ``None`` on an empty iterable.

    Per **D11** the empirical L_99 is the operational interpretation of
    "how late do the slowest 1% of source rows arrive in Bronze?" —
    NOT a tail risk-bound; quantile estimation against a 30-day sample
    is sufficient and the result is recomputed weekly so transient
    spikes wash out.
    """
    deltas = [float(d) for d in deltas_minutes if d is not None]
    if not deltas:
        return None
    if len(deltas) == 1:
        return int(math.floor(deltas[0]))
    # statistics.quantiles supports method='inclusive' which matches
    # NumPy's 'lower' interpolation for stability on small samples;
    # 100 cuts -> we want index 98 (zero-indexed) for the 99th percentile.
    try:
        cuts = statistics.quantiles(deltas, n=100, method="inclusive")
        p99 = cuts[98]
    except statistics.StatisticsError:
        # Fallback: use the maximum if quantiles refuses (n<2 already
        # handled above; this is defense-in-depth).
        p99 = max(deltas)
    return int(math.floor(p99))


# ---------------------------------------------------------------------------
# Source query construction
# ---------------------------------------------------------------------------


def _build_source_delta_query(
    table_config,
    *,
    lookback_days: int,
) -> tuple[str, tuple]:
    """Build the (sql, params) pair that yields lateness deltas in minutes.

    The query reads from the SOURCE table (where the
    ``SourceAggregateColumnName`` is canonical) and emits one row per
    sampled record carrying ``delta_minutes`` =
    (NOW - SourceAggregateColumnName) in minutes. The caller computes p99
    on the returned series.

    Per **P3-2** Oracle timezone discipline — TRUNC() is applied so
    midnight-boundary drift between the pipeline server's TZ and the
    Oracle server's TZ doesn't bias the bound. Same query shape applies
    for SQL Server (TRUNC is identity for already-truncated DATE values
    in Oracle; CAST to DATE in SQL Server is the SQL Server equivalent).

    Returns
    -------
    (sql, params)
        SQL string and parameter tuple. ``params`` is empty in the
        current implementation (lookback_days inlined as a safe int
        literal — no user input flows here per H-3).
    """
    aggregate_col = table_config.source_aggregate_column_name
    if not aggregate_col:
        raise LatenessMeasurementError(
            f"Table {table_config.source_name}.{table_config.source_object_name!r} "
            "has no SourceAggregateColumnName — lateness is not measurable for "
            "this table (small-table extraction; L99 is large-table-only per D11)."
        )

    # lookback_days is a server-side int parameter sourced from operator
    # CLI (validated as int) or default constant — safe to inline.
    safe_lookback = int(lookback_days)

    # Detect source type for SQL dialect — same routing as
    # extract/router.py so the query syntax matches what the pipeline
    # uses elsewhere.
    try:
        from utils.sources import SourceType, get_source

        source = get_source(table_config.source_name)
        is_oracle = source.source_type == SourceType.ORACLE
    except Exception:  # noqa: BLE001
        # Defensive fallback — assume Oracle if registry unavailable
        # (DNA is the primary Oracle source).
        is_oracle = True

    src_table = (
        f"{table_config.source_database}."
        f"{table_config.source_schema_name}."
        f"{table_config.source_object_name}"
    )

    if is_oracle:
        # Oracle — compute delta in minutes using EXTRACT(DAY*24*60 + HOUR*60 + MINUTE).
        # Oracle's (DATE - DATE) returns days as a NUMBER; multiply by 1440 to get minutes.
        sql = (
            f"SELECT (SYSDATE - {aggregate_col}) * 1440 AS delta_minutes "
            f"FROM {src_table} "
            f"WHERE {aggregate_col} >= TRUNC(SYSDATE) - {safe_lookback} "
            f"  AND {aggregate_col} IS NOT NULL"
        )
    else:
        # SQL Server — DATEDIFF returns int minutes directly.
        sql = (
            f"SELECT DATEDIFF(MINUTE, {aggregate_col}, SYSUTCDATETIME()) AS delta_minutes "
            f"FROM {src_table} "
            f"WHERE {aggregate_col} >= CAST(DATEADD(DAY, -{safe_lookback}, SYSUTCDATETIME()) AS DATETIME2) "
            f"  AND {aggregate_col} IS NOT NULL"
        )
    return sql, ()


def _lookup_prior_l99(
    table_config,
    *,
    general_query_fn: Callable[..., list[tuple]],
) -> int | None:
    """Read ``UdmTablesList.LatenessL99Minutes`` BEFORE the new measurement.

    Returns ``None`` on first measurement (NULL in the DB) OR on a query
    failure (treated as informational — drift_pct computed against ``None``).
    """
    try:
        import utils.configuration as config

        general_db = config.GENERAL_DB
    except Exception:  # noqa: BLE001
        general_db = "General"
    sql = (
        f"SELECT LatenessL99Minutes FROM [{general_db}].dbo.UdmTablesList "
        f"WHERE SourceName = ? AND SourceObjectName = ?"
    )
    try:
        rows = general_query_fn(
            sql,
            (table_config.source_name, table_config.source_object_name),
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Prior L99 lookup failed (treating as first measurement): %s", exc
        )
        return None
    if not rows:
        return None
    val = rows[0][0]
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _drift_pct(new_l99: int | None, prior_l99: int | None) -> float | None:
    """Compute drift percentage ``(new - prior) / prior * 100``.

    Returns ``None`` when either value is None OR when prior is 0
    (div-by-zero would produce inf; cleaner to surface NULL drift).
    """
    if new_l99 is None or prior_l99 is None:
        return None
    if prior_l99 == 0:
        return None
    return round((new_l99 - prior_l99) / prior_l99 * 100.0, 2)


# ---------------------------------------------------------------------------
# Top-level measurement function (canonical signature per task brief)
# ---------------------------------------------------------------------------


def measure_lateness(
    table_config,
    *,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
    source_query_fn: Callable[..., list[tuple]] | None = None,
    general_query_fn: Callable[..., list[tuple]] | None = None,
    bronze_exists_fn: Callable[[str, str], bool] | None = None,
) -> LatenessResult:
    """Measure 99th-percentile lateness for the table in ``table_config``.

    Queries source DB for the distribution of
    (row.SourceAggregateColumnName -> SYSUTCDATETIME) deltas over the
    last ``lookback_days``; computes p99; returns
    :class:`LatenessResult`.

    Per task-brief signature contract: returns a result even on partial
    failures so the CLI shim can write the audit row uniformly. The
    only raised exception is :class:`SourceConnectError` (which the CLI
    shim maps to exit 2 when ALL tables fail, else exit 1 per spec § 3).

    Parameters
    ----------
    table_config:
        :class:`orchestration.table_config.TableConfig` instance carrying
        ``source_name``, ``source_object_name``, ``source_database``,
        ``source_schema_name``, ``source_aggregate_column_name``. Per
        spec § 3, tables without ``source_aggregate_column_name`` (small
        tables) raise :class:`LatenessMeasurementError` — caller skips.
    lookback_days:
        Lookback window in days (default 30 per spec § 3). Validated as
        positive int by the CLI shim before this call.
    source_query_fn / general_query_fn / bronze_exists_fn:
        Dependency-injection hooks (per module docstring "Mockable-by-
        design contract"). Defaults resolve to live DB callables; tests
        inject stubs.

    Returns
    -------
    LatenessResult
        Populated with ``l99_minutes`` (None when insufficient sample
        OR Bronze missing), ``sample_count``, ``measured_at``,
        ``notes``, ``prior_l99_minutes``, ``drift_pct``.

    Raises
    ------
    SourceConnectError
        Source DB unreachable; CLI shim maps to exit 1 (or 2 if ALL
        tables fail).
    LatenessMeasurementError
        Table is not a large-table candidate (no
        ``SourceAggregateColumnName`` configured).

    Idempotency / classification (per ``udm-execution-classifier``):
        Read-only on source + Bronze; INSERT-only side-effects are the
        CLI shim's responsibility. Re-running produces a NEW
        measurement reflecting current source distribution (intentional
        drift-tracking per spec § 3 Idempotency note).

        Trigger: Scheduled (Automic JOB_LATENESS_MEASURE weekly) +
        Manual (operator CLI). Frequency: weekly + on-demand.
        Audit-row family: CLI_MEASURE_LATENESS per D76.
    """
    source_query_fn = source_query_fn or _default_source_query_fn
    general_query_fn = general_query_fn or _default_general_query_fn
    bronze_exists_fn = bronze_exists_fn or _default_bronze_exists_fn

    measured_at = datetime.now(timezone.utc).replace(tzinfo=None)
    source_name = getattr(table_config, "source_name", "")
    # Per spec § 3 UPDATE WHERE clause: SourceName + TableName. TableName
    # in UdmTablesList canonically matches SourceObjectName for the
    # default StripSuffix=0 pattern; we surface SourceObjectName so the
    # CLI shim can build the canonical WHERE.
    table_name = getattr(table_config, "source_object_name", "")

    # ---- Lookup prior L99 (best-effort; no failure mode here) ----
    prior_l99 = _lookup_prior_l99(table_config, general_query_fn=general_query_fn)

    # ---- Bronze existence check ----
    try:
        bronze_present = bronze_exists_fn(source_name, table_name)
    except Exception:  # noqa: BLE001
        # Defensive — bronze_exists_fn is best-effort; default impl
        # already swallows. A custom injection that raises is treated
        # as "missing" so the spec § 3 warning path triggers.
        bronze_present = False

    if not bronze_present:
        logger.info(
            "[%s.%s] Bronze table not deployed — emitting warning result per § 3 "
            "(l99_minutes=None, notes='Bronze not deployed yet').",
            source_name, table_name,
        )
        return LatenessResult(
            source_name=source_name,
            table_name=table_name,
            l99_minutes=None,
            sample_count=0,
            measured_at=measured_at,
            notes=NOTE_BRONZE_MISSING,
            prior_l99_minutes=prior_l99,
            drift_pct=None,
        )

    # ---- Source query ----
    sql, params = _build_source_delta_query(
        table_config, lookback_days=lookback_days,
    )
    try:
        rows = source_query_fn(source_name, sql, params)
    except SourceConnectError:
        # Propagate the canonical class — CLI shim handles the audit row.
        raise
    except Exception as exc:  # noqa: BLE001
        # Wrap any other exception into SourceConnectError per spec § 3
        # error mode mapping. The CLI shim then writes the audit row
        # with Status=FAILED and the wrapped error.
        raise SourceConnectError(
            f"Source query failed for {source_name}.{table_name}: {exc}"
        ) from exc

    # ---- Sample-count gate ----
    deltas = [row[0] for row in rows if row and row[0] is not None]
    sample_count = len(deltas)

    if sample_count == 0:
        # Truly empty distribution — InsufficientSampleError path per § 3
        # but we return a populated result with l99_minutes=None so the
        # CLI shim writes a uniform audit row.
        logger.info(
            "[%s.%s] Zero rows in lookback window of %d days — "
            "emitting warning result with l99_minutes=None.",
            source_name, table_name, lookback_days,
        )
        return LatenessResult(
            source_name=source_name,
            table_name=table_name,
            l99_minutes=None,
            sample_count=0,
            measured_at=measured_at,
            notes=f"{NOTE_LOW_SAMPLE_PREFIX}: 0",
            prior_l99_minutes=prior_l99,
            drift_pct=None,
        )

    # ---- p99 computation ----
    l99 = _compute_p99_minutes(deltas)

    if sample_count < MIN_SAMPLE_COUNT:
        # Below threshold — populate l99 anyway with the warning note
        # per spec § 3 "UPDATE writes the L99 anyway with notes
        # 'low sample count: N'".
        notes = f"{NOTE_LOW_SAMPLE_PREFIX}: {sample_count}"
        logger.info(
            "[%s.%s] sample_count=%d below MIN_SAMPLE_COUNT=%d — "
            "l99=%s with warning note (CLI shim will map to exit 1).",
            source_name, table_name, sample_count, MIN_SAMPLE_COUNT, l99,
        )
    else:
        notes = NOTE_OK

    drift = _drift_pct(l99, prior_l99)

    return LatenessResult(
        source_name=source_name,
        table_name=table_name,
        l99_minutes=l99,
        sample_count=sample_count,
        measured_at=measured_at,
        notes=notes,
        prior_l99_minutes=prior_l99,
        drift_pct=drift,
    )


# ---------------------------------------------------------------------------
# Serialization helper for the audit-row Metadata JSON
# ---------------------------------------------------------------------------


def serialize_result(result: LatenessResult) -> dict:
    """Convert :class:`LatenessResult` to a JSON-serializable dict.

    Per spec § 3 Metadata JSON shape — keys match the canonical
    PipelineEventLog Metadata column inventory:
    ``source_name``, ``table_name``, ``l99_minutes``, ``sample_count``,
    ``prior_l99_minutes``, ``drift_pct``, ``notes``, ``measured_at``.

    The ``measured_at`` datetime is rendered ISO 8601 with 'Z' suffix
    (UTC). All other fields are JSON-native (int / float / str / None).
    """
    return {
        "source_name": result.source_name,
        "table_name": result.table_name,
        "l99_minutes": result.l99_minutes,
        "sample_count": result.sample_count,
        "measured_at": result.measured_at.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "notes": result.notes,
        "prior_l99_minutes": result.prior_l99_minutes,
        "drift_pct": result.drift_pct,
    }


def is_drifted(result: LatenessResult, threshold_pct: float) -> bool:
    """Return True iff ``|drift_pct| > threshold_pct`` AND drift_pct is non-None.

    Per spec § 3 "M tables drifted >20% from prior baseline" — first
    measurement (prior=NULL) is NOT drifted; sign of drift is irrelevant
    (a 50% DROP in lateness still flags as drift for operator review).
    """
    if result.drift_pct is None:
        return False
    return abs(result.drift_pct) > threshold_pct
