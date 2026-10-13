from __future__ import annotations

from mini_sqlite import Database
from mini_sqlite.planner.plan import AccessPath, JoinSelectPlan, SelectPlan
from mini_sqlite.sql import Parser
from mini_sqlite.sql.ast import AnalyzeStmt


def _build_skewed(db: Database) -> None:
    db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, grp INTEGER, name TEXT);")
    for i in range(1, 101):
        grp = 1 if i <= 90 else i
        db.execute(f"INSERT INTO users VALUES ({i}, {grp}, 'u{i}');")
    db.execute("CREATE INDEX idx_users_grp ON users(grp);")


def test_parse_analyze_variants():
    assert Parser("ANALYZE;").parse() == AnalyzeStmt(None)
    assert Parser("ANALYZE users;").parse() == AnalyzeStmt("users")


def test_analyze_statistics_persist_and_are_observable(tmp_path):
    path = tmp_path / "stats.db"
    with Database(path) as db:
        _build_skewed(db)
        assert db.catalog.get_table("users").stats is None
        result = db.execute("ANALYZE users;")
        assert result.rowcount == 1
        stats = db.catalog.get_table("users").stats
        assert stats is not None and stats.row_count == 100
        grp = stats.column("grp")
        assert grp is not None and grp.distinct_count == 11
        assert (1, 90) in grp.most_common

    with Database(path) as reopened:
        assert reopened.catalog.get_table("users").stats is not None
        assert reopened.catalog.get_table("users").stats.row_count == 100


def test_cost_model_rejects_low_selectivity_index_but_uses_rare_lookup(tmp_path):
    with Database(tmp_path / "selectivity.db") as db:
        _build_skewed(db)
        before = db.planner.plan(Parser("SELECT * FROM users WHERE grp = 1;").parse())
        assert isinstance(before, SelectPlan)
        assert before.access_path == AccessPath.SECONDARY_INDEX
        assert before.estimated_cost is None

        db.execute("ANALYZE users;")
        hot = db.planner.plan(Parser("SELECT * FROM users WHERE grp = 1;").parse())
        rare = db.planner.plan(Parser("SELECT * FROM users WHERE grp = 95;").parse())
        assert isinstance(hot, SelectPlan) and isinstance(rare, SelectPlan)
        assert hot.access_path == AccessPath.TABLE_SCAN
        assert hot.estimated_rows == 90
        assert rare.access_path == AccessPath.SECONDARY_INDEX
        assert rare.estimated_rows == 1
        assert hot.estimated_cost < next(
            alt.estimated_cost for alt in hot.alternatives if "SECONDARY" in alt.name
        )
        assert "CANDIDATES" in db.explain("SELECT * FROM users WHERE grp = 1;")


def test_range_selectivity_uses_analyzed_min_max(tmp_path):
    with Database(tmp_path / "range.db") as db:
        db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v INTEGER);")
        for i in range(1, 102):
            db.execute(f"INSERT INTO t VALUES ({i}, {i});")
        db.execute("ANALYZE t;")

        plan = db.planner.plan(Parser("SELECT * FROM t WHERE v < 50;").parse())
        assert isinstance(plan, SelectPlan)
        assert plan.access_path == AccessPath.TABLE_SCAN
        assert plan.estimated_rows is not None
        assert 45 <= plan.estimated_rows <= 55


def test_stats_are_snapshots_until_analyze_runs_again(tmp_path):
    with Database(tmp_path / "stale.db") as db:
        db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v INTEGER);")
        db.execute("INSERT INTO t VALUES (1, 10);")
        db.execute("ANALYZE t;")
        assert db.catalog.get_table("t").stats.row_count == 1
        db.execute("INSERT INTO t VALUES (2, 20);")
        assert db.catalog.get_table("t").stats.row_count == 1
        db.execute("ANALYZE t;")
        assert db.catalog.get_table("t").stats.row_count == 2


def test_analyze_participates_in_rollback_transaction(tmp_path):
    with Database(tmp_path / "rollback-stats.db") as db:
        db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v INTEGER);")
        db.execute("INSERT INTO t VALUES (1, 1);")
        db.execute("BEGIN;")
        db.execute("ANALYZE t;")
        assert db.catalog.get_table("t").stats is not None
        db.execute("ROLLBACK;")
        assert db.catalog.get_table("t").stats is None


def test_join_order_reverses_to_smaller_outer_without_indexes(tmp_path):
    with Database(tmp_path / "join-order.db") as db:
        db.execute("CREATE TABLE big (id INTEGER PRIMARY KEY, k INTEGER);")
        db.execute("CREATE TABLE small (id INTEGER PRIMARY KEY, k INTEGER);")
        for i in range(1, 101):
            db.execute(f"INSERT INTO big VALUES ({i}, {i % 10});")
        for i in range(1, 6):
            db.execute(f"INSERT INTO small VALUES ({i}, {i});")
        db.execute("ANALYZE;")
        sql = "SELECT big.id, small.id FROM big JOIN small ON big.k = small.k;"
        plan = db.planner.plan(Parser(sql).parse())
        assert isinstance(plan, JoinSelectPlan)
        assert plan.outer_side == 1
        assert plan.inner_access_path == AccessPath.TABLE_SCAN
        assert "PHYSICAL ORDER small -> big" in db.explain(sql)
        rows = db.execute(sql).rows
        assert len(rows) == 50
        assert (1, 1) in rows


def test_join_order_can_reverse_into_secondary_index_probe(tmp_path):
    with Database(tmp_path / "join-index.db") as db:
        db.execute("CREATE TABLE big (id INTEGER PRIMARY KEY, k INTEGER);")
        db.execute("CREATE TABLE small (id INTEGER PRIMARY KEY, k INTEGER);")
        for i in range(1, 101):
            db.execute(f"INSERT INTO big VALUES ({i}, {i % 10});")
        for i in range(1, 6):
            db.execute(f"INSERT INTO small VALUES ({i}, {i});")
        db.execute("CREATE INDEX idx_big_k ON big(k);")
        db.execute("ANALYZE;")
        sql = "SELECT big.id, small.id FROM big JOIN small ON big.k = small.k;"
        plan = db.planner.plan(Parser(sql).parse())
        assert isinstance(plan, JoinSelectPlan)
        assert plan.outer_side == 1
        assert plan.inner_access_path == AccessPath.SECONDARY_INDEX
        assert plan.inner_index is not None and plan.inner_index.name == "idx_big_k"
        assert "INNER SECONDARY INDEX idx_big_k" in db.explain(sql)
        assert len(db.execute(sql).rows) == 50


def test_wal_analyze_survives_reopen_and_checkpoint(tmp_path):
    path = tmp_path / "wal-stats.db"
    with Database(path, journal_mode="wal", buffer_pages=4) as db:
        db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v INTEGER);")
        for i in range(1, 21):
            db.execute(f"INSERT INTO t VALUES ({i}, {i % 3});")
        db.execute("CREATE INDEX idx_t_v ON t(v);")
        db.execute("ANALYZE t;")
        assert db.catalog.get_table("t").stats.row_count == 20
    with Database(path, journal_mode="wal", buffer_pages=4) as reopened:
        assert reopened.catalog.get_table("t").stats.row_count == 20
        reopened.checkpoint()
    with Database(path, journal_mode="rollback", buffer_pages=4) as rollback:
        assert rollback.catalog.get_table("t").stats.row_count == 20
