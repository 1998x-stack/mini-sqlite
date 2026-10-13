# mini-sqlite

A small SQLite-inspired database engine for learning how SQL becomes page-backed execution, transactions, indexes, joins, WAL commits, and finally a bounded database buffer pool.

`mini-sqlite` is **not** a wrapper around Python `sqlite3`. Table/index state is persisted in B+Trees managed by Pager.

## Current version: v0.7 — Bounded Buffer Manager

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
relational pipeline / JOIN
 ↓
Table + Index B+Trees
 ↓
Pager
 ↓
Bounded Buffer Manager
 ├─ pin / unpin
 ├─ LRU / CLOCK
 └─ hit / miss / eviction metrics
 ↓
Durability
 ├─ rollback journal -> database file
 └─ WAL overlay -> checkpoint -> database file
```

Version progression:

```text
v0.1  Page/Pager/B+Tree + SQL/Planner/VM
v0.2  Rollback Journal + Crash Recovery
v0.3  Secondary Index + Index Access Path
v0.4  Relational Execution + UPDATE
v0.5  INNER JOIN + Indexed Nested Loop
v0.6  WAL + Read Overlay + Checkpoint
v0.7  Bounded Buffer Manager + LRU/CLOCK        ← current
v0.8  Cost-Based Optimizer                      ← next
```

## v0.7 capabilities

Everything from v0.1-v0.6 remains available, including:

- fixed 4096-byte pages;
- table/catalog and secondary-index B+Trees;
- rollback-journal transactions and hot-journal recovery;
- WAL after-images, read overlay, crash recovery, and checkpoint;
- `CREATE TABLE`, `CREATE INDEX`, `INSERT`, `SELECT`, `DELETE`, `UPDATE`;
- predicates, `ORDER BY`, `LIMIT`, scalar aggregates;
- INNER JOIN, aliases, self-joins, nested loop and indexed nested loop.

New in v0.7:

- fixed buffer capacity via `buffer_pages=N`;
- explicit `BufferFrame` / `BufferManager` subsystem;
- page pin/unpin lifetime;
- LRU replacement;
- CLOCK second-chance replacement;
- durability-aware dirty eviction;
- cache hits, misses, hit rate, evictions, dirty evictions;
- `.buffer` and `.frames` inspection;
- tests that force B+Tree/index/JOIN execution through a 3-page buffer.

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
python examples/buffer_pool.py
python -m compileall -q mini_sqlite
```

## Open with a bounded buffer

```python
from mini_sqlite import Database

with Database(
    "demo.db",
    buffer_pages=32,
    replacement_policy="clock",  # or "lru"
) as db:
    db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, body TEXT);")
    db.execute("INSERT INTO items VALUES (1, 'hello');")
    print(db.execute("SELECT * FROM items;").rows)
    print(db.buffer_status())
```

The key invariant is:

```text
resident pages <= buffer_pages
```

A miss at capacity must choose an evictable victim before loading the new page.

## Pin / unpin

Pager exposes an explicit lifetime for code that must keep a frame stable while using its bytes:

```python
with pager.pin_page(page_id) as page:
    node = BTreeNode.decode(page_id, page)
```

Pinned pages are never eviction candidates.

Use this path whenever a page buffer must remain stable across additional page fetches; synchronous decoders may continue using transient `get_page()` reads.

## LRU vs CLOCK

LRU:

```text
choose unpinned + Pager-approved frame
with oldest last_touch
```

CLOCK:

```text
clock hand
   ↓
referenced? -> clear + second chance
   ↓ no
unpinned + Pager-approved? -> evict
```

Use:

```python
Database("demo.db", buffer_pages=8, replacement_policy="lru")
Database("demo.db", buffer_pages=8, replacement_policy="clock")
```

CLOCK is the default v0.7 policy.

## Dirty eviction and durability

The replacement algorithm itself does not know about journal/WAL rules.

```text
Buffer Manager chooses victim
            ↓
Pager.can_evict(frame)
            ↓
Pager performs safe writeback if needed
```

### Rollback mode

A dirty transaction page can be evicted because its old image is already protected by the rollback journal:

```text
before-image captured
      ↓
journal sync before DB write
      ↓
dirty page writeback
      ↓
evict
```

ROLLBACK/hot-journal recovery can restore the old version even though the modified frame no longer exists in memory.

### WAL mode

An uncommitted WAL dirty frame cannot be written into the main DB, so it is not evictable:

```text
active WAL tx + dirty frame
          ↓
      keep resident
```

After COMMIT, the after-image is durable in WAL, the frame becomes clean, and it may be evicted. A later miss reloads the page from WAL overlay.

This educational version deliberately raises `BufferPoolFullError` if one WAL transaction dirties more pages than fit in the configured buffer. It does not hide a second unbounded transaction cache.

## Buffer observability

Python:

```python
print(db.buffer_status())
print(db.buffer_frames_text())
```

Example status:

```text
policy=clock capacity=3 resident=3 dirty=0 pinned=0
hits=411 misses=28 hit_rate=93.6% evictions=32 dirty_evictions=1
```

Resident frame table:

```text
PAGE  DIRTY  PIN  REF  LAST_TOUCH
   1  False    0  True          553
   4  False    0  True          554
   9  False    0  True          555
```

## CLI

```bash
mini-sqlite \
  --journal-mode wal \
  --buffer-pages 16 \
  --replacement-policy clock \
  demo.db
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
.buffer
.frames
.explain SQL
.bytecode SQL
```

## Project structure

```text
mini_sqlite/
├── storage/
│   ├── buffer.py      # v0.7 bounded residency + replacement
│   ├── pager.py       # logical page API + durability-aware eviction hooks
│   ├── journal.py     # v0.2 before-image rollback
│   ├── wal.py         # v0.6 after-image WAL
│   ├── meta.py
│   └── record.py
├── btree/
├── index/
├── catalog/
├── sql/
├── planner/
├── vm/
├── transaction/
└── cli/
```

## Learning order

For v0.7, read:

1. `docs/BUFFER_MANAGER.md`
2. `mini_sqlite/storage/buffer.py`
3. `mini_sqlite/storage/pager.py`
4. `tests/test_buffer_manager.py`
5. `docs/TRANSACTIONS.md`
6. `docs/WAL.md`
7. `examples/buffer_pool.py`

The main lesson is the separation between **replacement policy** and **durability policy**.

## Deliberate limits

This is an educational engine, not SQLite compatibility work. v0.7 does **not** implement concurrent connections, shared cache, async page I/O, prefetching, mmap/direct I/O, ARC/2Q, transaction spill files, cost-based optimization, or SQLite binary compatibility.

See `Plan.md` for v0.8: statistics, cardinality/selectivity estimation, access-path costing, and JOIN-order selection.
