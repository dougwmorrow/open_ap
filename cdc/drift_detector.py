"""Logging-only Stage↔Bronze drift detection.

Phase 1 of ``docs/cdc_root_cause_blueprint.md``. Detects the symptom that
caused the ``ACCTNBR=205`` incident: a PK with a Bronze active row but no
Stage ``_cdc_is_current=1`` row. **Logs only** — never writes recovery
rows. The data in Stage and Bronze is the source of truth; this module
just makes inconsistencies visible so downstream alerting can act.

Two drift classes are observed and reported separately:

* ``stage_only`` — Stage current row exists but Bronze has no active row
  (or worse, has Flag=2 deleted). Suggests SCD2 missed a propagation.
* ``bronze_only`` — Bronze active exists but Stage has no current row.
  Matches the ``ACCTNBR=205`` symptom; usually a flapping source extraction.

Each detection emits a structured JSON log line (``signal: drift_detected``)
plus a human-readable WARNING with sample PKs. Returns a small dataclass
the caller can use to attach the counts to the next ``PipelineEventLog``
event's ``metadata``.

Usage::

    from cdc.drift_detector import log_stage_bronze_drift
    drift = log_stage_bronze_drift(table_config)
    # drift.bronze_only / drift.stage_only — int counts
    # drift.bronze_only_samples — list of up to 5 PK strings
    # drift.skipped — bool, True if unable to evaluate (table missing, error)

Disabling: set ``CDC_DRIFT_DETECTION=0`` to skip entirely. Default ON.
The check costs one cross-database FULL OUTER JOIN per CDC run, which is
cheap on PK-indexed tables and dominated by the existing CDC anti-joins.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from utils.connections import get_connection, quote_identifier, quote_table

if TYPE_CHECKING:
    from orchestration.table_config import TableConfig


logger = logging.getLogger(__name__)


_SAMPLE_LIMIT = 5
_SIGNAL = "drift_detected"
_DISABLE_ENV = "CDC_DRIFT_DETECTION"


@dataclass
class DriftReport:
    """Per-table drift counts emitted by :func:`log_stage_bronze_drift`."""

    source_name: str
    table_name: str
    skipped: bool = False
    skip_reason: str = ""
    stage_only: int = 0
    bronze_only: int = 0
    stage_only_samples: list[str] = field(default_factory=list)
    bronze_only_samples: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.stage_only + self.bronze_only

    def as_metadata_dict(self) -> dict:
        """Compact representation for ``PipelineEventLog.Metadata``."""
        return {
            "stage_only": self.stage_only,
            "bronze_only": self.bronze_only,
            "stage_only_samples": self.stage_only_samples,
            "bronze_only_samples": self.bronze_only_samples,
        }


def log_stage_bronze_drift(table_config: TableConfig) -> DriftReport:
    """Detect and log Stage↔Bronze drift for one table. Read-only.

    Returns a :class:`DriftReport` regardless of outcome — caller decides
    whether to attach it to a PipelineEvent or just discard.

    Never raises. Any error is captured in ``skip_reason`` and the report
    is marked ``skipped=True``.
    """
    report = DriftReport(
        source_name=table_config.source_name,
        table_name=table_config.source_object_name,
    )

    if os.environ.get(_DISABLE_ENV) == "0":
        report.skipped = True
        report.skip_reason = f"{_DISABLE_ENV}=0"
        return report

    pk_columns = table_config.pk_columns
    if not pk_columns:
        report.skipped = True
        report.skip_reason = "no PK columns configured"
        return report

    stage = table_config.stage_full_table_name
    bronze = table_config.bronze_full_table_name

    try:
        if not _table_exists(stage):
            report.skipped = True
            report.skip_reason = f"Stage table {stage} does not exist"
            return report
        if not _table_exists(bronze):
            report.skipped = True
            report.skip_reason = f"Bronze table {bronze} does not exist"
            return report
    except Exception as exc:
        report.skipped = True
        report.skip_reason = f"existence check failed: {exc}"
        logger.debug("Drift detect skipped for %s.%s: %s",
                     report.source_name, report.table_name, exc)
        return report

    try:
        _populate_report(report, stage, bronze, pk_columns)
    except Exception as exc:
        report.skipped = True
        report.skip_reason = f"query failed: {exc}"
        logger.debug("Drift query failed for %s.%s: %s",
                     report.source_name, report.table_name, exc)
        return report

    _emit_logs(report)
    return report


# ---------------------------------------------------------------------------
# Existence + query helpers
# ---------------------------------------------------------------------------


def _table_exists(full_name: str) -> bool:
    """Lightweight existence check — avoids importing the heavier
    ``extract.udm_connectorx_extractor.table_exists`` dependency chain."""
    db, schema, table = full_name.split(".")
    conn = get_connection(db)
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM INFORMATION_SCHEMA.TABLES "
            "WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?",
            schema, table,
        )
        row = cursor.fetchone()
        cursor.close()
        return row is not None
    finally:
        conn.close()


def _pk_select_for_sample(pk_columns: list[str], alias: str) -> str:
    """``CAST(a.x AS NVARCHAR(50)) + N'|' + CAST(a.y AS NVARCHAR(50))`` —
    composite-PK-friendly string repr for sample logging."""
    parts = [
        f"CAST({alias}.{quote_identifier(c)} AS NVARCHAR(50))"
        for c in pk_columns
    ]
    return " + N'|' + ".join(parts) if len(parts) > 1 else parts[0]


def _populate_report(
    report: DriftReport,
    stage: str,
    bronze: str,
    pk_columns: list[str],
) -> None:
    """Run the cross-database FULL OUTER JOIN and fill counts + samples.

    The query runs against the Stage database; Bronze is reached via
    three-part name. Stage and Bronze must be on the same SQL Server
    instance — true throughout this pipeline.
    """
    db = stage.split(".")[0]
    qs = quote_table(stage)
    qb = quote_table(bronze)

    on_clause = " AND ".join(
        f"s.{quote_identifier(c)} = b.{quote_identifier(c)}"
        for c in pk_columns
    )
    pk_sample_s = _pk_select_for_sample(pk_columns, "s")
    pk_sample_b = _pk_select_for_sample(pk_columns, "b")

    # One-pass: get drift counts AND a small sample for each side.
    sql_counts = f"""
        WITH stage_current AS (
            SELECT {", ".join(quote_identifier(c) for c in pk_columns)}
            FROM {qs}
            WHERE _cdc_is_current = 1
        ),
        bronze_active AS (
            SELECT {", ".join(quote_identifier(c) for c in pk_columns)}
            FROM {qb}
            WHERE UdmActiveFlag = 1
        )
        SELECT
            SUM(CASE WHEN b.{quote_identifier(pk_columns[0])} IS NULL THEN 1 ELSE 0 END) AS stage_only,
            SUM(CASE WHEN s.{quote_identifier(pk_columns[0])} IS NULL THEN 1 ELSE 0 END) AS bronze_only
        FROM stage_current s
        FULL OUTER JOIN bronze_active b ON {on_clause}
        WHERE s.{quote_identifier(pk_columns[0])} IS NULL
           OR b.{quote_identifier(pk_columns[0])} IS NULL
    """

    sql_stage_only_samples = f"""
        SELECT TOP {_SAMPLE_LIMIT} {pk_sample_s} AS pk_str
        FROM {qs} s
        LEFT JOIN {qb} b
          ON {on_clause}
          AND b.UdmActiveFlag = 1
        WHERE s._cdc_is_current = 1
          AND b.{quote_identifier(pk_columns[0])} IS NULL
    """

    sql_bronze_only_samples = f"""
        SELECT TOP {_SAMPLE_LIMIT} {pk_sample_b} AS pk_str
        FROM {qb} b
        LEFT JOIN {qs} s
          ON {on_clause}
          AND s._cdc_is_current = 1
        WHERE b.UdmActiveFlag = 1
          AND s.{quote_identifier(pk_columns[0])} IS NULL
    """

    conn = get_connection(db)
    try:
        cursor = conn.cursor()

        cursor.execute(sql_counts)
        row = cursor.fetchone()
        if row:
            report.stage_only = int(row[0] or 0)
            report.bronze_only = int(row[1] or 0)

        if report.stage_only > 0:
            cursor.execute(sql_stage_only_samples)
            report.stage_only_samples = [str(r[0]) for r in cursor.fetchall()]

        if report.bronze_only > 0:
            cursor.execute(sql_bronze_only_samples)
            report.bronze_only_samples = [str(r[0]) for r in cursor.fetchall()]

        cursor.close()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------


def _emit_logs(report: DriftReport) -> None:
    """Two log lines per detection: a structured JSON line for ingestion,
    and a human-readable WARNING for the operator. INFO-level "all clean"
    when total == 0 so DriftReport runs are visible in PipelineLog history.
    """
    payload = {
        "signal": _SIGNAL,
        "source": report.source_name,
        "table": report.table_name,
        "stage_only": report.stage_only,
        "bronze_only": report.bronze_only,
        "stage_only_samples": report.stage_only_samples,
        "bronze_only_samples": report.bronze_only_samples,
    }
    if report.total == 0:
        logger.info("CDC_DRIFT: %s", json.dumps(payload))
        logger.debug(
            "Stage↔Bronze drift check passed for %s.%s",
            report.source_name, report.table_name,
        )
        return

    logger.warning("CDC_DRIFT: %s", json.dumps(payload))
    if report.bronze_only > 0:
        logger.warning(
            "Stage↔Bronze drift in %s.%s — %d PK(s) have an active Bronze row "
            "but no _cdc_is_current=1 row in Stage. Sample PKs: %s. The next "
            "CDC run will classify these as 'I' (resurrection) and SCD2 hash "
            "comparison should leave Bronze unchanged. Investigate the "
            "extraction if this count grows across runs — likely a flapping "
            "source. See docs/cdc_root_cause_blueprint.md.",
            report.source_name, report.table_name,
            report.bronze_only,
            ", ".join(report.bronze_only_samples) or "(none)",
        )
    if report.stage_only > 0:
        logger.warning(
            "Stage↔Bronze drift in %s.%s — %d PK(s) have a current Stage row "
            "but no active Bronze row. Sample PKs: %s. SCD2 promotion may "
            "have skipped these PKs; investigate the SCD2 run for this table.",
            report.source_name, report.table_name,
            report.stage_only,
            ", ".join(report.stage_only_samples) or "(none)",
        )
