# Agents.md — mini-sqlite Development Contract

> Canonical contract for `main`. Read before changing architecture, storage, planner, caching, durability, statistics, or connection semantics.

## Mission

mini-sqlite is an educational, Python-first database engine. Each version introduces one dominant database mental model while preserving earlier invariants.

## Branch protocol

```text
latest validated main
   ↓
create vX.Y
   ↓
one dominant mechanism
   ↓
tests + docs + example
   ↓
exact branch-head CI green
   ↓
freeze version branch
   ↓
integrate same engine tree into main
   ↓
restore canonical main docs
```

`main` must represent the newest validated integrated state.

## Integrated milestones

```text
v0.1  pages / B+Tree / SQL / Planner / VM
v0.2  rollback transactions / crash recovery
v0.3  secondary indexes
v0.4  relational execution / UPDATE / aggregates
v0.5  JOIN / indexed nested loop
v0.6  WAL / overlay / checkpoint
v0.7  bounded Buffer Manager / LRU / CLOCK
v0.8  ANALYZE / persistent statistics / cost-based optimizer   ← integrated
v0.9  concurrency / locking                                    ← next
v1.0  educationally complete
```

## Current architecture

```text
SQL -> Parser -> AST -> Planner
                         │
                  stats + CostModel
                         ↓
                  physical plan
                         ↓
                Compiler / VM
                         ↓
              relations / JOIN
                         ↓
             table/index B+Trees
                         ↓
                       Pager
                         ↓
              Bounded Buffer Manager
                  ├─ LRU
                  └─ CLOCK
                         ↓
             rollback journal or WAL
                         ↓
                        disk
```

## Architecture rules

- SQL frontend never reads page bytes directly.
- Planner chooses physical work but performs no file I/O.
- B+Trees obtain logical pages only through Pager.
- Buffer Manager decides residency; Pager decides durability legality.
- rollback/WAL remain interchangeable policies below the same page API.
- optimizer estimates may change performance, never correctness.
- statistics are persisted catalog metadata and may be stale until ANALYZE.
- future locking belongs at connection/transaction boundaries, not inside B+Tree nodes.

## Current validation

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

## Current directive

`main` contains the validated **v0.8 Cost-Based Optimizer** milestone.

Next: **v0.9 Concurrency / Locking**.

Central question:

> What changes when two independent connections can read or write the same database while preserving transaction isolation, rollback/WAL durability, cache coherence, and deterministic busy behavior?
