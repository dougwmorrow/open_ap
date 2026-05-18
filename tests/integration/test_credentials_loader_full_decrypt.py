"""Tier 3 integration tests for data_load/credentials_loader.py full-decrypt path.

Per docs/migration/phase1/05_tests.md § 6.2 canonical scenario:
"Real GPG envelope (test key) -> decrypt -> validate CredentialsDict shape
+ audit event written".

Canonical signature under test (per phase1/03_core_modules.md § 3.1):

    def load_credentials(
        envelope_path: str = CANONICAL_ENVELOPE_PATH,
        passphrase_source: PassphraseSource = "tpm2",
        passphrase_file_path: str | None = None,
        *,
        actor: str | None = None,
    ) -> CredentialsDict:
        ...

    def release_snowflake_key() -> None: ...
    def clear_cache() -> None: ...

D-numbers covered:
  - D6  (vault credentials live in the envelope) - structural prerequisite
    the loader enforces via VaultConfigError when VAULT_DB_PASSWORD is absent.
  - D27 (cross-server parity) - envelope SHA-256 recorded in audit metadata.
  - D64 (TPM2 passphrase storage) - production passphrase_source.
  - D67 (Tier 0 smoke required).
  - D68 (error class hierarchy) - CredentialsLoadError carries metadata
    kwarg per § 3.1 error modes.
  - D76 (audit-row contract) - exactly one CREDENTIALS_LOAD event row
    on success, including envelope_sha256 + passphrase_source + key_names
    metadata (NEVER values - P5 invariant).
  - D85 (module startup sequence Stage 1: CREDS_LOAD).
  - D103 (Claude Code security model) - canonical envelope path lives
    OUTSIDE /debi; sentinel GPG_SOURCED detection is FATAL.
  - P5  (PII redaction) - NEVER log credential values.

The flow under test (per § 3.3):
  1. Get passphrase (TPM2 / keyutils / env / file).
  2. gpg2 --batch --pinentry-mode loopback --passphrase-fd 0 --decrypt.
  3. Parse JSON; validate schema_version; sentinel-detect.
  4. Materialize Snowflake RSA key to /dev/shm if present.
  5. INSERT one 'CREDENTIALS_LOAD' audit row to PipelineEventLog.
  6. Cache the dict per-process; subsequent calls return from cache.

The gpg2 subprocess is mocked because the Tier 3 container does NOT have
gpg2 installed AND the canonical /etc/pipeline/credentials.json.gpg
envelope lives OUTSIDE the /debi working directory per D103. Mocking
``_run_subprocess`` (the single subprocess wrapper) is the cleanest
seam: it returns ``(rc, stdout, stderr)`` tuples; the rest of the
decrypt + JSON parse + audit-row write path is real code running
against the real container's PipelineEventLog table.

Module-level skip pattern per scaffold pattern: import
``docker_skip_marker`` from conftest, set ``pytestmark``; tests skip
cleanly when Docker is unavailable.
"""
from __future__ import annotations

import json
import logging
import sys
import tempfile
from pathlib import Path
from typing import Any
from unittest import mock

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# Module-level skip via the canonical conftest helper - same activation
# pattern as the sibling Tier 3 test files (B-115 follow-up 2026-05-14).
from tests.integration.conftest import docker_skip_marker  # noqa: E402

pytestmark = docker_skip_marker()


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers - canonical envelope plaintext per § 3.1.
#
# A minimal but spec-compliant envelope: schema_version + credentials with
# the structurally-required VAULT_DB_PASSWORD plus a handful of typical keys.
# The "values" are obviously-non-secret test strings - never deployed.
# ---------------------------------------------------------------------------


_CANONICAL_TEST_ENVELOPE = {
    "schema_version": "1.0",
    "rotated_at": "2026-05-14T00:00:00Z",
    "credentials": {
        "ORACLE_DNA_PASSWORD": "test_oracle_dna_password_NOT_REAL",
        "SQLSERVER_CCM_PASSWORD": "test_ccm_password_NOT_REAL",
        "SQLSERVER_EPICOR_PASSWORD": "test_epicor_password_NOT_REAL",
        "TARGET_PASSWORD": "test_target_password_NOT_REAL",
        "VAULT_DB_PASSWORD": "test_vault_password_NOT_REAL",
    },
}


def _canonical_envelope_bytes() -> bytes:
    """Return the canonical test envelope serialized as JSON bytes."""
    return json.dumps(_CANONICAL_TEST_ENVELOPE).encode("utf-8")


def _sentinel_envelope_bytes() -> bytes:
    """Return an envelope whose VAULT_DB_PASSWORD is the FATAL sentinel.

    Per § 3.1 the literal string 'GPG_SOURCED' inside the decrypted dict
    indicates a re-substitution bug - the loader MUST raise immediately.
    """
    payload = {
        "schema_version": "1.0",
        "rotated_at": "2026-05-14T00:00:00Z",
        "credentials": {
            "ORACLE_DNA_PASSWORD": "real_value",
            "VAULT_DB_PASSWORD": "GPG_SOURCED",  # the FATAL sentinel
        },
    }
    return json.dumps(payload).encode("utf-8")


# ---------------------------------------------------------------------------
# Test class - full decrypt path + audit-row write + sentinel detection.
# ---------------------------------------------------------------------------


class TestCredentialsLoaderFullDecrypt:
    """End-to-end credentials_loader contract per § 3.1 / § 3.3.

    The mocks are surgical: only ``_run_subprocess`` is replaced (the
    single seam through which gpg2 / tpm2_unseal flow). Everything else
    - JSON parsing, schema_version validation, sentinel guard, audit-row
    INSERT, cache - is the real production code running against the
    real container.
    """

    def _patch_subprocess_with_envelope(
        self,
        envelope_bytes: bytes,
        *,
        passphrase: bytes = b"test-passphrase-NOT-REAL",
    ) -> mock._patch:
        """Return a mock-patch over ``_run_subprocess`` that returns
        ``envelope_bytes`` on the gpg2 decrypt path.

        Mirrors the production wrapper's ``(returncode, stdout, stderr)``
        tuple contract.
        """
        def fake_run(cmd: list[str], **kwargs: Any) -> tuple[int, bytes, bytes]:
            # The single seam: gpg2 --decrypt path. We do NOT need to
            # mock tpm2_unseal because the test uses passphrase_source='env'
            # which never shells out.
            if cmd and "gpg2" in cmd[0] or "--decrypt" in cmd:
                return (0, envelope_bytes, b"")
            # Unknown subprocess call - test setup bug.
            raise AssertionError(
                f"Unexpected subprocess call in mock: cmd={cmd!r}"
            )

        return mock.patch(
            "data_load.credentials_loader._run_subprocess",
            side_effect=fake_run,
        )

    def test_decrypt_test_envelope_returns_credentials_dict_shape(
        self,
        mssql_cursor: Any,
        test_db_transaction: Any,
        canonical_schema_loaded: None,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Decrypt the canonical test envelope -> CredentialsDict shape.

        Per § 3.1 plaintext-envelope spec: the returned dict flattens
        ``credentials`` to the top level, drops ``schema_version`` and
        ``rotated_at``. Every key + value is a string. The dict carries
        the structurally-required VAULT_DB_PASSWORD plus whatever other
        keys appeared in the envelope's credentials sub-dict.
        """
        from data_load.credentials_loader import (  # noqa: PLC0415
            clear_cache,
            load_credentials,
        )

        # Reset per-process cache so prior tests cannot leak in.
        clear_cache()

        # Force the env-passphrase path so we never shell out to tpm2_unseal.
        monkeypatch.setenv("PIPELINE_GPG_PASSPHRASE", "test-passphrase-NOT-REAL")

        # Use a tmp envelope path that EXISTS on disk (the loader stats
        # the file even though we mock the decrypt subprocess) - the
        # contents are irrelevant; the mock supplies the plaintext.
        envelope = tmp_path / "credentials.json.gpg"
        envelope.write_bytes(b"<ciphertext placeholder>")

        # Patch the platform probe + the subprocess wrapper so the test
        # runs cross-platform. _is_linux gates the gpg path; we force
        # True so the Linux decrypt branch executes against the mock.
        with mock.patch(
            "data_load.credentials_loader._is_linux", return_value=True
        ), self._patch_subprocess_with_envelope(_canonical_envelope_bytes()):
            result = load_credentials(
                envelope_path=str(envelope),
                passphrase_source="env",
                actor="test-tier3",
            )

        # CredentialsDict is a NewType over dict[str, str]; runtime
        # check is via isinstance(dict, ...) since NewType erases.
        assert isinstance(result, dict), (
            f"load_credentials must return a dict; got {type(result).__name__}"
        )
        # Every key + value must be a string (P5 + § 3.1).
        for key, value in result.items():
            assert isinstance(key, str), f"Non-string key {key!r}"
            assert isinstance(value, str), (
                f"Non-string value for key={key!r}; got {type(value).__name__}"
            )

        # Structural prerequisite per § 3.1: VAULT_DB_PASSWORD MUST be
        # present in the returned dict (otherwise VaultConfigError fires).
        assert "VAULT_DB_PASSWORD" in result, (
            "VAULT_DB_PASSWORD must be present in decrypted envelope; "
            f"got keys {sorted(result.keys())}"
        )
        assert result["VAULT_DB_PASSWORD"] == "test_vault_password_NOT_REAL"

        # Schema_version / rotated_at MUST NOT leak into the returned dict.
        assert "schema_version" not in result
        assert "rotated_at" not in result

        # Sample other expected keys per the canonical test envelope.
        assert "ORACLE_DNA_PASSWORD" in result
        assert "SQLSERVER_CCM_PASSWORD" in result

    def test_decrypt_with_audit_event_written(
        self,
        mssql_cursor: Any,
        test_db_transaction: Any,
        canonical_schema_loaded: None,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Successful decrypt writes exactly one CREDENTIALS_LOAD audit row.

        Per D76 + § 3.1 + § 3.5: one PipelineEventLog row with
        EventType='CREDENTIALS_LOAD' carrying Metadata JSON =
        {envelope_sha256, envelope_path, passphrase_source, key_names}.

        Key invariant (P5 / D103): the Metadata JSON includes KEY NAMES
        only, NEVER values. We assert the absence of any plaintext
        credential VALUE in the audit row.
        """
        from data_load.credentials_loader import (  # noqa: PLC0415
            clear_cache,
            load_credentials,
        )

        clear_cache()
        monkeypatch.setenv("PIPELINE_GPG_PASSPHRASE", "test-passphrase-NOT-REAL")

        envelope = tmp_path / "credentials.json.gpg"
        envelope.write_bytes(b"<ciphertext placeholder>")

        # Count of CREDENTIALS_LOAD events BEFORE the call so we can
        # assert exactly one row was written (the test runs inside
        # test_db_transaction; the rollback discards it at exit).
        mssql_cursor.execute(
            "SELECT COUNT(*) FROM General.ops.PipelineEventLog "
            "WHERE EventType = 'CREDENTIALS_LOAD'"
        )
        before_count = mssql_cursor.fetchone()[0]

        with mock.patch(
            "data_load.credentials_loader._is_linux", return_value=True
        ), self._patch_subprocess_with_envelope(_canonical_envelope_bytes()):
            load_credentials(
                envelope_path=str(envelope),
                passphrase_source="env",
                actor="test-audit-row",
            )

        # Post-condition: exactly ONE new CREDENTIALS_LOAD row.
        mssql_cursor.execute(
            "SELECT COUNT(*) FROM General.ops.PipelineEventLog "
            "WHERE EventType = 'CREDENTIALS_LOAD'"
        )
        after_count = mssql_cursor.fetchone()[0]
        assert after_count == before_count + 1, (
            f"Expected exactly 1 new CREDENTIALS_LOAD row; "
            f"got delta {after_count - before_count}"
        )

        # Fetch + inspect the row's Metadata JSON to verify P5 invariant.
        mssql_cursor.execute(
            """
            SELECT TOP 1 Status, Metadata, EventDetail
            FROM General.ops.PipelineEventLog
            WHERE EventType = 'CREDENTIALS_LOAD'
            ORDER BY EventLogId DESC
            """
        )
        row = mssql_cursor.fetchone()
        assert row is not None, "Could not fetch CREDENTIALS_LOAD row"
        status, metadata_json, event_detail = row
        assert status == "SUCCESS", f"Expected Status='SUCCESS'; got {status!r}"

        metadata = json.loads(metadata_json or "{}")
        # P5 + D103: KEY NAMES only, NEVER values.
        assert "key_names" in metadata, (
            f"Metadata must carry key_names; got {sorted(metadata.keys())}"
        )
        assert isinstance(metadata["key_names"], list)
        assert "VAULT_DB_PASSWORD" in metadata["key_names"]

        # Defense-in-depth: assert NO known plaintext value leaked into
        # the row. The test envelope's values all contain the literal
        # 'NOT_REAL' so we scan the full row text.
        row_text = json.dumps({"metadata": metadata, "event_detail": event_detail})
        assert "NOT_REAL" not in row_text, (
            "P5 INVARIANT VIOLATED - credential VALUE leaked into "
            f"PipelineEventLog row: {row_text!r}"
        )

        # Audit row must carry envelope_sha256 + passphrase_source.
        assert "envelope_sha256" in metadata
        assert metadata.get("passphrase_source") == "env"

    def test_decrypt_sentinel_detection_raises(
        self,
        mssql_cursor: Any,
        test_db_transaction: Any,
        canonical_schema_loaded: None,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """GPG_SOURCED sentinel inside the decrypted dict raises FATAL.

        Per § 3.1: the literal string 'GPG_SOURCED' is the .env
        placeholder per § 2.3 - it marks every key that MUST be sourced
        from the envelope. If the decrypted envelope returns
        'GPG_SOURCED' as a VALUE, an operator copied the placeholder
        INTO the envelope itself OR there is a re-substitution bug.
        The loader raises CredentialsLoadError immediately.
        """
        from data_load.credentials_loader import (  # noqa: PLC0415
            clear_cache,
            load_credentials,
        )
        from utils.errors import CredentialsLoadError  # noqa: PLC0415

        clear_cache()
        monkeypatch.setenv("PIPELINE_GPG_PASSPHRASE", "test-passphrase-NOT-REAL")

        envelope = tmp_path / "credentials.json.gpg"
        envelope.write_bytes(b"<ciphertext placeholder>")

        with mock.patch(
            "data_load.credentials_loader._is_linux", return_value=True
        ), self._patch_subprocess_with_envelope(_sentinel_envelope_bytes()):
            with pytest.raises(CredentialsLoadError) as exc_info:
                load_credentials(
                    envelope_path=str(envelope),
                    passphrase_source="env",
                    actor="test-sentinel",
                )

        # Per D68: metadata kwarg carries per-raise context. The
        # offending_key should identify which key carried the sentinel.
        meta = exc_info.value.metadata
        assert meta is not None, "CredentialsLoadError must carry metadata"
        assert meta.get("offending_key") == "VAULT_DB_PASSWORD", (
            f"Expected offending_key='VAULT_DB_PASSWORD'; got {meta!r}"
        )
        # The exception message MUST mention the sentinel literal so
        # operators can grep PipelineLog for incidents.
        assert "GPG_SOURCED" in str(exc_info.value), (
            f"Exception message must reference the sentinel; got "
            f"{str(exc_info.value)!r}"
        )

    def test_release_snowflake_key_cleans_tmpfs(
        self,
        mssql_cursor: Any,
        test_db_transaction: Any,
        canonical_schema_loaded: None,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """release_snowflake_key removes /dev/shm/snowflake_pk_<pid>.

        Per § 3.3: the canonical Snowflake key path template is
        ``/dev/shm/snowflake_pk_<pid>`` mode 0600. release_snowflake_key
        unlinks the file - idempotent, safe to call on non-Linux (no-op).

        The test substitutes ``tmp_path`` for ``/dev/shm`` via monkeypatch
        on the private module constant so the file lives in pytest's
        temp dir (works cross-platform).
        """
        from data_load import credentials_loader  # noqa: PLC0415
        from data_load.credentials_loader import (  # noqa: PLC0415
            release_snowflake_key,
        )

        # Substitute tmp_path for /dev/shm so the test is platform-agnostic.
        monkeypatch.setattr(credentials_loader, "_SHM_DIR", str(tmp_path))
        # Force the Linux branch so release_snowflake_key actually
        # attempts the unlink (otherwise it short-circuits).
        monkeypatch.setattr(
            credentials_loader, "_is_linux", lambda: True
        )

        import os as _os
        pid = _os.getpid()
        key_path = tmp_path / credentials_loader._SHM_SNOWFLAKE_KEY_TEMPLATE.format(
            pid=pid
        )
        # Setup: write a fake key file so release has something to delete.
        key_path.write_text(
            "-----BEGIN RSA PRIVATE KEY-----\n<fake>\n-----END RSA PRIVATE KEY-----\n"
        )
        assert key_path.exists(), "Setup failed - key file must exist before release"

        # Act: release should unlink the file.
        release_snowflake_key()

        # Post-condition: file is GONE.
        assert not key_path.exists(), (
            f"release_snowflake_key did not unlink {key_path!r}"
        )

        # Idempotent: second call MUST be a no-op (no exception, file
        # still absent).
        release_snowflake_key()
        assert not key_path.exists()
