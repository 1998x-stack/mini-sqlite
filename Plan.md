# mini-sqlite — Architecture-Driven Development Plan

## Completed learning milestones

```text
v0.1  Pages / Pager / primary B+Tree / SQL -> VM                 ✅
v0.2  Rollback journal / transactions / crash recovery           ✅
v0.3  Secondary indexes / richer access paths                    ✅
v0.4  Relational execution / UPDATE / sort / aggregate           ✅
v0.5  INNER JOIN / indexed nested loop                           ✅
v0.6  WAL / committed overlay / checkpoint                       ✅
v0.7  Bounded buffer manager / LRU / CLOCK                       ✅
v0.8  ANALYZE / statistics / cost-based optimizer                ✅
v0.9  Multi-connection concurrency / locks / busy / snapshots    ✅
```

## v0.9 mental model

```text
correct crash recovery
        +
correct page cache
        +
correct optimizer
        ≠
correct concurrent database

multiple connections
        ↓
lock compatibility
        ↓
snapshot visibility
        ↓
deterministic busy handling
```

Rollback and WAL deliberately expose different concurrency behavior.

## Current next milestone — v1.0 Educationally Complete

Central question:

> Can a reader follow one coherent path from SQL text to plans, bytecode, B+Trees, pages, transactions, WAL, buffer replacement, statistics, and connection locks — and inspect each layer without hidden magic?

Target v1.0 work:

- final cross-version architecture guide;
- cohesive learning labs from v0.1 to v0.9;
- end-to-end `EXPLAIN + bytecode + pages + buffer + WAL + locks` inspection scenario;
- small reproducible benchmark suite showing scan/index/JOIN/cache effects without pretending to benchmark SQLite itself;
- compatibility and corruption/recovery matrix;
- cleanup of public APIs and naming;
- final code-map and recommended reading order;
- final full regression and CI matrix.

Explicit v1.0 non-goals: SQL feature parity with SQLite, SQLite file-format compatibility, cross-process production locking, MVCC, distributed transactions, and production-grade cost calibration.

## Version protocol

```text
read Agents.md / Plan.md / version.md
        ↓
create vX.Y from newest validated main
        ↓
implement one dominant mental model
        ↓
tests + example + docs
        ↓
exact version branch-head CI green
        ↓
freeze branch
        ↓
integrate same engine tree into main
        ↓
restore canonical main docs
```
