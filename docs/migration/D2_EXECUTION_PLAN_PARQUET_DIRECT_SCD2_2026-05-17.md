# D2 + D18 Execution Plan — Parquet-Direct SCD2 (Small + Large Tables)

**Date**: 2026-05-17
**Author**: pipeline lead + parent agent (orchestrator role) + reviewer Agent `a04ff0da8f7a69993` (40th cumulative; udm-design-reviewer)
**Status**: 🟡 Draft — awaiting pipeline-lead sign-off before Phase 2 R1 execution
**Scope**: execute already-locked D2 ("Drop Stage layer entirely; Parquet snapshots replace it") + D18 ("Move verify-before-close + E-12 detection to SCD2 layer") at ALL scales — small tables (1.2M rows; ACCT pilot) AND large tables (3B+ records; months-of-Parquet replay)

---

## §0. Planning session provenance

**Skills invoked during this planning session** (per `udm-planning-session-startup` skill at session start; see `docs/migration/PLANNING_DISCIPLINE.md` for matrix):

| Skill | Invoked at | Scope reference | Rationale |
|---|---|---|---|
| `udm-planning-session-startup` | 2026-05-17 (session start) | Always-mandatory entry skill | Walked 5-step protocol; surfaced 10 active + 8 on-demand skills; user approved |
| `udm-brainstorm` | 2026-05-17 (initial brainstorm attempt) | PS-1 + PS-8 conditional | HALTED per skill anti-pattern when CCL Stage 3 read surfaced D2 + D18 ALREADY LOCKED — pivoted to execution plan |
| `udm-design-reviewer` (agent) | 2026-05-17 (Phase 1 review) | PS-1 + PS-8 mandatory | Agent `a04ff0da8f7a69993` (40th cumulative); 8-question architectural review; 🔴 2 BLOCK + 🟡 6 IMPROVE + 6 B-N candidates + 3 risk candidates |
| `udm-data-engineer-review` (agent) | 2026-05-17 — FAILED | PS-1 implicit | Agent type NOT registered in `.claude/agents/` despite being in PLANNING_DISCIPLINE matrix — infrastructure gap (B-N candidate); design-reviewer scope substituted for pipeline-mechanics review |
| `udm-decision-recorder` (skill) | DEFERRED | PS-8 mandatory | D2 + D18 already locked; no NEW D-N this plan (unless plan execution surfaces revisit) |
| `udm-edge-case-validator` (skill) | 2026-05-17 (inline) | PS-1 implicit | Walked SCD2-P1-* invariants + E-2 + B-4 + P0-8 + D15 against Parquet-direct path |
| `udm-checks-and-balances` (skill) | scheduled at plan attestation | PS-1 + PS-8 mandatory | 5-gate validation before plan 🟢 lock |
| `udm-gap-check` (skill) | scheduled at plan attestation | always-mandatory §2.3 | Independent gap-check reviewer at plan attestation |
| `udm-progress-logger` (skill) | 2026-05-17 (throughout) | always-mandatory §2.3 | Tracker updates throughout |
| `udm-post-edit-verification` (skill) | this commit | always-mandatory §2.3 per hard rule 14 | TEST + GAP + REVIEW cascade for this plan deliverable |

**Sub-agents spawned + skill inheritance** (per CLAUDE.md hard rule 13):

| Sub-agent | Spawned at | Skills inherited |
|---|---|---|
| udm-design-reviewer (Q1-Q8 architectural review) | 2026-05-17 (40th cumulative; agentId `a04ff0da8f7a69993`) | udm-checks-and-balances 5-gate + udm-edge-case-validator + udm-data-engineer-review awareness + udm-gap-check + superpowers-verification-before-completion |
| udm-data-engineer-review (pipeline mechanics) | 2026-05-17 — FAILED (agent type not registered) | N/A |

**Infrastructure gap surfaced** (tracked as B-339 below): `udm-data-engineer-review` is listed in `PLANNING_DISCIPLINE.md` matrix as an agent but is NOT registered in `.claude/agents/`. Either the matrix should be amended to remove it OR the agent should be authored.

---

## §1. Background & current state

### §1.1 D2 + D18 are LOCKED (not under brainstorm)

**D2** (`03_DECISIONS.md` L17, 🟢 Locked): "Remove the `UDM_Stage.{Source}.{Table}_cdc` tables. Pipeline writes a Parquet snapshot per run directly to the network drive; SCD2 promotion reads the in-memory DataFrame and compares against Bronze active rows. Stage no longer exists as a layer."

**D18** (`03_DECISIONS.md` L223, 🟢 Locked): "Move these existing defenses from `cdc/engine.py` into `scd2/engine.py`: `cdc/source_verifier.py::verify_deletes_against_source` + E-12 phantom-update ratio monitoring."

### §1.2 Project is GREENFIELD (per Phase 0 note)

`02_PHASES.md` L5: "This is an initial build, not a migration. There is no legacy Stage layer to cut over from."

**Critical clarification**: even though it's greenfield, the CURRENT implementation has Stage tables in code (`cdc/engine.py` + BCP→UDM_Stage in happy path) because Phase 2 (Pilot ACCT) + Phase 3 (Large Tables) have NOT been executed yet. D2 is the TARGET architecture; current code is the pre-D2 implementation that needs to be cut over BEFORE pilot ACCT runs in production.

### §1.3 User-binding constraints (this plan must honor)

1. **Parquet files = daily snapshot** of source data (canonical extraction artifact; per-day partition)
2. **Blob storage** (H drive primary per D107 + VendorFile secondary) = **SOURCE OF TRUTH** (regulator-grade record; UDM_Bronze is downstream consumer)
3. **SCD2 corruption recovery MUST be possible from MONTHS-OLD Parquet** (long-horizon replay; ops can refer to Parquet from months ago to solve SCD2 issues)
4. **Large-table scale**: 3B records in a single table; months of Parquet must be processable for SCD2 reconstruction

### §1.4 What needs to be built (gap analysis)

| Capability | Current state | Required for D2/D18 |
|---|---|---|
| Per-day Parquet write | ✅ EXISTS (`data_load/parquet_writer.py`; D16 stage-check-exchange) | KEEP |
| Single-snapshot Parquet replay | ✅ EXISTS (`data_load/parquet_replay.py::replay_parquet_snapshot`) | KEEP |
| **Multi-day ordered Parquet replay** | ❌ MISSING | **NEW: `replay_parquet_range()` per Reviewer Q1 🔴 BLOCK** |
| Small-table Parquet write in happy path | ❌ MISSING (orchestration/small_tables.py doesn't call write_parquet_snapshot) | **NEW: add Parquet write per Reviewer Gap B** |
| SCD2 reads from in-memory DataFrame (no Stage) | ✅ EXISTS (scd2/engine.py takes df_current) | KEEP |
| Stage table WRITES in happy path | ✅ EXISTS — **MUST BE REMOVED** | DELETE: `cdc/engine.py` + BCP→Stage path |
| `cdc/engine.py` Stage-based change classification | ✅ EXISTS — **MUST BE REMOVED** | DELETE per D2 |
| `_row_hash` injection location | Currently in CDC layer | **MOVE to extraction-time** (before Parquet write) |
| NULL PK filter (P0-4) | Currently in CDC layer | **MOVE to SCD2 input validation** |
| Source verifier invocation | Currently in CDC engine | **MOVE to SCD2 via `source_verifier_fn` closure** per D18 + Reviewer Q7 🔴 BLOCK |
| E-12 phantom-update ratio | Currently in CDC engine | **MOVE to SCD2** per D18 |
| Operator query of recent changes | `SELECT * FROM UDM_Stage.*` | **NEW: `tools/query_parquet.py` CLI** per Reviewer Q5 |
| Reconciliation (P3-4) | Stage vs source | **CHANGE to Bronze vs source** per Reviewer Q4 (Parquet-vs-source rejected as too costly at 3B-row scale) |

---

## §2. Architecture: D2 + D18 target state

### §2.1 Happy path (post-D2)

```
Source (Oracle / SQL Server)
        ↓
Python Pipeline (Linux RHEL)
   1. Extract (Polars + ConnectorX / oracledb; with NULL PK filter + _row_hash injection here, not CDC layer)
   2. PII tokenize via vault SP-1
   3. Sanitize + add _extracted_at
        ↓
   [PARALLEL FORK]
        ├──→ Parquet on H drive (canonical; stage-check-exchange per D16)
        │    └──→ ParquetSnapshotRegistry INSERT (Status='created')
        │    └──→ VendorFile async-replicated copy per D107
        │
        ├──→ SCD2 promotion (scd2/engine.py)
        │    1. Read active Bronze rows (full for small; PK-scoped for large via P1-3)
        │    2. Compare df_current (from Polars in-memory; SAME DataFrame written to Parquet) vs Bronze active
        │    3. Detect: NEW INSERTS / CLOSES / NEW_VERSIONS / UNCHANGED / RESURRECTIONS
        │    4. **D18: invoke source_verifier_fn(candidate_deletes)** before closing on candidate deletes
        │    5. **D18: emit E-12 phantom-update ratio in SCD2_PROMOTION metadata** if exceeds threshold
        │    6. 3-step atomic write (E-2): INSERT Flag=0 → close old → activate new
        │    7. B-4 orphan cleanup at start of run
        │
        └── NO STAGE WRITE (Stage tables DELETED per D2)
```

### §2.2 Replay path (post-D2; SCD2 corruption recovery)

```
Operator detects Bronze corruption / drift
        ↓
Diagnose: tools/validate_scd2.py (existing) + new tools/diagnose_parquet_bronze_gap.py (replaces stage_bronze diagnostic)
        ↓
Operator invokes: tools/scd2_replay_smoke.py --source DNA --table ACCT --start-date 2026-01-01 --end-date 2026-06-30 (NEW range mode)
        ↓
data_load/parquet_replay.replay_parquet_range(source, table, start_date, end_date)  [NEW]
   1. Query ParquetSnapshotRegistry for snapshots in REPLAY_ELIGIBLE_STATUSES, BusinessDate ASC
   2. B-4 orphan cleanup ONCE at start (NOT per day per Reviewer guidance)
   3. For each day's snapshot in BatchId ASC order:
      a. ledger_step(BatchId=replay_batch, EventType='PARQUET_REPLAY', day=N)
      b. SHA verify against registry
      c. Load Parquet → df_current
      d. Call scd2/engine.run_scd2_targeted(df_current, source_begin_date=day.business_date)
         (preserves SCD2-P1-b chained source end date invariant)
      e. ledger_step complete; resumable on crash
   4. Final: validate_scd2.py confirms invariant restored
```

### §2.3 Layer responsibility matrix (post-D2)

| Layer | Before D2 | After D2 |
|---|---|---|
| Source extraction | extract/ | extract/ (+ `_row_hash` injection moved here) |
| Stage | UDM_Stage tables + cdc/engine.py | **DELETED** |
| Parquet write | data_load/parquet_writer.py | data_load/parquet_writer.py (extended to small-table path) |
| SCD2 promotion | scd2/engine.py reading from Stage | scd2/engine.py reading from in-memory DataFrame OR Parquet (via replay) |
| Verify-before-close | cdc/source_verifier.py invoked from cdc/engine.py | cdc/source_verifier.py invoked from scd2/engine.py via `source_verifier_fn` closure per D18 |
| E-12 phantom-update | CDC engine logging | SCD2Result + SCD2_PROMOTION metadata per D18 |
| Operator query | `SELECT * FROM UDM_Stage.*` | `tools/query_parquet.py` CLI (NEW) |
| Reconciliation | Stage vs source | Bronze vs source (keep current pattern; skip Stage) |

---

## §3. Implementation phases

### §3.1 Phase 2 R1 (ACCT pilot — small-table D2 execution) — **HIGHEST PRIORITY**

**Pilot table**: DNA.osibank.ACCT (1.2M rows; per D104; small-table)

**Deliverables**:
1. **`replay_parquet_range()`** in `data_load/parquet_replay.py` — sequential per-day with ledger_step gating; B-4 cleanup ONCE at range start; preserves SCD2-P1-b chain (B-N #1 below)
2. **Add Parquet write to `orchestration/small_tables.py`** — small-table path currently lacks `write_parquet_snapshot()` call (B-N #4 below)
3. **D18 source_verifier_fn closure**: `run_scd2(source_verifier_fn=...)` parameter; orchestrator assembles closure; `CDC_VERIFY_STRICT_ON_FAILURE` env var read in orchestrator (B-N #3 below)
4. **(2026-05-19 D125 amendment per `UDM_PIPELINE_CDC_MODE_3WAY_DISPATCH_PLAN_2026-05-19.md`)** ~~Delete Stage write path from `orchestration/small_tables.py` — surgical removal of BCP→UDM_Stage path~~ — **AMENDED 2026-05-19**: Stage write path RETAINED during migration period for `CDCMode IN ('change_detect', 'both')` dispatch values (per D125 + B-544 3-mode dispatch wiring). Full Stage path removal deferred to Phase 2 R4+ AFTER all production tables successfully on `'parquet_snapshot'` for ≥90 days per RB-16 procedure (B-547). D2 original intent of "surgical removal of BCP→UDM_Stage" is preserved as eventual end-state; this commit just adds a validation window via 'both' mode shadow-write
5. **IdempotencyLedger SUPERSEDED status** (or NEW `EventType='SCD2_PROMOTION_D2'`) for ACCT migration boundary — prevents false-short-circuit on replay (B-N #6 below)
6. **`tools/query_parquet.py` CLI** — operator query migration (B-N #5 below)
7. **Update CLAUDE.md Structure + L207 CLI_* family registry** — `CLI_QUERY_PARQUET` (25th member)
8. **Tier 0 + Tier 1 tests** for all new code paths
9. **Validation gate**: ACCT runs end-to-end without Stage; SCD2 invariants preserved; Bronze identical to pre-D2 implementation

**Effort estimate**: ~2-3 cycles (multiple sub-tasks; multi-agent team)

**Risk profile**: MEDIUM (small dataset; fast iteration; bug blast radius bounded)

### §3.2 Phase 3 R1 (smallest large-table — D2 large-table execution)

**Pilot table per Phase 3 plan**: "lowest daily-row large table available" (NOT ACCT/CARDTXN/AuditLog yet)

**Prerequisites**: Phase 2 R1 ACCT pilot ⚫ CLOSED (D2 proven on small-table first)

**Deliverables**:
1. `cdc/range_scheduler.py` integrated for windowed large-table (already in Phase 3 plan)
2. `cdc/extraction_state.py::trust_gate_window()` (already in Phase 3 plan)
3. SCD2 windowed delete detection via PipelineExtraction trust gate (already in Phase 3 plan)
4. `replay_parquet_range()` proven at small-large-table scale (~10-50M rows)
5. MaxRowsPerDay enforcement verified for large tables (per Reviewer Q2)
6. **H drive capacity verification** — measure_capacity_and_partition.py runs for pilot large table; capacity projection per 7-year retention recorded (B-N #2 below)
7. 2-week soak
8. Validation gate per `02_PHASES.md` L185

**Effort estimate**: ~2-3 cycles + 2-week soak

**Risk profile**: MEDIUM (proven small-table pattern; new scale; capacity unknown until measured)

### §3.3 Phase 3 R2+ (larger large-tables progressively)

**Sequence**: small large-table → medium large-table → ACCT/CARDTXN → AuditLog (3B+ rows)

**Per-table per-cycle deliverables**:
1. Capacity verification before enablement
2. MaxRowsPerDay tuned per table
3. Source-DB load testing during peak windows
4. Replay smoke test for backfill scenario
5. 1-week soak per cohort

**Risk profile**: HIGH at ACCT/CARDTXN/AuditLog scale (3B+ rows; capacity may exceed H drive; memory cliff at ~250M-row daily delta per Reviewer Q2)

---

## §4. Multi-day Parquet replay engine (`replay_parquet_range`)

### §4.1 Design (per Reviewer Q1)

```python
def replay_parquet_range(
    source: str,
    table: str,
    start_date: date,
    end_date: date,
    *,
    output_dir: Path,
    table_config: TableConfig,
    source_verifier_fn: Callable | None = None,  # D18 per Reviewer Q7
) -> ReplayRangeResult:
    """Multi-day ordered Parquet replay for SCD2 corruption recovery.

    Per Reviewer Q1: sequential per-day is the ONLY option that preserves
    SCD2-P1-b chained source end dates. Sharded + batched-window violate
    the chain invariant. Snowflake-side replay violates D3 + budget.

    Per Reviewer Edge Case #1 (E-2 during multi-day replay): B-4 cleanup
    ONLY at range start (not per day) — otherwise it deletes in-flight
    rows the previous day just wrote for next-day activation.

    Args:
        source / table: target Bronze table
        start_date / end_date: inclusive replay window (BusinessDate)
        output_dir: staging dir for BCP CSVs
        table_config: per UdmTablesList; includes scd2_date_columns, MaxRowsPerDay
        source_verifier_fn: closure over source connection per D18 (optional;
            if None, verify-before-close skipped; CDC_VERIFY_STRICT_ON_FAILURE
            behavior preserved via env var read in orchestrator)

    Returns:
        ReplayRangeResult with per-day counts + total + per-day status
    """
    result = ReplayRangeResult()

    # Query registry for eligible snapshots in BatchId ASC
    snapshots = query_snapshots_in_range(
        source, table, start_date, end_date,
        status_in=REPLAY_ELIGIBLE_STATUSES,  # ('verified', 'replicated', 'archived')
        order_by="BatchId ASC",  # CRITICAL: preserves SCD2-P1-b chain
    )

    # B-4 orphan cleanup ONCE at range start (per Reviewer guidance)
    _cleanup_orphaned_inactive_rows(table_config.bronze_full_table_name, table_config)

    # Sharded sp_getapplock on (source, table) — concurrent replay prevention
    with replay_table_lock(source, table):
        for snapshot in snapshots:
            with ledger_step(
                batch_id=snapshot.batch_id,
                source_name=source,
                table_name=table,
                event_type="PARQUET_REPLAY",  # B-231: harmonize 'REPLAY' vs 'PARQUET_REPLAY'
            ) as step:
                if step.action == "skip":
                    # Already COMPLETED — replay resumable from this point
                    continue

                # SHA verify
                if not _verify_sha(snapshot):
                    step.fail("SHA mismatch")
                    raise RegistryHashMismatch(snapshot.file_path)

                # Load Parquet to df_current
                df_current = pl.read_parquet(snapshot.file_path)

                # SCD2 with source_begin_date = snapshot business_date
                # Preserves SCD2-P1-b chained source end dates per Reviewer Q1
                scd2_result = run_scd2_targeted(
                    table_config=table_config,
                    df_current=df_current,
                    pk_columns=table_config.pk_columns,
                    output_dir=output_dir,
                    target_date=snapshot.business_date,
                    source_begin_date=snapshot.business_date,  # critical
                    source_verifier_fn=source_verifier_fn,  # D18
                )

                result.per_day.append((snapshot.business_date, scd2_result))
                result.total_inserts += scd2_result.inserts
                result.total_new_versions += scd2_result.new_versions
                result.total_closes += scd2_result.closes

                step.complete()

    return result
```

### §4.2 Performance at 3B-row scale (per Reviewer Q3)

For 6-month replay of 3B-row table at 1% daily change:
- Initial backfill: ~300 GB ZSTD-3 (one-time)
- 180 daily Parquets × ~3 GB = ~540 GB total
- Per-day SCD2: 30M-row delta vs Bronze active (PK-scoped via P1-3 staging join)
- Per-day cost: ~30M PK staging-join lookups against 3B Bronze
- Total replay: ~5.4B Bronze lookups for full 180-day replay
- **Estimated wall-clock**: 24-48 hours for 180-day full replay on RHEL Linux at expected BCP + SQL Server throughput

**This is acceptable for corruption recovery scenarios** (which are rare; multi-day RTO is consistent with `01_ARCHITECTURE.md` L181 "days for 3B-row table").

**Optimization candidates** (defer to Phase 4+):
- Sharded replay across non-overlapping PK ranges (parallel; preserves chain if shards are disjoint)
- Batched-window replay (process 7-day chunks; fewer Bronze writes — but RISKS SCD2-P1-b chain unless carefully designed)
- Snowflake-side replay (violates D3; reject)

### §4.3 Crash recovery during multi-day replay (per Reviewer Q7 + Edge Case #1)

**New scenario surfaced by Reviewer**: B-4 cleanup at per-day cadence would WRONGLY delete in-flight rows from previous day's activation. Mitigation: B-4 ONCE at range start.

**New scenario**: distinguishing "in-flight from current replay day" vs "orphaned from prior crashed replay". Mitigation: tag rows with `UdmModifiedBy = 'replay-batch-<id>'` to identify replay-context rows.

**Concurrent replay prevention**: `sp_getapplock` on (source, table) wrapping the replay orchestrator.

---

## §5. Large-table specific challenges (3B records + months of data)

### §5.1 Memory bound at 250M+ row daily delta (per Reviewer Q2)

For 3B-row table at 8% daily change (e.g., bulk update at source): 250M-row delta + Polars in-memory = ~50 GB → exceeds typical 32 GB server RAM.

**Mitigation**: `MaxRowsPerDay` config column in `UdmTablesList` MANDATORY for any 3B-row table. If a day's extraction exceeds the cap, day splits into multiple windows; each window's SCD2 stays memory-bounded.

**Phase 3 gate**: every 3B-row table must have `MaxRowsPerDay` set CONSERVATIVELY before enablement.

### §5.2 H drive capacity verification (per Reviewer Q3 — NEW RISK)

**Math** (Reviewer-corrected):
- 1 large table: ~840 GB per 6 months (300 GB initial + 540 GB incremental)
- 10 large tables: ~8.4 TB per 6 months
- 7-year full retention: ~80 TB for 10 large tables

**Phase 3 gate**: `tools/measure_capacity_and_partition.py` (Tool 16; BUILT 2026-05-12 per B190 closure) MUST run for each large table to verify capacity BEFORE enablement.

**Risk**: H drive capacity NOT documented in any planning artifact. Risk candidate per §11 below (will be assigned R-number upon plan approval).

### §5.4 Pre-execution gates (per 2026-05-17 pre-sign-off gap-check Agent `ae1476a588dd34e15` — CRITICAL)

**This plan's execution is GATED on resolving 2 CRITICAL gaps surfaced by independent gap-check reviewer 2026-05-17:**

- **G1 (CCPA + Parquet replay)**: naive `replay_parquet_range()` would mechanically defeat CCPA right-to-deletion by re-INSERTing Bronze rows referencing tokens with `PiiVault.Status='deleted_per_request'`. Design proposed: Option A4 time-aware replay per `docs/migration/D2_GAP_RESOLUTION_PLAN_2026-05-17.md` §2. Pending: R5 research integration (Agent `a959ee0434c90087b` background; CCPA/GDPR + immutable audit data legal classification) → lock D-N (tentative-future-D-N number assigned at lock) → implement per **B-341**. **GATES Phase 2 R1 ACCT pilot.**

- **G2 (Multi-table replay ordering)**: `replay_parquet_range()` per-(source, table) cannot preserve FK integrity for multi-table corruption recovery. Design proposed: Option B1 cross-table BatchId-aligned replay per `docs/migration/D2_GAP_RESOLUTION_PLAN_2026-05-17.md` §3 → implement per **B-342**. **GATES Phase 3 R1 large-table pilot** (single-table ACCT pilot Phase 2 R1 can proceed without).

**Plan sign-off authorizes APPROACH; execution requires B-341 + B-342 + B-343 + B-344 + B-345 resolution per gap-resolution plan §7.3 + §7.4.**

### §5.3 Schema evolution during 6-month replay (per Reviewer Q8 not explicitly addressed; SURFACE here)

If source schema changes mid-replay window:
- Old Parquet has old schema (per D-N Parquet-schema-frozen-at-write)
- New Parquet has new schema
- Bronze schema is current (latest)

**Industry pattern**: Iceberg schema evolution / Delta Lake column mapping handle this via per-file schema tracking.

**For our case** (greenfield + 1 Bronze schema at a time): replay must use Polars schema-promotion (per W-7 `validate_schema_before_concat()`) when reading multi-day Parquet with schema drift. New edge case to author: **"Replay across schema-evolution boundary"** (would land as I-N or S-N).

---

## §6. D18 source-verifier integration (`source_verifier_fn` closure pattern)

Per Reviewer Q7 🔴 BLOCK: D18 source coupling is deeper than the decision describes. Implementation:

```python
# scd2/engine.py — updated signature
def run_scd2_targeted(
    table_config: TableConfig,
    df_current: pl.DataFrame,
    pk_columns: list[str],
    output_dir: str | Path,
    *,
    target_date: date | datetime | None = None,
    source_begin_date: date | datetime | None = None,
    source_verifier_fn: Callable[[pl.DataFrame], VerifyResult] | None = None,  # NEW per D18
) -> SCD2Result:
    ...
    # Before closing on candidate deletes (existing logic):
    if df_closed_pks and source_verifier_fn is not None:
        verify_result = source_verifier_fn(df_closed_pks)
        # CDC_VERIFY_STRICT_ON_FAILURE env var read in orchestrator + forwarded via closure
        if verify_result.failed_with_strict:
            # Suppress close; will retry next cycle
            df_closed_pks = df_closed_pks.filter(~pl.col("pk").is_in(verify_result.uncertain))
    ...
    # E-12 phantom-update ratio (existing CDC logic moved here):
    if result.unchanged > 0 and (result.unchanged / (result.new_versions + result.unchanged)) > E12_THRESHOLD:
        logger.warning("E-12: phantom-update ratio %.2f exceeds threshold for %s",
                       ratio, table_config.source_object_name)
        # Emit as SCD2_PROMOTION metadata
```

```python
# orchestration/small_tables.py + orchestration/large_tables.py — updated invocation
from cdc.source_verifier import verify_deletes_against_source
from sources import get_source_cursor

def _process_table(table_config: TableConfig):
    source_cursor = get_source_cursor(table_config.source_name)

    def source_verifier_fn(candidate_pks: pl.DataFrame) -> VerifyResult:
        return verify_deletes_against_source(
            source_cursor, candidate_pks,
            source_table=table_config.source_object_name,
            strict_on_failure=os.environ.get("CDC_VERIFY_STRICT_ON_FAILURE", "1") == "1",
        )

    run_scd2_targeted(
        table_config=table_config,
        df_current=df_current,
        pk_columns=table_config.pk_columns,
        output_dir=output_dir,
        target_date=target_date,
        source_begin_date=target_date,
        source_verifier_fn=source_verifier_fn,
    )
```

**Critical**: `cdc/source_verifier.py` module STAYS (its unit tests + `CDC_VERIFY_MAX_CANDIDATES` ceiling logic are valuable). Only the INVOCATION POINT moves from CDC to SCD2.

---

## §7. Reconciliation strategy (per Reviewer Q4)

**Decision**: P3-4 column-by-column reconciliation = **Bronze vs source** (NOT Parquet vs source).

**Rationale**:
- Parquet-vs-source via DuckDB at 3B-row scale is multi-hour query (too costly for daily/weekly cadence)
- Bronze active rows ALREADY materialize "current state" — SQL Server can answer reconciliation queries with indexes
- Parquet remains for the LONG-HORIZON AUDIT case ("what did the source say on date X?") — that's the point of keeping Parquet

**Use Parquet for**: SCD2 corruption recovery (replay) + per-batch audit queries + Snowflake federation (Phase 5).

**Use Bronze for**: daily/weekly reconciliation (P3-4 + B-11 boundary reconciliation).

---

## §8. Operator query migration

Per Reviewer Q5: build `tools/query_parquet.py` (NEW; D74/D75/D76 contract).

**Why NOT PolyBase**: SQL Server 2022 PolyBase has known operational complexity (connector instability + credential management + Kerberos constraints on network drives). Introducing PolyBase creates new ops dependency. **REJECT per Reviewer.**

**Why NOT DuckDB CLI**: requires every operator to install DuckDB + know UNC path patterns. Too much friction for DBAs.

**Build `tools/query_parquet.py`**:
- Wraps DuckDB OR Polars (TBD; perf test at build time)
- Operator passes: `--source DNA --table ACCT --start-date 2026-01-01 --end-date 2026-06-30 --filter "_cdc_operation='D'" --output json|csv|tsv`
- DBA-friendly output (matches `SELECT *` muscle memory)
- D74 exit codes / D75 dry-run / D76 audit row to PipelineEventLog
- EventType: `CLI_QUERY_PARQUET` (25th CLI_* family member)
- Tier 0 + Tier 1 tests

---

## §9. Edge case walk (SCD2 invariants under Parquet-direct)

| Invariant | Preserved under D2? | Mechanism |
|---|---|---|
| SCD2-P1-a: dual date pair | ✅ | Unchanged; `UdmEffective/EndDateTime` = load time; `UdmSourceBegin/EndDate` = business time |
| SCD2-P1-b: chained source end dates | ✅ (preserved by `replay_parquet_range` sequential per-day per Reviewer Q1) | `source_begin_date=snapshot.business_date` per day; chain holds |
| SCD2-P1-c: active-row sentinel `'2999-12-31'` | ✅ | Unchanged; SCD2 engine writes sentinel |
| SCD2-P1-e: orphan marker BOTH predicates | ✅ | B-4 cleanup unchanged; runs ONCE at replay range start (per Reviewer) |
| SCD2-P1-f: datetime precision + tz invariant | ✅ | Polars `_cdc_now_ms()` unchanged |
| SCD2-R2-a: per-row source waterfall | ✅ | `UdmTablesList.scd2_date_columns` unchanged |
| SCD2-R4: three-value flag | ✅ | E-2 3-step write unchanged |
| E-2: 3-step atomic write | ✅ | Unchanged in `scd2/engine.py` |
| P0-8: INSERT-first then UPDATE | ✅ | Unchanged |
| B-4: orphan cleanup | ✅ (modified: ONCE per replay range, not per day) | Per Reviewer guidance |
| D15: master idempotency | ✅ | `ledger_step()` per replay day + UNIQUE registry constraints |

### §9.1 NEW edge cases introduced by D2 (candidates for `04_EDGE_CASES.md`)

- **D2-EC1**: Multi-day replay crash between day N activation + day N+1 INSERT — B-4 cleanup MUST NOT delete day N's activation work. Mitigated via "B-4 once at range start" rule. **Tag rows with `UdmModifiedBy='replay-batch-<id>'`** to distinguish replay-in-flight from prior-crash-orphan.
- **D2-EC2**: Concurrent `replay_parquet_range()` on same (source, table) — `sp_getapplock` wraps replay orchestrator.
- **D2-EC3**: IdempotencyLedger old `EventType='CDC_PROMOTION'` rows from pre-D2 era cause false-short-circuit on first post-D2 replay. Mitigation: either `Status='SUPERSEDED'` new status OR new `EventType='SCD2_PROMOTION_D2'` for post-D2 ledger rows.
- **D2-EC4**: Schema evolution mid-replay (Parquet old schema vs Bronze new schema). Mitigation: Polars schema-promotion via W-7 `validate_schema_before_concat()`.

---

## §10. B-N candidate enumeration

Per Reviewer; renumbered to avoid B-N sequence collision (current open B-N high = B-331):

| B-N | Description | WSJF | Phase |
|---|---|---|---|
| **B-332** | Author `replay_parquet_range(source, table, start_date, end_date)` in `data_load/parquet_replay.py` (multi-day SCD2 replay; sequential per-day; ledger_step gating; B-4 once at range start; SCD2-P1-b chain preserved) | 1.7 | Phase 2 R1 prerequisite (BEFORE Phase 3) |
| **B-333** | Record H drive actual capacity + 7-year Parquet footprint projection as Phase 3 gate; run `tools/measure_capacity_and_partition.py` for representative large table; document in `02_PHASES.md` | 4.0 | Before Phase 3 plan authored |
| **B-334** | Add `source_verifier_fn: Callable \| None = None` parameter to `run_scd2` + `run_scd2_targeted`; orchestrators pass closure over source connection; `CDC_VERIFY_STRICT_ON_FAILURE` read in orchestrator + forwarded; D18 implementation | 2.0 | Phase 2 R1 (ACCT pilot exercises new call site) |
| **B-335** | Author `tools/query_parquet.py` (D74/D75/D76 contract; `EVENT_TYPE='CLI_QUERY_PARQUET'`; DuckDB or Polars wrapper; filters by source/table/date/_cdc_operation; DBA-friendly output) | 1.5 | Phase 2 R3 (production cutover; ops needs before Stage decommissioning) |
| **B-336** | Add `parquet_writer.write_parquet_snapshot()` call to `orchestration/small_tables.py` (D2 gap: small-table path has no Parquet write today) | 2.5 | Phase 2 R1 (ACCT is a small-table pilot) |
| **B-337** | Record IdempotencyLedger row expiration strategy for pre-D2 → post-D2 cutover; either `Status='SUPERSEDED'` new status OR new `EventType='SCD2_PROMOTION_D2'`; prevents false-short-circuit on first post-cutover replay | 4.0 | Phase 2 R1 ACCT cutover (must be resolved BEFORE first post-cutover replay) |
| **B-338** | Author `tools/diagnose_parquet_bronze_gap.py` replacing `tools/diagnose_stage_bronze_gap.py` for post-D2 diagnostic surface (5 theory categories adapted to Parquet vs Bronze) | 1.5 | Phase 2 R2 (post-pilot diagnostic readiness) |
| **B-339** | Author `udm-data-engineer-review` agent at `.claude/agents/udm-data-engineer-review.md` — currently listed in PLANNING_DISCIPLINE.md matrix as agent type but NOT registered; infrastructure gap surfaced this session | 2.0 | Opportunistic |
| **B-340** | Author 4 NEW edge case entries (D2-EC1 through D2-EC4) in `docs/migration/04_EDGE_CASES.md` for D2-introduced scenarios | 1.0 | Phase 2 R1 close-out |

---

## §11. Risk delta

**Risk candidates pending pipeline-lead sign-off** (will land in RISKS.md upon plan approval; R-numbers TBD per next available in RISKS.md sequence):

| Candidate | Description | Status |
|---|---|---|
| **Risk-NEW-A** | Multi-day replay engine does not exist; SCD2-invariant-preserving ordered replay at 3B-row scale is unproven | 🟡 Medium × High = 6; mitigation: implement `replay_parquet_range()` as Phase 2 R1 prerequisite (B-332) BEFORE Phase 3 |
| **Risk-NEW-B** | H drive capacity for 10 large tables at 7-year retention is ~80 TB and NOT verified against actual drive sizing | 🟡 Medium × High = 6; mitigation: record actual capacity as Phase 3 gate (B-333) |
| **Risk-NEW-C** | D18 source coupling — wiring source connections into SCD2 layer changes every `run_scd2_targeted` call site in `orchestration/`; risk of regression at unupdated call sites | ⚪ Low × Medium = 2; mitigation: `source_verifier_fn` parameter pattern; grep all call sites before plan executes (B-334) |
| **Risk-NEW-D** (added 2026-05-17 per pre-sign-off gap-check G1) | **CCPA + Parquet replay interaction unresolved** — naive replay would re-INSERT Bronze rows referencing tokens whose `PiiVault.Status='deleted_per_request'`, mechanically defeating CCPA right-to-deletion = compliance breach risk | 🟡 Medium × **High** = 6; mitigation: G1 design Option A4 time-aware replay per `D2_GAP_RESOLUTION_PLAN_2026-05-17.md` §2 + B-341 CRITICAL; pending R5 legal research integration |
| **R15 ESCALATION candidate** | DR drill scenarios reveal Bronze rebuild gaps — 80 TB Parquet footprint × 7-year retention + D110 DC-loss-no-DR posture means replay-from-scratch after DC loss requires source re-extraction (may not be possible 7 years later) | Severity increases from Medium × Medium = 4 → escalate to Medium × High = 6 |
| **R02 DE-ESCALATION candidate** | Round 0.5 spike untested — execution plan context confirms D2 design is stable; spike scope narrows to connection factory + tokenization integration only | severity reduces |
| **R01 watch** | Phase 0 deliverables completion — H drive capacity gap may re-escalate this when Phase 3 encounters storage constraint | watch |

---

## §12. Acceptance criteria + sign-off

### §12.1 Plan acceptance (this document)

- [ ] Pipeline lead reviews + signs off below
- [ ] `udm-gap-check` independent reviewer at plan attestation (scheduled)
- [ ] `udm-checks-and-balances` 5-gate at plan attestation (scheduled)
- [ ] 9 B-N candidates opened in BACKLOG.md (B-332 through B-340)
- [ ] 3 risk candidates opened in RISKS.md (Risk-NEW-A/B/C from §11 above; R-numbers assigned per next-available; plus R15 escalation + R02 de-escalation)
- [ ] 4 D2-EC edge cases authored in 04_EDGE_CASES.md

### §12.2 Phase 2 R1 execution acceptance

- [ ] B-332 (replay_parquet_range) BUILT + tests pass
- [ ] B-336 (small-table Parquet write) BUILT + tests pass
- [ ] B-334 (source_verifier_fn closure) BUILT + tests pass
- [ ] B-337 (IdempotencyLedger SUPERSEDED) IMPLEMENTED
- [ ] ACCT pilot runs end-to-end without Stage write
- [ ] SCD2 invariants verified preserved (Reviewer table §9 walked)
- [ ] Bronze output byte-identical to pre-D2 implementation (regression check)
- [ ] 1-week soak

### §12.3 Phase 3 R1 execution acceptance

- [ ] B-333 (H drive capacity verification) RECORDED
- [ ] Smallest large-table selected per Phase 3 plan
- [ ] `replay_parquet_range()` proven at small-large-table scale (~10-50M rows)
- [ ] 2-week soak per Phase 3 plan

### §12.4 Sign-off

🟡 **DRAFT 2026-05-17** by parent agent (orchestrator role) + reviewer Agent `a04ff0da8f7a69993` (40th cumulative; 🔴 2 BLOCK + 🟡 6 IMPROVE; all addressed in this plan).

**Pipeline lead sign-off**: [ ] APPROVED / [ ] REDIRECT / [ ] BLOCK
**Date**: ___________
**Signature**: dougmorrow@protonmail.com

---

## §13. Cross-references

- `docs/migration/03_DECISIONS.md` D2 + D4 + D16 + D17 + D18 + D25 + D107 + D110 + D104
- `docs/migration/01_ARCHITECTURE.md` § 1-4 (layer responsibilities + idempotency contract + failure recovery)
- `docs/migration/02_PHASES.md` Phase 2 + Phase 3 + Phase 4 deliverables
- `docs/migration/phase1/01c_data_flow_walkthrough.md` § 3 (per-table inner loop)
- `docs/migration/CLAUDE_GOTCHAS.md` SCD2-P1-* + SCD2-R* + E-2 + P0-8 + B-4 + D15
- `scd2/engine.py` (1800+ lines; `run_scd2` + `run_scd2_targeted`)
- `data_load/parquet_writer.py` + `data_load/parquet_replay.py` (existing single-snapshot; B-332 extends to range)
- `cdc/source_verifier.py` (MOVES from CDC to SCD2 invocation per D18; module stays)
- `tools/scd2_replay_smoke.py` (existing; extended to range mode per B-332)
- Independent reviewer Agent `a04ff0da8f7a69993` (40th cumulative; udm-design-reviewer) verdict citation throughout

---

**Awaiting pipeline-lead sign-off** before Phase 2 R1 execution begins.
