"""Damages a Susz file of version 2 (docs/susz.md) in one of a few ways, for
tests/susz.sh: python3 -I suszbad.py MODE IN OUT. Prints nothing and exits 3
when the file has no place the mode can damage (no proof blocks, say).

Each mode names what the reader must find, and where (docs/susz.md, rule 4):
a damaged proof block is its declaration's error, reported in the order of
declarations; damage outside the blocks rejects the file before checking.

Modes:
  tag        the first record of the first block gets the unknown tag 99
  twotags    the same in the first and the last block: the first is the one
             reported, whatever the number of workers
  lastblock  the same in the last block only
  count      the first block's count one higher: it ends inside a record
  fewer      the first block's count one lower: bytes after its last record
  hugecount  the first block's count 2^40
  ref        the first application of a block names an expression
             past the frontier listed before its declaration
  late       an application of a block names the first frontier expression
             listed after its declaration record, which exists
  mark       the first mark record of the first block says a declaration
             after its own
  markdown   the same mark record says declaration 0: the block's names are
             then not placed before it, against its placed byte (exits 3
             when the block names none)
  placed     the first lazy theorem's placed byte flipped
  length     the first lazy theorem's block one byte longer: the blocks no
             longer fill the proof section
  section    the trailer's proof section one byte shorter
  frontier   the first frontier record names nothing (0 back)
  version    the version byte says 3
"""
import struct
import sys


def rv(b, p):
    v, s = 0, 0
    while True:
        x = b[p]
        p += 1
        v |= (x & 127) << s
        if x < 128:
            return v, p
        s += 7


def wv(n):
    out = bytearray()
    while True:
        x = n & 127
        n >>= 7
        if n == 0:
            out.append(x)
            return bytes(out)
        out.append(x | 128)


def skip_n(b, p, n):
    for _ in range(n):
        _, p = rv(b, p)
    return p


def skip_list(b, p):
    n, p = rv(b, p)
    return skip_n(b, p, n)


def skip_text(b, p):
    n, p = rv(b, p)
    return p + n


def skip_head(b, p):
    p = skip_n(b, p, 1)
    p = skip_list(b, p)
    return skip_n(b, p, 1)


def skip_record(b, p):
    """Past the main-block record at p; for a lazy theorem (kind 6) also
    where its length and its placed byte are."""
    t = b[p]
    q = p + 1
    if t == 1:
        return skip_text(b, skip_n(b, q, 1)), None
    if t in (2, 4, 5, 10):
        return skip_n(b, q, 2), None
    if t in (3, 6, 7, 8, 17):
        return skip_n(b, q, 1), None
    if t == 9:
        return skip_list(b, skip_n(b, q, 1)), None
    if t in (11, 12):
        return skip_n(b, q + 1, 3), None
    if t == 13:
        return skip_n(b, q, 4), None
    if t in (14, 15):
        return skip_text(b, q), None
    if t == 16:
        return skip_n(b, q, 3), None
    if t == 19:
        return skip_n(b, q + 1, 1), None
    if t == 18:
        return skip_decl(b, q)
    raise ValueError("tag %d at %d" % (t, p))


def skip_decl(b, p):
    k = b[p]
    p += 1
    if k == 0:
        return skip_head(b, p) + 1, None
    if k == 1:
        p = skip_n(b, skip_head(b, p), 1)
        if b[p] == 2:
            p = skip_n(b, p + 1, 1)
        else:
            p += 1
        return skip_list(b, p + 1), None
    if k == 2:
        return skip_list(b, skip_n(b, skip_head(b, p), 1)), None
    if k == 3:
        return skip_list(b, skip_n(b, skip_head(b, p), 1) + 1), None
    if k == 4:
        return skip_head(b, p) + 1, None
    if k == 6:
        at = skip_head(b, p)
        length, q = rv(b, at)
        return skip_list(b, q + 1), (at, length, q)
    n, p = rv(b, p)
    for _ in range(n):
        p = skip_head(b, p) + 1
        p = skip_n(b, p, 2)
        p = skip_list(b, skip_list(b, p))
        p = skip_n(b, p, 1) + 2
    n, p = rv(b, p)
    for _ in range(n):
        p = skip_n(b, skip_head(b, p) + 1, 4)
    n, p = rv(b, p)
    for _ in range(n):
        p = skip_n(b, skip_list(b, skip_head(b, p) + 1), 4)
        r, p = rv(b, p)
        p = skip_n(b, p, 3 * r) + 1
    return p, None


class File:
    def __init__(self, b):
        self.b = bytearray(b)
        n = len(b)
        assert b[4] == 2 and struct.unpack("<I", b[n - 8 : n - 4])[0] == 56
        t = b[n - 56 :]
        self.counts = struct.unpack("<4I", t[:16])
        self.moff, self.mlen, self.poff, self.plen = struct.unpack("<4Q", t[16:48])
        self.lazy = []  # (at of length, length, at of placed byte, declaration)
        self.frontier = []
        self.blocks = []  # (offset in file, length)
        self.fe = []  # frontier expressions listed before each lazy theorem
        p, end, off, d, fe = self.moff, self.moff + self.mlen, self.poff, 0, 0
        while p < end:
            if b[p] == 19:
                self.frontier.append(p)
                fe += b[p + 1] == 2
            q, z = skip_record(b, p)
            if z:
                self.fe.append(fe)
                self.lazy.append(z + (d,))
                self.blocks.append((off, z[1]))
                off += z[1]
            if b[p] == 18:
                d += 1
            p = q

    def replaced(self, j, new):
        """The file with block j's bytes replaced by new, its declaration's
        length, the main block and the trailer following."""
        b = self.b
        at, length, q, _ = self.lazy[j]
        off, _ = self.blocks[j]
        w = wv(len(new))
        grow = len(w) - (q - at)
        out = b[: at] + w + b[q:off] + new + b[off + length : len(b) - 56]
        self.mlen += grow
        self.poff += grow
        self.plen += len(new) - length
        return out + self.trailer()

    def trailer(self):
        t = struct.pack("<4I", *self.counts) + struct.pack("<4Q", self.moff, self.mlen, self.poff, self.plen)
        return t + struct.pack("<I", 56) + b"ZSUS"

    def first_record(self, j):
        """Where block j's first expression record and its first mark are."""
        off, length = self.blocks[j]
        _, p = rv(self.b, off)
        mark = None
        while self.b[p] == 19:
            mark = mark if mark is not None else p
            p = skip_n(self.b, p + 1, 1)
        return p, mark


def main():
    mode, src, dst = sys.argv[1], sys.argv[2], sys.argv[3]
    f = File(open(src, "rb").read())
    b = f.b
    if mode == "version":
        b[4] = 3
    elif mode == "frontier":
        if not f.frontier:
            sys.exit(3)
        b[f.frontier[0] + 2] = 0
    elif mode == "section":
        f.plen -= 1
        b[len(b) - 56 :] = f.trailer()
    elif not f.blocks:
        sys.exit(3)
    elif mode in ("tag", "twotags", "lastblock"):
        js = {"tag": [0], "twotags": [0, len(f.blocks) - 1], "lastblock": [len(f.blocks) - 1]}[mode]
        if mode == "twotags" and len(f.blocks) < 2:
            sys.exit(3)
        for j in js:
            p, _ = f.first_record(j)
            b[p] = 99
    elif mode in ("count", "fewer", "hugecount"):
        off, length = f.blocks[0]
        n, p = rv(b, off)
        m = {"count": n + 1, "fewer": n - 1, "hugecount": 1 << 40}[mode]
        b = f.replaced(0, wv(m) + b[p : off + length])
    elif mode == "ref":
        for j, (off, length) in enumerate(f.blocks):
            n, p = rv(b, off)
            k = 0
            while k < n and b[p] != 10:
                if b[p] == 19:
                    p = skip_n(b, p + 1, 1)
                else:
                    k += 1
                    p, _ = skip_record(b, p)
            if k < n:
                _, q = rv(b, p + 1)
                b = f.replaced(j, b[off : p + 1] + wv(1 << 30) + b[q : off + length])
                break
        else:
            sys.exit(3)
    elif mode == "late":
        total = sum(1 for x in f.frontier if b[x + 1] == 2)
        for j, (off, length) in enumerate(f.blocks):
            if f.fe[j] >= total:
                continue
            n, p = rv(b, off)
            k = 0
            while k < n and b[p] != 10:
                if b[p] == 19:
                    p = skip_n(b, p + 1, 1)
                else:
                    k += 1
                    p, _ = skip_record(b, p)
            if k < n:
                _, q = rv(b, p + 1)
                b = f.replaced(j, b[off : p + 1] + wv(k + 1 + f.fe[j]) + b[q : off + length])
                break
        else:
            sys.exit(3)
    elif mode in ("mark", "markdown"):
        off, length = f.blocks[0]
        _, m = f.first_record(0)
        if m is None:
            sys.exit(3)
        _, q = rv(b, m + 1)
        to = f.lazy[0][3] + 1 if mode == "mark" else 0
        if mode == "markdown" and b[f.lazy[0][2]] == 0:
            sys.exit(3)
        b = f.replaced(0, b[off : m + 1] + wv(to) + b[q : off + length])
    elif mode == "placed":
        at, length, q, _ = f.lazy[0]
        b[q] ^= 1
    elif mode == "length":
        at, length, q, _ = f.lazy[0]
        w = wv(length + 1)
        if len(w) != q - at:
            sys.exit(3)
        b[at:q] = w
    else:
        sys.exit("unknown mode " + mode)
    open(dst, "wb").write(bytes(b))


main()
