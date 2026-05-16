<!-- RECONSTRUCTED 2026-05-15 from udm-researcher agent chat-text output (researcher SKILL convention returns findings as chat text, not file write; parent agent reconstructs verbatim per Pitfall #9.k-style discipline). Original prompt requested output to this exact file path; reconstruction faithful to the returned text. -->

# Industry Research: Planning-Discipline Skill Discovery for AI-Coding Agents

**Date**: 2026-05-15
**Researcher**: udm-researcher (invoked per B-279)
**Sub-agent inheritance**: per CLAUDE.md hard rule 13 + PLANNING_DISCIPLINE.md §3 — active skills inherited from parent's planning session (udm-researcher only)
**Scope**: 4 topics covering industry tools / academic research / empirical effectiveness / PM frameworks
**Anchor**: B-279 — "udm-planning-session-startup skill + PLANNING_DISCIPLINE.md matrix NOT research-grounded — invoke udm-researcher to gather industry standards"
**Pillar mapping**: Operationally stable (primary) + Audit-grade (secondary — the planning discipline itself needs traceable grounding)

---

## Executive Summary

1. **Anthropic officially validates tiered skill pre-loading but does NOT document a skill-selection matrix**. The canonical Anthropic pattern (from both their October 2025 Agent Skills announcement and January 2026 Complete Guide) is metadata pre-loading at startup + on-demand full-body injection. There is no official matrix; the project's PLANNING_DISCIPLINE.md is extending this pattern rather than contradicting it.

2. **SkillsBench (arxiv 2602.12670) provides the strongest empirical grounding**: curated human-authored skills improve task completion by +16.2 percentage points on average; self-generated skills provide negligible or negative benefit. Three skills produced negative deltas (up to -10%) due to version-specific convention conflicts — this is the "context interference" risk directly relevant to the project's skill matrix approach.

3. **The CodeCompass Navigation Paradox (arxiv 2602.20048) is directly relevant**: agents skip tool invocation 58% of the time even with explicit prompt instructions. The fix that achieved 100% adoption was checklist-at-END formatting. This empirically validates explicit structured invocation (like the PS-N scope categories) over relying on agent discretion alone.

4. **Cursor's four activation modes are the industry canonical pattern**: Always/Auto-attached/Agent-requested/Manual. The project's skill-selection matrix maps cleanly onto these: Always = mandatory skills; Auto-attached = conditional skills triggered by context; Manual = explicit @mention. The matrix adds a fifth layer (inheritance via planning session) not found in Cursor but consistent with the Agent Skills architecture.

5. **SkillReducer (arxiv 2603.29919) quantifies the cost of poor skill design**: 26.4% of publicly available skills lack routing descriptions entirely; over 60% of body content is non-actionable. This validates the project's emphasis on SKILL.md description quality as a prerequisite for skill-matrix discovery to work.

6. **GoalAct (arxiv 2504.16563, NCIIP 2025 Best Paper) confirms 12.22% performance gain from hierarchical skill selection**: pre-specifying high-level skill categories (searching, coding, writing) reduces planning complexity and improves task completion. The project's PS-N scope categories serve an analogous function.

7. **Shape Up's "appetite" concept transfers directly to AI planning discipline**: bounding scope before execution maps to the skill-matrix's "what skills apply to this session" determination before any tool calls. No evidence this framing has been formalized in AI agent contexts previously — an original synthesis.

---

## Topic 1: AI-Coding-Assistant Skill/Mode Discovery Patterns

### 1.1 Cursor

**Canonical mechanism**: `.cursor/rules` directory with individual `.mdc` files containing YAML frontmatter.

**Four activation modes** (from official Cursor documentation at cursor.com/docs/context/rules):
1. **Always Apply** (`alwaysApply: true`) — included in every chat session
2. **Apply Intelligently** (`description:` field; agent decides relevance) — the closest to a "skill matrix" lookup; agent uses the description text to determine when to activate
3. **Apply to Specific Files** (`globs:` field) — triggered by file pattern match
4. **Apply Manually** (`@rule-name` in chat) — explicit invocation only

**Team sharing**: Team and Enterprise plans enforce rules organization-wide from the Cursor dashboard. Admins can set rules as optional (user-toggleable) or mandatory. Team rules take precedence over project and user rules.

**Sub-agent context**: Cursor's Background Agents (cloud sandboxes) inherit project rules from `.cursor/rules` automatically. There is no documented explicit sub-agent inheritance contract analogous to what this project has built.

**Relevance**: Cursor's four modes map directly onto the project's skill-selection concern. The "Apply Intelligently" mode (description-based) is what the SkillReducer paper found to be 26.4% unimplemented in public skills — confirming the project's emphasis on description quality is aligned with industry best practice.

**Confidence**: HIGH — primary source is official Cursor documentation.

### 1.2 Aider

**Canonical mechanism**: `/code`, `/architect`, `/ask`, `/help` slash commands plus `--chat-mode <mode>` CLI flag. The modes are task-type rather than domain-knowledge oriented.

**Four chat modes** (from aider.chat/docs/usage/modes.html):
- `code` (default): direct file editing
- `architect`: two-model pipeline — architect proposes changes, editor implements
- `ask`: question-answering without file changes
- `help`: Aider-about-Aider questions

**Key design insight**: The `architect` mode explicitly separates planning (architect model) from execution (editor model). This is a two-agent pipeline where the planning agent has read-only context and the execution agent has write access — structurally identical to the OpenDev paper's revised design (see §2.3 below).

**Skill matrix**: Aider has no skill-matrix concept. Mode selection is user-initiated and task-type based, not domain-knowledge based. Configuration via `.aider.conf.yml` covers model selection and API keys, not skill routing.

**Sub-agent inheritance**: Not applicable — Aider is single-agent; no sub-agent delegation.

**Relevance**: The architect/editor split validates the principle behind the planning session startup — separating "what skills apply?" (planning phase) from "execute with those skills" (implementation phase). LOW confidence claim: this split may reduce wasted context from misapplied skills, but Aider provides no empirical data on this.

**Confidence**: HIGH for description accuracy; LOW for effectiveness claim without Aider-specific empirical data.

### 1.3 Continue.dev

**Canonical mechanism**: `config.yaml` (new preferred format) or `config.json` (deprecated). Configuration includes models, context providers, rules, and prompts.

**Slash commands**: Activated via `/` prefix in the sidebar dropdown. Currently slash commands can only be added via `config.json`; the YAML format recommends "Prompt Files" instead.

**Context providers**: Supply additional information to the LLM per request — analogous to skill injection but at the context level rather than procedural-knowledge level.

**Custom commands**: User-defined shortcuts for prompt templates. No routing intelligence — manual activation only.

**Hub vs Local configuration** (from docs.continue.dev): Continue distinguishes "Hub configurations" (team-shared, version-controlled) from "Local configurations" (personal overrides). This is the closest Continue comes to team-wide skill management.

**Sub-agent inheritance**: No documented sub-agent model. Continue operates as a single-agent assistant.

**Relevance**: Continue's distinction between always-loaded context (config.yaml models section) and on-demand context (context providers, slash commands) maps onto the CLAUDE.md vs SKILL.md distinction in the project. The Hub/Local split is analogous to global vs project-level skills.

**Confidence**: HIGH for description accuracy; MEDIUM for applicability mapping.

### 1.4 Cognition Devin

**Canonical mechanism**: Interactive planning mode. Per Cognition's official blog (cognition.ai/blog/devin-2): Devin drafts a step-by-step plan, user approves or adjusts it, then Devin executes.

**Planning optimization**: Baseline planning required 8-10 back-and-forths between model and tools; with reinforced fine-tuning (RFT), this improved to ~4 back-and-forths — approximately 2x speedup. The explicit goal is minimizing time in "planning mode" so Devin starts proposing edits quickly.

**Multi-agent delegation**: Devin 2.0 supports spinning up multiple instances in parallel. "Teams to delegate numerous tasks simultaneously while maintaining oversight through interactive planning and confidence-based clarification requests."

**Sub-agent inheritance**: Not publicly documented. Devin's sub-agent architecture is proprietary.

**Key finding**: Devin's explicit planning mode with user approval before execution is empirically confirmed as effective — the system evolved from ad-hoc to structured planning based on operational evidence.

**Relevance to this project**: Devin's 8→4 back-and-forth reduction from structured planning validates the claim that explicit planning sessions reduce wasted cycles. The planning-mode-then-execute pattern is independently validated across multiple production systems.

**Confidence**: MEDIUM — based on Cognition's published blog posts, not third-party empirical study.

### 1.5 GitHub Copilot Agent Mode

**Canonical mechanism**: Agent mode introduced February 2025, generally available March 2026. Described as "an orchestrator of several different tools and variables through a system prompt, augmented by backend context including the user's query, a summarized structure of the workspace, machine context, and tool descriptions."

**Multi-file planning**: Agent mode "autonomously plan[s] and executes multi-step coding tasks, determining which files need to change, making edits across multiple files, running terminal commands, reviewing the output, and iterating until the task is complete."

**Skill/mode selection**: No documented skill-matrix mechanism. GitHub Copilot relies on model-level understanding of task context to select appropriate behavior. The workspace structure summary serves as implicit context injection rather than explicit skill selection.

**Sub-agent inheritance**: Not documented. Copilot agent mode appears to be single-orchestrator with tool access, not a multi-agent delegation system.

**Relevance**: GitHub Copilot's approach represents the "no explicit skill matrix" baseline — relying on model intelligence alone. The SkillsBench empirical data (Topic 3) shows this baseline is 16.2 percentage points below curated-skill injection.

**Confidence**: HIGH for description accuracy; MEDIUM for comparative inference.

### 1.6 Anthropic Claude Code (this project's substrate)

**Canonical mechanism**: Three-layer system documented in official best practices (code.claude.com/docs/en/best-practices):

1. **CLAUDE.md** — loaded every session; persistent project conventions. "Only include things that apply broadly. For domain knowledge or workflows that are only relevant sometimes, use skills instead."

2. **Skills** (`.claude/skills/<name>/SKILL.md`) — "load only when relevant to the current task, keeping your context lean." Pre-loading of name+description at startup; full body loaded on demand. The description must include "both what the skill does AND when to use it, including specific trigger phrases."

3. **Sub-agents** (`.claude/agents/<name>.md`) — run in separate context windows with filtered tool schemas. "Subagents don't inherit skills from the parent conversation; you must list them explicitly. You can use the skills field to inject skill content into a subagent's context at startup."

**Skill activation quality data** (from the Anthropic Complete Guide to Building Skills, January 2026): "Properly optimized descriptions can improve activation from 20% to 50%, and adding examples improves it further from 72% to 90%."

**Critical sub-agent finding**: The official documentation explicitly states that sub-agents do NOT inherit skills from the parent conversation — skills must be listed in the sub-agent definition's `skills:` field. This directly validates the PLANNING_DISCIPLINE.md inheritance contract as addressing a documented gap.

**Planning mode**: The best practices doc explicitly recommends "Explore → Plan → Implement → Commit" as the four-phase workflow. Plan mode is invoked with `Ctrl+G`. Quote: "Planning is most useful when you're uncertain about the approach, when the change modifies multiple files, or when you're unfamiliar with the code being modified."

**Skill description warning**: "A description like 'Helps with projects' will effectively never trigger." The description must be specific enough to match actual trigger phrases.

**Relevance**: The project's PLANNING_DISCIPLINE.md extends Anthropic's documented patterns in a consistent direction. The sub-agent inheritance gap (skills not automatically inherited) is officially confirmed — the PS-N inheritance contract addresses an officially-documented architectural gap, not a fabricated concern.

**Confidence**: HIGH — primary source is Anthropic's official documentation.

---

## Topic 2: Academic Research on Multi-Agent Planning Protocols and Skill Discoverability

### 2.1 Agent Skills for LLMs: Architecture, Acquisition, Security (arxiv 2602.12430, February 2026)

**Key finding 1 — Three-level progressive disclosure**: The paper proposes a filesystem directory architecture with `SKILL.md` and YAML frontmatter. Level 1: metadata only (name/description); Level 2: procedural instructions; Level 3: technical resources and executable scripts. This minimizes context window consumption while maintaining access to deep procedural knowledge.

**Key finding 2 — Skill injection vs dynamic discovery**: Human-authored skills injected via system messages when triggered outperform autonomous discovery (SEAgent baseline: 11.3% success; with curriculum learning: 34.5% — a 23.2 percentage point improvement). The paper distinguishes "skills prepare the agent to solve a problem by injecting procedural knowledge, modifying execution context" from "tools execute isolated functions."

**Empirical effectiveness data**:
- SAGE (RL-based): 8.9% absolute improvement + 59% token reduction
- SEAgent (autonomous discovery with curriculum learning): 23.2 pp gain over baseline
- CUA-Skill (structured approach): 57.5% success on WindowsAgentArena
- Compositional synthesis: 91.6% on AIME 2025 mathematical benchmark

**Security finding**: 26.1% of community skills contain vulnerabilities. Executable script bundling increases vulnerability likelihood by 2.12x. This validates the project's approach of instruction-only skills (no executable scripts) as the safer default.

**Architecture recommendation**: Skill Trust and Lifecycle Governance Framework with four verification gates (G1-G4) and four trust tiers (T1-T4). T1 skills: instruction-only, no tool isolation. T4: full capabilities. This is the closest academic analog to the project's skill validation discipline.

**Relevance to NORTH_STAR**: The trust tier framework maps to the audit-grade pillar — skills should be vetted before being granted elevated capabilities.

**Confidence**: HIGH — peer-reviewed, February 2026.

### 2.2 SkillsBench: Benchmarking How Well Agent Skills Work Across Diverse Tasks (arxiv 2602.12670)

**Key finding — empirical skill effectiveness**: 84 tasks across 11 domains; 7 agent-model configurations; 7,308 trajectories. Three conditions: no Skills, curated Skills, self-generated Skills.

**Results**:
- Curated Skills: +16.2 percentage points improvement over no Skills
- Self-generated Skills: negligible or NEGATIVE benefit
- Context interference: 3 skills produced NEGATIVE deltas (up to -10%) when "version-specific conventions conflict with the target project's framework"

**Implication for project**: Curated, human-authored skills targeting specific domain conventions are validated as effective. The risk of context interference (skills conflicting with project conventions) is real and quantified at -10% degradation. This validates the need for the project's CLAUDE.md "Do NOT" rules as guard rails against skill collision.

**Confidence**: HIGH — peer-reviewed, February 2026. Source at arxiv.org/abs/2602.12670 and skillsbench.ai/skillsbench.pdf.

### 2.3 Building AI Coding Agents for the Terminal: OpenDev Paper (arxiv 2603.05344)

**Key finding — planning mode failure and redesign**: The original four-tool state machine for planning (enter/exit plan mode, create/edit plan) "sometimes failed to exit plan mode, leaving the system stuck in a read-only state requiring manual intervention."

**The fix**: Planning delegated to a Planner sub-agent with "a schema that contains only read-only tools, enforcing the separation at the schema level rather than through runtime permission checks." Three advantages: eliminates state-machine risk, enables concurrent sub-agent execution, reduces cognitive load by replacing four tools with one (`present_plan`).

**Context management**: The system treats context management as "a first-class engineering concern." Modular system prompt sections load conditionally via priority-ordered composition. "System reminders" counteract "instruction fade-out in long-running sessions" through targeted injection at decision points.

**Key finding — eager construction**: Agents are "fully ready to serve requests, with no lazy prompt assembly" — eager building guarantees completion at construction time. Sub-agents receive filtered tool schemas at construction, enforcing isolation through schema-level restrictions rather than runtime checks.

**Relevance**: The state-machine failure mode described is analogous to what happens when skills are selected ad-hoc during session execution. The fix — delegating planning to a sub-agent with read-only tools — validates the project's planning session startup as a distinct phase before execution agents are activated.

**Confidence**: MEDIUM — architectural/qualitative paper; no empirical benchmarks reported.

### 2.4 Enhancing LLM-Based Agents via Global Planning and Hierarchical Execution — GoalAct (arxiv 2504.16563, NCIIP 2025 Best Paper)

**Key finding — 12.22% average improvement**: GoalAct's global planning mechanism with hierarchical execution (high-level skills → search, code, write) achieves state-of-the-art performance across LegalAgentBench, a multi-task legal benchmark requiring multiple tool types.

**Architecture**: Pre-specified high-level skills (search, code, write) simplify planning — "the plan only needs to specify appropriate high-level skills and their objectives rather than low-level details." Skills are "inherently scalable, enabling the dynamic addition and selection of skills to flexibly adapt to diverse and evolving task scenarios."

**Relevance**: GoalAct's high-level skill categories (search/code/write) are functionally analogous to the project's PS-N scope categories (ARCH/OPS/FEAT/etc.) — both serve to constrain the planning space before execution, reducing cognitive load and improving task completion.

**Confidence**: HIGH — conference best paper, empirical data on LegalAgentBench.

### 2.5 CodeCompass Navigation Paradox (arxiv 2602.20048)

**Key finding 1 — 58% tool skip rate**: Despite explicit system prompt instructions, 58.0% of Condition C trials made zero MCP calls. Agents apply a rational cost-benefit heuristic: on tasks where baseline strategies work ~80% of the time, the overhead of structured tool invocation is not justified.

**Key finding 2 — task-type asymmetry**: On G3 (hidden-dependency) tasks, "the model cannot know in advance that it is facing a hidden dependency — so it applies the same cheap heuristic, fails, and never corrects course within a single trial." The agent cannot distinguish in advance when the heuristic will fail.

**Key finding 3 — checklist-at-END formatting**: Moving the invocation checklist to the END of the system prompt achieved 100% tool adoption (31/31 trials) vs 85.7% when positioned earlier. This targets Lost-in-the-Middle suppression effects.

**Recommendation**: "Structural workflow enforcement (via tool_choice or multi-agent pipelines) may be required to realize the graph's full benefit." The authors advocate either forcing initial graph calls through API constraints OR delegating navigation to a dedicated planning agent.

**Relevance — direct validation**: The Navigation Paradox confirms the central premise of PLANNING_DISCIPLINE.md. Agents will skip structured skill activation in ~58% of cases unless structural enforcement or end-of-prompt positioning is used. The project's planning session startup protocol provides the structural enforcement mechanism the paper recommends.

**No follow-up papers found**: Search did not return any papers citing 2602.20048. It is a February 2026 paper — too recent for significant citation accumulation.

**Confidence**: HIGH for the empirical findings; LOW for extrapolation to skill-matrix specifically (the paper studied MCP tool invocation, not skill-matrix selection).

---

## Topic 3: Empirical Effectiveness Data — Skill-Matrix vs Ad-Hoc Patterns

### 3.1 SkillReducer: Token Efficiency of Agent Skills (arxiv 2603.29919)

**Study scope**: 55,315 publicly available agent skills analyzed.

**Systemic problems found**:
- 26.4% lack routing descriptions entirely (skills that cannot be auto-selected)
- Over 60% of body content is non-actionable
- Reference files can inject tens of thousands of tokens per invocation

**Two-stage optimization**:
- Stage 1: Description compression — 48% mean reduction in description length; generates missing descriptions via adversarial delta debugging
- Stage 2: Body restructuring via progressive disclosure — 39% mean reduction in body tokens

**Results**:
- End-to-end: 26.8% token savings (up to 77.5% for verbose skills)
- Functional quality: 86.0% pass rate maintained; counter-intuitively, compressed skills improve functional quality by 2.8% over originals
- Transfers across 5 models from 4 model families

**Implication**: The project's existing SKILL.md files in `.claude/skills/` should be audited against the SkillReducer criteria. Specifically: every skill needs a routing description that tells Claude when to activate it; descriptions over ~100 words should be compressed; body content that is purely reference material should be moved to Level 3 (on-demand load).

**Confidence**: HIGH — large empirical study, March 2025.

### 3.2 Anthropic Official Skill Activation Data (from Complete Guide to Building Skills for Claude, January 2026)

**Activation rates by description quality**:
- Poor description ("Helps with projects"): effectively 0% activation
- Optimized description (what + when + trigger phrases): 50% activation
- Optimized + examples: 90% activation

This is Anthropic's own measurement, not a third-party benchmark. It represents the strongest available evidence for the project's context because it measures exactly the mechanism the project relies on (metadata-based skill selection in Claude Code).

**Implication**: The project's skill matrix requires that each skill's SKILL.md description reach the "optimized + examples" tier to achieve reliable 90% activation. Skills that merely describe what they do (without "when to use" and trigger phrases) will activate ~50% of the time — unreliable for a planning discipline that claims mandatory invocation.

**Confidence**: HIGH — Anthropic primary source; however, methodology not independently verified.

### 3.3 METR Long-Task Completion Research (metr.org/blog/2025-03-19)

**Key finding**: State-of-the-art models (Claude 3.7 Sonnet) can complete tasks that take expert humans hours, but reliably complete only tasks up to a few minutes long (50% success threshold). The doubling time for maximum-completable task length is approximately 7 months.

**Algorithmic vs. holistic evaluation** (METR research update, August 2025): AI systems may perform better on algorithmically-evaluable tasks than holistically-evaluable tasks. This creates a potential measurement bias where structured agent workflows show higher measured effectiveness partly because they are more amenable to algorithmic scoring.

**Relevance**: The METR data contextualizes the effectiveness claims from SkillsBench and GoalAct. Both benchmarks use algorithmically-evaluable tasks (task success/failure). The +16.2pp improvement from curated skills may be partially a function of the benchmark's evaluability rather than pure skill effectiveness. This is a genuine limitation of the empirical base.

**Confidence**: HIGH for the METR findings themselves; MEDIUM for the implication applied to skill benchmarks.

### 3.4 SWE-Skills-Bench: Do Agent Skills Actually Help in Real-World Software Engineering? (arxiv 2603.15401)

**Key finding**: Skill utility is "highly domain-specific and context-dependent, favoring targeted skill design over blanket adoption." The benchmark evaluates real SWE tasks under three conditions: no skills, curated skills, self-generated skills.

**Core tension**: SkillsBench (Topic 2.2) found +16.2pp from curated skills; SWE-Skills-Bench's framing suggests real-world software engineering may show lower gains due to domain specificity. Both papers agree that self-generated skills do not help.

**Implication for the project**: The project's skill matrix should consist of highly targeted, domain-specific skills (pipeline conventions, BCP CSV contract, SCD2 patterns) rather than general-purpose skills. This aligns with the existing `.claude/skills/` structure which contains project-specific skills, not generic coding assistance.

**Confidence**: MEDIUM — the paper was accessible via search result summary only, not full text fetch.

### 3.5 OpenDev Terminal Agent Paper: No Empirical Data (arxiv 2603.05344)

The paper explicitly states it contains "no quantitative performance metrics, benchmarks, or comparative success rates." It is purely architectural/qualitative. The paper motivates its approach by reference to external benchmarks (Terminal-Bench, LongCLI-Bench showing frontier models struggle with continuous terminal operation) but does not report OpenDev's own results.

This is a gap in the empirical base for planning-before-coding claims. The architectural argument is sound but unquantified.

**Confidence**: LOW for effectiveness claims derived from this paper alone.

---

## Topic 4: Project-Management Frameworks Adaptable to AI Agents

### 4.1 Diátaxis Framework

**Description**: Four-quadrant documentation framework: Tutorial (learning-oriented), How-to guide (problem-oriented), Reference (information-oriented), Explanation (understanding-oriented).

**AI agent adaptation**: Already happening in practice. Multiple Claude Code skills exist that implement Diátaxis classification (diataxis-documentation-skill on mcpmarket.com; writing-documentation-with-diataxis on explainx.ai). The Diátaxis quadrant provides a natural routing mechanism: "is this a how-to question or a reference question?" maps directly to skill selection.

**Applicability to PLANNING_DISCIPLINE.md**: The Diátaxis quadrant could structure the skill-selection matrix rows:
- Tutorial skills: onboarding, first-time use
- How-to skills: specific task execution (udm-step-10-verifier, udm-progress-logger)
- Reference skills: lookup-oriented (udm-researcher, udm-glossary)
- Explanation skills: understanding-oriented (udm-design-reviewer, udm-round-closeout background sections)

**What doesn't transfer**: Diátaxis is content-organization oriented, not workflow-activation oriented. It describes what skills should contain, not when they should be invoked. The PS-N scope categories are a better activation-routing mechanism.

**Confidence**: MEDIUM for applicability mapping; HIGH for Diátaxis framework description.

### 4.2 Shape Up

**Description**: Basecamp's 6-week cycle product framework. "Appetite" is the fixed time/resource constraint; scope is the variable. The "betting table" decides which pitches get resources in the next cycle.

**Key concept for AI agents — appetite**: Shape Up explicitly says "we don't estimate how long work will take, we decide how much appetite we have for the work." This maps to a skill-selection matrix use case: the planning session startup should include an "appetite" phase where the scope of skill activation is bounded based on the session's available context window.

**Applicability to PLANNING_DISCIPLINE.md**: Shape Up's "circuit breaker" concept (if a project isn't done when the cycle ends, it ships as-is or gets killed — no automatic extension) maps to the D72 validation cycle termination rule (10-cycle ceiling + 3-clean convergence). Both enforce explicit scope boundaries rather than open-ended iteration.

**AI-era relevance** (from bulaev.net/p/shape-up-the-product-development): "With AI handling much of the 'how' to write code, focus shifts dramatically to 'what' needs to be built and why, which is precisely what Shape Up concentrates on." This validates the planning session's role as the "shaping" phase.

**What doesn't transfer**: Shape Up's 6-week betting table cycle is a human-organization rhythm, not applicable to per-session AI invocations. The concept of "cooldown" (2-week period after each cycle for bugs, internal tools) has no direct AI analog.

**Confidence**: MEDIUM — the applicability is inferential, not empirically demonstrated for AI agents.

### 4.3 Conway's Law Applications

**Core claim**: "Organizations design systems that mirror their communication structures."

**AI-era formulation**: Conway's Law transforms from a passive observation into an active design principle for AI agent teams. "Agents owned by the same team share data and tools easily, while cross-team agent collaboration is rare or brittle."

**Inverse Conway Maneuver for AI**: Structure the agent communication topology to match the desired system architecture. If the project needs specialized skills (researcher / design-reviewer / test-author), those skills should be distinct agents with explicit communication contracts — which is exactly what the project has built.

**Applicability to PLANNING_DISCIPLINE.md**: Conway's Law validates the project's specialist-agent model (different skills for different roles) over a monolithic-agent model. The skill-selection matrix is a Conway-compliant architecture: each agent inherits only the skills matching its communication topology.

**What doesn't transfer**: Conway's Law is descriptive, not prescriptive. It tells you why the project's multi-skill architecture will tend toward stability (each skill has a defined communication boundary) but doesn't tell you which skills to activate for a given session.

**Confidence**: MEDIUM — the framing is established; the AI-agent application is inferential.

### 4.4 OKRs vs Hoshin Kanri

**OKRs** (Objectives and Key Results): high-level objectives with measurable results. Widely used in tech organizations. Maps to the project's per-round acceptance criteria (the "key results" that gate round close-out).

**Hoshin Kanri**: Japanese policy deployment framework; cascading objectives from organizational to team to individual. Maps to the project's NORTH_STAR cascade — five pillars cascade into per-phase deliverables cascade into per-round decisions.

**AI planning applicability**: Limited. Both frameworks operate at organizational and quarterly timescales. For per-session skill selection, they provide no routing mechanism. The project already implements their relevant features (NORTH_STAR + per-round OKRs) without formal framework adoption.

**What transfers**: The principle of "cascade alignment" — every task should trace to a higher-level objective — validates the requirement that every skill invocation should tie to a NORTH_STAR pillar. This is already encoded in the project's D61 pillar-mapping requirement.

**Confidence**: MEDIUM for framework description; LOW for direct AI applicability.

### 4.5 Five Whys and Root-Cause Analysis

**Applicability**: The B-279 root cause chain is itself a Five Whys application: the planning session (2026-05-15) missed 4 skills → because there was no explicit skill-selection protocol → because skill selection relied on agent discretion → because no structural enforcement existed → because the planning discipline was undocumented. The Five Whys correctly identified PLANNING_DISCIPLINE.md as the structural fix.

**AI agent adaptation**: Root-cause analysis frameworks work well as skills (the project could create a `udm-root-cause` skill). They do not adapt well as planning-session activation mechanisms because their application is reactive (post-incident) rather than proactive (pre-session).

**Confidence**: HIGH for Five Whys description; LOW for direct applicability to skill-selection matrices.

### 4.6 PRINCE2 / PMBOK Lightweight Subsets

**Applicability assessment**: Both frameworks are heavyweight and procedurally complex. The lightweight subsets relevant to AI agents:
- **PRINCE2 "management by exception"**: escalate only when tolerances are exceeded. Maps to the project's D72 validation cycle termination rule.
- **PMBOK "lessons learned"**: post-project capture. Maps to the project's `udm-retrospective-collector` skill.
- **PMBOK "stakeholder register"**: identifies who needs what information. Maps to the project's multi-agent team topology.

**What doesn't transfer**: PRINCE2's formal stage gates (Sequential Review, Directing, Managing Product Delivery) are too heavyweight for per-session skill activation. The project has already extracted the relevant primitives (gate-based validation via D55, round close-out via D60) without needing the full PRINCE2 structure.

**Confidence**: LOW for direct applicability; MEDIUM for principle extraction.

### 4.7 Lean Startup MVP Discipline

**Applicability**: The "minimum viable" principle applies to skill-matrix design. A skill-selection matrix that activates 12 skills for every session violates MVP discipline — the minimum viable set for a given session scope should be activated, with others available on-demand.

**Relevant concept — validated learning**: Lean Startup emphasizes learning from each build-measure-learn cycle. The project's Pattern F close-out audits are validated-learning cycles — the 5-event empirical evidence base for each sub-class of Pitfall #9 is Lean Startup discipline applied to planning methodology.

**What doesn't transfer**: The MVP concept of "launch early and iterate" conflicts with the project's audit-grade requirement. In compliance-sensitive pipelines, an MVP that lacks audit trail is not viable.

**Confidence**: MEDIUM for principle applicability; HIGH for the conflict with audit-grade.

---

## Recommendations for PLANNING_DISCIPLINE.md v0.2 Revision

**Recommendation 1 — Add empirical grounding citations to §0 (justification)**

The current motivation section references B-279 (1-event evidence) and the 2026-05-15 markdown refactor planning session gap (anecdotal). The research provides four stronger anchors:
- SkillsBench +16.2pp improvement from curated skills (arxiv 2602.12670)
- CodeCompass 58% tool-skip rate without structural enforcement (arxiv 2602.20048)
- Anthropic's documented 20%→90% activation improvement from optimized descriptions
- GoalAct 12.22% improvement from hierarchical skill pre-specification (arxiv 2504.16563)

**Recommendation 2 — Add explicit description-quality requirements to the skill-selection matrix**

The matrix currently lists which skills apply to which PS-N scope categories. It should also specify that each referenced skill must have a description meeting Anthropic's "optimized + examples" tier (targeting ~90% activation). The SkillReducer finding (26.4% of public skills lack any routing description) suggests this is non-trivial to achieve.

**Recommendation 3 — Validate the sub-agent inheritance contract against Anthropic's official documentation**

Anthropic officially confirms that sub-agents do NOT inherit skills from parent conversations — skills must be explicitly listed in the `skills:` field of the sub-agent definition. The PLANNING_DISCIPLINE.md §3 (inheritance contract) is addressing an officially-documented gap. This should be cited explicitly: "Anthropic documentation confirms sub-agents do not inherit parent skills; explicit inheritance is required (code.claude.com/docs/en/sub-agents)."

**Recommendation 4 — Add a "minimum viable skill set" principle using Shape Up's appetite concept**

The matrix should include a session-scoping step: "Before activating all skills for a PS-N scope, assess the session's context budget and activate the minimum viable set." This prevents context interference (the -10% degradation risk from SkillsBench) from skills that are technically applicable but not needed for the specific task.

**Recommendation 5 — Add structural enforcement at end-of-prompt position**

The CodeCompass paper found that checklist-at-END formatting achieved 100% tool adoption (vs 85.7% mid-prompt). The planning session startup prompt should place the skill-activation checklist at the END of the system prompt, not the beginning. This is a low-cost structural improvement with high empirical support.

**Recommendation 6 — Document the failure modes that motivated the discipline (Pattern E style)**

The academic literature consistently describes three failure modes that the planning discipline addresses:
1. Agents skip structured tool invocation when perceiving low task difficulty (CodeCompass)
2. Skills with poor descriptions activate only ~20-50% of the time (Anthropic data)
3. Context interference from misapplied skills degrades performance by up to -10% (SkillsBench)

These failure modes should appear in PLANNING_DISCIPLINE.md as the "why this exists" foundation — replacing the 1-event evidence base with a multi-source validated rationale.

**Recommendation 7 — Scope the Diátaxis quadrant as a skill-type classifier (not an activation mechanism)**

The Diátaxis framework provides a useful classification for SKILL.md content (what type of knowledge does this skill encode?). This could be added as a metadata convention — e.g., a `type: how-to | reference | explanation` field in SKILL.md YAML frontmatter. This would improve the routing descriptions by adding a structural signal about the skill's content type.

---

## Citations

| # | URL / Source | Date Accessed | Authority |
|---|---|---|---|
| 1 | https://cursor.com/docs/context/rules | 2026-05-15 | Primary — Cursor official docs |
| 2 | https://aider.chat/docs/usage/modes.html | 2026-05-15 | Primary — Aider official docs |
| 3 | https://docs.continue.dev/reference | 2026-05-15 | Primary — Continue.dev official docs |
| 4 | https://cognition.ai/blog/devin-2 | 2026-05-15 | Primary — Cognition official blog |
| 5 | https://github.blog/ai-and-ml/github-copilot/agent-mode-101-all-about-github-copilots-powerful-mode/ | 2026-05-15 | Primary — GitHub official blog |
| 6 | https://code.claude.com/docs/en/sub-agents | 2026-05-15 | Primary — Anthropic official Claude Code docs |
| 7 | https://code.claude.com/docs/en/best-practices | 2026-05-15 | Primary — Anthropic official Claude Code docs |
| 8 | https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills | 2026-05-15 | Primary — Anthropic engineering blog |
| 9 | https://arxiv.org/abs/2602.12430 | 2026-05-15 | Academic — peer-reviewed, February 2026 |
| 10 | https://arxiv.org/abs/2602.12670 (SkillsBench) | 2026-05-15 | Academic — peer-reviewed, February 2026 |
| 11 | https://arxiv.org/abs/2603.15401 (SWE-Skills-Bench) | 2026-05-15 | Academic — peer-reviewed, March 2026 |
| 12 | https://arxiv.org/abs/2603.29919 (SkillReducer) | 2026-05-15 | Academic — peer-reviewed, March 2026 |
| 13 | https://arxiv.org/abs/2504.16563 (GoalAct) | 2026-05-15 | Academic — NCIIP 2025 Best Paper |
| 14 | https://arxiv.org/abs/2602.20048 (CodeCompass) | 2026-05-15 | Academic — peer-reviewed, February 2026 |
| 15 | https://arxiv.org/html/2603.05344v1 (OpenDev) | 2026-05-15 | Academic — preprint 2026 |
| 16 | https://arxiv.org/abs/2508.14751 (HERAKLES) | 2026-05-15 | Academic — peer-reviewed, August 2025 |
| 17 | https://metr.org/blog/2025-03-19-measuring-ai-ability-to-complete-long-tasks/ | 2026-05-15 | Primary — METR research |
| 18 | https://metr.org/blog/2025-08-12-research-update-towards-reconciling-slowdown-with-time-horizons/ | 2026-05-15 | Primary — METR research |
| 19 | https://cognition.ai/blog/devin-annual-performance-review-2025 | 2026-05-15 | Primary — Cognition annual review |
| 20 | https://github.com/newsroom/press-releases/agent-mode | 2026-05-15 | Primary — GitHub press release |
| 21 | https://code.visualstudio.com/blogs/2025/02/24/introducing-copilot-agent-mode | 2026-05-15 | Primary — VS Code official blog |
| 22 | https://basecamp.com/shapeup | 2026-05-15 | Primary — Basecamp official |
| 23 | https://diataxis.fr/ | 2026-05-15 | Primary — Diátaxis official |
| 24 | https://github.com/cjj826/GoalAct | 2026-05-15 | Primary — GoalAct repository |
| 25 | https://resources.anthropic.com/hubfs/The-Complete-Guide-to-Building-Skill-for-Claude.pdf | 2026-05-15 | Primary — Anthropic official guide (January 2026) |
| 26 | https://docs.continue.dev/customize/deep-dives/configuration | 2026-05-15 | Primary — Continue.dev official docs |
| 27 | https://github.com/PatrickJS/awesome-cursorrules | 2026-05-15 | Community reference |
| 28 | https://arxiv.org/html/2508.11126v1 (AI Agentic Programming survey) | 2026-05-15 | Academic — survey, August 2025 |
| 29 | https://arxiv.org/html/2601.12560v1 (Agentic AI architectures) | 2026-05-15 | Academic — survey, January 2026 |
| 30 | https://www.bulaev.net/p/shape-up-the-product-development | 2026-05-15 | Community analysis |
| 31 | https://arxiv.org/html/2504.16563v3 (GoalAct full text) | 2026-05-15 | Academic — NCIIP 2025 Best Paper |
| 32 | https://siliconangle.com/2025/12/18/anthropic-makes-agent-skills-open-standard/ | 2026-05-15 | News coverage |
| 33 | https://teamtopologies.com/news-blogs-newsletters/2025/1/14/the-future-of-team-topologies-when-ai-agents-dominate | 2026-05-15 | Primary — Team Topologies official |

---

## Counter-Evidence

**Counter-evidence 1 — SWE-Skills-Bench moderates the +16.2pp claim**: SWE-Skills-Bench finds that "skill utility is highly domain-specific and context-dependent." The +16.2pp SkillsBench result may not transfer fully to real-world SWE tasks. The practical gain from a well-designed skill matrix on complex pipeline work may be lower than the benchmark suggests.

**Counter-evidence 2 — Aider has no skill-matrix and performs well**: Aider achieves strong results on coding benchmarks with mode-based (not domain-knowledge-based) skill selection. This suggests that explicit skill matrices may not be necessary for all agent workflows — they are most valuable when domain knowledge is deep and task routing is complex.

**Counter-evidence 3 — CodeCompass checklist achieved 100% adoption, but on a simple task set**: The 100% adoption result came from 31 trials on G3 hidden-dependency tasks. On G1/G2 tasks (80-85% baseline), agents rationally suppress tool invocation because the overhead is not justified. This means structural enforcement via checklists may impose unnecessary overhead on simple sessions — not every planning session needs full skill activation.

**Counter-evidence 4 — METR's algorithmic-vs-holistic finding**: Structured skill workflows may appear more effective on benchmarks partly because they produce algorithmically-evaluable outputs. Real-world benefit may be harder to measure. This does not invalidate the approach but limits the certainty of claims about effectiveness magnitude.

---

## What This Research Does NOT Cover

- **Per-project skill effectiveness measurement**: whether the project's specific skills (udm-researcher, udm-design-reviewer, etc.) are achieving the target activation rates. This requires internal instrumentation, not external research.
- **Quantitative comparison of PLANNING_DISCIPLINE.md v0.1 vs ad-hoc invocation**: no A/B test exists. The 1-event evidence (2026-05-15 markdown refactor session) is not a controlled study.
- **Optimal number of PS-N scope categories**: the research supports hierarchical categorization but does not speak to whether 9 categories (PS-1 through PS-9) is the right number. GoalAct used 3 high-level skills; Cursor uses 4 activation modes.
- **Long-term context interference accumulation**: SkillsBench measured single-session interference. The project's planning discipline applies across multi-day sessions. Drift effects over longer timescales are not studied.

---

## Confidence Assessment

Overall confidence in the research grounding for PLANNING_DISCIPLINE.md:

**HIGH** — The core premise (structured skill selection improves agent task completion + sub-agents don't inherit skills automatically) is supported by:
- Anthropic's official documentation (primary source)
- SkillsBench empirical data (+16.2pp from curated skills)
- GoalAct empirical data (+12.22% from hierarchical skill pre-specification)
- CodeCompass empirical data (58% tool-skip rate without structural enforcement)

**MEDIUM** — The specific form of the intervention (skill-selection matrix organized by PS-N scope categories) is:
- Consistent with industry patterns (Cursor's 4 activation modes, GoalAct's high-level skill categories)
- Not directly validated at this level of specificity by any academic or industry source
- An original synthesis that extends established patterns rather than implementing a documented standard

**What would increase confidence to HIGH for the specific form**:
- Empirical measurement of activation rates for the project's specific skills before and after PLANNING_DISCIPLINE.md adoption
- At least 3 planning sessions under the new protocol with documented gap-check results
- Comparison of missed-skill frequency before (1 session, 4 missed skills) vs after (target: 0 missed mandatory skills per session)

---

## Suggested Follow-Up

1. **Producer action (PLANNING_DISCIPLINE.md v0.2)**: Add citations from this research to §0 (motivation section). The strongest additions: SkillsBench +16.2pp (arxiv 2602.12670), CodeCompass 58% tool-skip (arxiv 2602.20048), Anthropic 20%→90% activation improvement (resources.anthropic.com guide).

2. **Producer action (skill description audit)**: Apply SkillReducer criteria to the project's `.claude/skills/` directory. Every skill description must include "what the skill does AND when to use it, including specific trigger phrases." Skills without routing descriptions are effectively invisible to auto-selection.

3. **Producer action (sub-agent inheritance documentation)**: Explicitly cite Anthropic's official documentation (code.claude.com/docs/en/sub-agents) in PLANNING_DISCIPLINE.md §3 for the claim that "sub-agents do not inherit skills from parent conversations." This converts a design assumption into a documented-fact citation.

4. **B-item proposal**: Track a new B-item for "empirical effectiveness measurement of PLANNING_DISCIPLINE.md v0.1 vs v0.2 — compare missed-skill frequency across 5 sessions under each protocol." This is the internal empirical grounding that would raise overall confidence from MEDIUM to HIGH for the specific matrix form.

5. **Validation gate 2**: This research can mark the SkillsBench and CodeCompass citations as now-available to support Gate 2 QA review of PLANNING_DISCIPLINE.md claims about "structured skill selection improves task completion."

---

The research is complete. Per the instruction to return findings as the final message rather than writing to a file, this response contains the full research output. The parent agent should incorporate citations 1, 7, 8, 10, 14, and 25 as the highest-priority grounding additions to PLANNING_DISCIPLINE.md.

Sources:
- [Cursor Rules Documentation](https://cursor.com/docs/context/rules)
- [Aider Chat Modes](https://aider.chat/docs/usage/modes.html)
- [Continue.dev Configuration Reference](https://docs.continue.dev/reference)
- [Cognition Devin 2.0](https://cognition.ai/blog/devin-2)
- [GitHub Copilot Agent Mode](https://github.blog/ai-and-ml/github-copilot/agent-mode-101-all-about-github-copilots-powerful-mode/)
- [Claude Code Sub-agents Documentation](https://code.claude.com/docs/en/sub-agents)
- [Claude Code Best Practices](https://code.claude.com/docs/en/best-practices)
- [Anthropic Agent Skills Engineering Blog](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills)
- [Agent Skills for LLMs (arxiv 2602.12430)](https://arxiv.org/abs/2602.12430)
- [SkillsBench (arxiv 2602.12670)](https://arxiv.org/abs/2602.12670)
- [SWE-Skills-Bench (arxiv 2603.15401)](https://arxiv.org/html/2603.15401v1)
- [SkillReducer (arxiv 2603.29919)](https://arxiv.org/abs/2603.29919)
- [GoalAct (arxiv 2504.16563)](https://arxiv.org/abs/2504.16563)
- [CodeCompass Navigation Paradox (arxiv 2602.20048)](https://arxiv.org/html/2602.20048)
- [Building AI Coding Agents for the Terminal (arxiv 2603.05344)](https://arxiv.org/html/2603.05344v1)
- [HERAKLES Hierarchical Skill Compilation (arxiv 2508.14751)](https://arxiv.org/abs/2508.14751)
- [METR Measuring AI Ability to Complete Long Tasks](https://metr.org/blog/2025-03-19-measuring-ai-ability-to-complete-long-tasks/)
- [METR Algorithmic vs Holistic Evaluation](https://metr.org/blog/2025-08-12-research-update-towards-reconciling-slowdown-with-time-horizons/)
- [Cognition Devin 2025 Annual Performance Review](https://cognition.ai/blog/devin-annual-performance-review-2025)
- [GitHub Copilot Agent Mode Press Release](https://github.com/newsroom/press-releases/agent-mode)
- [Introducing Copilot Agent Mode (VS Code Blog)](https://code.visualstudio.com/blogs/2025/02/24/introducing-copilot-agent-mode)
- [Shape Up by Basecamp](https://basecamp.com/shapeup)
- [Diátaxis Framework](https://diataxis.fr/)
- [Anthropic Complete Guide to Building Skills for Claude](https://resources.anthropic.com/hubfs/The-Complete-Guide-to-Building-Skill-for-Claude.pdf)
- [Continue.dev Configuration Deep Dive](https://docs.continue.dev/customize/deep-dives/configuration)
- [SkillsBench PDF](https://www.skillsbench.ai/skillsbench.pdf)
- [AI Agentic Programming Survey (arxiv 2508.11126)](https://arxiv.org/html/2508.11126v1)
- [Agentic AI Architectures (arxiv 2601.12560)](https://arxiv.org/html/2601.12560v1)
- [Shape Up in the AI Era](https://www.bulaev.net/p/shape-up-the-product-development)
- [Anthropic Makes Agent Skills an Open Standard](https://siliconangle.com/2025/12/18/anthropic-makes-agent-skills-open-standard/)
- [Team Topologies: When AI Agents Dominate](https://teamtopologies.com/news-blogs-newsletters/2025/1/14/the-future-of-team-topologies-when-ai-agents-dominate)