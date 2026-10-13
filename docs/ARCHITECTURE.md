# Architecture through v1.2

```text
SQL → Parser/AST → Cost Planner → Compiler/VM → Relational operators
                                              ↓
                                  Table / Index B+Trees
                                              ↓
                                            Pager
                       ┌──────────────────────┼──────────────────────┐
                       ↓                      ↓                      ↓
                 Buffer Manager        Free-list allocator   Durability policy
                                      free/reuse/trim        rollback or WAL
                                              ↓                      ↓
                                           database file / sidecars
```

v1.2 adds a space-management path below B+Trees. Catalog decides when an old index tree loses ownership; Pager alone owns page allocation/deallocation. B+Trees never parse free-page bytes. Page 0 persists the free-list head through a callback injected by the Database layer.

Page states are now explicit:

```text
owned → free_page() → FREE → allocate_page() → owned
                         └→ tail free suffix → incremental vacuum → absent
```

Integrity checking treats meta, trees and free-list as disjoint ownership classes.
