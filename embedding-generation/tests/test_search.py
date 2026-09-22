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

"""Focused regressions for parent-aware window retrieval."""

import importlib
import sys
from pathlib import Path

import numpy as np

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

search = importlib.import_module("arm_kb_search.search")
resources = importlib.import_module("arm_kb_search.resources")


class FakeEmbeddingModel:
    def encode(self, queries):
        assert len(queries) == 1
        return np.asarray([[0.0]], dtype=np.float32)

    def get_embedding_dimension(self):
        return 1


class FakeMatches:
    def __init__(self, keys, distances):
        self.keys = np.asarray(keys)
        self.distances = np.asarray(distances)


class FakeIndex:
    def __init__(self, keys):
        self.keys = keys
        self.calls = []

    def search(self, _query_embedding, count):
        self.calls.append(count)
        keys = self.keys[:count]
        return FakeMatches(keys, [0.1] * len(keys))


def parent_and_children():
    parent = {
        "chunk_uuid": "parent__window_1_of_3",
        "parent_chunk_uuid": "parent",
        "chunk_index": 1,
        "chunk_count": 3,
        "url": "https://example.com/manual",
        "title": "Manual",
        "original_text": "Complete manual text",
        "search_text": "manual complete text",
    }
    children = [
        {
            "chunk_uuid": f"parent__window_{index}_of_3",
            "parent_chunk_uuid": "parent",
            "chunk_index": index,
            "chunk_count": 3,
        }
        for index in (2, 3)
    ]
    return parent, children


def test_embedding_search_resolves_child_window_to_parent_metadata():
    parent, children = parent_and_children()
    index = FakeIndex([1])

    results = search.embedding_search(
        "manual details",
        index,
        [parent, *children],
        FakeEmbeddingModel(),
        k=1,
    )

    assert results[0]["metadata"] is parent
    assert results[0]["metadata"]["original_text"] == "Complete manual text"
    assert results[0]["matched_window"] == {
        "chunk_uuid": "parent__window_2_of_3",
        "chunk_index": 2,
        "chunk_count": 3,
    }


def test_embedding_search_deduplicates_sibling_windows():
    parent, children = parent_and_children()
    other = {
        "chunk_uuid": "other",
        "url": "https://example.com/other",
        "title": "Other",
        "original_text": "Other complete text",
        "search_text": "other complete text",
    }
    index = FakeIndex([1, 2, 3])

    results = search.embedding_search(
        "details",
        index,
        [parent, *children, other],
        FakeEmbeddingModel(),
        k=2,
    )

    assert [result["metadata"] for result in results] == [parent, other]
    assert len({search._candidate_key(result) for result in results}) == 2


def test_bm25_indexes_only_parent_representatives():
    parent, children = parent_and_children()
    other = {
        "chunk_uuid": "other",
        "search_text": "other document",
    }
    metadata = [parent, *children, other]

    bm25 = search.build_bm25_index(metadata)
    scores = bm25.get_scores(["manual"])

    assert len(scores) == len(metadata)
    assert scores[1] == scores[2] == 0
    assert bm25.metadata_indices.tolist() == [0, 3]


def test_parent_index_prefers_first_window_even_when_rows_are_reordered():
    parent, children = parent_and_children()
    metadata = [children[0], parent, children[1]]

    assert search.build_parent_index(metadata) == {"parent": parent}


def test_resource_loading_rejects_index_metadata_count_mismatch(monkeypatch):
    monkeypatch.setattr(resources, "load_metadata", lambda _path: [{"chunk_uuid": "a"}])
    monkeypatch.setattr(
        resources,
        "load_embedding_model",
        lambda *_args, **_kwargs: FakeEmbeddingModel(),
    )
    monkeypatch.setattr(
        resources,
        "load_usearch_index",
        lambda *_args, **_kwargs: [object(), object()],
    )

    with np.testing.assert_raises_regex(ValueError, "2 vectors for 1 metadata rows"):
        resources.load_search_resources("metadata.json", "index.bin")
