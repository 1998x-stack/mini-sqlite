# Write-Ahead Log — v0.6

v0.6 answers one question:

> How can committed page changes become durable without immediately overwriting the main database file?

## Rollback journal vs WAL

Rollback mode stores **before-images**:

```text
old page -> journal fsync -> overwrite DB -> DB fsync -> delete journal
```

WAL mode stores **after-images**:

```text
new page image -> WAL frame(s) -> COMMIT record -> WAL fsync
```

The main database may lag behind the newest committed logical state until checkpoint.

## WAL file format

Sidecar path: `mini.db-wal`.

Header:

```text
magic         8 bytes   MSQLWAL1
version       u16       1
header_size   u16
page_size     u32
reserved      8 bytes
```

Every record begins with:

```text
kind          u8        FRAME=1 / COMMIT=2
padding       7 bytes
transaction   u64
arg           u64
payload_len   u32
aux           u32
```

FRAME:

```text
arg           = target page id
payload_len   = page size
aux           = crc32(page image)
payload       = full page after-image
```

COMMIT:

```text
arg           = committed logical page count
payload_len   = 0
aux           = number of FRAME records in this transaction
```

Only a complete transaction whose frames are followed by a valid COMMIT record becomes visible.

## Write path

```text
BEGIN
  ↓
B+Tree writes cached pages
  ↓
Pager tracks dirty page ids
  ↓
COMMIT
  ↓
append full after-images
  ↓
append COMMIT(page_count, frame_count)
  ↓
flush + fsync WAL
  ↓
mark cache pages committed
```

Uncommitted dirty pages never overwrite the main DB in WAL mode.

## Read overlay

```text
get_page(N)
   ↓
cache hit?
   ├─ yes -> cached bytes
   └─ no
       ↓
committed WAL frame for N?
   ├─ yes -> newest frame bytes
   └─ no  -> main database bytes
```

Catalog, table B+Tree, index B+Tree, VM and JOIN stay unaware of where bytes came from.

## Rollback before COMMIT

WAL frames are emitted only at commit in this educational version. Pager stores in-memory before-images for existing pages so explicit ROLLBACK restores the local view; pages allocated after BEGIN disappear by restoring the original logical page count.

A process crash before commit loses private memory only.

## Crash recovery

On open, only complete committed prefixes are installed:

```text
committed tx1
committed tx2
FRAME tx3
FRAME tx3
<crash before COMMIT>
```

Recovery exposes tx1 + tx2, ignores tx3, and truncates the invalid/uncommitted tail to the last committed boundary. The newest committed frame for each page wins.

## Checkpoint

```text
WAL overlay pages
      ↓
write main database pages
      ↓
truncate/extend to committed logical page count
      ↓
flush + fsync database
      ↓
reset WAL to header
```

The WAL is retained until database fsync succeeds. A crash after copying only some pages is therefore safe: reopen still overlays every committed frame.

## Mode switch

Opening a WAL-backed database using rollback mode checkpoints committed WAL frames first and then removes the WAL sidecar. This keeps the single-connection educational API deterministic.

## Inspection

```python
with Database("demo.db", journal_mode="wal") as db:
    print(db.wal_status())
    copied = db.checkpoint()
```

CLI:

```text
mini-sqlite --journal-mode wal demo.db
.wal
.checkpoint
.txn
```

## Deliberate simplifications

No concurrent readers/writers, `-shm`, wal-index shared memory, snapshot isolation, automatic checkpoint scheduling, writer locks, or SQLite binary compatibility.
