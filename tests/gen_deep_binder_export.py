#!/usr/bin/env python3
"""Generate a tiny valid export with a deeply bound outer variable."""

import json
from pathlib import Path
import sys


def emit(lines: list[dict[str, object]], value: dict[str, object]) -> int:
    # The metadata and name are the only records before the contiguous
    # expression table.  Do not rescan the growing table for every node: the
    # interesting depths are around 2^14.
    index = len(lines) - 2
    value = {"ie": index, **value}
    lines.append(value)
    return index


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: gen_deep_binder_export.py DEPTH OUT.ndjson")
    depth = int(sys.argv[1])
    if depth < 1:
        raise SystemExit("DEPTH must be positive")
    out = Path(sys.argv[2])
    lines: list[dict[str, object]] = [
        {
            "meta": {
                "exporter": {"name": "lean4export", "version": "3.1.0"},
                "format": {"version": "3.1.0"},
                "lean": {"githash": "generated", "version": "4.35.0"},
            }
        },
        {"in": 1, "str": {"pre": 0, "str": "deepBinder"}},
    ]
    prop = emit(lines, {"sort": 0})
    outer_domain = emit(lines, {"bvar": depth - 1})
    outer_result = emit(lines, {"bvar": depth})
    theorem_type = emit(
        lines,
        {
            "forallE": {
                "binderInfo": "default",
                "body": outer_result,
                "name": 0,
                "type": outer_domain,
            }
        },
    )
    for _ in range(depth):
        theorem_type = emit(
            lines,
            {
                "forallE": {
                    "binderInfo": "default",
                    "body": theorem_type,
                    "name": 0,
                    "type": prop,
                }
            },
        )

    proof = emit(lines, {"bvar": 0})
    proof = emit(
        lines,
        {
            "lam": {
                "binderInfo": "default",
                "body": proof,
                "name": 0,
                "type": outer_domain,
            }
        },
    )
    for _ in range(depth):
        proof = emit(
            lines,
            {
                "lam": {
                    "binderInfo": "default",
                    "body": proof,
                    "name": 0,
                    "type": prop,
                }
            },
        )
    lines.append(
        {
            "thm": {
                "all": [1],
                "levelParams": [],
                "name": 1,
                "type": theorem_type,
                "value": proof,
            }
        }
    )
    out.write_text(
        "".join(json.dumps(line, separators=(",", ":")) + "\n" for line in lines),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
