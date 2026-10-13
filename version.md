# mini-sqlite v0.8.0 — Cost-Based Optimizer

This frozen branch adds an inspectable cost-based planner on top of the v0.1-v0.7 storage, durability, relational, JOIN, WAL, and bounded-buffer foundations.

## Primary mental model

```text
ANALYZE
   ↓
Persistent statistics
   ↓
Cardinality / selectivity estimates
   ↓
Candidate physical plans
   ↓
Cost model
   ↓
Minimum-cost choice
   ↓
Bytecode / VM
```

## New capabilities

- `ANALYZE;` and `ANALYZE table;`;
- persistent `TableStats` / `ColumnStats` inside catalog rows;
- row count, NULL count, distinct count, min/max;
- top-16 most-common-value frequencies for skew;
- explicit statistics staleness model;
- table-scan vs secondary-index cost comparison;
- equality and simple range cardinality estimation;
- two-table JOIN orientation comparison;
- physical JOIN order may differ from SQL order;
- join inner path may use PK, secondary index, or scan;
- EXPLAIN shows estimated rows, chosen cost, and rejected candidates;
- `Catalog.get_table(...).stats` inspection;
- rollback/WAL persistence tests for statistics.

## Important files

```text
mini_sqlite/catalog/statistics.py
mini_sqlite/catalog/catalog.py
mini_sqlite/planner/optimizer.py
mini_sqlite/planner/cost_planner.py
mini_sqlite/planner/plan.py
mini_sqlite/vm/cost_compiler.py
examples/optimizer.py
tests/test_optimizer.py
docs/OPTIMIZER.md
```

## Reading order

1. `docs/OPTIMIZER.md`
2. `catalog/statistics.py`
3. `Catalog.analyze()`
4. `planner/optimizer.py`
5. `planner/cost_planner.py`
6. `vm/cost_compiler.py`
7. `tests/test_optimizer.py`
8. `examples/optimizer.py`

## Compatibility

The main database page format and B+Tree/index layouts are unchanged.

Catalog table JSON gains an optional `stats` field. Older v0.7-style decoders ignore unknown JSON fields, while v0.8 accepts catalog rows with no stats. Statistics therefore remain metadata rather than a new page type.

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

## Explicit limits

No many-way join enumeration, production histograms, multi-column correlation statistics, hash/merge join, adaptive optimization, or index range scan.

## Next

v0.9: **Concurrency / Locking** — multiple connections, lock state, busy handling, and interaction between readers/writers under rollback and WAL durability modes.
