# Phased execution breakdown for MARKDOWN_REFACTOR_PLAN.md remaining work

**Date**: 2026-05-15
**Scope**: Phase-by-phase decomposition of the remaining MARKDOWN_REFACTOR_PLAN.md work, from current "Plan-final pending sign-off" boundary through year-1 long-term governance.
**Anchors**: `MARKDOWN_REFACTOR_PLAN.md` §5.1 (Phase 1 task list) + §7.1 (Phase 1 work breakdown) + §16.4 (year-1 milestones) + §17 (gap audit reflection); `_research/gap-audit-synthesis-2026-05-15.md` (BLOCKER classification); `_research/ccl-baseline-2026-05-15.md` (empirical priority sequencing); `_research/em-dash-slug-test-2026-05-15.md` (Phase B heading-style migration).
**Status**: planning-tier artifact; complementary to the plan itself; not a binding commitment until pipeline-lead reviews.

---

## Summary table

| Phase | Scope (1 line) | Effort | Blocker / deferrable |
|---|---|---|---|
| **A** | Pre-sign-off cleanup — 3 mandatory BLOCKERS (B-3 + B-4 + B-5) | 30-60 min | 🔴 BLOCKER (gates sign-off) |
| **B** | Pre-execution mitigations — 3 CRITICAL failure modes (F9.1 + F1.1 + F5.1) | ~30 min | 🔴 BLOCKER (gates sign-off + Phase D) |
| **C** | Sign-off ceremony — pipeline-lead review + §12 lock + status flip | 30-60 min pipeline-lead | 🔴 GATE (gates everything downstream) |
| **D** | Phase 1 execution per plan §7.1 (archive + INDEX.md + skill cascade + CLAUDE.md trim) | 1-2 cycles | 🔴 BLOCKER (the headline work) |
| **E** | Phase 2 tooling — regenerator + Tier 0/1 tests + pre-commit + Pattern F extension + udm-context-loader subagent | ~1 cycle | 🟡 Deferrable post-Phase-D |
| **F** | Conditional Phase 3 — file splits (only if Phase A-E metrics fall short) | ~1-2 cycles | ⚪ Conditional (skip if not needed) |
| **G** | Conditional Phase 4 — frontmatter + tagged sections + polish | ~1 cycle | ⚪ Conditional (skip if not needed) |
| **H** | Long-term governance — quarterly Q11 + `_research/_INDEX.md` + sign-off mechanism + multi-agent patterns | ~3 hours one-time + recurring | 🟡 Deferrable post-Phase-D |

**Total effort (mandatory phases A-D)**: ~1.5-3 cycles wall-clock; ~5-8 hours of active work.
**Total effort (all phases A-H)**: ~3-5 cycles wall-clock; ~12-16 hours of active work + recurring quarterly Q11.

---

## Phase A — Pre-sign-off cleanup (3 mandatory BLOCKERS)

### Scope
Close the 3 open mandatory BLOCKERS identified in `_research/gap-audit-synthesis-2026-05-15.md`. None of these is hard work; the gating constraint is pipeline-lead decision-time on B-4 (archive cutoff date). All 3 must close before Phase C sign-off ceremony fires.

### Tasks
1. **B-3**: Extend `tools/verify_cascade.py` `default_scan_paths()` to include `_archive/**/*.md` glob (5-line edit). Test by running `py tools/verify_cascade.py` and confirming any existing `_archive/` files appear in the audit output.
2. **B-4**: Pipeline-lead picks ONE archive cutoff rule from the 3 conflicting candidates (30-day per plan §5.1 / >30-day per template §6 / 90-day per `_validation_log.md` L13-15) and updates plan §7.1 task 1.1 with the literal cutoff date in `YYYY-MM-DD` form.
3. **B-5**: Author plan §10.A classification table — 1 row per open Q-N (Q-1 through Q-26 minus Q-13 + Q-22 resolved); column 1 = Q-N; column 2 = sign-off-blocking (yes/no); column 3 = rationale. Best read from gap-audit synthesis: ~4 questions actually block (Q-1 approval / Q-2 cutoff / Q-12 CLAUDE.md trim / Q-23 hygiene-rules-as-binding).

### Effort estimate
- B-3: 5-10 min (script edit + dry-run verify)
- B-4: 10-15 min (pipeline-lead decision + plan edit) — gated on pipeline-lead availability
- B-5: 15-25 min (classification table authoring, ~24 rows)
- **Total**: 30-60 minutes wall-clock IF pipeline-lead is available; otherwise B-4 stretches to next pipeline-lead review window

### Dependencies
- None upstream — all 3 are inline edits to existing artifacts
- Pipeline-lead availability for B-4

### Acceptance criteria
- `tools/verify_cascade.py` `_archive/**/*.md` glob present and verified via dry-run
- Plan §7.1 task 1.1 cites a literal `YYYY-MM-DD` cutoff with rationale (30 vs 90)
- Plan §10.A classification table exists; every open Q-N has a sign-off-blocking determination
- All 3 changes committed in a single atomic commit (or 3 commits with clear progression)

### Risk register
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Pipeline-lead unavailable for B-4 decision | Low | Low | Operator can stub B-4 as "30-day per plan §5.1 (default; pipeline-lead may revise at C)"; pipeline-lead overrides at sign-off |
| §10.A classification creates new disagreements | Low | Low | Each row is a recommendation; pipeline-lead has final say at Phase C |
| `verify_cascade.py` edit accidentally breaks existing audit coverage | Low | Medium | Dry-run before commit; compare audit output pre-/post-edit |

### Sign-off gate
Operator confirms all 3 BLOCKERS closed; pipeline-lead reviews at Phase C.

---

## Phase B — Pre-execution mitigations (3 CRITICAL failure modes)

### Scope
Mechanical plan edits that add specific anti-failure-mode constraints flagged by the adversarial gap audit. None changes the plan's direction; all 3 add specificity that prevents documented failure modes during Phase D execution.

### Tasks
1. **F9.1**: Add to plan §5.1 — "Phase 1.0 + Phase 1.B INDEX.md are an ATOMIC COHORT; do not commit Phase 1.0 without Phase 1.B simultaneously; explicit reject-if-either-missing gate at Phase C sign-off." Mechanical edit.
2. **F1.1**: Add to plan §7.1 task 1.2 — Two-phase-commit procedure for archive script: (1) write `_archive/_validation_log_archive_YYYY-MM.md` + verify SHA-256 hash matches original content range; (2) atomically replace live `_validation_log.md` with truncated version via `os.replace()` (POSIX `rename()` equivalent; cross-platform atomic on same filesystem); (3) only delete pre-archive temp file after both succeed. Document Windows-on-dev caveat (no `flock` available; rely on file-handle exclusivity).
3. **F5.1**: Add to plan §15.2 Pattern D + §16.5 anti-patterns — "`udm-context-loader` subagent briefs MUST pass-through-verbatim every Do-NOT rule + every Pitfall #9.x sub-class header (do not summarize, do not paraphrase, do not omit)." Reference this as a Do-NOT itself in the udm-context-loader skill SKILL.md.

### Effort estimate
- F9.1: 5-10 min
- F1.1: 10-15 min (procedure spec + Windows caveat)
- F5.1: 10-15 min (anti-pattern entry + mirror to skill SKILL.md when authored)
- **Total**: ~30 minutes

### Dependencies
- Phase A complete (consolidates pre-sign-off edits into one commit cycle)
- None other; these are all mechanical plan edits

### Acceptance criteria
- Plan §5.1 contains explicit ATOMIC COHORT constraint for Phase 1.0 + 1.B
- Plan §7.1 task 1.2 contains two-phase-commit procedure with verifiable steps
- Plan §15.2 Pattern D + §16.5 anti-pattern entries contain pass-through-verbatim mandate
- Cross-references between the 3 mitigations and §17 (gap audit reflection) are bidirectional

### Risk register
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Two-phase-commit procedure under-specifies hash-verification step | Low | Medium | Reference `hashlib.sha256()` + explicit bytes-range citation in plan |
| Pass-through-verbatim rule conflicts with subagent token budget | Low | Low | Plan §15.2 Pattern D already explicitly accepts ~500-1K line briefs; verbatim of Do-NOT + Pitfall is ~50-100 lines max |
| ATOMIC COHORT constraint blocks Phase D progress if Phase 1.B INDEX.md slips | Medium | Low | This is the desired behavior — F9.1 explicitly chose this trade-off |

### Sign-off gate
Operator confirms all 3 mitigations land in same commit cycle as Phase A; pipeline-lead reviews at Phase C.

---

## Phase C — Plan-locks (sign-off ceremony)

### Scope
Pipeline-lead reviews the consolidated Phase A+B commit, answers the sign-off-blocking Q-Ns from §10.A, and signs off via §12 mechanism. Plan status flips 🟡 Plan-final → 🟢 Locked. This is the gate that authorizes Phase D execution.

### Tasks
1. Pipeline-lead reads the consolidated Phase A+B commit
2. Pipeline-lead answers each sign-off-blocking Q-N per §10.A classification table
3. Pipeline-lead executes §12 sign-off mechanism (currently P-6 polish gap; needs definition — see Phase H task H.3)
4. Plan status flips 🟡 Plan-final → 🟢 Locked
5. Commit lands with `chore(round-6): MARKDOWN_REFACTOR_PLAN.md → 🟢 Locked` message
6. `_validation_log.md` row appended for the lock event (per udm-progress-logger discipline)

### Effort estimate
- Pipeline-lead review: 30-60 min depending on Q-N depth
- Sign-off mechanism execution: 5-10 min (once defined)
- Lock commit + log row: 10 min
- **Total**: ~45-75 minutes wall-clock

### Dependencies
- Phase A + Phase B complete (consolidates pre-sign-off material)
- Pipeline-lead availability
- Sign-off mechanism defined (Phase H.3 if formalizing inline; otherwise ad-hoc "Pipeline lead edits §12 table row")

### Acceptance criteria
- Plan §12 carries pipeline-lead name + date + ✅ Approved decision
- Plan status header flips 🟡 Plan-final → 🟢 Locked
- All sign-off-blocking Q-Ns answered in §10.A or in §12 notes
- `_validation_log.md` row recorded for the lock event
- Phase D entry conditions met (per §17.2 + §17.3 gating)

### Risk register
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Pipeline-lead requests redirect (🔄) instead of approval | Medium | Medium | Plan re-enters revision cycle; B-Ns opened for any new asks; Phase D delayed but not blocked |
| Pipeline-lead approves with unresolved deferrable Q-Ns | Low | Low | §10.A explicitly distinguishes sign-off-blocking from deferrable; deferrable Q-Ns can answer later |
| Sign-off mechanism is ambiguous (P-6 polish gap) | Medium | Low | Default: pipeline-lead edits §12 table row directly; formalize later via Phase H.3 |

### Sign-off gate
Pipeline-lead approves via §12; this IS the gate for Phase D.

---

## Phase D — Phase 1 execution per plan §7.1 (the actual work)

### Scope
Execute the headline markdown refactor work specified in plan §7.1 — archive `_validation_log.md` (cuts ~62% of CCL Stage 1+2 token cost), author INDEX.md routing manifest, update D62 CCL doctrine, cascade updates to udm-* skill SKILL.md files, trim CLAUDE.md, and gate on Pattern E independent review. This is the value-delivery phase; everything upstream serves this.

### Tasks
1. **D.0 Pre-execution prep**: Build remaining tooling — `tools/rewrite_cross_refs.py` (if cross-ref rewrites needed for archive split) + scaffold `.claude/skills/udm-find-canonical/SKILL.md` (per plan §5.1 Phase 1.E)
2. **D.1 Execute Phase 1.0 archive cascade** (per plan §7.1 task 1.2 + F1.1 two-phase-commit per Phase B): archive `_validation_log.md` history older than chosen cutoff (B-4 decision) into `_archive/_validation_log_archive_YYYY-MM.md`; truncate live file to retain only recent N rounds; add 1-line back-reference at top of live file
3. **D.2 Execute Phase 1.B INDEX.md authoring** (per plan §7.1 task 1.3 + F9.1 atomic-cohort per Phase B): author `docs/migration/INDEX.md` as routing-by-intent manifest (per ETH Zurich research §3.6 Finding 5); include D-numbers / B-numbers / R-numbers / SP-N / RB-N / Pattern codes / Pitfall sub-classes / EventType families. MUST land in same commit as D.1.
4. **D.3 Execute Phase 1.5 D62 CCL Stage 0 update + skill prompt cascade** (per plan §7.1 task 1.5): update D62 in `03_DECISIONS.md` to add Stage 0 (read `INDEX.md` first); grep `.claude/skills/**/SKILL.md` for D62 / CCL references; bulk-update affected skills with Stage 0 reference
5. **D.4 Execute Phase 1.5b skill SKILL.md updates** (per plan §10b.1 G-MR3 enumeration): enumerate affected skills BEFORE the sweep; bulk-update via single commit OR per-skill commits with per-skill validation
6. **D.5 Execute Phase 1.6 CLAUDE.md trim** (per plan §10b.1 G-MR2 + Q-12): audit CLAUDE.md (715 lines) against Anthropic "would removing this cause Claude to make mistakes?" test; move sometimes-relevant content to skills; target ~300 lines
7. **D.6 Pattern E independent review (Gate 2)**: spawn `udm-design-reviewer` agent + `udm-checks-and-balances` skill against the Phase D commits; surface any 🔴 (broken cite, lost content, INDEX-vs-source drift); D56 mandatory second-pass if 🔴 found

### Effort estimate
- D.0: 1-2 hours (skill scaffold + tooling)
- D.1: ~1 hour (archive cascade per plan §7.1)
- D.2: ~2-3 hours (INDEX.md authoring per plan §7.1; ~300-500 lines)
- D.3: ~1 hour (D62 update + skill prompt sweep)
- D.4: ~1-2 hours (skill cascade; depends on count enumerated)
- D.5: ~1-2 hours (CLAUDE.md audit + trim; 715 → ~300 lines)
- D.6: ~30-60 min (Pattern E review; longer if 🔴 found)
- **Total**: ~8-12 hours active work = 1-2 cycles wall-clock (per plan §7.1 estimate)

### Dependencies
- Phase C complete (sign-off gate)
- B-3 `verify_cascade.py` fix landed (Phase A); audit coverage of `_archive/` glob required for D.1
- B-4 archive cutoff date decided (Phase A); literal date required for D.1
- F1.1 two-phase-commit procedure specified (Phase B); required for D.1 execution
- F9.1 atomic-cohort constraint accepted (Phase B); required for D.1 + D.2 coordination

### Acceptance criteria
- `_validation_log.md` archived per cutoff; live file < 2,000 lines
- `_archive/_validation_log_archive_YYYY-MM.md` exists with full pre-cutoff content + back-reference
- `INDEX.md` exists with routing-by-intent structure (NOT structural-by-description per ETH Zurich Finding 5)
- D62 in `03_DECISIONS.md` updated with Stage 0 read-INDEX-first reference
- All affected udm-* skill SKILL.md files updated with Stage 0 reference
- CLAUDE.md trimmed to <300 lines (or pipeline-lead-approved alternative target)
- Pattern E independent review returns ✅ CLEAN verdict; D56 second-pass clean if 🔴 found
- Pytest baseline preserved (refactor is doc-only)
- CCL token cost measurement repeated; confirms ~62% reduction (target: 362K → ~140K tokens per §16.4 Day 0)

### Risk register
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Archive script partial-write crash (F1.1) | Low | High | Two-phase-commit procedure per Phase B; rollback via git revert |
| INDEX.md written as structural-by-description (anti-pattern per ETH Zurich) | Medium | Medium | Pattern E reviewer specifically checks for this; reject if structural |
| Skill cascade misses affected SKILL.md files | Medium | Low | Plan §10b.1 G-MR3 grep enumeration; Tier 0 test per A-MR1 verifies Stage 0 in every udm-* skill |
| CLAUDE.md trim removes load-bearing content | Medium | High | Pipeline-lead reviews trim diff before commit; D56 second-pass on trim |
| Phase 1.0 lands without Phase 1.B (F9.1) | Low | High | Atomic-cohort constraint per Phase B; pre-commit reject if INDEX.md missing |

### Sign-off gate
Pattern E reviewer ✅ CLEAN + pipeline-lead approves the Phase D commit batch + CCL measurement confirms ~62% reduction.

---

## Phase E — Phase 2 (tooling + multi-agent optimization)

### Scope
Build the maintenance loop infrastructure that prevents the post-Phase-D state from rotting. Pre-commit hook keeps INDEX.md in sync with source files; Pattern F audit script extension catches stale-INDEX drift; udm-context-loader subagent reduces per-cycle context cost in multi-agent Pattern E + Pattern F cycles.

### Tasks
1. **E.1**: Author `tools/regenerate_md_indexes.py` — pure-Python script; reads source files; emits `INDEX.md` + per-file `<file>_INDEX.md`; must handle parse failures gracefully (per plan §10b.1 G-MR5: skip+warn; emit `_index_errors.md`; support `--skip-validation` flag; exit 0 on partial-failure)
2. **E.2**: Author Tier 0 + Tier 1 tests for the generator — `tests/tier0/test_regenerate_md_indexes.py` + `tests/tier1/test_regenerate_md_indexes.py` (per `udm-test-author` conventions)
3. **E.3**: Add pre-commit hook — `.pre-commit-config.yaml` entry invoking the generator with auto-add-if-changed design (NOT fail-if-stale per plan §3.6 Finding 13); benchmark runtime ≤ 2 seconds per §9 metric
4. **E.4**: Extend `tools/verify_cascade.py` Pattern F Layer 1 — add INDEX consistency check (verifies INDEX.md line ranges match source file current state); read-only check; never modifies tree
5. **E.5**: Author `udm-context-loader` subagent per plan §5.1 Phase 2.I + §15.2 Pattern D + F5.1 mitigation (PASS-THROUGH-VERBATIM Do-NOT + Pitfall #9.x rules from Phase B)

### Effort estimate
- E.1: ~2-3 hours
- E.2: ~1-2 hours
- E.3: ~30 min (config + first-run verify)
- E.4: ~1 hour (regex extension + dry-run verify)
- E.5: ~2-3 hours (skill design + verbatim-rule discipline)
- **Total**: ~7-10 hours = ~1 cycle wall-clock (per plan §7.2 estimate)

### Dependencies
- Phase D complete (INDEX.md exists; generator has source to read)
- F5.1 pass-through-verbatim mandate accepted (Phase B); required for E.5 udm-context-loader design

### Acceptance criteria
- `tools/regenerate_md_indexes.py` runs successfully on current `docs/migration/` tree; produces byte-identical INDEX.md to the Phase D hand-authored version (idempotency)
- Tier 0 + Tier 1 tests for generator pass (`uv run pytest tests/tier0/test_regenerate_md_indexes.py tests/tier1/test_regenerate_md_indexes.py`)
- Pre-commit hook installed; runtime benchmarked ≤ 2 seconds; auto-add-if-changed verified via test commit
- `tools/verify_cascade.py` Pattern F extension catches INDEX drift in test fixture
- `udm-context-loader` SKILL.md authored; verbatim-rule discipline verified via 5x repeated invocation on same input (deterministic output per plan §10b.2 EC-MR3)
- Phase 2.3 metrics: pre-commit hook never blocks commit due to stale INDEX after first 2 weeks (per §9 metric)

### Risk register
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Generator runtime exceeds 2s budget | Low | Medium | Profile + optimize; opt-out flag for emergency commits per §8 R-MR6 |
| Generator silent parse failure (G-MR5) | Medium | Medium | Skip+warn + `_index_errors.md` artifact per plan |
| udm-context-loader brief non-deterministic across runs (EC-MR3) | Medium | Medium | 5x repeated-invocation test in skill verification; canonical structure + sorted entries |
| Pre-commit hook becomes commit-friction source | Low | Low | Auto-add-if-changed minimizes; opt-out flag preserved |

### Sign-off gate
All Tier 0/1 tests pass; pre-commit hook proves stable over 2-week soak; udm-context-loader passes determinism test.

---

## Phase F — Conditional Phase 3 (file splits)

### Scope
ONLY fires if Phase A-E measured discoverability gain falls short of plan §9 success criteria — specifically, if metrics 1 OR 2 fail by >25% at the 14-day post-Phase-E mark, with Phase F decision at the 21-day mark per plan §10b.1 G-MR6.

### Tasks
1. Measure metrics at 14-day post-Phase-E mark (CCL Stage 1+2 ≤2K lines + re-read frequency ≥50% drop per §9)
2. If both metrics met → SKIP Phase F entirely
3. If either metric fails >25% → Pipeline-lead decides whether to invoke Phase F or revise expectations
4. If Phase F invoked: split candidates in priority order — `03_DECISIONS.md` (split by D-number ranges or topic) > `phase1/06_deployment.md` (split per § major) > `phase1/01_database_schema.md` (split per table)
5. Each split requires: (a) cross-reference verification script run; (b) Pattern F audit script update; (c) D-number lock for the supersession per D92 forward-only

### Effort estimate
- Metric measurement: ~30 min
- IF SKIPPED: 0 hours
- IF INVOKED: ~1-2 cycles per split (1-3 splits possible) = 1-6 cycles total

### Dependencies
- Phase E complete + 14-day soak window elapsed
- Measurement data available (per plan §9 metric collection)

### Acceptance criteria
- Either: metrics met → Phase F SKIPPED (artifact: measurement report)
- Or: Phase F INVOKED → each split lands with cross-ref verification ✅ + Pattern F audit script update ✅ + D-number supersession lock ✅

### Risk register
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Phase F triggers but cascading edit cost blows up (R-MR5) | High if invoked | High if invoked | Make Phase F conditional on metric proof; require cite-rewrite tooling as prereq |
| Metric measurement period too short to be meaningful | Medium | Medium | Per plan §10b.1 G-MR6: 14-day measure + 21-day decide; 5 invocations/week minimum |
| Pattern F regex breaks silently on split (EC-MR4) | Medium | High | Per plan §7.2 task 2.4: Pattern F regex extension MUST land BEFORE any Phase F split |

### Sign-off gate
Pipeline-lead reviews measurement data + decides skip vs invoke; if invoke, each split has its own Pattern E review.

---

## Phase G — Phase 4 (polish; conditional)

### Scope
Only after Phase A-F validated. Frontmatter (YAML headers per Option D) + tagged sections + inline anchor comments (Option T4) for fine-grained Grep targeting. `udm-find-canonical` skill is NOT in Phase G because it was elevated to Phase D.0 per plan §5.1.

### Tasks
1. Measure post-Phase-F state — are there specific files where Grep is still slow?
2. If no specific pain → SKIP Phase G entirely
3. If specific pain → frontmatter + tagged sections for those files (per plan §5.1 Phase 4)
4. Inline anchor comments (Option T4) for fine-grained Grep targeting

### Effort estimate
- IF SKIPPED: 0 hours
- IF INVOKED: ~1 cycle

### Dependencies
- Phase F decision (skip or complete) finalized

### Acceptance criteria
- Either: SKIPPED (artifact: no-pain rationale documented)
- Or: Frontmatter + tagged sections + anchor comments land + agents do not break on YAML parser dependency (per §8 R-MR7)

### Risk register
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| YAML frontmatter breaks agents lacking parser | Low | Low | Per §8 R-MR7: reversible; agents can ignore frontmatter |
| Tagged sections fragment discoverability further | Low | Low | Pattern E reviewer checks; rollback via git revert |

### Sign-off gate
Pipeline-lead reviews polish diff; Pattern E reviewer ✅ CLEAN.

---

## Phase H — Long-term governance (per plan §16)

### Scope
One-time governance authoring + recurring quarterly Q11. Establishes the durable infrastructure that keeps the markdown refactor work from rotting over the year-1 horizon per plan §16.4 (Day 0 / 30 / 90 / 180 / 365 milestones).

### Tasks
1. **H.1**: Establish Q11 quarterly cadence — author `docs/migration/audit_reports/_TEMPLATE_q11_quarterly.md` mirroring existing Q1-Q10 quarterly drill template (per plan §16.3); first Q11 run due Day 90 post-sign-off
2. **H.2**: Author `_research/_INDEX.md` register — one row per research artifact (filename + date + scope + key findings 1 line + which plan sections it backs + supersession status); append-only audit trail (per plan §16.1 Tier 1 + gap synthesis #6)
3. **H.3**: Define sign-off mechanism (P-6 polish item) — formalize what pipeline-lead actually DOES to sign off (edit §12 table row directly? approve via PR review comment? both?); document in plan §12 + applicable skills
4. **H.4**: Add multi-agent gap-audit cohort to plan §16.5 patterns (already done per §17.6 recommendation; verify text is present + complete)

### Effort estimate
- H.1: ~1 hour (template authoring + skill integration)
- H.2: ~1 hour (register authoring; ~20 existing artifacts to backfill)
- H.3: ~30 min (mechanism spec + plan §12 update)
- H.4: ~15 min (verify text + add if missing)
- **Total one-time**: ~3 hours
- **Recurring**: Q11 quarterly = ~30-60 min per quarter per plan §16.3 cost model

### Dependencies
- Phase D complete (so Q11 has a baseline to refresh against)
- Phase C complete (so sign-off mechanism reflects actual experience)

### Acceptance criteria
- `_TEMPLATE_q11_quarterly.md` exists; integrates into `udm-round-closeout` Stage 2.5 per plan §16.1 Tier 3
- `_research/_INDEX.md` exists with backfilled entries for all current research artifacts (~20 entries per `_research/` directory listing)
- Plan §12 specifies sign-off mechanism unambiguously
- §16.5 contains "Periodic gap-audit cohort (3-perspective parallel)" pattern entry per §17.6 recommendation
- First Q11 quarterly drill executed at Day 90 post-sign-off; report at `docs/migration/audit_reports/Q2026_Q3_markdown_hygiene.md`

### Risk register
| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Q11 quarterly not run (per Adversarial #7 gap) | Medium | Medium | Per plan §16.4: rotating quarterly owner; add to §16.1 governance |
| Q11 catches drift but no one fixes (per Adversarial #7) | Medium | Medium | Q11 report includes action items + assignment; tracked as B-Ns |
| Sign-off mechanism formalization is bikeshedding | Low | Low | Default: pipeline-lead edits §12 table row directly; only formalize if pain emerges |
| `_research/_INDEX.md` register grows stale | Medium | Low | Per plan §16.1: updated at every new research artifact via `udm-researcher` skill |

### Sign-off gate
H.1-H.4 land in single commit batch; first Q11 quarterly drill scheduled.

---

## Critical-path analysis

### Sequential phases (must run in order)
**A → B → C → D** are the critical-path mandatory sequence. C is the single hardest gate (pipeline-lead availability). D is the value-delivery phase.

```
Phase A (cleanup) ───┐
                     ├─► Phase C (sign-off) ──► Phase D (execute) ──► Phase E (tooling)
Phase B (mitigate) ──┘                                                       │
                                                                             ▼
                                                                  Phase F (conditional)
                                                                             │
                                                                             ▼
                                                                  Phase G (conditional)
```

### Parallelizable
- **Phase A tasks B-3 and B-5 can run in parallel** (B-3 is a script edit; B-5 is a classification table authoring; no shared files). B-4 is gated on pipeline-lead.
- **Phase B mitigations F9.1 / F1.1 / F5.1 can be authored in parallel** (mechanical edits to different plan sections).
- **Phase A + Phase B can run in parallel** (different commits; Phase B is plan-only; Phase A includes a script edit).
- **Phase D.3 + D.4 + D.5 can run in parallel** (D62 update, skill cascade, CLAUDE.md trim are independent edits).
- **Phase E.1 + E.4 can run in parallel** (regenerator and Pattern F extension are different scripts).
- **Phase H.1 / H.2 / H.3 / H.4 can run in parallel** (independent governance artifacts).

### Cannot parallelize
- **Phase D.1 + D.2 must be ATOMIC** (per F9.1 mitigation; reject if either lands without other)
- **Phase D.0 must precede D.1 + D.2** (skill scaffold + tooling required)
- **Phase D.6 must follow D.1 + D.2 + D.3 + D.4 + D.5** (Pattern E reviews the consolidated state)
- **Phase E must follow Phase D** (generator needs INDEX.md to read; tests need source to verify against)
- **Phase F triggers ONLY after Phase E + 14-day soak**

### Highest-leverage parallelization opportunities
1. **Phase A + Phase B in one commit cycle** — saves ~30 min wall-clock; both are pre-sign-off prep
2. **Phase D.3 + D.4 + D.5 as parallel subagent invocations** — saves ~2-3 hours wall-clock by running skill cascade + CLAUDE.md trim simultaneously
3. **Phase H all 4 tasks as parallel subagent invocations** — saves ~1.5 hours wall-clock

---

## Recommended next-week / next-month sequencing

### Next 1-2 sessions (next week)
1. **Session 1** (~1 hour): Phase A + Phase B in single commit cycle. Pipeline-lead decides B-4 cutoff. All 6 pre-sign-off items land.
2. **Session 2** (~1 hour pipeline-lead time): Phase C sign-off ceremony. Plan flips 🟡 → 🟢 Locked.

### Next 2-3 weeks
3. **Session 3** (~3-4 hours): Phase D.0 + D.1 + D.2 — pre-execution prep + archive cascade + INDEX.md authoring (ATOMIC COHORT per F9.1)
4. **Session 4** (~3-4 hours): Phase D.3 + D.4 + D.5 as parallel agent cohort — D62 update + skill cascade + CLAUDE.md trim
5. **Session 5** (~30-60 min): Phase D.6 Pattern E independent review + D56 second-pass if needed

### Next month
6. **Session 6** (~7-10 hours): Phase E — full tooling buildout (regenerator + Tier 0/1 + pre-commit + Pattern F extension + udm-context-loader)
7. **Session 7** (~3 hours): Phase H.1-H.4 governance authoring

### Day 30 mark
8. CCL measurement: confirm ~62% reduction target met per §16.4 Day 30
9. Pre-commit hook 2-week soak begins

### Day 90 mark (first Q11)
10. First Q11 quarterly drill executes; Phase F skip-vs-invoke decision based on 14-day metrics

---

## Confidence rating

🟢 **High** for Phases A-D scope + effort estimates (anchored to plan §7.1 + gap synthesis + ccl-baseline). 🟡 **Medium** for Phase E-H estimates (more discretionary; depends on adoption rate). ⚪ **Conditional** for Phases F + G (only fire if metrics fall short).

The phased breakdown is a planning aid; pipeline-lead may revise sequencing at Phase C sign-off.
