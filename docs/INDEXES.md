# Secondary indexes in mini-sqlite v0.3

## 1. Why a second B+Tree exists

A table B+Tree is ordered by the INTEGER PRIMARY KEY:

```text
users table
1 -> (1, Alice, 20)
2 -> (2, Bob,   25)
3 -> (3, Carol, 20)
```

Without another structure, `WHERE age = 20` must inspect every row. After:

```sql
CREATE INDEX idx_users_age ON users(age);
```

v0.3 builds another B+Tree whose logical entries are:

```text
(20, 1) -> rowid 1
(20, 3) -> rowid 3
(25, 2) -> rowid 2
```

The rowid is part of the physical key. That is how non-unique SQL values become unique ordered B+Tree entries without an in-memory posting list.

## 2. Key encoding

`KeyCodec` converts a typed SQL value into a byte prefix. The rowid is appended as an ordered signed-64-bit encoding:

```text
encode(age=20) || encode(rowid=1)
encode(age=20) || encode(rowid=3)
```

INTEGER encodings flip the signed domain into unsigned big-endian order. TEXT uses UTF-8 with escaped NUL bytes and an explicit terminator, so `'a'` is not mistaken for the prefix of `'ab'`.

The v0.3 planner only uses equality lookup; range semantics are intentionally deferred.

## 3. Physical index page

Index pages use the same 32-byte slotted-page header concept as table pages, but distinct node-type tags:

```text
3 = INDEX_LEAF
4 = INDEX_INTERNAL
```

Index leaf cell:

```text
u16 key_len
u32 value_len
key bytes
value bytes
```

Index internal cell:

```text
u16 key_len
u32 right_child
key bytes
```

The byte-key B+Tree supports search, insert, delete, full scan, prefix scan, leaf split, internal split, and root split.

## 4. Equality lookup

For:

```sql
SELECT name FROM users WHERE age = 20;
```

bytecode is conceptually:

```text
OPEN_READ users
OPEN_INDEX idx_users_age
SEEK_INDEX_EQ 20

loop:
    INDEX_TO_TABLE
    PROJECT name
    RESULT_ROW
    INDEX_NEXT loop
HALT
```

The explicit `INDEX_TO_TABLE` step is important. A secondary index does not contain the full table row in v0.3; it produces a rowid that is used to seek the table's primary B+Tree.

## 5. Planner rule

```text
WHERE primary_key = literal
        ↓
PRIMARY_KEY

WHERE indexed_column = literal
        ↓
SECONDARY_INDEX

otherwise
        ↓
TABLE_SCAN
```

There are no statistics or cost estimates yet. Those belong to v0.8.

## 6. CREATE INDEX builds existing rows

`CREATE INDEX` does not start empty. It scans the current table, decodes each row, creates composite keys, inserts them into the new byte-key B+Tree, then persists index metadata in the table's catalog record.

Because `CREATE INDEX` is a normal write statement, all of this occurs inside v0.2 autocommit transaction semantics. A failure rolls back pages and catalog metadata together.

## 7. INSERT/DELETE atomicity

INSERT:

```text
insert table row
      ↓
insert index entry 1
      ↓
insert index entry 2 ...
      ↓
commit one Pager transaction
```

DELETE performs the inverse. If any operation fails, the existing rollback journal restores the pre-transaction images and truncates newly allocated pages.

This is the key cross-version invariant: **indexes do not invent their own durability protocol.**

## 8. Crash case

If uncommitted table and index pages have already reached the main database file and the process dies, startup finds the hot journal before reading normal metadata:

```text
hot journal
    ↓
restore table before-images
restore index before-images
truncate transaction-created pages
fsync DB
remove journal
```

After recovery, planner-visible index metadata and the physical index contents both match the restored table.

## 9. Explicit non-goals

v0.3 does not implement UNIQUE, compound indexes, range predicates, collations, covering indexes, index-only scans, partial/expression indexes, statistics, or cost-based planning.
