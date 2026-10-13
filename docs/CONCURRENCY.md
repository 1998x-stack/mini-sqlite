# v0.9 Concurrency / Locking

v0.9 introduces a second dimension to mini-sqlite: more than one live `Database` connection can point at the same file.

> **Which connection may read or write now, what snapshot does it see, and how do conflicts become deterministic instead of corrupting storage?**

## Scope

The v0.9 registry is **process-local**, keyed by canonical database path. Cross-process OS locks are intentionally deferred.

## Rollback mode

```text
NONE -> SHARED -> RESERVED -> EXCLUSIVE
```

Multiple SHARED holders coexist. Only one RESERVED writer intent is permitted. EXCLUSIVE requires all other SHARED readers to finish. EXCLUSIVE is necessary because rollback-mode dirty pages may reach the main DB before COMMIT and must remain invisible to other connections.

### Lazy rollback journal

`BEGIN` no longer eagerly creates `<db>-journal`. A read transaction holds SHARED only. The journal is created on the first physical write or new page, allowing multiple read-only transactions to coexist safely.

## WAL mode

Readers coexist with a single `WAL_WRITE` holder. An explicit reader keeps the committed WAL prefix observed at `BEGIN`; autocommit reads refresh before each statement.

If another connection commits after a reader snapshot and that reader then attempts a write, v0.9 raises `BusySnapshotError` so the transaction can restart from fresh state.

## Checkpoint

Checkpoint changes the main database base beneath WAL overlays, so it waits for explicit reader snapshots and conflicts with the WAL writer.

## Busy timeout

`Database(..., busy_timeout_ms=N)` waits on a condition variable for up to N milliseconds. Zero fails immediately. COMMIT, ROLLBACK and CLOSE wake waiting connections; there is no spin loop.

## Connection cache coherence

Each connection owns its own Pager and buffer pool. Under the appropriate connection lock, a new autocommit statement or transaction snapshot clears clean stale frames, rescans the committed WAL prefix when applicable, reloads page count, and rebuilds Catalog/Planner runtime state. Active transactions never refresh.

## Live WAL tails

A reader refresh may occur while a writer is active. An incomplete suffix is ignored, never truncated. Only first-connection crash recovery may truncate a genuinely abandoned WAL tail.

## Crash simulation

Historical tests simulate process death by closing Pager directly. The registry binds a liveness callback; closed Pager holders are pruned so later hot-journal recovery behaves like a real process restart.

## Mixed journal modes

Simultaneously live connections must agree on rollback vs WAL mode. `JournalModeConflictError` is raised otherwise. Once all old-mode connections close, normal mode switching is allowed.

## Observability

`.locks` / `Database.lock_status()` show current connection lock, number of connections/readers, reserved/exclusive holder, WAL writer, and timeout.

## Non-goals

No cross-process file locks, row/predicate locks, deadlock graph detector, MVCC, savepoints, distributed transactions, or multi-writer WAL.

The lesson is: **durability protects transactions from crashes; concurrency control protects transactions from each other.**
