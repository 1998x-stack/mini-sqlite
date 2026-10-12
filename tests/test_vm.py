from mini_sqlite import Database


def test_bytecode_exposes_scan_loop(tmp_path):
    with Database(tmp_path / "vm.db") as db:
        db.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, value TEXT);")
        text = db.bytecode("SELECT value FROM t WHERE value = 'x';")
        assert "OPEN_READ" in text
        assert "REWIND" in text
        assert "FILTER_EQ" in text
        assert "NEXT" in text
        assert "RESULT_ROW" in text
