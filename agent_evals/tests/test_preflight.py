# Copyright © 2026, Arm Limited and Contributors. All rights reserved.
"""Check failures that should be detected before an agent trial starts."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent_evals.preflight import PreflightError, check_preflight, check_prepared_skills
from agent_evals.scenario import ScenarioError, load_scenario


class PreflightTests(unittest.TestCase):
    def _scenario(self, folder: Path, verifier: list[str], servers: list[dict] | None = None,
                  *, docker_access: bool = False):
        document = {
            "schema_version": 1, "id": "check",
            "task": {"request": "Do the task.", "verifier": {"command": verifier}},
            "run": {"execution_target": "local", "repetitions": 1,
                    "agent_timeout_seconds": 30, "docker_access": docker_access},
            "configurations": [{
                "id": "codex", "agent": {"kind": "codex", "model": "test"},
                **({"mcp_servers": servers} if servers else {}),
            }],
        }
        path = folder / "scenario.json"
        path.write_text(json.dumps(document), encoding="utf-8")
        return load_scenario(path)

    def test_missing_verifier_script_fails_before_agent_check(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ScenarioError, "task.verifier.command script does not exist"):
                self._scenario(Path(temporary), [sys.executable, "missing.py"])

    def test_missing_local_skill_root_fails_scenario_loading(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(temporary)
            source = folder / "server"
            source.mkdir()
            with self.assertRaisesRegex(ScenarioError, "skills_root does not exist"):
                self._scenario(folder, [sys.executable, "-c", "pass"], [{
                    "name": "test-server", "source": {"kind": "local", "path": "server"},
                    "skills_root": "skills", "launch": [sys.executable, "-m", "server"],
                }])

    def test_duplicate_skills_from_prepared_servers_fail_before_trials(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            prepared = []
            for name in ("first", "second"):
                source = root / name
                skill = source / "skills" / "shared"
                skill.mkdir(parents=True)
                (skill / "SKILL.md").write_text("---\nname: shared\n---\n", encoding="utf-8")
                prepared.append(({"name": name, "skills_root": "skills"}, source))
            with self.assertRaisesRegex(PreflightError, "bundles skill 'shared'"):
                check_prepared_skills({"codex": prepared})

    def test_docker_access_checks_the_daemon_once(self):
        with tempfile.TemporaryDirectory() as temporary:
            scenario = self._scenario(Path(temporary), [sys.executable, "-c", "pass"],
                                      docker_access=True)
            with patch("agent_evals.preflight.shutil.which", return_value=sys.executable), \
                 patch("agent_evals.preflight.subprocess.run") as run:
                run.return_value = subprocess.CompletedProcess([], 0, "linux\n", "")
                check_preflight(scenario)
            run.assert_called_once_with(
                ["docker", "info", "--format", "{{.OSType}}"],
                capture_output=True, text=True, timeout=15,
            )

    def test_docker_build_checks_the_daemon_even_without_agent_docker_access(self):
        with tempfile.TemporaryDirectory() as temporary:
            scenario = self._scenario(Path(temporary), [sys.executable, "-c", "pass"],
                                      [{"name": "server", "build": ["docker", "build", "."],
                                        "launch": [sys.executable, "-m", "server"]}])
            with patch("agent_evals.preflight.shutil.which", return_value=sys.executable), \
                 patch("agent_evals.preflight.subprocess.run") as run:
                run.return_value = subprocess.CompletedProcess([], 1, "", "Cannot connect")
                with self.assertRaisesRegex(PreflightError, "Docker daemon is unavailable: Cannot connect"):
                    check_preflight(scenario)


if __name__ == "__main__":
    unittest.main()
