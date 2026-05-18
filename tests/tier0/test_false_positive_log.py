"""Tier 0 build-time smoke test for `docs/migration/_false_positive_log.md` per B-489 closure.

Pins canonical structure + initial 4-event corpus against silent regression.
Authored 2026-05-18 per B-489 closure (Layer 3 of false-positive prevention
architecture; accumulation tracker parallel to _validation_log.md +
_reviewer_effectiveness.md).
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LOG_PATH = REPO_ROOT / "docs" / "migration" / "_false_positive_log.md"


def test_false_positive_log_exists():
    """B-489 Assertion 1: _false_positive_log.md exists at canonical path."""
    assert LOG_PATH.is_file(), (
        f"Expected _false_positive_log.md at {LOG_PATH}. "
        f"Layer 3 of false-positive prevention architecture per B-489 closure."
    )


def test_false_positive_log_required_sections_present():
    """B-489 Assertion 2: required canonical section headers present.

    Pins the structural sections that future close-out cascade walks +
    aggregation discipline depends on."""
    content = LOG_PATH.read_text(encoding="utf-8")
    required_sections = [
        "# False-Positive Event Log",
        "## Purpose",
        "## When to log an event",
        "## Schema",
        "## Aggregation discipline",
        "## Composition with other discipline layers",
        "## Initial event corpus",
        "## Aggregation findings",
    ]
    for section in required_sections:
        assert section in content, (
            f"_false_positive_log.md missing required section header: {section!r}. "
            f"This structure is the contract that round close-out cascade walks "
            f"+ aggregation discipline depends on."
        )


def test_false_positive_log_initial_corpus_4_events():
    """B-489 Assertion 3: initial event corpus contains all 4 historical events
    seeded at B-489 closure (FP-1 through FP-4). Pins the empirical evidence
    base against silent removal."""
    content = LOG_PATH.read_text(encoding="utf-8")
    required_event_ids = ["FP-1", "FP-2", "FP-3", "FP-4"]
    for event_id in required_event_ids:
        assert event_id in content, (
            f"_false_positive_log.md missing initial event {event_id!r}. "
            f"All 4 historical events from 2026-05-18 must be preserved "
            f"per B-489 closure empirical-evidence-base discipline."
        )


def test_false_positive_log_canonical_classes_present():
    """B-489 Assertion 4: canonical false-positive classes documented + each
    has forward-prevention status cited. Pins the aggregation findings
    against silent erosion."""
    content = LOG_PATH.read_text(encoding="utf-8")
    canonical_classes = [
        "self-reference meta-pattern",
        "reviewer-methodology blind-spot",
        "Pitfall #9.h",
    ]
    for cls in canonical_classes:
        assert cls in content, (
            f"_false_positive_log.md missing canonical false-positive class: {cls!r}"
        )
    # Forward-prevention B-N references for the 3 classes:
    forward_prevention_bns = ["B-488", "B-490", "B-481"]
    for bn in forward_prevention_bns:
        assert bn in content, (
            f"_false_positive_log.md missing forward-prevention B-N reference: {bn!r}"
        )


def test_false_positive_log_schema_fields_documented():
    """B-489 Assertion 5: canonical 7-field schema documented (event_date /
    check_name / trigger_pattern / actual_semantic / empirical_anchor_commit /
    detected_by / remediation_status / forward_prevention_B_N / class).
    Pins the schema contract that future event additions follow."""
    content = LOG_PATH.read_text(encoding="utf-8")
    schema_fields = [
        "trigger_pattern",
        "actual_semantic",
        "empirical_anchor_commit",
        "detected_by",
        "remediation_status",
        "forward_prevention_B_N",
        "class",
    ]
    for field in schema_fields:
        assert f"**{field}**" in content, (
            f"_false_positive_log.md schema missing canonical field: {field!r}"
        )
