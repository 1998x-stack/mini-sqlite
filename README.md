# mini-sqlite

A small SQLite-inspired database engine for learning how SQL becomes page-backed execution, transactions, indexes, relational operators, joins, and durable WAL commits.

`mini-sqlite` is **not** a wrapper around Python `sqlite3`. Table/index state is persisted in B+Trees managed by a Pager.

## Current version: v0.6 — WAL

```text
SQL -> Parser / AST -> Planner -> Compiler / VM
                                   ↓
                         relational pipeline / JOIN
                                   ↓
                         Table + Index B+Trees
                                   ↓
                                 Pager
              ┌────────────────────┴────────────────────┐
              ▼                                         ▼
        rollback mode                                WAL mode
  before-image journal -> DB           after-images -> overlay -> checkpoint -> DB
```

Version progression:

```text
v0.1  Page/Pager/B+Tree + SQL/Planner/VM
v0.2  Rollback Journal + Crash Recovery
v0.3  Secondary Index + Index Access Path
v0.4  Relational Execution + UPDATE
v0.5  INNER JOIN + Indexed Nested Loop
v0.6  WAL + Read Overlay + Checkpoint             ← current
v0.7  Bounded Buffer Manager                       ← next
```

## v0.6 capabilities

Everything from v0.1-v0.5 remains available, including persistent B+Trees, rollback transactions, secondary indexes, UPDATE, ORDER BY/LIMIT/aggregates, INNER JOIN, aliases, and indexed nested loops.

New in v0.6:

- explicit `journal_mode="rollback" | "wal"` database open option;
- WAL file with page after-image frames and transaction COMMIT records;
- CRC-checked frame payloads;
- committed WAL overlay on Pager reads;
- crash recovery by ignoring/truncating uncommitted or torn WAL tails;
- multiple committed transactions in one WAL;
- explicit checkpoint from WAL into the main database;
- crash-safe partial checkpoint while the WAL remains present;
- page creation/root-split persistence beyond main-file EOF;
- safe WAL -> rollback mode switching by checkpointing committed frames;
- `.wal` and `.checkpoint` inspection commands.

## Install and validate

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'

python -m pytest -q
python examples/quickstart.py
python examples/transactions.py
python examples/indexes.py
python examples/relational.py
python examples/joins.py
python examples/wal.py
python -m compileall -q mini_sqlite
```

## Rollback journal vs WAL

Rollback mode:

```text
old page image -> journal fsync -> overwrite main DB -> DB fsync -> delete journal
```

WAL mode:

```text
new page image(s) -> WAL FRAME records -> COMMIT record -> WAL fsync
```

The main DB can lag behind committed state until checkpoint.

## WAL example

```python
from mini_sqlite import Database

with Database("demo.db", journal_mode="wal") as db:
    db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, body TEXT);")
    db.execute("INSERT INTO items VALUES (1, 'hello');")
    print(db.execute("SELECT * FROM items;").rows)
    print(db.wal_status())
    print("checkpointed", db.checkpoint(), "page(s)")
```

Read path before checkpoint:

```text
get_page(N)
   ↓
cache?
   ↓ no
committed WAL frame for N?
   ├─ yes -> WAL bytes
   └─ no  -> database-file bytes
```

Everything above Pager is unaware of where those bytes came from.

## WAL file concept

```text
MSQLWAL1 header
FRAME tx=1 page=2 + 4096-byte image
FRAME tx=1 page=5 + 4096-byte image
COMMIT tx=1 logical_page_count=6 frame_count=2
FRAME tx=2 ...
COMMIT tx=2 ...
```

A FRAME sequence without a valid COMMIT record is not visible.

## Checkpoint

```text
newest committed WAL page versions
               ↓
         write main DB
               ↓
            fsync DB
               ↓
          reset WAL
```

The WAL remains until DB fsync succeeds, so a crash after copying only some pages is recoverable.

## CLI

```bash
mini-sqlite demo.db
mini-sqlite --journal-mode wal demo.db
```

Useful commands:

```text
.schema
.indexes
.pages
.btree TABLE
.index INDEX
.txn
.wal
.checkpoint
.explain SQL
.bytecode SQL
```

## Learning order

1. `docs/TRANSACTIONS.md`
2. `docs/WAL.md`
3. `mini_sqlite/storage/wal.py`
4. `mini_sqlite/storage/pager.py`
5. `tests/test_wal.py`
6. `examples/wal.py`

## Deliberate limits

v0.6 does **not** implement concurrent readers/writers, multi-writer WAL locks, SQLite `-shm`, snapshot isolation, automatic checkpoints, SQLite WAL binary format, cost-based optimization, or a bounded page cache.

See `Plan.md` for the roadmap.
