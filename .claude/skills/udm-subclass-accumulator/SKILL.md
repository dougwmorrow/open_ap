---
name: udm-subclass-accumulator
description: Scans Round N 🔴 findings; identifies bug patterns recurring ≥2 times that don't match existing Pitfall #9 sub-classes (9.a-9.j); proposes new sub-class with first-evidence entry + producer self-check directive. Round 8 close-out lands sub-class 9.j (B-item status-render discipline) per B144 2-event evidence base (R6 unscoped + R7 first-production Pattern F). Invoked AFTER `udm-retrospective-collector`; per Round 8 D96.
---

# UDM Sub-Class Accumulator

Third close-out analysis skill. Detects emerging Pitfall #9 sub-class patterns + proposes formalization at the 2-event evidence threshold.

## When to invoke

- Every round close-out, AFTER `udm-retrospective-collector`
- Position: 3rd of 7 close-out skills (2nd of 5 analysis skills; per `udm-round-closeout` Section 10.3 NEW)
- Always invoked, even on small rounds (1 finding can clarify a 2nd-event pattern)

## Canonical Context Load (CCL) per D62

- **Stage 0**: `docs/migration/INDEX.md` (routing manifest; recommended-not-mandatory; added 2026-05-15 per D62 amendment + D.2 INDEX.md per MARKDOWN_REFACTOR_PLAN.md §7.1 task 1.3; read FIRST when uncertain which downstream Stage 1+2+3 docs your task needs; skip when you already know).
- **Stage 1**: `NORTH_STAR.md` + `HANDOFF.md` (§8 sub-class accumulator) + `CURRENT_STATE.md` + `CHECKS_AND_BALANCES.md`
- **Stage 2**: `RISKS.md` + `BACKLOG.md` + `_validation_log.md` (this round's entry + prior rounds for cross-round pattern matching)
- **Stage 3**: `_reviewer_effectiveness.md` (specialty correlation); prior subclass-accumulator outputs at `docs/migration/_agent_evolution/subclass-accumulator-round*-*.md`
- **Stage 4**: grep `_validation_log.md` for 🔴 findings text matching candidate patterns

## Pattern-matching algorithm

For each 🔴 finding in Round N:

1. **Match against existing sub-classes** by keyword:
   - 9.a column-name — keywords: "column", "invented column", "canonical column"
   - 9.b parameter-name — keywords: "parameter", "@", "SP signature"
   - 9.c enum-value — keywords: "enum", "CHECK constraint", "status value"
   - 9.d type-width — keywords: "NVARCHAR(", "VARCHAR(", "DECIMAL(", "width"
   - 9.e Unicode-vs-ASCII — keywords: "Unicode", "NVARCHAR vs VARCHAR"
   - 9.f cross-table-lift — keywords: "lift", "cross-table"
   - 9.g keyword-only marker — keywords: "*,", "keyword-only", "PEP 3102"
   - 9.h wrong-section — keywords: "section", "§", "invented section"
   - 9.i process-discipline — keywords: "false-closure", "stale B-range", "silent omission", "trailing summary"
   - 9.j B-item status-render — keywords: "leading badge", "🟡 Open + CLOSED inline"

2. **Unclassified findings** → potential new sub-class candidate

3. **Cluster unclassified by similarity** (semantic + keyword)

4. **Threshold check**:
   - ≥3 fresh instances across 2+ rounds → 🔴 propose new sub-class with 5-step audit directive
   - ≥2 fresh instances across 2 rounds → 🟡 propose new sub-class candidate
   - Single-event cluster → 🟡 **MONITOR** (insufficient evidence; track in skill output but don't propose formalization yet)

## Output contract

Markdown file at `docs/migration/_agent_evolution/subclass-accumulator-round<N>-<YYYY-MM-DD>.md`:

```markdown
# Sub-Class Accumulator Output — Round N

## Date: YYYY-MM-DD
## Confidence: HIGH/MEDIUM/LOW
## Sample size: <N 🔴 findings in Round N>

## Existing sub-class hits

- 9.a: <count> instances this round (cumulative: <count> across <rounds>)
- 9.b: <count> instances this round
- ...

## New sub-class candidates

### Candidate 9.k — <descriptive name>

**Evidence**:
- Round X cycle Y: "<finding text>"
- Round X+1 cycle Z: "<finding text>"

**Pattern**: <inferred>

**Proposed HANDOFF §8 entry**:
- **9.k — <name>**: <one-paragraph>. First evidence: <round/cycle>. Tracked for HANDOFF wording strengthening as B<num>.

**Producer self-check directive**: <1-5 step audit>

**Threshold met**: 2-event ✅ / 3-event ✅ / insufficient

## Cumulative sub-class status

<table 9.a through 9.j + new candidates>

## User review required: YES / NO
```

## 9.j formalization at Round 8 close-out (this round's load-bearing output)

Round 8 close-out output explicitly formalizes 9.j per B144 2-event evidence base. Sample output:

```
### Sub-class 9.j — B-item status-render discipline

**Evidence**:
- R6 unscoped Pattern F audit 2026-05-11: 15+ B-items with `🟡 Open` leading + `**CLOSED**` inline
- R7 first-production Pattern F audit 2026-05-11: 7 + 4 simultaneous instances

**Pattern**: round close-out high-velocity B-item adds; inline-close annotation faster than badge-flip; mass-flip at end is error-prone

**Producer self-check**: after ANY cycle-N or close-out edit that adds/closes a B-item:
(1) verify leading badge matches inline annotation; (2) flip badge if mismatch

**Threshold**: 2-event ✅ — eligible for HANDOFF §8 formalization at Round 8 close-out per B144
```

## Confidence calibration

| Evidence | Confidence |
|---|---|
| ≥3 events / ≥2 rounds | HIGH |
| 2 events / 2 rounds | MEDIUM |
| 1 event | LOW (MONITOR only) |

## Composition with HANDOFF §8

Skill PROPOSES new sub-class additions. Pipeline lead REVIEWS at close-out cascade. If approved, sub-class lands inline at HANDOFF §8 via the close-out cascade aggregate-doc update step (Section 6 of `udm-round-closeout` skill — HANDOFF.md update). `udm-agent-prompt-versioner` (8.F) handles `.claude/agents/<name>.md` versioned edits only; HANDOFF.md is project-doc-class and updated through the existing close-out cascade discipline, not skill-class versioning.

## Tier 0 stub (per D67)

`tests/smoke/test_skill_subclass_accumulator.py`. Verifies:
- Skill imports
- 9.a finding classified as 9.a
- Unclassified single-event returns MONITOR
- Unclassified 2-event returns 🟡 propose sub-class
- 9.j evidence at Round 8 returns formalization proposal

## Cross-references

- D96 (sub-class 9.j formalization)
- `docs/migration/phase1/08_sub_agent_self_improvement.md` § 4 + § 12
- `HANDOFF.md` §8 sub-class accumulator 9.a-9.j
- B144 (sub-class 9.j candidate)

## Owner

Pipeline lead.
