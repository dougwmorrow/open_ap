# Next Steps — captured 2026-05-12 post-gap-analysis on POLISH_QUEUE.md

**Trigger**: gap analysis on newly-authored `POLISH_QUEUE.md` surfaced MUST-FIX correctness gaps + SHOULD-FIX discipline gaps + NICE-TO-HAVE polish items. User direction: "Take down as a note as to what next steps are." (User also redirected: research Tolaria + Graphify GitHub repos in parallel — that work is tracked separately at `_research/tolaria-2026-05-12.md` + `_research/graphify-2026-05-12.md` once authored; deliberate scope-separation.)

**Format**: phased action list with effort estimates. Items are NOT priority-sorted within phase; pick any order within a phase.

---

## Phase A — MUST-FIX (factual / operationalization; this session, ~15 min)

**Phase A status**: ✅ **LANDED 2026-05-12** (D113 fix-cascade — all 3 items closed inline; see `_validation_log.md` 2026-05-12 D113 lock entry for full Gate 1/2/5 documentation).

### ~~A.1~~ ✅ LANDED 2026-05-12: Correct P-4 archive policy misquote in POLISH_QUEUE.md

- **File**: `docs/migration/POLISH_QUEUE.md` L82-85 (P-4 body)
- **Errors**:
  - Threshold unit wrong: `~120 KB` should be `~2000 lines`
  - Threshold value wrong: file is currently 2659 lines — threshold ALREADY exceeded, not "approaching"
  - Archive shape wrong: P-4 claims `_archive/` subdirectory + by-round naming; real policy at `_validation_log.md:14-19` says sibling file `_validation_log_archive_<YYYY-MM>.md` + by-month naming + keep last ~30 days
  - Closure-target off by one round event: P-4 says `"Phase 2 R1 kickoff"`; real policy at `_validation_log.md:23` says `"at Phase 2 R1 close-out"`
- **Action**: rewrite P-4 body verbatim against the actual archive-policy text

### ~~A.2~~ ✅ LANDED 2026-05-12: Update `udm-round-closeout/SKILL.md` to include POLISH_QUEUE.md

- **File**: `.claude/skills/udm-round-closeout/SKILL.md`
- **Current state**: grep shows zero POLISH_QUEUE / P-number references; CCL Stage 2 says `RISKS.md, BACKLOG.md, _validation_log.md`
- **Action**: add POLISH_QUEUE.md to CCL (Stage 2 OR Stage 2.5) + add a checklist item under round close-out: "Skim POLISH_QUEUE 🟡 items the round touched → close inline if the closing round's work covered them"
- **Why**: without skill update, the L133 POLISH_QUEUE claim "Skim it at round close-outs" is aspirational

### ~~A.3~~ ✅ LANDED 2026-05-12: Update `udm-cascade-audit-evolver/SKILL.md` to audit POLISH_QUEUE.md at Pattern F

- **File**: `.claude/skills/udm-cascade-audit-evolver/SKILL.md`
- **Current state**: grep shows zero POLISH_QUEUE / P-number references; Pattern F Layer 2 doesn't include POLISH_QUEUE in scope
- **Action**: add POLISH_QUEUE.md to Pattern F Layer 2 audit scope at round close-out (audit ⚫ CLOSED entries from the closing round + audit 🟡 Open entries to confirm they're genuinely cosmetic, not B-candidates in disguise)
- **Why**: without skill update, the L143 POLISH_QUEUE claim "Pattern F still reviews POLISH_QUEUE.md" is aspirational

---

## Phase B — SHOULD-FIX (discipline integration; this session OR Phase 2 R1 kickoff, ~10 min)

**Phase B status**: ✅ **LANDED 2026-05-12** (D113 fix-cascade — all 4 items closed inline; D113 🟢 Locked + cascade across 9 docs; see `_validation_log.md` 2026-05-12 D113 lock entry).

### ~~B.1~~ ✅ LANDED 2026-05-12: NORTH_STAR pillar mapping in POLISH_QUEUE.md

- **Action**: add a "Pillar mapping per D61" section to POLISH_QUEUE.md citing **Audit-grade** (preserves render-discipline trail) + **Traceability** (every cosmetic change has dated audit row)

### ~~B.2~~ ✅ LANDED 2026-05-12: Risk delta in POLISH_QUEUE.md

- **Action**: add a "Risk delta per D61" section noting POLISH_QUEUE de-escalates a sub-class of R28 (cascade self-attestation gap) — render-drift now has a dedicated home instead of leaking into BACKLOG WSJF view or `_validation_log.md` ad-hoc deferral lists

### ~~B.3~~ ✅ LANDED 2026-05-12: Lock P-N scheme as D113 in `03_DECISIONS.md`

- **Action**: draft D113 "POLISH_QUEUE.md cosmetic-tracker discipline" — 🟢 directly per D111 exemption for process-infra (analogous to D55 5-gate / D60 round close-out / D89-D91 Pattern F / D95-D99 self-improvement — all process-discipline D-numbers locked 🟢 at first authoring); cite precedent
- **D-body skeleton**: scope (cosmetic items only); P-number scheme; status legend; how-items-leave rule; relation to BACKLOG / _validation_log / Pattern F; producer self-check at round close-out; archive cadence (self-rule for POLISH_QUEUE itself when it grows)
- **Cascade**: aggregate-doc updates per D60 close-out discipline (HANDOFF §3 lock list + CURRENT_STATE + NORTH_STAR decision list + GLOSSARY D-range bump + _validation_log entry)

### ~~B.4~~ ✅ LANDED 2026-05-12: Lock-status badge on POLISH_QUEUE.md header

- **Action**: add `**Status**: 🟢 Locked 2026-05-12 (per D113 once authored)` to POLISH_QUEUE.md L5 region

---

## Phase C — NICE-TO-HAVE (organic evolution; track as self-referential P-items)

These should land as they bite, not preemptively. Track each as a new P-item in POLISH_QUEUE.md itself:

- **P-6 candidate**: P-N format consistency — `P-1` vs `P-<N>` placeholder; pick one (probably `P-N` as the canonical with `P-1` as the instance form)
- **P-7 candidate**: "Last reviewed" should distinguish "Created" vs "Reviewed" (file is one day old; the field is ambiguous)
- **P-8 candidate**: P-2 references "all 13 cascade docs" — enumerate or strike the count
- **P-9 candidate**: P-5 closure cites specific line "L598" in GLOSSARY — line-rot risk; cite section name instead
- **P-10 candidate**: Status legend has 🟠 Noticeable but no item uses it; criteria for when to use it?
- **P-11 candidate**: No formal P→B escalation criteria (rule 2 mentions "rare" but no test)
- **P-12 candidate**: No archive cadence for POLISH_QUEUE itself (if it grows like _validation_log)

---

## Phase D — User's actual roadmap (beyond this gap analysis)

User-confirmed in prior turns:

1. **DDL deployment** — deferred per user direction; resume when authorized
2. **Round 0.5 spike week** — deferred per user direction; resume when engineer assignment + Snowflake-test conclusion solidify
3. **Phase 2 R1 kickoff** — gated by R02 spike + Tools 12-16 implementation:
   - B193 migration: `UdmTablesList` ADD COLUMN `LatenessL99Minutes` + `LatenessL99UpdatedAt`
   - B194 migration: CREATE TABLE `General.ops.PiiInventoryAuditLog`
   - B195 migration: CREATE TABLE `General.ops.CapacityBaselineLog`
   - B188: Tool 14 `measure_lateness.py`
   - B189: Tool 15 `import_pii_inventory.py`
   - B190: Tool 16 `measure_capacity_and_partition.py`
   - B185: data-side PII inventory population (gated by B189)
4. **B191** — Snowflake-test-conclusion (~mid-June 2026); gates Phase 5 plan + Tool 16 partition refinement
5. **B186 carryover** — Phase 3 plan authoring at Phase 2 R4 close-out per D112 just-in-time discipline

---

## Phase E — Tooling research (parallel work; tracked separately)

**Phase E status**: ✅ **LANDED 2026-05-12** — both research files persisted; integration synthesis delivered inline in conversation.

This note's parent-turn user direction also asked for Tolaria + Graphify GitHub research. Tracked at:
- ~~`docs/migration/_research/tolaria-2026-05-12.md` (once authored by `udm-researcher` agent)~~ → ✅ landed; verdict = tangential (markdown knowledge-base desktop app; no integration recommended)
- ~~`docs/migration/_research/graphify-2026-05-12.md` (once authored by `udm-researcher` agent)~~ → ✅ landed; verdict = partially relevant (cross-reference visualization potential); user direction post-research = "Graphify can wait"

Integration-into-planning-phase synthesis delivered in conversation 2026-05-12 turn following research returns. User deferred deeper Graphify pilot.

---

## Phase F — Cascade-completion + audit-trail closure (added 2026-05-12 post-D113)

Surfaced by gap-analysis-on-cascade audit 2026-05-12 (post-D113 lock; Pattern F Triggers E + F + skill-operationalization gaps). Phase 1 cascade landed core docs (HANDOFF / CURRENT_STATE / NORTH_STAR / GLOSSARY / 03_DECISIONS / POLISH_QUEUE / _validation_log + 2 skills); Phase F extends to:

- ✅ **F.1**: Register POLISH_QUEUE + P-N + D113 in `CLAUDE.md` project-root § Validation discipline (Trigger E — CLAUDE.md convention registration) — landed inline
- ✅ **F.2**: `udm-checks-and-balances/SKILL.md` CCL Stage 2.5 + Gate 1 cross-ref guidance — landed inline
- ✅ **F.3**: This note's own closure-render discipline applied (Pitfall #9.i 9th-event closure — note tracks its own LANDED state)
- ✅ **F.4**: `00_OVERVIEW.md` document map row
- ✅ **F.5**: `MAINTENANCE.md` grooming entry
- ✅ **F.6**: `MULTI_AGENT_GUIDE.md` CCL section reference
- ✅ **F.7**: `udm-decision-recorder` + `udm-producer-checklist-evolver` low-touch POLISH_QUEUE awareness
- ✅ **F.8**: `_validation_log.md` Phase F cascade-completion entry

(Items below are populated as F.4-F.8 land later this session.)

---

## How items leave this note

- **Phase A / B items**: when fix lands inline in the affected doc, strike the entry through with `~~...~~` + add `**LANDED YYYY-MM-DD**` line; preserve body for audit-trail
- **Phase C items**: when converted to a P-item in POLISH_QUEUE.md, strike + cite the P-number (e.g. `~~P-6 candidate~~ — landed as P-6 in POLISH_QUEUE.md`)
- **Phase D items**: tracked authoritatively in BACKLOG.md; this note's Phase D is mirror-only and gets struck wholesale when BACKLOG items close
- **This file**: archive at Phase 2 R1 kickoff (move to `docs/migration/_archive/_NEXT_STEPS_2026-05-12.md` once all Phase A/B items land + Phase C/D items are tracked authoritatively elsewhere)

---

Owner: pipeline lead. Note authored 2026-05-12 post-gap-analysis turn.
