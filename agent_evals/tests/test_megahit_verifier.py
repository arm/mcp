"""Check host-side fixture handling in the MEGAHIT verifier."""

from __future__ import annotations

import os
import runpy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


VERIFY = Path(__file__).resolve().parents[1] / "scenarios" / "megahit-arm64" / "verify.py"


class MegahitVerifierTests(unittest.TestCase):
    def test_original_fixtures_unchanged_allows_new_tests(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            workspace = root / "workspace"
            for directory in (source, workspace):
                fixture = directory / "test_data"
                fixture.mkdir(parents=True)
                (fixture / "sample.fa").write_text(">read\nACGT\n", encoding="ascii")
            environment = {
                "AGENT_EVAL_SCENARIO_DIR": str(root),
                "AGENT_EVAL_WORKSPACE": str(workspace),
                "AGENT_EVAL_TRIAL_DIR": str(root),
                "AGENT_EVAL_VERIFIER_RESULT": str(root / "verifier.json"),
            }
            with patch.dict(os.environ, environment):
                unchanged = runpy.run_path(str(VERIFY))["original_fixtures_unchanged"]

            (workspace / "test_data" / "check_portable_rank.cpp").write_text(
                "int main() { return 0; }\n", encoding="ascii"
            )
            self.assertTrue(unchanged(source, workspace))

            original = workspace / "test_data" / "sample.fa"
            original.write_text(">read\nTTTT\n", encoding="ascii")
            self.assertFalse(unchanged(source, workspace))

            original.unlink()
            self.assertFalse(unchanged(source, workspace))

    def test_fixture_hashes_reject_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            fixture = workspace / "test_data"
            fixture.mkdir(parents=True)
            (fixture / "sample.fa").write_text(">read\nACGT\n", encoding="ascii")
            outside = root / "outside.fa"
            outside.write_text(">secret\nTTTT\n", encoding="ascii")
            environment = {
                "AGENT_EVAL_SCENARIO_DIR": str(root),
                "AGENT_EVAL_WORKSPACE": str(workspace),
                "AGENT_EVAL_TRIAL_DIR": str(root),
                "AGENT_EVAL_VERIFIER_RESULT": str(root / "verifier.json"),
            }
            with patch.dict(os.environ, environment):
                fixture_hashes = runpy.run_path(str(VERIFY))["fixture_hashes"]

            self.assertEqual(len(fixture_hashes(workspace)), 1)
            linked_file = fixture / "linked.fa"
            linked_file.symlink_to(outside)
            with self.assertRaisesRegex(OSError, "symlink"):
                fixture_hashes(workspace)
            linked_file.unlink()

            linked_directory = fixture / "linked_directory"
            linked_directory.symlink_to(root, target_is_directory=True)
            with self.assertRaisesRegex(OSError, "symlink"):
                fixture_hashes(workspace)
            linked_directory.unlink()

            fixture.rename(root / "original_test_data")
            fixture.symlink_to(root / "original_test_data", target_is_directory=True)
            with self.assertRaisesRegex(OSError, "symlink"):
                fixture_hashes(workspace)


if __name__ == "__main__":
    unittest.main()
