# Agents.md — mini-sqlite v0.4 Development Contract

> **Frozen learning snapshot.** Read this file before changing v0.4 code, tests, documentation, or execution semantics.

## 1. Version mission

v0.4 adds one dominant mental model:

> **A SQL query is a composition of row-processing stages layered on top of a physical row source.**

```text
access path -> filter -> collect -> sort -> aggregate/project -> limit -> result
```

Storage, index, and durability layers must remain independent of SQL relational semantics.

## 2. Mandatory reading order

1. `Agents.md`
2. `version.md`
3. `docs/RELATIONAL_ENGINE.md`
4. `docs/ARCHITECTURE.md`
5. `tests/test_relational.py`
6. `sql/ast.py`
7. `planner/plan.py`
8. `planner/planner.py`
9. `vm/compiler.py`
10. `vm/vm.py`

## 3. Branch boundary

This branch is the frozen **v0.4 relational execution milestone**. Allowed changes are documentation corrections, tests clarifying promised behavior, and narrowly scoped defects within v0.4 semantics.

Do not backport v0.5 JOIN, v0.6 WAL, future buffer-manager work, cost optimization, or concurrency.

## 4. Architecture rules

- Parser describes syntax; it never chooses B+Tree access paths.
- Planner chooses access path and relational processing metadata; it never reads pages.
- VM evaluates predicates/aggregates and mutates rows through table/index abstractions.
- B+Trees remain unaware of SQL expressions and transactions.
- Pager remains the physical durability boundary.
- equality may use v0.3 indexes; range predicates must not pretend to use an equality-only index cursor.
- UPDATE must keep table and every secondary index atomically consistent.

## 5. Relational pipeline invariants

For SELECT, visible logical order is:

```text
source/filter -> collect -> sort -> aggregate/project -> limit -> emit
```

`ORDER BY` operates on full source rows before projection. Aggregate queries without GROUP BY produce at most one row before LIMIT.

v0.4 uses an in-memory materialized working set. Do not claim streaming/vectorized execution or early LIMIT short-circuit.

## 6. UPDATE invariants

- assignment types are validated against schema;
- INTEGER PRIMARY KEY updates are rejected;
- old secondary-index entries are removed before replacement;
- new secondary-index entries are inserted after replacement;
- all page changes use the surrounding rollback-journal transaction;
- indexed-column UPDATE may use the old index to locate a snapshot of rowids and then safely rewrite that same index.

## 7. Testing contract

Run:

```bash
python -m pytest -q
python examples/quickstart.py
python examples/transactions.py
python examples/indexes.py
python examples/relational.py
python -m compileall -q mini_sqlite
```

Changes require regression coverage for parser/planner/bytecode, comparison semantics, sort/limit, aggregate NULL behavior, PK/index/scan UPDATE paths, secondary-index maintenance, reopen persistence, rollback, and hot-journal recovery.

## 8. Definition of Done

A v0.4-compatible change is complete only when the pipeline remains inspectable, older access paths remain correct, UPDATE/index atomicity is tested, crash recovery remains valid, docs match exact semantics, and full regression passes.
