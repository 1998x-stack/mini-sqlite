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
     Planner ───────────── binding + access path + join algorithm + relational stages
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
   │          ├────────────── joined row working set
   │          │
   ▼          ▼
Table       Index Cursor
Cursor         │
   │           ▼
   ▼        byte-key B+Tree
integer-key    │
B+Tree         │
   └──────┬────┘
          ▼
        Pager
   ┌──────┴──────┐
   ▼             ▼
rollback      database
journal         file
```

Parser and Planner never read page bytes. JOIN is implemented by composing existing table/index cursors, not by adding a new storage primitive.

## 2. Storage remains unchanged in v0.5

v0.5 introduces no new page type or database-file layout. It retains:

- page 0 metadata;
- INTEGER-key table/catalog B+Tree pages;
- byte-key secondary-index B+Tree pages;
- JSON catalog table/index metadata;
- rollback-journal before-images.

Joined rows are transient VM tuples only.

## 3. Planner responsibilities

The Planner now performs four visibly separate jobs:

```text
name binding
    ↓
physical source/access selection
    ↓
JOIN inner-path selection
    ↓
post-source relational metadata
```

For a single table, access remains:

```text
PRIMARY_KEY / SECONDARY_INDEX / TABLE_SCAN
```

For v0.5 JOIN, the written left source remains outer. The right ON column selects:

```text
right primary key       -> indexed nested loop via PK seek
right secondary index   -> indexed nested loop via index seek + rowid lookup
otherwise               -> nested loop via right table scan
```

There is deliberately no cost model or join reordering yet.

## 4. Joined row representation

Two physical table records are decoded independently and combined only in VM memory:

```text
(left columns..., right columns...)
```

Planner name binding maps SQL references onto flat indexes in this transient row. Therefore v0.4 operators can be reused unchanged:

```text
FILTER_ROWS
SORT_ROWS
PROJECT_ROWS
AGGREGATE_ROWS
LIMIT_ROWS
EMIT_ROWS
```

## 5. JOIN bytecode

Plain nested loop exposes both cursor loops:

```text
REWIND left
REWIND right
FILTER_JOIN_EQ
COLLECT_JOIN_ROW
NEXT right
NEXT left
```

Primary-key indexed nested loop replaces the full inner loop with:

```text
SEEK_PK_FROM_COLUMN
COLLECT_JOIN_ROW
```

Secondary-index nested loop uses:

```text
SEEK_INDEX_FROM_COLUMN
INDEX_TO_TABLE
COLLECT_JOIN_ROW
INDEX_NEXT
```

The VM, rather than B+Tree, owns this composition.

## 6. Durability layering remains intact

JOIN is read-only. Existing write paths still use v0.2 rollback-journal transactions, and table/index maintenance from v0.3/v0.4 is unchanged.

That layering is intentional:

```text
query semantics / JOIN
        ↓
cursors / B+Trees
        ↓
Pager durability
```

v0.6 WAL should replace/extend the bottom durability mechanism without rewriting JOIN or planner semantics.

## 7. Cross-version layering invariant

```text
v0.1  pages + primary B+Tree + SQL/VM
v0.2  Pager rollback journal
v0.3  secondary index access path
v0.4  relational row-processing stages
v0.5  two-source JOIN composition
```

Each version adds a mechanism at the narrowest useful boundary instead of replacing earlier layers.
