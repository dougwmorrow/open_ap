---
name: udm-producer-checklist-evolver
description: Identifies bug classes reviewers consistently catch that producer Gate 1 self-check missed; proposes strengthening producer pre-flight directives (HANDOFF §8 sub-class directives + spec doc § 1.5 walks). Threshold: ≥3 producer-missable instances in ≥2 rounds → 🟡 propose directive strengthening. ≥5 in ≥3 rounds → 🔴 propose elevation to Gate 2 mandatory specialty. Invoked AFTER `udm-retrospective-collector` + `udm-subclass-accumulator`; per Round 8 D95.
---

# UDM Producer Checklist Evolver

Fourth close-out analysis skill. Closes the producer-side gap by shifting catches from reviewer Gate 2 to producer Gate 1 over time.

## When to invoke

- Every round close-out, AFTER `udm-retrospective-collector` + `udm-subclass-accumulator`
- Position: 4th of 7 close-out skills (3rd of 5 analysis skills; per `udm-round-closeout` Section 10.4 NEW)
- Skip if `_reviewer_effectiveness.md` has < 3 rounds of post-seed data

## Canonical Context Load (CCL) per D62

- **Stage 0**: `docs/migration/INDEX.md` (routing manifest; recommended-not-mandatory; added 2026-05-15 per D62 amendment + D.2 INDEX.md per MARKDOWN_REFACTOR_PLAN.md §7.1 task 1.3; read FIRST when uncertain which downstream Stage 1+2+3 docs your task needs; skip when you already know).
- **Stage 1**: `NORTH_STAR.md` + `HANDOFF.md` (§8 sub-class directives + producer self-check section) + `CURRENT_STATE.md` + `CHECKS_AND_BALANCES.md`
- **Stage 2**: `RISKS.md` + `BACKLOG.md` + `_validation_log.md` (current round)
- **Stage 2.5**: `POLISH_QUEUE.md` (added 2026-05-12 per D113) — proposed producer-checklist deltas that ONLY cover cosmetic-discipline (status-render verification, supersession-crumb authoring, stale-date refresh) may land as P-N seed items rather than as B-N items. Distinguishing test: does the proposed checklist delta change WHAT the producer does (substantive) or HOW the producer renders it (cosmetic)? Substantive → B-N candidate per §8 directive evolution; cosmetic-only → P-N candidate per D113.
- **Stage 3**: `_reviewer_effectiveness.md` (specialty-to-sub-class correlation); existing spec doc § 1.5 producer self-check templates (e.g., `phase1/08_sub_agent_self_improvement.md` § 1.5)
- **Stage 4**: grep prior producer-checklist-evolver outputs at `docs/migration/_agent_evolution/`

## Gap-detection algorithm

For each Round N 🔴 finding:

1. **Find catching reviewer specialty** (from `_reviewer_effectiveness.md` per agentId)
2. **Look up canonical producer self-check**:
   - HANDOFF §8 sub-class directive (e.g., 9.a says "walk canonical columns")
   - Spec doc § 1.5 walk (e.g., R8 § 1.5 enumerates 9.a-9.j)
3. **If producer self-check could have caught this** (the finding maps to a sub-class with a directive):
   - Cluster by missed-sub-class
   - If sub-class is missed-by-producer ≥3 times across 2+ rounds → propose strengthening
4. **If only a reviewer specialty could have caught this** (e.g., advisory-research external-evidence framing):
   - Tag as "reviewer-only specialty class"; skip

## Threshold

- ≥3 producer-missable misses in ≥2 rounds → 🟡 propose directive strengthening
- ≥5 producer-missable misses in ≥3 rounds → 🔴 propose elevation (e.g., make sub-class a hard pre-flight gate; convert "verify each is canonical" wording to "verify each is canonical AND cite the line-anchor")

## Output contract

Markdown file at `docs/migration/_agent_evolution/producer-checklist-evolver-round<N>-<YYYY-MM-DD>.md`:

```markdown
# Producer Checklist Evolver Output — Round N

## Date: YYYY-MM-DD
## Confidence: HIGH/MEDIUM/LOW

## Producer-missable 🔴 findings this round (and prior rounds with sub-class match)

### Sub-class 9.a — column-name drift
- Round N cycle X: <count> instances (caught by column-walk)
- Cumulative across rounds: <count>
- Producer self-check: HANDOFF §8 9.a directive — says "<current directive text>"
- **Gap**: <specific weakness in current directive>
- **Proposed delta**: <strengthening>

## Proposed directive strengthenings: <count>

## Reviewer-only classes (no producer self-check possible)

- Advisory-research framing (e.g., B156 SRE inversion)
- Cross-doc cascade gaps (Pattern F catches these — not producer surface)

## User review required: YES / NO
```

## Edge cases

- **SI7** (producer self-check exhausted): if a sub-class has 5+ producer-missable instances AND the existing directive is already comprehensive (4-5 steps), propose ELEVATION to Gate 2 mandatory specialty rather than directive strengthening
- **SI8** (producer self-check over-fires false-positives): if a directive declines valid patterns (skill detects via reviewer agreeing with producer's pre-flight pass), note "directive over-fires; consider relaxing"

## Confidence calibration

| Evidence | Confidence |
|---|---|
| ≥5 missable findings ≥3 rounds | HIGH |
| ≥3 missable findings ≥2 rounds | MEDIUM |
| 1-2 findings, 1 round | LOW (recommendation: MONITOR not REFINE) |

## Composition

| Used with | Role |
|---|---|
| `udm-subclass-accumulator` | Identifies NEW sub-classes; this skill identifies WHICH existing sub-class directives need strengthening |
| `udm-agent-prompt-versioner` | Applies approved deltas |
| HANDOFF §8 sub-class accumulator | Canonical home for sub-class directives (this skill proposes additions to existing entries) |

## Tier 0 stub (per D67)

`tests/smoke/test_skill_producer_checklist_evolver.py`. Verifies:
- Skill imports
- Producer-missable finding clustered correctly
- Reviewer-only class flagged separately
- Threshold logic (3+ in 2 rounds → REFINE; 5+ in 3 rounds → ELEVATE)

## Cross-references

- D95 (umbrella)
- `docs/migration/phase1/08_sub_agent_self_improvement.md` § 5
- HANDOFF §8 sub-class accumulator + producer self-check directive
- `_reviewer_effectiveness.md`

## Owner

Pipeline lead.
