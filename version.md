# mini-sqlite v1.1.0 — Cross-process File Locking

## Status

**Implemented / frozen candidate.**

v1.1 makes the v0.9 connection lock protocol visible to the operating system so independent Python processes can safely share one database file.

## Main mental model

```text
process-local LockRegistry
        ↓
POSIX flock backend
        ↓
MODE / PENDING / READERS / WRITER
        ↓
rollback or WAL durability
```

## New capabilities

- POSIX `flock` backend for macOS/Linux;
- cross-process rollback SHARED / RESERVED / EXCLUSIVE behavior;
- cross-process WAL readers + single writer;
- cross-process checkpoint exclusion;
- global live journal-mode agreement;
- constructor guard preventing rollback Pager open during EX writer;
- busy timeout across processes;
- automatic OS lock release after abrupt process death;
- globally-first recovery ownership through MODE-EX;
- cross-process VACUUM exclusion;
- `.locks` exposes backend + per-connection OS lock state;
- multiprocessing spawn test suite.

## Sidecars

For `demo.db`:

```text
demo.db-lock-mode
demo.db-lock-pending
demo.db-lock-readers
demo.db-lock-writer
```

These files may remain after every connection closes. Only live kernel locks matter.

## Compatibility

The v1.0 database-page, rollback-journal, and WAL formats are unchanged. v1.0 database files reopen directly in v1.1.

## Platform scope

POSIX/macOS/Linux only for the cross-process backend. Windows support is intentionally deferred rather than emulated incorrectly.

## Validation target

- all v0.1–v1.0 regression tests;
- 9 cross-process spawn tests;
- cross-process smoke example;
- Python 3.10 / 3.12 CI;
- `compileall`.

## Next

**v1.2 — Free-list Page Reuse + Incremental VACUUM**: stop treating deleted/replaced pages as permanently orphaned until full VACUUM; introduce an explicit free-page lifecycle and reuse policy.
