# Round 2 Cycle 1 — External Evidence (Reviewer R2-5, Pattern E 5th slot)

**Date**: 2026-05-10
**Reviewer**: R2-5 (research specialist, advisory only — does not contribute to D72 consecutive-clean count)
**Artifact under review**: `phase1/02_configuration.md` (Round 2 — Configuration)
**Decisions under research**: D64 (GPG/TPM2), D65 (parity severity tiers), D66 (Automic gate-table), D71 (Snowflake key file), plus § 3.1 (multi-recipient GPG envelope) and § 4 (parity baseline JSON).
**Output convention**: per `udm-researcher` agent definition — Summary, Sources, Findings, Recommendation, Confidence.

---

## Q1. D64 — TPM2 sealed-against-PCR-set for unattended-service GPG passphrase on RHEL

### Summary

**TPM2 sealed-against-PCR-set is well-grounded as a current pattern on RHEL** for unattended-service secret storage, but the spec's framing as "industry-standard for GPG passphrase specifically" is one step removed from authoritative recommendations. Red Hat / systemd / GnuPG documentation supports two adjacent, more idiomatic patterns: (a) **systemd-creds with `--with-key=tpm2` + PCR binding** for service credentials in general, and (b) **moving the GPG key into the TPM directly via GnuPG 2.3+** (eliminating the passphrase storage problem). Either is more defensible than "seal the GPG passphrase against PCRs" as a standalone pattern. **Confidence: 🟡** — recommend tightening D64's framing.

### Sources

| URL | Date accessed | Authority |
|---|---|---|
| https://systemd.io/CREDENTIALS/ | 2026-05-10 | Vendor (systemd) — high |
| https://gnupg.org/blog/20210315-using-tpm-with-gnupg-2.3.html | 2026-05-10 | Vendor (GnuPG) — high |
| https://github.com/systemd/systemd/blob/main/docs/CREDENTIALS.md | 2026-05-10 | Vendor (systemd) — high |
| https://archive.fosdem.org/2024/schedule/event/fosdem-2024-2452-using-your-laptop-tpm-as-a-secure-key-store-are-we-there-yet-/ | 2026-05-10 | FOSDEM 2024 conference talk — medium |
| https://smallstep.com/blog/systemd-creds-hardware-protected-secrets/ | 2026-05-10 | Community / commercial — medium |

### Findings

- **systemd-creds is the RHEL-canonical mechanism for unattended service credentials.** systemd.io/CREDENTIALS: *"Credentials may optionally be encrypted and authenticated, either with a key derived from a local TPM2 chip, or one stored in /var/, or both."* This is what Red Hat / RHEL 9 use for service-level secrets and binds via TPM2 + PCR set.
- **GnuPG 2.3+ supports moving the GPG private key into the TPM directly** — eliminating "where do we store the passphrase" entirely. The GnuPG team explicitly documented this 2021-03 onward.
- **PCR-set binding is real but fragile**: FOSDEM 2024 talk (*"Using your Laptop TPM as a Secure Key Store: Are we there yet?"*) covers caveats — kernel updates, firmware updates, and boot-chain changes invalidate the seal. RHEL workaround is Clevis policy that re-binds after measured-boot changes.
- **The specific phrasing "TPM2 sealed against PCR set for GPG passphrase" is not in any vendor doc I found.** It's a derivable pattern (combine `systemd-creds encrypt --with-key=tpm2+host` with GPG batch-mode passphrase delivery) but not what the GnuPG team or Red Hat reference materials independently recommend.

### Recommendation

D64's recommendation is **technically sound** but the framing "industry-standard pattern" overstates external precedent. Stronger framings to consider for the spec:
- **Option A**: Reframe as "RHEL-canonical mechanism (systemd-creds) sealed against TPM2+PCR, delivering passphrase to `gpg --pinentry-mode loopback --batch --passphrase-fd`." Cites systemd-creds doc.
- **Option B**: Replace the passphrase-storage approach with **GPG-on-TPM** per the GnuPG 2.3 blog post — the GPG private key itself lives in the TPM, and there is no passphrase to store. This is a stronger alignment with the GnuPG team's own recommendation.
- **Option C (current spec)**: keep as-is but cite systemd-creds + GnuPG-on-TPM as the two adjacent vendor patterns the spec's recommendation derives from. Drop the "industry-standard" framing.

**Advisory finding for reviewers**: spec § 3.2's rejection of "keyutils, YubiKey, manual unlock" is well-reasoned (Automic unattended schedule precludes manual unlock; YubiKey requires hardware presence; keyutils alone doesn't survive reboot). The rejection rationale is grounded — only the positive framing of TPM2-sealed-PCR needs softening.

### Confidence: 🟡

Pattern is real and grounded; framing as "industry-standard for GPG passphrase" needs to be softened or re-grounded against systemd-creds (the actual standard) or GPG-on-TPM (GnuPG's own recommendation).

---

## Q2. D65 — Parity drift severity classification (fatal / warning / informational)

### Summary

**3-tier severity is a recognized pattern in modern data-quality tooling**, but the specific naming "fatal / warning / informational" is closer to log-level conventions than to canonical data-quality severity vocabulary. dbt uses `error / warn` (2-tier), Delta Live Tables uses `EXPECT / EXPECT OR DROP / EXPECT OR FAIL` (3-tier behavior, different naming). No single vendor uses the exact "fatal/warning/informational" triple, but the underlying tier structure (terminate-pipeline / log-and-continue / log-only) is well-established. **Confidence: 🟢** — the tiering concept is grounded; naming is a stylistic choice with no contradicting authority.

### Sources

| URL | Date accessed | Authority |
|---|---|---|
| https://hub.getdbt.com/Divergent-Insights/dbt_dataquality/latest/ | 2026-05-10 | Vendor adjacent (dbt) — medium |
| https://atlan.com/know/databricks/data-quality/ | 2026-05-10 | Vendor adjacent (Databricks) — medium |
| https://www.getdbt.com/blog/elt-best-practices-snowflake | 2026-05-10 | Vendor (dbt) — high |

### Findings

- **dbt test severity model is 2-tier**: `severity: error` (fails the run) and `severity: warn` (logs and continues). No "informational" third tier.
- **Delta Live Tables (Databricks) is 3-tier-by-behavior**: `EXPECT` (log violation), `EXPECT OR DROP` (drop row), `EXPECT OR FAIL` (fail pipeline). Different vocabulary from "fatal/warning/informational" but isomorphic structure.
- **Snowflake itself has no native data-quality tier vocabulary** — defers to client tools (dbt, Great Expectations, custom).
- **The "fatal/warning/informational" naming is closer to syslog severity levels** (RFC 5424) than to ETL/data-quality tooling vocabulary. This is fine — D65 isn't a data-quality contract; it's a configuration-drift contract, where syslog-style naming is more apt.

### Recommendation

D65's tiering is sound. Recommend the spec **explicitly note that "fatal/warning/informational" is syslog-style naming applied to configuration drift** (per RFC 5424 severity levels), not data-quality severity. This sidesteps any confusion with dbt/DLT conventions and grounds the choice in a recognized standard. If the spec already does this somewhere, no change needed.

**Advisory finding for reviewers**: classification taxonomy is well-defended by the analogy to syslog. The specific items called fatal (Python version, library SHAs, `MALLOC_ARENA_MAX`, envelope hash) are all changes that genuinely break correctness, supporting the "fatal = terminate" semantic.

### Confidence: 🟢

Tier concept is established practice; naming is a defensible choice that maps to RFC 5424 (syslog) conventions rather than to ETL data-quality vocabulary.

---

## Q3. D66 — Automic gate-table contract (AM/PM via `PipelineExecutionGate` + `sp_getapplock`)

### Summary

**`sp_getapplock` is canonical Microsoft-blessed concurrency control for SQL Server**, and pairing it with an atomic gate row is a known pattern, but the specific **`PipelineExecutionGate` table contract is a custom project pattern** without direct external precedent. The underlying primitives (sp_getapplock + atomic gate row + Session/Transaction lock ownership) are all well-grounded; the assembly is project-specific. **Confidence: 🟢** — the building blocks are authoritative; the specific table contract is fine as a custom pattern.

### Sources

| URL | Date accessed | Authority |
|---|---|---|
| https://learn.microsoft.com/en-us/sql/relational-databases/system-stored-procedures/sp-getapplock-transact-sql | 2026-05-10 | Vendor (Microsoft) — high |
| https://erikdarling.com/sp_getapplock-is-pretty-cool/ | 2026-05-10 | Community (Erik Darling) — medium |
| https://www.brentozar.com/archive/2024/04/troubleshooting-mysterious-blocking-caused-by-sp_getapplock/ | 2026-05-10 | Community (Brent Ozar) — medium |
| https://michaeljswart.com/2021/01/avoid-this-pitfall-when-using-sp_getapplock/ | 2026-05-10 | Community (Michael J. Swart) — medium |

### Findings

- **`sp_getapplock` is Microsoft-supported and explicitly designed for "logical resource coordination independent of physical database objects"** (per docs.microsoft.com). Using it to gate a scheduled ETL run is one of the documented use cases.
- **Session-owned vs Transaction-owned lock distinction is well-documented** — the spec correctly uses Session-owned per CLAUDE.md W-8 (RCSI race avoidance). External authority backs this.
- **Pitfall coverage is good**: Michael J. Swart (community) and Brent Ozar (community) both call out the long-transaction-detection problem with sp_getapplock — CLAUDE.md already cites this in `table_lock.py`.
- **The `PipelineExecutionGate` table contract itself** (AM/PM cycle, `Status` lifecycle, heartbeat, cancellation flag) is a custom pattern. No external doc covers this specific shape — but the components (atomic row with status transitions, heartbeat column, cancellation flag for cooperative cancellation per D33) are all standard.

### Recommendation

D66 is well-grounded on the primitives. Recommend the spec **cite Microsoft's sp_getapplock doc + the Session/Transaction ownership distinction** as the authoritative basis. The atomic gate-row pattern is a custom assembly and that's fine — no need to claim external precedent for the table shape itself. If the spec currently frames this as "industry-standard pattern," soften to "built on Microsoft-supported `sp_getapplock` + project-specific gate-row contract."

**Advisory finding for reviewers**: the scope correction in spec § 5 (gate table is AM/PM-only; other jobs use `sp_getapplock` + `PipelineEventLog`) is the right granularity. CHECK constraint `CycleType IN ('AM', 'PM')` is the enforcement mechanism per Round 1.

### Confidence: 🟢

Building blocks are authoritative (Microsoft docs); table contract is a custom assembly with no contradicting external authority.

---

## Q4. § 3.1 — GPG envelope with multiple recipients (primary + break-glass)

### Summary

**Multi-recipient GPG encryption is a documented GnuPG feature and a recognized backup/escrow pattern.** The GnuPG manual explicitly covers `--recipient` multiplicity, and the "encrypt to primary + escrow keys" is mentioned in community guidance for encrypted backups. The "break-glass" terminology is more common in IAM contexts (PAM, vault unsealing) than in GPG specifically, but the technique is the same. **Confidence: 🟢** — well-grounded.

### Sources

| URL | Date accessed | Authority |
|---|---|---|
| https://www.gnupg.org/gph/en/manual/x110.html | 2026-05-10 | Vendor (GnuPG manual) — high |
| https://www.gnupg.org/documentation/manuals/gnupg/GPG-Key-related-Options.html | 2026-05-10 | Vendor (GnuPG manual) — high |
| http://laurent.bachelier.name/2013/03/gpg-encryption-to-multiple-recipients/ | 2026-05-10 | Community blog — low/medium |

### Findings

- **GnuPG explicitly supports `--recipient` invoked multiple times** — the encrypted message contains one session-key packet per recipient, each holding the symmetric key encrypted to that recipient's public key. Any one recipient can decrypt.
- **The pattern is described in GnuPG's own documentation** for encrypted backups and team-shared archives: *"while your user database is hosted on your server, it is backed up outside of it and multiple people (members of the board) can decrypt it."*
- **"Break-glass" terminology is borrowed from emergency-access patterns** (Bitwarden, HashiCorp Vault, AWS Break Glass). The GnuPG technique is identical — the "break-glass" framing is about the operational policy (key holder accesses only in declared emergency), not the cryptography.

### Recommendation

§ 3.1's multi-recipient envelope is well-grounded. The spec can cite the GnuPG manual directly. No softening needed.

**Advisory finding for reviewers**: ensure the spec covers the **operational discipline** for break-glass keys — escrow location, access logging, post-use rotation. The cryptography is fine; the governance around when the break-glass key is used and how the access is audited is the substantive control. If the spec doesn't already cover this, surface as 🟡 (BACKLOG candidate).

### Confidence: 🟢

Pattern is vendor-documented; operational governance is the additional concern, not cryptographic grounding.

---

## Q5. D71 — `/dev/shm/snowflake_pk_<pid>` ephemeral key file

### Summary

**Snowflake's documented Python connector approach supports BOTH `private_key_file` (path on disk) AND `private_key` (in-memory DER bytes).** The in-memory variant is more secure and is the recommended pattern when the key is decrypted in-process — there is no need to write the decrypted key to `/dev/shm` if the process can hold it in memory. **D71's `/dev/shm` pattern is a valid intermediate but not the most idiomatic Snowflake auth flow.** **Confidence: 🟡** — recommend the spec consider the in-memory `private_key=` parameter as the preferred form, with `/dev/shm` only as fallback for sub-processes or libraries that demand a file path.

### Sources

| URL | Date accessed | Authority |
|---|---|---|
| https://docs.snowflake.com/en/user-guide/key-pair-auth | 2026-05-10 | Vendor (Snowflake) — high |
| https://docs.snowflake.com/en/developer-guide/python-connector/python-connector-connect | 2026-05-10 | Vendor (Snowflake) — high |
| https://community.snowflake.com/s/article/How-To-Connect-to-Snowflake-using-key-pair-authentication-directly-using-the-private-key-incode-with-the-Python-Connector | 2026-05-10 | Vendor community — high |

### Findings

- **Snowflake Python connector accepts `private_key=<DER bytes>`** — no file required. The community KB article *"How to connect to Snowflake using key pair authentication directly using the private key in-code with the Python Connector"* documents this. The pattern:
  ```python
  from cryptography.hazmat.primitives import serialization
  p_key = serialization.load_pem_private_key(pem_bytes, password=passphrase, backend=default_backend())
  pkb = p_key.private_bytes(
      encoding=serialization.Encoding.DER,
      format=serialization.PrivateFormat.PKCS8,
      encryption_algorithm=serialization.NoEncryption())
  conn = snowflake.connector.connect(..., private_key=pkb)
  ```
- **`private_key_file=<path>` is the older / file-based pattern.** The connector docs cover both.
- **AWS Secrets Manager / cloud-secret-manager pattern is the canonical 2024-2025 recommendation** for production environments — fetch the key bytes from a secret store, pass via `private_key=` parameter, never touch disk.
- **`/dev/shm` is tmpfs (RAM-backed)** — superior to a regular file but inferior to never-touch-filesystem. The R20 risk (key file leak via process crash) is genuinely mitigated only by in-memory delivery, not by `/dev/shm`.

### Recommendation

D71's `/dev/shm/snowflake_pk_<pid>` is a **defensible fallback** but not the most idiomatic Snowflake auth pattern. Recommend the spec:
- **Primary path**: decrypt GPG envelope → load PEM bytes → call `serialization.load_pem_private_key()` → call `.private_bytes()` → pass via `private_key=` parameter. Never touch filesystem.
- **Fallback path (only if a subprocess or library needs a file path)**: `/dev/shm/snowflake_pk_<pid>` with mode 0600 + explicit `release_snowflake_key()` cleanup. The R20 risk would then apply only to this fallback path.
- **Mitigation for the fallback path**: an `atexit` handler or `weakref.finalize` to clean up on graceful exit, plus a systemd `ExecStopPost=` for crash cases. tmpfs auto-clears on reboot, which catches the worst case.

**Advisory finding for reviewers**: this is the strongest "spec claim weaker than authority" finding in the cycle. D71 explicitly chose the file-based pattern; the in-memory pattern is documented as supported and more secure. If the spec's reasoning was "we already write the BCP CSV to a temp dir, so a file-based key is consistent" — that's a defensible operational argument, but it should be **stated explicitly** rather than left as the implicit default. Recommend either re-grounding D71 against the in-memory pattern or documenting why file-based was chosen.

### Confidence: 🟡

Pattern is valid but not the most idiomatic Snowflake recommendation; in-memory `private_key=` parameter exists and is preferred in vendor docs.

---

## Q6. § 4 — Cross-server parity baseline JSON

### Summary

**Configuration drift detection with a baseline + verification pattern is a recognized industry approach.** Ansible, Puppet, Chef, and OneUptime / Spacelift all document the "baseline JSON / playbook" + "scheduled verification + drift report" pattern for 3-server (dev/test/prod) environments. The spec's approach is consistent with industry practice. **Confidence: 🟢** — well-grounded.

### Sources

| URL | Date accessed | Authority |
|---|---|---|
| https://www.puppet.com/blog/configuration-drift | 2026-05-10 | Vendor (Puppet) — high |
| https://spacelift.io/blog/ansible-configuration-drift-management | 2026-05-10 | Community / commercial — medium |
| https://jwkenney.github.io/auditing-configuration-drift/ | 2026-05-10 | Community blog — medium |
| https://oneuptime.com/blog/post/2026-02-21-how-to-use-ansible-for-configuration-drift-detection/view | 2026-05-10 | Vendor adjacent (OneUptime) — medium |

### Findings

- **Puppet, Ansible, Chef all use baseline + verification patterns**: a declarative baseline (playbook, manifest, recipe) + a verification mode that compares live state against the baseline and reports drift.
- **The 3-server failover pattern (dev/test/prod) is well-served by per-environment baselines** with explicit "documented exceptions" arrays for legitimate per-server differences (test has more debugging, prod has tighter security).
- **A pinned baseline JSON checked into source control is a recognized variant** — simpler than running Puppet/Ansible if the goal is detection (not enforcement). The spec's approach (JSON file + Python verifier script + startup check) is a known minimalist implementation.
- **No external doc found that contradicts the spec's approach.** The pattern is well-established.

### Recommendation

§ 4's parity baseline JSON is well-grounded. The spec can cite Puppet's drift-management blog or Spacelift's Ansible drift article as authoritative references if framing the approach for stakeholders. No softening needed.

**Advisory finding for reviewers**: the spec's `documented_exceptions` array with expiration enforcement (per R18) is **more rigorous than typical industry practice** — most baseline-JSON implementations don't have expiration on exceptions. This is a strength worth highlighting. R18's score (2) is appropriate given the quarterly maintenance cadence.

### Confidence: 🟢

Pattern is well-established; spec's exception-expiration enforcement is a positive enhancement over typical practice.

---

## REVIEWER R2-5 — Research grounding (Round 2 cycle 1, Pattern E 5th slot)

### Research questions investigated (6)

| # | Topic | Confidence | Authoritative source(s) |
|---|---|---|---|
| Q1 | TPM2-sealed-PCR for GPG passphrase (D64) | 🟡 | systemd.io/CREDENTIALS, GnuPG 2.3 blog |
| Q2 | Parity drift severity tiers (D65) | 🟢 | dbt severity model, RFC 5424 syslog analogy |
| Q3 | Automic gate-table + sp_getapplock (D66) | 🟢 | Microsoft sp_getapplock docs, Erik Darling, Brent Ozar |
| Q4 | Multi-recipient GPG envelope (§ 3.1) | 🟢 | GnuPG manual x110 |
| Q5 | `/dev/shm/snowflake_pk` ephemeral key (D71) | 🟡 | Snowflake Python connector docs, community KB |
| Q6 | Parity baseline JSON for 3-server drift (§ 4) | 🟢 | Puppet drift-mgmt blog, Spacelift Ansible drift |

### Advisory findings (claims requiring grounding strengthening or rewording)

1. **D64 (TPM2 for GPG passphrase)** — framing as "industry-standard" overstates external precedent. Vendor-canonical patterns are systemd-creds (RHEL service credentials) or GPG-on-TPM (GnuPG's own recommendation). The spec's recommendation is technically sound but should re-ground against systemd-creds or GPG-on-TPM rather than claiming a generic industry-standard pattern.

2. **D71 (`/dev/shm` key file)** — Snowflake Python connector documents an in-memory `private_key=<DER bytes>` parameter that avoids touching the filesystem entirely. D71's file-based approach is defensible as fallback but not the most idiomatic vendor recommendation. R20 (key file leak on crash) is genuinely mitigated by the in-memory pattern. Recommend either re-grounding D71 against the in-memory pattern or explicitly documenting why file-based was chosen.

3. **(Not 🔴, just advisory)** — Reviewers R2-1/2/3/4 may incorporate Q1 and Q5 findings into their own 🟡 verdicts if they want stronger grounding in the spec.

### Output file written

`docs/migration/_research/round2-cycle1-evidence.md`

### Pattern E effectiveness from research-specialist perspective

- **External grounding caught 2 of 6 claims weaker than authority** (D64 framing, D71 file-vs-memory). Both are not 🔴 by themselves — the patterns work — but stronger external grounding would improve audit-grade defensibility.
- **4 of 6 claims well-grounded** — D65 tiering (syslog), D66 gate-table (sp_getapplock vendor doc), § 3.1 multi-recipient GPG (GnuPG manual), § 4 parity baseline (Puppet/Ansible industry pattern).
- **Pattern E value-add**: 4-reviewer composition would have caught spec/code drift; 5th slot research caught framing-vs-authority drift. These are different failure modes — Pattern E's external-grounding slot is complementary, not redundant.
- **Cycle clean / not-clean determination defers to R2-1/2/3/4** per D72.

### CCL COMPLIANCE TRACE

| Stage | File read | First content-substantive call |
|---|---|---|
| Stage 1 | `NORTH_STAR.md` | ✅ First Read call (lines 1-82) |
| Stage 1 | `HANDOFF.md` (lines 1-100) | ✅ |
| Stage 1 | `CURRENT_STATE.md` (lines 1-100) | ✅ |
| Stage 1 | `CHECKS_AND_BALANCES.md` (lines 1-80) | ✅ |
| Stage 2 | `RISKS.md` (lines 1-40, R18-R21 read) | ✅ |
| Stage 2 | `BACKLOG.md` (lines 1-40) | ✅ |
| Stage 3 | `phase1/02_configuration.md` (lines 1-200) | ✅ — Round 2 artifact under review |
| Stage 4 | WebSearch — 8 queries across 6 research questions | ✅ |

**Verification**: first content-substantive `Read` call hit `NORTH_STAR.md` (Stage 1) before any WebSearch / artifact read. CCL invariant per D62 satisfied.
