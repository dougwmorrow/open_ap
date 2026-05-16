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


def test_hook_cites_b301_and_instance_8_and_9(hook_content: str):
    """Assertion 3: hook docstring cites B-301 + Pitfall #9.o instance 8 + 9 evidence."""
    assert "B-301" in hook_content
    assert "INSTANCE 8" in hook_content or "instance 8" in hook_content
    assert "bd9210c" in hook_content
    assert "INSTANCE 9" in hook_content or "instance 9" in hook_content
    assert "f8a6ae1" in hook_content


def test_exemption_trigger_phrases_list_present(hook_content: str):
    """Assertion 4: hook has exemption-trigger-phrase list with 12+ entries."""
    assert "EXEMPTION_TRIGGER_PHRASES" in hook_content
    expected_phrases = [
        # Original 8 from SKILL.md
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


def test_hook_runs_query_blindspots(hook_content: str):
    """Assertion 5: hook invokes tools/query_blindspots.py for staged-file scan."""
    assert "query_blindspots.py" in hook_content
    assert "--severity" in hook_content
    assert "p0,p1" in hook_content


def test_hook_uses_live_mode(hook_content: str):
    """Assertion 6: hook uses --live mode for D74 exit-code-2 blocking semantic."""
    assert "--live" in hook_content


def test_hook_check_functions_present(hook_content: str):
    """Assertion 7: hook has 2 check functions per design."""
    assert "_check_blindspots" in hook_content
    assert "_check_exemption_phrases" in hook_content


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
