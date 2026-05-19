# Research: LLM Handoffs, Traceability, and Hallucination Defenses

**Date**: 2026-05-18
**Triggered by**: on-demand (explicit user request)
**Question**: What do 2024-2026 primary sources say about (1) multi-session/multi-agent context handoff patterns, (2) audit-trail traceability for LLM-assisted decisions, and (3) hallucination root causes, detection, and mitigation for coding systems? Evaluate the UDM pipeline project's existing discipline stack against those findings.
**Anchor**: D55, D56, D60, D62, D114; udm-session-compactor (B-492); _validation_log.md discipline; Mechanism C-1 git hooks; 14-edge-case series

---

## Summary

The 2024-2026 research corpus validates the UDM project's core handoff, traceability, and hallucination-defense disciplines at a high level, while surfacing two concrete gaps: (1) the project lacks structured persistent state that survives context compaction without information loss (the udm-session-compactor skill is Phase 1/manual, and SESSION_RESUME.md is a lightweight pointer rather than a CMV-class snapshot), and (2) the project has no runtime hallucination-detection layer that operates independently of the producer—all current defenses are producer-side or post-commit. The most actionable recommendations are adding a snapshot-trim policy to the session compactor, deploying a verifier-model pattern on D-N/B-N claims before they enter primary docs, and formalizing the gap between ISO 42001 content traceability (which the D-N pattern satisfies) and EU AI Act process traceability (which requires per-actor timestamped event logs even for AI-assisted planning decisions). Confidence overall: medium-high for §1 and §3 (multiple primary sources), medium for §2 (traceability standards are moving quickly and this project does not yet operate under EU AI Act high-risk AI classification, but the regulatory direction is clear).

---

## Sources cited

| # | URL | Date accessed | Authority |
|---|---|---|---|
| 1 | https://arxiv.org/html/2602.22402 | 2026-05-18 | Academic (Imperial College London) |
| 2 | https://arxiv.org/pdf/2511.00776 | 2026-05-18 | Academic (ACM/arXiv) |
| 3 | https://arxiv.org/html/2509.18970v1 | 2026-05-18 | Academic (arXiv) |
| 4 | https://arxiv.org/html/2604.08224v1 | 2026-05-18 | Academic (arXiv) |
| 5 | https://arxiv.org/html/2604.03826v1 | 2026-05-18 | Academic (arXiv, 2026) |
| 6 | https://claude.com/blog/building-agents-with-the-claude-agent-sdk | 2026-05-18 | Anthropic (primary vendor documentation) |
| 7 | https://www.anthropic.com/engineering/multi-agent-research-system | 2026-05-18 | Anthropic (engineering blog, production evidence) |
| 8 | https://www.isms.online/frameworks/iso-42001/iso-42001-logging-lifecycle-traceability-vs-eu-ai-act/ | 2026-05-18 | Practitioner (ISMS.online; summarizes ISO 42001 + EU AI Act Articles 12/19) |
| 9 | https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf | 2026-05-18 | NIST (primary regulatory body) |
| 10 | https://arxiv.org/pdf/2603.24579 | 2026-05-18 | Academic (arXiv, 2026) |
| 11 | https://dl.acm.org/doi/10.1145/3696630.3728702 | 2026-05-18 | Academic (ACM FSE 2025) |
| 12 | https://arxiv.org/pdf/2504.07303 | 2026-05-18 | Academic (arXiv, 2025) |

---

## §1 — Handoffs (multi-session + multi-agent context transfer)

### Finding 1.1: Naive compaction destroys 90%+ of session state; structured-trim is the canonical alternative

- **Source**: [#1] — Contextual Memory Virtualisation (CMV), Imperial College London, 2026
- **Evidence**: Anthropic's native `/compact` command reduced 132k tokens to 2.3k (98% reduction). CMV achieves 12-86% reduction (median 20%, mean 39% for tool-heavy sessions) while preserving every user message, assistant response, and the model's own reasoning — only discarding regenerable raw tool outputs.
- **Key mechanism**: CMV stores structural snapshots (DAG nodes) rather than LLM-generated summaries. "The model's architectural summary of a 847-line file remains; the raw 847-line file dump is removed." The difference is that the model's reasoning is preserved, not just a compressed paraphrase of it.
- **Context-rebuild cost**: Without snapshots, rebuilding destroyed context costs 10-20 user turns and 15-30 minutes. With a CMV snapshot, the full prior context loads in a single prompt ($0.53 at cache-write rates).
- **Relevance to UDM**: The udm-session-compactor skill (B-492, 2026-05-18) uses a 5-section manual snapshot format. This is structurally closer to CMV than to naive compaction — but the project lacks a trimming policy that distinguishes regenerable content (raw tool outputs) from irreplaceable content (agent reasoning, decision rationale). Pillar: **Traceability** (preserving reasoning chain across sessions).
- **Confidence**: High

### Finding 1.2: Structured-artifact handoff (not shared context) is the production-validated pattern for multi-agent systems

- **Sources**: [#6], [#7] — Anthropic Claude Agent SDK documentation + multi-agent research system engineering blog
- **Evidence**: Anthropic's production multi-agent research system uses a LeadResearcher agent that saves its plan to external Memory before spawning subagents, because "if the context window exceeds 200,000 tokens it will be truncated." Subagents return only structured excerpts, not their full context. The SDK's recommended pattern: "gather context → take action → verify work → repeat," with file system as primary persistence layer.
- **SDK capability**: The Claude Agent SDK's `compact` feature automatically summarizes when approaching context limits. For long-running agents, Anthropic recommends an initializer agent (sets up environment on first run) + coding agent (makes incremental progress, leaving clear artifacts for the next session).
- **Empirical finding**: "Token usage explains 80% of the variance" in research quality. Multi-agent systems consume 15x more tokens than chats — economic discipline on token budget is load-bearing.
- **Relevance to UDM**: The UDM project's CCL (Canonical Context Load, D62) + INDEX.md CCL Stage 0 routing + 5-tracker canonical set follows this pattern exactly — agents load structured state from external files rather than relying on shared context. This is validated by Anthropic's own production practice. Pillar: **Operational stability**.
- **Confidence**: High

### Finding 1.3: Four memory dimensions must be externalized for reliable multi-session continuity

- **Source**: [#4] — "Externalization in LLM Agents", arXiv 2604.08224, 2026
- **Evidence**: The unified review identifies four externalization dimensions: (a) working context (live task state, files, checkpoints), (b) episodic experience (prior runs with decisions and failures), (c) semantic knowledge (domain heuristics), (d) personalized memory (interaction history). The paper identifies four failure modes: stale memories, over-abstraction, under-abstraction, and poisoned memories.
- **Key finding**: "Retrieval quality matters more than raw storage capacity" — the goal is making the right history legible at the right moment, not storing everything.
- **Relevance to UDM**: The 5-tracker canonical set (BACKLOG + CURRENT_STATE + HANDOFF + CODE_BUILD_STATUS + _validation_log) maps approximately to dimensions (a), (b), and (c). The project has no explicit mechanism for dimension (d) (agent-specific interaction history), which is consistent with the project's human-in-the-loop model. Pillar: **Traceability** (episodic experience), **Operational stability** (working context).
- **Confidence**: Medium (paper is a review without controlled experiments)

### Finding 1.4: Shared context vs. structured artifact tradeoff — 70-90% token reduction with 500ms-1.5s latency cost

- **Source**: [#12] — "Modeling Response Consistency in Multi-Agent LLM Systems", arXiv 2504.07303, 2025
- **Evidence**: Summarized context reduces token count by 70-90% versus full conversation forwarding (200-500 tokens vs. 5,000-20,000 tokens) but introduces summarization latency and information loss. Production deployments use Redis or PostgreSQL indexed by conversation_id for persistent state across sessions.
- **Relevance to UDM**: The UDM project uses markdown files rather than a database backing store for persistent state, which is appropriate for a planning/documentation project (not a runtime agent system). The SESSION_RESUME.md + _session_snapshots/ directory is the project's analog of this pattern. Pillar: **Operational stability**.
- **Confidence**: Medium

---

## §2 — Traceability (audit trail for LLM-assisted decisions)

### Finding 2.1: Content traceability and process traceability are distinct requirements with different enforcement mechanisms

- **Source**: [#8] — ISO 42001 vs. EU AI Act analysis (ISMS.online, summarizing Articles 12/19)
- **Evidence**: Content traceability (ISO 42001 emphasis) focuses on WHY decisions occurred — rationale, business context, approval authority. Process traceability (EU AI Act emphasis) demands forensic-level proof of WHAT happened — complete event sequences, actor identity, timestamp precision, system state linkage. ISO 42001 grants discretion on event scope and retention; the EU AI Act mandates automatic logging with no discretionary gaps, six-month minimum retention, and individual/system attribution per entry.
- **Key finding**: Two-thirds of EU AI enforcement actions stem from traceability breakdowns at team handoffs and system boundaries where logs fragment across silos.
- **Relevance to UDM**: The D-N decision record pattern (03_DECISIONS.md) satisfies content traceability — it captures rationale, pillar mapping, and supersession chains. The _validation_log.md + PipelineEventLog satisfy process traceability for runtime events. The gap is in AI-assisted planning decisions: when an LLM agent writes a D-N body, the actor attribution in the validation log (e.g., "agentId a38e85eab71d1b477") satisfies the "who" but not the "which model version" or "which context at time of generation." Pillar: **Audit-grade**, **Traceability**.
- **Confidence**: Medium-high (EU AI Act Articles 12/19 are primary law; enforcement case evidence is from practitioner sources)

### Finding 2.2: LLM-assisted ADR generation is validated but requires Last-K context strategy and chronological ordering

- **Source**: [#5] — "Context Matters: Evaluating Context Strategies for Automated ADR Generation Using LLMs", arXiv 2604.03826, 2026
- **Evidence**: Evaluated five context strategies across 750 OSS repositories. Last-K (3-5 recent ADRs) achieved peak performance comparable to All-History while dramatically reducing token usage. LLM-generated ADRs averaged 1,123 tokens vs. 527 tokens for human-authored records — LLMs produce more verbose but more self-contained justifications.
- **Failure modes found**: (a) LLMs lose implicit organizational context not captured in prior ADRs; (b) semantic retrieval (RAFG) disrupts chronological continuity, severing causal decision chains; (c) external reference dependencies (wikis, design docs) cannot be captured by LLMs without access.
- **Production recommendation**: "Default to Last-K strategies rather than complex retrieval systems; recency heuristics prove nearly equivalent." Maintain self-contained ADRs with explicit rationale (avoid external references that obstruct future agents).
- **Relevance to UDM**: The D-N pattern already follows this — each decision is self-contained with explicit rationale and pillar mapping. The CCL Last-K analog is the INDEX.md CCL Stage 0 + HANDOFF.md §2 read order, which gives agents recent context. The project's chronological D-number ordering preserves decision path-dependency. Pillar: **Traceability**.
- **Confidence**: High (primary academic source with controlled evaluation)

### Finding 2.3: NIST AI RMF requires traceable measurement basis for AI-assisted decisions

- **Source**: [#9] — NIST AI 600-1 (Generative AI Profile, released July 2024)
- **Evidence**: "Where tradeoffs among the trustworthy characteristics arise, measurement provides a traceable basis to inform management decisions." Documentation must "provide sufficient information to assist relevant AI Actors when making decisions." The AI RMF emphasizes TEVV (Test, Evaluation, Verification, Validation) processes that are "objective, repeatable, or scalable" and documented.
- **Relevance to UDM**: The _validation_log.md + CHECKS_AND_BALANCES.md 5-gate discipline directly implements the NIST TEVV requirement — each gate is documented, each validation event is logged with reviewer agent ID. The gap is that NIST AI 600-1 specifically addresses generative AI risk and recommends documenting the model version and context size used in AI-assisted decisions. The UDM project logs agent IDs but not model version or context pressure at time of decision. Pillar: **Audit-grade**.
- **Confidence**: High (primary NIST source)

### Finding 2.4: Process traceability at system boundaries is the highest-risk failure point

- **Source**: [#8] (EU AI Act enforcement case analysis)
- **Evidence**: "Three of Europe's most impactful AI enforcement cases in 2024 were triggered not by biased algorithms, but by logging failures — missing, ambiguous, or inaccessible records." Traceability failures concentrate at team handoffs and system boundaries.
- **Relevance to UDM**: The UDM project's CCL discipline specifically addresses the boundary problem — every agent reads canonical state before acting. The _validation_log.md audit trail with reviewer agent IDs addresses attribution at the handoff point. However, the agent ID (e.g., "agentId a38e85eab71d1b477") is not the same as model version + system prompt hash, which is what EU AI Act process traceability requires. Pillar: **Audit-grade**, **Traceability**.
- **Confidence**: Medium (practitioner source, not primary EU law text)

---

## §3 — Hallucination (root causes, detection, mitigation)

### Finding 3.1: Code-specific hallucination taxonomy — four dominant sub-types

- **Source**: [#2] — "A Systematic Literature Review of Code Hallucinations in LLMs", arXiv 2511.00776, 2025 (60 papers reviewed)
- **Evidence**: Four sub-types dominate code hallucination: (a) API hallucination (fabricated methods from libraries), (b) library-version drift (conflating API versions with conflicting signatures in training data), (c) function-signature hallucination (incorrect parameters/return types that compile but are functionally incompatible), (d) file-path confabulation (invented file paths and import statements reflecting learned patterns without validation against actual project structure).
- **Most effective mitigations found**: RAG grounding (constraining output to documented APIs), chain-of-thought + self-verification (step-by-step reasoning with spec check), prompt engineering with explicit version/import constraints, in-context examples.
- **Runtime detection**: Static analysis (undefined references, incorrect function calls), execution-based testing in sandboxes, semantic API checking against documentation databases.
- **Key limitation**: "No single approach fully eliminates code hallucinations. Most effective solutions combine multiple strategies."
- **Relevance to UDM**: The UDM project's Tier 0/1/2/3/4 test pyramid directly implements the execution-based detection (running generated code catches hallucinated APIs at CI). The pre-commit hook `check_9n_new_public_surface_reminder` catches function-signature-registration gaps. The CLAUDE.md Do NOT rules encode explicit version/API constraints that reduce prompt-level hallucination. File-path confabulation is the least-mitigated sub-type — the project has no automated file-path validation layer. Pillar: **Idempotent**, **Operational stability**.
- **Confidence**: High (systematic literature review, primary academic source)

### Finding 3.2: Agent-specific hallucination taxonomy — five types distinct from general LLM hallucination

- **Source**: [#3] — "LLM-based Agents Suffer from Hallucinations: A Survey", arXiv 2509.18970, 2025
- **Evidence**: Five types unique to agentic systems: (1) Reasoning hallucination (flawed plans, misinterpreted goals), (2) Execution hallucination (incorrect tool selection/invocation from documentation gaps), (3) Perception hallucination (inaccurate environmental observation), (4) Memorization hallucination (reliance on corrupted/stale memory), (5) Communication hallucination (erroneous inter-agent message propagation). Critical property: agent hallucinations span multiple modules, accumulate across steps, and produce physically consequential errors — they cannot be detected by checking individual outputs in isolation.
- **Mitigation ranking from survey**: Knowledge utilization (expert knowledge bases, rules) > Paradigm improvement (contrastive/causal learning) > Post-hoc verification (self-verification + validator assistance). Structured JSON inter-agent communication (vs. natural language) mitigates "talking past each other" scenarios.
- **Producer-reviewer separation**: The survey discusses "Validator Assistance" as post-hoc verification but does not specifically analyze dedicated producer-reviewer separation architectures. The closest documented evidence is that "external validators can calibrate outputs" — no quantified effectiveness for the specific D55/D56 pattern.
- **Relevance to UDM**: The UDM project's multi-layer defense architecture (Mechanism C-1 hooks + blindspot ledger + udm-gap-check 6-category audit + Pattern F cascade + 14 edge-case series) maps to the survey's "post-hoc verification" category. The producer != reviewer discipline (D55/D56) is a producer-reviewer separation architecture that the survey validates in principle but does not quantify. The structured CASCADE EVIDENCE commit-message format is the project's analog of structured JSON inter-agent communication. Pillar: **Audit-grade**, **Idempotent**.
- **Confidence**: High (survey paper); medium for the producer-reviewer quantification claim (not explicitly tested)

### Finding 3.3: Multi-agent self-check (MARCH-style) reduces hallucinations via independent verification paths

- **Source**: [#10] — "MARCH: Multi-Agent Reinforced Self-Check for LLM Hallucination", arXiv 2603.24579, 2026
- **Evidence**: Multiple independent verification agents outperform chain-of-thought alone by introducing diverse perspectives that catch inconsistencies a single model propagates. Limitation: systematically biased information where all agents agree on false claims escapes multi-agent consensus — the independent agents must have genuinely different knowledge or reasoning paths, not just be different instances of the same model with the same context.
- **Relevance to UDM**: The project's Pattern E paired-judgment (5-agent parallel deep validation) + Pattern F paired-judgment cascade audit directly implements multi-agent self-check. The D56 second-pass requirement (independent reviewer after 🔴) ensures genuinely different reasoning path rather than same-context re-check. The empirical record of 8 cycles finding 5-8 cascade gaps per round (HANDOFF §8 Pitfall #11) substantiates MARCH's finding that multi-agent verification catches errors single-pass misses. Pillar: **Audit-grade**.
- **Confidence**: Medium (paper lacks specific quantification for the UDM-relevant workflow; production evidence from HANDOFF §8 empirical record supplements)

### Finding 3.4: Structured output format constraints reduce hallucination surface significantly

- **Source**: ACM FSE 2025 [#11] + practitioner analysis
- **Evidence**: "Structured output constraints reduce the hallucination surface by constraining the model to fill known fields rather than invent narrative text, turning an LLM call into something closer to a typed function call than a text-generation task. The more structured the LLM output, the easier it is to validate." Output format constraints are a "double-edged sword" — strict enforcement may hinder reasoning; dedicated reasoning models use two-stage generation (unrestricted reasoning → structured final answer).
- **Relevance to UDM**: The CASCADE EVIDENCE commit-message template (TEST / GAP ANALYSIS / REVIEW sections), the D-N decision record template, and the B-N backlog entry format are all structured output constraints applied to agent-generated documentation. The `InlineFixClaimVerificationCheck` CommitMsgCheck subclass specifically validates that fix claims in the structured format correspond to actual staged content. This is a property-based verification of LLM-generated structured output — a recognized hallucination-detection pattern. Pillar: **Audit-grade**, **Idempotent**.
- **Confidence**: High

### Finding 3.5: Claude Sonnet 4.6 hallucination profile — coding-specific

- **Source**: Third-party benchmark analysis (community sources, 2026; no primary Anthropic benchmark disclosure found)
- **Evidence**: Claude Sonnet 4.6 (the model powering this agent, per environment context) achieves 79.6% on SWE-bench. Users preferred Sonnet 4.6 over Sonnet 4.5 roughly 70% of the time in Claude Code "because of improved instruction following, fewer hallucinations, and consistent multi-step task performance." No primary Anthropic disclosure of per-hallucination-type breakdown was found in the research window.
- **Limitation**: No primary Anthropic source was found for TruthfulQA or SimpleQA scores for Sonnet 4.6 specifically. Community benchmark comparisons exist but lack methodological transparency.
- **Relevance to UDM**: The primary agent in this project is Sonnet 4.6. The lack of primary benchmarks for file-path confabulation (the least-mitigated sub-type per Finding 3.1) on this specific model is a gap. The project's mitigation for this is the cross-reference gate (Gate 1, CHECKS_AND_BALANCES.md) which catches invented file paths in D-N bodies.
- **Confidence**: Low (community benchmarks; no primary Anthropic disclosure)

---

## §4 — Synthesis: UDM Project Discipline Stack vs. Research Findings

### §4.1 — Handoffs

**Patterns the project DOES have (validated by research):**

1. **Structured-artifact handoff via canonical external state** (Finding 1.2): CCL mandatory read order (D62) + INDEX.md CCL Stage 0 routing + 5-tracker canonical set is exactly the "store to external memory, retrieve at next agent start" pattern Anthropic validates in production. The LeadResearcher agent saving its plan to memory before spawning subagents is the production equivalent of the CCL.

2. **Episodic experience externalization** (Finding 1.3): _validation_log.md (append-only audit trail of every validation event), _reviewer_effectiveness.md (per-event ledger), and BACKLOG.md (WSJF-prioritized history with closure mechanisms and empirical anchors) collectively implement dimension (b) episodic memory with structured retrieval via B-number search.

3. **Last-K context strategy via read order** (Finding 2.2): The CCL Stage 1 mandatory 4-read sequence prioritizes the most recent authoritative state (CURRENT_STATE.md, HANDOFF.md) over exhaustive history — structurally equivalent to Last-K ADR context strategy, with well-evidenced quality preservation.

**Patterns the project does NOT have:**

1. **Structured-trim snapshot policy** (Finding 1.1 gap): The udm-session-compactor skill (B-492) produces 5-section manual snapshots, but has no policy distinguishing regenerable content (raw tool output logs) from irreplaceable content (agent reasoning chains, decision rationale). CMV research shows that WITHOUT this distinction, naive compaction destroys 98% of nuanced understanding. The project's current snapshot is closer to a structured summary than a structured trim. Recommendation: add a "what to preserve vs. what to shed" taxonomy to the udm-session-compactor SKILL.md.

2. **Versioned DAG for branching workstreams** (Finding 1.1 gap): The _session_snapshots/ directory stores linear snapshots but has no branch-point mechanism. When multiple parallel workstreams run (e.g., Pattern E 5-agent validation), there is no mechanism to fork from a stable state and merge back. This is currently handled by the orchestrator maintaining context, but for long multi-session workstreams it is a gap.

**Anti-patterns the project successfully avoids:**

1. **Naive compaction (destroys reasoning)**: The udm-session-compactor explicitly preserves D-N, B-N, and skill invocation records — not just a prose summary. This avoids the 98% loss failure mode.

2. **Shared mutable context (context pollution)**: The DACS finding (Dynamic Attentional Context Scoping) shows that flat shared context causes inter-agent contamination. The UDM project's independent agent contexts with explicit read-at-start discipline avoids this.

---

### §4.2 — Traceability

**Patterns the project DOES have (validated by research):**

1. **Content traceability via structured decision records** (Finding 2.1, 2.2): The D-N pattern (03_DECISIONS.md) with rationale + pillar mapping + supersession chains is a validated ADR pattern. The research finding that "LLMs produce more self-contained but more verbose ADRs vs. human-authored ones" matches the UDM D-N records, which are intentionally self-contained.

2. **Process traceability via append-only event log** (Finding 2.1): _validation_log.md with reviewer agent IDs, gate outcomes, and empirical anchors satisfies the ISO 42001 content traceability requirement. PipelineEventLog satisfies runtime process traceability with per-step actor attribution and timestamp precision.

3. **TEVV documented + repeatable** (Finding 2.3 — NIST AI RMF): The 5-gate validation discipline (D55), 14 canonical edge-case series, and Tier 0/1/2/3/4 test pyramid collectively implement documented, repeatable TEVV processes. The _validation_log.md is the "documented" evidence record per NIST AI RMF.

**Patterns the project does NOT have:**

1. **Model-version attribution in validation events** (Finding 2.1, 2.3 gap): The validation log records reviewer agent IDs (e.g., "agentId a38e85eab71d1b477") but not the model version (claude-sonnet-4-6) or context pressure (token count) at time of decision. NIST AI 600-1 recommends this for generative AI. EU AI Act Article 19 requires system-level attribution. The gap is low-risk today (project not operating under EU AI Act high-risk classification) but grows as AI-assisted decisions accumulate.

2. **Automated process traceability at system boundaries** (Finding 2.4): The CCL discipline is honor-system (R16 in RISKS.md acknowledges this). EU AI Act enforcement cases cluster at team handoffs — exactly the CCL boundary. The pre-commit hook scans staged content but cannot verify CCL compliance before the agent began. A Session-start audit row (similar to the STARTUP_* EventType family) for agent invocations would close this gap.

**Anti-patterns the project successfully avoids:**

1. **Implicit decision rationale (knowledge vaporization)**: The ADR research finding that LLMs lose implicit organizational context not captured in prior ADRs is avoided by the D-N pattern's mandatory rationale + pillar + risk-delta fields. The project has no decision that is implied rather than stated.

2. **Log fragmentation at system boundaries**: Each agent in the multi-agent system reads the same canonical state (CCL) and writes to the same append-only trackers. The enforcement case pattern (logs fragmenting across silos) is structurally prevented.

---

### §4.3 — Hallucination Defenses

**Patterns the project DOES have (validated by research):**

1. **Structured output format constraints** (Finding 3.4): CASCADE EVIDENCE commit-message template + D-N record template + B-N entry format are structured output constraints on agent-generated content. The `InlineFixClaimVerificationCheck` CommitMsgCheck subclass is a property-based verifier of structured output — the research finding's "typed function call" analog applied to documentation.

2. **Multi-layer post-hoc verification** (Finding 3.2, 3.3): The UDM project's defense stack (Mechanism C-1 pre-commit + udm-gap-check 6-category + Pattern F paired-judgment + udm-cohort-review + InlineFixClaimVerificationCheck) implements the research-validated multi-layer approach. The MARCH finding that multi-agent self-check outperforms chain-of-thought alone is validated by the empirical record: 8 validation cycles each finding 5-8 cascade gaps that self-check missed (HANDOFF §8 Pitfall #11).

3. **Execution-based hallucination detection** (Finding 3.1): The CI test pyramid (Tier 0 smoke + Tier 1 unit + Tier 2 property-based + Tier 3 integration + Tier 4 crash) catches API hallucinations, incorrect function signatures, and file-path confabulations at the code layer. The 2827-baseline pytest count (2026-05-18) is the running anchor.

**Patterns the project does NOT have:**

1. **Runtime token-level uncertainty monitoring** (Finding 3.1 gap): The research identifies per-token perplexity / entropy-based uncertainty as the simplest effective runtime hallucination signal. The project has no mechanism to flag D-N or B-N claims where the LLM's per-token confidence is low. This is tool-level (requires access to logprobs) but would be especially valuable for the `InlineFixClaimVerificationCheck` class — high-entropy "fix claimed" outputs are more likely to be hallucinated claims.

2. **Explicit file-path validation layer** (Finding 3.1 gap): File-path confabulation is the least-mitigated code hallucination sub-type and the one most relevant to a documentation-heavy project. The project's Gate 1 cross-reference check catches some invented D-N / B-N references, but does not validate that skill file paths (e.g., `.claude/skills/udm-session-compactor/SKILL.md`) or code module paths cited in D-N bodies actually exist. A lightweight file-path existence check on all `backtick-path` patterns in staged markdown would catch this class.

**Anti-patterns the project successfully avoids:**

1. **Single-agent verification (same-context re-check)**: The MARCH finding that independent agents with different reasoning paths are required for effective verification is directly implemented by D56's "Producer != first-pass != second-pass agent" rule. The project explicitly rejects self-review as a validation mechanism.

2. **Consensus from homogeneous agents** (MARCH limitation): The project's Pattern E spawns 5 agents with different specializations (gap-check / design-reviewer / test-author / data-engineer-review / researcher), not 5 instances of the same role. This addresses MARCH's identified failure mode (systematically biased consensus where all agents agree on false claims).

---

## §5 — Recommendations

Ranked by estimated effort × impact ÷ risk, descending. All are actionable within the project's existing architecture without requiring parallel session work on scd2/ or parquet/ scope.

### Recommendation 1: Add trim-policy taxonomy to udm-session-compactor SKILL.md

**What**: Extend the SKILL.md with an explicit policy distinguishing (a) regenerable content (raw tool output logs, file listing outputs, test runner stdout) from (b) irreplaceable content (agent reasoning chains, D-N rationale, rejection rationale, empirical anchor citations, reviewer verdict text). Snapshots should preserve (b) verbatim and may omit (a).

**Why**: Finding 1.1 (CMV paper) shows that without this distinction, compaction destroys the reasoning chain while preserving only the surface summary. The udm-session-compactor currently produces a 5-section snapshot but has no policy on what to trim within each section.

**Effort**: 0.5 days (SKILL.md edit + 3-4 Tier 1 assertions to verify the taxonomy is documented and checkable by the skill).

**Impact**: High — prevents the scenario where a compaction event strips agent rationale, causing the next session to reconstruct decisions incorrectly. This directly addresses the 2-3 cohort lag detected by gap-check reviewer ab45539c33d1cebd1 (cited in _validation_log.md 2026-05-18).

**Where it lands**: `.claude/skills/udm-session-compactor/SKILL.md` § regenerable-vs-irreplaceable taxonomy. B-number: propose as a new B-N at next BACKLOG update.

**Cites**: Finding 1.1 [#1], Finding 1.3 [#4].

**Risk**: Low — SKILL.md edit is additive; no code changes required; falls within the producer ≠ reviewer discipline.

---

### Recommendation 2: Add model-version + context-pressure field to _validation_log.md event rows

**What**: Establish a convention (not a tool enforcement) that every _validation_log.md event row includes: (a) the model name/version used (e.g., `claude-sonnet-4-6`), (b) an approximate context pressure indicator (e.g., `context: high / medium / low` based on producer judgment), (c) whether CCL was completed before the event (yes/no). This is a documentation convention, not a software feature.

**Why**: Finding 2.1 (EU AI Act Articles 12/19) + Finding 2.3 (NIST AI 600-1) both require actor-level attribution at AI-assisted decisions. The project logs agent IDs but not model version. As AI-assisted decisions accumulate in D-N and B-N records, the ability to audit "which model version made this recommendation under what context pressure" becomes critical for AI governance defensibility. The EU AI Act high-risk AI timeline begins August 2026; establishing the convention now at zero enforcement cost is prudent.

**Effort**: 0.25 days (add 3-field convention to _validation_log.md header + backfill format guidance in CHECKS_AND_BALANCES.md Gate 2 template).

**Impact**: Medium — closes the process traceability gap (Finding 2.4) at minimal cost. Does not require code changes. The _validation_log.md is already append-only, so no retroactive change needed.

**Where it lands**: `docs/migration/_validation_log.md` header section + `docs/migration/CHECKS_AND_BALANCES.md` Gate 2 template. Propose as D-N decision if adopted (AI governance traceability convention).

**Cites**: Finding 2.1 [#8], Finding 2.3 [#9].

**Risk**: Very low — documentation convention only; zero enforcement mechanism required initially; can be mechanically enforced later via a 10th `check_*` in `tools/pre_commit_checks.py` if pattern drifts.

---

### Recommendation 3: Add file-path existence validation to Gate 1 cross-reference check

**What**: Extend the Gate 1 cross-reference check (`udm-checks-and-balances` SKILL.md + the validator's procedure) to explicitly validate that backtick-path patterns in staged markdown files that look like file system paths (e.g., `.claude/skills/udm-*/SKILL.md`, `tools/*.py`, `tests/tier*/test_*.py`) exist in the repository. Flag missing paths as 🔴 BLOCK candidates.

**Why**: Finding 3.1 (code hallucination systematic review) identifies file-path confabulation as the least-mitigated sub-type and one that compiles correctly but references non-existent targets. In this project, D-N bodies and SKILL.md files frequently cite specific file paths as canonical references. If an agent confabulates a path (e.g., `tests/tier1/test_parquet_source_exactness.py` for a test that hasn't been written yet), downstream agents reading those D-N records may treat the reference as authoritative.

**Effort**: 0.5-1 day (add a 10th `check_file_path_existence` function to `tools/pre_commit_checks.py` using a regex for backtick-path patterns + `os.path.exists()` check + 6-8 Tier 0 assertions).

**Impact**: High for trust in D-N/B-N citation accuracy. Medium overall — this class of error is currently caught only when the phantom file is directly invoked in a test.

**Where it lands**: `tools/pre_commit_checks.py` as a 10th check + `tools/pre_commit_checks.py::CHECKS` registry entry + companion Tier 0 test assertions in `tests/tier0/test_pre_commit_checks.py`.

**Cites**: Finding 3.1 [#2], Finding 3.4 [#11].

**Risk**: Medium — false positives on future-planned file paths cited in D-N proposals before build. Mitigate by: (a) only validating paths in committed (not staged-new) D-N bodies, or (b) treating as WARN rather than BLOCK, consistent with D74 exit code 1 (operational failure, not fatal).

---

### Recommendation 4: Formalize the "regenerable vs. irreplaceable" distinction as a project-wide writing convention

**What**: Add a short "Content durability" section to HANDOFF.md §8 (Pitfall #N sub-classes area) or the udm-session-compactor SKILL.md defining: regenerable content (raw grep output, file listings, test stdout verbatim) should not be preserved verbatim in snapshots or HANDOFF.md; irreplaceable content (reviewer rationale, rejection reasoning, empirical anchor citations, session-specific insight that cannot be reconstructed from primary docs) MUST be preserved verbatim or in a structured log.

**Why**: Finding 1.1 (CMV paper) shows this is the load-bearing distinction for preserving context across compaction. Finding 1.3 (Externalization paper) identifies "over-abstraction" (losing operational details) and "under-abstraction" (flooding prompts with noise) as the two symmetric failure modes. The project currently has no explicit guidance on which is which.

**Effort**: 0.25 days (prose addition to SKILL.md or HANDOFF.md — no code changes).

**Impact**: Medium — prevents the systematic error of compaction stripping the wrong content, which cannot be detected mechanically after the fact.

**Where it lands**: `.claude/skills/udm-session-compactor/SKILL.md` §3 or HANDOFF.md §8 new Pitfall #12 candidate.

**Cites**: Finding 1.1 [#1], Finding 1.3 [#4].

**Risk**: Very low — documentation only.

---

### Recommendation 5: Session-start audit row for agent invocations (CCL compliance signal)

**What**: Establish a convention (not mechanically enforced yet) that every agent spawned in a multi-agent session writes a one-line audit row to _validation_log.md or a dedicated `_session_logs/agent_start_<date>.log` at the START of its CCL, including: (a) agent name/role, (b) model version, (c) which Stage 1 docs were read (CCL compliance evidence), (d) timestamp. This is the Session-start analog of the STARTUP_* EventType family in PipelineEventLog.

**Why**: Finding 2.4 (EU AI enforcement cases cluster at handoff boundaries) + R16 (CCL is honor-system, no hard enforcement). The CCL trace audit currently runs at round close-out (quarterly) — a session-start log would give immediate CCL compliance signal. This also addresses the NIST AI 600-1 "individual or system ID with timestamp" per-event requirement for AI-assisted decisions.

**Effort**: 0.5 days (convention documentation + optional hook in `.claude/hooks/` if D54 PreToolUse hooks become available; until then, agent prompts instruct CCL completion logging).

**Impact**: Medium — closes R16 without requiring new tooling, by shifting the audit signal from quarterly (close-out) to per-session. Also strengthens EU AI Act readiness.

**Where it lands**: Agent prompts in `.claude/agents/udm-*.md` + MULTI_AGENT_GUIDE.md CCL section. Optional future: `_session_logs/agent_start_<date>.log` file format spec.

**Cites**: Finding 2.4 [#8], Finding 2.3 [#9], R16.

**Risk**: Low — documentation convention; no existing behavior broken.

---

## Counter-evidence

**Against Recommendation 1 (trim-policy taxonomy)**: The CMV paper's 12-86% median/max reduction range reflects tool-heavy vs. conversational sessions. The UDM project's sessions are documentation-heavy (markdown reads, grep, structured planning), not tool-heavy (no large raw file dumps). The break-even economics (10 turns for tool-heavy, 40 turns for conversational) may not favor structured trimming in this project's typical session profile. The simpler approach — SESSION_RESUME.md as a human-readable summary — may be adequate. Counter-argument: the empirical anchor (2-3 cohort lag detected by gap-check reviewer) shows the current approach IS losing critical information; the CMV finding explains why.

**Against Recommendation 3 (file-path validation)**: Adding a 10th pre-commit check increases the false-positive rate (R33 — blindspot-ledger false-positive fatigue) and may cause WARN-fatigue on legitimate future-planned file path citations in D-N proposals. The current Gate 1 cross-reference check (human reviewer) may be sufficient. Counter-argument: D-N bodies are written by LLMs whose specific failure mode is file-path confabulation; human-only Gate 1 already has 8 documented instances of missing path catches across the validation history.

**Against Recommendation 5 (session-start audit row)**: The honor-system CCL compliance has held for all 8+ rounds without a documented CCL-skip causing a major error class. The quarterly Pattern F trace audit has been sufficient. Adding per-session logging adds friction without a demonstrated failure event. Counter-argument: R16 explicitly lists this as Medium × Medium = 4 risk; the EU AI Act timeline creates external compliance pressure independent of internal failure evidence.

---

## What this research does NOT cover

- LLM fine-tuning approaches for hallucination reduction (not applicable to this project's runtime model)
- Snowflake-specific agent handoff patterns (parallel session owns Phase 5 / scd2 / parquet scope)
- RAG-over-conversation-history architectures (the project uses structured file retrieval, not vector search; this research does not evaluate which is better for documentation-planning use cases)
- Claude 4.x primary benchmark disclosures for coding-specific hallucination sub-types (no primary Anthropic source found; community benchmarks have methodological opacity)
- HaluEval or TruthfulQA scores for claude-sonnet-4-6 specifically (not found in primary sources during research window)
- Knowledge graph approaches for multi-agent context (MemoryBank, xMemory etc.) — evaluated but out of scope for a Python+SQL-Server planning project
- EU AI Act high-risk AI classification applicability to this project (requires legal determination; pipeline lead should consult compliance team as R38 work progresses)

---

## Confidence assessment

Overall confidence: **Medium-High**

- §1 Handoffs: 🟢 High — multiple primary academic sources (CMV, Externalization review) + Anthropic production evidence converge on the structured-artifact-externalization pattern. The project's approach is well-validated.
- §2 Traceability: 🟡 Medium — primary regulatory sources (NIST AI 600-1, EU AI Act Articles 12/19 summary) are authoritative, but the project's applicability to EU AI Act high-risk classification is uncertain. The D-N / _validation_log.md approach is validated as ADR best practice; the model-version gap is real but not currently a compliance obligation.
- §3 Hallucination: 🟢 High — code-specific hallucination taxonomy [#2] is primary (60-paper systematic review); agent-specific taxonomy [#3] is primary (survey); multi-agent self-check [#10] is empirically supported. The Claude Sonnet 4.6 specific benchmark claim is 🔴 Low (community sources only).
- §4 Synthesis: 🟡 Medium — evaluation of the UDM discipline stack is based on structural pattern-matching to research findings, not empirical measurement. The claims about what the project "does" are grounded in CLAUDE.md, CHECKS_AND_BALANCES.md, and _validation_log.md as read during CCL.

---

## Suggested follow-up

1. **Recommendation 1** (trim-policy): Producer should author a SKILL.md extension for udm-session-compactor with regenerable-vs-irreplaceable taxonomy. Can be a B-N with LOW WSJF (effort 0.5 day; COD 2 given current manual Phase 1 status).

2. **Recommendation 2** (model-version in validation log): Producer should propose as a D-N decision (AI governance traceability convention) with 🟡 Proposed status. If adopted, apply retroactively to the next _validation_log.md event row authored.

3. **Recommendation 3** (file-path validation): Producer should evaluate adding a `check_file_path_existence` 10th check to `tools/pre_commit_checks.py` as a B-N with WARN severity and WSJF medium. Blocked on deciding false-positive policy for future-planned paths.

4. **Recommendations 4+5**: Proposal only — no B-N needed yet; incorporate into next session planning review.

5. **Research gap**: Commission a follow-up research run on "Claude-specific hallucination benchmarks and code-confabulation rates" when primary Anthropic benchmark disclosure becomes available (likely when claude-sonnet-4-6 evaluation card is published).

6. **Validation gate 2 can mark**: Claims in D55/D56 bodies about "producer != reviewer catches N% more bugs" should now cite Finding 3.3 [#10] (MARCH multi-agent verification) as external support. The claim is now research-grounded, not just empirically observed within this project.

---

## Last reviewed

2026-05-18 (initial creation, on-demand research triggered by user request).
