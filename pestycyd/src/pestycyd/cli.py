from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import random
import sys
import tempfile
import tomllib
from collections import deque
from pathlib import Path

from .campaigns import CAMPAIGNS, selected as selected_campaigns
from .config import Config, KernelSpec, load_config
from .generators import con_k_params, deep_binder
from .minimize import ddmin
from .ndjson import Document, Mutation, files
from .outcomes import Outcome
from .runner import run_matrix, run_probe
from .store import FindingStore, atomic_text


def matrix_json(results: dict[str, Outcome]) -> dict[str, object]:
    return {name: outcome.json() for name, outcome in results.items()}


def statuses(results: dict[str, Outcome]) -> str:
    return ", ".join(f"{name}={result.status}" for name, result in results.items())


def is_interesting(
    mutation: Mutation,
    results: dict[str, Outcome],
    include_robustness: bool = True,
) -> tuple[bool, str]:
    values = [outcome.status for outcome in results.values()]
    severe = any(value in {"crash", "timeout", "error", "runner-error"} for value in values)
    if mutation.oracle == "guaranteed-reject":
        accepted = [name for name, outcome in results.items() if outcome.status == "accept"]
        if accepted:
            return True, "accepted guaranteed-invalid input"
        return severe and include_robustness, "kernel robustness failure"
    if mutation.oracle == "guaranteed-accept":
        failures = [
            name
            for name, outcome in results.items()
            if outcome.status != "accept"
            and (include_robustness or outcome.status in {"reject", "decline"})
        ]
        return bool(failures), "failed validity-preserving input"
    semantic = [value for value in values if value in {"accept", "reject", "decline"}]
    different = len(set(semantic)) > 1
    robustness = severe and include_robustness
    return robustness or different, "kernel robustness failure" if robustness else "differential outcome"


def feedback_features(
    results: dict[str, Outcome], *, include_behavior: bool = False,
) -> set[str]:
    features = {
        f"{name}:{feature}"
        for name, outcome in results.items()
        for feature in outcome.feedback
    }
    if include_behavior:
        features.update(
            f"{name}:behavior:{outcome.status}:{outcome.fingerprint}"
            for name, outcome in results.items()
        )
    return features


def seed_is_eligible(policy: str, results: dict[str, Outcome]) -> bool:
    values = [outcome.status for outcome in results.values()]
    if policy == "accepted":
        return all(value == "accept" for value in values)
    severe = {"timeout", "crash", "error", "runner-error"}
    if policy == "consensus":
        return len(set(values)) == 1 and values[0] in {"accept", "reject"}
    if policy == "any":
        return not severe.intersection(values)
    if policy == "all":
        return True
    raise ValueError(f"unknown seed policy: {policy}")


def doctor(config: Config, kernels: tuple[KernelSpec, ...], _args: argparse.Namespace) -> int:
    failures = 0
    for kernel in kernels:
        ok, message = run_probe(kernel)
        print(f"{'ok' if ok else 'FAIL'} {kernel.name}: {message}")
        failures += not ok
    return 1 if failures else 0


def list_campaigns(_config: Config, _kernels: tuple[KernelSpec, ...], _args: argparse.Namespace) -> int:
    for campaign in CAMPAIGNS.values():
        print(f"{campaign.name} [{campaign.oracle}]\n  {campaign.description}")
        print(f"  targets: {', '.join(campaign.targets)}")
    return 0


def generate_deep_binder(
    _config: Config | None, _kernels: tuple[KernelSpec, ...], args: argparse.Namespace
) -> int:
    atomic_text(args.output, deep_binder(args.depth))
    print(f"generated deep-binder depth {args.depth}: {args.output}")
    return 0


def generate_con_k(
    _config: Config | None, _kernels: tuple[KernelSpec, ...], args: argparse.Namespace
) -> int:
    atomic_text(args.output, con_k_params(args.count))
    print(f"generated con-k-params width {args.count}: {args.output}")
    return 0


def matrix_command(config: Config, kernels: tuple[KernelSpec, ...], args: argparse.Namespace) -> int:
    paths = files(args.paths)
    rows: list[dict[str, object]] = []
    differences = 0
    for path in paths:
        results = run_matrix(kernels, path, args.workers)
        row = {"file": str(path), "results": matrix_json(results)}
        rows.append(row)
        values = {result.status for result in results.values()}
        if len(values) > 1 or any(
            value in {"crash", "timeout", "error", "runner-error"} for value in values
        ):
            differences += 1
            print(f"DIFFER {path}: {statuses(results)}")
        elif args.verbose:
            print(f"{path}: {statuses(results)}")
    report = {"schema": "pestycyd-matrix-1", "kernels": [k.public() for k in kernels], "runs": rows}
    if args.report:
        atomic_text(args.report, json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(f"matrix: {len(paths)} inputs, {len(kernels)} kernels, {differences} interesting")
    return 1 if differences else 0


def hunt(config: Config, kernels: tuple[KernelSpec, ...], args: argparse.Namespace) -> int:
    paths = files(args.paths)
    campaigns = selected_campaigns(args.campaign)
    rng = random.Random(args.seed)
    store = FindingStore(args.state or config.state)
    frontier: list[
        tuple[
            Path,
            Document,
            Mutation,
            int,
            tuple[dict[str, object], ...],
            frozenset[int],
        ]
    ] = []
    frontier_buckets: list[
        list[
            tuple[
                Path,
                Document,
                Mutation,
                int,
                tuple[dict[str, object], ...],
                frozenset[int],
            ]
        ]
    ] = []
    seen_feedback: set[str] = set()
    seen_inputs: set[str] = set()

    def allowed(mutation: Mutation, protected: frozenset[int]) -> bool:
        return (
            mutation.line not in protected
            and all(edit.line not in protected for edit in mutation.edits)
            and all(
                edit.kind == "insert" or edit.line not in protected
                for edit in mutation.line_edits
            )
        )

    for path in paths:
        try:
            document = Document.load(path)
        except (OSError, ValueError, json.JSONDecodeError) as failure:
            print(f"SKIP {path}: {failure}")
            continue
        seen_inputs.add(hashlib.sha256(document.render().encode()).hexdigest())
        baseline = run_matrix(kernels, path, args.workers)
        if not seed_is_eligible(args.seed_policy, baseline):
            print(
                f"SKIP {path}: seed does not satisfy {args.seed_policy} policy; "
                f"{statuses(baseline)}"
            )
            continue
        seen_feedback.update(
            feedback_features(
                baseline, include_behavior=getattr(args, "behavior_feedback", False)
            )
        )
        protected = (
            document.final_goal_lines()
            if getattr(args, "protect_final_goal", False)
            else frozenset()
        )
        mutations = [
            mutation
            for campaign in campaigns
            for mutation in campaign.generate(document)
            if allowed(mutation, protected)
        ]
        bucket = [(path, document, mutation, 1, (), protected) for mutation in mutations]
        rng.shuffle(bucket)
        frontier_buckets.append(bucket)
    while any(frontier_buckets):
        for bucket in frontier_buckets:
            if bucket:
                frontier.append(bucket.pop())
    if not frontier:
        print("no accepted seed has mutations for the selected campaigns")
        return 2
    queue = deque(frontier)
    findings = 0
    novel = 0
    corpus = 0
    attempts = 0
    with tempfile.TemporaryDirectory(prefix="pestycyd-hunt-") as directory:
        candidate = Path(directory) / "candidate.ndjson"
        while queue and (args.iterations is None or attempts < args.iterations):
            seed, document, original, depth, lineage, protected = queue.popleft()
            mutation = original if depth == 1 else dataclasses.replace(original, oracle="differential")
            child = document.mutated(mutation)
            child_protected = (
                child.final_goal_lines()
                if getattr(args, "protect_final_goal", False)
                else frozenset()
            )
            content = child.render()
            content_digest = hashlib.sha256(content.encode()).hexdigest()
            if content_digest in seen_inputs:
                continue
            seen_inputs.add(content_digest)
            attempts += 1
            candidate.write_text(content)
            results = run_matrix(kernels, candidate, args.workers)
            interesting, reason = is_interesting(
                mutation, results, include_robustness=not args.semantic_only
            )
            features = feedback_features(
                results, include_behavior=getattr(args, "behavior_feedback", False)
            )
            added = features.difference(seen_feedback)
            seen_feedback.update(features)
            history = (*lineage, mutation.json())
            metadata: dict[str, object] = {
                "seed": str(seed),
                "mutation": mutation.json(),
                "lineage": list(history),
                "depth": depth,
                "protected_goal_lines": sorted(line + 1 for line in child_protected),
                "reason": reason,
                "feedback": {
                    "new": len(added),
                    "new_features": sorted(added)[:256],
                    "new_features_truncated": len(added) > 256,
                    "total_seen": len(seen_feedback),
                },
                "kernels": [kernel.public() for kernel in kernels],
                "results": matrix_json(results),
            }
            if interesting:
                findings += 1
                digest, created = store.save(content, metadata)
                novel += created
                print(f"{'FINDING' if created else 'KNOWN'} {digest[:12]} {mutation.label}: {statuses(results)}")
            if added:
                coverage_metadata = dict(metadata)
                coverage_metadata["reason"] = "novel search feedback"
                digest, created = store.save_corpus(content, coverage_metadata)
                corpus += created
                if not interesting:
                    print(
                        f"COVERAGE {digest[:12]} +{len(added)} {mutation.label}: "
                        f"{statuses(results)}"
                    )
                if depth < args.max_depth:
                    descendants = [
                        next_mutation
                        for campaign in campaigns
                        for next_mutation in campaign.generate(child)
                        if allowed(next_mutation, child_protected)
                    ]
                    rng.shuffle(descendants)
                    descendants = descendants[: args.max_children]
                    queue.extend(
                        (seed, child, next_mutation, depth + 1, history, child_protected)
                        for next_mutation in descendants
                    )
            elif args.verbose:
                print(f"ok {attempts} {mutation.label}: {statuses(results)}")
    print(
        f"hunt: {attempts} mutations, {findings} interesting, {novel} novel findings, "
        f"{corpus} coverage inputs, {len(seen_feedback)} feedback features"
    )
    return 1 if findings else 0


def parse_expect(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("expectation must be KERNEL=STATUS")
    name, status = value.split("=", 1)
    allowed = {"accept", "reject", "decline", "timeout", "crash", "error", "runner-error"}
    if not name or status not in allowed:
        raise argparse.ArgumentTypeError("invalid KERNEL=STATUS expectation")
    return name, status


def minimize_command(config: Config, kernels: tuple[KernelSpec, ...], args: argparse.Namespace) -> int:
    expected = dict(args.expect)
    unknown = set(expected).difference(kernel.name for kernel in kernels)
    if unknown:
        raise ValueError(f"expectations name unknown kernels: {', '.join(sorted(unknown))}")
    lines = args.input.read_text().splitlines()
    tests = 0
    with tempfile.TemporaryDirectory(prefix="pestycyd-minimize-") as directory:
        candidate = Path(directory) / "candidate.ndjson"

        def interesting(trial: list[str]) -> bool:
            nonlocal tests
            tests += 1
            candidate.write_text("\n".join(trial) + "\n")
            results = run_matrix(kernels, candidate, args.workers)
            return all(results[name].status == status for name, status in expected.items())

        if not interesting(lines):
            print("input does not satisfy the requested outcomes", file=sys.stderr)
            return 2
        reduced = ddmin(lines, interesting, tuple(args.keep))
    atomic_text(args.output, "\n".join(reduced) + "\n")
    print(f"minimized {len(lines)} -> {len(reduced)} lines in {tests} tests: {args.output}")
    return 0


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="pestycyd", description="Pest control for Lean kernels")
    root.add_argument("--config", type=Path, default=Path("pestycyd.toml"))
    root.add_argument("--kernel", action="append", help="select a configured kernel; repeatable")
    root.add_argument("--workers", type=int, default=None, help="parallel kernel processes per input")
    sub = root.add_subparsers(dest="command", required=True)

    command = sub.add_parser("doctor", help="probe configured kernel executables")
    command.set_defaults(function=doctor)
    command = sub.add_parser("campaigns", help="list structural campaigns and source targets")
    command.set_defaults(no_config=True)
    command.set_defaults(function=list_campaigns)

    command = sub.add_parser("generate", help="generate boundary and stress inputs")
    generators = command.add_subparsers(dest="generator", required=True)
    generator = generators.add_parser("deep-binder", help="valid deeply bound NDJSON export")
    generator.add_argument("depth", type=int)
    generator.add_argument("output", type=Path)
    generator.set_defaults(function=generate_deep_binder, no_config=True)
    generator = generators.add_parser("con-k-params", help="valid Lean K-recursor stress module")
    generator.add_argument("count", type=int)
    generator.add_argument("output", type=Path)
    generator.set_defaults(function=generate_con_k, no_config=True)

    command = sub.add_parser("matrix", help="run inputs through a kernel matrix")
    command.add_argument("paths", nargs="+")
    command.add_argument("--report", type=Path)
    command.add_argument("--verbose", action="store_true")
    command.set_defaults(function=matrix_command)

    command = sub.add_parser("hunt", help="run structure-aware mutation campaigns")
    command.add_argument("paths", nargs="+")
    command.add_argument("--campaign", action="append")
    command.add_argument("--iterations", type=int, default=1000)
    command.add_argument("--seed", type=int, default=0)
    command.add_argument(
        "--seed-policy",
        choices=("accepted", "consensus", "any", "all"),
        default="accepted",
        help=(
            "accepted requires every kernel to accept; consensus also permits unanimous "
            "rejection; any permits non-fatal disagreement; all also permits crash/error "
            "seeds for repair-oriented mutation"
        ),
    )
    command.add_argument(
        "--max-depth", type=int, default=3,
        help="mutate coverage-expanding inputs up to this depth",
    )
    command.add_argument(
        "--max-children", type=int, default=256,
        help="maximum mutations queued from one coverage-expanding input",
    )
    command.add_argument("--state", type=Path)
    command.add_argument(
        "--semantic-only",
        action="store_true",
        help="record semantic oracle violations and disagreements, but not crash/timeout noise",
    )
    command.add_argument(
        "--behavior-feedback",
        action="store_true",
        help=(
            "grow the queue from new normalized outcome fingerprints as well as explicit "
            "instrumentation; useful for fast release-only screening"
        ),
    )
    command.add_argument(
        "--protect-final-goal",
        action="store_true",
        help=(
            "never mutate the last theorem declaration or any expression node reachable "
            "from its type"
        ),
    )
    command.add_argument("--verbose", action="store_true")
    command.set_defaults(function=hunt)

    command = sub.add_parser("minimize", help="delete NDJSON lines while preserving outcomes")
    command.add_argument("input", type=Path)
    command.add_argument("output", type=Path)
    command.add_argument("--expect", action="append", type=parse_expect, required=True)
    command.add_argument("--keep", action="append", default=[])
    command.set_defaults(function=minimize_command)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if getattr(args, "no_config", False):
            return args.function(None, (), args)
        config = load_config(args.config)
        kernels = config.selected(args.kernel)
        if not kernels:
            raise ValueError("no kernels selected; enable one or pass --kernel NAME")
        if args.workers is not None and args.workers < 1:
            raise ValueError("--workers must be at least 1")
        if getattr(args, "max_depth", 1) < 1:
            raise ValueError("--max-depth must be at least 1")
        if getattr(args, "max_children", 1) < 1:
            raise ValueError("--max-children must be at least 1")
        iterations = getattr(args, "iterations", None)
        if iterations is not None and iterations < 1:
            raise ValueError("--iterations must be at least 1")
        return args.function(config, kernels, args)
    except (OSError, ValueError, tomllib.TOMLDecodeError) as failure:
        print(f"pestycyd: {failure}", file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())

