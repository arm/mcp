# Copyright © 2026, Arm Limited and Contributors. All rights reserved.
"""Run one Codex CLI trial and retain its machine-readable trace."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from .runner import RunnerError, _kill_process_group

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib


def _toml_value(value: Any) -> str:
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(item) for item in value) + "]"
    if isinstance(value, dict):
        return "{ " + ", ".join(
            f"{_toml_value(key)} = {_toml_value(item)}" for key, item in value.items()
        ) + " }"
    raise ValueError(f"unsupported Codex provider setting type: {type(value).__name__}")


def _write_provider_config(original_home: Path, isolated_home: Path) -> None:
    """Keep the user's provider routing without importing their MCP/plugin setup."""
    config_path = original_home / "config.toml"
    if not config_path.is_file():
        return
    with config_path.open("rb") as source:
        config = tomllib.load(source)
    provider_name = config.get("model_provider")
    if not provider_name:
        return
    provider = config.get("model_providers", {}).get(provider_name)
    if not isinstance(provider, dict):
        raise ValueError(f"Codex model provider {provider_name!r} is not configured")
    lines = [f"model_provider = {_toml_value(provider_name)}", "",
             f"[model_providers.{_toml_value(provider_name)}]"]
    lines.extend(f"{_toml_value(key)} = {_toml_value(value)}"
                 for key, value in provider.items())
    descriptor = os.open(isolated_home / "config.toml", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as target:
        target.write("\n".join(lines) + "\n")


def _usage_from_trace(path: Path) -> tuple[dict[str, int | None], bool]:
    usage: dict[str, int | None] = {
        "input_tokens": None,
        "output_tokens": None,
        "cached_input_tokens": None,
        "total_tokens": None,
    }
    completed = False
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("type") == "turn.completed":
                completed = True
                reported = event.get("usage", {})
                for key in ("input_tokens", "output_tokens", "cached_input_tokens"):
                    value = reported.get(key)
                    usage[key] = value if isinstance(value, int) and not isinstance(value, bool) else None
                if usage["input_tokens"] is not None and usage["output_tokens"] is not None:
                    usage["total_tokens"] = usage["input_tokens"] + usage["output_tokens"]
            elif event.get("type") == "turn.failed":
                completed = False
    return usage, completed


def _docker_socket() -> Path:
    """Resolve the active local Docker context before isolating Codex's HOME."""
    endpoint = os.environ.get("DOCKER_HOST")
    if not endpoint:
        try:
            result = subprocess.run(
                ["docker", "context", "inspect", "--format", "{{json .Endpoints.docker.Host}}"],
                capture_output=True, text=True, check=True,
            )
            endpoint = json.loads(result.stdout)
        except (OSError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"cannot resolve the active Docker socket: {exc}") from exc
    if not isinstance(endpoint, str) or not endpoint.startswith("unix://"):
        raise RuntimeError("docker_access requires a local Unix-socket Docker context")
    path = Path(endpoint.removeprefix("unix://")).expanduser().resolve()
    if not path.is_socket():
        raise RuntimeError(f"Docker socket is unavailable: {path}")
    return path


def _skill_dir(source_dir: Path, name: str) -> Path:
    matches = [path.parent for path in source_dir.rglob("SKILL.md")
               if path.parent.name == name]
    if len(matches) != 1:
        raise RunnerError(f"expected one bundled skill {name!r} in {source_dir}; found {len(matches)}")
    return matches[0]


def _install_skills(
    servers: list[tuple[dict[str, Any], Path]], profile_home: Path,
) -> list[str]:
    installed: list[str] = []
    for server, source_dir in servers:
        for name in server.get("skills", []):
            destination = profile_home / ".agents" / "skills" / name
            if destination.exists():
                raise RunnerError(f"skill {name!r} is selected by more than one server")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(_skill_dir(source_dir, name), destination, symlinks=True)
            installed.append(name)
    return installed


def run_codex(
    configuration: dict[str, Any],
    servers: list[tuple[dict[str, Any], Path]],
    workspace: Path,
    trial_dir: Path,
    prompt: str,
    timeout_seconds: int,
    *,
    docker_access: bool = False,
    executable: str = "codex",
) -> dict[str, Any]:
    """Run Codex with the selected stdio MCP servers."""
    trace = trial_dir / "agent.jsonl"
    stderr = trial_dir / "agent.stderr.txt"
    final_answer = trial_dir / "final.txt"
    profile_home = trial_dir / "profile"
    profile_home.mkdir(exist_ok=True)

    args = [
        executable, "exec", "--json", "--ephemeral",
        "--skip-git-repo-check", "--sandbox", "workspace-write",
        "-c", 'approval_policy="never"',
        "-C", str(workspace), "-m", configuration["agent"]["model"],
        "-o", str(final_answer),
    ]
    if docker_access:
        try:
            docker_socket = _docker_socket()
        except RuntimeError as exc:
            stderr.write_text(str(exc) + "\n", encoding="utf-8")
            trace.touch()
            return {"status": "launch_error", "error": str(exc), "elapsed_seconds": None,
                    "usage": None, "exit_code": None, "trace": trace.name,
                    "stderr": stderr.name, "final_answer": None}
        args.extend(["--add-dir", str(docker_socket.parent),
                     "-c", "sandbox_workspace_write.network_access=true"])
    for server, source_dir in servers:
        prefix = f"mcp_servers.{server['name']}"
        args.extend(["-c", f"{prefix}.command={_toml_value(server['launch'][0])}"])
        args.extend(["-c", f"{prefix}.args={_toml_value(server['launch'][1:])}"])
        args.extend(["-c", f"{prefix}.cwd={_toml_value(str(source_dir))}"])
        args.extend(["-c", f"{prefix}.required=true"])
        if "enabled_tools" in server:
            args.extend(["-c", f"{prefix}.enabled_tools={_toml_value(server['enabled_tools'])}"])
        if "default_tools_approval_mode" in server:
            args.extend(["-c", f"{prefix}.default_tools_approval_mode="
                         f"{_toml_value(server['default_tools_approval_mode'])}"])
        forwarded = list(configuration.get("environment", {}))
        if docker_access and Path(server["launch"][0]).name == "docker":
            # The isolated HOME has no Docker context; pass the socket to
            # the stdio MCP launcher as well as to agent shell commands.
            if "DOCKER_HOST" not in forwarded:
                forwarded.append("DOCKER_HOST")
        if forwarded:
            args.extend(["-c", f"{prefix}.env_vars={_toml_value(forwarded)}"])

    environment = os.environ.copy()
    original_home = Path.home()
    original_codex_home = Path(os.environ.get("CODEX_HOME", original_home / ".codex")).expanduser().resolve()
    environment["HOME"] = str(profile_home)
    environment.update(configuration.get("environment", {}))
    if docker_access:
        environment["DOCKER_HOST"] = f"unix://{docker_socket}"
    timed_out = False
    # Keep user MCP servers and plugins out while retaining the provider and auth.
    # The temporary home (and its private auth copy) is removed after this turn.
    with tempfile.TemporaryDirectory(prefix="arm-agent-eval-codex-") as codex_home:
        _write_provider_config(original_codex_home, Path(codex_home))
        auth_file = original_codex_home / "auth.json"
        if auth_file.is_file():
            auth_copy = Path(codex_home) / "auth.json"
            descriptor = os.open(auth_copy, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as target, auth_file.open("rb") as source:
                shutil.copyfileobj(source, target)
        environment["CODEX_HOME"] = codex_home
        started = time.monotonic()
        with trace.open("wb") as stdout_file, stderr.open("wb") as stderr_file:
            try:
                process = subprocess.Popen(
                    args + ["-"], stdin=subprocess.PIPE, stdout=stdout_file,
                    stderr=stderr_file, cwd=workspace, env=environment,
                    start_new_session=True,
                )
            except OSError as exc:
                return {"status": "launch_error", "error": str(exc),
                        "elapsed_seconds": None, "usage": None, "exit_code": None}
            try:
                process.communicate(input=prompt.encode("utf-8"), timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                _kill_process_group(process)
                process.communicate()
            except KeyboardInterrupt:
                _kill_process_group(process)
                process.communicate()
                raise
        elapsed = time.monotonic() - started
    usage, completed = _usage_from_trace(trace)
    status = ("timeout" if timed_out else
              "completed" if process.returncode == 0 and completed else
              "interrupted" if process.returncode < 0 else "failed")
    return {
        "status": status,
        "exit_code": process.returncode,
        "elapsed_seconds": round(elapsed, 3),
        "usage": usage,
        "trace": trace.name,
        "stderr": stderr.name,
        "final_answer": final_answer.name if final_answer.exists() else None,
    }


def run_codex_trial(
    configuration: dict[str, Any],
    servers: list[tuple[dict[str, Any], Path]],
    workspace: Path,
    trial_dir: Path,
    prompt: str,
    timeout_seconds: int,
    *,
    docker_access: bool = False,
    executable: str = "codex",
) -> tuple[dict[str, Any], list[str]]:
    """Install selected Codex skills, then run the agent."""
    installed = _install_skills(servers, trial_dir / "profile")
    result = run_codex(
        configuration, servers, workspace, trial_dir, prompt, timeout_seconds,
        docker_access=docker_access, executable=executable,
    )
    return result, installed
