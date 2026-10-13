# Transactions and rollback journal — v0.2

v0.2 answers one question: **how can a page-oriented database avoid becoming half-written when a process crashes?**

## Transaction boundary

By default each mutating SQL statement is an autocommit transaction:

```text
INSERT
  ↓
BEGIN internally
  ↓
run VM / modify cached pages
  ↓
fsync rollback journal
  ↓
flush + fsync database file
  ↓
delete journal  ← commit point
```

Explicit transactions group statements:

```sql
BEGIN;
INSERT INTO accounts VALUES (1, 'A');
INSERT INTO accounts VALUES (2, 'B');
COMMIT;
```

`ROLLBACK` restores all pre-transaction pages.

## Before-image rule

When an existing page is modified for the first time in a transaction:

```text
old page P
   ↓
append (P, checksum, old 4096 bytes) to mini.db-journal
   ↓
modify cached page P
```

A page is journaled only once. Repeated writes do not append repeated old images.

Pages allocated after `BEGIN` have no old image. The journal header stores the database's original page count, so rollback/recovery simply truncates the file to that size.

## Journal file

Header:

```text
magic                8 bytes   MSQLJNL2
version              u16
header_size          u16
page_size            u32
original_page_count  u64
reserved             8 bytes
```

Each entry:

```text
page_id              u64
crc32                u32
reserved             u32
page_image           page_size bytes
```

The checksum catches corrupted complete entries. A torn trailing entry is ignored: database pages cannot be flushed until the preceding journal content has been fsynced.

## Commit ordering

The ordering is the important part:

```text
1. journal fsync
2. database dirty-page writes
3. database fsync
4. delete journal
```

The journal's deletion is the commit point.

Crash before step 4:

```text
journal still exists
      ↓
startup detects hot journal
      ↓
restore before-images
      ↓
truncate newly allocated pages
      ↓
fsync database
      ↓
delete journal
```

Crash after step 4 means the transaction committed.

## Why B+Tree does not know about transactions

The layering remains:

```text
B+Tree
  ↓ logical page read/write
Pager
  ├─ cache
  ├─ rollback journal
  └─ database file
```

This matters for future v0.6 WAL. B+Tree should not be rewritten when the durability mechanism changes.

## v0.2 simplifications

- one process / one connection is assumed
- no file locking yet
- no nested transactions or savepoints
- an execution-time error aborts the whole explicit transaction
- no concurrent readers/writers
- no WAL
- read-only autocommit SELECT does not create a journal

These are deliberate release boundaries.

## v0.6 comparison: WAL mode

v0.2 rollback mode remains supported and remains the default. v0.6 adds an explicit alternative:

```python
Database("demo.db", journal_mode="wal")
```

The models differ deliberately:

```text
rollback journal                     WAL
----------------                     ---
before-images                         after-images
main DB updated before commit         main DB may lag after commit
journal deletion = commit point       WAL fsync after COMMIT = commit point
crash => undo                         reopen => overlay committed frames
```

See `docs/WAL.md` for the v0.6 byte format, recovery rules, and checkpoint ordering.
