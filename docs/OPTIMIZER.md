# v0.8 Cost-Based Optimizer

v0.8 changes one question in mini-sqlite:

```text
old planner:  which rule matches first?
new planner:  which correct candidate has the lowest estimated work?
```

The optimizer never changes query correctness. Statistics and cost estimates are advisory inputs used only to choose among semantically equivalent physical plans.

## 1. ANALYZE

```sql
ANALYZE;
ANALYZE users;
```

`ANALYZE` performs an exact educational full-table scan and persists a statistics snapshot inside the table's catalog JSON record.

Per table: `row_count`. Per column: `null_count`, `distinct_count`, `min_value`, `max_value`, and up to 16 `(value,count)` most-common entries.

The most-common-value list demonstrates skew: a value occupying 90% of rows should not be estimated as `N / distinct` when the catalog already knows its frequency. Statistics are snapshots. INSERT/UPDATE/DELETE do not silently recompute them; run `ANALYZE` again to refresh.

## 2. Selectivity estimation

For equality:

```text
if value appears in most_common:
    estimated_rows = exact saved frequency
else:
    remaining_rows / remaining_distinct
```

For integer ranges, v0.8 linearly interpolates between min/max. TEXT ranges and unknown shapes use conservative fallback fractions. This is deliberately not a production histogram estimator.

## 3. Access-path cost model

Costs are abstract work units, not milliseconds:

```text
TABLE_ROW_COST       = 1.0
PK_SEEK_COST         = 2.0
INDEX_SEEK_COST      = 2.0
INDEX_MATCH_COST     = 0.20
ROWID_LOOKUP_COST    = 2.0
```

Candidate examples:

```text
TABLE SCAN cost = row_count
PRIMARY KEY cost = 2
SECONDARY INDEX equality cost = 2 + estimated_matches * (0.2 + 2)
```

### Skew example

Suppose 100 rows have an index on `grp`, where `grp=1` appears 90 times. After ANALYZE:

```text
WHERE grp = 1
TABLE SCAN cost = 100
INDEX cost      = 200
=> TABLE SCAN

WHERE grp = 95
TABLE SCAN cost = 100
INDEX cost      = 4.2
=> SECONDARY INDEX
```

So “an index exists” no longer means “the optimizer must use it.”

## 4. Missing statistics fallback

Old databases and newly-created tables may have no statistics. v0.8 preserves the v0.7 rule planner in that case:

```text
PK equality        -> primary-key lookup
secondary equality -> secondary-index lookup
otherwise          -> table scan
```

Missing statistics can degrade plan quality, never correctness.

## 5. Two-table JOIN order

v0.5-v0.7 used SQL-left as the outer source. v0.8 evaluates both legal orientations:

```text
A outer -> B inner
B outer -> A inner
```

The physical inner side independently chooses PRIMARY KEY seek, SECONDARY INDEX seek, or TABLE SCAN. For each orientation:

```text
cost ≈ outer_rows + outer_rows * inner_probe_cost
```

The logical SQL row layout is unchanged. Cursor 0 remains SQL-left and cursor 1 remains SQL-right, so projection/WHERE/ORDER BY semantics do not depend on physical order.

## 6. Join cardinality estimate

For equality joins with statistics on both join columns:

```text
estimated_rows ≈ rows(A) * rows(B) / max(ndv(A.key), ndv(B.key))
```

This is a classic simplified estimator and intentionally assumes independence/uniformity outside saved MCV information.

## 7. Thin v0.8 extension layer

v0.8 deliberately preserves the v0.7 binder and VM implementation:

```text
Legacy Planner -> CostBasedPlanner physical replacement
Legacy Compiler -> CostBasedCompiler JOIN orientation + ANALYZE opcode
Legacy VM -> CostBasedVirtualMachine ANALYZE catalog write
```

This keeps the version delta focused on the optimizer rather than rewriting stable query/storage mechanisms.

## 8. EXPLAIN observability

After ANALYZE, `Database.explain(sql)` includes chosen path, estimated rows, estimated cost, all candidate costs, and physical join order.

The goal is not to claim estimates are perfect. The goal is to make optimizer reasoning inspectable.

## 9. Durability and storage boundaries

ANALYZE updates catalog rows, so it participates in the existing transaction system. Rollback journal can undo the stats change; WAL can hold committed catalog after-images before checkpoint. Buffer Manager treats optimizer metadata like ordinary catalog pages.

## 10. Non-goals

v0.8 does not implement many-way Selinger dynamic programming, multi-column statistics, production histograms, correlation estimation, adaptive re-optimization, index range scans, hash/merge join, runtime feedback learning, or parallel execution.

Central lesson: **statistics → cardinality → cost → candidate comparison → plan choice**.
