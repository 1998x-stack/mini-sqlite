# Current integrated state — v0.5

`main` currently contains the validated **v0.5 INNER JOIN + indexed nested-loop** implementation on top of the v0.1 page/B+Tree/SQL/VM, v0.2 rollback-journal transaction, v0.3 secondary-index, and v0.4 relational-execution foundations.

## Integrated architecture

```text
SQL → AST → Planner
          │
          ├─ single source: PRIMARY_KEY / SECONDARY_INDEX / TABLE_SCAN
          ├─ JOIN inner:    PK seek / index seek / table scan
          └─ filter / sort / aggregate-project / limit metadata
                               ↓
                         Compiler → VM
                               ↓
outer source → inner lookup/scan → JOIN
                               ↓
filter → sort → aggregate/project → limit → emit
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
- `ORDER BY ... ASC/DESC`, `LIMIT`, scalar `COUNT/SUM/MIN/MAX`;
- transactional maintenance of every secondary index during writes;
- `JOIN` / `INNER JOIN` for one two-table join per SELECT;
- table aliases and qualified column references;
- ambiguity detection for unqualified names;
- self-join with distinct aliases;
- plain nested-loop join;
- primary-key indexed nested-loop join;
- secondary-index indexed nested-loop join with duplicate inner matches;
- explicit JOIN opcodes `SEEK_PK_FROM_COLUMN`, `SEEK_INDEX_FROM_COLUMN`, `FILTER_JOIN_EQ`, `COLLECT_JOIN_ROW`;
- JOIN rows reuse v0.4 filter/sort/aggregate/project/limit stages;
- schema/page/tree/index/plan/bytecode/transaction inspection commands.

## Recommended reading order for the latest mechanism

1. `docs/JOINS.md`
2. `mini_sqlite/sql/ast.py`
3. `mini_sqlite/sql/parser.py`
4. `mini_sqlite/planner/plan.py`
5. `mini_sqlite/planner/planner.py`
6. `mini_sqlite/vm/compiler.py`
7. `mini_sqlite/vm/opcode.py`
8. `mini_sqlite/vm/vm.py`
9. `tests/test_joins.py`
10. `examples/joins.py`

For earlier mechanisms, read `docs/TRANSACTIONS.md`, `docs/INDEXES.md`, and `docs/RELATIONAL_ENGINE.md`.

## Validation commands

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

v0.5 introduces no on-disk format change. Existing database pages, catalog metadata, secondary-index pages, and rollback journal remain v0.4-compatible.

## Next

See `Plan.md`: **v0.6 WAL** — an educational after-image write-ahead log, committed-frame read overlay, crash recovery, inspection, and checkpointing below the unchanged B+Tree/query layers.
