from __future__ import annotations

from collections.abc import Callable


def ddmin(lines: list[str], interesting: Callable[[list[str]], bool], keep: tuple[str, ...] = ()) -> list[str]:
    current = list(lines)
    groups = 2
    while True:
        removable = [
            index for index, line in enumerate(current)
            if not any(marker in line for marker in keep)
        ]
        if not removable:
            return current
        width = max(1, (len(removable) + groups - 1) // groups)
        reduced = False
        for start in range(0, len(removable), width):
            removed = set(removable[start : start + width])
            trial = [line for index, line in enumerate(current) if index not in removed]
            if trial and interesting(trial):
                current = trial
                groups = 2
                reduced = True
                break
        if reduced:
            continue
        if groups >= len(removable):
            return current
        groups = min(len(removable), groups * 2)

