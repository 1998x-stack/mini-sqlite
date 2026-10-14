# v1.3 — Ordered range scans and composite indexes

v1.3 turns the secondary-index B+Tree from an equality-only lookup structure into an ordered access path.

## 1. Physical key

For `CREATE INDEX idx_ab ON t(a, b)`, each leaf key is:

```text
encode(a) || encode(b) || encode(rowid)
```

Scalar encodings are self-delimiting and lexicographically ordered. The trailing rowid makes duplicate SQL keys physically unique.

## 2. Range cursor

`ByteKeyBTree.scan_range(lower, upper)` scans a half-open byte interval `[lower, upper)`. SQL inclusive bounds are converted with `KeyCodec.prefix_successor()`.

```text
b <= 20

upper = successor(prefix(a) || encode(20))
```

An unbounded ordered comparison begins at the column type tag, not at the raw prefix, so the NULL run is excluded.

## 3. Left-prefix rule

For index `(a,b,c)` the planner can exploit:

```text
a = ?
a = ? AND b = ?
a = ? AND b BETWEEN ? AND ?
a = ? AND b = ? AND c >= ?
```

but not:

```text
b = ?
c >= ?
```

because the B+Tree is ordered first by `a`.

The planner consumes zero or more equality columns and then at most one range column. Remaining predicates are post-filters.

## 4. SQL surface

v1.3 adds:

```sql
CREATE INDEX idx_region_ts ON events(region, ts);

SELECT * FROM events
WHERE region = 'us'
  AND ts BETWEEN 20 AND 40;

SELECT * FROM events
WHERE region = 'us'
  AND ts >= 20
  AND ts < 40;
```

`AND` is intentionally conjunction-only; `OR`, parentheses and general boolean expression trees remain future work.

## 5. VM path

A composite/range query is visible in bytecode:

```text
OPEN_READ
OPEN_INDEX
SEEK_INDEX_RANGE
INDEX_TO_TABLE
FILTER_PREDICATE   # only when residual predicates remain
COLLECT_ROW
INDEX_NEXT
...
```

Single-column equality retains the historical `SEEK_INDEX_EQ` opcode so earlier milestones remain easy to compare.

## 6. Cost model

After `ANALYZE`, the optimizer compares table scan cost with the estimated row count of the range probe. A broad range may deliberately choose TABLE SCAN while a selective range chooses SECONDARY INDEX RANGE.

## 7. Format compatibility

v1.3 raises the main database format version to **3** because catalog index metadata now has ordered `columns[]`, not only a single `column`. Page size, table/index B+Tree node bytes, record encoding, rollback journal and WAL record layouts are unchanged.

v1.3 reads v1/v2 databases. Before a composite index becomes reachable, page 0 is persisted as format v3 so older engines fail explicitly instead of silently treating `(a,b)` as a single-column index.
