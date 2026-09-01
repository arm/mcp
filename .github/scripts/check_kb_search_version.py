#!/usr/bin/env python3
"""Require package input changes to increase the arm-kb-search version."""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Iterable

import tomllib

PACKAGE_DIRECTORIES = ("arm_kb_search/",)
PACKAGE_FILES = {"LICENSE", "MANIFEST.in", "pyproject.toml"}


def project_version(project_text: str) -> tuple[int, int, int]:
    try:
        project = tomllib.loads(project_text)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError("invalid pyproject.toml") from exc
    try:
        version = project["project"]["version"]
    except (KeyError, TypeError) as exc:
        raise ValueError("pyproject.toml must define [project].version") from exc
    try:
        parts = tuple(int(part) for part in version.split("."))
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"invalid arm-kb-search version: {version}") from exc
    if len(parts) != 3 or any(part < 0 for part in parts):
        raise ValueError(f"invalid arm-kb-search version: {version}")
    return parts


def format_version(version: tuple[int, int, int]) -> str:
    return ".".join(map(str, version))


def is_package_input(path: str) -> bool:
    return path in PACKAGE_FILES or path.startswith(PACKAGE_DIRECTORIES)


def relevant_package_changes(changed_paths: Iterable[str]) -> list[str]:
    return sorted({path for path in changed_paths if is_package_input(path)})


def validate_version_change(
    changed_paths: Iterable[str],
    base_version: tuple[int, int, int],
    head_version: tuple[int, int, int],
) -> list[str]:
    relevant_changes = relevant_package_changes(changed_paths)
    if not relevant_changes:
        return []
    if head_version <= base_version:
        changed = ", ".join(relevant_changes)
        raise ValueError(
            "arm-kb-search package inputs changed without a version increase "
            f"({format_version(base_version)} -> {format_version(head_version)}): "
            f"{changed}. Increase the [project] version in pyproject.toml."
        )
    return relevant_changes


def git_output(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def changed_paths(base_ref: str, head_ref: str) -> list[str]:
    output = git_output("diff", "--name-only", f"{base_ref}...{head_ref}", "--")
    return [line for line in output.splitlines() if line]


def project_text_at(ref: str) -> str:
    return git_output("show", f"{ref}:pyproject.toml")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-ref", required=True)
    parser.add_argument("--head-ref", default="HEAD")
    args = parser.parse_args()

    try:
        paths = changed_paths(args.base_ref, args.head_ref)
        base_version = project_version(project_text_at(args.base_ref))
        head_version = project_version(project_text_at(args.head_ref))
        relevant_changes = validate_version_change(paths, base_version, head_version)
    except ValueError as exc:
        print(f"::error title=arm-kb-search version::{exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    if relevant_changes:
        print(
            "arm-kb-search package inputs changed and version increased: "
            f"{format_version(base_version)} -> {format_version(head_version)}"
        )
        for path in relevant_changes:
            print(f"- {path}")
    else:
        print("No arm-kb-search package inputs changed.")


if __name__ == "__main__":
    main()
