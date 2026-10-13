# Buffer Manager — v0.7

v0.7 answers one question:

> What changes when the database cannot keep every touched page in memory?

Earlier versions used an effectively unbounded Python dictionary. v0.7 replaces that convenience with a fixed-capacity buffer pool whose frames can be pinned, dirtied, measured, and evicted.

## 1. Layering

```text
B+Tree / Index / Catalog
          ↓
        Pager
          ↓
    Buffer Manager
  ┌────────┼─────────┐
  ▼        ▼         ▼
frames   replacer   metrics
  │      LRU/Clock  hit/miss
  │
  ├─ page_id
  ├─ bytes
  ├─ dirty
  └─ pin_count
          ↓
Pager durability policy
   ├─ rollback journal
   └─ WAL overlay/checkpoint
          ↓
        disk
```

The Buffer Manager never opens a file and never understands a WAL record. Pager provides two hooks during replacement:

```text
can_evict(frame)
on_evict(frame)
```

Replacement chooses *which* frame should leave. Pager decides *whether/how* it can leave safely.

## 2. Frame model

Each resident page is represented by:

```text
BufferFrame
  page_id
  data[4096]
  dirty
  pin_count
  last_touch
  referenced
```

`last_touch` supports LRU. `referenced` supports CLOCK's second-chance bit.

## 3. Capacity

```python
Database("demo.db", buffer_pages=32)
```

The invariant is:

```text
resident_frames <= buffer_pages
```

A miss at capacity requires one eligible victim before the new page may enter memory.

## 4. Pin / unpin

A page actively used by an operation cannot be evicted:

```text
pin page
  ↓
pin_count += 1
  ↓
decode/use bytes
  ↓
unpin
  ↓
pin_count -= 1
```

The Pager exposes a readable context manager:

```python
with pager.pin_page(page_id) as page:
    node = BTreeNode.decode(page_id, page)
```

Use this API for operations whose page lifetime crosses additional fetches; current synchronous node decoders can continue to use transient reads.

## 5. LRU

LRU chooses the eligible frame with the oldest access timestamp:

```text
eligible = pin_count == 0 and Pager.can_evict(frame)
victim   = min(eligible, key=last_touch)
```

It is easy to reason about and is useful as a deterministic teaching baseline.

## 6. CLOCK

CLOCK approximates LRU with one reference bit:

```text
hand -> frame

pinned / durability-blocked
    skip

referenced = 1
    clear bit, second chance

referenced = 0
    evict
```

The default v0.7 policy is `clock`; `lru` remains selectable.

```python
Database(
    "demo.db",
    buffer_pages=32,
    replacement_policy="clock",  # or "lru"
)
```

## 7. Dirty eviction in rollback mode

Rollback mode may evict a dirty transaction page, but only with journal-before-database ordering:

```text
dirty victim
   ↓
old page already captured in rollback journal
   ↓
fsync pending journal bytes if needed
   ↓
write dirty page to main DB
   ↓
frame becomes clean
   ↓
evict
```

This is safe because ROLLBACK/hot-journal recovery can restore the before-image even if the dirty page left memory long ago.

The v0.7 tests explicitly create a transaction whose dirty working set is larger than the buffer and then roll it back.

## 8. Dirty eviction in WAL mode

Uncommitted WAL pages must **not** be written into the main database. This educational v0.7 design therefore marks active transaction dirty frames as non-evictable:

```text
WAL + active tx + dirty page
        ↓
     blocked victim
```

After COMMIT, the page's after-image is durable in WAL and the resident frame becomes clean. It may then be evicted safely because a future miss can reload the committed bytes from WAL overlay.

A large WAL transaction whose dirty working set exceeds `buffer_pages` raises `BufferPoolFullError`. Later concurrency/workspace versions could add transaction spill; v0.7 keeps the rule explicit instead of hiding an unbounded side cache.

## 9. Read miss path

```text
get page N
   ↓
buffer hit?
  ├─ yes -> hit counter + frame
  └─ no
       ↓
    choose victim if full
       ↓
    Pager loads logical page
       ├─ newest committed WAL frame
       └─ database file
       ↓
    install frame
```

The Buffer Manager sees only page bytes returned by Pager's loader.

## 10. Observability

```python
print(db.buffer_status())
print(db.buffer_frames_text())
```

CLI:

```text
.buffer
.frames
```

Metrics include:

```text
capacity
resident
dirty
pinned
hits
misses
hit rate
evictions
dirty evictions
```

This makes workloads visible. A large sequential scan with a three-page buffer should cause misses and evictions; repeated point lookups on a small hot set should accumulate hits.

## 11. Deliberate limits

v0.7 does not implement async I/O, prefetching, page guards with thread safety, ARC/2Q, separate read/write pools, transaction spill files, OS direct I/O, mmap, shared cache, or concurrent connections. The goal is the core bounded-residency mental model first.
