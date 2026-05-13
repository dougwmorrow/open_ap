# Security Model — Claude Code + Production Credential Defense

**Status**: 🟢 Locked 2026-05-11 per D103. Authoritative reference for engineers + auditors.
**Audience**: engineers (especially those unfamiliar with RHEL), operations, security auditors, anyone reviewing the project's credential-access defense posture.

This doc covers the canonical security model for using Claude Code in dev + the production credential defense for test/prod (where Claude is NOT installed). Per user-stated strict security policy: NO commercial endpoint security spending; RHEL-shipped + Microsoft-built-in tools only.

---

## § 1 — TL;DR

**Claude Code operates in `/debi` project directory only. Credentials live OUTSIDE `/debi`. Test + Prod servers do not have Claude Code installed. Defense built from RHEL-shipped tools (SELinux + auditd + systemd-creds + POSIX ACLs + kernel keyring), Microsoft Windows built-in (NTFS ACLs + DPAPI + Credential Manager), Claude Code's own deny rules, and operational discipline.**

13 layers of defense detailed in § 4. The MOST IMPORTANT defense is **L1 (working-directory boundary)** + **L13 (image-bake policy: Claude not installed on test/prod)**. If those two are enforced, the rest is hardening.

---

## § 2 — Threat surface inversion: dev > test > prod

Standard intuition says "prod is where the crown jewels are, prod gets the most protection." That's not the threat model here.

| Environment | Claude Code installed? | Real credentials? | Threat surface | Protection focus |
|---|---|---|---|---|
| **Dev** (workstation) | ✅ Yes — operates in `/debi` only | ❌ NEVER on disk | **HIGH** — Claude operates here; engineers experiment with code; mistakes happen | **MAXIMUM** |
| **Test** (RHEL server) | ❌ No (image-bake) | ✅ Test-only credentials | LOW (Claude can't access) | Standard RHEL hardening |
| **Prod** (RHEL server) | ❌ No (image-bake) | ✅ Prod credentials TPM2-sealed | LOW (Claude can't access) | Standard RHEL hardening + restricted access |

The reasoning: Claude is the new variable. Prod has been hardened for years; we trust the existing model. Dev is where Claude operates + where developer mistakes happen + where credentials could leak into dev artifacts that engineers then push.

---

## § 3 — Where credentials live

### Production credentials (test + prod servers)

| Item | Location | Owner / mode | Defense |
|---|---|---|---|
| `.env` (replacement for legacy `/debi/.env`) | `/etc/pipeline/.env` | `pipeline:pipeline` 0400 | L5 ACLs + L11 SELinux |
| GPG envelope | `/etc/pipeline/credentials.json.gpg` | `pipeline:pipeline` 0400 | L5 ACLs + L11 SELinux |
| TPM2-sealed master passphrase | TPM hardware (no on-disk file) | Hardware-bound | TPM2 PCR constraints |
| Snowflake RSA key (ephemeral) | `/dev/shm/snowflake_pk_<pid>` | Per-process; tmpfs | Cleared on process exit |
| Source DB credentials | Inside GPG envelope; decrypted to memory only at runtime | systemd unit context | systemd-creds + L11 |

### Dev workstation credentials (if needed for interactive debugging)

| Item | Location | Why |
|---|---|---|
| Engineer's SSH key for accessing test/prod | `~/.ssh/id_*` (NOT in /debi) | Standard SSH; Claude has no read access via L1-L3 |
| Engineer's git credentials | OS-native: macOS Keychain / Windows Credential Manager / Linux secret-service / kernel keyring | OS-native vault; no file on disk |
| AWS / GCP / Azure CLI auth | `~/.aws/credentials`, etc. (NOT in /debi) | Standard CLI conventions; Claude has no read access |
| Project-specific dev credentials | NONE — use `.env.example` placeholders only | Real credentials NEVER on dev disk per D103 L4 |

### Project directory `/debi` (Claude operates here)

| Content | Why |
|---|---|
| Source code (Python, SQL) | Yes — Claude reads + writes |
| Spec docs (`docs/migration/`) | Yes — Claude reads + writes |
| Test fixtures (mock data only) | Yes — Claude reads + writes |
| `.env.example` (fake values) | Yes — placeholder template |
| **Real credentials of any kind** | **NEVER** — D103 L4 |

---

## § 4 — The 13 layers of defense

### Dev environment (Claude operates here — maximum protection)

**L1 — `/debi` working-directory boundary** (primary architectural defense)

Claude Code is launched with `/debi` as cwd. Relative paths in tool calls (`Read("./config.py")`) resolve within `/debi`. Absolute paths outside `/debi` (`Read("/etc/pipeline/.env")`) require crossing OS filesystem boundaries that are explicitly denied by L2-L5.

```bash
# Dev workstation setup
mkdir -p /debi
cd /debi
git clone <repo-url> .
# Claude is launched here:
claude-code  # CWD = /debi
```

Engineers should never invoke Claude outside `/debi`. RB-12 doesn't apply to dev workstations (test/prod only), but operational discipline expects `cd /debi && claude-code` pattern.

**L2 — `.claudeignore` patterns**

File at `/debi/.claudeignore` enumerates paths Claude must not read. Per D53 baseline + D103 extension. Patterns include `/etc/pipeline/**`, `/home/**`, `/root/**`, `~/.ssh/**`, `~/.gnupg/**`, `~/.pipeline/**`, `~/.aws/**`, `~/.kube/**`, `/dev/shm/snowflake_pk_*`, `C:/ProgramData/Pipeline/**`, `C:/Users/*/AppData/Local/Pipeline/**`, `*.gpg`, `*.pem`, `*.key`, `**/.env`, etc.

Caveat per the file's own header: `.claudeignore` is NOT officially supported by Claude Code as of May 2026. The enforced mechanism is L3. `.claudeignore` documents intent and supports community PreToolUse hooks.

**L3 — `.claude/settings.local.json` `permissions.deny` rules**

File at `/debi/.claude/settings.local.json` has explicit `deny` array. These rules override `bypassPermissions` mode (per D52). Every Read / Bash / PowerShell tool call against a denied path returns refusal.

Sample (full set in committed file):
```json
"deny": [
  "Read(/etc/pipeline/**)",
  "Read(/home/**)",
  "Read(~/.ssh/**)",
  "Bash(gpg --decrypt:*)",
  "Bash(cat ~/.ssh/*)",
  "Bash(printenv:*)",
  "PowerShell(Get-Credential*)"
]
```

**L4 — No real credentials on dev disk EVER**

Operational discipline: dev uses fake values in `.env.example`. Tier 1 tests use mocks (per D70). Tier 2 property tests use Hypothesis synthetic data. Tier 3 integration tests use **test environment** credentials by SSHing into the test server (where Claude is not installed). Engineers NEVER copy real credentials to dev disk.

**L5 — Filesystem ACLs (per-user explicit deny)**

For paths that exist on dev workstation (e.g., engineer's home directory) where Claude shouldn't read:

```bash
# Linux/RHEL — POSIX ACLs (RHEL-shipped; vendor-supported)
sudo setfacl -m u:<claude-user>:--- /home/<engineer>/.ssh/
sudo setfacl -m u:<claude-user>:--- /home/<engineer>/.gnupg/
sudo setfacl -m u:<claude-user>:--- /etc/pipeline/

# Verify
getfacl /home/<engineer>/.ssh/

# Windows — NTFS ACLs (Windows-built-in)
icacls "C:\Users\<engineer>\.ssh" /deny "<claude-user>:(R)"
icacls "C:\ProgramData\Pipeline" /deny "<claude-user>:(R)"
```

Note: if Claude runs as the same OS user as the engineer (common dev setup), ACL deny rules require a separate Claude user account OR explicit-deny on Claude's user. The cleanest setup is: dedicate a `claude` user account for Claude Code runs, separate from the engineer's user account. This makes ACL enforcement straightforward.

**L8 — OS-native credential storage** (if dev-side credentials are unavoidable for interactive debugging)

Use OS-built-in credential vaults; never plaintext files:

**Windows**: DPAPI / Credential Manager
```powershell
# Store
$secureString = ConvertTo-SecureString -String "my-secret" -AsPlainText -Force
$cred = New-Object -TypeName System.Management.Automation.PSCredential -ArgumentList "user", $secureString
$cred | Export-Clixml -Path "C:\Users\<user>\AppData\Local\Pipeline\cred.xml"  # DPAPI-encrypted to current user

# Read in pipeline code (runs as user)
$cred = Import-Clixml -Path "C:\Users\<user>\AppData\Local\Pipeline\cred.xml"
```

**Linux (RHEL)**: kernel keyring via `keyctl` (kernel built-in; vendor-supported)
```bash
# Store secret in user session keyring
echo -n "my-secret" | keyctl padd user db_password @us

# Read in pipeline code (Python via libkeyutils binding)
keyctl read $(keyctl search @us user db_password)
```

The advantage: secrets are kernel-mediated; not visible to other processes unless explicitly granted; ephemeral (cleared on session end). Claude (running as user) might query keyring keys but L3 denies `keyctl read:*` / `keyctl print:*` Bash calls.

### Test + Prod environment (RHEL; Claude NOT installed)

**L9 — auditd** (RHEL-shipped, vendor-supported by Red Hat)

Linux Audit framework logs every file access to credential paths. Standard RHEL component.

```bash
# Add audit rules for credential paths (RHEL administrator action)
sudo cat <<EOF > /etc/audit/rules.d/pipeline-secrets.rules
-w /etc/pipeline/ -p rwxa -k pipeline_secrets
-w /etc/pipeline/.env -p rwxa -k pipeline_secrets
-w /etc/pipeline/credentials.json.gpg -p rwxa -k pipeline_secrets
-w /var/lib/pipeline/ -p rwxa -k pipeline_secrets
-w /dev/shm/snowflake_pk -p rwxa -k pipeline_secrets
EOF
sudo augenrules --load
sudo systemctl restart auditd
```

Audit logs land in `/var/log/audit/audit.log`. Search for credential access:
```bash
sudo ausearch -k pipeline_secrets --start today
```

Quarterly review per `MAINTENANCE.md` cadence + any anomalous-process-access alerts to ops.

**L10 — systemd-creds + TPM2 sealing** (per D64; RHEL 9+ systemd-native)

systemd's native credential mechanism integrates with TPM2 for hardware-bound credential storage. The pipeline's systemd unit receives credentials via `LoadCredentialEncrypted=` directives. Credentials never appear as conventional files in the filesystem.

```ini
# /etc/systemd/system/pipeline.service
[Unit]
Description=UDM Pipeline Service
After=network.target

[Service]
Type=simple
User=pipeline
Group=pipeline

# TPM2-encrypted credentials (systemd ≥ 250)
LoadCredentialEncrypted=db_password:/etc/pipeline/creds/db_password.cred
LoadCredentialEncrypted=vault_key:/etc/pipeline/creds/vault_key.cred
LoadCredentialEncrypted=snowflake_pk:/etc/pipeline/creds/snowflake_pk.cred

# The credentials become available to the process at:
# $CREDENTIALS_DIRECTORY/db_password
# $CREDENTIALS_DIRECTORY/vault_key
# $CREDENTIALS_DIRECTORY/snowflake_pk

ExecStart=/opt/pipeline/v1.2.3/bin/main_small_tables.py --workers 4 --cycle AM

[Install]
WantedBy=multi-user.target
```

Encrypt credentials at setup (RHEL administrator action):
```bash
# Encrypts using TPM2 PCR-bound policy; only decryptable on this exact machine
sudo systemd-creds encrypt --with-key=tpm2 plaintext_db_password.txt /etc/pipeline/creds/db_password.cred
```

Per D103 L3: `Bash(systemd-creds list:*)` and `Bash(systemd-creds cat:*)` are denied for Claude.

**L11 — SELinux MAC** (RHEL-default, enabled per Phase 0 0.11 confirmation)

Security-Enhanced Linux provides Mandatory Access Control. SELinux contexts label every file and process. Policies define which contexts can access which.

### Quick reference for engineers unfamiliar with RHEL/SELinux

**Check SELinux status**:
```bash
sestatus
# Should report:
#   SELinux status:                 enabled
#   Current mode:                   enforcing
#   Policy from config file:        targeted
```

**View SELinux context of a file**:
```bash
ls -lZ /etc/pipeline/credentials.json.gpg
# Output includes context like: unconfined_u:object_r:etc_t:s0
```

**View SELinux context of a process**:
```bash
ps -eZ | grep pipeline
# Output includes context like: system_u:system_r:pipeline_t:s0
```

**If a process is denied access (legitimate operation), check audit log**:
```bash
sudo ausearch -m AVC --start today
# AVC = Access Vector Cache denial events
```

**Generate policy to allow a denied operation** (use sparingly; understand WHY first):
```bash
sudo ausearch -m AVC --start today | audit2allow -M pipeline_policy
sudo semodule -i pipeline_policy.pp
```

**Common operations**:
- Allow pipeline service to read `/etc/pipeline/`:
  ```bash
  sudo semanage fcontext -a -t pipeline_etc_t "/etc/pipeline(/.*)?"
  sudo restorecon -Rv /etc/pipeline/
  ```
- Verify policy module loaded:
  ```bash
  sudo semodule -l | grep pipeline
  ```

**SELinux modes**:
- `enforcing` — policy enforced (deny actions get blocked + logged); production default
- `permissive` — policy NOT enforced but violations logged (useful for debugging)
- `disabled` — SELinux off (do NOT use in production)

**Switch modes temporarily** (for debugging):
```bash
sudo setenforce 0  # temporarily go permissive
sudo setenforce 1  # back to enforcing
```

**Persistent mode change** (requires reboot):
```bash
# Edit /etc/selinux/config: SELINUX=enforcing
```

**L12 — Network isolation** (test + prod)

Production + test servers have firewall rules allowing outbound connections only to:
- Snowflake endpoints (`*.snowflakecomputing.com`)
- Source DB hosts (configured per `UdmTablesList.SourceServer`)
- Internal monitoring + log aggregation endpoints

Claude Code's calls to `api.anthropic.com` would fail. This is belt-and-suspenders given L13 (Claude not installed at all).

**L13 — Image-bake policy** (RB-12 enforcement)

The RHEL OS image baked for test + prod servers does NOT include the Claude Code CLI binary. Pre-deploy checklist in RB-12 verifies:

```bash
# RB-12 post-deploy verification
if which claude-code 2>/dev/null; then
    echo "CRITICAL: Claude Code installed on test/prod; halt deploy"
    exit 1
fi
```

Ansible/automation removes any errant install:
```yaml
- name: Ensure Claude Code is not installed on test/prod
  hosts: pipeline_servers
  tasks:
    - name: Remove claude-code binary
      file:
        path: /usr/local/bin/claude-code
        state: absent
    - name: Remove .claude/ user dir
      file:
        path: "{{ ansible_user_dir }}/.claude"
        state: absent
```

---

## § 5 — Operational discipline (the human layer)

The above 13 layers are technical. The operational layer is equally important:

### DO

- ✅ Always `cd /debi && claude-code` — start Claude with the right working directory
- ✅ Use `.env.example` placeholders in dev; never paste real credentials
- ✅ For credential-dependent debugging: SSH into test environment; do the work there; never copy creds back to dev
- ✅ When asked to test a feature that needs real credentials: write the test as Tier 3 (Docker integration with `testcontainers`) using fake-but-realistic data
- ✅ Review `.claude/settings.local.json` `permissions.deny` annually; update if new credential paths emerge
- ✅ Review audit logs (`auditd` for Linux test/prod; Sysmon equivalent for dev workstation) quarterly per MAINTENANCE.md
- ✅ Rotate credentials per company policy; document rotation cadence in `RB-6` (vault corruption response) + future RB

### DO NOT

- ❌ NEVER `cat /etc/pipeline/.env` or similar — denied by L3 + L5
- ❌ NEVER copy production credentials to dev workstation for "convenience"
- ❌ NEVER install Claude Code on test or prod servers (RB-12 prevents)
- ❌ NEVER ask Claude to "show me the credentials" — even rhetorically
- ❌ NEVER commit `.env` files (`.gitignore` should exclude; pre-commit hook should refuse)
- ❌ NEVER use `bypassPermissions` mode WITHOUT explicit `permissions.deny` for credentials (D52 + D103 must be paired)
- ❌ NEVER decrypt the GPG envelope to disk in dev — use the systemd-creds path on test/prod
- ❌ NEVER install commercial endpoint security in dev (policy: no commercial spending)
- ❌ NEVER install AppArmor or similar open-source MAC frameworks (policy: open-source banned unless RHEL-shipped)

---

## § 6 — Incident response

If a credential is suspected to have leaked (in any direction):

1. **Immediate**: rotate the affected credential per company policy + RB-6
2. **Verify**: search `auditd` logs for the relevant credential path during the suspected window
3. **Quarantine**: review Claude session transcripts (in `.claude/sessions/` or wherever stored) for unusual tool calls
4. **Root cause**: identify which defense layer failed (L1-L13) — document for security retrospective
5. **Strengthen**: add new deny rules to `.claudeignore` + `.claude/settings.local.json` if needed
6. **Disclose**: per company policy + compliance obligations

Per R32 risk score (Low × Medium = 2 ⚪ post-mitigation): the multi-layer defense makes accidental credential access unlikely, but the incident response plan is here regardless.

---

## § 7 — Cross-references

- **D103**: This decision (canonical authority for the security model)
- **D52**: bypassPermissions mode rationale
- **D53**: `.claudeignore` baseline
- **D54**: PreToolUse hooks (deferred; would programmatically enforce L3)
- **D64**: GPG envelope + TPM2 sealing
- **D102**: AES-256-GCM encryption pinning for vault
- **R32**: Risk of Claude credential-access (Low × Medium = 2 ⚪ post-mitigation)
- **RB-3 / RB-4**: Authorized decryption procedures
- **RB-6**: Vault corruption response
- **RB-10**: CCPA right-to-deletion
- **RB-12**: Pipeline deployment (image-bake L13 enforcement)
- **RB-14**: `.env` Location Migration (`/debi/.env` → `/etc/pipeline/.env`) — operational manifestation of L1 working-directory boundary + L6 file mode 0400 + L9 auditd watch + L11 SELinux context (authored 2026-05-11 at Phase 0 prep close-out; closes B182)
- **B184**: `tools/verify_credentials_load.py` CLI shim — RB-14 pre-flight smoke test dependency; gates Phase 2 R1 pilot prerequisites
- **`MAINTENANCE.md`**: Quarterly audit cadence
- **`.claudeignore`**: ignore patterns (L2)
- **`.claude/settings.local.json`**: deny rules (L3)

---

## § 8 — Future evolution

Items deferred or under consideration:

- **PreToolUse hooks** (D54) — when Claude Code hooks gain support, L3 becomes hook-enforced rather than config-enforced
- **Secrets manager evaluation** (Phase 5+) — HashiCorp Vault / AWS Secrets Manager / Azure Key Vault — currently NOT pursued due to no-commercial-spending policy
- **Hardware Security Modules (HSM)** for vault key — currently TPM2 + systemd-creds; HSM upgrade is Phase 5+ candidate
- **Quarterly red-team review** — proposal to simulate Claude credential-access attempts annually + adjust defenses

---

## Owner

Pipeline lead + Security team (review quarterly per MAINTENANCE.md).

## Last reviewed

2026-05-11 (authored at Phase 0 0.12 closure per D103 lock; supports 0.1 architecture sign-off + future Phase 1 implementation; supersedes prior CLAUDE.md convention of `/debi/.env` location with new `/etc/pipeline/.env` canonical)
