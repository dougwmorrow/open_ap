---
name: udm-specialty-tuner
description: At round close-out, reads `docs/migration/_reviewer_effectiveness.md` trend tables; identifies reviewer specialties needing prompt refinement; proposes structured deltas for user review. Conservative bias — recommends "no action" unless thresholds unambiguously crossed (false-clean rate > 25% over ≥4 events for RETIRE-OR-PAIR; > 10% over ≥6 events for REFINE). Empirical ground: column-walk 0% over 7 events (NO ACTION); comprehensive-5-gate 2/8 = 25% (REFINE candidate). Invoked AFTER `udm-retrospective-collector` has appended the latest round; per Round 8 D95 + D97.
---

# UDM Specialty Tuner

Second close-out analysis skill. Identifies reviewer specialties with degrading effectiveness over time + proposes prompt refinements at structured-delta-with-user-review cadence.

## When to invoke

- Every round close-out, AFTER `udm-retrospective-collector` has appended current round's events
- Position: 2nd of 7 close-out skills (1st of 5 analysis skills; per `udm-round-closeout` Section 10.2 NEW)
- Skip if `_reviewer_effectiveness.md` has < 3 rounds of post-seed data (insufficient evidence)

## When NOT to invoke

- Mid-round (effectiveness analysis needs full-cycle data per round)
- If user has FROZEN the self-improvement loop per SELF_IMPROVEMENT_DISCIPLINE.md § Bounds

## Canonical Context Load (CCL) per D62

- **Stage 0**: `docs/migration/INDEX.md` (routing manifest; recommended-not-mandatory; added 2026-05-15 per D62 amendment + D.2 INDEX.md per MARKDOWN_REFACTOR_PLAN.md §7.1 task 1.3; read FIRST when uncertain which downstream Stage 1+2+3 docs your task needs; skip when you already know).
- **Stage 1**: `NORTH_STAR.md` + `HANDOFF.md` + `CURRENT_STATE.md` + `CHECKS_AND_BALANCES.md`
- **Stage 2**: `RISKS.md` + `BACKLOG.md` + `_validation_log.md`
- **Stage 3**: `_reviewer_effectiveness.md` (trend tables + per-round data); `MULTI_AGENT_GUIDE.md` § Pattern E (current specialty composition); reviewer agent prompts at `.claude/agents/udm-*.md`
- **Stage 4**: grep prior round-closeout-skill outputs at `docs/migration/_agent_evolution/specialty-tuner-round*-*.md`

## Trend analysis algorithm

Per specialty (from `_reviewer_effectiveness.md` "By specialty role" trend table):

1. **Read events to-date** (`Events to date` column)
2. **Read false-clean rate** (`False-clean rate` column)
3. **Compute recent trend**: if 🔴 found / event is monotonically declining over last 3 rounds → "exhausted-surface signal"
4. **Threshold check**:
   - `false-clean rate > 25%` over ≥4 events → 🔴 **RETIRE-OR-PAIR** (recommend specialty deprecation OR mandatory pairing with complementary specialty)
   - `false-clean rate > 10%` over ≥6 events → 🟡 **REFINE** (propose prompt strengthening)
   - 🔴-catch declining 3+ rounds → 🟡 **EXHAUSTED-SURFACE** (consider rotating to new specialty)
   - All clean + stable → ✅ **NO ACTION**
5. **Minimum-event guard**: if `events to date < 5` → output `CONFIDENCE: LOW` regardless of computed signal; recommendation marked "consider waiting for more evidence"

## Output contract

Markdown file at `docs/migration/_agent_evolution/specialty-tuner-round<N>-<YYYY-MM-DD>.md`:

```markdown
# Specialty Tuner Output — Round N

## Date: YYYY-MM-DD
## Confidence: HIGH/MEDIUM/LOW
## Sample size: <N total events across <M> specialties>
## Skill version: v0.1.0

## Findings per specialty

### <specialty-name> (<events> events, <false-clean-%>% false-clean) — <verdict>

<one-paragraph analysis>

[If verdict ∈ {REFINE, RETIRE-OR-PAIR}, include proposed delta:]

**Proposed delta**:
- BEFORE: "<quoted prior prompt text>"
- AFTER: "<proposed prompt text>"
- **Reversibility**: prior prompt archived at `.claude/agents/_archive/<name>-v<prior>-<date>.md`

## Proposed deltas summary

<count> deltas proposed. User review required: YES / NO.
```

## Conservative bias

- A specialty with mixed signal (some 🔴-catches, some misses, no clear false-clean pattern) → 🟡 **MONITOR** (not 🟡 REFINE)
- A specialty newly-introduced this round (1 event) → ✅ NO ACTION + first observation note
- A specialty with rising 🔴 catch + 0% false-clean → ✅ NO ACTION (rising-catch is healthy signal)

## Composition with Pattern E

Skill MAY propose:
- **Composition change** (e.g., "swap comprehensive-5-gate slot for paired comprehensive-2-pass")
- **Threshold change** (e.g., "minimum events for verdict-of-MANDATORY raise from 5 to 7")
- **Specialty deprecation** (e.g., "feasibility-Tier0 has 1 event in 6 rounds; deprecate")

Skill does NOT propose:
- New specialties not in the canonical enum (that goes via D-numbered decision)
- Replacing Pattern E entirely (canonical per D-numbered decision)

## Confidence calibration

| Events | Confidence |
|---|---|
| ≥10 OR ≥3 rounds matching | HIGH |
| 5-9 OR 2 rounds matching | MEDIUM |
| < 5 | LOW |

## User approval gate

Skill PROPOSES; user APPROVES before `udm-agent-prompt-versioner` applies. No autonomous prompt-rewrite. Per Round 8 D95.

## Tier 0 stub (per D67)

`tests/smoke/test_skill_specialty_tuner.py` (~5s, no external deps). Verifies:
- Skill imports
- All-clean specialty returns NO_ACTION
- Degrading specialty returns REFINE or RETIRE_OR_PAIR per thresholds
- LOW-confidence flag fires when events < 5

## Cross-references

- D95 (umbrella) + D97 (cycle-cadence-optimizer tier mapping) + D98 (versioner)
- `docs/migration/phase1/08_sub_agent_self_improvement.md` § 3
- `_reviewer_effectiveness.md` Trends section
- `MULTI_AGENT_GUIDE.md` Pattern E

## Owner

Pipeline lead. Round 8 ownership.
