# mini-sqlite

## v1.3 — Ordered Range Scans + Composite Indexes

v1.3 turns secondary indexes into ordered access paths. It adds `< <= > >= BETWEEN`, conjunctions with `AND`, composite indexes such as `(region, ts)`, the SQL left-prefix rule, and cost-based choice between range index scans and table scans. See `docs/ORDERED_INDEXES.md` and `examples/range_indexes.py`.

```text
WHERE region = 'us' AND ts BETWEEN 20 AND 40
                 ↓
       composite index (region, ts)
                 ↓
          SEEK_INDEX_RANGE
                 ↓
             rowid lookup
```


A Python-first, SQLite-inspired educational database engine built as a sequence of architectural milestones. It is **not** a wrapper around Python `sqlite3`, and it is **not** SQLite file-format compatible.

## v1.0 — Educationally Complete

The project now forms one inspectable path from SQL text to durable storage and maintenance:

```text
SQL text
   ↓
Tokenizer / Parser / AST
   ↓
Cost-Based Planner  ← ANALYZE statistics
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

Maintenance / diagnostics observe the whole stack:
  integrity_check · reindex · vacuum · explain_analyze
```

## Version progression

```text
v0.1  Page/Pager/B+Tree + SQL/Planner/VM
v0.2  Rollback Journal + Crash Recovery
v0.3  Secondary Index
v0.4  Relational Execution + UPDATE
v0.5  INNER JOIN + Indexed Nested Loop
v0.6  WAL + Read Overlay + Checkpoint
v0.7  Bounded Buffer Manager + LRU/CLOCK
v0.8  ANALYZE + Cost-Based Optimizer
v0.9  Multi-Connection Concurrency + Locks
v1.0  Integrity / REINDEX / VACUUM / EXPLAIN ANALYZE
v1.1  Cross-process File Locking
v1.2  Free-list Page Reuse + Incremental VACUUM
v1.3  Range Index Scan + Composite Index                 ← current
```

## Quick start

```python
from mini_sqlite import Database

with Database("demo.db") as db:
    db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, age INTEGER, name TEXT);")
    db.execute("INSERT INTO users VALUES (1, 20, 'Alice');")
    db.execute("CREATE INDEX idx_users_age_name ON users(age, name);")
    db.execute("ANALYZE users;")

    print(db.execute("SELECT * FROM users WHERE age BETWEEN 18 AND 25;").rows)
    print(db.explain("SELECT * FROM users WHERE age BETWEEN 18 AND 25;"))
    print(db.explain_analyze("SELECT * FROM users WHERE age BETWEEN 18 AND 25;").render())
    print(db.integrity_check().render())
```

## v1.0 maintenance lifecycle

### Integrity check

```python
report = db.integrity_check()
print(report.ok)
print(report.render())
```

The checker validates more than page decodability. It verifies:

- Catalog/table/index B+Tree parent-child structure;
- separator/key ordering and leaf sibling chains;
- row record decoding and schema types;
- INTEGER PRIMARY KEY == stored rowid;
- secondary-index contents exactly match table rows;
- page ownership across trees;
- unreachable/orphan pages;
- stale ANALYZE statistics as a warning rather than corruption.

### REINDEX

```python
db.reindex("idx_users_age")  # one index
db.reindex()                 # all indexes
```

A rebuild allocates a new index tree and updates the catalog inside the existing transaction machinery. Failure/ROLLBACK restores the old root and truncates new pages. Old successful index pages are returned to the persistent free-list inside the same transaction.

### VACUUM

```python
result = db.vacuum()
print(result.render())
```

VACUUM rebuilds the logical database into a private compact file, recreates indexes/statistics, and atomically replaces the old file. It requires global OS-level exclusivity so another process cannot keep a live reader snapshot while the inode is replaced. v1.2 adds `incremental_vacuum()` for the cheaper case where already-free pages form a tail suffix and no live pages need to move.

### EXPLAIN ANALYZE

```python
print(
    db.explain_analyze(
        "SELECT id FROM users WHERE age = 20 ORDER BY id LIMIT 5;"
    ).render()
)
```

It combines:

```text
estimated plan / candidate costs
                +
actual output row count
actual wall-clock elapsed time
actual buffer hits / misses / evictions
                +
compiled VM bytecode
```

This is intentionally for teaching, not a stable benchmarking API.

## Durability modes

Rollback journal:

```python
Database("demo.db", journal_mode="rollback")
```

WAL:

```python
Database("demo.db", journal_mode="wal")
```

The SQL/Planner/VM/B+Tree stack is shared; only the Pager durability policy differs.

## Bounded cache and concurrency

```python
Database(
    "demo.db",
    journal_mode="wal",
    buffer_pages=32,
    replacement_policy="clock",  # or lru
    busy_timeout_ms=250,
)
```

v1.1 mirrors the process-local lock state machine into POSIX `flock`, so independent Python processes coordinate rollback readers/writers, WAL readers/single-writer, checkpoint, mode agreement, and busy timeout. v1.2 space management reuses those same locks for physical truncation. See `docs/CROSS_PROCESS_LOCKING.md`.

## CLI

```bash
mini-sqlite demo.db --buffer-pages 32 --replacement-policy clock
```

Inspection and maintenance commands:

```text
.schema
.indexes
.pages
.btree TABLE
.index INDEX
.explain SQL
.explain-analyze SQL
.bytecode SQL
.txn
.locks
.buffer
.frames
.wal
.checkpoint
.integrity
.reindex [INDEX]
.vacuum
.freelist
.incremental-vacuum [N]
```

## Validate

```bash
python -m pip install -e '.[dev]'
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

Optional illustrative microbenchmark:

```bash
python examples/benchmark.py
```

It compares only mini-sqlite plans with each other; it is not a benchmark against SQLite.

## Recommended reading order

Start with [`docs/LEARNING_PATH.md`](docs/LEARNING_PATH.md). For v1.3 ordered indexes read:

1. `docs/ORDERED_INDEXES.md`
2. `mini_sqlite/index/key_codec.py`
3. `mini_sqlite/index/btree.py`
4. `mini_sqlite/planner/indexing.py`
5. `tests/test_range_composite.py`
6. `examples/range_indexes.py`

For v1.2 space management read:

1. `docs/FREELIST.md`
2. `mini_sqlite/storage/freelist.py`
3. `mini_sqlite/storage/pager.py`
4. `tests/test_freelist.py`
5. `examples/freelist.py`

For v1.1 locking read:

1. `docs/CROSS_PROCESS_LOCKING.md`
2. `mini_sqlite/concurrency/file_lock.py`
3. `mini_sqlite/concurrency/lock.py`
4. `tests/test_cross_process_locking.py`
5. `examples/cross_process.py`

For lifecycle maintenance read `docs/MAINTENANCE.md`; for persistence/failure semantics see `docs/COMPATIBILITY.md` and `docs/FAULT_MATRIX.md`.

## Explicit non-goals

- SQLite binary file-format compatibility;
- SQL feature parity;
- Windows cross-process locking in v1.1;
- MVCC / multi-writer WAL;
- savepoints and nested transactions;
- production-calibrated optimizer costs;
- page-moving online VACUUM or background compaction;
- production security/performance guarantees.

The goal is a compact engine where the major database mechanisms are visible, testable, and connected.
