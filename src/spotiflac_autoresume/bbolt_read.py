"""Minimal read-only reader for the bbolt (Go) database format used by SpotiFLAC.

bbolt is copy-on-write: the newest committed state is reachable from whichever
of the two meta pages has the higher txid. Scanning the raw bytes for JSON (as
peek_queue.py does) can return stale copies, so this walks the real B+tree.
"""
import struct

MAGIC = 0xED0CDAED
LEAF, BRANCH, META = 0x02, 0x01, 0x04
BUCKET_FLAG = 0x01


def _meta(buf, pgsize_guess=4096):
    best = None
    for pg in (0, 1):
        off = pg * pgsize_guess
        flags = struct.unpack_from("<H", buf, off + 8)[0]
        if not flags & META:
            continue
        magic, version, pagesize, _f = struct.unpack_from("<IIII", buf, off + 16)
        if magic != MAGIC:
            continue
        root, _seq, _fl, _pgid, txid = struct.unpack_from("<QQQQQ", buf, off + 16 + 16)
        if best is None or txid > best[0]:
            best = (txid, pagesize, root)
    if best is None:
        raise ValueError("no valid bbolt meta page")
    return best[1], best[2]


def _walk(buf, off, pagesize):
    """Yield (flags, key, value) for every leaf element under the page at `off`."""
    _id, flags, count, _ovf = struct.unpack_from("<QHHI", buf, off)
    if flags & LEAF:
        for i in range(count):
            e = off + 16 + i * 16
            eflags, pos, ksize, vsize = struct.unpack_from("<IIII", buf, e)
            k = e + pos
            yield eflags, bytes(buf[k:k + ksize]), (k + ksize, vsize)
    elif flags & BRANCH:
        for i in range(count):
            e = off + 16 + i * 16
            _pos, _ksize, pgid = struct.unpack_from("<IIQ", buf, e)
            yield from _walk(buf, pgid * pagesize, pagesize)
    else:
        raise ValueError(f"unexpected page flags {flags:#x} at {off}")


def _bucket_entries(buf, bucket_val, pagesize):
    """bucket_val = (offset, size) of a bucket header; returns its leaf entries."""
    voff, _ = bucket_val
    root, _seq = struct.unpack_from("<QQ", buf, voff)
    start = voff + 16 if root == 0 else root * pagesize   # root==0 -> inline bucket
    return _walk(buf, start, pagesize)


def read_bucket(path, *bucket_path):
    """Return {key(bytes): value(bytes)} for the nested bucket at bucket_path."""
    with open(path, "rb") as f:
        buf = f.read()
    pagesize, root = _meta(buf)
    entries = _walk(buf, root * pagesize, pagesize)
    for name in bucket_path:
        found = None
        for eflags, key, val in entries:
            if eflags & BUCKET_FLAG and key.decode("utf-8", "ignore") == name:
                found = val
                break
        if found is None:
            return {}
        entries = _bucket_entries(buf, found, pagesize)
    out = {}
    for eflags, key, (voff, vsize) in entries:
        if not eflags & BUCKET_FLAG:
            out[key] = bytes(buf[voff:voff + vsize])
    return out
