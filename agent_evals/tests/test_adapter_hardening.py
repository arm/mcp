# Copyright © 2026, Arm Limited and Contributors. All rights reserved.
"""Check that a trial cannot alter saved Codex authentication."""

from __future__ import annotations

import json
import os
import signal
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_evals.codex_adapter import run_codex


class AdapterHardeningTests(unittest.TestCase):
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
