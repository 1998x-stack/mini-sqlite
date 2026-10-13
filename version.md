# mini-sqlite v0.5

## Theme

**Two-source relational execution through visible JOIN algorithms.**

v0.5 keeps v0.4's post-source relational pipeline and adds an explicit second row source:

```text
outer source
    ↓
inner scan / PK seek / secondary-index seek
    ↓
INNER JOIN
    ↓
filter -> sort -> aggregate/project -> limit -> emit
```

## Delta from v0.4

Added:

- `JOIN` / `INNER JOIN`;
- one INNER JOIN per SELECT;
- table aliases with and without `AS`;
- qualified column names;
- unqualified-column ambiguity checks;
- self-join with distinct aliases;
- plain nested-loop join;
- primary-key indexed nested-loop join;
- secondary-index indexed nested-loop join;
- join-aware projection/filter/order/aggregate resolution;
- explicit VM instructions `SEEK_PK_FROM_COLUMN`, `SEEK_INDEX_FROM_COLUMN`, `FILTER_JOIN_EQ`, `COLLECT_JOIN_ROW`, `FILTER_ROWS`;
- `docs/JOINS.md`, `examples/joins.py`, and `tests/test_joins.py`.

## Important source files

- `mini_sqlite/sql/ast.py`
- `mini_sqlite/sql/tokens.py`
- `mini_sqlite/sql/tokenizer.py`
- `mini_sqlite/sql/parser.py`
- `mini_sqlite/planner/plan.py`
- `mini_sqlite/planner/planner.py`
- `mini_sqlite/vm/opcode.py`
- `mini_sqlite/vm/compiler.py`
- `mini_sqlite/vm/vm.py`
- `tests/test_joins.py`
- `docs/JOINS.md`

## Recommended reading order

1. v0.4 relational pipeline
2. `docs/JOINS.md`
3. `sql/ast.py`
4. `sql/parser.py`
5. `planner/plan.py`
6. `planner/planner.py`
7. `vm/compiler.py`
8. `vm/vm.py`
9. `tests/test_joins.py`
10. `examples/joins.py`

## Validation

```bash
python -m pytest -q
python examples/quickstart.py
python examples/transactions.py
python examples/indexes.py
python examples/relational.py
python examples/joins.py
python -m compileall -q mini_sqlite
```

## Storage compatibility

v0.5 introduces **no on-disk format change**. The database page format, catalog encoding, rollback journal, table B+Tree, and secondary-index B+Tree remain v0.4-compatible.

## Explicit non-goals

No outer joins, multiple join chains, arbitrary ON expressions, hash/merge joins, join reordering, cost model, GROUP BY/HAVING, subqueries, range index scans, WAL, or concurrency.

## Next

v0.6 should add **WAL** so the project can contrast rollback-journal durability with append-only logging and checkpointing.
