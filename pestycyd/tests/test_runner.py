from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

from pestycyd.config import FeedbackSpec, KernelSpec
from pestycyd.runner import _feedback_features, run_kernel


class RunnerTests(unittest.TestCase):
    def test_chunked_bitmap_feedback_tracks_changed_chunks(self) -> None:
        header = bytes(128)
        first = _feedback_features(header + bytes([1]) + bytes(127), "bitmap-chunks")
        second = _feedback_features(
            header + bytes([2]) + bytes(63) + bytes([1]) + bytes(63),
            "bitmap-chunks",
        )
        self.assertEqual(len(first), 1)
        self.assertEqual(len(second), 2)
        self.assertTrue(first.difference(second))

    def test_collects_line_feedback_from_run_directory(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            input_path = root / "case.ndjson"
            input_path.write_text("{}\n")
            script = (
                "from pathlib import Path; import sys; "
                "Path(sys.argv[2]).write_text('edge-a\\nedge-b\\nedge-a\\n'); "
                "print('accepted')"
            )
            kernel = KernelSpec(
                name="fake",
                command=(sys.executable, "-c", script, "{file}", "{run_dir}/trace"),
                cwd=root,
                timeout=5.0,
                verdict="required",
                feedback=FeedbackSpec(format="lines", path="{run_dir}/trace", required=True),
            )
            outcome = run_kernel(kernel, input_path)

        self.assertEqual(outcome.status, "accept")
        self.assertEqual(len(outcome.feedback), 2)
        self.assertIsNone(outcome.feedback_error)
        feedback = outcome.json()["feedback"]
        self.assertEqual(feedback["features"], 2)  # type: ignore[index]

    def test_required_feedback_failure_is_a_runner_error(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            input_path = root / "case.ndjson"
            input_path.write_text("{}\n")
            kernel = KernelSpec(
                name="fake",
                command=(sys.executable, "-c", "print('accepted')", "{file}"),
                cwd=root,
                timeout=5.0,
                verdict="required",
                feedback=FeedbackSpec(format="lines", path="{run_dir}/missing", required=True),
            )
            outcome = run_kernel(kernel, input_path)

        self.assertEqual(outcome.status, "runner-error")
        self.assertIn("required feedback failed", outcome.error or "")

    def test_process_output_is_bounded_to_a_tail(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            input_path = root / "case.ndjson"
            input_path.write_text("{}\n")
            kernel = KernelSpec(
                name="noisy",
                command=(
                    sys.executable,
                    "-c",
                    "print('x' * 100000); print('accepted')",
                    "{file}",
                ),
                cwd=root,
                timeout=5.0,
                verdict="required",
            )
            outcome = run_kernel(kernel, input_path)

        self.assertEqual(outcome.status, "accept")
        self.assertLessEqual(len(outcome.output.encode()), 4096)
        self.assertTrue(outcome.output.rstrip().endswith("accepted"))

    def test_timeout_is_reported_after_forced_termination(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            input_path = root / "case.ndjson"
            input_path.write_text("{}\n")
            kernel = KernelSpec(
                name="sleeper",
                command=(sys.executable, "-c", "import time; time.sleep(10)", "{file}"),
                cwd=root,
                timeout=0.05,
                verdict="required",
            )
            outcome = run_kernel(kernel, input_path)

        self.assertEqual(outcome.status, "timeout")


if __name__ == "__main__":
    unittest.main()
