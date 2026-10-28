from __future__ import annotations

import argparse
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

from pestycyd.cli import feedback_features, hunt, is_interesting, seed_is_eligible
from pestycyd.config import Config, FeedbackSpec, KernelSpec
from pestycyd.ndjson import Mutation
from pestycyd.outcomes import Outcome


class HuntTests(unittest.TestCase):
    def test_novel_feedback_grows_persistent_corpus(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            seed = root / "seed.ndjson"
            seed.write_text('{"idx":2}\n')
            script = (
                "from pathlib import Path; import hashlib, sys; "
                "data=Path(sys.argv[1]).read_bytes(); "
                "Path(sys.argv[2]).write_text(hashlib.sha256(data).hexdigest()); "
                "print('accepted')"
            )
            kernel = KernelSpec(
                name="instrumented",
                command=(sys.executable, "-c", script, "{file}", "{run_dir}/trace"),
                cwd=root,
                timeout=5.0,
                verdict="required",
                feedback=FeedbackSpec(format="lines", path="{run_dir}/trace", required=True),
            )
            state = root / "state"
            config = Config(path=root / "pestycyd.toml", state=state, kernels=(kernel,))
            args = argparse.Namespace(
                paths=[str(seed)],
                campaign=["metadata-boundaries"],
                seed=7,
                state=None,
                workers=None,
                iterations=2,
                max_depth=2,
                max_children=32,
                seed_policy="accepted",
                semantic_only=False,
                verbose=False,
            )

            with contextlib.redirect_stdout(io.StringIO()):
                result = hunt(config, (kernel,), args)
            corpus = list((state / "corpus").glob("*.ndjson"))

        self.assertEqual(result, 0)
        self.assertEqual(len(corpus), 2)

    def test_consensus_policy_mutates_unanimously_rejected_seed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            seed = root / "seed.ndjson"
            seed.write_text('{"idx":2}\n')
            script = (
                "from pathlib import Path; import hashlib, sys; "
                "data=Path(sys.argv[1]).read_bytes(); "
                "Path(sys.argv[2]).write_text(hashlib.sha256(data).hexdigest()); "
                "print('rejected', file=sys.stderr); raise SystemExit(1)"
            )
            kernel = KernelSpec(
                name="instrumented",
                command=(sys.executable, "-c", script, "{file}", "{run_dir}/trace"),
                cwd=root,
                timeout=5.0,
                verdict="required",
                feedback=FeedbackSpec(format="lines", path="{run_dir}/trace", required=True),
            )
            state = root / "state"
            config = Config(path=root / "pestycyd.toml", state=state, kernels=(kernel,))
            args = argparse.Namespace(
                paths=[str(seed)],
                campaign=["metadata-boundaries"],
                seed=7,
                state=None,
                workers=None,
                iterations=1,
                max_depth=1,
                max_children=32,
                seed_policy="consensus",
                semantic_only=False,
                verbose=False,
            )

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                result = hunt(config, (kernel,), args)

        self.assertEqual(result, 0)
        self.assertIn("hunt: 1 mutations", stdout.getvalue())

    def test_semantic_only_ignores_reject_versus_internal_error(self) -> None:
        mutation = Mutation("test", "test", "differential", 0, (), "x", 1, "test")
        results = {
            "reference": Outcome("reject", 0.1, 1, "reject", "a", ""),
            "target": Outcome("error", 0.1, 3, None, "b", "internal error"),
        }
        self.assertTrue(is_interesting(mutation, results)[0])
        self.assertFalse(is_interesting(mutation, results, include_robustness=False)[0])

    def test_semantic_only_keeps_accept_reject_disagreement(self) -> None:
        mutation = Mutation("test", "test", "differential", 0, (), "x", 1, "test")
        results = {
            "reference": Outcome("reject", 0.1, 1, "reject", "a", ""),
            "target": Outcome("accept", 0.1, 0, "accept", "b", ""),
        }
        self.assertTrue(is_interesting(mutation, results, include_robustness=False)[0])

    def test_behavior_feedback_uses_normalized_outcome_fingerprints(self) -> None:
        results = {
            "target": Outcome("reject", 0.1, 1, "reject", "rejected: first class", ""),
        }
        self.assertEqual(feedback_features(results), set())
        features = feedback_features(results, include_behavior=True)
        self.assertEqual(len(features), 1)
        self.assertTrue(next(iter(features)).startswith("target:behavior:reject:"))

    def test_all_seed_policy_can_evolve_from_target_crash(self) -> None:
        results = {
            "official": Outcome("reject", 0.1, 1, "reject", "rejected", ""),
            "target": Outcome("crash", 0.1, 101, None, "panic", ""),
        }
        self.assertFalse(seed_is_eligible("any", results))
        self.assertTrue(seed_is_eligible("all", results))


if __name__ == "__main__":
    unittest.main()
