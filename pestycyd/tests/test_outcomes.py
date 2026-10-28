import unittest

from pestycyd.outcomes import classify, parse_verdict


class OutcomeTests(unittest.TestCase):
    def test_accept_count_is_a_verdict(self) -> None:
        self.assertEqual(parse_verdict("accepted 42 declarations\n"), "accept")

    def test_exit_one_without_verdict_is_not_rejection(self) -> None:
        status, verdict, error = classify(1, "WASM requires --features wasm\n", "required")
        self.assertEqual(status, "runner-error")
        self.assertIsNone(verdict)
        self.assertIn("no recognized verdict", error or "")

    def test_verdict_must_match_code(self) -> None:
        status, _, _ = classify(1, "accepted\n", "required")
        self.assertEqual(status, "runner-error")

    def test_rust_panic_is_a_crash_even_without_verdict(self) -> None:
        status, verdict, error = classify(101, "thread panicked\n", "required")
        self.assertEqual(status, "crash")
        self.assertIsNone(verdict)
        self.assertIsNone(error)

    def test_nonstandard_process_failure_is_not_a_runner_failure(self) -> None:
        status, _, _ = classify(3, "internal error\n", "required")
        self.assertEqual(status, "error")

    def test_custom_decline_exit_code(self) -> None:
        status, _, _ = classify(4, "", "none", ((4, "decline"),))
        self.assertEqual(status, "decline")


if __name__ == "__main__":
    unittest.main()

