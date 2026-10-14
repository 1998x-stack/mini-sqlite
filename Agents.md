# Agents.md — mini-sqlite Development Contract

> **Mandatory for future work:** read this file before changing code, tests, documentation, branches, formats, durability, planning, concurrency, maintenance, or ordered-index semantics.
>
> `main` is the canonical integrated state. Historical version branches are frozen learning snapshots.

## 1. Repository mission

mini-sqlite is a Python-first educational database engine for understanding SQLite-style mechanisms.

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
      ↓
performance / SQL breadth later
```

It is not SQLite binary compatible and is not intended for production workloads.

## 2. Integrated architecture through v1.3

```text
SQL / Parser / AST
        ↓
Cost-Based Planner ← ANALYZE statistics
        ↓
Compiler / Tiny VM
        ↓
Relational operators / JOIN
        ↓
Ordered Table + Secondary-Index B+Trees
        ↓
Database connection / process-local + POSIX file locks
        ↓
Pager
        ↓
Bounded Buffer Manager (LRU / CLOCK)
        ↓
Rollback Journal OR WAL
        ↓
Database file

Lifecycle / space management:
 integrity_check · reindex · vacuum · explain_analyze
 free-list · page reuse · incremental_vacuum

Ordered index layer:
 scalar/composite keys · left-prefix probes · range cursors
```

Every subsystem must remain at its narrowest useful boundary. SQL parsing must not encode physical index keys; B+Trees must not know SQL predicates; replacement policy must not bypass durability; maintenance must use normal transaction/storage APIs.

## 3. Version history

```text
v0.1  Page/Pager/B+Tree + SQL/Planner/VM
v0.2  Rollback Journal + Transactions + Crash Recovery
v0.3  Secondary Index
v0.4  Relational Execution + UPDATE
v0.5  INNER JOIN + Indexed Nested Loop
v0.6  WAL + Read Overlay + Checkpoint
v0.7  Bounded Buffer Manager + LRU/CLOCK
v0.8  ANALYZE + Cost-Based Optimizer
v0.9  Process-local Concurrency + Locks/Snapshots
v1.0  Integrity / REINDEX / VACUUM / EXPLAIN ANALYZE
v1.1  Cross-process POSIX File Locking
v1.2  Persistent Free-list + Page Reuse + Incremental VACUUM
v1.3  Range Index Scan + Composite Index                    ✅ integrated
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
- Planner performs no OS I/O.
- VM talks to cursors/storage abstractions, not files.
- B+Trees obtain and mutate pages only through Pager.
- Pager owns durability ordering and free-page lifecycle.
- Buffer Manager owns residency/replacement, not durability.
- pinned frames are never evicted.
- rollback before-images become durable before unsafe DB-page writeback.
- uncommitted WAL dirty frames never leak into the main DB.
- WAL reads use only complete committed prefixes.
- process-local lock state is mirrored to kernel `flock` for cross-process correctness.
- Catalog owns schema/index/statistics metadata; root page ids are mutable and persisted.
- valid free pages are explicit owners, not orphans.
- allocation prefers persistent free-list pages before growing the file.
- incremental vacuum truncates only a consecutive free suffix; it does not move live pages.
- composite physical keys follow declared index-column order and end with rowid.
- ordered index planning follows the SQL left-prefix rule: equality prefix then at most one range column.
- residual predicates must still be evaluated when a probe does not consume the complete WHERE clause.
- ordered SQL comparisons do not match NULL.
- integrity checking is read-only; REINDEX/VACUUM use ordinary engine transactions/storage APIs.

## 6. Compatibility rule

Any incompatible page, record, catalog, rollback-journal, WAL, index-key, free-page, or lock-sidecar semantic change requires an explicit format/version statement and reopen/corruption tests.

Current main-file format is **v3**. v3 keeps the same page-0 binary layout as v2 but gates composite-index catalog semantics. Table/index node bytes, row bytes, rollback-journal bytes, WAL bytes, free-page bytes and lock sidecars are unchanged from their earlier milestones.

## 7. Testing contract

Full regression:

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
python examples/freelist.py
python examples/range_indexes.py
python -m compileall -q mini_sqlite
```

For new mechanisms include invariants, error/boundary cases, reopen/persistence, optimizer diagnostics, concurrency/crash cases where relevant, and one educational example.

## 8. Next version boundary

**v1.4 — Savepoints** is the next dominant mental model:

```text
BEGIN
  work A
  SAVEPOINT s1
    work B
  SAVEPOINT s2
    work C
  ROLLBACK TO s2
  RELEASE s1
COMMIT
```

v1.4 must focus on partial rollback markers inside one transaction, including page allocation/free-list restoration and rollback/WAL correctness. Do not mix Hash Join, covering indexes, ORDER BY elimination, or MVCC into the same milestone.
