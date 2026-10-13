# Agents.md — mini-sqlite Development Contract

> `main` is the canonical integrated state. Historical version branches are frozen learning snapshots. Read this file before changing storage formats, durability, page ownership, planning, locking, maintenance, tests, or docs.

## Mission

mini-sqlite is a Python-first educational database engine. Prefer architectural clarity, explicit invariants, mechanism-focused tests, and observable behavior over SQL breadth or production optimizations.

## Integrated architecture through v1.2

```text
SQL → Parser/AST → Cost Planner → Compiler/VM → relational operators/JOIN
                                              ↓
                                   table/index B+Trees
                                              ↓
                                            Pager
             ┌────────────────────────────────┼───────────────────────────────┐
             ↓                                ↓                               ↓
       Buffer Manager                 Free-list allocator              Durability
       LRU / CLOCK                 free / reuse / tail trim       rollback journal / WAL
             └────────────────────────────────┴───────────────────────────────┘
                                              ↓
                                         database file

Concurrency: process-local state machine + POSIX flock
Maintenance: integrity_check · reindex · vacuum · incremental_vacuum · explain_analyze
```

## Version spine

```text
v0.1 Page/Pager/B+Tree/SQL/VM
v0.2 Rollback Journal + Transactions
v0.3 Secondary Index
v0.4 Relational Execution
v0.5 JOIN
v0.6 WAL
v0.7 Buffer Manager
v0.8 Cost-Based Optimizer
v0.9 Process-local Concurrency
v1.0 Integrity / REINDEX / VACUUM / Diagnostics
v1.1 Cross-process File Locking
v1.2 Free-list Page Reuse + Incremental VACUUM        ✅ integrated
```

## Core invariants

- SQL/planner/VM never edit file bytes directly.
- B+Trees obtain pages only through Pager.
- Pager owns durability and page allocation/deallocation.
- Buffer Manager owns residency, not durability.
- Page 0 is never free.
- A page may have exactly one ownership class: meta, tree/index, or free-list.
- Free-list reuse and release are transactional.
- Rollback before-images are durable before destructive DB writes/truncation.
- Uncommitted WAL pages never leak into the main DB.
- WAL reads use complete committed prefixes only.
- Incremental vacuum truncates only consecutive free tail pages and never moves live pages.
- Cross-process OS locks remain authoritative for physical shrink.
- Integrity checking is read-only; REINDEX repairs derived index state through normal transactions.

## Format rule

v1.2 main-file metadata format is version 2. v1 files are readable; persistence of v2 metadata/free-list semantics upgrades the file. Older engines must reject unknown newer format versions. Any future incompatible format change requires an explicit version bump, migration/compatibility statement, reopen tests, and corruption tests.

## Branch protocol

```text
validated main
   ↓
create vX.Y
   ↓
one dominant mental model
   ↓
implementation + tests + docs + example
   ↓
exact branch-head CI green
   ↓
freeze version branch
   ↓
integrate the same engine tree into main
   ↓
restore canonical Agents.md / version.md
```

Never claim a version is frozen from local tests alone.

## Full regression

Run `python -m pytest -q`, all examples through `examples/freelist.py`, and `python -m compileall -q mini_sqlite`.

## Next extension

v1.3 should focus only on **Range Index Scan + Composite Index**: ordered lower/upper-bound cursors, multi-column key metadata/encoding, left-prefix planning, selectivity/cost integration, and explain-visible range plans. Do not mix savepoints, new join algorithms, or MVCC into that version.
