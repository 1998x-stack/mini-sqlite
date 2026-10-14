from __future__ import annotations

from mini_sqlite import Database
from mini_sqlite.sql import Parser
from mini_sqlite.sql.ast import AndPredicate, BetweenPredicate, CreateIndexStmt


def _seed_events(db: Database) -> None:
    db.execute(
        "CREATE TABLE events (id INTEGER PRIMARY KEY, region TEXT, ts INTEGER, note TEXT);"
    )
    rows = [
        (1, "us", 10, "a"),
        (2, "us", 20, "b"),
        (3, "us", 30, "c"),
        (4, "us", 40, "d"),
        (5, "eu", 20, "e"),
        (6, "eu", 30, "f"),
        (7, "us", None, "null"),
    ]
    for row in rows:
        values = ", ".join("NULL" if v is None else repr(v) for v in row)
        db.execute(f"INSERT INTO events VALUES ({values});")


def test_parser_composite_index_and_between_conjunction() -> None:
    stmt = Parser("CREATE INDEX idx_rt ON events(region, ts);").parse()
    assert isinstance(stmt, CreateIndexStmt)
    assert stmt.columns == ("region", "ts")
    query = Parser(
        "SELECT * FROM events WHERE region = 'us' AND ts BETWEEN 20 AND 40;"
    ).parse()
    assert isinstance(query.where, AndPredicate)
    assert isinstance(query.where.terms[1], BetweenPredicate)


def test_composite_left_prefix_and_range_scan(tmp_path) -> None:
    with Database(tmp_path / "composite.db") as db:
        _seed_events(db)
        db.execute("CREATE INDEX idx_region_ts ON events(region, ts);")

        sql = (
            "SELECT id FROM events "
            "WHERE region = 'us' AND ts BETWEEN 20 AND 40 ORDER BY id;"
        )
        assert db.execute(sql).rows == [(2,), (3,), (4,)]
        explain = db.explain(sql)
        assert "SECONDARY INDEX RANGE idx_region_ts" in explain
        assert "SEEK_INDEX_RANGE" in db.bytecode(sql)

        prefix = "SELECT id FROM events WHERE region = 'eu' ORDER BY id;"
        assert db.execute(prefix).rows == [(5,), (6,)]
        assert "SECONDARY INDEX RANGE idx_region_ts" in db.explain(prefix)

        no_prefix = "SELECT id FROM events WHERE ts >= 20 ORDER BY id;"
        assert db.execute(no_prefix).rows == [(2,), (3,), (4,), (5,), (6,)]
        assert "TABLE SCAN" in db.explain(no_prefix)


def test_composite_multiple_range_terms_are_combined(tmp_path) -> None:
    with Database(tmp_path / "bounds.db") as db:
        _seed_events(db)
        db.execute("CREATE INDEX idx_region_ts ON events(region, ts);")
        sql = (
            "SELECT id FROM events WHERE region = 'us' "
            "AND ts >= 20 AND ts < 40 ORDER BY id;"
        )
        assert db.execute(sql).rows == [(2,), (3,)]
        assert "SECONDARY INDEX RANGE idx_region_ts" in db.explain(sql)


def test_single_column_range_excludes_null_and_supports_text(tmp_path) -> None:
    with Database(tmp_path / "scalar-range.db") as db:
        _seed_events(db)
        db.execute("CREATE INDEX idx_ts ON events(ts);")
        db.execute("CREATE INDEX idx_region ON events(region);")
        assert db.execute(
            "SELECT id FROM events WHERE ts < 25 ORDER BY id;"
        ).rows == [(1,), (2,), (5,)]
        assert db.execute(
            "SELECT id FROM events WHERE region >= 'us' ORDER BY id;"
        ).rows == [(1,), (2,), (3,), (4,), (7,)]


def test_composite_index_maintained_by_update_delete_and_reopen(tmp_path) -> None:
    path = tmp_path / "maintain.db"
    with Database(path) as db:
        _seed_events(db)
        db.execute("CREATE INDEX idx_region_ts ON events(region, ts);")
        assert db.execute(
            "UPDATE events SET ts = 35 WHERE region = 'us' AND ts = 30;"
        ).rowcount == 1
        assert db.execute(
            "DELETE FROM events WHERE region = 'eu' AND ts >= 25;"
        ).rowcount == 1
        assert db.integrity_check().ok

    with Database(path) as db:
        assert db.execute(
            "SELECT id FROM events WHERE region = 'us' AND ts BETWEEN 30 AND 36;"
        ).rows == [(3,)]
        assert db.execute(
            "SELECT id FROM events WHERE region = 'eu' ORDER BY id;"
        ).rows == [(5,)]
        assert db.integrity_check().ok


def test_cost_model_can_reject_broad_range_but_choose_selective_range(tmp_path) -> None:
    with Database(tmp_path / "cost-range.db") as db:
        db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, x INTEGER);")
        for i in range(100):
            db.execute(f"INSERT INTO t VALUES ({i}, {i});")
        db.execute("CREATE INDEX idx_x ON t(x);")
        db.execute("ANALYZE t;")

        broad = db.explain("SELECT id FROM t WHERE x >= 0;")
        selective = db.explain("SELECT id FROM t WHERE x >= 95;")
        assert "TABLE SCAN" in broad
        assert "SECONDARY INDEX RANGE idx_x" in selective
        assert db.execute("SELECT id FROM t WHERE x >= 95 ORDER BY id;").rows == [
            (95,), (96,), (97,), (98,), (99,)
        ]


def test_reindex_and_vacuum_preserve_composite_index(tmp_path) -> None:
    path = tmp_path / "reindex-composite.db"
    with Database(path) as db:
        _seed_events(db)
        db.execute("CREATE INDEX idx_region_ts ON events(region, ts);")
        db.reindex("idx_region_ts")
        assert db.integrity_check().ok
        db.vacuum()
        assert db.integrity_check().ok
        assert db.execute(
            "SELECT id FROM events WHERE region = 'us' AND ts BETWEEN 10 AND 30 ORDER BY id;"
        ).rows == [(1,), (2,), (3,)]


def test_format_v2_opens_and_composite_index_persists_v3(tmp_path) -> None:
    from mini_sqlite.storage.meta import DatabaseMeta

    path = tmp_path / "format-v2.db"
    with Database(path) as db:
        db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, a TEXT, b INTEGER);")
        legacy = DatabaseMeta(
            page_size=db.meta.page_size,
            catalog_root_page=db.meta.catalog_root_page,
            next_table_id=db.meta.next_table_id,
            version=2,
            free_list_head=db.meta.free_list_head,
        )
        db.pager.write_page(0, legacy.encode())
        db.flush()

    with Database(path) as db:
        assert db.meta.version == 3
        db.execute("CREATE INDEX idx_ab ON t(a, b);")
        with db.pager.pin_page(0) as raw:
            persisted = DatabaseMeta.decode(raw)
        assert persisted.version == 3
        assert db.schema_text().splitlines()[-1] == "CREATE INDEX idx_ab ON t(a, b);"
