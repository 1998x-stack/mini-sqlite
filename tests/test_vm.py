from mini_sqlite import Database


def test_bytecode_exposes_relational_scan_pipeline(tmp_path):
    with Database(tmp_path / "vm.db") as db:
        db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, value TEXT);")
        text = db.bytecode("SELECT value FROM t WHERE value = 'x';")
        assert "OPEN_READ" in text
        assert "REWIND" in text
        assert "FILTER_COMPARE" in text
        assert "COLLECT_ROW" in text
        assert "PROJECT_ROWS" in text
        assert "EMIT_ROWS" in text
        assert "NEXT" in text
