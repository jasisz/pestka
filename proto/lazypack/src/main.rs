// lazypack IN.susz OUT.susz : rewrites a Susz v0 file as the experimental
// version 2 ("lazy proofs"): expressions reachable only from one theorem's
// value move into a per-theorem block in a proof section; the main block
// keeps names, levels, every other expression (renumbered densely) and the
// declarations; a theorem whose value is its own is declaration kind 6
// (head, block offset, block length, all). Records tag 19 at the end of the
// main block list the names (kind 0), levels (1) and main expressions (2)
// blocks name, by absolute id: the "frontier" tables, in order.
//
// In a block: varint count, then expression records as in v0 except that
// an expression reference r means local back r when r <= k (k = records of
// the block before this one), else frontier expression r - k - 1; a name is
// a frontier name index, a level a frontier level index.
//
// Trailer (60 bytes): names u32, levels u32, main exprs u32, decls u32,
// total exprs u32, main off u64, main len u64, proofs off u64, proofs len
// u64, u32 60, "ZSUS". Header: "SUSZ" 2 0 0 0, meta string.
use std::collections::HashMap;
use std::io::Write;

const NONE: u32 = u32::MAX;
const SHARED: u32 = u32::MAX - 1;

fn rv(b: &[u8], p: &mut usize) -> u64 {
    let mut v: u64 = 0;
    let mut s = 0;
    loop {
        let x = b[*p];
        *p += 1;
        v |= ((x & 127) as u64) << s;
        if x < 128 {
            return v;
        }
        s += 7;
    }
}

fn wv(out: &mut Vec<u8>, mut v: u64) {
    loop {
        let x = (v & 127) as u8;
        v >>= 7;
        if v == 0 {
            out.push(x);
            return;
        }
        out.push(x | 128);
    }
}

fn u32at(b: &[u8], i: usize) -> u32 {
    u32::from_le_bytes(b[i..i + 4].try_into().unwrap())
}
fn u64at(b: &[u8], i: usize) -> u64 {
    u64::from_le_bytes(b[i..i + 8].try_into().unwrap())
}

#[derive(Clone, Copy)]
enum Piece {
    Raw(usize, usize),
    Expr(u32),
}

struct Cur<'a> {
    b: &'a [u8],
    p: usize,
    raw: usize,
    pieces: Vec<Piece>,
    next: u32,
}

impl<'a> Cur<'a> {
    fn v(&mut self) -> u64 {
        rv(self.b, &mut self.p)
    }
    fn byte(&mut self) -> u8 {
        let x = self.b[self.p];
        self.p += 1;
        x
    }
    fn list(&mut self) {
        let n = self.v();
        for _ in 0..n {
            self.v();
        }
    }
    fn expr(&mut self) {
        if self.p > self.raw {
            self.pieces.push(Piece::Raw(self.raw, self.p));
        }
        let d = self.v() as u32;
        self.pieces.push(Piece::Expr(self.next - d));
        self.raw = self.p;
    }
    fn head(&mut self) {
        self.v();
        self.list();
        self.expr();
    }
    fn finish(&mut self) {
        if self.p > self.raw {
            self.pieces.push(Piece::Raw(self.raw, self.p));
        }
        self.raw = self.p;
    }
}

struct Decl {
    kind: u8,
    pieces: Vec<Piece>,
    value: Option<usize>, // piece index of a theorem's value
}

fn parse_decl(b: &[u8], p: usize, next: u32) -> (Decl, usize) {
    let kind = b[p];
    let mut c = Cur { b, p: p + 1, raw: p + 1, pieces: Vec::new(), next };
    let mut value = None;
    match kind {
        0 => {
            c.head();
            c.byte();
        }
        1 => {
            c.head();
            c.expr();
            let h = c.byte();
            if h == 2 {
                c.v();
            }
            c.byte();
            c.list();
        }
        2 => {
            c.head();
            c.expr();
            value = Some(c.pieces.len() - 1);
            c.list();
        }
        3 => {
            c.head();
            c.expr();
            c.byte();
            c.list();
        }
        4 => {
            c.head();
            c.byte();
        }
        5 => {
            let nt = c.v();
            for _ in 0..nt {
                c.head();
                c.byte();
                c.v();
                c.v();
                c.list();
                c.list();
                c.v();
                c.byte();
                c.byte();
            }
            let nc = c.v();
            for _ in 0..nc {
                c.head();
                c.byte();
                c.v();
                c.v();
                c.v();
                c.v();
            }
            let nr = c.v();
            for _ in 0..nr {
                c.head();
                c.byte();
                c.list();
                c.v();
                c.v();
                c.v();
                c.v();
                let rules = c.v();
                for _ in 0..rules {
                    c.v();
                    c.v();
                    c.expr();
                }
                c.byte();
            }
        }
        k => panic!("unknown decl kind {k}"),
    }
    c.finish();
    let end = c.p;
    (Decl { kind, pieces: c.pieces, value }, end)
}

// Skips a record at p (tag at p); returns the end.
fn skip_record(b: &[u8], p: usize) -> usize {
    let mut q = p + 1;
    match b[p] {
        1 => {
            rv(b, &mut q);
            let n = rv(b, &mut q) as usize;
            q += n;
        }
        2 | 4 | 5 => {
            rv(b, &mut q);
            rv(b, &mut q);
        }
        3 | 6 | 7 | 8 | 17 => {
            rv(b, &mut q);
        }
        9 => {
            rv(b, &mut q);
            let n = rv(b, &mut q);
            for _ in 0..n {
                rv(b, &mut q);
            }
        }
        10 => {
            rv(b, &mut q);
            rv(b, &mut q);
        }
        11 | 12 => {
            q += 1;
            rv(b, &mut q);
            rv(b, &mut q);
            rv(b, &mut q);
        }
        13 => {
            for _ in 0..4 {
                rv(b, &mut q);
            }
        }
        14 | 15 => {
            let n = rv(b, &mut q) as usize;
            q += n;
        }
        16 => {
            for _ in 0..3 {
                rv(b, &mut q);
            }
        }
        t => panic!("unknown tag {t} at {p}"),
    }
    q
}

fn children(b: &[u8], off: usize, id: u32, out: &mut Vec<u32>) {
    out.clear();
    let mut q = off + 1;
    match b[off] {
        10 => {
            let f = rv(b, &mut q) as u32;
            let a = rv(b, &mut q) as u32;
            out.push(id - f);
            out.push(id - a);
        }
        11 | 12 => {
            q += 1;
            rv(b, &mut q);
            let t = rv(b, &mut q) as u32;
            let x = rv(b, &mut q) as u32;
            out.push(id - t);
            out.push(id - x);
        }
        13 => {
            rv(b, &mut q);
            for _ in 0..3 {
                let d = rv(b, &mut q) as u32;
                out.push(id - d);
            }
        }
        16 => {
            rv(b, &mut q);
            rv(b, &mut q);
            let d = rv(b, &mut q) as u32;
            out.push(id - d);
        }
        17 => {
            let d = rv(b, &mut q) as u32;
            out.push(id - d);
        }
        _ => {}
    }
}

// Re-encodes the expression record at off (id) with references, names and
// levels mapped.
fn enc_expr(
    b: &[u8],
    off: usize,
    id: u32,
    out: &mut Vec<u8>,
    fe: &mut dyn FnMut(u32) -> u64,
    fname: &mut dyn FnMut(u64) -> u64,
    flevel: &mut dyn FnMut(u64) -> u64,
) {
    let tag = b[off];
    out.push(tag);
    let mut q = off + 1;
    match tag {
        7 => {
            let k = rv(b, &mut q);
            wv(out, k);
        }
        8 => {
            let l = rv(b, &mut q);
            wv(out, flevel(l));
        }
        9 => {
            let n = rv(b, &mut q);
            wv(out, fname(n));
            let k = rv(b, &mut q);
            wv(out, k);
            for _ in 0..k {
                let l = rv(b, &mut q);
                wv(out, flevel(l));
            }
        }
        10 => {
            let f = id - rv(b, &mut q) as u32;
            let a = id - rv(b, &mut q) as u32;
            wv(out, fe(f));
            wv(out, fe(a));
        }
        11 | 12 => {
            out.push(b[q]);
            q += 1;
            let n = rv(b, &mut q);
            wv(out, fname(n));
            let t = id - rv(b, &mut q) as u32;
            let x = id - rv(b, &mut q) as u32;
            wv(out, fe(t));
            wv(out, fe(x));
        }
        13 => {
            let n = rv(b, &mut q);
            wv(out, fname(n));
            for _ in 0..3 {
                let d = id - rv(b, &mut q) as u32;
                wv(out, fe(d));
            }
        }
        14 | 15 => {
            let n = rv(b, &mut q) as usize;
            wv(out, n as u64);
            out.extend_from_slice(&b[q..q + n]);
        }
        16 => {
            let n = rv(b, &mut q);
            wv(out, fname(n));
            let k = rv(b, &mut q);
            wv(out, k);
            let d = id - rv(b, &mut q) as u32;
            wv(out, fe(d));
        }
        17 => {
            let d = id - rv(b, &mut q) as u32;
            wv(out, fe(d));
        }
        t => panic!("not an expression tag {t}"),
    }
}

fn main() {
    let args: Vec<String> = std::env::args().collect();
    let b = std::fs::read(&args[1]).expect("read");
    let size = b.len();
    assert_eq!(&b[size - 4..], b"ZSUS");
    let tn = u32at(&b, size - 8) as usize;
    let tr = &b[size - tn..];
    assert_eq!(tn, 60);
    assert_eq!(u32at(tr, 16), 1);
    let (names, levels, exprs, ndecls) = (u32at(tr, 0), u32at(tr, 4), u32at(tr, 8), u32at(tr, 12));
    let boff = u64at(tr, 20) as usize;
    let blen = u64at(tr, 28) as usize;
    assert_eq!(&b[0..8], b"SUSZ\0\0\0\0");
    let header = &b[8..boff];

    // Pass 1: offsets of expressions, declarations parsed.
    let mut eoff: Vec<u32> = Vec::with_capacity(exprs as usize);
    let mut decls: Vec<Decl> = Vec::with_capacity(ndecls as usize);
    let mut p = boff;
    let end = boff + blen;
    while p < end {
        let tag = b[p];
        if tag == 18 {
            let (d, q) = parse_decl(&b, p + 1, eoff.len() as u32);
            decls.push(d);
            p = q;
        } else {
            if (7..=17).contains(&tag) {
                eoff.push(p as u32);
            }
            p = skip_record(&b, p);
        }
    }
    assert_eq!(eoff.len() as u32, exprs);
    assert_eq!(decls.len() as u32, ndecls);
    eprintln!("pass 1: {} exprs, {} decls", eoff.len(), decls.len());

    // Ownership.
    let n = eoff.len();
    let mut owner: Vec<u32> = vec![NONE; n];
    fn mark(owner: &mut [u32], e: u32, o: u32) {
        let x = &mut owner[e as usize];
        if *x == NONE {
            *x = o;
        } else if *x != o {
            *x = SHARED;
        }
    }
    for (di, d) in decls.iter().enumerate() {
        for (pi, pc) in d.pieces.iter().enumerate() {
            if let Piece::Expr(e) = *pc {
                let o = if d.value == Some(pi) { di as u32 } else { SHARED };
                mark(&mut owner, e, o);
            }
        }
    }
    let mut ch: Vec<u32> = Vec::with_capacity(4);
    let mut unreached = 0u64;
    for e in (0..n).rev() {
        let mut o = owner[e];
        if o == NONE {
            unreached += 1;
            o = SHARED;
            owner[e] = SHARED;
        }
        children(&b, eoff[e] as usize, e as u32, &mut ch);
        for &c in ch.iter() {
            mark(&mut owner, c, o);
        }
    }
    // New ids.
    let mut newid: Vec<u32> = vec![0; n];
    let mut count: Vec<u32> = vec![0; decls.len()];
    let mut main = 0u32;
    for e in 0..n {
        let o = owner[e];
        if o == SHARED {
            newid[e] = main;
            main += 1;
        } else {
            newid[e] = count[o as usize];
            count[o as usize] += 1;
        }
    }
    let owned = n as u64 - main as u64;
    let lazy = count.iter().filter(|&&c| c > 0).count();
    eprintln!("main exprs {main}, owned {owned}, unreached {unreached}, lazy theorems {lazy}");

    // Blocks.
    let mut fe_map: HashMap<u32, u32> = HashMap::new();
    let mut fe_list: Vec<u32> = Vec::new();
    let mut fn_map: HashMap<u64, u32> = HashMap::new();
    let mut fn_list: Vec<u64> = Vec::new();
    let mut fl_map: HashMap<u64, u32> = HashMap::new();
    let mut fl_list: Vec<u64> = Vec::new();
    let mut blocks: Vec<Vec<u8>> = (0..decls.len()).map(|_| Vec::new()).collect();
    for e in 0..n {
        let o = owner[e];
        if o == SHARED {
            continue;
        }
        let k = newid[e] as u64;
        let mut out = std::mem::take(&mut blocks[o as usize]);
        enc_expr(
            &b,
            eoff[e] as usize,
            e as u32,
            &mut out,
            &mut |c: u32| {
                let oc = owner[c as usize];
                if oc == o {
                    k - newid[c as usize] as u64
                } else {
                    assert_eq!(oc, SHARED);
                    let m = newid[c as usize];
                    let f = *fe_map.entry(m).or_insert_with(|| {
                        fe_list.push(m);
                        (fe_list.len() - 1) as u32
                    });
                    k + 1 + f as u64
                }
            },
            &mut |x: u64| {
                *fn_map.entry(x).or_insert_with(|| {
                    fn_list.push(x);
                    (fn_list.len() - 1) as u32
                }) as u64
            },
            &mut |x: u64| {
                *fl_map.entry(x).or_insert_with(|| {
                    fl_list.push(x);
                    (fl_list.len() - 1) as u32
                }) as u64
            },
        );
        blocks[o as usize] = out;
    }
    eprintln!(
        "frontier: names {}, levels {}, exprs {}",
        fn_list.len(),
        fl_list.len(),
        fe_list.len()
    );

    // Proof section and block places.
    let mut proofs: Vec<u8> = Vec::new();
    let mut place: Vec<(u64, u64)> = vec![(0, 0); decls.len()];
    for di in 0..decls.len() {
        if count[di] > 0 {
            let start = proofs.len();
            wv(&mut proofs, count[di] as u64);
            proofs.extend_from_slice(&blocks[di]);
            place[di] = (start as u64, (proofs.len() - start) as u64);
            blocks[di] = Vec::new();
        }
    }
    drop(blocks);

    // Main block.
    let mut out: Vec<u8> = Vec::with_capacity(blen);
    let mut p = boff;
    let mut ei = 0usize;
    let mut di = 0usize;
    let mut mrun = 0u32;
    while p < end {
        let tag = b[p];
        if tag == 18 {
            let (_, q) = parse_decl(&b, p + 1, ei as u32);
            let d = &decls[di];
            let mnext = mrun;
            let lazy = count[di] > 0;
            out.push(18);
            out.push(if lazy { 6 } else { d.kind });
            for (pi, pc) in d.pieces.iter().enumerate() {
                match *pc {
                    Piece::Raw(s, t) => out.extend_from_slice(&b[s..t]),
                    Piece::Expr(e) => {
                        if lazy && d.value == Some(pi) {
                            wv(&mut out, place[di].0);
                            wv(&mut out, place[di].1);
                        } else {
                            assert_eq!(owner[e as usize], SHARED);
                            wv(&mut out, mnext as u64 - newid[e as usize] as u64);
                        }
                    }
                }
            }
            di += 1;
            p = q;
        } else if (7..=17).contains(&tag) {
            let e = ei;
            ei += 1;
            let q = skip_record(&b, p);
            if owner[e] == SHARED {
                let k = newid[e] as u64;
                enc_expr(
                    &b,
                    p,
                    e as u32,
                    &mut out,
                    &mut |c: u32| {
                        assert_eq!(owner[c as usize], SHARED);
                        k - newid[c as usize] as u64
                    },
                    &mut |x| x,
                    &mut |x| x,
                );
                mrun += 1;
            }
            p = q;
        } else {
            let q = skip_record(&b, p);
            out.extend_from_slice(&b[p..q]);
            p = q;
        }
    }
    for &x in fn_list.iter() {
        out.push(19);
        out.push(0);
        wv(&mut out, x);
    }
    for &x in fl_list.iter() {
        out.push(19);
        out.push(1);
        wv(&mut out, x);
    }
    for &x in fe_list.iter() {
        out.push(19);
        out.push(2);
        wv(&mut out, x as u64);
    }

    let mut f = std::io::BufWriter::new(std::fs::File::create(&args[2]).expect("create"));
    let mut hd: Vec<u8> = b"SUSZ\x02\0\0\0".to_vec();
    hd.extend_from_slice(header);
    let moff = hd.len() as u64;
    let poff = moff + out.len() as u64;
    let mut t: Vec<u8> = Vec::new();
    for x in [names, levels, main, ndecls, exprs] {
        t.extend_from_slice(&x.to_le_bytes());
    }
    for x in [moff, out.len() as u64, poff, proofs.len() as u64] {
        t.extend_from_slice(&x.to_le_bytes());
    }
    t.extend_from_slice(&60u32.to_le_bytes());
    t.extend_from_slice(b"ZSUS");
    assert_eq!(t.len(), 60);
    f.write_all(&hd).unwrap();
    f.write_all(&out).unwrap();
    f.write_all(&proofs).unwrap();
    f.write_all(&t).unwrap();
    f.flush().unwrap();
    eprintln!(
        "main block {} bytes, proof section {} bytes, file {} bytes (was {})",
        out.len(),
        proofs.len(),
        poff + proofs.len() as u64 + 60,
        size
    );
}

// The next main id at the position of expression index ei (exprs before it
// that are shared): newid of the last shared expr before ei, plus one.
fn newid_main_next(owner: &[u32], newid: &[u32], ei: usize) -> u32 {
    let mut e = ei;
    while e > 0 {
        e -= 1;
        if owner[e] == SHARED {
            return newid[e] + 1;
        }
    }
    0
}
