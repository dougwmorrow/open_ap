#!/usr/bin/env python3
"""SessionStart hook: optionally log session start to _session_logs/.

Per user D answer 2026-05-16: optional markdown/text recording of chat is
allowed but not required. This hook writes a minimal session-start row to
_session_logs/sessions_<date>.log when the directory exists; otherwise
silently passes.

Exit code: always 0.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SESSION_LOG_DIR = REPO_ROOT / "_session_logs"


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}

    if not SESSION_LOG_DIR.is_dir():
        return 0

    log_path = SESSION_LOG_DIR / f"sessions_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.log"
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": "session_start",
        "session_id": payload.get("session_id", "unknown"),
        "cwd": os.getcwd(),
    }
    try:
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except OSError:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
