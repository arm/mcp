# Copyright © 2026, Arm Limited and Contributors. All rights reserved.
"""Run the MEGAHIT verifier in a native Linux/AArch64 container."""

from __future__ import annotations

import json
import hashlib
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path


SCENARIO = Path(os.environ["AGENT_EVAL_SCENARIO_DIR"])
WORKSPACE = Path(os.environ["AGENT_EVAL_WORKSPACE"])
SOURCE = Path(os.environ.get("AGENT_EVAL_INPUT_SOURCE", ""))
TRIAL = Path(os.environ["AGENT_EVAL_TRIAL_DIR"])
RESULT = Path(os.environ["AGENT_EVAL_VERIFIER_RESULT"])
IMAGE = "arm-megahit-verifier:local"
# The runner stops verifier commands after 1,800 seconds. Reserve time to
# remove a daemon-managed container before that outer deadline.
VERIFIER_BUDGET_SECONDS = 1700


def fixture_hashes(directory: Path) -> dict[str, str]:
    fixture = directory / "test_data"
    if directory.is_symlink() or fixture.is_symlink():
        raise OSError(f"fixture path is a symlink: {fixture}")
    if not fixture.is_dir():
        raise FileNotFoundError(f"missing test data: {fixture}")
    hashes = {}
    for path in sorted(fixture.rglob("*")):
        if path.is_symlink():
            raise OSError(f"fixture path is a symlink: {path}")
        if path.is_file():
            with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as data:
                hashes[str(path.relative_to(fixture))] = hashlib.sha256(data.read()).hexdigest()
    return hashes


def original_fixtures_unchanged(source: Path, workspace: Path) -> bool:
    original = fixture_hashes(source)
    try:
        current = fixture_hashes(workspace)
    except OSError:
        # A missing, unreadable, or replaced fixture in the agent checkout is
        # a failed migration, not a failure to prepare the clean source.
        return False
    return all(current.get(path) == digest for path, digest in original.items())


def _remaining_seconds(deadline: float) -> float:
    return max(0.1, deadline - time.monotonic())


def _remove_container(name: str) -> str | None:
    try:
        removed = subprocess.run(
            ["docker", "rm", "-f", "-v", name], capture_output=True,
            text=True, timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"could not remove verifier container {name}: {exc}"
    if removed.returncode and "No such container" not in removed.stderr:
        return f"could not remove verifier container {name}: {removed.stderr.strip()}"
    return None


def _interrupt_on_sigterm(_signum: int, _frame: object) -> None:
    raise KeyboardInterrupt


def _verifier_user_args(security_options: list[str], host_platform: str,
                        uid: int, gid: int) -> list[str]:
    if host_platform != "linux" or any(option.startswith("name=rootless")
                                        for option in security_options):
        return []
    if any(option.startswith("name=userns") for option in security_options):
        raise RuntimeError("Docker userns-remap cannot write the verifier output mount")
    return ["--user", f"{uid}:{gid}", "-e", "HOME=/results"]


def main() -> int:
    deadline = time.monotonic() + VERIFIER_BUDGET_SECONDS
    if not os.environ.get("AGENT_EVAL_INPUT_SOURCE"):
        RESULT.write_text(json.dumps({"success": False, "stage": "fixture_source",
                                      "error": "missing AGENT_EVAL_INPUT_SOURCE"}) + "\n")
        return 2
    try:
        if not original_fixtures_unchanged(SOURCE, WORKSPACE):
            RESULT.write_text(json.dumps({"success": False, "stage": "fixture_integrity",
                                          "error": "agent checkout changed an original test_data file"}) + "\n")
            return 1
    except OSError as exc:
        RESULT.write_text(json.dumps({"success": False, "stage": "fixture_source",
                                      "error": str(exc)}) + "\n")
        return 2
    try:
        daemon = subprocess.run(
            ["docker", "info", "--format", "{{.Architecture}} {{.OSType}}"],
            capture_output=True, text=True, check=True,
            timeout=min(30, _remaining_seconds(deadline)),
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        RESULT.write_text(json.dumps({"success": False, "stage": "docker_info",
                                      "error": str(exc)}) + "\n")
        return 2
    architecture, _, os_type = daemon.stdout.strip().partition(" ")
    if os_type != "linux":
        RESULT.write_text(json.dumps({"success": False, "stage": "docker_info",
                                      "error": f"expected a Linux Docker daemon, got {daemon.stdout.strip()!r}"}) + "\n")
        return 2
    native_arm = architecture.lower() in ("aarch64", "arm64")
    user_args = []
    if sys.platform == "linux":
        try:
            security = subprocess.run(
                ["docker", "info", "--format", "{{json .SecurityOptions}}"],
                capture_output=True, text=True, check=True,
                timeout=min(30, _remaining_seconds(deadline)),
            )
            options = json.loads(security.stdout)
            if not isinstance(options, list) or not all(isinstance(option, str)
                                                         for option in options):
                raise ValueError("unexpected Docker security options")
            user_args = _verifier_user_args(options, sys.platform, os.getuid(), os.getgid())
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired,
                ValueError, RuntimeError) as exc:
            RESULT.write_text(json.dumps({"success": False, "stage": "docker_info",
                                          "error": str(exc)}) + "\n")
            return 2
    try:
        build = subprocess.run(
            ["docker", "build", "-q", "-f", str(SCENARIO / "verifier.Dockerfile"),
             "-t", IMAGE, str(SCENARIO)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            timeout=_remaining_seconds(deadline),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        RESULT.write_text(json.dumps({"success": False, "stage": "verifier_image_build",
                                      "error": str(exc)}) + "\n")
        return 2
    if build.returncode:
        RESULT.write_text(json.dumps({"success": False, "stage": "verifier_image_build",
                                      "error": build.stdout[-4000:]}) + "\n")
        print(build.stdout[-4000:])
        return 2
    print("Verifier image:", build.stdout.strip())
    output_dir = Path(tempfile.mkdtemp(prefix="verifier-output-", dir=TRIAL))
    container_name = f"arm-megahit-verifier-{uuid.uuid4().hex}"
    try:
        previous_sigterm = signal.signal(signal.SIGTERM, _interrupt_on_sigterm)
        try:
            run = subprocess.run(
                ["docker", "run", "--rm", "--name", container_name,
                 *user_args,
                 "--network", "none", "--platform", "linux/arm64",
                 "-e", f"AGENT_EVAL_NATIVE_ARM={int(native_arm)}",
                 "-e", f"AGENT_EVAL_DAEMON_ARCH={architecture}",
                 "--mount", f"type=bind,source={WORKSPACE},target=/workspace,readonly",
                 "--mount", f"type=bind,source={SOURCE},target=/fixture,readonly",
                 "--mount", f"type=bind,source={output_dir},target=/results",
                 "--mount", f"type=bind,source={SCENARIO},target=/scenario,readonly",
                 IMAGE, "python3", "/scenario/verify_inside.py"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                timeout=_remaining_seconds(deadline),
            )
        finally:
            signal.signal(signal.SIGTERM, previous_sigterm)
    except subprocess.TimeoutExpired as exc:
        cleanup_error = _remove_container(container_name)
        error = f"verifier container timed out: {exc}"
        if cleanup_error:
            error += f"; {cleanup_error}"
        RESULT.write_text(json.dumps({"success": False, "stage": "verifier_container",
                                      "error": error}) + "\n")
        return 2
    except KeyboardInterrupt:
        cleanup_error = _remove_container(container_name)
        if cleanup_error:
            print(cleanup_error, file=sys.stderr)
        raise
    except OSError as exc:
        cleanup_error = _remove_container(container_name)
        error = str(exc)
        if cleanup_error:
            error += f"; {cleanup_error}"
        RESULT.write_text(json.dumps({"success": False, "stage": "verifier_container",
                                      "error": error}) + "\n")
        return 2
    print(run.stdout[-8000:])
    cleanup_error = _remove_container(container_name) if run.returncode else None
    inside_result = output_dir / "verifier.json"
    if inside_result.is_symlink() or not inside_result.is_file():
        error = run.stdout[-4000:]
        if cleanup_error:
            error += f"; {cleanup_error}"
        RESULT.write_text(json.dumps({"success": False, "stage": "verifier_container",
                                      "error": error}) + "\n")
        return 2
    if cleanup_error:
        RESULT.write_text(json.dumps({"success": False, "stage": "verifier_container",
                                      "error": cleanup_error}) + "\n")
        return 2
    try:
        shutil.copyfile(inside_result, RESULT)
    except OSError as exc:
        error = json.dumps({"success": False, "stage": "verifier_container",
                            "error": f"cannot copy verifier result: {exc}"}) + "\n"
        try:
            RESULT.write_text(error)
        except OSError:
            print(error, file=sys.stderr)
        return 2
    return run.returncode


if __name__ == "__main__":
    sys.exit(main())
