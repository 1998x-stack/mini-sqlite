# Current integrated state — v0.8

`main` contains the validated v0.1-v0.8 learning stack.

## Current capabilities

- persistent 4 KiB pages and table/catalog B+Trees;
- tokenizer/parser/AST/planner/tiny VM;
- rollback-journal transactions and crash recovery;
- secondary indexes and rowid lookup;
- UPDATE, comparisons, ORDER BY, LIMIT and scalar aggregates;
- INNER JOIN, aliases, self-join and indexed nested loops;
- WAL after-image commits, read overlay and checkpoint;
- bounded buffer pool with LRU/CLOCK, pinning and dirty eviction rules;
- `ANALYZE` statistics snapshots;
- selectivity/cardinality estimates;
- table-scan vs index cost comparison;
- cost-selected two-table JOIN orientation;
- EXPLAIN candidate costs and physical order.

## Latest mechanism reading order

1. `docs/OPTIMIZER.md`
2. `mini_sqlite/catalog/statistics.py`
3. `mini_sqlite/catalog/catalog.py::analyze`
4. `mini_sqlite/planner/optimizer.py`
5. `mini_sqlite/planner/cost_planner.py`
6. `mini_sqlite/vm/cost_compiler.py`
7. `tests/test_optimizer.py`
8. `examples/optimizer.py`

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
python -m compileall -q mini_sqlite
```

## Next

v0.9: **Concurrency / Locking** — multiple live connections, rollback SHARED/RESERVED/EXCLUSIVE state, WAL reader/writer distinction, busy handling, cache refresh, and deterministic cleanup.
