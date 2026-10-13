# mini-sqlite v1.2.0 — Free-list Page Reuse + Incremental VACUUM

## Status

**Implemented / frozen candidate.**

v1.2 closes the fixed-page storage lifecycle: pages can now be explicitly released, persisted on a free-list, reused by later allocations, and physically truncated when free pages reach the file tail.

## Main mental model

```text
owned page
   ↓
free_page()
   ↓
persistent free-list
   ↓
allocate_page()
   ├─ reuse
   └─ extend file

free tail suffix
   ↓
incremental_vacuum()
   ↓
physical space reclaimed
```

## New capabilities

- database metadata format v2;
- page-0 `free_list_head`;
- `MSQLFREE` linked free-page format;
- transactional page deallocation;
- allocation prefers free pages;
- REINDEX returns old index-tree pages to the free-list;
- integrity checker validates free-list structure and ownership;
- `.freelist` and `FREE` page display;
- incremental tail-page vacuum with optional limit;
- rollback-journal crash-safe truncation;
- WAL logical page-count shrink + checkpoint truncate;
- read/upgrade path for format-v1 databases.

## Compatibility

v1.2 reads format-v1 mini-sqlite databases. New databases use format 2. An opened v1 database is upgraded in memory and is persisted as format 2 when metadata/free-list semantics are next written.

Unchanged:

- 4 KiB page size;
- table/catalog B+Tree page layout;
- secondary-index B+Tree page layout;
- row record encoding;
- rollback-journal format;
- WAL format;
- v1.1 lock sidecars.

## Validation target

- all v0.1–v1.1 regression tests;
- dedicated free-list/reuse/incremental-vacuum tests;
- rollback and WAL crash/reopen cases;
- format-v1 upgrade case;
- free-list smoke example;
- Python 3.10 / 3.12 exact branch-head CI;
- `compileall`.

## Next

**v1.3 — Range Index Scan + Composite Index**: turn the secondary-index layer from equality-only lookup into ordered-range access and multi-column keys, then expose those choices to the cost-based planner.
