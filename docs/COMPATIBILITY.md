# Compatibility and Format Boundaries

mini-sqlite is not SQLite file-format compatible. Compatibility here means **between mini-sqlite milestones**.

## Stable main-file format

The main database format introduced in v0.1 remains the base through v1.0:

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
