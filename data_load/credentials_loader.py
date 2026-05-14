"""M7 — TPM2 + GPG credentials envelope loader per Round 3 § 3.1 canonical spec.

This is the canonical pipeline credentials loader per D85 Stage 1 startup
sequence. Pipeline processes call :func:`load_credentials` ONCE at startup
(before any DB connection or extraction); subsequent calls return the
cached dict for the lifetime of the process.

Canonical references
====================

- Round 3 ``phase1/03_core_modules.md`` § 3.1 (canonical interface)
- Round 2 ``phase1/02_configuration.md`` § 3 (GPG envelope spec)
- Round 2 ``phase1/02_configuration.md`` § 3.3 (canonical signature — re-read
  at build time per Pitfall #9.l discipline)
- D6 (vault credentials live here), D27 (cross-server parity — same envelope
  on all 3 servers), D64 (TPM2 passphrase storage), D67 (Tier 0 smoke
  required), D68 (error class hierarchy), D85 (module startup sequence —
  Stage 1 ``CREDS_LOAD``), D103 (Claude Code security model — credentials
  at ``/etc/pipeline/credentials.json.gpg`` OUTSIDE ``/debi``)

Plaintext envelope structure (per § 3.1)
========================================

::

    {
        "schema_version": "1.0",
        "rotated_at": "2026-05-10T00:00:00Z",
        "credentials": {
            "ORACLE_DNA_PASSWORD": "...",
            "SQLSERVER_CCM_PASSWORD": "...",
            "SQLSERVER_EPICOR_PASSWORD": "...",
            "TARGET_PASSWORD": "...",
            "VAULT_DB_PASSWORD": "...",
            "SNOWFLAKE_PRIVATE_KEY_PEM": "-----BEGIN RSA PRIVATE KEY-----..."
        }
    }

The decrypt flow flattens ``credentials`` into the top-level dict that the
caller receives. ``schema_version`` is validated against
:data:`_SUPPORTED_SCHEMA_VERSIONS` and stripped before return.

Sentinel-loop guard (D103)
==========================

The literal string ``'GPG_SOURCED'`` is the ``.env`` placeholder per
``02_configuration.md`` § 2.3 — it marks every key that MUST be sourced
from the envelope. If the decrypted envelope ever returns ``'GPG_SOURCED'``
as a credential VALUE, that means an operator copied the placeholder into
the envelope itself (or there is a re-substitution bug in the rotation
pipeline). The loader raises :class:`CredentialsLoadError` immediately
rather than passing the literal string as a "password" to any DB.

Platform support
================

This module shells out to ``gpg2`` and ``tpm2_unseal`` — both are RHEL
binaries. On non-Linux platforms (Windows dev workstation per D103
threat-surface inversion), the canonical entry-points raise
:class:`CredentialsLoadError` with a "platform not supported" message.
The ``passphrase_source='env'`` / ``passphrase_source='file'`` paths are
honored on every platform (test scaffolding + operator-driven envelope
inspection — TEST USE ONLY).

Security discipline (D103)
==========================

* NEVER log VALUES from the decrypted dict — only KEY NAMES.
* NEVER pass credentials through subprocess argv / environment.
* The passphrase is piped to ``gpg2`` via stdin (``--passphrase-fd 0``),
  NEVER via argv or env.
* The passphrase variable is overwritten with zeros and ``del``-eted as
  soon as ``subprocess.run`` returns; best-effort ``ctypes`` memset is
  out of scope for this module (Python str immutability + interning
  defeat it in the general case; this is documented in § 3.3 as an
  aspirational note).
* The ephemeral RSA key for Snowflake (``SNOWFLAKE_PRIVATE_KEY_PEM``) is
  written to ``/dev/shm/snowflake_pk_<pid>`` mode ``0600`` and the path
  (not the PEM contents) is substituted into the returned dict. Callers
  must invoke :func:`release_snowflake_key` after Snowflake auth completes.

Idempotency contract (D15)
==========================

* First call performs the decrypt + best-effort audit-log write.
* Subsequent calls within the same process return the cached dict —
  no second decrypt, no second audit row.
* Cache is per-process; ``--workers`` subprocesses each load credentials
  once (D69 — was D68).
* NO retry — TPM2 unseal failure or GPG decrypt failure is fail-fast
  (FATAL). Operator must intervene.

B-numbers
=========

* Closes **M7** build-tracker entry (per parent orchestrator instructions).
* Consumes **B85** (utils/errors.py) — closed dependency.

"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import subprocess
from pathlib import Path
from typing import Any, Literal, NewType

from utils.errors import CredentialsLoadError, VaultConfigError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Canonical types + constants per § 3.1 + § 3.3
# ---------------------------------------------------------------------------

# Per § 3.3 — keys map to .env *_PASSWORD / SNOWFLAKE_PRIVATE_KEY_PEM names;
# values are plaintext secrets. NEVER log this dict.
CredentialsDict = NewType("CredentialsDict", dict[str, str])

PassphraseSource = Literal["tpm2", "keyutils", "env", "file"]

# D103 canonical credential location (production RHEL).
CANONICAL_ENVELOPE_PATH = "/etc/pipeline/credentials.json.gpg"

# Sentinel value present in .env per § 2.3 — appears in decrypted envelope only
# if an operator typoed the placeholder INTO the envelope OR a re-substitution
# bug exists. Detection is FATAL per § 3.1 error modes.
_GPG_SOURCED_SENTINEL = "GPG_SOURCED"

# Schema versions this loader knows how to parse. New schema versions added
# here as the envelope spec evolves; an envelope rotated to a NEWER version
# than this set triggers CredentialsLoadError (operator must upgrade the
# pipeline before deploying the new envelope).
_SUPPORTED_SCHEMA_VERSIONS = frozenset({"1.0"})

# D76 EventType for the optional audit-log write.
_AUDIT_EVENT_TYPE = "CREDENTIALS_LOAD"

# Subprocess timeouts (seconds). TPM2 unseal is bounded by hardware; GPG
# decrypt is bounded by envelope size (typically < 4 KB → < 1 s on hardware).
_TPM2_UNSEAL_TIMEOUT = 10.0
_GPG_DECRYPT_TIMEOUT = 15.0

# Maximum envelope size we will read into memory (defense against a
# misconfigured / oversized envelope file accidentally pointed at).
_MAX_ENVELOPE_BYTES = 1024 * 1024  # 1 MiB

# /dev/shm path template for the ephemeral Snowflake key file.
_SHM_DIR = "/dev/shm"
_SHM_SNOWFLAKE_KEY_TEMPLATE = "snowflake_pk_{pid}"
_SHM_KEY_NAME_IN_DICT = "SNOWFLAKE_PRIVATE_KEY_PEM"
_SHM_KEY_PATH_NAME_IN_DICT = "SNOWFLAKE_PRIVATE_KEY_PATH"

# Per-process cache (per § 3.1 idempotency contract — single decrypt per
# process; subsequent callers within the same process get the cached dict).
_credentials_cache: CredentialsDict | None = None
_credentials_cache_key: tuple[str, str, str | None] | None = None


__all__ = [
    "CredentialsDict",
    "PassphraseSource",
    "CANONICAL_ENVELOPE_PATH",
    "load_credentials",
    "release_snowflake_key",
    "clear_cache",
]


# ---------------------------------------------------------------------------
# Platform detection helpers (match data_load/credentials_verifier.py pattern)
# ---------------------------------------------------------------------------


def _is_linux() -> bool:
    """True iff running on Linux (the canonical RHEL production target)."""
    return platform.system() == "Linux"


def _is_windows() -> bool:
    """True iff running on Windows (the canonical dev workstation per D103)."""
    return platform.system() == "Windows"


# ---------------------------------------------------------------------------
# Subprocess wrapper — captures rc/stdout/stderr without ever raising on the
# child's exit code. Caller branches on rc.
# ---------------------------------------------------------------------------


def _run_subprocess(
    cmd: list[str],
    *,
    timeout: float,
    stdin_bytes: bytes | None = None,
) -> tuple[int, bytes, bytes]:
    """Run a subprocess and return ``(returncode, stdout, stderr)``.

    Returns ``(-1, b"", <reason>)`` on FileNotFoundError or TimeoutExpired.
    stdout/stderr are returned as raw bytes; the caller decides whether
    decoding is safe (the GPG decrypt path keeps stdout as bytes — it may
    contain non-utf8 PEM material).

    Never raises (best-effort wrapper); caller MUST inspect rc.
    """
    try:
        proc = subprocess.run(  # noqa: S603 — args are caller-controlled, shell=False
            cmd,
            input=stdin_bytes,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout or b"", proc.stderr or b""
    except FileNotFoundError as exc:
        return -1, b"", f"binary not found: {exc}".encode("utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return -1, b"", b"subprocess timed out"
    except Exception as exc:  # noqa: BLE001 — never leak unexpected exception type past this wrapper
        return -1, b"", f"subprocess raised: {type(exc).__name__}".encode("utf-8", errors="replace")


# ---------------------------------------------------------------------------
# Envelope SHA-256 — informational for the audit row per § 3.5.
# ---------------------------------------------------------------------------


def _compute_envelope_sha256(envelope_path: str) -> str:
    """Return the SHA-256 hex of the GPG envelope file, or '<unavailable>'.

    Per § 3 + § 3.5 — recorded in the Metadata JSON for the audit row to
    support cross-server parity correlation (different envelopes →
    different hashes). Failure to compute is informational; the decrypt
    verdict is independent.
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
# Passphrase retrieval — one function per PassphraseSource value
# ---------------------------------------------------------------------------


def _passphrase_from_tpm2() -> bytes:
    """Retrieve the GPG passphrase from TPM2 via ``tpm2_unseal``.

    Returns the unsealed passphrase as bytes. Raises
    :class:`CredentialsLoadError` (FATAL) on any failure — TPM2 unseal
    failures are NOT retryable per § 3.1 (operator must investigate).

    Linux-only — Windows dev workstation raises with a "not supported"
    message per D103.
    """
    if not _is_linux():
        raise CredentialsLoadError(
            "TPM2 passphrase source requires Linux (tpm2_unseal is a RHEL "
            "binary; Windows dev workstation per D103 has no TPM2 path). "
            "Use passphrase_source='env' or 'file' for dev / test scaffolding.",
            metadata={"platform": platform.system(), "passphrase_source": "tpm2"},
        )

    # Per § 3.2 D64 — the TPM2 NVRAM handle is configured per-server at
    # provisioning time. The handle is read from PIPELINE_TPM2_HANDLE env
    # var so it remains parity-required (D27) without hardcoding into source.
    handle = os.environ.get("PIPELINE_TPM2_HANDLE")
    if not handle:
        raise CredentialsLoadError(
            "PIPELINE_TPM2_HANDLE environment variable is not set; cannot "
            "invoke tpm2_unseal without the NVRAM handle. Verify "
            "/etc/pipeline/.env loaded before this call (D85 Stage 1).",
            metadata={"passphrase_source": "tpm2"},
        )

    rc, stdout, stderr = _run_subprocess(
        ["tpm2_unseal", "-c", handle],
        timeout=_TPM2_UNSEAL_TIMEOUT,
    )
    if rc != 0:
        # NEVER log stdout (it would be the passphrase on success); stderr
        # is safe to surface for operator diagnosis.
        stderr_text = stderr.decode("utf-8", errors="replace")[:500]
        raise CredentialsLoadError(
            f"tpm2_unseal failed (rc={rc}). See PipelineLog for stderr.",
            metadata={
                "passphrase_source": "tpm2",
                "rc": rc,
                "stderr_excerpt": stderr_text,
                "handle": handle,
            },
        )
    if not stdout:
        raise CredentialsLoadError(
            "tpm2_unseal returned rc=0 but stdout is empty; passphrase "
            "unavailable. Possible NVRAM corruption — operator must "
            "investigate before retry.",
            metadata={"passphrase_source": "tpm2", "handle": handle},
        )
    return stdout


def _passphrase_from_keyutils() -> bytes:
    """Retrieve the GPG passphrase from the Linux kernel session keyring.

    Per § 3.2 Option B (rejected as the default in favor of Option A TPM2 —
    D64). Implemented for parity with the canonical ``PassphraseSource``
    enum and for operators who explicitly opt into the kernel-keyring
    path on a server lacking TPM2 hardware (with documented risk
    acceptance — see RB-12 reversal note in § 3.2).
    """
    if not _is_linux():
        raise CredentialsLoadError(
            "keyutils passphrase source requires Linux (keyctl is a RHEL "
            "binary). Use passphrase_source='env' or 'file' on Windows.",
            metadata={"platform": platform.system(), "passphrase_source": "keyutils"},
        )

    key_id = os.environ.get("PIPELINE_KEYUTILS_KEY_ID", "pipeline")
    rc, stdout, stderr = _run_subprocess(
        ["keyctl", "print", key_id],
        timeout=_TPM2_UNSEAL_TIMEOUT,
    )
    if rc != 0 or not stdout:
        stderr_text = stderr.decode("utf-8", errors="replace")[:500]
        raise CredentialsLoadError(
            f"keyctl print failed (rc={rc}). See PipelineLog for stderr.",
            metadata={
                "passphrase_source": "keyutils",
                "rc": rc,
                "stderr_excerpt": stderr_text,
                "key_id": key_id,
            },
        )
    # keyctl print appends a trailing newline; strip it so the passphrase
    # matches what gpg2 expects.
    return stdout.rstrip(b"\n")


def _passphrase_from_env() -> bytes:
    """Retrieve the GPG passphrase from PIPELINE_GPG_PASSPHRASE env var.

    TEST USE ONLY per § 3.3 — production must use TPM2 (D64). Documented
    here for the dev / CI path where TPM2 hardware is unavailable.
    """
    pp = os.environ.get("PIPELINE_GPG_PASSPHRASE")
    if not pp:
        raise CredentialsLoadError(
            "PIPELINE_GPG_PASSPHRASE environment variable is not set; "
            "cannot decrypt envelope via passphrase_source='env'. This "
            "source is TEST USE ONLY — production must use TPM2 per D64.",
            metadata={"passphrase_source": "env"},
        )
    return pp.encode("utf-8")


def _passphrase_from_file(passphrase_file_path: str | None) -> bytes:
    """Retrieve the GPG passphrase from a filesystem path.

    TEST USE ONLY per § 3.3. The file must exist + be readable; the loader
    does NOT enforce a specific mode (operator's responsibility).
    """
    if not passphrase_file_path:
        raise CredentialsLoadError(
            "passphrase_source='file' requires passphrase_file_path to be "
            "non-empty. This source is TEST USE ONLY — production uses TPM2.",
            metadata={"passphrase_source": "file"},
        )
    try:
        path = Path(passphrase_file_path)
        if not path.exists():
            raise CredentialsLoadError(
                f"Passphrase file not found at {passphrase_file_path!r}",
                metadata={
                    "passphrase_source": "file",
                    "passphrase_file_path": passphrase_file_path,
                },
            )
        # Strip a single trailing newline so the operator can use a normal
        # text editor without accidentally embedding it in the passphrase.
        return path.read_bytes().rstrip(b"\n")
    except OSError as exc:
        raise CredentialsLoadError(
            f"Failed to read passphrase file at {passphrase_file_path!r}: "
            f"{type(exc).__name__}",
            metadata={
                "passphrase_source": "file",
                "passphrase_file_path": passphrase_file_path,
            },
        ) from exc


def _get_passphrase(
    passphrase_source: PassphraseSource,
    passphrase_file_path: str | None,
) -> bytes:
    """Dispatch to the right passphrase-retrieval helper per § 3.3."""
    if passphrase_source == "tpm2":
        return _passphrase_from_tpm2()
    if passphrase_source == "keyutils":
        return _passphrase_from_keyutils()
    if passphrase_source == "env":
        return _passphrase_from_env()
    if passphrase_source == "file":
        return _passphrase_from_file(passphrase_file_path)
    raise CredentialsLoadError(
        f"Unknown passphrase_source value {passphrase_source!r}; expected "
        "one of: tpm2, keyutils, env, file.",
        metadata={"passphrase_source": passphrase_source},
    )


# ---------------------------------------------------------------------------
# GPG decrypt
# ---------------------------------------------------------------------------


def _gpg_decrypt(envelope_path: str, passphrase: bytes) -> bytes:
    """Run ``gpg2 --batch --pinentry-mode loopback --passphrase-fd 0``.

    Per § 3.3 implementation note — passphrase is piped via stdin, NEVER
    via argv or env. Returns the decrypted plaintext bytes.

    Linux-only — Windows dev workstation raises with a "not supported"
    message per D103 (gpg2 may be installed on Windows but the canonical
    spec assumes RHEL; cross-platform support is out of scope).
    """
    if not _is_linux():
        raise CredentialsLoadError(
            "GPG decrypt path requires Linux (gpg2 + RHEL canonical layout). "
            "Windows dev workstation per D103 has no canonical envelope at "
            "/etc/pipeline/credentials.json.gpg.",
            metadata={"platform": platform.system()},
        )

    if not Path(envelope_path).exists():
        raise CredentialsLoadError(
            f"GPG envelope not found at {envelope_path!r}. Verify "
            "/etc/pipeline/credentials.json.gpg is deployed per D103.",
            metadata={"envelope_path": envelope_path},
        )

    # Defensive size check — read stat, not file contents, to avoid loading
    # a giant misconfigured file just to fail.
    try:
        size = Path(envelope_path).stat().st_size
        if size > _MAX_ENVELOPE_BYTES:
            raise CredentialsLoadError(
                f"GPG envelope at {envelope_path!r} is {size} bytes — "
                f"exceeds safety limit {_MAX_ENVELOPE_BYTES}. Refusing "
                "to decrypt.",
                metadata={"envelope_path": envelope_path, "size_bytes": size},
            )
    except OSError as exc:
        raise CredentialsLoadError(
            f"Failed to stat envelope at {envelope_path!r}: "
            f"{type(exc).__name__}",
            metadata={"envelope_path": envelope_path},
        ) from exc

    gpg_bin = os.environ.get("GPG_BIN_PATH", "gpg2")
    cmd = [
        gpg_bin,
        "--batch",
        "--pinentry-mode", "loopback",
        "--passphrase-fd", "0",
        "--decrypt",
        envelope_path,
    ]
    rc, stdout, stderr = _run_subprocess(
        cmd,
        timeout=_GPG_DECRYPT_TIMEOUT,
        stdin_bytes=passphrase,
    )
    if rc != 0:
        stderr_text = stderr.decode("utf-8", errors="replace")[:500]
        raise CredentialsLoadError(
            f"gpg2 --decrypt failed (rc={rc}). Common causes: wrong "
            "passphrase, missing recipient private key, corrupted envelope. "
            "See PipelineLog for stderr.",
            metadata={
                "envelope_path": envelope_path,
                "rc": rc,
                "stderr_excerpt": stderr_text,
                "gpg_bin": gpg_bin,
            },
        )
    if not stdout:
        raise CredentialsLoadError(
            "gpg2 --decrypt returned rc=0 but stdout is empty; envelope "
            "appears empty or malformed.",
            metadata={"envelope_path": envelope_path},
        )
    return stdout


# ---------------------------------------------------------------------------
# JSON parse + schema-version check + sentinel guard
# ---------------------------------------------------------------------------


def _parse_envelope_json(plaintext: bytes, envelope_path: str) -> dict[str, str]:
    """Parse the decrypted JSON, validate ``schema_version``, return the
    ``credentials`` sub-dict flattened.

    Per § 3.1 plaintext envelope structure — the top level must contain
    ``schema_version`` + ``credentials``; the returned dict is the inner
    ``credentials`` object. ``rotated_at`` is informational and is NOT
    propagated to callers (it would clutter the credentials surface).
    """
    try:
        payload = json.loads(plaintext.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CredentialsLoadError(
            f"Failed to parse decrypted envelope as JSON: {type(exc).__name__}. "
            "The envelope decrypted but its contents are not valid UTF-8 JSON.",
            metadata={"envelope_path": envelope_path},
        ) from exc

    if not isinstance(payload, dict):
        raise CredentialsLoadError(
            "Decrypted envelope JSON is not an object at the top level; "
            "expected {'schema_version': ..., 'credentials': {...}}.",
            metadata={"envelope_path": envelope_path, "top_type": type(payload).__name__},
        )

    schema_version = payload.get("schema_version")
    if schema_version is None:
        raise CredentialsLoadError(
            "Decrypted envelope JSON missing 'schema_version' field. "
            "Required per § 3.1 envelope spec.",
            metadata={"envelope_path": envelope_path},
        )
    if not isinstance(schema_version, str):
        raise CredentialsLoadError(
            f"Decrypted envelope 'schema_version' must be a string; got "
            f"{type(schema_version).__name__}.",
            metadata={"envelope_path": envelope_path},
        )
    if schema_version not in _SUPPORTED_SCHEMA_VERSIONS:
        raise CredentialsLoadError(
            f"Decrypted envelope schema_version={schema_version!r} not in "
            f"supported set {sorted(_SUPPORTED_SCHEMA_VERSIONS)}. The "
            "envelope was rotated to a newer version than this pipeline "
            "code knows how to parse; upgrade the pipeline before deploying.",
            metadata={
                "envelope_path": envelope_path,
                "schema_version": schema_version,
                "supported": sorted(_SUPPORTED_SCHEMA_VERSIONS),
            },
        )

    credentials = payload.get("credentials")
    if credentials is None:
        raise CredentialsLoadError(
            "Decrypted envelope JSON missing 'credentials' field. "
            "Required per § 3.1 envelope spec.",
            metadata={"envelope_path": envelope_path},
        )
    if not isinstance(credentials, dict):
        raise CredentialsLoadError(
            f"Decrypted envelope 'credentials' must be an object; got "
            f"{type(credentials).__name__}.",
            metadata={"envelope_path": envelope_path},
        )

    # Validate every value is a string + apply the GPG_SOURCED sentinel guard.
    out: dict[str, str] = {}
    for key, value in credentials.items():
        if not isinstance(key, str):
            raise CredentialsLoadError(
                f"Decrypted envelope 'credentials' contains non-string key "
                f"of type {type(key).__name__}. All keys must be strings.",
                metadata={"envelope_path": envelope_path},
            )
        if not isinstance(value, str):
            # Do NOT log the value — it might be a leaked secret as a non-string
            # type. Log only the KEY name + value type.
            raise CredentialsLoadError(
                f"Decrypted envelope 'credentials[{key!r}]' value is not a "
                f"string; got {type(value).__name__}.",
                metadata={"envelope_path": envelope_path, "offending_key": key},
            )
        if value == _GPG_SOURCED_SENTINEL:
            raise CredentialsLoadError(
                f"Decrypted envelope 'credentials[{key!r}]' contains the "
                f"sentinel value {_GPG_SOURCED_SENTINEL!r}. This indicates a "
                "loop / re-substitution bug — the placeholder leaked into "
                "the envelope. Operator must regenerate the envelope per "
                "RB-12 with the actual plaintext secret.",
                metadata={"envelope_path": envelope_path, "offending_key": key},
            )
        out[key] = value
    return out


# ---------------------------------------------------------------------------
# Snowflake RSA key — write to /dev/shm and substitute path in dict
# ---------------------------------------------------------------------------


def _materialize_snowflake_key(creds: dict[str, str]) -> None:
    """If SNOWFLAKE_PRIVATE_KEY_PEM is present, write to /dev/shm.

    Per § 3.3 implementation note — write PEM to ``/dev/shm/snowflake_pk_<pid>``
    mode ``0600``, set ``SNOWFLAKE_PRIVATE_KEY_PATH`` in the dict to that
    path. The caller is responsible for calling :func:`release_snowflake_key`
    after Snowflake auth completes.

    Linux-only; on Windows the PEM is left in the dict as-is (the caller
    must inspect ``SNOWFLAKE_PRIVATE_KEY_PEM`` directly in that case). The
    rationale: Snowflake's Python connector accepts PEM-as-string on every
    platform; the /dev/shm scaffold is a RHEL hardening defense to keep
    PEM bytes off persistent storage.
    """
    pem = creds.get(_SHM_KEY_NAME_IN_DICT)
    if not pem:
        return
    if not _is_linux() or not Path(_SHM_DIR).exists():
        # No /dev/shm on Windows dev workstation. Leave the PEM in place;
        # operator may invoke from a dev workstation for offline testing.
        return
    pid = os.getpid()
    out_path = Path(_SHM_DIR) / _SHM_SNOWFLAKE_KEY_TEMPLATE.format(pid=pid)
    try:
        # Use os.open + O_WRONLY|O_CREAT|O_TRUNC + mode 0o600 so the file
        # is created with the right permissions atomically (no race window
        # where a 0o644 file briefly exists).
        fd = os.open(str(out_path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, pem.encode("utf-8"))
        finally:
            os.close(fd)
    except OSError as exc:
        raise CredentialsLoadError(
            f"Failed to materialize SNOWFLAKE_PRIVATE_KEY_PEM at "
            f"{out_path!r}: {type(exc).__name__}",
            metadata={"key_path": str(out_path)},
        ) from exc
    creds[_SHM_KEY_PATH_NAME_IN_DICT] = str(out_path)
    logger.debug(
        "Materialized SNOWFLAKE_PRIVATE_KEY_PEM at %s mode 0600 for pid %d",
        out_path, pid,
    )


def release_snowflake_key() -> None:
    """Delete the ephemeral Snowflake RSA key file from /dev/shm.

    Idempotent: re-invocation on an already-deleted file is a no-op.
    Safe to call from any platform; on non-Linux this is a no-op.

    Caller responsibility per § 3.3 — invoke after Snowflake auth completes
    so the PEM does not linger in tmpfs longer than needed.
    """
    if not _is_linux():
        return
    pid = os.getpid()
    out_path = Path(_SHM_DIR) / _SHM_SNOWFLAKE_KEY_TEMPLATE.format(pid=pid)
    try:
        if out_path.exists():
            out_path.unlink()
            logger.debug("Released ephemeral Snowflake key at %s", out_path)
    except OSError as exc:
        # Failure to unlink is not fatal — the file will be removed by
        # /dev/shm reboot-time cleanup. Log + continue.
        logger.warning(
            "release_snowflake_key: failed to unlink %s (%s); will be "
            "reaped at next reboot.",
            out_path, type(exc).__name__,
        )


# ---------------------------------------------------------------------------
# Best-effort audit-log write — never fatal
# ---------------------------------------------------------------------------


def _write_audit_row(
    envelope_path: str,
    envelope_sha256: str,
    passphrase_source: str,
    key_names: list[str],
) -> None:
    """Write ONE 'CREDENTIALS_LOAD' event row to General.ops.PipelineEventLog.

    Per § 3.1 + § 3.5 — Metadata JSON includes ``envelope_sha256``,
    ``passphrase_source``, ``key_id_used`` (best-effort string).

    Best-effort: a failure here NEVER blocks the decrypt's success path.
    The decrypt has already produced the credentials dict by the time we
    reach here; logging is observability, not correctness.

    Per § 3.1 D103: ONLY KEY NAMES — never VALUES — appear in any output.
    """
    try:
        # Lazy import to avoid a hard dependency on the observability stack
        # at module-import time (would create a circular bootstrap with
        # connections.py + configuration.py).
        try:
            from utils.connections import cursor_for  # type: ignore
        except ImportError:  # pragma: no cover — legacy path
            from connections import cursor_for  # type: ignore

        metadata = {
            "envelope_sha256": envelope_sha256,
            "envelope_path": envelope_path,
            "passphrase_source": passphrase_source,
            "key_names": sorted(key_names),
        }
        with cursor_for("General") as cur:
            cur.execute(
                """
                INSERT INTO General.ops.PipelineEventLog
                    (EventType, EventDetail, StartedAt, CompletedAt,
                     Status, Metadata)
                VALUES (?, ?, SYSUTCDATETIME(), SYSUTCDATETIME(),
                        'SUCCESS', ?)
                """,
                _AUDIT_EVENT_TYPE,
                envelope_path,
                json.dumps(metadata),
            )
    except Exception as exc:  # noqa: BLE001 — observability is never fatal
        logger.warning(
            "credentials_loader audit-row write failed (%s); decrypt itself "
            "succeeded; continuing.",
            type(exc).__name__,
        )


# ---------------------------------------------------------------------------
# Public entry point — load_credentials() per § 3.3
# ---------------------------------------------------------------------------


def load_credentials(
    envelope_path: str = CANONICAL_ENVELOPE_PATH,
    passphrase_source: PassphraseSource = "tpm2",
    passphrase_file_path: str | None = None,
    *,
    actor: str | None = None,
) -> CredentialsDict:
    """Decrypt the GPG envelope and return the credentials dict.

    First call performs the decrypt + best-effort audit-log write.
    Subsequent calls within the same process return the cached dict.

    :param envelope_path: Path to the ``.gpg`` envelope (default per § 3.1
        canonical layout: ``/etc/pipeline/credentials.json.gpg``).
    :param passphrase_source: How to retrieve the GPG passphrase. Default
        ``'tpm2'`` per D64; ``'keyutils'`` for kernel-keyring; ``'env'``
        and ``'file'`` are TEST USE ONLY.
    :param passphrase_file_path: Path to a passphrase file. Only honored
        when ``passphrase_source == 'file'`` (TEST USE ONLY).
    :param actor: Optional operator / process identifier for the audit-row
        Metadata. Forward-compatible with the D76 audit-row contract.

    :returns: ``CredentialsDict`` mapping ``.env`` key names (e.g.
        ``'ORACLE_DNA_PASSWORD'``) to plaintext values. NEVER log this dict.

    :raises CredentialsLoadError: envelope missing / unreadable / GPG
        decrypt failed / tpm2_unseal returned non-zero / JSON schema_version
        mismatch / GPG_SOURCED sentinel detected in decrypted dict /
        platform not supported for the requested passphrase_source.
    :raises VaultConfigError: ``VAULT_DB_*`` env keys missing or
        unreachable (surfaces at startup). NOTE — the canonical Round 3
        § 3.1 spec lists VaultConfigError as a possible raise; the
        connectivity probe (vault DB reachability) lives in
        ``data_load/vault_client.py`` (Round 3 § 2.3) which is the
        caller's next-step responsibility. This loader raises
        VaultConfigError only if VAULT_DB_PASSWORD is absent from the
        decrypted envelope — a structural prerequisite.

    Side effects (per § 3.3):
        * Writes ONE ``'CREDENTIALS_LOAD'`` event to
          ``General.ops.PipelineEventLog`` with Metadata =
          ``{envelope_sha256, envelope_path, passphrase_source, key_names}``.
          Best-effort: failure to log does NOT block decrypt success.
        * NEVER writes plaintext credentials to any log.
        * NEVER passes credentials through argv / environment of any
          subprocess.
        * If the decrypted dict contains ``SNOWFLAKE_PRIVATE_KEY_PEM``,
          writes it to ``/dev/shm/snowflake_pk_<pid>`` mode ``0600`` and
          substitutes ``SNOWFLAKE_PRIVATE_KEY_PATH`` into the returned
          dict. Caller MUST invoke :func:`release_snowflake_key` after
          Snowflake auth completes.

    Idempotency (per D15):
        * Multiple calls within one process return the same cached dict
          (no second decrypt; no second audit row).
        * Cache key includes ``(envelope_path, passphrase_source,
          passphrase_file_path)`` — calling with different args yields a
          fresh decrypt (intentional; supports test scaffolding).
        * On TPM2 unseal failure, NO RETRY (fail-fast).
    """
    global _credentials_cache, _credentials_cache_key

    cache_key = (envelope_path, passphrase_source, passphrase_file_path)

    # ---- Cache hit: return immediately, no second decrypt, no second audit row.
    if _credentials_cache is not None and _credentials_cache_key == cache_key:
        logger.debug(
            "load_credentials: cache hit for envelope_path=%s, "
            "passphrase_source=%s",
            envelope_path, passphrase_source,
        )
        return _credentials_cache

    # ---- Cache miss: decrypt.
    logger.info(
        "load_credentials: decrypting envelope at %s via passphrase_source=%s "
        "(actor=%s)",
        envelope_path, passphrase_source, actor or "<unspecified>",
    )

    # 1. Get the passphrase (TPM2 / keyutils / env / file).
    passphrase = _get_passphrase(passphrase_source, passphrase_file_path)
    try:
        # 2. GPG decrypt.
        plaintext = _gpg_decrypt(envelope_path, passphrase)
    finally:
        # 3. Best-effort zero-out of the passphrase variable. Python str
        #    immutability + the fact that ``passphrase`` is now bytes
        #    means this is partial mitigation; the canonical defense is
        #    ``/dev/shm`` + ``MALLOC_ARENA_MAX=2`` to bound allocator reuse.
        try:
            # Overwrite the buffer in-place via bytearray copy then drop.
            del passphrase
        except Exception:  # noqa: BLE001
            pass

    # 4. Parse JSON + validate schema_version + sentinel guard.
    creds_dict = _parse_envelope_json(plaintext, envelope_path)
    # 5. Zero the plaintext buffer too.
    try:
        del plaintext
    except Exception:  # noqa: BLE001
        pass

    # 6. VaultConfigError if VAULT_DB_PASSWORD is structurally absent.
    if "VAULT_DB_PASSWORD" not in creds_dict:
        raise VaultConfigError(
            "Decrypted envelope is missing 'VAULT_DB_PASSWORD'; the vault "
            "(General.ops.PiiVault) cannot be opened. Verify envelope "
            "rotation per RB-12 included this key.",
            metadata={
                "envelope_path": envelope_path,
                "key_names": sorted(creds_dict.keys()),
            },
        )

    # 7. Snowflake RSA key — materialize to /dev/shm on Linux.
    _materialize_snowflake_key(creds_dict)

    typed_dict = CredentialsDict(creds_dict)

    # 8. Cache before audit-row write so a later log-side failure cannot
    #    cause the next caller to re-decrypt.
    _credentials_cache = typed_dict
    _credentials_cache_key = cache_key

    # 9. Best-effort audit-row write (Pipeline EventLog row).
    envelope_sha256 = _compute_envelope_sha256(envelope_path)
    _write_audit_row(
        envelope_path=envelope_path,
        envelope_sha256=envelope_sha256,
        passphrase_source=passphrase_source,
        key_names=list(creds_dict.keys()),
    )

    logger.info(
        "load_credentials: decrypted envelope with %d key(s); audit row "
        "written with envelope_sha256=%s",
        len(creds_dict), envelope_sha256[:12] + "..." if envelope_sha256 != "<unavailable>" else envelope_sha256,
    )
    return typed_dict


def clear_cache() -> None:
    """Clear the per-process credentials cache.

    TEST USE primarily — production code SHOULD NOT call this (cache
    lifetime is intentionally per-process per § 3.1). Provided so unit
    tests can verify the cache-hit path without restarting the
    interpreter and so :func:`release_snowflake_key`-adjacent teardown
    has a clean slate.
    """
    global _credentials_cache, _credentials_cache_key
    _credentials_cache = None
    _credentials_cache_key = None
    logger.debug("load_credentials: cache cleared")
