#!/usr/bin/env python3
"""Commit-msg check logic — Mechanism C-1 exemption-phrase detection.

Extracted from `.githooks/commit-msg` per B-310 cross-platform shebang fix
(2026-05-16): Windows git-bash lacks `python3` in PATH, so the previous
direct-Python-script hook failed. The git hook is now a bash wrapper
(`.githooks/commit-msg`) that detects an available Python interpreter and
invokes this module.

Per B-306 (2026-05-16): writes per-invocation audit row to
`_session_logs/cli_check_commit_msg_<date>.log` per D76 audit-row contract.
Mirrors `tools/pre_commit_checks.py` `_emit_audit_row` pattern.

Usage (invoked by `.githooks/commit-msg` wrapper):
    python check_commit_msg.py <commit-msg-path> [--no-audit]

Exit codes:
- 0: no exemption-claim phrases detected (pass)
- 1: exemption-claim phrases detected (BLOCK)
- 0: COMMIT_EDITMSG missing or unreadable (graceful fallback)
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

EVENT_TYPE = "CLI_CHECK_COMMIT_MSG"
EXIT_SUCCESS = 0
EXIT_BLOCKED = 1

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

try:
    from tools.exemption_phrases import contains_exemption_phrase
except ImportError as _exc:
    print(f"[commit-msg WARN] cannot import tools.exemption_phrases ({_exc}); "
          "exemption-phrase check skipped.", file=sys.stderr)
    contains_exemption_phrase = None  # type: ignore[assignment]


def _emit_audit_row(commit_msg_path: Path, matched_phrases: list[str], exit_code: int) -> None:
    """Per-invocation audit row per D76 + B-306."""
    audit_dir = REPO_ROOT / "_session_logs"
    try:
        audit_dir.mkdir(exist_ok=True)
    except OSError:
        return
    log_path = audit_dir / f"cli_check_commit_msg_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.log"
    payload = {
        "event_type": EVENT_TYPE,
        "ts": datetime.now(timezone.utc).isoformat(),
        "commit_msg_path": str(commit_msg_path),
        "matched_phrases": matched_phrases,
        "exit_code": exit_code,
    }
    try:
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload) + "\n")
    except OSError:
        pass


def main(argv: list[str]) -> int:
    no_audit = "--no-audit" in argv
    positional = [a for a in argv[1:] if not a.startswith("--")]
    if not positional:
        return EXIT_SUCCESS
    commit_msg_path = Path(positional[0])
    if not commit_msg_path.is_file():
        return EXIT_SUCCESS
    try:
        commit_msg = commit_msg_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return EXIT_SUCCESS
    if contains_exemption_phrase is None:
        return EXIT_SUCCESS

    non_comment_lines = [
        line for line in commit_msg.splitlines()
        if not line.lstrip().startswith("#")
    ]
    actual_msg = "\n".join(non_comment_lines)

    matched_phrases = contains_exemption_phrase(actual_msg)
    exit_code = EXIT_BLOCKED if matched_phrases else EXIT_SUCCESS

    if not no_audit:
        _emit_audit_row(commit_msg_path, matched_phrases, exit_code)

    if matched_phrases:
        print("[commit-msg BLOCKED] commit message contains exemption-claim "
              "trigger phrases:", file=sys.stderr)
        for p in matched_phrases:
            print(f"  - {p!r}", file=sys.stderr)
        print("\nPer Mechanism C-1 + udm-exemption-verifier SKILL.md: spawn "
              "udm-exemption-verifier reviewer (via Claude Code session) BEFORE "
              "committing. Reviewer verdict VALID -> proceed; INVALID -> spawn "
              "udm-gap-check per D56 second-pass; address findings; re-attempt "
              "commit.", file=sys.stderr)
        print("\nBypass with --no-verify is self-flagging exemption-claim that "
              "reviewers should treat as quasi-audit-question trigger.",
              file=sys.stderr)

    return exit_code


if __name__ == "__main__":
    sys.exit(main(sys.argv))
