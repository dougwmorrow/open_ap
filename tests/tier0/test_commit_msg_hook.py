"""Tier 0 smoke tests for `.githooks/commit-msg` (bash wrapper per B-310).

Per B-310 cross-platform fix (2026-05-16): commit-msg hook is now a bash
wrapper (not Python script). Bash detects Python interpreter then invokes
tools/check_commit_msg.py with COMMIT_EDITMSG path as $1.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOOK_PATH = REPO_ROOT / ".githooks" / "commit-msg"


@pytest.fixture
def hook_content() -> str:
    """Load commit-msg hook content."""
    assert HOOK_PATH.is_file(), f"commit-msg hook not found at {HOOK_PATH}"
    return HOOK_PATH.read_text(encoding="utf-8")


def test_hook_file_exists():
    """Assertion 1: commit-msg hook file exists."""
    assert HOOK_PATH.is_file()


def test_hook_has_sh_shebang(hook_content: str):
    """Assertion 2: hook has /bin/sh shebang."""
    first_line = hook_content.split("\n", 1)[0]
    assert first_line.startswith("#!"), "hook must have shebang"
    assert "/sh" in first_line or "/bash" in first_line


def test_hook_cites_b307_b310(hook_content: str):
    """Assertion 3: hook docstring cites B-307 split + B-310 cross-platform fix."""
    assert "B-307" in hook_content
    assert "B-310" in hook_content
    assert "COMMIT_EDITMSG" in hook_content
    assert "git commit -m" in hook_content


def test_hook_detects_venv_python(hook_content: str):
    """Assertion 4 (per B-310): hook detects venv Python cross-platform."""
    assert ".venv/Scripts/python.exe" in hook_content
    assert ".venv/bin/python" in hook_content


def test_hook_falls_back_to_python_commands(hook_content: str):
    """Assertion 5 (per B-310): hook falls back to python3 / py / python in PATH."""
    assert "python3" in hook_content
    assert "py -3" in hook_content


def test_hook_delegates_to_checker(hook_content: str):
    """Assertion 6: hook delegates to tools/check_commit_msg.py."""
    assert "check_commit_msg.py" in hook_content
    assert "CHECKER" in hook_content


def test_hook_passes_argv_dollar_1(hook_content: str):
    """Assertion 7: hook passes $1 (COMMIT_EDITMSG path) to checker."""
    assert '"$1"' in hook_content, (
        "hook must pass $1 (COMMIT_EDITMSG path per git contract) to Python checker"
    )


def test_hook_documents_no_verify_bypass(hook_content: str):
    """Assertion 8: hook docstring acknowledges --no-verify bypass + self-flagging."""
    assert "--no-verify" in hook_content
    assert "self-flagging" in hook_content


def test_hook_fail_open_when_no_python(hook_content: str):
    """Assertion 9: hook fails open if no Python found."""
    assert "exit 0" in hook_content
    assert "no Python interpreter found" in hook_content or "WARN" in hook_content


def test_hook_fail_open_when_checker_missing(hook_content: str):
    """Assertion 10: hook fails open if checker file missing."""
    assert "checker not found" in hook_content
