# R1C1-5 Advisory Research

## Date: 2026-05-12
## Confidence: MEDIUM (SELinux finding HIGH; others MEDIUM-LOW due to no external authority specifying exact checklist counts)
## Question: External grounding for `phase2/01_pilot_prerequisites.md` — does the doc match industry-standard practices?
## Anchor: Pattern E cycle 1, R1C1-5 advisory researcher slot. Artifact: `phase2/01_pilot_prerequisites.md` (~30 KB, Tier β, 2026-05-12).

---

## 🔴 BLOCKING-class concerns (claims that contradict industry-standard practice)

### 🔴-1: `restorecon -v` alone is insufficient for `/etc/pipeline/.env` — a `semanage fcontext` rule must be defined first

**Doc claim** (§ 4.1): the `.env` migration procedure includes `restorecon -v /etc/pipeline/.env` as the SELinux restore step, with no preceding `semanage fcontext -a` call.

**External authority**: Red Hat Enterprise Linux documentation (RHEL 6 + 7 + RHEL 9 practitioner guidance) is explicit that `restorecon` resolves the correct label by looking up rules in `/etc/selinux/targeted/contexts/files/`. For a **new, non-standard path** like `/etc/pipeline/` that is not in the default shipped file-context policy, there is no rule to resolve — so `restorecon` either silently applies a generic fallback label (`etc_t`) or does nothing meaningful. The canonical RHEL pattern is a two-step:

```
sudo semanage fcontext -a -t <type> "/etc/pipeline(/.*)?"
sudo restorecon -Rv /etc/pipeline/
```

**Contradiction**: The doc omits the `semanage fcontext` step entirely. On a fresh RHEL system, `/etc/pipeline/` is not in the default file-context policy (unlike `/etc/httpd/conf.d/` or `/var/www/html/` which are). Running `restorecon -v /etc/pipeline/.env` without first registering a policy rule produces no meaningful label change — the file gets or retains a generic `etc_t` label, which may not correctly confine the pipeline service user.

**Severity justification**: D103 is the security model foundation. SELinux Layer 11 is cited as one of the 13 layers of defense-in-depth. A `restorecon` call that silently fails to apply the right label is an audit-grade (pillar 1) and operationally-stable (pillar 4) defect — the operator believes SELinux is correctly confining the `.env` file when it may not be.

**Sources**:
- Red Hat docs (RHEL 6): https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/6/html/security-enhanced_linux/sect-security-enhanced_linux-selinux_contexts_labeling_files-persistent_changes_semanage_fcontext
- RHEL 7 SELinux labeling guide: https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/7/html/selinux_users_and_administrators_guide/sect-security-enhanced_linux-working_with_selinux-selinux_contexts_labeling_files
- Red Hat blog "Four semanage commands to keep SELinux in enforcing mode": https://www.redhat.com/en/blog/semanage-keep-selinux-enforcing
- Practitioner RHEL 9 guidance (2026-03): https://oneuptime.com/blog/post/2026-03-04-restorecon-fix-selinux-file-labels-rhel-9/view
- semanage fcontext + restorecon explained: https://linuxcert.guru/blog/?name=semanage-fcontext-restorecon

**Recommended fix for RB-14**: Add `semanage fcontext -a -t <service_type> "/etc/pipeline(/.*)?"` before the `restorecon -Rv /etc/pipeline/` call. The type (`etc_t` or a custom pipeline-specific type) should be confirmed with the RHEL sysadmin against the environment's policy. The `-v` flag is fine to keep for operator visibility but is not the load-bearing part.

---

## 🟡 Grounding-class concerns (claims that lack external citation but are project-specific-defensible)

### 🟡-1: Deployment ladder (dev → test → prod with check-pause-check) is consistent with Continuous Delivery canon — no citation needed but one would strengthen D86/D87

**Doc claims** (§ 4.6, § 5): the 3-environment ladder with dev nightly → test daily + 4h soak → prod weekly Monday window (D86) plus pre-deploy 12-check + post-deploy 10-check (D87) is used throughout.

**External grounding check**: Jez Humble and David Farley's "Continuous Delivery" (Addison-Wesley, 2010) is the canonical authority on deployment pipelines. The book defines the deployment pipeline as a progression through environments with automated checks at each gate — directly analogous to dev → test → prod with pre/post checks. The "check-pause-check" framing (per the doc: run checks, pause for soak, run checks again before promoting) is not a branded CD term but it maps cleanly to Humble/Farley Chapter 5 "Anatomy of the Deployment Pipeline" — specifically the concept of commit stage + acceptance-test stage + UAT stage as discrete gates.

**Conclusion**: The pattern is consistent with industry canon. No external citation exists for "check-pause-check" as a named pattern, but the underlying concept (staged promotion with automated gates + soak period) is well-supported by Humble/Farley. The absence of a citation is a 🟡, not a 🔴 — the pattern is defensible on its own merits.

**Sources**:
- Humble/Farley "Continuous Delivery" canonical reference: https://www.oreilly.com/library/view/continuous-delivery-reliable/9780321670250/
- Microsoft "best practices for dev/test/prod environments" (aligned): https://learn.microsoft.com/en-us/answers/questions/1355586/best-practices-for-managing-dev-test-and-prod-envi
- Bunnyshell "Dev, Test, Prod best practices 2025" (industry practitioner): https://www.bunnyshell.com/blog/best-practices-for-dev-qa-and-production-environments/

### 🟡-2: Pre-check count (12) and post-check count (10) are project-defined — not derived from any external standard

**Doc claims** (§ 3, § 5): "12 pre-checks per D87" and "10 post-checks per D87". The acceptance gate (§ 6 row 8) mentions "66 checklist-line audit notes" (3 servers × 22 checks).

**External grounding check**: Industry deployment checklists (Octopus Deploy "16-step deployment checklist", DeployHQ "ultimate deployment checklist", LaunchDarkly "release management checklist") confirm that pre/post deployment checklists are a universal best practice, but the specific counts (12/10) are not derived from any standard — they are project-specific. Octopus's canonical deployment checklist has 16 steps total; the project's split of 12+10 = 22 across two phases is entirely reasonable and within the range observed in real-world runbooks.

**Conclusion**: The counts are defensible as project-specific. No external authority mandates a specific count. This is a 🟡 because a claim like "the 12 pre-checks from `phase1/06_deployment.md` § 5" is an internal cross-reference, not a claim that 12 is an industry-canonical number. The doc does not make the latter claim, so no correction is needed. Noted here for completeness.

**Sources**:
- Octopus Deploy "Ultimate 16-step Deployment Checklist": https://octopus.com/devops/software-deployments/deployment-checklist/
- DeployHQ "Ultimate Deployment Checklist": https://www.deployhq.com/blog/the-ultimate-deployment-checklist-ensuring-smooth-and-successful-releases
- Cortex "2024 Software Release Checklist": https://www.cortex.io/post/software-release-checklist

### 🟡-3: Migration script idempotency pattern (`IF NOT EXISTS` ALTER) is consistent with SQL Server canon — no contradiction, but no explicit Microsoft Learn citation in the doc

**Doc claims** (§ 4.4): "idempotent (`IF NOT EXISTS` guard on every DDL statement)" for B193/B194/B195 migration scripts.

**External grounding check**: Microsoft Learn's "Managing Migrations - EF Core" documentation endorses idempotent migration scripts ("it should be safe to re-run the same migration multiple times") and the pattern of checking current state via `sys` metadata views or `INFORMATION_SCHEMA.COLUMNS` before applying DDL is standard SQL Server practice. The `IF NOT EXISTS` guard on `ALTER TABLE ... ADD COLUMN` specifically is endorsed by community-canonical sources (DZone "Trouble-Free Database Migration" article, SQLdef tooling). Microsoft's ALTER TABLE (Transact-SQL) documentation does not explicitly demonstrate the `IF NOT EXISTS` pattern for column adds (it is a T-SQL idiom via `COL_LENGTH` or `COLUMNPROPERTY` checks), but the underlying principle of idempotent DDL is unambiguously endorsed.

**Conclusion**: The pattern is industry-canonical. No 🔴; the doc is consistent with best practice. Adding a Microsoft Learn citation would strengthen D92 forward-only schema evolution claims in future gates.

**Sources**:
- Microsoft Learn "Managing Migrations - EF Core": https://learn.microsoft.com/en-us/ef/core/managing-schemas/migrations/managing
- DZone "Trouble-Free Database Migration: Idempotence": https://dzone.com/articles/trouble-free-database-migration-idempotence-and-co
- SQL Server ALTER TABLE docs: https://learn.microsoft.com/en-us/sql/t-sql/statements/alter-table-transact-sql?view=sql-server-ver16

### 🟡-4: Synthetic-data smoke test approach (§ 4.7) is consistent with industry-standard pipeline smoke-test patterns

**Doc claims** (§ 4.7): insert one synthetic row into a test-only staging table, run the pipeline, verify event log and gate-table, tear down — a "synthetic data smoke test" before touching real data.

**External grounding check**: Industry-standard data pipeline testing guidance explicitly endorses this pattern. Dagster's canonical blog post "Smoke Test Your Data Pipelines First" (2024) defines the pattern as "run all your data transformations on empty or synthetic data" before deploying to production. CircleCI's smoke testing guidance defines smoke tests as "lightweight validations that run before deployment to ensure basic functionality" and endorses synthetic inputs. The doc's approach (synthetic row → pipeline invocation → event log verification → teardown) is a textbook implementation of this pattern.

**Conclusion**: The approach is well-supported. No 🔴; no external contradiction found.

**Sources**:
- Dagster "Smoke Test Your Data Pipelines First": https://dagster.io/blog/smoke-test-data-pipeline
- CircleCI "Smoke testing in CI/CD pipelines": https://circleci.com/blog/smoke-tests-in-cicd-pipelines/
- Atlan "Testing Data Pipelines 2025": https://atlan.com/testing-data-pipelines/

### 🟡-5: R02 throwaway-spike pattern (~500 lines + archive-but-don't-deploy) is consistent with XP spike methodology — the canonical source should be cited

**Doc claims** (§ 4.8): "~500 lines of throwaway Python in `_spike_round_0_5/`"; "throwaway code archived but not deployed"; "lessons-learned captured in `_spike_round_0_5/findings_2026-MM-DD.md` for future reference".

**External grounding check**: This is textbook XP spike methodology per Kent Beck and James Shore. James Shore's "The Art of Agile Development" (canonical spike chapter) states explicitly: "I discard the spikes I create to clarify a technical question. Never copy spike code into production code. Even if it is exactly what you need, rewrite it using test-driven development so that it meets your production code standards." The exception noted is spikes demonstrating *how* to do something may be preserved in a `spikes/` directory as reference material — which is exactly what `_spike_round_0_5/findings_*.md` does.

**Conclusion**: The doc's spike treatment is well-aligned with XP canon. The 🟡 is that the doc doesn't cite this external authority — a reference to Beck XP / Shore AOAD would strengthen the R02 section's credibility, especially since D47 only cites the internal `phase1/03_round_0_5_spike_plan.md`.

**Sources**:
- James Shore "The Art of Agile Development: Spike Solutions": https://www.jamesshore.com/v2/books/aoad1/spike_solutions (explicit: "never copy spike code into production")
- Agile Alliance XP glossary: https://agilealliance.org/glossary/xp/
- Mountain Goat Software "What Are Agile Spikes?": https://www.mountaingoatsoftware.com/blog/spikes

### 🟡-6: POLISH_QUEUE skim during post-checks (§ 5 post-check #10) has no external analog but is internally coherent

**Doc claims** (§ 5, post-check 10): "POLISH_QUEUE skim: skim P-1/P-2/P-3/P-4/P-6/P-7 — close any whose underlying cosmetic drift was incidentally cleaned up by this sub-step's work per D113."

**External grounding check**: No external industry framework uses a "POLISH_QUEUE" construct. The closest analog is the concept of a "technical debt ledger" or "cosmetic backlog" in Agile (Scrum.org "Product Backlog and Technical Debt", Martin Fowler's "Technical Debt" bliki). The separation of cosmetic/non-load-bearing items from the main backlog (P-numbers vs B-numbers per D113) is a project-specific discipline. No external authority contradicts it; it is simply a project-specific innovation not covered by any external standard.

**Conclusion**: The discipline is defensible and internally coherent per D113. The absence of external grounding is expected — D113 is a project-local process invention. Including this step in post-checks is analogous to the "backlog grooming" step found in Agile release checklists (remove resolved items). Not a 🔴; flagged as 🟡 for transparency that no external citation supports or contradicts this specific mechanism.

**Sources**:
- Scrum.org "The Product Backlog and Technical Debt": https://www.scrum.org/resources/blog/product-backlog-and-technical-debt
- Backlog refinement best practices: https://www.easyagile.com/blog/backlog-refinement/

---

## Citations / sources consulted

| # | URL | Date accessed | Authority |
|---|---|---|---|
| 1 | https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/6/html/security-enhanced_linux/sect-security-enhanced_linux-selinux_contexts_labeling_files-persistent_changes_semanage_fcontext | 2026-05-12 | Red Hat (vendor primary) |
| 2 | https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/7/html/selinux_users_and_administrators_guide/sect-security-enhanced_linux-working_with_selinux-selinux_contexts_labeling_files | 2026-05-12 | Red Hat (vendor primary) |
| 3 | https://www.redhat.com/en/blog/semanage-keep-selinux-enforcing | 2026-05-12 | Red Hat (vendor blog) |
| 4 | https://oneuptime.com/blog/post/2026-03-04-restorecon-fix-selinux-file-labels-rhel-9/view | 2026-05-12 | Community (RHEL 9 practitioner, 2026) |
| 5 | https://linuxcert.guru/blog/?name=semanage-fcontext-restorecon | 2026-05-12 | Community (practitioner) |
| 6 | https://man7.org/linux/man-pages/man8/restorecon.8.html | 2026-05-12 | Linux man page (authoritative) |
| 7 | https://www.oreilly.com/library/view/continuous-delivery-reliable/9780321670250/ | 2026-05-12 | Jez Humble / David Farley (canonical CD text) |
| 8 | https://octopus.com/devops/software-deployments/deployment-checklist/ | 2026-05-12 | Octopus Deploy (industry practitioner) |
| 9 | https://learn.microsoft.com/en-us/ef/core/managing-schemas/migrations/managing | 2026-05-12 | Microsoft Learn (vendor primary) |
| 10 | https://learn.microsoft.com/en-us/sql/t-sql/statements/alter-table-transact-sql?view=sql-server-ver16 | 2026-05-12 | Microsoft Learn (vendor primary) |
| 11 | https://dzone.com/articles/trouble-free-database-migration-idempotence-and-co | 2026-05-12 | DZone (community engineering) |
| 12 | https://dagster.io/blog/smoke-test-data-pipeline | 2026-05-12 | Dagster (data pipeline tooling vendor) |
| 13 | https://circleci.com/blog/smoke-tests-in-cicd-pipelines/ | 2026-05-12 | CircleCI (CI/CD vendor) |
| 14 | https://www.jamesshore.com/v2/books/aoad1/spike_solutions | 2026-05-12 | James Shore "Art of Agile Development" (XP canonical) |
| 15 | https://agilealliance.org/glossary/xp/ | 2026-05-12 | Agile Alliance (canonical body) |
| 16 | https://www.mountaingoatsoftware.com/blog/spikes | 2026-05-12 | Mountain Goat Software / Mike Cohn (Agile practitioner) |
| 17 | https://www.scrum.org/resources/blog/product-backlog-and-technical-debt | 2026-05-12 | Scrum.org (canonical body) |

---

## Summary for producer agent

**One blocking finding** (🔴-1): `restorecon -v` alone in RB-14 § 4.1 is insufficient for the non-standard `/etc/pipeline/` path. RHEL canonical guidance requires `semanage fcontext -a` to register a policy rule before `restorecon` can apply the correct label. Without the `semanage` step, `restorecon` may silently apply a generic `etc_t` label that does not correctly confine the pipeline service. This is a D103 / Layer-11 (SELinux) correctness defect.

**Five grounding concerns** (🟡-1 through 🟡-6): all project choices are industry-defensible; the gaps are missing external citations, not contradictions. The deployment ladder pattern, idempotent migration patterns, synthetic smoke test, and spike methodology are all consistent with canonical external sources. The POLISH_QUEUE mechanism is project-local with no external contradiction.

**Recommended action**:
1. Fix RB-14 (in `05_RUNBOOKS.md`) to add `semanage fcontext -a -t <type> "/etc/pipeline(/.*)?"` before the `restorecon` call. This is a 🔴 and blocks the Gate 2 QA check. The R1 spec doc (§ 4.1) cites RB-14 — the fix lands in the runbook, not in this spec, but the spec's acceptance criteria for § 4.1 depend on RB-14 being correct.
2. Optionally (🟡, non-blocking): add citations to D47/R02 section referencing XP spike methodology (James Shore AOAD); this would strengthen the decision trail for the "archive but don't deploy" claim.
