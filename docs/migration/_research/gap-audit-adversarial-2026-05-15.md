# Adversarial gap audit — MARKDOWN_REFACTOR_PLAN.md

**Date**: 2026-05-15
**Scope**: `docs/migration/MARKDOWN_REFACTOR_PLAN.md` (~997 lines, 4th revision) + `NEW_REPO_STARTER_TEMPLATE.md` + 3 P0 research artifacts (em-dash-slug-test / ccl-baseline / cross-reference-maintenance-agent)
**Perspective**: Red-team reviewer — finding ways this plan can FAIL through edge cases, race conditions, silent corruptions, and partial-completion failure modes. Adopting the assumption that what CAN go wrong WILL go wrong.
**Method**: Walk all 10 audit dimensions from the brief; produce per-dimension failure scenarios with severity; conclude with top-5 most-likely failures + mitigations.

**Severity legend**: 🔴 CRITICAL (data loss / unrecoverable / silent corruption) / 🟡 SERIOUS (recoverable but costly) / ⚪ MINOR (annoying)

---

## §1. Phase 1.0 archive cascade silent corruption (🔴 ≈ HIGH risk)

The promoted Phase 1.0 task — trim `_validation_log.md` 7,519 → 2,000 lines via archive — is the highest-leverage SINGLE action AND the highest-blast-radius single action. Failures land directly on the project's audit-trail-of-record.

- **F1.1 🔴 CRITICAL — partial-write crash**: archive script begins copying entries to `_validation_log_archive_2026-04.md`, fsync-fails mid-write, then the truncate step on the live file proceeds; result = entries vanish from live file but archive is partial. Append-only invariant violated; D55 audit trail has a hole. **No atomic-rename or two-phase-commit pattern is specified in §7.1 task 1.2 or §16.1 hygiene rule 6.** Plan §13.1 says "Time-based correct for append-only logs" but never mandates atomic mv-after-fsync.
- **F1.2 🔴 CRITICAL — straddling entries**: the policy cutoff is "30 days" but entries are not aligned to day boundaries. A multi-day cohort event-row (e.g., Pattern E R8 spanning 2026-04-09 → 2026-04-14) might be split — the "produce" row archived, the "validate" + "sign-off" rows kept live — turning a single audit event into two orphaned half-events. Plan never specifies how to handle entries that share a `BatchId`-like grouping.
- **F1.3 🟡 SERIOUS — cross-reference straddling**: entries reference each other ("see entry above on 2026-04-01" or "supersedes the 2026-04-09 Pattern E close"). After archive, the "above" entry lives in a different file. Plan §13.3 mandates explicit-link rewriting for FILE splits but does NOT mention back-reference rewriting WITHIN `_validation_log` archive cuts.
- **F1.4 🟡 SERIOUS — mid-write append race**: archive runs while parent-agent appends a new entry (the round-closeout cascade itself is writing). Concurrent fcntl/flock locking not specified; on Windows dev workstation there's no flock at all. The append could land in the wrong file or get lost.
- **F1.5 🟡 SERIOUS — re-archive on Tier 1 → Tier 0 boundary**: §16.1 hygiene rule 6 says "archive at 5,000 lines OR quarterly"; §16.4 Day 90 audit re-archives. The two cadences can fire on the same file in the same week, producing `_validation_log_archive_2026-04.md` AND `_validation_log_archive_2026-Q1.md` with overlapping content. Idempotency-of-archive not specified.

---

## §2. INDEX.md regeneration race conditions (🟡)

- **F2.1 🟡 SERIOUS — three-way merge race**: agent commits doc edit A → pre-commit hook regenerates INDEX.md against state with A applied → human commits unrelated doc edit B → hook regenerates against state with B applied (not A+B). Result: INDEX.md alternates with each commit, never representing both. Plan §5.1 Phase 2.G acknowledges "auto-add-if-changed" design but says nothing about merge-driver behavior on overlapping INDEX.md edits → guaranteed conflicts on every concurrent PR.
- **F2.2 🟡 SERIOUS — hook-modifies-tree-mid-cycle invisible to agent**: research §3.6 Finding 13 explicitly warns this. Plan acknowledges it (§5.1 Phase 2.G), but the proposed mitigation ("succeeds silently") makes the problem WORSE for agents — the agent's next Read of INDEX.md will see content the agent did not author and didn't see at commit time. Pattern F audit then trusts the regenerated INDEX over the canonical files (it's "newer").
- **F2.3 ⚪ MINOR — pre-commit hook loop**: hook regenerates INDEX → adds to commit → triggers another pre-commit cycle (git hooks technically don't, but `commit -a` semantics + some IDE integrations do). Not catastrophic; just developer-friction.

---

## §3. Heading-slug migration edge cases (🟡)

- **F3.1 🟡 SERIOUS — historical GREP search fails**: the em-dash-slug-test research artifact explicitly states "forward-only per D92; existing em-dash headings stay". An operator searching `_validation_log_archive_2026-04.md` for the OLD slug `d15-—-idempotency-ledger` (because the historical entry cites the literal old anchor) will get a hit; following the citation to the LIVE file finds a colon-form heading that doesn't match. Cross-file fragment validation tools (lychee) WILL flag this as a broken link — but it isn't actually broken, it just navigates to the historically-correct heading whose slug has been renormalized.
- **F3.2 🟡 SERIOUS — external URL citations break silently**: git commit messages, GitHub Issues, Slack messages, prior research artifacts (e.g., `agent-discoverability-2026-05-15.md`) may cite anchors via URL `github.com/...#d15-—-idempotency-ledger`. When the heading is renamed colon-form, the URL 404s. No 301-redirect mechanism for Markdown headings exists; plan §15.2 Pattern (e) acknowledges this concept but provides no mechanism.
- **F3.3 ⚪ MINOR — heading renamed AS PART OF migration**: if rename touches the title text AND the separator, neither old-slug nor new-slug resolves anywhere. Mitigation requires a redirect/anchor stub at the old slug — plan has no such mechanism.
- **F3.4 🔴 CRITICAL — Pattern F regex calibration**: `tools/verify_cascade.py` regex patterns (per §2.2 non-goal #2) are calibrated against em-dash heading style. Mass colon-form heading authoring in NEW content while regex still expects em-dash means Trigger D forward-cite resolution silently fails to validate new content. Plan §7.2 task 2.4 mentions extending verify_cascade but doesn't specify the regex update is REQUIRED BEFORE colon-form headings land.

---

## §4. udm-find-canonical skill failure modes (🟡)

- **F4.1 🟡 SERIOUS — stale routing-table.md drift**: the skill body is under 500 lines (Anthropic cap) and points at `routing-table.md`. If routing-table.md isn't pinned to a regenerator + pre-commit hook with the SAME discipline as INDEX.md, it goes stale. Plan §5.1 Phase 1.E doesn't specify a regenerator for the routing-table; Phase 2.F only mentions `tools/regenerate_md_indexes.py` for INDEX files, not routing-table.
- **F4.2 🟡 SERIOUS — case + Unicode normalization mismatch**: `D15` vs `d15` vs `D15` (NFKC normalized) — does the skill accept all variants? What about a citation `[D-15]` (with hyphen) vs `[D15]`? Plan doesn't specify the skill's input-canonicalization contract.
- **F4.3 🟡 SERIOUS — multiple-candidate ambiguity**: D15 is cited in `03_DECISIONS.md` (canonical), `HANDOFF.md` (narrative), `phase1/01_database_schema.md` (cross-cut), `_validation_log.md` (audit trail). Which does the skill return? "Canonical home" assumes D-numbers always have one. They don't always — SP-N has BOTH spec doc AND implementation file as canonical homes for different concerns.
- **F4.4 ⚪ MINOR — token budget regression**: the skill SAVES context only if the agent uses it. If an agent invokes the skill THEN also greps + reads the cited file (defensive doubt), net context cost is HIGHER than skipping the skill. No plan mechanism enforces "trust the skill output."

---

## §5. udm-context-loader subagent failure modes (🟡 → 🔴)

- **F5.1 🔴 CRITICAL — brief omits critical context**: subagent reads 12K-16K lines in isolated context, distills to ~500-1K line brief, returns to parent. Anything the distillation drops is INVISIBLE to downstream agents — they cannot ask "did the brief omit X?" because they don't have the full text. A missed Pitfall #9 sub-class or missed do-NOT rule can land destruction-class production changes.
- **F5.2 🟡 SERIOUS — non-deterministic briefs**: run twice on same input → different briefs (model temperature, prompt-cache state, context-shuffling). Pattern E 5-agent cycles depending on the brief diverge on which agent saw which framing of the same CCL. Reproducibility violated. Plan §10b.2 EC-MR3 acknowledges this in the gap section but the mitigation ("test with 5x repeated invocation") doesn't address how to handle non-deterministic results IN PRODUCTION — just how to MEASURE them.
- **F5.3 🔴 CRITICAL — silent subagent OOM**: large CCL read exceeds subagent context window (research §3.6 mentioned 12K-16K lines for CCL; with `_validation_log.md` at 231K tokens UNTIL Phase 1.0 archive lands, a single subagent CCL read OOMs the subagent's 200K window). Subagent returns truncated brief OR empty brief OR errors out. Parent agent may not surface the failure → downstream agents proceed with hollow context.
- **F5.4 🔴 CRITICAL — composition contract gap**: parent passes brief to downstream agents. If brief format isn't versioned + schema-validated, the brief format can change between cycles and break downstream consumers silently. No schema-versioning specified.

---

## §6. 6-rule hygiene enforcement edge cases (🟡)

- **F6.1 🟡 SERIOUS — legitimate exception case**: a heading in a user-facing report needs em-dash for typography (e.g., a runbook table title `## Round 5: Test cohort — empirical findings`). Hygiene rule blocks the commit. No exception process specified. Workaround = disable hook = enforcement decays.
- **F6.2 🟡 SERIOUS — lead-with-answer regex check is wrong-shape detection**: hygiene rule "1-3 sentence direct answer" via regex is unreliable. False positives (well-written intros that don't match the regex) + false negatives (3-sentence rambling intros that pass regex but aren't direct answers). The regex check creates illusion of enforcement.
- **F6.3 🔴 CRITICAL — lychee finds 1000 broken links during refactor**: legitimate refactor activity produces many transient broken links. CI goes red. Operator must investigate each (or ignores them all). After ignoring once, the broken-link detection becomes noise → real breakage missed. Plan §16.1 mandates lychee weekly cron but doesn't specify the failure-mode response procedure.
- **F6.4 ⚪ MINOR — file >2000-line auto-flag noise**: when `_validation_log.md` regrows past 2K (it will, eventually), the auto-flag fires every commit until archive runs. Operator dismisses; archive doesn't run; flag becomes background noise.

---

## §7. Quarterly Q11 audit failure modes (🟡)

- **F7.1 🟡 SERIOUS — audit not scheduled**: Q11 is just a documentation entry. Unlike Q1-Q10 which are wired into existing Tier 5 quarterly drill register (per `06_TESTING.md`), Q11 is new. Plan §16.3 says "mirrors existing Q1-Q10 quarterly cadence" but doesn't specify HOW Q11 gets onto the calendar. No cron / Automic / GitHub Action. Silently drops off backlog.
- **F7.2 🟡 SERIOUS — audit becomes ritual checkbox**: operator runs Q11, sees drift, writes "needs investigation," nobody investigates. No accountability mechanism. The audit reports get filed in `audit_reports/QYYYY_QN_markdown_hygiene.md` but those reports themselves are never audited.
- **F7.3 ⚪ MINOR — late-quarter standards invalidation**: Anthropic ships breaking change to skills mechanism 30 days before Q11; Q11 audit fires 60 days late; recommendations are now based on already-superseded standards. Wasted cycle.

---

## §8. External-platform breaking changes (🟡)

- **F8.1 🟡 SERIOUS — Anthropic skills mechanism breaking change**: udm-find-canonical depends on Anthropic's current skill loading mechanism. A breaking change (rename of `routing-table.md` convention, change to skill-body byte cap, change in how SKILL.md frontmatter is parsed) silently invalidates the skill. Plan provides no version-pin or migration runbook.
- **F8.2 ⚪ MINOR — GitHub slug algorithm change**: low probability but historically documented (GitHub has changed slug algo before). `tools/test_github_slug.py` is the canary, but it's only run quarterly per §16.3. A change between quarters means up to 90 days of broken anchors before detection.
- **F8.3 🟡 SERIOUS — Anthropic context-window scaling**: Anthropic ships 500K-context model. Plan's entire CCL token budget math (Stage 1+2 = 181% of 200K) becomes irrelevant. Phase 1.0 archive cascade still useful but the urgency justification evaporates. Worse: operator de-prioritizes archive cascade because "we have headroom now" → audit trail still bloats unbounded → eventually hits 500K too.

---

## §9. Migration partial-completion (🔴)

- **F9.1 🔴 CRITICAL — Phase 1.0 runs, Phase 1.B abandoned**: operator executes the archive (Phase 1.0) — easy win — then loses momentum / gets pulled to other work. INDEX.md (Phase 1.B) never lands. Now `_validation_log.md` is trimmed AND there's no master cross-ref manifest AND the routing-by-intent discipline isn't in place. Repo is in WORSE state than before because audit-trail navigation is now also harder (need to know which archive file holds which entry).
- **F9.2 🔴 CRITICAL — Phase 1 succeeds, Phase 2 tooling never lands**: INDEX.md is authored manually; no regenerator (Phase 2.F) is ever built; INDEX goes stale over weeks; agents see stale routing → form wrong mental model → revert to grep → the entire Phase 1 investment becomes dead weight. Plan provides no mechanism to detect "Phase 2 abandoned" and revert Phase 1.
- **F9.3 🟡 SERIOUS — Phase 3 fires partial**: 03_DECISIONS.md splits into 3 files; cross-references partially rewritten; Pattern F regex partially updated; some inbound citations broken; lychee silent because hook isn't wired yet. Plan's §13.3 mandates "binding precondition" for cross-ref preservation BEFORE split, but no enforcement mechanism prevents the operator from doing the split before the script is built.

---

## §10. Self-referential failures (🟡)

- **F10.1 🟡 SERIOUS — plan itself violates colon-form rule**: §13.4 mandates colon-form; the plan still has em-dash headings throughout (e.g., `## §13. Option A deep-dive — naming + TOC + discoverability (added 2026-05-15)`). Forward-only is documented but the plan-as-artifact still uses em-dash in the body, so anyone reading the plan to learn the rule sees a counter-example.
- **F10.2 🟡 SERIOUS — plan lacks lead-with-answer**: §16.1's hygiene table says "lead-with-answer discipline" but the plan opens with a 250-word **Status** block before getting to "what does this plan do?" — a textbook anti-pattern per its own rule.
- **F10.3 🟡 SERIOUS — plan exceeds its own SKILL.md cap**: §13 preamble notes the plan is approaching 500-line SKILL.md cap; §15 acknowledges "Plan now exceeds 700 lines per the §13 preamble's own split trigger." Plan is now ~997 lines. It violates its own §13.1 KEEP-vs-SPLIT rule and self-acknowledges it (Pitfall #9.m discipline-not-applied-to-tracker). Self-aware but not self-correcting.
- **F10.4 ⚪ MINOR — NEW_REPO_STARTER_TEMPLATE.md uses ASCII hyphen "em-dash-feeling" character `—` in body text** (e.g., "agents do not browse like humans") — visually inconsistent with the colon-form heading rule it preaches, though this is body text not heading text. Minor.
- **F10.5 🟡 SERIOUS — template demonstrates principles imperfectly**: NEW_REPO_STARTER_TEMPLATE.md skeleton CLAUDE.md (§4) doesn't actually demonstrate "lead-with-answer" — it opens with "{Project Name}" + project description, not a direct-answer status block. A new project copying this template will inherit the anti-pattern.

---

## §11. Top-5 most-likely failure modes + mitigations

Ranked by `likelihood × impact`:

| # | Failure | Severity | Likelihood | Mitigation |
|---|---|---|---|---|
| **1** | **F9.1 Phase 1.0 archive runs, INDEX.md never lands** — operator gets quick win on archive, loses momentum on remaining Phase 1; repo ends WORSE than before because audit-trail navigation now needs cross-file awareness | 🔴 CRITICAL | HIGH (this is the canonical "ship MVP, never ship V1" failure pattern) | Make Phase 1.0 + Phase 1.B atomic — bundle in single round / single cycle; do NOT allow archive to land without INDEX.md committed in same cohort. Add §7.1 task 1.0+1.3 as paired-deliverable; reject if either lands without the other. |
| **2** | **F1.1 archive partial-write crash** — script crashes mid-write; live file truncated but archive partial; append-only invariant violated; D55 audit trail has hole | 🔴 CRITICAL | MEDIUM (Windows dev workstation, no flock; pipeline interrupted by power loss / Ctrl-C is the trigger) | Two-phase commit: (a) write archive to `_validation_log_archive_2026-04.md.tmp`; (b) fsync; (c) verify line count matches expectation; (d) ONLY THEN rename tmp → final + truncate live. Add Tier 0 test that simulates crash between phases (a) and (d) and verifies live file is untouched. |
| **3** | **F5.1 udm-context-loader brief silently omits critical context** — subagent distillation drops a Pitfall #9 sub-class or do-NOT rule; downstream agents land destruction-class production changes | 🔴 CRITICAL | MEDIUM (non-deterministic LLM distillation is the canonical "summary lies" failure pattern) | Subagent brief MUST include explicit "raw-read cross-ref" list — every Do-NOT rule + Pitfall #9 sub-class header is PASSED THROUGH VERBATIM (not summarized). Downstream agents that touch production code must direct-Read those passages, not trust the summary. Add to brief schema as mandatory `verbatim_excerpts` field. |
| **4** | **F3.4 Pattern F regex calibration drift** — verify_cascade.py regex expects em-dash headings; colon-form NEW headings land; Trigger D silently passes when it should fail; bad citations slip through audit | 🔴 CRITICAL | MEDIUM-HIGH (regex update is a small line-change task; it will be missed because nothing forces sequencing) | Bundle regex update with §13.4 colon-form mandate — Phase 1.6 sub-task = "verify_cascade.py regex covers BOTH em-dash and colon-form heading patterns; add Tier 0 test fixture with one of each; merge regex update BEFORE merging colon-form mandate." |
| **5** | **F2.1+F2.2 INDEX regen race conditions** — concurrent commits + hook-modifies-tree make INDEX.md non-deterministic; Pattern F trusts INDEX over canonical files; silent drift accumulates | 🟡 SERIOUS | HIGH (this is the standard pre-commit-hook-modifies-tree anti-pattern; well-documented in research §3.6 Finding 13 but mitigation in plan is incomplete) | Pick ONE of two options + commit: (a) move INDEX regeneration to `udm-round-closeout` (human-triggered, no race); OR (b) keep pre-commit hook but with custom git merge-driver registered for `INDEX.md` that always re-generates on merge instead of doing 3-way text merge. Plan currently says "both options preserved; pipeline-lead picks at execution time" — that's the worst answer; deferring the decision delays the failure mode emerging until production. |

---

## Recommendations beyond top-5

- **R1**: Add §17 "Failure-mode runbook" covering F1.1 (archive crash) + F5.1 (brief omits context) + F9.1 (partial migration) as RB-N candidates with explicit pre-flight + rollback procedures.
- **R2**: Make the plan eat its own dog food — colon-form ALL headings in the plan itself in same commit that locks the colon-form rule. Self-referential failures (F10.1-F10.3) erode credibility.
- **R3**: Specify schema-versioning for `udm-context-loader` brief output (avoids F5.4 silent drift).
- **R4**: Add an explicit "Phase 1 must land as atomic cohort" gate (§7.1 prefatory line) — addresses F9.1 directly.
- **R5**: Codify F8.3 (Anthropic context-window scaling) as a triggered re-plan event in §16.3 OFF-CADENCE trigger list — current list doesn't include "underlying context budget changed by ≥2x."

---

## Confidence assessment

🟢 High on §1, §3, §6, §9, §10 — failure modes are concrete and grounded in plan text. 🟡 Medium on §2, §4, §5 — failure modes are real but depend on implementation specifics not yet authored. 🟡 Medium on §7, §8 — these are slow-moving structural risks where my estimates of likelihood are inherently uncertain.

The plan is THOROUGH in its research grounding but UNDER-SPECIFIED in failure-mode handling at the script + sequencing layer. The top-5 above are first-order fixes; the broader pattern is that the plan treats "happy path" as primary and "what if it crashes" as out-of-scope (§2.2 implicitly excludes recovery scenarios). Adding §17 failure-mode runbook would close most of the 🔴 gaps.
