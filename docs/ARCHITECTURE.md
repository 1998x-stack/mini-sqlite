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
     Planner ───────────── access path + relational stages
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

## 2. Storage remains unchanged in v0.4

v0.4 does not introduce a new on-disk format. It retains:

- page 0 database metadata;
- INTEGER-key table/catalog B+Tree pages;
- byte-key secondary-index B+Tree pages;
- JSON catalog records containing table/index metadata;
- rollback-journal before-images.

The architectural change is above storage: richer planning and relational row processing.

## 3. Catalog and root ownership

A `TableSchema` persists table root, columns, and secondary indexes. Root movement can occur in catalog, table, or index trees. Tree callbacks persist the new root in the owning metadata.

UPDATE may increase row size enough to cause a table split and may also mutate/split secondary indexes. Those root changes are ordinary Pager writes and remain rollback-safe.

## 4. Planner

v0.4 keeps three physical access paths:

```text
PRIMARY_KEY
SECONDARY_INDEX
TABLE_SCAN
```

Only equality predicates can use PK/secondary-index seeks. Other comparisons scan.

The SELECT plan also carries relational processing metadata:

```text
where predicate
order specification
projection
aggregate specifications
limit
```

This separates **where rows come from** from **how rows are transformed**.

## 5. VM relational working set

v0.4 adds:

```text
FILTER_COMPARE
COLLECT_ROW
SORT_ROWS
PROJECT_ROWS
AGGREGATE_ROWS
LIMIT_ROWS
EMIT_ROWS
UPDATE_CURRENT
```

Source cursors still navigate B+Trees. `COLLECT_ROW` materializes decoded rows into a working set; later opcodes transform it.

The working-set design is intentionally simple and inspectable. It is not presented as a production execution strategy.

## 6. UPDATE composition

`UPDATE_CURRENT` owns logical row replacement, but not durability policy:

```text
remove old index entries
        ↓
replace table record
        ↓
insert new index entries
        ↓
Pager transaction commits all participating pages
```

If any step fails, the v0.2 transaction manager rolls back the active transaction. B+Trees still know nothing about COMMIT/ROLLBACK.

## 7. Cross-version layering invariant

```text
v0.1  pages + primary B+Tree + SQL/VM
v0.2  Pager rollback journal
v0.3  secondary index access path
v0.4  relational row-processing stages
```

Each version adds a mechanism at the narrowest useful boundary instead of replacing earlier layers.
