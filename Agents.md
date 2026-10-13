# Agents.md — mini-sqlite v1.2 Development Contract

> Frozen learning snapshot. Read this file before changing page allocation, free-list metadata, truncation, durability, integrity, tests, or documentation.

## 1. Version mission

v1.2 adds one dominant mental model:

> **A page has an owner lifecycle: owned → free → reused or physically reclaimed.**

The existing SQL, optimizer, locking, rollback-journal, WAL, and buffer-pool layers remain. v1.2 introduces explicit page deallocation and space reuse below B+Trees.

## 2. Mandatory reading order

1. `Agents.md`
2. `version.md`
3. `docs/FREELIST.md`
4. `docs/ON_DISK_FORMAT.md`
5. `mini_sqlite/storage/freelist.py`
6. `mini_sqlite/storage/pager.py`
7. `mini_sqlite/catalog/catalog.py`
8. `mini_sqlite/maintenance/database.py`
9. `mini_sqlite/maintenance/integrity.py`
10. `tests/test_freelist.py`
11. `examples/freelist.py`
12. `docs/TRANSACTIONS.md` and `docs/WAL.md`

## 3. Branch boundary

This branch is the frozen **v1.2 free-list + incremental-vacuum milestone**.

Do not backport v1.3 range/composite indexes, savepoints, hash/merge join, or MVCC.

## 4. Layering invariant

```text
Catalog / future tree maintenance
        │ page no longer owned
        ▼
Pager.free_page()
        ↓
persistent singly-linked free-list
        ↓
Pager.allocate_page()
        ├─ reuse free head
        └─ extend file
        ↓
rollback journal OR WAL

free tail pages
        ↓
Pager.trim_free_tail()
        ↓
Database.incremental_vacuum()
```

B+Trees and indexes must not parse free-page bytes. Pager owns allocation/deallocation. Page 0 owns the persistent head pointer via a callback injected by Database.

## 5. Free-list invariants

- page 0 is never free;
- every free page starts with `MSQLFREE` and stores exactly one next-page pointer;
- `0` terminates the chain;
- no free-list cycles;
- every free-list page id is `< logical page_count`;
- a page cannot simultaneously belong to a tree and the free-list;
- allocation prefers the free-list head before extending the file;
- reusing/freeing a page requires an active transaction;
- rollback restores both page bytes and the original free-list head;
- WAL publishes free-list changes only at COMMIT;
- valid free pages are not integrity-check orphans.

## 6. Incremental-vacuum invariants

- only consecutive free pages at the logical file tail may be truncated;
- live pages are never moved;
- `max_pages` limits one invocation without changing correctness;
- rollback mode journals every tail free page that may physically disappear before deleting the journal;
- WAL mode commits a smaller logical page count, then checkpoint performs physical truncation;
- WAL incremental vacuum obtains checkpoint-level exclusion so old readers cannot race physical shrink;
- failure before commit leaves the original logical page count visible.

## 7. Format invariant

v1.2 promotes the database metadata format from **1 → 2**.

Page 0 keeps the same 24-byte structure, but the final `u32` is now `free_list_head` instead of reserved. v1.2 reads format 1 and upgrades in memory; the first metadata/free-list persistence writes format 2. Older v1.1 engines must reject v2 instead of silently destroying space metadata.

Table/catalog/index page bytes, row records, rollback-journal bytes, and WAL bytes are unchanged.

## 8. Cross-process invariant

v1.1 POSIX locking remains authoritative. Incremental vacuum requires rollback EXCLUSIVE or WAL checkpoint-level exclusion. Free-list mutation itself does not introduce new lock files.

## 9. Testing contract

Run:

```bash
python -m pytest -q
python examples/freelist.py
python examples/cross_process.py
python -m compileall -q mini_sqlite
```

Changes to free-list/truncation logic must include rollback, WAL, reopen, corruption, page-reuse, and crash-window tests.

## 10. Definition of done

A v1.2 change is complete only when:

1. reachable pages, free pages, and orphan pages are disjoint;
2. page reuse does not increase file size unnecessarily;
3. rollback/WAL restore or publish ownership atomically;
4. incremental vacuum never truncates a live page;
5. crash recovery restores a file truncated before rollback-journal deletion;
6. format-v1 databases still open and can upgrade deliberately;
7. exact branch-head CI is green on supported Python versions;
8. docs match the actual on-disk and transaction ordering.
