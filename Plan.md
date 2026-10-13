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
v1.1  Cross-process File Locking                     ← current
```

## v1.1 — Cross-process File Locking

Goal: make the v0.9 lock state machine real across independent Python processes without changing storage formats.

Deliverables:

- POSIX `flock` abstraction;
- MODE agreement/recovery ownership;
- rollback reader/writer/PENDING protocol;
- WAL global single writer + concurrent readers;
- checkpoint global exclusion;
- busy timeout across processes;
- crash auto-release and recovery tests;
- maintenance/VACUUM integration;
- lock observability and documentation.

## v1.2 — Free-list Page Reuse + Incremental VACUUM

Dominant question:

> When a B+Tree/index stops owning a page, must the database file grow forever until full VACUUM?

Planned work:

- persistent free-page metadata;
- page free/reuse API below B+Tree;
- index rebuild returns old pages to free-list;
- delete/merge preparation;
- free-list integrity checks;
- page allocation prefers reusable pages;
- incremental vacuum/truncation when free pages reach file tail;
- crash/rollback/WAL safety for free-list mutation;
- `.freelist` inspection.

## Later extensions

```text
v1.3  Range Index Scan + Composite Index
v1.4  Savepoints
v1.5  Hash Join / Merge Join
v2.0  MVCC experiment
```

These are extensions, not prerequisites for the v1.0 educational database core.
