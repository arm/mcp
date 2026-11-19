# Copyright © 2026, Arm Limited and Contributors. All rights reserved.
"""Developer-facing commands for checking, running, and reporting evaluations."""

from __future__ import annotations

import argparse
import json
import signal
import sys
from collections.abc import Sequence
from pathlib import Path

from .preflight import PreflightError, check_preflight
from .report import ReportError, write_report
from .runner import RunnerError, run_scenario
from .scenario import ScenarioError, load_scenario


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="arm-agent-evals",
        description="Check an evaluation, run it, or rebuild a report from saved results.",
    )
    commands = parser.add_subparsers(dest="command", required=True)

    preflight = commands.add_parser(
        "preflight", help="Check local prerequisites and summarize the planned run"
    )
    preflight.add_argument("scenario", help="Path to a scenario JSON file")
    preflight.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    run = commands.add_parser(
        "run", help="Run agents and verifiers, then save artifacts and a report"
    )
    run.add_argument("scenario", help="Path to a scenario JSON file")
    run.add_argument("--output", required=True, help="New directory for trial artifacts")
    run.add_argument("--repetitions", type=int, help="Run only the first N repetitions")

    report = commands.add_parser(
        "report", help="Rebuild a report from saved results without rerunning trials"
    )
    report.add_argument("output", help="Directory containing saved trial results")

    args = parser.parse_args(argv)
    if args.command == "report":
        try:
            comparison = write_report(Path(args.output))
        except (ReportError, OSError) as exc:
            print(f"Cannot create report: {exc}", file=sys.stderr)
            return 2
        print(json.dumps({
            "report": str(Path(args.output).expanduser().resolve() / "report.md"),
            "planned": comparison["planned"],
            "recorded": comparison["recorded"],
            "scored": comparison["scored"],
            "passing": comparison["passing"],
        }, indent=2))
        return 0

    try:
        scenario = load_scenario(args.scenario)
    except ScenarioError as exc:
        print(f"Invalid scenario: {exc}", file=sys.stderr)
        return 2
    try:
        checks = check_preflight(scenario)
    except PreflightError as exc:
        print(f"Preflight failed: {exc}", file=sys.stderr)
        return 2
    if args.command == "preflight":
        summary = {
            "scenario": scenario.id,
            "inputs": scenario.inputs,
            "configurations": [config["id"] for config in scenario.configurations],
            "repetitions": scenario.repetitions,
            "planned_trials": (len(scenario.inputs) * len(scenario.configurations)
                               * scenario.repetitions),
            "checks": ["Scenario schema and local references", *checks],
        }
        if args.json:
            print(json.dumps(summary, indent=2))
        else:
            print(f"Preflight passed: {summary['scenario']}")
            print("Checks passed:")
            for check in summary["checks"]:
                print(f"  {check}")
            print(f"Inputs ({len(summary['inputs'])}):")
            for task_input in summary["inputs"]:
                if task_input["kind"] == "git":
                    detail = f"{task_input['repository']} @ {task_input['revision']}"
                elif task_input["kind"] == "local":
                    detail = task_input["path"]
                else:
                    detail = "request only"
                print(f"  {task_input['id']}: {detail}")
            print(f"Configurations ({len(summary['configurations'])}):")
            for name in summary["configurations"]:
                print(f"  {name}")
            print(f"Plan: {summary['repetitions']} repetitions, "
                  f"{summary['planned_trials']} planned trials.", flush=True)
        return 0

    if args.command == "run":
        print("Preflight passed; source fetches and builds are checked by run.",
              file=sys.stderr)
        terminated = False

        def interrupt_on_sigterm(_signum: int, _frame: object) -> None:
            nonlocal terminated
            terminated = True
            raise KeyboardInterrupt

        previous_sigterm = signal.signal(signal.SIGTERM, interrupt_on_sigterm)
        try:
            try:
                summary = run_scenario(
                    scenario, Path(args.output), repetitions=args.repetitions,
                    progress=lambda message: print(message, file=sys.stderr, flush=True),
                )
            except (ReportError, RunnerError, OSError) as exc:
                print(f"Run failed: {exc}", file=sys.stderr)
                return 2
            except KeyboardInterrupt:
                print("Run interrupted", file=sys.stderr)
                return 128 + (signal.SIGTERM if terminated else signal.SIGINT)
        finally:
            signal.signal(signal.SIGTERM, previous_sigterm)
        print(json.dumps(summary, indent=2))
        return 0 if all(summary[key] == 0 for key in
                        ("failed", "unscored", "not_recorded")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
