# mini-sqlite

A small SQLite-inspired database engine for learning how a SQL database works from SQL text down to bytes on disk.

`mini-sqlite` is **not** a wrapper around Python `sqlite3`, and persisted rows are not stored in Python dictionaries. The current v0.2 pipeline is:

```text
SQL text
   ↓
Tokenizer / Parser
   ↓
AST
   ↓
Rule-based Planner
   ↓
Tiny bytecode Compiler
   ↓
Virtual Machine
   ↓
B+Tree Cursor
   ↓
Persistent B+Tree
   ↓
Pager / 4 KiB pages
   ├──────────────→ database file
   └──────────────→ rollback journal (during writes)
```

## Current version: v0.2 — transactions + crash recovery

v0.1 established the page/B+Tree/SQL/VM vertical slice. v0.2 adds rollback-journal durability **under the B+Tree**, preserving the architecture while answering a new question:

> What prevents a database from being left half-written when a process crashes?

### v0.1 foundation

- fixed 4096-byte database pages;
- page cache + dirty-page flushing;
- slotted B+Tree leaf/internal pages;
- leaf, internal, and root splits;
- persistent catalog;
- typed row codec (`NULL`, `INTEGER`, `TEXT`);
- SQL tokenizer/parser/AST;
- planner with primary-key seek vs table scan;
- VDBE-inspired bytecode compiler/interpreter;
- `CREATE TABLE`, `INSERT`, `SELECT`, `DELETE`;
- `.schema`, `.pages`, `.btree`, `.explain`, `.bytecode`.

### v0.2 additions

- `BEGIN [TRANSACTION]`;
- `COMMIT` / `END [TRANSACTION]`;
- `ROLLBACK [TRANSACTION]`;
- write-statement autocommit;
- connection transaction state machine;
- physical before-image rollback journal;
- first-write page journaling;
- original database page-count tracking;
- CRC32 validation for complete journal entries;
- journal-fsync → DB-write/fsync → journal-delete commit ordering;
- startup hot-journal recovery;
- rollback of transaction-created B+Tree pages by truncation;
- catalog/meta rollback;
- Python `with db.transaction():` API;
- `.txn` shell inspection.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

## Validate

```bash
python -m pytest -q
python examples/quickstart.py
python examples/transactions.py
python -m compileall -q mini_sqlite
```

## Quick session

```text
$ mini-sqlite demo.db
mini-sqlite> CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, age INTEGER);
mini-sqlite> INSERT INTO users VALUES (1, 'Alice', 20);
mini-sqlite> BEGIN;
mini-sqlite> INSERT INTO users VALUES (2, 'Bob', 25);
mini-sqlite> .txn
mini-sqlite> ROLLBACK;
mini-sqlite> SELECT * FROM users;
1 | Alice | 20
```

## Transaction mental model

When an existing page is modified for the first time in a transaction:

```text
old page image
      ↓
append to demo.db-journal
      ↓
modify cached database page
```

Commit ordering:

```text
1. fsync rollback journal
2. write dirty database pages
3. fsync database file
4. delete rollback journal   ← commit point
```

If the process dies before journal deletion, startup sees the hot journal, restores old page images, truncates pages created by the transaction, fsyncs the repaired database, then removes the journal.

## Why this is architecture-first

The B+Tree API remains logical:

```python
search(key)
insert(key, value)
delete(key)
scan()
```

It does not know whether durability is implemented with a rollback journal today or WAL in a later version. Pager owns durability protocol. This separation is the point of v0.2.

## Planner example

```sql
SELECT * FROM users WHERE id = 2;
```

uses a primary-key B+Tree seek, while:

```sql
SELECT * FROM users WHERE age = 20;
```

currently performs a table scan. That visible gap motivates v0.3 secondary indexes.

## Debug commands

```text
.schema
.pages
.btree users
.explain SELECT * FROM users WHERE id = 2;
.bytecode SELECT * FROM users WHERE id = 2;
.txn
```

The project intentionally exposes internals because it is meant to be read and inspected.

## Repository learning order

For v0.1 fundamentals:

1. `mini_sqlite/storage/record.py`
2. `mini_sqlite/storage/pager.py`
3. `mini_sqlite/btree/node.py`
4. `mini_sqlite/btree/btree.py`
5. `mini_sqlite/catalog/`
6. `mini_sqlite/sql/`
7. `mini_sqlite/planner/`
8. `mini_sqlite/vm/`

Then for v0.2:

9. `docs/TRANSACTIONS.md`
10. `mini_sqlite/storage/journal.py`
11. `mini_sqlite/transaction/manager.py`
12. `tests/test_transactions.py`

## v0.2 explicit non-goals

- nested transactions and savepoints;
- concurrent readers/writers;
- file locking;
- WAL;
- secondary indexes;
- joins/aggregates/`ORDER BY`;
- SQLite binary/journal compatibility;
- production-grade durability claims across every filesystem/hardware failure model.

See `Plan.md` for the architecture-driven roadmap. The next milestone is **v0.3: Secondary Indexes + Richer Planner**.
