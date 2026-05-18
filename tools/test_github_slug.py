"""Test GitHub heading-slug generation for the §13.4 em-dash assumption.

Implements the GitHub heading-slug algorithm locally and tests 5 heading
variants surfaced by Q-22 (per `docs/migration/MARKDOWN_REFACTOR_PLAN.md`
§13.4 + §15.4 + Q2 cross-ref-maintenance research artifact).

Algorithm reference: ``github-slugger`` npm package
(https://github.com/Flet/github-slugger), the canonical port of GitHub's
internal slug logic. The character class kept by github-slugger is the
Unicode regex ``[^\\p{L}\\p{N}\\p{M}\\p{Pd}_ ]`` — i.e. KEEP letters,
numbers, marks, dash-punctuation, underscore, and ASCII space; STRIP
everything else. After stripping, ASCII spaces are replaced by single
hyphens (consecutive hyphens are NOT collapsed).

Critical: ``\\p{Pd}`` (Unicode Dash punctuation) INCLUDES em-dash
(U+2014), en-dash (U+2013), and other dashes. They survive the strip
pass and appear LITERALLY in the slug. The §13.4 assumption that
``D15 — Title`` produces ``d15-title`` is FALSE — the actual slug is
``d15-—-title`` with a literal em-dash between hyphens.

Stdlib-only (no `regex` package needed): we use ``unicodedata.category``
to test each char against L*/N*/M*/Pd categories instead of Unicode
property regex escapes.

Usage:
    py tools/test_github_slug.py
"""

import unicodedata


def is_kept_char(ch: str) -> bool:
    """True iff `ch` survives github-slugger's strip pass."""
    if ch == "_" or ch == " ":
        return True
    cat = unicodedata.category(ch)
    if cat[0] in ("L", "N", "M"):  # Letter / Number / Mark
        return True
    if cat == "Pd":  # Dash punctuation (incl. em/en/ASCII hyphen)
        return True
    return False


def github_slug(heading_text: str) -> str:
    """Compute the GitHub heading anchor slug for `heading_text`.

    Mirrors ``github-slugger`` v2.x ``slug()`` behavior (without the
    duplicate-counter that increments slugs to slug-1 / slug-2 within a
    single document — that's a stateful concern, irrelevant here).
    """
    s = heading_text.lower()
    s = "".join(ch for ch in s if is_kept_char(ch))
    s = s.replace(" ", "-")
    return s


CASES = [
    ("em-dash U+2014", "D15 — Idempotency Ledger"),
    ("en-dash U+2013", "D15 – Idempotency Ledger"),
    ("ASCII hyphen U+002D", "D15 - Idempotency Ledger"),
    ("colon", "D15: Idempotency Ledger"),
    ("period", "D15. Idempotency Ledger"),
]
ASSUMED_SLUG = "d15-idempotency-ledger"
PREFIX = "d15"


def main() -> None:
    print("GitHub heading-slug test (§13.4 / Q-22)")
    print(f"Assumed slug per §13.4:  {ASSUMED_SLUG!r}")
    print(f"Prefix-cite assumption:  starts with {PREFIX!r}")
    print()
    print(
        f"{'Case':<24}{'Heading':<40}{'Slug':<44}"
        f"{'#d15-prefix?':<14}{'==assumed?'}"
    )
    print("-" * 130)
    for label, heading in CASES:
        slug = github_slug(heading)
        prefix_ok = slug.startswith(PREFIX)
        equals_ok = slug == ASSUMED_SLUG
        print(
            f"{label:<24}{heading!r:<40}{slug!r:<44}"
            f"{('YES' if prefix_ok else 'NO'):<14}{'YES' if equals_ok else 'NO'}"
        )


if __name__ == "__main__":
    main()
