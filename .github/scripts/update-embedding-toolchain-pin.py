#!/usr/bin/env python3
"""Update the immutable embedding toolchain input used by the pipeline."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


REPOSITORY = Path(__file__).resolve().parents[2]
DEFAULT_LOCK = REPOSITORY / "embedding-generation" / "pipeline-inputs.lock.json"
REFERENCE_PATTERN = re.compile(
    r"^ghcr\.io/[A-Za-z0-9_.-]+/mcp-embedding-generator@sha256:[0-9a-f]{64}$"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference", required=True)
    parser.add_argument("--lock-file", type=Path, default=DEFAULT_LOCK)
    return parser.parse_args()


def update_pin(*, reference: str, lock_file: Path) -> None:
    if not REFERENCE_PATTERN.fullmatch(reference):
        raise ValueError(
            f"invalid immutable embedding toolchain reference: {reference}"
        )

    lock = json.loads(lock_file.read_text(encoding="utf-8"))
    if set(lock) != {"generator_image", "intrinsic_chunks_image"}:
        raise ValueError("pipeline input lock does not contain the expected keys")

    lock["generator_image"] = reference
    lock_file.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    args = parse_args()
    update_pin(reference=args.reference, lock_file=args.lock_file)


if __name__ == "__main__":
    main()
