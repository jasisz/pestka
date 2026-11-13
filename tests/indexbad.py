"""Damages the INDEX section of a Susz 1 file (Susz 1 spec, section 6a),
for tests/only.sh: python3 -I indexbad.py MODE IN OUT [NAME]. MAIN and
PROOFS are left as they are, so a full check of the damaged file gives the
verdict of the original; a subset check that relies on the damaged entry
must end as index invalid.

Modes:
  garbage  INDEX's bytes all replaced
  offset   entry 0's offset one byte later: every offset after it is wrong
  decl     NAME's entry in the name table gives another declaration
  kind     the kind of NAME's declaration entry changed (0 and 1 swapped,
           or 0 for any other kind)
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


def key(name):
    out = bytearray()
    for c in name.split("."):
        if c and c.isdigit() and len(c) < 20:
            out += b"\x02" + wv(int(c))
        else:
            u = c.encode()
            out += b"\x01" + wv(len(u)) + u
    return bytes(out)


def parse(b):
    p = 0
    nd, p = rv(b, p)
    entries = []
    for _ in range(nd):
        k = b[p]
        p += 1
        d, p = rv(b, p)
        l = None
        if k == 6:
            l, p = rv(b, p)
        entries.append([k, d, l])
    nn, p = rv(b, p)
    names, cur = [], b""
    for _ in range(nn):
        sh, p = rv(b, p)
        sl, p = rv(b, p)
        cur = cur[:sh] + b[p : p + sl]
        p += sl
        d, p = rv(b, p)
        names.append([cur, d])
    return entries, names


def encode(entries, names):
    out = bytearray(wv(len(entries)))
    for k, d, l in entries:
        out.append(k)
        out += wv(d)
        if k == 6:
            out += wv(l)
    out += wv(len(names))
    prev = b""
    for k, d in names:
        sh = 0
        while sh < len(prev) and sh < len(k) and prev[sh] == k[sh]:
            sh += 1
        out += wv(sh) + wv(len(k) - sh) + k[sh:] + wv(d)
        prev = k
    return bytes(out)


def main():
    mode, src, dst = sys.argv[1], sys.argv[2], sys.argv[3]
    b = bytearray(open(src, "rb").read())
    assert b[:8] == MAGIC
    n = len(b)
    tl = struct.unpack("<I", b[n - 8 : n - 4])[0]
    t = b[n - tl :]
    k = struct.unpack("<I", t[16:20])[0]
    secs = []
    for i in range(k):
        sid, flags, _, off, ln = struct.unpack("<HHIQQ", t[20 + 24 * i : 44 + 24 * i])
        secs.append([sid, flags, bytearray(b[off : off + ln])])
    idx = [s for s in secs if s[0] == 5]
    if not idx:
        sys.exit(3)
    body = idx[0][2]
    if mode == "garbage":
        body[:] = bytes((i * 37 + 11) & 255 for i in range(len(body)))
    else:
        entries, names = parse(bytes(body))
        if mode == "offset":
            entries[0][1] += 1
        else:
            want = key(sys.argv[4])
            hit = [x for x in names if x[0] == want]
            if not hit:
                sys.exit("no name " + sys.argv[4])
            d = hit[0][1]
            if mode == "decl":
                hit[0][1] = d - 1 if d > 0 else d + 1
            elif mode == "kind":
                e = entries[d]
                if e[0] == 6:
                    sys.exit(3)
                e[0] = {0: 1, 1: 0}.get(e[0], 0)
            else:
                sys.exit("unknown mode " + mode)
        body[:] = encode(entries, names)
    out = bytearray(MAGIC + struct.pack("<HHI", 1, 0, 0))
    dirs, off = b"", 16
    for sid, flags, sb in secs:
        out += sb
        dirs += struct.pack("<HHIQQ", sid, flags, 0, off, len(sb))
        off += len(sb)
    tr = bytes(t[:16]) + struct.pack("<I", len(secs)) + dirs
    open(dst, "wb").write(bytes(out + tr + struct.pack("<I", len(tr) + 8) + b"ZSUS"))


main()
