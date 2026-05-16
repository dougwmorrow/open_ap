# Agentic Orchestration Architecture Research

**Date**: 2026-05-16
**Researcher**: udm-researcher (invoked per user-direction "Research first then design")
**Sub-agent inheritance**: per CLAUDE.md hard rule 13 + PLANNING_DISCIPLINE.md §3 — active skills inherited from parent's planning session (udm-researcher only); 16th cumulative production application this 2-day session
**Scope**: 5 topics covering library maturity / production pitfalls / trigger patterns / cost control / discipline-cascade prior art
**Anchor**: parent agent will choose architecture (A/B/C/D from prior presentation OR alternative surfaced by research) based on these findings
**Triggered by**: on-demand (user-direction "Research first then design")

---

## Executive Summary

1. **Option B (Anthropic Claude SDK direct) is the strongest fit for this project**, not LangGraph. The project already runs inside Claude Code, uses subagents/skills natively, and the target workflow is a bounded 4-step cascade — not a sprawling stateful graph requiring LangGraph's complexity premium. The SDK's native hooks (PreToolUse, PostToolUse, Stop, TaskCompleted) provide the trigger layer without a framework abstraction.

2. **Claude Code hooks are the canonical 2026 trigger mechanism** for developer-tool agentic workflows. They fire deterministically at tool-use boundaries, can block actions (exit code 2), inject context into Claude's reasoning, and are already present in the project's settings infrastructure.

3. **The dominant production failure mode is unbounded cost from recursive loops** — a $47,000 incident from an 11-day undetected loop is the most-cited empirical case. The mitigation is always the same: hard per-invocation token budgets + explicit termination conditions + circuit-breaker agent monitoring for repeated outputs.

4. **LangGraph is the right choice only if state complexity genuinely requires it**: time-travel debugging, complex branching with human-in-the-loop at each node, and cross-session resumption. For a sequential 4-step cascade with bounded scope, LangGraph adds framework overhead (mandatory LangSmith at $39/seat/month, 126K-star community but also complexity) without commensurate benefit.

5. **Multi-agent token economics are brutal at scale**: orchestration systems "burn roughly 15x the tokens of chat interactions" (Anthropic research team, cited in production survey). The cascade must use prompt caching + Haiku-for-tracking-steps model routing to stay within the $120K/year North Star ceiling.

6. **Prior art exists** for the Plan→Execute→Verify→Track pattern: GitHub Agentic Workflows (Continuous AI, February 2025), Greptile v3 (autonomous code review using Anthropic Claude Agent SDK), and the emerging AC/DC (Agent-Centric Development Cycle) model all implement structured agentic validation cascades. This pattern is recognized but not yet commoditized — the project's specific discipline cascade is genuinely novel in its audit-grade traceability requirements.

7. **The MCP + A2A protocol stack is now the 2026 industry standard** for agent coordination. MCP (vertical: agent-to-tools) has 97M monthly downloads and is supported by every major AI vendor. The project should adopt MCP as its tool-integration layer and use Claude's native subagent spawning for agent-to-agent coordination rather than a separate A2A implementation.

---

## Topic 1: Library Maturity Comparison

### LangGraph (LangChain)

**Current version + release date**: v1.1.6 as of April 10, 2026; v1.1.3 added distributed runtime support and deep agent templates.

**Production-readiness signals**: 126,000 GitHub stars as of April 2026 (highest in class). 27,100 monthly searches. Production deployments at Meta (Ranking Engineer Agent — doubled average model accuracy across 6 models), S&P Global's Kensho, Exa's deep research system (hundreds of queries/day, 15s–3min latency). LangSmith observability is deeply integrated.

**Architectural model**: Directed graphs with typed state. Nodes are agents or tools; edges are transitions (conditional or unconditional). The "low-level workhorse" for complex, branching, stateful workflows. Graph state is fully serializable — enabling time-travel debugging and crash resume.

**State management**: First-class typed state. Built-in checkpointing with configurable backends (SQLite, Postgres). Time-travel debugging allows replaying any historical graph state. Agents can crash and resume from the last checkpoint without re-running prior steps.

**Cost overhead**: Framework itself is MIT-licensed and free. LangSmith observability required for production: $39/seat/month for the Plus tier. No LLM provider markup — calls go directly to the provider. Tool-call token overhead: 300–700 extra input tokens per tool-enabled request (same as direct SDK). Multi-agent overhead: orchestration agents burn "roughly 15x the tokens of chat interactions."

**Anthropic integration**: Fully model-agnostic. Anthropic models work as any other LLM provider via the `langchain-anthropic` package. Not Anthropic-first — Claude Code features (subagents, hooks, skills, MCP) are NOT natively accessible through LangGraph without custom integration.

**Multi-agent coordination primitives**: Parallel node execution (fan-out/fan-in), sequential chains, conditional branching, human-in-the-loop interrupts at any node boundary, supervisor patterns, and streaming at node and token level.

**Failure handling**: Retry policies per node, rollback via checkpoint restore, graph-level exception handling, human escalation at interrupt nodes. The "From Spark to Fire" research paper found that one falsehood injected at the hub produces 100% system failure in LangGraph versus 9.7% from leaf injection — hub fragility is the primary structural risk.

**Observability**: LangSmith provides traces, cost tracking, latency (P50/P99), error rates, feedback scores, custom dashboards, and alerts. Deep integration — LangSmith is effectively mandatory for production LangGraph deployments.

**Relevance to this project**: LangGraph is the right tool when workflow branching is complex and state must survive session boundaries. The 4-step discipline cascade is sequential, bounded, and single-session — LangGraph's complexity premium is unwarranted.

---

### CrewAI

**Current version + release date**: v1.14 as of 2026. The 1.9.x releases added SqliteProvider checkpointing.

**Production-readiness signals**: 40,000+ GitHub stars by early 2026. 14,800 monthly searches. Fastest-growing multi-agent framework in 2026. Positioned as rapid-prototyping tool; production readiness rated "medium" by multiple comparative analyses.

**Architectural model**: Role-based "crews" with three process types: sequential, hierarchical, and consensual. Agents have explicit roles (Researcher, Writer, Reviewer), goals, and backstory prompts. Abstracts orchestration details — lower ceiling but lower floor.

**State management**: Task outputs passed sequentially between agents. Limited checkpointing (SqliteProvider in recent versions). Less visibility into state when failures occur versus LangGraph.

**Cost overhead**: Free tier available; enterprise plans at $25+/month. No LLM provider markup. Limited streaming support compared to competitors.

**Anthropic integration**: Fully model-agnostic. Same limitation as LangGraph — Claude Code native features (hooks, skills, subagents) not accessible without custom integration.

**Failure handling**: Weaker than LangGraph. Failures may leave task state ambiguous. Less visibility into what happened inside a failed crew run.

**Assessment**: CrewAI is appropriate for rapid prototyping of role-based multi-agent tasks. For the project's audit-grade traceability requirements (every discipline event logged to `_validation_log.md`, every tracker updated), CrewAI's abstracted state management creates blind spots. **Not recommended** for this project.

---

### Microsoft Agent Framework (formerly AutoGen)

**Current version + release date**: Microsoft Agent Framework 1.0 GA shipped April 3, 2026 — the production-ready convergence of Semantic Kernel and AutoGen. AutoGen itself is now in maintenance mode (no new features); existing AutoGen users are encouraged to migrate.

**Production-readiness signals**: Microsoft Agent Framework is 1.0 with production-stable multi-agent workflows. AutoGen's GitHub star count: not directly cited; AG2 fork has 4,200 stars. Enterprise adoption through Azure integration.

**Architectural model**: Microsoft Agent Framework provides stable support for sequential, concurrent, handoff, group chat, and Magentic-One patterns. AG2 (the open-source AutoGen fork) uses conversation-based group chat where a selector determines speaker order. AutoGen's conversational model means every agent turn involves a full LLM call — high token consumption.

**State management**: Microsoft Agent Framework adds session-based state management from Semantic Kernel. AutoGen/AG2 has weaker built-in state management.

**Cost overhead**: AG2 is completely free (Apache 2.0). Microsoft Agent Framework pricing tied to Azure consumption. High token burn in multi-round conversational patterns.

**Anthropic integration**: Works with any model provider including Claude. No Claude Code native feature access.

**Assessment**: Valuable in .NET/Azure-first shops. For a Python-first, Anthropic-native project running inside Claude Code, the migration overhead from AutoGen + the lack of Claude Code integration makes this a poor fit.

---

### Anthropic Claude Agent SDK / Claude Code Native

**Announcement date**: September 29, 2025 (blog post). Claude Managed Agents entered public beta April 2026.

**Current version**: Claude Code v2.1.32+ required for Agent Teams. Agent Teams flagged as experimental (disabled by default; enable via `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS = 1`).

**Production-readiness signals**: Claude Code powers Anthropic's own internal deployments. Greptile v3 (autonomous code review tool) uses the Anthropic Claude Agent SDK in production with a 256% better upvote/downvote ratio. Multi-agent Opus 4 + Sonnet 4 systems outperformed single-agent Opus 4 by 90.2% on Anthropic's internal research evaluation. Meta uses the hub-and-spoke pattern with Claude in production (tribal-knowledge precompute: 50+ specialized agents, 59 durable context files, 40% fewer tool calls).

**Architectural model**: Two options within Claude Code:

- **Subagents** (Task tool): spawn helper agents for bounded tasks. Subagent runs in its own context window; results returned to calling agent. Main agent manages all work. Lower token cost — results summarized back to main context. Best for focused, sequential tasks.

- **Agent Teams** (experimental): teammates run as independent Claude Code instances with a shared task list and direct inter-agent messaging (mailbox). Lead manages task assignment; teammates self-claim from the shared list. Task state stored locally at `~/.claude/teams/{team-name}/config.json` and `~/.claude/tasks/{team-name}/`. File locking prevents race conditions on task claiming.

**State management**: Filesystem as context store — the project's `docs/migration/` directory structure IS the state store. Automatic context compaction (summarizes when context limit approaches). Subagent isolation: subagents load project context (CLAUDE.md, MCP servers, skills) from their working directory. Agent Teams share a task list; teammate communication via mailbox.

**Cost overhead**: No framework overhead — calls go directly to Anthropic's API. Significant token cost: agent teams "use significantly more tokens than a single session; token usage scales with the number of active teammates." For the cascade use case, subagents (not full teams) are the appropriate choice — lower overhead.

**Anthropic integration**: First-class. All Claude Code features (hooks, skills, MCP servers, subagent definitions, CLAUDE.md context, permission settings) work natively. Claude Managed Agents (April 2026 public beta) provides hosted runtime for stateful, long-running sessions.

**Multi-agent coordination primitives**: Parallel subagent spawning (via Task tool), sequential discipline cascade (via skill invocation), conditional branching (via LLM reasoning), hooks at tool-use boundaries (PreToolUse/PostToolUse/Stop/TaskCompleted/TeammateIdle).

**Failure handling**: Three verification approaches documented: rules-based feedback (clearly defined rules + which rules failed), visual feedback (screenshots via Playwright MCP), LLM-as-judge (noted as "generally not a very robust method"). Hook-based circuit breakers: exit code 2 from any hook blocks the triggering action and sends feedback to Claude. TeammateIdle hook fires when a teammate goes idle — exit code 2 sends feedback and keeps the teammate working.

**Observability**: No built-in cost tracking (unlike LangSmith). Requires external tooling (Langfuse, LangSmith, or custom logging). The project's existing `General.ops.PipelineEventLog` + `General.ops.PipelineLog` infrastructure can serve as the observability layer without third-party dependencies.

---

### Summary Comparison Table

| Dimension | LangGraph | CrewAI | MS Agent Framework | Claude Code Native |
|---|---|---|---|---|
| Version (2026) | v1.1.6 | v1.14 | 1.0 GA | CC v2.1.32+ |
| GitHub Stars | 126,000 | 40,000+ | 4,200 (AG2) | N/A (product) |
| Production Ready | High | Medium | High (MS Agent FW) | High (subagents); Experimental (Teams) |
| Architectural model | Directed graph | Role-based crew | Sequential/concurrent/group | Subagent + Teams |
| State management | Typed, checkpointed | Limited | Session-based | Filesystem + task list |
| Cost overhead (platform) | $39/seat/month (LangSmith) | $25+/month (enterprise) | Azure consumption | $0 (direct API) |
| Anthropic integration | Via langchain-anthropic | Via any LLM | Via any LLM | First-class native |
| Hooks/triggers | Custom via nodes | None native | Middleware | PreToolUse/PostToolUse/Stop/TaskCompleted |
| Fit for this project | Low (complexity mismatch) | Low (audit blind spots) | Low (Azure-first) | High |

---

## Topic 2: Production Multi-Agent System Pitfalls

### Pitfall 1: Cost Runaway from Recursive Loops

**Empirical evidence**: A multi-agent research tool slipped into a recursive loop running for 11 days, undetected, resulting in a $47,000 API bill. GitHub reported a sub-agent stuck in an infinite loop consuming 27 million tokens (Issue #15909, 2025). Agentic resource exhaustion is now classified as a distinct attack vector by OWASP (ASI08 — Cascading Failures in Agentic AI).

**Mechanism**: Two agents with conflicting directives or complementary validation patterns can enter a "Mirror Mirror" loop — each agent corrects the other's output endlessly. In multi-turn execution, early mistakes are recursively incorporated into subsequent reasoning (trajectory-level drift).

**Cascade relevance**: HIGH. If the Verify agent finds a problem and re-triggers the Execute agent, which re-triggers Verify, the loop is unbounded without a stop condition.

**Mitigation (canonical)**:
- Hard per-invocation token budget (e.g., `max_tokens` parameter in API call or `--max-tokens` flag)
- Explicit iteration ceiling (e.g., `MAX_CASCADE_CYCLES = 3` constant)
- State hash check: if 95% semantically similar outputs repeat 3 times, terminate and escalate to human
- Circuit-breaker agent (small, cheap model monitoring for stalled progress)
- Claude Code hook: PostToolUse on Write events checking if the same doc was modified more than N times in one session

---

### Pitfall 2: Hallucination Compounding (Error Propagation Cascade)

**Empirical evidence**: The MIT cascade result found that adding relay stages without new information degraded GPT-4.1-mini accuracy from 90.7% (one stage) to 22.5% (five stages) — below random chance. Prose relay degraded accuracy by 8.5 points per stage versus 2.8 points for structured formats. Multi-agent visual hallucination snowballing research (arXiv 2509.21789) shows visual misinterpretations amplify as information flows through subsequent agents, producing "catastrophic hallucination snowballing."

**Mechanism**: Agent A produces a plausible-looking but wrong output. Agent B receives it as "fact" and builds on it. Agent C compounds further. The MAST failure taxonomy (validated across 1,600+ execution traces at NeurIPS 2025) maps 14 failure modes: 41.77% from specification ambiguity, 36.94% from coordination breakdowns, 21.30% from verification gaps.

**Cascade relevance**: MEDIUM. The discipline cascade is sequential (Plan → Execute → Verify → Track). If the Plan agent produces an ambiguous scope, all downstream agents operate on a flawed foundation.

**Mitigation**:
- Use structured output formats (JSON schemas, not prose) for inter-agent communication — structured formats degrade accuracy by only 2.8 points/stage vs 8.5 for prose
- Verification agent must have access to canonical sources (docs/migration/ files) rather than relying on Execute agent's summary
- Mandatory human review gate between Verify and Track for any 🔴 finding
- "Auditor doesn't prepare the books" principle (Greptile): the review agent must be independent from the authoring agent

---

### Pitfall 3: Context Window Pollution (State Explosion)

**Empirical evidence**: Without context management techniques (summarization, observation masking), costs increase proportionally with context length. Research shows applying context management reduces costs by ~50% without significantly degrading task performance, yet most multi-agent deployments skip these techniques. Context drift — old goals lingering after conditions change — compounds with every step in long-running systems.

**Mechanism**: Each agent in the cascade reads prior agents' full outputs. After several cycles, the cumulative context exceeds the model's practical reasoning capacity — even if it technically fits within the context window, reasoning quality degrades.

**Cascade relevance**: HIGH. The project's `docs/migration/` corpus is already large (CLAUDE.md alone is multi-thousand tokens). A cascade that loads CURRENT_STATE.md + HANDOFF.md + BACKLOG.md + RISKS.md + the artifact under review + prior cascade outputs will hit degraded-reasoning territory quickly.

**Mitigation**:
- Canonical Context Load (CCL) is already the project's mitigation for this — load only the stage-specific documents, not the full corpus
- Each cascade agent gets a minimal context brief (not the full prior agent conversation)
- Use prompt caching for stable documents (NORTH_STAR.md, HANDOFF.md static sections) — 90% cost reduction on cached reads
- SessionStart hooks with `compact` matcher to re-inject critical context after compaction

---

### Pitfall 4: Trigger Loops (Agent Output Triggers Same Agent)

**Empirical evidence**: Generic trigger configuration creates infinite loops when agents update the same records they monitor. The Assignment Group pattern was developed specifically to resolve this (modify the assignment group during processing so the completion event doesn't re-trigger the same workflow).

**Cascade relevance**: CRITICAL. If the Track agent writes to `_validation_log.md` and there is a PostToolUse hook on Write events that re-triggers the Plan agent, the system enters an infinite loop.

**Mitigation**:
- Write sentinel files to mark cascade-in-progress (e.g., `.cascade_lock`)
- Use explicit trigger conditions in hook matchers — target only specific tool names or file paths, NOT catch-all matchers
- Track agent writes only to designated output paths (e.g., `_validation_log.md`) with a hook that explicitly ignores writes from within a cascade session
- Session ID–based deduplication: each cascade run has a unique ID; hooks check if the current session ID matches an in-progress cascade before re-triggering

---

### Pitfall 5: Race Conditions in Parallel Agents

**Empirical evidence**: Agent Teams documentation explicitly notes task claiming uses file locking to prevent race conditions when multiple teammates try to claim the same task simultaneously. Teammates should not edit the same file concurrently (leads to overwrites).

**Cascade relevance**: LOW for sequential 4-step cascade. MEDIUM if the cascade spawns parallel subagents in the Verify step (e.g., multiple reviewers running simultaneously and writing to the same `_validation_log.md`).

**Mitigation**:
- Keep the cascade sequential for the primary flow (Plan → Execute → Verify → Track)
- If Verify spawns parallel sub-reviewers, each writes to a temporary file; Track agent merges results into `_validation_log.md`
- Use append-only semantics for all cascade output files (consistent with the project's existing `_validation_log.md` discipline)

---

### Pitfall 6: Hub Fragility in Orchestration Patterns

**Empirical evidence**: The "From Spark to Fire" research showed one falsehood at the hub produces 100% system failure in LangGraph versus 9.7% from leaf injection. 40% of multi-agent pilots fail within six months of production deployment.

**Cascade relevance**: HIGH if a central orchestrator manages all cascade steps. If the Plan agent produces a corrupted scope definition, all subsequent agents work on a flawed foundation.

**Mitigation**:
- Use validated schema output from the Plan agent (the parent agent validates the plan against NORTH_STAR.md and CHECKS_AND_BALANCES.md before triggering Execute)
- Plan approval gate: the TeammateIdle or TaskCompleted hook can block plan completion if required fields are missing
- Structured plan format: JSON with required fields (scope, artifact_path, pillar_mapping, b_items_to_close) — fail fast if schema invalid

---

## Topic 3: Trigger + Execution Patterns

### Option A: Git Hooks (pre-commit / post-commit)

**Mechanism**: Shell scripts in `.git/hooks/` or managed via `pre-commit` framework. Fire on commit events. The hook script invokes `claude -p` or the Anthropic SDK to run a cascade agent.

**Latency**: Synchronous — blocks the commit until complete. For a full Plan→Execute→Verify→Track cascade (estimated 5–20 minutes), this is unusable for routine commits. Appropriate only for lightweight checks (e.g., `pre-commit` running `verify_tier0_drift.py`).

**2026-canonical?**: Git hooks are NOT the canonical pattern for full agentic cascades in 2026. They are canonical for deterministic linters and formatters. GitHub Agentic Workflows (announced February 2025, production 2026) explicitly moves agentic work INTO the CI runner, not into git hooks, precisely because hooks block the developer's workflow.

**Recommendation**: Use git hooks ONLY for the lightweight deterministic checks (Layer 1 of Pattern F: `tools/verify_cascade.py`). Do NOT use git hooks for the full multi-agent cascade.

---

### Option B: CLI Invocation (manual or alias)

**Mechanism**: Developer runs `python cascade.py --trigger post-build` or an alias in the shell. The cascade script invokes Claude API calls in sequence (Plan → Execute → Verify → Track), each as a separate API call with appropriate context.

**Latency**: Asynchronous (developer-initiated). Developer can go do other work while cascade runs. Output written to files; developer reviews when done.

**2026-canonical?**: This is the most mature and proven pattern for agentic developer tools in 2026. Anthropic's own documentation for Claude Code subagents, agent teams, and skill invocation all use CLI as the primary interface. Every Round 3–6 tool in this project already uses this pattern (`python tools/verify_tier0_drift.py`, `python tools/parquet_verify.py`, etc.).

**Integration with Claude Code**: `claude -p "invoke udm-next-step-cascade"` invokes the cascade as a single Claude Code session. Within that session, the cascade skill can spawn subagents for each step. Alternatively, `claude --skill udm-plan-agent` invokes a skill directly.

**Recommendation**: **This is the primary trigger pattern for this project.** Simple, auditable, no infrastructure overhead, consistent with existing patterns.

---

### Option C: Claude Code Hooks (PostToolUse, Stop, TaskCompleted)

**Mechanism**: Shell commands registered in `.claude/settings.json` that fire automatically at specific Claude Code lifecycle events. These ARE already present in the project's infrastructure.

**Available hook events**:
- `PreToolUse`: fires before a tool executes; exit code 2 blocks the action
- `PostToolUse`: fires after a tool executes (cannot undo); perfect for post-validation
- `Stop`: fires when Claude finishes a response; can inject continuation prompt
- `Notification`: fires when Claude needs input (idle, permission prompt, etc.)
- `SessionStart`: fires at session start (with `compact` matcher: after context compaction)
- `ConfigChange`: fires when config files change
- `CwdChanged`: fires when working directory changes
- `TeammateIdle`: fires when an agent team teammate goes idle; exit code 2 keeps them working
- `TaskCreated`: fires when a team task is created; exit code 2 blocks creation
- `TaskCompleted`: fires when a task is marked complete; exit code 2 blocks completion

**Cascade relevance**: Hooks can implement quality gates at task boundaries. Example: `TaskCompleted` hook checks that `_validation_log.md` was updated before allowing the Track step to mark "done." `Stop` hook after the Execute agent writes files can automatically invoke the Verify agent.

**Recommendation**: Use hooks as quality gates WITHIN a cascade run (not as the primary trigger). The `Stop` hook after each step can enforce the hand-off to the next step. The `PreToolUse` hook can block writes to protected docs (NORTH_STAR.md, 03_DECISIONS.md) from cascade agents that should only write to `_research/` or `_validation_log.md`.

---

### Option D: CI/CD Pipeline (GitHub Actions / GitLab CI)

**Mechanism**: A YAML pipeline that runs on push/PR events, invokes `claude -p` or a cascade script in a runner, and writes results back (PR comments, status checks, artifact uploads).

**Latency**: Triggered on push; runs in cloud runner. Results visible in PR within minutes.

**2026-canonical?**: GitHub Agentic Workflows (February 2025, production 2026) explicitly positions this as the canonical enterprise pattern. The trigger can be any CI event: push, label change, PR comment, cron, webhook.

**Project applicability**: The project runs on RHEL Linux with Automic as the scheduler (D109). There is no GitHub Actions infrastructure currently in scope. Adapting to Automic-scheduled triggers is possible but adds a new infrastructure dependency.

**Recommendation**: DEFER. The project's Automic scheduler (D109) can invoke a CLI cascade script on a scheduled trigger — this is the CI/CD pattern adapted to the project's existing infrastructure, without requiring GitHub Actions.

---

### 2026-Canonical Recommendation for This Project

The canonical trigger pattern for this project is **CLI invocation with hooks as quality gates**:
1. Developer (or Automic scheduler) runs `python tools/cascade.py --step post-build` (or equivalent)
2. The cascade script invokes Claude Code sessions sequentially (Plan → Execute → Verify → Track), each as a subprocess call to `claude -p`
3. Hooks enforce quality gates at each step boundary: `TaskCompleted` blocks progression if required tracker updates are missing; `PreToolUse` blocks writes to protected documents from non-authorized agents
4. Cost guard: each `claude -p` invocation includes `--max-tokens N` to cap per-step token spend

---

## Topic 4: Cost Control + Observability

### Anthropic Pricing (May 2026)

| Model | Input (per 1M tokens) | Output (per 1M tokens) | Best for |
|---|---|---|---|
| Claude Haiku 4.5 | $1.00 | $5.00 | Tracking, simple validation |
| Claude Sonnet 4.6 (current) | $3.00 | $15.00 | Execute, Verify |
| Claude Opus 4.7 | $5.00 | $25.00 | Complex planning |

**Prompt caching**: 90% reduction on cached input tokens (cache reads at 0.1x input rate; cache writes at 1.25x one-time cost). Cache the stable portions of CLAUDE.md, HANDOFF.md, NORTH_STAR.md — these change infrequently.

**Batch API**: 50% off all models for non-time-critical work. The Track step (writing to markdown trackers) could use batch API if latency is not critical.

**Model routing for the cascade**:
- **Plan** step: Sonnet 4.6 (needs reasoning; Haiku too weak for scope-setting)
- **Execute** step: Sonnet 4.6 (the production model for this project per CLAUDE.md)
- **Verify** step: Sonnet 4.6 (independent reviewer needs same capability as executor)
- **Track** step: Haiku 4.5 (mechanical tracker updates; structured output; cheap)

**Estimated per-cascade token budget** (conservative):
- Plan: ~15,000 input + ~3,000 output = ~$0.09 (Sonnet)
- Execute: ~20,000 input + ~5,000 output = ~$0.135 (Sonnet)
- Verify: ~25,000 input + ~4,000 output = ~$0.135 (Sonnet)
- Track: ~5,000 input + ~1,500 output = ~$0.013 (Haiku)
- **Total per cascade run (uncached)**: ~$0.37
- **With prompt caching on stable docs (~60% of input)**: ~$0.18

At 2 cascade runs/day (AM + PM Automic schedule per D109): ~$0.36/day = ~$131/year. Well within the $120K Snowflake ceiling (cascade costs are negligible relative to compute).

### Observability

**Langfuse** (open-source; acquired by ClickHouse January 2026 with $400M Series D): Best for self-hosted deployments. Captures every LLM call as a trace with token counts, model identifiers, latency, and cost. Attribution by user, session, or custom dimension. Observability-first: logs and dashboards spend rather than enforcing it.

**LangSmith** (paid; $39/seat/month Plus): Best if deep in the LangGraph ecosystem. Real-time monitoring with alerts for latency spikes, error rates, cost anomalies.

**Bifrost** (open-source AI gateway): The only tool enforcing LLM cost controls in the request path itself — blocks requests before provider call if any budget cap is exhausted. Four independent scope levels.

**Recommendation for this project**: The project already has `General.ops.PipelineEventLog` and `General.ops.PipelineLog` as the observability infrastructure. Every CLI tool (D74–D76 contract) already writes a `CLI_*` audit row. Extend this pattern: each cascade agent writes a `CASCADE_PLAN` / `CASCADE_EXECUTE` / `CASCADE_VERIFY` / `CASCADE_TRACK` event with token counts + model + duration. No third-party dependency required. This is consistent with the North Star's operational stability pillar (no new infrastructure without proven need).

**Per-invocation token budget enforcement**: Pass `--max-tokens N` per `claude -p` subprocess call. Hard cap prevents runaway. Log the cap value in the `CASCADE_*` event's metadata JSON for audit.

---

## Topic 5: Discipline-Cascade Prior Art

### GitHub Agentic Workflows (Continuous AI)

**Source**: GitHub Blog, February 2025 announcement; production by 2026. InfoQ coverage February 2026.

**Mechanism**: GitHub embeds AI agents directly into CI/CD runner execution model. Trigger on any CI event: issue, label change, PR comment, cron, webhook. The ChatOps pattern (`/security-review` command in PR comment) gives teams opt-in control. Agent runs inside an isolated container with a built-in network firewall (Squid proxy, explicit domain allowlist). Agent produces structured artifacts describing intended actions; a separate job with scoped write permissions applies only what the workflow explicitly permits.

**Relevance to cascade**: GitHub's "Planner Agent" + "Security Analyst Agent" implement a 2-step Plan→Verify pattern. The project's 4-step cascade is an extension of this pattern with explicit tracker updates as a first-class step. The project's cascade is architecturally parallel but richer (audit-grade traceability requirements; multi-doc tracker updates; existing D55/D56 validation discipline integration).

**Learning**: The "agent cannot write to GitHub directly — produces structured artifacts" pattern is directly applicable. The cascade's Execute and Track agents should produce structured JSON artifacts describing intended changes; a final apply step materializes them. This prevents partial writes from corrupting primary docs.

---

### Greptile v3 (Autonomous Code Review via Anthropic Claude Agent SDK)

**Source**: Greptile blog, November 2025.

**Mechanism**: Complete rewrite of code review workflow using Anthropic Claude Agent SDK. Indexes entire repository, builds a code graph, uses multi-hop investigation to trace dependencies. 256% better upvote/downvote ratios; 70.5% higher acceptance rates versus v2. Key design principle: "The review agent must be independent from the coding agent — an auditor doesn't prepare the books."

**Relevance to cascade**: The D55/D56 "producer ≠ reviewer" principle the project already enforces is validated by Greptile's empirical data. The cascade's Verify step MUST be an independent agent invocation, not a self-review by the Execute agent. Greptile uses the Anthropic Claude Agent SDK directly (not LangGraph), validating Option B for production-grade quality-gate workflows.

---

### AC/DC (Agent-Centric Development Cycle)

**Source**: Security Boulevard, March 2026.

**Mechanism**: Emerging model describing inner loop (agent generates, verifies, iterates) and outer loop (planning, integration, release). Inner loop: Plan → Generate → Verify → Solve. Outer loop: sprint planning, cross-agent integration, deployment validation. The model explicitly separates planning from generation from verification.

**Relevance to cascade**: The AC/DC model is the closest published prior art to the project's Plan→Execute→Verify→Track discipline cascade. The project's "Track" step (updating markdown trackers) is an addition that existing AC/DC models don't formalize — this step reflects the project's unique audit-grade traceability requirement (every change logged to `_validation_log.md` immediately per the progress-logger discipline).

**Assessment**: The project's 4-step cascade with mandatory tracking is genuinely novel relative to published prior art. The 3-step Plan→Execute→Verify pattern is recognized and validated by multiple sources. The mandatory Track step with specific tracker routing (BACKLOG.md, CODE_BUILD_STATUS.md, `_validation_log.md`, ONE_OFF_SCRIPTS.md) is the project-specific innovation.

---

### Stripe Minions (1,000+ PRs/week)

**Source**: Referenced in multiple 2026 CI/CD agentic workflow analyses.

**Scale signal**: Stripe's Minions produce 1,000+ merged PRs/week via autonomous agents. This validates that agentic code workflows can reach production scale but provides limited architectural detail for replication.

---

## Recommended Architecture

Based on the research findings, the recommended architecture is **Option B (Anthropic Claude SDK / Claude Code Native)** with hooks as the quality-gate layer. This is not exactly any of the four options presented by the parent agent — it is a hybrid that uses Claude Code's native primitives without a framework abstraction layer.

**Specific design**:

**Trigger layer**: Manual CLI invocation + Automic-scheduled invocation. Two modes: (1) developer runs `python tools/cascade.py --trigger post-build --artifact <path>` at will; (2) Automic job runs it on schedule (mirroring D109's AM/PM cadence). No git hooks for the full cascade — only for deterministic pre-commit checks.

**Agent topology**: Sequential hub-and-spoke (not parallel mesh). A lightweight Python orchestrator script calls `claude -p` sequentially, passing structured JSON context between steps. Each step is an isolated Claude Code session (own context window, own CLAUDE.md load, per-step token budget).

```
cascade.py orchestrator (Python subprocess controller)
    |
    +-- Step 1: Plan agent       (Sonnet 4.6, max_tokens=4000)
    |   reads: CURRENT_STATE.md + artifact path + scope
    |   writes: cascade_plan.json (structured: scope, pillar, b_items, artifact)
    |
    +-- Step 2: Execute agent    (Sonnet 4.6, max_tokens=8000)
    |   reads: cascade_plan.json + artifact + relevant primary docs
    |   writes: changes to artifact + cascade_execute_result.json
    |
    +-- Step 3: Verify agent     (Sonnet 4.6, max_tokens=6000)
    |   reads: cascade_plan.json + cascade_execute_result.json + D55 gates
    |   writes: cascade_verify_result.json (verdict: GREEN/YELLOW/RED + findings)
    |   GATE: RED verdict -> human escalation + STOP
    |
    +-- Step 4: Track agent      (Haiku 4.5, max_tokens=3000)
        reads: cascade_verify_result.json + tracker routing table
        writes: _validation_log.md + BACKLOG.md + CODE_BUILD_STATUS.md
```

**State shape** (cascade_plan.json):
```json
{
  "cascade_id": "uuid",
  "trigger": "post-build|scheduled|manual",
  "artifact_path": "docs/migration/...",
  "scope": "B-270 closed via crash injection hooks",
  "pillar_mapping": ["operationally-stable", "idempotent"],
  "b_items_to_close": ["B-270"],
  "initiated_by": "dougmorrow@protonmail.com",
  "plan_timestamp": "2026-05-16T...",
  "max_tokens_per_step": {"plan": 4000, "execute": 8000, "verify": 6000, "track": 3000}
}
```

**Hook quality gates** (`.claude/settings.json`):
```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write",
        "hooks": [{
          "type": "command",
          "command": ".claude/hooks/cascade-protect-primary-docs.sh"
        }]
      }
    ],
    "TaskCompleted": [
      {
        "hooks": [{
          "type": "command",
          "command": ".claude/hooks/cascade-require-validation-log-update.sh"
        }]
      }
    ]
  }
}
```

**Cost guard**: Each `claude -p` subprocess includes `--max-tokens N` per step. Cascade script reads token usage from API response and logs to `CASCADE_*` event in PipelineEventLog. Hard stop if cumulative cascade cost exceeds `$5.00` (kill-switch).

**Loop prevention**: Cascade script writes `.cascade_lock` sentinel before Step 1; removes after Step 4 completion or on error. Hook script checks sentinel before re-triggering. Cascade ID logged to prevent duplicate runs on same artifact within a session.

---

## Confidence Assessment

| Topic | Recommendation | Confidence | Primary Sources |
|---|---|---|---|
| Framework choice (Topic 1) | Claude Code Native | HIGH — 3+ corroborating sources confirm native integration advantage | Anthropic SDK blog (9/2025), Claude Code docs (current), Greptile v3 case study |
| Pitfall: cost runaway | Hard token budget per step | HIGH — empirical $47K incident + GitHub 27M-token loop | Multiple incident reports, OWASP ASI08 |
| Pitfall: hallucination compounding | Structured inter-agent format | HIGH — MIT cascade result is primary-source empirical data | arXiv 2509.21789, MIT study cited in production survey |
| Pitfall: trigger loops | Sentinel file + hook matcher specificity | MEDIUM — logical mitigation; no direct empirical evidence for this exact pattern | Cognizant whitepaper, ServiceNow pattern docs |
| Trigger pattern (Topic 3) | CLI + hooks | HIGH — consistent with existing project patterns + 2026 GitHub Agentic Workflows direction | GitHub Blog, Claude Code hooks docs |
| Cost estimate | ~$0.18/cascade run (cached) | MEDIUM — based on current pricing + typical cascade context sizes; actual usage may vary | Anthropic pricing docs (current), finout.io pricing guide |
| Prior art (Topic 5) | AC/DC model closest match; Track step is novel | MEDIUM — based on survey of published sources; some sources may not have been indexed | Security Boulevard AC/DC (3/2026), Greptile blog (11/2025) |

Overall confidence: **HIGH** for framework selection and pitfall mitigations; **MEDIUM** for cost estimates and prior-art completeness.

---

## Counter-Evidence

**Against Option B (Claude Code Native)**:
- Agent Teams are explicitly flagged "experimental" with known limitations (no session resumption for in-process teammates, task status lag, one team at a time)
- No built-in cost tracking — requires custom implementation
- 15x token burn rate versus single-agent chat (Anthropic's own finding) applies to teams; subagents are cheaper but still higher than single-session

**Against rejecting LangGraph**:
- LangGraph's time-travel debugging could be valuable when a cascade step fails mid-run and needs inspection
- 126,000 stars signals strong community support and future maintenance confidence
- LangGraph v1.1.6's distributed runtime support (released April 2026) reduces prior concerns about single-machine limitations

**Against CLI trigger pattern**:
- Fully manual unless integrated with Automic — depends on human remembering to run the cascade after each build
- No push-triggered automatic invocation (GitHub Actions–style) in the current Automic infrastructure without additional integration work

**Recommendation remains Option B** despite counter-evidence because: (1) the experimental limitations of Agent Teams are not in scope — the recommended design uses subagents, not teams; (2) custom cost tracking via `PipelineEventLog` is already the project's pattern; (3) Automic scheduling provides the automatic trigger layer that addresses the "manual only" concern.

---

## What This Research Does NOT Cover

- Anthropic's Claude Managed Agents (public beta April 2026) — hosted runtime for stateful sessions — was not fully evaluated; may become relevant if the cascade needs to survive multiple Automic scheduling cycles as a persistent session
- Security hardening of the cascade script itself (credential access, output sanitization) — the project's D103 security model applies but specific cascade-script attack surface was not researched
- Specific Automic job definition format for invoking the cascade as a scheduled job
- Performance benchmarks of `claude -p` subprocess overhead versus direct Python SDK calls (relevant for Automic scheduling latency)
- The emerging ACP (Agent Communication Protocol) alongside MCP + A2A — not yet stable enough to influence architecture decisions

---

## Suggested Follow-Up

1. **Producer should create a D-number** for the cascade architecture decision, citing this research as the primary source for the "Option B via Claude Code subagents + CLI trigger + hooks" recommendation
2. **Producer should author `tools/cascade.py`** per the specific design proposal above (classified as recurring + scheduled → Automic inventory per D109 + udm-execution-classifier discipline)
3. **Producer should add a new B-item** for the Automic integration of the cascade script (the manual-only limitation is the primary operational risk)
4. **Validation Gate 2** can mark all "Option B" claims in the architecture decision as now supported by primary sources (Anthropic SDK blog, Claude Code docs, Greptile v3 case study)
5. **Research NOT needed** on Langfuse/LangSmith — the existing `PipelineEventLog` infrastructure is a sufficient observability layer per the North Star's operational stability pillar

---

## Citations

All sources accessed 2026-05-16.

1. [LangGraph in 2026: Build Multi-Agent AI Systems That Actually Work — DEV Community](https://dev.to/ottoaria/langgraph-in-2026-build-multi-agent-ai-systems-that-actually-work-3h5)
2. [GitHub — langchain-ai/langgraph](https://github.com/langchain-ai/langgraph)
3. [Best Multi-Agent Frameworks in 2026: LangGraph, CrewAI... — GuruSup](https://gurusup.com/blog/best-multi-agent-frameworks-2026)
4. [LangGraph overview — Docs by LangChain](https://docs.langchain.com/oss/python/langgraph/overview)
5. [Definitive Guide to Agentic Frameworks in 2026 — SoftmaxData](https://softmaxdata.com/blog/definitive-guide-to-agentic-frameworks-in-2026-langgraph-crewai-ag2-openai-and-more/)
6. [GitHub — crewAIInc/crewAI](https://github.com/crewaiinc/crewai)
7. [CrewAI Review 2026 — VibeCoding](https://vibecoding.app/blog/crewai-review)
8. [Microsoft Agent Framework Version 1.0 — Microsoft Developer Blogs](https://devblogs.microsoft.com/agent-framework/microsoft-agent-framework-version-1-0/)
9. [Microsoft Ships Production-Ready Agent Framework 1.0 — Visual Studio Magazine](https://visualstudiomagazine.com/articles/2026/04/06/microsoft-ships-production-ready-agent-framework-1-0-for-net-and-python.aspx)
10. [Building Agents with the Claude Agent SDK — Anthropic Engineering (September 2025)](https://claude.com/blog/building-agents-with-the-claude-agent-sdk)
11. [Orchestrate Teams of Claude Code Sessions — Claude Code Docs](https://code.claude.com/docs/en/agent-teams)
12. [Anthropic's Multi-Agent Blueprint: What Production Adds — FountainCity Tech](https://fountaincity.tech/resources/blog/anthropic-multi-agent-blueprint-production/)
13. [Multi-Agent in Production in 2026: What Actually Survived — Medium (Micheal Lanham)](https://medium.com/@Micheal-Lanham/multi-agent-in-production-in-2026-what-actually-survived-f86de8bb1cd1)
14. [AI Agents Horror Stories: How a $47,000 Failure Exposed Hidden Risks — Tech Startups](https://techstartups.com/2025/11/14/ai-agents-horror-stories-how-a-47000-failure-exposed-the-hype-and-hidden-risks-of-multi-agent-systems/)
15. [Multi-Agent AI Production Requirements Beyond the Demo — Augment Code](https://www.augmentcode.com/guides/multi-agent-ai-production-requirements)
16. [When AI Agents Collide: Multi-Agent Orchestration Failure Playbook for 2026 — Cogent Infotech](https://cogentinfo.com/resources/when-ai-agents-collide-multi-agent-orchestration-failure-playbook-for-2026)
17. [Cascading Failures in Agentic AI — OWASP ASI08 Security Guide 2026 — Adversa AI](https://adversa.ai/blog/cascading-failures-in-agentic-ai-complete-owasp-asi08-security-guide-2026/)
18. [Why Multi-Agent LLM Systems Fail — Orq.ai](https://orq.ai/blog/why-do-multi-agent-llm-systems-fail)
19. [Why Your Multi-Agent System Is Failing: 17x Error Trap — Towards Data Science](https://towardsdatascience.com/why-your-multi-agent-system-is-failing-escaping-the-17x-error-trap-of-the-bag-of-agents/)
20. [Automate Workflows with Hooks — Claude Code Docs](https://code.claude.com/docs/en/hooks-guide)
21. [Automate Repository Tasks with GitHub Agentic Workflows — GitHub Blog](https://github.blog/ai-and-ml/automate-repository-tasks-with-github-agentic-workflows/)
22. [GitHub Agentic Workflows: A Hands-On Guide — DEV Community](https://dev.to/htekdev/github-agentic-workflows-a-hands-on-guide-to-ai-powered-cicd-255e)
23. [GitHub Agentic Workflows Unleash AI-Driven Repository Automation — InfoQ (February 2026)](https://www.infoq.com/news/2026/02/github-agentic-workflows/)
24. [Agent Hooks: The Secret to Controlling AI Agents — DEV Community](https://dev.to/htekdev/agent-hooks-the-secret-to-controlling-ai-agents-in-your-codebase-6a8)
25. [Token & Cost Tracking — Langfuse](https://langfuse.com/docs/observability/features/token-and-cost-tracking)
26. [LangSmith: AI Agent & LLM Observability Platform](https://www.langchain.com/langsmith/observability)
27. [Anthropic API Pricing 2026 — Finout](https://www.finout.io/blog/anthropic-api-pricing)
28. [Claude API Pricing: Haiku 4.5, Sonnet 4.6, Opus 4.7 (April 2026) — BenchLM.ai](https://benchlm.ai/blog/posts/claude-api-pricing)
29. [MCP and A2A: The Protocols Building the AI Agent Internet — Medium](https://medium.com/@aftab001x/mcp-and-a2a-the-protocols-building-the-ai-agent-internet-bc807181e68a)
30. [Model Context Protocol — Wikipedia](https://en.wikipedia.org/wiki/Model_Context_Protocol)
31. [Introducing the Model Context Protocol — Anthropic](https://www.anthropic.com/news/model-context-protocol)
32. [Greptile v3: An Agentic Approach to Code Review — Greptile Blog](https://www.greptile.com/blog/greptile-v3-agentic-code-review)
33. [The Future Is AC/DC: The Agent-Centric Development Cycle — Security Boulevard (March 2026)](https://securityboulevard.com/2026/03/the-future-is-ac-dc-the-agent-centric-development-cycle/)
34. [Create Custom Subagents — Claude Code Docs](https://code.claude.com/docs/en/sub-agents)
35. [Laminar vs Langfuse vs LangSmith: LLM Observability Compared — Laminar (January 2026)](https://laminar.sh/blog/2026-01-29-laminar-vs-langfuse-vs-langsmith-llm-observability-compared)
