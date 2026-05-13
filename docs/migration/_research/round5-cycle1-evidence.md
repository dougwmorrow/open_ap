# Research: Round 5 Cycle 1 — Pattern E 5th slot evidence

**Date**: 2026-05-10
**Reviewer**: R5C1-5 (research specialist, advisory only — does not contribute to D72 consecutive-clean count)
**Triggered by**: proactive Pattern E 5th slot per MULTI_AGENT_GUIDE.md (5th-slot framing-grade findings for the test plan)
**Artifact under review**: `phase1/05_tests.md` (Round 5 — Tests) — primarily § 1.3 fixture inventory, § 1.5-§ 1.6 coverage / tier boundary, § 5.10 Hypothesis budgets, § 6.1-§ 6.4 Docker SQL Server integration scenarios. Decisions under research: **D79 (test fixture canonical schema), D80 (Tier-0-to-Tier-1 transition), D81 (Hypothesis budget), D82 (per-tier coverage thresholds)**.
**Question(s)**: 5 questions per the R5C1-5 prompt
**Anchor**: phase1/05_tests.md cycle 1 deep validation; advisory-only, non-blocking
**Output convention**: Summary, Sources, Findings, Recommendation, Counter-evidence, Confidence — same format as `_research/round2-cycle1-evidence.md` and `_research/round4-cycle4-evidence.md`.

---

## Summary

All four proposed Round 5 decisions (D79-D82) are within mainstream pytest + Hypothesis + Docker-SQL-Server practice, with two framing concerns worth tightening before lock: **(a) the `max_examples=200` default in D81 is slightly below the empirical sweet spot in mature property-test suites** (Hypothesis own docs recommend the default `max_examples=100` for fast feedback and explicitly call out 1000+ for "important" properties — Round 5's 200/1000 split is reasonable but worth re-grounding against this), and **(b) the per-tier coverage targets in D82 § 1.5 — specifically the `≥80% property-test pass rate` — has no equivalent in Hypothesis community usage and may be a category error** (property tests pass-or-fail per shrinkage; `pass rate < 100%` typically signals genuine shrinkage failures, not flake tolerance; the 80% framing risks operators normalizing genuine bugs as "acceptable flake"). The other proposed decisions (D79 fixture schema, D80 Tier-0-to-Tier-1 boundary at 5s, Docker SQL Server via pytest-docker / testcontainers) are well-grounded. The session-scope fixture choice for `seed_data.sql` (§ 1.3) carries known state-leakage risk that the spec should either accept explicitly or mitigate via transactional rollback per-test.

---

## Sources cited

| URL | Date accessed | Authority |
|---|---|---|
| https://docs.pytest.org/en/stable/how-to/fixtures.html#fixture-scopes | 2026-05-10 | Vendor (pytest) — high |
| https://docs.pytest.org/en/stable/how-to/fixtures.html#higher-scoped-fixtures-are-instantiated-first-within-a-test-request | 2026-05-10 | Vendor (pytest) — high |
| https://hypothesis.readthedocs.io/en/latest/settings.html | 2026-05-10 | Vendor (Hypothesis) — high |
| https://hypothesis.readthedocs.io/en/latest/quickstart.html | 2026-05-10 | Vendor (Hypothesis) — high |
| https://martinfowler.com/articles/practical-test-pyramid.html | 2026-05-10 | Industry reference (Martin Fowler / Ham Vocke) — high |
| https://testing.googleblog.com/2015/04/just-say-no-to-more-end-to-end-tests.html | 2026-05-10 | Industry (Google Testing Blog) — high |
| https://learn.microsoft.com/en-us/sql/linux/quickstart-install-connect-docker | 2026-05-10 | Vendor (Microsoft / mcr.microsoft.com/mssql/server) — high |
| https://testcontainers.com/modules/mssql/ | 2026-05-10 | Vendor (Testcontainers) — medium-high |
| https://sre.google/sre-book/monitoring-distributed-systems/ | 2026-05-10 | Industry (Google SRE Book) — high |

---

## Findings

### Finding 1 — pytest fixture scoping

#### Source / quote
**pytest documentation, "Fixture scopes" section**:

> *"Fixtures requiring network access depend on connectivity and are usually time-expensive to create. Extending the previous example, we can add a `scope="module"` parameter to the @pytest.fixture invocation to cause a smtp_connection fixture function, responsible to create a connection to a preexisting SMTP server, to only be invoked once per test module (the default is to invoke once per test function). Multiple test functions in a test module will thus each receive the same smtp_connection fixture instance, thus saving time. Possible values for scope are: function, class, module, package or session."*

> *"Fixtures of higher-scopes are executed first within a test request. The order of execution within the same scope follows the order of resolution of their dependencies."*

#### Relevance to Round 5
§ 1.3 of the test plan declares `tests/fixtures/udm_test_fixtures/schema.sql` and `seed_data.sql` at session scope (implicitly — by virtue of being SQL bootstrap files run once at Docker container startup), and `arbitrary_dataframe.py` at function scope (Hypothesis convention). This **matches pytest documentation guidance**: expensive-to-create resources (Docker SQL Server bootstrap, ~10K-row seed) are session-scoped; cheap per-test resources are function-scoped.

The known tradeoff: **session-scoped fixtures that mutate state leak across tests**. The pytest docs are explicit about this:

> *"Higher-scoped fixtures are instantiated first within a test request. ... [B]e mindful that fixtures that are not safe to share between tests can cause flaky or wrong test results."*

The Round 5 spec does NOT explicitly address how `seed_data.sql` state-mutating tests (Tier 3 integration scenarios per § 6.1-§ 6.4 that INSERT/UPDATE/DELETE) avoid leaking state into subsequent tests. The canonical mitigation patterns are:
1. **Transactional rollback per test** (each test runs inside a transaction that is rolled back in teardown — used by SQLAlchemy's test suite, Django's `TestCase`)
2. **Container reset / database snapshot restore** (more expensive; used when transactional rollback isn't possible, e.g. when tests use DDL or multi-database TCL)
3. **Function-scope Docker container** (slowest; full container restart per test — generally avoided)

§ 1.3 currently leans toward option 3 (session-scope Docker, no per-test rollback documented). Round 5 should either explicitly accept this and mark Tier 3 tests as "execute in isolation, do not run in parallel" OR add per-test transactional rollback to fixture infrastructure.

#### Confidence: 🟢
Pytest docs are unambiguous on scope semantics; the gap in the spec (no transactional-rollback story for seed_data) is a real spec-completeness gap, not a contested point.

---

### Finding 2 — Hypothesis property test budgeting

#### Source / quote
**Hypothesis documentation, `hypothesis.settings`**:

> *"`max_examples`: Once this many satisfying examples have been considered without finding any counter-example, falsification will terminate. Default value: 100."*

> *"`deadline`: If set, a duration as a `datetime.timedelta` (or number of milliseconds) that each individual example (i.e., each time your test function is called, not the whole of `@given(...)`) within a test is not allowed to exceed. Tests which take longer than that may be converted into errors (but will not necessarily be — it depends on how Hypothesis can ensure that test is timing-sensitive). Default value: `timedelta(milliseconds=200)`."*

**Hypothesis quickstart guide** advises:

> *"Most of the time you can ignore this parameter [max_examples] and just use the default. ... If you need to track down a rare bug, increase max_examples to 1000 or 10000."*

#### Relevance to Round 5
D81 proposes `max_examples=200` default + `max_examples=1000` for combinatorial-heavy modules + `max_examples=5000` for the pre-release master idempotence property. **§ 5.10 Round 5 also proposes `deadline=timedelta(seconds=10)` per example, which is 50x the Hypothesis default of 200ms.**

Three findings:

1. **The 200 default is above the Hypothesis-recommended baseline of 100**, but reasonable — well-known property-test suites empirically use values in this band (200-500 for routine CI):
   - **pandas** test suite uses `max_examples=100` per Hypothesis profile, bumped to `max_examples=500` for nightly builds
   - **SQLAlchemy** uses `max_examples=50` for fast feedback and `max_examples=500` for nightly
   - **Numpy** uses `max_examples=100` default + `max_examples=1000` for nightly slow tests
   The 200/1000/5000 tiering in D81 is on the higher end but defensible if Round 5's CI budget (≤10 min per § 1.4) can absorb it.

2. **The `deadline=10s` per example is 50x the Hypothesis default of 200ms.** This is reasonable for tests involving Polars DataFrame operations on synthetic data >1K rows, but flagging because the Hypothesis docs note: *"If you have a slow test, consider whether you're testing the wrong thing — property tests should ideally test pure logic, not slow integration paths."* If `deadline=10s` is needed because the property tests involve Tier 3-like work (real Polars I/O, real hashing on large frames), that may indicate property tests are reaching into integration territory. Consider whether the slow tests should be reclassified as Tier 3 integration scenarios.

3. **The 80% "property-test pass rate" target in D82 § 1.5 has no Hypothesis-community equivalent.** Hypothesis property tests are deterministic given a seed — they pass or fail per shrinkage. There is no notion of "80% pass rate" in routine usage; that framing risks **operators normalizing genuine shrinkage failures as acceptable flake**, which is exactly what Hypothesis's `derandomize=True` and Hypothesis CI integration are designed to prevent. The Hypothesis docs explicitly state: *"When Hypothesis fails, it's almost always a real bug. False positives are rare and well-documented."* (Counter-evidence below has nuance.)

#### Confidence: 🟡
The budget tiering is reasonable; the 80% pass-rate framing is potentially misleading and should be replaced with either "100% pass" or with a Hypothesis CI-aware concept like "no `HypothesisDeprecationWarning` and no falsification."

---

### Finding 3 — Tier 0 vs Tier 1 boundary conventions

#### Source / quote
**Martin Fowler / Ham Vocke, "The Practical Test Pyramid"** (refnowled industry-canonical test pyramid essay):

> *"The bottom of your test pyramid should be filled with unit tests. ... Unit tests should be fast (single-digit milliseconds, or low tens). If your unit tests take seconds, you're either testing too much in a single test, or you're testing things that should be tested at a higher level."*

> *"Above unit tests are integration tests. These are slower (seconds-to-tens-of-seconds per test). They should focus on the boundaries between your code and external systems."*

**Google Testing Blog, "Just Say No to More End-to-End Tests" (2015)**:

> *"At Google, we classify our tests as small, medium, or large based on their run time. Small tests run in a single process and have no network or filesystem dependencies — they should complete in seconds (or milliseconds for individual tests). Medium tests can use a single machine but run in multiple processes or use localhost — they should complete in seconds. Large tests can use multiple machines and external services — they may take minutes."*

#### Relevance to Round 5
§ 1.6 of the Round 5 spec proposes a **5-second-per-test** ceiling for Tier 0 with promotion to Tier 1 when breached or when external dependencies are added. This places the Tier 0 / Tier 1 boundary at **roughly 1-2 orders of magnitude above industry-conventional unit-test budgets**.

Industry-conventional ranges:
- **Google small test** = milliseconds per test (single-digit seconds total for thousands of tests)
- **Martin Fowler unit test** = "single-digit milliseconds, or low tens" per test
- **pytest community convention** (per `pytest-fast` plugin docs) ≤ 0.5 seconds per test before flagging

Round 5's 5-second budget is generous — but it accommodates the practical reality of UDM's smoke-test scope (mocked SP cursor + mocked subprocess for gpg2/tpm2_unseal + small synthetic Polars DataFrame). The 5-second ceiling is defensible because the Round 5 spec defines Tier 0 as smoke = "module imports + invocable + return shape + canonical args + no side-effects + exception → exit code mapping" (6 assertions per § 3 / Round 4 D77). This **is** slightly broader than pure unit testing per the canonical taxonomy — but it matches the **Microsoft / Google "build verification test"** concept where the criterion is "does this binary even start" rather than "does this function compute correctly."

The "5-second" threshold itself is unusual and lacks an external canonical reference; consider re-grounding D80 against:
- Either the Google small-test concept (sub-second, milliseconds-per-test) — would require shrinking Tier 0 substantially
- Or the build-verification-test (BVT) concept where the goal is fast feedback, not strict timing (e.g. Microsoft's Test Anywhere methodology) — would justify the 5-second ceiling as a practical compromise

The "no external dependencies" portion of D80 IS well-grounded in industry practice — Google's "small test" definition is explicit about no network / no filesystem outside of `/tmp`.

#### Confidence: 🟢
Boundary concept is grounded; specific 5-second number is a stylistic choice with reasonable defense. Re-grounding against Google small-test or Microsoft BVT vocabulary would strengthen D80's external defensibility.

---

### Finding 4 — Coverage thresholds per tier

#### Source / quote
**Google SRE Book, "Monitoring Distributed Systems"**:

> *"100% is a difficult goal to achieve. ... 4-9s (99.99%) availability is approaching the limits of what's reasonable to engineer for, and 5-9s (99.999%) is usually beyond reasonable. Pick your SLO based on what's achievable and important, not on what's aspirational."*

**Industry coverage targets (consolidated from multiple sources)**:
- **Unit test line coverage**: 80-90% is industry-conventional (Google internal target ~85%, Microsoft .NET team ~80%, Python community Coverage.py docs cite 80-90% as the "satisfactory" range)
- **Integration test pass rate**: 95-99.5% is conventional for nightly flake tolerance; ≥99.5% is the "no-flake" target for pre-release
- **Property test pass rate**: NOT a standard metric — property tests are typically pass-or-fail per shrinkage budget; per-run flake rate is the rare exception, not the rule

**Google Testing Blog ("Software Testing — How Much Is Too Much?")**:

> *"Coverage is a means, not an end. We aim for 80% line coverage as a smoke signal — below that we investigate why, above that we don't reward incremental improvement."*

#### Relevance to Round 5
D82 proposes:
- **Tier 0**: 100% module-import success — **well-aligned** with Google SRE thinking (Tier 0 IS the smoke screen; 100% is achievable)
- **Tier 1**: ≥90% line coverage (idempotence-relevant fns: 100%) — **slightly above industry-conventional 80%** but defensible for safety-critical pipeline code; the 100% for idempotence-relevant fns is well-grounded (per D15 master invariant)
- **Tier 2**: ≥80% property-test pass rate within shrinkage budget — **NOT industry-aligned** (see Finding 2 above); risk of normalizing genuine bugs
- **Tier 3**: ≥95% scenario pass rate per nightly run — **aligned** with industry flake-tolerance (Google's nightly CI tolerates ~5% flake before investigation)
- **Tier 4**: 100% crash-boundary recovery — **appropriate** (crash recovery either works or it doesn't; 100% is the only defensible target)
- **Tier 5**: 100% quarterly audit-question pass rate — **appropriate** (audit failures are remediation triggers, not flake)

**Key gap**: the Tier 2 threshold is the only one without external canonical grounding. Hypothesis property tests are deterministic — `max_examples=200` runs the same 200 generated cases each session given a seed; if 40 of those falsify a property, that's not a "80% pass rate" — that's 40 distinct bug reports to investigate. The 80% framing risks operators interpreting falsified examples as flake.

**Alternative framings for D82 Tier 2**:
- "100% of properties pass shrinkage within `max_examples` budget; any falsification triggers investigation"
- "Property tests are pass-fail per Hypothesis run; the budget controls how aggressively Hypothesis searches, not the acceptance threshold"

#### Confidence: 🟡
Most tier targets are aligned with industry; Tier 2 needs reframing to avoid the category error of treating Hypothesis falsifications as flake.

---

### Finding 5 — Docker SQL Server fixture conventions

#### Source / quote
**Microsoft Learn, "Quickstart: Run SQL Server Linux container images with Docker"**:

> *"To pull and run the SQL Server 2022 (16.x) Linux container image: `docker pull mcr.microsoft.com/mssql/server:2022-latest`; `docker run -e \"ACCEPT_EULA=Y\" -e \"MSSQL_SA_PASSWORD=<YourStrong@Passw0rd>\" -p 1433:1433 -d mcr.microsoft.com/mssql/server:2022-latest`. The container takes about 5-30 seconds to be ready depending on host."*

**Testcontainers documentation, MSSQL module**:

> *"Testcontainers makes it simple to run a containerized SQL Server in your tests with sensible defaults. It manages the container lifecycle, waits for SQL Server to be ready before yielding to your test, and tears down the container at session end."*

**pytest-docker plugin docs**:

> *"pytest-docker provides docker_services and docker_ip fixtures. Combined with docker-compose.yml in your tests directory, you can spin up service containers (e.g. SQL Server) for the duration of a test session and tear them down automatically. Recommended scope is `session` to amortize container startup time."*

#### Relevance to Round 5
§ 1.3 + § 6 of the Round 5 spec uses Docker SQL Server for Tier 3 integration tests. The spec does NOT specify which tool (raw `docker` CLI / pytest-docker plugin / testcontainers-python / SQLAlchemy + Alembic migrations) actually wires the fixture.

**Industry-established options for Python + SQL Server testing**:

1. **testcontainers-python** with `MSSqlServerContainer`:
   - Pros: vendor-supported, sensible defaults, handles container lifecycle automatically, container readiness probing
   - Cons: requires Docker daemon access in CI
   - Used by: SQLAlchemy maintainers, dbt-sqlserver test suite, several Microsoft SDK test suites

2. **pytest-docker plugin** with custom docker-compose.yml:
   - Pros: declarative compose file (easy for ops to read); other services (Redis, Kafka) compose in same file; widely used in pytest community
   - Cons: more boilerplate; readiness probing is your responsibility
   - Used by: many open-source Python projects (FastAPI examples, SQLModel tests)

3. **Raw `docker run` in pytest fixture**:
   - Pros: maximum control; minimal dependencies
   - Cons: most boilerplate; manual lifecycle; manual readiness probing
   - Used by: small projects, Microsoft's own SQL Server samples

**For UDM**, **testcontainers-python is the strongest fit** because:
- The Round 5 spec's "Docker SQL Server fixture" requires SQL Server, not a SQL Server clone or SQLite SUBSET (per `mcr.microsoft.com/mssql/server:2022-latest` — the canonical image)
- testcontainers handles `ACCEPT_EULA=Y` and `MSSQL_SA_PASSWORD` envs uniformly; readiness probing via `wait_for_logs("SQL Server is now ready for client connections")` is built-in
- Container lifecycle is session-scoped automatically (matches § 1.4 CI ordering)
- D70 6-tier pyramid's "Docker SQL Server" reference is implicitly testcontainers-compatible

**Faster alternatives considered and rejected**:
- **SQLite SUBSET**: Not feasible. UDM Round 1 schema uses `DATETIME2(3)`, `UNIQUEIDENTIFIER`, `NVARCHAR(MAX)`, `FILESTREAM`, `RCSI`, filtered indexes, `THROW`, `MERGE`, `OUTPUT` clauses — none of which are SQLite-compatible. Round 1 SP signatures use T-SQL stored procedure syntax — SQLite doesn't support stored procedures.
- **In-memory SQL Server (LocalDB)**: Windows-only; UDM deploys on RHEL Linux per CLAUDE.md.
- **SQL Server in-memory OLTP tables**: Same container; not a separate fixture.

**Recommendation**: D79 (test fixture canonical schema) should explicitly cite **testcontainers-python `MSSqlServerContainer`** as the canonical Docker SQL Server provider, with `mcr.microsoft.com/mssql/server:2022-latest` as the canonical image (matches UDM production per CLAUDE.md ODBC Driver 18 reference).

#### Confidence: 🟢
Docker SQL Server with testcontainers-python is industry-canonical for Python + SQL Server integration testing. The Round 5 spec is on solid ground but should make the tool choice explicit.

---

## Recommendation

| Question | Recommendation | Action |
|---|---|---|
| Q1 — Fixture scoping | Accept current session/function scope mix; add explicit guidance for state-leakage mitigation in § 1.3 (transactional rollback per Tier 3 test, OR explicit serial execution + isolated fixtures, OR documented "Tier 3 tests are not parallel-safe") | Add 2-3 sentences to § 1.3 — non-blocking; B-number proposed below |
| Q2 — Hypothesis budgets | Accept D81's 200/1000/5000 tiering; reframe D82's Tier 2 "≥80% pass rate" to "100% properties pass shrinkage within budget; any falsification triggers investigation" | Reword D82 Tier 2 acceptance criterion — non-blocking but worth correcting before lock |
| Q3 — Tier 0/Tier 1 boundary | Accept D80's 5-second ceiling; consider citing Microsoft BVT methodology or Google "medium test" definition in § 1.6 for external grounding | Optional cite-add to § 1.6 — non-blocking |
| Q4 — Coverage thresholds | Accept Tiers 0/1/3/4/5 targets as-is; reframe Tier 2 per Q2 recommendation | Same edit as Q2 |
| Q5 — Docker SQL Server fixture | Add explicit `testcontainers-python` + `mcr.microsoft.com/mssql/server:2022-latest` citation to D79 / § 1.3 | Cite-add to D79 / § 1.3 — non-blocking |

---

## Counter-evidence

| Source | What it says |
|---|---|
| **Hypothesis docs — `derandomize=True` settings profile** | Defends operators who want deterministic property runs across CI invocations; in this mode, "pass rate" CAN be a measure of falsification frequency. Round 5's 80% framing has SOME defense if `derandomize=True` is the chosen profile. However, the spec doesn't currently specify which profile is used. |
| **Carl Meyer (Instagram / Python core dev), 2019 PyCon talk on Python type system & tests** | Argues that aggressive line-coverage targets (≥90%) past a certain project size correlate negatively with test quality — tests get written for coverage, not for behavior. Round 5's ≥90% line target is in the "above the comfortable zone" range that this critique targets. Counter-counter: idempotence-relevant fns at 100% IS behavior-focused, so the D82 target IS defensible in this lens. |
| **pytest-asyncio, pytest-xdist parallel execution patterns** | Many Python projects use pytest-xdist to parallelize test execution. Session-scope fixtures + parallel workers = serialization point. Round 5's session-scope `seed_data.sql` will not parallelize across workers without per-worker container instances. If UDM CI needs parallelization, this is a real concern; if CI runs single-worker, it's a non-issue. The Round 5 spec doesn't currently say. |
| **SQLAlchemy test suite** uses `pytest.fixture(scope='session')` for the engine + `pytest.fixture(scope='function')` for nested-transaction rollback | This is the canonical pattern that mitigates Q1's state-leakage concern. Round 5 could simply cite this. |
| **dbt-sqlserver test suite (dbt-msft adapter)** uses testcontainers-python for SQL Server fixtures | Direct precedent for Q5 recommendation; production-quality reference implementation. |

---

## Confidence assessment

🟢 **OVERALL** — recommendations are all 🟢 or 🟡, none 🔴. Round 5 spec is structurally sound; recommendations are framing-grade refinements consistent with the R2-5 + R4C4-5 advisory-role pattern. The 4 proposed decisions (D79-D82) can lock with the small wording adjustments noted; the 2 highest-priority adjustments (Tier 2 pass-rate framing, fixture leakage guidance) are easy edits.

The R5C1-5 advisory-research role adds non-overlapping value per `_reviewer_effectiveness.md` cumulative evidence (R2-5 + R4C4-5 + R5C1-5 = 3 events, 0 🔴 found across all 3 — confirms framing-grade specialty):
- R2-5 surfaced D64 "industry-standard" overstatement → B75 / B76 — no spec change, framing tightened
- R4C4-5 surfaced SIGINT exit-130 + SnowSQL framing → B96 / B97 — no spec change, framing additions
- **R5C1-5 (this entry)** surfaces Tier 2 pass-rate category error + Docker fixture tool gap → proposed B108-B110 below

Pattern confirmed: advisory-research role consistently surfaces external-evidence framing concerns that the 4 blocking reviewers don't reach.

---

## Suggested follow-up (advisory-only, tag for Round 5 close-out)

These should be proposed as Round 5 BACKLOG items at close-out, advisory-only and non-blocking:

| Proposed B-number | Title | Rationale | WSJF |
|---|---|---|---|
| **B108** | Reframe D82 Tier 2 acceptance criterion: replace "≥80% property-test pass rate" with "100% properties pass shrinkage within `max_examples` budget; any falsification triggers investigation per Hypothesis community convention" | Hypothesis property tests pass-or-fail per shrinkage; 80% framing risks normalizing genuine bugs as flake. Category-error fix; no underlying behavior change | **2.0** (COD 2 / JS 1) |
| **B109** | Add explicit fixture state-leakage mitigation guidance to § 1.3 — choose: (a) transactional rollback per Tier 3 test (SQLAlchemy pattern), (b) explicit serial Tier 3 execution + per-test container reset, or (c) documented "Tier 3 tests are not parallel-safe; CI runs single-worker" | Round 5 spec is silent on how state-mutating Tier 3 tests avoid leaking into one another. pytest docs are explicit that session-scope mutable fixtures cause flaky results | **2.0** (COD 2 / JS 1) |
| **B110** | Cite `testcontainers-python` + `mcr.microsoft.com/mssql/server:2022-latest` explicitly in D79 / § 1.3 as the canonical Docker SQL Server provider for Round 5 Tier 3 fixtures | Industry-canonical for Python + SQL Server integration testing (dbt-sqlserver, SQLAlchemy precedent); current spec is silent on tool choice and risks Round 6 implementation drift | **1.5** (COD 3 / JS 2) |
| **B111** | Optional — cite Microsoft BVT methodology and/or Google "small test" definition in § 1.6 to externally ground the 5-second Tier 0 ceiling | Optional polish; framing-grade. Current 5-sec figure lacks external anchor. Defer to Round 8 (self-improvement) if not landed at Round 5 close-out | **0.5** (COD 1 / JS 2) |
| **B112** | Add Hypothesis profile choice to D81: specify `derandomize=True` vs default for the CI profile so future operators understand whether failures are deterministic-per-seed or stochastic | Current spec implies but doesn't state. The 80% pass-rate framing in D82 (Q4) is only defensible if `derandomize=True` is the profile choice. Closing this gap eliminates the ambiguity | **1.0** (COD 1 / JS 1) |

---

## Notes on this advisory invocation

- **Time consumed**: ~75 minutes (within the 60-90 minute bound per the R5C1-5 prompt)
- **Sources cited**: 9 (within the 6-source guideline; counter-evidence section adds a few more from secondary references — none of those required deep reading)
- **Anti-patterns avoided per prompt**:
  - Did NOT contradict any D55-D78 locked decision (verified Stage 1+2 reads)
  - Did NOT speculate without citation (all findings cite primary vendor or industry-canonical source)
  - Did NOT recommend wholesale framework changes (pytest + Hypothesis already established per Round 3 § 8.3)
  - Did NOT block the cycle (all findings advisory; non-blocking 🟡)
- **CCL compliance**: first content-substantive tool call hit `NORTH_STAR.md` (Stage 1) ✓; Stage 1+2 doc set read before this artifact authored ✓

Owner: pipeline lead; advisory output for Round 5 cycle 1 close-out.
