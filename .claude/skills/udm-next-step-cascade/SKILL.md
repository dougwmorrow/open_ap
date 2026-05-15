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
4. **Apply `udm-progress-logger`** per CLAUDE.md hard rule 9 — update canonical trackers:
   - BACKLOG.md (close any B-N affected; open B-Ns surfaced)
   - CURRENT_STATE.md (L7 narrative prepended)
   - HANDOFF.md (§14 narrative prepended)
   - CODE_BUILD_STATUS.md (L12 if code changed)
   - _validation_log.md (event entry)
5. **Apply Step 10** per HANDOFF §8 Pitfall #9.n if new public surface added (CLAUDE.md Structure + GLOSSARY)
6. **Commit** on the current branch
7. **Hold push** unless explicit instruction to push (recent user direction "hold the push" is the default)

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
