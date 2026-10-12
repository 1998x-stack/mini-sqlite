# mini-sqlite

A small SQLite-inspired database engine for learning how a SQL database works from SQL text down to page bytes, indexes, and crash recovery.

`mini-sqlite` is **not** a wrapper around Python `sqlite3`. Persisted table/index state lives in page-backed B+Trees.

## Current version: v0.3 — secondary indexes + richer planner

```text
SQL text
   ↓
Tokenizer / Parser
   ↓
AST
   ↓
Rule-based Planner
   ├─ PRIMARY_KEY
   ├─ SECONDARY_INDEX
   └─ TABLE_SCAN
   ↓
Tiny bytecode Compiler
   ↓
Virtual Machine
   ├─────────────┐
   ▼             ▼
Table Cursor   Index Cursor
   │             │
   ▼             ▼
int-key B+Tree  byte-key B+Tree
   └──────┬──────┘
          ▼
        Pager
   ┌──────┴──────┐
   ▼             ▼
rollback journal database file
```

v0.1 established pages/B+Tree/SQL/VM. v0.2 added rollback-journal transactions and hot-journal recovery. v0.3 answers:

> Why can a secondary index turn a filter into logarithmic navigation, why does it still need a rowid lookup back into the table, and how do table + index stay transactionally consistent?

## v0.3 capabilities

Foundation retained from v0.1/v0.2:

- 4096-byte pages and page cache;
- slotted table/catalog B+Tree pages;
- leaf/internal/root splits;
- persistent catalog;
- typed row codec (`NULL`, `INTEGER`, `TEXT`);
- SQL tokenizer/parser/AST;
- planner → bytecode compiler → VM;
- `CREATE TABLE`, `INSERT`, `SELECT`, `DELETE`;
- explicit/autocommit transactions;
- before-image rollback journal;
- hot-journal crash recovery.

New in v0.3:

- `CREATE INDEX idx ON table(column)`;
- persistent index metadata;
- variable-length byte-key B+Tree pages;
- `(indexed_value, rowid)` composite physical keys;
- duplicate secondary-key support;
- INTEGER/TEXT/NULL index key encoding;
- build index over pre-existing rows;
- planner choice among primary-key seek, secondary-index seek, and table scan;
- explicit index-to-table rowid lookup in VM bytecode;
- INSERT/DELETE maintenance of every index in the same transaction;
- index root split persistence;
- rollback/crash recovery covering table + indexes atomically;
- `.indexes` / `.index INDEX` inspection.

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
python examples/indexes.py
python -m compileall -q mini_sqlite
```

## Quick index session

```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    name TEXT,
    age INTEGER
);

INSERT INTO users VALUES (1, 'Alice', 20);
INSERT INTO users VALUES (2, 'Bob', 25);
INSERT INTO users VALUES (3, 'Carol', 20);
```

Before an index:

```text
mini-sqlite> .explain SELECT name FROM users WHERE age = 20;
SELECT FROM users USING TABLE SCAN
```

Create the index:

```sql
CREATE INDEX idx_users_age ON users(age);
```

Now:

```text
mini-sqlite> .explain SELECT name FROM users WHERE age = 20;
SELECT FROM users USING SECONDARY INDEX idx_users_age ON age -> ROWID LOOKUP
```

The query still returns table rows:

```text
Alice
Carol
```

because the index yields rowids, then the VM seeks the table B+Tree.

## Bytecode makes the back-to-table lookup visible

```text
ADDR OPCODE             P1   P2   P3 P4
---- ---------------- ---- ---- ---- ------------------------------------------
   0 OPEN_READ           0    0    0 'users'
   1 OPEN_INDEX          1    0    0 'idx_users_age'
   2 SEEK_INDEX_EQ       1    7    0 20
   3 INDEX_TO_TABLE      1    0    0
   4 PROJECT             0    0    0 [1]
   5 RESULT_ROW          0    0    0
   6 INDEX_NEXT          1    3    0
   7 HALT                0    0    0
```

This is the v0.3 mental model in executable form:

```text
index seek → rowid → table seek → row
```

## Why duplicate index values work

For:

```text
(1, Alice, 20)
(3, Carol, 20)
```

the secondary tree does not try to store two identical physical keys `20`. It stores:

```text
(20, 1)
(20, 3)
```

`KeyCodec` encodes the indexed value as a byte prefix and appends an ordered rowid. Equality lookup seeks the shared prefix and walks only that duplicate run.

## Transactional index maintenance

An indexed INSERT is logically:

```text
insert table row
      ↓
insert idx_users_age entry
      ↓
insert any other index entries
      ↓
COMMIT one Pager transaction
```

A failure or crash does not leave “table changed but index stale”. Existing v0.2 rollback-journal rules restore all participating pages together.

## Debug commands

```text
.schema
.indexes
.pages
.btree users
.index idx_users_age
.txn
.explain SELECT * FROM users WHERE age = 20;
.bytecode SELECT * FROM users WHERE age = 20;
```

`.pages` distinguishes table and index pages:

```text
LEAF / INTERNAL
IDX_LEAF / IDX_INTERNAL
```

## Source map

```text
mini_sqlite/
├── database.py
├── sql/                 SQL → AST
├── planner/             AST → access path / logical plan
├── vm/                  Plan → bytecode → execution
├── catalog/             table + index metadata
├── btree/               INTEGER-key table/catalog B+Tree
├── index/
│   ├── key_codec.py     SQL values → ordered byte prefixes
│   ├── node.py          variable-key slotted index pages
│   ├── btree.py         byte-key B+Tree
│   ├── secondary.py     row/index mapping
│   └── cursor.py        equality lookup → rowids
├── storage/
│   ├── pager.py
│   ├── journal.py
│   ├── record.py
│   └── meta.py
└── transaction/
```

## Recommended reading order

For fundamentals:

1. `storage/record.py`
2. `btree/node.py`
3. `btree/btree.py`
4. `storage/pager.py`
5. `docs/TRANSACTIONS.md`

For v0.3:

6. `docs/INDEXES.md`
7. `index/key_codec.py`
8. `index/node.py`
9. `index/btree.py`
10. `index/secondary.py`
11. `catalog/schema.py`
12. `planner/planner.py`
13. `vm/compiler.py`
14. `vm/vm.py`
15. `tests/test_indexes.py`

## v0.3 explicit non-goals

- UNIQUE indexes;
- multi-column / expression / partial indexes;
- range predicates and range index scans;
- covering/index-only scans;
- collation configuration;
- statistics/selectivity/cost model;
- `UPDATE`, `ORDER BY`, aggregates, `LIMIT`;
- JOIN;
- WAL;
- concurrent connections / locking;
- SQLite file-format compatibility.

See `Plan.md`. The next milestone is **v0.4: Relational Execution Engine**.
