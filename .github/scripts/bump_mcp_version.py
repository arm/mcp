#!/usr/bin/env python3
"""Update the MCP server metadata to a reviewed release version."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


REPOSITORY = Path(__file__).resolve().parents[2]
DEFAULT_SERVER_FILE = REPOSITORY / "mcp-local" / "server.json"
RELEASE_IMAGE = "docker.io/armlimited/arm-mcp"


def prepare_version_bump(server_file: Path, bump_type: str) -> tuple[dict, str]:
    server = json.loads(server_file.read_text(encoding="utf-8"))
    current_version = server.get("version")
    match = re.fullmatch(r"([0-9]+)\.([0-9]+)\.([0-9]+)", current_version or "")
    if not match:
        raise ValueError(f"invalid MCP release version: {current_version}")

    current_identifier = f"{RELEASE_IMAGE}:{current_version}"
    release_packages = [
        package
        for package in server.get("packages", [])
        if package.get("registryType") == "oci"
        and package.get("identifier") == current_identifier
    ]
    if len(release_packages) != 1:
        raise ValueError(
            f"server.json must contain exactly one OCI package for {current_identifier}"
        )

    major, minor, patch = (int(part) for part in match.groups())
    if bump_type == "major":
        next_version = f"{major + 1}.0.0"
    elif bump_type == "minor":
        next_version = f"{major}.{minor + 1}.0"
    elif bump_type == "hotfix":
        next_version = f"{major}.{minor}.{patch + 1}"
    else:
        raise ValueError(f"unsupported release type: {bump_type}")

    server["version"] = next_version
    release_packages[0]["identifier"] = f"{RELEASE_IMAGE}:{next_version}"
    return server, next_version


def write_version_bump(server_file: Path, bump_type: str) -> str:
    server, next_version = prepare_version_bump(server_file, bump_type)
    server_file.write_text(json.dumps(server, indent=2) + "\n", encoding="utf-8")
    return next_version


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--bump-type", choices=("major", "minor", "hotfix"), required=True
    )
    parser.add_argument("--server-file", type=Path, default=DEFAULT_SERVER_FILE)
    args = parser.parse_args()
    print(write_version_bump(args.server_file, args.bump_type))


if __name__ == "__main__":
    main()
