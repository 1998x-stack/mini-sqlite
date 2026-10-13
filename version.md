# Current integrated state — v0.6

`main` currently contains the validated **v0.6 WAL** implementation on top of the v0.1 page/B+Tree/SQL/VM, v0.2 rollback-journal transactions, v0.3 secondary indexes, v0.4 relational execution, and v0.5 JOIN foundations.

## Integrated architecture

```text
SQL → Parser / AST → Planner → Compiler / VM
                                  │
                         relational ops / JOIN
                                  ↓
                       table/index B+Trees
                                  ↓
                                Pager
              ┌───────────────────┴───────────────────┐
              ▼                                       ▼
       rollback journal                              WAL
       before-images                     committed after-image frames
              │                              + read overlay
              ▼                                       │
        database file                              checkpoint
                                                      │
                                                      ▼
                                                database file
```

## Current capabilities

- persistent 4 KiB page file and slotted B+Trees;
- tokenizer/parser/AST/planner/tiny VM;
- CREATE TABLE/INDEX, INSERT/SELECT/DELETE/UPDATE;
- rollback-journal BEGIN/COMMIT/ROLLBACK and crash recovery;
- secondary-index equality paths and atomic table/index maintenance;
- comparisons, ORDER BY, LIMIT, scalar aggregates;
- INNER JOIN, aliases, qualified names, self-join;
- plain, primary-key indexed, and secondary-index indexed nested loops;
- explicit `journal_mode="rollback" | "wal"`;
- WAL page after-image frames + transaction COMMIT boundaries;
- CRC validation and torn/uncommitted-tail recovery;
- newest committed WAL frame overlay on reads;
- WAL page creation beyond main-file EOF;
- explicit crash-safe checkpoint;
- deterministic WAL → rollback mode switch by checkpoint;
- `.txn`, `.wal`, `.checkpoint`, page/tree/index/plan/bytecode inspection.

## Recommended reading order for the latest mechanism

1. `docs/TRANSACTIONS.md`
2. `docs/WAL.md`
3. `mini_sqlite/storage/wal.py`
4. `mini_sqlite/storage/pager.py`
5. `tests/test_wal.py`
6. `examples/wal.py`

For query/index/JOIN mechanics, read `docs/RELATIONAL_ENGINE.md`, `docs/INDEXES.md`, and `docs/JOINS.md`.

## Validation commands

```bash
python -m pytest -q
python examples/quickstart.py
python examples/transactions.py
python examples/indexes.py
python examples/relational.py
python examples/joins.py
python examples/wal.py
python -m compileall -q mini_sqlite
```

## Next

See `Plan.md`: **v0.7 Bounded Buffer Manager** — replace the hidden unbounded page cache with explicit capacity, pin/unpin semantics, replacement policy, eviction/writeback invariants, and observable hit/miss/eviction metrics while preserving both rollback and WAL durability rules.
