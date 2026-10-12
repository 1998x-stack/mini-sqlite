# v0.1 on-disk format

This file documents the educational format. It is **not** SQLite-compatible.

All multi-byte numbers are little-endian.

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

## B+Tree page header

| Offset | Size | Field |
|---:|---:|---|
| 0 | 1 | node type (`1=LEAF`, `2=INTERNAL`) |
| 1 | 1 | flags |
| 2 | 2 | cell count |
| 4 | 4 | parent page |
| 8 | 4 | right sibling |
| 12 | 4 | first child |
| 16 | 2 | free-start offset |
| 18 | 2 | content-start offset |
| 20 | 12 | reserved |
| 32 | 2*N | cell pointer array |

A pointer is an absolute offset within the page.

## Leaf cell

```text
i64 key
u32 value length
value bytes
```

## Internal cell

```text
i64 separator key
u32 right child page id
```

## Record value

```text
u16 column_count
repeated column_count times:
    u8  type_tag
    u32 payload_length
concatenated payload bytes
```

Integer payload is signed 64-bit little-endian. Text payload is UTF-8.

## Format-version policy

Any incompatible change to these layouts must increment `FORMAT_VERSION` in `mini_sqlite/constants.py`.
