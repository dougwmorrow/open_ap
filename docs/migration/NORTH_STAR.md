# North Star

This document defines the single outcome that every decision in this project must serve. When two paths diverge, this is the rubric.

## The North Star

> **Audit-grade traceability for every Bronze row, deployable, idempotent, and operationally stable — at a Snowflake spend ceiling of $120K/year.**

Five compound words doing real work:

| Word | What it forbids | What it favors |
|---|---|---|
| **Audit-grade** | Silent fixes; data scrubbed without trail; "we just rolled it back" recoveries | Append-only logs; superseded-not-deleted decisions; validation-gated status flips |
| **Traceability** | Untraceable PII flows; orphaned tokens; schema changes without governance | Provenance (PiiTokenProvenance), event logs (PipelineEventLog), validation log (`_validation_log.md`) |
| **Idempotent** | Lookup-then-INSERT races; non-deterministic hashing; UPSERT without unique keys | Hash-based change detection; ledger-gated steps; `UPDLOCK + HOLDLOCK` patterns |
| **Operationally stable** | Untested runbooks; ungoverned schema changes; single points of failure | DR rehearsal; Round 0.5 spike before locking modules; cross-server parity |
| **$120K/year ceiling** | Always-on Snowflake compute for daily SCD2; full re-loads every run; storage-as-an-afterthought | Python-first SCD2; Parquet-first archive; Snowflake for analytics + reconciliation only |

## Per-phase contribution

Every phase must explicitly advance one or more of the five pillars. If a deliverable doesn't, it either gets re-scoped or skipped (per the "skip if it doesn't help" rule from D34).

| Phase | Audit-grade | Traceability | Idempotent | Operationally stable | $120K |
|---|---|---|---|---|---|
| Phase 0 — Decisions | ✅ Stakeholder sign-off chains | ✅ PII inventory | — | ✅ Cross-server parity baseline | ✅ Snowflake cost data |
| Phase 1 — Foundation | ✅ Audit log tables | ✅ Token provenance | ✅ Idempotency ledger | ✅ Crash-safe procedures | ✅ Per-table cost projections |
| Phase 2 — Pilot | ✅ First validation log entries | ✅ End-to-end Parquet→Bronze chain | ✅ Replay tests | ✅ One table production-stable | — |
| Phase 3 — Large tables | ✅ DeleteEvaluationAudit | ✅ PipelineExtraction trust gate | ✅ Idempotent backfill | ✅ Per-day checkpointing | — |
| Phase 4 — Production rollout | ✅ Per-table enablement log | — | — | ✅ Per-table soak | — |
| Phase 5 — Snowflake | — | ✅ Iceberg lineage | ✅ COPY INTO load history | ✅ Failover-tested mirror | ✅ Trial cost data |
| Phase 6 — Health checks | ✅ Trend dashboards | ✅ Lineage publication | — | ✅ Anomaly alerting | — |

## Conflict-resolution rubric

When facing a design trade-off, walk the pillars in this order:

1. **Audit-grade always wins.** A "simpler" design that loses audit traceability is not simpler — it's wrong.
2. **Traceability beats convenience.** If a feature would produce orphaned PII references, it doesn't ship until the orphan is logged.
3. **Idempotent beats fast.** If a fix breaks idempotency, it's not a fix.
4. **Operational stability beats cleverness.** A 99% solution we can run unattended beats a 99.9% solution that needs operator intervention every cycle.
5. **Cost ceiling beats feature richness.** If a path requires Snowflake compute we don't have budget for, it gets reshaped to fit Python+SQL Server, not the other way around.

## Anti-patterns this North Star explicitly rejects

- ❌ "Just add a manual step" — operational instability
- ❌ "We can clean this up later" — audit-grade requires immutable trail
- ❌ "Skip the test, we'll catch it in production" — idempotency requires verification
- ❌ "Snowflake will scale that for us" — $120K ceiling
- ❌ "Trust me, the data is correct" — traceability requires evidence
- ❌ "We don't need a runbook for this" — operational stability requires written procedures

## Decisions that codify this North Star

- D6 (in-house tokenization vault) — audit-grade + cost ceiling
- D11 (empirical L_99 lookback) — operational stability + idempotency
- D15 (idempotency mandatory) — idempotency
- D17 (idempotency ledger) — idempotency + audit-grade
- D26 (append-only provenance) — traceability + audit-grade
- D29 (Automic gate-table coordination) — operational stability
- D30 (7-year retention with legal hold) — audit-grade + traceability
- D3 (SCD2 stays in Python+Polars; Snowflake for analytics + reconciliation only) — cost ceiling
- D34 (greenfield deployment, no legacy migration) — operational stability
- D38 (Phase 6 = Health, Lineage & Catalog) — traceability
- D55 (5-gate validation) — audit-grade
- D56 (second-pass validation) — audit-grade
- D60 (round close-out protocol) — operational stability + audit-grade
- D61 (NORTH_STAR/RISKS/BACKLOG integration) — audit-grade + traceability
- D62 (Canonical Context Load doctrine) — audit-grade + operational stability
- D63-D66 (Round 2 Configuration — UdmTablesList + GPG envelope + parity baseline + Automic inventory) — audit-grade + operational stability
- D67 (Tier 0 build-time smoke) — operational stability + idempotency
- D68-D71 (Round 3 cross-cutting — error class hierarchy + cursor ownership + 6-tier test pyramid + Snowflake auth flow) — operational stability + audit-grade
- D72 (validation cycle termination rule — 10-cycle ceiling + 3-clean convergence) — audit-grade + operational stability
- D73 (Round 3 math-infeasibility architectural-review acceptance) — operational stability
- D74-D77 (Round 4 Tools — CLI exit-code contract / argument naming / audit-row contract / Tier 0 scaffold) — audit-grade + operational stability
- D78 (Round 4 math-infeasibility architectural-review acceptance) — operational stability
- D79-D82 (Round 5 Tests — fixture canonical schema / Tier 0-1 boundary / Hypothesis budget / coverage thresholds) — idempotent + audit-grade
- D83 (Round 5 convergence-confirmed acceptance — NEW PRECEDENT) — operational stability + audit-grade
- D84-D87 (Round 6 Deployment — artifact contract / module startup sequence / 3-env cadence / pre-post-deploy checklist) — audit-grade + operational stability + idempotent
- D88 (Round 6 convergence-confirmed acceptance) — operational stability + audit-grade
- D89-D91 (Pattern F discipline — tiered close-out cascade audit; 🟢 Locked 2026-05-11 at Round 7 first-production close-out per empirical evidence; extended at Round 8 close-out) — audit-grade + operational stability + idempotent
- D92 (Schema evolution governance procedure — forward-only additive + SchemaContract supersession) — audit-grade + operational stability + idempotent
- D93 (Cross-doc cascade propagation requirement — formalizes Pattern F unscoped audit lesson) — audit-grade + operational stability
- D94 (Round 7 architectural-review acceptance — 3rd math-infeasibility variant after D73/D78) — operational stability
- D95-D99 (Round 8 Sub-Agent Self-Improvement Discipline — 7-skill suite umbrella + 9.j sub-class formalization + cycle-cadence tier mapping α/β/γ/δ + agent prompt versioning semver + R8 convergence-confirmed acceptance per D83/D88 precedent) — operationally stable + audit-grade + traceability + idempotent + cost ceiling (bounded compute)
- D100-D101 (Round 1.5 documentation supplement discipline — Round-N.5 mini-round pattern + R1.5 math-infeasibility acceptance per D73/D78/D94 precedent; 5 supplements G1-G6 closing schema-story gaps for new engineers + dashboard authors; B166-B175 carryover) — audit-grade + traceability + operationally stable
- **D102** (PiiVault encryption pin = AES-256-GCM Python with 12-byte nonce + 16-byte auth-tag wire format; closes Phase 0.4 merger-context mask/unmask algorithm question) — audit-grade + traceability (every decrypted token recorded in PiiVaultAccessLog)
- **D103** (Claude Code security model — 13-layer defense-in-depth with `/debi` working-directory boundary; threat-surface inversion dev > test > prod; canonical `SECURITY_MODEL.md`; closes Phase 0.12) — audit-grade + operationally stable; this is the foundational decision that makes AI-assisted development safe for a compliance-sensitive pipeline
- **D104** (Phase 2 pilot table = `DNA.osibank.ACCT` 1.2M rows; closes Phase 0.7) — operationally stable (small enough to iterate fast; large enough to exercise CDC + SCD2 + reconciliation paths)
- **D105** (SQL naming standards MANDATORY for new SP/view objects + filenames; existing pre-D105 names grandfathered per D92 forward-only; agent + skill enforcement) — audit-grade + traceability (consistent naming makes log queries + grep across the codebase deterministic)
- **D106** (operational pipeline schedule: `JOB_PIPELINE_AM` = 02:00 weekdays + `JOB_PIPELINE_PM` = 17:00 daily; supersedes Round 2 § 5.1 example values; closes Phase 0 deliv 0.10) — operationally stable
- **D107** (two LOCAL Windows network drive paths: H = primary local + VendorFile = secondary local; both in-company DC; closes Phase 0 deliv 0.5; DC-loss DR delegated to D110 since both drives local) — operationally stable (in-DC single-disk/single-server resilience + operational secondary for read access by other teams)
- **D108** (ops-channel email-centric: SQL Server Database Mail + Automic + Power BI + MS Teams; NO Slack/PagerDuty/SMS; supersedes B156 R7C1-5 SRE-pattern advisory; closes Phase 0 deliv 0.20) — operationally stable + audit-grade ($0 cost; pre-existing audit-trackable infrastructure)
- **D109** (operational pipeline schedule revised; dual-Automic prod-then-test 4-hour gap; AM Prod 02:00 + Test 06:00 weekdays; PM Prod 17:00 + Test 21:00 daily; SQL-table coordination via PipelineExecutionGate; supersedes D106) — operationally stable + audit-grade
- **D110** (DC-loss-no-DR posture acceptance per B192 path b; recovery via company backup + source-DB re-extraction; closes Phase 0 deliv 0.19 re-flip + B192) — audit-grade + operationally stable (documented residual risk per D30 7-year retention)
- **D111** (operational-infra D-number discipline: start 🟡 Proposed; flip 🟢 after user-attestation + session boundary; 🟡 Proposed itself per the discipline it defines) — audit-grade + operationally stable
- **D112** (Round-N.5 deep-dive plan timing = just-in-time at prior-phase close-out; formalizes B186; Phase 5 gated by B191 Snowflake-test-conclusion) — audit-grade + operationally stable
- **D113** (POLISH_QUEUE.md cosmetic-tracker discipline; P-N scheme distinct from B-numbers; status legend matches BACKLOG.md per Pitfall #9.j; round-close-out skim + Pattern F audit coverage via skill updates; 🟢 Locked directly per D111 process-infra exemption analogous to D55/D60/D89-D91/D95-D99) — audit-grade + traceability (de-escalates sub-class of R28 cascade self-attestation gap)

## How to apply this in agent prompts

Every custom agent in `.claude/agents/` should include a reference to this doc. Pattern:

> "Before reviewing this artifact, read NORTH_STAR.md. If your review surfaces a trade-off, walk the conflict-resolution rubric in priority order."

This is enforced via the `udm-researcher` agent prompt (which reads NORTH_STAR.md before any research run). The `udm-design-reviewer` agent's reference to NORTH_STAR is a 🟡 follow-up tracked in `BACKLOG.md` — to be added in the next sweep.

## Owner

Pipeline lead. North Star changes are major architectural events; require D-numbered decisions to revise.

## Last reviewed

2026-05-12 (**Multi-agent cascade**: extended decision list D109-D112 — operational schedule revised (dual-Automic) + DC-loss-no-DR posture acceptance + operational-infra D-number discipline + just-in-time plan timing. D106 ⚫ Superseded by D109. Earlier 2026-05-12: **Phase 0 user-sign-off batch**: extended decision list D106-D108 — operational pipeline schedule + dual offsite Parquet paths (D107 framing SUBSEQUENTLY REFRAMED 2026-05-12 fix-application-2 to "two local network drive paths"; see latest entry above) + ops-channel email-centric architecture. Closes Phase 0 deliv 0.10/0.19/0.20 strict-🟢. Earlier 2026-05-11: **Phase 0 prep close-out**: extended decision list D102-D105 — AES-256-GCM crypto pin (D102) + Claude Code 13-layer security model (D103) + pilot = DNA.osibank.ACCT (D104) + SQL naming standards MANDATORY with grandfather clause (D105). All four decisions support audit-grade + traceability pillars; D103 specifically makes AI-assisted development safe for a compliance-sensitive pipeline by enforcing `/debi` working-directory boundary. Now lists D6/D11/D15/D17/D26/D29/D30/D3/D34/D38/D55-D105 — Phase 1 corpus + Phase 0 prep close. Earlier 2026-05-11: Round 8 close-out D95-D99; Round 1.5 close D100-D101; post-Round-6-retrospective + Pattern F unscoped audit + Round 7 close-out D92-D94.)
