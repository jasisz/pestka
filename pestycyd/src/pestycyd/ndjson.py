from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Literal


Oracle = Literal["guaranteed-reject", "guaranteed-accept", "differential"]


@dataclass(frozen=True)
class Edit:
    line: int
    path: tuple[object, ...]
    field: str
    value: object
    delete: bool = False

    def json(self) -> dict[str, object]:
        return {
            "line": self.line + 1,
            "path": list(self.path),
            "field": self.field,
            "value": self.value,
            "delete": self.delete,
        }


@dataclass(frozen=True)
class LineEdit:
    kind: Literal["insert", "delete", "replace"]
    line: int
    value: dict[str, object] | None = None

    def json(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "line": self.line + 1,
            "value": self.value,
        }


@dataclass(frozen=True)
class Mutation:
    campaign: str
    label: str
    oracle: Oracle
    line: int
    path: tuple[object, ...]
    field: str
    value: object
    target: str
    end_line: int | None = None
    edits: tuple[Edit, ...] = ()
    delete: bool = False
    line_edits: tuple[LineEdit, ...] = ()

    def json(self) -> dict[str, object]:
        return {
            "campaign": self.campaign,
            "label": self.label,
            "oracle": self.oracle,
            "line": self.line + 1,
            "path": list(self.path),
            "field": self.field,
            "value": self.value,
            "target": self.target,
            "end_line": None if self.end_line is None else self.end_line + 1,
            "edits": [edit.json() for edit in self.edits],
            "delete": self.delete,
            "line_edits": [edit.json() for edit in self.line_edits],
        }


@dataclass(frozen=True)
class Document:
    lines: tuple[dict[str, object], ...]

    @classmethod
    def load(cls, path: Path) -> "Document":
        values: list[dict[str, object]] = []
        for number, raw in enumerate(path.read_text().splitlines(), 1):
            if not raw.strip():
                continue
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{number}: line is not a JSON object")
            values.append(value)
        return cls(tuple(values))

    def render(self) -> str:
        return "".join(
            json.dumps(line, separators=(",", ":"), ensure_ascii=False) + "\n"
            for line in self.lines
        )

    def final_goal_lines(self) -> frozenset[int]:
        """Return the final theorem and expression lines defining its type."""
        expressions = {
            ie: (line_no, line)
            for line_no, line in enumerate(self.lines)
            if isinstance((ie := line.get("ie")), int)
        }
        theorem_line: int | None = None
        root: int | None = None
        for line_no in range(len(self.lines) - 1, -1, -1):
            theorem = self.lines[line_no].get("thm")
            if isinstance(theorem, dict) and isinstance(theorem.get("type"), int):
                theorem_line = line_no
                root = theorem["type"]
                break
        if theorem_line is None or root is None:
            return frozenset()

        protected = {theorem_line}
        pending = [root]
        seen: set[int] = set()
        while pending:
            ie = pending.pop()
            if ie in seen or ie not in expressions:
                continue
            seen.add(ie)
            line_no, line = expressions[ie]
            protected.add(line_no)
            references: list[object] = []
            app = line.get("app")
            if isinstance(app, dict):
                references.extend((app.get("fn"), app.get("arg")))
            for binder in ("lam", "forallE"):
                obj = line.get(binder)
                if isinstance(obj, dict):
                    references.extend((obj.get("type"), obj.get("body")))
            let_expr = line.get("letE")
            if isinstance(let_expr, dict):
                references.extend(
                    (let_expr.get("type"), let_expr.get("value"), let_expr.get("body"))
                )
            proj = line.get("proj")
            if isinstance(proj, dict):
                references.append(proj.get("struct"))
            pending.extend(value for value in references if isinstance(value, int))
        return frozenset(protected)

    def mutated(self, mutation: Mutation) -> "Document":
        end = len(self.lines) if mutation.end_line is None else mutation.end_line + 1
        changed = copy.deepcopy(list(self.lines[:end]))
        edits = (
            Edit(
                mutation.line,
                mutation.path,
                mutation.field,
                mutation.value,
                delete=mutation.delete,
            ),
            *mutation.edits,
        )
        for edit in edits:
            if edit.line >= end:
                raise ValueError("mutation edit lies beyond its truncated document")
            current: object = changed[edit.line]
            for part in edit.path:
                current = current[part]  # type: ignore[index]
            if not isinstance(current, dict):
                raise ValueError("mutation path does not name an object")
            if edit.delete:
                if edit.field not in current:
                    raise ValueError("mutation deletes a missing field")
                del current[edit.field]
            else:
                current[edit.field] = edit.value
        for edit in sorted(mutation.line_edits, key=lambda item: item.line, reverse=True):
            if edit.kind == "insert":
                if edit.value is None or not 0 <= edit.line <= len(changed):
                    raise ValueError("invalid line insertion")
                changed.insert(edit.line, copy.deepcopy(edit.value))
            elif edit.kind == "delete":
                if not 0 <= edit.line < len(changed):
                    raise ValueError("invalid line deletion")
                del changed[edit.line]
            elif edit.kind == "replace":
                if edit.value is None or not 0 <= edit.line < len(changed):
                    raise ValueError("invalid line replacement")
                changed[edit.line] = copy.deepcopy(edit.value)
            else:  # pragma: no cover - Literal keeps callers honest
                raise ValueError(f"unknown line edit: {edit.kind}")
        return Document(tuple(changed))


def files(paths: list[str]) -> list[Path]:
    found: set[Path] = set()
    for raw in paths:
        path = Path(raw)
        if not path.exists():
            raise ValueError(f"input path does not exist: {path}")
        if path.is_dir():
            found.update(item.resolve() for item in path.rglob("*.ndjson"))
        elif path.suffix == ".ndjson":
            found.add(path.resolve())
        else:
            raise ValueError(f"input is neither an NDJSON file nor a directory: {path}")
    return sorted(found)


def walk_objects(value: object, path: tuple[object, ...] = ()) -> Iterator[tuple[tuple[object, ...], dict[str, object]]]:
    if isinstance(value, dict):
        yield path, value
        for key, child in value.items():
            yield from walk_objects(child, (*path, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk_objects(child, (*path, index))

