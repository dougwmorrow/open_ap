# SESSION_RESUME — router (B-562 Component B Phase 2 refactor 2026-05-19)

**This file is now a thin router**. Per-chat resume pointers live in `SESSION_RESUME/active/<chat-name>.md` per B-562 Component B (multi-chat coordination cohort).

## For a fresh Claude session

1. Read `SESSION_RESUME/README.md` to understand the directory + naming convention.
2. Identify which chat's resume pointer matches your scope (see "Active chats" table below).
3. Read that `SESSION_RESUME/active/<chat-name>.md` first.
4. Then proceed to `docs/migration/INDEX.md` → `CURRENT_STATE.md` → `HANDOFF.md` → `CLAUDE.md` per CCL Stage 0+1 discipline.

## Active chats

| Chat name | Scope | State pointer |
|---|---|---|
| **meta-discipline** | udm-* skills + Phase 1 quality checks + producer-discipline forward-prevention + multi-chat coordination cohort | `SESSION_RESUME/active/meta-discipline.md` |
| **scd2** (if/when authored) | SCD2 + CDC + Bronze + replay-from-Parquet pipeline core; D125 3-mode CDC dispatch; RB-16 / RB-18 runbooks | `SESSION_RESUME/active/scd2.md` (not yet created — parallel chat may author at next milestone) |

When a chat session ends cleanly, its `active/<chat-name>.md` file moves to `SESSION_RESUME/_archive/<YYYY-MM-DD>-<chat-name>.md` per lifecycle in `SESSION_RESUME/README.md`.

## Empirical anchor

User-direction 2026-05-19 "Maybe we should have a SESSION_RESUME directory that tracks different chats so that there is no overlap" → accepted → B-562 Component B authored. Phase 1 landed directory + first per-chat pointer at commit `64175d9`. Phase 2 (this router refactor) landed at follow-up commit. Phase 3 (`udm-session-compactor` SKILL.md Step 3 extension + CLAUDE.md CCL Stage 0 routing update) deferred to next commit cohort.

## What this file used to contain

Until B-562 Component B Phase 2 (2026-05-19), this file held verbose per-chat session-resume state. That content has migrated to `SESSION_RESUME/active/meta-discipline.md` for the meta-discipline chat. Future per-chat state lives in `SESSION_RESUME/active/<chat-name>.md` files (one per active chat), not in this root file.

## Owner

Pipeline lead. Router file maintained at each Component B Phase 2+3 follow-up commit; per-chat state pointers maintained by each chat session.
