# Copyright © 2026, Arm Limited and Contributors. All rights reserved.
"""Check host-side fixture handling in the MEGAHIT verifier."""

from __future__ import annotations

import os
import json
import runpy
import signal
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


VERIFY = Path(__file__).resolve().parents[1] / "scenarios" / "megahit-arm64" / "verify.py"


class MegahitVerifierTests(unittest.TestCase):
    def test_verifier_user_matches_rootful_linux_caller(self):
        with tempfile.TemporaryDirectory() as temporary:
            environment = {
                "AGENT_EVAL_SCENARIO_DIR": temporary,
                "AGENT_EVAL_WORKSPACE": temporary,
                "AGENT_EVAL_TRIAL_DIR": temporary,
                "AGENT_EVAL_VERIFIER_RESULT": str(Path(temporary) / "verifier.json"),
            }
            with patch.dict(os.environ, environment):
                user_args = runpy.run_path(str(VERIFY))["_verifier_user_args"]
        self.assertEqual(user_args([], "linux", 1000, 1001),
                         ["--user", "1000:1001", "-e", "HOME=/results"])
        self.assertEqual(user_args(["name=rootless"], "linux", 1000, 1001), [])
        self.assertEqual(user_args([], "darwin", 1000, 1001), [])
        with self.assertRaisesRegex(RuntimeError, "userns-remap"):
            user_args(["name=userns"], "linux", 1000, 1001)

    def test_missing_workspace_fixture_is_scored_as_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            fixture = source / "test_data"
            fixture.mkdir(parents=True)
            (fixture / "sample.fa").write_text(">read\nACGT\n", encoding="ascii")
            workspace = root / "workspace"
            workspace.mkdir()
            result = root / "verifier.json"
            environment = {
                "AGENT_EVAL_SCENARIO_DIR": str(root),
                "AGENT_EVAL_WORKSPACE": str(workspace),
                "AGENT_EVAL_INPUT_SOURCE": str(source),
                "AGENT_EVAL_TRIAL_DIR": str(root),
                "AGENT_EVAL_VERIFIER_RESULT": str(result),
            }
            with patch.dict(os.environ, environment), patch("subprocess.run") as docker:
                verify = runpy.run_path(str(VERIFY))
                self.assertEqual(verify["main"](), 1)
                docker.assert_not_called()
            self.assertEqual(json.loads(result.read_text())["stage"],
                             "fixture_integrity")

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

            (workspace / "test_data").rename(root / "removed_test_data")
            self.assertFalse(unchanged(source, workspace))
            (workspace / "test_data").symlink_to(root / "removed_test_data",
                                                    target_is_directory=True)
            self.assertFalse(unchanged(source, workspace))

            (source / "test_data" / "sample.fa").unlink()
            (source / "test_data").rmdir()
            with self.assertRaises(OSError):
                unchanged(source, workspace)

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

    def test_container_uses_dedicated_output_mount(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, workspace, trial = (root / name for name in
                                         ("source", "workspace", "trial"))
            for directory in (source, workspace):
                fixture = directory / "test_data"
                fixture.mkdir(parents=True)
                (fixture / "sample.fa").write_text(">read\nACGT\n", encoding="ascii")
            trial.mkdir()
            environment = {
                "AGENT_EVAL_SCENARIO_DIR": str(root),
                "AGENT_EVAL_WORKSPACE": str(workspace),
                "AGENT_EVAL_INPUT_SOURCE": str(source),
                "AGENT_EVAL_TRIAL_DIR": str(trial),
                "AGENT_EVAL_VERIFIER_RESULT": str(trial / "verifier.json"),
            }

            def fake_docker(args, **kwargs):
                if args[:2] == ["docker", "info"]:
                    if "{{json .SecurityOptions}}" in args:
                        return subprocess.CompletedProcess(args, 0, "[]\n")
                    return subprocess.CompletedProcess(args, 0, "arm64 linux\n")
                if args[:2] == ["docker", "build"]:
                    return subprocess.CompletedProcess(args, 0, "image-id\n")
                self.assertEqual(args[:2], ["docker", "run"])
                self.assertEqual(args[args.index("--user") + 1],
                                 f"{os.getuid()}:{os.getgid()}")
                mounts = [args[index + 1] for index, value in enumerate(args)
                          if value == "--mount"]
                self.assertIn(f"type=bind,source={workspace},target=/workspace,readonly",
                              mounts)
                self.assertIn(f"type=bind,source={source},target=/fixture,readonly",
                              mounts)
                results_mount = next(mount for mount in mounts
                                     if mount.endswith(",target=/results"))
                output_dir = Path(results_mount.split("source=", 1)[1].split(",", 1)[0])
                self.assertEqual(output_dir.parent, trial)
                self.assertNotEqual(output_dir, trial)
                (output_dir / "verifier.json").write_text('{"success": true}\n')
                return subprocess.CompletedProcess(args, 0, "verified\n")

            with patch.dict(os.environ, environment), patch("sys.platform", "linux"), \
                 patch("subprocess.run", side_effect=fake_docker):
                verify = runpy.run_path(str(VERIFY))
                self.assertEqual(verify["main"](), 0)
                self.assertTrue(json.loads((trial / "verifier.json").read_text())["success"])
                with patch("shutil.copyfile", side_effect=OSError("copy denied")):
                    self.assertEqual(verify["main"](), 2)
            copy_error = json.loads((trial / "verifier.json").read_text())
            self.assertEqual(copy_error["stage"], "verifier_container")
            self.assertIn("copy denied", copy_error["error"])

    def test_unfinished_containers_are_removed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source, workspace, trial = (root / name for name in
                                         ("source", "workspace", "trial"))
            for directory in (source, workspace):
                fixture = directory / "test_data"
                fixture.mkdir(parents=True)
                (fixture / "sample.fa").write_text(">read\nACGT\n", encoding="ascii")
            trial.mkdir()
            environment = {
                "AGENT_EVAL_SCENARIO_DIR": str(root),
                "AGENT_EVAL_WORKSPACE": str(workspace),
                "AGENT_EVAL_INPUT_SOURCE": str(source),
                "AGENT_EVAL_TRIAL_DIR": str(trial),
                "AGENT_EVAL_VERIFIER_RESULT": str(trial / "verifier.json"),
            }
            removed = []
            failure_mode = ["timeout"]

            def fake_docker(args, **kwargs):
                if args[:2] == ["docker", "info"]:
                    if "{{json .SecurityOptions}}" in args:
                        return subprocess.CompletedProcess(args, 0, "[]\n")
                    return subprocess.CompletedProcess(args, 0, "arm64 linux\n")
                if args[:2] == ["docker", "build"]:
                    return subprocess.CompletedProcess(args, 0, "image-id\n")
                if args[:2] == ["docker", "run"]:
                    if failure_mode[0] == "timeout":
                        raise subprocess.TimeoutExpired(args, kwargs["timeout"])
                    if failure_mode[0] == "sigterm":
                        handler = signal.getsignal(signal.SIGTERM)
                        self.assertTrue(callable(handler))
                        handler(signal.SIGTERM, None)
                    if failure_mode[0] == "client_with_result":
                        mounts = [args[index + 1] for index, value in enumerate(args)
                                  if value == "--mount"]
                        result_mount = next(mount for mount in mounts
                                            if mount.endswith(",target=/results"))
                        output_dir = Path(result_mount.split("source=", 1)[1]
                                          .split(",", 1)[0])
                        (output_dir / "verifier.json").write_text(
                            '{"success": false, "stage": "build"}\n'
                        )
                        return subprocess.CompletedProcess(args, 1, "build failed\n")
                    return subprocess.CompletedProcess(args, 125, "client failed\n")
                self.assertEqual(args[:3], ["docker", "rm", "-f"])
                removed.append(args)
                return subprocess.CompletedProcess(args, 0, "removed\n", "")

            with patch.dict(os.environ, environment), patch("subprocess.run",
                                                             side_effect=fake_docker):
                verify = runpy.run_path(str(VERIFY))
                previous_sigterm = signal.getsignal(signal.SIGTERM)
                self.assertEqual(verify["main"](), 2)
                verdict = json.loads((trial / "verifier.json").read_text())
                self.assertEqual(verdict["stage"], "verifier_container")
                self.assertIn("timed out", verdict["error"])

                failure_mode[0] = "sigterm"
                with self.assertRaises(KeyboardInterrupt):
                    verify["main"]()
                self.assertIs(signal.getsignal(signal.SIGTERM), previous_sigterm)

                failure_mode[0] = "client_error"
                self.assertEqual(verify["main"](), 2)
                self.assertIn("client failed", (trial / "verifier.json").read_text())

                failure_mode[0] = "client_with_result"
                self.assertEqual(verify["main"](), 1)
                self.assertEqual(json.loads((trial / "verifier.json").read_text())["stage"],
                                 "build")
            self.assertEqual(len(removed), 4)
            for command in removed:
                self.assertEqual(command[:4], ["docker", "rm", "-f", "-v"])
            self.assertEqual(len({command[-1] for command in removed}), 4)


if __name__ == "__main__":
    unittest.main()
