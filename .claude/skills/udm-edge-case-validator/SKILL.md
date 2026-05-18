---
name: udm-edge-case-validator
description: Walks the M/S/I/N/P/G/D/F/V edge case series in 04_EDGE_CASES.md and checks if a given design or change addresses relevant ones. Use before signing off a round, before merging a code change, before locking a decision. Catches edge cases the design implicitly addresses but doesn't document, AND edge cases the design doesn't yet address.
---

# UDM Edge Case Validator

Use this skill when reviewing any design artifact — a schema doc, a runbook, a stored procedure, a Python module — to walk the edge case register and verify coverage.

## When to use

- Before flipping a decision from 🟡 to 🟢 in `03_DECISIONS.md`
- Before signing off a round (Phase 1 Round 1 acceptance, etc.)
- Before merging a code change that touches a decision-implementing function
- When reviewing a runbook for completeness
- When reviewing a stored procedure for atomicity / idempotency

## Canonical Context Load (CCL) — required before invoking this skill (per D62)

Whoever invokes this skill (main agent or subagent) MUST have performed the Canonical Context Load (per `docs/migration/MULTI_AGENT_GUIDE.md` § Canonical Context Load) before walking the edge case series.

- **Stage 0 — Routing manifest** (recommended-not-mandatory; added 2026-05-15 per D62 amendment + D.2 INDEX.md per MARKDOWN_REFACTOR_PLAN.md §7.1 task 1.3): `docs/migration/INDEX.md` — read FIRST when uncertain which downstream Stage 1+2+3 docs your task actually needs. Skip when: you already know which Stage 1+2+3 docs to load (typical for recurring task patterns).
- **Stage 1 — Orientation** (mandatory, 4 reads): `NORTH_STAR.md`, `HANDOFF.md`, `CURRENT_STATE.md`, `CHECKS_AND_BALANCES.md`
- **Stage 2 — Risk + Backlog awareness** (mandatory): `RISKS.md`, `BACKLOG.md`, `_validation_log.md`
- **Stage 3 — Task-specific reads for this skill**: `04_EDGE_CASES.md` (full read of relevant series — M / S / I / N / P / G / D / F / V); the artifact under review
- **Stage 4 — Reference-on-demand**: grep `03_DECISIONS.md` for D-numbers cited in edge case mitigations, `05_RUNBOOKS.md` for RBs that handle specific cases

If invoked from a subagent context, the subagent's CCL responsibility is hard-required (per agent definition — first `Read` must hit a Stage 1 doc).

## Input

Provide:
- The design artifact (a doc path, a code function, a SQL DDL block, a runbook section)
- Optionally: which edge case series to focus on (e.g. "just I-series and N-series")

## Output structure

```
ARTIFACT: <what was reviewed>

EDGE CASE COVERAGE:
| ID | Series | Description | Status in artifact | Mitigation gap? |
|---|---|---|---|---|
| ... walk the relevant series ... |

ADDRESSED ✅:
- <list of edge cases the artifact handles, with how>

GAPS 🔴:
- <list of edge cases the artifact does NOT address, with risk assessment>
- For each gap: should this be addressed here, deferred, or accepted with rationale?

NOT-APPLICABLE ⚪:
- <list of edge cases that don't apply to this artifact, with one-line reason>

RECOMMENDED ACTIONS:
1. <specific change to artifact>
2. <new edge case to add to register if discovered>
3. <test case to add (Tier 1/2/3)>
```

## The series

| Series | Topic | Where to find them |
|---|---|---|
| M | Math / lookback / lateness | `04_EDGE_CASES.md` § M-Series |
| S | SCD2 reliability | § S-Series |
| I | Idempotency | § I-Series |
| N | Network drive / Parquet | § N-Series |
| P | PII / encryption | § P-Series |
| G | Gap detection / outage recovery | § G-Series |
| D | 2x/day cadence | § D-Series |
| F | Failover / cross-server parity | § F-Series |
| V | Vault provenance | § V-Series |

## Hard rules

1. **Walk the relevant series in full.** Don't skip cases that "obviously don't apply" — write the one-line reason in NOT-APPLICABLE.
2. **Distinguish "addressed" from "addressed correctly".** A case can be referenced in the artifact but the implementation has a bug. The reflection agent caught SP-1's concurrency bug this way.
3. **Identify implicit coverage.** If the artifact addresses an edge case without naming it, that's a documentation gap.
4. **Identify new edge cases.** If review surfaces something not in the register, propose adding it.
5. **Map gaps to action.** Every 🔴 gap needs: address-here / defer-to-phase / accept-with-rationale. No gap left unaddressed.

## Anti-patterns

- ❌ "Looks good" without walking the series
- ❌ Listing edge cases the artifact handles but not those it misses
- ❌ Treating "addressed" as binary (yes / no) — implementation can be subtly wrong
- ❌ Inventing edge cases that aren't in the register without proposing them be added

## Round-1 example

Reviewing `phase1/01_database_schema.md` SP-1 (`PiiVault_GetOrCreateToken`):

- I-series walk:
  - I1 (same BatchId retry): N/A — SP doesn't take BatchId
  - I3 (concurrent same-key INSERT): **🔴 GAP** — lookup-then-INSERT race; need MERGE WITH HOLDLOCK or try/catch-then-relookup pattern
  - I13 (snapshot re-INSERT same key): N/A
- P-series walk:
  - P1 (deterministic encryption): ✅ — same plaintext returns same token via lookup
  - P3 (vault corruption): N/A here; covered by RB-6
  - P9 (cross-source isolation): ✅ — SourceName in lookup index

Recommended action: rewrite SP-1 with `MERGE WITH (HOLDLOCK)` or replicate SP-7's catch-and-relookup pattern. Add I3 to schema doc's edge case mapping table.
