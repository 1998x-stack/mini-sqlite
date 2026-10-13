# Agents.md — mini-sqlite v0.6 Development Contract

> **Frozen learning snapshot.** Read this file before changing v0.6 code, tests, documentation, or durability semantics.

## 1. Version mission

v0.6 adds one dominant mental model:

> **WAL stores committed after-images outside the main database; Pager reconstructs the newest logical page view until checkpoint folds those frames back.**

```text
write transaction
      ↓
dirty cached pages
      ↓
append page after-images
      ↓
append COMMIT boundary
      ↓
fsync WAL
      ↓
committed logical view
```

## 2. Mandatory reading order

1. `Agents.md`
2. `version.md`
3. `docs/WAL.md`
4. `docs/TRANSACTIONS.md`
5. `docs/ARCHITECTURE.md`
6. `tests/test_wal.py`
7. `mini_sqlite/storage/wal.py`
8. `mini_sqlite/storage/pager.py`
9. `mini_sqlite/transaction/manager.py`
10. `mini_sqlite/database.py`
11. `examples/wal.py`

## 3. Branch boundary

This branch is the frozen **v0.6 WAL milestone**. Allowed changes are documentation corrections, tests clarifying promised behavior, and narrowly scoped durability defects inside v0.6 semantics.

Do not backport v0.7 bounded-cache replacement, v0.8 cost optimization, v0.9 concurrency/locking, SQLite `-shm`, snapshot isolation, or multi-writer WAL coordination.

## 4. Durability modes

```python
Database("demo.db")
Database("demo.db", journal_mode="wal")
```

```text
rollback
  before-image journal
  commit = database fsync + journal deletion

wal
  after-image frames
  commit = WAL frames + COMMIT record + WAL fsync
  checkpoint = WAL -> database file
```

Do not silently mix their ordering rules.

## 5. WAL invariants

- uncommitted dirty pages never overwrite the main database file;
- a WAL frame is visible only if followed by a valid transaction COMMIT record;
- reads prefer the newest committed WAL frame over the database page;
- a torn/uncommitted WAL tail is ignored and truncated on reopen;
- checkpoint keeps WAL intact until copied pages and the database file are fsynced;
- only after successful database fsync may checkpoint reset the WAL;
- page creation beyond database EOF is represented by committed WAL frames plus committed logical page count;
- B+Trees/catalog/indexes/JOINs do not know whether bytes came from DB or WAL.

## 6. Mode switching

Opening a database in rollback mode when a committed WAL exists first checkpoints committed WAL state into the main database and removes the WAL. This is an educational single-connection mode switch, not SQLite-compatible shared WAL coordination.

## 7. Testing contract

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

Coverage must include committed reopen, uncommitted crash, complete uncommitted-frame tail, torn tail, multiple commits/newest overlay, checkpoint, partial-checkpoint crash, page creation/root splits, index/JOIN reuse, mode switching, and full older-version regression.

## 8. Definition of Done

A v0.6-compatible change is complete only when rollback mode remains green, WAL commit/checkpoint/recovery ordering is inspectable, query/storage semantics are unchanged above Pager, all durability fault tests pass, docs match the exact byte protocol, and the exact final `v0.6` branch-head CI passes.
