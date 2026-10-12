# Agents.md — mini-sqlite v0.1 Development Contract

> **Frozen learning snapshot.** Read this file before changing v0.1 code, tests, documentation, or binary formats.

## 1. Version mission

v0.1 teaches the shortest complete path from SQL text to durable page-backed rows:

```text
SQL → AST → Plan → Bytecode → VM → Cursor → B+Tree → Pager → database file
```

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
SQLite conceptual mapping
      ↓
feature breadth later
```

Do not replace the page-backed storage path with Python lists/dicts.

## 2. Mandatory reading order

1. `Agents.md`
2. `version.md`
3. `README.md`
4. `docs/ARCHITECTURE.md`
5. `docs/ON_DISK_FORMAT.md`
6. subsystem tests
7. subsystem implementation

## 3. Branch boundary

This branch represents **v0.1 only**. Allowed changes are documentation corrections, tests clarifying promised behavior, and narrowly scoped bug fixes inside the v0.1 boundary.

Do not backport v0.2 rollback journals, v0.3 secondary indexes, WAL, joins, or later runtime features.

## 4. Architecture ownership

- `sql/`: syntax and AST only
- `planner/`: access-path choice; no physical I/O
- `vm/`: bytecode execution semantics
- `btree/`: ordered page-backed structure
- `storage/`: page/file encoding and I/O
- `catalog/`: persisted schema metadata

Forbidden shortcuts include Parser → Pager, Planner → OS file, or table state persisted in ordinary Python containers.

## 5. Storage invariants

- page size is fixed at 4096 bytes;
- page 0 owns database metadata;
- B+Tree pages use a slotted-page layout;
- B+Tree root page ids may change after splits;
- catalog root changes must update page 0;
- table root changes must update the table catalog record;
- incompatible binary-layout changes require `FORMAT_VERSION` changes and documentation.

## 6. Testing contract

Run:

```bash
python -m pytest -q
python examples/quickstart.py
python -m compileall -q mini_sqlite
```

Storage changes require reopen/persistence tests. B+Tree changes require forced split tests. Planner changes require access-path tests. VM changes require bytecode and execution tests.

## 7. Definition of Done

A v0.1-compatible change is complete only when the intended layer owns the behavior, tests cover mechanism boundaries, persistence is validated where relevant, docs remain accurate, and the package/example run cleanly.
