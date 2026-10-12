# Architecture

## 1. One statement, all layers

```text
Database.execute(sql)
        |
        v
      Parser
        |
        v
       AST
        |
        v
     Planner
        |
        v
       Plan
        |
        v
    Compiler
        |
        v
   Instruction[]
        |
        v
 VirtualMachine
        |
        +--> Catalog --+
        |              |
        v              v
     Cursor          Schema
        |
        v
      BTree
        |
        v
      Pager
        |
        v
    database file
```

The architecture is deliberately more layered than the absolute minimum. That is the point: it mirrors the important separations in a real database.

## 2. Page 0

Page 0 is not a B+Tree page. It stores fixed metadata:

```text
8 bytes  magic = MSQLITE1
2 bytes  format version
2 bytes  page size
4 bytes  catalog root page id
4 bytes  next table id
4 bytes  reserved
rest     zero
```

## 3. B+Tree node header

Each B+Tree node begins with 32 bytes:

```text
u8   node_type       LEAF or INTERNAL
u8   flags
u16  cell_count
u32  parent_page
u32  right_sibling   leaf chain; 0 when none
u32  first_child     internal nodes only
u16  free_start
u16  content_start
12B  reserved
```

Then comes a `u16` cell-pointer array. Cell data is packed from the end of the page backwards.

## 4. Leaf cells

```text
i64 key
u32 value_length
N B value
```

The B+Tree treats `value` as opaque bytes. Table rows are encoded by `RecordCodec`; the catalog stores JSON-encoded schema bytes. This separation is useful because the B+Tree should not know row semantics.

## 5. Internal cells

An internal node uses a left-most `first_child` plus cells:

```text
i64 separator_key
u32 right_child
```

For:

```text
first_child = A
(100, B)
(200, C)
```

routing is:

```text
key < 100       -> A
100 <= key <200 -> B
key >= 200      -> C
```

## 6. Leaf split

When a leaf no longer fits:

```text
before

[1 2 3 4 5 6]
```

becomes:

```text
left          right
[1 2 3]  ->  [4 5 6]
                ^
                separator 4 inserted into parent
```

Rows are split by approximate byte footprint, not merely row count, because records are variable length.

## 7. Internal split

For an internal node:

```text
children: c0, c1, c2, c3, c4
keys:         k1, k2, k3, k4
```

one middle separator is promoted to the parent. Children on the right half have their `parent` field rewritten to the new internal page.

## 8. Catalog root and table roots

There are two levels of root movement:

- catalog B+Tree root may split -> page 0 must be updated
- table B+Tree root may split -> that table's catalog record must be updated

This is why `BTree` accepts an `on_root_change` callback.

## 9. Row encoding

`RecordCodec` is self-describing:

```text
u16 column_count

for each column:
    u8  type_tag
    u32 byte_length

payload bytes...
```

Tags in v0.1:

```text
0 NULL
1 INTEGER (signed i64)
2 TEXT (UTF-8)
```

## 10. Planning

The planner recognizes only two access paths:

### Primary-key equality

```sql
SELECT * FROM users WHERE id = 7;
```

```text
PRIMARY_KEY
```

### Everything else

```sql
SELECT * FROM users WHERE age = 20;
```

```text
TABLE_SCAN
```

This tiny distinction is enough to demonstrate why a secondary index matters in v0.3.

## 11. VM

The VM is intentionally register-light in v0.1. Its opcodes include:

```text
CREATE_TABLE
OPEN_READ
OPEN_WRITE
REWIND
SEEK_PK
FILTER_EQ
PROJECT
RESULT_ROW
NEXT
INSERT_ROW
DELETE_CURRENT
HALT
```

The compiler emits control-flow addresses into instructions. `REWIND`, `SEEK_PK`, `FILTER_EQ`, and `NEXT` can alter the program counter.

## 12. Durability boundary

v0.1 flushes and fsyncs after a statement. This means completed page writes are durable, but a crash during a multi-page mutation can still leave partial structural changes.

v0.2 should solve this below the B+Tree with a rollback journal:

```text
BTree mutation
    ↓
Pager.write_page
    ↓
if first write to page in transaction:
    save old page to journal
    fsync journal
    mark journal ready
    write database page
```

That design keeps transaction recovery out of SQL and B+Tree logic.
