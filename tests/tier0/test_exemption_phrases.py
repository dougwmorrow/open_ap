"""Tier 0 test: verify EXEMPTION_TRIGGER_PHRASES Python constant stays in sync
with SKILL.md trigger-phrase enumeration per B-309 dedupe closure.

Detects 4-way drift surface (SKILL.md / Python module / commit-msg hook / tests)
by enforcing single-source-of-truth: tools/exemption_phrases.py is authoritative
for Python; SKILL.md L29-46 is authoritative for documentation. They must agree.

If this test fails, the producer must update BOTH SKILL.md AND
tools/exemption_phrases.py with the same set of phrases.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))

SKILL_PATH = REPO_ROOT / ".claude" / "skills" / "udm-exemption-verifier" / "SKILL.md"


def _extract_phrases_from_skill_md() -> set[str]:
    """Parse SKILL.md to extract bullet-list trigger phrases between the
    'Pre-commit' enumeration heading and the next subsection.

    Returns set of phrases (stripped + quotes removed).
    """
    content = SKILL_PATH.read_text(encoding="utf-8")
    in_section = False
    phrases = set()
    for line in content.splitlines():
        stripped = line.strip()
        if "MANDATORY triggers" in line or "**MANDATORY triggers**" in line:
            in_section = True
            continue
        if in_section and stripped.startswith("###"):
            break
        if in_section and stripped.startswith("- ") and '"' in stripped:
            start = stripped.find('"')
            end = stripped.find('"', start + 1)
            if start != -1 and end != -1:
                phrases.add(stripped[start + 1:end])
    return phrases


def test_exemption_phrases_python_module_imports():
    """Assertion 1: canonical Python module imports cleanly."""
    import tools.exemption_phrases  # noqa: F401


def test_exemption_trigger_phrases_constant_present():
    """Assertion 2: EXEMPTION_TRIGGER_PHRASES tuple has 12 entries."""
    from tools.exemption_phrases import EXEMPTION_TRIGGER_PHRASES
    assert isinstance(EXEMPTION_TRIGGER_PHRASES, tuple), "must be tuple (immutable)"
    assert len(EXEMPTION_TRIGGER_PHRASES) == 12, (
        f"expected 12 trigger phrases; got {len(EXEMPTION_TRIGGER_PHRASES)}"
    )


def test_contains_exemption_phrase_function():
    """Assertion 3: contains_exemption_phrase() returns list of matches."""
    from tools.exemption_phrases import contains_exemption_phrase
    assert contains_exemption_phrase("") == []
    assert contains_exemption_phrase("normal commit") == []
    result = contains_exemption_phrase("contains Layer N+1 termination here")
    assert "Layer N+1 termination" in result
    result_case = contains_exemption_phrase("LAYER N+1 TERMINATION uppercase")
    assert "Layer N+1 termination" in result_case, "must be case-insensitive"


def test_skill_md_exists():
    """Assertion 4: canonical SKILL.md exists at expected path."""
    assert SKILL_PATH.is_file()


def test_python_constant_matches_skill_md():
    """Assertion 5 (the core sync check): Python constant matches SKILL.md trigger list.

    If this fails: edit BOTH SKILL.md AND tools/exemption_phrases.py with same phrases.
    """
    from tools.exemption_phrases import EXEMPTION_TRIGGER_PHRASES
    skill_phrases = _extract_phrases_from_skill_md()
    python_phrases = set(EXEMPTION_TRIGGER_PHRASES)
    missing_in_python = skill_phrases - python_phrases
    missing_in_skill = python_phrases - skill_phrases
    assert not missing_in_python, (
        f"SKILL.md has phrases not in Python constant: {missing_in_python}. "
        f"Add to tools/exemption_phrases.py."
    )
    assert not missing_in_skill, (
        f"Python constant has phrases not in SKILL.md: {missing_in_skill}. "
        f"Add to SKILL.md L29-46."
    )


def test_check_commit_msg_uses_python_module():
    """Assertion 6 (per B-310 bash-wrapper split): tools/check_commit_msg.py
    (extracted from commit-msg hook per B-310 cross-platform shebang fix)
    imports from tools.exemption_phrases (single source of truth)."""
    checker_path = REPO_ROOT / "tools" / "check_commit_msg.py"
    assert checker_path.is_file()
    content = checker_path.read_text(encoding="utf-8")
    assert "from tools.exemption_phrases import" in content, (
        "check_commit_msg.py must import from tools.exemption_phrases (single source of truth)"
    )
    assert "EXEMPTION_TRIGGER_PHRASES = [" not in content, (
        "check_commit_msg.py must NOT embed its own EXEMPTION_TRIGGER_PHRASES list "
        "(would re-introduce 4-way drift surface)"
    )
