# Phase D.5 prep — CLAUDE.md trim to <300 lines (per Q-12 approval)

**Date**: 2026-05-15
**Phase**: D.5 reconnaissance for CLAUDE.md trim task per MARKDOWN_REFACTOR_PLAN.md §7.1 task 1.6 + §18 phase breakdown
**Trigger**: User-direction "Proceed with your suggested next step" 2026-05-15; cascade trigger picked HIGH-priority D.5 from runway
**Sub-agent inheritance**: per CLAUDE.md hard rule 13 + PLANNING_DISCIPLINE.md §3 — this reconnaissance is parent-agent solo work; no sub-agents spawned this turn
**Skill activation per `udm-planning-session-startup` v0.2**: PS-2 DOC scope; minimum-viable-set = udm-checks-and-balances + udm-progress-logger + udm-gap-check + udm-step-10-verifier (always-mandatory); conditional brainstorm + execution-classifier deferred until needed
**Outcome**: 🟡 **3 trim approaches surfaced; pipeline-lead choice required before destructive execution**

---

## §1. Empirical baseline

```
$ wc -l CLAUDE.md
720 CLAUDE.md
```

**Q-12 target**: <300 lines. **Reduction required**: ~420 lines (~58%).

## §2. Section-by-section categorization

| Lines | Section | Size | Category | Rationale |
|---|---|---|---|---|
| 1-12 | Header + Environment & Dependencies | 12 | **KEEP** | Essential — agent setup context |
| 13-96 | Structure (file inventory) | 84 | **KEEP** | Agent code-location lookup; per Anthropic best-practices "what applies broadly" |
| 97-102 | Known Issues & Backlog cross-ref | 6 | **KEEP** | Small + essential |
| 103-109 | Commands | 7 | **KEEP** | Essential operational |
| 110-125 | BCP CSV Contract | 16 | **KEEP** | Single source of truth per project convention |
| 126-150 | Table Naming Conventions | 25 | **KEEP** | Operational naming reference |
| 151-213 | Data Flow (per table) | 63 | **TRIM** | Existing canonical at `phase1/01c_data_flow_walkthrough.md`; replace with brief summary + cross-ref |
| 214-291 | Key Architecture Decisions | 78 | **TRIM** | Replace with summary + cross-ref to `phase1/01_database_schema.md` |
| 292-405 | Observability detail | 114 | **TRIM** | Extract to `phase1/02_configuration.md` or new sidecar; replace with summary |
| 406-409 | Deployment Requirements | 4 | **KEEP** | Small + critical |
| 410-497 | Gotchas (B-N + E-N + W-N + V-N + OBS-N + SCD2-* labels) | 88 | **TRIM** | Extract to new `CLAUDE_GOTCHAS.md` sidecar; cross-ref + brief category list |
| 498-537 | SQL Naming Standards (D105) | 40 | **KEEP** | Mandatory per D105 |
| 538-600 | Claude Code Security Model (D103 summary) | 63 | **COMPRESS** | Canonical at `SECURITY_MODEL.md`; compress summary to ~20 lines |
| 601-644 | Do NOT (rules) | 44 | **KEEP** | Mandatory safety rules |
| 645-651 | Autonomous Rules | 7 | **KEEP** | Small + essential |
| 652-706 | Validation discipline (hard rules 1-13) | 55 | **KEEP** | Hard rules canonical |
| 707-720 | Error Recovery | 14 | **KEEP** | Small + operational |

**KEEP subtotal**: 12 + 84 + 6 + 7 + 16 + 25 + 4 + 40 + 44 + 7 + 55 + 14 = **314 lines**

**TRIM/COMPRESS subtotal**: 63 + 78 + 114 + 88 + 63 = **406 lines**

**Sum check**: 314 + 406 = 720 ✅

## §3. Three trim approach options

### Approach A — Conservative (recommended; ~340 lines; ~40 over target)

Extract obvious sidecar candidates; preserve all KEEP content unmodified.

**Edits**:
1. **Lines 151-213 (Data Flow)** → replace with 5-line summary + cross-ref to `phase1/01c_data_flow_walkthrough.md`. Net: -58 lines.
2. **Lines 214-291 (Key Architecture Decisions)** → replace with 8-line summary + cross-ref to `phase1/01_database_schema.md`. Net: -70 lines.
3. **Lines 292-405 (Observability detail)** → replace with 15-line summary + cross-ref to `phase1/02_configuration.md` § Observability. Net: -99 lines.
4. **Lines 410-497 (Gotchas)** → extract verbatim to new `CLAUDE_GOTCHAS.md` sidecar; replace with 10-line category list + cross-ref. Net: -78 lines (sidecar = +88 new file).
5. **Lines 538-600 (Security Model summary)** → compress to 20-line essentials + cross-ref to `SECURITY_MODEL.md` canonical. Net: -43 lines.

**Result**: 720 − 348 = **372 lines** (still 72 over target).

Hmm — my §2 categorization underestimates the trim impact because the cross-ref replacements add small content. Let me recalculate.

Edits save: 58 + 70 + 99 + 78 + 43 = 348 lines. Result = 720 − 348 = **372 lines** (under previous estimate of 340; need to be more aggressive OR revisit Q-12).

### Approach B — Aggressive (~270 lines; under target)

All of Approach A PLUS:
6. **Lines 13-96 (Structure)** — compress to top-level subsection list with `<details>`-style cross-refs to `phase1/01_database_schema.md` for module-level surfaces. Net: -50 lines.
7. **Lines 652-706 (Hard rules 1-13)** — compress to numbered list of titles + cross-ref to `docs/migration/SELF_IMPROVEMENT_DISCIPLINE.md` + `CHECKS_AND_BALANCES.md` + `PLANNING_DISCIPLINE.md` for full detail. Net: -45 lines.

**Result**: 720 − 348 − 95 = **277 lines** (under target ✅).

**Risk**: Anthropic best-practices specifically warns "Only include things that apply broadly" — Structure DOES apply broadly (every agent needs to locate code). Compressing Structure may hurt activation reliability for code-location tasks. Hard rules compression similarly risks reducing rule-discipline application.

### Approach C — Restructure (split into CLAUDE.md + sidecar)

Split CLAUDE.md into 2 files:
- **CLAUDE.md** (always-load; ~280 lines): Header + Environment + Structure + Commands + BCP Contract + Naming + Do NOT + Hard rules + Read order + Error Recovery
- **CLAUDE_OPERATIONAL.md** (reference-on-demand; ~400 lines): Data Flow + Architecture Decisions + Observability detail + Gotchas + Security Model summary

CLAUDE.md cross-refs CLAUDE_OPERATIONAL.md at top: "For operational reference (data flow, observability, gotchas, security model summary), see `CLAUDE_OPERATIONAL.md`."

**Result**: CLAUDE.md = ~280 lines (under target ✅); CLAUDE_OPERATIONAL.md = ~400 lines (new sidecar).

**Risk**: split convention different from rest of repo. Per CodeCompass Navigation Paradox research, agents may skip the cross-ref to CLAUDE_OPERATIONAL.md 58% of the time → operational context lost.

**Mitigation**: place cross-ref at END of CLAUDE.md per CodeCompass 100%-adoption finding for end-of-prompt structural enforcement (per PLANNING_DISCIPLINE.md §2.6 v0.2).

## §4. Recommendation

**Approach A (recommended)** with one revision: **revisit Q-12 target** to ~400 lines if conservative-extract math holds at ~372 lines actual. Q-12 was approved with "<300 lines" target, but the empirical KEEP analysis shows ~314 lines is the floor for essential always-load content. A ~370-400 line CLAUDE.md is a ~50% reduction from 720, still substantial CCL leverage.

**Approach B** if pipeline-lead insists on <300 target — accepting the Structure-compression risk + hard-rule-compression risk. Mitigated by aggressive cross-refs at end of compressed sections per CodeCompass research.

**Approach C** if pipeline-lead prefers a structural split — but this is a different conventional pattern (no other docs/migration file is split this way; cross-refs to a sidecar may have lower discoverability than inline content).

## §5. Risks (per CodeCompass Navigation Paradox arxiv 2602.20048)

1. **Cross-ref skipping**: agents skip following cross-refs 58% of the time. Mitigation: place cross-refs at END of each section (per PLANNING_DISCIPLINE.md §2.6 v0.2); include explicit "you MUST follow this cross-ref to <X>" framing for load-bearing references.
2. **Content fragmentation**: extracted content lives in multiple files; future updates must propagate (Pitfall #9.k arithmetic-propagation drift risk). Mitigation: each TRIM/COMPRESS edit includes a clear "canonical = <X>" marker so producers know where to update.
3. **Sidecar discoverability**: new `CLAUDE_GOTCHAS.md` may not be discovered by agents who don't read CLAUDE.md fully. Mitigation: add to CLAUDE.md Read order list.
4. **Backwards-compat**: agents that have memorized CLAUDE.md gotcha-line locations will get drift. Mitigation: trim is doc-only; git history preserves the verbatim content.

## §6. 5-gate validation per `udm-checks-and-balances` (post-execution)

When trim executes, apply 5-gate validation:
- **Gate 1 — Cross-reference**: every TRIM/COMPRESS section's cross-ref MUST point to a valid existing file path
- **Gate 2 — QA**: pytest unchanged (doc-only); manual spot-check of compressed sections
- **Gate 3 — Edge cases**: agents reading trimmed CLAUDE.md still have access to load-bearing rules (Do NOT + Hard rules + BCP Contract preserved verbatim)
- **Gate 4 — Edge case validation**: spawn `udm-gap-check` independent reviewer to verify trim doesn't drop load-bearing content
- **Gate 5 — Idempotency/regression**: re-run trim should be a no-op (idempotent); git diff should be clean after second trim

## §7. Acceptance criteria for D.5 trim execution (post-approval)

✅ CLAUDE.md line count = chosen target (Approach A: ~370-400; Approach B: <300; Approach C: <300)
✅ All TRIM/COMPRESS extractions preserve content verbatim in destination files
✅ Every removed section has a cross-ref to where content moved
✅ Pytest unchanged (`2320 / 58 / 0`)
✅ `udm-step-10-verifier` ✅ N/A or ✅ CLEAN for any new sidecar files
✅ `udm-gap-check` independent reviewer verdict ≤🟡
✅ `udm-checks-and-balances` 5-gate verdict ≤🟡 per §6
✅ Pipeline-lead post-trim review approves

## §8. Pipeline-lead decision required

**Choose Approach A / B / C** (or redirect / partial / different idea).

If A: I execute the trim ~370-400 line target; Q-12's <300 target relaxed to "<400 with floor justification".

If B: I execute the trim <300 target; accept Structure + Hard rules compression risk.

If C: I execute the split; CLAUDE.md becomes ~280 lines + CLAUDE_OPERATIONAL.md ~400 lines sidecar.

All approaches:
- ~30-60 min execution time
- 5 file modifications (CLAUDE.md + 3-5 sidecar/cross-ref destinations)
- Doc-only (no pytest impact)
- Reversible via `git revert`
- Tracker pass + commit + udm-gap-check + 5-gate at attestation
