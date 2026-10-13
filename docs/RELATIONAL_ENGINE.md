# Relational execution in mini-sqlite v0.4

## 1. The new mental model

v0.1-v0.3 established how rows are stored, found, indexed, and made crash-atomic. v0.4 focuses on what happens **after a row source is chosen**.

```text
access source
(table scan / PK seek / index seek)
        ↓
      filter
        ↓
      collect
        ↓
       sort
        ↓
 aggregate OR project
        ↓
       limit
        ↓
       emit
```

The implementation stays bytecode-oriented. Instead of introducing a large iterator framework, v0.4 adds explicit relational VM opcodes so the pipeline is visible in `.bytecode`.

## 2. Access path is still separate from row processing

For equality predicates, v0.3 rules remain:

```text
WHERE primary_key = value  -> PRIMARY_KEY
WHERE indexed_col = value  -> SECONDARY_INDEX
otherwise                   -> TABLE_SCAN
```

Range predicates such as `age >= 20` deliberately use a table scan in v0.4. The index B+Tree already has ordering, but a range-capable index cursor is a separate mechanism and is not silently invented here.

That separation matters:

```text
Planner chooses where rows come from
            ↓
relational pipeline decides what happens to rows
```

## 3. Comparison predicates

v0.4 supports one simple predicate:

```text
=
!=
<
<=
>
>=
```

Examples:

```sql
SELECT * FROM users WHERE age >= 21;
DELETE FROM users WHERE age < 18;
UPDATE users SET age = 30 WHERE age != 30;
```

Expression evaluation lives in VM row processing; storage pages and B+Trees do not interpret SQL comparison syntax.

### NULL policy

v0.4 does **not** implement SQL three-valued logic or `IS NULL` yet. Equality follows the project's earlier educational Python-like semantics; ordered comparisons involving NULL do not match. This is explicit and tested rather than pretending to be full SQLite semantics.

## 4. Materialized working rows

`COLLECT_ROW` decodes matching table records into an in-memory working set. Later operators transform that set.

This deliberately favors visibility over streaming efficiency:

```text
physical cursor loop
       ↓
working_rows
       ↓
SORT_ROWS / AGGREGATE_ROWS / PROJECT_ROWS / LIMIT_ROWS
```

A later execution-engine version may replace this with iterator or vectorized operators without changing Parser/Planner/storage boundaries.

## 5. ORDER BY

Example:

```sql
SELECT name FROM users ORDER BY age DESC LIMIT 3;
```

The VM sorts full table rows **before projection**, so the order column does not need to appear in the output list.

v0.4 uses an in-memory sort. It does not claim that an index automatically satisfies ORDER BY.

NULL sorts before non-NULL in ascending order and after non-NULL in descending order in this educational engine.

## 6. Aggregates

Supported scalar aggregates without GROUP BY:

```text
COUNT(*)
COUNT(column)
SUM(integer_column)
MIN(column)
MAX(column)
```

Rules:

- `COUNT(*)` counts rows;
- `COUNT(column)` ignores NULL;
- `SUM/MIN/MAX` ignore NULL;
- `SUM/MIN/MAX` return NULL for an empty/non-NULL-free input;
- `SUM` requires INTEGER;
- mixing aggregate and ordinary SELECT items is deferred until GROUP BY semantics exist.

Example:

```sql
SELECT COUNT(*), SUM(age), MIN(age), MAX(age)
FROM users
WHERE age >= 18;
```

## 7. UPDATE and index maintenance

Example:

```sql
UPDATE users SET age = 36 WHERE age = 35;
```

If `age` is indexed, the planner can use that index to find rowids. For each row, VM executes conceptually:

```text
old row
  ↓
delete every old secondary-index entry
  ↓
replace table record under same INTEGER PRIMARY KEY
  ↓
insert every new secondary-index entry
  ↓
continue
```

All page mutations participate in the same v0.2 rollback-journal transaction. Therefore an UPDATE cannot durably leave the table and its secondary indexes disagreeing.

v0.4 deliberately forbids changing the INTEGER PRIMARY KEY. Rowid-changing UPDATE would add a different storage identity problem and is not required to understand relational row processing.

## 8. Bytecode example

A scan/sort/project/limit query looks conceptually like:

```text
OPEN_READ
REWIND
FILTER_COMPARE
COLLECT_ROW
NEXT
SORT_ROWS
PROJECT_ROWS
LIMIT_ROWS
EMIT_ROWS
HALT
```

An aggregate replaces `PROJECT_ROWS` with `AGGREGATE_ROWS`.

This is the v0.4 teaching surface: relational operations are visible as execution stages rather than buried in statement-specific Python branches.

## 9. Explicit non-goals

v0.4 does not add:

- JOIN;
- GROUP BY / HAVING;
- aliases / qualified names;
- AND / OR expression trees;
- SQL three-valued NULL logic;
- arithmetic UPDATE expressions;
- primary-key UPDATE;
- streaming LIMIT short-circuit;
- external sort;
- range index scans;
- cost-based optimization.
