from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mini_sqlite import Database


def measure(db: Database, sql: str, repeats: int = 40) -> tuple[float, int, int]:
    before = db.pager.buffer_stats()
    samples: list[float] = []
    for _ in range(repeats):
        start = time.perf_counter_ns()
        db.execute(sql)
        samples.append((time.perf_counter_ns() - start) / 1_000_000)
    after = db.pager.buffer_stats()
    return (
        statistics.median(samples),
        int(after["hits"]) - int(before["hits"]),
        int(after["misses"]) - int(before["misses"]),
    )


def main() -> None:
    path = Path("benchmark.db")
    for candidate in (path, Path(str(path) + "-journal"), Path(str(path) + "-wal")):
        if candidate.exists():
            candidate.unlink()

    with Database(path, buffer_pages=8) as db:
        db.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, bucket INTEGER, payload TEXT);")
        for i in range(1, 801):
            bucket = 1 if i <= 720 else i
            db.execute(f"INSERT INTO events VALUES ({i}, {bucket}, 'payload-{i:04d}');")
        db.execute("CREATE INDEX idx_events_bucket ON events(bucket);")
        db.execute("ANALYZE events;")

        hot = "SELECT id FROM events WHERE bucket = 1;"
        rare = "SELECT id FROM events WHERE bucket = 800;"
        print("hot plan:", db.explain(hot))
        print("rare plan:", db.explain(rare))

        hot_ms, hot_hits, hot_misses = measure(db, hot)
        rare_ms, rare_hits, rare_misses = measure(db, rare)
        print(
            f"hot median_ms={hot_ms:.3f} hits={hot_hits} misses={hot_misses} "
            "(usually table scan due to low selectivity)"
        )
        print(
            f"rare median_ms={rare_ms:.3f} hits={rare_hits} misses={rare_misses} "
            "(usually secondary-index lookup)"
        )

    for candidate in (path, Path(str(path) + "-journal"), Path(str(path) + "-wal")):
        if candidate.exists():
            candidate.unlink()


if __name__ == "__main__":
    main()
