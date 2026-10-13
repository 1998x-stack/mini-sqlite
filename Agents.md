# Agents.md — mini-sqlite Development Contract

> **Mandatory for future work:** read this file before changing code, tests, documentation, branches, storage formats, durability, planning, concurrency, or maintenance semantics.
>
> `main` is the canonical integrated state. Historical version branches are frozen learning snapshots.

## 1. Repository mission

mini-sqlite is a Python-first educational database engine for understanding the mechanisms behind SQLite-style systems.

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

It is not intended to provide SQLite binary compatibility or production database guarantees.

## 2. Integrated v1.0 architecture

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
Database connection / Lock Registry
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

Every subsystem must remain at its narrowest useful boundary. Planner choices must not change storage correctness; cache replacement must not bypass durability; maintenance must use normal storage/transaction APIs rather than editing page bytes ad hoc.

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
v0.9  Multi-Connection Concurrency + Locks/Snapshots
v1.0  Integrity / REINDEX / VACUUM / EXPLAIN ANALYZE        ✅ integrated core
```

v1.0 is the educationally-complete core. Future releases are optional extension tracks rather than missing prerequisites.

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
- Pager owns durability ordering.
- Buffer Manager owns residency/replacement, not durability.
- pinned frames are never evicted.
- rollback before-images must become durable before unsafe DB-page writeback.
- uncommitted WAL dirty frames never leak into the main DB.
- WAL reads use only complete committed prefixes.
- connection locking lives above storage structures.
- schema/index/statistics metadata is persisted through Catalog.
- root page ids are mutable and owners persist root changes.
- integrity checking is read-only.
- REINDEX repairs derived index state through ordinary transactions.
- VACUUM rebuilds through normal engine APIs and requires exclusive process-local connection ownership.

## 6. Compatibility rule

Any future incompatible page, record, catalog, rollback-journal, WAL, or index byte-layout change requires an explicit new version, format documentation, reopen/corruption tests, and a compatibility or migration statement.

v1.0 itself does not change the binary formats established by earlier milestones.

## 7. Testing contract

Full core regression:

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
python -m compileall -q mini_sqlite
```

`examples/benchmark.py` is illustrative only and is not a production benchmark.

For new mechanisms include happy paths, invariants, errors, reopen/persistence checks, access-path diagnostics, concurrency/fault/crash cases where relevant, and one educational example.

## 8. Documentation contract

Review when architecture/public behavior changes:

```text
Agents.md
Plan.md
version.md
README.md
relevant docs/*
relevant tests/examples
```

## 9. Stable v1.0 non-goals

- SQLite file/API parity;
- cross-process OS locking;
- MVCC or multi-writer WAL;
- savepoints;
- online/incremental VACUUM;
- free-list page reuse;
- production cost calibration;
- query parallelism;
- production security/performance guarantees.

## 10. Post-1.0 extensions

Optional directions are documented in `Plan.md`, including cross-process locking, free-list reuse, range/composite indexes, savepoints, additional join algorithms, and an MVCC experiment.

Each must be a distinct version with one dominant mental model; do not blur them into the frozen v1.0 branch.
