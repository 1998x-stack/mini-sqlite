# mini-sqlite — Architecture-Driven Development Plan

> v0.1 branch snapshot. `main` may contain later integrated milestones.

## Project purpose

mini-sqlite removes one layer of database “magic” at a time with readable Python implementations. Each version introduces one dominant database mental model and keeps prior layers visible.

```text
pages / records
      ↓
B+Tree
      ↓
SQL → planner → VM
      ↓
transactions
      ↓
secondary indexes
      ↓
relational operators
      ↓
joins
      ↓
WAL
      ↓
buffer manager
      ↓
cost optimizer
      ↓
concurrency
```

## v0.1 — Storage engine + SQL-to-VM vertical slice ✅

**Question:** How does `SELECT ...` ultimately become page reads from one database file?

Implemented:

- 4 KiB fixed-size pages and cache;
- database meta page;
- typed record codec (`NULL`, `INTEGER`, `TEXT`);
- slotted B+Tree leaf/internal pages;
- leaf, internal, and root splits;
- linked-leaf scans;
- persistent catalog B+Tree;
- root-page propagation;
- SQL tokenizer, parser, AST;
- rule planner;
- VDBE-inspired bytecode compiler/interpreter;
- `CREATE`, `INSERT`, `SELECT`, `DELETE`;
- `.schema`, `.pages`, `.btree`, `.explain`, `.bytecode`;
- reopen/persistence tests.

Explicit non-goals: crash-atomic multi-statement transactions, secondary indexes, joins, WAL, concurrent writers, SQLite binary compatibility.

## Planned sequence

- **v0.2** — rollback-journal transactions and crash recovery
- **v0.3** — secondary indexes and richer planner
- **v0.4** — relational execution (`UPDATE`, `LIMIT`, `ORDER BY`, aggregates)
- **v0.5** — joins
- **v0.6** — WAL
- **v0.7** — bounded buffer manager
- **v0.8** — cost-based optimizer
- **v0.9** — concurrency and locking
- **v1.0** — educationally complete mini SQLite

## Version protocol

```text
latest validated main
      ↓
create vX.Y branch
      ↓
write version boundary/docs first
      ↓
implement one primary mechanism
      ↓
tests + example + architecture docs
      ↓
freeze version branch
      ↓
integrate validated state into main
```
