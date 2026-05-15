# Research: AI Agent Navigation of Large Markdown Documentation Repositories

**Date**: 2026-05-15
**Triggered by**: on-demand (user request — authoring `MARKDOWN_REFACTOR_PLAN.md`)
**Question**: How do AI agents and agentic teams most effectively navigate large markdown documentation repositories? What patterns, tools, and conventions does industry use, and how do they apply to this project's specific CCL-driven traversal problem?
**Anchor**: D62 (CCL doctrine), MARKDOWN_REFACTOR_PLAN.md Phase 1–4 proposals, Operationally stable pillar

---

## Summary

The industry evidence base is surprisingly thin on the precise question of "how should a large project-internal markdown repository be structured for AI agent consumption at zero infrastructure cost." What exists is either (a) web-facing documentation platforms (Mintlify, MkDocs) with external tooling requirements, (b) code-navigation patterns that apply only loosely to doc repositories, or (c) the AGENTS.md/CLAUDE.md single-file disciplines that apply well to small-to-medium context budgets but do not directly address 41K-line multi-file corpora. The core finding: the plan's Phase 1 (index-front manifest + per-file sidecars) is directionally correct and consistent with the closest industry analogues (llms.txt, SKILL.md supporting files, AGENTS.md nested patterns), but the plan's Phase 2 pre-commit regeneration proposal carries a real staleness-friction risk that the industry evidence flags as a known anti-pattern. The plan's Phase 3 (conditional file splits) is validated by two independent data points: the SKILL.md 500-line cap and the AGENTS.md 150-200-line split threshold. Phase 4 frontmatter is validated by emerging standards (llms.txt, MAGI) but no primary source shows AI agents natively consuming YAML frontmatter from project-internal markdown files without additional tooling.

Confidence: 🟡 Medium — multiple sources agree on directional patterns; no benchmark study directly measures index-front vs. embedded-metadata for internal planning-doc corpora.

---

## Sources cited

| # | URL | Date accessed | Authority |
|---|---|---|---|
| 1 | https://code.claude.com/docs/en/best-practices | 2026-05-15 | Anthropic (primary) |
| 2 | https://code.claude.com/docs/en/skills | 2026-05-15 | Anthropic (primary) |
| 3 | https://llmstxt.org/ | 2026-05-15 | Community spec (widely adopted) |
| 4 | https://www.infoq.com/news/2026/03/agents-context-file-value-review/ | 2026-05-15 | InfoQ / ETH Zurich research |
| 5 | https://github.blog/ai-and-ml/github-copilot/how-to-write-a-great-agents-md-lessons-from-over-2500-repositories/ | 2026-05-15 | GitHub (primary) |
| 6 | https://developers.openai.com/codex/guides/agents-md | 2026-05-15 | OpenAI (primary) |
| 7 | https://www.mintlify.com/blog/state-of-ai | 2026-05-15 | Mintlify (industry data) |
| 8 | https://magi-mda.mintlify.app/introduction | 2026-05-15 | MAGI spec (community) |
| 9 | https://factory.ai/news/context-window-problem | 2026-05-15 | Factory.ai (industry) |
| 10 | https://weaviate.io/blog/chunking-strategies-for-rag | 2026-05-15 | Weaviate (community/academic) |
| 11 | https://diataxis.fr/ | 2026-05-15 | Diátaxis (community standard) |
| 12 | https://www.trychroma.com/research/context-rot | 2026-05-15 | Chroma (empirical research) |
| 13 | https://blog.premai.io/rag-chunking-strategies-the-2026-benchmark-guide/ | 2026-05-15 | Prem AI (benchmark) |
| 14 | https://gist.github.com/0xfauzi/7c8f65572930a21efa62623557d83f6e | 2026-05-15 | Community (GitHub Gist) |
| 15 | https://www.augmentcode.com/guides/how-to-build-agents-md | 2026-05-15 | Augment Code (community) |

---

## Findings

### Finding 1: CLAUDE.md is specifically designed to be short — "bloated CLAUDE.md files cause Claude to ignore your actual instructions"

**Source**: [#1] Anthropic Claude Code best practices

**Quote**: "Keep it concise. For each line, ask: 'Would removing this cause Claude to make mistakes?' If not, cut it. Bloated CLAUDE.md files cause Claude to ignore your actual instructions!"

The guidance explicitly states CLAUDE.md should exclude "file-by-file descriptions of the codebase" and "information that changes frequently." Domain knowledge or workflows that are "only relevant sometimes" should use skills instead, loaded on demand.

**Relevance to our project**: The project's current CLAUDE.md is extremely large (> 41K lines across all migration docs; CLAUDE.md itself spans hundreds of lines). The CCL pattern reads 7–11 files at startup, consuming 12K–16K lines per invocation. This directly contradicts Anthropic's own guidance. The index-front proposal in Phase 1 (a master INDEX.md that agents read instead of the full files) is the correct structural response.

**Anchor**: Operationally stable pillar — context bloat degrades agent performance, which is an operational stability failure mode.

**Confidence**: High — primary Anthropic documentation.

---

### Finding 2: Subdirectory-level CLAUDE.md files load on-demand (lazy), root-level loads at startup (eager)

**Source**: [#1] Anthropic Claude Code best practices

**Quote**: "Parent-level files load immediately at startup, subdirectory files load lazily, only when Claude reads files in that directory, so context cost scales with what you're actually working on."

CLAUDE.md files can also import other files via `@path/to/import` syntax, enabling modular context loading from a root entry point.

**Relevance to our project**: The plan's Phase 1 proposes a master INDEX.md with per-file sidecars. The native Claude mechanism for this is exactly the `@import` pattern and subdirectory CLAUDE.md files. The plan proposes a new "Stage 0" read-INDEX-first discipline as a doctrinal update to D62. The industry pattern suggests an alternative: restructure `docs/migration/` so each major doc lives in its own subdirectory, with a subdirectory-level CLAUDE.md that loads lazily. This would be more native to Claude's architecture than a custom INDEX manifest, though it would require more restructuring.

**Anchor**: Operationally stable pillar — native platform mechanics are more reliable than bespoke navigation disciplines.

**Confidence**: High — primary Anthropic documentation.

---

### Finding 3: Skills are the intended mechanism for "reference content that loads only when needed"

**Source**: [#2] Anthropic Claude Code skills documentation

**Quote**: "Create a skill when you keep pasting the same instructions, checklist, or multi-step procedure into chat, or when a section of CLAUDE.md has grown into a procedure rather than a fact. Unlike CLAUDE.md content, a skill's body loads only when it's used, so long reference material costs almost nothing until you need it."

The SKILL.md architecture is: one entry file (SKILL.md under 500 lines) that names supporting files; those files load only when the skill invokes them. Skill descriptions (truncated to 1,536 chars) are always in context; full body loads only when triggered.

**Relevance to our project**: The plan's Phase 4 proposes a `udm-find-canonical` skill (Option T3) for one-shot canonical-home lookups. This is exactly the intended use case per Anthropic's design. More broadly, the CCL doctrine (reading 7–11 files at startup) is performing the role that skills were designed to replace: loading topic-specific reference content on demand. The plan should more strongly anchor Phase 4's skill proposal as a Phase 1 or Phase 2 priority — it is the native Claude Code solution to the 12K–16K lines per invocation problem.

**Anchor**: Operationally stable pillar + cost ceiling (token costs per invocation).

**Confidence**: High — primary Anthropic documentation.

---

### Finding 4: The llms.txt open standard is the nearest industry analogue to the plan's master INDEX.md proposal

**Source**: [#3] llmstxt.org (specification)

**Quote**: "A proposal to standardise on using an /llms.txt file to provide information to help LLMs use a website at inference time... Rather than listing all pages like sitemaps do, llms.txt provides a 'curated overview for LLMs.'"

File structure: H1 heading (project name), blockquote (summary), sections with linked files and optional descriptions. Widely adopted: 844,000+ websites as of October 2025. Anthropic itself has adopted it for its own documentation.

**Relevance to our project**: The plan's Phase 1 master INDEX.md is structurally equivalent to llms.txt applied to an internal repository. The llms.txt pattern validates: (a) a single entry manifest is the industry-standard approach, (b) each entry in the manifest has a name, URL (or relative path), and one-line description, (c) an "Optional" section signals content that can be skipped when context is limited. The plan should name this analogy explicitly to justify the design.

**Anchor**: Traceability pillar — grounding design decisions in external standards makes them auditable.

**Confidence**: High — widely adopted open spec with Anthropic adoption.

---

### Finding 5: ETH Zurich research found that structural/architectural overviews in context files do NOT help agents navigate — and LLM-generated context files actively hurt

**Source**: [#4] InfoQ / ETH Zurich research (2026), based on AGENTbench testing of Claude 3.5 Sonnet, GPT-5 variants, Qwen Code across 138 real-world Python tasks

**Findings**:
- LLM-generated context files: task success rates reduced ~3% vs. no context file; agent steps +2.45–3.92 per task; inference costs +20–23%
- Human-written context files: success rates +4%; but also +19% inference cost
- Architectural overviews and repo structure explanations "did not meaningfully reduce time spent locating relevant files"
- Agents followed context file instructions too literally, running unnecessary tests and reading additional files

**Quote**: "instructions in context files are generally followed and lead to more testing and a broader exploration; however, they do not function as effective repository overviews."

**Relevance to our project**: This is counter-evidence for the plan's Phase 1 per-file INDEX sidecars if those sidecars are primarily structural (listing what each file contains). The research suggests this content increases cost without proportionate benefit. What does help: specific commands, code examples, explicit constraints (never do / always do). The plan's INDEX sidecars should focus on "when to read this file and when not to" rather than "what this file contains." The CCL doctrine's 7–11 file reads at startup are the exact pattern this research warns against: broad exploration that consumes context without grounding the agent.

**Anchor**: Operationally stable pillar + cost ceiling.

**Confidence**: High — peer-reviewed research, specific to the agent-context-file use case.

---

### Finding 6: The AGENTS.md / CLAUDE.md 150–200-line threshold for splitting into subdirectories is cross-platform consensus

**Sources**: [#5] GitHub blog (2,500+ repos), [#6] OpenAI Codex AGENTS.md documentation, [#14] community gist, [#15] Augment Code

**Quote (OpenAI)**: "Start with a single file; split it into subdirectories when it exceeds 150-200 lines."

**Quote (GitHub)**: The maas repo at 371 lines represents "the upper bound: a 371-line root file. Beyond that scale, modular organization becomes necessary for token budget reasons."

OpenAI's own repos use 88 AGENTS.md files demonstrating that per-subdirectory nesting at scale is the production pattern.

**Relevance to our project**: `_validation_log.md` at 7,129 lines and multiple files exceeding 1,000 lines each far exceed any recognized threshold. Phase 3's conditional file splits are validated as the right long-term destination; the question is whether Phase 1's index-front approach is sufficient as an intermediate step. The evidence supports: yes, index-front is a valid intermediate, but Phase 3 splits are not optional long-term. The specific threshold of 1,000 lines as a "split trigger" in Phase 3 has no direct industry backing — the researched threshold is 150–200 lines for context files, though this applies to agent-directive files (CLAUDE.md/AGENTS.md) rather than reference documents.

**Anchor**: Operationally stable pillar.

**Confidence**: Medium — thresholds apply to agent-directive files specifically, not to reference documentation; the analogy is approximate.

---

### Finding 7: Skills' SKILL.md has an explicit 500-line cap with a "move to supporting files" pattern

**Source**: [#2] Anthropic Claude Code skills documentation

**Quote**: "Keep SKILL.md under 500 lines. Move detailed reference material to separate files."

The supporting-files pattern: SKILL.md is the entry point (index); `reference.md`, `examples.md`, etc. are satellite files that load only when the skill explicitly reads them. The SKILL.md lists supporting files explicitly so Claude knows they exist.

**Relevance to our project**: The skills architecture is the native Claude implementation of the plan's "index-front + per-file satellites" pattern. For the `docs/migration/` refactor, the structural analogue is: INDEX.md (500-line max, entry point) → per-doc stub sections → full docs as separate files (loaded on demand). The plan's per-file INDEX sidecars should be internal to the INDEX.md master file as named entries, not separate sidecar files, to stay consistent with the SKILL.md pattern.

**Anchor**: Operationally stable pillar.

**Confidence**: High — primary Anthropic documentation.

---

### Finding 8: AI agent traffic at documentation sites is nearly tied with human traffic (45.3% agents vs. 45.8% humans)

**Source**: [#7] Mintlify state of AI agents in documentation (March 2026), across 790 million requests

Claude Code alone generated 199.4 million requests in 30 days — surpassing Chrome on Windows (119.4M). Agents require documentation that is "structured, comprehensive, and easy to parse programmatically."

**Relevance to our project**: This is calibrating data, not a prescription. It confirms that optimizing documentation for agent consumption is commercially and operationally significant. The UDM project's docs serve agent readers (via CCL) as their primary consumer — humans read them at round close-out, but agents read them at every invocation. This inverts the conventional assumption that docs are primarily human-facing with occasional AI skimming.

**Anchor**: Operationally stable pillar — treating agents as first-class readers is not speculative; it is the documented production reality.

**Confidence**: High — primary data from a major documentation platform.

---

### Finding 9: YAML frontmatter for AI discoverability is emerging but not consumed natively by Claude Code without tooling

**Sources**: [#8] MAGI spec, blog.trysteakhouse.com (Front-Matter Standard), llms.txt spec [#3]

The MAGI spec (Mintlify) extends Markdown with: YAML frontmatter (`doc-id`, `title`, `tags`, `purpose`, dates), `ai-script` blocks that guide summarization, and footnote-based relationship declarations (`parent`, `child`, `cites`, `related`).

The "Front-Matter Standard" proposes treating YAML headers as a programmatic API for AI crawlers: semantic layer (entities, summary, topic_cluster) distinct from presentation layer (build-engine directives).

**Critical gap**: Neither MAGI nor the Front-Matter Standard shows Claude Code consuming YAML frontmatter natively from project-internal markdown files. The frontmatter-as-signal pattern is primarily for web-crawlers, RAG pipelines with dedicated extractors, and llms.txt-adjacent discovery systems. Without a parser (tooling not in stdlib) or explicit Claude instruction to read the frontmatter, YAML frontmatter in internal docs is inert from an agent navigation perspective.

**Relevance to our project**: Phase 4's frontmatter proposal has no evidence of native agent consumption in Claude Code. It could function as human-readable metadata (valid on its own terms) and as input to the plan's `tools/regenerate_md_indexes.py` script (the generator reads frontmatter to build the INDEX.md). But it should NOT be presented as "AI-readable" metadata in the plan without acknowledging the tooling gap. The plan should clarify: frontmatter is machine-readable via the regenerator script, not natively consumed by Claude during a CCL read.

**Anchor**: Audit-grade pillar — avoid overclaiming what the system does.

**Confidence**: Medium — absence of evidence in primary Claude docs + confirmed consumption in RAG/web contexts only.

---

### Finding 10: Context "rot" is documented and measurable — quality degrades predictably as context fills

**Sources**: [#12] Chroma "Context Rot" research, [#13] Prem AI benchmark guide (2026)

The January 2026 systematic analysis identified a "context cliff" around 2,500 tokens of retrieved context where response quality drops. A Vectara/NAACL 2025 study found chunking configuration had as much influence on retrieval quality as embedding model choice. Models claiming 200K context become unreliable around 130K; 1M-context models degrade around 600K–700K tokens.

**Relevance to our project**: Reading 12K–16K lines per CCL invocation at startup is consuming roughly 12K–20K tokens before the agent sees the actual task prompt. For claude-sonnet-4-6 with its context window, this is a non-trivial fraction. The plan's stated goal of reducing per-invocation context load from ~12K–16K lines is grounded in the documented context-rot phenomenon: starting agents with leaner context produces better task performance. This validates Phase 1's priority: reducing startup read cost is a quality-improvement mechanism, not just a cost-cutting one.

**Anchor**: Operationally stable pillar — context rot is an operational failure mode.

**Confidence**: High — multiple independent benchmarks.

---

### Finding 11: Subagents are the native Claude Code pattern for "read large documentation without polluting main context"

**Source**: [#1] Anthropic best practices, [#2] skills documentation

**Quote** (best practices): "Delegate research with 'use subagents to investigate X'. They explore in a separate context window and report back summaries."

**Quote** (skills): "context: fork — runs the skill in a forked subagent context."

The subagent pattern is: parent spawns a child with an isolated context; child reads as many files as needed; child returns only a summary to parent. The parent context never sees the raw file content.

**Relevance to our project**: The CCL pattern (every agent reads 7–11 files at startup in its own context) is the opposite of this pattern. CCL is designed for sequential single-agent workflows where context accumulates. For multi-agent teams (Pattern E, Pattern F), the native architecture would be: one research subagent does the CCL read and summarizes findings; other agents in the team receive the summary, not the raw files. The plan does not address this multi-agent dimension. It should: a `udm-context-loader` subagent that performs CCL and distills into a structured brief would reduce context overhead across the team. This is a gap in the current plan.

**Anchor**: Operationally stable pillar + cost ceiling.

**Confidence**: High — primary Anthropic documentation; the pattern is explicitly recommended.

---

### Finding 12: Diátaxis framework applies to documentation structure but not to agent navigation mechanics

**Source**: [#11] diataxis.fr

Diátaxis classifies documentation into Tutorials (learning), How-to guides (problem-solving), Reference (information lookup), and Explanation (understanding). AI agents can be configured to enforce and classify content by quadrant. Several Claude Code skill implementations of the Diátaxis classifier exist.

**Relevance to our project**: Diátaxis is relevant as a content-organization framework but does not address the token-cost problem of startup reads. The UDM docs already implicitly follow Diátaxis: `NORTH_STAR.md` ≈ Explanation; `CHECKS_AND_BALANCES.md` ≈ Reference; `05_RUNBOOKS.md` ≈ How-to; `phase1/01_database_schema.md` ≈ Reference. Explicitly labeling docs by Diátaxis quadrant in frontmatter (Phase 4) could help agents that are given a "navigate by quadrant" instruction, but there is no evidence Claude Code does this natively. Low priority for the refactor plan unless the team adopts an explicit quadrant-routing skill.

**Anchor**: Traceability pillar (organizing content for auditability).

**Confidence**: Medium — Diátaxis is a well-established framework; its application to agent navigation is speculative.

---

### Finding 13: Pre-commit hook for index regeneration is technically feasible but carries friction risk documented in the community

**Sources**: Community data on pre-commit hook adoption patterns

Pre-commit hooks that auto-regenerate clients and fail-if-stale are a known pattern. The standard pre-commit framework (pre-commit.ci) schedules weekly autoupdates. Friction pattern: agents (GitHub Copilot, Claude Code) have difficulty with pre-commit + pre-push hooks because the agent creates a commit, the hook fires, the hook fails or modifies files, and the agent does not retry in the expected way.

**Relevance to our project**: The plan's Phase 2 pre-commit hook for index regeneration creates a risk: if an agent writes to `BACKLOG.md` or `HANDOFF.md` and the hook modifies `INDEX.md` as a side effect, the agent may encounter an unexpected dirty-tree state on commit. The hook should be structured as: (1) run the regenerator, (2) add `INDEX.md` to the commit if changed, (3) succeed (not fail-if-stale, since the agent cannot be expected to retry). Alternatively, treat index regeneration as a round-close-out step (human-triggered) rather than a pre-commit hook. The "fail-if-stale" pattern that works for human developers is an anti-pattern when the committer is an AI agent.

**Anchor**: Operationally stable pillar — pre-commit hooks must not block agent commit workflows.

**Confidence**: Medium — inferred from Claude Code commit-workflow documentation + community reports; no direct test of this specific scenario.

---

## Recommendation

The research supports the plan's direction with five specific adjustments:

**1. Validate Phase 1 (Index-front) — with a framing correction**
The master INDEX.md is the correct structural intervention and maps directly to the llms.txt standard and the SKILL.md entry-point pattern. However, the per-file INDEX sidecars should focus on "when to read / when to skip" routing signals, NOT on structural summaries of file contents. ETH Zurich research (Finding 5) shows structural overviews increase cost without improving navigation. Each INDEX entry should answer: "If you need X, read this file. If you need Y, skip this file and read Z instead."

**2. Elevate Phase 4's `udm-find-canonical` skill to Phase 1 or Phase 2**
The skill (Option T3) is the native Claude Code mechanism for on-demand reference lookup. Implementing it early is higher-leverage than frontmatter (Phase 4). The skill's SKILL.md body should be under 500 lines with the full canonical-home routing table in a supporting `routing-table.md` file.

**3. Modify Phase 2's pre-commit hook design**
Change from "fail-if-stale" to "auto-add-if-changed." This prevents the hook from blocking agent commit workflows. Consider making index regeneration a step in `udm-round-closeout` (human-triggered at round boundaries) rather than a per-commit event. The CCL Stage 0 "read INDEX.md first" instruction is the primary mechanism; the pre-commit hook is secondary.

**4. Clarify Phase 4's frontmatter scope**
YAML frontmatter is NOT natively consumed by Claude Code as routing metadata. Its value is: (a) human readability, (b) machine-readable input for the `tools/regenerate_md_indexes.py` script. Phase 4 should state this explicitly. Do not frame frontmatter as "AI-readable" without qualifying "only via the regenerator tool."

**5. Add a multi-agent dimension — propose a `udm-context-loader` subagent**
Not in the current plan. The subagent pattern (Finding 11) means: one agent performs the full CCL read in an isolated context and summarizes into a structured brief; other agents in Pattern E teams receive the brief. This could reduce per-agent startup cost from 12K–16K lines to ~500–1K lines for downstream agents. Low-cost to add to the plan's Phase 2 as an optional advanced optimization; high-value for multi-agent Pattern E cycles.

---

## Counter-evidence

**Against Phase 1 (index-front)**:
ETH Zurich (Finding 5) found that "architectural overviews and repository structure explanations did not meaningfully reduce time spent locating relevant files." If the INDEX.md reads like a table of contents / structure overview, it may not help navigation and may add cost. The counter is that llms.txt (Finding 4) is specifically designed to solve this, and the key is routing-by-intent rather than structure-by-description. The plan must implement the distinction.

**Against pre-commit hooks**:
The community evidence (Finding 13) suggests AI agents have known difficulties with pre-commit hooks modifying the working tree. No primary benchmark quantifies the failure rate. Risk is real but may be low-frequency in practice.

**Against file splitting (Phase 3)**:
No source shows that splitting a 7,000-line planning doc into smaller files improves agent accuracy in a project-internal (not RAG) context. The threshold evidence (Finding 6) applies to agent-directive files (CLAUDE.md/AGENTS.md), not reference documentation. The 500-line SKILL.md cap (Finding 7) is the closest analogue and does apply.

**Against frontmatter (Phase 4)**:
MAGI is an emerging standard with no evidence of native Claude Code consumption. There is no industry case study showing YAML frontmatter in internal project docs improving Claude's navigation accuracy.

---

## What this research does NOT cover

- Quantitative benchmarks on index-front vs. no-index for internal planning-doc corpora specifically (not web docs, not code repos). No such study was found.
- Specific token cost measurements for CCL reads in claude-sonnet-4-6. The 12K–16K line estimate is from the plan; no external source validates it.
- Performance comparison of the archive pattern vs. the split pattern for `_validation_log.md` (7,129 lines). Both are reasonable; no external benchmark adjudicates.
- The interaction between CCL and Claude Code's auto-compaction behavior. Auto-compaction re-attaches invoked skills at a combined 25K token budget — whether this applies to CCL docs read via the Read tool is not documented.
- Any tool or framework for automated cross-reference link-checking in internal markdown repos without external dependencies (the plan deliberately avoids non-stdlib dependencies; no stdlib-only solution was surfaced).

---

## Confidence assessment

🟡 Medium — multiple authoritative sources agree on directional patterns; the research gap is the absence of a benchmark study for project-internal (non-web, non-RAG) markdown doc navigation specifically. The findings are extrapolations from adjacent domains (web docs, code repos, agent-directive files) applied to a planning-doc corpus. The directional findings are consistent across sources; the magnitudes are not empirically grounded for this use case.

---

## Suggested follow-up

1. **Producer should validate** the Phase 1 INDEX.md design against llms.txt structure (H1 project name, blockquote summary, sections with routing-intent descriptions per file). This grounds the design in the adopted open spec.
2. **Producer should reconsider** the Phase 4 frontmatter framing — change "AI-readable metadata" to "machine-readable input for the regenerator script" to avoid overclaiming.
3. **Producer should add** a Phase 2 item: `udm-context-loader` subagent design (or explicit discussion of why the subagent pattern does not apply to this project's CCL discipline).
4. **Producer should modify** Phase 2's pre-commit hook from "fail-if-stale" to "auto-add-if-changed" to preserve agent commit compatibility.
5. **Validation Gate 2** can mark the following claims in the plan as now supported by external evidence:
   - "Index-front is an industry-recognized pattern" — YES (llms.txt + SKILL.md entry-point pattern)
   - "Large files should be split at ~500–1000 lines" — PARTIALLY (500-line SKILL.md cap is primary; 150-200-line AGENTS.md cap applies to directive files only)
   - "Frontmatter aids AI navigation" — UNSUPPORTED for native Claude Code; supported only via external tooling

---

*Research complete. No further tool calls needed for this question. Adjacent research questions not investigated: Snowflake documentation conventions for AI agents (Phase 5); semantic search within Claude Code project docs (out of scope for Phase 1–4 refactor); llms-full.txt vs. llms.txt tradeoffs.*
