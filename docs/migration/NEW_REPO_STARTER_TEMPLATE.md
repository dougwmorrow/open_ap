# New repo starter template — agent-friendly markdown organization

**Status**: 🟡 Plan-draft authored 2026-05-15 — companion to `MARKDOWN_REFACTOR_PLAN.md` §16.2. Awaiting pipeline-lead approval (Q-24) before binding for new repos.

**Purpose**: Greenfield template for organizing `docs/` in a new repo to be agent-friendly from day 1. Encodes the lessons from the UDM project's after-the-fact retrofit (`MARKDOWN_REFACTOR_PLAN.md` 4 revisions; 6 research artifacts; ~50 cumulative findings). Copy this template's structure when bootstrapping a new project's documentation.

**Source-of-record**: `MARKDOWN_REFACTOR_PLAN.md` is the canonical plan; this template is its applied form for greenfield projects.

---

## §1. The 8 design principles applied from day 1

These are the lessons that took the UDM project 6 research artifacts to discover. A new repo applying them from day 1 avoids the entire retrofit cycle.

1. **Lean CLAUDE.md** — under 300 lines from creation. Anthropic's explicit guidance: "Bloated CLAUDE.md files cause Claude to ignore your actual instructions." Apply the "would removing this cause Claude to make mistakes?" filter to every line.

2. **Routing manifest INDEX.md from day 1** — in `llms.txt` format (H1 + blockquote summary + sections with linked files + intent descriptions). Routing-by-intent ("if task = X, read Y") NOT structural-by-description (per ETH Zurich research: structural overviews increase agent inference cost +20-23% with success rate -3%).

3. **Colon-form heading discipline from day 1** — all D-number / B-number / R-number / RB-N / SP-N headings use `## D15: Title` format (NOT `## D15 — Title` em-dash; em-dash breaks GitHub slug algorithm per empirical test in `_research/em-dash-slug-test-2026-05-15.md`).

4. **Cross-reference discipline from day 1** — explicit `[D15](03_DECISIONS.md#d15-title)` Markdown links from first commit. Never plain text "see D15" (Navigation Paradox per CodeCompass arxiv 2602.20048: explicit links push agent file-discovery from 78.2% → 99.4%).

5. **Append-only logs follow archive cadence from day 1** — `_validation_log.md` carries archive policy in its header from creation; archive when file exceeds 2,000 lines OR every 90 days (whichever first). Never let it grow past the trigger.

6. **Quality tiers explicit in CCL doctrine from day 1** — D62-equivalent specifies Stage 1 = canon-tier (4 reads max) / Stage 2 = reference-tier (3 reads max) / Stage 3 = ad-hoc-tier. Prevents CCL bloat (UDM hit 362K tokens = 181% of 200K context window before discovering this).

7. **`udm-find-canonical` skill scaffolded from day 1** — agents have native lookup mechanism from first invocation; SKILL.md under 500 lines + supporting `routing-table.md`.

8. **Token measurement script from day 1** — `tools/measure_ccl_overhead.py` (copy from this repo); run quarterly to track CCL drift; alerts when Stage 1+2 exceeds 100K tokens (50% of 200K window).

---

## §2. Recommended `docs/` directory structure

```
docs/
├── INDEX.md                       # ROUTING MANIFEST (Stage 0 read; <300 lines; llms.txt format)
├── 00_OVERVIEW.md                 # what is this project (lean; <500 lines)
├── 01_ARCHITECTURE.md             # high-level design
├── 02_DECISIONS.md                # D-numbers (split when >2K lines)
├── 03_RISKS.md                    # R-numbers
├── 04_BACKLOG.md                  # B-numbers
├── 05_RUNBOOKS.md                 # operational procedures (RB-N)
├── 06_TESTING.md                  # test strategy + Tier 5 quarterly drill register
├── _validation_log.md             # APPEND-ONLY audit (archive at 2K lines OR 90 days)
├── _research/
│   ├── _INDEX.md                  # research artifact register (per-artifact row)
│   └── *.md                       # individual research artifacts (one per topic)
├── _archive/                      # archived sections (split-source preservation)
│   └── _validation_log_*.md       # archived validation log entries
└── audit_reports/
    ├── _TEMPLATE_quarterly.md     # quarterly Q1-Q9 audit report template
    └── QYYYY_QN.md                # actual quarterly reports
```

**At project root**:
```
CLAUDE.md                          # entry-point compass (<300 lines; loads at every agent startup)
.claude/
├── settings.json                  # permissions config
├── settings.local.json            # local overrides + permissions.deny
├── agents/
│   └── *.md                       # custom agents (each <500 lines per Anthropic skill cap)
└── skills/
    ├── udm-find-canonical/
    │   ├── SKILL.md               # <500 lines
    │   └── routing-table.md       # canonical-home lookup table
    └── *.md                       # other custom skills
.claudeignore                      # patterns to exclude from Claude reads (credentials, secrets)
```

---

## §3. INDEX.md skeleton

Copy this template; fill in per-project specifics:

```markdown
# {Project Name} Documentation Index

> Intent-based routing for agents performing Canonical Context Load (CCL) Stage 0.
> Read the entry that matches your task; skip others. Routing-by-intent only — NOT a structural map.

**Last regenerated**: YYYY-MM-DD HH:MM

## Stage 0 reads (every CCL invocation; canon-tier)

- [CLAUDE.md](../CLAUDE.md) — "What MUST agents know before any task?" Entry-point compass.
- [INDEX.md](INDEX.md) — "Where do I find X?" This file.

## Stage 1 reads (canon-tier; mandatory)

- [00_OVERVIEW.md](00_OVERVIEW.md) — "What is this project?" Read first if unfamiliar.
- [01_ARCHITECTURE.md](01_ARCHITECTURE.md) — "How is it designed?" Read for architectural decisions.

## Stage 2 reads (reference-tier; on-demand)

- [02_DECISIONS.md](02_DECISIONS.md) — D-numbers. Read if your task references a specific D-N.
- [03_RISKS.md](03_RISKS.md) — R-numbers. Read if your task touches a risk.
- [04_BACKLOG.md](04_BACKLOG.md) — B-numbers. Read if your task closes or opens a B-N.

## Stage 3 reads (ad-hoc-tier; targeted)

- [05_RUNBOOKS.md](05_RUNBOOKS.md) — RB-N operational procedures. Read for incident response.
- [06_TESTING.md](06_TESTING.md) — Test strategy. Read for testing-related work.

## Validation trail

- [_validation_log.md](_validation_log.md) — LIVE entries (last 30 days OR <2K lines).
- [_archive/](_archive/) — Archived validation logs (older than 30 days).

## Research artifacts

- [_research/_INDEX.md](_research/_INDEX.md) — Research artifact register. Read first if researching.

## Audit reports (Tier 5)

- [audit_reports/](audit_reports/) — Quarterly audit reports. Q11 covers markdown hygiene.
```

---

## §4. CLAUDE.md skeleton (lean)

```markdown
# {Project Name}

{1-paragraph project description; <100 words}

## Critical guardrails (DO + DO NOT)

### DO
- Use colon-form headings for D/B/R/RB/SP IDs: `## D15: Title`
- Cite cross-references as explicit Markdown links: `[D15](docs/02_DECISIONS.md#d15-title)`
- Lead every section with 1-3 sentence direct answer before elaborating
- Run pytest before committing
- Run `tools/measure_ccl_overhead.py --baseline-out` quarterly + before any major doc work

### DO NOT
- Create files >2K lines without sub-section splits
- Use em-dash, en-dash, or ASCII hyphen in ID-prefix headings (breaks GitHub slug algorithm)
- Cite cross-references as plain text "see D15" (Navigation Paradox: 22-point file-discovery hit)
- Let `_validation_log.md` exceed 2K lines or 90 days without archive
- Add to CLAUDE.md without applying "would removing this cause Claude to make mistakes?" filter

## Where to find things

See `docs/INDEX.md` for routing-by-intent manifest. Use `udm-find-canonical` skill for one-shot ID lookups.

## Commands

- `pytest -q` — run tests
- `python tools/measure_ccl_overhead.py` — measure CCL token cost
- `python tools/test_github_slug.py` — verify heading-slug behavior

## Autonomous rules

- Proceed without asking: refactoring shared utilities, fixing lint, adding type hints
- STOP and ask: changing data contracts, modifying core logic, altering naming conventions
```

---

## §5. CCL doctrine skeleton (D62-equivalent)

```markdown
# Canonical Context Load (CCL) doctrine

Every agent / sub-agent / skill performs CCL before any task-specific tool call.

## Stage 0 — Routing (1 read)
- Read `docs/INDEX.md`

## Stage 1 — Canon-tier (4 reads max; mandatory; never skip)
- Read `CLAUDE.md`
- Read `docs/00_OVERVIEW.md`
- Read `docs/01_ARCHITECTURE.md`
- Read `docs/_validation_log.md` (LIVE entries; archive read on-demand only)

## Stage 2 — Reference-tier (3 reads max; on-demand based on Stage 0 routing)
- Per task: read decisions / risks / backlog as INDEX directs

## Stage 3 — Ad-hoc-tier (targeted; offset+limit reads only for files >500 lines)
- Per task: read specific sections of larger files

## Verification
- Stage 1+2 token budget should stay under 100K tokens (50% of 200K context window)
- Run `tools/measure_ccl_overhead.py` quarterly to track drift
```

---

## §6. _validation_log.md header skeleton (with archive policy from day 1)

```markdown
# Validation Log

Append-only audit trail for all artifacts that pass through the 5-gate validation discipline.

**Pattern**: produce → validate → record → lock. Always in that order.

**Hard rules**:
- Append only. Never edit or delete entries.
- Each entry corresponds to one artifact / one validation pass.

## Archive policy

**Triggers** (whichever fires first):
- File exceeds 2,000 lines
- File contains entries older than 90 days
- Quarterly review boundary

**Procedure**:
1. Copy entries dated >30-days-ago to `docs/_archive/_validation_log_archive_<YYYY-MM>.md`
2. Truncate the archived entries from this live file
3. Add 1-line back-reference at top: `**Archive**: pre-<YYYY-MM-DD> entries archived to _validation_log_archive_<YYYY-MM>.md`
4. Verify line count post-truncate is <2,000

Audit-trail discipline preserved by the archive file. Append-only invariant applies to BOTH files post-archive.

---

(append validation entries below; newest at top OR newest at bottom — pick one + apply consistently)
```

---

## §7. _research/_INDEX.md skeleton (research artifact register)

```markdown
# Research artifact register

Per-artifact register for `docs/_research/`. Append-only audit trail.

## Active artifacts

| Date | Artifact | Scope | Key findings | Plan section(s) | Status |
|---|---|---|---|---|---|
| YYYY-MM-DD | example-2026-XX-XX.md | scope description | 1-line summary | §X.Y | Active / Superseded-by-<artifact> |

## Quarterly refresh due

| Artifact | Last refreshed | Next due | Owner |
|---|---|---|---|
| example-2026-XX-XX.md | YYYY-MM-DD | YYYY-MM-DD (90 days) | quarterly Q11 audit |
```

---

## §8. tools/ scripts to copy from day 1

Copy these from the UDM project (zero-cost; pure stdlib; no external deps):

- `tools/measure_ccl_overhead.py` — CCL token cost measurement (~218 lines)
- `tools/test_github_slug.py` — GitHub slug algorithm validator (~89 lines)

Run them at project setup + quarterly thereafter.

---

## §9. CI / pre-commit hooks (Phase 2 of UDM plan; copy when ready)

When the project is ready for CI infrastructure:
- `lychee` — broken link checker (weekly cron)
- `markdownlint` — heading + structure linting
- Pre-commit hook running `tools/measure_ccl_overhead.py --check-budget` (fails if Stage 1+2 exceeds 150K tokens)

These can land later — Phase 1 (the structural patterns above) is the high-leverage starting point.

---

## §10. Why these matter (1-paragraph each)

**Lean CLAUDE.md**: every agent reads it at startup. Bloated CLAUDE.md = bloated context for every single agent invocation = degraded agent reasoning. Anthropic's explicit guidance.

**Routing manifest INDEX.md**: agents don't browse like humans. They grep + filename + H2 headers + entry-point files. INDEX.md as routing manifest is the entry-point cascade root. Without it, agents form ad-hoc mental models of the repo, which drifts.

**Colon-form headings**: GitHub's slug algorithm keeps em-dash + en-dash + ASCII hyphen as literal characters in the slug. `## D15 — Title` produces slug `d15-—-title` (em-dash embedded). Only colon and period strip cleanly. Empirically verified via `tools/test_github_slug.py`.

**Explicit cross-reference Markdown links**: Navigation Paradox (CodeCompass arxiv 2602.20048): explicit links push agent file-discovery from 78.2% → 99.4%. Plain text "see D15" is a 22-point file-discovery hit.

**Append-only logs with archive cadence**: append-only audit trails grow unboundedly. UDM's `_validation_log.md` reached 7,519 lines = 231K tokens = 115% of context window before the archive policy fired. Apply policy from day 1 to never reach that state.

**Quality tiers in CCL**: training labs explicitly weight high-quality data; CCL Stage 1/2/3 is the doc analog. Without explicit tiering, every doc gets read at every CCL → token cost spirals.

**Native skill for canonical lookup**: Anthropic's skill mechanism is THE native pattern for on-demand reference loading. Using grep + Read for D-number lookups every time is wasteful when a single skill does the job.

**Token measurement from day 1**: empirical baselines beat theoretical estimates. UDM took 6 research artifacts to discover that Stage 1+2 = 181% of context window. A measurement script answers this in 2 seconds.

---

## §11. What this template does NOT cover

- Project-specific content (every project has unique decisions, runbooks, risks)
- Deployment patterns (use the project's existing deploy approach)
- Test framework choice (pytest assumed; adapt to your stack)
- Code conventions outside docs/ (style guides, lint rules — orthogonal)
- Multi-language docs (if you need i18n, use a docs platform like Docusaurus)
- Web-publishable docs (if docs are public-facing, sitemap.xml + crawler discovery applies; this template is for INTERNAL repos)

---

## §12. Migration path for EXISTING repos

If you have an existing repo and want to retrofit this pattern:
1. Read `MARKDOWN_REFACTOR_PLAN.md` Phase 1.0 (`_validation_log.md` archive cascade) first — this is the highest-leverage single change for an existing repo
2. Apply colon-form heading rule going forward (existing em-dash headings stay; bulk-normalize at next major refactor)
3. Author INDEX.md routing manifest with current files
4. Add CLAUDE.md (or trim existing one)
5. Don't try to do everything at once — stage per Phase 1 → Phase 2 → Phase 3 of `MARKDOWN_REFACTOR_PLAN.md`

The retrofit is harder than the greenfield from-day-1 application. New repos: use this template. Existing repos: follow the plan.

---

## §13. Cross-references

- `MARKDOWN_REFACTOR_PLAN.md` — canonical plan (4 revisions; ~1080 lines); this template is the applied form for greenfield
- `MARKDOWN_REFACTOR_PLAN.md` §16.2 — section that introduces this template
- `_research/agent-markdown-traversal-2026-05-15.md` — research backing principles 1-2
- `_research/agent-discoverability-2026-05-15.md` — research backing principles 3-4 + Navigation Paradox
- `_research/em-dash-slug-test-2026-05-15.md` — empirical validation of principle 3
- `_research/ccl-baseline-2026-05-15.md` — empirical baseline backing principle 8
- `_research/llm-training-data-storage-2026-05-15.md` — backing principle 6 (quality tiers)
- `_research/cross-reference-maintenance-agent-2026-05-15.md` — backing 4-component design referenced in §9
- `_research/web-crawler-techniques-2026-05-15.md` — backing principles 1-2 + lead-with-answer discipline
- Anthropic Claude Code best practices: https://code.claude.com/docs/en/best-practices
- Anthropic Claude Code skills: https://code.claude.com/docs/en/skills
- llms.txt open standard: https://llmstxt.org/
- CodeCompass Navigation Paradox: https://arxiv.org/html/2602.20048v1

---

*Authored 2026-05-15 as companion to MARKDOWN_REFACTOR_PLAN.md §16.2. Q-24 in plan §10 gates this template's adoption as binding for new repos.*
