"""Tier 0 smoke tests for tools/audit_cascade_compliance.py per D67 + B-317 Phase 3."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))


def test_module_imports():
    """Assertion 1: module imports cleanly."""
    import tools.audit_cascade_compliance  # noqa: F401


def test_public_surface_exports():
    """Assertion 2: public surface present."""
    import tools.audit_cascade_compliance as acc
    assert hasattr(acc, "main")
    assert hasattr(acc, "cli_main")
    assert hasattr(acc, "audit_commits")
    assert hasattr(acc, "classify_historical")
    assert hasattr(acc, "CommitAudit")
    assert hasattr(acc, "EVENT_TYPE")
    assert hasattr(acc, "EXIT_SUCCESS")
    assert hasattr(acc, "EXIT_WARNING")
    assert hasattr(acc, "EXIT_FATAL")


def test_event_type_constant():
    """Assertion 3: EVENT_TYPE per D76 audit-row contract."""
    from tools.audit_cascade_compliance import EVENT_TYPE
    assert EVENT_TYPE == "CLI_AUDIT_CASCADE_COMPLIANCE"


def test_exit_codes_per_d74():
    """Assertion 4: D74 exit-code constants."""
    from tools.audit_cascade_compliance import EXIT_SUCCESS, EXIT_WARNING, EXIT_FATAL
    assert EXIT_SUCCESS == 0
    assert EXIT_WARNING == 1
    assert EXIT_FATAL == 3


def test_classify_historical_substrate():
    """Assertion 5: substrate file → SUBSTRATE_EDIT classification + cascade_required."""
    from tools.audit_cascade_compliance import classify_historical, CLASS_SUBSTRATE_HIST
    classification, cascade_required = classify_historical(["tools/pre_commit_checks.py"])
    assert classification == CLASS_SUBSTRATE_HIST
    assert cascade_required is True


def test_classify_historical_canonical_source():
    """Assertion 6: D-N source file → CANONICAL_SOURCE classification + cascade_required."""
    from tools.audit_cascade_compliance import classify_historical, CLASS_CANONICAL_SOURCE
    classification, cascade_required = classify_historical(["docs/migration/03_DECISIONS.md"])
    assert classification == CLASS_CANONICAL_SOURCE
    assert cascade_required is True


def test_classify_historical_polish_only():
    """Assertion 7: POLISH_QUEUE only → POLISH classification + cascade NOT required."""
    from tools.audit_cascade_compliance import classify_historical, CLASS_POLISH
    classification, cascade_required = classify_historical(["docs/migration/POLISH_QUEUE.md"])
    assert classification == CLASS_POLISH
    assert cascade_required is False


def test_classify_historical_backlog_classifies_as_canonical_source():
    """Assertion 8 (per reviewer pre-emptive flag + design correction): BACKLOG-only
    commits classify as CANONICAL_SOURCE (cascade required) — safer default since
    new B-N entries are substantive content. Was BACKLOG_ONLY (cascade NOT required)
    which would have missed substantive BACKLOG additions."""
    from tools.audit_cascade_compliance import classify_historical, CLASS_CANONICAL_SOURCE
    classification, cascade_required = classify_historical(["docs/migration/BACKLOG.md"])
    assert classification == CLASS_CANONICAL_SOURCE
    assert cascade_required is True


def test_classify_historical_typo_small_md():
    """Assertion 9: small md-only (≤2 files) → TYPO_SMALL_MD + cascade NOT required."""
    from tools.audit_cascade_compliance import classify_historical, CLASS_TYPO_SMALL_MD
    classification, cascade_required = classify_historical(["docs/migration/HANDOFF.md"])
    assert classification == CLASS_TYPO_SMALL_MD
    assert cascade_required is False


def test_classify_historical_substantive_default():
    """Assertion 10: mixed/many non-substrate files → SUBSTANTIVE + cascade_required."""
    from tools.audit_cascade_compliance import classify_historical, CLASS_SUBSTANTIVE
    classification, cascade_required = classify_historical([
        "src/foo.py", "src/bar.py", "src/baz.py"
    ])
    assert classification == CLASS_SUBSTANTIVE
    assert cascade_required is True


def test_classify_historical_empty():
    """Assertion 11: empty file list defaults to SUBSTANTIVE (safe default)."""
    from tools.audit_cascade_compliance import classify_historical, CLASS_SUBSTANTIVE
    classification, cascade_required = classify_historical([])
    assert classification == CLASS_SUBSTANTIVE
    assert cascade_required is True


def test_commit_audit_to_dict():
    """Assertion 12: CommitAudit dataclass to_dict() emits all fields."""
    from tools.audit_cascade_compliance import CommitAudit
    a = CommitAudit(
        hash="abc12345", subject="test", classification="SUBSTANTIVE",
        cascade_required=True, has_evidence=False, missing_sections=["TEST"],
        is_compliant=False, file_count=3,
    )
    d = a.to_dict()
    for k in ("hash", "subject", "classification", "cascade_required",
              "has_evidence", "missing_sections", "is_compliant", "file_count"):
        assert k in d


def test_cli_main_help_invocable():
    """Assertion 13: --help exits 0."""
    from tools.audit_cascade_compliance import cli_main
    with pytest.raises(SystemExit) as excinfo:
        cli_main(["--help"])
    assert excinfo.value.code == 0


def test_audit_commits_returns_list(monkeypatch):
    """Assertion 14: audit_commits returns a list of CommitAudit (smoke; mocked git)."""
    import tools.audit_cascade_compliance as acc

    monkeypatch.setattr(acc, "_git_log",
                        lambda n: [("abc12345", "test commit")])
    monkeypatch.setattr(acc, "_commit_files",
                        lambda h: ["tools/pre_commit_checks.py"])
    monkeypatch.setattr(acc, "_commit_message",
                        lambda h: "## TEST\nok\n## GAP ANALYSIS\nok\n## REVIEW\nok\n")

    audits = acc.audit_commits(n_commits=1)
    assert len(audits) == 1
    assert audits[0].hash == "abc12345"
    assert audits[0].classification == "SUBSTRATE_EDIT"
    assert audits[0].has_evidence is True
    assert audits[0].is_compliant is True


def test_audit_commits_flags_non_compliant(monkeypatch):
    """Assertion 15: substrate commit WITHOUT cascade-evidence → is_compliant=False."""
    import tools.audit_cascade_compliance as acc

    monkeypatch.setattr(acc, "_git_log",
                        lambda n: [("deadbeef", "bare substrate commit")])
    monkeypatch.setattr(acc, "_commit_files",
                        lambda h: ["tools/cascade_classifier.py"])
    monkeypatch.setattr(acc, "_commit_message",
                        lambda h: "build: bare commit message no sections\n")

    audits = acc.audit_commits(n_commits=1)
    assert len(audits) == 1
    assert audits[0].is_compliant is False
    assert "TEST" in audits[0].missing_sections


def test_audit_row_emission_on_warning(tmp_path, monkeypatch):
    """Assertion 16: per-invocation audit row written; exit_code WARNING for non-compliant."""
    import tools.audit_cascade_compliance as acc

    monkeypatch.setattr(acc, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(acc, "_git_log",
                        lambda n: [("deadbeef", "bare commit")])
    monkeypatch.setattr(acc, "_commit_files",
                        lambda h: ["tools/cascade_classifier.py"])
    monkeypatch.setattr(acc, "_commit_message",
                        lambda h: "build: bare\n")

    rc = acc.cli_main([])
    assert rc == acc.EXIT_WARNING
    audit_dir = tmp_path / "_session_logs"
    assert audit_dir.is_dir()
    log_files = list(audit_dir.glob("cli_audit_cascade_compliance_*.log"))
    assert len(log_files) == 1
    content = log_files[0].read_text(encoding="utf-8")
    assert "CLI_AUDIT_CASCADE_COMPLIANCE" in content
    assert '"non_compliant_count": 1' in content
    assert '"exit_code": 1' in content


def test_classify_historical_skill_md_substrate_via_prefix():
    """Assertion 17 (per reviewer 🟡 IMPROVE): substrate matching via
    SUBSTRATE_DIR_PREFIXES — `.claude/skills/udm-foo/SKILL.md` classifies as
    SUBSTRATE_EDIT even though not an exact-match in SUBSTRATE_FILES."""
    from tools.audit_cascade_compliance import classify_historical, CLASS_SUBSTRATE_HIST
    classification, cascade_required = classify_historical([
        ".claude/skills/udm-gap-check/SKILL.md"
    ])
    assert classification == CLASS_SUBSTRATE_HIST
    assert cascade_required is True


def test_cli_main_json_mode(capsys, monkeypatch):
    """Assertion 18 (per reviewer 🟡 IMPROVE): --json emits valid JSON."""
    import json
    import tools.audit_cascade_compliance as acc

    monkeypatch.setattr(acc, "_git_log",
                        lambda n: [("abc12345", "test commit subject")])
    monkeypatch.setattr(acc, "_commit_files",
                        lambda h: ["tools/cascade_classifier.py"])
    monkeypatch.setattr(acc, "_commit_message",
                        lambda h: "## TEST\nok\n## GAP ANALYSIS\nok\n## REVIEW\nok\n")

    rc = acc.cli_main(["--json", "--no-audit"])
    assert rc == acc.EXIT_SUCCESS
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert isinstance(parsed, list)
    assert len(parsed) == 1
    assert parsed[0]["hash"] == "abc12345"
    assert parsed[0]["is_compliant"] is True


def test_cli_main_non_compliant_only_filter(capsys, monkeypatch):
    """Assertion 19 (per reviewer 🟡 IMPROVE): --non-compliant-only filters output
    to only flagged commits."""
    import tools.audit_cascade_compliance as acc

    def fake_log(n):
        return [("aaa11111", "compliant"), ("bbb22222", "non-compliant")]

    def fake_files(h):
        return ["tools/cascade_classifier.py"]

    def fake_msg(h):
        if h == "aaa11111":
            return "## TEST\nok\n## GAP ANALYSIS\nok\n## REVIEW\nok\n"
        return "build: bare\n"  # non-compliant

    monkeypatch.setattr(acc, "_git_log", fake_log)
    monkeypatch.setattr(acc, "_commit_files", fake_files)
    monkeypatch.setattr(acc, "_commit_message", fake_msg)

    rc = acc.cli_main(["--non-compliant-only", "--no-audit"])
    assert rc == acc.EXIT_WARNING
    captured = capsys.readouterr()
    # Output should mention the non-compliant hash but not the compliant one
    assert "bbb22222" in captured.out
    # Compliant hash should appear only in the count summary, not as a flagged item
    flagged_lines = [line for line in captured.out.splitlines() if line.strip().startswith("[WARN]")]
    assert all("aaa11111" not in line for line in flagged_lines)
