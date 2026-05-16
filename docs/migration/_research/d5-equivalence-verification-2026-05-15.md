<!-- RECONSTRUCTED 2026-05-15 from udm-researcher agent chat-text output per B-284 closure target. Sub-agent inheritance contract per CLAUDE.md hard rule 13 applied (9th cumulative production application). Findings verbatim per agent output. -->

# D.5 Equivalence Verification — udm-researcher per B-284

**Date**: 2026-05-15
**Sub-agent inheritance**: per CLAUDE.md hard rule 13 + PLANNING_DISCIPLINE.md §3 — active skills inherited from parent's planning session (udm-researcher only); 9th cumulative production application
**Researcher**: udm-researcher (invoked per B-284 closure target)
**Scope**: empirically verify each of 4 D.5 archived sections against claimed canonical destination

---

## Executive summary

- §1 (Data Flow vs 01c_data_flow_walkthrough.md): 🟡 **PARTIAL** — covers core mechanics; missing "Design decisions" block + V-7/OVERLAP_MINUTES rationale; informational cross-ref directs back to CLAUDE.md per 01c §0.4 required-reading. No 🔴 actively-misleading gaps.
- §2 (Architecture Decisions vs 01_database_schema.md): 🔴 **GAPS FOUND** — schema doc covers General.ops DDL only. UdmTablesList column inventory, extraction routing rules, connection strings, Column Tracking/Sync, CDC+SCD2 in-memory design, BULK_LOGGED pattern are ABSENT from destination. **Cross-ref MISLEADS readers.** Correct dest for UdmTablesList: `02_configuration.md §1` (35 columns enumerated there). Remaining content is CLAUDE.md-only (no spec-doc equivalent).
- §3 (Observability vs 02_configuration.md § Observability): 🔴 **GAPS FOUND** — 02_configuration.md has NO observability section. EventType + two-table pattern actually at `01c § 8`; column-level DDL at `01_database_schema.md`. SqlServerLogHandler design + retention policy + PipelineEventTracker code example + debugging workflow exist ONLY in CLAUDE.md.
- §4 (Security Model vs SECURITY_MODEL.md): ✅ **EQUIVALENT** with minor nuance differences — SECURITY_MODEL.md is canonical and comprehensive; one minor procedural gap (RISKS.md R32 incident note).

## §1 Data Flow verdict: 🟡 PARTIAL (acceptable)

01c covers mechanics well; "Design decisions (resolved)" block + V-7/OVERLAP_MINUTES rationale ABSENT but 01c §0.4 explicitly cross-refs back to CLAUDE.md. Not misleading.

**Remediation**: NONE required. Archive serves as recovery path; cross-ref is informational.

## §2 Architecture Decisions verdict: 🔴 INCORRECT cross-ref destination

The cross-ref to `phase1/01_database_schema.md` is INCORRECT. None of the archive content exists there.

**Per-claim breakdown** (all 16 claims):
- Extraction routing (SourceIndexHint / PartitionOn / oracledb vs ConnectorX) — 🔴 MISSING from schema doc (correct dest: `02_configuration.md §1`)
- UdmTablesList 13-column inventory — 🔴 MISSING from schema doc (correct dest: `02_configuration.md §1` has 29+6 columns)
- Connection string patterns (oracle:// / mssql:// / pyodbc/BCP) — 🔴 MISSING (no spec-doc dest)
- Column Tracking (UdmTablesColumnsList 9 columns) — 🔴 MISSING (no spec-doc dest)
- Column Sync 7-step procedure — 🔴 MISSING (no spec-doc dest)
- Oracle/SQL Server PK discovery — 🔴 MISSING (no spec-doc dest)
- View PK discovery via dependencies — 🔴 MISSING (no spec-doc dest)
- UdmTablesColumnsList metadata columns (ObjectType / DatabaseName / MetadataLastUpdated) — 🔴 MISSING (no spec-doc dest)
- CDC + SCD2 Polars in-memory design (df_current + pk_columns forward) — 🔴 MISSING (no spec-doc dest)
- SCD2 optimization 5→2 steps — 🔴 MISSING (no spec-doc dest)
- BULK_LOGGED + `_bulk_load_recovery_context()` — 🔴 MISSING (no spec-doc dest)

**Remediation**: split cross-ref in CLAUDE.md post-trim:
- For UdmTablesList columns + extraction routing: change cross-ref to `phase1/02_configuration.md §1`
- For Column Tracking / Sync / CDC+SCD2 design / connection strings / BULK_LOGGED: mark as "CLAUDE.md-only; see `_archive/CLAUDE_architecture_decisions_archive_2026-05-15.md` for verbatim preservation"

## §3 Observability verdict: 🔴 INCORRECT cross-ref destination

02_configuration.md has NO § Observability — that section does not exist in the file. The cross-ref destination is invalid.

**Actual coverage locations**:
- EventType families + two-table pattern → `01c § 8` (data flow walkthrough observability annotations)
- PipelineEventLog + PipelineLog column-level DDL → `01_database_schema.md` (the DDL home)
- SqlServerLogHandler design + retention policy + PipelineEventTracker code example + debugging workflow SQL → CLAUDE.md ONLY (no spec-doc equivalent anywhere)

**Remediation**: split cross-ref in CLAUDE.md post-trim:
- For EventType families + two-table pattern: change cross-ref to `phase1/01c_data_flow_walkthrough.md §8`
- For DDL column lists: change cross-ref to `phase1/01_database_schema.md` (PipelineEventLog + PipelineLog table definitions)
- For Handler design / retention / code example / debugging workflow: mark as "CLAUDE.md-only; see `_archive/CLAUDE_observability_archive_2026-05-15.md` for verbatim preservation"

## §4 Security Model verdict: ✅ EQUIVALENT

SECURITY_MODEL.md is canonical and comprehensive (407 lines). All 13 archive claims verified equivalent or partially-present-with-acceptable-nuance.

**One minor gap**: archive incident step 5 "File incident note in RISKS.md under R32" not in § 6 incident procedure (R32 cross-referenced in §7 but not in incident steps). Trivial procedural; could be added to SECURITY_MODEL.md § 6 OR accepted as archive-only.

**Remediation**: NONE required (canonical destination is correct + comprehensive).

## Recommended remediations

1. **CLAUDE.md L165-178 (post-trim Architecture Decisions stub)**: split cross-ref — `02_configuration.md §1` for UdmTablesList; mark Column Sync etc. as CLAUDE.md-only with `_archive/` recovery pointer
2. **CLAUDE.md L195-225 (post-trim Observability stub)**: split cross-ref — `01c §8` for EventType families; `01_database_schema.md` for DDL; mark Handler design etc. as CLAUDE.md-only with `_archive/` recovery pointer
3. **`_refactor_log.md`**: update equivalence-status from 🟡 NOT YET FORMALLY VERIFIED to ✅ VERIFIED (with notes per §1 + §4) OR 🔴 INCORRECT-CROSS-REF (with corrections per §2 + §3) per entry

## Aggregate verdict

🟡 **PARTIAL** — significant 🔴 GAPS in §2 + §3 cross-ref destinations; §1 acceptable; §4 fully equivalent. Closure of B-284 requires cross-ref correction THIS COMMIT.
