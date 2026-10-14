# Current integrated state — v1.3

`main` contains the validated **v1.3 Ordered Range Scans + Composite Indexes** engine tree.

## Integrated capability spine

```text
SQL / Parser / AST
        ↓
Cost-Based Planner ← ANALYZE statistics
        ↓
Compiler / Tiny VM
        ↓
Relational pipeline / JOIN
        ↓
Ordered table + secondary-index B+Trees
        ↓
Buffer / Pager / Transactions
        ↓
rollback journal OR WAL
        ↓
process-local + cross-process locking
        ↓
database file

Lifecycle:
 integrity · REINDEX · VACUUM · EXPLAIN ANALYZE
 free-list reuse · incremental VACUUM

v1.3 ordered-index path:
 equality prefix → optional range → rowid lookup → residual filter
```

## v1.3 additions

- `<`, `<=`, `>`, `>=`, `BETWEEN`, and conjunctions with `AND`;
- `ByteKeyBTree.scan_range(lower, upper)` over half-open ordered intervals;
- composite `CREATE INDEX idx ON t(a, b, ...)`;
- lexicographically ordered self-delimiting composite keys with trailing rowid;
- SQL left-prefix planning: zero or more equality keys plus at most one following range key;
- `SEEK_INDEX_RANGE` VM execution;
- NULL-safe ordered bounds;
- ANALYZE-based broad-range scan vs selective-range index decisions;
- composite-index maintenance across INSERT / UPDATE / DELETE / REINDEX / VACUUM / integrity checking;
- main-file format version 3 for composite-index catalog semantics.

## Validation

The frozen `v1.3` branch passed the exact GitHub Actions matrix on Python 3.10 and 3.12, including the full test suite, all historical smoke examples, the ordered-range example, and package compilation.

## Recommended v1.3 reading path

1. `docs/ORDERED_INDEXES.md`
2. `mini_sqlite/index/key_codec.py`
3. `mini_sqlite/index/btree.py`
4. `mini_sqlite/index/secondary.py`
5. `mini_sqlite/planner/indexing.py`
6. `mini_sqlite/planner/optimizer.py`
7. `mini_sqlite/vm/compiler.py`
8. `tests/test_range_composite.py`
9. `examples/range_indexes.py`

## Next

```text
v1.4 — Savepoints
```

Goal: partial rollback boundaries inside one transaction (`SAVEPOINT`, `ROLLBACK TO`, `RELEASE`) while preserving page-allocation/free-list and rollback/WAL correctness.
