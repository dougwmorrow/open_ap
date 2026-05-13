# Round 1.5 Cycle 1 — External Evidence (Reviewer R1.5C1-5, Pattern E 5th slot)

**Date**: 2026-05-11
**Reviewer**: R1.5C1-5 (research specialist, advisory only — non-blocking; does not contribute to D72 consecutive-clean count)
**Artifact under review**: Round 1.5 supplement docs (`phase1/01a_control_tables.md`, `phase1/01b_bronze_stage_example_ddl.md`, `phase1/01c_data_flow_walkthrough.md`, `phase1/07a_schema_contract_examples.md`)
**Output convention**: per `udm-researcher` agent definition — per-claim findings with source citations, confidence, relevance to North Star pillars, and per-finding verdict.

---

## CCL compliance

Stage 1 reads completed before any research: NORTH_STAR.md, HANDOFF.md, CURRENT_STATE.md, CHECKS_AND_BALANCES.md.
Stage 2 reads completed: RISKS.md, BACKLOG.md, _validation_log.md.
Stage 3 reads completed: all 4 Round 1.5 supplement docs in full (01a, 01b, 01c, 07a).

---

## Research questions addressed

1. G1 § 1 control-tier vs operational-metadata-tier framing — recognized industry pattern?
2. G6 § 8.1 two-tables-two-purposes observability — matches canonical observability split?
3. G5 SchemaContract SupersededBy chain — Kimball Type-2 applied to metadata; comparable external patterns?
4. G2 Mermaid ER diagram convention — is `||--o{` cardinality notation canonical?
5. G6 § 10 bottleneck-investigation workflow — matches SRE incident-response practice?
6. G3+G4 type-mapping table (Polars dtype → SQL Server type) — canonical per Polars + Microsoft docs?
7. Dual date-pair SCD2 design (load-time pair + source-date pair) — Kimball-endorsed or project-specific?
8. Dashboard query catalog per-audience structuring — industry practice?

---

## Findings

---

### Finding 1: G1 § 1 Control-tier vs operational-metadata-tier framing

**Verdict**: APPROPRIATELY SCOPED with one strengthening opportunity

**Claim**: The supplement frames two tiers — `General.dbo` (control tier, pipeline reads) and `General.ops` (operational metadata tier, pipeline writes; downstream consumers read). These are named and separated by purpose, permissions, backup cadence, and audit semantics.

**External evidence**:

The control-plane / data-plane vocabulary is canonical in modern data engineering. IBM, Kong, Cloudflare, Airbyte, and dbt Labs all use exactly this framing: "The control plane manages configurations and policies; the data plane executes." (Sources: IBM [1], Airflow architecture docs [2], dbt Labs "What is a data control plane?" [3]). The pattern scales from network routing to Airflow's metadata DB vs. executor.

The Airflow analogy is particularly apt: Airflow's metadata DB (`airflow.db`) is a **control + state** hybrid — it stores DAG configuration, task state, and run history in one database schema, NOT separated by purpose. The UDM design is MORE disciplined than Airflow in this regard: it physically separates `General.dbo` (operator-editable trigger config) from `General.ops` (append-only execution records). dbt's artifact split is closer: `manifest.json` (static project definition, analogous to UdmTablesList) vs. `run_results.json` (execution outcomes, analogous to PipelineEventLog). dbt best-practice articles explicitly advise using them for separate purposes (governance vs. observability) [4].

**Missing citation opportunity**: The supplement doesn't name the pattern or cite any of these analogues. A single sentence noting "this follows the control-plane / data-plane separation pattern recognized in Apache Airflow architecture (metadata DB) and dbt artifacts (manifest vs. run_results)" would anchor the claim for a skeptical reader.

**Relevance to North Star**: Traceability (clear provenance of what the pipeline is configured to do vs. what it actually did) + Operationally stable (backup cadence and permissions policy differ by tier, preventing accidental operational metadata corruption).

**Confidence**: MEDIUM (framing is correct; analogy is strong; absence of citation is the gap)

---

### Finding 2: G6 § 8.1 "Two tables, two purposes" observability pattern

**Verdict**: APPROPRIATELY SCOPED — matches canonical observability split with one framing note

**Claim**: PipelineEventLog is the "dashboard layer" (small, structured, one row per step). PipelineLog is the "investigation layer" (many rows per step). Together they answer "what happened and how fast" (events) vs. "why did it happen that way" (logs).

**External evidence**:

This matches the canonical structured-observability split described by the OpenTelemetry specification and major observability vendors. OpenTelemetry separates Metrics (aggregated, timestamped measurements) from Logs (detailed event narrative) for exactly this reason: metrics for dashboards, logs for investigation [5]. The Honeycomb / Datadog investigation workflow is: alert fires on a metric → drill into structured logs / traces for root cause [6].

The RED method (Rate, Errors, Duration — Tom Wilkie, Grafana 2018) is the canonical microservices dashboard pattern [7]. PipelineEventLog's `RowsPerSecond`, `Status`, and `DurationMs` fields directly implement R, E, and D. The supplement doesn't name this alignment.

One framing note: the supplement calls PipelineEventLog a "dashboard layer" and PipelineLog an "investigation layer." The canonical terminology from Google SRE (Four Golden Signals) and OpenTelemetry is "metrics vs. logs" or "signals vs. events." The supplement's framing is functionally equivalent but uses project-internal vocabulary rather than the industry term. This is a missing-citation opportunity, not a correctness problem.

**Relevance to North Star**: Traceability (§ 10 bottleneck-investigation workflow maps exactly to canonical trace → log drill-down pattern) + Operationally stable (dashboard queries enable proactive anomaly detection).

**Confidence**: HIGH — pattern is well-grounded; framing is appropriate.

---

### Finding 3: G6 § 10 Bottleneck-investigation workflow

**Verdict**: APPROPRIATELY SCOPED — matches SRE incident-response best practice

**Claim**: The 5-step investigation workflow: (1) find cycle in PipelineEventLog, (2) get BatchId, (3) look at per-step durations, (4) filter PipelineLog by BatchId + time window, (5) cross-reference with control tier.

**External evidence**:

This is exactly the canonical SRE alert-then-investigate pattern. Datadog, Honeycomb, and the Google SRE Workbook all describe: alert → identify event → drill into logs → correlate with configuration/deployment context [6]. The Elastic blog on observability metrics describes the same "top-down investigation" flow: metrics surface the anomaly, logs explain the root cause [8].

The specific join pattern (BatchId linking PipelineEventLog to PipelineLog) is the project's implementation of the OpenTelemetry "trace ID propagation" concept: a single identifier threads through all signals so you can correlate across tiers [5]. This is a strong design that matches industry practice.

**Confidence**: HIGH — no concerns.

---

### Finding 4: G5 SchemaContract SupersededBy chain

**Verdict**: APPROPRIATELY SCOPED — project-specific extension of a recognized pattern; worth noting the distinction

**Claim**: `SchemaContract.SupersededBy` is a forward-link from a superseded contract row to its replacement, forming a versioned chain. Used for SP signature evolutions (Round 7) and source schema assertions.

**External evidence**:

The closest industry analogues are:
- Apache Iceberg metadata files: every schema change creates a new `metadata.json` with `previous-metadata-log` pointing back; the chain is backward-linked (Iceberg stores `current-snapshot-id` and a `snapshot-log` array), NOT forward-linked via `SupersededBy` [9]. Iceberg does not use a `SupersededBy` forward-pointer.
- Event sourcing / append-only log patterns: these don't use forward-links; the supersession is implied by temporal ordering.
- dbt lineage artifacts: `manifest.json` version is a full replacement; there's no `SupersededBy` field.

**The `SupersededBy` forward-link is project-specific.** It's a sound design choice (it allows direct navigation from old → new without a full table scan or date-ordering query), but it is NOT a named industry standard. The supplement (07a) presents it as straightforward DDL without claiming external precedent, which is appropriate. The Round 1 schema doc § 23 introduced it; 07a makes it concrete.

One concrete risk not cited: a `SupersededBy` forward-link creates a write-ordering dependency — the new contract row must be INSERTed (to get a `ContractId`) BEFORE the old row can be UPDATEd with `SupersededBy = <new_id>`. This is a two-step mutation on what is otherwise an append-only table. The BACKLOG item B04 (SchemaContract DDL hardening: self-FK on SupersededBy) is the right mitigation and is already tracked. This research confirms B04 is load-bearing.

**Relevance to North Star**: Audit-grade (forward-link enables unambiguous supersession chain navigation) + Traceability (SP signature evolutions are fully auditable via the chain).

**Confidence**: MEDIUM — design is sound; its project-specific nature should be acknowledged rather than implied as canonical.

---

### Finding 5: G2 / Mermaid ER diagram cardinality notation `||--o{`

**Verdict**: NOTE — Mermaid ER diagram is referenced as a convention in the doc set (09_VISUALS.md references Mermaid) but the Round 1.5 supplements themselves do NOT contain Mermaid ER diagrams. The supplement docs use prose tables and DDL, not erDiagram blocks.

**What was researched**: The Mermaid official docs confirm that `||--o{` IS canonical Mermaid crow's foot notation [10]:
- `||` = exactly one (innermost `|` = minimum one, outermost `|` = maximum one)
- `o{` = zero-or-more (innermost `{` = maximum many, outermost `o` = minimum zero)
- `--` = solid line (identifying relationship)

So `||--o{` means "exactly one parent → zero or more children." This is correct crow's foot semantics and is well-supported in Mermaid v9+ (which is the version used in GitHub Markdown rendering since 2022).

**Finding**: The supplements do not use erDiagram notation themselves. If `09_VISUALS.md` uses this notation, it is well-founded and does not require a citation. No concern here.

**Confidence**: HIGH for the notation itself; N/A for Round 1.5 supplements which don't use it.

---

### Finding 6: G3+G4 Polars dtype → SQL Server type mapping

**Verdict**: MOSTLY APPROPRIATELY SCOPED with two nuances

**Claim** (`phase1/01b_bronze_stage_example_ddl.md` § 6 type-mapping table):

| Polars | SQL Server |
|--------|-----------|
| Int8 | TINYINT |
| Int16 | SMALLINT |
| Int32 | INT |
| Int64 | BIGINT |
| UInt8 | TINYINT (unsigned domain via app) |
| UInt16 | INT |
| UInt32 | BIGINT |
| UInt64 | BIGINT after `.reinterpret(signed=True)` |
| Float32 | REAL |
| Float64 | FLOAT |
| Decimal(p,s) | DECIMAL(p,s) |
| Utf8 | NVARCHAR(N) |
| Date | DATETIME2(3) |
| Datetime(ms) | DATETIME2(3) |
| Boolean | BIT |
| Categorical | NVARCHAR(N) |
| Binary | VARBINARY(N) |

**Evidence from primary sources**:

1. Polars official docs confirm the integer type hierarchy: Int8, Int16, Int32, Int64 (signed); UInt8, UInt16, UInt32, UInt64 (unsigned) [11].

2. Microsoft SQL Server docs confirm: TINYINT = 0 to 255 (1 byte, unsigned-domain); SMALLINT = -32,768 to 32,767 (2 bytes, signed); INT = -2.1B to 2.1B (4 bytes, signed); BIGINT = -9.2×10^18 to 9.2×10^18 (8 bytes, signed) [12].

3. No official Polars documentation maps Polars types to SQL Server. The mapping in § 6 is a project-derived table based on Polars + SQL Server docs, not a cited external standard.

**Nuance 1 — UInt8 → TINYINT**: TINYINT in SQL Server is 0-255 (unsigned-domain by coincidence), so UInt8 → TINYINT is safe for values 0-255. The comment "(unsigned domain via app)" is accurate. No concern.

**Nuance 2 — UInt16 → INT**: SQL Server has no unsigned 16-bit type. Polars UInt16 is 0-65,535; SQL Server SMALLINT is -32,768 to 32,767. Mapping UInt16 to INT (0-2.1B) is the correct widening choice to preserve the full domain. The mapping is correct but the rationale note "SQL Server has no unsigned 16-bit; widen to INT" could be more explicit about why SMALLINT would be WRONG here (half the UInt16 domain would overflow signed SMALLINT). A one-line clarification would prevent a future maintainer from "optimizing" to SMALLINT.

**No primary source formalizes this exact mapping table.** The Polars GitHub issue #12277 confirms that `read_database_uri` returns i64 for BIGINT, suggesting the reverse mapping (SQL Server → Polars) is i64 for BIGINT, consistent with Int64 → BIGINT [13].

**Relevance to North Star**: Operationally stable (type mismatches cause silent data corruption; the mapping table is the spec for table_creator.py's _polars_dtype_to_sql).

**Confidence**: MEDIUM-HIGH — mappings are correct per individual source docs; the absence of a primary unified source is the gap.

---

### Finding 7: Dual date-pair SCD2 design (UdmEffectiveDateTime/UdmEndDateTime + UdmSourceBeginDate/UdmSourceEndDate)

**Verdict**: PROJECT-SPECIFIC EXTENSION of Kimball Type-2 — appropriately scoped in CLAUDE.md; the supplement (01b § 3.1) presents it correctly without overclaiming

**Claim**: Bronze carries two independent date pairs. Load-time pair (UdmEffectiveDateTime/UdmEndDateTime) is the Silver/Gold contract per Kimball. Source-date pair (UdmSourceBeginDate/UdmSourceEndDate) is the R-2 business-date contract.

**External evidence**:

Kimball's canonical Type-2 specification prescribes exactly one effective/expiration date pair [14]: "row effective date or date/time stamp" + "row expiration date or date/time stamp" + "current row indicator." Kimball does NOT prescribe a second date pair.

However, the Kimball community forum and practitioners do discuss dual-date-pair implementations for pipelines where load date ≠ business effective date [15][16]. A Datavault Builder article on "Temporality in the Data Warehouse" (2021) explicitly models business_effective_date vs. technical_insert_date as separate attributes [17]. This is a recognized practitioner extension of Kimball Type-2, not canonical Kimball, but it is well-grounded in practitioner literature.

The supplement presents the two pairs with correct CLAUDE.md references (SCD2-P1-a) and does NOT claim Kimball endorsement. CLAUDE.md's "Do NOT" section explicitly warns "Do NOT change the semantic of UdmEffectiveDateTime or UdmEndDateTime — Silver and Gold read these as the load-time pair." This framing correctly identifies the load-time pair as the Silver/Gold consumer contract and the source-date pair as a project-specific addition.

**Assessment**: The supplement is correct and appropriately scoped. No overclaiming.

**Missing citation opportunity**: 01b § 3.1 could add a single sentence noting "The dual-date-pair pattern is a recognized extension of Kimball Type-2 for pipelines where source business date differs from data warehouse load date" with a reference to the Kimball forum discussion. This is a strengthening opportunity, not a correctness concern.

**Relevance to North Star**: Audit-grade (load-time pair enables regulatory traceability of when data arrived in UDM) + Traceability (source-date pair enables business temporal queries aligned to source-system change semantics).

**Confidence**: HIGH — design is correct and well-motivated; Kimball extension is practitioner-recognized.

---

### Finding 8: Dashboard query catalog per-audience structuring (Operations / Engineering / Compliance / Management)

**Verdict**: APPROPRIATELY SCOPED — per-audience structuring is industry practice; the specific four categories are reasonable though not a named standard

**Claim**: `phase1/01c_data_flow_walkthrough.md` § 9 presents 15 dashboard queries grouped by audience: Operations (§ 9.1, 9.6, 9.7, 9.11, 9.12), Engineering (§ 9.2, 9.3, 9.8, 9.9, 9.10, 9.15), Compliance (§ 9.4, 9.5, 9.13), Management (§ 9.14).

**External evidence**:

Role-based observability dashboard structuring is a recognized SRE and data-platform practice. The Google SRE Workbook describes structuring dashboards by audience: paging dashboards for on-call SREs (analogous to Operations), capacity dashboards for engineers (analogous to Engineering), and executive summaries for management. Datadog's documentation structures its views by persona similarly [18]. The specific four-audience split (Ops / Engineering / Compliance / Management) is not a named industry standard, but per-role dashboard structuring is canonical.

The Compliance audience is particularly well-motivated for this pipeline given the CCPA/CPRA scope and financial regulatory context (NORTH_STAR Audit-grade pillar). Queries 9.4 (PII tokenization) and 9.5 (decrypt access patterns) directly serve audit requirements.

Query 9.15 (reviewer effectiveness) is project-internal (queries `_reviewer_effectiveness.md` imported as a SQL table) and is explicitly labeled as hypothetical ("For Round 8 self-improvement-loop dashboards"). This scoping is appropriate.

**Missing citation opportunity**: The catalog could note "per-audience dashboard structuring follows the Google SRE Workbook pattern" or similar, but this is low priority — the audience split is intuitive and well-justified by the project's compliance context.

**Confidence**: HIGH — per-audience structuring is sound; four-category split is reasonable.

---

### Finding 9: BCP tab-delimiter convention

**Verdict**: APPROPRIATELY SCOPED — tab delimiter is BCP's native default; no concern

**Claim**: BCP CSV Contract uses tab (`\t`) delimiter.

**External evidence**:

Microsoft's BCP documentation confirms: "In character format (-c), the field terminator is a tab character (\t) and the row terminator is a newline (\n)" — tab-delimited is BCP's own native default [19]. The Azure Synapse Analytics COPY INTO command also defaults to comma-delimited CSV, but tab-delimited is a supported option [20]. AWS Glue and Snowflake COPY INTO both support configurable delimiters.

The project's choice of tab delimiter matches BCP's natural mode and avoids the comma-quoting complexity documented in the Red Gate "TSQL of CSV" article. No concern here.

**Confidence**: HIGH.

---

## Sources cited

| # | URL | Date accessed | Authority |
|---|---|---|---|
| 1 | https://www.ibm.com/think/topics/control-plane-vs-data-plane | 2026-05-11 | Vendor (IBM) — high |
| 2 | https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/overview.html | 2026-05-11 | Vendor (Apache Airflow) — high |
| 3 | https://www.getdbt.com/blog/data-control-plane-introduction | 2026-05-11 | Vendor (dbt Labs) — high |
| 4 | https://medium.com/@manik.ruet08/dbt-artifacts-deep-dive-how-to-use-run-results-manifest-and-metadata-for-observability-1a28e8e29896 | 2026-05-11 | Community — medium |
| 5 | https://opentelemetry.io/docs/concepts/signals/logs/ | 2026-05-11 | Vendor (CNCF/OpenTelemetry) — high |
| 6 | https://www.datadoghq.com/blog/ | 2026-05-11 | Vendor (Datadog) — high |
| 7 | https://grafana.com/blog/the-red-method-how-to-instrument-your-services/ | 2026-05-11 | Vendor (Grafana) — high |
| 8 | https://www.elastic.co/blog/observability-metrics | 2026-05-11 | Vendor (Elastic) — high |
| 9 | https://iceberg.apache.org/spec/ | 2026-05-11 | Vendor (Apache Iceberg) — high |
| 10 | https://mermaid.js.org/syntax/entityRelationshipDiagram.html | 2026-05-11 | Vendor (Mermaid.js) — high |
| 11 | https://docs.pola.rs/user-guide/concepts/data-types-and-structures/ | 2026-05-11 | Vendor (Polars) — high |
| 12 | https://learn.microsoft.com/en-us/sql/t-sql/data-types/int-bigint-smallint-and-tinyint-transact-sql?view=sql-server-ver16 | 2026-05-11 | Vendor (Microsoft) — high |
| 13 | https://github.com/pola-rs/polars/issues/12277 | 2026-05-11 | Project repo issue — medium |
| 14 | https://www.kimballgroup.com/data-warehouse-business-intelligence-resources/kimball-techniques/dimensional-modeling-techniques/type-2/ | 2026-05-11 | Primary (Kimball Group) — high |
| 15 | https://kimballgroup.forumotion.net/t3191-best-practice-for-scd2-start-and-end-dates | 2026-05-11 | Community (Kimball forum) — medium |
| 16 | https://kimballgroup.forumotion.net/t3313-scd-type-2-dimensions-and-facts | 2026-05-11 | Community (Kimball forum) — medium |
| 17 | https://datavault-builder.com/2021/07/12/scd_type2_output_dwh_data_vault/ | 2026-05-11 | Practitioner blog — medium |
| 18 | https://sre.google/workbook/index/ | 2026-05-11 | Primary (Google SRE) — high |
| 19 | https://learn.microsoft.com/en-us/sql/tools/bcp/bcp-utility?view=sql-server-ver17 | 2026-05-11 | Vendor (Microsoft) — high |
| 20 | https://learn.microsoft.com/en-us/azure/data-factory/format-delimited-text | 2026-05-11 | Vendor (Microsoft) — high |

---

## Summary verdicts

| Finding | Claim in supplement | External verdict | Category |
|---------|-------------------|-----------------|----------|
| 1 — Control-tier vs operational-metadata-tier | Two-tier separation by purpose/permissions/audit | Matches control-plane/data-plane canonical pattern; analogy not cited | APPROPRIATELY SCOPED (missing-citation opportunity) |
| 2 — Two-tables-two-purposes observability | EventLog = dashboard, PipelineLog = investigation | Matches RED method + OpenTelemetry metrics/logs split; vocabulary differs | APPROPRIATELY SCOPED (framing note) |
| 3 — § 10 bottleneck-investigation workflow | 5-step alert→drill-down workflow | Matches canonical SRE incident-response pattern exactly | APPROPRIATELY SCOPED |
| 4 — SchemaContract SupersededBy chain | Forward-link versioning of schema contracts | Project-specific; Iceberg uses backward-link; no industry standard for forward-link | APPROPRIATELY SCOPED (project-specific acknowledged implicitly) |
| 5 — Mermaid `||--o{` notation | Canonical crow's-foot ER cardinality | Confirmed canonical per Mermaid official docs | N/A to supplements (not used in these docs) |
| 6a — Integer type mapping (Int8→TINYINT, etc.) | Polars integer types to SQL Server equivalents | Correct per individual Polars + Microsoft docs; no unified primary source | APPROPRIATELY SCOPED (no unified primary source is the gap) |
| 6b — UInt16 → INT rationale | SMALLINT would overflow half of UInt16 domain | Correct; rationale note could be clearer | FRAMING NOTE |
| 7 — Dual date-pair SCD2 | Load-time pair + source-date pair independent | Kimball prescribes one pair; dual-pair is recognized practitioner extension; not overclaimed | APPROPRIATELY SCOPED |
| 8 — Per-audience dashboard catalog | Ops/Engineering/Compliance/Management split | Per-audience structuring is SRE best practice; four-category split reasonable | APPROPRIATELY SCOPED |
| 9 — BCP tab delimiter | Tab (\t) as BCP CSV delimiter | Confirmed BCP native default per Microsoft docs | APPROPRIATELY SCOPED |

---

## Actionable recommendations for producer / reviewers 1-4

These are advisory (non-blocking). Reviewers 1-4's verdicts determine clean/not-clean.

1. **B-new (low priority)**: Consider adding one sentence in 01a § 1 citing the control-plane / data-plane separation pattern, naming Airflow metadata DB and dbt manifest/run_results as industry analogues. Strengthens the conceptual claim for onboarding readers. (Finding 1)

2. **B-new (low priority)**: Consider adding one sentence in 01c § 8.1 naming the RED method (Rate, Errors, Duration) as the canonical basis for PipelineEventLog's per-step metrics. (Finding 2)

3. **B-new (low priority)**: In 01b § 6, clarify the UInt16 → INT row: add "SMALLINT would lose values 32,768-65,535 from UInt16's domain; widening to INT is correct." Prevents future "optimization" to SMALLINT. (Finding 6b)

4. **B04 confirmed load-bearing**: The SchemaContract two-step INSERT-then-UPDATE pattern (SupersededBy forward-link) requires the new row to exist before the old row can be updated. B04 (SchemaContract DDL hardening: self-FK on SupersededBy) remains the correct mitigation and is already tracked. Research confirms this risk. (Finding 4)

5. **No action on dual date-pair**: 01b correctly presents it as project-defined (SCD2-P1-a reference). No overclaiming. (Finding 7)

6. **No action on Mermaid notation**: Supplements don't use erDiagram. If 09_VISUALS.md uses `||--o{`, it is canonically correct per Mermaid official docs. (Finding 5)

---

## Overall confidence

OVERALL: MEDIUM-HIGH

Multiple authoritative sources confirm the core design decisions. The main gaps are:
- Missing external citations for the control-plane terminology (easily added)
- Missing unified primary source for the Polars→SQL Server type mapping table (inherent; no such source exists)
- SchemaContract SupersededBy is project-specific (not a concern — it's not claimed as a standard)

No framing in the supplements is materially misleading or unsupported. All claims are either grounded in primary documentation or appropriately scoped as project-specific.

---

## Counter-evidence considered

- Against the two-table observability pattern: OpenTelemetry unifies all signals (metrics/logs/traces) through a single SDK and wire format. This could be read as "the industry is moving toward unified pipelines, not two separate tables." However, OTel's unified SDK is for data COLLECTION; backends (Honeycomb, Grafana, Datadog) still maintain separate metrics stores vs. log stores internally. The two-table design is at the storage layer, which aligns with how backends work, not contradicts it.
- Against the control-tier naming: "control tier" vs "control plane" — the supplement uses "tier" not "plane." The vocabulary gap is minor; the concept is the same.
- Against the per-audience dashboard structuring: One could argue a single role-based access control layer on a unified view is more maintainable than separate query catalogs. This is a valid engineering trade-off, but it's a capability the pipeline doesn't have (no RBAC on the query results themselves), so the catalog approach is appropriate for the current design.

---

## What this research does NOT cover

- Snowflake COPY INTO load history patterns (Phase 5 scope)
- Parquet compression level benchmarks (not claimed in supplements)
- polars-hash plugin stability vs. alternatives
- Power BI-specific query compatibility (supplements note "SQL Server syntax shown; trivially adaptable" — that claim was not verified)

---

## Last reviewed

2026-05-11 (Round 1.5 Cycle 1 — initial research run for Pattern E 5th slot advisory)
