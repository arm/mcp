"""Fingerprint image inputs, or require a pinned image to match this checkout."""

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LABEL = "com.arm.mcp.build-input-fingerprint"
INPUTS = {
    "toolchain": (
        "embedding-generation/.dockerignore",
        "embedding-generation/.python-version",
        "embedding-generation/Dockerfile.toolchain",
        "embedding-generation/acquire-model.py",
        "embedding-generation/embedding-model.lock.json",
        "embedding-generation/pyproject.toml",
        "embedding-generation/uv.lock",
    ),
    "mcp-inputs": (
        "pyproject.toml",
        "mcp-local/.dockerignore",
        "mcp-local/.python-version",
        "mcp-local/Dockerfile.inputs",
        "mcp-local/pyproject.toml",
        "mcp-local/scripts/stage-build-inputs.py",
        "mcp-local/uv.lock",
        "mcp-local/build-inputs.lock.json",
    ),
}


def fingerprint(kind: str, root: Path = ROOT) -> str:
    inputs = {}
    for name in (*INPUTS[kind], ".github/scripts/build-input-fingerprint.py"):
        content = (root / name).read_bytes()
        if name == "mcp-local/build-inputs.lock.json":
            lock = json.loads(content)
            # Promotions change these records, not the bundle's acquired inputs.
            for key in ("embeddings", "mcp_build_inputs"):
                lock["container_images"].pop(key, None)
            content = json.dumps(lock, sort_keys=True).encode()
        inputs[name] = hashlib.sha256(content).hexdigest()
    return hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()


def check(kind: str, expected: str, actual: str, image: str) -> None:
    if actual != expected:
        workflow = (
            "build-embedding-toolchain.yml"
            if kind == "toolchain"
            else "build-mcp-inputs.yml"
        )
        raise ValueError(
            f"Pinned {kind} image is stale or missing its fingerprint: {image}. "
            f"Expected {expected}; found {actual or 'missing'}. "
            f"Run {workflow} on main with dry_run=false, merge its pin-update PR, "
            "then rerun this workflow."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=INPUTS)
    parser.add_argument(
        "--image",
        help="Check this digest-pinned image instead of printing a fingerprint",
    )
    parser.add_argument("--platform", default="linux/arm64")
    args = parser.parse_args()
    expected = fingerprint(args.kind)
    if not args.image:
        print(expected)
        return
    if not re.fullmatch(r"[^@\s]+@sha256:[0-9a-f]{64}", args.image):
        parser.error("--image must be pinned by sha256 digest")
    subprocess.run(
        ["docker", "pull", "--platform", args.platform, args.image], check=True
    )
    result = subprocess.check_output(
        ["docker", "image", "inspect", args.image], text=True
    )
    actual = (json.loads(result)[0]["Config"].get("Labels") or {}).get(LABEL, "")
    try:
        check(args.kind, expected, actual, args.image)
    except ValueError as error:
        print(f"::error::{error}")
        raise SystemExit(1) from error
    print(f"Pinned {args.kind} image matches this checkout: {expected}")


if __name__ == "__main__":
    main()
