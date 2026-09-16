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

"""Focused regressions for parent-aware dense retrieval and tokenization."""

import importlib
import sys
from pathlib import Path

import numpy as np

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

search = importlib.import_module("arm_kb_search.search")


class FakeEmbeddingModel:
    def encode(self, queries):
        assert len(queries) == 1
        return np.asarray([[0.0]], dtype=np.float32)


class FakeMatches:
    def __init__(self, keys, distances):
        self.keys = np.asarray(keys)
        self.distances = np.asarray(distances)


class FakeIndex:
    def __init__(self, keys):
        self.keys = keys
        self.calls = []

    def search(self, _query_embedding, count, exact=False):
        self.calls.append((count, exact))
        keys = self.keys[:count]
        return FakeMatches(keys, [0.1] * len(keys))


def test_search_tokenization_canonicalizes_set_up_consistently():
    query = "Set up Docker"

    assert search.normalize_query_for_search(query) == "setup docker"
    assert search.tokenize_for_search(query) == ["setup", "docker"]
    assert search.tokenize_for_search(query) == search.tokenize_for_search(
        search.normalize_query_for_search(query)
    )


def test_embedding_search_resolves_child_window_to_parent_metadata():
    parent = {
        "chunk_uuid": "parent",
        "parent_chunk_uuid": "parent",
        "chunk_index": 1,
        "chunk_count": 2,
        "url": "https://example.com/manual",
        "title": "Manual",
        "original_text": "Complete manual text",
    }
    child = {
        "chunk_uuid": "parent__window_2_of_2",
        "parent_chunk_uuid": "parent",
        "chunk_index": 2,
        "chunk_count": 2,
    }
    index = FakeIndex([1])

    results = search.embedding_search(
        "manual details",
        index,
        [parent, child],
        FakeEmbeddingModel(),
        k=1,
    )

    assert results[0]["metadata"] is parent
    assert results[0]["metadata"]["url"] == "https://example.com/manual"
    assert results[0]["metadata"]["title"] == "Manual"
    assert results[0]["metadata"]["original_text"] == "Complete manual text"
    assert results[0]["matched_window"] == {
        "chunk_uuid": "parent__window_2_of_2",
        "chunk_index": 2,
        "chunk_count": 2,
    }


def test_exact_embedding_search_uses_one_bounded_scan_and_may_return_fewer(monkeypatch):
    metadata = [
        {
            "chunk_uuid": f"shared__window_{index + 1}_of_12",
            "parent_chunk_uuid": "shared",
            "chunk_index": index + 1,
            "chunk_count": 12,
            **(
                {
                    "url": "https://example.com/shared",
                    "title": "Shared",
                    "original_text": "Complete shared text",
                }
                if index == 0
                else {}
            ),
        }
        for index in range(12)
    ]
    index = FakeIndex(list(range(12)))
    monkeypatch.setattr(search, "DENSE_SEARCH_EXACT", True)

    results = search.embedding_search(
        "shared details",
        index,
        metadata,
        FakeEmbeddingModel(),
        k=3,
    )

    assert index.calls == [(12, True)]
    assert len(results) == 1
    assert results[0]["metadata"]["url"] == "https://example.com/shared"
