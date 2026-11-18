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


def image_fingerprint(image: str, platform: str) -> str:
    inspect = ["docker", "buildx", "imagetools", "inspect"]
    result = subprocess.check_output(
        [*inspect, "--format", "{{json .Image}}", "--", image], text=True
    )
    configs = json.loads(result) or {}
    # Buildx omits default variants from the platform keys in its config map.
    aliases = {
        "linux/amd64/v1": "linux/amd64",
        "linux/arm/v7": "linux/arm",
        "linux/arm64/v8": "linux/arm64",
    }
    # Buildx returns a bare config when the image has a single platform.
    if "os" in configs:
        parts = (configs["os"], configs["architecture"], configs.get("variant"))
        key = "/".join(filter(None, parts))
        configs = {aliases.get(key, key): configs}
    config = configs.get(aliases.get(platform, platform))
    if config is None:
        raise ValueError(f"Pinned image {image} does not contain platform {platform}.")
    return (config.get("config", {}).get("Labels") or {}).get(LABEL, "")


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
            "Check for a pending pin-update PR with matching inputs and merge it after review. "
            f"If none is available or its inputs are outdated, run {workflow} on main "
            "with dry_run=false and merge its pin-update PR after review. "
            "Then start a new workflow run from updated main."
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
    try:
        actual = image_fingerprint(args.image, args.platform)
        check(args.kind, expected, actual, args.image)
    except ValueError as error:
        print(f"::error::{error}")
        raise SystemExit(1) from error
    print(f"Pinned {args.kind} image matches this checkout: {expected}")


if __name__ == "__main__":
    main()
