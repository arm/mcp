# Copyright © 2026, Arm Limited and Contributors. All rights reserved.
"""Validate codebase inputs and request-only scenarios."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_evals import ScenarioError, load_scenario, planned_trials

HERE = Path(__file__).resolve().parents[1]
MEGAHIT = HERE / "scenarios" / "megahit-arm64" / "scenario.json"


def question_document():
    return {
        "schema_version": 1, "id": "questions",
        "task": {
            "request": "What is SVE? Answer with sources.",
            "verifier": {"command": ["python3", "judge.py"]},
        },
        "run": {"execution_target": "local", "repetitions": 2, "agent_timeout_seconds": 300},
        "configurations": [{"id": "another-agent", "agent": {"kind": "example", "model": "example"}}],
    }


class ScenarioTests(unittest.TestCase):
    def load_question(self, document, setup=None):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            if setup:
                setup(folder)
            path = folder / "scenario.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            return load_scenario(path)

    def test_megahit_plan_and_server_source(self):
        scenario = load_scenario(MEGAHIT)
        trials = list(planned_trials(scenario))
        self.assertEqual(len(trials), 20)
        self.assertEqual(trials[0]["trial_id"], "megahit-v1.2.9+codex-standalone+001")
        self.assertEqual([t["configuration_id"] for t in trials[:4]],
                         ["codex-standalone", "codex-arm-mcp", "codex-arm-mcp", "codex-standalone"])
        self.assertNotIn("mcp_servers", scenario.configurations[0])
        variant = scenario.configurations[1]
        self.assertEqual(variant["prompt"], "../../../agent-integrations/codex/arm-migration.md")
        server = variant["mcp_servers"][0]
        self.assertEqual(server["source"], {
            "kind": "git",
            "repository": "https://github.com/arm/mcp.git",
            "revision": "5950b0f1f7f7a4f2a68347eb2119c858a3d7376d",
        })
        self.assertEqual(server["skills"], [
            "arm-container-inspect", "arm-migration-scan", "arm-assembly-analyze"
        ])
        verifier = scenario.document["task"]["verifier"]
        self.assertEqual(verifier, {"command": ["python3", "verify.py"]})

    def test_verifier_has_only_a_command(self):
        for name, value in (
            ("checks", ["accuracy"]),
            ("measures", ["application_execution_seconds"]),
            ("files", {"fixture": "input.json"}),
        ):
            with self.subTest(field=name):
                document = question_document()
                document["task"]["verifier"][name] = value
                with self.assertRaises(ScenarioError):
                    self.load_question(document)

    def test_questions_need_no_codebase_or_mcp(self):
        scenario = self.load_question(question_document())
        trials = list(planned_trials(scenario))
        self.assertEqual(len(trials), 2)
        self.assertEqual(trials[0]["input_id"], "task")
        self.assertNotIn("inputs", scenario.document["task"])
        self.assertNotIn("prompt", scenario.configurations[0])
        self.assertNotIn("mcp_servers", scenario.configurations[0])

    def test_configuration_environment_rejects_reserved_variables(self):
        for name in ("HOME", "home", "CODEX_HOME", "CoDeX_HoMe", "TMPDIR",
                     "DOCKER_HOST", "PATH", "PaTh"):
            with self.subTest(name=name):
                document = question_document()
                document["configurations"][0]["environment"] = {name: "/tmp/unsafe"}
                with self.assertRaisesRegex(ScenarioError, "reserved variable"):
                    self.load_question(document)

        document = question_document()
        document["configurations"][0]["environment"] = {"ARM_MCP_IMAGE": "candidate"}
        self.load_question(document)

    def test_text_input_kind_is_rejected(self):
        document = question_document()
        document["task"]["inputs"] = [{"id": "q1", "kind": "text", "text": "What is SME?"}]
        with self.assertRaises(ScenarioError):
            self.load_question(document)

    def test_multiple_git_inputs_plan_separately(self):
        document = question_document()
        document["task"]["inputs"] = [
            {"id": "repo-a", "kind": "git", "repository": "https://example.invalid/a", "revision": "main"},
            {"id": "repo-b", "kind": "git", "repository": "https://example.invalid/b", "revision": "main"},
        ]
        scenario = self.load_question(document)
        self.assertEqual(len(list(planned_trials(scenario))), 4)

    def test_local_input_accepts_directory_without_git(self):
        document = question_document()
        document["task"]["inputs"] = [{"id": "local", "kind": "local", "path": "checkout"}]
        def setup(folder):
            (folder / "checkout").mkdir()
        scenario = self.load_question(document, setup)
        self.assertEqual(scenario.inputs[0]["kind"], "local")

    def test_code_inputs_reject_input_specific_text(self):
        def setup(folder):
            (folder / "checkout").mkdir()

        inputs = (
            {"id": "repo", "kind": "git", "repository": "https://github.com/voutcn/megahit.git",
             "revision": "d729cca1e201ca16749b67f750b0bc5465c9a990", "text": "Extra instruction"},
            {"id": "local", "kind": "local", "path": "checkout", "text": "Extra instruction"},
        )
        for task_input in inputs:
            with self.subTest(kind=task_input["kind"]):
                document = question_document()
                document["task"]["inputs"] = [task_input]
                with self.assertRaises(ScenarioError):
                    self.load_question(document, setup)

    def test_local_server_source_needs_no_git(self):
        document = question_document()
        document["configurations"][0].update({
            "prompt": "prompt.md",
            "mcp_servers": [{
                "name": "local-server",
                "source": {"kind": "local", "path": "assets"},
                "launch": ["python3", "-m", "local_server"],
            }],
        })
        def setup(folder):
            (folder / "assets").mkdir()
            (folder / "prompt.md").write_text("Answer carefully.", encoding="utf-8")
        scenario = self.load_question(document, setup)
        self.assertEqual(scenario.configurations[0]["mcp_servers"][0]["source"]["kind"], "local")

    def test_multiple_mcp_servers_can_use_different_sources(self):
        document = question_document()
        document["configurations"][0]["mcp_servers"] = [
            {
                "name": "arm-mcp",
                "source": {"kind": "git", "repository": "https://github.com/arm/mcp.git", "revision": "main"},
                "skills": ["arm-migration-scan"],
                "launch": ["python3", "-m", "arm_mcp"],
            },
            {
                "name": "local-helper",
                "source": {"kind": "local", "path": "helper"},
                "skills": ["helper-skill"],
                "launch": ["python3", "-m", "helper"],
            },
        ]
        def setup(folder):
            (folder / "helper").mkdir()
        scenario = self.load_question(document, setup)
        servers = scenario.configurations[0]["mcp_servers"]
        self.assertEqual([server["source"]["kind"] for server in servers], ["git", "local"])
        self.assertEqual(servers[0]["skills"], ["arm-migration-scan"])
        self.assertEqual(servers[1]["skills"], ["helper-skill"])

    def test_mcp_server_name_rejects_dot(self):
        document = question_document()
        document["configurations"][0]["mcp_servers"] = [{
            "name": "arm.mcp",
            "launch": ["python3", "-m", "arm_mcp"],
        }]
        with self.assertRaisesRegex(ScenarioError, "arm.mcp"):
            self.load_question(document)

    def test_mcp_servers_reject_http_configuration(self):
        for field, value in (
            ("url", "http://127.0.0.1:8000/mcp"),
            ("stop", ["docker", "stop", "arm-mcp"]),
        ):
            with self.subTest(field=field):
                document = question_document()
                document["configurations"][0]["mcp_servers"] = [{
                    "name": "local-server",
                    "source": {"kind": "local", "path": "assets"},
                    "launch": ["python3", "-m", "local_server"],
                    field: value,
                }]

                def setup(folder):
                    (folder / "assets").mkdir()

                with self.assertRaisesRegex(ScenarioError, field):
                    self.load_question(document, setup)

    def test_prompt_is_local_even_with_git_server_source(self):
        document = question_document()
        document["configurations"][0].update({
            "prompt": "prompt.md",
            "mcp_servers": [{
                "name": "arm-mcp",
                "source": {"kind": "git", "repository": "https://github.com/arm/mcp.git", "revision": "main"},
                "launch": ["python3", "-m", "arm_mcp"],
            }],
        })
        with self.assertRaises(ScenarioError):
            self.load_question(document)
        def setup(folder):
            (folder / "prompt.md").write_text("Use the Arm server.", encoding="utf-8")
        scenario = self.load_question(document, setup)
        self.assertEqual(scenario.configurations[0]["prompt"], "prompt.md")

    def test_configuration_source_and_skills_are_rejected(self):
        for field, value in (
            ("source", {"kind": "git", "repository": "https://github.com/arm/mcp.git", "revision": "main"}),
            ("skills", ["arm-migration-scan"]),
        ):
            with self.subTest(field=field):
                document = question_document()
                document["configurations"][0][field] = value
                with self.assertRaises(ScenarioError):
                    self.load_question(document)

    def test_prompt_object_is_rejected(self):
        document = question_document()
        document["configurations"][0]["prompt"] = {"path": "prompt.md"}
        with self.assertRaises(ScenarioError):
            self.load_question(document)

    def test_duplicate_configuration_is_rejected(self):
        document = question_document()
        document["configurations"].append(document["configurations"][0].copy())
        with self.assertRaisesRegex(ScenarioError, "duplicate configuration"):
            self.load_question(document)

    def test_unknown_field_is_rejected(self):
        document = question_document()
        document["task"]["repository"] = "unexpected"
        with self.assertRaises(ScenarioError):
            self.load_question(document)

    def test_request_and_request_file_are_mutually_exclusive(self):
        document = question_document()
        document["task"]["request_file"] = "extra-request.md"
        with self.assertRaises(ScenarioError):
            self.load_question(document)

    def test_request_file_cannot_escape_scenario_directory(self):
        document = question_document()
        del document["task"]["request"]
        document["task"]["request_file"] = "../outside.md"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "outside.md").write_text("Existing request.", encoding="utf-8")
            scenario_dir = root / "scenario"
            scenario_dir.mkdir()
            path = scenario_dir / "scenario.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ScenarioError, "must stay within"):
                load_scenario(path)

    def test_local_input_directory_is_checked(self):
        document = question_document()
        document["task"]["inputs"] = [{"id": "local", "kind": "local", "path": "missing"}]
        with self.assertRaises(ScenarioError):
            self.load_question(document)


if __name__ == "__main__":
    unittest.main()
