# Research: Web Crawler and Search Engine Patterns Applied to Internal Markdown Corpora

**Date**: 2026-05-15
**Triggered by**: on-demand (user request — follow-on to `agent-markdown-traversal-2026-05-15.md` and `agent-discoverability-2026-05-15.md`)
**Question**: Can web-crawler / search-engine patterns inform how we organize our internal `docs/migration/` markdown corpus for AI agent consumption?
**Anchor**: D62 (CCL doctrine), Operationally stable pillar, $120K pillar (token cost reduction)
**Follow-on to**: `agent-discoverability-2026-05-15.md` (Navigation Paradox / grep-first / index-front)

---

## Summary

Web-crawler patterns transfer to internal markdown corpora in three areas with high fidelity: (1) discovery manifests, (2) structural content signals, and (3) anti-pattern avoidance. They transfer poorly in one critical area: the link-graph / PageRank model, because it requires a many-to-many hyperlinked web — our doc tree is mostly tree-structured. The best transferable insight for UDM specifically is not about crawlers but about what AI search engines reward in 2026: **lead-with-answer structure, heading hierarchy, and self-contained sections**. These are achievable in markdown at zero infrastructure cost. The llms.txt standard is immature (no major AI provider reads it in production). XML sitemap structure transfers well as a model for a `CORPUS_INDEX.md` manifest. PageRank's mathematics are general and do transfer to citation-weighted document graphs, but building the weighting machinery for a 25-file planning corpus is over-engineered relative to the navigation payoff.

Confidence: 🟢 High — multiple primary-vendor sources (Google, Bing/Microsoft, W3C), academic sources (SIAM PageRank paper), and 2026 industry benchmarks agree on core findings. Negative finding on llms.txt is well-evidenced from multiple independent studies.

---

## Sources

| # | URL | Date accessed | Authority |
|---|---|---|---|
| 1 | https://developers.google.com/search/docs/crawling-indexing/robots/intro | 2026-05-15 | Google (primary) |
| 2 | https://developers.google.com/crawling/docs/robots-txt/robots-txt-spec | 2026-05-15 | Google (primary) |
| 3 | https://codersera.com/blog/llms-txt-complete-guide-2026/ | 2026-05-15 | Industry (2026) |
| 4 | https://aeoengine.ai/blog/llms-txt-zero-usage-ai-bots-ignore | 2026-05-15 | Industry (2026) |
| 5 | https://www.ritnerdigital.com/blog/how-to-build-an-ai-sitemap-for-agentic-crawlers-a-technical-guide-to-signaling-content-structure-beyond-google | 2026-05-15 | Industry (2026) |
| 6 | https://schemavalidator.org/guides/microdata-vs-json-ld | 2026-05-15 | Industry |
| 7 | https://recomaze.ai/xml-sitemap-optimization-for-ai-crawlers | 2026-05-15 | Industry (2026) |
| 8 | https://satyadeepmaheshwari.medium.com/inverted-index-the-backbone-of-modern-search-engines-8bfd19a9ff75 | 2026-05-15 | Community |
| 9 | https://wikipedia.org/wiki/Okapi_BM25 | 2026-05-15 | Wikipedia |
| 10 | https://learn.microsoft.com/en-us/azure/search/index-similarity-and-scoring | 2026-05-15 | Microsoft (primary) |
| 11 | https://www.hobo-web.co.uk/is-google-pagerank-still-relevant-in-2026/ | 2026-05-15 | Industry (2026) |
| 12 | https://epubs.siam.org/doi/10.1137/140976649 | 2026-05-15 | Academic (SIAM Review) |
| 13 | https://calmops.com/ai/hybrid-search-rag-complete-guide-2026/ | 2026-05-15 | Industry (2026) |
| 14 | https://www.leapd.ai/blog/ai-visibility/how-chatgpt-google-ai-overviews-and-perplexity-source-information-in-2026 | 2026-05-15 | Industry (2026) |
| 15 | https://sluggenius.com/blog/url-slug-best-practices | 2026-05-15 | Industry (2026) |
| 16 | https://www.firecrawl.dev/glossary/web-crawling-apis/what-is-breadth-first-vs-depth-first-crawling | 2026-05-15 | Industry |
| 17 | https://web.dev/learn/html/semantic-html | 2026-05-15 | Google web.dev (primary) |
| 18 | https://llmrefs.com/generative-engine-optimization | 2026-05-15 | Industry (2026) |
| 19 | https://searchengineland.com/mastering-generative-engine-optimization-in-2026-full-guide-469142 | 2026-05-15 | Industry (2026) |
| 20 | https://en.wikipedia.org/wiki/Web_crawler | 2026-05-15 | Wikipedia |

---

## Findings by question

### Q1. Discovery mechanisms

**sitemap.xml**
The XML Sitemap Protocol (canonical spec: sitemaps.org, consumed by Google and Bing) is a structured file listing URLs with optional `<lastmod>`, `<changefreq>`, and `<priority>` metadata. Crawlers discover it via (a) direct submission to Google Search Console, (b) a `Sitemap:` directive in `robots.txt`, or (c) convention at `/sitemap.xml`. Hard limit: 50,000 URLs per file; sitemap index files aggregate multiple sitemaps. Critical 2026 finding: Google publicly ignores `<changefreq>` and `<priority>` values, computing its own crawl schedule from content change signals. The useful content is the URL list itself plus `<lastmod>`. Source: [1, 7].

**robots.txt**
A plain text file at the domain root defining Allow/Disallow directives per User-agent. Key directives: `User-agent` (which crawler), `Disallow` (blocked path), `Allow` (override of a broader disallow), `Crawl-delay` (Googlebot ignores it), and `Sitemap:` (pointing to sitemap location). Robots.txt is advisory — crawlers honor it voluntarily. Not all crawlers respect Allow or Crawl-delay. Source: [1, 2].

**Link-following (graph traversal)**
Crawlers begin from seed URLs, extract hyperlinks from fetched pages, and add them to a crawl frontier. The dominant algorithm is BFS (breadth-first) because it discovers high-PageRank pages early and distributes load across hosts naturally. DFS is less common because it drills into one host and tends to surface lower-quality deep pages. BFS distance from seeds correlates with page authority. Source: [16, 20].

**llms.txt**
Proposed 2024 by Jeremy Howard (Answer.AI). Format: a Markdown file at `/llms.txt` with a required H1 (project name), optional summary blockquote, H2-sectioned links, and an `## Optional` section for lower-priority links. The spec also defines `llms-full.txt` (concatenated page content) and `llms-ctx.txt` variants. **Adoption verdict**: As of Q1 2026, no major AI company (OpenAI, Google, Anthropic, Meta, Mistral) has publicly committed to reading it in production. A study of 300,000 domains found no measurable improvement in AI citations from having the file. IDE agents (Cursor, Continue) and developer documentation platforms are the primary consumers. Source: [3, 4].

**2026 AI-crawler discovery**
No new standardized convention has emerged beyond llms.txt, which itself has not been confirmed adopted by major providers. AI search engines primarily discover content through existing web crawl pipelines (GPTBot, ClaudeBot, PerplexityBot, GoogleBot/GoogleOther-Extended) that follow standard sitemap + link traversal, then prioritize for inclusion based on content quality signals rather than metadata declarations. Source: [5, 14].

---

### Q2. Content extraction

**JSON-LD (Google's recommended format)**
JSON-LD (JavaScript Object Notation for Linked Data) embeds structured data in a `<script type="application/ld+json">` block in the HTML `<head>`, completely decoupled from visible content. This is Google's explicit recommendation. JSON-LD uses schema.org vocabulary to declare entity types (Article, Product, FAQ, etc.) and their properties. The decoupled approach is easier to maintain as HTML changes.

**Microdata and RDFa**
Both embed metadata inline within HTML content using attribute annotations. Microdata (`itemprop`, `itemscope`, `itemtype`) is simpler but tightly coupled to HTML structure. RDFa supports multiple vocabularies and is more expressive, used primarily in government and academic contexts. Both are harder to maintain as templates evolve. In 2026, JSON-LD is the safe default for new projects; Microdata persists in legacy CMS themes. Source: [6].

**Open Graph / Twitter Cards**
Meta-tag-based standards (`<meta property="og:title">`, `<meta name="twitter:card">`) for social sharing and link preview. Used by Facebook, Twitter, Slack, Discord when generating link unfurls. Not consumed by AI search engines for ranking, but used for citation snippets in some contexts.

**HTML5 semantic elements**
`<main>`, `<article>`, `<section>`, `<nav>`, `<header>`, `<footer>` signal content type and hierarchy to crawlers. Googlebot uses semantic tags to identify the primary content of a page vs. navigation chrome. `<article>` signals standalone reusable content; `<main>` appears once per page and marks the primary content zone. Well-structured semantic HTML leads to cleaner snippet extraction and better indexing. Source: [17].

**Meta tags**
`<title>` (still primary relevance signal for lexical matching), `<meta name="description">` (used for SERP snippet, not ranking), `<meta name="keywords">` (ignored by Google since ~2009, Bing since ~2014). In 2026, title and structured data (JSON-LD) matter; keywords meta tag is cargo-cult.

---

### Q3. Indexing techniques

**Inverted index**
The foundational search data structure: a mapping from terms to posting lists (documents containing that term, with position offsets and frequencies). Building it involves: tokenization (split text into terms), normalization (lowercase, stemming/lemmatization), stop-word removal, and insertion into the index. Retrieval is: given query terms, intersect posting lists, then rank by relevance score. Source: [8].

**TF-IDF**
Term Frequency × Inverse Document Frequency. TF rewards terms appearing frequently within a document; IDF penalizes terms appearing in many documents (common words). Product gives a relevance weight per term per document. Limitation: no length normalization (longer docs score higher artificially) and no saturation (each additional occurrence contributes linearly). Source: [9].

**BM25 (Best Match 25)**
The modern standard in production search engines (Elasticsearch, Lucene, Azure AI Search, Solr). Improvements over TF-IDF: (1) term frequency saturation via a `k1` parameter — additional occurrences of a term contribute diminishing marginal relevance, modeled as `TF / (TF + k1)`; (2) document length normalization via a `b` parameter that penalizes longer documents proportionally. BM25 is the default ranking function in Azure AI Search, used by Bing. Source: [9, 10].

**PageRank / link graph**
PageRank models the web as a directed graph where each page is a node and each hyperlink is an edge. A page's authority equals the probability that a random walker would be at that page after many steps. Key insight: a link from an authoritative page is worth more than a link from an obscure one (recursive definition). Modern Google uses PageRank-NearestSeeds (pagerank_ns), where authority is measured relative to distance from trusted "seed" sites. A 2024 Google internal leak confirmed multiple PageRank variants run in production. The SIAM Review paper confirms the mathematics generalize to any directed graph — citations, co-authorship networks, protein interaction networks, road networks, brain connectivity graphs. Source: [11, 12].

**Vector index / semantic search**
Dense vector embeddings (from models like text-embedding-3-large, BGE, etc.) represent documents as points in high-dimensional space where semantic similarity correlates with geometric proximity. FAISS (Facebook AI Similarity Search) and HNSW (Hierarchical Navigable Small World) are the dominant index algorithms. FAISS Flat is exact (100% recall, slow at scale); HNSW is approximate (high recall/speed tradeoff, default in most vector DBs, good for 100K–10M vectors); IVF-PQ is best above 10M vectors. Source: [13].

**Hybrid retrieval (BM25 + semantic)**
Production AI search systems combine lexical (BM25) and semantic (vector) retrieval with Reciprocal Rank Fusion (RRF) score merging. RRF uses a smoothing constant (typically k=60): `score = 1/(k + rank_in_BM25) + 1/(k + rank_in_vector)`. Reason: BM25 wins on exact term matching (product names, IDs, rare terms); vector search wins on paraphrases and intent matching. Neither alone is sufficient for broad coverage. Source: [13].

---

### Q4. AI search engine patterns (2026)

**Perplexity AI**
Real-time web search on every query using multiple search APIs. Cites an average of 21.87 sources per response. Prioritizes freshness — 82% of citations come from content published in the last 30 days. All citations are inline, sentence-level, and clickable. It is the most citation-generous of the major AI search engines. Source: [14].

**ChatGPT (OpenAI) with web search**
Two-layer system: static training data + Bing-powered retrieval. Retrieval triggers selectively: 53.5% on commercial queries, 18.7% on informational. Citation is highly selective — cites only 15% of pages retrieved, with 3x higher probability for domains with active profiles on G2/Capterra-type platforms. FAQ schema correlates with 40% higher citation weighting. Source: [14].

**Google AI Overviews (SGE)**
Formerly correlated tightly with top-10 organic rankings (76% overlap mid-2025), but by early 2026 that correlation dropped to ~38%. Google AI Overviews now prioritizes semantic completeness (r=0.87 with selection) and multi-modal content (156% higher selection rate vs text-only). YouTube transcripts are unexpectedly influential. Source: [14].

**Anthropic ClaudeBot / claude.ai web search**
ClaudeBot crawls the public web for training data, not real-time search. claude.ai's web search (when enabled) is powered by external search providers, not a proprietary index. No public specification of how it consumes structured data has been published by Anthropic as of 2026. ClaudeBot does not meaningfully fetch llms.txt files. Source: [3, 4].

**Universal signals across all AI search**
The Leapd study found 44.2% of all LLM citations come from the first 30% of page content — the lead-with-answer pattern is empirically validated. Structured lists, quotes, and statistics produced 30–40% higher AI visibility (source: GEO study of 10,000 queries). E-E-A-T signals (Experience, Expertise, Authoritativeness, Trust) remain relevant but expressed differently — AI systems evaluate semantic completeness rather than link equity alone. Source: [14, 18].

---

### Q5. URL structure conventions

**Hierarchical paths**
Recommended maximum depth: 3 levels. Flatter is better — `/topic/subtopic` outperforms `/blog/2026/march/topic-post`. Deep path nesting signals less authority to AI crawlers. Source: [15].

**Canonical URLs**
`rel="canonical"` tells crawlers which URL is authoritative when duplicate/near-duplicate content exists at multiple URLs. Self-referencing canonicals are recommended on every page even without obvious duplicates. Source: [15].

**Slug stability**
Once assigned, URL slugs should never change without a 301 redirect. Renamed content without a redirect loses accumulated link equity and drops from search indexes. URL changes stabilize within a few weeks after proper redirect + sitemap resubmission. Source: [15].

**Implications for file paths**
The slug-stability principle maps directly to file path stability in a doc repo: renaming `03_DECISIONS.md` to `03_DECISIONS_phase0_D1-D50.md` breaks all existing `[](03_DECISIONS.md)` inbound references unless every reference is updated. The web analogy is a 301 redirect — the doc-corpus analog is an index entry or symlink pointing from the old name to the new split.

---

### Q6. Transfer analysis — what applies to internal markdown corpora

**HIGH-FIDELITY TRANSFER**

| Web pattern | Internal markdown analog | Evidence |
|---|---|---|
| sitemap.xml URL manifest | `CORPUS_INDEX.md` routing manifest listing every file with scope summary | Conceptual parity: crawlers skip unknown URLs without sitemap; agents skip unknown files without manifest |
| `<lastmod>` in sitemap | "Last reviewed: YYYY-MM-DD" per file | Signals currency without full metadata system |
| HTML5 `<main>` / `<article>` | H1 file title + first H2 summary block | Agents read first 30% disproportionately (empirically: 44.2% of citations from top 30% of content) |
| Lead-with-answer GEO pattern | Summary paragraph at file head, before details | Zero infrastructure cost; pure content discipline |
| Canonical URL / slug stability | File path stability + redirect entry in CORPUS_INDEX when splitting | Prevents dead cross-references when docs split |
| BFS discovery from seeds | CCL Stage 1 reads as "seeds" for agent traversal | Exact analogy: 4 mandatory first reads = seed pages; everything else discovered via cross-reference |
| Short paragraph / scannable structure | 2–4 sentence blocks, bullet lists for enumerable content | GEO study: 30–40% higher citation visibility for structured lists vs prose walls |

**MEDIUM-FIDELITY TRANSFER (worth adapting, not adopting literally)**

| Web pattern | Internal markdown adaptation | Caveat |
|---|---|---|
| robots.txt (allow/disallow) | `.claudeignore` patterns per D103 | Already implemented; direct functional analog |
| JSON-LD structured data | YAML frontmatter with `scope`, `phase`, `d_numbers` fields | No AI agent natively consumes YAML frontmatter without tooling (per prior research `agent-markdown-traversal-2026-05-15.md` Finding 14) — treat as future enhancement |
| Inverted index | Per-corpus search via `grep` on D-numbers, B-numbers, RB-numbers | Agents already use grep-first (prior research Finding A); the inverted-index IS the grep index implicitly |
| Hybrid retrieval (BM25 + vector) | N/A without tooling | Requires RAG infrastructure; out of scope for $120K ceiling |

**LOW / NO TRANSFER**

| Web pattern | Why it does not transfer |
|---|---|
| PageRank link-graph weighting | Web is many-to-many hyperlinked; our docs are mostly tree-structured (25 files, ~100 cross-references). PageRank mathematics generalize to any directed graph (SIAM), but the payoff at this corpus scale is negligible — a "hub" doc like HANDOFF.md is already called out explicitly in the CCL; no algorithm needed |
| XML sitemap 50K URL limit | Corpus has ~25 files; limits irrelevant |
| Crawl-delay / rate limiting | No rate limit concern on local filesystem |
| llms.txt | No major AI provider reads it in production (2026 evidence); unsuitable as an internal convention without external infrastructure |
| Open Graph / Twitter Cards | Social link preview only; no agent relevance |
| `<changefreq>` / `<priority>` in sitemap | Even Google ignores these; not worth implementing in any internal analog |

---

### Q7. Anti-patterns from web-crawler era and their doc-corpus equivalents

| Web anti-pattern | Why it fails | Internal markdown equivalent |
|---|---|---|
| **Cloaking** (different content for crawlers vs humans) | Google penalizes showing crawlers different HTML than human visitors | Equivalent: writing CLAUDE.md content ("for AI agents") that contradicts the actual doc content in `03_DECISIONS.md`. This doesn't exist today but would emerge if agent-facing summaries in CORPUS_INDEX drifted from source docs. Mitigated by Pattern F audits |
| **Keyword stuffing** | Penalized by Google; content becomes unreadable | Equivalent: over-indexing on D-number repetition, B-number tags in every paragraph without content payoff. Detection: any future reviewer finding "D62 mentioned 14 times in one page section with no additional context" should flag this |
| **Thin content** | Surface-level pages with no unique value get demoted | Equivalent: creating per-file summary stubs that restate what the source doc says without adding routing or context value. The prior research warned against agent-facing mirrors that duplicate content ("context rot" from Chroma research in `agent-markdown-traversal`) |
| **Duplicate content** | Two pages with same content split link equity and confuse crawlers | Equivalent: `HANDOFF.md` and `CURRENT_STATE.md` containing nearly identical "status" paragraphs. Mitigated by clear scope division: HANDOFF = "pick up mid-flight context", CURRENT_STATE = "point-in-time state snapshot" |
| **Hiding content behind interaction** (tabs, accordions) | Crawlers don't execute JS; content in tabs is invisible | Equivalent: key D-numbers or B-numbers buried only inside code blocks or HTML comments that agents skip. Risk area: decisions recorded only in git commit messages but not in `03_DECISIONS.md` |
| **Outdated content without staleness signal** | Google deprioritizes stale content; AI search shows 82% fresh citations | Equivalent: no "Last reviewed" date — agents can't tell if a doc is authoritative-current or authoritative-stale. The prior research proposed per-file "Last reviewed: YYYY-MM-DD" headers as mitigation |

---

## Recommendation for UDM

**Priority 1 — Adopt: lead-with-answer structure on every new doc section**
Empirically validated: 44.2% of AI citations come from the first 30% of content; structured lists score 30–40% higher than prose walls. For UDM specifically: every Phase doc's section should open with a 1–3 sentence direct answer / status statement before elaborating. This is a writing discipline, zero infrastructure cost, applicable to all future edits.

**Priority 2 — Adopt: sitemap-analog CORPUS_INDEX with `<lastmod>` equivalent**
The XML sitemap's core value is its URL-manifest function, not its metadata richness. Build a `CORPUS_INDEX.md` that lists every file with: (a) one-line scope description, (b) last-reviewed date, (c) the CCL stage it serves. This is the internal analog of a sitemap pointing crawlers to all known URLs. Agents discovering new files via this manifest avoid the Navigation Paradox (prior research Finding 3 from CodeCompass arxiv:2602.20048).

**Priority 3 — Adopt: file-path stability discipline when splitting**
The slug-stability principle from web SEO maps directly: when `03_DECISIONS.md` splits into `03_DECISIONS_phase0.md` + `03_DECISIONS_phase1.md`, the CORPUS_INDEX must record the old name and its successor — analogous to a 301 redirect. Every in-repo cross-reference must be updated at split time. This is already partially captured in the doc-split plan but worth naming as a discipline.

**Priority 4 — Do not adopt: llms.txt**
No evidence that any major AI provider reads it in production as of 2026. The internal equivalent (a routing manifest) should be a standard `CORPUS_INDEX.md` that both humans and agents can read, not an llms.txt file that only AI tools might consume if the spec ever gets production adoption.

**Priority 5 — Do not adopt now: inverted index, vector index, hybrid retrieval**
These require infrastructure (a vector database, embedding pipeline, BM25 index server) that conflicts with the $120K ceiling and "operational stability beats cleverness" pillar. Agents already use grep-first (Layer 1 per prior research), which is functionally a real-time inverted index query on the filesystem. The benefit of a pre-built index is speed, not capability — and at 25–50 files, speed is not the constraint.

**Priority 6 — Do not adopt: PageRank weighting for internal docs**
The SIAM paper confirms the mathematics generalize to any directed graph. However, at 25 files and ~100 cross-references, the computational payoff is negligible. The CCL's explicit 4-seed-reads already implement the intent of PageRank weighting without the machinery: NORTH_STAR, HANDOFF, CURRENT_STATE, CHECKS_AND_BALANCES are the "high-authority seed sites" of the corpus.

---

## Counter-evidence

- The GEO-optimization industry assumes web-scale corpora with thousands of pages. At 25 files, "optimization" for AI citation is over-engineering — agents read the files directly with no intermediary.
- The llms.txt standard has generated significant practitioner hype (844K+ implementations per the Ritner Digital source), but the empirical server-log data shows no major AI bot fetches it. The practitioner enthusiasm does not translate to confirmed consumption.
- The PageRank generalization to document corpora is academically validated, but no practitioner source demonstrates it delivering measurable navigation improvement for a 25-file internal planning corpus. The Navigation Paradox (CodeCompass) offers a more relevant frame for small corpora.

---

## What this research does NOT cover

- Bing/Microsoft's specific crawler behavior (msnbot) — findings would overlap with Googlebot
- Apple's Applebot and its specific signals
- Yandex, Baidu crawler specifics
- AEO (Answer Engine Optimization) as a distinct discipline from GEO — adjacent topic flagged for follow-up if doc visibility in Claude.ai's web search becomes a UDM concern
- Practical implementation of a CORPUS_INDEX.md file — this is producer work, not research

---

## Suggested follow-up

- If the user's question about blob storage analogies was a genuine pivot interest (not just a stepping stone to web crawlers), a separate research run on "blob storage metadata indexing patterns (Azure Blob, S3)" would address that thread directly.
- The Navigation Paradox (prior research) + the slug-stability finding together suggest a concrete B-item: formalize doc-split discipline including CORPUS_INDEX entries + cross-reference updates as part of any future markdown refactoring effort. This is producer work, not research.
- The GEO "lead-with-answer" finding is immediately actionable in doc writing discipline but requires no decision or B-item — it is a writing convention.

---

*Research artifact authored 2026-05-15. Note: this artifact was reconstructed by the parent agent from the udm-researcher sub-agent's chat-text output, which mistakenly skipped the Write step. Content is verbatim from the sub-agent's response per the project's audit-trail discipline.*
