# UDM Documentation Index

> Intent-based routing for agents performing Canonical Context Load (CCL) Stage 0.
> Read the entry that matches your task; skip others. **Routing-by-intent only — NOT a structural map** (per ETH Zurich research §3.6 Finding 5: structural overviews increase agent inference cost +20-23% with success rate -3%).

**Last regenerated**: 2026-05-15

**How to use this index**: each entry follows the pattern `[filename](path) — "task-relevant question this file answers?" Read when: <trigger>. Skip when: <skip condition>.` If you're a fresh agent, start with the CCL Stage 1 reads below. If you have a specific identifier (D-N / B-N / R-N / SP-N / RB-N / Pitfall / Pattern / Tier code) you don't recognize, jump to `GLOSSARY.md` in CCL Stage 3.

**Authored per D.2 Phase 1 task 1.3** (`MARKDOWN_REFACTOR_PLAN.md` §7.1 + §13.2): 3-parallel-agent cohort with sub-agent inheritance contract per CLAUDE.md hard rule 13. Reconnaissance + assembly evidence at `_research/d2-index-md-reconnaissance-2026-05-15.md`.

---

## CCL Stage 1 reads (every agent invocation; mandatory)

- [CURRENT_STATE.md](CURRENT_STATE.md) — **"Where is the project RIGHT NOW?"** Read first if you're a fresh agent — captures the active phase / round, in-flight cycle state, and pending acceptance items. Skip when: you already have today's L7 narrative in context from this session AND no round-state-changing event has fired since you last loaded it.
- [HANDOFF.md](HANDOFF.md) — **"What context do I need to take over mid-flight?"** Read on every fresh-agent invocation — codifies the mission, the 9-doc read order, and the Pitfall #N + Pattern A-F discipline scaffolding. Skip when: you're a sub-agent whose parent already loaded HANDOFF this session (per `udm-planning-session-startup` inheritance contract).
- [NORTH_STAR.md](NORTH_STAR.md) — **"When two design paths diverge, which one wins?"** Read when: making any architectural trade-off, locking a D-number, or evaluating whether a deliverable advances the 5 pillars (Audit-grade / Traceability / Idempotent / Operationally stable / $120K ceiling). Cite the served pillar(s) in every new D-number per D61.
- [CHECKS_AND_BALANCES.md](CHECKS_AND_BALANCES.md) — **"How do I prove an artifact is actually done, not just produced?"** Read before: flipping any 🟡 → 🟢, signing off a cycle, or merging schema/runbook/SP changes. Defines the 5-gate validation discipline (cross-ref / QA / edge cases / edge-case validation / idempotency-regression) per D55 + D56. Non-negotiable precondition for status flips.

## CCL Stage 2 reads (risk + backlog awareness; mandatory)

- [RISKS.md](RISKS.md) — **"What active delivery risks should shape my decisions?"** Read when: scoping a new round, locking a decision (cite risk-delta per D61), or proposing a deliverable. R01-R32 are scored Likelihood × Impact; quarterly review per `MAINTENANCE.md`. Distinct from `04_EDGE_CASES.md` (technical-correctness in production).
- [BACKLOG.md](BACKLOG.md) — **"Is this work already tracked, or do I need a new B-number?"** Read when: surfacing a 🟡 follow-up from validation, closing-in-cycle a deferred item, or computing NEXT_AVAILABLE B-number before adding an item. WSJF-prioritized (COD ÷ JS); status-render rule — inline `**CLOSED YYYY-MM-DD**` annotation is canonical, leading badge may lag (Pitfall #9.j).
- [_validation_log.md](_validation_log.md) — **"What was the validation verdict + bug-catch evidence for this artifact?"** Read when: investigating a 🔴 finding's resolution trail, auditing a 🟢 lock for evidence backing, or appending a new validation event. Append-only audit trail per D55; archive cycle triggers at ~2000 lines OR 90-day entry age (next candidate cycle at Phase 2 R1 close-out per B-272).

## CCL Stage 3 reads (task-specific reference; on-demand)

- [GLOSSARY.md](GLOSSARY.md) — **"What does this code/acronym mean?"** Read when: you encounter an unfamiliar short-form identifier (`D93`, `R28`, `B144`, `SP-4`, `RB-10`, `Pattern F`, `Tier δ`, `Pitfall #9.j`, `M-series`, `WSJF`, etc.) and don't recognize it. Skip when: working only with familiar identifiers. The dictionary you keep open in another tab — every code family is enumerated in the quick-reference table at the top.
- [MULTI_AGENT_GUIDE.md](MULTI_AGENT_GUIDE.md) — **"How do I coordinate multiple agents on this task?"** Read when: spawning subagents, designing a Pattern A/B/C/D/E/F multi-agent cohort, or operationalizing CCL Stage 1+2 procedure per D62. Skip when: working as a single-agent task with no review-pair or cohort. Canonical reference for paired-judgment + Pattern F (D89-D91 cascade audit).
- [PLANNING_DISCIPLINE.md](PLANNING_DISCIPLINE.md) — **"Which skills must I invoke for THIS type of planning session, and how do sub-agents inherit them?"** Read when: starting a planning session of ANY kind (architectural / doc-refactor / new-tool / new-SP / new-runbook / multi-agent cohort / round close-out / D-N-introducing / self-improvement) per CLAUDE.md hard rule 13. Skip when: executing tactical edits inside an already-planned scope. Canonical home for the skill-selection matrix + sub-agent inheritance contract.
- [CLAUDE_GOTCHAS.md](CLAUDE_GOTCHAS.md) — **"What pipeline-code edge case am I about to step on?"** Read when: touching CDC, SCD2, BCP CSV, hashing, schema evolution, or large-table windowed processing AND you encounter a `B-N` / `E-N` / `V-N` / `W-N` / `OBS-N` / `SCD2-*` / `LT-*` / `DIAG-*` / `Item-*` reference in CLAUDE.md you need to understand. Skip when: working on planning/process artifacts (no pipeline code). Extracted from CLAUDE.md Gotchas section per D.5 Approach A trim 2026-05-15.

## Canonical registers (read when task references this register)

- [03_DECISIONS.md](03_DECISIONS.md) — **"What's the canonical wording / status / rationale of decision D-N?"** Search by D-number on-demand (never read top-to-bottom). Status legend: 🟢 Locked / 🟡 Proposed / 🔴 Deferred / ⚫ Superseded. Forward-only per D92 — supersession via new D-number with `superseded by` chain, never in-place rewrite of the old body.
- [04_EDGE_CASES.md](04_EDGE_CASES.md) — **"Does this design address edge case <X> in series M/S/I/N/P/G/D/F/V/T/DP/SI/SE?"** Read when: signing off a round, reviewing pipeline code, or invoking `udm-edge-case-validator`. **13 canonical series total** (Math / SCD2 / Idempotency / Network-Parquet / PII / Gap-detection / 2x-day / Failover / Vault / Testing / Deployment-pipeline / Self-improvement / **Source-exactness — Phase A**). Status: ✅ Mitigated / 🟡 Planned / 🔴 Open.
- [05_RUNBOOKS.md](05_RUNBOOKS.md) — **"What's the procedure for operational task RB-N?"** Read when: operating the pipeline, scripting an automated procedure, or authoring a new runbook (via `udm-runbook-author`). Each runbook self-contained with When → Pre-flight → Procedure → Validation → Rollback sections. RB-1 through RB-14 currently catalogued.
- [POLISH_QUEUE.md](POLISH_QUEUE.md) — **"Is this issue cosmetic (P-number) or substantive (B-number)?"** Read when: surfacing render-discipline drift, status-badge mismatches, or stale-date crumbs. P-numbers track items that don't change behavior, idempotency, ops surface, or cost — distinct from B-numbers. Distinguishing test: does fixing it change a decision body / runbook procedure / SP body / tool spec / pipeline code? YES → B-number; NO → P-number.
- [ONE_OFF_SCRIPTS.md](ONE_OFF_SCRIPTS.md) — **"Is this script run-once (operator-aware) or recurring (Automic-scheduled)?"** Read when: authoring an executable artifact (per `udm-execution-classifier`), or as an operator before running a migration / spike / per-CSV-import script. Per-script status tracker (🟡 Pending / 🟢 Build complete pending deployment / ✅ Run / ⚫ Archived). Scheduled-recurring tools belong in `phase1/02_configuration.md` § 5.1 frozen-N Automic inventory, NOT here.

## Architecture + phase status

- [00_OVERVIEW.md](00_OVERVIEW.md) — **"What is this project building, and where does the work currently stand?"** Read when: onboarding to the project, scoping a new round / phase, or summarizing status for stakeholders. Skip when: making a tactical edit to an already-locked artifact.
- [01_ARCHITECTURE.md](01_ARCHITECTURE.md) — **"What are the components, how do they connect, and what writes to which metadata table?"** Read when: proposing a new module, changing inter-component contracts, or reviewing how Parquet / Bronze / Snowflake fit together. Skip for cosmetic / tracker-only edits.
- [02_PHASES.md](02_PHASES.md) — **"Which phase / round am I in, what's its acceptance gate, and what other rounds depend on it?"** Read when: planning a new round, starting close-out, or asked "is X done?" Skip when: working entirely inside a single already-active round (use its `phase1/0N_*.md` doc instead).
- [06_TESTING.md](06_TESTING.md) — **"Which test tier does this assertion belong in, and what's the runtime budget?"** Read when: authoring tests, deciding Tier 0 vs Tier 1 placement, or scheduling Tier 5 quarterly drill (Q1-Q10). Pairs with `phase1/05_tests.md` for spec-level details.
- [07_LOGGING.md](07_LOGGING.md) — **"Should this be a PipelineEventLog row, a PipelineLog row, or both? Which level?"** Read when: adding an `EventType`, instrumenting a new code path, or designing a Power BI query against the observability tables. Cross-references CLAUDE.md OBS-1 through OBS-7.
- [09_VISUALS.md](09_VISUALS.md) — **"What does the snapshot-vs-CDC / end-to-end / SCD2 chain look like as a diagram?"** Read when: explaining the pipeline to a new engineer, drafting architecture-doc updates, or resolving a misunderstanding about CDC-append vs snapshot semantics. Mermaid-source; renders on GitHub.
- [SECURITY_MODEL.md](SECURITY_MODEL.md) — **"Where can Claude Code read? Where can it NOT?"** Read when: proposing any change that touches credentials, `.env`, AI-tool permissions, or `.claude/settings.local.json` per D103. Skip for pure tracker / cosmetic edits.
- [CODE_BUILD_STATUS.md](CODE_BUILD_STATUS.md) — **"Is this artifact specified, built, tested, or deployed — and what's blocking it?"** Read when: starting a code-build agent task (prevents duplicate work), flipping a status badge, or auditing aggregate progress at round close-out. Hard rule per CLAUDE.md §10: no 🟢 status flip without a corresponding per-unit row transition here.

## Process meta-docs (read when authoring process artifacts)

- [MAINTENANCE.md](MAINTENANCE.md) — **"Who owns this doc, on what cadence, and what's the update workflow?"** Read when: scheduling a quarterly doc review, escalating stale 🟡 items, or onboarding a new doc-owner. Skip during in-round substantive work.
- [OBSIDIAN_GUIDE.md](OBSIDIAN_GUIDE.md) — **"How do I get the docs/migration/ corpus to work well in Obsidian?"** Read when: setting up Obsidian as a navigation layer over the existing markdown, evaluating wiki-link conversion trade-offs, or installing the Smart Connections / Dataview plugins. Optional / additive — skip unless using Obsidian.
- [NEW_REPO_STARTER_TEMPLATE.md](NEW_REPO_STARTER_TEMPLATE.md) — **"What does an agent-friendly docs/ layout look like from day 1 for a greenfield repo?"** Read when: bootstrapping a new project's documentation, evaluating the 8 design principles distilled from this project's retrofit. Companion to `MARKDOWN_REFACTOR_PLAN.md` §16.2. Skip when working in this (UDM) repo.
- [MARKDOWN_REFACTOR_PLAN.md](MARKDOWN_REFACTOR_PLAN.md) — **"What's the canonical plan for the markdown refactor effort, and which D-Phase am I executing?"** Read when: authoring or executing any task within the refactor (D.0 through D.7 phases), checking open Q-N pipeline-lead questions, or verifying empirical findings (em-dash slug / CCL token cost). 🟢 LOCKED 2026-05-15.
- [SELF_IMPROVEMENT_DISCIPLINE.md](SELF_IMPROVEMENT_DISCIPLINE.md) — **"How does the validation system tune itself round-over-round?"** Read when: invoking any 8.A-8.G self-improvement skill at round close-out, reviewing proposed prompt deltas, or designing new meta-discipline. Constitutional doctrine for D95-D99.

## Active plans

- [PHASE_1_DEEP_DIVE_PLAN.md](PHASE_1_DEEP_DIVE_PLAN.md) — **"What are the eight Phase 1 rounds, in what order, and what's the per-round artifact list?"** Read when: planning a new Phase 1 round, scoping artifact-level work within an active round, or verifying round dependencies. Phase 1 rounds are now 🟢 Locked; doc remains canonical for round-structure reference.
- [PHASE_1_TESTING_BLUEPRINT.md](PHASE_1_TESTING_BLUEPRINT.md) — **"What's the step-by-step operator validation sequence from PR creation through production-bug root-cause?"** Read when: running hands-on testing of Phase 1 deliverables on your own environment, debugging a Phase 2 production-bug repair, or saving diagnostic output for chat analysis. 5-phase operator-facing procedure; expected runtime 30-60 minutes.
- [ROUND_1_REVIEW.md](ROUND_1_REVIEW.md) — **"What did Round 1 retrospective surface as critical bugs, gaps, and over-specification risk?"** Read when: studying the project's earliest critical-review pattern, learning the over-specification anti-pattern, or referencing the 8 original Round 1 findings (SP-1 concurrency, partition rollover time-bomb, etc.). Historical — most findings now closed; read for retrospective context.

## Phase-specific deep dives (read when task is in scope of specific phase/round)

### Phase 1 — Foundation Infrastructure

- [phase1/00_phase_overview.md](phase1/00_phase_overview.md) — **"What is Phase 1 building and why?"** Read first when entering ANY Phase 1 round. Skip when working on Phase 2+ or non-phase artifacts. Phase 1 ends when smoke-test pipeline runs end-to-end on dev.

**Round 1 — Database Schema (1 main + 5 supplements)**

- [phase1/01_database_schema.md](phase1/01_database_schema.md) — **"What tables/indexes/SPs exist in `General.ops`?"** Read when: authoring DDL, referencing a `General.ops.*` table/SP, or scoping schema evolution. Skip when: no schema touch. Canonical home for 23 tables + 1 sequence object + all stored procedures.
- [phase1/01a_control_tables.md](phase1/01a_control_tables.md) — **"How does the pipeline KNOW what to extract?"** Read when: working with `UdmTablesList` / `UdmTablesColumnsList` / `UdmScd2ConfigProposal` trigger tier. Skip when: working only with Bronze/Stage data tables.
- [phase1/01b_bronze_stage_example_ddl.md](phase1/01b_bronze_stage_example_ddl.md) — **"What does the CDC/SCD2 DDL `schema/table_creator.py` produces actually look like?"** Read when: debugging table-creation output OR writing DDL by hand for a new source. Concrete DNA.osibank.ACCT example.
- [phase1/01c_data_flow_walkthrough.md](phase1/01c_data_flow_walkthrough.md) — **"What writes happen to which tables, when, in what order?"** Read when: authoring dashboards OR tracing which `General.ops.*` table to query for a specific event. Per-cycle observability trace.
- [phase1/01d_consumer_query_patterns.md](phase1/01d_consumer_query_patterns.md) — **"How do downstream consumers safely query Bronze SCD2 tables?"** Read when: writing analyst SQL against Bronze (the V-4 defensive `ROW_NUMBER()` pattern lives here). Skip when: pipeline-internal queries only.

**Round 2 — Configuration**

- [phase1/02_configuration.md](phase1/02_configuration.md) — **"What `.env` keys / `UdmTablesList` columns / Automic jobs are part of the spec?"** Read when: adding a config column, an `.env` key, a credential, or an Automic job. Canonical home for cross-server parity baseline + frozen-N Automic inventory (§ 5.1).

**Round 3 — Core Modules (1 main + 1 spike companion)**

- [phase1/03_core_modules.md](phase1/03_core_modules.md) — **"What is the canonical module signature / public surface for Round 3 modules M1-M17?"** Read when: building, modifying, OR testing any core module (`idempotency_ledger`, `parquet_*`, `vault_client`, `credentials_loader`, `extraction_state`, `lateness_profiler`, `range_scheduler`, etc.) — per Step 11 wave-spawn discipline, cite the canonical spec signature verbatim.
- [phase1/03_round_0_5_spike_plan.md](phase1/03_round_0_5_spike_plan.md) — **"What integration spike must run BEFORE Round 1+ locks?"** Read when: scoping or executing Round 0.5 pre-locking validation (3 unvalidated integrations). Skip when: post-spike work in Rounds 1-8.

**Round 4 — Tools (1 main + 2 supplements)**

- [phase1/04_tools.md](phase1/04_tools.md) — **"What is the CLI signature / exit codes / Tier 0 sketch for operator tools 1-11?"** Read when: building or modifying any `tools/*.py` CLI. D74 exit-code contract + D75 dry-run default + D76 audit row discipline.
- [phase1/04a_phase_0_prep_tools.md](phase1/04a_phase_0_prep_tools.md) — **"What are Tools 12-13 (verify_credentials_load / capture_parity_baseline)?"** Read when: building tools that closed B183/B184 prep gaps for Phase 2 R1. Round 4.5 additive supplement per D100.
- [phase1/04b_phase_0_closure_tools.md](phase1/04b_phase_0_closure_tools.md) — **"What are Tools 14-16 (measure_lateness / import_pii_inventory / measure_capacity_and_partition)?"** Read when: closing Phase 0 deliverables 0.2 / 0.3 / 0.5 / 0.17. Round 4.5b additive supplement per D100.

**Round 5 — Tests**

- [phase1/05_tests.md](phase1/05_tests.md) — **"What is the Tier 0-5 test plan for module M-N or tool T-N?"** Read when: authoring tests OR debugging test discovery (Tier 0 fast-feedback / Tier 1 unit / Tier 2 property / Tier 3 integration / Tier 4 crash / Tier 5 quarterly). Authored test-first; consumed by Round 6 implementation.

**Round 6 — Deployment**

- [phase1/06_deployment.md](phase1/06_deployment.md) — **"How does code land in dev/test/prod, in what order, with what gates?"** Read when: building/modifying deployment scripts OR operationalizing the module startup sequence (Stage 1 creds → Stage 2 vault pool → Stage 3 parity → Stage 4 ledger sweep → Stage 5 orchestration). D87 3-env cadence canonical home.

**Round 7 — Schema Evolution Governance (1 main + 1 supplement)**

- [phase1/07_schema_evolution_governance.md](phase1/07_schema_evolution_governance.md) — **"How do locked Round 1 artifacts evolve post-lock without breaking dependents?"** Read when: changing an SP signature, adding an Automic job, or amending the frozen-N inventory. SP-4/SP-10/SP-12 evolution patterns + SchemaContract chain discipline (D40 + D92 forward-only).
- [phase1/07a_schema_contract_examples.md](phase1/07a_schema_contract_examples.md) — **"What does a SchemaContract row look like concretely?"** Read when: authoring a SchemaContract row for a new SP signature evolution or column addition. 3 example clusters (source contracts / Round 7 SP evolutions / SupersededBy chain).

**Round 8 — Sub-Agent Self-Improvement Discipline**

- [phase1/08_sub_agent_self_improvement.md](phase1/08_sub_agent_self_improvement.md) — **"How do skills + agent prompts evolve at round close-out without unbounded drift?"** Read when: invoking any of the 7 self-improvement skills (`udm-retrospective-collector` / `udm-specialty-tuner` / `udm-subclass-accumulator` / `udm-producer-checklist-evolver` / `udm-cycle-cadence-optimizer` / `udm-cascade-audit-evolver` / `udm-agent-prompt-versioner`). Canonical home for D95-D99 self-improvement cascade + SI-series edge cases.

### Phase 2 — Pilot Table Cutover

- [phase2/00_phase_overview.md](phase2/00_phase_overview.md) — **"What is Phase 2 piloting and what is the exit criterion?"** Read first when entering ANY Phase 2 round. Pilot table is `DNA.osibank.ACCT` (1.2M rows per D104); exit = 14 consecutive days zero-intervention bit-for-bit parity with legacy pipeline.
- [phase2/01_pilot_prerequisites.md](phase2/01_pilot_prerequisites.md) — **"What MUST be deployed/verified before Phase 2 R1 cutover can begin?"** Read when: working on R1 prerequisites or executing pre-flight gate. Canonical home for R1 spec; B197/B200 carryovers tracked here.
- [phase2/01a_execution_order.md](phase2/01a_execution_order.md) — **"In what order do R1 sub-steps R1a / R1b / R1c execute?"** Read when: orchestrating the R1 execution sequence. Operational companion to `phase2/01_pilot_prerequisites.md`; light-touch (no Pattern E).

## Validation trail + Sidecars + Subdirectories

- [_validation_log.md](_validation_log.md) — **"What is the canonical audit trail of every 5-gate validation event?"** Append-only — write when: any `udm-checks-and-balances` invocation, B-item closure, decision lock, fix-cycle landing (per `udm-progress-logger` hard rule). Read when: reconstructing what happened in a prior round OR verifying a "produce → validate → record → lock" sequence. Eventual archive when entries age per Phase D.1.
- [_research/](_research/) — **"Has anyone already researched this question?"** Browse when: a question feels novel — check here first to avoid duplicate research. Subdir of ~20+ cumulative artifacts (reconnaissance docs, baseline computations, ad-hoc explorations) accumulated since 2026-05-09. Includes the D.2 prep doc `d2-index-md-reconnaissance-2026-05-15.md` that grounded this INDEX.md authoring.
- [_reviewer_effectiveness.md](_reviewer_effectiveness.md) — **"Which reviewer specialty catches which bug class, with what false-clean rate?"** Read when: running `udm-specialty-tuner` / `udm-producer-checklist-evolver` at round close-out OR choosing a reviewer for a specific Pattern E cohort. Append-only ledger per `udm-retrospective-collector` discipline; trend evidence for D95-D97 self-improvement.
- [_agent_evolution/](_agent_evolution/) — **"What has changed in agent X's prompt across rounds?"** Read when: invoking an agent and wanting to see its semver delta history per D98. Per-agent changelog files (`<agent-name>-changelog.md`) maintained by `udm-agent-prompt-versioner`.
- [_archive/](_archive/) — **"Where do verbatim-archived refactor sections live for recovery without git archaeology?"** Read when: investigating what content was trimmed/extracted from an active file, or recovering pre-trim content for a non-git-savvy operator. Contains: 4 verbatim sections extracted from CLAUDE.md per D.5 Approach A trim 2026-05-15 (Data Flow / Architecture Decisions / Observability detail / Security Model summary) per user-direction "Archive EVERYTHING verbatim (belt-and-suspenders)" Option B. Provenance header at top of each archive file cites source line range + commit + cross-ref destination. Skip when: working with current active content (INDEX.md routes to canonical destinations, NOT archives).
- [_refactor_log.md](_refactor_log.md) — **"What was the audit trail of refactor event X (trim / split / extract / rename / relocate)?"** Read when: investigating refactor history, recovering pre-refactor state, or authoring a new refactor (binding contract at log's §"Future-trim contract"). Append-only per `udm-progress-logger` discipline. Distinct from `_validation_log.md` (5-gate validation events) and `BACKLOG.md` (work-item register).
- [audit_reports/](audit_reports/) — **"Where do Tier 5 quarterly audits land?"** Read when: running quarterly audit OR reviewing prior audit output. Templates at `_TEMPLATE_quarterly.md` + `_TEMPLATE_q10_weekly.md` are the canonical scaffolds.
- [blindspots/](blindspots/) — **"What drift patterns does the executable ledger catch, and how do I query it?"** Read when: invoking `tools/query_blindspots.py` for pre-commit / post-build / cascade-step-2 scanning OR adding a new Pitfall #9 sub-class entry. Contains `ledger.yml` (15 entries for Pitfall #9.a-9.o; queryable form of HANDOFF §8 prose; schema: id / class / severity / agents / tags / symptom / detection_rule / remediation / evidence_base / handoff_anchor) + `protocol.md` (query protocol + CLI usage + how to add entries + self-test discipline). Source: AppLaunchpad agentic-architecture.md §12 Layer 3 blindspot-ledger pattern (high-ROI subset adoption per D-N 2026-05-16). Companion: `tools/query_blindspots.py` CLI scanner + `.claude/hooks/auto-verify-step-10.py` PostToolUse auto-invocation.
