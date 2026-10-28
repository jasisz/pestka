from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

from pestycyd.cli import main


class CliTests(unittest.TestCase):
    def test_matrix_command_does_not_require_hunt_only_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            case = root / "case.ndjson"
            case.write_text("{}\n")
            config = root / "pestycyd.toml"
            command = [sys.executable, "-c", "print('accepted')", "{file}"]
            config.write_text(
                "version=1\n[kernels.fake]\n"
                f"command={json.dumps(command)}\nverdict='required'\n"
            )
            with contextlib.redirect_stdout(io.StringIO()):
                result = main(["--config", str(config), "matrix", str(case)])
        self.assertEqual(result, 0)

    def test_campaign_listing_needs_no_configuration(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            result = main(["campaigns"])
        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
