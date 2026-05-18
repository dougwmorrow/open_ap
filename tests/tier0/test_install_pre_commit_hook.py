"""Tier 0 smoke tests for tools/install_pre_commit_hook.py per D67 + B-305 closure."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))


def test_module_imports():
    """Assertion 1: module imports cleanly."""
    import tools.install_pre_commit_hook  # noqa: F401


def test_public_surface_exports():
    """Assertion 2: public surface present."""
    import tools.install_pre_commit_hook as ih
    assert hasattr(ih, "main")
    assert hasattr(ih, "cli_main")
    assert hasattr(ih, "install")
    assert hasattr(ih, "uninstall")
    assert hasattr(ih, "check")
    assert hasattr(ih, "EVENT_TYPE")
    assert hasattr(ih, "EXIT_SUCCESS")
    assert hasattr(ih, "EXIT_WARNING")
    assert hasattr(ih, "EXIT_OPERATIONAL_FAILURE")
    assert hasattr(ih, "EXIT_FATAL")
    assert hasattr(ih, "HOOK_FILES")
    assert hasattr(ih, "TARGET_CONFIG_VALUE")


def test_event_type_constant():
    """Assertion 3: EVENT_TYPE matches D76 audit-row contract."""
    from tools.install_pre_commit_hook import EVENT_TYPE
    assert EVENT_TYPE == "CLI_INSTALL_PRE_COMMIT_HOOK"


def test_exit_codes_per_d74():
    """Assertion 4: exit codes follow D74 convention."""
    from tools.install_pre_commit_hook import (
        EXIT_SUCCESS, EXIT_WARNING, EXIT_OPERATIONAL_FAILURE, EXIT_FATAL,
    )
    assert EXIT_SUCCESS == 0
    assert EXIT_WARNING == 1
    assert EXIT_OPERATIONAL_FAILURE == 2
    assert EXIT_FATAL == 3


def test_hook_files_constant():
    """Assertion 5: HOOK_FILES enumerates expected hook set."""
    from tools.install_pre_commit_hook import HOOK_FILES
    assert "pre-commit" in HOOK_FILES
    assert "commit-msg" in HOOK_FILES


def test_target_config_value():
    """Assertion 6: TARGET_CONFIG_VALUE matches CLAUDE.md hard rule 14 step 7."""
    from tools.install_pre_commit_hook import TARGET_CONFIG_VALUE
    assert TARGET_CONFIG_VALUE == ".githooks"


def test_check_function_returns_tuple():
    """Assertion 7: check() returns (exit_code, diagnostic) tuple."""
    from tools.install_pre_commit_hook import check
    result = check()
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert isinstance(result[0], int)
    assert isinstance(result[1], str)


def test_cli_main_help_invocable():
    """Assertion 8: --help exits 0."""
    from tools.install_pre_commit_hook import cli_main
    with pytest.raises(SystemExit) as excinfo:
        cli_main(["--help"])
    assert excinfo.value.code == 0


def test_cli_main_check_invocable():
    """Assertion 9: --check action invocable without --apply."""
    from tools.install_pre_commit_hook import cli_main
    exit_code = cli_main(["--check", "--no-audit"])
    assert exit_code in (0, 1)  # SUCCESS or WARNING (depends on current install state)


def test_cli_main_install_dry_run():
    """Assertion 10: --install without --apply is dry-run per D75."""
    from tools.install_pre_commit_hook import cli_main
    exit_code = cli_main(["--install", "--no-audit"])
    assert exit_code in (0, 2)  # SUCCESS dry-run OR OPERATIONAL_FAILURE if hooks missing


def test_cli_main_action_required():
    """Assertion 11: at least one action flag required (--install/--uninstall/--check)."""
    from tools.install_pre_commit_hook import cli_main
    with pytest.raises(SystemExit):
        cli_main(["--no-audit"])  # no action → argparse error
