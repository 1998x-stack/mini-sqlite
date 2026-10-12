# mini-sqlite

A small SQLite-inspired database engine for learning how a SQL database works end to end.

`mini-sqlite` is intentionally **not** a wrapper around Python `sqlite3`, and it does not store rows in a Python dictionary. A query travels through a real educational pipeline:

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
   ↓
mini.db
```

The goal of v0.1 is to make the most important SQLite ideas visible with a codebase small enough to read.

## What v0.1 implements

- fixed-size 4096-byte database pages
- page cache + dirty-page flushing
- slotted B+Tree page format
- leaf and internal B+Tree nodes
- leaf splits, internal splits, root splits
- persistent schema catalog
- compact typed row codec (`NULL`, `INTEGER`, `TEXT`)
- SQL tokenizer and parser
- explicit AST and logical plans
- primary-key seek vs full-table-scan planning
- VDBE-inspired bytecode compiler and interpreter
- `CREATE TABLE`
- `INSERT INTO ... VALUES (...)`
- `SELECT ... FROM ... [WHERE column = literal]`
- `DELETE FROM ... [WHERE column = literal]`
- shell debugging commands for schema, pages, B+Tree, plans, and bytecode
- statement-level fsync/autocommit durability

## Deliberate v0.1 limitations

The project keeps the first version narrow on purpose:

- exactly one `INTEGER PRIMARY KEY` per table
- no secondary indexes
- no `UPDATE`, `JOIN`, `ORDER BY`, aggregates, or subqueries
- no rollback journal / crash-atomic multi-page transactions yet
- no WAL or concurrent writers
- delete does not merge/rebalance under-full B+Tree pages
- no SQLite file-format compatibility
- planner is rule-based, not cost-based

These are version boundaries, not architectural dead ends. See `PLAN.md`.

## Install

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
```

Run tests:

```bash
pytest
```

Start the shell:

```bash
mini-sqlite demo.db
```

## Quick session

```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    name TEXT,
    age INTEGER
);

INSERT INTO users VALUES (1, 'Alice', 20);
INSERT INTO users VALUES (2, 'Bob', 25);
INSERT INTO users VALUES (3, 'Carol', 20);

SELECT * FROM users;
SELECT name FROM users WHERE age = 20;
SELECT * FROM users WHERE id = 2;
DELETE FROM users WHERE id = 1;
```

## Debug commands

The shell exposes internal structures because the project is meant to be studied.

```text
.schema
.pages
.btree users
.explain SELECT * FROM users WHERE id = 2;
.bytecode SELECT * FROM users WHERE id = 2;
```

Example plan:

```text
SELECT FROM users USING PRIMARY-KEY LOOKUP
```

Example bytecode:

```text
ADDR OPCODE             P1   P2   P3 P4
---- ---------------- ---- ---- ---- ------------------------------------------
   0 OPEN_READ           0    0    0 'users'
   1 SEEK_PK             0    4    0 2
   2 PROJECT             0    0    0 [0, 1, 2]
   3 RESULT_ROW          0    0    0
   4 HALT                0    0    0
```

## The physical file

A database is a sequence of fixed-size pages:

```text
mini.db

page 0   database metadata
page 1   initial catalog B+Tree root
page 2   first user-table root
page 3   another table / split page / ...
...
```

Each B+Tree page is a slotted page:

```text
0                                                        4095
┌───────────────────────────────────────────────────────────┐
│ 32-byte node header                                       │
├───────────────────────────────────────────────────────────┤
│ u16 cell pointer 0                                        │
│ u16 cell pointer 1                                        │
│ ...                                                       │
├───────────────────────────────────────────────────────────┤
│                                                           │
│                     free space                            │
│                                                           │
├───────────────────────────────────────────────────────────┤
│                                      cell payload N       │
│                                  cell payload 1           │
│                              cell payload 0               │
└───────────────────────────────────────────────────────────┘
```

The pointer array grows forward and cell payloads grow backward. That is the key reason variable-length rows can live efficiently in fixed-size pages.

## B+Tree representation

### Leaf page

```text
[key=1, encoded row]
[key=2, encoded row]
[key=3, encoded row]
right_sibling -> next leaf
```

### Internal page

```text
first_child
separator key 100 -> right_child
separator key 200 -> right_child
...
```

Search follows separator keys down to a leaf. Full scans walk the left-most leaf and then follow right-sibling pointers.

## Why the catalog is also a B+Tree

The database must persist facts such as:

- table name
- table id
- column definitions
- root page of each table B+Tree

`mini-sqlite` stores these schema records in a dedicated catalog B+Tree. Page 0 stores only small global metadata, including the catalog root page.

When a table root splits, the table's catalog entry is rewritten with the new root page. This is important: a B+Tree root is not a permanent page id.

## Query execution example

For:

```sql
SELECT name FROM users WHERE id = 42;
```

the system performs:

```text
"SELECT name ..."
      ↓
Tokenizer
      ↓
SelectStmt(table='users', columns=['name'], where=id=42)
      ↓
Planner
      ↓
PRIMARY_KEY access path
      ↓
Compiler
      ↓
OPEN_READ / SEEK_PK / PROJECT / RESULT_ROW / HALT
      ↓
VM
      ↓
BTree.search(42)
      ↓
internal-page routing
      ↓
leaf binary search
      ↓
RecordCodec.decode(...)
      ↓
('Alice',)
```

For:

```sql
SELECT name FROM users WHERE age = 20;
```

there is no secondary index in v0.1, so the planner emits a table scan:

```text
OPEN_READ
REWIND
FILTER_EQ
PROJECT
RESULT_ROW
NEXT → loop
HALT
```

That contrast is the foundation for adding indexes in v0.3.

## Source map

```text
mini_sqlite/
├── database.py            public facade / execution pipeline
├── sql/
│   ├── tokenizer.py       SQL text -> tokens
│   ├── parser.py          tokens -> AST
│   └── ast.py
├── planner/
│   ├── planner.py         choose access path
│   └── plan.py
├── vm/
│   ├── compiler.py        plan -> bytecode
│   ├── opcode.py
│   ├── instruction.py
│   └── vm.py              bytecode interpreter
├── catalog/
│   ├── schema.py
│   └── catalog.py         schema stored in a B+Tree
├── btree/
│   ├── node.py            physical B+Tree page format
│   ├── btree.py           search/insert/delete/split
│   └── cursor.py
└── storage/
    ├── pager.py           page cache + file I/O
    ├── meta.py            page-0 database header
    └── record.py          typed row serialization
```

## Recommended reading order

Do **not** begin with the SQL parser. Read from storage upward:

1. `storage/record.py`
2. `storage/pager.py`
3. `btree/node.py`
4. `btree/btree.py`
5. `catalog/catalog.py`
6. `vm/vm.py`
7. `vm/compiler.py`
8. `planner/planner.py`
9. `sql/tokenizer.py`
10. `sql/parser.py`
11. `database.py`

This order answers the central database question first: **how do bytes become durable rows, and how are those rows found?**

## Design rules

The project follows a few constraints to stay educational and extensible:

1. **No hidden Python collection as the database.** Persistent table state lives in pages.
2. **Layer boundaries matter.** Parser does not call B+Tree; planner does not read disk.
3. **Physical and logical data structures are separate.** Rows use `RecordCodec`; B+Tree stores opaque bytes.
4. **Root movement is explicit.** Split operations can change root page ids.
5. **Debuggability is a feature.** Internal page, plan, and bytecode views are public teaching tools.
6. **Version growth happens by adding mechanisms, not replacing the architecture.**

## Safety / correctness note

v0.1 fsyncs completed statements, but it does **not** yet provide crash-atomic rollback across a multi-page write. If power is lost in the middle of a page-splitting mutation, the file can be inconsistent. v0.2 introduces a rollback journal and transaction state machine specifically to solve that problem.

This repository is educational and should not be used as a production database.
