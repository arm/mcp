# Copyright © 2026, Arm Limited and Contributors. All rights reserved.
"""Run one Codex CLI trial and retain its machine-readable trace."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import time
import uuid
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
    lines = [f"model_provider = {_toml_value(provider_name)}"]
    if isinstance(provider, dict):
        lines.extend(["", f"[model_providers.{_toml_value(provider_name)}]"])
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


_SKILL_PATH = re.compile(
    r"(?:^|/)\.agents/skills/(?:([^/{}\s'\"`]+)|\{([^{}]+)\})/SKILL\.md"
    r"(?=$|[^A-Za-z0-9_.-])"
)
_READ_COMMANDS = {"cat", "sed", "head", "tail", "less", "more", "grep", "awk", "nl"}
_CONTROL_OPERATORS = {"&&", "||", "|", ";", "&", "(", ")"}
_VALUE_OPTIONS = {
    "grep": {"-e", "--regexp", "-f", "--file", "-m", "--max-count",
             "--include", "--exclude", "--exclude-dir"},
    "sed": {"-e", "--expression", "-f", "--file"},
    "awk": {"-F", "-f", "-v"},
    "head": {"-n", "--lines", "-c", "--bytes"},
    "tail": {"-n", "--lines", "-c", "--bytes"},
    "nl": {"-w", "-s", "-i", "-v", "-l"},
}


def _read_file_operands(command: str) -> list[str]:
    """Return unambiguous file inputs for one successful shell read command."""
    if "\n" in command or "`" in command or "$(" in command:
        return []
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>()")
        lexer.whitespace_split = True
        lexer.commenters = "#"
        tokens = list(lexer)
    except ValueError:
        return []
    if not tokens or any(token in _CONTROL_OPERATORS for token in tokens):
        return []
    reader = Path(tokens[0]).name
    if reader not in _READ_COMMANDS:
        return []

    files: list[str] = []
    positionals: list[str] = []
    has_pattern_option = False
    options = True
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token in ("<", ">", ">>"):
            if index + 1 >= len(tokens):
                return []
            if token == "<":
                files.append(tokens[index + 1])
            index += 2
            continue
        if options and token == "--":
            options = False
        elif options and token.startswith("-") and token != "-":
            if reader == "sed" and (token.startswith("-i") or token == "--in-place"):
                return []
            if token in _VALUE_OPTIONS.get(reader, set()):
                if index + 1 >= len(tokens):
                    return []
                if reader in ("grep", "sed", "awk") and token in (
                        "-e", "--regexp", "--expression", "-f", "--file"):
                    has_pattern_option = True
                index += 1
        else:
            positionals.append(token)
        index += 1

    if reader in ("grep", "sed", "awk") and not has_pattern_option:
        positionals = positionals[1:]
    return files + positionals


def _activity_from_trace(path: Path, installed: list[str]) -> dict[str, Any] | None:
    """Summarize observable KB calls and skill-file reads in a Codex trace."""
    kb_calls: set[str] = set()
    skills_read: set[str] = set()
    known_skills = set(installed)
    saw_event = False
    try:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(event, dict):
                    continue
                saw_event = True
                item = event.get("item")
                if not isinstance(item, dict):
                    continue
                if (event.get("type") in ("item.started", "item.completed") and
                        item.get("type") == "mcp_tool_call" and
                        item.get("tool") == "knowledge_base_search" and
                        isinstance(item.get("id"), str)):
                    kb_calls.add(item["id"])
                if (event.get("type") != "item.completed" or
                        item.get("type") != "command_execution" or
                        item.get("exit_code") != 0):
                    continue
                command = item.get("command")
                if not isinstance(command, str) or "SKILL.md" not in command:
                    continue
                try:
                    words = shlex.split(command)
                except ValueError:
                    words = []
                if (len(words) >= 3 and Path(words[0]).name in ("sh", "bash", "zsh") and
                        words[1] in ("-c", "-lc", "-ic")):
                    command = words[2]
                for file in _read_file_operands(command):
                    for match in _SKILL_PATH.finditer(file):
                        names = (match.group(1),) if match.group(1) else match.group(2).split(",")
                        skills_read.update(name for name in names if name in known_skills)
    except (OSError, UnicodeError):
        return None
    if not saw_event:
        return None
    return {"knowledge_base_calls": len(kb_calls), "skills_read": sorted(skills_read)}


def _docker_socket() -> Path:
    """Resolve the active local Docker context before isolating Codex's HOME."""
    endpoint = None if os.environ.get("DOCKER_CONTEXT") else os.environ.get("DOCKER_HOST")
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


def _install_skills(
    servers: list[tuple[dict[str, Any], Path]], profile_home: Path,
) -> list[str]:
    installed: list[str] = []
    for server, source_dir in servers:
        if "skills_root" not in server:
            continue
        root = (source_dir / server["skills_root"]).resolve()
        if not root.is_relative_to(source_dir.resolve()) or not root.is_dir():
            raise RunnerError(f"invalid skills_root for {server['name']!r}: {root}")
        skill_files = sorted(root.glob("*/SKILL.md"))
        if not skill_files:
            raise RunnerError(f"no bundled skills in {root}")
        for skill_file in skill_files:
            name = skill_file.parent.name
            destination = profile_home / ".agents" / "skills" / name
            if destination.exists():
                raise RunnerError(f"skill {name!r} is bundled by more than one server")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(skill_file.parent, destination, symlinks=True)
            installed.append(name)
    return installed


def _cleanup_docker_mcp_containers(
    launches: list[tuple[str, str]], environment: dict[str, str],
) -> None:
    """Remove only containers labeled by this Codex attempt's MCP launches."""
    errors: list[str] = []
    for executable, label in launches:
        try:
            found = subprocess.run(
                [executable, "ps", "--all", "--quiet", "--filter", f"label={label}"],
                capture_output=True, text=True, timeout=10, env=environment,
            )
            if found.returncode != 0:
                raise RunnerError(f"cannot find MCP containers for {label}: {found.stderr.strip()}")
            for container_id in found.stdout.split():
                removed = subprocess.run(
                    [executable, "rm", "--force", "--volumes", container_id],
                    capture_output=True, text=True, timeout=10, env=environment,
                )
                if removed.returncode != 0 and "No such container" not in removed.stderr:
                    errors.append(f"cannot remove MCP container {container_id}: {removed.stderr.strip()}")
        except (OSError, subprocess.TimeoutExpired) as exc:
            errors.append(f"cannot clean up MCP containers for {label}: {exc}")
        except RunnerError as exc:
            errors.append(str(exc))
    if errors:
        raise RunnerError("; ".join(errors))


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
    if "reasoning_effort" in configuration["agent"]:
        args.extend(["-c", f"model_reasoning_effort="
                     f"{_toml_value(configuration['agent']['reasoning_effort'])}"])
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
    docker_mcp_launches: list[tuple[str, str]] = []
    for server, source_dir in servers:
        launch = list(server["launch"])
        if Path(launch[0]).name == "docker" and launch[1:2] == ["run"]:
            label = f"arm-agent-evals.mcp={uuid.uuid4().hex}"
            launch[2:2] = ["--label", label]
            docker_mcp_launches.append((launch[0], label))
        prefix = f"mcp_servers.{server['name']}"
        args.extend(["-c", f"{prefix}.command={_toml_value(launch[0])}"])
        args.extend(["-c", f"{prefix}.args={_toml_value(launch[1:])}"])
        args.extend(["-c", f"{prefix}.cwd={_toml_value(str(source_dir))}"])
        args.extend(["-c", f"{prefix}.required=true"])
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
        environment.pop("DOCKER_CONTEXT", None)
    cleanup_environment = os.environ.copy()
    cleanup_environment.update(configuration.get("environment", {}))
    if docker_access:
        cleanup_environment["DOCKER_HOST"] = environment["DOCKER_HOST"]
        cleanup_environment.pop("DOCKER_CONTEXT", None)
    timed_out = False
    cleanup_error = None
    # Keep user MCP servers and plugins out while retaining the provider and auth.
    # The temporary home (and its private auth copy) is removed after this turn.
    try:
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
                else:
                    # Codex may exit while an MCP or shell child is still running.
                    _kill_process_group(process)
            elapsed = time.monotonic() - started
    finally:
        try:
            _cleanup_docker_mcp_containers(docker_mcp_launches, cleanup_environment)
        except RunnerError as exc:
            cleanup_error = str(exc)
    usage, completed = _usage_from_trace(trace)
    status = ("timeout" if timed_out else
              "completed" if process.returncode == 0 and completed else
              "interrupted" if process.returncode < 0 else "failed")
    result = {
        "status": status,
        "exit_code": process.returncode,
        "elapsed_seconds": round(elapsed, 3),
        "usage": usage,
        "trace": trace.name,
        "stderr": stderr.name,
        "final_answer": final_answer.name if final_answer.exists() else None,
    }
    if cleanup_error is not None:
        result["mcp_cleanup_error"] = cleanup_error
    return result


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
    """Install every bundled Codex skill, then run the agent."""
    try:
        version_probe = subprocess.run(
            [executable, "--version"], capture_output=True, text=True, timeout=10,
        )
        cli_version = (version_probe.stdout.strip() or None
                       if version_probe.returncode == 0 else None)
    except (OSError, subprocess.TimeoutExpired):
        cli_version = None
    installed = _install_skills(servers, trial_dir / "profile")
    result = run_codex(
        configuration, servers, workspace, trial_dir, prompt, timeout_seconds,
        docker_access=docker_access, executable=executable,
    )
    result["activity"] = _activity_from_trace(trial_dir / "agent.jsonl", installed)
    result["cli_version"] = cli_version
    return result, installed
