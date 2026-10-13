# Current integrated state — v0.4

`main` currently contains the validated **v0.4 relational-execution** implementation on top of the v0.1 page/B+Tree/SQL/VM, v0.2 rollback-journal transaction, and v0.3 secondary-index foundations.

## Integrated architecture

```text
SQL → AST → Planner
          │
          ├─ PRIMARY_KEY / SECONDARY_INDEX / TABLE_SCAN
          │
          └─ filter / sort / aggregate-project / limit metadata
                               ↓
                         Compiler → VM
                               ↓
source → filter → collect → sort → aggregate/project → limit → emit
                               ↓
                 table/index B+Trees → Pager
                                      ├─ rollback journal
                                      └─ database file
```

## Current capabilities

- persistent 4 KiB page file;
- slotted table/catalog B+Tree and secondary-index B+Tree;
- tokenizer/parser/AST/planner/tiny VM;
- explicit/autocommit rollback-journal transactions and hot-journal recovery;
- `CREATE TABLE`, `CREATE INDEX`, `INSERT`, `SELECT`, `DELETE`, `UPDATE`;
- primary-key equality lookup, secondary-index equality lookup, table scan;
- predicates `= != < <= > >=`;
- explicit range-predicate fallback to table scan;
- `ORDER BY ... ASC/DESC`;
- `LIMIT`;
- `COUNT(*)`, `COUNT(column)`, `SUM`, `MIN`, `MAX` without GROUP BY;
- explicit VM stages `FILTER_COMPARE`, `COLLECT_ROW`, `SORT_ROWS`, `PROJECT_ROWS`, `AGGREGATE_ROWS`, `LIMIT_ROWS`, `EMIT_ROWS`;
- UPDATE maintenance of every secondary index in the same transaction;
- persistence, rollback, and hot-journal recovery tests for UPDATE;
- schema/page/tree/index/plan/bytecode/transaction inspection commands.

## Recommended reading order for the latest mechanism

1. `docs/RELATIONAL_ENGINE.md`
2. `mini_sqlite/sql/ast.py`
3. `mini_sqlite/sql/parser.py`
4. `mini_sqlite/planner/plan.py`
5. `mini_sqlite/planner/planner.py`
6. `mini_sqlite/vm/compiler.py`
7. `mini_sqlite/vm/vm.py`
8. `tests/test_relational.py`
9. `examples/relational.py`

For durability and index mechanics, read `docs/TRANSACTIONS.md` and `docs/INDEXES.md` first.

## Validation commands

```bash
python -m pytest -q
python examples/quickstart.py
python examples/transactions.py
python examples/indexes.py
python examples/relational.py
python -m compileall -q mini_sqlite
```

## Next

See `Plan.md`: **v0.5 JOIN** — aliases/qualified names, INNER JOIN, readable nested-loop baseline, and indexed nested-loop lookup while preserving all v0.1-v0.4 storage/durability boundaries.
