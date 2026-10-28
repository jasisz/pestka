from __future__ import annotations

import json
import unittest

from pestycyd.generators import con_k_params, deep_binder


class GeneratorTests(unittest.TestCase):
    def test_deep_binder_is_ndjson_with_requested_depth(self) -> None:
        lines = [json.loads(line) for line in deep_binder(4).splitlines()]
        foralls = [line for line in lines if "forallE" in line]
        lambdas = [line for line in lines if "lam" in line]
        self.assertEqual(len(foralls), 5)
        self.assertEqual(len(lambdas), 5)
        self.assertIn("thm", lines[-1])

    def test_con_k_generator_has_every_parameter(self) -> None:
        source = con_k_params(4)
        self.assertIn("(P0 : Prop)", source)
        self.assertIn("(P3 : Prop)", source)
        self.assertIn("collapse", source)


if __name__ == "__main__":
    unittest.main()
