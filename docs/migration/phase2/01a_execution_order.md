# Phase 2 R1 — Execution Order (R1a / R1b / R1c sequencing)

**Status**: Operational companion to `phase2/01_pilot_prerequisites.md`. NOT a new spec doc; sequences existing § 4 sub-steps into 3 micro-rounds. Authored 2026-05-12 per user-direction "scope chunking" reframe.

**Tier**: light-touch (no Pattern E; 1-cycle review + pipeline-lead sign-off when authored).

---

## Purpose

R1 spec doc covers 8 sub-steps that aggregate to 3-5 weeks. Splitting into 3 micro-rounds gives:
- Faster feedback (R1a in ~5 days → real implementation milestone)
- Smaller blast radius (each micro-round is independently rollback-able per R1 § 7)
- Clear gate transitions for pipeline-lead sign-off per micro-round
- Parallel-track for R02 spike independent of R1a/R1b critical path

`phase2/01_pilot_prerequisites.md` remains canonical procedural authority. This doc only sequences.

---

## R1a — Environment prep (3-5 days)

**Sub-steps** (per R1 spec doc):
- § 4.1 RB-14 .env migration on dev → test → prod (🔴 gated on **B197** SELinux fix — sysadmin coordination required)
- § 4.2 Tool 12 (`verify_credentials_load.py`) implementation + verification on all 3 servers
- § 4.7 Dev end-to-end smoke (synthetic data only; no Tools 14-16 needed at this stage)

**Acceptance gate (R1a → R1b)**:
- 3 `CLI_VERIFY_CREDENTIALS_LOAD` SUCCESS rows in PipelineEventLog (1 per server)
- 5 STARTUP_* events clean on dev smoke per D85
- 3 RB-14 audit rows in `ManualCorrectionLog` (1 per server)
- Pipeline-lead sign-off

**Why this micro-round**: minimal credential + auth foundation. Doesn't depend on schema changes or Tool 14-16 work. Failure here means subsequent micro-rounds can't proceed; succeeds means all 3 servers can read credentials cleanly.

---

## R1b — Schema + parity (5-7 days)

**Sub-steps**:
- § 4.4 B193 + B194 + B195 migration scripts authored + applied dev → test → prod
  - **B200 carryover applies here**: SchemaContract abandonment guard refinement happens during § 4.4 implementation with empirical schema access
- § 4.3 Tool 13 (`capture_parity_baseline.py`) implementation + parity baseline capture
- `verify_server_parity.py` (Tool 14-equivalent per R4 § 3.7) execution
- Targeted INFORMATION_SCHEMA cross-server query passes per § 4.3 + § 6 Gate 2 sub-check

**Acceptance gate (R1b → R1c)**:
- 9 first-application MIGRATION_* events filtered per § 4.4 contract (`event_kind='apply' AND ddl_applied=true`)
- 9 active SchemaContract rows (3 per server, identical natural-key row sets)
- INFORMATION_SCHEMA cross-server row-sets identical across dev/test/prod
- 3 `CLI_VERIFY_SERVER_PARITY` SUCCESS rows
- Pipeline-lead sign-off

**Why this micro-round**: schema state stabilization. Without B193/B194/B195 columns + tables, Tools 14/15/16 (R1c) can't run. With them + parity baseline captured, R1c can proceed in parallel paths.

---

## R1c — Tools + RB-12 deploy + R02 spike (5-10 days)

**Sub-steps**:
- § 4.5 Tools 14/15/16 implementations (B188 measure_lateness + B189 import_pii_inventory + B190 measure_capacity_and_partition)
- § 4.6 RB-12 Phase 1 artifact deploy ladder per D86 cadence (dev nightly → test daily +4h soak → prod weekly Monday window)
- § 4.8 R02 Round 0.5 spike (Scenarios A + B + C per `phase1/03_round_0_5_spike_plan.md`)

**Acceptance gate (R1 → R2 — full Phase 2 R1 acceptance per phase2/01 § 6)**:
- All 12 items in R1 spec doc § 6 acceptance gate satisfied
- R02 spike Scenarios A+B+C PASS; lessons-learned doc landed at `_spike_round_0_5/findings_<date>.md`
- 3 `DEPLOYMENT_*` event rows (DEV / TEST / PROD)
- R1 close-out cascade per D60 + Pattern F per D89-D91 + Section 10 self-improvement per D95-D99

**Pipeline-lead sign-off**: R1 complete → R2 (Dry-Run on Test) begins.

---

## Parallel-track recommendation

**R02 Round 0.5 spike (§ 4.8)** is independent of R1a/R1b critical path. As soon as engineer assignment lands, kick off R02 in parallel with R1a:

- R02 has ~1 engineer-week scope (Scenarios A + B + C per `phase1/03_round_0_5_spike_plan.md`)
- Can complete during R1a/R1b without blocking
- R02 closure (Scenarios A+B+C PASS + RISKS.md R02 🔴 → ⚪) is needed BEFORE R1 → R2 transition but can land any time during R1a-R1c

Recommend: engineer who staffed R02 spike starts immediately; R1a/R1b engineer(s) run sequentially; converge at R1c.

---

## What this doc does NOT do

- Does NOT replace `phase2/01_pilot_prerequisites.md` — parent remains canonical for procedural detail, edge cases, rollback procedures, post-step verification
- Does NOT introduce new D-numbers, B-numbers, R-numbers, or P-numbers
- Does NOT trigger Pattern E validation cycle (operational sequencing, not architectural decision)
- Does NOT re-decompose acceptance gates (R1 → R2 gate per phase2/01 § 6 unchanged)
- Does NOT add new tracking discipline; each micro-round close just gets ONE `_validation_log.md` line at the time of close (light close-out cascade per D60)

---

## Validation discipline (chunking-discipline-aware)

Per user-direction 2026-05-12 scope chunking: **lighter validation for operational rounds going forward**. Pattern E's 6-cycle machinery is for architectural spec docs (Round 1 schema; Round 4 tools; Round 7 governance). For migration scripts + Tool implementations + runbook execution + sequencing docs, a 1-cycle review with cross-reference + idempotency specialists is sufficient.

**This doc itself**: 1-cycle informal review at authoring; pipeline-lead sign-off at micro-round transitions. Forward-only per D92 — if sub-step content drifts during implementation, the parent R1 spec doc receives the update; this sequencing doc tracks the parent.

---

## Carryover gates summary

R1a is blocked on: **B197** (RB-14 SELinux fix; sysadmin coordination); engineer assignment; pipeline-lead R1 execution authorization.

R1b inherits R1a gates + adds: engineer empirical SchemaContract DDL access for **B200** resolution.

R1c inherits R1a/R1b gates + adds: R02 spike execution (parallel-track if started during R1a).

Full R1 → R2 transition adds: pipeline-lead R1 completion sign-off + R02 closure + 12-item § 6 acceptance gate.

---

Owner: pipeline lead (delegated to R1 implementation engineer for sub-step execution).
