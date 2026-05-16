---
name: udm-retrospective-collector
description: Auto-appends per-reviewer-event rows to docs/migration/_reviewer_effectiveness.md at round close-out. Replaces the manual orchestrator burden Rounds 4-7 paid. Always HIGH confidence — mechanical append, not trend analysis. Invoke at the start of every round close-out cascade, BEFORE any of the analysis skills (udm-specialty-tuner / udm-subclass-accumulator / udm-producer-checklist-evolver / udm-cycle-cadence-optimizer / udm-cascade-audit-evolver) read the ledger. Authored at Round 8 per `docs/migration/phase1/08_sub_agent_self_improvement.md` § 2 + D95-D96.
---

# UDM Retrospective Collector

The first skill invoked at every round close-out. Captures per-reviewer-event evidence into the append-only ledger so downstream analysis skills (specialty-tuner / subclass-accumulator / etc.) read fresh data.

## When to invoke

- Every round close-out (Phase 1 R1-R8, Phase 2+)
- Position: 1st of 7 close-out skills — must run before 8.B-8.E + 8.G (the 5 analysis skills) and 8.F (versioner)
- Triggers: round acceptance criterion met (per `udm-round-closeout` skill SKILL.md Section 10.1 NEW Round 8 addition)

## When NOT to invoke

- Mid-round (close-out is the trigger; mid-round appends violate append-discipline)
- For trivial-edit rounds (skip per `_reviewer_effectiveness.md` § Discipline)

## Canonical Context Load (CCL) per D62

- **Stage 0**: `docs/migration/INDEX.md` (routing manifest; recommended-not-mandatory; added 2026-05-15 per D62 amendment + D.2 INDEX.md per MARKDOWN_REFACTOR_PLAN.md §7.1 task 1.3; read FIRST when uncertain which downstream Stage 1+2+3 docs your task needs; skip when you already know).
- **Stage 1** (mandatory): `NORTH_STAR.md` + `HANDOFF.md` + `CURRENT_STATE.md` + `CHECKS_AND_BALANCES.md`
- **Stage 2**: `RISKS.md` + `BACKLOG.md` + `_validation_log.md`
- **Stage 3**: `_reviewer_effectiveness.md` (schema reference + current trend tables); the round's `_validation_log.md` entry (for per-cycle bug counts + agentIds)
- **Stage 4**: grep `docs/migration/_research/` for advisory-research outputs (if any)

First content-substantive `Read` MUST hit a Stage 1 doc.

## Input contract

The orchestrator provides per-cycle:

```python
@dataclass
class ReviewerEvent:
    round: int
    cycle: int  # 1-indexed
    agent_id: str  # from Agent tool invocation result
    specialty: Literal[
        "column-walk", "cross-reference", "internal-consistency",
        "D72-edge-cases", "advisory-research", "comprehensive-5-gate",
        "sleeper-bug-stress", "convergence-verification",
        "feasibility-Tier0", "mechanical-fix", "cascade-audit"
    ]
    mode: Literal["Pattern-E", "single-agent", "Pattern-F-Layer-2-paired"]
    red_count: int
    yellow_count: int
    wall_clock_minutes: int
    cross_ref: str  # pointer to _validation_log.md entry
```

Skill validates:
- All fields populated (missing → 🔴 abort; orchestrator must re-capture)
- `specialty` matches canonical enum (drift → 🔴 abort with valid-enum list)
- `cycle` is monotonic vs prior events for this round (out-of-order → 🔴)
- `round` is next-expected (gap → 🔴; "Round 9 ledger entry but no Round 8 section found")

## Output contract

Appends to `_reviewer_effectiveness.md` per existing schema:

1. **Add round section** if first event for this round:
   ```markdown
   ### Round <N> D72 <cycle-count>-cycle campaign + Pattern F first-production (<YYYY-MM-DD>)
   
   | Agent | Cycle | Specialty | Mode | 🔴 | 🟡 | Min | Subsequent | False-clean | Cross-ref |
   |---|---|---|---|---|---|---|---|---|---|
   ```

2. **Append row per event** (single-line markdown table row matching schema)

3. **At end of round section**, append summary:
   ```
   **Cumulative Round N**: <total-🔴> caught + <total-🟡>; <N> reviewer-agent events; <N> false-clean events.
   ```

4. **Update trend tables** at top of doc (per `_reviewer_effectiveness.md` § Trends):
   - "By specialty role" — increment events count + recompute false-clean rate + recompute average minutes
   - Append new key empirical finding if observed (e.g., "Column-walk specialty has 0% false-clean rate across 8 events" — extends prior 7-event count)

## Backward-update rule

When the round being closed surfaced a bug in a region cleared by a PRIOR round's reviewer:
- Find prior round's row in ledger
- Increment `Subsequent` count
- Set `False-clean` to TRUE
- Append "Correction note" sub-row referencing discovering cycle

NEVER edit prior verdict — append-only audit trail per § Backward-update rule.

## Confidence

ALWAYS HIGH. This skill is mechanical append. No interpretation. No trend inference. Downstream skills (8.B-8.G) interpret.

## Anti-patterns

- ❌ Editing prior entries' verdicts — append-only
- ❌ Computing trends in this skill — that's 8.B's job
- ❌ Skipping cycles that "didn't matter" — every reviewer invocation is captured
- ❌ Aggregating multiple events into one row — one row per event (one agent, one cycle, one specialty)
- ❌ Inferring specialty when the orchestrator didn't tag — abort 🔴 instead

## Composition

| Used with | Role |
|---|---|
| `udm-round-closeout` | Invokes this skill at Section 10.1 (NEW per Round 8) |
| `udm-specialty-tuner` | Reads ledger AFTER this skill's appends |
| `udm-subclass-accumulator` | Reads ledger AFTER this skill's appends |
| `udm-cascade-audit-evolver` | Reads ledger AFTER this skill's appends |

## Tier 0 stub (per D67)

`tests/smoke/test_skill_retrospective_collector.py` (~5s, no external deps). Verifies:
- Skill imports
- Valid event passes validation
- Invalid specialty raises ValueError
- Out-of-order cycle raises ValueError
- Markdown row generation matches schema

## Cross-references

- D95 (umbrella discipline)
- `docs/migration/phase1/08_sub_agent_self_improvement.md` § 2
- `_reviewer_effectiveness.md` § Schema + § Backward-update rule
- `udm-round-closeout` Section 10.1

## Owner

Pipeline lead. Round 8 ownership.
