# mini-sqlite — Architecture-Driven Development Plan

> Canonical roadmap for `main`.
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

Implemented:

- 4 KiB Pager;
- slotted leaf/internal pages;
- B+Tree search/insert/delete/scan/splits;
- RecordCodec;
- persistent catalog;
- tokenizer/parser/AST;
- rule planner;
- tiny VDBE-inspired VM;
- primary-key seek vs full scan;
- CREATE TABLE / INSERT / SELECT / DELETE;
- inspection commands.

### v0.2 — Rollback-journal transactions + crash recovery ✅

Implemented:

- BEGIN / COMMIT / ROLLBACK;
- write autocommit;
- before-image journal;
- one-before-image-per-old-page rule;
- original-page-count truncation;
- journal fsync → DB write/fsync → journal deletion;
- hot-journal startup recovery;
- rollback across B+Tree/catalog/meta root changes;
- Python transaction context manager;
- fault/crash tests.

### v0.3 — Secondary indexes + richer planner ✅

Central question:

> How can a secondary index provide a different ordered access path while INSERT/DELETE and crash recovery keep table and index state atomically consistent?

Implemented:

- `CREATE INDEX name ON table(column)`;
- persistent `IndexSchema` in table metadata;
- byte-key index B+Tree with slotted leaf/internal pages;
- `KeyCodec` for INTEGER/TEXT/NULL;
- `(indexed_value, rowid)` physical composite keys;
- duplicate-key equality runs;
- existing-row index build;
- index root split persistence;
- planner `PRIMARY_KEY / SECONDARY_INDEX / TABLE_SCAN` paths;
- VM `OPEN_INDEX / SEEK_INDEX_EQ / INDEX_TO_TABLE / INDEX_NEXT`;
- transactional INSERT/DELETE index maintenance;
- rollback and hot-journal recovery across table + index;
- index inspection and educational example.

## 3. Current next milestone — v0.4 Relational Execution Engine 🎯

### Central question

> How should SQL relational operations compose as execution mechanisms instead of accumulating statement-specific special cases inside the VM?

v0.3 now has multiple access paths. Before JOIN or cost optimization, the engine needs richer row-processing operators.

### Target architecture

```text
SQL / AST
    ↓
Planner
    ↓
logical plan
    ↓
access source
(table / PK / index)
    ↓
Filter
    ↓
Projection
    ↓
Sort / Limit / Aggregate
    ↓
Result
```

The exact implementation may remain bytecode-oriented, but operator boundaries must be explicit enough that v0.5 JOIN can compose with them.

### v0.4.1 UPDATE

Add:

```sql
UPDATE users SET age = 21 WHERE id = 1;
```

Requirements:

- reuse access-path planning;
- validate assignment types;
- if an indexed column changes, remove old index key and insert new index key in the same transaction;
- primary-key updates may be an explicit non-goal if they obscure the version.

### v0.4.2 richer expressions

At minimum consider:

```text
=
!=
<
<=
>
>=
AND
```

Keep expression evaluation separate from storage navigation. Do not yet build a full SQL expression engine.

### v0.4.3 LIMIT

```sql
SELECT * FROM users LIMIT 10;
```

LIMIT should stop upstream execution rather than materialize all rows first when practical.

### v0.4.4 ORDER BY

```sql
SELECT * FROM users ORDER BY age;
```

Start with an explicit in-memory sort operator. Do not silently claim that a secondary index always satisfies ordering; that optimization belongs later.

### v0.4.5 aggregates

Start with:

```text
COUNT
SUM
MIN
MAX
```

Make aggregate state explicit and test NULL behavior defined by mini-sqlite.

### v0.4.6 execution composition

Refactor only as much as necessary to make the flow visible:

```text
source → filter → project → aggregate/sort/limit
```

Avoid premature iterator-framework complexity if a small VM-compatible operator boundary is clearer.

### Definition of Done for v0.4

Tests should prove:

- UPDATE works for scanned/PK/indexed predicates;
- indexed-column UPDATE maintains indexes atomically;
- LIMIT stops correctly;
- ORDER BY returns deterministic ordering;
- COUNT/SUM/MIN/MAX work on supported types;
- expression/error semantics are documented;
- v0.3 index path remains visible in EXPLAIN;
- rollback/crash behavior remains correct;
- full v0.1–v0.3 regression stays green.

### Explicit non-goals for v0.4

No JOIN, subqueries, GROUP BY/HAVING, window functions, sophisticated NULL three-valued logic, external sort, statistics, WAL, or concurrency.

## 4. Future milestones

### v0.5 — JOIN

Qualified names, aliases, INNER JOIN, nested-loop join, indexed nested-loop join; optional teaching-only hash join comparison.

### v0.6 — WAL

WAL header/frames, commit marker, read overlay, checkpoint, recovery, snapshot concept, WAL inspection.

### v0.7 — Buffer manager

Bounded cache, pin/unpin, LRU/Clock replacement, eviction/writeback, hit/miss metrics.

### v0.8 — Cost-based optimizer

Statistics, cardinality/selectivity estimation, I/O cost model, scan-vs-index costing, join-order costing, `ANALYZE`.

### v0.9 — Concurrency and locking

Connection abstraction, shared/reserved/pending/exclusive locks, busy timeout, concurrent-process tests.

### v1.0 — Educationally complete mini SQLite

Durable rollback/WAL modes, primary/secondary indexes, basic relational operators and joins, bounded page cache, explainable planning, crash tests, documented formats, benchmark/inspection tooling.

## 5. Version-development protocol

```text
read main/Agents.md + Plan.md + version.md
        ↓
create vX.Y from latest main
        ↓
write version boundary/docs
        ↓
implement smallest readable mechanism
        ↓
add invariant/error/persistence/crash tests
        ↓
add educational example
        ↓
run full regression
        ↓
exact version branch CI green
        ↓
freeze version branch
        ↓
integrate same validated engine tree into main
        ↓
restore canonical main Agents.md/version.md
        ↓
advance Plan.md
```

## 6. Compatibility policy

Before v1.0, Python APIs may evolve between minor versions. Existing page formats should remain readable when practical. Additive metadata/page types must be documented. Any incompatible byte-layout change requires `FORMAT_VERSION` review, reopen tests, and an explicit compatibility/migration statement.
