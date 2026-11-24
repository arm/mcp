# Copyright © 2026, Arm Limited and Contributors. All rights reserved.
"""Summarize saved trials and link the evidence for each comparison."""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import quote


class ReportError(RuntimeError):
    """A saved run does not contain enough valid data to create a report."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReportError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReportError(f"expected a JSON object in {path}")
    return value


def _read_results(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    results = []
    try:
        with path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    result = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ReportError(f"invalid {path}:{line_number}: {exc}") from exc
                if not isinstance(result, dict):
                    raise ReportError(f"expected a JSON object at {path}:{line_number}")
                results.append(result)
    except (OSError, UnicodeError) as exc:
        raise ReportError(f"cannot read {path}: {exc}") from exc
    return results


def _classification(result: dict[str, Any]) -> tuple[str, str | None]:
    agent = result.get("agent") or {}
    agent_status = agent.get("status")
    if agent_status == "timeout":
        return "failed", "agent_timeout"
    if agent_status == "failed":
        if isinstance(agent.get("exit_code"), int) and agent["exit_code"] < 0:
            return "unscored", "agent_interrupted"
        return "failed", "agent_failed"
    if agent_status == "interrupted":
        return "unscored", "agent_interrupted"
    if agent_status == "launch_error":
        return "unscored", "agent_launch_error"
    if agent_status != "completed":
        return "unscored", "unknown_agent_status"

    verifier = result.get("verifier") or {}
    verifier_status = verifier.get("status")
    if verifier_status == "passed":
        return "passing", None
    if verifier_status == "failed":
        return "failed", "verifier_failed"
    if verifier_status == "error":
        return "unscored", "verifier_error"
    return "unscored", "missing_verifier"


def _valid_measure(value: Any, *, integer: bool = False) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return (not integer or isinstance(value, int)) and math.isfinite(value) and value >= 0


def _measure(result: dict[str, Any], name: str) -> int | float | None:
    agent = result.get("agent") or {}
    if name == "agent_elapsed_seconds":
        value = agent.get("elapsed_seconds")
    elif name == "total_tokens":
        value = (agent.get("usage") or {}).get("total_tokens")
    else:
        value = ((result.get("verifier") or {}).get("result") or {}).get(name)
    return value if _valid_measure(value, integer=name == "total_tokens") else None


def _metric(results: list[dict[str, Any]], name: str, *, applicable: bool = True) -> dict[str, Any]:
    values = [_measure(result, name) for result in results] if applicable else []
    available = [value for value in values if value is not None]
    metric = {
        "mean": sum(available) / len(available) if available else None,
        "samples": len(available),
        "missing": len(results) - len(available) if applicable else 0,
    }
    if name == "application_execution_seconds":
        metric["applicable"] = applicable
    return metric


def _timeout_count(result: dict[str, Any]) -> int:
    count = result.get("timeout_count")
    if count is None:
        return int((result.get("agent") or {}).get("status") == "timeout")
    if type(count) is not int or count < 0:
        raise ReportError(f"invalid timeout count for {result.get('trial_id')!r}")
    return count


def _counts(
    records: list[tuple[dict[str, Any], str, str | None]],
    planned: int,
    *, benchmark_applicable: bool,
) -> dict[str, Any]:
    recorded = len(records)
    passing = [result for result, classification, _ in records if classification == "passing"]
    scored = sum(classification != "unscored" for _, classification, _ in records)
    verifier_scored = [result for result, _, _ in records
                       if (result.get("verifier") or {}).get("status") in ("passed", "failed")]
    verifier_passing = [result for result in verifier_scored
                        if (result.get("verifier") or {}).get("status") == "passed"]
    failures = Counter(category for _, classification, category in records
                       if classification != "passing" and category is not None)
    return {
        "planned": planned,
        "recorded": recorded,
        "not_recorded": planned - recorded,
        "scored": scored,
        "unscored": recorded - scored,
        "passing": len(passing),
        "timeouts": sum(_timeout_count(result) for result, _, _ in records),
        "end_to_end_success_rate": len(passing) / scored if scored else None,
        "verifier_scored": len(verifier_scored),
        "verifier_passing": len(verifier_passing),
        "verifier_pass_rate": len(verifier_passing) / len(verifier_scored) if verifier_scored else None,
        "metrics": {
            "agent_elapsed_seconds": _metric(passing, "agent_elapsed_seconds"),
            "total_tokens": _metric(passing, "total_tokens"),
            "application_execution_seconds": _metric(
                verifier_passing, "application_execution_seconds",
                applicable=benchmark_applicable
            ),
        },
        "failure_categories": dict(sorted(failures.items())),
    }


def _artifact(run_dir: Path, trial_id: str, name: Any, attempt: int | None = None) -> str | None:
    if (not isinstance(name, str) or Path(name).name != name or
            Path(trial_id).name != trial_id or trial_id in (".", "..") or
            (attempt is not None and (type(attempt) is not int or attempt < 1))):
        return None
    relative = Path("trials") / trial_id
    if attempt is not None:
        relative /= Path("attempts") / f"{attempt:03d}"
    relative /= name
    path = (run_dir / relative).resolve()
    trial_dir = (run_dir / "trials" / trial_id).resolve()
    if (trial_dir.is_relative_to((run_dir / "trials").resolve()) and
            path.is_relative_to(trial_dir) and path.is_file()):
        return relative.as_posix()
    return None


def _trial_artifacts(run_dir: Path, result: dict[str, Any]) -> dict[str, str]:
    trial_id = result["trial_id"]
    agent = result.get("agent") or {}
    final_attempt = result.get("final_attempt")
    candidates = {
        "trace": agent.get("trace"),
        "final_answer": agent.get("final_answer"),
        "patch": result.get("patch"),
        "agent_stderr": agent.get("stderr"),
        "verifier_result": "verifier.json",
        "verifier_log": "verifier.log",
    }
    artifacts = {"result": _artifact(run_dir, trial_id, "result.json")}
    artifacts.update({label: path for label, name in candidates.items()
                      if (path := _artifact(run_dir, trial_id, name, final_attempt)) is not None})
    attempts = result.get("attempts", [])
    if isinstance(attempts, list):
        for attempt in attempts:
            if not isinstance(attempt, dict):
                continue
            number = attempt.get("number")
            if (path := _artifact(run_dir, trial_id, "result.json", number)) is not None:
                artifacts[f"attempt_{number}_result"] = path
    return {label: path for label, path in artifacts.items() if path is not None}


def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def _link(label: str, path: str) -> str:
    return f"[{_cell(label)}]({quote(path, safe='/-_.~')})"


def _mean(metric: dict[str, Any], *, seconds: bool = False) -> str:
    if metric["mean"] is None:
        return "unavailable (n=0)"
    number = f"{metric['mean']:.3f}" if seconds else f"{metric['mean']:,.1f}"
    return f"{number} (n={metric['samples']})"


def _markdown(report: dict[str, Any]) -> str:
    reason_labels = {
        "agent_timeout": "Agent timed out",
        "agent_failed": "Agent failed",
        "agent_interrupted": "Agent interrupted",
        "agent_launch_error": "Agent could not start",
        "unknown_agent_status": "Unknown agent result",
        "verifier_failed": "Verifier failed",
        "verifier_error": "Verifier error",
        "missing_verifier": "Verifier did not run",
    }
    agent_labels = {
        "completed": "Completed", "timeout": "Timed out", "failed": "Failed",
        "interrupted": "Interrupted", "launch_error": "Could not start",
    }
    verifier_labels = {"passed": "Passed", "failed": "Failed", "error": "Error"}
    outcome_labels = {"passing": "Success", "failed": "Failed", "unscored": "Not scored"}
    lines = [
        f"# Comparison report: {_cell(report['scenario_id'])}", "",
        f"Of {report['planned']} planned trials, {report['scored']} were scored and "
        f"{report['planned'] - report['scored']} were not scored. "
        f"Agent timeout attempts: {report['timeouts']}.", "",
        "Run metadata: [run.json](run.json), [scenario.json](scenario.json), "
        "[sources.json](sources.json).", "",
        "End-to-end success requires a completed agent and a verifier pass on the "
        "terminating attempt. The success rate divides successes by scored trials. "
        "Not scored includes trials without a saved result or without a score.", "",
        "Timeouts count agent attempts, including retries that later succeeded. A final "
        "timeout is a scored failure. Verifier pass rate uses scored verifier runs on "
        "the terminating attempt, including after an agent timeout; verifier errors "
        "are excluded.", "",
        "Mean agent time and tokens use end-to-end successful trials. Mean application "
        "time uses verifier-passed terminating attempts with an available measurement.", "",
        "## Comparison", "",
        "| Configuration | Planned trials | Scored trials | Not scored | End-to-end successes | End-to-end success rate | Agent timeouts | Verifier scored | Verifier passes | Verifier pass rate |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for config in report["configurations"]:
        rate = ("unavailable" if config["end_to_end_success_rate"] is None
                else f"{config['end_to_end_success_rate']:.1%}")
        verifier_rate = ("unavailable" if config["verifier_pass_rate"] is None
                         else f"{config['verifier_pass_rate']:.1%}")
        lines.append(f"| {_cell(config['id'])} | {config['planned']} | "
                     f"{config['scored']} | {config['planned'] - config['scored']} | "
                     f"{config['passing']} | {rate} | {config['timeouts']} | "
                     f"{config['verifier_scored']} | {config['verifier_passing']} | "
                     f"{verifier_rate} |")
    lines += [
        "", "## Measurements", "",
        "| Configuration | Mean agent time (s) | Mean total tokens | Mean application time (s) |",
        "| --- | ---: | ---: | ---: |",
    ]
    for config in report["configurations"]:
        metrics = config["metrics"]
        app = metrics["application_execution_seconds"]
        app_text = _mean(app, seconds=True)
        lines.append(f"| {_cell(config['id'])} | "
                     f"{_mean(metrics['agent_elapsed_seconds'], seconds=True)} | "
                     f"{_mean(metrics['total_tokens'])} | {app_text} |")
    reasons = []
    for config in report["configurations"]:
        counts = []
        if config["not_recorded"]:
            counts.append(f"No saved result: {config['not_recorded']}")
        counts.extend(f"{reason_labels.get(name, name.replace('_', ' ').capitalize())}: {count}"
                      for name, count in config["failure_categories"].items())
        if counts:
            reasons.append(f"- **{_cell(config['id'])}:** {', '.join(counts)}.")
    if reasons:
        lines += ["", "## Why trials did not succeed", "",
                  "These counts are trials, based on the terminating attempt.", "", *reasons]
    lines += [
        "", "## Trial evidence", "",
        "Knowledge base (KB) calls count distinct knowledge-base search requests "
        "recorded in the agent trace. Skills read lists skill names identified from "
        "successful file-read commands; a read does not prove the instructions were "
        "followed. With retries, these fields describe the terminating attempt.", "",
        "| Trial | Input | Configuration | Agent result | Verifier result | End-to-end result | Agent timeouts | KB calls | Skills read | Artifacts |",
        "| --- | --- | --- | --- | --- | --- | ---: | ---: | --- | --- |",
    ]
    for trial in report["trials"]:
        outcome = outcome_labels.get(trial["classification"], trial["classification"])
        if trial["failure_category"]:
            outcome += f" ({reason_labels.get(trial['failure_category'], trial['failure_category'])})"
        agent_result = agent_labels.get(trial["agent_status"], trial["agent_status"] or "Unknown")
        verifier_result = verifier_labels.get(trial["verifier_status"], "Not run")
        links = ", ".join(_link(label.replace("_", " "), path)
                          for label, path in trial["artifacts"].items()) or "none"
        kb_calls = (str(trial["knowledge_base_calls"])
                    if trial["knowledge_base_calls"] is not None else "unavailable")
        if trial["skills_read"] is None:
            skills_read = "unavailable"
        else:
            skills_read = ", ".join(_cell(name) for name in trial["skills_read"]) or "none"
        lines.append(f"| {_cell(trial['trial_id'])} | {_cell(trial['input_id'])} | "
                     f"{_cell(trial['configuration_id'])} | {_cell(agent_result)} | "
                     f"{_cell(verifier_result)} | "
                     f"{_cell(outcome)} | {trial['timeout_count']} | "
                     f"{kb_calls} | {skills_read} | {links} |")
    if report["setup_logs"]:
        lines += ["", "## Setup logs", ""]
        lines += [f"- {_link(Path(path).name, path)}" for path in report["setup_logs"]]
    return "\n".join(lines) + "\n"


def run_summary(report: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    """Return the compact status shown by the run command."""
    return {
        "output": str(run_dir.expanduser().resolve()),
        "trials": report["recorded"],
        "passed": report["passing"],
        "failed": report["scored"] - report["passing"],
        "timeouts": report["timeouts"],
        "verifier_passed": report["verifier_passing"],
        "verifier_scored": report["verifier_scored"],
        "unscored": report["unscored"],
        "not_recorded": report["not_recorded"],
        "report": "report.md",
    }


def write_report(run_dir: Path) -> dict[str, Any]:
    """Generate the comparison and compact summary from saved trial records."""
    run_dir = run_dir.expanduser().resolve()
    run = _read_json(run_dir / "run.json")
    scenario = _read_json(run_dir / "scenario.json")
    results = _read_results(run_dir / "results.jsonl")
    try:
        repetitions = run["repetitions"]
        inputs = {item["id"] for item in scenario["task"].get("inputs", [{"id": "task"}])}
        config_ids = [item["id"] for item in scenario["configurations"]]
        scenario_id = scenario["id"]
    except (KeyError, TypeError, ValueError) as exc:
        raise ReportError(f"incomplete saved run metadata: {exc}") from exc
    if not isinstance(repetitions, int) or repetitions < 1 or not inputs or not config_ids:
        raise ReportError("invalid planned trial counts in saved run metadata")
    if len(config_ids) != len(set(config_ids)):
        raise ReportError("duplicate configuration IDs in saved scenario")

    records: list[tuple[dict[str, Any], str, str | None]] = []
    seen: set[str] = set()
    for result in results:
        trial_id = result.get("trial_id")
        if (not isinstance(trial_id, str) or not trial_id or trial_id in seen or
                Path(trial_id).name != trial_id or trial_id in (".", "..") or
                result.get("input_id") not in inputs or
                result.get("configuration_id") not in config_ids or
                type(result.get("repeat")) is not int or
                not 1 <= result["repeat"] <= repetitions):
            raise ReportError(f"invalid or duplicate trial record: {trial_id!r}")
        seen.add(trial_id)
        classification, category = _classification(result)
        records.append((result, classification, category))
    planned = len(inputs) * len(config_ids) * repetitions
    if len(records) > planned:
        raise ReportError("more recorded trials than planned trials")

    benchmark_applicable = any(
        "application_execution_seconds" in ((result.get("verifier") or {}).get("result") or {})
        for result, _, _ in records
    )
    overall = _counts(records, planned, benchmark_applicable=benchmark_applicable)
    configurations = []
    for config_id in config_ids:
        group = [record for record in records if record[0]["configuration_id"] == config_id]
        configurations.append({
            "id": config_id,
            **_counts(group, len(inputs) * repetitions,
                      benchmark_applicable=benchmark_applicable),
        })
    trials = [{
        "trial_id": result["trial_id"],
        "input_id": result["input_id"],
        "configuration_id": result["configuration_id"],
        "repeat": result["repeat"],
        "classification": classification,
        "failure_category": category,
        "agent_status": (result.get("agent") or {}).get("status"),
        "verifier_status": (result.get("verifier") or {}).get("status"),
        "timeout_count": _timeout_count(result),
        "knowledge_base_calls": ((result.get("agent") or {}).get("activity") or {}).get(
            "knowledge_base_calls"
        ),
        "skills_read": ((result.get("agent") or {}).get("activity") or {}).get(
            "skills_read"
        ),
        "artifacts": _trial_artifacts(run_dir, result),
    } for result, classification, category in records]
    logs = run_dir / "setup-logs"
    setup_logs = [path.relative_to(run_dir).as_posix() for path in sorted(logs.glob("*.log"))
                  if path.is_file() and path.resolve().is_relative_to(run_dir)]
    report = {
        "scenario_id": scenario_id,
        "started_at": run.get("started_at"),
        **overall,
        "configurations": configurations,
        "trials": trials,
        "setup_logs": setup_logs,
    }
    (run_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (run_dir / "report.md").write_text(_markdown(report), encoding="utf-8")
    (run_dir / "summary.json").write_text(
        json.dumps(run_summary(report, run_dir), indent=2) + "\n", encoding="utf-8"
    )
    return report
