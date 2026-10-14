# Fault and Recovery Matrix

This matrix summarizes what each layer protects and what tests exercise.

| Scenario | Expected behavior | Mechanism |
|---|---|---|
| crash after rollback journal sync, before commit | restore old pages | hot rollback journal |
| new pages allocated then rollback/crash | truncate to original page count | journal header original size |
| crash before WAL COMMIT | ignore uncommitted tail | committed-prefix scan |
| torn WAL record | ignore/truncate invalid tail | framing + CRC |
| multiple WAL commits for same page | newest committed frame wins | overlay map |
| crash during checkpoint before WAL reset | committed WAL still reconstructs state | DB fsync before WAL reset |
| buffer dirty eviction in rollback mode | safe writeback then possible rollback | before-image-first ordering |
| WAL active dirty set exceeds buffer | explicit BufferPoolFullError | uncommitted WAL pages non-evictable |
| rollback reader + writer | writer waits/fails until readers leave | SHARED/RESERVED/EXCLUSIVE |
| WAL reader + writer | coexist on reader snapshot | SHARED + WAL_WRITE |
| stale WAL reader upgrades to writer | fail with BusySnapshotError | WAL signature snapshot |
| checkpoint while WAL reader active | wait/fail | checkpoint maintenance lock |
| index entry missing/extra | integrity check fails | table↔index recomputation |
| stale ANALYZE statistics | warning only | statistics are snapshots |
| old index pages after REINDEX | return to persistent free-list | transactional page ownership transfer |
| VACUUM with second live connection | reject | Lock Registry connection count |
| free-list mutation rolls back | old head/page ownership restored | normal rollback/WAL page semantics |
| crash after rollback-mode physical truncate before journal deletion | restore truncated free pages + old size | journaled tail before-images + original page count |
| WAL incremental shrink commit | readers see committed smaller logical count; main file shrinks at checkpoint | WAL COMMIT page_count + checkpoint |
| free-list cycle/out-of-range/shared live page | integrity check fails | free-list traversal + ownership map |

## Crash tests vs process-local lock registry

Some tests emulate a process crash by force-closing Pager file handles without ending the Python process. v0.9 liveness pruning treats a connection with a dead Pager as dead so later hot-journal recovery behaves like a real process restart.

## What is not protected

v1.2 does not provide:

- live-page movement during incremental vacuum;
- filesystem or hardware guarantees beyond normal `fsync` assumptions;
- checksums on main database pages;
- replication;
- backup snapshots;
- distributed transactions.

## v1.3 ordered-index boundaries

| Fault / edge | Required behavior |
|---|---|
| Range starts below first non-NULL value | NULL index entries are excluded from ordered SQL comparisons |
| Composite index update crashes | table row and every composite index mutation recover atomically through existing journal/WAL rules |
| CREATE composite index crashes before commit | catalog entry and newly allocated index pages do not become partially visible |
| Reopen after composite index root split | persisted root and ordered tuple encoding remain queryable |
