# mini-sqlite on-disk format through v1.2

Page size remains 4096 bytes. v1.2 changes only page-0 metadata semantics and adds a free-page header; table/index pages, rows, rollback journal and WAL record layouts are unchanged.

## Page 0 metadata

The 24-byte header remains `<8sHHIII>`:

| Offset | Type | Meaning |
|---:|---|---|
| 0 | 8 bytes | `MSQLITE1` |
| 8 | u16 | format version |
| 10 | u16 | page size |
| 12 | u32 | catalog root page |
| 16 | u32 | next table id |
| 20 | u32 | v1: reserved; v2: `free_list_head` |

Format v2 uses `0` for an empty free-list. v1.2 can decode v1 and upgrades metadata in memory; once new metadata/free-list semantics are persisted, page 0 is written as format 2. Older v1.1 engines reject format 2.

## Free page

A free page starts with:

```text
0x00  8 bytes  MSQLFREE
0x08  u32      next free page id
0x0c  20 bytes reserved zero
0x20  ...      zero-filled remainder
```

Page 0 can never be free. `next_page=0` terminates the singly linked list.

## Transaction compatibility

Rollback-journal bytes are unchanged. During incremental vacuum every disappearing free tail page is journaled before physical truncate so hot-journal recovery can reconstruct the original file length.

WAL bytes are unchanged. The existing COMMIT logical `page_count` field carries shrink semantics: v1.2 may commit a smaller logical page count, and checkpoint later truncates the main file accordingly.
