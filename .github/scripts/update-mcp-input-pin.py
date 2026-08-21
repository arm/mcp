#!/usr/bin/env python3
"""Keep the checked-in MCP build-input image pins synchronized."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


REPOSITORY = Path(__file__).resolve().parents[2]
DEFAULT_LOCK = REPOSITORY / "mcp-local" / "build-inputs.lock.json"
DEFAULT_DOCKERFILE = REPOSITORY / "mcp-local" / "Dockerfile"
REFERENCE_PATTERN = re.compile(
    r"^ghcr\.io/[A-Za-z0-9_.-]+/mcp-build-inputs@sha256:[0-9a-f]{64}$"
)
REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", required=True)
    parser.add_argument("--amd64-reference", required=True)
    parser.add_argument("--arm64-reference", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--workflow-run", required=True)
    parser.add_argument("--lock-file", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--dockerfile", type=Path, default=DEFAULT_DOCKERFILE)
    return parser.parse_args()


def update_pin(
    *,
    reference: str,
    amd64_reference: str,
    arm64_reference: str,
    source_revision: str,
    workflow_run: str,
    lock_file: Path,
    dockerfile: Path,
) -> None:
    references = (reference, amd64_reference, arm64_reference)
    if not all(REFERENCE_PATTERN.fullmatch(value) for value in references):
        raise ValueError("invalid immutable MCP build-input reference")
    if len(set(references)) != len(references):
        raise ValueError("index and architecture references must be distinct")
    if not REVISION_PATTERN.fullmatch(source_revision):
        raise ValueError(f"invalid source revision: {source_revision}")
    if not workflow_run.isdigit():
        raise ValueError(f"invalid workflow run ID: {workflow_run}")

    lock = json.loads(lock_file.read_text(encoding="utf-8"))
    build_inputs = lock["container_images"]["mcp_build_inputs"]
    if set(build_inputs["manifests"]) != {"amd64", "arm64"}:
        raise ValueError("MCP build-input manifest does not cover amd64 and arm64")

    previous_reference = build_inputs["reference"]
    previous_arg = f"ARG MCP_BUILD_INPUTS_IMAGE={previous_reference}"
    dockerfile_text = dockerfile.read_text(encoding="utf-8")
    if dockerfile_text.count(previous_arg) != 1:
        raise RuntimeError(
            "Dockerfile MCP_BUILD_INPUTS_IMAGE does not match the checked-in manifest"
        )

    # Re-running the same source revision can reproduce the exact image index.
    # Keep the reviewed provenance in that case instead of opening a metadata-only
    # promotion PR for a new workflow run.
    if reference == previous_reference:
        return

    build_inputs["reference"] = reference
    build_inputs["manifests"] = {
        "amd64": amd64_reference,
        "arm64": arm64_reference,
    }
    build_inputs["source_revision"] = source_revision
    build_inputs["workflow_run"] = workflow_run
    lock_file.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    dockerfile.write_text(
        dockerfile_text.replace(
            previous_arg, f"ARG MCP_BUILD_INPUTS_IMAGE={reference}"
        ),
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    update_pin(
        reference=args.reference,
        amd64_reference=args.amd64_reference,
        arm64_reference=args.arm64_reference,
        source_revision=args.source_revision,
        workflow_run=args.workflow_run,
        lock_file=args.lock_file,
        dockerfile=args.dockerfile,
    )


if __name__ == "__main__":
    main()
