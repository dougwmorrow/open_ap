#!/usr/bin/env python3
"""Commit-msg check logic — Mechanism C-1 exemption-phrase detection.

Extracted from `.githooks/commit-msg` per B-310 cross-platform shebang fix
(2026-05-16): Windows git-bash lacks `python3` in PATH, so the previous
direct-Python-script hook failed. The git hook is now a bash wrapper
(`.githooks/commit-msg`) that detects an available Python interpreter and
invokes this module.

Usage (invoked by `.githooks/commit-msg` wrapper):
    python check_commit_msg.py <commit-msg-path>

Exit codes:
- 0: no exemption-claim phrases detected (pass)
- 1: exemption-claim phrases detected (BLOCK)
- 0: COMMIT_EDITMSG missing or unreadable (graceful fallback)
"""
from __future__ import annotations

import sys
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


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        return EXIT_SUCCESS
    commit_msg_path = Path(argv[1])
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
        return EXIT_BLOCKED

    return EXIT_SUCCESS


if __name__ == "__main__":
    sys.exit(main(sys.argv))
