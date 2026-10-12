# Current integrated state — v0.3

`main` currently contains the validated **v0.3 secondary-index + richer-planner** implementation on top of the v0.1 page/B+Tree/SQL/VM and v0.2 rollback-journal transaction foundations.

## Integrated architecture

```text
SQL → AST → Planner → Bytecode → VM
                 │                ├─ table cursor → integer-key B+Tree
                 │                └─ index cursor → byte-key B+Tree → rowid → table
                 │
                 └─ PRIMARY_KEY / SECONDARY_INDEX / TABLE_SCAN
                                      ↓
                                    Pager
                              ┌───────┴───────┐
                              ▼               ▼
                     rollback journal    database file
```

## Current capabilities

- persistent 4 KiB page file;
- slotted table/catalog B+Tree and splits;
- SQL tokenizer/parser/AST/planner/tiny VM;
- `CREATE TABLE`, `INSERT`, `SELECT`, `DELETE`;
- explicit/autocommit rollback-journal transactions and hot-journal recovery;
- `CREATE INDEX name ON table(column)`;
- persisted index metadata;
- variable-length byte-key secondary-index B+Tree;
- `(indexed value, rowid)` composite physical keys with duplicate-value support;
- INTEGER/TEXT/NULL key encoding;
- index build over existing rows;
- planner choice among primary-key lookup, secondary-index lookup, and table scan;
- explicit index-to-table rowid lookup in bytecode;
- transactional INSERT/DELETE index maintenance;
- index root-split persistence;
- crash recovery covering table and index pages atomically;
- schema/page/tree/index/plan/bytecode/transaction inspection commands.

## Recommended reading order for the latest mechanism

1. `docs/INDEXES.md`
2. `mini_sqlite/index/key_codec.py`
3. `mini_sqlite/index/node.py`
4. `mini_sqlite/index/btree.py`
5. `mini_sqlite/index/secondary.py`
6. `mini_sqlite/catalog/schema.py`
7. `mini_sqlite/planner/planner.py`
8. `mini_sqlite/vm/compiler.py`
9. `mini_sqlite/vm/vm.py`
10. `tests/test_indexes.py`

For durability, read `docs/TRANSACTIONS.md` and Pager/journal code before the index atomicity tests.

## Validation commands

```bash
python -m pytest -q
python examples/quickstart.py
python examples/transactions.py
python examples/indexes.py
python -m compileall -q mini_sqlite
```

## Next

See `Plan.md`: **v0.4 Relational Execution Engine** — UPDATE, richer expressions, LIMIT, ORDER BY, aggregates, and explicit composable execution operators while preserving v0.3 access paths.
