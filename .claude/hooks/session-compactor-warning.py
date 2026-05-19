#!/usr/bin/env python3
"""PostToolUse hook — emit warning when session is approaching compaction limit.

Per B-494 closure 2026-05-19 (udm-session-compactor Phase 2 auto-trigger
extension). This hook implements **Path E hybrid checkpoint pattern** from
claude-code-guide research 2026-05-18:

- Measures session transcript JSONL file size as proxy for token usage
- Compares against threshold (default: 70% of 1M Opus 4.7 context window)
- Emits actionable warning to stderr when threshold crossed
- Suppresses further warnings if snapshot already authored this session
- Throttles to one-warning-per-session-state (won't spam on every tool call)

Architecture (per B-494 BACKLOG entry + research-recommended Path E):

  PostToolUse fires    →  Hook measures transcript size
                       →  Compare against 70% threshold
                       →  If crossed AND no recent snapshot:
                              Emit stderr warning
                              Mark warning-fired state
                       →  Claude reads stderr in next turn
                       →  Claude proactively invokes udm-session-compactor
                       →  Snapshot authored at _session_snapshots/<date>-<hash>.md
                       →  Subsequent hook invocations detect snapshot,
                              suppress further warnings

Threshold tuning (per claude-code-guide research):
- JSONL byte-to-token ratio: ~5 bytes/token (heuristic; varies with content)
- Opus 4.7 context: 1,000,000 tokens
- 70% threshold: 700,000 tokens ≈ 3.5 MB JSONL
- Configurable via UDM_COMPACTOR_THRESHOLD_PCT env var (default 70)

Exit code: always 0 (silent on errors; never blocks tool execution).
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
METRICS_DIR = REPO_ROOT / ".claude" / "_session_metrics"
SNAPSHOTS_DIR = REPO_ROOT / "docs" / "migration" / "_session_snapshots"

# Heuristic constants per research artifact
_BYTES_PER_TOKEN_HEURISTIC = 5  # JSONL byte-to-token approximation
_DEFAULT_THRESHOLD_PCT = 70     # warn at 70% of context window
_OPUS_4_7_CONTEXT_TOKENS = 1_000_000

# State file marker — once warning fires per session, suppress until snapshot
_WARNED_STATE_SUFFIX = ".compactor-warned"


def _resolve_threshold_pct() -> int:
    """Return threshold percentage; configurable via env var per operator preference."""
    try:
        raw = os.environ.get("UDM_COMPACTOR_THRESHOLD_PCT", str(_DEFAULT_THRESHOLD_PCT))
        pct = int(raw)
        if pct < 10 or pct > 95:
            return _DEFAULT_THRESHOLD_PCT  # defensive against absurd values
        return pct
    except (ValueError, TypeError):
        return _DEFAULT_THRESHOLD_PCT


def _resolve_transcript_path(payload: dict) -> Path | None:
    """Resolve transcript JSONL path from PostToolUse hook payload.

    Per B-558 closure 2026-05-19 (Component D): use `payload["transcript_path"]`
    directly. Per claude-code-guide research `a7778dca8c0fdb8b8`: the harness
    passes the fully-qualified absolute path of the originating session's
    transcript in the hook payload. This is the CANONICAL session-identification
    field — guaranteed unique + correct even when concurrent sessions run on
    the same machine.

    Pre-B-558 implementation iterated `~/.claude/projects/*/<session-uuid>.jsonl`
    via glob — inefficient + carried a (small) concurrent-session collision risk
    surface that the payload-field approach eliminates entirely.

    Fallback to glob-based search if payload field absent (e.g., older Claude
    Code versions OR test contexts) — silent skip per defensive pattern.

    Returns None if path can't be resolved (silent skip).
    """
    # Primary: use payload field (Claude Code canonical per research)
    transcript_path_str = payload.get("transcript_path", "")
    if transcript_path_str:
        try:
            candidate = Path(transcript_path_str)
            if candidate.is_file():
                return candidate
        except (TypeError, ValueError):
            pass

    # Fallback: glob-based search (compatibility with older Claude Code OR test contexts)
    session_id = payload.get("session_id", "")
    if not session_id:
        return None
    claude_projects_dir = Path.home() / ".claude" / "projects"
    if not claude_projects_dir.is_dir():
        return None
    for project_dir in claude_projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        candidate = project_dir / f"{session_id}.jsonl"
        if candidate.is_file():
            return candidate
    return None


def _estimate_token_usage(transcript_path: Path) -> tuple[int, int]:
    """Return (estimated_tokens, transcript_byte_size).

    Heuristic per claude-code-guide research: ~5 bytes/token in JSONL transcripts.
    Refined estimation could parse JSONL + count assistant message content tokens
    via Token Counting API, but Path E hybrid uses byte heuristic for low-latency
    per-tool-call check + reserves API calls for less-frequent ground-truth.
    """
    try:
        size = transcript_path.stat().st_size
    except OSError:
        return 0, 0
    estimated_tokens = size // _BYTES_PER_TOKEN_HEURISTIC
    return estimated_tokens, size


_MIN_SNAPSHOT_BYTES = 2048  # B-558 Phase 2.1 Component B 2026-05-19 — structural-validation floor
_REQUIRED_SNAPSHOT_HEADERS = ("## §1 ", "## §2 ", "## §3 ", "## §4 ", "## §5 ")


def _is_structurally_valid_snapshot(snapshot_file: Path) -> bool:
    """Return True if snapshot file has minimum size + all 5 canonical headers.

    Per B-558 Phase 2.1 Component B closure 2026-05-19: a snapshot file that
    exists but lacks structural markers (e.g., authored as a stub before content
    landed; truncated by a crash; placeholder file) should NOT suppress the
    auto-trigger warning. Treating malformed snapshots as "no snapshot" forces
    the agent to re-author properly.

    Validation:
    1. File size >= 2048 bytes (filters out single-line stubs)
    2. All 5 canonical section headers present (## §1 through ## §5)

    Defensive: returns False on OSError / UnicodeDecodeError.
    """
    try:
        size = snapshot_file.stat().st_size
        if size < _MIN_SNAPSHOT_BYTES:
            return False
        content = snapshot_file.read_text(encoding="utf-8", errors="replace")
    except (OSError, UnicodeDecodeError):
        return False
    return all(header in content for header in _REQUIRED_SNAPSHOT_HEADERS)


def _has_recent_snapshot(session_start_iso: str | None) -> bool:
    """Return True if a STRUCTURALLY VALID session snapshot has been authored this session.

    Looks for files in `docs/migration/_session_snapshots/` modified after
    session start AND passing structural validation (per B-558 Phase 2.1
    Component B closure 2026-05-19: file size >= 2KB + all 5 canonical
    section headers present). If session_start_iso is missing, falls back
    to checking for any file modified in the last 30 minutes.

    Malformed snapshots (stubs / truncated files / placeholder files) do
    NOT suppress the auto-trigger warning — forces re-authoring.
    """
    if not SNAPSHOTS_DIR.is_dir():
        return False
    try:
        session_start_dt = (
            datetime.fromisoformat(session_start_iso.replace("Z", "+00:00"))
            if session_start_iso
            else datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
        )
        session_start_ts = session_start_dt.timestamp()
    except (ValueError, AttributeError):
        # Fallback: 30-minute cutoff
        session_start_ts = datetime.now(timezone.utc).timestamp() - 1800

    for snapshot_file in SNAPSHOTS_DIR.iterdir():
        if not snapshot_file.is_file():
            continue
        if snapshot_file.suffix != ".md":
            continue
        try:
            if snapshot_file.stat().st_mtime < session_start_ts:
                continue
        except OSError:
            continue
        # Structural validation per B-558 Phase 2.1 Component B
        if _is_structurally_valid_snapshot(snapshot_file):
            return True
    return False


def _has_warned_this_session(session_id: str) -> bool:
    """Check if warning has already fired for this session (suppression marker)."""
    if not session_id:
        return False
    marker = METRICS_DIR / f"{session_id}{_WARNED_STATE_SUFFIX}"
    return marker.is_file()


def _mark_warning_fired(session_id: str) -> None:
    """Write suppression marker so subsequent hook invocations skip the warning."""
    if not session_id:
        return
    try:
        METRICS_DIR.mkdir(parents=True, exist_ok=True)
        marker = METRICS_DIR / f"{session_id}{_WARNED_STATE_SUFFIX}"
        marker.write_text(
            datetime.now(timezone.utc).isoformat() + "\n",
            encoding="utf-8",
        )
    except OSError:
        pass  # defensive: never break tool execution


def _write_telemetry(
    session_id: str,
    tool_name: str,
    estimated_tokens: int,
    transcript_bytes: int,
    threshold_pct: int,
    warning_fired: bool,
) -> None:
    """Append telemetry row to `.claude/_session_metrics/<session-id>.jsonl`.

    Audit trail for retrospective analysis (per B-494 spec; enables
    Token Counting API ground-truth recalibration later if heuristic drift
    observed empirically).
    """
    if not session_id:
        return
    try:
        METRICS_DIR.mkdir(parents=True, exist_ok=True)
        telemetry_file = METRICS_DIR / f"{session_id}.jsonl"
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "tool_name": tool_name,
            "estimated_tokens": estimated_tokens,
            "transcript_bytes": transcript_bytes,
            "threshold_pct": threshold_pct,
            "warning_fired": warning_fired,
        }
        with telemetry_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")
    except OSError:
        pass  # defensive


def _emit_warning(estimated_tokens: int, transcript_bytes: int, threshold_pct: int) -> None:
    """Print actionable warning to stderr. Claude reads this in the next turn."""
    pct_used = round(estimated_tokens * 100 / _OPUS_4_7_CONTEXT_TOKENS, 1)
    mb_size = round(transcript_bytes / (1024 * 1024), 2)
    print(
        f"\n⚠️  SESSION COMPACTION APPROACHING (per B-494 udm-session-compactor Phase 2 auto-trigger)\n"
        f"Transcript size: {mb_size} MB (~{estimated_tokens:,} estimated tokens; {pct_used}% of 1M Opus 4.7 context)\n"
        f"Threshold crossed: {threshold_pct}%\n"
        f"\n"
        f"ACTION REQUIRED: Invoke `udm-session-compactor` skill IMMEDIATELY to author "
        f"session snapshot per skill v1.0.0 procedure. This preserves §4 Deeper insights "
        f"(architectural decisions / rejected alternatives / cross-cohort patterns / why-not "
        f"justifications / reviewer-finding context / empirical-evidence accumulations) "
        f"that context compaction would otherwise destroy.\n"
        f"\n"
        f"Snapshot path: docs/migration/_session_snapshots/<YYYY-MM-DD>-<commit-hash-prefix-7>.md\n"
        f"\n"
        f"This warning will not repeat this session once a snapshot is authored.\n",
        file=sys.stderr,
    )


def main() -> int:
    """Hook entrypoint. Exit code: always 0 (never block tool execution)."""
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # defensive

    session_id = payload.get("session_id", "")
    tool_name = payload.get("tool_name", "unknown")
    session_start = payload.get("session_start", None)
    threshold_pct = _resolve_threshold_pct()

    transcript_path = _resolve_transcript_path(payload)
    if transcript_path is None:
        return 0  # silent skip; can't measure without transcript

    estimated_tokens, transcript_bytes = _estimate_token_usage(transcript_path)
    threshold_tokens = (_OPUS_4_7_CONTEXT_TOKENS * threshold_pct) // 100

    over_threshold = estimated_tokens >= threshold_tokens
    has_snapshot = _has_recent_snapshot(session_start)
    already_warned = _has_warned_this_session(session_id)

    should_warn = over_threshold and not has_snapshot and not already_warned

    _write_telemetry(
        session_id=session_id,
        tool_name=tool_name,
        estimated_tokens=estimated_tokens,
        transcript_bytes=transcript_bytes,
        threshold_pct=threshold_pct,
        warning_fired=should_warn,
    )

    if should_warn:
        _emit_warning(estimated_tokens, transcript_bytes, threshold_pct)
        _mark_warning_fired(session_id)

    return 0


if __name__ == "__main__":
    sys.exit(main())
