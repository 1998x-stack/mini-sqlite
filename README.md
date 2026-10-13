# mini-sqlite

A small SQLite-inspired database engine for learning how SQL becomes page-backed execution, transactions, indexes, relational operators, and joins.

`mini-sqlite` is **not** a wrapper around Python `sqlite3`. Table/index state is persisted in B+Trees managed by a Pager.

## Current version: v0.5 — JOIN

```text
SQL
 ↓
Parser / AST
 ↓
Planner
 ├─ single-table access: PK / secondary index / scan
 └─ JOIN inner access:   PK / secondary index / scan
 ↓
Compiler / VM
 ↓
outer source -> inner lookup/scan -> JOIN
                                 ↓
                       filter -> sort
                                 ↓
                     aggregate/project
                                 ↓
                            limit -> emit
 ↓
Table / Index B+Trees
 ↓
Pager
 ├─ rollback journal
 └─ database file
```

Version progression:

```text
v0.1  Page/Pager/B+Tree + SQL/Planner/VM
v0.2  Rollback Journal + Crash Recovery
v0.3  Secondary Index + Index Access Path
v0.4  Relational Execution + UPDATE
v0.5  INNER JOIN + Indexed Nested Loop          ← current
v0.6  WAL                                        ← next
```

## v0.5 capabilities

Retained from earlier versions:

- fixed 4096-byte pages;
- table/catalog and secondary-index B+Trees;
- leaf/internal/root splits;
- persistent schema/index catalog;
- rollback-journal transactions and hot-journal recovery;
- primary-key / secondary-index equality lookup / table scan;
- `CREATE TABLE`, `CREATE INDEX`, `INSERT`, `SELECT`, `DELETE`, `UPDATE`;
- comparison predicates, ORDER BY, LIMIT and scalar aggregates.

New in v0.5:

- `JOIN` / `INNER JOIN`;
- one INNER JOIN per SELECT;
- `AS` aliases and shorthand aliases;
- qualified columns such as `u.name`;
- ambiguous-column detection;
- plain nested-loop join;
- indexed nested-loop join through right-side PRIMARY KEY;
- indexed nested-loop join through right-side secondary index;
- JOIN output flowing through v0.4 filter/sort/aggregate/project/limit operators;
- self-join support when aliases disambiguate the two sources.

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
python -m compileall -q mini_sqlite
```

## JOIN example

```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    name TEXT
);

CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    user_id INTEGER,
    item TEXT
);

SELECT u.name, o.item
FROM users u
JOIN orders o ON u.id = o.user_id
ORDER BY o.id;
```

Without an index on `orders.user_id`, Planner shows:

```text
NESTED LOOP | INNER TABLE SCAN
```

Conceptually:

```text
for each users row:
    scan all orders rows
        compare u.id = o.user_id
```

After:

```sql
CREATE INDEX idx_orders_user ON orders(user_id);
```

the **same SQL** changes to:

```text
INDEXED NESTED LOOP
| INNER SECONDARY INDEX idx_orders_user ON o.user_id
```

The bytecode changes from:

```text
REWIND left
REWIND right
FILTER_JOIN_EQ
COLLECT_JOIN_ROW
NEXT right
NEXT left
```

to:

```text
OPEN_INDEX
REWIND outer
SEEK_INDEX_FROM_COLUMN
INDEX_TO_TABLE
COLLECT_JOIN_ROW
INDEX_NEXT
NEXT outer
```

This is the central v0.5 lesson: **an index does not change JOIN semantics; it changes how the inner row source is found.**

## Primary-key indexed nested loop

Reversing the written join order:

```sql
SELECT o.id, u.name
FROM orders o
JOIN users u ON o.user_id = u.id;
```

makes `users.id` the right-side join column. Since it is the INTEGER PRIMARY KEY, Planner selects:

```text
INDEXED NESTED LOOP | INNER PRIMARY KEY u.id
```

and bytecode uses:

```text
SEEK_PK_FROM_COLUMN
```

No secondary index is required.

## Name resolution

Qualified names are the clearest form:

```sql
SELECT u.id, o.id
FROM users u
JOIN orders o ON u.id = o.user_id;
```

Unqualified names are accepted only when unique across both sources:

```sql
SELECT name, item ...   -- valid if unique
SELECT id ...           -- error if both tables have id
```

Self-joins require aliases:

```sql
SELECT e.name, m.name
FROM people e
JOIN people m ON e.manager_id = m.id;
```

## JOIN composes with v0.4 operators

Matched rows are materialized as:

```text
(left row columns..., right row columns...)
```

Then existing relational stages apply unchanged:

```text
JOIN
 ↓
FILTER_ROWS
 ↓
SORT_ROWS
 ↓
AGGREGATE_ROWS or PROJECT_ROWS
 ↓
LIMIT_ROWS
 ↓
EMIT_ROWS
```

Example:

```sql
SELECT o.id, u.name, o.amount
FROM orders o
JOIN users u ON o.user_id = u.id
WHERE o.amount >= 10
ORDER BY o.amount DESC
LIMIT 2;
```

## Debug commands

```text
.schema
.indexes
.pages
.btree users
.index idx_orders_user
.txn
.explain SELECT u.name, o.item FROM users u JOIN orders o ON u.id=o.user_id;
.bytecode SELECT u.name, o.item FROM users u JOIN orders o ON u.id=o.user_id;
```

## Source map

```text
mini_sqlite/
├── database.py
├── sql/                  SQL tokens / AST / parser
├── planner/              binding + access/join path policy
├── vm/                   bytecode compiler + relational/join execution
├── catalog/              table/index metadata
├── btree/                INTEGER-key table/catalog tree
├── index/                byte-key secondary-index tree
├── storage/              Pager / journal / records / page-0 metadata
└── transaction/          connection transaction state
```

## Recommended reading order

For foundations:

1. `storage/record.py`
2. `btree/node.py`
3. `btree/btree.py`
4. `storage/pager.py`
5. `docs/TRANSACTIONS.md`
6. `docs/INDEXES.md`
7. `docs/RELATIONAL_ENGINE.md`

For v0.5:

8. `docs/JOINS.md`
9. `sql/ast.py`
10. `sql/parser.py`
11. `planner/plan.py`
12. `planner/planner.py`
13. `vm/compiler.py`
14. `vm/vm.py`
15. `tests/test_joins.py`

## Explicit v0.5 non-goals

- LEFT / RIGHT / FULL OUTER JOIN;
- multiple JOIN chains;
- arbitrary ON expression trees;
- hash join / merge join;
- join reordering and cost-based join selection;
- GROUP BY / HAVING;
- subqueries / CTEs;
- full SQL NULL semantics;
- range index scans;
- WAL / concurrent readers-writer protocol;
- SQLite binary compatibility.

See `Plan.md`. The next milestone is **v0.6: WAL**.
