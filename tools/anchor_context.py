"""Shared empirical-anchor context detection.

Per B-491 + B-496 bundled closure 2026-05-18 — extracted from
`tools/check_commit_msg.py` (B-488 original closure) to enable reuse across
`tools/pre_commit_checks.py` Phase 1 quality checks that have the same
self-firing-on-historical-citation class:

- `check_wc_line_count_claims` (B-481 9th check) — fires on historical wc -l
  citations in BACKLOG.md / _validation_log.md narrative entries
- `check_file_path_existence` (B-495 10th check) — fires on historical path
  citations in _validation_log.md narrative entries pointing to renamed /
  moved / never-built paths

Empirical evidence base (2-event 2026-05-18 — B-491 + B-496 simultaneous
deferral patterns reached the HANDOFF §8 formalization threshold; this module
operationalizes the canonical resolution via shared-helper extraction).

The original B-488 closure introduced this helper at `check_commit_msg.py`
for 3 CommitMsgCheck subclasses (ClosureAnnotationConsistencyCheck +
NarrativePytestClaimVerificationCheck + latent InlineFixClaimVerificationCheck
extension). This module preserves all prior call-site contracts via
back-compatible aliases at `tools/check_commit_msg.py`.
"""
from __future__ import annotations


# Canonical 18-marker set per B-488 closure 2026-05-18. Case-sensitive — both
# common case variants included explicitly. Forward-extensible: new markers
# appended as empirical evidence accumulates.
EMPIRICAL_ANCHOR_MARKERS: tuple[str, ...] = (
    "empirical anchor commit",
    "empirical anchor",
    "1st-event empirical anchor",
    "1st-event",
    "META-IRONY",
    "meta-irony",
    "historical reference",
    "historical context",
    "historical anchor",
    "Quote-cite from reviewer",
    "quote-cite from reviewer",
    "Mechanism A step 5",
    "per Cohort",
    "per cohort",
    "verbatim quote",
    "reviewer quote",
    "Reviewer cited",
    "reviewer cited",
)


def is_empirical_anchor_context(
    lines: list[str], idx: int, lookback: int = 5,
) -> bool:
    """True if `lines[idx]` is within an empirical-anchor citation context.

    Scans `lines[idx-lookback:idx+1]` for any marker phrase from
    `EMPIRICAL_ANCHOR_MARKERS`. Returns True if found (suppression should
    apply); False otherwise.

    Used to suppress false-positive WARNs across heuristic checks when the
    matching content cites historical pattern instances rather than asserting
    current-commit claims.

    Empirical evidence base (5+ events 2026-05-18 across both check_commit_msg
    and pre_commit_checks layers):
        - commit 133b212: B-458 fired on `**B-414 CLOSED**` inside REVIEW-section
          quote-cite of prior reviewer's verdict (B-480 absorbed via B-488)
        - commit c6ba969: B-464 fired on `2664 pass / 62 skip / 0 fail` inside
          empirical-anchor prose citing 1f74b72 META-IRONY (B-487 absorbed via B-488)
        - commit c781c9b: check_wc_line_count_claims fired on 3 historical wc -l
          citations in BACKLOG.md (B-491 deferred-then-bundled)
        - commit 2ac353b: check_file_path_existence fired on 37 historical path
          citations in _validation_log.md (B-496 deferred-then-bundled)

    Args:
        lines: split content lines (commit-msg OR staged markdown file).
        idx: target line index to evaluate (0-based).
        lookback: number of lines BEFORE idx to scan for markers (default 5).

    Returns:
        True if any line in `lines[idx-lookback:idx+1]` contains an empirical
        anchor marker (case-sensitive match against EMPIRICAL_ANCHOR_MARKERS).
        False otherwise. Note: case-sensitive — EMPIRICAL_ANCHOR_MARKERS
        includes both common case variants explicitly.
    """
    if idx < 0 or idx >= len(lines):
        return False
    lo = max(0, idx - lookback)
    window = lines[lo:idx + 1]
    for line in window:
        for marker in EMPIRICAL_ANCHOR_MARKERS:
            if marker in line:
                return True
    return False
