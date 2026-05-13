# UDM Pipeline — Visuals

System-level diagrams in Mermaid. Renders in GitHub, VS Code, most modern markdown viewers. Source-controlled with the rest of the docs.

## 1. CDC append vs Snapshot vs SCD2 — clarification

The most common misunderstanding on the team. This pipeline does **snapshot data**, not traditional CDC append. The distinction matters for how we document the system to other engineers.

```mermaid
graph TB
    subgraph TraditionalCDC["Pattern A: Traditional CDC Append (NOT what we do)"]
        A1["Source mutation occurs<br/>(INSERT, UPDATE, DELETE)"]
        A1 --> A2["DB log captures the EVENT"]
        A2 --> A3["Append-only event log<br/>op=I/U/D, before/after, LSN"]
        A3 --> A4["Each row in log = a CHANGE"]
    end
    
    subgraph SnapshotData["Pattern B: Snapshot Data (what we do)"]
        B1["Pipeline schedule fires<br/>(02:00 AM, 17:00 PM)"]
        B1 --> B2["Extract full row state<br/>via windowed query"]
        B2 --> B3["Per-run Parquet file<br/>tokens replace PII"]
        B3 --> B4["Each row in Parquet = a STATE OBSERVATION"]
    end
    
    subgraph SCD2["Pattern C: SCD2 in Bronze (downstream of snapshot)"]
        C1["Snapshot DataFrame<br/>(in Python memory)"]
        C1 --> C2["Hash compare vs Bronze active rows"]
        C2 --> C3["Detect: new / changed / unchanged / deleted"]
        C3 --> C4["Write new Bronze versions only on actual change"]
        C4 --> C5["Each Bronze row = a STATE FOR A TIME RANGE<br/>(UdmEffectiveDateTime / UdmEndDateTime)"]
    end
    
    style TraditionalCDC fill:#ffeeee
    style SnapshotData fill:#eeffee
    style SCD2 fill:#eeeeff
```

**Key takeaway**: when an engineer says "we're doing CDC," they may mean "we're capturing changes" (true) — but the CDC pattern at the storage level is **snapshot + change detection downstream**, not append-only event log. The Stage layer that traditional CDC implementations use is removed from this pipeline.

## 2. End-to-end data flow

```mermaid
graph LR
    Source[("Source DB<br/>Oracle / SQL Server")]
    Source -->|Polars + ConnectorX extract| Pipeline
    
    Pipeline["Python Pipeline<br/>(Linux server)"]
    Pipeline -->|tokenize PII via vault| Pipeline
    Pipeline -->|hash + add metadata| Pipeline
    Pipeline -->|write Parquet| NetworkDrive
    Pipeline -->|SCD2 vs Bronze active| Bronze
    Pipeline -->|log events| MetadataTables
    
    NetworkDrive[("Network Drive<br/>Parquet snapshots<br/>Hive partitioned")]
    NetworkDrive -.->|async upload| SnowflakeStage
    
    Bronze[("UDM_Bronze<br/>SCD2 dimension<br/>SQL Server")]
    Bronze -.->|async mirror| SnowflakeBronze
    
    SnowflakeStage[("Snowflake Iceberg<br/>external Parquet")]
    SnowflakeBronze[("Snowflake Bronze<br/>analytics queryable")]
    
    SnowflakeStage --> Analytics
    SnowflakeBronze --> Analytics
    
    Analytics["Silver/Gold<br/>(downstream teams)"]
    
    MetadataTables[("General.ops<br/>13+ metadata tables")]
    MetadataTables -.->|Power BI| Dashboards
    Dashboards["Power BI Dashboards<br/>ops + audit views"]
    
    Vault[("PiiVault<br/>SQL Server")]
    Pipeline -->|tokens| Vault
    
    style Source fill:#ddd
    style Bronze fill:#fdf
    style NetworkDrive fill:#dfd
    style Vault fill:#fdd
    style Analytics fill:#ddf
```

## 3. Idempotency layers

What makes a re-run produce zero net writes:

```mermaid
graph TD
    Run["Pipeline run with BatchId X"]
    Run --> L1
    
    L1["Layer 1: Idempotency Ledger<br/>Status='COMPLETED' for prior step?<br/>YES → skip"]
    L1 -->|else| L2
    
    L2["Layer 2: Source extract<br/>TRUNC date boundaries → byte-identical query<br/>Same source state → byte-identical extract"]
    L2 --> L3
    
    L3["Layer 3: PII tokenization<br/>Vault lookup-before-insert<br/>Same plaintext → same token"]
    L3 --> L4
    
    L4["Layer 4: Hash computation<br/>polars-hash plugin = deterministic<br/>Same row data → same _row_hash"]
    L4 --> L5
    
    L5["Layer 5: Parquet write<br/>Stage-check-exchange<br/>UNIQUE registry + filename includes BatchId"]
    L5 --> L6
    
    L6["Layer 6: SCD2 promotion<br/>Hash compare vs Bronze UdmHash<br/>Equal hash = no write"]
    L6 --> L7
    
    L7["Layer 7: Delete detection<br/>Window-scoped + trust-gated + verify-before-close<br/>Re-evaluation produces same candidate set"]
    L7 --> L8
    
    L8["Layer 8: Snowflake replication<br/>COPY INTO with LOAD_HISTORY dedup"]
    L8 --> Done["Done — zero net writes if state unchanged"]
    
    style L1 fill:#ddf
    style L8 fill:#dfd
```

## 4. AM/PM cycle with failover and cancellation

```mermaid
sequenceDiagram
    participant Automic
    participant ProdServer as Production Server
    participant Gate as PipelineExecutionGate
    participant TestServer as Test Server
    participant Operator
    
    Note over Automic: 02:00 AM — production cycle starts
    Automic->>ProdServer: Start pipeline (AM cycle)
    ProdServer->>Gate: Acquire gate (Status=STARTING)
    ProdServer->>Gate: Update Status=RUNNING
    
    loop Every 5 min
        ProdServer->>Gate: Heartbeat (LastHeartbeatAt)
        ProdServer->>Gate: Check CancellationRequested
    end
    
    alt Production succeeds
        ProdServer->>Gate: Update Status=SUCCEEDED
        Note over Automic: 04:30 AM — test pipeline checks
        Automic->>TestServer: Start failover check (AM)
        TestServer->>Gate: Read Status
        Gate-->>TestServer: SUCCEEDED
        TestServer-->>Automic: Exit cleanly (no failover needed)
    else Production stuck
        Note over Automic: 04:30 AM — test pipeline checks
        Automic->>TestServer: Start failover check (AM)
        TestServer->>Gate: Read Status (RUNNING + stale heartbeat)
        TestServer->>Gate: Set CancellationRequested=1
        ProdServer->>Gate: Read CancellationRequested=1
        ProdServer->>ProdServer: Finish current table; release locks; flush logs
        ProdServer->>Gate: Update Status=CANCELLED
        TestServer->>Gate: Detect ack
        TestServer->>Gate: Acquire gate as test (Status=STARTING, ExecutingServer=test)
        TestServer->>Gate: Update Status=RUNNING (failover)
        TestServer->>Gate: Update Status=SUCCEEDED
    else Production stuck and doesn't acknowledge
        TestServer->>Gate: Set CancellationRequested=1
        Note over TestServer: Wait 15 min — no acknowledgment
        TestServer->>Operator: ALERT: manual intervention required
        Note over TestServer: Test does NOT proceed automatically
    end
```

## 5. PII tokenization flow

```mermaid
graph TD
    Plaintext["Plaintext PII<br/>e.g., SSN '123-45-6789'"]
    Plaintext --> Hash
    Hash["Compute SHA-256<br/>of plaintext"]
    Hash --> Lookup
    Lookup{"Vault lookup<br/>(PiiType, SourceName, PlaintextHash)"}
    
    Lookup -->|Found| ExistingToken["Return existing Token<br/>(idempotent)"]
    Lookup -->|Not found| NewToken["Generate new Token (GUID)<br/>INSERT into PiiVault"]
    
    NewToken --> NewProvenance["INSERT into PiiTokenProvenance<br/>(append-only first-observation)"]
    ExistingToken --> ProvenanceCheck
    NewProvenance --> ProvenanceCheck
    
    ProvenanceCheck{"Provenance row exists for<br/>(Token, Source, Object, Column)?"}
    ProvenanceCheck -->|Yes| Done
    ProvenanceCheck -->|No| InsertProvenance
    InsertProvenance["INSERT new provenance row<br/>(append-only)"]
    InsertProvenance --> Done
    
    Done["Token returned to pipeline<br/>Plaintext never leaves vault"]
    Done --> BatchAudit["Update PiiTokenizationBatch<br/>(NewTokensGenerated, ExistingTokensReused)"]
    
    style Plaintext fill:#fdd
    style Done fill:#dfd
```

## 6. Phase dependency graph

```mermaid
graph LR
    P0["Phase 0<br/>Decisions"]
    P1["Phase 1<br/>Foundation"]
    P2["Phase 2<br/>Pilot"]
    P3["Phase 3<br/>Large tables"]
    P4["Phase 4<br/>Production rollout"]
    P5["Phase 5<br/>Snowflake"]
    P6["Phase 6<br/>Health, Lineage & Catalog"]
    
    P0 --> P1
    P1 --> P2
    P2 --> P3
    P2 --> P4
    P3 --> P4
    P4 --> P5
    P4 --> P6
    P5 --> P6
    
    style P0 fill:#fff8dc
    style P1 fill:#dde
    style P6 fill:#cfc
```

Phase 4 doesn't strictly require Phase 3 to complete — small tables can roll out before large-table support is fully ready, since they don't use the trust-gate delete logic. But large tables in Phase 4 do depend on Phase 3.

## 7. Phase 1 deep dive rounds

```mermaid
graph TD
    R1["Round 1<br/>Database Schema"]
    R2["Round 2<br/>Configuration"]
    R3["Round 3<br/>Core Modules"]
    R4["Round 4<br/>Tools"]
    R5["Round 5<br/>Tests"]
    R6["Round 6<br/>Deployment"]
    R7["Round 7<br/>Schema Evolution Governance"]
    
    R1 --> R2
    R1 --> R3
    R2 --> R3
    R3 --> R4
    R3 --> R5
    R4 --> R5
    R5 --> R6
    R1 --> R7
    
    style R1 fill:#ffd
```

Round 1 (DDL) gates everything else. Round 2 (config) and Round 3 (modules) depend on the schema being final. Tools (Round 4) build on modules. Tests (Round 5) cover modules + tools. Deployment (Round 6) is the final gate. Schema evolution governance (Round 7) builds on the schema.

## 8. Failure recovery layered model

```mermaid
graph TB
    subgraph Operational["Layer 1: Operational state"]
        Bronze[(Bronze SCD2)]
        Stage[(Idempotency Ledger)]
        EventLog[(PipelineEventLog)]
    end
    
    subgraph Durable["Layer 2: Durable substrate"]
        Parquet[(Parquet on Network Drive)]
        Vault[(PiiVault + Provenance)]
        Registry[(ParquetSnapshotRegistry)]
    end
    
    subgraph Source["Layer 3: Source of truth"]
        SourceDB[(Source DB<br/>Oracle / SQL Server)]
    end
    
    Operational -.->|"recovery if needed"| Durable
    Durable -.->|"last-resort recovery<br/>only if both above fail"| Source
    
    Note1["Crash mid-run → Layer 1 recovery via ledger"]
    Note2["Bronze drift → Layer 2 recovery from Parquet replay"]
    Note3["Catastrophic loss → Layer 3 source re-extract (within source retention)"]
    
    style Operational fill:#ddf
    style Durable fill:#dfd
    style Source fill:#fdd
```

## 9. CCPA right-to-deletion data flow

```mermaid
sequenceDiagram
    participant Customer
    participant CustomerService
    participant Operator
    participant Vault as PiiVault
    participant Bronze
    participant CcpaLog as CcpaDeletionLog
    
    Customer->>CustomerService: Submit deletion request
    CustomerService->>Operator: Verified request + identifiers
    Operator->>CcpaLog: Insert request row (RequestId, identifiers)
    Operator->>Vault: Identify all tokens for plaintext identifiers
    Vault-->>Operator: Token list with LegalHold flags
    
    alt All tokens have LegalHold=0
        Operator->>Vault: UPDATE Status='deleted_per_request' for all tokens
        Vault-->>Operator: Tokens now orphan references in Bronze
        Operator->>CcpaLog: Action='deleted', ProcessedAt=now
    else Some tokens have LegalHold=1
        Operator->>Vault: UPDATE Status only for non-legal-hold tokens
        Operator->>CcpaLog: Action='partial', LegalExceptionReason
        Note over Customer: Customer notified of legal exception per CCPA
    end
    
    Note over Bronze: Bronze rows NOT physically scrubbed<br/>(audit trail preserved; tokens become orphan refs)
```

## ER diagrams — General.dbo control tier + General.ops operational metadata tier (added Round 1.5e 2026-05-11)

These ER diagrams supplement Round 1 + Round 2 schema content. They show table relationships visually for the 26 tables across both schemas (`General.dbo.*` control tier × 2 + `General.ops.*` operational metadata tier × 24). Each cluster is its own diagram for readability.

### Control tier — UdmTablesList ↔ UdmTablesColumnsList

```mermaid
erDiagram
    UdmTablesList ||--o{ UdmTablesColumnsList : "drives column inventory"
    UdmTablesList {
        nvarchar SourceName PK
        nvarchar SourceObjectName PK
        nvarchar SourceServer
        nvarchar SourceDatabase
        nvarchar SourceSchemaName
        nvarchar StageLoadTool
        nvarchar SourceAggregateColumnName
        nvarchar SourceIndexHint
        nvarchar PartitionOn
        nvarchar StageTableName
        nvarchar BronzeTableName
        bit StripSuffix
        bigint MaxRowsPerDay
        nvarchar SCD2Mode
        nvarchar SCD2DateColumns
        nvarchar ExcludeFromHash
        int ExpectedRetentionDays
        nvarchar LastModifiedColumn
        nvarchar CDCMode
        nvarchar PiiColumnList
        nvarchar DataClassification
        nvarchar CohortAssignment
        bit IsEnabled
        bit LegalHoldOnly
    }
    UdmTablesColumnsList {
        nvarchar SourceName PK
        nvarchar TableName PK
        nvarchar Layer PK
        nvarchar ColumnName PK
        int OrdinalPosition
        bit IsPrimaryKey
        bit IsIndex
        nvarchar IndexName
        nvarchar IndexType
        nvarchar ObjectType
        nvarchar DatabaseName
        datetime MetadataLastUpdated
    }
```

### PII / Vault / Compliance cluster

```mermaid
erDiagram
    PiiVault ||--o{ PiiTokenProvenance : "first-observation history"
    PiiVault ||--o{ PiiVaultAccessLog : "decrypt audit trail"
    PiiVault ||--o{ CcpaDeletionLog : "right-to-deletion target"
    PiiVault ||--o{ OrphanedTokenLog : "post-retention cleanup audit"
    PiiTokenizationBatch ||--o{ PiiTokenProvenance : "batch context"
    
    PiiVault {
        bigint TokenId PK
        varchar Token UK
        binary EncryptedPlaintext
        nvarchar PiiType "SSN/EIN/EMAIL/NAME/ACCOUNT/PHONE/ADDRESS/OTHER"
        nvarchar SourceName
        datetime CreatedAt
        nvarchar Status "active/deleted_per_request/purged_for_retention/legal_hold_only"
        bit LegalHold
        datetime RetentionExpiresAt
    }
    PiiTokenProvenance {
        bigint ProvenanceId PK
        bigint TokenId FK
        nvarchar SourceName
        nvarchar SourceObjectName
        datetime FirstObservedAt
        bigint FirstObservedBatchId
    }
    PiiTokenizationBatch {
        bigint BatchTokenizationId PK
        bigint BatchId
        nvarchar SourceName
        nvarchar ObjectName
        nvarchar ColumnName
        datetime TokenizedAt
        bigint NewTokensGenerated
        bigint ExistingTokensReused
        bigint TotalRowsTokenized
        bigint DurationMs
    }
    PiiVaultAccessLog {
        bigint AccessId PK
        uniqueidentifier RequestId
        bigint TokenId FK
        nvarchar Justification
        nvarchar RequestedBy
        nvarchar Actor
        datetime AccessedAt
    }
    CcpaDeletionLog {
        bigint DeletionId PK
        uniqueidentifier RequestId UK
        datetime RequestedAt
        nvarchar RequestedBy
        nvarchar SubjectIdentifier
        nvarchar AffectedTokens
        nvarchar Action "deleted/partial/legal_hold_override/pending"
        nvarchar LegalExceptionReason
        datetime ProcessedAt
        nvarchar ProcessedBy
        datetime NotifiedConsumerAt
    }
    OrphanedTokenLog {
        bigint OrphanLogId PK
        varchar Token FK
        datetime OrphanedAt
        nvarchar OrphanReason "ccpa_deletion/retention_purge/manual_override/legal_hold_release"
        nvarchar OrphanReference
        nvarchar DownstreamSummary
        bigint TotalDownstreamRows
        bit NotificationSent
        nvarchar Status "logged/notified/scrubbed"
    }
```

### Pipeline orchestration + state tier

```mermaid
erDiagram
    PipelineBatchSequence ||--o{ PipelineEventLog : "groups events by batch"
    PipelineBatchSequence ||--o{ PipelineLog : "groups narrative logs"
    PipelineExecutionGate ||--o{ PipelineEventLog : "gate-state observed"
    IdempotencyLedger ||--o{ PipelineEventLog : "step-state observed"
    MaintenanceWindow ||--o{ PipelineEventLog : "suppression context"
    PipelineExtraction ||--o{ DeleteEvaluationAudit : "per-day delete decisions"
    PipelineExtraction ||--o{ ExtractionGapLog : "gap detection"
    
    PipelineBatchSequence {
        bigint BatchId PK
    }
    PipelineEventLog {
        bigint EventId PK
        bigint BatchId FK
        nvarchar EventType "CLI_/CYCLE_/MIGRATION_/DEPLOYMENT_/STARTUP_/EXTRACT/CDC_PROMOTION/SCD2_PROMOTION/TABLE_TOTAL"
        nvarchar SourceName
        nvarchar TableName
        datetime StartedAt
        datetime CompletedAt
        int DurationMs
        nvarchar Status "IN_PROGRESS/SUCCESS/FAILED/SKIPPED"
        int RowsProcessed
        nvarchar Metadata "JSON"
    }
    PipelineLog {
        bigint LogId PK
        bigint BatchId FK
        nvarchar LogLevel
        nvarchar Module
        nvarchar Message
        nvarchar StackTrace
        datetime CreatedAt
    }
    PipelineExecutionGate {
        bigint GateId PK
        nvarchar CycleType "AM/PM"
        date CycleDate
        nvarchar ExecutingServer
        nvarchar Status
        datetime ActualStartTime
        datetime ActualCompletionTime
        datetime LastHeartbeatAt
        bit CancellationRequested
    }
    IdempotencyLedger {
        bigint LedgerId PK
        bigint BatchId FK
        nvarchar SourceName
        nvarchar TableName
        nvarchar EventType
        nvarchar Status
        datetime StartedAt
        nvarchar ErrorMessage
    }
    PipelineExtraction {
        bigint ExtractionId PK
        bigint BatchId
        nvarchar SourceName
        nvarchar TableName
        date DateValue
        nvarchar Status "IN_PROGRESS/SUCCESS/FAILED"
        datetime StartedAt
        datetime CompletedAt
        datetime EvaluatedAt
        bigint RowsExtracted
        bit IsReExtraction
        int ExtractionAttempt
        nvarchar FailureReason
    }
    PromotionLock {
        bigint LockId PK
        datetime LockedAt
        nvarchar LockedBy
        nvarchar Reason
        datetime ReleasedAt
        nvarchar ReleasedBy
        bit Active "computed: 1 when ReleasedAt IS NULL"
    }
    MaintenanceWindow {
        bigint WindowId PK
        datetime StartAt
        datetime EndAt
        nvarchar AffectedComponent "production_pipeline/test_pipeline/all"
        nvarchar Reason
        nvarchar CreatedBy
        datetime CreatedAt
    }
    DeleteEvaluationAudit {
        bigint AuditId PK
        bigint BatchId
        nvarchar SourceName
        nvarchar TableName
        date DateValue
        datetime EvaluatedAt
        nvarchar EvaluationOutcome "evaluated/suppressed_no_success/suppressed_all_failed/no_candidates"
        bigint AuthoritativeBatchId
        bigint BronzeActiveCount
        bigint CandidateDeleteCount
        bigint ConfirmedDeleteCount
        nvarchar SuppressedReason
    }
    ExtractionGapLog {
        bigint GapLogId PK
        nvarchar SourceName
        nvarchar TableName
        date MissingFromDate
        date MissingToDate
        nvarchar Classification "never_attempted/all_attempts_failed/beyond_source_retention"
        datetime DetectedAt
        bigint DetectedByBatchId
        nvarchar Resolution "PENDING/BACKFILLED/ACCEPTED/NO_LONGER_RECOVERABLE"
        datetime ResolvedAt
        nvarchar ResolvedBy
        nvarchar Reason
    }
```

### Snapshot + reconciliation tier

```mermaid
erDiagram
    ParquetSnapshotRegistry ||--o{ ReconciliationLog : "validated snapshot"
    ReconciliationLog ||--o{ SCD2RepairLog : "follow-on repair"
    ReconciliationLog ||--o{ HealthCheckLog : "informs health metrics"
    
    ParquetSnapshotRegistry {
        bigint RegistryId PK
        nvarchar SourceName
        nvarchar TableName
        bigint BatchId
        date BusinessDate
        nvarchar StorageTier "hot/warm/cold/snowflake_staged"
        bigint CompressedBytes
        bigint UncompressedBytes
        varchar Checksum
        datetime CreatedAt
        datetime LastVerifiedAt
        datetime PurgedAt
        nvarchar SnowflakeStagePath
    }
    ReconciliationLog {
        bigint ReconciliationId PK
        bigint BatchId
        nvarchar SourceName
        nvarchar TableName
        nvarchar CheckType "reconcile_counts/reconcile_active_pks/reconcile_bronze/reconcile_aggregates/reconcile_table"
        nvarchar Status
        int DiscrepancyCount
        datetime CompletedAt
    }
    SCD2RepairLog {
        bigint RepairId PK
        nvarchar SourceName
        nvarchar TableName
        nvarchar RepairType "sentinel_fill/orphan_cleanup/duplicate_active_dedup"
        nvarchar Status
        int RowsAffected
        nvarchar SamplePks "JSON"
        datetime StartedAt
        datetime CompletedAt
    }
    HealthCheckLog {
        bigint HealthCheckId PK
        bigint BatchId
        nvarchar CheckName
        nvarchar SourceName
        nvarchar TableName
        datetime StartedAt
        datetime CompletedAt
        nvarchar Status "OK/INFO/WARNING/ERROR/CRITICAL"
        decimal Value
        decimal Threshold
        nvarchar Findings "JSON"
        bit Acknowledged
        datetime AcknowledgedAt
        nvarchar AcknowledgedBy
    }
```

### Lifecycle + governance tier

```mermaid
erDiagram
    SchemaContract ||--o| SchemaContract : "SupersededBy self-reference"
    ExtractionRangePolicy ||--o{ LatenessProfile : "policy informs L_99 measurement"
    
    TableEnablementLog {
        bigint EnablementId PK
        nvarchar SourceName
        nvarchar TableName
        datetime EnabledAt
        nvarchar EnabledBy
        bigint EnabledBatchId
        datetime FirstSuccessfulRunAt
        nvarchar Cohort
        nvarchar SignoffUser
        datetime SignoffAt
        nvarchar Notes
    }
    ManualCorrectionLog {
        bigint CorrectionId PK
        bigint BatchId
        nvarchar SourceName
        nvarchar TableName
        nvarchar CorrectionType
        nvarchar Description
        nvarchar Actor
        nvarchar Justification
        datetime CorrectedAt
    }
    SchemaContract {
        bigint ContractId PK
        nvarchar SourceName
        nvarchar ObjectName
        nvarchar ColumnName
        nvarchar ContractKey
        nvarchar ContractValue
        datetime EffectiveFrom
        datetime EffectiveTo
        bigint SupersededBy FK
        nvarchar Notes
        nvarchar CreatedBy
    }
    ExtractionRangePolicy {
        bigint RangeId PK
        nvarchar SourceName
        nvarchar TableName
        date RangeStartDate
        date RangeEndDate
        nvarchar RangeKind "current/lookback/backfill/reconciliation"
        int MaxStaleDays
        int Priority
        datetime LastExtractedAt
        datetime LastSuccessAt
        bit Active
        nvarchar Notes
    }
    LatenessProfile {
        bigint ProfileId PK
        nvarchar SourceName
        nvarchar TableName
        datetime MeasuredAt
        int MeasurementWindowDays
        nvarchar BusinessDateColumn
        nvarchar LastModifiedColumn
        decimal LatenessP50
        decimal LatenessP90
        decimal LatenessP95
        decimal LatenessP99
        decimal LatenessP999
        decimal LatenessMax
        int RecommendedLookback
        decimal SafetyFactor
        int CurrentConfiguredLookback
        decimal PreviousP99
        decimal DriftPct
        bigint SampleRowCount
    }
```

**How to read these diagrams**: each diagram shows ONE cluster of related tables. Cross-cluster joins (e.g., `PipelineEventLog.SourceName` → `UdmTablesList.SourceName`) happen at runtime via the join columns shown in each block. Column names + types match canonical Round 1 schema (`phase1/01_database_schema.md`) post-B173 comprehensive canonical sweep 2026-05-11. Column lists may be illustrative subsets (full DDL — including indexes + CHECK constraints + storage forecasts — lives in the canonical schema doc).

## How to add a new diagram

1. Identify the audience (engineers / management / auditors / operators)
2. Decide diagram type (graph for static structure, sequenceDiagram for time-ordered flows, flowchart for decisions, erDiagram for relationships)
3. Add the diagram to this file or to the relevant phase's `00_phase_overview.md`
4. Reference from the appropriate text doc (e.g., "see Visuals §3 for idempotency layers")
5. Test rendering in GitHub or VS Code before committing
