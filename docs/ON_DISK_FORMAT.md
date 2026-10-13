# mini-sqlite database on-disk format (v0.1–v0.8)

This is an educational format and is **not SQLite-compatible**. All existing table-page and metadata integers are little-endian unless explicitly noted by the index key codec.

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

Table B+Tree and secondary-index B+Tree pages share this 32-byte header with node type, flags, cell count, parent, right sibling, first child, free-start, content-start, reserved bytes, then a cell-pointer array.

Node types:

```text
1 TABLE/CATALOG LEAF
2 TABLE/CATALOG INTERNAL
3 SECONDARY INDEX LEAF
4 SECONDARY INDEX INTERNAL
```

Table/catalog leaf cells use `i64 key + u32 value length + value bytes`; internal cells use `i64 separator key + u32 right child`.

Secondary-index leaf cells use `u16 key length + u32 value length + key bytes + value bytes`; internal cells use `u16 key length + u32 right child + key bytes`.

Logical secondary-index keys are `KeyCodec.encode_value(indexed_value) + KeyCodec.encode_rowid(rowid)`.

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

`TableSchema` JSON adds optional index metadata. v0.3 accepts older catalog records where `indexes` is absent. Existing v0.1/v0.2 table B+Tree byte layouts are unchanged.

## Rollback journal and WAL

The v0.2 rollback journal stores before-images. The v0.6 `<database>-wal` sidecar stores full-page after-image FRAME records followed by transaction COMMIT records. v0.7 changes only in-memory residency, not either file format.

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
