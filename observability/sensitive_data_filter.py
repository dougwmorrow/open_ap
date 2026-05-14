"""Sensitive-data redaction filter per Round 3 § 6.1 + P5 + D6.

A ``logging.Filter`` subclass that redacts plaintext from log records BEFORE
they hit any sink. Installed on every handler at process start by
``log_handler`` (Round 3 § 6.2) so P5 (no plaintext PII anywhere in logs)
is enforced universally.

Default patterns
================

- ``password`` — anything of the form ``*_password = <value>`` (case-insensitive)
- ``rsa_private_key`` — full PEM-formatted private key blocks (multiline)
- ``gpg_passphrase`` — anything of the form ``passphrase = <value>``

Per-source PII patterns (SSN, account number, etc.) are added at runtime via
:func:`register_pii_pattern` by ``pii_tokenizer`` after reading
``UdmTablesList.PiiColumnList`` per D63.

Filter contract
===============

- Mutates ``record.msg`` and each ``record.args`` element in place.
- **Always returns True** — never drops a log line. Redaction, not suppression.
- On regex / unexpected exception during filtering, the record passes
  through with a synthetic ``<filter_failed>`` marker appended to
  ``record.msg``. This contract is per § 6.1 — losing a log line because
  the filter blew up is worse than emitting an unredacted log line, but
  emitting *something* is better than silence.
- Pattern compilation happens at module import (or via
  :func:`register_pii_pattern`). Compilation failure raises
  :class:`FilterConfigError` per D68 — module import fails so the operator
  sees the bad pattern before any log line writes.

Performance
===========

O(P × M) per record where P = pattern count and M = message length. Patterns
are compiled once and stored as read-only ``re.Pattern`` objects; per-record
cost is ~50 µs for the default pattern set. The filter is thread-safe — no
shared mutable state after import + any ``register_pii_pattern`` calls in
the single-threaded startup phase.

D-numbers consumed
==================

- P5 — no plaintext PII in logs
- D6 — PII tokenization (this filter complements the SP-based tokenizer)
- D67 — Tier 0 smoke discipline
- D68 — :class:`FilterConfigError` ⊂ PipelineFatalError
- D69 — stateless / thread-safe per process

B-numbers
=========

- Closes the M14 dependency referenced by every Round 3 / Round 4 module
  that installs a logging handler.
"""

from __future__ import annotations

import logging
import re
from typing import Pattern

from utils.errors import FilterConfigError

__all__ = [
    "SENSITIVE_PATTERNS",
    "SensitiveDataFilter",
    "register_pii_pattern",
]

# Marker appended to record.msg when the filter itself raises an unexpected
# exception. Per § 6.1: never drop the log line — emit it with a marker so
# the operator knows redaction failed (still safer than silence).
_FILTER_FAILED_MARKER = " <filter_failed>"


def _compile(pattern: str, *, flags: int = 0) -> Pattern[str]:
    """Compile a regex pattern, wrapping failures in FilterConfigError.

    Per D68: ``FilterConfigError`` ⊂ ``PipelineFatalError``. A bad pattern
    is a fatal config issue surfacing at module import — the operator
    must fix the pattern before the pipeline can start.
    """
    try:
        return re.compile(pattern, flags=flags)
    except re.error as exc:
        raise FilterConfigError(
            f"Failed to compile regex pattern: {exc!r}. "
            f"Pattern source: {pattern!r}",
            metadata={"pattern_source": pattern, "regex_error": str(exc)},
        ) from exc


# Default patterns — compiled at module import per D67 Tier 0 contract.
# All matches are replaced with f"<REDACTED:{name}>" where name is the dict
# key. Add new defaults here (not at runtime) so module import surfaces
# pattern errors immediately. Per-source PII patterns go through
# register_pii_pattern() instead.
#
# DELIBERATE BROADER-THAN-SPEC DIVERGENCE (recorded post-gap-check 2026-05-13):
# The ``password`` pattern below uses ``[\w_]*password`` (no required leading
# ``_``); spec § 6.1 wrote ``[\w_]*_password`` which would miss bare
# ``Password=foo`` / ``password = bar``. Broader impl catches both prefixed
# (``MSSQL_PASSWORD``, ``user_password``) and bare forms, providing
# defense-in-depth on P5. Functionally a superset of the spec — no plaintext
# the spec would have caught can now leak; some plaintext the spec MISSED is
# now also redacted. Tests pin the broader behavior.
SENSITIVE_PATTERNS: dict[str, Pattern[str]] = {
    "password": _compile(
        r"(?i)([\w_]*password)\s*[=:]\s*\S+",
    ),
    "rsa_private_key": _compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        flags=re.DOTALL,
    ),
    "gpg_passphrase": _compile(
        r"(?i)passphrase\s*[=:]\s*\S+",
    ),
}


def register_pii_pattern(name: str, pattern: str, *, flags: int = 0) -> None:
    """Register a per-source PII pattern at runtime.

    Called by ``pii_tokenizer`` at process start after reading
    ``UdmTablesList.PiiColumnList`` per D63. The named pattern is added
    to :data:`SENSITIVE_PATTERNS` and applied by every subsequent filter
    invocation.

    :param name: pattern label used in the redaction marker — the match
        is replaced with ``<REDACTED:{name}>``. Must be unique; re-using
        an existing name OVERWRITES the prior pattern (intentional —
        per-source config reloads should override defaults).
    :param pattern: regex source. Compiled immediately; failure raises
        :class:`FilterConfigError`.
    :param flags: optional ``re`` flag bitmask. Defaults to 0.

    :raises FilterConfigError: pattern fails to compile.
    """
    if not name or not isinstance(name, str):
        raise FilterConfigError(
            f"register_pii_pattern: name must be a non-empty string "
            f"(received {name!r})",
        )
    if not isinstance(pattern, str):
        raise FilterConfigError(
            f"register_pii_pattern: pattern must be a string (received "
            f"{type(pattern).__name__})",
            metadata={"name": name},
        )
    SENSITIVE_PATTERNS[name] = _compile(pattern, flags=flags)


def _redact(text: str) -> str:
    """Apply all SENSITIVE_PATTERNS to text and return the redacted result.

    Each match is replaced with ``<REDACTED:{name}>``. The function is
    pure (no side effects) and idempotent — re-running on an already-
    redacted string produces the same output (the marker text does NOT
    match any default pattern).
    """
    for name, regex in SENSITIVE_PATTERNS.items():
        text = regex.sub(f"<REDACTED:{name}>", text)
    return text


def _redact_value(value: object) -> object:
    """Redact a single record-args value.

    Strings are run through :func:`_redact`. Non-strings pass through
    unchanged — formatting them via ``%`` will stringify them later, and
    we trust that the stringified form of an int / bool / None contains
    no secrets. Mapping types (dict / etc.) used as % args are deep-walked
    so per-value strings get redacted while structure is preserved.
    """
    if isinstance(value, str):
        return _redact(value)
    if isinstance(value, dict):
        return {k: _redact_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        redacted = [_redact_value(v) for v in value]
        return type(value)(redacted) if isinstance(value, tuple) else redacted
    return value


class SensitiveDataFilter(logging.Filter):
    """Redact plaintext from log records per P5.

    Apply all :data:`SENSITIVE_PATTERNS` (defaults + any registered via
    :func:`register_pii_pattern`) to ``record.msg`` and each
    ``record.args`` item. Mutates the record in place.

    **Contract**:

    - Returns ``True`` always — never drops a log line.
    - Exceptions during filtering are caught; the record passes through
      with ``" <filter_failed>"`` appended to ``record.msg`` so the
      operator knows redaction did not run on this line.

    Concurrency: thread-safe — patterns are read-only after import. The
    only mutation point is :func:`register_pii_pattern`, called during
    process startup before threads spawn.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003 — stdlib API
        try:
            # record.msg can be non-string (e.g. an Exception or arbitrary
            # object). _redact_value preserves non-string identity.
            if isinstance(record.msg, str):
                record.msg = _redact(record.msg)
            # record.args is either a tuple of positional values OR a dict
            # of named values (for %(name)s formatting) OR None.
            if record.args:
                if isinstance(record.args, tuple):
                    record.args = tuple(_redact_value(a) for a in record.args)
                elif isinstance(record.args, dict):
                    record.args = {
                        k: _redact_value(v) for k, v in record.args.items()
                    }
                # Any other shape (rare; some libs use lists) — pass through.
        except BaseException:  # noqa: BLE001 — never drop a log line
            # Append failure marker to whatever's in record.msg. If msg is
            # not a string (e.g. an Exception instance), coerce to str so
            # the marker is appendable.
            try:
                record.msg = (
                    record.msg if isinstance(record.msg, str)
                    else str(record.msg)
                ) + _FILTER_FAILED_MARKER
            except BaseException:
                # If even str() raises, leave record.msg alone — the line
                # will still emit (returning True below).
                pass
        return True
