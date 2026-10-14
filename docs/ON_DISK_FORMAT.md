# mini-sqlite On-Disk Format

Version 0.3 extends the v0.1/v0.2 database with secondary-index B+Tree page types and catalog metadata. v0.6 adds a separate WAL sidecar without changing database-page bytes. v0.8 adds optional planner statistics inside catalog JSON without changing page layouts. v1.2 promotes the main database metadata format to version 2 and gives the final page-0 `u32` a persistent free-list meaning.

All fixed-size database pages are **4096 bytes**.

## Page 0: database metadata

| Offset | Size | Field |
|---:|---:|---|
| 0 | 8 | magic `MSQLITE1` |
| 8 | 2 | format version |
| 10 | 2 | page size |
| 12 | 4 | catalog root page |
| 16 | 4 | next table id |
| 20 | 4 | format v1: reserved; format v2: free-list head page |
| 24 | rest | zero/reserved |

## Common slotted-page header

Table B+Tree and secondary-index B+Tree pages share this 32-byte header:

| Offset | Size | Field |
|---:|---:|---|
| 0 | 1 | node type |
| 1 | 1 | flags |
| 2 | 2 | cell count |
| 4 | 4 | parent page |
| 8 | 4 | right sibling |
| 12 | 4 | first child |
| 16 | 2 | free-start offset |
| 18 | 2 | content-start offset |
| 20 | 12 | reserved |
| 32 | 2*N | cell pointer array |

Node types:

```text
1 TABLE/CATALOG LEAF
2 TABLE/CATALOG INTERNAL
3 SECONDARY INDEX LEAF
4 SECONDARY INDEX INTERNAL
```

## Table/catalog leaf cell

```text
i64 key
u32 value length
value bytes
```

## Table/catalog internal cell

```text
i64 separator key
u32 right child page id
```

## Secondary-index leaf cell

```text
u16 key length
u32 value length
key bytes
value bytes
```

## Secondary-index internal cell

```text
u16 key length
u32 right child page id
key bytes
```

## Secondary-index key

Logical shape:

```text
KeyCodec.encode_value(indexed_value)
+
KeyCodec.encode_rowid(rowid)
```

The rowid encoding occupies the final eight bytes. INTEGER and rowid ordering uses a signed-to-unsigned bias followed by big-endian bytes so lexicographic order follows signed integer order. TEXT is UTF-8 with escaped NUL plus a terminator.

## Record value

```text
u16 column_count
repeated column_count times:
    u8  type_tag
    u32 payload_length
concatenated payload bytes
```

Integer payload is signed 64-bit little-endian. Text payload is UTF-8.

## Catalog schema extension in v0.3

`TableSchema` JSON adds optional:

```json
{"indexes":[{"name":"idx_users_age","column":"age","root_page":7,"unique":false}]}
```

v0.3 accepts older table catalog records where `indexes` is absent. Existing v0.1/v0.2 table B+Tree byte layouts are unchanged.

An older engine must not write a database after v0.3 indexes exist because it cannot maintain those indexes.

## Rollback-journal sidecar

The v0.2 rollback journal remains unchanged. Index pages participate in the same before-image protocol and transaction-created index pages are removed by truncation during rollback/recovery. See `TRANSACTIONS.md`.

## v0.6 WAL sidecar

The main database page bytes are unchanged. WAL mode adds a sidecar file `<database>-wal` with magic `MSQLWAL1`; it stores full-page after-image FRAME records followed by transaction COMMIT records. See `docs/WAL.md` for the exact record layout and checkpoint protocol.


## v0.8 optimizer metadata

The 4 KiB page format, table B+Tree cells, index B+Tree cells, rollback-journal format and WAL format are unchanged.

Catalog table-schema JSON may now contain an optional `stats` object:

```json
{
  "stats": {
    "row_count": 100,
    "columns": {
      "grp": {
        "null_count": 0,
        "distinct_count": 11,
        "min_value": 1,
        "max_value": 100,
        "most_common": [[1, 90], [91, 1]]
      }
    }
  }
}
```

Missing `stats` means "not analyzed". Older schema JSON without this field remains readable. Because statistics live inside ordinary catalog B+Tree values, they inherit the existing rollback/WAL durability protocol.


## v1.2 metadata format v2 and free pages

v1.2 raises the page-0 format version from `1` to `2`. The 24-byte metadata
header size is unchanged; the final `u32` is now the persistent `free_list_head`.
`0` means the free-list is empty. v1.2 can decode format-v1 metadata and upgrades
the in-memory metadata before later persistence.

A free page uses its own header at offset 0:

| Offset | Size | Field |
|---:|---:|---|
| 0 | 8 | magic `MSQLFREE` |
| 8 | 4 | next free page id (`0` = end) |
| 12 | 20 | reserved zero bytes |
| 32 | rest | zero |

Free pages are not table/index nodes. Reallocation overwrites the page through the
normal Pager write path before the page is handed to a B+Tree.

The rollback-journal and WAL byte formats are unchanged. Incremental vacuum uses
the existing rollback journal `original_page_count` and WAL COMMIT `page_count`
fields to make a smaller logical database size crash-safe.

## Format version 3 (v1.3)

The 4 KiB page-0 struct remains `<8sHHIII>`. Only the `version` value changes to 3. The binary page layouts are unchanged; format 3 gates catalog semantics in which an index schema can store an ordered list of key columns.

Composite secondary-index leaf keys are:

```text
encode(col_1) || encode(col_2) || ... || encode(col_n) || encode_i64(rowid)
```

Each scalar encoding is self-delimiting, so a prefix ending after any complete indexed column is a valid B+Tree search prefix.
