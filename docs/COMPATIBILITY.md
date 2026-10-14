# Compatibility and Format Boundaries

mini-sqlite is not SQLite file-format compatible. Compatibility here means **between mini-sqlite milestones**.

## Stable main-file format

The main database format introduced in v0.1 remains the base through v1.1:

- 4 KiB fixed pages;
- page 0 metadata;
- integer-key table/catalog B+Trees;
- typed self-describing row records.

v0.3 adds secondary-index page node types and catalog JSON fields. Older catalog JSON without `indexes` remains readable by later versions.

v0.8 adds optional statistics fields to catalog JSON. Missing statistics remain valid and trigger rule-based fallback planning.

## Durability sidecars

### Rollback journal

v0.2 format remains unchanged through v1.0. v0.9 changed **when** a journal is created (lazy first write), not its bytes.

### WAL

v0.6 WAL frame/commit format remains unchanged through v1.0.

## Buffer/concurrency/optimizer

v0.7 buffer management, v0.8 optimizer, and v0.9 process-local locking do not change database page bytes.

## v1.0 maintenance

`integrity_check` is read-only.

`REINDEX` creates new index pages and changes catalog root references, but no byte layout changes.

`VACUUM` rewrites a semantically equivalent database. Physical page ids/root ids may differ, which is expected. Logical tables, rows, index definitions, and statistics presence are preserved.

## Unsupported compatibility claims

- SQLite `.db` files cannot be opened by mini-sqlite;
- mini-sqlite files cannot be opened by SQLite;
- separate mini-sqlite major/minor versions are not promised to perform migrations for future incompatible formats unless a later milestone explicitly implements them.


## v1.2 format version 2

v1.2 is the first milestone to bump the main-file metadata version. Page 0 keeps
the same 24-byte structure, but its last `u32` becomes `free_list_head`. New v1.2
databases write format 2.

v1.2 can read format-1 files. It upgrades metadata in memory and writes format 2
when a later metadata/free-list mutation persists page 0. This is a deliberate
one-way write boundary: v1.1 rejects format-2 metadata rather than silently
clearing the free-list head.

Table/index page layouts, row records, rollback-journal bytes, WAL bytes, and lock
sidecar semantics remain unchanged.

## v1.3 format 3

v1.3 raises the database format version from 2 to 3 because catalog index metadata may contain an ordered `columns[]` tuple. Page-0 size/layout, table/index node bytes, record bytes, rollback journal, WAL, free-page format, and lock sidecars are unchanged.

v1.3 reads v1/v2. A composite-index creation persists v3 before publishing the new catalog entry. v1.2 engines therefore fail explicitly on v3 rather than writing a composite index as though it were single-column.
