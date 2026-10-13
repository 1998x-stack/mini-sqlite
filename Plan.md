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
transactions / recovery
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

Central question:

> How can two row sources be composed while keeping name resolution, physical access paths, and join algorithms explicit?

Implemented:

- `JOIN` / `INNER JOIN`;
- table aliases and qualified names;
- ambiguity detection and self-join aliases;
- equality ON predicate between the two sources;
- plain nested-loop reference algorithm;
- primary-key indexed nested loop;
- secondary-index indexed nested loop;
- duplicate inner matches;
- explicit JOIN bytecode rather than an opaque helper;
- joined rows flowing through v0.4 filter/sort/project/aggregate/limit;
- no on-disk format change.

## 3. Current next milestone — v0.6 WAL 🎯

### Central question

> How can committed changes be made durable by appending new page images to a log first, while readers still reconstruct the newest database view and checkpoints eventually fold frames back into the main file?

v0.2 established rollback-journal **before images**. v0.6 should deliberately contrast that with WAL **after images**.

### Target architecture

```text
                 read page N
                     │
                     ▼
              WAL frame lookup?
                /          \
              yes          no
              │             │
              ▼             ▼
        newest WAL frame   main db page
              \             /
               \           /
                 Pager view

writer:
page mutation
    ↓
append WAL frame
    ↓
append commit marker / commit boundary
    ↓
fsync WAL

checkpoint:
committed WAL frames
    ↓
copy newest page versions to database file
    ↓
fsync database
    ↓
reset/truncate WAL when safe
```

### v0.6.1 WAL file format

Define a small, documented format containing at minimum:

- magic/version;
- database page size;
- frame sequence/order;
- target page id;
- page image;
- transaction/commit boundary metadata;
- integrity/bounds validation sufficient for educational recovery tests.

Any durable protocol is part of the format contract even if main database page bytes remain unchanged.

### v0.6.2 write path

A write transaction in WAL mode should not overwrite committed database pages before WAL durability.

Conceptual sequence:

```text
dirty logical page
      ↓
append after-image frame
      ↓
commit boundary
      ↓
fsync WAL
      ↓
transaction visible as committed
```

Do not mix rollback-journal and WAL ordering implicitly. Make mode ownership explicit at Pager/durability boundaries.

### v0.6.3 read overlay

Reads must see the newest committed version:

```text
page id
  ↓
latest committed WAL frame?
  ├─ yes -> frame bytes
  └─ no  -> database file bytes
```

Keep B+Tree/query layers unaware of whether bytes came from WAL or the database file.

### v0.6.4 crash recovery

Tests should cover crashes:

- before commit marker;
- after committed frames are durable;
- during/after checkpoint;
- with multiple committed transactions in WAL;
- with pages created past the current database EOF.

Uncommitted tail frames must not become visible after reopen.

### v0.6.5 checkpoint

Implement one clear checkpoint mode first. It should copy the newest committed frame for each page to the database file and preserve crash safety.

Expose inspection such as:

```text
.wal
.checkpoint
```

or equivalent Python/debug surfaces.

### v0.6.6 mode boundary

A simple explicit open option is preferable to hidden policy, e.g. rollback-journal by default with an educational WAL mode. Do not implement concurrent writer sophistication yet.

### Definition of Done for v0.6

Tests should prove:

- committed WAL transactions survive reopen;
- uncommitted/crashed WAL tail is ignored;
- B+Tree/catalog/index/JOIN behavior is unchanged above Pager;
- checkpoint preserves logical contents;
- page creation/root splits survive WAL commit/checkpoint;
- WAL state is inspectable;
- exact final branch-head CI passes on the full regression suite.

### Explicit non-goals for v0.6

No multi-writer concurrency, production SQLite WAL binary compatibility, shared-memory `-shm` implementation, sophisticated checkpoint scheduling, snapshot isolation across many simultaneous connections, cost optimizer, or bounded buffer replacement.

## 4. Future milestones

### v0.7 — Buffer manager

Bounded cache, pin/unpin, LRU/Clock replacement, eviction/writeback, hit/miss metrics.

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

Before v1.0, Python APIs may evolve between minor versions. Existing page formats should remain readable when practical. Any incompatible byte-layout or durability-protocol change requires `FORMAT_VERSION` review, reopen tests, and an explicit compatibility/migration statement.
