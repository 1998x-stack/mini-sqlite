# Current integrated state — v0.2

`main` currently contains the validated **v0.2 rollback-journal transaction** implementation on top of the v0.1 page/B+Tree/SQL/VM vertical slice.

## Integrated architecture

```text
SQL → AST → Plan → Bytecode → VM → B+Tree → Pager
                                            ├─ rollback journal
                                            └─ database file
```

## Current capabilities

- persistent 4 KiB page file;
- slotted B+Tree leaf/internal pages and splits;
- persistent catalog;
- tokenizer/parser/AST/planner/tiny VM;
- `CREATE`, `INSERT`, `SELECT`, `DELETE`;
- primary-key seek vs table scan;
- explicit and autocommit transactions;
- before-image rollback journal;
- hot-journal crash recovery;
- rollback of new pages via truncation;
- inspection commands for schema/pages/tree/plan/bytecode/transaction state.

## Reading order

For storage/query basics, read v0.1 layers first. For the newest mechanism, read:

1. `docs/TRANSACTIONS.md`
2. `mini_sqlite/storage/journal.py`
3. `mini_sqlite/storage/pager.py`
4. `mini_sqlite/transaction/manager.py`
5. `mini_sqlite/database.py`
6. `tests/test_transactions.py`

## Validation commands

```bash
python -m pytest -q
python examples/quickstart.py
python examples/transactions.py
python -m compileall -q mini_sqlite
```

## Next

See `Plan.md`: **v0.3 Secondary Indexes + Richer Planner**.
