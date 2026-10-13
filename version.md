# Current integrated state — v1.1

`main` contains the validated **v1.1 Cross-process File Locking** engine tree on top of the v1.0 educational core.

## Integrated architecture

```text
SQL → Parser / AST → Cost-Based Planner → Compiler / VM
                           ↑                    │
                    ANALYZE statistics         ↓
                                    relational ops / JOIN
                                             ↓
                                  table/index B+Trees
                                             ↓
                                     Database connection
                                      │              │
                                      ↓              ↓
                                LockRegistry     FileLockSet
                                 local state     POSIX flock
                                      │              │
                                      └──────┬───────┘
                                             ↓
                                           Pager
                                             ↓
                                  Bounded Buffer Manager
                                             ↓
                          rollback journal OR WAL/checkpoint
                                             ↓
                                        database file

Lifecycle diagnostics / maintenance:
 integrity_check · reindex · vacuum · explain_analyze
```

## v1.1 additions

- cross-process POSIX `flock` backend on macOS/Linux;
- persistent MODE / PENDING / READERS / WRITER sidecars whose existence is not liveness;
- globally-first MODE-EX recovery/bootstrap ownership;
- live rollback/WAL mode agreement across interpreters;
- rollback SHARED / RESERVED / EXCLUSIVE semantics across processes;
- PENDING turnstile preventing reader starvation of writers;
- WAL concurrent readers + one global writer;
- checkpoint exclusion across processes;
- cross-process `busy_timeout_ms`;
- constructor guard preventing rollback Pager open during EX writer;
- kernel auto-release after abrupt process death;
- hot-journal recovery after `os._exit()`;
- VACUUM global exclusion;
- lock observability showing process-local and OS lock state.

## Validation

The frozen `v1.1` branch passed the exact GitHub CI matrix on Python 3.10 and 3.12, including the complete regression suite, lifecycle smoke, cross-process smoke, and compile check.

```bash
python -m pytest -q
python examples/cross_process.py
python -m compileall -q mini_sqlite
```

## Compatibility

v1.1 changes no database-page, record, catalog, rollback-journal, WAL, or index byte format. v1.0 database files reopen directly.

The cross-process backend is POSIX-only in v1.1; Windows support is intentionally deferred rather than simulated incorrectly.

## Next — v1.2

**Free-list Page Reuse + Incremental VACUUM**

Planned direction:

```text
page becomes unreachable
        ↓
persistent free-list
        ↓
future allocation reuses page
        ↓
free pages reach file tail
        ↓
incremental truncation
```

The key invariant is that free-list mutation must obey the same rollback/WAL crash-safety and v1.1 locking rules as ordinary page ownership changes.
