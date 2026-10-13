# mini-sqlite

A readable SQLite-inspired database engine built as a sequence of small architectural milestones. It is not a wrapper around Python `sqlite3` and it is not SQLite file-format compatible.

## Current milestone: v0.9 — Concurrency / Locking

```text
SQL -> Parser / AST
          ↓
   Cost-Based Planner
          ↓
   Compiler / Tiny VM
          ↓
 relational ops / JOIN
          ↓
 table + index B+Trees
          ↓
       Database connection
          ↓
       Lock Registry
          ↓
         Pager
          ↓
 Bounded Buffer Manager
    ├─ LRU
    └─ CLOCK
          ↓
 rollback journal OR WAL
          ↓
         disk
```

Version progression:

```text
v0.1  Page/Pager/B+Tree + SQL/Planner/VM
v0.2  Rollback Journal + Crash Recovery
v0.3  Secondary Index
v0.4  Relational Execution + UPDATE
v0.5  INNER JOIN + Indexed Nested Loop
v0.6  WAL + Read Overlay + Checkpoint
v0.7  Bounded Buffer Manager + LRU/CLOCK
v0.8  ANALYZE + Cost-Based Optimizer
v0.9  Multi-Connection Concurrency + Locks        <- current
v1.0  Educationally Complete                     <- next
```

## What v0.9 adds

Multiple live connections can now coordinate against one database path:

```python
from mini_sqlite import Database

reader = Database("demo.db")
writer = Database("demo.db", busy_timeout_ms=250)
```

### Rollback mode

```text
reader A: SHARED
reader B: SHARED
writer C: RESERVED -> waits for readers -> EXCLUSIVE
```

Rollback mode writers need EXCLUSIVE because uncommitted dirty pages may reach the main database before COMMIT and must remain invisible to other readers.

Read-only explicit transactions use a **lazy rollback journal**: `BEGIN` alone creates no `<db>-journal`; the sidecar is created only on first physical write.

### WAL mode

```text
reader A: SHARED snapshot S1
writer B: WAL_WRITE -> COMMIT S2
reader A: still sees S1
new statement: sees S2
```

Readers coexist with one WAL writer. If an old WAL reader tries to upgrade into a writer after somebody else committed, mini-sqlite raises `BusySnapshotError` rather than writing from stale state.

### Busy handling

```python
Database("demo.db", busy_timeout_ms=500)
```

`0` fails immediately. Positive values wait on a condition variable until a conflicting connection releases its lock or the timeout expires.

### Lock inspection

`Database.lock_status()` and CLI `.locks` expose the current connection and global path state.

## v0.8 optimizer remains intact

`ANALYZE` statistics still drive scan/index and JOIN-order cost choices. Locking sits below planning: concurrency changes when a connection may execute and which snapshot it sees, not SQL semantics or cost formulas.

## CLI

```bash
mini-sqlite demo.db --busy-timeout-ms 250
```

Useful commands include `.schema`, `.indexes`, `.pages`, `.btree`, `.index`, `.explain`, `.bytecode`, `.txn`, `.locks`, `.buffer`, `.frames`, `.wal`, and `.checkpoint`.

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
python -m compileall -q mini_sqlite
```

## Key v0.9 files

```text
mini_sqlite/concurrency/lock.py
mini_sqlite/database.py
mini_sqlite/storage/pager.py
mini_sqlite/storage/wal.py
mini_sqlite/errors.py
tests/test_concurrency.py
examples/concurrency.py
docs/CONCURRENCY.md
```

## Important limit

v0.9 concurrency is **process-local**. Two `Database` objects in one Python process coordinate correctly; this release does not claim cross-process operating-system locking.
