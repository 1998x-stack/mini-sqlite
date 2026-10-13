# mini-sqlite

## v1.2 — Free-list Page Reuse + Incremental VACUUM

v1.2 adds explicit page ownership/deallocation. Successful REINDEX returns the old index tree to a persistent free-list, later allocations reuse those pages before extending the file, and incremental vacuum truncates only a consecutive free suffix. See `docs/FREELIST.md` and `examples/freelist.py`.

```text
owned page → free_page() → persistent free-list → allocate_page() reuse
                                             ↓
                                  free pages at file tail
                                             ↓
                                  incremental_vacuum()
```

A Python-first, SQLite-inspired educational database engine built as a sequence of architectural milestones. It is **not** a wrapper around Python `sqlite3`, and it is **not** SQLite file-format compatible.

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
v1.2  Free-list Page Reuse + Incremental VACUUM         ← current
```

## Quick start

```python
from mini_sqlite import Database

with Database("demo.db") as db:
    db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, age INTEGER, name TEXT);")
    db.execute("INSERT INTO users VALUES (1, 20, 'Alice');")
    db.execute("CREATE INDEX idx_users_age ON users(age);")
    db.execute("ANALYZE users;")
    print(db.execute("SELECT * FROM users WHERE age = 20;").rows)
    print(db.explain("SELECT * FROM users WHERE age = 20;"))
    print(db.explain_analyze("SELECT * FROM users WHERE age = 20;").render())
    print(db.integrity_check().render())
```

## Space lifecycle

`REINDEX` now frees the old index tree in the same transaction that publishes the new root. `Pager.allocate_page()` reuses the free-list head before extending the file. `Database.incremental_vacuum(N)` reclaims at most `N` consecutive free pages from the logical tail without moving live pages.

```python
db.reindex("idx_users_age")
print(db.freelist_text())
print(db.incremental_vacuum().render())
```

Integrity checking treats free-list pages as a first-class ownership class, so a page cannot simultaneously belong to a B+Tree and the free-list.

## Durability modes

Rollback journal and WAL share the same SQL/Planner/VM/B+Tree stack. Free-list mutations are ordinary transactional page mutations. Rollback mode journals disappearing tail pages before physical truncate; WAL mode publishes a smaller logical page count and checkpoint performs the physical truncate.

## Bounded cache and concurrency

```python
Database(
    "demo.db",
    journal_mode="wal",
    buffer_pages=32,
    replacement_policy="clock",
    busy_timeout_ms=250,
)
```

v1.1 POSIX file locking remains authoritative across processes. Incremental vacuum obtains rollback EXCLUSIVE or WAL checkpoint-level exclusion before physical shrink.

## CLI

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
python -m compileall -q mini_sqlite
```

## Recommended reading order

For v1.2:

1. `docs/FREELIST.md`
2. `docs/ON_DISK_FORMAT.md`
3. `mini_sqlite/storage/freelist.py`
4. `mini_sqlite/storage/pager.py`
5. `mini_sqlite/catalog/catalog.py`
6. `mini_sqlite/maintenance/database.py`
7. `tests/test_freelist.py`
8. `examples/freelist.py`

## Explicit non-goals

- SQLite binary file-format compatibility;
- SQL feature parity;
- Windows cross-process locking;
- MVCC / multi-writer WAL;
- savepoints and nested transactions;
- production-calibrated optimizer costs;
- moving live pages during incremental vacuum or background compaction;
- production security/performance guarantees.

The goal is a compact engine where the major database mechanisms are visible, testable, and connected.
