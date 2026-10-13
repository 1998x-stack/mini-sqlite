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
bounded buffer manager
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

After-image FRAME records, COMMIT boundaries, logical read overlay, torn-tail recovery, checkpoint, page creation beyond DB EOF, rollback/WAL mode switching.

### v0.7 — Bounded Buffer Manager ✅

Central question:

> What changes when the database can no longer keep every touched page in memory?

Implemented:

- configurable fixed frame capacity;
- `BufferFrame` metadata: page id, bytes, dirty, pin count, replacement state;
- explicit pin/unpin context;
- LRU replacement;
- CLOCK second-chance replacement;
- hit/miss/eviction/dirty-eviction statistics;
- rollback dirty eviction after journal-before-DB ordering;
- WAL blocking of uncommitted dirty eviction;
- clean committed WAL-frame eviction/reload through overlay;
- tiny-buffer B+Tree/index/JOIN regression;
- `.buffer` / `.frames` inspection;
- no page-format or durability-format change.

## 3. Completed milestone — v0.8 Cost-Based Optimizer ✅

Central question:

> When several correct plans exist, how can the database estimate their work and choose from data rather than fixed rules?

Implemented:

- `ANALYZE` / `ANALYZE table` statistics collection;
- persistent row/null/distinct/min/max statistics;
- top-16 most-common-value frequencies for skew;
- explicit stale-statistics semantics;
- equality/range cardinality estimates;
- table scan vs PK/index candidate costs;
- two legal JOIN orientations compared by cost;
- physical JOIN order independent from SQL order;
- PK/index/scan inner probes under either orientation;
- EXPLAIN estimated rows, estimated cost and rejected candidates;
- `Catalog.get_table(...).stats` inspection;
- rollback/WAL durability tests for optimizer metadata.

## 4. Current next milestone — v0.9 Concurrency / Locking 🎯

### Central question

> What changes when two independent connections can read or write the same database at the same time?

### Target architecture

```text
Connection A                 Connection B
     │                            │
 transaction                  transaction
     │                            │
     └──────── Lock Manager ──────┘
                  │
        shared / reserved / exclusive
                  │
                Pager
          ┌───────┴───────┐
       rollback          WAL
```

### v0.9.1 connection-visible lock states

Teach a small state machine first. Rollback mode should make reader/writer exclusion visible rather than relying on accidental process behavior.

### v0.9.2 busy handling

Add deterministic busy errors and a bounded busy timeout/retry policy. Never spin forever.

### v0.9.3 WAL reader/writer distinction

WAL should demonstrate why readers can continue to observe committed snapshots while one writer appends newer frames, while still keeping a single-writer simplification.

### v0.9.4 multi-connection tests

Use separate `Database` instances against one file and cover reader-reader, reader-writer, writer-writer, rollback, crash/reopen, and checkpoint interactions.

### Definition of Done for v0.9

- lock state is explicit and inspectable;
- conflicting writers fail or wait deterministically;
- rollback mode reader/writer rules are tested;
- WAL reader/writer behavior is tested;
- transaction cleanup releases locks after commit/rollback/error;
- old optimizer/storage/durability tests stay green;
- exact final branch-head CI passes.

### Explicit non-goals for v0.9

No MVCC engine, distributed locking, deadlock graph detector, row-level locks, predicate locks, Serializable Snapshot Isolation, or multi-writer WAL.

## 5. Future milestones

### v1.0 — Educationally complete mini SQLite

Durable rollback/WAL modes, primary/secondary indexes, relational operators and joins, bounded page cache, explainable cost planning, crash tests, documented formats, benchmark/inspection tooling.

## 6. Version-development protocol

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

## 7. Compatibility policy

Before v1.0, Python APIs may evolve between minor versions. Existing main database page formats should remain readable when practical. Any incompatible byte-layout or durability-protocol change requires format review, reopen tests, and an explicit compatibility/migration statement.
