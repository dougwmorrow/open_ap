"""Tier 0 smoke tests for tools/check_commit_msg.py (extracted from commit-msg hook per B-310).

Verifies the Python module that does the commit-msg exemption-phrase check
when invoked by the bash wrapper at .githooks/commit-msg.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))


def test_module_imports():
    """Assertion 1: module imports cleanly."""
    import tools.check_commit_msg  # noqa: F401


def test_main_function_present():
    """Assertion 2: main(argv) function defined."""
    import tools.check_commit_msg as ccm
    assert hasattr(ccm, "main")
    assert callable(ccm.main)


def test_main_empty_argv_returns_zero():
    """Assertion 3: main(['script']) returns 0 (no COMMIT_EDITMSG path provided)."""
    from tools.check_commit_msg import main
    assert main(["check_commit_msg.py"]) == 0


def test_main_nonexistent_path_returns_zero(tmp_path):
    """Assertion 4: main with nonexistent COMMIT_EDITMSG path returns 0 (graceful)."""
    from tools.check_commit_msg import main
    fake_path = tmp_path / "does-not-exist"
    assert main(["check_commit_msg.py", str(fake_path)]) == 0


def test_main_clean_message_returns_zero(tmp_path):
    """Assertion 5: main with clean commit message returns 0."""
    from tools.check_commit_msg import main
    msg_path = tmp_path / "COMMIT_EDITMSG"
    msg_path.write_text("feat: add new feature\n\nNormal commit body.\n", encoding="utf-8")
    assert main(["check_commit_msg.py", str(msg_path)]) == 0


def test_main_blocks_on_exemption_phrase(tmp_path):
    """Assertion 6: main with exemption-phrase message returns 1 (BLOCK)."""
    from tools.check_commit_msg import main
    msg_path = tmp_path / "COMMIT_EDITMSG"
    msg_path.write_text("docs: applying Layer N+1 termination\n", encoding="utf-8")
    assert main(["check_commit_msg.py", str(msg_path)]) == 1


def test_main_strips_git_comment_lines(tmp_path):
    """Assertion 7: main ignores git-comment lines (#-prefixed)."""
    from tools.check_commit_msg import main
    msg_path = tmp_path / "COMMIT_EDITMSG"
    # Exemption phrase only in a comment line — should NOT block
    msg_path.write_text(
        "feat: real commit message\n\n# Comment: Layer N+1 termination is forbidden\n",
        encoding="utf-8",
    )
    assert main(["check_commit_msg.py", str(msg_path)]) == 0


def test_main_uses_canonical_phrases():
    """Assertion 8: module imports contains_exemption_phrase from canonical source."""
    hook_path = REPO_ROOT / "tools" / "check_commit_msg.py"
    content = hook_path.read_text(encoding="utf-8")
    assert "from tools.exemption_phrases import contains_exemption_phrase" in content
    assert "EXEMPTION_TRIGGER_PHRASES = [" not in content, (
        "check_commit_msg must NOT embed its own list (B-309 dedupe)"
    )


def test_d74_exit_codes_present():
    """Assertion 9 (per B-306): D74 exit-code constants present."""
    import tools.check_commit_msg as ccm
    assert ccm.EXIT_SUCCESS == 0
    assert ccm.EXIT_BLOCKED == 1


def test_event_type_constant():
    """Assertion 10 (per B-306): EVENT_TYPE constant per D76 audit-row contract."""
    import tools.check_commit_msg as ccm
    assert ccm.EVENT_TYPE == "CLI_CHECK_COMMIT_MSG"


def test_audit_row_written_on_clean_message(tmp_path, monkeypatch):
    """Assertion 11 (per B-306): per-invocation audit row written when not --no-audit."""
    import tools.check_commit_msg as ccm
    audit_dir = tmp_path / "_session_logs"
    monkeypatch.setattr(ccm, "REPO_ROOT", tmp_path)

    msg_path = tmp_path / "COMMIT_EDITMSG"
    msg_path.write_text("feat: clean commit\n", encoding="utf-8")

    rc = ccm.main(["check_commit_msg.py", str(msg_path)])
    assert rc == ccm.EXIT_SUCCESS
    assert audit_dir.is_dir()
    log_files = list(audit_dir.glob("cli_check_commit_msg_*.log"))
    assert len(log_files) == 1
    content = log_files[0].read_text(encoding="utf-8")
    assert '"event_type": "CLI_CHECK_COMMIT_MSG"' in content
    assert '"exit_code": 0' in content
    assert '"matched_phrases": []' in content


def test_audit_row_written_on_blocked_message(tmp_path, monkeypatch):
    """Assertion 12 (per B-306): audit row captures matched phrases when BLOCKED."""
    import tools.check_commit_msg as ccm
    audit_dir = tmp_path / "_session_logs"
    monkeypatch.setattr(ccm, "REPO_ROOT", tmp_path)

    msg_path = tmp_path / "COMMIT_EDITMSG"
    msg_path.write_text("docs: applying Layer N+1 termination\n", encoding="utf-8")

    rc = ccm.main(["check_commit_msg.py", str(msg_path)])
    assert rc == ccm.EXIT_BLOCKED
    log_files = list(audit_dir.glob("cli_check_commit_msg_*.log"))
    assert len(log_files) == 1
    content = log_files[0].read_text(encoding="utf-8")
    assert '"exit_code": 1' in content
    assert "Layer N+1 termination" in content


def test_no_audit_flag_skips_audit_write(tmp_path, monkeypatch):
    """Assertion 13 (per B-306): --no-audit flag suppresses audit-row write."""
    import tools.check_commit_msg as ccm
    monkeypatch.setattr(ccm, "REPO_ROOT", tmp_path)

    msg_path = tmp_path / "COMMIT_EDITMSG"
    msg_path.write_text("feat: clean\n", encoding="utf-8")

    rc = ccm.main(["check_commit_msg.py", str(msg_path), "--no-audit"])
    assert rc == ccm.EXIT_SUCCESS
    audit_dir = tmp_path / "_session_logs"
    if audit_dir.is_dir():
        assert not list(audit_dir.glob("cli_check_commit_msg_*.log"))
