# Learning path

The project is meant to be read version-by-version. For v1.2 focus on one question: **what happens after a Page stops being owned?**

Recommended v1.2 order:

1. `docs/FREELIST.md` — lifecycle and invariants.
2. `docs/ON_DISK_FORMAT.md` — format v2 and `MSQLFREE`.
3. `mini_sqlite/storage/freelist.py` — free-page codec.
4. `mini_sqlite/storage/pager.py` — `free_page`, reusable `allocate_page`, tail trim, rollback/WAL ordering.
5. `mini_sqlite/catalog/catalog.py` — REINDEX ownership transfer.
6. `mini_sqlite/maintenance/integrity.py` — free-list as an ownership class.
7. `mini_sqlite/maintenance/database.py` — locking + incremental vacuum orchestration.
8. `tests/test_freelist.py` — rollback, WAL, corruption, migration and crash windows.
9. `examples/freelist.py` — observe reuse and physical shrink.

Questions to answer after reading: Why must free-list state be transactional? Why can interior free pages be reused but not physically removed? Why does rollback need before-images of pages that will be truncated? Why can WAL represent shrink before the main file is physically shorter? Why does format v2 matter for downgrade safety?
