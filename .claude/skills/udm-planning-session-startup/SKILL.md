---
name: udm-planning-session-startup
version: 0.2.0
description: Operationalizes the planning-session-startup protocol — invoked at the START of any planning session (architectural, doc-refactor, new-tool, new-SP, new-runbook, multi-agent cohort, round close-out, D-N-introducing, self-improvement). Walks the skill-selection matrix at `docs/migration/PLANNING_DISCIPLINE.md`; surfaces the chosen skill list to the user for approval/redirect; ensures sub-agents inherit the skill list per Anthropic's official Claude Code sub-agent doc (sub-agents don't auto-inherit; code.claude.com/docs/en/sub-agents). Trigger phrases include "Let's plan", "Plan for", "Design X", "Refactor effort", "Come up with a quality plan". Anti-triggers: questions about existing plans, mid-plan redirects, tactical edits. Closes the gap that markdown refactor planning 2026-05-15 surfaced — 4 skills were not invoked that should have been (udm-design-reviewer / udm-checks-and-balances / udm-execution-classifier / udm-decision-recorder). v0.2 grounded in 5 primary sources (Anthropic official docs + SkillsBench arxiv 2602.12670 + CodeCompass arxiv 2602.20048 + GoalAct arxiv 2504.16563 + Anthropic Complete Guide January 2026) per B-279 closure. Example trigger: "Let's plan a refactor of the markdown files" → activates the skill → walks 5-step procedure.
---

# UDM Planning Session Startup

User-invocable + auto-fire skill that operationalizes the planning-session startup protocol. Pairs with `udm-next-step-cascade` (post-commit forward-motion + verification) and `udm-round-closeout` (round-end cascade) to form the canonical lifecycle: **startup → forward-motion → close-out**.

## CRITICAL — when to invoke

This skill ONLY fires when the user's MOST RECENT message contains an explicit planning-intent trigger phrase. **NEVER invoke as a default behavior** when the user asks a question or makes a tactical edit request.

### Trigger phrases (case-insensitive; user's message must contain ONE)

- "Let's plan ..." / "let's come up with a plan for ..."
- "Plan for ..." / "I want to plan ..."
- "Design X" (where X is non-trivial; small UI tweaks don't count)
- "Refactor effort for ..." / "refactor plan for ..."
- "Come up with a quality plan ..." / "come up with a strategy ..."
- "How should we approach ..." (paired with non-trivial scope)
- "Architectural plan for ..." / "spec out ..."
- "What's our approach to ..." (paired with implementation question)

### Anti-triggers (do NOT invoke even if a trigger-like phrase appears)

- User asking a question about an existing plan ("what's in the plan?" / "did we plan for X?")
- User redirecting an in-flight plan ("change the plan to do Y instead")
- User invoking a tactical edit ("update plan file X with Y")
- User invoking a different skill standalone (`/udm-planning` for round decomp; `/udm-brainstorm` for design alternatives)
- User saying "stop" / "pause" / "wait"

When in doubt: **ASK the user to clarify** rather than invoking. Cost of asking < cost of invoking the wrong skill.

## 5-step procedure

### Step 1 — Identify planning scope

Classify the planning task along ONE of these 9 scope categories (per `docs/migration/PLANNING_DISCIPLINE.md` §2 matrix; multi-scope plans pick PRIMARY scope):

| Scope code | Description | Examples |
|---|---|---|
| **PS-1 ARCH** | Architectural plan touching pipeline core / CCL doctrine / schema / security | Phase round structure; new module family; security model change |
| **PS-2 DOC** | Doc-refactor / structural / markdown-hygiene plan | Markdown refactor; CCL reduction; spec doc reorganization |
| **PS-3 TOOL** | New tool / executable script (one-shot or recurring) | Operator CLI; migration script; meta-tooling for measurement |
| **PS-4 SP** | New stored procedure / DDL change / schema evolution | SP-N addition; column ALTER; SchemaContract row |
| **PS-5 RUNBOOK** | New runbook (RB-N) | Operational procedure; recovery runbook |
| **PS-6 COHORT** | Multi-agent cohort spawn | Parallel agent work (3+ sub-agents) |
| **PS-7 CLOSEOUT** | Round close-out | End of Phase round; self-improvement cascade |
| **PS-8 D-N** | Plan introducing D-N candidates | Decision documentation; policy lock |
| **PS-9 SELF** | Self-improvement family (skill / agent prompt / discipline) | Producer-checklist evolution; sub-class accumulation; cascade-audit-evolver |

If multi-scope (most plans are): pick PRIMARY + note SECONDARY scopes for matrix lookup.

### Step 2 — Look up applicable skills via matrix

Read `docs/migration/PLANNING_DISCIPLINE.md` §2 skill-selection matrix. Extract the row(s) for the identified scope(s). The matrix specifies:

- **Mandatory at session start**: skills to invoke BEFORE any planning content is authored
- **Conditional during session**: skills to invoke at specific gates during the session
- **When to invoke**: timing specification for each conditional skill

For multi-scope plans: union of all scope rows' skill lists (de-duplicated).

### Step 3 — Surface skill list to user with rationale

Emit a markdown block to the user enumerating:

```markdown
## Planning session startup — skill activation

**Scope**: PS-X <description> (and optionally PS-Y secondary)

**Mandatory skills to invoke at session start**:
- `udm-<skill-name>` — <rationale: why this scope needs this skill>
- ...

**Conditional skills to invoke during session**:
- `udm-<skill-name>` — invoke when: <gate condition>
- ...

**Sub-agent inheritance**: when sub-agents are spawned during this session (e.g., via Agent tool), their prompts MUST include explicit "use these skills" section listing the above (per CLAUDE.md hard rule 13 sub-agent inheritance contract).

**Approve this skill activation? Redirect? Add/remove specific skills?**
```

User responds. If approve → proceed. If redirect → re-classify scope OR adjust skill list per user direction. If add/remove → adjust + re-confirm.

### Step 4 — Apply skills throughout planning session

As the planning session unfolds, invoke each mandatory + conditional skill at the appropriate moment per the matrix's "When to invoke" specification.

Each invocation MUST be cited in the plan deliverable (see Step 5) so the audit trail of which skills were used is preserved. Citation format: `[<skill-name> invoked YYYY-MM-DD per matrix scope PS-X]`.

### Step 5 — Emit §0 provenance section into plan deliverable

The plan deliverable (e.g., `MARKDOWN_REFACTOR_PLAN.md`, `PHASE_X_DEEP_DIVE_PLAN.md`, etc.) MUST include a §0 "Planning session provenance" section near the top (between header + §1). Format:

```markdown
## §0. Planning session provenance

**Skills invoked during this planning session** (per `udm-planning-session-startup` skill at session start; see `docs/migration/PLANNING_DISCIPLINE.md` for matrix):

| Skill | Invoked at | Scope reference | Rationale |
|---|---|---|---|
| `udm-design-reviewer` | YYYY-MM-DD HH:MM | PS-1 ARCH mandatory | Plan touches CCL doctrine + skill prompts → architectural review pre-implementation |
| `udm-checks-and-balances` | YYYY-MM-DD HH:MM | PS-1 + PS-8 mandatory | 5-gate validation at plan attestation |
| `udm-researcher` | YYYY-MM-DD HH:MM (× 6) | PS-1 + PS-2 mandatory | Primary-source grounding for industry standards |
| ... | ... | ... | ... |

**Sub-agents spawned + skill inheritance**:

| Sub-agent | Spawned at | Skills inherited (per CLAUDE.md hard rule 13) |
|---|---|---|
| general-purpose (gap-audit) | YYYY-MM-DD HH:MM | udm-design-reviewer + udm-checks-and-balances |
| udm-researcher (em-dash test) | YYYY-MM-DD HH:MM | (none — researcher is itself a leaf skill) |
| ... | ... | ... |
```

This §0 section makes the audit trail VISIBLE in the plan deliverable itself (not just in trackers). Future readers of the plan can immediately see which disciplines were applied + which were skipped.

## Output contract

After Step 1-3 complete, parent agent emits the markdown block from Step 3 + awaits user approval. After Step 4-5 complete throughout the planning session, the plan deliverable has §0 provenance section.

## Sub-agent skill inheritance contract (binding per CLAUDE.md hard rule 13)

When the parent agent spawns a sub-agent via the Agent tool for planning work, the sub-agent prompt MUST include:

```markdown
## Planning-discipline skill inheritance (per CLAUDE.md hard rule 13)

You are operating within an active planning session with the following skills activated:

- **Mandatory skills you MUST apply within your scope**: <list>
- **Conditional skills available at your scope**: <list>

You do NOT need to re-invoke `udm-planning-session-startup` (parent agent already invoked it). Apply the listed skills throughout your work and cite invocations in your output per the parent's planning-session provenance contract.

If your work surfaces a need for a skill NOT in the inherited list, surface this to the parent agent (do NOT silently invoke).
```

This contract closes the multi-agent dimension: sub-agents don't have to discover the right skills independently; the parent agent inherits the activation context to them explicitly.

**Anti-pattern**: spawning a sub-agent with a terse prompt that omits the skill inheritance section. Sub-agent then operates without discipline context; output may miss the matrix's required skills. Caught by `udm-gap-check` post-cohort (G7 NEW category — sub-agent skill-inheritance audit) but better caught at spawn time.

## Examples

### Example 1 — Trigger present (architectural planning)

```
User: "Let's plan a refactor of the markdown files."
Parent agent: [Invokes udm-planning-session-startup]
  Step 1: Identify scope → PS-2 DOC (primary) + PS-1 ARCH (secondary: touches CCL doctrine)
  Step 2: Matrix lookup → mandatory skills (udm-checks-and-balances + udm-researcher + udm-design-reviewer); conditional (udm-execution-classifier + udm-decision-recorder + udm-cascade-audit-evolver)
  Step 3: Surface to user with rationale; await approval
  [User: "approve"]
  Step 4: Apply skills throughout session (cite each invocation)
  Step 5: Emit §0 provenance into plan deliverable
```

### Example 2 — Trigger present (round close-out)

```
User: "Let's wrap up Round 8 and run the close-out."
Parent agent: [Invokes udm-planning-session-startup]
  Step 1: Identify scope → PS-7 CLOSEOUT
  Step 2: Matrix lookup → mandatory (udm-round-closeout); conditional (udm-cascade-auditor + udm-progress-logger + self-improvement family per Section 10)
  Step 3-5: as above
```

### Example 3 — Anti-trigger (question)

```
User: "What was in the Phase 2 plan again?"
Parent agent: [Does NOT invoke this skill]
  Answers the question by reading the plan file.
  Does NOT invoke any planning protocol — this is informational.
```

### Example 4 — Anti-trigger (mid-plan redirect)

```
User: "Change the plan: skip Phase D.1 since it's blocked."
Parent agent: [Does NOT re-invoke this skill]
  This is a mid-plan redirect, not a new planning session. Apply the redirect directly.
  Skills already activated remain active.
```

### Example 5 — Ambiguous → ask

```
User: "We should think about how to handle X."
Parent agent: [Asks for clarification]
  "Should we open a quick planning session for X (would invoke udm-planning-session-startup) OR is this a question for udm-brainstorm (design alternatives only)?"
```

## Edge cases

- **Plan deliverable doesn't exist yet at Step 5**: defer §0 provenance to first plan-authoring write. If plan is authored across multiple commits, §0 lands in the first plan-deliverable commit.
- **Plan deliverable already exists from prior session (no §0 yet)**: backfill §0 at next plan revision commit. Flag as Pitfall #9.m candidate (discipline-applied-retroactively).
- **Scope ambiguous between 2+ PS categories**: pick PRIMARY + note SECONDARY; matrix lookup unions the rows.
- **No applicable skills for the scope**: edge case; if scope is truly outside the matrix, propose new scope category (PS-10+) via B-N at next round close-out for udm-cascade-audit-evolver consideration.
- **User skips Step 3 approval (just says "go")**: treat as approval; proceed with default matrix output.
- **Mid-session scope change (e.g., plan grows from PS-2 DOC to also include PS-3 TOOL because new tools are introduced)**: re-invoke Step 1-3 at the scope-change moment; add newly-mandatory skills to the active list; cite the scope change in §0 provenance with timestamp.

## Composition

| Used with | Role |
|---|---|
| `docs/migration/PLANNING_DISCIPLINE.md` | Step 2 matrix lookup |
| `udm-next-step-cascade` | Pairs at post-commit timescale; this skill is the PRE-work analog |
| `udm-round-closeout` | One of the PS-7 skills the matrix routes to |
| `udm-planning` | One of the conditional skills for PS-1 ARCH (round decomposition) |
| `udm-brainstorm` | Optional conditional skill for any scope (design alternatives) |
| `udm-design-reviewer` | Mandatory for PS-1 ARCH / PS-4 SP / PS-5 RUNBOOK |
| `udm-checks-and-balances` | Mandatory for PS-1 ARCH / PS-2 DOC / PS-5 RUNBOOK / PS-8 D-N |
| `udm-execution-classifier` | Mandatory for PS-3 TOOL (any plan introducing new executable) |
| `udm-decision-recorder` | Mandatory for PS-8 D-N |
| `udm-runbook-author` | Mandatory for PS-5 RUNBOOK |
| `udm-data-engineer-review` | Mandatory for PS-4 SP (pipeline-touching) |
| `udm-test-author` | Mandatory for PS-3 TOOL + PS-4 SP (test sketches at spec time) |
| `udm-researcher` | Conditional for any scope needing primary-source grounding |
| `udm-gap-check` | Mandatory at planning-session attestation (post-substantive-work per CLAUDE.md hard rule 11) |
| `udm-step-10-verifier` | Mandatory if planning session introduces new public surface (modules / tools / EventTypes / SPs) |
| `udm-progress-logger` | Throughout — mid-session tracker updates |

## Confidence calibration

| User message contains | Confidence to invoke |
|---|---|
| Exact-match trigger phrase ("Let's plan a refactor of X") | HIGH ✅ INVOKE |
| Strong paraphrase ("I want to design Y") | HIGH ✅ INVOKE |
| Weak paraphrase ("Should we think about Z?") | MEDIUM 🟡 ASK first |
| Question / status / clarification | HIGH ✅ DO NOT INVOKE |
| Mid-plan redirect or tactical edit | HIGH ✅ DO NOT INVOKE |

When confidence is MEDIUM 🟡, ALWAYS ask. Cost of asking < cost of unauthorized planning protocol.

## Tier 0 stub (per D67)

`tests/tier0/test_skill_planning_session_startup.py` (Tier 1 if more complex). Verifies:
- Skill SKILL.md imports / parses as valid markdown
- 9 PS-N scope codes documented
- Trigger-phrase matcher rejects empty / single word / questions
- Trigger-phrase matcher accepts canonical phrases (case-insensitive)
- Anti-trigger matcher rejects mid-plan-redirect + status questions
- Matrix lookup returns non-empty skill list for each of 9 PS codes
- Sub-agent inheritance contract section present + correctly formatted
- §0 provenance schema example renders correctly

## Cross-references

- User-direction 2026-05-15: "What skills should agents use when planning? How do we ensure agents, sub-agents, multi-agent teams use those skills from the start?"
- Evidence base: markdown refactor planning session 2026-05-15 missed 4 skills (udm-design-reviewer / udm-checks-and-balances / udm-execution-classifier / udm-decision-recorder); independent gap-check on commit `1b00755` surfaced this
- `docs/migration/PLANNING_DISCIPLINE.md` — skill-selection matrix (canonical lookup source)
- CLAUDE.md hard rule 13 — binding directive for this skill + sub-agent inheritance contract
- `.claude/skills/udm-next-step-cascade/SKILL.md` — paired skill (post-commit timescale)
- `.claude/skills/udm-round-closeout/SKILL.md` — paired skill (round-end timescale)
- HANDOFF §8 Pitfall #9 sub-class candidate 9.o: "skill-discoverability-not-applied-at-planning-session-start" (3-event evidence base candidate; pending formalization at next round close-out if pattern recurs)

## Owner

Pipeline lead. First production invocation expected: next planning session triggered by user (e.g., when planning Phase 3 deep-dive OR when scoping a Round 6 follow-up effort OR when designing a new tool).
