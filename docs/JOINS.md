# v0.5 JOIN internals

v0.5 asks one question:

> How can two independently stored tables become one row stream without hiding the physical cost of finding the inner row?

The answer is deliberately small: one `INNER JOIN`, one written outer source, and three visible inner access paths.

## 1. SQL surface

```sql
SELECT u.name, o.item
FROM users u
JOIN orders o ON u.id = o.user_id
WHERE o.amount >= 10
ORDER BY o.id
LIMIT 5;
```

Supported in v0.5:

- `JOIN` / `INNER JOIN`;
- one join per SELECT;
- `AS` aliases or shorthand aliases (`users u`);
- qualified column references (`u.id`);
- unqualified references only when unambiguous;
- equality `ON left.col = right.col`;
- existing WHERE / ORDER BY / LIMIT / aggregate pipeline after JOIN;
- self-join when aliases make the two sources distinct.

Deferred: LEFT/RIGHT/FULL JOIN, multi-join chains, arbitrary ON expressions, GROUP BY, hash join, merge join, join reordering, cost-based selection.

## 2. Logical row shape

The VM materializes joined rows as:

```text
(left column 0 ... left column N, right column 0 ... right column M)
```

Name resolution maps every projected/filter/sort/aggregate column onto one flat index. This lets v0.4 operators remain unchanged after a JOIN.

Example:

```text
users(id, name) + orders(id, user_id, item)

joined row:
(users.id, users.name, orders.id, orders.user_id, orders.item)
```

## 3. Algorithm selection

The left source stays the outer loop in v0.5. The right ON column selects the inner path.

### Plain nested loop

No usable right-side equality index:

```text
for left_row in users:
    for right_row in orders:
        if left_row.id == right_row.user_id:
            emit pair
```

Bytecode exposes this as:

```text
REWIND left
REWIND right
FILTER_JOIN_EQ
COLLECT_JOIN_ROW
NEXT right
NEXT left
```

Work is approximately `O(L × R)` row comparisons.

### Indexed nested loop through a primary key

If the right ON column is the INTEGER PRIMARY KEY:

```text
for order in orders:
    user = users.pk_seek(order.user_id)
```

Bytecode:

```text
REWIND outer
SEEK_PK_FROM_COLUMN
COLLECT_JOIN_ROW
NEXT outer
```

This changes the inner operation from a full scan to B+Tree lookup.

### Indexed nested loop through a secondary index

If the right ON column has a secondary index:

```text
for user in users:
    for rowid in idx_orders_user.seek_equal(user.id):
        order = orders.pk_seek(rowid)
        emit pair
```

Bytecode:

```text
OPEN_INDEX
REWIND outer
SEEK_INDEX_FROM_COLUMN
INDEX_TO_TABLE
COLLECT_JOIN_ROW
INDEX_NEXT
NEXT outer
```

Duplicate foreign-key values are preserved because the v0.3 physical index key remains `(indexed_value, rowid)`.

## 4. Why the join does not live inside B+Tree

B+Tree knows only ordered key/value storage. It must not know tables, aliases, JOIN, WHERE, or projection.

```text
SQL / name resolution
        ↓
Planner: join algorithm policy
        ↓
Compiler: visible nested-loop bytecode
        ↓
VM: compose two cursor mechanisms
        ↓
B+Tree / secondary index / Pager
```

That boundary is important for later versions: v0.8 can choose a different join order/cost without changing storage, and a future hash join can be added as another execution operator.

## 5. JOIN then relational pipeline

A matched pair enters the v0.4 working set. Existing operators then compose normally:

```text
JOIN
 ↓
FILTER_ROWS
 ↓
SORT_ROWS
 ↓
AGGREGATE_ROWS or PROJECT_ROWS
 ↓
LIMIT_ROWS
 ↓
EMIT_ROWS
```

So v0.5 is additive: it creates a richer source stream rather than duplicating WHERE/ORDER BY/LIMIT logic for JOIN statements.

## 6. Name resolution

For two tables, an unqualified column is accepted only if exactly one source owns that name.

```sql
SELECT name, item ...      -- valid if only users has name and only orders has item
SELECT id ...              -- error if both sources have id
SELECT u.id, o.id ...      -- explicit and valid
```

Self-joins require distinct aliases:

```sql
SELECT e.name, m.name
FROM people e
JOIN people m ON e.manager_id = m.id;
```

## 7. Learning path

Read in this order:

1. `mini_sqlite/sql/ast.py`
2. `mini_sqlite/sql/parser.py`
3. `mini_sqlite/planner/plan.py`
4. `mini_sqlite/planner/planner.py`
5. `mini_sqlite/vm/compiler.py`
6. `mini_sqlite/vm/opcode.py`
7. `mini_sqlite/vm/vm.py`
8. `tests/test_joins.py`
9. `examples/joins.py`

The central observation is that JOIN is not a storage primitive. It is an execution strategy for repeatedly obtaining rows from two already-existing access mechanisms.
