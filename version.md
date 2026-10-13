# Current integrated state — v1.0

`main` contains the validated **v1.0 Educationally Complete** mini-sqlite core.

## Integrated architecture

```text
SQL → Parser / AST → Cost-Based Planner → Compiler / VM
                           ↑                    │
                    ANALYZE statistics         ↓
                                    relational ops / JOIN
                                             ↓
                                  table/index B+Trees
                                             ↓
                              Database / Lock Registry
                                             ↓
                                           Pager
                                             ↓
                                  Bounded Buffer Manager
                                  ├─ LRU
                                  └─ CLOCK
                                             ↓
                          rollback journal OR WAL/checkpoint
                                             ↓
                                        database file

Lifecycle diagnostics / maintenance:
 integrity_check · reindex · vacuum · explain_analyze
```

## Core capabilities

- persistent 4 KiB page file and slotted B+Trees;
- SQL tokenizer/parser/AST/planner/tiny VM;
- CREATE TABLE/INDEX, INSERT/SELECT/DELETE/UPDATE;
- comparisons, ORDER BY, LIMIT and scalar aggregates;
- INNER JOIN, aliases, self-join, indexed nested loop;
- rollback-journal transactions and crash recovery;
- secondary indexes with atomic table/index maintenance;
- WAL after-image frames, committed overlay and checkpoint;
- bounded LRU/CLOCK buffer pool with pin/unpin and dirty eviction rules;
- ANALYZE statistics, selectivity estimates and cost-based scan/index/JOIN choices;
- process-local multi-connection locking, busy timeout and WAL reader snapshots;
- integrity checking across page trees, table rows and secondary indexes;
- transaction-safe REINDEX;
- exclusive compact VACUUM rewrite;
- EXPLAIN ANALYZE with estimated plan, actual rows/time, buffer deltas and VM bytecode;
- architecture/compatibility/fault/learning-path documentation.

## Recommended v1.0 reading path

1. `docs/LEARNING_PATH.md`
2. `docs/MAINTENANCE.md`
3. `mini_sqlite/maintenance/database.py`
4. `mini_sqlite/maintenance/integrity.py`
5. `tests/test_maintenance.py`
6. `examples/lifecycle.py`
7. `docs/COMPATIBILITY.md`
8. `docs/FAULT_MATRIX.md`

For earlier mechanisms follow the version-by-version paths in `docs/LEARNING_PATH.md`.

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
python examples/lifecycle.py
python -m compileall -q mini_sqlite
```

The frozen v1.0 branch passed the exact GitHub CI matrix on Python 3.10 and 3.12.

## Status after v1.0

The educational core is complete. `Plan.md` lists optional extension tracks rather than mandatory missing layers:

```text
v1.1  Cross-process file locking
v1.2  Free-list reuse + incremental vacuum
v1.3  Range scans + composite indexes
v1.4  Savepoints
v1.5  Hash/Merge Join + wider enumeration
v2.0  MVCC experiment
```

Future work should preserve v1.0 as a frozen learning checkpoint and introduce one major mental model per extension version.
