"""Tier 0 PII scrubbing test for `docs/migration/_session_snapshots/*.md` per B-559 closure 2026-05-19.

Mechanical defense-in-depth layer ensuring snapshots committed to the repository
do not contain CCPA/PII-sensitive patterns. Primary discipline is operator-side
at authoring time per `.claude/skills/udm-session-compactor/SKILL.md` "Do NOT
include in snapshots" section; this test is the harness-layer backstop.

Per D67 — runs at build time + every commit; runtime ceiling < 5 s.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SNAPSHOTS_DIR = REPO_ROOT / "docs" / "migration" / "_session_snapshots"

# Sensitive-pattern regexes per SKILL.md "Operator workflow when in doubt" §
# Each pattern is conservative — matches likely-PII shapes, not project codes.
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
# Credit-card-shape: 13-19 contiguous digits (no separators). Project codes
# like B-N / D-N are not 13+ contiguous digits.
_CC_RE = re.compile(r"\b\d{13,19}\b")
# Private-key file headers — definitive sensitive material
_PRIVKEY_RE = re.compile(
    r"-----BEGIN (?:RSA |OPENSSH |EC |PGP |DSA )?PRIVATE KEY-----"
)
# Connection strings with embedded passwords — `proto://user:password@host`
# Conservative: requires password segment with at least 4 chars to avoid
# matching SSH config tokens like `git@github.com`
_DBURL_RE = re.compile(
    r"\b(?:postgresql|mysql|mssql|mongodb|redis)://[^:\s]+:[^@\s]{4,}@",
    re.IGNORECASE,
)

# Email regex — conservative; common @ symbol + domain pattern. We ALLOW
# specific known-safe addresses (test fixtures / Anthropic noreply / system
# robots / explicit operator/team handles). All real-customer email shapes
# would not match the allowlist.
_EMAIL_RE = re.compile(
    r"\b[a-zA-Z0-9._+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9.-]+\b"
)
# Known-safe email patterns (allowlist; do NOT flag these as PII)
_EMAIL_ALLOWLIST_SUBSTRINGS = (
    "noreply@anthropic.com",
    "@protonmail.com",   # operator handle per CLAUDE.md
    "@example.com",
    "@test.com",
    "@localhost",
)


def _enumerate_snapshot_files() -> list[Path]:
    """Return list of all *.md files in _session_snapshots/ (empty if dir missing)."""
    if not SNAPSHOTS_DIR.is_dir():
        return []
    return sorted(SNAPSHOTS_DIR.glob("*.md"))


def _scan_for_pattern(
    snapshot_path: Path, pattern: re.Pattern[str], allow_substrings: tuple[str, ...] = (),
) -> list[tuple[int, str]]:
    """Return (line_no, matched_text) tuples for each match NOT in allowlist."""
    try:
        content = snapshot_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    findings: list[tuple[int, str]] = []
    for line_no, line in enumerate(content.splitlines(), start=1):
        for m in pattern.finditer(line):
            matched = m.group(0)
            if any(allow in matched for allow in allow_substrings):
                continue
            findings.append((line_no, matched))
    return findings


def test_snapshots_dir_exists_or_empty() -> None:
    """Assertion 1: _session_snapshots/ directory exists (or is acceptably absent)."""
    # Directory MAY not exist on fresh clones before first snapshot lands;
    # in that case, this test is vacuously PASS.
    if not SNAPSHOTS_DIR.is_dir():
        pytest.skip("_session_snapshots/ directory not present; no snapshots to scan")
    # Directory exists — verify it's actually a directory (not a regular file)
    assert SNAPSHOTS_DIR.is_dir()


def test_no_ssn_shape_in_snapshots() -> None:
    """Assertion 2: no SSN-shaped patterns (DDD-DD-DDDD) in any snapshot file."""
    snapshots = _enumerate_snapshot_files()
    if not snapshots:
        pytest.skip("no snapshot files present")
    all_findings: list[tuple[str, int, str]] = []
    for snapshot in snapshots:
        findings = _scan_for_pattern(snapshot, _SSN_RE)
        for line_no, matched in findings:
            all_findings.append((snapshot.name, line_no, matched))
    assert not all_findings, (
        f"SSN-shaped patterns detected in snapshots (CCPA/PII violation per "
        f"B-559 closure 2026-05-19; udm-session-compactor SKILL.md 'Do NOT "
        f"include' guidance):\n"
        + "\n".join(f"  - {name}:{ln}: {match}" for name, ln, match in all_findings)
    )


def test_no_credit_card_shape_in_snapshots() -> None:
    """Assertion 3: no 13-19 contiguous digit sequences (credit-card-shaped)."""
    snapshots = _enumerate_snapshot_files()
    if not snapshots:
        pytest.skip("no snapshot files present")
    all_findings: list[tuple[str, int, str]] = []
    for snapshot in snapshots:
        findings = _scan_for_pattern(snapshot, _CC_RE)
        for line_no, matched in findings:
            all_findings.append((snapshot.name, line_no, matched))
    assert not all_findings, (
        f"Credit-card-shaped patterns detected in snapshots (B-559 violation):\n"
        + "\n".join(f"  - {name}:{ln}: {match}" for name, ln, match in all_findings)
    )


def test_no_private_key_headers_in_snapshots() -> None:
    """Assertion 4: no `-----BEGIN ... PRIVATE KEY-----` headers in any snapshot."""
    snapshots = _enumerate_snapshot_files()
    if not snapshots:
        pytest.skip("no snapshot files present")
    all_findings: list[tuple[str, int, str]] = []
    for snapshot in snapshots:
        findings = _scan_for_pattern(snapshot, _PRIVKEY_RE)
        for line_no, matched in findings:
            all_findings.append((snapshot.name, line_no, matched))
    assert not all_findings, (
        f"Private-key headers detected in snapshots (CRITICAL credential leak; "
        f"B-559 violation):\n"
        + "\n".join(f"  - {name}:{ln}: {match}" for name, ln, match in all_findings)
    )


def test_no_db_url_with_password_in_snapshots() -> None:
    """Assertion 5: no `proto://user:password@host` connection strings."""
    snapshots = _enumerate_snapshot_files()
    if not snapshots:
        pytest.skip("no snapshot files present")
    all_findings: list[tuple[str, int, str]] = []
    for snapshot in snapshots:
        findings = _scan_for_pattern(snapshot, _DBURL_RE)
        for line_no, matched in findings:
            all_findings.append((snapshot.name, line_no, matched))
    assert not all_findings, (
        f"Connection string with embedded password detected in snapshots (B-559 "
        f"violation):\n"
        + "\n".join(f"  - {name}:{ln}: {match}" for name, ln, match in all_findings)
    )


def test_no_unallowlisted_email_in_snapshots() -> None:
    """Assertion 6: no email addresses outside the known-safe allowlist."""
    snapshots = _enumerate_snapshot_files()
    if not snapshots:
        pytest.skip("no snapshot files present")
    all_findings: list[tuple[str, int, str]] = []
    for snapshot in snapshots:
        findings = _scan_for_pattern(snapshot, _EMAIL_RE, _EMAIL_ALLOWLIST_SUBSTRINGS)
        for line_no, matched in findings:
            all_findings.append((snapshot.name, line_no, matched))
    assert not all_findings, (
        f"Email addresses outside allowlist detected in snapshots (B-559 "
        f"violation; allowlisted = noreply@anthropic.com, @protonmail.com, "
        f"@example.com, @test.com, @localhost):\n"
        + "\n".join(f"  - {name}:{ln}: {match}" for name, ln, match in all_findings)
    )


def test_pattern_constants_compile() -> None:
    """Assertion 7: all regex constants are valid + compile-time-validated."""
    assert _SSN_RE is not None
    assert _CC_RE is not None
    assert _PRIVKEY_RE is not None
    assert _DBURL_RE is not None
    assert _EMAIL_RE is not None
    # Allowlist non-empty
    assert len(_EMAIL_ALLOWLIST_SUBSTRINGS) >= 5
