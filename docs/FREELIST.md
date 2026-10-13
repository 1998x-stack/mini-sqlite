# v1.2 Free-list Page Reuse + Incremental VACUUM

v1.2 adds an explicit lifecycle for pages that are no longer owned by any table,
catalog, or secondary-index B+Tree.

## 1. The problem

Before v1.2, a successful `REINDEX` built a new index tree and updated the catalog,
but the old index pages simply became unreachable:

```text
old index pages
      ↓
no owner
      ↓
orphan pages
      ↓
file keeps growing
      ↓
full VACUUM required
```

This is correct but incomplete page lifecycle management.

v1.2 changes the lifecycle to:

```text
owned page
    ↓ owner replacement / future deallocation
free_page(page_id)
    ↓
persistent free-list
    ↓
allocate_page()
    ├─ free-list non-empty → reuse head page
    └─ empty → extend file

free pages reach logical file tail
    ↓
incremental_vacuum()
    ↓
truncate only consecutive free tail pages
```

## 2. Layering

```text
Catalog / future tree deallocation
        │
        │ page lost its owner
        ▼
Pager.free_page(page_id)
        │
        ├─ write FREE page header
        ├─ link to previous head
        └─ update page-0 free_list_head callback
        ▼
transaction durability
  ├─ rollback journal
  └─ WAL
```

Pager owns allocation/deallocation. Catalog only decides when an old index tree no
longer owns pages. B+Trees do not parse free-list metadata.

## 3. Main-file format v2

Page 0 still uses the original 24-byte metadata header:

```text
magic             8 bytes  MSQLITE1
format_version    u16      now 2
page_size         u16
catalog_root      u32
next_table_id     u32
free_list_head    u32      previously reserved
```

A free page begins with:

```text
magic       8 bytes  MSQLFREE
next_page   u32
reserved    20 bytes zero
rest         zero
```

`0` means end-of-list. Page 0 itself can never be free.

v1.2 can read format-v1 databases. The in-memory metadata is upgraded to v2 and
format 2 is persisted when later metadata/free-list mutation writes page 0. Old
v1.1 engines reject format-v2 metadata instead of silently discarding the free-list
head.

## 4. Allocation

`Pager.allocate_page()` now follows:

```text
free_list_head != 0 ?
        │
      yes
        ↓
decode MSQLFREE page
        ↓
head = free.next_page
        ↓
overwrite page with zero page
        ↓
return reused page id

otherwise
        ↓
page_id = page_count
page_count += 1
```

Reusing a free page is a normal transaction mutation. The old free-page bytes and
page-0 head update therefore participate in rollback/WAL exactly like table pages.

## 5. Freeing pages

`Pager.free_page(page_id)` requires an active transaction:

```text
before:
head → A → B → 0

free_page(X)

X.next = head
head = X

result:
head → X → A → B → 0
```

v1.2 uses this immediately in `REINDEX`: after the new index root is persisted in
the catalog, every page in the old index tree is returned to the free-list inside
the same transaction.

Atomicity therefore includes both ownership directions:

```text
new index tree reachable
+
old tree pages free
```

or after rollback:

```text
old index tree reachable
+
new pages discarded/reverted
+
original free-list restored
```

## 6. Incremental VACUUM

Incremental vacuum does **not** move live pages. It only truncates free pages that
already form a consecutive suffix of the file:

```text
page ids:  0 1 2 3 4 5 6 7 8 9
state:     M L L L F L L F F F
                         └─────┘
                         reclaimable tail
```

After:

```text
page ids:  0 1 2 3 4 5 6
state:     M L L L F L L
```

The interior free page 4 remains reusable but cannot shrink the file without moving
page 5/6. That is intentionally left to full `VACUUM`.

`incremental_vacuum(N)` reclaims at most `N` tail pages per call.

## 7. Rollback-journal safety

For rollback mode, truncating a file is itself a destructive write. Before commit,
v1.2 journals every free tail page that will disappear plus any free-list/meta pages
whose links change:

```text
journal before-images fsync
        ↓
metadata/free-list writeback
        ↓
database fsync
        ↓
physical truncate
        ↓
database fsync
        ↓
delete journal
```

If the process dies after truncate but before journal deletion, hot-journal recovery
rewrites the free tail page images and restores the original page count.

## 8. WAL safety

WAL does not truncate the main file at transaction commit:

```text
free-list/meta after-images
        +
smaller logical page_count
        ↓
WAL COMMIT
```

The new logical snapshot simply ignores pages at or above that committed page count.
`checkpoint()` later copies committed frames and truncates the main DB to the smaller
count. `Database.incremental_vacuum()` acquires checkpoint-level exclusion first so
physical shrinking cannot race an older reader snapshot.

## 9. Integrity checking

The integrity checker treats free pages as a fourth ownership class:

```text
meta
catalog/table trees
secondary-index trees
free-list
```

A page referenced by both a tree and free-list is corruption. A free-list cycle,
out-of-range pointer, or invalid `MSQLFREE` header is corruption. Valid free pages
are not reported as orphan pages.

## 10. What v1.2 intentionally does not do

- table/index delete merge or rebalance;
- automatic freeing of empty B+Tree pages after DELETE;
- moving live pages during incremental vacuum;
- background vacuum;
- multiple free-list trunks or bitmap allocation;
- production-grade space maps.

Those would obscure the central v1.2 lesson: explicit ownership transfer and safe
reuse of fixed-size pages.
