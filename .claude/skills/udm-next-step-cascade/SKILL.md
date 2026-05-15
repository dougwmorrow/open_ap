---
name: udm-next-step-cascade
description: User-triggered 2-step cascade for the "proceed with recommended next step + gap-check after" workflow. ONLY fires when the user explicitly says trigger phrases like "Proceed with next steps", "Proceed with your suggested next steps", "Move forward", "Continue with next steps", or similar imperative phrasing. NEVER fires as a default behavior between turns. NEVER fires when the user asks questions, clarifies, requests a specific action, or invokes a different workflow. When in doubt, ASK the user rather than invoking. Per user-direction 2026-05-14 — closes the "agent always proceeds with next steps autopilot" anti-pattern.
---

# UDM Next-Step Cascade

User-invocable 2-step cascade that operationalizes the standing instruction: "1. Proceed with your recommended next steps. 2. Check for any gaps to ensure that nothing is missed."

## CRITICAL — when to invoke

This skill ONLY fires when the user's MOST RECENT message contains an explicit trigger phrase. **NEVER invoke as a default behavior** between turns. The user-direction 2026-05-14 that authorized this skill ("We shouldn't always proceed with next steps") explicitly rejects the auto-proceed pattern.

### Trigger phrases (case-insensitive; user's message must contain ONE)

- "Proceed with next steps"
- "Proceed with your next steps"
- "Proceed with your suggested next steps"
- "Proceed with your recommended next steps"
- "Proceed with the next steps"
- "Proceed with the recommended"
- "Proceed forward"
- "Move forward"
- "Move on to next steps"
- "Continue with next steps"
- "Continue forward"
- "Run a gap check after" (when paired with a forward-work directive)
- "And gap-check" / "+ gap-check" (as a tail on a forward-work directive)
- Imperative variants that combine forward-motion + gap-check semantics

### Anti-triggers (do NOT invoke even if a trigger-like phrase appears)

- User asking a clarifying question ("Can you tell me about X?")
- User pointing out an issue ("I see an error in...")
- User requesting a SPECIFIC action ("Update file X to do Y") — execute directly; don't invoke this cascade
- User asking about progress ("What did we accomplish?")
- User invoking a different workflow standalone ("Run a gap check on Y" → invokes `udm-gap-check` alone, not this cascade)
- User saying "stop" / "pause" / "wait"
- User redirecting scope ("Let's move to Phase 2 instead" → execute the redirect, don't invoke the cascade)
- Implicit continuation in a multi-message exchange where the user is mid-thought (wait for explicit trigger)

When in doubt: **ASK the user to clarify** rather than invoking. Cost of asking < cost of unauthorized forward motion.

## 2-step procedure

### Step 1 — Execute the recommended next step

1. **Identify the recommended next step** from the PRIOR assistant turn:
   - Look for explicit "Recommended next step" / "What's next" / "Runway" / "Suggested next" section
   - Pick the HIGHEST priority item per the priority labels (HIGH > MEDIUM > LOW)
   - If multiple items at same priority, pick the one with smallest scope
   - If NO recommended next step exists in prior turn, ASK the user what they want
2. **Execute the work** (build / fix / authoring / scaffold / etc.)
3. **Verify pytest** if code changed; update test count tracking if test changes landed
   - **3.1 — Parallel-agent re-verification (B-268 closure 2026-05-14)**: If Step 1.2 spawned MULTIPLE parallel sub-agents (e.g. `run_in_background=true` Agent invocations OR multiple sequential Agents touching different files), the parent agent MUST re-run pytest authoritatively AFTER all sibling agents complete. **Never trust** a sub-agent's reported pytest count from inside the cohort — each sub-agent runs pytest at a SNAPSHOT moment that may not include sibling agents' files. Empirical evidence (commit 9b3007c): 3 parallel build agents each reported "2127 pass" but the authoritative post-cohort count was 2281 (math: 2083 + 69 + 61 + 68 = 2281). Each agent ran pytest before sibling files landed. **Mechanism**: invoke `udm-post-build-verify` skill OR run `.venv/Scripts/python.exe -m pytest tests/tier0 tests/tier1 tests/unit tests/property tests/regression tests/integration tests/crash -q --no-header` directly after the LAST sub-agent reports completion. Document the authoritative count in the commit message + tracker narratives. **Anti-pattern**: copy-pasting a sub-agent's reported count into the commit message without re-verification = Pitfall #9.k arithmetic-propagation drift via sub-agent-stale-snapshot. Sequential single-agent work is NOT subject to this re-verification (single agent's pytest count is authoritative since no sibling work is in flight); only multi-agent parallel cohorts.
4. **Apply `udm-progress-logger`** per CLAUDE.md hard rule 9 -- update canonical trackers + RELATED markdown files based on build type. Per user-direction 2026-05-15 ("Update the skill so it includes updating markdown files related to the build that just took place"), the cascade now walks a per-build-type checklist:

   **Always update (5 canonical trackers — universal regardless of build type)**:
   - `docs/migration/BACKLOG.md` — close any B-N affected (leading-badge flip + inline closure annotation per Pitfall #9.j); open B-Ns surfaced (with WSJF + closure target)
   - `docs/migration/CURRENT_STATE.md` (L7 narrative prepended) — most-recent event at top; "Earlier <date>:" backfill for prior events
   - `docs/migration/HANDOFF.md` (section 14 narrative prepended) — mirror of CURRENT_STATE for fresh-agent onboarding
   - `docs/migration/CODE_BUILD_STATUS.md` (L12 narrative prepended) — code-build state dashboard; per-unit row state transitions if applicable
   - `docs/migration/_validation_log.md` (event entry appended) — full audit-trail entry per hard rule 9

   **Conditional updates (per-build-type)**:

   | Build type | Additional markdown files to update |
   |---|---|
   | NEW public surface (function / class / module-level constant; NOT underscore-prefixed) | `CLAUDE.md` Structure section (per Step 10 / Pitfall #9.n) + `docs/migration/GLOSSARY.md` public-surface tables |
   | NEW EventType constant (CLI_* family) | `CLAUDE.md` L325 CLI_* family registry (per B-269 closure via udm-step-10-verifier Step 3) |
   | NEW D-number locked | `docs/migration/03_DECISIONS.md` (D-number body + status + rationale) per udm-decision-recorder |
   | NEW RB-N runbook | `docs/migration/05_RUNBOOKS.md` (When/Pre-flight/Procedure/Validation/Rollback structure) per udm-runbook-author |
   | NEW SP-N stored procedure | `docs/migration/phase1/01_database_schema.md` SP section + SchemaContract row per D40 / D92 forward-only |
   | NEW edge case (M/S/I/N/P/G/D/F/V series) | `docs/migration/04_EDGE_CASES.md` (relevant series section) |
   | Risk change (new R-N OR escalation/de-escalation) | `docs/migration/RISKS.md` (R-N row update OR new row) |
   | Phase status change (phase / round transitioning) | `docs/migration/02_PHASES.md` (status flip) |
   | Cosmetic / render-discipline / status-render / supersession-crumb / stale-date fix | `docs/migration/POLISH_QUEUE.md` (open P-N OR close P-N per D113) |
   | Executable artifact (one-time vs scheduled per udm-execution-classifier) | `docs/migration/ONE_OFF_SCRIPTS.md` (one-time + manual) OR `docs/migration/phase1/02_configuration.md` section 5.1 (scheduled + Automic) |
   | Spec doc edit (touched phase1/0X_*.md) | The relevant `docs/migration/phase1/0X_*.md` is the canonical edit; cross-doc cascade per D93 may also touch related specs |
   | Sub-class formalization / Pitfall sub-class new entry | `docs/migration/HANDOFF.md` section 8 Pitfall #9 sub-class accumulator (9.a, 9.b, ..., 9.n, 9.o, ...) |
   | New skill / agent / .md template authoring | `docs/migration/GLOSSARY.md` skill catalogue (mirrors udm-progress-logger row format) |

   **Verification procedure** (mandatory; surface in commit message + _validation_log entry):
   For each tracker in the universal-5 list: state "UPDATED" or "UNTOUCHED-AS-EXPECTED (reason)".
   For each conditional row that applies to the current build: state "UPDATED" or explicitly justify the "UNTOUCHED" decision.
   Anti-pattern: silent skip without justification = Pitfall #9.m (discipline-not-applied-to-own-tracker) class drift. The "UNTOUCHED-AS-EXPECTED" justification is the discipline application.

   **Empirical anchor** (this directive surfaced 2026-05-15 per user-direction "After proceeding, update any markdown files that are used for tracking purposes. ... Update the skill so it includes updating markdown files related to the build that just took place"): user noticed multiple commits across the session had slim tracker updates focused on the canonical 5; some build types (e.g. POLISH_QUEUE for cosmetic items; RISKS for risk-touching builds) were inconsistently updated. The per-build-type checklist closes that gap by forcing explicit walk-and-justify per build cohort.
5. **Apply Step 10** per HANDOFF §8 Pitfall #9.n if new public surface added (CLAUDE.md Structure + GLOSSARY)
6. **Commit** on the current branch
7. **Hold push by default**; auto-push ONLY when user trigger phrase includes explicit PR-submission semantics (see Step 1.7.1 below).
   - **1.7.1 — Optional PR submission (added 2026-05-14 per user-direction)**: If user's trigger phrase contains BOTH "next steps" AND ("push" OR "submit" OR "PR" OR "open a PR" OR "make a PR" OR "open PR") semantics, the cascade DOES auto-push the branch after the gap-check completes AND reports the PR creation URL. Otherwise default = hold push (per session-established "hold the push" convention).

   **Trigger-phrase examples that auto-push**:
   - "Push the PR. Next, proceed with next steps." (combines explicit push + cascade trigger)
   - "Proceed with next steps and submit PR"
   - "Move forward + open PR"
   - "Continue with next steps + make a PR after"

   **Trigger-phrase examples that do NOT auto-push (default hold)**:
   - "Proceed with your next steps" (no push/PR semantics)
   - "Move forward" (no push/PR semantics)

   **Mechanism when auto-push fires**:
   1. Run `git push origin <current-branch>` after Step 2 gap-check completes cleanly
   2. Capture the GitHub PR-create URL from the push response (or construct it manually: `https://github.com/<owner>/<repo>/pull/new/<branch>`)
   3. Include the PR URL in the Step 3 cascade-complete report
   4. Suggest PR title + body sections in the report (do NOT auto-open the PR via `gh pr create` — user opens via the URL)

   **Anti-pattern**: auto-pushing without explicit user direction = silent state-change to remote (operator may have wanted to inspect commits locally before pushing). Always require BOTH trigger conditions (cascade-trigger phrase AND PR/push semantics) before auto-pushing.

   **Safety scoping**: auto-push only runs at end of cascade (after Step 2 gap-check clears); NEVER push partial work. If Step 2 surfaces 🟡 IN-FLIGHT-DRIFT, the cascade fixes inline FIRST + commits; THEN auto-push if trigger semantics matched.

### Step 2 — Gap-check on the just-landed commit

Two-layer gap-check per established session pattern:

**Layer 2a — udm-step-10-verifier** (per HANDOFF §8 Step 12 + CLAUDE.md hard rule 9 Step 12):
- Invoke `udm-step-10-verifier` skill
- If verdict is 🟡 IN-FLIGHT-DRIFT: fix inline + re-verify before proceeding to Layer 2b
- If verdict is ✅ CLEAN or ✅ N/A: proceed to Layer 2b

**Layer 2b — broader parent-agent gap reflection**:
- Probe surfaces in parallel:
  - **G1 (Pitfall #9.j)** — leading-badge alignment: any `🟡 Open` badges with inline `CLOSED` annotations that need flip
  - **G2 (Pitfall #9.k)** — arithmetic-propagation: count/state mirrors consistent across BACKLOG / CURRENT_STATE / HANDOFF / CODE_BUILD_STATUS / _validation_log
  - **G3 (Pitfall #9.l)** — canonical re-read: any spec references that need canonical verification
  - **G4 (Pitfall #9.m)** — discipline-applied-to-tracker: any "noted but not opened" B-N candidates
  - **G5 (Pitfall #9.n)** — convention-registration: any new public surface missing from CLAUDE.md/GLOSSARY (overlaps with Layer 2a but broader scope)
  - **G6** — new B-N opportunities surfaced by the work
- For each gap found:
  - 🟡 fixable inline → fix + extend commit OR add new commit on the same branch
  - ✅ clean → proceed to reporting

### Step 3 — Report status

Final commit hash(es) + summary table:
- Recommended next step that was executed
- Net delta (B-N closures / tests / file changes / lines)
- Gap-check verdict (✅ CLEAN / 🟡 fixed-inline)
- Suggested NEXT recommended item from updated runway (but do NOT auto-proceed; user must invoke trigger again)

## Examples

### Example 1 — Trigger present

```
User: "Proceed with your suggested next steps."
Parent agent: [Invokes this skill]
  Step 1: Reads prior turn; finds "Tier 4 crash-injection bodies" as MEDIUM-priority runway item
  Step 1: Authors Tier 4 scaffold + commits
  Step 2a: udm-step-10-verifier → ✅ CLEAN (or fixes inline if 🟡)
  Step 2b: Parent-agent gap reflection → ✅ CLEAN (or fixes inline)
  Step 3: Reports commit hash + updated runway; awaits next user direction
```

### Example 2 — Anti-trigger (question)

```
User: "How many B-Ns have we closed this session?"
Parent agent: [Does NOT invoke this skill]
  Answers the question directly. Counts B-N closures from session history.
  Suggests this skill's invocation only IF user explicitly asks for forward motion.
```

### Example 3 — Anti-trigger (specific action)

```
User: "Update CLAUDE.md L325 with the latest CLI_* family count."
Parent agent: [Does NOT invoke this skill]
  Performs the specific edit. Does NOT chain into "next step" autopilot.
  After completing the edit, awaits next user direction.
```

### Example 4 — Ambiguous → ask

```
User: "Looking good. Keep going."
Parent agent: [Asks for clarification]
  "Keep going" is ambiguous — could mean (a) proceed with next runway item, OR (b) continue the current sub-task. 
  Asks user to clarify before invoking the cascade.
```

## Output contract

After both steps complete, parent agent emits:

```markdown
## Cascade complete — commit `<hash>` (+ optional `<hash>` for gap-fix)

**Recommended step executed**: <item from prior turn's runway>

**Net delta**:
- B-Ns closed: <count> / opened: <count>
- Tests: <prev_pass> → <new_pass> (delta <+N>)
- Files modified: <count>
- Lines: +<count> / -<count>

**Gap-check verdict**: ✅ CLEAN / 🟡 fixed inline (N gaps surfaced + fixed)

**Suggested next recommended item** (do NOT auto-proceed):
- HIGH/MEDIUM/LOW: <next item with effort estimate>

**Awaiting user direction.**
```

## Edge cases

- **No prior turn recommended next step**: skill cannot identify what "next" means → ASK user
- **Prior turn proposed multiple items but no explicit priority**: pick smallest scope; flag the ambiguity in the cascade-complete report
- **Step 1 work fails mid-execution**: surface failure to user; do NOT auto-fix or retry; do NOT proceed to Step 2 until user directs
- **Step 2 gap-check finds 🔴 (not 🟡) drift**: surface 🔴 to user; do NOT auto-fix; await user direction (per CLAUDE.md hard rule 11 D55+D56 second-pass discipline)
- **User invokes trigger mid-session-pause** (e.g., session resumed after sleep): trigger valid; proceed normally

## Composition

| Used with | Role |
|---|---|
| `udm-progress-logger` | Invoked at Step 1.4 to update canonical trackers |
| `udm-step-10-verifier` | Invoked at Step 2a as the in-flight verification layer (per B-261 closure) |
| `udm-gap-check` | Step 2b broader-scope reflection; this cascade IS a wrapper that includes gap-check semantics; standalone udm-gap-check still invocable by user direction without invoking this cascade |
| HANDOFF §8 producer self-check Steps 1-12 | Each step's directive applies; this skill is the orchestration layer |

## Confidence calibration

| User message contains | Confidence to invoke |
|---|---|
| Exact-match trigger phrase ("Proceed with your suggested next steps") | HIGH ✅ INVOKE |
| Strong paraphrase ("Move forward with the next item") | HIGH ✅ INVOKE |
| Weak paraphrase ("OK keep going") | MEDIUM 🟡 ASK first |
| Question / clarification | HIGH ✅ DO NOT INVOKE |
| Specific action request | HIGH ✅ DO NOT INVOKE |
| Anti-trigger phrase ("stop" / "pause" / "wait") | HIGH ✅ DO NOT INVOKE |

When confidence is MEDIUM 🟡, the cost of asking < cost of unauthorized forward motion. ALWAYS ask.

## Tier 0 stub (per D67)

`tests/tier0/test_skill_next_step_cascade.py` (Tier 1 if more complex). Verifies:
- Skill imports
- Trigger-phrase matcher rejects empty string / single word
- Trigger-phrase matcher accepts canonical phrases (case-insensitive)
- Anti-trigger matcher rejects questions / specific-action requests
- Edge case: no prior recommended next step → returns ASK verdict (not INVOKE verdict)

## Cross-references

- User-direction 2026-05-14: "Update the skill to trigger only when I say Proceed with next steps or something similar. We shouldnt always proceed with next steps."
- HANDOFF §8 Pitfall #9 sub-classes 9.j-9.n (all gap-check targets)
- HANDOFF §8 Step 12 (`udm-step-10-verifier` invocation directive)
- CLAUDE.md hard rule 9 (`udm-progress-logger` mandatory)
- CLAUDE.md hard rule 11 (`udm-gap-check` mandatory post-build)
- `.claude/skills/udm-step-10-verifier/SKILL.md` (Step 2a layer)
- `.claude/skills/udm-gap-check/SKILL.md` (Step 2b layer; can also be invoked standalone)
- `.claude/skills/udm-progress-logger/SKILL.md` (invoked at Step 1.4)

## Anti-pattern this skill closes

Throughout the 2026-05-14 session, parent agent operated under a STANDING instruction "1. Proceed with your recommended next steps. 2. Check for any gaps" — but this instruction was treated as AUTOPILOT between every turn, leading to:

- Multiple 1-3 commit forward-motion cycles per user message
- User losing direct control over which runway item gets executed next
- "We shouldn't always proceed with next steps" user feedback 2026-05-14 (the explicit authorization for THIS skill)

The fix: convert the standing instruction from "always proceed" to "proceed ONLY on explicit trigger phrase." User retains direct control; cascade only fires when explicitly invoked.

## Owner

Pipeline lead. First production invocation expected: immediately after this skill is committed, when user invokes trigger phrase ("Proceed with your suggested next steps" — which is exactly what they said in the authorization message).
