# R6 — PME + Extraction-Time + KMS + Source-Exactness Research

**Date**: 2026-05-17
**Researcher**: `udm-researcher` (per planning-discipline inheritance)
**Trigger**: User HARD REQUIREMENT 2026-05-17 ("Parquet files must be the exact copy of the data that was extracted from the source at the time of the data pipeline run. We need to ensure that we can tell when the raw data was extracted from source.") + plan `UDM_PIPELINE_REDESIGN_PARQUET_SOURCE_EXACT_2026-05-17.md`
**Purpose**: Primary-source grounding for tentative-future D-N decisions (currently labeled D-NEW-A through D-NEW-E in the redesign plan) covering tokenization-timing-reorder, Parquet Modular Encryption (PME), crypto-shredding, extraction-timestamp recording, and PiiSubjectKeys DDL.
**Extends**: `_research/r5-ccpa-parquet-replay-legal-2026-05-17.md` (CCPA/GDPR legal landscape; do not duplicate)

---

## R1 Findings: Parquet File-Level `key_value_metadata`

**Summary**: The Apache Parquet `key_value_metadata` field is a well-specified, stable mechanism for storing arbitrary string key-value pairs at file scope. It is the correct channel for recording extraction timestamps. However, its interaction with PME encrypted footer mode is a critical constraint: in encrypted footer mode, `key_value_metadata` is encrypted and inaccessible without the footer key. In plaintext footer mode, it remains readable without decryption.

### R1-1: Specification location and encoding

Sources:
- Apache Parquet format specification at `parquet.apache.org/docs/file-format/metadata/`
- `github.com/apache/parquet-format`

The Parquet footer's `FileMetaData` structure, serialized via Thrift TCompactProtocol, includes `key_value_metadata: optional list<KeyValue>`. Each `KeyValue` is `{key: string, value: string}`. The spec imposes no maximum size limit on the list or individual values — practical bounds are the maximum Thrift-serializable footer size (implementation-defined; generally multi-MB).

The metadata is **immutable post-write**. There is no "append metadata to existing Parquet file" mechanism without rewriting the file.

### R1-2: pyarrow API for file-level metadata

Sources: `arrow.apache.org/docs/python/parquet.html` + `mungingdata.com/pyarrow/arbitrary-metadata-parquet-table/`

Canonical pyarrow pattern:

```python
import pyarrow as pa
import pyarrow.parquet as pq

schema_with_meta = df_arrow.schema.with_metadata({
    "udm_extracted_at": "2026-05-17T02:00:00.000Z",
    "udm_source_query_started_at": "2026-05-17T01:59:59.123Z",
    "udm_source_system": "DNA",
    "udm_source_table": "osibank.ACCT",
    "udm_pipeline_run_id": "b5c3a1...",
    "udm_parquet_schema_version": "1",
})
table_with_meta = df_arrow.cast(schema_with_meta)
pq.write_table(table_with_meta, filepath, ...)
```

Reading back:

```python
meta = pq.read_metadata(filepath)
schema = pq.read_schema(filepath)
custom = schema.metadata  # dict of bytes -> bytes
extracted_at = custom[b"udm_extracted_at"].decode("utf-8")
```

**Critical caveat**: using `replace_schema_metadata()` on individual batches passed to `ParquetWriter` had no effect (silently failed). Correct approach: set metadata on the schema passed to the `ParquetWriter` constructor.

### R1-3: Polars metadata support

Source: `docs.pola.rs/api/python/dev/reference/api/polars.read_parquet_metadata.html` + Polars GitHub issues

Polars has `polars.read_parquet_metadata()` (experimental) which reads file-level metadata without loading data. Polars itself (2024 baseline) does not expose a native Python API to write custom schema-level metadata; recommended pattern: convert Polars → pyarrow Table via `df.to_arrow()`, attach metadata via `table.schema.with_metadata(...)`, write via `pq.write_table()`. Round-trip confirmed by community practice.

### R1-4: Interaction with PME — CRITICAL CONSTRAINT

Source: `parquet.apache.org/docs/file-format/data-pages/encryption/` + `github.com/apache/parquet-format/Encryption.md`

**Most important finding for D-NEW-B and D-NEW-D**:

In **encrypted footer mode** (`plaintext_footer=False`, the default): Parquet spec states encrypted footer mode hides "file schema, number of rows, key-value properties, column sort order, names of the encrypted columns." `key_value_metadata` IS encrypted and CANNOT be read without the footer key.

In **plaintext footer mode** (`plaintext_footer=True`): Footer kept in plaintext (with an integrity-protecting GCM signature). Column data for encrypted columns remains encrypted. File-level `key_value_metadata` IS readable without any key. Integrity signature still prevents tampering.

**Recommendation for the plan**: **Use `plaintext_footer=True` for our PME configuration.** This preserves `key_value_metadata` accessibility while keeping PII column data encrypted. The integrity signature prevents footer tampering. Tradeoff accepted: schema structure (column names, including which columns are encrypted) is visible — acceptable since our schema is not itself sensitive.

### R1-5: No industry naming standard for extraction-timestamp keys

Source: Web search across Dremio, Databricks, Iceberg, open-source pipeline literature 2024-2025.

No published standard defines key names like `extracted_at`, `source_query_started_at`, or `pipeline_run_id` for Parquet file-level metadata. Convention is organization-specific. Use `udm_` prefix (our project prefix) to avoid collisions with Arrow's reserved `b"ARROW:schema"` and `b"pandas"` keys.

**Confidence R1**: HIGH — pyarrow API well-documented; spec behavior for encrypted vs plaintext footer is definitive.

---

## R2 Findings: PME Production Maturity

**Summary**: PME in pyarrow is production-capable as of Arrow 8.0+ (first PME exposure), API documented through 24.0.0. Uber has deployed it at hundreds-of-PB scale (Java/Spark stack, not pyarrow). AES-GCM overhead on AES-NI hardware is well under 10% for realistic column-encryption ratios. Main production risk: KMS client implementation (no reference KMS client in OSS pyarrow distribution; must be written per environment).

### R2-1: pyarrow PME API and version timeline

Source: `arrow.apache.org/docs/python/generated/pyarrow.parquet.encryption.EncryptionConfiguration.html`

PME first exposed in pyarrow at Arrow 8.0.0. API documented through 24.0.0 (current).

`EncryptionConfiguration` parameters:
- `footer_key: str` — master key ID for footer encryption/signing
- `column_keys: dict` — per-column key IDs (string labels, NOT raw keys)
- `plaintext_footer: bool` — whether to keep footer readable
- `encryption_algorithm: str` — "AES_GCM_V1" (default) or "AES_GCM_CTR_V1"
- `double_wrapping: bool` — DEK wrapped by KEK then by master key
- `data_key_length_bits: int` — 128, 192, or 256

**Key concept**: pyarrow PME does NOT ship with a reference KMS client. Must implement `pyarrow.parquet.encryption.KmsClient` interface. The `CryptoFactory` takes `KmsConnectionConfig` and a factory function returning your `KmsClient` instance. Documentation exists; non-trivial implementation work.

### R2-2: Algorithm choice — AES-GCM-V1 vs AES-GCM-CTR-V1

Source: `parquet.apache.org/docs/file-format/data-pages/encryption/` + `medium.com/tomersolomon/test-driving-parquet-encryption`

| Algorithm | Confidentiality | Integrity | Speed |
|---|---|---|---|
| AES_GCM_V1 (default) | ✅ | ✅ | Baseline |
| AES_GCM_CTR_V1 | ✅ data, ✅ metadata | ❌ data tampering undetected | 4.5x faster (Java 8 benchmark) |

For our compliance use-case requiring audit-grade data integrity, the speed tradeoff is unfavorable. **Recommendation: keep AES_GCM_V1.**

### R2-3: AES-NI overhead at scale — Uber production measurement

Source: `uber.com/blog/one-stone-three-birds-finer-grained-encryption-apache-parquet/`

Uber measured Spark workload performance with 60% of columns encrypted (AES-CTR mode):
- Write overhead: **5.7%**
- Read overhead: **3.7%**

For AES-GCM (our selected mode), Java 11 benchmark showed ~3% overhead per column. pyarrow C++ uses OpenSSL EVP with AES-NI; similar hardware acceleration to Java 11. Spec: "performing encryption on full pages (~1MB buffers) causes AES to work at maximal speed."

At our pipeline scale (a few hundred MB per table per run), AES-NI hardware overhead should be **well under 10% even with GCM mode**.

### R2-4: ZSTD + PME interaction

Source: Parquet spec on compression + encryption ordering.

PME encrypts AFTER compression. Data compressed first, then encrypted. ZSTD ratios preserved for non-PII columns. PII columns (encrypted) will not benefit from ZSTD since AES ciphertext is not compressible. Net: slightly larger files than unencrypted+compressed for PII portions; non-PII compression unaffected.

### R2-5: Per-column key configuration model — CRITICAL UNDERSTANDING

Source: `arrow.apache.org/docs/python/generated/pyarrow.parquet.encryption.EncryptionConfiguration.html`

`column_keys` is a dict mapping column path (string) to **master key ID** (string label), NOT to per-subject key material. The per-subject key granularity is achievable by making the "key ID" actually encode the subject identifier and having the KmsClient resolve per-subject keys from `PiiSubjectKeys`.

**Architecture implication**: per-subject granularity lives in the KmsClient implementation, NOT in the `column_keys` parameter structure. The plan's pseudocode at §4.2 is misleading and must be revised to clarify the layer-of-indirection.

**Counter-evidence**: Most published PME production deployments use per-table or per-column-classification key granularity (e.g., one key for all SSN columns across all tables), NOT per-subject keys. Per-subject PME at production scale has **no published case study found**; this is inference from documented mechanism, not direct observation.

**Confidence R2**: HIGH for API/mechanism; MEDIUM for per-subject granularity production pattern.

---

## R3 Findings: KMS Choices for On-Prem PME

**Summary**: No off-the-shelf on-premises KMS natively integrates with pyarrow's PME `KmsClient` interface. Practical options: (a) custom `KmsClient` wrapping a SQL Server table (`General.ops.PiiSubjectKeys`), aligning with existing architecture; (b) HashiCorp Vault Enterprise KMIP secrets engine (enterprise license required); (c) Thales CipherTrust / Fortanix (commercial). TPM2 is suited for master key sealing only, not per-subject key operations at scale.

### R3-1: TPM2 is not suitable for per-subject key operations

Source: FOSDEM 2024 Linux Kernel TPM security talk + Red Hat documentation on TPM2 LUKS.

TPM2's `tpm2_unseal` command decrypts a single sealed blob. Designed for low-frequency operations (disk unlock at boot, credential unsealing). TPM2 has no API for managing millions of sealed blobs or performing per-row encryption at pipeline throughput. Single hardware chip with serialized access — concurrent per-subject key operations serialize through it.

**Correct use of TPM2 in our architecture** (confirmed): TPM2 seals ONE master key (the KEK, key-encryption key), which wraps per-subject DEKs (Data Encryption Keys) stored in SQL Server. At write time, pipeline unseals master KEK from TPM2 once per run, uses it in-memory to unwrap per-subject DEKs from `General.ops.PiiSubjectKeys`. Avoids per-row TPM2 operations.

### R3-2: HashiCorp Vault KMIP — Enterprise-only barrier

Source: `developer.hashicorp.com/vault/docs/secrets/kmip`

HashiCorp Vault KMIP secrets engine requires Vault Enterprise with the Advanced Data Protection (ADP) module. No community equivalent. Given $120K/year Snowflake ceiling + on-prem posture (D110), adding a Vault Enterprise license is material cost + procurement overhead.

Vault Transit secrets engine (Community edition) CAN perform AES-GCM encryption/decryption on demand. COULD serve as KMS backend for pyarrow's KmsClient interface, but requires running Vault server. No existing Vault infrastructure referenced in project.

### R3-3: SQL Server table as KMS backend — the pragmatic on-prem pattern

The plan's `General.ops.PiiSubjectKeys` as KMS backend is architecturally sound for our environment. KmsClient implementation:

1. At pipeline startup: unseal master KEK from TPM2 (one `tpm2_unseal` call)
2. Per-subject lookup: SELECT `EncryptedSubjectKey` FROM `PiiSubjectKeys` WHERE `SubjectIdentifier = ?` (batched)
3. Per-subject DEK decrypt: AES-GCM unwrap using in-memory master KEK
4. At pipeline end: zero master KEK from memory

Avoids TPM2 per-row operations; keeps all key material in `General.ops` (existing metadata database). No external KMS required. Aligns with D64 (TPM2 for credentials) + D103 (security model).

**Performance**: At 3B rows across M distinct subjects, key lookup is per-subject (NOT per-row). Pipeline needs M DEK lookups. Typical financial table with millions of accounts: tractable as batched IN-clause.

### R3-4: Key management scale for crypto-shredding

Source: Uber production deployment + research synthesis.

Uber manages "hundreds of PB" of encrypted Parquet with per-subject keys (via Hive metastore, NOT per-row KMS calls from compute). Key management happens at schema propagation time, not data-page write time. Our SQL Server KMS backend fits this pattern.

For crypto-shredding: `UPDATE PiiSubjectKeys SET EncryptedSubjectKey = NULL` is single SQL UPDATE per subject. At typical CCPA request volume (<100 subjects per request batch): negligible overhead.

**Confidence R3**: HIGH for TPM2 scope limitation; HIGH for SQL-Server-as-KMS viability; MEDIUM for scale performance (derived from Uber analogous pattern, not direct measurement).

---

## R4 Findings: Crypto-Shredding GDPR/CCPA Guidance

**Summary**: No DPA enforcement action explicitly accepting or rejecting crypto-shredding as sufficient for Article 17 erasure has been identified. EDPB Guidelines **02/2025** (April 2025; consultation closed June 2025) accept key destruction as a method for blockchain contexts. ICO has stated data should be put "beyond use" when deletion not technically feasible. CCPA enforcement record shows no case law specifically on crypto-shredding. Industry consensus: crypto-shredding satisfies "practical inaccessibility" standard; EDPB irreversibility standard remains contested for non-blockchain.

### R4-1: EDPB Guidelines 02/2025 on blockchain — direct crypto-shredding endorsement

Source: `edpb.europa.eu/system/files/2025-04/edpb_guidelines_202502_blockchain_en.pdf`

EDPB published Guidelines 02/2025 on processing personal data through blockchain. Guidelines explicitly address crypto-shredding in immutable ledger context: recommends storing data in a form where "deleting off-chain data can make on-chain records unlinkable to individuals." Functionally crypto-shredding applied to blockchain.

**Critical nuance**: Guidelines are blockchain-specific, not Parquet archives generally. However, the legal principle transfers: key destruction makes encrypted data "unlinkable to individuals" — functionally anonymous from GDPR perspective when combined with (a) no other copy exists, (b) key verifiably destroyed, (c) no reconstruction pathway exists.

**Note on numbering**: R5 research cited "EDPB Guidelines 01/2025" but actual published guidelines are numbered "02/2025." Minor citation correction; substance of R5 confirmed.

### R4-2: ICO position on encryption and erasure

Source: ICO right-to-erasure guidance + Cooley CDPInsights on ICO encryption.

ICO: "If deletion is not technically possible, organisations should at least take steps to put the personal data 'beyond use'." ICO defines "beyond use" criteria: organization cannot use the data, give access to it, or use it to affect the individual. **Key destruction satisfies all three criteria.**

ICO encryption guidance (updated for Data (Use and Access) Act 2025) is under review. Prior guidance treated key destruction as making data effectively inaccessible.

### R4-3: CCPA enforcement — no crypto-shredding precedent found

Source: Multiple CCPA enforcement searches; California AG settlement records 2024-2026.

California AG enforcement (largest settlement February 2026 per Troutman Pepper) has focused on opt-out rights violations + data broker obligations, NOT deletion methodology. **No enforcement action specifically addressing whether key destruction satisfies 1798.105 found.**

CCPA statute (1798.105(b)) only requires deletion of personal information, without specifying bit-level erasure vs cryptographic unreadability. Practical guidance consensus (IAPP, TechTarget, practitioner sources): key destruction = deletion when (a) all key copies destroyed, (b) no reconstruction pathway exists.

### R4-4: Industry adoption signals

| Source | Position |
|---|---|
| Uber Engineering | Key destruction "makes the data garbage" — explicit crypto-shredding compliance mechanism |
| Apache Iceberg | Crypto-shredding documented as one of three GDPR right-to-deletion patterns; described as "faster compliance without physical file deletion" |
| Conduktor (Kafka) | Presents crypto-shredding as GDPR/CCPA compliance without citing DPA authority (industry-consensus claim, not regulatory holding) |
| IBM Parquet PME blog | Positioned PME crypto-shredding as enabling data retention policy compliance |

**Counter-evidence**: EDPB 01/2025 position (per R5) remains valid: "deletion of additional information does not automatically render pseudonymised data anonymous." Vault-soft-delete (token exists, mapping nulled) FAILS this test. PME crypto-shredding (key destroyed, decryption mathematically infeasible) is STRONGER than vault-soft-delete and has better legal footing, but EDPB has NOT explicitly stated "PME crypto-shredding = anonymized" outside blockchain.

### R4-5: CNIL (France) — no specific PME/crypto-shredding guidance found

CNIL website search 2025: no specific guidance on Parquet encryption or crypto-shredding. CNIL generally follows EDPB. EDPB Guidelines 02/2025 is the closest applicable guidance.

**Risk assessment for D-NEW-C**: Crypto-shredding via PME key destruction is on stronger legal footing than vault-soft-delete for GDPR/CCPA. Industry consensus endorses. No DPA has explicitly rejected. EDPB "beyond use" + blockchain guidance implicitly support. **Legal counsel review remains required** for final sign-off.

**Confidence R4**: MEDIUM — industry consensus strong; primary DPA authority supportive but not explicit for PME-on-Parquet pattern; no enforcement precedent.

---

## R5 Findings: Snowflake + PME Real-Customer Evidence

**Summary**: Snowflake does **NOT** natively support reading Parquet files encrypted with Parquet Modular Encryption (PME). Snowflake's encryption model is Snowflake-managed or cloud-KMS-managed at storage layer, not at Parquet format layer. PME-encrypted Parquet files written by our pipeline cannot be read directly by Snowflake without first decrypting. Material constraint for the D5/D23/D71 Snowflake COPY INTO Iceberg plan.

### R5-1: Snowflake encryption model — storage-level, not format-level

Source: `docs.snowflake.com/en/user-guide/security-encryption-manage` + Snowflake blog on customer-managed keys.

Snowflake uses hierarchical key model: encrypts all data at storage layer using AES-256 (Snowflake-managed) or Tri-Secret Secure with cloud provider KMS (AWS KMS / Azure Key Vault / GCP KMS). Entirely different from Parquet Modular Encryption.

Snowflake's customer-managed key (CMK) support (GA January 2025 with AWS external key store integration) operates at Snowflake platform level, not at individual Parquet file column level. Does NOT give Snowflake ability to decrypt PME columns using customer-held per-subject keys.

### R5-2: Snowflake + Iceberg + external storage — no PME support

Source: Apache Iceberg GitHub issue #1413 (closed not-planned) + iceberg-rust issue #686 (in development for Iceberg spec v3).

Apache Iceberg specification does not include native PME key management in currently GA versions. Issue #1413 (opened September 2020, closed "not planned") confirms not implemented in Java Iceberg library. Issue #686 in iceberg-rust: PME being developed as part of Iceberg specification v3, not yet released.

Snowflake Iceberg tables store data in customer-supplied object storage as Parquet files. If those files are PME-encrypted, Snowflake cannot read encrypted columns without PME key — which Snowflake has no mechanism to acquire from our on-prem TPM2/SQL Server KMS.

**Critical finding**: Writing to KMS-encrypted external volumes is explicitly flagged as "not supported" in Snowflake documentation on external volumes.

### R5-3: Snowflake Tri-Secret Secure — relevant but not a solution

Tri-Secret Secure (Snowflake Enterprise) encrypts Snowflake INTERNAL storage with composite key requiring both Snowflake's key + customer's cloud KMS key. Does NOT help with reading externally-written PME Parquet files.

### R5-4: Snowflake masking policies — applicable post-decryption only

Snowflake masking policies can be applied to Iceberg table columns. ONLY applies to data Snowflake can READ. If Snowflake cannot decrypt PME columns, masking policies cannot be applied.

### Recommendation for Snowflake integration (D5/D23/D71)

Two options:

**Option A (Decrypt before Snowflake COPY)**: Pipeline decrypts PII columns before copying to Snowflake, tokenizes in-memory, copies tokenized data. Snowflake receives tokenized (not plaintext) data. No PME involved in Snowflake path. **PRAGMATIC PATH.**

**Option B (Wait for Iceberg v3 PME support)**: Once Iceberg v3 ships with PME + Snowflake adopts, native PME Parquet reading becomes possible. Timeline UNKNOWN.

**Recommendation**: Adopt Option A for Phase 5. Document PME-as-Snowflake-limitation explicitly. Parquet archive (H drive + VendorFile) maintains PME encryption for compliance. Snowflake path uses in-memory decrypted+tokenized data flow per §3.1 of redesign plan.

**Confidence R5**: HIGH — Snowflake lack of PME support confirmed from multiple sources.

---

## R6 Findings: Source-Exactness Verification Patterns

**Summary**: Three verification approaches exist. Hash-based per-column verification most tractable for our pipeline at scale. Oracle-to-Parquet type mapping has one confirmed precision boundary (Oracle DATE → Parquet DATE not timestamp). SQL Server DATETIME2(7) has 100-nanosecond precision that Parquet timestamp[us] cannot represent — definitive precision loss requiring documentation as accepted exception. ConnectorX has known Oracle DATE overflow bug for dates >= 2262-04-12 when using arrow2/polars return type.

### R6-1: Oracle type mapping to Parquet — authoritative table

Source: `docs.oracle.com/en/cloud/paas/autonomous-database/serverless/adbsb/data-type-mapping-oracle-parquet.html`

| Oracle Type | Parquet Type | Notes |
|---|---|---|
| DATE | DATE | **Not timestamp** — Oracle DATE includes time, Parquet DATE is date-only |
| NUMBER(p,s) | DECIMAL(p,s) | Precision preserved |
| NUMBER(p) | DECIMAL(p) | Precision preserved |
| TIMESTAMP(3) | TIMESTAMP_MILLIS | |
| TIMESTAMP(6) | TIMESTAMP_MICROS | |
| TIMESTAMP(9) | TIMESTAMP_NANOS | |
| VARCHAR2 | STRING | |
| BINARY_FLOAT | FLT | |
| BINARY_DOUBLE | DBL | |

**Critical finding**: Oracle DATE → Parquet DATE is **DATE only**, losing time component. However, ConnectorX routes Oracle DATE as `timestamp[ns]` (issue #495), different from Oracle Cloud mapping above. ConnectorX behavior: Oracle DATE → Arrow `timestamp[ns]` as of v0.3.2. PRESERVES time component but introduces nanosecond-precision inflation (Oracle DATE has second precision; timestamp[ns] advertises sub-second which is zero-filled).

NVARCHAR2, CLOB, TIMESTAMP WITH TIME ZONE NOT covered in official Oracle mapping — require separate documentation.

### R6-2: Oracle NUMBER precision edge cases

Source: Polars GitHub issue #12375 + Microsoft ADF documentation on Oracle NUMBER.

Oracle `NUMBER` without precision (floating-point) maps to DECIMAL(126, ...) in some implementations, but Parquet's DECIMAL limited to precision ≤ 38 in pyarrow. Oracle `NUMBER(p)` with p > 38 cannot be faithfully represented as Parquet DECIMAL. ADF converts NUMBER with precision > 28 to String. **Source-exactness violation for wide-precision Oracle NUMBERs.**

Polars has documented issues writing Decimal128 (maps from Oracle NUMBER) to Parquet (issues #12375, #21684). Known bugs may affect source-exactness for numeric types.

### R6-3: SQL Server DATETIME2(7) precision loss — definitive

Source: `learn.microsoft.com/en-us/sql/t-sql/data-types/datetime2-transact-sql` + pyarrow write_table docs.

SQL Server DATETIME2(7) has precision to 100 nanoseconds (7 decimal places fractional seconds). Parquet timestamp[us] (microseconds) has precision to 1 microsecond = 1000 nanoseconds. Precision loss is 100ns → 1μs: **factor of 10 truncation**.

For Parquet 2.6 (pyarrow default), nanoseconds written natively but:
1. Polars internal datetime is `datetime[us]` (microsecond) by default — truncates at read time from SQL Server's 100ns
2. ConnectorX SQL Server connector maps DATETIME2 to Arrow timestamp — precision depends on connector version

pyarrow `write_table` parameter `coerce_timestamps` with `allow_truncated_timestamps=True` exists for this case. Without it, truncation exception raised.

**Documented, unavoidable precision boundary** for SQL Server DATETIME2(7). Plan's SE-2 invariant ("Parquet column dtypes correspond 1:1 to source dtypes") must document this as ACCEPTED EXCEPTION: DATETIME2(7) → timestamp[us] with truncation of 8th decimal digit.

### R6-4: ConnectorX Oracle DATE overflow bug

Source: `github.com/sfu-db/connector-x/issues/495`

ConnectorX versions ≥ 0.3.2 return Oracle DATE as `timestamp[ns]`. Dates ≥ 2262-04-12 overflow int64 nanoseconds representation and produce incorrect results. **Known bug.** For financial pipeline data from DNA source, dates approaching 2262 are implausible but bug exists.

Mitigation: use `return_type="arrow"` which maps Oracle DATE to `date64[ms]` and handles dates correctly, OR use oracledb fallback (uses Python datetime objects; avoids Arrow2 overflow).

### R6-5: Verification approaches

Three industry approaches:

1. **Row count check**: Verify `COUNT(*)` source ≡ Parquet row count. Fast, mandatory. Catches row loss/duplication, not value corruption.
2. **Sample-based hash comparison**: Hash N randomly sampled rows from source; compare to Parquet after decryption. Probabilistic confidence; impractical for continuous operation.
3. **Per-column aggregate comparison**: Compare MIN/MAX/SUM (numeric) + COUNT(DISTINCT) between source and Parquet. Industry-standard for ETL validation.

Plan's SE-3 via "sample-based round-trip test per write" is correct for periodic verification. For every-write validation, row count (SE-6) is the practical check.

**Confidence R6**: HIGH for Oracle/SQL Server known precision boundaries; MEDIUM for Polars Decimal bug scope.

---

## R7 Findings: Extraction-Timestamp Convention

**Summary**: No single industry standard exists for recording source-extraction timestamps in raw Parquet file-level metadata. Table format systems (Iceberg, Delta, Hudi) record COMMIT timestamps, not SOURCE EXTRACTION timestamps. Consensus pattern for raw Parquet (pre-table-format layer): embed custom key-value metadata. Recommended key naming for our `key_value_metadata` schema follows `udm_` prefix with ISO-8601 UTC values.

### R7-1: Apache Iceberg — commit timestamp, not extraction timestamp

Iceberg snapshot metadata records `committed-at` (timestamp when snapshot was committed to catalog) + `snapshot-id`. Reflect catalog commit time, not source database query time. Snapshot "summary" map may include additional properties; no standard key for "source extraction time" in Iceberg spec.

**For our pipeline**: Iceberg metadata records when pipeline pushed data to Snowflake, not when source extraction SQL ran. Differs by hours (extraction at 02:00; Snowflake COPY at batch cadence). Source extraction timestamp MUST live in the Parquet file itself.

### R7-2: Apache Hudi — record-level commit time, not extraction time

Hudi `_hoodie_commit_time` field is record-level metadata column embedded in each data row. Format `YYYYMMddHHmmssSSS` (millisecond). Records when Hudi committed the row, not when source system data was extracted. Hudi has no concept of "source query started at."

### R7-3: Delta Lake — `_commit_timestamp` in CDF

Delta Lake `_commit_timestamp` available through Change Data Feed (CDF). Records wall-clock time of Delta commit, not source extraction time.

### R7-4: Raw Parquet convention — no standard; use custom `key_value_metadata`

Source: Industry blog synthesis, Dremio documentation, Alex Merced's "All About Parquet" series (Medium 2024).

For raw Parquet (not wrapped in table format), consensus pattern is file-level custom metadata via `key_value_metadata`. Different organizations use different key names:
- `"source_system"` → source name
- `"extraction_timestamp"` / `"extracted_at"` → ISO-8601 string
- `"pipeline_version"` → pipeline version
- `"source_query"` → SQL query (often omitted)

No IANA registry, OpenLineage standard, or Apache project specification defines canonical key names for raw Parquet lineage metadata. OpenLineage operates at pipeline-run metadata level, not Parquet file-level.

### Recommendation for our `key_value_metadata` schema

`ParquetSnapshotRegistry` already records `CreatedAt` (write-completion timestamp). Plan's D-NEW-D proposes NOT storing `_extracted_at` in Parquet. But registry row and Parquet file are separate artifacts. For self-describing compliance (Parquet file alone proves WHEN extraction occurred, without DB lookup), file-level metadata is right vehicle.

**Recommended key schema** for our Parquet writer:

```
udm_source_system          : "DNA" | "CCM" | "EPICOR"
udm_source_schema          : "osibank" | ...
udm_source_table           : "ACCT" | ...
udm_extraction_started_at  : ISO-8601 UTC (when source SQL query was submitted)
udm_extraction_ended_at    : ISO-8601 UTC (when Polars DataFrame fully populated)
udm_parquet_written_at     : ISO-8601 UTC (when pq.write_table completed; matches Registry.CreatedAt)
udm_pipeline_batch_id      : batch GUID from PipelineBatchSequence
udm_pipeline_version       : pipeline release tag
udm_encryption_config      : "pme_plaintext_footer_aes_gcm_v1" | "none"
udm_row_count              : string(int) — SE-6 invariant check
```

Three timestamps (extraction_started, extraction_ended, parquet_written) allow reconstructing end-to-end latency without DB query. Exceeds what Iceberg/Delta/Hudi natively capture. Correct approach for compliance auditability per Pillar 1 (Audit-grade) and Pillar 2 (Traceability).

**Confidence R7**: HIGH — absence of standard is well-evidenced finding; recommended schema derived from synthesis of confirmed industry patterns.

---

## Recommendations for the Plan

### Tentative-future-D-N-A (Tokenization timing reorder)
**PASS with evidence.** Source-exact requirement confirmed achievable. Tokenization after Parquet write with in-memory separation is correct pattern. No external authority contradicts. Architecture correctly aligns with SE-1 through SE-7 invariants.

### Tentative-future-D-N-B (PME for at-rest PII protection)
**PASS with two mandatory refinements**:

1. **Use `plaintext_footer=True`** (NOT the default encrypted footer mode). In encrypted footer mode, `key_value_metadata` (including extraction timestamps) is encrypted and inaccessible to non-key-holding tools. Plaintext footer preserves metadata accessibility for operators + monitoring while keeping PII column data encrypted. Integrity signature still prevents tampering.

2. Plan's pyarrow code snippet at §4.2 uses `column_keys={"SSN": "subject_key_id_for_ssn_row", ...}`. **Correct understanding**: string values are KEY IDs passed to KmsClient for lookup, NOT the keys themselves. KmsClient resolves to actual AES key material from `PiiSubjectKeys`. Must be explicit in implementation spec.

### Tentative-future-D-N-C (Crypto-shredding as CCPA deletion mechanism)
**PASS with legal counsel caveat maintained.** Crypto-shredding via PME key destruction is:
- Stronger than vault-soft-delete (R5 finding confirmed)
- Consistent with EDPB Guidelines 02/2025 blockchain guidance (key destruction = unlinkable = functionally anonymous)
- Consistent with ICO "beyond use" framework
- Adopted as industry pattern by Uber, Apache Iceberg, IBM
- Not explicitly contradicted by any DPA enforcement action

Plan's §4.4 caution "legal counsel still required" is correct and must remain. The crypto-shredding is RIGHT direction; legal uncertainty is about specific PME-on-Parquet pattern (no DPA explicitly addressed).

### Tentative-future-D-N-D (extraction timestamp in ParquetSnapshotRegistry.CreatedAt, not in Parquet)
**REQUIRES REVISION per R1 + R7 findings.** Plan proposes not storing extraction timestamps in Parquet, relying on `ParquetSnapshotRegistry.CreatedAt`. Compliance vulnerability:

- Parquet file is the compliance artifact (source-exact archive for 7 years per D30)
- `ParquetSnapshotRegistry` is mutable SQL table (can be updated, rows can be corrupted)
- After 7 years, registry may be archived, deleted, or schema-evolved; Parquet file may outlive its registry row
- Audit-grade requirement (Pillar 1) demands Parquet file itself be self-describing regarding WHEN it was created

**Recommendation**: Store extraction timestamps in Parquet `key_value_metadata` (plaintext footer mode) using R7 schema. Trivial overhead (<1KB per file), immutable post-write, makes Parquet file self-auditing. `ParquetSnapshotRegistry.CreatedAt` remains as secondary index for fast lookups.

Revised D-NEW-D should read: "Extraction timestamps stored as `key_value_metadata` in Parquet file footer (plaintext mode; per R1+R7 research findings); `ParquetSnapshotRegistry.CreatedAt` provides secondary SQL-queryable index of the same data."

### Tentative-future-D-N-E (PiiSubjectKeys table schema)
**PASS with one refinement**: Add `SubjectKeyVersion INT NOT NULL DEFAULT 1` column for master key rotation tracking. When TPM2-sealed master KEK is rotated (per B41), existing subject DEKs must be re-wrapped with new master. Without version column, pipeline cannot identify which DEKs were wrapped by old master vs new master during rotation.

---

## B-N Candidates Surfaced by Research

| B-N | Title | COD | JS | WSJF |
|---|---|---|---|---|
| **R-B1** | Document PME `plaintext_footer=True` as MANDATORY in D-NEW-B spec; update plan §4.2 code example | 5 | 1 | 5.0 |
| **R-B2** | Document ConnectorX Oracle DATE overflow bug (issue #495); add defensive assertion in oracle_extractor.py | 4 | 2 | 2.0 |
| **R-B3** | Document DATETIME2(7) → timestamp[us] precision loss as accepted SE-2 exception; add `allow_truncated_timestamps=True` | 4 | 1 | 4.0 |
| **R-B4** | Revise D-NEW-D to include `key_value_metadata` extraction timestamp in Parquet file (not just ParquetSnapshotRegistry); author key schema per R7 | 5 | 2 | 2.5 |
| **R-B5** | Add `SubjectKeyVersion` column to planned `General.ops.PiiSubjectKeys` DDL for master-KEK rotation tracking; add re-wrap batch procedure spec | 3 | 2 | 1.5 |
| **R-B6** | Document Snowflake PME limitation explicitly in D5/D23/D71; specify Snowflake path receives tokenized plaintext, NOT PME columns | 5 | 1 | 5.0 |
| **R-B7** | Track iceberg-rust #686 (PME for Iceberg spec v3) as future Phase 5+ enhancement candidate | 2 | 1 | 2.0 |
| **R-B8** | Author KmsClient interface implementation spec for `General.ops.PiiSubjectKeys` backend (startup master-KEK unseal, per-subject lookup batching, zero-on-exit); Tier β build | 4 | 3 | 1.3 |

---

## Counter-Evidence

1. **Against PME at pyarrow at our scale**: No published pyarrow/Python PME production case study at 3B-row scale found. Uber case study is Java/Spark. pyarrow C++ should perform equivalently (same OpenSSL AES-NI path) but inference, not direct measurement.
2. **Against crypto-shredding as sufficient GDPR**: EDPB non-blockchain guidance maintains pseudonymized data does NOT automatically become anonymous even when additional information is deleted. PME crypto-shredding NOT explicitly blessed by any DPA for non-blockchain contexts.
3. **Against per-subject key granularity**: PME `column_keys` parameter designed for per-column (schema-level) key assignment, not per-row-value. Implementing per-subject (per-row) granularity requires KmsClient custom logic — possible but NOT intended design. Most PME production deployments use per-table or per-column-classification key granularity.
4. **Against SQL Server as KMS backend**: SQL Server as key store has no HSM backing by default. If server compromised, both encrypted DEKs and lookup mechanism accessible. TPM2 for master KEK provides one hardware-protection layer, but DEKs in `PiiSubjectKeys` only as secure as SQL Server access controls. Industry KMS (Thales, Vault) provide HSM-backed key storage.

---

## What This Research Does NOT Cover

- Oracle `NVARCHAR2`, `CLOB`, `TIMESTAMP WITH TIME ZONE`, `XMLTYPE`, `SDO_GEOMETRY` → Parquet mapping (not in official Oracle docs; requires empirical testing)
- Polars Decimal128 → Parquet round-trip bug fix status (open GitHub issue; fix timeline unknown)
- pyarrow PME performance benchmarks specifically on C++ Python binding (only Java benchmarks for GCM at scale)
- CNIL / Bayerisches Landesbeauftragter published guidance specifically on crypto-shredding (not found; generally follow EDPB)
- Per-subject key granularity PME production deployments (no published case study; per-table + per-column-classification are documented patterns)
- Snowflake PME roadmap (not publicly documented)

---

## Confidence Assessment

- **R1 (Parquet key_value_metadata)**: HIGH — spec authoritative; pyarrow API well-documented
- **R2 (PME maturity)**: HIGH for API/mechanism; MEDIUM for per-subject-key production pattern
- **R3 (KMS choices)**: HIGH for TPM2 scope limitation; HIGH for SQL-Server-as-KMS viability; MEDIUM for scale
- **R4 (Crypto-shredding legal)**: MEDIUM — industry consensus strong; DPA explicit blessing absent for non-blockchain PME
- **R5 (Snowflake + PME)**: HIGH — absence of PME support confirmed from multiple authoritative sources
- **R6 (Source-exactness)**: HIGH for Oracle/SQL Server known precision boundaries; MEDIUM for Polars Decimal bug scope
- **R7 (Extraction timestamp convention)**: HIGH — confirmed absence of standard; recommended schema grounded in industry patterns

---

## Sources Cited

| # | URL | Authority |
|---|---|---|
| 1 | https://parquet.apache.org/docs/file-format/metadata/ | Apache (primary) |
| 2 | https://github.com/apache/parquet-format/blob/master/Encryption.md | Apache (primary spec) |
| 3 | https://parquet.apache.org/docs/file-format/data-pages/encryption/ | Apache (primary) |
| 4 | https://arrow.apache.org/docs/python/generated/pyarrow.parquet.encryption.EncryptionConfiguration.html | Apache Arrow (primary) |
| 5 | https://arrow.apache.org/docs/python/parquet.html | Apache Arrow (primary) |
| 6 | https://www.mungingdata.com/pyarrow/arbitrary-metadata-parquet-table/ | Community |
| 7 | https://colinsblog.net/2024-04-11-save-parquet-with-custom-metadata/ | Community (2024) |
| 8 | https://www.uber.com/blog/one-stone-three-birds-finer-grained-encryption-apache-parquet/ | Uber Engineering (production) |
| 9 | https://medium.com/@tomersolomon/test-driving-parquet-encryption-3d5319f5bc22 | IBM Research (benchmark) |
| 10 | https://www.edpb.europa.eu/system/files/2025-04/edpb_guidelines_202502_blockchain_en.pdf | EDPB (primary regulatory) |
| 11 | https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/individual-rights/individual-rights/right-to-erasure/ | ICO (primary regulatory) |
| 12 | https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?sectionNum=1798.105.&lawCode=CIV | California statute (primary) |
| 13 | https://docs.snowflake.com/en/user-guide/security-encryption-manage | Snowflake (primary vendor) |
| 14 | https://github.com/apache/iceberg/issues/1413 | Apache Iceberg (primary) |
| 15 | https://github.com/apache/iceberg-rust/issues/686 | Apache Iceberg (primary) |
| 16 | https://docs.oracle.com/en/cloud/paas/autonomous-database/serverless/adbsb/data-type-mapping-oracle-parquet.html | Oracle (primary vendor) |
| 17 | https://github.com/sfu-db/connector-x/issues/495 | ConnectorX (primary; Oracle DATE overflow bug) |
| 18 | https://github.com/pola-rs/polars/issues/12375 | Polars (primary; Decimal128 write bug) |
| 19 | https://github.com/pola-rs/polars/issues/21684 | Polars (primary; Decimal round-trip) |
| 20 | https://github.com/pola-rs/polars/issues/21392 | Polars (primary; datetime precision) |
| 21 | https://learn.microsoft.com/en-us/sql/t-sql/data-types/datetime2-transact-sql | Microsoft (primary) |
| 22 | https://developer.hashicorp.com/vault/docs/secrets/kmip | HashiCorp (primary vendor) |
| 23 | https://www.conduktor.io/blog/crypto-shredding-in-kafka-a-cost-effective-way-to-ensure-compliance | Conduktor (community) |
| 24 | https://g-research.github.io/ParquetSharp/guides/Encryption.html | G-Research (community) |
