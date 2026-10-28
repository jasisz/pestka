from __future__ import annotations

import argparse
import glob
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def find_tool(name: str, explicit: str | None = None) -> str:
    if explicit:
        return explicit
    found = shutil.which(name)
    if found:
        return found
    try:
        sysroot = Path(
            subprocess.check_output(
                ["rustc", "--print", "sysroot"], text=True, stderr=subprocess.DEVNULL
            ).strip()
        )
    except (OSError, subprocess.CalledProcessError):
        sysroot = Path("/")
    bundled = sorted((sysroot / "lib" / "rustlib").glob(f"*/bin/{name}"))
    if bundled:
        return str(bundled[0])
    raise FileNotFoundError(
        f"cannot find {name}; install rustup component llvm-tools-preview or pass --{name}"
    )


def display_path(
    filename: str, source_root: Path | None, only_source_root: bool = False
) -> str | None:
    path = Path(filename)
    if source_root is not None:
        try:
            return str(path.resolve().relative_to(source_root.resolve()))
        except ValueError:
            if only_source_root:
                return None
    return path.as_posix()


def extract_features(
    report: dict[str, object],
    source_root: Path | None = None,
    only_source_root: bool = False,
) -> set[str]:
    features: set[str] = set()
    data = report.get("data")
    if not isinstance(data, list):
        return features
    for unit in data:
        if not isinstance(unit, dict):
            continue
        files = unit.get("files")
        if not isinstance(files, list):
            continue
        for file in files:
            if not isinstance(file, dict) or not isinstance(file.get("filename"), str):
                continue
            filename = display_path(file["filename"], source_root, only_source_root)
            if filename is None:
                continue
            segments = file.get("segments")
            if isinstance(segments, list):
                for segment in segments:
                    if (
                        isinstance(segment, list)
                        and len(segment) >= 5
                        and isinstance(segment[0], int)
                        and isinstance(segment[1], int)
                        and isinstance(segment[2], int)
                        and segment[2] > 0
                        and segment[3] is True
                        and segment[4] is True
                    ):
                        features.add(f"region:{filename}:{segment[0]}:{segment[1]}")
            branches = file.get("branches")
            if isinstance(branches, list):
                for branch in branches:
                    if not isinstance(branch, list) or len(branch) < 6:
                        continue
                    location = branch[:4]
                    if not all(isinstance(value, int) for value in location):
                        continue
                    prefix = ":".join(str(value) for value in location)
                    if isinstance(branch[4], int) and branch[4] > 0:
                        features.add(f"branch-true:{filename}:{prefix}")
                    if isinstance(branch[5], int) and branch[5] > 0:
                        features.add(f"branch-false:{filename}:{prefix}")
    return features


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        prog="pestycyd-llvm-feedback",
        description="Convert Rust/LLVM profraw coverage into Pestycyd line features",
    )
    result.add_argument("binary", type=Path)
    result.add_argument("profiles", help="profraw path or glob (expanded by this command)")
    result.add_argument("--source-root", type=Path)
    result.add_argument(
        "--only-source-root",
        action="store_true",
        help="discard coverage whose source path is outside --source-root",
    )
    result.add_argument("--llvm-profdata")
    result.add_argument("--llvm-cov")
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        profiles = sorted(Path(path) for path in glob.glob(args.profiles))
        if not profiles:
            raise FileNotFoundError(f"no coverage profiles match {args.profiles}")
        profdata = find_tool("llvm-profdata", args.llvm_profdata)
        cov = find_tool("llvm-cov", args.llvm_cov)
        with tempfile.TemporaryDirectory(prefix="pestycyd-llvm-") as raw:
            merged = Path(raw) / "merged.profdata"
            subprocess.run(
                [profdata, "merge", "-sparse", *map(str, profiles), "-o", str(merged)],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )
            export_command = [
                cov,
                "export",
                str(args.binary),
                f"-instr-profile={merged}",
                "--skip-functions",
            ]
            if args.only_source_root and args.source_root is not None:
                sources = sorted(
                    str(path.resolve()) for path in args.source_root.rglob("*.rs")
                )
                if sources:
                    export_command.extend(("--sources", *sources))
            exported = subprocess.run(
                export_command,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            ).stdout
        report = json.loads(exported)
        if not isinstance(report, dict):
            raise ValueError("llvm-cov export did not return a JSON object")
        for feature in sorted(
            extract_features(report, args.source_root, args.only_source_root)
        ):
            print(feature)
        return 0
    except (OSError, ValueError, json.JSONDecodeError, subprocess.CalledProcessError) as failure:
        if isinstance(failure, subprocess.CalledProcessError) and failure.stderr:
            detail = failure.stderr.decode(errors="replace").strip()
            print(f"pestycyd-llvm-feedback: {failure}: {detail}", file=sys.stderr)
        else:
            print(f"pestycyd-llvm-feedback: {failure}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
