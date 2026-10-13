# Fault matrix through v1.2

| Failure window | Required outcome |
|---|---|
| free-list mutation before commit | rollback restores page bytes + old head |
| WAL free-list mutation without COMMIT | frames ignored |
| rollback shrink after journal sync, before truncate | old state visible/recoverable |
| rollback shrink after physical truncate, before journal delete | hot journal restores truncated page images and original page count |
| WAL shrink after COMMIT, before checkpoint | smaller logical snapshot comes from WAL; main DB may still be larger |
| WAL checkpoint during shrink | readers drained; committed frames applied then main DB truncated |
| free-list cycle / out-of-range next | integrity reports corruption |
| tree page also present in free-list | integrity reports ownership corruption |

Incremental vacuum intentionally does not move live pages, so it has no page-relocation crash window.
