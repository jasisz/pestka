// lazypack IN.susz OUT.susz : rewrites a Susz v0 file as version 2
// (docs/susz.md), independently of Pestka's own packer (export/split.av), so
// that the two can be compared byte for byte (tests/susz.sh).
//
// Expressions reachable only from one theorem's value move into that
// theorem's block in the proof section; the main block keeps names, levels,
// every other expression (renumbered densely) and the declarations. A
// theorem whose value has a block is declaration kind 6: head, block length,
// placed byte, all. Records 19 of the main block list the frontier: kind 0
// name, 1 level, 2 expression, then how far back the item is (always 1 here:
// each entry follows its item).
//
// A block: varint count, then records: expression records as in v0 except
// that an expression reference r means local back r when r <= k (k = the
// block's expressions before this one), else frontier expression r - k - 1;
// a name is a frontier name index, a level a frontier level index. Record
// 19 | mark: the expression records after it stood before declaration mark
// in the export (marks start at 0).
//
// Trailer (56 bytes): names u32, levels u32, main exprs u32, decls u32, main
// off u64, main len u64, proofs off u64, proofs len u64, u32 56, "ZSUS".
use std::collections::HashMap;
use std::io::Write;

const NONE: i64 = -1;
const SHARED: i64 = -2;
const EXPORTED: i64 = -3;
const NEVER: u64 = 1 << 61;

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

fn wvlen(v: u64) -> usize {
    let mut t = Vec::new();
    wv(&mut t, v);
    t.len()
}

fn u32at(b: &[u8], i: usize) -> u32 {
    u32::from_le_bytes(b[i..i + 4].try_into().unwrap())
}
fn u64at(b: &[u8], i: usize) -> u64 {
    u64::from_le_bytes(b[i..i + 8].try_into().unwrap())
}

fn placed_for(code: u64, mark: u64) -> bool {
    code < 2 * mark || code == 2 * mark + 1
}

#[derive(Clone, Copy)]
enum Piece {
    Raw(usize, usize),
    Ref(u32),
    Val(u32),
}

struct Cur<'a> {
    b: &'a [u8],
    p: usize,
    raw: usize,
    pieces: Vec<Piece>,
    next: u32,
    names: Vec<u64>,
    skip: bool,
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
    fn unsafe_byte(&mut self) {
        if self.byte() == 1 {
            self.skip = true;
        }
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
        self.pieces.push(Piece::Ref(self.next - d));
        self.raw = self.p;
    }
    fn head(&mut self) {
        let n = self.v();
        self.names.push(n);
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
    names: Vec<u64>,
    skip: bool,
}

fn parse_decl(b: &[u8], p: usize, next: u32) -> (Decl, usize) {
    let kind = b[p];
    let mut c = Cur { b, p: p + 1, raw: p + 1, pieces: Vec::new(), next, names: Vec::new(), skip: false };
    match kind {
        0 => {
            c.head();
            c.unsafe_byte();
        }
        1 => {
            c.head();
            c.expr();
            let h = c.byte();
            if h == 2 {
                c.v();
            }
            if c.byte() != 0 {
                c.skip = true;
            }
            c.list();
        }
        2 => {
            c.head();
            c.expr();
            if let Some(Piece::Ref(e)) = c.pieces.last().copied() {
                *c.pieces.last_mut().unwrap() = Piece::Val(e);
            }
            c.list();
        }
        3 => {
            c.head();
            c.expr();
            c.unsafe_byte();
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
                c.unsafe_byte();
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
    (Decl { kind, pieces: c.pieces, names: c.names, skip: c.skip }, end)
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
        2 | 4 | 5 | 10 => {
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

// The expression parts (as ids), names and levels of the record at off.
fn parts(b: &[u8], off: usize, id: u32, ch: &mut Vec<u32>, names: &mut Vec<u64>, levels: &mut Vec<u64>) {
    ch.clear();
    names.clear();
    levels.clear();
    let mut q = off + 1;
    match b[off] {
        8 => levels.push(rv(b, &mut q)),
        9 => {
            names.push(rv(b, &mut q));
            let k = rv(b, &mut q);
            for _ in 0..k {
                levels.push(rv(b, &mut q));
            }
        }
        10 => {
            let f = rv(b, &mut q) as u32;
            let a = rv(b, &mut q) as u32;
            ch.push(id - f);
            ch.push(id - a);
        }
        11 | 12 => {
            q += 1;
            names.push(rv(b, &mut q));
            let t = rv(b, &mut q) as u32;
            let x = rv(b, &mut q) as u32;
            ch.push(id - t);
            ch.push(id - x);
        }
        13 => {
            names.push(rv(b, &mut q));
            for _ in 0..3 {
                let d = rv(b, &mut q) as u32;
                ch.push(id - d);
            }
        }
        16 => {
            names.push(rv(b, &mut q));
            rv(b, &mut q);
            let d = rv(b, &mut q) as u32;
            ch.push(id - d);
        }
        17 => {
            let d = rv(b, &mut q) as u32;
            ch.push(id - d);
        }
        _ => {}
    }
}

fn mark(owner: &mut [i64], e: u32, o: i64) {
    let x = &mut owner[e as usize];
    if *x == NONE {
        *x = o;
    } else if *x != o {
        *x = SHARED;
    }
}

struct Acc {
    out: Vec<u8>,
    k: u32,
    mark: u64,
    fine: bool,
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
    let (nnames, nlevels, exprs, ndecls) = (u32at(tr, 0), u32at(tr, 4), u32at(tr, 8), u32at(tr, 12));
    let boff = u64at(tr, 20) as usize;
    let blen = u64at(tr, 28) as usize;
    assert_eq!(&b[0..8], b"SUSZ\0\0\0\0");
    let header = &b[8..boff];
    let end = boff + blen;

    // Pass 1: names (canonical), offsets of expressions, declarations.
    let mut canon: Vec<u32> = vec![0; nnames as usize];
    let mut cmap: HashMap<(u32, u8, Vec<u8>), u32> = HashMap::new();
    let mut ncanon: u32 = 1;
    let mut eoff: Vec<u32> = Vec::with_capacity(exprs as usize);
    let mut decls: Vec<Decl> = Vec::with_capacity(ndecls as usize);
    let mut known: HashMap<u32, u64> = HashMap::new();
    let mut nid = 1usize;
    let mut p = boff;
    let mut canon_of = |key: (u32, u8, Vec<u8>), cmap: &mut HashMap<(u32, u8, Vec<u8>), u32>| -> u32 {
        *cmap.entry(key).or_insert_with(|| {
            let c = ncanon;
            ncanon += 1;
            c
        })
    };
    while p < end {
        let tag = b[p];
        if tag == 18 {
            let (d, q) = parse_decl(&b, p + 1, eoff.len() as u32);
            if !d.skip {
                let di = decls.len() as u64;
                let code = 2 * di + if d.kind == 5 { 1 } else { 0 };
                for &n in d.names.iter() {
                    known.entry(canon[n as usize]).or_insert(code);
                }
            }
            decls.push(d);
            p = q;
        } else {
            let q = skip_record(&b, p);
            if tag == 1 {
                let mut r = p + 1;
                let pre = rv(&b, &mut r) as usize;
                let n = rv(&b, &mut r) as usize;
                canon[nid] = canon_of((canon[pre], 0, b[r..r + n].to_vec()), &mut cmap);
                nid += 1;
            } else if tag == 2 {
                let mut r = p + 1;
                let pre = rv(&b, &mut r) as usize;
                let k = rv(&b, &mut r);
                canon[nid] = canon_of((canon[pre], 1, k.to_le_bytes().to_vec()), &mut cmap);
                nid += 1;
            } else if (7..=17).contains(&tag) {
                eoff.push(p as u32);
            }
            p = q;
        }
    }
    assert_eq!(eoff.len() as u32, exprs);
    assert_eq!(decls.len() as u32, ndecls);
    let code_of_canon = |c: Option<u32>| -> u64 { c.and_then(|c| known.get(&c).copied()).unwrap_or(NEVER) };
    let code_by_id: Vec<u64> = canon.iter().map(|&c| code_of_canon(Some(c))).collect();
    let lit = |pre: u32, s: &str| cmap.get(&(pre, 0, s.as_bytes().to_vec())).copied();
    let nat = lit(0, "Nat");
    let string = lit(0, "String");
    let char_ = lit(0, "Char");
    let str_names = [
        nat,
        string,
        string.and_then(|s| lit(s, "ofList")),
        lit(0, "List"),
        char_,
        char_.and_then(|c| lit(c, "ofNat")),
    ];
    let nat_code = code_of_canon(nat);
    let str_codes: Vec<u64> = str_names.iter().map(|&c| code_of_canon(c)).collect();

    // Ownership.
    let n = eoff.len();
    let mut owner: Vec<i64> = vec![NONE; n];
    for (di, d) in decls.iter().enumerate() {
        for pc in d.pieces.iter() {
            match *pc {
                Piece::Val(e) => mark(&mut owner, e, di as i64),
                Piece::Ref(e) => mark(&mut owner, e, SHARED),
                _ => {}
            }
        }
    }
    let mut ch: Vec<u32> = Vec::with_capacity(4);
    let mut nm: Vec<u64> = Vec::new();
    let mut lv: Vec<u64> = Vec::new();
    for e in (0..n).rev() {
        let mut o = owner[e];
        if o == NONE {
            o = SHARED;
            owner[e] = SHARED;
        }
        parts(&b, eoff[e] as usize, e as u32, &mut ch, &mut nm, &mut lv);
        for &c in ch.iter() {
            mark(&mut owner, c, o);
        }
    }
    // Numbers, and what goes to the frontier.
    let mut newid: Vec<u32> = vec![0; n];
    let mut count: Vec<u32> = vec![0; decls.len()];
    let mut name_f: Vec<i64> = vec![-2; nnames as usize];
    let mut level_f: Vec<i64> = vec![-2; nlevels as usize];
    let mut main = 0u32;
    for e in 0..n {
        let o = owner[e];
        if o >= 0 {
            newid[e] = count[o as usize];
            count[o as usize] += 1;
            parts(&b, eoff[e] as usize, e as u32, &mut ch, &mut nm, &mut lv);
            for &c in ch.iter() {
                if owner[c as usize] < 0 {
                    owner[c as usize] = EXPORTED;
                }
            }
            for &x in nm.iter() {
                name_f[x as usize] = -1;
            }
            for &x in lv.iter() {
                level_f[x as usize] = -1;
            }
        } else {
            newid[e] = main;
            main += 1;
        }
    }
    drop(eoff);

    // Writing.
    let mut out: Vec<u8> = Vec::with_capacity(blen);
    let mut proofs: Vec<u8> = Vec::new();
    let mut open: HashMap<u32, Acc> = HashMap::new();
    let (mut f_n, mut f_l, mut f_e) = (0i64, 0i64, 0i64);
    let mut fidx: Vec<i64> = vec![-1; n]; // frontier index of an exported main expression
    let (mut name_id, mut level_id, mut ei, mut di, mut mnext) = (1usize, 1usize, 0usize, 0u64, 0u32);
    let mut lazy = 0u32;
    // The anonymous name and the level zero have no records: their entries
    // open the main block when a block names them.
    if name_f[0] == -1 {
        out.extend_from_slice(&[19, 0, 1]);
        name_f[0] = f_n;
        f_n += 1;
    }
    if level_f[0] == -1 {
        out.extend_from_slice(&[19, 1, 1]);
        level_f[0] = f_l;
        f_l += 1;
    }
    let mut p = boff;
    while p < end {
        let tag = b[p];
        if tag == 18 {
            let (d, q) = parse_decl(&b, p + 1, ei as u32);
            let is_lazy = count[di as usize] > 0;
            out.push(18);
            if is_lazy {
                let acc = open.remove(&(di as u32)).expect("block");
                assert_eq!(acc.k, count[di as usize]);
                let blen = wvlen(acc.k as u64) + acc.out.len();
                out.push(6);
                for pc in d.pieces.iter() {
                    match *pc {
                        Piece::Raw(s, t) => out.extend_from_slice(&b[s..t]),
                        Piece::Ref(e) => wv(&mut out, (mnext - newid[e as usize]) as u64),
                        Piece::Val(_) => {
                            wv(&mut out, blen as u64);
                            out.push(if acc.fine { 1 } else { 0 });
                        }
                    }
                }
                wv(&mut proofs, acc.k as u64);
                proofs.extend_from_slice(&acc.out);
                lazy += 1;
            } else {
                out.push(d.kind);
                for pc in d.pieces.iter() {
                    match *pc {
                        Piece::Raw(s, t) => out.extend_from_slice(&b[s..t]),
                        Piece::Ref(e) | Piece::Val(e) => wv(&mut out, (mnext - newid[e as usize]) as u64),
                    }
                }
            }
            di += 1;
            p = q;
            continue;
        }
        let q = skip_record(&b, p);
        if tag <= 2 {
            out.extend_from_slice(&b[p..q]);
            if name_f[name_id] == -1 {
                out.extend_from_slice(&[19, 0, 1]);
                name_f[name_id] = f_n;
                f_n += 1;
            }
            name_id += 1;
        } else if tag <= 6 {
            out.extend_from_slice(&b[p..q]);
            if level_f[level_id] == -1 {
                out.extend_from_slice(&[19, 1, 1]);
                level_f[level_id] = f_l;
                f_l += 1;
            }
            level_id += 1;
        } else {
            let e = ei as u32;
            let o = owner[ei];
            if o >= 0 {
                let acc = open.entry(o as u32).or_insert_with(|| Acc { out: Vec::new(), k: 0, mark: 0, fine: true });
                if acc.mark != di {
                    acc.out.push(19);
                    wv(&mut acc.out, di);
                    acc.mark = di;
                }
                let k = newid[ei];
                let m = acc.mark;
                let a = &mut acc.out;
                let mut r = p + 1;
                let mut eref = |a: &mut Vec<u8>, d: u64| {
                    let c = e - d as u32;
                    if owner[c as usize] == o {
                        wv(a, (k - newid[c as usize]) as u64);
                    } else {
                        assert!(fidx[c as usize] >= 0);
                        wv(a, k as u64 + 1 + fidx[c as usize] as u64);
                    }
                };
                a.push(tag);
                let mut fine = true;
                match tag {
                    7 => wv(a, rv(&b, &mut r)),
                    8 => {
                        let l = level_f[rv(&b, &mut r) as usize];
                        assert!(l >= 0);
                        wv(a, l as u64)
                    }
                    9 => {
                        let nmi = rv(&b, &mut r);
                        fine = placed_for(code_by_id[nmi as usize], m);
                        wv(a, name_f[nmi as usize] as u64);
                        let c = rv(&b, &mut r);
                        wv(a, c);
                        for _ in 0..c {
                            wv(a, level_f[rv(&b, &mut r) as usize] as u64);
                        }
                    }
                    10 => {
                        let f = rv(&b, &mut r);
                        let x = rv(&b, &mut r);
                        eref(a, f);
                        eref(a, x);
                    }
                    11 | 12 => {
                        a.push(b[r]);
                        r += 1;
                        wv(a, name_f[rv(&b, &mut r) as usize] as u64);
                        let t = rv(&b, &mut r);
                        let x = rv(&b, &mut r);
                        eref(a, t);
                        eref(a, x);
                    }
                    13 => {
                        wv(a, name_f[rv(&b, &mut r) as usize] as u64);
                        for _ in 0..3 {
                            let d = rv(&b, &mut r);
                            eref(a, d);
                        }
                    }
                    14 | 15 => {
                        a.pop();
                        a.extend_from_slice(&b[p..q]);
                        fine = if tag == 14 { placed_for(nat_code, m) } else { str_codes.iter().all(|&c| placed_for(c, m)) };
                    }
                    16 => {
                        let nmi = rv(&b, &mut r);
                        fine = placed_for(code_by_id[nmi as usize], m);
                        wv(a, name_f[nmi as usize] as u64);
                        wv(a, rv(&b, &mut r));
                        let d = rv(&b, &mut r);
                        eref(a, d);
                    }
                    17 => {
                        let d = rv(&b, &mut r);
                        eref(a, d);
                    }
                    t => panic!("not an expression tag {t}"),
                }
                acc.fine &= fine;
                acc.k += 1;
            } else {
                let mut r = p + 1;
                let mref = |out: &mut Vec<u8>, d: u64| {
                    let c = e - d as u32;
                    wv(out, (mnext - newid[c as usize]) as u64);
                };
                match tag {
                    10 => {
                        out.push(10);
                        let f = rv(&b, &mut r);
                        let x = rv(&b, &mut r);
                        mref(&mut out, f);
                        mref(&mut out, x);
                    }
                    11 | 12 | 13 | 16 => {
                        let (skip, refs) = match tag {
                            11 | 12 => (2, 2),
                            13 => (1, 3),
                            _ => (2, 1),
                        };
                        // raw prefix: tag, (binder byte), then varints that are not references
                        let mut s = p + 1;
                        if tag == 11 || tag == 12 {
                            s += 1;
                            rv(&b, &mut s);
                        } else {
                            for _ in 0..skip {
                                rv(&b, &mut s);
                            }
                        }
                        out.extend_from_slice(&b[p..s]);
                        let mut r2 = s;
                        for _ in 0..refs {
                            let d = rv(&b, &mut r2);
                            mref(&mut out, d);
                        }
                    }
                    17 => {
                        out.push(17);
                        let d = rv(&b, &mut r);
                        mref(&mut out, d);
                    }
                    _ => out.extend_from_slice(&b[p..q]),
                }
                if o == EXPORTED {
                    out.extend_from_slice(&[19, 2, 1]);
                    fidx[ei] = f_e;
                    f_e += 1;
                }
                mnext += 1;
            }
            ei += 1;
        }
        p = q;
    }
    assert!(open.is_empty());
    assert_eq!(mnext, main);

    let mut f = std::io::BufWriter::new(std::fs::File::create(&args[2]).expect("create"));
    let mut hd: Vec<u8> = b"SUSZ\x02\0\0\0".to_vec();
    hd.extend_from_slice(header);
    let moff = hd.len() as u64;
    let poff = moff + out.len() as u64;
    let mut t: Vec<u8> = Vec::new();
    for x in [nnames, nlevels, main, ndecls] {
        t.extend_from_slice(&x.to_le_bytes());
    }
    for x in [moff, out.len() as u64, poff, proofs.len() as u64] {
        t.extend_from_slice(&x.to_le_bytes());
    }
    t.extend_from_slice(&56u32.to_le_bytes());
    t.extend_from_slice(b"ZSUS");
    assert_eq!(t.len(), 56);
    f.write_all(&hd).unwrap();
    f.write_all(&out).unwrap();
    f.write_all(&proofs).unwrap();
    f.write_all(&t).unwrap();
    f.flush().unwrap();
    eprintln!(
        "main exprs {main}, in blocks {}, lazy theorems {lazy}, frontier names {f_n} levels {f_l} exprs {f_e}; main block {} bytes, proof section {} bytes, file {} bytes (was {size})",
        n as u32 - main,
        out.len(),
        proofs.len(),
        poff + proofs.len() as u64 + 56
    );
}
