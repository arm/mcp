# Copyright © 2026, Arm Limited and Contributors. All rights reserved.
"""Exercise one complete local run without network or Codex credentials."""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import unittest
from functools import partial
from pathlib import Path
from unittest.mock import Mock, call, patch

from agent_evals import Scenario, load_scenario
from agent_evals.codex_adapter import (
    _docker_socket, _write_provider_config, run_codex,
    run_codex_trial, tomllib,
)
from agent_evals.runner import RunnerError, _command, _patch, _stop_process_group, _verify, run_scenario


class RunnerTests(unittest.TestCase):
    def test_timeout_still_verifies_saved_workspace(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            check = (
                "import os, pathlib, sys\n"
                "workspace = pathlib.Path(os.environ['AGENT_EVAL_WORKSPACE'])\n"
                "sys.exit(0 if (workspace / 'working.txt').is_file() else 1)\n"
            )
            document = {
                "schema_version": 1, "id": "timeout-check",
                "task": {"request": "Create working.txt.",
                         "verifier": {"command": [sys.executable, "-c", check]}},
                "run": {"execution_target": "local", "repetitions": 1,
                        "agent_timeout_seconds": 30},
                "configurations": [
                    {"id": "standalone", "agent": {"kind": "test-agent", "model": "test"}}
                ],
            }
            scenario_path = root / "scenario.json"
            scenario_path.write_text(json.dumps(document), encoding="utf-8")

            def timed_out_agent(configuration, servers, workspace, trial_dir, prompt,
                                timeout_seconds, *, docker_access=False):
                (workspace / "working.txt").write_text("done\n", encoding="utf-8")
                return ({"status": "timeout", "elapsed_seconds": 30.0,
                         "usage": None, "trace": None, "final_answer": None}, [])

            output = root / "output"
            summary = run_scenario(
                load_scenario(scenario_path), output, adapters={"test-agent": timed_out_agent}
            )
            result_path = next((output / "trials").glob("*/result.json"))
            result = json.loads(result_path.read_text(encoding="utf-8"))
            self.assertEqual(result["agent"]["status"], "timeout")
            self.assertEqual(result["verifier"]["status"], "passed")
            self.assertEqual(result["status"], "timeout")
            self.assertEqual(summary["passed"], 0)

    def test_patch_respects_gitignore_and_captures_other_new_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repository"
            repository.mkdir()
            subprocess.run(["git", "init", "-q", str(repository)], check=True)
            (repository / ".gitignore").write_text("ignored-output/\n", encoding="utf-8")
            (repository / "tracked.cpp").write_text("int old_value = 0;\n", encoding="utf-8")
            build = repository / "build-arm"
            build.mkdir()
            (build / "tracked.txt").write_text("old\n", encoding="utf-8")
            subprocess.run(["git", "add", ".gitignore", "tracked.cpp", "build-arm/tracked.txt"],
                           cwd=repository, check=True)
            subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
                            "commit", "-qm", "initial"], cwd=repository, check=True)
            baseline = subprocess.check_output(["git", "rev-parse", "HEAD"],
                                               cwd=repository, text=True).strip()
            (repository / "tracked.cpp").write_text("int old_value = 1;\n", encoding="utf-8")
            (build / "tracked.txt").write_text("new\n", encoding="utf-8")
            (repository / "new_feature.cpp").write_text("int new_value = 2;\n", encoding="utf-8")
            (build / "CMakeCache.txt").write_text("generated cache\n", encoding="utf-8")
            (build / "megahit_core").write_bytes(b"generated binary")
            other = repository / "other-output"
            other.mkdir()
            (other / "CMakeCache.txt").write_text("not excluded\n", encoding="utf-8")
            ignored = repository / "ignored-output"
            ignored.mkdir()
            (ignored / "CMakeCache.txt").write_text("ignored by Git\n", encoding="utf-8")

            patch_name = _patch(repository, baseline, root)
            patch_text = (root / patch_name).read_text(encoding="utf-8")

            self.assertIn("tracked.cpp", patch_text)
            self.assertIn("build-arm/tracked.txt", patch_text)
            self.assertIn("new_feature.cpp", patch_text)
            self.assertIn("other-output/CMakeCache.txt", patch_text)
            self.assertIn("build-arm/CMakeCache.txt", patch_text)
            self.assertIn("build-arm/megahit_core", patch_text)
            self.assertNotIn("ignored-output/CMakeCache.txt", patch_text)

    def test_non_codex_kind_selects_its_adapter(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            verify_script = (
                "import os, pathlib, sys\n"
                "workspace = pathlib.Path(os.environ['AGENT_EVAL_WORKSPACE'])\n"
                "sys.exit(0 if (workspace / 'agent-output.txt').is_file() else 1)\n"
            )
            document = {
                "schema_version": 1, "id": "other-agent",
                "task": {
                    "request": "Answer the question.",
                    "verifier": {"command": [sys.executable, "-c", verify_script]},
                },
                "run": {"execution_target": "local", "repetitions": 1,
                        "agent_timeout_seconds": 30, "docker_access": True},
                "configurations": [
                    {"id": "other", "agent": {"kind": "other-agent", "model": "test"}}
                ],
            }
            path = root / "scenario.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            calls = []

            def run_other(configuration, servers, workspace, trial_dir, prompt,
                          timeout_seconds, *, docker_access=False):
                calls.append((configuration["agent"]["kind"], servers, prompt,
                              timeout_seconds, docker_access))
                (workspace / "agent-output.txt").write_text("done", encoding="utf-8")
                return ({"status": "completed", "elapsed_seconds": 0.1, "usage": None,
                         "trace": None, "final_answer": None}, [])

            output = root / "output"
            progress = []
            summary = run_scenario(load_scenario(path), output,
                                   adapters={"other-agent": run_other},
                                   progress=progress.append)
            self.assertEqual((summary["trials"], summary["passed"]), (1, 1))
            self.assertTrue(any("[1/1] task+other+001: running other-agent" in message
                                for message in progress))
            self.assertTrue(any("[1/1] task+other+001: verifier passed" in message
                                for message in progress))
            self.assertEqual(calls, [("other-agent", [], "Answer the question.\n",
                                      30, True)])
            result = json.loads((output / "trials" / "task+other+001" /
                                 "result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["skills"], [])

    def test_unsupported_agent_kind_fails_before_creating_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            document = {
                "schema_version": 1, "id": "unknown-agent",
                "task": {
                    "request": "Answer the question.",
                    "verifier": {"command": [sys.executable, "-c", "pass"]},
                },
                "run": {"execution_target": "local", "repetitions": 1,
                        "agent_timeout_seconds": 30},
                "configurations": [
                    {"id": "other", "agent": {"kind": "unknown-agent", "model": "test"}}
                ],
            }
            path = root / "scenario.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            output = root / "output"
            with self.assertRaisesRegex(RunnerError, "agent kind"):
                run_scenario(load_scenario(path), output)
            self.assertFalse(output.exists())

    def test_docker_access_resolves_an_explicit_unix_socket(self):
        with tempfile.TemporaryDirectory() as temporary, socket.socket(socket.AF_UNIX) as listener:
            path = Path(temporary) / "docker.sock"
            listener.bind(str(path))
            with patch.dict(os.environ, {"DOCKER_HOST": f"unix://{path}"}):
                self.assertEqual(_docker_socket(), path.resolve())

    def test_docker_stdio_mcp_receives_socket_without_exposing_it_to_other_servers(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_codex = root / "fake-codex"
            fake_codex.write_text(
                f"#!{sys.executable}\n"
                "import json, os, sys\nfrom pathlib import Path\n"
                "args = sys.argv[1:]\n"
                "configs = dict(args[i + 1].split('=', 1) for i, arg in enumerate(args[:-1]) "
                "if arg == '-c')\n"
                "capture = Path(args[args.index('-o') + 1]).with_name('capture.json')\n"
                "capture.write_text(json.dumps({'docker_host': os.environ.get('DOCKER_HOST'), "
                "'env_vars': configs.get('mcp_servers.test.env_vars')}))\n"
                "sys.stdin.read()\n"
                "print(json.dumps({'type': 'turn.completed', 'usage': "
                "{'input_tokens': 1, 'output_tokens': 1}}))\n",
                encoding="utf-8",
            )
            fake_codex.chmod(0o755)
            socket_path = root / "docker.sock"
            config = {
                "agent": {"kind": "codex", "model": "test"},
                "environment": {"ARM_MCP_IMAGE": "test-image"},
            }
            with patch("agent_evals.codex_adapter._docker_socket", return_value=socket_path):
                for command in ("docker", "python3"):
                    with self.subTest(command=command):
                        trial = root / command
                        workspace = trial / "workspace"
                        workspace.mkdir(parents=True)
                        server = {"name": "test", "launch": [command, "serve"]}
                        result = run_codex(
                            config, [(server, root)], workspace, trial, "Test.", 10,
                            docker_access=True, executable=str(fake_codex),
                        )
                        self.assertEqual(result["status"], "completed")
                        capture = json.loads((trial / "capture.json").read_text(encoding="utf-8"))
                        self.assertEqual(capture["docker_host"], f"unix://{socket_path}")
                        env_vars = json.loads(capture["env_vars"])
                        expected = ["ARM_MCP_IMAGE", "DOCKER_HOST"] if command == "docker" else ["ARM_MCP_IMAGE"]
                        self.assertEqual(env_vars, expected)

    def test_verifier_setup_error_is_not_a_task_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            trial = root / "trial"
            trial.mkdir()
            script = (
                "import json, os\n"
                "from pathlib import Path\n"
                "Path(os.environ['AGENT_EVAL_VERIFIER_RESULT']).write_text("
                "json.dumps({'success': False, 'stage': 'setup'}))\n"
                "raise SystemExit(2)\n"
            )
            scenario = Scenario(
                path=root / "scenario.json",
                document={"task": {"verifier": {"command": [sys.executable, "-c", script]}}},
                request="",
            )
            result = _verify(scenario, root, trial)
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["result"]["stage"], "setup")

    def test_signal_terminated_verifier_is_unscored(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            trial = root / "trial"
            trial.mkdir()
            scenario = Scenario(
                path=root / "scenario.json",
                document={"task": {"verifier": {"command": [
                    sys.executable, "-c", "import os, signal; os.kill(os.getpid(), signal.SIGTERM)",
                ]}}},
                request="",
            )
            result = _verify(scenario, root, trial)
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["exit_code"], -15)

    def test_interrupted_command_stops_process_group(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with patch("agent_evals.runner.subprocess.Popen") as popen, \
                 patch("agent_evals.runner._stop_process_group") as stop_group:
                process = popen.return_value
                process.wait.side_effect = KeyboardInterrupt
                process.pid = 12345
                with self.assertRaises(KeyboardInterrupt):
                    _command(["example"], root, root / "command.log")
                stop_group.assert_called_once_with(process)

    def test_stopping_process_group_escalates_after_grace_period(self):
        process = Mock(pid=12345)
        process.wait.side_effect = [subprocess.TimeoutExpired("example", 35), 0]
        with patch("agent_evals.runner.os.killpg") as killpg:
            _stop_process_group(process)
        self.assertEqual(killpg.call_args_list, [
            call(12345, signal.SIGTERM), call(12345, signal.SIGKILL),
        ])
        self.assertEqual(process.wait.call_args_list, [call(timeout=35), call()])

    def test_stopping_process_group_clears_surviving_children(self):
        process = Mock(pid=12345)
        process.wait.return_value = 0
        with patch("agent_evals.runner.os.killpg") as killpg:
            _stop_process_group(process)
        self.assertEqual(killpg.call_args_list, [
            call(12345, signal.SIGTERM), call(12345, signal.SIGKILL),
        ])

    def test_server_snapshots_do_not_collide_for_hyphenated_ids(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "server"
            source.mkdir()
            (source / "marker.txt").write_text("source", encoding="utf-8")
            configurations = [
                {"id": "a-b", "agent": {"kind": "test-agent", "model": "test"},
                 "mcp_servers": [{"name": "c", "source": {"kind": "local", "path": str(source)},
                                  "launch": ["true"]}]},
                {"id": "a", "agent": {"kind": "test-agent", "model": "test"},
                 "mcp_servers": [{"name": "b-c", "source": {"kind": "local", "path": str(source)},
                                  "launch": ["true"]}]},
            ]
            document = {
                "schema_version": 1, "id": "distinct-sources",
                "task": {"request": "Answer.", "verifier": {"command": [sys.executable, "-c", "pass"]}},
                "run": {"execution_target": "local", "repetitions": 1,
                        "agent_timeout_seconds": 30},
                "configurations": configurations,
            }
            scenario_path = root / "scenario.json"
            scenario_path.write_text(json.dumps(document), encoding="utf-8")

            def run_agent(configuration, servers, workspace, trial_dir, prompt,
                          timeout_seconds, *, docker_access=False):
                return ({"status": "completed", "elapsed_seconds": 0.1,
                         "usage": None, "trace": None, "final_answer": None}, [])

            output = root / "output"
            run_scenario(load_scenario(scenario_path), output,
                         adapters={"test-agent": run_agent})
            self.assertTrue((output / "sources" / "server-a-b+c" / "marker.txt").is_file())
            self.assertTrue((output / "sources" / "server-a+b-c" / "marker.txt").is_file())

    def test_isolated_codex_config_keeps_provider_but_not_user_servers(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = root / "original"
            isolated = root / "isolated"
            original.mkdir()
            isolated.mkdir()
            (original / "config.toml").write_text(
                'model_provider = "proxy"\n'
                '[model_providers.proxy]\n'
                'name = "proxy"\n'
                'base_url = "https://example.invalid/api"\n'
                'wire_api = "responses"\n'
                'requires_openai_auth = true\n'
                '[mcp_servers.other]\n'
                'command = "false"\n'
                '[plugins."other@example"]\n'
                'enabled = true\n', encoding="utf-8",
            )
            _write_provider_config(original, isolated)
            with (isolated / "config.toml").open("rb") as file:
                config = tomllib.load(file)
            self.assertEqual(set(config), {"model_provider", "model_providers"})
            self.assertEqual(config["model_provider"], "proxy")
            self.assertEqual(config["model_providers"]["proxy"]["base_url"],
                             "https://example.invalid/api")

    def test_git_comparison_keeps_workspaces_and_artifacts_separate(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = root / "repository"
            repository.mkdir()
            subprocess.run(["git", "init", "-q", str(repository)], check=True)
            (repository / "README.md").write_text("original\n", encoding="utf-8")
            subprocess.run(["git", "add", "README.md"], cwd=repository, check=True)
            subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=test@example.com",
                            "commit", "-qm", "initial"], cwd=repository, check=True)
            revision = subprocess.check_output(["git", "rev-parse", "HEAD"],
                                               cwd=repository, text=True).strip()

            server_source = root / "server"
            skill = server_source / "skills" / "example-skill"
            skill.mkdir(parents=True)
            (skill / "SKILL.md").write_text("---\nname: example-skill\n"
                                                  "description: Test skill\n---\nDo work.\n",
                                                  encoding="utf-8")

            scenario_dir = root / "scenario"
            scenario_dir.mkdir()
            (scenario_dir / "prompt.md").write_text("Use the selected skill.", encoding="utf-8")
            (scenario_dir / "verify.py").write_text(
                "import json, os\nfrom pathlib import Path\n"
                "workspace = Path(os.environ['AGENT_EVAL_WORKSPACE'])\n"
                "source = Path(os.environ['AGENT_EVAL_INPUT_SOURCE'])\n"
                "passed = (workspace / 'agent-output.txt').is_file() and (source / 'README.md').read_text() == 'original\\n'\n"
                "Path(os.environ['AGENT_EVAL_VERIFIER_RESULT']).write_text("
                "json.dumps({'success': passed, 'application_execution_seconds': 1.5}))\n"
                "raise SystemExit(0 if passed else 1)\n", encoding="utf-8",
            )
            document = {
                "schema_version": 1, "id": "local-smoke",
                "task": {"request": "Update the project.", "inputs": [{
                    "id": "repo", "kind": "git", "repository": str(repository),
                    "revision": revision,
                }], "verifier": {"command": [sys.executable, "verify.py"]}},
                "run": {"execution_target": "local", "repetitions": 1,
                        "agent_timeout_seconds": 30},
                "configurations": [
                    {"id": "standalone", "agent": {"kind": "codex", "model": "test"}},
                    {"id": "with-mcp", "agent": {"kind": "codex", "model": "test"},
                     "prompt": "prompt.md", "mcp_servers": [{
                         "name": "test-server", "source": {"kind": "local", "path": str(server_source)},
                         "skills": ["example-skill"], "enabled_tools": ["search"],
                         "build": [sys.executable, "-c",
                                   "from pathlib import Path; Path('built.txt').write_text('built')"],
                         "launch": [sys.executable, "-c", "print('server')"],
                     }]},
                ],
            }
            path = scenario_dir / "scenario.json"
            path.write_text(json.dumps(document), encoding="utf-8")

            fake_codex = root / "fake-codex"
            fake_codex.write_text(
                f"#!{sys.executable}\n"
                "import json, os, sys\nfrom pathlib import Path\n"
                "args = sys.argv[1:]\n"
                "workspace = Path(args[args.index('-C') + 1])\n"
                "answer = Path(args[args.index('-o') + 1])\n"
                "prompt = sys.stdin.read()\n"
                "assert '--ignore-user-config' not in args\n"
                "with_mcp = 'Use the selected skill.' in prompt\n"
                "skill = Path(os.environ['HOME']) / '.agents/skills/example-skill/SKILL.md'\n"
                "assert skill.is_file() == with_mcp\n"
                "assert any(arg.startswith('mcp_servers.test-server.command=') "
                "for arg in args) == with_mcp\n"
                "(workspace / 'agent-output.txt').write_text(prompt)\n"
                "(workspace / 'build-arm').mkdir()\n"
                "(workspace / 'build-arm/CMakeCache.txt').write_text('generated')\n"
                "answer.write_text('Finished.')\n"
                "print(json.dumps({'type': 'turn.completed', 'usage': "
                "{'input_tokens': 10, 'cached_input_tokens': 3, 'output_tokens': 4}}))\n",
                encoding="utf-8",
            )
            fake_codex.chmod(0o755)
            output = root / "output"
            summary = run_scenario(
                load_scenario(path), output,
                adapters={"codex": partial(run_codex_trial, executable=str(fake_codex))},
            )

            self.assertEqual((summary["trials"], summary["passed"]), (2, 2))
            standalone = output / "trials" / "repo+standalone+001"
            variant = output / "trials" / "repo+with-mcp+001"
            self.assertFalse((standalone / "profile" / ".agents" / "skills" /
                              "example-skill").exists())
            self.assertTrue((variant / "profile" / ".agents" / "skills" /
                             "example-skill" / "SKILL.md").is_file())
            self.assertTrue((output / "sources" / "server-with-mcp+test-server" /
                             "built.txt").is_file())
            result = json.loads((variant / "result.json").read_text(encoding="utf-8"))
            self.assertEqual(result["trial_id"], variant.name)
            self.assertEqual(result["agent"]["usage"]["total_tokens"], 14)
            self.assertEqual(result["verifier"]["result"]["application_execution_seconds"], 1.5)
            comparison = json.loads((output / "report.json").read_text(encoding="utf-8"))
            self.assertEqual((comparison["scored"], comparison["passing"]), (2, 2))
            sources = json.loads((output / "sources.json").read_text(encoding="utf-8"))
            self.assertEqual(sources["inputs"]["repo"]["commit"], revision)
            self.assertEqual(sources["mcp_servers"]["with-mcp"][0]["name"], "test-server")
            patch = (variant / "changes.patch").read_text(encoding="utf-8")
            self.assertIn("agent-output.txt", patch)
            self.assertNotIn("example-skill", patch)
            self.assertIn("build-arm/CMakeCache.txt", patch)


if __name__ == "__main__":
    unittest.main()
