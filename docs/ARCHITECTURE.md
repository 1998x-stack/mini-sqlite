# mini-sqlite Architecture — v0.8

```text
SQL -> Parser -> AST -> Binder/Planner
                         │
                         ├-> Catalog statistics
                         ├-> Cardinality estimates
                         ├-> Candidate access/JOIN plans
                         └-> CostModel -> chosen physical plan
                                      ↓
                               Compiler / VM
                                      ↓
                         relational pipeline / JOIN
                                      ↓
                           table/index B+Trees
                                      ↓
                                    Pager
                                      ↓
                           Bounded Buffer Manager
                           ├-> LRU / CLOCK
                           └-> pin / dirty frames
                                      ↓
                         rollback journal or WAL
                                      ↓
                                     disk
```

The v0.8 optimizer changes plan choice only. Page layout, B+Tree structure, durability ordering and buffer-replacement correctness remain below the planner boundary. See `OPTIMIZER.md` for statistics and cost formulas.

## 1. Current vertical slice

```text
Database.execute(sql)
        ↓
Parser -> AST -> CostBasedPlanner -> Plan -> CostBasedCompiler -> VM
                                                         │
                         ┌───────────────────────────────┴────────────────────┐
                         ▼                                                    ▼
                   Table Cursor                                         Index Cursor
                         │                                                    │
                         ▼                                                    ▼
                integer-key B+Tree                                    byte-key B+Tree
                         └──────────────────────────┬─────────────────────────┘
                                                    ▼
                                                  Pager
                                                    │
                                             Buffer Manager
                                                    │
                             ┌──────────────────────┴──────────────────────┐
                             ▼                                             ▼
                      rollback mode                                    WAL mode
```

Parser, Planner, VM and B+Trees never read or write OS files directly.

## 2. Buffer/Pager boundary

```text
B+Tree asks for page N
        ↓
Pager logical-page API
        ↓
Buffer Manager decides residency
        ↓
Pager decides durable source / writeback legality
```

Replacement policy does not know what a rollback journal or WAL is.

## 3. Optimizer boundary

```text
Catalog ordinary metadata pages
          ↓
     TableStats / ColumnStats
          ↓
       CostModel
          ↓
 correct physical alternatives
          ↓
       minimum cost
```

Optimizer statistics live in catalog values, not in page-cache or B+Tree internals. A bad estimate may select a slower plan but must not change query results.

## 4. JOIN physical-order boundary

Cursor identity remains logical:

```text
cursor 0 = SQL-left
cursor 1 = SQL-right
```

`outer_side` changes loop order only. `COLLECT_JOIN_ROW` still emits logical-left followed by logical-right, preserving projections and qualified names.

## 5. Durability

ANALYZE is a catalog write and therefore follows the same rollback/WAL transaction ordering as DDL. No new durability sidecar or page type is introduced in v0.8.

## 6. Cross-version layering invariant

```text
v0.1  pages + primary B+Tree + SQL/VM
v0.2  rollback-journal durability
v0.3  secondary index access path
v0.4  relational row-processing stages
v0.5  two-source JOIN composition
v0.6  alternative WAL durability below Pager
v0.7  bounded page residency between Pager API and durable sources
v0.8  statistics + cost-based physical plan selection above execution
```

Each version adds one mechanism at the narrowest useful boundary instead of replacing earlier layers.
