#!/usr/bin/env python3
"""Prepare a reviewed MCP release by pinning embeddings and bumping version."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from bump_mcp_version import prepare_version_bump


REPOSITORY = Path(__file__).resolve().parents[2]
DEFAULT_LOCK = REPOSITORY / "mcp-local" / "build-inputs.lock.json"
DEFAULT_DOCKERFILE = REPOSITORY / "mcp-local" / "Dockerfile"
DEFAULT_SERVER_FILE = REPOSITORY / "mcp-local" / "server.json"
REFERENCE_PATTERN = re.compile(
    r"^ghcr\.io/[A-Za-z0-9_.-]+/mcp-embedding-vectorstore@sha256:[0-9a-f]{64}$"
)
REVISION_PATTERN = re.compile(r"^[0-9a-f]{40}$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--workflow-run", required=True)
    parser.add_argument("--lock-file", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--dockerfile", type=Path, default=DEFAULT_DOCKERFILE)
    parser.add_argument("--server-file", type=Path, default=DEFAULT_SERVER_FILE)
    return parser.parse_args()


def update_pin(
    *,
    reference: str,
    source_revision: str,
    workflow_run: str,
    lock_file: Path,
    dockerfile: Path,
    server_file: Path,
) -> None:
    if not REFERENCE_PATTERN.fullmatch(reference):
        raise ValueError(f"invalid immutable embedding reference: {reference}")
    if not REVISION_PATTERN.fullmatch(source_revision):
        raise ValueError(f"invalid source revision: {source_revision}")
    if not workflow_run.isdigit():
        raise ValueError(f"invalid workflow run ID: {workflow_run}")

    lock = json.loads(lock_file.read_text(encoding="utf-8"))
    embeddings = lock["container_images"]["embeddings"]
    previous_reference = embeddings["reference"]

    # A new workflow run can reproduce the exact image digest. Preserve the
    # reviewed provenance and release version in that case: there is no new
    # build input to promote.
    if reference == previous_reference:
        return

    previous_arg = f"ARG EMBEDDINGS_IMAGE={previous_reference}"

    dockerfile_text = dockerfile.read_text(encoding="utf-8")
    if dockerfile_text.count(previous_arg) != 1:
        raise RuntimeError(
            "Dockerfile EMBEDDINGS_IMAGE does not match the checked-in manifest"
        )

    server, next_version = prepare_version_bump(server_file, "minor")

    embeddings["reference"] = reference
    embeddings["source_revision"] = source_revision
    embeddings["workflow_run"] = workflow_run
    lock_file.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    dockerfile.write_text(
        dockerfile_text.replace(previous_arg, f"ARG EMBEDDINGS_IMAGE={reference}"),
        encoding="utf-8",
    )
    server_file.write_text(json.dumps(server, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    update_pin(
        reference=args.reference,
        source_revision=args.source_revision,
        workflow_run=args.workflow_run,
        lock_file=args.lock_file,
        dockerfile=args.dockerfile,
        server_file=args.server_file,
    )


if __name__ == "__main__":
    main()
