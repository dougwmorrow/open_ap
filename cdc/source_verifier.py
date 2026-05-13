"""Verify-before-close — Phase 2 of ``docs/cdc_root_cause_blueprint.md``.

The CDC reverse-anti-join classifies a PK as deleted whenever it's
present in Stage current rows but absent from the fresh extraction.
Under a flapping source extraction, this produces false-positive
deletes — the row is *actually still in source*, but the extractor
dropped it. The current row gets closed; the next run sees a
"resurrection" and writes a new ``I`` event in Stage.

This module verifies candidate deletes against the source before the
engine closes their Stage current rows. If the source still has the
PK, the close is **suppressed** for that PK — the engine treats the
delete classification as a false positive and does nothing.

Public entry point::

    from cdc.source_verifier import verify_deletes_against_source

    result = verify_deletes_against_source(
        candidate_pks=df_deleted_pks,
        pk_columns=["ACCTNBR"],
        table_config=tc,
    )
    # result.confirmed_deletes — safe to close
    # result.false_negatives  — DO NOT close (source still has them)
    # result.skipped          — True if verification couldn't run

Behavior summary
----------------

* Empty candidate set → no-op, both outputs empty.
* Disabled via ``CDC_VERIFY_BEFORE_CLOSE=0`` → ``skipped=True``,
  caller proceeds with original close behavior.
* Candidate set > ``CDC_VERIFY_MAX_CANDIDATES`` (default 10000) →
  ``skipped=True``. At that scale the extraction-count check should
  have aborted the run; if it didn't, dumping >10k IN-list queries on
  the source isn't the right defense.
* Composite PKs supported — falls back to OR-of-AND construction
  with smaller batch size.
* Source query failure (network, permissions): behavior governed by
  ``CDC_VERIFY_STRICT_ON_FAILURE``. Default ``1`` (strict): treat ALL
  candidates as false negatives — refuse to close on uncertainty.
  ``0``: log WARNING and treat all as confirmed — fall back to
  original behavior. Production should always run strict.
* Always logs a structured ``CDC_VERIFY: {...}`` JSON line plus a
  human-readable summary.

Scope of v1
-----------

* Small tables only. Windowed (large-table) CDC is detected via
  ``windowed=True`` and skipped with a clear log line.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import polars as pl

if TYPE_CHECKING:
    from orchestration.table_config import TableConfig


logger = logging.getLogger(__name__)


# Env-var knobs.
_DISABLE_ENV = "CDC_VERIFY_BEFORE_CLOSE"
_STRICT_ENV = "CDC_VERIFY_STRICT_ON_FAILURE"
_MAX_CANDIDATES_ENV = "CDC_VERIFY_MAX_CANDIDATES"

# IN-list batch sizes. Oracle's hard ceiling is 1000 elements per IN
# clause; SQL Server's parameter limit is 2100 (per statement), so 500
# is a safe round number for both. Composite PKs use a smaller batch
# because we send N parameters per row rather than 1.
_BATCH_SIZE_SINGLE_PK = 500
_BATCH_SIZE_COMPOSITE_PK = 200

_DEFAULT_MAX_CANDIDATES = 10000


@dataclass
class VerificationResult:
    """Outcome of a verify-before-close run for one table."""

    source_name: str
    table_name: str

    # Candidate PKs that source confirms are gone — safe to close.
    confirmed_deletes: pl.DataFrame = field(
        default_factory=lambda: pl.DataFrame()
    )
    # Candidate PKs that source still has — DO NOT close.
    false_negatives: pl.DataFrame = field(
        default_factory=lambda: pl.DataFrame()
    )

    candidate_count: int = 0
    confirmed_count: int = 0
    false_negative_count: int = 0

    skipped: bool = False
    skip_reason: str = ""
    error: str | None = None
    duration_ms: float = 0.0

    def as_metadata_dict(self) -> dict[str, Any]:
        return {
            "candidate_count": self.candidate_count,
            "confirmed_count": self.confirmed_count,
            "false_negative_count": self.false_negative_count,
            "skipped": self.skipped,
            "skip_reason": self.skip_reason,
            "duration_ms": round(self.duration_ms, 1),
        }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def verify_deletes_against_source(
    candidate_pks: pl.DataFrame,
    pk_columns: list[str],
    table_config: TableConfig,
    *,
    windowed: bool = False,
) -> VerificationResult:
    """Verify candidate-delete PKs against the source system.

    Returns a :class:`VerificationResult` describing which PKs source
    confirms are gone (safe to close) vs which are still present
    (false negatives — DO NOT close).
    """
    import time

    started = time.monotonic()
    result = VerificationResult(
        source_name=table_config.source_name,
        table_name=table_config.source_object_name,
        candidate_count=int(candidate_pks.height) if candidate_pks is not None else 0,
    )

    if result.candidate_count == 0:
        # Nothing to verify — short-circuit success.
        _emit_log(result)
        return _stamp_duration(result, started)

    if windowed:
        result.skipped = True
        result.skip_reason = "windowed CDC — verify-before-close not yet supported"
        _emit_log(result)
        return _stamp_duration(result, started)

    if os.environ.get(_DISABLE_ENV) == "0":
        result.skipped = True
        result.skip_reason = f"{_DISABLE_ENV}=0"
        _emit_log(result)
        return _stamp_duration(result, started)

    if not pk_columns:
        result.skipped = True
        result.skip_reason = "no PK columns configured"
        _emit_log(result)
        return _stamp_duration(result, started)

    max_candidates = _read_int_env(_MAX_CANDIDATES_ENV, _DEFAULT_MAX_CANDIDATES)
    if result.candidate_count > max_candidates:
        result.skipped = True
        result.skip_reason = (
            f"candidate count {result.candidate_count} exceeds "
            f"{_MAX_CANDIDATES_ENV}={max_candidates} — extraction-count "
            f"check should have aborted; refusing to flood source with "
            f"IN-list queries"
        )
        logger.warning(
            "Verify-before-close skipped for %s.%s: %s",
            result.source_name, result.table_name, result.skip_reason,
        )
        _emit_log(result)
        return _stamp_duration(result, started)

    try:
        found_pks = _query_source_for_pks(candidate_pks, pk_columns, table_config)
    except Exception as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        result.skipped = True
        result.skip_reason = f"source query failed: {result.error}"
        strict = os.environ.get(_STRICT_ENV, "1") == "1"
        if strict:
            # Conservative: treat all candidates as false negatives so the
            # caller refuses to close any rows. Better to under-close than
            # to over-close on uncertain ground.
            result.false_negatives = candidate_pks
            result.false_negative_count = result.candidate_count
            logger.error(
                "Verify-before-close FAILED for %s.%s — strict mode: "
                "treating all %d candidate(s) as false negatives. "
                "No Stage current rows will be closed this run. "
                "Reason: %s",
                result.source_name, result.table_name,
                result.candidate_count, result.error,
            )
        else:
            # Compatibility mode — caller proceeds with original close
            # behavior. Logged as a single WARNING.
            logger.warning(
                "Verify-before-close FAILED for %s.%s — non-strict mode "
                "(%s=0): falling back to original close behavior. "
                "Reason: %s",
                result.source_name, result.table_name,
                _STRICT_ENV, result.error,
            )
        _emit_log(result)
        return _stamp_duration(result, started)

    # Partition candidate_pks: those found in source = false negatives,
    # those not found = confirmed deletes.
    if found_pks.height == 0:
        result.confirmed_deletes = candidate_pks
        result.false_negatives = candidate_pks.head(0)
    else:
        # Anti-join on PK columns. Aligning dtypes defensively in case
        # the source query returned subtly different types
        # (e.g. NUMBER → Int64 vs Int32).
        found_pks = _align_pk_dtypes(found_pks, candidate_pks, pk_columns)
        result.confirmed_deletes = candidate_pks.join(
            found_pks, on=pk_columns, how="anti",
        )
        result.false_negatives = candidate_pks.join(
            found_pks, on=pk_columns, how="semi",
        )

    result.confirmed_count = int(result.confirmed_deletes.height)
    result.false_negative_count = int(result.false_negatives.height)
    _emit_log(result)
    return _stamp_duration(result, started)


# ---------------------------------------------------------------------------
# Source query
# ---------------------------------------------------------------------------


def _query_source_for_pks(
    candidate_pks: pl.DataFrame,
    pk_columns: list[str],
    table_config: TableConfig,
) -> pl.DataFrame:
    """Query the source system for PKs in ``candidate_pks``. Returns a
    Polars DataFrame containing only the PKs that source confirms exist.

    Routes to the Oracle or SQL Server path based on the registered
    source type. Batches the IN-list / OR-of-AND clauses to stay within
    Oracle's 1000-element IN ceiling and SQL Server's 2100-parameter
    limit.
    """
    from utils.sources import SourceType, get_source_for_table

    source = get_source_for_table(table_config)
    schema = table_config.source_schema_name
    table = table_config.source_object_name
    fully_qualified = f"{schema}.{table}" if schema else table

    is_composite = len(pk_columns) > 1
    batch_size = _BATCH_SIZE_COMPOSITE_PK if is_composite else _BATCH_SIZE_SINGLE_PK

    found_rows: list[dict[str, Any]] = []

    if source.source_type == SourceType.ORACLE:
        import oracledb
        conn = oracledb.connect(**source.oracledb_connect_params())
        placeholder = lambda i: f":p{i}"  # noqa: E731
    else:
        from utils.connections import get_source_connection
        conn = get_source_connection(
            host=source.host,
            database=source.service_or_database,
            port=source.port,
        )
        placeholder = lambda i: "?"  # noqa: E731

    try:
        for batch in _iter_batches(candidate_pks, pk_columns, batch_size):
            query, params = _build_existence_query(
                fully_qualified, pk_columns, batch, placeholder,
            )
            cursor = conn.cursor()
            try:
                cursor.execute(query, params)
                col_names = [d[0] for d in cursor.description]
                for row in cursor:
                    found_rows.append(dict(zip(col_names, row)))
            finally:
                cursor.close()
    finally:
        conn.close()

    if not found_rows:
        # Build empty df with same dtypes as candidate_pks so anti-join works.
        return candidate_pks.head(0).select(pk_columns)
    return pl.DataFrame(found_rows)


def _iter_batches(
    df: pl.DataFrame,
    pk_columns: list[str],
    batch_size: int,
):
    """Yield Python lists of PK tuples (one tuple per row) sized at
    ``batch_size``. Tuples are unpacked downstream into IN-clause params.
    """
    rows = df.select(pk_columns).iter_rows()
    batch: list[tuple] = []
    for r in rows:
        batch.append(r)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def _build_existence_query(
    fully_qualified: str,
    pk_columns: list[str],
    batch: list[tuple],
    placeholder,
) -> tuple[str, list]:
    """Build the source-side existence query for one batch of candidate PKs.

    Single-column PK::

        SELECT pk FROM schema.table WHERE pk IN (?, ?, ?)

    Composite PK::

        SELECT pk1, pk2 FROM schema.table
        WHERE (pk1=? AND pk2=?) OR (pk1=? AND pk2=?) OR ...

    The OR-of-AND form is portable across Oracle and SQL Server.
    Row-constructor IN syntax (`WHERE (a, b) IN ((1,'x'), ...)`) works
    on Oracle but not on SQL Server, so the OR form is used uniformly.
    """
    select_cols = ", ".join(pk_columns)

    if len(pk_columns) == 1:
        col = pk_columns[0]
        # Each batch row is a 1-tuple (pk_value,).
        param_idx = 0
        placeholders = []
        params: list = []
        for (val,) in batch:
            placeholders.append(placeholder(param_idx))
            params.append(val)
            param_idx += 1
        in_list = ", ".join(placeholders)
        query = f"SELECT {select_cols} FROM {fully_qualified} WHERE {col} IN ({in_list})"
        return query, params

    # Composite — OR-of-AND.
    or_terms: list[str] = []
    params: list = []
    param_idx = 0
    for row_tuple in batch:
        and_terms = []
        for col_name, val in zip(pk_columns, row_tuple):
            and_terms.append(f"{col_name} = {placeholder(param_idx)}")
            params.append(val)
            param_idx += 1
        or_terms.append("(" + " AND ".join(and_terms) + ")")
    where = " OR ".join(or_terms)
    query = f"SELECT {select_cols} FROM {fully_qualified} WHERE {where}"
    return query, params


def _align_pk_dtypes(
    found_pks: pl.DataFrame,
    candidate_pks: pl.DataFrame,
    pk_columns: list[str],
) -> pl.DataFrame:
    """Cast ``found_pks`` PK columns to match ``candidate_pks`` dtypes.

    Source drivers occasionally return subtly different integer widths
    (Int32 vs Int64) or NUMBER as Decimal vs Int. Without alignment the
    Polars anti-join silently produces zero matches.
    """
    casts = {
        c: candidate_pks.schema[c]
        for c in pk_columns
        if c in found_pks.columns and found_pks.schema[c] != candidate_pks.schema[c]
    }
    if not casts:
        return found_pks
    return found_pks.with_columns(
        [pl.col(c).cast(dt, strict=False) for c, dt in casts.items()]
    )


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def _emit_log(result: VerificationResult) -> None:
    """Emit one structured JSON line and (when notable) a human WARNING."""
    payload = {
        "signal": "verify_before_close",
        "source": result.source_name,
        "table": result.table_name,
        "candidate_count": result.candidate_count,
        "confirmed_count": result.confirmed_count,
        "false_negative_count": result.false_negative_count,
        "skipped": result.skipped,
        "skip_reason": result.skip_reason,
        "error": result.error,
    }

    if result.skipped:
        logger.info("CDC_VERIFY: %s", json.dumps(payload))
        return

    if result.false_negative_count > 0:
        logger.warning("CDC_VERIFY: %s", json.dumps(payload))
        # Sample a handful of suppressed PKs for the operator log.
        sample = (
            result.false_negatives.head(5).to_dicts()
            if result.false_negatives.height > 0
            else []
        )
        logger.warning(
            "Verify-before-close suppressed %d/%d delete(s) for %s.%s — "
            "source still has these PKs. Stage current rows will NOT be "
            "closed this run. Sample: %s. Likely a flapping/partial "
            "extraction; investigate the EXTRACT step. See "
            "docs/cdc_root_cause_blueprint.md.",
            result.false_negative_count, result.candidate_count,
            result.source_name, result.table_name, sample,
        )
    else:
        # All candidates were genuine deletes. INFO level — visible in
        # PipelineLog as a positive heartbeat.
        logger.info("CDC_VERIFY: %s", json.dumps(payload))


def _stamp_duration(result: VerificationResult, started_monotonic: float) -> VerificationResult:
    import time
    result.duration_ms = (time.monotonic() - started_monotonic) * 1000.0
    return result


def _read_int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning(
            "Invalid %s=%s; falling back to default %d",
            name, raw, default,
        )
        return default
