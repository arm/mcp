# Copyright © 2026, Arm Limited and Contributors. All rights reserved.
"""Exercise comparison reporting from saved trial records without an agent run."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_evals.report import write_report


class ReportTests(unittest.TestCase):
    def test_partial_comparison_counts_and_pass_only_means(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            (output / "run.json").write_text(json.dumps({
                "scenario_id": "sample", "started_at": "2026-11-04T12:00:00+00:00",
                "repetitions": 4,
            }), encoding="utf-8")
            (output / "scenario.json").write_text(json.dumps({
                "schema_version": 1, "id": "sample",
                "task": {"request": "Migrate the code.", "inputs": [
                    {"id": "code", "kind": "git", "repository": "https://example.invalid/repo",
                     "revision": "main"},
                ], "verifier": {"command": ["python3", "verify.py"]}},
                "run": {"execution_target": "local", "repetitions": 4,
                        "agent_timeout_seconds": 30},
                "configurations": [
                    {"id": "standalone", "agent": {"kind": "codex", "model": "test"}},
                    {"id": "with-mcp", "agent": {"kind": "codex", "model": "test"}},
                ],
            }), encoding="utf-8")

            def trial(config: str, repeat: int, agent_status: str,
                      verifier_status: str | None, elapsed: float | None,
                      tokens: int | None, benchmark: float | None = None) -> dict:
                trial_id = f"code+{config}+{repeat:03d}"
                verifier = None
                if verifier_status is not None:
                    result = {"success": verifier_status == "passed"}
                    if benchmark is not None or (config == "standalone" and repeat == 2):
                        result["application_execution_seconds"] = benchmark
                    verifier = {"status": verifier_status, "result": result}
                return {
                    "trial_id": trial_id, "input_id": "code",
                    "configuration_id": config, "repeat": repeat,
                    "agent": {
                        "status": agent_status, "elapsed_seconds": elapsed,
                        "usage": {"total_tokens": tokens} if tokens is not None else None,
                        "trace": "agent.jsonl", "stderr": "agent.stderr.txt",
                        "final_answer": "final.txt" if agent_status == "completed" else None,
                    },
                    "patch": "changes.patch", "verifier": verifier,
                    "status": verifier_status if agent_status == "completed" else agent_status,
                }

            records = [
                trial("standalone", 1, "completed", "passed", 10.0, 100, 2.0),
                trial("standalone", 2, "completed", "passed", 20.0, None),
                trial("standalone", 3, "completed", "failed", 30.0, 300),
                trial("standalone", 4, "launch_error", None, None, None),
                trial("with-mcp", 1, "completed", "passed", 5.0, 200, 3.0),
                trial("with-mcp", 2, "timeout", "passed", 40.0, 400, 0.5),
                trial("with-mcp", 3, "completed", "error", 50.0, 500),
            ]
            (output / "results.jsonl").write_text(
                "".join(json.dumps(record) + "\n" for record in records),
                encoding="utf-8",
            )
            first = output / "trials" / records[0]["trial_id"]
            first.mkdir(parents=True)
            for name in ("result.json", "agent.jsonl", "changes.patch", "verifier.log",
                         "verifier.json"):
                (first / name).write_text("evidence\n", encoding="utf-8")
            setup = output / "setup-logs"
            setup.mkdir()
            (setup / "build-arm.log").write_text("setup\n", encoding="utf-8")

            report = write_report(output)

            self.assertEqual(
                {key: report[key] for key in (
                    "planned", "recorded", "not_recorded", "scored", "unscored",
                    "passing", "end_to_end_success_rate",
                )},
                {"planned": 8, "recorded": 7, "not_recorded": 1,
                 "scored": 5, "unscored": 2, "passing": 3,
                 "end_to_end_success_rate": 3 / 5},
            )
            self.assertEqual(report["scenario_id"], "sample")
            self.assertEqual(
                (report["verifier_scored"], report["verifier_passing"],
                 report["verifier_pass_rate"]), (5, 4, 4 / 5)
            )
            self.assertEqual(report["failure_categories"], {
                "verifier_failed": 1, "agent_launch_error": 1,
                "agent_timeout": 1, "verifier_error": 1,
            })
            by_config = {item["id"]: item for item in report["configurations"]}
            standalone = by_config["standalone"]
            self.assertEqual((standalone["planned"], standalone["recorded"],
                              standalone["scored"], standalone["unscored"],
                              standalone["passing"]), (4, 4, 3, 1, 2))
            self.assertAlmostEqual(standalone["end_to_end_success_rate"], 2 / 3)
            self.assertEqual(standalone["metrics"]["agent_elapsed_seconds"],
                             {"mean": 15.0, "samples": 2, "missing": 0})
            self.assertEqual(standalone["metrics"]["total_tokens"],
                             {"mean": 100.0, "samples": 1, "missing": 1})
            self.assertEqual(standalone["metrics"]["application_execution_seconds"],
                             {"mean": 2.0, "samples": 1, "missing": 1,
                              "applicable": True})
            with_mcp = by_config["with-mcp"]
            self.assertEqual((with_mcp["planned"], with_mcp["recorded"],
                              with_mcp["not_recorded"], with_mcp["scored"],
                              with_mcp["unscored"], with_mcp["passing"]),
                             (4, 3, 1, 2, 1, 1))
            self.assertEqual(with_mcp["end_to_end_success_rate"], 0.5)
            self.assertEqual(
                (with_mcp["verifier_scored"], with_mcp["verifier_passing"],
                 with_mcp["verifier_pass_rate"]), (2, 2, 1.0)
            )
            self.assertEqual(with_mcp["metrics"]["total_tokens"]["mean"], 200.0)
            self.assertEqual(with_mcp["metrics"]["agent_elapsed_seconds"],
                             {"mean": 5.0, "samples": 1, "missing": 0})
            self.assertEqual(with_mcp["metrics"]["application_execution_seconds"],
                             {"mean": 1.75, "samples": 2, "missing": 0,
                              "applicable": True})
            self.assertAlmostEqual(
                report["metrics"]["application_execution_seconds"]["mean"],
                (2.0 + 3.0 + 0.5) / 3,
            )
            timed_out = next(item for item in report["trials"]
                             if item["trial_id"] == records[5]["trial_id"])
            self.assertEqual(
                (timed_out["agent_status"], timed_out["verifier_status"],
                 timed_out["classification"], timed_out["failure_category"]),
                ("timeout", "passed", "failed", "agent_timeout"),
            )
            self.assertEqual(json.loads((output / "report.json").read_text()), report)
            summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
            self.assertEqual((summary["failed"], summary["unscored"],
                              summary["not_recorded"], summary["verifier_passed"],
                              summary["verifier_scored"]), (2, 2, 1, 4, 5))
            markdown = (output / "report.md").read_text(encoding="utf-8")
            self.assertIn("End-to-end success rate", markdown)
            self.assertIn("Verifier pass rate", markdown)
            self.assertIn("including timed-out agents.", markdown)
            self.assertIn("| timeout | passed | failed (agent_timeout) |", markdown)
            for artifact in ("agent.jsonl", "changes.patch", "verifier.log",
                             "build-arm.log"):
                self.assertIn(artifact, markdown)

    def test_stopped_agent_is_unscored_without_a_verifier(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            (output / "run.json").write_text(json.dumps({
                "scenario_id": "interrupted", "repetitions": 1,
            }), encoding="utf-8")
            (output / "scenario.json").write_text(json.dumps({
                "id": "interrupted",
                "task": {"request": "Example", "verifier": {"command": ["python3", "verify.py"]}},
                "configurations": [{"id": "with-mcp"}],
            }), encoding="utf-8")
            stopped = {
                "trial_id": "task+with-mcp+001", "input_id": "task",
                "configuration_id": "with-mcp", "repeat": 1,
                "agent": {"status": "failed", "exit_code": -15,
                          "elapsed_seconds": 1251.087,
                          "usage": {"total_tokens": None},
                          "trace": "agent.jsonl", "final_answer": None},
                "verifier": None, "status": "failed",
            }
            (output / "results.jsonl").write_text(
                json.dumps(stopped) + "\n", encoding="utf-8",
            )

            report = write_report(output)

            self.assertEqual((report["planned"], report["recorded"],
                              report["scored"], report["unscored"],
                              report["passing"]), (1, 1, 0, 1, 0))
            self.assertIsNone(report["end_to_end_success_rate"])
            self.assertEqual(report["failure_categories"], {"agent_interrupted": 1})
            self.assertEqual(report["trials"][0]["classification"], "unscored")
            self.assertEqual(report["trials"][0]["failure_category"], "agent_interrupted")


if __name__ == "__main__":
    unittest.main()
