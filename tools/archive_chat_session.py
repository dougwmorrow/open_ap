#!/usr/bin/env python3
"""Archive a `SESSION_RESUME/active/<chat>.md` per-chat pointer per B-569 closure 2026-05-19.

Mechanical lifecycle automation for the B-562 multi-chat coordination
architecture. Per user-direction 2026-05-19: "we should have an update for
when a SESSION_RESUME.md file should be archived and updated as completed."

Replaces operator-manual `mv` workflow currently documented in
`SESSION_RESUME/README.md` lifecycle section. Composes with B-562 substrate
(directory + per-chat pointers + root router) + B-565 mechanical refresh
enforcement + B-568 (future) topic-drift warning.

Operator workflow:
- Dry-run (default per D75): `python tools/archive_chat_session.py --chat <name>`
- Apply: `python tools/archive_chat_session.py --chat <name> --apply`
- Abandoned variant: add `--abandoned "<reason>"`

D74 exit codes: 0=success, 1=warning, 2=operational failure, 3=fatal.
D76 audit row to `_session_logs/cli_archive_chat_session_<date>.log`.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ACTIVE_DIR = REPO_ROOT / "SESSION_RESUME" / "active"
ARCHIVE_DIR = REPO_ROOT / "SESSION_RESUME" / "_archive"
ROUTER_PATH = REPO_ROOT / "SESSION_RESUME.md"
SESSION_LOG_DIR = REPO_ROOT / "_session_logs"

EVENT_TYPE = "CLI_ARCHIVE_CHAT_SESSION"

# D74 canonical exit codes
EXIT_SUCCESS = 0
EXIT_WARNING = 1
EXIT_OPERATIONAL = 2
EXIT_FATAL = 3


def _current_head_hash() -> str:
    """Return current HEAD commit hash (short form) or 'unknown' on failure."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    if result.returncode != 0:
        return "unknown"
    return result.stdout.strip() or "unknown"


def _compute_archive_filename(chat_name: str, abandoned_reason: str | None = None) -> str:
    """Compute the archive filename per `SESSION_RESUME/README.md` lifecycle spec.

    Format: `<YYYY-MM-DD>-<chat>.md` OR `<YYYY-MM-DD>-<chat>-ABANDONED-<reason>.md`
    The `<reason>` is normalized: lowercase + spaces -> hyphens + non-alphanumeric stripped.
    """
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if abandoned_reason:
        # Normalize reason: lowercase + replace spaces/underscores with hyphens
        # + strip non-alphanumeric/hyphen chars
        normalized = abandoned_reason.lower().replace(" ", "-").replace("_", "-")
        normalized = re.sub(r"[^a-z0-9-]", "", normalized)
        return f"{today}-{chat_name}-ABANDONED-{normalized}.md"
    return f"{today}-{chat_name}.md"


def _build_closure_metadata(
    chat_name: str, closure_reason: str, abandoned_reason: str | None
) -> str:
    """Build the closure-metadata block appended to the archived file."""
    head = _current_head_hash()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    status = "ABANDONED" if abandoned_reason else "CLOSED-CLEAN"
    reason_line = f"abandoned-reason: {abandoned_reason}" if abandoned_reason else f"closure-reason: {closure_reason}"
    return (
        f"\n\n---\n\n"
        f"## Archive metadata (appended by `tools/archive_chat_session.py` per B-569)\n\n"
        f"- archived-at: {today}\n"
        f"- final-commit: `{head}`\n"
        f"- chat-name: `{chat_name}`\n"
        f"- status: {status}\n"
        f"- {reason_line}\n"
    )


def _update_router_active_table(chat_name: str, dry_run: bool) -> bool:
    """Remove `chat_name` row from the active-chats table in root SESSION_RESUME.md.

    Defensive: returns True if removal applied OR if the row was not found
    (no-op is acceptable). Returns False only on file-write OSError.
    Dry-run: returns True without writing.
    """
    if not ROUTER_PATH.is_file():
        return True  # No router file — silently skip (e.g., pre-B-562 Phase 2 repos)
    try:
        content = ROUTER_PATH.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False

    # Match table rows like `| **chat-name** | scope | path |` (any whitespace around |)
    row_pattern = re.compile(
        rf"^\|\s*\*\*{re.escape(chat_name)}\*\*\s*\|.*?\|.*?\|\s*$\n",
        re.MULTILINE,
    )
    new_content, count = row_pattern.subn("", content)
    if count == 0:
        return True  # Row not in table; silent skip per defensive design

    if dry_run:
        return True

    try:
        ROUTER_PATH.write_text(new_content, encoding="utf-8")
    except OSError:
        return False
    return True


def archive_chat(
    chat_name: str,
    closure_reason: str = "session naturally closed",
    abandoned_reason: str | None = None,
    dry_run: bool = True,
) -> tuple[Path, Path, bool]:
    """Archive a per-chat pointer from active/ to _archive/.

    Args:
        chat_name: chat name (e.g., 'meta-discipline'); used to locate active/<chat>.md
        closure_reason: clean-close reason (ignored if abandoned_reason set)
        abandoned_reason: if set, marks the archive as ABANDONED with the reason
        dry_run: if True, computes paths WITHOUT moving files (per D75 default)

    Returns:
        (source_path, archive_path, was_applied) — was_applied is False in dry_run

    Raises:
        FileNotFoundError: if `SESSION_RESUME/active/<chat>.md` does not exist
    """
    source_path = ACTIVE_DIR / f"{chat_name}.md"
    if not source_path.is_file():
        raise FileNotFoundError(
            f"SESSION_RESUME/active/{chat_name}.md does not exist; "
            f"cannot archive non-existent chat"
        )

    archive_filename = _compute_archive_filename(chat_name, abandoned_reason)
    archive_path = ARCHIVE_DIR / archive_filename

    if dry_run:
        return source_path, archive_path, False

    # Read existing content + append closure metadata
    existing_content = source_path.read_text(encoding="utf-8")
    metadata_block = _build_closure_metadata(chat_name, closure_reason, abandoned_reason)
    archived_content = existing_content + metadata_block

    # Ensure archive dir exists
    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    archive_path.write_text(archived_content, encoding="utf-8")

    # Update router (defensive; tolerate row-not-found)
    _update_router_active_table(chat_name, dry_run=False)

    # Remove source after archive lands
    source_path.unlink()

    return source_path, archive_path, True


def _write_audit_row(
    chat_name: str,
    abandoned_reason: str | None,
    closure_reason: str,
    archive_path: Path,
    was_applied: bool,
    exit_code: int,
    actor: str = "operator",
) -> None:
    """Append D76 audit row. Silent on errors (defensive)."""
    try:
        SESSION_LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = (
            SESSION_LOG_DIR
            / f"cli_archive_chat_session_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.log"
        )
        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event_type": EVENT_TYPE,
            "actor": actor,
            "chat_name": chat_name,
            "abandoned_reason": abandoned_reason,
            "closure_reason": closure_reason,
            "archive_path": str(archive_path),
            "applied": was_applied,
            "exit_code": exit_code,
        }
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
    except OSError:
        pass


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Archive a SESSION_RESUME/active/<chat>.md per-chat pointer to "
            "_archive/<YYYY-MM-DD>-<chat>.md per B-562 lifecycle (B-569 mechanical "
            "automation). Per D75, --dry-run is default; pass --apply to execute."
        )
    )
    parser.add_argument(
        "--chat",
        type=str,
        required=True,
        help="chat name (file at SESSION_RESUME/active/<chat>.md)",
    )
    parser.add_argument(
        "--closure-reason",
        type=str,
        default="session naturally closed",
        help="reason cited in closure metadata (clean-close path)",
    )
    parser.add_argument(
        "--abandoned",
        type=str,
        default=None,
        help=(
            "if set, mark archive as ABANDONED with this reason; "
            "filename gets `-ABANDONED-<reason-normalized>` suffix per README.md spec"
        ),
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually move the file + update router (per D75 dry-run-default)",
    )
    parser.add_argument(
        "--actor",
        type=str,
        default=os.environ.get("USER", "operator"),
        help="actor name for audit row (default $USER)",
    )
    return parser


def cli_main(argv: list[str] | None = None) -> int:
    """CLI entrypoint per D74 contract; returns canonical exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])
    dry_run = not args.apply

    try:
        source_path, archive_path, was_applied = archive_chat(
            chat_name=args.chat,
            closure_reason=args.closure_reason,
            abandoned_reason=args.abandoned,
            dry_run=dry_run,
        )
    except FileNotFoundError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        _write_audit_row(
            args.chat, args.abandoned, args.closure_reason,
            Path("(none)"), False, EXIT_FATAL, args.actor,
        )
        return EXIT_FATAL
    except OSError as exc:
        print(f"OPERATIONAL: {exc}", file=sys.stderr)
        _write_audit_row(
            args.chat, args.abandoned, args.closure_reason,
            Path("(none)"), False, EXIT_OPERATIONAL, args.actor,
        )
        return EXIT_OPERATIONAL

    if dry_run:
        print(f"DRY-RUN: would archive `{source_path}` -> `{archive_path}`")
        if args.abandoned:
            print(f"  status: ABANDONED ({args.abandoned})")
        else:
            print(f"  status: CLOSED-CLEAN ({args.closure_reason})")
        print(f"Pass --apply to execute the move + router update.")
        exit_code = EXIT_SUCCESS
    else:
        print(f"ARCHIVED: `{source_path}` -> `{archive_path}`")
        if args.abandoned:
            print(f"  status: ABANDONED ({args.abandoned})")
        else:
            print(f"  status: CLOSED-CLEAN ({args.closure_reason})")
        print(f"  router (SESSION_RESUME.md) active-chats table updated")
        exit_code = EXIT_SUCCESS

    _write_audit_row(
        args.chat, args.abandoned, args.closure_reason,
        archive_path, was_applied, exit_code, args.actor,
    )
    return exit_code


def main() -> None:
    sys.exit(cli_main())


if __name__ == "__main__":
    main()
