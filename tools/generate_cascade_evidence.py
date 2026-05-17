#!/usr/bin/env python3
"""Generate cascade-evidence section template per hard rule 14 + B-317 Phase 2A.

Reduces friction of cascade-evidence authoring per `udm-post-edit-verification`
SKILL.md + B-318 tri-section discipline. Producer runs this CLI on staged
scope; tool classifies the commit + emits a tri-section template; producer
pipes into commit message + fills in verdicts.

Closes the "skip cascade because writing the evidence section feels like
overhead" failure mode — template is auto-generated; producer only fills
in the verdict text.

Composition:
- Reads classification from `tools/cascade_classifier.py::classify_commit()`
- Anti-trigger commits: brief template with `SKIPPED: <classification>` rationale
- SUBSTANTIVE / SUBSTRATE commits: full tri-section template with G1-G6
  audit scaffold + reviewer-verdict scaffold

Per D74 exit codes:
- 0: template emitted successfully
- 3: fatal error (e.g., git unavailable)

Per D75: read-only; no --dry-run needed (pure template emission).
Per D76: audit row to `_session_logs/cli_generate_cascade_evidence_<date>.log`.

Usage:
    python tools/generate_cascade_evidence.py             # emit to stdout
    python tools/generate_cascade_evidence.py --output evidence.md
    python tools/generate_cascade_evidence.py --json      # JSON classification

Public surface:
- `cli_main(argv) -> int`
- `main() -> None`
- `generate_template(cls: CommitClassification) -> str`
- `EVENT_TYPE` = "CLI_GENERATE_CASCADE_EVIDENCE"
- `EXIT_SUCCESS` = 0
- `EXIT_FATAL` = 3
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

EVENT_TYPE = "CLI_GENERATE_CASCADE_EVIDENCE"
EXIT_SUCCESS = 0
EXIT_FATAL = 3

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

try:
    from tools.cascade_classifier import (
        CommitClassification,
        classify_commit,
        CLASS_SUBSTRATE,
    )
except ImportError as _exc:
    print(f"[generate_cascade_evidence FATAL] cannot import tools.cascade_classifier "
          f"({_exc})", file=sys.stderr)
    sys.exit(EXIT_FATAL)


_ANTI_TRIGGER_TEMPLATE = """## TEST
SKIPPED: {classification} anti-trigger ({rationale}). NOTE: if any code or test
file was touched, replace this line with the pytest verdict; SKIPPED is for
pure-prose anti-triggers only.

## GAP ANALYSIS
SKIPPED: {classification} anti-trigger; per CLAUDE.md hard rule 14 anti-trigger clause.

## REVIEW
SKIPPED: {classification} anti-trigger; per CLAUDE.md hard rule 14 anti-trigger clause.
"""


_SUBSTRATE_TEMPLATE = """## TEST
<pytest verdict — e.g. `pytest tests/tier0 tests/tier1 tests/unit ...` -> NNN/MM/0>
<orchestrator smoke test verdict — e.g. `python tools/pre_commit_checks.py --verbose` -> 6/6 PASS>
<targeted-module test verdict if applicable>

## GAP ANALYSIS
<inline G1-G6 audit OR `udm-gap-check` independent-reviewer verdict>
- G1 cross-tracker drift (BACKLOG / CURRENT_STATE / HANDOFF / _validation_log consistency): <verdict>
- G2 arithmetic-propagation (test counts / B-N counts / file counts verified): <verdict>
- G3 canonical re-read (line numbers / function names / B-N citations verified): <verdict>
- G4 discipline-applied (hard rule 14 cascade applied to this commit): <verdict — YES if filling this template>
- G5 convention-registration (CLAUDE.md Structure + GLOSSARY for new public surface): <verdict>
- G6 new B-N opportunities surfaced: <list or NONE>

## REVIEW
<spawn appropriate reviewer per CLAUDE.md hard rule 14 step 3:>
<- udm-design-reviewer (architectural / hook orchestrator / Mechanism C-1 enforcement)>
<- udm-data-engineer-review (pipeline-touching: scd2 / cdc / orchestration / extract)>
<- udm-checks-and-balances 5-gate (D-N + doc artifacts)>
<- udm-runbook-author (RB-N)>
<- udm-edge-case-validator (M / S / I / N / P / G / D / F / V series)>
<- udm-exemption-verifier (when commit message contains exemption-phrase patterns)>
<For substrate edits inline self-review is NEVER valid; independent spawn required.>

Reviewer agentId: <hex>
Verdict: <SOUND-as-is / SOUND-with-improvements / UNSOUND-fix-required>
Findings disposition:
- <BLOCK finding 1>: <inline-fix / new B-N opened>
- <IMPROVE finding 1>: <inline-fix / new B-N opened / dismiss-with-rationale>

Classification: {classification}
Rationale: {rationale}
Staged files: {staged_count}; lines changed: {total_lines_changed}
"""


_SUBSTANTIVE_TEMPLATE = """## TEST
<pytest verdict — e.g. `pytest tests/tier0 tests/tier1 ...` -> NNN/MM/0>
<targeted-module test verdict if applicable>

## GAP ANALYSIS
<inline G1-G6 audit OR `udm-gap-check` independent-reviewer verdict>
- G1 cross-tracker drift: <verdict>
- G2 arithmetic-propagation: <verdict>
- G3 canonical re-read: <verdict>
- G4 discipline-applied: <verdict — YES if filling this template>
- G5 convention-registration: <verdict>
- G6 new B-N opportunities: <list or NONE>

## REVIEW
<spawn appropriate reviewer per CLAUDE.md hard rule 14 step 3>
<inline self-review is valid ONLY when scope is ≤50 LOC AND no new public surface>
<for >50 LOC OR new public surface: independent reviewer spawn required>

Reviewer agentId / scope: <hex or "inline self-review (≤50 LOC; no new surface)">
Verdict: <SOUND / SOUND-with-improvements / UNSOUND>
Findings disposition: <inline-fix / new B-N / dismiss>

Classification: {classification}
Rationale: {rationale}
"""


def generate_template(cls: CommitClassification) -> str:
    """Generate cascade-evidence template appropriate for the classification.

    SUBSTRATE_EDIT -> full template with reviewer-spawn scaffold (high-risk
    discipline-substrate edits MUST have independent review).

    Anti-triggers (TYPO / WHITESPACE / BADGE_FLIP / POLISH) -> brief template
    with `SKIPPED: <anti-trigger>` text in each section.

    SUBSTANTIVE (default) -> full template; reviewer may be inline self-review
    OR independent spawn per scope.
    """
    fields = {
        "classification": cls.classification,
        "rationale": cls.rationale,
        "staged_count": cls.staged_count,
        "total_lines_changed": cls.total_lines_changed,
    }
    if cls.is_anti_trigger:
        return _ANTI_TRIGGER_TEMPLATE.format(**fields)
    if cls.classification == CLASS_SUBSTRATE:
        return _SUBSTRATE_TEMPLATE.format(**fields)
    return _SUBSTANTIVE_TEMPLATE.format(**fields)


def _emit_audit_row(cls: CommitClassification, exit_code: int) -> None:
    """Per-invocation audit row per D76."""
    audit_dir = REPO_ROOT / "_session_logs"
    try:
        audit_dir.mkdir(exist_ok=True)
    except OSError:
        return
    log_path = audit_dir / f"cli_generate_cascade_evidence_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.log"
    payload = {
        "event_type": EVENT_TYPE,
        "ts": datetime.now(timezone.utc).isoformat(),
        "classification": cls.classification,
        "cascade_required": cls.cascade_required,
        "staged_count": cls.staged_count,
        "exit_code": exit_code,
    }
    try:
        with log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload) + "\n")
    except OSError:
        pass


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Emit cascade-evidence section template for current staged scope.",
    )
    parser.add_argument("--output", default="-",
                        help="Output file path; default '-' for stdout.")
    parser.add_argument("--json", action="store_true",
                        help="Emit classification as JSON (no template).")
    parser.add_argument("--no-audit", action="store_true",
                        help="Skip audit-row write.")
    return parser.parse_args(argv)


def cli_main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    try:
        cls = classify_commit()
    except Exception as exc:  # noqa: BLE001
        print(f"generate_cascade_evidence FATAL: {exc}", file=sys.stderr)
        # Per reviewer 🟡 IMPROVE: audit row should fire on failure paths too
        # for forensic completeness; fabricate a minimal classification record
        # if classify_commit failed before producing one.
        if not args.no_audit:
            try:
                fake_cls = CommitClassification(
                    classification="UNKNOWN",
                    rationale=f"classify_commit raised {type(exc).__name__}: {exc}",
                    is_anti_trigger=False,
                    cascade_required=True,
                    staged_count=0,
                    total_lines_changed=0,
                )
                _emit_audit_row(fake_cls, EXIT_FATAL)
            except Exception:  # noqa: BLE001 — defensive
                pass
        return EXIT_FATAL

    if args.json:
        out = json.dumps(cls.to_dict(), indent=2)
    else:
        out = generate_template(cls)

    exit_code = EXIT_SUCCESS
    if args.output == "-":
        print(out)
    else:
        try:
            Path(args.output).write_text(out, encoding="utf-8")
        except OSError as exc:
            print(f"generate_cascade_evidence FATAL: cannot write {args.output}: {exc}",
                  file=sys.stderr)
            exit_code = EXIT_FATAL

    # Per reviewer 🟡 IMPROVE: emit audit row with ACTUAL exit code so forensic
    # audit captures file-write failures (previously hardwired to EXIT_SUCCESS).
    if not args.no_audit:
        _emit_audit_row(cls, exit_code)

    return exit_code


def main() -> None:
    sys.exit(cli_main())


if __name__ == "__main__":
    main()
