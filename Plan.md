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

## 3. Current next milestone — v0.8 Cost-Based Optimizer 🎯

### Central question

> When several correct plans exist, how can the database estimate their work and choose a plan from data rather than from fixed rules?

v0.3-v0.5 introduced physical alternatives but Planner selection is still mostly heuristic: PK equality beats secondary equality, otherwise scan; JOIN outer/inner order is syntax-driven.

### Target architecture

```text
Catalog statistics
   ├─ row count
   ├─ distinct count
   ├─ min / max
   └─ optional histograms
          ↓
Cardinality estimator
          ↓
Cost model
   ├─ table scan
   ├─ PK seek
   ├─ index seek + row lookup
   └─ nested-loop alternatives
          ↓
Candidate plans
          ↓
choose min estimated cost
          ↓
EXPLAIN estimated rows / cost
```

### v0.8.1 ANALYZE / statistics

Add a small statistics subsystem rather than reading the entire table during every planning decision. Suggested first metadata:

```text
table row_count
column distinct_count
column null_count
column min/max for INTEGER
index metadata
```

Statistics should be persistent or explicitly recomputable, with a clear staleness model.

### v0.8.2 selectivity estimation

Teach simple estimates first:

```text
PK equality            ≈ 1 row
indexed equality       ≈ N / distinct
range on INTEGER       ≈ fraction from min/max
unknown predicate      conservative fallback
```

Correctness must never depend on estimate quality; estimates only choose among equivalent plans.

### v0.8.3 access-path costs

Expose comparable conceptual costs, for example:

```text
table scan              pages(table)
PK seek                 tree_height + 1
secondary equality      index_height + matches * table_lookup
```

Use buffer-aware page concepts, but do not pretend to model real hardware precisely.

### v0.8.4 JOIN order

For two-table INNER JOIN, compare at least both legal nested-loop orientations:

```text
A outer -> B inner
B outer -> A inner
```

Include whether the chosen inner side has PK/index lookup. This is the first version where SQL FROM order should not necessarily equal physical join order.

### v0.8.5 EXPLAIN observability

Show:

```text
estimated rows
estimated cost
chosen access path
rejected alternatives
join orientation
```

The teaching goal is to make optimizer reasoning auditable.

### Definition of Done for v0.8

- statistics can be collected deterministically;
- equality/range estimates have tests;
- scan vs index choice can flip with data distribution;
- JOIN orientation can flip based on cardinality/indexes;
- EXPLAIN exposes estimates/costs;
- stale/missing stats have safe fallbacks;
- all v0.1-v0.7 storage/durability/buffer tests stay green;
- exact final branch-head CI passes.

### Explicit non-goals for v0.8

No Selinger-style exhaustive many-way JOIN optimizer, sophisticated histograms, adaptive runtime reoptimization, vectorized execution, ML cardinality estimation, or concurrent DDL/statistics maintenance.

## 4. Future milestones

### v0.9 — Concurrency and locking

Connection abstraction, lock states, busy timeout, concurrent-process tests, transaction interaction with WAL/rollback modes.

### v1.0 — Educationally complete mini SQLite

Durable rollback/WAL modes, primary/secondary indexes, relational operators and joins, bounded page cache, explainable cost planning, crash tests, documented formats, benchmark/inspection tooling.

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
