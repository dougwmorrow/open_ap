# Round 4.5 — Phase 0 Prep Tools Supplement

**Status**: 🟡 Draft (authored 2026-05-11 to close B183 + B184 surfaced at Phase 0 prep / Phase 2 plan-draft cascades). Per **D100** Round-N.5 documentation supplement discipline + **D92** forward-only schema-evolution governance — this is an additive supplement to the locked `phase1/04_tools.md` (Round 4 🟢 Locked 2026-05-10 via D78). Pre-D78 tool inventory (Tools 1-11) is grandfathered; this supplement adds Tools 12 + 13.

## § 1. Purpose + scope

Two tools surfaced AFTER Round 4 close that are operationally required before Phase 2 R1 can begin:

- **Tool 12 — `verify_credentials_load.py`** (B184; WSJF 4.0): CLI shim wrapping the Round 3 § 3.1 `credentials_loader` module; verifies TPM2 unseal + GPG envelope decrypt + required-key presence WITHOUT exposing plaintext. Hard prerequisite for RB-14 pre-flight (`05_RUNBOOKS.md` L1311+) and Phase 2 R1 deploy verification.

- **Tool 13 — `capture_parity_baseline.py`** (B183; WSJF 2.0): produces the `parity_baseline_<env>_<date>.json` file (per Round 2 § 4.1 schema at `02_configuration.md`) consumed by `verify_server_parity.py` (R4 § 3.7). Closes the operational loop on D27 (cross-server parity) + D65 (drift severity classification) + Phase 0 deliv 0.11.

Both tools follow Round 4 conventions: **D74** exit-code contract (0/1/2), **D75** argument naming + actor TTY heuristic, **D76** audit-row contract (one `PipelineEventLog` row per invocation with `EventType='CLI_<TOOL_NAME>'`), **D77** Tier 0 scaffold pattern (6 canonical assertions, <5s, mocked subprocess + cursor), **D67** + **D70** test pyramid (Tier 0 + Tier 1 unit; Tier 3 integration on Docker fixtures).

### Boundaries (what this supplement does NOT do)

- Does NOT modify any Round 4 tool spec (Tools 1-11 in `phase1/04_tools.md` § 3.1 - § 3.11). Those are 🟢 Locked per D78.
- Does NOT re-spec the Round 3 `credentials_loader` module (§ 3.1) or the Round 2 baseline JSON schema (§ 4.1). Those are 🟢 Locked.
- Does NOT introduce new D-numbers — this supplement consumes existing D-decisions (D27 / D55 / D62 / D65 / D67 / D70 / D74-D77 / D85 / D92 / D100 / D103) and operationalizes them.
- Does NOT cover the actual Python implementation — only the spec. Implementation lands at Phase 2 R1 per the Phase 2 deep-dive plan (`phase2/00_phase_overview.md`).

## § 2. Read order

For an engineer or AI agent picking this up cold:

1. `phase1/04_tools.md` § 1 (cross-cutting CLI conventions — exit codes, args, audit rows, Tier 0 scaffold)
2. `phase1/03_core_modules.md` § 3.1 (`credentials_loader` module — Tool 12's wrapped function) + § 3.2 (`server_parity_verifier` module — informs Tool 13's output schema)
3. `phase1/02_configuration.md` § 4.1 (parity baseline JSON canonical schema — Tool 13's output contract)
4. `03_DECISIONS.md` D27 + D65 + D74-D77 + D103 (decisions this supplement operationalizes)
5. `05_RUNBOOKS.md` § RB-14 (operational consumer of Tool 12)
6. `phase2/00_phase_overview.md` § Round 1 (Phase 2 R1 consumer of both tools)
7. This document (§ 3 + § 4)

## § 3. Tool 12 — `tools/verify_credentials_load.py`

**Purpose**: CLI shim for the `credentials_loader.load_credentials()` function specified at Round 3 § 3.1. Verifies the credential-loading chain (TPM2 unseal → GPG envelope decrypt → returned-dict shape) at deploy time WITHOUT exposing any plaintext. Round 3 freezes the module body + interface; this supplement freezes the operator surface. The CLI shim's verdict logic lives ENTIRELY in the shim — Tool 12 inspects the returned `CredentialsDict` keys against an operator-supplied required-key set and produces 0/1/2 exit-code mapping per D74.

**Wraps**: Round 3 § 3.1 `credentials_loader.load_credentials(envelope_path: str, passphrase_source: Literal["env", "file"], passphrase_file_path: str | None) -> CredentialsDict` per canonical signature at `phase1/03_core_modules.md` § 3.1 (L728-L769) + `phase1/02_configuration.md` § 3.3 (interface canonical). `CredentialsDict` is a `NewType` wrapping `dict[str, str]` whose keys match the `.env` `*_PASSWORD` / `SNOWFLAKE_PRIVATE_KEY_PEM` placeholder names. **The wrapped function returns only the dict — no metadata dataclass, no boolean flags, no per-stage status. Tool 12's verdict is derived from (a) whether the wrapped function returned vs raised, and (b) whether the returned dict contains the operator-supplied required-key set.**

**Consumes**:
- Decisions: D6 (vault credentials live here), D27 (cross-server parity), D64 (GPG envelope + TPM2 sealing), D67, D74-D77 (R4 conventions), D85 (module startup sequence stage 1), D103 (Claude Code security model — credentials live OUTSIDE `/debi`)
- Round 1: `PipelineEventLog` schema (`EventType` enum extends per Round 4 D76)
- Round 2 § 3.1 (envelope spec) + § 3.2 (D64 TPM2 rationale) + § 3.3 (loader interface canonical at `phase1/02_configuration.md`)
- Round 3 § 3.1: `credentials_loader.load_credentials()` returning `CredentialsDict` — the wrapped function performs TPM2 unseal + GPG decrypt + caches per process; raises `CredentialsLoadError` (`PipelineFatalError`) on envelope-missing / GPG-failed / TPM2-failed / sentinel-loop / schema-version-mismatch; raises `VaultConfigError` on `VAULT_DB_*` env-keys missing
- Round 3 § 6.3: `event_tracker.track()` for the audit row
- Round 3 § 6.1: `SensitiveDataFilter` (regex-based masking applied to BOTH stderr AND PipelineEventLog Metadata to ensure no accidental envelope-content leak)
- D103: credentials envelope lives at `/etc/pipeline/credentials.json.gpg` (mode 0640 + `pipeline:pipeline`); TPM2-sealed passphrase per D64

**Produces**:
- **stdout** (success, all required keys present): `✅ Credentials envelope decrypted; required keys present (N/N); optional keys present (M/M)` — N and M are real counts derived from operator-supplied required + optional key sets; no plaintext rendering of any key value
- **stdout** (`--json`): a CLI-shim-authored JSON document containing `actor: str`, `envelope_path: str`, `invoked_at: ISO8601 str`, `envelope_sha256: str` (from PipelineEventLog Metadata per R3 § 3.1), `required_keys_present_count: int`, `required_keys_total: int`, `optional_keys_present_count: int`, `optional_keys_total: int`, `missing_required_keys: list[str]` (sorted; key NAMES only, never values), `missing_optional_keys: list[str]` (sorted), `exit_code: int`. **NEVER includes the `CredentialsDict` content** — no key VALUES, only key NAMES. SensitiveDataFilter applied as a defense-in-depth layer
- **PipelineEventLog**: ONE row with `EventType='CLI_VERIFY_CREDENTIALS_LOAD'`, `Status` in {`SUCCESS`, `FAILED`}, `Metadata` JSON containing the same fields as the `--json` output PLUS `error_type` (one of `'CredentialsLoadError'`, `'VaultConfigError'`, or null on success) and `error_message` (filtered through SensitiveDataFilter on raise); per D76 the audit row is always written (even on dry-run-style invocations)
- **stderr** (failure): structured error message naming the canonical error class (e.g., `FAIL: CredentialsLoadError raised; envelope_sha256=<hash>; investigate via tpm2_pcrread + ausearch -k pipeline_secrets per RB-6`) — the wrapped function's exception message is filtered through `SensitiveDataFilter` before being printed; root cause stays in the structured error class, not in free-text leakage

**Invocation patterns**:
- **RB-14 pre-flight** (primary): `sudo -u pipeline /opt/pipeline/current/tools/verify_credentials_load.py --dry-run --actor pipeline` — runs as part of RB-14 Step 3 pre-flight smoke test; exit 0 confirms the migration target server can still load credentials post-migration
- **Phase 2 R1 deploy verification** (secondary): after Phase 1 artifact deploy to dev/test/prod, verify credentials still load before proceeding to next round
- **Operator ad-hoc** (occasional): "are credentials currently loadable on this server?" — read-only, no side effects beyond audit row
- **Pipeline** (NEVER): pipeline itself uses `credentials_loader.load_credentials()` directly at startup per D85 Stage 1; the CLI shim exists for OPERATOR-driven verification, not pipeline-internal use

**Idempotency** (per D15): read-only on filesystem; TPM2 unseal is read-only (does not consume a one-time pad); GPG decrypt is read-only on the envelope; INSERT-only on `PipelineEventLog`. Per Round 3 § 3.1 — "re-invocation produces a NEW audit row (intentional — each verification is its own audit moment)". Multi-invocation in close succession is safe; no rate-limit needed.

**Error modes** (per D68 + Round 4 § 1.8). The wrapped function raises only TWO error classes per Round 3 § 3.1 canonical; the CLI shim derives the rest from inspecting the returned `CredentialsDict`:

- **Wrapped-function exceptions** (raised by `load_credentials()` per R3 § 3.1):
  - `CredentialsLoadError` (`PipelineFatalError`) — envelope missing / unreadable, GPG decrypt failed, `tpm2_unseal` returned non-zero, JSON schema_version mismatch, or sentinel `'GPG_SOURCED'` reappeared in decrypted dict (loop / re-substitution bug per R3 § 3.1). **Tool 12 catches this, writes `Status='FAILED'` audit row with `error_type='CredentialsLoadError'`, prints filtered stderr, → exit 2**
  - `VaultConfigError` (`PipelineFatalError`) — `VAULT_DB_*` env keys missing or unreachable. **Tool 12 catches this, writes `Status='FAILED'` audit row with `error_type='VaultConfigError'`, → exit 2**
- **CLI-shim-derived verdicts** (from inspecting the returned dict's keys vs operator-supplied key sets):
  - Wrapped function returned successfully + ALL required keys present + ALL optional keys present → exit 0
  - Wrapped function returned successfully + ALL required keys present + SOME optional keys missing → exit 1 (warning-tier per D74 "expected operational failure"; pipeline can proceed; operator review)
  - Wrapped function returned successfully + SOME required keys missing → exit 2 (fatal; the envelope decrypted but its contents don't satisfy this server's required-key contract — operator must investigate why the envelope is missing expected keys)
- **No retry**: wrapped function is fail-fast per R3 § 3.1; the CLI shim does not retry either.

**Concurrency**: synchronous; single-threaded; no locking needed (read-only). Multiple operators running this in parallel is fine — each produces its own audit row.

**CLI interface**:

```bash
# RB-14 pre-flight (primary use) — verify envelope decrypt still works post-migration
sudo -u pipeline /opt/pipeline/current/tools/verify_credentials_load.py --actor pipeline

# Operator ad-hoc with full JSON output for piping
sudo -u pipeline /opt/pipeline/current/tools/verify_credentials_load.py --json

# Phase 2 R1 dev deploy verification with explicit required-key set
sudo -u pipeline /opt/pipeline/current/tools/verify_credentials_load.py \
    --require ORACLE_PASSWORD,MSSQL_PASSWORD,SNOWFLAKE_PRIVATE_KEY_PEM \
    --actor pipeline
```

**Tool-specific arguments** (in addition to D75 canonical args `--actor`, `--justification`, `--json`, `--verbose`, `--quiet`):

| Argument | Type | Default | Semantics |
|---|---|---|---|
| `--envelope-path` | path | `/etc/pipeline/credentials.json.gpg` per D103 + R3 § 3.1 | Override the GPG envelope path. Maps to the wrapped function's `envelope_path` parameter |
| `--passphrase-source` | choice | `env` per R3 § 3.1 | One of `env` / `file`. Maps to the wrapped function's `passphrase_source` parameter. `env` reads from `GPG_PASSPHRASE` env var (post-TPM2-unseal); `file` reads from `--passphrase-file-path` |
| `--passphrase-file-path` | path \| None | `None` | Required when `--passphrase-source=file`. Maps to the wrapped function's `passphrase_file_path` parameter |
| `--require` | comma-separated | empty (no required-key constraint enforced by the shim) | Operator-supplied required-key NAMES. When the wrapped function returns successfully, the shim asserts every name in this list appears in the returned `CredentialsDict`. Useful for partial-deploy verification (e.g., dev environment without Snowflake) |
| `--optional` | comma-separated | empty | Operator-supplied optional-key NAMES. Missing optional keys → exit 1 warning-tier; missing required keys → exit 2 fatal |

**Note on `--dry-run`**: Tool 12 has NO `--dry-run` argument. The wrapped function is read-only on filesystem (TPM2 unseal + GPG decrypt + cache); the only side-effect is the PipelineEventLog audit row, which is mandatory per D76 and not suppressible. Per D75 dry-run convention is reserved for tools with destructive operations to preview; verification tools that are intrinsically read-only do NOT take `--dry-run`.

**Stdout** (success): `✅ Credentials envelope decrypted; required keys present (N/N); optional keys present (M/M)`

**Stdout** (`--json`):

```json
{
  "actor": "pipeline",
  "envelope_path": "/etc/pipeline/credentials.json.gpg",
  "envelope_sha256": "<hash from PipelineEventLog Metadata per R3 § 3.1>",
  "invoked_at": "2026-05-11T14:23:01Z",
  "required_keys_present_count": 3,
  "required_keys_total": 3,
  "optional_keys_present_count": 5,
  "optional_keys_total": 5,
  "missing_required_keys": [],
  "missing_optional_keys": [],
  "error_type": null,
  "exit_code": 0
}
```

**Exit codes** (per D74):
- **0**: wrapped function returned successfully + all `--require` keys present in returned dict + all `--optional` keys present (or both lists empty)
- **1**: wrapped function returned successfully + all `--require` keys present BUT some `--optional` keys missing (warning-tier; pipeline can proceed; operator review)
- **2**: ANY of: wrapped function raised `CredentialsLoadError`, wrapped function raised `VaultConfigError`, wrapped function returned successfully BUT some `--require` keys missing, OR unexpected exception (pipeline MUST NOT proceed; investigate before retry)

**Tier 0 smoke test** (per D77 — 6 canonical assertions; `tests/smoke/test_tools_verify_credentials_load.py` runs in <5s with mocked subprocess + mocked cursor):

1. (import) module imports without error
2. (help) `--help` exits 0
3. (success) mocked `load_credentials` returning `CredentialsDict({'ORACLE_PASSWORD': '<masked>', 'MSSQL_PASSWORD': '<masked>'})` + `--require ORACLE_PASSWORD,MSSQL_PASSWORD` → exit 0; one `CLI_VERIFY_CREDENTIALS_LOAD` event row with `Status=SUCCESS`; JSON output's `required_keys_present_count` equals 2
4. (warning) mocked returning all required keys present + optional missing → exit 1; event row with `Status=SUCCESS` + Metadata `missing_optional_keys` populated as sorted list
5. (fatal canonical) mocked raising `CredentialsLoadError` → exit 2; event row with `Status=FAILED` + Metadata `error_type='CredentialsLoadError'`; stderr filtered through SensitiveDataFilter
6. (sensitive-data filter) mocked dict returning a value matching the SensitiveDataFilter regex (e.g., a string starting with `-----BEGIN RSA PRIVATE KEY-----`) → assert that value NEVER appears in stdout/stderr/PipelineEventLog Metadata; only the KEY NAME appears in any output

**Test surface (Round 5 extension)**:
- Tier 1: per-canonical-error-class exit-code mapping (`CredentialsLoadError` → 2; `VaultConfigError` → 2; unexpected exception → 2)
- Tier 1: shim-derived verdict mapping (all required present + all optional present → 0; all required present + some optional missing → 1; some required missing → 2)
- Tier 1: `--require` + `--optional` argument parsing (CSV → set) + intersection logic against returned dict's keys
- Tier 1: `--envelope-path` + `--passphrase-source` + `--passphrase-file-path` correctly threaded to wrapped function
- Tier 2 (Hypothesis property): arbitrary `CredentialsDict` (Hypothesis strategy generates `dict[str, str]` with constrained key names) + arbitrary required/optional sets → exit code matches the deterministic rule (no spurious wins or losses)
- Tier 3 (integration): Docker fixture with a real GPG envelope sealed against a test TPM2 emulator (per Round 5 § Tier 3 patterns); exercises full chain end-to-end including SensitiveDataFilter on real envelope content

**Cross-doc references**: Round 3 § 3.1 (`credentials_loader`); D27 + D64 + D74-D77 + D85 + D103; B182 (RB-14 pre-flight consumer; ⚫ CLOSED via RB-14 authoring); B184 (this tool's authoring closes B184); RB-14 (`05_RUNBOOKS.md` L1297+); Phase 2 R1 (`phase2/00_phase_overview.md` R1 prereq #1).

---

## § 4. Tool 13 — `tools/capture_parity_baseline.py`

**Purpose**: Probe the current server's state (RHEL version + kernel; Python version + pip freeze hash; native libraries Oracle Instant Client / ODBC Driver 18 / mssql-tools18 / GPG; required env vars; filesystem layout with owner/mode; systemd unit; TPM2 + PCR policy; credentials envelope SHA-256 + recipient fingerprints; UdmTablesList expected-columns hash) and produce the canonical `parity_baseline.json` per **Round 2 § 4.1 nested-object schema** (`phase1/02_configuration.md` L820-L915). Consumed by `tools/verify_server_parity.py` (R4 § 3.7) at every pipeline startup.

**Wraps**: NEW module function — `data_load/parity_baseline_capture.capture_baseline(output_path: str, pinned_by: str, pipeline_version: str, *, dry_run: bool = False) -> dict` (per **D92** forward-only additive schema-evolution governance; this is a NEW module function, not a modification to any locked Round 3 module). The function performs the probes synchronously and returns a `dict` whose JSON serialization is byte-equivalent to the canonical R2 § 4.1 schema. **No intermediate dataclass is introduced** — the returned object IS the canonical schema, ensuring zero divergence between capture-time output and verify-time read.

**Canonical schema reference**: `phase1/02_configuration.md` § 4.1 L820-L915 defines the baseline JSON as a flat nested-object structure with these top-level keys: `schema_version` (str, currently `"1.0"`), `baseline_name` (str), `pinned_at` (ISO8601 str), `pinned_by` (str), `pipeline_version` (str), and these sub-objects: `operating_system` (`distro` / `version` / `kernel` / `kernel_match_policy`), `python` (`version` / `version_match_policy` / `pip_freeze_sha256` / `pip_lockfile_path`), `native_libraries` (`oracle_instant_client_version` / `oracle_instant_client_dir` / `odbc_driver_version` / `odbc_driver_name` / `mssql_tools_version` / `mssql_tools_dir` / `gpg_version`), `env_vars_required` (dict of expected `KEY: value`), `filesystem_layout` (list of `{path, owner, mode, must_exist}` records), `systemd_unit` (`path` / `sha256` / `must_have_env_vars`), `tpm2` (`required` / `pcr_policy_hash` / `tpm2_tools_version`), `credentials_envelope` (`path` / `sha256` / `schema_version` / `recipient_count` / `primary_recipient_fingerprint` / `breakglass_recipient_fingerprint`), `udm_tables_list_schema` (`spec_doc` / `expected_columns_sha256` / `expected_check_constraints`), `documented_exceptions` (list of `{key, dev_value, test_value, prod_value, rationale, expires_at, owner}` records — empty on initial capture). **The `checks` array (with `ParityCheck` items per R2 § 4.2) is NOT part of the baseline schema — it is the verifier's OUTPUT structure. The baseline IS the input that drives those checks.**

**Consumes**:
- Decisions: D27 (parity contract), D55 (5-gate validation — applied at capture time), D65 (drift severity classification — capture sets the baseline against which `verify_server_parity` tiers drift), D67, D74-D77 (R4 conventions), D92 (additive new module — no rename or removal of locked Round 3 modules), D103 (output path inside `/etc/pipeline/` per L862-L867 of R2 § 4.1 filesystem_layout)
- Round 2 § 4.1 (L820-L915): canonical baseline JSON schema (the EXACT contract this tool produces; schema_version `"1.0"` per L826)
- Round 2 § 4.3: documented_exceptions structure (empty on initial capture; populated by operators post-capture for known-divergent fields)
- Round 4 § 3.7: `verify_server_parity.py` consumer (the JSON this tool produces is the input that `verify_server_parity` reads at every pipeline startup)
- Phase 0 deliv 0.11: this tool's first invocation on each server CLOSES the operational portion of 0.11 (parity baseline established per D27)

**Produces**:
- **Output file**: `/etc/pipeline/parity_baseline.json` at `--output-path` (default per R2 § 4.1 L862-L867 filesystem_layout `must_exist: true` contract; the default writes to the canonical location for immediate verify_server_parity consumption). File content conforms byte-equivalently to the canonical R2 § 4.1 schema (L820-L915)
- **stdout** (success): human-readable summary table of probed fields + their captured values (see Stdout example below); final line `Baseline captured; output written to <path> (schema R2 § 4.1)`
- **stdout** (`--json`): the captured dict serialized to JSON; byte-equivalent to file content; canonical R2 § 4.1 schema verbatim
- **stdout** (`--dry-run`): captured values shown but NO file written
- **PipelineEventLog**: ONE row with `EventType='CLI_CAPTURE_PARITY_BASELINE'`, `Status` in {`SUCCESS`, `FAILED`}, `Metadata` JSON containing `actor`, `pinned_by`, `pipeline_version`, `output_path`, `dry_run`, `exit_code`, `probes_failed_count`, `capture_duration_ms`, `server_name`, `baseline_sha256` (of the captured JSON content, useful for downstream comparison). **Per D76**, the audit row is mandatory; even dry-run produces an audit row (the row's Metadata flags `dry_run=true`).

**Invocation patterns**:
- **Phase 2 R1 prerequisite** (primary): operator runs this ONCE per server during Phase 2 R1 dev/test/prod deploy preparation: `sudo -u pipeline /opt/pipeline/current/tools/capture_parity_baseline.py --pinned-by pipeline-lead --pipeline-version 1.0.0 --actor pipeline` (then on test, then on prod — per-server, in sequence with check-pause-check)
- **Phase 2 R3 cutover prep** (also valid): re-capture immediately before production cutover if pipeline version has bumped since the R1 capture
- **Operator ad-hoc** (occasional): "what does the current server look like?" with `--dry-run` to preview without overwriting the canonical baseline
- **Pipeline** (NEVER): pipeline only CONSUMES the baseline via `verify_server_parity`; it does NOT produce baselines (humans-in-the-loop produce them so drift is intentional, not accidental)
- **Automic** (NEVER): no scheduled job for this; baseline capture is human-driven per D27 governance

**Idempotency** (per D15 + D26 + D92):
- Dry-run is read-only on filesystem
- Apply-mode writes to a single output path; **the file is overwrite-only** (no append, no versioning at the filesystem level — versioning is via git on the host's repo containing parity_baseline.json + the `pinned_at` timestamp + `pipeline_version` fields inside the JSON per canonical R2 § 4.1)
- Re-capture on the same server in close succession produces a NEW baseline that may diverge slightly (e.g. `env_vars_required.MALLOC_ARENA_MAX` could be different if env var changed; `python.pip_freeze_sha256` could differ post-package-update). This is intentional — the baseline IS the snapshot; recapturing means "new snapshot moment".
- **Important**: re-capture does NOT preserve the `documented_exceptions` list from the prior baseline. Operators MUST re-add documented exceptions after a re-capture. This is by design — exceptions are a governance decision per R2 § 4.3, not a probe result, and forcing re-review prevents stale exceptions from masking real drift. (See B-future candidate: `parity_baseline_merge_exceptions.py` for an optional helper if recapture frequency increases.)

**Error modes** (per D68). Note: the canonical R2 § 4.1 baseline schema has NO per-field `severity` attribute — severity emerges at VERIFICATION time when `verify_server_parity()` produces its `ParityCheck` outputs per R2 § 4.2. Tool 13's "probe failed" case is recorded INSIDE the canonical baseline JSON via (a) the failed field's value set to the sentinel string `"<probe_failed>"`, AND (b) an auto-populated entry in `documented_exceptions` (per R2 § 4.1 L903-L913) following this mapping:

- `key`: dotted path of the failed field (e.g., `"native_libraries.gpg_version"`)
- `dev_value` / `test_value` / `prod_value`: ALL three set to the sentinel `"<probe_failed>"` (the capturing server only knows its own probe-failed result; the other two environments' values are unknown at capture time and re-capture on each env will overwrite this auto-entry with concrete values)
- `rationale`: literal `"Auto-populated by capture_parity_baseline.py — probe for <field-path> failed during baseline capture; manual review + re-capture required"`
- `expires_at`: `pinned_at + 30 days` (per R2 § 4.3 documented_exceptions semantics, expired exceptions are auto-rejected by `verify_server_parity` — this forces operator re-review within a month)
- `owner`: value of `--pinned-by` argument (the operator who ran the capture is the implicit owner of any auto-flagged gap)

This keeps the baseline structurally conformant with R2 § 4.1 while preserving the audit trail of the partial-capture event. Operators are expected to investigate the failed probe + either fix the underlying issue OR replace the auto-populated entry with a hand-authored exception that carries true per-environment values + a real rationale.

- `ProbeFailedError` (a single probe failed — e.g. `rpm -q gpg2` returned non-zero) → exit 1 (warning-tier per D74); partial baseline captured with the failed field set to `"<probe_failed>"` AND a `documented_exceptions` entry auto-populated
- `OutputPathNotWritableError` → exit 2; stderr: `FAIL: output path <path> not writable; check ownership + mode (expected pipeline:pipeline 0640 on /etc/pipeline/)`
- `InsufficientPermissionsError` (probe required sudo but invoked without) → exit 2
- `SELinuxEnforcingButContextWrongError` (output path exists but has wrong SELinux context, preventing write even with correct POSIX perms) → exit 2; stderr: `FAIL: SELinux context on <path> blocks write; run: sudo restorecon -v <path>`
- All probes succeeded + file written → exit 0
- All probes succeeded + dry-run (no file written) → exit 0

**Concurrency**: synchronous; single-threaded. Multiple operators capturing simultaneously on the SAME server is a race — last-write wins; the audit-row trail records which capture finally landed. Recommend operator-coordination to avoid concurrent captures.

**CLI interface**:

```bash
# Phase 2 R1 baseline capture (primary use); --pinned-by is the canonical R2 § 4.1 field
sudo -u pipeline /opt/pipeline/current/tools/capture_parity_baseline.py \
    --pinned-by pipeline-lead --pipeline-version 1.0.0 --actor pipeline

# Preview without writing (dry-run)
sudo -u pipeline /opt/pipeline/current/tools/capture_parity_baseline.py \
    --pinned-by pipeline-lead --pipeline-version 1.0.0 --dry-run

# Capture to alternate path (pre-deployment review)
sudo -u pipeline /opt/pipeline/current/tools/capture_parity_baseline.py \
    --output-path /tmp/new_baseline.json --pinned-by pipeline-lead --pipeline-version 1.0.0

# Full JSON output for piping into a comparison tool
sudo -u pipeline /opt/pipeline/current/tools/capture_parity_baseline.py \
    --pinned-by pipeline-lead --pipeline-version 1.0.0 --json --dry-run | jq '.'
```

**Tool-specific arguments** (in addition to D75 canonical args `--actor`, `--justification`, `--json`, `--verbose`, `--quiet`, `--dry-run`):

| Argument | Type | Default | Semantics |
|---|---|---|---|
| `--pinned-by` | str | required (no default — operator MUST declare who is pinning to prevent silent baselining) | Canonical R2 § 4.1 `pinned_by` field. Records the human-readable identity of the pipeline lead authorizing the capture |
| `--pipeline-version` | str | required (no default — operator MUST declare which pipeline release this baseline corresponds to) | Canonical R2 § 4.1 `pipeline_version` field (e.g. `"1.0.0"`). Used by `verify_server_parity` to detect deploy-version drift |
| `--output-path` | path | `/etc/pipeline/parity_baseline.json` per R2 § 4.1 + L862-L867 filesystem_layout | Override the output JSON path. The default writes the canonical location consumed by `verify_server_parity.py` |
| `--baseline-name` | str | `f"pipeline-baseline-v{pipeline_version}"` per R2 § 4.1 L827 example | Override the canonical R2 § 4.1 `baseline_name` field. Useful for forked baselines (e.g., during canary testing) |
| `--no-tpm2` | flag | False (TPM2 probed by default per R2 § 4.1 L878-L882) | Skip TPM2 probing. When set, the `tpm2.pcr_policy_hash` field is recorded as `"<unavailable>"` with a documented-exception entry auto-populated to flag the gap |

**Stdout** (success) — human-readable summary derived from the captured JSON; the JSON itself is the canonical R2 § 4.1 schema:

```
Parity baseline capture — server: udm-prod-1
  schema_version              : 1.0
  baseline_name               : pipeline-baseline-v1.0.0
  pinned_at                   : 2026-05-11T14:23:01Z
  pinned_by                   : pipeline-lead
  pipeline_version            : 1.0.0
  operating_system.distro     : RHEL
  operating_system.version    : 9.4
  operating_system.kernel     : 5.14.0-427.13.1.el9_4.x86_64
  python.version              : 3.12.11
  python.pip_freeze_sha256    : sha256:abc123...
  native_libraries.oracle_*   : 19.21.0 @ /opt/oracle/instantclient_19_21
  native_libraries.odbc_*     : 18.3.2.1-1 @ ODBC Driver 18 for SQL Server
  native_libraries.mssql_*    : 18.3.2.1-1 @ /opt/mssql-tools18
  native_libraries.gpg_version: 2.3.3-2.el9
  env_vars_required           : 3 keys captured (MALLOC_ARENA_MAX, ORACLE_HOME, LD_LIBRARY_PATH)
  filesystem_layout           : 7 paths captured (per R2 § 4.1 L862-L870)
  systemd_unit.sha256         : sha256:xyz789...
  tpm2.pcr_policy_hash        : sha256:def456...
  credentials_envelope.sha256 : sha256:fedcba...
  udm_tables_list_schema.expected_columns_sha256: sha256:9876ab...
  documented_exceptions       : 0 (initial capture; operators add post-capture per R2 § 4.3)
Baseline captured; output written to /etc/pipeline/parity_baseline.json (schema R2 § 4.1)
```

**Stdout** (`--json`): canonical R2 § 4.1 schema verbatim (byte-equivalent to file content) — see `phase1/02_configuration.md` L820-L915 for the full schema example.

**Exit codes** (per D74):
- **0**: all probes succeeded; file written (or dry-run with all probes succeeded)
- **1**: at least one probe raised `ProbeFailedError` (e.g., TPM2 probe attempted but `tpm2_getcap` returned non-zero — independent of `--no-tpm2` opt-out); file written with the failed field set to sentinel `"<probe_failed>"` AND a `documented_exceptions` entry auto-populated per R2 § 4.1 L903-L913
- **2**: output path not writable OR insufficient permissions OR SELinux context blocks write (file NOT written; operator must remediate before retry)

**Tier 0 smoke test** (per D77 — 6 canonical assertions; `tests/smoke/test_tools_capture_parity_baseline.py` runs in <5s with mocked subprocess for all probes + mocked filesystem):

1. (import) module imports without error
2. (help) `--help` exits 0
3. (success-apply) mocked probes all succeed → exit 0; mocked filesystem `write_text` invoked once with JSON content matching canonical R2 § 4.1 top-level keys (`schema_version`, `baseline_name`, `pinned_at`, `pinned_by`, `pipeline_version`, `operating_system`, `python`, `native_libraries`, `env_vars_required`, `filesystem_layout`, `systemd_unit`, `tpm2`, `credentials_envelope`, `udm_tables_list_schema`, `documented_exceptions`); one `CLI_CAPTURE_PARITY_BASELINE` event row with `Status=SUCCESS`
4. (success-dry-run) `--dry-run` → exit 0; filesystem `write_text` NOT invoked; event row with Metadata `dry_run=true` + `output_path_would_be=<path>`
5. (warning-probe-failed) one mocked probe raises `ProbeFailedError` (e.g. `rpm -q gpg2` returns non-zero) → exit 1; file written with that field's value set to `"<probe_failed>"` and a `documented_exceptions` entry auto-populated naming the failed probe; event row with `Status=SUCCESS` + Metadata `probes_failed_count=1`
6. (fatal-write-permission) mocked `Path.write_text` raises `PermissionError` → exit 2; event row with `Status=FAILED` + Metadata `error_type='OutputPathNotWritableError'`; file NOT written

**Test surface (Round 5 extension)**:
- Tier 1: each probe function in isolation (RHEL distro/version/kernel probe; `pip freeze` SHA probe; Oracle Instant Client version probe; ODBC Driver 18 probe; mssql-tools18 probe; GPG version probe; required-env-var presence probe; filesystem-layout `stat` probe per path; systemd unit SHA probe; TPM2 PCR + tpm2-tools probe; credentials envelope SHA probe; UdmTablesList schema-hash probe per R2 § 1)
- Tier 1: round-trip — captured JSON → `verify_server_parity` consumes it without raising `ParityBaselineMissing` (schema-conformance check)
- Tier 1: schema-version pinning — captured `schema_version` matches canonical `"1.0"` per R2 § 4.1 L826 (test fails if canonical schema_version changes without this tool updating)
- Tier 2 (Hypothesis property): arbitrary set of probe outputs → resulting JSON validates against the canonical R2 § 4.1 schema shape (no field omission; no extra fields; no nested-object rearrangement)
- Tier 3 (integration): Docker fixture with a known-good RHEL image; capture against it; round-trip through `verify_server_parity` returns `overall='pass'` (catches probe-implementation drift end-to-end)

**Cross-doc references**: Round 2 § 4 (baseline JSON canonical); Round 3 § 3.2 (`server_parity_verifier` — sibling consumer); Round 4 § 3.7 (`verify_server_parity.py` — operational consumer); D27 + D55 + D65 + D74-D77 + D92 + D103; B12 (Phase 0 deliv 0.11 main backlog item; ⚫ CLOSED 2026-05-11 with B183 as residual); B183 (this tool's authoring closes B183); Phase 2 R1 (`phase2/00_phase_overview.md` R1 prereq #6).

---

## § 5. Cross-tool considerations

### § 5.1 Order of invocation during Phase 2 R1 deploy

The two tools have a strict invocation order during Phase 2 R1 setup, per the Phase 2 plan (`phase2/00_phase_overview.md` § Round 1):

1. **Pre-deploy**: `verify_credentials_load.py` on the CURRENT system (before RB-14) — confirms credentials currently load from `/debi/.env`
2. **RB-14 migration**: apply per server (dev → test → prod)
3. **Post-migration**: `verify_credentials_load.py` on the migrated system — confirms credentials still load from `/etc/pipeline/.env`
4. **Baseline capture**: `capture_parity_baseline.py --pinned-by <pipeline-lead> --pipeline-version <release>` per server — first capture establishes the canonical baseline per R2 § 4.1
5. **Verify gate**: `verify_server_parity.py` (R4 § 3.7) — verifies the captured baseline is self-consistent

Skipping step 1 means RB-14 rollback may be needed without warning. Skipping step 3 means the migration's correctness is unverified. Skipping step 4 means `verify_server_parity` at pipeline startup has nothing to verify against (D85 Stage 3 fails closed).

### § 5.2 D85 supersession candidate (carryover from RB-14 known-issues)

The Round 3 § 3.1 `credentials_loader.load_credentials()` function spec references the .env file at `/debi/.env` (per D85 Stage 1 narrative locked at Round 6 close-out 2026-05-10). Post-D103, the canonical path is `/etc/pipeline/.env`. Per D92 forward-only, D85 cannot be edited in place; D103 supersedes the path clause implicitly.

The `credentials_loader` module function MUST default to `/etc/pipeline/.env` at implementation time (per D103) but the spec doc at Round 3 § 3.1 still cites `/debi/.env`. This supplement notes the implementation contract (D103 wins) but does NOT modify Round 3. **Tracked as a candidate for an explicit D85-supersession decision OR a Round 3.5 supplement at Phase 2 R1 close-out** — surface to pipeline lead for ratification.

### § 5.3 Validation gates

This supplement is itself an artifact subject to the D55 5-gate discipline (cross-reference / QA / edge cases / edge case validation / idempotency-regression) + D56 mandatory second-pass-after-🔴 + D62 CCL + Pattern F at close-out. Validation log entry to follow at completion. **First production validation 2026-05-11 found 5 🔴 + 8 🟡 (Trigger B canonical-source contradictions on Tool 12 `LoadedCredentials` fabrication + Tool 13 `ParityBaseline.checks` field invention; Trigger C stale RB-14 loci; Trigger D § 4.1.1 forward-cite); fix-application cycle applied same session per D56.**

**Edge cases addressed**:
- **F22** (parity drift severity): both tools encode D65 fatal/warning/informational tiers consistently
- **F23** (parity exception expiration): `capture_parity_baseline.py` resets `documented_exceptions` on re-capture per § 4 idempotency note
- **P5** (no plaintext PII in logs): `verify_credentials_load.py` applies SensitiveDataFilter per Tier 0 assertion 6
- **D103 working-directory boundary**: both tools default output to `/etc/pipeline/` (outside `/debi`); audit-row paths recorded in PipelineEventLog never include credential values

**Edge cases NOT addressed** (out of scope; deferred to Phase 2 R1 or later):
- **F-future**: multi-host parallel capture (operators currently run per-server; B-future may add a wrapper script)
- **F-future**: baseline-merge-exceptions helper (re-capture wipes `documented_exceptions`; operators currently re-add manually; B-future candidate for a merge helper if frequency increases)

## § 6. Validation gates (per D55 + D56 + D62 + Pattern F)

This supplement's acceptance criteria:

- ✅ Gate 1 (cross-reference): every D-number cited resolves to the locked decision; every R3/R4 spec section cited has the canonical line range; no contradictions with locked Round 3 + Round 4 specs
- ✅ Gate 2 (QA): independent agent review (Pattern F Layer 2 paired-judgment at close-out)
- ✅ Gate 3 (edge case enumeration): M / S / I / N / P / G / D / F / V walk applied to both tool specs
- ✅ Gate 4 (edge case validation): every "addressed" case has a concrete spec element pointing to the mechanism
- ✅ Gate 5 (idempotency / regression): D92 forward-only respected; no Round 3 or Round 4 spec modifications; pre-D78 tool inventory grandfathered

## § 7. Cross-references

- **D27** (cross-server parity contract) — operational foundation for Tool 13
- **D55 + D56 + D62** (validation discipline) — applies to this supplement (D72 cycle-termination + D89-D91 Pattern F apply at any Round-N.5 supplement close-out)
- **D64** (GPG envelope + TPM2 sealing) — Tool 12's verification chain
- **D65** (drift severity classification) — drives `verify_server_parity`'s severity tiering against the baseline Tool 13 produces
- **D67** (Tier 0 smoke discipline) — both tools have Tier 0 scaffolds
- **D70** (6-tier test fixture strategy / pyramid) — Test Surface sections in § 3 + § 4 follow R3 test pyramid (Tier 0 → 1 → 2 → 3)
- **D74-D77** (R4 CLI conventions) — both tools follow
- **D85** (module startup sequence) — Tool 12's Stage 1 consumer (Tool 13's output read at Stage 3)
- **D92** (forward-only additive schema evolution) — supplement authoring discipline
- **D100** (documentation supplement Round-N.5 mini-round pattern) — this supplement's pattern
- **D103** (Claude Code security model) — output path discipline
- **B12** (Phase 0 deliv 0.11 baseline; ⚫ CLOSED 2026-05-11 with B183 as residual) — Tool 13 closes the operational loop
- **B13** (Phase 0 deliv 0.12 GPG credentials; ⚫ CLOSED 2026-05-11 via D103) — Tool 12 closes the verification loop
- **B182** (`.env` migration runbook; ⚫ CLOSED via RB-14 authoring) — Tool 12 enables RB-14 pre-flight
- **B183** (parity baseline capture script) — closed by Tool 13 authoring (this supplement)
- **B184** (verify_credentials_load CLI shim) — closed by Tool 12 authoring (this supplement)
- **RB-14** (.env Location Migration) — Tool 12's primary consumer
- **`phase2/00_phase_overview.md` R1** — Phase 2 R1 prerequisites both tools satisfy
- **`phase1/02_configuration.md` § 4** — Round 2 baseline JSON canonical (Tool 13's output schema)
- **`phase1/03_core_modules.md` § 3.1** — Round 3 `credentials_loader` (Tool 12's wrapped module) + § 3.2 `server_parity_verifier` (Tool 13's sibling)
- **`phase1/04_tools.md` § 1** — Round 4 cross-cutting CLI conventions + § 3.7 `verify_server_parity` (Tool 13's operational consumer)

## § 8. How to update this document

This is a living supplement. Per D100 Round-N.5 discipline + D92 forward-only:

- **Additive changes only**: new tool specs (Tool 14, Tool 15, etc.) may be appended as new sections; existing sections (Tool 12, Tool 13) get fix-in-place updates ONLY for typos / cross-reference corrections — substantive changes go through a new D-number supersession
- **Validation discipline**: every substantive update goes through D55 5-gate + D56 second-pass + D62 CCL + Pattern F at close-out
- **Cascade**: any update propagates to `_validation_log.md` + BACKLOG (if B-items affected) + HANDOFF + CURRENT_STATE + GLOSSARY per Pattern F Trigger F
- **Naming**: future supplements to Round 4 use sibling naming `phase1/04b_*.md`, `phase1/04c_*.md`, etc. (per Round 1.5 precedent at `phase1/01a/01b/01c/01d`)
