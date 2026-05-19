#!/usr/bin/env python3
"""Atomic B-N claim CLI per B-562 Component A closure 2026-05-19.

Eliminates the manual-discipline-dependent collision detection that caught
the empirical B-N collision 2026-05-19 between this chat (`665f14d` opened
B-558+B-559) and parallel chat (`9b1d7fb` attempted same opens; `7a810b9`
renumbered to B-560+B-561 — "other-agent published first").

Operator workflow:
- `python tools/claim_next_bn.py` (read-only; reports next available slot)
- `python tools/claim_next_bn.py --scope "..." --severity HIGH --wsjf 4.0` (dry-run
  per D75; shows what would be written)
- `python tools/claim_next_bn.py --scope "..." --severity HIGH --wsjf 4.0 --apply`
  (writes placeholder entry to BACKLOG.md)

D74 exit codes: 0=success, 1=warning, 2=operational failure, 3=fatal.
D76 audit row to `_session_logs/cli_claim_next_bn_<date>.log`.

Atomicity note: this CLI is NOT atomic across concurrent processes (Python
file I/O doesn't lock by default). For TRUE atomicity, pair with a pre-commit
hook check that validates staged BACKLOG diff doesn't contain B-N entries
matching already-committed entries — tracked as part of B-562 Component A
follow-up work (no separate B-N needed; in-cohort scope per B-562 spec).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BACKLOG_PATH = REPO_ROOT / "docs" / "migration" / "BACKLOG.md"
SESSION_LOG_DIR = REPO_ROOT / "_session_logs"

EVENT_TYPE = "CLI_CLAIM_NEXT_BN"

# D74 canonical exit codes
EXIT_SUCCESS = 0
EXIT_WARNING = 1
EXIT_OPERATIONAL = 2
EXIT_FATAL = 3

VALID_SEVERITIES: tuple[str, ...] = ("CRITICAL", "HIGH", "MEDIUM", "LOW")

# Match both `- **B-N**` (standard) AND `- ~~**B-N**~~` (strikethrough-wrapped legacy);
# capture (~~, number) per B-490 canonical format-variant table
_BN_ROW_RE = re.compile(r"^- (~~)?\*\*B-(\d+)\*\*", re.MULTILINE)


def find_highest_bn(backlog_path: Path = BACKLOG_PATH) -> int:
    """Return the highest B-N integer present in BACKLOG.md.

    Defensive: returns 0 if file missing OR no B-N rows match.
    """
    try:
        content = backlog_path.read_text(encoding="utf-8")
    except (OSError, FileNotFoundError):
        return 0
    matches = _BN_ROW_RE.findall(content)
    if not matches:
        return 0
    return max(int(num) for _strikethrough, num in matches)


def next_available_bn(backlog_path: Path = BACKLOG_PATH) -> int:
    """Return highest_bn + 1 — the next available B-N slot."""
    return find_highest_bn(backlog_path) + 1


def open_placeholder_entry(
    backlog_path: Path,
    scope: str,
    severity: str,
    wsjf: float,
    dry_run: bool = True,
) -> tuple[int, bool]:
    """Open a placeholder B-N entry in BACKLOG.md.

    Args:
        backlog_path: path to BACKLOG.md
        scope: 1-line scope description for the new B-N
        severity: one of CRITICAL / HIGH / MEDIUM / LOW
        wsjf: numeric WSJF estimate
        dry_run: if True, computes slot WITHOUT writing (per D75 default)

    Returns:
        (claimed_b_n, was_written) — was_written is False in dry_run mode

    Raises:
        ValueError: if severity not in VALID_SEVERITIES
    """
    if severity not in VALID_SEVERITIES:
        raise ValueError(
            f"invalid severity {severity!r}; must be one of {VALID_SEVERITIES}"
        )
    b_n = next_available_bn(backlog_path)
    if dry_run:
        return b_n, False

    entry = (
        f"\n- **B-{b_n}** (🟡 Open; {severity}; WSJF {wsjf}): "
        f"**[PLACEHOLDER — replace with full scope]** {scope}\n"
    )
    try:
        existing = backlog_path.read_text(encoding="utf-8") if backlog_path.is_file() else ""
        backlog_path.write_text(existing + entry, encoding="utf-8")
    except OSError:
        return b_n, False
    return b_n, True


def _write_audit_row(
    scope: str,
    severity: str,
    wsjf: float,
    claimed_bn: int,
    written: bool,
    exit_code: int,
    actor: str = "operator",
) -> None:
    """Append D76 audit row to _session_logs/cli_claim_next_bn_<date>.log.

    Silent on errors (defensive; never block CLI exit).
    """
    try:
        SESSION_LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_path = SESSION_LOG_DIR / f"cli_claim_next_bn_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.log"
        row = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event_type": EVENT_TYPE,
            "actor": actor,
            "scope": scope,
            "severity": severity,
            "wsjf": wsjf,
            "claimed_bn": claimed_bn,
            "written": written,
            "exit_code": exit_code,
        }
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
    except OSError:
        pass


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Atomic B-N claim CLI per B-562 Component A. Reads BACKLOG.md + finds next available B-N slot. Per D75, --dry-run is default; use --apply to write placeholder entry."
    )
    parser.add_argument("--scope", type=str, help="1-line scope description for new B-N entry")
    parser.add_argument(
        "--severity",
        type=str,
        default="MEDIUM",
        choices=VALID_SEVERITIES,
        help="severity classification (default MEDIUM)",
    )
    parser.add_argument(
        "--wsjf", type=float, default=2.0, help="WSJF estimate numeric (default 2.0)"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually write the placeholder entry (per D75 dry-run-default convention)",
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

    try:
        highest = find_highest_bn()
    except Exception as exc:  # noqa: BLE001
        print(f"FATAL: could not read BACKLOG.md ({exc})", file=sys.stderr)
        _write_audit_row("", args.severity, args.wsjf, 0, False, EXIT_FATAL, args.actor)
        return EXIT_FATAL

    next_slot = highest + 1

    if not args.scope:
        # Report-only mode: print next available slot + exit 0
        print(f"Next available B-N slot: B-{next_slot}")
        print(f"Highest committed B-N: B-{highest}")
        _write_audit_row("", args.severity, args.wsjf, next_slot, False, EXIT_SUCCESS, args.actor)
        return EXIT_SUCCESS

    dry_run = not args.apply
    try:
        claimed_bn, written = open_placeholder_entry(
            BACKLOG_PATH,
            scope=args.scope,
            severity=args.severity,
            wsjf=args.wsjf,
            dry_run=dry_run,
        )
    except ValueError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        _write_audit_row(args.scope, args.severity, args.wsjf, 0, False, EXIT_FATAL, args.actor)
        return EXIT_FATAL

    if dry_run:
        print(f"DRY-RUN: would claim B-{claimed_bn} for scope: {args.scope}")
        print(f"Pass --apply to write entry to BACKLOG.md")
        exit_code = EXIT_SUCCESS
    else:
        if written:
            print(f"CLAIMED: B-{claimed_bn} written to BACKLOG.md")
            print(f"  Severity: {args.severity}; WSJF: {args.wsjf}")
            print(f"  Scope (placeholder): {args.scope}")
            print(f"NEXT STEPS: edit BACKLOG.md L<last> to expand the placeholder entry")
            exit_code = EXIT_SUCCESS
        else:
            print(f"OPERATIONAL: could not write B-{claimed_bn} entry (OSError)", file=sys.stderr)
            exit_code = EXIT_OPERATIONAL

    _write_audit_row(args.scope, args.severity, args.wsjf, claimed_bn, written, exit_code, args.actor)
    return exit_code


def main() -> None:
    sys.exit(cli_main())


if __name__ == "__main__":
    main()
