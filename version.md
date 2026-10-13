# Current integrated state — v0.9

`main` contains the validated v0.1-v0.9 learning stack.

## Current capabilities

- persistent 4 KiB pages and table/catalog B+Trees;
- tokenizer/parser/AST/planner/tiny VM;
- rollback-journal transactions and crash recovery;
- secondary indexes and rowid lookup;
- UPDATE, comparisons, ORDER BY, LIMIT and scalar aggregates;
- INNER JOIN, aliases, self-join and indexed nested loops;
- WAL after-image commits, read overlay and checkpoint;
- bounded buffer pool with LRU/CLOCK, pinning and dirty-eviction rules;
- `ANALYZE` statistics snapshots and cost-based access/JOIN planning;
- multiple live process-local connections against one database path;
- rollback SHARED/RESERVED/EXCLUSIVE lock transitions;
- one WAL writer coexisting with reader snapshots;
- deterministic busy timeout and stale-snapshot write rejection;
- cache refresh under connection locks;
- `.locks` / lock-status inspection.

## Latest mechanism reading order

1. `docs/CONCURRENCY.md`
2. `mini_sqlite/concurrency/lock.py`
3. `mini_sqlite/database.py`
4. `mini_sqlite/storage/pager.py`
5. `mini_sqlite/storage/wal.py`
6. `tests/test_concurrency.py`
7. `examples/concurrency.py`

For optimizer/storage foundations, continue with `docs/OPTIMIZER.md`, `docs/BUFFER_MANAGER.md`, `docs/WAL.md`, and `docs/TRANSACTIONS.md`.

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
python examples/optimizer.py
python examples/concurrency.py
python -m compileall -q mini_sqlite
```

## Important concurrency scope

v0.9 locking is intentionally process-local. It teaches connection-state compatibility, snapshots, busy handling, and rollback-vs-WAL differences; it does not claim cross-process OS-level locking.

## Next

v1.0: **Educationally Complete mini SQLite** — consolidate the architecture, add end-to-end inspection labs and benchmark scenarios, document compatibility/recovery guarantees, clean the public learning surface, and provide a final v0.1→v0.9 reading path.
