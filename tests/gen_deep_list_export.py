#!/usr/bin/env python3
"""Generate a valid export whose check compares two long lists cell by cell.

T : Type, z u : T, c : T -> T -> T, one : T := u, P : T -> Prop,
h : P (c u (c u ... z)), and the theorem P (c one (c one ... z)) := h: the
two lists are equal only argument by argument, each tail one comparison
deeper than the last. With "bad", the right list ends in u instead of z,
and the theorem is illtyped.
"""

import json
from pathlib import Path
import sys


def main() -> None:
    if len(sys.argv) not in (3, 4):
        raise SystemExit("usage: gen_deep_list_export.py LENGTH OUT.ndjson [bad]")
    bad = sys.argv[3:] == ["bad"]
    n = int(sys.argv[1])
    out = Path(sys.argv[2])
    lines = [{"meta": {"exporter": {"name": "lean4export", "version": "3.1.0"},
                       "format": {"version": "3.1.0"},
                       "lean": {"githash": "generated", "version": "4.35.0"}}}]
    names = ["T", "z", "u", "c", "one", "P", "h", "deepList"]
    for i, s in enumerate(names, 1):
        lines.append({"in": i, "str": {"pre": 0, "str": s}})
    T, Z, U, C, ONE, P, H, THM = range(1, 9)
    lines.append({"il": 1, "succ": 0})
    count = [0]

    def emit(value):
        i = count[0]
        count[0] += 1
        lines.append({"ie": i, **value})
        return i

    prop = emit({"sort": 0})
    typ = emit({"sort": 1})
    t = emit({"const": {"name": T, "us": []}})
    tt = emit({"forallE": {"binderInfo": "default", "body": t, "name": 0, "type": t}})
    ttt = emit({"forallE": {"binderInfo": "default", "body": tt, "name": 0, "type": t}})
    tp = emit({"forallE": {"binderInfo": "default", "body": prop, "name": 0, "type": t}})
    z = emit({"const": {"name": Z, "us": []}})
    u = emit({"const": {"name": U, "us": []}})
    c = emit({"const": {"name": C, "us": []}})
    one = emit({"const": {"name": ONE, "us": []}})
    p = emit({"const": {"name": P, "us": []}})
    h = emit({"const": {"name": H, "us": []}})

    def chain(x, last):
        acc = last
        cx = emit({"app": {"fn": c, "arg": x}})
        for _ in range(n):
            acc = emit({"app": {"fn": cx, "arg": acc}})
        return acc

    left = emit({"app": {"fn": p, "arg": chain(u, z)}})
    right = emit({"app": {"fn": p, "arg": chain(one, u if bad else z)}})
    def ax(name, ty):
        lines.append({"axiom": {"isUnsafe": False, "levelParams": [], "name": name, "type": ty}})
    ax(T, typ)
    ax(Z, t)
    ax(U, t)
    ax(C, ttt)
    lines.append({"def": {"all": [ONE], "hints": {"regular": 1}, "levelParams": [], "name": ONE,
                          "safety": "safe", "type": t, "value": u}})
    ax(P, tp)
    ax(H, left)
    lines.append({"thm": {"all": [THM], "levelParams": [], "name": THM, "type": right, "value": h}})
    out.write_text("".join(json.dumps(l, separators=(",", ":")) + "\n" for l in lines), encoding="utf-8")


if __name__ == "__main__":
    main()
