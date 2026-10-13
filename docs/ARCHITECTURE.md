# Architecture

## 1. Current vertical slice

```text
Database.execute(sql)
        ↓
Parser -> AST -> Planner -> Plan -> Compiler -> Instruction[] -> VM
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
                         ┌───────────────────────┴───────────────────────┐
                         ▼                                               ▼
                  rollback mode                                     WAL mode
            before-image journal                             committed after-images
                         │                                               │
                         ▼                                               ▼
                  database file                              read overlay / checkpoint
                                                                         │
                                                                         ▼
                                                                  database file
```

Parser, Planner, VM and B+Trees never read or write OS files directly. Pager is the durability boundary.

## 2. Query layers remain unchanged in v0.6

v0.6 changes no SQL semantics, row layout, B+Tree page format, catalog encoding, index key format, or JOIN algorithm. It adds a second durability policy below those mechanisms.

That boundary is the core lesson:

```text
query meaning
   ↓
logical page operations
   ↓
Pager durability policy
```

## 3. Rollback mode

v0.2 before-image flow remains available and is still the default:

```text
capture old page
      ↓
fsync rollback journal
      ↓
write DB page
      ↓
fsync DB
      ↓
delete journal
```

## 4. WAL mode

v0.6 changes commit ordering:

```text
cached new page versions
      ↓
append FRAME after-images
      ↓
append transaction COMMIT record
      ↓
fsync WAL
      ↓
logical commit visible
```

The main DB is not required to contain the newest committed version until checkpoint.

## 5. Pager read overlay

```text
page id
  ↓
cache?
  ├─ yes -> cache
  └─ no
       ↓
latest committed WAL frame?
  ├─ yes -> WAL bytes
  └─ no  -> main DB bytes
```

Table/index/catalog code therefore needs no WAL-specific branches.

## 6. Checkpoint

```text
WAL newest-page map
       ↓
copy to main DB
       ↓
set committed logical file length
       ↓
fsync DB
       ↓
reset WAL
```

Keeping WAL until DB fsync makes a partial-checkpoint crash recoverable: the WAL still overlays the complete committed state.

## 7. Logical vs physical page count

In WAL mode, committed frames may describe pages beyond the current main-file EOF. Pager therefore distinguishes:

```text
physical database page count
logical committed page count
```

The logical count may be larger until checkpoint extends the main file.

## 8. Cross-version layering invariant

```text
v0.1  pages + primary B+Tree + SQL/VM
v0.2  rollback-journal durability
v0.3  secondary index access path
v0.4  relational row-processing stages
v0.5  two-source JOIN composition
v0.6  alternative WAL durability below Pager
```

Each version adds a mechanism at the narrowest useful boundary instead of replacing earlier layers.
