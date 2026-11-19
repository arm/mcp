# Copyright © 2026, Arm Limited and Contributors. All rights reserved.
"""Check local run prerequisites before starting an agent trial."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from .scenario import Scenario


class PreflightError(RuntimeError):
    """The scenario's local execution setup is incomplete."""


def _executable(command: list[str], cwd: Path, label: str) -> None:
    name = command[0]
    if "/" in name:
        path = Path(name).expanduser()
        if not path.is_absolute():
            path = cwd / path
        if not path.is_file() or not os.access(path, os.X_OK):
            raise PreflightError(f"{label}: executable is missing or not executable: {path}")
    elif shutil.which(name) is None:
        raise PreflightError(f"{label}: executable is not on PATH: {name}")


def _python_script(command: list[str], cwd: Path, label: str) -> None:
    if not Path(command[0]).name.startswith("python") or "-c" in command or "-m" in command:
        return
    script = next((arg for arg in command[1:] if arg.endswith(".py")), None)
    if script is None:
        return
    path = Path(script)
    if not path.is_absolute():
        path = cwd / path
    if not path.is_file():
        raise PreflightError(f"{label} script does not exist: {path}")


def check_prepared_launch(server: dict[str, Any], source_dir: Path) -> None:
    """Check a launch command after any build has created its local files."""
    label = f"MCP launch {server['name']}"
    _executable(server["launch"], source_dir, label)
    _python_script(server["launch"], source_dir, label)


def _skill_names(server: dict[str, Any], source_dir: Path) -> set[str]:
    if "skills_root" not in server:
        return set()
    root = (source_dir / server["skills_root"]).resolve()
    if not root.is_relative_to(source_dir.resolve()) or not root.is_dir():
        raise PreflightError(f"invalid skills_root for {server['name']!r}: {root}")
    skill_files = sorted(root.glob("*/SKILL.md"))
    if not skill_files:
        raise PreflightError(f"no bundled skills in {root}")
    for skill_file in skill_files:
        try:
            skill_file.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            raise PreflightError(f"cannot read skill {skill_file}: {exc}") from exc
    return {file.parent.name for file in skill_files}


def check_prepared_skills(
    servers_by_config: dict[str, list[tuple[dict[str, Any], Path]]],
) -> None:
    """Validate all skill roots after Git/local server sources are prepared."""
    for config_id, servers in servers_by_config.items():
        names: set[str] = set()
        for server, source_dir in servers:
            found = _skill_names(server, source_dir)
            repeated = names & found
            if repeated:
                raise PreflightError(
                    f"configuration {config_id!r} bundles skill {sorted(repeated)[0]!r} "
                    "in more than one MCP server"
                )
            names.update(found)


def check_preflight(scenario: Scenario) -> list[str]:
    """Run fast local checks and return the checks that completed."""
    from .runner import _default_adapters

    scenario_dir = scenario.path.parent
    supported_agents = _default_adapters()
    verifier_command = scenario.document["task"]["verifier"]["command"]
    _executable(verifier_command, scenario_dir, "verifier")
    requires_docker = (scenario.document["run"].get("docker_access", False)
                       or Path(verifier_command[0]).name == "docker")
    local_skills_checked = False

    for config in scenario.configurations:
        kind = config["agent"]["kind"]
        if kind not in supported_agents:
            raise PreflightError(f"no adapter for agent kind {kind!r}")
        if kind == "codex":
            _executable(["codex"], scenario_dir, "Codex agent")
        local_servers: list[tuple[dict[str, Any], Path]] = []
        for server in config.get("mcp_servers", []):
            if any(Path(command[0]).name == "docker"
                   for command in (server.get("build"), server["launch"]) if command):
                requires_docker = True
            source = server.get("source", {"kind": "local", "path": "."})
            if source["kind"] == "local":
                source_dir = Path(source["path"]).expanduser()
                if not source_dir.is_absolute():
                    source_dir = scenario_dir / source_dir
                local_servers.append((server, source_dir.resolve()))
        check_prepared_skills({config["id"]: local_servers})
        local_skills_checked |= any("skills_root" in server for server, _ in local_servers)

    if requires_docker:
        _executable(["docker"], scenario_dir, "Docker")
        try:
            info = subprocess.run(
                ["docker", "info", "--format", "{{.OSType}}"],
                capture_output=True, text=True, timeout=15,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise PreflightError(f"Docker daemon is unavailable: {exc}") from exc
        if info.returncode != 0:
            detail = (info.stderr.strip() or info.stdout.strip())[:300]
            raise PreflightError(f"Docker daemon is unavailable: {detail}")

    checks = ["Verifier executable", "Agent adapters and executables"]
    if local_skills_checked:
        checks.append("Local MCP skill files")
    if requires_docker:
        checks.append("Docker CLI and daemon")
    return checks
