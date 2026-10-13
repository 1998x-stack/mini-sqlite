# v1.1 Cross-process File Locking

v1.1 takes the connection state machine introduced in v0.9 and mirrors it into the operating system. Independent Python processes now coordinate through POSIX `flock` sidecars while the existing in-process `LockRegistry` remains the readable state machine and observability layer.

> Scope: macOS/Linux POSIX `flock`. The on-disk database, rollback-journal, and WAL formats are unchanged.

## 1. Why v0.9 was not enough

v0.9 could protect two `Database(...)` objects in one Python process:

```text
Process A
  connection 1 ─┐
                ├─ LockRegistry
  connection 2 ─┘
```

but another interpreter had a different registry:

```text
Process A             Process B
LockRegistry A        LockRegistry B
     │                     │
     └──── same.db ────────┘
```

Without an OS-visible lock, both processes could believe they were the only writer.

## 2. Sidecar lock files

For `demo.db`, v1.1 creates four tiny persistent sidecars:

```text
demo.db-lock-mode
demo.db-lock-pending
demo.db-lock-readers
demo.db-lock-writer
```

Their **existence means nothing**. They may remain forever. Only the kernel `flock` state determines whether a process is alive.

That distinction matters after `kill -9` or `os._exit()`: file descriptors close automatically, so the kernel releases locks without requiring cleanup code.

## 3. MODE lock: mode agreement + recovery ownership

Every live connection holds MODE-SH. The globally first opener obtains MODE-EX, writes either `rollback` or `wal`, performs recovery/bootstrap, then downgrades to MODE-SH.

```text
no live process
   ↓
MODE-EX
   ↓
write journal mode
   ↓
hot-journal / WAL recovery
   ↓
open runtime
   ↓
MODE-SH
```

If MODE-EX cannot be obtained, another live process exists. The new opener joins MODE-SH and must agree with the stored mode. This makes live rollback + WAL mixing a cross-process error while still allowing mode switching after every old process exits.

## 4. Rollback mode

Rollback readers use:

```text
PENDING-SH   (brief entrance turnstile)
    ↓
READERS-SH  (held for snapshot)
    ↓
release PENDING-SH
```

A writer first declares intent:

```text
WRITER-EX  == RESERVED
```

Then upgrades:

```text
PENDING-EX
    ↓
no new readers may enter
    ↓
release writer's own READERS-SH if upgrading
    ↓
wait for READERS-EX
    ↓
EXCLUSIVE writer
```

The PENDING lock is important: without it, a steady stream of new readers could starve a writer that is waiting for old readers to drain.

## 5. WAL mode

WAL keeps reader and writer locks independent:

```text
reader process: READERS-SH
writer process: WRITER-EX
```

Therefore a reader snapshot can coexist with the single WAL writer. The reader continues using the committed WAL prefix captured at `BEGIN`, exactly as in v0.9, but now the relationship works across independent interpreters.

## 6. Checkpoint

Checkpoint needs both domains:

```text
WRITER-EX
   ↓
PENDING-EX
   ↓
READERS-EX
   ↓
checkpoint WAL → main DB
```

This blocks a new WAL writer and waits for existing explicit reader snapshots before changing the main database file.

## 7. Opening a rollback Pager safely

A subtle problem appears before SQL locks exist: a new process must not open/read the rollback main DB while another process has uncommitted pages in it.

During construction v1.1 temporarily acquires READERS-SH before opening/recovering the Pager. The guard is released after the runtime is installed. An EX rollback writer therefore blocks a new process at the constructor boundary rather than letting it inspect uncommitted main-file bytes.

## 8. Crash behavior

No PID file is used for correctness.

```text
writer holds flock
      ↓
os._exit / kill -9
      ↓
kernel closes descriptors
      ↓
locks vanish automatically
      ↓
next globally-first opener gets MODE-EX
      ↓
hot journal / WAL recovery
```

The small sidecar files can remain because they are not ownership records.

## 9. busy_timeout

The same `busy_timeout_ms` applies to cross-process acquisition. POSIX `flock` has no portable timed call, so the educational backend uses non-blocking acquisition plus a short monotonic-clock sleep until the deadline.

```python
Database("demo.db", busy_timeout_ms=500)
```

`0` still means fail immediately.

## 10. VACUUM and maintenance

v1.0's process-local `connections == 1` check is no longer sufficient by itself. v1.1 relies on the same OS EX locks used by writers/checkpoint, so another process holding a reader snapshot makes VACUUM return `BusyError` before the atomic file replacement.

Temporary VACUUM databases create their own lock sidecars and remove them during cleanup.

## 11. Observability

`.locks` now includes the backend and this connection's OS state, for example:

```text
connection=2 pid=12345 mode=rollback backend=posix-flock
mine=exclusive connections=1 readers=0
os_readers=exclusive os_writer=exclusive
```

The numeric connection count remains process-local. v1.1 intentionally does not maintain a shared-memory global connection counter; kernel locks are the global truth.

## 12. Tests

`tests/test_cross_process_locking.py` uses the multiprocessing `spawn` start method so children have fresh interpreters and fresh `LockRegistry` objects. It covers:

- rollback reader blocks writer across processes;
- cross-process busy timeout;
- WAL snapshot reader + writer coexistence;
- one WAL writer globally;
- checkpoint waits for another process reader;
- `os._exit()` automatically releases OS locks and hot-journal recovery succeeds;
- journal-mode mismatch across processes;
- rollback writer blocks a new process from opening Pager;
- VACUUM requires global exclusivity.

## 13. Non-goals

No Windows lock backend, shared-memory lock table, advisory-lock support on every network filesystem, deadlock graph, multi-writer WAL, row locks, or MVCC.

The v1.1 lesson is:

> **Process-local state explains the lock protocol; kernel locks make that protocol real across process boundaries.**
