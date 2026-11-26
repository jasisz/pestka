#!/usr/bin/env python3
"""Generate a beta-redex over a lambda of N binders whose body is bound variable K.

With A : Type, c : A, Q2 : (A -> ... -> A) -> Prop (N arguments) and
F = fun x1 .. xN => #K, the theorem x : Q2 ((fun w : A => F) c) holds by
one beta step from h : Q2 F (good); from h : Q2 (fun x1 .. xN => c) it
does not (bad), as w does not occur in F. At N >= 16383 and K >= 16382 the
nodes' stored loose range is saturated (SaturatedRangeWalked in Check.Tc).
The hunt of 2026-11-26 found it as c-binders/h15_N16383_k16382_*.
"""

import json
from pathlib import Path
import sys


def main() -> None:
    if len(sys.argv) != 5 or sys.argv[3] not in ("good", "bad"):
        raise SystemExit("usage: gen_deep_beta_export.py N K good|bad OUT.ndjson")
    n, k, mode, out = int(sys.argv[1]), int(sys.argv[2]), sys.argv[3], Path(sys.argv[4])
    if not 0 <= k < n:
        raise SystemExit("K must be below N")
    lines = [{"meta": {"exporter": {"name": "lean4export", "version": "3.1.0"},
                       "format": {"version": "3.1.0"},
                       "lean": {"githash": "5045d0056413266e57c625dcd7c365b10e377c52", "version": "4.34.1"}}}]
    nexpr = [0]

    def expr(value: dict) -> int:
        i = nexpr[0]
        nexpr[0] += 1
        lines.append({**value, "ie": i})
        return i

    def name(i: int, s: str) -> int:
        lines.append({"in": i, "str": {"pre": 0, "str": s}})
        return i

    def axiom(nm: int, ty: int) -> None:
        lines.append({"axiom": {"isUnsafe": False, "levelParams": [], "name": nm, "type": ty}})

    def binder(kind: str, nm: int, ty: int, body: int) -> int:
        return expr({kind: {"binderInfo": "default", "body": body, "name": nm, "type": ty}})

    prop = expr({"sort": 0})
    lines.append({"succ": 0, "il": 1})
    typ = expr({"sort": 1})
    a_n = name(1, "A")
    axiom(a_n, typ)
    a = expr({"const": {"name": a_n, "us": []}})
    c_n = name(2, "c")
    axiom(c_n, a)
    x_n = name(3, "x")
    ty = a
    for _ in range(n):
        ty = binder("forallE", x_n, a, ty)
    q2_n = name(4, "Q2")
    f_n = name(5, "f")
    axiom(q2_n, binder("forallE", f_n, ty, prop))

    def lams(body: int) -> int:
        for _ in range(n):
            body = binder("lam", x_n, a, body)
        return body

    f = lams(expr({"bvar": k}))
    c = expr({"const": {"name": c_n, "us": []}})
    q2 = expr({"const": {"name": q2_n, "us": []}})
    h_n = name(6, "h")
    axiom(h_n, expr({"app": {"fn": q2, "arg": f if mode == "good" else lams(c)}}))
    w_n = name(7, "w")
    redex = expr({"app": {"fn": binder("lam", w_n, a, f), "arg": c}})
    stmt = expr({"app": {"fn": q2, "arg": redex}})
    h = expr({"const": {"name": h_n, "us": []}})
    lines.append({"thm": {"all": [x_n], "levelParams": [], "name": x_n, "type": stmt, "value": h}})
    out.write_text("".join(json.dumps(line, separators=(",", ":")) + "\n" for line in lines))


if __name__ == "__main__":
    main()
