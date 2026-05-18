---
name: udm-gap-check
description: Runs an independent gap analysis IMMEDIATELY after substantive build / enhancement / multi-artifact discipline work to catch cross-tracker drift, Pitfall #9 sub-class instances, convention registration gaps, and untracked B-N opportunities BEFORE the work is declared 🟢 complete. Mandatory for every agent / sub-agent / multi-agent team after build closure. Distinct from udm-checks-and-balances (per-artifact validation) and udm-round-closeout (round-aggregate cadence) — this skill is the per-completion independent gap audit that fills the gap between artifact validation (covers a single artifact) and round close-out (covers multiple artifacts but only at end of round).
---

# UDM Gap Check

Per-completion meta-skill that runs IMMEDIATELY after substantive work finishes — AFTER `udm-progress-logger` has logged the completion, BEFORE the work is claimed 🟢 complete. Spawns an independent reviewer (per D55+D56 producer ≠ reviewer discipline) to catch drift the producer self-check missed.

## Why this skill exists (the gap it closes)

Empirical evidence from the 2026-05-12 session (3 waves of build/enhancement work):

- **Wave 1** (udm-progress-logger + CODE_BUILD_STATUS + Pitfall #9.k/9.l/9.m + B02 + .gitignore): 5-gate validation by independent reviewer surfaced 5 🟡 findings (F-1 through F-5) — none caught by producer self-check; F-1 was a Pitfall #9.k arithmetic-propagation drift (line-anchor `:1937` should have been `:1938`).
- **Wave 2** (§ 3.10 build + B218 + Execution Sequence): 6-category gap analysis surfaced 7 🟡 findings — including stale test counts in CODE_BUILD_STATUS (`283` → `311` count was not propagated), 2 B-N opportunities (B219 + B220), and cross-tracker drift in 00_OVERVIEW.md / GLOSSARY.md / MAINTENANCE.md.
- **Wave 3** (§ 3.8 build + B218 retroactive + B219 empirical validation): 6-category gap analysis (this one).

In EACH wave, the user had to explicitly ASK for a gap check. Each time, the independent reviewer found 🟡 issues the producer self-check missed. The pattern is structural: producer self-check (HANDOFF §8 Steps 1-9) catches author-time drift but NOT post-completion cross-tracker drift. The gap-check skill **operationalizes the post-completion audit as a mandatory step**, not an optional user-driven follow-up.

Per user-direction 2026-05-12: "Ensure that all agents, sub-agents and multi-agent teams run a gap check after the enhancements are built out. Turn this into a requirement for them to follow or a skill or whatever gets them to run this check. A trigger perhaps."

## When to invoke

Mandatory invocation triggers (one of):

1. **Pattern B cohort completion** — after `udm-post-build-verify` returns clean (or with documented carryover) AND `udm-progress-logger` has logged the build event
2. **B-item closure landing** — after substantive work closes a B-number (especially closures that span multiple files)
3. **Multi-artifact discipline lock** — after a coherent multi-artifact authoring cycle (e.g., new skill + tracker + CLAUDE.md registration + HANDOFF update) — the discipline introduction itself needs a gap check before locking
4. **Retroactive fix-application across multiple files** — after applying a learned pattern to multiple test files / multiple modules (e.g., B215-style fix-application; B218 retroactive)
5. **Decision lock cascade** — after a D-number locks AND multiple docs get cascade updates per D93

## When NOT to invoke

- For single-doc edits (typo fixes, formatting, cosmetic-only) — those route to POLISH_QUEUE per D113
- For exploratory reads / research with no state change
- For mid-build state (skill runs at the natural completion boundary, NOT mid-iteration)
- When the only work was already-gap-checked (don't re-check the same artifacts unless changed since last check)

## Canonical Context Load (CCL) per D62

Whoever invokes this skill (the completing agent OR the main agent) MUST have completed CCL before SPAWNING the gap-check reviewer agent. The reviewer agent ITSELF must perform its own CCL (per D62 + B34 self-edit fallback if needed).

- **Stage 0 — Routing manifest** (recommended-not-mandatory; added 2026-05-15 per D62 amendment + D.2 INDEX.md per MARKDOWN_REFACTOR_PLAN.md §7.1 task 1.3): `docs/migration/INDEX.md` — read FIRST when uncertain which downstream Stage 1+2+3 docs your task actually needs. Skip when: you already know which Stage 1+2+3 docs to load (typical for recurring task patterns).
- **Stage 1 — Orientation** (mandatory, 4 reads): `NORTH_STAR.md`, `HANDOFF.md`, `CURRENT_STATE.md`, `CHECKS_AND_BALANCES.md`
- **Stage 2 — Tracker awareness** (mandatory): `BACKLOG.md`, `_validation_log.md` (last 1-2 entries — they document what producer claims; reviewer verifies), `CODE_BUILD_STATUS.md` (if code-build work in scope)
- **Stage 3 — The artifacts**: every artifact authored / modified in the scope being gap-checked
- **Stage 4 — Reference-on-demand**: `MULTI_AGENT_GUIDE.md` § Canonical Context Load + prior gap-check reports if related

## The 6-category audit (canonical)

The reviewer agent walks these 6 categories. Add/remove categories sparingly — the canonical 6 are battle-tested per the 3-wave 2026-05-12 evidence.

### Category 1 — Cross-tracker drift

Check that EVERY new artifact reference is consistent across canonical docs:
- CLAUDE.md "Validation discipline" mentions the new convention?
- HANDOFF §3 (Locked vs in-flight) / §7 (Skills) / §8 (Pitfalls) reflect new work?
- CURRENT_STATE.md "Recently completed" lists the closure?
- 00_OVERVIEW.md document-map row for any new doc?
- GLOSSARY.md entries for any new short-form identifier (B-N, D-N, R-N, P-N, Pitfall #9.x, Pattern X.y, skill name)?
- GLOSSARY.md public-surface entries for any new `tools/*.py` with ≥3 non-trivial public surfaces (per 2026-05-17 extension after empirical gap-check finding on 3 B-317 tools that had CLAUDE.md Structure rows but ZERO GLOSSARY entries; mechanical detection now in `tools/query_blindspots.py::check_9n_convention_registration` per 9n GLOSSARY-parity extension)?
- MAINTENANCE.md grooming cadence for new trackers?
- POLISH_QUEUE.md skim if cosmetic-class drift surfaced?

### Category 2 — Untracked dependencies / blockers

For each completion claim, verify:
- "Depends on" edges are accurate (e.g., Tool X depends on Migration Y — verify Y exists + has correct schema)
- Effort estimates on remaining work are credible
- Blockers explicitly named (sysadmin / DBA / engineer coordination required → flagged)

### Category 3 — Pitfall #9 sub-class instances in the work

Walk 9.a-9.m against the new artifacts:
- **9.a column-name drift**: did producer cite canonical columns correctly?
- **9.b parameter-name drift**: any invented SP / function parameters?
- **9.c enum-value drift**: invented or stale enum values?
- **9.d type-width drift**: correct types but wrong widths (e.g., NVARCHAR(50) vs canonical (20))?
- **9.e Unicode-vs-ASCII**: NVARCHAR/VARCHAR swap?
- **9.f cross-table column lift**: column from table A applied to table B where it doesn't exist?
- **9.g Python `*,` keyword-only marker drift**?
- **9.h wrong section number with invented description**?
- **9.i process-discipline-claim drift**: any false-closure / B-range proxy / silent-omission / invented forward-reference?
- **9.j status-render**: leading badges match inline annotations?
- **9.k arithmetic-propagation**: count / row-index updated everywhere it's mirrored?
- **9.l canonical-schema-detail working-memory drift**: did producer re-read canonical DDL before authoring?
- **9.m discipline-not-applied-to-its-own**: does the new discipline / tracker / skill satisfy its own rules?

### Category 4 — Convention registration gaps

Did any new convention land WITHOUT registration in canonical convention-aware docs?
- New skill → registered in HANDOFF §7 + CLAUDE.md / SKILLS_PLAN.md?
- New Pitfall sub-class → registered in HANDOFF §8 + CLAUDE.md summary block?
- New D-number → registered in 03_DECISIONS.md + NORTH_STAR.md decisions list + GLOSSARY?
- New tracker → registered in 00_OVERVIEW.md doc-map + CLAUDE.md + MAINTENANCE.md?
- New Pattern label / discipline → registered in HANDOFF / CLAUDE.md / cycle-cadence-optimizer skill?
- New `tools/*.py` with ≥3 non-trivial public surfaces → BOTH CLAUDE.md Structure section AND GLOSSARY.md public-surface entries? (Per 2026-05-17 extension after B-317 tools landed with CLAUDE.md rows but missing GLOSSARY entries; mechanical detection at commit-msg hook per `check_9n` GLOSSARY parity extension)
- New optional kwarg on a function with multiple ENFORCEMENT callers (e.g., `has_cascade_evidence(commit_msg, classification=None)`) → did ALL enforcement-pathway callers update to pass the new kwarg? Add an entry to `tools/required_kwargs_registry.py::REQUIRED_KWARGS` mapping the function name to its required kwarg list (per B-326 closure 2026-05-17); the parametrized Tier 1 test at `tests/tier1/test_required_kwargs_registry.py::test_parametrized_registry_function_callers_clean` then mechanically verifies all callers compliant. (Original empirical instance: `audit_cascade_compliance` initially missed passing `classification=` to `has_cascade_evidence`, silently bypassing the substrate-stricter B-321 check in retroactive scans; the registry generalizes this pattern so new function entries get automatic coverage.)

### Category 5 — Untracked B-N opportunities

Did the work surface new work items that should be B-tracked?
- Carryover work explicitly named in commit / annotation but not B-numbered
- Patterns observed twice (per HANDOFF §8 9.j 2-event formalization precedent) deserving Pitfall sub-class candidates
- Empirical findings deserving formal capture (e.g., B219 from B215 + B218 pattern observation)

### Category 6 — Just-noticed issues

Free-form catchall for drift the reviewer happens to notice while reading. Common findings:
- Stale dates in self-references
- Test count drift (suite said `283` but actual is `311`)
- Inconsistencies between leading badges and inline annotations (Pitfall #9.j catchall)
- Orphaned cross-references (cite [doc that doesn't exist])

## Procedure — invocation pattern

```
1. Producer (agent/team/main agent) completes substantive work.
2. Producer invokes udm-progress-logger to update trackers (BACKLOG / _validation_log / CODE_BUILD_STATUS).
3. udm-progress-logger's "Next-natural-action" line MUST recommend udm-gap-check invocation.
4. Producer (or main agent) invokes udm-gap-check.
5. udm-gap-check spawns INDEPENDENT reviewer agent (NOT the producer; per D55+D56).
6. Reviewer performs CCL + walks the 6 categories.
7. Reviewer returns structured report (🔴/🟡/✅ verdict per category + summary).
8. If 🔴: BLOCK 🟢 status claim until fixed (mandatory second-pass per D56).
9. If 🟡: fix inline if small + B-tracked enough to defer if needed.
10. If ✅ CLEAN: 🟢 status claim authorized.
```

## Output contract

Reviewer agent returns ~300-500 word report:

```markdown
# GAP ANALYSIS — <DATE> <SCOPE>

## Category-by-category findings
### Category 1 — Cross-tracker drift
[per finding: doc / what's stale / proposed fix; if no findings: ✅]
### Category 2 — Untracked dependencies / blockers
[same]
### Category 3 — Pitfall #9 sub-class instances
[per sub-class: ✅ / N instances + cite]
### Category 4 — Convention registration gaps
[same]
### Category 5 — Untracked B-N opportunities
[same]
### Category 6 — Just-noticed issues
[free-form]

## 🔴 / 🟡 Summary
- 🔴 (must fix): N
- 🟡 (should fix; inline OR B-N): N
- P-N candidates (cosmetic): N

## Overall verdict: ✅ NO GAPS / 🟡 MINOR GAPS / 🔴 SUBSTANTIVE GAPS
```

## Hard rules

1. **No 🟢 status claim WITHOUT a gap-check `_validation_log.md` entry.** This is the canonical hard rule operationalizing user-direction 2026-05-12. Builds may complete + tests may pass, but until gap-check returns ≤🟡 verdict, the build is 🟡 In progress, not 🟢 Built.
2. **Independent reviewer — never producer self-checks the gap.** Per D55+D56. The producer's own self-check (HANDOFF §8 Steps 1-9) is necessary but NOT sufficient.
3. **6-category audit is canonical.** Reviewer walks all 6. Categories may be partial-scope-skipped if obviously N/A (e.g., Category 1 has no canonical convention-aware docs to check for pure-code work), but the agent MUST state "N/A" explicitly, not silently skip.
4. **🔴 verdict blocks 🟢.** No exceptions. If 🔴 found, fix + mandatory second-pass per D56 before retry.
5. **🟡 findings get inline-fix OR B-N opening.** No silent deferral. Every 🟡 must have a closure path documented.
6. **One gap-check invocation per completion event.** Not per artifact (that's udm-checks-and-balances). Not per round (that's udm-round-closeout). PER completion.
7. **Reviewer agent's CCL is hard-required.** First content-substantive tool call MUST hit a Stage 1 doc. If reviewer skips CCL, report is invalid — re-spawn.

## Anti-patterns

- ❌ "I'll gap-check at round close-out" — defeats the skill's purpose
- ❌ Producer self-checking the gap (violates Hard Rule 2)
- ❌ Spawning a gap-check reviewer with the SAME agent type as the producer (use general-purpose for doc/tracker work; udm-design-reviewer for code/schema)
- ❌ Accepting a reviewer report that doesn't walk all 6 categories (categories aren't optional — partial coverage is invalid)
- ❌ Re-running gap-check on artifacts that haven't changed since last check (waste; rate-limit per artifact-version)
- ❌ Skipping gap-check because "the build was small" (small builds can have big drift; the discipline scales)

## Integration with existing skills

- **`udm-checks-and-balances`** — runs BEFORE the build (per-artifact validation); not a substitute for udm-gap-check
- **`udm-post-build-verify`** — runs BEFORE this skill (tests pass; this skill then audits the broader gap surface)
- **`udm-progress-logger`** — runs IMMEDIATELY BEFORE this skill (logs the completion; this skill then audits for missed items)
- **`udm-execution-classifier`** — runs IN PARALLEL with progress-logger for tool/migration builds; gap-check verifies the classifier routing landed correctly
- **`udm-round-closeout`** — runs AT END OF ROUND, aggregating gap-check outputs across multiple builds; this skill populates that aggregate
- **`udm-design-reviewer` agent** — appropriate reviewer-agent type for code/schema gap checks; `general-purpose` is appropriate for doc/tracker/skill gap checks

## CCL self-check fallback (per D62 + B34)

If the reviewer agent realizes mid-procedure that CCL wasn't performed and re-loading would blow context budget:
1. AT MINIMUM read `HANDOFF.md` §3 + `BACKLOG.md` + every artifact being gap-checked
2. Note in the report: "CCL self-edit fallback applied per D62 + B34 — Stage 1 partial"
3. Report is still valid; discipline preserved; audit trail captures the shortcut

Full CCL is preferred; the self-edit fallback exists for narrow-context reviewers.

## Example invocation

After § 3.8 enforce_retention build + B218 retroactive fixes (2026-05-12):

```
INVOKE udm-gap-check
  scope: § 3.8 build artifacts (tools/enforce_retention.py + tests + _exceptions.py extensions)
         + B218 retroactive fixes (tools/log_retention_cleanup.py audit_event_id; tests/tier1 bound-param inspection)
         + tracker updates (CODE_BUILD_STATUS Round 4 count 1/11 → 2/11; BACKLOG B218 leading badge)
  reviewer-agent-type: general-purpose (doc/tracker mix; not pure code)
  scope-bound: this session's third wave; NOT first or second wave (already gap-checked)

OUTPUT:
[reviewer's 500-word structured report]

[Producer reviews:]
- If 🔴: fix + second-pass + re-invoke
- If 🟡: inline-fix small items + open B-N for big items
- If ✅: 🟢 status claim authorized; close session
```

## Where this skill lives in the broader discipline

| Cadence | Skill | Trigger |
|---|---|---|
| Per-artifact validation | `udm-checks-and-balances` | New artifact authored / locked |
| Per-build test verify | `udm-post-build-verify` | Pattern B cycle completes |
| Per-build classification | `udm-execution-classifier` | Tool / migration authored |
| Per-completion tracker | `udm-progress-logger` | ANY substantive work finishes |
| **Per-completion gap audit** | **`udm-gap-check`** (this skill) | **ANY substantive work finishes — AFTER progress-logger; BEFORE 🟢 claim** |
| Per-decision | `udm-decision-recorder` | D-number lock candidate |
| Per-round | `udm-round-closeout` | End of Phase round |

This skill fills the gap between per-completion tracker update (which records progress) and per-round aggregate audit (which catches drift only at round end) — the moment-of-completion independent gap audit.

---

Owner: pipeline lead (skill definition); every agent / sub-agent / multi-agent team that completes substantive work (skill invoker per Hard Rule 1).

Authored 2026-05-12 per user-direction "Ensure that all agents, sub-agents and multi-agent teams run a gap check after the enhancements are built out. Turn this into a requirement for them to follow or a skill or whatever gets them to run this check. A trigger perhaps."

Empirical evidence base: 3-wave 2026-05-12 session (each wave had a user-driven gap check that found 🟡 issues producer self-check missed; F-1 line-anchor / B219 + B220 surface / stale test counts; each wave validates the skill's hypothesis that producer self-check is necessary but insufficient at post-completion timescale).
