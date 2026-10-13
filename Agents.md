# Agents.md — mini-sqlite Development Contract

> **Mandatory for every future iteration:** read this file before changing code, tests, documentation, branches, version scope, storage formats, planner/execution behavior, or durability protocol.
>
> This is the canonical engineering contract for `main`. Frozen version branches carry branch-specific `Agents.md` files.

## 1. Repository mission

mini-sqlite is an educational, Python-first database engine for understanding mechanisms behind SQLite-style systems.

Priorities:

```text
architectural clarity
      ↓
correctness + explicit invariants
      ↓
readable reference implementation
      ↓
mechanism-focused tests
      ↓
conceptual mapping to SQLite/database systems
      ↓
performance and SQL breadth later
```

Do not optimize for SQLite API/file-format completeness or copy upstream SQLite source.

## 2. Mandatory reading order

### On `main`

1. `Agents.md`
2. `Plan.md`
3. `version.md`
4. relevant architecture/format docs
5. relevant tests
6. current implementation

### On a version branch

1. branch `Agents.md`
2. branch `version.md`
3. relevant docs/tests/source

Never assume a historical branch should contain later-version mechanisms.

## 3. Branch invariant

`main` must always be the newest integrated, validated state.

```text
latest main
   ↓
create vX.Y
   ↓
implement one major database mental model
   ↓
full tests + docs + example
   ↓
exact version branch-head CI green
   ↓
freeze version branch
   ↓
integrate the same validated engine tree into main
   ↓
restore canonical main docs
```

Forbidden: a version branch containing newer validated engine code while `main` remains stale.

## 4. Version sequence

```text
v0.1  Page-backed B+Tree + SQL → Planner → VM
v0.2  Rollback-journal transactions + crash recovery
v0.3  Secondary indexes + richer planner
v0.4  Relational execution operators
v0.5  JOIN                                                ← next
v0.6  WAL
v0.7  Bounded buffer manager
v0.8  Cost-based optimizer
v0.9  Concurrency / locking
v1.0  Educationally complete mini SQLite
```

One version should introduce one dominant mental model.

## 5. Current architecture

```text
SQL → Parser → AST → Planner
                      │
                      ├─ physical access path
                      │    PRIMARY_KEY / SECONDARY_INDEX / TABLE_SCAN
                      │
                      └─ relational processing metadata
                               │
                               ▼
                         Compiler → Bytecode → VM
                                           │
                  source → filter → collect → sort
                                           ↓
                                aggregate/project
                                           ↓
                                      limit → emit
                                           │
                         ┌─────────────────┴─────────────────┐
                         ▼                                   ▼
                    Table Cursor                        Index Cursor
                         │                                   │
                         ▼                                   ▼
                 integer-key B+Tree                   byte-key B+Tree
                         └─────────────────┬─────────────────┘
                                           ▼
                                         Pager
                                   ┌───────┴───────┐
                                   ▼               ▼
                          rollback journal    database file
```

v0.4 proves that relational operators and UPDATE can compose above v0.3 access paths while reusing v0.2 durability unchanged.

## 6. Architecture rules

- separate policy from mechanism;
- SQL frontend never accesses page bytes directly;
- Planner chooses access paths/relational metadata but performs no physical I/O;
- VM talks to cursors/storage abstractions, not OS files;
- table/index B+Trees obtain and write pages only through Pager;
- Pager owns physical durability ordering;
- transaction state belongs outside B+Trees;
- schema/index metadata is persisted, never reconstructed from Python-only state;
- root page ids are mutable and their owners must persist root changes;
- relational operators compose above physical access paths rather than duplicating storage logic;
- UPDATE must keep table and all indexes atomically consistent through the existing transaction boundary;
- future JOIN should compose multiple row sources without moving name resolution or join predicates into storage;
- future WAL must replace/extend Pager durability behavior rather than rewrite query layers.

## 7. On-disk protocol rule

Any incompatible byte-layout change requires:

- `FORMAT_VERSION` review/bump;
- exact layout documentation;
- corruption and bounds checks;
- reopen tests;
- compatibility/migration statement.

Additive page types/metadata must still be documented. A durability-order change is a protocol change even when page bytes are unchanged.

## 8. Testing contract

Every new subsystem should include, where applicable:

- happy path;
- invariant/property tests;
- error-path tests;
- persistence/reopen validation;
- access-path/EXPLAIN validation;
- fault/crash tests for durability-sensitive changes;
- end-to-end integration example.

Full regression:

```bash
python -m pytest -q
python examples/quickstart.py
python examples/transactions.py
python examples/indexes.py
python examples/relational.py
python -m compileall -q mini_sqlite
```

Never claim a version is validated unless the exact reported tree has passed the relevant suite and final version-branch CI.

## 9. Documentation contract

When architecture/public API changes, review:

```text
version.md
README.md
Agents.md
Plan.md
relevant docs/*
relevant example
```

Every version should state its theme, delta, important source files, reading order, quick-run commands, explicit non-goals, and next-version rationale.

## 10. Historical branch rule

A frozen version branch may receive only documentation corrections, tests clarifying promised behavior, and narrowly scoped defects within that version boundary. Do not backport future subsystems.

## 11. Performance rule

Prefer:

```text
readable reference
   ↓
correctness
   ↓
measure/profile
   ↓
optimized educational path
```

Do not obscure page/tree/transaction/planner/execution invariants for premature optimization.

## 12. Generated artifacts and dependencies

Do not commit database files, journals, caches, logs, generated plots, or build artifacts unless a tiny deterministic fixture is explicitly required by tests. Keep the engine standard-library-first; development-only test/lint dependencies are acceptable.

## 13. Definition of Done for a version

A version can be frozen only when its primary mental model is explicit, promised implementation is complete, unit/invariant/error/persistence/crash tests pass where relevant, an educational example exists, `version.md` records the delta, branch-specific `Agents.md` exists, architecture/format docs are updated, package imports cleanly, the exact final version-branch CI is green, the validated engine state is integrated into `main`, and `Plan.md` records the next architectural question.

## 14. Current main directive

`main` contains the completed **v0.4 relational-execution milestone**.

The next version should be **v0.5: JOIN**.

Central question:

> How can two independently planned row sources be composed through an explicit join operator, while aliases/name resolution, duplicate matches, and indexed nested-loop access remain visible and storage-independent?
