# Building an Agentic Software Factory — AppLaunchpad-Style Architecture

A replication guide for systems that take ideas through research → blueprint → build → ship via specialized AI agents. Sourced from AppLaunchpad, an autonomous AI software factory built by a solo developer to ship mobile apps end-to-end.

---

## 1. What You're Building

An **event-driven, pull-based system of specialized Claude Code agents** that collaborate via a shared event store and per-project knowledge vault, with a human (you) approving phase gates via Slack. Each agent is autonomous within its phase; the orchestrator routes work based on event state; quality gates and blindspot checks enforce discipline.

Core properties to preserve:

- **Append-only event store** — every action is a typed event; state is reconstructed via projections
- **Pull-based orchestration** — no push notifications between agents; orchestrator polls state
- **Vault-as-knowledge** — markdown files with frontmatter; agents read each other's outputs via files, not in-memory state
- **Slack as sole human interface** — gate approvals, progress updates, errors all flow through 4 channels
- **Self-hosted substrate** — runs on a Mac mini via launchd; no cloud Managed Agents, secrets stay local
- **90/10 planning ratio** — agents spend 90% planning, 10% implementing; gate checkpoints between phases

---

## 2. Foundational Philosophy

Adapted from AppLaunchpad's `AGENT_TEAM_OS.md` — a 1200-line operating manual every agent reads first. The principles are deliberately non-negotiable; everything else (templates, phases, tools) is revisable.

### The 10 Agent Principles

1. **Why before how.** Every project starts with a problem statement, not a tech choice. Sequence: Why → What → How.
2. **Tools serve problems, not the reverse.** No default tech stack. Choose tools that match the problem's constraints.
3. **Evidence over assumption.** Claims must be grounded in observable evidence. "I think users want X" is hypothesis; "We observed Y" is evidence.
4. **Plan cheaply, build expensively.** Words are cheaper than code. Invest heavily in planning.
5. **The vault is the source of truth.** If it matters, it's written down with metadata. No reliance on conversational memory.
6. **Agents are accountable through transparency.** All work is visible via the vault. No hidden work.
7. **Deterministic gates over hopeful instructions.** Anything that must always happen is enforced via hooks, not written instructions.
8. **The system improves itself.** Reflect after every project; capture lessons as document updates.
9. **Done means verified.** "I wrote the code" is not done. "Acceptance criteria are met by tests" is done.
10. **Minimum viable everything.** Smallest version that could work, validate, expand.

### The 7 Organizational Principles (How Teams Relate)

A. **Commander's intent, not method.** CLAUDE.md sets objective + constraints. How is up to the agent.
B. **Contracts are the only communication.** Teams interact ONLY through typed events. No backdoor file reads.
C. **Small teams, single mission, full ownership.** One team = one mission, end-to-end.
D. **Pull, not push.** Teams activate when their trigger events appear. No scheduling.
E. **Stop the line on defects.** Upstream quality problems halt the pipeline; don't build on bad foundations.
F. **The system improves itself.** After-action reviews; outcome tracking closes the feedback loop.
G. **Teams are mortal.** Deprecate when purpose is served. Cheap to create, cheap to archive.

These principles drive specific architectural choices below.

---

## 3. The Six-Phase Pipeline

Every project moves through six phases in order. Each phase has explicit inputs, outputs, exit criteria, and a human gate.

| Phase | Goal | Outputs | Gate question |
|---|---|---|---|
| **0. Idea Evaluation** | Filter ideas in hours, not weeks | Scored idea record, go/park/kill decision | Worth investing a week of research? |
| **1. Research** | Validate the problem deeply | Problem statement, personas, competitor map, market sizing | Is the gap real and solvable now? |
| **2. Blueprint** | Design before building | Spec, architecture, data model, API contract, task breakdown, tool decisions | Is this buildable as specified? |
| **3. Build** | Implement the blueprint | Working code, tests, component docs | Do acceptance criteria pass? |
| **4. Ship** | Get it into users' hands | Deployment, runbook, monitoring, rollback plan | Is it live and observable? |
| **5. Customers** | Find people who need this | ICP, prospect list, outreach templates, feedback | Did people respond? |

**Phase 0 scoring** uses four dimensions on a 1-5 scale: Problem Intensity, Timing, Path to Revenue, Buildability. Scores 18+ skip to Architect; 15-17 trigger automated validation; 13-14 are human-reviewed; 8-12 are parked; <8 killed.

**Gates** are explicit checkpoints. The team requesting a gate emits `vault.gate.requested`; the orchestrator notifies the human via Slack with Approve/Reject buttons; on approval the next team is triggered.

---

## 4. Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                     SLACK (human interface)                  │
│   #ideas  #errors  #alternatives  #opportunities             │
└──────────────────┬──────────────────────┬───────────────────┘
                   │                      │
            slack_bot.py            slack_notify.py
          (Socket Mode listener)    (notification dispatch)
                   │                      │
                   ▼                      ▲
┌─────────────────────────────────────────────────────────────┐
│                   ORCHESTRATOR (pull-based)                  │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐ │
│  │  router.py     │  │  actions.py    │  │  runner.py     │ │
│  │  (queries)     │  │  (emit events) │  │  (spawn agents)│ │
│  └────────────────┘  └────────────────┘  └────────────────┘ │
└──────────────────┬──────────────────────────────────────────┘
                   │ polls every 30s
                   ▼
┌─────────────────────────────────────────────────────────────┐
│              EVENT STORE (SQLite, append-only)               │
│  events table  │  projections (decisions, gates, tasks, ...)│
└──────────────────┬──────────────────────────────────────────┘
                   ▲                          ▲
                   │ emits                    │ emits + reads
                   │                          │
┌──────────────────┴──────────┐   ┌──────────┴──────────────┐
│  TEAMS (Claude Code agents) │   │  INGESTER (vault→events)│
│  scout/architect/builder/   │   │  watches vault changes  │
│  qa_agent/auditor/shipper   │   │  parses 15 event types  │
└──────────────┬──────────────┘   └──────────┬──────────────┘
               │                              │
               ▼                              ▼
┌─────────────────────────────────────────────────────────────┐
│        VAULT (per-project Obsidian, markdown + YAML)         │
│   00-inbox/  01-research/  02-blueprint/  03-build/          │
│   04-ship/  05-customers/  06-retro/  agents/                │
└─────────────────────────────────────────────────────────────┘
                                              ▲
                                              │ reads/writes
┌─────────────────────────────────────────────────────────────┐
│                    COCKPIT (dashboard)                       │
│        pipeline status, project view, event tail             │
└─────────────────────────────────────────────────────────────┘

                  ┌──────────────────┐
                  │ launchd (macOS)  │   substrate:
                  │  orchestrator    │   - Mac mini
                  │  slack_bot       │   - SQLite database
                  └──────────────────┘   - Cloudflare Tunnel (if external webhooks)
```

---

## 5. The Event Store (State Foundation)

### Why event-driven

- **Single source of truth** for all state transitions
- **Idempotent** — re-running a step doesn't duplicate work
- **Auditable** — every decision is traceable to the events that caused it
- **Concurrency-safe** — pull-based polling eliminates race conditions
- **Replayable** — projections can be rebuilt from events

### Schema (SQLite)

Six tables, all derived from the canonical `events` table:

```python
# Canonical (append-only)
events(id, event_type, occurred_at, actor, session_id,
       entity_type, entity_id, parent_event_id,
       payload JSON, context JSON, idempotency_key, created_at)

# Projections (rebuilt from events)
decisions(id, title, status, category, tags, ...,
          actual_outcome, outcome_quality, ...)  # Farnam Street columns
gates(id, gate_name, requesting_team, next_team, status, summary, ...)
tasks(id, project_id, title, status, depends_on, ...)
ideas(id, hypothesis, score_problem, score_timing, ...,
      score_total, decision, ...)
projects(id, name, phase, current_team, ...)
```

### Idempotency

Every event has an `idempotency_key`. For single-event source files:

```python
idempotency_key = sha256(source_path + content_sha256)
```

For multi-event source files (e.g., a markdown table with N rows → N events), add a per-event discriminator:

```python
# Event-log row: discriminator = row hash
key = sha256(source_path + sha256(line)[:8])

# YAML list entry: discriminator = entry ID + content hash
key = sha256(source_path + entry_id + content_sha256)
```

Backfill uses `INSERT OR IGNORE` on `idempotency_key` — re-running emits zero duplicates.

### Standard event fields

Every event carries:

- `event_type` — namespaced like `vault.decision.captured`
- `entity_type` + `entity_id` — what the event is about
- `parent_event_id` — causal lineage (incident → blindspot → skill)
- `payload` — typed JSON, with `schema_version` for evolution
- `context` — `{subsidiary, source_vault, source_path, ingester_version}`
- `idempotency_key` — for dedup

### Performatives

Every payload includes a `performative` field disambiguating intent:

| Performative | Meaning |
|---|---|
| `INFORM` | Delivering completed work |
| `REQUEST` | Asking another agent to act |
| `PROPOSE` | Suggesting something needing approval |
| `CONFIRM` | Acknowledging or approving |
| `REJECT` | Declining with feedback |
| `QUERY` | Asking a question |

### Event types

15 `vault.*` events cover the lifecycle. Three classes:

**Decision lifecycle (2):** `decision.captured`, `decision.outcome_reviewed`
**Artifact discovery (8):** `event.logged`, `blindspot.observed`, `incident.detected`, `insight.recorded`, `assumption.surfaced`, `skill.adopted`, `reflection.updated`, `entity.archived`
**Pipeline control (5):** `gate.requested → gate.passed | gate.blocked`, `pipeline_gap.identified → pipeline_gap.resolved`

Each event type has a Pydantic payload schema with `schema_version` for backward-compat evolution. See `docs/event-taxonomy.md` for the canonical reference.

### Projection updates

```python
@on_event("vault.decision.captured")
def update_decisions_projection(event):
    upsert decisions table from event.payload
```

Decorators register handlers; the event emitter invokes them after `INSERT OR IGNORE` succeeds.

---

## 6. The Vault (Knowledge Foundation)

Per-project Obsidian vault (just markdown + YAML — no Obsidian instance required). Each project gets its own vault directory. The vault is the **only** way knowledge crosses agent boundaries; events carry state, the vault carries context.

### Structure

```
vault/
├── 00-inbox/           # Raw captures, unprocessed
├── 01-research/        # Problem statements, personas, competitors, market
│   ├── problems/
│   ├── competitors/
│   ├── users/
│   └── market/
├── 02-blueprint/       # spec.md, architecture.md, data-model.md,
│   │                   # api-contract.md, tool-decisions.md, todo.md
│   └── blindspots-*.yml
├── 03-build/           # Implementation docs
│   ├── components/
│   ├── decisions/      # Architecture decision records
│   ├── issues/         # Incident reports
│   └── event-log.md    # Timestamped event narrative
├── 04-ship/            # deploy-runbook.md, monitoring.md, rollback-plan.md
├── 05-customers/       # ICP, prospects, outreach templates
├── 06-retro/           # observations/, overrides/, rejected/, changelog.md
├── agents/             # tasks/, handoffs/, gates/, status-board.canvas
├── templates/          # Note templates for consistency
└── DASHBOARD.md        # Dataview-powered project overview
```

### Frontmatter standard

Every vault file:

```yaml
---
type: research | blueprint | build | ship | decision | task | observation
phase: research | blueprint | build | qa | ship
agent: scout | architect | builder | qa_agent | shipper
status: draft | active | blocked | review | done | archived
owner: agent-name | unassigned
created: YYYY-MM-DD
updated: YYYY-MM-DD
tags: []
links_to: []
---
```

### Wiki-link convention

The vault is a knowledge graph via `[[wiki-link]]` syntax:

| From | Links to | Purpose |
|---|---|---|
| `problem-statement.md` | `[[personas]]`, `[[competitors]]` | Context for the core problem |
| `spec.md` features | `[[problem-statement#core-need]]` | Traceability: every feature → problem |
| `tasks.md` items | `[[spec#feature]]`, `[[architecture#component]]` | What each task implements |
| `qa-results.md` failures | `[[tasks#task-id]]` | Which task's code failed |

Never delete links — they are the project's knowledge graph.

---

## 7. Agents (Capability Layer)

Agents are immutable, specialized Claude Code subagents launched in isolated sessions. Each lives in its own directory under `teams/<category>/<name>/`.

### Categories

| Category | Agents |
|---|---|
| **research** | scout, brainstormer, verifier, opportunity_scout |
| **planning** | architect, planner |
| **build** | builder |
| **testing** | qa_agent, acceptance_tester, auditor |
| **deployment** | shipper, verifier |
| **operations** | human_task_tracker, retrospective |

### Per-agent directory

```
teams/research/scout/
├── agent-card.json     # Capability declaration (machine-readable)
├── CLAUDE.md           # Operating protocol (binding, agent reads first)
├── reflections.md      # Distilled learnings from past runs
├── README.md           # Human-readable team description
├── knowledge/          # Reference material (competitors, markets, patterns)
│   └── *.md
├── src/                # Code, if the team runs scripts
└── tests/              # Validation suite
```

### `agent-card.json` schema

```json
{
  "name": "scout",
  "display_name": "Scout — Research & Validation",
  "category": "research",
  "description": "Evaluates ideas and researches problems. Produces evidence, not opinions.",
  "capabilities": ["idea_scoring", "competitor_analysis", "market_sizing"],
  "input_requirements": {
    "vault_files": ["brainstorm/session.md"],
    "event_types": ["idea.submitted"],
    "requires_gate": false
  },
  "output_artifacts": {
    "vault_files": ["HANDOFF.md", "research/problem-statement.md"],
    "event_types": ["idea.scored", "research.completed", "gate.requested"]
  },
  "constraints": {
    "max_duration_minutes": 20,
    "can_write_code": false,
    "can_deploy": false,
    "can_modify_spec": false
  },
  "routing": {
    "triggered_by": ["idea.submitted"],
    "routes_to": ["architect"],
    "blocked_routes_to": ["doug"]
  },
  "performatives_used": ["INFORM", "PROPOSE"]
}
```

### `CLAUDE.md` — the operating protocol

Required sections for every team's CLAUDE.md:

1. **Team metadata** — YAML: name, category, trigger_events, output_events
2. **Purpose** — What this team does and does NOT do
3. **Principles** — Specialized from AGENT_TEAM_OS for this domain
4. **Input contract** — Exact events/files this team reads
5. **Output contract** — Exact events this team emits
6. **Tools and permissions** — Allowed and forbidden
7. **Quality gates** — Checklist before declaring done
8. **Constraints** — Hard boundaries (never-do list)
9. **Secrets & sensitive files** — Standard secrets rules
10. **Blindspot query protocol** — How to check the ledger before phase exit

### Skills integration

Agents load skills at trigger time, not upfront:

- **Audited skills** (`skills-import/audited/`) — code imported into the repo, no per-use CVE audit
- **Plugin skills** — third-party from marketplace, looser trust boundary
- **Binding skills** (`no-production-pii`, `never-touch-secrets`) — enforced via ingester denylist, not just instructions

Example: Builder loads 5 audited skills at different moments:

| Skill | When loaded |
|---|---|
| `writing-plans` | Before task breakdown |
| `executing-plans` | Before task execution |
| `subagent-driven-development` | When fanning out parallel workstreams |
| `using-git-worktrees` | Before creating isolated workspaces |
| `verification-before-completion` | Before EVERY `task.completed` claim |
| `finishing-a-development-branch` | At task completion (4-option chooser) |

---

## 8. Orchestrator (Pull-Based Polling Loop)

The orchestrator does NOT push work to agents. It polls the event store every 30 seconds and reacts to state.

### Three core modules

**`router.py`** — read-only queries:

```python
def find_unprocessed_ideas() -> list[Idea]: ...
def find_pending_gates() -> list[Gate]: ...
def find_approved_gates_needing_teams() -> list[Gate]:
    # filter out async reviewers: auditor, verifier, retrospective
    # they run alongside the main pipeline, not in it
```

**`actions.py`** — event emitters:

```python
def submit_idea(text, channel, thread_ts) -> Event
def approve_gate(gate_id, approver) -> Event
def reject_gate(gate_id, feedback) -> Event
def terminate_project(project_id, reason) -> Event
```

**`runner.py`** — spawns Claude Code subagents:

```python
def launch_team_cli(gate_id, team_name, project_path):
    # spawns: claude -p "<team_prompt>" with env vars
    #   GATE_ID, PROJECT_PATH, TEAM_NAME
    # captures stdout/stderr to .logs/
    # tracks run state; skips if team already running for this gate
```

### Main loop

```python
while True:
    for idea in router.find_unprocessed_ideas():
        runner.launch_team_cli(idea.gate_id, "scout", idea.project_path)
    
    for gate in router.find_pending_gates():
        slack_notify.notify_pending_gates(gate)  # idempotent
    
    for gate in router.find_approved_gates_needing_teams():
        runner.launch_team_cli(gate.id, gate.next_team, gate.project_path)
    
    health.check_stale_runs()
    health.backup_database()
    
    time.sleep(30)
```

### Why pull, not push

- **No race conditions** — orchestrator is single-threaded; agents read state, never coordinate
- **Easy to add a new team** — register an event consumer; no changes to existing code
- **Recovery is free** — restart orchestrator, it resumes from event store

### State transitions

```
idea submitted (Slack)
  → idea.submitted event
  → Scout triggered (next poll)
  → Scout emits research.completed + gate.requested
  → Orchestrator detects pending gate
  → Slack notification with Approve/Reject buttons
  → User clicks Approve
  → slack_bot emits gate.approved
  → Orchestrator detects approved gate, triggers Architect
  → Architect emits blueprint.completed + gate.requested
  → ...repeat through phases...
  → Shipper emits release.shipped
```

---

## 9. Ingester (Vault → Events Bridge)

The ingester watches vault filesystem changes and emits events. This lets agents communicate by writing markdown files — much more natural than constructing event payloads inline.

### Components

```
core/ingester/
├── parser.py              # 15 event-builder functions (one per event type)
├── watcher.py             # Filesystem watcher (backfill + watch modes)
├── frontmatter_schemas.py # Pydantic models per event payload
├── denylist.py            # Enforces binding skills (no PII, no secrets)
└── backfill.py            # Historical event hydration
```

### Detection rules

| Vault location | Event emitted |
|---|---|
| `03-build/decisions/*.md` | `vault.decision.captured` |
| `03-build/decisions/<id>-outcome.md` | `vault.decision.outcome_reviewed` |
| `03-build/event-log.md` (new rows) | `vault.event.logged` |
| `02-blueprint/blindspots-*.yml` entries | `vault.blindspot.observed` |
| `03-build/issues/*.md` with `severity:` | `vault.incident.detected` |
| `.claude/skills/<name>/SKILL.md` (create) | `vault.skill.adopted` |
| `teams/*/reflections.md` (new section) | `vault.reflection.updated` |
| Any deleted file | `vault.entity.archived` |

### Denylist (binding skills enforced at parse time)

```python
DENIED_PATHS = [
    "06-founder/**",          # personal reflections
    "**/private/**",
    "*.env*", "*.key", "*.pem", "credentials*",
    "*-service-account*.json",
]

DENIED_FRONTMATTER = {
    "status": "private",
    "audience": "doug",
    "confidential": True,
}
```

Files matching denylist are skipped entirely — no events emitted.

---

## 10. Slack Integration (Sole Human Interface)

### Channels (per tenant)

| Channel | Purpose |
|---|---|
| `#<tenant>-ideas` | Idea submissions + per-idea threads |
| `#<tenant>-errors` | Failures, system alerts, exception traces |
| `#<tenant>-alternatives` | Pivot ideas surfaced from Scout research |
| `#<tenant>-opportunities` | Opportunity Scout findings (boring businesses, grants) |

Channel prefix is the tenant's 3-letter code (e.g., `swt-` for ScrewwormTracker). Cross-tenant channels (e.g., `#alerts`) with title prefixing are an alternative to per-tenant proliferation.

### Two services

**`slack_bot.py`** — Socket Mode listener:

```python
# Receives:
#   - Messages in #ideas → actions.submit_idea()
#   - Button clicks (Approve/Reject) → actions.approve_gate() / reject_gate()
# Required env: SLACK_BOT_TOKEN, SLACK_SIGNING_SECRET, SLACK_APP_TOKEN
```

**`slack_notify.py`** — notification dispatch:

```python
def create_idea_thread(idea)              # new idea → #ideas + thread
def notify_pending_gates(gate)            # Doug: "Approve or Reject?"
def post_pipeline_summary()               # daily/weekly digest
def notify_failed_runs(run, context)      # → #errors
def post_auditor_findings(findings)       # async reviewer output
def post_opportunity_findings(map)        # Opportunity Scout maps
```

### Gate review loop

1. Team emits `gate.requested` → orchestrator detects
2. `slack_notify.notify_pending_gates()` posts thread in #ideas with Approve/Reject buttons
3. User clicks → slack_bot receives button_click → `actions.approve_gate()` updates gate.status in event store
4. Orchestrator polls next cycle, sees `status=approved` → triggers next_team

The button click writes to the event store; the orchestrator reads from the event store. Slack never directly invokes anything.

---

## 11. Cockpit (Visibility)

```
core/cockpit/
├── cli.py            # Command-line: status, tail, diagnostics
├── html_render.py    # Flask + WebSocket templates
└── __main__.py       # HTTP server entry
```

Displays:

- Real-time pipeline status (which team is running, percent complete)
- Per-project dashboard (tasks, blocked items, phase, P&L if tracked)
- Event log tail (latest events across all projects)
- Health metrics (DB backups, stale runs, scale-trigger values)

Built as plain Flask + WebSocket (no SPA framework). Reads directly from the SQLite event store and projections.

---

## 12. Quality & Guardrails

Three layers of defense:

### Layer 1 — Hooks (deterministic, can't be bypassed)

Configured in `.claude/settings.json`:

```json
{
  "hooks": {
    "SessionStart": [
      {"hooks": [{"type": "command", "command": "git status --short"}]}
    ],
    "PreToolUse": [
      {
        "matcher": "Bash|Read|Edit|Write|NotebookEdit|Glob|Grep",
        "hooks": [{"type": "command", "command": "~/.claude/hooks/block-secrets.py"}]
      }
    ]
  }
}
```

Standard hook patterns:

- **PreToolUse on Bash|Read|Edit|Write** — block `.env`, credentials, secrets paths
- **PostToolUse on Write|Edit** — auto-lint and auto-format
- **Stop** — run test suite before declaring task complete
- **SessionStart** — load git status, active tasks, blockers

### Layer 2 — Skills (loaded at trigger time)

- **Audited skills** — copied into `skills-import/audited/`, code-reviewed, no per-use trust check
- **Plugin skills** — third-party from marketplace; agent loads via Skill tool; lower trust boundary
- **Binding skills** — enforced by ingester denylist, not just instructions; e.g., `no-production-pii`, `never-touch-secrets`

### Layer 3 — Blindspot ledger (queried at phase exit)

A central registry of recurring gotchas. Each agent queries it before emitting completion events.

```
playbooks/blindspots/
├── ledger.yml      # The actual entries
└── protocol.md     # Query protocol (infer context → match → verify)
```

Example entry:

```yaml
- id: mobile-app-icon-missing
  class: missing-asset
  severity: p1
  agents: [builder, shipper]
  tags: [mobile, ios, app-store]
  symptom: "App Store rejects submission for missing 1024x1024 icon"
  detection_rule: "Check assets/icons/ for 1024x1024 PNG; fail if absent"
  remediation: "Generate icon set before ship phase"
```

Before emitting `build.completed`, Builder:

1. Reads `playbooks/blindspots/ledger.yml`
2. Infers context tags from project (mobile, observability, privacy)
3. Matches entries where agent matches OR tags overlap
4. Runs each entry's `detection_rule` against current state
5. Includes `blindspot_check: {unresolved: []}` in completion payload (empty = gate passes)

Phase gates BLOCK if `unresolved != []`.

---

## 13. Substrate

Self-hosted on a Mac mini. Doug's PII never leaves his hardware.

### Components

| Component | Tool | Why |
|---|---|---|
| Service manager | launchd (macOS) | Native, reliable, KeepAlive |
| Database | SQLite | Single file, ACID, zero ops |
| HTTPS tunnel | Cloudflare Tunnel | If external webhooks needed |
| Agent runtime | Claude Code CLI | Per-agent isolated sessions |

### launchd services

```
launchd/
├── com.applaunchpad.orchestrator.plist
└── com.applaunchpad.slack_bot.plist
```

Sample:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<plist version="1.0">
<dict>
  <key>Label</key><string>com.applaunchpad.orchestrator</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/local/bin/python3</string>
    <string>-m</string>
    <string>orchestrator.orchestrator</string>
    <string>run</string>
  </array>
  <key>WorkingDirectory</key>
  <string>/Users/dmorrow/Desktop/projects/AppLaunchpad</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>/usr/local/bin:/usr/bin:/bin:/Users/dmorrow/.local/bin</string>
    <key>PYTHONPATH</key>
    <string>/Users/dmorrow/Desktop/projects/AppLaunchpad</string>
  </dict>
  <key>StandardOutPath</key><string>.logs/orchestrator.stdout.log</string>
  <key>StandardErrorPath</key><string>.logs/orchestrator.stderr.log</string>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
</dict>
</plist>
```

Load with: `launchctl bootstrap gui/$UID launchd/com.applaunchpad.orchestrator.plist`

---

## 14. Tools & Tech Stack

| Layer | Tool | Purpose |
|---|---|---|
| Agent runtime | Claude Code CLI | Spawn isolated agent sessions; tool use + skills + MCP |
| Event store | SQLite | Append-only events + projections; single file |
| Event payloads | Pydantic | Typed schemas with `schema_version` for evolution |
| Knowledge | Obsidian-compatible markdown + YAML frontmatter | Per-project vault; no Obsidian instance needed |
| Wiki-links | `[[name]]` syntax | Knowledge graph navigation |
| Service mgmt | launchd (macOS) | Orchestrator + slack_bot as daemons |
| Slack listener | `slack_sdk` + Socket Mode | Receive messages + button clicks |
| Slack send | `slack_sdk` WebClient | Post notifications, threads, buttons |
| Per-agent overlay | MCP servers | Runtime tools per agent (Playwright, Context7, etc.) |
| Skills | Audited + plugin + binding | Layered trust model |
| Hooks | `.claude/settings.json` PreToolUse / PostToolUse / Stop | Deterministic guardrails |
| Blindspot ledger | `playbooks/blindspots/ledger.yml` | Phase-exit quality check |
| Tunneling | Cloudflare Tunnel | If external webhooks needed |
| Language | Python 3.11+ | stdlib + select packages; no heavy framework |

Notably absent (intentional):

- **No web framework** (FastAPI/Flask) for orchestrator — it's a polling loop, not a server
- **No message queue** — SQLite + pull-based polling is sufficient at this scale
- **No cloud Managed Agents** — self-hosted only; secrets stay local
- **No Kubernetes / containers** — launchd is enough for a solo developer

---

## 15. Build Order (Suggested Sequence)

When replicating from scratch, build in this order. Each step is verifiable before moving on.

1. **Event store** (`core/decision_tracker/`)
   - SQLite schema with `events` + projection tables
   - `emit()` API + `@on_event` decorator
   - Test: emit a hand-crafted event; verify projection updates

2. **Event taxonomy** (`docs/event-taxonomy.md`)
   - Define 5-10 starter event types with Pydantic schemas
   - Document idempotency strategy
   - Test: parse + validate sample events

3. **First agent** (`teams/research/scout/`)
   - `CLAUDE.md` with the 10 mandatory sections
   - `agent-card.json` with capabilities + routing
   - `knowledge/` with reference material
   - Test: launch manually via `claude -p "<scout prompt>"`; verify it reads CLAUDE.md and emits the right events

4. **Vault template** (`templates/project-vault/`)
   - Starter directory structure (00-06 + agents + templates)
   - Standard templates (problem-statement, decision-record, task-card)
   - Frontmatter conventions
   - Test: instantiate for a fake project; verify directory layout

5. **Hooks layer** (`.claude/settings.json`)
   - PreToolUse for secrets (`block-secrets.py`)
   - PostToolUse for format/lint (per-language)
   - SessionStart for context loading
   - Test: trigger each hook with a representative tool call

6. **Orchestrator skeleton** (`orchestrator/`)
   - `router.py` with 3 queries (unprocessed_ideas, pending_gates, approved_gates_needing_teams)
   - `actions.py` with 4 emitters (submit_idea, approve/reject_gate, terminate_project)
   - `runner.py` to spawn Claude Code subagents
   - Main loop polling every 30s
   - Test: manually emit `idea.submitted`; verify orchestrator launches Scout

7. **Second agent** (`teams/planning/architect/`)
   - Same pattern as Scout
   - Triggered by Scout's `research.completed`
   - Test: end-to-end from idea → Scout → Architect handoff

8. **Slack integration** (`orchestrator/slack_bot.py` + `slack_notify.py`)
   - Socket Mode listener for messages + button clicks
   - Notification dispatch for gates + errors
   - Test: post to a test channel; click button; verify event emission

9. **Ingester** (`core/ingester/`)
   - Parser for 5-10 starter event types
   - Filesystem watcher
   - Denylist enforcement
   - Test: add a vault file; verify event emitted with correct idempotency

10. **Remaining agents** (Builder, QA, Auditor, Verifier, Shipper)
    - One at a time; each adds a phase
    - Builder needs subagent-driven-development skill for parallel workstreams
    - QA emits qa.failed → Builder relaunched with feedback (idempotent loop, max 3x)
    - Auditor + Verifier are async reviewers — filter from main pipeline router

11. **Blindspot ledger** (`playbooks/blindspots/`)
    - `ledger.yml` with 5-10 starter entries
    - Each agent's CLAUDE.md gets the Blindspot Query Protocol section
    - Test: add a blindspot; verify Builder fails its gate when matched

12. **Cockpit** (`core/cockpit/`)
    - Flask app reading from SQLite
    - Pipeline status view
    - Event log tail
    - Test: launch in browser; verify reflects current pipeline state

13. **launchd services** (`launchd/`)
    - Orchestrator plist
    - Slack bot plist
    - Test: `launchctl bootstrap`; verify auto-restart on crash

14. **First end-to-end run**
    - Submit an idea via Slack
    - Watch it flow through all phases
    - Approve gates manually
    - Capture lessons → blindspots → next iteration

---

## 16. Gotchas & Hard-Won Lessons

These are not theoretical — they're lessons from AppLaunchpad's evolution.

1. **Don't push from orchestrator. Always pull.** Push-based coordination creates race conditions and tight coupling. Pull-based scales to N agents trivially.

2. **Async reviewers must be filtered from the main pipeline router.** Auditor, verifier, retrospective run alongside the pipeline, not in it. If they're in `next_team`, they'll block the main flow.

3. **One team = one mission.** When a team starts doing two things, split it. The cost of splitting is always lower than the cost of a bloated team.

4. **90/10 planning ratio.** Every agent spends 90% planning, 10% implementing. If an agent is implementing without a written plan, stop it and force planning.

5. **Vault is the knowledge channel, NOT event payloads.** Events carry state transitions; the vault carries context. Downstream agents read vault files, not event payloads.

6. **Idempotency is non-negotiable.** Every event needs an idempotency key. Backfill, retries, and re-runs MUST be safe.

7. **Blindspot check before EVERY phase exit.** Don't just write "remember to check icons" — encode it as a YAML entry with a `detection_rule` and make it block the gate.

8. **Don't trust agent claims — verify.** Add a `verification-before-completion` skill to every agent that emits `task.completed`. Run the test, read the file, confirm the artifact exists.

9. **Hooks > instructions.** Anything that must always happen gets a hook. Instructions are suggestions.

10. **Slack channel proliferation is real.** 6 channels per tenant × 10 tenants = 60 channels. Consider cross-tenant channels with title prefixes (e.g., `#alerts` with `[swt]` / `[appname]` prefixes) instead.

11. **Builder-QA must be a tight idempotent loop.** QA failures route back to Builder with specifics. Max 3 retries; then escalate to human. Each retry resets the state cleanly.

12. **Token-tracking is a future feature, not a budget constraint.** Surface usage as data when relevant, but don't optimize for token cost — optimize for correctness.

13. **Restart from scratch is cheap; learnings persist.** Don't be precious about the implementation. Memory of what worked is the asset.

14. **Strict per-project key isolation.** Secrets never cross tenant boundaries. CLI masked entry. Environment filtering in subprocess.Popen.

15. **`.env` is sacred.** Never read it. Use `os.environ.get()` exclusively. Backup with PreToolUse hook denying file access to anything matching `.env*`.

---

## 17. Scale Triggers (When to Split the Monorepo)

Start as a monorepo. The system emits `system.health_check` events weekly with these metrics. When ANY crosses threshold, evaluate splitting.

| Trigger | Threshold | What it means |
|---|---|---|
| Context saturation | A team's CLAUDE.md + src/ + core/ > 60% of model context window | Team is too big; split or extract shared infra |
| CI duration | Full suite > 10 min, or single team > 2 min | Teams need independent CI/CD |
| Cross-team commits | > 25% of commits touch multiple teams | Boundaries are wrong; extract shared dep |
| Team count | Warning at 30 active teams, review at 50 | Monorepo navigation degrades |
| Contributors | > 3 humans | Social complexity exceeds monorepo |
| Deploy independence | Any team deploys to different target than monorepo default | Team needs own CI/CD config |

### Migration procedure

1. Extract team directory → new repo `<org>/team-<name>`
2. Publish shared infra (`core/decision_tracker`, `core/team_sdk`) as installable Python package
3. Publish event schemas as separate package
4. Update orchestrator to discover teams from service catalog (registry) instead of filesystem scan
5. Update team's CLAUDE.md to reference packaged core
6. Event store remains shared (path is config, not hard-coded)

Migrate incrementally — extract the most independent team first.

---

## 18. AppLaunchpad Source Paths (Cross-Reference)

For replicators who want to look at the actual implementation:

| Concern | File |
|---|---|
| Methodology | `AGENT_TEAM_OS.md` (1200 lines, 10 principles + 7 org principles + 6 phases) |
| Event schema | `docs/event-taxonomy.md` (15 event types, payload schemas, idempotency) |
| Event store | `core/decision_tracker/schema.py`, `events.py`, `db.py`, `queries.py` |
| Orchestrator | `orchestrator/orchestrator.py`, `router.py`, `actions.py`, `runner.py` |
| Slack | `orchestrator/slack_bot.py`, `slack_notify.py` |
| Ingester | `core/ingester/parser.py`, `watcher.py`, `frontmatter_schemas.py`, `denylist.py` |
| Cockpit | `core/cockpit/cli.py`, `html_render.py` |
| Team template | `teams/_template/CLAUDE.md` |
| Sample agents | `teams/research/scout/`, `teams/planning/architect/`, `teams/build/builder/` |
| Audited skills | `skills-import/audited/` |
| Blindspots | `playbooks/blindspots/ledger.yml`, `protocol.md` |
| Lessons | `playbooks/lessons-learned.md` |
| Hooks | `.claude/settings.json`, `~/.claude/hooks/block-secrets.py` |
| Substrate | `launchd/com.applaunchpad.orchestrator.plist`, `launchd/com.applaunchpad.slack_bot.plist` |
| Vault template | `templates/project-vault/` |

---

## Closing Notes

This architecture is **opinionated** in service of one workflow: a solo developer who wants AI agents to take ideas through research → blueprint → build → ship with minimal but meaningful human oversight. The opinions are:

- **Pull over push** — eliminates entire classes of bugs
- **Event sourcing over CRUD** — makes audit + replay free
- **Markdown vault over database for knowledge** — agents read each other naturally
- **Slack over web UI** — already where the human lives
- **Self-hosted over cloud** — secrets stay local
- **Skills + hooks over instructions** — deterministic where it matters
- **Blindspots as data, not docs** — queryable, executable, projection-ready
- **90/10 planning** — words are cheap, code is expensive

Adapt freely. The principles are the load-bearing parts; the implementation is just one path.
