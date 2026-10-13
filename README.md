# mini-sqlite

A small SQLite-inspired database engine for learning how SQL becomes page-backed execution, indexing, transactions, and relational row processing.

`mini-sqlite` is **not** a wrapper around Python `sqlite3`. Persisted table/index state lives in B+Trees managed by a Pager.

## Current version: v0.4 — Relational Execution Engine

```text
SQL
 ↓
Parser / AST
 ↓
Planner
 ├─ PRIMARY_KEY
 ├─ SECONDARY_INDEX
 └─ TABLE_SCAN
 ↓
Compiler / VM
 ↓
source -> filter -> collect -> sort -> aggregate/project -> limit -> emit
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
v0.4  Relational Execution + UPDATE               ← current
v0.5  JOIN                                         ← next
```

## v0.4 capabilities

Retained from earlier versions:

- fixed 4096-byte pages;
- table/catalog and secondary-index B+Trees;
- leaf/internal/root splits;
- persistent schema/index catalog;
- rollback-journal transactions and hot-journal recovery;
- primary-key lookup / secondary-index equality lookup / table scan;
- `CREATE TABLE`, `CREATE INDEX`, `INSERT`, `SELECT`, `DELETE`.

New in v0.4:

- `UPDATE`;
- `= != < <= > >=` predicates;
- `ORDER BY ... ASC/DESC`;
- `LIMIT`;
- `COUNT(*)`, `COUNT(column)`, `SUM`, `MIN`, `MAX`;
- explicit VM relational stages;
- UPDATE maintenance of every secondary index in one transaction.

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
python -m compileall -q mini_sqlite
```

## Relational example

```sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    name TEXT,
    age INTEGER
);

CREATE INDEX idx_users_age ON users(age);

SELECT name
FROM users
WHERE age >= 20
ORDER BY age DESC
LIMIT 3;
```

Planner output is intentionally explainable:

```text
SELECT FROM users USING TABLE SCAN
| FILTER age >= 20
| SORT age DESC
| PROJECT name
| LIMIT 3
```

Why a table scan despite `idx_users_age`? v0.3's index cursor supports equality lookup only. v0.4 refuses to disguise a range scan as an index capability it does not yet have.

For equality:

```sql
SELECT name FROM users WHERE age = 35;
```

the plan still uses:

```text
SECONDARY INDEX idx_users_age ON age -> ROWID LOOKUP
```

## Bytecode exposes the relational pipeline

For a scan/sort/project/limit query, `.bytecode` contains stages like:

```text
OPEN_READ
REWIND
FILTER_COMPARE
COLLECT_ROW
NEXT
SORT_ROWS
PROJECT_ROWS
LIMIT_ROWS
EMIT_ROWS
HALT
```

For aggregates:

```sql
SELECT COUNT(*), SUM(age), MIN(age), MAX(age) FROM users;
```

`AGGREGATE_ROWS` replaces ordinary projection.

This is the v0.4 core idea: query processing is a composition of explicit mechanisms rather than a growing collection of statement-specific branches.

## UPDATE and indexes

```sql
UPDATE users SET age = 36 WHERE age = 35;
```

If `age` has an index, the old index can find matching rowids. Each matching row is changed as one transactional unit:

```text
remove old index entries
        ↓
replace table record
        ↓
insert new index entries
        ↓
commit through v0.2 rollback journal
```

A crash cannot durably leave the table updated while its index still points at the old value.

The INTEGER PRIMARY KEY cannot be changed in v0.4; that is an explicit version boundary.

## Aggregate semantics

Supported without GROUP BY:

```text
COUNT(*)
COUNT(column)
SUM(integer_column)
MIN(column)
MAX(column)
```

`COUNT(column)` ignores NULL. `SUM/MIN/MAX` ignore NULL and return NULL when no non-NULL input exists. Full SQL three-valued NULL logic is not implemented yet.

## Debug commands

```text
.schema
.indexes
.pages
.btree users
.index idx_users_age
.txn
.explain SELECT name FROM users WHERE age >= 20 ORDER BY age DESC LIMIT 3;
.bytecode SELECT name FROM users WHERE age >= 20 ORDER BY age DESC LIMIT 3;
```

## Source map

```text
mini_sqlite/
├── database.py
├── sql/                  SQL tokens / AST / parser
├── planner/              access path + relational plan metadata
├── vm/                   bytecode compiler + relational execution
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

For v0.4:

7. `docs/RELATIONAL_ENGINE.md`
8. `sql/ast.py`
9. `sql/parser.py`
10. `planner/plan.py`
11. `planner/planner.py`
12. `vm/compiler.py`
13. `vm/vm.py`
14. `tests/test_relational.py`

## Explicit v0.4 non-goals

- JOIN;
- GROUP BY / HAVING;
- aliases / qualified columns;
- AND / OR expression trees;
- complete SQL NULL semantics;
- arithmetic expressions in UPDATE;
- INTEGER PRIMARY KEY UPDATE;
- streaming LIMIT / external sort;
- range index scans;
- statistics / cost-based optimization;
- WAL / concurrent connections;
- SQLite binary compatibility.

See `Plan.md`. The next milestone is **v0.5: JOIN**.
