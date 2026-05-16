# Phase D.2 prep — INDEX.md authoring reconnaissance

**Date**: 2026-05-15
**Phase**: D.2 reconnaissance for INDEX.md authoring per MARKDOWN_REFACTOR_PLAN.md §7.1 task 1.3 + §13.2 + §18 phase breakdown
**Trigger**: User-direction Option A choice for B-273 → D.2 → D.3 → D.4 path; B-273 F9.1 one-directional relaxation just landed (this commit) unblocks D.2 standalone
**Sub-agent inheritance**: parent-agent solo reconnaissance this turn; multi-agent cohort plan for D.2 EXECUTION surfaced below for user approval
**Skill activation per `udm-planning-session-startup` v0.2**: PS-2 DOC (primary) + PS-6 COHORT (planned execution); minimum-viable-set = `udm-checks-and-balances` + `udm-progress-logger` + `udm-gap-check` + `udm-step-10-verifier` + `superpowers-verification-before-completion` (always-mandatory; this is the FIRST production use of the just-imported skill)
**Outcome**: 🟢 INDEX.md structure proposed + file inventory categorized + multi-agent cohort plan + multi-agent vs single-agent recommendation — pipeline-lead choice required before spawn

---

## §1. Current `docs/migration/` file inventory (**36 files** in `docs/migration/*.md` + **17 files** in `phase1/*.md` + **3+ files** in `phase2/*.md` + subdirs; verified via `ls | wc -l` 2026-05-15 per `superpowers-verification-before-completion` discipline first production use; initial draft said "~30 + 15" which was Pitfall #9.k stale-snapshot arithmetic drift caught + fixed pre-commit)

Survey via `ls docs/migration/*.md` + `ls docs/migration/phase1/*.md` + `ls docs/migration/phase2/*.md`:

### Category A — Always-load (CCL Stage 1; 4 files per D62)
- `CURRENT_STATE.md` — "Where is the project right now?"
- `HANDOFF.md` — "How do I pick up this project mid-flight?"
- `NORTH_STAR.md` — pillar conflict-resolution rubric (per D61)
- `CHECKS_AND_BALANCES.md` — 5-gate validation framework (per D55)

### Category B — Stage 2 risk/backlog awareness (3 files per D62)
- `RISKS.md` — active delivery risks register
- `BACKLOG.md` — B-N register (open + closed)
- `_validation_log.md` — append-only audit trail

### Category C — Reference lookup (loaded on demand; 4 files)
- `GLOSSARY.md` — code/acronym index (D-N / B-N / R-N / SP-N / RB-N / Pattern / Tier codes)
- `MULTI_AGENT_GUIDE.md` — Pattern A-F multi-agent doctrine + CCL Stage 1+2 procedure
- `PLANNING_DISCIPLINE.md` — skill-selection matrix + sub-agent inheritance (per hard rule 13)
- `CLAUDE_GOTCHAS.md` — B-N / E-N / V-N / W-N / OBS-N / SCD2-* / LT-* / DIAG-* code-level reference (extracted per D.5 Approach A trim)

### Category D — Canonical-home registers (4 files)
- `03_DECISIONS.md` — D-number register (currently ~3,200 lines)
- `04_EDGE_CASES.md` — M/S/I/N/P/G/D/F/V/T/DP/SI series
- `05_RUNBOOKS.md` — operational runbook register (RB-N)
- `POLISH_QUEUE.md` — cosmetic-tracker P-N register (per D113)
- `ONE_OFF_SCRIPTS.md` — per-script operational tracker

### Category E — Architecture / phase reference (8 files)
- `00_OVERVIEW.md` — project scope + architecture pillars
- `01_ARCHITECTURE.md` — system architecture diagrams + component model
- `02_PHASES.md` — phase / round status register
- `06_TESTING.md` — Tier 0-5 test pyramid + Q-quarterly audit cadence
- `07_LOGGING.md` — PipelineLog + PipelineEventLog observability model
- `09_VISUALS.md` — diagrams + visual reference
- `SECURITY_MODEL.md` — Claude Code 13-layer security model (per D103)
- `CODE_BUILD_STATUS.md` — code-build status dashboard

### Category F — Process meta-docs (5 files)
- `MAINTENANCE.md` — periodic maintenance procedures
- `OBSIDIAN_GUIDE.md` — Obsidian-style markdown conventions
- `NEW_REPO_STARTER_TEMPLATE.md` — greenfield repo template
- `MARKDOWN_REFACTOR_PLAN.md` — this work's canonical plan
- `SELF_IMPROVEMENT_DISCIPLINE.md` — Round 8 self-improvement family doctrine (D95-D99)

### Category G — Plans (phase-specific + cross-phase; 3 files)
- `PHASE_1_DEEP_DIVE_PLAN.md` — Phase 1 6-round breakdown
- `PHASE_1_TESTING_BLUEPRINT.md` — 5-phase operator validation sequence
- `ROUND_1_REVIEW.md` — Round 1 retrospective

### Category H — Phase-specific (phase1/* — 15 files; phase2/* — 3 files)
- phase1: 00_phase_overview.md, 01_database_schema.md (+ 01a/01b/01c/01d sub-files), 02_configuration.md, 03_core_modules.md (+ 03_round_0_5_spike_plan.md), 04_tools.md (+ 04a/04b sub-files), 05_tests.md, 06_deployment.md, 07_schema_evolution_governance.md, 08_sub_agent_self_improvement.md
- phase2: 00_phase_overview.md, 01_pilot_prerequisites.md, 01a_execution_order.md

### Category I — Subdirectories (research + reviewer-effectiveness)
- `_research/` — ~15-20 research artifacts accumulated this session + prior
- `_reviewer_effectiveness.md` — reviewer-effectiveness ledger
- `_agent_evolution/` — semver changelogs per agent prompt
- `_archive/` — archived old content
- `audit_reports/` — Tier 5 quarterly audit destination

**Aggregate**: ~50 files; ~120K-150K lines total per measure_ccl_overhead.py baseline.

---

## §2. Proposed INDEX.md structure (per MARKDOWN_REFACTOR_PLAN.md §13.2 + research)

Per llms.txt format (validated by §3.6 Finding 4):
- H1 project name
- Blockquote summary
- Sections with linked files + routing-by-intent descriptions (NOT structural)
- `last_regenerated_at` line at top per gap §10b.2 EC-MR2

**Proposed sections (matching Category A-H above)**:

```markdown
# UDM Documentation Index

> Intent-based routing for agents performing Canonical Context Load (CCL) Stage 0.
> Read the entry that matches your task; skip others. Routing-by-intent only — NOT a structural map.

**Last regenerated**: YYYY-MM-DD HH:MM

## CCL Stage 1 reads (every agent invocation; mandatory)
[Category A entries with routing-by-intent]

## CCL Stage 2 reads (risk + backlog awareness; mandatory)
[Category B entries]

## CCL Stage 3 reads (task-specific; on-demand)
[Category C reference lookups]

## Canonical registers (read when task references this register)
[Category D — 03_DECISIONS / 04_EDGE_CASES / 05_RUNBOOKS / POLISH_QUEUE / ONE_OFF_SCRIPTS]

## Architecture + phase status
[Category E entries]

## Process meta-docs (read when authoring process artifacts)
[Category F entries]

## Active plans
[Category G entries]

## Phase-specific deep dives (read when task is in scope of specific phase/round)
[Category H entries; phase1/ + phase2/ subdirs]

## Validation trail (live + archive)
[_validation_log.md (live) + any future _validation_log_archive_*.md]

## Sidecars + extracted references
[CLAUDE_GOTCHAS.md + future sidecars per D.5 trim pattern]
```

**Estimated total INDEX.md size**: ~280-350 lines (under 500-line research-recommended cap per SKILL.md convention).

---

## §3. Routing-by-intent example entries (drafted; full INDEX would have ~30-50 entries)

Per ETH Zurich research §3.6 Finding 5: structural overviews increase agent inference cost +20-23% with success rate -3%. Avoid "this file contains sections A/B/C". Use "if your task involves X, read this; if Y, skip and read Z" format.

```markdown
## CCL Stage 1 reads (every agent invocation; mandatory)

- [CURRENT_STATE.md](CURRENT_STATE.md) — **"What's the project state RIGHT NOW?"** Read first if you're a fresh agent. Contains: most-recent narrative event prepended to L7 with backfill chain; round status; runway items. **Skip** if you already have CURRENT_STATE.md L7 in context from earlier this session.
- [HANDOFF.md](HANDOFF.md) — **"How do I pick up this project mid-flight?"** Read second; §14 narrative mirror of CURRENT_STATE L7; §8 Pitfall #9 sub-class accumulator (9.a-9.n + emerging 9.o); §3 in-flight bullets for round-history.
- [NORTH_STAR.md](NORTH_STAR.md) — **"Which pillar wins when goals conflict?"** Read when proposing design alternatives that hit multiple pillars (per D61 conflict-resolution). Skip for tactical fixes.
- [CHECKS_AND_BALANCES.md](CHECKS_AND_BALANCES.md) — **"What gates apply before this artifact can lock?"** Read when authoring any artifact subject to D55 5-gate validation. Skip for cosmetic / tracker-only edits.

## Canonical registers (read when task references this register)

- [03_DECISIONS.md](03_DECISIONS.md) — **"What was decided about X, and why?"** Read when task references a D-number (e.g., D55, D62, D103). Grep `^## D<N>` to locate specific decision. **Note**: ~3,200 lines; future Phase 2 may split per MARKDOWN_REFACTOR_PLAN §13.1 if line count crosses threshold.
- [04_EDGE_CASES.md](04_EDGE_CASES.md) — **"Does this design address documented edge cases?"** Read when validating per D55 Gate 3 (edge case validation). Series: M/S/I/N/P/G/D/F/V (Rounds 1-5) + DP (Round 6 deployment) + T (Round 5/6 testing) + SI (Round 8 self-improvement).
- [05_RUNBOOKS.md](05_RUNBOOKS.md) — **"How do I execute operational procedure X?"** Read when task involves a runbook (RB-N). Structure: When → Pre-flight → Procedure → Validation → Rollback per `udm-runbook-author` skill.
- [BACKLOG.md](BACKLOG.md) — **"Is this work item tracked? What's its WSJF?"** Read when scoping new work to check for existing B-N. Grep `B-<N>` to locate.

## Process meta-docs (read when authoring process artifacts)

- [PLANNING_DISCIPLINE.md](PLANNING_DISCIPLINE.md) — **"Which skills should I invoke for THIS planning session?"** Read at START of any planning session (per CLAUDE.md hard rule 13). Contains: 9 PS-N scope categories + skill-selection matrix + sub-agent inheritance contract + §0 provenance template.
- [MULTI_AGENT_GUIDE.md](MULTI_AGENT_GUIDE.md) — **"How do I structure a multi-agent cohort? What's Pattern E/F?"** Read when planning parallel agent work or round close-out cascade.
- [SECURITY_MODEL.md](SECURITY_MODEL.md) — **"Where can Claude Code read? Where can it NOT?"** Read when proposing any change that touches credentials, `.env`, or AI-tool permissions (per D103).
```

---

## §4. Multi-agent cohort plan (PS-6 COHORT scope)

### §4.1 Cohort vs single-agent decision

Total INDEX.md work: ~280-350 lines + ~30-50 routing entries.

| Approach | Pros | Cons |
|---|---|---|
| **A. Single-agent (parent solo)** | Simpler; lower coordination overhead; no inheritance-contract complexity | Slower; misses opportunity to validate B-280 + inheritance-contract disciplines in production cohort |
| **B. 3-agent parallel cohort** (Recommended for discipline-proving) | Faster (3× parallel); validates inheritance contract for 4th time; produces empirical evidence for `_research/planning-discipline-industry-standards-2026-05-15.md` §"What This Research Does NOT Cover" gap | More coordination; ~30-min cohort spawn overhead; risk of overlapping content if agents don't have crisp section boundaries |

### §4.2 Recommended cohort design (Option B)

3 parallel sub-agents (general-purpose; each receives inheritance contract per CLAUDE.md hard rule 13):

| Agent | Scope | Sections to author | Expected output |
|---|---|---|---|
| **Agent A** | CCL Stage 1+2 + Canonical registers | CCL Stage 1 reads + CCL Stage 2 reads + Canonical registers (Categories A+B+D) | ~80-100 lines of routing entries |
| **Agent B** | Architecture + Process meta-docs + Plans | Architecture + phase status + Process meta-docs + Active plans (Categories E+F+G) | ~80-100 lines |
| **Agent C** | Phase-specific + Validation trail + Sidecars | Phase-specific deep dives (phase1 + phase2 subdirs) + Validation trail + Sidecars + Reference lookup (Categories C+H+I) | ~80-100 lines |

Each sub-agent prompt includes:
- **Planning-discipline skill inheritance** section per CLAUDE.md hard rule 13 + PLANNING_DISCIPLINE.md §3.1 template
- **Active skills**: `superpowers-verification-before-completion` (always-mandatory) + `superpowers-systematic-debugging` (if confusion) + `udm-progress-logger` (mid-session) + `udm-gap-check` (post)
- **Routing-by-intent constraint**: per §13.2 + ETH Zurich research §3.6 Finding 5; flag structural-style entries pre-emptively
- **Cross-ref preservation**: per §13.3 Navigation Paradox MANDATORY; verify each linked file exists; verify section anchors

Parent agent assembles + reviews cohort outputs + applies `udm-gap-check` independent reviewer for final 🟡/🟢 verdict before commit.

### §4.3 Risks + mitigations

1. **Overlap / section-boundary drift**: agents may interpret category boundaries differently. **Mitigation**: each agent's prompt explicitly enumerates sections to author + sections to NOT author (deduplication contract).
2. **Verbatim-extraction-safety per B-280**: when sub-agents quote file titles / paths from the inventory, they should cite paths (not re-type). **Mitigation**: pass §1 inventory as verbatim quote in each prompt.
3. **Cross-ref staleness per Pitfall #9.k arithmetic-propagation**: section line counts / file counts in routing descriptions may drift. **Mitigation**: routing-by-intent doesn't include line counts (avoids drift class entirely).

---

## §5. 5-gate validation per `udm-checks-and-balances` (post-execution)

When INDEX.md authoring lands:
- **Gate 1 — Cross-reference**: every entry's `[filename](path)` link MUST resolve to an existing file. Verify via Bash glob.
- **Gate 2 — QA**: routing-by-intent format consistent across all entries; no structural-by-description leakage.
- **Gate 3 — Edge cases**: agents reading INDEX.md from fresh context can locate target docs via the descriptions alone.
- **Gate 4 — Edge case validation**: spawn `udm-gap-check` independent reviewer to verify INDEX completeness + routing-correctness.
- **Gate 5 — Idempotency/regression**: re-running INDEX generation should produce same content (sort + format stability).

---

## §6. Application of new discipline floor

Per session-2026-05-15 synthesis, every commit going forward applies:
- **`superpowers-verification-before-completion`**: re-read draft INDEX.md before claiming D.2 prep complete (THIS doc); pytest + content re-read before claiming D.2 execution complete
- **`superpowers-systematic-debugging`**: if INDEX.md has any unexpected behavior (broken cross-refs, agent confusion), apply 4-phase root-cause first
- **`udm-planning-session-startup`**: applied at start of this prep (PS-2 DOC + PS-6 COHORT scope identified)
- **B-280 verbatim-extraction-safety**: when sub-agents extract file content, use curl/sed for raw + project-local paths for assembly (not Write-tool re-typing)
- **Sub-agent inheritance contract per CLAUDE.md hard rule 13**: 4th production application (research, gap-check, gap-check on D.5 trim, now D.2 cohort)

---

## §7. Acceptance criteria for D.2 execution (post-approval)

✅ INDEX.md lands at `docs/migration/INDEX.md` (~280-350 lines; routing-by-intent format)
✅ Each entry's `[filename](path)` link resolves to existing file (Gate 1)
✅ `last_regenerated_at` line at top per gap §10b.2 EC-MR2
✅ Per-file scope statements drafted for the 10 large files (~1,000+ lines) per §7.1 task 1.4
✅ CLAUDE.md Read order extended with INDEX.md as new item 0 (PRE-everything; CCL Stage 0 doctrine per D62)
✅ GLOSSARY entry added for INDEX.md
✅ `udm-step-10-verifier` ✅ CLEAN (new public surface = INDEX.md)
✅ `udm-gap-check` independent reviewer verdict ≤🟡
✅ `superpowers-verification-before-completion`: fresh `wc -l docs/migration/INDEX.md` + cross-ref grep evidence shown before completion claim
✅ Pytest unchanged (`2320 / 58 / 0`)
✅ Pipeline-lead post-INDEX review approves

---

## §8. Pipeline-lead decision required

**Choose execution approach for D.2 INDEX.md authoring**:
- **Option A — single-agent (parent solo)**: ~1-2 hours; simpler; no cohort overhead
- **Option B — 3-parallel-agent cohort (Recommended for discipline-proving)**: ~3-4 hours; validates inheritance contract for 4th time; produces empirical evidence for `udm-context-loader` skill (per B-275) eventual authoring; demonstrates discipline floor working at scale
- **Option C — partial cohort (2 agents)**: middle ground — Agent A (CCL Stage 1+2 + Canonical) + Agent B (everything else); ~2-3 hours

All approaches:
- Apply discipline floor (verification-before-completion + inheritance + planning-session-startup)
- Land INDEX.md at `docs/migration/INDEX.md`
- Update CLAUDE.md Read order + GLOSSARY + tracker pass + commit
- Pattern E review (D.6) deferred to Phase 1 close-out

After D.2 lands → D.3 (D62 CCL Stage 0 doctrine update) → D.4 (skill SKILL.md cascade) per Option A path you chose.
