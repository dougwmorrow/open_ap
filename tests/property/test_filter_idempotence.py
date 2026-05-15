"""Tier 2 SensitiveDataFilter idempotence property tests per § 5.7.

Canonical reference (Step 11 verbatim — DELTA-B2 elevation 2026-05-14):
  docs/migration/phase1/05_tests.md § 5.7 "SensitiveDataFilter idempotence
  (per § 6.1 module spec)":
    ```python
    @given(log_message=st.text())
    def test_sensitive_data_filter_idempotent(log_message):
        \"\"\"filter(filter(msg)) == filter(msg) — no double-redaction artifacts.\"\"\"
        once = sensitive_data_filter.apply(log_message)
        twice = sensitive_data_filter.apply(once)
        assert once == twice
    ```

M14 API surface (read via ``git show HEAD:observability/sensitive_data_filter.py``):
  - ``SensitiveDataFilter(logging.Filter)`` — primary public class; mutates
    record.msg in place via ``filter(record) -> bool`` (always True).
  - ``_redact(text: str) -> str`` — module-level pure helper; idempotence
    contract documented in its docstring: "re-running on an already-
    redacted string produces the same output (the marker text does NOT
    match any default pattern)".
  - ``register_pii_pattern(name, pattern, *, flags=0)`` — runtime pattern
    addition (mutates module-level SENSITIVE_PATTERNS dict).

This test exercises ``_redact`` directly (the pure helper used by
``SensitiveDataFilter.filter``) per the § 5.7 spec contract. The class-
based path (with LogRecord wrapping) is exercised by the existing Tier 0
smoke test ``tests/tier0/test_sensitive_data_filter.py``.

D-numbers: P5 (no plaintext PII in logs), D67 (Tier 0 smoke discipline does
not apply here — Tier 2 may take longer per § 5.10), D81 (property-test
budget), D92 (forward-only additive).
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


# ---------------------------------------------------------------------------
# § 5.7 — _redact idempotence on arbitrary text
# ---------------------------------------------------------------------------


@given(log_message=st.text(min_size=0, max_size=1000))
def test_redact_idempotent_on_arbitrary_text(log_message: str) -> None:
    """``_redact(_redact(msg)) == _redact(msg)`` for arbitrary log message text.

    Per § 6.1 docstring: "re-running on an already-redacted string produces
    the same output (the marker text ``<REDACTED:{name}>`` does NOT match
    any default pattern)".
    """
    from observability.sensitive_data_filter import _redact

    once = _redact(log_message)
    twice = _redact(once)

    assert once == twice, (
        f"_redact is not idempotent. once={once!r} twice={twice!r}"
    )


# ---------------------------------------------------------------------------
# § 5.7 — Targeted edge case: password/passphrase/PEM patterns
# ---------------------------------------------------------------------------


@given(
    secret_prefix=st.sampled_from([
        "password", "user_password", "MSSQL_PASSWORD",
        "passphrase", "GPG_PASSPHRASE",
    ]),
    sep=st.sampled_from(["=", ": "]),
    secret_value=st.text(
        alphabet=st.characters(blacklist_characters=" \t\n\r"),
        min_size=1, max_size=30,
    ),
    surrounding_text=st.text(min_size=0, max_size=50),
)
def test_redact_idempotent_with_password_patterns(
    secret_prefix: str,
    sep: str,
    secret_value: str,
    surrounding_text: str,
) -> None:
    """Same idempotence guarantee specifically for messages that DO contain
    redacted patterns — the first pass redacts, the second pass finds the
    ``<REDACTED:...>`` marker and leaves it alone.
    """
    from observability.sensitive_data_filter import _redact

    msg = f"{surrounding_text} {secret_prefix}{sep}{secret_value} done"

    once = _redact(msg)
    twice = _redact(once)

    assert once == twice, (
        f"_redact not idempotent on password-pattern msg. "
        f"once={once!r} twice={twice!r}"
    )


# ---------------------------------------------------------------------------
# § 5.7 — Class-level idempotence via SensitiveDataFilter.filter
# ---------------------------------------------------------------------------


def _make_record(msg: str) -> logging.LogRecord:
    """Build a stand-in LogRecord — pattern matches the existing Tier 0 smoke
    test in tests/tier0/test_sensitive_data_filter.py (consistency with the
    M14 test style)."""
    return logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=None,
        exc_info=None,
    )


@given(log_message=st.text(min_size=0, max_size=500))
@settings(max_examples=200)  # § 5.10 default budget; class path is heavier
def test_filter_class_idempotent_via_logrecord(log_message: str) -> None:
    """``SensitiveDataFilter().filter(record)`` is idempotent — applying the
    filter twice to the same record produces the same final ``record.msg``.

    Per M14 contract: filter MUTATES record.msg in place. We pass the same
    msg through two fresh records (one filter pass each) and compare —
    semantically equivalent to applying the filter twice to one record.
    """
    from observability.sensitive_data_filter import SensitiveDataFilter

    flt = SensitiveDataFilter()

    r1 = _make_record(log_message)
    assert flt.filter(r1) is True
    once_msg = r1.msg

    r2 = _make_record(once_msg)
    assert flt.filter(r2) is True
    twice_msg = r2.msg

    assert once_msg == twice_msg, (
        f"SensitiveDataFilter.filter is not idempotent. "
        f"once={once_msg!r} twice={twice_msg!r}"
    )
