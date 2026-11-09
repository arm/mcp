# Copyright © 2026, Arm Limited and Contributors. All rights reserved.
"""Prepare isolated local trials and hand each one to an agent adapter."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .report import run_summary, write_report
from .scenario import Scenario, planned_trials


class RunnerError(RuntimeError):
    """A trial cannot be prepared or an external setup command failed."""


AgentAdapter = Callable[..., tuple[dict[str, Any], list[str]]]


def _default_adapters() -> dict[str, AgentAdapter]:
    from .codex_adapter import run_codex_trial

    return {"codex": run_codex_trial}


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _kill_process_group(process: subprocess.Popen[Any]) -> None:
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _stop_process_group(process: subprocess.Popen[Any]) -> None:
    """Allow child cleanup on interruption, then force-stop a stuck group."""
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        process.wait(timeout=35)
    except subprocess.TimeoutExpired:
        _kill_process_group(process)
        process.wait()
    else:
        # A child may remain in the group after its leader exits on SIGTERM.
        _kill_process_group(process)


def _command(
    args: list[str], cwd: Path, log: Path, *,
    environment: dict[str, str] | None = None, timeout: int = 1800,
) -> int:
    with log.open("wb") as output:
        try:
            process = subprocess.Popen(
                args, cwd=cwd, env=environment, stdout=output,
                stderr=subprocess.STDOUT, start_new_session=True,
            )
        except OSError as exc:
            raise RunnerError(f"cannot start {args[0]}: {exc}") from exc
        try:
            return process.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            _stop_process_group(process)
            raise RunnerError(f"command timed out after {timeout}s; see {log}") from exc
        except KeyboardInterrupt:
            _stop_process_group(process)
            raise


def _git(args: list[str], cwd: Path, log: Path) -> None:
    if _command(["git", *args], cwd, log) != 0:
        raise RunnerError(f"git {' '.join(args[:2])} failed; see {log}")


def _copy_source(source: Path, destination: Path) -> None:
    shutil.copytree(source, destination, symlinks=True,
                    ignore=shutil.ignore_patterns(".git", "__pycache__", "*.egg-info"))


def _prepare_source(
    source: dict[str, Any], scenario_dir: Path, destination: Path, log_dir: Path,
) -> dict[str, str]:
    if source["kind"] == "git":
        _git(["clone", "--no-checkout", source["repository"], str(destination)],
             log_dir, log_dir / f"{destination.name}-clone.log")
        _git(["checkout", "--detach", source["revision"]],
             destination, log_dir / f"{destination.name}-checkout.log")
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=destination,
                                         text=True).strip()
        return {"kind": "git", "repository": source["repository"], "commit": commit}
    original = Path(source["path"]).expanduser()
    if not original.is_absolute():
        original = scenario_dir / original
    original = original.resolve()
    _copy_source(original, destination)
    return {"kind": "local", "path": str(original)}


def _prompt(scenario: Scenario, configuration: dict[str, Any], task_input: dict[str, Any]) -> str:
    parts: list[str] = []
    if "prompt" in configuration:
        path = (scenario.path.parent / configuration["prompt"]).resolve()
        parts.append(path.read_text(encoding="utf-8"))
    parts.append(scenario.request)
    return "\n\n".join(part.strip() for part in parts) + "\n"


def _patch(workspace: Path, baseline: str | None, trial_dir: Path) -> str | None:
    if baseline is None:
        return None
    untracked = subprocess.check_output(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=workspace,
    ).split(b"\0")
    untracked = [path for path in untracked if path]
    if untracked:
        subprocess.run(
            ["git", "add", "-N", "--pathspec-from-file=-", "--pathspec-file-nul"],
            input=b"\0".join(b":(literal)" + path for path in untracked) + b"\0",
            cwd=workspace, check=True, stdout=subprocess.DEVNULL,
        )
    path = trial_dir / "changes.patch"
    with path.open("wb") as output:
        subprocess.run(["git", "diff", "--binary", baseline, "--"], cwd=workspace,
                       check=True, stdout=output)
    return path.name


def _verify(
    scenario: Scenario, workspace: Path, trial_dir: Path, input_source: Path | None = None,
) -> dict[str, Any]:
    command = scenario.document["task"]["verifier"]["command"]
    result_path = trial_dir / "verifier.json"
    environment = os.environ.copy()
    environment.update({
        "AGENT_EVAL_WORKSPACE": str(workspace),
        "AGENT_EVAL_TRIAL_DIR": str(trial_dir),
        "AGENT_EVAL_SCENARIO_DIR": str(scenario.path.parent),
        "AGENT_EVAL_VERIFIER_RESULT": str(result_path),
    })
    if input_source is not None:
        environment["AGENT_EVAL_INPUT_SOURCE"] = str(input_source)
    started = time.monotonic()
    try:
        exit_code = _command(command, scenario.path.parent,
                             trial_dir / "verifier.log", environment=environment)
    except RunnerError as exc:
        return {"status": "error", "error": str(exc), "elapsed_seconds": None}
    verdict = None
    if result_path.exists():
        try:
            verdict = json.loads(result_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            return {"status": "error", "error": f"invalid verifier.json: {exc}",
                    "elapsed_seconds": round(time.monotonic() - started, 3)}
        if not isinstance(verdict, dict):
            return {"status": "error", "error": "verifier.json must be an object",
                    "elapsed_seconds": round(time.monotonic() - started, 3)}
    if verdict is not None and "success" in verdict and not isinstance(verdict["success"], bool):
        return {"status": "error", "error": "verifier.json success must be a boolean",
                "elapsed_seconds": round(time.monotonic() - started, 3)}
    status = ("error" if exit_code < 0 or exit_code >= 2 else
              "passed" if exit_code == 0 and (verdict is None or verdict.get("success", True))
              else "failed")
    return {
        "status": status,
        "exit_code": exit_code,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "result": verdict,
    }


def run_scenario(
    scenario: Scenario, output: Path, *, repetitions: int | None = None,
    adapters: Mapping[str, AgentAdapter] | None = None,
    progress: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Run selected repetitions sequentially and save one result per trial."""
    repetitions = scenario.repetitions if repetitions is None else repetitions
    if not 1 <= repetitions <= scenario.repetitions:
        raise RunnerError(f"repetitions must be between 1 and {scenario.repetitions}")
    selected_adapters = _default_adapters() if adapters is None else adapters
    for config in scenario.configurations:
        if config["agent"]["kind"] not in selected_adapters:
            raise RunnerError(f"no adapter for agent kind {config['agent']['kind']!r}")
    output = output.expanduser().resolve()
    scenario_dir = scenario.path.parent
    for source in [*scenario.inputs, *(
        server.get("source", {"kind": "local", "path": "."})
        for config in scenario.configurations
        for server in config.get("mcp_servers", [])
    )]:
        if source["kind"] == "local":
            original = Path(source["path"]).expanduser()
            if not original.is_absolute():
                original = scenario_dir / original
            if output.is_relative_to(original.resolve()):
                raise RunnerError("output directory must not be inside a local input or server source")
    output.mkdir(parents=True, exist_ok=False)
    sources = output / "sources"
    logs = output / "setup-logs"
    trials_dir = output / "trials"
    for directory in (sources, logs, trials_dir):
        directory.mkdir()
    total_trials = len(scenario.inputs) * len(scenario.configurations) * repetitions

    def announce(message: str) -> None:
        if progress is not None:
            progress(message)

    announce(f"Preparing {scenario.id}: {total_trials} trial(s)")
    _write_json(output / "run.json", {
        "scenario": str(scenario.path), "scenario_id": scenario.id,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "repetitions": repetitions,
    })
    shutil.copy2(scenario.path, output / "scenario.json")
    inputs: dict[str, tuple[Path | None, dict[str, str]]] = {}
    for task_input in scenario.inputs:
        if task_input["kind"] == "request":
            inputs[task_input["id"]] = (None, {"kind": "request"})
        else:
            announce(f"Preparing input {task_input['id']} ({task_input['kind']})")
            destination = sources / f"input-{task_input['id']}"
            inputs[task_input["id"]] = (
                destination, _prepare_source(task_input, scenario_dir, destination, logs)
            )

    servers_by_config: dict[str, list[tuple[dict[str, Any], Path]]] = {}
    server_sources: dict[str, list[dict[str, Any]]] = {}
    for config in scenario.configurations:
        prepared: list[tuple[dict[str, Any], Path]] = []
        source_records: list[dict[str, Any]] = []
        for server in config.get("mcp_servers", []):
            destination = sources / f"server-{config['id']}+{server['name']}"
            source = server.get("source", {"kind": "local", "path": "."})
            announce(f"Preparing MCP server {config['id']}/{server['name']} ({source['kind']})")
            source_info = _prepare_source(source, scenario_dir, destination, logs)
            source_records.append({
                "name": server["name"], "version": server.get("version"),
                "source": source_info, "snapshot": str(destination.relative_to(output)),
            })
            if "build" in server:
                environment = os.environ.copy()
                environment.update(config.get("environment", {}))
                log = logs / f"build-{config['id']}+{server['name']}.log"
                announce(f"Building MCP server {config['id']}/{server['name']} (log: {log})")
                if _command(server["build"], destination, log, environment=environment) != 0:
                    raise RunnerError(f"MCP build failed; see {log}")
                announce(f"Built MCP server {config['id']}/{server['name']}")
            prepared.append((server, destination))
        servers_by_config[config["id"]] = prepared
        server_sources[config["id"]] = source_records
    _write_json(output / "sources.json", {
        "inputs": {name: info for name, (_, info) in inputs.items()},
        "mcp_servers": server_sources,
    })

    by_input = {item["id"]: item for item in scenario.inputs}
    by_config = {item["id"]: item for item in scenario.configurations}
    results: list[dict[str, Any]] = []
    with (output / "results.jsonl").open("w", encoding="utf-8") as index:
        for trial in planned_trials(scenario):
            if trial["repeat"] > repetitions:
                continue
            task_input = by_input[trial["input_id"]]
            config = by_config[trial["configuration_id"]]
            label = f"[{len(results) + 1}/{total_trials}] {trial['trial_id']}"
            announce(f"{label}: preparing workspace")
            trial_dir = trials_dir / trial["trial_id"]
            trial_dir.mkdir()
            workspace = trial_dir / "workspace"
            source_dir, source_info = inputs[task_input["id"]]
            baseline = None
            if source_dir is None:
                workspace.mkdir()
            elif task_input["kind"] == "git":
                _git(["clone", "--shared", str(source_dir), str(workspace)],
                     trial_dir, trial_dir / "workspace-clone.log")
                baseline = source_info["commit"]
                _git(["checkout", "--detach", baseline], workspace,
                     trial_dir / "workspace-checkout.log")
                _git(["remote", "set-url", "origin", source_info["repository"]],
                     workspace, trial_dir / "workspace-remote.log")
            else:
                _copy_source(source_dir, workspace)
            prompt = _prompt(scenario, config, task_input)
            (trial_dir / "prompt.txt").write_text(prompt, encoding="utf-8")
            adapter = selected_adapters[config["agent"]["kind"]]
            announce(f"{label}: running {config['agent']['kind']} "
                     f"(timeout {scenario.document['run']['agent_timeout_seconds']}s)")
            agent, installed = adapter(
                config, servers_by_config[config["id"]], workspace, trial_dir,
                prompt, scenario.document["run"]["agent_timeout_seconds"],
                docker_access=scenario.document["run"].get("docker_access", False),
            )
            elapsed = agent.get("elapsed_seconds")
            duration = f" in {elapsed:.1f}s" if isinstance(elapsed, (int, float)) else ""
            announce(f"{label}: agent {agent['status']}{duration}")
            patch = _patch(workspace, baseline, trial_dir)
            if agent["status"] in ("completed", "timeout"):
                announce(f"{label}: verifying")
                verifier = _verify(scenario, workspace, trial_dir, source_dir)
                announce(f"{label}: verifier {verifier['status']}")
            else:
                verifier = None
            result = {
                **trial, "input": source_info, "agent": agent,
                "skills": installed, "patch": patch, "verifier": verifier,
                "status": verifier["status"] if agent["status"] == "completed" and verifier is not None
                          else agent["status"],
            }
            _write_json(trial_dir / "result.json", result)
            index.write(json.dumps(result) + "\n")
            index.flush()
            results.append(result)
    announce("Writing comparison report")
    comparison = write_report(output)
    return run_summary(comparison, output)
