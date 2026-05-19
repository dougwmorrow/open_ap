# SESSION_RESUME -- scd2 chat (D125 implementation arc PRODUCTION-READY for SMALL + LARGE + B-563 closure + 10-event B-541 milestone)

**Chat scope**: D125 3-mode CDC dispatch (CDCMode `'change_detect'` / `'parquet_snapshot'` / `'both'`) + SCD2 + CDC + Bronze + replay-from-Parquet pipeline core + RB-16 production cutover procedure + B-541 read-only audit contract empirical validation + B-564 apply-path Tier 1 test layer. Does NOT touch udm-* skills + Phase 1 quality checks + producer-discipline meta-work (separate `meta-discipline.md` chat per parallel session).

**For fresh Claude session**: read this file first, then the immutable snapshot at `docs/migration/_session_snapshots/2026-05-19-7a810b9.md` (Section 4 Deeper insights = irreplaceable architectural-decision context), then `docs/migration/INDEX.md` -> `CURRENT_STATE.md` -> `HANDOFF.md` -> `CLAUDE.md` per CCL Stage 0+1 discipline.

---

## State as of session end

- **Branch**: `round-6-post-merge-tracking`
- **Latest commits (this chat; most recent 7; refreshed 2026-05-19 post-B-564)**:
  - **THIS COMMIT** -- B-564 closure (apply-path Tier 1 tests for `run_parquet_replay_step()` via AST-extracted canonical signature pin + signature-validating stub + bare-return AST audit + CSV cleanup sequencing audit; 14 new tests at `tests/tier1/test_parquet_replay_step_apply_path.py`; structural forward-prevention against B-552 v1 Finding 1.1+1.2 production-crash class; D56 second-pass minor-finding scd2.md drift inline-remediated; per cross-cohort reviewer `aea6c9174151af2f5` 2026-05-19 D56 second-pass verdict ATTENTION on `0c06961`)
  - `0c06961` -- B-552 v1 BLOCK remediation (per cross-cohort reviewer `a234fda11b870c78d` 7-event B-541 milestone; 6 inline-fixes including replay_parquet_snapshot signature correction + bare return fix + REPLAY EventType registration + _validation_log row + CSV cleanup + scd2.md refresh; B-564 opened)
  - `719b76b` -- B-552 v1 closure -- cdc_mode='parquet_snapshot' end-to-end (initial commit had 2 production-breaking bugs; remediated at `0c06961`)
  - `f42e200` -- SESSION_RESUME/active/scd2.md authored -- D125 / parquet-SCD2 chat state pointer per B-562 Component B Phase 1
  - `6868564` -- gap-check remediation post-B-547 (Pitfall #9.k + #9.m inline-fixes; 6-event B-541 milestone strengthening)
  - `d192cee` -- B-547 closure -- RB-16 procedure rewrite for 2-step D125 cutover (supersedes B-501 historical 2-phase design)
  - (Earlier arc commits enumerated in snapshot Section 5)
- **Push status**: HELD -- `git rev-list --count origin/round-6-post-merge-tracking..HEAD` ahead by N commits (verify at next session start; default-hold convention)
- **pytest baseline (this chat's D125 module scope)**: 156 Tier 0/1 tests pass across D125 implementation modules at HEAD (refreshed 2026-05-19 per gap-check reviewer `a121478077f0b7713` G1.1 -- prior `~133` claim was a Pitfall #9.k sum-vs-enumeration drift; enumeration below sums to 156):
  - `tests/tier0/test_cdc_mode_column.py` -- 11 tests (B-542 migration)
  - `tests/tier1/test_table_config_cdc_mode.py` -- 13 tests (B-543 TableConfig field)
  - `tests/tier1/test_orchestrator_cdc_mode_dispatch.py` -- 25 tests (B-544 v1 orchestrator dispatch + B-552 v1 Class E)
  - `tests/tier1/test_parquet_replay_step_apply_path.py` -- 14 tests (B-564 apply-path forward-prevention; NEW THIS COMMIT)
  - `tests/tier0/test_flip_cdc_mode.py` -- 21 tests (B-546 flip CLI)
  - `tests/tier0/test_validate_parquet_vs_stage.py` -- 40 tests (B-545 v1 parity-check CLI + B-553/B-554 NULL-PK + SS-1)
  - `tests/tier1/test_idempotency_ledger_d2_cutover.py` -- 7 tests (B-337 D119 forensic preservation)
  - `tests/tier1/test_scd2_source_verifier_fn.py` -- 18 tests (B-498 + B-334 + B-538 + B-543 dispatch)
  - `tests/tier1/test_table_lock_resource_identity.py` -- 7 tests (B-345 TABLE_LOCK_RESOURCE_FORMAT)
  - Full-suite: 9 pre-existing failures unrelated to D125 arc (test_crash_test_harness_hooks + test_measure_lateness; confirmed pre-existing via stash isolation)
- **Cumulative session delta (D125 / parquet->SCD2 scope only; meta-discipline chat's work is separate)**:
  - **D125 Locked 2026-05-19** at `03_DECISIONS.md` tail -- 3-value CDCMode enum extension (`'change_detect'` + `'parquet_snapshot'` + `'both'`) per `docs/migration/UDM_PIPELINE_CDC_MODE_3WAY_DISPATCH_PLAN_2026-05-19.md`
  - **21 B-Ns CLOSED** this arc (refreshed 2026-05-19 post-B-564 closure per D56 second-pass minor-finding G6.3): B-345 + B-334 + B-498 + B-337 + B-538 + B-541 + B-343 + B-542 + B-543 + B-544 v1 + B-545 v1 + B-546 + B-553 + B-554 + B-547 + B-552 v1 + B-564 + B-566 + B-567 + B-563 + B-555
  - **2 B-Ns inline-closed** this arc: B-548 + B-549
  - **B-Ns OPEN from this arc** (next-step queue; refreshed 2026-05-19 post-B-564 closure per D56 second-pass minor-finding G6.1): B-556 + B-557 + B-560 + B-561 + P-24
  - **NEW production modules** (this arc): `migrations/cdc_mode_column.py` (B-542) + `tools/flip_cdc_mode.py` (B-546) + `tools/validate_parquet_vs_stage.py` (B-545 v1)
  - **NEW production code** (extensions): `orchestration/table_config.py` (B-543; +18 LOC TableConfig.cdc_mode field + loader); `orchestration/pipeline_steps.py` (B-544 v1; +82 LOC dispatch helpers; B-552 v1 +~80 LOC run_parquet_replay_step helper); `orchestration/large_tables.py` + `orchestration/small_tables.py` (B-544 v1; ~30 LOC dispatch wiring each; B-552 v1 +~25 LOC parquet_snapshot branch each); `scd2/engine.py` (R1.3; B-498 + B-334; +106 LOC source_verifier_fn parameter + helper); `utils/idempotency_ledger.py` (R1.8; B-337; +30 LOC D119 forensic-preservation 3-site defense); `orchestration/table_lock.py` (R1.7; B-345; constant promotion)
  - **NEW test modules** (this arc): `tests/tier1/test_parquet_replay_step_apply_path.py` (B-564 THIS COMMIT; 14 tests; AST-extracted canonical-signature pin + signature-validating stub apply-path + bare-return audit + CSV cleanup sequencing audit + cross-orchestrator symmetry pin)
  - **NEW EventType family registrations**: CLI_FLIP_CDC_MODE (25th) + CLI_VALIDATE_PARQUET_VS_STAGE (26th) + MIGRATION_CDC_MODE_COLUMN + PARQUET_WRITE + REPLAY (registered at CLAUDE.md L215 per B-552 v1 BLOCK remediation Fix 3 at `0c06961`)
  - **NEW CLAUDE.md Do-NOT rule** (B-544 v1; preserved): BOTH mode Parquet-before-CDC sequencing invariant
  - **LIFTED CLAUDE.md Do-NOT rule** (first instance precedent; B-545 v1 production-safety pin LIFTED via B-553+B-554 closures): strikethrough body + LIFTED 2026-05-19 annotation + B-N closure citations + empirical anchor preservation
  - **NEW operational runbooks** (this arc): RB-18 D2 cutover rollback for ACCT pilot (B-343 closure at `b7c1c5a`); RB-16 D2 production cutover for AuditLog/large tables (B-547 closure at `d192cee`)
- **B-541 read-only audit contract empirical validation milestone**: **8 consecutive cross-cohort reviewers** honored the contract without violation (zero side-effect files / zero sub-agents / zero file modifications). Per HANDOFF Section 8 5-event empirical formalization threshold, the structural fix is now SIGNIFICANTLY BEYOND multi-event-validation threshold (8-event = 160% of formalization minimum):
  - `a843ad09d24f2a607` (post-B-541 closure)
  - `ac2dd8d0ec814dc7e` (post-D125 plan)
  - `ad50cb5cceda3f90c` (post-D125 implementation cohort)
  - `adc861405ff006766` (post-D125 toolkit completion)
  - `a8130cf417bb5692a` (post-B-553/B-554 closure)
  - `a95d8cc8b0ce3b7b6` (post-B-547 + arc review)
  - `a234fda11b870c78d` (post-B-552 v1 closure -- verdict BLOCK with 6 findings; drove BLOCK remediation at `0c06961`)
  - `aea6c9174151af2f5` (D56 mandatory second-pass on `0c06961` BLOCK remediation -- verdict ATTENTION with 6 minor scd2.md findings; drove inline remediation at THIS COMMIT)
- **Parallel session state**: meta-discipline chat (parallel session) is working on B-558 Phase 2.1 hardening cohort (udm-session-compactor) + B-562 multi-chat coordination cohort. B-562 Component A (`tools/claim_next_bn.py`) CLOSED at `dd9fbdb`; Component B Phase 1 (`SESSION_RESUME/active/` + `_archive/` directory structure) CLOSED at `64175d9`; Phase 2 router refactor CLOSED at `c8bb55b`. B-562 Phase 3 + B-558 Components A/B/C remain. **Do NOT touch their working files** (B-558 Phase 2.1 substrates + `SESSION_RESUME/active/meta-discipline.md`).

## NEXT SESSION RESUME PROCEDURE

Read in this order:

1. **This file** (state pointer; D125 chat scope)
2. **`docs/migration/_session_snapshots/2026-05-19-7a810b9.md`** -- immutable snapshot at session-pause point; Section 4 Deeper insights captures 6 architectural decisions + 6 cross-cohort patterns + 3 convergence-discipline events + 6 meta-discipline observations + reviewer-finding context table. **IRREPLACEABLE substrate for D125 architectural-decision context**.
3. **`docs/migration/UDM_PIPELINE_CDC_MODE_3WAY_DISPATCH_PLAN_2026-05-19.md`** -- D125 canonical plan; Section 2.3 transition matrix + Section 5.2 dispatch pseudocode + Section 8.2/8.3 R1/R2 checklists (post-B-547 + B-552 v1 + B-564 closures most R1+R2 items checked off)
4. **`docs/migration/BACKLOG.md`** L1108 (B-552 closed) + L1116 (B-564 closed) + L1115 (B-563 large-table delete-detection open) + B-555 + B-556 + B-557 + B-560 + B-561 entries
5. **`docs/migration/05_RUNBOOKS.md`** L1188 RB-13 (Permanent-Retire Table; canonical pattern reference) + L1558 RB-16 (D125 D2 production cutover; B-547 closure) + L1582 RB-18 (D2 cutover rollback for ACCT pilot; B-343 closure)
6. **`docs/migration/03_DECISIONS.md`** D125 entry (tail; Locked 2026-05-19)
7. **`CLAUDE.md`** L209+ CLI_* registry (now 27 tools post-B-562 Component A) + Do-NOT rules section (LIFTED B-545 rule + active BOTH-mode Parquet-before-CDC rule) + L215 PARQUET_* family entry (REPLAY registered post-B-552 v1)
8. **`CLAUDE.md`** L407+ substrate-edit enumeration (cascade-evidence requirement for any further D125 work)

## Open runway (priority-ordered; awaiting user direction)

### HIGH priority -- production-cutover blockers

- ~~**B-552** (HIGH; WSJF 3.5): **v2 of B-544 -- `cdc_mode='parquet_snapshot'` end-to-end Parquet->replay->SCD2 path**~~ -- **CLOSED 2026-05-19** via commits `719b76b` (v1) + `0c06961` (BLOCK remediation per cross-cohort reviewer `a234fda11b870c78d`). Per D56 second-pass reviewer `aea6c9174151af2f5` 2026-05-19 verdict ACCEPT remediation: all 6 production/discipline fixes correct; only minor scd2.md drift remained (inline-remediated THIS COMMIT). Orchestrator NotImplementedError REMOVED for `cdc_mode == 'parquet_snapshot'` mode. Operator workflow end-to-end PRODUCTION-READY for SMALL tables (ACCT pilot unblocked). Large-table cutover requires B-563 (delete-detection day-N vs day-N-1 Parquet diff) PLUS B-555 (per-PK hash parity definition).

### MEDIUM priority -- production-cutover sequence

- **B-563** (MEDIUM; WSJF 2.5 -- reviewer-suggested HIGH 3.5): **Large-table delete-detection via day-N vs day-N-1 Parquet diff**. HARD-PREREQUISITE for FIRST large-table cutover to `'parquet_snapshot'` mode (CCM.AuditLog at 96M / DNA.CARDTXN at 214M / etc.). B-552 v1 routes ALL parquet_snapshot through `run_scd2_promotion(targeted=False)` which is memory-heavy for 3B+ row tables. ~80-100 LOC orchestrator extension. Closure target: Phase 2 R2 BEFORE first large-table cutover. ACCT pilot is SMALL-table so unblocked.
- **B-555** (MEDIUM; WSJF 3.5): **v2 of B-545 -- per-PK hash comparison via polars Parquet read + Bronze `UdmHash` join**. Closes the row-count-only parity-check structural gap ("rows match but contents differ" silent failure) + the NULL-PK interpretation-gap (Parquet > Bronze drift attributable to NULL-PK noise). Symmetric to B-552 v2-of-B-544. Requires polars dep at tool level. Closure target: Phase 2 R2.
- **B-556** (LOW; WSJF 2.0): **Apply-path Tier 0/1 tests for `tools/flip_cdc_mode.py` + `tools/validate_parquet_vs_stage.py`**. Currently only dry-run paths are tested; non-dry-run UPDATE/INSERT/commit/rollback paths mechanically uncovered. Closure target: opportunistic alongside B-563/B-555 OR next CLI-tool authoring. **B-564 closure 2026-05-19 (THIS COMMIT) addresses the run_parquet_replay_step subset of this scope but does NOT cover flip_cdc_mode or validate_parquet_vs_stage CLI tools** -- B-556 remains the open scope for those two CLIs.

### LOW priority -- opportunistic discipline + cleanup

- **B-557** (LOW; WSJF 1.5): **Extract `_write_event_log_row()` shared helper into `utils/cli_common.py`**. ~40 LOC of identical CLI-audit-row boilerplate replicated across 27+ CLI tools (cumulative ~1080 LOC). Closure target: opportunistic at next round close-out OR when 28th CLI_* tool authored.
- **B-560** (LOW; WSJF 1.5): **Log WARNING when `tools/validate_parquet_vs_stage.py::_resolve_pk_columns()` returns empty list**. Operationally minor (Bronze excludes NULL-PK via legacy CDC's `_filter_null_pks()` (P0-4); defensive filter is no-op) but UdmTablesColumnsList unpopulated state likely indicates a separate operational issue worth surfacing. Closure target: opportunistic alongside B-556.
- **B-561** (LOW; WSJF 1.0): **Sharpen LIFTED Do-NOT rule body in CLAUDE.md for NULL-PK caveat prominence**. Current LIFTED-rule body buries the NULL-PK caveat at the end; could be more prominent OR re-armed as softer "WARN for NULL-PK tables until B-555 ships". Closure target: opportunistic OR at B-555 closure.
- **P-24** (LOW; cosmetic): **Document LIFTED-Do-NOT-rule format in CLAUDE.md Do-NOT-rules section header**. First instance precedent set at `00039a1`; format = strikethrough body + **LIFTED YYYY-MM-DD** annotation + B-N closure citations + empirical-anchor preservation. Closure target: opportunistic at next Do-NOT rule lift OR round close-out.

### Recommended next-step

**B-563** is the highest-impact next deliverable -- closes the HARD-PREREQUISITE for FIRST large-table cutover to `'parquet_snapshot'` mode (CCM.AuditLog / DNA.CARDTXN). Substantive scope (~80-100 LOC orchestrator + day-N vs day-N-1 Parquet diff via Polars set-diff + Tier 1 tests via B-564 harness pattern). B-564 closure THIS COMMIT provides the test-authoring pattern for B-563 (AST-extracted canonical-signature pin + signature-validating stub) so B-563 cannot ship with the same MagicMock false-coverage class that B-552 v1 hit. Alternative: **B-555 (per-PK hash parity)** unblocks interpretation of B-545 nightly parity results before large-table cutover decision; B-563 + B-555 are both pre-requisites for first large-table cutover.

## This session's commit chain (most-recent 12 D125-arc commits; older arc commits in snapshot Section 5)

```
<THIS COMMIT>  build(round-6): B-564 closure -- apply-path Tier 1 tests + AST-extracted canonical signature pin + scd2.md inline-remediation
0c06961  build(round-6): B-552 v1 BLOCK remediation -- 6 inline-fixes per cross-cohort reviewer a234fda11b870c78d
719b76b  build(round-6): B-552 v1 closure -- cdc_mode='parquet_snapshot' end-to-end Parquet->replay->SCD2
f42e200  docs(round-6): SESSION_RESUME/active/scd2.md authored per B-562 Component B Phase 1
6868564  docs(round-6): gap-check remediation post-B-547 -- Pitfall #9.k + #9.m inline-fixes + 6-event B-541 milestone
d192cee  build(round-6): B-547 closure -- RB-16 procedure rewrite for 2-step D125 cutover
fc79ec7  docs(round-6): session snapshot @ 7a810b9 -- D125 implementation arc complete + B-541 5-event milestone
7a810b9  docs(round-6): B-N collision renumber -- my B-558+B-559 -> B-560+B-561
9b1d7fb  docs(round-6): cross-cohort review post-B-553/B-554 remediation
00039a1  build(round-6): B-553 + B-554 bundled closure -- SS-1 + NULL-PK + Parquet-missed-data guard
325eb7e  docs(round-6): D125 toolkit cohort gap-check remediation -- 5 inline-fixes + 5 B-N opens + Do-NOT rule
1995aa3  docs(round-6): D125 cohort gap-check remediation -- 2 inline-fixes + 2 IMPROVEs + 43/43 tests
```

(Earlier arc commits -- R1.3 + R1.7 + R1.8 cohort + B-344 adoption + D125 plan + B-542 + B-543 + B-544 v1 + B-343 RB-18 + B-545 v1 + B-546 -- enumerated in snapshot Section 5 with significance annotations.)

## Composition with B-562 Component B (multi-chat coordination)

This file lives at `SESSION_RESUME/active/scd2.md` per B-562 Component B Phase 1 (commit `64175d9`) per-chat directory structure. Parallel meta-discipline chat's pointer is at `SESSION_RESUME/active/meta-discipline.md`. Both files are scope-stable + chat-named per B-562 README convention. Future chat sessions reading EITHER pointer will know which other chats are active + can avoid touching their files.

**Coordination contract** (per B-562 README + this session arc empirical observation):
- D125 / scd2 chat owns: `migrations/cdc_mode_column.py`, `tools/flip_cdc_mode.py`, `tools/validate_parquet_vs_stage.py`, `orchestration/*`, `scd2/*`, `utils/idempotency_ledger.py`, RB-16 + RB-18 procedures, D125 plan + entry, `tests/tier1/test_parquet_replay_step_apply_path.py` (B-564 NEW)
- meta-discipline chat owns: `udm-*` skills, `tools/pre_commit_checks.py`, `tools/claim_next_bn.py`, B-558 Phase 2.1 substrates
- Shared / coordination-required: `CLAUDE.md` (Do-NOT rules + CLI_* registry + L215 PARQUET_* family + L407 substrate enumeration), `docs/migration/BACKLOG.md`, `docs/migration/_validation_log.md`, `docs/migration/03_DECISIONS.md`
- B-562 Component A (`tools/claim_next_bn.py`) is the canonical B-N collision prevention mechanism; use BEFORE opening new B-Ns to avoid the `9b1d7fb`/`665f14d` collision class

## Empirical anchor

**Session arc theme**: started 2026-05-18 with operator question "I am testing the parquet data load process for large tables. How do I set up my env files and General.dbo.UDMTablesList to ensure that the AuditLog table from CCM loads parquet files properly into VendorFiles network drive?" -> arc covered R1 cohort SCD2 foundation (R1.3+R1.7+R1.8) + B-344 RB-15 adoption + D125 3-mode CDC dispatch plan + 7 D125 implementation B-N closures + B-547 RB-16 procedure rewrite + B-552 v1 closure + BLOCK remediation + B-564 forward-prevention test layer + 8 cross-cohort/second-pass gap-checks.

**Operator workflow now end-to-end complete** for D125 cutover (SMALL tables; large tables blocked on B-563):

```
# 1. Deploy schema (B-542)
python3 migrations/cdc_mode_column.py --apply --actor pipeline-lead --justification "D63+D125 schema deploy" --server dev

# 2. Flip table to shadow-write mode (B-546)
python3 tools/flip_cdc_mode.py --apply \
  --source CCM --table AuditLog --mode both \
  --actor pipeline-lead --justification "RB-16 Step 1: AuditLog 30-day shadow validation start"

# 3. Run pipeline (B-544 v1 dispatch writes Parquet + legacy CDC + SCD2)
python3 main_large_tables.py --table AuditLog --source CCM

# 4. Nightly parity check (B-545 v1 + B-553 + B-554)
python3 tools/validate_parquet_vs_stage.py --apply \
  --source CCM --table AuditLog \
  --actor automated --justification "RB-16 nightly parity sanity"

# 5. After >=30-day clean parity period, canonical cutover (SMALL tables -- orchestrator NotImplementedError REMOVED at 0c06961; large tables additionally require B-563):
python3 tools/flip_cdc_mode.py --apply \
  --source CCM --table AuditLog --mode parquet_snapshot \
  --actor pipeline-lead --justification "RB-16 Step 2: AuditLog canonical D2 cutover"
```

Steps 1-4 are PRODUCTION-READY at HEAD `0c06961`. Step 5 is PRODUCTION-READY for SMALL tables at HEAD `0c06961` (B-552 v1 closure removed orchestrator NotImplementedError); LARGE tables (3B+ rows) additionally require B-563 (day-N vs day-N-1 Parquet diff delete-detection) per B-552 v1 deferred-scope. B-555 (v2 per-PK hash) recommended before Step 5 for definitive parity interpretation. B-564 closure THIS COMMIT pins the apply-path test pattern that B-563 should follow.

---

*Refreshed 2026-05-19 per B-564 closure + D56 second-pass minor-finding inline remediation (per cross-cohort reviewer `aea6c9174151af2f5` ACCEPT verdict on `0c06961`). State-pointer is point-in-time (commit `0c06961` baseline + THIS COMMIT B-564 closure); refresh at next D125-arc substantive commit. Canonical deep-context substrate: `docs/migration/_session_snapshots/2026-05-19-7a810b9.md`.*
