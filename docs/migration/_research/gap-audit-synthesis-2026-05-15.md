# Gap audit synthesis — multi-agent reflection on planning sessions

**Date**: 2026-05-15
**Triggered by**: on-demand (user request — "Reflect on the last planning sessions. Are there any gaps in the plans? Are there any edge cases worth considering?")
**Workflow**: 3 parallel general-purpose agents executed independent gap audits from 3 perspectives; this artifact synthesizes their findings + classifies severity + recommends pre-sign-off action.
**Anchor**: D55 5-gate validation discipline + §16.5 multi-agent team patterns + Pitfall #9 sub-class accumulator

---

## Executive summary

🔴 **Plan is research-rich but execution-poor.** All 3 independent gap audits converged on the same headline: the plan validates direction but is missing concrete execution specifications. Before pipeline-lead flips Plan-final → 🟢 Locked, **5 mandatory pre-sign-off fixes** are essential. Without them, an operator handed this plan tomorrow morning will be blocked within 30 minutes.

🟡 **2 fixes already applied this commit** (the most critical contradictions): §13.4 internal contradiction (em-dash MUST + em-dash BROKEN) restructured to lead with empirical findings; archive trigger threshold standardized at 2,000 lines (was 5K vs 2K vs unspecified across artifacts).

🟡 **3 fixes remain pre-sign-off**: (a) `tools/verify_cascade.py` `_archive/` glob extension; (b) literal archive cutoff date in §7.1; (c) Q-N classification table separating sign-off-blocking from answer-when-needed.

⚪ **8 polish items + edge cases surfaced** for follow-up B-Ns post-approval.

Confidence: 🟢 High — 3 independent audits converged; combined ~600-line scrutiny; multiple specific contradictions cited with file:line precision.

---

## Source artifacts (3 parallel gap audits)

| # | Path | Perspective | Lines | Top finding |
|---|---|---|---|---|
| 1 | `_research/gap-audit-producer-2026-05-15.md` | "Engineer about to execute Phase 1 tomorrow" | ~210 | F-7 BLOCKER: `verify_cascade.py` doesn't glob `_archive/` |
| 2 | `_research/gap-audit-adversarial-2026-05-15.md` | Red-team failure-mode reviewer | ~200 | F9.1 CRITICAL: Phase 1.0 lands but INDEX.md never does → repo worse than before |
| 3 | `_research/gap-audit-consistency-2026-05-15.md` | Cross-cutting consistency + governance auditor | ~220 | C-1 CONTRADICTION: §13.4 says em-dash MUST + em-dash BROKEN |

Each audit produced its own severity classification + top-5 recommendations. This synthesis consolidates across all 3.

---

## Findings consolidated (cross-audit)

### 🔴 BLOCKERS (5 — must close before pipeline-lead sign-off)

**B-1: §13.4 internal contradiction** (Consistency C-1) — ⚫ **FIXED THIS COMMIT**
- §13.4 opened with "MUST use em-dash" rule, listed em-dash as ✅ in best-practice table, then 14 lines later said em-dash is 🔴 BROKEN
- Top-down readers got the WRONG rule until they reached the empirical caveat
- **Fix applied**: §13.4 restructured to lead with revised colon-form rule; deprecated em-dash rule rewritten as PROHIBITED with explicit ❌ markers; self-referential acknowledgment added that the plan itself uses em-dash in historical headings (forward-only D92)

**B-2: Archive trigger contradiction** (Consistency C-2) — ⚫ **FIXED THIS COMMIT**
- §16.1 hygiene table said archive at **5,000 lines**
- §16.2 + NEW_REPO_STARTER_TEMPLATE.md + `tools/measure_ccl_overhead.py` constant said **2,000 lines**
- Inconsistent threshold across plan + tooling + template
- **Fix applied**: Standardized on 2,000 lines (aligns with §9 CCL metric + NEW_REPO_STARTER_TEMPLATE + measurement script constant). §16.1 + Q-23 reference both updated.

**B-3: `tools/verify_cascade.py` `_archive/` glob missing** (Producer F-7) — 🔴 **OPEN; mandatory pre-sign-off**
- `verify_cascade.py::default_scan_paths()` hardcodes scan targets; doesn't include `_archive/` paths
- When Phase 1.0 archive cascade fires, archived entries silently drop out of Pattern F audit coverage
- Risk: months of audit blind-spots before anyone notices
- **Fix needed**: 5-line edit to `default_scan_paths()` to include `_archive/**/*.md` glob
- **Must land BEFORE Phase 1.0 archive**, not as Phase 2.4 deliverable
- New B-N candidate: B-272 (proposed)

**B-4: Three conflicting archive cutoff date rules** (Producer F-1) — 🔴 **OPEN; mandatory pre-sign-off**
- Plan §5.1 implies "30 days"
- NEW_REPO_STARTER_TEMPLATE.md §6 says ">30-days-ago"
- Canonical policy at `_validation_log.md` L13-15 says "older than 90 days"
- Proposed 2026-04-12 cutoff doesn't match any of them precisely
- Operator at execution time has no authoritative tiebreaker
- **Fix needed**: Pipeline-lead picks ONE rule + plan §7.1 task 1.1 cites the literal cutoff date (e.g., "2026-04-15 = 30 days before today" OR "2026-02-15 = 90 days before today")
- New B-N candidate: B-273 (proposed)

**B-5: 17 of 24 open Q-N unclassified by sign-off-blocking vs deferrable** (Producer F-15) — 🔴 **OPEN; mandatory pre-sign-off**
- Plan §10 has Q-1 through Q-26; Q-13 + Q-22 RESOLVED; 24 remain
- NO classification of which questions BLOCK pipeline-lead's sign-off vs which are "answer-when-needed"
- Pipeline-lead reading the plan can't tell what's actually gating approval
- Best read: 4 questions actually block (Q-1 approval to proceed / Q-2 cutoff date / Q-12 CLAUDE.md trim / Q-23 hygiene-rules-as-binding)
- **Fix needed**: Add §10.A "Sign-off-blocking vs deferrable" classification table
- New B-N candidate: B-274 (proposed)

### 🔴 CRITICAL FAILURE MODES (3 — must mitigate before execution)

**F9.1 Phase 1.0 lands, INDEX.md never does** (Adversarial top-1)
- "Operator gets quick win on archive cascade then loses momentum"
- Repo ends WORSE than before because audit-trail navigation now needs cross-file awareness without a routing manifest to guide it
- Canonical "ship MVP, never ship V1" anti-pattern
- **Mitigation**: Bundle Phase 1.0 + Phase 1.B INDEX.md as ATOMIC COHORT (reject if either lands without the other); add to plan §5.1 as binding constraint

**F1.1 Archive partial-write crash** (Adversarial top-2)
- Script crashes between archive-write and live-truncate
- Append-only invariant violated; D55 audit trail has a hole
- Plan §7.1 task 1.2 specifies no atomic-rename / two-phase commit pattern
- Windows dev workstation has no `flock` as additional risk vector
- **Mitigation**: Specify two-phase-commit semantics for archive script: (1) write archive file + verify hash; (2) atomically replace live file with truncated version (mv -T or equivalent); (3) only delete original after both succeed

**F5.1 udm-context-loader brief silently omits Do-NOT rule** (Adversarial top-3)
- Subagent distillation drops a load-bearing constraint
- Downstream agents lack the omitted context and CAN'T ask "what's missing?" because they don't have the full text
- Destruction-class production changes become possible
- **Mitigation**: Require `udm-context-loader` briefs to PASS-THROUGH-VERBATIM every Do-NOT rule + Pitfall #9.x header (not summarize them); add to plan §15.2 Pattern D + §16.5 anti-patterns

### 🟡 SERIOUS issues (8 — fix in Phase 1 OR open as B-N)

| # | Finding | Source | Recommended action |
|---|---|---|---|
| 6 | `_research/_INDEX.md` register MISSING — referenced 4× across plan + template as binding Q1 governance, doesn't exist | Consistency E-4 | Author at Phase 1.0; until then no research artifact tracking |
| 7 | Plan violates own colon-form rule (uses em-dash in own §X.Y headings) | Adversarial #10 + Consistency #8 | Acknowledged via §13.4 self-referential exemption; bulk-normalize at next refactor cycle |
| 8 | Plan is 997 lines = 42% past §13's own 700-line split-trigger | Consistency #8 | Acknowledged via §15 preamble; defer split until after sign-off |
| 9 | 5 locations cite stale "12K-16K lines per CCL" estimate that §15.4 measured as 9,212 actual | Consistency drift | Update inline to "9,212 lines / 362K tokens" empirical value |
| 10 | `udm-find-canonical` skill design unclear — multiple candidates? case sensitivity? OOM scenarios? | Adversarial #4 | Open B-N for skill-design clarification before authoring |
| 11 | Lead-with-answer enforcement claimed but no CI mechanism | Consistency #5 | Plan says "regex check (best-effort; advisory not blocking)" — that's the mechanism; explicit |
| 12 | Quarterly Q11 audit failure modes (audit not run; audit catches drift but no one fixes) | Adversarial #7 | Plan §16.4 names "rotating quarterly owner" but no enforcement; add to §16.1 governance |
| 13 | External-platform breaking changes (Anthropic skills / GitHub slug / context budgets) | Adversarial #8 | Add risk register entry post-sign-off |

### ⚪ POLISH items (6 — open as P-Ns post-approval)

| # | Finding | Source |
|---|---|---|
| P-1 | §14 missing entirely (renumbering artifact) | Consistency #9 |
| P-2 | §12 sign-off appears AFTER §16 (section ordering broken; cosmetic only since §16 is "later content") | Consistency #9 |
| P-3 | Plan's own §X.Y headings don't lead with answers consistently (claims discipline; doesn't apply self) | Consistency #8 |
| P-4 | NEW_REPO_STARTER_TEMPLATE.md doesn't fully demonstrate the 8 principles it preaches (e.g., it doesn't have lead-with-answer in every section) | Adversarial #10 |
| P-5 | 5-line "I just got this; how do I start?" quick-start missing from plan | Producer #8 |
| P-6 | Sign-off mechanism procedurally undefined — what does pipeline-lead actually DO to sign off? Edit a row? | Producer #9 |

---

## Concrete pre-sign-off action plan

### IMMEDIATE (before pipeline-lead reviews; this commit)

✅ **Fix §13.4 contradiction** — DONE THIS COMMIT
✅ **Fix archive-trigger threshold (5K → 2K)** — DONE THIS COMMIT
🟡 **Synthesis artifact authored** — THIS DOCUMENT
🟡 **§17 plan section authored** — referencing this synthesis + the remaining 3 mandatory fixes

### MANDATORY pre-sign-off (next 1-2 sessions; before pipeline-lead approves)

🔴 **B-3: extend `verify_cascade.py` `default_scan_paths()` with `_archive/` glob** — 5-line edit
🔴 **B-4: pipeline-lead picks archive cutoff rule** — 30-day vs 90-day decision; plan §7.1 task 1.1 updated with literal cutoff date
🔴 **B-5: §10.A Q-N classification table** — sign-off-blocking vs deferrable for all 24 open questions

### Phase 1 entry conditions (after sign-off)

🟡 **F9.1 mitigation: bundle Phase 1.0 + 1.B as atomic cohort** — add to §5.1 as binding constraint
🟡 **F1.1 mitigation: two-phase-commit archive script** — add to §7.1 task 1.2 as procedural requirement
🟡 **F5.1 mitigation: pass-through-verbatim Do-NOT/Pitfall in udm-context-loader briefs** — add to §15.2 Pattern D

### Post-sign-off cleanup (Phase 1 close-out OR scheduled later)

⚪ Author `_research/_INDEX.md` register (gap #6)
⚪ Open B-N for `udm-find-canonical` design clarification (gap #10)
⚪ Add risk register entry for external-platform breaking changes (gap #13)
⚪ P-1 through P-6 polish items as P-Ns

---

## Multi-agent pattern observations (Q4 reflection)

This was the 2nd 3-parallel-agent session this cycle. Validations:

✅ **3-parallel-agent pattern works for ORTHOGONAL audits** — when each agent has a genuinely different perspective (producer / adversarial / consistency), parallel execution yields convergent findings WITHOUT context-rot. ~5 min wall-clock vs ~15 min if sequential.

✅ **Convergence is signal** — when all 3 audits independently flag the same finding (e.g., "plan is research-rich but execution-poor"; "Phase 1.0 + 1.B partial-completion risk"; "archive threshold contradiction"), that's high-confidence ground truth.

⚠️ **Anti-pattern reinforcement (per §16.5)**: 3 is the limit. A 4th parallel agent would not have added marginal value (the 3 perspectives already cover the design space). The §16.5 anti-pattern "Running >3 parallel research agents" is empirically validated AGAIN.

⚠️ **Cost calibration**: each gap-audit agent consumed ~160K tokens / ~20 tool uses / ~3-4 minutes. 3 in parallel = ~480K tokens cumulative. This is sustainable for periodic deep-dive audits but NOT a per-commit pattern.

**Recommendation for §16.5**: add a new pattern "**Periodic gap-audit cohort (3-perspective parallel)**" — fire at major plan revisions or pre-lock; not at every cycle.

---

## What this audit does NOT cover

- The empirical correctness of the 6 prior research artifacts (only their cross-references + consistency)
- The Pattern F audit script's actual behavior (only the gap that it doesn't glob `_archive/`)
- Performance benchmarks (the audit is a static analysis; runtime behavior of the proposed scripts not measured)
- Pipeline-lead workflow (how sign-off mechanically happens — surfaced as P-6 polish)

---

## Recommendation

**Accept the 2 inline fixes applied this commit** + **assign 3 mandatory pre-sign-off fixes** (B-3 + B-4 + B-5) + **defer 8 SERIOUS + 6 POLISH items as B-Ns / P-Ns post-approval**.

The plan is genuinely close to execution-ready. The audit's value is identifying that "research-rich + execution-poor" is the actual state — not "research-poor" (which would mean more research needed) or "execution-blocked-on-tooling" (which would mean Phase 2 work needed first). The 5 BLOCKERS + 3 CRITICAL failure-mode mitigations are the gap; closing them takes ~1-2 sessions; then sign-off is realistic.

🟢 **Recommendation**: pipeline-lead approves the 3 mandatory pre-sign-off fixes (B-3 + B-4 + B-5) inline OR delegates them to the next session, then signs off Plan-final → 🟢 Locked. Phase 1 begins per §7.1 task breakdown WITH F9.1/F1.1/F5.1 mitigations applied at task definition time (not as separate work).
