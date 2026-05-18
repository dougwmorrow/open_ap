<!-- RECONSTRUCTED 2026-05-15 from udm-researcher agent chat-text output (researcher SKILL convention returns findings as chat text, not file write; parent agent reconstructs verbatim per Pitfall #9.k-style discipline). Original prompt requested output to this exact file path; reconstruction faithful to the returned text. -->

# Superpowers Skill Framework — Industry Research

**Date**: 2026-05-15
**Sub-agent inheritance**: per CLAUDE.md hard rule 13 + PLANNING_DISCIPLINE.md §3 — active skills inherited from parent's planning session (udm-researcher only); 3rd production application of the inheritance contract.
**Researcher**: udm-researcher (invoked per user-direction 2026-05-15 "Reflect on superpowers skill. Are we leveraging this skill?")
**Scope**: identify Superpowers framework + assess leverage gap for this project

---

## Executive Summary

- **Superpowers is a real, actively-maintained open-source skills framework** created by Jesse Vincent (GitHub: obra) in October 2025. Canonical repository: `https://github.com/obra/superpowers`. MIT licensed. 184,000+ GitHub stars and 17,000+ forks as of May 2026 (star-history.com global rank #26).
- **The framework ships 14 skills** organized into Testing, Debugging, Collaboration, and Meta categories. Core mandate: enforce engineering discipline (TDD, root-cause-before-fix, design-before-code) that vanilla Claude Code omits.
- **This project adopted ONLY 2 of 14 skills as inspiration** (brainstorming + writing-plans) and evolved both considerably. The remaining 12 Superpowers skills have no equivalent in this project's `.claude/skills/` directory.
- **The leverage gap is REAL but SELECTIVE**: missing Superpowers skills address generic SWE discipline; project has built 22 domain-specific skills covering round planning, validation gates, self-improvement, decision recording, edge cases, execution classification — areas Superpowers does not address.
- **Superpowers does NOT cite academic research** (SkillsBench arxiv 2602.12670, CodeCompass, or similar). The project's planning discipline (PLANNING_DISCIPLINE.md v0.2) is better academically grounded than Superpowers itself.
- **Recommendation: Partial adoption (Option B)** — import `systematic-debugging`, `verification-before-completion`, and (optionally) `test-driven-development` as companion skills. They fill a genuine gap (code-execution discipline) that none of the 22 project skills currently address. Do NOT replace any existing project skills.

---

## §1. Identification

- **Repository URL**: https://github.com/obra/superpowers
- **Maintainer**: Jesse Vincent (obra); created Jifty + Prophet; blog at blog.fsck.com
- **License**: MIT
- **Created**: October 2025 (v2.0.0 on 2025-10-12; v3.0.1 adopted Anthropic's first-party skills system on 2025-10-16)
- **Last updated**: v5.1.0 on 2026-04-30
- **Community signals**: 184,700+ stars; 17,200+ forks; 28-33 contributors; 94% PR rejection rate (strict quality bar); accepted into official Anthropic Claude Code marketplace 2026-01-15; also available on Codex CLI / Factory Droid / Gemini CLI / OpenCode / Cursor / GitHub Copilot CLI
- **Documentation**: https://obra-superpowers.mintlify.app/introduction
- **Origin post**: https://blog.fsck.com/2025/10/09/superpowers/ ("How I'm using coding agents in October 2025")

---

## §2. Skill Catalogue (full 14-skill enumeration)

| Skill | Category | One-line description |
|---|---|---|
| `using-superpowers` | Meta | Orchestration: mandates skill invocation if 1% applicability; defines instruction hierarchy (user → superpowers → default system prompt) |
| `writing-skills` | Meta | TDD for skill authorship: write pressure test → watch fail → write skill → watch comply → refactor |
| `brainstorming` | Collaboration | 9-step Socratic design before any code; saves design doc to `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`; ONLY transitions to writing-plans |
| `writing-plans` | Collaboration | Breaks approved design into 2-5 minute tasks with exact paths + code blocks + commits; no TBD placeholders |
| `executing-plans` | Collaboration | Executes plan inline with human checkpoints; alternative to subagent-driven-development for shorter tasks |
| `dispatching-parallel-agents` | Collaboration | Delegates 3+ independent failures/tasks to specialized agents working concurrently; isolated context per agent |
| `subagent-driven-development` | Collaboration | Fresh subagent per task with two-stage review (spec-compliance THEN code-quality); never skip either |
| `requesting-code-review` | Collaboration | Structures how to request code review (agent or human); defines context |
| `receiving-code-review` | Collaboration | Structures how to receive + process review feedback; prevents defensive dismissal |
| `using-git-worktrees` | Collaboration | Isolated workspace on new branch before implementation; required before any implementation work |
| `finishing-a-development-branch` | Collaboration | Verifies tests pass; presents options (merge/PR/keep/discard); cleans up worktree |
| `test-driven-development` | Testing | RED-GREEN-REFACTOR with hard gates; tests MUST fail before implementation; "I'll write the test after" = delete and restart |
| `systematic-debugging` | Debugging | 4-phase: reproduce → minimize → hypothesize-and-validate → fix; forbids fixing what is not understood |
| `verification-before-completion` | Debugging | Runs FRESH verification commands + shows evidence BEFORE claiming success; prevents "it should work" declarations |

---

## §3. Installation + Usage Pattern

- **Primary path**: `/plugin install superpowers@claude-plugins-official` (Anthropic marketplace)
- **Structural convention**: same `skills/<name>/SKILL.md` layout as this project's `.claude/skills/<name>/SKILL.md`
- **Activation**: `using-superpowers` injected via `SessionStart` hook (platform-dependent)
- **Cross-platform**: works on Claude Code + Cursor + Codex CLI + Gemini CLI + Factory Droid + OpenCode + GitHub Copilot CLI
- **No version pinning**: auto-updates via plugin system; RELEASE-NOTES.md tracks changes; roughly monthly cadence
- **Companion repo** `obra/superpowers-skills` was archived (read-only) 2025-10-27; consolidated into main

---

## §4. Comparison vs This Project's `.claude/skills/`

| Superpowers Skill | This Project's Equivalent | Status |
|---|---|---|
| `brainstorming` | `udm-brainstorm` | **EVOLVED**: project adds NORTH_STAR pillar scoring + D-number/edge-case cross-ref + explicit recommendation rule |
| `writing-plans` | `udm-planning` | **EVOLVED**: project adds 6-step cycle (Plan/Validate/QA/Edge Cases/Validate Edge Cases/Sign-off) + D-N citation per task + CCL integration |
| `using-superpowers` | (none) | **MISSING**: orchestration "if 1% chance, invoke" — but conflicts with project's explicit-trigger discipline per `udm-next-step-cascade` |
| `writing-skills` | (none) | **MISSING**: TDD for skill authorship; project used D55 5-gate instead |
| `test-driven-development` | `udm-post-build-verify` (partial) | **PARTIAL**: project runs tests AFTER code; does not enforce RED first |
| `systematic-debugging` | (none) | **MISSING**: 4-phase root-cause discipline has no equivalent; project's CLAUDE.md Error Recovery is pattern-matching not structured |
| `verification-before-completion` | (none) | **MISSING**: project's `udm-gap-check` is post-completion audit; no PRE-completion verification gate |
| `subagent-driven-development` | `udm-checks-and-balances` + multi-agent patterns (partial) | **PARTIAL**: Pattern E exists; two-stage review structure differs |
| `requesting-code-review` | `udm-data-engineer-review` (partial) | **PARTIAL**: project version is domain-specific; Superpowers' is generic |
| `receiving-code-review` | (none) | **MISSING**: no formal skill governs feedback processing |
| `using-git-worktrees` | (none) | **MISSING**: project uses single working directory (CLAUDE.md `/debi` boundary) |
| `finishing-a-development-branch` | `udm-round-closeout` (partial) | **PARTIAL**: project's round close-out covers doc updates; Superpowers' focuses on branch/worktree cleanup |
| `executing-plans` | (implicit in build patterns) | **PARTIAL**: Pattern B1/B2 covers execution; not a standalone skill |
| `dispatching-parallel-agents` | (implicit in Pattern E) | **PARTIAL**: Pattern E spawns parallel agents; "3+ independent failures" dispatch rule not formalized |

**Surplus in this project (no Superpowers equivalent; 20+ skills)**: udm-checks-and-balances / udm-decision-recorder / udm-edge-case-validator / udm-round-closeout / udm-gap-check / udm-progress-logger / udm-execution-classifier / udm-step-10-verifier / udm-cascade-audit-evolver / udm-planning-session-startup / udm-next-step-cascade / udm-specialty-tuner / udm-subclass-accumulator / udm-cycle-cadence-optimizer / udm-agent-prompt-versioner / udm-retrospective-collector / udm-producer-checklist-evolver / udm-runbook-author / udm-post-build-verify / udm-data-engineer-review.

---

## §5. brainstorming + writing-plans deep dive

### brainstorming (Superpowers 9-step) vs udm-brainstorm

**Common DNA**: at-least-3 options; explicit recommendation; prohibit coding before design approval.

**Project's additions**: NORTH_STAR pillar scoring per option; mandatory D-number + edge-case cross-ref; "It depends is not an answer" rule.

**Superpowers' additions absent in project**: 9-step procedural checklist; mandatory section-by-section approval loop; saves design doc to canonical path `docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`; visual companion (separate from main content); self-review for placeholders/contradictions; explicit user approval of written spec before transitioning to writing-plans.

### writing-plans (Superpowers) vs udm-planning

**Common DNA**: 2-5 minute task granularity. (This is the shared element explaining the "Inspired by Superpowers" credit.)

**Project's additions**: per-task D-number + edge-case citation requirement; 6-step cycle mapping; CCL precondition.

**Superpowers' additions absent in project**: produces saved markdown document at canonical path `docs/superpowers/plans/YYYY-MM-DD-<feature>.md`; includes complete code blocks + exact file paths + specific git commit commands; no TBD placeholders allowed; embedded self-review checklist (spec coverage + placeholder scan + type consistency).

---

## §6. Recommendation: B — Partial adoption

Import 3 specific Superpowers skills as companions; leave all 22 existing project skills unchanged.

### Three skills to import

| # | Skill | Why import |
|---|---|---|
| 1 | **`systematic-debugging`** | 4-phase root-cause discipline has NO equivalent. Project's Error Recovery is pattern-matching, not structured. CDC/SCD2 failures are often systemic (hash mismatch, precision drift, staging orphan) — root cause identification before patching is load-bearing. |
| 2 | **`verification-before-completion`** | Project has strong POST-completion audit (`udm-gap-check`) but nothing prevents agents claiming success BEFORE running fresh verification. Direct relevance: parent agent's Pitfall #9.k stale-narrative-quotation pattern from commit `521b68c` (claimed 2320/62/0 without running pytest) would have been prevented. |
| 3 | **`test-driven-development`** (optional) | Project's `udm-post-build-verify` runs tests AFTER code. TDD enforces RED before GREEN. Lower priority since `udm-test-author` parallel-agent pattern achieves functional approximation. |

### What NOT to adopt

- **`using-superpowers`** — conflicts with project's explicit-trigger discipline per `udm-next-step-cascade` (user-direction 2026-05-14 "We shouldn't always proceed with next steps")
- **`using-git-worktrees`** — doesn't apply (single working directory per CLAUDE.md `/debi` boundary)
- **`writing-skills`** — lower priority than code-debugging discipline
- **Replace `brainstorming` or `writing-plans`** — project's evolved versions have UDM-specific value (D-N citation, NORTH_STAR scoring, CCL integration) the canonical versions lack

### Naming convention

Imported skills should use `superpowers-<name>` prefix to preserve provenance:
- `.claude/skills/superpowers-systematic-debugging/SKILL.md`
- `.claude/skills/superpowers-verification-before-completion/SKILL.md`
- `.claude/skills/superpowers-tdd/SKILL.md` (optional)

This distinguishes upstream-imported skills from project-authored skills (`udm-*`).

### Required updates if approved

- GLOSSARY skill catalogue: 3 new rows
- CLAUDE.md hard rule 13 reference: minor addition noting Superpowers as upstream skill source
- PLANNING_DISCIPLINE.md §2.2 matrix: add `superpowers-systematic-debugging` to PS-7 CLOSEOUT (debugging during failures) + add `superpowers-verification-before-completion` as always-mandatory (regardless of scope)
- `udm-planning` + `udm-brainstorm` SKILL.md headers: extend "Inspired by Superpowers" credit to "Inspired by Superpowers (https://github.com/obra/superpowers) version X.Y.Z; evolved per <reasons>"

---

## Counter-Evidence

Against partial adoption:
- D55 5-gate already catches "claimed done but not actually done" via Gate 5 — `verification-before-completion` may be redundant
- D67 + D79-D82 6-tier test pyramid + `udm-post-build-verify` may make TDD overhead duplicative
- Superpowers' generic skills lack domain awareness; importing adds weight without specificity

Against adopting nothing:
- Recent commit `521b68c` (sign-off ceremony) DEMONSTRATED the verification-gap: agent claimed `2320/62/0` without running pytest; gap was caught only post-hoc via user audit-question + remediation (`1b00755`). `verification-before-completion` would have prevented this.
- No existing skill addresses "what to do when debugging a novel pipeline failure" as a structured methodology.

---

## What This Research Does NOT Cover

- Whether `writing-skills` (TDD for skill authorship) should be applied retroactively to validate the 22 existing project skills
- The brainstorming companion (WebSocket visual design server, v5.0.0) usefulness
- `dispatching-parallel-agents` rules vs Pattern E — future research spike
- Third-party community skills beyond main Superpowers repo (e.g., `travisvn/awesome-claude-skills`)

---

## Citations (all accessed 2026-05-15)

1. [GitHub — obra/superpowers (canonical)](https://github.com/obra/superpowers)
2. [Superpowers README](https://github.com/obra/superpowers/blob/main/README.md)
3. [Superpowers RELEASE-NOTES](https://github.com/obra/superpowers/blob/main/RELEASE-NOTES.md)
4. [skills directory listing](https://github.com/obra/superpowers/tree/main/skills)
5. [brainstorming SKILL.md](https://github.com/obra/superpowers/blob/main/skills/brainstorming/SKILL.md)
6. [writing-plans SKILL.md](https://github.com/obra/superpowers/blob/main/skills/writing-plans/SKILL.md)
7. [using-superpowers SKILL.md](https://github.com/obra/superpowers/blob/main/skills/using-superpowers/SKILL.md)
8. [subagent-driven-development SKILL.md](https://github.com/obra/superpowers/blob/main/skills/subagent-driven-development/SKILL.md)
9. [Jesse Vincent origin post](https://blog.fsck.com/2025/10/09/superpowers/)
10. [Anthropic plugin listing](https://claude.com/plugins/superpowers)
11. [Mintlify documentation](https://obra-superpowers.mintlify.app/introduction)
12. [obra/superpowers-skills (archived community repo)](https://github.com/obra/superpowers-skills)
13. [star-history rank #26](https://www.star-history.com/obra/superpowers/)
14. [Emelia.io framework overview](https://emelia.io/hub/superpowers-claude-code-framework)
15. [Builder.io blog](https://www.builder.io/blog/claude-code-superpowers-plugin)
16. [DEV Community — combining Superpowers + gstack + GSD](https://dev.to/imaginex/a-claude-code-skills-stack-how-to-combine-superpowers-gstack-and-gsd-without-the-chaos-44b3)
17. [SkillsBench arxiv 2602.12670](https://arxiv.org/html/2602.12670v1) — confirmed Superpowers does NOT cite this

---

## Confidence Calibration

| Finding | Confidence |
|---|---|
| Repository identification (obra/superpowers, MIT, Oct 2025) | **HIGH** — primary GitHub source |
| Star/fork counts (184K / 17K as of May 2026) | **HIGH** — multiple independent sources with real-time variation |
| Full 14-skill catalogue | **HIGH** — direct skills directory fetch |
| Installation via Anthropic plugin marketplace | **HIGH** — README + official marketplace link |
| v5.1.0 current (April 30 2026) | **HIGH** — RELEASE-NOTES direct fetch |
| Active maintenance with strict PR quality bar | **HIGH** — release notes + community sources |
| Superpowers has NO academic citations | **HIGH** — README contains no research citations |
| brainstorm/planning skill mapping detail | **HIGH** — direct SKILL.md fetches both sides |
| Partial adoption recommendation | **MEDIUM** — counter-evidence is real; value depends on whether agent debugging behavior is currently a pain point |
