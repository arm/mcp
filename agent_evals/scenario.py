# Copyright © 2026, Arm Limited and Contributors. All rights reserved.
"""Load and plan agent evaluations from the versioned scenario format."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from jsonschema import Draft202012Validator


class ScenarioError(ValueError):
    """A scenario is malformed or refers to a missing local input."""


_RESERVED_ENVIRONMENT_KEYS = {"HOME", "CODEX_HOME", "TMPDIR", "DOCKER_HOST", "PATH"}


@dataclass(frozen=True)
class Scenario:
    path: Path
    document: dict[str, Any]
    request: str

    @property
    def id(self) -> str:
        return self.document["id"]

    @property
    def inputs(self) -> list[dict[str, Any]]:
        return self.document["task"].get("inputs", [{"id": "task", "kind": "request"}])

    @property
    def configurations(self) -> list[dict[str, Any]]:
        return self.document["configurations"]

    @property
    def repetitions(self) -> int:
        return self.document["run"]["repetitions"]


def load_scenario(path: str | Path) -> Scenario:
    scenario_path = Path(path).resolve()
    try:
        document = json.loads(scenario_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ScenarioError(f"cannot read {scenario_path}: {exc}") from exc
    except UnicodeError as exc:
        raise ScenarioError(f"cannot decode {scenario_path} as UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise ScenarioError(f"{scenario_path}:{exc.lineno}: {exc.msg}") from exc

    error = next(iter(_validator().iter_errors(document)), None)
    if error is not None:
        raise ScenarioError(f"{error.json_path}: {error.message}")

    _validate_environment(document)
    request = _validate_local_references(document, scenario_path.parent)
    return Scenario(path=scenario_path, document=document, request=request)


def planned_trials(scenario: Scenario) -> Iterator[dict[str, str | int]]:
    """List the input × configuration × repetition grid, without starting it."""
    for task_input in scenario.inputs:
        for repeat in range(1, scenario.repetitions + 1):
            # Rotate the fixed comparison order so one setup is not always first.
            configurations = (
                scenario.configurations
                if repeat % 2
                else reversed(scenario.configurations)
            )
            for configuration in configurations:
                yield {
                    "trial_id": f"{task_input['id']}+{configuration['id']}+{repeat:03d}",
                    "input_id": task_input["id"],
                    "configuration_id": configuration["id"],
                    "repeat": repeat,
                }


def _validator() -> Draft202012Validator:
    schema_path = Path(__file__).with_name("scenario.schema.json")
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ScenarioError(f"cannot read scenario schema at {schema_path}: {exc}") from exc
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _validate_environment(document: dict[str, Any]) -> None:
    for index, configuration in enumerate(document["configurations"]):
        for name in configuration.get("environment", {}):
            if name.upper() in _RESERVED_ENVIRONMENT_KEYS:
                raise ScenarioError(
                    f"configurations[{index}].environment cannot override reserved variable {name!r}"
                )


def _validate_local_references(document: dict[str, Any], scenario_dir: Path) -> str:
    task = document["task"]
    if "request_file" in task:
        request_file = _existing_file(
            task["request_file"], scenario_dir, "task.request_file"
        )
        try:
            request = request_file.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise ScenarioError(f"cannot read task.request_file: {exc}") from exc
        if not request.strip():
            raise ScenarioError("task.request_file is empty")
    else:
        request = task["request"]

    verifier_command = task["verifier"]["command"]
    if (Path(verifier_command[0]).name.startswith("python")
            and "-c" not in verifier_command and "-m" not in verifier_command):
        script = next((arg for arg in verifier_command[1:] if arg.endswith(".py")), None)
        if script is not None and not Path(script).is_absolute():
            _existing_file(script, scenario_dir, "task.verifier.command script", allow_parent=True)

    _unique_ids(task.get("inputs", []), "task.inputs")
    for index, task_input in enumerate(task.get("inputs", [])):
        if task_input["kind"] == "local":
            _require_directory(
                task_input["path"], scenario_dir, f"task.inputs[{index}].path"
            )

    _unique_ids(document["configurations"], "configurations")
    for index, configuration in enumerate(document["configurations"]):
        where = f"configurations[{index}]"
        prompt = configuration.get("prompt")
        if prompt is not None:
            _existing_file(prompt, scenario_dir, f"{where}.prompt", allow_parent=True)

        servers = configuration.get("mcp_servers", [])
        _unique_ids(servers, f"{where}.mcp_servers", field="name")
        for server_index, server in enumerate(servers):
            skills_root = server.get("skills_root")
            if skills_root is not None:
                _relative_source_path(
                    skills_root, f"{where}.mcp_servers[{server_index}].skills_root"
                )
            source = server.get("source")
            if source is not None and source["kind"] == "local":
                _require_directory(
                    source["path"],
                    scenario_dir,
                    f"{where}.mcp_servers[{server_index}].source.path",
                )
            if skills_root is not None and (source is None or source["kind"] == "local"):
                source_path = Path(source["path"] if source is not None else ".").expanduser()
                if not source_path.is_absolute():
                    source_path = scenario_dir / source_path
                source_path = source_path.resolve()
                root = (source_path / skills_root).resolve()
                if not root.is_relative_to(source_path) or not root.is_dir():
                    raise ScenarioError(
                        f"{where}.mcp_servers[{server_index}].skills_root "
                        f"does not exist within the local server source: {root}"
                    )

    return request


def _relative_source_path(path: str, where: str) -> None:
    if ("\\" in path or re.match(r"^[a-zA-Z]:", path) or
            Path(path).is_absolute() or ".." in Path(path).parts):
        raise ScenarioError(f"{where} must be a relative path within its server source")


def _unique_ids(
    entries: list[dict[str, Any]], where: str, *, field: str = "id"
) -> None:
    names: set[str] = set()
    for entry in entries:
        name = entry[field]
        if name in names:
            if where == "configurations":
                raise ScenarioError(f"duplicate configuration id {name!r}")
            raise ScenarioError(f"{where} has duplicate {field} {name!r}")
        names.add(name)


def _existing_file(
    path: str, scenario_dir: Path, where: str, *, allow_parent: bool = False
) -> Path:
    if "\\" in path or re.match(r"^[a-zA-Z]:", path) or Path(path).is_absolute():
        raise ScenarioError(f"{where} must be a relative path")
    scenario_dir = scenario_dir.resolve()
    file_path = (scenario_dir / path).resolve()
    if not allow_parent and not file_path.is_relative_to(scenario_dir):
        raise ScenarioError(f"{where} must stay within the scenario directory")
    if not file_path.is_file():
        raise ScenarioError(f"{where} does not exist: {file_path}")
    return file_path


def _require_directory(path: str, base_dir: Path, where: str) -> None:
    directory = Path(path).expanduser()
    if not directory.is_absolute():
        directory = base_dir / directory
    directory = directory.resolve()
    if not directory.is_dir():
        raise ScenarioError(f"{where} does not exist or is not a directory: {directory}")
