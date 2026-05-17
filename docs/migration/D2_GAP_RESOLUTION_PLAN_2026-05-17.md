# D2 Gap Resolution Plan — Comprehensive Pre-Sign-off Addendum

**Date**: 2026-05-17
**Author**: pipeline lead + parent agent (orchestrator role) + reviewer Agent `ae1476a588dd34e15` (41st cumulative; udm-gap-check 6-category) + researcher Agent `a959ee0434c90087b` (42nd cumulative; udm-researcher R5 CCPA/GDPR legal — IN PROGRESS background)
**Status**: 🟡 Draft — addresses 11 pre-sign-off gaps surfaced by 41st-cumulative reviewer; awaiting R5 research integration + pipeline-lead sign-off
**Scope**: comprehensive design for all 11 gaps (2 CRITICAL / 4 HIGH / 3 MEDIUM / 2 LOW) + 5 research dispatch + 10 B-N enumeration for `docs/migration/D2_EXECUTION_PLAN_PARQUET_DIRECT_SCD2_2026-05-17.md` sign-off readiness
**Parent plan**: `docs/migration/D2_EXECUTION_PLAN_PARQUET_DIRECT_SCD2_2026-05-17.md` (this is APPENDIX; not standalone)

---

## §0. Planning session provenance

**Skills invoked during this gap-resolution session** (extends parent D2 plan §0; same `udm-planning-session-startup` session per CLAUDE.md hard rule 13):

| Skill | Invoked at | Scope reference | Rationale |
|---|---|---|---|
| `udm-gap-check` (skill) | 2026-05-17 (Phase 2 pre-sign-off) | always-mandatory §2.3 | Independent gap-check Agent `ae1476a588dd34e15` (41st cumulative) returned 11 gaps; this plan addresses each |
| `udm-researcher` (agent) | 2026-05-17 (R5 dispatch) | PS-1 + PS-8 mandatory (PROMOTED from on-demand) | Agent `a959ee0434c90087b` (42nd cumulative) IN PROGRESS background; R5 CCPA/GDPR + immutable audit data legal grounding; informs G1 design |
| `udm-decision-recorder` (skill) | scheduled (G1 + G2 D-N candidates likely) | PS-8 mandatory | Will record D-N for G1 (CCPA + replay design) + possibly G2 (multi-table replay) post-research integration |
| `udm-checks-and-balances` (skill) | scheduled at plan attestation | PS-1 + PS-8 mandatory | 5-gate validation before plan 🟢 lock |
| `udm-edge-case-validator` (skill) | 2026-05-17 (inline) | PS-1 implicit | Will surface 4+ NEW edge cases from G1 + G2 designs (CCPA-replay-EC1; multi-table-replay-EC1, etc.) |
| `udm-gap-check` second-pass (skill) | scheduled post-plan-author | per D56 second-pass discipline | Independent reviewer on this gap-resolution plan |

**Sub-agents spawned + skill inheritance** (per CLAUDE.md hard rule 13):

| Sub-agent | Spawned at | Skills inherited |
|---|---|---|
| general-purpose (pre-sign-off gap-check) | 2026-05-17 (41st cumulative; agentId `ae1476a588dd34e15`) | udm-gap-check 6-category + edge case validator awareness |
| udm-researcher (R5 CCPA/GDPR legal) | 2026-05-17 (42nd cumulative; agentId `a959ee0434c90087b`; IN PROGRESS background) | udm-researcher 5-source minimum primary-source grounding |

---

## §1. Binding principle: **Idempotency**

Per user-direction 2026-05-17: "We must ensure idempotency."

### §1.1 Idempotency axes for D2 architecture

| Axis | Requirement | Mechanism |
|---|---|---|
| **SCD2 chain integrity** | Replay produces SAME Bronze chain state given SAME input Parquet snapshots | Hash compare on `_row_hash` vs `UdmHash`; conditional MERGE; deterministic per-row source waterfall (R-2) |
| **Replay determinism** | Re-running `replay_parquet_range()` produces SAME Bronze state regardless of when run | Per-day `ledger_step()` gating; SHA-256 SHA verify pre-read; B-4 once-at-range-start |
| **CCPA + replay interaction** | Replay across CCPA deletion events produces deterministic Bronze given the historical CcpaDeletionLog | **Option A4 (time-aware replay; §2 below)**: replay treats CCPA deletion as historical SCD2 close event |
| **Multi-table consistency** | Cross-table replay (FK-related tables) produces consistent Bronze across all tables in range | **Option B1 (cross-table BatchId-aligned; §3 below)**: process all tables for BatchId N before moving to BatchId N+1 |
| **Compaction + replay** | Replay against compacted-monthly Parquet produces SAME Bronze as replay against original-daily | Registry `superseded_by_registry_id` column; replay-dispatcher reads canonical (compacted OR original) per registry |

### §1.2 Idempotency-violating patterns to REJECT

- **Mutable Parquet** (e.g., CCPA deletion SP per RB-10 purges subject-PKs from Parquet at deletion time) → CONTRADICTS D2 immutability invariant + D16 stage-check-exchange. **REJECT.**
- **Replay-time mutable CcpaDeletionLog** (e.g., replay uses current vault state per-row at replay time) → non-deterministic across deletion events. **REJECT.**
- **Snapshot-based replay** (e.g., compute target Bronze for all tables as atomic transaction) → infeasible at 3B-row × 10-table scale + violates D3 (Python+Polars stays). **REJECT.**
- **Per-table independent replay without coordination** (e.g., parallel per-table replay without BatchId alignment) → cross-table FK inconsistency window during replay. **REJECT.**

### §1.3 Idempotency proofs (each gap's design includes proof)

Every gap design in §2-§4 below ends with an **idempotency proof** stanza demonstrating the design preserves all 5 axes above.

---

## §2. G1 Design: CCPA + Parquet replay (CRITICAL)

### §2.1 Problem statement (from Reviewer)

Plan's binding constraint "Parquet = SOURCE OF TRUTH for SCD2 corruption recovery" + RB-10 CCPA right-to-deletion mechanism collide. When CCPA deletion processes, `PiiVault.Status='deleted_per_request'` (crypto-shredding via token orphaning). But Parquet snapshots written BEFORE deletion contain the same tokens AND the source-side PII columns. **Naive replay would re-INSERT Bronze rows referencing tokens whose Status='deleted_per_request' — mechanically defeating right-to-deletion.**

### §2.2 Design: Option A4 — Time-aware replay (RECOMMENDED pending R5 research integration)

`replay_parquet_range()` consults `CcpaDeletionLog` as part of replay logic. When the replay window includes a date T where a CCPA deletion request was processed, the engine:

```python
def replay_parquet_range(
    source: str, table: str, start_date: date, end_date: date,
    *,
    ccpa_snapshot_as_of: datetime | None = None,  # NEW per G1 design
    ...
):
    # Capture CcpaDeletionLog snapshot at replay-time-of-record
    # (idempotency: same snapshot_as_of → same Bronze output)
    ccpa_snapshot_as_of = ccpa_snapshot_as_of or datetime.utcnow()
    ccpa_log = read_ccpa_deletion_log_as_of(ccpa_snapshot_as_of)

    # Per-day replay (sequential per Reviewer Q1 + SCD2-P1-b)
    for snapshot in snapshots:
        df_current = pl.read_parquet(snapshot.file_path)

        # G1 mechanism: filter rows against CcpaDeletionLog per BusinessDate
        # 3-case decision per row PK + token:
        # Case A: token in ccpa_log AND ccpa_request_date < snapshot.business_date
        #         → SKIP row (already deleted at this BusinessDate)
        # Case B: token in ccpa_log AND ccpa_request_date == snapshot.business_date
        #         → write SCD2 delete-close event (Flag=2; Op='D'; UdmSourceEndDate=BusinessDate)
        #         (synthesizes the deletion as historical SCD2 chain event)
        # Case C: token NOT in ccpa_log OR ccpa_request_date > snapshot.business_date
        #         → write row normally (deletion comes later in chain OR never)
        df_current_filtered, df_deletion_synthesized = _apply_ccpa_filter(
            df_current, ccpa_log, snapshot.business_date, pk_columns,
        )

        # Standard SCD2 promotion on filtered rows
        run_scd2_targeted(
            table_config=table_config,
            df_current=df_current_filtered,
            pk_columns=pk_columns,
            source_begin_date=snapshot.business_date,
            ...
        )

        # Append synthesized deletion events (rows for Case B)
        if not df_deletion_synthesized.is_empty():
            _apply_synthetic_ccpa_deletions(
                df_deletion_synthesized,
                bronze_table,
                source_end_date=snapshot.business_date,
            )
```

### §2.3 Net effect

Bronze chain shows the subject existed historically + was deleted on T per the CCPA request timeline. This is the **most CCPA-compliant + most truthful** historical record:
- Before T: subject has Flag=1 active row (visible in historical queries; tokenized PII)
- On T: subject row closed (Flag=2; Op='D'; UdmSourceEndDate=T)
- After T: subject does NOT appear in active Bronze (deletion respected)

### §2.4 Idempotency proof for G1

Given fixed `(source, table, start_date, end_date, ccpa_snapshot_as_of)`:
1. **CcpaDeletionLog snapshot** captured at `ccpa_snapshot_as_of` — IMMUTABLE per D26 append-only contract
2. **Parquet files** in range — IMMUTABLE per D16 stage-check-exchange
3. **Per-row filter decision** (Case A/B/C) — deterministic function of (token, ccpa_request_date, business_date)
4. **SCD2 promotion** — deterministic per existing engine (D15 master invariant)
5. **Synthesized deletion events** — deterministic per (PK, BusinessDate)

**Therefore**: re-running `replay_parquet_range(source, table, start_date, end_date, ccpa_snapshot_as_of=T)` produces BYTE-IDENTICAL Bronze for the range. Idempotent. ✅

### §2.5 Pending R5 research integration

Currently `udm-researcher` Agent `a959ee0434c90087b` is investigating:
- RQ1: tokenized-PII legal classification (personal data vs pseudonymized vs deidentified)
- RQ2: immutable audit data exemptions under GDPR Article 17(3)
- RQ3: replay capability legal exposure
- RQ4: industry patterns (Snowflake / Databricks / AWS / banking)
- RQ5: idempotency-preserving deletion design patterns

R5 findings will land at `docs/migration/_research/r5-ccpa-parquet-replay-legal-2026-05-17.md`. Findings may:
- CONFIRM Option A4 (time-aware replay) is industry-canonical → lock as D-N
- SURFACE legal/regulatory constraint requiring different design (e.g., subject must be truly absent post-deletion = cannot synthesize Flag=2 row)
- IDENTIFY safe-harbor pattern (e.g., crypto-shredding via vault Status='deleted' satisfies CCPA even with Parquet retaining tokens) → simplifies design

**G1 D-N candidate** (to be locked post-R5 integration): tentative **tentative-future-D-N** "CCPA + Parquet replay interaction — time-aware replay with CcpaDeletionLog as-of snapshot".

### §2.6 Edge cases introduced by G1

New edge case candidates (will land in `04_EDGE_CASES.md` per B-340):
- **CCPA-REPLAY-EC1**: replay across multiple CCPA deletion events for same subject — `ccpa_log.distinct(subject_id, request_date)` semantics; only earliest deletion event matters per subject
- **CCPA-REPLAY-EC2**: legal-hold OVERRIDES CCPA deletion (per RB-10 + D30); replay must respect `LegalHold=1` rows even if CCPA delete also processed
- **CCPA-REPLAY-EC3**: subject deletion + token reuse (different subject re-tokenized with same plaintext post-deletion — token mapping changes); replay must use ccpa_snapshot_as_of vault state
- **CCPA-REPLAY-EC4**: synthesized Flag=2 deletion event vs natural Bronze close event (existing Flag=2 from non-CCPA delete) — distinguishable via `UdmModifiedBy='ccpa-synth-replay-batch-<id>'` tag

---

## §3. G2 Design: Multi-table replay ordering (CRITICAL)

### §3.1 Problem statement (from Reviewer)

`replay_parquet_range()` is per-(source, table). For Bronze corruption spanning multiple tables with FK relationships (ACCT references CUST_ID; AUDITLOG references both), the engine has NO mechanism for dependency-order replay, cross-table batch boundaries, OR cross-table inconsistency window.

### §3.2 Design: Option B1 — Cross-table BatchId-aligned replay (RECOMMENDED)

NEW API:

```python
def replay_parquet_range_multi_table(
    tables: list[tuple[str, str]],  # [(source, table), ...]
    start_date: date,
    end_date: date,
    *,
    dependency_order: list[tuple[str, str]] | None = None,  # operator-supplied OR auto
    ccpa_snapshot_as_of: datetime | None = None,  # per G1 design
    ...
) -> MultiTableReplayResult:
    """Cross-table coordinated Parquet replay preserving FK integrity.

    Per Reviewer G2 design: process all tables for BatchId N before BatchId N+1.
    Per dependency_order: within a single BatchId, replay tables in FK-dependency
    order (parents before children).

    Idempotency: deterministic given (tables, start_date, end_date,
    dependency_order, ccpa_snapshot_as_of). Same inputs → byte-identical
    multi-table Bronze.
    """
    # Resolve dependency order (operator-supplied OR derive from UdmTablesList FK metadata)
    if dependency_order is None:
        dependency_order = _resolve_fk_dependency_order(tables)

    # Get unioned BatchId list across all tables in range
    all_batch_ids = sorted(_union_batch_ids(tables, start_date, end_date))

    # Cross-table lock (sp_getapplock spanning all tables in scope)
    with multi_table_replay_lock(tables):
        for batch_id in all_batch_ids:
            for source, table in dependency_order:
                # Skip if this table doesn't have a snapshot for this batch_id
                snapshot = lookup_snapshot(source, table, batch_id)
                if snapshot is None:
                    continue

                # Per-(batch_id, table) ledger step (resumable on crash)
                with ledger_step(
                    batch_id=batch_id,
                    source_name=source,
                    table_name=table,
                    event_type="PARQUET_REPLAY_MULTI",
                ) as step:
                    if step.action == "skip":
                        continue
                    # Standard replay for this (batch_id, table)
                    _replay_single_snapshot(snapshot, ccpa_snapshot_as_of=ccpa_snapshot_as_of)
                    step.complete()

    return MultiTableReplayResult(...)
```

### §3.3 FK dependency resolution

Two paths:
- **Operator-supplied**: pipeline lead specifies `dependency_order=[('DNA', 'CUST'), ('DNA', 'ACCT'), ('DNA', 'AUDITLOG')]` per understanding of FK structure
- **Auto-derived from UdmTablesList**: NEW column `UdmTablesList.ForeignKeyRefs NVARCHAR(MAX) NULL` listing referenced tables; topological sort produces order
  - D92 forward-only additive ALTER for the column
  - Optional: NULL = no FK refs; treat as root in dependency graph

### §3.4 Idempotency proof for G2

Given fixed `(tables, start_date, end_date, dependency_order, ccpa_snapshot_as_of)`:
1. **all_batch_ids** — deterministic per registry contents (immutable per D25)
2. **dependency_order** — operator-supplied OR derived deterministically from UdmTablesList
3. **Per-(batch_id, table) replay** — deterministic per G1 design (§2.4 proof)
4. **Cross-table coordination** — strict BatchId-ascending traversal preserves chain integrity within each table
5. **FK referential integrity** — preserved because parent table (e.g., CUST) processed BEFORE child (e.g., ACCT) within each BatchId

**Therefore**: re-running `replay_parquet_range_multi_table(...)` produces BYTE-IDENTICAL multi-table Bronze. Idempotent. ✅

### §3.5 Edge cases introduced by G2

- **MULTI-TABLE-EC1**: missing snapshot in one table for a given BatchId — skip-with-warning vs fail-fast policy
- **MULTI-TABLE-EC2**: dependency cycle (e.g., A→B→A) — operator must break manually; auto-derive must surface error
- **MULTI-TABLE-EC3**: cross-table BatchId misalignment (e.g., CUST BatchId 1000 exists but ACCT BatchId 1000 doesn't) — replay handles missing snapshots gracefully
- **MULTI-TABLE-EC4**: replay partial-failure (CUST succeeds at BatchId 1000; ACCT fails at BatchId 1000) — cross-table consistency window during recovery; ledger_step tracks per-(batch_id, table) for resume

---

## §4. G3-G11 designs (concise per gap)

### §4.1 G3: Initial backfill ingestion strategy (HIGH)

**Decision rule** (per table size + extraction window):
- **Small tables** (≤10M rows): single backfill Parquet file `batch={InitialBatchId}_part-1.parquet` with `BusinessDate=FirstLoadDate` per UdmTablesList; no per-day chunking
- **Medium tables** (10M-100M rows): per-day chunked over a 7-day initial-load window; subsequent daily-delta extractions begin on Day 8
- **Large tables** (>100M rows, e.g., AuditLog/ACCT): per-day chunked over a 30-day initial-load window (matches `MaxRowsPerDay` cap); subsequent daily-delta extractions begin on Day 31

**Implementation**: extend `main_large_tables.py` with `--mode=initial-backfill` flag; preserves existing windowed-CDC pattern but configures larger window with no LookbackDays overlap.

**Idempotency proof**: deterministic per (table_config, source state at extraction time). Re-running initial-backfill with same inputs produces SAME Parquet sets.

### §4.2 G4: D2 cutover rollback procedure for ACCT pilot (HIGH)

**NEW RB-N** (to be authored as **RB-12** at Phase 2 R1 prep):
```
Pre-flight:
  1. BCP OUT pre-D2 Bronze.ACCT to filesystem snapshot
  2. Lock Bronze.ACCT (sp_getapplock; Session-owned)
  3. Verify ledger has no IN_PROGRESS rows for ACCT

Procedure:
  4. Deploy D2 code (small_tables.py without Stage write)
  5. Run ACCT pipeline end-to-end
  6. Verify §12.2 acceptance criteria (Bronze byte-identical)

Validation:
  7. BCP OUT post-D2 Bronze.ACCT
  8. DIFF pre-D2 vs post-D2 (per PK + per UdmEffectiveDateTime; sample N PKs)
  9. If diff exists: ROLLBACK

Rollback:
  10. BCP IN pre-D2 snapshot OVER current Bronze.ACCT
  11. Revert deploy (re-enable Stage write path)
  12. Document divergence + open B-N for investigation
  13. Halt D2 rollout until divergence understood
```

### §4.3 G5: RB-13 SCD2 corruption replay runbook (HIGH)

**NEW RB-N** (to be authored as **RB-13** at Phase 2 R2 prep; per user-binding constraint #3):
```
Detection:
  - Tool: tools/validate_scd2.py reports invariant violation
  - Symptoms: missing active row; duplicate active rows; orphaned Flag=0; broken chain

Pre-flight:
  1. Identify affected (source, table, time range)
  2. Verify Parquet snapshots exist for range (parquet_tier_review)
  3. Verify capacity for replay output (CapacityBaselineLog)
  4. Check IdempotencyLedger for in-progress rows (must be CLEAN)
  5. Confirm CcpaDeletionLog snapshot date (default = now)
  6. Estimate replay duration (per-day SCD2 time × days in range)
  7. Obtain pipeline-lead approval if estimate >24h
  8. Schedule maintenance window (no concurrent AM/PM cycle on table)

Procedure:
  9. Acquire sp_getapplock on (source, table)
  10. python3 tools/scd2_replay_smoke.py --source X --table Y --start-date YYYY-MM-DD --end-date YYYY-MM-DD --ccpa-snapshot-as-of <datetime>
  11. Monitor PipelineEventLog EventType='PARQUET_REPLAY' rows (per-day progress)

Validation:
  12. Re-run tools/validate_scd2.py
  13. Cross-Bronze sample check (N PKs vs source DB current values)
  14. Verify CCPA-deleted subjects absent from active Bronze
  15. Sign-off ledger entry

Rollback:
  16. If replay fails partway: ledger has per-day checkpoints; resumable
  17. If replay produces incorrect Bronze: BCP OUT current Bronze; investigate; re-replay with corrected inputs
  18. Document at incident-log + open B-N if engine bug
```

### §4.4 G6: Lock-resource-string identity verification (HIGH)

**Action**: confirm `replay_table_lock(source, table)` and `orchestration/table_lock.py::acquire_lock(source, table)` target IDENTICAL sp_getapplock resource string.

**Implementation**:
- Refactor: `data_load/parquet_replay.py::replay_table_lock` IMPORTS from `orchestration/table_lock.py::TABLE_LOCK_RESOURCE_FORMAT` (single source of truth)
- Tier 1 test: verify both code paths produce identical resource string for same (source, table) inputs
- Documentation: cite in `01c_data_flow_walkthrough.md` § 4 (failover branch)

**Idempotency proof**: lock identity is REQUIRED for cross-cycle mutual exclusion. Without identity, replay + normal cycle could BOTH hold "different" locks for same table → double-write.

### §4.5 G7: Performance baseline benchmark (MEDIUM)

**Phase 2 R2 deliverable**: empirical benchmarks before Phase 3 R1:
- Single-day SCD2 throughput at 3B-row Bronze (P1-3 PK-scoped pattern)
- BCP throughput at 30M-row backfill (BCP `-b` param tuning per Reviewer R4 research)
- Polars memory profile at 100M-row delta with ZSTD-3 Parquet read
- Replay engine throughput per Parquet day

**Output**: `docs/migration/_research/phase2-r2-performance-baseline-<date>.md`

### §4.6 G8: Compaction registry semantics (MEDIUM)

**Defer to compaction-feature build time** (B-N-α from prior turn). At build time:
- ALTER ParquetSnapshotRegistry ADD `superseded_by_registry_id BIGINT NULL` + FK to self
- Replay-dispatcher logic: if `superseded_by_registry_id IS NULL`, read this file; else read the compacted-superseder
- Compaction tool atomically: writes compacted Parquet → INSERT new registry row → UPDATE old rows' `superseded_by_registry_id`

### §4.7 G9: Phase 6 D2 health-check extensions (MEDIUM)

**Defer to Phase 6 planning**. D2-specific extensions:
- `health_checks/parquet_file_size_distribution.py` — partition skew detection
- `health_checks/parquet_schema_over_time.py` — schema-evolution drift detection (mitigates D2-EC4)
- `health_checks/parquet_daily_count.py` — missing daily Parquet detection (catches silent extraction failures)
- `health_checks/parquet_registry_status_histogram.py` — stuck `created` rows catch verify failing silently

### §4.8 G10: Polars version compatibility during replay (LOW)

**Acknowledgment**: V-11 polars-hash fallback + R07 pin mitigate. Add to plan §6:
- BEFORE multi-version replay (e.g., 6-month replay traversing polars upgrade): manual verify `polars-hash --version` pin matches pinned version used at original Parquet write time
- Document in RB-13 pre-flight step 6 (estimate calculation)
- Long-term: track polars-hash version per Parquet file in registry (NEW `polars_hash_version VARCHAR(20) NULL`)

### §4.9 G11: Cost analysis (LOW)

**Defer to Phase 0 supplement** (Phase 0 deliv 0.17 capacity already partly covers; needs $ extension):
- H drive 80 TB infrastructure cost: ops/infra team estimate
- SQL Server storage for full Bronze: DBA team estimate
- Pipeline-team time cost for Stage→Parquet learning curve: pipeline lead estimate
- Replay compute cost (24-48hr RHEL allocation): ops team estimate

**Output**: `docs/migration/_research/d2-cost-analysis-<date>.md` (Phase 0 supplement scope)

---

## §5. Research items dispatch

| R# | Topic | Status | Output target |
|---|---|---|---|
| **R1** | Delta Lake / Iceberg / Hudi compaction patterns | DEFERRED (post-pilot) | `_research/r1-compaction-patterns-<date>.md` |
| **R2** | Snowflake Iceberg federation small-file performance | DEFERRED (Phase 5 dep) | `_research/r2-snowflake-iceberg-small-files-<date>.md` |
| **R3** | Polars memory profiling at 100M-row+ scale | DEFERRED (Phase 2 R2 benchmark per G7) | `_research/r3-polars-memory-profile-<date>.md` |
| **R4** | SQL Server BCP optimal batch size at TB-scale | DEFERRED (Phase 2 R2 benchmark per G7) | `_research/r4-bcp-batch-size-tb-scale-<date>.md` |
| **R5** | CCPA / GDPR + immutable audit data legal classification | **IN PROGRESS** (Agent `a959ee0434c90087b`; background) | `_research/r5-ccpa-parquet-replay-legal-2026-05-17.md` |

---

## §6. B-N enumeration (B-341 through B-350)

Per Reviewer recommendation; new B-Ns to open:

| B-N | Severity | Description | Closure target |
|---|---|---|---|
| **B-341** | CRITICAL | G1 design (CCPA + Parquet replay): lock D-N (likely tentative-future-D-N) post-R5 research integration; implement `_apply_ccpa_filter` + `ccpa_snapshot_as_of` parameter in `replay_parquet_range` | BEFORE D2 execution begins |
| **B-342** | CRITICAL | G2 design (multi-table replay ordering): author `replay_parquet_range_multi_table()`; UdmTablesList.ForeignKeyRefs column (D92 forward-only ALTER); FK dependency resolution | Phase 3 prereq (single-table ACCT pilot can defer) |
| **B-343** | HIGH | G4 D2 cutover rollback runbook: author RB-12 per §4.2 specification | Phase 2 R1 prep (BEFORE ACCT pilot) |
| **B-344** | HIGH | G5 SCD2 corruption replay runbook: author RB-13 per §4.3 specification | Phase 2 R2 (BEFORE production cutover) |
| **B-345** | HIGH | G6 lock-resource-string identity verification + Tier 1 test | Phase 2 R1 prep (cheap; should be hours) |
| **B-346** | MEDIUM | G7 performance baseline benchmark: Phase 2 R2 deliverable | Phase 2 R2 (BEFORE Phase 3 R1 estimate validation) |
| **B-347** | MEDIUM | G8 compaction registry semantics: defer; design at compaction-feature build time | Compaction-feature scope |
| **B-348** | MEDIUM | G9 Phase 6 D2 health-check extensions: 4 new health-check tools | Phase 6 planning |
| **B-349** | LOW | G10 Polars version tracking per Parquet file: registry column `polars_hash_version` | Phase 2 R2 (opportunistic) |
| **B-350** | LOW | G11 cost analysis: H drive infra + SQL Server storage + ops learning curve + replay compute | Phase 0 supplement |

Additional B-Ns implied by the comprehensive design (for completeness):
- **B-351** | LOW | CCPA-REPLAY edge cases (CCPA-REPLAY-EC1 through EC4) authoring in 04_EDGE_CASES.md | Phase 2 R1 close-out (per G1 implementation)
- **B-352** | LOW | MULTI-TABLE-REPLAY edge cases (MULTI-TABLE-EC1 through EC4) authoring in 04_EDGE_CASES.md | Phase 3 R1 close-out (per G2 implementation)

---

## §7. Sign-off readiness checklist

### §7.1 Pre-sign-off actions (this commit)

- [x] G1 design proposed (Option A4 time-aware replay; §2)
- [x] G2 design proposed (Option B1 cross-table BatchId-aligned; §3)
- [x] G3-G11 designs proposed (concise per gap; §4)
- [x] R5 research dispatched (background udm-researcher; §5)
- [ ] 12 B-Ns opened (B-341 through B-352; §6)
- [ ] D2 plan §5.4 amended acknowledging G1+G2 as pre-execution gates
- [ ] D2 plan §11 amended with Risk-NEW-D (CCPA-replay-interaction-unresolved)
- [ ] Independent gap-check second-pass on this gap-resolution plan (per D56)

### §7.2 Post-R5 integration actions (next session)

- [ ] R5 findings integrated into G1 design (§2.5)
- [ ] D-N candidate tentative-future-D-N locked (CCPA + Parquet replay design)
- [ ] G1 design finalized + this plan's §2 updated to reflect R5-grounded design

### §7.3 Phase 2 R1 prerequisites (Phase 2 R1 BLOCK on these)

- [ ] B-341 (G1 D-N decision + design) RESOLVED
- [ ] B-345 (G6 lock-resource verification) RESOLVED
- [ ] B-343 (RB-12 rollback runbook) AUTHORED
- [ ] B-332 from parent D2 plan (replay_parquet_range single-table) BUILT
- [ ] B-334 from parent D2 plan (source_verifier_fn closure) BUILT
- [ ] B-336 from parent D2 plan (small-table Parquet write) BUILT
- [ ] B-337 from parent D2 plan (IdempotencyLedger SUPERSEDED) BUILT

### §7.4 Phase 3 R1 prerequisites (Phase 3 R1 BLOCK on these)

- [ ] B-342 (G2 multi-table replay ordering) BUILT
- [ ] B-344 (RB-13 SCD2 corruption replay runbook) AUTHORED
- [ ] B-346 (G7 performance baseline benchmark) MEASURED
- [ ] B-333 from parent D2 plan (H drive capacity verification) RECORDED

### §7.5 Sign-off

🟡 **DRAFT 2026-05-17** by parent agent + reviewer Agent `ae1476a588dd34e15` (41st cumulative) + researcher Agent `a959ee0434c90087b` (42nd cumulative; IN PROGRESS).

**Pipeline lead sign-off**: [ ] APPROVED / [ ] REDIRECT / [ ] BLOCK on specific gap

**Sign-off authorizes**:
- D2 plan APPROACH (parent D2 execution plan)
- This gap-resolution plan APPROACH (designs proposed; B-Ns opened)
- B-341 (G1 D-N decision + implementation) becomes the next Phase 2 R1 work item

**Sign-off does NOT authorize**:
- Phase 2 R1 execution begin (gated on B-341 + B-345 + B-343 per §7.3)
- Phase 3 R1 execution begin (gated on B-342 + B-344 + B-346 per §7.4)
- B-N closure without their individual reviewer + validator passes

---

## §8. Cross-references

- `docs/migration/D2_EXECUTION_PLAN_PARQUET_DIRECT_SCD2_2026-05-17.md` (PARENT plan; this is APPENDIX)
- `docs/migration/03_DECISIONS.md` D2 + D4 + D15 + D16 + D17 + D18 + D25 + D26 + D30 + D102 + D107 + D110
- `docs/migration/05_RUNBOOKS.md` RB-10 (CCPA right-to-deletion) + RB-7 (DC-loss DR drill) + RB-8 (Bronze rebuild)
- `docs/migration/CLAUDE_GOTCHAS.md` SCD2-P1-* + SCD2-R* + E-2 + P0-8 + B-4 + B-2 + D15 + V-4 + V-11
- `scd2/engine.py` (1800+ lines)
- `data_load/parquet_replay.py` (existing single-snapshot; B-332 extends to range; B-342 extends to multi-table)
- `cdc/source_verifier.py` (existing module; D18 moves invocation to SCD2 per B-334)
- Reviewer Agent `ae1476a588dd34e15` verdict + recommendations
- Researcher Agent `a959ee0434c90087b` R5 findings (background; will land at `_research/r5-ccpa-parquet-replay-legal-2026-05-17.md`)

---

**Awaiting**:
1. R5 research integration into §2.5 G1 design
2. Pipeline-lead sign-off per §7.5
