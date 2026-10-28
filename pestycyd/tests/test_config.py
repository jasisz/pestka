from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from pestycyd.config import load_config


class ConfigTests(unittest.TestCase):
    def test_example_lists_the_complete_kernel_matrix(self) -> None:
        example = Path(__file__).resolve().parents[1] / "pestycyd.example.toml"
        config = load_config(example)
        names = {kernel.name for kernel in config.kernels}
        self.assertTrue(
            {
                "pestka-old", "pestka-next", "pestka-vm", "pestka-wasm-gc",
                "pestka-llvm", "official", "lean4lean", "nanoda", "nanoda-arena", "nanoclo",
                "nanobruijn", "sokonanoda", "mathgraph", "kefir", "con-leche",
                "tenet", "con-ron", "con-agua",
            }.issubset(names)
        )
        self.assertEqual(
            {kernel.name for kernel in config.selected(None)},
            {"pestka-old", "pestka-next"},
        )
        self.assertEqual(config.selected(["kefir"])[0].name, "kefir")

    def test_file_placeholder_may_live_in_environment(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            path = Path(raw) / "pestycyd.toml"
            path.write_text(
                'version=1\n[kernels.k]\ncommand=["checker"]\n'
                'env={IN="{file}"}\nverdict="none"\n'
            )
            config = load_config(path)
        self.assertEqual(config.kernels[0].env, (("IN", "{file}"),))

    def test_checker_can_override_decline_exit_code(self) -> None:
        example = Path(__file__).resolve().parents[1] / "pestycyd.example.toml"
        tenet = load_config(example).selected(["tenet"])[0]
        self.assertIn((4, "decline"), tenet.exit_codes)


if __name__ == "__main__":
    unittest.main()
