from mini_sqlite import Database


def create_users(db):
    db.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, age INTEGER);"
    )


def test_end_to_end_and_reopen(tmp_path):
    path = tmp_path / "demo.db"
    with Database(path) as db:
        create_users(db)
        db.execute("INSERT INTO users VALUES (1, 'Alice', 20);")
        db.execute("INSERT INTO users VALUES (2, 'Bob', 25);")
        db.execute("INSERT INTO users VALUES (3, 'Carol', 20);")

        result = db.execute("SELECT * FROM users WHERE id = 2;")
        assert result.columns == ["id", "name", "age"]
        assert result.rows == [(2, "Bob", 25)]
        assert "PRIMARY-KEY LOOKUP" in db.explain("SELECT * FROM users WHERE id = 2;")

        result = db.execute("SELECT name FROM users WHERE age = 20;")
        assert result.rows == [("Alice",), ("Carol",)]
        assert "TABLE SCAN" in db.explain("SELECT name FROM users WHERE age = 20;")

        deleted = db.execute("DELETE FROM users WHERE id = 1;")
        assert deleted.rowcount == 1
        assert db.execute("SELECT * FROM users;").rows == [
            (2, "Bob", 25),
            (3, "Carol", 20),
        ]
        assert "SEEK_PK" in db.bytecode("SELECT * FROM users WHERE id = 3;")

    with Database(path) as db:
        assert db.execute("SELECT name FROM users WHERE id = 2;").rows == [("Bob",)]
        assert "CREATE TABLE users" in db.schema_text()


def test_table_root_split_is_persisted_in_catalog(tmp_path):
    path = tmp_path / "split.db"
    with Database(path) as db:
        db.execute("CREATE TABLE docs (id INTEGER PRIMARY KEY, body TEXT);")
        initial_root = db.catalog.get_table("docs").root_page
        for i in range(180):
            db.execute(f"INSERT INTO docs VALUES ({i}, '{'x' * 80}{i}');")
        new_root = db.catalog.get_table("docs").root_page
        assert new_root != initial_root
        assert db.execute("SELECT body FROM docs WHERE id = 179;").rows[0][0].endswith("179")

    with Database(path) as db:
        assert db.execute("SELECT body FROM docs WHERE id = 179;").rows[0][0].endswith("179")
