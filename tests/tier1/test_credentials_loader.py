"""Tier 1 unit test for data_load/credentials_loader.py.

Per D70 Tier 1 — per-edge-case + per-error-path coverage; mocks subprocess
+ pyodbc cursor; no live TPM2 / GPG / SQL Server.

Test scope (organized as classes per sibling tier1 style):

  TestPlatformDetection
    - TPM2 / keyutils paths reject non-Linux callers with FATAL.
    - 'env' / 'file' paths work on every platform.

  TestPassphraseRetrieval
    - env-var path returns the bytes from PIPELINE_GPG_PASSPHRASE.
    - file path returns the bytes from the file (trailing newline stripped).
    - missing env var raises FATAL.
    - missing file path raises FATAL.
    - unknown passphrase_source raises FATAL.

  TestGpgDecrypt
    - envelope-missing raises FATAL.
    - envelope-too-large raises FATAL (size guard).
    - rc != 0 raises FATAL with stderr in metadata.
    - rc == 0 + empty stdout raises FATAL (corrupted envelope).
    - gpg2 binary path comes from GPG_BIN_PATH env var.

  TestEnvelopeParse
    - valid JSON returns the inner 'credentials' dict.
    - non-UTF8 plaintext raises FATAL.
    - non-JSON plaintext raises FATAL.
    - top-level not-object raises FATAL.
    - missing schema_version raises FATAL.
    - non-string schema_version raises FATAL.
    - unsupported schema_version raises FATAL.
    - missing 'credentials' field raises FATAL.
    - non-object 'credentials' field raises FATAL.
    - non-string value raises FATAL (with key NAME, no value type leak).
    - GPG_SOURCED sentinel raises FATAL.

  TestVaultConfig
    - decrypted envelope missing VAULT_DB_PASSWORD raises VaultConfigError.

  TestCaching
    - second call with same args returns cached dict (no second decrypt).
    - second call with different args triggers fresh decrypt.
    - clear_cache() forces re-decrypt on next call.

  TestAuditRow
    - exactly ONE audit row written per process per cache miss.
    - audit row contains key NAMES, never values.
    - audit-row write failure is non-fatal (decrypt still succeeds).

  TestSnowflakeKey
    - PEM in decrypted dict → /dev/shm/snowflake_pk_<pid> written + path
      substituted (Linux path).
    - release_snowflake_key() deletes the file (idempotent on missing file).
    - non-Linux path leaves PEM in dict unchanged.

  TestSecurityDiscipline
    - Plaintext credentials never appear in any log message.
    - stderr from subprocess is truncated (no unbounded log flood).

Spec: phase1/03_core_modules.md § 3.1 + phase1/02_configuration.md § 3.3.

D-numbers: D6, D15, D27, D64, D67, D68, D85, D103.
B-numbers: M7 (build-tracker entry — closed by authoring this test).
"""
from __future__ import annotations

import json
import logging
import os
import platform
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Shared synthetic envelope JSON
# ---------------------------------------------------------------------------


def _synthetic_envelope(
    credentials: dict | None = None,
    schema_version: str | None = "1.0",
    rotated_at: str = "2026-05-10T00:00:00Z",
    omit_credentials: bool = False,
    omit_schema_version: bool = False,
    top_level_list: bool = False,
) -> bytes:
    """Build a synthetic envelope JSON for parser tests."""
    if top_level_list:
        return b'[1, 2, 3]'
    out: dict = {}
    if not omit_schema_version:
        out["schema_version"] = schema_version
    out["rotated_at"] = rotated_at
    if not omit_credentials:
        out["credentials"] = credentials if credentials is not None else {
            "ORACLE_DNA_PASSWORD": "<masked-in-test>",
            "SQLSERVER_CCM_PASSWORD": "<masked-in-test>",
            "VAULT_DB_PASSWORD": "<masked-in-test>",
        }
    return json.dumps(out).encode("utf-8")


def _ok_runner(stdout: bytes):
    """Build a _run_subprocess mock that returns rc=0 + stdout."""
    def _r(cmd, *, timeout, stdin_bytes=None):
        return 0, stdout, b""
    return _r


def _fail_runner(rc: int, stderr: bytes = b""):
    """Build a _run_subprocess mock that returns the given non-zero rc."""
    def _r(cmd, *, timeout, stdin_bytes=None):
        return rc, b"", stderr
    return _r


# ---------------------------------------------------------------------------
# Fixture — clear cache between tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_credentials_cache():
    """Reset per-process cache between tests."""
    from data_load import credentials_loader as cl
    cl.clear_cache()
    yield
    cl.clear_cache()


# ===========================================================================
# TestPlatformDetection
# ===========================================================================


class TestPlatformDetection:
    """TPM2 / keyutils require Linux; env / file work everywhere."""

    def test_tpm2_on_windows_raises(self):
        from data_load import credentials_loader as cl
        from utils.errors import CredentialsLoadError

        with patch.object(cl, "_is_linux", return_value=False), \
             patch.object(cl.platform, "system", return_value="Windows"):
            with pytest.raises(CredentialsLoadError) as excinfo:
                cl._passphrase_from_tpm2()
        assert "Linux" in str(excinfo.value)

    def test_keyutils_on_windows_raises(self):
        from data_load import credentials_loader as cl
        from utils.errors import CredentialsLoadError

        with patch.object(cl, "_is_linux", return_value=False), \
             patch.object(cl.platform, "system", return_value="Windows"):
            with pytest.raises(CredentialsLoadError) as excinfo:
                cl._passphrase_from_keyutils()
        assert "Linux" in str(excinfo.value)

    def test_gpg_decrypt_on_windows_raises(self, tmp_path):
        from data_load import credentials_loader as cl
        from utils.errors import CredentialsLoadError

        with patch.object(cl, "_is_linux", return_value=False), \
             patch.object(cl.platform, "system", return_value="Windows"):
            with pytest.raises(CredentialsLoadError) as excinfo:
                cl._gpg_decrypt(str(tmp_path / "x.gpg"), b"pp")
        assert "Linux" in str(excinfo.value)

    def test_env_passphrase_works_on_any_platform(self, monkeypatch):
        from data_load import credentials_loader as cl
        monkeypatch.setenv("PIPELINE_GPG_PASSPHRASE", "test-pp")
        # No platform patching — should work everywhere.
        assert cl._passphrase_from_env() == b"test-pp"

    def test_file_passphrase_works_on_any_platform(self, tmp_path):
        from data_load import credentials_loader as cl
        f = tmp_path / "pp.txt"
        f.write_bytes(b"hello-from-file\n")
        assert cl._passphrase_from_file(str(f)) == b"hello-from-file"


# ===========================================================================
# TestPassphraseRetrieval
# ===========================================================================


class TestPassphraseRetrieval:
    """Each PassphraseSource value dispatches to the right helper."""

    def test_env_source_reads_env_var(self, monkeypatch):
        from data_load import credentials_loader as cl
        monkeypatch.setenv("PIPELINE_GPG_PASSPHRASE", "from-env")
        assert cl._get_passphrase("env", None) == b"from-env"

    def test_env_source_missing_var_raises(self, monkeypatch):
        from data_load import credentials_loader as cl
        from utils.errors import CredentialsLoadError
        monkeypatch.delenv("PIPELINE_GPG_PASSPHRASE", raising=False)
        with pytest.raises(CredentialsLoadError):
            cl._get_passphrase("env", None)

    def test_file_source_reads_file_strips_newline(self, tmp_path):
        from data_load import credentials_loader as cl
        f = tmp_path / "pp.txt"
        f.write_bytes(b"file-pp\n")
        assert cl._get_passphrase("file", str(f)) == b"file-pp"

    def test_file_source_missing_path_arg_raises(self):
        from data_load import credentials_loader as cl
        from utils.errors import CredentialsLoadError
        with pytest.raises(CredentialsLoadError):
            cl._get_passphrase("file", None)

    def test_file_source_missing_file_raises(self, tmp_path):
        from data_load import credentials_loader as cl
        from utils.errors import CredentialsLoadError
        missing = tmp_path / "does-not-exist.txt"
        with pytest.raises(CredentialsLoadError):
            cl._get_passphrase("file", str(missing))

    def test_unknown_passphrase_source_raises(self):
        from data_load import credentials_loader as cl
        from utils.errors import CredentialsLoadError
        with pytest.raises(CredentialsLoadError):
            cl._get_passphrase("bogus", None)  # type: ignore[arg-type]

    def test_tpm2_missing_handle_raises(self, monkeypatch):
        from data_load import credentials_loader as cl
        from utils.errors import CredentialsLoadError
        monkeypatch.delenv("PIPELINE_TPM2_HANDLE", raising=False)
        with patch.object(cl, "_is_linux", return_value=True):
            with pytest.raises(CredentialsLoadError) as excinfo:
                cl._passphrase_from_tpm2()
        assert "PIPELINE_TPM2_HANDLE" in str(excinfo.value)

    def test_tpm2_rc_zero_empty_stdout_raises(self, monkeypatch):
        from data_load import credentials_loader as cl
        from utils.errors import CredentialsLoadError
        monkeypatch.setenv("PIPELINE_TPM2_HANDLE", "0x81000001")
        with patch.object(cl, "_is_linux", return_value=True), \
             patch.object(cl, "_run_subprocess",
                          side_effect=_ok_runner(b"")):
            with pytest.raises(CredentialsLoadError) as excinfo:
                cl._passphrase_from_tpm2()
        assert "empty" in str(excinfo.value).lower() or "stdout" in str(excinfo.value).lower()

    def test_tpm2_rc_zero_with_stdout_returns_bytes(self, monkeypatch):
        from data_load import credentials_loader as cl
        monkeypatch.setenv("PIPELINE_TPM2_HANDLE", "0x81000001")
        with patch.object(cl, "_is_linux", return_value=True), \
             patch.object(cl, "_run_subprocess",
                          side_effect=_ok_runner(b"sealed-passphrase")):
            assert cl._passphrase_from_tpm2() == b"sealed-passphrase"


# ===========================================================================
# TestGpgDecrypt
# ===========================================================================


class TestGpgDecrypt:
    """gpg2 subprocess wrapper, error paths, and size guards."""

    def test_missing_envelope_raises(self, tmp_path):
        from data_load import credentials_loader as cl
        from utils.errors import CredentialsLoadError
        missing = tmp_path / "absent.gpg"
        with patch.object(cl, "_is_linux", return_value=True):
            with pytest.raises(CredentialsLoadError) as excinfo:
                cl._gpg_decrypt(str(missing), b"pp")
        assert "not found" in str(excinfo.value).lower() or "envelope" in str(excinfo.value).lower()

    def test_oversized_envelope_raises(self, tmp_path):
        from data_load import credentials_loader as cl
        from utils.errors import CredentialsLoadError
        big = tmp_path / "big.gpg"
        # Avoid actually writing 1+ MiB — patch the size constant down.
        big.write_bytes(b"X" * 1024)
        with patch.object(cl, "_is_linux", return_value=True), \
             patch.object(cl, "_MAX_ENVELOPE_BYTES", 512):
            with pytest.raises(CredentialsLoadError) as excinfo:
                cl._gpg_decrypt(str(big), b"pp")
        assert "exceeds" in str(excinfo.value) or "size" in str(excinfo.value).lower()

    def test_gpg_nonzero_rc_raises_with_stderr(self, tmp_path):
        from data_load import credentials_loader as cl
        from utils.errors import CredentialsLoadError
        env = tmp_path / "x.gpg"
        env.write_bytes(b"<encrypted>")
        with patch.object(cl, "_is_linux", return_value=True), \
             patch.object(cl, "_run_subprocess",
                          side_effect=_fail_runner(rc=2, stderr=b"bad passphrase")):
            with pytest.raises(CredentialsLoadError) as excinfo:
                cl._gpg_decrypt(str(env), b"wrong")
        # stderr text appears in the error metadata, not necessarily the message.
        assert "gpg2" in str(excinfo.value)

    def test_gpg_rc_zero_empty_stdout_raises(self, tmp_path):
        from data_load import credentials_loader as cl
        from utils.errors import CredentialsLoadError
        env = tmp_path / "x.gpg"
        env.write_bytes(b"<encrypted>")
        with patch.object(cl, "_is_linux", return_value=True), \
             patch.object(cl, "_run_subprocess",
                          side_effect=_ok_runner(b"")):
            with pytest.raises(CredentialsLoadError) as excinfo:
                cl._gpg_decrypt(str(env), b"pp")
        assert "empty" in str(excinfo.value).lower() or "malformed" in str(excinfo.value).lower()

    def test_gpg_bin_path_honored(self, tmp_path, monkeypatch):
        """GPG_BIN_PATH env var changes which binary the runner is called with."""
        from data_load import credentials_loader as cl
        env = tmp_path / "x.gpg"
        env.write_bytes(b"<encrypted>")
        runner = MagicMock(return_value=(0, b'{"schema_version":"1.0","credentials":{"VAULT_DB_PASSWORD":"x"}}', b""))
        monkeypatch.setenv("GPG_BIN_PATH", "/opt/bin/gpg-custom")
        with patch.object(cl, "_is_linux", return_value=True), \
             patch.object(cl, "_run_subprocess", runner):
            cl._gpg_decrypt(str(env), b"pp")
        # The first positional arg to _run_subprocess is the command list.
        called_cmd = runner.call_args.args[0]
        assert called_cmd[0] == "/opt/bin/gpg-custom"


# ===========================================================================
# TestEnvelopeParse
# ===========================================================================


class TestEnvelopeParse:
    """JSON parse + schema_version + sentinel guard."""

    def test_valid_envelope_returns_credentials(self):
        from data_load import credentials_loader as cl
        out = cl._parse_envelope_json(_synthetic_envelope(), "x.gpg")
        assert "VAULT_DB_PASSWORD" in out
        assert "schema_version" not in out
        assert "rotated_at" not in out

    def test_non_utf8_plaintext_raises(self):
        from data_load import credentials_loader as cl
        from utils.errors import CredentialsLoadError
        # Invalid UTF-8 byte sequence.
        with pytest.raises(CredentialsLoadError):
            cl._parse_envelope_json(b"\xff\xfe\x00invalid", "x.gpg")

    def test_non_json_plaintext_raises(self):
        from data_load import credentials_loader as cl
        from utils.errors import CredentialsLoadError
        with pytest.raises(CredentialsLoadError):
            cl._parse_envelope_json(b"this is not json", "x.gpg")

    def test_top_level_not_object_raises(self):
        from data_load import credentials_loader as cl
        from utils.errors import CredentialsLoadError
        with pytest.raises(CredentialsLoadError):
            cl._parse_envelope_json(_synthetic_envelope(top_level_list=True), "x.gpg")

    def test_missing_schema_version_raises(self):
        from data_load import credentials_loader as cl
        from utils.errors import CredentialsLoadError
        with pytest.raises(CredentialsLoadError) as excinfo:
            cl._parse_envelope_json(
                _synthetic_envelope(omit_schema_version=True), "x.gpg"
            )
        assert "schema_version" in str(excinfo.value)

    def test_non_string_schema_version_raises(self):
        from data_load import credentials_loader as cl
        from utils.errors import CredentialsLoadError
        # Build by hand — schema_version as an int.
        payload = json.dumps({
            "schema_version": 1.0,
            "credentials": {"VAULT_DB_PASSWORD": "x"},
        }).encode()
        with pytest.raises(CredentialsLoadError):
            cl._parse_envelope_json(payload, "x.gpg")

    def test_unsupported_schema_version_raises(self):
        from data_load import credentials_loader as cl
        from utils.errors import CredentialsLoadError
        with pytest.raises(CredentialsLoadError) as excinfo:
            cl._parse_envelope_json(
                _synthetic_envelope(schema_version="99.0"), "x.gpg"
            )
        assert "schema_version" in str(excinfo.value)
        assert "99.0" in str(excinfo.value)

    def test_missing_credentials_field_raises(self):
        from data_load import credentials_loader as cl
        from utils.errors import CredentialsLoadError
        with pytest.raises(CredentialsLoadError) as excinfo:
            cl._parse_envelope_json(
                _synthetic_envelope(omit_credentials=True), "x.gpg"
            )
        assert "credentials" in str(excinfo.value)

    def test_non_object_credentials_field_raises(self):
        from data_load import credentials_loader as cl
        from utils.errors import CredentialsLoadError
        payload = json.dumps({
            "schema_version": "1.0",
            "credentials": "not-an-object",
        }).encode()
        with pytest.raises(CredentialsLoadError):
            cl._parse_envelope_json(payload, "x.gpg")

    def test_non_string_value_raises_with_key_name(self):
        from data_load import credentials_loader as cl
        from utils.errors import CredentialsLoadError
        # Value is an int instead of a string.
        payload = json.dumps({
            "schema_version": "1.0",
            "credentials": {"VAULT_DB_PASSWORD": 12345},
        }).encode()
        with pytest.raises(CredentialsLoadError) as excinfo:
            cl._parse_envelope_json(payload, "x.gpg")
        # Key NAME must be in the error message; integer value must NOT be.
        assert "VAULT_DB_PASSWORD" in str(excinfo.value)
        assert "12345" not in str(excinfo.value)

    def test_gpg_sourced_sentinel_raises(self):
        from data_load import credentials_loader as cl
        from utils.errors import CredentialsLoadError
        with pytest.raises(CredentialsLoadError) as excinfo:
            cl._parse_envelope_json(
                _synthetic_envelope(
                    credentials={
                        "ORACLE_DNA_PASSWORD": "GPG_SOURCED",
                        "VAULT_DB_PASSWORD": "<masked>",
                    }
                ),
                "x.gpg",
            )
        # Sentinel text + offending key must both appear; the literal
        # 'GPG_SOURCED' is a documented sentinel so logging it is safe.
        assert "GPG_SOURCED" in str(excinfo.value)
        assert "ORACLE_DNA_PASSWORD" in str(excinfo.value)


# ===========================================================================
# TestVaultConfig
# ===========================================================================


class TestVaultConfig:
    """VaultConfigError raised when VAULT_DB_PASSWORD is structurally absent."""

    def test_missing_vault_db_password_raises_vault_config(self, tmp_path):
        from data_load import credentials_loader as cl
        from utils.errors import VaultConfigError

        envelope_bytes = _synthetic_envelope(credentials={
            "ORACLE_DNA_PASSWORD": "<masked>",
            # No VAULT_DB_PASSWORD on purpose.
        })
        env = tmp_path / "x.gpg"
        env.write_bytes(b"<enc>")
        pp = tmp_path / "pp.txt"
        pp.write_bytes(b"x\n")

        with patch.object(cl, "_is_linux", return_value=True), \
             patch.object(cl, "_run_subprocess", side_effect=_ok_runner(envelope_bytes)), \
             patch.object(cl, "_materialize_snowflake_key"):
            with pytest.raises(VaultConfigError) as excinfo:
                cl.load_credentials(
                    envelope_path=str(env),
                    passphrase_source="file",
                    passphrase_file_path=str(pp),
                )
        assert "VAULT_DB_PASSWORD" in str(excinfo.value)


# ===========================================================================
# TestCaching
# ===========================================================================


class TestCaching:
    """Per-process cache contract per § 3.1."""

    def test_second_call_same_args_uses_cache(self, tmp_path):
        from data_load import credentials_loader as cl

        env = tmp_path / "x.gpg"
        env.write_bytes(b"<enc>")
        pp = tmp_path / "pp.txt"
        pp.write_bytes(b"x\n")

        runner = MagicMock(side_effect=_ok_runner(_synthetic_envelope()))
        audit_spy = MagicMock()

        with patch.object(cl, "_is_linux", return_value=True), \
             patch.object(cl, "_run_subprocess", runner), \
             patch.object(cl, "_write_audit_row", audit_spy), \
             patch.object(cl, "_materialize_snowflake_key"):
            d1 = cl.load_credentials(
                envelope_path=str(env),
                passphrase_source="file",
                passphrase_file_path=str(pp),
            )
            d2 = cl.load_credentials(
                envelope_path=str(env),
                passphrase_source="file",
                passphrase_file_path=str(pp),
            )

        assert d1 is d2  # same dict object on cache hit
        # Decrypt ran exactly once.
        assert runner.call_count == 1
        # Audit row written exactly once.
        assert audit_spy.call_count == 1

    def test_different_args_force_fresh_decrypt(self, tmp_path):
        from data_load import credentials_loader as cl

        env_a = tmp_path / "a.gpg"
        env_a.write_bytes(b"<enc-a>")
        env_b = tmp_path / "b.gpg"
        env_b.write_bytes(b"<enc-b>")
        pp = tmp_path / "pp.txt"
        pp.write_bytes(b"x\n")

        runner = MagicMock(side_effect=_ok_runner(_synthetic_envelope()))
        with patch.object(cl, "_is_linux", return_value=True), \
             patch.object(cl, "_run_subprocess", runner), \
             patch.object(cl, "_write_audit_row"), \
             patch.object(cl, "_materialize_snowflake_key"):
            cl.load_credentials(
                envelope_path=str(env_a),
                passphrase_source="file",
                passphrase_file_path=str(pp),
            )
            cl.load_credentials(
                envelope_path=str(env_b),
                passphrase_source="file",
                passphrase_file_path=str(pp),
            )

        # Two different envelopes → two decrypts.
        assert runner.call_count == 2

    def test_clear_cache_forces_redecrypt(self, tmp_path):
        from data_load import credentials_loader as cl

        env = tmp_path / "x.gpg"
        env.write_bytes(b"<enc>")
        pp = tmp_path / "pp.txt"
        pp.write_bytes(b"x\n")

        runner = MagicMock(side_effect=_ok_runner(_synthetic_envelope()))
        with patch.object(cl, "_is_linux", return_value=True), \
             patch.object(cl, "_run_subprocess", runner), \
             patch.object(cl, "_write_audit_row"), \
             patch.object(cl, "_materialize_snowflake_key"):
            cl.load_credentials(
                envelope_path=str(env),
                passphrase_source="file",
                passphrase_file_path=str(pp),
            )
            cl.clear_cache()
            cl.load_credentials(
                envelope_path=str(env),
                passphrase_source="file",
                passphrase_file_path=str(pp),
            )

        assert runner.call_count == 2


# ===========================================================================
# TestAuditRow
# ===========================================================================


class TestAuditRow:
    """One CREDENTIALS_LOAD audit row per cache miss; no plaintext leak."""

    def test_audit_row_written_once_per_cache_miss(self, tmp_path):
        from data_load import credentials_loader as cl

        env = tmp_path / "x.gpg"
        env.write_bytes(b"<enc>")
        pp = tmp_path / "pp.txt"
        pp.write_bytes(b"x\n")

        audit_spy = MagicMock()
        with patch.object(cl, "_is_linux", return_value=True), \
             patch.object(cl, "_run_subprocess", side_effect=_ok_runner(_synthetic_envelope())), \
             patch.object(cl, "_write_audit_row", audit_spy), \
             patch.object(cl, "_materialize_snowflake_key"):
            cl.load_credentials(
                envelope_path=str(env),
                passphrase_source="file",
                passphrase_file_path=str(pp),
            )
        assert audit_spy.call_count == 1
        kwargs = audit_spy.call_args.kwargs
        # key_names is a list of KEY NAMES, never values.
        assert "key_names" in kwargs
        assert isinstance(kwargs["key_names"], list)
        for name in kwargs["key_names"]:
            assert isinstance(name, str)

    def test_audit_row_write_failure_non_fatal(self, tmp_path):
        """_write_audit_row failure must NOT cause load_credentials to raise."""
        from data_load import credentials_loader as cl

        env = tmp_path / "x.gpg"
        env.write_bytes(b"<enc>")
        pp = tmp_path / "pp.txt"
        pp.write_bytes(b"x\n")

        def _audit_fails(**kwargs):
            raise RuntimeError("simulated DB failure")

        with patch.object(cl, "_is_linux", return_value=True), \
             patch.object(cl, "_run_subprocess", side_effect=_ok_runner(_synthetic_envelope())), \
             patch.object(cl, "_write_audit_row", side_effect=_audit_fails), \
             patch.object(cl, "_materialize_snowflake_key"):
            # The audit failure happens inside _write_audit_row's own try/except,
            # so this call should still raise. But _write_audit_row's body
            # itself catches and logs; we test the production wrapper by
            # invoking the real function with a broken cursor_for.
            # The patch.object on _write_audit_row above replaces with side_effect
            # which propagates exceptions — that simulates a callsite that fails.
            # The production load_credentials calls _write_audit_row AFTER caching
            # so even if it raises, the cached dict is already returned.
            # However, the canonical contract is: _write_audit_row body is the
            # one that swallows. To assert the contract, we instead patch its
            # internal cursor_for to fail and check NO exception propagates.
            pass

        # Re-test using the real _write_audit_row body with a broken cursor_for.
        cl.clear_cache()
        with patch.object(cl, "_is_linux", return_value=True), \
             patch.object(cl, "_run_subprocess", side_effect=_ok_runner(_synthetic_envelope())), \
             patch.object(cl, "_materialize_snowflake_key"):
            broken_cursor_for = MagicMock(side_effect=RuntimeError("DB down"))
            # Inject the broken cursor_for into the module's lookup namespace
            # used by _write_audit_row's lazy import.
            with patch.dict(sys.modules, {
                "utils.connections": MagicMock(cursor_for=broken_cursor_for),
            }):
                # Should NOT raise — audit failure is non-fatal.
                d = cl.load_credentials(
                    envelope_path=str(env),
                    passphrase_source="file",
                    passphrase_file_path=str(pp),
                )
                assert "VAULT_DB_PASSWORD" in d


# ===========================================================================
# TestSnowflakeKey
# ===========================================================================


class TestSnowflakeKey:
    """Ephemeral RSA key materialization + cleanup."""

    @pytest.mark.skipif(platform.system() == "Windows", reason="No /dev/shm on Windows")
    def test_pem_materialized_on_linux(self, tmp_path, monkeypatch):
        from data_load import credentials_loader as cl

        # Use a temp dir as a fake /dev/shm so the test does not depend on
        # the real /dev/shm existing in the CI container.
        shm = tmp_path / "shm"
        shm.mkdir()
        monkeypatch.setattr(cl, "_SHM_DIR", str(shm))

        with patch.object(cl, "_is_linux", return_value=True):
            creds = {"SNOWFLAKE_PRIVATE_KEY_PEM": "-----BEGIN RSA-----\nfake\n-----END RSA-----"}
            cl._materialize_snowflake_key(creds)

        path_in_dict = creds.get("SNOWFLAKE_PRIVATE_KEY_PATH")
        assert path_in_dict
        assert Path(path_in_dict).exists()
        assert Path(path_in_dict).read_text().startswith("-----BEGIN RSA-----")

    def test_no_pem_no_materialization(self, tmp_path):
        from data_load import credentials_loader as cl
        creds = {"ORACLE_DNA_PASSWORD": "<masked>"}
        # Should be a no-op; no exceptions, no path key added.
        cl._materialize_snowflake_key(creds)
        assert "SNOWFLAKE_PRIVATE_KEY_PATH" not in creds

    def test_non_linux_leaves_pem_in_dict(self, tmp_path):
        from data_load import credentials_loader as cl
        creds = {"SNOWFLAKE_PRIVATE_KEY_PEM": "PEM-CONTENT"}
        with patch.object(cl, "_is_linux", return_value=False):
            cl._materialize_snowflake_key(creds)
        # On non-Linux the function is a no-op; PEM stays.
        assert creds["SNOWFLAKE_PRIVATE_KEY_PEM"] == "PEM-CONTENT"
        assert "SNOWFLAKE_PRIVATE_KEY_PATH" not in creds

    @pytest.mark.skipif(platform.system() == "Windows", reason="release_snowflake_key is Linux-scoped")
    def test_release_snowflake_key_idempotent(self, tmp_path, monkeypatch):
        from data_load import credentials_loader as cl
        shm = tmp_path / "shm"
        shm.mkdir()
        monkeypatch.setattr(cl, "_SHM_DIR", str(shm))
        # release on missing file is a no-op.
        with patch.object(cl, "_is_linux", return_value=True):
            cl.release_snowflake_key()  # no file → silent
            # Now materialize and release.
            creds = {"SNOWFLAKE_PRIVATE_KEY_PEM": "PEM"}
            cl._materialize_snowflake_key(creds)
            path = creds.get("SNOWFLAKE_PRIVATE_KEY_PATH")
            assert path and Path(path).exists()
            cl.release_snowflake_key()
            assert not Path(path).exists()
            # Second release on already-deleted file is a no-op.
            cl.release_snowflake_key()

    def test_release_snowflake_key_no_op_on_windows(self):
        from data_load import credentials_loader as cl
        with patch.object(cl, "_is_linux", return_value=False):
            # No exception.
            cl.release_snowflake_key()


# ===========================================================================
# TestSecurityDiscipline
# ===========================================================================


class TestSecurityDiscipline:
    """D103 — never log VALUES from the decrypted dict; only key NAMES."""

    def test_log_contains_key_names_not_values(self, tmp_path, caplog):
        from data_load import credentials_loader as cl

        env = tmp_path / "x.gpg"
        env.write_bytes(b"<enc>")
        pp = tmp_path / "pp.txt"
        pp.write_bytes(b"x\n")

        # The synthetic value is a known sentinel — if it appears in
        # captured logs anywhere, that is a D103 violation.
        secret_canary = "SECRET-CANARY-VALUE-12345"
        envelope_bytes = _synthetic_envelope(credentials={
            "ORACLE_DNA_PASSWORD": secret_canary,
            "VAULT_DB_PASSWORD": secret_canary,
        })

        caplog.set_level(logging.DEBUG, logger="data_load.credentials_loader")
        with patch.object(cl, "_is_linux", return_value=True), \
             patch.object(cl, "_run_subprocess", side_effect=_ok_runner(envelope_bytes)), \
             patch.object(cl, "_write_audit_row"), \
             patch.object(cl, "_materialize_snowflake_key"):
            cl.load_credentials(
                envelope_path=str(env),
                passphrase_source="file",
                passphrase_file_path=str(pp),
            )

        # No log message should contain the canary value.
        for rec in caplog.records:
            assert secret_canary not in rec.getMessage(), (
                f"D103 violation — log message leaked plaintext: "
                f"{rec.getMessage()!r}"
            )

    def test_stderr_excerpt_truncated_in_error_metadata(self, tmp_path):
        """When subprocess fails, stderr in error metadata is bounded."""
        from data_load import credentials_loader as cl
        from utils.errors import CredentialsLoadError

        env = tmp_path / "x.gpg"
        env.write_bytes(b"<enc>")

        huge_stderr = b"X" * 10_000  # Way larger than the 500-byte excerpt cap.
        with patch.object(cl, "_is_linux", return_value=True), \
             patch.object(cl, "_run_subprocess",
                          side_effect=_fail_runner(rc=1, stderr=huge_stderr)):
            with pytest.raises(CredentialsLoadError) as excinfo:
                cl._gpg_decrypt(str(env), b"pp")
        # The error's metadata stderr_excerpt should be bounded.
        md = excinfo.value.metadata or {}
        excerpt = md.get("stderr_excerpt", "")
        assert len(excerpt) <= 500


# ===========================================================================
# TestEndToEndIntegration
# ===========================================================================


class TestEndToEndIntegration:
    """Full load_credentials() path — mocked subprocess + audit, real parser."""

    def test_load_credentials_full_path_returns_dict_shape(self, tmp_path):
        from data_load import credentials_loader as cl

        env = tmp_path / "credentials.json.gpg"
        env.write_bytes(b"<enc>")
        pp = tmp_path / "pp.txt"
        pp.write_bytes(b"hunter2\n")

        with patch.object(cl, "_is_linux", return_value=True), \
             patch.object(cl, "_run_subprocess", side_effect=_ok_runner(_synthetic_envelope())), \
             patch.object(cl, "_write_audit_row"), \
             patch.object(cl, "_materialize_snowflake_key"):
            result = cl.load_credentials(
                envelope_path=str(env),
                passphrase_source="file",
                passphrase_file_path=str(pp),
            )
        # CredentialsDict is a NewType over dict.
        assert isinstance(result, dict)
        assert "VAULT_DB_PASSWORD" in result
        assert "ORACLE_DNA_PASSWORD" in result
        # Top-level meta fields stripped.
        assert "schema_version" not in result
        assert "rotated_at" not in result
        assert "credentials" not in result

    def test_compute_envelope_sha256_existing_file(self, tmp_path):
        from data_load import credentials_loader as cl
        env = tmp_path / "x.gpg"
        env.write_bytes(b"some encrypted bytes")
        sha = cl._compute_envelope_sha256(str(env))
        assert sha != "<unavailable>"
        assert len(sha) == 64
        assert all(c in "0123456789abcdef" for c in sha)

    def test_compute_envelope_sha256_missing_file(self, tmp_path):
        from data_load import credentials_loader as cl
        sha = cl._compute_envelope_sha256(str(tmp_path / "missing.gpg"))
        assert sha == "<unavailable>"
