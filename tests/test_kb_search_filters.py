"""Filter contracts and retrieval eligibility, using tiny real search indexes."""

import numpy as np
import pytest
from usearch.index import Index

from arm_kb_search import SearchFilters, SearchResources, search
from arm_kb_search.filters import MetadataFilterIndex
from arm_kb_search.search import (
    bm25_search,
    build_bm25_index,
    embedding_search,
    hybrid_search,
    tokenize_for_search,
)


class QueryModel:
    def __init__(self):
        self.calls = 0

    def encode(self, queries):
        self.calls += 1
        return np.zeros((len(queries), 2), dtype=np.float32)


def chunk(row_id, **metadata):
    return {
        "chunk_uuid": str(row_id),
        "url": f"https://example.com/{row_id}",
        "search_text": "needle",
        **metadata,
    }


def index_for(vectors):
    index = Index(ndim=2, metric="l2sq", dtype="f32")
    index.add(np.arange(len(vectors)), np.asarray(vectors, dtype=np.float32))
    return index


@pytest.mark.parametrize("name", ["doc_type", "product", "platform", "edition"])
def test_filter_matching_normalizes_values_and_excludes_missing_metadata(name):
    metadata = [{name: value} for value in [" Linux ", "LINUX", "windows", "", None, ["linux"]]]
    metadata.append({})
    lookup = MetadataFilterIndex(metadata)
    assert lookup.eligible_ids(SearchFilters.parse({name: " linux "})) == (0, 1)
    assert lookup.eligible_ids(SearchFilters.parse({name: "unknown"})) == ()
    assert metadata[0][name] == " Linux "  # Matching never rewrites returned metadata.


@pytest.mark.parametrize("filters", [None, {}, SearchFilters(), {"edition": None}])
def test_empty_filters_are_unrestricted(filters):
    assert MetadataFilterIndex([{}]).eligible_ids(SearchFilters.parse(filters)) is None


@pytest.mark.parametrize("value", ["", "  ", [], {}, 1, True])
def test_invalid_filter_values(value):
    with pytest.raises(ValueError, match="non-empty string"):
        SearchFilters.parse({"product": value})


@pytest.mark.parametrize("value", [{"typo": "linux"}, "linux", [], False])
def test_invalid_filter_objects(value):
    with pytest.raises(ValueError):
        SearchFilters.parse(value)


def test_combined_filters_apply_before_dashboard_deduplication():
    common = {"doc_type": "Ecosystem Dashboard", "product": "Arm", "content_type": "markdown"}
    metadata = [
        chunk(0, **common, platform="linux", edition="commercial"),
        chunk(1, **common, platform="linux", edition="open-source", url="https://example.com/0"),
        chunk(2, **common, platform="linux", edition="open-source", url="https://example.com/0"),
        chunk(3, **common, platform="windows", edition="open-source"),
        *[chunk(i, search_text="other") for i in range(4, 10)],
    ]
    state = SearchResources(
        metadata, QueryModel(), index_for([[i / 10, 0] for i in range(10)]),
        build_bm25_index(metadata), include_disclaimers=False,
    )
    baseline = search("needle", state, k=10)
    for filters in [None, {}, SearchFilters()]:
        assert search("needle", state, k=10, filters=filters) == baseline
    filters = SearchFilters(
        doc_type=" ecosystem dashboard ", product="ARM", platform="Linux", edition="OPEN-SOURCE"
    )
    hits = search("needle", state, k=10, filters=filters)
    assert len(hits) == 1
    assert (hits[0]["platform"], hits[0]["edition"], hits[0]["product"]) == (
        "linux", "open-source", "Arm"
    )
    calls = state.embedding_model.calls
    assert search("needle", state, filters={"platform": "missing"}) == []
    assert state.embedding_model.calls == calls
    assert search("needle", state, k=10) == baseline  # No shared state mutation.


def test_filtered_dense_search_maps_subset_positions_and_keeps_distance_threshold():
    metadata = [chunk(i) for i in range(4)]
    index = index_for([[0, 0], [0.2, 0], [2, 0], [0.1, 0]])
    hits = embedding_search("needle", index, metadata, QueryModel(), k=10, eligible_ids=(2, 3, 1))
    assert [hit["metadata"]["chunk_uuid"] for hit in hits] == ["3", "1"]
    assert [hit["distance"] for hit in hits] == pytest.approx([0.01, 0.04])
    with pytest.raises(ValueError, match="mismatched chunk IDs"):
        embedding_search("needle", index, metadata, QueryModel(), eligible_ids=(9,))


def test_filtered_bm25_retains_global_scores_and_ranks_only_eligible_ids(monkeypatch):
    metadata = [chunk(i, search_text=text) for i, text in enumerate(
        ["needle needle", "other", "needle other", "other", "other", "other"]
    )]
    bm25 = build_bm25_index(metadata)
    expected_score = bm25.get_scores(tokenize_for_search("needle"))[2]

    def unexpected_full_scoring(_):
        pytest.fail("Filtered requests must score only eligible rows")

    monkeypatch.setattr(bm25, "get_scores", unexpected_full_scoring)
    hits = bm25_search("needle", metadata, bm25, k=1, eligible_ids=(1, 2))
    assert hits[0]["metadata"] == metadata[2]
    assert hits[0]["bm25_score"] == pytest.approx(expected_score)


@pytest.mark.parametrize("branch", ["dense", "lexical", "hybrid"])
def test_selective_filter_finds_chunks_beyond_global_candidate_limits(branch):
    # More than 400 stronger ineligible hits would hide the eligible chunk if
    # filtering happened after dense, sparse, or lexical candidate truncation.
    metadata = [chunk(i, search_text="needle needle needle") for i in range(405)]
    metadata.append(chunk(405, search_text="needle other other other"))
    metadata.extend(chunk(i, search_text="other") for i in range(406, 906))
    index = index_for([[0, 0]] * 405 + [[0.2, 0]] + [[2, 0]] * 500)
    hits = hybrid_search(
        "needle", index if branch != "lexical" else None, metadata, QueryModel(),
        build_bm25_index(metadata) if branch != "dense" else None,
        k=1, candidate_depth=2, eligible_ids=(405,),
    )
    assert [hit["metadata"]["chunk_uuid"] for hit in hits] == ["405"]
    assert bool(hits[0].get("pinned_lexical")) == (branch != "dense")
