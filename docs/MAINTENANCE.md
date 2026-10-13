# v1.0 Maintenance and Diagnostics

v1.0 adds a final lifecycle layer above the existing engine. The maintenance layer does **not** bypass Pager, transaction, buffer, WAL, or locking rules.

## 1. Integrity check

`Database.integrity_check()` walks the logical database snapshot and validates four dimensions.

### Tree structure

For catalog/table/index B+Trees it checks:

- every referenced page id is inside the logical page range;
- each page has one owner;
- parent pointers agree with traversal parents;
- internal separators are strictly ordered;
- leaf keys are strictly ordered;
- leaf right-sibling chains match in-order traversal;
- keys respect inherited lower/upper bounds.

### Rows

For each table row:

- record bytes decode successfully;
- row width and SQL types match the schema;
- PRIMARY KEY is non-null INTEGER;
- B+Tree rowid equals the PRIMARY KEY value.

### Secondary indexes

The checker recomputes the exact physical `(indexed value, rowid)` keys implied by table rows and compares them with persisted index leaf entries. This catches both missing and extra index entries.

### Warnings instead of corruption

Two conditions are intentionally warnings:

- ANALYZE statistics disagree with current row count, because statistics are snapshots;
- unreachable pages exist, because REINDEX and non-merging deletes may legitimately leave abandoned pages for VACUUM.

## 2. REINDEX

```python
db.reindex("idx_users_age")
db.reindex()  # all secondary indexes
```

The rebuild flow is:

```text
old catalog index root
        ↓
scan table rows
        ↓
allocate fresh index B+Tree
        ↓
insert every derived key
        ↓
update catalog root
        ↓
COMMIT
```

The entire operation runs through the ordinary transaction manager. In rollback mode, new pages and catalog updates can be undone by the rollback journal. In WAL mode, after-images are committed as WAL frames. Old successful index pages are no longer reachable and become VACUUM candidates.

## 3. VACUUM

VACUUM is a logical rewrite, not an in-place page compactor.

```text
current logical snapshot
        ↓
private same-directory database
        ↓
recreate tables
copy rows
rebuild indexes
recompute stats when present
        ↓
flush + close private database
        ↓
atomic os.replace()
        ↓
reopen Pager in original journal mode
```

### Why only one live connection?

Replacing the file while another live connection has the old file open would split the process into two physical database identities. v1.0 therefore rejects VACUUM when `LockRegistry` reports more than one connection.

### WAL mode

A WAL-mode VACUUM first obtains the checkpoint maintenance lock, refreshes the committed view, and checkpoints. The compact file is then built from the stable logical state. After replacement the connection reopens in WAL mode with an empty WAL.

### What VACUUM preserves

- table names and column definitions;
- every committed row;
- secondary-index definitions;
- existence of ANALYZE statistics, recomputed exactly;
- connection journal mode.

Physical root/page ids may change by design.

## 4. EXPLAIN ANALYZE

```python
report = db.explain_analyze("SELECT ...")
print(report.render())
```

It executes a SELECT once on one snapshot and records:

- planner `EXPLAIN` text, including estimated rows/cost when stats exist;
- actual emitted row count;
- wall-clock elapsed milliseconds;
- buffer hits, misses, evictions, dirty evictions during execution;
- VM bytecode.

The timing is for education and local diagnostics. It should not be treated as a stable performance benchmark.

## 5. CLI

```text
.integrity
.reindex [INDEX]
.vacuum
.explain-analyze SQL
```
