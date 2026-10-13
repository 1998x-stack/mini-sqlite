# mini-sqlite v0.4

## Theme

**Relational execution composition.**

v0.4 turns SELECT row processing into explicit VM stages and adds UPDATE while preserving v0.1-v0.3 storage, transaction, and index boundaries.

```text
source -> filter -> collect -> sort -> aggregate/project -> limit -> emit
```

## Delta from v0.3

Added:

- `UPDATE table SET ... [WHERE ...]`;
- predicates `= != < <= > >=`;
- `ORDER BY column [ASC|DESC]`;
- `LIMIT n`;
- `COUNT(*)`, `COUNT(column)`, `SUM`, `MIN`, `MAX`;
- explicit relational VM opcodes;
- full-row sorting before projection;
- UPDATE maintenance of all secondary indexes;
- range-predicate table-scan planning;
- UPDATE rollback/hot-journal crash tests;
- `docs/RELATIONAL_ENGINE.md` and `examples/relational.py`.

## Important source files

- `mini_sqlite/sql/ast.py`
- `mini_sqlite/sql/parser.py`
- `mini_sqlite/planner/plan.py`
- `mini_sqlite/planner/planner.py`
- `mini_sqlite/vm/compiler.py`
- `mini_sqlite/vm/vm.py`
- `tests/test_relational.py`
- `docs/RELATIONAL_ENGINE.md`

## Recommended reading order

1. v0.3 index/access-path material
2. `docs/RELATIONAL_ENGINE.md`
3. `sql/ast.py`
4. `planner/plan.py`
5. `planner/planner.py`
6. `vm/compiler.py`
7. `vm/vm.py`
8. `tests/test_relational.py`

## Validation

```bash
python -m pytest -q
python examples/quickstart.py
python examples/transactions.py
python examples/indexes.py
python examples/relational.py
python -m compileall -q mini_sqlite
```

## Explicit non-goals

No JOIN, GROUP BY/HAVING, aliases, AND/OR expression trees, full SQL NULL semantics, arithmetic UPDATE expressions, primary-key UPDATE, external sort, streaming LIMIT optimization, range index scans, WAL, or concurrency.

## Next

v0.5 should add **JOIN** as the next major relational composition mechanism.
