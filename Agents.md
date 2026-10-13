# Agents.md — mini-sqlite v0.9 Frozen Development Contract

> This branch teaches one dominant mental model: **multiple connections require explicit lock state and snapshot rules in addition to crash durability**.

## 1. Preserve the layer boundary

```text
SQL / Planner / VM / B+Trees
             ↓
          Database
             ↓
      Lock Registry
             ↓
           Pager
      ┌──────┴──────┐
   rollback        WAL
```

Do not move lock acquisition into B+Tree nodes, the optimizer, or Buffer Manager.

## 2. Scope

The registry is process-local and keyed by canonical database path. Cross-process OS locking is not part of v0.9.

## 3. Rollback invariants

- multiple SHARED readers may coexist;
- one RESERVED writer intent at a time;
- EXCLUSIVE requires no other SHARED readers;
- no reader may execute while another connection owns EXCLUSIVE;
- rollback journal is lazy and created only at first physical write/new page;
- dirty rollback pages may still evict only after journal-before-DB ordering.

## 4. WAL invariants

- multiple SHARED reader snapshots may coexist with one WAL writer;
- only one WAL writer exists;
- explicit reader snapshot does not refresh until COMMIT/ROLLBACK;
- stale reader snapshot cannot upgrade to writer after another WAL commit;
- checkpoint must not race an explicit reader snapshot or WAL writer;
- reader refresh never truncates a live partial WAL tail.

## 5. Busy contract

`busy_timeout_ms=0` fails immediately. Positive timeout waits on a condition variable and expires deterministically. Never spin indefinitely.

## 6. Cache-coherence contract

A connection refreshes its clean Pager/buffer view only when beginning a new statement/transaction snapshot under the correct connection lock. Active transactions never refresh.

## 7. Cleanup contract

COMMIT, ROLLBACK, statement failure that aborts the transaction, and CLOSE must release connection locks. Crash-simulation tests may close Pager directly; liveness pruning must make later recovery possible.

## 8. Testing contract

Keep every v0.1-v0.8 test green and cover reader-reader, reader-writer, writer-writer, timeout wake/expiry, WAL snapshot isolation, stale upgrade, checkpoint conflict, error cleanup, mixed journal modes, and recovery.

## 9. Validation

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

## 10. Non-goals

No OS cross-process locks, row/predicate locks, deadlock detector, MVCC, savepoints, distributed locking, or multi-writer WAL.

## 11. Definition of Done

The exact final v0.9 branch-head must pass all tests and examples on CI, lock transitions must be inspectable, conflicts deterministic, WAL/rollback behavior distinct and documented, old durability tests must remain green, and no on-disk format may change accidentally.
