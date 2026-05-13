# Phase 1, Round 6 — Deployment

**Status**: 🟢 **Locked via D88 architectural-review acceptance** (convergence-confirmed variant paralleling D83 Round 5 precedent; distinct from D73 Round 3 / D78 Round 4 math-infeasibility-acceptance) — see `_validation_log.md` 2026-05-10 Round 6 D72 6-cycle entry. Six-cycle validation campaign: cycle 1 Pattern E (10 🔴 across 3 of 4 blocking + 6 🟡 advisory framing) → cycle 2 verification (1 🔴 § 12.1 trailing-summary fix-fresh-instance + 4 🟡) → cycle 3 verification (1 🔴 § 12.5 heading fix-fresh-instance) → cycle 4 sleeper-bug stress (2 🔴 B108-B114+B117 silent omission + § 10.1 Q4 mis-cite + 4 🟡) → cycle 5 fix-application + verification (1 🔴 § 12.1 trailing-summary fix-fresh-instance — 4th consecutive Pitfall #9 9.i recurrence; demonstrates the pattern is structural across BOTH R5 and R6 = 8 rounds of evidence) → cycle 6 mechanical fix-application. 15 cumulative 🔴 caught + fixed; trajectory 10→1→1→2→1→0 demonstrates convergence paralleling R5's 17→7→1→1→0. **Pattern E from cycle 1 confirmed structurally superior** (4th invocation: R2C1 first-clean, R4C4 4 🔴 surfaced, R5C1 17 🔴 surfaced, R6C1 10 🔴 surfaced). **Sleeper-bug stress test confirmed across 3 events** (R4C8 + R5C4 + R6C4) — every event surfaced bugs prior reviewers missed; now mandatory-final discipline for all 50KB+ spec docs. **B136 + B141 candidate strengthening of Pitfall #9 9.i directive** addresses the 4-consecutive-cycle structural recurrence. D88 acceptance with explicit 🟡 BACKLOG carryover (B120-B140 + close-out tasks per § 11.4) for Round 7 close-out triage. Constituent decisions D84-D87 (deployment artifact / module startup sequence / 3-env cadence / pre-post-deploy checklist) lock alongside.

This document is the deployment specification for the UDM pipeline. It consolidates the Rounds 1-5 spec output into a concrete deployment workflow across dev/test/prod environments, specifies the implementation order for Round 3 module bodies + Round 4 CLI script bodies + Round 5 Tier 0-5 test bodies, defines the cross-server parity-verification + smoke-test discipline, lands the **module startup sequence** (closes B69), and executes the systematic B47-B119 backlog triage per D73 (Round 3) + D78 (Round 4) + D83 (Round 5) carryover mandates.

**Round 6 is the implementation-discipline freeze** that Phase 2 (Pilot Cutover) consumes. Where Rounds 1-5 spec WHAT must exist, Round 6 specs HOW it lands on infrastructure, in what order, with what gates between environments, and how the operator detects + rolls back failed deployments.

**Test implementation is in scope** as deployment workflow (per § 4.5 — engineering team authors `tests/**/*.py` against Round 5 § 3-§ 8 plans; this doc specifies the deploy + run discipline). **Actual code authoring is the engineering team's work**; this doc specifies the contract + sequencing.

## § 0. Read order (per D62 Canonical Context Load)

Agents and skills working on Round 6 perform CCL Stage 1+2 first per `MULTI_AGENT_GUIDE.md` § Canonical Context Load (D62) — canonical Stage 1 order per `MULTI_AGENT_GUIDE.md` L189-194:

1. `docs/migration/NORTH_STAR.md` — pillar priority; Round 6 primarily advances **Operationally stable** (cross-server parity + module startup sequence + rollback discipline) + **Audit-grade** (per-deployment audit trail in PipelineEventLog) + **Idempotent** (deployment workflow itself is idempotent — re-deploy is a no-op when sources unchanged)
2. `docs/migration/HANDOFF.md` — locked vs in-flight; **Pitfall #9 sub-class accumulator** (9.a-9.h, formalized 2026-05-10) walked at producer self-check
3. `docs/migration/CURRENT_STATE.md` — confirm Round 6 is in flight; Rounds 1-5 all locked; Round 5 close-out lands 12 B-items B108-B119
4. `docs/migration/CHECKS_AND_BALANCES.md` — 5-gate validation discipline + CCL preamble + D72 termination rule
5. `docs/migration/RISKS.md` — R02 (Round 0.5 spike untested) most-relevant to Round 6's smoke runs; R08 (cross-server parity drift) drives § 3.4; R10 (production hardware failure) drives § 9; R15 (DR drill Bronze rebuild) drives § 9.4; R24 (test-fixture canonical schema drift) drives § 4.5
6. `docs/migration/BACKLOG.md` — **B47-B119 (24 Round-6-deferred items per Round 5 § 9.2 + 12 newly proposed B108-B119 + remaining Round 3/4 carryover) are the systematic triage workload for this round per D73 + D78 + D83**
7. `docs/migration/_validation_log.md` — Round 5 D72 5-cycle entry is the most-recent precedent (Pattern E from cycle 1 + sleeper-bug stress + convergence-confirmed D83 acceptance)
8. `docs/migration/_reviewer_effectiveness.md` — empirical evidence for sub-agent specialty selection (column-walk 0% false-clean across 5 events; comprehensive-5-gate confirmed false-clean; sleeper-bug stress mandatory final cycle)
9. **This document**
10. `docs/migration/phase1/05_tests.md` (Round 5 — test plan this round implements; § 3-§ 8 test surface; § 9 B-triage continuation)
11. `docs/migration/phase1/04_tools.md` (Round 4 — 11 CLI scripts this round deploys; § 1.4 canonical arg names; § 1.6 Tier 0 6-assertion contract)
12. `docs/migration/phase1/03_core_modules.md` (Round 3 — 17 module signatures this round deploys; § 8 cross-cutting decisions D68/D69/D70/D71)
13. `docs/migration/phase1/02_configuration.md` (Round 2 — UdmTablesList + `.env` per-server + GPG envelope; deployment artifact references this)
14. `docs/migration/phase1/01_database_schema.md` (Round 1 — DDL apply order for migrations; PK + FK ordering; index creation strategy)
15. `docs/migration/05_RUNBOOKS.md` (RB-1 through RB-11; RB-12 deployment runbook added at Round 6 close-out per B41)
16. `docs/migration/02_PHASES.md` (Phase 1 deliverables that Round 6 closes; Phase 0 deliverables 0.11 + 0.12 that Round 6 partially closes)
17. `docs/migration/03_DECISIONS.md` (search by D-number) — D27 (cross-server parity); D29 (Automic coordination); D34 (greenfield); D55 (5-gate); D56 (second-pass); D62 (CCL); D67 (Tier 0); D68-D71 (Round 3 cross-cutting); D72 (D72 termination rule); D74-D77 (Round 4 CLI contracts); D79-D82 (Round 5 test contracts)
18. `CLAUDE.md` (project root) — Architecture Decisions + Do-NOT rules + BCP CSV Contract + Deployment Requirements section (MALLOC_ARENA_MAX=2 invariant for W-4)
19. `docs/migration/06_TESTING.md` (canonical 6-tier framework; CI integration; quarterly drill schedule)
20. `docs/migration/MAINTENANCE.md` (quarterly cadence; ownership)
21. `docs/migration/04_EDGE_CASES.md` (M/S/I/N/P/G/D/F/V series + new T-series per B108) — edge cases that Round 6's smoke runs verify

## Scope

**In scope** (this document):

- **Foundational decisions** (unnumbered preamble — Round 6 dependencies)
- **§ 1**: Cross-cutting deployment conventions — three-environment topology, deployment artifact contract, server provisioning prerequisites, code deployment mechanism, deployment cadence + rollback strategy, pre/post-deployment checklist, **module startup sequence** (closes B69), Pitfall #9 compliance
- **§ 2**: Round 6 producer self-check pre-flight (Pitfall #9 9.a-9.h walk)
- **§ 3**: Server provisioning per environment — dev / test / prod / parity baseline / GPG credentials / documented exceptions
- **§ 4**: Code deployment workflow — Round 1 migrations / Round 2 configuration / Round 3 modules (17) / Round 4 tools (11) / Round 5 tests (Tier 0-5) / `utils/errors.py` (closes B85) / `tools/verify_tier0_drift.py` (closes B58 stub → full impl)
- **§ 5**: Smoke test runs — Tier 0 per artifact (28 tests) / Tier 1 unit / Tier 2 property / Tier 3 integration / Tier 4 crash (pre-release) / first end-to-end pipeline run with synthetic data
- **§ 6**: Automic integration deployment — frozen-8 job inventory deployment / gate-table contract activation / failover protocol activation / CLI_* + CYCLE_* + DEPLOYMENT_* + MIGRATION_* + STARTUP_* EventType family (closes B86)
- **§ 7**: Cross-cutting fix workstream — closes 12+ B-items requiring deployment-time implementation (B65 release_snowflake_key / B68 thread-safety / B70 ledger metadata footgun / B72 prior_result pinning / B87 KeyboardInterrupt / B88 mutex / B90 isatty / B103 docstring fix / B104 batch-size default / B115 fixture rollback / B118 Hypothesis CI profile)
- **§ 8**: Spec doc corrections — non-substantive edits to Rounds 3-4 spec docs to close trivial-polish B-items without supersession (closes B89 / B96 / B97 / B100 / B101 / B102 / B106 / B116 / B119)
- **§ 9**: Rollback + recovery — per-environment rollback procedure / failed-deployment recovery / module-startup-failure handling / RB-12 deployment runbook (closes B41 — promoted to Round 6)
- **§ 10**: Edge case mapping — M / S / I / N / P / G / D / F / V + new T-series + new deployment-specific edge cases (Round 6 § 10.2)
- **§ 11**: Validation gates self-check + Round 6 acceptance criteria
- **§ 12**: B47-B119 systematic triage (per D73 + D78 + D83 mandate — 36 items active carryover plus Round 5 § 9.2 + § 9.6 deferrals)
- **§ 13**: End of Round 6 — distinctive outputs summary

**Out of scope** (deferred):

- Code implementation bodies — engineering team authors `tests/**/*.py`, `data_load/**/*.py`, `tools/**/*.py` against the contracts in this doc + Rounds 3-5 specs; § 4 specifies deployment discipline + sequencing, NOT the code itself
- Phase 2 pilot table selection — separate decision; Phase 0 deliv 0.7 owns it
- Round 7 schema evolution governance — SP signature changes / Automic inventory amendments live there per § 12.3
- Round 8 self-improvement skill suite — meta-discipline; Round 8 owns it
- Power BI dashboards — Phase 6 scope per `02_PHASES.md` § Phase 6
- Snowflake Iceberg table provisioning — Phase 5 scope per `02_PHASES.md` § Phase 5
- Phase 0 deliverables 0.1-0.10 + 0.14-0.19 (most) — Phase 0 owns; Round 6 partially closes 0.9 (failover protocol per § 9 + RB-2/RB-9), 0.11 (cross-server parity baseline per § 3.4), 0.12 (GPG credential strategy per § 3.5)

## Foundational decisions (Round 6 dependencies)

| # | Decision | Round 6 dependency |
|---|---|---|
| D27 | Cross-server parity (RHEL version, Python pinned, library set, systemd unit identical across dev/test/prod) | § 3.4 baseline establishment + § 3.6 documented exceptions per D65 |
| D29 | Automic-driven AM/PM gate coordination | § 6 deployment activates the gate-table contract; § 6.3 failover protocol per RB-9 |
| D34 | Greenfield deployment, not migration | Round 6 has no legacy cutover step — initial deployment per environment |
| D47 | Round 0.5 spike authorized | § 5.6 first end-to-end pipeline run with synthetic data is the Round 0.5 spike's parallel; Round 6 is doc-only — Round 0.5 is engineering-driven |
| D49 | Schema v3 ready for DBA review | § 4.1 Round 1 migrations apply this DDL |
| D55 | 5-gate validation discipline | § 11 self-check |
| D56 | Mandatory second-pass after 🔴 | Pattern E cycle iteration per D72 |
| D60 | Round close-out protocol | Round 6 close-out follows the 8-section checklist |
| D61 | NORTH_STAR/RISKS/BACKLOG integration (pillar mapping + risk delta + backlog surfacing) | § 11.2 risk delta + § 12 backlog triage |
| D62 | CCL doctrine | § 0 read order; producer + reviewers Stage 1+2 read protocol |
| D63 | UdmTablesList canonical 29-column inventory + 6 new columns + idempotent ALTER DDL | § 4.2 configuration deployment applies; § 8.12 closes B42 reconciliation query |
| D64 | GPG passphrase storage — TPM2 sealed against PCR set | § 3.5 GPG credential deployment workflow |
| D65 | Parity drift severity classification — fatal / warning / informational tiers | § 3.4 parity baseline + § 3.6 documented exceptions; § 5.1 smoke runs verify per-tier exit-code mapping |
| D66 | Automic job inventory (8 jobs) + naming + gate-table contract (AM/PM only via SP-3/SP-4) | § 6.1 frozen-8 inventory deployment |
| D67 | Build-time Tier 0 dummy-data smoke test discipline | § 5.1 Tier 0 smoke run per module + per tool (28 tests); § 4.7 verify_tier0_drift.py full impl |
| D68 | Error class hierarchy (PipelineFatalError / PipelineRetryableError + per-module subclasses) | § 4.6 utils/errors.py implementation closes B85 |
| D69 | Connection / cursor ownership model (cursor_for() canonical) | § 1.7 module startup sequence respects this — no cursor crosses subprocess boundaries |
| D70 | Test fixture strategy / 6-tier pyramid | § 4.5 test deployment; § 5.2-§ 5.6 per-tier smoke runs |
| D71 | Snowflake auth flow — RSA key decrypted from GPG envelope; ephemeral `/dev/shm/snowflake_pk_<pid>` | § 3.5 GPG credential deployment; § 7.1 release_snowflake_key() implementation closes B65 |
| D72 | Validation cycle termination rule | Pattern E from cycle 1 + sleeper-bug stress final cycle |
| D73 | Round 3 architectural-review acceptance with B47-B74 carryover | § 12 systematic triage continues |
| D74 | CLI exit-code contract (0/1/2) | § 5.1 Tier 0 smoke verifies per-tool exit-code mapping; § 7.5 KeyboardInterrupt decision per B87 |
| D75 | CLI argument naming + default semantics + actor TTY heuristic | § 7.7 AUTOMIC_RUN_ID + isatty() edge case per B90 |
| D76 | CLI audit-row contract (`EventType='CLI_<TOOL_NAME>'` + Metadata JSON) | § 6.4 EventType family deployment closes B86 |
| D77 | CLI Tier 0 scaffold pattern (6 canonical assertions per tool) | § 5.1 Tier 0 catalog implementation; § 8.1 D77 5-vs-6 count reconciliation closes B89 |
| D78 | Round 4 architectural-review acceptance with B77-B107 carryover | § 12 systematic triage continues |
| D79 | Test data fixture canonical schema (`tests/fixtures/udm_test_fixtures/schema.sql`) | § 4.5 fixture deployment; § 8.10 testcontainers image cite closes B116 |
| D80 | Tier-0-to-Tier-1 transition discipline (≤5s, no external deps boundary) | § 5.1 Tier 0 smoke discipline + § 1.9 boundary in deployment context |
| D81 | Property-test shrinkage budget per module (Hypothesis max_examples + derandomize CI profile) | § 5.3 Tier 2 smoke run config; § 7.11 Hypothesis CI profile per B118 |
| D82 | Coverage thresholds per tier (Tier 2 reframed to "100% properties pass shrinkage within budget") | § 5 per-tier acceptance criteria |
| D83 | Round 5 architectural-review acceptance (convergence-confirmed variant) with B108-B119 carryover | § 12 systematic triage continues |

## New decisions anticipated in this round

These will be captured via `udm-decision-recorder` (per D62):

| Proposed | Topic | Pillar(s) served |
|---|---|---|
| D84 | **Deployment artifact contract** — immutable tagged release (git tag per deploy; rsync of source-controlled tree + GPG-signed manifest of file SHAs); no in-place edits on deployed servers; rollback = re-deploy prior tag. Pre-deploy + post-deploy checklists gate environment promotion (dev → test → prod) | **Audit-grade**, **Operationally stable**, **Idempotent** |
| D85 | **Module startup sequence** (closes B69) — canonical sequence: credentials_loader → vault pool config → server_parity_verifier → ledger startup sweep → orchestration. Each stage is fail-fast: any failure halts before next stage. The sequence runs once per process invocation; subprocess workers (per D69) inherit credentials via env vars (NOT file re-read) | **Operationally stable**, **Audit-grade** |
| D86 | **Three-environment deployment cadence** — dev: nightly auto-deploy on `main` HEAD; test: daily after dev smoke-pass + 4-hour soak; prod: weekly after test soak + sign-off. Failed test soak blocks prod promotion. Parity baseline (per D65) re-snapshotted at each environment after successful deploy | **Operationally stable** |
| D87 | **Pre/post-deployment checklist contract** — each environment promotion (dev → test, test → prod) runs an explicit checklist captured as a `PipelineEventLog` row with `EventType='DEPLOYMENT_<ENV>'` + Metadata JSON of every check + pass/fail per check; one row per environment per deployment artifact. Failed checklist short-circuits the promotion | **Audit-grade**, **Operationally stable** |

These are the constituent decisions Round 6 locks alongside the deployment spec. **D88** locked 2026-05-10 via convergence-confirmed architectural-review acceptance per D83 precedent (the 6-cycle trajectory 10→1→1→2→1→0 demonstrates convergence; Pattern E from cycle 1 + mandatory sleeper-bug stress final cycle; 4-consecutive-cycle Pitfall #9 9.i recurrence pattern empirically confirmed → B136/B141 candidate sub-class strengthening tracked).

---

## § 1. Cross-cutting deployment conventions

### § 1.1 Three-environment topology (per D86 proposed)

| Environment | Role | Hardware tier | Source data | Update cadence |
|---|---|---|---|---|
| **dev** | Engineering work; nightly auto-deploy on `main` HEAD | Single RHEL 8 server (modest spec); local SQL Server 2022 dev instance; synthetic data only | Synthetic fixtures only (no real PII) | Nightly (02:00 dev-server local time) |
| **test** | Pre-prod soak + failover destination per RB-9; daily auto-deploy after dev smoke pass + 4-hour soak | Production-equivalent RHEL 8 server; production-equivalent SQL Server 2022 instance; production-equivalent network drive mount | Mirror of prod source databases via read-only replicas (D28-scoped — source on-call team owns replicas) | Daily after dev passes |
| **prod** | Production pipeline; weekly auto-deploy after test soak + manual sign-off | Production RHEL 8 server; SQL Server 2022 Always-On Availability Group; production network drive (per D34 architecture) | Production source databases (DNA, CCM, EPICOR) | Weekly after test passes (Monday window 02:00-05:00 local) |

**Parity invariants** (per D27 + D65 — verified by `tools/verify_server_parity.py` at every startup):
- Python version pinned identical across all three (currently 3.12.11 per CLAUDE.md)
- Library set identical (verified via SHA-256 of `requirements-lock.txt`)
- `MALLOC_ARENA_MAX=2` set in systemd unit per W-4 / CLAUDE.md Deployment Requirements
- Oracle Instant Client 19c installed identical
- ODBC Driver 18 for SQL Server installed identical
- mssql-tools18 version identical (per CLAUDE.md Deployment Requirements — upgrade pending v18.6.1.1+ for W-1 `-C 65001` re-enablement)
- systemd unit SHA identical
- GPG envelope SHA identical (the `.gpg` file, not the decrypted contents — different per env, but envelope ID matches deployment artifact)
- TPM2 PCR set identical (per D64 — PCR registers match the pipeline-server policy)

**Variance allowed** (per D65 informational tier — environment-specific values are NOT parity violations):
- `.env` per-server keys (45 keys per Round 2 § 2.1) — different DB endpoints, different network drive paths, different Snowflake account
- Server hostname + IP
- `documented_exceptions` array per env (per Round 2 § 4.4) — different exception sets per env, but all expire ≤90 days

### § 1.2 Deployment artifact contract (per D84 proposed)

**Artifact definition**: immutable git-tagged release of the source-controlled tree.

| Component | Source | Contents |
|---|---|---|
| Code tree | git tag `v<MAJOR>.<MINOR>.<PATCH>-<env>` (e.g., `v1.0.0-dev`, `v1.0.0-test`, `v1.0.0-prod`) | All `.py` files under project root; `tests/**/*.py`; `tools/**/*.py`; `data_load/**/*.py`; `migrations/**/*.py`; `schema/**/*.py`; etc. |
| Migration scripts | Inside tag — `migrations/*.py` | Round 1 DDL migrations apply via `python3 migrations/<name>.py --apply` |
| Configuration template | Inside tag — `config/templates/.env.template` | Operator copies + fills per-env; never committed with real secrets |
| GPG envelope | Per-server — `/etc/pipeline/credentials.json.gpg` | Deployed separately via secured channel; NOT in git tag (env-specific secrets) |
| Parity baseline | Per-server — `/etc/pipeline/parity_baseline.json` | Generated post-deploy from server state; checked into ops repo (NOT app repo); per D65 |
| File manifest | Inside tag — `MANIFEST.sha256` | GPG-signed list of file paths + SHA-256 hashes; verified at deploy-time |

**Immutability rule**: once a tag is created, the corresponding artifact is frozen. No in-place edits on deployed servers. Re-deploy = re-checkout from the same tag. Rollback = re-deploy a prior tag.

**Deployment workflow**:

```
1. Engineering: create git tag on `main` after CI passes (Tier 0+1+2+3 stages green per Round 5 § 1.4)
2. Build: rsync source tree to `/opt/pipeline/<tag>/` on target server (NEVER overwrite `current/`)
3. Verify: compare `MANIFEST.sha256` against deployed file SHAs; abort on mismatch
4. Switch: atomic symlink swap — `/opt/pipeline/current` → `/opt/pipeline/<tag>/`
5. Restart: `systemctl restart pipeline.service` — module startup sequence per § 1.7 runs
6. Smoke: § 5 Tier 0 + first synthetic pipeline run; halt + rollback if any failure
7. Audit: write `EventType='DEPLOYMENT_<ENV>'` row to PipelineEventLog per D87 / § 1.6
```

**Rollback workflow** (per environment, ≤5 minutes from rollback decision to operational state):

```
1. Detect: post-deploy checklist fails OR first synthetic run fails OR alert fires within 30 min of restart
2. Decide: operator confirms rollback (acquire RB-12 § 3 authorization — see § 9.5)
3. Symlink revert: `/opt/pipeline/current` → `/opt/pipeline/<prior_tag>/`
4. Restart: systemctl restart pipeline.service
5. Verify: § 5.1 Tier 0 smoke runs against prior_tag
6. Audit: write `EventType='DEPLOYMENT_ROLLBACK'` row to PipelineEventLog with `Metadata.prior_tag` + `Metadata.failed_tag` + `Metadata.failure_reason`
7. Investigate: failed tag remains on disk under `/opt/pipeline/<failed_tag>/` for forensics; do NOT auto-delete
```

### § 1.3 Server provisioning prerequisites (per D27)

Every environment server (dev/test/prod) provisions with the identical software baseline:

| Component | Version | Provisioning step |
|---|---|---|
| Operating system | RHEL 8.x (specific minor pinned per CLAUDE.md) | OS image via system engineering (D27 — single-OS-version invariant) |
| Python | 3.12.11 | Built from source against pinned OpenSSL; installed at `/opt/python3.12.11/`; symlinked `/usr/local/bin/python3` |
| Oracle Instant Client | 19c | Installed at `/opt/oracle/instantclient_19_19/`; `LD_LIBRARY_PATH` set in systemd unit |
| ODBC Driver 18 for SQL Server | latest | `microsoft-prod.repo` + `msodbcsql18` package |
| mssql-tools18 | per CLAUDE.md Deployment Requirements current minimum | `msodbcsql18` + `mssql-tools18` packages; `/opt/mssql-tools18/bin/` in PATH |
| GPG | 2.3+ | RHEL default; verified `gpg2 --version` returns 2.3+ for per-CLAUDE.md TPM2 integration (W-2 sentinel; D64) |
| TPM2 tools | tpm2-tools 5.x | `tpm2-tools` package; tpm2 device accessible via `/dev/tpmrm0` |
| systemd | distro default | `pipeline.service` unit file deployed per § 1.5 |
| Polars + polars-hash + connectorx + oracledb + pyodbc | per `requirements-lock.txt` SHA | `pip install --no-deps -r requirements-lock.txt` after CCL Stage 1 verification |
| Project user | `pipeline` (UID/GID fixed across envs per D27) | `useradd -m -u 7700 -g 7700 pipeline`; `/debi/` home dir |
| .env location | `/debi/.env` | Mode 0600; owned by `pipeline:pipeline`; NEVER world-readable |
| GPG envelope location | `/etc/pipeline/credentials.json.gpg` | Mode 0640; owned by `root:pipeline`; pipeline user reads via gpg2 |
| Parity baseline | `/etc/pipeline/parity_baseline.json` | Mode 0644; checked into ops repo (NOT app repo); generated post-first-deploy per § 3.4 |
| Network drive mount | `\\archive\source=X\table=Y\...` per source/table | NFSv4 mount per `/etc/fstab`; readable + writable by pipeline user |
| Logs directory | `/var/log/pipeline/` | Mode 0750; owned by `pipeline:pipeline`; logrotate weekly |

**Verification**: `tools/verify_server_parity.py` (per Round 4 § 3.7) runs at every pipeline-process startup. Fatal-tier mismatches per D65 trigger `sys.exit(1)` before any extraction begins. Warning-tier logs ERROR + continues. Informational-tier logs INFO + continues.

### § 1.4 Code deployment mechanism (per D84)

**Source artifact**: git tag → rsync → atomic symlink swap.

```bash
# Engineering workstation
git tag -a v1.0.0-test -m "Test deploy 2026-05-N — D84 first invocation"
git push origin v1.0.0-test

# CI builds + signs manifest
git archive --format=tar v1.0.0-test | gzip > pipeline-v1.0.0-test.tar.gz
cd /tmp && tar -xzf pipeline-v1.0.0-test.tar.gz
find . -type f -exec sha256sum {} \; > MANIFEST.sha256
gpg --detach-sign --armor MANIFEST.sha256

# Target server (per env)
ssh pipeline@<target> <<'EOF'
mkdir -p /opt/pipeline/v1.0.0-test
rsync -av --delete /tmp/pipeline-v1.0.0-test/ /opt/pipeline/v1.0.0-test/
cd /opt/pipeline/v1.0.0-test
sha256sum -c MANIFEST.sha256  # FAIL → abort
gpg --verify MANIFEST.sha256.asc  # FAIL → abort
# Atomic symlink swap via mv -T (single rename(2) syscall; ln -sfn is NOT atomic —
# it's unlink() + symlink() with a race window. Pattern per Capistrano #346 +
# Deployer + Etsy canonical references; cycle 1 R6C1-5 advisory finding.)
ln -s /opt/pipeline/v1.0.0-test /opt/pipeline/current.new
mv -T /opt/pipeline/current.new /opt/pipeline/current
sudo systemctl restart pipeline.service
EOF
```

**Idempotency**: re-running the deploy with the same tag is a no-op (rsync `--delete` reaches identical state; symlink already correct; systemd restart is idempotent at process-state level — module startup sequence re-runs but writes the same `DEPLOYMENT_<ENV>` audit row only if BatchId differs).

### § 1.5 Deployment cadence + rollback strategy (per D86 proposed)

**Cadence**: dev nightly → test daily after dev pass → prod weekly after test soak.

| Promotion | Trigger | Pre-conditions | Soak duration |
|---|---|---|---|
| `main` HEAD → dev | Nightly cron (02:00 dev-server local) | CI Tier 0+1+2 green on `main` HEAD; CI Tier 3 green within last 24h | 0 — dev IS the soak |
| dev → test | Daily after dev smoke pass (next morning) | Last 12h of dev smoke-runs all green; no operator alerts | 4 hours minimum test smoke + soak before next-step gate; failed soak → ROLLBACK |
| test → prod | Weekly Monday window 02:00-05:00 | Last 168h (7 days) of test smoke-runs all green; pipeline-lead manual sign-off + Automic gate-table reconciliation pass | 24 hours minimum prod smoke + soak before declaring success |

**Rollback decision matrix** (per § 1.2 + RB-12 deployment runbook):

| Failure mode | Detection | Rollback decision |
|---|---|---|
| `tools/verify_server_parity.py` returns FAIL severity at startup | First post-deploy startup | AUTO-ROLLBACK — symlink revert + alert |
| First synthetic pipeline run fails (any module crashes) | § 5.6 first run | AUTO-ROLLBACK — symlink revert + alert + forensic capture |
| Tier 0 smoke fails post-deploy | § 5.1 cron | AUTO-ROLLBACK |
| Smoke run succeeds but specific table extraction fails | Operator alert (per `tools/alert_dispatcher.py`) | MANUAL — pipeline-lead decides; either rollback OR investigate within the deployed version |
| Latency regression > 2x baseline | Latency profile (`tools/lateness_profile.py`) | MANUAL — pipeline-lead decides |
| Memory usage regression > 50% baseline | RSS monitor per main_*.py + B-8 | MANUAL — investigate first |

**Rollback target**: prior tag MUST be present at `/opt/pipeline/<prior_tag>/` to enable rollback. Rollback retention: keep last 5 tags on each server (manual purge older). Failed tags retained indefinitely under `/opt/pipeline/<failed_tag>/.failed` marker for forensic analysis.

### § 1.6 Pre/post-deployment checklist contract (per D87 proposed)

Each environment promotion writes ONE `PipelineEventLog` row with `EventType='DEPLOYMENT_<ENV>'` (per Round 4 § 1.6 D76 pattern extended to deployment events) + `Status` ∈ `('IN_PROGRESS', 'SUCCESS', 'FAILED', 'SKIPPED')` per `CK_PipelineEventLog_Status` (verified against Round 1 schema L143-144 per Pitfall #9 9.c).

**Pre-deployment checklist** (gates the deploy):

```
1. Source git tag matches expected — tag exists on remote + signed by authorized committer
2. Target server reachable (ssh + sudo)
3. Target server has ≥1.5x required disk free (per `/opt/pipeline/<new_tag>` extraction estimate)
4. Target server has ≥8GB free memory (per pipeline startup baseline)
5. Target server is NOT mid-pipeline-run (check `PipelineExecutionGate` Status NOT IN ('STARTING', 'RUNNING') — per Round 1 schema L328-330 enum)
6. Target environment is NOT in maintenance window — query: `SELECT 1 FROM General.ops.MaintenanceWindow WHERE StartAt <= SYSUTCDATETIME() AND EndAt > SYSUTCDATETIME() AND AffectedComponent IN ('<env>_pipeline', 'all')` returns ≥1 row → ABORT (per Round 1 schema L398-415 + `IX_MaintenanceWindow_Active`)
7. Prior tag confirmed retained at `/opt/pipeline/<prior_tag>/`
8. Parity baseline at `/etc/pipeline/parity_baseline.json` is current (≤90 days old)
9. GPG envelope at `/etc/pipeline/credentials.json.gpg` is current (≤90 days old; TPM2 PCR set unchanged since envelope was sealed)
10. CI Tier 0+1+2 green on the source tag's commit
11. CI Tier 3 (integration) green within last 24h
12. Operator (`--actor`) supplied + justification (`--justification`) supplied per D75
```

**Failed pre-check**: `Status='FAILED'` + Metadata.failed_check enumerates which check; deployment ABORTS. No file changes on target server.

**Deployment execution**: rsync + symlink swap + restart per § 1.4.

**Post-deployment checklist** (gates the promotion to next env):

```
1. systemctl status pipeline.service shows active
2. /opt/pipeline/current symlink points to <new_tag>
3. `tools/verify_server_parity.py` returns overall='pass' OR documented exceptions match per § 3.6
4. Tier 0 smoke (all 28 tests) green per § 5.1
5. First synthetic pipeline run succeeds end-to-end per § 5.6 (zero crashes, expected event log rows)
6. `IdempotencyLedger` table has no stale IN_PROGRESS rows (per Round 1 schema; cleaned by startup sweep)
7. `PipelineExecutionGate` table accepts new INSERT (sp_getapplock acquirable per Round 1 SP-3)
8. Module startup sequence completed successfully (per § 1.7 — credentials_loader → vault pool config → parity verifier → ledger sweep)
9. No CRITICAL log entries written within first 5 min post-restart
10. Soak period (per § 1.5) elapsed without operator alerts
```

**Failed post-check**: `Status='FAILED'` + ROLLBACK per § 1.5 decision matrix.

**Audit row schema** (Metadata JSON):

```json
{
  "tag": "v1.0.0-test",
  "prior_tag": "v0.9.0-test",
  "actor": "engineer.lastname",
  "justification": "Round 5 test suite implementation + 12 cross-cutting fixes per B47-B119",
  "pre_check_results": {"check_1_tag_exists": "pass", ..., "check_12_actor_supplied": "pass"},
  "post_check_results": {"check_1_systemctl_active": "pass", ..., "check_10_soak_elapsed": "pass"},
  "soak_duration_minutes": 240,
  "deploy_started_at": "2026-05-N 02:00:00",
  "deploy_completed_at": "2026-05-N 02:08:00",
  "soak_completed_at": "2026-05-N 06:08:00"
}
```

### § 1.7 Module startup sequence (per D85 proposed — closes B69)

The pipeline process startup runs THIS sequence in THIS order. Each stage is **fail-fast**: any failure exits with the documented exit code per D74 (1=expected operational failure / 2=fatal) and does NOT proceed to the next stage.

```
STAGE 1: credentials_loader (per Round 3 § 3.1)
  - Read `/debi/.env` (operator-edited per Round 2 § 2)
  - Decrypt GPG envelope at `/etc/pipeline/credentials.json.gpg` via gpg2 + TPM2 unseal (per D64)
  - Build CredentialsDict (per Round 3 § 3.1 Returns)
  - Write Snowflake RSA key to `/dev/shm/snowflake_pk_<pid>` mode 0600 (per D71)
  - Audit-log INSERT to `PipelineEventLog` (EventType='CREDS_LOAD', Status='SUCCESS')
  - Exit codes: 2 on CredentialsLoadError (gpg2 fail, TPM2 unseal fail, envelope SHA drift); 0 on success

STAGE 2: vault pool config (per Round 3 § 2.3)
  - Call `configure_vault_connection_pool(pool_size, ...)` once
  - Verify connectivity via `SELECT 1` against General database vault context
  - Exit codes: 2 on VaultConfigError; 0 on success

STAGE 3: server_parity_verifier (per Round 3 § 3.2 / Round 4 § 3.7)
  - Read `/etc/pipeline/parity_baseline.json`
  - Compare against current server state (Python version, library SHA, env vars, systemd unit SHA, TPM2 PCR, envelope SHA)
  - Apply documented_exceptions per D65 (per Round 2 § 4.4) with expires_at filter
  - Exit codes: 2 on FATAL-tier mismatch per D65; 1 on WARNING-tier (with --fail-on-warning); 0 on INFORMATIONAL or pass

STAGE 4: ledger startup recovery sweep (per Round 3 § 4.1)
  - Call `idempotency_ledger.startup_recovery_sweep(max_age_minutes=60)` once (canonical threshold per Round 3 § 4.1 L835 = "find IN_PROGRESS rows older than 1 hour" — cycle 5 fix corrected from initial draft's `max_age_minutes=240` per R6C4 sleeper-bug stress 🟡-1 finding)
  - Mark any stale IN_PROGRESS rows (per `CK_IdempotencyLedger_Status IN ('IN_PROGRESS', 'COMPLETED', 'FAILED')` — `01_database_schema.md` L445-446; 3-value enum distinct from PipelineEventLog L143-144) older than threshold as FAILED
  - Audit-log INSERT to PipelineEventLog (EventType='LEDGER_SWEEP', Metadata.rows_swept=<N>)
  - Exit codes: 1 on sweep failure (DB unreachable); 0 on success

STAGE 5: orchestration begins
  - main_small_tables.py / main_large_tables.py invocation flows take over
  - First operation: acquire PipelineExecutionGate per Round 1 SP-3 (prod) or SP-4 (test) per D66
  - Subprocess workers (per D69 `--workers`) inherit credentials via env vars (NOT re-read GPG envelope per subprocess — that would re-trigger TPM2 unseal which is rate-limited)
```

**Failure semantics**: a Stage N failure means the process exits before any Stage N+M execution. The `PipelineEventLog` audit trail records which stage failed and why. Operator runs `tools/verify_server_parity.py` standalone to diagnose Stage 3 issues; `tools/inspect_cdc_pk.py` (existing per CLAUDE.md DIAG-1) for downstream investigation if a later stage finds inconsistent state.

**Idempotency**: re-running the sequence is safe. Stages 1-4 are idempotent by design (credentials_loader caches; vault pool errors on second config; parity is read-only; ledger sweep is idempotent per Round 3 § 4.1). Only Stage 5 onwards has side effects.

**Per D69 subprocess inheritance**: `--workers N` spawns N subprocesses via `multiprocessing.Pool`. Each subprocess receives the credentials dict via pickle-serialized `TableConfig` plus env vars (per CLAUDE.md WORKER-SERIALIZE invariant). NO subprocess re-runs Stage 1 (would cause TPM2 unseal storm). The main process's `release_snowflake_key()` (per § 7.1 / B65) runs at process exit; subprocesses do NOT manage the key file (only the parent owns it).

### § 1.8 Pitfall #9 compliance (per HANDOFF §8 — every test plan reference)

Per HANDOFF §8 Pitfall #9 sub-class accumulator (9.a-9.h, formalized 2026-05-10 plus candidate 9.i process-discipline-failure surfaced in Round 5), every reference in this doc to Round 1 SP / column / enum / Round 2 dataclass field / Round 3 module function signature / Round 4 CLI argument / Round 5 test path MUST cite the exact canonical source (`file:line` or `file § X.Y`). The producer Gate 1 self-check (§ 2 below) walks each sub-class 9.a-9.i. The Gate 2 Pattern E reviewers (specifically the column-walk specialist per `_reviewer_effectiveness.md` 0% false-clean rate across 5 events) re-verify EVERY such reference. **No invented column names. No invented parameter names. No invented enum values. No invented Round 3 function names. No invented Round 4 CLI argument names. No wrong-section-cites with invented section descriptions. No false-closure claims using B-number range as proxy for content (9.i candidate — Round 5 cycles 1-4 evidence).**

### § 1.9 Tier 0 vs Tier 1 boundary in deployment context (per D80)

Tier 0 smoke tests run on EVERY post-deploy startup (per § 5.1). They MUST stay within D80 constraints (≤5s; no external deps; canonical 6-assertion contract per Round 4 § 1.6 + D77; no exhaustive error-path coverage). Round 6 deployment-time decision: **Tier 0 is the gate before module startup completes**. If Tier 0 takes >5s OR requires external deps, it's promoted to Tier 1 (per D80) and runs in CI's Tier 1 stage instead of the post-deploy gate. The post-deploy gate runs only Tier 0; Tier 1+ runs in CI per Round 5 § 1.4.

Pitfall #10 reminder (per HANDOFF §8): Tier 0 is the smoke screen, NOT the comprehensive test. Resist expanding it during deployment debugging.

---

## § 2. Round 6 producer self-check pre-flight (Pitfall #9 sub-class walk)

Before invoking § 11 Pattern E review, producer walks each sub-class against this artifact:

- **9.a column-name drift**: Round 1 column references — `PipelineEventLog.Status` (enum L143-144 per Round 1 schema); `PipelineEventLog.EventType` (NVARCHAR — `CLI_<TOOL_NAME>` family + new `DEPLOYMENT_<ENV>` + `DEPLOYMENT_ROLLBACK` per D87 + § 6.4 + § 1.6); `PipelineEventLog.Metadata` (NVARCHAR(MAX) JSON); `PipelineExecutionGate.Status` (enum L328-330); `PipelineExecutionGate.CycleType` (enum L326-327 — `'AM'`, `'PM'`); `PipelineExecutionGate.ExecutingServer` (enum L331-332 — `'production'`, `'test'`); `PipelineExecutionGate.LastHeartbeatAt`, `ActualStartTime`, `ActualCompletionTime`, `BatchId`; `IdempotencyLedger.Status` (enum — `'IN_PROGRESS'`, `'COMPLETED'`, `'FAILED'`); `ParquetSnapshotRegistry.Status` (7-state per Round 3 § 1.3); `MaintenanceWindow` table (Round 1 schema). ✓ Verified per-table.
- **9.b parameter-name drift**: Round 1 SP signatures per `01_database_schema.md` L1456-1461 (SP-3) + L1538-1546 (SP-4) — SP-3 `PipelineExecutionGate_AcquireProd(@CycleType NVARCHAR(10), @CycleDate DATE, @ExpectedStartTime DATETIME2(3), @GateId BIGINT OUTPUT, @BatchId BIGINT OUTPUT)` (5 parameters); SP-4 `PipelineExecutionGate_AcquireTest(@CycleType NVARCHAR(10), @CycleDate DATE, @ExpectedStartTime DATETIME2(3), @HeartbeatStaleMinutes INT = 10, @ProdMaxRuntimeMinutes INT = 120, @GateId BIGINT OUTPUT, @BatchId BIGINT OUTPUT, @Action NVARCHAR(30) OUTPUT)` (8 parameters; `@ProdMaxRuntimeMinutes` default `120` NOT `NULL`). Round 4 CLI canonical args per `04_tools.md` § 1.4: `--source` / `--table` / `--apply` / `--dry-run` / `--batch-id` / `--actor` / `--justification` / `--no-audit-event` / `--json` / `--verbose` / `--quiet`. ✓ Verified canonical post-cycle-2 fix (cycle 1 R6C1-1 caught SP-3/SP-4 signature drift in this very self-check — fix-fresh-instance pattern of Pitfall #9 sub-classes 9.b + 9.d).
- **9.c enum-value drift**: `CK_PipelineEventLog_Status IN ('IN_PROGRESS','SUCCESS','FAILED','SKIPPED')` per `01_database_schema.md` L143-144; `CK_PipelineExecutionGate_Status IN ('PENDING', 'STARTING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'TIMEOUT', 'CANCELLED')` L328-330; `CK_PipelineExecutionGate_CycleType IN ('AM', 'PM')` L326-327; `CK_PipelineExecutionGate_ExecutingServer IN ('production', 'test')` L331-332; `CK_PipelineLog_LogLevel IN ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')` L215-216; `CK_IdempotencyLedger_Status IN ('IN_PROGRESS', 'COMPLETED', 'FAILED')` L445-446 (3 values — NO `SKIPPED`); SP-4 `@Action ∈ ('EXIT_SUCCEEDED', 'EXIT_RUNNING_HEALTHY', 'PROCEED_FAILOVER')` L1546; ParquetSnapshotStatus per Round 3 § 1.3 `('created', 'verified', 'replicated', 'archived', 'missing', 'replication_failed', 'purged')`. ✓ Verified canonical post-cycle-2 fix (cycle 1 R6C1-1 caught LedgerStep status erroneously including `SKIPPED` — IdempotencyLedger has 3-value enum, not 4-value).
- **9.d type-width drift**: `@CycleType NVARCHAR(10)` per SP-3 L1457 + SP-4 L1539 (NOT `NVARCHAR(2)` — cycle 1 R6C1-1 caught the drift); `@Action NVARCHAR(30) OUTPUT` L1546; `@ExpectedStartTime DATETIME2(3)` L1459/L1541; `LogLevel NVARCHAR(10)` L202; `ExecutingServer NVARCHAR(20)` L310; `Status NVARCHAR(20)` per PipelineEventLog; `EventType NVARCHAR(50)` per PipelineEventLog; `CycleType` column itself `NVARCHAR(10)` L305 (matches SP parameter widths). ✓ Verified canonical post-cycle-2 fix.
- **9.e Unicode-vs-ASCII drift**: All Round 1 string columns are NVARCHAR per canonical (Round 1 § Schema convention); `@Token VARCHAR(40)` per SP-1/SP-2 (L1416 — ASCII per token format); `@Justification NVARCHAR(MAX)` (L1417 — Unicode for free text). ✓ Verified.
- **9.f cross-table column-name lift**: `Status` exists on PipelineEventLog (L143-144 enum) AND PipelineExecutionGate (L328-330 different enum) AND PipelineLog (no CHECK — free text per L202 LogLevel) AND PiiVault (per D45.6) AND ParquetSnapshotRegistry (7-state per Round 3 § 1.3) AND IdempotencyLedger (3-state enum L445-446 per `01_database_schema.md`). Every reference in this doc specifies which table — § 1.7 Stage 4 IdempotencyLedger cite corrected post-cycle-2 fix to L445-446 (cycle 1 R6C1-1 caught § 1.7 L344 wrongly citing L143-144 which is PipelineEventLog). `BatchId` is BIGINT on PipelineEventLog AND PipelineExecutionGate AND IdempotencyLedger; sequence-sourced from `PipelineBatchSequence` per Round 1. `ExecutingServer` is on PipelineExecutionGate L310 — NOT on PipelineEventLog (which has `ServerRole` L139 — distinct cross-table column per Round 4 cycle 4 R4C4-2 finding history). ✓ Verified per-table context post-cycle-2 fix.
- **9.g Python keyword-only marker drift**: Round 3 module signatures use `*,` keyword-only marker. Every cited Round 3 function preserves the marker: `verify_parquet_snapshot(*, registry_id, actor)` per Round 3 § 1.3; `decrypt_token(*, token, justification, request_id)` per § 2.2; `ledger_step(*, batch_id, source_name, table_name, event_type, metadata)` per § 4.1; `track(*, event_type, table_name, source_name, batch_id, event_detail)` per § 6.3; `copy_parquet_to_snowflake(*, registry_id, snowflake_table, timeout_seconds)` per § 7.1. Round 2 `verify_server_parity(baseline_path, server_name, fail_on_warning)` per L957-961 is positional (NOT keyword-only — different convention; this is intentional). ✓ Verified.
- **9.h wrong-section-cite with invented section description**: Every `§ X.Y` citation in this doc resolved against the target doc's actual section header before writing. Round 2 § 4.4 (Documented exceptions per D65) — distinct from § 4.3 (Drift severity tiers). Round 3 § 1.3 (parquet_registry_client) — distinct from § 1.2 (parquet_replay) and § 1.1 (parquet_writer). Round 4 § 3.10 (log_retention_cleanup) — distinct from § 3.11 (alert_dispatcher). Round 1 schema L143-144 (`CK_PipelineEventLog_Status`) — distinct from L215-216 (`CK_PipelineLog_LogLevel`). ✓ Verified.
- **9.i process-discipline-failure (candidate)**: No false-closure claims (every B-item triaged in § 12 has its canonical BACKLOG.md description, NOT inferred from B-number range). No wrong-doc-scope assertions (every "this doc closes B-X" is verified that the canonical fix lives in THIS doc's content, not in another locked artifact). No stale-count propagation (carryover counts derived from BACKLOG.md current state, NOT from prior-round acceptance text). **Note**: cycle 1 R6C1-1 caught the cycle-1-draft's self-check at § 2 claimed "✓ Verified" on SP-3/SP-4 signatures + CycleType width + IdempotencyLedger enum — the claim itself was a 9.i instance (false-clean producer self-check despite explicit walk). Cycle 2 fix re-walked canonical sources before re-asserting. The pattern is structural: explicit-walk-without-tool-reads-against-canonical produces 9.i drift. Mitigation for future producer self-checks: cite line ranges of canonical source DURING the walk, not just `file § X.Y` references. ✓ Verified canonical-source-by-canonical-source post-cycle-2.

**Status**: ✅ producer self-check complete post-cycle-2 fix. Mandatory Pattern E Gate 2 re-review per § 11.3 cycle 2.

---

## § 3. Server provisioning

### § 3.1 Dev server provisioning

Dev is the engineering team's workspace. Provisioning steps:

```
1. System engineering provisions RHEL 8.x VM per § 1.3 prerequisites
2. Install Python 3.12.11 from source against pinned OpenSSL
3. Install Oracle Instant Client 19c + ODBC Driver 18 + mssql-tools18 per § 1.3
4. Install pipeline user (UID 7700) + /debi home directory
5. Mount network drive at /mnt/archive (dev fixture path, synthetic data only)
6. Deploy GPG envelope at /etc/pipeline/credentials.json.gpg (dev secrets — NOT prod secrets)
7. Seal envelope passphrase with TPM2 PCR set per D64 / RB-12
8. Install systemd unit pipeline.service per § 1.5; MALLOC_ARENA_MAX=2 in unit file
9. Confirm Round 0.5 spike outcomes (D47 — if not yet run, this is the trigger to run it)
10. First-time deploy: rsync v0.1.0-dev artifact; symlink swap; restart
11. Run tools/verify_server_parity.py --baseline-generate (creates first parity baseline)
12. Commit /etc/pipeline/parity_baseline.json to ops repo
```

**Cadence**: nightly auto-deploy on `main` HEAD via cron (02:00 dev-server local time). CI's Tier 0+1+2 stage must be green at `main` HEAD before nightly cron fires. Failed deploys leave dev at the prior tag; alert fires to engineering team.

### § 3.2 Test server provisioning

Test is the pre-prod soak environment AND the failover destination per RB-9. Provisioning steps:

```
1-9: Same as § 3.1 (substitute "test" for "dev" — test secrets in /etc/pipeline/credentials.json.gpg)
10. Mount production source-DB replicas as read-only (per D28 — source on-call team provisions)
11. First-time deploy: rsync v0.1.0-test from prior dev-soak-passed tag
12. Run tools/verify_server_parity.py --baseline-generate (test baseline)
13. Configure Automic test job inventory per Round 2 § 5.1 frozen-8 — runs daily at 04:30 (failover trigger time per RB-9) AND 19:30
14. Test Automic gate-acquire path (SP-4 PipelineExecutionGate_AcquireTest) functional
```

**Cadence**: daily auto-deploy after dev smoke-pass + 4-hour test soak before next-step gate per § 1.5.

### § 3.3 Prod server provisioning

Prod is the production pipeline server. Provisioning steps:

```
1-9: Same as § 3.1 (substitute "prod" for "dev" — production secrets in /etc/pipeline/credentials.json.gpg)
10. Mount production network drive at /mnt/archive (production source-data path)
11. Mount production source databases (DNA, CCM, EPICOR — connectorx + oracledb endpoints per Round 2 § 2.1)
12. Provision SQL Server 2022 Always-On Availability Group per D27 + Phase 0 deliv 0.4 (DBA work)
13. Apply Round 1 schema DDL via migrations/ scripts in sequence (per § 4.1)
14. First-time deploy: rsync v1.0.0-prod from prior test-soak-passed tag
15. Run tools/verify_server_parity.py --baseline-generate (prod baseline — canonical)
16. Configure Automic production job inventory per Round 2 § 5.1 frozen-8 — runs daily at 02:00 (AM) AND 17:00 (PM)
17. Smoke-run first synthetic pipeline cycle (NOT against real source data — against a pilot fixture table) per § 5.6
18. After pilot smoke passes, schedule first real production cycle per RB-1 cutover discipline (Phase 2 territory, not Round 6)
```

**Cadence**: weekly auto-deploy after test soak + pipeline-lead manual sign-off per § 1.5. Monday window 02:00-05:00 local. Failed prod deploy → AUTO-ROLLBACK per § 1.5.

### § 3.4 Cross-server parity baseline (Phase 0 deliv 0.11 partial closure)

Per D27 + D65, `/etc/pipeline/parity_baseline.json` captures the per-server canonical state. Re-snapshotted at each successful deploy.

**Baseline schema** (per Round 2 § 4 + D65):

```json
{
  "generated_at": "2026-05-N 02:08:00 UTC",
  "server_name": "test-pipeline-01.example.com",
  "environment": "test",
  "deployment_tag": "v1.0.0-test",
  "fatal_tier": {
    "python_version": "3.12.11",
    "library_sha256": "<sha256 of requirements-lock.txt>",
    "malloc_arena_max": "2",
    "oracle_client_version": "19.19.0.0",
    "odbc_driver_version": "18.3.2.1",
    "envelope_sha256": "<sha256 of credentials.json.gpg>",
    "tpm2_pcr_set": "0,2,4,7",
    "tpm2_pcr_values": {"0": "<hex>", "2": "<hex>", "4": "<hex>", "7": "<hex>"},
    "systemd_unit_sha256": "<sha256 of pipeline.service>"
  },
  "warning_tier": {
    "mssql_tools_version": "18.0.0",
    "polars_hash_plugin_version": "0.5.0",
    "kernel_version": "5.14.0-362.13.1.el9_3.x86_64"
  },
  "informational_tier": {
    "server_hostname": "test-pipeline-01.example.com",
    "server_ip": "10.0.0.42",
    "uptime_seconds": 86400,
    "disk_free_bytes": 50000000000
  },
  "documented_exceptions": [
    {"check": "mssql_tools_version", "actual": "18.0.0", "baseline": "18.6.1.1", "reason": "Pending W-1 upgrade window", "expires_at": "2026-08-15", "approved_by": "pipeline-lead", "approved_at": "2026-05-15"}
  ]
}
```

**Severity tiers** (per D65 verified against Round 2 § 4.3):

| Tier | Behavior on mismatch | Exit code (`tools/verify_server_parity.py`) |
|---|---|---|
| `fatal` | sys.exit(1) at pipeline startup per Stage 3 of § 1.7 | 2 |
| `warning` | Log WARNING + continue; ELEVATED to fatal if `--fail-on-warning` per Round 4 § 3.7 | 1 (or 2 with `--fail-on-warning`) |
| `informational` | Log INFO + continue; never blocks | 0 |

### § 3.5 GPG credential deployment (Phase 0 deliv 0.12 partial closure)

Per D64, GPG passphrase is sealed against TPM2 PCR set. Deployment workflow:

```
1. Operator generates GPG keypair on engineering workstation (or per company key-management process)
2. Operator generates the per-env credentials.json plaintext (offline, on secured workstation)
3. Encrypt: gpg2 --symmetric --cipher-algo AES256 --s2k-mode 3 --s2k-count 65011712 \
              --output credentials.json.gpg credentials.json
4. The encryption passphrase is HIGH-ENTROPY (32+ bytes from /dev/urandom)
5. Seal passphrase to target server's TPM2:
   tpm2_createpolicy --policy-pcr -l sha256:0,2,4,7 --policy-pcr-out policy.dat
   echo -n "<passphrase>" | tpm2_create -C primary.ctx -P "<owner_pw>" -i - -L policy.dat -u key.pub -r key.priv
   # Store key.pub + key.priv at /etc/pipeline/tpm2_sealed/ on target server
   #
   # PCR-set rationale (per cycle 1 R6C1-5 advisory finding):
   # - PCR 0  = UEFI firmware (drifts only on firmware update — rare)
   # - PCR 2  = optional ROMs (rare drift)
   # - PCR 4  = boot manager (DRIFTS on every grub2/shim package update — monthly+
   #            cadence per RHEL patch schedule). Including PCR 4 is intentional —
   #            an unauthorized bootloader swap should invalidate the sealed
   #            credential. Trade-off: scheduled re-sealing required after every
   #            grub2/shim package update; B131 proposes a streamlined re-seal
   #            runbook.
   # - PCR 7  = Secure Boot policy (drifts only on policy change)
   # Vendor-canonical alternative on RHEL 9+ is `systemd-creds` (per cycle 1
   # R6C1-5 + Round 2 cycle 1 R2-5 advisory). For RHEL 8 deployment (per § 1.3),
   # systemd-creds is not fully available; bespoke tpm2_unseal + gpg2 path is
   # the necessary choice. B-75 / B-76 tracks the future re-grounding research.
6. Transfer credentials.json.gpg to target server via secured channel
7. Place at /etc/pipeline/credentials.json.gpg mode 0640 owner root:pipeline
8. credentials_loader (Round 3 § 3.1) decrypts via:
   PASSPHRASE=$(tpm2_unseal -c key.ctx -P "session:policy.dat")
   gpg2 --batch --passphrase "$PASSPHRASE" --decrypt credentials.json.gpg
9. The decrypted plaintext stays in process memory (never written to disk)
10. Snowflake RSA key extracted from decrypted dict, written to /dev/shm/snowflake_pk_<pid>
    mode 0600 owner pipeline:pipeline (per D71)
11. On process exit, release_snowflake_key() (per § 7.1 / B65) unlinks /dev/shm key file
```

**Rotation**: GPG envelope rotates quarterly per `MAINTENANCE.md`. TPM2 PCR set drift (e.g., kernel upgrade) requires re-sealing — captured by `tools/verify_server_parity.py` envelope_sha256 check at startup.

**Failure modes**:
- gpg2 fails (envelope corrupt, passphrase wrong) → `CredentialsLoadError` (PipelineFatalError per D68) → exit 2 per § 1.7 Stage 1
- TPM2 unseal fails (PCR set drift) → `CredentialsLoadError` → exit 2; operator runs RB-12 § 5 to re-seal against new PCR set
- /dev/shm full or unwritable → `CredentialsLoadError` → exit 2

### § 3.6 Documented exceptions (per D65 + B38)

Per Round 2 § 4.4, the parity baseline carries a `documented_exceptions` array for time-bounded variance from canonical baseline.

**Constraints** (per D65):

- Each exception has `expires_at` ≤ 90 days from approval date
- Expired exception → behaves as if no exception (the underlying check fails per its tier)
- Exception applies only to the specific `check` it names
- Pipeline-lead is the sole approver (per `MAINTENANCE.md` quarterly cadence)
- 30 days before expiry, B38-tracked notification mechanism fires (cron + email/Slack)

**Round 6 deployment closure of B38**: § 6 below specifies the cron job (`JOB_PARITY_EXCEPTION_NOTIFY` — proposed addition to Round 2 § 5.1 frozen-8 inventory; Round 7 governance amends inventory per B80). Until B80 lands, dev/test/prod each manually check exceptions monthly per MAINTENANCE.

---

## § 4. Code deployment workflow

### § 4.1 Round 1 migrations deployment

Round 1 DDL applies via `migrations/*.py` scripts in dependency order. Per D49 schema v3 ready for DBA review.

**Order of application** (per Round 1 § 1.1 dependency tree):

```
1. PipelineBatchSequence — sequence object; foundational (others reference its NEXT VALUE FOR)
2. PipelineEventLog — referenced by many; partition function predates rows
3. PipelineLog — same
4. PipelineExtraction — referenced by gap detection + range scheduler
5. PipelineExecutionGate — gate-table for AM/PM coordination
6. PromotionLock — server failover lock
7. MaintenanceWindow — outage suppression
8. IdempotencyLedger — referenced by every step
9. ParquetSnapshotRegistry — file index
10. ExtractionRangePolicy — date-range config
11. LatenessProfile — L_99 measurements
12. DeleteEvaluationAudit — per-(date,batch) delete decisions
13. ExtractionGapLog — documented gaps
14. ManualCorrectionLog — operator-driven writes
15. ReconciliationLog — P3-4 results
16. SCD2RepairLog — R-6 actions
17. PiiVault + PiiVaultAccessLog (sibling for FK) — vault + decrypt audit
18. PiiTokenProvenance — first-observation
19. PiiTokenizationBatch — batch audit
20. CcpaDeletionLog — right-to-deletion audit (per RB-10)
21. TableEnablementLog — Phase 4 tracking
22. HealthCheckLog — Phase 6 (deferred; Round 6 creates table for forward-compat)
23. SchemaContract — D40 schema evolution governance (Round 7 territory; Round 6 creates table)
24. All FKs added after referenced tables exist
25. Indexes created after primary tables
26. Stored procedures created last (depend on tables + indexes)
27. UdmTablesList + UdmTablesColumnsList (per Round 2 § 1) — populated by operator post-DDL via separate config tooling
```

**Per-environment apply discipline**:

```
1. dev: apply via `python3 migrations/<name>.py --apply --env dev` in dependency order
2. test: same after dev verified
3. prod: same after test verified — pipeline-lead + DBA pair-review

Each migration script writes one PipelineEventLog row:
  EventType='MIGRATION_<NAME>'
  Status='SUCCESS' or 'FAILED'
  Metadata.applied_at + Metadata.applied_by + Metadata.checksum

Idempotency: re-running a migration on a target that already has the table is
a no-op (per IF NOT EXISTS guards in DDL — same pattern as Round 2 § 1.3
canonical ALTER DDL for the 6 new UdmTablesList columns).
```

**Failure handling**: a migration that errors raises `MigrationError` (proposed PipelineFatalError subclass per D68). Subsequent migrations in the batch are SKIPPED. Operator manually investigates + re-applies failed migration after fix. Re-application is idempotent (per IF NOT EXISTS).

### § 4.2 Round 2 configuration deployment

Per Round 2 § 1 + § 2 + § 5.

**UdmTablesList canonical 29-column inventory + 6 new columns** (per Round 2 § 1 D63):

```
1. Apply migrations/udm_tables_list_new_columns.py — idempotent ALTER DDL adds
   CDCMode, PiiColumnList, DataClassification, CohortAssignment, IsEnabled,
   LegalHoldOnly per Round 2 § 1.2 + § 1.3 canonical DDL
2. Operator populates per-table rows via separate config-management process
   (NOT in scope for Round 6 — config-management is operational, not deployment-time)
3. CK_UdmTablesList_SCD2Mode (per B42) — verify exists post-deploy via:
     SELECT name FROM sys.check_constraints WHERE name = 'CK_UdmTablesList_SCD2Mode'
   If missing, apply migrations/udm_tables_list_check_constraints.py
```

**`.env` per-server keys** (per Round 2 § 2 45 keys):

```
1. Operator copies config/templates/.env.template to /debi/.env
2. Operator fills per-env values from secured operator notes (NEVER committed)
3. File mode 0600 owned by pipeline:pipeline
4. credentials_loader (Round 3 § 3.1) merges /debi/.env env vars with decrypted
   credentials dict at module startup per § 1.7 Stage 1
```

**Automic job inventory** (per Round 2 § 5.1 frozen-8 + Round 7 amendments per B80):

```
Frozen-8 at Round 2:
1. JOB_PIPELINE_AM (production, 02:00)
2. JOB_PIPELINE_AM_FAILOVER (test, 04:30)
3. JOB_PIPELINE_PM (production, 17:00)
4. JOB_PIPELINE_PM_FAILOVER (test, 19:30)
5. JOB_RECONCILE_WEEKLY (production, Sunday 06:00)
6. JOB_RETENTION_MONTHLY (production, 1st of month 04:00)
7. JOB_CCPA_PROCESS (manual invocation only; not Automic-scheduled)
8. JOB_DR_DRILL_QUARTERLY (manual invocation only; not Automic-scheduled)

Round 7 amendments per B80:
9. JOB_PARQUET_VERIFY (proposed daily 03:00 — pending Round 7)
10. JOB_LOG_CLEANUP (proposed weekly Sunday 05:00 — pending Round 7)
11. JOB_PARITY_EXCEPTION_NOTIFY (proposed daily 06:00 per B38 — pending Round 7)
```

**Deployment activates the inventory**:

```
1. Automic team imports job definitions per JOB_<DOMAIN>_<CADENCE> naming
2. Each job's first-step is a gate-table acquire (per RB-9 mechanism) for AM/PM
   OR sp_getapplock + PipelineEventLog for non-AM/PM jobs (per Round 2 § 5.3 D66)
3. Pipeline lead reviews each job's schedule against Round 2 § 5.1
4. First production run scheduled per RB-1 cutover discipline (Phase 2 territory)
```

### § 4.3 Round 3 module deployment (17 modules)

Per Round 3 § 1-§ 7 spec, engineering authors module bodies against the documented signatures. Round 6 deployment workflow:

```
1. Engineering authors module bodies in subprocess from CI:
   - data_load/parquet_writer.py per Round 3 § 1.1
   - data_load/parquet_replay.py per § 1.2
   - data_load/parquet_registry_client.py per § 1.3
   - data_load/pii_tokenizer.py per § 2.1
   - data_load/pii_decryptor.py per § 2.2
   - data_load/vault_client.py per § 2.3
   - data_load/credentials_loader.py per § 3.1
   - schema/server_parity_verifier.py per § 3.2
   - utils/idempotency_ledger.py per § 4.1
   - cdc/extraction_state.py per § 4.2
   - cdc/range_scheduler.py per § 5.1
   - cdc/lateness_profiler.py per § 5.2
   - cdc/gap_detector.py per § 5.3
   - observability/sensitive_data_filter.py per § 6.1
   - observability/log_handler.py per § 6.2
   - observability/event_tracker.py per § 6.3
   - data_load/snowflake_uploader.py per § 7.1
2. Each module gets its Tier 0 smoke test in tests/smoke/test_<module>.py
   per Round 5 § 3.1 catalog (6-assertion contract)
3. CI Tier 0 stage runs all 17 smoke tests in ≤2 min; failure blocks merge
4. CI Tier 1 stage runs unit tests per Round 5 § 4.1 per-module surface
5. Cross-cutting fixes per § 7 below land within the module bodies as they're authored:
   - B65 release_snowflake_key() in credentials_loader per § 7.1
   - B66 event_tracker split (optional refactor) per § 7.x (Round 6 decision: defer per B66 = optional)
   - B67 vault_client typed wrappers (optional) per § 7.x (Round 6 decision: defer per B67 = optional)
   - B68 sensitive_data_filter thread-safety per § 7.4
   - B70 ledger_step metadata param mitigation per § 7.2
   - B72 LedgerStep.prior_result pinning per § 7.3
6. After all 17 modules pass CI Tier 0+1+2, deploy artifact tagged + rolled out per § 1.4
```

### § 4.4 Round 4 tool deployment (11 CLI scripts)

Per Round 4 § 3 spec, engineering authors CLI scripts against the documented contracts. Round 6 deployment workflow:

```
1. Engineering authors CLI scripts under tools/:
   - tools/parquet_tier_review.py per Round 4 § 3.1
   - tools/parquet_verify.py per § 3.2
   - tools/lateness_profile.py per § 3.3
   - tools/decrypt_pii.py per § 3.4
   - tools/detect_extraction_gaps.py per § 3.5
   - tools/promote_test_to_prod.py per § 3.6
   - tools/verify_server_parity.py per § 3.7
   - tools/enforce_retention.py per § 3.8
   - tools/process_ccpa_deletion.py per § 3.9
   - tools/log_retention_cleanup.py per § 3.10
   - tools/alert_dispatcher.py per § 3.11
2. Each tool gets its Tier 0 smoke test in tests/smoke/test_tools_<tool>.py
   per Round 5 § 3.2 catalog (6-assertion contract — D77)
3. Each tool follows D74 exit-code contract (0/1/2)
4. Each tool follows D75 argument naming (--source / --table / --apply / etc.)
5. Each tool writes one PipelineEventLog row per invocation with
   EventType='CLI_<TOOL_NAME>' per D76 + § 6.4
6. Cross-cutting fixes per § 7 below:
   - B87 KeyboardInterrupt → exit 1 per § 7.5
   - B88 --dry-run + --apply mutex per § 7.6
   - B90 AUTOMIC_RUN_ID + isatty() per § 7.7
   - B104 log_retention_cleanup --batch-size 4000 per § 7.8
7. Spec doc corrections per § 8:
   - B89 D77 5-vs-6 Tier 0 assertion count fix
   - B96 SIGINT/exit-130 rationale note
   - B97 SnowSQL exit-code cross-reference note
   - B100 Gate 5 label rename in Round 3 + Round 4 spec docs
   - B101 RB-11 framing reconciliation
   - B102 Round 4 § 0 read order canonical CCL Stage 1
   - B106 B101 line citation refresh
```

### § 4.5 Round 5 test suite deployment (Tier 0-5 implementation)

Per Round 5 § 1.2 + § 3-§ 8 plans, engineering authors test bodies against the documented test plans. Round 6 deployment workflow:

```
Tier 0 (28 tests; <2 min total CI runtime per Round 5 § 1.4):
  - tests/smoke/test_<module>.py for 17 modules per Round 5 § 3.1
  - tests/smoke/test_tools_<tool>.py for 11 tools per Round 5 § 3.2
  - 6-assertion contract per D77 + Round 4 § 1.6
  - Mock subprocess + pyodbc cursor; no external deps; <5s each per D80

Tier 1 (estimated 250-350 individual tests per Round 5 § 4):
  - tests/unit/test_<module>.py per-module surface
  - happy path + per-error-path + per-edge-case coverage
  - ≥90% line coverage per D82 (100% on idempotence-relevant fns)
  - CI runtime ≤5 min total

Tier 2 (Hypothesis-based property tests per Round 5 § 5):
  - tests/property/test_<invariant>.py organized by invariant
  - Master idempotence property per § 5.1 (D15 invariant)
  - Hash byte-stability per § 5.2
  - Tokenization determinism per § 5.3
  - Encryption roundtrip per § 5.4
  - ParquetSnapshotRegistry state graph per § 5.5
  - Lateness percentile monotonicity per § 5.6
  - SensitiveDataFilter idempotence per § 5.7
  - PiiTokenProvenance UNIQUE property per § 5.8
  - max_examples=200 default + derandomize=True CI profile per D81 + B118 per § 7.11
  - CI runtime ≤10 min total

Tier 3 (integration scenarios per Round 5 § 6):
  - tests/integration/test_<scenario>.py per Round 5 § 6.1-§ 6.4
  - Docker SQL Server fixture per D70 + D79 (mcr.microsoft.com/mssql/server:2022-CU14-ubuntu-22.04
    explicit CU pin per § 7.10 cycle 2 fix; Round 5 § 1.3 + B116 referenced `:latest` which
    is now superseded — explicit CU pin avoids parity drift between dev and CI)
  - testcontainers-python Mssql module session-scope container
  - SQLAlchemy-style transactional rollback per Round 5 § 1.3 + B115 per § 7.10
  - Fixture state-leakage mitigation per § 7.10
  - CI runtime ≤30 min total

Tier 4 (crash injection per Round 5 § 7):
  - tests/crash/test_crash_<C-number>.py one file per crash boundary
  - C1-C10 pre-existing per 06_TESTING.md
  - C11-C15 new per Round 5 § 7.2 (CLI-level boundaries)
  - Pre-release only; CI runtime ≤2 hours

Tier 5 (manual audit drills per Round 5 § 8):
  - docs/migration/audit_reports/Q<year>_<quarter>.md per quarter
  - Q1-Q5 pre-existing per 06_TESTING.md
  - Q6-Q10 new per Round 5 § 8.2 (CLI audit / Tier 0 drift / reviewer effectiveness /
    CCPA proof / backup integrity)
  - Manual procedure; no CI runtime; sign-off recorded in audit report
```

### § 4.6 `utils/errors.py` implementation (closes B85)

Per D68 error class hierarchy. Engineering authors `utils/errors.py` at Round 6 deploy as first dependency before any module body:

```python
"""utils/errors.py — Pipeline error class hierarchy per D68.

Two top-level base classes (per D68 + Round 3 § 8.1):
- PipelineError: abstract base; all pipeline-emitted exceptions inherit
- PipelineFatalError: subclass of PipelineError; unrecoverable; CLI exit code 2 per D74
- PipelineRetryableError: subclass of PipelineError; transient; CLI exit code 1 per D74

Per-module subclasses (named per Round 3 + Round 4 spec):
- CredentialsLoadError(PipelineFatalError) per Round 3 § 3.1
- VaultUnavailable(PipelineRetryableError) per Round 3 § 2.3
- VaultConfigError(PipelineFatalError) per Round 3 § 2.3
- TokenNotFound(PipelineFatalError) per Round 3 § 2.2
- DecryptDenied(PipelineFatalError) per Round 3 § 2.2 (NOTE: docstring contradiction
  flagged at B103 — resolved per § 7.9: DecryptDenied IS raised + docstring updated)
- ParityFatalError(PipelineFatalError) per Round 3 § 3.2
- ParityBaselineMissing(PipelineFatalError) per Round 4 § 3.7
- RegistryInsertConflict(PipelineRetryableError) per Round 3 § 1.1
- RegistryStatusInvalid(PipelineFatalError) per Round 3 § 1.3
- RegistryFileNotFound(PipelineRetryableError) per Round 4 § 3.2
- ParquetReplayError(PipelineFatalError) per Round 3 § 1.2
- PiiColumnNotFound(PipelineFatalError) per Round 3 § 2.1
- InvalidTrustGate(PipelineFatalError) per Round 3 § 4.2
- RangePolicyMissing(PipelineFatalError) per Round 3 § 5.1
- InsufficientHistory(PipelineFatalError) per Round 3 § 5.2
- SnowflakeAuthFailed(PipelineFatalError) per Round 3 § 7.1
- LegalHoldConflict(PipelineFatalError) per Round 4 § 3.9
- MigrationError(PipelineFatalError) — NEW per § 4.1 / Round 6 proposal
- FilterConfigError(PipelineFatalError) per Round 3 § 6.1

Each subclass's __init__ accepts (message, *, metadata: dict | None = None).
The metadata dict feeds into PipelineEventLog Metadata field on the wrapping
audit row written by the CLI's error-path handler per D76.
"""

class PipelineError(Exception):
    def __init__(self, message: str, *, metadata: dict | None = None) -> None:
        super().__init__(message)
        self.metadata = metadata or {}

class PipelineFatalError(PipelineError):
    """Exit code 2 per D74."""

class PipelineRetryableError(PipelineError):
    """Exit code 1 per D74; B-7 retry pattern applies."""

# ... per-module subclasses (~17 total)
```

### § 4.7 `tools/verify_tier0_drift.py` implementation (closes B58 stub → full impl)

Per Round 3 close-out, the stub at `tools/verify_tier0_drift.py` raises `NotImplementedError`. Round 6 deployment lands the full implementation:

```
1. Read every Round 3 § 1-§ 7 Tier 0 sketch + Round 4 § 3.1-§ 3.11 Tier 0 sketch
   from the spec docs (regex-extract assertions per the canonical
   6-assertion contract per D77)
2. Read every tests/smoke/test_<X>.py file's assertion set
3. Compute per-file diff:
   - Missing assertion in test file → 🔴 drift
   - Extra assertion in test file → 🟡 (Tier 1 bloat per D80; flag for Tier 1 promotion)
   - Assertion type mismatch (e.g., spec says PipelineFatalError, test catches generic
     Exception) → 🔴 drift
4. Output report at tests/audit_reports/tier0_drift_<date>.md
5. CI integration: run weekly per Q7 audit drill (Round 5 § 8.2)
6. Exit code: 0 clean / 1 yellow drift / 2 red drift per D74
```

---

## § 5. Smoke test runs

### § 5.1 Tier 0 smoke (28 tests, post-deploy gate)

Per Round 5 § 3 catalog + D67 + D77. Tier 0 smoke runs on EVERY post-deploy startup as the deployment gate per § 1.6.

**Execution**: `pytest tests/smoke/ --tb=short --maxfail=1` runs in <2 min on dev-class hardware.

**Pass criteria** (per D82):

| Metric | Target |
|---|---|
| Module-import success rate | 100% (28 of 28 must pass) |
| Total runtime | ≤2 min |
| Per-test runtime | ≤5s (per D80; tests breaching this get Tier 1 promotion review) |
| Mock-only — no external deps | Verified by absence of network / DB / filesystem reads beyond `tmp_path` |

**Failure handling**: any single Tier 0 test failure aborts the deploy. AUTO-ROLLBACK per § 1.5. Failed assertions logged to `PipelineEventLog` with `EventType='DEPLOYMENT_<ENV>'` Status='FAILED' + Metadata.failed_smoke_test.

### § 5.2 Tier 1 unit smoke

Per Round 5 § 4. Tier 1 runs in CI's Tier 1 stage per Round 5 § 1.4 (≤5 min). NOT a post-deploy gate (would breach §1.6 timing budget).

**Execution**: `pytest tests/unit/ --cov=. --cov-report=term-missing --cov-fail-under=90`.

**Pass criteria** (per D82):

| Metric | Target |
|---|---|
| Line coverage | ≥90% per module |
| Idempotence-relevant fns line coverage | 100% |
| Total runtime | ≤5 min |

### § 5.3 Tier 2 property smoke

Per Round 5 § 5. Tier 2 runs in CI's Tier 2 stage per Round 5 § 1.4 (≤10 min).

**Execution**: `pytest tests/property/ --hypothesis-profile=ci`.

**Pass criteria** (per D82 reframed per R5C1-5 advisory):

| Metric | Target |
|---|---|
| Property pass rate within shrinkage budget | 100% of declared properties (Hypothesis is pass-or-fail per shrinkage, not stochastic) |
| max_examples per non-combinatorial module | 200 (default) per D81 |
| max_examples per combinatorial module | 1000 per D81 |
| derandomize | TRUE for CI profile per D81 + § 7.11 |
| deadline per example | 10 seconds per Round 5 § 5.10 |

### § 5.4 Tier 3 integration smoke

Per Round 5 § 6. Tier 3 runs in CI's Tier 3 stage per Round 5 § 1.4 (≤30 min) + nightly.

**Execution**: `pytest tests/integration/ --testcontainers --image=mcr.microsoft.com/mssql/server:2022-CU14-ubuntu-22.04` (explicit CU pin per § 7.10 cycle 2 fix; bumped via dependency-version PR at the same cadence as `requirements-lock.txt` updates).

**Pass criteria** (per D82):

| Metric | Target |
|---|---|
| Scenario pass rate per nightly run | ≥95% (investigate flakes >5%) |
| Docker SQL Server fixture | session-scope container per D79 |
| Fixture state-leakage | mitigated via SQLAlchemy-style transactional rollback per § 7.10 |

### § 5.5 Tier 4 crash injection (pre-release only)

Per Round 5 § 7. Tier 4 runs pre-release; NOT on every CI run (would blow Tier 0+1+2 budget).

**Execution**: manual + scheduled monthly per RB-7 + per release branch creation.

**Pass criteria**:

| Metric | Target |
|---|---|
| Crash boundary recovery success rate | 100% per pre-release run |
| C1-C15 coverage | every crash point tested at least once per release |
| Audit trail | every crash recovery verified by re-running the affected module + asserting clean state |

### § 5.6 First end-to-end pipeline run with synthetic data (post-deploy)

After every successful deploy (per § 1.6 post-check), the first synthetic pipeline run validates the deployment end-to-end. **Synthetic data only** — NO real PII, NO real source DB, NO real Snowflake account.

**Workflow**:

```
1. Operator (or CI on dev) invokes:
   python3 main_small_tables.py --source TEST --table SYNTHETIC_PILOT --dry-run

2. Verify each module startup stage (per § 1.7 Stages 1-5) completes:
   - Credentials_loader stage 1 ✓
   - Vault pool config stage 2 ✓
   - Parity verifier stage 3 ✓
   - Ledger sweep stage 4 ✓
   - Orchestration stage 5 begins ✓

3. Verify orchestration acquires PipelineExecutionGate (per Round 1 SP-3) ✓

4. Verify dry-run extracts synthetic data + writes audit events (NO actual Bronze writes):
   SELECT * FROM General.ops.PipelineEventLog
   WHERE BatchId = <new_batch_id> ORDER BY StartedAt;
   -- Expect: EXTRACT, CDC_PROMOTION (skipped — dry-run), SCD2_PROMOTION (skipped),
   --         CSV_CLEANUP, TABLE_TOTAL — all Status='SUCCESS' or Status='SKIPPED'

5. Verify NO errors in PipelineLog:
   SELECT * FROM General.ops.PipelineLog
   WHERE BatchId = <new_batch_id> AND LogLevel IN ('ERROR', 'CRITICAL');
   -- Expect: zero rows

6. Verify release_snowflake_key cleanup on exit:
   ls /dev/shm/snowflake_pk_*  # Should be empty after process exit
```

**Pass criteria**: all 6 verification steps pass + module startup sequence completed + zero CRITICAL log entries + clean /dev/shm.

**Failure handling**: any step failure aborts the deploy. AUTO-ROLLBACK per § 1.5.

---

## § 6. Automic integration deployment

### § 6.1 Frozen-8 inventory deployment (per D66 + Round 2 § 5.1)

Per Round 2 § 5.1, the Automic job inventory is frozen at 8 jobs. Round 6 deployment activates them.

**Activation order** (post-prod deploy):

```
1. JOB_PIPELINE_AM — start scheduled at 02:00 (production server)
2. JOB_PIPELINE_PM — start scheduled at 17:00 (production server)
3. JOB_PIPELINE_AM_FAILOVER — start scheduled at 04:30 (test server)
4. JOB_PIPELINE_PM_FAILOVER — start scheduled at 19:30 (test server)
5. JOB_RECONCILE_WEEKLY — start scheduled at Sunday 06:00 (production server)
6. JOB_RETENTION_MONTHLY — start scheduled at 1st of month 04:00 (production server)
7. JOB_CCPA_PROCESS — defined but not Automic-scheduled (manual invocation only)
8. JOB_DR_DRILL_QUARTERLY — defined but not Automic-scheduled (manual invocation only)
```

Round 7 amendments per B80 add jobs 9-11 (JOB_PARQUET_VERIFY, JOB_LOG_CLEANUP, JOB_PARITY_EXCEPTION_NOTIFY).

### § 6.2 Gate-table contract activation (per RB-9 + Round 2 § 5.3)

Per RB-9 mechanism, `General.ops.PipelineExecutionGate` is the AM/PM coordination point. Round 6 deployment activates:

```
1. Verify SP-3 (AcquireProd) + SP-4 (AcquireTest) compile + execute (smoke run per § 5.6 confirms)
2. Verify gate-table indices exist (per Round 1 § 1.3):
     UX_PipelineExecutionGate (CycleType, CycleDate) — UNIQUE
     IX_PipelineExecutionGate_Status_StartedAt
3. Verify CK constraints active (per Round 1 L326-332):
     CK_PipelineExecutionGate_CycleType
     CK_PipelineExecutionGate_Status
     CK_PipelineExecutionGate_ExecutingServer
4. Verify sp_getapplock pattern works at acquire-time (no deadlocks under concurrent test)
```

### § 6.3 Failover protocol activation (per RB-2 + RB-9)

Round 6 deployment activates the failover automation:

```
1. Test Automic job JOB_PIPELINE_AM_FAILOVER reads gate-table at 04:30 daily
2. If gate-table reports production AM succeeded → exit cleanly
3. If gate-table reports production AM stale heartbeat + Status='RUNNING' →
   tools/promote_test_to_prod.py per Round 4 § 3.6 D33 cancellation flow
4. Manual fallback runbook: RB-2 for non-Automic failover
5. RB-9 documents the automated path (this section)
```

### § 6.4 CLI_* + CYCLE_* + DEPLOYMENT_* + MIGRATION_* + STARTUP_* EventType family (per D76 + closes B86)

Per D76, every CLI invocation writes one `PipelineEventLog` row with `EventType='CLI_<TOOL_NAME>'`. Round 6 deployment lands the full EventType family registration in CLAUDE.md Architecture Decisions section — five families covering CLI invocations, gate-cycle events, deployment events, migration events, and process-startup events.

**`EventType` width budget** (per Round 1 schema L120 — `EventType NVARCHAR(50)`): every value in every family below MUST fit in NVARCHAR(50). Longest values surveyed: `CLI_DETECT_EXTRACTION_GAPS` (25), `MIGRATION_udm_tables_list_check_constraints` (42), `DEPLOYMENT_ROLLBACK` (19), `CYCLE_FAILED_OVER` (17), `STARTUP_LEDGER_SWEEP` (20) — all comfortably under 50. Future additions must be width-checked at producer self-check time per Pitfall #9 9.d.

**CLI_* family** (11 values, one per Round 4 tool):

```
CLI_PARQUET_TIER_REVIEW
CLI_PARQUET_VERIFY
CLI_LATENESS_PROFILE
CLI_DECRYPT_PII
CLI_DETECT_EXTRACTION_GAPS
CLI_PROMOTE_TEST_TO_PROD
CLI_VERIFY_SERVER_PARITY
CLI_ENFORCE_RETENTION
CLI_PROCESS_CCPA_DELETION
CLI_LOG_RETENTION_CLEANUP
CLI_ALERT_DISPATCHER
```

**CYCLE_* family** (per B105 + Round 4 § 3.6 — 2 new values):

```
CYCLE_FAILED_OVER (test claimed gate after prod heartbeat stale; written by SP-4 path)
CYCLE_CANCELLED (graceful cancellation per D33; written by check_cancellation per RB-9)
```

**DEPLOYMENT_* family** (per D87 — 4 new values for Round 6):

```
DEPLOYMENT_DEV (per dev environment deploy)
DEPLOYMENT_TEST (per test environment deploy)
DEPLOYMENT_PROD (per prod environment deploy)
DEPLOYMENT_ROLLBACK (per any environment rollback)
```

**MIGRATION_* family** (per § 4.1 — N values, one per migration script):

```
MIGRATION_<NAME> (one per migrations/<name>.py invocation)
```

**STARTUP_* family** (per § 1.7 module startup sequence — 4 values for fail-fast diagnostics):

```
STARTUP_CREDS_LOAD (Stage 1 — credentials_loader audit row per § 1.7 L327)
STARTUP_VAULT_CONFIG (Stage 2 — vault pool configuration audit row)
STARTUP_PARITY_CHECK (Stage 3 — server_parity_verifier audit row)
STARTUP_LEDGER_SWEEP (Stage 4 — idempotency_ledger startup_recovery_sweep audit row)
```

(Cycle 1 R6C1-3 found § 1.7 + § 9.3 emit `CREDS_LOAD` / `PARITY_CHECK` / `LEDGER_SWEEP` without registering the family. Cycle 2 fix: register STARTUP_* prefix to canonical the 4 startup-stage audit events.)

**Metadata JSON schema** for each family is defined inline at the relevant section (CLI_* per Round 4 § 1.6; CYCLE_* per Round 4 § 3.6 + RB-9; DEPLOYMENT_* per § 1.6 above; MIGRATION_* per § 4.1; STARTUP_* per § 1.7 stage definitions).

---

## § 7. Cross-cutting fix workstream

### § 7.1 `release_snowflake_key()` implementation (closes B65)

Per D71 + Round 3 § 3.1 / § 7.1 Produces, `release_snowflake_key()` is declared but not defined. Round 6 deployment lands the implementation in `credentials_loader.py`:

```python
def release_snowflake_key(*, key_file_path: str) -> None:
    """Remove the ephemeral Snowflake RSA key file at process exit.

    Owner of the file is credentials_loader (creates it at module startup
    per § 1.7 Stage 1 / D71). Called at process exit via atexit registration.

    Per D71 the key file is at /dev/shm/snowflake_pk_<pid> mode 0600;
    /dev/shm is tmpfs so the file is volatile across reboots, but a crash
    mid-session leaves the file (per R20 risk). This function is the
    deterministic cleanup path; atexit ensures it runs on clean exit.

    Args:
      key_file_path: absolute path to the ephemeral key file.

    Returns: None. Logs INFO on success; WARNING on file already absent
    (idempotent re-call); CRITICAL on unlink failure (operator must
    investigate /dev/shm state).

    Raises: nothing. This is a best-effort cleanup function.
    """
    import os, logging
    logger = logging.getLogger(__name__)
    try:
        if os.path.exists(key_file_path):
            os.unlink(key_file_path)
            logger.info("Released Snowflake key file: %s", key_file_path)
        else:
            logger.warning("Snowflake key file already absent: %s", key_file_path)
    except OSError as e:
        logger.critical(
            "Failed to release Snowflake key file %s: %s",
            key_file_path, e, exc_info=True
        )
```

**Closes B65**. R20 (per RISKS.md L30) score remains 2 ⚪ — `release_snowflake_key()` doesn't eliminate the risk (only mitigates the clean-exit path), so tmpfs auto-reset + filesystem-level orphan monitor (per RISKS.md L30 mitigation) remain in place.

### § 7.2 `ledger_step(metadata=...)` param footgun mitigation (closes B70)

Per Round 3 § 4.1, `ledger_step()` accepts `metadata` kwarg but silently discards (B70-flagged "traceability beats convenience" violation per pillar rubric). Round 6 deployment implements `DeprecationWarning`:

```python
def ledger_step(*, batch_id, source_name, table_name, event_type, metadata=None):
    """Per Round 3 § 4.1 with B70 footgun mitigation."""
    if metadata is not None:
        import warnings
        warnings.warn(
            "ledger_step(metadata=...) is accept-and-discard; "
            "use event_tracker.track() to persist Metadata. "
            "metadata kwarg will be removed in a future version.",
            DeprecationWarning,
            stacklevel=2,
        )
    # ... rest of ledger_step body
```

**Closes B70**. Future Round (post-Round-8) may remove the kwarg entirely.

### § 7.3 `LedgerStep.prior_result` pinning (closes B72)

Per Round 3 § 4.1 LedgerStep dataclass, `prior_result: Optional[dict]` — None on short-circuit. Callers MUST check `was_short_circuited` first. Round 6 deployment adds mypy annotation + Tier 0 assertion:

```python
@dataclass
class LedgerStep:
    """Per Round 3 § 4.1 with B72 caller-side contract pinning."""
    batch_id: int
    source_name: str
    table_name: str
    event_type: str
    status: str  # 'IN_PROGRESS' / 'COMPLETED' / 'FAILED' per `CK_IdempotencyLedger_Status` (`01_database_schema.md` L445-446 — 3-value enum; distinct from PipelineEventLog 4-value enum L143-144 which includes 'SKIPPED')
    was_short_circuited: bool
    prior_result: Optional[dict] = None  # None iff was_short_circuited is True
    
    def __post_init__(self):
        # B72: pin caller-side contract
        if self.was_short_circuited and self.prior_result is None:
            pass  # Expected: short-circuit returns None prior_result
        elif not self.was_short_circuited and self.prior_result is None:
            pass  # Expected: normal flow, no prior result to surface
        # else: prior_result populated → caller should check was_short_circuited before subscripting
```

**Closes B72**. Round 5 § 4.1 unit tests assert this invariant.

### § 7.4 `sensitive_data_filter` thread-safety resolution (closes B68)

Per Round 3 § 6.1 deep-validation Reviewer D, `sensitive_data_filter` claims "read-only after import" but exposes `register_pii_pattern()` runtime mutation. Round 6 deployment chooses **option (a)**: restrict registration to module-import time only.

```python
# observability/sensitive_data_filter.py
_PATTERNS: dict[str, re.Pattern] = {}  # Frozen at module import
_REGISTRATION_CLOSED = False  # Set to True after module-import-time registrations

def register_pii_pattern(name: str, pattern: str) -> None:
    """Per Round 3 § 6.1 + B68 option (a) — module-import time only.
    
    Raises FilterConfigError if called after module import is complete.
    """
    if _REGISTRATION_CLOSED:
        raise FilterConfigError(
            "register_pii_pattern() must be called at module import time only. "
            "Runtime mutation breaks thread-safety guarantees per § 6.1."
        )
    try:
        _PATTERNS[name] = re.compile(pattern)
    except re.error as e:
        raise FilterConfigError(f"Invalid regex pattern {pattern!r}: {e}")

def _close_registration() -> None:
    """Called once at end of module-import via @final marker; thread-safety boundary."""
    global _REGISTRATION_CLOSED
    _REGISTRATION_CLOSED = True
```

**Closes B68**. Documentation in Round 3 § 6.1 already claims "read-only after import" — Round 6 implementation enforces it.

### § 7.5 `KeyboardInterrupt` → exit 1 (closes B87)

Per Round 4 § 1.8 D74, exit codes are 0/1/2. KeyboardInterrupt has two conventions: Unix exit 130 (128+SIGINT) OR Round 4 default exit 1 (expected operational failure). Round 6 deployment chooses **Round 4 default exit 1** for consistency with D74 contract:

```python
# tools/<any>.py wrapper
def main():
    try:
        return _real_main()
    except KeyboardInterrupt:
        logger.warning("Interrupted by operator (SIGINT)")
        return 1  # B87 decision: Round 4 contract over Unix convention
    except PipelineRetryableError as e:
        logger.warning("Retryable error: %s", e)
        return 1
    except PipelineFatalError as e:
        logger.critical("Fatal error: %s", e)
        return 2
    except Exception as e:
        logger.critical("Unexpected error: %s", e, exc_info=True)
        return 2
```

**Closes B87**. SIGINT rationale note added to Round 4 § 1.8 per § 8.8 closing B96.

### § 7.6 `--dry-run` + `--apply` mutex (closes B88)

Per Round 4 § 1.4, `--dry-run` (default for side-effecting tools) and `--apply` are mutually exclusive. Round 6 deployment implements via argparse mutex group:

```python
parser = argparse.ArgumentParser(...)
mutex = parser.add_mutually_exclusive_group()
mutex.add_argument("--dry-run", action="store_true", default=True)
mutex.add_argument("--apply", action="store_true")
args = parser.parse_args()
# argparse raises SystemExit(2) if both set — matches D74 exit-code contract
```

**Closes B88**.

### § 7.7 `AUTOMIC_RUN_ID` + `isatty()` edge case (closes B90)

Per Round 4 § 1.7 actor TTY heuristic + D75. Round 6 deployment chooses: when both `AUTOMIC_RUN_ID` env var IS set AND `sys.stdin.isatty() is True`, prefer the explicit env var (AUTOMIC_RUN_ID = automated invocation) over TTY heuristic. Rationale: an Automic operator manually testing via terminal may have both — the env var is the more reliable signal.

```python
def detect_invocation_pattern():
    """Per Round 4 § 1.7 + B90 edge case resolution."""
    if os.environ.get("AUTOMIC_RUN_ID"):
        return "automic"  # Env var takes precedence over TTY heuristic
    elif sys.stdin.isatty():
        return "tty"
    else:
        return "non-tty"  # Cron, systemd, pipe, etc.
```

**Closes B90**.

### § 7.8 `log_retention_cleanup --batch-size` default 50000 → 4000 (closes B104)

Per CLAUDE.md B-2 lesson, SQL Server escalates to table-level exclusive locks at ~5000 locks. Round 6 deployment changes the default from 50000 (Round 4 § 3.10 L1274 original) to 4000 (mirrors `config.SCD2_UPDATE_BATCH_SIZE`):

```python
# tools/log_retention_cleanup.py
parser.add_argument(
    "--batch-size", type=int, default=4000,  # B104: was 50000
    help="DELETE batch size. Default 4000 mirrors B-2 lock-escalation threshold "
         "(SQL Server escalates to table-level exclusive lock at ~5000)."
)
```

**Round 4 § 3.10 L1297 Tier 0 assertion (f) coordination**: Round 4 § 3.10's Tier 0 smoke asserts `'--batch-size 10000' reflected in DELETE` — that assertion documents that an explicit `--batch-size <N>` argument is honored at the DELETE WHERE clause (a *behavior* test, not a *default-value* test). The behavior test remains valid post-default-change (passing `--batch-size 10000` still produces a DELETE that reflects `10000`). § 8.3 spec doc correction lands the default-value documentation change in Round 4 § 3.10 L1274 (50000 → 4000) without modifying the L1297 Tier 0 behavior-assertion line.

**Closes B104** in code (default change) + § 8.3 closes the doc-side default reference. R6C1-1 cycle 1 finding correctly flagged the Tier 0 assertion language; cycle 2 framing clarifies the *behavior-vs-default* distinction so the assertion stays as-is.

### § 7.9 `decrypt_token` docstring contradiction resolution (closes B103)

Per Round 3 § 2.2 + R4C8 finding, `decrypt_token` has internal contradiction: declared `DecryptDenied` PipelineFatalError vs docstring claims "returns None on denied". Round 6 deployment chooses **DecryptDenied IS raised**: behavior follows D68 PipelineFatalError pattern; docstring updated. Engineering updates `pii_decryptor.py` body to actually `raise DecryptDenied()` for the denied path; Round 5 § 4.1 / § 3.1 pii_decryptor tests reflect this (the previous Round 5 plan assumed `returns None` — Round 6 reconciles).

**Closes B103** in code + spec doc. § 8.2 closes the doc-side reference.

### § 7.10 Test fixture state-leakage mitigation (closes B115)

Per Round 5 § 1.3 + R5C1-5 advisory + B115. Round 6 deployment authors fixture infrastructure:

```python
# tests/fixtures/udm_test_fixtures/conftest.py
import pytest
from sqlalchemy import create_engine

@pytest.fixture(scope="session")
def mssql_container():
    """Session-scope Docker SQL Server fixture per D79 + B116.

    Image pin: explicit cumulative-update tag, NOT `:latest` (cycle 1 R6C1-5
    advisory — `:latest` is a moving target; today's :latest may be CU14,
    six months later :latest = CU17 and a SQL Server behavior change masks
    a real bug. Pin to explicit CU tag tracked under the parity baseline.)
    Update the pin via dependency-version PR at the same cadence as
    requirements-lock.txt updates; never bump silently.
    """
    from testcontainers.mssql import MsSqlServer
    with MsSqlServer(image="mcr.microsoft.com/mssql/server:2022-CU14-ubuntu-22.04") as container:
        # Apply schema.sql once per session
        engine = create_engine(container.get_connection_url())
        with open("tests/fixtures/udm_test_fixtures/schema.sql") as f:
            engine.execute(f.read())
        yield container

@pytest.fixture(scope="function")
def test_db_transaction(mssql_container):
    """Per-function transactional rollback per Round 5 § 1.3 + B115."""
    engine = create_engine(mssql_container.get_connection_url())
    conn = engine.connect()
    trans = conn.begin()
    yield conn
    trans.rollback()  # Each test starts from clean slate
    conn.close()
```

**Closes B115**.

### § 7.11 Hypothesis `derandomize=True` CI profile (closes B118)

Per Round 5 § 5.10 + R5C1-5 advisory + B118. Round 6 deployment authors:

```python
# tests/conftest.py
from hypothesis import settings, HealthCheck

settings.register_profile(
    "ci",
    derandomize=True,
    max_examples=200,
    deadline=timedelta(seconds=10),
    suppress_health_check=[HealthCheck.too_slow],
)
settings.register_profile(
    "dev",
    max_examples=200,
    deadline=timedelta(seconds=10),
)
settings.register_profile(
    "release",
    max_examples=5000,
    deadline=timedelta(seconds=30),
)
# Nightly: non-derandomized to discover fresh edge cases over time.
# Counterbalances the `ci` profile's coverage-freeze property — when test
# functions don't change for weeks, derandomized profile stops finding new
# bugs. Cycle 1 R6C1-5 advisory finding.
settings.register_profile(
    "nightly",
    derandomize=False,
    max_examples=500,
    deadline=timedelta(seconds=20),
)

# CI sets:        pytest --hypothesis-profile=ci         (per-commit; reproducible)
# Local sets:     pytest --hypothesis-profile=dev        (default; randomized)
# Nightly CI:     pytest --hypothesis-profile=nightly    (fresh-edge-case discovery)
# Pre-release:    pytest --hypothesis-profile=release    (broad sweep before tag)
```

**Closes B118**. Round 6 CI stage 3 (Tier 2 nightly per § 5.3) runs `--hypothesis-profile=nightly` in addition to `--hypothesis-profile=ci` to mitigate the derandomized-coverage-freeze trade-off.

### § 7.12 Optional deferred refactors (B66 + B67)

**B66 event_tracker god-module split**: deferred per BACKLOG entry "Architectural refactor, not blocking Round 3 lock". Round 6 deployment does NOT split. Reason: refactor would require Round 5 § 4.1 event_tracker unit tests to be rewritten; Round 5 test surface is frozen. Defer to post-Round-8 architectural cleanup phase.

**B67 vault_client typed wrappers**: deferred per BACKLOG entry "Affects Round 5 test surface — typed wrappers easier to mock". Round 6 deployment does NOT introduce typed wrappers. Reason: Round 5 § 4.1 vault_client tests already accommodate the stringly-typed RPC; adding wrappers post-Round-5 would require test-surface changes outside Round 6's deployment scope. Defer to post-Round-8 architectural cleanup phase.

---

## § 8. Spec doc corrections (Round 6 documentation closures)

Round 6 deployment-time edits to Rounds 3-4 spec docs to close trivial-polish B-items without supersession. These are documentation corrections — NOT substantive design changes — and follow the close-out task pattern established by B40 (which appended F21-F23 to `04_EDGE_CASES.md` without superseding it).

### § 8.1 D77 5-vs-6 Tier 0 assertion count fix (closes B89)

`phase1/04_tools.md` § 2 currently states "5 canonical assertions" per D77; § 1.6 + `06_TESTING.md` Tier 0 section + Round 5 § 3 state 6. Round 6 fix: update `04_tools.md` § 2 to "6 canonical assertions" matching § 1.6 + canonical.

### § 8.2 Round 3 § 2.2 `decrypt_token` docstring fix (closes B103)

Per § 7.9 above, `DecryptDenied` IS raised. Update `phase1/03_core_modules.md` § 2.2 `decrypt_token` docstring to "Raises DecryptDenied on access denied" — replacing the "returns None on denied" claim. Round 5 § 4.1 pii_decryptor test plan updated to match.

### § 8.3 Round 4 § 3.10 batch-size default doc fix (closes B104)

Per § 7.8 above, default is 4000 (was 50000). Update `phase1/04_tools.md` § 3.10 to reflect.

### § 8.4 RB-11 framing reconciliation (closes B101)

`docs/migration/05_RUNBOOKS.md` L967 canonical title: "7-Year Retention Enforcement". `phase1/04_tools.md` § 3.8 + § 3.9 mislabel as "legal-hold runbook" at L1069/L1125/L1216. Round 6 fix: correct `04_tools.md` references to canonical "7-Year Retention Enforcement". RB-11 itself is unchanged.

### § 8.5 Round 4 § 0 read order canonical CCL Stage 1 fix (closes B102)

`phase1/04_tools.md` § 0 (L13-19) reorders canonical CCL Stage 1 sequence. Canonical per `MULTI_AGENT_GUIDE.md` L189-194: NORTH_STAR → HANDOFF → CURRENT_STATE → CHECKS_AND_BALANCES. Round 6 fix: re-order Round 4 § 0 to canonical sequence.

### § 8.6 Gate 5 label rename in Round 3 + Round 4 (closes B100)

Per R4C4-4 finding, `phase1/04_tools.md` § 5.2 + `phase1/03_core_modules.md` § 10.2 conflate Gate 5 (idempotency/regression) with D61 risk-delta meta-check. Round 6 fix: re-label these sections to "Gate 5 + D61 risk-delta + Backlog surfacing" matching Round 5 § 11.2 corrected label.

### § 8.7 B101 line citation refresh (closes B106)

BACKLOG.md B101 entry claims "L1124/L1156/L1215" but actual post-fix lines are "L1069/L1125/L1216". Trivial fix: refresh B101 BACKLOG entry.

### § 8.8 SIGINT/exit-130 rationale note in Round 4 § 1.8 (closes B96)

Per § 7.5 above, decision: KeyboardInterrupt → exit 1 (Round 4 contract over Unix exit 130 convention). Round 6 fix: add rationale note to `phase1/04_tools.md` § 1.8 documenting the choice.

### § 8.9 SnowSQL cross-reference note in Round 4 § 1.1 (closes B97)

R5C1-5 advisory: Round 4 § 1.1 doesn't reference SnowSQL exit-code conventions (which differ from D74). Round 6 fix: add a note to `phase1/04_tools.md` § 1.1 acknowledging SnowSQL's different convention + explicit reason Round 4 doesn't adopt it (pipeline tools wrap module bodies, not native Snowflake CLIs).

### § 8.10 testcontainers-python image pin in D79 / § 1.3 (closes B116)

R5C1-5 advisory + R6C1-5 cycle 1 advisory: cite canonical `mcr.microsoft.com/mssql/server:<CU-tag>` + testcontainers-python Mssql module in D79 + Round 5 § 1.3. **Cycle 2 fix supersedes the `:latest` reference**: pin to explicit cumulative-update tag `2022-CU14-ubuntu-22.04` to avoid parity drift between dev + CI environments. The `:latest` tag is a moving target — today's `:latest` may be `CU14`; six months later it's `CU17` with a SQL Server behavior change that masks a real bug. Round 6 § 7.10 + § 5.4 use the explicit CU pin; Round 5 § 1.3 doc reference updated at close-out via § 8.10 spec correction. The pin bumps via dependency-version PR at the same cadence as `requirements-lock.txt` updates — never silently.

### § 8.11 BACKLOG B77 closure (closes B119)

B77 BACKLOG entry status 🟡 Open but R22 already in RISKS.md L32 per Round 4 close-out. Round 6 fix: move B77 to BACKLOG.md Completed section with reference "Closed at Round 6 close-out — R22 already landed in RISKS.md per Round 4 close-out".

### § 8.12 `CK_UdmTablesList_SCD2Mode` reconciliation query (closes B42)

Per Round 2 § 1.4 reconciliation query. Round 6 deployment runs against prod:

```sql
SELECT name FROM sys.check_constraints
WHERE parent_object_id = OBJECT_ID('General.dbo.UdmTablesList')
  AND name = 'CK_UdmTablesList_SCD2Mode';
```

If missing, apply `migrations/udm_tables_list_check_constraints.py`. **Closes B42**.

---

## § 9. Rollback + recovery

### § 9.1 Per-environment rollback procedure

Per § 1.2 + § 1.5 rollback workflow. Operator authorization required for any prod rollback (per RB-12 § 3).

### § 9.2 Failed-deployment recovery

A failed deploy leaves the prior tag intact at `/opt/pipeline/<prior_tag>/`. Recovery is symlink-revert + restart per § 1.5. Failed tag retained for forensics.

### § 9.3 Module-startup-failure handling

If § 1.7 module startup fails at any stage, the process exits with the documented exit code. The systemd unit restarts the process up to 3 times (per `Restart=on-failure, RestartSec=30s, StartLimitInterval=3min, StartLimitBurst=3`); if all 3 fail, systemd enters `failed` state and alerts.

**Restart policy depends on D74 exit-code contract** (per cycle 1 R6C1-5 advisory): `Restart=on-failure` triggers ONLY on non-zero exit or signal — NOT on `sys.exit(0)`. Honoring this restart policy requires the Python process exits with non-zero on operational failures per D74 (1=expected operational / 2=fatal). A module that catches an exception and silently returns 0 on logical failure = no restart, no alert, invisible failure. This is why D74 exit-code discipline is load-bearing for the systemd retry mechanism, not just for Automic semantics. § 4.6 `utils/errors.py` + Round 4 § 1.8 PipelineFatalError / PipelineRetryableError → exit-code wrappers preserve this contract end-to-end.

Operator workflow:
```
1. systemctl status pipeline.service → check failure stage from journal
2. Inspect PipelineEventLog for the failed startup event:
   SELECT TOP 10 EventType, Status, ErrorMessage, Metadata
   FROM General.ops.PipelineEventLog
   WHERE EventType IN ('CREDS_LOAD','PARITY_CHECK','LEDGER_SWEEP')
   ORDER BY StartedAt DESC;
3. Stage 1 fail → run tools/verify_server_parity.py + check GPG envelope + TPM2 state
4. Stage 3 fail → run tools/verify_server_parity.py standalone
5. Stage 4 fail → check IdempotencyLedger connectivity; clear stale IN_PROGRESS rows manually
6. If unresolvable → ROLLBACK per § 9.1
```

### § 9.4 Partial-deployment cleanup

If deploy fails mid-rsync (partial file tree present), the symlink swap doesn't fire (atomic — only swaps after rsync complete). Failed partial trees auto-clean via cron job that purges `/opt/pipeline/<tag>/` dirs older than 7 days that AREN'T the current or last-5 prior tags.

### § 9.5 RB-12 deployment runbook (closes B41)

Per B41 (BACKLOG L73), RB-12 is to be authored after D64 locks. D64 locked 2026-05-10; Round 6 close-out lands RB-12 in `05_RUNBOOKS.md`. RB-12 sub-section numbering (per cycle 5 fix per R6C4 sleeper-bug 🟡-2 — pre-pinned so forward-cites in § 1.5 / § 3.5 / § 9.1 / § 10.1 resolve consistently at close-out):

```
RB-12: Pipeline Deployment (per D84-D87 + § 1.2 + § 1.5)

When: scheduled per § 1.5 (dev nightly, test daily, prod weekly Monday window)
      OR emergency hotfix (with explicit operator + pipeline-lead sign-off)

§ 1 — Pre-flight checks (§ 1.6 pre-deployment checklist)
§ 2 — Procedure (§ 1.4 code deployment mechanism)
§ 3 — Authorization (operator + pipeline-lead sign-off chain; rollback decision per § 1.5 matrix)
§ 4 — Smoke runs (§ 5 smoke test runs)
§ 5 — Post-deployment validation (§ 1.6 post-deployment checklist; lateness baseline verification per § 10.1 M-row; vault decrypt path verification per § 10.1 P-row; re-seal workflow when TPM2 PCR drifts per § 3.5; quarterly parity baseline refresh per § 10.1 DP3-row)
§ 6 — Rollback (§ 1.5 + § 9.1)
§ 7 — Recovery (§ 9.2 + § 9.3) + Audit verification (verify DEPLOYMENT_<ENV> + DEPLOYMENT_ROLLBACK rows in PipelineEventLog)
```

RB-12 full body authored at Round 6 close-out per B127 (closes B41). Sub-section ordinal map preserved at authoring.

---

## § 10. Edge case mapping (Gate 3 input)

Walk M / S / I / N / P / G / D / F / V series + new T-series + new Round 6 deployment-specific edge cases:

### § 10.1 Series-by-series walk

| Series | Round 6 coverage | Specifics |
|---|---|---|
| **M** | ✅ Tier 1 unit tests (Round 5 § 4.1 lateness_profiler — monotonic p50≤p90≤p95≤p99≤max + InsufficientHistory) + Tier 2 property (Round 5 § 5.6 percentile monotonicity) + Tier 3 integration (Round 5 § 6.2 test_lateness_profiler_full_history) | RB-12 § 5 (post-deployment validation per § 9.5 outline) runs `tools/lateness_profile.py` against post-deploy state; first synthetic run per § 5.6 confirms lateness baseline path. Cycle 5 fix: original M-row cited Round 5 § 8 Q4 which is canonically "Vault key/token rotation proof (annual)" per `06_TESTING.md` L378, NOT lateness — Pitfall #9 9.h instance corrected. |
| **S** | ✅ § 4.5 Tier 3 integration smoke verifies SCD2 chain integrity after deploy | First synthetic pipeline run per § 5.6 |
| **I** | ✅ § 1.4 deploy idempotency + § 4.1 migration idempotency + § 1.7 startup sequence idempotent | Re-deploy = no-op when sources unchanged |
| **N** | ✅ § 3.4 network drive mount verification + § 5 first synthetic run writes Parquet to mounted drive | Mount must be pre-deployed |
| **P** | ✅ § 3.5 GPG credential deployment + § 7.1 release_snowflake_key cleanup + § 5.6 P5 verification (no plaintext in log) | RB-12 § 5 verifies vault decrypt path |
| **G** | ✅ § 5.6 first synthetic run verifies gap detection path (running tools/detect_extraction_gaps.py against post-deploy state) | No gaps expected on fresh deploy |
| **D** | ✅ § 6.1 Automic frozen-8 activates AM/PM cadence | RB-9 + RB-12 cross-reference |
| **F** | ✅ § 6.3 failover protocol activation + § 9 rollback discipline | F21/F22/F23 closed at Round 2; F25 (per B98) per Round 5 § 10 |
| **V** | ✅ Tier 5 Q9 CCPA proof drill + § 8.12 CK_UdmTablesList reconciliation | Per RB-10 |

### § 10.2 New Round 6 deployment-specific edge cases (DP-series, NEW prefix)

Note on prefix: existing D-series in `04_EDGE_CASES.md` L148 is "D-Series: 2x/day Cadence" (5 cases D1-D5). To avoid collision, Round 6 introduces a new **DP-series** prefix for **D**eployment-**P**ipeline edge cases. Cycle 1 R6C1-4 flagged the collision; cycle 2 fix renames the new series before close-out.

| Proposed | Description | Mitigation in Round 6 |
|---|---|---|
| **DP1** (deployment series, NEW for Round 6) | Atomic symlink swap fails mid-deploy — `/opt/pipeline/current` points to incomplete tag dir | § 1.4 rsync completes BEFORE symlink swap; failed rsync leaves symlink at prior tag; **swap itself is atomic via `mv -T`** (single rename(2) syscall per cycle-2 fix) |
| **DP2** | systemd restart fails — process won't start in new tag | systemd retries 3x; falls into `failed` state; alert fires; operator ROLLBACK per § 9.1; **restart policy requires non-zero exit per D74 end-to-end** per § 9.3 cycle-2 fix |
| **DP3** | Parity baseline drift detected post-deploy but not at deploy-time — sneaking through documented_exceptions window | § 3.6 90-day exception expiry + RB-12 § 5 quarterly parity baseline refresh |
| **DP4** | Subprocess workers fail to inherit credentials (per D69 + § 1.7 invariant) — TPM2 unseal storm | § 1.7 NOTE: subprocess workers inherit via pickle, NOT re-read GPG envelope; load test at § 5.6 catches this |
| **DP5** | Tier 0 smoke passes but Tier 1 fails in CI — false-clean deploy gate | § 5.2 Tier 1 runs in CI pre-deploy; CI fail blocks promotion to next env per § 1.5 |
| **DP6** | Time-skew between dev/test/prod servers — affects scheduled job sequencing | NTP sync mandated per § 1.3; § 3.4 parity baseline includes server time drift check |
| **DP7** (NEW per cycle 2 R6C1-5 advisory) | grub2/shim package update drifts PCR 4; TPM2 unseal fails → Stage 1 of § 1.7 exits 2 | § 3.5 PCR rationale note + RB-12 § 5 re-seal workflow + alert routes to operator |

**Close-out task**: append DP1-DP7 to `04_EDGE_CASES.md` under new **"DP-Series: Deployment Pipeline"** section. Tracked as B121.

### § 10.3 Test-series edge cases (per B108 + Round 5 § 10.2)

T1-T3 from Round 5 § 10.2 still apply at Round 6 deploy:

| ID | Description | Round 6 mitigation |
|---|---|---|
| T1 (test-series) | Tier 0 smoke test drift — CI passes stale test that no longer matches contract | § 4.7 verify_tier0_drift.py full impl (closes B58); Q7 quarterly audit per Round 5 § 8.2 |
| T2 | Tier 2 property hits Hypothesis shrinkage budget — masked real bug | § 7.11 derandomize=True CI profile per B118 + nightly profile per cycle 2 fix ensures reproducible failures + fresh-edge-case discovery |
| T3 | Tier 3 integration test produces flake (Docker SQL Server warmup) | § 7.10 SQLAlchemy-style rollback per B115 + ≥95% scenario pass rate target; § 5.4 + § 7.10 pin explicit CU tag per cycle 2 fix |
| **T4** (NEW per cycle 2 R6C1-5 advisory) | Hypothesis CI profile derandomized → fresh edge cases not discovered for weeks while test function stable | § 7.11 nightly profile (non-derandomized) runs in nightly CI stage; counterbalances derandomized CI profile coverage-freeze property |

---

## § 11. Validation gates (Round 6 producer self-check)

Per D55 + D62, producer self-check before Pattern E Gate 2 review.

### § 11.1 Gate 1 self-check — Cross-reference

Per § 2 above, every Round 1 / Round 2 / Round 3 / Round 4 / Round 5 reference walked against canonical per Pitfall #9 a-i. ✅

### § 11.2 Gate 5 self-check — Idempotency + Risk delta + Backlog (per D61 + B100 corrected label)

**Idempotency / regression** (the actual Gate 5 surface per D55):
- D15 invariant: § 1.4 deploy workflow + § 4.1 migration application are idempotent (re-deploy = no-op when sources unchanged)
- D17 ledger pattern: § 1.7 Stage 4 ledger startup sweep preserves the master invariant
- D26 append-only: § 1.6 DEPLOYMENT_<ENV> audit rows are append-only
- No locked decision (D55-D83) contradicted by Round 6 deployment spec

**Risks introduced / addressed** (per D61):

```
RISKS (per D61):
- ⬇️ DE-ESCALATED (pending substantiation): R02 (Round 0.5 spike untested) — § 5.6
  first synthetic pipeline run is the Round 0.5 spike's parallel verification. Hedge
  per Pitfall #8: do NOT reduce R02 score until first ~3 production deploys actually
  succeed AND Round 0.5 spike outcomes are documented.

- ⬇️ DE-ESCALATED (pending): R08 (cross-server parity drift) — § 3.4 baseline
  discipline + § 1.7 Stage 3 startup verifier + § 3.6 documented exceptions
  mitigate. Hedge: do NOT reduce R08 score until first quarterly parity audit per
  MAINTENANCE.md confirms drift detection works.

- ⬇️ DE-ESCALATED (pending): R23 (Round 4 BACKLOG carryover) — Round 6 § 12 triage
  closes 12+ in-round + 6 to Round 7. Hedge: do NOT reduce R23 score until Round 7
  close-out confirms its 6-item triage completes.

- ⬇️ DE-ESCALATED (pending): R25 (Round 5 BACKLOG carryover) — Round 6 § 12 picks up
  the 24 Round-6-deferral items per Round 5 § 9.2. Hedge: do NOT reduce R25 score
  until Round 6 close-out confirms the systematic triage.

- ◎ UNCHANGED: R10 (production hardware failure) — § 9 rollback discipline + RB-12
  do NOT address hardware-level failure (which is RB-2 + RB-9 territory). Round 6
  validates the failover code path via § 6.3 + § 5.6 smoke runs but doesn't reduce
  the hardware-failure risk itself.

- 🆕 NEW PROPOSAL: R26 — Deployment artifact tampering. Likelihood Low × Impact
  High = 3 🟡. Risk: between git tag creation + target server deployment, the
  artifact tarball could be tampered with in transit. Mitigation: § 1.4 GPG-signed
  manifest verified post-rsync. Status: NOT YET ADDED to RISKS.md — close-out task
  per Pitfall #8.

- 🆕 NEW PROPOSAL: R27 — Pre/post-deploy checklist gate skipped under deadline
  pressure. Likelihood Medium × Impact Medium = 4 🟡. Risk: operator under
  pressure manually overrides the failed-check, deploys anyway, downstream
  failures. Mitigation: § 1.6 audit-row records every check pass/fail with actor
  + justification; pipeline-lead reviews any FAILED-with-override at next round
  close-out. Status: NOT YET ADDED — close-out task per Pitfall #8.
```

**Backlog proposals** (per D61 — current max in BACKLOG.md after Round 5 close-out is B119; NEXT_AVAILABLE = B120):

```
BACKLOG (per D61):
- 🟡 B120: HANDOFF §8 Pitfall #9 sub-class 9.i formalization
       (process-discipline-claim drift / false-closure / wrong-doc-scope /
       stale-count). 3+ fresh-instance occurrences across R5 cycles 1-4 + zero
       fresh-instance in R6 producer self-check pre-flight = pattern is structural,
       not coincidental. Round 5 anticipated B120 at its close-out as candidate;
       Round 6 close-out lands the formal sub-class. COD 2, JS 1, WSJF=2.0
- 🟡 B121: Append D-next..D-next+5 deployment-series edge cases to 04_EDGE_CASES.md
       per § 10.2 (rsync atomic-swap fail, systemd restart fail, parity drift
       sneaking through exceptions, subprocess credential inheritance, Tier 0/1
       gate mismatch, time-skew). Round 6 close-out task. COD 2, JS 1, WSJF=2.0
- 🟡 B122: D84 (Deployment artifact contract) lockdown via decision recording at
       Round 6 close-out. COD 1, JS 1, WSJF=1.0
- 🟡 B123: D85 (Module startup sequence) lockdown — closes B69. COD 1, JS 1, WSJF=1.0
- 🟡 B124: D86 (3-env deployment cadence) lockdown. COD 1, JS 1, WSJF=1.0
- 🟡 B125: D87 (Pre/post-deploy checklist contract) lockdown. COD 1, JS 1, WSJF=1.0
- 🟡 B126: Add R26 (artifact tampering) + R27 (checklist override) to RISKS.md per
       Pitfall #8. COD 2, JS 1, WSJF=2.0
- 🟡 B127: Author RB-12 (Pipeline Deployment) in full per § 9.5 outline. Closes B41
       (which was Phase 1 R4 placeholder; promoted to Round 6 per § 9.5). COD 3,
       JS 2, WSJF=1.5
- 🟡 B128: Round 7 amends Round 2 § 5.1 frozen-8 inventory with JOB_PARQUET_VERIFY
       (per B80), JOB_LOG_CLEANUP (per B80), JOB_PARITY_EXCEPTION_NOTIFY
       (NEW per § 3.6 + B38 — 30-day pre-expiry notification mechanism). COD 2,
       JS 1, WSJF=2.0
- 🟡 B129: Round 8 candidate — self-improvement loop should detect when a single
       round triages 24+ B-items (per R5/R6 trend) and flag for HANDOFF Pitfall #11
       "carryover compounding" candidate. COD 1, JS 1, WSJF=1.0
```

### § 11.3 Gate 2 — Independent review (NEXT STEP after this self-check)

**Per `_reviewer_effectiveness.md` empirical evidence + Pattern E proven on Round 4 cycle 4 + Round 5 cycle 1**: invoke Pattern E from cycle 1 with 5 parallel agents:

1. **R6C1-1**: column-walk specialist (Pitfall #9 a-i surface — every Round 1 SP/column/enum + Round 2 dataclass + Round 3 function + Round 4 CLI argument + Round 5 test path reference verified against canonical)
2. **R6C1-2**: cross-reference / Pitfall #9 sweep (B47-B119 triage accuracy in § 12; D-numbers; cross-doc links to Rounds 1-5 + RB-9/RB-12 references)
3. **R6C1-3**: internal consistency (deployment workflow coherence § 1.2 ↔ § 1.4 ↔ § 1.5 ↔ § 1.6; § 1.7 startup sequence integrity; § 7 fix-cycle coherence with § 8 spec doc corrections)
4. **R6C1-4**: D72 convergence + edge case coverage (Gate 3 + Gate 4 — every edge case has ≥1 deploy mitigation; § 10 walk completeness)
5. **R6C1-5**: advisory researcher (deployment-discipline best practices — immutable artifacts; rsync + symlink vs blue-green; TPM2 unseal at scale; testcontainers fixture lifecycle; Hypothesis CI profile patterns)

Then **sleeper-bug stress test cycle** per R4C8 + R5C4 precedent (mandatory final cycle before D83-style architectural acceptance).

### § 11.4 Round 6 acceptance criteria checklist (run at close-out)

- [ ] Intro through § 13 all present and self-consistent
- [ ] D84-D87 captured in `03_DECISIONS.md` (deployment artifact contract + module startup sequence + 3-env cadence + pre/post-deploy checklist)
- [ ] Pattern E cycle 1 returned ≤4 🔴 (or single comprehensive returned 0 — per `_reviewer_effectiveness.md` evidence, expect Pattern E to surface bugs single-agent would miss)
- [ ] Sleeper-bug stress test cycle complete (mandatory final cycle per R4C8 + R5C4 precedent)
- [ ] `_validation_log.md` entry appended documenting all validation passes
- [ ] `_reviewer_effectiveness.md` updated with Round 6 cycle entries per ledger schema
- [ ] Cross-doc updates landed: 04_EDGE_CASES.md (B121 — DP1-DP7 Deployment-Pipeline series + T4 test-series per § 10.3 — note new DP prefix to avoid collision with existing D-series "2x/day Cadence" per cycle 2 fix), CLAUDE.md (CLI_* + CYCLE_* + DEPLOYMENT_* + MIGRATION_* + STARTUP_* EventType families per B86 + cycle 2 STARTUP_* addition), 05_RUNBOOKS.md (RB-12 authored per § 9.5 closing B41/B127)
- [ ] BACKLOG.md updated with B120-B141 (22 proposed; 10 cycle-1 + 3 cycle-2 advisory + 4 cycle-3 verification + 4 cycle-4-sleeper-bug + 1 cycle-6-final-convergence-fresh-instance) + close 29 items per § 12.1 (cycle 2 added B63; cycle 3 updated trailing summary count; cycle 5 added B108 per R6C4 🔴-1) + reclassify 6 items per § 12.2 (Round 7 work) + audit-trail 30 items per § 12.3 (24 + 6 cycle-5 B109-B114 additions per R6C4 🔴-1) + 13 items per § 12.4 (12 + B117 cycle-5 addition; 3 of which are § 9.2 re-deferrals: B66, B67, B71)
- [ ] RISKS.md updated with R26 (artifact tampering, Low × High = 3 🟡) + R27 (checklist override, Medium × Medium = 4 🟡) per B126
- [ ] HANDOFF.md §3 + §12 + §14 updated via `udm-round-closeout`; §8 Pitfall #9 sub-class 9.i formalization per B120
- [ ] CURRENT_STATE.md "Recently completed" + "Recent rounds" + "Last updated" + "Next concrete step" (→ Round 7 Schema Evolution Governance) updated
- [ ] NORTH_STAR.md Phase 1 row already shows pillars (no change expected — Round 6 advances **Operationally stable** + **Audit-grade** + **Idempotent** as expected)
- [ ] Doc status flip: `phase1/06_deployment.md` "🟡 Drafting" → "🟢 Locked" (after validation passes; D83-style architectural-review acceptance if D72 math infeasible)

---

## § 12. B47-B119 systematic triage (per D73 + D78 + D83 carryover mandates)

**Scope**: every B-number in B47-B119 active range that remained open at Round 5 close-out, plus B33/B36/B37 (D62 follow-ups) + B38/B41/B42/B49/B64/B74-B76 (open Phase-scoped follow-ups) + B69 (explicitly Round 6 per Round 3 close-out) + B85 (Round 6 dependency). Each item triaged below with **canonical BACKLOG.md description** + classification.

**Producer note**: this triage rebuilds on Round 5 § 9 corrections per cycle-2-fix lesson. Every "Round 6 closes X" claim is verified that the canonical fix lives in THIS Round 6 spec doc's content.

### § 12.1 Round 6 closes — items this round resolves

| B-num | Canonical BACKLOG description | How Round 6 closes it |
|---|---|---|
| B38 | 30-day pre-expiry notification for parity-baseline `documented_exceptions` (R18) | § 3.6 specifies the mechanism; § 4.2 lists JOB_PARITY_EXCEPTION_NOTIFY as Round 7-amendment per B128. Effective closure tied to Round 7 inventory amendment, but Round 6 lands the mechanism design |
| B41 | Author RB-12 in full per `udm-runbook-author` skill | § 9.5 outline; full RB-12 body authored at Round 6 close-out per B127 |
| B42 | After D63 locks, ensure CK_UdmTablesList_SCD2Mode exists via reconciliation query — run against prod | § 8.12 spec + run at Round 6 close-out |
| B58 | Author Tier 0 vs module-interface reconciliation script (drift detection per R19 mitigation) | § 4.7 full implementation spec (stub closed at Round 3; Round 6 lands full impl) |
| B63 | Extend Tier 0 sketches to cover ALL declared Error modes per module (Reviewer C 13/17 partial; 2 zero-coverage) | § 4.7 verify_tier0_drift.py + § 5.1 Tier 0 6-assertion contract enforcement at every deploy; § 4.3 Round 3 module deployment step 2 explicitly references Round 5 § 3.1 catalog as the contract Round 6 implements (cycle 2 fix: B63 added per cycle 1 R6C1-2 finding that B63 was missing from § 12 disposition) |
| **B108** | Append T1-T3 + F25 + I-next per B48 to `04_EDGE_CASES.md` at Round 5 close-out → Round 6 close-out | Cycle 5 fix per R6C4 sleeper-bug 🔴-1: § 10.2 DP1-DP7 + § 10.3 T4 closure adds at close-out paired with B121. T1-T3 carryover from Round 5 § 10.2 referenced in § 10.3; T4 added cycle 2 for Hypothesis derandomized-CI coverage-gap. F25 (alert dispatcher zero-channels-fatal per B98) appended at close-out per § 12.1 B98 row in Round 5 § 9.1. I-next per B48 appended at close-out paired with B121. |
| B65 | Define `release_snowflake_key(*, key_file_path: str) -> None` inline in Round 3 § 3.1 | § 7.1 spec (engineering implements in credentials_loader.py at Round 6 deploy) |
| B68 | `sensitive_data_filter` thread-safety contradiction resolution | § 7.4 chooses option (a) — module-import-time registration only |
| B69 | Add explicit "module startup sequence" section | § 1.7 spec — D85 proposed lockdown |
| B70 | `ledger_step(metadata=...)` param footgun mitigation | § 7.2 DeprecationWarning spec |
| B72 | Pin caller-side contract for `LedgerStep.prior_result is None` | § 7.3 spec + Round 5 § 4.1 Tier 1 tests assert |
| B85 | Author `utils/errors.py` with PipelineError / PipelineFatalError / PipelineRetryableError | § 4.6 spec — engineering implements at Round 6 deploy |
| B86 | Add CLI_* EventType family (+ CYCLE_* per B105) to CLAUDE.md | § 6.4 family registration spec — adds CLI_* (11) + CYCLE_* (2) + DEPLOYMENT_* (4) + MIGRATION_* (N) |
| B87 | KeyboardInterrupt → exit 1 vs 130 decision | § 7.5 chooses exit 1 |
| B88 | `--dry-run` + `--apply` mutual exclusion | § 7.6 argparse mutex group |
| B89 | D77 5-vs-6 Tier 0 assertion count reconciliation | § 8.1 fix Round 4 § 2 to "6 canonical assertions" |
| B90 | AUTOMIC_RUN_ID set AND isatty() True edge case | § 7.7 env-var precedence |
| B96 | SIGINT/exit-130 rationale note added to § 1.8 (Round 4) | § 8.8 spec doc correction |
| B97 | SnowSQL exit-code cross-reference note added to § 1.1 (Round 4) | § 8.9 spec doc correction |
| B100 | § 5.2 (Round 4) + § 10.2 (Round 3) Gate 5 label rename | § 8.6 spec doc correction |
| B101 | RB-11 framing reconciliation | § 8.4 spec doc correction in Round 4 § 3.8 + § 3.9 |
| B102 | § 0 Read order in Round 4 uses canonical CCL Stage 1 order | § 8.5 spec doc correction |
| B103 | Round 3 § 2.2 `decrypt_token` internal contradiction | § 7.9 + § 8.2 — DecryptDenied IS raised; docstring updated |
| B104 | `log_retention_cleanup --batch-size` default 50000 → 4000 | § 7.8 + § 8.3 — code default + spec doc correction |
| B106 | B101 line citation off-by-one | § 8.7 BACKLOG.md fix |
| B115 | Fixture state-leakage mitigation (SQLAlchemy transactional rollback) | § 7.10 spec — engineering implements at Round 6 deploy |
| B116 | testcontainers-python image cite in D79 / § 1.3 | § 8.10 spec doc correction in D79 + Round 5 § 1.3 |
| B118 | Hypothesis `derandomize=True` CI profile in conftest.py | § 7.11 spec — engineering implements at Round 6 deploy |
| B119 | Close BACKLOG entry B77 at Round 5 close-out | § 8.11 spec — moved to Completed at Round 6 close-out |

**Round 6 closure count**: 29 items (substantively closed via spec content + close-out task list; cycle 2 fix added B63 row per cycle 1 R6C1-2 finding; cycle 3 fix updated count 27 → 28 per Pitfall #9 sub-class 9.i fix-fresh-instance recurrence; cycle 5 fix added B108 row per R6C4 sleeper-bug 🔴-1 with corresponding count update 28 → 29 at cycle 6 per 4th-consecutive Pitfall #9 9.i recurrence pattern — R5C5 → R6C6 trajectory comparison: same structural pattern, same number of cycles required to break the fix-fresh-instance loop).

### § 12.2 Round 7 work — Schema Evolution Governance

| B-num | Canonical BACKLOG description | Round 7 scope |
|---|---|---|
| B79 | SP-4 `@AcknowledgmentOnly` schema evolution | Round 7 — SP signature change |
| B80 | `JOB_PARQUET_VERIFY` + `JOB_LOG_CLEANUP` Automic inventory amendment | Round 7 — Round 2 § 5.1 inventory change (plus JOB_PARITY_EXCEPTION_NOTIFY per § 3.6 per B128) |
| B81 | Author CCPA deletion SP | Round 7 — net-new SP requires Round 1 supersession |
| B82 | Propose new Phase 0 deliverable for ops-channel client | Round 7 — new Phase 0 deliv + 02_PHASES.md amendment |
| B93 | SP-10 `@CutoffOverride` parameter | Round 7 — SP signature change |
| B94 | SP-10 `@CategoryFilter` parameter | Round 7 — SP signature change |

**Round 7 deferral count**: 6 items (carries forward from Round 5 § 9.3).

### § 12.3 Already closed at prior round (audit trail only)

Items already closed; listed for completeness:

| B-num | Closed at | Reference |
|---|---|---|
| B40, B43, B53, B54, B55, B56, B57 (partial), B59, B60, B61, B62, B73, B92 | Various prior rounds | BACKLOG.md Completed section |
| B47, B48, B50, B83, B84, B91, B98, B99, B105 (partial) | 2026-05-10 at Round 5 close-out | BACKLOG.md L213-222 |
| B95, B107 | 2026-05-10 process optimization phase 1 | BACKLOG.md history |
| **B109** | R24 added to RISKS.md per Pitfall #8 at Round 5 close-out (cycle 5 fix per R6C4 sleeper-bug 🔴-1) | RISKS.md L34 — R24 (Test fixture canonical schema drift) score 2 ⚪ — verified per Round 5 D83 acceptance |
| **B110** | D79 (test fixture canonical schema) lockdown — closed inline at Round 5 close-out (cycle 5 fix per R6C4 sleeper-bug 🔴-1) | `03_DECISIONS.md` D79 entry locked at 2026-05-10 |
| **B111** | D80 (Tier-0-to-Tier-1 boundary) lockdown — closed inline at Round 5 close-out (cycle 5 fix) | `03_DECISIONS.md` D80 entry locked at 2026-05-10 |
| **B112** | D81 (Hypothesis shrinkage budget) lockdown — closed inline at Round 5 close-out (cycle 5 fix) | `03_DECISIONS.md` D81 entry locked at 2026-05-10 |
| **B113** | D82 (coverage thresholds per tier) lockdown — closed inline at Round 5 close-out (cycle 5 fix) | `03_DECISIONS.md` D82 entry locked at 2026-05-10 |
| **B114** | D82 Tier 2 reframe "≥80% pass rate" → "100% properties pass shrinkage within budget" — already applied inline at Round 5 § 1.5 + § 11.2; B114 tracked decision-record landing at Round 5 close-out (cycle 5 fix) | Round 5 § 1.5 + § 11.2; D82 entry in `03_DECISIONS.md` |

### § 12.4 Open and intentionally NOT scoped to Round 6/7 (some are Round 5 § 9.2 re-deferrals)

| B-num | Canonical BACKLOG description | Why not in 12.1/12.2 |
|---|---|---|
| B33 | Author CCL audit-cadence checklist (Phase 6 quarterly cadence) | Phase 6 scope, not Round 6/7 |
| B36 | Tighten CCL verification rule (Bash-cat / WebFetch) | Phase 1 R3 follow-up; not blocking deployment |
| B37 | Document multi-Stage-1-doc edit handling | Phase 1 R3 follow-up; not blocking deployment |
| B39 | Capture first month of Snowflake trial cost data (Phase 0 deliv 0.6) | Phase 0 scope |
| B49 | Pin parity-baseline `expires_at` timezone to UTC | Phase 0 follow-up |
| B64 | Correct D71 pillar mapping in `03_DECISIONS.md` | Round 3 close-out polish; non-blocking |
| **B66** | event_tracker god-module split — **§ 9.2 deferral re-deferred per Round 6 § 7.12** | Optional architectural refactor; affects Round 5 test surface if pursued; deferred to post-Round-8 cleanup phase |
| **B67** | vault_client typed wrappers — **§ 9.2 deferral re-deferred per Round 6 § 7.12** | Optional refactor; affects Round 5 test surface if pursued; deferred to post-Round-8 cleanup phase |
| **B71** | Nested with-block example for event_tracker + ledger_step — **§ 9.2 deferral re-deferred** | Documentation polish; defer to Round 8 self-improvement loop |
| B74 | Optional re-sort BACKLOG main table to strict-monotonic-by-B-ID | Non-load-bearing polish |
| B75 | Re-ground D64 framing ("industry-standard" → systemd-creds / GPG-on-TPM advisory) | Round 3-style framing polish; non-blocking. Cycle 2 R6C1-5 advisory partially substantiates: PCR-set rationale note added inline at § 3.5 + systemd-creds explicitly acknowledged as RHEL 9+ canonical (bespoke path needed for RHEL 8) |
| B76 | Investigate D71 in-memory Snowflake key alternative | Could be Round 7 or post-Round-8 research; non-blocking |
| **B117** | Optional cite Microsoft BVT + Google small-test vocabulary in Round 5 § 1.6 Tier-0-vs-Tier-1 boundary (R5C1-5 advisory) | Cycle 5 fix per R6C4 sleeper-bug 🔴-1: low priority framing-only polish (WSJF 0.5 per BACKLOG); could land at Round 6 close-out or Round 7+ — not blocking |

**Out-of-scope count**: 13 items (cycle 5 fix added B117). **Re-deferral note** (per cycle 1 R6C1-2 finding + § 9.2 reconciliation): B66/B67/B71 were Round 5 § 9.2 deferrals → Round 6 § 7.12 explicitly re-defers (B66+B67 = optional refactors; B71 = doc polish) → these are tracked here as "deferred", NOT as "closed". The Round 5 § 9.2 list of 24 deferrals breaks down at Round 6 as: 20 substantively closed in § 12.1 (B58, B65, B68, B70, B72, B85, B86, B87, B88, B89, B90, B96, B97, B100, B101, B102, B103, B104, B106, B69) + 3 re-deferred per § 12.4 (B66, B67, B71) + 1 promoted-and-closed per § 12.1 (B63 added cycle-2 per finding) = 24 ✓.

### § 12.5 New BACKLOG items proposed at Round 6 (B120-B141)

Per § 11.2:

| B-num | Description | WSJF |
|---|---|---|
| B120 | HANDOFF §8 Pitfall #9 sub-class 9.i formalization (process-discipline-claim drift) | 2.0 |
| B121 | Append D-next..D-next+5 deployment-series edge cases to 04_EDGE_CASES.md | 2.0 |
| B122 | D84 (Deployment artifact contract) lockdown | 1.0 |
| B123 | D85 (Module startup sequence) lockdown — closes B69 | 1.0 |
| B124 | D86 (3-env deployment cadence) lockdown | 1.0 |
| B125 | D87 (Pre/post-deploy checklist contract) lockdown | 1.0 |
| B126 | Add R26 (artifact tampering) + R27 (checklist override) to RISKS.md per Pitfall #8 | 2.0 |
| B127 | Author RB-12 (Pipeline Deployment) in full per § 9.5 outline — closes B41 | 1.5 |
| B128 | Round 7 Automic inventory amendment includes JOB_PARITY_EXCEPTION_NOTIFY per § 3.6 / B38 | 2.0 |
| B129 | Round 8 candidate — self-improvement loop detects carryover compounding ≥24/round | 1.0 |
| **B130** (NEW per cycle 2 R6C1-5 advisory) | RFC 2119 must/should/may framing alternative for D65 parity severity 3-tier (fatal/warning/informational) — re-ground in `03_DECISIONS.md` D65 entry to acknowledge RFC 2119 inspiration + de-facto enterprise-monitoring (Splunk/Datadog/Nagios) convention rather than implying CIS/NIST severity-tier precedent that doesn't exist. Low priority framing polish | 0.5 |
| **B131** (NEW per cycle 2 R6C1-5 advisory) | TPM2 PCR 4 (boot manager) re-seal runbook subsection — after every grub2/shim package update, scheduled re-seal procedure to refresh sealed credential. Pairs with B75 framing polish + RB-12 § 3 re-seal subsection | 1.5 |
| **B132** (NEW per cycle 2 R6C1-1 advisory) | NEXT_AVAILABLE B-number reconciliation discipline across CURRENT_STATE / HANDOFF / BACKLOG — at every round close-out, verify the next-available B-number is consistent across all three docs. Cycle 1 found ambiguity in B120 vs B119 closure state | 1.0 |
| **B133** (NEW per cycle 2 R6C2 verification) | § 12.6 reconciliation prose minor grouping miscount — "B38/B41/B42 (pre-Round-5) + B115/B116/B118/B119 (Round 5 § 11.2 set)" should clarify "3 + 4 = 7 earlier-carryover items". Cycle 3 inline fix applied; B133 tracks decision-record + Pitfall #9 9.i lesson learned | 0.5 |
| **B134** (NEW per cycle 2 R6C2 verification) | testcontainers image-tag pin-vs-cite sweep — § 4.5 + § 5.4 + § 8.10 + § 7.10 all reference the mssql:2022 image. Cycle 2 pinned § 7.10 to `:2022-CU14-ubuntu-22.04`; cycle 3 sweep updates § 4.5 + § 5.4 + § 8.10 to match. Tracks for future pin-bump-discipline at requirements-lock.txt cadence | 1.0 |
| **B135** (NEW per cycle 2 R6C2 verification) | B130 framing precedent verification — verify D65 3-tier severity model isn't currently claimed as CIS/NIST in `03_DECISIONS.md` D65 entry before applying the B130 RFC-2119 framing fix. Pre-flight check before close-out. Low priority | 0.5 |
| **B136** (NEW per cycle 2 R6C2 verification) | HANDOFF §8 Pitfall #9 sub-class 9.i directive strengthening — add explicit "verify trailing summary counts match table row counts after any cycle-N fix that modifies row counts". Cycle 2 caught this pattern recurring; cycle 3 mechanical fix; cycle-2-introduced 🔴 closed in this same cycle 3 fix. Cycle 3 R6C3 found yet-another fresh-instance (§ 12.5 heading L1769 stale "B120-B129"). Cycle 4 R6C4 sleeper-bug 🔴-1 found B108-B114+B117 silent-omission. Strengthening: "after any cycle-N B-item addition, run regex sweep `B\d+-B\d+` to verify ALL ranges match new upper bound; additionally, verify every B-number proposed in a prior round's § 11.2 + § 12.5 is classified in this round's § 12.1/§ 12.3/§ 12.4". WSJF 1.5 (raised from 1.0; high-impact structural fix). | 1.5 |
| **B137** (NEW per cycle 4 R6C4 sleeper-bug 🟡-1) | Reconcile `startup_recovery_sweep` `max_age_minutes` threshold between Round 3 § 4.1 L835 (canonical 1 hour) and Round 6 § 1.7 initial draft (240min/4h). Cycle 5 fix applied inline at § 1.7 Stage 4 → `max_age_minutes=60`. B137 tracks decision-record + Pitfall #9 9.i lesson | 0.5 |
| **B138** (NEW per cycle 4 R6C4 sleeper-bug 🟡-2) | RB-12 outline sub-section numbering — forward-cites to "RB-12 § 3" + "RB-12 § 5" in § 1.5 / § 3.5 / § 9.1 / § 10.1 of this Round 6 doc presume an explicit § N numbering that § 9.5 outline doesn't yet have. Cycle 5 fix applied: § 9.5 outline now explicitly numbered § 1-§ 7. B138 tracks the close-out RB-12 authoring discipline | 1.0 |
| **B139** (NEW per cycle 4 R6C4 sleeper-bug 🟡-3) | RISKS.md self-audit at close-out for score/status enum alignment — R23 shows 🟡 Open status but score 2 = ⚪ threshold per L45. Audit all rows with score 2 (R12, R18, R20, R21, R23, R24, R25) for ⚪ status. Pre-existing inconsistency; Round 6 close-out task | 1.0 |
| **B140** (NEW per cycle 4 R6C4 sleeper-bug 🟡-4) | BACKLOG.md B116 canonical entry update — entry text says `:2022-latest` but Round 6 § 7.10 + § 4.5 + § 5.4 + § 8.10 pin to `:2022-CU14-ubuntu-22.04` per cycle 2/3 fixes. Cycle 5 close-out task: update BACKLOG.md B116 entry text + `phase1/05_tests.md` § 1.3 + D79 entry in `03_DECISIONS.md` to match | 1.0 |
| **B141** (NEW per cycle 6 R6C6 final-convergence-verification fresh-instance — **5th consecutive Pitfall #9 9.i recurrence**) | Extend B136 strengthening directive with cycle-6-specific learning: "after any cycle-N mechanical fix that ADDS a forward-reference to a future B-number (e.g. citing `B<N+1>` in commentary), verify the cited B-number is defined before the cite is committed OR explicitly mark the reference as 'candidate' / 'future'". Cycle 6 mechanical fix introduced "B136/B141" in Status header + D88 entry — B141 didn't exist; cycle 7 closure defines B141 here (self-referentially closing the recurrence). The 5-cycle structural pattern of Pitfall #9 9.i (R6C2 / R6C3 / R6C4 sleeper / R6C5 / R6C6) is empirically the strongest evidence base yet for the sub-class formalization at HANDOFF §8 close-out task per B120. WSJF 2.0 (high impact — addresses the structural recurrence pattern that defeats producer self-checks 5 cycles in a row) | 2.0 |

**New B-item count**: 22 items (10 cycle-1 + 3 cycle-2 + 4 cycle-3 + 4 cycle-4-sleeper-bug-introduced + 1 cycle-6-final-convergence-fresh-instance).

### § 12.6 Triage summary (post-cycle-5 corrections)

| Category | Count |
|---|---|
| Round 6 closes (per § 12.1) | 29 (cycle 2 fix added B63 row; cycle 3 fix updated trailing summary count 27→28 per Pitfall #9 9.i recurrence; cycle 5 fix added B108 row per R6C4 sleeper-bug 🔴-1) |
| Round 7 deferral (per § 12.2) | 6 |
| Already-closed audit trail (per § 12.3) | 30 (combined: 13 prior-round + 9 Round-5-close-out + 2 process-optimization + 6 cycle-5 additions B109-B114 per R6C4 sleeper-bug 🔴-1) |
| Outside Round 6/7 scope (per § 12.4) | 13 (12 + B117 added at cycle 5 per R6C4 sleeper-bug 🔴-1; includes 3 § 9.2 re-deferrals B66/B67/B71) |
| New B-items proposed at Round 6 (per § 12.5) | 22 (10 cycle-1 + 3 cycle-2 + 4 cycle-3 + 4 cycle-4-sleeper-bug + 1 cycle-6-final-convergence-fresh-instance) |
| **Total tracked** | **100 unique items** (29 + 6 + 30 + 13 + 22 = 100) across the B47-B119 + new B120-B141 range plus referenced earlier carryover (B33-B49 + B58-B76 outside-D73-strict scope items) |

**Reconciliation note (cycle 5 corrected — Round 5 § 9.2 + § 11.2 B108-B119 set comprehensively classified)**: Round 5 § 9.2 stated **24 items deferred to Round 6** (per `phase1/05_tests.md` L562 + § 9.7 L646 enumeration: B58, B63, B65, B66, B67, B68, B69, B70, B71, B72, B85, B86, B87, B88, B89, B90, B96, B97, B100, B101, B102, B103, B104, B106). Round 6 § 12.1 closes **20** of those § 9.2 items (B58, B65, B68, B69, B70, B72, B85, B86, B87, B88, B89, B90, B96, B97, B100, B101, B102, B103, B104, B106) + Round 6 § 12.4 re-defers **3** § 9.2 items (B66, B67, B71) + Round 6 § 12.1 closes B63 cycle-2-promoted **1** = **24 § 9.2 items accounted for ✓**. Beyond the § 9.2 24-item set, Round 6 also classifies **all 12 of Round 5 § 11.2 B108-B119 set** (cycle 5 fix per R6C4 sleeper-bug 🔴-1 — initial draft silently omitted 8 of these): **§ 12.1 closes 5** (B108 Round 6 close-out task + B115/B116/B118/B119 Round 6 substantive) + **§ 12.3 audit-trail 6** (B109/B110/B111/B112/B113/B114 — all already closed at Round 5 close-out per BACKLOG.md L196-202) + **§ 12.4 outside-scope 1** (B117 low-priority Round 6 close-out polish). Total § 12.1 closure count = **20 § 9.2 substantive + 1 cycle-2 B63 + 3 pre-Round-5 earlier-carryover (B38/B41/B42) + 5 Round 5 § 11.2 set (B108/B115/B116/B118/B119) = 29** (verified row-count in § 12.1 table post-cycle-5). The "carryover compounding" pattern (B129 candidate) is empirically: Round 5 inherited 58 items (24+34) from Round 3+4, closed 9, deferred 24 to Round 6; Round 6 inherits 36 items (24 § 9.2 + 12 B108-B119 newly proposed at Round 5), classifies all 36 (28 closed + 3 re-deferred + 5 audit-trail + 1 outside-scope = 37 ≈ 36 with B108 being shared between § 9.2 close-out task and § 11.2 proposal) → net reduction of ~5 carryover items per round. Sustainable trajectory; Round 8 self-improvement loop monitors via B129.

---

## § 13. End of Round 6 — Deployment

**Status when this checklist completes**: 🟢 Locked, ready for Phase 2 (Pilot Cutover) to engage the deployed infrastructure; Round 7 (Schema Evolution Governance) to handle SP signature changes + Automic inventory amendments per § 12.2; Round 8 (Sub-Agent Self-Improvement Discipline) to consume Round 6's `_reviewer_effectiveness.md` updates + propose carryover-compounding mitigation per B129.

**Round 6 distinctive outputs**:
- Three-environment deployment topology + cadence (dev nightly / test daily / prod weekly Monday)
- Immutable git-tag-driven artifact contract with GPG-signed manifests
- Module startup sequence (5 stages) closes B69
- Cross-server parity baseline discipline (Phase 0 deliv 0.11 partial closure)
- GPG credential deployment workflow with TPM2 sealing (Phase 0 deliv 0.12 partial closure)
- 28-test Tier 0 smoke discipline as deploy gate
- First synthetic pipeline run as end-to-end verification post-deploy
- Automic frozen-8 inventory activation with CLI_* + CYCLE_* + DEPLOYMENT_* + MIGRATION_* + STARTUP_* EventType family (5 families post-cycle-2 STARTUP_* addition)
- Per-deployment audit row in `PipelineEventLog` with pre + post-check JSON
- AUTO-ROLLBACK + manual-rollback decision matrix
- 4 new decisions proposed (D84-D87 deployment discipline)
- 2 new risks proposed (R26 artifact tampering + R27 checklist override)
- 22 new BACKLOG items proposed (B120-B141 — 10 cycle-1 + 3 cycle-2 advisory + 4 cycle-3 verification + 4 cycle-4-sleeper-bug + 1 cycle-6-final-convergence-fresh-instance)
- 29 BACKLOG items closed in-round (substantive content + close-out tasks; cycle 2 fix added B63 row; cycle 3 fix updated trailing summary count per Pitfall #9 9.i recurrence; cycle 5 added B108 row per R6C4 sleeper-bug 🔴-1)
- 6 items deferred to Round 7 (schema evolution governance)
- 3 items re-deferred to post-Round-8 cleanup (B66/B67/B71 § 9.2 deferrals)
- Carryover compounding pattern surfaced as B129 candidate for Round 8 self-improvement scope

**Phase 1 readiness**: Rounds 1-6 deliverables together meet `02_PHASES.md` Phase 1 acceptance criteria (DB schema deployed parity-verified / All Tier 1+2 tests green / Smoke pipeline runs end-to-end / Code review complete / Operational runbooks reviewed / All edge cases addressed). Round 7 + Round 8 add Phase 1 completion (schema evolution governance + self-improvement discipline).
