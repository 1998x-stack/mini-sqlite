# mini-sqlite v0.1

## Theme

**Storage engine + SQL-to-VM vertical slice.**

v0.1 makes one complete query path inspectable:

```text
SQL → Parser → AST → Planner → Bytecode → VM → B+Tree → Pager → file
```

## Important source files

- `mini_sqlite/storage/pager.py` — fixed-size page I/O/cache
- `mini_sqlite/storage/record.py` — typed row serialization
- `mini_sqlite/btree/btree.py` — persistent B+Tree and splits
- `mini_sqlite/catalog/catalog.py` — persisted schema
- `mini_sqlite/sql/parser.py` — SQL → AST
- `mini_sqlite/planner/planner.py` — scan vs primary-key seek
- `mini_sqlite/vm/compiler.py` — plan → bytecode
- `mini_sqlite/vm/vm.py` — bytecode execution

## Recommended reading order

1. `storage/record.py`
2. `storage/pager.py`
3. `btree/node.py`
4. `btree/btree.py`
5. `catalog/`
6. `sql/`
7. `planner/`
8. `vm/`
9. `database.py`

## Validation

Run:

```bash
python -m pytest -q
python examples/quickstart.py
```

## Non-goals

No rollback journal, WAL, secondary indexes, joins, aggregates, page rebalancing after delete, concurrency, or SQLite file-format compatibility.

## Next

v0.2 adds **rollback-journal transactions and crash recovery** without teaching the B+Tree about durability protocol internals.
