from __future__ import annotations

import copy
from collections import deque
from dataclasses import dataclass, replace
from typing import Callable, Iterable

from .ndjson import Document, Edit, LineEdit, Mutation, walk_objects


DECLARATION_KINDS = ("axiom", "def", "thm", "opaque")


@dataclass(frozen=True)
class Campaign:
    name: str
    oracle: str
    description: str
    targets: tuple[str, ...]
    generate: Callable[[Document], Iterable[Mutation]]


def _safe(kind: str, obj: dict[str, object]) -> bool:
    if kind == "def":
        return obj.get("safety") == "safe"
    if kind in {"axiom", "opaque"}:
        return obj.get("isUnsafe") is False
    return kind == "thm"


def closedness(document: Document) -> Iterable[Mutation]:
    prior_bvar: int | None = None
    for line_no, line in enumerate(document.lines):
        if isinstance(line.get("ie"), int) and isinstance(line.get("bvar"), int):
            prior_bvar = line["ie"]  # type: ignore[assignment]
        if prior_bvar is None:
            continue
        for kind in ("axiom", "def", "thm", "opaque"):
            obj = line.get(kind)
            if not isinstance(obj, dict) or not _safe(kind, obj):
                continue
            yield Mutation(
                "closedness", f"{kind}-type-loose", "guaranteed-reject", line_no,
                (kind,), "type", prior_bvar, "declaration type closedness guard",
            )
            if kind in {"def", "thm", "opaque"}:
                yield Mutation(
                    "closedness", f"{kind}-value-loose", "guaranteed-reject", line_no,
                    (kind,), "value", prior_bvar, "declaration value closedness guard",
                )
        block = line.get("inductive")
        if not isinstance(block, dict):
            continue
        unsafe = any(
            isinstance(item, dict) and item.get("isUnsafe") is True
            for group in ("types", "ctors", "recs")
            for item in (block.get(group) if isinstance(block.get(group), list) else [])
        )
        if unsafe:
            continue
        for group in ("types", "ctors", "recs"):
            items = block.get(group)
            if not isinstance(items, list):
                continue
            for index, item in enumerate(items):
                if isinstance(item, dict) and item.get("isUnsafe") is not True:
                    yield Mutation(
                        "closedness", f"inductive-{group}-{index}-type-loose",
                        "guaranteed-reject", line_no, ("inductive", group, index),
                        "type", prior_bvar, "inductive component closedness guard",
                    )


def duplicate_levels(document: Document) -> Iterable[Mutation]:
    for line_no, line in enumerate(document.lines):
        checked: list[tuple[tuple[object, ...], dict[str, object]]] = []
        for kind in DECLARATION_KINDS:
            obj = line.get(kind)
            if isinstance(obj, dict) and _safe(kind, obj):
                checked.append(((kind,), obj))
        block = line.get("inductive")
        if isinstance(block, dict):
            unsafe = any(
                isinstance(item, dict) and item.get("isUnsafe") is True
                for group in ("types", "ctors", "recs")
                for item in (block.get(group) if isinstance(block.get(group), list) else [])
            )
            if not unsafe:
                for group in ("types", "ctors", "recs"):
                    items = block.get(group)
                    if isinstance(items, list):
                        checked.extend(
                            (("inductive", group, index), item)
                            for index, item in enumerate(items)
                            if isinstance(item, dict)
                        )
        for path, obj in checked:
            params = obj.get("levelParams")
            if isinstance(params, list) and params and all(isinstance(x, int) for x in params):
                yield Mutation(
                    "level-params", "duplicate-level-parameter", "guaranteed-reject",
                    line_no, path, "levelParams", [params[0], *params],
                    "universe parameter nodup guard",
                )


def _declared_names(line: dict[str, object]) -> list[int]:
    names: list[int] = []
    for kind in DECLARATION_KINDS:
        obj = line.get(kind)
        if isinstance(obj, dict) and isinstance(obj.get("name"), int):
            names.append(obj["name"])
    block = line.get("inductive")
    if isinstance(block, dict):
        for group in ("types", "ctors", "recs"):
            items = block.get(group)
            if isinstance(items, list):
                names.extend(
                    item["name"]
                    for item in items
                    if isinstance(item, dict) and isinstance(item.get("name"), int)
                )
    return names


def _declared_params(line: dict[str, object]) -> list[int]:
    params: list[int] = []
    for kind in DECLARATION_KINDS:
        obj = line.get(kind)
        if isinstance(obj, dict) and isinstance(obj.get("levelParams"), list):
            params.extend(value for value in obj["levelParams"] if isinstance(value, int))
    block = line.get("inductive")
    if isinstance(block, dict):
        for group in ("types", "ctors", "recs"):
            items = block.get(group)
            if not isinstance(items, list):
                continue
            for item in items:
                if isinstance(item, dict) and isinstance(item.get("levelParams"), list):
                    params.extend(value for value in item["levelParams"] if isinstance(value, int))
    return params


def _is_declaration(line: dict[str, object]) -> bool:
    return any(kind in line for kind in (*DECLARATION_KINDS, "quot", "inductive"))


def _expression_loose_ranges(document: Document) -> dict[int, int]:
    """Compute the number of surrounding binders required by each expression node."""
    loose: dict[int, int] = {}

    def child(value: object) -> int:
        return loose.get(value, 0) if isinstance(value, int) else 0

    for line in document.lines:
        ie = line.get("ie")
        if not isinstance(ie, int):
            continue
        if isinstance(line.get("bvar"), int):
            value = line["bvar"]
            loose[ie] = value + 1 if isinstance(value, int) else 0
            continue
        app = line.get("app")
        if isinstance(app, dict):
            loose[ie] = max(child(app.get("fn")), child(app.get("arg")))
            continue
        binder = line.get("lam") or line.get("forallE")
        if isinstance(binder, dict):
            loose[ie] = max(child(binder.get("type")), max(child(binder.get("body")) - 1, 0))
            continue
        let_expr = line.get("letE")
        if isinstance(let_expr, dict):
            loose[ie] = max(
                child(let_expr.get("type")),
                child(let_expr.get("value")),
                max(child(let_expr.get("body")) - 1, 0),
            )
            continue
        proj = line.get("proj")
        if isinstance(proj, dict):
            loose[ie] = child(proj.get("struct"))
            continue
        loose[ie] = 0
    return loose


def expression_structure(document: Document) -> Iterable[Mutation]:
    """The expression-level, oracle-guided sweep from arena-candidate."""
    next_declarations: list[int | None] = [None] * len(document.lines)
    next_declaration: int | None = None
    for line_no in range(len(document.lines) - 1, -1, -1):
        if _is_declaration(document.lines[line_no]):
            next_declaration = line_no
        next_declarations[line_no] = next_declaration

    bvars_by_index: dict[int, int] = {}
    last_name: int | None = None
    for line_no, line in enumerate(document.lines):
        prior_name = last_name
        ie, bvar = line.get("ie"), line.get("bvar")
        if isinstance(ie, int) and isinstance(bvar, int):
            bvars_by_index.setdefault(bvar, ie)
        names = _declared_names(line)
        if names:
            last_name = names[-1]
        end_line = next_declarations[line_no]
        if end_line is None or end_line <= line_no:
            continue

        if isinstance(bvar, int) and not isinstance(bvar, bool):
            yield Mutation("expression-structure", "bvar-plus-one", "differential", line_no,
                           (), "bvar", bvar + 1, "bound-variable index handling", end_line)
        const = line.get("const")
        if isinstance(const, dict):
            levels = const.get("us")
            if isinstance(levels, list) and levels:
                yield Mutation("expression-structure", "const-levels-empty", "differential",
                               line_no, ("const",), "us", [], "constant universe instantiation", end_line)
                yield Mutation("expression-structure", "const-level-duplicate", "differential",
                               line_no, ("const",), "us", [levels[0], *levels],
                               "constant universe instantiation", end_line)
            name = const.get("name")
            if prior_name is not None and isinstance(name, int) and name != prior_name:
                yield Mutation("expression-structure", "const-name-from-prior", "differential",
                               line_no, ("const",), "name", prior_name,
                               "constant lookup and arity validation", end_line)
        app = line.get("app")
        if isinstance(app, dict):
            fn, arg = app.get("fn"), app.get("arg")
            if isinstance(fn, int) and isinstance(arg, int) and fn != arg:
                yield Mutation("expression-structure", "app-fn-from-arg", "differential", line_no,
                               ("app",), "fn", arg, "application inference", end_line)
                yield Mutation("expression-structure", "app-arg-from-fn", "differential", line_no,
                               ("app",), "arg", fn, "application inference", end_line)
        for binder in ("lam", "forallE"):
            obj = line.get(binder)
            if not isinstance(obj, dict):
                continue
            ty, body = obj.get("type"), obj.get("body")
            if isinstance(ty, int) and isinstance(body, int) and ty != body:
                yield Mutation("expression-structure", f"{binder}-type-from-body", "differential",
                               line_no, (binder,), "type", body, "binder domain checking", end_line)
                yield Mutation("expression-structure", f"{binder}-body-from-type", "differential",
                               line_no, (binder,), "body", ty, "binder body checking", end_line)
            if binder == "lam":
                for index in (0, 1):
                    replacement = bvars_by_index.get(index)
                    if replacement is not None and body != replacement:
                        yield Mutation("expression-structure", f"lam-body-from-bvar-{index}",
                                       "differential", line_no, (binder,), "body", replacement,
                                       "closure and binder-depth handling", end_line)
        let_expr = line.get("letE")
        if isinstance(let_expr, dict):
            ty, value, body = let_expr.get("type"), let_expr.get("value"), let_expr.get("body")
            if isinstance(ty, int) and isinstance(value, int) and ty != value:
                yield Mutation("expression-structure", "let-value-from-type", "differential",
                               line_no, ("letE",), "value", ty, "let value checking", end_line)
            if isinstance(value, int) and isinstance(body, int) and value != body:
                yield Mutation("expression-structure", "let-body-from-value", "differential",
                               line_no, ("letE",), "body", value, "let body substitution", end_line)
        proj = line.get("proj")
        if isinstance(proj, dict):
            index = proj.get("idx")
            if isinstance(index, int) and not isinstance(index, bool):
                yield Mutation("expression-structure", "proj-index-plus-one", "differential",
                               line_no, ("proj",), "idx", index + 1, "projection validation", end_line)
            type_name = proj.get("typeName")
            if prior_name is not None and isinstance(type_name, int) and type_name != prior_name:
                yield Mutation("expression-structure", "proj-type-from-prior", "differential",
                               line_no, ("proj",), "typeName", prior_name,
                               "projection inductive lookup", end_line)


def expression_structure_full(document: Document) -> Iterable[Mutation]:
    """Apply expression mutations without dropping downstream declarations."""
    for mutation in expression_structure(document):
        yield replace(
            mutation,
            campaign="expression-structure-full",
            label=f"full-{mutation.label}",
            end_line=None,
        )


def declaration_structure(document: Document) -> Iterable[Mutation]:
    last_name: int | None = None
    last_param: int | None = None
    for line_no, line in enumerate(document.lines):
        prior_name, prior_param = last_name, last_param
        names, params_here = _declared_names(line), _declared_params(line)
        if names:
            last_name = names[-1]
        if params_here:
            last_param = params_here[-1]
        for kind in DECLARATION_KINDS:
            obj = line.get(kind)
            if not isinstance(obj, dict) or not _safe(kind, obj):
                continue
            path = (kind,)
            params = obj.get("levelParams")
            if isinstance(params, list) and params:
                yield Mutation("declaration-structure", f"{kind}-levels-empty", "differential",
                               line_no, path, "levelParams", [], "declaration universe validation", line_no)
                if len(params) > 1:
                    yield Mutation("declaration-structure", f"{kind}-level-drop-first", "differential",
                                   line_no, path, "levelParams", params[1:],
                                   "declaration universe validation", line_no)
                if prior_param is not None and prior_param not in params:
                    yield Mutation("declaration-structure", f"{kind}-level-from-prior", "differential",
                                   line_no, path, "levelParams", [prior_param, *params[1:]],
                                   "universe parameter scope", line_no)
            if prior_name is not None:
                yield Mutation("declaration-structure", f"{kind}-duplicate-name", "differential",
                               line_no, path, "name", prior_name, "environment insertion", line_no)
            ty, value = obj.get("type"), obj.get("value")
            if isinstance(ty, int) and isinstance(value, int) and ty != value:
                yield Mutation("declaration-structure", f"{kind}-type-from-value", "differential",
                               line_no, path, "type", value, "declaration type/value agreement", line_no)
                yield Mutation("declaration-structure", f"{kind}-value-from-type", "differential",
                               line_no, path, "value", ty, "declaration type/value agreement", line_no)
            all_names = obj.get("all")
            if isinstance(all_names, list) and all_names:
                yield Mutation("declaration-structure", f"{kind}-all-empty", "differential",
                               line_no, path, "all", [], "declaration dependency metadata", line_no)
                yield Mutation("declaration-structure", f"{kind}-all-duplicate", "differential",
                               line_no, path, "all", [all_names[0], *all_names],
                               "declaration dependency metadata", line_no)


def declaration_structure_full(document: Document) -> Iterable[Mutation]:
    """Mutate declaration structure without dropping dependent declarations."""
    for mutation in declaration_structure(document):
        yield replace(
            mutation,
            campaign="declaration-structure-full",
            label=f"full-{mutation.label}",
            end_line=None,
        )


def binder_context_pairs(document: Document) -> Iterable[Mutation]:
    """Force declaration checking to compare related Pi/lambda closure pairs."""
    loose_ranges = _expression_loose_ranges(document)
    pis_by_body: dict[int, list[int]] = {}
    pis_by_type: dict[int, list[int]] = {}
    lams_by_body: dict[int, list[int]] = {}
    lams_by_type: dict[int, list[int]] = {}
    candidates: deque[tuple[int, int]] = deque(maxlen=64)

    def add_pairs(ie: int, obj: dict[str, object], other_body: dict[int, list[int]],
                  other_type: dict[int, list[int]], reverse: bool) -> None:
        related: list[int] = []
        body, ty = obj.get("body"), obj.get("type")
        if isinstance(body, int):
            related.extend(other_body.get(body, ())[-4:])
        if isinstance(ty, int):
            related.extend(other_type.get(ty, ())[-4:])
        for other in dict.fromkeys(related):
            candidates.append((other, ie) if reverse else (ie, other))

    for line_no, line in enumerate(document.lines):
        ie = line.get("ie")
        pi = line.get("forallE")
        lam = line.get("lam")
        if isinstance(ie, int) and isinstance(pi, dict):
            if loose_ranges.get(ie) == 0:
                add_pairs(ie, pi, lams_by_body, lams_by_type, False)
            if isinstance(pi.get("body"), int):
                if loose_ranges.get(ie) == 0:
                    pis_by_body.setdefault(pi["body"], []).append(ie)
            if isinstance(pi.get("type"), int):
                if loose_ranges.get(ie) == 0:
                    pis_by_type.setdefault(pi["type"], []).append(ie)
        if isinstance(ie, int) and isinstance(lam, dict):
            if loose_ranges.get(ie) == 0:
                add_pairs(ie, lam, pis_by_body, pis_by_type, True)
            if isinstance(lam.get("body"), int):
                if loose_ranges.get(ie) == 0:
                    lams_by_body.setdefault(lam["body"], []).append(ie)
            if isinstance(lam.get("type"), int):
                if loose_ranges.get(ie) == 0:
                    lams_by_type.setdefault(lam["type"], []).append(ie)

        for kind in ("def", "thm", "opaque"):
            declar = line.get(kind)
            if not isinstance(declar, dict) or not _safe(kind, declar):
                continue
            current = (declar.get("type"), declar.get("value"))
            for pi_ie, lam_ie in tuple(candidates)[-16:]:
                if current == (pi_ie, lam_ie):
                    continue
                yield Mutation(
                    "binder-context-pairs",
                    f"{kind}-pi-{pi_ie}-lam-{lam_ie}",
                    "differential",
                    line_no,
                    (kind,),
                    "type",
                    pi_ie,
                    "Pi/lambda closure context comparison",
                    edits=(Edit(line_no, (kind,), "value", lam_ie),),
                )


def const_universe_crosswire(document: Document) -> Iterable[Mutation]:
    """Cross-wire level instantiations of two occurrences of the same constant."""
    by_name: dict[int, list[tuple[int, list[object]]]] = {}
    for line_no, line in enumerate(document.lines):
        const = line.get("const")
        if not isinstance(const, dict):
            continue
        name, levels = const.get("name"), const.get("us")
        if not isinstance(name, int) or not isinstance(levels, list):
            continue
        for other_line, other_levels in by_name.get(name, ())[-8:]:
            if levels == other_levels:
                continue
            yield Mutation(
                "const-universe-crosswire",
                f"const-{name}-levels-from-{other_line + 1}",
                "differential",
                line_no,
                ("const",),
                "us",
                other_levels,
                "constant level-substitution environment",
            )
            yield Mutation(
                "const-universe-crosswire",
                f"const-{name}-levels-swap-{other_line + 1}-{line_no + 1}",
                "differential",
                line_no,
                ("const",),
                "us",
                other_levels,
                "paired constant level-substitution environments",
                edits=(Edit(other_line, ("const",), "us", levels),),
            )
        by_name.setdefault(name, []).append((line_no, list(levels)))


def typed_neighborhood_crosswire(document: Document) -> Iterable[Mutation]:
    """Cross-wire references that occur in the same approximate type context.

    Unlike the broad expression campaign, this keeps the surrounding operator
    fixed: arguments are exchanged between applications of the same function,
    binder bodies between binders with the same domain, and so on.  Equal loose
    ranges are only a syntactic approximation of typing, but they avoid most of
    the immediate loose-bvar failures while still perturbing context-sensitive
    inference and conversion.
    """
    loose_ranges = _expression_loose_ranges(document)
    expression_lines = {
        ie: line_no
        for line_no, line in enumerate(document.lines)
        if isinstance((ie := line.get("ie")), int)
    }
    groups: dict[
        tuple[object, ...],
        list[tuple[int, tuple[object, ...], str, int]],
    ] = {}

    def related(
        key: tuple[object, ...],
        line_no: int,
        path: tuple[object, ...],
        field: str,
        value: object,
        target: str,
    ) -> Iterable[Mutation]:
        if not isinstance(value, int):
            return
        entries = groups.setdefault(key, [])
        for other_line, other_path, other_field, other_value in entries[-8:]:
            if value == other_value:
                continue
            if loose_ranges.get(value) != loose_ranges.get(other_value):
                continue
            stem = f"{key[0]}-{field}-{other_line + 1}-{line_no + 1}"
            yield Mutation(
                "typed-neighborhood-crosswire",
                f"{stem}-from-prior",
                "differential",
                line_no,
                path,
                field,
                other_value,
                target,
            )
            # The earlier node may only point to an expression already defined
            # before it.  Without this guard an atomic swap commonly creates a
            # forward reference and merely exercises parser robustness.
            if expression_lines.get(value, len(document.lines)) < other_line:
                yield Mutation(
                    "typed-neighborhood-crosswire",
                    f"{stem}-swap",
                    "differential",
                    line_no,
                    path,
                    field,
                    other_value,
                    target,
                    edits=(Edit(other_line, other_path, other_field, value),),
                )
        entries.append((line_no, path, field, value))

    for line_no, line in enumerate(document.lines):
        app = line.get("app")
        if isinstance(app, dict):
            fn, arg = app.get("fn"), app.get("arg")
            if isinstance(fn, int):
                yield from related(
                    ("same-fn-app", fn), line_no, ("app",), "arg", arg,
                    "application arguments under a shared function",
                )
            if isinstance(arg, int):
                yield from related(
                    ("same-arg-app", arg), line_no, ("app",), "fn", fn,
                    "application functions under a shared argument",
                )

        for binder in ("lam", "forallE"):
            obj = line.get(binder)
            if not isinstance(obj, dict):
                continue
            ty, body = obj.get("type"), obj.get("body")
            if isinstance(ty, int):
                yield from related(
                    (f"same-domain-{binder}", ty), line_no, (binder,), "body", body,
                    "binder bodies under a shared domain",
                )
            if isinstance(body, int):
                yield from related(
                    (f"same-body-{binder}", body), line_no, (binder,), "type", ty,
                    "binder domains around a shared body",
                )

        let_expr = line.get("letE")
        if isinstance(let_expr, dict):
            ty, value = let_expr.get("type"), let_expr.get("value")
            if isinstance(ty, int):
                yield from related(
                    ("same-type-let", ty), line_no, ("letE",), "value", value,
                    "let values under a shared annotation",
                )

        proj = line.get("proj")
        if isinstance(proj, dict):
            key = ("same-projection", proj.get("typeName"), proj.get("idx"))
            yield from related(
                key, line_no, ("proj",), "struct", proj.get("struct"),
                "projection majors with shared structure metadata",
            )

        for kind in ("def", "thm", "opaque"):
            declaration = line.get(kind)
            if not isinstance(declaration, dict) or not _safe(kind, declaration):
                continue
            ty = declaration.get("type")
            if isinstance(ty, int):
                yield from related(
                    ("same-declaration-type", kind, ty),
                    line_no,
                    (kind,),
                    "value",
                    declaration.get("value"),
                    "declaration values with an identical serialized type",
                )


def recursor_rule_permutations(document: Document) -> Iterable[Mutation]:
    """Swap correlated fields in adjacent recursor rules instead of corrupting one side."""
    for line_no, line in enumerate(document.lines):
        block = line.get("inductive")
        if not isinstance(block, dict) or not isinstance(block.get("recs"), list):
            continue
        for rec_index, rec in enumerate(block["recs"]):
            if not isinstance(rec, dict) or not isinstance(rec.get("rules"), list):
                continue
            rules = rec["rules"]
            for index in range(len(rules) - 1):
                left, right = rules[index], rules[index + 1]
                if not isinstance(left, dict) or not isinstance(right, dict):
                    continue
                left_path = ("inductive", "recs", rec_index, "rules", index)
                right_path = ("inductive", "recs", rec_index, "rules", index + 1)
                for fields in (("rhs",), ("ctor",), ("rhs", "ctor")):
                    if any(field not in left or field not in right for field in fields):
                        continue
                    if all(left[field] == right[field] for field in fields):
                        continue
                    first, *remaining = fields
                    edits = [Edit(line_no, right_path, first, left[first])]
                    for field in remaining:
                        edits.extend(
                            (
                                Edit(line_no, left_path, field, right[field]),
                                Edit(line_no, right_path, field, left[field]),
                            )
                        )
                    yield Mutation(
                        "recursor-rule-permutations",
                        f"rec-{rec_index}-rules-{index}-{index + 1}-swap-{'-'.join(fields)}",
                        "differential",
                        line_no,
                        left_path,
                        first,
                        right[first],
                        "correlated recursor-rule permutation",
                        edits=tuple(edits),
                    )


def inductive_block_crosswire(document: Document) -> Iterable[Mutation]:
    """Transplant earlier, shape-compatible inductive semantics into later blocks.

    References taken from an earlier block cannot become forward references.  Keeping
    the later names, constructor association and rule arities makes these mutations
    useful for finding checkers which validate the block's surface shape but trust a
    serialized type or recursor right-hand side.
    """
    loose_ranges = _expression_loose_ranges(document)
    prior_blocks: list[tuple[int, dict[str, object]]] = []
    for line_no, line in enumerate(document.lines):
        block = line.get("inductive")
        if not isinstance(block, dict):
            continue

        current_types = block.get("types")
        current_ctors = block.get("ctors")
        current_recs = block.get("recs")
        if not all(isinstance(group, list) for group in (current_types, current_ctors, current_recs)):
            prior_blocks.append((line_no, block))
            continue

        for prior_line, prior in prior_blocks:
            prior_types = prior.get("types")
            prior_ctors = prior.get("ctors")
            prior_recs = prior.get("recs")
            if not all(isinstance(group, list) for group in (prior_types, prior_ctors, prior_recs)):
                continue

            for rec_index, current_rec in enumerate(current_recs):
                if not isinstance(current_rec, dict) or not isinstance(current_rec.get("rules"), list):
                    continue
                for prior_rec_index, prior_rec in enumerate(prior_recs):
                    if not isinstance(prior_rec, dict) or not isinstance(prior_rec.get("rules"), list):
                        continue
                    for rule_index, current_rule in enumerate(current_rec["rules"]):
                        if not isinstance(current_rule, dict):
                            continue
                        current_rhs = current_rule.get("rhs")
                        if not isinstance(current_rhs, int):
                            continue
                        for prior_rule_index, prior_rule in enumerate(prior_rec["rules"]):
                            if not isinstance(prior_rule, dict):
                                continue
                            prior_rhs = prior_rule.get("rhs")
                            if (
                                not isinstance(prior_rhs, int)
                                or prior_rhs == current_rhs
                                or current_rule.get("nfields") != prior_rule.get("nfields")
                                or loose_ranges.get(current_rhs, 0) != loose_ranges.get(prior_rhs, 0)
                            ):
                                continue
                            yield Mutation(
                                "inductive-block-crosswire",
                                (
                                    f"block-{prior_line + 1}-rec-{prior_rec_index}-rule-"
                                    f"{prior_rule_index}-into-rec-{rec_index}-rule-{rule_index}"
                                ),
                                "differential",
                                line_no,
                                ("inductive", "recs", rec_index, "rules", rule_index),
                                "rhs",
                                prior_rhs,
                                "scope-compatible cross-block recursor RHS",
                            )

            for rec_index, (current_rec, prior_rec) in enumerate(zip(current_recs, prior_recs)):
                if not isinstance(current_rec, dict) or not isinstance(prior_rec, dict):
                    continue
                current_rules = current_rec.get("rules")
                prior_rules = prior_rec.get("rules")
                if (
                    not isinstance(current_rules, list)
                    or not isinstance(prior_rules, list)
                    or len(current_rules) != len(prior_rules)
                    or not current_rules
                ):
                    continue

                compatible = all(
                    current_rec.get(field) == prior_rec.get(field)
                    for field in ("numParams", "numIndices", "numMotives", "numMinors")
                )
                compatible = compatible and all(
                    isinstance(current_rule, dict)
                    and isinstance(prior_rule, dict)
                    and current_rule.get("nfields") == prior_rule.get("nfields")
                    for current_rule, prior_rule in zip(current_rules, prior_rules)
                )
                if not compatible:
                    continue

                mapped_rules: list[object] = []
                changed = False
                for rule_index, (current_rule, prior_rule) in enumerate(
                    zip(current_rules, prior_rules)
                ):
                    if not isinstance(current_rule, dict) or not isinstance(prior_rule, dict):
                        mapped_rules = []
                        break
                    prior_rhs = prior_rule.get("rhs")
                    current_rhs = current_rule.get("rhs")
                    if not isinstance(prior_rhs, int) or not isinstance(current_rhs, int):
                        mapped_rules = []
                        break
                    mapped = dict(current_rule)
                    mapped["rhs"] = prior_rhs
                    mapped_rules.append(mapped)
                    if prior_rhs != current_rhs:
                        changed = True
                        yield Mutation(
                            "inductive-block-crosswire",
                            f"block-{prior_line + 1}-rec-{rec_index}-rule-{rule_index}-rhs",
                            "differential",
                            line_no,
                            ("inductive", "recs", rec_index, "rules", rule_index),
                            "rhs",
                            prior_rhs,
                            "shape-compatible cross-block recursor semantics",
                        )
                if changed and len(mapped_rules) == len(current_rules) and len(current_rules) > 1:
                    yield Mutation(
                        "inductive-block-crosswire",
                        f"block-{prior_line + 1}-rec-{rec_index}-all-rhs",
                        "differential",
                        line_no,
                        ("inductive", "recs", rec_index),
                        "rules",
                        mapped_rules,
                        "correlated cross-block recursor semantics",
                    )

            same_shape = (
                len(current_types) == len(prior_types)
                and len(current_ctors) == len(prior_ctors)
                and len(current_recs) == len(prior_recs)
                and all(
                    isinstance(current, dict)
                    and isinstance(old, dict)
                    and all(current.get(field) == old.get(field) for field in fields)
                    for current, old, fields in (
                        *(
                            (current, old, ("numParams", "numIndices"))
                            for current, old in zip(current_types, prior_types)
                        ),
                        *(
                            (current, old, ("numParams", "numFields", "cidx"))
                            for current, old in zip(current_ctors, prior_ctors)
                        ),
                        *(
                            (current, old, ("numParams", "numIndices", "numMotives", "numMinors"))
                            for current, old in zip(current_recs, prior_recs)
                        ),
                    )
                )
            )
            if not same_shape:
                continue

            edits: list[Edit] = []
            for group_name, current_group, prior_group in (
                ("types", current_types, prior_types),
                ("ctors", current_ctors, prior_ctors),
            ):
                for index, (current, old) in enumerate(zip(current_group, prior_group)):
                    if (
                        isinstance(current, dict)
                        and isinstance(old, dict)
                        and isinstance(old.get("type"), int)
                        and current.get("type") != old["type"]
                    ):
                        edits.append(
                            Edit(line_no, ("inductive", group_name, index), "type", old["type"])
                        )
            for rec_index, (current_rec, prior_rec) in enumerate(zip(current_recs, prior_recs)):
                if not isinstance(current_rec, dict) or not isinstance(prior_rec, dict):
                    continue
                if isinstance(prior_rec.get("type"), int) and current_rec.get("type") != prior_rec["type"]:
                    edits.append(
                        Edit(line_no, ("inductive", "recs", rec_index), "type", prior_rec["type"])
                    )
                current_rules = current_rec.get("rules")
                prior_rules = prior_rec.get("rules")
                if not isinstance(current_rules, list) or not isinstance(prior_rules, list):
                    continue
                for rule_index, (current_rule, prior_rule) in enumerate(
                    zip(current_rules, prior_rules)
                ):
                    if (
                        isinstance(current_rule, dict)
                        and isinstance(prior_rule, dict)
                        and current_rule.get("nfields") == prior_rule.get("nfields")
                        and isinstance(prior_rule.get("rhs"), int)
                        and current_rule.get("rhs") != prior_rule["rhs"]
                    ):
                        edits.append(
                            Edit(
                                line_no,
                                ("inductive", "recs", rec_index, "rules", rule_index),
                                "rhs",
                                prior_rule["rhs"],
                            )
                        )
            if edits:
                primary, *remaining = edits
                yield Mutation(
                    "inductive-block-crosswire",
                    f"block-{prior_line + 1}-semantic-bundle",
                    "differential",
                    primary.line,
                    primary.path,
                    primary.field,
                    primary.value,
                    "shape-compatible inductive semantic transplant",
                    edits=tuple(remaining),
                )

        prior_blocks.append((line_no, block))


def _declaration_expression_roots(line: dict[str, object]) -> list[int]:
    """Return expression IDs consumed directly by a declaration line."""
    roots: list[int] = []

    def take(value: object) -> None:
        if isinstance(value, int) and not isinstance(value, bool):
            roots.append(value)

    for kind in DECLARATION_KINDS:
        declaration = line.get(kind)
        if isinstance(declaration, dict):
            take(declaration.get("type"))
            take(declaration.get("value"))

    block = line.get("inductive")
    if isinstance(block, dict):
        for group in ("types", "ctors", "recs"):
            items = block.get(group)
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                take(item.get("type"))
                rules = item.get("rules")
                if isinstance(rules, list):
                    for rule in rules:
                        if isinstance(rule, dict):
                            take(rule.get("rhs"))
    return roots


def _expression_children(line: dict[str, object]) -> tuple[int, ...]:
    values: list[object] = []
    app = line.get("app")
    if isinstance(app, dict):
        values.extend((app.get("fn"), app.get("arg")))
    for binder in ("lam", "forallE"):
        obj = line.get(binder)
        if isinstance(obj, dict):
            values.extend((obj.get("type"), obj.get("body")))
    let_expr = line.get("letE")
    if isinstance(let_expr, dict):
        values.extend(
            (let_expr.get("type"), let_expr.get("value"), let_expr.get("body"))
        )
    proj = line.get("proj")
    if isinstance(proj, dict):
        values.append(proj.get("struct"))
    mdata = line.get("mdata")
    if isinstance(mdata, dict):
        values.append(mdata.get("expr"))
    return tuple(
        value
        for value in values
        if isinstance(value, int) and not isinstance(value, bool)
    )


def intern_table_shadowing(document: Document) -> Iterable[Mutation]:
    """Shadow an expression-table entry immediately before it is consumed.

    The original entry and declaration stay byte-for-byte present. Only a second
    line with the same ``ie`` is inserted. This exercises the parser/kernel
    boundary: a checker must not silently pick a convenient value for a duplicate
    intern-table key. Restricting replacements to equal loose-variable ranges
    avoids spending the frontier almost entirely on trivially open terms.
    """
    loose_ranges = _expression_loose_ranges(document)
    expressions: dict[int, tuple[int, dict[str, object]]] = {}

    for declaration_line, line in enumerate(document.lines):
        ie = line.get("ie")
        if isinstance(ie, int) and not isinstance(ie, bool):
            expressions[ie] = (declaration_line, line)
        if not _is_declaration(line):
            continue

        pending = deque(_declaration_expression_roots(line))
        target_ids: list[int] = []
        seen: set[int] = set()
        while pending and len(target_ids) < 64:
            target = pending.popleft()
            if target in seen or target not in expressions:
                continue
            seen.add(target)
            target_ids.append(target)
            pending.extend(_expression_children(expressions[target][1]))

        available = list(expressions.items())
        for target in target_ids:
            target_line, target_value = expressions[target]
            target_payload = {key: value for key, value in target_value.items() if key != "ie"}
            target_shape = next((key for key in target_payload if key != "info"), "")
            candidates: list[tuple[bool, int, dict[str, object]]] = []
            for source, (source_line, source_value) in available:
                if source == target or loose_ranges.get(source, 0) != loose_ranges.get(target, 0):
                    continue
                source_payload = {
                    key: value for key, value in source_value.items() if key != "ie"
                }
                if source_payload == target_payload:
                    continue
                source_shape = next((key for key in source_payload if key != "info"), "")
                candidates.append((source_shape != target_shape, source_line, source_value))

            # Prefer nearby expressions of the same shape, while retaining a few
            # cross-shape substitutions that reach different parser/checker paths.
            candidates.sort(key=lambda item: (item[0], -item[1]))
            same_shape = [candidate for candidate in candidates if not candidate[0]][:6]
            cross_shape = [candidate for candidate in candidates if candidate[0]][:2]
            for _, source_line, source_value in (*same_shape, *cross_shape):
                shadow = copy.deepcopy(source_value)
                shadow["ie"] = target
                yield Mutation(
                    "intern-table-shadowing",
                    f"ie-{target}-from-line-{source_line + 1}-before-{declaration_line + 1}",
                    "differential",
                    target_line,
                    (),
                    "ie",
                    target,
                    "duplicate expression intern key and environment consumption",
                    line_edits=(LineEdit("insert", declaration_line, shadow),),
                )


def field_deletion(document: Document) -> Iterable[Mutation]:
    """Delete mandatory checker-facing fields while preserving the full export."""
    declaration_fields = {
        "axiom": ("name", "levelParams", "type", "isUnsafe"),
        "def": ("name", "levelParams", "type", "value", "safety"),
        "thm": ("name", "levelParams", "type", "value"),
        "opaque": ("name", "levelParams", "type", "value", "isUnsafe"),
    }
    inductive_fields = {
        "types": (
            "name", "levelParams", "type", "numParams", "numIndices",
            "numNested", "ctors", "isRec", "isReflexive", "isUnsafe",
        ),
        "ctors": (
            "name", "levelParams", "type", "induct", "cidx", "numParams",
            "numFields", "isUnsafe",
        ),
        "recs": (
            "name", "levelParams", "type", "numParams", "numIndices",
            "numMotives", "numMinors", "rules", "k", "isUnsafe",
        ),
    }

    for line_no, line in enumerate(document.lines):
        for kind, fields in declaration_fields.items():
            obj = line.get(kind)
            if not isinstance(obj, dict) or not _safe(kind, obj):
                continue
            for field in fields:
                if field in obj:
                    yield Mutation(
                        "field-deletion", f"delete-{kind}-{field}", "differential",
                        line_no, (kind,), field, None,
                        f"mandatory {kind}.{field} handling", delete=True,
                    )

        block = line.get("inductive")
        if not isinstance(block, dict):
            continue
        for group, fields in inductive_fields.items():
            items = block.get(group)
            if not isinstance(items, list):
                continue
            for index, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                path = ("inductive", group, index)
                for field in fields:
                    if field in item:
                        yield Mutation(
                            "field-deletion", f"delete-{group}-{index}-{field}",
                            "differential", line_no, path, field, None,
                            f"mandatory inductive {group}.{field} handling", delete=True,
                        )
                if group != "recs" or not isinstance(item.get("rules"), list):
                    continue
                for rule_index, rule in enumerate(item["rules"]):
                    if not isinstance(rule, dict):
                        continue
                    for field in ("ctor", "nfields", "rhs"):
                        if field in rule:
                            yield Mutation(
                                "field-deletion",
                                f"delete-recs-{index}-rule-{rule_index}-{field}",
                                "differential",
                                line_no,
                                (*path, "rules", rule_index),
                                field,
                                None,
                                f"mandatory recursor rule {field} handling",
                                delete=True,
                            )


def declaration_replay(document: Document) -> Iterable[Mutation]:
    """Duplicate declarations so descendants can mutate a shadowing copy."""
    previous: tuple[int, dict[str, object], str] | None = None
    for line_no, line in enumerate(document.lines):
        kind = next(
            (candidate for candidate in (*DECLARATION_KINDS, "quot", "inductive") if candidate in line),
            None,
        )
        if kind is None:
            continue
        yield Mutation(
            "declaration-replay",
            f"duplicate-{kind}-{line_no + 1}",
            "differential",
            line_no,
            (),
            kind,
            line[kind],
            "duplicate declaration insertion and shadowing",
            line_edits=(LineEdit("insert", line_no + 1, line),),
        )
        if previous is not None:
            prior_line, prior, prior_kind = previous
            yield Mutation(
                "declaration-replay",
                f"replay-{prior_kind}-{prior_line + 1}-before-{kind}-{line_no + 1}",
                "differential",
                line_no,
                (),
                kind,
                line[kind],
                "declaration replay before a later environment insertion",
                line_edits=(LineEdit("insert", line_no, prior),),
            )
        previous = (line_no, line, kind)


def inductive_structure(document: Document) -> Iterable[Mutation]:
    last_name: int | None = None
    last_param: int | None = None
    for line_no, line in enumerate(document.lines):
        prior_name, prior_param = last_name, last_param
        names, params_here = _declared_names(line), _declared_params(line)
        if names:
            last_name = names[-1]
        if params_here:
            last_param = params_here[-1]
        block = line.get("inductive")
        if not isinstance(block, dict):
            continue
        unsafe = any(
            isinstance(item, dict) and item.get("isUnsafe") is True
            for group in ("types", "ctors", "recs")
            for item in (block.get(group) if isinstance(block.get(group), list) else [])
        )
        if unsafe:
            continue
        for group in ("types", "ctors", "recs"):
            items = block.get(group)
            if not isinstance(items, list):
                continue
            for index, item in enumerate(items):
                if not isinstance(item, dict):
                    continue
                path = ("inductive", group, index)
                params = item.get("levelParams")
                if isinstance(params, list) and params:
                    yield Mutation("inductive-structure", f"{group}-{index}-levels-empty", "differential",
                                   line_no, path, "levelParams", [], "inductive universe validation", line_no)
                    if len(params) > 1:
                        yield Mutation("inductive-structure", f"{group}-{index}-level-drop-first",
                                       "differential", line_no, path, "levelParams", params[1:],
                                       "inductive universe validation", line_no)
                    if prior_param is not None and prior_param not in params:
                        yield Mutation("inductive-structure", f"{group}-{index}-level-from-prior",
                                       "differential", line_no, path, "levelParams",
                                       [prior_param, *params[1:]], "inductive universe scope", line_no)
                if prior_name is not None:
                    yield Mutation("inductive-structure", f"{group}-{index}-duplicate-name",
                                   "differential", line_no, path, "name", prior_name,
                                   "inductive environment insertion", line_no)
                all_names = item.get("all")
                if isinstance(all_names, list) and all_names:
                    yield Mutation("inductive-structure", f"{group}-{index}-all-empty", "differential",
                                   line_no, path, "all", [], "inductive dependency metadata", line_no)
                    yield Mutation("inductive-structure", f"{group}-{index}-all-duplicate",
                                   "differential", line_no, path, "all", [all_names[0], *all_names],
                                   "inductive dependency metadata", line_no)
                numeric_fields = {
                    "types": ("numParams", "numIndices", "numNested"),
                    "ctors": ("cidx", "numFields", "numParams"),
                    "recs": ("numIndices", "numMinors", "numMotives", "numParams"),
                }[group]
                for field in numeric_fields:
                    value = item.get(field)
                    if isinstance(value, int) and not isinstance(value, bool):
                        yield Mutation("inductive-structure", f"{group}-{index}-{field}-plus-one",
                                       "differential", line_no, path, field, value + 1,
                                       f"inductive {field} validation", line_no)
                if group == "types":
                    ctors = item.get("ctors")
                    if isinstance(ctors, list) and ctors:
                        yield Mutation("inductive-structure", f"types-{index}-ctors-empty", "differential",
                                       line_no, path, "ctors", [], "constructor membership", line_no)
                        yield Mutation("inductive-structure", f"types-{index}-ctors-duplicate",
                                       "differential", line_no, path, "ctors", [ctors[0], *ctors],
                                       "constructor membership", line_no)
                    for field in ("isRec", "isReflexive"):
                        value = item.get(field)
                        if isinstance(value, bool):
                            yield Mutation("inductive-structure", f"types-{index}-{field}-flip",
                                           "differential", line_no, path, field, not value,
                                           f"inductive {field} validation", line_no)
                elif group == "ctors" and prior_name is not None:
                    yield Mutation("inductive-structure", f"ctors-{index}-wrong-induct", "differential",
                                   line_no, path, "induct", prior_name, "constructor owner validation", line_no)
                elif group == "recs":
                    k = item.get("k")
                    if isinstance(k, bool):
                        yield Mutation("inductive-structure", f"recs-{index}-k-flip", "differential",
                                       line_no, path, "k", not k, "K-recursion validation", line_no)
                    rules = item.get("rules")
                    if not isinstance(rules, list):
                        continue
                    if rules:
                        yield Mutation("inductive-structure", f"recs-{index}-rules-empty", "differential",
                                       line_no, path, "rules", [], "recursor rule validation", line_no)
                        yield Mutation("inductive-structure", f"recs-{index}-rules-duplicate",
                                       "differential", line_no, path, "rules", [rules[0], *rules],
                                       "recursor rule validation", line_no)
                    for rule_index, rule in enumerate(rules):
                        if not isinstance(rule, dict):
                            continue
                        rule_path = (*path, "rules", rule_index)
                        nfields = rule.get("nfields")
                        if isinstance(nfields, int) and not isinstance(nfields, bool):
                            yield Mutation("inductive-structure",
                                           f"recs-{index}-rule-{rule_index}-nfields-plus-one",
                                           "differential", line_no, rule_path, "nfields", nfields + 1,
                                           "recursor rule field count", line_no)
                        if prior_name is not None:
                            yield Mutation("inductive-structure",
                                           f"recs-{index}-rule-{rule_index}-wrong-ctor",
                                           "differential", line_no, rule_path, "ctor", prior_name,
                                           "recursor rule constructor", line_no)
                        rec_type = item.get("type")
                        if isinstance(rec_type, int) and isinstance(rule.get("rhs"), int):
                            yield Mutation("inductive-structure",
                                           f"recs-{index}-rule-{rule_index}-rhs-from-type",
                                           "differential", line_no, rule_path, "rhs", rec_type,
                                           "recursor rule right-hand side", line_no)


def inductive_structure_full(document: Document) -> Iterable[Mutation]:
    """Mutate inductive metadata while retaining every downstream use and theorem."""
    for mutation in inductive_structure(document):
        yield replace(
            mutation,
            campaign="inductive-structure-full",
            label=f"full-{mutation.label}",
            end_line=None,
        )


def declaration_shadow_copy(document: Document) -> Iterable[Mutation]:
    """Insert an independently corrupted copy after the checked declaration."""
    base_mutations = (
        *declaration_structure(document),
        *inductive_structure(document),
        *field_deletion(document),
    )
    for base in base_mutations:
        line = document.lines[base.line]
        kind = next(
            (candidate for candidate in (*DECLARATION_KINDS, "quot", "inductive") if candidate in line),
            None,
        )
        if kind is None or base.line_edits:
            continue
        edits = (
            Edit(base.line, base.path, base.field, base.value, delete=base.delete),
            *base.edits,
        )
        if any(edit.line != base.line for edit in edits):
            continue
        shadow = copy.deepcopy(line)
        try:
            for edit in edits:
                current: object = shadow
                for part in edit.path:
                    current = current[part]  # type: ignore[index]
                if not isinstance(current, dict):
                    raise ValueError("shadow-copy mutation path does not name an object")
                if edit.delete:
                    del current[edit.field]
                else:
                    current[edit.field] = edit.value
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        yield Mutation(
            "declaration-shadow-copy",
            f"shadow-{base.label}",
            "differential",
            base.line,
            (),
            kind,
            line[kind],
            f"shadow-copy composition: {base.target}",
            line_edits=(LineEdit("insert", base.line + 1, shadow),),
        )


BOUNDARY_FIELDS = {
    "bvar",
    "idx",
    "cidx",
    "nfields",
    "numFields",
    "numParams",
    "numIndices",
    "numNested",
    "numMinors",
    "numMotives",
}


def metadata_boundaries(document: Document) -> Iterable[Mutation]:
    sentinels = (0, 1, 32766, 32767, 32768, 2**32 - 1, 2**63 - 1, 2**64 - 1)
    for line_no, line in enumerate(document.lines):
        for path, obj in walk_objects(line):
            for field in sorted(BOUNDARY_FIELDS.intersection(obj)):
                current = obj[field]
                if not isinstance(current, int) or isinstance(current, bool):
                    continue
                values = {*sentinels}
                if current > 0:
                    values.add(current - 1)
                values.add(current + 1)
                for value in sorted(values):
                    if value != current:
                        yield Mutation(
                            "metadata-boundaries", f"{field}-to-{value}", "differential",
                            line_no, path, field, value,
                            f"machine-boundary handling for {field}",
                        )


def rule_crosswire(document: Document) -> Iterable[Mutation]:
    for line_no, line in enumerate(document.lines):
        block = line.get("inductive")
        if not isinstance(block, dict):
            continue
        recs = block.get("recs")
        if not isinstance(recs, list):
            continue
        for rec_index, rec in enumerate(recs):
            if not isinstance(rec, dict):
                continue
            rules = rec.get("rules")
            if not isinstance(rules, list) or len(rules) < 2:
                continue
            for index in range(len(rules) - 1):
                left, right = rules[index], rules[index + 1]
                if not isinstance(left, dict) or not isinstance(right, dict):
                    continue
                for field in ("rhs", "ctor", "nfields"):
                    if field in left and field in right and left[field] != right[field]:
                        yield Mutation(
                            "recursor-crosswire", f"swap-adjacent-{field}-{index}",
                            "differential", line_no,
                            ("inductive", "recs", rec_index, "rules", index),
                            field, right[field], f"recursor rule {field} validation",
                        )


CAMPAIGNS: dict[str, Campaign] = {
    "closedness": Campaign(
        "closedness", "guaranteed-reject",
        "Inject a previously declared bound-variable node into closed declarations.",
        ("looseBVarsBounded", "checkConstantVal", "inductive component guards"),
        closedness,
    ),
    "level-params": Campaign(
        "level-params", "guaranteed-reject",
        "Duplicate a declaration or inductive universe parameter.",
        ("nameNodup", "allLevelParamsDefined"), duplicate_levels,
    ),
    "metadata-boundaries": Campaign(
        "metadata-boundaries", "differential",
        "Push structural counts and indices across machine-word and saturation boundaries.",
        ("range caches", "recursor metadata", "projection indices"), metadata_boundaries,
    ),
    "recursor-crosswire": Campaign(
        "recursor-crosswire", "differential",
        "Cross-wire adjacent recursor-rule fields while leaving the block shape intact.",
        ("recursor generation", "rule comparison", "rule installation"), rule_crosswire,
    ),
    "recursor-rule-permutations": Campaign(
        "recursor-rule-permutations", "differential",
        "Atomically permute correlated fields between adjacent recursor rules.",
        ("recursor rule association", "constructor matching", "rule installation"),
        recursor_rule_permutations,
    ),
    "inductive-block-crosswire": Campaign(
        "inductive-block-crosswire", "differential",
        "Transplant shape-compatible types and recursor semantics from earlier blocks.",
        ("cross-block validation", "recursor RHS trust", "inductive type trust"),
        inductive_block_crosswire,
    ),
    "intern-table-shadowing": Campaign(
        "intern-table-shadowing", "differential",
        "Insert a scope-compatible duplicate expression ID before a declaration consumes it.",
        ("intern-table uniqueness", "parser/kernel boundary", "expression identity"),
        intern_table_shadowing,
    ),
    "field-deletion": Campaign(
        "field-deletion", "differential",
        "Delete mandatory declaration, inductive and recursor-rule fields.",
        ("parser/kernel boundary", "defaulted metadata", "recursor validation"),
        field_deletion,
    ),
    "declaration-replay": Campaign(
        "declaration-replay", "differential",
        "Duplicate and replay declarations for independent shadow-copy mutation.",
        ("environment replay", "duplicate names", "cache invalidation", "shadowing"),
        declaration_replay,
    ),
    "declaration-shadow-copy": Campaign(
        "declaration-shadow-copy", "differential",
        "Insert a corrupted duplicate while retaining the original checked declaration.",
        ("environment shadowing", "cache invalidation", "duplicate validation"),
        declaration_shadow_copy,
    ),
    "expression-structure": Campaign(
        "expression-structure", "differential",
        "Cross-wire expression components and binder references, truncating at the next declaration.",
        ("infer", "defEq", "binder opening", "projection checking"), expression_structure,
    ),
    "expression-structure-full": Campaign(
        "expression-structure-full", "differential",
        "Cross-wire expression components while preserving every downstream declaration.",
        ("end-to-end theorem validation", "infer", "defEq", "binder opening"),
        expression_structure_full,
    ),
    "declaration-structure": Campaign(
        "declaration-structure", "differential",
        "Mutate declaration universes, names, dependencies, types and values.",
        ("checkConstantVal", "environment insertion", "dependency metadata"),
        declaration_structure,
    ),
    "declaration-structure-full": Campaign(
        "declaration-structure-full", "differential",
        "Mutate declaration structure while preserving dependent declarations and final theorems.",
        ("end-to-end declaration validation", "environment insertion", "dependency metadata"),
        declaration_structure_full,
    ),
    "binder-context-pairs": Campaign(
        "binder-context-pairs", "differential",
        "Force declarations to compare structurally related Pi and lambda closures.",
        ("closure context identity", "type cache", "Pi/lambda conversion"),
        binder_context_pairs,
    ),
    "const-universe-crosswire": Campaign(
        "const-universe-crosswire", "differential",
        "Cross-wire and swap level instantiations of repeated constant occurrences.",
        ("level substitution", "closure environments", "constant caches"),
        const_universe_crosswire,
    ),
    "typed-neighborhood-crosswire": Campaign(
        "typed-neighborhood-crosswire", "differential",
        "Cross-wire references only between matching syntactic type neighborhoods.",
        ("context-sensitive infer", "defEq caches", "binder opening", "projection reduction"),
        typed_neighborhood_crosswire,
    ),
    "inductive-structure": Campaign(
        "inductive-structure", "differential",
        "Mutate inductive metadata, constructor ownership and recursor rules.",
        ("inductive validation", "recursor generation", "K-recursion guards"),
        inductive_structure,
    ),
    "inductive-structure-full": Campaign(
        "inductive-structure-full", "differential",
        "Mutate inductive metadata while preserving all dependent declarations and theorems.",
        ("end-to-end recursor use", "inductive validation", "K-recursion guards"),
        inductive_structure_full,
    ),
}


def selected(names: list[str] | None) -> tuple[Campaign, ...]:
    if not names:
        return tuple(CAMPAIGNS.values())
    missing = set(names).difference(CAMPAIGNS)
    if missing:
        raise ValueError(f"unknown campaigns: {', '.join(sorted(missing))}")
    return tuple(CAMPAIGNS[name] for name in names)

