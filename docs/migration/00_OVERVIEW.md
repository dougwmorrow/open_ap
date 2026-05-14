# UDM Pipeline — Overview

## Purpose

This directory tracks the design and initial deployment of the UDM (Unified Data Management) pipeline. The pipeline extracts from Oracle (DNA) and SQL Server (CCM, EPICOR) sources, applies PII tokenization, writes Parquet snapshots to a network drive, promotes through an SCD2 dimension layer in SQL Server, and mirrors to Snowflake for analytics. The design is driven by audit-grade traceability requirements, cost discipline ($120K/year Snowflake budget), and the team's preference for an explicit per-run audit trail.

**This is an initial build, not a migration.** No SQL Server tables exist yet; we are deploying the system from scratch. The codebase exists (per CLAUDE.md), but production tables and operational state are greenfield.

## Status

- **Current phase**: Phase 1 — Foundation Infrastructure **🟢 COMPLETE** — Rounds 1-8 all Locked 2026-05-11. R8 Sub-Agent Self-Improvement Discipline (LAST Phase 1 round) Locked via D99 convergence-confirmed acceptance. **Phase 2 (Pilot Cutover) is next.** Phase 0 deliverables 0.X still 🟡 In progress; proceed in parallel.
- **Pattern F discipline (D89/D90/D91)**: 🟢 Locked at Round 7 first-production close-out 2026-05-11 (3-event evidence base extended to 4 at Round 8 close-out cascade).
- **Code-build progress (Phase 1 implementation)**: as of 2026-05-14, ~75% complete via 7-commit campaign on `phase-1-round-3-build-campaign` branch:
  - Round 3 (Core Modules): 17/17 BUILT (100%) — utils/errors.py prereq + 17 module bodies + 1063 Tier 0+1 tests
  - Round 4 (Operator Tools): 9/11 BUILT (82%) — 2 blocked on B81 (SP-12 schema evo) + B82 (ops-channel Phase 0 deliv)
  - Round 6 (Deployment): Tier 2 property tests landed (53 properties across 8 files); Tier 3/4 + B-item closures + actual RHEL deploy pending
  - 1 production bug surfaced + fixed (B-262 NFC-vs-Categorical hash ordering via Hypothesis Tier 2 catch)
  - Step 11 (canonical-spec verbatim citation) elevated to Gate 2 mandatory specialty in udm-design-reviewer v1.1.0 (first agent prompt versioned per D98)
  - Per-artifact tracking at `CODE_BUILD_STATUS.md`; consolidating session record at `SESSION_2026-05-13_BUILD_LOG.md`
- **First production deployment**: TBD (Phase 2 pilot)
- **Full production rollout**: TBD (after Phase 4)
- **Total phases**: 6 (Phase 6 cleanup removed — no legacy to clean up; current Phase 6 is Data Health Checks)

## Headline Decisions Locked In

1. **Drop the Stage layer.** Parquet snapshots on the network drive replace it as the operational change-detection substrate AND the audit-grade observation log.
2. **SCD2 stays in Python+Polars indefinitely.** Snowflake handles analytics, periodic full reconciliation, and ad-hoc backfills only. Daily SCD2 promotion remains on the existing Linux server.
3. **PII protection via in-house tokenization vault** (SQL Server-based, no external services, no new open-source software).
4. **Lookback driven by empirical L_99** measurement per table, replacing the fixed `LookbackDays = 30`.
5. **Idempotency mandatory at every layer** — hash-deduped extraction, idempotency ledger gating each pipeline step, conditional MERGE for SCD2, verify-before-close for deletes, INSERT-IF-NOT-EXISTS for the Parquet registry and tokenization vault.
6. **Pipeline runs 2x daily** for resilience; minimum acceptable cadence is 1x daily.
7. **3-server architecture** (dev/test/prod) supports failover during production outages.

## Storage Architecture (high level)

| Layer | Location | Purpose | Retention |
|---|---|---|---|
| Network Drive Parquet | `\\archive\source=...\table=...\year=YY\month=MM\day=DD\batch=N.parquet` | Audit-grade snapshot archive; SCD2 replay substrate | Indefinite (until Snowflake migration) |
| UDM_Bronze (SQL Server) | SCD2-versioned dimension tables | Regulatory state-truth queries; SCD2 versions | Indefinite |
| Snowflake Mirror | Iceberg-managed Bronze + external Parquet stage | Analytics, reconciliation, audit queries | TBD (cost-driven) |
| Operational metadata | `General.ops.*` tables | Process attestation, idempotency, registry | 7 years (audit retention) |

## Open Decisions

These items still need explicit sign-off before code lands. See `03_DECISIONS.md` for current status of each.

- Pilot table selection (small, low-volume, low consumer impact)
- Lateness measurement query results per large table
- Network drive path layout finalized
- Tokenization vault DDL reviewed and approved
- 2x/day pipeline schedule windows
- Phase 0 sign-off from architecture + compliance

## Document Map

### Tier 1 — Read first / on resume

| File | Purpose |
|---|---|
| `CURRENT_STATE.md` | **Read this first if resuming.** Where we are, what's next |
| `HANDOFF.md` | Continuity doc for picking up the project mid-flight |
| `GLOSSARY.md` | **Code/acronym reference** — if you see `D93`, `R8-PF-INST2`, `Tier δ`, `Pattern F`, etc. and don't recognize it, look here. Keep open in another tab. |
| `NORTH_STAR.md` | Single conflict-resolution rubric (5 pillars) |
| `00_OVERVIEW.md` | This file — orientation and current status |

### Tier 2 — Core architecture

| File | Purpose |
|---|---|
| `01_ARCHITECTURE.md` | Final architecture: layers, data flow, idempotency contract, recovery model |
| `02_PHASES.md` | Implementation roadmap with phases, deliverables, validation gates, status tracking |
| `09_VISUALS.md` | Mermaid diagrams: architecture, CDC vs snapshot, failover, idempotency layers |

### Tier 3 — Discipline and governance

| File | Purpose |
|---|---|
| `03_DECISIONS.md` | Decision log — every architectural decision with rationale, date, status |
| `04_EDGE_CASES.md` | Consolidated edge case register (M/S/I/N/P/G/D/F/V series) |
| `CHECKS_AND_BALANCES.md` | 5-gate validation discipline (D55 + D56) |
| `_validation_log.md` | Append-only audit trail for validation gate runs |
| `BACKLOG.md` | WSJF-prioritized follow-up items |
| `POLISH_QUEUE.md` | Cosmetic / readability tracker (P-numbers; added 2026-05-12 per D113); distinct from BACKLOG (substantive work) |
| `RISKS.md` | Active delivery risk register |

### Tier 4 — Operations and testing

| File | Purpose |
|---|---|
| `05_RUNBOOKS.md` | Operational runbooks: cutover, recovery, decryption, failover, backfill, CCPA, retention |
| `06_TESTING.md` | Test strategy: 5-tier pyramid, fixtures, scenarios |
| `07_LOGGING.md` | Logging strategy: levels, schema, per-layer content, Power BI integration |
| `MAINTENANCE.md` | Ongoing practices, ownership, dependency upgrades, drills |

### Tier 5 — Tooling

| File | Purpose |
|---|---|
| `SKILLS_PLAN.md` | Per-skill invocation map and composition |
| `MULTI_AGENT_GUIDE.md` | Subagent patterns and project-specific agents |
| `OBSIDIAN_GUIDE.md` | Optional Obsidian integration |

### Tier 6 — Phase-specific

| File | Purpose |
|---|---|
| `PHASE_1_DEEP_DIVE_PLAN.md` | Phase 1 round-by-round plan |
| `SESSION_2026-05-13_BUILD_LOG.md` | Consolidating record of the 7-commit Phase 1 build campaign (Round 3 + Round 4 + Round 6 Tier 2; 2026-05-13 / 2026-05-14) |
| `phase1/00_phase_overview.md` | Phase 1 narrative for engineers / management / auditors / operators |
| `phase1/01_database_schema.md` | Round 1 v3 — 24 tables + 11 stored procedures (🟢 Locked) |
| `phase1/02_configuration.md` | Round 2 — UdmTablesList + .env per-server + GPG envelope + parity baseline + Automic frozen-8 inventory (🟢 Locked; D63-D66) |
| `phase1/03_core_modules.md` | Round 3 — 17 Python module interface specs across 7 layers (🟢 Locked via D73; D67-D71) |
| `phase1/04_tools.md` | Round 4 — 11 operator CLI scripts wrapping Round 3 modules (🟢 Locked via D78; D74-D77) |
| `phase1/05_tests.md` | Round 5 — per-module + per-tool test plans across 28 artifacts × 6-tier pyramid (🟢 Locked via D83; D79-D82) |
| `phase1/06_deployment.md` | Round 6 — deployment workflow / 3-env topology / artifact contract / module startup / Pattern F retrospective (🟢 Locked via D88; D84-D87 + Pattern F D89-D91 🟢 Locked at R7 close-out 2026-05-11) |
| `phase1/07_schema_evolution_governance.md` | Round 7 — schema evolution governance / SP signature evolutions (SP-4 / SP-10 / new SP-12) / Automic frozen-11 / Phase 0 deliv 0.20 / RB-11 framing reconciliation / first production Pattern F invocation (🟢 Locked via D94 math-infeasibility; D92-D94) |
| `phase1/08_sub_agent_self_improvement.md` | Round 8 — Sub-Agent Self-Improvement Discipline (LAST Phase 1 round) / 7-skill suite + meta-doc / B144 sub-class 9.j formalization / B47-B159 cumulative triage / second production Pattern F invocation (🟢 Locked via D99 convergence-confirmed; D95-D99) |
| `phase1/01a_control_tables.md` | Round 1.5a — Control tables trigger tier (UdmTablesList + UdmTablesColumnsList canonical inventories + lifecycle + observability hooks). Sibling to R1 schema doc per D100 supplement-discipline (🟢 Locked via D101 math-infeasibility) |
| `phase1/01b_bronze_stage_example_ddl.md` | Round 1.5b — Canonical Bronze + Stage example DDL for DNA.osibank.ACCT (per `schema/table_creator.py` template). Sibling to R1 (🟢 Locked via D101) |
| `phase1/01c_data_flow_walkthrough.md` | Round 1.5c — AM cycle end-to-end data flow trace + observability annotations + 15-query dashboard catalog (for Power BI + Snowflake dashboards on the data pipeline process). Sibling to R1 (🟢 Locked via D101) |
| `phase1/07a_schema_contract_examples.md` | Round 1.5d — 3 example SchemaContract row clusters showing R7 SP-4/SP-10/SP-12 evolution + SupersededBy chain pattern. Sibling to R7 (🟢 Locked via D101) |
| `09_VISUALS.md` (§ ER diagrams) | Round 1.5e — 5 Mermaid erDiagram blocks (control tier + PII + orchestration + reconciliation + lifecycle clusters). Section added 2026-05-11 (🟢 Locked via D101) |
| `GLOSSARY.md` | Code/acronym reference (D-numbers, R-numbers, B-numbers, RB-N, SP-N, Pitfall #N, Pattern A-F, Tier α/β/γ/δ, Round-N.5, etc.) — open in another tab when unfamiliar codes appear |
| `phase1/03_round_0_5_spike_plan.md` | Pre-locking integration spike (D47) |
| `_research/` | Output directory for `udm-researcher` agent findings |

### Tier 7 — Skills (`.claude/skills/`)

15 skills total (8 foundational + 7 self-improvement added at Round 8 close-out 2026-05-11):

| Skill | Purpose |
|---|---|
| `udm-planning` | Round task decomposition with verification |
| `udm-brainstorm` | Force ≥3 alternatives before locking design |
| `udm-edge-case-validator` | M/S/I/N/P/G/D/F/V series check against artifacts |
| `udm-decision-recorder` | D-number / status / pillar / risk delta enforcement |
| `udm-runbook-author` | Runbook structure enforcement |
| `udm-data-engineer-review` | CDC/SCD2/Polars/Parquet/BCP pattern review |
| `udm-checks-and-balances` | 5-gate validation orchestration (D55) |
| `udm-round-closeout` | End-of-round aggregate doc updates (D60); extended with Section 10 self-improvement loop at Round 8 close-out 2026-05-11 |
| `udm-retrospective-collector` | Round 8 self-improvement skill 8.A: auto-append per-reviewer-event rows to `_reviewer_effectiveness.md` at close-out (per D95) |
| `udm-specialty-tuner` | Round 8 self-improvement skill 8.B: reviewer specialty trend analysis + prompt refinement proposals (per D95) |
| `udm-subclass-accumulator` | Round 8 self-improvement skill 8.C: Pitfall #9 sub-class auto-proposal at 2-event evidence threshold (per D95 + D96) |
| `udm-producer-checklist-evolver` | Round 8 self-improvement skill 8.D: producer Gate 1 strengthening proposals (per D95) |
| `udm-cycle-cadence-optimizer` | Round 8 self-improvement skill 8.E: per-tier cadence calibration + carryover-compounding monitor (per D95 + D97) |
| `udm-agent-prompt-versioner` | Round 8 self-improvement skill 8.F: semver application + archive + changelog; ONLY write authority for `.claude/agents/*.md` post-Round-8 (per D95 + D98) |
| `udm-cascade-audit-evolver` | Round 8 self-improvement skill 8.G (B143 implementation): Pattern F trigger evolution + Layer 1 / Layer 2 trigger-candidate proposals (per D95) |

### Tier 8 — Custom subagents (`.claude/agents/`)

| Agent | Purpose |
|---|---|
| `udm-design-reviewer` | Independent design QA + risk surfacing (D61) |
| `udm-test-author` | Tier 1/2/3 test authoring |
| `udm-researcher` | Proactive + on-demand research; output to `_research/` |
| `udm-cascade-auditor` | Pattern F Layer 2 paired-judgment cascade audit at round close-out (D90 🟢 Locked at R7 close-out 2026-05-11 per first-production empirical evidence; R8 second-production extended). Invoked as PAIR — never single instance. Triggers A/B/E (D-acceptance substantiation / B-item closure-target audit / CLAUDE.md convention registration) |

## Key Glossary (domain terms; for code/acronym reference see `GLOSSARY.md`)

| Term | Meaning |
|---|---|
| **CDC** | Change Data Capture — detecting changes in source data |
| **SCD2** | Slowly Changing Dimension Type 2 — versioned history of business key state with effective dates |
| **Stage** | Legacy intermediate layer (being removed) |
| **Bronze** | SCD2 dimension table — the regulator-truth state layer |
| **Parquet snapshot** | Per-pipeline-run dump of every extracted row; replaces Stage |
| **Parquet registry** | `General.ops.ParquetSnapshotRegistry` — index of every Parquet file |
| **Idempotency ledger** | `General.ops.IdempotencyLedger` — per-step status to short-circuit retries |
| **Tokenization vault** | `General.ops.PiiVault` — plaintext-to-token mapping; SQL Server-resident |
| **L_99** | Empirical 99th-percentile late-arrival horizon per table; drives LookbackDays |
| **PipelineExtraction trust gate** | Rule that delete detection only proceeds for dates with `Status='SUCCESS'` |
| **Verify-before-close** | Pre-MERGE source query confirming candidate deletes really aren't in source |

## Master Idempotency Invariant

> Running the pipeline against a state S — regardless of whether prior runs succeeded, failed, partially completed, or never executed — eventually produces a Bronze that is `f(S, full_history_of_source_states)`. Re-running with the same source state is a no-op.

See `01_ARCHITECTURE.md` § "Idempotency contract" for the complete enumeration of mechanisms that establish this invariant.

## Migration Triggers (when to revisit)

The architecture is stable for the foreseeable future, but these conditions warrant escalation to architecture review:

- Any table sustained > 50M rows/day delta
- Bronze approaches 100B rows
- Polars-hash plugin loses upstream maintenance
- Polars upgrade breaks hash determinism
- L_99 grows >25% on any table without explanation
- Snowflake monthly spend exceeds 80% of $120K/12 cap
- Tokenization vault row count approaches integer limits or query degradation
- DEK / vault key rotation cadence missed
- Idempotency ledger sees stuck IN_PROGRESS rows >2× T_max age
- Production outage > 48 hours despite failover protocol

See `03_DECISIONS.md` for the original migration-trigger discussion and `05_RUNBOOKS.md` for response procedures.
