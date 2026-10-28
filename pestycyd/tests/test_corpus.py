from __future__ import annotations

import unittest
from pathlib import Path

from pestycyd.ndjson import Document


class CorpusTests(unittest.TestCase):
    def test_every_checked_in_case_is_valid_ndjson(self) -> None:
        corpus = Path(__file__).resolve().parents[1] / "corpus"
        cases = sorted(corpus.rglob("*.ndjson"))
        self.assertGreaterEqual(len(cases), 10)
        for case in cases:
            with self.subTest(case=case.name):
                self.assertTrue(Document.load(case).lines)

    def test_dangling_expression_regression_really_has_missing_ids(self) -> None:
        case = (
            Path(__file__).resolve().parents[1]
            / "corpus"
            / "regressions"
            / "sokonanoda-dangling-expr-ids.ndjson"
        )
        document = Document.load(case)
        defined = {
            line["ie"]
            for line in document.lines
            if isinstance(line.get("ie"), int)
        }
        recursor = document.lines[-1]["inductive"]["recs"][0]
        referenced = {recursor["type"], *(rule["rhs"] for rule in recursor["rules"])}
        self.assertEqual(referenced.difference(defined), {14, 20})


if __name__ == "__main__":
    unittest.main()
