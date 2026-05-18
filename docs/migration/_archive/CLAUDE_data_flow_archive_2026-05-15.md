<\!-- Archive provenance:
- Extracted from: CLAUDE.md (pre-trim state at commit c189432 / 2026-05-15 / 720 lines total)
- Extracted at: lines 151-213 (63 lines verbatim)
- Trim commit: 7e2c606 (D.5 Approach A — Conservative trim per Q-12 approved)
- Trim rationale: section was largely DUPLICATE of canonical content at the destination(s); replaced in active CLAUDE.md with summary + cross-ref to reduce CCL token cost
- Destination cross-ref(s) in active CLAUDE.md: docs/migration/phase1/01c_data_flow_walkthrough.md (canonical 1,146 lines)
- Archive strategy: belt-and-suspenders per user-direction 2026-05-15 (Option B "Archive EVERYTHING verbatim"); content preserved for recovery without git archaeology
- Reversibility: `git show c189432:CLAUDE.md` returns full pre-trim CLAUDE.md; this archive is a partial slice
- Authored: 2026-05-15 by retroactive archive sweep per refactor-strategy decision
- Linked from: docs/migration/_refactor_log.md (refactor event D.5-data-flow)
-->

# CLAUDE.md — Data Flow (per table) (archived)

**This is an archived copy** of the Data Flow (per table) section from CLAUDE.md, extracted verbatim from the pre-D.5-trim state. The active CLAUDE.md no longer contains this section — see cross-ref destination(s) above for the canonical home(s).

If you arrived here looking for current information: prefer the destination cross-ref. This archive exists for recovery + audit-trail purposes only.

---

## Data Flow (per table)

### Small Tables (no date column - full extract each run)
Source (Oracle/SQL Server)
  -> ConnectorX full extract -> Polars DataFrame
  -> add _row_hash (polars-hash, deterministic across sessions) + _extracted_at
  -> Write BCP CSV (per BCP CSV Contract above)
  -> Ensure stage/bronze tables exist in UDM (auto-create from DataFrame dtypes)
  -> Schema evolution: detect new/removed/changed columns (P0-2)
  -> Column sync: auto-populate UdmTablesColumnsList + discover PKs from source
  -> Empty extraction guard: skip CDC if row count drops >90% vs previous run (P1-1)
  -> Table lock: sp_getapplock prevents concurrent runs on the same table (P1-2)
  -> CDC promotion (Polars in-memory comparison with existing CDC table)
        NULL PK filter (P0-4) -> anti-join inserts, hash compare updates, reverse anti-join deletes
        Column reorder to match target INFORMATION_SCHEMA ordinal position (P0-1)
        Staging tables use actual PK types from target (P0-3)
        columns: _cdc_operation (I/U/D), _cdc_valid_from/to, _cdc_is_current, _cdc_batch_id
        -> Capture changes via BCP into staging table
  -> SCD2 promotion (Polars comparison: CDC current vs Bronze active)
        Staging tables use actual PK types from target (P0-3)
        columns: UdmHash, UdmEffectiveDateTime, UdmEndDateTime, UdmActiveFlag, UdmScd2Operation
        -> UPDATEs via BCP staging table + MERGE
        -> INSERTs via BCP (append-only, never truncate Bronze)

### Large Tables (date-chunked - incremental extraction)
Per-day processing pipeline: extract one day at a time → windowed CDC → targeted SCD2 → checkpoint → next day.

Source (Oracle/SQL Server)
  -> Windowed extract (single day via SourceAggregateColumnName) -> Polars DataFrame
  -> add _row_hash (polars-hash) + _extracted_at
  -> Write BCP CSV (per BCP CSV Contract above)
  -> Ensure stage/bronze tables exist (first day only)
  -> Schema evolution (P0-2)
  -> Column sync (first load only)
  -> Table lock: sp_getapplock prevents concurrent runs (P1-2)
  -> Windowed CDC (P1-3/P1-4): compare only within extraction date window
        NULL PK filter (P0-4) -> anti-join inserts, hash compare updates
        Delete detection scoped to extraction window only (P1-4) — rows outside window untouched
        Column reorder (P0-1), typed staging tables (P0-3)
  -> Targeted SCD2 (P1-3): PK-scoped Bronze read via staging table join (not full table load)
  -> Checkpoint date as SUCCESS in PipelineExtractionState (P1-5)
  -> CSV cleanup
  -> Next day...

**Design decisions (resolved):**
- **Memory bounding (P1-3/P2-4):** Processing one day at a time keeps memory bounded. A 3B-row table with 3M rows/day fits comfortably in memory per-day.
- **Checkpoint and gap detection (P1-5):** `orchestration/pipeline_state.py` tracks per-day status in PipelineExtractionState. On restart, the pipeline resumes from the last successful date and fills gaps.
- **Partial extraction recovery (P1-6):** Each completed day is checkpointed. A failure on day 15 of 30 preserves the first 14 days; the next run picks up from day 15.
- **Idempotency:** Windowed CDC comparison handles re-runs safely. Re-extracting the same date produces unchanged hashes for untouched rows.
- **Delete detection (P1-4):** Scoped to extraction window. Rows outside the window are not considered deleted. Pair with periodic full reconciliation for real deletes.
- **Cross-day transaction overlap (V-7):** Source transactions spanning midnight may split across processing windows. Three mitigations exist: (1) `LookbackDays` provides a rolling re-extraction window as the primary mechanism — a lookback of 3 days means each date is re-processed across 3 runs, catching most split transactions. (2) `OVERLAP_MINUTES` env var (default 0) extends each day's window backward; when >= 1440 minutes (full day), shifts target_date back by 1+ days; sub-day precision requires datetime-level WHERE clauses in extractors (future enhancement). (3) Weekly reconciliation (`cdc/reconciliation.py`) catches any remaining discrepancies as the safety net. CDC comparison is idempotent — overlapping extraction windows produce no phantom changes because unchanged rows hash identically.

**Current extraction routing:**
- Oracle + SourceIndexHint populated -> oracledb with per-day date chunks, INDEX hints, TRUNC() boundaries (P3-2), distinct-date pre-query to skip empty days (P2-2)
- Oracle + SourceIndexHint NULL -> ConnectorX windowed with FULL scan hint, TRUNC() boundaries (P3-2)
- SQL Server -> ConnectorX windowed

**What we know works:**
- SourceAggregateColumnName is the date column used for WHERE clause filtering
- LookbackDays provides a rolling window to capture day-over-day changes
- FirstLoadDate defines the earliest date boundary for initial loads
- Multiple runs per day provide natural retry coverage for transient failures
