# Agents.md — mini-sqlite v1.0 Frozen Development Contract

> v1.0 is the educationally-complete core. Its dominant mental model is **database lifecycle integrity and maintainability across all previously built layers**.

## 1. Preserve the architecture

```text
SQL / Planner / VM
        ↓
relational operators / JOIN
        ↓
Table + Index B+Trees
        ↓
Database + Lock Registry
        ↓
Pager + Buffer Manager
        ↓
rollback journal / WAL
        ↓
disk

Maintenance/diagnostics observe and repair through these public boundaries;
they must not invent a hidden second storage engine.
```

## 2. Integrity-check contract

`integrity_check()` must validate structural and logical invariants without mutating the database. It may report stale statistics and unreachable pages as warnings, but structural tree errors, invalid rows, page aliasing, and index/table disagreement are errors.

## 3. REINDEX contract

REINDEX rebuilds derived index state inside ordinary transaction/durability semantics. A failed or rolled-back rebuild must leave the old index usable. Successful rebuild may leave old pages orphaned; VACUUM is responsible for reclaiming them.

## 4. VACUUM contract

VACUUM rewrites the logical database to a same-directory private file and atomically replaces the original. It must preserve:

- schema and table ids as logical schema, not necessarily physical page ids;
- every committed row;
- secondary-index definitions and contents;
- presence of ANALYZE statistics (recomputed exactly);
- selected connection journal mode after reopen.

It must reject active transactions and multiple live process-local connections.

## 5. EXPLAIN ANALYZE contract

It is read-only and SELECT-only. It must report the chosen estimated plan and actual execution metrics without changing query semantics. Timing is educational/diagnostic, not a stable performance API.

## 6. Compatibility contract

Do not silently change the main page, rollback journal, WAL, record, catalog, or secondary-index binary formats in v1.0. Any post-1.0 format change requires a new version and explicit compatibility statement.

## 7. Historical invariants remain mandatory

All v0.1-v0.9 tests must remain green: crash recovery, WAL committed-prefix rules, bounded cache/pin rules, cost choices, and concurrency locks are not weakened by maintenance features.

## 8. Validation

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

`examples/benchmark.py` is optional and illustrative only.

## 9. Non-goals

No cross-process locking, online VACUUM, free-list reuse, MVCC, savepoints, multi-writer WAL, SQLite binary compatibility, or production benchmark claims.

## 10. Frozen-branch rule

After exact v1.0 branch-head CI is green, permit only documentation corrections, tests clarifying promised behavior, and narrowly scoped defects within v1.0 semantics. New mechanisms belong on post-1.0 extension branches.
