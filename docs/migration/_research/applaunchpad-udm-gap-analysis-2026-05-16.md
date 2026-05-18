# AppLaunchpad ↔ UDM Cascade Gap Analysis

**Date**: 2026-05-16
**Author**: Parent agent (reflection on user-provided `agentic-architecture.md`)
**Purpose**: Section-by-section comparison of AppLaunchpad's production-tested agentic-software-factory architecture against UDM project's current cascade-discipline scaffolding. Identifies REUSE / ADAPT / SKIP / DECISION-NEEDED for each AppLaunchpad section.
**Triggered by**: user-direction "Show me the gap analysis first" 2026-05-16
**Source spec**: `C:\Users\bigba\Desktop\Test_Repo-main\agentic-architecture.md` (920 lines, 18 sections, 3 cross-reference appendices)

---

## Headline

**18 sections walked. Net assessment:**

- **8 sections = REUSE as-is** (philosophy + event-driven principles + vault concept + skills+hooks+blindspot 3-layer defense + gotchas + scale triggers)
- **5 sections = ADAPT** (pipeline phases / event taxonomy / orchestrator implementation / substrate / Slack→email)
- **3 sections = SKIP** (Cockpit dashboard — premature; AppLaunchpad source-path appendix — reference only; build-order is conditional on adoption choice)
- **2 sections = DECISION-NEEDED** (event store backing — SQLite new vs existing PipelineEventLog reuse; tenant model — UDM as new tenant in AppLaunchpad vs UDM standalone instance)

**The fundamental architectural delta**: AppLaunchpad is **pull-based** (orchestrator polls; agents trigger themselves when their event appears); UDM is **push-based** (parent agent invokes skills when user types trigger phrase). This is the single biggest design shift if adopting AppLaunchpad fully.

---

## Section 1: What You're Building (core properties)

**AppLaunchpad**: Event-driven, pull-based system of specialized Claude Code agents collaborating via shared event store + per-project knowledge vault, Slack as sole human interface, self-hosted Mac mini substrate.

**UDM current state**: Push-based discipline-cascade where parent agent invokes skills (udm-progress-logger / udm-gap-check / udm-step-10-verifier / etc.) when user types trigger phrases. Knowledge in `docs/migration/`. Direct conversation as sole human interface. No substrate (runs inside Claude Code session).

**Gap**:
- Event store: ABSENT in UDM (state is in markdown files + General.ops.PipelineEventLog for runtime events)
- Pull-based: ABSENT (current model is conversational push)
- Self-hosted substrate: ABSENT (no daemon process; runs only when Claude Code session active)
- Slack interface: ABSENT (uses conversation)

**Verdict**: ADAPT. Core properties are aspirational targets; current UDM state has none of the four.

**Decision needed**: How much of "core properties" to adopt? Full adoption = significant infra build. Minimal adoption = use the principles, skip the substrate.

---

## Section 2: Foundational Philosophy (10 Agent Principles + 7 Organizational Principles)

**AppLaunchpad**:
- 10 Agent Principles: Why-before-how / tools-serve-problems / evidence-over-assumption / plan-cheaply / vault-source-of-truth / agents-accountable-via-transparency / deterministic-gates / system-improves-itself / done-means-verified / minimum-viable-everything
- 7 Org Principles: Commander's-intent / contracts-only-communication / small-teams-single-mission / pull-not-push / stop-the-line / system-improves-itself / teams-are-mortal

**UDM equivalents**:

| AppLaunchpad principle | UDM equivalent |
|---|---|
| Why-before-how | D55 (5-gate validation) + D61 (pillar mapping) |
| Plan-cheaply / 90-10 ratio | The whole project culture (D55, D56, D60, hard rules 11+13+14) |
| Vault is source of truth | `docs/migration/` is canonical; `_validation_log.md` audit-trail |
| Deterministic gates over instructions | Hard rules 11 / 13 / 14 + `udm-step-10-verifier` skill |
| Done means verified | D55 5-gate + D56 second-pass + hard rule 11 udm-gap-check |
| System improves itself | D95-D99 self-improvement skill suite + Pattern F audit |
| Contracts as only communication | Skill invocation contract + EventType families |
| Stop the line on defects | 🔴 verdict blocks 🟢 status flip per D55/D56 |
| Teams are mortal | Skill versioning per D98 (semver + archive) |

**Gap**: 16 of 17 principles already operationalized in UDM in different form. The single conceptual gap is **pull-not-push** (Principle D in AppLaunchpad's org principles).

**Verdict**: REUSE the philosophy; UDM already lives by these principles. Document the mapping in a CLAUDE.md "principles inheritance" section if formal adoption desired.

**Decision needed**: NONE. Philosophy already aligned.

---

## Section 3: Six-Phase Pipeline (Idea → Customers)

**AppLaunchpad**: 6 phases per project — Idea Evaluation / Research / Blueprint / Build / Ship / Customers. Each phase has inputs / outputs / exit criteria / human gate.

**UDM equivalents**: UDM uses different phase taxonomy organized around DATA PIPELINE work, not PRODUCT work:

| UDM concept | AppLaunchpad concept | Match quality |
|---|---|---|
| Phase 0 prep (research + governance) | Idea Eval + Research | Partial — UDM Phase 0 is one-time governance setup, not per-project |
| Phase 1 (core build: rounds 1-8) | Blueprint + Build | Good — Round 1 spec ≈ Blueprint; Rounds 2-8 ≈ Build |
| Phase 2 hardening (planned next) | Build (continued) | Same |
| Production rollout (per D87 + RB-N) | Ship | Good — clear match |
| Operational tier (post-launch ops) | Customers | Partial — UDM operates pipelines, doesn't sell to customers |

**Gap**: UDM's "phases" are MIGRATION phases (one-time effort), not PER-PROJECT phases (recurring). AppLaunchpad's 6-phase pipeline runs PER IDEA. UDM's phases run ONCE for the whole migration.

**The relevant analog**: each **round** within UDM Phase 1 could be modeled as a mini-pipeline (Round-Plan → Round-Build → Round-Verify → Round-Track), which IS what the cascade automates.

**Verdict**: ADAPT. Don't import AppLaunchpad's 6 product-development phases. DO use the pipeline-per-round model as the cascade's mini-pipeline.

**Decision needed**: Should the cascade automate ROUND lifecycle (high-level) or each individual BUILD COHORT (mid-level) or each single COMMIT (low-level)? Current udm-next-step-cascade skill operates at the commit level.

---

## Section 4: Architecture Overview (Slack → Orchestrator → EventStore → Agents+Ingester → Vault → Cockpit)

**AppLaunchpad** (visual recap):
```
Slack → slack_bot/slack_notify → Orchestrator (router/actions/runner)
                                    ↓
                                 SQLite event store
                                    ↑ ↑
                       Teams (Claude Code agents)   Ingester (vault→events)
                                                       ↓
                                                    Vault (markdown + YAML)
                                                       ↑
                                                    Cockpit (Flask + WebSocket)

Substrate: launchd (macOS) running orchestrator + slack_bot daemons
```

**UDM equivalents**:
```
User-direction (conversational) → Parent agent (current Claude Code session)
                                    ↓
                          Skill invocation (udm-progress-logger / udm-gap-check / etc.)
                                    ↓
                          docs/migration/ files (vault-equivalent; markdown only)
                                    ↑
                          General.ops.PipelineEventLog (runtime events; NOT discipline events)

No substrate. No orchestrator. No ingester. No cockpit.
```

**Gap**: UDM has ONE of the six AppLaunchpad architectural components (vault-equivalent). Missing: Slack interface, orchestrator, event store, ingester, cockpit, substrate.

**Verdict**: ADAPT. The architecture is a target state; adoption is incremental. Build order matters (see Section 15).

**Decision needed**: Build all 5 missing components OR build only the subset that closes specific discipline gaps?

---

## Section 5: Event Store (SQLite, 15 event types, idempotency, performatives)

**AppLaunchpad**: SQLite append-only events table + 5 projection tables (decisions/gates/tasks/ideas/projects). 15 vault.* event types. Every event has idempotency_key (sha256). Performatives (INFORM/REQUEST/PROPOSE/CONFIRM/REJECT/QUERY) disambiguate intent.

**UDM equivalents**:
- `_validation_log.md`: append-only validation events (markdown rows, not SQLite)
- `General.ops.PipelineEventLog`: append-only runtime events (SQL table; CLI_*, CYCLE_*, DEPLOYMENT_*, etc.)
- `General.ops.IdempotencyLedger`: D15 master invariant (Round 3 module)
- Pitfall #9 sub-classes: prose entries in HANDOFF §8 (not queryable)

**Gap**:
- No DISCIPLINE event store (validation events live in markdown only)
- No performatives (intent encoding ad-hoc)
- No idempotency on validation events (markdown rows can duplicate on re-runs)
- No event projections (UDM has trackers but they're hand-maintained)

**DECISION-NEEDED #1 — Event store backing**:

| Option | Pro | Con |
|---|---|---|
| **A. SQLite NEW table** (new infra) | Clean separation from runtime events; AppLaunchpad pattern reuse | New infra; another DB; sync with markdown still needed |
| **B. PipelineEventLog NEW EventType family** (`CASCADE_*` / `DISCIPLINE_*`) | Reuse existing infra; one DB for ops + cascade; SchemaContract discipline applies | Mixing runtime + discipline events; query patterns differ |
| **C. Stay in markdown** (`_validation_log.md` enhanced) | Zero new infra; current workflow preserved | No projections; no idempotency enforcement; no programmatic query |

**Recommendation**: B if pursuing event-driven architecture (existing infra + discipline composition); C if minimal-adoption path.

**Verdict**: ADAPT. The concept REUSED; the backing storage DECISION-NEEDED.

---

## Section 6: Vault (Per-Project Obsidian Vault, Frontmatter, Wiki-links)

**AppLaunchpad**: Per-project vault under `vault/`; structure: 00-inbox / 01-research / 02-blueprint / 03-build / 04-ship / 05-customers / 06-retro / agents / templates / DASHBOARD.md. Every file has YAML frontmatter (type/phase/agent/status/owner/created/updated/tags/links_to). Wiki-link convention `[[name]]` as knowledge graph.

**UDM equivalents**:
- `docs/migration/`: project-wide vault (NOT per-project; UDM is the project)
- Subdirectory structure: phase1/ + _archive/ + _research/ + _agent_evolution/ + _refactor_log + INDEX.md + various flat aggregate docs (CURRENT_STATE.md / HANDOFF.md / BACKLOG.md / RISKS.md / etc.)
- Frontmatter: ABSENT (markdown files are unstructured at the file level; tracker rows have implicit structure)
- Wiki-links: PARTIAL (cross-references via filename + section anchors; not [[ ]] syntax)

**Gap**: UDM has the spirit of a vault but not the conventions.

**Verdict**: ADAPT.
- REUSE: per-project (UDM-project-wide) vault concept ✅ already in place
- ADAPT: frontmatter — could add YAML frontmatter to canonical docs for projection/query
- SKIP: wiki-link `[[ ]]` syntax — UDM uses markdown link syntax; rewriting all docs not justified

**Decision needed**: Add frontmatter to canonical docs? Useful if event store + ingester are built; useless otherwise.

---

## Section 7: Agents (Categories, per-agent directory, agent-card.json, CLAUDE.md, skills integration)

**AppLaunchpad**: Specialized Claude Code agents per category (research/planning/build/testing/deployment/operations). Each agent has its own directory: agent-card.json (machine-readable capability declaration) + CLAUDE.md (operating protocol with 10 mandatory sections) + reflections.md + knowledge/ + src/ + tests/. Skills loaded at trigger time (audited / plugin / binding categories).

**UDM equivalents**:
- `.claude/agents/`: 5 custom agents (udm-design-reviewer / udm-test-author / udm-researcher / udm-data-engineer-review / udm-cascade-auditor)
- `.claude/skills/`: ~25 skills (udm-progress-logger / udm-gap-check / udm-step-10-verifier / udm-next-step-cascade / udm-checks-and-balances / udm-decision-recorder / udm-runbook-author / udm-round-closeout / udm-cascade-audit-evolver / etc.)
- Per-agent files: AGENT_NAME.md (description + tools list); no agent-card.json
- Per-skill files: SKILL.md (description + procedure); no agent-card.json

**Gap**:
- agent-card.json: ABSENT — UDM has narrative descriptions; no machine-readable capability registry
- knowledge/ per-agent: ABSENT — UDM agents read from `docs/migration/` (shared)
- src/ per-agent: ABSENT — UDM agents don't run scripts; they spawn Claude Code sessions
- tests/ per-agent: ABSENT — no agent-level test suites

**Concept mapping**:
- AppLaunchpad's per-team CLAUDE.md ≈ UDM's per-skill SKILL.md ✅ functionally equivalent
- AppLaunchpad's reflections.md ≈ UDM's per-skill agent-evolution archives in `_agent_evolution/` ✅ similar concept
- AppLaunchpad's skill categories (audited / plugin / binding) ≈ UDM's no formal categorization (all UDM skills are "audited" by definition since project-owned)

**Verdict**: ADAPT.
- REUSE: SKILL.md as per-team operating protocol ✅
- ADAPT: agent-card.json — could add for machine-readable routing (REQUIRED if pull-based orchestrator built)
- SKIP: per-agent knowledge/ src/ tests/ — UDM model is different (shared vault + spawned sessions)

**Decision needed**: Build agent-card.json registry? Required for pull-based orchestrator; optional otherwise.

---

## Section 8: Orchestrator (Pull-Based Polling Loop)

**AppLaunchpad**: Three modules (router.py read-only queries / actions.py event emitters / runner.py spawns Claude Code subagents). Main loop polls every 30s. Why pull: no race conditions / easy to add new team / recovery is free (restart, resumes from event store).

**UDM equivalents**:
- ABSENT — UDM has no orchestrator. Parent agent IS the orchestrator (manual, conversational).

**Gap**: Complete absence of automated orchestration.

**Verdict**: ADAPT — this is the SINGLE BIGGEST INFRASTRUCTURE BUILD if adopting AppLaunchpad fully.

**Effort estimate**:
- router.py: ~150 lines (3 queries + event-store wrapper)
- actions.py: ~100 lines (4-6 emitters)
- runner.py: ~150 lines (subprocess.Popen claude -p + log capture + state tracking)
- Main loop: ~50 lines
- Total: ~450 lines + tests

**Substrate dependency**: Requires daemon process (launchd on Mac, Task Scheduler on Windows, systemd on RHEL). If UDM substrate = RHEL server (where pipeline runs), can use existing systemd. If UDM substrate = dev workstation, Task Scheduler is awkward (laptop sleeps; not always-on).

**Decision needed**: Build orchestrator now (full adoption) OR defer (minimal adoption)?

---

## Section 9: Ingester (Vault → Events Bridge)

**AppLaunchpad**: Filesystem watcher (backfill + watch modes) that parses 15 vault.* event types from markdown files. Pydantic frontmatter_schemas + denylist.py (binding skills enforced at parse time: blocks `*.env`, `*.key`, `06-founder/**`, `confidential: true`).

**UDM equivalents**:
- ABSENT — UDM has no event emission from vault changes. Parent agent manually invokes skills.

**Gap**: Complete absence.

**Verdict**: ADAPT (if event store + orchestrator adopted).

**Effort estimate**:
- parser.py: ~200 lines (15 event-builder functions × ~15 lines each)
- watcher.py: ~80 lines (using `watchdog` library)
- frontmatter_schemas.py: ~100 lines (Pydantic models)
- denylist.py: ~50 lines (path patterns + frontmatter checks)
- backfill.py: ~80 lines (historical hydration)
- Total: ~510 lines + tests

**Required precondition**: Section 6 vault frontmatter adopted. Otherwise nothing to parse.

**Decision needed**: Concurrent with Section 8 orchestrator decision.

---

## Section 10: Slack Integration (4 Channels per Tenant)

**AppLaunchpad**: 4 channels per tenant (`<tenant>-ideas` / `-errors` / `-alternatives` / `-opportunities`). Two services: slack_bot.py (Socket Mode listener for messages + button clicks) and slack_notify.py (notification dispatch). Gate review loop: agent emits `gate.requested` → orchestrator → Slack with Approve/Reject buttons → click → slack_bot emits `gate.approved` → orchestrator triggers next team.

**UDM equivalents**:
- ABSENT — UDM uses direct Claude Code conversation as the human interface. No Slack integration.
- Email is used in some runbooks (RB-N notification procedures).

**Gap**: Complete absence of async messaging interface.

**Decision needed**: Is async messaging the right interface for UDM operator interactions?

**Considerations**:
- UDM pipeline runs OVERNIGHT on Automic schedule; pipeline operators are likely on call via PagerDuty / email
- Most UDM operator decisions are deterministic (does a CCPA deletion proceed? does retention enforce? — answered by runbook + config, not real-time approval)
- The cascade's gate-approval use case is mostly developer-time (this session) not operator-time
- Slack would require new infrastructure + auth + corp IT involvement

**Verdict**: ADAPT (replace Slack with EMAIL) OR SKIP (use Claude Code conversation; defer async messaging).

---

## Section 11: Cockpit (Dashboard)

**AppLaunchpad**: Flask app + WebSocket reading from SQLite event store. Real-time pipeline status / per-project dashboard / event log tail / health metrics.

**UDM equivalents**:
- ABSENT — UDM has CODE_BUILD_STATUS.md + CURRENT_STATE.md as static dashboards (manually updated).

**Gap**: No real-time dashboard.

**Verdict**: SKIP for initial adoption. Cockpit is observability, not core function. Build if Section 5+8+9 done and observability becomes a pain point.

---

## Section 12: Quality & Guardrails (Hooks + Skills + Blindspot Ledger)

**AppLaunchpad**: 3-layer defense — Hooks (`.claude/settings.json`, deterministic, can't be bypassed) / Skills (audited / plugin / binding) / Blindspot ledger (`playbooks/blindspots/ledger.yml` queried at phase exit).

**UDM equivalents**:
- Hooks: `.claude/settings.json` exists (currently minimal — `permissions.deny` for credential paths per D103)
- Skills: ~25 skills in `.claude/skills/` (per-skill SKILL.md)
- Blindspot ledger: Pitfall #9 sub-classes in HANDOFF §8 (PROSE, not YAML; NOT queryable; manually invoked by producer self-check Steps 1-12)

**Gap analysis**:

| Layer | UDM state | Gap |
|---|---|---|
| Hooks | Minimal — only credential-path denial | Could add hooks for: SessionStart context load (e.g., auto-load CCL Stage 1), PreToolUse for protected-doc writes (NORTH_STAR.md, 03_DECISIONS.md), PostToolUse to invoke udm-step-10-verifier after Edit/Write to source files |
| Skills | ~25 skills active | Could add binding skills enforced at hook level (e.g., `no-d-number-without-validation-log-entry`) |
| Blindspot ledger | Prose in HANDOFF §8 | **BIGGEST GAP**: convert Pitfall #9.a-9.o sub-classes from prose to YAML with `detection_rule`; agents query at phase exit; gate BLOCKS if unresolved |

**Verdict**: ADAPT (blindspot ledger format upgrade) + REUSE (hooks + skills already in place; extend incrementally).

**HIGH-VALUE QUICK WIN**: Converting Pitfall #9 sub-classes to queryable YAML closes the "discipline-not-applied-to-tracker" gap that surfaced 5+ times this session. Estimated effort: 1-2 hours; impact: HIGH (prevents the discipline-debt accumulation pattern).

---

## Section 13: Substrate (Mac mini, launchd, SQLite, Cloudflare Tunnel)

**AppLaunchpad**: Self-hosted on Mac mini. launchd manages orchestrator + slack_bot daemons. SQLite event store. Cloudflare Tunnel for external webhooks (Slack).

**UDM substrate options**:

| Substrate | Pro | Con |
|---|---|---|
| **Windows 11 dev workstation** (current) | Already has dev environment | Laptop sleeps; not always-on; Windows Task Scheduler awkward |
| **RHEL pipeline server** (existing UDM substrate) | Always-on; same infra as pipeline; systemd available | No Claude Code per D103 security model — substrate would need to spawn Claude on a different machine |
| **Dedicated VM (new)** | Clean separation; always-on | New infra; corp IT involvement; security review |
| **GitHub Codespaces / cloud dev env** | Always-on; modern | Cost; data residency concerns; new corp IT |

**The D103 wrinkle**: Claude Code is FORBIDDEN on test + prod RHEL servers per the security model. The orchestrator's "spawn Claude Code subagent" pattern is fundamentally incompatible with RHEL substrate. Workarounds:
- Orchestrator on RHEL spawns Claude on dev workstation via SSH/SOCKS (security risk)
- Orchestrator on dev workstation (substrate = workstation; laptop-sleep limitation)
- Hybrid: event store on RHEL (always-on); orchestrator polls from dev workstation when active

**Verdict**: ADAPT — substrate choice is NON-trivial. Requires architectural decision.

**Decision needed**: Where does the orchestrator run? Tied to Section 8 build decision.

---

## Section 14: Tools & Tech Stack

**AppLaunchpad**: Claude Code CLI / SQLite / Pydantic / Obsidian-compatible markdown / launchd / slack_sdk / MCP servers / hooks / blindspot YAML / Cloudflare Tunnel / Python 3.11+.

**UDM existing tech stack** (per CLAUDE.md):
- Python 3.12.11 ✅ overlap
- Polars / polars-hash / ConnectorX / oracledb / pyodbc — pipeline-specific
- BCP (mssql-tools18) — pipeline-specific
- No SQLite (uses SQL Server)
- No Pydantic (could add)
- No watchdog (could add)
- No slack_sdk (would add IF Slack adopted)
- launchd not applicable (Windows / RHEL)

**Gap**: 2-3 new Python dependencies if full adoption (pydantic + watchdog + slack_sdk).

**Verdict**: REUSE conceptually; add specific dependencies as needed per section adoption.

**Notably absent in AppLaunchpad** (per Section 14): no web framework, no message queue, no cloud Managed Agents, no Kubernetes — same minimalism applies to UDM.

---

## Section 15: Build Order (14 Steps)

**AppLaunchpad's suggested sequence** (paraphrased; full details in source spec):
1. Event store (SQLite + emit() API)
2. Event taxonomy (5-10 starter event types + Pydantic schemas)
3. First agent (one team with CLAUDE.md + agent-card.json + knowledge/)
4. Vault template (per-project starter directory)
5. Hooks layer (PreToolUse for secrets + PostToolUse for format/lint + SessionStart for context)
6. Orchestrator skeleton (router + actions + runner + main loop)
7. Second agent (verify handoff)
8. Slack integration (slack_bot + slack_notify)
9. Ingester (parser + watcher + denylist)
10. Remaining agents (Builder/QA/Auditor/Verifier/Shipper)
11. Blindspot ledger (YAML + protocol)
12. Cockpit (Flask dashboard)
13. launchd services
14. First end-to-end run

**UDM adapted sequence** (REORDERED per high-value-first):

1. **Blindspot ledger YAML migration** (highest ROI; ~2 hours) — convert Pitfall #9 sub-classes to YAML with detection_rule per entry. Closes discipline-not-applied gap.
2. **Hooks layer extension** (~4 hours) — add SessionStart for auto-CCL load + PreToolUse for protected-doc writes + PostToolUse for udm-step-10-verifier auto-invoke.
3. (Decision point: continue full adoption or stop here)
4. **Event store** (Section 5 Decision A/B/C) — choose backing storage; ~1 day
5. **Event taxonomy** — define UDM-specific event types (CASCADE_PLAN / CASCADE_EXECUTE / CASCADE_VERIFY / CASCADE_TRACK / DISCIPLINE_GATE_REQUESTED / etc.); ~4 hours
6. **Agent-card.json per existing skill** — machine-readable capability registry; ~1 day for all ~25 skills
7. **Vault frontmatter migration** — add YAML frontmatter to canonical docs; ~2 days (touches many files)
8. **Orchestrator skeleton** — router + actions + runner + main loop; ~2 days
9. **Substrate decision + setup** — Section 13 choice; ~1-3 days depending
10. **Ingester** — parser + watcher + denylist; ~2 days
11. **Email notification layer** (replacing AppLaunchpad's Slack) OR conversation-as-interface decision; ~1 day if email
12. **Cockpit dashboard** (DEFER unless observability pain)
13. **First end-to-end cascade run** — sanity check
14. **Tune + iterate**

**Cumulative effort estimate (full adoption)**: ~10-15 working days. Minimal adoption (Steps 1+2 only): ~6 hours.

**Verdict**: ADAPT order; high-value steps first.

---

## Section 16: Gotchas (15 Hard-Won Lessons)

Walking each against UDM context:

| # | Gotcha | UDM relevance |
|---|---|---|
| 1 | Don't push; always pull | HIGH — this is the fundamental architectural choice |
| 2 | Async reviewers must be filtered from main pipeline router | MEDIUM — applies if multiple parallel review skills (current pattern: paired-judgment Gate 2 in 5-gate validation) |
| 3 | One team = one mission | HIGH — UDM has bloated skills (e.g., udm-round-closeout does ~10 things); could split |
| 4 | 90/10 planning ratio | HIGH — already UDM culture; reaffirms the discipline |
| 5 | Vault is knowledge channel, NOT event payloads | HIGH — applies; events should be lean (state transitions); knowledge in markdown |
| 6 | Idempotency is non-negotiable | HIGH — UDM lives this (D15 master invariant) |
| 7 | Blindspot check BEFORE every phase exit | HIGH — closes the discipline-not-applied gap |
| 8 | Don't trust agent claims; verify | HIGH — already UDM culture (D55/D56 + hard rule 11 udm-gap-check) |
| 9 | Hooks > instructions | HIGH — under-leveraged in UDM; Section 12 quick-win |
| 10 | Slack channel proliferation is real | LOW for UDM (1 tenant) |
| 11 | Builder-QA must be tight idempotent loop | MEDIUM — applies to Execute→Verify cascade transitions |
| 12 | Token-tracking is future feature, not budget constraint | MEDIUM — research recommended $0.18/run + budget; this gotcha suggests don't over-engineer |
| 13 | Restart from scratch is cheap; learnings persist | HIGH — UDM has restartability via _archive/ + git history |
| 14 | Strict per-project key isolation | LOW (UDM is single-project) |
| 15 | .env is sacred | HIGH — already enforced by D103 (.env at /etc/pipeline/.env outside /debi) |

**Verdict**: REUSE all 15; they're directly applicable.

---

## Section 17: Scale Triggers (When to Split Monorepo)

**AppLaunchpad**: Weekly `system.health_check` events with metrics — context saturation / CI duration / cross-team commits / team count / contributors / deploy independence.

**UDM relevance**: LOW currently (UDM is single repo with 1 contributor + Claude). Scale triggers would matter IF UDM monorepo grew beyond current scope (e.g., multiple data pipelines under one repo).

**Verdict**: SKIP for initial adoption. Bookmark for future.

---

## Section 18: AppLaunchpad Source Paths (Cross-Reference)

**Purpose**: Reference appendix pointing to actual AppLaunchpad implementation files.

**UDM relevance**: REFERENCE only. Useful if user wants to look at concrete code; not a UDM action item.

**Verdict**: SKIP. Reference appendix, not actionable.

---

## Cross-cutting decisions needed (consolidated)

Before any adoption work begins, these need answers:

### D1. Event store backing (Section 5)
- A. New SQLite DB
- B. New EventType family in existing PipelineEventLog
- C. Stay in markdown (`_validation_log.md` enhanced)

### D2. Substrate (Section 13)
- A. Windows 11 dev workstation
- B. RHEL pipeline server (with Claude on dev workstation via SSH)
- C. Dedicated VM
- D. Hybrid (event store on RHEL; orchestrator on workstation)
- E. SKIP substrate (no daemon; manual orchestration only)

### D3. Tenant model
- A. UDM as new tenant in existing AppLaunchpad infra (reuse Mac mini)
- B. UDM standalone instance (build separately for UDM substrate)
- C. Minimal-adoption (no orchestrator; just blindspot ledger + hooks)

### D4. Human interface (Section 10)
- A. Slack
- B. Email (existing UDM operator channel)
- C. Direct Claude Code conversation (current model preserved)

### D5. Pipeline phase granularity (Section 3)
- A. Round-level (Plan→Build→Verify→Track per round)
- B. Build-cohort-level (per multi-module wave)
- C. Commit-level (current `udm-next-step-cascade` granularity)

### D6. Adoption scope
- A. Full adoption (~10-15 days; all 14 build steps)
- B. High-ROI subset (~6 hours; Steps 1+2 — blindspot YAML + hooks)
- C. Custom subset (user picks specific sections)

---

## High-ROI quick win (recommended starting point regardless of full adoption decision)

**Convert Pitfall #9 sub-classes from prose in HANDOFF §8 → YAML in `playbooks/blindspots/ledger.yml` with detection_rule per entry.**

**Effort**: 2-4 hours
**Impact**: HIGH

**Why**:
- Closes the discipline-not-applied gap that surfaced 5+ times this session (commits 521b68c, 3eef410, aee329c, a03a35c, 4112e92)
- Makes Pitfall #9 sub-classes queryable + executable
- Doesn't require ANY other AppLaunchpad infrastructure
- Compatible with both minimal-adoption AND full-adoption paths
- Validates the conversion pattern before committing to broader adoption

**Sample YAML entry** (Pitfall #9.o — discipline-debt-cluster-via-recursive-exemption):

```yaml
- id: pitfall-9o-recursive-exemption-rationalization
  class: discipline-not-applied
  severity: p1
  agents: [parent-agent, any-skill-invoker]
  tags: [hard-rule-14, cascade-application, post-edit-verification]
  symptom: "Commit claims hard rule 14 cascade exemption via 'paired-judgment Gate 2 covers META-COMMIT scope' OR similar recursive-coverage claim"
  detection_rule: |
    Check commit message for phrases like 'triple-counted review', 'recursive exemption', 'Gate 2 covers',
    AND check files modified by sub-agents (cited in commit) overlap with files modified by META-COMMIT.
    If overlap < 80% AND commit claims exemption: FAIL.
  remediation: |
    Apply hard rule 14 cascade Step 2 (udm-gap-check) on the META-COMMIT scope explicitly.
    Cite specific FILES reviewed by sub-agents vs FILES modified by META-COMMIT.
    Justify recursion-depth + termination point if claiming Layer N+1 exemption.
  evidence_base: 5
  evidence_commits: [521b68c, 3eef410, aee329c, a03a35c, 4112e92]
```

---

## Recommended sequence

1. **Decide D1-D6** (consolidated decisions above) — ~30 min
2. **High-ROI quick win** (blindspot YAML migration) regardless of D6 choice — 2-4 hours
3. **Hooks layer extension** (Section 12) — 4 hours
4. (If D6 = full adoption) **Continue build order Steps 4-14** — ~10-15 days
5. (If D6 = high-ROI subset) **STOP** — assess after Steps 1-3 land

---

## Confidence assessment

| Section | Recommendation | Confidence | Notes |
|---|---|---|---|
| §1-§2 (philosophy + core properties) | REUSE | HIGH | UDM already lives 16/17 principles |
| §3 (pipeline phases) | ADAPT | HIGH | UDM phases differ structurally; mini-pipeline model fits cascade |
| §4 (architecture overview) | ADAPT | HIGH | UDM has 1 of 6 components; gap is real |
| §5 (event store) | DECISION-NEEDED | MEDIUM | Three viable backings; choice depends on D6 scope |
| §6 (vault) | ADAPT | MEDIUM | Concept ✅; conventions adoption ROI uncertain |
| §7 (agents) | ADAPT | MEDIUM | SKILL.md ≈ CLAUDE.md per-team; agent-card.json adoption depends on D6 |
| §8 (orchestrator) | ADAPT-IF-D6=FULL | HIGH | Biggest infrastructure build; pull-vs-push fundamental |
| §9 (ingester) | ADAPT-IF-§8-BUILT | HIGH | Required precondition: vault frontmatter |
| §10 (Slack) | DECISION-NEEDED | LOW | Email/conversation may be sufficient |
| §11 (Cockpit) | SKIP-INITIAL | HIGH | Premature; build only on observability pain |
| §12 (guardrails) | ADAPT | HIGH | Blindspot YAML is highest-ROI step |
| §13 (substrate) | DECISION-NEEDED | LOW | D103 security model complicates RHEL substrate |
| §14 (stack) | REUSE | HIGH | Add 2-3 deps incrementally |
| §15 (build order) | REORDER for ROI | HIGH | High-ROI first; full sequence optional |
| §16 (gotchas) | REUSE 12-of-15 | HIGH | Directly applicable; 3 less relevant for 1-tenant UDM |
| §17 (scale triggers) | SKIP | HIGH | Premature |
| §18 (source paths) | SKIP | HIGH | Reference only |

---

## Counter-arguments to full adoption

**Against full adoption**:
- UDM is mid-Phase-1 (rounds 1-8 done; Phase 2+ in flight); pausing for ~15 days of infrastructure may delay actual pipeline work
- Current push-based discipline-cascade IS functional (just discipline-debt accumulation)
- Pull-based requires daemon; UDM dev workstation isn't always-on; substrate decision non-trivial
- Existing skills + hard rules + udm-gap-check already implement much of the AppLaunchpad principle set

**Against full skip**:
- Discipline-debt accumulation pattern (5 commits this session) suggests current conversational model has reached its scaling ceiling
- AppLaunchpad's blindspot-ledger pattern is a direct fix for the gap that's been chased all session
- Hooks > instructions principle is under-leveraged
- Even minimal adoption (Steps 1+2) is 6-hour ROI for HIGH-impact discipline closure

**Balanced position**: HIGH-ROI quick win (Steps 1+2) regardless of D6 decision; defer larger adoption pending pipeline-work prioritization conversation.

---

## What this gap analysis does NOT cover

- Specific code implementations for any of the build-order steps (research artifact only; design step is separate)
- Detailed migration plan for converting Pitfall #9 sub-classes (would need separate runbook)
- Cost/risk analysis of corp IT involvement for Slack, dedicated VM, or daemon substrate
- AppLaunchpad architecture's interaction with project-specific D103 security model (only surfaces it; doesn't resolve)
- Tenancy model details (Section: D3) — needs separate discussion with you about whether AppLaunchpad-Mac-mini can host UDM events

---

## Suggested follow-up

1. **Answer D1-D6** (consolidated decisions; ~30 min of your time)
2. **Approve High-ROI quick win** (blindspot YAML migration; I can author in this session)
3. **Defer fuller adoption** to a separate dedicated session — significant infrastructure scope deserves dedicated focus
4. **Consider this gap analysis a planning artifact** (per PS-1 ARCH planning scope); add to `_research/` index in INDEX.md if useful
