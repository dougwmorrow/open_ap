"""Single source of truth for hard-rule-14 cascade exemption-claim trigger phrases.

Canonical Python module providing `EXEMPTION_TRIGGER_PHRASES` constant per
B-309 closure (2026-05-16 critical-review Cycle 1; deduplicate previously
4-way-duplicated list across SKILL.md + commit-msg hook + 2 test files;
Pitfall #9.k arithmetic-propagation drift mitigation).

Consumed by:
- `.githooks/commit-msg` (Mechanism C-1 exemption-phrase BLOCK check)
- `tests/tier0/test_commit_msg_hook.py` (verifies hook uses the canonical list)
- `tests/tier0/test_exemption_phrases_sync.py` (NEW; verifies SKILL.md matches)

Authoritative reference (documentation): `.claude/skills/udm-exemption-verifier/SKILL.md`
L29-46. If this Python constant diverges from SKILL.md, the sync test fails.

To add a new trigger phrase: edit BOTH this file AND SKILL.md L29-46. The sync
test catches half-updates.

Empirical pattern: at instance 6/7/8 of Pitfall #9.o, parent claimed cascade
exemption via varied rationalizations. Trigger phrases catch these claims at
commit-msg-hook time via mechanical substring match.
"""
from __future__ import annotations

EXEMPTION_TRIGGER_PHRASES: tuple[str, ...] = (
    # Verbatim phrases per SKILL.md L29-36 (8 original)
    "Layer N+1 termination",
    "recursive-exemption",
    "verbatim implementation",
    "100% overlap on architectural-decision-substance",
    "specific scope-justified exemption",
    "REVIEW: SKIPPED",
    "no new architecture introduced",
    "implementing prior reviewer's recommendation",
    # B-303 structured-pattern extensions per SKILL.md L37-41 (4)
    "EXEMPTION VALID",
    "step 6: N/A",
    "cannot fire on commits modifying its own SKILL.md",
    "self-exemption clause applies",
)


def contains_exemption_phrase(text: str) -> list[str]:
    """Return list of trigger phrases found in `text` (case-insensitive).

    Returns empty list if no matches.
    """
    if not text:
        return []
    matched = []
    text_lower = text.lower()
    for phrase in EXEMPTION_TRIGGER_PHRASES:
        if phrase.lower() in text_lower:
            matched.append(phrase)
    return matched
