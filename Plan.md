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

- 4 KiB Pager;
- slotted table/catalog B+Tree;
- search/insert/delete/scan/splits;
- typed record codec;
- persistent catalog;
- tokenizer/parser/AST;
- rule planner;
- tiny VDBE-inspired VM;
- PK seek vs table scan;
- CREATE TABLE / INSERT / SELECT / DELETE.

### v0.2 — Rollback-journal transactions + crash recovery ✅

- BEGIN / COMMIT / ROLLBACK;
- autocommit writes;
- before-image journal;
- journal-first fsync ordering;
- hot-journal startup recovery;
- truncation of transaction-created pages;
- rollback across tree/catalog/meta root changes.

### v0.3 — Secondary indexes + richer planner ✅

- CREATE INDEX;
- persistent IndexSchema;
- byte-key secondary-index B+Tree;
- typed composite `(value,rowid)` keys;
- duplicate equality runs;
- planner PRIMARY_KEY / SECONDARY_INDEX / TABLE_SCAN;
- explicit index-to-table rowid lookup;
- transactional INSERT/DELETE index maintenance;
- crash recovery across table + indexes.

### v0.4 — Relational Execution Engine ✅

Central question:

> How should SQL row processing compose as explicit execution mechanisms instead of accumulating statement-specific special cases?

Implemented:

- UPDATE with type validation and fixed INTEGER PRIMARY KEY identity;
- comparison predicates `= != < <= > >=`;
- ORDER BY ASC/DESC;
- LIMIT;
- COUNT / SUM / MIN / MAX;
- explicit VM stages `FILTER_COMPARE / COLLECT_ROW / SORT_ROWS / PROJECT_ROWS / AGGREGATE_ROWS / LIMIT_ROWS / EMIT_ROWS`;
- full-row sort before projection;
- equality index paths preserved while range predicates correctly fall back to scans;
- UPDATE maintenance of all secondary indexes;
- rollback and hot-journal recovery for UPDATE;
- relational execution documentation and example.

## 3. Current next milestone — v0.5 JOIN 🎯

### Central question

> How can two row sources be composed while keeping name resolution, physical access paths, and join algorithms explicit?

v0.4 now has a visible single-source relational pipeline. JOIN is the next mechanism because it forces the engine to compose multiple sources rather than merely transform one source.

### Target architecture

```text
                 logical join
                 /          \
          left source     right source
             │               │
      scan/PK/index      scan/PK/index
             \               /
              \             /
               join operator
                    ↓
                  filter
                    ↓
                projection
                    ↓
             sort / limit
                    ↓
                  result
```

### v0.5.1 aliases and qualified names

Support enough name resolution for unambiguous joins:

```sql
SELECT u.name, o.total
FROM users u
JOIN orders o ON u.id = o.user_id;
```

Requirements:

- table aliases;
- qualified column references;
- clear ambiguous-column errors;
- keep name binding in Planner/schema resolution, not storage.

### v0.5.2 INNER JOIN

Start with one explicit form:

```sql
FROM left JOIN right ON left.col = right.col
```

Do not add OUTER/CROSS/NATURAL joins until INNER JOIN mechanics are clear.

### v0.5.3 nested-loop join reference path

Implement the most readable baseline first:

```text
for left row:
    for right row:
        if join predicate:
            emit combined row
```

This is the reference algorithm and correctness baseline.

### v0.5.4 indexed nested-loop join

When the inner join column has a usable primary/secondary equality index:

```text
outer row
   ↓
extract join key
   ↓
seek inner PK/index
   ↓
matching rows
```

Planner should expose why the indexed path was chosen. Do not add cost estimates yet; a rule-based choice is enough.

### v0.5.5 join bytecode / operator visibility

The execution model should make the join mechanism visible, for example:

```text
OPEN_LEFT
OPEN_RIGHT
REWIND_LEFT
REWIND_RIGHT / SEEK_INNER
JOIN_COMPARE
...
```

or an equally clear relational operator representation. Do not hide the complete join in one opaque helper.

### v0.5.6 optional teaching comparison: hash join

A small in-memory hash join may be added only after nested-loop correctness is complete, to contrast algorithmic trade-offs. It is not required for v0.5 completion.

### Definition of Done for v0.5

Tests should prove:

- aliases and qualified names resolve correctly;
- ambiguous columns fail clearly;
- INNER JOIN works with duplicate matches;
- nested-loop join is correct;
- indexed nested-loop join is planner-visible and equivalent to nested loop;
- downstream projection/filter/order/limit compose with joined rows;
- transactions/storage/index behavior from v0.1-v0.4 remains unchanged;
- full regression and exact branch-head CI pass.

### Explicit non-goals for v0.5

No LEFT/RIGHT/FULL OUTER JOIN, GROUP BY/HAVING, subqueries, join reordering, cost-based join optimization, spill-to-disk hash tables, WAL, or concurrency.

## 4. Future milestones

### v0.6 — WAL

WAL header/frames, commit marker, read overlay, checkpoint, recovery, snapshot concept, WAL inspection.

### v0.7 — Buffer manager

Bounded cache, pin/unpin, LRU/Clock replacement, eviction/writeback, hit/miss metrics.

### v0.8 — Cost-based optimizer

Statistics, cardinality/selectivity estimation, I/O cost model, scan-vs-index costing, join-order costing, `ANALYZE`.

### v0.9 — Concurrency and locking

Connection abstraction, shared/reserved/pending/exclusive locks, busy timeout, concurrent-process tests.

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

Before v1.0, Python APIs may evolve between minor versions. Existing page formats should remain readable when practical. Any incompatible byte-layout change requires `FORMAT_VERSION` review, reopen tests, and an explicit compatibility/migration statement.
