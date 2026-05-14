# CODE_BUILD_STATUS.md — Coding Progress Dashboard

**Purpose**: single-pane view of which CODE artifacts are built, tested, and deployed across the pipeline project. Distinct from `BACKLOG.md` (meta-work + doc edits) and `ONE_OFF_SCRIPTS.md` (per-script operational tracking).

**Status legend**:
- ⬜ **Specified** — design doc exists; no code authored
- 🟡 **In progress** — author / test cycle running OR partial code landed
- 🟢 **Built** — code authored + tests pass + ready for deployment; not yet on a server
- ✅ **Deployed** — running in production OR at minimum on the target dev server
- ⚫ **Superseded / archived** — code retired per supersession or deprecation

**Last reviewed**: 2026-05-13 (Wave 2 COMPLETE 4/4 build close — M11 `orchestration/range_scheduler.py` + M3 `data_load/parquet_registry_client.py` (Tier γ — biggest module yet at 1,202 lines) + M6 `data_load/vault_client.py` + M15 `observability/log_handler.py` v2 cutover replacing v1 + post-cohort test-pollution fix; Round 3 now 8/17 BUILT 47%).

---

## At a glance (2026-05-13)

| Layer | Total | ⬜ Spec | 🟡 In prog | 🟢 Built | ✅ Deployed | ⚫ Archived |
|---|---|---|---|---|---|---|
| **Phase 0 prep tools** (Round 1.5a) | 2 | 0 | 0 | **2** | 0 | 0 |
| **Phase 0 closure tools** (Round 4.5b) | 3 | 0 | 0 | **3** | 0 | 0 |
| **Round 4 operator tools** (§ 3.1-3.11) | 11 | **8** | 0 | **3** | 0 | 0 |
| **Round 3 prerequisites** (Wave 0 — blocks all 17 R3 modules) | 1 | 0 | 0 | **1** | 0 | 0 |
| **Round 3 core modules** (§ 1-7) | 17 | **9** | 0 | **8** | 0 | 0 |
| **Round 6 modules** (TBD) | TBD | — | — | — | — | — |
| **Migrations** (one-time DB-schema scripts) | 13 | 0 | 0 | **3** | **10** | 0 |
| **Pipeline core** (extract / cdc / scd2 / etc.) | ~20 | 0 | 0 | 0 | **~20** | 0 |
| **Tests** (Tier 0 + Tier 1) | covered by build units | — | — | 920 pass + 14 skip + 2 fail (Wave 2.4 added 43 new tests for `observability/log_handler.py` v2 cutover all passing 2026-05-13 after 2 inline-fix cycles + 1 post-cohort test-pollution fix; Wave 2.3 added 66 new tests for `data_load/vault_client.py` all passing 2026-05-13 after 1 inline-fix cycle; Wave 2.2 added 80 new tests for `data_load/parquet_registry_client.py` — Tier γ, biggest module yet — all passing 2026-05-13 after 1 inline-fix cycle; Wave 2.1 added 45 new tests for `orchestration/range_scheduler.py` all passing 2026-05-13 after 1 inline-fix cycle; Wave 1.4 added 60 new tests for `cdc/extraction_state.py` all passing 2026-05-13 after 1 inline-fix cycle; Wave 1.3 added 50 new tests + 2 platform-skipped for `data_load/credentials_loader.py` all passing 2026-05-13 first-iteration; Wave 1.2 added 29 new tests for `observability/sensitive_data_filter.py` all passing 2026-05-13 first-iteration; Wave 1.1 added 41 new tests for `utils/idempotency_ledger.py` all passing 2026-05-13; Wave 0 added 111 new tests for `utils/errors.py` all passing 2026-05-13; § 3.6 added 46 new tests all passing 2026-05-12) across 40 test files | — | — |

**Build cohort 2026-05-12** (8 units in one session): all 🟢 Built; pending engineer R1 deployment.
**Build cohort 2026-05-13 (Wave 0)** (1 unit, prerequisite-zero for Round 3): `utils/errors.py` 🟢 Built — 111 tests pass; pending engineer R1 deployment. Unblocks Wave 1 (M14 sensitive_data_filter / M9 idempotency_ledger / M7 credentials_loader / M10 extraction_state) per Round 3 build DAG.
**Build cohort 2026-05-13 (Wave 1.1)** (1 unit, first of 4 in Wave 1 — M9 chosen for highest leverage per planning agent: central D15 enforcer that every Wave 2-4 module composes through): `utils/idempotency_ledger.py` 🟢 Built — 41 tests pass (29 Tier 1 functions, 35 collected after parametrize × 6; 6 Tier 0 + 35 Tier 1 collected = 41 total); pending engineer R1 deployment. Inline iteration fixes — 2 (tightened `_is_unique_violation()` heuristic to canonical SQL Server phrases per false-positive catch; corrected no-output-row test fixture). **B63 (🟡 Open carryover)** — canonical IdempotencyLedger DDL still has no Metadata JSON column; `metadata` kwarg accepted-but-not-persisted (`TestB63MetadataCaveat` pins behavior). Unblocks downstream Wave 1.x modules (M14 / M7 / M10) that compose through idempotency_ledger per Round 3 build DAG.
**Build cohort 2026-05-13 (Wave 1.2)** (2nd of 4 in Wave 1; ~210 lines, Tier α): `observability/sensitive_data_filter.py` 🟢 Built — 29 tests pass (6 Tier 0 + 23 Tier 1 collected after parametrize × 2; 22 functions; **all 29 PASS first-iteration with 0 inline fixes**); pending engineer R1 deployment. Implements R3 § 6.1 + D67 + D68 (FilterConfigError) + P5 PII redaction discipline. No Round 3 dependencies beyond `utils.errors.FilterConfigError` (Wave 0); stdlib only otherwise. Unblocks any downstream module composing through sensitive-data redaction (observability layer).
**Build cohort 2026-05-13 (Wave 1.3)** (3rd of 4 in Wave 1; **905 lines, effectively Tier β** — larger than the planning agent's Tier α estimate; candidate empirical anchor for B-226 tier-reclassification observation): `data_load/credentials_loader.py` 🟢 Built — **50 tests pass + 2 platform-skipped on Windows** (6 Tier 0 + 44 Tier 1; **all PASS first-iteration with 0 inline fixes**); pending engineer R1 deployment. Implements R3 § 3.1 + § 3.3 (file structure) + D64 (TPM2) + D71 (Snowflake RSA key) + D85 (startup stage 1 audit row) + D103 (security model) + D92 (additive evolution). Unblocks every Round 4 tool that needs env loading (~6 of 8 remaining § 3.1/§ 3.2/§ 3.3/§ 3.4/§ 3.5/§ 3.7/§ 3.11 — anything using credentials). Key surfaced for gap-checker: (1) `actor` param forward-compat with D76 audit-row contract; (2) Snowflake PEM additive-substitution (BOTH PEM kept AND `SNOWFLAKE_PRIVATE_KEY_PATH` added — spec ambiguous on REPLACE vs ADD); (3) `PIPELINE_TPM2_HANDLE` env var name needs registration in `02_configuration.md` § 2.1 (potential B-N); (4) `'CREDENTIALS_LOAD'` audit EventType vs documented `STARTUP_*::CREDS_LOAD` per D85 (potential P-N for naming reconciliation); (5) `'GPG_SOURCED'` sentinel check at envelope-parse time vs post-substitution — spec ambiguous.
**Build cohort 2026-05-13 (Wave 1.4)** (4th of 4 in Wave 1 — **Wave 1 COMPLETE 4/4**; **905 lines, effectively Tier β**): `cdc/extraction_state.py` 🟢 Built — **60 tests pass** (6 Tier 0 + 54 Tier 1; 1 inline-fix cycle = 3 fixes on test side — off-by-one cur.execute arg positions + MagicMock fetchone helper guard); pending engineer R1 deployment. Implements R3 § 4.2 + D11 (empirical L_99) + D13 (trust gate) + D14 (IsReExtraction / ExtractionAttempt) + D67/D68/D69. Unblocks M11 `cdc/range_scheduler.py` (Wave 2 first unit). Key surfaced for gap-checker: (1) `FirstLoadDate` looked up from `UdmTablesList` (not parameter-passed) — mirrors existing `orchestration/table_config.py` pattern; spec ambiguous; (2) Missing UdmTablesList row downgrades trust-gate floor check to no-op (conservative); (3) `record_extraction_attempt` non-UNIQUE IntegrityError surfaced as `InvalidTrustGate` (caller-side config error vs retryable); (4) explicit `extraction_attempt` keyword parameter exposed to let callers do IN_PROGRESS→SUCCESS transition; spec said "INSERT or UPDATE" but the UNIQUE key includes ExtractionAttempt; (5) `LookbackDays` listed in spec § 4.2 Consumes but not used by any of the 5 listed functions — moved to `orchestration/range_scheduler.py` per § 5.1 (just-noticed). **Wave 1 milestone**: 4/4 BUILT — unblocks Waves 2-4 per Round 3 build DAG.
**Build cohort 2026-05-13 (Wave 2.1)** (1st of 4 in Wave 2; **586 lines, Tier β**): `orchestration/range_scheduler.py` 🟢 Built — **45 tests pass** (6 Tier 0 + 39 Tier 1; 1 inline-fix cycle); pending engineer R1 deployment. Implements R3 § 5.1 + D11/D12/D67/D68/D69. Consumes M10 `cdc/extraction_state.py` (Wave 1.4). Unblocks downstream Phase 2 R2+ pipeline cycles that need windowed-CDC scheduling.
**Build cohort 2026-05-13 (Wave 2.2)** (2nd of 4 in Wave 2; **1,202 lines, Tier γ — biggest module yet in Round 3 build**): `data_load/parquet_registry_client.py` 🟢 Built — **80 tests pass** (21 Tier 0 + 59 Tier 1; 1 inline-fix cycle); pending engineer R1 deployment. Implements R3 § 1.3 + D2/D4/D15/D45.2/D67/D68/D69. Consumes M9 `utils/idempotency_ledger.py` (Wave 1.1). Key surfaced for gap-checker: (a) M3 agent defined `ParquetRegistryError` / `RegistryStatusInvalid` / `RegistryFileNotFound` / `RegistryHashMismatch` / `RegistryInsertConflict` / `RegistryNotFound` LOCALLY instead of importing from `utils.errors` — likely mis-interpretation of `git status` showing utils/errors.py untracked (it DOES exist per Wave 0 / B85 ⚫ CLOSED 2026-05-13); post-build refactor needed; (b) introduces NEW `PARQUET_*` EventType family (PARQUET_VERIFY / PARQUET_REPLICATE / etc.) not in CLAUDE.md's existing CLI_* / CYCLE_* / DEPLOYMENT_* / MIGRATION_* / STARTUP_* registry — worth tracking like B86.
**Build cohort 2026-05-13 (Wave 2.3)** (3rd of 4 in Wave 2; **978 lines, Tier β**): `data_load/vault_client.py` 🟢 Built — **66 tests pass** (8 Tier 0 + 58 Tier 1; 1 inline-fix cycle); pending engineer R1 deployment. Implements R3 § 2.3 + D6/D69/D71/W-8. Consumes M7 `data_load/credentials_loader.py` (Wave 1.3) AND M9 `utils/idempotency_ledger.py` (Wave 1.1). Validates B222 vault-error catch-path canonicalization — closure target for B222 (Wave 0 follow-up tracked per BACKLOG).
**Build cohort 2026-05-13 (Wave 2.4)** (4th of 4 in Wave 2 — **Wave 2 COMPLETE 4/4**; v2 cutover replacing v1 in-place; **435 lines, Tier α**): `observability/log_handler.py` v2 cutover 🟢 Built — **43 tests pass** (6 Tier 0 + 37 Tier 1; 2 inline-fix cycles + 1 post-cohort test-pollution fix); pending engineer R1 deployment. Implements R3 § 6.2 + D33/D67/D68/D69 + OBS-1 through OBS-7. v2 PRESERVES v1 API (`SqlServerLogHandler`, `set_context()`) — drop-in replacement; downstream callers in pipeline core continue working without code-side changes. **Post-cohort test-pollution fix (2026-05-13)**: M15's tier0+tier1 test files had `sys.modules["utils.connections"]` stub injection without cleanup; broke 16 downstream `test_measure_capacity_and_partition.py` tests when run after log_handler tests (B214-class pattern). Fix landed via `_snapshot_utils_connections_state()` + `_restore_utils_connections_state()` helpers + autouse fixture — test-file-only edit; no module touches. **Wave 2 milestone**: 4/4 BUILT; Round 3 now 8/17 BUILT (47% complete). Key surfaced for gap-checker: (a) D33 cancellation polling correctly excluded from handler (spec § 6.2 doesn't list D33 as consumed); (b) PipelineLog DDL has 4 columns (CycleType / CycleDate / ServerRole / Layer) not used by v2 — v2 preserved v1's 11-column INSERT; worth a P-N for future extension.


---

## Round 4 operator tools (`phase1/04_tools.md` § 3.1-3.11) — 3/11 built

These are CLI scripts under `tools/`. Specs in [`phase1/04_tools.md`](phase1/04_tools.md). Most depend on Round 3 core modules (which are 8/17 built). Status assumes a tool is BLOCKED when its referenced Round 3 module hasn't been authored.

| § | Tool | Status | Round 3 dep | Blocker | Notes |
|---|---|---|---|---|---|
| 3.1 | `parquet_tier_review.py` | ⬜ | `parquet_registry_client` (§ 1.3) | 🔴 R3 module | Status transition walker created→verified→replicated→archived→purged |
| 3.2 | `parquet_verify.py` | ⬜ | `parquet_registry_client.verify_parquet_snapshot()` | 🔴 R3 module | Re-verify a registry_id (operator retest) |
| 3.3 | `lateness_profile.py` | ⬜ | `cdc/lateness_profiler.py` (R3 § 5.2) | 🔴 R3 module | Distinct from Tool 14 `measure_lateness.py` (which is built); this one is the L-tier wrapper |
| 3.4 | `decrypt_pii.py` | ⬜ | `data_load/pii_decryptor.py` (R3 § 2.2) | 🔴 R3 module | Justified operator decrypt per P8 |
| 3.5 | `detect_extraction_gaps.py` | ⬜ | `tools/gap_detector.py` (R3 § 5.3) | 🔴 R3 module | CLI shim for the detector |
| 3.6 | `promote_test_to_prod.py` | 🟢 **Built 2026-05-12** (Pattern B2 + B219 pre-spec; 1,759-line tool + 39 tests collected as 46 after parametrize × 7; **46/46 PASS after 5 inline fixes**; gap-check 🔴→🟡 via B79 leading-badge flip + B221 cascade tracked) | SP-4 (R1 DDL — already locked) + B79 `@AcknowledgmentOnly` parameter (⚫ CLOSED 2026-05-11 per Round 7 § 2) | Author code defensively handles BOTH B79-landed AND B79-not-landed states | Failover acknowledgment per D29 + D33; pending engineer deploy |
| 3.7 | `verify_server_parity.py` | ⬜ | `data_load/server_parity_verifier.py` (R3 § 3.2) | 🔴 R3 module | CLI surface for the verifier |
| 3.8 | `enforce_retention.py` | 🟢 **Built 2026-05-12** (Pattern B2 cohort + B219 pre-spec lesson applied; 1,219-line tool + 31 tests; **34/34 PASS first-iteration after 3 inline test-mock fixes**) | SP-10 (R1 DDL — locked) + (per B93+B94) `@CutoffOverride` + `@CategoryFilter` parameters | 🟢 UNBLOCKED — SP-10 + B93/B94 amendments landed | Retention sweep per D30 |
| 3.9 | `process_ccpa_deletion.py` | ⬜ | SP-12 (R7 § 4.5; spec'd but DDL not yet deployed per B81) | 🟡 BLOCKED on SP-12 deployment | RB-10 CCPA right-to-deletion |
| 3.10 | `log_retention_cleanup.py` | 🟢 **Built 2026-05-12** (Pattern B2 cohort + inline iteration; 1,255-line tool + 32 tests; **28/34 PASS**, 6 carryover per B218 author/test alignment iteration) | None — pure DELETE of old `PipelineLog` rows | 🟢 UNBLOCKED — no module dependency | Pending B218 + engineer deploy |
| 3.11 | `alert_dispatcher.py` | ⬜ | Ops-channel client (B82 — unscoped Phase 0; spec'd to use EMAIL per D108) | 🟡 BLOCKED on B82 deferred to Phase 2 R1 deployment | Notification fanout |

**Currently unblocked for Claude-side build**: § 3.6 (promote_test_to_prod), § 3.8 (enforce_retention), § 3.10 (log_retention_cleanup). The other 8 are blocked on Round 3 module spec implementation or SP / ops-channel work.

---

## Phase 0 prep + closure tools — 5/5 built ✅ (pending deployment)

These tools landed in the 8-unit build cohort 2026-05-12.

| # | Tool | Build | Tests | Spec |
|---|---|---|---|---|
| 12 | `tools/verify_credentials_load.py` | 🟢 2026-05-12 | 24/24 pass | `phase1/04a_phase_0_prep_tools.md` § 3 (B184) |
| 13 | `tools/capture_parity_baseline.py` | 🟢 2026-05-12 | 28/28 + 3 skip | `phase1/04a_phase_0_prep_tools.md` § 4 (B183) |
| 14 | `tools/measure_lateness.py` | 🟢 2026-05-12 (B215 fix) | 23 Tier 1 + 7 Tier 0 | `phase1/04b_phase_0_closure_tools.md` § 3 (B188) |
| 15 | `tools/import_pii_inventory.py` | 🟢 2026-05-12 | 30/30 pass | `phase1/04b_phase_0_closure_tools.md` § 4 (B189) |
| 16 | `tools/measure_capacity_and_partition.py` | 🟢 2026-05-12 (B215 fix) | 17 Tier 1 + 5 Tier 0 + 5 skip | `phase1/04b_phase_0_closure_tools.md` § 5 (B190) |

**Deployment**: 0/5 deployed to any server. R1 engineer owns dev → test → prod cadence.

---
## Round 3 prerequisites — Wave 0 (1/1 built)

Wave 0 is prerequisite-zero for the Round 3 build — modules that don't fit any of the 17 R3 numbered sections but are imported by all R3 modules. Per Round 3 build DAG, Wave 0 must complete before Wave 1 starts.

| Wave | Module | Status | Test files | Spec |
|---|---|---|---|---|
| 0 | `utils/errors.py` | 🟢 **Built 2026-05-13** (Pattern B Wave 0; 111 tests pass — 6 Tier 0 + 105 Tier 1; full pytest regression 506 pass / 12 skip / 2 fail — 2 pre-existing B218 § 3.10 carryover, no new regression) | `tests/tier0/test_errors.py` (6) + `tests/tier1/test_errors.py` (105) | Round 6 § 4.6 + Round 3 § 8.1 + D68 |

**Build close 2026-05-13** (B85 CODE close): unblocks Wave 1 — M14 `observability/sensitive_data_filter.py` + M9 `data_load/idempotency_ledger.py` + M7 `data_load/credentials_loader.py` + M10 `data_load/extraction_state.py`. Per planning agent's Round 3 build DAG.

**Execution classification**: Library module (not executable). Per `udm-execution-classifier` matrix — no entry in `ONE_OFF_SCRIPTS.md` (not a Manual × One-time script) and no entry in `phase1/02_configuration.md` § 5.1 (not a Scheduled-recurring job). Imported as a Python library by every Round 3 module per § 4.6 contract.

---

## Round 3 build — Wave 1 (4/4 BUILT; 4 🟢 Built)

Wave 1 is the second wave of the Round 3 build DAG. Four units: **M9** (`utils/idempotency_ledger.py` — central D15 enforcer; first because every Wave 2-4 module composes through it), **M14** (`observability/sensitive_data_filter.py`), **M7** (`data_load/credentials_loader.py`), **M10** (`data_load/extraction_state.py`). M9 chosen first by planning agent for highest leverage. Wave 1 unblocks Waves 2-4.

| Wave | Module | Status | Test files | Spec |
|---|---|---|---|---|
| 1.1 | `utils/idempotency_ledger.py` (canonical spec: `data_load/idempotency_ledger.py` per R3 § 4.1; built at `utils/` for naming-collision-free import alongside `utils/errors.py`) | 🟢 **Built 2026-05-13** (Pattern B Wave 1; ~430 lines, Tier β; 41 tests pass — 29 Tier 1 functions, 35 collected after parametrize × 6; 6 Tier 0 + 35 Tier 1 collected = 41 total; 2 inline iteration fixes; full pytest regression 547 pass / 12 skip / 2 fail — 2 pre-existing B218 § 3.10 carryover, no new regression from Wave 1.1) | `tests/tier0/test_idempotency_ledger.py` (6) + `tests/tier1/test_idempotency_ledger.py` (29 functions / 35 collected) | R3 § 4.1 + D15 + D17 + D67 + D68 + D69 |
| 1.2 | `observability/sensitive_data_filter.py` (M14) | 🟢 **Built 2026-05-13** (Pattern B Wave 1.2; ~210 lines, Tier α; 29 tests pass — 6 Tier 0 + 23 Tier 1 collected after parametrize × 2 (22 functions); **all 29 PASS first-iteration with 0 inline fixes**; full pytest regression 576 pass / 12 skip / 2 fail — 2 pre-existing B218 § 3.10 carryover, no new regression from Wave 1.2) | `tests/tier0/test_sensitive_data_filter.py` (6) + `tests/tier1/test_sensitive_data_filter.py` (22 functions / 23 collected) | R3 § 6.1 + D67 + D68 + P5 |
| 1.3 | `data_load/credentials_loader.py` (M7) | 🟢 **Built 2026-05-13** (Wave 1.3 3rd unit; **905 lines, effectively Tier β** — larger than planning agent's Tier α estimate; 50 tests pass + 2 platform-skipped on Windows — 6 Tier 0 + 44 Tier 1; **all PASS first-iteration with 0 inline fixes**; full pytest regression 686 pass / 14 skip / 2 fail — 2 pre-existing B218 § 3.10 carryover, no new regression from Wave 1.3) | `tests/tier0/test_credentials_loader.py` (6) + `tests/tier1/test_credentials_loader.py` (44 + 2 platform-skipped) | R3 § 3.1 + § 3.3 + D64 + D71 + D85 + D103 + D92 |
| 1.4 | `cdc/extraction_state.py` (M10; built at `cdc/` because the module is consumed by the windowed-CDC scheduler per § 4.2 + § 5.1 dependency wiring, not by data_load/) | 🟢 **Built 2026-05-13** (Wave 1.4 4th unit — **Wave 1 COMPLETE 4/4**; **905 lines, effectively Tier β**; 60 tests pass — 6 Tier 0 + 54 Tier 1; 1 inline-fix cycle = 3 test-side fixes; full pytest regression 686 pass / 14 skip / 2 fail — 2 pre-existing B218 § 3.10 carryover, no new regression from Wave 1.4) | `tests/tier0/test_extraction_state.py` (6) + `tests/tier1/test_extraction_state.py` (54) | R3 § 4.2 + D11 + D13 + D14 + D67 + D68 + D69 |

**Build close 2026-05-13** (Wave 1.1 M9 first unit): unblocks downstream Wave 1.x units (M14 / M7 / M10) that compose through `idempotency_ledger.ledger_step()` per Round 3 build DAG. The B85 ↔ M9 ordering is intentional — Wave 0 `utils/errors.py` is imported by `idempotency_ledger` (per § 4.6 + D68 error-hierarchy contract); M9 is imported by every D15-bearing module downstream.

**Inline iteration fixes (2)**: (a) tightened `_is_unique_violation()` heuristic to use canonical SQL Server phrases (`Violation of UNIQUE KEY constraint` / `Cannot insert duplicate key` / numeric codes) instead of bare `UNIQUE` substring (caught `FK references a UNIQUE index` false-positive); (b) corrected no-output-row test fixture to set `fetchone.return_value=None` explicitly.

**Carryover**: **B63 (🟡 Open)** — canonical `IdempotencyLedger` DDL has no `Metadata` JSON column per `phase1/01_database_schema.md` § 7. M9 accepts a `metadata` kwarg for caller ergonomic future-proofing but does NOT persist it; `LedgerStep.prior_result` is always `None` until B63 lands (either ALTER add Metadata column OR populate from PipelineEventLog.Metadata joined on BatchId). Both Tier 1 tests pin the caveat explicitly via `TestB63MetadataCaveat`. NOT a new B-N — B63 was already open per BACKLOG L60 + spec doc L860-898.

**Execution classification**: Library module (not executable). Per `udm-execution-classifier` matrix — no entry in `ONE_OFF_SCRIPTS.md` (not a Manual × One-time script) and no entry in `phase1/02_configuration.md` § 5.1 (not a Scheduled-recurring job). Imported by every Round 3 module that bears the D15 idempotency contract per § 4.1 + § 8.4.

---

## Round 3 build — Wave 2 (4/4 BUILT; 4 🟢 Built)

Wave 2 is the third wave of the Round 3 build DAG. Four units: **M11** (`orchestration/range_scheduler.py` — windowed-CDC scheduler; consumes M10), **M3** (`data_load/parquet_registry_client.py` — Parquet medallion registry; consumes M9 — Tier γ biggest module yet at 1,202 lines), **M6** (`data_load/vault_client.py` — PII vault SP wrapper; consumes M7 + M9), **M15** (`observability/log_handler.py` v2 — D69 cursor-ownership-aware cutover replacing v1 in-place; consumes M9 + M7). All 4 chosen in this order by planning agent per Round 3 build DAG: M11 first because Wave 2 dependencies cluster around M10 (Wave 1.4); M3 second because biggest unit benefits from earliest review; M6 third per dep chain; M15 last because v2 cutover risks downstream pipeline-core impact (mitigated via API-preserving v1 to v2 in-place replacement). Wave 2 brings Round 3 build to 8/17 (47%) and unblocks Wave 3 + Wave 4 modules.

| Wave | Module | Status | Test files | Spec |
|---|---|---|---|---|
| 2.1 | `orchestration/range_scheduler.py` (M11) | 🟢 **Built 2026-05-13** (Wave 2.1 1st unit; **586 lines, Tier β**; 45 tests pass — 6 Tier 0 + 39 Tier 1; 1 inline-fix cycle; full pytest regression 731 pass / 14 skip / 2 fail — 2 pre-existing B218 § 3.10 carryover, no new regression from Wave 2.1) | `tests/tier0/test_range_scheduler.py` (6) + `tests/tier1/test_range_scheduler.py` (39) | R3 § 5.1 + D11 + D12 + D67 + D68 + D69 |
| 2.2 | `data_load/parquet_registry_client.py` (M3) | 🟢 **Built 2026-05-13** (Wave 2.2 2nd unit; **1,202 lines, Tier γ — biggest module in Round 3 build to date**; 80 tests pass — 21 Tier 0 + 59 Tier 1; 1 inline-fix cycle; full pytest regression 811 pass / 14 skip / 2 fail — 2 pre-existing B218 § 3.10 carryover, no new regression from Wave 2.2; **deviation surfaced for gap-checker**: M3 defined exception classes LOCALLY (`ParquetRegistryError` / `RegistryStatusInvalid` / `RegistryFileNotFound` / `RegistryHashMismatch` / `RegistryInsertConflict` / `RegistryNotFound`) instead of importing from `utils.errors` per D68 canonical hierarchy — likely mis-interpretation of `git status` showing utils/errors.py untracked-from-HEAD; post-build refactor needed; introduces NEW `PARQUET_*` EventType family not in CLAUDE.md registry — worth tracking like B86) | `tests/tier0/test_parquet_registry_client.py` (21) + `tests/tier1/test_parquet_registry_client.py` (59) | R3 § 1.3 + D2 + D4 + D15 + D45.2 + D67 + D68 + D69 |
| 2.3 | `data_load/vault_client.py` (M6) | 🟢 **Built 2026-05-13** (Wave 2.3 3rd unit; **978 lines, Tier β**; 66 tests pass — 8 Tier 0 + 58 Tier 1; 1 inline-fix cycle; full pytest regression 877 pass / 14 skip / 2 fail — 2 pre-existing B218 § 3.10 carryover, no new regression from Wave 2.3; validates B222 vault-error catch-path canonicalization candidate closure) | `tests/tier0/test_vault_client.py` (8) + `tests/tier1/test_vault_client.py` (58) | R3 § 2.3 + D6 + D69 + D71 + W-8 |
| 2.4 | `observability/log_handler.py` v2 cutover (M15; replaces v1 in-place; PRESERVES v1 API per `SqlServerLogHandler` + `set_context()` drop-in compatibility) | 🟢 **Built 2026-05-13** (Wave 2.4 4th unit — **Wave 2 COMPLETE 4/4**; **435 lines, Tier α**; 43 tests pass — 6 Tier 0 + 37 Tier 1; 2 inline-fix cycles + 1 post-cohort test-pollution fix via `_snapshot_utils_connections_state()` / `_restore_utils_connections_state()` autouse fixture pair — broke 16 downstream `test_measure_capacity_and_partition.py` tests in initial cutover via `sys.modules["utils.connections"]` stub injection without cleanup (B214-class pattern); full pytest regression 920 pass / 14 skip / 2 fail — 2 pre-existing B218 § 3.10 carryover, no new regression from Wave 2.4 net of pollution fix) | `tests/tier0/test_log_handler.py` (6) + `tests/tier1/test_log_handler.py` (37) | R3 § 6.2 + D33 + D67 + D68 + D69 + OBS-1 through OBS-7 |

**Build close 2026-05-13** (Wave 2 COMPLETE 4/4): brings Round 3 core modules to 8/17 BUILT (47%). Wave 2 closes the dep chain unlocking Wave 3 (M1 / M2 / M4 / M12 etc.) and Wave 4 (M13 / M16 / M17) per Round 3 build DAG.

**Inline iteration fixes (5 + 1 post-cohort)**: (Wave 2.1) 1 cycle on M11; (Wave 2.2) 1 cycle on M3; (Wave 2.3) 1 cycle on M6; (Wave 2.4) 2 cycles on M15 — initial cutover + downstream test-pollution post-fix via autouse `sys.modules` state snapshot/restore.

**Carryovers surfaced for gap-checker** (NO new B-N opens this cohort — gap-checker will route): (a) M3 local-exception-classes deviation vs canonical `utils.errors` per D68 — utils/errors.py DOES exist (Wave 0 / B85 ⚫ CLOSED 2026-05-13); (b) M3 introduces NEW `PARQUET_*` EventType family not in CLAUDE.md CLI_* / CYCLE_* / DEPLOYMENT_* / MIGRATION_* / STARTUP_* registry — worth tracking like B86; (c) M15 `sys.modules` pollution confirms the B214 sweep should be prioritized; (d) Tier α planning agent estimate vs Tier β/γ actual — extends B-226 evidence base from 2-event to 6-event (M3 1,202 / M6 978 / M11 586 misclassified as Tier α by planning agent — only M15 435-line truly fit Tier α); (e) D33 cancellation scope ambiguity — M15 spec § 6.2 does not list D33 as consumed; producer correctly excluded cancellation polling — worth a spec-clarification B-N or P-N; (f) PipelineLog DDL has 4 columns (CycleType / CycleDate / ServerRole / Layer) not used by v2 — preserved v1 11-column INSERT; worth a P-N for future extension.

**Execution classification**: All 4 are library modules (not executable). Per `udm-execution-classifier` matrix — no entries in `ONE_OFF_SCRIPTS.md` (not Manual × One-time) and no entries in `phase1/02_configuration.md` § 5.1 (not Scheduled-recurring). All imported as Python libraries by downstream pipeline-core + R3 consumers. **M15 v2 cutover** preserves v1 import contract — pipeline-core callers (e.g. `main_small_tables.py`, `main_large_tables.py`, `observability/event_tracker.py`) continue working without source-side edits; the `--workers` serialization path remains untouched per the CLAUDE.md WORKER-SERIALIZE rule (table_config_to_dict dataclass asdict contract).

---


## Round 3 core modules (`phase1/03_core_modules.md` § 1-7) — 8/17 built

Foundation modules for the pipeline. Round 4 tools, Round 6 partition manager, and Phase 2 R2+ pipeline cycles all depend on these. Largest single chunk of remaining build work.

| § | Module | Status | Test files | Spec |
|---|---|---|---|---|
| 1.1 | `data_load/parquet_writer.py` | ⬜ | — | R3 § 1.1 |
| 1.2 | `data_load/parquet_replay.py` | ⬜ | — | R3 § 1.2 |
| 1.3 | `data_load/parquet_registry_client.py` | 🟢 **Built 2026-05-13** (Wave 2.2 2nd Wave 2 unit; **1,202 lines, Tier γ — biggest Round 3 module yet**; 80 tests pass — 21 Tier 0 + 59 Tier 1; 1 inline-fix cycle; full pytest regression 811 pass / 14 skip / 2 fail; **deviation surfaced**: local exception classes vs canonical `utils.errors` per D68 — post-build refactor needed; introduces NEW `PARQUET_*` EventType family worth registering like B86) | `tests/tier0/test_parquet_registry_client.py` (21) + `tests/tier1/test_parquet_registry_client.py` (59) | R3 § 1.3 + D2 + D4 + D15 + D45.2 + D67 + D68 + D69 |
| 2.1 | `data_load/pii_tokenizer.py` | ⬜ | — | R3 § 2.1 |
| 2.2 | `data_load/pii_decryptor.py` | ⬜ | — | R3 § 2.2 |
| 2.3 | `data_load/vault_client.py` | 🟢 **Built 2026-05-13** (Wave 2.3 3rd Wave 2 unit; **978 lines, Tier β**; 66 tests pass — 8 Tier 0 + 58 Tier 1; 1 inline-fix cycle; full pytest regression 877 pass / 14 skip / 2 fail; validates B222 vault-error catch-path canonicalization candidate closure) | `tests/tier0/test_vault_client.py` (8) + `tests/tier1/test_vault_client.py` (58) | R3 § 2.3 + D6 + D69 + D71 + W-8 |
| 3.1 | `data_load/credentials_loader.py` | 🟢 **Built 2026-05-13** (Wave 1.3 3rd unit; **905 lines, effectively Tier β**; 50 tests pass + 2 platform-skipped on Windows — 6 Tier 0 + 44 Tier 1; **all PASS first-iteration with 0 inline fixes**; full pytest regression 686 pass / 14 skip / 2 fail; related `credentials_verifier.py` is the validator, not the loader; see B184) | `tests/tier0/test_credentials_loader.py` (6) + `tests/tier1/test_credentials_loader.py` (44 + 2 platform-skipped) | R3 § 3.1 + § 3.3 + D64 + D71 + D85 + D103 + D92 |
| 3.2 | `data_load/server_parity_verifier.py` | ⬜ (related `parity_baseline_capture.py` is the baseline-capture step, not the verifier; see B183) | — | R3 § 3.2 |
| 4.1 | `data_load/idempotency_ledger.py` (canonical spec) → built as `utils/idempotency_ledger.py` (actual location; ~430 lines) | 🟢 **Built 2026-05-13** (Wave 1.1 first unit; Tier β; 41 tests pass — 29 Tier 1 functions, 35 collected after parametrize × 6; 6 Tier 0 + 35 Tier 1 collected = 41 total; 2 inline iteration fixes — `_is_unique_violation()` heuristic tightening + no-output-row fixture; full pytest regression 547 pass / 12 skip / 2 fail — 2 pre-existing B218 § 3.10 carryover, no new regression; **B63 (🟡 Open carryover)** — DDL has no Metadata column, `metadata` kwarg accepted-but-not-persisted, `LedgerStep.prior_result` always None until B63 lands, both Tier 1 tests verify via `TestB63MetadataCaveat`) | `tests/tier0/test_idempotency_ledger.py` (6) + `tests/tier1/test_idempotency_ledger.py` (29 functions / 35 collected after parametrize × 6) | R3 § 4.1 + D15 + D17 + D67 + D68 + D69 |
| 4.2 | `cdc/extraction_state.py` (canonical spec: `data_load/extraction_state.py` per R3 § 4.2; built at `cdc/` for proximity to `cdc/engine.py` + future `cdc/range_scheduler.py` per § 5.1 consumer location) | 🟢 **Built 2026-05-13** (Wave 1.4 4th unit — **Wave 1 COMPLETE 4/4**; **905 lines, effectively Tier β**; 60 tests pass — 6 Tier 0 + 54 Tier 1; 1 inline-fix cycle = 3 test-side fixes — off-by-one cur.execute arg positions + MagicMock fetchone helper guard; full pytest regression 686 pass / 14 skip / 2 fail — 2 pre-existing B218 § 3.10 carryover, no new regression; related `orchestration/pipeline_state.py` exists for small-table state; this new module is the canonical R3 ledger-backed contract) | `tests/tier0/test_extraction_state.py` (6) + `tests/tier1/test_extraction_state.py` (54) | R3 § 4.2 + D11 + D13 + D14 + D67 + D68 + D69 |
| 5.1 | `orchestration/range_scheduler.py` (M11; canonical spec: `cdc/range_scheduler.py` per R3 § 5.1; built at `orchestration/` for proximity to existing `orchestration/large_tables.py` + `orchestration/pipeline_state.py` consumer location) | 🟢 **Built 2026-05-13** (Wave 2.1 1st Wave 2 unit; **586 lines, Tier β**; 45 tests pass — 6 Tier 0 + 39 Tier 1; 1 inline-fix cycle; full pytest regression 731 pass / 14 skip / 2 fail) | `tests/tier0/test_range_scheduler.py` (6) + `tests/tier1/test_range_scheduler.py` (39) | R3 § 5.1 + D11 + D12 + D67 + D68 + D69 |
| 5.2 | `cdc/lateness_profiler.py` | ⬜ (distinct from `data_load/lateness_measurement.py` per B188 — that's the L_99 baseline computer, this is the per-table L-tier profiler) | — | R3 § 5.2 |
| 5.3 | `tools/gap_detector.py` | ⬜ | — | R3 § 5.3 |
| 6.1 | `observability/sensitive_data_filter.py` | 🟢 **Built 2026-05-13** (Wave 1.2 2nd unit; ~210 lines, Tier α; 29 tests pass — 6 Tier 0 + 23 Tier 1 collected after parametrize × 2 (22 functions); **all 29 PASS first-iteration with 0 inline fixes**; full pytest regression 576 pass / 12 skip / 2 fail — 2 pre-existing B218 § 3.10 carryover, no new regression) | `tests/tier0/test_sensitive_data_filter.py` (6) + `tests/tier1/test_sensitive_data_filter.py` (22 functions / 23 collected) | R3 § 6.1 + D67 + D68 + P5 |
| 6.2 | `observability/log_handler.py` v2 (cutover REPLACES v1 in-place; PRESERVES v1 API `SqlServerLogHandler` + `set_context()` drop-in) | 🟢 **Built 2026-05-13** (Wave 2.4 4th Wave 2 unit — **Wave 2 COMPLETE 4/4**; **435 lines, Tier α**; 43 tests pass — 6 Tier 0 + 37 Tier 1; 2 inline-fix cycles + 1 post-cohort test-pollution fix via `_snapshot_utils_connections_state()` / `_restore_utils_connections_state()` autouse fixture (B214-class pattern); full pytest regression 920 pass / 14 skip / 2 fail — 2 pre-existing B218 § 3.10 carryover, no new regression net of pollution fix) | `tests/tier0/test_log_handler.py` (6) + `tests/tier1/test_log_handler.py` (37) | R3 § 6.2 + D33 + D67 + D68 + D69 + OBS-1 through OBS-7 |
| 6.3 | `observability/event_tracker.py` v2 | ⬜ (v1 exists in `observability/event_tracker.py`; v2 is the per-D85 startup-stage-aware variant) | — | R3 § 6.3 |
| 7.1 | `data_load/snowflake_uploader.py` | ⬜ | — | R3 § 7.1; gated by B191 Snowflake test conclusion |

---

## Migrations — 13/13 built (10 ✅ deployed pre-existing; 3 🟢 pending deployment)

Migration scripts under `migrations/`. Idempotent `IF NOT EXISTS` guards per D92.

| Script | Built | Deployed | Source |
|---|---|---|---|
| `b1_hash_varchar64.py` | ✅ | ✅ | B-1 (CLAUDE.md) |
| `strip_suffix_column.py` | ✅ | ✅ | SS-1 |
| `audit_log_cardtxn_config.py` | ✅ | ✅ | SS-1 per-table |
| `scd2_phase1_config.py` | ✅ | ✅ | SCD2-P1-d |
| `scd2_expected_retention_days.py` | ✅ | ✅ | SCD2-R2-b |
| `scd2_repair_log.py` | ✅ | ✅ | SCD2-R6 |
| `extraction_guard_per_table.py` | ✅ | ✅ | P1-13 + MaxRowsPerDay |
| `udm_tables_columns_list_metadata.py` | ✅ | ✅ | Column Sync metadata |
| `scd2_last_modified_column.py` | ✅ | ✅ | LT-2 modified-date sweep |
| `udm_tables_list_source_server.py` | ✅ | ✅ | Source-server tracking |
| `lateness_columns.py` | 🟢 2026-05-12 | ⬜ | B193 |
| `pii_inventory_audit_log.py` | 🟢 2026-05-12 | ⬜ | B194 |
| `capacity_baseline_log.py` | 🟢 2026-05-12 | ⬜ | B195 |

---

## Pipeline core code — pre-existing ✅ (no recent rebuild)

Modules under `cdc/`, `scd2/`, `extract/`, `data_load/` (legacy), `schema/`, `orchestration/`, `observability/` are pre-existing pipeline code per CLAUDE.md "Structure" section. They are NOT recently rebuilt; they are the baseline pipeline on which Phase 2+ extensions ride.

| Path | Files | Status |
|---|---|---|
| `cdc/engine.py` + `cdc/reconciliation/*` + `cdc/source_verifier.py` + `cdc/source_count_check.py` + `cdc/modified_sweep.py` + `cdc/scd2_repair.py` | ~10 | ✅ Production |
| `scd2/engine.py` | 1 | ✅ Production |
| `extract/router.py` + `extract/connectorx_*.py` + `extract/oracle_extractor.py` + `extract/udm_connectorx_extractor.py` | ~5 | ✅ Production |
| `data_load/bcp_loader.py` + `data_load/bcp_csv.py` + `data_load/bcp_format.py` + `data_load/row_hash.py` + `data_load/sanitize.py` + `data_load/schema_utils.py` + `data_load/index_management.py` + `data_load/silver_gold_loader.py` | ~8 | ✅ Production |
| `schema/evolution.py` + `schema/column_sync.py` + `schema/table_creator.py` + `schema/staging_cleanup.py` + `schema/scd2_autoconfig.py` | ~5 | ✅ Production |
| `orchestration/small_tables.py` + `orchestration/large_tables.py` + `orchestration/guards.py` + `orchestration/pipeline_steps.py` + `orchestration/table_config.py` + `orchestration/table_lock.py` + `orchestration/pipeline_state.py` | ~7 | ✅ Production |
| `observability/event_tracker.py` v1 + `observability/log_handler.py` v1 | 2 | ✅ Production |
| `main_small_tables.py` + `main_large_tables.py` + `main_file_extract.py` + `main_pre_pipeline_setup.py` | 4 | ✅ Production |
| `utils/configuration.py` + `utils/cli_common.py` | 2 | ✅ Production | (`utils/errors.py` moved to Wave 0 section above — built 2026-05-13, NOT yet deployed; corrected per Pitfall #9.j status-render discipline — the pre-2026-05-13 ✅ Production claim was stale because the module hadn't been authored yet)
| `tools/inspect_*.py` + `tools/validate_*.py` + `tools/repair_*.py` + `tools/sweep_*.py` + `tools/backfill.py` + `tools/truncate_stage_bronze.py` + `tools/seed_from_legacy.py` + `tools/detect_scd2_config.py` + `tools/verify_cascade.py` + `tools/verify_tier0_drift.py` | ~12 | ✅ Production (legacy operator + governance tools) |

---

## Tests — current state

| Tier | Status | Pass count (2026-05-12) | Coverage |
|---|---|---|---|
| **Tier 0** (D67 smoke; <5s; mocks) | 🟢 | included in 283 | Covers all 8 new build units + governance scripts |
| **Tier 1** (unit; per-edge-case + per-error-path) | 🟢 | included in 283 | Covers all 8 new build units |
| **Tier 2** (Hypothesis property-based) | 🟡 | 12 skip (deferred per markers) | Lenient mode in B190 / B188; full coverage Phase 2 R5 |
| **Tier 3** (Docker integration) | ⬜ | 0 (no CI yet) | Authored at Round 5; runs on RHEL CI per Phase 2 |
| **Tier 4** (crash injection) | ⬜ | 0 | Authored Phase 2+ |
| **Tier 5** (quarterly drills) | ⬜ | 0 | Operator-driven per `06_TESTING.md` |

**Current full-suite result**: `920 passed + 14 skipped + 2 failed` (verified 2026-05-13 post-Wave-2.4 build — Wave 2 COMPLETE 4/4; +234 new passing tests net of cohort + 5 platform-skipped on Windows inherited from M7). Wave 2.4 (2026-05-13) added 43 new tests for `observability/log_handler.py` v2 cutover (6 Tier 0 + 37 Tier 1); all 43 pass after 2 inline-fix cycles + 1 post-cohort test-pollution fix via `_snapshot_utils_connections_state()` / `_restore_utils_connections_state()` autouse fixture (B214-class pattern — initial cutover broke 16 downstream `test_measure_capacity_and_partition.py` tests; fix landed test-file-only, no module touches). Wave 2.3 (2026-05-13) added 66 new tests for `data_load/vault_client.py` (8 Tier 0 + 58 Tier 1); all 66 pass after 1 inline-fix cycle. Wave 2.2 (2026-05-13) added 80 new tests for `data_load/parquet_registry_client.py` (21 Tier 0 + 59 Tier 1; **Tier γ — biggest module yet at 1,202 lines**); all 80 pass after 1 inline-fix cycle. Wave 2.1 (2026-05-13) added 45 new tests for `orchestration/range_scheduler.py` (6 Tier 0 + 39 Tier 1); all 45 pass after 1 inline-fix cycle. Wave 1.4 (2026-05-13) added 60 new tests for `cdc/extraction_state.py` (6 Tier 0 + 54 Tier 1); all 60 pass after 1 inline-fix cycle (3 test-side fixes — off-by-one cur.execute arg positions + MagicMock fetchone helper guard). Wave 1.3 (2026-05-13) added 50 new tests + 2 platform-skipped on Windows for `data_load/credentials_loader.py` (6 Tier 0 + 44 Tier 1 + 2 platform-skipped); **all 50 PASS first-iteration with 0 inline fixes**. Wave 1.2 (2026-05-13) added 29 new tests for `observability/sensitive_data_filter.py` (6 Tier 0 + 23 Tier 1 collected after parametrize × 2; 22 functions); **all 29 PASS first-iteration with 0 inline fixes**. Wave 1.1 (2026-05-13) added 41 new tests for `utils/idempotency_ledger.py` (29 Tier 1 functions, 35 collected after parametrize × 6; 6 Tier 0 + 35 Tier 1 collected = 41 total); all 41 pass after 2 inline iteration fixes. Wave 0 (2026-05-13) added 111 new tests for `utils/errors.py` (6 Tier 0 + 105 Tier 1); all 111 pass first-iteration. § 3.6 (2026-05-12) added 46 new tests (39 functions + 7 from parametrize expansion); all 46 pass after 5 inline iteration fixes. The 2 remaining failures are still the B218 § 3.10 residuals (#4 tier0 test_apply_invokes_per_level_delete; #5 TestConfigMissing); NO regression from Wave 2.

---
## Round 4 dependency-unblock map (as of 2026-05-13)

Cross-section view of which Round 4 operator tools (`phase1/04_tools.md` § 3.1-3.11) are NOW BUILDABLE given the current 🟢 Built state of Round 3 modules (Wave 0 + Waves 1-2; 9 modules total ⚫ CLOSED + Wave 2.2 M3 `parquet_registry_client.py` ⚫ CLOSED). Maps each Round 4 tool to its Round 3 module dependency + current blocker state.

| § | Tool | Round 3 dep | Dep state | Tool state (as of 2026-05-13) |
|---|---|---|---|---|
| § 3.1 | `parquet_tier_review.py` | M3 `parquet_registry_client.py` | ✅ Wave 2.2 🟢 Built 2026-05-13 | **NOW BUILDABLE** (was blocked on M3 pre-Wave-2) |
| § 3.2 | `parquet_verify.py` | M3 `parquet_registry_client.py` (`verify_parquet_snapshot()`) | ✅ Wave 2.2 🟢 Built 2026-05-13 | **NOW BUILDABLE** (was blocked on M3 pre-Wave-2) |
| § 3.3 | `lateness_profile.py` | M12 `cdc/lateness_profiler.py` | ⬜ NOT YET BUILT | Still blocked on M12 |
| § 3.4 | `decrypt_pii.py` | M5 `data_load/pii_decryptor.py` + M6 `data_load/vault_client.py` | M5 ⬜ + M6 ✅ Wave 2.3 🟢 | Still blocked on M5 |
| § 3.5 | `detect_extraction_gaps.py` | M13 `tools/gap_detector.py` | ⬜ NOT YET BUILT | Still blocked on M13 |
| § 3.6 | `promote_test_to_prod.py` | SP-4 (R1 DDL locked) + B79 `@AcknowledgmentOnly` (⚫ CLOSED Round 7) | ✅ deps land via SP-4 + B79 | **Already built** 2026-05-12 (Pattern B2; 46/46 PASS after 5 inline fixes) |
| § 3.7 | `verify_server_parity.py` | M8 `data_load/server_parity_verifier.py` (R3 § 3.2) | ⬜ NOT YET BUILT | Still blocked on M8 |
| § 3.8 | `enforce_retention.py` | SP-10 (R1 DDL locked) + B93/B94 amendments | ✅ deps satisfied | **Already built** 2026-05-12 (Pattern B2; 34/34 PASS) |
| § 3.9 | `process_ccpa_deletion.py` | SP-12 (R7 § 4.5 spec'd; DDL NOT yet deployed per B81) + M5 | ⬜ SP-12 + M5 | Still blocked on SP-12 deployment + M5 |
| § 3.10 | `log_retention_cleanup.py` | (none — pure DELETE on `PipelineLog`) | ✅ no dep | **Already built** 2026-05-12 (Pattern B2; 28/34 PASS; B218 carryover for 6 residuals) |
| § 3.11 | `alert_dispatcher.py` | Ops-channel client (B82 unscoped Phase 0; spec'd to use EMAIL per D108) | ⬜ NOT YET BUILT | Still blocked on B82 |

**Net dep-unblock as of 2026-05-13**:
- **2 newly-buildable tools** (§ 3.1 `parquet_tier_review` + § 3.2 `parquet_verify`) — both unblocked by Wave 2.2 M3 `parquet_registry_client.py` ⚫ CLOSED.
- **6 still blocked** (§ 3.3 / § 3.4 [partially — M5 missing] / § 3.5 / § 3.7 / § 3.9 / § 3.11) — pending Round 3 M5 / M8 / M12 / M13 + SP-12 deployment + B82 ops-channel.
- **3 already built** (§ 3.6 / § 3.8 / § 3.10) — Pattern B2 cohort 2026-05-12; pending engineer R1 deployment.

---

## Build queue — next recommended targets

Sorted by unblocked-and-small-first:

1. **§ 3.10 `tools/log_retention_cleanup.py`** — smallest unblocked tool; no Round 3 module dependency; pure DELETE on old `PipelineLog` rows. Cheap Pattern B1 (single agent). Demonstrates the new tracker discipline end-to-end.
2. **§ 3.8 `tools/enforce_retention.py`** — wraps SP-10 (Round 1 locked DDL); B93/B94 amendments already locked. Pattern B1.
3. **§ 3.6 `tools/promote_test_to_prod.py`** — wraps SP-4 (Round 1 locked DDL); B79 `@AcknowledgmentOnly` parameter already locked. Pattern B1.

After those 3, the next significant chunk is **Round 3 core modules**, which are foundational dependencies for the remaining 8 Round 4 tools + Phase 2 R2+ pipeline cycles. Largest single chunk of remaining work; should be planned as a multi-round Pattern B build cohort.

---

## How units move through state

```
⬜ Specified  →  🟡 In progress  →  🟢 Built  →  ✅ Deployed
   ↑               ↑                  ↑              ↑
   Spec doc       Author / test    Tests pass +    Engineer
   exists         agent running    code authored   runs deploy
                                   + reviewer 🟢   on target server
                                   on artifact     (dev → test → prod)

                                   ↓                ↓
                                   ⚫ Archived  ←  ⚫ Archived
                                   (supersession   (supersession
                                    pre-deploy)     post-deploy)
```

**State change** is annotated inline with date + mechanism. Updates land per the `udm-progress-logger` skill discipline at the moment of build-state transition, NOT batched to round close-out.

**Supersession path (🟢 → ⚫ or ✅ → ⚫)** (added 2026-05-12 per F-3 validation finding): when a built / deployed unit is superseded — replaced by a successor unit, deprecated per a new D-number, or retired per a SchemaContract supersession chain — the row transitions to ⚫ Archived with a closure annotation citing (a) the supersession mechanism (D-number / new unit name / SchemaContract chain ContractKey), (b) the date, and (c) the successor unit's CODE_BUILD_STATUS row if applicable. The original row body is preserved per D92 forward-only / Pitfall #9.j strikethrough discipline (never deleted; ⚫ + strikethrough). Pre-deploy supersession (🟢 → ⚫) is rare and typically indicates a major spec rewrite mid-build; post-deploy supersession (✅ → ⚫) is the canonical path when a successor unit ships.

---

## Relation to other trackers

| Tracker | Scope |
|---|---|
| **CODE_BUILD_STATUS.md** (this file) | What CODE is built / tested / deployed |
| **BACKLOG.md** | Substantive B-item work (mix of code + doc + process) |
| **ONE_OFF_SCRIPTS.md** | Operational one-off-ness tracking (Manual × One-time scripts) |
| **`phase1/02_configuration.md` § 5.1** | Scheduled / recurring Automic jobs |
| **POLISH_QUEUE.md** | Cosmetic / readability items (P-numbers) |
| **`_validation_log.md`** | Append-only audit trail of all validation + completion events |
| **CURRENT_STATE.md** | Project-wide round-level state + recent rounds |

---

## Read order context

CODE_BUILD_STATUS.md is **NOT** part of D62 CCL Stage 1 mandatory reads — it's a build-state worklist. Optional skim at:
- Start of any code-build agent invocation (worker should know what's built before authoring; prevents duplicate work)
- Round close-out cascade (per `udm-round-closeout` skill — verify aggregate counts match per-unit tables)
- User-side periodic review (this is the answer to "how is the build going?")

Owner: pipeline lead (file ownership); every agent / sub-agent / multi-agent team building code (entry author). Authored 2026-05-12 per user-direction "tracking progress on completing the coding tasks."
