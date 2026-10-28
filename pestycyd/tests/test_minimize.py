import unittest

from pestycyd.minimize import ddmin


class MinimizeTests(unittest.TestCase):
    def test_ddmin_keeps_only_required_lines(self) -> None:
        lines = ["header", "noise-a", "needle", "noise-b"]
        result = ddmin(lines, lambda trial: "header" in trial and "needle" in trial, ("header",))
        self.assertEqual(result, ["header", "needle"])


if __name__ == "__main__":
    unittest.main()
