"""Source row-count integrity check — Phase 2 + Phase 3.1 of the CDC blueprint.

Runs after extraction, before CDC. Queries the source for a quick
``COUNT(*)`` and compares to ``len(df_fresh)``. If the delta exceeds a
configurable tolerance, the run aborts for that table — this defends
against partial / racy extractions that drop rows silently.

Two modes:

* **Full-table** (small tables): no window args → ``SELECT COUNT(*)
  FROM source`` matches what extraction returns.
* **Windowed** (large tables, Phase 3.1): caller passes
  ``date_column``, ``window_start`` and ``window_end`` →
  ``SELECT COUNT(*) FROM source WHERE date_column >= ? AND
  date_column < ?``. The bounds match the half-open ``[start, end)``
  predicate large-table extractors already use, so the count and the
  extracted-row count are apples-to-apples.

Complementary to:

* ``orchestration/guards.py::run_extraction_guard`` — compares to
  *historical baselines* from ``PipelineEventLog``. Catches drops vs
  trend, but won't catch a partial extraction that's been consistent
  across runs (steady-state under-extraction).
* ``cdc/source_verifier.py`` — verifies *individual candidate-delete
  PKs* against the source. Catches false-positive deletes within the
  tolerance band.

This module sits between them in scope: a single fresh-vs-source count
comparison that catches catastrophic partial extractions immediately,
without depending on history.

Public entry point::

    from extract.source_count_check import check_source_count_integrity

    # Small table — full-table count
    result = check_source_count_integrity(df_fresh, table_config)

    # Large table — daily window
    result = check_source_count_integrity(
        df_fresh, table_config,
        date_column=table_config.source_aggregate_column_name,
        window_start=target_date,
        window_end=target_date + timedelta(days=1),
    )

    if not result.ok:
        # Abort the run for this table.
        ...

Behavior summary
----------------

* Disabled via ``CDC_SOURCE_COUNT_CHECK=0`` → ``ok=True``, ``skipped=True``.
* Tolerance via ``CDC_SOURCE_COUNT_TOLERANCE_PCT`` (float). Default 0.5
  (i.e. 0.5%). For per-day windows the operator can tighten via
  ``CDC_SOURCE_COUNT_WINDOWED_TOLERANCE_PCT`` (default 0.1) — daily
  counts have less natural drift than table totals, so a smaller
  tolerance catches more.
* Source query failure: ``ok`` defaults to True with ``skipped=True`` —
  this check shouldn't block the pipeline on connection blips.
  Set ``CDC_SOURCE_COUNT_STRICT_ON_FAILURE=1`` to invert and fail closed.
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import date as date_cls
from typing import TYPE_CHECKING, Any

import polars as pl

if TYPE_CHECKING:
    from orchestration.table_config import TableConfig


logger = logging.getLogger(__name__)


_DISABLE_ENV = "CDC_SOURCE_COUNT_CHECK"
_TOLERANCE_ENV = "CDC_SOURCE_COUNT_TOLERANCE_PCT"
_WINDOWED_TOLERANCE_ENV = "CDC_SOURCE_COUNT_WINDOWED_TOLERANCE_PCT"
_STRICT_ENV = "CDC_SOURCE_COUNT_STRICT_ON_FAILURE"

_DEFAULT_TOLERANCE_PCT = 0.5
_DEFAULT_WINDOWED_TOLERANCE_PCT = 0.1


@dataclass
class CountCheckResult:
    """Outcome of a source-row-count integrity check."""

    source_name: str
    table_name: str
    ok: bool = True
    skipped: bool = False
    skip_reason: str = ""

    extracted_count: int = 0
    source_count: int = 0
    delta: int = 0
    delta_pct: float = 0.0
    tolerance_pct: float = _DEFAULT_TOLERANCE_PCT

    # Phase 3.1: windowed metadata for per-day diagnostics.
    windowed: bool = False
    window_start: str = ""
    window_end: str = ""

    error: str | None = None
    duration_ms: float = 0.0

    def as_metadata_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "extracted_count": self.extracted_count,
            "source_count": self.source_count,
            "delta": self.delta,
            "delta_pct": round(self.delta_pct, 4),
            "tolerance_pct": self.tolerance_pct,
            "windowed": self.windowed,
            "window_start": self.window_start,
            "window_end": self.window_end,
            "duration_ms": round(self.duration_ms, 1),
        }


def check_source_count_integrity(
    df_fresh: pl.DataFrame,
    table_config: TableConfig,
    *,
    date_column: str | None = None,
    window_start: date_cls | None = None,
    window_end: date_cls | None = None,
) -> CountCheckResult:
    """Compare ``len(df_fresh)`` to ``COUNT(*)`` from source.

    Returns ``CountCheckResult`` describing the delta. Caller (the
    orchestrator) interprets ``ok=False`` as a signal to abort the run
    for this table.

    Args:
        df_fresh: The freshly-extracted DataFrame.
        table_config: Source connection metadata.
        date_column: Source-side column name to scope the COUNT by.
            Required for windowed callers; must match the column the
            extractor used in its own WHERE clause.
        window_start: Inclusive lower bound for the date scope.
        window_end: Exclusive upper bound for the date scope. The
            half-open ``[start, end)`` interval matches the extractor
            convention (``WHERE date_col >= :start AND date_col <
            :end``) so the count and the extracted-row count are
            apples-to-apples.

    All three window args must be provided together for windowed
    behavior; passing only one raises ``ValueError``.
    """
    started = time.monotonic()

    windowed = _validate_window_args(date_column, window_start, window_end)

    result = CountCheckResult(
        source_name=table_config.source_name,
        table_name=table_config.source_object_name,
        extracted_count=int(df_fresh.height) if df_fresh is not None else 0,
        tolerance_pct=_read_tolerance(windowed=windowed),
        windowed=windowed,
        window_start=window_start.isoformat() if window_start else "",
        window_end=window_end.isoformat() if window_end else "",
    )

    if os.environ.get(_DISABLE_ENV) == "0":
        result.skipped = True
        result.skip_reason = f"{_DISABLE_ENV}=0"
        _emit_log(result)
        return _stamp_duration(result, started)

    try:
        result.source_count = _query_source_count(
            table_config,
            date_column=date_column,
            window_start=window_start,
            window_end=window_end,
        )
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        result.skipped = True
        result.skip_reason = f"source COUNT(*) failed: {result.error}"
        strict = os.environ.get(_STRICT_ENV, "0") == "1"
        if strict:
            result.ok = False
            logger.error(
                "Source-count check FAILED for %s.%s — strict mode: "
                "marking ok=False. Reason: %s",
                result.source_name, result.table_name, result.error,
            )
        else:
            logger.warning(
                "Source-count check FAILED for %s.%s — non-strict mode: "
                "skipping check, ok=True. Reason: %s",
                result.source_name, result.table_name, result.error,
            )
        _emit_log(result)
        return _stamp_duration(result, started)

    result.delta = result.extracted_count - result.source_count
    if result.source_count == 0:
        # Source genuinely empty — extraction must also be empty for OK.
        result.delta_pct = 0.0 if result.extracted_count == 0 else 100.0
    else:
        result.delta_pct = abs(result.delta) / result.source_count * 100.0

    result.ok = result.delta_pct <= result.tolerance_pct
    _emit_log(result)
    return _stamp_duration(result, started)


# ---------------------------------------------------------------------------
# Source COUNT(*) query
# ---------------------------------------------------------------------------


def _validate_window_args(
    date_column: str | None,
    window_start: date_cls | None,
    window_end: date_cls | None,
) -> bool:
    """Returns True for windowed mode, False for full-table.

    Raises ``ValueError`` if some-but-not-all window args were provided —
    avoids silently degrading to a full-table count when a caller
    expected a windowed one.
    """
    provided = [
        date_column is not None and date_column != "",
        window_start is not None,
        window_end is not None,
    ]
    if all(provided):
        return True
    if any(provided):
        raise ValueError(
            "Windowed source-count check requires all of date_column, "
            "window_start, window_end. Got "
            f"date_column={date_column!r} window_start={window_start} "
            f"window_end={window_end}"
        )
    return False


def _query_source_count(
    table_config: TableConfig,
    *,
    date_column: str | None,
    window_start: date_cls | None,
    window_end: date_cls | None,
) -> int:
    """Run ``SELECT COUNT(*) FROM source.schema.table [WHERE ...]``.

    Routes Oracle vs SQL Server via the source registry. The query is
    one round-trip; no pagination, no result-set materialization.
    """
    from utils.sources import SourceType, get_source_for_table

    source = get_source_for_table(table_config)
    schema = table_config.source_schema_name
    table = table_config.source_object_name
    fully_qualified = f"{schema}.{table}" if schema else table

    is_oracle = source.source_type == SourceType.ORACLE
    where, params = _build_where_clause(
        date_column, window_start, window_end, is_oracle,
    )
    query = f"SELECT COUNT(*) FROM {fully_qualified}{where}"

    if is_oracle:
        import oracledb
        conn = oracledb.connect(**source.oracledb_connect_params())
    else:
        from utils.connections import get_source_connection
        conn = get_source_connection(
            host=source.host,
            database=source.service_or_database,
            port=source.port,
        )

    try:
        cursor = conn.cursor()
        try:
            cursor.execute(query, params)
            row = cursor.fetchone()
            return int(row[0])
        finally:
            cursor.close()
    finally:
        conn.close()


def _build_where_clause(
    date_column: str | None,
    window_start: date_cls | None,
    window_end: date_cls | None,
    is_oracle: bool,
) -> tuple[str, dict | list]:
    """Return the parameterized WHERE clause and the bind values.

    Oracle uses named binds (``:start_dt`` / ``:end_dt``) — same pattern
    as ``extract/oracle_extractor.py``. SQL Server uses positional ``?``
    placeholders.

    Returns ``("", [])`` for full-table mode. The caller passes the
    second item directly to ``cursor.execute(query, params)``.
    """
    if date_column is None:
        return "", []

    if is_oracle:
        where = f" WHERE {date_column} >= :start_dt AND {date_column} < :end_dt"
        params = {"start_dt": window_start, "end_dt": window_end}
        return where, params

    where = f" WHERE {date_column} >= ? AND {date_column} < ?"
    return where, [window_start, window_end]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _read_tolerance(*, windowed: bool) -> float:
    env = _WINDOWED_TOLERANCE_ENV if windowed else _TOLERANCE_ENV
    default = _DEFAULT_WINDOWED_TOLERANCE_PCT if windowed else _DEFAULT_TOLERANCE_PCT
    raw = os.environ.get(env)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning(
            "Invalid %s=%s; falling back to default %.2f",
            env, raw, default,
        )
        return default


def _stamp_duration(result: CountCheckResult, started_monotonic: float) -> CountCheckResult:
    result.duration_ms = (time.monotonic() - started_monotonic) * 1000.0
    return result


def _emit_log(result: CountCheckResult) -> None:
    payload = {
        "signal": "source_count_check",
        "source": result.source_name,
        "table": result.table_name,
        "extracted_count": result.extracted_count,
        "source_count": result.source_count,
        "delta": result.delta,
        "delta_pct": round(result.delta_pct, 4),
        "tolerance_pct": result.tolerance_pct,
        "windowed": result.windowed,
        "window_start": result.window_start,
        "window_end": result.window_end,
        "ok": result.ok,
        "skipped": result.skipped,
        "skip_reason": result.skip_reason,
        "error": result.error,
    }
    if result.skipped:
        logger.info("CDC_SRC_COUNT: %s", json.dumps(payload))
        return
    if not result.ok:
        logger.error("CDC_SRC_COUNT: %s", json.dumps(payload))
        scope = (
            f" for window [{result.window_start}, {result.window_end})"
            if result.windowed else ""
        )
        logger.error(
            "Source-count integrity check FAILED for %s.%s%s: extracted "
            "%d rows, source has %d (delta=%+d, %.4f%%, tolerance=%.4f%%). "
            "Likely a partial extraction. Run will be aborted for this "
            "%s. See docs/cdc_root_cause_blueprint.md.",
            result.source_name, result.table_name, scope,
            result.extracted_count, result.source_count,
            result.delta, result.delta_pct, result.tolerance_pct,
            "day" if result.windowed else "table",
        )
    else:
        logger.info("CDC_SRC_COUNT: %s", json.dumps(payload))
