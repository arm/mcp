# Copyright © 2025, Arm Limited and Contributors. All rights reserved.
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

from typing import Dict, List, Optional
import json
import os

from usearch.index import Index


def load_usearch_index(index_path: str, dimension: int) -> Optional[Index]:
    """Load USearch index from file."""
    if not os.path.exists(index_path):
        print(f"Error: USearch index file '{index_path}' does not exist.")
        return None
    if dimension <= 0:
        print("Error: Invalid embedding dimension.")
        return None
    index = Index(
        ndim=dimension,
        metric="l2sq",
        dtype="f32",
        connectivity=16,
        expansion_add=128,
        expansion_search=64,
    )
    index.load(index_path)
    return index


def load_metadata(metadata_path: str) -> List[Dict]:
    """Load metadata from JSON file."""
    if not os.path.exists(metadata_path):
        print(f"Error: Metadata file '{metadata_path}' does not exist.")
        return []
    with open(metadata_path, "r") as file:
        return json.load(file)
