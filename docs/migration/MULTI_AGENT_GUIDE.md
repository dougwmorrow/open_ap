# Multi-Agent Team Guide

How to organize Claude Code agents for the UDM pipeline project.

## Architecture: subagents vs agent teams

Claude Code distinguishes two coordination models:

### Subagents (we use this)
- Run within the main session, with their own context windows
- Spawned by the main agent via the Agent tool or @-mention
- Results return to the main conversation only
- **Cannot spawn other subagents** (no nesting)
- Best for: focused, self-contained tasks where verbose output should be isolated from the main context

### Agent Teams (experimental)
- Run as **separate Claude Code instances** with full independent sessions
- Communicate peer-to-peer via shared mailbox
- Coordinate via shared task list
- Require `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` env var
- Best for: parallel exploration, competing hypotheses, sustained collaboration

For our project: **start with subagents**. Agent teams are overkill until we hit a bottleneck where multiple agents truly need to collaborate, not just report back.

## Configuration locations (precedence: high → low)

1. **Managed settings** (org-wide, via `.claude/settings/` from admin)
2. **CLI `--agents` flag** (current session only)
3. **`.claude/agents/<name>.md`** (project-scoped, version-controlled)
4. **`~/.claude/agents/<name>.md`** (user-scoped, all projects)
5. **Plugin `agents/` directory** (plugin-distributed)

For our project, we use #3 (`.claude/agents/`).

## File format

Each subagent is a markdown file with YAML frontmatter:

```yaml
---
name: udm-design-reviewer
description: Reviews UDM pipeline architectural changes... use proactively before...
tools: Read, Grep, Glob, Bash
model: sonnet
---

You are an expert in...

(body of the system prompt)
```

### Frontmatter fields

| Field | Required | Notes |
|---|---|---|
| `name` | Yes | lowercase, hyphens (e.g., `udm-design-reviewer`) |
| `description` | Yes | ~50 words; tells Claude when to delegate; include "use proactively when..." |
| `tools` | No | comma-separated; e.g., `Read, Grep, Glob, Bash, Edit, Write` |
| `disallowedTools` | No | denylist if inheriting all tools |
| `model` | No | `sonnet`, `opus`, `haiku`, or specific ID; default inherits |
| `permissionMode` | No | `default`, `acceptEdits`, `auto`, `bypassPermissions`, `plan` |
| `maxTurns` | No | safety bound on iterations |
| `skills` | No | preload skills into context |
| `mcpServers` | No | MCP servers to load |
| `hooks` | No | PreToolUse / PostToolUse hooks |
| `memory` | No | `user`, `project`, or `local` for cross-session memory |
| `background` | No | `true` to always run async |
| `isolation` | No | `worktree` to fork into a git branch |
| `color` | No | `red`, `blue`, etc. for visual distinction |
| `initialPrompt` | No | auto-submit first message when agent runs as main session |

## Our installed agents

| Agent | File | Use when |
|---|---|---|
| **udm-design-reviewer** | `.claude/agents/udm-design-reviewer.md` | Reviewing architectural changes, CDC/SCD2 logic, schema evolution, before locking decisions |
| **udm-test-author** | `.claude/agents/udm-test-author.md` | Authoring unit/property/integration tests; Phase 1 Round 5 onward |
| **udm-researcher** | `.claude/agents/udm-researcher.md` | On-demand: targeted research questions. Proactive: triggered by validation Gate 2 unsupported claims, new edge case mitigations without sources, decision benchmarks lacking citations, "industry-standard" / "best practice" questions. Outputs to `docs/migration/_research/<topic>-<date>.md`. Read-only on primary docs. |

Future agents (deferred until specific phases):

| Agent | Trigger to author |
|---|---|
| `udm-runbook-validator` | After RB-12+ runbooks are written; checks against template enforcement |
| `udm-decision-archivist` | When decision count > 60; reviews superseded decisions for cleanup |
| `udm-power-bi-query-reviewer` | Phase 6 (dashboards) starts |

## Built-in agents we use

| Agent | Source | Use when |
|---|---|---|
| `general-purpose` | Built-in | Open-ended research, multi-step tasks, code searches |
| `Explore` | Built-in | Fast read-only code search; finding files / symbols |
| `Plan` | Built-in | Software architecture planning; implementation strategy |
| `claude-code-guide` | Built-in | Questions about Claude Code itself, plugins, skills |

## Patterns we use

### Pattern A: Parallel research (most common)

When researching a multi-faceted question, spawn multiple agents in **one** Agent tool call message:

```
Agent A: research X
Agent B: research Y  
Agent C: research Z
(all in parallel)
```

Each agent gets independent context. Results return together. Used in this project for:
- Industry standards research (CDC patterns, idempotency patterns, lookback math)
- Skill gathering across sources
- Phase reflection alongside research

**Anti-pattern**: spawning agents sequentially when they're independent. Wastes wall-clock time.

### Pattern B: Specialized review

A custom subagent with deep domain knowledge reviews a specific artifact:

```
1. Author a stored procedure / module / runbook
2. Invoke udm-design-reviewer on it
3. Address findings
4. Re-invoke if substantial changes
```

Used in this project for: SP-1 review (caught the I3 race condition).

### Pattern C: Test-first via specialist

When implementing a function:

```
1. Read function spec / signature
2. Invoke udm-test-author to author tests first (TDD)
3. Run tests (should fail)
4. Implement function
5. Re-run tests (should pass)
6. Invoke udm-design-reviewer for final QA
```

Will be used starting Phase 1 Round 5.

### Pattern D: Reflection / progress check

When deep into a phase, spawn a reflection agent to assess progress:

```
Agent: read all phase docs, identify gaps, recommend next steps
```

Used in this project: Phase 1 reflection that surfaced SP-1 bug, Round 0.5 spike recommendation.

### Pattern E: 5-agent deep validation with research grounding (added 2026-05-10 post-Round-3)

Adopted after Round 3 D72 deep-validation campaign (cycles 4-9, 24 reviewer agents, 12+ real bug catches) demonstrated multi-agent parallel validation's value but with one limitation: findings rest on reviewers' internal knowledge alone. Pattern E adds external-evidence grounding via a 5th research-specialist agent.

**Composition (5-agent batch)**:
1. **Cross-reference audit** (Pitfall #9 sub-classes — column / parameter / enum / type / line citation; cross-table column-name lift surface)
2. **Implementation feasibility** (can downstream rounds consume this artifact's contracts?)
3. **Regression / consistency audit** (does this round's content drift other docs? aggregate-doc state?)
4. **D72 convergence verdict + next-cycle strategy** (CLEAN / NOT CLEAN per D72; recommend cycle-N+1 focus)
5. **Research specialist (NEW)** — external-evidence grounding for findings + claims

**Research specialist (5th slot) mandate**:
- Performs full CCL Stage 1+2 (per D62) like other reviewers
- For each claim in the artifact saying "industry standard", "best practice", "canonical pattern", "deterministic guarantee", etc. — find authoritative external source (vendor docs, NIST, academic, community consensus)
- For each 🔴/🟡 finding from reviewers 1-4 (read other reviewers' outputs OR work independently): look up whether the proposed fix matches external best practices
- Output: `docs/migration/_research/<round>-cycle-<N>-evidence.md` per existing `udm-researcher` convention
- **Advisory, not blocking** — research findings supplement reviewers' reasoning; cycle clean/not-clean verdict comes from reviewers 1-4 only

**When to use Pattern E vs Pattern B (specialized review)**:
- Pattern B: single-review of localized artifact (one stored procedure, one runbook, one decision)
- Pattern E: deep validation of multi-section artifact (a full round's spec doc) under D72 convergence cycle
- Round 3 cycles 4-9 are the precursor pattern; future deep-validation campaigns should adopt Pattern E by default

**Composition with D72**:
- Each Pattern E batch counts as ONE D72 cycle (per D72 counting rule — multi-agent batch = 1 cycle)
- Cycle clean / not clean determined by reviewers 1-4; research output is advisory
- Research findings inform fix-cycle direction but don't reset / advance D72 consecutive-clean counter

### Pattern F: Round-level cascade audit with tiered enforcement (added 2026-05-11 post-Round-6)

Adopted after Round 6 close-out cascade produced 7 structural gaps (B140 false-closure; B86 CLAUDE.md gap; RB-12 forward-cite to non-existent body; HANDOFF §3 L108 stale B-range; 02_PHASES.md + PHASE_1_DEEP_DIVE_PLAN.md multi-round stale; B121 partial closure; D88 acceptance lacking clean verification cycle). Root cause: artifact-level work has 3-tier defense (Pattern E 5-agent + sleeper-bug stress + D72 convergence), but the round close-out cascade had ZERO independent verification — producer self-attests round 🟢 with no Gate-2 equivalent. Pattern F is the structural fix at round level.

Pattern F is structurally distinct from Pattern E:
- **Pattern E** = per-artifact spec doc validation (focuses on spec CONTENT)
- **Pattern F** = per-round cascade audit (focuses on cascade CONSISTENCY across aggregate docs)
- They DO NOT replace each other; both run per round (Pattern E at artifact level, Pattern F at close-out).

**Composition (tiered enforcement)**:

1. **Layer 1 — Deterministic script** (`tools/verify_cascade.py`) covers the 3 mechanical triggers:
   - **Trigger C — stale references**: regex sweep for `B(\d+)-B(\d+)` ranges; `Round N — <name> (next round)` claims where Round N is locked; B-count claims drifted from BACKLOG state
   - **Trigger D — forward-cite resolution**: every `RB-N` / `SP-N` / `B-N` / `D-N` / `R-N` reference resolves to canonical doc anchor; broken refs → 🔴
   - **Trigger F — aggregate-doc freshness**: 02_PHASES.md Phase row + PHASE_1_DEEP_DIVE_PLAN.md Round stubs + HANDOFF §3 in-flight section reflect current locked-Round state
   - Exit codes: 0 clean / 1 🟡 only / 2 🔴 (per D74)
   - 100% deterministic — zero agent variance on text-matching classes

2. **Layer 2 — Paired-judgment agents** (`.claude/agents/udm-cascade-auditor.md` invoked as TWO independent instances) covers the 3 judgment triggers:
   - **Trigger A — D-acceptance substantiation**: every architectural-review acceptance decision (D73/D78/D83/D88 and future) has the substantiating cycle evidence in `_validation_log.md` matching the cited variant (convergence-confirmed vs math-infeasibility)
   - **Trigger B — B-item closure-target audit**: every "CLOSED" BACKLOG entry has its cited target docs actually reflecting the change (the R6 B140 false-closure pattern)
   - **Trigger E — CLAUDE.md convention registration**: when a round defines new conventions (EventType families, SP signatures, Tier classifications), CLAUDE.md project root is updated
   - Findings reports compared by orchestrator; agreement → clean; disagreement on any finding → cascade fix-cycle

**Why paired-judgment (constraint: never trust 1 agent)**:

Round 6 demonstrated that single-agent comprehensive-5-gate audit has confirmed false-clean history (R4C5 + R4C7 per `_reviewer_effectiveness.md`). Pattern E's column-walk specialty achieves 0% false-clean BECAUSE it's narrowly-scoped and paired with cross-reference + internal-consistency reviewers. Pattern F applies the same lesson: deterministic where possible (Layer 1 = no agent variance); paired-independent where judgment is needed (Layer 2). No single agent has unilateral verdict on any trigger.

**When to use Pattern F**:

- MANDATORY at every round close-out, AFTER producer completes the aggregate-doc cascade AND BEFORE round 🟢 lock
- NOT used at artifact level (Pattern E + sleeper-bug stress own that scope)
- NOT used for trivial edits (round close-out IS the trigger — trivial-edit exception does not apply)

**Composition with D72**:
- Pattern F counts as ONE cycle in the round's cycle ledger
- Layer 1 (script) runs once per audit; deterministic verdict
- Layer 2 (paired agents) — both instances run in parallel; their COMBINED verdict counts as one cycle
- 🔴 findings → ONE cascade fix-cycle; second Pattern F audit verifies
- If second audit still 🔴 → architectural-review escalation per D73/D78/D83/D88 precedent

**Cost**: 1 script invocation (~seconds; deterministic; cacheable) + 2 agent invocations per close-out. LIGHTER than Pattern E (5 agents per spec-doc cycle × multiple cycles per round). Structurally correct: round-level discipline backstops artifact-level, not the other way around.

**Forward path (when D54 hooks return)**:
- Layer 1's deterministic checks convert directly to PreToolUse hooks on `Edit`/`Write` (e.g., refuse to edit BACKLOG.md marking B-N CLOSED if target docs cited in description weren't touched in current session)
- Layer 2 (paired agents) remains for judgment classes
- Net effect: Pattern F evolves from "+1 script + 2 agents per close-out" to "zero compute on mechanical triggers + 2 agents on judgment"

**Cross-references**:
- D89 — Pattern F discipline lock (Round 7 close-out target)
- D90 — `udm-cascade-auditor` agent definition lock
- D91 — `tools/verify_cascade.py` contract lock
- R28 — round-level cascade self-attestation gap (the risk Pattern F mitigates)
- HANDOFF §8 Pitfall #11 — first-evidence Round 6 close-out gaps

## Canonical Context Load (CCL) — mandatory for every agent and skill (per D62)

Every custom subagent invocation (via the Agent tool) and every project-local skill invocation MUST perform the Canonical Context Load BEFORE any substantive work — drafting, reviewing, recording, validating, brainstorming.

D60 + D61 added per-discipline read requirements (HANDOFF, NORTH_STAR, RISKS, BACKLOG) to specific agents and skills, but lists drifted: some agents read 8 docs, some read 3, most skills read none. CCL standardizes the read protocol with a verification rule.

### Stage 1 — Orientation (mandatory, 4 reads, before any other Read or substantive tool call)

1. `docs/migration/NORTH_STAR.md` — pillar priority for trade-off resolution
2. `docs/migration/HANDOFF.md` — locked vs in-flight, round history, pitfalls
3. `docs/migration/CURRENT_STATE.md` — what's in-flight right now
4. `docs/migration/CHECKS_AND_BALANCES.md` — the 5-gate validation discipline this work runs under

### Stage 2 — Risk + Backlog awareness (mandatory for review / production work, per D61)

5. `docs/migration/RISKS.md` — surface risk delta in output (per D61)
6. `docs/migration/BACKLOG.md` — propose B-numbers for any 🟡 findings (per D61)
7. `docs/migration/_validation_log.md` — past validation findings; don't contradict, don't re-discover

Skip Stage 2 only for pure-research or doc-orientation tasks.

### Stage 2.5 — Polish queue awareness (recommended for review work, per D113; added 2026-05-12)

7.5. `docs/migration/POLISH_QUEUE.md` — cosmetic / readability tracker (P-numbers); skim 🟡 Open P-N items. Cosmetic-only 🟡 findings (stale supersession crumbs, status-render badge drift, stale dates) propose P-numbers, NOT B-numbers — preserves BACKLOG WSJF view as substantive-work signal. Distinguishing test: does fixing change behavior / decisions / runbooks / SP bodies / code? If NO → P-N candidate.

### Stage 3 — Task-specific reads (varies)

Each agent and skill enumerates its Stage 3 reads in its own definition file. Common patterns:

| Task | Stage 3 reads |
|---|---|
| Design review (CDC/SCD2/schema) | `CLAUDE.md` + `01_ARCHITECTURE.md` + the artifact |
| Test authoring | `06_TESTING.md` + the code under test + existing tests |
| Research | the specific docs the question touches |
| Decision recording | `03_DECISIONS.md` (max D-number) + `NORTH_STAR.md` (re-confirm pillar canonical names) |
| Round close-out | aggregate docs: HANDOFF, CURRENT_STATE, BACKLOG, RISKS, NORTH_STAR, 00_OVERVIEW, 02_PHASES |
| Edge case validation | `04_EDGE_CASES.md` (relevant series) + the artifact |
| Runbook authoring | `05_RUNBOOKS.md` (template + cross-refs) + the related D-number |
| Brainstorm | `03_DECISIONS.md` (existing decisions) + `04_EDGE_CASES.md` (related) + `NORTH_STAR.md` (pillar implications) |
| Planning a round | `02_PHASES.md` + `PHASE_1_DEEP_DIVE_PLAN.md` + current phase's `00_phase_overview.md` |
| Data engineering review | `CLAUDE.md` (project root) + `01_ARCHITECTURE.md` + the artifact |

### Stage 4 — Reference-on-demand (grep, don't full-read)

- `docs/migration/03_DECISIONS.md` — by D-number
- `docs/migration/04_EDGE_CASES.md` — by series prefix (M / S / I / N / P / G / D / F / V) or specific ID
- `docs/migration/05_RUNBOOKS.md` — by RB-number
- `docs/migration/02_PHASES.md` — by phase or deliverable

### Verification rule

The agent's FIRST content-substantive tool call (`Read` or `Grep` with content output) MUST be on a Stage 1 document. Glob-only / filesystem-listing calls (e.g., `Glob` for path discovery) before Stage 1 do not violate the rule — they're orientation, not content. If the trace shows content reads on the artifact-under-review BEFORE Stage 1 reads, the discipline is violated and the output is invalid — re-run from scratch.

Audit cadence: spot-checked at every round close-out; full audit quarterly per `MAINTENANCE.md`.

### Self-edit fallback (when a Stage 1 doc IS the artifact)

If a Stage 1 doc itself is being edited (e.g., adding a pillar to `NORTH_STAR.md`, updating round history in `HANDOFF.md`), the Stage 1 reads still run BEFORE the edit. The artifact-as-target is then implicitly read again under Stage 3 with intent-to-edit framing. The first read counts toward CCL compliance.

### Trivial-task exception

Typo / formatting / 1-line clarification edits skip Stages 1-2. Note the exception in the output: "Trivial edit — CCL Stage 1+2 skipped per exception".

Examples that QUALIFY as trivial:
- Fixing a typo in a section header
- Tightening a sentence's grammar without changing meaning
- Renaming a section heading for consistency
- Bumping a "Last reviewed" date with no other content change

Examples that DO NOT qualify (do the full protocol):
- Adding a new bullet to a list (changes scope)
- Updating a table row's status (changes meaning)
- Adding a 5-line code block, even if "small" (introduces new behavior or constraint)
- Reorganizing a section (changes navigability — affects readers)
- Updating a cross-reference (changes link semantics)

If unsure: it's not trivial. Run the full CCL.

### CCL invocation pattern in subagent prompts

When the main agent spawns a custom subagent, the prompt should include this clause verbatim:

> "Per `docs/migration/MULTI_AGENT_GUIDE.md` § Canonical Context Load (D62), perform the CCL before any substantive work. Your first `Read` MUST be on a Stage 1 doc."

Built-in agents (Explore, Plan, general-purpose, claude-code-guide) are NOT subject to CCL because they don't operate on UDM artifacts. Custom subagents (udm-design-reviewer, udm-test-author, udm-researcher) ARE.

### Why we don't enforce via hooks (yet)

D54 deferred PreToolUse / PostToolUse hooks until production-class data flows. Until then, CCL compliance is honor-system + trace-audit. When hooks return, a `PreToolUse` hook on `Read` could enforce ordering programmatically (block any `Read` not on a Stage 1 doc until the agent has read all four).

### Composition with existing patterns

CCL extends, not replaces:
- **D55 (5-gate validation)** — Gate 2 (QA) reviewer must perform CCL
- **D56 (mandatory second-pass)** — second-pass reviewer must perform CCL (independent agent)
- **D60 (round close-out)** — closeout invocation must perform CCL
- **D61 (NORTH_STAR/RISKS/BACKLOG integration)** — pillar mapping + risk delta + backlog surfacing rely on CCL Stage 1+2 reads

## Anti-patterns

- ❌ **Spawning the same agent twice in parallel** with overlapping prompts. Wastes context.
- ❌ **Empty / generic descriptions.** "Code reviewer" → Claude won't know when to delegate. Use "Reviews X for Y; use proactively when Z" pattern.
- ❌ **Over-constraining tools.** A subagent with `tools: Read` only can't run tests. Allow what the work needs.
- ❌ **Bloated subagents.** One 50KB orchestrator trying to do everything. Anthropic's 2026 guidance: 4-5 specialists max.
- ❌ **Subagent loop.** Subagents can't spawn subagents (architecture prevents). If you need multi-level, chain sequentially from main.
- ❌ **Using subagents for trivial tasks.** A 1-minute fix doesn't need delegation.
- ❌ **Orphaned agent configs.** `.claude/agents/old-agent.md` checked in but unused. Treat agent configs like production code; review when adding/modifying.

## Cost / context implications

Each subagent gets its own context window:

- **Pro**: relief on main context (don't pollute with research output)
- **Con**: each agent costs tokens

Worth delegating when:
- The task produces verbose intermediate output (research, multi-file analysis)
- The task can run in parallel with other work
- The task is specialized (security review, design review)

NOT worth delegating when:
- The task is one tool call deep (just do it in main)
- The task needs lots of back-and-forth with the user
- The agent would essentially echo back what main could compute directly

## Communication between agents

### Within session (subagents)
Subagents return results to main conversation. Main can synthesize and pass to next subagent.

### Across sessions (advanced)
- File-based handoff: agent A writes a file, agent B reads it (we use this for persisted research output)
- Background agents (`run_in_background: true`): notify main when complete

### SendMessage tool
Allows continuing a previous agent's session via its agentId. Useful for follow-up questions to a research agent without re-explaining context.

## Project-specific agent conventions

1. **Every custom agent and project-local skill performs the Canonical Context Load (§ CCL above) before any substantive work.** Stage 1 (NORTH_STAR / HANDOFF / CURRENT_STATE / CHECKS_AND_BALANCES) is mandatory; Stage 2 (RISKS / BACKLOG / _validation_log) is mandatory for review/production work; Stage 3 reads are task-specific and enumerated in each agent/skill definition. The verification rule — agent's first content-substantive tool call (`Read` or `Grep` with content output) must hit a Stage 1 doc — is auditable from the tool trace.
2. **Output format is structured.** Findings categorized by severity (✅ / 🟡 / 🔴 / ⚪) with action items.
3. **Reference D-numbers and edge case IDs.** Vague "this looks bad" is rejected; specific "violates D15 (idempotency)" is required.
4. **Test agents reference `06_TESTING.md` tier definitions.** Tier 1/2/3/4/5 must be specified.
5. **Agents update planning docs.** When an agent finds a new edge case, the agent's recommendation is to add it to `04_EDGE_CASES.md` (not silently log).

## When to author a new agent

Author a new custom agent when:
1. The same review pattern is invoked 3+ times
2. The pattern requires specific domain knowledge that built-in agents don't have
3. The pattern requires reading multiple project-specific docs to be useful

Don't author when:
- The pattern is one-off
- A built-in agent (Plan, Explore, claude-code-guide) suffices
- The pattern is generic (use built-in `/review`)

## Maintenance

- Quarterly review per `MAINTENANCE.md`: are all agents in `.claude/agents/` still in active use?
- After 6 months of disuse, archive the agent (move to `.claude/agents/_archive/`)
- Update agent prompts when CLAUDE.md or `04_EDGE_CASES.md` change in ways that affect their checklist

## Related decisions

- D48 (Project-local skills authored)
- D46 (Skill / plugin evaluation; agents are conceptually similar)
- D17 (Idempotency ledger pattern; agents that touch this should reference it)
- D27 (Cross-server parity; agent configs are part of parity baseline)

## Sources

- code.claude.com/docs/en/sub-agents
- code.claude.com/docs/en/agent-teams
- anthropic.com/engineering/building-agents-with-the-claude-agent-sdk
- paddo.dev/blog/claude-code-hidden-swarm/
