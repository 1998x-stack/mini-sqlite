# mini-sqlite v0.3

## Theme

**Secondary indexes + richer planner access paths.**

v0.3 keeps the v0.2 Pager transaction protocol intact and adds a second ordered access structure above it.

```text
WHERE age = 20
     ↓
   Planner
     ↓
SECONDARY_INDEX
     ↓
idx_users_age B+Tree
     ↓
   rowids
     ↓
users primary B+Tree
```

## Delta from v0.2

Added:

- `CREATE INDEX name ON table(column)`;
- persistent `IndexSchema` metadata;
- byte-key slotted B+Tree pages for secondary indexes;
- `KeyCodec` for INTEGER/TEXT/NULL index prefixes;
- physical `(indexed_value, rowid)` composite keys;
- duplicate secondary-key support;
- index build over pre-existing table rows;
- index-root split persistence;
- planner access path `SECONDARY_INDEX`;
- VM index opcodes: `OPEN_INDEX`, `SEEK_INDEX_EQ`, `INDEX_TO_TABLE`, `INDEX_NEXT`;
- transactional INSERT/DELETE index maintenance;
- rollback/crash recovery covering table + index together;
- `.indexes` and `.index INDEX` inspection;
- `docs/INDEXES.md` and `examples/indexes.py`.

## Important source files

- `mini_sqlite/index/key_codec.py`
- `mini_sqlite/index/node.py`
- `mini_sqlite/index/btree.py`
- `mini_sqlite/index/secondary.py`
- `mini_sqlite/catalog/schema.py`
- `mini_sqlite/catalog/catalog.py`
- `mini_sqlite/planner/planner.py`
- `mini_sqlite/vm/compiler.py`
- `mini_sqlite/vm/vm.py`
- `tests/test_indexes.py`
- `docs/INDEXES.md`

## Recommended reading order

1. v0.1 table B+Tree
2. v0.2 transaction/Pager journal
3. `docs/INDEXES.md`
4. `index/key_codec.py`
5. `index/node.py`
6. `index/btree.py`
7. `index/secondary.py`
8. `catalog/schema.py`
9. `planner/planner.py`
10. `vm/compiler.py` / `vm/vm.py`
11. `tests/test_indexes.py`

## Non-goals

No UNIQUE indexes, multi-column indexes, range predicates, covering-index optimization, statistics/cost model, UPDATE, ORDER BY, aggregates, JOIN, WAL, or concurrent writers.

## Next

v0.4 should add a **relational execution layer**: UPDATE, LIMIT, ORDER BY, aggregates, richer expressions, and clearer iterator/VM composition without changing the page/index/transaction foundations.
