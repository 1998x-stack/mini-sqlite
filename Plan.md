# mini-sqlite — Architecture-Driven Development Plan

> Canonical roadmap.
>
> **Invariant:** `main` is always the newest integrated, validated state. Version branches are readable learning snapshots. One version introduces one dominant database mental model.

## 1. Project purpose

mini-sqlite removes one layer of database “magic” at a time with readable Python implementations.

```text
pages / records
      ↓
primary B+Tree
      ↓
SQL / planner / VM
      ↓
rollback recovery
      ↓
secondary indexes
      ↓
relational operators
      ↓
joins
      ↓
WAL
      ↓
buffer manager
      ↓
cost optimizer
      ↓
concurrency
```

## 2. Completed milestones

### v0.1 — Page-backed B+Tree + SQL → Planner → VM ✅

4 KiB Pager, slotted B+Tree, typed records, persistent catalog, Parser/AST/Planner/VM, PK seek vs scan, CREATE/INSERT/SELECT/DELETE.

### v0.2 — Rollback-journal transactions + crash recovery ✅

BEGIN/COMMIT/ROLLBACK, autocommit writes, before-image journal, fsync ordering, hot-journal recovery, transaction-created-page truncation.

### v0.3 — Secondary indexes + richer planner ✅

CREATE INDEX, persistent index metadata, byte-key B+Tree, `(value,rowid)` keys, duplicate equality runs, secondary-index seek + rowid lookup, atomic table/index maintenance.

### v0.4 — Relational Execution Engine ✅

UPDATE, richer comparisons, ORDER BY, LIMIT, scalar aggregates, explicit materialized relational stages, transactional indexed-column UPDATE.

### v0.5 — INNER JOIN + Indexed Nested Loop ✅

Aliases, qualified names, ambiguity detection, self-join, plain nested loop, PK indexed nested loop, secondary-index nested loop, post-JOIN relational stages.

### v0.6 — WAL + read overlay + checkpoint ✅

Implemented:

- explicit rollback/WAL durability mode;
- documented WAL sidecar format;
- full-page after-image FRAME records;
- transaction COMMIT records carrying logical page count and frame count;
- CRC validation and bounds checking;
- newest committed frame overlay on Pager reads;
- private in-memory rollback before WAL commit;
- torn/uncommitted WAL tail recovery;
- multiple committed transactions per WAL;
- checkpoint ordering that keeps WAL until database fsync;
- partial-checkpoint crash recovery;
- pages/root splits beyond main-file EOF;
- WAL -> rollback mode switch through checkpoint;
- `.wal` / `.checkpoint` inspection;
- no query/B+Tree rewrite above Pager.

## 3. Current next milestone — v0.7 Buffer Manager 🎯

### Central question

> What changes when the database can no longer keep every touched page in memory, and page residency becomes a bounded resource that must be pinned, evicted, measured, and written back safely?

v0.1-v0.6 use an effectively unbounded Python dictionary cache. v0.7 should turn that hidden convenience into an explicit subsystem.

### Target architecture

```text
B+Tree / Index / Catalog
          ↓
       Pager API
          ↓
    Buffer Manager
  ┌────────┼─────────┐
  ▼        ▼         ▼
frames   replacer   stats
  │      LRU/Clock   hit/miss
  │
  ├─ pin count
  ├─ dirty bit
  └─ page id
          ↓
 durability layer
 rollback / WAL
          ↓
      disk files
```

### v0.7.1 bounded frames

Introduce a configurable capacity, for example:

```python
Database("demo.db", buffer_pages=32)
```

The buffer manager owns a fixed number of frames rather than allowing `_cache` to grow forever.

### v0.7.2 pin / unpin

A page currently in use by a cursor/tree operation cannot be evicted.

```text
fetch page -> pin_count += 1 -> use page -> unpin -> pin_count -= 1
```

### v0.7.3 replacement policy

Implement one readable policy first, preferably LRU or Clock. Eviction candidates require `pin_count == 0`.

Dirty eviction must respect the active durability mode rather than bypassing WAL/journal ordering.

### v0.7.4 observability

Expose capacity, resident/pinned/dirty pages, hits, misses, evictions, writebacks and hit ratio. A `.buffer` command would make the mechanism visible.

### v0.7.5 durability interaction

- rollback mode must preserve journal-before-database ordering;
- WAL mode must never write uncommitted pages into the main DB;
- committed WAL-backed pages may be evicted because WAL is durable truth;
- checkpoint should remain independent of residency.

### Definition of Done for v0.7

Tests should prove capacity bounds, pin safety, replacement behavior, dirty writeback correctness in rollback mode, WAL correctness under eviction, query correctness with tiny buffers, inspectable metrics, and green reopen/crash regression on the exact final branch head.

### Explicit non-goals for v0.7

No async I/O, direct-I/O tuning, prefetcher, ARC/2Q sophistication, multi-connection lock manager, cost optimizer, or production-grade memory accounting.

## 4. Future milestones

### v0.8 — Cost-based optimizer

Statistics, cardinality/selectivity estimation, scan/index costing, join-order costing, `ANALYZE`.

### v0.9 — Concurrency and locking

Connection abstraction, lock states, busy timeout, concurrent-process tests, transaction interaction with WAL/rollback modes.

### v1.0 — Educationally complete mini SQLite

Durable rollback/WAL modes, primary/secondary indexes, relational operators and joins, bounded page cache, explainable planning, crash tests, documented formats, benchmark/inspection tooling.

## 5. Version-development protocol

```text
read main/Agents.md + Plan.md + version.md
        ↓
create vX.Y from latest main
        ↓
write branch version.md + Agents.md
        ↓
implement smallest readable reference mechanism
        ↓
add invariant/error/persistence/crash tests as relevant
        ↓
add educational example + architecture docs
        ↓
run full regression
        ↓
exact final version-branch CI green
        ↓
freeze version branch
        ↓
integrate same validated engine tree into main
        ↓
restore canonical main Agents.md/version.md
        ↓
advance roadmap
```

## 6. Compatibility policy

Before v1.0, Python APIs may evolve between minor versions. Existing main database page formats should remain readable when practical. Any incompatible byte-layout or durability-protocol change requires format review, reopen tests, and an explicit compatibility/migration statement.
