# mini-sqlite

A readable SQLite-inspired database engine that removes one layer of database “magic” per version. It is not a wrapper around Python `sqlite3`: tables, indexes, transactions, WAL, buffer residency, and optimizer statistics are implemented in this repository.

## Current version: v0.8 — Cost-Based Optimizer

```text
SQL
 ↓
Parser / AST
 ↓
Planner
 ├─ persistent ANALYZE statistics
 ├─ cardinality/selectivity estimator
 ├─ access-path candidates
 └─ JOIN-order candidates
 ↓
Cost Model
 ↓
chosen physical plan
 ↓
Compiler / VM
 ↓
relational pipeline / JOIN
 ↓
Table + Index B+Trees
 ↓
Pager
 ↓
Bounded Buffer Manager (LRU/CLOCK)
 ↓
Rollback Journal or WAL
 ↓
Disk
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
v0.8  Cost-Based Optimizer + ANALYZE            ← current
v0.9  Concurrency / Locking                     ← next
```

## What v0.8 adds

```sql
ANALYZE;
ANALYZE users;
```

The catalog stores a statistics snapshot containing row count plus per-column NULL count, distinct count, min/max, and top-16 most-common-value frequencies. Planner uses those statistics to compare correct physical alternatives rather than blindly preferring an available index.

### Index can lose to a scan

For 100 rows where `grp=1` occurs 90 times:

```text
TABLE SCAN                cost=100
SECONDARY INDEX idx_grp   cost=200
```

so `SELECT * FROM users WHERE grp = 1;` chooses a table scan. For a one-row value, the same query shape chooses the index because its estimated cost is about 4.2.

### JOIN order can differ from SQL order

```sql
SELECT big.id, small.id
FROM big
JOIN small ON big.k = small.k;
```

may explain as `PHYSICAL ORDER small -> big`. If `big(k)` is indexed, the chosen plan can use `small` as outer and probe the secondary index on `big`, while logical result column order remains `big, small`.

## Cost model

v0.8 intentionally uses transparent abstract units:

```text
TABLE_ROW_COST       = 1.0
PK_SEEK_COST         = 2.0
INDEX_SEEK_COST      = 2.0
INDEX_MATCH_COST     = 0.20
ROWID_LOOKUP_COST    = 2.0
```

These are teaching constants, not latency predictions.

## Statistics are snapshots

```text
ANALYZE -> stats saved -> writes may make stats stale -> ANALYZE again
```

Correctness never depends on statistics. Missing statistics fall back to the historical v0.7 rule planner.

## EXPLAIN

After ANALYZE:

```text
SELECT FROM users USING TABLE SCAN
| EST rows=90.00 cost=100.00
| CANDIDATES TABLE SCAN:cost=100.00;
  SECONDARY INDEX idx_users_grp:cost=200.00
| FILTER grp = 1
| PROJECT ...
```

JOIN EXPLAIN also shows physical order and both orientation costs.

## Python quick start

```python
from mini_sqlite import Database

with Database("demo.db", buffer_pages=32) as db:
    db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, grp INTEGER);")
    db.execute("CREATE INDEX idx_grp ON users(grp);")
    # load data ...
    db.execute("ANALYZE users;")
    print(db.catalog.get_table("users").stats)
    print(db.explain("SELECT * FROM users WHERE grp = 1;"))
```

## CLI

```bash
mini-sqlite demo.db
```

Useful commands include `.schema`, `.indexes`, `.pages`, `.btree TABLE`, `.index INDEX`, `.txn`, `.wal`, `.checkpoint`, `.buffer`, `.frames`, `.explain SQL`, and `.bytecode SQL`.

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
python -m compileall -q mini_sqlite
```

## Project map

```text
mini_sqlite/
├── catalog/
│   ├── catalog.py       # persisted schema + ANALYZE scan
│   ├── schema.py        # table/index metadata + optional stats
│   └── statistics.py    # v0.8 TableStats / ColumnStats
├── planner/
│   ├── optimizer.py     # cardinality + cost model + candidates
│   ├── cost_planner.py  # v0.8 cost-aware physical selection
│   ├── planner.py       # v0.7 binder / logical planning base
│   └── plan.py
├── vm/                  # legacy VM + thin v0.8 cost compiler/ANALYZE adapter
├── btree/               # primary table B+Tree
├── index/               # secondary B+Tree
└── storage/
    ├── buffer.py        # bounded v0.7 buffer pool
    ├── pager.py
    ├── journal.py
    └── wal.py
```

Read `docs/OPTIMIZER.md` for the v0.8 model and limitations.
