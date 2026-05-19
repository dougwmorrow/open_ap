# UDM Pipeline CDCMode 3-Way Dispatch Plan — extending D63 with `'both'` value (2026-05-19)

**Status**: 🟡 Proposed 2026-05-19
**Closes**: planning-task — surfaces D125 proposal + 8 B-N opens + 4 doc updates
**Supersedes**: extends (does NOT supersede) D63 per D92 forward-only-additive schema evolution discipline
**Empirical anchor**: user-direction 2026-05-19 "Path A is acceptable, and we should be able to do both or choose one. We can set a 3rd option for CDCMode to do both. Come up with a solution and plan for us to follow. Update older plans so that we are properly tracking what is in scope."

---

## §0. Planning session provenance

**Skills invoked during this planning session** (per `udm-planning-session-startup` skill at session start; see `docs/migration/PLANNING_DISCIPLINE.md` for matrix):

| Skill | Invoked at | Scope reference | Rationale |
|---|---|---|---|
| `udm-planning-session-startup` | 2026-05-19 (this commit) | PS-1 ARCH + PS-8 D-N + PS-2 DOC | Session-start protocol; identifies multi-scope plan |
| `udm-decision-recorder` | 2026-05-19 (inline §3) | PS-8 mandatory | D125 proposal authoring |
| `udm-design-reviewer` | 2026-05-19 (sub-agent TBD post-attestation) | PS-1 mandatory | Architectural soundness of 3-mode dispatch |
| `udm-execution-classifier` | 2026-05-19 (inline §6) | PS-3 conditional | Classify schema migration + dispatch wiring |
| `udm-edge-case-validator` | 2026-05-19 (inline §9) | PS-1 conditional | Walk M/S/I/N/P/G/D/F/V/DP/T/SI/SE/PL/LT series |
| `udm-checks-and-balances` | 2026-05-19 (at attestation) | PS-1 + PS-8 mandatory | 5-gate validation pre-lock |
| `udm-gap-check` | 2026-05-19 (post-plan-authoring) | mandatory per hard rule 11 | Independent G1-G6 audit |
| `udm-progress-logger` | 2026-05-19 (at commit) | throughout per hard rule 9 | Tracker updates |

**Sub-agents spawned + skill inheritance** (per CLAUDE.md hard rule 13):

| Sub-agent | Spawned at | Skills inherited |
|---|---|---|
| `udm-design-reviewer` (TBD) | post-attestation | udm-design-reviewer + udm-data-engineer-review |
| `udm-gap-check` reviewer (TBD) | post-plan-landing | G1-G6 audit (inherited from skill spec) |

---

## §1. Background + current state

### §1.1. D63 canonical 2-value CDCMode design (locked 2025-XX-XX per `03_DECISIONS.md` L1284-1314)

`UdmTablesList.CDCMode NVARCHAR(20) NOT NULL DEFAULT 'change_detect'` with CHECK constraint `IN ('change_detect', 'parquet_snapshot')`. Per-table flag for D2 cutover atomicity:

- `'change_detect'` (default; current behavior): legacy Stage→CDC→SCD2 pipeline (extract → CSV → BCP to `UDM_Stage.{source}.{table}_cdc` → Polars CDC hash comparison → SCD2 promotion to `UDM_Bronze.{source}.{table}_scd2_python`)
- `'parquet_snapshot'`: D2 target pipeline (extract → write Parquet → replay Parquet via `replay_parquet_snapshot()` → SCD2 promotion)

### §1.2. Current implementation gap

Per `git grep -nE "write_parquet_snapshot|cdc_mode" HEAD -- 'orchestration/*.py' 'main_*.py'` verified 2026-05-19:
- `data_load/parquet_writer.py::write_parquet_snapshot()` is **DEFINED** but has **ZERO production call sites**
- `data_load/parquet_replay.py::replay_parquet_snapshot()` is **DEFINED** but has **ZERO orchestrator call sites**
- `migrations/cdc_mode_column.py` is referenced in `02_PHASES.md` L95 but **does NOT exist on disk** (verified via `git show HEAD:`)
- `TableConfig.cdc_mode` field is referenced in D63 affects-section but **NOT YET in `orchestration/table_config.py`**
- `orchestration/large_tables.py` + `orchestration/small_tables.py` do NOT dispatch on CDCMode — they unconditionally run legacy Stage→CDC→SCD2 path

**Net**: nothing currently reads `CDCMode`. The D63-locked design is intent-only; implementation is pending.

### §1.3. User-direction 2026-05-19 — add 3rd value `'both'`

Pattern A (per-table CDCMode flag for exclusive mode selection) is acceptable. User also wants a 3rd value enabling DUAL-execute for safety during migration. This plan extends D63's 2-value enum to 3 values, proposes D125 as the formal extension, and defines the orchestrator dispatch semantics for all 3 values.

---

## §2. The 3-mode design

### §2.1. Mode enumeration

| Value | Semantics | Path that drives Bronze | Parquet artifact written? |
|---|---|---|---|
| `'change_detect'` | Legacy Stage→CDC→SCD2 only (D63 canonical default) | Legacy CDC | NO |
| `'parquet_snapshot'` | Parquet→replay→SCD2 only (D2 target; D63 canonical alternate) | Parquet replay | YES |
| `'both'` (NEW per D125) | Dual-execute: Parquet write + legacy CDC; legacy CDC drives Bronze | Legacy CDC (audit substrate via Parquet) | YES |

### §2.2. `'both'` mode sub-variant decision

Three sub-variants of `'both'` mode were considered:

| Sub-variant | Bronze source | Shadow side | Failure semantic |
|---|---|---|---|
| **BOTH_LEGACY_FEEDS** (CHOSEN) | Legacy CDC | Parquet (audit + future replay substrate) | Parquet failure aborts run; Bronze never compromised |
| BOTH_PARQUET_FEEDS (rejected for v1) | Parquet replay | Legacy Stage CDC | Higher Bronze-impact risk; Parquet is unproven path |
| BOTH_COMPARE (deferred to future enhancement) | Both feed SCD2 with parity check | n/a | Divergence alerts; requires §6 parity-check tool first |

**Rationale for BOTH_LEGACY_FEEDS as v1**: minimizes Bronze risk during migration. Legacy CDC is the canonical production path with months of testing; Parquet is unwired today. Initial `'both'` deployment must ensure Bronze never degrades — Parquet failure cannot affect Bronze population. Future BOTH_COMPARE variant enabled by parity-check tool (B-NEW-4).

**`CDCMode = 'both'` implicitly means BOTH_LEGACY_FEEDS in v1**. Future enhancements may add `'both_parquet_feeds'` and `'both_compare'` as additional CHECK values without breaking v1 callers (forward-only-additive per D92).

### §2.3. Mode-transition matrix (RB-16 cutover semantics)

| From → To | Direct allowed? | Recommended via |
|---|---|---|
| `change_detect` → `parquet_snapshot` | YES but RISKY (direct cutover; no validation period) | Stop via `'both'` for ≥30 days first |
| `change_detect` → `both` | YES (safe; adds shadow Parquet write; Bronze unaffected) | RB-16 step 1 of safe cutover |
| `both` → `parquet_snapshot` | YES (canonical cutover after 30-day validation period) | RB-16 step 2 of safe cutover |
| `parquet_snapshot` → `both` | YES (defensive rollback during cutover instability) | RB-16 rollback |
| `parquet_snapshot` → `change_detect` | YES (full rollback) | RB-18 rollback (extends current scope) |
| `both` → `change_detect` | YES (rollback during shadow period) | RB-18 rollback (extends current scope) |

---

## §3. D125 proposal (extends D63)

### §3.1. Decision body

**D125 — CDCMode 3rd value `'both'` for dual-execute shadow safety**

**Status**: 🟡 Proposed 2026-05-19; lock at attestation post-design-reviewer

**Pillar(s) served** (per D61): **Audit-grade** (Parquet substrate captured during migration) + **Operational safety** (Bronze never at risk from unwired Parquet path) + **Traceability** (per-table mode auditable via PipelineEventLog)

**Decision**: Extend D63's CDCMode CHECK constraint from 2 values to 3:
- Before: `CHECK (CDCMode IN ('change_detect', 'parquet_snapshot'))`
- After: `CHECK (CDCMode IN ('change_detect', 'parquet_snapshot', 'both'))`

`'both'` value implements BOTH_LEGACY_FEEDS sub-variant in v1 (legacy CDC drives Bronze; Parquet is shadow/audit). Future sub-variants (BOTH_PARQUET_FEEDS, BOTH_COMPARE) may be added as additional CHECK values without breaking v1 callers per D92 forward-only-additive discipline.

**Rationale**: D63's 2-value enum forces direct `change_detect` → `parquet_snapshot` cutover with no validation period. Bronze population risk is HIGH for the FIRST D2 cutover (ACCT pilot) since Parquet write path has zero production exercise. Adding `'both'` enables operators to capture Parquet substrate during a 30-day shadow period BEFORE flipping Bronze authority — same pattern as canonical migration shadow-write discipline (per Google SRE Workbook + AWS Well-Architected; cited in `_research/scd2-corruption-recovery-rb15-2026-05-18.md` §3 Pattern A).

**Alternatives considered**:
- (a) **Keep D63 2-value; direct cutover** — rejected: HIGH Bronze risk on first D2 cutover; no validation period
- (b) **Add 3rd value `'both'` (CHOSEN)** — chosen: incremental safety; forward-only-additive extension of D63
- (c) **Add 3 sub-variants of `'both'` immediately** (`'both_legacy_feeds'`, `'both_parquet_feeds'`, `'both_compare'`) — rejected for v1: scope creep; v1 needs only ONE sub-variant; future enhancement enabled by forward-only-additive discipline
- (d) **Runtime env-var or CLI flag for mode selection** — rejected: per-table flexibility needed (different tables migrate at different times); D63 architecture already chose per-table column

**Trade-offs accepted**:
- BOTH mode adds ~30% I/O cost (Parquet write); storage budget per B-333 H drive capacity gate must accommodate this overhead during validation period
- BOTH mode requires 3-way dispatch logic in orchestrators — testing surface 1.5x larger than 2-way
- Future BOTH sub-variants (BOTH_PARQUET_FEEDS / BOTH_COMPARE) deferred to separate D-Ns + B-Ns when needed

**Affects**:
- Decisions: extends D63 (D92 forward-only-additive); supersedes implicit assumption in D2 plan §1.4 that Stage write MUST be removed before pilot (now: Stage path retained during 'both' mode validation)
- Edge cases: T-series (testing) — 3-mode parametrize required; M-series (memory) — BOTH mode 1.3x memory; F-series (failover) — BOTH mode partial-failure semantic
- Runbooks: RB-16 (AuditLog cutover) — procedure now uses 2-step `change_detect` → `both` → `parquet_snapshot` instead of direct flip; RB-18 (D2 cutover rollback) — extends to handle 'both' value
- Schema: `General.dbo.UdmTablesList.CDCMode` CHECK constraint extended; SchemaContract row per § 4.5
- Code modules: `orchestration/table_config.py::TableConfig.cdc_mode` field (D63-pending; built at B-NEW-2 closure); `orchestration/large_tables.py` + `orchestration/small_tables.py` 3-way dispatch logic (B-NEW-3)
- Migrations: `migrations/cdc_mode_column.py` (D63-pending; built at B-NEW-1 closure with CHECK extension already including 'both')
- Docs: 03_DECISIONS.md (this D125 entry); 05_RUNBOOKS.md RB-16 update; phase1/01a_control_tables.md L158 CHECK constraint update; phase1/02_configuration.md § 1.2 value enumeration update; D2_EXECUTION_PLAN §1.4 + §10 (acknowledge 'both' mode + validation period); PHASE2_LARGE_TABLES_AUDITLOG_PILOT_PLAN R1 + R2 deliverables

**Reversibility**: Reversible at the constraint level (DROP CHECK + recreate 2-value). But: once tables are configured with `'both'` value in production, reverting requires data preservation strategy. Treat as reversible during Phase 2 R1 prep; harder once R2 validation period populates Parquet substrate for production tables.

---

## §4. Schema migration design

### §4.1. Migration script: `migrations/cdc_mode_column.py` (D63-pending, extended with D125)

The D63-referenced migration script was NEVER built (verified via `git show HEAD:migrations/cdc_mode_column.py` returns "fatal: path does not exist"). This is a Pitfall #9.k-adjacent drift class — referenced in `02_PHASES.md` L95 but unbuilt.

Migration script combines BOTH D63 + D125 from day 1:

```python
# migrations/cdc_mode_column.py

DDL = """
IF NOT EXISTS (
    SELECT 1 FROM sys.columns
    WHERE object_id = OBJECT_ID('General.dbo.UdmTablesList')
      AND name = 'CDCMode'
)
BEGIN
    ALTER TABLE General.dbo.UdmTablesList
    ADD CDCMode NVARCHAR(20) NOT NULL
        CONSTRAINT DF_UdmTablesList_CDCMode DEFAULT 'change_detect';
END

IF NOT EXISTS (
    SELECT 1 FROM sys.check_constraints
    WHERE name = 'CK_UdmTablesList_CDCMode'
)
BEGIN
    ALTER TABLE General.dbo.UdmTablesList
    ADD CONSTRAINT CK_UdmTablesList_CDCMode
        CHECK (CDCMode IN ('change_detect', 'parquet_snapshot', 'both'));
END
"""
```

Note: CHECK constraint includes 'both' from day 1 — no separate D63→D125 evolution needed since D125 attestation happens BEFORE migration runs.

### §4.2. SchemaContract row

Per § 1.2 of `phase1/01_database_schema.md`:
- ContractName: `UdmTablesList_CDCMode_3way`
- ContractVersion: 1 (extends 0 if any prior CDCMode contract existed — verify at migration authoring time)
- ContractDef JSON: `{"column": "CDCMode", "type": "NVARCHAR(20)", "default": "change_detect", "check": ["change_detect", "parquet_snapshot", "both"]}`
- IsActive: 1
- ActivatedAt: migration-run timestamp

### §4.3. Migration triggers

EventType `MIGRATION_CDC_MODE_COLUMN` registered per § 4.5 of D63's EventType convention (CLAUDE.md L209+ family registry — currently has CLI_*, CYCLE_*, DEPLOYMENT_*, MIGRATION_*, PARQUET_*, STARTUP_*, SNOWFLAKE_REPLICATION_*, SCD2_PROMOTION_D2 families). MIGRATION_* family adds one row per migration invocation per Round 6 § 4.1.

---

## §5. Orchestrator dispatch logic

### §5.1. TableConfig field

`orchestration/table_config.py::TableConfig` dataclass extends with:

```python
@dataclass(frozen=True)
class TableConfig:
    # ... existing fields ...
    cdc_mode: str = "change_detect"  # D63 + D125; one of {'change_detect', 'parquet_snapshot', 'both'}
```

`TableConfigLoader` reads `CDCMode` from `UdmTablesList` SELECT and populates the field. Default `'change_detect'` preserves current behavior when column is missing (defensive).

### §5.2. Dispatch pseudocode (large_tables.py + small_tables.py)

```python
def process_large_table(table_config: TableConfig, ...) -> bool:
    mode = table_config.cdc_mode  # 'change_detect' / 'parquet_snapshot' / 'both'
    
    for target_date in dates_to_process:
        # --- EXTRACT (always; mode-independent) ---
        df, csv_path = extract_windowed(table_config, target_date, output_dir)
        
        # --- GUARDS (always; mode-independent) ---
        validate_source_schema(...)
        run_daily_extraction_guard(...)
        check_source_count_integrity(...)
        
        # --- PARQUET WRITE (modes: 'parquet_snapshot', 'both') ---
        parquet_result = None
        if mode in ('parquet_snapshot', 'both'):
            parquet_result = write_parquet_snapshot(
                df=df,
                source_name=source_name,
                table_name=table_name,
                business_date=target_date,
                batch_id=event_tracker.batch_id,
                output_dir=config.PARQUET_OUTPUT_DIR,
            )
            # Audit row via M3 parquet_registry_client (Status='created')
        
        # --- BRONZE-DRIVING PATH (mode-dependent) ---
        if mode in ('change_detect', 'both'):
            # Legacy Stage→CDC→SCD2 path; for 'both', this is canonical Bronze source
            cdc_result = run_cdc_promotion(table_config, df, ...)
            del df; gc.collect()
            run_scd2_promotion(table_config, cdc_result, ...)
        elif mode == 'parquet_snapshot':
            # D2 path: Parquet→replay→SCD2; replay reads back the just-written Parquet
            replay_result = replay_parquet_snapshot(
                registry_id=parquet_result.registry_id,
                # ... ledger_step composition + SHA-256 verify ...
            )
            del df; gc.collect()
            run_scd2_promotion(table_config, replay_result, ...)
        
        # --- CSV CLEANUP (always) ---
        cleanup_csvs(...)
```

### §5.3. Failure-mode semantics (BOTH mode)

| Scenario | Action | Bronze impact |
|---|---|---|
| Extract fails | Abort run; no Parquet, no Stage, no Bronze write | None |
| Parquet write fails AFTER extract succeeds | Abort run; legacy CDC NOT started; checkpoint EXTRACTED (not COMPLETE) | None |
| Parquet write succeeds + legacy CDC fails | Bronze remains at pre-run state; Parquet file exists (registry 'created' or 'verified'); idempotent retry safe (legacy CDC re-runs; Parquet write idempotent via inflight-rename) | None (failed CDC = no Bronze change) |
| Parquet succeeds + legacy CDC + SCD2 succeed | Normal completion; checkpoint SUCCESS; both substrates present | Bronze updated |

**Critical invariant**: Parquet write MUST run BEFORE legacy CDC starts. If Parquet write fails, legacy CDC must NOT start (preserves audit-substrate-before-Bronze-change semantic).

---

## §6. Affected plans / tracker updates

### §6.1. In-scope this commit cohort

| Artifact | Update | Sequencing |
|---|---|---|
| `docs/migration/UDM_PIPELINE_CDC_MODE_3WAY_DISPATCH_PLAN_2026-05-19.md` | NEW (this file) | This commit |
| `docs/migration/03_DECISIONS.md` | Add D125 entry | This commit (proposed status) |
| `docs/migration/BACKLOG.md` | Open 8 new B-Ns + 2 inline-fixes (B-336 stale claim; RB-16 stale value) | This commit + follow-up commit |
| `docs/migration/05_RUNBOOKS.md` RB-16 | Fix `'legacy'` → `'change_detect'` (Pitfall #9.k); add 3-mode cutover path | Follow-up commit |
| `docs/migration/05_RUNBOOKS.md` RB-18 | Add CDCMode value capture in Pre-flight step 4; rollback can flip to 'both' or 'change_detect' | Follow-up commit |

### §6.2. In-scope older plans to update

| Plan | Update required |
|---|---|
| `docs/migration/D2_EXECUTION_PLAN_PARQUET_DIRECT_SCD2_2026-05-17.md` | §1.4 "Stage MUST BE REMOVED" softens to "Stage path retained for `change_detect` AND `both` modes during migration; full removal deferred to Phase 2 R4+ per RB-16 cutover"; §1.2 GREENFIELD still applies; add cross-ref to this plan + D125 |
| `docs/migration/PHASE2_LARGE_TABLES_AUDITLOG_PILOT_PLAN_2026-05-18.md` | R1 deliverables: add B-NEW-1 (migration) + B-NEW-2 (TableConfig field) + B-NEW-3 (dispatch wiring) as R1 prereqs; R2: add B-NEW-4 (parity check) |
| `docs/migration/phase1/01a_control_tables.md` L158 | CHECK constraint becomes 3-value `IN ('change_detect', 'parquet_snapshot', 'both')` |
| `docs/migration/phase1/02_configuration.md` § 1.2 | CDCMode value enumeration becomes 3-value with `'both'` rationale |
| `docs/migration/02_PHASES.md` L95 | Migration script reference unchanged (still `migrations/cdc_mode_column.py`); body now implements D63 + D125 |
| `CLAUDE.md` | Add CDCMode-dispatch reference to "Data Flow (per table)" section OR add a new Do-NOT rule on `'both'` mode invariants (Parquet-before-CDC sequencing) |

### §6.3. Out-of-scope (deferred to future commits)

- Production wiring of `migrations/cdc_mode_column.py` (B-NEW-1 implementation; this plan only opens the B-N)
- TableConfig field implementation (B-NEW-2)
- Orchestrator dispatch implementation (B-NEW-3)
- Parity-check tool (B-NEW-4)
- Pre-cutover validation tool (B-NEW-5)
- RB-16 procedure rewrite for 3-step cutover (B-NEW-6)
- Tier 1 / Tier 2 test coverage for 3-mode dispatch

---

## §7. New B-Ns to open

| B-N | Severity | WSJF | Body | Closure target |
|---|---|---|---|---|
| **B-NEW-1** | HIGH | 4.0 | Author `migrations/cdc_mode_column.py` per D63 + D125 (was D63-referenced but never built; verified missing 2026-05-19); idempotent ALTER + DEFAULT 'change_detect' + 3-value CHECK constraint from day 1; SchemaContract row + MIGRATION_CDC_MODE_COLUMN EventType registration | Phase 2 R1 prep |
| **B-NEW-2** | HIGH | 4.0 | `TableConfig.cdc_mode` field + `TableConfigLoader` SELECT extension (defaults to `'change_detect'`); Tier 1 test pinning the 3-value parametrize + default fallback when column absent | Phase 2 R1 prep |
| **B-NEW-3** | HIGH | 4.0 | Orchestrator 3-mode dispatch in `orchestration/large_tables.py` + `orchestration/small_tables.py` per §5.2 pseudocode; supersedes B-336 (small-table Parquet write) + B-375 (extraction timestamp wiring) in implementation scope; Tier 1 mode-parametrize tests | Phase 2 R1 |
| **B-NEW-4** | MEDIUM | 3.0 | Parity-check tool: `tools/validate_parquet_vs_stage.py` — for tables in `'both'` mode, compare Bronze that legacy CDC produced vs Bronze that Parquet replay WOULD produce (dry-run replay); surface drift before cutover decision; D74/D75/D76 contract + `CLI_VALIDATE_PARQUET_VS_STAGE` EventType (27th CLI_* family member if B-540 + B-NEW-5 also land) | Phase 2 R2 |
| **B-NEW-5** | MEDIUM | 2.5 | Mode-transition tool: `tools/flip_cdc_mode.py` — operator CLI that flips `UdmTablesList.CDCMode` per RB-16 procedure (atomic transaction; INSERT PipelineEventLog row + UPDATE in same txn); validates transition matrix (§2.3); D74/D75/D76 contract + `CLI_FLIP_CDC_MODE` EventType | Phase 2 R2 |
| **B-NEW-6** | HIGH | 3.0 | Rewrite RB-16 procedure: 2-step cutover (`'change_detect'` → `'both'` for ≥30 days → `'parquet_snapshot'`) instead of direct flip; include B-NEW-4 parity-check pre-requisite; cite B-NEW-5 flip tool | Phase 2 R4 (BEFORE AuditLog cutover) |
| **B-NEW-7** | LOW | 1.0 | Pitfall #9.k inline-fix at RB-16 (`05_RUNBOOKS.md` L1568): rollback step says `SET CDCMode='legacy'` but canonical value is `'change_detect'` per D63 | This commit cohort |
| **B-NEW-8** | LOW | 1.0 | Inline-fix at B-336 (`docs/migration/BACKLOG.md` L588): body claims "only large-table path writes Parquet today per windowed-CDC" — verified FALSE 2026-05-19 (no production path writes Parquet today). Update to "neither large- nor small-table path writes Parquet today; B-NEW-3 wires both" | This commit cohort |

**B-N renumber risk**: B-N collision check at commit-authoring time. Current HIGH-WSJF range goes through B-540+. Renumber B-NEW-1 through B-NEW-8 to sequential numbers at attestation commit per BACKLOG conventions.

---

## §8. Execution sequence

### §8.1. R0 — this plan attestation (THIS commit cohort)

- [x] Plan markdown authored (this file)
- [ ] D125 entry added to `03_DECISIONS.md` (this commit)
- [ ] 8 new B-Ns opened in `BACKLOG.md` (this commit)
- [ ] RB-16 stale value `'legacy'` → `'change_detect'` inline-fix (this commit cohort OR follow-up)
- [ ] B-336 stale claim inline-fix (this commit cohort OR follow-up)
- [ ] Older plans cross-references updated (this commit cohort OR follow-up)
- [ ] `udm-design-reviewer` sub-agent invoked for architectural review (post-this-commit)
- [ ] `udm-gap-check` post-cohort audit (post-this-commit)
- [ ] D125 status flip 🟡 Proposed → 🟢 Locked (after reviewer 🟢 verdict)

### §8.2. R1 prep — BEFORE ACCT pilot

- [x] **B-542** (CLOSED 2026-05-19 via `2d65078`): `migrations/cdc_mode_column.py` authored; dev DB deployment pending operator action
- [x] **B-543** (CLOSED 2026-05-19 via `ce360da`): `TableConfig.cdc_mode` field wired + 13 Tier 1 tests pass
- [x] **B-544 v1** (CLOSED 2026-05-19 via `60f1283`; v2 → B-552): Orchestrator 3-mode dispatch wired; 18+1 Tier 1 tests pass; `'parquet_snapshot'` mode raises NotImplementedError pending B-552
- [ ] First end-to-end smoke: ACCT in `'change_detect'` mode (verify dispatch picks legacy path; current behavior preserved)
- [ ] Second end-to-end smoke: ACCT in `'both'` mode (verify dispatch writes Parquet + runs legacy CDC; Bronze byte-identical to step above)
- [ ] Third end-to-end smoke: ACCT in `'parquet_snapshot'` mode (verify dispatch writes Parquet + replays + runs SCD2; Bronze byte-identical to step above per D2 acceptance criteria)

### §8.3. R2 — post-ACCT-validation

- [ ] **B-552**: v2 of B-544 — `cdc_mode='parquet_snapshot'` end-to-end Parquet→replay→SCD2 path (HARD-BLOCKER for R3 cutover; opened at B-544 v1 partial closure commit `60f1283` 2026-05-19; added to checklist per cohort-review Agent ad50cb5cceda3f90c 2026-05-19 Scope 6 finding)
- [ ] B-540: production `tools/scd2_replay_range_smoke.py` (depends on B-NEW-3 dispatch wiring being production-stable)
- [ ] B-332: `data_load/parquet_replay.py::replay_parquet_range()`
- [x] **B-545 v1** (CLOSED 2026-05-19 via `e94d136`; v2 → B-555): Parity-check tool authored + 29 Tier 0 tests pass; row-count parity v1; per-PK hash deferred. ~~NOTE: B-553 + B-554 BLOCK production use against StripSuffix=1 OR NULL-PK tables~~ **RESOLVED 2026-05-19 via `00039a1`**: B-553 + B-554 closed; CLAUDE.md Do-NOT rule LIFTED; B-555 v2 per-PK hash remains pending for NULL-PK interpretation-gap closure (see B-561 for LIFTED-rule sharpening if needed; renumbered 2026-05-19 from B-559 to B-561 per B-N collision with other-agent's udm-session-compactor B-559)
- [x] **B-546** (CLOSED 2026-05-19 via `0ad5bcc`): Mode-transition flip tool authored + 21 Tier 0 tests pass; 6-allowed + 1-RISKY transition matrix per §2.3
- [ ] First production table in `'both'` mode for 30-day validation period (operator-selected; low-risk small table FIRST)
- [ ] Parity-check tool runs nightly; alerts on Parquet/Stage divergence

### §8.4. R3 — cutover phase

- [ ] B-NEW-6: RB-16 procedure rewrite per 2-step cutover
- [ ] B-344: RB-15 SCD2 corruption replay full body (depends on B-540)
- [ ] Per-table cutover from `'both'` → `'parquet_snapshot'` via B-NEW-5 + RB-16 procedure
- [ ] Monitor each cutover table for 30 days post-flip; rollback to `'both'` on any divergence

### §8.5. R4 — legacy removal (deferred; out-of-scope this plan)

- [ ] All production tables successfully on `'parquet_snapshot'` for ≥90 days
- [ ] Legacy Stage write code path deletion (per original D2 plan §1.4)
- [ ] CDCMode CHECK constraint update: drop `'both'` value (or keep forever for audit-substrate guarantee — D-N decision at that time)

---

## §9. Risks + edge cases (per udm-edge-case-validator series walk)

### §9.1. NEW R-Ns from this plan

| R-N | Severity | Body |
|---|---|---|
| **R-NEW-1** | MEDIUM | BOTH mode I/O cost — Parquet write adds ~30% disk I/O per run; storage capacity (per B-333 H drive analysis) must include `'both'` mode load during 30-day validation periods |
| **R-NEW-2** | MEDIUM | Failure-mode ambiguity in BOTH mode — if Parquet write succeeds but legacy CDC fails, Parquet file exists with `registry.Status='created'` but no Bronze write; next-run idempotency requires Parquet write to be a no-op on retry (per inflight-rename + sha256 hash invariant in M1 parquet_writer) |
| **R-NEW-3** | LOW | Parity-check tool semantic gap — BOTH_LEGACY_FEEDS means legacy CDC is canonical; Parquet "drift" is informational only until cutover. Operator must NOT panic on early parity-check alerts during `'both'` mode (drift is expected if Parquet path has bugs not yet caught) |
| **R-NEW-4** | LOW | Test surface explosion — 3 modes × N orchestrator paths × N edge cases = 1.5x baseline test count. Mode-parametrize Tier 1 tests; selective Tier 2 integration tests (not all mode combos in Tier 2) |

### §9.2. Edge case series walk

| Series | Coverage required for `'both'` mode |
|---|---|
| **M** (memory) | BOTH mode peak memory: extract DataFrame held during Parquet write + during legacy CDC. ~1.3x baseline. Must verify against W-4 MALLOC_ARENA_MAX=2 ceiling at ACCT smoke (small table) BEFORE production tables |
| **S** (state machine) | Parquet registry state transitions (`created` → `verified` → `replicated` → `archived` → `purged`) coexist with Stage table state transitions; no overlap risk |
| **I** (idempotency) | BOTH mode partial failure retries — Parquet write idempotent per M1 (inflight-rename + sha256); legacy CDC idempotent per existing P1-1 guard |
| **N** (NULL) | NULL PK filter (P0-4) runs in CDC layer — applies to legacy path in BOTH mode. Parquet path bypasses NULL filter (writes source-exact rows including NULL PK). DISCREPANCY: legacy CDC excludes NULL-PK rows from Bronze; Parquet INCLUDES them. Document in B-NEW-3 wiring + parity-check tool (B-NEW-4) excludes NULL-PK rows from comparison |
| **P** (PII) | Tokenization timing in BOTH mode — per Phase A reorder (D115), tokenization runs BEFORE Parquet write in source-exact design. BOTH mode: tokenize → write Parquet (tokenized) AND BCP CSV (tokenized) — both downstream paths see same tokenized data |
| **G** (guards) | Extraction guard (P1-13) + source-count check (Phase 3.1) MUST run BEFORE either path begins (mode-independent guards) |
| **D** (deletes) | Delete detection in BOTH mode: legacy CDC detects deletes via hash anti-join on Stage; Parquet path detects deletes via day-N-1 vs day-N Parquet diff (at replay time). Both arrive at same delete set IF source is consistent — parity-check tool (B-NEW-4) validates this |
| **F** (failover) | BOTH mode + SP-4 failover mid-run: which checkpoint resumes? Plan: failover BEFORE Parquet write completes → re-extract; failover AFTER Parquet success but BEFORE legacy CDC complete → retry legacy CDC from EXTRACTED checkpoint (Parquet write skipped via inflight-rename idempotency) |
| **V** (validation) | Cross-path validation via parity-check tool (B-NEW-4) — BOTH mode default. Continuous monitoring during 30-day validation period per table |
| **DP** (deployment) | BOTH mode requires BOTH Stage table writable AND Parquet directory writable; pre-flight check at orchestrator startup per DP-series |
| **T** (testing) | 3-mode parametrize at Tier 1; selective 3-mode at Tier 2 (Docker-fixture integration); 3-mode at Tier 4 crash-injection (BOTH mode partial-failure scenarios) |
| **SE** (source-exactness) | Phase A source-exact invariants apply to Parquet path; BOTH mode means SE-1 through SE-10 apply to the Parquet output (legacy CDC output is NOT source-exact by design; that's the migration motivation) |
| **PL** (progress-logger) | Event-row tags per run: include `CDCMode` field in PipelineEventLog metadata so operators can grep by mode |
| **LT** (large-table reconciliation) | LT-2/LT-3 modified-date sweep runs regardless of mode; sweep populates both Parquet + Stage in BOTH mode |

---

## §10. Open questions for review

| # | Question | Recommended answer | Confidence |
|---|---|---|---|
| 1 | BOTH mode default sub-variant: BOTH_LEGACY_FEEDS chosen. Should there be operator override at runtime? | NO — per-table column flexibility sufficient; runtime override adds complexity without clear benefit | HIGH |
| 2 | Parity-check cadence: continuous (every run) vs spot-check (operator-triggered)? | Continuous (B-NEW-4 default) during `'both'` mode validation period; spot-check after cutover to `'parquet_snapshot'` | MEDIUM |
| 3 | CDCMode default for NEW tables: `'change_detect'` (matches D63 default) vs `'both'` (forces audit substrate from day 1) | `'change_detect'` (preserves D63 default; opt-in to BOTH explicitly per table) | HIGH |
| 4 | Legacy removal timeline: never (keep `'both'` forever) vs after 30-day `'parquet_snapshot'` validation per table? | After 90-day `'parquet_snapshot'` validation per table; revisit at R4 close-out with empirical evidence | LOW (deferred to R4 D-N) |
| 5 | Bronze rollback during BOTH mode: which path's Bronze is "authoritative" for BCP OUT snapshot in RB-18? | Legacy CDC is canonical Bronze source in BOTH mode (BOTH_LEGACY_FEEDS semantic); BCP OUT captures the SAME Bronze regardless of which mode wrote it | HIGH |
| 6 | NULL-PK handling discrepancy between Stage CDC + Parquet path: warrants a CLAUDE.md Do-NOT rule? | Document inline in B-NEW-3 wiring; promote to CLAUDE.md Do-NOT only if parity-check tool surfaces actionable issues | MEDIUM |
| 7 | Should B-NEW-3 implementation use a strategy-pattern OR if/elif dispatch? | If/elif (3 paths) — KISS; strategy-pattern over-engineering for 3 cases | HIGH |
| 8 | Crash-injection test priority for BOTH mode: which crash boundaries? | C2 (inflight Parquet during BOTH mode) + C7 (SCD2 activation during BOTH); defer others to R3 | MEDIUM |

---

## §11. Citation provenance

- D63 body verbatim cite: `docs/migration/03_DECISIONS.md` L1284-1314
- D63 migration script reference: `docs/migration/02_PHASES.md` L95
- RB-16 placeholder body: `docs/migration/05_RUNBOOKS.md` L1558-1568
- Verified file-existence absence: `migrations/cdc_mode_column.py` NOT in git history via `git show HEAD:migrations/cdc_mode_column.py` 2026-05-19
- Verified call-site absence: `write_parquet_snapshot()` NOT called from `orchestration/`, `main_*.py` via `git grep -nE "write_parquet_snapshot\("` returns only definition at `data_load/parquet_writer.py:654`
- D2 cutover original design: `docs/migration/D2_EXECUTION_PLAN_PARQUET_DIRECT_SCD2_2026-05-17.md` §1.4
- Phase A reorder (tokenization-before-Parquet): D115 — `docs/migration/03_DECISIONS.md`
- Phase 2 R1 prep context: `docs/migration/PHASE2_LARGE_TABLES_AUDITLOG_PILOT_PLAN_2026-05-18.md`
- Smoke runbook reference: `TEST_PARQUET_TO_SCD2_PIPELINE.md` (committed bfe3502 2026-05-19)
- R1 cohort closure evidence: 10 commits 4b3e5c9 → b7c1c5a 2026-05-18 through 2026-05-19
