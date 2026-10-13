# mini-sqlite v0.9.0 — Concurrency / Locking

This frozen milestone adds explicit multi-connection lock state on top of the v0.1-v0.8 page, transaction, index, relational, JOIN, WAL, buffer-pool, and optimizer foundations.

## Primary mental model

```text
Connection A              Connection B
     │                          │
 transaction / statement   transaction / statement
     │                          │
     └────── Lock Registry ─────┘
                   │
           rollback or WAL rules
                   │
                 Pager
```

## New capabilities

- multiple live `Database` instances against one path;
- process-local lock registry;
- rollback `SHARED / RESERVED / EXCLUSIVE` states;
- lazy rollback-journal creation for read-only transactions;
- one WAL writer coexisting with WAL readers;
- stable explicit WAL read snapshots;
- stale WAL read→write upgrade detection (`BusySnapshotError`);
- deterministic `BusyError` conflicts;
- configurable `busy_timeout_ms` wait/retry;
- condition-variable wakeups after release;
- connection-local Pager/buffer refresh before new snapshots;
- checkpoint waits for explicit WAL readers;
- live journal-mode conflict detection;
- crash-test liveness pruning;
- `.locks` and `Database.lock_status()` inspection.

## Compatibility

The main database file, rollback-journal format, WAL format, B+Tree layout, secondary-index layout, and optimizer-statistics encoding are unchanged. Rollback journal creation is now lazy; its byte format is unchanged.

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
python -m compileall -q mini_sqlite
```

## Explicit limits

Locking is process-local; v0.9 does not claim safe coordination between separate operating-system processes. No row locks, MVCC engine, deadlock detector, multi-writer WAL, or savepoints.

## Next

v1.0: **Educationally Complete mini SQLite** — consolidate invariants, end-to-end inspection labs, compatibility/recovery matrix, benchmark scenarios, and a final learning path across v0.1–v0.9.
