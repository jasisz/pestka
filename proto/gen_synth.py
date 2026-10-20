"""Synthetic NDJSON shaped like a lean4export dump, for parser timing only."""
import json, random, sys

random.seed(1)
target = int(sys.argv[2]) if len(sys.argv) > 2 else 10_000_000
out = open(sys.argv[1], "w")
size = 0
n = 0
while size < target:
    k = random.random()
    if k < 0.15:
        rec = {"in": n, "str": {"pre": max(0, n - random.randint(1, 50)), "str": "foo" + str(n)}}
    elif k < 0.2:
        rec = {"il": n, "succ": max(0, n - 1)}
    elif k < 0.5:
        rec = {"ie": n, "app": {"fn": random.randint(0, max(0, n - 1)), "arg": random.randint(0, max(0, n - 1))}}
    elif k < 0.65:
        rec = {"ie": n, "forallE": {"name": random.randint(0, n), "type": random.randint(0, n), "body": random.randint(0, n), "binderInfo": "default"}}
    elif k < 0.8:
        rec = {"ie": n, "const": {"name": random.randint(0, n), "us": [random.randint(0, n)]}}
    elif k < 0.95:
        rec = {"ie": n, "bvar": random.randint(0, 20)}
    else:
        rec = {"ie": n, "natVal": str(random.randint(0, 2**64))}
    line = json.dumps(rec, separators=(",", ":")) + "\n"
    out.write(line)
    size += len(line)
    n += 1
print(n, "lines")
