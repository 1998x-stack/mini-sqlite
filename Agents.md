# Agents.md — mini-sqlite v0.8 Frozen Development Contract

> This branch teaches one dominant mental model: **cost-based plan choice from persistent statistics**. Do not backport v0.9 concurrency mechanisms here.

## 1. Preserved architecture

```text
SQL -> Parser -> AST
          ↓
       Planner
          ↓
   Cost Model / Stats
          ↓
      physical plan
          ↓
Compiler -> Bytecode -> VM
          ↓
Table / Index B+Trees
          ↓
Pager -> Buffer Manager -> rollback/WAL -> disk
```

Optimizer estimates may change plan selection but never storage correctness or SQL semantics.

## 2. Statistics contract

`ANALYZE` is explicit. It scans data and persists a snapshot in catalog metadata.

Statistics include:

```text
row_count
null_count
distinct_count
min/max
up to 16 most-common-value frequencies
```

Writes after ANALYZE may make statistics stale. Do not silently recompute them inside INSERT/UPDATE/DELETE; staleness is part of the lesson.

## 3. Missing-stats contract

When statistics are absent, preserve the historical rule planner:

```text
PK equality -> PK seek
indexed equality -> secondary-index seek
otherwise -> table scan
```

Missing or poor estimates may reduce performance, never correctness.

## 4. Cost-model contract

Keep constants small, explicit, deterministic, and documented. Costs are abstract work units, not latency promises.

Candidate enumeration and costing must be separated from SQL parsing and from B+Tree implementation.

## 5. JOIN-order contract

Logical SQL-left/right identity is stable even when physical outer/inner order changes.

```text
cursor 0 = logical SQL-left
cursor 1 = logical SQL-right
```

`outer_side` controls iteration only. Projection, qualified names, WHERE, ORDER BY, and result tuple order must remain semantic, not physical.

## 6. Durability contract

ANALYZE modifies catalog pages and must use the same transaction/durability path as DDL:

- rollback journal can undo stats changes;
- WAL can hold committed stats before checkpoint;
- checkpoint preserves stats;
- Buffer Manager must not special-case optimizer metadata.

## 7. Observability contract

`EXPLAIN` after ANALYZE should make reasoning auditable:

```text
estimated rows
estimated chosen cost
candidate costs
physical join order
chosen access path
```

`Catalog.get_table(...).stats` exposes saved statistics.

## 8. Tests

Must retain full v0.1-v0.7 regression and cover:

- ANALYZE parser variants;
- persisted statistics;
- explicit stale-stat behavior;
- hot-value scan vs rare-value index plan flip;
- JOIN order reversal;
- reversed JOIN using an inner secondary index;
- ANALYZE rollback;
- WAL reopen/checkpoint of stats;
- result correctness independent of physical order.

Run:

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

## 9. Non-goals

No multi-way DP join optimizer, advanced histograms, multi-column stats, adaptive runtime plans, hash/merge join, parallelism, or concurrency controls.

## 10. Definition of Done

v0.8 can be frozen only when statistics are durable and inspectable, scan/index choice demonstrably flips with distribution, JOIN orientation demonstrably flips with cardinality/index access, all prior storage/durability/buffer behavior remains green, docs and examples match implementation, and the exact final v0.8 branch-head CI passes.
