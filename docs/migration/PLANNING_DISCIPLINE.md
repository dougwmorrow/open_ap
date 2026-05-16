# UDM Planning Discipline — skill-selection matrix + sub-agent inheritance contract

**Version**: v0.2 (research-grounded; revised 2026-05-15 per B-279 closure via `udm-researcher` invocation; semver MINOR delta from v0.1 per `udm-agent-prompt-versioner` discipline)

**Status**: 🟢 **Locked 2026-05-15** per D111 process-infra exemption (analogous to D55 / D60 / D89-D91 / D95-D99 / D113 — process-discipline meta-docs don't gate on 🟡-first attestation when the discipline they encode is itself first-event-evidenced and pipeline-lead approved). v0.2 confidence elevated MEDIUM → HIGH for core premise (sub-agent inheritance contract + structured skill selection); MEDIUM remains for specific 9-PS-N-scope-categories design choice per research counter-evidence noted in §7.

**Owner**: Pipeline lead. Maintainers: `udm-planning-session-startup` skill + `udm-cascade-audit-evolver` (for matrix evolution at round close-out).

**Purpose**: Single canonical reference for (a) which skills should be invoked during which type of planning session, (b) how sub-agents inherit the parent's skill activation context, (c) the §0 provenance section format for plan deliverables. Closes the gap surfaced 2026-05-15 by the markdown refactor planning session (4 skills were not invoked that should have been: `udm-design-reviewer` / `udm-checks-and-balances` / `udm-execution-classifier` / `udm-decision-recorder`).

---

## §1. Why this exists (gap evidence + structural intervention rationale)

### §1.0 Research-grounded foundation (v0.2 addition per B-279 closure)

The v0.1 of this doc cited 1-event evidence (markdown refactor planning session 2026-05-15 missed 4 skills). v0.2 grounds the discipline in **4 academic + 1 official-vendor primary sources** per `udm-researcher` invocation 2026-05-15 (see `_research/planning-discipline-industry-standards-2026-05-15.md`):

| Source | Finding | Validates |
|---|---|---|
| **Anthropic official Claude Code docs** ([code.claude.com/docs/en/sub-agents](https://code.claude.com/docs/en/sub-agents)) | Sub-agents do NOT inherit skills from parent conversations — skills must be explicitly listed in the sub-agent definition's `skills:` field | §3 sub-agent inheritance contract addresses an officially-documented architectural gap, NOT a fabricated concern |
| **Anthropic Complete Guide to Building Skills** (January 2026; [resources.anthropic.com](https://resources.anthropic.com/hubfs/The-Complete-Guide-to-Building-Skill-for-Claude.pdf)) | Activation rates: poor description → 0%; optimized (what + when + trigger phrases) → 50%; optimized + examples → 90% | §2.2 matrix entries require each skill's SKILL.md to reach the "optimized + examples" tier for reliable invocation; non-trivial requirement |
| **SkillsBench (arxiv 2602.12670)** | Curated human-authored skills: +16.2 percentage points improvement on task completion across 84 tasks / 11 domains / 7 model configs. Self-generated skills: negligible OR negative benefit. 3 skills produced negative deltas up to -10% due to context interference | Curated-skill approach validated; context-interference risk quantified (motivates the "minimum viable skill set" principle in §2.5 v0.2 addition) |
| **CodeCompass Navigation Paradox (arxiv 2602.20048)** | Agents skip tool invocation 58% of the time even with explicit prompt instructions. Fix: checklist-at-END formatting achieves 100% adoption (vs 85.7% mid-prompt). Lost-in-the-Middle suppression effect | §2.6 v0.2 addition: structural enforcement via end-of-prompt placement |
| **GoalAct (arxiv 2504.16563, NCIIP 2025 Best Paper)** | +12.22% performance gain from hierarchical skill pre-specification (high-level categories: search / code / write) | 9 PS-N scope categories serve analogous function (constrains planning space; reduces cognitive load) |

**Aggregate empirical confidence**: HIGH for core premise (sub-agent inheritance gap + structured skill selection improves task completion). See §7 + companion research artifact for full citation list (~30 primary sources) + counter-evidence (SWE-Skills-Bench domain-specificity moderation; Aider performs well without skill-matrix; METR algorithmic-vs-holistic measurement bias).

### §1.1 The empirical gap

Markdown refactor planning session 2026-05-15 (commit `521b68c` + remediation `1b00755`):

- Plan touched CCL doctrine + skill-prompt cascade + INDEX architecture — would have warranted `udm-design-reviewer` invocation at session start; **NEVER invoked**
- Plan introduced 2 new tools (`test_github_slug.py`, `measure_ccl_overhead.py`) — would have warranted `udm-execution-classifier` at spec time; **classified ad-hoc in CLAUDE.md after the fact**
- Plan proposed D-N candidates (Q-23 hygiene rules; refactor decision itself) — would have warranted `udm-decision-recorder` upfront; **deferred to "next round close-out"** without explicit tracker until B-274 was opened during remediation
- Plan attestation should have run formal 5-gate validation per D55 — would have warranted `udm-checks-and-balances`; **did inline gap-audits which are spirit-not-letter of the discipline**

Independent `udm-gap-check` reviewer on commit `1b00755` confirmed all 4 omissions.

### §1.2 The structural cause

The standing skill catalogue lives at `.claude/skills/<skill-name>/SKILL.md`. There are 20+ skills. Each skill documents its own "When to invoke" section but no SINGLE LOOKUP TABLE maps "planning scope" → "applicable skills". Without a matrix, agents fall back to memory + intuition, which:

- Favors recently-used skills (recency bias)
- Misses skills the agent has never invoked before (discoverability gap)
- Doesn't propagate to sub-agents (each sub-agent re-discovers independently OR doesn't discover at all)

This is the **CodeCompass Navigation Paradox** (arxiv 2602.20048) applied to skill discovery: explicit cross-references push agent file-discovery from 78.2% to 99.4%. Same principle applies to skill discovery.

### §1.3 The intervention (3 components)

1. **`udm-planning-session-startup` skill** (`.claude/skills/udm-planning-session-startup/SKILL.md`) — operationalizes the 5-step protocol (identify scope → matrix lookup → surface to user → apply skills → emit §0 provenance)
2. **This document (`PLANNING_DISCIPLINE.md`)** — canonical skill-selection matrix + sub-agent inheritance contract + plan-deliverable §0 provenance template
3. **CLAUDE.md hard rule 13** — binding directive for all agents/sub-agents/multi-agent-teams to invoke the startup skill on planning-intent + apply the inheritance contract

---

## §2. Skill-selection matrix

### §2.1 Scope categories (9 PS-N codes)

| Scope code | Description | Examples |
|---|---|---|
| **PS-1 ARCH** | Architectural plan touching pipeline core / CCL doctrine / schema / security / decision framework | Phase round structure; new module family; security model change; CCL Stage 0 doctrine |
| **PS-2 DOC** | Doc-refactor / structural / markdown-hygiene plan | Markdown refactor; spec doc reorganization; per-file INDEX sidecars |
| **PS-3 TOOL** | New tool / executable script (one-shot or recurring) | Operator CLI; migration script; meta-tooling for measurement |
| **PS-4 SP** | New stored procedure / DDL change / schema evolution | SP-N addition; column ALTER; SchemaContract row; index change |
| **PS-5 RUNBOOK** | New operational runbook (RB-N) | Recovery procedure; deployment runbook; incident response |
| **PS-6 COHORT** | Multi-agent cohort spawn (3+ parallel sub-agents) | Parallel build cohort; parallel gap-audit; parallel research |
| **PS-7 CLOSEOUT** | Phase round close-out | End of Round N; self-improvement cascade |
| **PS-8 D-N** | Plan introducing D-N candidates | Decision documentation; policy lock; convention change |
| **PS-9 SELF** | Self-improvement family (skill / agent prompt / discipline) | Producer-checklist evolution; sub-class accumulation; cascade-audit-evolver delta |

**Multi-scope plans**: pick PRIMARY scope + note SECONDARY scopes; matrix lookup unions the rows (de-duplicated skill list).

### §2.2 Skill-selection matrix (the canonical lookup table)

**Tool surface disambiguation** (per udm-gap-check 2026-05-15 G3 finding): the matrix below references both **skills** (`.claude/skills/<name>/SKILL.md` — invoked via Skill tool) AND **agents** (`.claude/agents/<name>.md` — invoked via Agent tool with `subagent_type` parameter). To clarify the invocation mechanism:
- **Skills**: `udm-brainstorm`, `udm-checks-and-balances` (also an agent), `udm-decision-recorder`, `udm-edge-case-validator`, `udm-execution-classifier`, `udm-gap-check`, `udm-next-step-cascade`, `udm-planning`, `udm-planning-session-startup`, `udm-post-build-verify`, `udm-progress-logger`, `udm-round-closeout`, `udm-runbook-author`, `udm-step-10-verifier`, plus self-improvement family (`udm-retrospective-collector`, `udm-producer-checklist-evolver`, `udm-specialty-tuner`, `udm-subclass-accumulator`, `udm-cycle-cadence-optimizer`, `udm-cascade-audit-evolver`, `udm-agent-prompt-versioner`)
- **Agents**: `udm-design-reviewer`, `udm-test-author`, `udm-researcher`, `udm-cascade-auditor`, `udm-data-engineer-review`, `udm-checks-and-balances`
- **Doc-discipline (not a tool)**: `MULTI_AGENT_GUIDE.md § Canonical Context Load (D62)` — the canonical-context-load discipline that agents apply directly via the Read tool over Stage 1+2 docs

| Scope | Mandatory at session start | Conditional during session | When (conditional timing) |
|---|---|---|---|
| **PS-1 ARCH** | `udm-design-reviewer` (agent), `udm-checks-and-balances` (skill/agent), `udm-researcher` (agent) | `udm-decision-recorder` (skill), `udm-execution-classifier` (skill), `udm-test-author` (agent), `udm-brainstorm` (skill) | recorder for D-N candidates; classifier for new tools; test-author for test sketches; brainstorm for open design questions |
| **PS-2 DOC** | `udm-checks-and-balances` (skill), `udm-researcher` (agent) | `udm-execution-classifier` (skill), `udm-cascade-audit-evolver` (skill), `udm-decision-recorder` (skill) | classifier if new tools introduced; cascade-evolver if Pattern F changes; recorder if D-N candidate |
| **PS-3 TOOL** | `udm-execution-classifier` (skill), `udm-test-author` (agent), `udm-design-reviewer` (agent) | `udm-runbook-author` (skill), `udm-decision-recorder` (skill) | runbook-author if operator-facing; recorder if D-N candidate (often paired) |
| **PS-4 SP** | `udm-data-engineer-review` (agent), `udm-design-reviewer` (agent), `udm-checks-and-balances` (skill/agent), `udm-decision-recorder` (skill) | `udm-runbook-author` (skill), `udm-test-author` (agent), `udm-edge-case-validator` (skill) | runbook for operational change; test for integration; edge-case for new SP edge cases |
| **PS-5 RUNBOOK** | `udm-runbook-author` (skill), `udm-design-reviewer` (agent) | `udm-decision-recorder` (skill), `udm-checks-and-balances` (skill/agent) | recorder for D-N pair; checks at attestation |
| **PS-6 COHORT** | `MULTI_AGENT_GUIDE.md § Canonical Context Load` (D62 doc-discipline; sub-agents apply at spawn time per CLAUDE.md hard rule 13 inheritance contract), `udm-step-10-verifier` (skill), `udm-gap-check` (skill), `udm-progress-logger` (skill) | + cascade-specific skills per cohort scope; `udm-post-build-verify` (skill) if code | CCL discipline at sub-agent spawn (binding per CLAUDE.md hard rule 13; sub-agent's first Read MUST hit a Stage 1 doc per D62); verifier after build; gap-check after; logger throughout; post-build-verify for pytest re-run after parallel cohort. **Note**: planned `udm-context-loader` skill (per MARKDOWN_REFACTOR_PLAN.md §4.5) would operationalize this discipline as a single-Skill invocation; **B-275** tracks its authoring. |
| **PS-7 CLOSEOUT** | `udm-round-closeout` (skill), `udm-cascade-auditor` (agent), `udm-progress-logger` (skill) | self-improvement family (`udm-retrospective-collector`, `udm-producer-checklist-evolver`, `udm-specialty-tuner`, `udm-subclass-accumulator`, `udm-cycle-cadence-optimizer`, `udm-cascade-audit-evolver`, `udm-agent-prompt-versioner` — all skills) | Section 10 self-improvement cascade per `udm-round-closeout` SKILL.md |
| **PS-8 D-N** | `udm-decision-recorder` (skill), `udm-design-reviewer` (agent), `udm-checks-and-balances` (skill/agent) | `udm-brainstorm` (skill), `udm-researcher` (agent), `udm-progress-logger` (skill) | brainstorm if multiple defensible options; researcher for primary-source grounding; logger throughout |
| **PS-9 SELF** | `udm-producer-checklist-evolver` OR `udm-specialty-tuner` OR `udm-subclass-accumulator` (skills; per which family), `udm-retrospective-collector` (skill), `udm-agent-prompt-versioner` (skill) | `udm-cascade-audit-evolver` (skill), `udm-checks-and-balances` (skill/agent), `udm-design-reviewer` (agent) | cascade-evolver for Pattern F changes; checks at attestation; reviewer for non-trivial skill prompt changes |

### §2.3 Always-mandatory skills (regardless of scope)

These skills apply to EVERY planning session, regardless of PS code:

- **`udm-gap-check`** — at planning-session attestation per CLAUDE.md hard rule 11 (post-substantive-work; spawn independent reviewer)
- **`udm-progress-logger`** — at end of each substantive build/edit per CLAUDE.md hard rule 9 (universal-5 trackers + per-build-type checklist)
- **`udm-step-10-verifier`** — if planning session introduces new public surface (modules / tools / functions / classes / constants / EventTypes / SPs) per CLAUDE.md hard rule 9 Step 12
- **`superpowers-verification-before-completion`** (added 2026-05-15 per B-279 follow-up partial adoption Option B; upstream `obra/superpowers` v5.1.0 MIT) — invoke BEFORE any completion claim. Iron Law: "NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE". Pairs with `udm-gap-check` (this skill is PRE-completion; gap-check is POST-completion). Direct relevance: would have prevented Pitfall #9.k stale-narrative-quotation pattern from commit `521b68c` (claimed pytest 2320/62/0 without running pytest).
- **`superpowers-systematic-debugging`** (added 2026-05-15 per same; upstream `obra/superpowers` v5.1.0 MIT) — invoke when encountering ANY bug / test failure / unexpected behavior, BEFORE proposing fixes. Iron Law: "NO FIXES WITHOUT ROOT CAUSE INVESTIGATION FIRST". 4 phases: root-cause investigation → pattern analysis → hypothesis/testing → implementation. Closes gap in project's `.claude/skills/` — no `udm-*` skill addresses structured debugging methodology.

These are NOT enumerated per-scope above because they apply to ALL scopes (would be N×repetition).

**Optional upstream skill (per-scope conditional)**: `superpowers-tdd` (RED-GREEN-REFACTOR test-driven-development; upstream `obra/superpowers` v5.1.0) — recommended for PS-3 TOOL scope when introducing new executable code; complements `udm-test-author` parallel-agent pattern. Lower priority than the 2 always-mandatory superpowers-* imports per research recommendation.

### §2.5 Minimum viable skill set principle (v0.2 addition per Shape Up "appetite" + SkillsBench context-interference data)

**Binding for any planning session**: BEFORE activating ALL skills listed for a PS-N scope, assess the session's context budget + apply minimum-viable-set principle. Activate only skills DIRECTLY needed for the session's specific scope; defer applicable-but-not-immediately-needed skills to on-demand load.

**Rationale**: SkillsBench (arxiv 2602.12670) quantified context interference risk at -10% performance degradation when skills with conflicting conventions are simultaneously active. Shape Up's "appetite" concept (Basecamp's planning framework) explicitly bounds scope before execution rather than estimating; analogous discipline applies here — bound skill activation scope before session execution rather than activating defensively.

**Procedure**: at Step 3 of `udm-planning-session-startup` (surface skill list to user), surface TWO lists:
- **Active for THIS session** (minimum viable; activated immediately)
- **Available on-demand** (matrix-applicable but deferred; can be invoked mid-session if needed)

**Anti-pattern**: blanket-activating all 8+ matrix skills "to be safe" — risks context interference + dilutes the parent agent's attention across skills not actually needed.

### §2.6 Structural enforcement at end-of-prompt position (v0.2 addition per CodeCompass arxiv 2602.20048)

The CodeCompass Navigation Paradox study found agents skip tool invocation 58% of the time even with explicit prompt instructions UNLESS the activation checklist is placed at the END of the system prompt (Lost-in-the-Middle suppression effect). End-of-prompt position achieved 100% tool adoption vs 85.7% mid-prompt.

**Binding**: when `udm-planning-session-startup` SKILL.md Step 3 surfaces the skill activation list to the user, the list MUST appear at the END of the message (not buried mid-message). Similarly, when sub-agent prompts include the inheritance contract section per §3, the inheritance section MUST appear near the END of the prompt body (after the task description; before only edge-case notes).

**Implementation note**: this is a low-cost structural improvement with high empirical support. Existing skill prompts can be retrofitted at next round close-out via `udm-cascade-audit-evolver` proposal (B-280 candidate; pending recurrence).

### §2.7 Failure modes documented (v0.2 addition per Pattern E style; closes "why this exists" with multi-source rationale)

The academic literature consistently describes THREE failure modes this discipline addresses:

1. **Agent skips structured tool invocation when perceiving low task difficulty** (CodeCompass arxiv 2602.20048): on tasks where baseline strategies work ~80% of the time, the overhead of structured tool invocation is not justified per the agent's cost-benefit heuristic. Agents cannot distinguish in advance when the heuristic will fail (G3 hidden-dependency case). **Mitigation**: §2.6 end-of-prompt structural enforcement + §3 sub-agent inheritance contract removes the discretion.

2. **Skills with poor descriptions activate only ~20-50% of the time** (Anthropic official data, January 2026 Complete Guide): description quality directly determines activation reliability. **Mitigation**: §2.4 description-quality requirement (each matrix-referenced skill must reach "optimized + examples" tier; SkillReducer arxiv 2603.29919 found 26.4% of public skills lack any routing description = effectively invisible to auto-selection).

3. **Context interference from misapplied skills degrades performance by up to -10%** (SkillsBench arxiv 2602.12670): version-specific conventions conflict with target project framework when skills not designed for the task are simultaneously active. **Mitigation**: §2.5 minimum-viable-set principle + CLAUDE.md "Do NOT" rules as guard rails.

These failure modes REPLACE the 1-event evidence base from v0.1 — v0.2 grounds the discipline in multi-source empirical rationale.

### §2.4 Description-quality requirement (v0.2 addition per Anthropic activation data + SkillReducer arxiv 2603.29919)

Every skill referenced in the §2.2 matrix MUST have a SKILL.md description meeting Anthropic's "optimized + examples" tier (target: ~90% activation reliability). Required elements:

- **What the skill does**: 1-2 sentence functional summary
- **When to use it**: explicit trigger conditions (scope categories, task types, or natural-language phrases)
- **Trigger phrases**: at least 3 example phrases that would activate the skill
- **Anti-trigger guidance**: explicit phrases that should NOT activate the skill (anti-discoverability)
- **At least 1 example** of the skill's typical invocation pattern

**Audit cadence**: at every round close-out, invoke `udm-cascade-audit-evolver` to verify each matrix-referenced skill meets the description-quality requirement. SkillReducer's empirical finding (26.4% of public skills lack any routing description) suggests this audit is non-trivial; expect 1-3 skills per round needing description tightening.

**Anti-pattern caught**: skills with "Helps with X" -tier descriptions (effectively 0% activation per Anthropic data). The v0.1 of `udm-planning-session-startup` SKILL.md was authored with explicit trigger phrases; verify other matrix-referenced skills meet the same bar.

### §2.4-LEGACY Scope-classification edge cases

- **Plan scope unclear**: invoke `udm-brainstorm` FIRST to surface scope candidates; THEN re-invoke this skill with the brainstormed scope
- **Plan scope is "research only" (no execution)**: skip mandatory `udm-design-reviewer` + `udm-checks-and-balances`; invoke `udm-researcher` only; defer scope re-classification to when execution planning begins
- **Plan scope is "decision-redirect" (replacing existing D-N)**: PS-8 D-N category; ALSO Grep `docs/migration/03_DECISIONS.md` + `docs/migration/_validation_log.md` + `docs/migration/BACKLOG.md` for the existing D-N identifier (e.g., `D62`) to confirm full impact scope before recommending supersession. **Note**: planned `udm-find-canonical` skill (per MARKDOWN_REFACTOR_PLAN.md Phase 1.E candidate) would operationalize this lookup as a single-Skill invocation; **B-276** tracks its authoring.
- **Plan scope is "fix-only" (no new design)**: SKIP this skill entirely; treat as tactical edit; invoke `udm-next-step-cascade` post-commit

---

## §3. Sub-agent inheritance contract (binding per CLAUDE.md hard rule 13)

### §3.0 Anthropic official confirmation (v0.2 addition per B-279 research-grounding)

> "Subagents don't inherit skills from the parent conversation; you must list them explicitly. You can use the skills field to inject skill content into a subagent's context at startup."
>
> — Anthropic official Claude Code documentation, [code.claude.com/docs/en/sub-agents](https://code.claude.com/docs/en/sub-agents) (accessed 2026-05-15)

This sub-agent inheritance contract addresses an **officially-documented architectural gap** in Claude Code. The project's contract operationalizes the discipline at the prompt-template level since the project doesn't yet uniformly populate the `skills:` frontmatter field on sub-agent definitions. Future hardening: cascade-audit-evolver could propose auto-populating `skills:` frontmatter on existing sub-agent definitions at next round close-out (B-281 candidate; pending recurrence evidence).

### §3.1 The contract

When parent agent spawns a sub-agent via the Agent tool DURING a planning session, the sub-agent prompt MUST include the following section:

```markdown
## Planning-discipline skill inheritance (per CLAUDE.md hard rule 13)

You are operating within an active planning session with the following skills activated:

- **Mandatory skills you MUST apply within your scope**: <list from parent's active skill set>
- **Conditional skills available at your scope**: <list from parent's active skill set>

You do NOT need to re-invoke `udm-planning-session-startup` (parent agent already invoked it). Apply the listed skills throughout your work and cite invocations in your output per the parent's planning-session provenance contract.

If your work surfaces a need for a skill NOT in the inherited list, surface this to the parent agent (do NOT silently invoke).
```

### §3.2 Anti-patterns the contract closes

| Anti-pattern | Empirical evidence |
|---|---|
| Sub-agent spawned with terse prompt; skill discipline not propagated; sub-agent operates without discipline context | Markdown refactor session 2026-05-15: 3 parallel gap-audit agents spawned without explicit skill inheritance; verdicts converged but discipline application was uneven |
| Sub-agent silently invokes skill NOT in parent's active set; output deviates from parent's plan; parent has to reconcile | Hypothetical (not yet observed; preemptively closed) |
| Multiple sub-agents in cohort each independently re-discover skill list; redundant CCL Stage 1+2 reads inflate token cost | Markdown refactor session 2026-05-15: cumulative CCL cost for 3 parallel gap-audit agents was ~362K × 3 = ~1M tokens; inheritance contract reduces to ~362K total (parent does CCL once; sub-agents inherit) |

### §3.3 Inheritance scope

The contract applies to:

✅ **Sub-agents spawned via Agent tool** during a planning session (general-purpose, udm-researcher, udm-design-reviewer, udm-checks-and-balances, udm-test-author, etc.)

✅ **Parallel cohorts** (3+ sub-agents spawned in same parent message) — each sub-agent gets the same inheritance section

❌ **Skills the parent agent invokes itself** (parent doesn't need to inherit from itself; parent IS the activation source)

❌ **One-off tool calls** (Bash, Read, Edit, Grep, etc.) — these aren't agents

❌ **Sub-agents spawned OUTSIDE a planning session** (e.g., during tactical edit work; no active planning skill list to inherit)

### §3.4 Verification (post-cohort)

`udm-gap-check` extended (per `udm-cascade-audit-evolver` to land at next round close-out) with **G7 NEW category — sub-agent skill-inheritance audit**:

- For each sub-agent spawned during the planning session, verify the prompt included the inheritance section
- For each sub-agent output, verify cited skills are a subset of the parent's active skill set
- 🔴 if sub-agent invoked a skill not in parent's active set; surface as parent-side discipline gap
- 🟡 if inheritance section was present but malformed (missing list / typo / wrong skill name)
- ✅ CLEAN if all sub-agents inherited correctly

---

## §4. Plan-deliverable §0 provenance section (template + format)

Every plan deliverable authored under this discipline MUST include a §0 "Planning session provenance" section between the header and §1. Template:

```markdown
## §0. Planning session provenance

**Skill activation** (per `udm-planning-session-startup` skill invoked at session start; see `docs/migration/PLANNING_DISCIPLINE.md` for matrix):

**Scope**: PS-X <description> (PRIMARY) [+ PS-Y <description> (SECONDARY)]

**Mandatory skills invoked**:

| Skill | Invocation count | Timestamp(s) | Rationale |
|---|---|---|---|
| `udm-<name>` | N | YYYY-MM-DD HH:MM, ... | <why this scope needs this skill> |
| ... | ... | ... | ... |

**Conditional skills invoked**:

| Skill | Invocation count | Timestamp(s) | Trigger condition |
|---|---|---|---|
| `udm-<name>` | N | YYYY-MM-DD HH:MM | <gate that triggered the invocation> |
| ... | ... | ... | ... |

**Skills available but NOT invoked** (with rationale):

| Skill | Rationale for non-invocation |
|---|---|
| `udm-<name>` | <e.g., "scope doesn't introduce D-N candidates"> |

**Sub-agents spawned + skill inheritance**:

| Sub-agent type | Description | Spawned at | Skills inherited | Inheritance section present? |
|---|---|---|---|---|
| general-purpose | <description> | YYYY-MM-DD HH:MM | <list> | ✅ / 🟡 / 🔴 |
| ... | ... | ... | ... | ... |

**Planning-session attestation**:
- `udm-gap-check` independent reviewer verdict: ✅ CLEAN / 🟡 fixable inline / 🔴 escalate
- `udm-step-10-verifier` verdict (if new public surface): ✅ N/A / ✅ CLEAN / 🟡 IN-FLIGHT DRIFT
- `udm-checks-and-balances` 5-gate verdict (if D-N introduced): ✅ all gates pass / 🟡 gate N findings inline
- Pipeline-lead approval: ✅ Approved / 🔄 Redirect / ❌ Rejected
```

This section makes the audit trail VISIBLE in the plan deliverable. Future readers can immediately see WHICH disciplines were applied and which were skipped (with rationale).

---

## §5. Exemptions (when this discipline is N/A)

This discipline does NOT apply to:

- **Tactical edits** (single-file fixes; tracker updates; rename; cosmetic) — invoke `udm-next-step-cascade` instead
- **Status / clarifying questions** — no planning happens; just informational
- **Mid-plan redirects** (changing an in-flight plan) — apply the redirect; skills already activated remain active
- **Bug investigations** (root-cause analysis is not planning) — invoke `udm-design-reviewer` if architectural; otherwise just investigate
- **Build execution following an approved plan** — the planning skill list is already in §0; invoke `udm-next-step-cascade` for forward motion

If unsure: ask the user. Cost of asking < cost of wrong invocation.

---

## §6. Cross-references

- `udm-planning-session-startup` skill (`.claude/skills/udm-planning-session-startup/SKILL.md`) — the canonical activation skill
- CLAUDE.md hard rule 13 — binding directive for skill invocation + sub-agent inheritance
- `udm-next-step-cascade` (`.claude/skills/udm-next-step-cascade/SKILL.md`) — paired skill (post-commit timescale)
- `udm-round-closeout` (`.claude/skills/udm-round-closeout/SKILL.md`) — paired skill (round-end timescale; one of the PS-7 routed skills)
- `udm-gap-check` (`.claude/skills/udm-gap-check/SKILL.md`) — always-mandatory at attestation; extended with G7 sub-agent inheritance audit per §3.4
- `MULTI_AGENT_GUIDE.md` § Canonical Context Load (D62) — sub-agent CCL Stage 1+2 still mandatory; inheritance contract supplements (does not replace) CCL discipline
- `SELF_IMPROVEMENT_DISCIPLINE.md` — analogous process-discipline meta-doc (D95-D99 framework)
- `CHECKS_AND_BALANCES.md` — analogous 5-gate validation meta-doc (D55)
- HANDOFF §8 Pitfall #9 sub-class candidate 9.o: "skill-discoverability-not-applied-at-planning-session-start" (1-event evidence base 2026-05-15 + this doc's authoring is the structural fix; 3-event evidence base for formalization pending recurrence)

---

## §6.5 Counter-evidence + limits (v0.2 addition per research artifact §"Counter-Evidence")

Per the discipline of grounding (per `udm-researcher` invocation): present counter-evidence transparently.

1. **SWE-Skills-Bench moderates the SkillsBench +16.2pp claim** (arxiv 2603.15401): "skill utility is highly domain-specific and context-dependent, favoring targeted skill design over blanket adoption." Real-world SWE tasks may show lower gains than the SkillsBench benchmark suggests. Implication: the project's skill matrix should remain **highly targeted to domain-specific pipeline conventions** (BCP CSV contract, SCD2 patterns, Polars hashing) rather than expanding to general-purpose skills.

2. **Aider has no skill-matrix yet performs well on coding benchmarks**: mode-based selection without explicit skill matrix is a viable alternative architecture. Implication: skill-matrix is NOT universally required; it's most valuable when (a) domain knowledge is deep, (b) sub-agent topology is complex, (c) audit-grade traceability is required. The project meets all 3 conditions.

3. **CodeCompass 100% adoption was on simple task set** (G3 hidden-dependency; 31 trials): on simple tasks where baseline strategies succeed 80%+, structural enforcement may impose unnecessary overhead. Implication: not every planning session needs FULL skill activation; §2.5 minimum-viable-set principle (v0.2 addition) addresses this.

4. **METR algorithmic-vs-holistic measurement bias** (metr.org August 2025 research update): structured skill workflows may appear more effective partly because they're more amenable to algorithmic scoring. Real-world benefit may be harder to measure. The +16.2pp + +12.22% gains from curated skills should be interpreted as **upper bounds**, not guaranteed gains.

## §6.6 What this research does NOT cover (v0.2 addition)

- **Per-project skill effectiveness measurement**: whether the project's specific skills (udm-researcher, udm-design-reviewer, etc.) are achieving target activation rates. Requires internal instrumentation, not external research. **Action**: B-280 candidate (proposed at v0.2 commit) — empirical A/B measurement of PLANNING_DISCIPLINE.md v0.1 vs v0.2 over 5 sessions; compare missed-skill frequency.
- **Optimal number of PS-N scope categories**: research supports hierarchical categorization but doesn't speak to whether 9 categories is right. GoalAct used 3 high-level skills; Cursor uses 4 activation modes. **Action**: monitor matrix usage over next 5 sessions; if certain PS codes never get invoked, consolidate at next round close-out.
- **Long-term context interference accumulation**: SkillsBench measured single-session interference. The project's planning discipline applies across multi-day sessions. Drift effects over longer timescales are not studied.

## §7. Empirical evidence base + evolution

**1-event evidence base** (2026-05-15 markdown refactor planning session):
- 4 skills not invoked: `udm-design-reviewer` / `udm-checks-and-balances` / `udm-execution-classifier` / `udm-decision-recorder`
- Surfaced via independent `udm-gap-check` reviewer on commit `1b00755` post-hoc remediation
- Pipeline-lead authorization for structural intervention: 2026-05-15 via AskUserQuestion ("A+B+C full intervention Recommended")

**Pending evolution triggers** (track at next round close-out via `udm-cascade-audit-evolver`):
- 2nd-event: any planning session where matrix-lookup produces SURPRISING skill list (skills the parent agent wouldn't have invoked from memory)
- 3rd-event: any planning session where sub-agent inheritance contract catches a discipline gap (G7 finding)
- Formalization trigger: 3-event evidence base → HANDOFF §8 Pitfall #9 sub-class 9.o canonical formalization

**Matrix evolution mechanism**:
- New scope categories (PS-10+) added via B-N at next round close-out + udm-cascade-audit-evolver review
- New skills added to matrix rows at skill-creation time (whoever adds a new skill SHOULD update matrix; verified at next round close-out cascade)
- Skill removal (rare): supersession + 2-cycle deprecation per D92 forward-only schema-evolution analog

---

## §8. Self-application (this document's own provenance)

Per Pitfall #9.m "discipline-applied-to-its-own-tracker" sub-class: this document's authoring session IS a planning session (PS-1 ARCH + PS-9 SELF + PS-8 D-N for hard rule 13). The skills that SHOULD have been invoked per §2.2 are:

| Skill | Invoked during this authoring? | Notes |
|---|---|---|
| `udm-design-reviewer` (PS-1 mandatory) | ❌ deferred to user review (user IS the design reviewer for this meta-doc) | Pragmatic exemption: meta-docs are inherently reviewer-blocked-on-user |
| `udm-checks-and-balances` (PS-1 + PS-2 mandatory) | ❌ deferred to next round close-out 5-gate validation | Plan deliverable §0 provenance will track |
| `udm-researcher` (PS-1 mandatory) | ❌ not invoked (didn't ground in external primary sources) | Pragmatic exemption: structural intervention informed by 1-event session evidence, not industry-standard research; future iteration could ground via `udm-researcher` |
| `udm-decision-recorder` (PS-8 mandatory) | ⚠️ deferred to next round close-out per D111 process-infra exemption | Hard rule 13 IS the D-N candidate; will lock at next close-out via `udm-decision-recorder` |
| `udm-step-10-verifier` (post-build) | ✅ will invoke at end-of-commit | New public surface = the `udm-planning-session-startup` skill itself |
| `udm-gap-check` (post-build) | ✅ will invoke at end-of-commit | Independent reviewer |
| `udm-progress-logger` (throughout) | ✅ tracker pass at end-of-commit | 5 canonical trackers + per-build-type checklist |

**Self-referential discipline acknowledgment**: this document's authoring is itself the FIRST production application of the discipline it describes. Pragmatic exemptions (design-reviewer, researcher) are documented above. Next planning session (after this lock) is the first NON-self-referential application.
