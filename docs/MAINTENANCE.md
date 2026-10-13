# Maintenance through v1.2

v1.0 introduced integrity checking, REINDEX, full VACUUM and EXPLAIN ANALYZE. v1.2 connects those lifecycle operations to explicit page reuse.

## REINDEX

A replacement secondary-index tree is built transactionally. After the new root is persisted, every page in the old tree is passed to `Pager.free_page()` in the same transaction. Rollback restores the old root, old page bytes and original free-list head.

## Integrity

`integrity_check()` validates B+Tree structure, table/index agreement, page ownership and now the persistent free-list. Free-list cycles, invalid pointers, malformed `MSQLFREE` headers, and pages shared by a tree and free-list are corruption. Valid free pages are not orphans.

## Incremental VACUUM

`incremental_vacuum(max_pages=None)` only removes consecutive free pages from the logical file tail. It never moves a live page. Interior free pages stay reusable.

Rollback mode journals disappearing pages before truncate. WAL mode commits a smaller logical page count and checkpoint performs physical truncation under checkpoint-level exclusion.

CLI: `.freelist`, `.pages` (`FREE` rows), `.incremental-vacuum [N]`.
