# UDM Pipeline — Phase Plan

Each phase is independently shippable with an explicit validation gate before the next starts. Each phase follows the deep-dive cycle (plan → validate → QA → edge cases → edge case validation → sign-off) before advancing.

**Note**: This is an initial build, not a migration. There is no legacy Stage layer to cut over from. Phase 6 (formerly "cleanup") is removed; "Data Health Checks" is now Phase 6.

## Deep dive cycle (applied per phase)

```
1. PLAN — complete artifact list, sequencing, acceptance criteria
2. VALIDATE THE PLAN — cross-reference architecture, edge cases, runbooks
3. QUALITY ASSURANCE — peer review of DDL, modules, tests
4. EDGE CASE ENUMERATION — walk the M/S/I/N/P/G/D/F/V/DP/T/SI/SE register
5. VALIDATE EDGE CASES — write tests / verify config / write runbook section
6. PHASE COMPLETE — validation gate green, stakeholder sign-off
```

A phase does not advance until step 6 is complete for it.

## Phase Status Legend

- ⬜ Not started
- 🟡 In progress
- 🟢 Complete
- 🔴 Blocked

---

## Phase 0 — Decisions, Measurements, Fixtures

**Status: 🟡 In progress** (**12/20 strict-closed + 6/20 partial-closed + 0/20 open + 2/20 removed = 18/20 addressed (90%) as of 2026-05-12 multi-agent cascade + D109/D110/D111/D112 locks + D106 supersession** — **applying canonical-anchor + enumerate-before-count discipline** per Pitfall #9 sub-class 9.k, items individually enumerated before tally. **🟢 Strict-closed (12, enumerated)**: 0.5 + 0.6 + 0.7 + 0.9 + 0.10 + 0.11 + 0.12 + 0.14 + 0.15 + 0.18 + 0.19 + 0.20 = 12 (0.19 RE-CLOSED 🟢 per D110 explicit DC-loss-no-DR posture acceptance — D107 fix-app-2 downgrade reversed; B192 ⚫ CLOSED). **🟡 Partial-closed (6, enumerated)**: 0.1 (architecture sign-off — pipeline-lead sign-off ✅ received 2026-05-12; team meeting on D103 still pending) + 0.2 (Tool 14 lateness measurement spec via Round 4.5b; impl B188) + 0.3 (PII inventory spec ✅ per D63; data-side B185 + import script B189) + 0.4 (vault DDL algorithm pinned per D102; DDL review pending) + 0.8 (Phases 1-2 ✅; Phases 3-6 just-in-time per D112) + 0.17 (capacity baseline Tool 16 spec via Round 4.5b; impl B190) = 6. **⬜ Open (0)**. **⚫ Removed (2)**: 0.13 + 0.16. **TOTAL 12 + 6 + 0 + 2 = 20 ✓**. **R01 STAYS DE-ESCALATED** (12/20 strict ≥ 10/20 threshold restored post-D110). See `phase0/_sweep_2026-05-12.md` + 2026-05-12 multi-agent cascade narrative.)

**Goal**: lock the foundation. No code changes.

### Deliverables

| # | Item | Owner | Status |
|---|---|---|---|
| 0.1 | Architecture sign-off from management & engineering leads — **Unblocked 2026-05-11 per D102/D103/D104/D105 lock; pending team meeting on D103 (Claude Code security model + `SECURITY_MODEL.md`)** | TBD | 🟡 |
| 0.2 | Lateness measurement query run on top 5 large tables; per-table `L_99` baseline established | Pipeline team | ⬜ |
| 0.3 | PII column inventory per source (DNA, CCM, EPICOR) — **🟡 Spec-side closed 2026-05-12 per Phase 0 sweep**: `UdmTablesList.PiiColumnList` + `DataClassification` columns added at Round 2 per D63 (`phase1/02_configuration.md` § 1.1 + § 1.2). **Data-side ⬜**: populating per-source actual PII column inventory awaits compliance review per source — tracked as **B185** | Pipeline team + compliance | 🟡 |
| 0.4 | Tokenization vault DDL reviewed & approved — **Algorithm pinned 2026-05-11 per D102 (AES-256-GCM Python, nonce 12B + ciphertext + auth-tag 16B in single VARBINARY column); DDL itself still pending DBA + compliance review** | DBA + compliance | 🟡 |
| 0.5 | Network drive path standard finalized (`\\archive\source=...\table=...\year=...\month=...\day=...\batch=...`) — **🟢 Closed 2026-05-12 per Phase 0 sweep + D107 final framing**: standard locked in `00_OVERVIEW.md` L31 + `01_ARCHITECTURE.md` L42 + L99 + `03_DECISIONS.md` D2/D4 area L66 (canonical UNC pattern: `\\archive\source={Source}\table={Table}\year={YYYY}\month={MM}\day={DD}\batch={BatchId}_part-{N}.parquet`). **Per D107 final framing 2026-05-12**: TWO local Windows network drive paths — (1) **H drive** = primary local network drive (Windows drive-letter mount of canonical UNC on operator workstations + RHEL pipeline servers via SMB/CIFS); pipeline writes Parquet here first; D45.2 invariants (100-250 MB target file size; ZSTD compression; sort order; statistics enabled) apply. (2) **VendorFile location** = secondary local network drive (also in-company DC; receives async-replicated copies for in-DC redundancy + operational secondary use). BOTH local per user-confirmation 2026-05-12; DC-loss DR delegated to D110 explicit acceptance (no off-DC mirror required) | Pipeline team + sysadmin | 🟢 |
| 0.6 | Snowflake trial week-1 cost data captured (storage rate, COPY INTO compute, Iceberg query rate) — **🟢 Closed 2026-05-12 per user sign-off**: Snowflake (vendor) absorbs trial-week costs; project does NOT need to capture per-component cost data for the trial week. Cost monitoring resumes at Phase 5 once trial concludes + production Snowflake billing begins; alert threshold ($8K/month per R04 mitigation) stays canonical | Pipeline team | 🟢 |
| 0.7 | Pilot table selected (small, ≤1M rows, low consumer impact) — **🟢 Closed 2026-05-11 per D104: `DNA.osibank.ACCT` (1.2M rows; user-confirmed sizing as "fine enough" — large enough to exercise CDC + SCD2 + reconciliation paths, small enough to iterate fast)** | Pipeline team | 🟢 |
| 0.8 | Acceptance criteria for each subsequent phase signed off — **🟡 Partial 2026-05-12 per Phase 0 sweep**: Phase 1 acceptance criteria fully spec'd in `phase1/00_phase_overview.md` § "Phase 1 acceptance criteria (gate to Phase 2)" (all Rounds 1-8 + R1.5 locked); Phase 2 acceptance criteria fully spec'd in `phase2/00_phase_overview.md` § "Phase 2 acceptance criteria (gate to Phase 3)". **Phase 3-6 deep-dive plans ⬜**: high-level scope exists in this doc but no per-phase deep-dive — tracked as **B186** | All | 🟡 |
| 0.9 | Server failover protocol documented in `05_RUNBOOKS.md` — **🟢 Closed 2026-05-12 per Phase 0 sweep + user sign-off**: **RB-2** Production Server Failover at `05_RUNBOOKS.md` L129 (manual failover with operator-driven decision); **RB-9** Automatic AM/PM Failover (Automic-driven) at L575 (cooperative cancellation per D33 + automatic gate-table coordination per D29). **Test↔Prod communication mechanism** preventing overlap: `General.ops.PipelineExecutionGate` table per Round 1 § 2 + SP-3 (prod acquire) / SP-4 (test acquire-with-acknowledgment-window) — both servers gate AM/PM cycle acquisition through the SAME gate table; concurrent execution prevented by the `CycleType, CycleDate` unique constraint; RB-9 codifies the test-side hot-standby flow. Both runbooks follow D55 5-gate discipline with pre-flight / procedure / validation / rollback | Pipeline team + sysadmin | 🟢 |
| 0.10 | 2x/day pipeline schedule windows agreed (job inventory frozen at Round 2; **amended to 11 canonical Automic jobs at Round 7 per `phase1/07_schema_evolution_governance.md` § 6.2 — added JOB_PARQUET_VERIFY / JOB_LOG_CLEANUP / JOB_PARITY_EXCEPTION_NOTIFY**; see `phase1/02_configuration.md` § 5.1 for the original 8 + Round 7 § 6.2 for the 3 additions; this Phase 0 step is operational scheduling against the frozen-11 inventory) — **🟢 Closed 2026-05-12 per user sign-off + D109 lock (supersedes D106 same-session)**: canonical operational schedule = **dual-Automic prod-then-test 4-hour gap pattern**: AM Prod 02:00 + Test 06:00 weekdays; PM Prod 17:00 + Test 21:00 daily per D109 (D106 single-event 02:00 AM + 17:00 PM was expanded to dual-Automic-instance topology at multi-agent cascade 2026-05-12; supersedes Round 2 § 5.1 example values 06:00 / 18:00; structure + dependencies + CHECK constraints unchanged per D66 + Round 7 § 6.2). Automic UI configuration deploys at Phase 2 R1 per D86 cadence. Both servers (prod + test hot-standby) gate via `PipelineExecutionGate` per SP-3/SP-4 (see 0.9 closure) | Pipeline team + ops | 🟢 |
| 0.11 | Cross-server parity baseline established (D27) — RHEL version, Python pinned, library set, systemd unit identical across dev/test/prod — **🟢 Closed 2026-05-11: user confirmed RHEL Linux Servers set up and good to go (test + prod); SELinux enforcing on servers; B183 baseline-capture-script spec ⚫ CLOSED via Round 4.5 supplement `phase1/04a_phase_0_prep_tools.md` § 4; Tool 13 implementation lands at Phase 2 R1** | Pipeline team + sysadmin | 🟢 |
| 0.12 | GPG-based credential strategy agreed (D27) — `/etc/pipeline/credentials.json.gpg` deployment plan; passphrase storage (TPM2 or keyutils) — **🟢 Closed 2026-05-11 per D103 Claude Code security model**: 13-layer defense-in-depth with `/debi` working-directory boundary (Claude installed on dev only — test/prod RHEL servers image-baked NO Claude); RHEL-shipped tools only (SELinux + auditd + systemd-creds + kernel keyring + POSIX ACLs + TPM2) + MS built-ins (DPAPI + NTFS ACLs + Credential Manager) + Claude Code's own `.claude/settings.local.json` deny/allow lists; commercial endpoint security + AppArmor + third-party secrets managers ALL banned per user policy; `.env` migration `/debi/.env` → `/etc/pipeline/.env`; canonical reference `docs/migration/SECURITY_MODEL.md` (~20 KB). R32 opened (Claude credential-access risk Low × Medium = 2 ⚪ post-mitigation). Pitfall #12 logged (naming-standard locked late). | Pipeline team + security | 🟢 |
| 0.13 | (Removed — was watchdog host; D29 revised to use Automic) | — | ⚫ |
| 0.14 | Source-DB on-call escalation contacts captured in runbook (D28) — **🟢 Closed 2026-05-12 per user sign-off**: no further action required; D28 already designates the source-DB on-call team as out-of-pipeline-team-scope, and existing escalation channels (operator team + DB on-call rotation) are pre-existing infrastructure. Contact list maintained operationally OUTSIDE the pipeline doc set per project D28 governance | Pipeline team + DB on-call team | 🟢 |
| 0.15 | PiiTokenProvenance schema reviewed (D26) — column list, indexes, FK to PiiVault — **🟢 Closed 2026-05-12 per user sign-off**: schema reviewed + accepted as-is at Round 1 v3 lock per D49; future amendments expected when company merger formalizes (per Phase 0 deliv 0.4 D102 merger-context). Per-D92 forward-only, post-merger amendments will land via SchemaContract supersession + additive ALTER paths, NOT in-place edits to the current schema | DBA + compliance | 🟢 |
| 0.16 | (Removed — was source schema contracts; D41 superseded by D40 internal governance) | — | ⚫ |
| 0.17 | Capacity baseline established (D42) — current row counts, growth rates, 12-month projections, 7-year storage forecast for top 10 tables | Pipeline team | ⬜ |
| 0.18 | Alation integration scope agreed with data governance team (D43) — what metadata the pipeline publishes; coordination cadence — **🟢 Closed 2026-05-12 per user sign-off: deferred to future scope**. D43 remains 🟡 Proposed (not pursued at this Phase 0 close); Alation integration is NOT a Phase 1-6 deliverable. If future requirements demand catalog integration, new D-number + new Phase 0/1 deliverable to be added at that time | Pipeline team + data governance team | 🟢 |
| 0.19 | Offsite Parquet replication target identified (D44) — for DC-loss DR scenario — **🟢 RE-CLOSED 2026-05-12 per D110 DC-loss-no-DR posture acceptance**: per user direction at multi-agent cascade ("The DC-loss DR posture decision (B192) has also been approved. We're fine with this scope."), the project explicitly accepts DC-loss-no-DR. D110 documents acceptance rationale: company-level backup is the DC-loss recovery mechanism; source-DB re-extraction is the in-pipeline recovery mechanism per D34 greenfield + D14 IsReExtraction + D11 lookback days; vendor SLAs on source-DB availability per D28; commercial off-DC mirror procurement deferred to Phase 5+ if business case emerges. **B192 ⚫ CLOSED alongside D110** (resolution path (b) — explicit acceptance via new D-number — chosen over path (a)). Regulatory implications for D30 7-year retention surfaced + accepted in D110 rationale. RB-7 Q2/Q4 drill scope reduces to tabletop + re-extraction validation; RB-8 DC-loss case delegated to D110 path; spec updates tracked at Phase 2 R1 | Pipeline team + sysadmin | 🟢 |
| 0.20 | Ops-channel client integration — **🟢 Closed 2026-05-12 per user sign-off + D108 lock**: ops-channel architecture is EMAIL-centric via three pre-existing engines: (1) **SQL Server Database Mail** (`msdb.dbo.sysmail_*` + `sp_send_dbmail` — already used by team) for Bronze-layer-originated alerts; (2) **Automic notifications** for job lifecycle alerts; (3) **Power BI metric-based alerts** for trend / threshold dashboards. **Microsoft Teams** as secondary surface (via mailbox monitoring OR Power BI Teams integration OR Automic-to-Teams webhook). NO Slack / NO PagerDuty / NO SMS — project stack is email-centric. Pre-existing infrastructure ($0 incremental cost). **B156 ⚫ CLOSED via D108** (R7C1-5 advisory framing concern resolved — project doesn't use SRE-canonical Slack/PagerDuty pattern, so the inversion concern doesn't apply). Round 4 § 3.11 `alert_dispatcher` implementation at Phase 2 R1 uses `smtplib` or `sp_send_dbmail` per D108 trade-offs | Pipeline lead + system engineering | 🟢 |

### Validation Gate

Written go/no-go from stakeholder list, including compliance sign-off on tokenization approach.

---

## Phase 1 — Foundation Infrastructure

**Status: 🟢 Complete** — All 8 rounds Locked + Round 1.5 documentation supplements. R1 v3 schema; R2 Configuration with D63-D66; R3 Core Modules with D67-D71 via D73 architectural-review acceptance; R4 Tools with D74-D77 via D78; R5 Tests with D79-D82 via D83 convergence-confirmed acceptance; R6 Deployment with D84-D87 via D88; R7 Schema Evolution Governance with D92-D94 via D94 math-infeasibility; **R8 Sub-Agent Self-Improvement Discipline with D95-D99 via D99 convergence-confirmed acceptance 2026-05-11 (LAST Phase 1 round)**. **Round 1.5 Documentation Supplements (G1-G6; 5 supplement docs) with D100-D101 via D101 math-infeasibility acceptance 2026-05-11** — closes schema-story gaps for new engineers + dashboard authors; carryover B166-B175 + I24 + deferred B173 comprehensive ER canonical sweep. Pattern F discipline (D89/D90/D91) 🟢 Locked at Round 7 first-production close-out 2026-05-11. **Phase 2 (Pilot Cutover) is next.** Round 0.5 spike (D47) authorized awaiting engineer assignment — proceeds in parallel.

**Code-build sub-status** (as of 2026-05-14; tracked at per-artifact granularity in `CODE_BUILD_STATUS.md`; consolidating session record at `SESSION_2026-05-13_BUILD_LOG.md`):
- Round 3 (Core Modules): 17/17 🟢 BUILT
- Round 4 (Operator Tools): 9/11 🟢 BUILT; 2 🔴 blocked on external prereqs (B81 SP-12 schema evo + B82 ops-channel Phase 0 deliv)
- Round 6 (Deployment): partial — Tier 2 property tests 🟢 (53 properties across 8 files; 1 production bug surfaced + fixed via Hypothesis = B-262); Tier 3/4 + B-item closures + RHEL deploy pending
- Phase 1 implementation: ~75% complete

**Goal**: build infrastructure that doesn't change pipeline behavior. Code lands; no table is using it yet.

### Deliverables

#### Migrations
- `migrations/parquet_snapshot_registry.py` — `General.ops.ParquetSnapshotRegistry`
- `migrations/idempotency_ledger.py` — `General.ops.IdempotencyLedger`
- `migrations/delete_evaluation_audit.py` — `General.ops.DeleteEvaluationAudit`
- `migrations/extraction_range_policy.py` — `General.ops.ExtractionRangePolicy`
- `migrations/lateness_profile.py` — `General.ops.LatenessProfile`
- `migrations/pii_vault.py` — `General.ops.PiiVault` + `PiiVaultAccessLog`
- `migrations/pii_token_provenance.py` — `General.ops.PiiTokenProvenance` (D26 revised, append-only first-observation)
- `migrations/pii_tokenization_batch.py` — `General.ops.PiiTokenizationBatch` (D26 revised, batch-level audit)
- `migrations/pii_vault_retention.py` — adds Status, LegalHold, RetentionExpiresAt columns to PiiVault (D30)
- `migrations/ccpa_deletion_log.py` — `General.ops.CcpaDeletionLog` (D30, RB-10)
- `migrations/pipeline_execution_gate.py` — `General.ops.PipelineExecutionGate` (D29 revised, Automic coordination, includes cancellation columns per D33)
- `migrations/table_enablement_log.py` — `General.ops.TableEnablementLog` (Phase 4 tracking)
- `migrations/extraction_attempt_columns.py` — adds `IsReExtraction BIT`, `ExtractionAttempt INT` to `PipelineExtraction`
- `migrations/extraction_gap_log.py` — `General.ops.ExtractionGapLog`
- `migrations/cdc_mode_column.py` — adds `UdmTablesList.CDCMode NVARCHAR(20) DEFAULT 'change_detect'`
- `migrations/manual_correction_log.py` — `General.ops.ManualCorrectionLog`

#### New modules
- `data_load/parquet_writer.py` — Polars→Parquet (per spec); stage-check-exchange (inflight rename)
- `data_load/parquet_replay.py` — read Parquet back into a DataFrame for SCD2 replay
- `data_load/snowflake_uploader.py` — async upload to Snowflake stage (Phase 5 readiness)
- `data_load/pii_tokenizer.py` — vault GET-OR-CREATE call + provenance UPSERT; row-level idempotent tokenization (D26)
- `data_load/pii_decryptor.py` — counterpart for authorized callers; logs to PiiVaultAccessLog
- `data_load/credentials_loader.py` — GPG-encrypted credential file loader; supports TPM2 / keyutils passphrase sources (D27)
- `utils/idempotency_ledger.py` — context manager: `with ledger.step(...) as step:`; short-circuits on COMPLETED
- `cdc/extraction_state.py` — `is_date_trusted()`, `most_recent_success()`, `is_reextraction()`
- `cdc/range_scheduler.py` — picks `ExtractionRangePolicy` ranges per time budget
- `cdc/lateness_profiler.py` — runs measurement query, writes to `LatenessProfile`
- `cdc/gap_detector.py` — surfaces missing dates; auto-enqueues recoverable ones

#### New tools
- `tools/parquet_tier_review.py` — weekly cron, reclassifies `StorageTier`
- `tools/parquet_verify.py` — walks registry, checks file existence + checksum
- `tools/lateness_profile.py` — manual or scheduled lateness measurement
- `tools/decrypt_pii.py` — operator/auditor decryption tool with role check
- `tools/detect_extraction_gaps.py` — gap detector CLI
- `tools/promote_test_to_prod.py` — full server failover scripted helper (RB-2)
- `tools/verify_server_parity.py` — cross-server config drift detector (D27); runs at pipeline startup
- `tools/enforce_retention.py` — 7-year vault retention enforcement (D30, RB-11); monthly cron
- `tools/process_ccpa_deletion.py` — operator-driven CCPA right-to-deletion processor (RB-10)
- (Note: `tools/watchdog.py` removed — superseded by Automic gate-based failover D29 revised)

#### Cross-cutting
- Move `cdc/source_verifier.py` defenses into `scd2/engine.py` as the new home for verify-before-close (still active in change_detect mode for backwards compatibility)
- Move E-12 phantom-update detection from CDC to SCD2 metadata layer
- Property-based idempotency tests (Tier 2 in `06_TESTING.md`) for every new module

### Validation Gate

- 100% unit test pass on every new module
- Property-based tests (Tier 2) green
- Integration smoke test against fixture table
- Manual code review of tokenization code by a second engineer
- DBA review of all migration scripts

---

## Phase 2 — Pilot Table Cutover

**Status: 🟢 Locked** (deep-dive plan at `phase2/00_phase_overview.md` 🟢 Locked 2026-05-12 per pipeline-lead sign-off; Round 1 unblocked pending R02 Round 0.5 spike execution. Pilot table = `DNA.osibank.ACCT` per **D104**. Round structure: R1 Pilot Prerequisites → R2 Dry-Run on Test → R3 Production Cutover → R4 Post-Cutover Verification + Close-Out. Estimated 3-5 weeks once R1 begins. Schedule per **D109** (AM Prod 02:00 + Test 06:00 weekdays; PM Prod 17:00 + Test 21:00 daily; SQL-table coordination via PipelineExecutionGate per D29/D33/SP-3/SP-4).)

**Goal**: single small table runs the new flow end-to-end. Validate Bronze output identical to legacy pipeline.

### Cutover Protocol (per table)

1. **Pre-flight**: `validate_scd2.py` reports HEALTHY; no in-flight runs; ledger has no stale `IN_PROGRESS` rows
2. **Acquire `sp_getapplock`** with extended timeout
3. Inside transaction:
   - `UPDATE Stage SET _cdc_is_current = 0 WHERE _cdc_is_current = 1` — closes the change-detect chapter
   - `INSERT PipelineEventLog` row with `EventType='CDC_MODE_CUTOVER'`
   - `UPDATE UdmTablesList SET CDCMode = 'parquet_snapshot'` for this table
4. **Release lock**
5. **First post-cutover run** uses new flow: extract → tokenize → write Parquet → register → run SCD2 vs Bronze (no Stage read or write). Stage table no longer touched for this table.

### Validation Gate (per pilot table)

- Bronze identical to old pipeline output (same row count, same `UdmHash` on every active row)
- `ParquetSnapshotRegistry` reflects every batch
- `IdempotencyLedger` reflects every step
- Re-run with same `BatchId` is a no-op (zero Bronze writes)
- Re-run with new `BatchId` on unchanged source = no Bronze writes
- Pilot table runs daily for 2 weeks without operator intervention
- One deliberate downtime test mid-soak (stop pipeline 24-48 hours, restart, validate auto-recovery)

---

## Phase 3 — Large-Table Support

**Status: ⬜ Not started**

**Goal**: add windowed extraction + delete detection via `PipelineExtraction` trust gate.

### Deliverables

- `cdc/extraction_state.py::trust_gate_window()` — given a window, returns trusted/untrusted dates set
- SCD2 windowed delete detection rewires per architecture: candidate deletes only for trusted-date PKs
- `tools/backfill.py` updated to set `IsReExtraction = 1` automatically
- `cdc/range_scheduler.py` integrated for large tables (replaces fixed `LookbackDays` for opt-in)
- Lateness measurement scheduled monthly per large table (cron job)

### Pilot

One low-volume large table (NOT ACCT, CARDTXN, AuditLog yet — pick the lowest daily-row large table available).

### Validation Gate

- Per-day events tagged with `target_date` (OBS-2 invariant preserved)
- Suppressed deletes correctly logged in `DeleteEvaluationAudit` when a date has `Status='FAIL'`
- Backfill re-runs are idempotent (zero Bronze writes if data unchanged)
- `ParquetSnapshotRegistry` has one row per (table, batch_id, business_date)
- 2 week soak

---

## Phase 4 — Production Rollout (per-table enablement)

**Status: ⬜ Not started**

**Goal**: enable remaining tables for production. No legacy cutover protocol — this is initial deployment per table.

### Per-table enablement process

1. Configure table in `UdmTablesList` (PK columns, schedule, source object info, PII column flags) — see `phase1/02_configuration.md` § 1.1 (existing 29-column inventory) + § 1.2 (6 new columns locked by D63: `CDCMode`, `PiiColumnList`, `DataClassification`, `CohortAssignment`, `IsEnabled`, `LegalHoldOnly`). Per-cohort enablement uses `CohortAssignment` (§ 1.2.4).
2. Run measurement query for `L_99` (large tables)
3. First pipeline run (manual invocation) to validate end-to-end:
   - Extract succeeds
   - Tokenization completes (vault populated for new PII values)
   - Parquet written and registered
   - Bronze populated correctly
4. Schedule the table in Automic for AM/PM cycles
5. Soak 1 week per cohort of 5-10 tables before adding the next cohort
6. Power BI dashboard verification (table-level deep dive)

### Tracking

`General.ops.TableEnablementLog` (new) tracks: table, source, enabled_batch_id, enabled_at, first_successful_run, signoff_user.

### Validation Gate (per cohort)

- Every table's first run completes successfully
- Subsequent runs are idempotent (re-run = no-op on unchanged source)
- Bronze SCD2 versions match the manual reconciliation against source
- Power BI dashboards show table-level health green
- 1-week soak with no operator intervention

---

## Phase 5 — Snowflake Integration

**Status: ⬜ Not started**

**Goal**: based on actual trial cost data from Phase 0, integrate Snowflake for analytics.

### Deliverables

- Snowflake Iceberg table provisioning per source/table
- `data_load/snowflake_uploader.py` upgraded from "stage upload only" to "Iceberg manifest update"
- Snowflake Bronze mirror via Snowpipe or CTAS-from-Parquet
- Snowflake masking policies on PII token columns
- Reconciliation job: weekly Python-Bronze ↔ Snowflake-Bronze diff; alerts on drift
- Decision (with cost data): does Snowflake also run any SCD2? Per Agent 1 research: only periodic full-row reconciliation (P3-4) and backfill, never daily

### Validation Gate

- Snowflake Bronze mirror within 1 hour of SQL Server Bronze for active tables
- Audit query against Snowflake Iceberg returns identical results to network drive Polars query
- $/month tracking shows < $10K with cushion
- Token decrypt path documented for Snowflake-side audit (call back to SQL Server vault)

---

## Phase 6 — Data Health Checks

(formerly Phase 7; renumbered after old Phase 6 Cleanup was removed)

See section below.

---

## ~~Phase 6 — Cleanup~~ (REMOVED)

**Status: ⚫ Removed** — no legacy Stage layer to clean up. Pipeline is greenfield deployment, not migration.

The Phase 6 work that remains relevant (Tier 4 crash-injection tests, CLAUDE.md alignment) is folded into Phase 1 (Tier 1+2 tests) and Phase 4 (Tier 3+4 tests) as part of phase-level acceptance criteria.

---

## Time & Effort Estimate (rough)

| Phase | Calendar weeks | Key risk |
|---|---|---|
| 0 | 1-2 weeks | Stakeholder sign-off latency |
| 1 | 4-6 weeks | Tokenization vault correctness; idempotency ledger pattern |
| 2 | 2 weeks live + 2 weeks soak | First real cutover may surface unforeseen edge cases |
| 3 | 3-4 weeks | Delete detection via PipelineExtraction trust gate is genuinely new logic |
| 4 | 6-10 weeks | Per-table enablement velocity; consumer-team coordination for any net-new consumer queries |
| 5 | 4-6 weeks | Snowflake cost characterization may force re-scoping |
| 6 | 4-6 weeks | Data health checks; Power BI dashboards; alerting integration |

**Total**: ~5-9 months from Phase 0 sign-off to Phase 6 complete (~2 months saved by removing legacy cleanup).

---

## Phase 6 — Data Health Checks

**Status: ⬜ Not started** (planned post-rollout)

**Goal**: comprehensive health-check framework with Power BI dashboards, anomaly detection, alerting integration. Builds on existing reconciliation (P3-4), freshness alerting (B-9, E-15), and active-ratio monitoring (E-14).

### Deliverables

#### Migrations
- `migrations/health_check_log.py` — `General.ops.HealthCheckLog` capturing each check's result
- `migrations/health_check_thresholds.py` — `General.ops.HealthCheckThresholds` for per-check, per-table threshold config
- `migrations/anomaly_detection_baseline.py` — `General.ops.AnomalyBaseline` for distribution-shift baselines

#### New modules
- `health_checks/source_drift.py` — row count, schema, null rate, distribution shifts at source
- `health_checks/pipeline_metrics.py` — extraction throughput, SCD2 churn, vault hit/miss ratio, error rates
- `health_checks/bronze_health.py` — active-to-total, version velocity, freshness, RI consolidator
- `health_checks/cross_layer.py` — Bronze ↔ Parquet drift, Bronze ↔ Snowflake mirror drift
- `health_checks/anomaly_detector.py` — per-metric z-score / control-chart-style detection
- `health_checks/dispatcher.py` — runs all checks, writes to HealthCheckLog, fires alerts
- `health_checks/alerter.py` — escalation router; integrates with corporate alerting (email, Teams, etc.)

#### Tools
- `tools/run_health_checks.py` — manual or cron-driven invoker
- `tools/health_check_baseline.py` — captures distribution baselines for anomaly detection

#### Power BI dashboards
- **Pipeline overview**: per-cycle success rate, runtime trends, gap counts
- **Table-level deep dive**: per-table health metrics with drill-down
- **Anomaly board**: recent anomalies, severity, status, owner
- **Executive summary**: roll-up of pipeline health + audit posture
- **Vault health**: tokenization metrics, retention status, decrypt access patterns

#### Documentation
- `08_HEALTH_CHECKS.md` — full design (created when Phase 7 begins)

### Validation Gate

- All scheduled health checks running on cron without flakes for 4 weeks
- Power BI dashboards published and accessible to ops team
- Anomaly thresholds tuned based on 4-week baseline data
- Alert routing tested end-to-end (synthetic anomaly triggers correct escalation)
- Operator playbook documents response per anomaly type
