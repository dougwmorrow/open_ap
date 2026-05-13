# Phase 1 Round 8 — Sub-Agent Self-Improvement Discipline

**Status**: 🟢 Locked 2026-05-11 via D99 convergence-confirmed architectural-review acceptance (paralleling D83/D88; distinct from D73/D78/D94 math-infeasibility). 9-cycle Pattern E campaign with sleeper-bug stress at cycle 5; trajectory 5→1→3→2→0→0. Pattern F 2nd-production invocation at close-out cascade caught + fixed 1 🔴 (B155 false-closure) + 1 🟡 (SI-series CLAUDE.md gap). Constituent D95-D99 all 🟢 Locked alongside.
**Round position**: LAST Phase 1 round (Round 8 of 8). After this round, Phase 1 acceptance criteria check + Phase 2 (Pilot Cutover) kick-off.
**Estimated artifact size**: ~60 KB spec doc + ~50 KB across 7 skill files + ~20 KB meta-doc = ~130 KB total round output
**Authored**: 2026-05-11

---

## § 0 — Read order + foundational decisions

### 0.1 Required reading (per D62 CCL Stage 1+2)

Before reviewing this artifact:
1. `docs/migration/NORTH_STAR.md` — pillar priority + conflict-resolution rubric
2. `docs/migration/HANDOFF.md` — locked vs in-flight; §8 Pitfalls 1-11 (especially #9 sub-class accumulator + #11 cascade self-attestation)
3. `docs/migration/CURRENT_STATE.md` — Round 8 is in-flight; this doc is the work
4. `docs/migration/CHECKS_AND_BALANCES.md` — 5-gate discipline + D72 termination rule + Pattern F (D89-D91)
5. `docs/migration/RISKS.md` — R11 (validation drift; what self-improvement counteracts) + R16/R17 (CCL honor-system; what versioning protects against)
6. `docs/migration/BACKLOG.md` — B47-B159 cumulative carryover (this round's mandatory triage workload) + B129 (carryover-compounding monitor) + B143 (cascade-audit-evolver) + B144 (sub-class 9.j formalization) + B146/B150-B159 (Round 7 carryover)
7. `docs/migration/_reviewer_effectiveness.md` — the evidence-ledger this round's skills consume
8. `docs/migration/_validation_log.md` — Round 5/6/7 entries + Round 6 Pattern F retrospective + Round 7 Pattern F first-production

### 0.2 Constituent decisions (proposed; locked at Round 8 close-out)

- **D95** — Self-improvement skill suite umbrella discipline (7 skills + meta-doc + governance loop)
- **D96** — Pitfall #9 sub-class 9.j formalization (B-item status-render discipline; 2-event evidence base met per R6 unscoped Pattern F + R7 first-production Pattern F)
- **D97** — Cycle-cadence-optimizer artifact-complexity tier mapping + minimum-event thresholds for trend trustworthiness
- **D98** — Agent prompt versioning + change-log convention (`.claude/agents/<name>.md` semver + frontmatter `version:` + `archived_at` for superseded)
- **D99** — Round 8 acceptance — **CONVERGENCE-CONFIRMED variant** per D83/D88 precedent (set 2026-05-11 at cycle 9 clean verification). Trajectory 5→1→3→2→0→0; sleeper-bug stress C5 caught canonical class; cycle 7 caught fix-fresh-instance class; cycle 9 final-verify clean. 9-cycle campaign within D72 ceiling (1 cycle remaining). 3rd convergence-confirmed acceptance (R5 D83 + R6 D88 + R8 D99) vs 3 math-infeasibility precedents (R3 D73 + R4 D78 + R7 D94). Both variants empirically valid per Round 5+ precedent.

### 0.3 Round 8 design constraints (drives every skill design)

| Constraint | Source | Implication |
|---|---|---|
| Bounded compute | NORTH_STAR ($120K/year ceiling) + D72 (10-cycle ceiling) | Skills run at round close-out only, NOT per cycle. One invocation per round per skill. |
| Human-in-the-loop preserved | D55 + D56 + D89 (paired-judgment never single instance) | Every skill PROPOSES deltas; user APPROVES before changes take effect. No autonomous prompt-rewrite. |
| Reversibility | NORTH_STAR (audit-grade always wins) | Every prompt change has a versioned predecessor archived (D98). Rollback = restore prior version. |
| Cross-doc consistency | D62 CCL + D93 cascade propagation | Skill outputs reference `_reviewer_effectiveness.md` + HANDOFF §8 + relevant agent prompt; no orphan outputs. |
| Skill outputs are themselves validated | D55 (5-gate applies to ALL artifacts) | Skill output deltas go through Gate 1+2 like any other artifact. Recursive measurement. |
| Minimum-event thresholds | Pattern E empirical evidence (column-walk: 7-event 0% false-clean; sleeper-bug: 4-event 100% catch) | Specialty recommendations need ≥5 events; sub-class formalization needs ≥2 events; cadence proposals need ≥3 rounds of evidence per complexity tier. |

### 0.4 What this round does NOT do

To prevent scope creep (Round 6 lesson: 110 KB spec doc with 7-cycle campaign):

- ❌ Does NOT implement autonomous prompt rewriting — skills propose; user approves
- ❌ Does NOT replace D72 termination rule — cycle-cadence-optimizer proposes calibration; D72 stays canonical
- ❌ Does NOT replace Pattern E or Pattern F — they remain canonical; specialty-tuner refines composition within them
- ❌ Does NOT introduce a new test tier — Tier 0-5 remain canonical per D70
- ❌ Does NOT touch production pipeline code — meta-discipline only; `.claude/skills/`, `.claude/agents/`, `docs/migration/` only
- ❌ Does NOT replace HANDOFF Pitfall #9 sub-class accumulator — sub-class accumulator skill (8.C) AUTOMATES proposing additions; the HANDOFF section remains canonical

### 0.5 Round 8 vs prior rounds — pattern continuity

| Aspect | R3 | R4 | R5 | R6 | R7 | **R8** |
|---|---|---|---|---|---|---|
| Primary output | Module specs | CLI specs | Test specs | Deployment specs | Schema evolution specs | **Skill specs + skill files** |
| Artifact size (KB) | 80 | 85 | 75 | 110 | 50 | **~130 (spec ~60 + 7 SKILL.md ~50 + meta ~20)** |
| Tier (per D97) | γ | γ | γ | δ | γ | **δ (>100 KB; 2nd Tier-δ event)** |
| Lock mechanism | D73 math-infeasibility | D78 math-infeasibility | D83 convergence-confirmed | D88 convergence-confirmed | D94 math-infeasibility | TBD (set during campaign) |
| Cycle ceiling | 9 | 8 | 5 | 7 | 8 | TBD (≤10 per D72) |
| Pattern E from C1 | No (cycle 4 first) | Cycle 4 first | **Yes** | **Yes** | **Yes** | **Yes** |
| Sleeper-bug stress | C8 | C8 | C4 | C4 | C5 | **C5 (mandatory final)** |
| Pattern F at close-out | N/A | N/A | N/A | **Retroactive** | **First production** | **Mandatory** |

Round 8 follows the established R5/R6/R7 cadence: Pattern E from cycle 1 + sleeper-bug stress mandatory final + Pattern F at close-out. **Self-classification**: R8 total deliverable ~130 KB → Tier δ per D97 (2nd Tier-δ event after R6 110 KB). Cadence remains Tier γ until 2nd Tier-δ event provides convergent evidence — Round 8 IS that 2nd event; post-Round-8 the Tier δ cadence row in § 6.3 + 8.E will be updated based on observed outcome.

---

## § 1 — Cross-cutting self-improvement conventions

### 1.1 The discipline loop

```
Round N close-out
   ↓
[1] udm-retrospective-collector — append per-reviewer-event row to _reviewer_effectiveness.md
   ↓
[2-6 run in parallel — they READ the ledger; they don't modify it]
[2] udm-specialty-tuner — read ledger trends; identify specialties needing refinement; propose deltas
[3] udm-subclass-accumulator — scan Round-N 🔴 findings; propose new Pitfall #9 sub-class if 2-event evidence base
[4] udm-producer-checklist-evolver — identify bug classes reviewers consistently catch that producer Gate 1 misses
[5] udm-cycle-cadence-optimizer — compute optimal cycle cadence per artifact-complexity tier
[6] udm-cascade-audit-evolver — scan Pattern F findings; propose Layer 1 trigger additions if new gap classes emerge
   ↓
[7] User-review session — ONE session per round; pipeline lead reviews ALL proposed deltas at once; approves YES/NO PER DELTA within the session (N-of-M deltas approved in one batch decision)
   ↓
[8] udm-agent-prompt-versioner — apply approved batch (the N-of-M deltas that received YES); archive prior version; bump semver; append changelog. Skips deltas marked NO.
   ↓
Round N+1 begins with refined sub-agent corpus
```

**Cost per round**: 7 skill invocations (1 collector + 5 analysis + 1 versioner; ~2-5 min each) + 1 user review session (~10-15 min). Total: ~30-40 min per round close-out.

**Cost before this discipline (Rounds 1-7)**: each optimization required user-identifies-issue → user-asks-Claude-to-fix → user-approves-implementation = 3 round-trips per optimization (~30 min per round × ~2 optimizations per round = ~60 min × 7 rounds = 7 hours over Phase 1).

**Break-even**: round 8+. Self-improvement loop pays for itself after ~3 rounds of operation (Phase 2 first 3 rounds; or final 3 Phase 1 rounds if Round 8 had been earlier).

### 1.2 Skill output format (mechanical structure)

All 7 skills emit Markdown deltas with this structure (enforced by D55 Gate 1 + skill template):

```markdown
# <skill-name> output for Round <N>

## Date: <YYYY-MM-DD>
## Confidence: HIGH / MEDIUM / LOW
## Sample size: <N events>
## Skill version: <semver>

## Findings

<one structured finding per row; categorized by severity ✅ / 🟡 / 🔴>

## Proposed deltas

<one per row; explicit before/after; cite the artifact and line>

## Justification

<brief; cites ledger evidence + threshold check>

## Reversibility

<one-line: predecessor archived at <path>; rollback procedure>

## User review required

<YES/NO; if NO, explain why (typically: change is fully auto per pre-approval rule)>
```

**Confidence scale**:
- **HIGH**: ≥10 events of evidence for the trend OR ≥3 rounds matching the pattern
- **MEDIUM**: 5-9 events OR 2 rounds matching
- **LOW**: <5 events OR single-round signal

If confidence is LOW, the skill flags it for human review with "consider waiting for more evidence" disclaimer. LOW-confidence deltas are NOT auto-applied even if user pre-approves.

### 1.3 Output storage

All skill outputs land at `docs/migration/_agent_evolution/<skill>-<round>-<date>.md`. Append-only (paralleling `_validation_log.md` discipline). Directory created at Round 8 close-out as part of the cascade.

### 1.4 Pre-flight checks every skill performs

Per D62 CCL + D55:
- Read `NORTH_STAR.md` + `HANDOFF.md` + `CURRENT_STATE.md` + `CHECKS_AND_BALANCES.md` (Stage 1)
- Read `_reviewer_effectiveness.md` + the round's `_validation_log.md` entry (Stage 2-3)
- Verify `03_DECISIONS.md` lock state — abort if proposed delta contradicts a locked D-number
- Verify the prior round's skill output exists (or note "first round" if Round 8 itself)

**Self-test**: each skill includes a Tier 0 stub in `tests/smoke/test_skill_<name>.py` per D67 — verifies skill loads + reads ledger + produces output without external deps. Stub is part of Round 8 deliverable.

### 1.5 Producer self-check (Pitfall #9 sub-class walk)

Per HANDOFF §8 sub-class accumulator, producer Gate 1 walks each sub-class against this spec doc BEFORE Gate 2 invocation:

- **9.a (column-name drift)**: N/A — this round produces no SQL DDL or canonical column lists
- **9.b (parameter-name drift)**: skill function signatures cited in § 2-§ 8 walked against intended Python contracts
- **9.c (enum-value drift)**: `Confidence: HIGH/MEDIUM/LOW` set verified; skill version semver convention verified
- **9.d (type-width drift)**: N/A
- **9.e (Unicode-vs-ASCII drift)**: N/A
- **9.f (cross-table column-name lift)**: N/A
- **9.g (Python keyword-only marker drift)**: skill function signatures use `def fn(*, ...)` where applicable per Round 3 D69 convention
- **9.h (wrong section number with invented description)**: all `§ X.Y` references walked; § 12 B-item triage verified
- **9.i (process-discipline-claim drift)**: 5-step audit at every cycle-N B-item modification per HANDOFF §8 directive — applied to § 11 B-item triage (§ 11.1 closures + § 11.2 deferrals + § 11.5 net-new items)
- **9.j (B-item status-render discipline; FORMALIZED THIS ROUND per § 12)**: every B-item cited in § 11 walked — leading badge MUST match inline status (closed inline = closed leading badge; otherwise 🟡 Open). Forward-references to future B-numbers (B160/B161 per § 11.5 "Round 8 net-new items") explicitly marked "anticipated" per 9.i directive Step 5.

Verified at producer self-check, NOT hedged for later verification.

### 1.6 Pre-existing tooling this round consumes

Round 8 builds ON, not REPLACES:
- `_reviewer_effectiveness.md` — Round 4 introduced; Round 5/6/7 populated. Round 8's 8.A automates further appends.
- HANDOFF §8 sub-class accumulator 9.a-9.i — Round 4-6 grew; Round 8's 8.C automates proposals + lands 9.j inline.
- Pattern E (5-agent) — Round 3 formalized; Round 8's 8.B + 8.E tune specialty composition.
- Pattern F (D89-D91) — Round 6 retrospective authored; Round 7 first-production validated. Round 8's 8.G monitors Pattern F trend; proposes Layer 1 trigger additions if new gap classes emerge.
- `udm-round-closeout` skill (D60) — Round 8 extends its checklist to invoke 8.A-8.F at close-out.

---

## § 2 — udm-retrospective-collector (skill 8.A)

### 2.1 Purpose

Auto-append per-reviewer-event rows to `_reviewer_effectiveness.md` at round close-out. Replaces manual orchestrator burden (Rounds 4-7 required manual ledger append after every cycle).

### 2.2 Invocation pattern

```
Trigger: round close-out (via udm-round-closeout skill Section 10.1 NEW Round 8 addition)
Input: round number; list of reviewer agentIds + specialties + cycle numbers + findings counts
Output: appended rows in _reviewer_effectiveness.md "Round N D72 N-cycle" section
```

### 2.3 Required input (gathered by orchestrator at round close-out)

Per cycle:
- `agentId` (from Agent tool invocation)
- `specialty` (one of: `column-walk` / `cross-reference` / `internal-consistency` / `D72-edge-cases` / `advisory-research` / `comprehensive-5-gate` / `sleeper-bug-stress` / `convergence-verification` / `feasibility-Tier0` / `mechanical-fix` / `cascade-audit`)
- `mode` (`Pattern-E` / `single-agent` / `Pattern-F-Layer-2-paired`)
- `🔴 count` + `🟡 count`
- `wall-clock minutes` (from task notification timing)
- `cross-reference` (validation log entry pointer)

### 2.4 Output format

Appends one row per event to the "Round N D72 N-cycle campaign" table per existing `_reviewer_effectiveness.md` schema (per § 9 of that doc):

```
| AgentId | Cycle | Specialty | Mode | 🔴 | 🟡 | Min | Subsequent | False-clean | Cross-ref |
```

Plus, at end of round section:
```
**Cumulative Round N**: <total 🔴> caught + <total 🟡>; <N> reviewer-agent events; <N> false-clean events.
```

### 2.5 Backward-update rule (per `_reviewer_effectiveness.md` § "Backward-update rule")

When cycle N+M discovers a bug in region X that cycle N's reviewer cleared:
- Skill receives the discovery event from the orchestrator
- Looks up cycle N's row; updates `Subsequent-cycle findings` count + `False-clean signal` field
- Appends "Correction note" sub-row referencing discovering cycle
- Does NOT edit original verdict (append-only audit trail)

### 2.6 Schema validation

Skill verifies every appended row has all 10 schema fields populated. Missing field → 🔴 abort; orchestrator must provide.

### 2.7 Confidence

ALWAYS HIGH — this skill is mechanical append, not trend analysis. No interpretation.

### 2.8 Edge cases

- **SI1** (missing agentId): orchestrator forgot to capture. Skill aborts 🔴; orchestrator must re-run cycle with capture.
- **SI2** (specialty enum drift): orchestrator passes unknown specialty (e.g., `column-walks` plural). Skill aborts 🔴 with valid-enum list.
- **SI3** (cycle-out-of-order): round close-out gathers cycles 1, 2, 3 ... N; skill verifies sequence. Out-of-order → 🔴.

### 2.9 Tier 0 stub (per D67 + § 1.4)

```python
# tests/smoke/test_skill_retrospective_collector.py
def test_retrospective_collector_smoke():
    """<5s; no external deps. Verifies skill loads, accepts valid event, rejects invalid specialty."""
    from skills.retrospective_collector import RetrospectiveEvent, append_round_section
    # Valid event
    event = RetrospectiveEvent(
        agentId="abc123", cycle=1, specialty="column-walk", mode="Pattern-E",
        red_count=0, yellow_count=0, minutes=10, subsequent_findings=0,
        false_clean=False, cross_ref="_validation_log.md round 8 entry"
    )
    assert event.is_valid()
    # Invalid specialty
    bad = RetrospectiveEvent(agentId="x", cycle=1, specialty="invented", mode="Pattern-E",
                              red_count=0, yellow_count=0, minutes=1, subsequent_findings=0,
                              false_clean=False, cross_ref="x")
    with pytest.raises(ValueError, match="unknown specialty"):
        bad.is_valid(strict=True)
```

---

## § 3 — udm-specialty-tuner (skill 8.B)

### 3.1 Purpose

Identify reviewer specialties with degrading effectiveness over time + propose prompt refinements. Reads `_reviewer_effectiveness.md` trend tables; flags any specialty crossing thresholds.

### 3.2 Invocation pattern

```
Trigger: round close-out (after retrospective-collector has appended; via udm-round-closeout Section 10.2 NEW Round 8 addition)
Input: round number; specialty-event ledger
Output: docs/migration/_agent_evolution/specialty-tuner-round<N>-<date>.md
```

### 3.3 Trend analysis algorithm

Per specialty (from `_reviewer_effectiveness.md` trend table):

1. **Read events to-date** (`Events to date` column)
2. **Compute false-clean rate** (`False-clean rate` column over events-to-date window)
3. **Threshold check**:
   - `false-clean rate > 25%` over ≥4 events → 🔴 RETIRE-OR-PAIR recommendation
   - `false-clean rate > 10%` over ≥6 events → 🟡 REFINE recommendation
   - `🔴 found / event` declining trend over 3 consecutive rounds → 🟡 EXHAUSTED-SURFACE recommendation
   - All clean + stable → ✅ NO ACTION
4. **Minimum-event guard**: if `events to date < 5`, skill output is `CONFIDENCE: LOW` regardless of computed signal — recommendations marked "consider waiting for more evidence"

### 3.4 Output structure

```markdown
# Specialty Tuner Output — Round N

## Date: YYYY-MM-DD
## Confidence: HIGH/MEDIUM/LOW
## Sample size: <N total events across <M> specialties>
## Skill version: v0.1.0

## Findings per specialty

### column-walk (7 events, 0% false-clean) — ✅ NO ACTION
Continue current prompt; mandatory in every Pattern E batch (HANDOFF §8 directive holds).

### comprehensive-5-gate (8 events, 2/8 = 25% false-clean) — 🟡 REFINE
Persistent false-clean on spec docs >50 KB. Proposed delta:
- BEFORE: "Walk all 5 gates against the artifact."
- AFTER: "Walk all 5 gates against the artifact. For spec docs >50 KB, walk Gate 1 (cross-reference) twice — once forward (this artifact's citations to canonical) and once reverse (canonical's citations expected here). Empirical evidence: false-clean rate 2/8 events post-walk; 0 false-clean post-walk + cross-cycle independent verification."
- Reversibility: prior prompt archived at `.claude/agents/_archive/udm-comprehensive-5gate-v0.1.0.md`

### sleeper-bug-stress (4 events, 0% false-clean) — ✅ NO ACTION
Mandatory final cycle confirmed across 4 rounds. Continue current prompt.

### advisory-research (5 events, 0 🔴 always) — ✅ NO ACTION
Distinct-value layer; non-overlapping with blocking reviewers. Continue.

## Proposed deltas

<summarize all 🟡 + 🔴 specialties; one delta per>

## User review required: YES (1 delta proposed)
```

### 3.5 Conservative bias

Skill ERRS toward "no action". A specialty with mixed signal (some events with 🔴, some without) but no clear false-clean pattern → 🟡 MONITOR (not 🟡 REFINE). Only proposes changes when threshold is unambiguously crossed.

### 3.6 Composition with Pattern E

Skill output may propose:
- **Composition change**: e.g., "swap comprehensive-5-gate slot for paired comprehensive-2-pass" in Pattern E batches
- **Threshold change**: e.g., "minimum events for column-walk verdict raise from 5 to 7" (already done implicitly per current trend table)
- **Specialty deprecation**: e.g., "feasibility-Tier0 has 1 event in 6 rounds; deprecate as standalone specialty; fold into column-walk"

User reviews; approves OR rejects per delta.

### 3.7 Edge cases

- **SI4** (specialty newly-introduced this round): if `events to date == 1`, skill output is `CONFIDENCE: LOW` + "first observation; no action yet"
- **SI5** (specialty with monotonic 🔴 count rise but 0% false-clean): rising catch rate is GOOD, not bad. Skill recognizes this as healthy.
- **SI6** (specialty with all-clean but never invoked): if a specialty has 0 events, skill output says "deprecate candidate" (paralleling feasibility-Tier0)

### 3.8 Tier 0 stub

```python
def test_specialty_tuner_smoke():
    from skills.specialty_tuner import analyze_specialty
    # All-clean specialty
    result = analyze_specialty(events=7, false_clean=0, recent_trend="stable")
    assert result.recommendation == "NO_ACTION"
    # Degrading specialty
    result = analyze_specialty(events=8, false_clean=2, recent_trend="false_clean_persistent")
    assert result.recommendation in ("REFINE", "RETIRE_OR_PAIR")
```

---

## § 4 — udm-subclass-accumulator (skill 8.C)

### 4.1 Purpose

Scan Round N's 🔴 findings; identify bug patterns appearing ≥2 times that don't match an existing Pitfall #9 sub-class (9.a-9.j). Propose new sub-class with first-evidence entry. Critical: this skill landed sub-class 9.i (R6) + 9.j (R8 close-out) — proves the discipline.

### 4.2 Invocation pattern

```
Trigger: round close-out (via udm-round-closeout Section 10.3 NEW Round 8 addition)
Input: round number; round's _validation_log.md entries with full 🔴 findings text
Output: docs/migration/_agent_evolution/subclass-accumulator-round<N>-<date>.md
```

### 4.3 Pattern-matching algorithm

For each 🔴 finding in Round N:

1. **Match against existing sub-class** by keyword search:
   - 9.a (column-name) — keywords: "column", "invented column", "canonical column"
   - 9.b (parameter-name) — keywords: "parameter", "@Verdict", "@AcknowledgmentOnly"
   - 9.c (enum-value) — keywords: "enum", "CHECK constraint", "status value"
   - 9.d (type-width) — keywords: "NVARCHAR(", "VARCHAR(", "DECIMAL(", "width"
   - 9.e (Unicode-vs-ASCII) — keywords: "NVARCHAR vs VARCHAR", "Unicode", "ASCII"
   - 9.f (cross-table lift) — keywords: "lift", "cross-table", "table A applied to table B"
   - 9.g (keyword-only marker) — keywords: "*,", "keyword-only", "PEP 3102"
   - 9.h (wrong section) — keywords: "section", "§", "invented section"
   - 9.i (process-discipline) — keywords: "false-closure", "stale B-range", "trailing summary", "silent omission"
   - 9.j (B-item status-render) — keywords: "leading badge", "inline annotation", "🟡 Open + CLOSED"

2. **Unclassified findings** (don't match 9.a-9.j) → potential new sub-class candidate

3. **Cluster unclassified by similarity** (e.g., 2 findings with "invented method signature", 1 with "missing import statement" — 2 of the 3 cluster as `9.k method-signature-drift`)

4. **Threshold check**:
   - ≥2 fresh instances of a cluster across 2+ rounds → 🟡 propose new sub-class
   - ≥3 fresh instances → 🔴 propose new sub-class with 5-step audit directive
   - Single-event cluster → 🟡 MONITOR (insufficient evidence)

### 4.4 Output structure

```markdown
# Sub-Class Accumulator Output — Round N

## Date: YYYY-MM-DD
## Confidence: HIGH/MEDIUM/LOW
## Sample size: <N 🔴 findings in Round N>

## Existing sub-class hits

- 9.a: <count> instances this round (cumulative: <count> rounds)
- 9.b: <count> instances this round
- ...

## New sub-class candidates

### Candidate 9.k — <descriptive name>

**Evidence**:
- Round X cycle Y: "<finding text>"
- Round X+1 cycle Z: "<finding text>"

**Pattern**: <inferred>

**Proposed sub-class entry for HANDOFF §8 sub-class accumulator**:
```
- **9.k — <name>**: <one-paragraph description with example>. First evidence: <round/cycle>. Tracked for HANDOFF wording strengthening as B<num>.
```

**Producer self-check directive**: <if applicable, 1-5 step audit>

**User review required**: YES

## Confidence: <HIGH if 3+ events; MEDIUM if 2 events; LOW if 1 event>
```

### 4.5 9.j formalization (THIS ROUND)

Round 8 close-out includes 9.j formalization (per B144 description):

```
- **9.j — B-item status-render discipline**: B-item entries showing leading status badge (e.g. `🟡 Open`) AND inline `**CLOSED YYYY-MM-DD**` annotation in the same row create render-discipline drift. The inline annotation is canonical; the leading badge stale. First evidence: R6 unscoped Pattern F audit 2026-05-11 (15+ B-items with stale-badge instances). Second evidence: R7 first-production Pattern F audit 2026-05-11 (7 simultaneous Round 7 in-scope items B79/B80/B81/B82/B93/B94/B128 + 4 newly-created items B147/B148/B149/B154 with same pattern at the close-out cascade itself). Tracked for HANDOFF wording strengthening as B144. **Producer self-check directive**: after ANY cycle-N or close-out edit that adds/closes a B-item: (1) verify leading badge `🟡 Open` / `⚫ Closed` matches inline annotation; (2) if mismatch, flip leading badge to canonical render. Add to existing 5-step 9.i audit as step 6.
```

This entry lands in HANDOFF §8 inline at Round 8 close-out per § 12 of this spec.

### 4.6 Tier 0 stub

```python
def test_subclass_accumulator_smoke():
    from skills.subclass_accumulator import classify_finding, propose_subclass
    # Match existing sub-class
    finding = "Round 6 cycle 2: § 12.1 trailing-summary count drift (B120-B129 said 22 items; only 20 in table)"
    assert classify_finding(finding) == "9.i"
    # Unclassified, single-event
    finding = "Round 8 cycle 1: method signature uses bare `def fn(arg)` but spec requires `def fn(*, arg)`"
    # First event → MONITOR, not new sub-class yet
    result = propose_subclass(findings=[finding])
    assert result.recommendation == "MONITOR"
```

---

## § 5 — udm-producer-checklist-evolver (skill 8.D)

### 5.1 Purpose

Identify bug classes reviewers consistently catch that producer Gate 1 self-check missed. Propose adding those classes as explicit producer pre-flight items.

### 5.2 Invocation pattern

```
Trigger: round close-out (via udm-round-closeout Section 10.4 NEW Round 8 addition)
Input: round N validation log entries; current producer self-check directives across HANDOFF §8 + spec doc § 1.5 templates
Output: docs/migration/_agent_evolution/producer-checklist-evolver-round<N>-<date>.md
```

### 5.3 Gap-detection algorithm

For each Round N 🔴 finding:
1. **Find the catching reviewer specialty** (from `_reviewer_effectiveness.md` row)
2. **Look up canonical producer self-check** (HANDOFF §8 sub-class directive OR spec doc § 1.5 walk)
3. **If producer self-check could have caught this** (e.g., column-walk sub-class 9.a — producer walks canonical columns; if producer walked it, the drift would have been caught at Gate 1, not Gate 2):
   - Cluster this 🔴 finding by missed-sub-class
   - If a sub-class is missed-by-producer ≥3 times across 2+ rounds → propose strengthening producer directive
4. **If only a reviewer specialty could have caught this** (e.g., advisory-research framing concern — producer doesn't have external-evidence access):
   - Tag as "reviewer-only specialty class"; skip

### 5.4 Threshold

- ≥3 producer-missable misses in ≥2 rounds → 🟡 propose directive strengthening
- ≥5 producer-missable misses in ≥3 rounds → 🔴 propose directive elevation (e.g., make it a hard pre-flight gate)

### 5.5 Output structure

```markdown
# Producer Checklist Evolver Output — Round N

## Date: YYYY-MM-DD
## Confidence: HIGH/MEDIUM/LOW

## Producer-missable 🔴 findings this round (and prior rounds with sub-class match)

### Sub-class 9.a — column-name drift
- Round 8 cycle 1: 3 instances (caught by column-walk)
- Cumulative across rounds: 18 instances (caught by column-walk)
- Producer self-check: HANDOFF §8 9.a directive exists; says "walk canonical columns"
- **Gap**: directive is generic; doesn't enumerate WHICH canonical tables to walk
- **Proposed delta**: add inline citation list ("For SP signature drafts, walk Round 1 §<N> SP-<N> parameters. For column-name drift, walk Round 1 §<N> Tables N-N column lists.")

## Proposed directive strengthenings: <count>
## User review required: YES (if ≥1 proposed)
```

### 5.6 Edge cases

- **SI7** (producer self-check exhausted): if a sub-class has 5+ producer-missable instances and the existing directive is already comprehensive, the proposal is "elevate to Gate 2 mandatory specialty" rather than "strengthen producer Gate 1"
- **SI8** (producer self-check too restrictive): if Round N producer self-check declined a valid pattern (false-positive), skill notes "directive over-fires; consider relaxing"

### 5.7 Tier 0 stub

```python
def test_producer_checklist_evolver_smoke():
    from skills.producer_checklist_evolver import identify_missed_subclasses
    findings = [
        {"red": "invented column LastHeartbeat", "caught_by": "column-walk", "sub_class": "9.a"},
        {"red": "invented column FileSizeBytes", "caught_by": "column-walk", "sub_class": "9.a"},
        # ...
    ]
    result = identify_missed_subclasses(findings, prior_rounds_data=[...])
    assert "9.a" in result.proposed_strengthenings
```

---

## § 6 — udm-cycle-cadence-optimizer (skill 8.E)

### 6.1 Purpose

Compute optimal cycle cadence per artifact-complexity tier based on cumulative evidence. Propose tier mapping (e.g., "spec docs >50 KB → Pattern E from cycle 1 + sleeper-bug stress mandatory").

### 6.2 Invocation pattern

```
Trigger: round close-out (via udm-round-closeout Section 10.5 NEW Round 8 addition)
Input: round N + prior rounds' cycle counts + trajectory shapes + sleeper-bug catches
Output: docs/migration/_agent_evolution/cycle-cadence-optimizer-round<N>-<date>.md
```

### 6.3 Complexity tier definition

Per Round 8 D97 lock proposal. **NOTE**: Tier α/β/γ/δ is a project-derived taxonomy, not an external SE standard — grounded in 7 rounds of empirical evidence (per R8C1-5 advisory framing).

| Tier | Definition | Recommended cadence (initial) | Empirical basis |
|---|---|---|---|
| Tier α (small) | Single-section artifact <10 KB | Single agent D56 2-pass | R2 D62 dog-food (1 first-pass + 1 second-pass = 2 cycles converged) |
| Tier β (medium) | Multi-section artifact 10-50 KB | Pattern E from cycle 1 + 2-3 verify cycles | R2 (no D72 ceiling needed; Pattern E first-cycle all-clean) |
| Tier γ (large) | Multi-section spec doc 50-100 KB | Pattern E from cycle 1 + sleeper-bug stress final + Pattern F close-out | R3 (80 KB, 9 cycles); R5 (75 KB, 5 cycles); R7 (50 KB, 8 cycles due to 9.i recurrence). Mean cycles 7.3; std-dev 2.1. Sleeper-bug + Pattern E from C1 + Pattern F mandatory final = canonical Tier γ cadence. |
| Tier δ (mega) | Mega-spec >100 KB OR mega-table inventory | Pattern E from cycle 1 + sleeper-bug stress final + math-infeasibility OR convergence-confirmed acceptance + Pattern F | R6 (110 KB, 7 cycles, convergence-confirmed) + R8 (~130 KB, 9 cycles, convergence-confirmed). 2-event tier base CONFIDENCE LOW per 8.E minimum-event guard (≥3 events required). Conservative cadence retained pending 3rd Tier-δ event. |

### 6.4 Trend analysis

Per round, compute:
- Artifact size (KB)
- Cycle count to convergence/acceptance
- Pattern E invocation count
- Sleeper-bug-stress cycle position
- Pattern F findings count

Track the trend:
- Rounds-per-tier convergence cycle count converging or diverging
- Carryover items per round (Pattern: R3 → ~28; R4 → ~29; R5 → ~12; R6 → ~22; R7 → ~10 — converging)

### 6.5 Output structure

```markdown
# Cycle Cadence Optimizer Output — Round N

## Date: YYYY-MM-DD
## Confidence: HIGH/MEDIUM/LOW
## Sample size: <N rounds>

## Per-tier cadence empirical fit

### Tier γ (large spec docs 50-100 KB) — 3 rounds of evidence
- R3: 80 KB → 9 cycles (math-infeasibility)
- R5: 75 KB → 5 cycles (convergence-confirmed)
- R7: 50 KB → 8 cycles (math-infeasibility; 9.i recurrence-driven)

Mean cycles: 7.3; std-dev: 2.1. Current recommendation (Pattern E from C1 + sleeper-bug final + Pattern F close-out) is empirically fitting. **NO CHANGE proposed**.

### Tier δ (mega-spec >100 KB) — 1 round of evidence
- R6: 110 KB → 7 cycles (convergence-confirmed)

Single event; CONFIDENCE: LOW. Recommendation: retain Tier γ cadence + math-infeasibility-acceptance fallback pending second event.

## Proposed deltas

<if applicable>

## Carryover trend monitoring (per B129)

R5 → R6 → R7 trajectory: 12 → 22 → 10 carryover items per round. Trend: stabilizing. No "compounding alarm" raised. (Threshold per B129: ≥24 items in any single round + monotonic rise → flag.)

## User review required: YES (if any deltas proposed) / NO (if all stable)
```

### 6.6 Composition with D72

Skill does NOT propose changing D72's 10-cycle ceiling or 3-consecutive-clean rule — those are canonical D-numbers. Skill MAY propose Tier-specific cadence WITHIN D72 (e.g., "for Tier α, set ceiling at 4 cycles; for Tier γ, keep 10").

### 6.7 Tier 0 stub

```python
def test_cycle_cadence_optimizer_smoke():
    from skills.cycle_cadence_optimizer import propose_tier_cadence
    round_data = [
        {"round": 3, "size_kb": 80, "cycles": 9, "outcome": "math-infeasibility"},
        {"round": 5, "size_kb": 75, "cycles": 5, "outcome": "convergence-confirmed"},
    ]
    result = propose_tier_cadence(round_data, tier="γ")
    assert result.confidence in ("LOW", "MEDIUM")  # Only 2 events for tier γ
```

---

## § 7 — udm-agent-prompt-versioner (skill 8.F)

### 7.1 Purpose

Every reviewer agent prompt (`.claude/agents/udm-*.md`) gets a version number + change-log. Prompt edits from skills 8.B-8.E require user approval. Superseded versions archived for audit.

### 7.2 Versioning convention (D98 lock proposal)

Semver `vMAJOR.MINOR.PATCH`:
- **MAJOR**: structural change (e.g., new mandatory tool, new mandatory output section)
- **MINOR**: directive addition (e.g., new sub-class added to producer self-check)
- **PATCH**: wording polish; example update; trivial fix

Frontmatter convention:
```yaml
---
name: udm-design-reviewer
description: ...
tools: Read, Grep, Glob, Bash
model: opus
version: v1.2.1
last_updated: 2026-05-11
changelog: docs/migration/_agent_evolution/udm-design-reviewer-changelog.md
---
```

### 7.3 Archive structure

`.claude/agents/_archive/`:
- `udm-design-reviewer-v1.0.0-2026-05-10.md`
- `udm-design-reviewer-v1.1.0-2026-05-11.md`
- `udm-design-reviewer-v1.2.0-2026-05-11.md`

Filename: `<name>-<version>-<date>.md`. Append-only.

### 7.4 Invocation pattern

```
Trigger: user APPROVES batch of deltas from 8.B / 8.C / 8.D / 8.E / 8.G proposals at round close-out
Input: approved deltas list; target agent prompt files
Output: 
  - Updated .claude/agents/<name>.md with bumped version + new content
  - Copy of pre-update version to .claude/agents/_archive/<name>-<prior-version>-<date>.md
  - Appended row in docs/migration/_agent_evolution/<name>-changelog.md
```

### 7.5 Changelog row format

```markdown
## v1.2.1 — 2026-05-11

**Source**: specialty-tuner Round 8 proposal accepted by pipeline lead 2026-05-11
**Change type**: PATCH
**Delta**:
- Section "Pre-flight": added "For spec docs >50 KB, walk Gate 1 (cross-reference) twice — once forward, once reverse."

**Rationale**: comprehensive-5-gate specialty showed 2/8 false-clean across Rounds 4-7. Two-pass cross-reference is the structural fix per specialty-tuner skill output 2026-05-11.

**Tested at**: Round 8 close-out cascade; no regressions found.
**Reversible**: yes — prior v1.2.0 archived at `.claude/agents/_archive/udm-design-reviewer-v1.2.0-2026-05-11.md`
```

### 7.6 Rollback procedure

If a versioned prompt's first-round-after-update shows regression (e.g., false-clean rate jumps, NEW bug class introduced):
1. User invokes rollback at next round close-out OR mid-round if severity high
2. Skill copies `_archive/<name>-<prior-version>-<date>.md` back to `.claude/agents/<name>.md`
3. Changelog appended with "REVERTED to vX.Y.Z; reason: <regression evidence>"
4. Failed delta documented + analyzed at next 8.B invocation

### 7.7 User approval gate

Per Round 8 D95 umbrella: skill 8.F NEVER applies a delta unless user has explicitly approved it. The discipline is user-review-ONE-SESSION-per-round, NOT user-review-per-delta-individually. In that ONE session, pipeline lead reviews ALL deltas + approves YES/NO PER DELTA within the session. 8.F then applies the N-of-M deltas that received YES; skips deltas marked NO.

### 7.8 Tier 0 stub

```python
def test_agent_prompt_versioner_smoke():
    from skills.agent_prompt_versioner import bump_version, archive_prior
    assert bump_version("v1.0.0", "MINOR") == "v1.1.0"
    assert bump_version("v1.1.0", "PATCH") == "v1.1.1"
    assert bump_version("v1.1.1", "MAJOR") == "v2.0.0"
```

---

## § 8 — udm-cascade-audit-evolver (skill 8.G; B143 implementation)

### 8.1 Purpose

Scan Pattern F findings across rounds; propose Layer 1 trigger additions if new cascade-gap classes emerge. Pattern F counterpart to 8.C (subclass-accumulator is for Pattern E findings; this is for Pattern F).

### 8.2 Invocation pattern

```
Trigger: round close-out AFTER Pattern F invocation completes (via udm-round-closeout Section 10.6 NEW Round 8 addition)
Input: Round N Pattern F findings (both Layer 1 deterministic-script results + Layer 2 paired-agent reports)
Output: docs/migration/_agent_evolution/cascade-audit-evolver-round<N>-<date>.md
```

### 8.3 Trigger-pattern detection algorithm

For each Pattern F 🔴 finding:
1. **Match against existing Layer 1 trigger** (Trigger C / D / F):
   - C — stale references
   - D — forward-cite resolution
   - F — aggregate-doc freshness
2. **Match against existing Layer 2 trigger** (Trigger A / B / E):
   - A — D-acceptance substantiation
   - B — B-item closure-target audit
   - E — CLAUDE.md convention registration
3. **Unmatched findings** → potential new trigger candidate

### 8.4 Threshold

- ≥2 unmatched findings across 2 rounds → 🟡 propose new Layer 1 OR Layer 2 trigger
- ≥3 unmatched findings → 🔴 propose new trigger + Layer 1 script implementation OR Layer 2 prompt strengthening

### 8.5 Output structure

```markdown
# Cascade Audit Evolver Output — Round N

## Date: YYYY-MM-DD
## Confidence: HIGH/MEDIUM/LOW
## Sample size: <N Pattern F events (R6 retroactive + R6 unscoped + R7 first-production + R8 close-out = 4 events at Round 8)>

## Per-trigger hit count

- Trigger A (D-acceptance substantiation): <N> hits this round; <N> cumulative
- Trigger B (B-item closure-target audit): <N> hits this round; <N> cumulative
- ...

## New trigger candidates

### Candidate Trigger G — <descriptive name>
**Evidence**:
- R6 unscoped: "<finding>"
- R7 first-production: "<finding>"

**Pattern**: <inferred>

**Proposed Layer 1 script addition** (if deterministic):
<Python regex / structure check>

**Proposed Layer 2 agent prompt strengthening** (if judgment-class):
<one-paragraph addition to udm-cascade-auditor.md mandate>

**User review required**: YES (if ≥2 events evidence base)
```

### 8.6 Composition with Pattern F D89-D91

Skill does NOT modify D89/D90/D91 canonical (those are locked). Skill MAY propose:
- Adding trigger G to D91 (`tools/verify_cascade.py`) script
- Adding trigger H to D90 (`udm-cascade-auditor.md`) agent mandate
- Acknowledging that some 🔴 findings are class-A or class-B (already triggered)

If a NEW trigger is approved, it goes through D-numbered decision recording (e.g. D-future) — skill doesn't bypass decision governance.

### 8.7 Tier 0 stub

```python
def test_cascade_audit_evolver_smoke():
    from skills.cascade_audit_evolver import classify_finding
    finding = "NORTH_STAR.md decision list missing D89-D91"
    assert classify_finding(finding) == "Trigger F"  # aggregate-doc freshness
    finding = "BACKLOG B146-B155 silent omission despite cascade-claim of addition"
    # Not Trigger F, not Trigger A, not Trigger B, not Trigger C, not Trigger D, not Trigger E
    # Closest match: Trigger B (B-item closure-target audit) — silent OMISSION is opposite of false-closure
    # Could be a sub-trigger or new trigger
    assert classify_finding(finding) in ("Trigger B", "NEW")
```

---

## § 9 — SELF_IMPROVEMENT_DISCIPLINE.md meta-doc

### 9.1 Purpose

Meta-document at `docs/migration/SELF_IMPROVEMENT_DISCIPLINE.md` (NEW file at Round 8 close-out) explaining the discipline loop end-to-end. Reader audience: future agents picking up the project + pipeline lead reviewing at quarterly cadence.

### 9.2 Structure (Stage-3 read for any agent invoking self-improvement skills)

```markdown
# Self-Improvement Discipline

## Purpose
Make the validation system self-tuning without abandoning human-in-the-loop control.

## How it works

1. Every round produces a `_reviewer_effectiveness.md` trail (via 8.A retrospective-collector)
2. At round close-out, 6 skills analyze the trail + the round's 🔴 findings + Pattern F findings
3. Skills propose deltas; pipeline lead reviews; 8.F versioner applies approved deltas

## Bounds (escape conditions)

If any of these trigger, FREEZE the loop and escalate to human:
- Specialty effectiveness DECLINES 2 rounds in a row
- New 🔴 bug class introduced by a recently-applied delta
- Carryover items per round monotonically rising for 3+ rounds (B129 trigger)
- User declines 50%+ of proposed deltas in 2 consecutive rounds (signal: skills are noisy)
- Any skill's output 🔴 cited a locked D-number contradiction

## Bounds (auto-revert conditions)

If a delta is applied and round N+1's first cycle shows regression in the same surface:
- 8.F auto-reverts to prior version
- Changelog appended with regression evidence
- Failed delta becomes input to next 8.B/8.C/8.D/8.E invocation (so they learn from the failure)

## Lifecycle

- Authored: Round 8 close-out 2026-05-11
- First live invocation: NEXT round close-out (Phase 2 Round 1)
- Quarterly review: pipeline lead reviews ALL agent prompts + skill outputs per `MAINTENANCE.md`
- Disablement: if loop is FROZEN per escape condition AND not unfrozen within 1 quarter, deprecate per D-numbered decision

## Decisions

- D95 (umbrella discipline)
- D96 (sub-class 9.j formalization landed at Round 8 close-out)
- D97 (cycle-cadence-optimizer tier mapping)
- D98 (agent prompt versioning convention)
- D99 (Round 8 acceptance)

## Cross-references

- `_reviewer_effectiveness.md` — the evidence ledger
- HANDOFF §8 sub-class accumulator — the bug taxonomy
- `MULTI_AGENT_GUIDE.md` § Pattern E + Pattern F — the validation patterns this tunes
- `MAINTENANCE.md` quarterly review cadence
- `CHECKS_AND_BALANCES.md` — the discipline this tunes (without replacing)
```

### 9.3 Pillar mapping (per D61)

| Pillar | Contribution |
|---|---|
| Audit-grade | Every prompt change versioned + decision-recorded + changelog-tracked |
| Traceability | Ledger trends back to every prompt iteration; reversibility preserved |
| Idempotent | Reverting to prior version is mechanical (file copy + version bump down) |
| Operationally stable | Discipline self-maintains without manual optimization cycles |
| $120K/year ceiling | Bounded compute (skills run at close-out only; not per cycle) |

### 9.4 Anti-patterns this doc rejects

- ❌ Autonomous prompt rewriting — human review preserved
- ❌ Continuous tuning — skills run at close-out only; no mid-round changes
- ❌ Removing existing producer self-check directives — discipline accumulates, doesn't replace
- ❌ Bypassing D72 termination rule — skills propose calibration WITHIN D72; never replace it

---

## § 10 — Edge case mapping (SI-series for "self-improvement")

New series: **SI** for self-improvement-discipline edge cases. 23 cases enumerated. Appended to `04_EDGE_CASES.md` at Round 8 close-out.

| ID | Description | Mitigation |
|---|---|---|
| SI1 | Missing agentId in retrospective-collector input | Orchestrator captures via Agent tool result; skill aborts 🔴 if absent (per § 2.8) |
| SI2 | Specialty enum drift on a KNOWN existing value (e.g., `column-walks` plural or `column_walk` underscore for canonical `column-walk` hyphen) | Skill validates against canonical enum list; aborts 🔴 with valid-enum error. **Distinct from SI4**: SI2 is misspelling/typo of an existing canonical value; SI4 is a NEW value that the orchestrator deliberately added. |
| SI3 | Cycle-out-of-order in close-out gather | Skill verifies cycle sequence; 🔴 if non-monotonic |
| SI4 | NEW specialty proposed by orchestrator (a value not in canonical enum but the addition is intentional, e.g., a new reviewer type) | Skill output `CONFIDENCE: LOW`; recommendation "first observation; no action". **Distinct from SI2**: SI4 is intentional addition; SI2 is unintentional typo. To distinguish, skill checks if value is in current enum (SI2) vs orchestrator-declared-new (SI4). |
| SI5 | Specialty with rising 🔴 catch rate but 0% false-clean — healthy, not unhealthy | Skill recognizes rising-catch as healthy signal; does NOT propose degrading recommendation |
| SI6 | Specialty never invoked (0 events EVER, across all rounds) | Skill output: "deprecate candidate" (paralleling current feasibility-Tier0 status). **Distinct from SI13**: SI6 is 0-event-ever; SI13 is LOW-confidence-persists (could be 1-4 events repeatedly). |
| SI7 | Producer self-check directive exhausted (cannot be strengthened further) | Skill proposes elevation to Gate 2 mandatory specialty rather than further directive |
| SI8 | Producer self-check over-fires (false-positive directive) | Skill notes "directive over-fires; consider relaxing"; flags for user review |
| SI9 | Skill output proposes change that contradicts locked D-number | Pre-flight check against `03_DECISIONS.md`; 🔴 abort with D-number cite |
| SI10 | Approved delta introduces fresh-instance bug class | 8.F auto-revert at next round close-out + failed-delta documented |
| SI11 | User declines 50%+ proposed deltas in 2 consecutive rounds (skill noisy) | FREEZE the loop per SELF_IMPROVEMENT_DISCIPLINE.md § Bounds |
| SI12 | Multiple skills propose conflicting deltas (e.g., 8.B says "strengthen comprehensive-5-gate", 8.E says "deprecate comprehensive-5-gate") | User adjudicates at review; both deltas documented; pipeline-lead decision recorded as D-numbered |
| SI13 | Skill confidence LOW persists for 3+ rounds (insufficient sample for any meaningful proposal — e.g., specialty consistently 1-4 events per round) | Skill output: "insufficient evidence accumulated; consider extending evidence horizon or deprecating skill"; SI6 covers strict-0-event case |
| SI14 | Cascade-audit-evolver finds Pattern F gap class not coverable by Layer 1 OR Layer 2 alone (requires both) | Propose joint Layer-1-script-extension AND Layer-2-prompt-strengthening with cross-reference |
| SI15 | Concurrent close-out invocations (multi-agent close-out coordination) | All 6 analysis skills are read-then-propose; only 8.F writes; serial invocation enforced by `udm-round-closeout` orchestrator |
| SI16 | Skill outputs older than 1 quarter become stale (skills not invoked between Phase rounds) | Quarterly review per `MAINTENANCE.md` re-grounds skills against current state |
| SI17 | **8.F archive-write atomicity failure** — applying delta + archive write are two file operations; if archive succeeds but main write fails (or vice versa), state is corrupt | Mitigation: archive-FIRST atomicity contract — copy current version to `_archive/` BEFORE applying delta; verify archive checksum; only then write main file. If main write fails after archive succeeds, leave archive in place (no rollback needed since main is unchanged) |
| SI18 | **8.F re-run idempotency** — same approved batch invoked twice (e.g., after partial failure recovery) | Skill checks current frontmatter `version:` field against expected post-apply version; if already at target version, skip with INFO log "already applied"; if at prior version, apply as normal. Idempotent re-run produces zero net writes |
| SI19 | **`.claude/agents/_archive/` unbounded growth** — over 10+ rounds × 7 skills × N versions, archive directory accumulates | Quarterly archive-compaction per MAINTENANCE.md; retain last 4 versions per agent (most recent 4 quarters); older archives compressed to single tar.gz per agent with date range. Tie to D30 7-year retention for legal/audit purposes |
| SI20 | User rejects ALL proposed deltas in a single round (100% NO) | Skill cascade exits gracefully; no writes; INFO log "no deltas approved this round"; round close-out continues normally. Does NOT trigger SI11 freeze (single-round signal only); SI11 needs 2 consecutive rounds of 50%+ reject |
| SI21 | **🔴 Pattern F frozen / D89/D90/D91 superseded** — 8.G (cascade-audit-evolver) attempts invocation against deprecated discipline | 8.G pre-flight check: if D89/D90/D91 status is ⚫ Superseded or framework FROZEN, skill ABORTS with INFO log "Pattern F discipline currently FROZEN; skipping 8.G this round". No-op until discipline unfrozen |
| SI22 | Standing pre-approval — user grants "all PATCH-level deltas auto-approved going forward" | NOT supported by current design (D95 hard rule: human-in-the-loop preserved per-delta per-round). If user requests this, escalate to D-numbered decision (e.g., D-future) before discipline change. Until then, every PATCH delta still requires per-batch approval |
| SI23 | Concurrent ledger edit corruption — `_reviewer_effectiveness.md` edited simultaneously by 8.A append + manual operator edit | 8.A acquires advisory file lock (POSIX `fcntl.flock` LOCK_EX) before append; on lock-contention, retries 3× then aborts 🔴 with "concurrent edit detected; orchestrator must serialize". Operator advised to commit manual edits BEFORE invoking close-out cascade |

Tracked at `04_EDGE_CASES.md` SI-series append (Round 8 close-out task).

---

## § 11 — B-item triage (B47-B159 cumulative)

Per D73 + D78 + D83 + D88 + D94 mandate, Round 8 close-out triages cumulative carryover. Round 7 closed 7 items (B79/B80/B81/B82/B93/B94/B128) per § 12 of `phase1/07_schema_evolution_governance.md`. Round 8 closes additional items here + classifies remainder.

### 11.1 In-round closures (Round 8 close-out cascade — applied prospectively at cascade completion)

These closures are SCHEDULED to land at Round 8 close-out cascade. The spec doc identifies the closure mechanism; the actual BACKLOG.md 🟡 → ⚫ flip happens at the cascade Section 6 aggregate-doc update step. Date stamp 2026-05-11 reflects close-out cascade completion date.

- **B129** — Round 8 candidate "carryover-compounding monitor" → IMPLEMENTED via 8.E cycle-cadence-optimizer carryover-trend section (§ 6.5). **CLOSING at Round 8 close-out cascade 2026-05-11**.
- **B143** — `udm-cascade-audit-evolver` 7th skill candidate → IMPLEMENTED as § 8 of this spec + `.claude/skills/udm-cascade-audit-evolver/SKILL.md`. **CLOSING at Round 8 close-out cascade 2026-05-11**.
- **B144** — Pitfall #9 sub-class 9.j formalization → LANDED INLINE per § 12 of this spec; HANDOFF §8 updated at close-out cascade Section 6. **CLOSING at Round 8 close-out cascade 2026-05-11**.
- **B145** — Pattern F unscoped audit remaining 🟡s deferred to Round 7 close-out (SKILLS_PLAN refresh + MAINTENANCE Pattern F + R28 + Pitfall #11 + BACKLOG priority view) → ADDRESSED via close-out cascade in Section 6. **CLOSING at Round 8 close-out cascade 2026-05-11**.
- **B155** — CLAUDE.md register evolved SP signatures + new SP-12 + MIGRATION_AUTOMIC_INVENTORY EventType + forward-only schema evolution discipline (B86-parallel) → ADDRESSED at Round 8 close-out cascade (CLAUDE.md is project root, edited as part of close-out per D93 cross-doc cascade). **CLOSING at Round 8 close-out cascade 2026-05-11**.

### 11.2 Round-8-deferred items (deferred to Phase 2 first round close-out)

These items don't fit Round 8 scope; carryover to Phase 2:

- **B146** — Append I23 + F25 + F26 + DP8 edge cases to 04_EDGE_CASES.md → DEFERRED to Phase 2 cutover work (closer to where the edge cases land in production)
- **B150** — SchemaContract row archival policy → DEFERRED to Phase 2 (when archival actually executes against 1+ rows of SchemaContract)
- **B151** — Round 4 § 3.6 + § 3.8 + § 3.9 RB-11 title cascade addenda → DEFERRED to Phase 2 round 1 (locked-artifact-touch — Round 4 spec doc is 🟢 Locked; cascading edits go through D40/D92 supersession governance)
- **B152** — Round 5 § 3-§ 4 add Tier 0+1 plans for SP-4 / SP-10 / SP-12 → DEFERRED to Phase 2 (test plan addenda go with implementation work)
- **B153** — Round 2 § 5.1 frozen-11 update → DEFERRED to Phase 2 (Round 2 spec doc 🟢 Locked; cascading edit per D92 supersession)
- **B156** — Re-ground § 7.3 ops-channel fallback order per SRE canonical → DEFERRED to Phase 2 implementation
- **B157** — Add Kimball SCD2 citation to SchemaContract framing → DEFERRED to Phase 2 implementation
- **B158** — Add CCPA pseudonymization rationale per IAB/GDPR Art 17 → DEFERRED to Phase 2 implementation
- **B159** — Add named-parameter calling-style note to § 1.2 SP signature evolution → DEFERRED to Phase 2 implementation

### 11.3 Audit-trail-only items (already addressed elsewhere)

These were closed in prior rounds; preserved here for cumulative audit:

- **B47-B76**: 27 items closed inline at Round 3 close-out + 3 items closed in subsequent rounds (B53/B58/B59/B61/B62/B65/B66 sub-set per BACKLOG L131-156)
- **B77-B107**: Round 4 carryover; subset closed inline at R4 + R5 + R6 close-outs per BACKLOG L289-327
- **B108-B119**: Round 5 carryover; subset closed at R6 close-out per BACKLOG L314-318
- **B120-B141**: Round 6 carryover; subset closed at R6 close-out + R7 close-out per BACKLOG L289-327
- **B142** — Round 7 close-out first production Pattern F invocation → CLOSED at Round 7 close-out 2026-05-11
- **B147-B149** — Round 7 D92/D93 lockdowns + R29/R30 RISKS additions → CLOSED at Round 7 close-out 2026-05-11
- **B154** — 02_PHASES.md Phase 0 deliv 0.20 + frozen-11 amendment → CLOSED at Round 7 close-out 2026-05-11

### 11.4 Outside-scope items (long-term, not active)

- **B16-B18** — Pillar mapping backfill on D1-D60 + cross-reference audit tool + per-decision risk classification → ALL Phase 6 maintenance work (low priority; outside Phase 1 scope)
- **B66 / B67 / B71** — Optional architectural refactors per Round 6 § 7.12 re-deferral → DEFER to post-Round-8 cleanup phase

### 11.5 Round 8 net-new items (added at close-out)

Round 8 close-out adds new B-items B160+ via the close-out cascade:

- **B160** (anticipated): Round 8 close-out — first production self-improvement loop invocation at Phase 2 R1 close-out. Lock criteria: skills produce structured deltas; pipeline lead reviews; 8.F applies approved batch with zero regression in subsequent round. **WSJF 2.0** (COD 2, JS 1).
- **B161** (anticipated): Future skill candidate — `udm-edge-case-evolver` — monitors edge case register growth + proposes consolidation when a series exceeds 20 entries. Round 9+ scope (Phase 2). **WSJF 1.0**.

(Additional B-items added during Round 8 D72 validation cycles via close-out cascade.)

### 11.6 Triage summary

| Disposition | Count | Cumulative B-range |
|---|---|---|
| Closed in Round 8 (this round) | 5 | B129/B143/B144/B145/B155 |
| Deferred to Phase 2 | 9 | B146/B150-B153/B156-B159 |
| Audit-trail (closed prior) | ~30 | B47-B76 subset + B77-B107 subset + B108-B119 subset + B120-B141 subset + B142+B147-B149+B154 |
| Outside-scope (Phase 6+) | ~6 | B16-B18 + B66/B67/B71 |
| New items added Round 8 | 2+ | B160+ |

---

## § 12 — Pitfall #9 sub-class 9.j formalization (B144)

### 12.1 Evidence base (2-event empirical, per HANDOFF §8 sub-class accumulator threshold)

**Event 1 — R6 unscoped Pattern F audit (2026-05-11)**:
15+ B-items in `BACKLOG.md` showed `🟡 Open` leading badge with `**CLOSED YYYY-MM-DD**` inline annotation. Pattern F INSTANCE 2 explicitly surfaced this as a systemic render-discipline gap (per `_reviewer_effectiveness.md` line 270: "B-item-status-render discipline gap (~15 entries with leading badge stale vs inline annotation)").

**Event 2 — R7 first-production Pattern F audit (2026-05-11)**:
7 simultaneous Round 7 in-scope items (B79/B80/B81/B82/B93/B94/B128) + 4 newly-created items (B147/B148/B149/B154) showed same `🟡 Open` leading + inline-closed pattern at the close-out cascade itself. Per `BACKLOG.md` L17-18 acknowledgment: "Status-render convention (clarified 2026-05-11 per Pattern F unscoped audit finding)".

### 12.2 Pattern (structural-not-coincidental)

Round close-out is high-velocity: producer adds many B-items in rapid sequence at the end of a round. When a B-item is added with `🟡 Open` badge then closed in-cycle, producer adds `**CLOSED YYYY-MM-DD**` inline (which is faster than flipping the badge). The badge is left stale. Mass-flipping badges at the end of close-out cascade is itself error-prone (mass edit → cascade-fresh-instance per Pitfall #9.i).

### 12.3 Formal sub-class entry (LANDED at Round 8 close-out in HANDOFF §8)

```
- **9.j — B-item status-render discipline (formalized 2026-05-11 at Round 8 close-out per B144)**: 
  B-item entries showing leading status badge (e.g. `🟡 Open`) AND inline `**CLOSED YYYY-MM-DD**` 
  annotation in the same row create render-discipline drift. The inline annotation is canonical; 
  the leading badge stale. 
  
  **First evidence**: R6 unscoped Pattern F audit 2026-05-11 (15+ B-items with stale-badge instances). 
  **Second evidence**: R7 first-production Pattern F audit 2026-05-11 (7 simultaneous Round 7 in-scope 
  items B79/B80/B81/B82/B93/B94/B128 + 4 newly-created items B147/B148/B149/B154). 
  Tracked for HANDOFF wording strengthening as B144. 
  
  **Producer self-check directive**: after ANY cycle-N or close-out edit that adds/closes a B-item:
  (1) verify leading badge `🟡 Open` / `⚫ Closed` matches inline annotation;
  (2) if mismatch, flip leading badge to canonical render — `🟡 Open` only if NOT inline-closed; 
  `⚫ Closed` if inline-closed AND completion date documented.
  Add this as step 6 to existing 5-step 9.i audit.
  
  **Structural fix**: skill 8.F `udm-agent-prompt-versioner` + Pattern F Layer 1 trigger extension 
  (proposed by 8.G `udm-cascade-audit-evolver`) covers programmatic detection. At Round 8 close-out, 
  candidate-Trigger G (B-item status-render consistency) gets evaluated for Layer 1 inclusion 
  (per § 8.5 of this spec).
```

### 12.4 Cumulative Pitfall #9 sub-class status (post-Round-8)

**Column units note**: "instances" = total recurring drift count across rounds; "events" = round-level batches where the sub-class recurred. 9.j has 2 ROUND-events (R6 unscoped + R7 first-production) totaling ~26 INSTANCES.

| Sub-class | First evidence | Instances to date | Status |
|---|---|---|---|
| 9.a column-name | D49 v2→v3 | ~18 | Formalized |
| 9.b parameter-name | R2 second-pass | ~12 | Formalized |
| 9.c enum-value | R2 second-pass | ~8 | Formalized |
| 9.d type-width | R3 second-pass | ~6 | Formalized |
| 9.e Unicode-vs-ASCII | R3 second-pass | ~4 | Formalized |
| 9.f cross-table-lift | R3 cycle 4 | ~6 | Formalized |
| 9.g keyword-only marker | R4 cycle 3 | ~7 | Formalized |
| 9.h wrong-section-cite | R4 cycle 8 | ~5 | Formalized |
| 9.i process-discipline | R5 + R6 + R7 cycles 2/3/5/6/7 | ~13 (across 3 ROUND-events) | Formalized (R6 close-out) |
| **9.j B-item status-render** | R6 unscoped + R7 first-production Pattern F | ~26 instances across 2 ROUND-events | **FORMALIZED at Round 8 close-out (THIS ROUND)** |

10 sub-classes formalized. Round 9+ may surface 9.k+ via 8.C subclass-accumulator.

---

## § 13 — Validation gates self-check

### 13.1 Gate 1 — Cross-reference

| Check | Pass criterion | Verdict |
|---|---|---|
| D-numbers cited (D95-D99) | All match status / scope in `03_DECISIONS.md` (will lock at close-out) | ✅ Pending close-out |
| Pattern F cited (D89-D91) | Locked 2026-05-11 per HANDOFF §3 | ✅ |
| Cited D-numbers don't contradict | Walked NORTH_STAR pillar mapping (§ 9.3) | ✅ |
| BACKLOG items cited (B47-B159) | Walked per § 11 disposition table | ✅ |
| `_reviewer_effectiveness.md` schema cited | Walked per § 2 schema | ✅ |
| HANDOFF §8 sub-class accumulator | Walked per § 1.5 + § 12 | ✅ |

### 13.2 Gate 2 — Quality assurance (independent review)

Round 8 D72 validation campaign with Pattern E from cycle 1 (per R5/R6/R7 precedent). Triggered post-draft.

### 13.3 Gate 3 — Edge case enumeration

NEW series **SI** (self-improvement) introduced per § 10. 23 cases enumerated (SI1-SI23 — extended from initial 16 to 23 at Round 8 cycle 2 per R8C1-4 proposals SI17-SI23). M/S/I/N/P/G/D/F/V series walked — N/A for this spec doc (no SQL/schema content); applicable cases are at lower abstraction (covered in Rounds 1-7 where DDL + SP + module code lived).

### 13.4 Gate 4 — Edge case validation

Each SI-N case has explicit mitigation cited in § 2-§ 8 skill sections. Tier 0 stubs per § 2.9 / § 3.8 / § 4.6 / § 5.7 / § 6.7 / § 7.8 / § 8.7 provide build-time verification.

### 13.5 Gate 5 — Idempotency / regression

| Check | Verdict |
|---|---|
| D15 invariant preserved | ✅ (skills are read-then-propose; only 8.F writes; user-approved batch → mechanical apply; idempotent if re-run with same approvals) |
| D72 not contradicted | ✅ (skills propose calibration WITHIN D72; never replace) |
| Pattern E not contradicted | ✅ (8.B refines specialty composition WITHIN Pattern E) |
| Pattern F (D89-D91) not contradicted | ✅ (8.G refines Layer 1 trigger set WITHIN Pattern F; canonical D89/D90/D91 locked) |
| Producer self-check (HANDOFF §8) not contradicted | ✅ (8.C extends sub-class list; 8.D strengthens directives; never replaces) |
| `_reviewer_effectiveness.md` schema not contradicted | ✅ (8.A appends per existing schema; no schema mutation) |
| Locked-artifact discipline (D40 + D92) | ✅ (no locked artifact edited in place; cascading changes go through supersession governance per D93) |
| Master idempotency invariant (D15) | ✅ (re-running close-out with same inputs produces same skill outputs; user approval is the new state; applied deltas are append-only via 8.F archive) |

### 13.6 Pillar contribution (per D61)

| Pillar | Round 8 contribution |
|---|---|
| Audit-grade | Every prompt change versioned + decision-recorded (D98); changelogs append-only |
| Traceability | Ledger trends to every prompt iteration; reversibility via archived versions |
| Idempotent | Discipline self-reverts on regression (per § 7.6 rollback); user-approved deltas are append-only |
| Operationally stable | Self-tuning preserves discipline quality across rounds; no manual optimization needed |
| $120K/year ceiling | Bounded compute (close-out only; not per cycle); no Snowflake spend |

### 13.7 Risk delta (anticipated)

- 🆕 NEW: **R31** — Self-improvement loop introduces feedback-loop instability (Likelihood Low × Impact High = 3). Mitigation: trend-metric monitoring per § 9.2 SELF_IMPROVEMENT_DISCIPLINE.md Bounds + auto-revert per § 7.6 + freeze condition per § 9.2.
- 🟡 PROPOSED-PENDING-EVIDENCE: **R03** (single-engineer Python expertise bus factor) — once self-improvement loop is operational in Phase 2, agent-quality preservation may reduce bus-factor weight. Proposed score reduction: Medium × High = 6 → Medium × Medium = 4. **NOT** de-escalated yet — awaiting first round's loop operation in Phase 2.
- 🟡 PROPOSED-PENDING-EVIDENCE: **R11** (validation discipline drift) — self-improvement loop intends to actively counteract drift via 8.D producer-checklist-evolver. Score remains 4; de-escalation eligible after Phase 2 first-loop-invocation provides evidence.

### 13.8 Backlog surfacing (per D61)

Round 8 net-new B-items proposed per § 11.5; finalized at close-out per cumulative cycle findings.

---

## § 14 — Cycle log (populated during D72 campaign)

| Cycle | Type | Reviewer(s) | 🔴 | 🟡 | Outcome |
|---|---|---|---|---|---|
| R8C1 | Pattern E 5-agent | R8C1-1 column-walk + R8C1-2 cross-reference + R8C1-3 internal-consistency + R8C1-4 D72-edge-cases + R8C1-5 advisory-research | 5 (3 from R8C1-1 + 2 from R8C1-3) | ~10 + 6 advisory framing | NOT CLEAN; cycle 2 fix-cycle required |
| R8C2 | Fix-application (implicit, by orchestrator) | producer | — | — | Cycle-1 🔴 fixes applied across spec doc + 7 skill files |
| R8C3 | Comprehensive-5-gate verify | R8C3 single-agent | 1 (Pitfall #9.i fix-fresh-instance: § 12.5 invented section number sibling drift) + 1 🟡 (Section 4.x retained in spec doc after skill files updated to Section 10.x) | 0 | NOT CLEAN; 6th-consecutive 9.i recurrence empirically continues structural pattern (R6 cycles 2/3/5/6/7 + R8 cycle 3) |
| R8C4 | Fix-application (implicit) | producer | — | — | § 12.5 → § 11; § 4.7-4.11 → Section 10.x in spec doc; SI17-SI23 added; § 13.3 count updated; § 13.7 R03/R11 framing fixed |
| R8C5 | Sleeper-bug stress (mandatory final per R4C8 + R5C4 + R6C4 + R7C5 = 4-event precedent → R8C5 extends to 5 events) | R8C5 single-agent | 3 (R8C5-1 Section 10.x non-existent in udm-round-closeout + R8C5-2 cross-skill ordinal inconsistency + R8C5-3 prospective-closure-as-past-tense 9.j class) | 4 | NOT CLEAN; sleeper-bug catch extends specialty's 100% catch rate to 5 events |
| R8C6 | Fix-application | producer | — | — | Section 10 ADDED to udm-round-closeout SKILL.md with sub-sections 10.1-10.8; 7-skill ordinal numbering aligned (1/2/3/4/5/6/7 of 7); § 0.5 self-classification Tier δ acknowledged; § 14 cycle log populated; BACKLOG.md Round 8 closures section added flipping B129/B143/B144/B145/B155 inline-CLOSED + 9.j sub-class formalization landed at HANDOFF §8 inline |
| R8C7 | Final convergence verification (1st attempt) | R8C7 single-agent | 2 (Pitfall #9.i fix-fresh-instance from cycle 6 mechanical-fix-ADDS-content: § 2.2 L191 stale "Section 4.6 — NEW" sibling miss + § 7.4 L664 silent omission of 8.G in delta source list) | 0 | NOT CLEAN; cycle 8 fix-cycle required |
| R8C8 | Fix-application | producer | — | — | Spec doc L191 → "Section 10.1 NEW Round 8 addition"; L664 → 8.G added to source list. 2 surgical edits only. |
| R8C9 | Final convergence verification (2nd attempt, post-cycle-8 fix) | R8C9 single-agent | 0 | 0 | ✅ CLEAN — all 5 verifications pass. Trajectory 5 → 1 → 3 → 2 → 0 → 0 with sleeper-bug stress + fix-fresh-instance both caught + verified clean. D99 acceptance variant: CONVERGENCE-CONFIRMED per D83/D88 precedent. 9 cycles consumed of D72 ceiling 10. |
| R8-PF-INST1 | Pattern F Layer 2 paired (2nd production per D89; at close-out cascade) | cascade-auditor instance 1 (agentId `a3c945444b494db86`) | 0 (1 🟡 SI-series CLAUDE.md gap + 2 candidate Trigger G/H) | 1 🟡 | ✅ CLEAN — paired-judgment convergence found |
| R8-PF-INST2 | Pattern F Layer 2 paired (2nd production per D89; at close-out cascade) | cascade-auditor instance 2 (agentId `a10d4c8f5d0577771`) | 1 🔴 (B155 false-closure — CLAUDE.md missing SP-4/SP-10/SP-12 + MIGRATION_AUTOMIC_INVENTORY + forward-only schema discipline) + 2 🟡 framing + 3 candidate Triggers G/H/I | 5 🟡 | 🔴 → cascade fix-cycle applied 2026-05-11: CLAUDE.md extended with Round 7 SP signatures + MIGRATION_AUTOMIC_INVENTORY canonical value + forward-only schema evolution discipline + SI series. Pattern F structural validation: paired-judgment caught B155 that INSTANCE 1 missed — empirically substantiates R28 mitigation thesis. |

**Round 8 D72 campaign summary**: 9 review cycles + 4 fix cycles = 9-cycle effective campaign. **11 cumulative 🔴 caught + fixed** (5 + 1 + 3 + 2 across review cycles). Sleeper-bug stress caught + fix-fresh-instance caught + final-verify clean — three-stress-event evidence pattern matches R5 D83 convergence-confirmed precedent. **D99 acceptance variant: CONVERGENCE-CONFIRMED** (3rd invocation of D83/D88 variant; distinct from D73/D78/D94 math-infeasibility variant).

(Cycle log mirrors R5/R6/R7 § 14 + `_validation_log.md` Round 8 entry. Pattern F entries appended at close-out cascade Section 9.)

---

## Owner

Pipeline lead. Round 8 is last Phase 1 round. Next: Phase 1 acceptance criteria check + Phase 2 kickoff.

## Last updated

2026-05-11 (Round 8 🟢 Locked via D99 convergence-confirmed acceptance per D83/D88 precedent. 9-cycle Pattern E campaign with sleeper-bug stress C5; trajectory 5→1→3→2→0→0; 11 cumulative 🔴 caught + fixed. Pattern F 2nd-production at close-out caught + fixed 1 🔴 (B155 false-closure via paired-judgment INSTANCE 2) + 1 🟡 (SI-series CLAUDE.md gap via INSTANCE 1). Pitfall #9 sub-class 9.j formalized at HANDOFF §8 + CLAUDE.md per D96. Constituent D95-D99 all 🟢 Locked. Round 8 trends + R8-PF outcomes appended to `_reviewer_effectiveness.md`. **PHASE 1 COMPLETE — Rounds 1-8 all 🟢 Locked.**)
