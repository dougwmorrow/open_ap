"""Tier 0 smoke tests for `.githooks/pre-commit` per D67.

Verifies pre-commit hook (Mechanism C-1 per B-301 closure) is parseable + has
expected structure (shebang, exemption-trigger-phrase list, check functions,
exit-code semantics).

Note: full hook execution test requires git repo state setup (staged files +
commit message); covered at Tier 1 / integration level. This Tier 0 verifies
hook is loadable + has correct surface.
"""
from __future__ import annotations

import re
import subprocess
import sys
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
    """Assertion 1: pre-commit hook file exists at canonical path."""
    assert HOOK_PATH.is_file()


def test_hook_has_python_shebang(hook_content: str):
    """Assertion 2: hook has Python shebang for cross-platform execution."""
    first_line = hook_content.split("\n", 1)[0]
    assert first_line.startswith("#!"), "hook must have shebang"
    assert "python" in first_line.lower(), "hook shebang must invoke python"


def test_hook_cites_b301_b307_b308(hook_content: str):
    """Assertion 3 (per B-308 refactor): hook docstring cites B-301 + B-307 + B-308 closures."""
    assert "B-301" in hook_content
    assert "B-307" in hook_content
    assert "B-308" in hook_content


def test_exemption_trigger_phrases_moved_to_commit_msg(hook_content: str):
    """Assertion 4 (per B-307 split 2026-05-16): exemption-phrase check MOVED
    from pre-commit to commit-msg hook. Pre-commit hook should NOT contain the
    trigger-phrase list anymore; should reference the commit-msg hook split."""
    assert "EXEMPTION_TRIGGER_PHRASES" not in hook_content, (
        "EXEMPTION_TRIGGER_PHRASES should be MOVED to commit-msg hook per B-307 split; "
        "pre-commit hook should not contain the list"
    )
    assert "commit-msg" in hook_content, "pre-commit hook docstring must reference commit-msg companion"
    assert "B-307" in hook_content, "pre-commit hook docstring must cite B-307 split"


def test_hook_delegates_to_orchestrator(hook_content: str):
    """Assertion 5 (per B-308 refactor): hook delegates to tools/pre_commit_checks.py orchestrator
    instead of invoking query_blindspots directly. The orchestrator handles all 4 quality checks."""
    assert "pre_commit_checks.py" in hook_content
    assert "ORCHESTRATOR_PATH" in hook_content


def test_hook_propagates_exit_code(hook_content: str):
    """Assertion 6 (per B-308 refactor): hook returns orchestrator's exit code
    (BLOCK=1 propagates to git's commit-abort path)."""
    assert "result.returncode" in hook_content


def test_hook_check_functions_moved_to_orchestrator(hook_content: str):
    """Assertion 7 (per B-308 refactor): hook no longer contains _check_blindspots OR
    _check_exemption_phrases (both moved: blindspots to orchestrator, exemption to commit-msg)."""
    assert "_check_blindspots" not in hook_content, (
        "_check_blindspots should be in orchestrator per B-308 refactor"
    )
    assert "_check_exemption_phrases" not in hook_content, (
        "_check_exemption_phrases should be in commit-msg hook per B-307 split"
    )


def test_hook_documents_no_verify_bypass(hook_content: str):
    """Assertion 8: hook docstring acknowledges --no-verify bypass + self-flagging semantic."""
    assert "--no-verify" in hook_content
    assert "self-flagging" in hook_content


def test_hook_documents_chicken_and_egg(hook_content: str):
    """Assertion 9: hook docstring acknowledges chicken-and-egg limitation
    (hook cannot enforce on its own authoring commit)."""
    assert "chicken-and-egg" in hook_content or "own authoring" in hook_content


def test_hook_invocation_smoke(hook_content: str):
    """Assertion 10: hook script is syntactically valid Python (parses)."""
    try:
        compile(hook_content, str(HOOK_PATH), "exec")
    except SyntaxError as e:
        pytest.fail(f"hook script has syntax error: {e}")


def test_hook_main_function_defined(hook_content: str):
    """Assertion 11: hook script defines main() function with int return contract."""
    main_def_re = re.compile(r"^def main\(\)\s*->\s*int\s*:", re.MULTILINE)
    assert main_def_re.search(hook_content), "hook must define `def main() -> int:`"
    assert "if __name__ == \"__main__\":" in hook_content, "hook must have __main__ guard"
    assert "sys.exit(main())" in hook_content, "hook must invoke sys.exit(main())"
