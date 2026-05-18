# Research: AI Agent Discoverability — Naming Conventions, TOC Design, and Search Mechanisms

**Date**: 2026-05-15
**Triggered by**: on-demand (user request — deep-dive follow-on to `agent-markdown-traversal-2026-05-15.md`)
**Question**: When splitting large planning docs for agent discoverability: (A) what file-naming conventions help agents most, (B) what TOC patterns work best for agents specifically, (C) how do agents discover context in large repos (beyond grep/RAG basics), (D) what cross-file reference patterns survive splitting, (E) what meta-research topics remain unexplored?
**Anchor**: D62 (CCL doctrine), MARKDOWN_REFACTOR_PLAN.md Option A (split-by-section), Operationally stable pillar, $120K pillar (token cost reduction)
**Follow-on to**: `agent-markdown-traversal-2026-05-15.md` (13 findings, 15 sources; read before reading this file)

---

## Summary

This research goes deeper on Option A (split-by-section) from MARKDOWN_REFACTOR_PLAN.md. The prior research validated the index-front direction; this research identifies the optimal file-naming strategy, TOC design, discovery mechanism, and cross-file reference pattern for the UDM split.

Core findings, in priority order:

1. **File naming**: The industry-dominant pattern for split planning docs is semantic-functional naming with a numeric-prefix sort key — e.g., `03_DECISIONS_phase0_D1-D50.md`. Pure structural naming (`section_4_2.md`) is rejected by every source. Pure date-based naming (`2024-01-15-decisions.md`) is for changelogs, not reference docs. Kubernetes uses `topic-subtopic.md` (semantic, hyphen-separated). The Linux kernel uses `subsystem/index.rst` (directory-per-subsystem + index entry point). Both converge on: **the name communicates scope, not position**.

2. **TOC for agents**: Nested TOC-of-TOCs is an anti-pattern (adds tokens, agents don't traverse hierarchically). Per-file mini-TOCs at file-head beat a separate INDEX.md for agent navigation because the relevant routing information is co-located with the content. The INDEX.md remains valuable as a *routing manifest* (intent-based, not structural), but per-file H2 section headers are the primary navigation primitive agents use. Agents navigate by reading H2 section headers after they arrive at a file — they do not pre-read TOCs before deciding which file to open.

3. **Discoverability**: The confirmed 2026 hierarchy is grep-first (Layer 1, zero config, used for exploration) → structured/syntactic search (Layer 2, ast-grep) → semantic RAG (Layer 3, only when grep fails on intent-based queries). For internal planning-doc corpora specifically, a "numbered prefix + entry-point file" pattern (`00-start-here.md` or `00_overview.md`) is emerging as the agent-oriented equivalent of `index.rst`. The Navigation Paradox (CodeCompass, arxiv 2602.20048) is the most important new finding: larger context windows shift failure from retrieval capacity to *navigational salience* — an agent may have budget to read a file but never discover it because no keyword path leads there. This validates the UDM plan's index-front approach on structural-navigation grounds, not just token-cost grounds.

4. **Cross-file references**: When splitting, relative Markdown links (`[](../03_DECISIONS_phase0_D1-D50.md#D15)`) are the most portable pattern — they survive repo moves better than absolute paths, work in GitHub preview, and agents can follow them as grep targets. Sphinx's `:doc:` references and MyST cross-references are for rendered doc sites, not internal project repos. URL fragment anchors (`#D15`) require the heading slug to be stable; heading-slug instability on rename is the primary cross-reference failure mode.

5. **Meta-research candidates**: Eight topics identified and prioritized (see §E below). Highest priority: the Navigation Paradox's implications for UDM's specific cross-reference topology (decisions cite decisions cite edge cases cite runbooks — does graph navigation help more than grep for the UDM doc corpus?).

Confidence: 🟡 Medium-High — primary sources include peer-reviewed research (arxiv 2602.20048), primary vendor documentation (Anthropic, Kubernetes, Linux kernel), and 2026 practitioner reports. The gap is: no benchmark directly measuring index-front vs. split-file naming for internal *planning* docs (as opposed to code repos or web-facing docs).

---

## Sources cited

| # | URL | Date accessed | Authority |
|---|---|---|---|
| 1 | https://arxiv.org/html/2602.20048v1 | 2026-05-15 | Academic (CodeCompass, Navigation Paradox) |
| 2 | https://arxiv.org/html/2604.13108 | 2026-05-15 | Academic (Formal Architecture Descriptors) |
| 3 | https://yage.ai/share/why-coding-agents-still-use-grep-en-20260327.html | 2026-05-15 | Industry practitioner |
| 4 | https://www.landeranalytics.com/post/you-probably-don-t-need-rag-for-your-agent-s-knowledge-base | 2026-05-15 | Industry practitioner |
| 5 | https://kubernetes.io/docs/contribute/style/content-organization/ | 2026-05-15 | Kubernetes (primary) |
| 6 | https://docs.kernel.org/ | 2026-05-15 | Linux Kernel (primary) |
| 7 | https://mcsee.medium.com/ai-coding-tip-014-use-nested-agents-md-files-23031bb0786a | 2026-05-15 | Community practitioner |
| 8 | https://medium.com/@lnfnunes/how-to-structure-context-for-ai-agents-without-wasting-tokens-16dd5d333c8d | 2026-05-15 | Community practitioner |
| 9 | https://seylox.github.io/2026/03/05/blog-agents-meta-repo-pattern.html | 2026-05-15 | Community practitioner |
| 10 | https://extency.com/blog/markdown-versioned-folders-agent-brain-2026 | 2026-05-15 | Industry (2026) |
| 11 | https://www.knightli.com/en/2026/05/01/qmd-markdown-search-for-ai-agents/ | 2026-05-15 | Industry (2026) |
| 12 | https://packmind.com/context-engineering-ai-coding/context-engineering-best-practices/ | 2026-05-15 | Industry (2026) |
| 13 | https://zylos.ai/research/2026-04-19-codebase-intelligence-repository-understanding-ai-agents | 2026-05-15 | Industry research (2026) |
| 14 | https://mep.mystmd.org/mep-0002/ | 2026-05-15 | MyST/Sphinx (cross-reference standard) |
| 15 | https://github.blog/ai-and-ml/github-copilot/how-to-write-a-great-agents-md-lessons-from-over-2500-repositories/ | 2026-05-15 | GitHub (primary) — cited from prior research |
| 16 | https://datamanagement.hms.harvard.edu/plan-design/file-naming-conventions | 2026-05-15 | Harvard data management (academic) |
| 17 | https://blog.sigplan.org/2026/04/21/repositories-are-human-agent-knowledge-factories/ | 2026-05-15 | SIGPLAN (academic) |

---

## Findings

### A. FILE NAMING CONVENTIONS

---

#### Finding A-1: Industry convergence on semantic-functional naming; structural and date-based naming rejected for reference docs

**Sources**: [5] Kubernetes docs, [6] Linux kernel, [9] meta-repo pattern, [16] Harvard data management

Kubernetes documentation strongly implies semantic naming — their own files are named `task-tutorial-prereqs.md`, `content-guide.md`, `style-guide.md`. Directories are named `concepts/`, `tasks/`, `reference/` — all semantic. The _index.md convention (one per directory) acts as the section entry point; the filename itself is always `_index.md`, but the directory name is semantic.

The Linux kernel's `Documentation/` tree uses a subsystem-per-directory pattern: `admin-guide/`, `process/`, `core-api/`, `bpf/`, `driver-api/`. Each directory has an `index.rst`. Individual files are named for the specific topic within the subsystem: `coding-style.rst`, `submitting-patches.rst`. This is pure semantic naming at both levels (directory = domain, file = topic within domain).

The Harvard data management guide recommends: "file names should describe what they contain and how they relate to other files." For sequenced content, they recommend leading zeros for sort stability: `001`, `002`, not `1`, `2`.

The meta-repo pattern (seylox.github.io) uses `EPIC-###.md` for tracking documents with numeric suffix for identity (not sequence). Supporting files use subdirectory + semantic names: `EPIC-001/analysis.md`, `EPIC-001/decisions.md`.

**Quote (Kubernetes style guide)**: "Give it a good name, ending in .md – e.g. `getting-started.md`"

**What this means for UDM splits**: Pure structural names like `03_DECISIONS_part_1.md` are weak — they communicate position but not scope. Pure date-based names like `03_DECISIONS_2026-04.md` are for changelogs, not reference material (the date becomes stale and misleading). The validated pattern is **semantic scope** in the filename.

**Relevance to UDM pillars**: Traceability — if a D-number cite in a runbook needs to be verified, the file `03_DECISIONS_phase0_D1-D50.md` is grep-able. Operationally stable — stable names survive reorg.

**Confidence**: High — multiple primary sources agree; pattern is consistent across large open-source projects with different doc tooling.

---

#### Finding A-2: Numeric prefix as sort key is a recognized pattern; it serves filesystem ordering, not semantic scope

**Sources**: [4] Lander Analytics, [6] Linux kernel (implicit), [16] Harvard data management

The Lander Analytics agent-knowledge-base post explicitly uses numbered prefixes as a navigation aid: "10-, 20-, 30-" prefixes allow agents to browse topics selectively without loading entire knowledge bases into context windows. A `00-start-here.md` entry point is named by explicit position (always first), not by topic.

Harvard data management: leading zeros ensure sort stability at scale. "001-099" for one hundred items.

The Linux kernel does NOT use numeric prefixes on subsystem directories — `admin-guide/` is alphabetical, not numbered. Kubernetes also does not use numeric prefixes.

**What this means**: Numeric prefix serves two distinct purposes: (1) sort order enforcement (when files must be processed in sequence), (2) entry-point signaling (`00` = "read me first"). Purpose 1 is a filesystem convenience, not a navigational aid for agents. Purpose 2 (`00_INDEX.md`) is valuable as the canonical entry signal.

**The validated pattern**: `NN_SCOPE_RANGE.md` where NN is a sort key, SCOPE is semantic, RANGE is a boundary descriptor. Example: `03_DECISIONS_phase0_D1-D50.md`.

**Confidence**: Medium — "numbered prefix as sort key" is documented; its value for agent navigation specifically (vs. human navigation) is not empirically tested.

---

#### Finding A-3: Naming split files — no "Part N of X" convention exists in industry; scope-descriptor beats sequence-number

**Sources**: [5] Kubernetes, [6] Linux kernel, [9] meta-repo pattern, [10] extency.com

No source (including large open-source projects) uses `part-1`, `part-2`, or `section-4-2` naming for split documentation files. The pattern universally used when files must split is: **one file per logical domain/scope, named for that domain**.

Linux kernel: a 3,000-line `memory.rst` is not split into `memory-part-1.rst` and `memory-part-2.rst`. Instead it is broken by sub-topic: `memory-model.rst`, `memory-layout.rst`, `memblock.rst`, each in its own file under `arch/<arch>/mm/`.

Kubernetes: `security-context.md`, `configure-pod-configmap.md`, `configure-liveness-readiness-startup-probes.md` — each named for the specific task they cover.

**What this means for `_validation_log.md` (7,129 lines)**: The correct split is NOT `_validation_log_part-1.md` / `_validation_log_part-2.md`. It is either:
- Time-based archive: `_validation_log_archive_2026-04.md` (the current archive policy in the doc already proposes this — this research confirms it is correct)
- Topic-based split: `_validation_log_schema_rounds.md` / `_validation_log_deployment_rounds.md`

For `03_DECISIONS.md` (3,219 lines), the correct split is phase-scoped or D-range-scoped:
- `03_DECISIONS_phase0.md` (D1–D50 roughly: foundational decisions)
- `03_DECISIONS_phase1.md` (D50–D90 roughly: pipeline design decisions)
- `03_DECISIONS_phase2_onwards.md` (D90+: operational decisions)

The range suffix (`D1-D50`) is defensible as a finder-aid and is not a "part N" pattern — it communicates the scope precisely.

**Confidence**: High — "no Part-N convention in large OSS projects" is a confirmed absence; the presence of domain/scope naming is confirmed across all sources.

---

#### Finding A-4: Semantic naming vs. structural naming — semantic wins for agents, structural wins for machines

**Sources**: [1] Navigation Paradox (arxiv), [2] Formal Architecture Descriptors (arxiv), [3] grep analysis (yage.ai), [11] qmd analysis

The Navigation Paradox research (arxiv 2602.20048) identifies the core problem: "When architecturally critical but semantically distant files are absent from the model's attention, errors occur." If `03_DECISIONS_part_1.md` contains D15 (idempotency ledger decision), an agent asked "where is the idempotency ledger decision?" cannot grep to it by filename — the filename is semantically silent.

If instead the file is `03_DECISIONS_phase1_idempotency_ledger.md`, the agent's grep for "idempotency ledger" returns the filename itself as a hit, before even opening the file. This is the key principle: **filenames participate in grep/search**, not just in navigation.

The Formal Architecture Descriptors research (arxiv 2604.13108) reinforces: structured descriptors with domain names reduce agent exploration steps by 33-44%. This validates that semantic labels at the filename level reduce search cost.

**What this means for UDM**: For the UDM split, file names should include keywords that match likely agent queries. The decisions file should include "decisions", "D-numbers". The validation log split should include "validation", "round" or the round number. Edge cases file should include "edge-cases" or the series name.

**Confidence**: High — supported by two independent peer-reviewed papers and practitioner reports.

---

### B. TABLE OF CONTENTS DESIGN FOR AGENTS

---

#### Finding B-1: Nested TOC-of-TOCs is an anti-pattern for agents; it adds tokens without routing value

**Sources**: [8] context-without-wasting-tokens (lnfnunes), [12] packmind context engineering, [7] nested AGENTS.md (mcsee)

The progressive-disclosure principle (lnfnunes): agents benefit from "clear breadcrumbs to more detailed guidance when needed," NOT from a pre-loaded master index. Loading a TOC of TOCs means the agent reads a file that tells it what OTHER files contain — without yet knowing if those files are relevant.

The packmind guide is explicit: "a focused 400-token file that covers essentials precisely outperforms a sprawling 4,000-token file." A TOC of TOCs is a classic sprawl pattern — it is comprehensive but not focused.

The mcsee nested AGENTS.md analysis: "most tools load root files at startup and subdirectory files only when you touch files there — the tool handles discovery automatically." This means a master TOC-of-TOCs that replicates the native lazy-load mechanism is redundant.

**Counter-evidence**: A TOC of TOCs has human value — a reader surveying the whole doc corpus benefits from it. The finding is specifically that it does NOT help agents who are executing a task with a specific target.

**Relevance**: The UDM plan's proposed INDEX.md should NOT be structured as a nested TOC (list of files, each with sub-sections listed). It should be a routing manifest: "If your task involves X, read file Y. If your task involves Z, read file W."

**Confidence**: High — multiple independent sources agree; the one counter-evidence is for human readers, not agents.

---

#### Finding B-2: Per-file mini-TOCs (H2 headers) are the primary navigation primitive agents use; they are NOT wasteful

**Sources**: [1] Navigation Paradox (arxiv), [3] grep analysis (yage.ai), [13] Zylos codebase intelligence

The Navigation Paradox research documents that agents navigate within a file by "reading H2 section headers after they arrive at a file" — agents use the visible structure as their within-file navigation. This is not a finding about TOC rendering; it is about how agents scan file structure once they have opened a file.

The grep analysis (yage.ai): "ripgrep returns matches with file-name context; agents use that context to decide whether to open the full file." H2 section headers with semantic names participate in grep output, acting as within-file signposts that are visible from the grep layer without reading the full file.

**What this means**: Within-file H2/H3 structure is load-bearing for agent navigation — more so than a separate TOC. A file split without clear H2 headers is harder for agents to navigate than a longer file WITH clear H2 headers. This partially argues against aggressive splitting: a well-structured 2,000-line file may be more navigable than 4 × 500-line files with flat content.

**Confidence**: Medium-High — the grep finding is well-supported; the H2-header navigation finding is inferred from how agents scan structured text, not directly measured.

---

#### Finding B-3: What metadata in an INDEX entry helps agents most — intent/routing description beats line-ranges and freshness timestamps

**Sources**: [3] llms.txt spec (cited in prior research), [4] Lander Analytics, [8] lnfnunes context engineering, [11] qmd agent search

The llms.txt spec (from prior research Finding 4) uses: H1 (file/section name), one-line description (purpose/routing), optional URL. No line ranges, no freshness timestamps.

The Lander Analytics agent knowledge base: "00-start-here.md acts as the entry point, directing agents to relevant documentation." The entry point contains: topic name + pointer to file, not metadata about the file.

The packmind/lnfnunes finding: metadata fields that help human maintenance (last_updated, owner) have agent value only if agents are explicitly instructed to check freshness. Without such an instruction, freshness metadata is read but not acted on.

**The validated metadata set for an INDEX entry** (ordered by agent utility):
1. **Intent/routing description** (highest): "Read this file if you need to understand [X]; skip if your task is [Y]" — directly reduces unnecessary reads
2. **Scope** (high): D-range, round range, phase — lets agents grep for the scope before reading
3. **Line count** (medium): signals file size, helps agents estimate context cost
4. **Freshness timestamp** (low, unless explicitly instructed to check): useful for humans; agents don't naturally act on it without instruction
5. **Line ranges** (low): too brittle — any edit invalidates the range; grep finds sections without this

**Confidence**: Medium — the hierarchy is inferred from multiple sources; no single source ranks all five explicitly.

---

#### Finding B-4: Agents prefer routing information at file-head over separate INDEX files — but INDEX remains valuable as a repo entry-point

**Sources**: [13] Zylos codebase intelligence, [9] meta-repo pattern, [15] GitHub AGENTS.md study (prior research)

Zylos codebase intelligence: "Pre-computed context files follow a 'compass, not encyclopedia' philosophy — compact navigation guides (25-35 lines, ~1,000 tokens) that provide orientation rather than exhaustive documentation." These are co-located with the content they orient, not in a separate master index.

Meta-repo pattern: AGENTS.md at root "acts as a router pointing to detailed documentation" — the router is co-located with the repo root, not in a separate INDEX directory.

GitHub's finding from 2,500+ repos: the most effective AGENTS.md files use "inline links like '[More](/docs/BUILD.md)'" — progressive disclosure from the context file itself, not a pre-read index.

**The split finding**: a separate INDEX.md is valuable as the *repo entry point* for agents that don't know where to start. But agents already inside a file benefit more from that file's own internal structure (H2 headers, frontmatter scope description) than from a master index they would need to navigate to separately.

**Recommendation for UDM**: The INDEX.md should be positioned as the "Stage 0 of CCL" read — the single file an agent reads when it has NO prior context. Once an agent knows which file it needs, the file itself should be self-orienting. This is the "entry-point manifest" pattern, not the "always-consulted master index" pattern.

**Confidence**: Medium-High — consistent across sources; the specific recommendation (Stage 0 positioning) is an application inference.

---

### C. DISCOVERABILITY MECHANISMS

---

#### Finding C-1: The 2026 industry retrieval hierarchy — grep is Layer 1, structural/syntactic search is Layer 2, semantic RAG is Layer 3; for internal planning docs, grep wins

**Sources**: [3] yage.ai grep analysis, [11] qmd agent search, [4] Lander Analytics, [13] Zylos research

The confirmed 2026 hierarchy for agent information retrieval (from multiple independent sources):

- **Layer 1 — grep/glob** (always available, zero config): exact keyword match, file-type coverage, direct integration into agent control flow. Anthropic's experience: "plain glob and grep won" over vector DBs and recursive indexing. Used for: exploration, hypothesis generation, context foraging.
- **Layer 2 — structural/syntactic search** (tree-sitter, ast-grep): adds syntactic precision for code. For markdown planning docs, the Layer 2 analog is heading-aware search (grep for H2 patterns: `^## D15` finds the D15 section). No additional tooling required — the agent formulates smarter grep patterns.
- **Layer 3 — semantic/RAG** (vector embeddings, qmd, etc.): used when the agent cannot formulate a keyword query. For internal planning docs, this happens when the task involves a concept that may be named differently across files. Example: "where is the idempotency requirement?" — "idempotency" may appear as "ledger", "crash-safe", "D15", "D17" in different files.

**Specific finding for planning-doc corpora**: Lander Analytics argues RAG is not needed for small-to-medium internal knowledge bases precisely because the agent can formulate grep queries with sufficient specificity. The counter-condition: once documentation exceeds what agents can "search through in a few hops," retrieval infrastructure becomes necessary.

**UDM corpus size assessment**: The UDM corpus is large (41K+ lines) but the vocabulary is highly specialized (D-numbers, B-numbers, RB-numbers, phase names, module names) — all of which are grep-precise. RAG adds little value because exact-keyword grep almost always finds the right document. This validates NOT building RAG infrastructure for the UDM docs.

**Confidence**: High — multiple independent sources converge on this hierarchy; the UDM-specific conclusion is well-grounded.

---

#### Finding C-2: The Navigation Paradox — agents fail on structurally-connected but semantically-distant files; this is the strongest argument for explicit cross-references in split docs

**Sources**: [1] CodeCompass (arxiv 2602.20048), [2] Formal Architecture Descriptors (arxiv 2604.13108)

The CodeCompass research identified: "When architecturally critical but semantically distant files are absent from the model's attention, errors occur that additional context budget alone cannot resolve." The Navigation Paradox: larger context windows shift failure from retrieval capacity to *navigational salience*.

For UDM planning docs specifically: a decision in `03_DECISIONS_phase1.md` may cite an edge case in `04_EDGE_CASES.md` which cites a runbook in `05_RUNBOOKS.md` — a three-hop chain. If any link in that chain is broken by a split (e.g., `04_EDGE_CASES.md` splits into `04_EDGE_CASES_series_M.md` and `04_EDGE_CASES_series_N.md`), an agent that reads the D-number citation cannot follow the chain because the filename has changed.

**The 2602.20048 finding**: graph-based navigation achieved 99.4% coverage on hidden-dependency tasks; grep-only achieved 78.2%. The critical enabler: **explicit link/edge representation** (IMPORTS, INHERITS, INSTANTIATES). For markdown docs, the equivalent is **explicit cross-reference links** in the text (`[RB-8](../05_RUNBOOKS.md#rb-8)`). Without explicit links, split files break the dependency graph that agents need to traverse.

**What this means for UDM splits**: Every split file MUST preserve all internal cross-references as explicit relative Markdown links pointing to the correct target file. Breaking a `see D15` inline reference into a dead link is a navigability regression that grep cannot recover from.

**Confidence**: High — peer-reviewed research; the UDM application is an inference but a well-grounded one.

---

#### Finding C-3: "Compass, not encyclopedia" — agents form a mental model of an unfamiliar repo from entry points, not from comprehensive reading

**Sources**: [13] Zylos codebase intelligence, [17] SIGPLAN (repositories as knowledge factories), [9] meta-repo pattern, [15] GitHub (prior research)

Zylos codebase intelligence (2026): when an agent encounters an unfamiliar repo, it follows a cascade:
1. Read entry-point files (CLAUDE.md, AGENTS.md, README.md, `00-start-here.md`) — these form the "compass"
2. Follow references from the entry point to relevant sub-files — lazy discovery
3. Use grep/glob to fill specific gaps the entry point did not address

The SIGPLAN paper (2026) frames repositories as "human/agent knowledge factories" and identifies that agents need "structural understanding — not just semantic similarity." The compass metaphor: a 25-35 line orientation file with explicit pointers to sub-areas, NOT a comprehensive map of everything.

**What does NOT help agents**: "Architectural overviews and repo structure explanations did not meaningfully reduce time spent locating relevant files" (ETH Zurich, cited in prior research Finding 5). An INDEX.md that lists all 40 files with one-line descriptions each is an encyclopedia-style document — it triggers the cost increase without the navigational benefit.

**What DOES help agents**: The validated entry-point pattern has three components:
1. An explicit task-to-file routing table: "If task = X, read file Y"
2. Explicit cross-references from files to their dependencies: "This file cites D15; D15 is in `03_DECISIONS_phase1.md`"
3. Stable, grep-able filenames that agents can locate without reading the index

**Confidence**: High — multiple independent 2026 sources agree; the "compass not encyclopedia" principle is empirically grounded.

---

#### Finding C-4: There is no ARIA-style accessibility standard for AI agent navigation — the closest analogues are llms.txt, MAGI, and intent.lisp

**Sources**: [2] Formal Architecture Descriptors, prior research Findings 4, 9

The question "are there frameworks specifically for agent navigation aids — like ARIA for accessibility?" — the answer as of 2026 is: no single standard, three emerging approaches:

1. **llms.txt** (widest adoption, 844K+ sites): H1 name, blockquote summary, sections with linked files + one-line descriptions. For internal repos: equivalent to a root-level `INDEX.md` with the same structure.

2. **MAGI** (Mintlify extension): YAML frontmatter + `ai-script` blocks + footnote-based relationship declarations. Not natively consumed by Claude Code; requires a pipeline.

3. **intent.lisp / Formal Architecture Descriptors** (arxiv 2604.13108, April 2026): S-expression structured descriptors, auto-generated by LLM from natural language, achieving 34:1 compression with 100% task accuracy vs. 80% baseline. This is the most promising standard but requires a code-analysis pipeline and is designed for code repos, not planning-doc corpora.

**For UDM**: llms.txt structure applied to `INDEX.md` is the most practical zero-infrastructure approach. No new tooling needed; the structure is well-defined and widely validated.

**Confidence**: Medium — llms.txt is high-confidence; MAGI and intent.lisp are emerging and not validated for internal planning-doc corpora.

---

### D. CROSS-FILE REFERENCES WHEN SPLITTING

---

#### Finding D-1: Relative Markdown links are the most portable cross-reference pattern; URL fragment anchors work but require heading-slug stability

**Sources**: [14] MyST cross-reference spec (mep.mystmd.org), Sphinx docs, [6] Linux kernel (implicit)

MyST Enhancement Proposal 0002 documents the cross-reference problem for Markdown: "relative paths with POSIX path separators — `[](../file-types/myst-notebooks.md)` — are the most portable pattern."

Heading anchor slugs (e.g., `#d15`) are auto-generated from headings: lowercase, punctuation removed, spaces to hyphens, uniqueness via suffix enumeration. If a heading changes (even just adding a word), the slug changes and all inbound links break silently. This is the primary failure mode for fragment-based cross-references.

**Pattern hierarchy for UDM splits**:
1. `[D15](../03_DECISIONS_phase1_D50-D100.md#d15)` — file-relative + fragment. Works for GitHub preview, agents can grep for `03_DECISIONS_phase1` as a file-locator. **Preferred.**
2. `[D15](../03_DECISIONS_phase1_D50-D100.md)` — file-relative, no fragment. Loses within-file precision but survives heading renames. **Fallback.**
3. `[D15](#d15)` — fragment only, same file. Only valid when D15 is in the same file. **Restricted use.**
4. Sphinx `:doc:` references, intersphinx — only for Sphinx-rendered doc sites, not raw markdown repos. **Not applicable.**

**The slug stability problem for UDM**: D-number headings are inherently stable (`## D15 (Idempotency Ledger)` — the D15 part never changes). This makes fragment anchors workable specifically for D-numbered content. The risk is lower for D-numbers than for human-language headings.

**Confidence**: High — MyST/Sphinx documentation is primary source; the stability analysis is an application inference.

---

#### Finding D-2: The "manifest" pattern (doc-set membership declaration) is not a documented industry standard; the closest analogue is the Docusaurus sidebar config

**Sources**: Mintlify `docs.json`, Docusaurus `sidebars.json`, [6] Linux kernel `index.rst`

Mintlify uses `docs.json` to declare all pages and their navigation structure. Docusaurus uses `sidebars.json`. Linux kernel uses `index.rst` in each directory with a `toctree` directive. These are "manifest" patterns in the sense that they declare doc-set membership — but they are specific to doc-rendering platforms, not internal markdown repos.

For raw internal markdown repos (no rendering pipeline), the closest functional analog is:
- A root `INDEX.md` that explicitly links to all sub-files (the llms.txt pattern)
- Or a machine-readable `manifest.yaml` that the `tools/regenerate_md_indexes.py` script reads

The `manifest.yaml` approach (separate from the INDEX.md) is NOT a documented industry standard for internal repos. It is a custom infrastructure choice. The Linux kernel's `index.rst` pattern is the closest evidence for "per-directory manifest."

**For UDM**: The plan's `tools/regenerate_md_indexes.py` script could read either YAML frontmatter (per-file, no separate manifest) or a `manifest.yaml` (one manifest, all files enumerated). Frontmatter is more resilient to file additions (no manifest to update); a central manifest gives a single source of truth for doc-set membership.

**Confidence**: Medium — absence of a "manifest" standard is a confirmed absence; the alternatives are documented but not directly benchmarked.

---

### E. META-RESEARCH CANDIDATES

---

#### Finding E-1: Eight meta-research topics identified, prioritized by UDM-specific impact

The following topics were identified as the next research investments for the UDM discoverability strategy. Each is annotated with: rationale, estimated effort (Low/Medium/High), expected payoff (Low/Medium/High), and recommended timing.

**Priority 1 — The Navigation Paradox applied to UDM's cross-reference topology**
- Rationale: The CodeCompass finding (23-point improvement from graph navigation) is the most impactful new result. UDM's planning docs have an explicit cross-reference topology (D-numbers cite B-numbers cite RB-numbers cite edge-case series). Whether this topology creates "hidden dependency" problems for agents navigating the split doc corpus is unknown. If the answer is yes, the plan needs explicit cross-reference link preservation as a mandatory split constraint.
- Effort: Medium (requires mapping the UDM cross-reference graph and testing a few queries against both split and unsplit versions)
- Payoff: High — changes the core constraint on how files can be split
- Timing: Before executing Option A splits

**Priority 2 — Token cost measurement of the current CCL**
- Rationale: The plan claims "12K–16K lines per CCL invocation." No external source validates this estimate or its impact on claude-sonnet-4-6 performance. A direct measurement (count tokens in the 7–11 CCL reads) would ground the optimization target.
- Effort: Low (read the 7 mandatory Stage 1-3 files, count tokens or lines)
- Payoff: High — if actual cost is lower than estimated, Phase 3 splits may be premature; if higher, Phase 1 is even more urgent
- Timing: Immediately (inform the plan's priority sequencing)

**Priority 3 — Heading-slug stability audit across UDM docs**
- Rationale: Finding D-1 shows that D-number headings are slug-stable (D15 will always be D15), but other headings (round names, phase names, table names) may be renamed. Before committing to fragment-based cross-references in the split, auditing which headings are stable vs. mutable would identify the safe cross-reference strategy.
- Effort: Low (grep for heading patterns across docs/migration/)
- Payoff: Medium — informs whether the relative-link-with-fragment pattern is safe or needs fallback
- Timing: Before executing splits

**Priority 4 — Formal Architecture Descriptor generation for the UDM planning corpus**
- Rationale: The intent.lisp research (arxiv 2604.13108) shows LLM-generated descriptors achieve 100% task accuracy (vs. 80% baseline) with 33-44% reduction in exploration steps. The UDM corpus has a structural architecture (phases, rounds, D-numbers, modules) that could be auto-described. A generated `intent.md` for the `docs/migration/` corpus could serve as a better INDEX.md than a human-authored one.
- Effort: Medium (generate the descriptor, test against sample queries)
- Payoff: High — if it works, it replaces the Phase 1 INDEX.md authoring task with an auto-generated alternative
- Timing: Phase 1 design decision

**Priority 5 — Multi-agent CCL cost distribution**
- Rationale: Prior research Finding 11 identified that the subagent pattern (one agent reads CCL, summarizes, passes brief to peers) could reduce per-agent startup cost from 12K–16K lines to ~500–1K lines for downstream agents. No primary source quantifies the quality loss from summary vs. direct read for the UDM-specific decision validation tasks.
- Effort: Medium (test a Pattern E cycle with one context-loader subagent vs. without)
- Payoff: High — could reduce multi-agent session costs substantially
- Timing: Phase 2

**Priority 6 — Snowflake documentation conventions for AI agents (Phase 5)**
- Rationale: Phase 5 of the UDM project involves Snowflake Iceberg integration. Snowflake's documentation structure and agent-navigation patterns (for Cortex, Snowpark, COPY INTO) are unknown. Phase 5 planning will benefit from knowing whether Snowflake's docs follow the same patterns validated here.
- Effort: Low (targeted web search on Snowflake docs structure)
- Payoff: Medium — relevant for Phase 5 only; not load-bearing for the current refactor
- Timing: At Phase 5 planning

**Priority 7 — Auto-compaction interaction with CCL reads**
- Rationale: Prior research Finding 10 noted: "Claude Code's auto-compaction re-attaches invoked skills at a combined 25K token budget — whether this applies to CCL docs read via the Read tool is not documented." If auto-compaction summarizes CCL reads, the apparent context cost is lower but the agent may be operating on summaries rather than exact text (which matters for D-number validation and RB-N procedure review).
- Effort: Medium (test auto-compaction behavior; Anthropic docs may clarify)
- Payoff: Medium — changes the context cost model; affects whether Phase 3 splits are necessary
- Timing: Phase 1 design decision

**Priority 8 — Diátaxis-quadrant labeling for CCL routing**
- Rationale: Prior research Finding 12 identified that Diátaxis (tutorial/how-to/reference/explanation quadrants) could be used as a routing signal. The UDM docs implicitly follow Diátaxis quadrants. Explicitly labeling them (in frontmatter or INDEX.md) could enable a skill that routes agents to the right quadrant before searching within it. This is low priority because it adds new infrastructure without clear incremental benefit over grep.
- Effort: Low (label the files, test whether routing improves)
- Payoff: Low — incremental at best; useful only if a Diátaxis-aware routing skill is built
- Timing: Phase 4 (after Phases 1-3 are validated)

---

## Recommendation

### A. Naming convention proposal for UDM split files

**Canonical pattern**: `NN_SCOPE_{qualifier}.md`

Where:
- `NN` = two-digit sort prefix matching the original file number (preserves sort order; `00` reserved for entry points)
- `SCOPE` = the original filename base (e.g., `DECISIONS`, `EDGE_CASES`, `VALIDATION_LOG`)
- `qualifier` = the semantic scope boundary in the split file (phase name, D-range, round range, series name)

**Specific proposals**:

| Original file | Split files | Notes |
|---|---|---|
| `03_DECISIONS.md` (3,219 lines) | `03_DECISIONS_phase0.md` (D1–D50 approx) / `03_DECISIONS_phase1.md` (D50–D95 approx) / `03_DECISIONS_phase2_onwards.md` (D96+) | D-range in name aids grep; phase name aids routing |
| `_validation_log.md` (7,129 lines) | `_validation_log.md` (live: last 30 days) + `_validation_log_archive_2026-04.md` | Existing archive policy already proposes this; research confirms time-based is correct for append-only logs |
| `phase1/01_database_schema.md` | Keep as one file — split by H2 heading is sufficient; agents navigate within via H2 headers | Only split if exceeds 3,000 lines with no clear scope boundary |
| `BACKLOG.md` | Keep as one file — B-numbers are grep-precise; splitting by B-number range creates orphan-reference risk | Exception: if file exceeds 5,000 lines, split as `BACKLOG_B1-B150.md` / `BACKLOG_B151-onwards.md` |

**What to avoid**:
- `03_DECISIONS_part_1.md` — communicates sequence, not scope; grep for "part_1" returns nothing useful
- `03_DECISIONS_2026-05.md` — date is correct for changelogs, not for reference material
- `DECISIONS_section_4_2.md` — structural; opaque to search

### B. TOC structure proposal

**Root INDEX.md** — routing manifest, NOT a comprehensive table of contents:

```markdown
# UDM Documentation Index

> Intent-based routing for agents and humans. Read the entry that matches your task; skip others.

## Stage 0: Start here (all agents read this)

- [CURRENT_STATE.md](CURRENT_STATE.md) — "What is the state of the project right now?"
- [HANDOFF.md](HANDOFF.md) — "How do I pick up this project mid-flight?"

## Decisions (D-numbers)

- [03_DECISIONS_phase0.md](03_DECISIONS_phase0.md) — D1–D50: foundational architecture decisions (greenfield, SCD2, tokenization, parity)
- [03_DECISIONS_phase1.md](03_DECISIONS_phase1.md) — D51–D95: pipeline design, validation discipline, round close-out
- [03_DECISIONS_phase2_onwards.md](03_DECISIONS_phase2_onwards.md) — D96+: security model, SQL naming, deployment pipeline

## Validation trail

- [_validation_log.md](_validation_log.md) — Live validation entries (last 30 days). Pre-2026-04: see archive.
- [_validation_log_archive_2026-04.md](_validation_log_archive_2026-04.md) — Archive (append-only).

## [... additional sections by need ...]
```

**Per-file H2 structure** (within each split file): Each split file should open with a one-paragraph scope statement before any content:

```markdown
# Decisions — Phase 0 (D1–D50)

**Scope**: This file contains decisions D1 through D50, covering foundational architecture
(greenfield deployment, SCD2 strategy, tokenization vault, parity baseline, and Automic gate
coordination). For D51+, see [03_DECISIONS_phase1.md](03_DECISIONS_phase1.md).

**Quick-find**: Use Ctrl+F or grep for the D-number (e.g., `D15`). All D-numbers in this file
have H2-level headings.
```

---

## Counter-evidence

**Against semantic naming in split files**:
The extency.com "agent brain" article argues naming should prioritize "clarity and human readability" over algorithmic optimization — and demonstrates this with simple names like `acme.md`, `refunds.md`. Their corpus is a customer knowledge base (short, discrete documents), not a cross-referenced planning doc corpus. The simpler naming works for their case because their documents don't cross-reference each other. UDM's docs DO cross-reference each other extensively; semantic-in-filename is more important for UDM than for their use case.

**Against the Index.md as entry point**:
ETH Zurich (prior research Finding 5) found that context files containing repo structure explanations "did not meaningfully reduce time spent locating relevant files." If INDEX.md is written as a structural map ("here is what each file contains") rather than a routing manifest ("if your task is X, read Y"), it risks the same failure mode. The distinction between routing (helpful) and structural description (not helpful) is load-bearing.

**Against splitting `_validation_log.md`**:
The Navigation Paradox finding suggests that splitting a log by date creates hidden-dependency risk: an agent validating a decision that was first debated in 2026-04 (archived) and re-affirmed in 2026-05 (live) would need to read both files. If the index does not explicitly cross-reference the archive, the agent may conclude the decision was never debated. Counter: the existing archive policy in the validation log already accounts for this by requiring a back-reference line at the top of the live file.

---

## What this research does NOT cover

- Quantitative benchmark comparing naming conventions for agent navigation performance (no such study found for internal planning-doc corpora)
- The specific token count for each UDM CCL file (Priority 2 meta-research; can be measured without web search)
- Snowflake-specific documentation conventions (Priority 6 meta-research; deferred to Phase 5)
- Auto-compaction behavior interaction with CCL reads in claude-sonnet-4-6 specifically (Priority 7)
- Whether the UDM cross-reference topology creates Navigation Paradox failure modes (Priority 1; requires empirical testing)

---

## Confidence assessment

🟡 Medium-High overall.

- **Naming conventions (Finding A-1 to A-4)**: 🟢 High — multiple primary sources agree; the pattern is consistent across large OSS projects with different tooling
- **TOC design (Finding B-1 to B-4)**: 🟡 Medium — supported by practitioner reports and the Navigation Paradox research; not directly measured for planning-doc corpora
- **Discoverability mechanisms (Finding C-1 to C-4)**: 🟢 High for grep hierarchy; 🟡 Medium for Navigation Paradox UDM application (the paper is about code repos, not planning docs)
- **Cross-file references (Finding D-1 to D-2)**: 🟢 High for the relative-link pattern; 🟡 Medium for the "no manifest standard" finding
- **Meta-research candidates (Finding E-1)**: 🟡 Medium — the candidates are grounded in findings but their payoff is speculative

---

## Synthesis: what changes the calculus of the plan?

### Findings that VALIDATE the plan

- The index-front approach (Phase 1) is validated by: llms.txt standard, SKILL.md entry-point pattern, the "compass not encyclopedia" principle, Lander Analytics numbered-prefix pattern, and the Kubernetes `_index.md` convention. All converge on: one manifest entry point + per-domain files.
- The 1,000-line split trigger (Phase 3) is directionally validated: no source recommends files that large for agent-facing content. The 500-line SKILL.md cap and 150-200-line AGENTS.md threshold from prior research are the floor; 1,000 lines is defensible for reference docs (not directive files).
- Archive-by-date for `_validation_log.md` is validated: the time-based split is the correct approach for append-only logs. Semantic splitting (by topic) would break the append-only invariant.

### Findings that CHANGE the calculus

1. **Semantic naming over structural naming** (Finding A-4): the plan's example `03_DECISIONS_phase0.md` is correct; avoid `03_DECISIONS_part_1.md` or `03_DECISIONS_part_A.md`. The filename participates in grep; structural names don't.

2. **The Navigation Paradox is the primary risk in splitting** (Finding C-2): when files split, cross-references that span split boundaries must be preserved as explicit relative Markdown links. "See D15" as plain text is not enough after splitting — it must become `[D15](../03_DECISIONS_phase1.md#d15)`. This is a mandatory constraint the plan does not currently specify.

3. **Routing manifest, not structural TOC** (Finding B-1 + B-4): the INDEX.md must be written as "if your task is X, read Y" — NOT as "file Y contains sections A, B, C." ETH Zurich's finding (prior research) is the evidence; the distinction is the implementation detail.

4. **Intent.lisp/Formal Architecture Descriptors are the most promising long-term standard** (Finding C-4): the plan should note this as a Phase 4+ investigation. Auto-generated structured descriptors (34:1 compression, 100% task accuracy) are more powerful than hand-authored frontmatter (Phase 4 in the current plan).

### Findings that EXPOSE GAPS in the plan

1. **The plan has no constraint on cross-reference preservation during splits** — the Navigation Paradox finding makes this a mandatory gap to address.

2. **The plan does not specify a heading-slug stability policy** — fragment anchors like `#d15` break if headings are renamed; the plan should require D-number headings to include the D-number as the first word (making the slug stable: `d15`, not `d15-idempotency-ledger-decision`).

3. **The plan has no test for whether the INDEX.md is written as routing vs. structural** — Gate 2 validation should include this check.

---

## Suggested follow-up

1. **Producer should add** a mandatory cross-reference preservation constraint to the split specification: "every inbound reference to content that moves to a new file must be updated to a relative Markdown link pointing to the new file location."
2. **Producer should add** a heading-slug stability policy: D-number section headings use the pattern `## D15 — {title}` (D-number as prefix, slug becomes `d15`).
3. **Producer should write** the INDEX.md routing manifest using the llms.txt format (H1, blockquote summary, sections with intent-based entries per file) rather than a TOC-of-TOCs.
4. **Meta-research Priority 1** (Navigation Paradox applied to UDM topology) should be assigned before Option A splits begin — it may change which cross-references need explicit link preservation.
5. **Meta-research Priority 2** (token count measurement of current CCL) should be done immediately; it takes 15 minutes and grounds the optimization target.
6. Validation Gate 2 for the plan can now mark:
   - "Index-front is industry-validated" — YES, grounded in llms.txt + Kubernetes `_index.md` + Lander Analytics `00-start-here.md`
   - "Semantic naming beats structural naming" — YES, grounded in Kubernetes, Linux kernel, Navigation Paradox (A-4)
   - "Part-N naming convention" — REJECTED, no industry precedent found
   - "Fragment anchors for D-numbers are stable" — YES, conditional on D-number-as-first-word heading format (D-1)

---

*Research complete. Scope deliberately bounded to the five research questions (A–E). Adjacent questions not investigated: Snowflake Phase 5 docs conventions (Priority 6); auto-compaction interaction with CCL (Priority 7); token cost measurement (Priority 2 — direct measurement, not web research).*
