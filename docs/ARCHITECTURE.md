# Architecture

## 1. Current vertical slice

```text
Database.execute(sql)
        │
        ▼
      Parser
        │
        ▼
       AST
        │
        ▼
     Planner ───────────── chooses AccessPath
        │
        ▼
       Plan
        │
        ▼
    Compiler
        │
        ▼
   Instruction[]
        │
        ▼
 VirtualMachine
    │          │
    │          └──────────────┐
    ▼                         ▼
Table Cursor             Index Cursor
    │                         │
    ▼                         ▼
integer-key B+Tree       byte-key B+Tree
    │                         │
    └───────────┬─────────────┘
                ▼
              Pager
         ┌──────┴──────┐
         ▼             ▼
 rollback journal   database file
```

Parser and Planner never read page bytes. Both B+Tree families use Pager; Pager remains the sole durability boundary.

## 2. Page 0

Page 0 stores fixed metadata:

```text
8 bytes  magic = MSQLITE1
2 bytes  format version
2 bytes  page size
4 bytes  catalog root page id
4 bytes  next table id
4 bytes  reserved
rest     zero
```

## 3. Table B+Tree

The original table/catalog B+Tree uses signed INTEGER keys. Node types:

```text
1 LEAF
2 INTERNAL
```

Leaf cell:

```text
i64 key
u32 value_length
value bytes
```

Internal cell:

```text
i64 separator_key
u32 right_child
```

Table values are `RecordCodec` rows. Catalog values are JSON `TableSchema` records.

## 4. Secondary-index B+Tree

v0.3 adds a separate byte-key tree. Node types:

```text
3 INDEX_LEAF
4 INDEX_INTERNAL
```

Its keys are opaque ordered bytes. `SecondaryIndex` gives those bytes SQL meaning through `KeyCodec`.

Physical key:

```text
encoded(indexed_value) || encoded(rowid)
```

The rowid suffix makes duplicate values unique and naturally orders duplicates by rowid.

## 5. Catalog ownership

A `TableSchema` persists:

```text
table_id
name
root_page
columns[]
indexes[]:
    name
    column
    root_page
    unique
```

Root movement occurs at three places:

- catalog B+Tree root split -> page 0 changes;
- table B+Tree root split -> table `root_page` changes;
- secondary-index root split -> that `IndexSchema.root_page` changes.

Each tree exposes an `on_root_change` callback so its owner persists the new root.

## 6. Planner

v0.3 access paths:

```text
PRIMARY_KEY
SECONDARY_INDEX
TABLE_SCAN
```

Priority for equality predicates is primary key first, then a matching secondary index, otherwise scan. It is rule-based by design.

## 7. VM

Important v0.3 opcodes:

```text
CREATE_TABLE
CREATE_INDEX
OPEN_READ
OPEN_WRITE
OPEN_INDEX
REWIND
SEEK_PK
SEEK_INDEX_EQ
INDEX_TO_TABLE
FILTER_EQ
PROJECT
RESULT_ROW
NEXT
INDEX_NEXT
INSERT_ROW
DELETE_CURRENT
HALT
```

`INDEX_TO_TABLE` makes secondary-index back-to-table lookup explicit rather than hiding it in planner or storage code.

## 8. Transaction composition

v0.2 already established the physical protocol:

```text
first modification to old page
        ↓
append before-image to journal
        ↓
modify page
```

v0.3 simply causes more pages to participate. Table and index mutations share the same Pager transaction and the same hot-journal recovery process.

## 9. Why there are two B+Tree implementations in v0.3

The table tree keeps the v0.1 fixed `i64` key format. The new index tree introduces variable-length byte keys without rewriting historical table storage. This makes the architectural delta visible and preserves the older learning slice. A later version may unify these behind a generic tree abstraction once the two mechanisms are understood separately.
