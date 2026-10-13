# mini-sqlite v0.7

## Theme

**Bounded page residency with pin/unpin, LRU/CLOCK replacement, and durability-aware dirty eviction.**

Earlier versions quietly kept every touched page in an unbounded Python dictionary. v0.7 makes memory pressure explicit:

```text
database pages >> buffer frames
         ↓
cache hit / miss
         ↓
replacement candidate
         ↓
pin + durability checks
         ↓
evict / write back
```

## Delta from v0.6

Added:

- `Database(..., buffer_pages=N)`;
- `replacement_policy="clock" | "lru"`;
- explicit `BufferFrame` and `BufferManager`;
- bounded resident-page invariant;
- pin/unpin page lifetime through `Pager.pin_page()`;
- LRU replacement;
- CLOCK second-chance replacement;
- durability-aware dirty victim checks;
- rollback-mode dirty writeback + eviction inside active transactions;
- WAL protection for uncommitted dirty frames;
- cache hit/miss/eviction/dirty-eviction metrics;
- `.buffer` and `.frames` shell commands;
- `docs/BUFFER_MANAGER.md`;
- `examples/buffer_pool.py`;
- `tests/test_buffer_manager.py`.

## Important source files

- `mini_sqlite/storage/buffer.py`
- `mini_sqlite/storage/pager.py`
- `mini_sqlite/btree/btree.py`
- `mini_sqlite/index/btree.py`
- `mini_sqlite/database.py`
- `tests/test_buffer_manager.py`
- `docs/BUFFER_MANAGER.md`

## Recommended reading order

1. `docs/BUFFER_MANAGER.md`
2. `storage/buffer.py`
3. `storage/pager.py`
4. `tests/test_buffer_manager.py`
5. `docs/TRANSACTIONS.md`
6. `docs/WAL.md`
7. `examples/buffer_pool.py`

## Validation

```bash
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

## Storage compatibility

The main DB page layout, rollback-journal format, and WAL format are unchanged from v0.6. v0.7 changes only in-memory residency and public configuration.

## Important limitation

In WAL mode, uncommitted dirty frames are deliberately non-evictable. A transaction whose dirty working set exceeds `buffer_pages` raises `BufferPoolFullError`. This keeps WAL atomicity obvious without adding a second hidden unbounded transaction cache or spill file.

## Explicit non-goals

No async I/O, prefetching, mmap/direct-I/O tuning, ARC/2Q, shared cache, transaction spill file, concurrent buffer access, cost-based planning, or multi-connection lock manager.

## Next

v0.8 should add a **cost-based optimizer**: persisted/analyzed statistics, cardinality/selectivity estimates, comparable access-path costs, and JOIN-order decisions that can be inspected rather than hard-coded.
