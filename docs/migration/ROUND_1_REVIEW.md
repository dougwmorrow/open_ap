# Phase 1 Round 1 — Critical Review

This document captures the reflection on Round 1 (Database Schema) progress and the recommendations for what to do next.

## Status snapshot

- **Phase 1 progress overall**: 1 of 6+1 rounds drafted. Round 1 is at draft stage, not signed off.
- **Phase 0 progress**: 0/19 deliverables checked. We jumped to Phase 1 deep dive in parallel without closing Phase 0 first.
- **Code written**: zero lines of production code. All work to date is documentation.
- **Decisions locked**: 41 (D1-D45 with some superseded). Decisions proposed: 4-5.
- **Doc volume**: ~250 KB of planning across 11 markdown files.

## Round 1 quality findings (from reflection agent)

### Critical bugs / gaps

| # | Issue | Severity | Where |
|---|---|---|---|
| 1 | **SP-1 (`PiiVault_GetOrCreateToken`) has lookup-then-INSERT concurrency bug** — two simultaneous callers can both miss SELECT, both INSERT, second violates UNIQUE on PlaintextHash | 🔴 Critical | `phase1/01_database_schema.md:1163-1189` |
| 2 | **SP-3 through SP-6 (gate procedures) are referenced but not defined** — bodies "see RB-9" instead of inline | 🟡 Doc-completeness | `phase1/01_database_schema.md:1230-1244` |
| 3 | **PartitionFunction values static through 2026 only** — PipelineLog INSERTs will fail at end of 2026 without a rollover job | 🔴 Time-bomb | `phase1/01_database_schema.md:187-191` |
| 4 | **No FK from `PiiTokenizationBatch`, `PiiVaultAccessLog`, `CcpaDeletionLog` to `PiiVault.Token`** while `PiiTokenProvenance` does have one — inconsistent policy | 🟡 Consistency | Multiple table sections |
| 5 | **No `PiiTokenizationBatch` UNIQUE constraint** — same batch could be tokenized twice and produce conflicting row counts (I3 violation) | 🔴 Idempotency | `phase1/01_database_schema.md` PiiTokenizationBatch |
| 6 | **No `EncryptionVersion` column on PiiVault** — D7 (AES-GCM-SIV fallback) couldn't be cleanly migrated to without rewrapping every row | 🟡 Future-proofing | PiiVault DDL |
| 7 | **No `SchemaContract` or `SchemaChangeLog` table** for D40 (schema evolution governance, Round 7) | 🟡 Round 7 unscheduled | Schema doc table inventory |
| 8 | **No `OrphanedTokenLog`** for P2 (vault deletion makes Bronze tokens unrecoverable) | 🔴 CCPA gap | Phase 1 vs Phase 2/Phase 6 |

### Doc-set inconsistencies

- `02_PHASES.md` Phase 1 mentions 6 rounds; `phase1/00_phase_overview.md` adds Round 7; `PHASE_1_DEEP_DIVE_PLAN.md` only has 6
- D29 (original) and D29 (revised) coexist; supersession pattern needs cleanup
- `01_database_schema.md` D45.6 lists "DELETE permission denied on audit tables" but does not include PiiVault in the list — inconsistency
- Storage forecast in schema doc (190-300 GB compressed) but Phase 0 capacity baseline (deliverable 0.17) is incomplete

### Largest unaddressed risk

**The plan is over-specified for a team that hasn't executed any of it yet.** 46 decisions, 23 tables, eight phases, six rounds, zero lines of production code. By the time we start writing code in Phase 1 Round 3, integrations between D6 (vault), D16 (Parquet stage-check-exchange), and D29 (Automic gate) will reveal edge cases that 46 locked decisions don't anticipate. **Each subsequent locked decision raises the cost of the inevitable correction.**

## Recommendations

### Recommendation A (priority 1): Iterate Round 1 v2 before DBA review

Three days of focused iteration to address the 🔴 critical issues from the table above:

```
DAY 1: Fix concurrency and partition issues
  - Rewrite SP-1 with MERGE WITH (HOLDLOCK) or try/catch-then-relookup pattern
  - Inline SP-3 through SP-6 bodies (lift from RB-9)
  - Add partition rollover plan: either inline a SQL Agent job DDL OR commit to it landing in Round 4 with a hard-block dependency
  - Add UNIQUE constraint to PiiTokenizationBatch (BatchId, SourceName, ObjectName, ColumnName)

DAY 2: Add missing tables and columns
  - Decide: SchemaContract (Round 7) lands in Round 1 v2 or as a separate Round 7 deliverable?
  - Add OrphanedTokenLog for P2/CCPA (or document why it's deferred)
  - Add EncryptionVersion to PiiVault for D7 future-proofing
  - Reconcile FK policy on PII audit tables (add or document the absence)

DAY 3: Doc-set hygiene
  - Reconcile round count across 02_PHASES.md, phase1/00_phase_overview.md, PHASE_1_DEEP_DIVE_PLAN.md
  - Sort 03_DECISIONS.md by D-number; archive superseded sections cleanly
  - Update D45.6 to be precise about PiiVault DELETE policy (vault is protected via SP, not DENY DELETE)
  - Cross-doc consistency check
```

After v2: send to DBA review; pre-flight is now clean.

### Recommendation B (priority 2): Round 0.5 — pre-locking spike

Before locking Round 3 (Core Modules) or Round 4 (Tools), execute a 1-week throwaway spike that exercises three integrations we have NOT yet validated with code:

1. **Parquet stage-check-exchange** (D16) — write to `_inflight_*.parquet`, validate, atomic-rename, register. Real Polars + real disk + real timing.
2. **Vault GET-OR-CREATE under concurrency** (D6) — fire 4 simultaneous Python processes calling SP-1 with same plaintext. Confirm only one row created.
3. **Automic gate-table acquire** (D29) — simulate prod failure mid-run, confirm test pipeline acquires gate cleanly with sp_getapplock.

These three integrations are the largest "decision combinations not validated" set. The spike is throwaway code on dev — not production. The output is:
- Confirmation that D6, D16, D29 work as specified
- A list of small adjustments to those decisions if implementation diverges from spec
- Confidence that subsequent rounds can lock module designs

**If we skip Round 0.5**, we'll discover these issues during Phase 2 pilot — much more disruptive.

### Recommendation C (priority 3): Run Round 2 in parallel during DBA review

Round 2 (Configuration) is independent of DBA feedback on schema. While Round 1 v2 is in DBA review, draft Round 2:

- `UdmTablesList` column additions
- `.env` structure per server (dev/test/prod)
- GPG-encrypted credential file deployment plan
- Cross-server parity baseline JSON
- Automic job definitions (production AM/PM, test AM/PM gate-check)

Round 2 review can complete while Round 1 v2 is awaiting DBA, parallelizing the gating work.

## Specific action items

For the user, in priority order:

1. **Decide on Round 0.5 spike** — yes/no. If yes, this becomes a new decision (D47) and moves us into a "validate before locking" mode for Round 3 onward.

2. **Authorize Round 1 v2 iteration** — yes/no. The 8 issues above need to be addressed before DBA review is productive. Estimated 2-3 days of work.

3. **Authorize Round 2 in parallel** — yes/no. Round 2 (Configuration) drafting can start while Round 1 v2 is in review; the work is independent.

4. **Doc cleanup pass** — yes/no. 1 hour of maintenance to reconcile inconsistencies. Low priority but compounds in pain over time.

5. **Schedule Phase 0 deliverables** — Phase 0 has 19 deliverables, 0 complete. Even with 13 still-relevant items (some superseded/removed), they need to actually start. Most are decisions or measurements, not engineering work.

## Why not the other paths?

- **Send to DBA as-is**: SP-1 has a real bug. DBA review on a known-bad doc wastes their time and your credibility.
- **Advance to Round 2 without iterating Round 1**: leaves the bugs in Round 1; they will surface during code generation in Round 3.
- **Pause Phase 1 entirely**: planning is more done than not done; pausing wastes the planning velocity we have.

The right answer is iterate Round 1 in parallel with starting Round 2 in parallel with the Round 0.5 spike.

## What I recommend doing right now

In priority order:

1. **Approve Round 0.5 spike** (or explicitly skip) — a high-leverage decision with bounded effort
2. **Approve Round 1 v2 work** — clear up the bugs before DBA review
3. **Approve Round 2 drafting in parallel** — keep planning velocity while DBA reviews Round 1 v2
4. **Schedule Phase 0 deliverables** — even just one (e.g. lateness measurement query) breaks the "all planning, no execution" pattern

Then we resume at Round 1 v2 day-1.
