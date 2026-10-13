# mini-sqlite v1.0.0 — Educationally Complete

v1.0 closes the core learning loop built from v0.1 through v0.9. It adds integrity checking, index repair, physical compaction, and estimated-vs-actual execution diagnostics without changing existing database file/journal/WAL formats.

## Primary mental model

```text
build structures
      ↓
execute queries
      ↓
make them durable
      ↓
coordinate connections
      ↓
inspect correctness
      ↓
repair derived indexes
      ↓
compact unreachable pages
```

## New capabilities

- `Database.integrity_check()` / `.integrity`;
- structural validation for catalog/table/index B+Trees;
- table-row and secondary-index cross-checking;
- stale statistics + orphan page diagnostics;
- `Database.reindex()` / `.reindex [INDEX]`;
- transaction-safe index rebuild;
- `Database.vacuum()` / `.vacuum`;
- compact logical rewrite + atomic same-filesystem replace;
- WAL checkpoint before WAL-mode rewrite;
- `Database.explain_analyze()` / `.explain-analyze SQL`;
- estimated plan + actual rows/time/buffer deltas + bytecode;
- final learning path, compatibility matrix, fault matrix, and lifecycle example;
- optional plan/cache microbenchmark.

## Compatibility

No on-disk binary format changes from v0.9. VACUUM may assign different physical page ids because it rebuilds B+Trees, but logical schema/data/index definitions are preserved.

## Important files

```text
mini_sqlite/maintenance/integrity.py
mini_sqlite/maintenance/diagnostics.py
mini_sqlite/database.py
mini_sqlite/catalog/catalog.py
mini_sqlite/cli/shell.py

tests/test_maintenance.py
examples/lifecycle.py
examples/benchmark.py

docs/MAINTENANCE.md
docs/LEARNING_PATH.md
docs/COMPATIBILITY.md
docs/FAULT_MATRIX.md
```

## Validation

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
python examples/concurrency.py
python examples/lifecycle.py
python -m compileall -q mini_sqlite
```

## Stable limits

The engine remains educational: no SQLite binary compatibility, cross-process production locking, MVCC, multi-writer WAL, savepoints, free-list reuse, online VACUUM, or production-calibrated optimizer.
