# Agents.md — mini-sqlite v0.5 Development Contract

> **Frozen learning snapshot.** Read this file before changing v0.5 code, tests, documentation, or JOIN semantics.

## 1. Version mission

v0.5 adds one dominant mental model:

> **JOIN composes two row sources; an index changes inner-row access cost, not relational meaning.**

```text
outer row source
      ↓
inner scan / seek
      ↓
join match
      ↓
existing v0.4 relational pipeline
```

## 2. Mandatory reading order

1. `Agents.md`
2. `version.md`
3. `docs/JOINS.md`
4. `docs/RELATIONAL_ENGINE.md`
5. `docs/ARCHITECTURE.md`
6. `tests/test_joins.py`
7. `sql/ast.py`
8. `sql/parser.py`
9. `planner/plan.py`
10. `planner/planner.py`
11. `vm/compiler.py`
12. `vm/vm.py`

## 3. Branch boundary

This branch is the frozen **v0.5 JOIN milestone**. Allowed changes are documentation corrections, tests clarifying promised behavior, and narrowly scoped defects inside v0.5 semantics.

Do not backport v0.6 WAL, v0.7 buffer management, cost-based join ordering, concurrency, outer joins, or multi-join planning.

## 4. Architecture rules

- Parser binds no physical access strategy.
- Name resolution belongs above storage.
- Planner decides the right-side JOIN access path.
- The written left source stays the outer side in v0.5; no hidden reordering.
- B+Trees know nothing about JOIN or aliases.
- Secondary-index duplicate rowids remain explicit through `(value,rowid)` keys.
- JOIN bytecode must expose scan/seek behavior; do not hide the complete JOIN in one opaque storage helper.
- Existing v0.4 filter/sort/project/aggregate/limit operators must be reused after JOIN.
- Pager remains the physical durability boundary; v0.5 adds no on-disk format.

## 5. JOIN invariants

Supported shape:

```text
left [alias]
INNER JOIN right [alias]
ON left_column = right_column
```

The Planner normalizes the ON predicate so one column belongs to each source. Join column types must match.

The inner path is rule-based:

```text
right ON column is PK          -> PRIMARY_KEY seek
right ON column has index      -> SECONDARY_INDEX seek
otherwise                      -> TABLE_SCAN nested loop
```

Do not claim cost-based selection.

## 6. Name-resolution invariants

- qualified names bind to their visible alias/source;
- unqualified names must resolve to exactly one source;
- ambiguous names raise `SchemaError`;
- self-joins require distinct visible aliases;
- joined rows use flat `(left..., right...)` layout only inside planning/execution, never in storage.

## 7. Testing contract

Run:

```bash
python -m pytest -q
python examples/quickstart.py
python examples/transactions.py
python examples/indexes.py
python examples/relational.py
python examples/joins.py
python -m compileall -q mini_sqlite
```

Coverage must include parser/name binding, duplicate matches, plain nested loop, PK indexed nested loop, secondary-index nested loop, post-JOIN filter/sort/limit/aggregate, self-join, ambiguity errors, reopen persistence, and full older-version regression.

## 8. Definition of Done

A v0.5-compatible change is complete only when JOIN semantics are equivalent across plain/indexed paths, bytecode remains inspectable, v0.1-v0.4 behavior stays green, docs match exact scope, and the exact final `v0.5` branch-head CI passes.
