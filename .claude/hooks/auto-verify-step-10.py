#!/usr/bin/env python3
"""PostToolUse hook: auto-invoke query_blindspots on the just-edited source file.

Conservative scope per user D answer 2026-05-16: fires only on Edit/Write
to source files under tools/ data_load/ cdc/ scd2/ orchestration/ schema/
extract/ observability/ utils/ migrations/. Skips test files, docs, .claude/.

The hook runs query_blindspots.py with --file <target> in dry-run mode,
captures the output, and emits a stderr summary + exit 0 (warning only).

Per Claude Code hooks documentation, PostToolUse cannot undo the action;
this is informational. Producer is expected to ACT on the warning at the
next cascade step.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

SOURCE_DIRS = (
    "tools/",
    "data_load/",
    "cdc/",
    "scd2/",
    "orchestration/",
    "schema/",
    "extract/",
    "observability/",
    "utils/",
    "migrations/",
)


def _normalize(path: str) -> str:
    if not path:
        return ""
    p = path.replace("\\", "/")
    repo_root = str(REPO_ROOT).replace("\\", "/")
    if p.startswith(repo_root):
        p = p[len(repo_root):].lstrip("/")
    return p


def _is_source_file(norm: str) -> bool:
    if not norm.endswith(".py"):
        return False
    if "/tests/" in norm or norm.startswith("tests/"):
        return False
    return any(norm.startswith(d) for d in SOURCE_DIRS)


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    tool_input = payload.get("tool_input", {})
    target = tool_input.get("file_path", "")
    norm = _normalize(target)

    if not _is_source_file(norm):
        return 0

    abs_target = REPO_ROOT / norm
    if not abs_target.is_file():
        return 0

    venv_python = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
    python_exe = str(venv_python) if venv_python.is_file() else sys.executable

    try:
        result = subprocess.run(
            [python_exe, "tools/query_blindspots.py", "--file", norm, "--no-audit"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
            timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        return 0

    if result.returncode != 0 and result.stdout:
        print(
            f"[blindspot-hook] query_blindspots flagged matches on {norm}:\n{result.stdout}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
