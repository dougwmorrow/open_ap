#!/usr/bin/env python3
"""PreToolUse hook: warn (do not block) on Edit/Write to protected primary docs.

Conservative scope per user D answer 2026-05-16: WARNS only; does not block.
The hook reads the tool_use payload from stdin, identifies the target file,
and emits a stderr message + exit 0 (pass through) when the target is a
protected doc.

Protected docs (per user-direction + canonical-source convention):
- docs/migration/03_DECISIONS.md  (D-number registry)
- docs/migration/NORTH_STAR.md    (pillar conflict-resolution rubric)
- docs/migration/02_PHASES.md     (phase status registry)
- docs/migration/CHECKS_AND_BALANCES.md  (5-gate validation discipline)
- docs/migration/HANDOFF.md       (continuity context + Pitfall #9 source)
- CLAUDE.md                       (project-wide rules)

Exit codes:
- 0: pass through (always; warning only)
- 2 would BLOCK; reserved for future strict mode

Per Claude Code hooks documentation, hooks receive JSON via stdin with
`tool_input.file_path` for Edit/Write tool calls.
"""
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

PROTECTED_DOCS = {
    "docs/migration/03_DECISIONS.md",
    "docs/migration/NORTH_STAR.md",
    "docs/migration/02_PHASES.md",
    "docs/migration/CHECKS_AND_BALANCES.md",
    "docs/migration/HANDOFF.md",
    "CLAUDE.md",
}


def _normalize(path: str) -> str:
    """Normalize path to forward-slash form relative to repo root.

    Resolves repo root via Path(__file__) rather than env var (CLAUDE_PROJECT_DIR
    may not be set in all hook invocation contexts; relative-path normalization
    is the load-bearing semantic for PROTECTED_DOCS matching).
    """
    if not path:
        return ""
    p = path.replace("\\", "/")
    repo_root = str(REPO_ROOT).replace("\\", "/")
    if p.startswith(repo_root):
        p = p[len(repo_root):].lstrip("/")
    return p


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    tool_input = payload.get("tool_input", {})
    target = tool_input.get("file_path", "")
    norm = _normalize(target)

    if norm in PROTECTED_DOCS:
        print(
            f"[blindspot-hook] WARN: editing protected primary doc {norm}. "
            "Verify (a) authorized cascade context, (b) D-number / supersession path, "
            "(c) cross-doc cascade per D93 + hard rule 9 tracker updates queued.",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
