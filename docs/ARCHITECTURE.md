# Architecture

## 1. Current vertical slice

```text
Database.execute(sql)
        ↓
Parser -> AST -> Planner -> Plan -> Compiler -> VM
                                                    │
                       ┌────────────────────────────┴─────────────────────┐
                       ▼                                                  ▼
                 Table Cursor                                       Index Cursor
                       │                                                  │
                       ▼                                                  ▼
              integer-key B+Tree                                  byte-key B+Tree
                       └────────────────────────┬─────────────────────────┘
                                                ▼
                                              Pager
                                                │
                                                ▼
                                        Buffer Manager
                                     frames / pin / LRU-Clock
                                                │
                         ┌──────────────────────┴───────────────────────┐
                         ▼                                              ▼
                  rollback mode                                    WAL mode
            before-image journal                            committed after-images
                         │                                              │
                         ▼                                              ▼
                  database file                             overlay / checkpoint
                                                                        │
                                                                        ▼
                                                                 database file
```

Parser, Planner, VM and B+Trees never read or write OS files directly.

## 2. v0.7 boundary

v0.7 changes page residency, not SQL semantics or disk page formats.

```text
B+Tree asks for page N
        ↓
Pager logical-page API
        ↓
Buffer Manager decides residency
        ↓
Pager decides durable source / writeback legality
```

The replacement policy does not know what a rollback journal or WAL is.

## 3. Page read path

```text
page id
  ↓
resident frame?
  ├─ yes -> hit
  └─ no  -> miss
             ↓
        capacity full?
          ├─ no
          └─ yes -> LRU/CLOCK victim
                       ↓
                 Pager can evict?
                       ↓
                 Pager writeback if dirty
             ↓
       Pager logical loader
          ├─ WAL overlay
          └─ database page
             ↓
       install new frame
```

## 4. Pinning

Pager exposes an explicit pin lifetime for operations whose page buffer must survive additional page fetches:

```text
pin -> use across nested fetches -> unpin
```

Pinned frames are never replacement candidates. Current synchronous node decoders that consume page bytes immediately may use transient reads without pinning.

## 5. Dirty pages + rollback journal

Rollback mode can evict dirty pages inside a transaction:

```text
before-image captured
      ↓
journal sync before DB write
      ↓
dirty frame writeback
      ↓
eviction
```

Rollback can still restore the old page because durability no longer depends on the frame remaining in RAM.

## 6. Dirty pages + WAL

WAL mode deliberately blocks eviction of uncommitted dirty frames:

```text
active WAL tx dirty frame
        ↓
   non-evictable
```

After COMMIT, WAL is durable, frames become clean, and replacement may discard them. A later miss reloads from the committed WAL overlay.

## 7. Checkpoint independence

Checkpoint reads the WAL's committed newest-page map and writes the database file. It does not depend on which pages happen to be resident in the buffer pool.

## 8. Cross-version layering invariant

```text
v0.1  pages + primary B+Tree + SQL/VM
v0.2  rollback-journal durability
v0.3  secondary index access path
v0.4  relational row-processing stages
v0.5  two-source JOIN composition
v0.6  alternative WAL durability below Pager
v0.7  bounded page residency between Pager API and durable sources
```

Each version adds one mechanism at the narrowest useful boundary instead of replacing earlier layers.
