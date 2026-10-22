"""Makes an ill-typed export from a well-typed one by rewriting one
declaration's type: the node reached by PATH (steps body/arg/fn/type/value)
in the type of declaration NAME becomes bvar J.

    python3 -I mkbad.py IN OUT NAME PATH J
"""
import json, sys
sys.setrecursionlimit(100000)
inp, out, name, path, j = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5])
lines = [json.loads(l) for l in open(inp)]
names = {}
for l in lines:
    if "in" in l:
        s, n = l.get("str"), l.get("num")
        if s:
            names[l["in"]] = ((names.get(s["pre"]) or "") + "." + s["str"]).lstrip(".")
        elif n:
            names[l["in"]] = ((names.get(n["pre"]) or "") + "." + str(n.get("i"))).lstrip(".")
exprs = {l["ie"]: l for l in lines if "ie" in l}
EXPR_FIELDS = {"app": ["fn", "arg"], "lam": ["type", "body"], "forallE": ["type", "body"], "letE": ["type", "value", "body"], "proj": ["struct"], "mdata": ["expr"]}
def tree(i):
    l = exprs[i]
    kind = next(k for k in l if k != "ie")
    p = l[kind]
    if kind in EXPR_FIELDS:
        p = dict(p)
        for f in EXPR_FIELDS[kind]:
            p[f] = tree(p[f])
    return (kind, p)
new_lines = []
nxt = [max(exprs) + 1]
def emit(t):
    kind, p = t
    if kind in EXPR_FIELDS:
        p = dict(p)
        for f in EXPR_FIELDS[kind]:
            p[f] = emit(p[f])
    i = nxt[0]; nxt[0] += 1
    new_lines.append({"ie": i, kind: p})
    return i
def replace(t, steps):
    if not steps:
        return ("bvar", j)
    kind, p = t
    step = steps[0]
    p = dict(p)
    p[step] = replace(p[step], steps[1:])
    return (kind, p)
decl_idx = None
for k, l in enumerate(lines):
    for kind in ("thm", "def", "defnInfo"):
        if kind in l and names.get(l[kind]["name"]) == name:
            decl_idx = k
assert decl_idx is not None, name
dk = next(k for k in lines[decl_idx])
t = tree(lines[decl_idx][dk]["type"])
root = emit(replace(t, path.split("/") if path else []))
lines[decl_idx][dk]["type"] = root
with open(out, "w") as f:
    for k, l in enumerate(lines):
        if k == decl_idx:
            for nl in new_lines:
                f.write(json.dumps(nl, ensure_ascii=False) + "\n")
        f.write(json.dumps(l, ensure_ascii=False) + "\n")
print(out, "new expressions:", len(new_lines))
