# Research: Cross-Reference Maintenance Agent for Markdown Repositories

**Date**: 2026-05-15
**Triggered by**: on-demand (user request — follow-on to `agent-discoverability-2026-05-15.md`)
**Question**: Can a dedicated agent keep cross-reference links continuously up to date — not just at split-time but as a background monitor, broken-link detector, safe-case fixer, and uncertainty surfacer? What design shape fits the UDM project best?
**Anchor**: MARKDOWN_REFACTOR_PLAN.md §13.3 (Navigation Paradox cross-reference preservation MANDATORY constraint); `tools/verify_cascade.py` (Pattern F Trigger D forward-cite resolution); D62 (CCL doctrine); B17 (cross-reference audit tool backlog item); Operationally stable pillar; Traceability pillar.
**Follow-on to**: `agent-discoverability-2026-05-15.md` (Navigation Paradox primary finding: 78.2% coverage grep-only → 99.4% with explicit cross-references)

---

## Summary

A dedicated cross-reference maintenance agent is FEASIBLE for the UDM project and RECOMMENDED at the CI-hook level, with a narrower mandate than the user envisions. The industry provides a mature toolchain for detection (lychee, markdown-link-check, markdownlint MD051, DocLinkChecker), established CI/bot patterns (lychee-action scheduled cron, PR-triggered pre-commit hooks), and emerging AI-agent maintenance workflows (GitHub Copilot Drasi pattern). However, auto-fix is only safe for a small, mechanically resolvable subset of failure modes. The majority of failure modes in the UDM context — broken D-number semantic references, heading-slug drift, orphan targets, reciprocal-link asymmetry — require human judgment.

The recommended design is NOT a continuously-running autonomous agent. It is a four-component system: (1) a pre-commit hook for basic link existence, (2) a scheduled CI job (lychee-action, weekly) for comprehensive cross-file fragment validation, (3) an extension to the existing `verify_cascade.py` Pattern F Trigger D for UDM-specific identifier resolution, and (4) a Claude Code SKILL (on-demand, not autonomous) for semantic-ambiguity cases and proposed-fix generation. This respects the North Star's "operationally stable beats clever" pillar — a 95% solution that runs reliably beats a 99% solution that occasionally makes wrong auto-fixes.

Confidence: 🟡 Medium — tool ecosystem is well-documented; the AI-agent auto-fix boundary is based on industry convergence (Drasi case study + WarpFix) but UDM-specific application is novel.

---

## Sources cited

| # | URL | Date accessed | Authority |
|---|---|---|---|
| 1 | https://github.com/tcort/markdown-link-check | 2026-05-15 | Primary (npm package, GitHub) |
| 2 | https://lychee.cli.rs/recipes/anchors/ | 2026-05-15 | Primary (lychee docs) |
| 3 | https://github.com/lycheeverse/lychee | 2026-05-15 | Primary (GitHub) |
| 4 | https://github.com/lycheeverse/lychee-action | 2026-05-15 | Primary (GitHub Actions marketplace) |
| 5 | https://github.com/DavidAnson/markdownlint/blob/main/doc/md051.md | 2026-05-15 | Primary (markdownlint docs) |
| 6 | https://deepwiki.com/DavidAnson/markdownlint/2.1.4-links-and-images-rules | 2026-05-15 | Community (markdownlint rules reference) |
| 7 | https://www.nuget.org/packages/DocLinkChecker/1.15.0 | 2026-05-15 | Primary (NuGet package registry) |
| 8 | https://vale.sh/docs | 2026-05-15 | Primary (Vale docs) |
| 9 | https://pypi.org/project/linkcheckmd/ | 2026-05-15 | Primary (PyPI) |
| 10 | https://github.com/marketplace/actions/lychee-broken-link-checker | 2026-05-15 | Primary (GitHub Marketplace) |
| 11 | https://github.com/marketplace/actions/markdown-link-check | 2026-05-15 | Primary (GitHub Marketplace) |
| 12 | https://opensource.microsoft.com/blog/2026/04/09/how-drasi-used-github-copilot-to-find-documentation-bugs/ | 2026-05-15 | Microsoft Open Source Blog (industry case study, April 2026) |
| 13 | https://warpfix.org/ | 2026-05-15 | Industry (WarpFix AI CI repair agent) |
| 14 | https://docs.renovatebot.com/bot-comparison/ | 2026-05-15 | Primary (Renovate docs) |
| 15 | https://github.com/apps/warpfix | 2026-05-15 | Primary (GitHub Apps) |
| 16 | https://www.mintlify.com/docs/guides/automate-agent | 2026-05-15 | Primary (Mintlify docs) |
| 17 | https://code.claude.com/docs/en/skills | 2026-05-15 | Anthropic primary |
| 18 | https://arxiv.org/html/2602.20048v1 | 2026-05-15 | Academic (CodeCompass Navigation Paradox) |

---

## Findings

### Finding 1: Existing tool landscape — what each tool covers and misses

**Sources**: [1][2][3][5][7][9]

**markdown-link-check (npm, tcort)** [1]: detects dead links (HTTP 4xx, file-not-found). Supports ignorePatterns, replacementPatterns, JUnit XML output for CI. Pre-commit hook available. What it does NOT do: no fragment/anchor validation; no cross-file heading-slug resolution; no orphan-target detection; no semantic reference resolution (e.g., "see D15" plain text is invisible to it).

**lychee (Rust)** [2][3]: Fast async link checker. Key differentiator: `--include-fragments` flag enables anchor validation within HTML. For Markdown, it uses "unique kebab case" conversion mirroring GitHub's anchor auto-generation. The lychee docs [2] show it can validate fragments in local files. Critical limitation: cross-file fragment link validation (e.g., `other-file.md#D15`) appears undocumented — the lychee docs do not explicitly describe cross-file anchor resolution for Markdown; this is an open question requiring direct testing. The lychee-action [4] supports scheduled cron runs and can create GitHub Issues on failure. This is the closest to a "Dependabot for links" in terms of CI integration.

**markdownlint MD051** [5][6]: Validates fragment links within a SINGLE document only. Per primary documentation: "MD051 does not validate cross-file link fragments." Auto-fixable for some violations (the rule is marked "Fixable: Some violations can be fixed by tooling"). Follows GitHub heading algorithm (lowercase + punctuation removal + spaces to hyphens). Does not detect orphan files or reciprocal asymmetry.

**vale** [8]: Prose linter for style guide rules (Elastic, GitLab, Grafana all use it). Cross-reference capability: Vale can write custom rules detecting missing patterns (existence extension point), repeated tokens, etc. A custom rule could flag "D15" or "B-17" as plain-text identifiers and require them to be formatted as explicit links. This is a style/lint approach — not a link-existence approach. Vale does not resolve whether a link destination exists.

**DocLinkChecker** [7]: .NET NuGet package. Most relevant feature: `--attachments` flag checks resource files to detect orphaned files (files that are present in the directory but referenced by no markdown file). Closest tool to "orphan target" detection. Platform limitation: .NET-only; not cross-platform without container.

**linkcheckmd (Python)** [9]: 10,000 files/second via asyncio. Internal and external URL checking. Does not address fragment anchors or orphan targets.

**Relevance to UDM**: Traceability pillar — broken internal references make audit-trail navigation unreliable. Operationally stable pillar — CI gate prevents regression.

**Confidence**: High (all from primary source documentation).

---

### Finding 2: CI / bot trigger patterns

**Sources**: [4][10][11][14]

Three trigger patterns dominate in practice:

**Pattern A — On-commit / on-PR** (pre-commit hook or CI gate): Catches newly introduced broken links before merge. markdown-link-check and lychee both have GitHub Actions marketplace variants [10][11] supporting this. Limitation: only catches links in changed files (or full repo scan on PR, which is slow for large repos).

**Pattern B — Scheduled cron** (weekly or daily): lychee-action [4] explicitly supports creating a GitHub Issue on failure from a scheduled workflow. This is the closest existing analog to a "Dependabot for links" — a background bot that surfaces link rot without being triggered by a commit. The lychee docs describe: "check all repository links once per day and create an issue in case of errors."

**Pattern C — Renovate/Dependabot shape** (auto-PR for detected drift): Renovate [14] uses a "Dependency Dashboard" issue with Markdown checkboxes to list pending updates. The shape is: detect → open issue (interactive) or open PR (auto-fix). This exact shape could apply to cross-reference maintenance: bot detects broken link, opens a PR with a proposed fix (or opens an issue listing the broken links). WarpFix [13][15] demonstrates this pattern for CI failures: detect failure, sandbox-validate a patch, open PR. No existing tool applies this shape specifically to markdown cross-references.

**Relevance to UDM**: Operationally stable — scheduled detection + issue/PR creation fits the project's existing operator-action model (humans approve, agents propose). This avoids the risk of autonomous rewrite of UDM canonical docs.

**Confidence**: High for existing tool behavior (primary sources); Medium for extending the Renovate/WarpFix shape to cross-references (no existing tool does this; it is an extrapolation from adjacent domains).

---

### Finding 3: Agent design question — SKILL vs AGENT vs PRE-COMMIT vs CRON

**Sources**: [17][12][13]

**SKILL (Claude Code, on-demand)** [17]: Loaded only when invoked; no token cost until needed. Appropriate for: semantic-ambiguity cases where a human invokes the skill to get a proposed fix list before a file split. Output: structured list of proposed link rewrites for human review. Anthropic skills documentation confirms: "Unlike CLAUDE.md content, a skill's body loads only when it's used, so long reference material costs almost nothing until you need it." This is the right shape for the UDM "review before apply" constraint.

**AUTONOMOUS AGENT (continuously running background)**: The Drasi case study [12] shows the state of the art for autonomous documentation maintenance: detect-only, not auto-fix. "When failures occur, the workflow files GitHub issues — humans then fix the documentation." The key constraint from Drasi: "Non-determinism from LLMs required three-stage retry escalation... and tight prompt constraints to prevent agents from 'going on a debugging journey.'" An autonomous agent that REWRITES UDM canonical docs (03_DECISIONS.md, BACKLOG.md, etc.) is unsafe — the validation discipline (D55 5-gate, D56 second-pass) explicitly prohibits unreviewed changes to primary docs. This is also the researcher agent's own constraint: outputs to `_research/`, not primary docs.

**PRE-COMMIT HOOK**: Appropriate for the lychee / markdown-link-check existence check (does the file exist? does the anchor exist in that file?). Not appropriate for semantic reference resolution. Limitation: pre-commit hooks run in the developer's environment; UDM runs on Windows dev workstation + RHEL Linux — cross-platform pre-commit hook configuration adds operational complexity.

**CRON-SCHEDULED CI JOB**: Best fit for comprehensive weekly audit. Opens a GitHub Issue on failure (lychee-action pattern). Does not require developer environment configuration; runs in CI. Can be extended to detect UDM-specific identifier patterns (D-numbers, B-numbers, RB-N) as plain-text vs explicit link.

**Interaction with existing `verify_cascade.py`**: The Pattern F Trigger D ("forward-cite resolution") already walks `docs/migration/` checking that cited D-numbers / B-numbers / R-numbers / SP-N / RB-N resolve to definitions in canonical home files. This is a semantic check — not a file-existence check. The proposed cross-reference maintenance agent should COMPLEMENT Trigger D, not duplicate it. Trigger D catches "B-9 cited but B-9 not defined in BACKLOG.md." A new Trigger (call it Trigger L for "link") would catch "docs/migration/HANDOFF.md references `phase1/05_tests.md § 8.2 L488` but that line number no longer contains § 8.2."

**Confidence**: High for SKILL and PRE-COMMIT shapes (Anthropic primary docs); High for CRON shape (lychee-action primary docs); High for autonomous-agent-being-unsafe (Drasi empirical case study, April 2026, Microsoft Open Source Blog).

---

### Finding 4: Failure-mode hierarchy — what can and cannot be caught mechanically

**Sources**: [5][6][18][2]

Seven failure modes identified, ordered by mechanical resolvability:

| Failure Mode | Mechanical Detection? | Auto-Fix Safe? | UDM Examples |
|---|---|---|---|
| **F1 — Broken file path** (file moved/renamed) | YES — file-existence check | YES if unique rename | `[HANDOFF](HANDOFF.md)` → file renamed |
| **F2 — Broken fragment anchor** (heading renamed) | PARTIAL — lychee + MD051 in-file; cross-file undocumented | RISKY — must know new heading name | `#d15-idempotency` → heading restructured |
| **F3 — Orphan reference** (referent file deleted) | YES — file-existence check | NO — must decide whether reference itself should be deleted or retargeted | `[see SECURITY_MODEL.md]` → file deleted |
| **F4 — Orphan target** (file referenced by no one) | YES — DocLinkChecker pattern | NO — must decide if the file itself should be deleted | `_research/old-finding.md` unreferenced |
| **F5 — Stale line-number citation** (line number drifted) | PARTIAL — script can check if line contains expected section | NO — new line must be computed | `phase1/05_tests.md § 8.2 L488` |
| **F6 — Reciprocal asymmetry** (A cites B, B doesn't cite A) | NO — requires semantic intent | NO — sometimes asymmetry is intentional | Decision cites edge case; edge case doesn't back-reference decision |
| **F7 — Forward reference** (A cites future B that doesn't exist yet) | PARTIAL — same as F1 but expected | NO — must know if this is intentional | `[B-999]` not yet created |

For UDM specifically: the most common failure modes are F2 (heading slug drift after heading rename — §13.4 in MARKDOWN_REFACTOR_PLAN.md explicitly addresses this) and F5 (stale line-number citations like `phase1/05_tests.md § 8.2 L488`). These are NOT safely auto-fixable without human confirmation.

The UDM corpus uses two distinct reference styles:
1. **Explicit Markdown links**: `[D15](03_DECISIONS.md#d15)` — detectable by lychee/MD051
2. **Plain-text identifiers**: "per D15" or "see B-17" — invisible to link checkers; requires regex-based detection + semantic resolution (Pattern F Trigger D already handles this for canonical-home resolution)

**Relevance to UDM pillars**: Audit-grade — broken D-number references make audit trails unnavigable. Navigation Paradox [18] empirically measured: plain-text "see D15" breaks agent navigation after file splitting (78.2% vs 99.4% coverage).

**Confidence**: High for F1/F3/F4 (file-existence checks are deterministic); Medium for F2 (cross-file fragment validation is undocumented in lychee for Markdown-to-Markdown specifically); Low for F5/F6/F7 (no existing tool covers these mechanically).

---

### Finding 5: AI-driven documentation tools — Mintlify, GitBook AI, GitHub Copilot

**Sources**: [12][16]

**Mintlify** [16]: Offers "agent suggestions to proactively improve documentation quality" and "CI checks for broken links and style guide linting using Vale." Their automation pipeline can draft documentation updates triggered by PRs, Slack messages, etc. and route through human review. This is the closest commercial product to the proposed agent. Key constraint: Mintlify is a documentation *platform*, not a script/tool that runs on a plain GitHub repo. Not applicable to UDM's plain-markdown-in-git model.

**GitBook AI**: "Agent scans connected sources to identify documentation gaps and proposes documentation updates." Again, platform-only; not applicable to UDM's model.

**GitHub Copilot (Drasi case study)** [12]: Most directly applicable. Drasi deployed Copilot CLI + Dev Containers to run automated weekly synthetic-user sessions against tutorials. Key lessons:
- Detection, not auto-fix: the agent files issues; humans fix
- Non-determinism requires retry logic and tight prompt constraints
- "The container is the boundary" security model limits blast radius
- Over 200 sessions → 18 distinct issues found; none auto-corrected

The Drasi pattern is the 2026 state of the art: AI agents as documentation QA, not documentation maintainers.

**Anthropic Claude Code SKILL** [17]: The skill model is explicitly designed for on-demand, bounded-scope tasks. A `udm-cross-ref-checker` skill with a narrow mandate (detect broken links in `docs/migration/`, propose fixes as structured output, write proposed fixes to `_research/`) aligns with the project's existing producer-vs-reviewer separation.

**Confidence**: High for Drasi case study (primary Microsoft blog, April 2026); High for Mintlify/GitBook (primary vendor docs); High for Claude Code SKILL shape (Anthropic primary docs).

---

### Finding 6: Auto-fix vs surface-for-review boundary

**Sources**: [12][13]

Industry convergence (2025-2026):

**Safe to auto-fix (mechanical)**:
- Broken file path where destination is uniquely identifiable (renamed file has one new name)
- Orphan resource files (DocLinkChecker `--cleanup` pattern; deletes unreferenced attachments — note: NOT unreferenced markdown files)
- Fragment anchors within a single file where the correct heading exists and is unique (MD051 auto-fixable cases)

**Must surface for human review**:
- Any reference where multiple candidate targets exist (ambiguous rename)
- Broken D-number / B-number / RB-N / SP-N semantic references (even if the number appears elsewhere, the canonical home may have moved or been superseded)
- Heading-slug drift on cross-file links (the new slug must be computed from the new heading; the agent cannot know if the heading was intentionally renamed)
- Reciprocal-link asymmetry (may be intentional design)
- Forward references (may be intentional stubs for planned content)
- ANY change to primary UDM docs (03_DECISIONS.md, BACKLOG.md, RISKS.md, etc.) — per UDM's own discipline, primary docs are only changed through the validation gate, not by autonomous agents

**The Drasi lesson** [12]: "Tight prompt constraints to prevent agents from going on a debugging journey." Any UDM cross-reference agent must have an explicit mandate boundary: detect and propose, never apply to primary docs.

**Relevance**: Audit-grade — silent auto-fix to a canonical doc is worse than a broken link. Traceability — every fix must be logged and reviewed.

**Confidence**: High — Drasi and WarpFix both empirically demonstrate the detect-then-PR (not detect-then-apply) pattern as the safe boundary for autonomous agents touching doc repos.

---

### Finding 7: UDM-specific design constraints from existing project infrastructure

**Source**: Internal (tools/verify_cascade.py, MARKDOWN_REFACTOR_PLAN.md §13.3, B17)

The UDM project already has:

1. **Pattern F Trigger D** in `verify_cascade.py`: regex-based resolution of D-numbers / B-numbers / R-numbers / SP-N / RB-N across the `docs/migration/` corpus. Catches "D-number cited but not defined." Does NOT catch: file path existence, fragment anchor validity, line-number drift, orphan targets.

2. **B17** in BACKLOG.md: "Cross-reference audit tool (link checker for docs/migration/ + .claude/) — COD=2, JS=4, WSJF=0.5 — Phase 6." This is already a known gap, low-priority.

3. **§13.3 mandatory constraint**: Any Phase 3 file split MUST run a cross-reference verification script before and after. The plan names `tools/rewrite_cross_refs.py` (not yet built).

4. **§13.4 heading-slug stability policy**: Headings that participate in cross-references use `## D15 — {title}` pattern where `D15` is the first word. This makes `#d15` a stable short-form anchor (lychee and markdownlint both use the GitHub slug algorithm: lowercase + hyphens + strip punctuation, so `## D15 — Title` → `#d15----title`, which is NOT `#d15`). This is a gap in the policy — the short-form `#d15` anchor only works if GitHub strips the `—` separator or if an explicit `{#d15}` custom anchor is added. This is a finding worth surfacing.

---

## Recommendation

**Recommended design: Four-component system (not a single autonomous agent)**

### Component 1 — lychee-action Scheduled CI Job (weekly)
- Trigger: scheduled cron (weekly, e.g. Sunday 02:00 UTC) + optionally on PR for changed files
- Tool: lychee-action [3][4] with `--include-fragments` flag
- Scope: all `*.md` files in `docs/migration/` and `.claude/`
- On failure: creates GitHub Issue listing broken links
- Auto-fix: NONE — issue creation only
- Estimated cost: ~5 minutes CI compute per week; zero developer time unless failures found
- What it catches: F1 (broken file paths), F2 partial (in-file anchors; cross-file anchor coverage uncertain — see Finding 1 caveat), F3 (orphan references to deleted files)
- What it misses: F4 (orphan targets), F5 (stale line numbers), F6 (reciprocal asymmetry), F7 (forward references), plain-text D-number / B-number references

### Component 2 — verify_cascade.py Trigger L Extension (Trigger L = link integrity)
- Extend the existing `tools/verify_cascade.py` with a new trigger (naming convention: Trigger L for "link")
- Trigger L runs on every Pattern F invocation (round close-out)
- What it catches:
  - F5 (stale line-number citations) — regex for `§ N.M L\d+` patterns; assert the referenced line contains the expected heading
  - F2 (heading-slug drift for explicit relative Markdown links) — extract all `[text](file.md#fragment)` patterns; resolve `file.md`; verify `#fragment` matches a heading in that file using the GitHub slug algorithm
- What it does NOT do: no auto-fix; findings are red/yellow per existing Trigger severity model
- Implementation estimate: ~200-300 lines of Python extending the existing dataclass + scanner structure; JS=2 (a half-day build)
- Interaction with existing Pattern F: additive, non-conflicting with Trigger C/D/F; runs after them

### Component 3 — Pre-split rewrite_cross_refs.py (split-time only, per §13.3)
- NOT a continuous monitor; executes ONCE before each Phase 3 file split
- Inputs: pre-split file list + new file mapping
- Outputs: rewritten links as a git diff proposal; human approves before merge
- Auto-fix: YES, but ONLY for mechanically resolvable F1 cases (file moved to a known new path, exact rename)
- The agent produces the proposed diff; a human reviews before `git apply`
- This is the `tools/rewrite_cross_refs.py` already named in §13.3 but not yet built

### Component 4 — udm-cross-ref-checker SKILL (on-demand)
- Claude Code SKILL (not an autonomous agent)
- Invoked by a human or the main agent when: (a) preparing for a Phase 3 split; (b) a Pattern F Trigger L finding surfaces an ambiguous case; (c) the user asks "what references will break if I rename this heading?"
- Mandate: detect and propose, NEVER apply to primary docs
- Output: writes proposed fixes to `docs/migration/_research/cross-ref-audit-<date>.md` (same pattern as this research artifact)
- Does NOT write to: `03_DECISIONS.md`, `BACKLOG.md`, `RISKS.md`, `HANDOFF.md`, or any primary doc
- This respects the project's D55/D56 producer-vs-reviewer separation
- Cost: zero until invoked (Anthropic SKILL model — body loads only on invocation)

---

## Design proposal contract (if built)

```
udm-cross-ref-checker SKILL
Inputs:
  - repo_root: path to docs/migration/
  - mode: audit | pre-split | on-rename
  - changed_files: list of files in scope (None = all)
  - heading_rename_map: {old_heading_slug: new_heading_slug} (for on-rename mode)
Outputs:
  _research/cross-ref-audit-YYYY-MM-DD.md containing:
    - Per-finding table: source_file | line | reference | target_file | fragment | status | proposed_fix
    - Status values: OK | BROKEN_FILE | BROKEN_FRAGMENT | STALE_LINE | ORPHAN_TARGET | FORWARD_REF | AMBIGUOUS
    - Auto-fixable flag: TRUE only for BROKEN_FILE with unique rename match
    - Proposed fix diff (human must apply via `git apply`)
Audit trail:
  - Every run logs to _validation_log.md (append-only per D55)
  - No changes written to primary docs; all output in _research/
Failure mode:
  - If agent attempts to write to primary docs → STOP; log error; surface to human
  - If proposed fix is ambiguous (multiple candidates) → AMBIGUOUS status; no proposed fix; surface to human
```

---

## Counter-evidence

**Against the multi-component recommendation**:

1. **Complexity risk**: Four components add maintenance surface. Counter-argument: Components 1 and 3 reuse existing open-source tools (lychee, standard Python); Component 2 extends existing code; Component 4 is a skill with no runtime cost until invoked. The complexity cost is low.

2. **lychee cross-file fragment validation is uncertain**: The lychee docs [2] do not explicitly confirm cross-file Markdown-to-Markdown fragment resolution. If lychee cannot validate `other-file.md#D15`, Component 1 loses its primary differentiator. Counter-argument: Trigger L in Component 2 covers this case independently; Component 1's value remains for external URL checking and file-existence checking.

3. **Industry is converging on AI-first** (Mintlify, GitBook AI, GitHub Copilot agents): Could the UDM project benefit from a fully autonomous agent rather than a script-first approach? Counter-argument: The Drasi case study [12] is the most current evidence (April 2026) and it explicitly chose detection-not-auto-fix even with AI agents. UDM's audit-grade constraint (North Star pillar 1) amplifies this: a wrong auto-fix to a canonical doc is worse than a wrong auto-fix to application code.

**No authoritative counter-evidence found** for the claim that scheduled CI link checking (Component 1) is inadequate for internal markdown repos. All sources agree it is the appropriate baseline.

---

## What this research does NOT cover

- Quantitative analysis of how many references in the UDM corpus are already broken (would require running lychee on the actual corpus)
- Whether lychee's `--include-fragments` flag correctly resolves cross-file Markdown anchors (requires empirical test in the UDM environment)
- The exact slug-computation behavior for `## D15 — Title` headings (the `—` character is not standard ASCII; slug generation varies by processor)
- Cross-reference maintenance for `.claude/skills/*.md` and `.claude/agents/*.md` files (separate from `docs/migration/` but subject to the same Navigation Paradox concerns)
- Integration with the proposed `udm-find-canonical` skill (MARKDOWN_REFACTOR_PLAN.md §4.3) — would the two skills be redundant?

---

## Confidence assessment

Overall: 🟡 Medium

- Component 1 (lychee CI): 🟢 High confidence — tool is mature, GitHub Actions integration is primary-documented, cron pattern is widely used
- Component 2 (Trigger L extension): 🟢 High confidence — extending `verify_cascade.py` is within existing project infrastructure; the regex patterns are deterministic
- Component 3 (rewrite_cross_refs.py): 🟡 Medium confidence — the script is not yet built; auto-fix boundary assessment is grounded in Drasi case study but is extrapolated to the UDM context
- Component 4 (SKILL): 🟢 High confidence for the shape (Anthropic primary docs); 🟡 Medium for effectiveness (no prior art for exactly this use case in UDM)
- AI autonomous agent as an alternative: 🔴 Rejected on current evidence — Drasi (April 2026, most current case study) demonstrates detection-only as the safe boundary

---

## Suggested follow-up

1. **Empirical test (immediate)**: Run `lychee --include-fragments` on `docs/migration/` and observe whether it validates cross-file Markdown anchors (e.g., HANDOFF.md link to NORTH_STAR.md#heading). 30 minutes; resolves the Component 1 capability uncertainty.

2. **Slug-computation policy clarification (immediate)**: Test what GitHub and lychee produce as a slug for `## D15 — Title` (the `—` em-dash). If the slug is `#d15----title` (not `#d15`), the §13.4 heading-slug stability policy needs a correction: explicit custom anchors `{#d15}` should be required. This is a finding for MARKDOWN_REFACTOR_PLAN.md §13.4.

3. **B17 upgrade consideration**: B17 is currently WSJF=0.5 (Phase 6, low priority). Given that Phase 3 file splits are being considered and the Navigation Paradox finding is now primary-sourced, the producer could consider escalating B17 to Phase 1 scope with the narrower mandate described in Component 2 (Trigger L extension to verify_cascade.py). This is a low-effort, high-traceability improvement.

4. **Producer should NOT open a new D-number** for this design proposal without first running the empirical lychee test (item 1 above) and confirming the slug-computation policy (item 2). The design is research, not a locked decision.

5. **Validation gate 2 can mark**: "cross-reference maintenance agent design proposal now grounded in primary sources (lychee, markdownlint, Drasi case study)"

---

## North Star pillar mapping

- **Traceability**: Broken D-number / B-number cross-references make audit trails non-navigable. Component 2 (Trigger L) directly addresses this.
- **Operationally stable**: Scheduled CI (Component 1) provides background assurance without developer overhead. Detect-not-auto-fix avoids the risk of wrong autonomous changes to canonical docs.
- **Audit-grade**: All proposed fixes are logged in `_research/`; no silent auto-fixes to primary docs. Drasi case study validates this as the 2026 industry standard.
- **Idempotent**: lychee and Trigger L are stateless; re-running produces the same output. No side effects.
- **$120K ceiling**: All components are free/OSS (lychee = Rust OSS, markdownlint = OSS, verify_cascade.py = project code). Zero incremental cost.
