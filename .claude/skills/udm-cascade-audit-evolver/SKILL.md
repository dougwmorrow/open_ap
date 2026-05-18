---
name: udm-cascade-audit-evolver
description: Scans Pattern F findings (D89-D91 Layer 1 + Layer 2) across rounds; proposes new trigger additions when novel cascade-gap classes emerge. Counterpart to `udm-subclass-accumulator` (which is for Pattern E findings — Pitfall #9 sub-classes). Threshold: ≥2 unmatched Pattern F findings across 2 rounds → 🟡 propose new trigger; ≥3 → 🔴 propose new trigger + Layer 1 script implementation OR Layer 2 prompt strengthening. Implementation of B143 (Round 6 retrospective). Invoked AFTER Pattern F completes at round close-out; per Round 8 D95.
---

# UDM Cascade Audit Evolver

Seventh skill, optional but recommended. Pattern F's discipline-evolution counterpart to `udm-subclass-accumulator`. Closes B143 (Round 6 retrospective candidate for 7th skill).

## When to invoke

- Every round close-out, AFTER Pattern F (D89-D91) invocation completes
- Position: 6th of 7 close-out skills (5th and last analysis skill — Pattern-F-focused; per `udm-round-closeout` Section 10.6 NEW)
- Always invoked when Pattern F runs (which is every round close-out after R6)

## When NOT to invoke

- For round close-outs that skip Pattern F (none currently; Pattern F is mandatory at all round close-outs per D89)

## Canonical Context Load (CCL) per D62

- **Stage 0**: `docs/migration/INDEX.md` (routing manifest; recommended-not-mandatory; added 2026-05-15 per D62 amendment + D.2 INDEX.md per MARKDOWN_REFACTOR_PLAN.md §7.1 task 1.3; read FIRST when uncertain which downstream Stage 1+2+3 docs your task needs; skip when you already know).
- **Stage 1**: `NORTH_STAR.md` + `HANDOFF.md` (§8 Pitfall #11 + §3 D89-D91) + `CURRENT_STATE.md` + `CHECKS_AND_BALANCES.md` (Pattern F discipline)
- **Stage 2**: `RISKS.md` (R28 cascade self-attestation) + `BACKLOG.md` + `_validation_log.md` (this round's Pattern F entry)
- **Stage 2.5**: `POLISH_QUEUE.md` (added 2026-05-12 per D113) ← skim 🟡 Open + ⚫ CLOSED P-N items from the closing round; cosmetic items closed inline OR newly surfaced are within Pattern F audit scope (Trigger E — convention registration sub-class — and Trigger B — closure-target audit — both apply to P-numbers analogously to B-numbers)
- **Stage 3**: `MULTI_AGENT_GUIDE.md` § Pattern F (current trigger set: A/B/C/D/E/F); `tools/verify_cascade.py` (Layer 1 deterministic); `.claude/agents/udm-cascade-auditor.md` (Layer 2 paired); prior cascade-audit-evolver outputs at `docs/migration/_agent_evolution/cascade-audit-evolver-round*-*.md`
- **Stage 4**: grep `_reviewer_effectiveness.md` for cascade-audit specialty events

## Trigger-pattern detection algorithm

For each Pattern F 🔴 finding (Layer 1 OR Layer 2):

1. **Match against existing Layer 1 triggers** (Trigger C/D/F):
   - C — stale references (regex `B(\d+)-B(\d+)` + Round-N status claims + B-count drift)
   - D — forward-cite resolution (`RB-N` / `SP-N` / `B-N` / `D-N` / `R-N` references)
   - F — aggregate-doc freshness (02_PHASES.md + PHASE_1_DEEP_DIVE_PLAN.md + HANDOFF §3 in-flight)
2. **Match against existing Layer 2 triggers** (Trigger A/B/E):
   - A — D-acceptance substantiation
   - B — B-item closure-target audit *(extended 2026-05-12 per D113: P-N item closure-target audit also covered — same render-discipline / closure-mechanism / strikethrough-preserved expectations apply to POLISH_QUEUE.md entries)*
   - E — CLAUDE.md convention registration *(extended 2026-05-12 per D113: GLOSSARY.md + POLISH_QUEUE.md convention registration also covered when a new tracker / prefix / discipline lands; D113 itself was the proof-case)*
3. **Unmatched findings** → potential new trigger candidate
4. **Cluster unmatched findings by similarity**:
   - Cross-round pattern recurrence detection
   - Layer assignment (deterministic-script-coverable vs paired-judgment-required)

## Threshold

- ≥2 unmatched findings across 2 rounds → 🟡 propose new trigger (Layer 1 OR Layer 2 — based on whether finding class is deterministic-detectable)
- ≥3 unmatched findings across 2+ rounds → 🔴 propose new trigger + Layer 1 script implementation OR Layer 2 prompt strengthening
- Single-event finding → 🟡 **MONITOR**

## Output contract

Markdown file at `docs/migration/_agent_evolution/cascade-audit-evolver-round<N>-<YYYY-MM-DD>.md`:

```markdown
# Cascade Audit Evolver Output — Round N

## Date: YYYY-MM-DD
## Confidence: HIGH/MEDIUM/LOW
## Sample size: <N Pattern F events>
  (R6 retroactive + R6 unscoped + R7 first-production + R8 close-out + ... = N events at Round N)

## Per-trigger hit count this round

- Trigger A: <count> hits (cumulative <count>)
- Trigger B: <count>
- Trigger C: <count>
- Trigger D: <count>
- Trigger E: <count>
- Trigger F: <count>

## Unmatched findings

<list>

## New trigger candidates

### Candidate Trigger G — <descriptive name>

**Evidence**:
- Round X: "<finding>"
- Round X+1: "<finding>"

**Pattern**: <inferred>

**Layer assignment**: Layer 1 deterministic / Layer 2 judgment-class

**Proposed Layer 1 script addition** (if deterministic):
```python
# <regex / structure check>
```

**Proposed Layer 2 agent prompt strengthening** (if judgment-class):
"<one-paragraph addition to udm-cascade-auditor.md mandate>"

**User review required**: YES (if ≥2 events evidence base)
```

## Composition with Pattern F D89-D91

Skill does NOT modify canonical D89/D90/D91. Skill MAY propose:
- Adding Trigger G to D91 (`tools/verify_cascade.py`) — goes through `udm-agent-prompt-versioner` (8.F) for application if approved (with `_archive/verify_cascade-v0.1.0.py` retention)
- Adding Trigger H to D90 (`udm-cascade-auditor.md`) — same path
- NEW D-numbered decision (e.g., D-future) if a trigger represents architectural change

Skill respects locked-artifact discipline (D40/D92): canonical D89-D91 stay locked; deltas apply additively via supersession-via-versioner.

## Round 8 close-out signal

At Round 8 close-out, this skill processes:
- R6 retroactive (16 findings)
- R6 unscoped (24 findings)
- R7 first-production (~13 findings)
- R8 close-out (TBD — populated post-Pattern-F)

Looking for: pattern matches against existing triggers + clustering unmatched

Expected output (anticipated, based on 4-event evidence):
- All R6/R7 findings classified into A/B/C/D/E/F
- B-item silent omission (R7 INSTANCE 2 catch of B146-B155) — fits Trigger B (closure-target audit) — could spawn Trigger B' (silent-add variant)
- 9.j B-item status-render — already formalized via 8.C; this skill confirms no new cascade-audit trigger needed (sub-class is producer-discipline, not cascade-audit-discipline)
- **CANDIDATE Trigger G**: "B-item-status-render consistency across BACKLOG.md leading-badge + inline-annotation" — Layer 1 deterministic (grep `🟡 Open` + `CLOSED YYYY-MM-DD` on same line as inconsistency check). Evidence: 2-event (R6 unscoped + R7 first-production). Proposes for user review at Round 8 close-out.

## Tier 0 stub (per D67)

`tests/smoke/test_skill_cascade_audit_evolver.py`. Verifies:
- Skill imports
- Finding classification against Triggers A-F
- Unmatched-cluster detection
- LOW confidence on 1-event finding
- Trigger candidate output format

## Cross-references

- D89/D90/D91 (Pattern F discipline) + D95 (umbrella)
- B143 (this skill's authoring mandate)
- `docs/migration/phase1/08_sub_agent_self_improvement.md` § 8
- `MULTI_AGENT_GUIDE.md` § Pattern F
- `tools/verify_cascade.py` (Layer 1 script — proposed modifications go through 8.F)
- `.claude/agents/udm-cascade-auditor.md` (Layer 2 agent — same)

## Owner

Pipeline lead.
