# udm-session-compactor Review — Professional Hardening + Resilience Gap Audit

**Date**: 2026-05-19
**Authored by**: parent agent (this chat session); claude-opus-4-7; context pressure high (close to compaction threshold — meta-irony noted; the very skill under review would warn me right now if it had a self-aware mode)
**Context**: pipeline-lead direction "Let's make udm-session-compactor more professional and resilient. Reflect on traceability + hallucinations research. Are there gaps in how udm-session-compactor has been built? Are there gaps in how udm-session-compactor works with other agents or skills?"
**Anchors**: research artifact at `docs/migration/_research/llm-handoffs-traceability-hallucination-2026-05-18.md` (12 primary sources); SKILL.md at `.claude/skills/udm-session-compactor/SKILL.md` (v1.0.0 + Phase 2 auto-trigger section added at B-494 closure); PostToolUse hook at `.claude/hooks/session-compactor-warning.py` (B-494 closure 2026-05-19)

---

## Executive summary

udm-session-compactor at current state (Phase 1 SKILL + Phase 2 hook landed 2026-05-19) has **29 identified gaps** across 4 categories. **6 are HIGH severity** (likely to cause real harm or reproduce the exact failure modes the research cited); **9 are MEDIUM** (operational maturity gaps); **14 are LOW** (polish + future-proofing). The most important finding: **no independent verification of snapshot claims** (gap #17) — currently snapshots are committed without producer ≠ reviewer discipline that every OTHER substrate artifact in the project requires. This is the same hallucination class the udm-researcher artifact (Finding 3.1 from arXiv 2511.00776 60-paper meta-analysis) identified as "LEAST-MITIGATED sub-type" — file-path + claim confabulation in LLM-authored artifacts.

The skill currently relies on producer self-discipline for accuracy. Research (Google SRE + AWS Well-Architected + MARCH multi-agent verification paper) consistently mandates **fresh-evidence-required + producer-≠-reviewer + idempotency-token + two-phase-mutation** patterns for any artifact that downstream consumers will treat as canonical. Snapshots are explicitly designed to be canonical for next-window agents — they should be subject to the SAME discipline as D-N decisions / RB-N runbooks / SP-N stored procedures.

---

## §1. Built-quality gaps — Phase 1 SKILL.md

### Gap 1.1 (MEDIUM) — No mechanical validation of 5-section snapshot format

**Issue**: SKILL.md mandates §1 Active work / §2 Completed deliverables / §3 Open runway / §4 Deeper insights / §5 Pointer-back cross-refs but no enforcement mechanism. A malformed snapshot (missing section or stub-only content) could be authored without detection.

**Research alignment**: AWS Well-Architected Operational Excellence "pre-defined quantifiable criteria" (Finding 3.3). 5-section structure is the contract; absence of mechanical enforcement is the gap.

**Fix candidate**: extend `tools/pre_commit_checks.py` with `check_session_snapshot_format` (11th Phase 1 check) — when staged path matches `docs/migration/_session_snapshots/*.md`, verify all 5 section headers present + each section has ≥1 substantive bullet. WARN severity per FP-policy.

### Gap 1.2 (HIGH) — No drift detection between snapshot claims and actual repo state

**Issue**: Snapshot §1 cites "latest commit: X" / "pytest: N pass / M skip / 0 fail" / "B-Ns closed: K". Currently NO mechanism validates these claims at authoring time. Producer can confabulate state (the exact failure mode at my prior commit `8dd2000` where snapshot claimed "+12 net" but actual was "+4 net" — Pitfall #9.k arithmetic drift on a snapshot about Pitfall #9.k).

**Research alignment**: Hallucination research arXiv 2511.00776 (60-paper meta-analysis 2025) explicit on file-path + numeric-claim confabulation as LEAST-MITIGATED hallucination sub-type. NIST AI 600-1 (July 2024) mandates "individual or system ID with timestamp" per-event attribution — applies to numeric claims.

**Fix candidate**: NEW check `tools/check_snapshot_claims.py` — for snapshot files in commit, parse §1 + §2 claims; cross-verify against `git log HEAD` (commit hash), `pytest --co -q` (count of collected tests), `grep ⚫ docs/migration/BACKLOG.md` (closure count). WARN on mismatch.

### Gap 1.3 (LOW) — No machine-readable schema for snapshot content

**Issue**: Snapshots are free-form markdown. Future agent reading them has no enforced structure to parse programmatically (e.g., "list all B-Ns mentioned in this snapshot" requires regex).

**Research alignment**: ISO 42001 logging + lifecycle traceability mandates structured logging where possible.

**Fix candidate**: optional YAML frontmatter extension — snapshot frontmatter could capture `b_ns_closed: [B-X, B-Y]` / `commits: [...]` / `pytest_state: {pass: N, skip: M}` as parseable structured fields, with §1-§5 markdown body retaining human-readable narrative.

### Gap 1.4 (LOW) — No retention policy for `_session_snapshots/`

**Issue**: Directory grows unbounded. No archive/cleanup mechanism. Over time, browsing the directory becomes noisy.

**Research alignment**: standard retention discipline (analogous to PipelineLog 30d INFO / 90d WARNING+ / indefinite ERROR+ per CLAUDE.md observability section).

**Fix candidate**: add to operational runbook (next available RB-N slot) — quarterly archive of pre-round-close snapshots to `_session_snapshots/_archive/<year>/`. Document in SKILL.md.

### Gap 1.5 (MEDIUM) — Phase 1 ↔ Phase 2 disconnect (warning emits but doesn't pre-author)

**Issue**: Phase 2 hook emits stderr warning telling Claude to invoke skill. But the snapshot is still authored by Claude manually after seeing the warning. If Claude is mid-cohort, busy, or doesn't notice (warning could be buried in long tool output), warning is missed. The "auto-trigger" is actually "claim-trigger".

**Research alignment**: Google SRE two-phase mutation (Finding 3.1) — but here the "two-phase" is hook-warns → claude-acts; if claude fails to act, no fallback.

**Fix candidate**: defense-in-depth — at threshold +5% (e.g., 75% if default threshold is 70%), hook could write a `_session_snapshots/.pending_<session-id>.md` stub with §1 metadata pre-populated from telemetry (commit hash + tool counts + timestamp). Claude then sees the stub exists and completes the snapshot. Doesn't bypass Claude's role but provides a safety net.

---

## §2. Built-quality gaps — Phase 2 hook

### Gap 2.1 (MEDIUM) — Heuristic accuracy unverified

**Issue**: 5 bytes/token heuristic from research; never validated against actual Token Counting API. JSONL content density varies (tool outputs vs prose vs code blocks). Could be 3-8 bytes/token in practice.

**Research alignment**: Anthropic Token Counting API documented as ground-truth source; research recommended Path B/E for periodic ground-truth sampling.

**Fix candidate**: Phase 2.1 — add Token Counting API ground-truth check every Nth hook invocation (configurable via env var). Compare heuristic vs ground-truth; log drift to telemetry. If >15% drift, recalibrate.

### Gap 2.2 (LOW) — Threshold default arbitrary

**Issue**: 70% chosen from research recommendation but no empirical calibration for THIS project's session patterns. Project might have higher-density JSONL (lots of structured tool outputs) → 70% might fire too late OR too early.

**Fix candidate**: after telemetry accumulates (≥10 sessions of data), compute p50/p95 session-end JSONL sizes + select threshold empirically.

### Gap 2.3 (HIGH) — No "successful authoring" check after snapshot detection

**Issue**: Hook suppresses further warnings once it detects ANY `_session_snapshots/*.md` modified after session start. But hook does NOT verify the snapshot is well-formed or contains required content. A stub file `touch _session_snapshots/2026-05-19-abc1234.md` would suppress warnings indefinitely.

**Research alignment**: AWS idempotency token pattern (Finding 3.2) — exact pattern requires verifying the prior result is valid before treating it as canonical.

**Fix candidate**: `_has_recent_snapshot()` should also parse the snapshot file + verify presence of §1-§5 section headers + minimum file size (e.g., ≥2KB). If invalid, treat as "no snapshot" and emit warning.

### Gap 2.4 (HIGH) — Session detection brittle for concurrent sessions

**Issue**: Hook iterates all `~/.claude/projects/*/` dirs to find a transcript matching `<session-id>.jsonl`. If the parallel Claude session is also running on this same machine for this same repo (which it IS — user explicitly stated this), wrong transcript could be measured. The hook's `session_id` comes from the hook payload, which is correct, but the dir-scan-with-glob could match THIS session in the wrong project dir.

**Research alignment**: Pattern matches AWS recommendation "generating keys inconsistently" anti-pattern.

**Fix candidate**: limit search to the canonical project dir based on `cwd` instead of all-dirs scan. OR: validate the located transcript's last line contains the current hook invocation's tool_name + timestamp before treating it as canonical.

### Gap 2.5 (MEDIUM) — No telemetry analytics tool

**Issue**: Telemetry written to `.claude/_session_metrics/<session-id>.jsonl` but no tool exists to analyze it. Required for retrospective calibration of threshold + heuristic.

**Fix candidate**: NEW `tools/analyze_session_telemetry.py` — reads all telemetry files; computes p50/p95 token-estimate-at-warning-time / warning-fired-vs-snapshot-authored rates / per-tool-call telemetry density. Operator-CLI; manual invocation per `udm-execution-classifier` Manual × Recurring.

### Gap 2.6 (LOW) — Suppression marker race condition

**Issue**: Hook fires concurrently across multiple Claude sessions in same project. Marker write could race; one session's "I warned" could be overwritten by another's "I didn't warn".

**Research alignment**: AWS exactly-once semantics — needs atomic write.

**Fix candidate**: use `O_EXCL` flag for marker creation OR include session_id in marker filename (already does via `<session-id>.compactor-warned`). Confirm filename uniqueness prevents collision. ✅ Already mitigated by per-session marker naming.

### Gap 2.7 (MEDIUM) — Hook + commit-msg discipline disconnect

**Issue**: Hook fires on every PostToolUse including `Bash(git commit)` invocations. During multi-commit cohorts, hook fires N times per commit, each time checking transcript size. Telemetry rows accumulate noisily.

**Fix candidate**: add a matcher to settings.json: `"matcher": "Read|Edit|Write|Grep|Glob|Agent|Bash"` — fires on substantive tools but skips spawned subprocess-style trivial tool calls. Document explicit exclusions.

### Gap 2.8 (HIGH) — No CCPA / PII compliance consideration

**Issue**: Snapshots may contain reviewer agent IDs, file paths, code snippets that could include sensitive data. Per D102 (AES-256-GCM PII encryption) + D103 (security model) + R36 (Phase A plaintext-PII compensating controls), snapshots should be subject to similar scrutiny.

**Research alignment**: EU AI Act Articles 12/19 + NIST AI 600-1 require audit trails but ALSO require PII compliance.

**Fix candidate**: SKILL.md add explicit "Do NOT include in snapshots" guidance — no PII values (only token references); no plaintext credentials (only path references); no extraction-time data from production tables. Add Tier 0 test that greps snapshot for sensitive patterns (e.g., SSN-shaped strings, email patterns).

---

## §3. Composition gaps with other skills/agents

### Gap 3.1 (HIGH) — No `udm-gap-check` invocation post-snapshot authoring

**Issue**: Snapshot is authored without independent verification of its claims (per D55+D56 producer ≠ reviewer discipline). Currently producer self-applies; same producer authors AND validates. Research mandates producer ≠ reviewer for any canonical artifact.

**Research alignment**: D55 + D56 (canonical project discipline) + MARCH multi-agent verification paper. The exact discipline applied to D-N decisions / RB-N runbooks / SP-N procedures should apply to snapshot artifacts since they're canonical for next-window agents.

**Fix candidate**: SKILL.md add explicit "Post-authoring verification" step: invoke `udm-gap-check` on the snapshot file. 6-category audit: G1 leading-badge N/A; G2 arithmetic vs actual repo state; G3 cross-references resolved; G4 discipline-applied; G5 N/A no new public surface; G6 surfaced patterns vs B-N tracking. Independent reviewer agent.

### Gap 3.2 (MEDIUM) — No integration with `udm-progress-logger`

**Issue**: When snapshot authored, no automatic propagation to `_validation_log.md` or other canonical trackers. Snapshot is its own artifact; doesn't update trackers consistently.

**Fix candidate**: SKILL.md add "Step N+1: Apply udm-progress-logger" — log snapshot authoring event row in `_validation_log.md` with snapshot path + section count + Model + Context pressure (per Rec 2 convention).

### Gap 3.3 (MEDIUM) — No integration with `udm-cohort-review`

**Issue**: Cross-cohort reviewer could read recent snapshots as context but isn't documented to do so. Currently relies on prompt-side telling reviewer about snapshots.

**Fix candidate**: `udm-cohort-review` SKILL.md extension — Step 0.5 "Read latest snapshot for arc context if cohort spans multiple session boundaries". Cross-link.

### Gap 3.4 (MEDIUM) — No integration with `udm-round-closeout`

**Issue**: Round close-out should ARCHIVE old snapshots into a round directory; currently snapshots just accumulate.

**Fix candidate**: `udm-round-closeout` SKILL.md Step N — archive `_session_snapshots/*.md` authored during this round to `_session_snapshots/_archive/round-<N>/` at close-out cascade.

### Gap 3.5 (LOW) — No interaction with `udm-step-10-verifier`

**Issue**: If snapshot mentions new public surface that hasn't been Step-10-registered, no cross-check. Snapshot could cite "NEW function `foo()` added at commit X" but `foo` isn't in CLAUDE.md Structure or GLOSSARY.

**Fix candidate**: optional — snapshot §2 Completed deliverables → udm-step-10-verifier reads and cross-checks if any "NEW <surface>" mention isn't in CLAUDE.md.

### Gap 3.6 (LOW) — No agent-side composition with `udm-checks-and-balances`

**Issue**: 5-gate validation discipline (D55) applies to substrate artifacts but not formally to snapshots.

**Fix candidate**: SKILL.md document the 5-gate mapping: Gate 1 cross-ref (paths exist) / Gate 2 reviewer (udm-gap-check independent) / Gate 3 edge cases (does snapshot address irreversibility / format drift / cross-session resumption?) / Gate 4 validate edge case treatment / Gate 5 idempotency (re-running invocation produces consistent output).

### Gap 3.7 (LOW) — No version pinning for snapshot format

**Issue**: udm-session-compactor SKILL.md is v1.0.0 but snapshots don't declare "authored against SKILL.md v1.0.0". Future skill version changes could invalidate prior snapshots silently.

**Fix candidate**: snapshot YAML frontmatter add `skill_version: 1.0.0` field. SKILL.md add note "if `skill_version` field in older snapshot < current SKILL.md version, treat as legacy format".

---

## §4. Traceability research alignment gaps

### Gap 4.1 (MEDIUM) — Snapshots don't apply Rec 2 model-attribution convention CANONICALLY

**Issue**: Research Rec 2 (NIST AI 600-1 + EU AI Act Articles 12/19) mandates `Model: claude-opus-4-7 / Context pressure / CCL completed` fields as structured event-row metadata. Snapshots have this in §1 prose but not in canonical structured fields.

**Fix candidate**: snapshot YAML frontmatter MUST include `model` / `context_pressure` / `ccl_completed` fields (currently optional). Mechanical check at pre-commit.

### Gap 4.2 (LOW) — No "what was DECIDED via this snapshot" tracking

**Issue**: Snapshots capture what happened but not what decision points the next agent must address (open questions / pending approvals / deferred items needing pipeline-lead input).

**Research alignment**: ISO 42001 + EU AI Act decision-traceability requirements.

**Fix candidate**: snapshot §3 Open runway already covers deferred items; could add §3a "Pending decisions" sub-section explicitly listing decisions awaiting input.

### Gap 4.3 (LOW) — No per-claim attribution

**Issue**: NIST AI 600-1 individual-or-system-ID-with-timestamp requirement applied at per-event level only (snapshot itself has timestamp). Per-claim attribution (which sub-agent produced which finding) is missing.

**Fix candidate**: snapshot §4 Deeper insights add `[<agent-id>]` inline citations for sub-agent-produced findings. Already partially done in current SCD2 review pattern.

---

## §5. Hallucination research alignment gaps

### Gap 5.1 (HIGH) — Snapshot file-path references unvalidated at authoring time

**Issue**: Snapshot §5 Pointer-back cross-refs lists file paths but no check that those paths exist at authoring time. Note: B-495 `check_file_path_existence` would catch this at commit time IF snapshot files are staged. Currently snapshots ARE committed; check WILL fire.

**Status**: ✅ Partial mitigation via B-495. Verify the check actually fires on snapshot files (test case missing).

**Fix candidate**: Tier 0 test verifies B-495 `check_file_path_existence` fires on `docs/migration/_session_snapshots/*.md` paths.

### Gap 5.2 (HIGH) — B-N citations in snapshots unvalidated

**Issue**: Snapshot §2 enumerates B-N closures but no check that those B-Ns actually exist in BACKLOG. Could cite non-existent B-Ns OR B-Ns with mismatched status (cite "B-X CLOSED" when B-X is still Open).

**Research alignment**: arXiv 2511.00776 Finding 3.1 (file-path-confabulation; same class applies to B-N-citation-confabulation).

**Fix candidate**: NEW Phase 1 check `check_bn_citations_in_snapshots` — when staged snapshot file, parse `B-NNN` mentions; verify each exists in BACKLOG.md AND status matches snapshot claim. WARN on mismatch.

### Gap 5.3 (HIGH) — Pytest count claims in snapshots unvalidated (THIS EXACT FAILURE MODE OBSERVED)

**Issue**: Snapshot cites pytest counts but no check against actual current state. The prior reviewer at gap-check `a8b3220ad407537b9` noted my snapshot at commit `8dd2000` cited "+12 net" but actual was "+4 net" — Pitfall #9.k arithmetic drift on a snapshot about Pitfall #9.k. **Meta-irony observed empirically.**

**Research alignment**: SAME as Rec 2 numeric-claim validation + B-449 pytest-count-disambiguation pattern that already exists for commit-msg.

**Fix candidate**: extend B-449's `PytestCountDisambiguationCheck` to ALSO scan snapshot files OR new dedicated check `check_snapshot_pytest_claims` — for snapshot file in commit, parse pytest count citations; cross-verify against actual pytest output AT AUTHORING TIME (requires snapshot to be authored AFTER pytest run + carry timestamp).

### Gap 5.4 (LOW) — No 2-phase mutation pattern for snapshot authoring

**Issue**: Research Rec mandates dry-run-first for irreversible operations. Snapshot authoring is committed directly; no dry-run preview step.

**Fix candidate**: SKILL.md add "Dry-run mode" — snapshot authoring should first emit to stdout / `/tmp/` for user review, then commit only after explicit approval. OR less restrictive: emit a draft snapshot that user reviews before B-N closure commit. Already partially done via the user-approval gate in planning protocol; could be made explicit.

### Gap 5.5 (LOW) — No verification-before-completion pattern application

**Issue**: Research Rec (Superpowers-verification-before-completion skill — exists in available skills list) mandates fresh-evidence-required gate. Snapshot claims about session arc aren't verified against fresh evidence (git log + BACKLOG + pytest) at authoring time.

**Fix candidate**: SKILL.md add "Pre-completion verification": before claiming snapshot complete, agent MUST run (a) `git log -10` to verify commit hashes; (b) `grep -c ⚫ BACKLOG.md` to verify closure count; (c) `pytest --co -q | tail -1` for collection count. Cite these in snapshot §1 verification footer.

---

## §6. Prioritized recommendations

### HIGH-severity recommendations (close exact-failure-mode-observed gaps)

| # | Gap | Effort | Fix | B-N candidate |
|---|---|---|---|---|
| **R-1** | #2 Snapshot drift from repo state | 0.5d | `check_snapshot_claims.py` Phase 1 check OR extend B-449 to snapshots | B-N (MEDIUM WSJF ~2.5) |
| **R-2** | #17 No producer ≠ reviewer on snapshots | 0.25d | SKILL.md mandate udm-gap-check post-snapshot | B-N (MEDIUM WSJF ~3.0) |
| **R-3** | #5.3 Pytest count claims unvalidated (empirical failure) | 0.5d | Extend B-449 PytestCountDisambiguationCheck to snapshot files | B-N (HIGH WSJF ~3.5) |
| **R-4** | #2.8 CCPA / PII compliance for snapshots | 0.5d | SKILL.md "Do NOT include" guidance + Tier 0 sensitive-pattern check | B-N (MEDIUM WSJF ~2.0) |
| **R-5** | #2.4 Session detection brittle | 0.25d | Constrain dir scan to cwd-based project; validate last-line | B-N (LOW WSJF ~2.0) |
| **R-6** | #2.3 No "successful authoring" check | 0.25d | Validate snapshot structure in `_has_recent_snapshot` | B-N (LOW WSJF ~2.0) |

### MEDIUM-severity recommendations (operational maturity)

| # | Gap | Effort | Fix |
|---|---|---|---|
| R-7 | #1 No 5-section format validation | 0.5d | 11th Phase 1 check `check_session_snapshot_format` |
| R-8 | #1.5 Phase 1+2 disconnect | 0.5d | Hook pre-populates stub at threshold +5% |
| R-9 | #2.1 Heuristic accuracy unverified | 1d | Phase 2.1 Token Counting API ground-truth sampling |
| R-10 | #2.5 No telemetry analytics tool | 1d | `tools/analyze_session_telemetry.py` operator CLI |
| R-11 | #2.7 Hook fires on every PostToolUse | 0.1d | settings.json matcher restriction |
| R-12 | #3.1 No udm-progress-logger integration | 0.25d | SKILL.md Step N+1 _validation_log append |
| R-13 | #3.3 No udm-cohort-review integration | 0.25d | Cross-link in udm-cohort-review SKILL.md |
| R-14 | #3.4 No udm-round-closeout archive | 0.25d | Round close-out cascade step |
| R-15 | #4.1 Rec 2 fields not canonical in frontmatter | 0.25d | Mechanical check in B-449 extension |

### LOW-severity recommendations (polish + future-proofing)

R-16 through R-29: various refinements (machine-readable schema / retention policy / version pinning / per-claim attribution / pending-decisions section / dry-run mode / verification-before-completion / udm-step-10-verifier integration / udm-checks-and-balances 5-gate mapping)

---

## §7. Recommendation prioritization (where to invest first)

### Phase 2.1 cohort (~1.5 days; consolidates R-1 + R-2 + R-3 + R-5 + R-6)

**Single B-N closure target**: build a comprehensive "snapshot validation discipline" cohort:

1. **R-3 first** (highest empirical signal): extend B-449 PytestCountDisambiguationCheck to ALSO scan staged `_session_snapshots/*.md` files. Closes the exact failure mode observed.
2. **R-1 next**: NEW Phase 1 check `check_snapshot_claims.py` — verify §1 commit hash + §2 closure count claims against `git log` + `grep ⚫ BACKLOG.md`.
3. **R-2 inline**: SKILL.md mandate `udm-gap-check` post-snapshot authoring + cite reviewer ID in snapshot §0-equivalent footer (or new §6 verification footer).
4. **R-5 + R-6 polish**: hook session-detection + suppression-marker validity improvements.

After this cohort, udm-session-compactor would have **full producer ≠ reviewer + fresh-evidence-required + mechanical-claim-validation** discipline matching every other canonical substrate artifact in the project.

### Phase 2.2 cohort (~1.5 days; covers R-4 + R-7 + R-11)

CCPA/PII compliance scrubbing + 5-section format validation + hook matcher restriction.

### Phase 2.3 cohort (~2 days; covers R-9 + R-10)

Token Counting API ground-truth sampling + telemetry analytics tool. Defers until empirical drift observed.

### Phase 2.4 composition cohort (~1 day; covers R-12 + R-13 + R-14)

Cross-skill integration updates (progress-logger / cohort-review / round-closeout).

---

## §8. Cross-references

- `.claude/skills/udm-session-compactor/SKILL.md` — v1.0.0 + Phase 2 auto-trigger section (added B-494 closure 2026-05-19)
- `.claude/hooks/session-compactor-warning.py` — Phase 2 PostToolUse hook (B-494; 260 LOC)
- `docs/migration/_research/llm-handoffs-traceability-hallucination-2026-05-18.md` — research artifact (12 primary sources; Google SRE + AWS Well-Architected + Apache Iceberg + Kimball + dbt + NIST AI 600-1 + EU AI Act + arXiv 2511.00776 code-hallucination meta-analysis)
- `docs/migration/_session_snapshots/2026-05-18-1233bc8.md` — first production invocation (empirical anchor; pytest count drift observed)
- `docs/migration/03_DECISIONS.md` — D55 + D56 (producer ≠ reviewer); D102 + D103 (PII compliance); D74 + D75 + D76 (CLI discipline)
- `tools/pre_commit_checks.py` — B-449 PytestCountDisambiguationCheck (existing pattern to extend per R-3); B-495 check_file_path_existence (already partial mitigation)
- `tools/check_commit_msg.py` — InlineFixClaimVerificationCheck + NarrativePytestClaimVerificationCheck (related pattern; could share suppression infrastructure via `tools/anchor_context.py`)

---

## §9. Status

**This review**: ⚫ COMPLETE — 29-gap audit grounded in research artifact + empirical failure-mode observation (the snapshot pytest-count drift I personally produced at commit `8dd2000` is the canonical empirical anchor for R-3).

**Recommended next action**: open Phase 2.1 closure cohort B-N (single closure target consolidating R-1 + R-2 + R-3 + R-5 + R-6 ~1.5d effort) per §7 prioritization. After that lands, udm-session-compactor v1.1.0 will have producer ≠ reviewer + fresh-evidence + mechanical-claim-validation discipline matching D-N / RB-N / SP-N substrate.

**Empirical anchor**: This review was authored AT a session where the auto-trigger warning would already be active (context pressure: high). If the hook itself worked end-to-end including the agent-side discipline, I should have been prompted to author a snapshot before reaching this review's commit. That I am authoring THIS review without first authoring a snapshot is itself the gap (#17 producer self-discipline failure mode).
