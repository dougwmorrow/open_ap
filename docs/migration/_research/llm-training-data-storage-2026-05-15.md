# Research: LLM Training Data Storage and Organization Patterns

**Date**: 2026-05-15
**Triggered by**: on-demand (user request — exploratory follow-on to agent-markdown-traversal-2026-05-15.md + agent-discoverability-2026-05-15.md)
**Question**: Do LLM training-data organization patterns (blob storage, sharding, tokenization, quality filtering, deduplication, data loading parallelism) offer insights for organizing our internal markdown corpus for AI agent consumption?
**Anchor**: D62 (CCL doctrine), MARKDOWN_REFACTOR_PLAN.md (referenced but not read in this session — this is advisory research), Operationally stable pillar
**Follow-on to**: `agent-markdown-traversal-2026-05-15.md` (traversal patterns) + `agent-discoverability-2026-05-15.md` (naming / TOC / Navigation Paradox)

---

## Summary

Training-data organization and documentation-corpus organization are solving fundamentally different problems. Training data is read once, sequentially, at massive scale, under high-throughput pressure, by infrastructure that does not understand content. Documentation corpora are read repeatedly, selectively, at small scale, by agents that do understand content and make routing decisions. Most training-data patterns do NOT transfer directly. However, three training-data ideas map usefully onto the markdown corpus problem: (1) the quality-tier insight (training labs weight high-quality curated data more heavily than raw noisy data — analogous to "core canon" vs "supporting detail" docs), (2) the deduplication principle (training labs actively remove near-duplicate content because it wastes compute and degrades model generalization — analogous to avoiding cross-file content duplication in planning docs), and (3) the metadata-for-navigation insight (shard index files like MosaicML's `index.json` are how infrastructure locates shards without reading them — analogous to a per-file sidecar or manifest). The shard-size and tokenization patterns do NOT transfer.

Confidence: 🟡 Medium — primary sources available for training-data patterns; transfer claims are inferential (no benchmark study directly tests this mapping).

---

## Sources cited

| # | URL | Date accessed | Authority |
|---|---|---|---|
| 1 | https://docs.mosaicml.com/projects/streaming/en/latest/preparing_datasets/dataset_format.html | 2026-05-15 | Databricks/MosaicML (primary) |
| 2 | https://www.databricks.com/blog/mosaicml-streamingdataset | 2026-05-15 | Databricks (primary) |
| 3 | https://community.databricks.com/t5/technical-blog/managing-llm-pretraining-data-using-mosaic-data-sharding/ba-p/117158 | 2026-05-15 | Databricks community |
| 4 | https://arxiv.org/html/2505.18458v2 | 2026-05-15 | Academic survey (Data x LLM, May 2025) |
| 5 | https://zilliz.com/blog/data-deduplication-at-trillion-scale-solve-the-biggest-bottleneck-of-llm-training | 2026-05-15 | Zilliz (industry) |
| 6 | https://arxiv.org/html/2411.04257v3 | 2026-05-15 | Academic (LSHBloom) |
| 7 | https://medium.com/@aefselinates/lessons-from-scaling-data-deduplication-for-trillion-token-llms-aa046319b7e9 | 2026-05-15 | Medium / practitioner |
| 8 | https://developer.nvidia.com/blog/mastering-llm-techniques-data-preprocessing/ | 2026-05-15 | NVIDIA (primary) |
| 9 | https://www.rohan-paul.com/p/selecting-and-preparing-training | 2026-05-15 | Practitioner blog |
| 10 | https://aiwithmike.substack.com/p/training-large-language-models-with | 2026-05-15 | Practitioner blog |
| 11 | https://arxiv.org/pdf/2601.21698 | 2026-05-15 | Academic (curriculum learning for LLM pretraining) |
| 12 | https://huggingface.co/docs/hub/datasets-upload-guide-llm | 2026-05-15 | HuggingFace (primary) |
| 13 | https://huggingface.co/blog/parquet-cdc | 2026-05-15 | HuggingFace (primary) |
| 14 | https://docs.ray.io/en/latest/data/data.html | 2026-05-15 | Ray/Anyscale (primary) |
| 15 | https://arxiv.org/html/2604.21275v1 | 2026-05-15 | Academic (distributed data pipelines) |
| 16 | https://www.blocksandfiles.com/ai-ml/2025/02/04/very-large-ai-model-training-uses-object-storage/1602990 | 2026-05-15 | Industry analysis |
| 17 | https://apxml.com/courses/mlops-for-large-models-llmops/chapter-2-llm-infrastructure-data-management/managing-large-datasets | 2026-05-15 | MLOps practitioner |
| 18 | https://crfm.stanford.edu/fmti/December-2025/company-reports/Anthropic_FinalReport_FMTI2025.html | 2026-05-15 | Stanford CRFM / Anthropic (primary) |
| 19 | https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents | 2026-05-15 | Anthropic (primary) |
| 20 | https://storage.googleapis.com/deepmind-media/gemini/gemini_v2_5_report.pdf | 2026-05-15 | Google DeepMind (primary) |
| 21 | https://machinelearningplus.com/gen-ai/tiktoken-vs-huggingface-tokenizers/ | 2026-05-15 | Practitioner benchmark |
| 22 | https://aclanthology.org/2025.acl-long.453.pdf | 2026-05-15 | Academic (Byte Latent Transformer) |

---

## Findings

### Finding 1: Blob storage — object storage is the dominant medium; file formats are purpose-built for sequential throughput

**Source**: [#1] MosaicML docs, [#2] Databricks blog, [#16] industry analysis, [#17] MLOps practitioner

Labs use S3 / GCS / Azure Blob as the primary storage tier for raw corpora. At training time, data is reformatted into throughput-optimized binary shards and served from object storage (sometimes with a fast NVMe cache layer for hot data).

File formats in practice:
- **JSONL** — raw/intermediate corpus (human-readable, compressible with zstd/gzip)
- **Parquet** — intermediate at scale (columnar, compressed; HuggingFace canonical format for Hub datasets per [#12])
- **WebDataset (TAR)** — PyTorch-native streaming from object storage; sequential reads without random access
- **MosaicML MDS (Mosaic Data Shard)** — purpose-built binary format for training; "most performant for fast sample random-access" [#1]; shards at 64 MB default (67,108,864 bytes exactly [#1]); indexed via `index.json` sidecar
- **Tokenized binary** — raw uint16/uint32 token arrays; ~4 bytes per English token [#17]; this is what the GPU actually trains on after all format conversions are done

Shard sizes:
- MosaicML MDS default: **64 MB per shard**, ~4,093 samples per shard [#1]
- CCNet/Common Crawl example: **5 GB per shard**, 1.6 million documents per shard [#17]
- HuggingFace Hub: **Parquet files with `data-{index:05d}.parquet` naming** for multi-shard datasets [#12]

The range is wide (64 MB to 5 GB) because shard size is driven by the number of workers, network bandwidth, and memory budget — not by any content-semantic criterion.

**Relevance**: Shard size is a COMPUTE engineering constraint, not a content-organization decision. There is no transfer to markdown file sizing. Our markdown file-size guidance (500-line cap per skill convention, H2-section splits per prior research) comes from agent context-budget constraints, which are fundamentally different.

---

### Finding 2: Tokenization — pre-tokenization is the dominant production pattern; measurement is in tokens not bytes

**Source**: [#21] tiktoken vs HuggingFace benchmark, [#22] Byte Latent Transformer paper, [#8] NVIDIA blog

At scale, labs pre-tokenize training data offline and store the resulting integer arrays. Reasons: (a) tokenization is the bottleneck in naive on-the-fly pipelines, (b) BPE tokenization is deterministic given a fixed vocabulary, (c) storing pre-tokenized shards eliminates GPU idle time waiting on CPU tokenization. The MosaicML pipeline converts JSONL → MDS with tokenized arrays stored in the shard.

Key numbers: BPE English text tokenizes at roughly 1 token per 4 bytes. A trillion-token corpus is therefore ~4 TB of tokenized data.

Measurement convention: **training is budgeted in tokens, not bytes or lines**. A 10B parameter model might train for 200B tokens (2x model size per Chinchilla scaling). Training run "compute-optimal" token budget is separate from corpus size.

Tokenization innovation in 2025: Meta's Byte Latent Transformer [#22] experiments with entropy-based dynamic patching — abandoning fixed-vocabulary BPE entirely. LiteToken (Feb 2026) removes "residue" tokens from BPE vocabularies. These are research-frontier approaches; production training still uses BPE/SentencePiece/TikToken.

**Relevance**: The token-as-unit-of-measure insight transfers conceptually. For our markdown corpus, the relevant question is "how many tokens does the CCL consume?" (answer from prior research: ~12K-16K tokens for 7-11 files). This is already established. Pre-tokenization at training scale has no direct analog at documentation-corpus scale.

---

### Finding 3: Quality filtering — a multi-stage pipeline; high-quality data is weighted more heavily

**Source**: [#4] Data x LLM survey, [#8] NVIDIA blog, [#9] practitioner blog, [#11] curriculum learning paper

Training quality filtering is a 2-3 stage pipeline:

1. **Heuristic filters** (fast, cheap): remove very short documents, boilerplate-heavy pages, high symbol ratio, known spam domains
2. **Perplexity filters** (medium cost): score each document against a reference LM; high-perplexity text is usually low-quality or incoherent; low-perplexity text may be too generic
3. **Classifier-based filters** (expensive): train a classifier on high-quality labeled documents (Wikipedia, books, academic papers) vs. raw web; Common Crawl filtering typically removes 50-95% of raw content

Quality curriculum: Models like Phi-3 and MiniCPM use multi-stage training — first on large-but-noisy generic data, then on a smaller high-quality curated subset. The 2025 consensus [#10] is "better data beats better algorithms."

RedPajama v2 [#7] provides 40+ quality annotations per document including perplexity score, toxicity, and language — the data is "tiered" into quality buckets but training uses a weighted mixture, not a hard cutoff.

**Relevance (direct transfer)**: This is the strongest cross-domain analog. The training quality pipeline suggests a **canonical / reference / peripheral document tier system** for our docs:
- "Canon tier" (always read first): NORTH_STAR.md, HANDOFF.md, CURRENT_STATE.md, CHECKS_AND_BALANCES.md — equivalent to Wikipedia/books in training data quality hierarchy
- "Reference tier" (read on demand): 03_DECISIONS.md, 04_EDGE_CASES.md, 05_RUNBOOKS.md, phase1/* — equivalent to curated secondary sources
- "Peripheral tier" (rarely needed by agents): historical validation log entries, archived research, superseded artifacts — equivalent to raw web data

The CCL already encodes this implicitly (Stage 1 = canon, Stage 2 = risk/backlog, Stage 3 = task-specific, Stage 4 = on-demand). The training-data analogy provides external validation for this design.

**Confidence**: Medium — the analogy is structural, not mechanistic. Training data quality filters are automated; our tier system is convention-based.

---

### Finding 4: Deduplication — MinHash at scale; 22% near-duplicate rate in real-world corpora

**Source**: [#5] Zilliz deduplication blog, [#6] LSHBloom paper, [#7] practitioner report

Production deduplication pipeline:
1. **Exact dedup** (MD5 hash or suffix arrays): catches identical documents; fast
2. **Near-dedup via MinHash-LSH**: catches paraphrased/reformatted duplicates; Jaccard similarity over word shingles (3-gram typical); MinhashLSH integrated natively into Milvus 2.6 and Zilliz Cloud as of 2024-2025 [#5]
3. **Semantic dedup** (SemDeDup): embedding-based; catches documents with same meaning but different wording; expensive but catches what statistical methods miss [#4]

Scale numbers:
- Real-world corpus near-duplicate rate: 22% in observed datasets [#7]
- LSHBloom extension: replaces expensive LSH index with Bloom filters; peS2o dataset (39M documents) takes 35+ hours + 200 GB disk with naive MinHashLSH [#6]
- Multi-stage dedup achieves 18-20% efficiency gains on validation perplexity vs. deduplicated baselines [paper #4]

Why deduplication matters for training: duplicate documents teach the model that certain text is "more likely" by repetition, distorting the true distribution. The model over-memorizes duplicated content and generalizes less well.

**Relevance (direct transfer, limited)**: The deduplication insight translates to: **do not repeat substantive content across multiple planning docs**. In our corpus, the same information appearing in HANDOFF.md, CURRENT_STATE.md, CLAUDE.md, and 00_OVERVIEW.md creates the documentation equivalent of near-duplicates. Agents reading multiple docs encounter the same facts, wasting context budget and creating stale-copy risk. The training-data fix is deduplication; the doc-corpus fix is cross-reference links + single-source-of-truth discipline (e.g., CURRENT_STATE.md owns "what is in flight"; HANDOFF.md owns "what is locked"; no doc repeats the other's content).

The _validation_log.md already notes this problem indirectly. The research confirms the structural diagnosis: duplication in a corpus degrades the quality of reasoning over it.

**Confidence**: Medium — transfer is analogical, not identical. Training dedup is algorithmic; doc dedup is governance discipline.

---

### Finding 5: Parallel data loading — data parallelism is the dominant pattern; each rank gets independent shard(s)

**Source**: [#14] Ray Data docs, [#15] distributed data pipelines paper, [#3] Mosaic data sharding

Training data loading parallelism:
- **Data parallelism**: each GPU rank (or group of ranks) reads a different shard; shards are pre-shuffled; sequential read within a shard
- **Pipeline parallelism**: data flows through model layers; not a data-loading pattern per se — it's a model-partitioning strategy
- **Token-packing**: sequences are packed to fill context windows (512 / 2048 / 8192 tokens) to avoid wasted compute on padding
- Ray Data in 2025 [#14]: Arrow-backed, streams data from object storage, parallelizes per-shard across workers; 2025 benchmarks show network I/O and CPU transforms constrain GPU utilization to 10-15% without optimization [#15]
- MosaicML StreamingDataset [#1]: designed for multi-node training; correctness guarantee that each sample is seen exactly once per epoch across all ranks; random-access by shard index rather than sequential scan

**Relevance**: The cross-shard independence principle has a weak analog. An agent processing multiple docs in parallel (e.g., spawning sub-agents) could be assigned non-overlapping doc subsets. But this is not how our CCL works — CCL is sequential, single-agent, intentionally ordered by dependency (Stage 1 must complete before Stage 2 because Stage 2 findings are contextualized by Stage 1). The parallel-reads pattern from training data does NOT apply here.

---

### Finding 6: Anthropic, DeepMind — public training infrastructure details are sparse; agent context engineering is more relevant

**Source**: [#18] Stanford FMTI transparency report, [#19] Anthropic context engineering blog, [#20] Gemini 2.5 report

Anthropic public details (from Stanford FMTI December 2025 report [#18]):
- Training data includes publicly available internet data (as of March 2025), third-party licensed data, data-labeling contractor data, and opt-in user data
- Training infrastructure details are not publicly disclosed (proprietary)
- Claude Sonnet 4.6 cutoff: August 2025

Anthropic context engineering for agents [#19] (most relevant finding in this category):
- Recommends just-in-time context loading: agents maintain lightweight references (file paths, queries) and retrieve on demand using tools
- Folder hierarchies, naming conventions, and timestamps are "important signals that help both humans and agents understand how and when to utilize information"
- Recommends pre-loading only critical documentation; enabling autonomous exploration via glob/grep
- System prompts should use structural delineators (`<background_information>`, `<instructions>`, etc.)

Google DeepMind Gemini 2.5 [#20]:
- Training data includes web documents, text, code, images, audio, video
- Data processing: deduplication, robots.txt compliance, safety filtering, quality filtering
- Infrastructure: TPU SuperPods (4,096 chips each) across multiple data centers; data parallelism across SuperPods
- No shard-size or format specifics published

**Relevance**: Anthropic's context engineering guidance [#19] is directly applicable to our markdown corpus problem and is already consistent with the MARKDOWN_REFACTOR_PLAN.md direction. The key phrase "folder hierarchies, naming conventions, and timestamps all provide important signals" validates the prior research's finding #1 on semantic-functional naming with numeric-prefix sort keys.

---

### Finding 7: The fundamental asymmetry — training reads vs. agent reads

This finding is the central synthesis judgment (no single external source; inferred from the combined evidence base above).

| Dimension | LLM Training Data | UDM Documentation Corpus |
|---|---|---|
| Read frequency | Once (or very few epochs) | Repeatedly (every CCL invocation) |
| Read scope | Sequential scan of everything | Targeted reads of relevant subset |
| Reader | Infrastructure (no content understanding) | LLM agent (full content understanding) |
| Scale | Terabytes to petabytes | ~500 KB across ~40 files |
| Optimization target | Throughput (tokens/second) | Relevance (minimize irrelevant tokens read) |
| Navigation | Shard index + sequential read | Grep + intent-based routing |
| Shuffle | Required (training) | Counterproductive (agents need deterministic order) |
| Quality signal | Classifier / perplexity score | Content structure + naming convention |
| Duplication effect | Degrades generalization | Wastes context budget + creates stale-copy risk |
| Metadata role | Shard-level index (`index.json`) | File-level routing manifest (INDEX.md or frontmatter) |

---

## Recommendation

**Three patterns transfer; the rest do not.**

**Pattern A — Quality tiers transfer (adopt).** The training-data insight "curated high-quality data is weighted more heavily than raw noisy data" maps directly to the CCL's Stage 1 / Stage 2 / Stage 3 hierarchy. MARKDOWN_REFACTOR_PLAN.md should explicitly label this as the organizing principle for file priority. Producers should treat canon-tier docs (NORTH_STAR.md, HANDOFF.md, CURRENT_STATE.md, CHECKS_AND_BALANCES.md) as "high-quality curated" — always read, kept maximally accurate, never allowed to drift. Reference-tier docs (03_DECISIONS.md, phase1/*) are "secondary curated." Peripheral docs (_validation_log.md entries older than 30 days, superseded artifacts) are "raw/archived."

**Pattern B — Deduplication discipline transfers (adopt).** Training labs remove near-duplicate content because it distorts the model's distribution. For our corpus, the equivalent is: any fact that must be updated when reality changes should appear in exactly one authoritative location. Cross-reference links (not content copies) handle all other appearances. This is already the intent of CURRENT_STATE.md (source of truth for in-flight state) vs. HANDOFF.md (source of truth for locked decisions). The research validates enforcing this discipline more rigorously rather than letting duplicates drift.

**Pattern C — Sidecar index files transfer (adopt, already planned).** MosaicML's `index.json` is how infrastructure locates shards without reading shard content. The doc-corpus analog is an INDEX.md or frontmatter sidecar that an agent reads BEFORE opening a file to decide whether to open it at all. This is the Phase 1 proposal in MARKDOWN_REFACTOR_PLAN.md; training-data practice validates the design.

**Patterns that do NOT transfer:**
- Shard sizes (64 MB or 5 GB): our files are KB-scale; shard size is irrelevant
- Pre-tokenization: our corpus is read by an LLM at inference time, not pre-processed offline
- Sequential shuffled reads: our CCL is intentionally ordered and deterministic
- Parallel shard distribution: our CCL is sequential and single-agent
- Perplexity-based filtering: perplexity scores document coherence against a reference LM; our docs are small and domain-specific; perplexity would not be a useful signal

---

## Counter-evidence

The "deduplication transfers" claim has a limitation: training deduplication removes physically similar text (Jaccard similarity on n-grams). Our planning docs have cross-file conceptual overlap (same decision referenced from multiple docs) but rarely have verbatim text duplication. MinHash-style deduplication would not identify the problem. The fix for our corpus is governance (single-source-of-truth discipline), not algorithmic deduplication. This weakens the transfer from "direct technique" to "motivating principle."

The "quality tiers transfer" claim assumes that agents behave like the training process in that less-frequently-read docs matter less. This is not strictly accurate — a peripheral doc that IS the right source for a given query matters enormously in that context. The training analogy under-captures the "retrieval-on-demand" pattern. Anthropic's own guidance [#19] partially contradicts a strict quality-tier interpretation by recommending just-in-time loading rather than pre-loading only canon-tier docs.

---

## What this research does NOT cover

- Whether RAG / vector retrieval over our markdown corpus would outperform the current CCL grep-first pattern (addressed in prior research agent-discoverability-2026-05-15.md)
- Whether our Parquet pipeline artifacts (parquet_writer.py, parquet_registry_client.py) could benefit from training-data storage patterns (this is a separate question about operational data storage, not documentation corpus organization)
- Specific tokenization algorithms used by Anthropic for Claude (not publicly disclosed)
- How synthetic data generation (a 2024-2025 training trend not covered here) might apply to generating test fixtures for our Tier 2/3 tests

---

## Confidence assessment

Overall confidence in the recommendation: 🟡 Medium

- Findings 1-5 are well-sourced from primary vendor documentation and peer-reviewed papers
- Transfer claims (Patterns A, B, C) are inferential — no benchmark study directly tests training-data organizational principles against documentation corpus organization
- The fundamental asymmetry table (Finding 7) is the clearest finding and the most directly actionable; confidence in THAT specific synthesis is higher (🟢)
- The null results (shard size, pre-tokenization, parallel loading do not transfer) are high-confidence 🟢 — the differences in scale, read frequency, and reader capability are fundamental

---

## Suggested follow-up

- **Producer action**: When authoring MARKDOWN_REFACTOR_PLAN.md, cite this research for the quality-tier organizing principle (Pattern A) and the deduplication discipline (Pattern B). The Phase 1 sidecar/manifest proposal (Pattern C) now has an independent external analogy to cite.
- **No new D-number needed**: this research is exploratory/advisory; it validates existing directions rather than proposing new ones.
- **No validation gate action needed**: research was confirmatory + bound-setting (established which patterns do not transfer, which is the primary value of this inquiry).
- **Adjacent question for future research**: does the Navigation Paradox (from agent-discoverability-2026-05-15.md) interact with quality-tier structure? If canon-tier docs have dense cross-reference links to reference-tier docs, does that create navigational salience for the reference tier — eliminating the "island" problem even without an INDEX.md?

---

## Last reviewed

2026-05-15 (initial creation)
