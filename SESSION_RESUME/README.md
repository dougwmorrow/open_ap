# SESSION_RESUME/ — multi-chat coordination substrate (B-562 Component B)

**Purpose**: per-chat resume pointers to eliminate the `SESSION_RESUME.md` write-overlap class surfaced by the 2026-05-19 multi-chat coordination cohort.

**Empirical anchor**: 2026-05-19 user-observation "we used the compactor skill to update SESSION_RESUME.md at the same time that this chat updated the file. Did this parallel update cause issues?" → diagnosis was actually B-N integer collision (not file-write collision) BUT user-direction "Maybe we should have a SESSION_RESUME directory that tracks different chats so that there is no overlap" was accepted as architectural improvement regardless. Companion: `tools/claim_next_bn.py` (B-562 Component A; closed at commit `dd9fbdb`) closes the B-N integer collision class.

## Directory layout

```
SESSION_RESUME/
├── README.md                     (this file — router documentation)
├── active/
│   ├── meta-discipline.md        (chat focused on udm-* skills + Phase 1 quality checks)
│   ├── scd2.md                   (parallel chat focused on D125 CDC dispatch + RB-16) — NOT YET CREATED; parallel chat may author
│   └── <chat-name>.md            (one per active chat)
└── _archive/
    ├── <YYYY-MM-DD>-<chat-name>.md  (completed chats' final resume pointer)
    └── ...
```

## Lifecycle

### When a new chat session starts

Author `SESSION_RESUME/active/<chat-name>.md` with the canonical 4-section template:

1. **State as of session end / mid-session** — branch / latest commit / push status / pytest baseline / cumulative delta
2. **NEXT SESSION RESUME PROCEDURE** — read-order for fresh agent + build resumption sequence
3. **This session's commit chain** — chronological commit list with verdicts
4. **Open runway** — recommended next steps with priority labels + scope hints

Chat names should be **scope-stable** (the focus area of the chat, not a date or commit hash). Examples:
- `meta-discipline.md` — udm-* skills + Phase 1 quality checks + producer-discipline work
- `scd2.md` — SCD2 + CDC + Bronze + replay-from-Parquet pipeline core
- `phase-2-build.md` — Phase 2 deep-dive plans + new module authoring
- `runbooks-rb-13.md` — RB-13 SCD2 corruption replay runbook authoring
- `phase-0-prep.md` — Phase 0 .env / TPM2 / Snowflake credentials prep

### During a chat session

When `udm-session-compactor` skill fires (manual OR auto-trigger per Path E hybrid checkpoint), author/refresh `SESSION_RESUME/active/<chat-name>.md` for THIS chat's state. Do NOT touch other chats' active files.

The canonical `_session_snapshots/<YYYY-MM-DD>-<commit-hash-prefix-7>.md` immutable-snapshot directory pattern (B-492) remains the source-of-truth for **deeper insights + architectural decisions**. The `active/<chat-name>.md` file is the **lightweight pointer** mirroring `SESSION_RESUME.md`'s role at root.

### When a chat session ends (cleanly)

Move `SESSION_RESUME/active/<chat-name>.md` → `SESSION_RESUME/_archive/<YYYY-MM-DD>-<chat-name>.md` with the closure date prefixed. This preserves the resume pointer for forensic / audit purposes without cluttering the active directory.

### When a chat session is abandoned

Move to `_archive/` with an `ABANDONED-<reason>` suffix in the filename. Do NOT delete.

## Relationship to root `SESSION_RESUME.md`

**Phase 1 (this commit)**: root `SESSION_RESUME.md` remains as-is for backward-compat. Parallel chats may continue to write to it as they finalize their current milestone; future chat sessions should write to `SESSION_RESUME/active/<chat-name>.md` instead.

**Phase 2 (future commit; deferred)**: root `SESSION_RESUME.md` will be refactored to a thin router file pointing to `SESSION_RESUME/active/` directory listing. Trigger: parallel chat completes their milestone + archives their current SESSION_RESUME.md content to `_archive/`. Tracked via remaining B-562 Component B follow-up work.

## Cross-references

- **CLAUDE.md** CCL Stage 0 routing (future update once Phase 2 lands)
- **`.claude/skills/udm-session-compactor/SKILL.md`** — skill that authors snapshots + state pointers
- **`docs/migration/_session_snapshots/`** — immutable snapshot directory (B-492 substrate; deeper-insights canon)
- **`docs/migration/BACKLOG.md`** B-562 (multi-chat coordination cohort)
- **`tools/claim_next_bn.py`** (B-562 Component A) — companion CLI eliminating B-N integer collision class

## Composition with `udm-session-compactor` skill

The skill's Step 2 ("Author snapshot at `docs/migration/_session_snapshots/<YYYY-MM-DD>-<commit-prefix>.md`") remains the **immutable-substrate** authoring action.

A future SKILL.md extension (Phase 2 of B-562 Component B) will add a Step 3: "Refresh state pointer at `SESSION_RESUME/active/<chat-name>.md`" — mirroring the current root SESSION_RESUME.md refresh discipline at per-chat scope.

For Phase 1 (this commit), the directory + README documentation establish the convention; SKILL.md update lands in a follow-up commit alongside the root SESSION_RESUME.md router refactor.

## Owner

Pipeline lead. Directory structure landed 2026-05-19 per B-562 Component B Phase 1; SKILL.md + root-file router refactor deferred to Phase 2 follow-up.
