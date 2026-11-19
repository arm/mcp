# Copyright © 2026, Arm Limited and Contributors. All rights reserved.
"""Check that a trial cannot alter saved Codex authentication."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_evals.codex_adapter import _cleanup_docker_mcp_containers, run_codex
from agent_evals.runner import RunnerError


class AdapterHardeningTests(unittest.TestCase):
    def test_cleanup_continues_to_other_mcp_servers_after_an_error(self):
        calls = []

        def docker_command(args, **kwargs):
            calls.append(args)
            if args[1] == "ps" and args[-1] == "label=first":
                return subprocess.CompletedProcess(args, 1, "", "daemon error")
            if args[1] == "ps":
                return subprocess.CompletedProcess(args, 0, "second-container\n", "")
            return subprocess.CompletedProcess(args, 0, "second-container\n", "")

        with patch("agent_evals.codex_adapter.subprocess.run", side_effect=docker_command):
            with self.assertRaisesRegex(RunnerError, "daemon error"):
                _cleanup_docker_mcp_containers(
                    [("docker", "first"), ("docker", "second")], os.environ.copy(),
                )
        self.assertEqual(calls[-1],
                         ["docker", "rm", "--force", "--volumes", "second-container"])

    def test_docker_mcp_cleanup_preserves_agent_result_on_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_codex = root / "fake-codex"
            fake_codex.write_text(
                f"#!{sys.executable}\n"
                "import json, sys, time\n"
                "from pathlib import Path\n"
                "args = sys.argv[1:]\n"
                "configs = dict(args[i + 1].split('=', 1) for i, arg in "
                "enumerate(args[:-1]) if arg == '-c')\n"
                "trial = Path(args[args.index('-o') + 1]).parent\n"
                "(trial / 'mcp-args.json').write_text(configs['mcp_servers.arm.args'])\n"
                "sys.stdin.read()\n"
                "if (trial / 'hang').exists(): time.sleep(60)\n"
                "print(json.dumps({'type': 'turn.completed', 'usage': "
                "{'input_tokens': 1, 'output_tokens': 1}}))\n",
                encoding="utf-8",
            )
            fake_codex.chmod(0o755)
            server = {"name": "arm", "launch": ["docker", "run", "--rm", "-i", "test-image"]}

            for hangs, cleanup_fails in ((False, False), (True, False), (False, True)):
                with self.subTest(hangs=hangs, cleanup_fails=cleanup_fails):
                    trial = root / ("timeout" if hangs else
                                    "cleanup-error" if cleanup_fails else "completed")
                    workspace = trial / "workspace"
                    workspace.mkdir(parents=True)
                    if hangs:
                        (trial / "hang").touch()
                    docker_calls = []

                    def docker_command(args, **kwargs):
                        docker_calls.append(args)
                        if args[1] == "ps":
                            if cleanup_fails:
                                return subprocess.CompletedProcess(args, 1, "", "daemon error")
                            return subprocess.CompletedProcess(args, 0, "owned-container\n", "")
                        return subprocess.CompletedProcess(args, 0, "owned-container\n", "")

                    with patch("agent_evals.codex_adapter.subprocess.run", side_effect=docker_command):
                        result = run_codex(
                            {"agent": {"kind": "codex", "model": "test"}},
                            [(server, root)], workspace, trial, "Test.\n",
                            0.2 if hangs else 10, executable=str(fake_codex),
                        )

                    self.assertEqual(result["status"], "timeout" if hangs else "completed")
                    launch = json.loads((trial / "mcp-args.json").read_text(encoding="utf-8"))
                    self.assertEqual(launch[:3], ["run", "--label", launch[2]])
                    self.assertTrue(launch[2].startswith("arm-agent-evals.mcp="))
                    self.assertEqual(docker_calls[0][1:],
                                     ["ps", "--all", "--quiet", "--filter", f"label={launch[2]}"])
                    if cleanup_fails:
                        self.assertIn("daemon error", result["mcp_cleanup_error"])
                        self.assertEqual(len(docker_calls), 1)
                    else:
                        self.assertNotIn("mcp_cleanup_error", result)
                        self.assertEqual(docker_calls[1],
                                         ["docker", "rm", "--force", "--volumes",
                                          "owned-container"])
                    self.assertEqual(server["launch"], ["docker", "run", "--rm", "-i", "test-image"])

    def test_normal_codex_exit_stops_background_child(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            workspace = root / "workspace"
            trial = root / "trial"
            workspace.mkdir()
            trial.mkdir()
            heartbeat = trial / "child-heartbeat.txt"
            child_script = root / "child.py"
            child_script.write_text(
                "import sys, time\n"
                "while True:\n"
                "    with open(sys.argv[1], 'a') as output: output.write('x')\n"
                "    time.sleep(0.02)\n",
                encoding="utf-8",
            )
            fake_codex = root / "fake-codex"
            fake_codex.write_text(
                f"#!{sys.executable}\n"
                "import json, subprocess, sys, time\n"
                "from pathlib import Path\n"
                f"child = subprocess.Popen([{sys.executable!r}, {str(child_script)!r}, "
                f"{str(heartbeat)!r}])\n"
                f"Path({str(trial / 'child.pid')!r}).write_text(str(child.pid))\n"
                f"while not Path({str(heartbeat)!r}).exists(): time.sleep(0.01)\n"
                "sys.stdin.read()\n"
                "print(json.dumps({'type': 'turn.completed', 'usage': "
                "{'input_tokens': 1, 'output_tokens': 1}}))\n",
                encoding="utf-8",
            )
            fake_codex.chmod(0o755)
            try:
                result = run_codex(
                    {"agent": {"kind": "codex", "model": "test"}},
                    [], workspace, trial, "Test.\n", 10, executable=str(fake_codex),
                )
                self.assertEqual(result["status"], "completed")
                before = heartbeat.stat().st_size
                time.sleep(0.2)
                self.assertEqual(heartbeat.stat().st_size, before)
            finally:
                pid_file = trial / "child.pid"
                if pid_file.exists():
                    try:
                        os.kill(int(pid_file.read_text()), signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def test_interrupt_kills_and_reaps_codex(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            codex_home = root / "codex-home"
            codex_home.mkdir()
            workspace = root / "workspace"
            trial = root / "trial"
            workspace.mkdir()
            trial.mkdir()
            with patch.dict(os.environ, {"CODEX_HOME": str(codex_home)}), \
                 patch("agent_evals.codex_adapter.subprocess.Popen") as popen, \
                 patch("agent_evals.codex_adapter._kill_process_group") as kill_group:
                process = popen.return_value
                process.communicate.side_effect = [KeyboardInterrupt, (None, None)]
                with self.assertRaises(KeyboardInterrupt):
                    run_codex(
                        {"agent": {"kind": "codex", "model": "test"}},
                        [], workspace, trial, "Test.\n", 10,
                    )
                kill_group.assert_called_once_with(process)
                self.assertEqual(process.communicate.call_count, 2)

    def test_signaled_agent_is_recorded_as_interrupted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_codex = root / "fake-codex"
            fake_codex.write_text(
                f"#!{sys.executable}\n"
                "import os, signal\n"
                "os.kill(os.getpid(), signal.SIGTERM)\n",
                encoding="utf-8",
            )
            fake_codex.chmod(0o755)
            workspace = root / "workspace"
            trial = root / "trial"
            workspace.mkdir()
            trial.mkdir()

            with patch("agent_evals.codex_adapter._kill_process_group") as kill_group:
                result = run_codex(
                    {"agent": {"kind": "codex", "model": "test"}},
                    [], workspace, trial, "Test.\n", 10, executable=str(fake_codex),
                )

            self.assertEqual(result["status"], "interrupted")
            self.assertEqual(result["exit_code"], -15)
            kill_group.assert_called_once()

    def test_codex_uses_private_auth_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original_home = root / "original-codex-home"
            original_home.mkdir()
            original_auth = original_home / "auth.json"
            original_auth.write_text('{"token":"original"}', encoding="utf-8")

            fake_codex = root / "fake-codex"
            fake_codex.write_text(
                f"#!{sys.executable}\n"
                "import json, os, stat, sys\n"
                "from pathlib import Path\n"
                "auth = Path(os.environ['CODEX_HOME']) / 'auth.json'\n"
                "answer = Path(sys.argv[sys.argv.index('-o') + 1])\n"
                "answer.with_name('auth-check.json').write_text(json.dumps({\n"
                "    'is_symlink': auth.is_symlink(),\n"
                "    'mode': stat.S_IMODE(auth.stat().st_mode),\n"
                "    'codex_home': str(auth.parent),\n"
                "}))\n"
                "auth.write_text('changed during trial')\n"
                "sys.stdin.read()\n"
                "print(json.dumps({'type': 'turn.completed', 'usage': {\n"
                "    'input_tokens': 1, 'output_tokens': 1}}))\n",
                encoding="utf-8",
            )
            fake_codex.chmod(0o755)
            workspace = root / "workspace"
            trial = root / "trial"
            workspace.mkdir()
            trial.mkdir()
            configuration = {"agent": {"kind": "codex", "model": "test"}}

            with patch.dict(os.environ, {"CODEX_HOME": str(original_home)}), \
                 patch("agent_evals.codex_adapter._kill_process_group") as kill_group:
                result = run_codex(
                    configuration, [], workspace, trial, "Test.\n", 10,
                    executable=str(fake_codex),
                )

            self.assertEqual(result["status"], "completed")
            kill_group.assert_called_once()
            captured = json.loads((trial / "auth-check.json").read_text(encoding="utf-8"))
            self.assertFalse(captured["is_symlink"])
            self.assertEqual(captured["mode"] & 0o077, 0)
            self.assertFalse(Path(captured["codex_home"]).exists())
            self.assertEqual(original_auth.read_text(encoding="utf-8"), '{"token":"original"}')
