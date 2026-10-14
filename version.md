# mini-sqlite v1.3.0 — Ordered Range Scans + Composite Indexes

## Status

**Implemented / frozen candidate.**

v1.3 makes secondary indexes truly ordered: the engine can seek a lower bound, stop at an upper bound, combine equality prefixes with a following range column, and maintain multi-column indexes transactionally.

## Main mental model

```text
SQL predicates
   ↓
left-prefix analysis
   ↓
(a = ?) (b = ?) (c range ?..?)
   ↓
ordered byte lower/upper bounds
   ↓
ByteKeyBTree.scan_range()
   ↓
rowid lookup
   ↓
residual filter
```

## New capabilities

- `AND` conjunctions and `BETWEEN`;
- `< <= > >=` secondary-index range scans;
- composite indexes `(a,b,...)`;
- lexicographic self-delimiting key tuples;
- left-prefix planner rule;
- `SEEK_INDEX_RANGE` bytecode;
- range-aware cost model after ANALYZE;
- composite-index INSERT/UPDATE/DELETE/REINDEX/VACUUM maintenance;
- integrity checking of composite physical keys;
- ordered-index example and documentation.

## Format compatibility

The main database format version is **3**.

The page-0 byte layout itself is unchanged from v1.2; format 3 marks a catalog semantic change: index metadata can contain an ordered `columns[]` tuple instead of only one column. Table/index B+Tree page layouts, row encoding, rollback-journal format, WAL format, free-page format, and lock sidecars are unchanged.

v1.3 reads format-v1 and format-v2 databases. Before a composite index becomes reachable, the engine persists page 0 as format v3. Older v1.2 engines therefore reject the database rather than silently treating `(a,b)` as index `(a)`.

## Validation target

- all v0.1–v1.2 regressions;
- dedicated range/composite-index tests;
- NULL range boundary tests;
- UPDATE/DELETE/reopen/integrity tests;
- REINDEX/VACUUM composite-index tests;
- broad-vs-selective cost-plan flip;
- Python 3.10 / 3.12 exact branch-head CI;
- 13 smoke examples and `compileall`.

## Next

**v1.4 — Savepoints**: partial rollback boundaries inside one transaction, including allocation/free-list and rollback/WAL correctness.
