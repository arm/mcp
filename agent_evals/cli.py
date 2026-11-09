# Copyright © 2026, Arm Limited and Contributors. All rights reserved.
"""Developer-facing commands for checking and planning agent evaluations."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from .report import ReportError, write_report
from .runner import RunnerError, run_scenario
from .scenario import ScenarioError, load_scenario, planned_trials


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arm-agent-evals")
    commands = parser.add_subparsers(dest="command", required=True)

    validate = commands.add_parser("validate", help="Check a scenario without running agents")
    validate.add_argument("scenario", help="Path to a scenario JSON file")

    plan = commands.add_parser("plan", help="List the trials a scenario would run")
    plan.add_argument("scenario", help="Path to a scenario JSON file")
    plan.add_argument("--json", action="store_true", help="Print machine-readable JSON")

    run = commands.add_parser("run", help="Execute local trials and save their artifacts")
    run.add_argument("scenario", help="Path to a scenario JSON file")
    run.add_argument("--output", required=True, help="New directory for trial artifacts")
    run.add_argument("--repetitions", type=int, help="Run only the first N repetitions")

    report = commands.add_parser("report", help="Regenerate a comparison report from a saved run")
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

    if args.command == "run":
        try:
            summary = run_scenario(
                scenario, Path(args.output), repetitions=args.repetitions,
                progress=lambda message: print(message, file=sys.stderr, flush=True),
            )
        except (ReportError, RunnerError, OSError) as exc:
            print(f"Run failed: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(summary, indent=2))
        return 0 if all(summary[key] == 0 for key in
                        ("failed", "unscored", "not_recorded")) else 1

    trials = list(planned_trials(scenario))
    if args.command == "validate":
        print(
            f"Valid scenario {scenario.id}: "
            f"{len(scenario.inputs)} input(s), "
            f"{len(scenario.configurations)} configuration(s), "
            f"{len(trials)} planned trial(s)"
        )
        return 0

    if args.json:
        print(json.dumps(trials, indent=2))
    else:
        for trial in trials:
            print(
                f"{trial['trial_id']}  "
                f"input={trial['input_id']}  "
                f"configuration={trial['configuration_id']}  "
                f"repeat={trial['repeat']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
