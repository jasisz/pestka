#!/usr/bin/env python3
"""Delta-debug an NDJSON input while preserving a hang and a panic."""

from __future__ import annotations

import argparse
import shlex
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Outcome:
    code: int
    timed_out: bool
    output: str


def command(text: str) -> tuple[str, ...]:
    argv = tuple(shlex.split(text))
    if not argv or not any("{file}" in arg for arg in argv):
        raise argparse.ArgumentTypeError("command must contain {file}")
    return argv


def run(argv: tuple[str, ...], path: Path, timeout: float) -> Outcome:
    actual = [arg.replace("{file}", str(path)) for arg in argv]
    try:
        result = subprocess.run(
            actual,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            check=False,
        )
        return Outcome(result.returncode, False, result.stdout)
    except subprocess.TimeoutExpired as error:
        output = error.stdout or ""
        if isinstance(output, bytes):
            output = output.decode(errors="replace")
        return Outcome(124, True, output)
    except OSError as error:
        return Outcome(127, False, str(error))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--hang", type=command, required=True)
    parser.add_argument("--panic", type=command, required=True)
    parser.add_argument("--hang-timeout", type=float, default=0.5)
    parser.add_argument("--panic-timeout", type=float, default=2.0)
    parser.add_argument("--panic-code", type=int, default=3)
    parser.add_argument("--panic-text", required=True)
    parser.add_argument(
        "--keep",
        action="append",
        default=[],
        help="line substring that the reducer may not delete; repeatable",
    )
    parser.add_argument(
        "--truncate-after",
        help="first line containing this substring becomes the last input line",
    )
    parser.add_argument(
        "--truncate-only",
        action="store_true",
        help="stop after a successful --truncate-after operation",
    )
    args = parser.parse_args()

    lines = args.input.read_text().splitlines()
    tests = 0
    with tempfile.TemporaryDirectory(prefix="pestka-minimize-") as directory:
        candidate = Path(directory) / "candidate.ndjson"

        def interesting(selected: list[str]) -> bool:
            nonlocal tests
            tests += 1
            candidate.write_text("\n".join(selected) + "\n")
            hung = run(args.hang, candidate, args.hang_timeout)
            if not hung.timed_out:
                return False
            panicked = run(args.panic, candidate, args.panic_timeout)
            return panicked.code == args.panic_code and args.panic_text in panicked.output

        if not interesting(lines):
            raise SystemExit("input does not satisfy both predicates")

        if args.truncate_after:
            end = next(
                (index + 1 for index, line in enumerate(lines) if args.truncate_after in line),
                None,
            )
            if end is None:
                raise SystemExit("--truncate-after text not found")
            shortened = lines[:end]
            if interesting(shortened):
                lines = shortened
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text("\n".join(lines) + "\n")
                print(f"truncate: {len(lines)} lines")
                if args.truncate_only:
                    return 0

        groups = 2
        while True:
            removable = [
                index
                for index, line in enumerate(lines)
                if not any(marker in line for marker in args.keep)
            ]
            if not removable:
                break
            chunk_size = max(1, (len(removable) + groups - 1) // groups)
            reduced = False
            for start in range(0, len(removable), chunk_size):
                removed = set(removable[start : start + chunk_size])
                trial = [line for index, line in enumerate(lines) if index not in removed]
                if interesting(trial):
                    lines = trial
                    # A successful deletion can expose much larger removable
                    # regions.  Restart coarse instead of crawling one small
                    # chunk at a time after a highly partitioned pass.
                    groups = 2
                    args.output.parent.mkdir(parents=True, exist_ok=True)
                    args.output.write_text("\n".join(lines) + "\n")
                    print(f"reduce: {len(lines)} lines after {tests} tests", flush=True)
                    reduced = True
                    break
            if reduced:
                continue
            if groups >= len(removable):
                break
            groups = min(len(removable), groups * 2)

    print(f"minimal by line deletion: {len(lines)} lines after {tests} tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
