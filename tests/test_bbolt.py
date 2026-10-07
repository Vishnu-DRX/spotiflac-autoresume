"""bbolt reader tests on hand-built databases (no Go toolchain needed)."""
import struct

from spotiflac_autoresume import bbolt_read as bb

PAGE = 4096


def leaf(entries, page_id=0):
    """Build a leaf page. entries = [(flags, key, value)]. Returns bytes (unpadded)."""
    n = len(entries)
    head = struct.pack("<QHHI", page_id, bb.LEAF, n, 0)
    elems, data = b"", b""
    data_start = 16 + n * 16
    for i, (flags, k, v) in enumerate(entries):
        elem_off = 16 + i * 16
        pos = data_start + len(data) - elem_off
        elems += struct.pack("<IIII", flags, pos, len(k), len(v))
        data += k + v
    return head + elems + data


def meta_page(page_id, root_pgid, txid):
    body = struct.pack("<IIII", bb.MAGIC, 2, PAGE, 0)
    body += struct.pack("<QQQQQQ", root_pgid, 0, 0, 0, txid, 0)
    return struct.pack("<QHHI", page_id, bb.META, 0, 0) + body


def pad(b):
    return b + b"\0" * (PAGE - len(b))


def build(pages_after_meta, root_pgid=2, txids=(1, 2)):
    meta0 = pad(meta_page(0, root_pgid, txids[0]))
    meta1 = pad(meta_page(1, root_pgid, txids[1]))
    return meta0 + meta1 + b"".join(pad(p) for p in pages_after_meta)


def test_inline_nested_bucket(tmp_path):
    inline = struct.pack("<QQ", 0, 0) + leaf([(0, b"id-1", b'{"name":"A"}'), (0, b"id-2", b'{"name":"B"}')])
    root = leaf([(bb.BUCKET_FLAG, b"DownloadQueueItems", inline)], page_id=2)
    f = tmp_path / "q.db"
    f.write_bytes(build([root]))
    assert bb.read_bucket(f, "DownloadQueueItems") == {b"id-1": b'{"name":"A"}', b"id-2": b'{"name":"B"}'}


def test_bucket_stored_on_its_own_page(tmp_path):
    items = leaf([(0, b"k", b"v")], page_id=3)
    root = leaf([(bb.BUCKET_FLAG, b"DownloadQueueItems", struct.pack("<QQ", 3, 0))], page_id=2)
    f = tmp_path / "q.db"
    f.write_bytes(build([root, items]))
    assert bb.read_bucket(f, "DownloadQueueItems") == {b"k": b"v"}


def test_missing_bucket_returns_empty(tmp_path):
    root = leaf([(bb.BUCKET_FLAG, b"Other", struct.pack("<QQ", 0, 0) + leaf([]))], page_id=2)
    f = tmp_path / "q.db"
    f.write_bytes(build([root]))
    assert bb.read_bucket(f, "DownloadQueueItems") == {}


def test_newest_meta_page_wins(tmp_path):
    old_items = leaf([(0, b"k", b"old")], page_id=3)
    new_items = leaf([(0, b"k", b"new")], page_id=4)
    root_old = leaf([(bb.BUCKET_FLAG, b"B", struct.pack("<QQ", 3, 0))], page_id=2)
    root_new = leaf([(bb.BUCKET_FLAG, b"B", struct.pack("<QQ", 4, 0))], page_id=5)
    data = bytearray(build([root_old, old_items, new_items, root_new], root_pgid=2, txids=(1, 2)))
    # meta0 (txid 9) points at the new root (page 5); meta1 (txid 2) still points at the old one
    data[0:PAGE] = pad(meta_page(0, 5, 9))
    f = tmp_path / "q.db"
    f.write_bytes(bytes(data))
    assert bb.read_bucket(f, "B") == {b"k": b"new"}
