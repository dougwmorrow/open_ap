# Self-Improvement Discipline

The meta-discipline that makes the UDM validation system self-tuning across rounds, without abandoning human-in-the-loop control. Authored at Round 8 close-out 2026-05-11. Constituent decisions: D95 (umbrella) + D96 (sub-class 9.j formalization) + D97 (cycle-cadence-optimizer tier mapping) + D98 (agent prompt versioning) + D99 (Round 8 acceptance).

## Purpose

After 7 rounds, the validation discipline (D55 5-gate + D56 second-pass + D60 round close-out + D62 CCL + D72 termination + D89-D91 Pattern F) was demonstrably catching real bugs (~80+ across Rounds 2-7). But every refinement to the discipline required the user to identify a gap, propose a fix, and approve implementation — three round-trips per optimization, ~60 min per round, ~7 hours over Phase 1.

Round 8 inverts this. The discipline observes itself via `_reviewer_effectiveness.md`; six skills analyze the trail at every round close-out + propose refinements; the user reviews once + approves a batch.

## How it works

```
Round N close-out begins
   ↓
[Skill 8.A] udm-retrospective-collector
   Appends per-reviewer-event rows to _reviewer_effectiveness.md
   (Replaces manual orchestrator append from Rounds 4-7)
   ↓
[Skills 8.B-8.E + 8.G run in parallel — they read ledger; don't modify it]
   8.B udm-specialty-tuner — ledger trends → propose specialty refinements
   8.C udm-subclass-accumulator — 🔴 findings → propose new Pitfall #9 sub-classes
   8.D udm-producer-checklist-evolver — producer-Gate-1-misses → propose directive strengthening
   8.E udm-cycle-cadence-optimizer — cycle counts → propose per-tier cadence calibration
   8.G udm-cascade-audit-evolver — Pattern F findings → propose new trigger candidates
   ↓
[User review batch — once per round, NOT once per skill]
   Pipeline lead reviews ALL proposed deltas; approves YES/NO per delta
   Typical session: 10-15 min
   ↓
[Skill 8.F] udm-agent-prompt-versioner (ONLY skill that writes)
   Applies approved batch
   Bumps semver per change_type (MAJOR/MINOR/PATCH)
   Archives prior version
   Appends changelog row
   ↓
Round N+1 begins with refined sub-agent corpus
```

## Cost model

| Phase | Cost per round | Notes |
|---|---|---|
| Pre-Round-8 (Rounds 1-7) | ~60 min/round on discipline refinement | User identifies, asks Claude, reviews, approves, validates |
| Post-Round-8 (Phase 2+) | ~30-40 min/round | 5-10 min skill compute + 10-15 min user review + 5-10 min applied changes |

Break-even: round 8+ (Phase 2 first 3 rounds amortize the Round 8 investment).

## Bounds (escape conditions — FREEZE the loop)

If any of these trigger, FREEZE the loop and escalate to pipeline lead human review:

| Condition | Detection | Action |
|---|---|---|
| Specialty effectiveness declines 2 rounds in a row | 8.B trend analysis | Freeze 8.B; pipeline lead reviews per-specialty manually |
| New 🔴 bug class introduced by a recently-applied delta | Next-round 🔴 in just-versioned region | Auto-revert via 8.F + freeze that agent's evolution |
| Carryover items per round monotonically rising 3+ rounds | 8.E + B129 monitor | Freeze 8.E + 8.F; pipeline lead reviews scope creep |
| User declines 50%+ proposed deltas in 2 consecutive rounds | Approval ratio tracking | Freeze all skills; pipeline lead reviews skill prompt quality |
| Any skill's output 🔴 cites a locked D-number contradiction | Pre-flight check in each skill | Auto-abort that skill's specific delta; pipeline lead reviews |

## Bounds (auto-revert conditions — IDEMPOTENT recovery)

If a delta is applied at Round N close-out and Round N+1's FIRST cycle shows regression in the just-versioned surface:

1. 8.F detects regression signal (via `_reviewer_effectiveness.md` correlation)
2. Auto-reverts to prior version: copies `_archive/<name>-v<prior>-<date>.md` back to `.claude/agents/<name>.md`
3. Appends changelog row: `## v<x.y.z> (REVERTED to v<x.y.(z-1)>) — <date>` with regression evidence
4. Failed delta becomes input to next round's 8.B/8.C/8.D invocation (so they learn from the failure pattern)
5. Original failure logged to `docs/migration/_agent_evolution/_failed_deltas.md` (append-only audit trail)

## Lifecycle

- **Authored**: Round 8 close-out 2026-05-11
- **First live invocation**: NEXT round close-out (Phase 2 Round 1)
- **Quarterly review**: pipeline lead reviews ALL agent prompts + skill outputs per `MAINTENANCE.md` Quarterly cadence
- **Disablement (worst case)**: if loop is FROZEN per escape condition AND not unfrozen within 1 quarter, deprecate via D-numbered decision

## Locked-artifact discipline (D40 + D92)

The discipline DOES touch:
- `.claude/agents/<name>.md` (versioned via 8.F)
- `.claude/skills/<name>/SKILL.md` (versioned via 8.F if needed; typically rare)
- `docs/migration/_agent_evolution/*.md` (append-only audit trail)
- `_reviewer_effectiveness.md` (append-only ledger)
- `_archive/` directories (append-only)

The discipline DOES NOT touch:
- Locked phase spec docs (`phase1/01_database_schema.md`, etc.) — those go through D92 supersession governance
- `03_DECISIONS.md` entries — superseded via canonical D-number chain
- `04_EDGE_CASES.md` series entries — append-only per existing discipline
- Production pipeline code (out-of-scope; this is meta-tooling)
- CLAUDE.md project root — touched only via D93 cascade propagation discipline at round close-out

## Pillar mapping (per D61)

| Pillar | Contribution |
|---|---|
| **Audit-grade** | Every prompt change versioned + decision-recorded + changelog-tracked; reversibility via archived prior versions |
| **Traceability** | `_reviewer_effectiveness.md` ledger trends to every prompt iteration; `_failed_deltas.md` documents revert events |
| **Idempotent** | Reverting to prior version is mechanical (file copy); re-running close-out skills with same inputs produces same outputs |
| **Operationally stable** | Discipline self-maintains without manual optimization cycles; quarterly review per MAINTENANCE.md |
| **$120K/year ceiling** | Bounded compute (skills run at close-out only, not per cycle); no Snowflake spend |

## Anti-patterns this doc rejects

- ❌ **Autonomous prompt rewriting** — human review preserved at every batch (D95 hard rule)
- ❌ **Continuous tuning** — skills run at close-out only; no mid-round changes
- ❌ **Removing existing producer self-check directives** — discipline accumulates, doesn't replace
- ❌ **Bypassing D72 termination rule** — skills propose calibration WITHIN D72; never replace
- ❌ **Touching production pipeline code** — this is meta-tooling; production code lives in CLAUDE.md governance
- ❌ **Editing prior versions of archived prompts** — append-only audit trail
- ❌ **Skipping user approval** — abort 🔴 in 8.F if approval token missing
- ❌ **Aggregating multiple rounds of evidence into one delta** — one round = one set of proposed deltas

## Decisions

- **D95** — Self-improvement skill suite umbrella discipline (locked Round 8 close-out)
- **D96** — Pitfall #9 sub-class 9.j formalization (B-item status-render discipline; 2-event evidence base R6 unscoped + R7 first-production)
- **D97** — Cycle-cadence-optimizer artifact-complexity tier mapping (Tier α/β/γ/δ + minimum-event thresholds)
- **D98** — Agent prompt versioning + change-log convention (semver vMAJOR.MINOR.PATCH + frontmatter + archive)
- **D99** — Round 8 acceptance (TBD: math-infeasibility per D73/D78/D94 OR convergence-confirmed per D83/D88)

## Cross-references

- `_reviewer_effectiveness.md` — the evidence ledger
- `HANDOFF.md` §8 sub-class accumulator — the bug taxonomy
- `MULTI_AGENT_GUIDE.md` § Pattern E + Pattern F — the validation patterns this tunes
- `MAINTENANCE.md` quarterly review cadence
- `CHECKS_AND_BALANCES.md` — the discipline this tunes (without replacing)
- `docs/migration/phase1/08_sub_agent_self_improvement.md` — the spec doc
- `docs/migration/_agent_evolution/` — output directory (skill outputs + per-agent changelogs + failed-deltas log)
- `.claude/agents/_archive/` — append-only archive of superseded agent prompts
- `.claude/skills/udm-retrospective-collector/SKILL.md` (8.A)
- `.claude/skills/udm-specialty-tuner/SKILL.md` (8.B)
- `.claude/skills/udm-subclass-accumulator/SKILL.md` (8.C)
- `.claude/skills/udm-producer-checklist-evolver/SKILL.md` (8.D)
- `.claude/skills/udm-cycle-cadence-optimizer/SKILL.md` (8.E)
- `.claude/skills/udm-agent-prompt-versioner/SKILL.md` (8.F)
- `.claude/skills/udm-cascade-audit-evolver/SKILL.md` (8.G; B143)

## Owner

Pipeline lead. Quarterly review per `MAINTENANCE.md`. Discipline changes are D-numbered.

## Last reviewed

2026-05-11 (authored at Round 8 close-out; first live invocation pending Phase 2 Round 1 close-out)
