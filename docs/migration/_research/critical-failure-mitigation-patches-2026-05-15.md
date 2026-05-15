# Critical-failure mitigation patches — F9.1 + F1.1 + F5.1

**Date**: 2026-05-15
**Scope**: ready-to-apply inline edits for the 3 CRITICAL failure modes from `_research/gap-audit-synthesis-2026-05-15.md` § "🔴 CRITICAL FAILURE MODES (3 — must mitigate before execution)" — patches target `docs/migration/MARKDOWN_REFACTOR_PLAN.md`.
**Anchor**: per `MARKDOWN_REFACTOR_PLAN.md` §17.7 plan-calculus cascade — these patches operationalize the §17.7 directives (F9.1 → §5.1; F5.1 → §15.2 + §16.5; F1.1 → §7.1).
**How to use**: each section below contains a markdown code-fenced block (`UPDATED-MARKDOWN`) that is mechanically copy-pasteable into the target plan section. Insert at the cited section + line per the "Apply to" header.

---

## Patch 1 — F9.1: Phase 1.0 + Phase 1.B atomic-cohort gate

### Failure mode (restate)
Operator executes Phase 1.0 (the `_validation_log.md` archive cascade, which delivers a fast 73% trim + 62% CCL token recovery) but never lands Phase 1.B (the master `INDEX.md`). The repo ends up WORSE than before because audit-trail navigation now requires cross-file awareness (which entry lives in the live file vs which archive file) without a routing manifest to guide it. Canonical "ship MVP, never ship V1" anti-pattern.

### Mitigation (restate)
Bundle Phase 1.0 + Phase 1.B as an **ATOMIC COHORT**: reject the commit / pull-request if either lands without the other. Use a deterministic verification mechanism (round-close-out cascade check + Pattern F Layer 1 audit assertion) so the constraint cannot decay to "operator discipline."

### Apply to
`docs/migration/MARKDOWN_REFACTOR_PLAN.md` §5.1 "Phased execution" — INSERT a new "Phase 1 atomic-cohort gate" sub-section IMMEDIATELY BEFORE the existing `**Phase 1 (low-risk; reversible; ~1-2 cycles)**` bullet block (currently at L303).

### Exact text to insert

```markdown
**Phase 1 atomic-cohort gate (BINDING per F9.1 mitigation; 🔴 CRITICAL)** — Phase 1.0 (`_validation_log.md` archive cascade) and Phase 1.B (master `INDEX.md` authoring) are an **ATOMIC COHORT**. Both MUST land in the same round / same pull-request. Either-without-the-other is rejected.

- **Reject condition #1**: PR contains Phase 1.0 archive-cascade changes (live `_validation_log.md` truncated OR `_validation_log_archive_*.md` created) but does NOT contain `docs/migration/INDEX.md` — REJECT with reason "F9.1 atomic-cohort violation".
- **Reject condition #2**: PR contains `docs/migration/INDEX.md` but Phase 1.0 hasn't run (live `_validation_log.md` still >5,000 lines OR no `_validation_log_archive_*.md` present) — REJECT with same reason.
- **Verification mechanism (two-layer per D89-D91 Pattern F)**: (1) `tools/verify_cascade.py` Trigger N extension (NEW per this gate) asserts both atomic-cohort artifacts present-or-both-absent in any commit touching `_validation_log.md` OR `INDEX.md`; (2) `udm-round-closeout` skill CCL Stage 2.5 asserts the same invariant at round-boundary.
- **Rationale**: per F9.1 (gap-audit-adversarial §9) — operator gets the fast win on Phase 1.0 then loses momentum on Phase 1.B; repo ends WORSE than pre-refactor because audit-trail navigation now needs cross-file awareness without the routing manifest. The atomic-cohort gate forecloses the "ship MVP, never ship V1" partial-completion failure mode.
```

### Rationale for why this closes the failure mode
The failure mode is purely sequencing-based: trim THEN abandon. The atomic-cohort gate makes the sequencing impossible at commit-time — Phase 1.0 cannot land without Phase 1.B and vice-versa. Layer 1 (deterministic script in `verify_cascade.py`) catches it at PR time; Layer 2 (round-close-out human-triggered cascade check) catches it if the script somehow misses (e.g., bypassed via `--no-verify`). The two-layer pattern matches the canonical D89-D91 Pattern F discipline that already governs the project's cascade audits.

### Acceptance criterion
A test case: synthesize a commit that ONLY truncates `_validation_log.md` (no `INDEX.md` touched). Run `tools/verify_cascade.py`. Assert: exit-code ≠ 0 AND stderr contains "F9.1 atomic-cohort violation". Symmetric test: a commit that ONLY adds `INDEX.md` with `_validation_log.md` still at 7,519 lines — same expected outcome.

---

## Patch 2 — F1.1: two-phase-commit semantics for archive script

### Failure mode (restate)
Archive script runs partial write: writes entries to `_archive/_validation_log_archive_2026-04.md` but crashes (power loss / Ctrl-C / fsync failure / OS scheduler kill) BEFORE truncating live `_validation_log.md`. State: live file still has all entries; archive file has duplicate entries; the next archive run sees both files have the entries and may double-archive OR truncate the wrong file. Append-only invariant violated; D55 audit trail has a hole.

### Mitigation (restate)
Two-phase-commit semantics for the archive script: (1) write archive file to `.tmp` suffix → verify hash matches expected source range → fsync; (2) ONLY THEN atomically replace live file with truncated version via `os.replace()` (POSIX `mv -T` semantics on Linux; Win32 `MoveFileEx` with `MOVEFILE_REPLACE_EXISTING` on Windows); (3) ONLY THEN rename `.tmp` archive → final archive name. Failure-mode handling: pre-commit detection of stale `.tmp` files = recovery required.

### Apply to
`docs/migration/MARKDOWN_REFACTOR_PLAN.md` §7.1 "Phase 1 work breakdown" task 1.2 "Execute archive cascade for `_validation_log.md`" (currently at L375) — REPLACE the single-row table entry with the row PLUS an indented procedural-requirement block that follows.

### Exact text to insert

```markdown
| 1.2 Execute archive cascade for `_validation_log.md` (TWO-PHASE-COMMIT per F1.1 mitigation; 🔴 CRITICAL) | Parent agent | ~1 hour | `_validation_log_archive_2026-04.md` authored via two-phase-commit; live file truncated; 1-line back-reference added |

**F1.1 mitigation — two-phase-commit procedure (BINDING for task 1.2)**:

1. **Phase A — write archive to `.tmp`**: parent agent writes archive content to `_archive/_validation_log_archive_2026-04.md.tmp` (note `.tmp` suffix). Compute SHA-256 of the written content; record expected line count (= number of source entries in the archive cutoff range).
2. **Phase A verify**: re-read the `.tmp` file; assert SHA-256 matches; assert line count matches; assert first line + last line match the expected cutoff boundary (first archived entry date ≤ cutoff, next entry in live file date > cutoff).
3. **Phase B — atomically replace live file**: write the truncated live `_validation_log.md` content to `_validation_log.md.tmp.new`; verify line count = (original live line count) − (archived line count) + 1 (the back-reference line); use `os.replace('_validation_log.md.tmp.new', '_validation_log.md')` (atomic on both POSIX + Win32).
4. **Phase C — finalize archive**: `os.replace('_archive/_validation_log_archive_2026-04.md.tmp', '_archive/_validation_log_archive_2026-04.md')`. Order Phase B BEFORE Phase C: if B succeeds + C crashes, the recovery path is "rename the existing `.tmp` to final"; if C succeeds + B crashes, recovery is impossible (live file has entries that already exist in finalized archive — duplicates).
5. **Failure-mode detection (pre-commit + script-startup)**: any `_archive/*.tmp` file at script start = previous run crashed during Phase A/C; abort + require operator manual recovery. Any `_validation_log.md.tmp.new` at script start = previous run crashed during Phase B; same. Pattern F Layer 1 extension catches stale `.tmp` files in commits.
6. **Acceptance verification**: post-run assertion: (a) SHA-256 of archive + truncated live + back-reference line concatenated together = SHA-256 of original pre-archive live file; (b) no `.tmp` files remain; (c) `wc -l` on truncated live ≤ 2,000.
```

### Rationale for why this closes the failure mode
The append-only invariant violation requires BOTH (a) archive write happens AND (b) live truncate happens — partial application of either breaks D55. Two-phase-commit makes the operation atomic at filesystem-level via `os.replace()` (POSIX `rename(2)` is atomic per POSIX.1-2008; Win32 `MoveFileEx` with `MOVEFILE_REPLACE_EXISTING` is atomic on NTFS). Hash verification catches silent data corruption between write + verify. Stale `.tmp` detection at script-startup provides the crash-recovery story F1.1 originally lacked.

### Acceptance criterion
A test case in `tests/tier0/test_archive_cascade.py`: simulate crash between Phase A and Phase B (kill process via SIGKILL after Phase A verify). Re-run script; assert (a) live `_validation_log.md` is UNCHANGED from pre-Phase-A state; (b) `.tmp` file present + script aborted with explicit "recovery required" message; (c) no entries duplicated; (d) no entries lost. Repeat for crash between Phase B and Phase C.

---

## Patch 3 — F5.1: pass-through-verbatim Do-NOT + Pitfall headers in udm-context-loader briefs

### Failure mode (restate)
`udm-context-loader` subagent reads the full CCL (~12K-16K lines) in isolated context, distills into a brief (~500-1K lines), and returns it to the parent agent who passes it to downstream agents in Pattern E / Pattern F multi-agent cycles. Anything the distillation drops is INVISIBLE to downstream agents — they cannot ask "did the brief omit X?" because they don't have the full text. A missed Pitfall #9.x sub-class header OR a missed Do-NOT rule (e.g., "Do NOT change `UdmActiveFlag` semantic") can land destruction-class production changes.

### Mitigation (restate)
`udm-context-loader` brief schema MUST include a mandatory `verbatim_excerpts` field carrying the following content categories PASSED THROUGH VERBATIM (not summarized, not paraphrased):
- Every Do-NOT rule (any line starting with `Do NOT` OR `❌` in `CLAUDE.md` + canonical spec docs)
- Every Pitfall #9.x sub-class header (`Pitfall #9.X — <name>`)
- Every binding D-N status line (`**D-N**: ... 🟢 Locked YYYY-MM-DD` heading rows)
- Every R-N risk header (the row, not the body)

### Apply to (TWO sections)
**Section 3a**: `docs/migration/MARKDOWN_REFACTOR_PLAN.md` §15.2 (Pattern d — 4-component cross-ref maintenance design; currently at L773) — APPEND a new bullet to the Pattern (d) bullet list immediately after the 4th sub-bullet ("`udm-cross-ref-checker` SKILL").

**Section 3b**: `docs/migration/MARKDOWN_REFACTOR_PLAN.md` §16.5 (Multi-agent team structure; "Anti-patterns to avoid" list at L967-970) — APPEND a new bullet to the existing 3-item anti-pattern list.

**Cross-reference note**: per §17.7, F5.1 mitigation lands at §15.2 + §16.5. The structurally-cleanest home for the `udm-context-loader` schema spec itself is §4.5 Option T5 (where the subagent is specified) — recommend a follow-up B-N to also expand §4.5 with the `verbatim_excerpts` schema details. This patch operationalizes §17.7's two named sections; §4.5 expansion is a deferred polish item (P-N candidate).

### Exact text to insert

**Section 3a — append to §15.2 Pattern (d) bullet list (after L778)**:

```markdown
  5. **`udm-context-loader` brief schema `verbatim_excerpts` field** (NEW per F5.1 mitigation; 🔴 CRITICAL): every brief produced by `udm-context-loader` MUST carry a `verbatim_excerpts` field passing through (NOT summarizing) the following content categories: (a) every Do-NOT rule — any line starting with `Do NOT` or `❌` in `CLAUDE.md` + spec docs touched by the brief; (b) every Pitfall #9.X sub-class header — exact header text; (c) every binding `**D-N**: ... 🟢 Locked YYYY-MM-DD` status line; (d) every `R-N` risk header row (header only, not body). Distillation is permitted for everything else; these 4 categories are non-distillable. Brief consumers that touch production code (CDC/SCD2 engine, schema migrations, SP definitions, BCP CSV writers) MUST direct-Read the canonical source for any verbatim_excerpt before proposing a change — the brief carries the excerpt as a tripwire, not as a substitute for the full passage.
```

**Section 3b — append to §16.5 "Anti-patterns to avoid" list (after L970)**:

```markdown
- ❌ Summarizing Do-NOT rules / Pitfall #9.X headers / binding D-N status lines / R-N risk headers in subagent briefs (per F5.1 mitigation; 🔴 CRITICAL) — `udm-context-loader` brief schema's `verbatim_excerpts` field is mandatory for these 4 content categories. Distilling them risks destruction-class production changes when downstream agents act on incomplete context. Distillation is permitted for everything else; these 4 categories are pass-through-verbatim only.
```

### Rationale for why this closes the failure mode
The failure mode requires (a) the brief to drop a load-bearing constraint AND (b) downstream agents to act on the dropped constraint. Pass-through-verbatim eliminates (a) for the 4 highest-risk categories (Do-NOT / Pitfall / binding D-N / R-N) — these are the categories where summarization is most likely to drop a tripwire and where a dropped tripwire has highest blast radius. The "tripwire not substitute" framing in the consumer requirement ensures downstream agents direct-Read the canonical source when a verbatim_excerpt fires — the brief becomes a routing mechanism for the 4 critical categories rather than a substitute. The §16.5 anti-pattern entry reinforces the discipline at the multi-agent-pattern level so all future subagent designs inherit it.

### Acceptance criterion
A test case: hand-construct an `udm-context-loader` brief that summarizes (rather than passes through) the `Do NOT change UdmActiveFlag semantic` rule from `CLAUDE.md` SCD2-R4 (e.g., brief says "preserve UdmActiveFlag semantics" instead of carrying the literal Do-NOT line). Assert: a Pattern E reviewer agent inspecting the brief flags it as 🔴 schema violation citing "F5.1 mitigation — verbatim_excerpts required for Do-NOT rules". Symmetric tests for Pitfall #9.X header summarization + D-N status-line summarization.

---

## Summary table

| Patch | Failure mode | Target section | Line count | Atomic gate? |
|---|---|---|---|---|
| 1 | F9.1 — Phase 1.0/1.B partial completion | §5.1 (before L303) | 13 lines | Yes (Layer 1 + Layer 2) |
| 2 | F1.1 — archive partial-write crash | §7.1 task 1.2 (L375) | 24 lines (table row + 6-step procedure block) | Yes (filesystem-atomic via `os.replace`) |
| 3a | F5.1 — brief omits Do-NOT (Pattern D entry) | §15.2 (after L778) | 7 lines | N/A (schema requirement) |
| 3b | F5.1 — brief omits Do-NOT (anti-pattern entry) | §16.5 (after L970) | 4 lines | N/A (anti-pattern) |

**Total**: ~48 lines of patch content across 4 insertion points (3 patches, with patch 3 split across 2 sections per §17.7).

**Cross-reference handling**: all 4 patches preserve the plan's existing line-anchor regime per §13.3 Navigation Paradox constraint — insertions are additive; no existing line-anchors moved by the patches themselves. Subsequent line-numbers shift naturally as inserts land, which is the normal accepted drift handled by Pattern F regex tolerance.

**Outstanding B-N candidates surfaced by this patch session**:
- **B-N candidate (deferred)**: §4.5 Option T5 expansion with full `verbatim_excerpts` brief schema spec (this patch lands the discipline at §15.2 + §16.5 per §17.7; the canonical schema spec home is §4.5 — open as polish item).
- **B-N candidate (deferred)**: Pattern F Trigger N extension to `tools/verify_cascade.py` for F9.1 atomic-cohort detection (referenced in Patch 1 but the script edit itself is Phase 2 work per §7.2 task 2.4 — bundle into that task).
