"""Tier 1 unit test for observability/sensitive_data_filter.py.

Per D70 Tier 1 — per-pattern + per-error-path coverage; <5 min runtime;
no external deps.

Spec: phase1/03_core_modules.md § 6.1 + P5.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _record(msg, *, args=None) -> logging.LogRecord:
    return logging.LogRecord(
        name="t",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args,
        exc_info=None,
    )


# ---------------------------------------------------------------------------
# Default pattern coverage — each default pattern must match its target
# ---------------------------------------------------------------------------


class TestDefaultPatterns:

    def test_password_pattern(self):
        from observability.sensitive_data_filter import SensitiveDataFilter

        flt = SensitiveDataFilter()
        cases = [
            "MSSQL_PASSWORD=topsecret123",
            "user_password=foo",
            "vault_db_password = bar",
            "Password : qux",
        ]
        for msg in cases:
            rec = _record(msg)
            flt.filter(rec)
            assert "<REDACTED:password>" in rec.msg, (
                f"Failed to redact: {msg!r} → {rec.msg!r}"
            )
            # The plaintext value must not survive
            for plaintext in ["topsecret123", "foo", "bar", "qux"]:
                if plaintext in msg:
                    assert plaintext not in rec.msg

    def test_rsa_private_key_pattern_multiline(self):
        """RSA private keys span multiple lines and must be redacted as a block."""
        from observability.sensitive_data_filter import SensitiveDataFilter

        rsa_block = (
            "-----BEGIN RSA PRIVATE KEY-----\n"
            "MIIEowIBAAKCAQEAtopsecretRSAkeycontentNeverLogged\n"
            "abcdefghijklmnopqrstuvwxyz0123456789\n"
            "-----END RSA PRIVATE KEY-----"
        )
        msg = f"Loading Snowflake key:\n{rsa_block}\nDone."

        flt = SensitiveDataFilter()
        rec = _record(msg)
        flt.filter(rec)
        assert "topsecretRSAkeycontentNeverLogged" not in rec.msg
        assert "<REDACTED:rsa_private_key>" in rec.msg

    def test_gpg_passphrase_pattern(self):
        from observability.sensitive_data_filter import SensitiveDataFilter

        flt = SensitiveDataFilter()
        rec = _record("gpg --decrypt passphrase=hunter2 envelope.gpg")
        flt.filter(rec)
        assert "hunter2" not in rec.msg
        assert "<REDACTED:gpg_passphrase>" in rec.msg


# ---------------------------------------------------------------------------
# Idempotence — applying the filter twice produces the same output
# ---------------------------------------------------------------------------


class TestIdempotence:

    def test_filter_idempotent_password(self):
        from observability.sensitive_data_filter import SensitiveDataFilter

        flt = SensitiveDataFilter()
        rec = _record("password=topsecret")
        flt.filter(rec)
        once = rec.msg
        flt.filter(rec)
        assert rec.msg == once, (
            "Filter must be idempotent — re-applying must not double-redact "
            "or alter the marker text"
        )

    def test_redacted_marker_does_not_match_any_pattern(self):
        """The marker `<REDACTED:password>` itself must not match any default
        pattern (would cause infinite double-redaction)."""
        from observability.sensitive_data_filter import (
            SENSITIVE_PATTERNS, _redact,
        )

        marker = "<REDACTED:password>"
        for name, regex in SENSITIVE_PATTERNS.items():
            assert not regex.search(marker), (
                f"Default pattern {name!r} matches the redaction marker — "
                "this will cause runaway double-redaction"
            )
        # Round-trip: redact, redact again, identical
        text = "password=secret"
        once = _redact(text)
        twice = _redact(once)
        assert once == twice


# ---------------------------------------------------------------------------
# Clean text — no false positives
# ---------------------------------------------------------------------------


class TestNoFalsePositives:

    def test_clean_pipeline_message_unchanged(self):
        from observability.sensitive_data_filter import SensitiveDataFilter

        flt = SensitiveDataFilter()
        clean = [
            "Pipeline started for table ACCT",
            "CDC promoted 1234 rows",
            "BCP_LOAD complete in 12.4s",
            "ConnectorX extraction succeeded",
            "User logged in successfully",
        ]
        for msg in clean:
            rec = _record(msg)
            flt.filter(rec)
            assert rec.msg == msg, f"False positive on clean message: {msg!r}"

    def test_word_password_alone_does_not_match(self):
        """The word "password" appearing in prose without an `=` or `:`
        must not match (would mask legitimate documentation strings)."""
        from observability.sensitive_data_filter import SensitiveDataFilter

        flt = SensitiveDataFilter()
        rec = _record("The user changed their password yesterday")
        flt.filter(rec)
        assert rec.msg == "The user changed their password yesterday"


# ---------------------------------------------------------------------------
# Multi-pattern message — all patterns redact in one record
# ---------------------------------------------------------------------------


class TestMultiPattern:

    def test_multiple_secrets_in_one_message(self):
        from observability.sensitive_data_filter import SensitiveDataFilter

        flt = SensitiveDataFilter()
        rec = _record(
            "Connecting with mssql_password=secret1 and passphrase=secret2"
        )
        flt.filter(rec)
        assert "secret1" not in rec.msg
        assert "secret2" not in rec.msg
        assert "<REDACTED:password>" in rec.msg
        assert "<REDACTED:gpg_passphrase>" in rec.msg


# ---------------------------------------------------------------------------
# record.args handling — positional tuple + named dict
# ---------------------------------------------------------------------------


class TestRecordArgs:

    def test_tuple_args_redacted(self):
        from observability.sensitive_data_filter import SensitiveDataFilter

        flt = SensitiveDataFilter()
        rec = _record(
            "User %s connected with password=%s",
            args=("alice", "user_password=topsecret"),
        )
        flt.filter(rec)
        # alice (clean) preserved; the embedded password redacted
        assert rec.args[0] == "alice"
        assert "topsecret" not in rec.args[1]
        assert "<REDACTED:password>" in rec.args[1]

    def test_dict_args_redacted(self):
        from observability.sensitive_data_filter import SensitiveDataFilter

        flt = SensitiveDataFilter()
        rec = _record(
            "%(user)s connected with %(creds)s",
            args={"user": "alice", "creds": "password=foo"},
        )
        flt.filter(rec)
        assert rec.args["user"] == "alice"
        assert "<REDACTED:password>" in rec.args["creds"]
        assert "foo" not in rec.args["creds"]

    def test_none_args_passes_through(self):
        from observability.sensitive_data_filter import SensitiveDataFilter

        flt = SensitiveDataFilter()
        rec = _record("clean text", args=None)
        assert flt.filter(rec) is True

    def test_non_string_args_preserved(self):
        """Int / bool / None args pass through unchanged."""
        from observability.sensitive_data_filter import SensitiveDataFilter

        flt = SensitiveDataFilter()
        rec = _record("row_count=%d active=%s", args=(42, True))
        flt.filter(rec)
        assert rec.args == (42, True)


# ---------------------------------------------------------------------------
# Filter contract — ALWAYS returns True, never drops log lines
# ---------------------------------------------------------------------------


class TestFilterContract:

    def test_always_returns_true(self):
        from observability.sensitive_data_filter import SensitiveDataFilter

        flt = SensitiveDataFilter()
        for msg in ["", "x", "password=foo", "long " * 1000]:
            rec = _record(msg)
            assert flt.filter(rec) is True

    def test_non_string_msg_handled_without_dropping(self):
        """record.msg can be a non-string (e.g. an Exception). Filter must
        not raise; record must still be emittable."""
        from observability.sensitive_data_filter import SensitiveDataFilter

        flt = SensitiveDataFilter()
        rec = _record(ValueError("password=foo"))  # type: ignore[arg-type]
        # No exception, returns True
        assert flt.filter(rec) is True

    def test_filter_failed_marker_on_unexpected_exception(self, monkeypatch):
        """If the regex apply itself blows up, the record passes through
        with `<filter_failed>` appended to record.msg per § 6.1."""
        import observability.sensitive_data_filter as mod

        # Monkeypatch _redact to raise — simulates a bug in the pattern apply.
        def _broken_redact(_text):
            raise RuntimeError("filter exploded")

        monkeypatch.setattr(mod, "_redact", _broken_redact)
        flt = mod.SensitiveDataFilter()
        rec = _record("some message")
        assert flt.filter(rec) is True
        assert "<filter_failed>" in rec.msg, (
            "Per § 6.1 contract: when filtering raises, append <filter_failed> "
            "marker so the operator knows redaction didn't run"
        )


# ---------------------------------------------------------------------------
# register_pii_pattern — runtime pattern registration
# ---------------------------------------------------------------------------


class TestRegisterPiiPattern:

    def test_runtime_pattern_applies(self):
        from observability.sensitive_data_filter import (
            SENSITIVE_PATTERNS,
            SensitiveDataFilter,
            register_pii_pattern,
        )

        try:
            register_pii_pattern("ssn", r"\d{3}-\d{2}-\d{4}")
            flt = SensitiveDataFilter()
            rec = _record("User SSN 123-45-6789")
            flt.filter(rec)
            assert "<REDACTED:ssn>" in rec.msg
            assert "123-45-6789" not in rec.msg
        finally:
            SENSITIVE_PATTERNS.pop("ssn", None)

    def test_invalid_regex_raises_filter_config_error(self):
        from observability.sensitive_data_filter import register_pii_pattern
        from utils.errors import FilterConfigError

        with pytest.raises(FilterConfigError):
            register_pii_pattern("bad", r"(unclosed [group")

    @pytest.mark.parametrize("name", ["", None])
    def test_empty_or_none_name_raises(self, name):
        from observability.sensitive_data_filter import register_pii_pattern
        from utils.errors import FilterConfigError

        with pytest.raises(FilterConfigError):
            register_pii_pattern(name, r"x")  # type: ignore[arg-type]

    def test_non_string_pattern_raises(self):
        from observability.sensitive_data_filter import register_pii_pattern
        from utils.errors import FilterConfigError

        with pytest.raises(FilterConfigError):
            register_pii_pattern("badtype", 12345)  # type: ignore[arg-type]

    def test_overwriting_existing_name_replaces_pattern(self):
        """Re-registering a name OVERWRITES — intentional for per-source
        config reloads."""
        from observability.sensitive_data_filter import (
            SENSITIVE_PATTERNS,
            register_pii_pattern,
        )

        try:
            register_pii_pattern("test_overwrite", r"^old$")
            register_pii_pattern("test_overwrite", r"^new$")
            # Compiled regex should match "new", not "old"
            pat = SENSITIVE_PATTERNS["test_overwrite"]
            assert pat.match("new") is not None
            assert pat.match("old") is None
        finally:
            SENSITIVE_PATTERNS.pop("test_overwrite", None)


# ---------------------------------------------------------------------------
# Module surface
# ---------------------------------------------------------------------------


def test_module_all_surface():
    import observability.sensitive_data_filter as mod

    expected = {"SENSITIVE_PATTERNS", "SensitiveDataFilter", "register_pii_pattern"}
    assert set(mod.__all__) == expected


def test_default_patterns_compile_successfully():
    """Module import succeeds means all default patterns compiled. This
    test pins that the dict has at least the 3 documented defaults."""
    from observability.sensitive_data_filter import SENSITIVE_PATTERNS

    for required in ("password", "rsa_private_key", "gpg_passphrase"):
        assert required in SENSITIVE_PATTERNS, (
            f"Default pattern {required!r} missing — Round 3 § 6.1 spec "
            "lists it as canonical."
        )
