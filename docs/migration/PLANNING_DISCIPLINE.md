# UDM Planning Discipline — skill-selection matrix + sub-agent inheritance contract

**Status**: 🟢 **Locked 2026-05-15** per D111 process-infra exemption (analogous to D55 / D60 / D89-D91 / D95-D99 / D113 — process-discipline meta-docs don't gate on 🟡-first attestation when the discipline they encode is itself first-event-evidenced and pipeline-lead approved).

**Owner**: Pipeline lead. Maintainers: `udm-planning-session-startup` skill + `udm-cascade-audit-evolver` (for matrix evolution at round close-out).

**Purpose**: Single canonical reference for (a) which skills should be invoked during which type of planning session, (b) how sub-agents inherit the parent's skill activation context, (c) the §0 provenance section format for plan deliverables. Closes the gap surfaced 2026-05-15 by the markdown refactor planning session (4 skills were not invoked that should have been: `udm-design-reviewer` / `udm-checks-and-balances` / `udm-execution-classifier` / `udm-decision-recorder`).

---

## §1. Why this exists (gap evidence + structural intervention rationale)

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

These are NOT enumerated per-scope above because they apply to ALL scopes (would be N×repetition).

### §2.4 Scope-classification edge cases

- **Plan scope unclear**: invoke `udm-brainstorm` FIRST to surface scope candidates; THEN re-invoke this skill with the brainstormed scope
- **Plan scope is "research only" (no execution)**: skip mandatory `udm-design-reviewer` + `udm-checks-and-balances`; invoke `udm-researcher` only; defer scope re-classification to when execution planning begins
- **Plan scope is "decision-redirect" (replacing existing D-N)**: PS-8 D-N category; ALSO Grep `docs/migration/03_DECISIONS.md` + `docs/migration/_validation_log.md` + `docs/migration/BACKLOG.md` for the existing D-N identifier (e.g., `D62`) to confirm full impact scope before recommending supersession. **Note**: planned `udm-find-canonical` skill (per MARKDOWN_REFACTOR_PLAN.md Phase 1.E candidate) would operationalize this lookup as a single-Skill invocation; **B-276** tracks its authoring.
- **Plan scope is "fix-only" (no new design)**: SKIP this skill entirely; treat as tactical edit; invoke `udm-next-step-cascade` post-commit

---

## §3. Sub-agent inheritance contract (binding per CLAUDE.md hard rule 13)

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
