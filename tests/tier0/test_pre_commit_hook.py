"""Tier 0 smoke tests for `.githooks/pre-commit` (bash wrapper per B-310).

Per B-310 cross-platform fix (2026-05-16): pre-commit hook is now a bash
wrapper (not Python script) because Windows git-bash lacks `python3` in
PATH. Bash wrapper detects available Python interpreter then invokes
tools/pre_commit_checks.py orchestrator.

These tests verify bash wrapper structure + interpreter-detection logic +
orchestrator delegation.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOOK_PATH = REPO_ROOT / ".githooks" / "pre-commit"


@pytest.fixture
def hook_content() -> str:
    """Load pre-commit hook content."""
    assert HOOK_PATH.is_file(), f"pre-commit hook not found at {HOOK_PATH}"
    return HOOK_PATH.read_text(encoding="utf-8")


def test_hook_file_exists():
    """Assertion 1: pre-commit hook file exists."""
    assert HOOK_PATH.is_file()


def test_hook_has_sh_shebang(hook_content: str):
    """Assertion 2: hook has /bin/sh shebang for cross-platform bash."""
    first_line = hook_content.split("\n", 1)[0]
    assert first_line.startswith("#!"), "hook must have shebang"
    assert "/sh" in first_line or "/bash" in first_line, (
        "hook shebang must invoke /bin/sh or /bin/bash for cross-platform compat per B-310"
    )


def test_hook_cites_b301_b307_b308_b309_b310(hook_content: str):
    """Assertion 3: hook docstring cites all relevant closures."""
    assert "B-301" in hook_content
    assert "B-307" in hook_content
    assert "B-308" in hook_content
    assert "B-309" in hook_content
    assert "B-310" in hook_content


def test_hook_detects_venv_python(hook_content: str):
    """Assertion 4 (per B-310): hook detects venv Python interpreters cross-platform."""
    assert ".venv/Scripts/python.exe" in hook_content, "must detect Windows venv"
    assert ".venv/bin/python" in hook_content, "must detect Linux/Mac venv"


def test_hook_falls_back_to_python_commands(hook_content: str):
    """Assertion 5 (per B-310): hook falls back to python3 / py / python in PATH."""
    assert "python3" in hook_content
    assert "py -3" in hook_content
    assert "command -v python" in hook_content


def test_hook_delegates_to_orchestrator(hook_content: str):
    """Assertion 6: hook delegates to tools/pre_commit_checks.py orchestrator."""
    assert "pre_commit_checks.py" in hook_content
    assert "ORCHESTRATOR" in hook_content


def test_hook_handles_fatal_exit_code(hook_content: str):
    """Assertion 7 (per B-309 Improvement 2): hook distinguishes FATAL (exit 3) from BLOCKED (exit 1)."""
    assert "EXIT_CODE" in hook_content
    assert '"3"' in hook_content or "= 3" in hook_content
    assert "FATAL" in hook_content


def test_hook_documents_no_verify_bypass(hook_content: str):
    """Assertion 8: hook docstring acknowledges --no-verify bypass + self-flagging."""
    assert "--no-verify" in hook_content
    assert "self-flagging" in hook_content


def test_hook_documents_chicken_and_egg(hook_content: str):
    """Assertion 9: hook docstring acknowledges chicken-and-egg limitation."""
    assert "chicken-and-egg" in hook_content or "own authoring" in hook_content


def test_hook_fail_open_when_no_python(hook_content: str):
    """Assertion 10 (per B-309 + B-310): hook fails open with WARN if no Python found."""
    assert "exit 0" in hook_content
    assert "no Python interpreter found" in hook_content or "WARN" in hook_content


def test_hook_fail_open_when_orchestrator_missing(hook_content: str):
    """Assertion 11: hook fails open with WARN if orchestrator file missing."""
    assert "orchestrator not found" in hook_content
