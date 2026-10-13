# mini-sqlite Roadmap

## Completed learning spine

```text
v0.1  Page / Pager / B+Tree / SQL / VM
v0.2  Rollback Journal / Transaction / Recovery
v0.3  Secondary Index
v0.4  Relational Execution
v0.5  JOIN
v0.6  WAL
v0.7  Bounded Buffer Manager
v0.8  Cost-Based Optimizer
v0.9  Process-local Concurrency / Locking
v1.0  Integrity / REINDEX / VACUUM / Diagnostics
v1.1  Cross-process File Locking
v1.2  Free-list Page Reuse + Incremental VACUUM      ← current
```

## v1.2 — Free-list Page Reuse + Incremental VACUUM

Dominant question:

> When a tree stops owning a page, how can the database reuse or reclaim it without weakening transactions or crash recovery?

Deliverables:

- metadata format v2 with persistent `free_list_head`;
- `MSQLFREE` page format;
- transactional `Pager.free_page()`;
- `allocate_page()` reuses free pages before extending the file;
- successful REINDEX frees the old index tree;
- free-list integrity/ownership validation;
- `.freelist` and `FREE` page inspection;
- `incremental_vacuum(max_pages)` for consecutive free tail pages;
- rollback-journal truncation recovery;
- WAL logical shrink + checkpoint physical truncate;
- v1-format read/upgrade path;
- dedicated tests, example, and format documentation.

## v1.3 — Range Index Scan + Composite Index

Dominant question:

> Once indexes are durable and space-managed, how does the planner exploit ordered keys beyond exact equality?

Planned work:

- lower-bound / upper-bound index cursor;
- `< <= > >= BETWEEN` index access paths;
- multi-column index metadata;
- lexicographic composite key codec;
- left-prefix matching rules;
- planner candidate/cost integration;
- ORDER BY avoidance when index order already satisfies output;
- explain diagnostics and tests.

## Later extensions

```text
v1.4  Savepoints
v1.5  Hash Join / Merge Join
v2.0  MVCC experiment
```

These remain optional extensions beyond the educationally-complete v1.0 core.
