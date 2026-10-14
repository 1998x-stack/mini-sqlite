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

- Why can a highly duplicated indexed value cost more than a table scan?
- Why does the physical outer table of a JOIN not have to match SQL text order?

## Track C — concurrency

### v0.9: process-local locks

Read `docs/CONCURRENCY.md` and `examples/concurrency.py`.

Contrast rollback SHARED/RESERVED/EXCLUSIVE with WAL reader snapshot + single writer.

Question: why must a stale WAL reader fail when it tries to upgrade into a writer?

### v1.1: cross-process locks

Read `docs/CROSS_PROCESS_LOCKING.md`, `concurrency/file_lock.py`, and `tests/test_cross_process_locking.py`.

Question: why is a PENDING turnstile needed before a rollback writer can safely wait for EXCLUSIVE without starving?

## Track D — lifecycle and diagnostics (v1.0)

Read:

1. `docs/MAINTENANCE.md`
2. `mini_sqlite/maintenance/database.py`
3. `mini_sqlite/maintenance/integrity.py`
4. `tests/test_maintenance.py`
5. `examples/lifecycle.py`

Questions:

- Why is a missing secondary-index entry logical corruption even when every page decodes successfully?
- Why should REINDEX build a replacement tree instead of mutating the old one in place?
- Why does VACUUM use the engine's normal row/index APIs instead of copying raw page ids?
- Why does EXPLAIN ANALYZE report both an estimated plan and measured buffer deltas?

## Track E — failure semantics

Finish with:

1. `docs/COMPATIBILITY.md`
2. `docs/FAULT_MATRIX.md`
3. transaction/WAL fault tests
4. `Agents.md`
5. `Plan.md`

At this point you should be able to explain the full chain:

```text
SQL meaning
   ↓
logical/physical plan
   ↓
bytecode execution
   ↓
B+Tree/page access
   ↓
buffer residency
   ↓
transaction durability
   ↓
connection locking
   ↓
integrity / repair / compaction
```

and, equally importantly, identify which layer should **not** own each responsibility.


## Track F — page ownership and reuse (v1.2)

Read:

1. `docs/FREELIST.md`
2. `mini_sqlite/storage/freelist.py`
3. free-list portions of `mini_sqlite/storage/pager.py`
4. `Catalog.reindex()`
5. `Database.incremental_vacuum()`
6. `tests/test_freelist.py`
7. `examples/freelist.py`

Questions:

- Why is a valid free page different from an orphan?
- Why does allocation prefer the free-list before extending the file?
- Why can incremental vacuum truncate only a consecutive free suffix without moving pages?
- Why must rollback mode journal tail free pages before physically truncating them?
- Why does WAL mode commit a smaller logical page count before checkpoint performs physical truncation?


## Track G — ordered indexes (v1.3)

Read:

1. `docs/ORDERED_INDEXES.md`
2. `mini_sqlite/index/key_codec.py`
3. `mini_sqlite/index/btree.py`
4. `mini_sqlite/index/secondary.py`
5. `mini_sqlite/planner/indexing.py`
6. `tests/test_range_composite.py`
7. `examples/range_indexes.py`

Questions:

- Why can an index `(a,b)` efficiently answer `a=? AND b BETWEEN ...` but not `b=?` alone?
- Why are SQL inclusive bounds converted to half-open byte intervals?
- Why must an unbounded integer/text range skip the NULL tag?
- Why can a broad index range be more expensive than a table scan?
