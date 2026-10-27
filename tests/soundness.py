#!/usr/bin/env python3
"""Cross-check kernels and generate small, certainly ill-typed mutations.

Kernel commands are argv templates.  ``{file}`` is replaced with the input
path, so no shell is involved.  Example:

    tests/soundness.py corpus arena-tests \
      --kernel 'pestka=.build/target/release/main {file} 1 old' \
      --kernel 'nanoda=nanoda {file}'

The mutation mode starts from exports accepted by every selected kernel.  It
then replaces a checked declaration type or value by a loose bound variable,
or duplicates a universe parameter.  Each mutation is invalid independently
of reduction and therefore needs no heuristic oracle.  An accepted mutant is
copied to the findings directory.
"""

from __future__ import annotations

import argparse
import copy
import datetime
import json
import shlex
import subprocess
import fnmatch
import sys
import tempfile
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class Kernel:
    name: str
    argv: tuple[str, ...]
    require_verdict: bool = False

    def run(self, path: Path, timeout: float) -> "RunResult":
        argv = [part.replace("{file}", str(path)) for part in self.argv]
        started = time.perf_counter()
        try:
            completed = subprocess.run(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=timeout,
                check=False,
            )
            actual_code = completed.returncode
            output = completed.stdout
            verdict = verdict_code(output)
            code = actual_code
            if self.require_verdict and (verdict is None or verdict != actual_code):
                code = 127
        except subprocess.TimeoutExpired as error:
            actual_code = None
            code = 124
            output = error.stdout or ""
            if isinstance(output, bytes):
                output = output.decode(errors="replace")
        except OSError as error:
            actual_code = None
            code = 127
            output = str(error)
        return RunResult(code, time.perf_counter() - started, actual_code, output[-4096:])


@dataclass(frozen=True)
class RunResult:
    code: int
    seconds: float
    actual_code: int | None = None
    output: str = ""

    def json(self) -> dict[str, object]:
        result: dict[str, object] = {
            "code": self.code,
            "status": status(self.code),
            "seconds": round(self.seconds, 6),
        }
        if self.actual_code is not None and self.actual_code != self.code:
            result["actual_code"] = self.actual_code
        if self.output:
            result["output"] = self.output
        return result


@dataclass(frozen=True)
class Mutation:
    line: int
    label: str
    object_path: tuple[object, ...]
    field: str
    value: object


def parse_kernel(text: str) -> Kernel:
    if "=" not in text:
        raise argparse.ArgumentTypeError("kernel must be NAME=COMMAND")
    name, command = text.split("=", 1)
    argv = tuple(shlex.split(command))
    if not name or not argv or not any("{file}" in x for x in argv):
        raise argparse.ArgumentTypeError("kernel needs a name and a {file} argument")
    return Kernel(name, argv)


def default_kernels() -> list[Kernel]:
    binary = Path(__file__).resolve().parents[1] / ".build/target/release/main"
    return [
        Kernel("pestka-old", (str(binary), "{file}", "1", "old"), True),
        Kernel("pestka-next", (str(binary), "{file}", "1", "next"), True),
    ]


def kernels_from(args: argparse.Namespace) -> list[Kernel]:
    kernels = args.kernel or default_kernels()
    names = [k.name for k in kernels]
    if len(names) != len(set(names)):
        raise SystemExit("kernel names must be unique")
    required = set(args.require_verdict)
    unknown = required.difference(names)
    if unknown:
        raise SystemExit(f"--require-verdict names unknown kernels: {', '.join(sorted(unknown))}")
    kernels = [replace(k, require_verdict=True) if k.name in required else k for k in kernels]
    return kernels


def verdict_code(output: str) -> int | None:
    for line in reversed(output.splitlines()):
        stripped = line.strip()
        if stripped == "accepted":
            return 0
        if stripped.startswith("rejected:"):
            return 1
        if stripped.startswith("declined:"):
            return 2
    return None


def status(code: int) -> str:
    return {0: "accept", 1: "reject", 2: "decline", 124: "timeout", 127: "error"}.get(
        code, f"exit-{code}"
    )


def ndjson_files(
    paths: Iterable[str], excludes: Iterable[str] = (), max_bytes: int | None = None
) -> list[Path]:
    out: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_dir():
            out.extend(sorted(path.rglob("*.ndjson")))
        elif path.suffix == ".ndjson":
            out.append(path)
    unique = sorted(set(out))
    return [
        path
        for path in unique
        if not any(fnmatch.fnmatch(str(path), pattern) for pattern in excludes)
        and (max_bytes is None or path.stat().st_size <= max_bytes)
    ]


def expected_for(path: Path) -> int | None:
    parts = set(path.parts)
    if "good" in parts:
        return 0
    if "bad" in parts:
        return 1
    return None


def report_header(mode: str, kernels: list[Kernel]) -> dict[str, object]:
    return {
        "schema": "pestka-soundness-1",
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "mode": mode,
        "kernels": [
            {"name": k.name, "argv": list(k.argv), "require_verdict": k.require_verdict}
            for k in kernels
        ],
        "runs": [],
    }


def public_names(paths: Iterable[str], kernels: list[Kernel]) -> list[tuple[str, str]]:
    """This machine's paths and what a report shows instead, longest first: a
    program by its path in the repository or by its name, an input by its path
    from the directory holding the one given, the home directory as ~."""
    root = Path(__file__).resolve().parents[1]
    names: dict[str, str] = {}
    for kernel in kernels:
        for part in kernel.argv:
            program = Path(part)
            if program.is_absolute():
                real = program.resolve()
                shown = str(real.relative_to(root)) if real.is_relative_to(root) else real.name
                names[str(program)] = shown
                names[str(real)] = shown
    for raw in paths:
        for given in (Path(raw).absolute(), Path(raw).resolve()):
            base = given if given.is_dir() else given.parent
            if base.parent != base.parent.parent:
                names[str(base.parent) + "/"] = ""
    for local in (root, Path.cwd(), Path(tempfile.gettempdir()), Path(tempfile.gettempdir()).resolve()):
        names[str(local) + "/"] = ""
    names[str(Path.home())] = "~"
    return sorted(names.items(), key=lambda item: -len(item[0]))


def public(value: object, names: list[tuple[str, str]]) -> object:
    """value with every local path in its strings replaced as public_names says."""
    if isinstance(value, str):
        for local, shown in names:
            value = value.replace(local, shown)
        return value
    if isinstance(value, list):
        return [public(item, names) for item in value]
    if isinstance(value, dict):
        return {key: public(item, names) for key, item in value.items()}
    return value


def write_report(path: Path | None, report: dict[str, object], names: list[tuple[str, str]]) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(public(report, names), indent=2, ensure_ascii=False) + "\n")


def corpus(args: argparse.Namespace) -> int:
    kernels = kernels_from(args)
    files = ndjson_files(args.paths, args.exclude, args.max_bytes)
    failures = 0
    checked = 0
    report = report_header("corpus", kernels)
    runs = report["runs"]
    assert isinstance(runs, list)
    for path in files:
        expected = expected_for(path)
        results = {k.name: k.run(path, args.timeout) for k in kernels}
        codes = {name: result.code for name, result in results.items()}
        runs.append(
            {
                "file": str(path),
                "expected": None if expected is None else status(expected),
                "results": {name: result.json() for name, result in results.items()},
            }
        )
        mismatch = len(set(codes.values())) > 1
        wrong = expected is not None and any(code != expected for code in codes.values())
        if mismatch or wrong:
            failures += 1
            want = "unknown" if expected is None else status(expected)
            got = ", ".join(f"{name}={status(code)}" for name, code in codes.items())
            print(f"{path}: expected={want}; {got}")
        checked += 1
    report["summary"] = {"files": checked, "kernels": len(kernels), "findings": failures}
    write_report(args.report, report, public_names(args.paths, kernels))
    print(f"checked {checked} files with {len(kernels)} kernels; findings {failures}")
    return 1 if failures else 0


def safe_top(kind: str, obj: dict[str, object]) -> bool:
    if kind == "def":
        return obj.get("safety") == "safe"
    if kind in ("axiom", "opaque"):
        return obj.get("isUnsafe") is False
    return kind == "thm"


def mutations(lines: list[dict[str, object]]) -> list[Mutation]:
    out: list[Mutation] = []
    for line_no, line in enumerate(lines):
        prior_bvar = next(
            (
                earlier.get("ie")
                for earlier in lines[:line_no]
                if isinstance(earlier.get("ie"), int) and isinstance(earlier.get("bvar"), int)
            ),
            None,
        )
        for kind in ("axiom", "def", "thm", "opaque"):
            obj = line.get(kind)
            if not isinstance(obj, dict) or not safe_top(kind, obj):
                continue
            if prior_bvar is not None:
                out.append(Mutation(line_no, f"{kind}-type-loose", (kind,), "type", prior_bvar))
                if kind in ("def", "thm", "opaque"):
                    out.append(Mutation(line_no, f"{kind}-value-loose", (kind,), "value", prior_bvar))
            params = obj.get("levelParams")
            if isinstance(params, list) and params:
                out.append(
                    Mutation(line_no, f"{kind}-duplicate-level", (kind,), "levelParams", [params[0], *params])
                )

        block = line.get("inductive")
        if not isinstance(block, dict):
            continue
        unsafe = any(
            isinstance(item, dict) and item.get("isUnsafe") is True
            for group in ("types", "ctors", "recs")
            for item in block.get(group, [])
            if isinstance(block.get(group), list)
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
                if prior_bvar is not None:
                    out.append(
                        Mutation(
                            line_no,
                            f"inductive-{group}-{index}-type-loose",
                            ("inductive", group, index),
                            "type",
                            prior_bvar,
                        )
                    )
                params = item.get("levelParams")
                if isinstance(params, list) and params:
                    out.append(
                        Mutation(
                            line_no,
                            f"inductive-{group}-{index}-duplicate-level",
                            ("inductive", group, index),
                            "levelParams",
                            [params[0], *params],
                        )
                    )
    return out


def object_at(line: dict[str, object], path: tuple[object, ...]) -> dict[str, object]:
    current: object = line
    for part in path:
        current = current[part]  # type: ignore[index]
    assert isinstance(current, dict)
    return current


def render_mutant(lines: list[dict[str, object]], mutation: Mutation) -> str:
    changed = copy.deepcopy(lines)
    target = object_at(changed[mutation.line], mutation.object_path)
    target[mutation.field] = mutation.value

    rendered: list[str] = []
    for line in changed:
        rendered.append(json.dumps(line, separators=(",", ":"), ensure_ascii=False))
    return "\n".join(rendered) + "\n"


def mutate(args: argparse.Namespace) -> int:
    kernels = kernels_from(args)
    seeds = ndjson_files(args.paths, args.exclude, args.max_bytes)
    findings = 0
    tried = 0
    report = report_header("mutate", kernels)
    runs = report["runs"]
    assert isinstance(runs, list)
    with tempfile.TemporaryDirectory(prefix="pestka-soundness-") as tmp:
        temp = Path(tmp) / "mutant.ndjson"
        for seed in seeds:
            baseline = {k.name: k.run(seed, args.timeout) for k in kernels}
            active = [k for k in kernels if baseline[k.name].code == 0]
            if len(active) != len(kernels):
                got = ", ".join(
                    f"{name}={status(result.code)}" for name, result in baseline.items()
                )
                print(f"SKIP {seed}: seed is not accepted by every kernel; {got}")
                runs.append(
                    {
                        "seed": str(seed),
                        "kind": "baseline",
                        "skipped": True,
                        "results": {name: result.json() for name, result in baseline.items()},
                    }
                )
                continue
            try:
                lines = [json.loads(line) for line in seed.read_text().splitlines() if line]
            except (OSError, json.JSONDecodeError) as error:
                print(f"SKIP {seed}: {error}")
                continue
            candidates = list(enumerate(mutations(lines)))
            if args.start:
                candidates = candidates[args.start :]
            if args.limit is not None:
                candidates = candidates[: args.limit]
            for number, mutation in candidates:
                temp.write_text(render_mutant(lines, mutation))
                results = {k.name: k.run(temp, args.timeout) for k in active}
                codes = {name: result.code for name, result in results.items()}
                accepted = [name for name, code in codes.items() if code == 0]
                row: dict[str, object] = {
                    "seed": str(seed),
                    "kind": "mutation",
                    "number": number,
                    "label": mutation.label,
                    "source_line": mutation.line + 1,
                    "results": {name: result.json() for name, result in results.items()},
                }
                runs.append(row)
                if accepted:
                    findings += 1
                    args.findings.mkdir(parents=True, exist_ok=True)
                    saved = args.findings / f"{seed.stem}-{number:04d}-{mutation.label}.ndjson"
                    saved.write_text(temp.read_text())
                    row["saved"] = str(saved)
                    got = ", ".join(f"{name}={status(code)}" for name, code in codes.items())
                    print(f"ACCEPTED INVALID {saved}: {got}")
                elif len(set(codes.values())) > 1:
                    got = ", ".join(f"{name}={status(code)}" for name, code in codes.items())
                    print(f"DIFFER {seed} mutation={number} {mutation.label}: {got}")
                    if args.keep_differences:
                        args.findings.mkdir(parents=True, exist_ok=True)
                        saved = args.findings / f"{seed.stem}-{number:04d}-{mutation.label}-diff.ndjson"
                        saved.write_text(temp.read_text())
                        row["saved"] = str(saved)
                tried += 1
    report["summary"] = {"seeds": len(seeds), "mutations": tried, "accepted": findings}
    write_report(args.report, report, public_names(args.paths, kernels))
    print(f"ran {tried} invalid mutations from {len(seeds)} seeds; accepted {findings}")
    return 1 if findings else 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="mode", required=True)
    for name, help_text, function in (
        ("corpus", "compare kernels on good/ and bad/ corpora", corpus),
        ("mutate", "inject guaranteed-invalid declarations into good exports", mutate),
    ):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("paths", nargs="+", help="NDJSON files or directories")
        command.add_argument(
            "--kernel",
            action="append",
            type=parse_kernel,
            metavar="NAME=COMMAND",
            help="argv template containing {file}; repeat for each kernel",
        )
        command.add_argument(
            "--require-verdict",
            action="append",
            default=[],
            metavar="NAME",
            help="treat exit without accepted/rejected/declined output as a runner error",
        )
        command.add_argument("--timeout", type=float, default=20.0)
        command.add_argument(
            "--exclude",
            action="append",
            default=[],
            metavar="GLOB",
            help="skip paths matching this glob; repeatable",
        )
        command.add_argument(
            "--max-bytes", type=int, help="skip input files larger than this"
        )
        command.add_argument("--report", type=Path, help="write every result and timing as JSON")
        command.set_defaults(function=function)
    mutation = sub.choices["mutate"]
    mutation.add_argument("--start", type=int, default=0, help="skip this many mutations per seed")
    mutation.add_argument("--limit", type=int, help="maximum mutations per seed")
    mutation.add_argument("--findings", type=Path, default=Path("tests/soundness-findings"))
    mutation.add_argument(
        "--keep-differences",
        action="store_true",
        help="also retain mutants on which kernels reject, decline, or time out differently",
    )
    return p


def main() -> int:
    args = parser().parse_args()
    return args.function(args)


if __name__ == "__main__":
    sys.exit(main())
