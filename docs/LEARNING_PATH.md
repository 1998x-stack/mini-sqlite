# mini-sqlite Learning Path

The repository is intended to be read as a sequence of mechanisms. Avoid starting from `database.py` and trying to understand everything at once.

## Track A — storage first

### v0.1: pages and B+Trees

Read:

1. `mini_sqlite/storage/record.py`
2. `mini_sqlite/storage/pager.py`
3. `mini_sqlite/btree/node.py`
4. `mini_sqlite/btree/btree.py`
5. `docs/ON_DISK_FORMAT.md`

Questions:

- Why is a B+Tree better than a Python BST for page storage?
- Why are leaf cells stored behind a pointer array?
- Why must root page changes be persisted outside the tree object?

### v0.2: transaction durability

Read `docs/TRANSACTIONS.md` and `storage/journal.py`.

Question: why must the before-image journal reach durable storage before a dirty database page?

### v0.6: WAL

Read `docs/WAL.md` and compare the write order with v0.2.

Question: how can a committed value exist in WAL while the main database file still contains an older page?

### v0.7: buffer manager

Read `docs/BUFFER_MANAGER.md`.

Question: why is replacement policy separate from whether a dirty frame may be evicted safely?

## Track B — SQL execution

### v0.1/v0.4: parser → plan → VM

Read:

1. `sql/tokenizer.py`
2. `sql/parser.py`
3. `planner/planner.py`
4. `vm/compiler.py`
5. `vm/vm.py`
6. `docs/RELATIONAL_ENGINE.md`

Question: why does the parser not call B+Tree search directly?

### v0.3: secondary indexes

Read `docs/INDEXES.md`.

Question: why does `(indexed_value, rowid)` make duplicate SQL values possible while keeping physical index keys unique?

### v0.5: JOIN

Read `docs/JOINS.md`.

Question: how does an index on the inner join key change nested-loop cost?

### v0.8: cost-based planning

Read `docs/OPTIMIZER.md` and `examples/optimizer.py`.

Questions:

- Why can a low-selectivity index be slower than a table scan?
- Why can physical join order differ from SQL source order?

## Track C — connections and lifecycle

### v0.9: concurrency

Read `docs/CONCURRENCY.md`.

Compare:

```text
rollback: readers block EXCLUSIVE writer
WAL:      readers coexist with one writer snapshot
```

Question: why must an old WAL reader fail a stale read→write upgrade?

### v1.0: integrity and maintenance

Read `docs/MAINTENANCE.md`, then `maintenance/integrity.py` and `examples/lifecycle.py`.

Questions:

- Which structures are primary data and which are derived data?
- Why can REINDEX repair an index without rewriting the table?
- Why does VACUUM rebuild rather than simply delete arbitrary pages from the middle of the file?
- Why is stale ANALYZE information a warning, not corruption?

## One end-to-end tracing exercise

For a query such as:

```sql
SELECT u.name, o.amount
FROM users u
JOIN orders o ON u.id = o.user_id
WHERE o.amount >= 100
ORDER BY o.amount DESC
LIMIT 5;
```

Trace in this order:

```text
Parser AST
  ↓
Planner EXPLAIN + candidate costs
  ↓
Compiler bytecode
  ↓
VM opcodes
  ↓
Table/Index cursors
  ↓
B+Tree page reads
  ↓
Buffer hit/miss/eviction
  ↓
WAL or main-file source
  ↓
connection lock / snapshot
```

Then run `.integrity` to see how the same physical structures are checked after execution.
