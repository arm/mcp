#!/usr/bin/env python3
"""Keep the checked-in MCP embedding image pins synchronized."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


REPOSITORY = Path(__file__).resolve().parents[2]
DEFAULT_LOCK = REPOSITORY / "mcp-local" / "build-inputs.lock.json"
DEFAULT_DOCKERFILE = REPOSITORY / "mcp-local" / "Dockerfile"
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
    return parser.parse_args()


def update_pin(
    *,
    reference: str,
    source_revision: str,
    workflow_run: str,
    lock_file: Path,
    dockerfile: Path,
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
    previous_arg = f"ARG EMBEDDINGS_IMAGE={previous_reference}"

    dockerfile_text = dockerfile.read_text(encoding="utf-8")
    if dockerfile_text.count(previous_arg) != 1:
        raise RuntimeError(
            "Dockerfile EMBEDDINGS_IMAGE does not match the checked-in manifest"
        )

    embeddings["reference"] = reference
    embeddings["source_revision"] = source_revision
    embeddings["workflow_run"] = workflow_run
    lock_file.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    dockerfile.write_text(
        dockerfile_text.replace(previous_arg, f"ARG EMBEDDINGS_IMAGE={reference}"),
        encoding="utf-8",
    )


def main() -> None:
    args = parse_args()
    update_pin(
        reference=args.reference,
        source_revision=args.source_revision,
        workflow_run=args.workflow_run,
        lock_file=args.lock_file,
        dockerfile=args.dockerfile,
    )


if __name__ == "__main__":
    main()
