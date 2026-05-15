# Markdown Refactor + Agent Traversal System — Plan

**Status**: 🟡 Plan-draft authored 2026-05-15 — awaiting pipeline-lead review before any execution. **REVISED 2026-05-15** with: (a) research findings synthesis per §3.6 (udm-researcher artifact `_research/agent-markdown-traversal-2026-05-15.md`; 13 findings; 15 primary sources); (b) independent gap audit per §10b (7 confirmed gaps + 8 edge cases + 4 untested assumptions + 4 out-of-scope confirmations); (c) 5 new open questions Q-8 through Q-12 added to §10.

**Owner**: Pipeline lead. Contributor: parent-agent authoring this plan; no execution work landed.

**Driver**: User direction 2026-05-15 — "files at 6000 or more lines of code seems too much. ... we should come up with a quality plan. Specifically, we refactor markdown files and come to with a system to better traverse this repository for agents."

**Scope**: Plan-only deliverable. NO file refactors, NO splits, NO traversal-system implementation in this commit. Per the project's standing D55 + D56 + D60 discipline ("plan → validate → execute → record → lock"), this plan is the artifact under review; execution requires user approval and a separate work-cycle.

---

## §1. Problem statement

Two coupled concerns:

### §1.1 File-size cost

Reading a large markdown file consumes context proportional to its line count. The session-2026-05-15 measurement:

| File | Lines | Notes |
|---|---|---|
| `docs/migration/_validation_log.md` | **7,129** | Append-only audit trail; archive policy already documented at L23 (deferred to Phase 2 R1 close-out) |
| `docs/migration/03_DECISIONS.md` | 3,219 | D-number register; grows monotonically per D92 forward-only schema-evolution discipline |
| `docs/migration/phase1/01_database_schema.md` | 2,167 | Canonical Round 1 DDL — every table + SP + index lives here |
| `docs/migration/phase1/06_deployment.md` | 1,846 | Round 6 spec doc — per-section deployment workflows |
| `docs/migration/phase1/03_core_modules.md` | 1,724 | Round 3 spec doc — 17 module specs |
| `docs/migration/phase1/04_tools.md` | 1,628 | Round 4 spec doc — 11 tool specs |
| `docs/migration/05_RUNBOOKS.md` | 1,545 | Operational runbook register (RB-N) |
| `docs/migration/phase1/02_configuration.md` | 1,404 | Round 2 spec doc |
| `docs/migration/phase1/01c_data_flow_walkthrough.md` | 1,146 | |
| `docs/migration/phase1/08_sub_agent_self_improvement.md` | 1,129 | Round 8 self-improvement discipline |
| `docs/migration/phase1/05_tests.md` | 826 | Round 5 spec doc |
| `docs/migration/phase1/07_schema_evolution_governance.md` | 806 | Round 7 spec doc |
| `docs/migration/GLOSSARY.md` | 799 | Already structured as a code-family index |
| `docs/migration/phase1/01a_control_tables.md` | 778 | |
| `CLAUDE.md` (project root) | 715 | Dense single-paragraph blocks; high info density per line |

**Aggregate**: `docs/migration/` totals ~41,425 lines. 10 files over 1,000 lines each. Only ONE file (`_validation_log.md`) currently exceeds 6,000 lines as the user observed.

### §1.2 Agent traversal cost

Per `MULTI_AGENT_GUIDE.md` § Canonical Context Load (D62), every agent / sub-agent / skill MUST perform CCL Stage 1+2 before any task-specific tool call. Stage 1 is 4 mandatory reads; Stage 2 is 3 more for risk + backlog awareness; Stage 3 is task-specific (typically 2-4 reads). A typical agent invocation reads 7-11 markdown files at startup.

If those files average 1,500 lines each → ~12,000-16,500 lines per agent invocation just for CCL.

**Two cost surfaces**:
- **Compute / latency**: each Read tool call is bounded by file size; large reads slow down agent startup
- **Context-window pressure**: large CCL reads displace task-specific context (the work-product capacity); on a 200K-context model the budget allows reading every file once but degrades when re-reads happen mid-task

**Empirical evidence from this session**: parent-agent context this session has held the entire CLAUDE.md (715 lines) + multiple ~1,500-line spec docs + this session's growing _validation_log appendments. Re-reads of CLAUDE.md and CURRENT_STATE.md have been routine (visible in tool-use traces) — each ~700-line re-read is non-trivial overhead.

---

## §2. Goals + non-goals

### §2.1 Goals

1. **Reduce per-agent CCL cost** — agents should be able to perform Stage 1+2 in <2,000 lines total (down from ~12K-16K)
2. **Preserve canonical-source-of-truth structure** — every D-number / B-number / R-number / SP-N / RB-N has ONE canonical home; no duplication
3. **Backwards-compatible cross-references** — the ~hundreds of inline cite patterns (`phase1/05_tests.md § 8.2 L488`, `03_DECISIONS.md D77`, etc.) should remain stable across the refactor; if they MUST change, do so atomically with a verification script
4. **Reversible** — every refactor phase must be revertible via `git revert` without cascading breakage
5. **Low-risk first** — start with reversible / additive changes (indexes, archives) before any file splits
6. **Discipline-aligned** — apply the project's existing D55 5-gate validation + D62 CCL + D89-D91 Pattern F discipline to the refactor work itself

### §2.2 Non-goals

1. **Not** rewriting any spec doc content — content is canonical; only structure / discoverability changes
2. **Not** breaking the Pattern F audit script (`tools/verify_cascade.py`) — its regex patterns are calibrated against current paths
3. **Not** splitting `_validation_log.md` immediately — its archive policy (L23) is the right answer; just execute it, don't redesign it
4. **Not** introducing tooling that requires non-stdlib dependencies — markdown indexing should stay pure
5. **Not** changing the agent CCL canonical order (per D62 + B30 D62 first-pass) — only making each Stage 1 read cheaper

---

## §3. Refactor approaches — options enumerated

Per `udm-brainstorm` discipline: enumerate options before recommending. Each option scored on (a) backwards-compat cost, (b) implementation effort, (c) ongoing-maintenance cost, (d) discoverability gain.

### §3.1 Option A — Split-by-section (large files → many sub-files)

Split each >1,000-line file into topic-based sub-files. Examples:
- `_validation_log.md` → `_validation_log_2026-05.md`, `_validation_log_2026-04.md`, etc. (per-month archive)
- `03_DECISIONS.md` → `03_DECISIONS_phase0.md`, `03_DECISIONS_phase1.md`, etc.
- `phase1/01_database_schema.md` → `phase1/01_database_schema_<table>.md` per table

| Score | Value |
|---|---|
| Backwards-compat cost | 🔴 HIGH — every cite of a section / line breaks; ~100s of cites to update |
| Implementation effort | 🔴 HIGH — many splits + many cite-rewrites |
| Ongoing-maintenance cost | 🟡 MEDIUM — author discipline to put new content in the right sub-file |
| Discoverability gain | 🟢 HIGH — each sub-file is small + semantically self-contained |

**Verdict**: Avoid as Phase 1. Reserve for Phase 3 (targeted splits where Phase 1+2 prove insufficient).

### §3.2 Option B — Index-front (existing files keep; index sidecars added)

Each large file gets a companion `<file>_INDEX.md` with a TOC + per-heading line-range map. Agents read the INDEX first, then `Read` the canonical file with `offset` + `limit`.

Example for `03_DECISIONS.md`:
```markdown
# 03_DECISIONS_INDEX.md

| D-number | Title | Status | Lines |
|---|---|---|---|
| D1 | ... | 🟢 Locked | 12-44 |
| D2 | ... | 🟢 Locked | 45-89 |
| ... | ... | ... | ... |
| D77 | CLI Tier 0 scaffold pattern | 🟢 Locked | 1822-1890 |
```

| Score | Value |
|---|---|
| Backwards-compat cost | 🟢 ZERO — no source files touched |
| Implementation effort | 🟡 MEDIUM — generate INDEX content (could automate via `tools/generate_md_index.py`) |
| Ongoing-maintenance cost | 🟡 MEDIUM — INDEX must regenerate on any source edit; could automate via pre-commit hook |
| Discoverability gain | 🟢 HIGH — agents read 50-200 lines of INDEX + targeted offset-Read instead of 3,219 lines |

**Verdict**: STRONG candidate for Phase 1 (low risk; high gain).

### §3.3 Option C — Archive cascade (extend existing archive policies)

`_validation_log.md` already has an archive policy at L23 deferred to Phase 2 R1 close-out. Apply it now (proactively); extend the same pattern to `BACKLOG.md` (which has a "Completed" section that could split per-round).

Concretely:
- `_validation_log.md` (7,129 lines) → archive pre-2026-04-12 entries to `_validation_log_archive_2026-04.md`; live file truncates to recent ~30 days; stays under ~1,500 lines going forward
- `BACKLOG.md` (547 lines): the lower "Completed" sections could split to `BACKLOG_completed_round-N.md` per-round
- `_reviewer_effectiveness.md` (518 lines): may not need archive yet but pattern available

| Score | Value |
|---|---|
| Backwards-compat cost | 🟢 LOW — archive paths are new; existing cites stay; archive file's append-only invariant preserved |
| Implementation effort | 🟢 LOW — already documented at `_validation_log.md` L14-23; mechanical |
| Ongoing-maintenance cost | 🟢 LOW — policy is "archive on threshold" — automatic at round close-out |
| Discoverability gain | 🟢 HIGH for `_validation_log` (7K→<2K); MEDIUM for `BACKLOG` |

**Verdict**: CO-RECOMMEND for Phase 1 alongside Option B.

### §3.4 Option D — Frontmatter + tagged sections (in-file metadata)

Add YAML frontmatter to each large file + tag major sections with searchable metadata. Agents `Grep` by tag instead of reading full files.

Example:
```markdown
---
file_type: spec_doc
phase: 1
round: 5
status: locked
last_updated: 2026-05-10
sections:
  - § 1: Cross-cutting test conventions (L91-200)
  - § 2: Round 5 producer self-check (L201-280)
  ...
---
```

| Score | Value |
|---|---|
| Backwards-compat cost | 🟢 ZERO — additive frontmatter |
| Implementation effort | 🟡 MEDIUM — author frontmatter for 10 large files + agent-side discipline to grep tags |
| Ongoing-maintenance cost | 🔴 HIGH — every section edit needs frontmatter sync; line-range drift |
| Discoverability gain | 🟡 MEDIUM — depends on agents adopting grep-by-tag pattern |

**Verdict**: SECONDARY — gain is real but maintenance cost is brittle (line ranges drift; frontmatter rots). Consider for Phase 4 polish if Phase 1+2 prove insufficient.

### §3.5 Option E — Master cross-reference manifest

Single `docs/migration/INDEX.md` mapping every D-number / B-number / R-number / SP-N / RB-N / Pattern code / Pitfall sub-class to its canonical location with line number. Complements the existing `GLOSSARY.md` (which is currently a code-family index, not a per-instance index).

Example:
```markdown
# INDEX.md

## D-numbers (canonical home: 03_DECISIONS.md)
| D-N | Title | Line | Status |
|---|---|---|---|
| D1 | ... | 12 | 🟢 |
| D77 | CLI Tier 0 scaffold pattern | 1822 | 🟢 |
| ... | ... | ... | ... |

## B-numbers (canonical home: BACKLOG.md)
| B-N | Title | Status | Line | Closed-by |
|---|---|---|---|---|
| B77 | R22 to RISKS.md | ⚫ CLOSED 2026-05-10 | 179 | B119 batch |
| ... | ... | ... | ... | ... |

## SP-N (canonical home: phase1/01_database_schema.md)
... etc
```

| Score | Value |
|---|---|
| Backwards-compat cost | 🟢 ZERO — purely additive |
| Implementation effort | 🟡 MEDIUM — could automate via `tools/generate_index.py` |
| Ongoing-maintenance cost | 🟡 MEDIUM — needs regeneration on every spec edit; pre-commit hook automates |
| Discoverability gain | 🟢 VERY HIGH — agents jump to canonical line in O(1) lookup |

**Verdict**: CO-RECOMMEND for Phase 1. Strong complement to Option B (per-file INDEX) — Option E is the cross-cutting view.

---

### §3.6 Research validation (added 2026-05-15)

`docs/migration/_research/agent-markdown-traversal-2026-05-15.md` (full artifact via udm-researcher; 13 findings; 15 primary sources) was commissioned to validate the §3 + §4 options against industry evidence. Confidence: 🟡 Medium (no benchmark study directly measures index-front vs. embedded-metadata for internal planning-doc corpora; findings extrapolate from adjacent domains).

**Validates the plan's direction**:
- **§3.2 Option B (Index-front)** is structurally equivalent to the **llms.txt open standard** (844K+ sites adopted as of October 2025; Anthropic itself uses it). The proposed master `INDEX.md` is the right structural intervention.
- **§3.5 Option E (Master cross-ref manifest)** maps directly to llms.txt's "curated overview for LLMs" pattern (H1 project name + blockquote summary + sections of linked files with one-line descriptions).
- **§4.3 Option T3 (`udm-find-canonical` skill)** is the **native Claude Code mechanism** for on-demand reference lookup (per Anthropic skills documentation: "Unlike CLAUDE.md content, a skill's body loads only when it's used, so long reference material costs almost nothing until you need it"). Should be **elevated from Phase 4 to Phase 1 priority**.
- **Phase 3 file splits** validated by two independent thresholds: SKILL.md 500-line cap (Anthropic primary) + AGENTS.md 150-200-line subdirectory split threshold (OpenAI Codex + GitHub 2,500-repo lessons). The plan's >1,000-line trigger is approximate; the SKILL.md 500-line cap is the closest analogue for reference-doc files.

**Changes the plan's calculus** (5 specific adjustments per research §"Recommendation"):

1. **Per-file INDEX entries should be routing-by-intent, NOT structure-by-description**. ETH Zurich research (138 real-world Python tasks; AGENTbench testing of Claude 3.5 Sonnet + GPT-5 + Qwen) found that "architectural overviews and repository structure explanations did not meaningfully reduce time spent locating relevant files" and LLM-generated context files actually increased inference cost +20-23% with success rates -3%. **Design constraint**: each INDEX entry must answer "If you need X, read this file. If you need Y, skip this file and read Z instead" — not "this file contains sections A/B/C."

2. **Pre-commit hook (Phase 2.3) must be "auto-add-if-changed", NOT "fail-if-stale"**. Community evidence: AI agents (GitHub Copilot, Claude Code) have known difficulty with pre-commit hooks that modify the working tree mid-commit-cycle (agent doesn't retry as expected). The hook should: (1) run regenerator, (2) add INDEX.md to commit if changed, (3) succeed silently. Alternative: make INDEX regeneration a `udm-round-closeout` skill step (human-triggered at round boundaries) rather than per-commit.

3. **Phase 4 frontmatter is NOT natively consumed by Claude Code**. MAGI spec + Front-Matter Standard exist as emerging conventions but neither shows Claude Code consuming YAML frontmatter from project-internal files without external parser tooling. Phase 4 must reframe: frontmatter is (a) human-readable metadata + (b) machine-readable input for `tools/regenerate_md_indexes.py`, NOT "AI-readable" routing metadata. **Avoid overclaiming** per Audit-grade pillar.

4. **NEW Phase 2 item — `udm-context-loader` subagent** (Finding 11 gap). Anthropic best practices explicitly recommend the subagent pattern for "read large documentation without polluting main context": parent spawns child with isolated context; child performs CCL read; child returns structured brief. For multi-agent Pattern E + Pattern F cycles, this could reduce per-agent startup cost from ~12K-16K lines to ~500-1K lines for downstream agents in the team. Currently NOT in the plan. Low-cost to add; high-value for the project's existing multi-agent validation discipline.

5. **Subdirectory CLAUDE.md alternative considered + deferred**. Anthropic supports subdirectory-level CLAUDE.md files that load lazily (only when Claude reads files in that directory) + `@path/to/import` syntax for modular context loading. This is a NATIVE alternative to a bespoke INDEX.md. Decision: defer — restructuring `docs/migration/` into subdirectory hierarchy with per-subdir CLAUDE.md is higher-cost than the INDEX-front approach AND less reversible (changes file paths affecting hundreds of cross-references). The INDEX-front approach can adopt subdirectory CLAUDE.md as a Phase 4+ refinement IF Phase 1+2 metrics suggest deeper restructuring is warranted.

**Counter-evidence from research** (worth surfacing):
- ETH Zurich finding 5 is counter-evidence for naive structural INDEX entries; the plan must implement routing-by-intent to avoid the documented anti-pattern.
- No primary benchmark exists for project-internal (non-web, non-RAG) markdown doc navigation specifically. Magnitudes in §9 metrics are hypothesis-driven; first-Phase-1 measurement IS the empirical grounding.
- Frontmatter (Phase 4) has no industry case study showing Claude consumption — risk of building speculative infrastructure.

---

## §4. Agent traversal system — options enumerated

### §4.1 Option T1 — Agent-side discipline (read INDEX first; targeted offset-Read)

Update D62 CCL doctrine to add a Stage 0:
- **Stage 0 (NEW)**: Read `docs/migration/INDEX.md` (master cross-ref manifest)
- **Stage 1**: existing 4 mandatory reads
- **Stage 2**: existing 3 risk-+-backlog reads
- **Stage 3+**: task-specific Reads with `offset` + `limit` based on INDEX-derived line ranges

Parent agents should also issue `Read` with `offset`+`limit` for any file >500 lines unless full-file context is genuinely needed.

| Score | Value |
|---|---|
| Implementation effort | 🟢 LOW — D62 doctrine update + skill prompt updates |
| Adoption risk | 🟡 MEDIUM — agents may default to full-file reads from training inertia; needs test-suite verification |

**Verdict**: STRONG. Pair with Option B + Option E (the indexes that this discipline reads).

### §4.2 Option T2 — Pre-commit hook auto-regenerates indexes

A `tools/regenerate_md_indexes.py` runs as pre-commit hook; regenerates `INDEX.md` + per-file `<file>_INDEX.md` from current source files; commit fails if indexes are out-of-sync.

| Score | Value |
|---|---|
| Implementation effort | 🟡 MEDIUM — Python script + pre-commit-hook config + CI gate |
| Adoption risk | 🟢 LOW — automatic; no human discipline required |

**Verdict**: STRONG complement to Options B + E (closes the maintenance-cost concern).

### §4.3 Option T3 — Skill-side helper for "find canonical home"

Author a skill `udm-find-canonical` that wraps a Grep over the master INDEX → returns "D77 lives at 03_DECISIONS.md L1822" → agent then Read with offset. SKILL.md body under 500 lines per Anthropic skills cap (research §3.6 Finding 7); full canonical-home routing table in supporting `routing-table.md` file that loads only when the skill reads it.

| Score | Value |
|---|---|
| Implementation effort | 🟢 LOW — thin Grep wrapper |
| Adoption risk | 🟢 LOW — agents already use skills |

**Verdict (REVISED 2026-05-15 per research §3.6)**: **STRONG candidate for Phase 1 or Phase 2** (was: NICE-TO-HAVE Phase 4). Per Anthropic skills documentation: "Unlike CLAUDE.md content, a skill's body loads only when it's used, so long reference material costs almost nothing until you need it." This is the **native Claude Code pattern** for the canonical-home-lookup use case. Implementing it early is higher-leverage than frontmatter (Option D / Phase 4).

### §4.5 Option T5 — `udm-context-loader` subagent (NEW per research §3.6)

Per Anthropic best practices ("Delegate research with 'use subagents to investigate X'. They explore in a separate context window and report back summaries") + skills documentation `context: fork` mode. Pattern: parent agent in Pattern E or Pattern F multi-agent cycle spawns ONE `udm-context-loader` subagent in an isolated context; subagent performs the full CCL read (~12K-16K lines) and returns a structured brief (~500-1K lines) to the parent; parent passes the brief to downstream agents in the team; downstream agents skip CCL entirely.

| Score | Value |
|---|---|
| Implementation effort | 🟡 MEDIUM — requires authoring the subagent + brief schema + parent-side composition pattern |
| Multi-agent leverage | 🟢 VERY HIGH — Pattern E (5-agent) cycles currently re-read CCL 5× per cycle; this would reduce to 1×-load-and-distill + 4× brief-consumption. Saves ~50K-65K lines of agent-context per cycle |
| Adoption risk | 🟡 MEDIUM — requires Pattern E / F skill prompt updates to compose `udm-context-loader` BEFORE invoking blocking reviewers |
| Reversibility | 🟢 HIGH — additive subagent; can disable per-cycle if brief proves insufficient |

**Verdict**: STRONG **Phase 2** candidate. Pairs with Option T1 (D62 CCL doctrine update) — for single-agent invocations the Stage 0 INDEX read is sufficient; for multi-agent cycles the `udm-context-loader` distillation is higher-leverage. Both can coexist.

### §4.4 Option T4 — Inline `[anchor: D77]` HTML comments + `Grep`-by-anchor

Insert `<!-- anchor: D77 -->` HTML comments above every D-number heading. Agents `Grep -n 'anchor: D77'` to locate exactly. More precise than line numbers (which drift on edits).

| Score | Value |
|---|---|
| Implementation effort | 🟡 MEDIUM — bulk-insert anchors across all spec docs |
| Adoption risk | 🟡 MEDIUM — relies on author discipline to maintain anchors |

**Verdict**: SECONDARY. Worth considering if line-range drift in indexes proves problematic.

---

## §5. Recommended approach

### §5.1 Phased execution

**Phase 1 (low-risk; reversible; ~1-2 cycles)** — REVISED 2026-05-15 per research §3.6:
- **A. Apply existing `_validation_log.md` archive policy NOW** (don't wait for Phase 2 R1 close-out): archive pre-2026-04-12 entries to `_validation_log_archive_2026-04.md`; truncate live file to last 30 days. Mechanical execution per the policy at L14-23.
- **B. Author master `INDEX.md`** (cross-ref manifest per Option E + llms.txt structure per research §3.6 Finding 4): H1 project name + blockquote summary + sections with linked files + per-entry **routing-by-intent** descriptions ("If you need X, read this; if you need Y, skip and read Z" — NOT structural summaries; per ETH Zurich research §3.6 Finding 5)
- **C. Author per-file INDEX.md sidecars** for the 10 files over 1,000 lines (Option B) — same routing-by-intent constraint
- **D. Update D62 CCL doctrine** to add Stage 0 (read `INDEX.md` first; use targeted offset-Read for files >500 lines)
- **E. Author `udm-find-canonical` skill** (Option T3 — ELEVATED from Phase 4 per research §3.6): SKILL.md under 500-line cap (Anthropic standard); supporting `routing-table.md` file with full canonical-home table; agents invoke for one-shot D-number / B-number / R-number / SP-N / RB-N lookups instead of grepping files

**Phase 2 (medium-risk; tooling support + multi-agent optimization; ~1-2 cycles)** — REVISED 2026-05-15 per research §3.6:
- **F. Author `tools/regenerate_md_indexes.py`** — single source-of-truth generator for `INDEX.md` + per-file `*_INDEX.md`; takes spec doc paths as input; emits the index files
- **G. Add pre-commit hook** invoking the generator — **`auto-add-if-changed` design** (NOT `fail-if-stale`; per research §3.6 Finding 13 + Recommendation 3): hook runs regenerator, adds INDEX.md to commit if changed, succeeds silently. Alternative: integrate INDEX regeneration into `udm-round-closeout` skill as a human-triggered step at round boundaries. Both options preserved; pipeline-lead picks at execution time.
- **H. Update `tools/verify_cascade.py`** Pattern F Layer 1 script to incorporate INDEX validity (catches stale-index drift) — read-only check; never modifies tree
- **I. Author `udm-context-loader` subagent** (Option T5 — NEW per research §3.6 Finding 11 + Recommendation 5): for multi-agent Pattern E + Pattern F cycles; one subagent performs full CCL read in isolated context + returns structured brief (~500-1K lines) to parent; parent passes brief to downstream agents who skip CCL. Reduces per-cycle context cost ~50K-65K lines for Pattern E (5-agent) cycles.

**Phase 3 (higher-risk; targeted splits; conditional)**:
- Only execute IF Phase 1+2 measured discoverability gain falls short of the §6 metrics
- Candidates (in order of payoff): `03_DECISIONS.md` (split by D-number ranges or by topic) > `phase1/06_deployment.md` (split per § major) > `phase1/01_database_schema.md` (split per table)
- Any split requires: (a) cross-reference verification script run; (b) Pattern F audit script update; (c) D-number lock for the supersession (per D92 forward-only)

**Phase 4 (polish; conditional)**:
- Frontmatter + tagged sections (Option D) for files that prove hard to index by line range
- Inline anchor comments (Option T4) for fine-grained Grep targeting
- `udm-find-canonical` skill (Option T3) for one-shot canonical-home lookups

### §5.2 Decision rationale

- **Phase 1 is purely additive** — every change is a new file; existing cite patterns unchanged; immediately reversible via `git revert`
- **Phase 2 closes the maintenance loop** — generators + pre-commit hooks ensure indexes don't rot
- **Phase 3 is conditional on Phase 1+2 proving insufficient** — measured against §6 metrics, not anticipated
- **Phase 4 is polish** — only invoked if specific pain points emerge

---

## §6. Quality gates (per D55 5-gate discipline)

Each phase must pass these gates BEFORE merging to master:

### Gate 1 — Cross-reference integrity
- For each newly-authored INDEX entry: assert the cited line range matches the source file's current state (script: `tools/verify_md_index_consistency.py`)
- For each EXISTING cite in the repo (e.g., `phase1/05_tests.md § 8.2 L488`): assert it still resolves to the expected heading (Pattern F Layer 1 extension)

### Gate 2 — QA / Pattern E independent reviewer
- Spawn `udm-design-reviewer` agent + `udm-checks-and-balances` skill against the refactor commit
- Surface any 🔴 (broken cite, lost content, INDEX-vs-source drift)

### Gate 3 — Edge case enumeration
- M-series: any cross-source content moved to wrong canonical home?
- N-series: any null-state where INDEX entry exists but source is missing?
- I-series: idempotent regeneration of indexes (same input → byte-identical INDEX output)?

### Gate 4 — Edge case validation
- Run the regenerator on a clean checkout; assert output matches committed INDEX
- Spot-check 10 random INDEX entries against source files

### Gate 5 — Idempotency / regression
- Pytest baseline preserved (refactor is doc-only; should not move any test count)
- Re-run Pattern F audit script post-refactor; assert no new 🔴 introduced

### D56 mandatory second-pass
- If Gate 1-5 first-pass returns 🔴: independent second-pass agent reviews the fix BEFORE any 🟡 → 🟢 lock

---

## §7. Phased execution detail

### §7.1 Phase 1 work breakdown (proposed; ~1-2 cycles)

| Task | Owner | Effort | Outputs |
|---|---|---|---|
| 1.1 Survey current `_validation_log.md` cutoff date for archive | Pipeline lead | <30 min | Cutoff date decided (proposed: 2026-04-12 per the policy as written) |
| 1.2 Execute archive cascade for `_validation_log.md` | Parent agent | ~1 hour | `_validation_log_archive_2026-04.md` authored; live file truncated; 1-line back-reference added |
| 1.3 Author `docs/migration/INDEX.md` (cross-ref manifest) | Parent agent | ~2-3 hours | INDEX with D-numbers / B-numbers / R-numbers / SP-N / RB-N / Pattern codes / Pitfall sub-classes / EventType families |
| 1.4 Author per-file `<file>_INDEX.md` for 10 large files | Parent agent | ~1-2 hours | 10 sidecar INDEX files |
| 1.5 Update D62 CCL doctrine + relevant skill prompts | Pipeline lead | ~1 hour | D62 entry updated; udm-* skill SKILL.md files reference Stage 0 |
| 1.6 Pattern E independent review (Gate 2) | Sub-agent | ~30 min | ✅ CLEAN verdict required for merge |

### §7.2 Phase 2 work breakdown (proposed; ~1 cycle)

| Task | Owner | Effort | Outputs |
|---|---|---|---|
| 2.1 Author `tools/regenerate_md_indexes.py` | Engineer or parent agent | ~2-3 hours | Pure-Python script; reads source files; emits INDEX + per-file INDEX |
| 2.2 Author Tier 0 + Tier 1 tests for the generator | Per `udm-test-author` Tier 0 + Tier 1 conventions | ~1-2 hours | `tests/tier0/test_regenerate_md_indexes.py` + `tests/tier1/test_regenerate_md_indexes.py` |
| 2.3 Add pre-commit hook | Pipeline lead | <30 min | `.pre-commit-config.yaml` entry; CI gate added |
| 2.4 Extend `tools/verify_cascade.py` to validate INDEX consistency | Engineer or parent agent | ~1 hour | Pattern F Layer 1 enhancement |

### §7.3 Phase 3 + Phase 4

Specifications + work-breakdown will be authored at the close of Phase 2 IF the §6 metrics indicate need. Skipping detail here to avoid premature design.

---

## §8. Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| **R-MR1** Phase 1 INDEX line ranges drift on subsequent edits before pre-commit hook lands (Phase 2) | Medium | Low | Phase 1 INDEX is best-effort; agents tolerate 5-line drift via Grep fallback. Phase 2 hook closes the loop. |
| **R-MR2** Pattern F audit script (`tools/verify_cascade.py`) regex breaks if a file path or line anchor changes | Low | Medium | Phase 1 doesn't move any source file; only adds new INDEX files. Pattern F regex unaffected. |
| **R-MR3** D62 CCL doctrine update introduces an extra mandatory read; cumulative agent overhead increases short-term until INDEX-first habit lands | Low | Low | INDEX is small (target <300 lines); net read budget LOWER post-update because Stage 1+2 specific reads become offset-bounded |
| **R-MR4** `_validation_log.md` archive cutoff date debate (2026-04-12 vs other) | Low | Low | Policy at L14-23 already specifies 30-day cutoff; pipeline-lead decides at execution time |
| **R-MR5** Phase 3 file splits break ~100s of inline cites (cascading edit cost) | High (if Phase 3 fires) | High (if Phase 3 fires) | Mitigated by Phase 1+2 making Phase 3 conditional on metric-proven need; Pattern F audit script + grep-based cite-rewrite tooling required as prereq |
| **R-MR6** Pre-commit hook (Phase 2) becomes a commit-friction source if generator is slow | Low | Medium | Generator targets <2 second runtime; opt-out flag for emergency commits |
| **R-MR7** Frontmatter (Option D) introduces YAML parser dependency for agents | Low | Low | Phase 4 only; reversible; agents can ignore frontmatter without breaking canonical reads |

---

## §9. Metrics for success

Phase 1+2 are considered successful if ALL of:

1. **CCL Stage 1+2 read budget**: median agent invocation reads ≤2,000 lines for CCL (down from current ~12K-16K) — measured via tool-call traces over 5 sample agent invocations post-Phase-1
2. **Re-read frequency**: parent-agent re-reads of CLAUDE.md / CURRENT_STATE.md / HANDOFF.md drop ≥50% (measured via tool-call traces)
3. **INDEX freshness**: pre-commit hook never blocks a commit due to stale INDEX after first 2 weeks of Phase 2 (auto-regen working as intended)
4. **Zero broken cites**: Pattern F Layer 1 audit + spot-check of 20 random cites — 0 broken
5. **Pytest baseline preserved**: refactor is doc-only; pytest count unchanged
6. **Reversibility verified**: at least 1 dry-run `git revert` of a Phase 1 commit; verify clean reversion

Phase 3 is invoked ONLY IF Phase 1+2 fail metrics 1 OR 2 by >25%.

---

## §10. Open questions for pipeline lead

1. **Approval to proceed with Phase 1?** (Phase 1 is reversible / additive; low-risk to start; now includes `udm-find-canonical` skill per research §3.6)
2. **`_validation_log.md` archive cutoff** — is 2026-04-12 (per existing policy text) the right boundary, or should it shift to align with a recent round-close-out date?
3. **INDEX scope** — should `INDEX.md` cover ONLY the canonical-home cite-targets (D-numbers / B-numbers / etc.), OR also include "where to find topic X" navigation entries? Note research §3.6 Finding 5 + Recommendation 1 constraint: must be routing-by-intent, NOT structural-by-description.
4. **Pre-commit hook adoption** — is the project ready for a pre-commit hook? Now framed per research §3.6 Recommendation 3: "auto-add-if-changed" design, NOT "fail-if-stale"; alternative is INDEX regeneration as `udm-round-closeout` step (human-triggered). Pipeline-lead picks.
5. **D-number tracking** — should this refactor land its own D-number for the architectural decision (proposed D-N for "INDEX-front documentation discipline")? Per D111 process-infra exemption, would lock 🟢 directly without 🟡-first attestation.
6. **Skill update scope for D62** — which skills' SKILL.md files need Stage 0 added? Probably ALL the udm-* family; a one-shot sweep at Phase 1 close. Per gap §10b.1 G-MR3: enumerate affected skills BEFORE the sweep.
7. **Snowflake test fixture parquet pre-staging documentation** (orphan question from G6 of prior cascade gap-check) — does the Q10 weekly drill template need a backup runbook authored before first execution? Could pair with this refactor work.

**Q-8 (NEW per gap §10b.2 EC-MR5)**: Should INDEX.md be referenced from project-root CLAUDE.md so ad-hoc Claude Code sessions naturally pick it up (parent-level CLAUDE.md loads at startup per Anthropic mechanism)? Or stay agent-only via D62 CCL Stage 0?

**Q-9 (NEW per gap §10b.2 EC-MR7)**: Should `GLOSSARY.md` merge into `INDEX.md` (single file; code-family definitions + per-instance locations co-located) OR retain separation (GLOSSARY = code-family definitions; INDEX = per-instance line numbers)? Trade-off: merge reduces "where do I find X" ambiguity; separate respects existing reader expectations.

**Q-10 (NEW per gap §10b.3 A-MR3)**: Should the project commission its own benchmark study post-Phase-1+2 (compare instrumented agent invocations pre-/post-Phase-1 with line-count + tool-call traces) to validate the routing-by-intent design empirically? The ETH Zurich evidence generalizes from code-repo navigation; project-internal planning-doc navigation isn't directly benchmarked anywhere we found.

**Q-11 (NEW per research §3.6 Finding 11 / Option T5)**: Approve authoring `udm-context-loader` subagent at Phase 2 (Option T5)? Highest leverage for multi-agent Pattern E + Pattern F cycles; reduces per-cycle context cost ~50K-65K lines for 5-agent cycles.

**Q-12 (NEW per gap §10b.1 G-MR2)**: Approve CLAUDE.md (project root, 715 lines) audit + content-trimming at Phase 1.6 per Anthropic's "Keep it concise" guidance (research §3.6 Finding 1)? Target: <300 lines; move "sometimes-relevant" content to skills. Highest single-file leverage since CLAUDE.md loads at EVERY agent startup.

---

## §10b. Independent gap audit (added 2026-05-15)

Walking the plan with critical-reviewer perspective post-research integration. Findings:

### §10b.1 Confirmed gaps (worth fixing before approval)

| Gap | Severity | Recommendation |
|---|---|---|
| **G-MR1** No baseline measurement protocol specified | 🔴 — without baseline, §9 metrics are unverifiable | Add Phase 1.0 task: "instrument 3 sample agent invocations PRE-Phase-1; capture exact line-counts per CCL read + total tool-call count; commit baseline as `_research/ccl-baseline-2026-05-XX.md`" |
| **G-MR2** CLAUDE.md (project root, 715 lines) is itself in violation of Anthropic's "Keep it concise" guidance per research §3.6 Finding 1 | 🟡 — same file the project asks every agent to read at startup; high-leverage | Add Phase 1.6: "audit CLAUDE.md against Anthropic 'would removing this cause Claude to make mistakes?' test; move 'sometimes-relevant' content to skills per Finding 3; target reduction to <300 lines" |
| **G-MR3** D62 CCL doctrine modification cost not enumerated | 🟡 — ~10+ skill SKILL.md files reference D62 / CCL Stage 1+2; Stage 0 addition cascades | Add Phase 1.5b: "Grep `.claude/skills/**/SKILL.md` for D62 / 'Canonical Context Load' / 'Stage 1' references; enumerate affected skills; bulk-update via single commit OR per-skill commits with per-skill validation" |
| **G-MR4** Re-archive cadence for `_validation_log.md` not specified | 🟡 — Phase 1 archive cuts to ~1.5K lines; after 6 months operation, file regrows. Plan needs durable cadence | Add to §7.1 Phase 1.2: "extend archive policy at L14-23 to specify quarterly re-archive cadence (every Phase round close-out OR ~30-day cron); not just one-time" |
| **G-MR5** `tools/regenerate_md_indexes.py` failure modes not specified | 🟡 — what happens if generator can't parse a file? Pre-commit blocked? Manual override? | Add to §7.2 Phase 2.1: "generator must (a) skip+warn on parse failure (not abort), (b) emit a `_index_errors.md` artifact listing skipped files, (c) support `--skip-validation` flag for emergency overrides, (d) exit 0 even on partial-failure (warnings only)" |
| **G-MR6** Phase 3 trigger criteria timing unclear | 🟡 — §5 says "if Phase 1+2 fail metrics 1 OR 2 by >25%" but doesn't say WHEN measurement happens | Add to §9: "metrics measured at 14-day mark post-Phase-2-completion; Phase 3 decision at 21-day mark; adoption trends collected via tool-use trace sampling (5 agent invocations / week minimum)" |
| **G-MR7** Reviewer-burden cost analysis missing | 🟡 — Phase 1+2 add 5 new validation gates per artifact; expands existing Pattern E + Pattern F cost | Add to §6: "Phase 1+2 validation gates re-use existing Pattern E + Pattern F discipline (no new specialty roles); estimated incremental review cost = 1 cycle of Pattern E (5-agent parallel) at Phase 1 close + 1 cycle at Phase 2 close" |

### §10b.2 Edge cases the plan should explicitly address

| Edge case | Plan handles? | Recommended addition |
|---|---|---|
| **EC-MR1** Agent reads INDEX.md, then Read with offset, but file has been edited between INDEX regen and the offset-Read (line drift) | ❌ Not addressed | Add to §8 risk register as R-MR8 (low likelihood / medium impact); mitigation: Grep-by-anchor fallback (Option T4) when offset-Read content doesn't match INDEX-cited heading |
| **EC-MR2** Agent reads INDEX.md but INDEX is itself stale (regenerator failed silently) | ❌ Not addressed | Add to §6 Gate 1: "INDEX.md MUST carry a `last_regenerated_at` line at the top; agents check the timestamp; if older than 14 days, fall back to direct file Read with warning" |
| **EC-MR3** Multi-agent Pattern E cycle: one agent's brief differs from another's brief due to non-deterministic CCL summarization | ❌ Not addressed | Add to §8 risk register as R-MR9 (medium likelihood / medium impact); mitigation: `udm-context-loader` subagent must produce DETERMINISTIC briefs (canonical structure + sorted entries + stable formatting); test with 5x repeated invocation on same input |
| **EC-MR4** Phase 3 file split breaks the Pattern F audit script's regex patterns silently | ⚠️ Partially (R-MR2 + Phase 2.4) | Strengthen §7.2 task 2.4: "Pattern F regex extension MUST be implemented BEFORE any Phase 3 split; verified via dry-run + test fixture covering current path patterns" |
| **EC-MR5** User invokes Claude Code WITHOUT performing CCL (ad-hoc question; no skill invocation) — does the INDEX still help? | ❌ Not addressed | Add to §10 open question Q-8: "Should INDEX.md be referenced from project-root CLAUDE.md so ad-hoc Claude Code sessions naturally pick it up? Or stay agent-only?" |
| **EC-MR6** `_validation_log.md` archive split breaks any tool that grepss across the full log (e.g., `_reviewer_effectiveness.md` historical generation) | ❌ Not addressed | Add to §6 Gate 1: "post-archive, run `grep` against the canonical use cases (reviewer-effectiveness ledger generation; B-N audit-trail lookups); verify both archive + live files are searched" |
| **EC-MR7** GLOSSARY.md (799 lines) overlaps with the proposed master INDEX.md scope (per-code-family location index at L601) | ⚠️ Partially noted in §3.5 | Add to §10 open question Q-9: "Should GLOSSARY.md merge into INDEX.md (one file vs. two) OR retain separation (GLOSSARY = code-family definitions; INDEX = per-instance locations)?" |
| **EC-MR8** Phase 1 INDEX.md authoring is itself a large markdown file (~300-500 lines) — does it self-violate? | ❌ Not addressed | Add to §6 Gate 5: "INDEX.md size must stay under 500 lines per Anthropic SKILL.md cap (research §3.6 Finding 7); if exceeds, split into per-code-family sub-INDEX files (D-INDEX.md / B-INDEX.md / etc.)" |

### §10b.3 Untested assumptions

| Assumption | Currently | Recommended grounding |
|---|---|---|
| **A-MR1** Agents will adopt the new D62 Stage 0 read-INDEX-first discipline once added to the doctrine | Optimistic | Add a `tests/tier0/test_skill_ccl_includes_stage_0.py` Tier 0 smoke test that asserts every `udm-*` SKILL.md file contains a "Stage 0" CCL reference post-Phase-1.5 |
| **A-MR2** Per-cycle pre-commit hook latency stays <2 seconds (§9 metric implicit) | Untested | Add to §9 metric: "Phase 2.3 pre-commit hook regenerator runtime ≤ 2 seconds for current docs/migration/ size; benchmarked at Phase 2 close" |
| **A-MR3** ETH Zurich research finding (architectural overviews don't help) generalizes to internal planning-doc corpora | Inferred from adjacent domain (code repos) | Add to §10 open question Q-10: "Should the project commission its own benchmark study post-Phase-1+2 (compare instrumented agent invocations pre-/post-Phase-1) to validate the routing-by-intent design?" |
| **A-MR4** `udm-find-canonical` skill (elevated to Phase 1) will be invoked frequently enough to justify authoring | Speculative | Add to §9 metric: "Phase 1 success requires `udm-find-canonical` invocation ≥10× per week within 14 days of skill landing; tracked via `_reviewer_effectiveness.md` extension" |

### §10b.4 Out-of-scope confirmations

For audit-trail completeness, items confirmed OUT of scope:

- **Production Python file refactoring**: largest is `bcp_loader.py` at 2,210 lines; well below the 6K-line threshold the user originally cited. Per user clarifying directive #3 ("Specifically, we refactor markdown files"), code-file refactoring is OUT of this plan's scope. Code-side refactor would warrant its own separate planning effort if surfaced later.
- **Snowflake documentation conventions for AI agents**: Phase 5 territory; out of scope for Phase 1-4 markdown refactor.
- **Semantic search / embeddings within Claude Code project docs**: out of scope for Phase 1-4; would require external dependencies (vector DB, embedding model) that conflict with §2.2 non-goal #4.
- **`llms-full.txt` variant** (alternative to llms.txt that includes full content rather than links): considered + rejected — full-content variant defeats the purpose of context-cost reduction; the plan's INDEX.md follows the linked-files variant.

---

## §11. Cross-references

- D55 (5-gate validation discipline) — Quality gates §6
- D56 (mandatory second-pass) — D56 reference at Gate §6
- D60 (round close-out cascade) — applies if this refactor spans a round close-out
- D62 (Canonical Context Load) — directly modified by Phase 1.5; cascading skill-prompt updates per gap §10b.1 G-MR3
- D89/D90/D91 (Pattern F discipline) — Pattern F audit script extension at Phase 2.4
- D92 (forward-only schema-evolution) — extends to spec doc structure: any file split = D-number lock
- D111 (process-infra D-number exemption) — applies if a new D-number is proposed for this refactor
- B30 (D62 first-pass) — CCL canonical Stage 1+2 order; Stage 0 addition is additive per D92
- HANDOFF §8 Pitfall #9.k (arithmetic-propagation) — INDEX line ranges are arithmetic; subject to 9.k discipline
- `tools/verify_cascade.py` — Pattern F Layer 1 script extension at Phase 2.4
- `_validation_log.md` L14-23 — existing archive policy executed in Phase 1.1-1.2
- `GLOSSARY.md` § "Where each code family lives (one-line index)" L601 — partial precedent for the master INDEX; merge-vs-separate decision deferred to gap §10b.2 EC-MR7 / open question Q-9
- `MULTI_AGENT_GUIDE.md` § Canonical Context Load — modified by Phase 1.5
- **`docs/migration/_research/agent-markdown-traversal-2026-05-15.md`** (added 2026-05-15) — udm-researcher artifact with 13 findings + 15 primary sources; canonical research backing for §3.6 + §10b
- Anthropic Claude Code best practices: https://code.claude.com/docs/en/best-practices (cited in §3.6 Findings 1-2 + 11)
- Anthropic Claude Code skills: https://code.claude.com/docs/en/skills (cited in §3.6 Findings 3 + 7)
- llms.txt open standard: https://llmstxt.org/ (cited in §3.6 Finding 4; structural template for INDEX.md)
- ETH Zurich AGENTS.md research: https://www.infoq.com/news/2026/03/agents-context-file-value-review/ (cited in §3.6 Finding 5; counter-evidence for naive structural overviews)

---

## §12. Sign-off

This is a 🟡 Plan-draft. NO execution work begins until pipeline-lead reviews + approves OR redirects.

| Role | Name | Date | Decision |
|---|---|---|---|
| Pipeline lead | | | ✅ Approved as-is / 🔄 Redirect (see notes) / ❌ Rejected |
| Notes | | | |

If approved as-is: Phase 1 work begins with task 1.1 (survey `_validation_log.md` cutoff date). If redirected: re-author this plan with the redirect captured. If rejected: archive this plan as `_research/markdown_refactor_plan_<date>.md` and document rejection rationale in `_validation_log.md`.
