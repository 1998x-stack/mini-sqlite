# Agents.md — mini-sqlite v0.2 Development Contract

> **Frozen learning snapshot.** Read this file before changing v0.2 code, tests, documentation, or durability behavior.

## 1. Version mission

v0.2 adds one dominant mental model to the v0.1 engine:

> **Atomicity comes from ordering durable writes, not from merely having a `COMMIT` keyword.**

Architecture:

```text
SQL → AST → Plan → Bytecode → VM → B+Tree
                                  ↓
                                Pager
                           ┌───────┴────────┐
                           ↓                ↓
                   rollback journal    database file
```

The B+Tree must remain unaware of journal internals.

## 2. Mandatory reading order

1. `Agents.md`
2. `version.md`
3. `docs/TRANSACTIONS.md`
4. `docs/ARCHITECTURE.md`
5. `docs/ON_DISK_FORMAT.md`
6. `tests/test_transactions.py`
7. `storage/journal.py`
8. `storage/pager.py`
9. `transaction/manager.py`
10. `database.py`

## 3. Branch boundary

This branch is the frozen **v0.2 transaction milestone**. Allowed changes are documentation fixes, tests clarifying v0.2 promises, and narrowly scoped defects within rollback-journal semantics.

Do not backport v0.3 secondary indexes, v0.4 relational operators, WAL, locking, or later-version features.

## 4. Core architecture rules

- SQL syntax must not perform physical I/O.
- Planner must not know journal mechanics.
- VM executes plans; it does not call OS file primitives.
- B+Tree obtains and writes pages only through Pager.
- Pager owns write ordering and physical durability protocol.
- TransactionManager owns connection-level transaction state.
- Catalog/schema state is persisted and must roll back with pages.

## 5. Rollback-journal invariants

For each pre-existing page, capture exactly one before-image before its first transaction-local mutation. New pages need no before-image because rollback truncates to the transaction's original page count.

Commit ordering is:

```text
journal fsync
   ↓
database page writes
   ↓
database fsync
   ↓
journal delete  ← commit point
```

A surviving journal at startup is treated as hot and recovery restores before-images before normal metadata is read.

## 6. Failure policy

v0.2 deliberately has no savepoints. An execution-time error during an explicit transaction aborts and rolls back the whole transaction. Connection close also rolls back an unfinished explicit transaction.

## 7. Testing contract

Run:

```bash
python -m pytest -q
python examples/quickstart.py
python examples/transactions.py
python -m compileall -q mini_sqlite
```

Transaction changes require tests for normal commit, explicit rollback, autocommit, hot-journal recovery after dirty pages reach the main file, B+Tree split rollback/truncation, catalog/meta rollback, and corrupted/torn journal behavior where relevant.

## 8. Definition of Done

A v0.2-compatible change is complete only when crash atomicity remains explainable, B+Tree APIs stay durability-agnostic, tests validate reopen/recovery boundaries, docs match exact write ordering, and v0.1 regression behavior stays green.
