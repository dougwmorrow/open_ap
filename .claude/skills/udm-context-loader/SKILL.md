---
name: udm-context-loader
description: Operationalizes Canonical Context Load (D62) Stage 1+2+3 as a single-Skill invocation for sub-agents. Takes a sub-agent scope spec (PS-N code + topic) and emits a compact context brief carrying PASS-THROUGH-VERBATIM Do-NOT rules + Pitfall #9.x headers + D-N/R-N/RB-N/SP-N cross-refs per scope, plus skill-inheritance directives for the sub-agent. Closes the multi-agent CCL-repetition cost surface (per MARKDOWN_REFACTOR_PLAN.md §4.5 Option T5; F5.1 verbatim_excerpts mitigation per §15.2 + §17.3; B-275). When parent spawns a multi-agent cohort, parent invokes THIS skill ONCE; sub-agents consume the brief instead of each performing their own Stage 1+2 reads (~50K-65K lines saved per 5-agent Pattern E cycle).
version: 1.0.0
---

# UDM Context Loader

Skill that distills the Canonical Context Load (D62 Stage 1+2+3) for a specific sub-agent scope into a compact, structurally-bounded brief. Emitted brief lets sub-agents skip ad-hoc multi-Read of CCL substrate while preserving non-distillable content (Do-NOT rules, Pitfall #9.x headers, binding D-N status lines) verbatim. Pairs with `udm-planning-session-startup` (parent-side) + the CLAUDE.md hard rule 13 sub-agent inheritance contract.

## When to invoke

**Mandatory trigger phrases (parent agent invokes BEFORE spawning sub-agent(s))**:
- "Spawn N parallel sub-agents to ..." (any N ≥ 2)
- "Use a multi-agent team to ..." (per user-direction patterns)
- "Spawn an independent reviewer to ..." (single-agent CCL distillation also valid)
- "Pattern E review cohort" / "Pattern F audit cohort" / "Wave N build cohort"
- "Parallel gap-audit" / "Parallel research" / "Multi-agent cohort"

**Strongly recommended trigger phrases (single-agent invocations where the agent's scope is well-bounded)**:
- "Spawn a sub-agent to author RB-N ..." (PS-5 RUNBOOK scope)
- "Spawn a sub-agent to lock D-N ..." (PS-8 D-N scope)
- "Spawn a sub-agent to build tool X ..." (PS-3 TOOL scope)

**Anti-triggers (do NOT invoke)**:
- Single-agent fix-only cycle (modifying existing function body; signatures unchanged) — sub-agent has narrow Read scope; full CCL distillation is overhead
- Read-only exploration (Grep + Glob only; no Edit / Write) — no production-code touch, no canonical Edit
- Sub-agent inherits parent's already-loaded CCL via direct prompt context (parent's Stage 1+2 reads already in working context window) AND the sub-agent task is a narrow follow-up (e.g., a 5-min audit of a single artifact)
- Trivial cosmetic edits (typo / whitespace / badge flip per Pitfall #9.j anti-triggers per CLAUDE.md hard rule 14)

## Why this skill exists (empirical evidence base)

Per `docs/migration/MARKDOWN_REFACTOR_PLAN.md` §4.5 (Option T5) + §15.4 (CCL empirical baseline) + §17.3 (F5.1 verbatim_excerpts mitigation) + B-275 (`docs/migration/BACKLOG.md` L362-363):

**Empirical baseline (per `_research/ccl-baseline-2026-05-15.md`)**:
- CCL Stage 1 + Stage 2 = **362,154 tokens (~181% of 200K context window)**
- A 5-agent Pattern E cycle currently repeats Stage 1+2 reads 5× (each sub-agent re-loads CCL substrate from scratch)
- Total CCL repetition cost across a typical cycle: ~50K-65K tokens of redundant context

**Distillation target (per MARKDOWN_REFACTOR_PLAN.md §4.5)**:
- ONE invocation of `udm-context-loader` distills CCL into a brief of ~500-1K lines (~5K-10K tokens)
- Sub-agents consume the brief instead of re-reading raw CCL files
- **Savings**: ~80% reduction in CCL substrate cost across a 5-agent cohort

**F5.1 mitigation (per MARKDOWN_REFACTOR_PLAN.md §15.2 Pattern d + §17.3)**:
Distillation cannot summarize the following content (would lose tripwire fidelity for production-touching changes):
- Every Do-NOT rule (`CLAUDE.md` Do-NOT section + spec doc Do-NOT lines)
- Every Pitfall #9.X sub-class header (exact header text)
- Every binding `**D-N**: ... 🟢 Locked YYYY-MM-DD` status line in scope
- Every `R-N` risk header row (header only, not body)

These four categories MUST pass through the brief verbatim. The brief carries them as a tripwire, NOT as a substitute for the canonical source — sub-agents touching production code (CDC/SCD2/schema migrations/SP definitions/BCP writers) MUST direct-Read the canonical source for any verbatim excerpt before proposing a change.

## Canonical Context Load (CCL) per D62 — this skill's own CCL

The skill's invoker (typically the parent agent) MUST have already loaded CCL (Stage 1+2; ideally Stage 0 routing manifest). This skill REUSES the parent's already-loaded context to build the brief; it does NOT trigger new Read tool calls if the parent has the substrate in working context.

- **Stage 0**: `docs/migration/INDEX.md` (routing manifest; recommended when parent is uncertain which Stage 1+2 docs are relevant to the sub-agent scope)
- **Stage 1** (mandatory): `NORTH_STAR.md` + `HANDOFF.md` (§8 Pitfall #9.x sub-class register) + `CURRENT_STATE.md` + `CHECKS_AND_BALANCES.md`
- **Stage 2** (mandatory): `RISKS.md` + `BACKLOG.md` + `_validation_log.md` (current round entries only)
- **Stage 3** (scope-conditional): `CLAUDE.md` (Do-NOT + Structure + hard rules + EventType families) + `GLOSSARY.md` + spec docs per scope (see procedure Step 3) + `PLANNING_DISCIPLINE.md` (skill-inheritance matrix)

## Procedure (6 steps)

### Step 1 — Receive scope spec from parent

Parent passes:
- **PS-N code** (per `PLANNING_DISCIPLINE.md` §2.1; PS-1 ARCH / PS-2 DOC / PS-3 TOOL / PS-4 SP / PS-5 RUNBOOK / PS-6 COHORT / PS-7 CLOSEOUT / PS-8 D-N / PS-9 SELF)
- **Topic identifier** (e.g., `"Round 3 § 1.2 parquet_replay build"` / `"D62 CCL Stage 0 doctrine extension"` / `"RB-12 disaster recovery"`)
- **Sub-agent role** (`producer` / `reviewer` / `gap-auditor` / `researcher` / `test-author`)
- **Output target** (file path the sub-agent will Edit/Write; informs Stage 3 spec doc selection)

### Step 2 — Look up applicable skills per PS-N

Use `PLANNING_DISCIPLINE.md` §2.2 matrix to enumerate:
- **Mandatory at session start** skills the sub-agent inherits
- **Conditional during session** skills (with timing rationale)
- **Always-mandatory** skills (per §2.3): `udm-gap-check` / `udm-progress-logger` / `udm-step-10-verifier` (if new public surface) / `superpowers-verification-before-completion` / `superpowers-systematic-debugging` / `udm-post-edit-verification`

### Step 3 — Identify scope-conditional Stage 3 spec docs

Mechanical lookup (NOT enumeration of every Stage 3 doc — only those the sub-agent's scope touches):

| Scope keyword | Stage 3 spec doc(s) |
|---|---|
| Round 1 / DDL / table / index / SP / control-table | `phase1/01_database_schema.md` + `phase1/01a_control_tables.md` (+ `phase1/01c_data_flow_walkthrough.md` if data-flow-touching) |
| Round 2 / configuration / UdmTablesList / Automic | `phase1/02_configuration.md` |
| Round 3 / core module / data_load / cdc / observability / scd2 | `phase1/03_core_modules.md` (+ `phase1/01c_data_flow_walkthrough.md` if data-flow-touching) |
| Round 4 / operator tool / CLI | `phase1/04_tools.md` |
| Round 5 / test / Tier 0-4 | `phase1/05_tests.md` |
| Round 6 / deployment / promotion / soak | `phase1/06_deployment.md` |
| Round 7 / schema evolution / forward-only | `phase1/07_schema_evolution_governance.md` |
| Round 8 / self-improvement / skill / agent prompt | `phase1/08_sub_agent_self_improvement.md` |
| Runbook / RB-N | `05_RUNBOOKS.md` |
| Decision / D-N | `03_DECISIONS.md` |
| Edge case / M/S/I/N/P/G/D/F/V/DP/T/SI series | `04_EDGE_CASES.md` |
| Gotcha / B-N / E-N / V-N / W-N / OBS-N / SCD2-* | `CLAUDE_GOTCHAS.md` |
| Planning doc / plan output / PS-N session deliverable | None for PS-1/2/3/4/5/6/7/8 (Stage 1+2 brief sufficient; planning docs have no Phase-spec canonical source — sub-agent's output IS the planning artifact, not a derivative of one. Per reviewer `adf74ca386f192d64` IMPROVE #3 2026-05-17). **EXCEPTION: PS-9 SELF (skill review + optimization sessions) — REQUIRES Stage 3 additions of `04_EDGE_CASES.md` + `CLAUDE.md` (hard rule 14 + Pitfall sub-class additions)** per B-412 closure 2026-05-17 (Cohort B Agent 55 CB-7-A finding). Skill-review sessions need edge case register access + hard-rule citation surface; the 2026-05-17 4-cohort skill audit (Agents 54-57) empirically demonstrated this requirement when each cohort had to reference both files extensively. |

### Step 4 — Extract verbatim excerpts per F5.1 (PASS-THROUGH-VERBATIM contract)

For each Stage 1+2+3 doc identified in Step 3, the brief MUST extract verbatim (no summarization):

1. **Do-NOT rules in scope**: every line in `CLAUDE.md` Do-NOT section + every `❌` or `Do NOT` line in Stage 3 spec docs that touches the sub-agent's scope. Include full sentence-or-bullet context.
2. **Pitfall #9.X sub-class headers**: from `HANDOFF.md` §8, every Pitfall #9.X header text (e.g., `Pitfall #9.j — B-item status-render discipline`). Brief includes ONLY the header text + 1-line summary; full body stays in HANDOFF.md (sub-agent direct-Reads if it intends to apply the directive).
3. **Binding D-N status lines**: from `03_DECISIONS.md`, every `**D-N**: ... 🟢 Locked YYYY-MM-DD` status line for D-N referenced in scope. Status line only, not body.
4. **R-N risk header rows**: from `RISKS.md`, every risk-table header row for R-N referenced in scope.

### Step 5 — Compose the brief

Emit the brief as a markdown artifact (typically inline in the parent's prompt to the sub-agent, NOT a file). See "Output contract" below for schema.

**Rationale for "NOT a file"** (per reviewer `adf74ca386f192d64` IMPROVE #4 2026-05-17): briefs are SNAPSHOTS at composition time. Writing the brief to a file introduces a staleness risk — if the parent's context evolves between brief composition and sub-agent invocation (additional research surfaces; canonical source updated; new Pitfall sub-class promoted), the file-bound brief becomes stale + the sub-agent operates on outdated context. Inline-in-prompt is the safe default; the brief's `Brief composed: YYYY-MM-DD HH:MM` timestamp field warns the sub-agent of the snapshot moment.

### Step 6 — Pass brief to sub-agent + cite invocation

Parent's sub-agent prompt MUST include:
- The brief verbatim (parent does NOT re-summarize the brief)
- The `Planning-discipline skill inheritance` section (per CLAUDE.md hard rule 13)
- An explicit directive: "Direct-Read the canonical source for any verbatim excerpt before proposing production-code changes" (per F5.1 tripwire-not-substitute rule)

Parent's `_validation_log.md` event row for the sub-agent invocation MUST cite: `Brief composed via udm-context-loader skill at <timestamp>; passed to <N> sub-agents`.

## Output contract (the brief schema)

The brief is a markdown structure with these required sections (in this order):

```markdown
## Sub-agent context brief — <PS-N code> <topic>

### Scope header
- **PS-N code**: <PS-N> per PLANNING_DISCIPLINE.md §2.1
- **Topic**: <topic identifier>
- **Sub-agent role**: producer / reviewer / gap-auditor / researcher / test-author
- **Output target**: <file path>
- **Brief composed**: <YYYY-MM-DD HH:MM>

### Stage 1+2 canonical-source excerpts (PASS-THROUGH-VERBATIM)

#### Do-NOT rules in scope
- [verbatim from CLAUDE.md Do-NOT section + Stage 3 spec doc Do-NOT lines]
- ...

#### Pitfall #9.X sub-class headers in scope
- **Pitfall #9.X** — <header text> (per HANDOFF.md §8; direct-Read for body)
- ...

#### Binding D-N status lines in scope
- **D-N**: <title> 🟢 Locked YYYY-MM-DD (per 03_DECISIONS.md; direct-Read for body)
- ...

#### R-N risk headers in scope
- **R-N**: <header text> (per RISKS.md; direct-Read for body)
- ...

### Stage 3 spec doc cross-refs
- `phase1/XX_*.md § Y.Z` (the canonical section(s) the sub-agent's scope touches)
- ...

### Use these skills (per PLANNING_DISCIPLINE.md §2.2 + §2.3)

**Mandatory at sub-agent invocation start**:
- <skill-name> (skill/agent): <when>
- ...

**Conditional during sub-agent work**:
- <skill-name> (skill/agent): <when>
- ...

**Always-mandatory (per §2.3)**:
- `udm-gap-check` (skill) — at sub-agent attestation (independent reviewer per D55+D56)
- `udm-progress-logger` (skill) — at each substantive completion
- `udm-step-10-verifier` (skill) — if sub-agent introduces new public surface
- `superpowers-verification-before-completion` (skill) — before any completion claim (Iron Law: fresh evidence)
- `superpowers-systematic-debugging` (skill) — if sub-agent encounters bug / test failure
- `udm-post-edit-verification` (skill) — TEST + GAP + REVIEW cascade per CLAUDE.md hard rule 14

### Sub-agent inheritance contract (binding per CLAUDE.md hard rule 13)

You are operating within an active planning session. Your `Read` tool calls SHOULD focus on the Stage 3 spec doc(s) cited above + the file(s) at your output target. Stage 1+2 substrate is summarized in this brief; direct-Read canonical sources ONLY for verbatim excerpts you intend to apply or modify (per F5.1 tripwire-not-substitute rule).

You are NOT exempt from any always-mandatory skill. Cite skill invocations in your final report.
```

## Composition

| Used with | Role |
|---|---|
| `udm-planning-session-startup` | Parent invokes planning-startup FIRST (whole-session scope); then invokes `udm-context-loader` per sub-agent spawn (per-spawn scope). Both compose; neither replaces the other. |
| `udm-gap-check` | Sub-agent's brief includes `udm-gap-check` in always-mandatory list; sub-agent invokes at its attestation. Independent of parent's gap-check (parent's gap-check audits the META-COMMIT after all sub-agents return). |
| `udm-progress-logger` | Brief includes `udm-progress-logger` in always-mandatory list; sub-agent logs at completion to BACKLOG / `_validation_log.md` / applicable trackers. |
| `udm-step-10-verifier` | If sub-agent introduces new public surface, brief routes the verifier to fire after sub-agent build completes + before sub-agent gap-check. |
| `udm-exemption-verifier` | If sub-agent's commit message includes exemption-claim phrasing, the verifier fires at commit-msg hook time (Mechanism C-1 per CLAUDE.md hard rule 14). Brief does NOT pre-empt this; verifier is harness-enforced. |
| `MULTI_AGENT_GUIDE.md § Canonical Context Load (D62)` | The brief operationalizes the doc-discipline. When this skill is unavailable (e.g., on a fresh clone before SKILL.md is loaded), sub-agents fall back to the doc-discipline. |
| `check_planning_provenance` (`tools/pre_commit_checks.py`) | **Mechanical commit-time enforcement** of the `## §0. Planning session provenance` header per the same B-275 / planning-discipline class this skill addresses. Sub-agents committing plan docs without §0 will be BLOCKED at the hook level regardless of whether `udm-context-loader` was invoked. Companion mechanism added 2026-05-17 by Worker B parallel to this skill (per next-steps plan Option A); harness layer enforces what skill operationalizes at authoring time. |

## Sub-agent inheritance contract

This skill ITSELF establishes the sub-agent inheritance contract per CLAUDE.md hard rule 13. The brief's "Use these skills" section IS the inheritance section the parent's sub-agent prompt MUST include.

Edge cases:
- **Sub-agent spawns its own sub-agent** (rare; depth-2 multi-agent): the depth-1 sub-agent should ALSO invoke `udm-context-loader` for its depth-2 spawn. Each level of multi-agent depth gets its own brief.
- **Sub-agent abandons task mid-flight** (returns early without completion): parent's `udm-progress-logger` event row notes "sub-agent abandoned"; the brief is discarded. No tracker drift.
- **Brief composed but sub-agent never spawned** (parent changes plan): brief is discarded; parent notes the abort in `_validation_log.md`. Brief composition cost is sunk; no further action.

## Tier 0 stub reference

`tests/tier0/test_skill_context_loader.py` — verifies:
- SKILL.md file exists at `.claude/skills/udm-context-loader/SKILL.md`
- Frontmatter parses (name + version + description present)
- Required sections present (9 sections: When to invoke / Why this skill exists / Canonical Context Load / Procedure / Output contract / Composition / Sub-agent inheritance contract / Tier 0 stub reference / Cross-references)
- Trigger-phrase enumeration present (at least 5 mandatory triggers + at least 3 anti-triggers)
- Sub-agent inheritance section present
- Output-contract schema example present (markdown code fence with brief schema)

## Cross-references

- **MARKDOWN_REFACTOR_PLAN.md §4.5** — Option T5 design rationale + 50K-65K-line savings target
- **MARKDOWN_REFACTOR_PLAN.md §15.2 Pattern d** — F5.1 verbatim_excerpts brief schema mandate
- **MARKDOWN_REFACTOR_PLAN.md §17.3** — F5.1 CRITICAL failure mode (brief omits Do-NOT rule → destruction-class production change possible)
- **MARKDOWN_REFACTOR_PLAN.md §15.4** — empirical CCL baseline (Stage 1+2 = 362K tokens = 181% of 200K window)
- **PLANNING_DISCIPLINE.md §2.2** — skill-selection matrix lookup (mandatory/conditional/always)
- **PLANNING_DISCIPLINE.md §3** — sub-agent inheritance contract reference
- **CLAUDE.md hard rule 13** — planning-session-startup + sub-agent inheritance binding
- **CLAUDE.md hard rule 14** — post-edit verification cascade (always-mandatory for sub-agent commits)
- **CLAUDE.md Do-NOT section** — canonical home for Do-NOT rules passed through brief verbatim
- **HANDOFF.md §8** — Pitfall #9.X sub-class register passed through brief by header
- **D62** — Canonical Context Load doctrine (CCL Stage 0/1/2/3 framework)
- **D55 + D56** — independent reviewer + mandatory second-pass discipline (sub-agent gap-check)
- **MULTI_AGENT_GUIDE.md § Canonical Context Load** — fallback doc-discipline when skill unavailable
- **B-275** — this skill's closure target (BACKLOG.md L362-363)
- `.claude/skills/udm-planning-session-startup/SKILL.md` — companion (whole-session scope)
- `.claude/skills/udm-gap-check/SKILL.md` — sub-agent attestation skill
- `.claude/skills/udm-progress-logger/SKILL.md` — sub-agent completion-logging skill
- `.claude/skills/udm-step-10-verifier/SKILL.md` — sub-agent build-cohort surface-registration verifier
- `tools/measure_ccl_overhead.py` — empirical baseline tool (per `_research/ccl-baseline-2026-05-15.md`)

## Owner

Pipeline lead. First production invocation expected: next multi-agent cohort spawn (PS-6 COHORT scope) OR next single-agent spawn where sub-agent scope is well-bounded (PS-3 / PS-5 / PS-8). Brief composition cost target: <2 min wall-clock per spawn.
