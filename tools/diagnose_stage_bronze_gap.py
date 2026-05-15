"""Diagnostic CLI — identifies PKs in Stage CDC current rows but missing from Bronze SCD2 active rows.

Per CLAUDE.md DIAG-1 + SCD2-P1-c/e + SCD2-R4 invariants. Diagnostic tool for the
"PK in Stage CDC but missing from Bronze SCD2" production bug class.

Bug class characterized
-----------------------

A primary key has ``_cdc_is_current = 1`` in ``UDM_Stage.{SourceName}.{table}_cdc``
but has NO row with ``UdmActiveFlag = 1`` in
``UDM_Bronze.{SourceName}.{table}_scd2_python``.

Note this is **not** the normal source-deletion path (DIAG-1 per CLAUDE.md):
when a PK is deleted from source the CDC engine flips ``_cdc_is_current`` from
1 to 0 and Bronze gets ``UdmActiveFlag = 2``. The PK should NOT end up with
``_cdc_is_current = 1`` in Stage AND no Bronze active row.

What this tool does
-------------------

1. Resolves PK columns for the (source, table) pair from
   ``General.dbo.UdmTablesColumnsList`` (Layer='Stage', IsPrimaryKey=1).
2. Reads the Stage current PK set (``WHERE _cdc_is_current = 1``).
3. Reads the Bronze active PK set (``WHERE UdmActiveFlag = 1``).
4. Computes the set-difference Stage MINUS Bronze using Polars anti-join
   (per CLAUDE.md B-2: do NOT do server-side ``LEFT JOIN ... WHERE NULL`` —
   lock-escalation risk).
5. For each missing PK (up to ``--limit``), runs additional Bronze queries
   to classify the gap state via 5 theories:

   * **T1 IN_FLIGHT_ORPHAN** — mid-INSERT crash; B-4 orphan signature.
   * **T2 DELETED_FROM_SOURCE** — Bronze has Flag=2; Stage current=1 is
     inconsistent — likely CDC source-verifier flap.
   * **T3 NEVER_INSERTED** — no Bronze row at all for the PK; SCD2 silently
     skipped or BCP failed.
   * **T4 ALL_CLOSED** — Bronze rows exist but all Flag=0 (no in-flight, no
     active, no delete); partial SCD2 promotion failure.
   * **T5 RESURRECTED_AS_INACTIVE** — mix of Flag=0 + Flag=2 + no Flag=1;
     resurrection pending.

6. Writes ONE ``CLI_DIAGNOSE_STAGE_BRONZE_GAP`` audit row to
   ``General.ops.PipelineEventLog`` per D76 (one row per CLI invocation).
7. Renders summary + per-PK recommendation to stdout.

READ-ONLY contract
------------------

This tool issues **NO writes** to Stage / Bronze / source. The only write is
the single audit row into ``PipelineEventLog`` in General. There is no
``--dry-run`` flag because the tool has nothing to dry-run.

CLI contract
------------

::

    python -m tools.diagnose_stage_bronze_gap --source DNA --table ACCT
    python -m tools.diagnose_stage_bronze_gap --source DNA --table ACCT --limit 100
    python -m tools.diagnose_stage_bronze_gap --source DNA --table ACCT --json-output
    python -m tools.diagnose_stage_bronze_gap --source DNA --table ACCT \\
        --output-file /tmp/dna_acct_gap.txt

Exit codes (per D74)
~~~~~~~~~~~~~~~~~~~~

* **0** — no gap found (Stage current == Bronze active in PK space); HEALTHY.
* **1** — gap detected; operator must investigate using the per-PK
  recommendations printed.
* **2** — fatal config error: PK columns unresolvable from
  UdmTablesColumnsList, table doesn't exist, ``--source``/``--table``
  missing or invalid.

Audit row (per D76)
~~~~~~~~~~~~~~~~~~~

* ``EventType = 'CLI_DIAGNOSE_STAGE_BRONZE_GAP'`` — NEW CLI_* family value.
* ONE row per invocation; ``Metadata`` JSON carries
  ``{event_kind, actor, source_name, table_name, stage_current_count,
  bronze_active_count, gap_count, theories_breakdown, exit_code,
  started_at, completed_at, duration_ms}``.

Canonical references cited
--------------------------

* CLAUDE.md DIAG-1 — CDC source-delete behavior (Stage flips
  ``_cdc_is_current`` to 0; no delete-marker row inserted).
* CLAUDE.md SCD2-P1-c — Active rows carry ``UdmSourceEndDate = '2999-12-31'``;
  NULL = in-flight marker.
* CLAUDE.md SCD2-P1-e — In-flight orphan predicate requires BOTH
  ``UdmEndDateTime IS NULL`` AND ``UdmSourceEndDate IS NULL`` (plus
  ``UdmActiveFlag = 0 AND UdmScd2Operation IN ('U','R')``).
* CLAUDE.md SCD2-R4 — UdmActiveFlag tri-valued: 1=active, 2=deleted, 0=closed
  OR in-flight orphan.
* CLAUDE.md B-2 — Server-side LEFT JOIN ... NULL can lock-escalate; do
  set-diff client-side with Polars anti-join.
* CLAUDE.md SCD2-P1-f / CDC-NOW-MS — naive ms-precision UTC for any
  datetime values.

D-numbers consumed
------------------

* D67 — Tier 0 smoke discipline.
* D68 — canonical exception hierarchy (utils.errors single source).
* D74 — CLI exit-code contract (0 / 1 / 2).
* D75 — argument naming.
* D76 — CLI audit-row contract (CLI_* family).
* D92 — forward-only additive (new tool).
* D103 — security model (read-only against Stage/Bronze; no PII surfaced).

See also
--------

* ``tools/inspect_cdc_pk.py`` — single-PK CDC diagnostic (recommended
  follow-up when gap classification surfaces NEVER_INSERTED).
* ``tools/repair_scd2.py`` — in-flight orphan reaping (recommended
  follow-up when gap classification surfaces IN_FLIGHT_ORPHAN).
* ``tools/validate_cdc.py`` — table-wide Stage↔Bronze structural validator
  (sibling diagnostic; this tool drills into the specific gap class).
* ``tools/validate_scd2.py`` — Bronze SCD2 chain integrity validator.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# Project root on sys.path so we can reach data_load + utils.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# Canonical exception hierarchy per D68 + B228 (utils.errors single source
# of truth; tools import from utils.errors directly).
try:
    from utils.errors import (  # noqa: E402
        PipelineFatalError,
        PipelineRetryableError,
    )
except (ImportError, ModuleNotFoundError):
    # Defensive fallback for test environments where utils.errors is
    # mocked as MagicMock — re-import from the filesystem directly.
    import importlib.util as _importlib_util  # noqa: E402

    _err_path = Path(__file__).resolve().parent.parent / "utils" / "errors.py"
    _spec = _importlib_util.spec_from_file_location(
        "utils._errors_diagnose_stage_bronze_gap", _err_path
    )
    _err_mod = _importlib_util.module_from_spec(_spec)
    _spec.loader.exec_module(_err_mod)
    PipelineFatalError = _err_mod.PipelineFatalError
    PipelineRetryableError = _err_mod.PipelineRetryableError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Exit-code constants (per D74)
# ---------------------------------------------------------------------------

EXIT_SUCCESS = 0       # No gap found — healthy
EXIT_OPERATIONAL = 1   # Gap found — operator must investigate
EXIT_FATAL = 2         # Config error / unresolvable PK / table absent


# D76 EventType — NEW CLI_* family value (registered in CLAUDE.md
# `EventType families registered per Round 4 D76 + Round 6 § 6.4`).
EVENT_TYPE = "CLI_DIAGNOSE_STAGE_BRONZE_GAP"


# Theory classification constants (per CLAUDE.md SCD2-P1-c/e + SCD2-R4 + DIAG-1).
THEORY_T1_IN_FLIGHT_ORPHAN = "IN_FLIGHT_ORPHAN"
THEORY_T2_DELETED_FROM_SOURCE = "DELETED_FROM_SOURCE"
THEORY_T3_NEVER_INSERTED = "NEVER_INSERTED"
THEORY_T4_ALL_CLOSED = "ALL_CLOSED"
THEORY_T5_RESURRECTED_AS_INACTIVE = "RESURRECTED_AS_INACTIVE"
THEORY_UNKNOWN = "UNKNOWN"


# Theory metadata: (theory_id, short_explanation, recommendation)
_THEORY_DESCRIPTIONS = {
    THEORY_T1_IN_FLIGHT_ORPHAN: (
        "Mid-INSERT crash; B-4 orphan signature (Flag=0, Op IN U/R, "
        "both EndDates NULL). Next SCD2 run will auto-clean via "
        "_cleanup_orphaned_inactive_rows."
    ),
    THEORY_T2_DELETED_FROM_SOURCE: (
        "Hard-delete already captured (Flag=2). Stage _cdc_is_current=1 "
        "is INCONSISTENT with Bronze delete state — likely a CDC "
        "source-verifier flap (see cdc/source_verifier.py)."
    ),
    THEORY_T3_NEVER_INSERTED: (
        "No Bronze row at all for this PK. SCD2 promotion silently "
        "skipped this row. Causes: (a) NULL PK filtered downstream, "
        "(b) hash collision against existing closed row, (c) BCP load "
        "failed for this batch, (d) type mismatch in PK column between "
        "Stage and Bronze."
    ),
    THEORY_T4_ALL_CLOSED: (
        "All Bronze versions are closed (Flag=0); newest version did "
        "not activate. Likely a partial SCD2 promotion failure between "
        "INSERT and _activate_new_versions()."
    ),
    THEORY_T5_RESURRECTED_AS_INACTIVE: (
        "PK was deleted (Flag=2) then re-appeared in source (CDC "
        "inserted new row at Stage) but SCD2 has not promoted the "
        "resurrection yet. Check UdmScd2Operation='R' insert; may be "
        "in-flight per T1."
    ),
    THEORY_UNKNOWN: (
        "Pattern does not match any documented case. Inspect Bronze "
        "row dump manually via tools/inspect_cdc_pk.py."
    ),
}


_RECOMMENDATIONS = {
    THEORY_T1_IN_FLIGHT_ORPHAN: (
        "tools/repair_scd2.py --source {source} --table {table} --apply"
    ),
    THEORY_T2_DELETED_FROM_SOURCE: (
        "Inspect CDC source-verifier audit for flap (cdc/source_verifier.py); "
        "tools/inspect_cdc_pk.py --source {source} --table {table} "
        "--pk-values {pk_values}"
    ),
    THEORY_T3_NEVER_INSERTED: (
        "tools/inspect_cdc_pk.py --source {source} --table {table} "
        "--pk-values {pk_values}"
    ),
    THEORY_T4_ALL_CLOSED: (
        "Re-run the pipeline for this table; investigate "
        "PipelineEventLog/PipelineLog around the last SCD2_PROMOTION "
        "for this BatchId. tools/inspect_cdc_pk.py --source {source} "
        "--table {table} --pk-values {pk_values}"
    ),
    THEORY_T5_RESURRECTED_AS_INACTIVE: (
        "tools/inspect_cdc_pk.py --source {source} --table {table} "
        "--pk-values {pk_values}; if in-flight, also tools/repair_scd2.py"
    ),
    THEORY_UNKNOWN: (
        "tools/inspect_cdc_pk.py --source {source} --table {table} "
        "--pk-values {pk_values}"
    ),
}


# ---------------------------------------------------------------------------
# Actor detection (per § 1.7 invocation pattern heuristic)
# ---------------------------------------------------------------------------


def _detect_actor() -> str:
    """Resolve ``--actor`` default per spec § 1.7 invocation-pattern heuristic.

    1. AUTOMIC_RUN_ID env var present -> 'automic'
    2. sys.stdin.isatty() -> 'operator' (canonical operator-driven case)
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
# Lazy private resolvers for sibling-module imports (B214 pattern)
# ---------------------------------------------------------------------------


def _get_polars():
    """Resolve Polars at call time so tests can patch sys.modules['polars']."""
    try:
        import polars as pl  # type: ignore
        return pl
    except (ImportError, ModuleNotFoundError) as exc:
        raise PipelineFatalError(
            f"polars unavailable: {exc}",
            metadata={"step": "resolve_polars"},
        ) from exc


def _get_table_config_loader():
    """Resolve TableConfigLoader at call time."""
    from orchestration.table_config import TableConfigLoader  # type: ignore

    return TableConfigLoader


def _resolve_default_cursor_factory(database: str = "General") -> Callable:
    """Return a callable that opens a connection to the given database.

    Resolves at CALL TIME so tests patching ``sys.modules['pyodbc']``
    after tool import are honored. Production path uses
    ``utils.connections.get_connection(database)``.
    """

    def _open():
        try:
            from utils.connections import get_connection  # type: ignore

            return get_connection(database)
        except Exception:  # noqa: BLE001
            pass
        pyodbc_mod = sys.modules.get("pyodbc")
        if pyodbc_mod is None:
            try:
                import pyodbc as pyodbc_mod  # type: ignore  # noqa: F401
            except Exception as exc:  # noqa: BLE001
                raise PipelineFatalError(
                    f"pyodbc / utils.connections both unavailable: {exc}",
                    metadata={
                        "step": "resolve_default_cursor_factory",
                        "database": database,
                    },
                ) from exc
        return pyodbc_mod.connect("DRIVER={ODBC Driver 18 for SQL Server};")

    return _open


# ---------------------------------------------------------------------------
# Identifier quoting (defensive — same semantics as utils.connections.quote_*)
# ---------------------------------------------------------------------------


def _quote_identifier(name: str) -> str:
    """Bracket-escape a SQL Server identifier; double any embedded ']'."""
    if not name:
        raise PipelineFatalError(
            "Identifier cannot be empty",
            metadata={"step": "_quote_identifier"},
        )
    return f"[{name.replace(']', ']]')}]"


def _quote_three_part(db: str, schema: str, table: str) -> str:
    return f"{_quote_identifier(db)}.{_quote_identifier(schema)}.{_quote_identifier(table)}"


# ---------------------------------------------------------------------------
# PK column resolution (UdmTablesColumnsList Layer='Stage', IsPrimaryKey=1)
# ---------------------------------------------------------------------------


def _resolve_pk_columns_via_loader(
    *,
    source_name: str,
    table_name: str,
    table_config_loader: Callable,
) -> tuple[list[str], Any]:
    """Resolve PK columns and TableConfig via TableConfigLoader.

    Returns (pk_columns, table_config). Raises :class:`PipelineFatalError` if
    no matching row is found OR no PK columns are configured.
    """
    loader = table_config_loader()
    configs = []
    try:
        small = loader.load_small_tables(
            source_name=source_name, table_name=table_name
        )
        configs.extend(small)
    except Exception as exc:  # noqa: BLE001
        logger.warning("load_small_tables failed: %s", exc)

    try:
        large = loader.load_large_tables(
            source_name=source_name, table_name=table_name
        )
        configs.extend(large)
    except Exception as exc:  # noqa: BLE001
        logger.warning("load_large_tables failed: %s", exc)

    if not configs:
        raise PipelineFatalError(
            f"No row in UdmTablesList for source={source_name!r}, "
            f"table={table_name!r}.",
            metadata={"source_name": source_name, "table_name": table_name},
        )
    cfg = configs[0]
    pk_columns = cfg.pk_columns
    if not pk_columns:
        raise PipelineFatalError(
            f"No PK columns configured for {source_name}.{table_name} "
            f"in UdmTablesColumnsList (Layer='Stage', IsPrimaryKey=1). "
            f"Run column-sync first.",
            metadata={
                "source_name": source_name,
                "table_name": table_name,
                "configs_found": len(configs),
            },
        )
    return pk_columns, cfg


# ---------------------------------------------------------------------------
# Table-name resolution honoring StripSuffix + override
# ---------------------------------------------------------------------------


def _resolve_stage_table_name(table_config) -> str:
    """Resolve the effective Stage table name (no DB / schema prefix).

    Honors ``table_config.stage_table_name`` override and ``strip_suffix``.
    """
    base = (
        getattr(table_config, "stage_table_name", None)
        or table_config.source_object_name
    )
    suffix = "" if getattr(table_config, "strip_suffix", False) else "_cdc"
    return f"{base}{suffix}"


def _resolve_bronze_table_name(table_config) -> str:
    """Resolve the effective Bronze table name (no DB / schema prefix).

    Honors ``table_config.bronze_table_name`` override and ``strip_suffix``.
    """
    base = (
        getattr(table_config, "bronze_table_name", None)
        or table_config.source_object_name
    )
    suffix = "" if getattr(table_config, "strip_suffix", False) else "_scd2_python"
    return f"{base}{suffix}"


def _resolve_stage_schema(table_config) -> str:
    return (
        getattr(table_config, "_resolved_stage_schema", None)
        or table_config.source_name
    )


def _resolve_bronze_schema(table_config) -> str:
    return (
        getattr(table_config, "_resolved_bronze_schema", None)
        or table_config.source_name
    )


# ---------------------------------------------------------------------------
# Stage / Bronze PK-set fetch (NO server-side join — pull both sides as PK
# tuples then do anti-join in Polars per CLAUDE.md B-2)
# ---------------------------------------------------------------------------


def _fetch_pk_set(
    *,
    cursor_factory: Callable,
    qualified_table: str,
    pk_columns: list[str],
    where_clause: str,
    pl_module,
) -> Any:
    """Read distinct PK tuples from a (cursor_factory, table) into a Polars df.

    The query is shaped as::

        SELECT pk_col_1, pk_col_2, ... FROM <qualified_table>
        WHERE <where_clause>

    Returns a Polars DataFrame with the PK columns. Empty DataFrame on no
    rows. Caller wraps exceptions; all SQL exceptions bubble up as
    :class:`PipelineRetryableError` from outer scope (operator can re-run).
    """
    pk_select = ", ".join(_quote_identifier(c) for c in pk_columns)
    sql = f"SELECT {pk_select} FROM {qualified_table} WHERE {where_clause}"
    conn = cursor_factory()
    try:
        try:
            conn.autocommit = True
        except Exception:  # noqa: BLE001
            pass
        cursor = conn.cursor()
        try:
            cursor.execute(sql)
            rows = cursor.fetchall()
            # Build Polars DataFrame manually — preserves PK column types
            # as Object so any underlying type (int / str / date) round
            # trips through anti-join.
            if not rows:
                # Empty df with the right schema (Utf8 placeholder; anti-join
                # works on any matching dtype as long as both sides agree).
                empty_data = {col: [] for col in pk_columns}
                return pl_module.DataFrame(empty_data)
            data = {
                col: [r[i] for r in rows]
                for i, col in enumerate(pk_columns)
            }
            return pl_module.DataFrame(data)
        finally:
            try:
                cursor.close()
            except Exception:  # noqa: BLE001
                pass
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Per-PK Bronze characterization (5 theories)
# ---------------------------------------------------------------------------


def _characterize_missing_pk(
    *,
    cursor_factory: Callable,
    bronze_qualified: str,
    pk_columns: list[str],
    pk_values: list[Any],
) -> dict:
    """Run Bronze queries to classify the gap state for ONE missing PK.

    Returns a dict with::

        {
            "pk_values": {col: val, ...},
            "theory": THEORY_*,
            "explanation": "<short text>",
            "recommendation": "<actionable command>",
            "bronze_evidence": {
                "scd2_key": int | None,
                "udm_active_flag": int | None,
                "udm_scd2_operation": str | None,
                "udm_end_datetime": str | None,
                "udm_source_end_date": str | None,
                "udm_effective_datetime": str | None,
                "row_count": int,
                "flag_breakdown": {0: N0, 1: N1, 2: N2},
            },
        }

    The queries are READ-ONLY against Bronze. One round trip per missing PK
    (a single SELECT returning at most a few rows per PK — Bronze PK is
    versioned so we expect ≤ N rows where N is the version history depth).
    """
    pk_dict = dict(zip(pk_columns, pk_values))
    pk_clause = " AND ".join(
        f"{_quote_identifier(c)} = ?" for c in pk_columns
    )
    sql = (
        f"SELECT [_scd2_key], [UdmActiveFlag], [UdmScd2Operation], "
        f"[UdmEffectiveDateTime], [UdmEndDateTime], [UdmSourceEndDate] "
        f"FROM {bronze_qualified} "
        f"WHERE {pk_clause}"
    )

    conn = cursor_factory()
    try:
        try:
            conn.autocommit = True
        except Exception:  # noqa: BLE001
            pass
        cursor = conn.cursor()
        try:
            cursor.execute(sql, *pk_values)
            rows = cursor.fetchall()
        finally:
            try:
                cursor.close()
            except Exception:  # noqa: BLE001
                pass
    finally:
        try:
            conn.close()
        except Exception:  # noqa: BLE001
            pass

    flag_breakdown = {0: 0, 1: 0, 2: 0}
    inflight_row = None
    flag2_row = None
    any_flag0 = None
    flag1_present = False

    for row in rows:
        flag = int(row[1]) if row[1] is not None else None
        if flag in flag_breakdown:
            flag_breakdown[flag] += 1
        if flag == 1:
            flag1_present = True
        op = row[2]
        end_dt = row[4]
        src_end = row[5]
        if (
            flag == 0
            and op in ("U", "R")
            and end_dt is None
            and src_end is None
            and inflight_row is None
        ):
            inflight_row = row
        if flag == 2 and flag2_row is None:
            flag2_row = row
        if flag == 0 and any_flag0 is None:
            any_flag0 = row

    # Pick the most informative evidence row (priority: in-flight > Flag=2 >
    # first Flag=0 > first row if no rows yet)
    evidence_row = inflight_row or flag2_row or any_flag0 or (rows[0] if rows else None)

    # Classify per the 5-theory table
    theory: str
    if not rows:
        # T3 — no Bronze row at all for this PK
        theory = THEORY_T3_NEVER_INSERTED
    elif inflight_row is not None:
        # T1 — in-flight orphan signature (B-4 per CLAUDE.md SCD2-P1-e)
        theory = THEORY_T1_IN_FLIGHT_ORPHAN
    elif flag_breakdown[2] >= 1 and flag_breakdown[0] >= 1 and not flag1_present:
        # T5 — mix of closed + deleted; resurrection pending
        theory = THEORY_T5_RESURRECTED_AS_INACTIVE
    elif flag_breakdown[2] >= 1 and not flag1_present and flag_breakdown[0] == 0:
        # T2 — only Flag=2 (delete already captured), no Flag=0 history
        theory = THEORY_T2_DELETED_FROM_SOURCE
    elif flag_breakdown[2] >= 1 and not flag1_present:
        # T2 — Flag=2 present + no Flag=1 (covers mixed cases not caught
        # by T5 — e.g. Flag=2 + Flag=0 + Flag=2 history)
        theory = THEORY_T2_DELETED_FROM_SOURCE
    elif (
        flag_breakdown[0] >= 1
        and flag_breakdown[1] == 0
        and flag_breakdown[2] == 0
    ):
        # T4 — all Flag=0, no active, no delete; partial activation failure
        theory = THEORY_T4_ALL_CLOSED
    else:
        theory = THEORY_UNKNOWN

    bronze_evidence: dict[str, Any] = {
        "row_count": len(rows),
        "flag_breakdown": flag_breakdown,
        "scd2_key": int(evidence_row[0]) if evidence_row else None,
        "udm_active_flag": (
            int(evidence_row[1]) if evidence_row and evidence_row[1] is not None
            else None
        ),
        "udm_scd2_operation": evidence_row[2] if evidence_row else None,
        "udm_effective_datetime": (
            evidence_row[3].isoformat() if evidence_row and evidence_row[3]
            is not None and hasattr(evidence_row[3], "isoformat")
            else (str(evidence_row[3]) if evidence_row and evidence_row[3] is not None else None)
        ),
        "udm_end_datetime": (
            evidence_row[4].isoformat() if evidence_row and evidence_row[4]
            is not None and hasattr(evidence_row[4], "isoformat")
            else (str(evidence_row[4]) if evidence_row and evidence_row[4] is not None else None)
        ),
        "udm_source_end_date": (
            evidence_row[5].isoformat() if evidence_row and evidence_row[5]
            is not None and hasattr(evidence_row[5], "isoformat")
            else (str(evidence_row[5]) if evidence_row and evidence_row[5] is not None else None)
        ),
    }

    pk_string_for_cli = ",".join(
        str(v) if v is not None else "" for v in pk_values
    )
    recommendation = _RECOMMENDATIONS[theory].format(
        source="{source}",   # caller fills in via format on output rendering
        table="{table}",
        pk_values=pk_string_for_cli,
    )

    return {
        "pk_values": pk_dict,
        "theory": theory,
        "explanation": _THEORY_DESCRIPTIONS[theory],
        "recommendation": recommendation,
        "bronze_evidence": bronze_evidence,
    }


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
    """INSERT one ``CLI_DIAGNOSE_STAGE_BRONZE_GAP`` row into PipelineEventLog.

    Per D76. ONE row per CLI invocation. Best-effort — failures are
    logged but do not affect the verdict exit code (parity with sibling
    Round 4 tools).

    Returns the SCOPE_IDENTITY() of the inserted row so JSON
    ``audit_event_id`` key can be populated. Returns None on failure.

    When ``skip=True`` (test path; main()'s ``no_audit_event``), returns
    None immediately without writing.
    """
    if skip:
        return None

    metadata_json = json.dumps(metadata, separators=(",", ":"), default=str)
    event_detail = (
        f"diagnose_stage_bronze_gap / "
        f"source={metadata.get('source_name')} / "
        f"table={metadata.get('table_name')} / "
        f"gap_count={metadata.get('gap_count', 0)}"
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
        logger.exception(
            "Failed to write %s audit row", EVENT_TYPE
        )
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


def _format_pk_dict(pk_dict: dict) -> str:
    """Format a PK dict for stdout display: ``{k1=v1, k2=v2}``."""
    parts = [f"{k}={'NULL' if v is None else v}" for k, v in pk_dict.items()]
    return "{" + ", ".join(parts) + "}"


def _render_human_summary(result: dict) -> str:
    """Build the human-readable stdout block per spec.

    Returns a single multi-line string ready for print() / file write.
    """
    lines: list[str] = []
    lines.append("=" * 60)
    lines.append("Stage->Bronze Gap Diagnostic")
    lines.append("=" * 60)
    lines.append(f"Source: {result['source_name']}")
    lines.append(f"Table:  {result['table_name']}")
    lines.append(f"PK columns: {', '.join(result['pk_columns'])}")
    lines.append(
        f"Stage current rows (cdc_is_current=1): {result['stage_current_count']:,}"
    )
    lines.append(
        f"Bronze active rows (Flag=1):           {result['bronze_active_count']:,}"
    )
    lines.append("---")
    gap_count = result["gap_count"]
    if gap_count == 0:
        lines.append("GAP: 0 PKs — HEALTHY")
        lines.append("")
        lines.append("No follow-up action required.")
    else:
        lines.append(
            f"GAP: {gap_count:,} PKs in Stage but NOT in Bronze "
            f"(showing up to {result['limit']:,})"
        )
        lines.append("")
        for diag in result.get("diagnoses", []):
            pk_disp = _format_pk_dict(diag["pk_values"])
            theory = diag["theory"]
            recommendation = (
                diag["recommendation"]
                .replace("{source}", result["source_name"])
                .replace("{table}", result["table_name"])
            )
            lines.append(f"  PK={pk_disp} -> {theory}")
            bronze_ev = diag["bronze_evidence"]
            evidence_bits: list[str] = []
            if bronze_ev.get("scd2_key") is not None:
                evidence_bits.append(f"_scd2_key={bronze_ev['scd2_key']}")
            if bronze_ev.get("udm_active_flag") is not None:
                evidence_bits.append(f"Flag={bronze_ev['udm_active_flag']}")
            if bronze_ev.get("udm_scd2_operation"):
                evidence_bits.append(f"Op={bronze_ev['udm_scd2_operation']}")
            if bronze_ev.get("row_count") is not None:
                evidence_bits.append(f"bronze_rows={bronze_ev['row_count']}")
            if bronze_ev.get("flag_breakdown"):
                fb = bronze_ev["flag_breakdown"]
                evidence_bits.append(
                    f"flags=[0:{fb.get(0, 0)}, 1:{fb.get(1, 0)}, "
                    f"2:{fb.get(2, 0)}]"
                )
            if evidence_bits:
                lines.append("     " + " ".join(evidence_bits))
            lines.append(f"     Recommend: {recommendation}")
            lines.append("")
        # Summary by theory
        lines.append("Summary by theory:")
        breakdown = result.get("theories_breakdown", {})
        total = sum(breakdown.values()) if breakdown else 0
        if total > 0:
            for theory, count in sorted(
                breakdown.items(), key=lambda kv: -kv[1]
            ):
                pct = (count * 100.0 / total) if total else 0.0
                lines.append(
                    f"  {theory:30s}: {count:6d} ({pct:5.1f}%)"
                )
    audit_id = result.get("audit_event_id")
    if audit_id is not None:
        lines.append("")
        lines.append(f"audit event {audit_id}")
    return "\n".join(lines)


def _render_json_payload(result: dict) -> str:
    """Build the JSON output payload."""
    diagnoses_with_filled_recs = []
    for d in result.get("diagnoses", []):
        copy = dict(d)
        copy["recommendation"] = (
            d["recommendation"]
            .replace("{source}", result["source_name"])
            .replace("{table}", result["table_name"])
        )
        diagnoses_with_filled_recs.append(copy)
    payload = {
        "source_name": result["source_name"],
        "table_name": result["table_name"],
        "pk_columns": result["pk_columns"],
        "stage_current_count": result["stage_current_count"],
        "bronze_active_count": result["bronze_active_count"],
        "gap_count": result["gap_count"],
        "limit": result["limit"],
        "theories_breakdown": result.get("theories_breakdown", {}),
        "diagnoses": diagnoses_with_filled_recs,
        "audit_event_id": result.get("audit_event_id"),
        "exit_code": result.get("exit_code"),
    }
    return json.dumps(payload, indent=2, sort_keys=True, default=str)


# ---------------------------------------------------------------------------
# Top-level main() — programmatic entry
# ---------------------------------------------------------------------------


def main(
    *,
    source: str | None = None,
    table: str | None = None,
    limit: int = 100,
    include_state: bool = False,
    json_output: bool = False,
    output_file: str | Path | None = None,
    actor: str | None = None,
    no_audit_event: bool = False,
    verbose: bool = False,
    quiet: bool = False,
    # ---- Injection hooks (test path) ----
    cursor_factory: Callable | None = None,
    table_config_loader: Callable | None = None,
    audit_cursor_factory: Callable | None = None,
    general_db: str = "General",
    stage_db: str = "UDM_Stage",
    bronze_db: str = "UDM_Bronze",
) -> dict:
    """Programmatic entry — diagnose Stage->Bronze PK-set gap.

    Returns a result dict matching the D76 audit-row Metadata shape::

        {
            "event_kind": "diagnose_stage_bronze_gap",
            "actor": "<operator>",
            "source_name": "<DNA>",
            "table_name": "<ACCT>",
            "pk_columns": ["AcctNumber"],
            "stage_current_count": <int>,
            "bronze_active_count": <int>,
            "gap_count": <int>,
            "limit": <int>,
            "theories_breakdown": {THEORY_*: count, ...},
            "diagnoses": [{...per-PK...}, ...],
            "exit_code": <0 | 1 | 2>,
            "status": "SUCCESS|FAILED",
            "started_at": "<ISO-8601 naive-UTC>",
            "completed_at": "<ISO-8601 naive-UTC>",
            "duration_ms": <int>,
            "audit_event_id": <int | None>,
            "errors": [...],
            "error_message": "<text>" | None,
        }

    Parameters
    ----------
    source / table:
        Required pair identifying the (SourceName, SourceObjectName) row in
        ``General.dbo.UdmTablesList``.
    limit:
        Cap on per-PK characterization queries. Default 100. The total gap
        count is reported regardless; only the first ``limit`` PKs receive
        per-PK theory classification.
    include_state:
        Reserved for future per-state evidence dump. Currently informational
        — the standard output already carries Bronze evidence per missing PK.
    json_output:
        Emit JSON instead of human summary.
    output_file:
        Write the rendered output to this path instead of stdout. Stderr-side
        messages (FATAL, WARNING) are still emitted to stderr.
    actor:
        Operator identity. Auto-detected via ``_detect_actor()`` when None.
    no_audit_event:
        Skip the PipelineEventLog audit-row INSERT (pipeline-programmatic
        callers; tests).
    cursor_factory:
        Connection factory for Stage + Bronze reads. Defaults to live
        ``utils.connections.get_connection`` resolution at call time.
    table_config_loader:
        Defaults to ``orchestration.table_config.TableConfigLoader``.
    audit_cursor_factory:
        Defaults to ``cursor_factory`` (audit row INSERTs go to General;
        if cursor_factory is parameterized for Stage, callers should pass
        audit_cursor_factory explicitly).
    general_db / stage_db / bronze_db:
        Target database names (default 'General' / 'UDM_Stage' / 'UDM_Bronze').
    """
    started_at = datetime.now(timezone.utc).replace(tzinfo=None)
    started_at_iso = started_at.strftime("%Y-%m-%dT%H:%M:%SZ")
    started_monotonic = datetime.now()

    if verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    elif quiet:
        logging.getLogger().setLevel(logging.ERROR)

    if actor is None:
        actor = _detect_actor()

    # Validate required args
    if not isinstance(source, str) or not source.strip():
        return _build_fatal_result(
            error_type="MissingSource",
            error_message=(
                "--source is required (SourceName from UdmTablesList, "
                "e.g. DNA / CCM / EPICOR)."
            ),
            source=source,
            table=table,
            actor=actor,
            started_at=started_at,
            started_at_iso=started_at_iso,
            started_monotonic=started_monotonic,
            quiet=quiet,
            audit_cursor_factory=audit_cursor_factory,
            general_db=general_db,
            no_audit_event=no_audit_event,
        )
    if not isinstance(table, str) or not table.strip():
        return _build_fatal_result(
            error_type="MissingTable",
            error_message=(
                "--table is required (SourceObjectName from UdmTablesList, "
                "e.g. ACCT)."
            ),
            source=source,
            table=table,
            actor=actor,
            started_at=started_at,
            started_at_iso=started_at_iso,
            started_monotonic=started_monotonic,
            quiet=quiet,
            audit_cursor_factory=audit_cursor_factory,
            general_db=general_db,
            no_audit_event=no_audit_event,
        )
    if not isinstance(limit, int) or limit < 1:
        return _build_fatal_result(
            error_type="InvalidLimit",
            error_message=(
                f"--limit must be a positive integer; got {limit!r}."
            ),
            source=source,
            table=table,
            actor=actor,
            started_at=started_at,
            started_at_iso=started_at_iso,
            started_monotonic=started_monotonic,
            quiet=quiet,
            audit_cursor_factory=audit_cursor_factory,
            general_db=general_db,
            no_audit_event=no_audit_event,
        )

    # Pre-populate result so error returns carry consistent shape.
    result: dict[str, Any] = {
        "event_kind": "diagnose_stage_bronze_gap",
        "actor": actor,
        "source_name": source,
        "table_name": table,
        "pk_columns": [],
        "stage_current_count": 0,
        "bronze_active_count": 0,
        "gap_count": 0,
        "limit": limit,
        "include_state": bool(include_state),
        "theories_breakdown": {},
        "diagnoses": [],
        "exit_code": EXIT_SUCCESS,
        "status": "SUCCESS",
        "started_at": started_at_iso,
        "started_at_dt": started_at,
        "completed_at": None,
        "duration_ms": 0,
        "audit_event_id": None,
        "errors": [],
        "error_message": None,
    }

    # ---- Resolve table_config_loader + PK columns ----
    if table_config_loader is None:
        try:
            table_config_loader = _get_table_config_loader()
        except Exception as exc:  # noqa: BLE001
            result["exit_code"] = EXIT_FATAL
            result["status"] = "FAILED"
            result["error_message"] = (
                f"orchestration.table_config.TableConfigLoader unimportable: "
                f"{exc}"
            )
            result["errors"].append(result["error_message"])
            return _finalize_and_emit(
                result,
                quiet=quiet,
                json_output=json_output,
                output_file=output_file,
                audit_cursor_factory=audit_cursor_factory,
                general_db=general_db,
                no_audit_event=no_audit_event,
                started_monotonic=started_monotonic,
            )

    try:
        pk_columns, table_config = _resolve_pk_columns_via_loader(
            source_name=source,
            table_name=table,
            table_config_loader=table_config_loader,
        )
    except PipelineFatalError as exc:
        result["exit_code"] = EXIT_FATAL
        result["status"] = "FAILED"
        result["error_message"] = str(exc)
        result["errors"].append(f"PipelineFatalError: {exc}")
        if not quiet:
            print(f"FATAL: {exc}", file=sys.stderr)
        return _finalize_and_emit(
            result,
            quiet=quiet,
            json_output=json_output,
            output_file=output_file,
            audit_cursor_factory=audit_cursor_factory,
            general_db=general_db,
            no_audit_event=no_audit_event,
            started_monotonic=started_monotonic,
        )
    except Exception as exc:  # noqa: BLE001
        result["exit_code"] = EXIT_FATAL
        result["status"] = "FAILED"
        result["error_message"] = (
            f"PK resolution unexpected exception: {type(exc).__name__}: {exc}"
        )
        result["errors"].append(result["error_message"])
        if not quiet:
            print(f"FATAL: {result['error_message']}", file=sys.stderr)
        return _finalize_and_emit(
            result,
            quiet=quiet,
            json_output=json_output,
            output_file=output_file,
            audit_cursor_factory=audit_cursor_factory,
            general_db=general_db,
            no_audit_event=no_audit_event,
            started_monotonic=started_monotonic,
        )

    result["pk_columns"] = list(pk_columns)

    # ---- Resolve qualified table names ----
    stage_table_name = _resolve_stage_table_name(table_config)
    bronze_table_name = _resolve_bronze_table_name(table_config)
    stage_schema = _resolve_stage_schema(table_config)
    bronze_schema = _resolve_bronze_schema(table_config)
    stage_qualified = _quote_three_part(stage_db, stage_schema, stage_table_name)
    bronze_qualified = _quote_three_part(bronze_db, bronze_schema, bronze_table_name)
    result["stage_qualified"] = stage_qualified
    result["bronze_qualified"] = bronze_qualified

    # ---- Resolve cursor factories ----
    stage_cursor_factory = cursor_factory
    bronze_cursor_factory = cursor_factory
    if stage_cursor_factory is None:
        stage_cursor_factory = _resolve_default_cursor_factory(stage_db)
    if bronze_cursor_factory is None:
        bronze_cursor_factory = _resolve_default_cursor_factory(bronze_db)
    # Audit cursor factory defaults to General-DB connection
    if audit_cursor_factory is None and cursor_factory is None:
        audit_cursor_factory = _resolve_default_cursor_factory(general_db)
    elif audit_cursor_factory is None:
        # Caller passed `cursor_factory` for both Stage + Bronze; reuse it
        # for audit too (test path typically).
        audit_cursor_factory = cursor_factory

    # ---- Resolve Polars ----
    try:
        pl_module = _get_polars()
    except PipelineFatalError as exc:
        result["exit_code"] = EXIT_FATAL
        result["status"] = "FAILED"
        result["error_message"] = str(exc)
        result["errors"].append(f"PipelineFatalError: {exc}")
        if not quiet:
            print(f"FATAL: {exc}", file=sys.stderr)
        return _finalize_and_emit(
            result,
            quiet=quiet,
            json_output=json_output,
            output_file=output_file,
            audit_cursor_factory=audit_cursor_factory,
            general_db=general_db,
            no_audit_event=no_audit_event,
            started_monotonic=started_monotonic,
        )

    # ---- Fetch Stage current PK set ----
    try:
        stage_df = _fetch_pk_set(
            cursor_factory=stage_cursor_factory,
            qualified_table=stage_qualified,
            pk_columns=pk_columns,
            where_clause="[_cdc_is_current] = 1",
            pl_module=pl_module,
        )
    except Exception as exc:  # noqa: BLE001
        result["exit_code"] = EXIT_FATAL
        result["status"] = "FAILED"
        result["error_message"] = (
            f"Stage query failed against {stage_qualified}: {exc}"
        )
        result["errors"].append(result["error_message"])
        if not quiet:
            print(f"FATAL: {result['error_message']}", file=sys.stderr)
        return _finalize_and_emit(
            result,
            quiet=quiet,
            json_output=json_output,
            output_file=output_file,
            audit_cursor_factory=audit_cursor_factory,
            general_db=general_db,
            no_audit_event=no_audit_event,
            started_monotonic=started_monotonic,
        )

    # ---- Fetch Bronze active PK set ----
    try:
        bronze_df = _fetch_pk_set(
            cursor_factory=bronze_cursor_factory,
            qualified_table=bronze_qualified,
            pk_columns=pk_columns,
            where_clause="[UdmActiveFlag] = 1",
            pl_module=pl_module,
        )
    except Exception as exc:  # noqa: BLE001
        result["exit_code"] = EXIT_FATAL
        result["status"] = "FAILED"
        result["error_message"] = (
            f"Bronze query failed against {bronze_qualified}: {exc}"
        )
        result["errors"].append(result["error_message"])
        if not quiet:
            print(f"FATAL: {result['error_message']}", file=sys.stderr)
        return _finalize_and_emit(
            result,
            quiet=quiet,
            json_output=json_output,
            output_file=output_file,
            audit_cursor_factory=audit_cursor_factory,
            general_db=general_db,
            no_audit_event=no_audit_event,
            started_monotonic=started_monotonic,
        )

    result["stage_current_count"] = stage_df.height
    result["bronze_active_count"] = bronze_df.height

    # ---- Compute the gap via Polars anti-join (CLIENT-SIDE per B-2) ----
    try:
        if stage_df.height == 0:
            gap_df = stage_df
        elif bronze_df.height == 0:
            # All Stage current PKs are missing from Bronze
            gap_df = stage_df.unique(subset=pk_columns)
        else:
            # Align dtypes between sides for the anti-join. Cast both sides
            # to Utf8 for join-key stability — anti-join compares string
            # representations, which is safe for the PK-difference compute
            # (we re-fetch the original PK values for the characterization
            # queries from the stage side).
            stage_unique = stage_df.unique(subset=pk_columns)
            bronze_unique = bronze_df.unique(subset=pk_columns)
            # Cast PK columns to Utf8 on both sides for consistent join key
            stage_keyed = stage_unique.with_columns(
                [pl_module.col(c).cast(pl_module.Utf8).alias(f"__pk_{c}")
                 for c in pk_columns]
            )
            bronze_keyed = bronze_unique.with_columns(
                [pl_module.col(c).cast(pl_module.Utf8).alias(f"__pk_{c}")
                 for c in pk_columns]
            )
            join_keys = [f"__pk_{c}" for c in pk_columns]
            anti = stage_keyed.join(
                bronze_keyed.select(join_keys),
                on=join_keys,
                how="anti",
            )
            gap_df = anti.drop(join_keys)
    except Exception as exc:  # noqa: BLE001
        result["exit_code"] = EXIT_FATAL
        result["status"] = "FAILED"
        result["error_message"] = (
            f"Polars anti-join failed: {type(exc).__name__}: {exc}"
        )
        result["errors"].append(result["error_message"])
        if not quiet:
            print(f"FATAL: {result['error_message']}", file=sys.stderr)
        return _finalize_and_emit(
            result,
            quiet=quiet,
            json_output=json_output,
            output_file=output_file,
            audit_cursor_factory=audit_cursor_factory,
            general_db=general_db,
            no_audit_event=no_audit_event,
            started_monotonic=started_monotonic,
        )

    gap_count = gap_df.height
    result["gap_count"] = gap_count

    if gap_count == 0:
        # HEALTHY — no gap. Exit 0.
        result["exit_code"] = EXIT_SUCCESS
        result["status"] = "SUCCESS"
        return _finalize_and_emit(
            result,
            quiet=quiet,
            json_output=json_output,
            output_file=output_file,
            audit_cursor_factory=audit_cursor_factory,
            general_db=general_db,
            no_audit_event=no_audit_event,
            started_monotonic=started_monotonic,
        )

    # Gap detected — characterize the first `limit` PKs.
    result["exit_code"] = EXIT_OPERATIONAL
    result["status"] = "SUCCESS"  # operational signal, not failure

    diagnoses: list[dict] = []
    theories_breakdown: dict[str, int] = {}
    # Iterate the first `limit` rows of gap_df
    capped = gap_df.head(limit)
    rows_iter = capped.iter_rows(named=True)
    for row_dict in rows_iter:
        pk_values = [row_dict[c] for c in pk_columns]
        try:
            diag = _characterize_missing_pk(
                cursor_factory=bronze_cursor_factory,
                bronze_qualified=bronze_qualified,
                pk_columns=pk_columns,
                pk_values=pk_values,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Per-PK characterization failed for PK=%s: %s",
                pk_values,
                exc,
            )
            diag = {
                "pk_values": dict(zip(pk_columns, pk_values)),
                "theory": THEORY_UNKNOWN,
                "explanation": (
                    f"Bronze query raised {type(exc).__name__}: {exc}"
                ),
                "recommendation": _RECOMMENDATIONS[THEORY_UNKNOWN].format(
                    source="{source}",
                    table="{table}",
                    pk_values=",".join(
                        str(v) if v is not None else "" for v in pk_values
                    ),
                ),
                "bronze_evidence": {
                    "row_count": 0,
                    "flag_breakdown": {0: 0, 1: 0, 2: 0},
                    "error": str(exc)[:200],
                },
            }
        diagnoses.append(diag)
        theory = diag["theory"]
        theories_breakdown[theory] = theories_breakdown.get(theory, 0) + 1

    result["diagnoses"] = diagnoses
    result["theories_breakdown"] = theories_breakdown

    return _finalize_and_emit(
        result,
        quiet=quiet,
        json_output=json_output,
        output_file=output_file,
        audit_cursor_factory=audit_cursor_factory,
        general_db=general_db,
        no_audit_event=no_audit_event,
        started_monotonic=started_monotonic,
    )


# ---------------------------------------------------------------------------
# Fatal-path helper
# ---------------------------------------------------------------------------


def _build_fatal_result(
    *,
    error_type: str,
    error_message: str,
    source: Any,
    table: Any,
    actor: str,
    started_at: datetime,
    started_at_iso: str,
    started_monotonic: datetime,
    quiet: bool,
    audit_cursor_factory: Callable | None,
    general_db: str,
    no_audit_event: bool,
) -> dict:
    result: dict[str, Any] = {
        "event_kind": "diagnose_stage_bronze_gap",
        "actor": actor,
        "source_name": source if isinstance(source, str) else None,
        "table_name": table if isinstance(table, str) else None,
        "pk_columns": [],
        "stage_current_count": 0,
        "bronze_active_count": 0,
        "gap_count": 0,
        "limit": 0,
        "theories_breakdown": {},
        "diagnoses": [],
        "exit_code": EXIT_FATAL,
        "status": "FAILED",
        "error_type": error_type,
        "error_message": error_message,
        "errors": [error_message],
        "started_at": started_at_iso,
        "started_at_dt": started_at,
        "completed_at": None,
        "duration_ms": 0,
        "audit_event_id": None,
    }
    if not quiet:
        print(f"FATAL: {error_message}", file=sys.stderr)
    return _finalize_and_emit(
        result,
        quiet=quiet,
        json_output=False,
        output_file=None,
        audit_cursor_factory=audit_cursor_factory,
        general_db=general_db,
        no_audit_event=no_audit_event,
        started_monotonic=started_monotonic,
    )


# ---------------------------------------------------------------------------
# Finalize: compute duration_ms, write audit row, render stdout, return result.
# ---------------------------------------------------------------------------


def _finalize_and_emit(
    result: dict,
    *,
    quiet: bool,
    json_output: bool,
    output_file: str | Path | None,
    audit_cursor_factory: Callable | None,
    general_db: str,
    no_audit_event: bool,
    started_monotonic: datetime,
) -> dict:
    completed_at = datetime.now(timezone.utc).replace(tzinfo=None)
    result["completed_at"] = completed_at.strftime("%Y-%m-%dT%H:%M:%SZ")
    delta = datetime.now() - started_monotonic
    result["duration_ms"] = int(delta.total_seconds() * 1000)

    # ---- Audit row INSERT (best-effort) ----
    audit_metadata = {
        "event_kind": result["event_kind"],
        "actor": result["actor"],
        "source_name": result["source_name"],
        "table_name": result["table_name"],
        "pk_columns": result["pk_columns"],
        "stage_current_count": result["stage_current_count"],
        "bronze_active_count": result["bronze_active_count"],
        "gap_count": result["gap_count"],
        "limit": result["limit"],
        "theories_breakdown": result.get("theories_breakdown", {}),
        "exit_code": result["exit_code"],
        "status": result["status"],
        "started_at": result["started_at"],
        "completed_at": result["completed_at"],
        "duration_ms": result["duration_ms"],
        "started_at_dt": result["started_at_dt"],
    }
    audit_id = _write_audit_row(
        audit_metadata,
        status=result["status"],
        error_message=result.get("error_message"),
        cursor_factory=audit_cursor_factory,
        general_db=general_db,
        skip=no_audit_event,
    )
    result["audit_event_id"] = audit_id

    # ---- Render output ----
    if json_output:
        rendered = _render_json_payload(result)
    else:
        rendered = _render_human_summary(result)

    if output_file is not None:
        try:
            path = Path(output_file)
            path.write_text(rendered, encoding="utf-8")
            result["output_file_written"] = str(path)
            if not quiet:
                # Also emit a brief stderr breadcrumb so the operator sees
                # WHERE the report went when redirected.
                print(
                    f"Report written to {path}",
                    file=sys.stderr,
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Failed to write --output-file %s: %s",
                output_file,
                exc,
            )
            # Don't change the exit code on output-file failure; the
            # operator-facing data is on stdout still.
            if not quiet:
                print(
                    f"WARNING: --output-file {output_file} write failed: {exc}",
                    file=sys.stderr,
                )
                print(rendered)
    else:
        if not quiet:
            print(rendered)

    return result


# ---------------------------------------------------------------------------
# argparse + argv entry point
# ---------------------------------------------------------------------------


def _build_arg_parser() -> argparse.ArgumentParser:
    """Build the argparse parser per D75 canonical args."""
    return _build_parser()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Diagnose Stage->Bronze PK gap: PKs with _cdc_is_current=1 "
            "in UDM_Stage but no UdmActiveFlag=1 row in UDM_Bronze. "
            "READ-ONLY against Stage/Bronze; only writes one "
            "CLI_DIAGNOSE_STAGE_BRONZE_GAP audit row to "
            "General.ops.PipelineEventLog. No --dry-run because nothing "
            "to dry-run."
        ),
    )
    parser.add_argument(
        "--source",
        required=True,
        help=(
            "SourceName from UdmTablesList (e.g. DNA / CCM / EPICOR). "
            "Required."
        ),
    )
    parser.add_argument(
        "--table",
        required=True,
        help=(
            "SourceObjectName from UdmTablesList (e.g. ACCT). Required."
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=100,
        help=(
            "Cap on per-PK characterization queries (the total gap count "
            "is always reported; only the first --limit PKs get per-PK "
            "theory classification). Default 100."
        ),
    )
    parser.add_argument(
        "--include-state",
        action="store_true",
        help=(
            "Reserved for future per-state evidence dump. Currently a "
            "no-op — standard output already carries per-PK Bronze "
            "evidence."
        ),
    )
    parser.add_argument(
        "--json-output",
        action="store_true",
        help="Emit JSON instead of human summary.",
    )
    parser.add_argument(
        "--output-file",
        default=None,
        help=(
            "Path to write rendered output to instead of stdout. Stderr "
            "messages still go to stderr."
        ),
    )
    parser.add_argument(
        "--actor",
        default=None,
        help=(
            "Operator identity for audit row (D75 + D76). One of "
            "operator / automic / pipeline. Auto-detected via TTY + "
            "AUTOMIC_RUN_ID env when omitted."
        ),
    )
    parser.add_argument(
        "--no-audit-event",
        action="store_true",
        help=(
            "Skip the CLI-level PipelineEventLog INSERT (pipeline-"
            "programmatic callers per D75 + D76)."
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
        help=(
            "Suppress stdout summary (errors still go to stderr; audit "
            "row still written)."
        ),
    )
    return parser


def cli_main(argv: list[str] | None = None) -> int:
    """argv entry point — argparse + main() + return exit code per D74.

    Exit codes (per D74):
        - 0: no gap found (Stage current == Bronze active in PK space)
        - 1: gap detected; operator must investigate
        - 2: fatal config error (missing args / unresolvable PK / table
          absent)
    """
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        # argparse exit codes: 2 for invalid args; 0 for --help
        code = exc.code if isinstance(exc.code, int) else EXIT_FATAL
        if code not in (EXIT_SUCCESS, EXIT_OPERATIONAL, EXIT_FATAL):
            code = EXIT_FATAL
        return code

    try:
        result = main(
            source=args.source,
            table=args.table,
            limit=args.limit,
            include_state=args.include_state,
            json_output=args.json_output,
            output_file=args.output_file,
            actor=args.actor,
            no_audit_event=args.no_audit_event,
            verbose=args.verbose,
            quiet=args.quiet,
        )
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else EXIT_FATAL
        if code not in (EXIT_SUCCESS, EXIT_OPERATIONAL, EXIT_FATAL):
            code = EXIT_FATAL
        return code
    except KeyboardInterrupt:
        logger.warning("Interrupted by operator")
        return EXIT_OPERATIONAL
    except Exception:  # noqa: BLE001
        tb = traceback.format_exc()
        print(
            f"FATAL: diagnose_stage_bronze_gap unexpected exception:\n"
            f"{tb[:1500]}",
            file=sys.stderr,
        )
        return EXIT_FATAL

    exit_code = int(result.get("exit_code", EXIT_FATAL))
    if exit_code not in (EXIT_SUCCESS, EXIT_OPERATIONAL, EXIT_FATAL):
        logger.error(
            "Non-canonical exit_code %r returned from main(); "
            "clamping to EXIT_FATAL",
            exit_code,
        )
        exit_code = EXIT_FATAL
    return exit_code


if __name__ == "__main__":
    sys.exit(cli_main())
