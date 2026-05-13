"""R-2 autoconfig: propose ``UdmTablesList`` SCD2 values from column names.

Manual per-table configuration across 200+ DNA tables plus CCM / EPICOR is
untenable. Most DNA tables follow the same convention (``DATELASTMAINT`` in
every table, ``INACTIVEDATE`` on association tables, ``ADDDATE`` on entity
tables, ``EFFDATE`` on relationship tables, etc.) — the legacy
``GenerateTableSCD2`` proc calls bear this out. This module encodes those
conventions as source-scoped ``SourceProfile`` objects and derives column-
presence-driven proposals.

Design
------

Each source has a ``SourceProfile`` listing the conventions that apply to
it. The ``propose_config`` function takes a column-name set from a single
table and emits a proposed ``UdmTablesList`` config dict — one field per
config column, values formatted for direct INSERT/UPDATE.

The tool at ``tools/detect_scd2_config.py`` composes this with actual
``UdmTablesColumnsList`` rows and writes proposals to a review table for
operator sign-off.

Rules apply in this order of precedence:

  * Manual override in ``UdmTablesList`` wins. Autoconfig never overwrites
    an explicit non-NULL value.
  * Per-source ``SourceProfile`` supplies conventions for known sources.
  * The ``GENERIC_FALLBACK`` profile covers universal rules (``DATELASTMAINT``
    hash exclusion, ``'1900-01-01'`` default begin date).
  * Anything not covered stays NULL and requires manual configuration.

Adding a new source
-------------------

Create a new ``SourceProfile`` entry in ``PROFILES`` (even if empty — the
GENERIC_FALLBACK still applies for universal conventions). As you learn the
source's naming conventions from manual configs, migrate them into the
profile and re-run ``detect_scd2_config.py`` — preserved manual overrides
keep their values; tables without explicit config pick up the new defaults.

CAVEAT
------

Proposals from this module are *suggestions*. The CLI tool writes them to
``General.dbo.UdmScd2ConfigProposal`` with a review status (PENDING /
APPROVED / REJECTED) and a ``--apply`` flag copies only APPROVED rows into
``UdmTablesList``. Autoconfig never writes to ``UdmTablesList`` directly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SourceProfile:
    """Conventions for a single source system.

    Attributes:
        source_name: Matches ``UdmTablesList.SourceName`` (e.g. ``'DNA'``).
        hash_exclude_columns: Columns to put in ``ExcludeFromHash`` when
            present in the table. Ordered list — output preserves order for
            readability. ``DATELASTMAINT`` is the archetype: updated on
            every source touch, produces phantom CDC updates if hashed.
        waterfall_candidates: Ordered priority list for ``SCD2DateColumns``.
            Autoconfig picks the first ``waterfall_max`` that exist in the
            table. Primary (position 0) drives the effective date; later
            entries are tie-breakers.
        waterfall_max: Cap on the number of waterfall columns emitted.
            Legacy proc calls usually use 1–3.
        delete_date_candidates: Ordered list for ``SourceDeleteDateColumn``.
            First match wins (typically ``INACTIVEDATE`` on DNA).
        duplicate_resolution_cols: Ordered list for
            ``DuplicateResolutionOrder``. Output includes only columns that
            exist in the table; ``UdmEffectiveDateTime`` is always appended
            when the policy calls for it (it's a UDM column, always present
            post-SCD2).
        last_modified_candidates: Ordered list for ``LastModifiedColumn``.
            First match wins. Drives the modified-date sweep — None means
            no sweep for tables in this source.
        default_begin_date: Output for ``DefaultBeginDate`` (ISO date).
    """

    source_name: str
    hash_exclude_columns: list[str] = field(default_factory=list)
    waterfall_candidates: list[str] = field(default_factory=list)
    waterfall_max: int = 3
    delete_date_candidates: list[str] = field(default_factory=list)
    duplicate_resolution_cols: list[str] = field(default_factory=list)
    last_modified_candidates: list[str] = field(default_factory=list)
    default_begin_date: str = "1900-01-01"


# ---------------------------------------------------------------------------
# Source-specific profiles. Conventions captured from the legacy
# GenerateTableSCD2 proc call corpus.
# ---------------------------------------------------------------------------

_DNA_PROFILE = SourceProfile(
    source_name="DNA",
    # Only DATELASTMAINT is confirmed universal. Per-table extras
    # (DATELASTCONTACT, NEXT*NBR, etc. on ACCT) stay manual — no reliable
    # signal to auto-detect without behavioral data.
    hash_exclude_columns=["DATELASTMAINT"],
    # Priority list observed across legacy proc calls:
    #   * Entity tables (PERS, ORG): ADDDATE -> DATELASTMAINT
    #   * Association tables (ACCTACCTROLEPERS, PERSWRN): EFFDATE
    #   * Account tables (ACCT): CONTRACTDATE -> DATELASTCONTACT -> DATELASTMAINT
    # Autoconfig emits the first 2-3 that exist. ACCT's three-column
    # waterfall emerges naturally because all three columns are present.
    waterfall_candidates=[
        "ADDDATE",
        "EFFDATE",
        "CONTRACTDATE",
        "DATELASTCONTACT",
        "DATELASTMAINT",
    ],
    waterfall_max=3,
    # INACTIVEDATE observed on ACCTACCTROLEPERS, ACCTACCTROLEORG, PERSWRN,
    # ORGWRN — populated when the row is soft-deleted at source.
    delete_date_candidates=["INACTIVEDATE"],
    duplicate_resolution_cols=["DATELASTMAINT", "UdmEffectiveDateTime"],
    # Modified-date sweep candidate. DATELASTMAINT is updated on every
    # source touch — exactly the signal we need to detect rows updated
    # outside the LookbackDays window.
    last_modified_candidates=["DATELASTMAINT"],
    default_begin_date="1900-01-01",
)


# CCM — conventions TBD. CCM uses physical purges rather than soft deletes,
# so delete_date_candidates stays empty (ExpectedRetentionDays handles the
# age-based purge case). As manual configs accumulate, migrate the observed
# column names into this profile.
_CCM_PROFILE = SourceProfile(
    source_name="CCM",
    hash_exclude_columns=[],  # TBD — add as patterns emerge
    waterfall_candidates=[],  # TBD
    waterfall_max=3,
    delete_date_candidates=[],  # CCM uses purges, not soft deletes
    duplicate_resolution_cols=["UdmEffectiveDateTime"],
    default_begin_date="1900-01-01",
)


# EPICOR — conventions unknown. User direction was to mimic DNA patterns
# until evidence shows otherwise. Start with an empty profile so nothing is
# falsely inferred — manual config fills the gap until patterns are known.
_EPICOR_PROFILE = SourceProfile(
    source_name="EPICOR",
    hash_exclude_columns=[],
    waterfall_candidates=[],
    waterfall_max=3,
    delete_date_candidates=[],
    duplicate_resolution_cols=["UdmEffectiveDateTime"],
    default_begin_date="1900-01-01",
)


# Generic fallback for sources without a profile. Covers the universal
# conventions that apply regardless of source:
#   * DATELASTMAINT-style updated-timestamp columns need hash exclusion.
#     (Included only if the table actually has DATELASTMAINT — the rule
#     is column-presence gated in propose_config.)
#   * 1900-01-01 is a reasonable default begin date sentinel.
GENERIC_FALLBACK = SourceProfile(
    source_name="_generic",
    hash_exclude_columns=["DATELASTMAINT"],
    waterfall_candidates=[],
    waterfall_max=3,
    delete_date_candidates=[],
    duplicate_resolution_cols=["UdmEffectiveDateTime"],
    default_begin_date="1900-01-01",
)


PROFILES: dict[str, SourceProfile] = {
    "DNA": _DNA_PROFILE,
    "CCM": _CCM_PROFILE,
    "EPICOR": _EPICOR_PROFILE,
}


def get_profile(source_name: str) -> SourceProfile:
    """Return the profile for ``source_name``, falling back to generic.

    Case-insensitive lookup. Unknown sources get ``GENERIC_FALLBACK``.
    """
    return PROFILES.get(source_name.upper(), GENERIC_FALLBACK)


# ---------------------------------------------------------------------------
# Proposal computation
# ---------------------------------------------------------------------------


def _filter_existing(candidates: list[str], available: set[str]) -> list[str]:
    """Return ``candidates`` in order, keeping only those in ``available``.

    Case-sensitive — source systems use consistent casing per source
    (Oracle uppercase, SQL Server per-schema). Mismatches are usually
    real typos in the profile, so we surface them via the detect tool
    rather than silently doing case-insensitive matches.
    """
    return [c for c in candidates if c in available]


def _csv(values: list[str]) -> str | None:
    """Join a list to a comma-separated string, or return None if empty."""
    return ",".join(values) if values else None


def propose_config(
    source_name: str,
    column_names: set[str],
) -> dict[str, str | None]:
    """Derive a proposed ``UdmTablesList`` config for one table.

    Args:
        source_name: Value from ``UdmTablesList.SourceName``.
        column_names: Set of column names present in the table (from
            ``UdmTablesColumnsList`` Stage rows, post column-sync).

    Returns:
        Dict keyed by ``UdmTablesList`` column name. Values are either
        strings (as they will appear in the SQL UPDATE) or None when the
        profile has nothing to propose. The CLI writes this dict to the
        proposal table verbatim.
    """
    profile = get_profile(source_name)

    # Hash exclude: profile columns that exist, falling through to
    # GENERIC_FALLBACK rules if the profile is empty.
    hash_exclude = _filter_existing(profile.hash_exclude_columns, column_names)
    if not hash_exclude and profile is not GENERIC_FALLBACK:
        hash_exclude = _filter_existing(GENERIC_FALLBACK.hash_exclude_columns, column_names)

    # Waterfall: first waterfall_max matches from the profile.
    waterfall = _filter_existing(profile.waterfall_candidates, column_names)[: profile.waterfall_max]

    # Delete-date: first matching candidate from the profile.
    delete_date = _filter_existing(profile.delete_date_candidates, column_names)
    delete_date_value = delete_date[0] if delete_date else None

    # Duplicate resolution: start from profile cols, keeping only those that
    # exist in the table OR are UDM columns (UdmEffectiveDateTime is always
    # present post-SCD2, so we keep it unconditionally).
    dup_cols = []
    for col in profile.duplicate_resolution_cols:
        if col in column_names or col.startswith("Udm"):
            dup_cols.append(col)

    last_modified = _filter_existing(profile.last_modified_candidates, column_names)
    last_modified_value = last_modified[0] if last_modified else None

    proposed = {
        "ExcludeFromHash": _csv(hash_exclude),
        "SCD2DateColumns": _csv(waterfall),
        "SourceDeleteDateColumn": delete_date_value,
        "DuplicateResolutionOrder": _csv(dup_cols),
        "DefaultBeginDate": profile.default_begin_date,
        "LastModifiedColumn": last_modified_value,
    }

    logger.debug(
        "autoconfig %s: source=%s proposed=%s",
        sorted(column_names)[:5] + ["..."] if len(column_names) > 5 else sorted(column_names),
        source_name,
        proposed,
    )
    return proposed


__all__ = [
    "SourceProfile",
    "PROFILES",
    "GENERIC_FALLBACK",
    "get_profile",
    "propose_config",
]
