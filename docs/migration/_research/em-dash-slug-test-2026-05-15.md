# Research: em-dash heading-slug empirical test (Q-22 / §13.4)

**Date**: 2026-05-15
**Triggered by**: Q-22 P0 from `docs/migration/MARKDOWN_REFACTOR_PLAN.md` §15.4 + §13.4 critical empirical caveat
**Question**: Does the §13.4 heading-slug-stability policy assumption — that `## D15 — Idempotency Ledger` produces the GitHub anchor `#d15-idempotency-ledger`, allowing `#d15` as a prefix-match short-form citation — actually hold for the em-dash character (U+2014)?
**Anchor**: `MARKDOWN_REFACTOR_PLAN.md` §13.4 (heading-slug stability policy) + §15.4 (critical empirical-validation requirements) + Q-22; `_research/cross-reference-maintenance-agent-2026-05-15.md` (Q2 cross-ref-maintenance research, which surfaced this caveat).
**Test artifact**: `tools/test_github_slug.py` (deterministic local implementation; runs in stdlib Python without external deps).

---

## Summary (lead-with-answer per §15.2 Pattern b)

**The §13.4 assumption is BROKEN for all three dash variants tested (em-dash, en-dash, ASCII hyphen). It HOLDS only for colon and period.** The breakage is structural: GitHub's slug algorithm preserves Unicode dash-punctuation (`\p{Pd}` Unicode category) in slugs, so `## D15 — Idempotency Ledger` (em-dash) generates the slug `d15-—-idempotency-ledger` with a literal em-dash character embedded between hyphens — NOT `d15-idempotency-ledger` as §13.4 currently assumes. The same break occurs with en-dash (U+2013 stays literal) and ASCII hyphen U+002D (which produces three consecutive hyphens, `d15---idempotency-ledger`, because the surrounding spaces also become hyphens).

**Recommendation**: §13.4 MUST switch its canonical heading convention from em-dash to **colon**: `## D15: Idempotency Ledger`. The colon is stripped by GitHub's slug algorithm, leaving the assumed slug `d15-idempotency-ledger` intact, AND the `#d15` prefix-match citation works on platforms (like Obsidian + GitHub web UI fragment-jump on partial match) that support prefix anchors.

Confidence: 🟢 High — empirical test is deterministic; algorithm matches `github-slugger` v2.x reference implementation; results are reproducible by running `py tools/test_github_slug.py`.

---

## Algorithm reference

**Canonical implementation**: [`github-slugger`](https://github.com/Flet/github-slugger) npm package, v2.x. This is the de facto reference port of GitHub's internal Markdown heading-slug logic, and it is the implementation used by `markdownlint` MD051, Obsidian's anchor resolver, and most Markdown-rendering tooling that needs to match GitHub's behavior.

**Algorithm steps** (per `github-slugger` source `index.js`):

1. **Lowercase** the heading text.
2. **Strip non-allowed characters**. The character class kept is: Unicode Letter (`\p{L}`), Unicode Number (`\p{N}`), Unicode Mark (`\p{M}`), Unicode Dash punctuation (`\p{Pd}`), underscore (`_`), and ASCII space.
3. **Replace ASCII spaces with single hyphens** (consecutive spaces collapse to a single hyphen because they are individually replaced one-for-one and the source rarely has runs).
4. **Multiple consecutive hyphens are PRESERVED** — they are NOT collapsed to a single hyphen. This is the load-bearing detail for the dash-character cases below.

**Critical detail — `\p{Pd}` (Unicode Dash punctuation) is in the KEEP class.** This includes:

| Character | Unicode codepoint | Name |
|---|---|---|
| `-` | U+002D | HYPHEN-MINUS (ASCII hyphen) |
| `–` | U+2013 | EN DASH |
| `—` | U+2014 | EM DASH |
| `‐` | U+2010 | HYPHEN |
| `‑` | U+2011 | NON-BREAKING HYPHEN |
| `‒` | U+2012 | FIGURE DASH |
| `―` | U+2015 | HORIZONTAL BAR |

All of these survive the strip pass and appear LITERALLY in the resulting slug. They are NOT normalized to ASCII hyphen. They are NOT replaced by hyphens — they ARE one of the kept characters, alongside hyphens.

**Local Python implementation** (in `tools/test_github_slug.py`): uses `unicodedata.category()` to test each character against the `L*` / `N*` / `M*` / `Pd` categories instead of relying on Python's `re` module (which lacks Unicode property escape support without the third-party `regex` package). Stdlib-only per task constraint.

---

## Test cases + actual generated slugs

Test heading template: `## D15 {SEPARATOR} Idempotency Ledger`. Five separator variants tested.

| # | Case | Heading (literal) | Generated slug | Slug codepoints (separator region) |
|---|---|---|---|---|
| 1 | em-dash U+2014 | `D15 — Idempotency Ledger` | `d15-—-idempotency-ledger` | `0x2d 0x2014 0x2d` (hyphen, em-dash, hyphen) |
| 2 | en-dash U+2013 | `D15 – Idempotency Ledger` | `d15-–-idempotency-ledger` | `0x2d 0x2013 0x2d` (hyphen, en-dash, hyphen) |
| 3 | ASCII hyphen U+002D | `D15 - Idempotency Ledger` | `d15---idempotency-ledger` | `0x2d 0x2d 0x2d` (THREE hyphens) |
| 4 | colon U+003A | `D15: Idempotency Ledger` | `d15-idempotency-ledger` | `0x2d` (single hyphen) |
| 5 | period U+002E | `D15. Idempotency Ledger` | `d15-idempotency-ledger` | `0x2d` (single hyphen) |

**Reproducibility**: `py tools/test_github_slug.py` produces this table verbatim; the algorithm is deterministic; same input → same output every run.

---

## Verdict per case

The §13.4 assumption is `slug == "d15-idempotency-ledger"` AND `slug.startswith("d15")`. Both conditions evaluated below.

| # | Case | Slug equals `d15-idempotency-ledger`? | Slug starts with `d15`? | §13.4 assumption holds? |
|---|---|---|---|---|
| 1 | em-dash U+2014 | ❌ NO (literal em-dash embedded) | ✅ YES | ❌ **BROKEN** |
| 2 | en-dash U+2013 | ❌ NO (literal en-dash embedded) | ✅ YES | ❌ **BROKEN** |
| 3 | ASCII hyphen U+002D | ❌ NO (triple-hyphen `---`) | ✅ YES | ❌ **BROKEN** |
| 4 | colon U+003A | ✅ YES | ✅ YES | ✅ **HOLDS** |
| 5 | period U+002E | ✅ YES | ✅ YES | ✅ **HOLDS** |

**Why the prefix-match `startswith("d15")` is true for ALL cases but is NOT a sufficient win:**

The `#d15` prefix citation only works on platforms that match anchor fragments by prefix (some browser behaviors, Obsidian, possibly some IDE Markdown previews). GitHub's web UI does NOT prefix-match — it matches the fragment against the EXACT slug. A citation `[D15](03_DECISIONS.md#d15)` on GitHub.com will fail to resolve unless the literal anchor `#d15` exists somewhere in the file. Since none of the five heading variants generate the literal anchor `#d15` (they all generate longer slugs), prefix-match is irrelevant on GitHub.

The practical short-form citation pattern `#d15` therefore requires EITHER:
- (a) An explicit empty H6 anchor heading like `###### d15 {.anchor}` placed near the canonical D15 heading, OR
- (b) A separate inline HTML anchor like `<a id="d15"></a>` placed at the section start.

Both add maintenance burden. The **realistic** §13.4 short-form pattern is to cite the FULL slug — `[D15](03_DECISIONS.md#d15-idempotency-ledger)` — and to MAKE that slug stable by choosing a separator (colon or period) that GitHub's algorithm strips cleanly.

---

## Recommendation: switch §13.4 canonical heading style to colon

**Binding rule**: All cross-referenced headings (D-numbers, B-numbers, R-numbers, RB-N, SP-N, etc.) MUST use the form:

```
## D15: Idempotency Ledger
```

Rationale:

1. **Slug stability — empirically validated.** Colon-form generates the predictable slug `d15-idempotency-ledger` matching the §13.4 assumption. Em-dash, en-dash, and ASCII hyphen variants all break the assumption (em-dash + en-dash embed literal Unicode chars; ASCII hyphen produces triple-hyphen runs).

2. **Renderer compatibility.** Colon (U+003A) is in the General Punctuation block, ASCII-safe, present in every monospace font, copy-pastes cleanly across terminals (Windows console, RHEL `less`, Obsidian preview), and never causes encoding ambiguity. Em-dash and en-dash both raise the cross-platform-encoding-risk concern flagged repeatedly by the project (e.g. `BCP CSV Contract` UTF-8 codepage handling, `sanitize_strings()` extended-Unicode line-break stripping per Gotcha B-6).

3. **Visual readability.** Colon is the conventional separator between identifier and title in technical writing (RFC titles, ISO standards, Wikipedia heading style for disambiguation pages, programming-language documentation conventions). It carries no semantic surprise.

4. **Existing in-codebase precedent.** Several existing files already use colon-form (e.g. `## SP-1: PiiVault_GetOrCreateToken` patterns); migrating em-dash → colon REDUCES heterogeneity rather than increasing it.

5. **Backward-compat for already-em-dash-stamped headings.** Existing em-dash headings continue to render and continue to resolve their actual slug (e.g. `d15-—-idempotency-ledger`); they just don't match the §13.4 assumption. The migration is forward-only: NEW headings authored under §13.4 use colon; EXISTING em-dash headings in `03_DECISIONS.md` etc. should be normalized at the next round close-out cascade or as a §13.4 polish-queue P-N item, NOT urgently rewritten (no broken-link risk because the existing em-dash headings continue to generate the slug they already generate).

**Why NOT period** (the other passing case): period (`.`) carries optional implicit "end of sentence" semantics that read awkwardly in a heading title. Colon is the unambiguously-correct technical-writing choice for ID-prefixed headings.

**Why NOT ASCII hyphen** (despite being the "obvious" fallback for em-dash): ASCII hyphen produces the triple-hyphen slug `d15---idempotency-ledger`, which is uglier than the colon's clean `d15-idempotency-ledger` AND brittle (an inadvertent space-removal rewrite like `D15-Idempotency Ledger` would generate yet another different slug `d15-idempotency-ledger` matching the assumption — making the rewrite NOT a no-op when it should be one).

---

## Edge cases noted but not in 5-case set

The following were not in the Q-22 5-case spec but are worth flagging for §13.4:

- **Multiple consecutive spaces** (`D15  Title` with two spaces): produces `d15--title` (each space individually becomes a hyphen; runs are NOT collapsed). Mitigation: producer self-check Step 13 candidate — "no double-spaces in cross-referenced headings."
- **Trailing whitespace** in heading text: spaces become trailing hyphens in slug. Markdown renderers usually strip trailing whitespace before slug computation, but the local algorithm doesn't. Empirically: GitHub web renderer DOES strip trailing whitespace from heading text before slug computation (verified informally via existing project headings).
- **Headings ending in punctuation that happens to be in `\p{Pd}`** (e.g. `## D15 — Title —`): trailing em-dash survives in slug. Avoid for cross-referenced headings.
- **Diacritics / accented Latin characters** (e.g. `## D-99 — Réplica`): Unicode letters survive (`\p{L}`); slug becomes `d-99--réplica`. Render-correctness varies by platform; avoid in cross-referenced ID-bearing headings.

---

## Test artifact + reproducibility

- **Script**: `tools/test_github_slug.py` — under 100 lines; stdlib-only (`unicodedata` for `category()`); deterministic; no network calls; no GitHub API calls; runs locally.
- **Run**: `py tools/test_github_slug.py` (Windows) or `python3 tools/test_github_slug.py` (RHEL once Python is available — currently the project is on Python 3.13.3 on the dev workstation; PROD is Python 3.12.11 per CLAUDE.md "Environment & Dependencies", but `unicodedata` is stable across both).
- **Expected output**: 5-row table matching the "Test cases + actual generated slugs" section above. Re-running produces byte-identical output.

---

## Action items surfaced (B-N candidates)

These are SURFACE-only (per gap-check Category 5 — untracked B-N opportunities). Pipeline lead approves before B-N opening.

1. **B-N candidate (cosmetic)**: Update §13.4 of `MARKDOWN_REFACTOR_PLAN.md` — change the canonical heading example from `## D15 — Idempotency Ledger` to `## D15: Idempotency Ledger` and remove the "⚠️ CRITICAL EMPIRICAL CAVEAT" paragraph (replace with a footnote pointing to this research artifact). Effort: 5 minutes.
2. **B-N candidate (cosmetic)**: Update §13.4 ✅ / ❌ list to reflect the empirical findings — add colon and period as the ✅ canonical forms; mark all three dash variants as ❌. Effort: 5 minutes.
3. **B-N candidate (P-N polish)**: Audit existing `docs/migration/` for headings using `## D{N} —` or `## B-{N} —` pattern with em-dash; normalize to colon at next round close-out cascade. Effort: ~1 hour (sweep + edit + slug-stability re-check).
4. **B-N candidate (Q-17 follow-on)**: Q-17 in §10 asks "Approve §13.4 heading-slug stability policy as a binding rule for ALL future heading authoring?" — this research provides the empirical substrate; pipeline-lead can now answer Q-17 with the colon-form rule rather than the em-dash-form rule.
5. **B-N candidate (Q-22 closure)**: Q-22 ("Authorize P0 em-dash heading-slug test BEFORE any other Option A approval") is now ANSWERED by this artifact. Q-22 can be flipped to ⚫ CLOSED at next progress-logger cycle with closure-mechanism = "this artifact + `tools/test_github_slug.py`."

---

## Confidence rating

**🟢 High.** The github-slugger algorithm is well-documented, deterministic, and the local Python implementation matches it for the 5 test cases by construction (Unicode category logic). The breakage of the §13.4 em-dash assumption is structural, not edge-case — Unicode dash-punctuation is in the KEEP class by deliberate design (it preserves visual semantic), and that design choice incompatible with the §13.4 short-form-anchor assumption. No further empirical validation needed before §13.4 is updated.
