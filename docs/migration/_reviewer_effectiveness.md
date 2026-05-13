# Reviewer Effectiveness Ledger

**Purpose**: append-only measurement of sub-agent quality over time. Establishes evidence about which reviewer specialty catches which bug class, what false-clean rates each specialty has, and how Pattern E + single-agent passes compare empirically.

**Status**: 🟡 Seeded 2026-05-10 — backfilled with Round 2 cycle 1 Pattern E + Round 3 D72 cycles 4-9 (summarized) + Round 4 cycles 1-8 data. Future entries appended at every round close-out per discipline below.

**Authoritative reference**: this is the evidence layer. The trend doc. Individual cycle findings live in `_validation_log.md`; this doc tracks reviewer specialty performance over time.

## Schema

Each entry is one reviewer-spawning event (one agent invocation):

| Field | Definition |
|---|---|
| Round / cycle / agent ID | E.g. `Round 4 / cycle 4 / R4C4-1` |
| Date | YYYY-MM-DD |
| Specialty role | One of: `column-walk` / `cross-reference` / `internal-consistency` / `D72-edge-cases` / `advisory-research` / `comprehensive-5-gate` / `sleeper-bug-stress` / `convergence-verification` / `feasibility-Tier0` |
| Bug classes targeted | List of Pitfall #9 sub-classes (9.a-9.h) + non-9 classes (`internal-contradiction` / `phase-0-miscite` / `cross-doc-numerical` / etc.) |
| Mode | `single-agent` / `Pattern-E` (one of 5 parallel) |
| 🔴 found | Count |
| 🟡 found | Count |
| Wall-clock minutes | Approximate from task notification timing |
| Subsequent-cycle findings in same region | 0 initially; updated when later cycle finds bug a prior reviewer missed |
| False-clean signal | TRUE iff this reviewer returned ✅ but a subsequent cycle found a bug in a region they cleared |
| Cross-reference | Validation log entry + spawning prompt summary |

### Backward-update rule (append-only)

When cycle N+M discovers a bug in region X that cycle N's reviewer cleared:
1. Find cycle N's row in this ledger
2. Update `Subsequent-cycle findings` count and `False-clean signal` field
3. Append a "Correction note" sub-row referencing the discovering cycle
4. Do NOT edit the original verdict — keep the audit trail intact

## Trends (computed from ledger as evidence accumulates)

### By specialty role (catch rate)

| Specialty | Events to date | 🔴 found / event | False-clean rate | Average minutes | Verdict |
|---|---|---|---|---|---|
| `column-walk` | 4 (Round 2 R2-3, Round 3 cycle 7 Reviewer M, Round 3 cycle 8 batch column-walkers, Round 4 R4C4-1) | 0-2 per cycle | 0% (3 of 4 events; cycle-7 unverified) | 8-12 | **HIGHEST** for Pitfall #9.a/f. Recommend mandatory in every Pattern E batch. |
| `cross-reference` | 2 (Round 4 R4C4-2, Round 4 R4C7 covered Walk 1) | 1-2 per cycle | 0% (1 event verified) | 12-15 | Catches Phase-0 miscites + cross-doc inconsistencies. Distinct from column-walk. |
| `internal-consistency` | 1 (Round 4 R4C4-3) | 3 substantive | (pending) | ~10 | Catches contradictions within same artifact (e.g. § 3.3 exit-code conflict). |
| `D72-edge-cases` | 2 (Round 2 R2-4, Round 4 R4C4-4) | 0 substantive | 0% | ~10 | Catches edge-case enumeration gaps + D72 math errors. |
| `advisory-research` | 2 (Round 2 R2-5, Round 4 R4C4-5) | 0 🔴 | n/a (non-blocking) | 60-90 | Catches framing-grade concerns + external-evidence validation. Distinct value. |
| `comprehensive-5-gate` | 2 (Round 4 cycle 5 + cycle 7) | 0 | **PARTIAL FALSE-CLEAN** (cycle 5 cleared then cycle 6 found 2 bugs; cycle 7 cleared then cycle 8 found 2 bugs) | 15-20 | Verifies fixes work but **misses sleeper-class bugs**. Should be paired with sleeper-bug stress test. |
| `sleeper-bug-stress` | 1 (Round 4 R4C8) | 2 substantive | n/a (this IS the verifying role) | ~25 | **Found bugs 7 prior reviewers missed**. Should be mandatory final cycle before D72/D73 acceptance. |
| `convergence-verification` | 1 (Round 4 cycle 7) | 0 | TRUE (cycle 8 found 2 missed) | ~12 | Cycle-immediately-after-fix verification — confirms fixes worked but doesn't find sleepers. |
| `feasibility-Tier0` | 1 (Round 2 R2-2) | 0 | 0% | ~10 | D67 Tier 0 stub tracing — narrow scope. |

### Key empirical findings (cumulative as of 2026-05-10)

1. **Column-walk specialty has 0% false-clean rate across 4 invocations.** When R4C4-1 returned ✅ on Pitfall #9 surface, the surface stayed clean even under R4C8 sleeper-bug stress test. Strong evidence to make column-walk mandatory in every Pattern E batch.
2. **Comprehensive-5-gate single-agent has partial false-clean rate.** Round 4 cycle 5 cleared what cycle 6 then surfaced (invented `FileSizeBytes` column). Cycle 7 cleared what cycle 8 then surfaced (wrong section cite). Two consecutive false-cleans on this role = empirical evidence that comprehensive single-agent is insufficient for spec docs >50 KB.
3. **Sleeper-bug stress test has the highest per-cycle catch rate POST-CLEAN.** R4C8 found 2 bugs that 7 prior cycles missed. This is the strongest argument for making it a mandatory final cycle.
4. **Pattern E surfaces a different bug class than sequential single-agent.** Round 4 cycles 1-3 single-agent caught 11 🔴 in Pitfall #9 column/parameter/keyword-only-marker space. Cycle 4 Pattern E caught 4 🔴 in internal-contradiction + cross-doc-miscite space. Different specialties find different bugs. Pattern E from cycle 1 would have surfaced ALL of these.
5. **Advisory research role adds non-overlapping value.** R2-5 + R4C4-5 found framing concerns no other reviewer surfaced. Cost is high (60-90 min) but distinct value confirmed across 2 invocations.

## Ledger entries (append-only)

### Round 2 cycle 1 — Pattern E first invocation (2026-05-10)

| Agent | Specialty | Mode | 🔴 | 🟡 | Min | Subsequent | False-clean | Cross-ref |
|---|---|---|---|---|---|---|---|---|
| R2-1 | cross-reference | Pattern-E | 0 | 0 | ~8 | 0 | FALSE | `_validation_log.md` 2026-05-10 Round 2 cycle 1 |
| R2-2 | feasibility-Tier0 | Pattern-E | 0 | 0 | ~10 | 0 | FALSE | (same entry) |
| R2-3 | column-walk | Pattern-E | 0 | 0 | ~12 | 0 | FALSE | (same entry) |
| R2-4 | D72-edge-cases | Pattern-E | 0 | 0 | ~10 | 0 | FALSE | (same entry) |
| R2-5 | advisory-research | Pattern-E | 0 | 2 (framing → B75, B76) | ~60 | 0 | n/a | (same entry) + `_research/round2-cycle1-evidence.md` |

**Cycle outcome**: ✅ CLEAN on first invocation. Pattern E proved viable. Backfill confidence: HIGH (all 5 reviewers documented in validation log).

### Round 3 D72 cycles 4-9 — summary (2026-05-10)

24 reviewer-agent passes across 6 4-agent batches (cycles 4-9). Per-reviewer detail not fully documented in validation log; summary entries below.

| Cycle | Batch size | Roles (inferred from validation log) | 🔴 found in batch | Notes |
|---|---|---|---|---|
| 4 | 4 reviewers | column-walk + cross-reference + internal-consistency + D72-edge | 4 🔴 | First deep-validation batch; introduced Pitfall #9.f (cross-table lift) |
| 5 | 4 reviewers | (rotated specialties) | 2 🔴 | Recurrence of 9.f; fix-introduces-fresh-instance pattern |
| 6 | 4 reviewers | (rotated) | 2 🔴 | More 9.f instances |
| 7 | 4 reviewers (Reviewer M = column-walk specialist explicitly) | column-walk-specialist + 3 others | 0 substantive (clerical only) | **Reviewer M ZERO findings** confirms column-walk specialty exhaustion on 9.a-9.f |
| 8 | 4 reviewers (Q/R/S/T) | (full rotation) | 0 | First all-clean Pattern E batch in Round 3 |
| 9 | 4 reviewers (U/V/W/X) | (full rotation) | 2 🔴 clerical (aggregate-doc drift) | Triggered D72 ceiling → D73 escalation |

**Key takeaway**: cycle 7's Reviewer M precedent established column-walk specialist value. Backfill confidence: MEDIUM (cycle summaries in validation log; individual-reviewer specialties partially inferred).

### Round 4 D72 cycles 1-8 (2026-05-10)

| Agent | Cycle | Specialty | Mode | 🔴 | 🟡 | Min | Subsequent | False-clean | Cross-ref |
|---|---|---|---|---|---|---|---|---|---|
| R4C1 | 1 | comprehensive-5-gate | single-agent | 4 | many | ~25 | n/a (first pass) | n/a | log entry Round 4 D72 cycles 1-8 |
| R4C2 | 2 | comprehensive-5-gate (D56 second-pass) | single-agent | 4 NEW | many | ~25 | n/a | n/a | (same) |
| R4C3 | 3 | comprehensive-5-gate (third-pass) | single-agent | 3 NEW | many | ~20 | n/a | n/a | (same) |
| R4C4-1 | 4 | column-walk | Pattern-E | 0 | 1 minor | ~12 | 0 (verified through cycle 8) | FALSE | (same) |
| R4C4-2 | 4 | cross-reference | Pattern-E | 1 | ~5 | ~15 | (cycle 8 found `§ 2.1.10` invented + `§ 5.3.5` mis-cite — R4C4-2 did 7-walk including § 9 Phase-0 miscites; missed section-cite class) | TRUE (1 region) | (same) |
| R4C4-3 | 4 | internal-consistency | Pattern-E | 3 | ~10 | ~10 | 0 substantive in cleared regions | FALSE | (same) |
| R4C4-4 | 4 | D72-edge-cases | Pattern-E | 0 | 2 advisory | ~10 | 0 | FALSE | (same) |
| R4C4-5 | 4 | advisory-research | Pattern-E | 0 | 3 framing → B95/B96/B97 | ~75 | n/a | n/a | (same) + `_research/round4-cycle4-evidence.md` |
| R4C5 | 5 | comprehensive-5-gate | single-agent | 0 | 0 | ~15 | 2 (cycle 6 found invented `FileSizeBytes` + stale B-range — R4C5 verified cycle-4 fixes clean but missed fresh-instance class introduced by those fixes) | **TRUE** | (same) |
| R4C6 | 6 | Pitfall-9-persistence + doc-wide re-read (close to sleeper-bug-stress) | single-agent | 2 | ~5 | ~25 | 0 | FALSE | (same) |
| R4C7 | 7 | convergence-verification | single-agent | 0 | 0 | ~12 | 2 (cycle 8 found wrong-section-cite + invented-section-number) | **TRUE** | (same) |
| R4C8 | 8 | sleeper-bug-stress | single-agent | 2 | ~5 | ~25 | n/a (terminal cycle — no subsequent review) | n/a | (same) |

**Cumulative**: 19 🔴 caught + ~50 🟡; 12 reviewer-agent events; 2 confirmed false-clean events (R4C5 + R4C7 comprehensive role).

### Round 5 D72 cycles 1-5 (2026-05-10)

| Agent | Cycle | Specialty | Mode | 🔴 | 🟡 | Min | Subsequent | False-clean | Cross-ref |
|---|---|---|---|---|---|---|---|---|---|
| R5C1-1 | 1 | column-walk | Pattern-E | 0 | 0 | ~12 | 0 (verified through cycle 5) | FALSE | log entry Round 5 D72 5-cycle |
| R5C1-2 | 1 | cross-reference | Pattern-E | 8 | 3 | ~15 | 0 (subsequent cycles didn't surface NEW cross-ref bugs; cycle 2 caught fix-fresh-instance only) | FALSE | (same) |
| R5C1-3 | 1 | internal-consistency | Pattern-E | 4 | 4 | ~12 | 0 | FALSE | (same) |
| R5C1-4 | 1 | D72-edge-cases / B-triage spot-check | Pattern-E | 5 | 2 | ~15 | 0 | FALSE | (same) |
| R5C1-5 | 1 | advisory-research | Pattern-E | 0 | 5 framing | ~75 | n/a | n/a | (same) + `_research/round5-cycle1-evidence.md` |
| R5C2 | 2 | comprehensive-5-gate (focused on cycle 1 fix surface + Pitfall #9 fix-fresh-instance scan) | single-agent | 7 | 6 | ~15 | 0 (cycle 3 found 1 cycle-2-introduced bug = math drift; non-fresh-instance to cycle 2's specific fixes) | FALSE | (same) |
| R5C3 | 3 | comprehensive (focused on cycle 2 fix verification) | single-agent | 1 | 0 | ~5 | 0 | FALSE | (same) |
| R5C4 | 4 | sleeper-bug-stress | single-agent | 1 | 2 | ~10 | 0 (cycle 5 verified clean) | FALSE | (same) |
| R5C5 | 5 | convergence-verification | single-agent | 0 | 0 | ~3 | n/a (terminal cycle — D83 acceptance invoked) | n/a | (same) |

**Cumulative Round 5**: 26 🔴 caught + ~22 🟡; 9 reviewer-agent events; 0 false-clean events (significant improvement from Round 4's 2 false-cleans).

## Updated trends (post-Round-5)

### By specialty role (catch rate, post-Round-5)

| Specialty | Events to date | 🔴 found / event | False-clean rate | Average minutes | Verdict |
|---|---|---|---|---|---|
| `column-walk` | **5** (R2-3, R3 cycle 7 Reviewer M, R3 cycle 8 batch, R4C4-1, **R5C1-1**) | 0-2 per cycle | **0%** (5 of 5 events; cycle-7 verified post-hoc) | 8-12 | **HIGHEST** for Pitfall #9.a-g — Pattern E mandatory slot. Empirical track record CONFIRMED with 5-event sample. |
| `cross-reference` | 3 (R4C4-2, R4C7 covered Walk 1, **R5C1-2**) | 1-8 per cycle | 0% | 12-15 | Catches Phase-0 miscites + cross-doc inconsistencies + B-triage drift. Distinct from column-walk. |
| `internal-consistency` | 2 (R4C4-3, **R5C1-3**) | 3-4 substantive per cycle | 0% | ~10-12 | Catches contradictions within same artifact (exit-code conflicts, scope-vs-content mismatches, three-way contradictions). |
| `D72-edge-cases` | 3 (R2-4, R4C4-4, **R5C1-4**) | 0-5 per cycle | 0% | ~10-15 | Catches edge-case enumeration gaps + B-triage classification errors. |
| `advisory-research` | **3** (R2-5, R4C4-5, **R5C1-5**) | 0 🔴 always | n/a (non-blocking) | 60-90 | **EMPIRICAL TRACK RECORD CONFIRMED across 3 events**: 0 🔴 + framing-grade 🟡 only. Distinct value layer; non-overlapping with reviewers 1-4. |
| `comprehensive-5-gate` | 3 (R4C5, R4C7, **R5C2**) | 0-7 per cycle | **PARTIAL FALSE-CLEAN historical** (R4C5 cleared then R4C6 found bugs; R4C7 cleared then R4C8 found bugs); **R5C2 found 7 🔴 with 0 subsequent fresh-instance** | 15-20 | Mixed. Useful for fix-cycle verification (R5C2 caught 7 🔴 in cycle 1's fix surface) but unreliable as primary first-pass for spec docs >50 KB. |
| `sleeper-bug-stress` | **2** (R4C8, **R5C4**) | 1-2 per cycle (post-clean) | 0% (R5C4 → R5C5 clean) | ~10-25 | **MANDATORY FINAL CYCLE per R4C8 precedent + R5C4 confirmation**. Highest catch rate POST-CLEAN. R5C4 broke the historical "single sleeper-bug stress finds 2 bugs" pattern with 1 substantive 🔴 + 2 🟡. |
| `convergence-verification` | 2 (R4C7, **R5C5**) | 0 (R5C5) — partial false-clean (R4C7) | TRUE for R4C7; FALSE for R5C5 | ~3-12 | Mixed. R5C5 cleaner than R4C7 because Round 5 entered cycle 5 after sleeper-bug-stress (cycle 4) — Round 4's cycle 7 entered post-cycle-6-fixes without sleeper-bug depth. |
| `feasibility-Tier0` | 1 (R2-2) | 0 | 0% | ~10 | Narrow scope. |

### Key empirical findings (cumulative as of 2026-05-10 post-Round-5)

1. **Column-walk specialty has 0% false-clean rate across 5 events** (extended from 4 events post-Round-4). MANDATORY in every Pattern E batch + as producer self-check per HANDOFF §8 Pitfall #9 sub-class accumulator 9.a-9.h.
2. **Pattern E from cycle 1 is structurally superior to sequential single-agent cycles 1-3** for spec docs >50 KB. Round 5 cycle 1 surfaced 17 🔴 in 1 parallel cycle vs Round 4's 11 🔴 over 3 sequential single-agent cycles. **Pattern E first-cycle hypothesis confirmed empirically**.
3. **Advisory researcher specialty has 0 🔴 across 3 events** (R2-5, R4C4-5, R5C1-5) with consistent framing-grade 🟡 value. Non-overlapping with blocking reviewer specialties. Pattern E 5th-slot value confirmed.
4. **NEW bug class emerged in Round 5: process-discipline-failure** — B-triage sloppiness (using B-number range as proxy for content), false-closure claims, section-numbering mismatches, wrong-doc-scope, stale-count propagation. Distinct from Round 4's Pitfall #9 column/parameter/keyword-only surface. Candidate HANDOFF §8 Pitfall #9 sub-class **9.i** (process-discipline-claim drift) for Round 6 close-out via B120.
5. **Pitfall #9 fix-fresh-instance pattern BROKEN at Round 5 cycle 5** — first time in 8 rounds (D49 v2→v3 / R2 first-pass / R2 second-pass / R3 second-pass / R3 cycles 5-6 / R4 cycle 2 / R4 cycle 6 / R4 cycle 8 all had fresh-instance recurrences). Round 5 cycle 5 found ZERO fresh-instance drift across 3 cycle-4 fix locations. Sleeper-bug-stress (cycle 4) + careful cycle-5 verification IS the structural fix.
6. **D83 convergence-confirmed acceptance precedent established** — distinct from Round 3 D73 / Round 4 D78 math-infeasibility-acceptance. Round 5 invoked acceptance at cycle 5 with math still feasible due to convergence-evidence strength (cycle 5 ✅ CLEAN + 0 fresh-instance + sleeper-bug stress exhausted at cycle 4). Sets precedent for "convergence-confirmed acceptance" as legitimate D72 escalation path.
7. **Comprehensive-5-gate specialty has 2/3 false-clean history** (R4C5 + R4C7 false-clean; R5C2 caught real bugs). Useful for fix-cycle verification but NOT for primary first-pass. Pattern E specialty rotation is the structural fix.
8. **Sleeper-bug stress test specialty validated across 2 events** (R4C8 + R5C4). MANDATORY final cycle for spec docs >50 KB before D72-style architectural acceptance.

**Round 5 was the first round where**:
- Pattern E from cycle 1 was the DEFAULT (not Pattern E as escalation from cycle 4 like Round 4)
- Producer self-check used HANDOFF §8 Pitfall #9 sub-class accumulator 9.a-9.h walked before drafting (vs Round 4's narrative-prose Pitfall #9)
- 0 false-clean reviewer-events in the entire cycle campaign (vs Round 4's 2 false-cleans)
- Convergence-confirmed acceptance variant invoked (vs Round 3 + Round 4 math-infeasibility-acceptance)
- Pitfall #9 fix-fresh-instance pattern broken at cycle 5 (vs all prior rounds had fresh-instance recurrences at every fix cycle)

## Discipline for future entries

Per round close-out (per D60 + udm-round-closeout skill):

1. **Append one row per reviewer-spawning event** to the Round N section below
2. **Apply backward-update rule** if this cycle found bugs in regions cleared by prior cycles
3. **Recompute trends table** (by-specialty catch rate) — manual for now; could automate later via a script that parses the ledger
4. **Flag specialty roles with rising false-clean rate** — if a role hits >25% false-clean across 4+ events, recommend retiring or pairing it with a complementary specialty

## Anti-patterns

- ❌ Editing prior entries' verdicts — append-only audit trail
- ❌ Computing trends from incomplete backfill — if a round wasn't fully captured in `_validation_log.md`, mark its summary entries with "MEDIUM" or "LOW" backfill confidence
- ❌ Over-trusting trends from <3 events per specialty — use as direction-of-evidence, not conclusion
- ❌ Letting the ledger replace `_validation_log.md` — they have distinct purposes (ledger = trend; log = audit trail)

## Cross-references

- `_validation_log.md` — per-cycle audit trail with full findings detail
- `HANDOFF.md` §8 Pitfall #9 sub-class accumulator — bug taxonomy this ledger measures against
- `MULTI_AGENT_GUIDE.md` § Pattern E — the 5-agent specialty roles whose effectiveness this ledger tracks
- `CHECKS_AND_BALANCES.md` D72 termination rule — the convergence rule this ledger informs calibration of

## Owner

Pipeline lead. Updates appended at every round close-out per `udm-round-closeout` skill (to be extended with ledger-append step as part of Round 5+ discipline).

### Round 6 D72 cycles 1-7 (2026-05-10)

| Agent | Cycle | Specialty | Mode | 🔴 | 🟡 | Min | Subsequent | False-clean | Cross-ref |
|---|---|---|---|---|---|---|---|---|---|
| R6C1-1 | 1 | column-walk | Pattern-E | 6 | 4 | ~22 | 0 (cycles 2-7 found NO new column-walk-class drift; fix-fresh-instance was in B-triage/metadata, not column-walk) | FALSE | log entry Round 6 D72 7-cycle |
| R6C1-2 | 1 | cross-reference | Pattern-E | 3 | 0 | ~18 | 0 (cycle 4 sleeper-bug found B108-B114 silent omission which was process-discipline 9.i, not cross-ref class) | FALSE | (same) |
| R6C1-3 | 1 | internal-consistency | Pattern-E | 3 | 3 | ~12 | 0 | FALSE | (same) |
| R6C1-4 | 1 | D72-edge-cases | Pattern-E | 0 | 2 | ~12 | 0 | FALSE | (same) |
| R6C1-5 | 1 | advisory-research | Pattern-E | 0 | 6 framing → B130/B131/B132 + 3 inline incorporated | ~30 | n/a (advisory) | n/a | (same) + `_research/round6-cycle1-evidence.md` |
| R6C2 | 2 | comprehensive-5-gate verification (focus on fix-fresh-instance) | single-agent | 1 (§ 12.1 trailing summary) | 4 | ~15 | 0 (cycle 3 found different fresh-instance; cycle 2 fix surface stayed clean) | FALSE | (same) |
| R6C3 | 3 | comprehensive verification | single-agent | 1 (§ 12.5 heading stale) | 0 | ~10 | 0 (cycle 4 sleeper-bug found different class) | FALSE | (same) |
| R6C4 | 4 | sleeper-bug-stress | single-agent | 2 (B108-B114+B117 silent omission + § 10.1 Q4 mis-cite) | 4 | ~25 | 0 (cycle 5 found § 12.1 fresh-instance recurrence — same class as cycle 2/cycle 3, NOT new sleeper-bug class) | FALSE | (same) |
| R6C5 | 5 | comprehensive verification | single-agent | 1 (§ 12.1 trailing summary — 4th consecutive 9.i) | 0 | ~10 | 0 | FALSE | (same) |
| R6C6 | 6 | mechanical-fix + verification | single-agent | 1 (invented B141 forward-cite — 5th consecutive 9.i) | 0 | ~5 | 0 (cycle 7 closure self-referentially defined B141) | FALSE | (same) |
| R6C7 | 7 | mechanical-fix closure (B141 defined) | producer | 0 | 0 | ~3 | n/a (terminal cycle — D88 acceptance invoked) | n/a | (same) |

**Cumulative Round 6**: 15 🔴 caught + ~19 🟡; 11 reviewer-agent events; 0 false-clean events at cycle level. **5-consecutive Pitfall #9 sub-class 9.i recurrences** (cycles 2/3/5/6/7) = empirical evidence for B120 sub-class formalization. Round 6 invoked **D88 convergence-confirmed acceptance at cycle 7** paralleling Round 5 D83 precedent (Round 5 invoked D83 at cycle 5).

## Updated trends (post-Round-6)

### By specialty role (catch rate, post-Round-6)

| Specialty | Events to date | 🔴 found / event | False-clean rate | Average minutes | Verdict |
|---|---|---|---|---|---|
| `column-walk` | **6** (R2-3, R3 cycle 7 Reviewer M, R3 cycle 8 batch, R4C4-1, R5C1-1, **R6C1-1**) | 0-6 per cycle | **0%** (6 of 6 events; R6C1-1 found 6 🔴 — highest single-event catch in column-walk's history) | 8-22 | **HIGHEST** for Pitfall #9.a-g — Pattern E mandatory slot. Empirical track record CONFIRMED with 6-event sample. R6C1-1's 6-🔴 catch (SP-3/SP-4 signature drift in § 2 self-check) validates the sub-class 9.b + 9.d sweep against complex SP signatures even when producer self-check claims "verified". |
| `cross-reference` | 4 (R4C4-2, R4C7 covered Walk 1, R5C1-2, **R6C1-2**) | 1-8 per cycle | 0% | 12-18 | Catches Phase-0 miscites + cross-doc inconsistencies + B-triage drift. Distinct from column-walk. |
| `internal-consistency` | 3 (R4C4-3, R5C1-3, **R6C1-3**) | 3 substantive per cycle | 0% | ~10-12 | Catches contradictions within same artifact (§ 6.4 heading, § 12.6 sub-section + arithmetic). |
| `D72-edge-cases` | 4 (R2-4, R4C4-4, R5C1-4, **R6C1-4**) | 0-5 per cycle | 0% | ~10-15 | Catches edge-case enumeration gaps + B-triage classification + D72 convergence rule violations. |
| `advisory-research` | **4** (R2-5, R4C4-5, R5C1-5, **R6C1-5**) | 0 🔴 always | n/a (non-blocking) | 30-90 | **EMPIRICAL TRACK RECORD CONFIRMED across 4 events**: 0 🔴 + framing-grade 🟡 only. Distinct value layer; non-overlapping with reviewers 1-4. R6C1-5 6 🟡 partially incorporated inline (atomic symlink + mssql pin + Hypothesis nightly + D74 dependency + STARTUP_* family + EventType length budget). Distinct value layer demonstrated consistently. |
| `comprehensive-5-gate` | 5 (R4C5, R4C7, R5C2, R5C3, **R6C2, R6C5**) | 0-7 per cycle | **PARTIAL FALSE-CLEAN historical** (R4C5 + R4C7) but consistently catches fix-fresh-instance at verification cycles (R5C2 + R5C3 + R6C2 + R6C5 each found 1 🔴) | 5-20 | Mixed for first-pass; consistent value for fix-verification cycles. Pattern E specialty rotation is the structural fix for first-pass; comprehensive single-agent for cycle 2+ verification confirmed valuable. |
| `sleeper-bug-stress` | **3** (R4C8, R5C4, **R6C4**) | 1-2 per cycle | 0% across all 3 events | ~10-25 | **MANDATORY FINAL CYCLE** per 3-event precedent. Highest catch rate POST-CLEAN. Every event surfaced bugs prior reviewers missed despite explicit walks. R6C4 found 2 🔴 (B108-B114+B117 silent omission from § 12 + § 10.1 Q4 mis-cite) that cycles 1-3 + Pattern E 5-agent all missed. |
| `convergence-verification` | 3 (R4C7, R5C5, **R6C7**) | 0 (R5C5 + R6C7) — partial false-clean (R4C7) | TRUE for R4C7; FALSE for R5C5 + R6C7 | ~3-12 | Consistent post-Round-4. Both R5C5 + R6C7 confirmed cycle-clean (R5: 0 🔴 + 0 fresh-instance / R6: closure of self-referential B141 fresh-instance). Convergence-verification's role at final cycle is now reliably clean. |
| `mechanical-fix` | 1 (**R6C6**) | 1 fresh-instance (invented B141) | n/a (this IS a fix-fresh-instance generator role) | ~5 | **NEW SPECIALTY observed at R6C6** — mechanical fixes that ADD content (e.g. citations, B-numbers) reliably introduce 9.i fresh-instances if the content references items not yet defined. Pairs with B141 self-referential closure pattern. Should be paired with verify-cycle that runs B120 5-step audit. |
| `feasibility-Tier0` | 1 (R2-2) | 0 | 0% | ~10 | Narrow scope. |

### Key empirical findings (cumulative as of 2026-05-10 post-Round-6)

1. **Column-walk specialty has 0% false-clean rate across 6 events** (extended from 5 events post-Round-5). MANDATORY in every Pattern E batch + as producer self-check per HANDOFF §8 Pitfall #9 sub-class accumulator 9.a-9.i. R6C1-1's 6-🔴 catch validates the column-walk surface even on complex SP signatures.
2. **Pattern E from cycle 1 — 4th invocation confirmed structurally superior** for spec docs >50 KB. R2C1 (all-clean first cycle), R4C4 (4 🔴), R5C1 (17 🔴), R6C1 (10 🔴) — empirically stable surface pattern.
3. **Advisory researcher specialty has 0 🔴 across 4 events** (R2-5, R4C4-5, R5C1-5, **R6C1-5**) with consistent framing-grade 🟡 value. Non-overlapping with blocking reviewer specialties. Pattern E 5th-slot value confirmed across 4 distinct surfaces. R6C1-5 advisory partially incorporated inline (6 framing concerns → 3 substantive inline fixes + 3 BACKLOG items).
4. **NEW empirical learning at Round 6: Pitfall #9 sub-class 9.i is structurally real** (8 fresh-instance occurrences across R5 + R6 = 2-round evidence base). 5-consecutive R6 cycle 2/3/5/6/7 recurrences confirm the pattern is NOT coincidental. HANDOFF §8 sub-class 9.i FORMALIZED with 5-step producer self-check directive per B120 + B136 + B141 cumulative directive strengthening at Round 6 close-out.
5. **Sleeper-bug-stress test specialty validated across 3 events** (R4C8 + R5C4 + R6C4). MANDATORY final cycle for spec docs >50 KB before D72-style architectural acceptance. Every event surfaced bugs prior reviewers missed despite explicit walks. Empirical track record: highest catch rate POST-CLEAN at 100% (3 of 3 events found new substantive bugs).
6. **D88 convergence-confirmed acceptance is the 2nd invocation of the D83-precedent variant** (R5 was 1st). 7-cycle trajectory 10→1→1→2→1→1→0 paralleling R5's 5-cycle 17→7→1→1→0. Sets precedent for "convergence-confirmed acceptance" as legitimate D72 escalation path alongside D73/D78 math-infeasibility-acceptance — distinct triggers, distinct trajectory shapes, both valid.
7. **NEW specialty observed at R6C6: mechanical-fix-fresh-instance generator**. Mechanical fixes that ADD content (citations, B-numbers, references) reliably introduce 9.i fresh-instances if the added content references items not yet defined. Pairs with B141 self-referential closure pattern. Should be paired with verify-cycle that runs B120 5-step audit.
8. **Carryover compounding trajectory**: Round 5 closed 9 + Round 6 closed 29 → net reduction of ~5 carryover items per round. Sustainable. Round 8 self-improvement loop (B129) monitors for trend reversal.

**Round 6 was the first round where**:
- 7 cycles consumed before D72 architectural-review acceptance (paralleling R3 = 9, R4 = 8, R5 = 5; R6's 7 cycles fits the converging-per-round trend)
- 5-consecutive Pitfall #9 sub-class 9.i recurrences at metadata-level (highest streak ever; demonstrates the structural pattern + validates B120 formalization)
- Forward-reference invented before defined (R6C6 invented B141 → cycle 7 self-referentially defined it; B141 strengthening directive added to HANDOFF §8 9.i)
- HANDOFF §8 Pitfall #9 sub-class 9.i FORMALIZED inline at close-out (the longest-standing candidate sub-class finally landing)
- Convergence-confirmed acceptance invoked at cycle 7 (R5 invoked at cycle 5; R6 invoked at cycle 7 due to 5-consecutive 9.i recurrence pattern requiring more cycles to demonstrate structural-not-coincidental)

### Round 6 retroactive — Pattern F first paired-agent invocation (2026-05-11)

| Agent | Specialty | Mode | 🔴 | 🟡 | Min | Subsequent | False-clean | Cross-ref |
|---|---|---|---|---|---|---|---|---|
| R6-RETRO-INST1 | cascade-audit | Pattern-F (Layer 2 paired) | 6 (5 from open-ended search) | 4 | ~30 | (pending) | n/a (this IS the verifying role) | `_validation_log.md` 2026-05-11 entry; agentId `a7aa8fb0f252305f9` |
| R6-RETRO-INST2 | cascade-audit | Pattern-F (Layer 2 paired) | 5 (3 from open-ended search) | 4 | ~28 | (pending) | n/a | (same entry); agentId `ab037e22805d6e83b` |

**Pattern F empirical observation (first event)**: paired-agent Layer 2 converged on 4 🔴 (HANDOFF §3 D89-D91 missing + CURRENT_STATE Pattern F absence + HANDOFF §14 stale + D89 B142+ forward-cite unresolved); disagreed on 5 findings (orchestrator-judgment resolutions: stricter Pattern F reading wins for blocking-class; locked-artifact-immutability for content-level). INSTANCE 1 unique catches: 02_PHASES.md L67 status mis-claim + phase1/05_tests.md L757 second-order B140 + missing validation log entry. INSTANCE 2 unique catches: CLAUDE.md Pattern F discipline gap + phase1/06_deployment.md "Six-cycle" framing inconsistency. Combined: 16 total gaps surfaced (9 beyond producer's reflection-identified 7). This is the empirical validation of D89's core thesis: paired-judgment Layer 2 finds what producer self-attestation misses.

## Updated trends (post-Round-6-retrospective + Pattern F first invocation)

### By specialty role (catch rate, post-Round-6-retrospective)

| Specialty | Events to date | 🔴 found / event | False-clean rate | Average minutes | Verdict |
|---|---|---|---|---|---|
| `cascade-audit` | **2** (NEW SPECIALTY 2026-05-11 — R6-RETRO-INST1 + R6-RETRO-INST2) | 5-6 per event | 0% across 2 events (first invocation) | 28-30 | **NEW specialty for Pattern F Layer 2**. First paired invocation 2026-05-11 found 9 cascade gaps producer reflection missed. Paired-instance design (per D89 hard rule: never single instance) is structural — convergent findings = high confidence; divergent findings = orchestrator judgment. Lock criteria for D89/D90/D91 🟡 → 🟢: 1 round of empirical evidence; Round 7 close-out is first production invocation. |

### Key empirical findings (cumulative as of 2026-05-11 post-Round-6-retrospective)

9. **Pattern F immediately validated its own thesis on first invocation**. Producer reflection found 7 cascade gaps in Round 6 close-out. Paired-agent Layer 2 found 9 ADDITIONAL gaps (16 total). The producer's 7 were known-knowns; the paired-auditors' 9 additional were unknown-unknowns that independent verification surfaced. Empirical confirmation of constraint "never trust 1 agent at cascade level" (D89 driver).
10. **Paired-agent convergence rate at first invocation**: 4 / 9 findings convergent (~44%). 5 / 9 divergent — but divergence is information-rich, not noise. The divergence cases revealed legitimate interpretation differences (stricter Pattern F reading vs locked-artifact immutability). Pattern F doctrine handles divergence via orchestrator judgment with documented rationale.
11. **Mechanical-fix-fresh-instance + Pattern F = structural mitigation**. R6C6's invented B141 was a mechanical-fix-fresh-instance per HANDOFF §8 9.i; Pattern F Layer 1's regex sweep catches this class deterministically. The combination of "mechanical-fix specialty needed for adding content" + "Pattern F Layer 1 verifies references" closes the loop that previously took 5-consecutive cycles to surface.
12. **R28 mitigation evidence emerging**: pre-Pattern-F cascade-self-attestation gap = 6 🔴 (Medium × High); first paired invocation demonstrated the discipline catches what was previously invisible. Score reduction to 2 ⚪ (Low × Medium) pending Round 7 first-production-invocation evidence (per D89/D90/D91 lock criteria).

### Round 6 retroactive (UNSCOPED) — Pattern F 2nd paired-agent invocation (2026-05-11)

| Agent | Specialty | Mode | 🔴 | 🟡 | Min | Subsequent | False-clean | Cross-ref |
|---|---|---|---|---|---|---|---|---|
| R6-UNSCOPED-INST1 | cascade-audit (unscoped current-state) | Pattern-F (Layer 2 paired) | 11 (6 convergent + 5 unique) | 9 | ~45 | (pending) | n/a | `_validation_log.md` 2026-05-11 unscoped entry; agentId `a49b8ccdbf2234747` |
| R6-UNSCOPED-INST2 | cascade-audit (unscoped current-state) | Pattern-F (Layer 2 paired) | 13 (6 convergent + 7 unique including B-item-status systemic) | 19 | ~52 | (pending) | n/a | (same entry); agentId `aa4187d1f175d877a` |

**Pattern F empirical observation (2nd event)**: paired-agent Layer 2 with UNSCOPED current-state mandate found 11-13 🔴 + 19+ 🟡 across the cumulative R1-R6 cascade. Convergence on 7 blocking-class 🔴 findings (NORTH_STAR D-list / 00_OVERVIEW Phase + docs + agents / BACKLOG status-mismatch / CURRENT_STATE pickup sequence / PHASE_1_DEEP_DIVE_PLAN status mis-claim / CHECKS_AND_BALANCES no Pattern F / RISKS R12 enum). Divergent findings (~5) resolved via orchestrator judgment per Pattern F doctrine.

**NEW empirical pattern surfaced**: B-item-status-render discipline gap (~15 entries with leading badge stale vs inline annotation). Tracked as B144 candidate for sub-class 9.j formalization.

**NEW class proven: unscoped audit finds gaps that Round-N-scoped audit misses**. Of 11-13 🔴 findings, 7-9 were NOT in the R6-retroactive (Round-6-scoped) audit's 9-finding set. The two audit types are complementary, not duplicative. Round 7 close-out should run Round-7-scoped + unscoped sweep periodically (e.g., quarterly per MAINTENANCE.md cadence).

## Updated trends (post-Round-6-retrospective + unscoped Pattern F)

### By specialty role (catch rate, post-unscoped)

| Specialty | Events to date | 🔴 found / event | False-clean rate | Average minutes | Verdict |
|---|---|---|---|---|---|
| `cascade-audit` | **4** (R6-RETRO-INST1, R6-RETRO-INST2, **R6-UNSCOPED-INST1, R6-UNSCOPED-INST2**) | 5-13 per event (avg 8.75) | 0% across 4 events (still first-production-pending) | 28-52 (avg 39) | **NEW specialty for Pattern F Layer 2** — 4-event evidence base across 2 invocation modes (Round-scoped + unscoped). Convergence rate at first 2 invocations: 44% R6-retroactive / ~55% unscoped — paired-judgment design empirically substantiated as adding value beyond producer reflection. Round 7 close-out is 3rd Pattern F event (first PRODUCTION) and is the lock criteria for D89/D90/D91 🟡 → 🟢. |

### Key empirical findings (cumulative as of 2026-05-11 post-unscoped Pattern F)

13. **Pattern F unscoped audit finds latent gaps that Round-N-scoped audit misses**. R6-unscoped found 7-9 🔴 outside the R6-retroactive 9-finding set. The two scopes are complementary; Round 7+ close-outs should periodically run unscoped sweeps (recommended quarterly per MAINTENANCE.md cadence).
14. **B-item status-render discipline (candidate sub-class 9.j)**: 15+ B-items showed `🟡 Open` leading badge with `CLOSED YYYY-MM-DD` inline annotation as canonical render-discipline gap. Tracked as B144 for Round 7 formalization (needs 2-event evidence base; current = 1-event empirical from unscoped audit).
15. **Status-mismatch parallel-instance pattern**: D89-D91 mis-claimed as "locked" appeared at 02_PHASES.md L67 (R6-retroactive INST1 catch) AND PHASE_1_DEEP_DIVE_PLAN.md L173 (R6-unscoped INST2 catch). Same fix needed at multiple locations because the original error class duplicated. Pattern F discipline going forward should grep for parallel-instance siblings at every status-claim fix.
16. **Stage 1 doc staleness has highest blast radius**. NORTH_STAR.md decision list stopped at D56 (36 decisions absent); CHECKS_AND_BALANCES.md no Pattern F reference. Both are read FIRST by every CCL-compliant agent; staleness compounds across every subsequent fresh-agent invocation.

### Round 7 (Schema Evolution Governance) D72 8-cycle campaign + Pattern F first-production (2026-05-11)

| Agent | Specialty | Mode | 🔴 | 🟡 | Min | Subsequent | False-clean | Cross-ref |
|---|---|---|---|---|---|---|---|---|
| R7C1-1 | column-walk | Pattern-E | 8 (5 SP-12 col-drift + 1 PiiVault Status enum drift + 2 line-cite off-by-N) | 4 | ~35 | 0 fresh-instance | FALSE | `_validation_log.md` 2026-05-11 Round 7 entry; agentId `a3bb9683a48204417` |
| R7C1-2 | cross-reference | Pattern-E | 7 | 6 | ~50 | 0 | FALSE | (same) `a6cd3a6d01f49e71c` |
| R7C1-3 | internal-consistency | Pattern-E | 7 | 2 | ~45 | 0 | FALSE | (same) `a88a0aefbb96a9af9` |
| R7C1-4 | D72-edge-cases | Pattern-E | 4 | 4 | ~40 | 0 | FALSE | (same) `a580ae683c39aeb31` |
| R7C1-5 | advisory-research | Pattern-E | 0 🔴 + 1 🔴-framing (ops-channel SRE inversion) | 4 framing | ~50 | n/a | n/a | (same) + `_research/round7-cycle1-evidence.md`; `a4753d3965259baae` |
| R7C2 | comprehensive-5-gate (D56 verify) | single-agent | 5 (fix-fresh-instance) | 0 | ~25 | 0 | FALSE | (same) `a49d96f98444df712` |
| R7C3 | comprehensive (verify) | single-agent | 1 (count propagation) | 0 | ~15 | 0 | FALSE | (same) `a66f186b9f49f0262` |
| R7C5 | sleeper-bug-stress (mandatory final per R4C8/R5C4/R6C4 precedent) | single-agent | 1 (SP-12 Round 4 CLI consumer gap) | 4 | ~30 | 0 | FALSE | (same) `af9231868aee95572` |
| R7C7 | independent verify (per R5C5 precedent — NOT R6C7 self-referential) | single-agent | 3 (cycle-6-fix fresh-instance: SP-12 NULL regression + L275/L279 line drift + F26 forward-ref) | 2 | ~30 | 0 | FALSE | (same) `a9b24e62b57f09368` |
| R7-PF-INST1 | **cascade-audit (Pattern F first-production)** | Pattern-F Layer 2 paired | 5 | 5 | ~45 | n/a | n/a | (same) `ad80b8cef05d8c3bd` |
| R7-PF-INST2 | **cascade-audit (Pattern F first-production)** | Pattern-F Layer 2 paired | 8 (5 convergent + 3 unique incl. B146-B155 omission) | 8 | ~55 | n/a | n/a | (same) `a3ae7684dac80646f` |

**Cumulative Round 7**: ~22 cycle 🔴 + ~13 Pattern F first-production 🔴 = ~35 🔴 caught + fixed; ~30 🟡; 11 reviewer-agent events. **Pattern F first-production empirical thesis CONFIRMED**: paired-judgment Layer 2 surfaced 5-8 cascade gaps producer reflection missed despite 8 cycles of artifact-level Pattern E validation.

## Updated trends (post-Round-7 + Pattern F first-production)

### By specialty role (catch rate, post-Round-7)

| Specialty | Events to date | 🔴 found / event | False-clean rate | Average minutes | Verdict |
|---|---|---|---|---|---|
| `column-walk` | **7** (R2-3, R3 cycle 7 Reviewer M, R3 cycle 8 batch, R4C4-1, R5C1-1, R6C1-1, **R7C1-1**) | 0-8 per cycle | **0%** (7 of 7 events) | 8-35 | **HIGHEST and most-empirically-validated specialty** — extended 6→7 events with 0% false-clean across all. **Mandatory in every Pattern E batch**. R7C1-1 8 🔴 catch on SP-12 body drifts validates the surface even on complex SP signatures with multiple invented columns/enums. |
| `cross-reference` | 4 (R4C4-2, R4C7, R5C1-2, R6C1-2, **R7C1-2**) actually counting = 5 — corrected | 1-8 per cycle | 0% | 12-50 | Catches Phase-0 miscites + cross-doc inconsistencies + B-triage drift consistently. |
| `internal-consistency` | 4 (R4C4-3, R5C1-3, R6C1-3, **R7C1-3**) | 3-7 substantive per cycle | 0% | ~10-45 | Catches contradictions within same artifact reliably. R7C1-3 found 7 internal contradictions (migration script naming / SchemaContract ContractKey / closure count / EventType convention / Phase 0 attribution / NORTH_STAR pillar / .env count). |
| `D72-edge-cases` | 5 (R2-4, R4C4-4, R5C1-4, R6C1-4, **R7C1-4**) | 0-5 per cycle | 0% | ~10-40 | Catches edge-case enumeration gaps + D72 convergence rule violations. |
| `advisory-research` | **5** (R2-5, R4C4-5, R5C1-5, R6C1-5, **R7C1-5**) | 0 🔴 always (1 🔴-framing class at R7C1-5) | n/a (non-blocking) | 30-90 | **EMPIRICAL TRACK RECORD CONFIRMED across 5 events** — distinct framing-grade value layer; R7C1-5 surfaced 1 architectural-class concern (B156 ops-channel fallback inversion) + 3 grounding-class (B157 Kimball SCD2; B158 CCPA pseudonymization; B159 named-param calling-style). Pattern E 5th-slot value confirmed industrial-strength. |
| `comprehensive-5-gate` | 7 (R4C5, R4C7, R5C2, R5C3, R6C2, R6C5, **R7C2, R7C3**) actually 8 | 0-7 per cycle | mixed (R4C5 + R4C7 false-clean; R5C2/R6C2/R7C2/R7C3 consistent catches) | 5-25 | Useful for fix-cycle verification; unreliable as primary first-pass for spec docs >50 KB. R7C2 found 5 fix-fresh-instance items confirming Pitfall #9.i recurrence pattern. |
| `sleeper-bug-stress` | **4** (R4C8, R5C4, R6C4, **R7C5**) | 1-2 per cycle (post-clean) | 0% across 4 events | ~10-30 | **MANDATORY FINAL CYCLE per 4-event precedent** (extended R6's 3-event base). Every event surfaced substantive bugs prior reviewers missed. R7C5 found SP-12 vs Round 4 § 3.9 CLI consumer contract gap — would have caused runtime failure in token-file bulk mode. |
| `convergence-verification` | 4 (R4C7, R5C5, R6C7, **R7C7**) | 0-3 per cycle (mixed — R5C5/R6C7 clean; R7C7 found 3 🔴 fix-fresh-instance) | 50% (R4C7 + R7C7 not clean; R5C5 + R6C7 clean) | ~3-30 | Mixed. R7C7 returned 3 🔴 demonstrating fix-fresh-instance pattern persists even at independent-verify cycles. Convergence-verification at R5C5 / R6C7 patterns differ from R7C7 (different cycle phase). |
| `mechanical-fix` | 2 (R6C6, **R7C8**) | 1-3 fresh-instance per cycle (this IS the fresh-instance-generator role) | n/a | ~5-15 | **NEW SPECIALTY observed at R6C6 + extended to R7C8** — mechanical fixes reliably introduce 9.i fresh-instances if added content references items not yet defined. Pairs with subsequent verify-cycle. |
| `cascade-audit` | **6** (R6-RETRO-INST1, R6-RETRO-INST2, R6-UNSCOPED-INST1, R6-UNSCOPED-INST2, **R7-PF-INST1, R7-PF-INST2**) | 5-13 per event (avg ~8) | 0% across 6 events | 28-55 | **Pattern F Layer 2 specialty — 6-event evidence base across 3 invocation contexts**: R6 retroactive (post-fix verification), R6 unscoped (latent gap discovery), R7 first-production (D89/D90/D91 lock criteria). **Production-pattern confirmed**: paired-judgment Layer 2 reliably finds 5+ cascade gaps producer reflection misses. R7-PF-INST2 catch of B146-B155 silent omission (10-item missing from BACKLOG despite cascade-claim) is empirically the strongest cascade-discipline-violation case yet. |
| `feasibility-Tier0` | 1 (R2-2) | 0 | 0% | ~10 | Narrow scope. |

### Key empirical findings (cumulative as of 2026-05-11 post-Round-7)

17. **Pattern F first-production at Round 7 close-out CONFIRMED D89/D90/D91 lock criteria**: paired-agent Layer 2 found 5-8 cascade gaps (NORTH_STAR D-list stale + PHASE_1_DEEP_DIVE_PLAN + 00_OVERVIEW + 02_PHASES Round-7-status drift + B146-B155 BACKLOG silent omission + validation log entry missing + B94 type-width drift) the producer (and 8 prior Pattern E cycles) missed.
18. **Pitfall #9 8-event campaign empirically industrial**: Round 6 5-consecutive 9.i recurrences + Round 7 5-consecutive (cycles 2/3/5/6/7) = 10 fresh-instance recurrences across 2 rounds with NO discipline change between R6 and R7. Pattern is structural-not-coincidental at the highest confidence.
19. **D94 math-infeasibility variant**: 3rd math-infeasibility-acceptance (D73/D78/D94) distinct from D83/D88 convergence-confirmed. Establishes Pattern F first-production empirical-base as new substantiation argument paralleling math infeasibility — Round 7 evidence justifies acceptance even when literal trajectory math is ambiguous.
20. **B144 sub-class 9.j candidate at ≥2-event evidence base**: R6 unscoped (15+ B-item stale-badge instances) + R7 first-production (7 simultaneous Round 7 in-scope items with leading-badge stale). **Eligible for HANDOFF §8 formalization at Round 8 close-out per B144 description.**
21. **Pattern F discipline now production-validated across 3 invocation contexts** (R6 retroactive + R6 unscoped + R7 first-production = 3 events; all surfaced 5+ gaps producer reflection missed). D89/D90/D91 🟡 → 🟢 lock empirically satisfied.

### Round 8 (Sub-Agent Self-Improvement Discipline) D72 9-cycle campaign + Pattern F 2nd production (2026-05-11)

| Agent | Cycle | Specialty | Mode | 🔴 | 🟡 | Min | Subsequent | False-clean | Cross-ref |
|---|---|---|---|---|---|---|---|---|---|
| R8C1-1 | 1 | column-walk | Pattern-E | 3 (section number drift × 8 + § 12.5 invented + Tier δ math drift) | 2 minor | ~30 | 0 fresh-instance | FALSE | `_validation_log.md` 2026-05-11 Round 8 entry; agentId `aab08b0fae725a9da` |
| R8C1-2 | 1 | cross-reference | Pattern-E | 0 🔴 + 1 🟡 PLAN stub stale (6 skills proposed; 7 delivered) | 2 | ~25 | 0 | FALSE | (same) `ac8db6ffc2364ec43` |
| R8C1-3 | 1 | internal-consistency | Pattern-E | 2 (user-approval cadence + 8.F write-scope) | 6 | ~25 | 0 | FALSE | (same) `a456166a1917f51e3` |
| R8C1-4 | 1 | D72-edge-cases | Pattern-E | 0 (1 🔴 proposed-SI21 if Pattern F frozen) + 7 SI17-SI23 proposals | 3 | ~30 | 0 | FALSE | (same) `a93905934fad6bfb0` |
| R8C1-5 | 1 | advisory-research | Pattern-E | 0 🔴 + 6 🟡 framing (F1-F6 in `_research/round8-cycle1-evidence.md`) | 6 | ~45 | n/a | n/a | (same) + `_research/round8-cycle1-evidence.md`; `ad01ccf52d09a6045` |
| R8C3 | 3 | comprehensive-5-gate verify (post-cycle-2-fix) | single-agent | 1 (Pitfall #9.i 6th-consecutive fix-fresh-instance: § 12.5 sibling miss + § 4.7-4.11 retained in spec doc) | 1 | ~25 | 0 | FALSE | (same) `a9cad0dc3518236d3` |
| R8C5 | 5 | sleeper-bug stress (mandatory final per R4C8/R5C4/R6C4/R7C5 4-event precedent → R8C5 extends to 5 events) | single-agent | 3 (Section 10 non-existent in udm-round-closeout + cross-skill ordinal inconsistency + 9.j prospective-closure 9.j class) | 4 | ~30 | 0 | FALSE | (same) `a087d561ddcab6797` |
| R8C7 | 7 | final convergence verify (1st attempt) | single-agent | 2 (Pitfall #9.i from cycle 6 mechanical-fix-ADDS-content: § 2.2 L191 stale "Section 4.6 — NEW" + § 7.4 L664 silent omission of 8.G) | 0 | ~20 | 0 | FALSE | (same) `ae22294f46db3cc72` |
| R8C9 | 9 | final convergence verify (2nd attempt, post-cycle-8 fix) | single-agent | 0 ✅ CLEAN | 0 | ~12 | n/a (terminal — D99 acceptance invoked) | n/a | (same) `a3a291975055755d8` |
| R8-PF-INST1 | close-out | cascade-audit (Pattern F 2nd production) | Pattern-F Layer 2 paired | 0 🔴 + 1 🟡 (SI-series CLAUDE.md gap) + 1 candidate Trigger H | 1 | ~30 | n/a | n/a | (same) — runs at close-out cascade Section 9; agentId `a3c945444b494db86` |
| R8-PF-INST2 | close-out | cascade-audit (Pattern F 2nd production) | Pattern-F Layer 2 paired | 1 🔴 (B155 false-closure — CLAUDE.md missing Round 7 SP signatures + MIGRATION_AUTOMIC_INVENTORY + forward-only schema discipline) + 2 🟡 framing + 3 candidate triggers (G/H/I) | 5 | ~50 | n/a | n/a | (same); agentId `a10d4c8f5d0577771` |

**Pattern F paired-judgment empirical pattern at 2nd production event** (paralleling R7 first-production 5-vs-3 split): convergence on most findings; divergence reveals what single-agent would miss. INSTANCE 2 caught B155 false-closure that INSTANCE 1 marked ✅; INSTANCE 1 caught SI-series gap that INSTANCE 2 didn't flag. Per D89 paired-judgment orchestrator-judgment discipline: divergence resolved in favor of INSTANCE 2 (substantiated 🔴) + INSTANCE 1 (🟡 SI-series). Both fixed at cascade post-Pattern-F.

**Cumulative Round 8**: 11 🔴 caught + ~20 🟡 + 6 advisory framing; 9 review cycles + 2 Pattern F events; trajectory 5 → 1 → 3 → 2 → 0 → 0; **D99 convergence-confirmed acceptance** at cycle 9 (paralleling R5 D83 + R6 D88).

## Updated trends (post-Round-8)

### By specialty role (catch rate, post-Round-8)

| Specialty | Events to date | 🔴 found / event | False-clean rate | Average minutes | Verdict |
|---|---|---|---|---|---|
| `column-walk` | **8** (R2-3, R3 cycle 7, R3 cycle 8, R4C4-1, R5C1-1, R6C1-1, R7C1-1, **R8C1-1**) | 0-8 per cycle | **0%** (8 of 8 events) | 8-35 | **HIGHEST and most-empirically-validated specialty** — 8-event 0% false-clean confirmed. **Mandatory in every Pattern E batch**. R8C1-1 3-🔴 catch on Section number drift across 7 skill files + spec doc demonstrates surface continues to find load-bearing bugs even at Tier δ artifact sizes. |
| `cross-reference` | 5 (R4C4-2, R4C7, R5C1-2, R6C1-2, R7C1-2, **R8C1-2**) actually 6 | 0-8 per cycle | 0% | 12-50 | Catches Phase-0 miscites + cross-doc inconsistencies + PLAN stub stale (R8C1-2 finding). |
| `internal-consistency` | 5 (R4C4-3, R5C1-3, R6C1-3, R7C1-3, **R8C1-3**) | 2-7 substantive per cycle | 0% | ~10-25 | Catches contradictions within same artifact reliably. R8C1-3 found 2 🔴 + 6 🟡 (user-approval cadence + 8.F write-scope). |
| `D72-edge-cases` | 6 (R2-4, R4C4-4, R5C1-4, R6C1-4, R7C1-4, **R8C1-4**) | 0-7 per cycle | 0% | ~10-40 | Catches edge-case enumeration gaps + new SI-series additions (R8C1-4 proposed 7 SI17-SI23). |
| `advisory-research` | **6** (R2-5, R4C4-5, R5C1-5, R6C1-5, R7C1-5, **R8C1-5**) | 0 🔴 always | n/a (non-blocking) | 30-90 | **EMPIRICAL TRACK RECORD CONFIRMED across 6 events** — extended 5 → 6 events at Round 8. R8C1-5 found 6 framing-grade concerns (F1-F6) at `_research/round8-cycle1-evidence.md`. Distinct value layer confirmed industrial-strength. |
| `comprehensive-5-gate` | 8 (R4C5, R4C7, R5C2, R5C3, R6C2, R6C5, R7C2, R7C3, **R8C3**) actually 9 | 0-7 per cycle | mixed (R4C5 + R4C7 false-clean; R5C2/R6C2/R7C2/R7C3/R8C3 consistent catches) | 5-25 | Useful for fix-cycle verification; unreliable as primary first-pass for spec docs >50 KB. R8C3 caught 6th-consecutive Pitfall #9.i fix-fresh-instance. |
| `sleeper-bug-stress` | **5** (R4C8, R5C4, R6C4, R7C5, **R8C5**) | 1-3 per cycle (post-clean) | 0% across 5 events | ~10-30 | **MANDATORY FINAL CYCLE per 5-event precedent**. Every event surfaced substantive bugs prior reviewers missed. R8C5 found 3 🔴 (Section 10 non-existent + cross-skill ordinal inconsistency + 9.j prospective-closure class). |
| `convergence-verification` | 6 (R4C7, R5C5, R6C7, R7C7, **R8C7, R8C9**) | 0-3 per cycle (mixed — R5C5/R6C7/R8C9 clean; R4C7/R7C7/R8C7 found fresh-instance bugs) | 50% (R4C7 + R7C7 + R8C7 not clean; R5C5 + R6C7 + R8C9 clean) | ~3-30 | Mixed. R8C7 returned 2 🔴 demonstrating mechanical-fix-ADDS-content fresh-instance pattern persists at convergence-verify cycles even when sleeper-bug stress (C5) caught earlier; R8C9 ✅ CLEAN confirms post-cycle-8 fix. |
| `mechanical-fix` | 3 (R6C6, R7C8, **R8C6**) | 1-3 fresh-instance per cycle (this IS the fresh-instance-generator role) | n/a | ~5-15 | **NEW SPECIALTY observed at R6C6 + extended R7C8 + R8C6** — mechanical fixes that ADD content reliably introduce 9.i fresh-instances. R8C6 added Section 10 + 7-skill ordinal + § 0.5 self-classification + § 14 cycle log + § 11.1 prospective rewrite; R8C7 caught the 2 sibling-miss fresh-instances in spec doc § 2.2 + § 7.4. Pattern industrially confirmed. |
| `cascade-audit` | **8** (R6-RETRO × 2 + R6-UNSCOPED × 2 + R7-PF × 2 + **R8-PF × 2**) | 1-13 per event (R8 outliers 0 🔴 + 1 🔴) | 0% across 8 events | 28-55 | **Pattern F Layer 2 specialty — 8-event evidence base post-Round-8 cascade completion**. R8-PF-INST2's catch of B155 false-closure (INSTANCE 1 missed it) empirically substantiates the paired-judgment design — single-agent would not have caught this gap. Production-pattern confirmed across 8 events: paired-judgment Layer 2 reliably finds 5+ cascade gaps producer reflection misses at scale; at smaller cascades (R8) catches 1-2 with INSTANCE 2 having higher catch rate on specific cycles. |
| `feasibility-Tier0` | 1 (R2-2) | 0 | 0% | ~10 | Narrow scope. |

### Key empirical findings (cumulative as of 2026-05-11 post-Round-8)

22. **Pitfall #9 sub-class 9.j FORMALIZED at HANDOFF §8** per D96 + B144 2-event evidence base. Producer self-check Step 6 (extends 9.i 5-step audit to 6 steps): verify leading badge matches inline annotation; flip if mismatch.
23. **Column-walk specialty 8-event 0% false-clean** — extended from 7 events post-Round-7. Specialty's empirical strength continues at Tier δ artifact sizes (Round 8 ~130 KB total deliverable).
24. **Sleeper-bug stress 5-event 100% catch rate** — R4C8 + R5C4 + R6C4 + R7C5 + R8C5. Every event surfaced substantive bugs prior reviewers missed despite explicit walks. R8C5 found 3 🔴 (Section 10 non-existent in udm-round-closeout + cross-skill ordinal inconsistency + 9.j prospective-closure class) — within 1-2-🔴-per-event empirical band but slightly higher.
25. **Pitfall #9 sub-class 9.i industrially-confirmed at 6 fresh-instance occurrences** — R6 cycles 2/3/5/6/7 + R8 cycle 3 = 6 events across 2 rounds. Pattern continues structural-not-coincidental.
26. **Mechanical-fix-ADDS-content high-risk class confirmed at 3 events**: R6C6 (invented B141 forward-cite) + R7C8 (fix-application introduced SP-12 NULL regression) + R8C6 (Section 10 + ordinal fixes introduced sibling-miss in spec doc § 2.2 + § 7.4). Every event introduced fresh-instance bugs caught at subsequent verify cycle. Pairs with B120 9.i directive Step 7 extension proposal.
27. **D99 convergence-confirmed 3rd-event extends D83/D88 variant precedent** — R5 D83 + R6 D88 + R8 D99 all invoked convergence-confirmed at trajectory shape "declining-then-converged with sleeper-bug-stress depth exhausted + fix-fresh-instance class caught + final-verify clean". Distinct from D73/D78/D94 math-infeasibility variant.
28. **Tier δ 2nd event** (R6 + R8) — both convergence-confirmed. Tier γ cadence (Pattern E + sleeper-bug + Pattern F) empirically fits Tier δ artifacts; no cadence change proposed at this confidence level (LOW per 8.E minimum-event guard).

**Round 8 was the first round where**:
- 7 skill files + 1 meta-doc authored as round deliverables (vs prior rounds' spec-doc-only outputs)
- Self-improvement loop discipline self-applies (Round 8 IS the round that authored the discipline it produces)
- D99 convergence-confirmed acceptance invoked at cycle 9 paralleling R5 D83 + R6 D88
- Section 10 of udm-round-closeout authored to invoke the self-improvement loop at future round close-outs
- Pitfall #9 sub-class 9.j formalized inline at HANDOFF §8 (10 sub-classes total: 9.a-9.j)
- Pattern F 2nd-production invocation at close-out cascade (mandatory per D89)

### Round 1.5 D72 6-cycle campaign + Pattern F 3rd-production (2026-05-11)

| Agent | Cycle | Specialty | Mode | 🔴 | 🟡 | Min | Subsequent | False-clean | Cross-ref |
|---|---|---|---|---|---|---|---|---|---|
| R1.5C1-1 | 1 | column-walk | Pattern-E | 7 (PipelineExecutionGate.Status enum + IdempotencyLedger.Status enum + SP-10 name × 12 instances + @CategoryFilter type-width + SP-4 baseline + OrphanedTokenLog ER + CcpaDeletionLog ER) | 2 minor | ~30 | 0 fresh-instance | FALSE | `_validation_log.md` 2026-05-11 R1.5 entry; agentId `a4e863d2846f27d9a` |
| R1.5C1-2 | 1 | cross-reference | Pattern-E | 0 🔴 + 2 🟡 (D100 forward-cite; D40 NORTH_STAR L62 gap) | 2 | ~25 | 0 | FALSE | (same) `a265c4a63ae5a30f1` |
| R1.5C1-3 | 1 | internal-consistency | Pattern-E | 2 (filename/round-label mismatch; 5-supplement enumeration omitted) | 3 | ~25 | 0 | FALSE | (same) `a158f11820ad18562` |
| R1.5C1-4 | 1 | D72-edge-cases | Pattern-E | 2 (I24 unfiled; B-future placeholder discipline) | 5 | ~30 | 0 | FALSE | (same) `a49bb8851d285539c` |
| R1.5C1-5 | 1 | advisory-research | Pattern-E | 0 🔴 + 4 🟡 framing (control-tier external citation; RED method; UInt16 rationale; SupersededBy industry context) | 4 | ~45 | n/a | n/a | (same) + `_research/round1_5-cycle1-evidence.md`; `a621f87025a16ba07` |
| R1.5C3 | 3 | comprehensive-5-gate verify | single-agent | 3 (7th-event Pitfall #9.i: Cluster C audit-history off-by-one + Gate-1 self-check stale + dashboard query enum surviving) | 0 | ~25 | 0 | FALSE | (same) `a2c3d9b4a51417a09` |
| R1.5C5 | 5 | sleeper-bug stress (6-event 100% catch rate extended) | single-agent | **8** (SP-8 Status='SUCCESS' surviving + PiiVault.PiiCategory invented × 3 sites + @CategoryFilter Gate-1 contradiction + SP-4 audit-history off-by-one + PiiTokenizationBatch × 3 sites + token VARCHAR(40) discipline + B-4 marker drift + 09_VISUALS ER comprehensive drift across 9 tables) | 4 | ~30 | 0 | FALSE | (same) `a24fc577d31fc65f9` |
| R1.5-PF-INST1 | close-out | cascade-audit (Pattern F 3rd production) | Pattern-F Layer 2 paired | 1 🔴 (CLAUDE.md D100/D101 registration) + 2 🟡 (G1-G6 letter mapping; B173 9-table list verification) | 2 | ~30 | n/a | n/a | (same) `a9ca842d4e344bc19` |
| R1.5-PF-INST2 | close-out | cascade-audit (Pattern F 3rd production) | Pattern-F Layer 2 paired | 1 🔴 (D93 violation — 02_PHASES + PHASE_1_DEEP_DIVE_PLAN + 00_OVERVIEW missing Round 1.5) + 2 🟡 X2 (Trigger J candidate) + X3 (5th math-infeasibility sub-variant) | 4 | ~35 | n/a | n/a | (same) `a993aae6e677a974c` |

**Cumulative Round 1.5**: 22 cycle 🔴 + 1 Pattern F 🔴 = 23 substantive findings caught + fixed. **Paired-judgment Pattern F disagreement** on D100/D101 CLAUDE.md registration — INSTANCE 1 said required; INSTANCE 2 said NOT required per B86/B155 precedent (process discipline lives in HANDOFF + GLOSSARY, not CLAUDE.md). Orchestrator resolved per D89 paired-judgment: INSTANCE 2 reading aligns with prior precedent. INSTANCE 2's D93 violation 🔴 took precedence and was fixed (02_PHASES + PHASE_1_DEEP_DIVE_PLAN + 00_OVERVIEW now reference R1.5). 

**D101 math-infeasibility acceptance** (4th math-infeasibility variant after D73/D78/D94; distinct from D83/D88/D99 convergence-confirmed).

## Updated trends (post-Round-1.5)

### By specialty role (catch rate, post-Round-1.5)

| Specialty | Events to date | 🔴 found / event | False-clean rate | Average minutes | Verdict |
|---|---|---|---|---|---|
| `column-walk` | **9** (R2-3 + R3 cycle 7 + R3 cycle 8 + R4C4-1 + R5C1-1 + R6C1-1 + R7C1-1 + R8C1-1 + **R1.5C1-1**) | 0-8 per cycle | **0%** (9 of 9 events) | 8-35 | **9-event 0% false-clean — extended track record** |
| `cross-reference` | **6** (R4C4-2 + R5C1-2 + R6C1-2 + R7C1-2 + R8C1-2 + **R1.5C1-2**) | 0-8 per cycle | 0% | 12-50 | Consistent value |
| `internal-consistency` | **5** (R4C4-3 + R5C1-3 + R6C1-3 + R7C1-3 + **R1.5C1-3**) | 2-7 substantive | 0% | ~10-25 | Consistent |
| `D72-edge-cases` | **6** (R2-4 + R4C4-4 + R5C1-4 + R6C1-4 + R7C1-4 + R1.5C1-4 + **R8C1-4**) | 0-7 per cycle | 0% | ~10-40 | Consistent |
| `advisory-research` | **7** (R2-5 + R4C4-5 + R5C1-5 + R6C1-5 + R7C1-5 + R8C1-5 + **R1.5C1-5**) | 0 🔴 always | n/a (non-blocking) | 30-90 | **EMPIRICAL TRACK RECORD CONFIRMED across 7 events** — distinct framing-grade value layer |
| `sleeper-bug-stress` | **6** (R4C8 + R5C4 + R6C4 + R7C5 + R8C5 + **R1.5C5**) | 1-8 per cycle | 0% across 6 events | ~10-30 | **MANDATORY FINAL CYCLE per 6-event precedent**. R1.5C5's 8-🔴 catch = largest single sleeper-bug catch in project history; identifies 09_VISUALS ER comprehensive drift across 9 tables (load-bearing B173 carryover) |
| `cascade-audit` | **10** (R6-RETRO × 2 + R6-UNSCOPED × 2 + R7-PF × 2 + R8-PF × 2 + **R1.5-PF × 2**) | 1-13 per event | 0% across 10 events | 28-55 | **Pattern F Layer 2 specialty — 10-event evidence base post-Round-1.5**. R1.5-PF-INST2 caught D93 cross-doc cascade violation that INSTANCE 1 missed — empirically substantiates paired-judgment design for 3rd production event. |
| (other specialties unchanged) | | | | | |

### Key empirical findings (cumulative as of 2026-05-11 post-Round-1.5)

29. **Pitfall #9 sub-class 9.i 7-event campaign** (R6 cycles 2/3/5/6/7 + R8 cycle 3 + R8 cycle 7 + **R1.5 cycle 3** = 7 fresh-instance recurrences across 3 rounds). Pattern industrially confirmed at non-coincidental confidence — extends from 6 to 7 events.
30. **Sleeper-bug stress 6-event 100% catch rate extended**. R1.5C5 found 8 🔴 — largest single sleeper-bug catch in project history. The 09_VISUALS comprehensive ER drift across 9 tables (B173 carryover) was the scope-exhausting finding driving D101 math-infeasibility acceptance.
31. **D101 math-infeasibility 4th-event extends D73/D78/D94 variant precedent** — combined supplement-cluster math-infeasibility distinct from prior 3-clean-ceiling math-infeasibility cases. Sub-variant proposed (B177 — "scope-exhausting deferral" sub-variant per Pattern F INSTANCE 2 X3).
32. **Paired-judgment design validated for 3rd production Pattern F event**. INSTANCE 1 + INSTANCE 2 disagreed on D100/D101 CLAUDE.md registration; INSTANCE 2's D93 violation catch was independently substantive (02_PHASES / PHASE_1_DEEP_DIVE_PLAN / 00_OVERVIEW silent omission). Pattern: paired Layer-2 reliably finds what single-instance reviewer would miss.
33. **NEW empirical pattern observed at R1.5**: combined supplement-cluster validation has higher 🔴 yield (22 per ~80 KB across 5 docs) than single Tier γ spec doc (typical 10-15 🔴 per spec doc). Cross-supplement column-name drift propagates across cluster siblings — e.g., PiiTokenizationBatch column drift across 3 sites for 1 underlying error.

## Last reviewed

2026-05-11 (**Round 1.5 close-out + Pattern F 3rd production**: 9 new ledger entries for R1.5 cycles 1+3+5 (7 events) + 2 cascade-audit events R1.5-PF-INST1 + R1.5-PF-INST2; **10-event cascade-audit specialty evidence base** post-Round-1.5; 33 cumulative key empirical findings; **D101 math-infeasibility acceptance variant 4th invocation**; column-walk specialty 9-event 0% false-clean; sleeper-bug 6-event 100% catch rate; advisory-research 7-event 0% 🔴; paired-judgment Pattern F 3-event production track record. **PHASE 1 COMPLETE + R1.5 SUPPLEMENTS — Rounds 1-8 + R1.5 all 🟢 Locked.**). Previous: 2026-05-11 Round 8 close-out + Pattern F 2nd production; Round 7 close-out + Pattern F 1st production; 2026-05-10 Round 6 close-out.
