from mini_sqlite.btree import BTree
from mini_sqlite.storage.pager import Pager


def test_btree_split_search_scan_and_reopen(tmp_path):
    path = tmp_path / "tree.db"
    with Pager(path) as pager:
        # Reserve page 0 like a normal database would.
        pager.allocate_page()
        tree = BTree.create(pager)
        original_root = tree.root_page
        for i in range(350):
            tree.insert(i, (f"value-{i}-" + "x" * 40).encode())
        assert tree.root_page != original_root
        root_after_split = tree.root_page
        assert tree.search(0).startswith(b"value-0-")
        assert tree.search(349).startswith(b"value-349-")
        assert [k for k, _ in tree.scan()] == list(range(350))
        assert tree.delete(123) is True
        assert tree.search(123) is None
        pager.flush_all()

    with Pager(path) as pager:
        tree = BTree(pager, root_after_split)
        assert tree.search(200).startswith(b"value-200-")
        assert tree.search(123) is None


def test_btree_internal_split(tmp_path):
    path = tmp_path / "big-tree.db"
    with Pager(path) as pager:
        pager.allocate_page()
        tree = BTree.create(pager)
        payload = b"z" * 650
        # Large values force many leaf pages and eventually an internal split.
        for i in range(2200):
            tree.insert(i, payload + str(i).encode())
        for i in (0, 1, 777, 1500, 2199):
            assert tree.search(i).startswith(payload)
        assert sum(1 for _ in tree.scan()) == 2200
