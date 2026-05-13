# Obsidian Integration Guide

How to use Obsidian as the navigation and authoring layer over the existing `docs/migration/` markdown set. Optional, additive, fully reversible.

## What this enables

- **Bidirectional `[[wiki-links]]`** between decisions, edge cases, and runbooks (graph view shows D6 → D26 → D30 chain)
- **Dataview queries** over our 49 D-decisions and ~120 edge cases (e.g., "show all 🟡 status items")
- **Mermaid diagrams** render natively (we already use them)
- **Templater templates** for new decisions, edge cases, runbooks
- **Smart Connections** semantic search ("show notes related to D26" without exact-word match)
- **Obsidian Claude Code MCP** lets Claude Code see what tab you have open and edit through Obsidian's API

## Obsidian-flavored markdown caveats

Obsidian extends standard markdown with `[[wiki-links]]`, callouts, embeds, and Dataview blocks. **These render in Obsidian but NOT on GitHub or in standard markdown viewers.** If `docs/migration/` is rendered elsewhere (GitHub Pages, internal wiki), you'll see literal `[[D26]]` text and broken Dataview blocks.

Mitigations:
- Keep wiki-link conversion optional (this guide describes it, doesn't mandate it)
- Use `agathauy/wikilinks-to-mdlinks-obsidian` plugin for one-way conversion before publishing if needed
- Stick to standard Markdown unless Obsidian's extensions add real value

## Setup (zero-change baseline)

### 1. Open the existing folder as a vault

In Obsidian: **File → Open vault → Select folder** → point at `C:\Users\bigba\Desktop\Test_Repo-main\docs\migration\`.

That's it. Mermaid blocks render immediately. Existing inline references like "see D26" are plain text. Graph view shows nothing useful yet (no wiki-links).

This is sufficient for many use cases — Mermaid diagrams render, search works across all docs, file tree is the existing structure.

### 2. Recommended commercial license check

Obsidian is free for personal use. Commercial use (paid team, commercial codebase) requires a Commercial license (~$50/user/year). Verify with your org's licensing team before deploying.

## Phase 1: Plugin install (small effort, high value)

Install via Settings → Community plugins → Browse:

| Plugin | Purpose for our project |
|---|---|
| **Dataview** | Query 49 D-decisions and ~120 edge cases as a database. Generates phase rollup tables, decision status overviews. |
| **Templater** | Templates for new decisions/edge cases/runbooks. Auto-fills next D-number, today's date, status emoji. |
| **Smart Connections** | Local-embedding semantic search. "Show notes related to vault retention." No external API needed. |
| **Mermaid** | Built-in. Already works for our existing diagrams. |
| **Excalidraw** | Hand-drawn diagrams (architecture sketches, flowcharts) stored as `.excalidraw.md`. |
| **Frontmatter Links** | Renders YAML `depends_on: [[D26]]` as clickable links. Required if we use frontmatter-based dependencies. |
| **Claude Code MCP** | Lets Claude Code interact with the open Obsidian session (read open tab, edit through API). github.com/iansinnott/obsidian-claude-code-mcp |

**Note**: All plugins are open-source and would need approval per the user's strict OSS policy. Smart Connections + Templater + Dataview are the three that justify the cost most clearly.

## Phase 2: Templates directory (medium effort, optional)

Create `_templates/` for Templater:

```
docs/migration/_templates/
├── decision_template.md
├── edge_case_template.md
├── runbook_template.md
└── round_overview_template.md
```

Each template uses Templater syntax (`<% tp.date.now() %>`, `<% tp.system.prompt() %>`) to scaffold a new entity. See `_templates/decision_template.md` (created alongside this guide).

## Phase 3: Split monolith files (medium-large effort, optional, reversible)

This is the highest-value migration but the most invasive. **Don't do this without team buy-in** — it changes the doc set's structure significantly.

Currently:
- `03_DECISIONS.md` is one file with 49 decisions
- `04_EDGE_CASES.md` is one file with ~120 edge cases
- `05_RUNBOOKS.md` is one file with 11 runbooks

After split:
```
decisions/
  D01.md, D02.md, ..., D49.md
edge_cases/
  M/M01.md, ..., M12.md
  S/S01.md, ..., S14.md
  I/I01.md, ..., I20.md
  N/N01.md, ..., N10.md
  P/P01.md, ..., P10.md
  G/G01.md, ..., G10.md
  D/D01.md, ..., D05.md
  F/F01.md, ..., F20.md
  V/V01.md, ..., V10.md
runbooks/
  RB01.md, RB02.md, ..., RB11.md
```

Each split file gets YAML frontmatter:

```yaml
---
id: D26
type: decision
status: 🟢-locked
phase: phase1
depends_on: ["[[D06]]", "[[D26]]"]
related_edge_cases: ["[[P-12]]", "[[P-14]]"]
created: 2026-05-09
locked: 2026-05-09
owner: pipeline-lead
---
```

Inline references convert: "see D26" → "see [[D26]]".

**Trade-offs of splitting**:
- ✅ Dataview queries become powerful (per-decision metadata, status rollups)
- ✅ Graph view shows dependency relationships
- ✅ Per-decision history tracking
- ❌ `Ctrl-F` across all decisions becomes harder (open many files vs one)
- ❌ Git diff history fragments
- ❌ Reading flow disrupted (jumping between many files)

**Recommendation**: hold off on splitting until we have a concrete need (e.g., the team wants a per-decision Dataview dashboard, or auditors request a per-decision lineage view). The current monolith with Mermaid + Smart Connections covers most use cases.

## Phase 4: Dataview dashboards (after Phase 3 only)

Once split, create `_meta/dashboard.md` with:

````markdown
# Pipeline Decision Dashboard

## Decisions by status

```dataview
TABLE status, phase, owner
FROM "decisions"
WHERE type = "decision"
SORT status ASC, phase ASC
```

## Edge cases by series and status

```dataview
TABLE series, status
FROM "edge_cases"
WHERE type = "edge_case"
SORT series ASC, status ASC
```

## Open 🔴 items across the project

```dataview
LIST
FROM "decisions" OR "edge_cases" OR "runbooks"
WHERE status = "🔴"
```

## Phase progress

```dataview
TABLE length(rows) as count
FROM "decisions"
WHERE phase = "phase1"
GROUP BY status
```
````

These queries answer auditor and stakeholder questions automatically.

## Phase 5: Claude Code MCP integration (advanced)

Install `obsidian-claude-code-mcp` plugin in Obsidian. It runs a local MCP server on port 22360 that Claude Code auto-discovers.

What it enables:
- Claude Code knows what tab you have open in Obsidian
- Claude Code can open files in your Obsidian session (not just on disk)
- Diff view, workspace context, diagnostics

This is optional and most valuable when actively authoring docs. Less valuable for one-off review.

## Anti-patterns to avoid

- ❌ **Forcing the team into Obsidian when they prefer VS Code.** Obsidian is an option, not a mandate.
- ❌ **Splitting all monolith files at once.** Try one (e.g., 03_DECISIONS.md) and validate before doing 04_EDGE_CASES.md.
- ❌ **Using Obsidian-flavored markdown (Dataview, callouts) in files that GitHub renders.** Will produce broken-looking docs.
- ❌ **Committing `.obsidian/` config to git** if any vault settings contain personal preferences (themes, plugin lists). Add `.obsidian/workspace*` to `.gitignore` instead.
- ❌ **Running multiple AI agents (Claude Code MCP + Smart Connections external API) simultaneously** — context gets confused. Pick one.

## Decision matrix: when to use what

| Use case | Tool |
|---|---|
| Author a new decision | Templater (when split) or just edit `03_DECISIONS.md` |
| Find decisions related to "vault retention" | Smart Connections |
| Show all 🟡 status items | Dataview (after split) |
| Visualize D6 → D26 → D30 chain | Graph view (after split with frontmatter) |
| Quick edit while in Claude Code session | Claude Code MCP plugin |
| Render existing Mermaid diagrams | Built-in (works today, no setup) |
| Sketch a hand-drawn architecture | Excalidraw |
| Walk the doc tree to onboard | Open as vault, browse file tree |

## What about D43 (Alation integration)?

Alation is the data governance team's tool for the catalog of data assets (sources, tables, columns). Obsidian is for our planning/operational documentation.

These don't compete. Alation publishes to consumers; Obsidian is internal tooling for the pipeline team. Phase 6 deliverable for Alation integration (D43) is independent of this Obsidian setup.

## Migration script (when ready to split)

A one-time Python script can split monolith files:

```python
# tools/split_docs_for_obsidian.py
# Reads 03_DECISIONS.md, splits by ## D<N> headers, 
# writes one file per decision to decisions/D<N>.md
# Adds YAML frontmatter from existing status/driver/decision metadata
# Inline references "D<N>" become "[[D<N>]]"
```

Don't write this until Phase 3 is approved.

## Status

- **Phase 1 (plugin install)**: 🟡 Proposed; gated on OSS approval per D46
- **Phase 2 (templates)**: 🟡 Proposed; templates created at `_templates/`
- **Phase 3 (split files)**: 🔴 Not yet authorized
- **Phase 4 (Dataview)**: 🔴 Depends on Phase 3
- **Phase 5 (Claude Code MCP)**: 🔴 Depends on plugin OSS approval

## Cross-references

- D46 (skill / plugin evaluation) — Obsidian plugins fall under this gate
- D43 (Alation integration) — distinct from Obsidian; both can coexist
- `MAINTENANCE.md` § Development tooling — operational doc with install procedures
- `09_VISUALS.md` — Mermaid diagrams render in Obsidian without changes
