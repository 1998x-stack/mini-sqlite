# mini-sqlite database on-disk format (v0.1–v0.3)

This is an educational format and is **not SQLite-compatible**.

All existing table-page and metadata integers are little-endian unless explicitly noted by the index key codec.

## Database page size

`4096` bytes.

## Page 0: database metadata

| Offset | Size | Field |
|---:|---:|---|
| 0 | 8 | magic `MSQLITE1` |
| 8 | 2 | format version |
| 10 | 2 | page size |
| 12 | 4 | catalog root page |
| 16 | 4 | next table id |
| 20 | 4 | reserved |
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
