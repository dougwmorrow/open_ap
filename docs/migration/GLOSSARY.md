# Glossary — Codes, Acronyms, and Naming Conventions

**For fresh engineers, AI agents, or auditors arriving mid-flight.** Every short-form identifier used across this project is defined here. If you see something like `D93`, `R7`, `R8-PF-INST2`, `Pitfall #9.j`, `Tier δ`, `SP-4`, `Pattern F`, `M-series`, or `WSJF` and don't recognize it — look here first.

If you're new to the project, read `00_OVERVIEW.md` for the high-level picture and `HANDOFF.md` for current state. This doc is the dictionary you keep open in another tab.

---

## Quick-reference table (one line per family)

| Code prefix | Family | Meaning | Source doc | Example |
|---|---|---|---|---|
| `D<N>` | Decisions | Architectural decisions (1-113 to date) | `03_DECISIONS.md` | `D93` = Cross-doc cascade propagation requirement; `D113` = POLISH_QUEUE.md cosmetic-tracker discipline |
| `R<N>` | Risks | Delivery risks (1-31 to date) | `RISKS.md` | `R28` = Round-level cascade self-attestation gap |
| `B<N>` | Backlog | WSJF-prioritized follow-up items (1-165 to date) | `BACKLOG.md` | `B144` = Pitfall #9 sub-class 9.j candidate |
| `P-<N>` | Polish queue | Cosmetic / readability / status-render / supersession-crumb / stale-date items (P-1+; introduced 2026-05-12) — **distinct from B-numbers** (substantive backlog); items here don't change behavior, decisions, runbooks, SP bodies, or code | `POLISH_QUEUE.md` | `P-1` = D109 supersession crumb refresh in Round 4.5b § 6 |
| `R<N>` (Phase context) | Round | Phase 1 sub-area rounds (1-8) | `PHASE_1_DEEP_DIVE_PLAN.md` | `R7` = Phase 1 Round 7 — Schema Evolution Governance |
| `R<N>C<M>` | Reviewer agent | Round-N Cycle-M reviewer | `_reviewer_effectiveness.md` | `R8C3` = Round 8 Cycle 3 reviewer |
| `R<N>C<M>-<K>` | Reviewer slot | Round-N Cycle-M slot-K within Pattern E batch | `_reviewer_effectiveness.md` | `R5C1-2` = Round 5 Cycle 1 slot 2 (cross-reference specialty) |
| `R<N>-PF-INST<K>` | Pattern F instance | Round-N Pattern F paired-judgment instance K (1 or 2) | `_reviewer_effectiveness.md` | `R8-PF-INST2` = Round 8 Pattern F Instance 2 (cascade-auditor) |
| `Pattern <X>` | Multi-agent pattern | Multi-agent orchestration discipline A-F | `MULTI_AGENT_GUIDE.md` | `Pattern E` = 5-agent deep validation |
| `SP-<N>` | Stored procedure | Round 1 stored procedure (1-12) | `phase1/01_database_schema.md` | `SP-4` = `PipelineExecutionGate_AcquireTest` |
| `RB-<N>` | Runbook | Operational runbook (1-12) | `05_RUNBOOKS.md` | `RB-12` = Pipeline Deployment runbook |
| `<X>-series` | Edge case series | Single-letter series prefix | `04_EDGE_CASES.md` | `F-series` = Failover/failure edge cases |
| `<X><N>` | Specific edge case | Series + index | `04_EDGE_CASES.md` | `F4` = Failover gate-acquire race |
| `Phase <N>` | Phase | High-level phase (0-6) | `02_PHASES.md` | `Phase 2` = Pilot Cutover |
| `P<phase>-<N>` | Phase-prefixed edge case | Edge case from a specific Phase deliverable | `CLAUDE.md` | `P0-4` = NULL PK filter pre-CDC (Phase 0-derived) |
| `B-<N>` (in CLAUDE.md) | Code-level B-item | Production code edge cases tracked at CLAUDE.md level (1-14) — **different from BACKLOG B<N>!** | `CLAUDE.md` | `B-1` = `_row_hash` VARCHAR(64) discipline |
| `E-<N>` | Code-level E-item | Edge cases at CLAUDE.md level (1-21) | `CLAUDE.md` | `E-1` = Oracle empty-string/NULL equivalence |
| `V-<N>` | Code-level V-item | Vault/concurrent-access edge cases at CLAUDE.md | `CLAUDE.md` | `V-4` = duplicate active rows during SCD2 window |
| `W-<N>` | Code-level W-item | Wave-of-fixes edge cases at CLAUDE.md (1-17) | `CLAUDE.md` | `W-2` = NULL sentinel `\x1FNULL\x1F` not `\x00NULL\x00` |
| `Tier <N>` | Test tier | 6-tier test pyramid (0-5) | `06_TESTING.md` | `Tier 0` = build-time smoke; `Tier 3` = Docker integration |
| `Tier <α/β/γ/δ>` | Artifact-complexity tier | Round 8 cycle-cadence-optimizer tier mapping | `phase1/08_sub_agent_self_improvement.md` § 6.3 | `Tier γ` = 50-100 KB spec doc |
| `Pitfall #<N>` | Pitfall | Numbered project pitfall (1-11) | `HANDOFF.md` §8 | `Pitfall #9` = fix-introduces-fresh-instance-of-same-bug-class |
| `Pitfall #9.<letter>` | Pitfall sub-class | Sub-class of #9 (a-j) | `HANDOFF.md` §8 | `Pitfall #9.j` = B-item status-render discipline |
| `<N>.<letter>` (Round 8 skills) | Skill code | Round 8 self-improvement skill | `phase1/08_sub_agent_self_improvement.md` | `8.B` = `udm-specialty-tuner` |
| `Trigger <letter>` (Pattern F) | Cascade-audit trigger | Pattern F trigger class A-F | `MULTI_AGENT_GUIDE.md` § Pattern F | `Trigger A` = D-acceptance substantiation |
| `Gate <N>` | Validation gate | 5-gate validation discipline (1-5) | `CHECKS_AND_BALANCES.md` | `Gate 2` = Quality assurance (independent review) |
| `CLI_*` / `CYCLE_*` / `MIGRATION_*` / `DEPLOYMENT_*` / `STARTUP_*` | EventType family | Canonical `PipelineEventLog.EventType` family | `CLAUDE.md` | `CLI_PARQUET_VERIFY` = parquet_verify CLI invocation |

---

## Status icons (used throughout)

These appear on decisions, risks, backlog items, edge cases, gate verdicts, and round-history rows. Read them like traffic lights.

| Icon | Meaning | Where you'll see it |
|---|---|---|
| 🟢 Locked / Complete / Pass | Approved + immutable post-validation | Decisions, runbooks, rounds, schema |
| 🟡 Proposed / Open / In-progress / Pending | Drafted but not locked; OR active risk; OR non-blocking concern | Decisions, risks, backlog, gate findings |
| 🔴 Open / Blocked / Deferred / Active mitigation | Substantive issue requires action; OR explicit pause | Decisions, risks, edge cases, gate findings |
| ⚪ Open low-priority | Active but low score (2 or below) | Risks, backlog |
| ⚫ Superseded / Closed / Removed | Replaced or done | Decisions, backlog, phases |
| ✅ Pass / Addressed / Clean | All gates green; nothing more to do | Gate results, edge cases |
| 🆕 NEW | Newly surfaced | Risk deltas, edge case proposals |
| ⬇️ De-escalated | Score reduced | Risks (post-mitigation evidence) |
| ⬆️ Escalated | Score increased | Risks (incident or new evidence) |

---

## D-numbers — Decisions

Architectural decisions recorded in `03_DECISIONS.md`. Each entry includes: status, driver, decision text, rationale, trade-offs, affects, reversibility, risk delta. Decisions are **append-only**; supersession is by ⚫ marking + forward-link to the new decision.

Range to date: **D1 through D113** (Multi-agent cascade 2026-05-12: D109 schedule revision + D110 DC-loss-no-DR acceptance + D111 operational-infra discipline + D112 just-in-time plan timing; D106 ⚫ Superseded by D109. D113 POLISH_QUEUE.md cosmetic-tracker discipline locked 2026-05-12 post-cascade).

Notable ones:
- **D2** — Drop the Stage layer; Parquet snapshots replace it
- **D6** — In-house tokenization vault (no cloud KMS)
- **D15** — Master idempotency invariant (re-running pipeline = no-op on unchanged source)
- **D17** — Idempotency ledger pattern
- **D30** — 7-year retention with legal-hold override
- **D34** — Greenfield deployment (not migration)
- **D40** — Schema evolution governance lock (forward-only)
- **D47** — Round 0.5 spike authorization
- **D49** — Round 1 schema v3 ready for DBA review
- **D55** — 5-gate validation discipline
- **D56** — Mandatory second-pass after any 🔴
- **D60** — Round close-out protocol
- **D61** — NORTH_STAR / RISKS / BACKLOG integration on every decision
- **D62** — Canonical Context Load (CCL) — multi-agent read protocol
- **D72** — Validation cycle termination rule (10-cycle ceiling + 3-consecutive-clean)
- **D73 / D78 / D94** — Math-infeasibility architectural-review acceptance (Rounds 3/4/7)
- **D83 / D88 / D99** — Convergence-confirmed architectural-review acceptance (Rounds 5/6/8)
- **D89 / D90 / D91** — Pattern F discipline (tiered close-out cascade audit; locked at R7 first-production close-out)
- **D92** — Schema evolution governance procedure (forward-only additive + SchemaContract supersession)
- **D93** — Cross-doc cascade propagation requirement
- **D95 / D96 / D97 / D98 / D99** — Round 8 Sub-Agent Self-Improvement Discipline (umbrella + 9.j sub-class + tier mapping + agent prompt versioning + Round 8 acceptance)
- **D100 / D101** — Round 1.5 Documentation Supplement Discipline (Round-N.5 mini-round pattern + R1.5 math-infeasibility acceptance per D73/D78/D94 precedent; supplements G1-G6 closing schema-story gaps for new engineers + dashboard authors)
- **D102** — PiiVault encryption algorithm pin: AES-256-GCM Python (`cryptography` library); wire format `nonce (12 bytes) || ciphertext || auth_tag (16 bytes)` in single VARBINARY column; unique nonce per encryption op (closes deliv 0.4 mask/unmask algorithm question)
- **D103** — Claude Code security model: 13-layer defense-in-depth with `/debi` working-directory boundary; threat-surface inversion (dev > test > prod — Claude installed on dev only, image-baked NO on test/prod); RHEL-shipped tools + Microsoft built-ins + Claude Code's own deny/allow lists; commercial endpoint security + AppArmor + third-party secrets managers ALL banned per user policy; canonical reference `docs/migration/SECURITY_MODEL.md`; `.env` migration `/debi/.env` → `/etc/pipeline/.env`. Closes deliv 0.12; opens R32 Low × Medium = 2 ⚪
- **D104** — Phase 2 pilot table = `DNA.osibank.ACCT` (1.2M rows; closes deliv 0.7)
- **D105** — SQL naming standards MANDATORY for new SP/view objects + filenames; **procedures** object name `General.{schema}.Proc{ProcedureName}` + file `{schema}_Proc{ProcedureName}.sql`; **views** object name `General.{schema}.Vw{ViewName}` + file `{schema}_Vw{ViewName}.sql`; grandfather clause for pre-D105 names per D92 forward-only; agents + skills enforce on new artifacts
- **D106** — Operational pipeline schedule: `JOB_PIPELINE_AM` = 02:00 weekdays; `JOB_PIPELINE_PM` = 17:00 daily. Supersedes Round 2 § 5.1 example values (06:00 / 18:00); structure + dependencies + CHECK constraints from D66 + Round 7 § 6.2 unchanged. Closes Phase 0 deliv 0.10
- **D107** — Two Windows network drive paths (3-revision arc same-session 2026-05-12; FINAL framing per user clarification "The H drive and VendorFiles drive are local environments for the company"): (1) **H drive** = PRIMARY local network drive (Windows drive-letter mount of canonical `\\archive\...` UNC per D2/D4); (2) **VendorFile location** = SECONDARY local network drive (also in-company DC; name reflects content, not vendor-managed location). Async replication H → VendorFile for in-DC redundancy + operational secondary use. Closes Phase 0 deliv 0.5. **DC-loss DR is NOT covered by D107** because both drives are local; delegated to D110 (explicit DC-loss-no-DR posture acceptance per B192 path b). Pre-fix-1 framing cast both as "offsite"; pre-fix-2 framing cast VendorFile as vendor-managed off-DC — both incorrect; reframed via 2 same-session fix-applications
- **D108** — Ops-channel architecture: EMAIL-centric via SQL Server Database Mail (`sp_send_dbmail`) + Automic notifications + Power BI metric alerts; **MS Teams** as secondary surface (via mailbox monitoring / PBI Teams integration / Automic-to-Teams webhook). NO Slack / NO PagerDuty / NO SMS. Supersedes B156 R7C1-5 advisory framing (project doesn't use SRE-canonical pattern). Closes Phase 0 deliv 0.20
- **D109** — Operational pipeline schedule revised (supersedes D106): dual-Automic prod-then-test with 4-hour gap; AM Prod 02:00 weekdays + Test 06:00 weekdays; PM Prod 17:00 daily + Test 21:00 daily. SQL-table coordination via PipelineExecutionGate per D29/D33/SP-3/SP-4
- **D110** — DC-loss-no-DR posture acceptance (B192 path b): project does NOT require off-DC Parquet mirror; recovery via company backup + source-DB re-extraction per D34/D14/D11/D28. Phase 0 deliv 0.19 RE-CLOSED 🟢
- **D111** — 🟡 Proposed: operational-infra D-number discipline — decisions touching paths/schedules/env-keys/credentials start 🟡 Proposed; flip 🟢 only after user-attestation + ≥4h pause or session boundary. Surfaced from D107 + D106→D109 churn (3 revisions in one session each)
- **D112** — Round-N.5 deep-dive plan timing = just-in-time at prior-phase close-out (formalizes B186); Phase 3 plan at P2R4 close-out; Phase 5 plan additionally gated by B191 Snowflake-test-conclusion
- **D113** — POLISH_QUEUE.md cosmetic-tracker discipline (P-N scheme). Canonical home for cosmetic / readability / status-render / supersession-crumb / stale-date items; distinct from B-numbers (substantive backlog); distinguishing test = does fix change behavior? Status legend 🟡 / 🟠 / ⚫ / ⬜ matches BACKLOG.md per Pitfall #9.j. Round-close-out skim via `udm-round-closeout/SKILL.md` CCL Stage 2.5; Pattern F audit coverage via `udm-cascade-audit-evolver/SKILL.md` Trigger B + E extensions. 🟢 Locked directly per D111 process-infra exemption (analogous to D55 / D60 / D89-D91 / D95-D99). ⬇️ DE-ESCALATES sub-class of R28

Citing style: `D93` (no leading zero). When referencing for status: `D89 (🟢 Locked 2026-05-11)`.

---

## R-numbers — Risks (in `RISKS.md`)

Active delivery risks (NOT edge cases — risks are about delivering the project; edge cases are about technical correctness in production).

Range to date: **R1 through R32**.

Score: `Likelihood × Impact` on a 1-9 scale. Thresholds:
- Score 6-9 → 🔴 Active mitigation required; review weekly
- Score 3-5 → 🟡 Track; review monthly
- Score 1-2 → ⚪ Document; review quarterly

Notable ones:
- **R01** — Phase 0 deliverables 3/20 complete (deliv 0.7 / 0.11 / 0.12 closed at Phase 0 prep close 2026-05-11; 17 still open)
- **R02** — Round 0.5 spike not yet executed
- **R03** — Single-engineer Python expertise (bus factor)
- **R11** — Validation discipline drift
- **R12** — Documentation drift (de-escalated 2026-05-10 per D61)
- **R16 / R17** — CCL compliance is honor-system; CCL quarterly audit procedure
- **R19** — Tier 0 smoke test drift
- **R20** — `/dev/shm` Snowflake key file leak
- **R21 / R23 / R25** — Round 3/4/5 BACKLOG carryover risks (closed at later rounds)
- **R22** — CLI exit-code drift
- **R24** — Test fixture canonical schema drift
- **R26 / R27** — Deployment artifact tampering / pre-deploy checklist override (Round 6)
- **R28** — Round-level cascade self-attestation gap (mitigated by Pattern F per D89-D91)
- **R29 / R30** — SchemaContract supersession growth / D93 sweep miss prose-form refs (Round 7)
- **R31** — Self-improvement loop feedback-loop instability (Round 8; mitigated by FREEZE conditions + auto-revert)
- **R32** — Claude Code credential-access risk (Phase 0 prep 2026-05-11; pre-mitigation Medium × High = 6 🔴; post-mitigation Low × Medium = 2 ⚪ via D103 13-layer defense)

Citing style: `R28` (no leading zero unless specified). Single-digit risks often shown as `R03` per Pitfall #8 discipline.

---

## B-numbers — Backlog (in `BACKLOG.md`)

WSJF-prioritized follow-up items. **Not the same as `B-<N>` in CLAUDE.md** (those are code-level edge cases).

Range to date: **B1 through B195** (post-Phase-0-prep + Phase 2 plan-draft + RB-14 cascades 2026-05-11; Phase 0 sweep + user-sign-off batch + Round 4.5b + Snowflake-test-conclusion gating + DC-loss DR + multi-agent cascade migration scripts 2026-05-12).

**WSJF** = `Cost of Delay (COD) ÷ Job Size (JS)`:
- COD: 1-5 (5 = waiting hurts a lot; 1 = harmless)
- JS: 1-5 (5 = days; 1 = minutes)
- WSJF: higher = do sooner

Status convention (Round 8 9.j discipline): leading badge `🟡 Open` / `⚫ Closed YYYY-MM-DD` must match inline annotation.

Each entry includes: Title, COD, JS, WSJF, Source (validation log entry / D-number / round), Phase, Owner.

How items get added:
1. Validation log → Backlog (🟡 findings get B-numbers)
2. Phase deliverable → Backlog (open Phase 0 0.X items become B-numbered when worked)

Recent B-items of note:
- **B129** — Carryover-compounding monitor (closed Round 8 via 8.E skill)
- **B143** — `udm-cascade-audit-evolver` 7th skill (closed Round 8)
- **B144** — Pitfall #9 sub-class 9.j candidate (closed Round 8 via formalization)
- **B155** — CLAUDE.md register evolved SP signatures + 9.j (closed Round 8 cascade-fix)
- **B160-B165** — Round 8 net-new items (Phase 2 R1 first-loop-invocation; udm-edge-case-evolver candidate; MAINTENANCE Pattern F refresh; agent version frontmatter; skill cascade dry-run; Pattern F Trigger G)
- **B166-B175** — Round 1.5 documentation supplement carryover (G1-G6 schema-story gap closure; B173 ER canonical sweep deferred to Phase 6)
- **B176-B181** — Round 1.5 backlog-batch closures + net-new (Pattern F Trigger J candidate B176; math-infeasibility sub-variant β B177; 4 storytelling queries B178-B181)
- **B182** — `.env` migration runbook ⚫ CLOSED via RB-14 (Phase 0 prep close 2026-05-11)
- **B183** — Parity baseline JSON capture script Tool 13 ⚫ CLOSED via Round 4.5 supplement `phase1/04a_phase_0_prep_tools.md` § 4 (spec 2026-05-11; implementation lands at P2R1)
- **B184** — `tools/verify_credentials_load.py` CLI shim Tool 12 ⚫ CLOSED via Round 4.5 supplement `phase1/04a_phase_0_prep_tools.md` § 3 (spec 2026-05-11; implementation lands at P2R1)
- **B185** — Populate `UdmTablesList.PiiColumnList` + `DataClassification` per source (DNA/CCM/EPICOR); residual from Phase 0 sweep 2026-05-12 deliv 0.3 partial-closure (D63 spec ✅; data-side awaits compliance) — WSJF 2.5; gates Phase 2 R3 production cutover
- **B186** — Author Phase 3 / 4 / 5 / 6 deep-dive plan docs — ⚫ CLOSED 2026-05-12 via D112 (just-in-time discipline locked at process level; plan-doc authoring becomes per-phase-close-out work-items)
- **B187** — Identify offsite Parquet replication target per D44 (⚫ CLOSED 2026-05-12 via D107 lock — dual H + VendorFile paths)
- **B188** — Implement Tool 14 `tools/measure_lateness.py` per Round 4.5b § 3; closes deliv 0.2 partial residual + adds new UdmTablesList columns + JOB_LATENESS_MEASURE — WSJF 2.0; impl at Phase 2 R1
- **B189** — Implement Tool 15 `tools/import_pii_inventory.py` per Round 4.5b § 4; closes deliv 0.3 partial residual to B185; CSV-driven UdmTablesList.PiiColumnList + DataClassification import + new PiiInventoryAuditLog table — WSJF 2.5; gates P2R3 tokenization
- **B190** — Implement Tool 16 `tools/measure_capacity_and_partition.py` per Round 4.5b § 5; closes deliv 0.17 partial residual + advisory for deliv 0.5; new CapacityBaselineLog table + JOB_CAPACITY_BASELINE — WSJF 2.0; drives Phase 5 cost projections (partition-recommendation logic refinement gated by B191)
- **B191** — Snowflake-test-conclusion + Phase 5 architecture firming (~mid-June 2026 per user-confirmation 2026-05-12; gates B186 Phase 5 deep-dive plan timing + B190 Tool 16 partition recommendation refinement) — WSJF 2.0
- **B192** — True off-DC DR target identification — ⚫ CLOSED 2026-05-12 via D110 path (b) acceptance (DC-loss-no-DR posture explicit)
- **B193** — Migration script: `UdmTablesList` ADD `LatenessL99Minutes` + `LatenessL99UpdatedAt` columns per D63 + D92 additive ALTER; required for B188 Tool 14 impl. WSJF 2.0
- **B194** — Migration script: CREATE TABLE `General.ops.PiiInventoryAuditLog` (append-only per D26 + D92 additive); required for B189 Tool 15 impl. WSJF 2.5
- **B195** — Migration script: CREATE TABLE `General.ops.CapacityBaselineLog` (append-only per D26 + D92 additive); required for B190 Tool 16 impl. WSJF 2.0

---

## Round codes — Phase 1 (R1-R8) + Phase 2 (P2R1-P2R4)

Phase 1 is divided into 8 sub-area rounds (Phase 1 complete 2026-05-11). Phase 2 plan-draft authored 2026-05-11 with 4 proposed rounds. Round numbers are **distinct from R-numbers in RISKS.md** — context disambiguates.

### Phase 1 rounds (all 🟢 Locked 2026-05-11)

| Round | Sub-area | Status (post-2026-05-11) | Locked via |
|---|---|---|---|
| R1 (Round 1) | Database Schema | 🟢 Locked (v3) | D49 second-pass |
| R2 (Round 2) | Configuration | 🟢 Locked | D63-D66 (3-pass) |
| R3 (Round 3) | Core Modules | 🟢 Locked | D67-D73 math-infeasibility |
| R4 (Round 4) | Tools (CLIs) | 🟢 Locked | D74-D78 math-infeasibility |
| R5 (Round 5) | Tests | 🟢 Locked | D79-D83 convergence-confirmed |
| R6 (Round 6) | Deployment | 🟢 Locked | D84-D88 convergence-confirmed |
| R7 (Round 7) | Schema Evolution Governance | 🟢 Locked | D89-D94 math-infeasibility + first-production Pattern F |
| R8 (Round 8) | Sub-Agent Self-Improvement Discipline (LAST Phase 1 round) | 🟢 Locked | D95-D99 convergence-confirmed |

### Phase 2 rounds (proposed 2026-05-11; 🟡 Plan-draft per `phase2/00_phase_overview.md`)

| Round | Sub-area | Status | Notes |
|---|---|---|---|
| P2R1 (Phase 2 Round 1) | Pilot Prerequisites | ⬜ Pending plan-review | RB-14 .env migration + Round 0.5 spike + Phase 1 deploy parity + Tier 0/1/2 green + dev smoke test |
| P2R2 (Phase 2 Round 2) | Dry-Run on Test | ⬜ Pending P2R1 | ACCT end-to-end on test + parallel legacy run + 7-day soak + Bronze parity comparison |
| P2R3 (Phase 2 Round 3) | Production Cutover | ⬜ Pending P2R2 + R02 close | Apply RB-1 cutover + 14-day production soak |
| P2R4 (Phase 2 Round 4) | Post-Cutover Verification + Phase 2 Close-Out | ⬜ Pending P2R3 | RB-3 + RB-9 drills + Phase 2 acceptance D-number lock + close-out cascade |

Plus:
- **Round 0.5** — pre-implementation spike (per D47); validates D6/D16/D29 integrations before full Phase 1 implementation; is a 🔴 blocker for P2R3 production cutover per Phase 2 plan
- **Round N.5** — Documentation supplement mini-round (per D100; additive sibling docs to Round N spec; locked-artifact-respecting per D40 + D92 forward-only). Example: Round 1.5 produced 5 supplements (G1-G6) closing schema-story gaps in Round 1 schema doc — sibling files at `phase1/01a_*.md`, `phase1/01b_*.md`, etc.

When you see "R7C5" — that's Round 7 Cycle 5. When you see just "R7" with no cycle number — that's Round 7 (the whole round). When you see "R7" inside RISKS.md context, it would be Risk 7 (R07 typically — different family). **For Phase 2 rounds**: use the explicit `P2R<N>` prefix to disambiguate from Phase 1 R<N>.

---

## Reviewer agent codes — `R<N>C<M>-<K>` and `R<N>-PF-INST<K>`

Per `_reviewer_effectiveness.md`. Each row is one reviewer-spawning event.

| Pattern | Meaning | Example |
|---|---|---|
| `R<N>C<M>` | Round-N Cycle-M reviewer (single-agent) | `R8C3` = Round 8 Cycle 3 (post-cycle-2-fix comprehensive verification) |
| `R<N>C<M>-<K>` | Round-N Cycle-M Slot-K (Pattern E 5-agent batch) | `R5C1-2` = Round 5 Cycle 1 Slot 2 (cross-reference specialty) |
| `R<N>-PF-INST<K>` | Round-N Pattern F paired-judgment instance K (K ∈ {1, 2}) | `R8-PF-INST2` = Round 8 Pattern F Instance 2 (cascade-auditor; caught B155 false-closure) |
| `R<N>-RETRO-INST<K>` | Round-N retroactive Pattern F | `R6-RETRO-INST1` = Round 6 retroactive Pattern F Instance 1 |
| `R<N>-UNSCOPED-INST<K>` | Round-N unscoped (cross-round) Pattern F | `R6-UNSCOPED-INST1` = Round 6 unscoped Pattern F Instance 1 |

Specialty types (the "K" position in 5-agent Pattern E):
- Slot 1 = **column-walk** — Pitfall #9 sub-class drift (column/parameter/enum/type/cite)
- Slot 2 = **cross-reference** — Phase-0 miscites + cross-doc consistency + B-triage drift
- Slot 3 = **internal-consistency** — same-artifact contradictions, scope-vs-content mismatches
- Slot 4 = **D72-edge-cases** — edge-case enumeration gaps + B-triage classification
- Slot 5 = **advisory-research** — external-evidence grounding (non-blocking framing findings)

Other specialties used in single-agent cycles:
- **comprehensive-5-gate** — fix-cycle verification (D56 second-pass class)
- **sleeper-bug-stress** — mandatory final cycle for spec docs >50 KB; finds what prior reviewers missed
- **convergence-verification** — final-cycle check before D72 acceptance
- **mechanical-fix** — fixes that ADD content (high-risk for Pitfall #9.i fresh-instance recurrence)
- **cascade-audit** — Pattern F Layer 2 paired-judgment

---

## Pattern codes — Multi-agent orchestration (Pattern A-F)

Per `MULTI_AGENT_GUIDE.md`. Six orchestration patterns:

| Pattern | Purpose | When to use |
|---|---|---|
| **Pattern A** | Parallel research | Multi-faceted question; agents in parallel; results return together |
| **Pattern B** | Specialized review | One custom subagent + one artifact (e.g., `udm-design-reviewer` on a stored proc) |
| **Pattern B1** | Build cohort — single-agent | One author agent builds + tests one tool / module end-to-end; smallest unblocked cohort pattern (e.g. § 3.10 `log_retention_cleanup.py` 2026-05-12) |
| **Pattern B2** | Build cohort — paired (author + test-author) | Two parallel agents read the canonical spec independently per D55 producer ≠ reviewer; design-reviewer agent NOT spawned (small-scope + low-risk; e.g. § 3.10 + § 3.8 + § 3.6 2026-05-12) |
| **Pattern B3** | Build cohort — triad (author + test-author + design-reviewer) | Three parallel agents per D55 + D56 full discipline; reviewer issues blocking 🔴 findings before 🟢 build-state (e.g. Wave 1 cohort 2026-05-12; Wave 2 cohort 2026-05-13) |
| **Pattern C** | Test-first via specialist | TDD-style: spec → `udm-test-author` → fail → impl → pass → `udm-design-reviewer` |
| **Pattern D** | Reflection / progress check | Spawn reflection agent to assess phase progress |
| **Pattern E** | 5-agent deep validation | Spec docs >50 KB; 4 blocking reviewers + 1 advisory researcher in one cycle |
| **Pattern F** | Cascade audit (round close-out) | Mandatory at every round close-out; Layer 1 deterministic + Layer 2 paired-judgment |

Pattern F decomposition:
- **Layer 1** = `tools/verify_cascade.py` (deterministic script; Triggers C/D/F = stale references / forward-cite resolution / aggregate-doc freshness)
- **Layer 2** = `udm-cascade-auditor` × 2 paired instances (Triggers A/B/E = D-acceptance substantiation / B-item closure-target audit / CLAUDE.md convention registration)

---

## Stored procedure codes — SP-N (Round 1 schema)

Per `phase1/01_database_schema.md`. Range to date: **SP-1 through SP-12**.

| SP-N | Name | Purpose |
|---|---|---|
| SP-1 | `PiiVault_GetOrCreateToken` | Atomic UPDLOCK+HOLDLOCK tokenization (D6 + I3 race protection) |
| SP-2 | `PiiVault_Decrypt` | Single-token decryption + access audit log |
| SP-3 | `PipelineExecutionGate_AcquireProd` | Acquire AM/PM cycle gate on prod (D29) |
| SP-4 | `PipelineExecutionGate_AcquireTest` | Acquire AM/PM cycle gate on test + heartbeat-failover logic (D29 + R7 `@AcknowledgmentOnly` extension per B79) |
| SP-5 | (TBD) | (reserved) |
| SP-6 | `IdempotencyLedger_StartStep` | Begin a pipeline step with crash-recovery short-circuit (D17) |
| SP-7 | `IdempotencyLedger_CompleteStep` | Complete or fail a pipeline step |
| SP-8 | `IdempotencyLedger_RecoveryStartupSweep` | Pipeline startup recovery sweep (D85) |
| SP-9 | `PipelineExecutionGate_RequestCancellation` | Operator-initiated cancellation request (D33) |
| SP-10 | `PiiVault_EnforceRetention` | 7-year retention enforcement (D30; R7 `@CutoffOverride` + `@CategoryFilter` extensions per B93+B94) |
| SP-11 | `PipelineExecutionGate_AcknowledgeCancellation` | Test-side acknowledgment of cancellation (D33) |
| SP-12 | `PiiVault_ProcessCcpaDeletion` | NEW at R7 — CCPA right-to-deletion (RB-10; B81) |

---

## Runbook codes — RB-N

Per `05_RUNBOOKS.md`. Operational runbooks for failure scenarios + routine procedures. Range to date: **RB-1 through RB-14**.

| RB-N | Title | Scope |
|---|---|---|
| RB-1 | (pipeline cutover) | Pre-flight + cutover protocol |
| RB-2 | Manual failover to test-as-prod | Manual emergency failover |
| RB-3 | (pipeline operator decryption) | Authorized decryption procedure |
| RB-4 | (auditor decryption) | Auditor-class decryption + audit-trail |
| RB-5 | (vault key recovery) | Vault key rotation + emergency restore |
| RB-6 | Vault corruption response | Immediate response to vault data integrity issue |
| RB-7 | DR rehearsal (quarterly drills) | Q1/Q3 = server failover; Q2/Q4 = data center loss |
| RB-8 | Bronze rebuild from Parquet | Re-build SCD2 from network-drive Parquet archive |
| RB-9 | Auto-failover via Automic | Automatic gate-based failover (D29 + D33 cancellation) |
| RB-10 | CCPA right-to-deletion | Operator-driven CCPA + GDPR Art 17 deletion (uses SP-12 per R7) |
| RB-11 | 7-Year Retention Enforcement | Periodic retention + legal-hold checks (per R7 framing reconciliation per B101) |
| RB-12 | Pipeline Deployment | Code deployment to dev/test/prod (R6; uses D84 artifact contract) |
| RB-13 | Permanent-retire Table | Source table permanently decommissioned; closes B168 (authored Round 1.5 backlog batch 2026-05-11) |
| RB-14 | `.env` Location Migration | Per-server `/debi/.env` → `/etc/pipeline/.env` migration; closes B182 (authored Phase 0 prep close 2026-05-11); Phase 2 R1 prerequisite |

---

## Edge case series — single-letter prefixes (in `04_EDGE_CASES.md`)

Edge cases are about technical correctness IN PRODUCTION (distinct from risks which are about DELIVERING the project). Each series is one letter:

| Series | Theme | Example |
|---|---|---|
| **M** | (Memory / measurement) | (specific M-cases in 04_EDGE_CASES.md) |
| **S** | (Schema / source-system) | S-cases per the register |
| **I** | Idempotency | I3 = duplicate INSERT race (vault + ledger + tokenization-batch facets) |
| **N** | (Network / null) | N-cases per the register |
| **P** | PII / Provenance / Protection | P2 = OrphanedTokenLog wiring; P3 = vault corruption |
| **G** | (Governance / global) | G-cases per the register |
| **D** | (Data — overloaded with Decisions in this prefix) | D-cases per the register |
| **F** | Failover / failure | F4 = gate-acquire race; F15-F19 = cancellation flow |
| **V** | Vault / versioning | V-1 through V-10 = vault provenance edge cases |
| **T** | Test (added Round 5) | T1-T4 = test-series cases |
| **DP** | Deployment pipeline (added Round 6) | DP1-DP7 = deployment-specific |
| **SI** | Self-improvement (added Round 8) | SI1-SI23 = self-improvement-loop edge cases |

Each entry includes: ID, description, status, mitigation, optional Phase reference.

---

## Phase codes — Phase 0 through Phase 6

Per `02_PHASES.md`. Sequential phases of the project:

| Phase | Name | Status (post-2026-05-11) |
|---|---|---|
| Phase 0 | Decisions, Measurements, Fixtures | 🟡 In progress (3/20 deliverables — Phase 0 prep close 2026-05-11 closed deliv 0.7 / 0.11 / 0.12 via D104 / D103) |
| Phase 1 | Foundation Infrastructure | 🟢 Complete — Rounds 1-8 all 🟢 Locked |
| Phase 2 | Pilot Cutover (small table end-to-end) | ⬜ Not started (next) |
| Phase 3 | Large Tables (windowed extract + delete detection) | ⬜ Not started |
| Phase 4 | Production Rollout (per-table enablement) | ⬜ Not started |
| Phase 5 | Snowflake Integration | ⬜ Not started |
| Phase 6 | Data Health Checks (+ Power BI dashboards) | ⬜ Not started |

Note: Old Phase 6 (Cleanup) was REMOVED per D34 (greenfield deployment, no legacy migration). Current Phase 6 was renumbered from Phase 7.

Phase deliverables use `<phase>.<index>` notation: e.g., `0.4` = Phase 0 deliverable 4 (Tokenization vault DDL); `0.20` = Phase 0 deliverable 20 (Ops-channel client, added R7 per B82).

---

## CLAUDE.md code-level identifiers — IMPORTANT distinction

`CLAUDE.md` (project root) tracks 4 code-level edge-case families that are **distinct from the doc-level edge cases in `04_EDGE_CASES.md`**. These exist because they fix specific bugs at code level:

| Prefix in CLAUDE.md | Family | Range | Distinct from |
|---|---|---|---|
| `B-<N>` | Code-level edge case (BCP-related) | B-1 through B-14 | BACKLOG `B<N>` (different! No hyphen vs hyphen) |
| `E-<N>` | Code-level edge case (CDC/SCD2) | E-1 through E-21 | `04_EDGE_CASES.md` D-series and other |
| `V-<N>` | Vault / concurrent-access edge case | V-1 through V-11 | `04_EDGE_CASES.md` V-series (related but separate set) |
| `W-<N>` | Wave-of-fixes edge case | W-1 through W-17 | Nothing equivalent |
| `P<phase>-<N>` | Phase-prefixed edge case | P0-1 through P3-X | `04_EDGE_CASES.md` P-series |
| `OBS-<N>` | Observability edge case | OBS-1 through OBS-7 | (unique to CLAUDE.md) |
| `SCD2-P1-<letter>` | Phase 1 SCD2 edge case | SCD2-P1-a through SCD2-P1-f | (unique to CLAUDE.md) |
| `SCD2-R<N>-<letter>` | Round-N SCD2 edge case | SCD2-R2-a / SCD2-R10.2 etc. | (unique to CLAUDE.md) |
| `LT-<N>` | Large-table edge case | LT-2, LT-3 | (unique) |
| `DIAG-<N>` | Diagnostic edge case | DIAG-1 | (unique) |
| `CDC-NOW-MS` | Specific CDC `_cdc_now_ms()` edge case | (singleton) | (unique) |
| `WORKER-SERIALIZE` | Worker serialization edge case | (singleton) | (unique) |
| `SS-1` | StripSuffix edge case | (singleton) | (unique) |

**The most common point of confusion**: `B-1` (CLAUDE.md hash-VARCHAR-64 discipline) vs `B1` (BACKLOG B1 = OrphanedTokenLog wiring). The hyphen matters.

---

## Tier codes

Two distinct "Tier" families:

### Test pyramid tiers (Tier 0-5) — per `06_TESTING.md`

| Tier | Scope | Constraint |
|---|---|---|
| Tier 0 | Build-time smoke (D67) | <5s, no external deps |
| Tier 1 | Unit (per-function) | Run in CI per-commit |
| Tier 2 | Property-based (Hypothesis) | `max_examples=200` default per D81 |
| Tier 3 | Docker SQL Server integration (D70) | Run in CI per-PR; testcontainers `:2022-CU14-ubuntu-22.04` per D79 + B116 |
| Tier 4 | Crash injection (`kill -9` at boundaries) | Manual or scheduled |
| Tier 5 | Manual quarterly audit | Quarterly per MAINTENANCE.md |

### Artifact-complexity tiers (Tier α/β/γ/δ) — per Round 8 D97

Project-derived taxonomy (NOT external SE standard). Used by `udm-cycle-cadence-optimizer` skill to recommend per-round cycle cadence.

| Tier | Definition | Recommended cadence |
|---|---|---|
| Tier α | Single-section artifact <10 KB | D56 2-pass |
| Tier β | Multi-section 10-50 KB | Pattern E from cycle 1 + 2-3 verify cycles |
| Tier γ | Multi-section spec doc 50-100 KB | Pattern E + sleeper-bug stress final + Pattern F close-out |
| Tier δ | Mega-spec >100 KB OR mega-table inventory | Above + math-infeasibility OR convergence-confirmed acceptance |

Empirical fit: R3 (80 KB)/R5 (75)/R7 (50) → Tier γ; R6 (110 KB)/R8 (~130) → Tier δ.

---

## Pitfall codes — Pitfall #1 through Pitfall #12

Per `HANDOFF.md` §8. Lessons learned from actual project mistakes.

| Pitfall | Title | Lesson |
|---|---|---|
| #1 | Producing artifacts without validation | D55 5-gate is mandatory |
| #2 | Premature 🟢 lock | D56 independent second-pass mandatory after 🔴 |
| #3 | Decision text drifting from doc body | Cross-doc consistency = Gate 1 |
| #4 | Filtered-index + lookup-filter mismatch | Check index predicate matches lookup predicate |
| #5 | Fixing one bug introduces another | First-pass + second-pass discipline catches |
| #6 | Plan drift from execution | Round 0.5 spike validates decisions before they ossify |
| #7 | Cross-doc inconsistency on phase scope | Sweep `02_PHASES.md` / `phase1/00_phase_overview.md` / `PHASE_1_DEEP_DIVE_PLAN.md` on any phase scope change |
| #8 | Risk-delta-without-register-update | When a decision claims `MITIGATED: R<N>` or similar, verify RISKS.md row updated |
| #9 | Fix-introduces-fresh-instance-of-same-bug-class | The big one — 10 sub-classes 9.a-9.j formalized |
| #10 | Tier 0 sketch is a runnability check, not a replacement for error-path coverage | Tier 0 + Tier 1 are distinct purposes |
| #11 | Cascade-level self-attestation without independent verification | Pattern F discipline mitigates (D89-D91) |
| #12 | Naming-standard locked late | Grandfather cost is permanent — lock conventions in 30-min kickoff BEFORE output begins (Phase 0 prep 2026-05-11; D105) |

### Pitfall #9 sub-classes (9.a through 9.m)

When a 🔴 fix introduces a NEW reference to a canonical source, the validator MUST re-verify EVERY new reference. 13 sub-classes formalized (one per recurring bug pattern):

| Sub-class | Name | First evidence |
|---|---|---|
| **9.a** | Column-name drift (invented or misspelled canonical column) | D49 v2→v3 |
| **9.b** | Parameter-name drift (invented SP parameter) | Round 2 second-pass |
| **9.c** | Enum-value drift (invented enum value, CHECK constraint violation) | Round 2 second-pass |
| **9.d** | Type-width drift (correct base type, wrong width — e.g., `NVARCHAR(50)` vs `(20)`) | Round 3 second-pass |
| **9.e** | Unicode-vs-ASCII drift (`NVARCHAR` vs `VARCHAR`; `CHAR` vs `NCHAR`) | Round 3 second-pass |
| **9.f** | Cross-table column-name lift (column from table A applied to table B) | Round 3 cycle 4 |
| **9.g** | Python keyword-only marker (`*,`) drift per PEP 3102 | Round 4 cycle 3 |
| **9.h** | Wrong section number with invented description | Round 4 cycle 8 |
| **9.i** | Process-discipline-claim drift (false-closure, stale B-range, silent omission, invented forward-reference) | Round 5/6 (formalized Round 6 close-out) |
| **9.j** | B-item status-render discipline (leading `🟡 Open` badge + inline `**CLOSED**` annotation mismatch) | Round 6 unscoped + Round 7 first-production Pattern F (formalized Round 8 close-out) |
| **9.k** | Arithmetic-propagation drift (count / row-index updated in one location, mirrors not propagated) | 5-event evidence base 2026-05-12 (CLAUDE.md L634 stale-summary propagation + Phase 2 R1 cycle 1 cascade); formalized 2026-05-12 per B198 + producer self-check Step 7 (regex-sweep + enumerate when counts change) |
| **9.l** | Canonical-schema-detail working-memory drift (fix references canonical schema object but producer skipped re-read of canonical DDL) | 5-event evidence base from Phase 2 R1 spec doc Pattern E cycles 2-6 2026-05-12; formalized 2026-05-12 per B201 + producer self-check Step 8 (re-read canonical DDL before fixing schema-referencing procedures) |
| **9.m** | Discipline-not-applied-to-its-own-tracker (new tracker / skill / discipline authored without immediately applying its rule to itself) | 2-event evidence base 2026-05-12 (D113 POLISH_QUEUE.md + udm-progress-logger); formalized 2026-05-12 per B196 + producer self-check Step 9 (apply new discipline to its own authoring artifact + verify pass) |

Producer self-check: walk each sub-class against the artifact before Gate 2.

---

## Round 8 self-improvement skill codes — 8.A through 8.G

Per `phase1/08_sub_agent_self_improvement.md`. 7 skills + 1 meta-doc + governance loop.

| Code | Skill | Role |
|---|---|---|
| 8.A | `udm-retrospective-collector` | Auto-append per-reviewer-event rows to `_reviewer_effectiveness.md` |
| 8.B | `udm-specialty-tuner` | Reviewer specialty trend analysis + prompt refinement proposals |
| 8.C | `udm-subclass-accumulator` | Pitfall #9 sub-class auto-proposal at 2-event evidence threshold |
| 8.D | `udm-producer-checklist-evolver` | Producer Gate 1 strengthening proposals |
| 8.E | `udm-cycle-cadence-optimizer` | Per-tier cadence calibration + carryover-compounding monitor |
| 8.F | `udm-agent-prompt-versioner` | Semver application + archive + changelog; ONLY write authority for `.claude/agents/*.md` post-Round-8 |
| 8.G | `udm-cascade-audit-evolver` | Pattern F trigger evolution (B143 implementation) |

Cascade order: 8.A → (8.B/C/D/E/G in parallel) → user-review session → 8.F applies approved batch.

---

## Pattern F trigger codes — Trigger A through Trigger F

Per `MULTI_AGENT_GUIDE.md` § Pattern F. Six cascade-audit trigger classes:

| Trigger | Layer | Class |
|---|---|---|
| **A** | Layer 2 (judgment) | D-acceptance substantiation (every architectural-review acceptance has the cycle evidence the variant claim requires) |
| **B** | Layer 2 (judgment) | B-item closure-target audit (every "CLOSED" BACKLOG entry has its cited target docs actually reflecting the change) |
| **C** | Layer 1 (deterministic) | Stale references (regex `B<N>-B<M>` ranges; `Round N — <name>` claims; B-count drift) |
| **D** | Layer 1 (deterministic) | Forward-cite resolution (every `RB-N` / `SP-N` / `B-N` / `D-N` / `R-N` reference resolves to canonical anchor) |
| **E** | Layer 2 (judgment) | CLAUDE.md convention registration (new conventions like EventType families, SP signatures, Tier classifications are registered) |
| **F** | Layer 1 (deterministic) | Aggregate-doc freshness (`02_PHASES.md` + `PHASE_1_DEEP_DIVE_PLAN.md` + `HANDOFF.md` §3 in-flight reflect current locked-Round state) |

Layer 1 = 100% deterministic script (`tools/verify_cascade.py`); Layer 2 = paired-judgment agents (`udm-cascade-auditor` × 2 instances; never single).

Candidate Trigger G/H proposed at Round 8 close-out for `udm-cascade-audit-evolver` consumption at Phase 2 R1:
- **G** — B-item status-render consistency (Layer 1 deterministic check for 9.j class)
- **H** — Closure-target-content-verification (Layer 1 grep cited identifiers against target docs)

---

## EventType families — `PipelineEventLog.EventType`

Per CLAUDE.md. Canonical EventType prefixes for the operational metadata table:

| Family | Purpose | Example values |
|---|---|---|
| `EXTRACT` | Source extraction step | `EXTRACT` (singleton) |
| `BCP_LOAD` | BCP CSV → SQL Server load | `BCP_LOAD` (singleton — removed from small_tables; lives inside CDC/SCD2 promotion events per OBS-1) |
| `CDC_PROMOTION` | Polars CDC comparison + stage write | `CDC_PROMOTION` (singleton) |
| `SCD2_PROMOTION` | Polars SCD2 comparison + Bronze write | `SCD2_PROMOTION` (singleton) |
| `CSV_CLEANUP` | Temporary CSV file removal | `CSV_CLEANUP` (singleton) |
| `TABLE_TOTAL` | End-to-end per-table wall time | `TABLE_TOTAL` (singleton; also `Status=SKIPPED` for lock-blocked per OBS-3) |
| `CLI_*` | CLI tool invocation audit row (D76 + R4 tools) | `CLI_PARQUET_VERIFY`, `CLI_DECRYPT_PII`, `CLI_PROMOTE_TEST_TO_PROD` (11 values per R4) |
| `CYCLE_*` | Pipeline cycle lifecycle | `CYCLE_FAILED_OVER`, `CYCLE_CANCELLED` |
| `DEPLOYMENT_*` | Per-environment deployment audit | `DEPLOYMENT_DEV`, `DEPLOYMENT_TEST`, `DEPLOYMENT_PROD`, `DEPLOYMENT_ROLLBACK` (R6 D87) |
| `MIGRATION_*` | `migrations/<name>.py` script invocation | `MIGRATION_<NAME>` (one per script); R7 added canonical `MIGRATION_AUTOMIC_INVENTORY` |
| `STARTUP_*` | Module startup sequence (R6 D85) | `CREDS_LOAD`, `VAULT_CONFIG`, `PARITY_CHECK`, `LEDGER_SWEEP`, `ORCHESTRATION_START` |
| `DISTRIBUTION_CHECK` | Numeric distribution baseline (B-10) | `DISTRIBUTION_CHECK` (singleton) |
| `MODIFIED_SWEEP` | Modified-date sweep result (LT-2) | `MODIFIED_SWEEP` (singleton) |

---

## Validation discipline codes — 5-gate (Gate 1-5)

Per `CHECKS_AND_BALANCES.md`. Every artifact passes 5 gates before being declared complete:

| Gate | Name | Check |
|---|---|---|
| Gate 1 | Cross-reference | Consistent with the rest of the doc set |
| Gate 2 | Quality assurance (independent review) | A second pair of eyes (different agent) confirms correctness |
| Gate 3 | Edge case enumeration | M/S/I/N/P/G/D/F/V series walked |
| Gate 4 | Edge case validation | Every ✅-claimed case has tangible verification |
| Gate 5 | Idempotency / regression | D15 invariant preserved; no broken prior work |

---

## Term abbreviations

| Acronym | Meaning |
|---|---|
| **CCL** | Canonical Context Load (D62; multi-agent read protocol — Stage 1 mandatory before any substantive work) |
| **CDC** | Change Data Capture — detecting changes in source data |
| **SCD2** | Slowly Changing Dimension Type 2 — versioned history of business key state with effective dates |
| **PK** | Primary Key |
| **PII** | Personally Identifiable Information |
| **DEK** | Data Encryption Key |
| **TDE** | Transparent Data Encryption (SQL Server) |
| **TPM2** | Trusted Platform Module 2.0 (D64 GPG passphrase sealing) |
| **BCP** | Bulk Copy Program (SQL Server `bcp.exe`) |
| **WSJF** | Weighted Shortest Job First (`COD ÷ JS`; backlog prioritization) |
| **COD** | Cost of Delay (1-5; component of WSJF) |
| **JS** | Job Size (1-5; component of WSJF) |
| **DR** | Disaster Recovery |
| **AG** | Availability Group (SQL Server) |
| **UDM** | Unified Data Management (the project name) |
| **RHEL** | Red Hat Enterprise Linux |
| **GPG** | GNU Privacy Guard (encryption tool) |
| **CCPA** | California Consumer Privacy Act |
| **GDPR** | General Data Protection Regulation (EU) |
| **DBA** | Database Administrator |
| **L_99** | Empirical 99th-percentile late-arrival horizon per table (drives LookbackDays per D11) |
| **AM/PM** | AM cycle (morning pipeline run) / PM cycle (evening run); per D29 |
| **D72** | The 10-cycle ceiling + 3-consecutive-clean termination rule (Decision 72) |
| **`_cdc_now_ms()`** | CDC engine wall-clock helper (millisecond precision; per CDC-NOW-MS rule) |

---

## Cross-doc reference syntax

When a doc cites another doc:

| Syntax | Meaning |
|---|---|
| `phase1/01_database_schema.md L1212` | Specific line number in a doc |
| `§ 2.3` | Section 2 subsection 3 (intra-doc reference) |
| `§ 2.3 L45-78` | Section + line range |
| `HANDOFF.md §8 Pitfall #9.j` | Document + section + specific item |
| `D89/D90/D91` (or `D89-D91`) | Decision range (read as "D89 through D91") |
| `B47-B107` | BACKLOG item range |
| `Round X cycle Y` | Validation cycle context |

---

## Common pitfalls in code reading

These are real points of confusion:

1. **`R<N>` is overloaded**: Risk (R28 = risk 28) vs Round (R7 = Phase 1 Round 7) vs Reviewer (R8C3 = Round 8 Cycle 3). Context disambiguates: RISKS.md row = risk; round narrative = round; `_reviewer_effectiveness.md` table = reviewer.
2. **`B-<N>` (hyphen) vs `B<N>` (no hyphen)**: `B-1` = CLAUDE.md code-level edge case; `B1` = BACKLOG follow-up item.
3. **`D-<N>` (hyphen) vs `D<N>` (no hyphen)**: `D` series in `04_EDGE_CASES.md` (the edge-case D-series, distinct from Decisions) vs `D<N>` Decision (most common usage in this project).
4. **`P0-1` vs `Phase 0 deliverable 1`**: Both refer to Phase 0; `P0-1` is the phase-prefixed edge case ID. `Phase 0 deliverable 0.4` is one of 20 Phase 0 deliverables in `02_PHASES.md`.
5. **`Tier 0` vs `Tier α`**: Different tier taxonomies. Tier 0/1/2/3/4/5 = test pyramid. Tier α/β/γ/δ = artifact-complexity (Round 8 D97).
6. **`Pattern E` vs `Pattern F`**: Pattern E = per-artifact spec doc validation (CONTENT). Pattern F = per-round cascade audit (CONSISTENCY across aggregate docs). Both run per round; neither replaces the other.
7. **"R7C5" — middle character `C` is the disambiguator**: R7 alone = Round 7; R7C5 = Round 7 Cycle 5; R7-PF-INST1 = Round 7 Pattern F Instance 1.

---

## How to add a new code or naming convention

When introducing a new code family during a round:

1. Add an entry to this glossary as part of the round close-out cascade (Section 6 aggregate-doc update of `udm-round-closeout` skill)
2. Update the cross-doc consistency reference in `CLAUDE.md` if the code is project-doc-wide
3. Cite the originating round + D-number in the entry
4. If the new code overloads an existing prefix, add a "Common pitfalls in code reading" entry to disambiguate

---

## Where each code family lives (one-line index)

| Code prefix | Authoritative source |
|---|---|
| D-numbers | `03_DECISIONS.md` |
| R-numbers (risks) | `RISKS.md` |
| B-numbers (backlog) | `BACKLOG.md` |
| P-numbers (polish queue) | `POLISH_QUEUE.md` ← introduced 2026-05-12; cosmetic / readability / status-render / supersession-crumb / stale-date items; distinct from B-numbers |
| CODE_BUILD_STATUS (build-state dashboard) | `CODE_BUILD_STATUS.md` ← introduced 2026-05-12; single-pane view of which CODE artifacts are built / tested / deployed; ⬜ / 🟡 / 🟢 / ✅ / ⚫ legend; per-unit row state transition required at moment of state-flip (NOT batched to round close-out) per `udm-progress-logger` Hard Rule 7 |
| ONE_OFF_SCRIPTS (per-script operational tracker) | `ONE_OFF_SCRIPTS.md` ← canonical destination for Manual × One-time executable artifacts per `udm-execution-classifier` matrix (introduced 2026-05-12); distinct from `phase1/02_configuration.md` § 5.1 (Scheduled-recurring jobs) |
| `udm-progress-logger` (per-completion tracker-discipline skill) | `.claude/skills/udm-progress-logger/SKILL.md` ← introduced 2026-05-12; fills mid-round tracker-drift gap; 5-step checklist + tracker-routing matrix; invoked AFTER any agent / sub-agent / multi-agent team finishes substantive work |
| Round R<N> (Phase 1) | `PHASE_1_DEEP_DIVE_PLAN.md` + `phase1/0<N>_*.md` |
| Reviewer R<N>C<M>-<K> / PF-INST<K> | `_reviewer_effectiveness.md` + `_validation_log.md` |
| Pattern A-F | `MULTI_AGENT_GUIDE.md` |
| SP-N (stored procedures) | `phase1/01_database_schema.md` |
| RB-N (runbooks) | `05_RUNBOOKS.md` |
| Edge case series (M/S/I/N/P/G/D/F/V/T/DP/SI) | `04_EDGE_CASES.md` |
| Phase N | `02_PHASES.md` |
| CLAUDE.md code-level (B-N / E-N / V-N / W-N / OBS-N / SCD2-*) | `CLAUDE.md` (project root) |
| Tier 0-5 (test pyramid) | `06_TESTING.md` |
| Tier α/β/γ/δ (artifact complexity) | `phase1/08_sub_agent_self_improvement.md` § 6.3 |
| Pitfall #1-#12 + 9.a-9.m | `HANDOFF.md` §8 |
| SQL naming standards (D105: Proc/Vw + grandfather clause) | `CLAUDE.md` § SQL Naming Standards + `03_DECISIONS.md` D105 |
| Claude Code security model (D103: 13-layer + `/debi` boundary) | `SECURITY_MODEL.md` (canonical) + `CLAUDE.md` § Claude Code Security Model + `03_DECISIONS.md` D103 |
| Round 8 skill codes 8.A-8.G | `phase1/08_sub_agent_self_improvement.md` + `.claude/skills/udm-*/SKILL.md` |
| Pattern F Trigger A-F (G/H candidates) | `MULTI_AGENT_GUIDE.md` § Pattern F |
| Validation Gate 1-5 | `CHECKS_AND_BALANCES.md` |
| EventType families | `CLAUDE.md` (project root) |

---
## Round 3 build — module public surfaces

Public-API surface of newly-authored Round 3 modules (Wave 0 + Waves 1-2; build cohort 2026-05-13). All module locations under `utils/`, `data_load/`, `cdc/`, `orchestration/`, `observability/` per CLAUDE.md "Structure" section. Each entry: identifier → module path → 1-line purpose. Authoritative source for module-level surfaces.

### Exception classes (per D68 two-tier hierarchy)

| Identifier | Module | Inheritance | Purpose |
|---|---|---|---|
| **PipelineError** | `utils/errors.py` | `Exception` | Root of the canonical two-tier hierarchy; carries `metadata: dict` kwarg for D76 audit-row forwarding |
| **PipelineFatalError** | `utils/errors.py` | `PipelineError` | Non-retryable failures — config / contract / single-source-of-truth violations |
| **PipelineRetryableError** | `utils/errors.py` | `PipelineError` | Retryable failures — transient network / lock / source-side issues |
| **RegistryStatusInvalid / RegistryFileNotFound / RegistryHashMismatch / RegistryInsertConflict / RegistryNotFound** | `utils/errors.py` | Mix of Fatal / Retryable | Parquet registry transition failures (per M3 `data_load/parquet_registry_client.py`) |
| **VaultUnavailable / VaultConfigError** | `utils/errors.py` | Retryable / Fatal | Vault SP-call failures (per M6 `data_load/vault_client.py`); naming-collision-reconciliation with `data_load/_exceptions.py` tracked at B222 |
| **LedgerStepFailed / LedgerStuck / LedgerConfigError** | `utils/errors.py` | Fatal / Retryable / Fatal | IdempotencyLedger failure modes (per M9 `utils/idempotency_ledger.py`) |
| **FilterConfigError** | `utils/errors.py` | Fatal | Sensitive-data-filter config errors (per M14 `observability/sensitive_data_filter.py`) |
| **ParityFatalError** | `utils/errors.py` | Fatal | Cross-server parity check failures |
| **InvalidTrustGate** | `utils/errors.py` | Fatal | Extraction-state trust-gate config error (per M10 `cdc/extraction_state.py`) |

### Module classes

| Identifier | Module | Purpose |
|---|---|---|
| **LedgerStep** | `utils/idempotency_ledger.py` | Context manager for D15 idempotency-step bracket; carries `was_short_circuited` + `prior_result` (the latter is always `None` until B63 lands — see B63 carryover) |
| **SensitiveDataFilter** | `observability/sensitive_data_filter.py` | `logging.Filter` subclass; redacts P5 PII patterns from `record.msg` + `record.args` before emission |
| **CredentialsDict** | `data_load/credentials_loader.py` | TypedDict for credential payload returned by `load_credentials()` |
| **PassphraseSource** | `data_load/credentials_loader.py` | Enum / sentinel for credential passphrase provenance (TPM2 / keyring / env / GPG-cached) |
| **ExtractionState** | `cdc/extraction_state.py` | Per-table extraction-attempt state dataclass |
| **ExtractionPlan** | `orchestration/range_scheduler.py` | Ordered date-list + trust-gate verdict for windowed-CDC per-day processing |
| **SqlServerLogHandler** (v2) | `observability/log_handler.py` | `logging.Handler` subclass; PRESERVES v1 API per drop-in v2 cutover (Wave 2.4 build 2026-05-13); writes to `General.ops.PipelineLog` |
| **ParquetVerifyResult** | `data_load/parquet_registry_client.py` | Result dataclass for `verify_parquet_snapshot()` — registry status + verification outcome |
| **ParquetWriteResult** | `data_load/parquet_writer.py` | Result dataclass for `write_parquet_snapshot()` — final path / SHA-256 / file size / registry id (M1 / Wave 3.2) |
| **ReplayResult** | `data_load/parquet_replay.py` | Result dataclass for `replay_parquet_snapshot()` — registry row / file path / SHA verify outcome / ledger short-circuit flag (M2 / Wave 3.3) |
| **PipelineEvent** (v2-extended) | `observability/event_tracker.py` | v2-extended event dataclass; PRESERVES all v1 attrs (rows_*, status, error_message, metadata, event_detail, table_created); v2 adds `cancellation_requested` flag exposed to caller for D33 cooperative-cancellation handoff (M16 / Wave 3.1) |
| **SnowflakeCopyResult** | `data_load/snowflake_uploader.py` | Result dataclass for `copy_parquet_to_snowflake()` — rows_loaded / copy_history_id / registry_id / status_transition outcome (M17 / Wave 4) |
| **ParityCheck** | `tools/verify_server_parity.py` | Per-check parity dataclass — name / severity / status / message / metadata for D65 severity-tiered RPM / SP / job inventory comparison (M8 / Wave 5.1) |
| **ParityReport** | `tools/verify_server_parity.py` | Aggregate report dataclass — list[ParityCheck] + overall verdict + exit code per D65; consumed by `tools/promote_test_to_prod.py` pre-flight (M8 / Wave 5.1) |
| **LatenessReport** | `cdc/lateness_profiler.py` | Per-table lateness report dataclass — L_50 / L_95 / L_99 quantiles + sample count + table identifier per D11 empirical extraction-window sizing (M12 / Wave 5.2) |
| **GapReport** | `tools/gap_detector.py` | Per-table gap report dataclass — `(expected_range, missing_dates, recommended_action)` interface per canonical spec § 5.3 + D22; consumed by Round 4 § 3.5 `tools/detect_extraction_gaps.py` CLI shim (M13 / Wave 5.3) |

### Module functions

| Identifier | Module | Purpose |
|---|---|---|
| **ledger_step** | `utils/idempotency_ledger.py` | Factory for `LedgerStep` context manager; primary D15 entry point |
| **startup_recovery_sweep** | `utils/idempotency_ledger.py` | Pipeline-startup sweep that resolves stuck IN_PROGRESS rows per D85 stage 4 |
| **register_pii_pattern** | `observability/sensitive_data_filter.py` | Module-import-time pattern registration helper (mutates `SENSITIVE_PATTERNS`) |
| **load_credentials** | `data_load/credentials_loader.py` | Loads `/etc/pipeline/.env` via GPG/TPM2 path (D64 + D71 + D103) |
| **release_snowflake_key / clear_cache** | `data_load/credentials_loader.py` | Cleanup helpers for ephemeral Snowflake RSA key + module-level credential cache |
| **is_date_trusted / most_recent_success / is_reextraction** | `cdc/extraction_state.py` | Read-side predicates for trust-gate + re-extraction detection per D11 / D13 / D14 |
| **get_extraction_attempt / record_extraction_attempt** | `cdc/extraction_state.py` | Per-date extraction-attempt CRUD (INSERT-or-UPDATE state machine) |
| **plan_extraction_range** | `orchestration/range_scheduler.py` | Computes ordered date plan from `FirstLoadDate` + `LookbackDays` + checkpoint state |
| **call_vault_sp** | `data_load/vault_client.py` | Generic SP-call wrapper for PiiVault stored procedures (SP-1/SP-2/SP-10/SP-12) |
| **configure_vault_connection_pool / release_vault_connection_pool** | `data_load/vault_client.py` | Connection-pool lifecycle for vault SP calls |
| **set_log_context / clear_log_context** | `observability/log_handler.py` | v2 context-vars helpers (per D85 startup-stage routing) |
| **mark_replicated / mark_archived / mark_purged / mark_missing / mark_replication_failed** | `data_load/parquet_registry_client.py` | State-machine transitions (created→verified→replicated→archived→purged); 5 of the 6 mutating ops |
| **query_snapshot / is_legal_transition** | `data_load/parquet_registry_client.py` | Read-side + state-machine-validity helpers |
| **write_parquet_snapshot** | `data_load/parquet_writer.py` | Writes Polars DataFrame to canonical Hive-partitioned Parquet path via inflight-rename + computes full SHA-256 + INSERTs `ParquetSnapshotRegistry` row with `Status='created'` (M1 / Wave 3.2) |
| **replay_parquet_snapshot** | `data_load/parquet_replay.py` | Replays a registry-tracked Parquet snapshot back into pipeline state with SHA-256 verify against registry digest + ledger composition for replay idempotency (M2 / Wave 3.3) |
| **tokenize_pii_columns** | `data_load/pii_tokenizer.py` | Per-row PII tokenization via SP-1 `PiiVault_GetOrCreateToken` per column + provenance INSERT + batch-summary audit row (M4 / Wave 3.4) |
| **decrypt_token** | `data_load/pii_decryptor.py` | Operator-justified decrypt via SP-2 `PiiVault_DecryptForOperator` with justification enforcement + audit row (M5 / Wave 3.5) |
| **set_event_context / clear_event_context** | `observability/event_tracker.py` | v2 contextvars helpers parallel to `set_log_context` / `clear_log_context` per M15 layout — set `BatchId` / `TableName` / `SourceName` at pipeline-step boundary so both `PipelineEventLog` and `PipelineLog` rows carry consistent context (M16 / Wave 3.1) |
| **skip** (event_tracker helper) | `observability/event_tracker.py` | OBS-3 short-circuit helper — emit a `TABLE_TOTAL` event with `Status='SKIPPED'` + `EventDetail` reason (lock-blocked tables, cancellation acks etc.); preserved v1 contract (M16 / Wave 3.1) |
| **track** (preserved v1 method) | `observability/event_tracker.py` | Public `PipelineEventTracker.track(event_type, table_config)` context manager — yields a mutable `PipelineEvent` for per-step audit row capture. v1 API preserved unchanged for drop-in v2 cutover (M16 / Wave 3.1) |
| **copy_parquet_to_snowflake** | `data_load/snowflake_uploader.py` | M17 main entry point per spec § 7.1 — mirrors a `Status='verified'` Parquet snapshot from the network drive into Snowflake-managed Iceberg via `COPY INTO`; composes `mark_replicated()` post-COPY for registry `verified → replicated` transition; writes `SNOWFLAKE_COPY_INTO` audit row via M16 v2 (M17 / Wave 4) |
| **verify_server_parity** | `tools/verify_server_parity.py` | M8 main entry point per spec § 3.2 — runs D65 severity-tiered parity checks (FATAL / WARN / INFO) against baseline-vs-live RPM packages + SPs + Automic jobs + .env paths + TPM2 probe; returns ParityReport with exit-code semantics per D65 (M8 / Wave 5.1) |
| **profile_lateness** | `cdc/lateness_profiler.py` | M12 main entry point per spec § 5.2 — reads source `LastModifiedColumn` deltas via SQL query, computes empirical L_50/L_95/L_99 quantiles via `statistics.quantiles()` per D11; returns `LatenessReport`; **read-only** (no DB writes) — pair with `persist_lateness_report()` helper (M12 / Wave 5.2) |
| **persist_lateness_report** | `cdc/lateness_profiler.py` | Separate persister helper writing `LatenessReport` to `General.ops.LatenessProfile` table per D11 — split from `profile_lateness()` to keep the profiler read-only (M12 / Wave 5.2; see B-251 producer/persister split spec clarification) |
| **detect_extraction_gaps** | `tools/gap_detector.py` | M13 main entry point per spec § 5.3 — walks `cdc/extraction_state.py` ledger over expected date range, identifies missing dates, returns `GapReport(expected_range, missing_dates, recommended_action)` per canonical interface + D22; writes GAP_DETECT audit row (M13 / Wave 5.3) |

### Module constants

| Identifier | Module | Purpose |
|---|---|---|
| **REPLAY_ELIGIBLE_STATUSES** | `data_load/parquet_replay.py` | `frozenset({"verified", "replicated", "archived"})` — registry statuses for which replay is permitted; pinned per § 1.2 (replay against `created` / `missing` / `purged` / `replication_failed` is forbidden) (M2 / Wave 3.3) |
| **EVENT_TYPE_REPLAY** | `data_load/parquet_replay.py` | Canonical `IdempotencyLedger.EventType` value (`"REPLAY"`) for replay ledger rows; aligns with `utils/idempotency_ledger.py` § 4.1 canonical-value list; M3 by contrast uses `PARQUET_*` prefix family — harmonization tracked at B-231 |
| **EVENT_TYPE_SNOWFLAKE_COPY_INTO** | `data_load/snowflake_uploader.py` | Canonical `PipelineEventLog.EventType` value (`"SNOWFLAKE_COPY_INTO"`) for M17 audit rows; one row per COPY INTO attempt; M3's `PARQUET_REPLICATE` ledger row is the sibling audit signal per B-241 duality (M17 / Wave 4) |
| **COPY_REQUIRED_STATUS** | `data_load/snowflake_uploader.py` | `"verified"` — registry `Status` precondition for COPY INTO; any other status raises `RegistryStatusInvalid` (M17 / Wave 4) |
| **DEFAULT_COPY_TIMEOUT_SECONDS** | `data_load/snowflake_uploader.py` | `300` — default Snowflake COPY INTO timeout; overridable per-call; timeout exhaustion raises `SnowflakeCopyTimeout` (retryable per D69) (M17 / Wave 4) |
| **DEFAULT_BASELINE_PATH** | `tools/verify_server_parity.py` | Default baseline manifest path resolution per D103 — `/etc/pipeline/baseline_manifest.json`; CLI `--baseline-path` override supported (M8 / Wave 5.1) |
| **WINDOWS_SENTINEL** | `tools/verify_server_parity.py` | Sentinel value for Windows dev workstation parity-check probes that should not be considered FATAL on a non-RHEL host (M8 / Wave 5.1) |
| **PROBE_FAILED_SENTINEL** | `tools/verify_server_parity.py` | Sentinel value for parity-check probes that failed to execute (e.g. TPM2 probe failure on non-TPM2-equipped host); reported as WARN rather than FATAL per D65 severity discipline (M8 / Wave 5.1) |
| **UNAVAILABLE_SENTINEL** | `tools/verify_server_parity.py` | Sentinel value for unavailable probe data (e.g. `rpm -q` returns "not installed"); routed to severity check per D65 tier mapping (M8 / Wave 5.1) |
| **ACTION_BACKFILL** | `tools/gap_detector.py` | Recommended action constant — operator should run `tools/backfill.py` for the missing date range per LT-3 / R-13 (M13 / Wave 5.3) |
| **ACTION_INVESTIGATE** | `tools/gap_detector.py` | Recommended action constant — gap exceeds heuristic auto-backfill threshold OR cross-day discontinuity detected; operator review required (M13 / Wave 5.3) |
| **ACTION_NO_ACTION** | `tools/gap_detector.py` | Recommended action constant — no gaps detected OR gaps within tolerable LookbackDays band; informational only (M13 / Wave 5.3) |


## Owner

Pipeline lead. Glossary is maintained per round close-out (extended whenever a new code family is introduced).

## Last reviewed

2026-05-14 (**Wave 5 cohort + Round 3 17/17 COMPLETE gap-check inline closure** — extended "Round 3 build — module public surfaces" with 4 classes (`ParityCheck` / `ParityReport` / `LatenessReport` / `GapReport`), 4 functions (`verify_server_parity` / `profile_lateness` / `persist_lateness_report` / `detect_extraction_gaps`), 7 constants (`DEFAULT_BASELINE_PATH` / `WINDOWS_SENTINEL` / `PROBE_FAILED_SENTINEL` / `UNAVAILABLE_SENTINEL` / `ACTION_BACKFILL` / `ACTION_INVESTIGATE` / `ACTION_NO_ACTION`) for the 3 Wave 5 modules (M8 verify_server_parity + M12 lateness_profiler + M13 gap_detector); F-4/F-6 BLOCKER (CLAUDE.md "Structure" section M8/M12/M13 absence + no `tools/` section at all) reduced 🔴 → ⚫ via parallel CLAUDE.md extension (new `tools/` subsection authored + lateness_profiler entry added under cdc/). Round 3 build campaign now TRUE 17/17 BUILT 100% ✅ MILESTONE — both task-brief campaign framing AND canonical § 1-7 numbering converged. Earlier 2026-05-13 (**Wave 4 M17 + Round 3 14/17 reality gap-check inline closure**: extended "Round 3 build — module public surfaces" with 1 class (`SnowflakeCopyResult`), 1 function (`copy_parquet_to_snowflake`), 3 constants (`EVENT_TYPE_SNOWFLAKE_COPY_INTO` / `COPY_REQUIRED_STATUS` / `DEFAULT_COPY_TIMEOUT_SECONDS`) for the Wave 4 M17 `data_load/snowflake_uploader.py` module; F-4 BLOCKER (CLAUDE.md "Structure" section M17 absence) reduced 🔴 → ⚫ via parallel CLAUDE.md extension; F-1a/b/c sub-findings (convention-registration drift on M17) reduced 🟡 → ⚫. Earlier 2026-05-13 (**Wave 3 cohort gap-check inline closure**: extended "Round 3 build — module public surfaces" with 3 classes (`ParquetWriteResult` / `ReplayResult` / `PipelineEvent` v2-extended), 8 functions (`write_parquet_snapshot` / `replay_parquet_snapshot` / `tokenize_pii_columns` / `decrypt_token` / `set_event_context` / `clear_event_context` / `skip` event_tracker helper / `track` preserved v1 method), 2 constants (`REPLAY_ELIGIBLE_STATUSES` / `EVENT_TYPE_REPLAY`) for the 5 Wave 3 modules (M16 event_tracker v2 cutover + M1 parquet_writer + M2 parquet_replay + M4 pii_tokenizer + M5 pii_decryptor); F-6 convention-registration gap reduced 🔴 → ⚫ post-fix; new "Module constants" sub-section authored. Earlier 2026-05-13 (**B220 inline closure — cross-tracker registration sweep**: added new "Round 3 build — module public surfaces" section enumerating Wave 0 + Wave 1 + Wave 2 module public APIs (exception classes per D68 two-tier hierarchy + module classes + module functions); extended Pitfall #9 sub-classes table from 9.a-9.j to 9.a-9.m (9.k arithmetic-propagation / 9.l canonical-schema-detail / 9.m discipline-not-applied-to-its-own-tracker) per HANDOFF §8 formalization 2026-05-12; extended Pattern codes table with Pattern B1/B2/B3 build-cohort variants (single-agent / paired / triad); extended "Where each code family lives" table with CODE_BUILD_STATUS / ONE_OFF_SCRIPTS / udm-progress-logger rows; Pitfall family marker updated from "9.a-9.j" to "9.a-9.m". Earlier 2026-05-12 (**Phase 0 user-sign-off batch + R01 de-escalation**: extended D-range to D108 (D106 schedule + D107 dual offsite paths + D108 ops-channel email); extended B-range to B190 (B188/B189/B190 added for Round 4.5b tools; B187 closed via D107; B156 closed via D108). R01 DE-ESCALATED 9 → 6 per ≥10/20 strict-closure threshold trigger. Earlier 2026-05-12: **Phase 0 sweep residuals**: extended B-range to B187; added B185 / B186 / B187 to Recent B-items list (PII inventory data-side / Phase 3-6 deep-dive plans / offsite Parquet target). Earlier 2026-05-11: **Phase 2 plan-draft authored**: extended Round codes section to include 4 proposed Phase 2 rounds (P2R1-P2R4) with `P2R<N>` disambiguation prefix; Phase 1 rounds R1-R8 marked complete. Earlier 2026-05-11: **Phase 0 prep close-out**: extended D-number range to D105; added R32 (Claude credential-access risk); added Pitfall #12 (naming-standard locked late); added two new where-each-code-family-lives index rows for D105 SQL naming standards + D103 Claude Code security model. Earlier 2026-05-11: authored at Round 8 close-out per user-driven onboarding-clarity requirement — Pattern F INSTANCE 2 catch of B155 false-closure surfaced cascade-discipline gap; user observed code density would be opaque to fresh engineers + AI agents and requested human-readable reference; this glossary is the single-source-of-truth response).
