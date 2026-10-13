# Current integrated state — v1.2

`main` contains the validated **v1.2 Free-list Page Reuse + Incremental VACUUM** engine.

## Integrated capability

```text
SQL / Parser / AST
        ↓
Cost-Based Planner ← ANALYZE
        ↓
Compiler / VM → relational operators / JOIN
        ↓
Table + Secondary-Index B+Trees
        ↓
Pager
 ┌──────┼──────────────┐
 ↓      ↓              ↓
Buffer  Free-list      Rollback/WAL
Pool    reuse/trim     durability
        ↓
   database file
```

Concurrency includes process-local locks plus POSIX `flock`. Lifecycle tooling includes integrity checking, REINDEX, full VACUUM, incremental VACUUM and EXPLAIN ANALYZE.

## v1.2 additions

- metadata format v2 with persistent `free_list_head`;
- `MSQLFREE` linked free-page format;
- transactional `free_page()`;
- `allocate_page()` reuses free pages before extending the file;
- REINDEX returns old index-tree pages to the free-list;
- integrity checker validates free-list ownership/cycles/pointers;
- `.freelist` and `FREE` page inspection;
- `incremental_vacuum(max_pages)` for free file-tail suffixes;
- rollback crash recovery after physical tail truncation;
- WAL logical shrink followed by checkpoint physical truncate;
- format-v1 read/upgrade path.

## Validation

The frozen `v1.2` branch passed the exact GitHub CI matrix on Python 3.10 and 3.12 with 122 tests, all smoke examples through `examples/freelist.py`, and compileall.

## Next

`v1.3 — Range Index Scan + Composite Index`

The next dominant question is how an ordered secondary-index structure supports `< <= > >=` ranges and multi-column keys, and how the cost-based planner decides when those access paths beat a table scan.
