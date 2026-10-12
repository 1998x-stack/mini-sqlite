from mini_sqlite.storage.record import RecordCodec


def test_record_roundtrip():
    row = (42, "Alice", None, -7, "你好")
    assert RecordCodec.decode(RecordCodec.encode(row)) == row
