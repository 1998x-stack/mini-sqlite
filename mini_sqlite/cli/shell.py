from __future__ import annotations

import argparse
import shlex
from pathlib import Path

from mini_sqlite import Database, MiniSQLiteError, __version__

PROMPT = "mini-sqlite> "
CONT_PROMPT = "       ...> "


def _print_rows(columns: list[str], rows: list[tuple]) -> None:
    if not rows:
        print("(0 rows)")
        return
    if columns:
        print(" | ".join(columns))
        print("-+-".join("-" * max(3, len(c)) for c in columns))
    for row in rows:
        print(" | ".join("NULL" if value is None else str(value) for value in row))
    print(f"({len(rows)} rows)")


def _read_statement(first: str) -> str:
    parts = [first]
    while ";" not in parts[-1]:
        try:
            parts.append(input(CONT_PROMPT))
        except EOFError:
            break
    return "\n".join(parts)


def repl(path: str | Path, *, journal_mode: str = "rollback", buffer_pages: int = 64, replacement_policy: str = "clock", busy_timeout_ms: int = 0) -> None:
    with Database(path, journal_mode=journal_mode, buffer_pages=buffer_pages, replacement_policy=replacement_policy, busy_timeout_ms=busy_timeout_ms) as db:
        recovered = " (recovery performed)" if db.pager.recovery_performed else ""
        print(f"mini-sqlite v{__version__} mode={db.pager.journal_mode} buffer={buffer_pages}/{replacement_policy}{recovered} — .help for commands")
        while True:
            try:
                line = input(PROMPT).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not line:
                continue
            if line.startswith("."):
                if _meta_command(db, line):
                    break
                continue
            sql = _read_statement(line)
            try:
                result = db.execute(sql)
                if result.rows:
                    _print_rows(result.columns, result.rows)
                else:
                    print(f"OK ({result.rowcount} affected)")
            except MiniSQLiteError as exc:
                print(f"error: {exc}")


def _meta_command(db: Database, line: str) -> bool:
    parts = shlex.split(line)
    cmd = parts[0]
    if cmd in (".quit", ".exit"):
        return True
    if cmd == ".help":
        print(
            ".schema              show CREATE TABLE/INDEX statements\n"
            ".indexes             show secondary-index metadata\n"
            ".pages               show physical pages\n"
            ".btree TABLE         dump a table B+Tree\n"
            ".index INDEX         dump a secondary-index B+Tree\n"
            ".txn                 show transaction/durability state\n"
            ".locks               show connection lock state\n"
            ".buffer              show buffer-pool statistics\n"
            ".frames              show resident buffer frames\n"
            ".wal                 show WAL state\n"
            ".checkpoint          checkpoint committed WAL frames\n"
            ".integrity           run structural + logical integrity check\n"
            ".reindex [INDEX]     rebuild one/all secondary indexes\n"
            ".vacuum              rewrite database into a compact file\n"
            ".freelist            show persistent free-page chain\n"
            ".incremental-vacuum [N] reclaim up to N free tail pages\n"
            ".explain SQL         show planner access path\n"
            ".explain-analyze SQL execute SELECT with actual metrics\n"
            ".bytecode SQL        compile and disassemble SQL\n"
            ".quit/.exit          leave the shell"
        )
    elif cmd == ".schema": print(db.schema_text() or "(empty schema)")
    elif cmd == ".indexes": print(db.indexes_text() or "(no secondary indexes)")
    elif cmd == ".pages": print(db.pages_text())
    elif cmd == ".txn": print(db.transaction_status())
    elif cmd == ".locks": print(db.lock_status())
    elif cmd == ".buffer": print(db.buffer_status())
    elif cmd == ".frames": print(db.buffer_frames_text())
    elif cmd == ".wal": print(db.wal_status())
    elif cmd == ".integrity":
        try: print(db.integrity_check().render())
        except MiniSQLiteError as exc: print(f"error: {exc}")
    elif cmd == ".reindex" and len(parts) <= 2:
        try: print(f"rebuilt {db.reindex(parts[1] if len(parts) == 2 else None)} index(es)")
        except MiniSQLiteError as exc: print(f"error: {exc}")
    elif cmd == ".vacuum" and len(parts) == 1:
        try: print(db.vacuum().render())
        except MiniSQLiteError as exc: print(f"error: {exc}")
    elif cmd == ".freelist" and len(parts) == 1:
        try: print(db.freelist_text())
        except MiniSQLiteError as exc: print(f"error: {exc}")
    elif cmd == ".incremental-vacuum" and len(parts) <= 2:
        try:
            limit = int(parts[1]) if len(parts) == 2 else None
            print(db.incremental_vacuum(limit).render())
        except (MiniSQLiteError, ValueError) as exc: print(f"error: {exc}")
    elif cmd == ".checkpoint":
        try: print(f"checkpointed {db.checkpoint()} page(s)")
        except MiniSQLiteError as exc: print(f"error: {exc}")
    elif cmd == ".btree" and len(parts) == 2:
        try: print(db.btree_dump(parts[1]))
        except MiniSQLiteError as exc: print(f"error: {exc}")
    elif cmd == ".index" and len(parts) == 2:
        try: print(db.index_dump(parts[1]))
        except MiniSQLiteError as exc: print(f"error: {exc}")
    elif cmd == ".explain" and len(parts) > 1:
        try: print(db.explain(" ".join(parts[1:])))
        except MiniSQLiteError as exc: print(f"error: {exc}")
    elif cmd == ".explain-analyze" and len(parts) > 1:
        try: print(db.explain_analyze(" ".join(parts[1:])).render())
        except MiniSQLiteError as exc: print(f"error: {exc}")
    elif cmd == ".bytecode" and len(parts) > 1:
        try: print(db.bytecode(" ".join(parts[1:])))
        except MiniSQLiteError as exc: print(f"error: {exc}")
    else:
        print("unknown or malformed command; use .help")
    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Educational SQLite-inspired database")
    parser.add_argument("database", nargs="?", default="mini.db")
    parser.add_argument("--journal-mode", choices=["rollback", "wal"], default="rollback", help="durability mode (default: rollback)")
    parser.add_argument("--buffer-pages", type=int, default=64, help="maximum resident pages in the buffer pool (default: 64)")
    parser.add_argument("--replacement-policy", choices=["clock", "lru"], default="clock", help="buffer replacement policy (default: clock)")
    parser.add_argument("--busy-timeout-ms", type=int, default=0, help="wait this many milliseconds for connection locks (default: 0)")
    args = parser.parse_args()
    repl(args.database, journal_mode=args.journal_mode, buffer_pages=args.buffer_pages, replacement_policy=args.replacement_policy, busy_timeout_ms=args.busy_timeout_ms)


if __name__ == "__main__":
    main()
