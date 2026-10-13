# Compatibility through v1.2

v1.2 is the first mini-sqlite release to bump the main database metadata version from 1 to 2.

- v1.2 reads format-v1 databases.
- New databases use format 2.
- A v1 database is upgraded in memory on open and becomes format 2 when metadata/free-list state is next persisted.
- v1.1 and earlier reject format 2 rather than silently clearing the free-list pointer.

Unchanged binary layouts: 4 KiB pages, table/catalog B+Tree nodes, secondary-index nodes, row records, rollback journal, WAL and v1.1 POSIX lock sidecars.

The new format-v2 field is page-0 offset 20: `free_list_head`. Free pages use the `MSQLFREE` header documented in `ON_DISK_FORMAT.md`.
