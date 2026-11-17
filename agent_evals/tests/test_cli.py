# Copyright © 2026, Arm Limited and Contributors. All rights reserved.
"""Check that CLI termination reaches child-process cleanup and restores signals."""

from __future__ import annotations

import io
import json
import signal
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from agent_evals.cli import main
from agent_evals.preflight import PreflightError


class CliTests(unittest.TestCase):
    def test_preflight_prints_a_summary_instead_of_every_trial(self):
        scenario = SimpleNamespace(
            id="example",
            inputs=[
                {"id": "repo", "kind": "git", "repository": "https://example.test/repo.git",
                 "revision": "a" * 40},
                {"id": "local", "kind": "local", "path": "./source"},
            ],
            configurations=[{"id": "alone"}, {"id": "with-mcp"}], repetitions=3,
        )
        with patch("agent_evals.cli.load_scenario", return_value=scenario), \
             patch("agent_evals.cli.check_preflight", return_value=["Verifier executable"]), \
             redirect_stdout(io.StringIO()) as stdout, \
             redirect_stderr(io.StringIO()):
            exit_code = main(["preflight", "scenario.json"])
        self.assertEqual(exit_code, 0)
        output = stdout.getvalue()
        self.assertIn("Checks passed:\n  Scenario schema and local references\n  Verifier executable", output)
        self.assertIn("repo: https://example.test/repo.git @ " + "a" * 40, output)
        self.assertIn("local: ./source", output)
        self.assertIn("  alone\n", output)
        self.assertIn("  with-mcp\n", output)
        self.assertIn("12 planned trials", output)
        self.assertNotIn("+001", output)

    def test_preflight_json_is_a_summary(self):
        task_input = {"id": "task", "kind": "request"}
        scenario = SimpleNamespace(id="example", inputs=[task_input],
                                   configurations=[{"id": "alone"}, {"id": "with-mcp"}],
                                   repetitions=3)
        with patch("agent_evals.cli.load_scenario", return_value=scenario), \
             patch("agent_evals.cli.check_preflight", return_value=["Verifier executable"]), \
             redirect_stdout(io.StringIO()) as stdout, \
             redirect_stderr(io.StringIO()):
            exit_code = main(["preflight", "scenario.json", "--json"])
        self.assertEqual(exit_code, 0)
        self.assertEqual(json.loads(stdout.getvalue()), {
            "scenario": "example", "inputs": [task_input],
            "configurations": ["alone", "with-mcp"],
            "repetitions": 3, "planned_trials": 6,
            "checks": ["Scenario schema and local references", "Verifier executable"],
        })

    def test_run_stops_before_trials_when_preflight_fails(self):
        with patch("agent_evals.cli.load_scenario", return_value=object()), \
             patch("agent_evals.cli.check_preflight",
                   side_effect=PreflightError("missing verifier")), \
             patch("agent_evals.cli.run_scenario") as run_scenario, \
             redirect_stderr(io.StringIO()) as stderr:
            exit_code = main(["run", "scenario.json", "--output", "output"])
        self.assertEqual(exit_code, 2)
        self.assertIn("missing verifier", stderr.getvalue())
        run_scenario.assert_not_called()

    def test_sigterm_uses_interrupt_path_and_restores_handler(self):
        original_handler = signal.getsignal(signal.SIGTERM)

        def request_termination(*_args, **_kwargs):
            handler = signal.getsignal(signal.SIGTERM)
            self.assertTrue(callable(handler))
            handler(signal.SIGTERM, None)

        with patch("agent_evals.cli.load_scenario", return_value=object()), \
             patch("agent_evals.cli.check_preflight"), \
             patch("agent_evals.cli.run_scenario", side_effect=request_termination), \
             redirect_stderr(io.StringIO()) as stderr:
            exit_code = main(["run", "scenario.json", "--output", "output"])

        self.assertEqual(exit_code, 128 + signal.SIGTERM)
        self.assertIs(signal.getsignal(signal.SIGTERM), original_handler)
        self.assertIn("Run interrupted", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
