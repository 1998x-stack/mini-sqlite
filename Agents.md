# Agents.md — mini-sqlite v0.3 Development Contract

> **Frozen learning snapshot.** Read this file before changing v0.3 code, tests, documentation, index semantics, or planner behavior.

## 1. Version mission

v0.3 adds one dominant mental model to the v0.2 engine:

> **A secondary index is a second ordered structure that maps a search key to rowids, and every table mutation must keep both structures transactionally consistent.**

```text
                         Catalog
                      /           \
                 table meta      index meta
                      |              |
SQL → Planner → AccessPath         Index B+Tree
                 /      \              |
          table scan   index seek ── rowid
                                ↓
                           table B+Tree
                                ↓
                              Pager
                       rollback journal
```

## 2. Mandatory reading order

1. `Agents.md`
2. `version.md`
3. `docs/INDEXES.md`
4. `docs/ARCHITECTURE.md`
5. `docs/ON_DISK_FORMAT.md`
6. `tests/test_indexes.py`
7. `mini_sqlite/index/key_codec.py`
8. `mini_sqlite/index/node.py`
9. `mini_sqlite/index/btree.py`
10. `mini_sqlite/index/secondary.py`
11. `mini_sqlite/catalog/`
12. `mini_sqlite/planner/`
13. `mini_sqlite/vm/`

## 3. Branch boundary

This branch is the frozen **v0.3 secondary-index milestone**. Allowed changes are documentation fixes, tests clarifying v0.3 promises, and narrowly scoped defects inside the v0.3 boundary.

Do not backport v0.4 relational operators, JOIN, WAL, buffer replacement, cost-based optimization, or locking.

## 4. Index invariants

- table rows remain keyed by the INTEGER PRIMARY KEY in the original table B+Tree;
- a secondary index is a distinct page-backed B+Tree;
- physical secondary keys are `(encoded indexed value, rowid)` so duplicate SQL values remain unique in the tree;
- index lookup yields rowids, then VM explicitly returns to the table B+Tree;
- index metadata is persisted in `TableSchema.indexes`;
- index root page changes must be persisted in the catalog;
- index creation indexes rows that already exist;
- INSERT and DELETE must update table and every affected index in one v0.2 transaction;
- rollback/crash recovery must restore both table and index pages atomically;
- Planner performs no physical I/O.

## 5. Planner rule

For an equality predicate, access-path priority is:

```text
PRIMARY_KEY
    ↓
SECONDARY_INDEX
    ↓
TABLE_SCAN
```

v0.3 is rule based. Do not introduce a cost model on this branch.

## 6. Testing contract

Run:

```bash
python -m pytest -q
python examples/quickstart.py
python examples/transactions.py
python examples/indexes.py
python -m compileall -q mini_sqlite
```

Index changes require tests for duplicate secondary values, TEXT key delimiting, index build over existing rows, root split/reopen, planner path choice, INSERT/DELETE maintenance, explicit rollback, hot-journal crash recovery, and low-level byte-key tree behavior.

## 7. On-disk rule

v0.3 adds additive page node types `3=INDEX_LEAF` and `4=INDEX_INTERNAL`; existing table page layouts remain unchanged. `TableSchema` JSON gains an optional `indexes` field. v0.3 can decode v0.1/v0.2 table metadata that lacks this field.

Older writers must not modify a database after v0.3 indexes have been created because they do not maintain those indexes.

## 8. Definition of Done

A v0.3-compatible change is complete only when the index remains visibly separate from the table, duplicate-key semantics remain `(value,rowid)`, planner choice is explainable, root changes survive reopen, table/index mutations remain crash-atomic through the existing Pager journal, and all v0.1/v0.2 regression behavior stays green.
