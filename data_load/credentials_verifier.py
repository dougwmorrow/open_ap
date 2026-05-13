"""B184 — credentials_verifier helpers consumed by ``tools/verify_credentials_load.py``.

Per **phase1/04a_phase_0_prep_tools.md § 3** (canonical Tool 12 spec) +
**D67** (Tier 0 discipline) + **D74** (CLI exit-code contract 0/1/2) +
**D75** (CLI argument naming) + **D76** (audit-row contract; CLI_*
EventType family) + **D77** (Tier 0 6-canonical-assertion scaffold) +
**D85** (module startup sequence stage 1 — credentials_loader) +
**D92** (forward-only additive — this is a NEW module function,
NOT a modification to the locked Round 3 § 3.1 ``credentials_loader``
canonical spec) + **D103** (Claude Code security model;
credentials live OUTSIDE /debi).

What this module does (per canonical spec § 3)
----------------------------------------------

Wraps Round 3 § 3.1 ``credentials_loader.load_credentials(...)`` and
derives the CLI verdict from inspecting the returned ``CredentialsDict``
against an operator-supplied required-key set + optional-key set:

* Wrapped function returned + ALL required keys present + ALL optional
  keys present  -> exit 0 (clean)
* Wrapped function returned + ALL required keys present + SOME optional
  keys missing  -> exit 1 (warning-tier per D74 "expected operational
  failure"; pipeline can proceed; operator review)
* Wrapped function returned + SOME required keys missing  -> exit 2
  (fatal; the envelope decrypted but its contents don't satisfy this
  server's required-key contract — operator must investigate)
* Wrapped function raised ``CredentialsLoadError``                    -> exit 2
* Wrapped function raised ``VaultConfigError``                        -> exit 2
* Wrapped function raised any other exception                         -> exit 2

The verdict logic lives ENTIRELY in this module (per § 3:
"The CLI shim's verdict logic lives ENTIRELY in the shim — Tool 12
inspects the returned CredentialsDict keys against an operator-supplied
required-key set and produces 0/1/2 exit-code mapping per D74.").

Platform-aware skip semantics
-----------------------------

Per **D103** threat-surface inversion (dev > test > prod), the Windows
dev workstation does NOT have TPM2 or kernel keyring. Operators / engineers
running the tool from a Windows dev box must NOT see exit 2 simply
because TPM2 / keyctl probes are unavailable — those probes are
deliberately classified as "skipped" (recorded in the result dict for
audit-row visibility) and ignored in the exit-code derivation. The
canonical security-stack live RHEL probes (TPM2 unseal + keyctl
session keyring) are attempted on Linux only.

No plaintext ever in result / logs / Metadata
---------------------------------------------

Per § 3 + edge case P5 (no plaintext PII in logs): only KEY NAMES — never
VALUES — appear in any output. ``SensitiveDataFilter`` is applied as
defense-in-depth: even if a wrapped function ever leaked plaintext into a
key value, the regex-based scrubber masks PEM blocks / KEY=value style
substrings before the dict is serialized into the Metadata JSON column or
the audit-row ErrorMessage field.

Execution classification (per ``udm-execution-classifier`` skill)
-----------------------------------------------------------------

* **Idempotency**: YES — read-only filesystem (TPM2 unseal + GPG decrypt
  + load_credentials() cache); INSERT-only on PipelineEventLog. Each
  re-invocation produces a NEW audit row (intentional per § 3 — each
  verification is its own audit moment).
* **Trigger**: manual operator CLI (RB-14 pre-flight Step 3; Phase 2 R1
  deploy verification; ad-hoc "are credentials currently loadable?").
* **Frequency**: on-demand, never scheduled (pipeline uses
  ``credentials_loader.load_credentials()`` directly at D85 Stage 1
  startup — NOT this CLI shim).
* **Audit-row family**: ``CLI_VERIFY_CREDENTIALS_LOAD`` per D76 + Round 4
  § 3 (registered in CLAUDE.md ``CLI_*`` family registry).

Wrapped function
----------------

Round 3 § 3.1 ``credentials_loader.load_credentials(envelope_path,
passphrase_source, passphrase_file_path) -> CredentialsDict`` where
``CredentialsDict`` is a ``NewType`` wrapping ``dict[str, str]``. The
wrapped function performs TPM2 unseal + GPG decrypt + caches per process;
raises ``CredentialsLoadError`` (PipelineFatalError) on
envelope-missing / GPG-failed / TPM2-failed / sentinel-loop /
schema-version-mismatch, and ``VaultConfigError`` (PipelineFatalError)
on missing ``VAULT_DB_*`` env keys.

D-numbers consumed
------------------

D6, D15, D27, D62, D64, D67, D74, D75, D76, D77, D85, D92, D103, B184.
"""

from __future__ import annotations

import hashlib
import logging
import os
import platform
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Canonical paths + sentinels per D103 + phase1/04a § 3
# ---------------------------------------------------------------------------

# D103 canonical credential locations (production RHEL).
CANONICAL_ENV_PATH = "/etc/pipeline/.env"
CANONICAL_ENVELOPE_PATH = "/etc/pipeline/credentials.json.gpg"
CANONICAL_KEYRING_KEY = "pipeline"

# D76 EventType registered in CLAUDE.md CLI_* family registry.
EVENT_TYPE = "CLI_VERIFY_CREDENTIALS_LOAD"

# Exit-code constants per D74 contract (Round 4 § 1.8 + R22 — Automic
# interprets these values; deviation causes mis-categorization).
EXIT_SUCCESS = 0
EXIT_WARNING = 1
EXIT_FATAL = 2

# Sentinel substrings the SensitiveDataFilter masks before serialization.
# Anywhere any of these appears in a dict value or stringified payload,
# the matched run gets replaced with "<redacted>". This is defense-in-depth
# only — the primary line of defense is that the wrapped function never
# returns plaintext into a value position in the first place.
_SENSITIVE_REGEXES = (
    # PEM blocks — full ranges (RSA private key / generic private key / etc.)
    re.compile(r"-----BEGIN [A-Z ]+-----.*?-----END [A-Z ]+-----", re.DOTALL),
    # PEM headers alone (in case the body got chopped or we only got a fragment)
    re.compile(r"-----BEGIN [A-Z ]+-----[^\n]*"),
    # KEY=value style leakage (case-insensitive)
    re.compile(r"(?i)\b(?:password|passphrase|secret|token)\s*=\s*\S+"),
)
_REDACTION_PLACEHOLDER = "<redacted>"


# ---------------------------------------------------------------------------
# SensitiveDataFilter — defense-in-depth string scrubber
# ---------------------------------------------------------------------------


def sensitive_redact(text: str) -> str:
    """Mask any sensitive-shaped substring in ``text``.

    Pure-string transformation; idempotent (re-running on an already-
    redacted string produces the same output). Never raises.
    """
    if not isinstance(text, str):
        text = str(text)
    for regex in _SENSITIVE_REGEXES:
        text = regex.sub(_REDACTION_PLACEHOLDER, text)
    return text


def sensitive_redact_dict(payload: Mapping) -> dict:
    """Apply ``sensitive_redact`` recursively to every string value.

    Lists/tuples of strings are scrubbed element-wise; nested dicts
    recurse. Non-string scalars (ints / bools / None) pass through.
    """
    result: dict = {}
    for key, value in payload.items():
        if isinstance(value, str):
            result[key] = sensitive_redact(value)
        elif isinstance(value, dict):
            result[key] = sensitive_redact_dict(value)
        elif isinstance(value, (list, tuple)):
            result[key] = [
                sensitive_redact(v) if isinstance(v, str)
                else sensitive_redact_dict(v) if isinstance(v, dict)
                else v
                for v in value
            ]
        else:
            result[key] = value
    return result


# ---------------------------------------------------------------------------
# Platform detection helpers
# ---------------------------------------------------------------------------


def is_linux() -> bool:
    """True iff running on Linux (the canonical RHEL production target)."""
    return platform.system() == "Linux"


def is_windows() -> bool:
    """True iff running on Windows (the canonical dev workstation per D103)."""
    return platform.system() == "Windows"


def _run_subprocess(
    cmd: list[str],
    *,
    timeout: float = 10.0,
) -> tuple[int, str, str]:
    """Run a subprocess and return ``(returncode, stdout, stderr)``.

    Returns ``(-1, "", "<reason>")`` on FileNotFoundError or TimeoutExpired.
    Stdout/stderr are decoded utf-8 with replace so we can safely substring-
    scan without ever holding raw key material.
    """
    try:
        proc = subprocess.run(  # noqa: S603
            cmd,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        stdout = proc.stdout.decode("utf-8", errors="replace") if proc.stdout else ""
        stderr = proc.stderr.decode("utf-8", errors="replace") if proc.stderr else ""
        return proc.returncode, stdout, stderr
    except FileNotFoundError as exc:
        return -1, "", f"binary not found: {exc}"
    except subprocess.TimeoutExpired:
        return -1, "", "subprocess timed out"
    except Exception as exc:  # noqa: BLE001
        return -1, "", f"subprocess raised: {type(exc).__name__}"


# ---------------------------------------------------------------------------
# Envelope hash helper (D76 audit-row Metadata field per § 3)
# ---------------------------------------------------------------------------


def compute_envelope_sha256(envelope_path: str) -> str:
    """Return the SHA-256 hex of the GPG envelope file, or "<unavailable>".

    The envelope file is the .gpg-encrypted credentials blob. Its SHA-256
    is recorded in the Metadata JSON per § 3 to support forensic
    correlation across servers (different envelopes → different hashes).

    Returns ``"<unavailable>"`` when the file does not exist or cannot be
    read — the verdict can still be derived; the hash is informational.
    """
    try:
        path = Path(envelope_path)
        if not path.exists():
            return "<unavailable>"
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except (OSError, PermissionError):
        return "<unavailable>"


# ---------------------------------------------------------------------------
# Platform-aware checks (recorded for audit; do NOT affect verdict)
# ---------------------------------------------------------------------------


def probe_tpm2(
    envelope_path: str = CANONICAL_ENVELOPE_PATH,
    *,
    runner=_run_subprocess,
) -> str:
    """Best-effort TPM2 unseal probe.

    Returns:
        "passed"   — Linux + ``systemd-creds decrypt`` returned rc=0 + non-empty stdout
        "failed"   — Linux + probe ran but returned non-zero / empty stdout
        "skipped"  — Windows (no TPM2 on dev workstation per D103) OR
                     ``systemd-creds`` binary missing OR envelope path missing

    The decrypted plaintext is NEVER returned or logged — we inspect only
    ``rc`` + ``bool(stdout)`` and discard the buffer.
    """
    if not is_linux():
        return "skipped"
    if not Path(envelope_path).exists():
        return "skipped"
    rc, stdout, _stderr = runner(["systemd-creds", "decrypt", envelope_path])
    if rc == -1:
        return "skipped"
    if rc == 0 and stdout:
        return "passed"
    return "failed"


def probe_keyring(
    key_substring: str = CANONICAL_KEYRING_KEY,
    *,
    runner=_run_subprocess,
) -> str:
    """Best-effort kernel-keyring probe (``keyctl list @s``).

    Returns:
        "passed"   — Linux + keyctl rc=0 + key_substring present in stdout
        "failed"   — Linux + keyctl rc=0 but key_substring NOT present
        "skipped"  — Windows OR keyctl binary missing
    """
    if not is_linux():
        return "skipped"
    rc, stdout, _stderr = runner(["keyctl", "list", "@s"])
    if rc == -1:
        return "skipped"
    if rc != 0:
        return "failed"
    return "passed" if key_substring in stdout else "failed"


def probe_envelope_perms(env_path: str = CANONICAL_ENV_PATH) -> str:
    """Best-effort .env file permission probe.

    Returns:
        "passed"   — POSIX path exists + mode == 0o400 (Linux)
        "failed"   — POSIX path exists but mode != 0o400
        "skipped"  — Windows (POSIX mode bits do not map cleanly to NTFS ACLs;
                     Windows dev workstation .env lives outside the canonical
                     RHEL path per D103) OR file does not exist
    """
    if is_windows():
        return "skipped"
    path = Path(env_path)
    if not path.exists():
        return "skipped"
    try:
        mode = path.stat().st_mode & 0o777
        return "passed" if mode == 0o400 else "failed"
    except OSError:
        return "skipped"


# ---------------------------------------------------------------------------
# Core verdict logic
# ---------------------------------------------------------------------------


def _classify_error(exc: BaseException) -> str:
    """Map a wrapped-function exception to the canonical error_type string.

    Per § 3 error modes — the wrapped function raises only ``CredentialsLoadError``
    or ``VaultConfigError``; any other class indicates an unexpected exception
    path and is reported with its actual class name for forensic clarity.
    """
    return type(exc).__name__


def _verdict_from_keys(
    creds: Mapping[str, str],
    require: Iterable[str],
    optional: Iterable[str],
) -> tuple[int, list[str], list[str]]:
    """Compute (exit_code, missing_required, missing_optional) from key sets.

    Per § 3 exit codes:

    * empty require + empty optional        -> exit 0 (no constraint enforced)
    * all required present + all optional present -> exit 0
    * all required present + some optional missing -> exit 1 (warning)
    * some required missing                  -> exit 2 (fatal)

    Both missing-key lists are sorted (stability requirement per § 3
    Stdout (--json) shape — sorted lists ensure the audit row JSON is
    deterministic across invocations).
    """
    present_keys = set(creds.keys())
    require_set = set(require)
    optional_set = set(optional)

    missing_required = sorted(require_set - present_keys)
    missing_optional = sorted(optional_set - present_keys)

    if missing_required:
        return EXIT_FATAL, missing_required, missing_optional
    if missing_optional:
        return EXIT_WARNING, missing_required, missing_optional
    return EXIT_SUCCESS, missing_required, missing_optional


def _iso_utc_now() -> str:
    """Return current UTC time in ISO 8601 with 'Z' suffix per § 3 Stdout."""
    return datetime.now(timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Top-level verifier (consumed by tools/verify_credentials_load.py)
# ---------------------------------------------------------------------------


def run_verification(
    *,
    require: Iterable[str] | None,
    optional: Iterable[str] | None,
    envelope_path: str,
    actor: str | None,
    server: str | None,
    load_credentials_fn,
    credentials_load_error_cls: type[BaseException],
    vault_config_error_cls: type[BaseException],
    run_platform_probes: bool = True,
    runner=_run_subprocess,
) -> dict:
    """Run the full verification pipeline; return the canonical result dict.

    This is the engine consumed by ``tools/verify_credentials_load.verify_credentials_load``.
    Splits the wrapped-function-call + verdict-derivation + Metadata-shape
    construction into a single read-only pure(ish) operation that the CLI
    shim wraps in the audit-row write.

    Returns a dict with the canonical phase1/04a § 3 Stdout (--json) keys
    PLUS ``event_kind='verify'`` and ``server`` (caller-supplied tag for
    Gate 6 DISTINCT-counting; per the test contract).
    """
    require_list = list(require or [])
    optional_list = list(optional or [])

    # Always populate these unconditionally — defense-in-depth so every
    # exit path returns a dict with all canonical keys present.
    envelope_sha = compute_envelope_sha256(envelope_path)
    invoked_at = _iso_utc_now()

    # Platform probe roll-up — recorded for audit visibility; deliberately
    # NOT consulted in verdict derivation. On Windows the canonical TPM2 /
    # keyctl probes return "skipped" which means the tool stays usable on
    # the dev workstation without falsely reporting exit 2.
    if run_platform_probes:
        platform_probes = {
            "tpm2": probe_tpm2(envelope_path, runner=runner),
            "keyring": probe_keyring(runner=runner),
            "env_perms": probe_envelope_perms(),
            "platform": platform.system(),
        }
    else:
        platform_probes = {
            "tpm2": "skipped",
            "keyring": "skipped",
            "env_perms": "skipped",
            "platform": platform.system(),
        }

    base: dict = {
        "actor": actor,
        "server": server,
        "envelope_path": envelope_path,
        "envelope_sha256": envelope_sha,
        "invoked_at": invoked_at,
        "required_keys_present_count": 0,
        "required_keys_total": len(require_list),
        "optional_keys_present_count": 0,
        "optional_keys_total": len(optional_list),
        "missing_required_keys": [],
        "missing_optional_keys": [],
        "error_type": None,
        "error_message": None,
        "exit_code": EXIT_FATAL,
        "event_kind": "verify",
        "platform_probes": platform_probes,
        "all_passed": False,
        "event_type": EVENT_TYPE,
    }

    # ---- Wrapped function invocation ----
    try:
        creds = load_credentials_fn()
    except credentials_load_error_cls as exc:
        base["error_type"] = _classify_error(exc)
        base["error_message"] = sensitive_redact(str(exc))[:4000]
        base["exit_code"] = EXIT_FATAL
        return base
    except vault_config_error_cls as exc:
        base["error_type"] = _classify_error(exc)
        base["error_message"] = sensitive_redact(str(exc))[:4000]
        base["exit_code"] = EXIT_FATAL
        return base
    except BaseException as exc:  # pragma: no cover  # defensive — see § 3 error modes
        # Any non-canonical exception still maps to exit 2 per § 3:
        # "OR unexpected exception (pipeline MUST NOT proceed)".
        base["error_type"] = _classify_error(exc)
        base["error_message"] = sensitive_redact(str(exc))[:4000]
        base["exit_code"] = EXIT_FATAL
        return base

    # ---- Verdict derivation from returned dict ----
    if not isinstance(creds, dict):
        # The wrapped function returned a non-dict — treat as fatal.
        base["error_type"] = "UnexpectedReturnTypeError"
        base["error_message"] = sensitive_redact(
            f"load_credentials returned {type(creds).__name__}, expected dict"
        )
        base["exit_code"] = EXIT_FATAL
        return base

    # Apply SensitiveDataFilter to the returned dict to prevent any
    # accidental key-value leakage from ever populating fields downstream.
    # Note: we only inspect KEY NAMES for verdict derivation; we never
    # propagate VALUES into the result dict.
    require_set = set(require_list)
    optional_set = set(optional_list)
    present_keys = set(creds.keys())

    exit_code, missing_req, missing_opt = _verdict_from_keys(
        creds, require_list, optional_list
    )

    base["required_keys_present_count"] = len(require_set & present_keys)
    base["optional_keys_present_count"] = len(optional_set & present_keys)
    base["missing_required_keys"] = missing_req
    base["missing_optional_keys"] = missing_opt
    base["exit_code"] = exit_code
    base["all_passed"] = exit_code == EXIT_SUCCESS

    # Record KEY NAMES (never VALUES) of the keys that satisfied the
    # operator-supplied require + optional sets. This puts the names
    # into the audit-row Metadata so Gate 6 DISTINCT-counting and
    # forensic-trace queries can verify which keys were present without
    # exposing any plaintext value. The list is sorted for determinism
    # per § 3 Stdout (--json) shape (canonical lists are sorted).
    keys_present = sorted((require_set | optional_set) & present_keys)
    base["keys_present"] = keys_present

    # Final defense-in-depth pass: scrub any sensitive substring from the
    # entire result dict before returning. The KEY NAMES in
    # missing_required_keys / missing_optional_keys are intentionally
    # preserved — only VALUES (which shouldn't exist in the dict anyway)
    # would be redacted.
    return sensitive_redact_dict(base)
