# Agents.md — mini-sqlite v1.1 Development Contract

> Frozen learning snapshot. Read this file before changing v1.1 locking, recovery, maintenance, tests, or documentation.

## 1. Version mission

v1.1 adds one dominant mental model:

> **A database lock is only cross-process when the operating system can see it.**

The existing connection state machine remains; POSIX `flock` sidecars mirror it across independent Python interpreters.

## 2. Mandatory reading order

1. `Agents.md`
2. `version.md`
3. `docs/CROSS_PROCESS_LOCKING.md`
4. `docs/CONCURRENCY.md`
5. `mini_sqlite/concurrency/file_lock.py`
6. `mini_sqlite/concurrency/lock.py`
7. `tests/test_cross_process_locking.py`
8. `examples/cross_process.py`
9. `docs/TRANSACTIONS.md`
10. `docs/WAL.md`

## 3. Branch boundary

This branch is the frozen **v1.1 cross-process-locking milestone**.

Do not backport v1.2 free-list page reuse, v1.3 range/composite indexes, savepoints, hash/merge join, MVCC, or a Windows locking backend.

## 4. Layering invariant

```text
Database connection
      ↓
LockRegistry                 readable process-local state machine
      ↓
FileLockSet                  POSIX flock mirror
      ↓
MODE / PENDING / READERS / WRITER sidecars
      ↓
Pager / rollback / WAL       unchanged storage protocols
```

B+Trees, indexes, Planner, VM, Buffer Manager, rollback journal, and WAL must not parse or manipulate lock files.

## 5. Cross-process invariants

- lock-file existence is never a liveness signal;
- every live connection holds MODE-SH after construction;
- globally first opener owns MODE-EX through recovery/bootstrap;
- live processes must agree on rollback vs WAL mode;
- rollback readers hold READERS-SH;
- one rollback RESERVED writer holds WRITER-EX;
- rollback EXCLUSIVE owns WRITER-EX + PENDING-EX + READERS-EX;
- WAL readers and the one WAL writer may coexist;
- checkpoint owns WRITER-EX + PENDING-EX + READERS-EX;
- PENDING blocks new readers while a writer/checkpoint drains old readers;
- `busy_timeout_ms=0` fails immediately; positive values use a monotonic deadline;
- process death releases kernel locks automatically;
- failed partial lock acquisition must release/downgrade every lock it obtained.

## 6. Recovery invariant

Only the globally first opener may perform hot-journal/WAL recovery. MODE-EX is held until Pager recovery/bootstrap and runtime installation finish.

In rollback mode a constructor also holds a temporary READERS-SH guard so it cannot inspect main-file bytes while another process owns EXCLUSIVE.

## 7. Durability invariant

v1.1 changes **no database, rollback-journal, or WAL bytes**. Lock sidecars are advisory coordination metadata, not part of the database format and not required for crash recovery after all processes exit.

## 8. Platform boundary

v1.1 supports POSIX `flock` on macOS/Linux. A future Windows backend must preserve the same `FileLockSet` semantics rather than leaking platform calls into `Database` or Pager.

## 9. Tests required for changes

Run:

```bash
python -m pytest -q
python examples/cross_process.py
python -m compileall -q mini_sqlite
```

Any locking change must preserve all historical tests plus cross-process spawn tests. Crash tests must include abrupt process exit, not only graceful `close()`.

## 10. Definition of done

A v1.1 fix is complete only when:

1. process-local and cross-process lock state agree;
2. rollback and WAL conflict matrices remain correct;
3. busy timeout and failure cleanup are deterministic;
4. crash recovery works after abrupt process death;
5. v1.0 maintenance remains safe;
6. exact branch-head CI is green on supported Python versions;
7. documentation matches actual lock ordering.
