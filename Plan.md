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
v1.2  Free-list Page Reuse + Incremental VACUUM
v1.3  Range Index Scan + Composite Index            ← current
```

## v1.3 — Range Index Scan + Composite Index

Dominant question:

> How does a B+Tree exploit key order for ranges and multi-column predicates instead of only exact equality?

Delivered:

- ordered `ByteKeyBTree.scan_range(lower, upper)` using half-open byte intervals;
- `KeyCodec.prefix_successor()` for inclusive SQL upper bounds;
- `<`, `<=`, `>`, `>=`, `BETWEEN`, and conjunctions with `AND`;
- composite `CREATE INDEX idx ON t(a, b, ...)` metadata and physical keys;
- left-prefix matching: zero or more equality keys followed by at most one range key;
- `SEEK_INDEX_RANGE` VM opcode and materialized ordered index cursor;
- residual predicate filtering for conditions not consumed by the index probe;
- composite index maintenance across INSERT / UPDATE / DELETE / REINDEX / VACUUM;
- range selectivity and scan-vs-index decisions after ANALYZE;
- format version 3 compatibility boundary for composite-index catalog semantics;
- integrity validation for composite physical keys;
- dedicated tests, example, docs, and CI smoke.

Deferred deliberately:

- OR / NOT / parenthesized boolean expression trees;
- descending index key declarations;
- index-only scans / covering indexes;
- ORDER BY elimination from index order;
- skip-scan when the leftmost composite key is unconstrained.

## v1.4 — Savepoints

Dominant question:

> How can a transaction partially roll back without discarding all work since BEGIN?

Planned work:

- `SAVEPOINT name`, `ROLLBACK TO name`, `RELEASE name`;
- nested transaction markers without pretending nested COMMITs exist;
- rollback-journal/WAL interaction;
- page-allocation/free-list restoration at savepoint boundaries;
- lock semantics and failure tests.

## Later extensions

```text
v1.5  Hash Join / Merge Join + wider join enumeration
v1.6  Covering indexes / ORDER BY avoidance
v2.0  MVCC experiment
```
