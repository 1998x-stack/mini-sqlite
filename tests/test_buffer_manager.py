from __future__ import annotations

import pytest

from mini_sqlite import Database
from mini_sqlite.constants import PAGE_SIZE
from mini_sqlite.errors import BufferPoolFullError
from mini_sqlite.storage.pager import Pager


def _make_raw_pages(path, count: int = 4) -> None:
    with Pager(path, buffer_pages=2, replacement_policy="lru") as pager:
        for i in range(count):
            page_id = pager.allocate_page()
            pager.write_page(page_id, bytes([i + 1]) * PAGE_SIZE)
            pager.flush_page(page_id)


def test_lru_eviction_keeps_recently_touched_page(tmp_path):
    path = tmp_path / "lru.db"
    _make_raw_pages(path)

    with Pager(path, buffer_pages=2, replacement_policy="lru") as pager:
        assert pager.get_page(0)[0] == 1
        assert pager.get_page(1)[0] == 2
        assert pager.get_page(0)[0] == 1  # page 0 becomes MRU
        assert pager.get_page(2)[0] == 3

        resident = {row["page_id"] for row in pager.buffer_snapshot()}
        assert resident == {0, 2}
        stats = pager.buffer_stats()
        assert stats["hits"] >= 1
        assert stats["misses"] == 3
        assert stats["evictions"] == 1


def test_clock_replacement_is_bounded_and_uses_second_chance(tmp_path):
    path = tmp_path / "clock.db"
    _make_raw_pages(path)

    with Pager(path, buffer_pages=2, replacement_policy="clock") as pager:
        pager.get_page(0)
        pager.get_page(1)
        pager.get_page(2)
        resident = {row["page_id"] for row in pager.buffer_snapshot()}
        assert len(resident) == 2
        assert 2 in resident
        assert pager.buffer_stats()["evictions"] == 1


def test_pin_prevents_eviction_until_unpinned(tmp_path):
    path = tmp_path / "pin.db"
    _make_raw_pages(path, count=2)

    with Pager(path, buffer_pages=1, replacement_policy="lru") as pager:
        with pager.pin_page(0) as page:
            assert page[0] == 1
            with pytest.raises(BufferPoolFullError):
                pager.get_page(1)
        assert pager.get_page(1)[0] == 2
        assert pager.buffer_stats()["evictions"] == 1


def test_rollback_mode_can_evict_dirty_pages_without_losing_atomicity(tmp_path):
    path = tmp_path / "rollback-evict.db"
    with Database(path, buffer_pages=3, replacement_policy="lru") as db:
        db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, body TEXT);")
        db.execute("BEGIN;")
        for i in range(90):
            db.execute(f"INSERT INTO items VALUES ({i}, '{'x' * 180}{i}');")
        assert db.pager.buffer_stats()["dirty_evictions"] > 0
        db.execute("ROLLBACK;")
        assert db.execute("SELECT * FROM items;").rows == []

    with Database(path, buffer_pages=3, replacement_policy="lru") as reopened:
        assert reopened.execute("SELECT * FROM items;").rows == []


def test_wal_committed_frames_remain_readable_under_small_buffer(tmp_path):
    path = tmp_path / "wal-buffer.db"
    with Database(
        path,
        journal_mode="wal",
        buffer_pages=4,
        replacement_policy="clock",
    ) as db:
        db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, body TEXT);")
        for i in range(100):
            db.execute(f"INSERT INTO items VALUES ({i}, '{'y' * 140}{i}');")
        rows = db.execute("SELECT * FROM items ORDER BY id;").rows
        assert len(rows) == 100
        assert db.pager.buffer_stats()["evictions"] > 0
        assert db.pager.buffer_stats()["resident"] <= 4

    with Database(
        path,
        journal_mode="wal",
        buffer_pages=3,
        replacement_policy="lru",
    ) as reopened:
        assert reopened.execute("SELECT body FROM items WHERE id = 99;").rows == [
            ("y" * 140 + "99",)
        ]
        assert reopened.pager.buffer_stats()["resident"] <= 3


def test_wal_active_dirty_working_set_has_explicit_buffer_limit(tmp_path):
    path = tmp_path / "wal-working-set.db"
    with Database(
        path,
        journal_mode="wal",
        buffer_pages=3,
        replacement_policy="lru",
    ) as db:
        db.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, body TEXT);")
        db.execute("BEGIN;")
        with pytest.raises(BufferPoolFullError):
            for i in range(100):
                db.execute(f"INSERT INTO items VALUES ({i}, '{'z' * 220}{i}');")
        # Statement failure aborts the whole active transaction by project policy.
        assert db.in_transaction is False
        assert db.execute("SELECT * FROM items;").rows == []


def test_buffer_stats_and_frames_are_observable(tmp_path):
    path = tmp_path / "stats.db"
    with Database(path, buffer_pages=2, replacement_policy="lru") as db:
        db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, body TEXT);")
        db.execute("INSERT INTO t VALUES (1, 'a');")
        db.execute("SELECT * FROM t WHERE id = 1;")
        text = db.buffer_status()
        assert "policy=lru" in text
        assert "capacity=2" in text
        assert "hits=" in text
        frames = db.buffer_frames_text()
        assert "PAGE  DIRTY  PIN" in frames


def test_indexed_join_remains_correct_with_three_page_buffer(tmp_path):
    path = tmp_path / "tiny-join.db"
    with Database(path, buffer_pages=3, replacement_policy="clock") as db:
        db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);")
        db.execute(
            "CREATE TABLE orders (id INTEGER PRIMARY KEY, user_id INTEGER, item TEXT);"
        )
        db.execute("CREATE INDEX idx_orders_user ON orders(user_id);")
        for i in range(1, 21):
            db.execute(f"INSERT INTO users VALUES ({i}, 'u{i}');")
            for j in range(3):
                oid = i * 10 + j
                db.execute(
                    f"INSERT INTO orders VALUES ({oid}, {i}, '{'q' * 80}{oid}');"
                )

        sql = (
            "SELECT u.name, o.item FROM users u "
            "JOIN orders o ON u.id = o.user_id "
            "WHERE u.id >= 18 ORDER BY o.id;"
        )
        rows = db.execute(sql).rows
        assert len(rows) == 9
        assert rows[0][0] == "u18"
        assert rows[-1][0] == "u20"
        assert db.pager.buffer_stats()["resident"] <= 3
        assert db.pager.buffer_stats()["evictions"] > 0
