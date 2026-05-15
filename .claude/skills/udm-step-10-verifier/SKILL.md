---
name: udm-step-10-verifier
description: Producer-side Step 10 application verifier. Fires AFTER a build cohort completes AND BEFORE the independent gap-check reviewer. Verifies that every newly-authored module/tool has its public surface registered in CLAUDE.md "Structure" section + GLOSSARY.md public-surface tables. Surfaces drift as 🟡 in-flight so producer can fix BEFORE gap-check (not post-hoc detected). Closes B-261 mechanism-evolution candidate per D95 umbrella + 19-instance Pitfall #9.j/n empirical evidence base.
---

# UDM Step 10 Verifier

Producer-side application-mechanism for the Step 10 directive (Pitfall #9.n formalization 2026-05-14): "after authoring a new module/tool/public surface, BEFORE invoking `udm-progress-logger` 🟢 status claim, verify (a) CLAUDE.md 'Structure' subsection has the new artifact row; (b) GLOSSARY public-surface tables include the new exports; (c) Last reviewed date bumped."

## When to invoke

- **AFTER a build cohort completes** (multi-module parallel or sequential build with new public surface)
- **BEFORE invoking `udm-gap-check`** (independent gap-check reviewer per CLAUDE.md hard rule 11)
- **BEFORE the producer claims 🟢 status** via `udm-progress-logger`
- Position in build-cohort cascade: 5th step (1. Build agents → 2. Pytest verify → 3. Step 10 producer application → **4. udm-step-10-verifier (this skill)** → 5. udm-gap-check → 6. udm-progress-logger 🟢 claim)

Skip if:
- The cohort is tracker-only (no new code; no new public surface)
- The cohort is a fix-only commit (modifying existing function bodies; signatures unchanged)
- The cohort introduces only underscore-prefixed (private) helpers (e.g., B-266 + B-267 cases where `_resolve_test_file` extensions added internal-only helpers — no Step 10 application needed; verifier surfaces as ✅ N/A)

## Why this skill exists (empirical evidence base)

Per HANDOFF §8 Pitfall #9.n formalization 2026-05-14 + B-261 3rd-event-trigger:

**Pre-formalization (Round 3-4 cohorts)**:
- Step 10 directive formalized 2026-05-14 morning via DELTA-A3 (per `udm-producer-checklist-evolver` Round 4 close-out output)
- **FAILED first-encounter** at Round 4.1 5-tool cohort same afternoon (24h after formalization)
- 2nd-event recurrence at Round 4 § 3.4 decrypt_pii.py turn (caught at gap-check, corrected before commit)
- 3rd-event recurrence at Round 6 § 4.7 verify_tier0_drift.py full impl turn (commit `146d97a` — NOT corrected until 4 commits later)

**Post-formalization Pitfall #9.j cascade** (same session 2026-05-14):
- § 8 batch closure surfaced 9 stale leading-badges from Round 5 close-out (4-day staleness)
- Round 6 close-out residual sweep surfaced 10 MORE stale leading-badges (B122/123/124/125/126/136/137/138/140/141)
- **Combined empirical baseline: ~19 instances** of post-formalization render-drift surfacing 1-4 days after fix-time

**Pattern**: producer self-check Step 10 directive (in HANDOFF §8 as a 10-step audit list) does NOT auto-trigger application at first encounter; producer needs an EXTERNAL mechanism that fires before discipline-claim is finalized.

This skill IS the external mechanism. Per B-261 disposition: "after spawning a build cohort, schedule a parent-side Step-10-application-verifier sub-agent BEFORE the gap-check independent reviewer; if Step-10 not applied, surface as 🟡 BEFORE gap-check so producer can fix in-flight".

## Canonical Context Load (CCL) per D62

- **Stage 1**: `NORTH_STAR.md` + `HANDOFF.md` (§8 Pitfall #9.n) + `CURRENT_STATE.md` + `CHECKS_AND_BALANCES.md`
- **Stage 2**: `RISKS.md` + `BACKLOG.md` (B-261 closure context) + `_validation_log.md` (current round)
- **Stage 3**: `CLAUDE.md` (the actual Structure + EventType-families-registered + hard rules sections being verified) + `GLOSSARY.md` (public-surface tables being verified)

## Verification procedure (5 steps)

For each newly-authored module / tool in the cohort:

### Step 1 — Identify public surface

Run `git diff --name-only HEAD~N HEAD` to enumerate new + modified files. For each:
- Skip if file is under `tests/`, `docs/`, or `.claude/` (test/doc/skill files don't go in CLAUDE.md Structure)
- Skip if file is a test fixture (e.g., `tests/fixtures/`)
- For source files (`tools/`, `data_load/`, `cdc/`, `orchestration/`, `scd2/`, `observability/`, `utils/`, `schema/`, `extract/`):
  - Run `git diff <prev>..HEAD -- <file>` and identify new public surface:
    - New top-level `def name(` (NOT underscore-prefixed)
    - New top-level `class Name:` (NOT underscore-prefixed)
    - New module-level `NAME = ...` constants (UPPERCASE; typically `EVENT_TYPE`, `EXIT_*`, `DEFAULT_*`)
    - New `__all__ = (...)` entries

### Step 2 — Verify CLAUDE.md Structure registration

For each source file with new public surface:
- Search CLAUDE.md "Structure" section (typically L82-150; the bullet-list of project file paths with surface descriptions)
- Verify the file path has an entry
- Verify the entry's `surface:` list includes at least the new public names (function/class/constant names)
- Verify the entry cites the canonical spec section (e.g., `Round 3 § 1.3`, `Round 4 § 3.7`, `Round 6 § 4.7`)
- Verify build-date annotation present (e.g., `Wave 5.2 build 2026-05-14`)

**🟡 finding if**: file path missing from Structure list OR `surface:` list doesn't include a new public name

### Step 3 — Verify GLOSSARY.md public-surface registration

For each new public NAME (function / class / constant):
- Search GLOSSARY.md for the NAME (case-sensitive)
- For tools: verify entry in `## Round 4 CLI tool public surfaces` section (per the Round 4 cohort precedent)
- For modules: verify entry in the relevant module-surface section
- For EventType constants: verify mention in CLAUDE.md L325 CLI_* family registry (per B-269 follow-up)

**🟡 finding if**: NAME not present in GLOSSARY.md OR NAME present but in wrong section OR EventType constant not in L325 family registry

### Step 4 — Verify Last reviewed date bump

For each tracker that was supposed to be updated (CLAUDE.md typically has a "Last reviewed" date OR section-level date stamps):
- Verify the date is the current commit's date (e.g., `2026-05-14`)
- If date stale (older than commit date), surface as 🟡

### Step 5 — Emit verdict

Possible verdicts:

| Verdict | Meaning | Required action |
|---|---|---|
| ✅ CLEAN | All public surface registered; no drift | Proceed to udm-gap-check |
| 🟡 IN-FLIGHT DRIFT | Step 10 application incomplete; specific gaps enumerated | Producer fixes inline BEFORE udm-gap-check |
| ✅ N/A | Cohort had no new public surface (e.g., fix-only commit OR underscore-prefixed helpers only) | Proceed to udm-gap-check |

## Output contract

Markdown file at `docs/migration/_agent_evolution/step-10-verifier-<commit_or_cohort>-<YYYY-MM-DD>.md`:

```markdown
# Step 10 Verifier Output — <cohort_name>

## Date: YYYY-MM-DD
## Commit / Branch: <hash or branch>
## Verdict: ✅ CLEAN / 🟡 IN-FLIGHT DRIFT / ✅ N/A

## Files probed: <count>

| File | New public surface | CLAUDE.md Structure | GLOSSARY entries | Verdict |
|---|---|---|---|---|
| tools/X.py | `main`, `cli_main`, `EVENT_TYPE`, `EXIT_*` | ✅ L88 | ✅ Round 4 CLI section | ✅ |
| data_load/Y.py | `helper_fn`, `Result` dataclass | 🟡 L120 (missing `Result`) | 🟡 GLOSSARY missing both | 🟡 |

## 🟡 Findings (require producer fix BEFORE gap-check)

### Finding 1: data_load/Y.py — GLOSSARY missing `helper_fn`
- **What**: New public function `helper_fn` in data_load/Y.py at L42
- **Where missing**: GLOSSARY.md "Module function surface" section
- **Recommended fix**: Add row in GLOSSARY § <relevant section> citing `helper_fn` + 1-line purpose
- **Why this matters**: Future agents searching GLOSSARY for `helper_fn` get zero hits; risk of duplicate authorship OR mis-import from a different module

## CLI_* family registry check (CLAUDE.md L325)

| EventType | Status |
|---|---|
| `CLI_NEW_TOOL` | ✅ registered |
| `CLI_OTHER_NEW_TOOL` | 🟡 NOT in L325 family list |

## Recommendation: <FIX-INLINE / NO-ACTION>
```

## Edge cases

- **Underscore-prefixed helpers only** (`_helper_fn`, `_KEYWORD_STOPWORDS`, `_BACKTICKED_IDENT_RE`): per private-API convention, NOT subject to Step 10. Verdict: ✅ N/A. Document this in the verifier output to make the decision visible (so reviewers don't think Step 10 was skipped).
- **Test files** (`tests/tier0/`, `tests/tier1/`, `tests/integration/`, etc.): NOT subject to Step 10. Test files are referenced from CLAUDE.md only at the tier-level (e.g., `tests/property/` row at L92); per-test-file entries are NOT canonical.
- **Test fixtures** (`tests/fixtures/`): subject to Step 10 ONLY if the fixture introduces new shared public API (e.g., a fixture-factory function). DDL fixtures like `schema.sql` are exempt.
- **Modified function body, signature unchanged**: NOT new public surface. Verdict: ✅ N/A.
- **Modified function signature** (additive only per D92 forward-only): IS new public surface (new kwargs). Update CLAUDE.md Structure row's `surface:` list with the new signature signal (e.g., add the new kwarg name to surface inventory).
- **EventType constants added** (`EVENT_TYPE = "CLI_NEW"`): require BOTH CLAUDE.md Structure (per-tool row) AND CLAUDE.md L325 CLI_* family registry update (per B-269).

## Anti-patterns to detect

The verifier should explicitly catch these (each maps to a known prior recurrence):

| Anti-pattern | First instance | Recurrence count |
|---|---|---|
| New EventType constant in tool module; per-tool Structure row updated; CLI_* family registry text NOT updated | `146d97a` (verify_tier0_drift) | 4 (12 → 15 tools by Round 6 follow-up cohort) |
| New module landed; CLAUDE.md Structure row absent | Round 4.1 5-tool cohort 2026-05-14 afternoon | 3 (Round 4.1 + § 3.4 + § 4.7) |
| New dataclass added to module's public surface; CLAUDE.md `surface:` list NOT extended | Round 3 Wave 2 (multiple modules) | observed in ad-hoc gap-checks |
| EventType added; D76 audit-row contract honored; CLAUDE.md L325 registry text says old count | `146d97a` + 3 subsequent commits | 4 (B-269 evidence base) |

## Composition

| Used with | Role |
|---|---|
| `udm-progress-logger` | Skill runs BEFORE udm-progress-logger 🟢 status claim |
| `udm-gap-check` | Skill runs BEFORE udm-gap-check independent reviewer; reduces gap-check workload by catching Step 10 drift in-flight |
| `udm-producer-checklist-evolver` | If this skill surfaces NEW recurring drift patterns (3+ events / 2+ rounds), feed into producer-checklist-evolver for directive strengthening |
| HANDOFF §8 Pitfall #9.n | Canonical directive home; this skill is the producer-side application mechanism |

## Confidence calibration

| Evidence in run | Confidence |
|---|---|
| All Structure rows + GLOSSARY entries match new surface | HIGH ✅ CLEAN |
| 1-2 minor gaps in surface lists (typo / wrong section) | MEDIUM 🟡 IN-FLIGHT |
| Multiple modules with missing rows + missing GLOSSARY + missing L325 update | HIGH 🟡 IN-FLIGHT (escalate to udm-cascade-audit-evolver) |
| Cohort is fix-only / private-only | HIGH ✅ N/A |

## Tier 0 stub (per D67)

`tests/tier0/test_skill_step_10_verifier.py` (Tier 1 if more complex). Verifies:
- Skill imports
- Empty-surface cohort verdicts ✅ N/A
- Cohort with missing Structure row → 🟡 IN-FLIGHT
- Cohort with missing GLOSSARY entry → 🟡 IN-FLIGHT
- Cohort with missing L325 CLI_* family registry update → 🟡 IN-FLIGHT (separate per B-269)
- Underscore-prefixed-only cohort → ✅ N/A

## Cross-references

- D95 (self-improvement umbrella)
- D98 (semver versioning for agent prompts)
- HANDOFF §8 Pitfall #9.n (canonical directive)
- B-261 (this skill's mechanism-evolution closure target)
- B-269 (CLI_* family registry update sub-step; paired with this skill)
- B-260 (sub-class 9.o candidate: discipline-formalization-without-application-mechanism — this skill IS the application mechanism)
- `.claude/skills/udm-progress-logger/SKILL.md`
- `.claude/skills/udm-gap-check/SKILL.md`
- `.claude/skills/udm-producer-checklist-evolver/SKILL.md`

## Owner

Pipeline lead. First production invocation expected: next build cohort that introduces new public surface (e.g., Tier 4 crash-injection bodies authoring OR additional Tier 3 test scenarios with new fixture-factory functions OR a Round 4 § 3.9/§ 3.11 unblocked build).

## Empirical baseline (closure of B-261)

This skill closes B-261 with the following empirical evidence base (per HANDOFF §8 Pitfall #9.n formalization):

- **Step 10 first-encounter failures**: 3 (Round 4.1 + § 3.4 + § 4.7)
- **Post-formalization Pitfall #9.j render-drift instances**: ~19 (9 from § 8 batch + 10 from Round 6 close-out residual sweep)
- **CLI_* family registry drift instances**: 4 (B-269 evidence base)
- **Lag between formalization and recurrence**: ≤24 hours (Step 10 formalized 2026-05-14 AM; failed at Round 4.1 same afternoon)

This skill shifts the catch-time from post-hoc gap-check (1-4 day lag) to producer-time validation (0-day lag; in-flight fix).
