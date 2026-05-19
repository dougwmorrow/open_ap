"""Tier 0 tests for `tools/archive_chat_session.py` per B-569 closure 2026-05-19.

Mechanical lifecycle automation for B-562 multi-chat coordination architecture.
Per user-direction 2026-05-19 + B-569 BACKLOG body.

Per D67 — runs at build time + every commit; runtime ceiling < 5 s.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from tools.archive_chat_session import (
    EVENT_TYPE,
    EXIT_FATAL,
    EXIT_OPERATIONAL,
    EXIT_SUCCESS,
    EXIT_WARNING,
    _compute_archive_filename,
    archive_chat,
    cli_main,
)


def test_module_imports_and_constants() -> None:
    """Assertion 1: public surface available + D74 exit codes canonical."""
    assert callable(cli_main)
    assert callable(archive_chat)
    assert callable(_compute_archive_filename)
    assert EVENT_TYPE == "CLI_ARCHIVE_CHAT_SESSION"
    assert EXIT_SUCCESS == 0
    assert EXIT_WARNING == 1
    assert EXIT_OPERATIONAL == 2
    assert EXIT_FATAL == 3


def test_compute_archive_filename_clean_close() -> None:
    """Assertion 2: filename format <YYYY-MM-DD>-<chat>.md for clean closure."""
    name = _compute_archive_filename("meta-discipline")
    # Format: 10-char date prefix + hyphen + chat + .md
    assert name.endswith("-meta-discipline.md")
    # Date portion is YYYY-MM-DD (10 chars + 1 hyphen separator)
    date_prefix = name[:10]
    assert date_prefix.count("-") == 2
    parts = date_prefix.split("-")
    assert len(parts) == 3
    assert len(parts[0]) == 4  # year
    assert len(parts[1]) == 2  # month
    assert len(parts[2]) == 2  # day


def test_compute_archive_filename_abandoned_with_normalization() -> None:
    """Assertion 3: abandoned reason normalized (lowercase + hyphen-separated)."""
    name = _compute_archive_filename("scd2", abandoned_reason="Context Overflow")
    assert "ABANDONED-context-overflow" in name
    assert name.endswith(".md")

    # Special-char stripping
    name2 = _compute_archive_filename("test", abandoned_reason="OOM @ 2026/05/19")
    assert "ABANDONED-oom--20260519" in name2


def test_archive_chat_missing_file_raises_filenotfound(tmp_path: Path) -> None:
    """Assertion 4: missing active/<chat>.md → FileNotFoundError."""
    with patch("tools.archive_chat_session.ACTIVE_DIR", tmp_path):
        with pytest.raises(FileNotFoundError, match="does not exist"):
            archive_chat("nonexistent-chat", dry_run=True)


def test_archive_chat_dry_run_does_not_modify_filesystem(tmp_path: Path) -> None:
    """Assertion 5: dry_run=True returns paths WITHOUT moving any files."""
    active_dir = tmp_path / "active"
    archive_dir = tmp_path / "_archive"
    active_dir.mkdir()
    archive_dir.mkdir()
    source = active_dir / "testchat.md"
    source.write_text("# test content\n", encoding="utf-8")

    with patch("tools.archive_chat_session.ACTIVE_DIR", active_dir), \
         patch("tools.archive_chat_session.ARCHIVE_DIR", archive_dir), \
         patch("tools.archive_chat_session.ROUTER_PATH", tmp_path / "nonexistent-router.md"):
        source_path, archive_path, was_applied = archive_chat(
            "testchat", dry_run=True
        )

    assert was_applied is False
    assert source.is_file()  # Source NOT moved
    assert not archive_path.exists()  # Target NOT created
    assert source_path == source
    assert "testchat" in archive_path.name


def test_archive_chat_apply_moves_file_and_appends_metadata(tmp_path: Path) -> None:
    """Assertion 6: apply mode moves source → archive + appends closure metadata."""
    active_dir = tmp_path / "active"
    archive_dir = tmp_path / "_archive"
    active_dir.mkdir()
    archive_dir.mkdir()
    source = active_dir / "applychat.md"
    source.write_text("# original content\n", encoding="utf-8")

    with patch("tools.archive_chat_session.ACTIVE_DIR", active_dir), \
         patch("tools.archive_chat_session.ARCHIVE_DIR", archive_dir), \
         patch("tools.archive_chat_session.ROUTER_PATH", tmp_path / "nonexistent-router.md"):
        source_path, archive_path, was_applied = archive_chat(
            "applychat",
            closure_reason="test-completion",
            dry_run=False,
        )

    assert was_applied is True
    assert not source.exists()  # Source MOVED (deleted)
    assert archive_path.is_file()  # Target created
    archived_content = archive_path.read_text(encoding="utf-8")
    assert "# original content" in archived_content
    assert "Archive metadata" in archived_content
    assert "test-completion" in archived_content
    assert "applychat" in archived_content
    assert "CLOSED-CLEAN" in archived_content


def test_archive_chat_abandoned_variant_marks_status(tmp_path: Path) -> None:
    """Assertion 7: --abandoned variant produces ABANDONED status + filename suffix."""
    active_dir = tmp_path / "active"
    archive_dir = tmp_path / "_archive"
    active_dir.mkdir()
    archive_dir.mkdir()
    source = active_dir / "abandonedchat.md"
    source.write_text("# content\n", encoding="utf-8")

    with patch("tools.archive_chat_session.ACTIVE_DIR", active_dir), \
         patch("tools.archive_chat_session.ARCHIVE_DIR", archive_dir), \
         patch("tools.archive_chat_session.ROUTER_PATH", tmp_path / "nonexistent-router.md"):
        _, archive_path, was_applied = archive_chat(
            "abandonedchat",
            abandoned_reason="parallel chat took over scope",
            dry_run=False,
        )

    assert was_applied is True
    assert "ABANDONED" in archive_path.name
    assert "parallel-chat-took-over-scope" in archive_path.name
    archived_content = archive_path.read_text(encoding="utf-8")
    assert "ABANDONED" in archived_content
    assert "parallel chat took over scope" in archived_content


def test_archive_chat_router_table_row_removed(tmp_path: Path) -> None:
    """Assertion 8: router active-chats table row removed for archived chat."""
    active_dir = tmp_path / "active"
    archive_dir = tmp_path / "_archive"
    active_dir.mkdir()
    archive_dir.mkdir()
    source = active_dir / "routerchat.md"
    source.write_text("# content\n", encoding="utf-8")

    router_path = tmp_path / "SESSION_RESUME.md"
    router_path.write_text(
        "# Router\n\n"
        "| Chat name | Scope | State pointer |\n"
        "|---|---|---|\n"
        "| **routerchat** | test scope | `path/to/file.md` |\n"
        "| **otherchat** | other scope | `path/to/other.md` |\n",
        encoding="utf-8",
    )

    with patch("tools.archive_chat_session.ACTIVE_DIR", active_dir), \
         patch("tools.archive_chat_session.ARCHIVE_DIR", archive_dir), \
         patch("tools.archive_chat_session.ROUTER_PATH", router_path):
        archive_chat("routerchat", dry_run=False)

    router_content = router_path.read_text(encoding="utf-8")
    assert "**routerchat**" not in router_content  # Row removed
    assert "**otherchat**" in router_content  # Other rows preserved
