# mini-sqlite v0.2

## Theme

**Rollback-journal transactions + crash recovery.**

v0.2 keeps the v0.1 SQL/VM/B+Tree stack intact and inserts durability beneath the B+Tree at the Pager boundary.

```text
B+Tree logical page writes
          ↓
        Pager
      /       \
before-image  main DB
   journal
```

## Delta from v0.1

Added:

- `BEGIN [TRANSACTION]`;
- `COMMIT` / `END [TRANSACTION]`;
- `ROLLBACK [TRANSACTION]`;
- connection transaction state machine;
- statement autocommit for writes;
- physical before-image rollback journal;
- journal-first fsync ordering;
- hot-journal startup recovery;
- truncation of transaction-created pages;
- catalog/meta rollback;
- Python `with db.transaction():` API;
- `.txn` shell inspection;
- crash/fault-oriented transaction tests.

## Important source files

- `mini_sqlite/storage/journal.py`
- `mini_sqlite/storage/pager.py`
- `mini_sqlite/transaction/manager.py`
- `mini_sqlite/database.py`
- `tests/test_transactions.py`
- `docs/TRANSACTIONS.md`

## Recommended reading order

1. v0.1 storage/B+Tree path
2. `docs/TRANSACTIONS.md`
3. `storage/journal.py`
4. `storage/pager.py`
5. `transaction/manager.py`
6. `database.py`
7. `tests/test_transactions.py`

## Non-goals

No nested transactions/savepoints, concurrent connections, file locks, WAL, secondary indexes, statement-level rollback inside an explicit transaction, or SQLite journal compatibility.

## Next

v0.3 should add **secondary indexes + richer planner access paths** while preserving Pager/transaction boundaries.
