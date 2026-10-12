# Agents.md — mini-sqlite Development Contract

> **Mandatory for every future iteration:** read this file before changing code, tests, documentation, branches, version scope, durability protocol, or architecture.
>
> This is the canonical engineering contract for `main`. Version branches carry branch-specific `Agents.md` files.

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
freeze version branch
   ↓
integrate validated tree into main
   ↓
restore canonical main docs
```

Forbidden: a version branch containing newer validated engine code while `main` remains stale.

## 4. Version sequence

```text
v0.1  Page-backed B+Tree + SQL → Planner → VM
v0.2  Rollback-journal transactions + crash recovery
v0.3  Secondary indexes + richer planner                 ← next
v0.4  Relational execution operators
v0.5  JOIN
v0.6  WAL
v0.7  Bounded buffer manager
v0.8  Cost-based optimizer
v0.9  Concurrency / locking
v1.0  Educationally complete mini SQLite
```

One version should introduce one dominant mental model.

## 5. Current architecture

```text
SQL → Parser → AST → Planner → Plan → Compiler → Bytecode → VM
                                                       │
                                                       ▼
                                                     Cursor
                                                       │
                                  Catalog ─────────── B+Tree
                                                       │
                                                       ▼
                                                     Pager
                                               ┌───────┴───────┐
                                               ▼               ▼
                                      rollback journal    database file
```

v0.2 proves crash-atomic transactions can be added at the Pager boundary without contaminating B+Tree/VM/Planner logic.

## 6. Architecture rules

- separate policy from mechanism;
- SQL frontend never accesses page bytes directly;
- Planner never performs physical I/O;
- VM talks to cursors/storage abstractions, not OS files;
- B+Tree obtains and writes pages only through Pager;
- Pager owns physical durability ordering;
- connection transaction state belongs outside B+Tree;
- schema/index metadata must be persisted, not reconstructed from Python state;
- root page ids are mutable and owners must persist root changes;
- future indexes must extend Catalog + Planner + B+Tree boundaries rather than special-case Parser/SELECT;
- future WAL must replace/extend Pager durability behavior rather than rewrite query layers.

## 7. On-disk protocol rule

Any incompatible byte-layout change requires:

- `FORMAT_VERSION` review/bump;
- exact layout documentation;
- corruption and bounds checks;
- reopen tests;
- compatibility/migration statement.

A durability-order change is also a protocol change even when page bytes are unchanged.

## 8. Testing contract

Every new subsystem should include, where applicable:

- happy path;
- invariant/property tests;
- error-path tests;
- persistence/reopen validation;
- fault/crash tests for durability work;
- end-to-end integration test.

Full regression:

```bash
python -m pytest -q
python examples/quickstart.py
python examples/transactions.py
python -m compileall -q mini_sqlite
```

Never claim a version is validated unless the exact reported tree has passed the relevant suite.

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

Every version should state its theme, delta from previous release, important source files, recommended reading order, quick-run commands, explicit non-goals, and next-version rationale.

## 10. Historical branch rule

A frozen version branch may receive only documentation corrections, tests clarifying promised behavior, and narrowly scoped bug fixes within that version boundary. Do not backport future subsystems.

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

Do not obscure page/tree/transaction invariants for premature micro-optimization.

## 12. Generated artifacts and dependencies

Do not commit database files, journals, caches, logs, generated plots, or build artifacts unless a tiny deterministic fixture is explicitly required by tests. Keep the engine standard-library-first; development-only test/lint dependencies are acceptable.

## 13. Definition of Done for a version

A version can be frozen only when the primary mental model is explicit, promised implementation is complete, unit/invariant/error/crash tests pass where relevant, an educational example exists, `version.md` records the delta, branch-specific `Agents.md` exists, architecture/format docs are updated, package imports cleanly, the final branch tree is validated, and the integrated state is restored to `main`.

## 14. Current main directive

`main` contains the completed **v0.2 rollback-journal transaction milestone**.

The next version should be **v0.3: Secondary Indexes + Richer Planner**.

Central question:

> How can a secondary index provide a different ordered access path while INSERT/DELETE and crash recovery keep table and index state atomically consistent?
