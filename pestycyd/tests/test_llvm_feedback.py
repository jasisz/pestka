from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pestycyd.llvm_feedback import extract_features


class LlvmFeedbackTests(unittest.TestCase):
    def test_extracts_only_executed_regions_and_branch_sides(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "generated.rs"
            report: dict[str, object] = {
                "data": [
                    {
                        "files": [
                            {
                                "filename": str(source),
                                "segments": [
                                    [10, 2, 3, True, True, False],
                                    [11, 2, 0, True, True, False],
                                    [12, 2, 9, True, False, False],
                                ],
                                "branches": [
                                    [20, 1, 20, 8, 4, 0],
                                    [21, 1, 21, 8, 1, 2],
                                ],
                            }
                        ]
                    }
                ]
            }

            features = extract_features(report, root)

        self.assertEqual(
            features,
            {
                "region:generated.rs:10:2",
                "branch-true:generated.rs:20:1:20:8",
                "branch-true:generated.rs:21:1:21:8",
                "branch-false:generated.rs:21:1:21:8",
            },
        )

    def test_can_drop_dependency_coverage_outside_source_root(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            report: dict[str, object] = {
                "data": [
                    {
                        "files": [
                            {
                                "filename": "/dependency/lib.rs",
                                "segments": [[1, 1, 1, True, True, False]],
                            },
                            {
                                "filename": str(root / "main.rs"),
                                "segments": [[2, 1, 1, True, True, False]],
                            },
                        ]
                    }
                ]
            }
            features = extract_features(report, root, only_source_root=True)
        self.assertEqual(features, {"region:main.rs:2:1"})


if __name__ == "__main__":
    unittest.main()
