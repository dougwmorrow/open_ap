"""Tier 0 smoke tests for `.githooks/commit-msg` per D67 + B-307 closure.

Verifies commit-msg hook (Mechanism C-1 exemption-phrase check; split from
pre-commit hook per B-307 closure to cover `git commit -m` direct-message
commits which the pre-commit hook missed due to COMMIT_EDITMSG not being
populated at pre-commit hook execution time).
"""
from __future__ import annotations

import re
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
    """Assertion 1: commit-msg hook file exists at canonical path."""
    assert HOOK_PATH.is_file()


def test_hook_has_python_shebang(hook_content: str):
    """Assertion 2: hook has Python shebang for cross-platform execution."""
    first_line = hook_content.split("\n", 1)[0]
    assert first_line.startswith("#!"), "hook must have shebang"
    assert "python" in first_line.lower(), "hook shebang must invoke python"


def test_hook_cites_b307_split(hook_content: str):
    """Assertion 3: hook docstring cites B-307 closure + pre-commit split rationale."""
    assert "B-307" in hook_content
    assert "COMMIT_EDITMSG" in hook_content
    assert "git commit -m" in hook_content


def test_exemption_trigger_phrases_list_present(hook_content: str):
    """Assertion 4: hook has all 12 exemption-trigger phrases (8 verbatim + 4 B-303)."""
    assert "EXEMPTION_TRIGGER_PHRASES" in hook_content
    expected_phrases = [
        # Original 8 from SKILL.md L29-36
        "Layer N+1 termination",
        "recursive-exemption",
        "verbatim implementation",
        "100% overlap on architectural-decision-substance",
        "specific scope-justified exemption",
        "REVIEW: SKIPPED",
        "no new architecture introduced",
        "implementing prior reviewer's recommendation",
        # B-303 structured-pattern extensions
        "EXEMPTION VALID",
        "step 6: N/A",
        "cannot fire on commits modifying its own SKILL.md",
        "self-exemption clause applies",
    ]
    for phrase in expected_phrases:
        assert phrase in hook_content, f"expected trigger phrase missing: {phrase}"


def test_hook_accepts_commit_msg_path_argv(hook_content: str):
    """Assertion 5: hook main(argv) signature accepts COMMIT_EDITMSG path as $1."""
    main_def_re = re.compile(r"^def main\(argv:\s*list\[str\]\)\s*->\s*int\s*:", re.MULTILINE)
    assert main_def_re.search(hook_content), (
        "hook must define `def main(argv: list[str]) -> int:` per git commit-msg "
        "hook contract (receives COMMIT_EDITMSG path as $1)"
    )


def test_hook_strips_git_comment_lines(hook_content: str):
    """Assertion 6: hook strips git-comment lines (#-prefixed)."""
    assert "lstrip().startswith(\"#\")" in hook_content


def test_hook_returns_int(hook_content: str):
    """Assertion 7: main returns int (exit code 0 or 1)."""
    assert "return 0" in hook_content
    assert "return 1" in hook_content


def test_hook_main_guard(hook_content: str):
    """Assertion 8: hook has __main__ guard."""
    assert "if __name__ == \"__main__\":" in hook_content
    assert "sys.exit(main(sys.argv))" in hook_content


def test_hook_documents_no_verify_bypass(hook_content: str):
    """Assertion 9: hook docstring acknowledges --no-verify bypass + self-flagging."""
    assert "--no-verify" in hook_content
    assert "self-flagging" in hook_content


def test_hook_documents_chicken_and_egg(hook_content: str):
    """Assertion 10: hook docstring acknowledges chicken-and-egg limitation."""
    assert "chicken-and-egg" in hook_content or "own authoring" in hook_content


def test_hook_syntactically_valid(hook_content: str):
    """Assertion 11: hook script is syntactically valid Python."""
    try:
        compile(hook_content, str(HOOK_PATH), "exec")
    except SyntaxError as e:
        pytest.fail(f"commit-msg hook has syntax error: {e}")
