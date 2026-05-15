"""Tier 0 smoke test for observability/sensitive_data_filter.py per D67 + § 6.1.

<5 s runtime, pure / no external deps.

Per § 6.1 D67 Tier 0 contract:
  (a) module imports
  (b) filter applied to a record with `password=foo` redacts to `<REDACTED:password>`
  (c) filter applied to a clean record passes through unchanged
  (d) `register_pii_pattern` adds a runtime pattern

D-numbers: D67 (Tier 0), D68 (FilterConfigError), P5 (no plaintext).
B-numbers: M14 (sensitive_data_filter build close).
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def _make_record(msg: str, *args) -> logging.LogRecord:
    """Build a stand-in LogRecord for filter unit tests."""
    return logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=args if args else None,
        exc_info=None,
    )


def test_module_imports():
    """(a) module imports without error per D67."""
    import observability.sensitive_data_filter as mod

    assert mod is not None
    assert hasattr(mod, "SensitiveDataFilter")
    assert hasattr(mod, "register_pii_pattern")
    assert hasattr(mod, "SENSITIVE_PATTERNS")


def test_password_pattern_redacted():
    """(b) record with `password=secret` redacts to `<REDACTED:password>`."""
    from observability.sensitive_data_filter import SensitiveDataFilter

    flt = SensitiveDataFilter()
    record = _make_record("user_password=hunter2 connecting...")
    assert flt.filter(record) is True
    assert "hunter2" not in record.msg, "plaintext password must be redacted"
    assert "<REDACTED:password>" in record.msg


def test_clean_record_passes_through():
    """(c) clean record (no sensitive content) unchanged."""
    from observability.sensitive_data_filter import SensitiveDataFilter

    flt = SensitiveDataFilter()
    record = _make_record("Pipeline started for table ACCT")
    assert flt.filter(record) is True
    assert record.msg == "Pipeline started for table ACCT"


def test_register_pii_pattern_adds_runtime_pattern():
    """(d) register_pii_pattern adds a runtime pattern that subsequent
    filter calls apply."""
    from observability.sensitive_data_filter import (
        SENSITIVE_PATTERNS,
        SensitiveDataFilter,
        register_pii_pattern,
    )

    # Cleanup the test pattern so we don't pollute other tests.
    test_name = "smoke_ssn_test"
    try:
        register_pii_pattern(test_name, r"\d{3}-\d{2}-\d{4}")
        assert test_name in SENSITIVE_PATTERNS

        flt = SensitiveDataFilter()
        record = _make_record("User SSN: 123-45-6789 reported")
        flt.filter(record)
        assert "123-45-6789" not in record.msg
        assert f"<REDACTED:{test_name}>" in record.msg
    finally:
        SENSITIVE_PATTERNS.pop(test_name, None)


def test_filter_always_returns_true_even_on_exception():
    """Filter NEVER drops a log line. Even pathological input passes through."""
    from observability.sensitive_data_filter import SensitiveDataFilter

    flt = SensitiveDataFilter()
    # Pathological msg: an Exception instance (non-string)
    record = _make_record(ValueError("oops with password=foo embedded"))  # type: ignore[arg-type]
    assert flt.filter(record) is True  # never drop


def test_bad_pattern_raises_filter_config_error():
    """register_pii_pattern with an invalid regex raises FilterConfigError."""
    from observability.sensitive_data_filter import register_pii_pattern
    from utils.errors import FilterConfigError, PipelineFatalError

    with pytest.raises(FilterConfigError) as exc_info:
        register_pii_pattern("bad", r"(unclosed [group")

    # FilterConfigError must inherit from PipelineFatalError per D68 → exit code 2 per D74
    assert isinstance(exc_info.value, PipelineFatalError)
