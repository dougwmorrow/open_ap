---
name: udm-cycle-cadence-optimizer
description: At round close-out, computes optimal cycle cadence per artifact-complexity tier (Tier α/β/γ/δ) based on rounds-to-date evidence (cycle count, trajectory shape, sleeper-bug catches, Pattern F findings). Per Round 8 D97 tier mapping — Tier α (small <10 KB) → D56 2-pass; Tier β (medium 10-50 KB) → Pattern E + 2-3 verify; Tier γ (large 50-100 KB) → Pattern E + sleeper-bug + Pattern F; Tier δ (mega >100 KB OR mega-table) → above + math-infeasibility-acceptance. Conservative bias — does NOT modify D72 (canonical 10-cycle ceiling + 3-consecutive-clean stays). Invoked AFTER `udm-retrospective-collector`; per Round 8 D97.
---

# UDM Cycle Cadence Optimizer

Fifth close-out analysis skill. Tracks artifact-complexity-vs-convergence-cycles trend; proposes tier-specific cadence within D72 envelope.

## When to invoke

- Every round close-out, AFTER `udm-retrospective-collector`
- Position: 5th of 7 close-out skills (4th of 5 analysis skills; per `udm-round-closeout` Section 10.5 NEW)
- Skip if rounds-completed < 4 (insufficient evidence per tier)

## Canonical Context Load (CCL) per D62

- **Stage 0**: `docs/migration/INDEX.md` (routing manifest; recommended-not-mandatory; added 2026-05-15 per D62 amendment + D.2 INDEX.md per MARKDOWN_REFACTOR_PLAN.md §7.1 task 1.3; read FIRST when uncertain which downstream Stage 1+2+3 docs your task needs; skip when you already know).
- **Stage 1**: `NORTH_STAR.md` + `HANDOFF.md` (§12 round history) + `CURRENT_STATE.md` + `CHECKS_AND_BALANCES.md` (D72 termination rule)
- **Stage 2**: `RISKS.md` + `BACKLOG.md` (B129 carryover-compounding monitor) + `_validation_log.md`
- **Stage 3**: `_reviewer_effectiveness.md` (cycle counts per round); HANDOFF §12 round history (artifact size + cycle count); prior cycle-cadence-optimizer outputs
- **Stage 4**: grep `docs/migration/phase1/0?_*.md` for artifact sizes

## Tier definition (per Round 8 D97)

Project-derived taxonomy (NOT an external SE standard); grounded in 7 rounds of empirical evidence.

| Tier | Definition | Initial recommendation | Empirical basis |
|---|---|---|---|
| α | Single-section artifact <10 KB | D56 2-pass | R2 D62 dog-food (2 cycles converged) |
| β | Multi-section 10-50 KB | Pattern E from cycle 1 + 2-3 verify | R2 Configuration (Pattern E first-cycle all-clean) |
| γ | Multi-section spec doc 50-100 KB | Pattern E from C1 + sleeper-bug final + Pattern F close-out | R3 (80 KB, 9 cycles); R5 (75 KB, 5 cycles); R7 (50 KB, 8 cycles) — mean 7.3, std-dev 2.1 |
| δ | Mega-spec >100 KB OR mega-table inventory | Above + math-infeasibility-acceptance OR convergence-confirmed acceptance | R6 (110 KB, 7 cycles, convergence-confirmed) — single event so far; CONFIDENCE: LOW; retain Tier γ cadence pending 2nd event |

## Trend analysis

Per round, skill computes:
- Artifact size (KB measured at lock-time)
- Cycle count to convergence/acceptance
- Pattern E invocation count
- Sleeper-bug-stress cycle position
- Pattern F findings count (if Round ≥ 7)
- Carryover items per round (per B129)

Skill tracks per-tier mean + std-dev of cycle counts:
- If mean shifts >1 cycle from prior estimate → propose cadence calibration (e.g., "Tier γ rounds R5/R6/R7 averaged 6.6 cycles; current recommendation 'Pattern E + sleeper-bug' fitting" → confirm OR refine)
- If carryover trend monotonically rising 3+ rounds → 🟡 alarm per B129 trigger; recommend "freeze loop OR add cascade-audit-evolver Layer 1 trigger for carryover-detection"

## Output contract

Markdown file at `docs/migration/_agent_evolution/cycle-cadence-optimizer-round<N>-<YYYY-MM-DD>.md`:

```markdown
# Cycle Cadence Optimizer Output — Round N

## Date: YYYY-MM-DD
## Confidence: HIGH/MEDIUM/LOW
## Sample size: <N rounds; <M> tier-γ events>

## Per-tier cadence empirical fit

### Tier γ (large spec docs 50-100 KB) — <M> rounds of evidence
- R3: <size> → <cycles> (math-infeasibility)
- R5: <size> → <cycles> (convergence-confirmed)
- R6: <size> → <cycles> (convergence-confirmed)
- R7: <size> → <cycles> (math-infeasibility)
- R8: <size> → <cycles> (TBD)

Mean cycles: <N>; std-dev: <N>. Current recommendation (<X>) is empirically fitting. **NO CHANGE proposed** / **🟡 Refine proposed**.

## Proposed deltas

<if applicable>

## Carryover trend monitoring (per B129)

R5 → R6 → R7 → R8 trajectory: <N> → <N> → <N> → <N> carryover items per round. Trend: <stabilizing / rising / falling>. **No alarm** / **🟡 carryover-compounding alarm**.

## User review required: YES (deltas proposed) / NO (stable)
```

## Composition with D72

Skill does NOT propose changing:
- D72's 10-cycle ceiling (canonical)
- D72's 3-consecutive-clean convergence rule (canonical)
- D72's reset rule (canonical)

Skill MAY propose Tier-specific cadence WITHIN D72:
- "Tier α ceiling at 4 cycles" (still ≤10 per D72)
- "Tier γ Pattern E from cycle 1" (matches current R5+ practice)
- "Sleeper-bug-stress mandatory final cycle for Tier γ + δ" (matches R4C8 + R5C4 + R6C4 + R7C5 4-event precedent)

## Conservative bias

- Tier with 1-2 rounds of evidence → CONFIDENCE: LOW; recommendation "wait for more events"
- Tier with mixed-trajectory rounds (some converge fast, some slow) → CONFIDENCE: MEDIUM; "current cadence within band"
- Tier with monotonic trajectory shift (e.g., mean cycles falling round-over-round) → propose acknowledgment that "discipline is improving; current cadence may be over-conservative"

## Tier 0 stub (per D67)

`tests/smoke/test_skill_cycle_cadence_optimizer.py`. Verifies:
- Skill imports
- Tier-γ mean computation correct
- Carryover-trend detection (3 rising rounds → 🟡 alarm)
- LOW-confidence on tier with <3 events

## Cross-references

- D72 (10-cycle ceiling) + D97 (this skill's tier mapping)
- `docs/migration/phase1/08_sub_agent_self_improvement.md` § 6
- `CHECKS_AND_BALANCES.md` D72 termination rule section
- B129 (carryover-compounding monitor)
- `MAINTENANCE.md` quarterly review cadence

## Owner

Pipeline lead.
