<\!-- Archive provenance:
- Extracted from: CLAUDE.md (pre-trim state at commit c189432 / 2026-05-15 / 720 lines total)
- Extracted at: lines 538-600 (63 lines verbatim)
- Trim commit: 7e2c606 (D.5 Approach A — Conservative trim per Q-12 approved)
- Trim rationale: section was largely DUPLICATE of canonical content at the destination(s); replaced in active CLAUDE.md with summary + cross-ref to reduce CCL token cost
- Destination cross-ref(s) in active CLAUDE.md: docs/migration/SECURITY_MODEL.md (canonical 407 lines) + CLAUDE.md (post-trim) summary at L281-296
- Archive strategy: belt-and-suspenders per user-direction 2026-05-15 (Option B "Archive EVERYTHING verbatim"); content preserved for recovery without git archaeology
- Reversibility: `git show c189432:CLAUDE.md` returns full pre-trim CLAUDE.md; this archive is a partial slice
- Authored: 2026-05-15 by retroactive archive sweep per refactor-strategy decision
- Linked from: docs/migration/_refactor_log.md (refactor event D.5-security-model)
-->

# CLAUDE.md — Claude Code Security Model (D103 summary) (archived)

**This is an archived copy** of the Claude Code Security Model (D103 summary) section from CLAUDE.md, extracted verbatim from the pre-D.5-trim state. The active CLAUDE.md no longer contains this section — see cross-ref destination(s) above for the canonical home(s).

If you arrived here looking for current information: prefer the destination cross-ref. This archive exists for recovery + audit-trail purposes only.

---

## Claude Code Security Model (D103 — summary; canonical reference: `docs/migration/SECURITY_MODEL.md`)

**Claude Code operates only inside the `/debi` working directory. Credentials live OUTSIDE `/debi` and Claude has zero authorized read path to them.** This is the project's primary architectural defense for AI-assisted development.

### Per-environment posture (threat-surface inversion: dev > test > prod)
| Environment | Claude Code installed? | Why |
|---|---|---|
| **Dev workstation** | ✅ Yes (Windows or RHEL) | Highest threat surface — engineer AI-assists daily; deepest defense |
| **Test (RHEL)** | ❌ No | Image-baked NO-CLAUDE policy; test data has prod parity |
| **Prod (RHEL)** | ❌ No | Image-baked NO-CLAUDE policy; deployment is pull-from-registry only |

### Credential locations (Claude NEVER reads any of these)
- **Production (RHEL)**: `/etc/pipeline/.env` (mode 0400, pipeline:pipeline), `/etc/pipeline/credentials.json.gpg` (TPM2-sealed), `/dev/shm/snowflake_pk_<pid>` (ephemeral RSA, in-memory only)
- **Dev workstation (RHEL)**: `~/.ssh/`, `~/.gnupg/`, `~/.pipeline/`, `~/.aws/`, kernel keyring (`keyctl`)
- **Dev workstation (Windows)**: `C:/Users/<user>/.ssh/`, Credential Manager (DPAPI), `C:/ProgramData/Pipeline/`
- **NEVER inside `/debi`**: the project directory is sanitized — no `.env`, no `*.gpg`, no `*.pem`, no `*.key`, no `credentials.json`

### The 13 layers of defense (one-line summary; details in `SECURITY_MODEL.md`)
1. `/debi` working-directory boundary (Claude Code architectural)
2. `.claudeignore` patterns (human-readable inventory; community hook may enforce)
3. `.claude/settings.local.json` `permissions.deny` array (Claude Code enforced — Read/Bash/PowerShell deny rules for ~60 credential patterns)
4. No credential files on dev workstation inside any AI-accessible path
5. POSIX ACLs (`setfacl`) on RHEL + NTFS ACLs (`icacls`) on Windows — explicit deny for the Claude user against `~/.ssh/`, `~/.gnupg/`, `~/.aws/`, etc.
6. File-mode 0400 + ownership pipeline:pipeline on `/etc/pipeline/.env`
7. GPG-encrypted `credentials.json.gpg` at rest; decrypted in-memory only at pipeline start
8. OS-native credential vaults (Windows DPAPI / RHEL kernel keyring via `keyctl`) for dev secrets
9. `auditd` on RHEL — `/etc/audit/rules.d/pipeline-secrets.rules` watches `/etc/pipeline/` and `~/.ssh/` for any access; `ausearch -k pipeline_secrets`
10. `systemd-creds encrypt --with-key=tpm2` + `LoadCredentialEncrypted=` for service-managed secrets (TPM2-bound, cannot decrypt off the original machine)
11. **SELinux** on RHEL (enabled, enforcing) — RHEL-shipped MAC framework. `sestatus`, `ls -lZ`, `ps -eZ`, `audit2allow` for policy iteration. No AppArmor (open-source policy bans it).
12. Network isolation — Claude Code outbound restricted to allowlisted domains in `.claude/settings.local.json` `permissions.allow.WebFetch(domain:...)`
13. Image-bake check: production/test golden image build step fails if `which claude-code` returns 0

### What we use vs. what we don't (per user policy)
- ✅ RHEL-shipped tools (SELinux, auditd, systemd-creds, kernel keyring, POSIX ACLs, TPM2)
- ✅ Microsoft built-ins (DPAPI, NTFS ACLs, Credential Manager, Windows Defender baseline)
- ✅ Claude Code's own deny/allow lists in `.claude/settings.local.json`
- ❌ Commercial endpoint security (CrowdStrike, McAfee, MS Defender for Endpoint) — zero budget for paid security tools
- ❌ AppArmor — open-source MAC framework not shipped by RHEL; strict policy bans
- ❌ Third-party secrets managers (HashiCorp Vault SaaS, AWS Secrets Manager, Azure Key Vault) — deferred to Phase 5+ evaluation

### PiiVault encryption (D102 — AES-256-GCM)
- `PiiVault.EncryptedPlaintext` uses **AES-256-GCM** in Python (`cryptography` library).
- Wire format: `nonce (12 bytes) || ciphertext || auth_tag (16 bytes)` — single column, no separate IV/tag columns.
- Key managed via Phase 0.4 merger-context plan (TBD — likely TPM2-sealed on RHEL + DPAPI on Windows dev).
- Each token has a unique 12-byte random nonce per encryption operation; never reuse nonce + key.
- See `03_DECISIONS.md` D102 and `SECURITY_MODEL.md` § 4 for full crypto rationale.

### Operational discipline (DO / DO NOT)
- **DO** keep `/debi` clean — no committed `.env`, no committed `*.gpg`, no committed `*.pem`. Grep-check before every commit.
- **DO** add new credential paths to BOTH `.claudeignore` (documentation) AND `.claude/settings.local.json` `permissions.deny` (enforcement) when discovered.
- **DO** treat any `Read(...)` or `Bash(cat ...)` permission prompt for a credential path as a red flag — deny + investigate which agent/tool/skill is asking.
- **DO NOT** install Claude Code on test or prod RHEL servers. Image-bake check enforces this; do not whitelist around it.
- **DO NOT** loosen `.claude/settings.local.json` `permissions.deny` for the convenience of a single task — if a workflow legitimately needs credential access, the workflow runs OUTSIDE Claude (operator runs the script manually, pipes the result into the AI conversation as text).
- **DO NOT** commit anything from `~/.aws/`, `~/.ssh/`, `~/.gnupg/`, or any path matched by `.claudeignore` patterns.

### Incident response
If Claude Code is observed reading (or attempting to read) a credential file:
1. Capture the tool-call evidence (Read path + timestamp + agent invoking).
2. Check `auditd` (RHEL) or Event Viewer (Windows) for corroborating OS-level access logs.
3. Rotate the credential immediately (no debate — assume compromise).
4. Add the path to `permissions.deny` if not already present; verify `.claudeignore` parity.
5. File an incident note in `RISKS.md` under R32 (Claude credential-access risk) with the trigger event.
