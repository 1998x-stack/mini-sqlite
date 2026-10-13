# mini-sqlite — Architecture-Driven Development Plan

## Completed core track

```text
v0.1  Pages / Pager / primary B+Tree / SQL -> VM                 ✅
v0.2  Rollback journal / transactions / crash recovery           ✅
v0.3  Secondary indexes / richer access paths                    ✅
v0.4  Relational execution / UPDATE / sort / aggregate           ✅
v0.5  INNER JOIN / indexed nested loop                           ✅
v0.6  WAL / committed overlay / checkpoint                       ✅
v0.7  Bounded buffer manager / LRU / CLOCK                       ✅
v0.8  ANALYZE / statistics / cost-based optimizer                ✅
v0.9  Multi-connection concurrency / locks / snapshots           ✅
v1.0  Integrity / REINDEX / VACUUM / end-to-end diagnostics      ✅
```

## v1.0 completion criterion

A learner can now follow and inspect one coherent lifecycle:

```text
SQL
 ↓
parse / bind
 ↓
plan + cost
 ↓
bytecode / execution
 ↓
row / index B+Trees
 ↓
buffer pool
 ↓
rollback or WAL durability
 ↓
connection locks / snapshots
 ↓
integrity check / reindex / vacuum
```

v1.0 adds no new on-disk page/journal/WAL format. Its dominant mental model is **database lifecycle completeness**: build data structures, execute them, recover them, inspect them, detect inconsistency, repair derived structures, and compact abandoned pages.

## Stable v1.0 non-goals

- SQLite file/API parity;
- cross-process OS locking;
- MVCC or multi-writer WAL;
- free-list page reuse;
- online/incremental VACUUM;
- savepoints;
- hash/merge joins;
- production cost calibration;
- query parallelism.

## Optional post-1.0 extension track

These are intentionally outside the educationally-complete core and should each become a separate branch if pursued:

```text
v1.1  Cross-process file locking + lock-byte protocol
v1.2  Free-list page reuse + incremental vacuum
v1.3  Range index scans + composite indexes
v1.4  Savepoints / nested rollback scopes
v1.5  Hash Join / Merge Join + broader join enumeration
v2.0  MVCC experiment
```

The v1.0 branch should remain frozen except for narrowly scoped defects and documentation corrections.

## Version protocol

```text
read Agents.md / Plan.md / version.md
        ↓
create vX.Y from newest validated main
        ↓
implement one dominant mental model
        ↓
tests + example + docs
        ↓
exact version branch-head CI green
        ↓
freeze branch
        ↓
integrate same validated engine tree into main
        ↓
restore canonical main docs
```
