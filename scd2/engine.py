"""Polars SCD2: Bronze comparison, UPDATES via staging, INSERTs via BCP.

Provides two modes:
  - run_scd2(): Full Bronze comparison (small tables). Reads all active rows.
  - run_scd2_targeted(): PK-targeted Bronze comparison (large tables). Reads only
    Bronze rows matching the PKs in df_current via staging table join.

Optimized 2-step process (P0-8: INSERT-first for crash safety):
  1. INSERT: single batch for new rows + new versions (append-only, never truncate Bronze)
  2. UPDATE: single batch for closes/deletes
     (UdmActiveFlag=0 for update-close historical, UdmActiveFlag=2 for delete-close
     "deleted at source" — R-4 legacy alignment; UdmEndDateTime=now)

_scd2_key (IDENTITY) is excluded from all INSERT DataFrames and BCP column lists.
UdmHash = _row_hash copied from CDC.

W-16 TODO — SQL Server 2022 temporal tables evaluation:
  SQL Server 2022 temporal tables provide automatic SCD2-like versioning with
  native FOR SYSTEM_TIME AS OF query syntax. For stable dimension tables where
  column-level change tracking granularity isn't needed, temporal tables would
  eliminate custom SCD2 code entirely. Limitations: any column update creates a
  new version (no column-level selectivity), and the history table must be in
  the same database. Evaluation: identify candidate dimension tables that are
  low-to-moderate change volume, don't require column-level change tracking,
  and prototype conversion of one such table. Compare behavior with current
  SCD2 implementation before deciding on broader adoption.

C-4 NOTE — Bronze isolation level:
  ConnectorX reads Bronze using SQL Server's default READ COMMITTED isolation.
  Under standard READ COMMITTED, concurrent DML (non-pipeline writers) can cause
  inconsistent reads. Recommended: enable READ_COMMITTED_SNAPSHOT on the Bronze
  database for consistent snapshot reads without blocking. The table lock (P1-2)
  prevents concurrent pipeline runs but does not protect against non-pipeline
  writers (downstream ETL, reporting queries).

E-8 NOTE — RCSI transient SCD2 inconsistency window:
  Under RCSI, INSERT and UPDATE execute as separate statements, each with its own
  snapshot. Between INSERT commit and UPDATE commit, a concurrent reader may see:
    - Two active versions for updated PKs (new version inserted, old not yet closed)
    - One active version for new PKs (INSERT committed, no prior version to close)
  This transient window is typically milliseconds to seconds. For most analytics
  use cases this is acceptable. For real-time consumers querying Bronze during
  SCD2 promotion, use the dedup-safe query pattern:
    ROW_NUMBER() OVER (PARTITION BY pk_cols ORDER BY UdmEffectiveDateTime DESC)
    WHERE rn = 1
  instead of WHERE UdmActiveFlag = 1 alone. The V-4 post-SCD2 duplicate check
  and P1-16 dedup recovery handle the crash case where the window persists.

B-5 AUDIT (2026-02-23) — Polars join validation bug (#19624):
  Audited all .join() calls in this module. None use the `validate` parameter.
  All joins use only `on`, `how`, and `suffix`. Polars #19624 (false errors when
  `validate` is used with NULL keys) does not apply. CDC's `_filter_null_pks()`
  already removes NULL PKs before any data reaches SCD2 joins. No action required.

B-14 NOTE — INSERT-first zero-active-row window:
  The 3-step SCD2 pattern (INSERT with Flag=0 → UPDATE to close old → UPDATE to
  activate new) creates a transient window where queries filtering on
  UdmActiveFlag=1 see ZERO active rows for affected PKs. This occurs between
  the close-old UPDATE commit and the activate-new UPDATE commit.

  Timeline for a PK being updated:
    1. INSERT new version with UdmActiveFlag=0      → old=1, new=0 (readers see old)
    2. UPDATE old version: UdmActiveFlag=0           → old=0, new=0 (ZERO ACTIVE)
    3. UPDATE new version: UdmActiveFlag=1           → old=0, new=1 (readers see new)

  Under RCSI, readers with snapshots from before step 2 continue seeing the
  pre-operation state (consistent). New readers during step 2-3 see the gap.
  The window is typically milliseconds (single UPDATE statement execution time).

  For critical consumers, use the defensive query pattern that handles both
  the zero-active-row window AND the RCSI inconsistency window (E-8):
    SELECT * FROM (
      SELECT *, ROW_NUMBER() OVER (
        PARTITION BY pk_cols ORDER BY UdmEffectiveDateTime DESC
      ) AS rn
      FROM Bronze.table
    ) t WHERE rn = 1

  Minimization: Steps 2 and 3 execute as close together as possible within
  _execute_bronze_updates() followed immediately by _activate_new_versions().
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Callable

import polars as pl

import utils.configuration as config
from utils.connections import quote_identifier, quote_table, get_connection
from data_load import bcp_loader
from data_load.bcp_csv import validate_schema_before_concat, write_bcp_csv
from data_load.sanitize import cast_bit_columns, reorder_columns_for_bcp, sanitize_strings
from data_load.schema_utils import align_pk_dtypes, get_column_types
from extract.udm_connectorx_extractor import (
    read_bronze_deleted_pks,
    read_bronze_for_pks,
    read_bronze_table,
    table_exists,
    get_table_row_count,
)
from cdc.engine import _safe_concat, _validate_concat_columns
from utils.safe_concat import conform_to_schema, build_target_schema

if TYPE_CHECKING:
    from orchestration.table_config import TableConfig

logger = logging.getLogger(__name__)


# R-3.3: Sentinel for UdmSourceEndDate on active rows so point-in-time range
# queries (``WHERE @d BETWEEN UdmSourceBeginDate AND UdmSourceEndDate``) do not
# need special NULL handling. NULL on UdmSourceEndDate remains reserved for
# in-flight (Flag=0, operation U/R, pending activation) rows — this is the
# Phase 1 orphan-detection marker for the source-date chain.
#
# IMPORTANT: this sentinel applies ONLY to UdmSourceEndDate. UdmEndDateTime
# retains its legacy semantics (NULL while active; load timestamp at close)
# because Silver/Gold consumers read that column as the load-time pair.
#
# Naive (no tzinfo) intentionally — see _as_source_datetime for the
# pyodbc/BCP timezone-handling invariant.
UDM_SOURCE_END_SENTINEL: datetime = datetime(2999, 12, 31)


def _as_source_datetime(value: date | datetime | None) -> datetime | None:
    """Coerce an R-1 source business date into a naive UTC, ms-precision datetime.

    Accepts ``date``, naive ``datetime``, or aware ``datetime``. ``date`` is
    promoted to midnight UTC. Aware datetimes are converted to UTC then
    stripped of tzinfo. Returns None when given None.

    **Two invariants are load-bearing for activation to match.** The BCP
    CSV writer and the pyodbc UPDATE parameter must serialize to the exact
    same value on the SQL Server side.

    1. **Millisecond truncation.** BCP CSV writes datetimes with
       ``%Y-%m-%d %H:%M:%S.%3f`` (3-digit fractional seconds per the BCP
       CSV Contract), so the value stored in Bronze is only millisecond-
       precise. Without truncation here, INSERT stores ``.7070000`` while
       a microsecond-precision UPDATE parameter compares as ``.7074560``.

    2. **Naive (tzinfo-stripped) datetime.** BCP CSV writes UTC wall time
       without a timezone suffix, and SQL Server stores it in DATETIME2(3)
       as naive wall time. pyodbc/ODBC Driver 18 sends an *aware* Python
       datetime as DATETIMEOFFSET, which SQL Server implicitly converts
       against the session/server timezone when comparing to DATETIME2.
       On a non-UTC server the two values represent different UTC moments
       and the match silently fails. Stripping tzinfo forces pyodbc to
       send DATETIME2 naive, matching what BCP stored.

    Both invariants were latent pre-Phase-1 on ``UdmEffectiveDateTime = ?``
    and masked by the orphan-recycle cycle producing approximately correct
    current-state data. Phase 1 surfaces them because the source-date pair
    has tighter chain invariants.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is not None:
            # Convert to UTC wall time then strip tz so pyodbc sends
            # DATETIME2 (naive) instead of DATETIMEOFFSET.
            dt = value.astimezone(timezone.utc).replace(tzinfo=None)
        else:
            # Already naive — assume it represents UTC wall time.
            dt = value
    else:
        # `date` (not datetime) — promote to midnight UTC wall time.
        dt = datetime(value.year, value.month, value.day)
    # Truncate microseconds → milliseconds so INSERT (via BCP CSV) and
    # UPDATE (via pyodbc parameter) serialize to identical values.
    return dt.replace(microsecond=(dt.microsecond // 1000) * 1000)


# ---------------------------------------------------------------------------
# Internal: B-270 env-var-gated crash-injection harness (test-only)
#
# Tier 4 (Round 5 § 7 + docs/migration/06_TESTING.md) needs a deterministic
# crash boundary BETWEEN ``_execute_bronze_updates(...label_suffix=...)``
# (close-old versions) and ``_activate_new_versions(...)`` inside
# :func:`run_scd2` — so a parent test process can SIGKILL this subprocess
# and verify the in-flight orphan state (Flag=0, op∈{U,R}, both
# UdmEndDateTime AND UdmSourceEndDate IS NULL per SCD2-P1-e) is recovered
# by the NEXT run's ``_cleanup_orphaned_inactive_rows`` sweep. C7 canonical
# crash injection point per Round 5 § 7 inventory.
#
# Contract:
#   - Reads ``CRASH_INJECT_POINT`` env var; only fires when value matches
#     the ``checkpoint`` argument (default ``"after_close_old"``).
#   - Emits the canonical barrier token ``CLOSE_OLD_COMPLETE`` to stdout
#     (flushed immediately) so the parent test process sees it before the
#     sleep window opens.
#   - Sleeps ``CRASH_INJECT_SLEEP_SECONDS`` seconds (default 10) so the
#     parent has a deterministic window to SIGKILL this process before
#     the activate step runs.
#   - No-op when env var absent OR value doesn't match the checkpoint.
#     Zero production cost (one ``os.environ.get`` lookup + branch).
#   - NEVER raises — defensive try/except internal — pollution of the
#     production path is the only failure mode we cannot accept.
# ---------------------------------------------------------------------------


def _crash_test_harness_c7(checkpoint: str = "after_close_old") -> None:
    """B-270 closure: env-var-gated test-only crash injection point (C7).

    Reads ``CRASH_INJECT_POINT`` env var; if its value matches
    ``checkpoint``, emits the canonical barrier token
    (``CLOSE_OLD_COMPLETE``) to stdout (flushed) and sleeps to give a
    parent test process a deterministic window to SIGKILL this
    subprocess between the close-old UPDATE and the activate-new UPDATE.
    No-op when env var absent OR value doesn't match — zero production
    cost. NEVER raises (defensive try/except internal).

    Per docs/migration/06_TESTING.md Tier 4 + B-270 closure.
    """
    try:
        import os, sys, time  # noqa: PLC0415 — lazy by design
        if os.environ.get("CRASH_INJECT_POINT") != checkpoint:
            return
        print("CLOSE_OLD_COMPLETE", flush=True)
        sleep_seconds = float(os.environ.get("CRASH_INJECT_SLEEP_SECONDS", "10"))
        time.sleep(sleep_seconds)
    except Exception:  # noqa: BLE001 — production path MUST NOT be polluted
        # Defensive: env-var read or sleep failed for an unknown reason.
        # Swallow — the test harness is opt-in and any failure means we
        # silently degrade to "no-op", matching the env-var-absent case.
        return


@dataclass
class SCD2Result:
    """Results from SCD2 promotion."""

    inserts: int = 0
    new_versions: int = 0
    closes: int = 0
    unchanged: int = 0
    resurrections: int = 0

def _apply_source_verifier_or_block(
    candidate_delete_pks_df,
    source_verifier_fn,
    pk_columns: list[str],
    table_config: TableConfig,
):
    """B-498 + D18: invoke source_verifier_fn closure on candidate delete PKs
    and apply CDC_VERIFY_STRICT_ON_FAILURE semantic per CLAUDE.md Do-NOT rule.

    Per cdc/source_verifier.py canonical semantic (preserved per CLAUDE.md
    "Do NOT change CDC_VERIFY_STRICT_ON_FAILURE default from 1 to 0"):

    * STRICT=1 (default + canonical) + verifier raises → return EMPTY DataFrame
      (block ALL candidate deletes; the original df is dropped; no closes
      will fire). This is the canonical safe-by-default behavior — a
      verification-query failure (network / permissions / syntax) MUST NOT
      open the door to false-positive deletes.
    * STRICT=0 (explicit opt-out) + verifier raises → fall through with
      original candidate_delete_pks_df unchanged (verifier failure ignored;
      operator has explicitly accepted the risk).
    * verifier returns successfully → caller uses the returned df subset
      (verifier may filter out PKs that are still present on source).

    Per R1.3 (Phase 2 large-tables plan v5 + B-498): for now, the verifier
    output is wired through but the full "filter false-positives" semantic
    remains at the verifier-implementation layer. This function preserves
    the STRICT-on-failure block-all behavior so that whichever closure is
    passed at R2 (D2 cutover) cannot accidentally degrade to permissive.

    Args:
        candidate_delete_pks_df: Polars DataFrame of PKs that SCD2 plans to
            close as deletes (no successor; UdmActiveFlag = 2 path).
        source_verifier_fn: Caller-supplied closure (`Callable[[list], obj]`)
            or None. When None, this helper is a no-op (caller should not
            invoke it; defensive bypass for early callers).
        pk_columns: PK column names (forwarded for closure signature).
        table_config: For logging / audit-row context.

    Returns:
        DataFrame to use as the close set. May be:
        * unchanged input (verifier succeeded; STRICT not triggered)
        * verifier-returned subset (when verifier returns a DataFrame /
          list semantics; for R1.3 minimal scope, we trust the closure's
          return-type contract)
        * empty (STRICT=1 + verifier raised; block-all path)
    """
    import os  # noqa: PLC0415
    if source_verifier_fn is None:
        return candidate_delete_pks_df
    if candidate_delete_pks_df is None or len(candidate_delete_pks_df) == 0:
        return candidate_delete_pks_df

    strict_env = os.environ.get("CDC_VERIFY_STRICT_ON_FAILURE", "1")
    strict = strict_env not in ("0", "false", "False", "FALSE", "")

    try:
        # Verifier contract: takes candidate-deletes (as Polars DF OR list of PK
        # tuples per future B-334 wiring); returns either:
        # (a) None / no-op → caller proceeds with original candidate set
        # (b) DataFrame subset → caller uses returned subset
        # For R1.3 minimal scope, we accept either; downstream wiring at R2
        # (D2 cutover) finalizes the return-type contract.
        result = source_verifier_fn(candidate_delete_pks_df)
    except Exception as exc:  # noqa: BLE001 — STRICT semantic catches everything
        logger.warning(
            "B-498 source_verifier_fn raised for %s.%s candidate-delete PKs "
            "(STRICT=%s); %s closes per CLAUDE.md Do-NOT rule. Error: %s",
            table_config.source_name,
            table_config.source_object_name,
            "1" if strict else "0",
            "BLOCKING ALL" if strict else "PROCEEDING WITH (verifier failure ignored)",
            exc,
        )
        if strict:
            # Return empty DataFrame with same schema — block all closes
            return candidate_delete_pks_df.clear()
        # STRICT=0: explicit operator opt-out; proceed with original set
        return candidate_delete_pks_df

    # Verifier succeeded
    if result is None:
        return candidate_delete_pks_df
    return result


def run_scd2(
    table_config: TableConfig,
    df_current: pl.DataFrame,
    pk_columns: list[str],
    output_dir: str | Path,
    *,
    source_begin_date: date | datetime | None = None,
    source_verifier_fn: "Callable[[list], object] | None" = None,
) -> SCD2Result:
    """Run SCD2 promotion: compare CDC current vs Bronze active.

    R-1/R-3 source-date pair:
      ``source_begin_date`` feeds ``UdmSourceBeginDate`` on new versions and
      drives the chained source end date for closes
      (``successor_begin_date - 1 day`` for update-closes,
      batch business date for delete-closes). When None the engine falls
      back to the current load timestamp so ``UdmSourceBeginDate`` is still
      populated — acceptable for small tables without a business date column.

      Silver/Gold consumers continue to read ``UdmEffectiveDateTime`` /
      ``UdmEndDateTime`` as load times; those columns are unchanged.

    Args:
        table_config: Table configuration.
        df_current: Current CDC rows (from CDC result, _cdc_is_current=1).
        pk_columns: Primary key columns for SCD2 business key.
        output_dir: Directory for staging CSV files.
        source_begin_date: R-1 business begin date for this batch. For small
            tables with a date column pass ``_extracted_at`` (or equivalent);
            large tables use :func:`run_scd2_targeted` with ``target_date``.

    Returns:
        SCD2Result with counts.
    """
    result = SCD2Result()
    now = datetime.now(timezone.utc)
    # R-1/R-3: normalize source begin date. Falls back to load time so every
    # UdmSourceBeginDate is populated even for tables with no date column.
    # Both branches route through _as_source_datetime so the returned value
    # is always millisecond-aligned — required for activation to match the
    # BCP-written INSERT value (see _as_source_datetime docstring).
    source_begin_dt = _as_source_datetime(source_begin_date) or _as_source_datetime(now)
    # R-3.1/R-3.2: chained end dates for UdmSourceEndDate.
    #   update-close: successor_begin - 1 day  → gapless chain with the new version.
    #   delete-close: batch business date       → closes with no successor.
    update_close_source_end = source_begin_dt - timedelta(days=1)
    delete_close_source_end = source_begin_dt
    bronze_table = table_config.bronze_full_table_name

    if not pk_columns:
        logger.warning("No PK columns for %s — skipping SCD2", table_config.source_object_name)
        return result

    if df_current is None or len(df_current) == 0:
        logger.info("No current CDC rows for %s — skipping SCD2", table_config.source_object_name)
        return result

    # Source columns: everything that's not a CDC or SCD2 internal column
    internal_cols = {
        "_row_hash", "_extracted_at",
        "_cdc_operation", "_cdc_valid_from", "_cdc_valid_to",
        "_cdc_is_current", "_cdc_batch_id",
        "_scd2_key",
        "UdmHash", "UdmEffectiveDateTime", "UdmEndDateTime",
        "UdmSourceBeginDate", "UdmSourceEndDate",
        "UdmActiveFlag", "UdmScd2Operation", "UdmModifiedBy",
    }
    source_cols = [c for c in df_current.columns if c not in internal_cols]

    # First run: Bronze doesn't exist yet — all rows are inserts
    if not table_exists(bronze_table):
        logger.info("Bronze table %s doesn't exist — all %d rows are new inserts", bronze_table, len(df_current))
        result.inserts = len(df_current)

        df_insert = _build_scd2_insert(
            df_current, source_cols, pk_columns, now, "I",
            source_begin_date=source_begin_dt,
            table_config=table_config,
        )
        _write_and_load_bronze(df_insert, bronze_table, output_dir, table_config, "inserts")
        return result

    # B-4: Clean up orphaned inactive rows from prior crash recovery
    _cleanup_orphaned_inactive_rows(bronze_table, table_config)

    # Read active Bronze rows
    df_bronze = read_bronze_table(bronze_table)
    logger.info("Active Bronze rows: %d", len(df_bronze))

    if len(df_bronze) == 0:
        result.inserts = len(df_current)
        df_insert = _build_scd2_insert(
            df_current, source_cols, pk_columns, now, "I",
            source_begin_date=source_begin_dt,
            table_config=table_config,
        )
        _write_and_load_bronze(df_insert, bronze_table, output_dir, table_config, "inserts")
        return result

    # P1-16: Deduplicate active Bronze rows — crash recovery may leave
    # duplicate active rows (P0-8 INSERT-first design). Keep only the
    # row with the latest UdmEffectiveDateTime per PK.
    df_bronze = _dedup_bronze_active(df_bronze, pk_columns, table_config)

    # --- P0-12: Align PK dtypes before joins ---
    df_current, df_bronze = align_pk_dtypes(
        df_current, df_bronze, pk_columns, context="SCD2 run_scd2",
    )

    # --- Detect changes ---

    # Get hash from CDC current (_row_hash) and Bronze (UdmHash)
    df_cdc_keys = df_current.select(pk_columns + ["_row_hash"])
    df_bronze_keys = df_bronze.select(pk_columns + ["UdmHash"])

    # NEW INSERTS: in CDC but not in Bronze (anti-join on PKs)
    df_new = df_current.join(df_bronze_keys, on=pk_columns, how="anti")
    result.inserts = len(df_new)

    # CLOSES (deletes from source): in Bronze but not in CDC
    df_closed = df_bronze_keys.join(df_cdc_keys, on=pk_columns, how="anti")
    result.closes += len(df_closed)

    # E-6/E-18: Resurrection detection — verify no PKs appear in both
    # df_new (new inserts) and df_closed (deletes). By construction this
    # shouldn't happen (they're anti-joins in opposite directions), but a
    # PK appearing in both would cause the close UPDATE to close the just-inserted
    # new version. Resurrected PKs get UdmScd2Operation='R' for audit trail.
    resurrection_pks: pl.DataFrame | None = None
    if len(df_new) > 0 and len(df_closed) > 0:
        resurrection_check = df_new.select(pk_columns).join(
            df_closed.select(pk_columns), on=pk_columns, how="semi"
        )
        if len(resurrection_check) > 0:
            logger.info(
                "E-6/E-18: %d resurrected PKs in %s (in both new and closed sets). "
                "These will be inserted with UdmScd2Operation='R' for audit trail.",
                len(resurrection_check), table_config.source_object_name,
            )
            resurrection_pks = resurrection_check
            # Remove from both sets — resurrected PKs handled separately below
            df_new = df_new.join(resurrection_check, on=pk_columns, how="anti")
            df_closed = df_closed.join(resurrection_check, on=pk_columns, how="anti")
            result.inserts = len(df_new)
            result.closes = len(df_closed)

    # M3 / E-18 cross-run resurrection: a PK in df_new (looks like a fresh
    # insert against the active Bronze set) might actually be reappearing
    # after a prior run closed it with Flag=2. read_bronze_table only
    # returns Flag=1, so Flag=2 PKs aren't visible here without the lookup.
    # Without this branch they'd land as Op='I' instead of Op='R',
    # destroying the audit trail of the prior delete-and-resurrect.
    if len(df_new) > 0:
        m3_resurrection_pks = read_bronze_deleted_pks(
            bronze_table, pk_columns,
            df_new.select(pk_columns),
            output_dir, table_config,
        )
        if len(m3_resurrection_pks) > 0:
            logger.info(
                "M3 / E-18: %d cross-run resurrections detected for %s "
                "(PKs reappearing after prior Flag=2 close). Re-classifying "
                "as Op='R' instead of Op='I'.",
                len(m3_resurrection_pks), table_config.source_object_name,
            )
            # Move from df_new (Op='I') to resurrection_pks (Op='R').
            df_new = df_new.join(m3_resurrection_pks, on=pk_columns, how="anti")
            if resurrection_pks is None:
                resurrection_pks = m3_resurrection_pks
            else:
                resurrection_pks = pl.concat(
                    [resurrection_pks, m3_resurrection_pks]
                ).unique(subset=pk_columns)
            result.inserts = len(df_new)

    # CHANGED vs UNCHANGED: inner join, compare hashes
    df_matched = df_cdc_keys.join(
        df_bronze_keys,
        on=pk_columns,
        how="inner",
        suffix="_bronze",
    )

    # P0-10: NULL hash guards — treat NULL hashes as "changed" to prevent
    # silent misclassification when hashes are missing.
    changed_mask = (
        (pl.col("_row_hash") != pl.col("UdmHash"))
        | pl.col("_row_hash").is_null()
        | pl.col("UdmHash").is_null()
    )
    df_changed_pks = df_matched.filter(changed_mask).select(pk_columns)
    df_unchanged_pks = df_matched.filter(~changed_mask).select(pk_columns)

    result.new_versions = len(df_changed_pks)
    result.closes += len(df_changed_pks)  # old versions get closed
    result.unchanged = len(df_unchanged_pks)

    # P0-12: Count validation — CDC current rows must be fully accounted for
    accounted = result.inserts + result.new_versions + result.unchanged
    cdc_unique_pks = len(df_cdc_keys)
    if accounted != cdc_unique_pks:
        logger.error(
            "P0-12 COUNT MISMATCH in SCD2 %s: inserts(%d) + new_versions(%d) + unchanged(%d) = %d, "
            "but CDC has %d unique PKs. Possible PK dtype mismatch.",
            table_config.source_object_name,
            result.inserts, result.new_versions, result.unchanged, accounted, cdc_unique_pks,
        )

    logger.info(
        "SCD2 %s: inserts=%d, new_versions=%d, closes=%d, unchanged=%d",
        table_config.source_object_name,
        result.inserts, result.new_versions, result.closes, result.unchanged,
    )
    # O-2: Structured JSON for SCD2 signals.
    logger.info(
        "O-2_SCD2: %s",
        json.dumps({
            "signal": "scd2_result", "source": table_config.source_name,
            "table": table_config.source_object_name, "mode": "full",
            "inserts": result.inserts, "new_versions": result.new_versions,
            "closes": result.closes, "unchanged": result.unchanged,
            "resurrections": result.resurrections,
        }),
    )

    # P0-8: INSERT first, THEN UPDATE. A crash after insert but before update
    # leaves duplicate active rows (recoverable via next run's comparison),
    # instead of zero active rows (data loss requiring manual recovery).

    # --- Step 1: INSERT — new rows + new versions + resurrections ---
    insert_parts: list[pl.DataFrame] = []
    if result.inserts > 0:
        insert_parts.append(_build_scd2_insert(
            df_new, source_cols, pk_columns, now, "I",
            source_begin_date=source_begin_dt,
            table_config=table_config,
        ))
    if result.new_versions > 0:
        df_new_ver = df_current.join(df_changed_pks, on=pk_columns, how="semi")
        insert_parts.append(_build_scd2_insert(
            df_new_ver, source_cols, pk_columns, now, "U",
            source_begin_date=source_begin_dt,
            table_config=table_config,
        ))
    # E-18: Resurrected PKs get UdmScd2Operation='R' — distinct audit trail
    # for rows that were previously deleted and reappeared in source.
    if resurrection_pks is not None and len(resurrection_pks) > 0:
        df_resurrected = df_current.join(resurrection_pks, on=pk_columns, how="semi")
        insert_parts.append(_build_scd2_insert(
            df_resurrected, source_cols, pk_columns, now, "R",
            source_begin_date=source_begin_dt,
            table_config=table_config,
        ))
        result.resurrections = len(df_resurrected)
        result.inserts += len(df_resurrected)


    if insert_parts:
        # P0-7b/c: Build canonical SCD2 insert schema from df_current.
        # df_current comes from CDC (already schema-normalized if C-3a applied).
        # SCD2 columns (UdmHash, UdmEffectiveDateTime, etc.) are added by
        # _build_scd2_insert which produces consistent types. The risk is in
        # source columns where insert_parts[0] (new inserts from df_current)
        # and insert_parts[1] (new versions from df_current) diverge if
        # df_current itself was built from schema-mismatched parts.
        scd2_insert_schema = dict(insert_parts[0].schema)
        # Ensure all parts match the first part's schema (which includes
        # SCD2 metadata columns from _build_scd2_insert)
        context = f"SCD2 insert_parts for {table_config.source_object_name}"
        conformed = [
            conform_to_schema(part, scd2_insert_schema, context=context)
            for part in insert_parts
        ]
        try:
            df_all_inserts = pl.concat(conformed, how="vertical")
        except pl.exceptions.SchemaError as e:
            logger.error(
                "P0-7b: Strict vertical concat FAILED after conform_to_schema "
                "for %s — falling back to safe_concat. Error: %s",
                context, e,
            )
            df_all_inserts = _safe_concat(insert_parts)
            df_all_inserts = _validate_concat_columns(
                df_all_inserts, df_current, table_config
            )
        _write_and_load_bronze(df_all_inserts, bronze_table, output_dir, table_config, "inserts")

    # --- Step 2: UPDATE — close old versions + deletes ---
    # R-3.1/R-3.2: split closes by end-date semantics. Update-close (new
    # version supersedes old) stamps ``UdmSourceEndDate = successor_begin - 1 day``.
    # Delete-close (no successor in source) stamps ``UdmSourceEndDate = batch_business_date``.
    # Both calls stamp UdmEndDateTime (load-time close) with the same ``now``,
    # preserving the Silver/Gold contract.

    # Update-style closes (have a successor): changed PKs + resurrections.
    # R-2: when the waterfall is active, build PK + per-row _source_end_dt
    # so the old version closes on ``successor_begin - 1 day`` (gapless
    # business chain with the new version's waterfall value). Without a
    # waterfall, fall through to the pre-R-2 batch-level scalar close.
    use_waterfall_close = _waterfall_active(df_current, table_config)
    update_close_parts: list[pl.DataFrame] = []
    if len(df_changed_pks) > 0:
        if use_waterfall_close:
            df_changed_rows = df_current.join(df_changed_pks, on=pk_columns, how="semi")
            update_close_parts.append(
                _build_update_close_pks(
                    df_changed_rows, pk_columns, table_config, source_begin_dt,
                )
            )
        else:
            update_close_parts.append(df_changed_pks)
    if resurrection_pks is not None and len(resurrection_pks) > 0:
        if use_waterfall_close:
            df_resurrected_rows = df_current.join(resurrection_pks, on=pk_columns, how="semi")
            update_close_parts.append(
                _build_update_close_pks(
                    df_resurrected_rows, pk_columns, table_config, source_begin_dt,
                )
            )
        else:
            update_close_parts.append(resurrection_pks)

    if update_close_parts:
        validate_schema_before_concat(
            update_close_parts,
            f"SCD2 update-close PKs for {table_config.source_object_name}",
        )
        pks_close_update = pl.concat(update_close_parts).unique(subset=pk_columns)
        _execute_bronze_updates(
            pks_close_update, pk_columns, bronze_table,
            now, output_dir, table_config,
            # Per-PK mode carries _source_end_dt in the DataFrame; scalar mode
            # (pre-R-2) uses the batch-level successor_begin - 1 day.
            source_end_dt=None if use_waterfall_close else update_close_source_end,
            label_suffix="update_close",
        )

    # Delete-style closes (no successor in source): deleted PKs only.
    if len(df_closed) > 0:
        pks_close_delete = df_closed.select(pk_columns).unique(subset=pk_columns)
        # B-498 + D18: invoke source verifier closure (if provided) to apply
        # CDC_VERIFY_STRICT_ON_FAILURE semantic per CLAUDE.md Do-NOT rule.
        # When STRICT=1 (default) + verifier raises → block all closes.
        pks_close_delete = _apply_source_verifier_or_block(
            pks_close_delete, source_verifier_fn, pk_columns, table_config,
        )
        if len(pks_close_delete) > 0:
            _execute_bronze_updates(
                pks_close_delete, pk_columns, bronze_table,
                now, output_dir, table_config,
                source_end_dt=delete_close_source_end,
                label_suffix="delete_close",
            )

    # B-270: test-only crash injection point (C7) — fires only when
    # CRASH_INJECT_POINT=after_close_old; no-op otherwise. Boundary
    # between close-old (Step 2) and activate-new (Step 3) per the
    # B-14 transient zero-active-row window — a crash here is the
    # canonical "in-flight orphan" recovery target.
    _crash_test_harness_c7()

    # --- Step 3: ACTIVATE — flip new versions to active (E-2/E-18) ---
    # New versions (operation="U"/"R") were inserted with UdmActiveFlag=0 to avoid
    # conflicting with the filtered unique index. Now that old versions are closed,
    # activate the new versions. Activation stamps UdmSourceEndDate with the
    # R-3.3 sentinel. R-2: matching is by PK staging table (replaces the Phase-1
    # scalar UdmSourceBeginDate predicate so per-row waterfall values don't
    # mask activations).
    if result.new_versions > 0 or (resurrection_pks is not None and len(resurrection_pks) > 0):
        activate_parts: list[pl.DataFrame] = []
        if result.new_versions > 0:
            activate_parts.append(df_changed_pks.select(pk_columns))
        if resurrection_pks is not None and len(resurrection_pks) > 0:
            activate_parts.append(resurrection_pks.select(pk_columns))
        pks_to_activate = pl.concat(activate_parts).unique(subset=pk_columns)

        _expected = result.new_versions + result.resurrections
        _activated = _activate_new_versions(
            bronze_table, pks_to_activate, pk_columns, output_dir, table_config,
        )
        if _activated != _expected:
            logger.warning(
                "E-2 MISMATCH: expected %d activations in %s but UPDATE "
                "matched %d. In-flight rows will be recovered by next run's "
                "B-4 cleanup, but the update audit trail is at risk — "
                "investigate PK dtype alignment or staging-table integrity "
                "(see SCD2-P1-f and _cleanup_orphaned_inactive_rows).",
                _expected, bronze_table, _activated,
            )

    # V-4: Post-SCD2 duplicate active row check (non-blocking diagnostic).
    _check_duplicate_active_rows(bronze_table, pk_columns, table_config)

    return result


def _check_duplicate_active_rows(
    bronze_table: str,
    pk_columns: list[str],
    table_config: TableConfig,
) -> int:
    """V-4: Post-SCD2 diagnostic — check for duplicate active rows in Bronze.

    Queries Bronze for PKs with more than one UdmActiveFlag=1 row.
    Logs WARNING with count if found. Non-blocking diagnostic.

    Returns:
        Number of PKs with duplicate active rows.
    """
    if not pk_columns:
        return 0

    if not table_exists(bronze_table):
        return 0

    pk_group = ", ".join(quote_identifier(c) for c in pk_columns)
    q_bronze = quote_table(bronze_table)

    db = bronze_table.split(".")[0]
    conn = get_connection(db)
    try:
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT COUNT(*) FROM (
                SELECT {pk_group}
                FROM {q_bronze}
                WHERE UdmActiveFlag = 1
                GROUP BY {pk_group}
                HAVING COUNT(*) > 1
            ) AS dup
        """)
        dup_count = cursor.fetchone()[0]
        cursor.close()

        if dup_count > 0:
            logger.warning(
                "V-4: %d PKs with duplicate active rows in %s after SCD2 promotion. "
                "Downstream queries should use: "
                "ROW_NUMBER() OVER (PARTITION BY %s ORDER BY UdmEffectiveDateTime DESC) "
                "WHERE rn = 1 — instead of WHERE UdmActiveFlag = 1 alone.",
                dup_count, bronze_table, ", ".join(pk_columns),
            )
        return dup_count

    except Exception:
        logger.debug(
            "V-4: Could not check duplicate active rows for %s — continuing",
            bronze_table, exc_info=True,
        )
        return 0
    finally:
        conn.close()


def _parse_default_begin_date(value: str | None) -> datetime | None:
    """R-2.5: parse ``UdmTablesList.DefaultBeginDate`` into a naive datetime.

    Accepts ``'YYYY-MM-DD'`` or any ``datetime.fromisoformat``-compatible
    string. Returns None for blank/unparseable values so the caller falls
    through to the batch-level fallback.
    """
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    try:
        if len(s) <= 10:
            return datetime.strptime(s, "%Y-%m-%d")
        parsed = datetime.fromisoformat(s)
        return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed
    except ValueError:
        logger.warning(
            "R-2.5: Could not parse DefaultBeginDate %r — ignoring fallback",
            value,
        )
        return None


def _build_source_begin_expr(
    df: pl.DataFrame,
    table_config: TableConfig | None,
    batch_fallback: datetime,
) -> pl.Expr:
    """R-1/R-2: Polars expression producing per-row ``UdmSourceBeginDate``.

    Precedence for each row:
      1. First non-NULL value across ``table_config.scd2_date_columns``
         (the ordered waterfall — primary column first, then tie-breakers).
      2. ``table_config.default_begin_date`` (parsed from UdmTablesList).
      3. ``batch_fallback`` — the ms-aligned ``source_begin_dt`` supplied by
         the orchestrator (``target_date`` for large tables, max
         ``_extracted_at`` for small tables, else load time).

    When no waterfall is configured, returns a batch-level scalar literal
    — behaviour identical to pre-Phase-2 engine code.

    Missing waterfall column names log a WARNING and are skipped. All rows
    are truncated to ms precision to match the BCP CSV ``%3f`` contract
    (SCD2-P1-f) — keeps in-memory values consistent with what Bronze stores.
    """
    waterfall = table_config.scd2_date_columns if table_config else None
    default_begin = (
        _parse_default_begin_date(table_config.default_begin_date)
        if table_config else None
    )

    # Terminal fallback when neither waterfall nor default is usable.
    terminal = default_begin if default_begin is not None else batch_fallback

    if not waterfall:
        # No waterfall configured — emit a single scalar literal. Preserves
        # pre-R-2 behaviour (uniform batch-level UdmSourceBeginDate).
        return pl.lit(batch_fallback).cast(pl.Datetime("us")).alias("UdmSourceBeginDate")

    existing = [c for c in waterfall if c in df.columns]
    missing = [c for c in waterfall if c not in df.columns]
    if missing:
        logger.warning(
            "R-2: SCD2DateColumns references %d column(s) absent from the "
            "extracted DataFrame: %s. Check UdmTablesList.SCD2DateColumns "
            "spelling (case-sensitive). Ignoring missing names.",
            len(missing), missing,
        )
    if not existing:
        logger.warning(
            "R-2: None of the configured SCD2DateColumns %s were found in "
            "the DataFrame — using %s for every row's UdmSourceBeginDate.",
            waterfall,
            "DefaultBeginDate" if default_begin is not None else "batch fallback",
        )
        return pl.lit(terminal).cast(pl.Datetime("us")).alias("UdmSourceBeginDate")

    logger.info(
        "R-2: Building per-row UdmSourceBeginDate waterfall for %s over %s "
        "(default=%s, batch_fallback=%s)",
        table_config.source_object_name if table_config else "?",
        existing,
        default_begin,
        batch_fallback,
    )

    # Cast each waterfall column to Datetime(us) so pl.coalesce receives a
    # uniform dtype. ``strict=False`` keeps Utf8/date values usable — any
    # unparseable entry becomes NULL and falls through to the next waterfall
    # column, then to the terminal fallback.
    cast_exprs = [pl.col(c).cast(pl.Datetime("us"), strict=False) for c in existing]

    waterfall_expr = pl.coalesce(cast_exprs).fill_null(
        pl.lit(terminal).cast(pl.Datetime("us"))
    )

    # SCD2-P1-f: ms truncation keeps in-memory values consistent with what
    # BCP writes (DATETIME2(3)). Downstream activation matching is PK-based
    # so this is consistency, not correctness — but consistency is cheap.
    return waterfall_expr.dt.truncate("1ms").alias("UdmSourceBeginDate")


def _waterfall_active(
    df: pl.DataFrame,
    table_config: TableConfig | None,
) -> bool:
    """Return True when the R-2 per-row waterfall is usable on this DataFrame.

    ``_build_source_begin_expr`` tolerates missing waterfall columns and
    falls back to a scalar, but callers need a cheap boolean so they can
    decide whether to carry ``_source_end_dt`` through the update-close
    staging table. When False, the batch-level scalar path is preferred —
    less BCP overhead, same result.
    """
    if table_config is None or not table_config.scd2_date_columns:
        return False
    df_cols = set(df.columns)
    return any(c in df_cols for c in table_config.scd2_date_columns)


def _build_update_close_pks(
    df_rows: pl.DataFrame,
    pk_columns: list[str],
    table_config: TableConfig | None,
    batch_fallback: datetime,
) -> pl.DataFrame:
    """R-2 update-close: build PK + ``_source_end_dt`` DataFrame.

    For each new-version row (PKs currently being superseded), compute the
    successor's per-row ``UdmSourceBeginDate`` via the same waterfall as
    :func:`_build_scd2_insert`, then subtract one day for R-3.1 gapless
    chaining. The resulting DataFrame becomes the input to
    :func:`_execute_bronze_updates` in per-PK mode.

    Returned columns: ``pk_columns + ['_source_end_dt']``. One row per PK.
    """
    begin_expr = _build_source_begin_expr(df_rows, table_config, batch_fallback)
    df_with_begin = df_rows.with_columns(begin_expr)
    return df_with_begin.select(
        pk_columns
        + [
            (pl.col("UdmSourceBeginDate") - pl.duration(days=1))
            .dt.truncate("1ms")
            .alias("_source_end_dt"),
        ]
    )


def _build_scd2_insert(
    df: pl.DataFrame,
    source_cols: list[str],
    pk_columns: list[str],
    effective_dt: datetime,
    operation: str,
    *,
    source_begin_date: datetime | None = None,
    table_config: TableConfig | None = None,
) -> pl.DataFrame:
    """Build SCD2 INSERT DataFrame with UDM columns. Excludes _scd2_key (IDENTITY).

    Dual-pair date semantics (Phase 1 + Phase 2 R-1/R-2):

      Load-time pair — Silver/Gold contract, unchanged from pre-Phase-1:
        * ``UdmEffectiveDateTime`` = ``effective_dt`` (pipeline load timestamp).
        * ``UdmEndDateTime``       = NULL on active inserts; close UPDATE stamps
          the load timestamp when the version becomes historical.

      Source-date pair — R-1/R-3 business chain (Phase 1), extended in R-2:
        * ``UdmSourceBeginDate`` — when ``table_config.scd2_date_columns`` is
          configured, computed **per-row** by waterfall COALESCE
          (primary → tie-breakers → ``default_begin_date`` → ``source_begin_date``
          → ``effective_dt``). When no waterfall is configured, falls back to
          the pre-R-2 batch-level scalar (``source_begin_date`` or
          ``effective_dt``) applied uniformly to every row.
        * ``UdmSourceEndDate``   = :data:`UDM_SOURCE_END_SENTINEL` for
          operation="I" (immediately active), NULL for operations "U"/"R"
          (pending activation, see E-2). ``_activate_new_versions`` stamps the
          sentinel when flipping Flag=0 → Flag=1.

    E-2: For operation="U" (new versions of existing PKs), UdmActiveFlag is set
    to 0 initially. The activation UPDATE step (after closing old versions) flips
    it to 1. This prevents conflicts with the filtered unique index
    (ensure_bronze_unique_active_index) which rejects duplicate active rows per PK.
    For operation="I" (brand new PKs), UdmActiveFlag is set to 1 directly since
    there is no existing active row to conflict with.

    E-18: operation="R" (reactivation) behaves like "U" — starts inactive since
    there is an existing version (the deleted row) that needs to be closed first.
    The "R" operation type provides a distinct audit trail for resurrected PKs:
    active period → deleted period → reactivated period.

    Args:
        df: Current-row DataFrame (from CDC).
        source_cols: Source (non-UDM) columns to carry into the INSERT.
        pk_columns: PK columns (unused in this function; kept for signature
            stability with other engine helpers).
        effective_dt: Load timestamp shared by the whole batch.
        operation: SCD2 operation code ("I", "U", "R").
        source_begin_date: Batch-level R-1 business date. Used as the
            terminal fallback when the waterfall is empty / all-NULL.
        table_config: Drives the R-2 waterfall. When None the function
            falls back to the pre-R-2 single-literal behaviour.
    """
    # Select only source columns that exist in the DataFrame
    available_cols = [c for c in source_cols if c in df.columns]

    # E-2/E-18: New versions ("U") and reactivations ("R") start inactive to
    # avoid unique index conflict. New inserts ("I") start active since no
    # prior active row exists.
    active_flag = 0 if operation in ("U", "R") else 1

    # R-3.3: Active "I" inserts get the source-date sentinel immediately;
    # pending "U"/"R" rows keep NULL until _activate_new_versions flips them.
    if active_flag == 1:
        source_end_lit = pl.lit(UDM_SOURCE_END_SENTINEL).alias("UdmSourceEndDate")
    else:
        source_end_lit = pl.lit(None, dtype=pl.Datetime("us", "UTC")).alias("UdmSourceEndDate")

    # R-2: per-row waterfall. Falls back to source_begin_date (ms-aligned
    # by _as_source_datetime in the orchestrator) when not configured — so
    # UdmSourceBeginDate is never silently NULL.
    batch_fallback = source_begin_date if source_begin_date is not None else effective_dt
    source_begin_expr = _build_source_begin_expr(df, table_config, batch_fallback)

    # B-1: UdmHash is now VARCHAR(64) (full SHA-256 hex string), mapped from _row_hash (Utf8).
    df_out = df.select(available_cols).with_columns(
        df["_row_hash"].alias("UdmHash") if "_row_hash" in df.columns else pl.lit(None).cast(pl.Utf8).alias("UdmHash"),
        # Load-time pair — Silver/Gold contract preserved.
        pl.lit(effective_dt).alias("UdmEffectiveDateTime"),
        pl.lit(None, dtype=pl.Datetime("us", "UTC")).alias("UdmEndDateTime"),
        # Source-date pair — R-1/R-3 business chain (per-row under R-2).
        source_begin_expr,
        source_end_lit,
        pl.lit(active_flag).cast(pl.Int8).alias("UdmActiveFlag"),
        pl.lit(operation).alias("UdmScd2Operation"),
        pl.lit(config.SQL_SERVER_USER).alias("UdmModifiedBy"),
    )

    return df_out

def _write_and_load_bronze(
    df: pl.DataFrame,
    bronze_table: str,
    output_dir: str | Path,
    table_config: TableConfig,
    label: str,
) -> None:
    """Write SCD2 INSERT rows to CSV and BCP load into Bronze table.

    BCP-HANG-FIX-v3 — Adaptive context selection for Bronze loads:
      The new pipeline BCP-loads directly into Bronze clustered-index tables.
      With batch_size=800 and no TABLOCK, each micro-commit cycles through
      row-lock acquire → log flush → lock release → network round-trip.
      During the inter-batch gap, the SQL Server session can go idle long
      enough for TLS keep-alive to fail or for a stateful firewall to drop
      the connection. The BCP subprocess hangs waiting for a response that
      will never come.

      Fix: Detect when the Bronze table is empty (first-run backfill) and
      use bulk_load_stage_context (sp_tableoption TABLOCK) + large batch
      size (100K) instead of bulk_load_bronze_context. On an empty table
      there are NO concurrent readers, so TABLOCK's exclusive lock is safe
      and keeps the connection alive continuously.

      For incremental loads where the table has active rows (readers may
      exist), the existing Bronze context (LOCK_ESCALATION=DISABLE, 800-row
      batches) is preserved to avoid blocking readers.

    IDENTITY column handling:
      Bronze tables have a _scd2_key IDENTITY column. BCP in character mode
      (-c) maps CSV columns positionally to ALL table columns. Without a
      format file or placeholder, the CSV's N columns misalign against the
      table's N+1 columns, causing immediate rc=1 failure.

      XML format files (-f) are unreliable on Linux mssql-tools18 — the parser
      rejects them with "Unknown error occurred while attempting to read" and
      -f conflicts with -c ("Warning: -f overrides -c").

      Solution: Include _scd2_key as a placeholder column with value 0 in the
      CSV. BCP reads the 0 but ignores it for IDENTITY columns (auto-generates
      the next identity value) because the -E flag is NOT passed. This is
      documented Microsoft behavior: without -E, identity values in the data
      file are discarded and SQL Server assigns unique values.

    E-3: Bronze SCD2 loads use atomic=True (default) — the entire INSERT must
    be a single transaction for SCD2 atomicity.
    """
    df = sanitize_strings(df)
    df = cast_bit_columns(df)

    # Include _scd2_key as a placeholder (value=0) for BCP positional mapping.
    # BCP ignores this value for IDENTITY columns when -E is not passed —
    # SQL Server auto-generates the next identity value.
    # Do NOT pass -E in _build_bcp_command (it's not there — verified).
    if "_scd2_key" not in df.columns:
        df = df.with_columns(pl.lit(0).cast(pl.Int64).alias("_scd2_key"))

    # P0-1: Reorder columns to match target table positional order.
    # Do NOT exclude _scd2_key — it's now in the DataFrame as a placeholder.
    if table_exists(bronze_table):
        df = reorder_columns_for_bcp(
            df, bronze_table,
            fill_null_columns=table_config.exclude_columns or None,
        )

    csv_path = write_bcp_csv(
        df,
        Path(output_dir) / f"{table_config.source_name}_{table_config.source_object_name}_scd2_{label}.csv",
    )

    # =========================================================================
    # BCP-HANG-FIX-v3: Adaptive context selection
    # =========================================================================
    # Determine whether the Bronze table is empty (first-run / backfill).
    # An empty table has no concurrent readers, so TABLOCK is safe and solves
    # the connection-drop hang by:
    #   1. Acquiring a Bulk Update lock at session start, keeping the
    #      connection active continuously (no idle gaps between batches)
    #   2. Using 100K batch size instead of 800 (19x fewer commits,
    #      19x fewer log flushes, 19x fewer network round-trips)
    #   3. Enabling minimal logging on the clustered index via TABLOCK
    #
    # For tables WITH active rows, we must preserve the existing Bronze
    # context to avoid blocking concurrent readers with an exclusive lock.
    # =========================================================================
    db = bronze_table.split(".")[0]
    row_count = len(df)

    # Check if this is a first-run / empty table
    bronze_exists = table_exists(bronze_table)
    active_rows = get_table_row_count(bronze_table) if bronze_exists else 0

    use_first_run_context = (
        active_rows == 0
        and row_count > config.BCP_BRONZE_TABLOCK_THRESHOLD
    )

    if use_first_run_context:
        # -----------------------------------------------------------------
        # FIRST-RUN PATH: Empty table, no concurrent readers.
        # Mimic old pipeline: TABLOCK + large batch size + BULK_LOGGED.
        # This is the exact approach that made the old pipeline reliable
        # for initial backfills of 300 Bronze tables.
        # -----------------------------------------------------------------
        logger.info(
            "BCP-HANG-FIX-v3: First-run Bronze load for %s — using TABLOCK "
            "context (active_rows=%d, insert_rows=%d, batch_size=%d)",
            bronze_table, active_rows, row_count,
            config.BCP_BRONZE_FIRST_RUN_BATCH_SIZE,
        )
        with bcp_loader.bulk_load_bronze_first_run_context(db, bronze_table):
            # Single-stream BCP: Bronze tables have clustered indexes, so
            # TABLOCK acquires EXCLUSIVE (not BU) locks. Parallel streams
            # would serialize, not parallelize. Single stream with TABLOCK
            # + 100K batch size is still ~10x faster than 800-row batches
            # without TABLOCK, and keeps the connection alive continuously.
            bcp_loader.bcp_load(
                str(csv_path),
                bronze_table,
                expected_row_count=row_count,
                is_stage=True,  # Uses BCP_STAGE_BATCH_SIZE (100K)
            )

    else:
        # -----------------------------------------------------------------
        # INCREMENTAL PATH: Table has active rows, concurrent readers may
        # exist. Use Bronze context (LOCK_ESCALATION=DISABLE, 800-row
        # batches) to avoid blocking readers.
        #
        # Tables below BCP_BRONZE_TABLOCK_THRESHOLD on first-run also
        # use this path — they're small enough that 800-batch loads
        # complete quickly without hitting TLS idle timeouts.
        # -----------------------------------------------------------------
        if active_rows == 0 and row_count <= config.BCP_BRONZE_TABLOCK_THRESHOLD:
            logger.info(
                "BCP-HANG-FIX-v3: Small first-run Bronze load for %s — "
                "using standard Bronze context (rows=%d <= threshold=%d)",
                bronze_table, row_count, config.BCP_BRONZE_TABLOCK_THRESHOLD,
            )
        else:
            logger.info(
                "BCP-HANG-FIX-v3: Incremental Bronze load for %s — "
                "using LOCK_ESCALATION=DISABLE context (active_rows=%d, "
                "insert_rows=%d, batch_size=%d)",
                bronze_table, active_rows, row_count,
                config.BCP_BRONZE_BATCH_SIZE,
            )

        with bcp_loader.bulk_load_bronze_context(db, bronze_table):
            bcp_loader.bcp_load(
                str(csv_path),
                bronze_table,
                expected_row_count=row_count,
            )

def _check_log_space(db: str, bronze_table: str, estimated_log_gb: float) -> None:
    """E-10: Pre-flight check of available transaction log space.

    Queries sys.dm_db_log_space_usage to verify sufficient log space exists
    before large SCD2 UPDATE operations. Logs WARNING if available space
    appears insufficient.
    """
    try:
        conn = get_connection(db)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT total_log_size_in_bytes / 1073741824.0, "
                "       used_log_space_in_bytes / 1073741824.0 "
                "FROM sys.dm_db_log_space_usage"
            )
            row = cursor.fetchone()
            cursor.close()

            if row:
                total_gb, used_gb = float(row[0]), float(row[1])
                available_gb = total_gb - used_gb

                if available_gb < estimated_log_gb * 1.5:
                    logger.warning(
                        "E-10: Transaction log space may be insufficient for %s. "
                        "Available: %.1f GB, estimated need: %.1f GB (total: %.1f GB, "
                        "used: %.1f GB). Ensure frequent log backups (every 15-30 min) "
                        "or increase log file size before proceeding.",
                        bronze_table, available_gb, estimated_log_gb,
                        total_gb, used_gb,
                    )
                else:
                    logger.debug(
                        "E-10: Log space check for %s — available: %.1f GB, "
                        "estimated need: %.1f GB",
                        bronze_table, available_gb, estimated_log_gb,
                    )
        finally:
            conn.close()
    except Exception:
        logger.debug(
            "E-10: Could not check log space for %s — continuing",
            bronze_table, exc_info=True,
        )


def _classify_delete_retention(
    *,
    db: str,
    q_staging: str,
    q_bronze: str,
    join_condition: str,
    batch_dt: datetime,
    retention_days: int,
    bronze_table: str,
    total_deletes: int,
) -> None:
    """R-2: classify delete-close PKs as within-retention or anomalous.

    Runs one SELECT joining the staging PK set to Bronze, grouping each
    row by age (in days) against ``retention_days``. Emits INFO when all
    deletes fit inside the retention window, WARNING when one or more
    are newer than the policy allows.

    Pre-Phase-1 legacy rows with NULL ``UdmSourceBeginDate`` are counted
    separately (``unknown_age``) — they can't be classified but their
    count is logged so operators know the classification was partial.

    Non-blocking: any SELECT failure logs a warning and returns. Missing
    classification is preferable to skipping the delete-close UPDATE.
    """
    try:
        conn = get_connection(db)
        try:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT
                    COUNT(*) AS matched,
                    SUM(CASE
                        WHEN t.UdmSourceBeginDate IS NULL THEN 0
                        WHEN DATEDIFF(DAY, t.UdmSourceBeginDate, ?) <= ? THEN 1
                        ELSE 0 END) AS within_retention,
                    SUM(CASE
                        WHEN t.UdmSourceBeginDate IS NULL THEN 0
                        WHEN DATEDIFF(DAY, t.UdmSourceBeginDate, ?) > ? THEN 1
                        ELSE 0 END) AS exceeds_retention,
                    SUM(CASE WHEN t.UdmSourceBeginDate IS NULL THEN 1 ELSE 0 END) AS unknown_age,
                    MIN(CASE WHEN t.UdmSourceBeginDate IS NOT NULL
                        THEN DATEDIFF(DAY, t.UdmSourceBeginDate, ?) END) AS min_age_days,
                    MAX(CASE WHEN t.UdmSourceBeginDate IS NOT NULL
                        THEN DATEDIFF(DAY, t.UdmSourceBeginDate, ?) END) AS max_age_days
                FROM {q_bronze} t
                INNER JOIN {q_staging} s ON {join_condition}
                WHERE t.UdmActiveFlag = 1
            """, batch_dt, retention_days,
                 batch_dt, retention_days,
                 batch_dt,
                 batch_dt)
            row = cursor.fetchone()
            cursor.close()
        finally:
            conn.close()
    except Exception:
        logger.warning(
            "R-2: retention classification query failed for %s — "
            "delete-close proceeding without classification.",
            bronze_table, exc_info=True,
        )
        return

    if row is None or row[0] == 0:
        return

    matched, within, exceeds, unknown, min_age, max_age = (
        int(row[0]),
        int(row[1] or 0),
        int(row[2] or 0),
        int(row[3] or 0),
        int(row[4]) if row[4] is not None else None,
        int(row[5]) if row[5] is not None else None,
    )

    summary = (
        f"{bronze_table} delete-close retention: total={total_deletes}, "
        f"matched_active={matched}, within_{retention_days}d={within}, "
        f"exceeds_{retention_days}d={exceeds}, unknown_age={unknown}, "
        f"min_age_days={min_age}, max_age_days={max_age}"
    )
    if exceeds > 0:
        logger.warning("R-2 ANOMALOUS DELETES: %s", summary)
    else:
        logger.info("R-2 expected purge: %s", summary)


def _execute_bronze_updates(
    pks_to_close: pl.DataFrame,
    pk_columns: list[str],
    bronze_table: str,
    end_dt: datetime,
    output_dir: str | Path,
    table_config: TableConfig,
    *,
    source_end_dt: datetime | None = None,
    label_suffix: str = "",
) -> None:
    """Close old versions via staging table + UPDATE JOIN.

    Dual-pair semantics (Phase 1 + R-2 per-row extension):
      * ``end_dt`` stamps ``UdmEndDateTime`` — load time of the close.
        This is today's legacy semantic, unchanged, and preserves the
        Silver/Gold contract on the load-time pair.
      * ``UdmActiveFlag`` (R-4 legacy alignment): ``label_suffix == "delete_close"``
        sets Flag = 2 (legacy semantic for "deleted at source"); every other
        close path sets Flag = 0 (historical, superseded by an update).
        Existing nonclustered indexes filtered on ``Flag = 2`` and consumer
        queries with ``WHERE Flag != 0`` rely on this distinction.
      * ``UdmSourceEndDate`` — business chain end. Two modes:
          * **Per-PK (R-2, waterfall-driven update-close).** When
            ``pks_to_close`` contains a ``_source_end_dt`` column, the
            staging table carries it and the UPDATE reads
            ``UdmSourceEndDate = s._source_end_dt``. Each PK closes on
            ``successor_UdmSourceBeginDate - 1 day`` — gapless with the
            per-row waterfall values on the new version.
          * **Batch-level (Phase 1 default).** When ``pks_to_close`` has
            PK columns only, the UPDATE stamps
            ``UdmSourceEndDate = source_end_dt`` (the single scalar).
            Callers choose based on close reason (R-3.1 / R-3.2):
              * update-close without waterfall: ``new_source_begin - 1 day``.
              * delete-close: batch business date.
            When ``source_end_dt`` is None, ``UdmSourceEndDate`` is left unset.

    ``label_suffix`` disambiguates the staging-table name and CSV path when
    the caller invokes this function more than once per batch (update-close
    + delete-close). When empty, names match the pre-Phase-1 format for
    backward compatibility.

    SCD-4 NOTE: All UPDATE operations use cursor.execute() (single statement),
    NOT cursor.executemany(). pyodbc issue #481 confirms rowcount returns -1
    after executemany(), which would break P2-14 rowcount validation.

    L-3 NOTE — Bronze growth and partitioning:
      Bronze is append-only by design. For a 3B-row source with 5% monthly
      churn, Bronze grows ~1.8B rows/year. After 3 years the table reaches
      ~8.4B rows. The targeted read filters on UdmActiveFlag=1, but index
      structures span all rows (active + historical).
      Recommended partitioning strategy:
        - Partition Bronze on UdmActiveFlag or UdmEndDateTime so historical
          rows live in separate filegroups.
        - Periodic archival of UdmActiveFlag=0 rows older than N months to
          an archive table.
        - Use get_active_row_count() (filtered partition stats) instead of
          get_table_row_count() for INDEX_REBUILD_THRESHOLD calculations.
    """
    db = bronze_table.split(".")[0]
    schema = bronze_table.split(".")[1]
    _suffix = f"_{label_suffix}" if label_suffix else ""
    staging_table = f"{db}.{schema}._staging_scd2_{table_config.source_object_name}{_suffix}"
    q_staging = quote_table(staging_table)
    q_bronze = quote_table(bronze_table)

    # R-2: per-PK mode when caller attached _source_end_dt column. The staging
    # table then carries it alongside the PKs and the UPDATE reads
    # UdmSourceEndDate from the staging row instead of a scalar parameter.
    per_pk_source_end = "_source_end_dt" in pks_to_close.columns

    # P0-3: Use actual PK column types from target table instead of NVARCHAR(MAX)
    pk_types = get_column_types(bronze_table, pk_columns)

    conn = get_connection(db)
    try:
        cursor = conn.cursor()
        pk_col_defs = ", ".join(f"{quote_identifier(c)} {pk_types[c]}" for c in pk_columns)
        if per_pk_source_end:
            pk_col_defs = pk_col_defs + ", _source_end_dt DATETIME2(3) NULL"
        cursor.execute(f"IF OBJECT_ID(?, 'U') IS NOT NULL DROP TABLE {q_staging}", staging_table)
        cursor.execute(f"CREATE TABLE {q_staging} ({pk_col_defs})")
        cursor.close()
    finally:
        conn.close()

    # E-5: Dedup staging PKs — defense-in-depth against duplicate business keys.
    # The UPDATE FROM JOIN pattern is nondeterministic with duplicate keys.
    # Currently safe (SET values are constants), but this prevents issues if
    # the pattern is ever extended to SET values from the staging table.
    pre_dedup = len(pks_to_close)
    pks_to_close = pks_to_close.unique(subset=pk_columns)
    if len(pks_to_close) < pre_dedup:
        logger.debug(
            "E-5: Deduplicated %d duplicate PKs from close staging set for %s",
            pre_dedup - len(pks_to_close), bronze_table,
        )

    try:
        # BCP load PKs into staging — keep native dtypes (don't cast to Utf8)
        pks_clean = sanitize_strings(pks_to_close)
        _csv_label = f"close_pks{_suffix}" if _suffix else "close_pks"
        csv_path = write_bcp_csv(
            pks_clean,
            Path(output_dir) / f"{table_config.source_name}_{table_config.source_object_name}_scd2_{_csv_label}.csv",
        )
        # E-3: Staging tables are ephemeral — atomic=False for performance.
        # is_stage=True picks BCP_STAGE_BATCH_SIZE (100K) so heap-style
        # staging loads don't fall through to the 800-row Bronze default
        # and time out the BCP subprocess on large close / activation sets.
        bcp_loader.bcp_load(str(csv_path), staging_table, atomic=False, is_stage=True)

        # P2-5: Index staging table for efficient JOIN against large Bronze tables
        bcp_loader.create_staging_index(staging_table, pk_columns, row_count=len(pks_to_close))

        # R-2: retention-aware classification for delete-closes. Only runs on
        # delete-close batches where ExpectedRetentionDays is configured —
        # typical on CCM tables with scheduled purges. Non-blocking.
        if (
            label_suffix == "delete_close"
            and not per_pk_source_end
            and table_config.expected_retention_days is not None
        ):
            _classify_delete_retention(
                db=db,
                q_staging=q_staging,
                q_bronze=q_bronze,
                join_condition=" AND ".join(
                    f"t.{quote_identifier(c)} = s.{quote_identifier(c)}"
                    for c in pk_columns
                ),
                batch_dt=end_dt,
                retention_days=table_config.expected_retention_days,
                bronze_table=bronze_table,
                total_deletes=len(pks_to_close),
            )

        # P2-11/E-10: Warn about large UPDATE JOINs that generate significant
        # transaction log. UPDATEs are always fully logged regardless of recovery
        # model. Each row generates before+after images in the log.
        if len(pks_to_close) > 1_000_000:
            # E-10: Estimate transaction log usage (~400 bytes avg row × 2 for
            # before+after images in log records)
            estimated_log_gb = (len(pks_to_close) * 400 * 2) / (1024**3)
            logger.warning(
                "P2-11/E-10: Large Bronze UPDATE JOIN: %d rows in %s. "
                "Estimated transaction log: %.1f GB. "
                "This is fully logged regardless of BULK_LOGGED recovery model. "
                "Monitor: SELECT * FROM sys.dm_db_log_space_usage",
                len(pks_to_close), bronze_table, estimated_log_gb,
            )

            # E-10: Pre-flight log space check
            _check_log_space(db, bronze_table, estimated_log_gb)

        # SCD-3/B-2: Batch the UPDATE JOIN to avoid lock escalation.
        # SQL Server escalates row locks to table-level exclusive locks at ~5,000
        # locks. Table-level exclusive locks override RCSI, blocking all readers.
        # Keep batch size below 5,000 to maintain row-level locking.
        join_condition = " AND ".join(
            f"t.{quote_identifier(c)} = s.{quote_identifier(c)}" for c in pk_columns
        )

        _SCD3_BATCH_SIZE = config.SCD2_UPDATE_BATCH_SIZE
        total_affected = 0

        # Build the SET clause — close the row and stamp the load-time end.
        # R-4 flag semantic alignment with legacy:
        #   * label_suffix == "delete_close" → UdmActiveFlag = 2 ("deleted at source").
        #   * everything else (update_close, no suffix) → UdmActiveFlag = 0 (historical).
        # Existing nonclustered indexes filtered on UdmActiveFlag = 2 and consumer
        # queries with WHERE UdmActiveFlag != 0 depend on this distinction.
        # UdmSourceEndDate has three modes:
        #   * per-PK (R-2): reads s._source_end_dt from staging row.
        #   * batch scalar: reads the source_end_dt parameter.
        #   * legacy: left untouched when neither is provided.
        flag_value = 2 if label_suffix == "delete_close" else 0
        if per_pk_source_end:
            set_clause = (
                f"t.UdmActiveFlag = {flag_value}, "
                "t.UdmEndDateTime = ?, "
                "t.UdmSourceEndDate = s._source_end_dt"
            )
            update_params_single: tuple = (end_dt,)
            update_params_batch: tuple = (_SCD3_BATCH_SIZE, end_dt)
        elif source_end_dt is not None:
            set_clause = (
                f"t.UdmActiveFlag = {flag_value}, "
                "t.UdmEndDateTime = ?, "
                "t.UdmSourceEndDate = ?"
            )
            update_params_single = (end_dt, source_end_dt)
            update_params_batch = (_SCD3_BATCH_SIZE, end_dt, source_end_dt)
        else:
            set_clause = f"t.UdmActiveFlag = {flag_value}, t.UdmEndDateTime = ?"
            update_params_single = (end_dt,)
            update_params_batch = (_SCD3_BATCH_SIZE, end_dt)

        if len(pks_to_close) <= _SCD3_BATCH_SIZE:
            # Small enough for a single UPDATE — no batching needed
            conn = get_connection(db)
            try:
                cursor = conn.cursor()
                cursor.execute(f"""
                    UPDATE t
                    SET {set_clause}
                    FROM {q_bronze} t
                    INNER JOIN {q_staging} s ON {join_condition}
                    WHERE t.UdmActiveFlag = 1
                """, *update_params_single)
                total_affected = cursor.rowcount
                cursor.close()
            finally:
                conn.close()
        else:
            # SCD-3: Batch by adding a row-number column to staging and
            # processing _SCD3_BATCH_SIZE rows at a time via TOP + DELETE.
            # The staging table already has an index from create_staging_index().
            logger.info(
                "SCD-3/B-2: Batching Bronze UPDATE JOIN for %s — %d PKs in batches of %d "
                "(below 5K lock escalation threshold)",
                bronze_table, len(pks_to_close), _SCD3_BATCH_SIZE,
            )
            conn = get_connection(db)
            try:
                batch_num = 0
                while True:
                    batch_num += 1
                    cursor = conn.cursor()
                    # UPDATE TOP(N) processes a bounded batch each iteration.
                    # The WHERE UdmActiveFlag=1 filter ensures already-processed
                    # rows aren't touched again, providing natural convergence.
                    cursor.execute(f"""
                        UPDATE TOP (?) t
                        SET {set_clause}
                        FROM {q_bronze} t
                        INNER JOIN {q_staging} s ON {join_condition}
                        WHERE t.UdmActiveFlag = 1
                    """, *update_params_batch)
                    batch_affected = cursor.rowcount
                    cursor.close()
                    total_affected += batch_affected

                    if batch_affected > 0:
                        logger.info(
                            "SCD-3: Batch %d closed %d Bronze rows in %s (%d total)",
                            batch_num, batch_affected, bronze_table, total_affected,
                        )

                    if batch_affected < _SCD3_BATCH_SIZE:
                        break  # All rows processed
            finally:
                conn.close()

        # P2-14: Verify actual vs expected UPDATE row count
        if total_affected != len(pks_to_close):
            if total_affected < len(pks_to_close):
                # C-2: Expected during retries — WHERE UdmActiveFlag=1 makes
                # this idempotent. Already-closed rows won't be touched.
                logger.info(
                    "P2-14: Bronze UPDATE affected %d rows (expected %d) in %s — "
                    "delta of %d (idempotent retry: already-closed rows from prior run)",
                    total_affected, len(pks_to_close), bronze_table,
                    len(pks_to_close) - total_affected,
                )
            else:
                logger.error(
                    "P2-14: Bronze UPDATE affected %d rows (expected %d) in %s — "
                    "MORE rows affected than expected. Investigate join conditions.",
                    total_affected, len(pks_to_close), bronze_table,
                )
        else:
            logger.info("Closed %d Bronze rows in %s", total_affected, bronze_table)
    finally:
        # Always drop staging table
        conn = get_connection(db)
        try:
            cursor = conn.cursor()
            cursor.execute(f"DROP TABLE IF EXISTS {q_staging}")
            cursor.close()
        finally:
            conn.close()


def _activate_new_versions(
    bronze_table: str,
    pks_to_activate: pl.DataFrame,
    pk_columns: list[str],
    output_dir: str | Path,
    table_config: TableConfig,
) -> int:
    """E-2/E-18: Activate newly-inserted SCD2 versions after closing old versions.

    New versions are inserted with UdmActiveFlag=0 (operation='U' or 'R') to
    avoid conflicting with the filtered unique index during the INSERT phase.
    After the UPDATE step closes old active versions, this step flips the new
    versions to active and stamps the R-3.3 sentinel on UdmSourceEndDate.

    R-2 PK-staging match (replaces Phase-1 ``UdmSourceBeginDate = @dt``):
    ``pks_to_activate`` carries the PK set of this batch's new versions. A
    small staging table is BCP-loaded and joined into the Bronze UPDATE so
    only those rows flip. This is required under per-row waterfall
    ``UdmSourceBeginDate`` where a single scalar predicate no longer matches
    any row, and it also works identically for tables without waterfall
    config (all rows share the same PK set regardless of begin date).

    Remaining WHERE predicates preserve the Phase-1 orphan invariants:
    ``UdmActiveFlag=0 AND UdmSourceEndDate IS NULL AND UdmScd2Operation IN
    ('U','R')``. Both NULL-date predicates are load-bearing (SCD2-P1-e) —
    neither is sufficient alone.

    ``UdmEndDateTime`` is NOT modified here — it remains NULL while active
    per the pre-Phase-1 load-time contract consumed by Silver/Gold.

    A crash after INSERT but before this activation leaves rows with
    UdmActiveFlag=0 and UdmSourceEndDate IS NULL — detectable and recoverable
    by :func:`_cleanup_orphaned_inactive_rows` on the next pipeline run.

    Args:
        bronze_table: Fully qualified Bronze table name.
        pks_to_activate: DataFrame with ``pk_columns`` — the PKs of new
            versions inserted in this batch (operation U + R rows).
        pk_columns: Business key columns.
        output_dir: Staging CSV directory.
        table_config: Drives staging table naming and PK types.

    Returns:
        Number of rows activated.
    """
    if len(pks_to_activate) == 0:
        return 0

    db = bronze_table.split(".")[0]
    schema = bronze_table.split(".")[1]
    staging_table = (
        f"{db}.{schema}._staging_scd2_activate_{table_config.source_object_name}"
    )
    q_staging = quote_table(staging_table)
    q_bronze = quote_table(bronze_table)

    # P0-3: use actual PK column types from Bronze (avoids NVARCHAR(MAX) waste).
    pk_types = get_column_types(bronze_table, pk_columns)

    # Drop + create staging (idempotent — defends against stale staging
    # from a crash between pipeline restarts).
    conn = get_connection(db)
    try:
        cursor = conn.cursor()
        pk_col_defs = ", ".join(
            f"{quote_identifier(c)} {pk_types[c]}" for c in pk_columns
        )
        cursor.execute(
            f"IF OBJECT_ID(?, 'U') IS NOT NULL DROP TABLE {q_staging}",
            staging_table,
        )
        cursor.execute(f"CREATE TABLE {q_staging} ({pk_col_defs})")
        cursor.close()
    finally:
        conn.close()

    try:
        # E-5: dedup defensively — UPDATE JOIN with duplicate keys is
        # nondeterministic, though callers should already supply unique PKs.
        pks_unique = pks_to_activate.select(pk_columns).unique(subset=pk_columns)
        pks_clean = sanitize_strings(pks_unique)
        csv_path = write_bcp_csv(
            pks_clean,
            Path(output_dir)
            / f"{table_config.source_name}_{table_config.source_object_name}_scd2_activate_pks.csv",
        )
        # E-3: staging is ephemeral — atomic=False for performance.
        # is_stage=True picks BCP_STAGE_BATCH_SIZE (100K) so heap-style
        # staging loads don't fall through to the 800-row Bronze default
        # and time out the BCP subprocess on large close / activation sets.
        bcp_loader.bcp_load(str(csv_path), staging_table, atomic=False, is_stage=True)
        bcp_loader.create_staging_index(
            staging_table, pk_columns, row_count=len(pks_unique),
        )

        join_condition = " AND ".join(
            f"t.{quote_identifier(c)} = s.{quote_identifier(c)}" for c in pk_columns
        )

        conn = get_connection(db)
        try:
            cursor = conn.cursor()
            # Two-predicate in-flight filter (SCD2-P1-e) keeps us off active
            # rows and off pre-Phase-1 legacy closed rows whose UdmSourceEndDate
            # was never populated.
            cursor.execute(f"""
                UPDATE t
                SET t.UdmActiveFlag = 1,
                    t.UdmSourceEndDate = ?
                FROM {q_bronze} t
                INNER JOIN {q_staging} s ON {join_condition}
                WHERE t.UdmActiveFlag = 0
                  AND t.UdmSourceEndDate IS NULL
                  AND t.UdmScd2Operation IN ('U', 'R')
            """, UDM_SOURCE_END_SENTINEL)
            activated = cursor.rowcount
            cursor.close()
        finally:
            conn.close()

        if activated > 0:
            logger.info(
                "E-2: Activated %d new SCD2 versions in %s via PK staging",
                activated, bronze_table,
            )
        return activated
    except Exception:
        logger.exception(
            "E-2: Failed to activate new versions in %s — "
            "rows remain with UdmActiveFlag=0, UdmSourceEndDate IS NULL. "
            "Will be recovered on next run's B-4 cleanup.",
            bronze_table,
        )
        return 0
    finally:
        # Always drop staging — matches _execute_bronze_updates cleanup.
        try:
            conn = get_connection(db)
            try:
                cursor = conn.cursor()
                cursor.execute(
                    f"IF OBJECT_ID(?, 'U') IS NOT NULL DROP TABLE {q_staging}",
                    staging_table,
                )
                cursor.close()
            finally:
                conn.close()
        except Exception:
            logger.warning(
                "E-2: Could not drop activation staging table %s — "
                "staging_cleanup.py will reclaim it on the next pipeline start.",
                staging_table,
            )


def _cleanup_orphaned_inactive_rows(
    bronze_table: str,
    table_config: TableConfig,
) -> int:
    """B-4: Clean up orphaned Flag=0 rows from prior crash recovery.

    After a crash between SCD2 INSERT (UdmActiveFlag=0) and activation,
    orphaned rows persist. :func:`_activate_new_versions` only targets the
    current batch's UdmSourceBeginDate, so orphans from prior crashed runs
    are never activated.

    In-flight marker (Phase 1, SCD2-P1-e fix): the predicate requires BOTH
    ``UdmEndDateTime IS NULL`` AND ``UdmSourceEndDate IS NULL``. Either
    condition alone is insufficient:

    * ``UdmEndDateTime IS NULL`` alone also matches active rows under the
      legacy Silver/Gold contract (active rows stay NULL here).
    * ``UdmSourceEndDate IS NULL`` alone also matches pre-Phase-1 legacy
      CLOSED rows whose source-date column was never populated — deleting
      those destroys historical SCD2 versions. (This is the bug that
      deleted 53,747 legitimate rows on the first ACCT run; the predicate
      was tightened afterward.)

    Only truly in-flight rows have BOTH columns NULL simultaneously:
    UdmEndDateTime is set by the close UPDATE, UdmSourceEndDate is set by
    the activation UPDATE. Both happen after the INSERT. A crash between
    INSERT and either UPDATE leaves both NULL.

    Safe to DELETE because:
    - Flag=0 rows are invisible to downstream consumers (WHERE UdmActiveFlag=1)
    - The current run will re-insert correct versions via normal SCD2 flow
    - Rows that failed activation have no point-in-time coverage anyway.

    Args:
        bronze_table: Fully qualified Bronze table name.
        table_config: Table configuration for logging context.

    Returns:
        Number of orphaned rows deleted.
    """
    if not table_exists(bronze_table):
        return 0

    db = bronze_table.split(".")[0]

    try:
        q_bronze = quote_table(bronze_table)

        # Check for orphaned rows. Require BOTH UdmEndDateTime IS NULL AND
        # UdmSourceEndDate IS NULL — only genuine in-flight rows have both.
        # Legacy pre-Phase-1 closed rows have UdmEndDateTime populated; they
        # must not be matched.
        conn = get_connection(db)
        try:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT COUNT(*) FROM {q_bronze}
                WHERE UdmActiveFlag = 0
                  AND UdmEndDateTime IS NULL
                  AND UdmSourceEndDate IS NULL
                  AND UdmScd2Operation IN ('U', 'R')
            """)
            orphan_count = cursor.fetchone()[0]
            cursor.close()
        finally:
            conn.close()

        if orphan_count == 0:
            return 0

        logger.warning(
            "B-4: Found %d orphaned inactive rows in %s (UdmActiveFlag=0, "
            "UdmEndDateTime IS NULL, UdmSourceEndDate IS NULL, operation U/R). "
            "Likely from a prior crash between INSERT and activation. "
            "Deleting — current run will re-insert correct versions.",
            orphan_count, bronze_table,
        )

        # Delete in batches to avoid lock escalation (reuse B-2 batch size)
        batch_size = config.SCD2_UPDATE_BATCH_SIZE
        total_deleted = 0
        conn = get_connection(db)
        try:
            while True:
                cursor = conn.cursor()
                cursor.execute(f"""
                    DELETE TOP (?) FROM {q_bronze}
                    WHERE UdmActiveFlag = 0
                      AND UdmEndDateTime IS NULL
                      AND UdmSourceEndDate IS NULL
                      AND UdmScd2Operation IN ('U', 'R')
                """, batch_size)
                deleted = cursor.rowcount
                cursor.close()
                total_deleted += deleted

                if deleted < batch_size:
                    break
        finally:
            conn.close()

        logger.info(
            "B-4: Deleted %d orphaned inactive rows from %s",
            total_deleted, bronze_table,
        )
        return total_deleted

    except Exception:
        logger.warning(
            "B-4: Could not clean up orphaned inactive rows in %s — "
            "continuing with normal SCD2 flow (non-fatal)",
            bronze_table, exc_info=True,
        )
        return 0


def _dedup_bronze_active(
    df_bronze: pl.DataFrame,
    pk_columns: list[str],
    table_config: TableConfig,
) -> pl.DataFrame:
    """P1-16: Deduplicate active Bronze rows per PK.

    After a crash in the INSERT-first SCD2 design (P0-8), a PK may have
    multiple active rows (both old and new version with UdmActiveFlag=1).
    Keep only the row with the latest UdmEffectiveDateTime per PK to
    prevent inflated join results in the comparison.
    """
    before_count = len(df_bronze)

    if "UdmEffectiveDateTime" in df_bronze.columns:
        df_bronze = (
            df_bronze
            .sort("UdmEffectiveDateTime", descending=True)
            .unique(subset=pk_columns, keep="first")
        )
    else:
        df_bronze = df_bronze.unique(subset=pk_columns, keep="first")

    dedup_count = before_count - len(df_bronze)
    if dedup_count > 0:
        logger.warning(
            "P1-16: Found %d duplicate active Bronze rows for %s.%s "
            "(likely from prior crash recovery). Deduplicated to %d rows.",
            dedup_count, table_config.source_name,
            table_config.source_object_name, len(df_bronze),
        )

    return df_bronze


# ---------------------------------------------------------------------------
# P1-3: Targeted SCD2 for large tables
# ---------------------------------------------------------------------------

def run_scd2_targeted(
    table_config: TableConfig,
    df_current: pl.DataFrame,
    pk_columns: list[str],
    output_dir: str | Path,
    deleted_pks: pl.DataFrame | None = None,
    *,
    source_begin_date: date | datetime | None = None,
    source_verifier_fn: "Callable[[list], object] | None" = None,
) -> SCD2Result:
    """Run SCD2 promotion with PK-targeted Bronze read (large tables).

    Instead of reading all active Bronze rows (impossible at 3B scale),
    this loads only the Bronze rows whose PKs exist in df_current. Uses
    a staging table + INNER JOIN for the targeted read.

    The comparison logic is identical to run_scd2() — only the Bronze
    read is different.

    R-1/R-3 source-date pair: ``source_begin_date`` is the windowed
    ``target_date`` for large tables. It feeds ``UdmSourceBeginDate`` on new
    versions and drives the chained end date for closes (update-close:
    ``target_date - 1 day``; delete-close: ``target_date``). ``UdmEffectiveDateTime``
    and ``UdmEndDateTime`` continue to carry the load-time pair used by Silver/Gold.

    P0-11: Accepts deleted_pks from windowed CDC. Without this, windowed
    deletes would never propagate to Bronze because the PK-targeted read
    only looks up PKs in df_current (which excludes deleted rows).

    Args:
        table_config: Table configuration.
        df_current: Current CDC rows (from windowed CDC result).
        pk_columns: Primary key columns for SCD2 business key.
        output_dir: Directory for staging CSV files.
        deleted_pks: PKs deleted in windowed CDC (from CDCResult.deleted_pks).
        source_begin_date: R-1 business begin date — ``target_date`` from the
            windowed extraction. When None, falls back to the load timestamp.

    Returns:
        SCD2Result with counts.
    """
    result = SCD2Result()
    now = datetime.now(timezone.utc)
    # R-1/R-3: ms-aligned source begin date (see _as_source_datetime docstring
    # for why millisecond precision matters for the activation UPDATE match).
    source_begin_dt = _as_source_datetime(source_begin_date) or _as_source_datetime(now)
    update_close_source_end = source_begin_dt - timedelta(days=1)
    delete_close_source_end = source_begin_dt
    bronze_table = table_config.bronze_full_table_name

    if not pk_columns:
        logger.warning("No PK columns for %s — skipping targeted SCD2", table_config.source_object_name)
        return result

    if df_current is None or len(df_current) == 0:
        logger.info("No current CDC rows for %s — skipping targeted SCD2", table_config.source_object_name)
        return result

    # Source columns
    internal_cols = {
        "_row_hash", "_extracted_at",
        "_cdc_operation", "_cdc_valid_from", "_cdc_valid_to",
        "_cdc_is_current", "_cdc_batch_id",
        "_scd2_key",
        "UdmHash", "UdmEffectiveDateTime", "UdmEndDateTime",
        "UdmSourceBeginDate", "UdmSourceEndDate",
        "UdmActiveFlag", "UdmScd2Operation", "UdmModifiedBy",
    }
    source_cols = [c for c in df_current.columns if c not in internal_cols]

    # First run: Bronze doesn't exist yet — all rows are inserts
    if not table_exists(bronze_table):
        logger.info(
            "Bronze table %s doesn't exist — all %d rows are new inserts (targeted)",
            bronze_table, len(df_current),
        )
        result.inserts = len(df_current)
        df_insert = _build_scd2_insert(
            df_current, source_cols, pk_columns, now, "I",
            source_begin_date=source_begin_dt,
            table_config=table_config,
        )
        _write_and_load_bronze(df_insert, bronze_table, output_dir, table_config, "inserts")
        return result

    # B-4: Clean up orphaned inactive rows from prior crash recovery
    _cleanup_orphaned_inactive_rows(bronze_table, table_config)

    # Targeted Bronze read: only rows matching PKs in df_current
    pk_df = df_current.select(pk_columns).unique()
    df_bronze = read_bronze_for_pks(
        bronze_table, pk_columns, pk_df, output_dir, table_config,
    )
    logger.info("Targeted Bronze rows matching %d PKs: %d", len(pk_df), len(df_bronze))

    if len(df_bronze) == 0:
        result.inserts = len(df_current)
        df_insert = _build_scd2_insert(
            df_current, source_cols, pk_columns, now, "I",
            source_begin_date=source_begin_dt,
            table_config=table_config,
        )
        _write_and_load_bronze(df_insert, bronze_table, output_dir, table_config, "inserts")
        return result

    # P1-16: Deduplicate active Bronze rows (crash recovery)
    df_bronze = _dedup_bronze_active(df_bronze, pk_columns, table_config)

    # --- P0-12: Align PK dtypes before joins ---
    df_current, df_bronze = align_pk_dtypes(
        df_current, df_bronze, pk_columns, context="SCD2 run_scd2_targeted",
    )

    # --- Detect changes (same algorithm as run_scd2) ---

    df_cdc_keys = df_current.select(pk_columns + ["_row_hash"])
    df_bronze_keys = df_bronze.select(pk_columns + ["UdmHash"])

    # NEW INSERTS: in CDC but not in Bronze
    df_new = df_current.join(df_bronze_keys, on=pk_columns, how="anti")
    result.inserts = len(df_new)

    # CLOSES: in Bronze but not in CDC (within the targeted set)
    # For large tables, this only closes rows whose PKs were in the
    # extraction window. Rows outside the window are untouched.
    df_closed = df_bronze_keys.join(df_cdc_keys, on=pk_columns, how="anti")
    # C-5: Don't increment result.closes here — compute from deduplicated set below

    # CHANGED vs UNCHANGED
    df_matched = df_cdc_keys.join(
        df_bronze_keys,
        on=pk_columns,
        how="inner",
        suffix="_bronze",
    )

    # P0-10: NULL hash guards (same as run_scd2)
    changed_mask = (
        (pl.col("_row_hash") != pl.col("UdmHash"))
        | pl.col("_row_hash").is_null()
        | pl.col("UdmHash").is_null()
    )
    df_changed_pks = df_matched.filter(changed_mask).select(pk_columns)
    df_unchanged_pks = df_matched.filter(~changed_mask).select(pk_columns)

    result.new_versions = len(df_changed_pks)
    result.unchanged = len(df_unchanged_pks)

    # P0-12: Count validation
    accounted = result.inserts + result.new_versions + result.unchanged
    cdc_unique_pks = len(df_cdc_keys)
    if accounted != cdc_unique_pks:
        logger.error(
            "P0-12 COUNT MISMATCH in targeted SCD2 %s: "
            "inserts(%d) + new_versions(%d) + unchanged(%d) = %d, "
            "but CDC has %d unique PKs. Possible PK dtype mismatch.",
            table_config.source_object_name,
            result.inserts, result.new_versions, result.unchanged, accounted, cdc_unique_pks,
        )

    # C-5: Summary log moved after close set dedup below for accurate close count.

    # P0-8: INSERT first, THEN UPDATE. A crash after insert but before update
    # leaves duplicate active rows (recoverable via next run's comparison),
    # instead of zero active rows (data loss requiring manual recovery).

    # --- Step 1: INSERT — new rows + new versions + resurrections ---
    insert_parts: list[pl.DataFrame] = []
    targeted_resurrection_pks: pl.DataFrame | None = None  # E-18: set below if resurrections found
    if result.inserts > 0:
        insert_parts.append(_build_scd2_insert(
            df_new, source_cols, pk_columns, now, "I",
            source_begin_date=source_begin_dt,
            table_config=table_config,
        ))
    if result.new_versions > 0:
        df_new_ver = df_current.join(df_changed_pks, on=pk_columns, how="semi")
        insert_parts.append(_build_scd2_insert(
            df_new_ver, source_cols, pk_columns, now, "U",
            source_begin_date=source_begin_dt,
            table_config=table_config,
        ))

    # E-18: Resurrection inserts added after deleted_pks processing below
    # (need to detect resurrection PKs first before building inserts)

    # --- Step 2: UPDATE — close old versions + deletes ---
    # R-3.1/R-3.2: split by close reason so UdmSourceEndDate is set correctly.
    #   update_close_parts  → UdmSourceEndDate = source_begin - 1 day (successor)
    #   delete_close_parts  → UdmSourceEndDate = source_begin (no successor)
    # R-2: waterfall-active tables get per-PK _source_end_dt carried through
    # the update-close staging table (gapless chain with the new version's
    # per-row UdmSourceBeginDate). Delete-close always uses the batch-level
    # scalar — no successor to chain against.
    use_waterfall_close = _waterfall_active(df_current, table_config)

    update_close_parts: list[pl.DataFrame] = []
    delete_close_parts: list[pl.DataFrame] = []

    # Bronze-anti-CDC: PKs present in Bronze but missing from df_current.
    # Under windowed targeted SCD2 this is a delete-style close (no successor
    # in this extraction window).
    if len(df_closed) > 0:
        delete_close_parts.append(df_closed.select(pk_columns))
    # Hash-changed PKs get a new version → update-style close.
    if len(df_changed_pks) > 0:
        if use_waterfall_close:
            df_changed_rows = df_current.join(df_changed_pks, on=pk_columns, how="semi")
            update_close_parts.append(
                _build_update_close_pks(
                    df_changed_rows, pk_columns, table_config, source_begin_dt,
                )
            )
        else:
            update_close_parts.append(df_changed_pks)

    # P0-11: Include deleted PKs from windowed CDC. These PKs were removed
    # from the source within the extraction window. Without this, they'd stay
    # UdmActiveFlag=1 in Bronze permanently because the PK-targeted read
    # never loads them (they're not in df_current).
    if deleted_pks is not None and len(deleted_pks) > 0:
        # Align dtypes against an existing close part when possible
        _align_ref = update_close_parts[0] if update_close_parts else (
            delete_close_parts[0] if delete_close_parts else None
        )
        if _align_ref is not None:
            deleted_pks, _ = align_pk_dtypes(
                deleted_pks, _align_ref,
                pk_columns, context="SCD2 deleted_pks alignment",
            )

        # E-6/E-18: Resurrection detection — filter out PKs that appear in both
        # deleted_pks (windowed CDC detected as deleted) and df_current
        # (present in the current extraction). These are resurrected rows —
        # a PK was deleted from source in one window but re-inserted in another.
        # Without this filter, the close UPDATE would close the just-inserted
        # new version, leaving zero active rows for that PK.
        # E-18: Resurrected PKs get UdmScd2Operation='R' for audit trail.
        deleted_pks_filtered = deleted_pks.select(pk_columns)
        targeted_resurrection_pks = deleted_pks_filtered.join(
            df_current.select(pk_columns), on=pk_columns, how="semi"
        )
        if len(targeted_resurrection_pks) > 0:
            logger.info(
                "E-6/E-18: %d resurrected PKs detected in %s (in deleted_pks AND "
                "df_current). Removing from close set — these rows will be "
                "inserted with UdmScd2Operation='R' for audit trail.",
                len(targeted_resurrection_pks), table_config.source_object_name,
            )
            deleted_pks_filtered = deleted_pks_filtered.join(
                targeted_resurrection_pks, on=pk_columns, how="anti"
            )

        # B-498 + D18: invoke source verifier closure (if provided) on the
        # post-resurrection-filter set BEFORE adding to delete_close_parts.
        # CDC_VERIFY_STRICT_ON_FAILURE semantic preserved per CLAUDE.md.
        deleted_pks_filtered = _apply_source_verifier_or_block(
            deleted_pks_filtered, source_verifier_fn, pk_columns, table_config,
        )
        if len(deleted_pks_filtered) > 0:
            delete_close_parts.append(deleted_pks_filtered)
            logger.info(
                "P0-11: Adding %d deleted PKs from windowed CDC to Bronze close set for %s",
                len(deleted_pks_filtered), table_config.source_object_name,
            )

    # E-18: Build resurrection inserts (after targeted_resurrection_pks is known)
    if targeted_resurrection_pks is not None and len(targeted_resurrection_pks) > 0:
        df_resurrected = df_current.join(targeted_resurrection_pks, on=pk_columns, how="semi")
        insert_parts.append(_build_scd2_insert(
            df_resurrected, source_cols, pk_columns, now, "R",
            source_begin_date=source_begin_dt,
            table_config=table_config,
        ))
        result.resurrections = len(df_resurrected)
        result.inserts += len(df_resurrected)
        # Close the old deleted/inactive versions for resurrected PKs — the
        # resurrection is the successor, so this is an update-style close.
        # R-2: when the waterfall is active, emit PK + _source_end_dt rows
        # using the resurrected row's per-row UdmSourceBeginDate.
        if use_waterfall_close:
            update_close_parts.append(
                _build_update_close_pks(
                    df_resurrected, pk_columns, table_config, source_begin_dt,
                )
            )
        else:
            update_close_parts.append(targeted_resurrection_pks)

    # P0-8: INSERT first, THEN UPDATE (moved here after resurrection detection)
    if insert_parts:
            scd2_insert_schema = dict(insert_parts[0].schema)
            context = f"targeted SCD2 insert_parts for {table_config.source_object_name}"
            conformed = [
                conform_to_schema(part, scd2_insert_schema, context=context)
                for part in insert_parts
            ]
            try:
                df_all_inserts = pl.concat(conformed, how="vertical")
            except pl.exceptions.SchemaError as e:
                logger.error(
                    "P0-7b: Strict vertical concat FAILED after conform_to_schema "
                    "for %s — falling back to safe_concat. Error: %s",
                    context, e,
                )
                df_all_inserts = _safe_concat(insert_parts)
                df_all_inserts = _validate_concat_columns(
                    df_all_inserts, df_current, table_config
                )
            _write_and_load_bronze(df_all_inserts, bronze_table, output_dir, table_config, "inserts")

    # R-3.1/R-3.2: run update-style closes first, then delete-style closes,
    # each with its own UdmSourceEndDate semantic. PKs cannot appear in both
    # groups by construction.
    _total_closes = 0
    if update_close_parts:
        validate_schema_before_concat(
            update_close_parts,
            f"targeted SCD2 update-close PKs for {table_config.source_object_name}",
        )
        pks_close_update = pl.concat(update_close_parts).unique(subset=pk_columns)
        _total_closes += len(pks_close_update)
        _execute_bronze_updates(
            pks_close_update, pk_columns, bronze_table,
            now, output_dir, table_config,
            # Per-PK mode carries _source_end_dt in the DataFrame; scalar mode
            # (pre-R-2) uses the batch-level successor_begin - 1 day.
            source_end_dt=None if use_waterfall_close else update_close_source_end,
            label_suffix="update_close",
        )

    if delete_close_parts:
        validate_schema_before_concat(
            delete_close_parts,
            f"targeted SCD2 delete-close PKs for {table_config.source_object_name}",
        )
        pks_close_delete = pl.concat(delete_close_parts).unique(subset=pk_columns)
        _total_closes += len(pks_close_delete)
        _execute_bronze_updates(
            pks_close_delete, pk_columns, bronze_table,
            now, output_dir, table_config,
            source_end_dt=delete_close_source_end,
            label_suffix="delete_close",
        )

    # C-5: Report the total close count (update-close + delete-close).
    result.closes = _total_closes

    # --- Step 3: ACTIVATE — flip new versions to active (E-2/E-18) ---
    # New versions (operation="U"/"R") were inserted with UdmActiveFlag=0 to avoid
    # conflicting with the filtered unique index. Now that old versions are closed,
    # activate the new versions. R-2: match by PK staging table (replaces the
    # Phase-1 scalar UdmSourceBeginDate predicate so per-row waterfall values
    # don't mask activations).
    has_resurrections = targeted_resurrection_pks is not None and len(targeted_resurrection_pks) > 0
    if result.new_versions > 0 or has_resurrections:
        activate_parts: list[pl.DataFrame] = []
        if result.new_versions > 0:
            activate_parts.append(df_changed_pks.select(pk_columns))
        if has_resurrections:
            activate_parts.append(targeted_resurrection_pks.select(pk_columns))
        pks_to_activate = pl.concat(activate_parts).unique(subset=pk_columns)

        _expected = result.new_versions + result.resurrections
        _activated = _activate_new_versions(
            bronze_table, pks_to_activate, pk_columns, output_dir, table_config,
        )
        if _activated != _expected:
            logger.warning(
                "E-2 MISMATCH: expected %d activations in %s but UPDATE "
                "matched %d. In-flight rows will be recovered by next run's "
                "B-4 cleanup, but the update audit trail is at risk — "
                "investigate PK dtype alignment or staging-table integrity "
                "(see SCD2-P1-f and _cleanup_orphaned_inactive_rows).",
                _expected, bronze_table, _activated,
            )

    logger.info(
        "Targeted SCD2 %s: inserts=%d, new_versions=%d, closes=%d, unchanged=%d",
        table_config.source_object_name,
        result.inserts, result.new_versions, result.closes, result.unchanged,
    )
    # O-2: Structured JSON for targeted SCD2 signals.
    logger.info(
        "O-2_SCD2: %s",
        json.dumps({
            "signal": "scd2_result", "source": table_config.source_name,
            "table": table_config.source_object_name, "mode": "targeted",
            "inserts": result.inserts, "new_versions": result.new_versions,
            "closes": result.closes, "unchanged": result.unchanged,
            "resurrections": result.resurrections,
        }),
    )

    # V-4: Post-SCD2 duplicate active row check (non-blocking diagnostic).
    _check_duplicate_active_rows(bronze_table, pk_columns, table_config)

    return result