"""R-6: SCD2 chain repair operations (CLI-only, opt-in).

R-5 (``scd2_integrity.py``) reports defects; R-6 fixes only the ones that
are deterministically safe to repair. Anything ambiguous is left for human
review — auto-repairing the wrong thing destroys history.

Repair categories
-----------------

**Auto-repairable (safe + idempotent):**

* ``sentinel_fill`` — Flag=1 rows with ``UdmSourceEndDate IS NULL`` get
  ``'2999-12-31'`` stamped. Pure invariant fix; nothing is destroyed.

* ``orphan_cleanup`` — wraps the existing
  :func:`scd2.engine._cleanup_orphaned_inactive_rows` so operators can run
  it explicitly via CLI instead of waiting for the next pipeline run. The
  predicate (``Flag=0 + Op IN ('U','R') + both EndDates NULL``) is the
  hardened SCD2-P1-e form that won't touch legacy closed rows.

* ``duplicate_active_dedup`` — when a PK has more than one Flag=1 row
  (P0-8 crash recovery artifact), keep the row with the latest
  ``UdmEffectiveDateTime`` and close the others (``Flag=0``,
  ``UdmEndDateTime=now``, ``UdmSourceEndDate=successor_begin - 1 day``).

**NOT auto-repairable — log + require human review:**

* Overlapping intervals (load-time or source-date pair).
* Zero-active PKs (no Flag=1 AND no Flag=2) — legitimately deleted rows
  have Flag=2; missing both means the deletion context was lost.
* Source-date gaps — likely expected when source publishes episodically.
* Invalid Flag/Op domain values — investigate, don't auto-correct.
* Flag=2 rows with NULL UdmEndDateTime — delete-close UPDATE failed
  mid-flight; manual investigation needed.

Audit
-----

Every operation writes one row to ``General.ops.SCD2RepairLog`` (created
by ``migrations/scd2_repair_log.py``) with the repair type, row count,
sample PKs, status (``DRY_RUN`` / ``APPLIED`` / ``FAILED`` / ``SKIPPED``),
and timing.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import utils.configuration as config
from utils.connections import (
    cursor_for, get_connection, get_general_connection,
    quote_identifier, quote_table,
)
from extract.udm_connectorx_extractor import table_exists

if TYPE_CHECKING:
    from orchestration.table_config import TableConfig

logger = logging.getLogger(__name__)


# Maximum sample PKs persisted to the repair log. Keeps row size bounded
# while still giving operators enough context to investigate.
_SAMPLE_PK_LIMIT = 10


@dataclass
class RepairResult:
    """Result of a single repair operation on a single table."""

    source_name: str
    table_name: str
    repair_type: str
    status: str  # DRY_RUN | APPLIED | FAILED | SKIPPED
    rows_affected: int = 0
    sample_pks: list[str] = field(default_factory=list)
    message: str = ""
    error_message: str | None = None
    duration_ms: int = 0

    @property
    def is_clean(self) -> bool:
        return self.status in ("DRY_RUN", "APPLIED") and not self.error_message


# ---------------------------------------------------------------------------
# Repair: sentinel fill on Flag=1 rows
# ---------------------------------------------------------------------------


def repair_sentinel_fill(
    table_config: TableConfig,
    *,
    dry_run: bool,
) -> RepairResult:
    """Fill ``UdmSourceEndDate = '2999-12-31'`` on Flag=1 rows missing it.

    Pure invariant fix — never destroys data. Affects only rows that
    failed to receive the sentinel during a prior run (e.g. crash between
    INSERT and ``_activate_new_versions``, or a partial Phase 1 backfill).
    """
    started = time.time()
    bronze_table = table_config.bronze_full_table_name
    result = RepairResult(
        source_name=table_config.source_name,
        table_name=table_config.source_object_name,
        repair_type="sentinel_fill",
        status="DRY_RUN" if dry_run else "APPLIED",
    )

    if not table_exists(bronze_table):
        result.status = "SKIPPED"
        result.message = f"Bronze table {bronze_table} does not exist."
        result.duration_ms = int((time.time() - started) * 1000)
        return result

    db = bronze_table.split(".")[0]
    q_bronze = quote_table(bronze_table)
    pk_columns = table_config.pk_columns

    try:
        # Count + sample first
        with cursor_for(db) as cursor:
            cursor.execute(f"""
                SELECT COUNT(*) FROM {q_bronze}
                WHERE UdmActiveFlag = 1
                  AND UdmSourceBeginDate IS NOT NULL
                  AND (UdmSourceEndDate IS NULL OR UdmSourceEndDate <> '2999-12-31')
            """)
            count = cursor.fetchone()[0]
            result.rows_affected = count

            if count > 0 and pk_columns:
                pk_select = ", ".join(quote_identifier(c) for c in pk_columns)
                cursor.execute(f"""
                    SELECT TOP {_SAMPLE_PK_LIMIT} {pk_select}
                    FROM {q_bronze}
                    WHERE UdmActiveFlag = 1
                      AND UdmSourceBeginDate IS NOT NULL
                      AND (UdmSourceEndDate IS NULL OR UdmSourceEndDate <> '2999-12-31')
                """)
                result.sample_pks = [str(row) for row in cursor.fetchall()]

            if count == 0:
                result.message = "No Flag=1 rows missing the source-end sentinel."
                result.duration_ms = int((time.time() - started) * 1000)
                return result

            if dry_run:
                result.message = (
                    f"DRY RUN — would set UdmSourceEndDate='2999-12-31' on "
                    f"{count} Flag=1 row(s)."
                )
                result.duration_ms = int((time.time() - started) * 1000)
                return result

            cursor.execute(f"""
                UPDATE {q_bronze}
                SET UdmSourceEndDate = '2999-12-31'
                WHERE UdmActiveFlag = 1
                  AND UdmSourceBeginDate IS NOT NULL
                  AND (UdmSourceEndDate IS NULL OR UdmSourceEndDate <> '2999-12-31')
            """)
            actual = cursor.rowcount
            result.rows_affected = actual
            result.message = f"Stamped sentinel on {actual} Flag=1 row(s)."
        logger.info("R-6 sentinel_fill: %s — %s", bronze_table, result.message)
    except Exception as exc:
        result.status = "FAILED"
        result.error_message = str(exc)
        logger.exception("R-6 sentinel_fill failed for %s", bronze_table)

    result.duration_ms = int((time.time() - started) * 1000)
    return result


# ---------------------------------------------------------------------------
# Repair: orphan cleanup wrapper (calls existing engine helper)
# ---------------------------------------------------------------------------


def repair_orphan_cleanup(
    table_config: TableConfig,
    *,
    dry_run: bool,
) -> RepairResult:
    """B-4: delete in-flight orphaned Flag=0 rows.

    Wraps :func:`scd2.engine._cleanup_orphaned_inactive_rows` so operators
    can run it explicitly. The engine's predicate is the hardened
    SCD2-P1-e form (BOTH EndDates NULL + Op IN ('U','R')).
    """
    from scd2.engine import _cleanup_orphaned_inactive_rows

    started = time.time()
    bronze_table = table_config.bronze_full_table_name
    result = RepairResult(
        source_name=table_config.source_name,
        table_name=table_config.source_object_name,
        repair_type="orphan_cleanup",
        status="DRY_RUN" if dry_run else "APPLIED",
    )

    if not table_exists(bronze_table):
        result.status = "SKIPPED"
        result.message = f"Bronze table {bronze_table} does not exist."
        result.duration_ms = int((time.time() - started) * 1000)
        return result

    db = bronze_table.split(".")[0]
    q_bronze = quote_table(bronze_table)
    pk_columns = table_config.pk_columns

    try:
        with cursor_for(db) as cursor:
            cursor.execute(f"""
                SELECT COUNT(*) FROM {q_bronze}
                WHERE UdmActiveFlag = 0
                  AND UdmEndDateTime IS NULL
                  AND UdmSourceEndDate IS NULL
                  AND UdmScd2Operation IN ('U', 'R')
            """)
            count = cursor.fetchone()[0]
            result.rows_affected = count

            if count > 0 and pk_columns:
                pk_select = ", ".join(quote_identifier(c) for c in pk_columns)
                cursor.execute(f"""
                    SELECT TOP {_SAMPLE_PK_LIMIT} {pk_select}
                    FROM {q_bronze}
                    WHERE UdmActiveFlag = 0
                      AND UdmEndDateTime IS NULL
                      AND UdmSourceEndDate IS NULL
                      AND UdmScd2Operation IN ('U', 'R')
                """)
                result.sample_pks = [str(row) for row in cursor.fetchall()]

        if count == 0:
            result.message = "No in-flight orphan rows."
            result.duration_ms = int((time.time() - started) * 1000)
            return result

        if dry_run:
            result.message = f"DRY RUN — would DELETE {count} in-flight orphan row(s)."
            result.duration_ms = int((time.time() - started) * 1000)
            return result

        deleted = _cleanup_orphaned_inactive_rows(bronze_table, table_config)
        result.rows_affected = deleted
        result.message = f"Deleted {deleted} in-flight orphan row(s)."
        logger.info("R-6 orphan_cleanup: %s — %s", bronze_table, result.message)
    except Exception as exc:
        result.status = "FAILED"
        result.error_message = str(exc)
        logger.exception("R-6 orphan_cleanup failed for %s", bronze_table)

    result.duration_ms = int((time.time() - started) * 1000)
    return result


# ---------------------------------------------------------------------------
# Repair: dedupe duplicate Flag=1 rows per PK
# ---------------------------------------------------------------------------


def repair_duplicate_active(
    table_config: TableConfig,
    *,
    dry_run: bool,
) -> RepairResult:
    """When a PK has >1 Flag=1 row, keep the latest UdmEffectiveDateTime; close the rest.

    Closes the older duplicates via ``Flag=0, UdmEndDateTime=now,
    UdmSourceEndDate = winner_UdmSourceBeginDate - 1 day`` — same semantic
    as a normal update-close. The winner row is unchanged.

    Caller is expected to have run R-5 first; this function is a no-op
    when ``duplicate_active_pks = 0``.
    """
    started = time.time()
    bronze_table = table_config.bronze_full_table_name
    result = RepairResult(
        source_name=table_config.source_name,
        table_name=table_config.source_object_name,
        repair_type="duplicate_active_dedup",
        status="DRY_RUN" if dry_run else "APPLIED",
    )

    if not table_exists(bronze_table):
        result.status = "SKIPPED"
        result.message = f"Bronze table {bronze_table} does not exist."
        result.duration_ms = int((time.time() - started) * 1000)
        return result

    pk_columns = table_config.pk_columns
    if not pk_columns:
        result.status = "SKIPPED"
        result.message = "No PK columns configured — cannot dedupe."
        result.duration_ms = int((time.time() - started) * 1000)
        return result

    db = bronze_table.split(".")[0]
    q_bronze = quote_table(bronze_table)
    pk_join = " AND ".join(
        f"a.{quote_identifier(c)} = b.{quote_identifier(c)}" for c in pk_columns
    )
    pk_partition = ", ".join(quote_identifier(c) for c in pk_columns)
    pk_select_quoted = ", ".join(quote_identifier(c) for c in pk_columns)
    pk_select_a = ", ".join(f"a.{quote_identifier(c)}" for c in pk_columns)

    try:
        with cursor_for(db) as cursor:
            # Count duplicate-Flag=1 rows that AREN'T the winner.
            count_sql = f"""
                SELECT COUNT(*) FROM (
                    SELECT _scd2_key,
                        ROW_NUMBER() OVER (
                            PARTITION BY {pk_partition}
                            ORDER BY UdmEffectiveDateTime DESC, _scd2_key DESC
                        ) AS rn
                    FROM {q_bronze}
                    WHERE UdmActiveFlag = 1
                ) versioned
                WHERE rn > 1
            """
            cursor.execute(count_sql)
            count = cursor.fetchone()[0]
            result.rows_affected = count

            if count == 0:
                result.message = "No duplicate Flag=1 rows."
                result.duration_ms = int((time.time() - started) * 1000)
                return result

            cursor.execute(f"""
                SELECT TOP {_SAMPLE_PK_LIMIT} {pk_select_a}
                FROM {q_bronze} a
                INNER JOIN {q_bronze} b
                  ON {pk_join}
                  AND a._scd2_key <> b._scd2_key
                  AND a.UdmActiveFlag = 1
                  AND b.UdmActiveFlag = 1
                GROUP BY {pk_select_a}
            """)
            result.sample_pks = [str(row) for row in cursor.fetchall()]

            if dry_run:
                result.message = f"DRY RUN — would close {count} duplicate Flag=1 row(s)."
                result.duration_ms = int((time.time() - started) * 1000)
                return result

            now = datetime.now(timezone.utc).replace(tzinfo=None)
            now = now.replace(microsecond=(now.microsecond // 1000) * 1000)
            # Close every Flag=1 row that isn't the winner. UdmSourceEndDate
            # uses the winner row's UdmSourceBeginDate - 1 day so the
            # business chain stays gapless.
            cursor.execute(f"""
                WITH ranked AS (
                    SELECT _scd2_key,
                        ROW_NUMBER() OVER (
                            PARTITION BY {pk_partition}
                            ORDER BY UdmEffectiveDateTime DESC, _scd2_key DESC
                        ) AS rn,
                        FIRST_VALUE(UdmSourceBeginDate) OVER (
                            PARTITION BY {pk_partition}
                            ORDER BY UdmEffectiveDateTime DESC, _scd2_key DESC
                            ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
                        ) AS winner_source_begin
                    FROM {q_bronze}
                    WHERE UdmActiveFlag = 1
                )
                UPDATE t
                SET UdmActiveFlag = 0,
                    UdmEndDateTime = ?,
                    UdmSourceEndDate = DATEADD(DAY, -1, ranked.winner_source_begin)
                FROM {q_bronze} t
                INNER JOIN ranked ON t._scd2_key = ranked._scd2_key
                WHERE ranked.rn > 1
            """, now)
            actual = cursor.rowcount
            result.rows_affected = actual
            result.message = f"Closed {actual} duplicate Flag=1 row(s)."
        logger.info("R-6 duplicate_active_dedup: %s — %s", bronze_table, result.message)
    except Exception as exc:
        result.status = "FAILED"
        result.error_message = str(exc)
        logger.exception("R-6 duplicate_active_dedup failed for %s", bronze_table)

    result.duration_ms = int((time.time() - started) * 1000)
    return result


# ---------------------------------------------------------------------------
# Persistence: write each repair result to General.ops.SCD2RepairLog
# ---------------------------------------------------------------------------


def persist_repair_result(result: RepairResult, batch_id: int | None = None) -> None:
    """Append one row to ``General.ops.SCD2RepairLog`` for the repair operation.

    Non-blocking — log failures here do not fail the repair operation.
    """
    try:
        sample_json = json.dumps(result.sample_pks) if result.sample_pks else None
        completed = datetime.now(timezone.utc).replace(tzinfo=None)
        conn = get_general_connection()
        try:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO ops.SCD2RepairLog
                    (BatchId, SourceName, TableName, RepairType, Status,
                     RowsAffected, SamplePks, Message, ErrorMessage,
                     CompletedAt, DurationMs)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                batch_id, result.source_name, result.table_name,
                result.repair_type, result.status, result.rows_affected,
                sample_json, result.message, result.error_message,
                completed, result.duration_ms,
            )
            conn.commit()
            cursor.close()
        finally:
            conn.close()
    except Exception:
        logger.warning(
            "R-6: Could not persist repair result for %s.%s/%s — continuing.",
            result.source_name, result.table_name, result.repair_type,
            exc_info=True,
        )
