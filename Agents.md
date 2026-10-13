# Agents.md — mini-sqlite v0.7 Development Contract

> **Frozen learning snapshot.** Read this file before changing v0.7 code, tests, documentation, or buffer/durability semantics.

## 1. Version mission

v0.7 adds one dominant mental model:

> **Database pages are a bounded memory resource. Replacement chooses residency; Pager still owns durability.**

```text
logical page request
      ↓
Buffer Manager
  capacity / pin
  LRU or CLOCK
      ↓
Pager durability policy
 rollback / WAL
      ↓
durable page source
```

## 2. Mandatory reading order

1. `Agents.md`
2. `version.md`
3. `docs/BUFFER_MANAGER.md`
4. `docs/ARCHITECTURE.md`
5. `tests/test_buffer_manager.py`
6. `mini_sqlite/storage/buffer.py`
7. `mini_sqlite/storage/pager.py`
8. `docs/TRANSACTIONS.md`
9. `docs/WAL.md`
10. `examples/buffer_pool.py`

## 3. Branch boundary

This branch is the frozen **v0.7 bounded-buffer milestone**. Allowed changes are documentation corrections, tests clarifying promised behavior, and narrowly scoped defects inside v0.7 semantics.

Do not backport v0.8 statistics/cost optimization, v0.9 multi-connection locking, async I/O, ARC/2Q, transaction spill files, or shared caches.

## 4. Layering invariant

```text
B+Tree / Index / Catalog
          ↓
        Pager
          ↓
    Buffer Manager
          ↓
Pager durable loader/writeback
   ├─ rollback journal
   └─ WAL overlay/checkpoint
```

The Buffer Manager must not parse WAL/journal files. Replacement policy decides *which* frame; Pager decides *whether/how* eviction is legal.

## 5. Buffer invariants

- resident frames never exceed configured capacity;
- pinned frames are never evicted;
- every page id has at most one resident frame;
- dirty state belongs to a frame, not to replacement metadata;
- LRU and CLOCK operate only on Pager-approved candidates;
- eviction callback must resolve dirty state before the frame disappears;
- cache metrics must not affect correctness.

## 6. Durability interaction

Rollback mode:

```text
dirty victim
  ↓
journal before-image already captured
  ↓
sync journal if pending
  ↓
write DB page
  ↓
evict clean frame
```

WAL mode:

```text
active transaction dirty frame
  ↓
non-evictable
```

After WAL COMMIT, the frame becomes clean because WAL is the durable source of truth and may be evicted. Checkpoint must remain independent of frame residency.

## 7. Public configuration

```python
Database(
    "demo.db",
    journal_mode="rollback",   # or "wal"
    buffer_pages=64,
    replacement_policy="clock",  # or "lru"
)
```

CLI mirrors these knobs with `--buffer-pages` and `--replacement-policy`.

## 8. Inspection contract

```text
.buffer   aggregate capacity/hit/miss/eviction state
.frames   resident frame metadata
```

Metrics include capacity, resident, dirty, pinned, hits, misses, hit rate, evictions, and dirty evictions.

## 9. Testing contract

Run:

```bash
python -m pytest -q
python examples/quickstart.py
python examples/transactions.py
python examples/indexes.py
python examples/relational.py
python examples/joins.py
python examples/wal.py
python examples/buffer_pool.py
python -m compileall -q mini_sqlite
```

Coverage must include LRU, CLOCK, pin protection, bounded large scans, rollback dirty eviction + rollback correctness, WAL committed eviction/reopen, explicit WAL dirty-working-set exhaustion, indexed JOIN with a tiny buffer, metrics, and full v0.1-v0.6 regression.

## 10. Definition of Done

A v0.7-compatible change is complete only when capacity is truly bounded, pinning prevents eviction, both replacement policies remain inspectable, dirty eviction respects durability mode, old query/storage semantics remain green, docs match implementation limits, examples run from source, and the exact final `v0.7` branch-head CI passes.
