# BCP Loading Issues — main_small_tables Pipeline

Analysis comparing the working `stage_backfill.py` BCP setup against the `main_small_tables.py` pipeline to identify probable causes of BCP hangs and load failures.

---

## Critical Issue #1: Packet Size Exceeds SSL Ceiling

**stage_backfill** clamps packet size to 16,384 bytes:
```python
SSL_MAX_PACKET_SIZE = 16384
# "SSL/TLS caps at exactly 16384 bytes per RFC 2246 §6.2.2.
#  Values above this cause BCP failures on encrypted connections."
```

**main_small_tables** uses 32,768 unclamped:
```python
BCP_PACKET_SIZE = int(os.getenv("BCP_PACKET_SIZE", "32768"))
# passed directly to -a flag, no clamping
```

The BCP command includes `-Yo` (TrustServerCertificate), which means encryption is active. With TLS active, the 32KB packet size violates the RFC 2246 §6.2.2 record size limit. This can cause silent BCP hangs during the TLS handshake or mid-transfer — the process stalls with no error output, which matches what you're seeing.

**Fix:** Clamp to 16384 or lower, matching stage_backfill.

---

## Critical Issue #2: No Batch Size on Default (Atomic) Loads

`bcp_load()` defaults to `atomic=True`, which **omits the `-b` flag entirely**:

```python
def _build_bcp_command(..., atomic: bool, ...):
    # ...
    if not atomic:    # <-- only adds -b when atomic=False
        cmd.extend(["-b", str(batch_size)])
```

Without `-b`, the entire CSV is loaded as **one single transaction**. For a table with 500K+ rows this means:

- Transaction log grows unbounded for the duration of the load
- A single lock is held for the entire operation (minutes)
- If BCP is killed or times out, SQL Server must **roll back the entire load** — rollback of a large single-batch import can take longer than the original load
- The transaction log growth itself can trigger `WRITELOG` / `LOGBUFFER` waits, which the hang monitor detects as §4 log pressure

**stage_backfill** always uses `-b 100000`:
```python
batch_size: int = 100000  # -b flag: rows per batch (always included)
```

**Fix:** Always include `-b` with a reasonable batch size (100K for stage heaps, or whatever suits the table type). The `atomic=True` design is problematic for any non-trivial table size.

---

## Critical Issue #3: Field Terminator Format

**main_small_tables** uses an escaped string:
```python
"-t", "\\t",
```

**stage_backfill** uses hex notation:
```python
"-t", "0x09",  # Tab (hex — "most reliable cross-platform")
```

The `\\t` notation relies on the shell/subprocess to interpret the backslash escape correctly. In `subprocess.run()` / `Popen()` with a list (not a string), there's no shell interpretation — the literal string `\t` is passed to BCP. Whether BCP itself interprets `\t` as a tab depends on the BCP version and platform. The hex notation `0x09` is unambiguous and documented by Microsoft as the most reliable approach on Linux.

If BCP misinterprets the terminator, it treats the entire row as a single column, causing data corruption or immediate failure — but sometimes it manifests as a hang while BCP waits for data that matches its expected format.

**Fix:** Use `0x09` hex notation.

---

## Critical Issue #4: Missing `-k` Flag (Keep Nulls)

**stage_backfill** includes `-k`:
```python
if self.bcp_config.keep_nulls:
    cmd.append('-k')  # empty fields → SQL NULL
```

**main_small_tables** omits it entirely. Without `-k`, empty fields in the CSV get the column's **default value** instead of NULL. For columns with no default, this silently inserts empty strings where NULLs were expected.

This isn't a hang cause, but it's a data integrity issue that makes loaded data incorrect.

**Fix:** Add `-k` to the BCP command.

---

## High Issue #5: No Password on Command Line

**stage_backfill** passes password directly:
```python
'-P', config.SSMS_PASSWORD,
```

**main_small_tables** passes password via environment variable only:
```python
bcp_env = {"SQLCMDPASSWORD": config.SQL_SERVER_PASSWORD}
# No -P flag in the command
```

While `SQLCMDPASSWORD` should work, it's a `sqlcmd` environment variable. BCP's support for it is version-dependent. On some Linux `mssql-tools18` versions, BCP may not read `SQLCMDPASSWORD` correctly, causing an authentication hang — BCP waits for a password prompt that never comes (since stdin is `PIPE`), producing exactly the silent hang behavior you're seeing.

**Fix:** Add `-P` with the password directly, matching stage_backfill. If you prefer not to have the password in the process list, test that `SQLCMDPASSWORD` actually works with your BCP version first.

---

## High Issue #6: Recovery Model Switching Under Load

Both `bulk_load_stage_context` and `bulk_load_bronze_context` do:

```python
cursor.execute(f"ALTER DATABASE ... SET RECOVERY BULK_LOGGED")
# ... yield (BCP runs here) ...
# finally:
cursor.execute(f"ALTER DATABASE ... SET RECOVERY FULL")
```

Each `ALTER DATABASE SET RECOVERY` takes a **database-level exclusive lock**. If multiple workers (from `ProcessPoolExecutor`) hit this simultaneously for the same database, they serialize on this lock. Worse, if one worker's `finally` block runs while another worker's BCP is mid-load, the recovery model switch can cause log behavior changes mid-transaction.

`stage_backfill` either skips recovery model switching entirely or handles it once at the pipeline level, not per-table.

**Fix:** Switch recovery model once before all loads start and once after all loads finish, not per-table. Or skip it entirely if the database is already BULK_LOGGED.

---

## High Issue #7: Connection Pool + DDL Context Managers

The `bulk_load_stage_context` and `bulk_load_bronze_context` both call `connections.get_connection(database)` (which creates fresh connections) and then close them in `finally`. But the `cursor_for()` context manager used elsewhere maintains a per-database connection pool:

```python
_connection_pool: dict[str, pyodbc.Connection] = {}
```

The DDL operations (`ALTER DATABASE`, `sp_tableoption`, `ALTER TABLE SET LOCK_ESCALATION`) run on fresh connections that bypass the pool. Meanwhile, the pooled connection may have cached metadata or assumptions about the database state (recovery model, lock escalation setting) that are now stale.

Additionally, `ProcessPoolExecutor` forks workers — each worker gets its own `_connection_pool`. If a worker crashes or is killed, the pool's `close_connection_pool()` never runs, potentially leaving connections open.

**Fix:** Use context-managed connections consistently (like stage_backfill does), not a global pool, for DDL operations.

---

## Medium Issue #8: No `-m` Flag (Max Errors)

**stage_backfill** sets a max error threshold:
```python
'-m', str(self.bcp_config.max_errors),  # 10
```

**main_small_tables** omits `-m`. BCP's default max errors is 10, so this matches implicitly — but being explicit prevents surprises if the default changes in a future `mssql-tools18` version.

---

## Medium Issue #9: Bronze Batch Size vs Atomic Conflict

The code defines `BCP_BRONZE_BATCH_SIZE = 800` specifically to stay below lock escalation. But the default `bcp_load()` call uses `atomic=True`, which **skips `-b` entirely**. So for Bronze loads, either:

- `atomic=True` (default): No batching, entire load is one transaction, lock escalation happens at ~5000 rows regardless of `LOCK_ESCALATION=DISABLE` setting
- `atomic=False`: Uses 800-row batches as intended

If callers aren't explicitly passing `atomic=False` for Bronze loads, the batch size config is dead code and lock escalation is happening.

**Fix:** Verify all Bronze callers pass `atomic=False`, or change the default for Bronze tables.

---

## Summary: BCP Command Comparison

| Flag/Setting | stage_backfill (working) | main_small_tables (hanging) |
|---|---|---|
| `-t` (field terminator) | `0x09` (hex) | `\\t` (escape) |
| `-r` (row terminator) | `0x0A` (hex) | `0x0A` (hex) — OK |
| `-a` (packet size) | **16384** (SSL-clamped) | **32768** (unclamped) |
| `-b` (batch size) | Always 100K | **Omitted when atomic=True** |
| `-k` (keep nulls) | Yes | **Missing** |
| `-m` (max errors) | 10 | Missing (default 10) |
| `-P` (password) | Direct on command line | **Missing** (env var only) |
| `-d` (database) | Explicit `-d` flag | Missing (3-part name) |
| `-u` / `-Yo` (trust cert) | `-u` | `-Yo` — equivalent |
| sp_tableoption | Per-load toggle | Per-load toggle — OK |
| Recovery model | Not switched per table | Switched per table — risky |

---

## Recommended Fix Priority

1. **Clamp packet size to 16384** — most likely hang cause
2. **Always use `-b 100000`** — prevents unbounded transaction log growth and long lock holds
3. **Switch `-t` to `0x09`** — eliminates terminator ambiguity
4. **Add `-k` flag** — data integrity
5. **Add `-P` flag** — authentication reliability
6. **Move recovery model switching out of per-table contexts** — prevents DDL lock contention between workers
7. **Verify Bronze callers use `atomic=False`** — otherwise batch size config is unused