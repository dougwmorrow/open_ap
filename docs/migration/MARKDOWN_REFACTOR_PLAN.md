# Markdown Refactor + Agent Traversal System — Plan

**Status**: 🟢 **LOCKED 2026-05-15** — pipeline-lead approved all 4 binary 🔴 BLOCKING questions (Q-1 / Q-2 / Q-12 / Q-23) with Recommended defaults; sign-off attestation at §12; Phase 1 execution authorized. **HOWEVER**: D.0 reconnaissance (per §7.1 task 1.1) surfaced an empirical impasse for Phase D.1 (`_validation_log.md` archive cascade) — at 2026-04-15 cutoff, **zero entries qualify for archive** (earliest log entry is 2026-05-09; all 125 entries are within the 30-day retention window). Q-2 approval stands as policy; Phase D.1 execution requires a follow-up pipeline-lead decision (defer until entries age / aggressive-retention override / different split strategy). Tracked as **B-272** in BACKLOG. **Plan-prior history**: research-grounded + empirical-validation-complete + 3 critical-failure mitigations APPLIED inline + 3 BLOCKERS CLOSED inline (B-3 verify_cascade.py glob fix; B-4 §7.1 task 1.1 literal cutoff date 2026-04-15; B-5 §10.A Q-N classification table 4 🔴 / 8 🟡 / 12 ⚪) + §18 phase breakdown reference. **REVISED 2026-05-15 (4th revision)** with: (a) §3.6 research synthesis #1; (b) §10b independent gap audit; (c) §13 Option A deep-dive (research #2); (d) §15 cross-domain synthesis (research #3-5; 3 parallel artifacts); (e) **§16 long-term maintenance + governance (NEW)** addressing user Q1-Q3 directives; (f) **EMPIRICAL VALIDATION COMPLETE** — Q-22 em-dash test resolved via `tools/test_github_slug.py` + `_research/em-dash-slug-test-2026-05-15.md` (binding revision: colon-form `## D15: Title` mandatory); Q-13 token cost measurement resolved via `tools/measure_ccl_overhead.py` + `_research/ccl-baseline-2026-05-15.md` (CCL Stage 1+2 = 362K tokens = 181% of 200K window; `_validation_log.md` alone = 115% of window; archive cascade promoted to Phase 1.0 immediate priority); (g) 19 cumulative open questions Q-8 through Q-26 (Q-13 + Q-22 RESOLVED; 17 remaining for pipeline-lead). Backing research: **6 udm-researcher artifacts** + **2 empirical-test deliverables** at `_research/` + `tools/` (~50 cumulative findings; ~70 primary sources; medium-high confidence + 2 P0 empirical results). Plan now ~1080 lines — recommend split at next refactor cycle. Companion: `NEW_REPO_STARTER_TEMPLATE.md` (greenfield template per Q-24).

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

**Verdict (REVISED 2026-05-15 per §13 deep-dive)**: Avoid as Phase 1. Reserve for Phase 3 (targeted splits where Phase 1+2 prove insufficient) — AND requires §13.3 cross-reference preservation as a binding precondition. The Navigation Paradox (research §C-2; arxiv 2602.20048) makes "see D15" plain-text references dead-on-split unless rewritten as `[D15](03_DECISIONS_phase1.md#d15)`. See §13.1 for naming convention + §13.2 for TOC structure + §13.3 for the binding cross-ref preservation rule + §13.4 for slug-stability policy.

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

**Phase 1 atomic-cohort gate (BINDING per F9.1 mitigation; 🔴 CRITICAL)** — RELAXED 2026-05-15 to ONE-DIRECTIONAL per **B-273 ⚫ CLOSED** (pipeline-lead Option A choice for B-273 path): Phase 1.0 (`_validation_log.md` archive cascade) and Phase 1.B (master `INDEX.md` authoring) MAY land independently with the following asymmetric rules:

- **🔴 REJECT condition #1 (preserved)**: PR contains Phase 1.0 archive-cascade changes (live `_validation_log.md` truncated OR `_validation_log_archive_*.md` created) but does NOT contain `docs/migration/INDEX.md` — REJECT with reason "F9.1 atomic-cohort violation; D.1-without-D.2 is the originally-documented failure mode (operator ships MVP archive, never ships V1 routing manifest)".
- **✅ ALLOW condition (NEW per B-273 relaxation)**: PR contains `docs/migration/INDEX.md` but Phase 1.0 has NOT run (live `_validation_log.md` still >2,000 lines; no `_validation_log_archive_*.md` present) — ALLOW. Rationale: the live audit trail remains FULLY searchable; INDEX.md provides routing improvement immediately; future Phase 1.0 work appends archive without breaking INDEX.md.
- **Verification mechanism (revised one-directional)**: (1) `tools/verify_cascade.py` Trigger N extension (B-N candidate at Phase 2.4) asserts ONE-DIRECTIONAL gate: if `_validation_log_archive_*.md` exists in commit OR live `_validation_log.md` is below pre-trim baseline, INDEX.md MUST also exist; reverse direction is NOT checked; (2) `udm-round-closeout` skill CCL Stage 2.5 asserts the same one-directional invariant at round-boundary.
- **Rationale for relaxation (B-273 closure 2026-05-15)**: original bidirectional binding (per gap-audit-adversarial §9 + §17.3) was specifically about D.1-WITHOUT-D.2 (operator gets the fast win on archive then loses momentum on INDEX; repo ends WORSE than pre-refactor because audit-trail navigation needs cross-file awareness without routing manifest). The REVERSE (D.2-without-D.1) doesn't have this failure mode because: (a) live audit trail still exists in full searchable form; (b) INDEX.md helps navigation regardless of archive status; (c) future D.1 work appends archive entries that INDEX.md cross-refs naturally. Per B-272 empirical impasse (Phase D.1 deferred indefinitely until entries age ~24 days), the bidirectional binding had become a foot-gun BLOCKING the highest-leverage independent Phase 1 work; one-directional relaxation preserves anti-MVP intent while unblocking parallel D.2/D.3/D.4 progress.
- **B-273 ⚫ CLOSED 2026-05-15 same-commit**.

**Phase 1 (low-risk; reversible; ~1-2 cycles)** — REVISED 2026-05-15 per research §3.6 + §15.4 empirical baseline:
- **0. PROMOTED (per §15.4 empirical baseline 2026-05-15) — `_validation_log.md` archive cascade is the SINGLE-MOST-CONSEQUENTIAL Phase 1 task**: empirical token measurement shows this one file = 231K tokens = 115% of 200K context window for a single Stage 2 read. Trimming it by 73% (7,519 → 2,000 lines) recovers ~62% of CCL Stage 1+2 token cost. **Execute first; gate other Phase 1 tasks on this completing.**
- **A. ~~Apply existing `_validation_log.md` archive policy NOW~~ → see Phase 1.0 above (promoted to Phase 1.0 immediate priority)**
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
- **NEW (per §13.6 plan calculus change #2)**: INDEX.md MUST be written as routing-by-intent ("if your task involves X, read file Y") NOT as structural-by-description ("file Y contains sections A/B/C"). Validation: Pattern E reviewer agent inspects INDEX.md against the routing-vs-structural distinction; flags structural-style entries as 🟡 for revision per ETH Zurich research §3.6 Finding 5 (structural overviews increase agent inference cost +20-23% with success rate -3%).
- **NEW (per §13.3 Navigation Paradox constraint)**: For Phase 3 splits ONLY — verify all inbound cross-references to moved content are rewritten as relative Markdown links pointing to the new target file. Pattern F audit script extension at Phase 2.4 MUST verify this; failure on any unconverted plain-text reference = 🔴 BLOCKER.

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

> **2026-05-15 amendment**: Tasks 1.1 + 1.2 are 🟡 BLOCKED pending B-272 resolution. D.0 reconnaissance (`_research/d0-prep-validation-log-survey-2026-05-15.md`) found that at the approved 2026-04-15 cutoff, **zero entries qualify for archive** (earliest log entry is 2026-05-09; all 125 entries are within the 30-day retention window). Q-2 approval stands as policy; Phase D.1 execution path requires a follow-up pipeline-lead decision. See B-272 for the 5 enumerated options. Tasks 1.3-1.6 remain 🟢 AUTHORIZED standalone (see §12.3).

| Task | Owner | Effort | Outputs |
|---|---|---|---|
| 1.1 Compute archive cutoff date for `_validation_log.md` per existing policy at L12-19 (B-4 fix 2026-05-15) | Pipeline lead | <10 min | ✅ DONE 2026-05-15: cutoff date = 2026-04-15 (per Q-2 approval) |
| 1.1b 🆕 D.0 reconnaissance — survey `_validation_log.md` for entries qualifying for archive at cutoff | Parent agent | <10 min | ✅ DONE 2026-05-15: `_research/d0-prep-validation-log-survey-2026-05-15.md`. **Empirical finding: zero entries qualify** at 2026-04-15 cutoff. 5 options surfaced for pipeline-lead resolution. Tracked as **B-272**. |
| 1.2 Execute archive cascade for `_validation_log.md` (TWO-PHASE-COMMIT per F1.1 mitigation; 🔴 CRITICAL) | Parent agent | ~1 hour | 🟡 **BLOCKED pending B-272 resolution.** When unblocked, output is: `_validation_log_archive_2026-04.md` authored via two-phase-commit; live file truncated; 1-line back-reference added |

**F1.1 mitigation — two-phase-commit procedure (BINDING for task 1.2)**:

1. **Phase A — write archive to `.tmp`**: parent agent writes archive content to `_archive/_validation_log_archive_2026-04.md.tmp` (note `.tmp` suffix). Compute SHA-256 of the written content; record expected line count (= number of source entries in the archive cutoff range).
2. **Phase A verify**: re-read the `.tmp` file; assert SHA-256 matches; assert line count matches; assert first line + last line match the expected cutoff boundary (first archived entry date ≤ cutoff, next entry in live file date > cutoff).
3. **Phase B — atomically replace live file**: write the truncated live `_validation_log.md` content to `_validation_log.md.tmp.new`; verify line count = (original live line count) − (archived line count) + 1 (the back-reference line); use `os.replace('_validation_log.md.tmp.new', '_validation_log.md')` (atomic on both POSIX + Win32).
4. **Phase C — finalize archive**: `os.replace('_archive/_validation_log_archive_2026-04.md.tmp', '_archive/_validation_log_archive_2026-04.md')`. Order Phase B BEFORE Phase C: if B succeeds + C crashes, the recovery path is "rename the existing `.tmp` to final"; if C succeeds + B crashes, recovery is impossible (live file has entries that already exist in finalized archive — duplicates).
5. **Failure-mode detection (pre-commit + script-startup)**: any `_archive/*.tmp` file at script start = previous run crashed during Phase A/C; abort + require operator manual recovery. Any `_validation_log.md.tmp.new` at script start = previous run crashed during Phase B; same. Pattern F Layer 1 extension catches stale `.tmp` files in commits.
6. **Acceptance verification**: post-run assertion: (a) SHA-256 of archive + truncated live + back-reference line concatenated together = SHA-256 of original pre-archive live file; (b) no `.tmp` files remain; (c) `wc -l` on truncated live ≤ 2,000.
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

**Q-13 through Q-17** — see §13.6 (5 new questions derived from §13.5 meta-research candidates). Summary: Q-13 (token cost measurement P2 immediately) / Q-14 (Navigation Paradox UDM topology mapping P1 before Option A) / Q-15 (intent.lisp investigation P4 at Phase 1 design) / Q-16 (auto-compaction interaction P7 at Phase 1 design) / Q-17 (heading-slug stability policy §13.4 as binding rule for ALL future heading authoring).

**Q-18 through Q-22** — see §15.5 (5 new questions derived from §15 cross-domain synthesis). Summary: Q-18 (CCL stages as quality tiers per Q1 LLM-training Pattern A) / Q-19 (lead-with-answer writing discipline per Q3 GEO 44.2% finding) / Q-20 (near-duplicate-paragraph audit across canonical trackers per Q1 dedup pattern) / Q-21 (4-component cross-ref maintenance design per Q2 research) / Q-22 ✅ **RESOLVED 2026-05-15** via empirical em-dash test — see §13.4 + §15.4; binding revision: heading style is now COLON-FORM `## D15: Title`.

**Q-13 ✅ RESOLVED 2026-05-15** via empirical token measurement — see §15.4. CCL Stage 1+2 = 362K tokens (181% of 200K window); `_validation_log.md` alone = 231K (115% of window). Phase 1.0 promoted as immediate priority.

**Q-23 through Q-26** — see §16.6 (4 new questions derived from §16 long-term maintenance + governance). Summary: Q-23 (6-rule markdown hygiene enforcement as binding D-N candidate) / Q-24 (NEW_REPO_STARTER_TEMPLATE.md as canonical greenfield reference) / Q-25 (Q11 quarterly research-refresh cadence) / Q-26 (year-1 milestones Day 0/30/90/180/365 as roadmap commitment).

### §10.A Sign-off-blocking vs deferrable Q-N classification (B-5 fix 2026-05-15)

Per blocker-evidence-verification artifact + Wave 1 Agent A audit. The 24 unresolved questions (Q-13 + Q-22 RESOLVED earlier) are classified below by sign-off impact:

- 🔴 **SIGN-OFF BLOCKING** — pipeline-lead MUST answer before plan can flip 🟡 Plan-final → 🟢 Locked
- 🟡 **PHASE-1 DESIGN DECISION** — answer when starting the affected Phase 1 task; doesn't block sign-off
- ⚪ **DEFERRABLE** — answer when needed; not blocking; can land as B-N post-approval

| Q-N | Brief description | Classification | Rationale |
|---|---|---|---|
| Q-1 | Approval to proceed with Phase 1? | ✅ RESOLVED 2026-05-15 | Approved — Phase 1 starts now (Recommended); see §12 sign-off |
| Q-2 | `_validation_log.md` archive cutoff date | ✅ RESOLVED 2026-05-15 | Accepted 2026-04-15 (Recommended); see §12 sign-off. **Empirical impasse caveat**: D.0 prep found zero entries qualify at this cutoff (earliest entry 2026-05-09); Phase D.1 execution requires follow-up decision per B-272 |
| Q-3 | INDEX scope (canonical-only vs routing-by-intent) | 🟡 DESIGN | Answer when starting Phase 1.3 (INDEX.md authoring); doesn't gate sign-off |
| Q-4 | Pre-commit hook adoption (auto-add vs fail-if-stale) | 🟡 DESIGN | Phase 2.3 question; Phase 1 doesn't touch hooks |
| Q-5 | D-N for the refactor decision itself | ⚪ DEFERRABLE | Bookkeeping; per D111 process-infra exemption can land directly when authored |
| Q-6 | Skill update scope for D62 | 🟡 DESIGN | Phase 1.5 question; bulk-update enumerable at execution time |
| Q-7 | Snowflake test fixture pre-staging runbook | ⚪ DEFERRABLE | Orphan from prior cascade; not part of this refactor; can pair OR not |
| Q-8 | INDEX.md ref'd from project-root CLAUDE.md? | 🟡 DESIGN | Phase 1.6 CLAUDE.md trim question; can decide at execution time |
| Q-9 | GLOSSARY.md merge into INDEX.md? | 🟡 DESIGN | Phase 1.3 INDEX scope question; can decide at execution time |
| Q-10 | Commission internal benchmark study post-Phase-1+2? | ⚪ DEFERRABLE | Post-Phase-2 question; doesn't gate Phase 1 |
| Q-11 | Approve `udm-context-loader` subagent at Phase 2? | 🟡 DESIGN | Phase 2 question; doesn't gate Phase 1 sign-off |
| Q-12 | Approve CLAUDE.md trim to <300 lines at Phase 1.6? | ✅ RESOLVED 2026-05-15 | Approved <300 line target (Recommended); see §12 sign-off |
| Q-14 | Approve P1 Navigation Paradox UDM topology mapping? | ⚪ DEFERRABLE | Meta-research; doesn't gate Phase 1 execution |
| Q-15 | Approve P4 intent.lisp investigation? | ⚪ DEFERRABLE | Meta-research; doesn't gate Phase 1 execution |
| Q-16 | Approve P7 auto-compaction interaction investigation? | ⚪ DEFERRABLE | Meta-research; doesn't gate Phase 1 execution |
| Q-17 | Approve §13.4 heading-slug stability as binding rule? | 🟡 DESIGN | Empirical revision already locked at §13.4 + Q-22 resolved; this Q is "binding for ALL future heading authoring?" — pipeline-lead picks at Phase 1.3+ |
| Q-18 | Label CCL stages as quality tiers in D62? | ⚪ DEFERRABLE | D62 doctrine update Phase 1.5; framing question; not blocking |
| Q-19 | Mandate lead-with-answer writing discipline for all NEW edits? | 🟡 DESIGN | Markdown hygiene rule; relates to Q-23; can pair |
| Q-20 | Near-duplicate-paragraph audit across canonical trackers? | ⚪ DEFERRABLE | Polish work; can land as B-N post-Phase-1 |
| Q-21 | 4-component cross-ref maintenance design? | 🟡 DESIGN | Phase 2.4 design question; doesn't gate Phase 1 |
| Q-23 | 6-rule markdown hygiene as binding (D-N candidate)? | ✅ RESOLVED 2026-05-15 | Approved all 6 rules as binding (Recommended); see §12 sign-off; D-N lock at next round close-out cascade |
| Q-24 | NEW_REPO_STARTER_TEMPLATE.md as canonical greenfield ref? | ⚪ DEFERRABLE | Internal-only artifact; binding-or-not doesn't block Phase 1 |
| Q-25 | Q11 quarterly markdown research-refresh cadence? | ⚪ DEFERRABLE | Quarterly cadence start date doesn't gate Phase 1 |
| Q-26 | Year-1 milestones (Day 0/30/90/180/365) as roadmap commitment? | ⚪ DEFERRABLE | Roadmap framing; can iterate post-Phase-1 |

**Count**: 4 ✅ RESOLVED 2026-05-15 (pipeline-lead approved all 4 BLOCKING with Recommended defaults) / **9** 🟡 DESIGN (move to Phase 1 design-decision queue; Q-3 + Q-4 + Q-6 + Q-8 + Q-9 + Q-11 + Q-17 + Q-19 + Q-21 — note: prior tally said "8" which was an arithmetic-propagation drift caught by udm-gap-check 2026-05-15 G2 finding #2; canonical enumeration shows 9 rows) / 11 ⚪ DEFERRABLE (move to post-sign-off candidate list; Q-5 + Q-7 + Q-10 + Q-14 + Q-15 + Q-16 + Q-18 + Q-20 + Q-24 + Q-25 + Q-26) = 24 total ✅ (4 + 9 + 11 = 24; Q-13 + Q-22 already RESOLVED earlier session per §15.4)

**Shortest path to sign-off**: Pipeline-lead answers 4 binary 🔴 questions:
1. **Q-1**: Approve Phase 1? (yes / no / redirect)
2. **Q-2**: Accept 2026-04-15 archive cutoff per existing policy? (yes / pick different date / change policy)
3. **Q-12**: Approve CLAUDE.md trim to <300 lines at Phase 1.6? (yes / no / partial)
4. **Q-23**: Approve 6-rule markdown hygiene as binding? (yes / no / pick subset)

Plan flips 🟡 Plan-final → 🟢 Locked once those 4 are answered. The 20 non-blocking questions move to Phase 1 design decisions OR a `_research/open_questions_post_sign_off.md` artifact post-approval.

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
- **`docs/migration/_research/agent-discoverability-2026-05-15.md`** (added 2026-05-15; follow-on) — udm-researcher artifact with 17 primary sources; canonical research backing for §13 (naming conventions + TOC design + Navigation Paradox + cross-reference preservation + 8 meta-research candidates); supersedes any pre-research scope-naming intuitions in earlier plan revisions
- **`docs/migration/_research/llm-training-data-storage-2026-05-15.md`** (added 2026-05-15; cross-domain Q1) — udm-researcher artifact on LLM training data storage techniques; ~20 primary sources including Anthropic FMTI report + Anthropic effective-context-engineering blog + MosaicML StreamingDataset + HuggingFace + NVIDIA + Gemini 2.5 technical report + Byte Latent Transformer ACL 2025 paper; canonical research backing for §15.2 Patterns A (quality tiers) + B (deduplication) + C (sidecar index files)
- **`docs/migration/_research/cross-reference-maintenance-agent-2026-05-15.md`** (added 2026-05-15; cross-domain Q2) — udm-researcher artifact on autonomous cross-ref maintenance design space; surveys lychee + markdownlint + DocLinkChecker + Vale + Drasi/GitHub Copilot case study + WarpFix; canonical research backing for §15.2 Pattern D (4-component design) + §13.4 critical em-dash empirical-test caveat
- **`docs/migration/_research/web-crawler-techniques-2026-05-15.md`** (added 2026-05-15; cross-domain Q3) — udm-researcher artifact on web crawler / search engine techniques; 20 primary sources including Google developers + W3C + SIAM Review (PageRank paper) + Microsoft Azure Search + 2026 GEO industry research + Leapd AI-search-engine study; canonical research backing for §15.2 Pattern E (slug-stability discipline) + §15.3 negative findings (llms.txt + PageRank + hybrid retrieval don't transfer)
- Anthropic Claude Code best practices: https://code.claude.com/docs/en/best-practices (cited in §3.6 Findings 1-2 + 11)
- Anthropic Claude Code skills: https://code.claude.com/docs/en/skills (cited in §3.6 Findings 3 + 7)
- llms.txt open standard: https://llmstxt.org/ (cited in §3.6 Finding 4 + §13.2; structural template for INDEX.md)
- ETH Zurich AGENTS.md research: https://www.infoq.com/news/2026/03/agents-context-file-value-review/ (cited in §3.6 Finding 5; counter-evidence for naive structural overviews)
- **CodeCompass Navigation Paradox**: https://arxiv.org/html/2602.20048v1 (cited in §13.3; primary basis for cross-reference preservation MANDATORY constraint; 99.4% coverage with explicit links vs 78.2% grep-only)
- **Formal Architecture Descriptors / intent.lisp**: https://arxiv.org/html/2604.13108 (cited in §13.5 P4 meta-research; LLM-generated structured descriptors achieve 100% task accuracy + 33-44% reduction in exploration steps)
- Kubernetes content organization: https://kubernetes.io/docs/contribute/style/content-organization/ (cited in §13.1 Finding A-1; semantic-functional naming convention)
- Linux kernel docs: https://docs.kernel.org/ (cited in §13.1; subsystem-per-directory semantic naming pattern)

---

## §13. Option A deep-dive — naming + TOC + discoverability (added 2026-05-15)

Per user 4th-directive request: think more rigorously about Option A (split-by-section) — what to NAME each split file + how agents DISCOVER the right file + meta-research questions. Backed by `docs/migration/_research/agent-discoverability-2026-05-15.md` (17 primary sources; 4 finding sections + 8 meta-research candidates).

**Important context for §13**: this section adds ~200 lines to a plan already at 525 lines. Self-referential note: the plan itself is approaching the 500-line SKILL.md cap discussed in §3.6 Finding 7. If §13 grows further, OR if the plan crosses ~700 lines total, it should split per its own §13.1 naming convention into `MARKDOWN_REFACTOR_PLAN.md` (sections §1-§9) + `MARKDOWN_REFACTOR_PLAN_appendix.md` (sections §10b + §13 + §13). For now (~725 lines projected), keep as one file.

### §13.1 Naming convention proposal for split files

Research-validated pattern: **`NN_SCOPE_{qualifier}.md`** — semantic-functional naming where `NN` is sort prefix, `SCOPE` is the original filename base, `qualifier` is the semantic scope boundary.

**Industry evidence (research §A)**:
- Kubernetes uses `topic-subtopic.md` (semantic, hyphen-separated; no Part-N)
- Linux kernel uses subsystem-per-directory + `index.rst` per directory (semantic at every level)
- Lander Analytics agent-knowledge-base recommends numbered prefixes (`00-start-here.md` / `10-`, `20-`, `30-`)
- **Universal absence**: NO source uses `part-N` or `section-X-Y` naming for split planning docs; structural names are an anti-pattern (Navigation Paradox arxiv 2602.20048: filenames participate in grep — structural names are search-invisible)
- Harvard data management: leading-zero sort keys (`001`, `002`) for sort stability at scale

**Concrete proposals for UDM split files** (binding once Option A executes):

| Original file | Proposed splits | Trigger | Rationale |
|---|---|---|---|
| `_validation_log.md` (7,129 lines) | `_validation_log.md` (live; last 30 days) + `_validation_log_archive_2026-04.md` (pre-2026-04-12 entries) | Existing archive policy at L14-23 | Time-based correct for append-only logs; semantic split would break append-only invariant |
| `03_DECISIONS.md` (3,219 lines) | `03_DECISIONS_phase0.md` (D1-D50; foundational architecture) + `03_DECISIONS_phase1.md` (D51-D95; pipeline + validation discipline) + `03_DECISIONS_phase2_onwards.md` (D96+; security + naming + deployment) | If exceeds 5,000 lines OR Phase 1+2 metrics insufficient | D-range in name aids grep; phase qualifier aids routing intent |
| `phase1/01_database_schema.md` (2,167 lines) | KEEP as single file; navigate via H2 headers within | Below 3,000-line threshold + clear H2 structure exists | Per Finding B-2: well-structured 2,000-line file may be MORE navigable than 4 × 500-line files with flat content |
| `phase1/06_deployment.md` (1,846 lines) | KEEP as single file; navigate via H2 headers | Below 3,000-line threshold | Same rationale as above |
| `phase1/03_core_modules.md` (1,724 lines) | KEEP as single file; navigate via H2 headers | Below 3,000-line threshold | Same rationale |
| `phase1/04_tools.md` (1,628 lines) | KEEP as single file | Below 3,000-line threshold | Same rationale |
| `05_RUNBOOKS.md` (1,545 lines) | KEEP as single file | Below 3,000-line threshold; RB-numbers are grep-precise | Same rationale |
| `BACKLOG.md` (547 lines) | KEEP as single file | Already small; B-numbers are grep-precise | Splitting by B-number range creates orphan-reference risk per Navigation Paradox |
| `CLAUDE.md` (715 lines) | TRIM (per gap §10b.1 G-MR2 + research §3.6 Finding 1) — target <300 lines; move "sometimes-relevant" content to skills | Anthropic explicit guidance: "bloated CLAUDE.md files cause Claude to ignore your actual instructions" | Highest-leverage single-file change since CLAUDE.md loads at every agent startup |

**Anti-patterns (REJECTED based on research §A-3 + §A-4)**:
- ❌ `03_DECISIONS_part_1.md` / `03_DECISIONS_part_A.md` / `03_DECISIONS_section_4_2.md` — communicates sequence/position, NOT scope; grep-invisible
- ❌ `03_DECISIONS_2026-05.md` — date-based naming for reference material (date becomes stale); date-based correct only for changelogs and append-only logs
- ❌ `D1-D50.md` (no scope prefix) — drops the original-file-base identifier; grep for "DECISIONS" loses the file
- ❌ Sub-sub-directories (`docs/migration/decisions/phase0/D1-D50.md`) — adds depth without scope clarity; per gap §10b.2 EC-MR4 may break Pattern F regex patterns

### §13.2 TOC / INDEX.md structure proposal (research-grounded)

**Two-tier structure** per research §B (validated by llms.txt + "compass not encyclopedia" + Lander Analytics + Zylos):

**Tier 1 — Root `INDEX.md` (routing manifest; Stage 0 of CCL)**:
- Format: llms.txt-compatible (H1 project name + blockquote summary + sections with linked files + intent descriptions)
- NOT a comprehensive TOC of all sub-sections (research §B-1 anti-pattern: nested TOC-of-TOCs)
- Each entry follows: `[filename](path)` — "If your task involves X, read this. If your task involves Y, skip and read Z."
- Stays under 500 lines per research §3.6 Finding 7 (SKILL.md cap)
- Carries `last_regenerated_at: YYYY-MM-DD HH:MM` line at top (per gap §10b.2 EC-MR2: agents check freshness)

**Tier 2 — Per-file scope statement (within each file at the top)**:
- One paragraph immediately after H1 stating: scope + "see also" pointers to siblings + quick-find guidance
- H2 headers act as within-file navigation primitives (research §B-2: agents navigate via H2 after arriving at file)
- D-number / B-number / R-number headings use the pattern `## D15 — {title}` (D-number as FIRST WORD; per §13.4 slug-stability policy)

**Concrete INDEX.md skeleton** (illustrative; actual content per Phase 1.3):

```markdown
# UDM Documentation Index

> Intent-based routing for agents performing Canonical Context Load (CCL) Stage 0.
> Read the entry that matches your task; skip others. Routing-by-intent only — NOT a structural map.

**Last regenerated**: 2026-05-XX HH:MM

## Stage 0 reads (every CCL invocation)

- [CURRENT_STATE.md](CURRENT_STATE.md) — "Where is the project right now?" Read for in-flight context, recent events, run-state.
- [HANDOFF.md](HANDOFF.md) — "How do I pick up this project mid-flight?" Read for fresh-agent onboarding context.
- [GLOSSARY.md](GLOSSARY.md) — "What does this code/acronym mean?" Read on-demand for unfamiliar identifiers.

## Decisions (D-numbers; canonical home for D-N rationale)

- [03_DECISIONS_phase0.md](03_DECISIONS_phase0.md) — D1-D50 foundational architecture (greenfield, SCD2, tokenization, parity). Read if your task references D1-D50 OR involves architectural rationale.
- [03_DECISIONS_phase1.md](03_DECISIONS_phase1.md) — D51-D95 pipeline design + validation discipline + round close-out. Read if your task references D51-D95.
- [03_DECISIONS_phase2_onwards.md](03_DECISIONS_phase2_onwards.md) — D96+ security model + SQL naming + deployment. Read if your task references D96+.

## Edge cases (M/S/I/N/P/G/D/F/V series)

- [04_EDGE_CASES.md](04_EDGE_CASES.md) — All edge case series. Read if your task validates against documented edge cases per D55 Gate 3.

## Validation trail

- [_validation_log.md](_validation_log.md) — LIVE entries (last 30 days). Most agents read this for recent validation history.
- [_validation_log_archive_2026-04.md](_validation_log_archive_2026-04.md) — ARCHIVE (pre-2026-04-12). Read only if your task involves a historical validation event.

## [... continue per file family ...]
```

**Per-file scope statement skeleton** (illustrative; binding for split files):

```markdown
# Decisions — Phase 0 (D1-D50)

**Scope**: D1 through D50, covering foundational architecture (greenfield deployment, SCD2 strategy,
tokenization vault, parity baseline, Automic gate coordination). For D51-D95, see
[03_DECISIONS_phase1.md](03_DECISIONS_phase1.md). For D96+, see
[03_DECISIONS_phase2_onwards.md](03_DECISIONS_phase2_onwards.md).

**Quick-find**: All D-numbers in this file have H2-level headings (`## D15 — {title}` pattern).
Use grep `^## D15` to locate a specific decision.

**Cross-references**: D-numbers cited from other files use the pattern
`[D15](03_DECISIONS_phase0.md#d15)`. If you arrive here from a citation, the fragment anchor
points directly to the section.
```

### §13.3 Cross-reference preservation MANDATORY constraint (Navigation Paradox)

**This is a binding constraint for ANY Option A split execution** per research §C-2 (CodeCompass arxiv 2602.20048; 99.4% coverage with explicit cross-references vs 78.2% grep-only).

**Rule**: Every inbound reference to content that moves to a new file MUST be updated to a relative Markdown link pointing to the new file location. "See D15" as plain text becomes a dead reference after splitting; it MUST become `[D15](03_DECISIONS_phase1.md#d15)` (or whichever target file + fragment anchor).

**Implementation requirements**:
1. **Pre-split inventory**: Before splitting any file, run `grep -rn "D15\|D17\|D55"` (and similar D-number / B-number / R-number / RB-N / SP-N / Pattern code patterns) across `docs/migration/` to enumerate all inbound references. Capture the inventory in `_research/cross-ref-inventory-pre-split-<date>.md`.
2. **Per-split rewrite**: For each file being split, rewrite all outbound references to point to the new target file. Use a script (`tools/rewrite_cross_refs.py`) to handle this mechanically; no manual rewrites.
3. **Post-split verification**: Re-run the inventory; assert all references resolve to a file that exists. Pattern F audit script extension (Phase 2.4) MUST verify this.
4. **Slug-stability check**: Verify all fragment anchors (`#d15`) resolve to a heading in the target file with that exact slug.

**Failure mode this prevents**: Agent reads a runbook citing "D15"; tries to follow the reference; D15 has moved to `03_DECISIONS_phase1.md`; no link exists; agent grep for "D15" works (D-number is grep-precise); agent grep for the D-number title may fail if the title was rewritten. The Navigation Paradox: grep alone is 78.2% effective; explicit links push that to 99.4%.

**Cost of this constraint**: Mechanical (script-driven); estimated ~30 minutes for the script + ~10 minutes per file split. Negligible vs the cost of breaking Pattern F audit + cross-doc cascade per D93.

### §13.4 Heading-slug stability policy

**Rule (revised 2026-05-15 per Q-22 empirical findings)**: Headings that participate in cross-references MUST use the convention `## {ID}: {title}` (COLON-FORM) where `{ID}` is the first word (D-number, B-number, R-number, RB-N, SP-N, etc.). **Em-dash and en-dash variants are PROHIBITED for new headings** — empirically verified to break GitHub's slug algorithm (see §15.4 for test results).

**Why colon-form**: Markdown auto-generates fragment anchors from headings (lowercase + non-alphanumeric handling). Colon strips cleanly to a hyphen-separator; em-dash + en-dash + ASCII hyphen are preserved literal in the slug (per Unicode `\p{Pd}` dash-punctuation handling), producing unusable anchors like `d15-—-idempotency-ledger`. See full empirical detail in **§15.4 below + `_research/em-dash-slug-test-2026-05-15.md`**.

**Best practice for stable slugs (POST-REVISION)**:
- ✅ `## D15: Idempotency Ledger` → slug `d15-idempotency-ledger`; cite as `#d15-idempotency-ledger`
- ✅ `## B-271: FP-precision percentile fix` → slug `b-271-fp-precision-percentile-fix`; cite as `#b-271-fp-precision-percentile-fix`
- ❌ `## D15 — Idempotency Ledger` (em-dash) — slug becomes `d15-—-idempotency-ledger` (em-dash embedded literal); **PROHIBITED for new headings**
- ❌ `## D15 – Idempotency Ledger` (en-dash) — same problem; **PROHIBITED**
- ❌ `## D15 - Idempotency Ledger` (ASCII hyphen with surrounding spaces) — slug becomes `d15---idempotency-ledger` (triple hyphen); **PROHIBITED**
- ❌ `## Idempotency Ledger (D15)` — D15 not first; slug-cite requires platform-specific prefix matching
- ❌ `## D15: Idempotency Ledger (Locked 2026-05-09)` — date in heading; rename on supersession breaks inbound links

**Forward-only migration per D92**: Existing em-dash headings stay (their current slugs continue resolving — no inbound-link breakage). NEW headings authored after this revision (2026-05-15) MUST use colon-form. Bulk normalization deferred to next round close-out OR Phase 3 split (whichever fires first).

**Self-referential exemption acknowledged**: This plan document itself uses em-dash in many of its own historical headings (§3.6, §10b, §13.X, §15.X, §16.X). Per forward-only D92 + Pitfall #9.m self-referential acknowledgment, those existing headings stay; future plan revisions or splits will normalize incrementally. The plan is not yet self-compliant with its own §13.4 colon-form rule — this is acknowledged drift, not contradiction.

**⚠️ EMPIRICAL TEST COMPLETE (Q-22 RESOLVED 2026-05-15)** — see `docs/migration/_research/em-dash-slug-test-2026-05-15.md` for full findings + `tools/test_github_slug.py` for the deterministic stdlib-only Python implementation of GitHub's slug algorithm.

**🔴 CRITICAL FINDING — §13.4 ASSUMPTION WAS WRONG**: GitHub's slug algorithm uses Unicode dash punctuation `\p{Pd}` which **INCLUDES em-dash (U+2014), en-dash (U+2013), AND ASCII hyphen (U+002D)** — they are KEPT in the slug as literal characters, NOT replaced by hyphen-separators.

**Test results (5 heading variants tested)**:

| Heading | Generated slug | §13.4 prior assumption holds? |
|---|---|---|
| `## D15 — Idempotency Ledger` (em-dash) | `d15-—-idempotency-ledger` (em-dash literally embedded) | 🔴 NO |
| `## D15 – Idempotency Ledger` (en-dash) | `d15-–-idempotency-ledger` (en-dash literally embedded) | 🔴 NO |
| `## D15 - Idempotency Ledger` (ASCII hyphen) | `d15---idempotency-ledger` (triple hyphen) | 🔴 NO |
| `## D15: Idempotency Ledger` (colon) | `d15-idempotency-ledger` | ✅ YES |
| `## D15. Idempotency Ledger` (period) | `d15-idempotency-ledger` | ✅ YES |

**🟢 BINDING RECOMMENDATION (revised §13.4 canonical heading style)**: Use **colon-form** for all D-number / B-number / R-number / RB-N / SP-N headings going forward:

```markdown
## D15: Idempotency Ledger
## B-271: FP-precision percentile fix
## R22: CLI exit-code drift
## RB-7: DR rehearsal
## SP-3: PipelineExecutionGate_AcquireProd
```

This produces the assumed `d15-idempotency-ledger` slug, allowing `#d15-idempotency-ledger` for full slug-cite OR partial-prefix-match for `#d15` on platforms that support prefix-anchor matching.

**Why colon over period**: Colon is the conventional ID-prefix separator (RFC, ISO, Wikipedia disambiguation); period implies sentence-end and reads awkwardly in technical headings.

**Migration**: Forward-only per D92. Existing em-dash headings stay (their current slugs continue resolving — no inbound-link breakage). NEW headings must use colon-form. Bulk normalization deferred to next round close-out OR Phase 3 split (whichever fires first).

**Audit before split**: Per meta-research Priority 3 (research §E), audit all headings in `docs/migration/` for first-word-stable patterns BEFORE executing splits. Headings that don't match the convention should be normalized first.

### §13.5 Meta-research candidates (8 topics; prioritized per research §E)

Per user direction "What other research should be performed to help with discoverability?" — research surfaced 8 candidate topics. Each annotated with rationale, effort, payoff, recommended timing. Open as B-Ns once pipeline-lead approves Option A execution.

| Priority | Topic | Effort | Payoff | Timing |
|---|---|---|---|---|
| **P1** | Navigation Paradox applied to UDM cross-reference topology — map the D→B→R→RB→SP graph; test split-vs-unsplit agent navigation; quantify hidden-dependency risk | Medium | **HIGH** — changes split constraints | BEFORE Option A splits begin |
| **P2** | Token cost measurement of current CCL — count actual tokens in 7-11 mandatory CCL reads; ground the optimization target empirically | Low (15 min) | **HIGH** — informs Phase 1 priority sequencing | IMMEDIATELY (no infrastructure needed) |
| **P3** | Heading-slug stability audit — grep for heading patterns across `docs/migration/`; identify mutable headings; normalize before split | Low | Medium — informs cross-ref strategy | BEFORE splits |
| **P4** | Formal Architecture Descriptors (intent.lisp) for UDM corpus — generate auto-descriptor; test against sample queries; compare to hand-authored INDEX.md | Medium | **HIGH** — could replace Phase 1 INDEX authoring | Phase 1 design decision |
| **P5** | Multi-agent CCL cost distribution — test Pattern E cycle with vs without `udm-context-loader` subagent; measure quality loss from summary-vs-direct read | Medium | **HIGH** — quantifies subagent pattern value | Phase 2 |
| **P6** | Snowflake docs conventions for AI agents (Phase 5) — targeted Snowflake docs structure search; relevance for Cortex / Snowpark / COPY INTO | Low | Medium — Phase 5 only | At Phase 5 planning |
| **P7** | Auto-compaction interaction with CCL reads — test Anthropic's auto-compaction behavior on CCL Read calls; does compaction summarize and lose precision? | Medium | Medium — affects Phase 3 split necessity | Phase 1 design decision |
| **P8** | Diátaxis-quadrant labeling for CCL routing — label files by quadrant; test routing-skill effectiveness | Low | Low — incremental at best | Phase 4 (after Phases 1-3 validated) |

**Recommended execution order**:
- **NOW (today, no infrastructure)**: P2 (token cost measurement)
- **BEFORE Option A approval**: P1 + P3 + P4 (these inform the split design)
- **Phase 1 design**: incorporate P4 + P7 findings
- **Phase 2**: P5
- **Phase 4+**: P6 + P8

### §13.6 Plan calculus changes from §13 deep-dive (consolidated)

Three changes propagate back to existing plan sections:

**1. To §3.1 Option A**: revised verdict — Option A IS executable when needed (per Phase 3) but requires the §13.3 cross-reference preservation constraint as a HARD precondition. Without explicit link preservation, splitting becomes a Navigation Paradox failure mode (research §C-2). Update §3.1 verdict text: "Avoid as Phase 1. Reserve for Phase 3 (targeted splits where Phase 1+2 prove insufficient) — AND requires §13.3 cross-reference preservation as a binding precondition."

**2. To §6 Quality gates**: add Gate 1 sub-check — "INDEX.md MUST be written as routing-by-intent ('if task = X, read Y') NOT as structural-by-description ('file Y contains sections A/B/C'). Validation: Pattern E reviewer agent inspects INDEX.md against the routing-vs-structural distinction; flags structural-style entries as 🟡 for revision."

**3. To §10 Open questions**: add 5 new questions Q-13 through Q-17 derived from meta-research candidates:
- **Q-13**: Approve P2 (token cost measurement) immediately, BEFORE Phase 1 work begins?
- **Q-14**: Approve P1 (Navigation Paradox UDM topology mapping) BEFORE any Option A split?
- **Q-15**: Approve P4 (intent.lisp / Formal Architecture Descriptors investigation) at Phase 1 design?
- **Q-16**: Approve P7 (auto-compaction interaction with CCL) at Phase 1 design?
- **Q-17**: Approve §13.4 heading-slug stability policy as a binding rule for ALL future heading authoring (not just splits)?

---

## §15. Cross-domain research synthesis (added 2026-05-15)

Per user 5th-directive request: spawn 3 parallel research agents on (Q1) LLM training data storage techniques + (Q2) dedicated cross-reference maintenance agent + (Q3) web crawler / search engine techniques. All 3 artifacts landed in `docs/migration/_research/` 2026-05-15 (LLM training-data-storage / cross-reference-maintenance-agent / web-crawler-techniques). Combined ~1,800 lines + ~50 primary sources across 3 angles.

**Self-referential split-trigger note**: Plan now exceeds 700 lines per the §13 preamble's own split trigger. Post-this-edit: ~800 lines projected. **Recommended action at next refactor cycle**: split the plan per its own §13.1 naming convention — `MARKDOWN_REFACTOR_PLAN.md` (sections §1-§9 + §12 sign-off) + `MARKDOWN_REFACTOR_PLAN_appendix.md` (sections §10b + §13 + §15). Adding §15 anyway because (a) the synthesis content is too important to bury in `_research/`, (b) splitting the plan mid-revision would itself violate §13.3 cross-reference preservation discipline (would break inbound `§13.X` cites). Pitfall #9.m (discipline-not-applied-to-tracker) acknowledged in real-time.

### §15.1 Independent triangulation across 3 research angles

**The most important meta-finding**: All 3 research artifacts (LLM training, cross-ref maintenance, web crawlers) **independently converge** on the same structural intervention: a sidecar manifest / index file. This is significant because each angle reasons from a different domain:

- **LLM training (Q1)**: MosaicML's `index.json` lets infrastructure locate training shards without reading shard content (Pattern C: sidecar index files transfer)
- **Cross-ref maintenance (Q2)**: lychee + verify_cascade.py operate against an INDEX-as-source-of-truth for what files exist + what cross-refs are valid
- **Web crawlers (Q3)**: sitemap.xml is the URL manifest — high-fidelity transfer to a `CORPUS_INDEX.md`

When 3 independent research domains converge on the same answer, the convergence itself is signal. The plan's Phase 1 INDEX.md proposal is now triangulated by 3 angles + the original llms.txt finding from research #1 — 4 cumulative sources.

### §15.2 New patterns from cross-domain synthesis

**Pattern (a) — Quality tiers in the CCL** (per Q1 LLM-training Pattern A):
Training labs explicitly weight high-quality curated data more than raw web data. The CCL's Stage 1 (mandatory) / Stage 2 (risk + backlog) / Stage 3 (task-specific) hierarchy IS this pattern, but the plan never named it as such. **Adoption**: explicitly label CCL stages as quality tiers in D62 doctrine — "Stage 1 = canon-tier (always read; never drift); Stage 2 = reference-tier (read on-demand); Stage 3 = ad-hoc-tier". This frames the CCL doctrine consistently with established LLM-training discipline. Zero infrastructure cost.

**Pattern (b) — Lead-with-answer writing discipline** (per Q3 GEO research Finding):
Empirically validated: 44.2% of all LLM citations come from the FIRST 30% of page content. Structured lists score 30-40% higher than prose walls. **Adoption**: mandate "lead-with-answer" structure for every section in `docs/migration/` going forward — 1-3 sentence direct answer / status statement at the top of every section before elaboration. Zero infrastructure cost; pure writing discipline. Apply to NEW edits + retroactively at next round close-out cascade. This is the single highest-ROI writing-discipline change surfaced across all 5 research artifacts.

**Pattern (c) — Single-source-of-truth deduplication** (per Q1 LLM-training Pattern B):
Training labs deduplicate near-identical documents because duplication distorts the model. The doc-corpus analog: any fact that must update when reality changes should exist in EXACTLY ONE authoritative location, with cross-reference links everywhere else. **Current drift risk**: HANDOFF.md L7 narrative + CURRENT_STATE.md L7 narrative + CODE_BUILD_STATUS.md L12 narrative all carry near-identical event narratives. The plan's Phase 1 should add: "audit for near-duplicate paragraphs across canonical trackers; consolidate to single source + cross-reference."

**Pattern (d) — 4-component cross-ref maintenance design** (per Q2 cross-ref research):
NOT a single autonomous agent. Industry pattern (Drasi/GitHub Copilot case study + WarpFix): AI documentation agents are detection-only monitors that file issues for human fix. **Adoption**: replace plan's vague "Phase 2.4 Pattern F audit script extension" with concrete 4-component design:
  1. **`lychee-action` scheduled CI** (weekly cron): catches file-existence + in-file fragment failures; creates GitHub Issue; ZERO auto-fix
  2. **`verify_cascade.py` Trigger L extension** (Pattern F Layer 1): heading-slug drift + stale line-number detection
  3. **`tools/rewrite_cross_refs.py`** (one-shot at split-time only per §13.3): proposes diff; HUMAN approves before `git apply`
  4. **`udm-cross-ref-checker` SKILL** (on-demand): semantic-ambiguity cases; outputs to `_research/` only; never writes primary docs
  5. **`udm-context-loader` brief schema `verbatim_excerpts` field** (NEW per F5.1 mitigation; 🔴 CRITICAL): every brief produced by `udm-context-loader` MUST carry a `verbatim_excerpts` field passing through (NOT summarizing) the following content categories: (a) every Do-NOT rule — any line starting with `Do NOT` or `❌` in `CLAUDE.md` + spec docs touched by the brief; (b) every Pitfall #9.X sub-class header — exact header text; (c) every binding `**D-N**: ... 🟢 Locked YYYY-MM-DD` status line; (d) every `R-N` risk header row (header only, not body). Distillation is permitted for everything else; these 4 categories are non-distillable. Brief consumers that touch production code (CDC/SCD2 engine, schema migrations, SP definitions, BCP CSV writers) MUST direct-Read the canonical source for any verbatim_excerpt before proposing a change — the brief carries the excerpt as a tripwire, not as a substitute for the full passage.

**Pattern (e) — Slug-stability discipline as 301-redirect analog** (per Q3 web-crawler Finding):
Web URL slugs never change without a 301 redirect; same principle applies to file paths. **When Phase 3 splits execute**, the master INDEX.md must record old-name → new-name mapping (the doc-corpus equivalent of a 301 redirect). Already partially captured in §13.3; this synthesis names the discipline + grounds it in web-SEO precedent.

### §15.3 What does NOT transfer (negative findings worth recording)

- **llms.txt as crawler-discoverable convention**: per Q3 research, no major AI provider (OpenAI / Google / Anthropic / Meta / Mistral) reads it in production as of 2026. **The plan uses llms.txt FORMAT (H1 + blockquote + sections + descriptions) as a STRUCTURAL TEMPLATE for INDEX.md, NOT as a crawler-discovery file.** This distinction is important and should be clarified in §13.2: we adopt the llms.txt FORMAT for human + agent consumption inside the repo; we do NOT depend on web crawlers picking it up.
- **PageRank / link-graph weighting**: per Q3 web-crawler research, doesn't transfer at 25-file scale. The CCL's explicit 4-seed-reads (NORTH_STAR / HANDOFF / CURRENT_STATE / CHECKS_AND_BALANCES) already implement the intent without machinery. No infrastructure investment justified.
- **Hybrid retrieval (BM25 + vector)**: per Q3 + prior research, requires RAG infrastructure that conflicts with §2.2 non-goal #4 (no non-stdlib dependencies). Agents already use grep-first; the inverted-index IS the grep index implicitly.
- **Fully autonomous cross-ref maintenance agent**: per Q2 research bottom line — industry AI doc agents are detection-only monitors; humans fix. Don't build a continuously-running autonomous fixer. The 4-component design (Pattern d above) is the right shape.
- **LLM training shard-size conventions** (64 MB - 5 GB): per Q1 research, irrelevant at our KB-scale corpus. Markdown file-size targets should be agent-traversal-driven (per §13.1 1,000-line trigger), not training-shard-derived.

### §15.4 Empirical-validation results — BOTH P0 TESTS COMPLETE 2026-05-15

**Q-22 P0 em-dash test → ✅ COMPLETE** — see updated §13.4 above + research artifact `_research/em-dash-slug-test-2026-05-15.md`. **Outcome**: §13.4 prior assumption was WRONG; em-dash, en-dash, AND ASCII hyphen all break the assumed `d15-` slug prefix. **Binding revision**: heading style mandate is now **colon-form** `## D15: Title` (validated against GitHub's slug algorithm via stdlib-only Python implementation in `tools/test_github_slug.py`).

**Q-13 P2 token cost measurement → ✅ COMPLETE** — see `tools/measure_ccl_overhead.py` + research artifact `_research/ccl-baseline-2026-05-15.md` + machine baseline `_research/ccl-baseline-2026-05-15.json`. **Outcome**: empirical baseline reveals the situation is WORSE than estimated:

| CCL stage | File count | Token count | % of 200K context window |
|---|---|---|---|
| **Stage 1 (canon-tier)** | 4 (NORTH_STAR, HANDOFF, CURRENT_STATE, CHECKS_AND_BALANCES) | 69,572 tokens | ~35% |
| **Stage 2 (reference-tier)** | 3 (RISKS, BACKLOG, _validation_log) | 292,582 tokens | ~146% |
| **Stage 1 + Stage 2 combined** | 7 | **362,154 tokens** | **~181%** of 200K |
| Stage 3 (ad-hoc-tier; everything else) | 54 | 559,615 tokens | ~280% (but agents don't read all of S3 per invocation) |
| Total `docs/migration/` corpus | 61 | 921,769 tokens | ~461% |

**Key finding**: `_validation_log.md` alone = **231K tokens / 7,519 lines = 115% of context window** for a SINGLE FILE in Stage 2. The plan's prior estimate of "12K-16K lines per CCL invocation" matched line count (9,212 actual) but understated token cost by ~1.8×.

**Optimization target derived from baseline**: Trimming `_validation_log.md` by 73% via existing archive policy (7,519 → 2,000 lines) recovers ~62% of CCL Stage 1+2 token cost. **This single action is the highest-leverage Phase 1 task** — promoted from "Phase 1.A" to **Phase 1 IMMEDIATE PRIORITY (Phase 1.0)**.

**Implication for plan**: §5.1 Phase 1 task ordering revised below. The archive cascade is no longer just "first task" — it is the SINGLE-MOST-CONSEQUENTIAL change available. CLAUDE.md trim (Phase 1.6 / Q-12) remains second-highest leverage but ~6× smaller impact than `_validation_log.md` archive.

**Both P0 tests' deliverables landed this commit**:
- `tools/test_github_slug.py` (89 lines; stdlib-only; deterministic)
- `tools/measure_ccl_overhead.py` (218 lines; stdlib + optional tiktoken; ran in <2 sec)
- `tests/tier0/test_measure_ccl_overhead.py` (135 lines; 9 tests; pytest baseline 2311 → 2320 / 0 regression)
- `_research/em-dash-slug-test-2026-05-15.md` (149 lines; full test report + 5 B-N candidates)
- `_research/ccl-baseline-2026-05-15.md` + `.json` (canonical baseline doc + machine-readable for diffing)

**Q-22 + Q-13 status flipped 🟡 → ✅ RESOLVED**. §10 updated below.

### §15.5 New Q-numbers added to §10 open questions

- **Q-18 (NEW per §15.2 Pattern a)**: Approve labeling CCL stages as quality tiers in D62 doctrine ("Stage 1 = canon-tier; Stage 2 = reference-tier; Stage 3 = ad-hoc-tier")? Frames CCL discipline consistently with established LLM-training data-curation patterns.
- **Q-19 (NEW per §15.2 Pattern b)**: Mandate lead-with-answer writing discipline for all NEW section edits in `docs/migration/`? Highest-ROI writing change per Q3 empirical evidence (44.2% AI citations from first 30% of content).
- **Q-20 (NEW per §15.2 Pattern c)**: Approve near-duplicate-paragraph audit across HANDOFF.md / CURRENT_STATE.md / CODE_BUILD_STATUS.md L7-L12 narratives? Single-source-of-truth deduplication per Q1 LLM-training Pattern B.
- **Q-21 (NEW per §15.2 Pattern d)**: Approve 4-component cross-ref maintenance design (lychee CI + verify_cascade.py extension + rewrite_cross_refs.py + udm-cross-ref-checker SKILL)? Replaces plan's vague Phase 2.4 Pattern F audit script extension with concrete architecture.
- **Q-22 (NEW per §15.4)**: Authorize P0 em-dash heading-slug test BEFORE any other Option A approval? 15 minutes; informs whether §13.4 policy needs revision.

### §15.6 Cross-domain synthesis impact summary

| Plan section | Change from §15 synthesis |
|---|---|
| §3.6 (research validation) | Augmented — 3 NEW research artifacts confirmed prior research direction; triangulated via independent angles |
| §13.2 (TOC structure) | Clarified — llms.txt is FORMAT template only; NOT relying on crawler discovery |
| §13.4 (heading-slug stability) | CRITICAL caveat added — em-dash empirical test BEFORE any split |
| §13.5 (meta-research) | Added P0 (em-dash test); P2 unchanged but now triangulated by Q1 research |
| §10 (open questions) | +5 (Q-18 through Q-22) |
| §11 (cross-references) | +3 research artifacts cited |
| §3.2 + §5.1 (Phase 2 cross-ref tooling) | Refined — 4-component design replaces single Pattern F extension item |

---

## §16. Long-term maintenance + governance (added 2026-05-15)

Per user 6th-directive request: (Q1) how do we keep track of research + create plan with strict guidelines for markdown hygiene? (Q2) if creating a new repo, how do we build markdown files properly from the get-go? (Q3) how do we ensure research is updated every few months for industry-standard tracking? (Q4) finalize plan + plan long-term maintenance + use multi-agent team. This section addresses Q1, Q2, Q3 + the long-term maintenance dimension of Q4.

### §16.1 Research-tracking + markdown-hygiene enforcement (Q1)

**Problem**: This session generated 6 udm-researcher artifacts + 1 plan doc + 5 plan revisions. Without governance, the research artifacts will drift, get re-discovered, or get cited stale.

**Proposed governance (3-tier discipline)**:

**Tier 1 — Per-artifact research register** (~50 lines; new doc `docs/migration/_research/_INDEX.md`):
- One row per research artifact: filename + date + scope + key findings (1 line) + which plan sections it backs + supersession status
- Append-only audit trail (research artifacts don't get deleted; superseded ones get a closure line)
- Updated at every new research artifact authoring (per `udm-researcher` skill update)
- Companion: each research artifact carries `**Supersedes**:` and `**Superseded-by**:` frontmatter when applicable

**Tier 2 — Markdown hygiene linting** (CI gate per §15.2 Pattern D 4-component design):
- `lychee` weekly cron CI checks file existence + in-file fragment anchors
- `verify_cascade.py` Trigger L extension (heading-slug drift + stale line numbers)
- New: `tools/check_markdown_hygiene.py` runs at pre-commit + scheduled — checks:
  - All H2 headings carry colon-form ID prefix per revised §13.4 (`## D15: Title` not `## D15 — Title`)
  - All file paths cited as `[](path/file.md#anchor)` format (no plain `see file.md`)
  - All D-number / B-number / R-number references use canonical fragment anchors
  - Lead-with-answer discipline: every H2/H3 section opens with 1-3 sentence direct answer (regex check)

**Tier 3 — Round close-out cascade addition** (per `udm-round-closeout` skill):
- New CCL Stage 2.5 step: skim `_research/_INDEX.md` for research candidates aging beyond 90 days; flag for refresh
- New gap-check trigger: any plan/spec edit that cites a research artifact >180 days old surfaces 🟡 stale-citation finding (forces fresh research OR explicit "still-valid" attestation)

**Hygiene rules to enforce as binding (D-N candidate per Q-23 below)**:

| Rule | Enforcement mechanism |
|---|---|
| All NEW H2 headings use colon-form ID prefix | pre-commit hook + Pattern F audit |
| All NEW cross-references use explicit `[](path#anchor)` Markdown links | pre-commit hook + lychee CI |
| All NEW sections lead-with-answer (1-3 sentence direct answer) | regex check (best-effort; advisory not blocking) |
| All NEW research artifacts register in `_research/_INDEX.md` | `udm-researcher` skill update |
| Files >2,000 lines auto-flagged for split candidate review at next round close-out | `tools/measure_ccl_overhead.py` --report-large flag |
| `_validation_log.md` triggers archive cascade at 2,000 lines OR quarterly (whichever first) | extended archive policy at L14-23. **REVISED 2026-05-15 from 5K → 2K lines per consistency-audit C-2 + alignment with §9 CCL metric (≤2,000 lines target) + alignment with NEW_REPO_STARTER_TEMPLATE.md threshold** |

### §16.2 New-repo starter pattern (Q2)

**Standalone artifact**: `docs/migration/NEW_REPO_STARTER_TEMPLATE.md` (authored same commit as this plan revision; ~300 lines). Greenfield template that any new repo can copy as the starting point for `docs/` organization.

**Key design principles applied from-the-start** (vs UDM's after-the-fact retrofit):
1. **Lean CLAUDE.md from day 1** — under 300 lines; "would removing this cause Claude to make mistakes?" filter applied at every line per Anthropic guidance
2. **Routing manifest INDEX.md from day 1** — in llms.txt format; routing-by-intent ("if task = X, read Y") not structural-by-description
3. **Colon-form heading discipline from day 1** — `## D1: Foundational decision` NOT em-dash variants (per §13.4 empirical findings)
4. **Cross-reference discipline from day 1** — `[D15](03_DECISIONS.md#d15-title)` from first commit; never plain text "see D15"
5. **Append-only logs follow archive cadence from day 1** — `_validation_log.md` carries archive policy in its header from creation; never lets it grow past 2K lines
6. **Quality tiers explicit in CCL doctrine from day 1** — D62-equivalent specifies Stage 1 = canon-tier (4 reads) / Stage 2 = reference-tier (3 reads) / Stage 3 = ad-hoc-tier
7. **`udm-find-canonical` skill scaffolded from day 1** — agents have native lookup mechanism from first invocation
8. **Token measurement script from day 1** — `tools/measure_ccl_overhead.py` (zero-cost copy from this repo); run quarterly to track CCL drift

**Recommended directory structure for new repo's `docs/`**:
```
docs/
├── INDEX.md                       # routing manifest (Stage 0 read)
├── CLAUDE.md or README.md         # entry-point compass (<300 lines)
├── 00_OVERVIEW.md                 # what is this project (lean)
├── 01_ARCHITECTURE.md             # high-level design
├── 02_DECISIONS.md                # D-numbers (split when >2K lines)
├── 03_RISKS.md                    # R-numbers
├── 04_BACKLOG.md                  # B-numbers
├── 05_RUNBOOKS.md                 # operational procedures
├── _validation_log.md             # append-only audit (archive at 2K lines)
├── _research/
│   ├── _INDEX.md                  # research artifact register
│   └── *.md                       # individual research artifacts
└── _archive/                      # archived sections (split-source preservation)
    └── _validation_log_*.md       # archived validation log entries
```

See `NEW_REPO_STARTER_TEMPLATE.md` for full template + skeleton files.

### §16.3 Quarterly research-refresh cadence (Q3)

**Problem**: Industry standards evolve fast — 5 of the 6 udm-researcher artifacts in this session cited 2025-2026 sources. Without refresh, the plan becomes stale within months.

**Proposed cadence — Tier 5-style audit drill** (mirrors `06_TESTING.md` Q1-Q10 quarterly drills):

**Q11 — Markdown hygiene + agent-discoverability research refresh (NEW; quarterly)**:
1. Read `docs/migration/_research/_INDEX.md`; identify artifacts >90 days old
2. For each aging artifact: re-run the canonical research questions via `udm-researcher` skill; compare findings to prior artifact
3. If findings unchanged → append "Re-validated YYYY-MM-DD; no calculus changes" line; reset 90-day clock
4. If findings changed → author replacement artifact; mark prior as `**Superseded-by**: <new-artifact>`; flag plan sections for revision
5. Run `tools/measure_ccl_overhead.py` to track CCL token-cost drift over time; trend chart in `_research/ccl-trend-YYYY-Q.md`
6. Run `tools/test_github_slug.py` to confirm GitHub's slug algorithm hasn't changed (low likelihood but worth pinning)
7. File quarterly report at `docs/migration/audit_reports/QYYYY_QN_markdown_hygiene.md` (mirrors existing Q1-Q10 quarterly cadence)

**Trigger conditions for OFF-CADENCE research refresh** (in addition to quarterly):
- New Anthropic Claude Code release with documented changes to skill / subagent / context-loading mechanics
- New industry-standard publication (e.g., another arxiv paper like CodeCompass / Formal Architecture Descriptors)
- New emerging-standard adoption signal (e.g., llms.txt finally getting production AI consumer; or a successor standard launching)
- User-direction explicit refresh request

**Cost model**: ~30-60 minutes per quarter for the refresh cycle. ~2 hours per off-cadence trigger.

### §16.4 Long-term maintenance roadmap

**Year-1 milestones** (assuming Phase 1 lands within next 30 days):
- **Day 0** (next 1-2 sessions): Pipeline-lead reviews + approves §12 sign-off; Phase 1.0 (`_validation_log.md` archive cascade) executes; CCL token cost drops from 362K → ~140K (62% reduction)
- **Day 30**: Phase 1 complete (INDEX.md + udm-find-canonical skill + D62 CCL Stage 0 update + CLAUDE.md trim); first quarterly Q11 refresh due Day 90
- **Day 90 (Q1 audit)**: First Q11 quarterly refresh — re-run measurement script + check for new industry findings
- **Day 180 (Q2 audit)**: Second Q11 — assess whether Phase 1+2 metrics met §9 success criteria; decide Phase 3 (file splits) or stop
- **Day 365 (Q4 audit)**: Annual full refresh — re-run all 6 research questions if Anthropic Claude Code has had major updates

**Long-term governance hierarchy**:
- **Plan owner**: pipeline lead (decides plan revisions; sign-off authority)
- **Research owner**: rotates per quarterly Q11 (the operator running the audit drill that quarter)
- **Hygiene enforcement owner**: CI / pre-commit hooks (automated; humans only intervene on FAIL)
- **Cross-doc cascade owner**: `udm-round-closeout` skill (existing; extended for §16.1 Tier 3)

### §16.5 Multi-agent team structure for ongoing markdown work (Q4 dimension)

**Established multi-agent patterns from this session validated for ongoing use**:

| Pattern | Agents involved | When to use |
|---|---|---|
| **Sequential research → synthesis** | 1 udm-researcher → parent | When question is well-scoped + needs single coherent artifact |
| **Parallel research (3-stream)** | 3 udm-researcher in parallel → parent synthesizes | When 3 independent angles can be researched simultaneously (3× wall-clock savings) |
| **Empirical test + research split** | 1 general-purpose (test) + 1 udm-researcher (theory) → parent | When some questions need empirical data + others need literature review |
| **Build cohort (parallel agents)** | N general-purpose agents (one per artifact) → parent | When multiple INDEPENDENT artifacts can be authored simultaneously (e.g., 3 Tier 3 test files; 3 Round 4 CLI tools) |
| **Wave 1 + Wave 2** | Wave 1 parallel agents → parent waits → Wave 2 parent authors using Wave 1 results | When Wave 2 work depends on Wave 1 outputs (this commit's pattern) |

**Anti-patterns to avoid** (learned from this session):
- ❌ Spawning research agents on questions where empirical test is faster (the em-dash test should have been done as Wave 1, not deferred to a research artifact)
- ❌ Running >3 parallel research agents (context-rot in synthesis; diminishing returns observed at this session's 5-artifact mark)
- ❌ Research as a substitute for build (after 2+ artifacts validating direction, build the prototype + measure it)
- ❌ Summarizing Do-NOT rules / Pitfall #9.X headers / binding D-N status lines / R-N risk headers in subagent briefs (per F5.1 mitigation; 🔴 CRITICAL) — `udm-context-loader` brief schema's `verbatim_excerpts` field is mandatory for these 4 content categories. Distilling them risks destruction-class production changes when downstream agents act on incomplete context. Distillation is permitted for everything else; these 4 categories are pass-through-verbatim only.

### §16.6 New open questions Q-23 through Q-26 added to §10

- **Q-23 (NEW per §16.1)**: Approve the 6-rule markdown hygiene enforcement table as binding (D-N candidate)? Includes colon-form headings + explicit cross-ref links + lead-with-answer + `_research/_INDEX.md` registration + 2K-line file flag + 2K-line `_validation_log.md` archive trigger (revised from 5K per consistency-audit C-2; aligns with §9 metric + new-repo template).
- **Q-24 (NEW per §16.2)**: Approve `NEW_REPO_STARTER_TEMPLATE.md` as canonical greenfield reference? Pipeline-lead can adopt as binding template for any new internal repos.
- **Q-25 (NEW per §16.3)**: Approve Q11 quarterly markdown hygiene + agent-discoverability research refresh cadence (mirrors Tier 5 Q1-Q10 quarterly drills)?
- **Q-26 (NEW per §16.4)**: Approve year-1 milestones (Day 0 / 30 / 90 / 180 / 365) as roadmap commitment, OR redirect timeline?

### §16.7 Cross-domain synthesis impact summary (cumulative)

This is the 4th plan revision; cumulative governance discipline now spans:

| Layer | What's enforced | How |
|---|---|---|
| Per-cycle | colon-form headings + explicit cross-refs + lead-with-answer | pre-commit hook + lychee CI |
| Per-artifact | `_research/_INDEX.md` registration + supersession metadata | `udm-researcher` skill update |
| Per-round | hygiene gap-check + Pattern F Layer 1 INDEX consistency | `udm-round-closeout` Stage 2.5 |
| Per-quarter | Q11 research refresh + token cost trend | quarterly audit drill (mirrors Q1-Q10 Tier 5) |
| Per-year | full re-evaluation of plan against fresh research baseline | annual milestone review |

**Plan moves from 🟡 Plan-draft (research-grounded) → 🟡 Plan-final (decision-required)** with this commit. Pipeline-lead's §12 sign-off is the ONE remaining gate. After sign-off → 🟢 Locked + execution begins per §7.1 task breakdown WITH the §15.4 empirical-baseline-driven priority reordering (Phase 1.0 archive cascade FIRST).

---

## §17. Multi-agent gap-audit reflection (added 2026-05-15)

Per user 7th-directive request: "Reflect on the last planning sessions. Are there any gaps in the plans? Are there any edge cases worth considering? Use a multi-agent team to help."

3 parallel general-purpose agents executed independent gap audits from 3 perspectives (producer/execution + adversarial/edge-case + consistency/governance) per §16.5 multi-agent pattern. Combined ~600 lines of independent scrutiny; full synthesis at **`docs/migration/_research/gap-audit-synthesis-2026-05-15.md`**.

### §17.1 Headline finding

🔴 **Plan is research-rich but execution-poor.** All 3 audits independently converged on this verdict. Plan validates direction strongly but lacks concrete execution specifications. **5 mandatory pre-sign-off fixes** identified; 2 already applied inline this commit, 3 remain.

### §17.2 BLOCKERS (5; pre-sign-off)

| # | Finding | Source audit | Status |
|---|---|---|---|
| B-1 | §13.4 internal contradiction: opened with "MUST use em-dash" rule + listed em-dash as ✅ + later said em-dash 🔴 BROKEN | Consistency C-1 | ⚫ FIXED THIS COMMIT (§13.4 restructured to lead with empirical findings + colon-form) |
| B-2 | Archive trigger contradiction: §16.1 said 5K lines; §16.2 + new-repo template + measurement script said 2K | Consistency C-2 | ⚫ FIXED THIS COMMIT (standardized on 2K lines) |
| B-3 | `tools/verify_cascade.py` doesn't glob `_archive/` — Phase 1.0 archive cascade silently drops audit coverage | Producer F-7 | 🔴 OPEN; mandatory pre-sign-off; 5-line fix |
| B-4 | Three conflicting archive cutoff dates (30 / >30 / 90 days); operator can't pick | Producer F-1 | 🔴 OPEN; mandatory pre-sign-off; pipeline-lead decision |
| B-5 | 17 of 24 open Q-N unclassified by sign-off-blocking vs deferrable | Producer F-15 | 🔴 OPEN; mandatory pre-sign-off; new §10.A classification table |

### §17.3 CRITICAL failure modes (3; mitigate before execution)

| # | Failure mode | Mitigation | Status |
|---|---|---|---|
| F9.1 | Phase 1.0 lands; INDEX.md never does → repo WORSE than before | Bundle Phase 1.0 + 1.B as ATOMIC COHORT (reject if either lands without other) | Add to §5.1 as binding constraint |
| F1.1 | Archive partial-write crash → append-only invariant violated | Two-phase-commit semantics for archive script | Add to §7.1 task 1.2 procedural requirement |
| F5.1 | `udm-context-loader` brief silently omits Do-NOT rule → destruction-class production change possible | PASS-THROUGH-VERBATIM Do-NOT + Pitfall #9.x headers (not summarize) | Add to §15.2 Pattern D + §16.5 anti-patterns |

### §17.4 SERIOUS issues (8; Phase 1 fix OR B-N)

See synthesis §"SERIOUS" table for full list. Highlights:
- `_research/_INDEX.md` register MISSING (referenced 4× as binding governance; doesn't exist)
- Plan violates own colon-form rule (uses em-dash in own historical headings; D92 forward-only acknowledged)
- Plan is 997 lines / 42% past §13's own 700-line split-trigger (acknowledged)
- 5 stale "12K-16K lines per CCL" estimate references (empirical baseline shows 9,212 lines / 362K tokens)
- `udm-find-canonical` skill design unclear (multi-candidate? case sensitivity? OOM?)
- External-platform breaking changes not in risk register

### §17.5 POLISH items (6; P-Ns post-approval)

§14 missing (renumbering artifact) / §12 sign-off appears AFTER §16 (cosmetic) / lead-with-answer not applied to plan's own sections / NEW_REPO_STARTER_TEMPLATE.md doesn't fully demonstrate principles it preaches / 5-line quick-start missing from plan / sign-off mechanism procedurally undefined.

### §17.6 Multi-agent pattern reinforcement (Q4 reflection from §16.5)

This was the 2nd 3-parallel-agent session this cycle. Empirical observations:

✅ **3-parallel-agent pattern works for ORTHOGONAL audits** — when each agent has a genuinely different perspective, parallel execution yields convergent findings WITHOUT context-rot. ~5 min wall-clock vs ~15 min if sequential.

✅ **Convergence is signal** — when all 3 audits independently flag the same finding, that's high-confidence ground truth (e.g., "research-rich but execution-poor" surfaced from all 3 perspectives).

⚠️ **§16.5 anti-pattern empirically validated AGAIN**: 3 is the limit. A 4th parallel agent would not have added marginal value.

⚠️ **Cost calibration**: each gap-audit agent ~160K tokens / ~20 tool uses / ~3-4 min. Sustainable for periodic deep-dive audits; NOT a per-commit pattern.

**Recommendation**: add a new pattern to §16.5 — "**Periodic gap-audit cohort (3-perspective parallel)**" — fire at major plan revisions or pre-lock; not at every cycle.

### §17.7 Plan calculus changes from §17 reflection

Two cascade changes propagate to existing plan sections:

**1. To §5.1 (Phase 1)**: add F9.1 mitigation — Phase 1.0 + 1.B authored as ATOMIC COHORT; sign-off requires both to land together; explicit "do not commit Phase 1.0 without Phase 1.B" gate.

**2. To §15.2 Pattern D + §16.5**: add F5.1 mitigation — `udm-context-loader` briefs MUST pass-through-verbatim Do-NOT rules + Pitfall #9.x headers; never summarize them.

These can be inline-applied at the next plan revision OR at the pre-sign-off cleanup pass (B-3 + B-4 + B-5 fix session).

---

## §18. Phased execution breakdown (added 2026-05-15)

Per user 8th-directive sub-question "Break down the effort into phases. Use a multi-agent team to help." Wave 1 Agent C authored a comprehensive phase breakdown at **`docs/migration/_research/execution-phase-breakdown-2026-05-15.md`** (427 lines; 8 phases A through H with summary table + per-phase scope/tasks/effort/dependencies/acceptance/risk/sign-off + critical-path analysis + recommended sequencing). Brief reference here; full content in research artifact.

**8 phases summary**:

| Phase | Scope | Effort | Sequence |
|---|---|---|---|
| **A** | Pre-sign-off cleanup (3 BLOCKERS: B-3 verify_cascade.py + B-4 cutoff date + B-5 §10.A table) | ~30-60 min total | THIS COMMIT (mostly done) |
| **B** | Pre-execution mitigations (3 CRITICAL: F9.1 atomic-cohort + F1.1 two-phase-commit + F5.1 verbatim_excerpts) | ~30 min | THIS COMMIT (done) |
| **C** | Pipeline-lead sign-off ceremony (4 binary 🔴 BLOCKING Q-Ns from §10.A) | ~30-60 min pipeline-lead time | NEXT — gates Phase D |
| **D** | Phase 1 actual execution per §7.1 (D.0 prep / D.1 archive / D.2 INDEX.md / D.3-D.5 D62+skill+CLAUDE / D.6 Pattern E) | 1-2 cycles | After Phase C sign-off |
| **E** | Phase 2 tooling (regenerate_md_indexes / pre-commit hook / Pattern F extension / udm-context-loader) | ~1 cycle | After Phase D |
| **F** | Conditional Phase 3 (file splits) | TBD | Only fires if Phase A-E metrics insufficient |
| **G** | Conditional Phase 4 (frontmatter / udm-find-canonical polish) | TBD | After Phase A-F validated |
| **H** | Long-term governance (Q11 quarterly + _research/_INDEX.md + sign-off mechanism + multi-agent gap-audit pattern) | ~3 hours one-time + recurring | Parallel with Phase D-E |

**Critical-path sequence**: A → B → **C (sign-off gate)** → D → E (with optional Phase H parallel from Phase D onward).

**Total mandatory effort (Phases A-E)**: ~5-8 hours active work over 1.5-3 cycles wall-clock.

**Highest-leverage parallelization opportunities** (per Wave 1 Agent C analysis):
1. **Phase A + Phase B in single commit** — saves ~30 min; both pre-sign-off mechanical edits to different sections (✅ DONE THIS COMMIT)
2. **Phase D.3 + D.4 + D.5 as parallel subagent invocations** — saves ~2-3 hours (independent edits)
3. **Phase H.1-H.4 as parallel subagent invocations** — saves ~1.5 hours (independent governance artifacts)

**Recommended operator sequencing**:
- **Next 1-2 sessions**: Phase C sign-off (pipeline-lead reviews §10.A + answers 4 binary 🔴 questions; ~30-60 min) → Phase D.0 prep
- **Next 2-3 weeks**: Phase D execution in 3 sessions (D.0+D.1+D.2 atomic, then D.3-D.5 parallel cohort, then D.6 Pattern E review)
- **Next month**: Phase E tooling + Phase H governance (parallelizable)
- **Day 90 post-sign-off**: First Q11 quarterly drill triggers Phase F skip-vs-invoke decision

**Key gating constraints**: F9.1 atomic-cohort blocks Phase D.1 from landing without D.2 (✅ enforced via §5.1 atomic-cohort gate); B-4 archive cutoff blocks Phase D.1 from starting (✅ default 2026-04-15 stamped in §7.1 task 1.1); F1.1 two-phase-commit required for safe D.1 execution (✅ procedure spec'd in §7.1 task 1.2). All 3 trace back to gap-audit BLOCKERS now closed.

---

## §12. Sign-off

🟢 **APPROVED AS-IS 2026-05-15** by pipeline lead (dougmorrow@protonmail.com).

| Role | Name | Date | Decision |
|---|---|---|---|
| Pipeline lead | dougmorrow | 2026-05-15 | ✅ Approved as-is (4 binary 🔴 BLOCKING questions answered with Recommended defaults) |
| Notes | Q-1 ✅ Approve — Phase 1 starts now. Q-2 ✅ Accept 2026-04-15. Q-12 ✅ Approve <300 line CLAUDE.md trim. Q-23 ✅ Approve all 6 hygiene rules as binding. | | |

### §12.1 Approved questions (4 of 4 🔴 BLOCKING resolved)

| Q-N | Question | Decision | Operational note |
|---|---|---|---|
| Q-1 | Approve Phase 1? | ✅ Approved — Phase 1 starts now (Recommended) | Phase D.1+D.2 atomic-cohort gating (F9.1) still binding |
| Q-2 | Accept 2026-04-15 archive cutoff per existing policy? | ✅ Accept 2026-04-15 (Recommended) | **Empirical impasse**: D.0 prep found zero entries qualify (earliest entry 2026-05-09 = 24 days AFTER cutoff). Q-2 policy stands; Phase D.1 execution path requires follow-up decision — see B-272. |
| Q-12 | Approve CLAUDE.md trim to <300 lines at Phase 1.6? | ✅ Approve <300 line target (Recommended) | Phase 1.6 in scope; ~10% Stage 1+2 token savings via removal of grandfathered narrative |
| Q-23 | Approve 6-rule markdown hygiene as binding (D-N candidate)? | ✅ Approve all 6 rules as binding (Recommended) | D-N lock at next round close-out cascade via udm-decision-recorder (per D113 process-infra exemption precedent) |

### §12.2 Deferred questions (20 of 24 non-blocking; per §10.A classification)

**9** 🟡 DESIGN questions (Q-3, Q-4, Q-6, Q-8, Q-9, Q-11, Q-17, Q-19, Q-21 — corrected from "8" per udm-gap-check 2026-05-15 G2 finding #2 arithmetic-propagation drift; canonical enumeration shows 9 rows) move to Phase 1 design-decision queue (answer when starting affected task). 11 ⚪ DEFERRABLE questions move to `_research/open_questions_post_sign_off.md` candidate list (answer when needed; not blocking).

### §12.3 Phase 1 execution authorization

Per §18 phase breakdown, Phase 1 work is authorized to begin:
- Phase D.0 (recon) — ✅ COMPLETE (`_research/d0-prep-validation-log-survey-2026-05-15.md`); surfaced empirical impasse → B-272
- Phase D.1 (`_validation_log.md` archive cascade) — 🟡 BLOCKED pending B-272 resolution (pipeline-lead choice between Option A/C/E from D.0 prep doc)
- Phase D.2 (`INDEX.md` authoring) — 🟢 AUTHORIZED but ATOMIC-COHORT GATED with D.1 (per F9.1); can begin scoping but cannot land without D.1
- Phase D.3 (D62 CCL doctrine update) — 🟢 AUTHORIZED standalone
- Phase D.4 (Skill SKILL.md cascade updates) — 🟢 AUTHORIZED standalone
- Phase D.5 (CLAUDE.md trim to <300 lines) — 🟢 AUTHORIZED standalone (Q-12 approved)
- Phase D.6 (Pattern E independent review) — 🟢 AUTHORIZED once D.1-D.5 land

**Recommended path forward** (per D.0 prep recommendation): resolve B-272 via Option A (defer Phase D.1) OR Option E (pivot Phase 1 focus); proceed with D.3 + D.4 + D.5 standalone tasks; revisit D.1 + D.2 atomic-cohort when entries age OR retention policy is revised.
