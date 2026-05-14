# UDM Pipeline — Maintenance Practices

This document covers ongoing practices for keeping the pipeline, the documentation, and the audit posture healthy after the migration phases complete.

## Documentation maintenance

### Ownership

| Document | Primary owner | Review cadence |
|---|---|---|
| `00_OVERVIEW.md` | Pipeline lead | Quarterly |
| `01_ARCHITECTURE.md` | Pipeline lead | Quarterly + on architectural change |
| `02_PHASES.md` | Project manager | Weekly during active phase; monthly after Phase 6 |
| `03_DECISIONS.md` | Pipeline lead | On decision; never deleted, only superseded |
| `04_EDGE_CASES.md` | Pipeline lead | On new edge case discovery |
| `05_RUNBOOKS.md` | Operations lead | After each runbook execution; quarterly review |
| `06_TESTING.md` | QA lead | When test strategy changes |
| `07_LOGGING.md` | Pipeline lead | When logging schema changes |
| `08_HEALTH_CHECKS.md` | (TBD when Phase 6 begins) | TBD |
| `09_VISUALS.md` | Pipeline lead | When architecture changes |
| `CURRENT_STATE.md` | Whoever is actively working | Updated every session |
| `phase{N}/00_phase_overview.md` | Phase lead | At phase start + at phase complete |
| `CLAUDE.md` (root of repo) | Pipeline lead | After every phase + on operational changes |
| `MAINTENANCE.md` (this file) | Operations lead | Annually |

### Update workflow

1. **Adding a decision**: increment D-number, write rationale, set status to 🟡, capture trade-offs. Lock to 🟢 after sign-off. Never delete superseded decisions; mark ⚫ Superseded with link to replacement.
2. **Adding an edge case**: pick the appropriate series (M/S/I/N/P/G/D/F/V), increment, document mitigation status (✅/🟡/🔴).
3. **Adding a runbook**: increment RB-number, document When/Pre-flight/Procedure/Validation/Rollback. Test in dev before adding.
4. **Updating CLAUDE.md**: reflect operational changes, new "Do NOT" rules learned from incidents, new tools.
5. **Quarterly doc review**: a 30-min meeting per quarter to walk the doc map and flag stale content.

### Stale content detection

- 🔴 status items in any doc trigger a review
- Decisions without status flips after 6 months → review for staleness
- Edge cases marked 🟡 (planned) should advance to ✅ within their target phase; if not, escalate
- Runbooks not exercised in 6 months → run a tabletop exercise next quarter

## Code maintenance

### Dependency upgrades

| Component | Cadence | Notes |
|---|---|---|
| Polars | When polars-hash plugin updates compatibility | Test idempotence of `add_row_hash` against fixture before upgrading |
| Python | LTS version-track only; major upgrades during planned maintenance | Full test suite must pass on new version |
| ConnectorX | When source DB driver compatibility requires | Validate extraction throughput unchanged |
| pyodbc / ODBC Driver 18 | When SQL Server major version requires | BCP throughput regression test |
| `cryptography` library | Quarterly for security patches | AES-GCM-SIV roundtrip test |
| RHEL packages | Per IT policy | Server parity verified after upgrades |

**Hard rules**:
- Never upgrade Polars without verifying hash determinism (`tests/regression/test_hash_regression.py`)
- Never upgrade `cryptography` without AES-GCM-SIV roundtrip test
- Never upgrade ConnectorX without extraction throughput baseline comparison
- All upgrades happen on dev first, soak 1 week, then test, then prod

### Code review practices

- Every PR touching `cdc/`, `scd2/`, `data_load/` requires a second engineer's review
- Every PR touching `pii_*` requires security review
- Every PR adding a new SQL DDL requires DBA review
- Every PR modifying logging filters requires sensitive-data hygiene review
- Reviewer checklist documented in `docs/CONTRIBUTING.md` (created when code volume warrants it)

### Test suite health

- Tier 1 + 2 must pass on every commit; CI rejects on red
- Tier 3 nightly; flake rate > 5% triggers investigation
- Tier 4 pre-release; runtime > 4 hours triggers parallelization investigation
- Tier 5 quarterly; gaps in coverage filed as edge cases

## Operational maintenance

### Daily

- Check Power BI ops dashboard for run status (green / yellow / red)
- Verify gap detector reports zero gaps over the last 24 hours
- Review CRITICAL log entries from the prior 24 hours

### Weekly

- Vault row count vs prior week (sudden drop = investigate)
- Parquet tier review job ran and completed
- Reconciliation findings (if any) acknowledged or escalated
- Failover events review (count + reason)

### Monthly

- Retention enforcement job ran; review of Status flips
- Lateness profile updated for top 5 tables; alert if `L_99` shifted >25%
- Server parity verification audit (compare dev/test/prod configs)
- CCPA deletion log review (count + outcomes)
- Storage growth trending (Bronze, Parquet, vault)

### Quarterly

- DR rehearsal (RB-7 alternating scenarios per D44)
- Vault restore-test rehearsal (sample 100 tokens, verify decrypt path)
- Documentation map review (stale content detection)
- Edge case register review (advance 🟡 → ✅ where applicable)
- **Backlog grooming** (`BACKLOG.md` WSJF re-evaluation; close completed items; add new 🟡 follow-ups from validation log)
- **Polish queue grooming** (`POLISH_QUEUE.md` per D113; close P-N items whose underlying cosmetic drift was incidentally cleaned up by the round's substantive work; add new P-N items for cosmetic drift surfaced during close-out that doesn't deserve a B-number; verify ⚫ CLOSED items render-discipline-compliant per Pitfall #9.j — strikethrough preserved + closure date + closure-mechanism line)
- **Risk register review** (`RISKS.md` re-scoring; close mitigated risks; add new delivery risks)
- **`CODE_BUILD_STATUS.md` review** (per CLAUDE.md "Validation discipline" #10; verify aggregate "At a glance" counts match per-unit tables; flip 🟢 BUILT → ✅ DEPLOYED entries where servers have been provisioned; close ⚫ Archived entries where supersession has landed)
- **`udm-progress-logger` skill audit** (per CLAUDE.md "Validation discipline" #9; sample 5-10 recent substantive completions from `_validation_log.md`; verify each has a same-session row + tracker-routing matches the skill's procedure; surface drift as candidate Skill 8.D producer-checklist directives)
- **`_agent_evolution/` changelog review** (per D98 semver discipline; verify each `<agent>-changelog.md` reflects the prompt's current `v<MAJOR.MINOR.PATCH>` header; verify prior-version files exist in `.claude/agents/_archive/`; close any orphaned changelog rows where no archived predecessor exists)
- Capacity planning review (D42 baseline vs actual; 12-month projection refresh)
- Audit / compliance verification (RB-7 / Tier 5 from `06_TESTING.md`)
- Alation metadata refresh (per D43, pipeline metadata published to catalog)

### Annually

- This document reviewed and updated
- Tokenization key/credential rotation (if applicable to chosen scheme)
- Library dependency major-version review
- Server hardware capacity review
- License renewal (SQL Server, Snowflake, Power BI, Automic)
- DR tabletop exercise (full data-center-loss simulation per D44)

## Onboarding

### New pipeline engineer

1. Read `CURRENT_STATE.md` first to know where the project is right now
2. Read `HANDOFF.md` for continuity context (per D60)
3. Read `NORTH_STAR.md` for the conflict-resolution rubric (per D61)
4. Read `RISKS.md` to understand active delivery risks (per D61)
5. Read `00_OVERVIEW.md` for the document map
6. Read `01_ARCHITECTURE.md` for the system shape
7. Read `09_VISUALS.md` to internalize the data flow
8. Read `CHECKS_AND_BALANCES.md` for the validation discipline (NON-NEGOTIABLE per D55/D56)
9. Read `CLAUDE.md` (repo root) for the technical history and gotchas
10. Read `phase{N}/00_phase_overview.md` for any active phase
11. Pair with a senior engineer for one full pipeline run debugging session
12. Run the Tier 1 + 2 test suite locally; understand what each test proves
13. Shadow one operator runbook execution (any RB)

### New operator

1. Read `00_OVERVIEW.md` and `09_VISUALS.md`
2. Read all runbooks in `05_RUNBOOKS.md`
3. Run the Power BI dashboards; understand each tile's data source
4. Pair with a senior operator for one AM/PM cycle including any incidents
5. Execute one runbook end-to-end in dev (any low-risk one, e.g., RB-5 backfill)

### New auditor / compliance reviewer

1. Read `00_OVERVIEW.md` for the high-level architecture
2. Read the audit posture sections of `01_ARCHITECTURE.md` (§1.7) and `phase1/00_phase_overview.md` ("For auditors")
3. Read `03_DECISIONS.md` D6, D26, D30, D32 for PII / retention / health-check posture
4. Run sample audit queries from `07_LOGGING.md` against the metadata tables
5. Tour the Power BI audit dashboard

### New manager / executive sponsor

1. Read `00_OVERVIEW.md` only — the rest is engineer-facing
2. For specific phases, read `phase{N}/00_phase_overview.md` "For management" section
3. Quarterly stakeholder review of phase progress

## Decision-change protocol

Architectural decisions in `03_DECISIONS.md` change over time. The protocol:

1. Propose the change as a new D-number with status 🟡 Proposed; reference the prior D it would supersede
2. Capture the trigger (what changed: new requirement, learned anti-pattern, cost data, etc.)
3. Walk the impact: which docs, runbooks, edge cases, tests are affected
4. Stakeholder review per the original decision's owner list
5. On lock: status 🟢; the prior D moves to ⚫ Superseded with forward link
6. Update affected artifacts (architecture, runbooks, tests, etc.) in the same commit as the lock

Don't edit prior decisions in place; supersede. Audit trail.

## Incident response

When something goes wrong in production:

1. **Detect**: Power BI dashboard alert, log alerter, or operator observation
2. **Triage**: severity assessment (Critical / Warning / Info per `07_LOGGING.md`)
3. **Stabilize**: invoke the relevant runbook (RB-1 through RB-11)
4. **Diagnose**: log analysis using the workflows in `07_LOGGING.md` §"Debugging workflows"
5. **Resolve**: fix or workaround
6. **Document**:
   - File a post-mortem in `docs/postmortems/YYYY-MM-DD-<incident-slug>.md`
   - Update CLAUDE.md if a new "Do NOT" rule was learned
   - Add an edge case to `04_EDGE_CASES.md` if applicable
   - Update the relevant runbook with the new procedure
   - Update test suite if a regression test would have caught it

The pattern: every incident enriches the documentation. Don't move on without capturing the learning.

## Disaster preparedness

### Quarterly drills

- Q1 + Q3: server failover (RB-2)
- Q2 + Q4: data center loss (RB-7 Scenario B per D44)

### Continuous

- Vault backup every night; verified weekly
- Parquet integrity checks weekly (`parquet_verify.py`)
- Cross-server parity check at every pipeline startup
- Idempotency ledger startup-recovery sweep at every pipeline start

### Annual

- Full DR tabletop with executive observers
- Security audit including PII handling and decrypt access patterns
- Compliance review against current CCPA/CPRA/GLBA requirements

## Where to ask for help

| Question | Channel |
|---|---|
| "How does the pipeline work?" | This doc set + CLAUDE.md |
| "Why is X designed this way?" | `03_DECISIONS.md` |
| "What if X happens?" | `04_EDGE_CASES.md` + relevant runbook |
| "I see Y in production" | Log analysis workflow in `07_LOGGING.md` |
| "Is the system idempotent?" | `06_TESTING.md` § Tier 2 + 3 |
| "Are we audit-ready?" | `06_TESTING.md` § Tier 5 + audit posture sections |
| "Schema change incoming" | Schema evolution governance (Phase 1 Round 7) |
| "PII access request" | RB-4 (PII decryption) |
| "CCPA deletion request" | RB-10 |
| "Production is stuck" | RB-9 (cancellation flow) |

## Development tooling — Claude skills and plugins

Per D46, the project uses these Claude Code capabilities to support planning and development.

### Currently in use (no approval needed — built-in or already-approved)

| Tool | Type | Use case |
|---|---|---|
| `/review` | Built-in command | Run on every code change starting Phase 1 Round 3 |
| `/security-review` | Built-in command | Run on every PII/auth/encryption change |
| `/init` | Built-in command | Update CLAUDE.md as code evolves |
| `anthropic-skills:consolidate-memory` | Anthropic-approved skill | Periodic doc/memory cleanup |
| `anthropic-skills:skill-creator` | Anthropic-approved skill | If we author a project-local skill |

### Proposed for adoption (gated on open-source approval)

| Tool | Source | Status | Trigger to revisit |
|---|---|---|---|
| **Superpowers** | [github.com/obra/superpowers](https://github.com/obra/superpowers) | 🟡 Proposed | Open-source approval; install for Phase 1 round planning |
| **Senior Data Engineer skill** | [alirezarezvani/claude-skills](https://github.com/alirezarezvani/claude-skills) | 🟡 Proposed | After Superpowers approval validates the pipeline |
| **Python Test Auditor** | mcpmarket.com / community | 🟡 Deferred | Phase 1 Round 5 (Tests) onward |

### Skills explicitly NOT adopted (with reasoning)

| Tool | Reason |
|---|---|
| ADR skill | Substantial overlap with `03_DECISIONS.md`; our existing D-number convention IS an ADR pattern |
| Audit Trail skill | Overlaps with `03_DECISIONS.md` + `PipelineEventLog` + `IdempotencyLedger` |
| Database Designer | Round 1 DDL already drafted; missed the window |
| Codebase Audit skills | Premature — no production codebase deltas yet |
| Trail of Bits Security | `/security-review` built-in is sufficient |

### Open-source approval workflow

For any third-party skill:

1. Pipeline lead opens approval ticket with security/compliance team
2. Provide:
   - Source repo URL
   - Author / maintainer info
   - License (MIT, Apache 2.0, etc.)
   - What system access the skill requires (file system, network, secrets)
   - Examples of the skill's prompt content (so reviewers can see what would run)
3. Track in `docs/migration/oss_approvals.md` (created when first approval is requested)
4. On approval: install via `/plugin install` or `.claude/skills/<name>/SKILL.md`
5. On rejection: update D46 to ⚫ Skipped with rejection reason

### Project-local skills (no external approval needed)

We can author project-specific skills under `.claude/skills/<name>/SKILL.md`. These are pure markdown files version-controlled with the repo. Candidate skills for our project:

- `.claude/skills/udm-edge-case-validator/SKILL.md` — references the M/S/I/N/P/G/D/F/V series, prompts when designing new code to check against the register
- `.claude/skills/udm-decision-recorder/SKILL.md` — when a new decision is being made, prompts to add it to `03_DECISIONS.md` with the right structure
- `.claude/skills/udm-runbook-author/SKILL.md` — template enforcement for new runbooks (When/Pre-flight/Procedure/Validation/Rollback)
- `.claude/skills/udm-power-bi-query-builder/SKILL.md` — generates Power BI-compatible SQL queries against `General.ops` tables
- `.claude/skills/udm-ddl-validator/SKILL.md` — validates SQL DDL against the conventions in `phase1/01_database_schema.md`

These would be added incrementally as patterns emerge during implementation. Defer until Phase 1 Round 3 (Core Modules) so we have clarity on what's worth automating.

### Install commands (for reference)

```bash
# Superpowers (after approval)
/plugin install superpowers@claude-plugins-official

# Senior Data Engineer (after approval)
# Manual install — clone the skill repo into ~/.claude/plugins/

# Project-local skill
mkdir -p .claude/skills/<skill-name>
cat > .claude/skills/<skill-name>/SKILL.md <<EOF
---
description: <one-line description>
---

# <Skill Name>

<skill body>
EOF
/reload-plugins
```

### When to evaluate new skills

- Quarterly review during MAINTENANCE.md cycle
- When starting a new phase (different work mix may benefit from different tooling)
- When a recurring pain point surfaces in retro
- When the Anthropic skill ecosystem releases a major new capability

## How to update this document

This document is reviewed annually unless an incident or decision warrants earlier update. Updates increment a "Last reviewed" date at the top.

Owners: operations lead + pipeline lead jointly.
