---
name: udm-brainstorm
description: Explores design alternatives for an open architectural question before code or schema is written. Use when a question has more than one defensible answer (e.g. "how should we represent X?", "what's the failure mode for Y?", "is Z the right scope?"). Force-enumerates options, names trade-offs, recommends one. Inspired by Superpowers `brainstorming` discipline (`obra/superpowers` v5.1.0 — https://github.com/obra/superpowers/blob/main/skills/brainstorming/SKILL.md ; MIT licensed); evolved for UDM with NORTH_STAR pillar scoring + mandatory D-number / edge-case cross-ref + "It depends is not an answer" explicit-recommendation rule. See `docs/migration/_research/superpowers-framework-2026-05-15.md` §5 deep-dive comparison.
---

# UDM Design Brainstorm

Use this skill when facing an open design question. Force three or more alternatives even when one seems obvious — second-best alternatives often expose risks the obvious choice didn't.

## When to use

- Before drafting a new decision (D-number) in `03_DECISIONS.md`
- Before adding a new edge case to `04_EDGE_CASES.md`
- When a runbook procedure has multiple defensible paths
- When a schema design choice has trade-offs that aren't obviously resolved
- When the user asks "what should we do about X?"

## Canonical Context Load (CCL) — required before invoking this skill (per D62)

Whoever invokes this skill (main agent or subagent) MUST have performed the Canonical Context Load (per `docs/migration/MULTI_AGENT_GUIDE.md` § Canonical Context Load) before generating alternatives.

- **Stage 0 — Routing manifest** (recommended-not-mandatory; added 2026-05-15 per D62 amendment + D.2 INDEX.md per MARKDOWN_REFACTOR_PLAN.md §7.1 task 1.3): `docs/migration/INDEX.md` — read FIRST when uncertain which downstream Stage 1+2+3 docs your task actually needs. Skip when: you already know which Stage 1+2+3 docs to load (typical for recurring task patterns).
- **Stage 1 — Orientation** (mandatory, 4 reads): `NORTH_STAR.md` (re-read — every option must be scored against pillar implications), `HANDOFF.md`, `CURRENT_STATE.md`, `CHECKS_AND_BALANCES.md`
- **Stage 2 — Risk + Backlog awareness** (mandatory): `RISKS.md` (each option may create / mitigate a risk), `BACKLOG.md`, `_validation_log.md`
- **Stage 3 — Task-specific reads for this skill**: `03_DECISIONS.md` (existing decisions on the topic — DON'T re-decide); `04_EDGE_CASES.md` (related cases the option creates or solves)
- **Stage 4 — Reference-on-demand**: external research via `udm-researcher` agent for grounding option scoring

If invoked from a subagent context, the subagent's CCL responsibility is hard-required (per agent definition — first `Read` must hit a Stage 1 doc).

## Output structure

```
QUESTION: <one sentence>

CONTEXT:
- Why this question is open
- Existing decisions or edge cases that constrain the answer
- Cost-of-being-wrong assessment

OPTIONS:
1. <Option A name>
   - Description: <2-3 sentences>
   - Pros: <bullets>
   - Cons: <bullets>
   - Cost to implement: <small/medium/large>
   - Reversibility: <reversible / one-way / hard>
   - Edge cases it creates or solves: <IDs>
   - Decisions it touches: <D-numbers>

2. <Option B>
   ...

3. <Option C>
   ...

(force at least 3 even when 2 are obvious; the third option often reveals the reasoning)

RECOMMENDATION: Option <X>
JUSTIFICATION: <2-3 sentences citing specific trade-offs>

NEXT STEPS:
- If Option X locks: which docs/decisions to update
- Open questions that remain
- What would reverse this recommendation
```

## Hard rules

1. **Always enumerate at least 3 options.** Two-option framings ("do X or don't") miss alternatives.
2. **Each option must have a real downside.** If you can't name a downside, you don't understand the option yet.
3. **Recommend explicitly.** "It depends" is not an answer. If genuinely uncertain, recommend the least-reversible-option-with-most-info-gathered ("pick the one that lets us decide later").
4. **Cite existing decisions and edge cases.** Don't brainstorm in isolation; the project has 46+ decisions and 120+ edge cases that already constrain answers.
5. **Cost / reversibility matter more than apparent quality.** A "second-best" reversible decision often beats a "best" one-way one.
6. **Locked-D-number guard (added 2026-05-17 per B-413 closure + Cohort A Agent 54 BS-2 finding)**: BEFORE emitting RECOMMENDATION, verify that the recommended option does NOT contradict any 🟢 Locked decision in `03_DECISIONS.md`. If any recommended option directly contradicts a locked D-N, it CANNOT be the recommendation without an explicit D-N supersession process per D92 forward-only schema discipline. The brainstorm output must either (a) supersede the locked D-N through a new D-N candidate following `udm-decision-recorder` discipline, OR (b) recommend a different option that respects the locked decision. Closes the attack surface where a fast-moving brainstorm could undermine locked architectural choices.

## Anti-patterns

- ❌ "Let me think about it" (no options enumerated)
- ❌ Only listing options that all amount to the same thing (e.g. three flavors of MERGE)
- ❌ Recommending without citing the trade-off that drove the choice
- ❌ Brainstorming a question that's already been decided (check `03_DECISIONS.md` first)

## Project-specific framing

Most of our open questions live at one of these intersections:
- Schema vs runbook (data structure vs procedural fix)
- Pipeline vs operator (automate vs manual)
- Phase 1 vs deferred (foundation vs later phase)
- Idempotent vs simple (correctness vs implementation cost)

Identify which intersection your question sits at; the recommendation often follows from the intersection's bias (we always favor: schema over runbook for invariants, pipeline over operator for repeatable work, idempotent over simple per D15).

## Example invocation

User: "Should we add a `_pii_key_version` column on every table that holds tokens, or only PiiVault?"

Output: 3 options (only-vault / every-table / version-table-with-FK), each with pros/cons/cost/reversibility/edge cases (P2, D7), recommend one, list what would reverse it.
