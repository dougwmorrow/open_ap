"""Tier 0 smoke tests for tools/generate_cascade_evidence.py per D67 + B-317 Phase 2A."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))


def test_module_imports():
    """Assertion 1: module imports cleanly."""
    import tools.generate_cascade_evidence  # noqa: F401


def test_public_surface_exports():
    """Assertion 2: public surface present."""
    import tools.generate_cascade_evidence as gce
    assert hasattr(gce, "main")
    assert hasattr(gce, "cli_main")
    assert hasattr(gce, "generate_template")
    assert hasattr(gce, "EVENT_TYPE")
    assert hasattr(gce, "EXIT_SUCCESS")
    assert hasattr(gce, "EXIT_FATAL")


def test_event_type_constant():
    """Assertion 3: EVENT_TYPE per D76 audit-row contract."""
    from tools.generate_cascade_evidence import EVENT_TYPE
    assert EVENT_TYPE == "CLI_GENERATE_CASCADE_EVIDENCE"


def test_exit_codes_per_d74():
    """Assertion 4: D74 exit-code constants."""
    from tools.generate_cascade_evidence import EXIT_SUCCESS, EXIT_FATAL
    assert EXIT_SUCCESS == 0
    assert EXIT_FATAL == 3


def test_anti_trigger_template_has_skipped_sections():
    """Assertion 5: TYPO anti-trigger generates brief template with SKIPPED text."""
    from tools.generate_cascade_evidence import generate_template
    from tools.cascade_classifier import CommitClassification, CLASS_TYPO
    cls = CommitClassification(CLASS_TYPO, "test typo fix", True, False, 1, 2)
    template = generate_template(cls)
    assert "## TEST" in template
    assert "## GAP ANALYSIS" in template
    assert "## REVIEW" in template
    assert template.count("SKIPPED") >= 3
    assert "TYPO_ONLY" in template


def test_substantive_template_has_g1_g6_scaffold():
    """Assertion 6: SUBSTANTIVE commit gets full template with G1-G6 audit scaffold."""
    from tools.generate_cascade_evidence import generate_template
    from tools.cascade_classifier import CommitClassification, CLASS_SUBSTANTIVE
    cls = CommitClassification(CLASS_SUBSTANTIVE, "test", False, True, 5, 100)
    template = generate_template(cls)
    assert "## TEST" in template
    assert "## GAP ANALYSIS" in template
    assert "## REVIEW" in template
    for gate in ("G1", "G2", "G3", "G4", "G5", "G6"):
        assert gate in template, f"SUBSTANTIVE template missing {gate} scaffold"


def test_substrate_template_includes_reviewer_spawn_scaffold():
    """Assertion 7: SUBSTRATE_EDIT gets full template emphasizing independent review."""
    from tools.generate_cascade_evidence import generate_template
    from tools.cascade_classifier import CommitClassification, CLASS_SUBSTRATE
    cls = CommitClassification(CLASS_SUBSTRATE, "substrate test", False, True, 5, 100)
    template = generate_template(cls)
    assert "## REVIEW" in template
    assert "agentId" in template
    assert "udm-design-reviewer" in template or "udm-checks-and-balances" in template


def test_cli_main_help_invocable():
    """Assertion 8: --help exits 0."""
    from tools.generate_cascade_evidence import cli_main
    with pytest.raises(SystemExit) as excinfo:
        cli_main(["--help"])
    assert excinfo.value.code == 0


def test_cli_main_stdout_emission(capsys, monkeypatch):
    """Assertion 9: cli_main with default --output=- prints template to stdout."""
    import tools.generate_cascade_evidence as gce
    from tools.cascade_classifier import CommitClassification, CLASS_TYPO
    monkeypatch.setattr(gce, "classify_commit",
                        lambda: CommitClassification(CLASS_TYPO, "test", True, False, 1, 2))
    rc = gce.cli_main(["--no-audit"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "## TEST" in captured.out
    assert "SKIPPED" in captured.out


def test_cli_main_file_output(tmp_path, monkeypatch):
    """Assertion 10: --output <path> writes template to file."""
    import tools.generate_cascade_evidence as gce
    from tools.cascade_classifier import CommitClassification, CLASS_SUBSTANTIVE
    monkeypatch.setattr(gce, "classify_commit",
                        lambda: CommitClassification(CLASS_SUBSTANTIVE, "test", False, True, 5, 100))
    out_file = tmp_path / "evidence.md"
    rc = gce.cli_main(["--output", str(out_file), "--no-audit"])
    assert rc == 0
    assert out_file.is_file()
    content = out_file.read_text(encoding="utf-8")
    assert "## TEST" in content
    assert "## GAP ANALYSIS" in content
    assert "## REVIEW" in content


def test_cli_main_json_mode(capsys, monkeypatch):
    """Assertion 11: --json emits classification JSON instead of template."""
    import json
    import tools.generate_cascade_evidence as gce
    from tools.cascade_classifier import CommitClassification, CLASS_SUBSTRATE
    monkeypatch.setattr(gce, "classify_commit",
                        lambda: CommitClassification(CLASS_SUBSTRATE, "test", False, True, 5, 100))
    rc = gce.cli_main(["--json", "--no-audit"])
    assert rc == 0
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed["classification"] == "SUBSTRATE_EDIT"
    assert parsed["cascade_required"] is True


def test_audit_row_emission(tmp_path, monkeypatch):
    """Assertion 12: per-invocation audit row written when not --no-audit."""
    import tools.generate_cascade_evidence as gce
    from tools.cascade_classifier import CommitClassification, CLASS_TYPO
    monkeypatch.setattr(gce, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(gce, "classify_commit",
                        lambda: CommitClassification(CLASS_TYPO, "test", True, False, 1, 2))
    rc = gce.cli_main([])
    assert rc == 0
    audit_dir = tmp_path / "_session_logs"
    assert audit_dir.is_dir()
    log_files = list(audit_dir.glob("cli_generate_cascade_evidence_*.log"))
    assert len(log_files) == 1
    content = log_files[0].read_text(encoding="utf-8")
    assert "CLI_GENERATE_CASCADE_EVIDENCE" in content
    assert "TYPO_ONLY" in content


def test_classify_commit_exception_returns_fatal(tmp_path, monkeypatch, capsys):
    """Assertion 13 (per reviewer 🟡 IMPROVE): classify_commit exception path
    returns EXIT_FATAL + emits audit row with UNKNOWN classification."""
    import tools.generate_cascade_evidence as gce
    monkeypatch.setattr(gce, "REPO_ROOT", tmp_path)

    def raise_err():
        raise RuntimeError("simulated classify failure")
    monkeypatch.setattr(gce, "classify_commit", raise_err)

    rc = gce.cli_main([])
    assert rc == gce.EXIT_FATAL
    captured = capsys.readouterr()
    assert "FATAL" in captured.err
    # Audit row should still be emitted with UNKNOWN classification
    audit_dir = tmp_path / "_session_logs"
    log_files = list(audit_dir.glob("cli_generate_cascade_evidence_*.log"))
    assert len(log_files) == 1
    content = log_files[0].read_text(encoding="utf-8")
    assert "UNKNOWN" in content
    assert '"exit_code": 3' in content


def test_file_write_failure_emits_audit_row_with_fatal(tmp_path, monkeypatch):
    """Assertion 14 (per reviewer 🟡 IMPROVE): file-write failure returns EXIT_FATAL
    AND audit row records exit_code=3, not 0."""
    import tools.generate_cascade_evidence as gce
    from tools.cascade_classifier import CommitClassification, CLASS_SUBSTANTIVE
    monkeypatch.setattr(gce, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(gce, "classify_commit",
                        lambda: CommitClassification(CLASS_SUBSTANTIVE, "test", False, True, 5, 100))
    # Output path points to a non-existent directory — write should fail
    bad_path = tmp_path / "nonexistent_dir" / "evidence.md"
    rc = gce.cli_main(["--output", str(bad_path)])
    assert rc == gce.EXIT_FATAL
    audit_dir = tmp_path / "_session_logs"
    log_files = list(audit_dir.glob("cli_generate_cascade_evidence_*.log"))
    assert len(log_files) == 1
    content = log_files[0].read_text(encoding="utf-8")
    assert '"exit_code": 3' in content
