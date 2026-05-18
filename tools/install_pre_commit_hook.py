#!/usr/bin/env python3
"""Install / uninstall / verify Mechanism C-1 git hooks per B-305 closure.

One-command activation of `.githooks/pre-commit` + `.githooks/commit-msg` hooks
via `git config core.hooksPath .githooks`. Closes the silent-install-failure
gap surfaced at B-301 proactive reviewer Q4 finding: manual `git config` per
clone is friction-prone and silent-failure-prone (forgotten install = hook
never fires; producer believes Mechanism C-1 is active when it is not).

Per D74 exit-code contract:
- 0: success (install/uninstall/check completed; expected state achieved)
- 1: warning (install partially succeeded; some hooks missing or non-executable)
- 2: operational failure (git command failed; not a git repo; etc.)
- 3: fatal (script error; unexpected exception)

Per D75: --dry-run default for side-effecting operations (install + uninstall).
Per D76: audit-row written to `_session_logs/cli_install_hook_<date>.log`.

Usage:
    python tools/install_pre_commit_hook.py --install --apply
    python tools/install_pre_commit_hook.py --uninstall --apply
    python tools/install_pre_commit_hook.py --check
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

EVENT_TYPE = "CLI_INSTALL_PRE_COMMIT_HOOK"
EXIT_SUCCESS = 0
EXIT_WARNING = 1
EXIT_OPERATIONAL_FAILURE = 2
EXIT_FATAL = 3

REPO_ROOT = Path(__file__).resolve().parent.parent
HOOKS_DIR = REPO_ROOT / ".githooks"
HOOK_FILES = ("pre-commit", "commit-msg")
TARGET_CONFIG_VALUE = ".githooks"


def _run_git(*args: str) -> tuple[int, str, str]:
    """Run a git command in REPO_ROOT; return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            ["git", *args], capture_output=True, text=True,
            cwd=str(REPO_ROOT), check=False,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return -1, "", str(exc)


def _current_hooks_path() -> str | None:
    """Return current value of `git config core.hooksPath`, or None if unset."""
    code, stdout, _ = _run_git("config", "--get", "core.hooksPath")
    if code == 0:
        return stdout
    return None


def _verify_hooks_present() -> tuple[bool, list[str]]:
    """Verify both hook files exist in .githooks/. Return (all_present, missing)."""
    missing = []
    for hook_name in HOOK_FILES:
        hook_path = HOOKS_DIR / hook_name
        if not hook_path.is_file():
            missing.append(hook_name)
    return (not missing), missing


def install(apply: bool) -> tuple[int, str]:
    """Install hooks via `git config core.hooksPath .githooks`.

    Returns (exit_code, diagnostic).
    """
    all_present, missing = _verify_hooks_present()
    if not all_present:
        return EXIT_OPERATIONAL_FAILURE, (
            f"Missing hook files: {missing}. Cannot install incomplete hook set. "
            f"Expected: {list(HOOK_FILES)} in {HOOKS_DIR}"
        )
    current = _current_hooks_path()
    if current == TARGET_CONFIG_VALUE:
        return EXIT_SUCCESS, (
            f"Already installed (core.hooksPath={current}). No change needed."
        )
    if not apply:
        return EXIT_SUCCESS, (
            f"DRY-RUN: would set core.hooksPath={TARGET_CONFIG_VALUE} "
            f"(current: {current or 'unset'}). Re-run with --apply to commit."
        )
    code, _, stderr = _run_git("config", "core.hooksPath", TARGET_CONFIG_VALUE)
    if code != 0:
        return EXIT_OPERATIONAL_FAILURE, f"git config failed: {stderr}"
    return EXIT_SUCCESS, (
        f"Installed: core.hooksPath set to {TARGET_CONFIG_VALUE}. "
        f"Hooks active: {list(HOOK_FILES)}."
    )


def uninstall(apply: bool) -> tuple[int, str]:
    """Uninstall hooks via `git config --unset core.hooksPath`.

    Returns (exit_code, diagnostic).
    """
    current = _current_hooks_path()
    if current is None:
        return EXIT_SUCCESS, "Already uninstalled (core.hooksPath is unset)."
    if current != TARGET_CONFIG_VALUE:
        return EXIT_WARNING, (
            f"core.hooksPath is set to {current!r} (not {TARGET_CONFIG_VALUE!r}). "
            f"Refusing to unset without --force to avoid clobbering custom config."
        )
    if not apply:
        return EXIT_SUCCESS, (
            f"DRY-RUN: would unset core.hooksPath (current: {current}). "
            f"Re-run with --apply to commit."
        )
    code, _, stderr = _run_git("config", "--unset", "core.hooksPath")
    if code != 0:
        return EXIT_OPERATIONAL_FAILURE, f"git config --unset failed: {stderr}"
    return EXIT_SUCCESS, "Uninstalled: core.hooksPath unset. Hooks no longer active."


def check() -> tuple[int, str]:
    """Verify current install state without modifying anything.

    Returns (exit_code, diagnostic).
    """
    all_present, missing = _verify_hooks_present()
    current = _current_hooks_path()
    if not all_present:
        return EXIT_WARNING, (
            f"Hook files missing: {missing}. core.hooksPath={current or 'unset'}."
        )
    if current == TARGET_CONFIG_VALUE:
        return EXIT_SUCCESS, (
            f"INSTALLED: core.hooksPath={current}; hooks present: {list(HOOK_FILES)}."
        )
    return EXIT_WARNING, (
        f"NOT INSTALLED: core.hooksPath={current or 'unset'}. "
        f"Hook files present at {HOOKS_DIR} but not activated. "
        f"Run: python tools/install_pre_commit_hook.py --install --apply"
    )


def _emit_audit_row(action: str, exit_code: int, diagnostic: str, args: argparse.Namespace) -> None:
    """Write audit row to session log per D76 (DB-less fallback for dev workstation)."""
    audit_dir = REPO_ROOT / "_session_logs"
    audit_dir.mkdir(exist_ok=True)
    log_path = audit_dir / f"cli_install_hook_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.log"
    payload = {
        "event_type": EVENT_TYPE,
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "exit_code": exit_code,
        "diagnostic": diagnostic,
        "apply": getattr(args, "apply", False),
        "args": {k: v for k, v in vars(args).items() if k != "func"},
    }
    try:
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload) + "\n")
    except OSError:
        pass


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install/uninstall/check Mechanism C-1 git hooks per B-305 closure.",
    )
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--install", action="store_true", help="Install hooks (set core.hooksPath).")
    action.add_argument("--uninstall", action="store_true", help="Uninstall hooks (unset core.hooksPath).")
    action.add_argument("--check", action="store_true", help="Check install state without modifying.")
    parser.add_argument("--apply", action="store_true",
                       help="Apply changes (without --apply, install/uninstall are dry-run per D75).")
    parser.add_argument("--no-audit", action="store_true", help="Skip audit-row write.")
    return parser.parse_args(argv)


def cli_main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    if args.install:
        action = "install"
        exit_code, diagnostic = install(args.apply)
    elif args.uninstall:
        action = "uninstall"
        exit_code, diagnostic = uninstall(args.apply)
    elif args.check:
        action = "check"
        exit_code, diagnostic = check()
    else:
        return EXIT_FATAL
    print(diagnostic)
    if not args.no_audit:
        _emit_audit_row(action, exit_code, diagnostic, args)
    return exit_code


def main() -> None:
    sys.exit(cli_main())


if __name__ == "__main__":
    main()
