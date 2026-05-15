# Consistency + governance gap audit — MARKDOWN_REFACTOR_PLAN.md

**Date**: 2026-05-15
**Scope**: `docs/migration/MARKDOWN_REFACTOR_PLAN.md` (997 lines, 4th revision) + companion `NEW_REPO_STARTER_TEMPLATE.md` + `tools/test_github_slug.py` + `tools/measure_ccl_overhead.py` + 3 spot-checked research artifacts (em-dash-slug-test / ccl-baseline / agent-discoverability).
**Perspective**: Cross-cutting auditor — looking for CONTRADICTIONS (plan disagrees with itself), DRIFT (one location updated, another stale), UNENFORCEABLE GOVERNANCE (rules claimed without mechanism), and missing artifacts.
**Severity legend**: 🔴 CONTRADICTION (must fix; plan internally inconsistent) / 🟡 DRIFT (one place updated; another stale) / ⚪ ENFORCEABILITY-GAP (rule asserted; no mechanism)

---

## Summary

The plan is research-grounded and the directional verdicts are coherent, but the 4-revision evolution has left **18 concrete consistency / drift / enforceability issues**, including **two outright internal contradictions inside §13.4 itself**. The most serious finding is that §13.4 still asserts em-dash as the rule + shows em-dash forms as ✅ examples (L658, L663-664) DIRECTLY ABOVE the empirical test that proves em-dash is broken + the colon-form binding recommendation (L670-696). Anyone reading §13.4 top-down gets the wrong answer until L682. Additionally, **the `_research/_INDEX.md` register referenced 4 times across the plan and template does not yet exist**, leaving a Q1 governance hole. Section ordering is broken (§12 sign-off appears AFTER §16; §14 is missing). The plan asserts six markdown-hygiene CI rules but **none has a working tool implementation** today.

---

## §1. Contradictions inside the plan

### 🔴 C-1. §13.4 still says "MUST use em-dash" at L658 + shows em-dash as ✅ at L663-664
The opening Rule sentence (L658) reads: `Headings ... MUST use the convention ## {ID} — {title}` (em-dash). The "Best practice for stable slugs" bullets at L663-664 mark em-dash variants `## D15 — Idempotency Ledger` with ✅. Both directly contradict the empirical-test block at L670-696 which mandates **colon-form** + flags em-dash as 🔴 BROKEN. Top-down readers get the wrong rule until L682.
**Fix**: rewrite L658 + L663-664 to lead with colon-form; relegate em-dash discussion to a "previously assumed" footnote.

### 🔴 C-2. Archive trigger: 2K lines vs 5K lines
Two locations specify different `_validation_log.md` archive thresholds:
- §16.1 hygiene table (L873): "triggers archive cascade at **5,000 lines** OR quarterly"
- §16.2 starter principle 5 (L884) + NEW_REPO_STARTER §6 L208: archive at **2,000 lines**
- `tools/measure_ccl_overhead.py` `TARGET_CCL_LINES` constant = **2,000**
The 2K target ties to the §9 metric (CCL <2,000 lines). The 5K in §16.1 is inconsistent and softer than the plan's own optimization math.

### 🔴 C-3. Section ordering broken (§12 sign-off at end; §14 missing)
H2 ordering as authored: §1→§2→§3→§4→§5→§6→§7→§8→§9→§10→**§10b**→§11→**§13**→**§15**→**§16**→**§12**. §12 (Sign-off) appears LAST at L988 — out of numerical order. §14 is missing entirely (jumps §13 → §15). The §14 gap is not annotated as intentional anywhere.
**Fix**: renumber post-revision (§12 → §17) or explicitly annotate "§12 placed last for sign-off prominence; §14 reserved/skipped."

### 🟡 D-1. §3.1 verdict text says "REVISED 2026-05-15 per §13 deep-dive" but §13 has been further revised by §15.4
§3.1 (L94) cites §13 as authority for the Phase-1 deferral verdict. §15.4 + the empirical em-dash result further revised §13.4. §3.1's reference doesn't note the cascade — a reader following the trail from §3.1 → §13 sees the contradictions in §13.4 first.

### 🟡 D-2. CCL cost estimate `~12K-16K lines` repeated despite §15.4 measuring 9,212 actual lines
§1.2 (L45), §2.1 (L59), §3.6 finding 11 (L221), §4.5 (L280), §9 metric 1 (L414) all use the `~12K-16K lines per CCL invocation` estimate. §15.4 acknowledges the actual line count is 9,212 ("matched line count but understated token cost by ~1.8×"). The "12K-16K" figure is now known-stale in 5 locations; only §15.4 carries the correction.

---

## §2. Plan vs companion artifacts

### 🟡 D-3. NEW_REPO_STARTER_TEMPLATE.md INDEX.md skeleton diverges from plan §13.2 skeleton
- Plan §13.2 (L590-620) skeleton labels Stage 1 reads as **CURRENT_STATE / HANDOFF / GLOSSARY** (the UDM file names) — not the generic 00_OVERVIEW / 01_ARCHITECTURE.
- Template §3 (L86-95) labels Stage 1 reads as **00_OVERVIEW.md / 01_ARCHITECTURE.md** — these don't exist in UDM and aren't part of the existing CCL.
This is a category drift (UDM-specific vs generic) — defensible for a greenfield template, but the plan never explains why the two skeletons differ. A new-repo adopter who reads both sees conflicting structure and may copy the wrong one.

### 🟡 D-4. Template principle 6 specifies CCL "Stage 1 (4 reads max)" — but plan §9 metric is the inverse
Template §1.6 (L25) + §5 (L173) say Stage 1 = 4 reads max. Plan §15.4 measured current Stage 1 = 4 files = 69,572 tokens (35% of context). The "4 reads max" is a CEILING, but if a real project's canon-tier needs only 2 reads the template enforces a minimum-feeling 4. Wording should clarify "up to 4" vs "always 4."

### 🟢 OK. Template demonstrates the 8 principles
Spot-checked: colon-form mandated (L19, L133), explicit cross-ref links demonstrated (L21, L134), lean CLAUDE.md skeleton ≤300 lines (L123-160 = 38 lines body), append-only archive policy in `_validation_log.md` skeleton header (L193-224). 8 principles consistently demonstrated.

---

## §3. Plan vs tooling

### 🔴 C-4. Plan §16.1 references `tools/measure_ccl_overhead.py --report-large` flag — flag does not exist
§16.1 hygiene table L872: "Files >2,000 lines auto-flagged for split candidate review at next round close-out | `tools/measure_ccl_overhead.py` --report-large flag." Grep of the script confirms zero matches for `--report-large` or `report-large`. The script DOES emit `_trim_recommendation()` text per-file but no CLI flag triggers the "large file flag" enforcement claimed.

### 🟢 OK. `tools/test_github_slug.py` matches the empirical test
Script implements github-slugger v2.x algorithm correctly per stdlib `unicodedata.category()` check for `\p{Pd}`; 5 cases match the plan §13.4 + research artifact tables exactly. Validation reproducible.

### 🟢 OK. `tools/measure_ccl_overhead.py` implements what §15.4 claims
Script classifies files into Stage 1/2/3 per `STAGE_1_FILES` / `STAGE_2_FILES` constants (matches D62 canonical lists); token counter falls back to chars/4 heuristic when tiktoken unavailable (matches the "heuristic" method noted in `_research/ccl-baseline-2026-05-15.md`); reproducible results.

---

## §4. Plan vs research artifacts

### 🟢 OK. Plan §13.4 cites em-dash test results correctly
Plan §13.4 table at L676-680 matches `_research/em-dash-slug-test-2026-05-15.md` table at L56-60 exactly (5 cases; same slugs; same ✅/❌ verdicts).

### 🟢 OK. Plan §15.4 cites CCL baseline correctly
Plan §15.4 table at L790-796: Stage 1 = 69,572 tokens (35%); Stage 2 = 292,582 (146%); S1+S2 = 362,154 (181%); `_validation_log.md` alone = 231,039 (115%). All match `_research/ccl-baseline-2026-05-15.md` rows exactly.

### 🟡 D-5. Plan §3.6 references "13 findings + 15 primary sources" for agent-markdown-traversal artifact; plan §11 (L519) repeats this
Couldn't validate the source count without reading the artifact in full, but `agent-discoverability` source-table has 17 entries (validated). Numbers are consistent within the plan.

---

## §5. Governance enforceability gaps

### ⚪ E-1. "All NEW H2 headings use colon-form" — no enforcing tool exists today
§16.1 hygiene table promises "pre-commit hook + Pattern F audit" enforcement. Neither the pre-commit hook nor a Pattern F regex addition exists. The rule is asserted, but a producer who authors `## D-99 — New` in a new commit gets no automated feedback.

### ⚪ E-2. "All NEW cross-references use explicit `[](path#anchor)` Markdown links" — no enforcing tool
Same as E-1. The lychee CI hookup is named in §15.2 Pattern (d) but `.github/workflows/lychee.yaml` (or equivalent) does not exist. `tools/verify_cascade.py` is referenced; need separate audit to confirm whether it parses cross-ref Markdown links.

### ⚪ E-3. "All NEW sections lead-with-answer (1-3 sentences)" — regex check is admitted advisory; nothing built
§16.1 explicitly notes "(best-effort; advisory not blocking)". No script exists. The discipline relies entirely on author memory + reviewer agent eyeballing.

### ⚪ E-4. "All NEW research artifacts register in `_research/_INDEX.md`" — register file does not exist
Plan §16.1 + §16.2 + NEW_REPO_STARTER §2 + §7 all reference `docs/migration/_research/_INDEX.md`. The file is NOT in the filesystem (verified via directory listing). Until the register is authored + populated, none of the 6 existing research artifacts in `_research/` are tracked under the discipline the plan claims is binding.

### ⚪ E-5. "Files >2,000 lines auto-flagged" — flag doesn't exist (see C-4)
Cross-references C-4 above.

### ⚪ E-6. "`_validation_log.md` triggers archive cascade at 5,000 lines OR quarterly" — wrapping the C-2 contradiction
Even setting aside which threshold is right (2K vs 5K), no scheduled job, pre-commit hook, or skill trigger fires the archive procedure. Existing policy at `_validation_log.md` L14-23 documents the manual procedure but nothing automated invokes it.

---

## §6. Q-N numbering consistency

### 🟡 D-6. §10 references Q-13 through Q-26 inline but doesn't define them — they live in §13.6 / §15.5 / §16.6
§10 has full bodies for Q-1 through Q-12. For Q-13 through Q-26, §10 only has 1-line summary pointers ("see §13.6", "see §15.5", "see §16.6"). A reader expecting a flat numbered list gets fragmented definitions across 4 sections.

### 🟢 OK. No orphan or duplicate Q-numbers
Verified Q-1 → Q-26 are each referenced exactly once as a definition site. RESOLVED markers (Q-13, Q-22 = ✅ RESOLVED) are consistent — both have status flips at §15.4 L811 + §10 L447-449.

### 🟢 OK. Q-22 status consistent (RESOLVED) across §10 + §13.4 + §15.4
Three locations all mark Q-22 as ✅ RESOLVED with consistent rationale + research-artifact citation.

---

## §7. Cross-doc references — spot-checks (5 random)

1. **§3.6 cites `arxiv 2602.20048`** for Navigation Paradox — repeated at §11 (L528), §13.3 (L642), §15.2 (no cite). Consistent ✅
2. **§13.4 cites `tools/test_github_slug.py`** — file exists ✅ + content matches the cited 5-case algorithm ✅
3. **§15.4 cites `tools/measure_ccl_overhead.py` "218 lines"** — actual is 219 lines (off by 1; insignificant but technically D-7 drift) 🟡
4. **§16.1 cites `tools/check_markdown_hygiene.py`** — file does NOT exist (admitted as future-planned but not separated from existing-tool list) ⚪ E-7
5. **§16.2 cites `NEW_REPO_STARTER_TEMPLATE.md` "~300 lines"** — actual = 334 lines; close enough but cosmetic drift 🟡

### 🟡 D-7. Token estimate drift: `tools/measure_ccl_overhead.py "218 lines"` (actual 219) + template "~300 lines" (actual 334)
Both within rounding tolerance but symptomatic of Pitfall #9.k (arithmetic-propagation drift) the plan claims to enforce.

---

## §8. Self-referential integrity

### 🔴 C-5. Plan's self-imposed split trigger fired but plan was NOT split
§13 preamble (L539): "if the plan crosses ~700 lines total, it should split per its own §13.1 naming convention". §15 preamble (L743) explicitly acknowledges the trigger fired ("Plan now exceeds 700 lines... Post-this-edit: ~800 lines projected") and declines to split, citing §13.3 cross-ref preservation discipline as the blocker — flagging Pitfall #9.m in real-time. Plan is now 997 lines — 42% past the trigger. Acknowledged but unactioned.
**Fix**: either commit to the §13 split or update §13/§15 to relax the trigger explicitly.

### 🟡 D-8. Plan §16.1 mandates lead-with-answer; plan itself doesn't lead with answer in most sections
Spot-check: §1 leads with "Two coupled concerns" (heading-only; no direct answer). §3 leads with "Per udm-brainstorm discipline" (procedure-frame, not answer-frame). §5 starts directly with subsection header. The em-dash test artifact at `_research/em-dash-slug-test-2026-05-15.md` DOES lead with answer (per §15.2 Pattern b discipline). The plan demanding the discipline but not exemplifying it = Pitfall #9.m (discipline-not-applied-to-its-own-tracker).

### 🟡 D-9. Plan §13.4 mandates colon-form but plan §X.Y headings use period-form (`### §1.1`, `## §3`)
The colon-form mandate is specifically for D/B/R/RB/SP **ID-prefixed** headings (per §13.4 wording). Plan H2/H3 section headings like `## §1. Problem statement` use period-form which is also slug-safe per the empirical test. Not a violation strictly, but the plan never clarifies whether the rule applies to §X.Y headings too — ambiguous for future authors.

---

## §9. Drift between revisions

### 🟡 D-10. Header status text accumulates revisions without trimming
L3 status block is now 1 paragraph of ~1000 chars covering "4th revision" + 7 sub-bullets + total artifact count. Each revision appended; nothing pruned. New readers must parse the full revision history before reaching the actual plan content — anti-lead-with-answer.

### 🟢 OK. Q-13 + Q-22 resolution propagated to multiple sections
Status flips appear in §10 L447-449 + §13.4 L668 + §15.4 L786-811. Three locations all consistent.

### 🟡 D-11. §10 "Open questions" list and §16.6 Q-23-Q-26 list both append-only — no triage / prioritization
26 open questions, none flagged "blocker for sign-off" vs "nice-to-have." Pipeline-lead reviewing §12 sign-off has no triage signal among 26 questions. (Q-22, Q-13 are RESOLVED; 24 remain.)

---

## §10. Implicit assumptions worth surfacing

1. **Anthropic Claude Code stability over 1 year**: §16.4 milestones assume Anthropic Skills, subagent mechanism, llms.txt-format consumption all stay stable. Q11 quarterly refresh is the (only) hedge. No fallback if Anthropic deprecates skills or changes context loading.
2. **`_validation_log.md` remains append-only**: archive policy assumes this. If a future round introduces edit operations on the live file (e.g. to redact PII or fix typos), the archive cadence assumption breaks.
3. **Pipeline-lead availability for §12 sign-off**: plan blocks all execution on a single human approval. No fallback (e.g. "if no decision in 14 days, default to Phase 1.0 archive cascade only since both research + empirical baseline grade it as low-risk + high-value").
4. **Research-artifact authoring discipline scales**: 6 artifacts in 1 session is sustainable in burst mode; quarterly Q11 refresh assumes the same producer + budget continue. No succession plan if the current author rotates off.

---

## Top-5 most-impactful gaps to close before sign-off

1. **🔴 C-1 Fix §13.4 contradiction** — rewrite L658 + L663-664 to lead with colon-form. Anyone reading top-down gets the WRONG rule until L682. (~10 min edit; binding for ALL hygiene downstream)
2. **⚪ E-4 Author `_research/_INDEX.md`** — file is referenced 4× across plan + template as a binding governance artifact but does not exist. Without it, none of the 6 existing research artifacts are under discipline. (~30 min to author register + populate from 6 existing artifacts)
3. **🔴 C-2 Resolve archive trigger contradiction** — pick 2K (matches §9 metric + template) OR 5K (matches §16.1 table). One number, one place; remove the other. (~5 min edit)
4. **🔴 C-4 Either build `--report-large` flag or remove the claim** — plan says enforcement exists; tool says no. Honest options: implement the flag (~30 min) OR strike the row from §16.1 hygiene table (~2 min).
5. **🔴 C-5 + 🔴 C-3 Restructure plan** — at 997 lines, plan triggered its own split criterion AND has H2 numbering broken (§12 last; §14 missing). The split-or-renumber decision is itself blocking Pitfall #9.m closure. Recommendation: split into `MARKDOWN_REFACTOR_PLAN.md` (§1-§9, §11, §12) + `MARKDOWN_REFACTOR_PLAN_appendix.md` (§10b, §13, §15, §16) per the plan's own §13.1 naming. (~1 hour with cross-ref preservation per §13.3)

---

## Confidence rating

**🟢 High for contradiction findings** (C-1, C-2, C-3, C-4, C-5) — all empirically verified by reading the cited line numbers + running the tools + listing the filesystem.

**🟡 Medium for enforceability gaps** (E-1 through E-7) — claims are explicit in plan text; tooling absence is verified, but some may exist as planned-future-work the plan honestly defers. Sharper distinction between "shipped" vs "planned" enforcement would help.

**🟡 Medium for drift findings** (D-1 through D-11) — most are cosmetic / Pitfall #9.k style; none block sign-off; but cumulative drift across 4 revisions is symptomatic of the same Pitfall #9.m the plan claims to enforce.
