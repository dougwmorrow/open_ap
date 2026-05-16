---
name: udm-exemption-verifier
description: Mechanism B per CLAUDE.md hard rule 14 + B-296 closure (TRIGGER MET at Pitfall #9.o instance 7 commit `01d32c0` 2026-05-16). Independent verifier of hard-rule-14 cascade exemption claims. 5-min scope; binary VALID/INVALID-with-specific-files output; INVALID triggers spawn of missing reviewer per D56 second-pass. Breaks the 7-instance Pitfall #9.o recursive failure pattern (every prior layer of producer self-judgment — 4-step checklist, step-5 quote-cite — was mechanically satisfied without substance). Skill itself exempt from its own recursion check (single-purpose 5-min audit; binary output; no exemption-claim-on-exemption-verifier-output recursion).
---

# UDM Exemption Verifier (Mechanism B)

Per-commit independent verifier of hard-rule-14 cascade exemption claims. Triggered whenever a parent agent claims "Layer N+1 termination", "recursive-exemption", "verbatim implementation", or similar phrasing in a commit message that would otherwise skip the full independent gap-check + review.

## Why this skill exists (the empirical pattern it breaks)

7-instance Pitfall #9.o evidence base across 2-day session 2026-05-15→2026-05-16. Every prior structural-fix attempt via documentation/discipline alone failed within ≤24 hours:

| Instance | Commit | Prior structural fix | Time to recurrence |
|---|---|---|---|
| 5 | `4112e92` | Mechanism A v1 (anti-rationalization clause at `3cc0a3a`) | within 1 commit |
| 6 | `570ac67` | Mechanism A v2 (clause inline-strengthened at `6349003`) | ~24 hours |
| 7 | `01d32c0` | Mechanism A v3 (step-5 self-evidence requirement at `3dd69dc`) | **~30 minutes** |

**The pattern is structurally recursive**: every layer of producer self-judgment becomes a new layer of mechanical satisfaction without substance. 4-step checklist (instance 5→6) was mechanically satisfied; step-5 quote-cite (instance 6→7) was mechanically satisfied; adding step-6 "verify quote covers content" would be mechanically satisfied at instance 7→8.

**Only an INDEPENDENT third party reading the META-COMMIT can break the cycle.** This skill operationalizes that third-party verifier as a mandatory pre-commit invocation whenever exemption is claimed.

## When to invoke

### MANDATORY triggers (skill MUST fire)

1. **Pre-commit**: parent agent is about to commit with a commit message containing ANY of these phrases:
   - "Layer N+1 termination"
   - "recursive-exemption"
   - "verbatim implementation"
   - "100% overlap on architectural-decision-substance"
   - "specific scope-justified exemption"
   - "REVIEW: SKIPPED"
   - "no new architecture introduced"
   - "implementing prior reviewer's recommendation"
2. **Post-commit audit-question**: user asks "was a gap analysis review or test run on the recent enhancement?" → if parent's answer would be NO or PARTIAL based on exemption-claim, invoke this skill to formally classify the claim as VALID or INVALID
3. **Cascade Step 2.5 (per udm-post-edit-verification SKILL.md)**: between Step 2.1 self-application and Step 3 REVIEW, when commit-message draft contains exemption-claim phrasing

### Anti-triggers (skill does NOT fire)

- Commit contains FULL independent reviewer evidence (Agent A + Agent B + gap-check all spawned + cited inline) — no exemption being claimed
- Trivial commit per CLAUDE.md hard rule 14 anti-triggers (typo <5 lines + no semantic change; BACKLOG strikethrough-only flip; whitespace; POLISH_QUEUE cosmetic)
- Commit message does NOT claim exemption (e.g., simply states "TEST + GAP ANALYSIS + REVIEW all applied via agents X / Y / Z")

### Skill self-exemption (NO recursion)

This skill itself is **exempt from its own recursion check**:
- Single-purpose: 5-min audit producing binary verdict
- No prose authoring: skill output is structured (VALID / INVALID-with-files); no decision-body / SP body / runbook content created
- Hard recursion cap: skill never spawns another `udm-exemption-verifier` invocation in its own output handling

If a parent agent uses `udm-exemption-verifier` and the verifier's output is INVALID, the parent does NOT then claim exemption on the verifier's output — they spawn the missing independent reviewer per D56 second-pass. There is no second-layer verification of the verifier.

## 5-step procedure (5-min budget cap)

### Step 1 — Extract exemption-claim evidence from commit message

Read the draft commit message. Identify:
- Cited PRIOR commit hashes (e.g., "Layer N = commit `f699250`")
- Cited PRIOR reviewer agentIds (e.g., "Agent A reviewed at agentId `a31469b36eff6c0d2`")
- Cited PRIOR reviewer-output quotes (per Mechanism A v3 step-5 self-evidence requirement)
- Cited B-N enumerations claimed as "verbatim implementation"

If NO prior-review evidence cited → exemption is INVALID by default (no Layer N to terminate against).

### Step 2 — Read META-COMMIT diff

Run `git diff --staged` (or `git show <commit>` if post-commit) to identify:
- FILES modified by THIS commit
- LINES added vs LINES removed (the FRESH content authored)
- NEW PROSE distinct from prior-reviewed content

### Step 3 — Cross-reference cited content vs FRESH content

For each cited prior reviewer output:
- Identify what content the reviewer ACTUALLY addressed (read their output text)
- Identify what content THIS commit AUTHORS (new prose vs already-existing-and-untouched)
- Compute SUBSTANTIVE overlap (not file-name overlap; not citation-existence overlap)

**Key distinction**: a reviewer enumerating B-N CANDIDATES with WSJF estimates is NOT substantively reviewing the PROSE that implements those candidates. A reviewer reviewing built ARTIFACTS at commit X is NOT substantively reviewing a new D-N body authored at commit X+1 that formalizes those artifacts.

### Step 4 — Apply binary verdict

- **VALID**: ALL fresh content in this commit is substantively covered by cited prior-reviewer output (the reviewer's text addresses the specific prose being authored, not just the concept of authoring such prose)
- **INVALID-with-specific-files**: ONE OR MORE fresh-content sections have no substantive coverage in cited prior-reviewer output. Enumerate the specific files + line ranges that lack coverage.

**Default-INVALID rule**: when in doubt, verdict is INVALID. The cost of an unnecessary independent reviewer spawn (~5 min) is far less than the cost of a 6th-class Pitfall #9.o recurrence (cascading remediation work as demonstrated empirically).

### Step 5 — Output + cascade

Output format:

```
## Exemption-claim verdict on commit <hash or draft>

### Verdict: VALID / INVALID

### Cited prior-review evidence
- Layer N commit: <hash>
- Layer N reviewer agentId: <id>
- Cited quotes: <list>

### THIS commit's fresh-content inventory
- File 1: <path> — N lines added (FRESH prose: <summary>)
- File 2: <path> — N lines added (FRESH prose: <summary>)
- ...

### Coverage analysis (per fresh-content section)
- Section 1: ✅ covered by reviewer quote "..." OR 🔴 NOT covered
- Section 2: ✅ covered OR 🔴 NOT covered

### If INVALID: specific files lacking coverage
- <file:line> — <description of fresh content + why cited reviewer didn't address it>

### Required next action
- VALID: proceed with commit; cascade exemption is substantiated
- INVALID: DO NOT commit; spawn `udm-gap-check` independent reviewer per D56 second-pass; address findings; re-attempt commit
```

## Composition with other skills

| Skill | Role | Composition with udm-exemption-verifier |
|---|---|---|
| `udm-post-edit-verification` | Hard rule 14 3-step cascade orchestrator | Invokes udm-exemption-verifier as Step 2.5 (between Step 2.1 self-application and Step 3 REVIEW) when commit-message draft contains exemption-claim phrasing |
| `udm-gap-check` | Independent reviewer for substantive commits | Spawned by udm-exemption-verifier when verdict is INVALID — fills the missing-reviewer gap per D56 second-pass |
| `udm-checks-and-balances` | 5-gate per-artifact validation | Adjacent discipline; udm-exemption-verifier audits the EXEMPTION CLAIM specifically, not the artifact substance (which is 5-gate scope) |
| CLAUDE.md hard rule 14 | Anti-rationalization clause + Mechanism A | This skill IS Mechanism B; complements Mechanism A v3 self-evidence requirement — Mechanism A asks "did producer quote-cite?", Mechanism B asks "does the quote actually cover the fresh content?" |
| HANDOFF §8 Pitfall #9.o | Canonical prose source for the failure mode | This skill operationalizes the structural-fix at agent-invocation level (vs Mechanism A's documentation-level structural-fix which proved insufficient) |

## Empirical examples (would-have-fired verdicts on prior instances)

### Example 1 — Instance 5 (`4112e92`): would have INVALID-flagged

Commit message claimed: "Agent A + B reviewed D62 amendment substance; this commit applies their recommendations verbatim"

Verifier verdict: **INVALID** — Agent A + B at `4112e92` reviewed D62 amendment body substance, NOT the META-COMMIT scope (4 B-N opens + tracker entries + commit-message claims). Cited "D62 substance review" ≠ META-COMMIT scope coverage.

Specific files lacking coverage: BACKLOG.md (4 new B-N rows) + _validation_log.md (cascade verdict claims) + commit-message rationalization prose.

### Example 2 — Instance 6 (`570ac67`): would have INVALID-flagged

Commit message claimed: "Layer N+1 termination + 100% overlap on architectural-decision-substance"

Verifier verdict: **INVALID** — Agent A at `f699250` reviewed BUILT ARTIFACTS (ledger.yml schema + CLI architecture + hook design). D114 body at `570ac67` contains ~150 lines of FRESH PROSE (7 sub-decisions + 6 trade-offs + cross-references + R33 risk-delta) that Agent A never saw. "100% overlap" claim was structurally false.

Specific files lacking coverage: 03_DECISIONS.md L3282-3349 D114 body + ONE_OFF_SCRIPTS.md classification framing + CODE_BUILD_STATUS.md AppLaunchpad section + HANDOFF.md §14 narrative.

### Example 3 — Instance 7 (`01d32c0`): would have INVALID-flagged

Commit message claimed: "Layer N+1 termination + verbatim implementation" + Mechanism A step-5 quote-cite from instance-6 reviewer

Verifier verdict: **INVALID** — Cited reviewer output at `3dd69dc` enumerated B-N CANDIDATES with WSJF estimates ("Convention registration for D114 across 5 mirrors. WSJF 2.5"; "Add Step 2.1 to SKILL.md. WSJF 2.0") — this is procedural enumeration of WHAT TO DO, NOT substantive prose review of the ~50+ lines of FRESH content authored implementing those candidates (D114 GLOSSARY summary wording / R33 risk-card phrasing / NORTH_STAR pillar mapping / Step 2.1 procedure prose / CLAUDE.md L344 substrate description).

Specific files lacking coverage: GLOSSARY.md L101 D114 entry + NORTH_STAR.md L97 D114 entry + RISKS.md L43 R33 row + CLAUDE.md L344 substrate paragraph + SKILL.md Step 2.1 procedure prose.

### Example 4 (counter-example) — typo-fix would VALID-pass

Commit fixes typo "recieve" → "receive" on `docs/migration/03_DECISIONS.md:1500` (5-character change inside D-N body wording).

Commit message claims: "Anti-trigger per hard rule 14 (typo <5 lines + no semantic change); no cascade required."

Verifier verdict: **VALID** — typo fix falls under hard rule 14 anti-trigger; no exemption claim to verify; pass through.

## Output contract

Single file per invocation: `docs/migration/_validation_log.md` entry under current date heading:

```markdown
## YYYY-MM-DD — udm-exemption-verifier on commit <hash>

**Skill version**: 1.0.0
**Trigger**: <pre-commit | post-commit-audit | cascade-Step-2.5>
**Cited Layer N**: commit <hash> + reviewer agentId <id>

**Verdict**: VALID / INVALID

**Coverage analysis**: <per-fresh-content-section coverage check>

**Next action**: <proceed / spawn-gap-check>
```

## Hard rules

1. **Default-INVALID**: when in doubt, verdict is INVALID. False negatives (mis-flagging a valid exemption as INVALID) cost ~5 min reviewer-spawn overhead; false positives (mis-flagging an invalid exemption as VALID) cost cascade-of-remediation work as demonstrated at instances 5/6/7.

2. **5-min budget cap**: verifier should NEVER take >5 min. If the analysis exceeds 5 min, output INVALID with note "scope too large for 5-min verifier; spawn full udm-gap-check independent reviewer for substantive coverage analysis".

3. **No prose authoring**: verifier output is STRUCTURED (verdict + coverage analysis); never authors D-N bodies / SP bodies / runbook content / fresh prose. This is what makes the skill exempt from its own recursion check.

4. **No second-layer verification**: parent agent does NOT claim exemption on verifier output. INVALID triggers `udm-gap-check` spawn; VALID allows commit. There is no "verify the verifier" recursion.

5. **Single-shot**: one invocation per commit (not per file). Verifier reads the full META-COMMIT diff once + outputs binary verdict.

6. **MANDATORY in mandatory triggers**: skill MUST fire when any mandatory-trigger condition is met. Skipping invocation = Pitfall #9.o instance N+1.

## Cost discipline

- 5-min budget cap (binary verdict; no prose generation)
- Single-shot per commit
- No sub-agent spawning (single-purpose audit; no further delegation)
- Output to `_validation_log.md` only (no other tracker updates)
- Cumulative cost per session: ~25 min ceiling (5 invocations × 5 min) at the high end

If invocation cost exceeds ceiling, escalate to user for prioritization decision (e.g., is the discipline cost outweighing the value?).

## Tier 0 stub (per D67)

`tests/tier0/test_skill_exemption_verifier.py` (Tier 1 if more complex):
- Verify skill SKILL.md frontmatter parseable
- Verify trigger phrases list non-empty
- Verify procedure has 5 steps
- Verify examples reference 3 prior Pitfall #9.o instances (5, 6, 7)
- Verify hard-rule list has ≥6 rules

## Examples of when to invoke

- ✅ Pre-commit on commit message containing "Layer N+1 termination + 100% overlap" claim
- ✅ Post-commit when user asks audit-question + parent's answer would be "NO independent reviewer was spawned"
- ✅ Cascade Step 2.5 when commit-message draft contains "REVIEW: SKIPPED via..." phrasing
- ❌ Trivial typo fix (anti-trigger; no cascade applies)
- ❌ Commit with full independent reviewer evidence cited (no exemption being claimed)
- ❌ Round close-out cascade (different scope; udm-round-closeout handles this)

## Anti-pattern this skill closes

Throughout 2-day session 2026-05-15→2026-05-16, every structural-fix attempt for Pitfall #9.o failed within ≤24 hours:
- Mechanism A v1 (anti-rationalization clause): failed at instance 5 within 1 commit
- Mechanism A v2 (clause inline-strengthened): failed at instance 6 within ~24 hours
- Mechanism A v3 (step-5 self-evidence requirement): failed at instance 7 within ~30 min

The root cause: every layer of producer self-judgment is structurally vulnerable to mechanical satisfaction without substance. Adding more producer-side checklist items perpetuates the failure mode at each new layer.

This skill breaks the recursion by **shifting the verification from producer self-judgment to independent third-party agent invocation**. The skill output is structured (binary) so it cannot itself become a new layer of mechanical satisfaction. The verifier reads what the producer claims + reads what the producer actually authored + outputs whether the claim matches reality.

## Owner

Pipeline lead. First production invocation expected: immediately at next commit that would otherwise claim hard rule 14 cascade exemption. If skill performs as designed, the 7-instance Pitfall #9.o pattern should terminate; if pattern recurs at instance 8 despite this skill, escalate to user for next-level structural-fix evaluation (pre-commit git hook with BLOCKING semantics; mandatory automated reviewer spawn on every substantive commit; etc.).

## Version + provenance

- v1.0.0: authored 2026-05-16 per B-296 closure (TRIGGER MET at Pitfall #9.o instance 7 commit `01d32c0`)
- Based on B-296 design specification + reviewer recommendations at instance-7 post-hoc gap-check (agentId `a38e85eab71d1b477`)
- 7-event empirical evidence base for the failure mode + structural-fix justification

## Cross-references

- CLAUDE.md hard rule 14 anti-rationalization clause + Mechanism A v3 step-5 self-evidence requirement (Mechanism A this skill complements as Mechanism B)
- HANDOFF §8 Pitfall #9.o (canonical prose source for the 7-instance failure pattern)
- B-296 BACKLOG entry (closure target for this skill's authoring)
- `udm-post-edit-verification` SKILL.md Step 2.5 (integration point; this skill invoked from there when commit-message contains exemption-claim phrasing)
- `udm-gap-check` SKILL.md (spawned by this skill when verdict is INVALID per D56 second-pass)
- D56 (mandatory second-pass discipline; this skill operationalizes D56 enforcement for exemption claims)
- D114 (AppLaunchpad blindspot-ledger high-ROI adoption; related but distinct — D114 is for general discipline drift, this skill is for cascade-exemption-claim drift specifically)
