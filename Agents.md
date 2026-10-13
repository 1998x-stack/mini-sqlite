# Agents.md — mini-sqlite Development Contract

> **Mandatory for future work:** read this file before changing code, tests, documentation, branches, storage formats, durability, planning, concurrency, locking, or maintenance semantics.
>
> `main` is the canonical integrated state. Historical version branches are frozen learning snapshots.

## 1. Repository mission

mini-sqlite is a Python-first educational database engine for understanding SQLite-style database mechanisms through small, inspectable milestones.

Priorities:

```text
architectural clarity
      ↓
correctness + explicit invariants
      ↓
readable reference implementation
      ↓
mechanism-focused tests
      ↓
observable end-to-end behavior
```

## 2. Integrated architecture through v1.1

```text
SQL / Parser / AST
        ↓
Cost-Based Planner ← ANALYZE statistics
        ↓
Compiler / Tiny VM
        ↓
Relational operators / JOIN
        ↓
Table + Secondary-Index B+Trees
        ↓
Database connection
        ↓
LockRegistry ─→ POSIX FileLockSet
        │          MODE / PENDING / READERS / WRITER
        ↓
Pager
        ↓
Bounded Buffer Manager (LRU / CLOCK)
        ↓
Rollback Journal OR WAL
        ↓
Database file

Lifecycle layer:
 integrity_check · reindex · vacuum · explain_analyze
```

## 3. Version spine

```text
v0.1  Page/Pager/B+Tree + SQL/Planner/VM
v0.2  Rollback Journal + Transactions + Crash Recovery
v0.3  Secondary Index
v0.4  Relational Execution + UPDATE
v0.5  INNER JOIN + Indexed Nested Loop
v0.6  WAL + Read Overlay + Checkpoint
v0.7  Bounded Buffer Manager + LRU/CLOCK
v0.8  ANALYZE + Cost-Based Optimizer
v0.9  Process-local Multi-Connection Concurrency
v1.0  Integrity / REINDEX / VACUUM / EXPLAIN ANALYZE
v1.1  Cross-process POSIX File Locking                         ✅ integrated
v1.2  Free-list Page Reuse + Incremental VACUUM               ← next
```

## 4. Branch invariant

```text
validated main
   ↓
create vX.Y
   ↓
implement one dominant mental model
   ↓
tests + docs + example
   ↓
exact version branch-head CI green
   ↓
freeze version branch
   ↓
integrate the same validated engine tree into main
   ↓
restore canonical main Agents.md / version.md
```

Never claim a version is frozen from local tests alone.

## 5. Core invariants

- SQL frontend never accesses page bytes directly.
- Planner performs no physical I/O.
- VM talks to cursors/storage abstractions, not OS files.
- B+Trees mutate pages only through Pager.
- Pager owns durability ordering; Buffer Manager owns residency.
- rollback before-images become durable before unsafe DB-page writeback.
- uncommitted WAL dirty frames never leak into the main database.
- WAL readers observe complete committed prefixes only.
- process-local lock state remains readable in `LockRegistry`.
- cross-process truth comes from kernel locks, never lock-file existence.
- MODE owns live journal-mode agreement and globally-first recovery ownership.
- PENDING prevents new rollback readers from starving an EXCLUSIVE writer.
- process death must release OS locks without cleanup code.
- storage formats are independent of lock-sidecar metadata.
- integrity checking is read-only; REINDEX/VACUUM use normal engine paths.

## 6. Compatibility rule

Any incompatible page, record, catalog, rollback-journal, WAL, index, or future free-list byte-layout change requires an explicit version, exact format documentation, reopen/corruption/crash tests, and a compatibility statement.

v1.1 changes no database, journal, or WAL byte format.

## 7. Validation contract

```bash
python -m pytest -q
python examples/quickstart.py
python examples/transactions.py
python examples/indexes.py
python examples/relational.py
python examples/joins.py
python examples/wal.py
python examples/buffer_pool.py
python examples/optimizer.py
python examples/concurrency.py
python examples/lifecycle.py
python examples/cross_process.py
python -m compileall -q mini_sqlite
```

For cross-process behavior, use multiprocessing `spawn` or separate interpreters; `fork` alone does not prove independent lock registries.

## 8. Platform boundary

The v1.1 cross-process backend is POSIX `flock` for macOS/Linux. A Windows backend must implement the same abstraction rather than leaking platform-specific calls upward.

## 9. Next milestone: v1.2

The next dominant question is page lifecycle:

> When an index/table stops owning a page, must that page remain orphaned until full VACUUM?

v1.2 should introduce persistent free-page metadata, safe page reuse, integrity checks, transaction/WAL-safe free-list mutation, and incremental tail truncation without weakening v1.1 locking or prior durability invariants.
