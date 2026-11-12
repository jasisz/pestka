"""Damages a Susz 1 file (the Susz 1 spec, docs/susz.md) in one of a few
ways, for tests/susz.sh: python3 -I suszbad.py MODE IN OUT. Prints nothing
and exits 3 when the file has no place the mode can damage (no proof blocks,
say).

The file is taken apart into its sections and put together again, so a
mode may change a section's length: the directory follows. INDEX is copied
as it is, and so goes stale when MAIN changes, which a full check must not
notice (it never reads INDEX).

Each mode names what the reader must find, and where (spec section 8): a
damaged proof block is its theorem's error, reported in the order of
declarations; damage outside the blocks rejects the file before checking.

Modes:
  tag        the first record of the first block gets the unknown tag 99
  twotags    the same in the first and the last block: the first is the one
             reported, whatever the number of workers
  lastblock  the same in the last block only
  tag17      the first record of the first block gets tag 17 (mdata, retired)
  tag19      the first record of the first block gets tag 19 (frontier)
  count      the first block's count (in its theorem's record) one higher:
             the block ends inside a record
  fewer      the first block's count one lower: bytes after its last record
  hugecount  the first block's count larger than its bytes can hold
  ref        the first application of a block names an expression past the
             frontier listed before its declaration
  late       an application of a block names the first frontier expression
             listed after its declaration record, which exists
  rulep      a constant of a block names a frontier name not declared before
             its theorem (rule P)
  nonminimal an application of a block with its function written as a
             two-byte varint
  natzero    a Nat literal of a block given a trailing zero byte
  dupname    a declaration's name made an earlier declaration's name
  dupfront   a frontier entry made to list the item the entry before it of
             its kind lists
  length     the first lazy theorem's block one byte longer: it runs past
             PROOFS
  short      PROOFS one byte longer than its blocks
  frontier   the first frontier record names nothing (0 back)
  counts     the trailer's expression count one higher
  major      the major version 2 (declined)
  magic      the signature's last byte changed
  must       an unknown section that must be understood (declined)
  pad        a PAD section with a byte that is not zero
  index      INDEX's bytes all replaced: the verdict must not change
  extra      an unknown informational section and an all-zero PAD: the
             verdict must not change
"""
import struct
import sys

MAGIC = b"SUSZ\r\n\x1a\n"


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


def skip_bytes(b, p):
    n, p = rv(b, p)
    return p + n


def skip_expr(b, p):
    """Past the expression record at p (tags 7 to 16)."""
    t = b[p]
    q = p + 1
    if t in (7, 8):
        return skip_n(b, q, 1)
    if t == 9:
        return skip_list(b, skip_n(b, q, 1))
    if t == 10:
        return skip_n(b, q, 2)
    if t in (11, 12):
        return skip_n(b, q + 1, 3)
    if t == 13:
        return skip_n(b, q, 4)
    if t in (14, 15):
        return skip_bytes(b, q)
    if t == 16:
        return skip_n(b, q, 3)
    raise ValueError("tag %d at %d" % (t, p))


class File:
    def __init__(self, b):
        assert b[:8] == MAGIC
        n = len(b)
        tl = struct.unpack("<I", b[n - 8 : n - 4])[0]
        t = b[n - tl :]
        self.counts = list(struct.unpack("<4I", t[:16]))
        k = struct.unpack("<I", t[16:20])[0]
        self.sections = []  # [id, flags, bytearray]
        for i in range(k):
            sid, flags, _, off, ln = struct.unpack("<HHIQQ", t[20 + 24 * i : 44 + 24 * i])
            self.sections.append([sid, flags, bytearray(b[off : off + ln])])
        self.scan()

    def sec(self, sid):
        for s in self.sections:
            if s[0] == sid:
                return s
        return None

    def scan(self):
        """MAIN's frontier entries, declarations and blocks."""
        m = self.sec(1)[2]
        self.frontier = []  # (pos, kind, item)
        self.lazy = []  # (decl, pos of length, pos of count, pos after count)
        self.decls = []  # (pos of kind byte, name id or None)
        self.declared = {}  # name id -> declaration index
        nxt = [1, 1, 0]
        p, d = 0, 0
        while p < len(m):
            t = m[p]
            if t in (1, 2):
                p = skip_bytes(m, skip_n(m, p + 1, 1)) if t == 1 else skip_n(m, p + 1, 2)
                nxt[0] += 1
            elif t in (3, 4, 5, 6):
                p = skip_n(m, p + 1, 2 if t in (4, 5) else 1)
                nxt[1] += 1
            elif 7 <= t <= 16:
                p = skip_expr(m, p)
                nxt[2] += 1
            elif t == 19:
                kind = m[p + 1]
                dd, q = rv(m, p + 2)
                self.frontier.append((p, kind, nxt[kind] - dd))
                p = q
            elif t == 18:
                p = self.decl(m, p + 1, d)
                d += 1
            else:
                raise ValueError("tag %d" % t)
        blocks, off = [], 0
        for z in self.lazy:
            ln, _ = rv(m, z[1])
            blocks.append((off, ln))
            off += ln
        self.blocks = blocks

    def head(self, m, p, d):
        nm, p = rv(m, p)
        self.declared.setdefault(nm, d)
        return skip_n(m, skip_list(m, p), 1), nm

    def decl(self, m, p, d):
        k = m[p]
        p += 1
        if k == 5:
            self.decls.append((p - 1, None))
            n, p = rv(m, p)
            for _ in range(n):
                p, _ = self.head(m, p, d)
                p = skip_n(m, p + 1, 2)
                p = skip_list(m, skip_list(m, p))
                p = skip_n(m, p, 1) + 2
            n, p = rv(m, p)
            for _ in range(n):
                p, _ = self.head(m, p, d)
                p = skip_n(m, p + 1, 4)
            n, p = rv(m, p)
            for _ in range(n):
                p, _ = self.head(m, p, d)
                p = skip_n(m, skip_list(m, p + 1), 4)
                r, p = rv(m, p)
                p = skip_n(m, p, 3 * r) + 1
            return p
        start = p
        p, nm = self.head(m, p, d)
        self.decls.append((start - 1, nm))
        if k == 0:
            return p + 1
        if k == 1:
            p = skip_n(m, p, 1)
            p = skip_n(m, p + 1, 1) if m[p] == 2 else p + 1
            return skip_list(m, p + 1)
        if k == 2:
            return skip_list(m, skip_n(m, p, 1))
        if k == 3:
            return skip_list(m, skip_n(m, p, 1) + 1)
        if k == 4:
            return p + 1
        if k == 6:
            _, q = rv(m, p)
            _, r = rv(m, q)
            self.lazy.append((d, p, q, r))
            return skip_list(m, r)
        raise ValueError("kind %d" % k)

    def bytes(self):
        out = bytearray(MAGIC + struct.pack("<HHI", 1, 0, 0))
        dirs, off = b"", 16
        for sid, flags, body in self.sections:
            out += body
            dirs += struct.pack("<HHIQQ", sid, flags, 0, off, len(body))
            off += len(body)
        tr = struct.pack("<4I", *self.counts) + struct.pack("<I", len(self.sections)) + dirs
        return bytes(out + tr + struct.pack("<I", len(tr) + 8) + b"ZSUS")

    def block(self, j):
        off, ln = self.blocks[j]
        return bytearray(self.sec(2)[2][off : off + ln])

    def set_block(self, j, new):
        """Block j's bytes replaced; its theorem's length follows."""
        off, ln = self.blocks[j]
        pr = self.sec(2)[2]
        pr[off : off + ln] = new
        m = self.sec(1)[2]
        _, at, q, _ = self.lazy[j]
        m[at:q] = wv(len(new))
        self.scan()

    def set_count(self, j, n):
        m = self.sec(1)[2]
        _, _, q, r = self.lazy[j]
        m[q:r] = wv(n)
        self.scan()

    def records(self, j):
        """The positions of block j's records."""
        b = self.block(j)
        ps, p = [], 0
        while p < len(b):
            ps.append(p)
            p = skip_expr(b, p)
        return b, ps

    def fn_before(self, j):
        """How many frontier names, expressions are listed before block j's theorem."""
        d = self.lazy[j][0]
        pos = self.decls[d][0]
        names = [x for x in self.frontier if x[1] == 0 and x[0] < pos]
        exprs = [x for x in self.frontier if x[1] == 2 and x[0] < pos]
        return names, exprs


def main():
    mode, src, dst = sys.argv[1], sys.argv[2], sys.argv[3]
    f = File(open(src, "rb").read())
    if mode == "major":
        b = bytearray(f.bytes())
        b[8] = 2
        return write(dst, b)
    if mode == "magic":
        b = bytearray(f.bytes())
        b[7] = 0
        return write(dst, b)
    if mode == "counts":
        f.counts[2] += 1
    elif mode == "must":
        f.sections.append([0x6000, 1, bytearray(b"x")])
    elif mode == "pad":
        f.sections.append([4, 0, bytearray(b"\0\0\1")])
    elif mode == "extra":
        f.sections.append([0x6001, 0, bytearray(b"anything")])
        f.sections.append([4, 0, bytearray(8)])
    elif mode == "index":
        s = f.sec(5)
        if s is None:
            sys.exit(3)
        s[2][:] = bytes((i * 37 + 11) & 255 for i in range(len(s[2])))
    elif mode == "frontier":
        if not f.frontier:
            sys.exit(3)
        m = f.sec(1)[2]
        p = f.frontier[0][0]
        _, q = rv(m, p + 2)
        m[p + 2 : q] = b"\0"
    elif mode == "dupfront":
        m = f.sec(1)[2]
        last = {}
        for p, kind, item in f.frontier:
            if kind in last:
                prev = last[kind]
                dd, q = rv(m, p + 2)
                nd = dd + (item - prev)
                if len(wv(nd)) == q - (p + 2):
                    m[p + 2 : q] = wv(nd)
                    break
            last[kind] = item
        else:
            sys.exit(3)
    elif mode == "dupname":
        m = f.sec(1)[2]
        seen = []
        for d, (pos, nm) in enumerate(f.decls):
            if nm is None:
                continue
            for o in seen:
                if o != nm and len(wv(o)) == len(wv(nm)):
                    _, q = rv(m, pos + 1)
                    m[pos + 1 : q] = wv(o)
                    break
            else:
                seen.append(nm)
                continue
            break
        else:
            sys.exit(3)
    elif not f.blocks:
        sys.exit(3)
    elif mode in ("tag", "twotags", "lastblock", "tag17", "tag19"):
        js = {"twotags": [0, len(f.blocks) - 1], "lastblock": [len(f.blocks) - 1]}.get(mode, [0])
        if mode == "twotags" and len(f.blocks) < 2:
            sys.exit(3)
        t = {"tag17": 17, "tag19": 19}.get(mode, 99)
        for j in js:
            b = f.block(j)
            b[0] = t
            f.set_block(j, b)
    elif mode in ("count", "fewer", "hugecount"):
        _, ps = f.records(0)
        n = len(ps)
        m = {"count": n + 1, "fewer": n - 1, "hugecount": f.blocks[0][1]}[mode]
        if m < 1:
            sys.exit(3)
        f.set_count(0, m)
    elif mode in ("ref", "late"):
        for j in range(len(f.blocks)):
            _, fe = f.fn_before(j)
            total = sum(1 for x in f.frontier if x[1] == 2)
            if mode == "late" and len(fe) >= total:
                continue
            b, ps = f.records(j)
            for k, p in enumerate(ps):
                if b[p] == 10:
                    _, q = rv(b, p + 1)
                    r = (1 << 30) if mode == "ref" else k + 1 + len(fe)
                    f.set_block(j, b[: p + 1] + wv(r) + b[q:])
                    return write(dst, f.bytes())
        sys.exit(3)
    elif mode == "rulep":
        for j in range(len(f.blocks)):
            d = f.lazy[j][0]
            names, _ = f.fn_before(j)
            bad = [i for i, x in enumerate(names) if f.declared.get(x[2], 1 << 60) >= d]
            if not bad:
                continue
            b, ps = f.records(j)
            for p in ps:
                if b[p] == 9:
                    _, q = rv(b, p + 1)
                    f.set_block(j, b[: p + 1] + wv(bad[0]) + b[q:])
                    return write(dst, f.bytes())
        sys.exit(3)
    elif mode in ("nonminimal", "natzero"):
        want = 10 if mode == "nonminimal" else 14
        for j in range(len(f.blocks)):
            b, ps = f.records(j)
            for p in ps:
                if b[p] == want:
                    v, q = rv(b, p + 1)
                    if mode == "nonminimal":
                        if v > 127:
                            continue
                        new = b[: p + 1] + bytes([v | 128, 0]) + b[q:]
                    else:
                        new = b[: p + 1] + wv(v + 1) + b[q : q + v] + b"\0" + b[q + v :]
                    f.set_block(j, new)
                    return write(dst, f.bytes())
        sys.exit(3)
    elif mode == "length":
        m = f.sec(1)[2]
        _, at, q, _ = f.lazy[0]
        ln, _ = rv(m, at)
        if len(wv(ln + 1)) != q - at:
            sys.exit(3)
        m[at:q] = wv(ln + 1)
    elif mode == "short":
        f.sec(2)[2].append(0)
    else:
        sys.exit("unknown mode " + mode)
    write(dst, f.bytes())


def write(dst, b):
    open(dst, "wb").write(bytes(b))


main()
