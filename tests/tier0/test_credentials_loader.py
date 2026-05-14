"""Tier 0 build-time smoke test for data_load/credentials_loader.py.

Per D67 — runs at build time + every commit. Runtime ceiling < 5 s.
All external dependencies (subprocess for gpg2/tpm2_unseal, pyodbc cursor
for audit-log INSERT, filesystem for envelope) are mocked. No live TPM2,
GPG, or SQL Server required.

North Star pillars:
  - Audit-grade (D76 audit-row contract: one CREDENTIALS_LOAD row per
    process; Metadata JSON canonical; ONLY key NAMES — never values —
    per D103).
  - Operationally stable (D67 Tier 0 discipline: import + invoke + shape
    + error-modes in < 5 s with zero external I/O).
  - Idempotent (D15: re-invocation within same process returns cached
    dict; no second decrypt, no second audit row).
  - Traceability (D103: credentials live OUTSIDE /debi; sentinel guard
    catches GPG_SOURCED placeholder leaking into envelope).

D-numbers: D6, D15, D27, D64, D67, D68, D85, D103.
B-numbers: M7 (build-tracker entry — closed by authoring this module +
its tests).

Spec: phase1/03_core_modules.md § 3.1 + phase1/02_configuration.md § 3.3.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Project root on sys.path (matches tests/ convention)
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Synthetic plaintext envelope JSON (schema_version 1.0 per § 3.1).
# Values are masked sentinels — no real secrets in test code.
# ---------------------------------------------------------------------------

_SYNTHETIC_ENVELOPE_JSON = (
    b'{"schema_version": "1.0", "rotated_at": "2026-05-10T00:00:00Z", '
    b'"credentials": {'
    b'"ORACLE_DNA_PASSWORD": "<masked-in-test>", '
    b'"SQLSERVER_CCM_PASSWORD": "<masked-in-test>", '
    b'"SQLSERVER_EPICOR_PASSWORD": "<masked-in-test>", '
    b'"TARGET_PASSWORD": "<masked-in-test>", '
    b'"VAULT_DB_PASSWORD": "<masked-in-test>"'
    b'}}'
)


def _make_ok_subprocess(stdout_bytes: bytes = _SYNTHETIC_ENVELOPE_JSON):
    """Return a callable that mocks _run_subprocess with stable success rc=0."""
    def _runner(cmd, *, timeout, stdin_bytes=None):
        return 0, stdout_bytes, b""
    return _runner


def _make_fail_subprocess(rc: int = 1, stderr: bytes = b"mocked failure"):
    """Return a callable that mocks _run_subprocess with a non-zero rc."""
    def _runner(cmd, *, timeout, stdin_bytes=None):
        return rc, b"", stderr
    return _runner


# ---------------------------------------------------------------------------
# Fixture — clear cache between tests so each test sees a clean state.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_credentials_cache():
    """Reset the per-process cache so cache-hit tests are deterministic."""
    from data_load import credentials_loader as cl
    cl.clear_cache()
    yield
    cl.clear_cache()


# ---------------------------------------------------------------------------
# T-0.1 — module imports cleanly (the canonical first Tier 0 assertion)
# ---------------------------------------------------------------------------


def test_module_imports():
    """credentials_loader imports without side effects on a non-RHEL host."""
    from data_load import credentials_loader as cl
    assert hasattr(cl, "load_credentials")
    assert hasattr(cl, "CredentialsDict")
    assert hasattr(cl, "PassphraseSource")
    assert hasattr(cl, "release_snowflake_key")
    assert hasattr(cl, "clear_cache")
    assert hasattr(cl, "CANONICAL_ENVELOPE_PATH")
    assert cl.CANONICAL_ENVELOPE_PATH == "/etc/pipeline/credentials.json.gpg"


# ---------------------------------------------------------------------------
# T-0.2 — load_credentials() callable end-to-end with mocked decrypt
# ---------------------------------------------------------------------------


def test_load_credentials_invokable_with_mocked_decrypt(tmp_path):
    """load_credentials() returns CredentialsDict shape per § 3.1 spec."""
    from data_load import credentials_loader as cl

    # Provide a fake envelope file so the existence check passes.
    fake_envelope = tmp_path / "credentials.json.gpg"
    fake_envelope.write_bytes(b"<encrypted-bytes>")

    # Provide a fake passphrase file so passphrase_source='file' works.
    fake_pass = tmp_path / "pass.txt"
    fake_pass.write_bytes(b"test-passphrase\n")

    with patch.object(cl, "_is_linux", return_value=True), \
         patch.object(cl, "_run_subprocess", side_effect=_make_ok_subprocess()), \
         patch.object(cl, "_write_audit_row") as audit_spy, \
         patch.object(cl, "_materialize_snowflake_key"):
        result = cl.load_credentials(
            envelope_path=str(fake_envelope),
            passphrase_source="file",
            passphrase_file_path=str(fake_pass),
        )

    # Returned dict carries the synthetic key set; values are present
    # (the test must not assert specific value content — that would
    # be a security violation of D103 if a real envelope ever leaked).
    assert "ORACLE_DNA_PASSWORD" in result
    assert "VAULT_DB_PASSWORD" in result
    assert isinstance(result, dict)
    # Audit row was written exactly once.
    assert audit_spy.call_count == 1


# ---------------------------------------------------------------------------
# T-0.3 — sentinel detection: 'GPG_SOURCED' value raises CredentialsLoadError
# ---------------------------------------------------------------------------


def test_sentinel_detection_raises(tmp_path):
    """If decrypted envelope contains 'GPG_SOURCED' as a VALUE, raise FATAL."""
    from data_load import credentials_loader as cl
    from utils.errors import CredentialsLoadError

    sentinel_envelope = (
        b'{"schema_version": "1.0", "rotated_at": "2026-05-10T00:00:00Z", '
        b'"credentials": {'
        b'"ORACLE_DNA_PASSWORD": "GPG_SOURCED", '
        b'"VAULT_DB_PASSWORD": "<masked-in-test>"'
        b'}}'
    )
    fake_envelope = tmp_path / "credentials.json.gpg"
    fake_envelope.write_bytes(b"<encrypted-bytes>")
    fake_pass = tmp_path / "pass.txt"
    fake_pass.write_bytes(b"x\n")

    with patch.object(cl, "_is_linux", return_value=True), \
         patch.object(cl, "_run_subprocess", side_effect=_make_ok_subprocess(sentinel_envelope)), \
         patch.object(cl, "_materialize_snowflake_key"):
        with pytest.raises(CredentialsLoadError) as excinfo:
            cl.load_credentials(
                envelope_path=str(fake_envelope),
                passphrase_source="file",
                passphrase_file_path=str(fake_pass),
            )
    # The error message must reference the sentinel; key NAME is OK to log,
    # value is NOT (sentinel value is the literal string 'GPG_SOURCED' which
    # is BY DESIGN safe to log — it's the placeholder, not a real secret).
    assert "GPG_SOURCED" in str(excinfo.value)


# ---------------------------------------------------------------------------
# T-0.4 — schema_version mismatch raises CredentialsLoadError
# ---------------------------------------------------------------------------


def test_schema_version_mismatch_raises(tmp_path):
    """An envelope with an unrecognized schema_version is fatal per § 3.1."""
    from data_load import credentials_loader as cl
    from utils.errors import CredentialsLoadError

    future_envelope = (
        b'{"schema_version": "99.0", "rotated_at": "2099-05-10T00:00:00Z", '
        b'"credentials": {"VAULT_DB_PASSWORD": "<masked-in-test>"}}'
    )
    fake_envelope = tmp_path / "credentials.json.gpg"
    fake_envelope.write_bytes(b"<encrypted-bytes>")
    fake_pass = tmp_path / "pass.txt"
    fake_pass.write_bytes(b"x\n")

    with patch.object(cl, "_is_linux", return_value=True), \
         patch.object(cl, "_run_subprocess", side_effect=_make_ok_subprocess(future_envelope)):
        with pytest.raises(CredentialsLoadError) as excinfo:
            cl.load_credentials(
                envelope_path=str(fake_envelope),
                passphrase_source="file",
                passphrase_file_path=str(fake_pass),
            )
    assert "schema_version" in str(excinfo.value)


# ---------------------------------------------------------------------------
# T-0.5 — GPG decrypt failure raises CredentialsLoadError
# ---------------------------------------------------------------------------


def test_gpg_decrypt_failure_raises(tmp_path):
    """gpg2 returning non-zero is FATAL — no retry per § 3.1."""
    from data_load import credentials_loader as cl
    from utils.errors import CredentialsLoadError

    fake_envelope = tmp_path / "credentials.json.gpg"
    fake_envelope.write_bytes(b"<encrypted-bytes>")
    fake_pass = tmp_path / "pass.txt"
    fake_pass.write_bytes(b"x\n")

    with patch.object(cl, "_is_linux", return_value=True), \
         patch.object(cl, "_run_subprocess",
                      side_effect=_make_fail_subprocess(rc=2, stderr=b"bad passphrase")):
        with pytest.raises(CredentialsLoadError) as excinfo:
            cl.load_credentials(
                envelope_path=str(fake_envelope),
                passphrase_source="file",
                passphrase_file_path=str(fake_pass),
            )
    assert "gpg2" in str(excinfo.value)


# ---------------------------------------------------------------------------
# T-0.6 — TPM2 unseal failure raises CredentialsLoadError (no decrypt attempt)
# ---------------------------------------------------------------------------


def test_tpm2_unseal_failure_raises(tmp_path, monkeypatch):
    """tpm2_unseal rc != 0 is FATAL; gpg2 is NEVER invoked in this path."""
    from data_load import credentials_loader as cl
    from utils.errors import CredentialsLoadError

    monkeypatch.setenv("PIPELINE_TPM2_HANDLE", "0x81000001")

    # Single _run_subprocess mock — it should be called exactly ONCE (the
    # TPM2 unseal), and the GPG decrypt should never be reached.
    runner = MagicMock(return_value=(1, b"", b"NVRAM not provisioned"))
    with patch.object(cl, "_is_linux", return_value=True), \
         patch.object(cl, "_run_subprocess", runner):
        with pytest.raises(CredentialsLoadError) as excinfo:
            cl.load_credentials(
                envelope_path="/etc/pipeline/credentials.json.gpg",
                passphrase_source="tpm2",
            )
    assert "tpm2_unseal" in str(excinfo.value)
    # Only one subprocess call — the TPM2 unseal. GPG decrypt never ran.
    assert runner.call_count == 1
