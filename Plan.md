# mini-sqlite — Architecture-Driven Development Plan

> Canonical roadmap snapshot after v0.2. `main` must remain the newest integrated, validated state. Version branches are readable learning snapshots.

## 1. Project purpose

mini-sqlite removes one layer of SQLite/database “magic” at a time using readable Python. The roadmap follows architectural dependency order:

```text
Page / record format
      ↓
Persistent B+Tree
      ↓
SQL → planner → VM
      ↓
Rollback transactions
      ↓
Secondary indexes
      ↓
Relational operators
      ↓
JOIN
      ↓
WAL
      ↓
Bounded buffer manager
      ↓
Cost-based optimizer
      ↓
Concurrency / locking
```

One version should introduce one dominant mental model.

## 2. Completed milestones

### v0.1 — Storage engine + SQL-to-VM vertical slice ✅

**Question:** How does SQL ultimately become page reads/writes in one database file?

Implemented fixed 4 KiB pages, typed records, slotted B+Tree pages, leaf/internal/root splits, persistent catalog, tokenizer/parser/AST, rule planner, VDBE-inspired bytecode/VM, `CREATE`/`INSERT`/`SELECT`/`DELETE`, and physical debug commands.

### v0.2 — Transactions + rollback journal ✅

**Question:** What prevents a page-oriented database from being half-written after a crash?

Implemented:

- `BEGIN`, `COMMIT`/`END`, `ROLLBACK`;
- connection transaction state machine;
- write-statement autocommit;
- before-image rollback journal;
- original-page-count recovery/truncation;
- CRC32 per complete journal entry;
- journal fsync → DB write/fsync → journal-delete protocol;
- hot-journal detection before normal database metadata is opened;
- crash recovery after uncommitted pages reach the main file;
- rollback of B+Tree splits and schema/catalog changes;
- Python transaction context manager;
- `.txn` debug state.

Pager remains the durability boundary; B+Tree code is journal-agnostic.

## 3. Current next milestone — v0.3 Secondary Indexes + Planner 🎯

### Central question

> Why can an index transform a filter from a table scan into logarithmic navigation, and what extra work is required to keep that index correct?

### Target architecture

```text
                         Catalog
                      /           \
                 table meta      index meta
                      |              |
SQL → Planner → AccessPath         Index B+Tree
                 /      \              |
          table scan   index seek ── rowid
                                ↓
                           table B+Tree
```

### v0.3.1 `CREATE INDEX`

Add syntax/AST/catalog representation for:

```sql
CREATE INDEX idx_users_age ON users(age);
```

Catalog metadata should record index name, table id/name, indexed columns, uniqueness flag (non-unique first), and index root page.

### v0.3.2 Generic sortable index keys

v0.1/v0.2 table B+Trees use integer primary keys. v0.3 should introduce an explicit key-codec boundary rather than scattering special cases through BTree.

Candidate abstraction:

```text
KeyCodec
  encode(value or tuple) -> sortable bytes
  compare(encoded_a, encoded_b)
```

Keep the first implementation readable; do not prematurely build a full SQLite serial-type comparator.

### v0.3.3 Duplicate secondary keys

Secondary indexes are commonly non-unique. Represent the mapping explicitly, for example:

```text
(index_key, rowid) as composite ordered key
```

This avoids ad-hoc Python posting lists and preserves ordered page-backed semantics.

### v0.3.4 Planner access paths

Planner should choose among:

```text
TABLE_SCAN
PRIMARY_KEY_SEEK
SECONDARY_INDEX_SEEK
```

Use a simple rule/selectivity heuristic first. Cost-based planning belongs to v0.8.

### v0.3.5 Index maintenance

`INSERT` and `DELETE` must update table and affected index B+Trees in the **same v0.2 transaction**. A crash must not leave table and index inconsistent.

This is the most important cross-version invariant for v0.3.

### v0.3.6 Explainability

Extend `.explain` / query-plan output so the selected index and follow-up rowid lookup are visible.

### Definition of Done for v0.3

Tests should prove:

- index metadata survives reopen;
- duplicate secondary keys work;
- index root splits persist correctly;
- planner selects primary-key vs secondary-index vs scan paths correctly;
- INSERT/DELETE maintain indexes;
- rollback/crash recovery restores both table and index atomically;
- full v0.1/v0.2 regression remains green;
- educational example compares scan vs index seek.

### Explicit non-goals for v0.3

No cost-based optimizer, multi-column statistics, partial/expression indexes, covering-index optimization, joins, WAL, or concurrent writers.

## 4. Future milestones

### v0.4 — Relational execution engine

`UPDATE`, `LIMIT`, `ORDER BY`, aggregates, richer expressions, NULL-aware comparisons, and clearer iterator/VM composition.

### v0.5 — JOIN

Qualified names, aliases, INNER JOIN, nested-loop and indexed nested-loop joins; optional teaching-only hash join.

### v0.6 — WAL

WAL header/frames, commit marker, read overlay, checkpoint, recovery, snapshot concept, WAL inspection.

### v0.7 — Buffer manager

Bounded cache, pin/unpin, LRU/Clock replacement, eviction/writeback, hit/miss metrics.

### v0.8 — Cost-based optimizer

Statistics, cardinality/selectivity estimation, I/O cost model, index-vs-scan costing, join-order costing, `ANALYZE`.

### v0.9 — Concurrency and locking

Connection abstraction, shared/reserved/pending/exclusive lock states, busy timeout, concurrent-process tests.

### v1.0 — Educationally complete mini SQLite

Durable rollback/WAL modes, primary/secondary indexes, basic joins/aggregates, bounded page cache, explainable planning, crash tests, documented binary formats and benchmark/inspection tooling.

## 5. Version-development protocol

For every future version:

```text
read main/Agents.md + Plan.md + version.md
        ↓
create vX.Y from latest validated main
        ↓
write version boundary + docs first
        ↓
implement smallest readable mechanism
        ↓
add invariant/error/crash/integration tests
        ↓
add educational example + architecture docs
        ↓
run full regression
        ↓
freeze version branch
        ↓
integrate validated tree into main
        ↓
restore canonical main docs
        ↓
advance Plan.md
```

## 6. Compatibility policy

Before v1.0, Python APIs may evolve between minor versions. Incompatible on-disk changes require `FORMAT_VERSION` changes, updated format docs, and either migration support or an explicit incompatibility note.
