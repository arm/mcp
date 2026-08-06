# Copyright © 2026, Arm Limited and Contributors. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Acquire the embedding model at the revision recorded in its lock file.

This script is intentionally network-capable. Run it only during the controlled
generator-image build phase. Vector generation and the MCP runtime load the
resulting local directory and do not read or resolve the remote model lock.
"""

import argparse
import json
from pathlib import Path

from sentence_transformers import SentenceTransformer


def acquire_model(lock_path: Path, output_dir: Path) -> None:
    """Download the locked model and save a self-contained local copy."""
    model_lock = json.loads(lock_path.read_text(encoding="utf-8"))
    model = SentenceTransformer(
        model_lock["model_id"],
        revision=model_lock["revision"],
        trust_remote_code=False,
    )
    model.save_pretrained(str(output_dir), safe_serialization=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download the embedding model at its locked revision."
    )
    parser.add_argument(
        "--lock",
        type=Path,
        default=Path("embedding-model.lock.json"),
        help="Path to the embedding-model lock manifest.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Directory where the local model will be written.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    acquire_model(args.lock, args.output)


if __name__ == "__main__":
    main()
