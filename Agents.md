# Agents.md — mini-sqlite v1.3 Development Contract

> Frozen learning snapshot. Read this file before changing ordered-index encoding, range planning, composite-index metadata, VM access paths, compatibility rules, tests, or documentation.

## 1. Version mission

v1.3 adds one dominant mental model:

> **A B+Tree is useful not only because it can find one key, but because its lexicographic order can represent SQL equality prefixes and bounded ranges.**

The v1.2 page lifecycle, free-list, durability, locking, buffer-pool, optimizer and maintenance layers remain intact. v1.3 extends the secondary-index path from scalar equality probes to ordered multi-column probes.

## 2. Mandatory reading order

1. `Agents.md`
2. `version.md`
3. `docs/ORDERED_INDEXES.md`
4. `mini_sqlite/index/key_codec.py`
5. `mini_sqlite/index/btree.py`
6. `mini_sqlite/index/secondary.py`
7. `mini_sqlite/planner/indexing.py`
8. `mini_sqlite/planner/planner.py`
9. `mini_sqlite/planner/optimizer.py`
10. `mini_sqlite/vm/compiler.py`
11. `mini_sqlite/vm/vm.py`
12. `tests/test_range_composite.py`
13. `examples/range_indexes.py`

## 3. Branch boundary

This branch is the frozen **v1.3 ordered range scan + composite-index milestone**.

Do not backport v1.4 savepoints, covering-index execution, ORDER BY elimination, additional join algorithms, or MVCC.

## 4. Layering invariant

```text
SQL predicates / CREATE INDEX
        ↓
Parser / AST
        ↓
left-prefix probe analysis
        ↓
Cost-Based Planner
        ↓
SEEK_INDEX_EQ or SEEK_INDEX_RANGE
        ↓
SecondaryIndexCursor
        ↓
KeyCodec bounds + ByteKeyBTree ordered scan
        ↓
rowid lookup
        ↓
residual predicate filter
```

SQL parsing must not construct physical page keys. Planner describes a logical index probe. `SecondaryIndex` and `KeyCodec` own translation into byte bounds. B+Tree owns ordered traversal only.

## 5. Composite-index invariants

- physical index order follows the declared column order;
- the rowid remains the final key component so duplicate SQL keys remain unique;
- scalar components are self-delimiting and lexicographically order-preserving;
- old single-column indexes remain readable and behave as one-element composite indexes;
- INSERT / UPDATE / DELETE / REINDEX / VACUUM maintain every indexed column atomically through existing transactions;
- integrity checking reconstructs the complete composite physical key, not only the leftmost column.

## 6. Left-prefix invariant

For index `(a, b, c)`, an ordered probe may consume:

```text
zero or more equality columns
        +
at most one following range column
```

Examples:

```text
a = 1                              usable
a = 1 AND b = 2                    usable
a = 1 AND b BETWEEN 10 AND 20      usable
a = 1 AND b = 2 AND c >= 5         usable
b = 2                              not usable
c >= 5                             not usable
```

Conditions not consumed by the probe remain residual predicates and must still be evaluated for correctness.

## 7. Range-bound invariants

`ByteKeyBTree.scan_range(lower, upper)` uses a half-open interval `[lower, upper)`.

- inclusive SQL upper bounds use `KeyCodec.prefix_successor(encoded_upper)`;
- exclusive SQL lower bounds advance to the prefix successor;
- prefix equality scans stop at the successor of the full equality prefix;
- unbounded ordered ranges start at the indexed column's type tag, not raw `0x00`, so SQL ordered comparisons do not accidentally include NULL;
- NULL does not satisfy `<`, `<=`, `>`, `>=`, or BETWEEN in this educational SQL model.

## 8. Planner / optimizer invariants

- primary-key equality remains the strongest rule candidate;
- historical scalar equality can retain `SECONDARY_INDEX` / `SEEK_INDEX_EQ` for readability;
- composite-prefix and range probes use `SECONDARY_INDEX_RANGE` / `SEEK_INDEX_RANGE`;
- without ANALYZE, rule selection may use the best valid ordered index candidate;
- with ANALYZE, the cost model may reject a broad range and choose TABLE SCAN;
- EXPLAIN must reveal the chosen index and ordered columns.

## 9. Format compatibility

v1.3 promotes the main database format version from **2 → 3** because catalog index metadata now has an ordered `columns[]` tuple.

The page-0 byte structure is unchanged. Table B+Tree bytes, secondary-index node bytes, row encoding, free-page bytes, rollback-journal records, WAL records and lock sidecars are unchanged.

v1.3 reads v1/v2 databases. Before a composite index becomes reachable, page 0 is persisted as format v3. Older v1.2 engines must reject v3 rather than silently reinterpret `(a,b)` as index `(a)`.

## 10. Testing contract

Run:

```bash
python -m pytest -q
python examples/range_indexes.py
python examples/indexes.py
python examples/optimizer.py
python -m compileall -q mini_sqlite
```

Changes to ordered-index behavior must include boundary tests, NULL behavior, left-prefix fallback, maintenance/reopen tests and broad-vs-selective optimizer tests.

## 11. Definition of done

A v1.3 change is complete only when:

1. range scans return exactly the SQL-visible interval;
2. composite indexes obey left-prefix semantics;
3. residual predicates preserve correctness;
4. range/index choices remain explainable through bytecode and EXPLAIN;
5. UPDATE/DELETE/REINDEX/VACUUM/integrity remain correct for composite indexes;
6. format-v1/v2 files still open and composite-index persistence crosses to v3 deliberately;
7. all v0.1–v1.2 regressions remain green;
8. exact branch-head CI passes on supported Python versions;
9. docs match the actual key encoding and compatibility boundary.
