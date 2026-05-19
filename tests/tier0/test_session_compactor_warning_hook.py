"""Tier 0 smoke tests for `.claude/hooks/session-compactor-warning.py` per D67 + B-494 closure.

PostToolUse hook for udm-session-compactor Phase 2 auto-trigger extension.
Per B-494 closure 2026-05-19: hook emits warning to stderr when transcript
JSONL size estimates token usage above threshold (default 70% of 1M Opus 4.7
context window).

Pins canonical hook behavior against silent regression. Architecture per
claude-code-guide research 2026-05-18 Path E hybrid checkpoint pattern.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HOOK_PATH = REPO_ROOT / ".claude" / "hooks" / "session-compactor-warning.py"


def test_hook_file_exists() -> None:
    """B-494 Assertion 1: hook script exists at canonical path."""
    assert HOOK_PATH.is_file(), f"Hook not found at {HOOK_PATH}"


def test_hook_imports_clean() -> None:
    """B-494 Assertion 2: hook module imports without errors (syntax check)."""
    sys.path.insert(0, str(HOOK_PATH.parent))
    try:
        # Import as module by reading + execing in isolated namespace
        with HOOK_PATH.open("r", encoding="utf-8") as fh:
            code = fh.read()
        compile(code, str(HOOK_PATH), "exec")
    finally:
        if str(HOOK_PATH.parent) in sys.path:
            sys.path.remove(str(HOOK_PATH.parent))


def test_resolve_threshold_pct_default() -> None:
    """B-494 Assertion 3: default threshold is 70% when no env var set."""
    # Import hook module to access _resolve_threshold_pct
    import importlib.util
    spec = importlib.util.spec_from_file_location("compactor_hook", HOOK_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # Save + clear env var
    original = os.environ.pop("UDM_COMPACTOR_THRESHOLD_PCT", None)
    try:
        assert module._resolve_threshold_pct() == 70
    finally:
        if original is not None:
            os.environ["UDM_COMPACTOR_THRESHOLD_PCT"] = original


def test_resolve_threshold_pct_env_override() -> None:
    """B-494 Assertion 4: env var override respected for valid pct."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("compactor_hook", HOOK_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    original = os.environ.get("UDM_COMPACTOR_THRESHOLD_PCT")
    try:
        os.environ["UDM_COMPACTOR_THRESHOLD_PCT"] = "85"
        assert module._resolve_threshold_pct() == 85
    finally:
        if original is None:
            os.environ.pop("UDM_COMPACTOR_THRESHOLD_PCT", None)
        else:
            os.environ["UDM_COMPACTOR_THRESHOLD_PCT"] = original


def test_resolve_threshold_pct_invalid_falls_back() -> None:
    """B-494 Assertion 5: invalid env values fall back to default 70 (defensive)."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("compactor_hook", HOOK_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    original = os.environ.get("UDM_COMPACTOR_THRESHOLD_PCT")
    try:
        for invalid_val in ("not_a_number", "5", "120", "-10"):
            os.environ["UDM_COMPACTOR_THRESHOLD_PCT"] = invalid_val
            assert module._resolve_threshold_pct() == 70, f"Failed for {invalid_val!r}"
    finally:
        if original is None:
            os.environ.pop("UDM_COMPACTOR_THRESHOLD_PCT", None)
        else:
            os.environ["UDM_COMPACTOR_THRESHOLD_PCT"] = original


def test_hook_exits_zero_on_empty_stdin() -> None:
    """B-494 Assertion 6: hook returns exit 0 on empty/invalid stdin (defensive)."""
    venv_python = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
    if not venv_python.is_file():
        pytest.skip("venv Python not present; skip subprocess test")
    result = subprocess.run(
        [str(venv_python), str(HOOK_PATH)],
        input="",
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0


def test_hook_exits_zero_on_unknown_session() -> None:
    """B-494 Assertion 7: hook returns exit 0 when session_id doesn't match any transcript (silent skip)."""
    venv_python = REPO_ROOT / ".venv" / "Scripts" / "python.exe"
    if not venv_python.is_file():
        pytest.skip("venv Python not present; skip subprocess test")
    payload = {"session_id": "nonexistent-session-uuid-test", "tool_name": "Bash"}
    result = subprocess.run(
        [str(venv_python), str(HOOK_PATH)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    # No stderr warning should fire (session not found)
    assert "SESSION COMPACTION APPROACHING" not in result.stderr


def test_emit_warning_format() -> None:
    """B-494 Assertion 8: warning text contains canonical action-required markers."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("compactor_hook", HOOK_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # Capture stderr
    captured = io.StringIO()
    original_stderr = sys.stderr
    sys.stderr = captured
    try:
        module._emit_warning(estimated_tokens=750_000, transcript_bytes=3_750_000, threshold_pct=70)
    finally:
        sys.stderr = original_stderr

    warning_text = captured.getvalue()
    assert "SESSION COMPACTION APPROACHING" in warning_text
    assert "udm-session-compactor" in warning_text
    assert "B-494" in warning_text
    assert "ACTION REQUIRED" in warning_text
    assert "_session_snapshots" in warning_text
    assert "750,000" in warning_text  # estimated tokens formatted with comma


def test_estimate_token_usage_byte_ratio() -> None:
    """B-494 Assertion 9: token estimation uses 5 bytes/token heuristic."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("compactor_hook", HOOK_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # Create temp file with known size
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".jsonl") as tmp:
        tmp.write("x" * 50_000)  # 50KB file
        tmp_path = Path(tmp.name)
    try:
        est_tokens, byte_size = module._estimate_token_usage(tmp_path)
        assert byte_size == 50_000
        assert est_tokens == 10_000  # 50000 / 5
    finally:
        tmp_path.unlink()


def test_b558_resolve_transcript_path_uses_payload_field(tmp_path: Path) -> None:
    """B-558 Assertion 11 (Component D 2026-05-19): _resolve_transcript_path uses
    payload['transcript_path'] directly per claude-code-guide research.

    Validates Path E refinement — eliminates the glob-search-based collision
    risk by using the canonical hook-payload field that Claude Code populates
    with the fully-qualified absolute path.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("compactor_hook", HOOK_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # Create a fake transcript file
    fake_transcript = tmp_path / "session-abc123.jsonl"
    fake_transcript.write_text("synthetic transcript\n", encoding="utf-8")

    # Payload with transcript_path set → should return that path directly
    payload = {
        "session_id": "abc123",
        "transcript_path": str(fake_transcript),
    }
    result = module._resolve_transcript_path(payload)
    assert result is not None
    assert result == fake_transcript


def test_b558_resolve_transcript_path_falls_back_when_payload_field_missing() -> None:
    """B-558 Assertion 12 (Component D 2026-05-19): _resolve_transcript_path
    falls back to glob-search when payload['transcript_path'] is missing OR
    points to a non-existent file. Defensive design for older Claude Code
    versions OR test contexts that lack the canonical field.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("compactor_hook", HOOK_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # Payload with missing transcript_path AND unknown session_id → returns None
    payload = {"session_id": "nonexistent-session-uuid-b558-test"}
    result = module._resolve_transcript_path(payload)
    assert result is None


def test_b558_resolve_transcript_path_handles_invalid_payload_field(tmp_path: Path) -> None:
    """B-558 Assertion 13 (Component D 2026-05-19): defensive coding when
    payload['transcript_path'] is non-string or path points to non-existent file
    — falls through to glob-search path; no exceptions raised.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("compactor_hook", HOOK_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # Invalid types should not raise
    for invalid in (None, 123, [], {"nested": "value"}):
        payload = {"session_id": "x", "transcript_path": invalid}
        # Should not raise; should return None (since session not in projects either)
        result = module._resolve_transcript_path(payload)
        assert result is None


def test_has_warned_this_session_detection() -> None:
    """B-494 Assertion 10: warning suppression marker detected correctly."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("compactor_hook", HOOK_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # Use a test session_id; create + check + cleanup
    test_session_id = "test-session-b494-tier0"
    marker = module.METRICS_DIR / f"{test_session_id}{module._WARNED_STATE_SUFFIX}"

    try:
        # Before marking: should be False
        assert module._has_warned_this_session(test_session_id) is False
        # After marking: should be True
        module._mark_warning_fired(test_session_id)
        assert module._has_warned_this_session(test_session_id) is True
    finally:
        # Cleanup
        if marker.is_file():
            marker.unlink()
