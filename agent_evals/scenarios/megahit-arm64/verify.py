"""Run the MEGAHIT verifier in a native Linux/AArch64 container."""

import json
import hashlib
import os
import subprocess
import sys
from pathlib import Path


SCENARIO = Path(os.environ["AGENT_EVAL_SCENARIO_DIR"])
WORKSPACE = Path(os.environ["AGENT_EVAL_WORKSPACE"])
SOURCE = Path(os.environ.get("AGENT_EVAL_INPUT_SOURCE", ""))
TRIAL = Path(os.environ["AGENT_EVAL_TRIAL_DIR"])
RESULT = Path(os.environ["AGENT_EVAL_VERIFIER_RESULT"])
IMAGE = "arm-megahit-verifier:local"


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
    current = fixture_hashes(workspace)
    return all(current.get(path) == digest for path, digest in original.items())


def main() -> int:
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
            capture_output=True, text=True, check=True, timeout=30,
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
    try:
        build = subprocess.run(
            ["docker", "build", "-q", "-f", str(SCENARIO / "verifier.Dockerfile"),
             "-t", IMAGE, str(SCENARIO)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
    except OSError as exc:
        RESULT.write_text(json.dumps({"success": False, "stage": "verifier_image_build",
                                      "error": str(exc)}) + "\n")
        return 2
    if build.returncode:
        RESULT.write_text(json.dumps({"success": False, "stage": "verifier_image_build",
                                      "error": build.stdout[-4000:]}) + "\n")
        print(build.stdout[-4000:])
        return 2
    print("Verifier image:", build.stdout.strip())
    try:
        run = subprocess.run(
            ["docker", "run", "--rm", "--network", "none", "--platform", "linux/arm64",
             "-e", f"AGENT_EVAL_NATIVE_ARM={int(native_arm)}",
             "-e", f"AGENT_EVAL_DAEMON_ARCH={architecture}",
             "--mount", f"type=bind,source={WORKSPACE},target=/workspace,readonly",
             "--mount", f"type=bind,source={SOURCE},target=/fixture,readonly",
             "--mount", f"type=bind,source={TRIAL},target=/results",
             "--mount", f"type=bind,source={SCENARIO},target=/scenario,readonly",
             IMAGE, "python3", "/scenario/verify_inside.py"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
    except OSError as exc:
        RESULT.write_text(json.dumps({"success": False, "stage": "verifier_container",
                                      "error": str(exc)}) + "\n")
        return 2
    print(run.stdout[-8000:])
    if not RESULT.exists():
        RESULT.write_text(json.dumps({"success": False, "stage": "verifier_container",
                                      "error": run.stdout[-4000:]}) + "\n")
        return 2
    return run.returncode


if __name__ == "__main__":
    sys.exit(main())
