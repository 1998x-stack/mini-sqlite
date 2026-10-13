# mini-sqlite v0.6

## Theme

**Write-Ahead Logging through committed page after-images, read overlay, and checkpoint.**

v0.2 taught rollback with old page images. v0.6 adds the complementary model:

```text
rollback journal: old page -> main DB may be overwritten -> undo on crash
WAL:              new page -> append log first          -> replay/overlay on reopen
```

## Delta from v0.5

Added:

- `Database(..., journal_mode="rollback" | "wal")`;
- documented WAL file format;
- physical page after-image frames;
- transaction COMMIT records;
- CRC validation and tail-bound checks;
- newest-committed-frame read overlay;
- WAL-safe in-memory rollback for active transactions;
- committed WAL reconstruction across reopen;
- torn/uncommitted-tail truncation;
- explicit checkpoint to main database;
- crash-safe partial-checkpoint behavior while WAL remains;
- WAL -> rollback mode switching through checkpoint;
- `.wal` and `.checkpoint` shell commands;
- `docs/WAL.md`, `examples/wal.py`, `tests/test_wal.py`.

## Important source files

- `mini_sqlite/storage/wal.py`
- `mini_sqlite/storage/pager.py`
- `mini_sqlite/transaction/manager.py`
- `mini_sqlite/database.py`
- `mini_sqlite/cli/shell.py`
- `tests/test_wal.py`
- `docs/WAL.md`

## Recommended reading order

1. `docs/TRANSACTIONS.md`
2. `docs/WAL.md`
3. `storage/wal.py`
4. `storage/pager.py`
5. `transaction/manager.py`
6. `tests/test_wal.py`
7. `examples/wal.py`

## Validation

```bash
python -m pytest -q
python examples/quickstart.py
python examples/transactions.py
python examples/indexes.py
python examples/relational.py
python examples/joins.py
python examples/wal.py
python -m compileall -q mini_sqlite
```

## Storage compatibility

The main database page layout is unchanged from v0.5. v0.6 adds a new sidecar protocol, `<database>-wal`. It is intentionally **not binary-compatible with SQLite WAL**.

## Explicit non-goals

No concurrent connections, multi-writer locking, SQLite `-shm`, reader snapshots, automatic checkpoint scheduling, WAL index shared memory, production SQLite WAL compatibility, bounded buffer replacement, or cost-based optimization.

## Next

v0.7 should add a **bounded buffer manager** so page caching becomes an explicit resource-management problem: capacity, pin/unpin, hit/miss accounting, dirty eviction, and LRU/Clock replacement.
