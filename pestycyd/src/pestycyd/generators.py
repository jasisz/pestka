from __future__ import annotations

import json


def deep_binder(depth: int) -> str:
    """A tiny valid export whose body uses a deeply bound outer variable."""
    if depth < 1:
        raise ValueError("depth must be positive")
    lines: list[dict[str, object]] = [
        {
            "meta": {
                "exporter": {"name": "lean4export", "version": "3.1.0"},
                "format": {"version": "3.1.0"},
                "lean": {"githash": "pestycyd-generated", "version": "4.35.0"},
            }
        },
        {"in": 1, "str": {"pre": 0, "str": "deepBinder"}},
    ]

    def emit(value: dict[str, object]) -> int:
        index = len(lines) - 2
        lines.append({"ie": index, **value})
        return index

    prop = emit({"sort": 0})
    outer_domain = emit({"bvar": depth - 1})
    outer_result = emit({"bvar": depth})
    theorem_type = emit(
        {
            "forallE": {
                "binderInfo": "default",
                "body": outer_result,
                "name": 0,
                "type": outer_domain,
            }
        }
    )
    for _ in range(depth):
        theorem_type = emit(
            {
                "forallE": {
                    "binderInfo": "default",
                    "body": theorem_type,
                    "name": 0,
                    "type": prop,
                }
            }
        )
    proof = emit({"bvar": 0})
    proof = emit(
        {
            "lam": {
                "binderInfo": "default",
                "body": proof,
                "name": 0,
                "type": outer_domain,
            }
        }
    )
    for _ in range(depth):
        proof = emit(
            {
                "lam": {
                    "binderInfo": "default",
                    "body": proof,
                    "name": 0,
                    "type": prop,
                }
            }
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
    return "".join(json.dumps(line, separators=(",", ":")) + "\n" for line in lines)


def con_k_params(count: int) -> str:
    """A valid Lean module stressing K-recursor parameter guards."""
    if count < 1:
        raise ValueError("count must be positive")
    names = [f"P{index}" for index in range(count)]
    binders = " ".join(f"({name} : Prop)" for name in names)
    packed = "True"
    for name in reversed(names):
        packed = f"And {name} ({packed})"
    return f"""set_option maxRecDepth 100000

inductive WideK (A : Prop) : Prop where
  | mk : WideK A

opaque stuck (A : Prop) : WideK A := @WideK.mk A

noncomputable def collapse (A : Prop) : Nat :=
  WideK.rec (motive := fun _ => Nat) 0 (stuck A)

theorem collapse_eq {binders} : collapse ({packed}) = 0 := rfl
"""
