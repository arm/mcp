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

"""Query ranking, filter contracts, and retrieval eligibility."""

import importlib

import numpy as np
import pytest
from usearch.index import Index

from arm_kb_search import SearchFilters, SearchResources, resources, search
from arm_kb_search.filters import MetadataFilterIndex
from arm_kb_search.search import (
    bm25_search,
    build_bm25_index,
    embedding_search,
    hybrid_search,
    tokenize_for_search,
)

search_module = importlib.import_module("arm_kb_search.search")


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
    # Keep synthetic ANN fixtures stable across platforms and CPU counts.
    index.add(np.arange(len(vectors)), np.asarray(vectors, dtype=np.float32), threads=1)
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


def test_refill_after_navigation_filtering_stays_within_metadata_filters():
    metadata = [
        chunk(i, platform="linux", original_text="Log an issue" if i < 100 else "Useful needle instructions")
        for i in range(103)
    ]
    metadata.extend(chunk(i, platform="windows", original_text="Useful needle instructions") for i in range(103, 105))
    state = SearchResources(
        metadata, QueryModel(), index_for([[0.1, 0]] * 100 + [[0.2, 0]] * 3 + [[0, 0]] * 2),
        None, include_disclaimers=False,
    )

    hits = search("needle", state, k=3, filters={"platform": "linux"})

    assert len(hits) == 3
    assert all(hit["platform"] == "linux" and hit["snippet"] == "Useful needle instructions" for hit in hits)


def candidate(key, title, url=None, **metadata):
    values = {
        "chunk_uuid": key,
        "title": title,
        "url": url if url is not None else f"https://example.com/{key}/",
        "search_text": title,
    }
    if url is not None:
        values["resolved_url"] = url
    values.update(metadata)
    return {"rrf_score": 0.0, "metadata": values}


def passage(key, title, text, **metadata):
    return {"metadata": {"chunk_uuid": key, "title": title, "heading": title,
                         "url": f"https://example.com/{key}/", "search_text": text,
                         "original_text": text, **metadata}}


def test_url_tokenization_splits_path_separators_but_not_hostname():
    tokens = set(
        search_module.tokenize_url_content_for_search(
            "https://docs.example.com/install-guides/learning-paths/"
            "google-chrome/7-zip"
        )
    )

    assert {
        "install",
        "guides",
        "learning",
        "paths",
        "google",
        "chrome",
        "7",
        "zip",
    } <= tokens
    assert not {"docs", "example", "com"} & tokens


def test_lexical_exactness_ignores_url_hostname():
    matching_host = {
        "url": "https://docs.example.com/install-guides/linux",
        "resolved_url": "https://docs.example.com/install-guides/linux",
    }
    different_host = {
        "url": "https://other.example.com/install-guides/linux",
        "resolved_url": "https://other.example.com/install-guides/linux",
    }

    query = search_module._analyze_query("docs.example.com linux")
    assert search_module._score_lexical_exactness(
        query, matching_host
    ) == search_module._score_lexical_exactness(query, different_host)


@pytest.mark.parametrize("public_url", ["present", "missing", None, ""])
def test_learning_path_root_bonus_requires_learning_path_intent(public_url):
    root = candidate(
        "root",
        "Docker",
        "https://learn.arm.com/learning-paths/servers-and-cloud-computing/docker/",
        doc_type="Learning Paths",
    )
    if public_url != "present":
        del root["metadata"]["url"]
        if public_url != "missing":
            root["metadata"]["url"] = public_url
    other = candidate(
        "other",
        "Docker",
        "https://example.com/docker",
        doc_type="Tutorial",
    )

    ordinary = search_module.rerank_candidates("docker", [root, other])
    explicit = search_module.rerank_candidates("docker learning path", [root, other])
    ordinary_scores = {
        item["metadata"]["chunk_uuid"]: item["rerank_score"] for item in ordinary
    }
    explicit_scores = {
        item["metadata"]["chunk_uuid"]: item["rerank_score"] for item in explicit
    }

    assert ordinary_scores["root"] - ordinary_scores["other"] < 0.5
    assert explicit_scores["root"] - explicit_scores["other"] > 0.5


@pytest.mark.parametrize("field", ["url", "resolved_url"])
@pytest.mark.parametrize("value", [None, "", "missing"])
def test_empty_url_fields_do_not_match_none(field, value):
    metadata = {"title": "Utility", "url": "https://example.com/utility",
                "resolved_url": "https://example.com/utility"}
    if value == "missing":
        metadata.pop(field)
    else:
        metadata[field] = value
    query = search_module._analyze_query("none")
    assert search_module._score_lexical_exactness(query, metadata) == 0.0
    ranked = search_module.rerank_candidates("none", [{"metadata": metadata}])
    assert ranked[0]["rerank_score"] == 0.0
    metadata[field] = "https://example.com/none"
    assert search_module._score_lexical_exactness(query, metadata) > 0.0


@pytest.mark.parametrize("architecture", ["arm64", "aarch64"])
@pytest.mark.parametrize("suffix", ["", " package"])
@pytest.mark.parametrize("stage", ["lexical", "rerank"])
def test_phrase_scoring_treats_architecture_aliases_equally(architecture, suffix, stage):
    query = f"download {architecture}{suffix}"
    analysis = search_module._analyze_query(query)

    def score(title):
        metadata = {"title": title, "url": "https://example.com/utility"}
        if stage == "lexical":
            return search_module._score_lexical_exactness(analysis, metadata)
        # Isolate reranking's phrase bonus from its lexical contribution.
        candidate = {"metadata": metadata, "lexical_exactness_score": 0.0}
        return search_module.rerank_candidates(query, [candidate])[0]["rerank_score"]

    exact = score(f"Download Arm64{suffix}")
    equivalent = score(f"Download AARCH64{suffix}")
    assert exact == pytest.approx(equivalent)
    assert equivalent > score(f"Arm64{suffix} Download")
    assert equivalent > score(f"Download Arm32{suffix}")


@pytest.mark.parametrize("name", ["myaarch64", "aarch64tool", "aarch64_tool"])
def test_phrase_alias_normalization_preserves_larger_names(name):
    title = f"Download {name}"
    assert search_module._field_phrase_bonus(["download", "arm64"], title) == 0.0
    assert search_module._field_phrase_bonus(["download", name], title) == pytest.approx(0.10)


def test_query_tokenization_does_not_grow_with_rerank_candidate_count(monkeypatch):
    query = "install docker on linux"
    original_tokenize = search_module.tokenize_for_search
    query_calls = 0

    def counted_tokenize(text):
        nonlocal query_calls
        if text == query:
            query_calls += 1
        return original_tokenize(text)

    monkeypatch.setattr(search_module, "tokenize_for_search", counted_tokenize)
    candidates = [
        candidate(str(i), "Docker instructions", f"https://example.com/docker/{i}",
                  doc_type="Install Guides")
        for i in range(25)
    ]
    search_module.rerank_candidates(query, candidates[:1])
    single_candidate_calls = query_calls
    query_calls = 0
    results = search_module.rerank_candidates(query, candidates)

    assert len(results) == 25
    assert query_calls == single_candidate_calls


def test_embedding_keeps_original_cli_query():
    class Model:
        def encode(self, texts):
            assert texts == ["Install AWS-CLI!"]
            return np.zeros((1, 2))

    class Index:
        def search(self, _vector, _k, *, exact):
            assert exact is True
            return (np.array([0]), np.array([0.1]))

    metadata = [candidate("aws-cli", "AWS CLI")["metadata"]]
    results = search_module.hybrid_search("Install AWS-CLI!", Index(), metadata, Model(), None, k=1)
    assert results[0]["metadata"]["chunk_uuid"] == "aws-cli"


@pytest.mark.parametrize("intent", ["install", "installing", "installation", "setup", "set up"])
def test_install_preference_requires_product_evidence(intent):
    def delta(title):
        # Generic acquisition keywords must not count as product evidence.
        keywords = "install; build; download"
        plain = candidate("tool", title, doc_type="Tutorial", keywords=keywords)
        guide = candidate("tool", title, doc_type="Install Guides", keywords=keywords)
        a = search_module.rerank_candidates(f"{intent} docker", [plain])[0]["rerank_score"]
        b = search_module.rerank_candidates(f"{intent} docker", [guide])[0]["rerank_score"]
        return b - a

    assert delta("Kubernetes") < 0.10
    assert delta("Install Guide") < 0.10
    assert delta("Docker") > 0.20


def test_navigation_filter_preserves_substantive_next_steps():
    footer = candidate("footer", "Docker", original_text="Document Title: Docker\nHeading Path: Next Steps\n\nLog an issue\nFork and edit\nDiscuss on Discord")
    next_steps = candidate("useful", "Docker", original_text="Next Steps\nRun docker hello-world to verify installation.\nLog an issue")
    results = search_module.rerank_candidates("docker", [footer, next_steps])
    assert [item["metadata"]["chunk_uuid"] for item in results] == ["useful"]


def test_filtered_dense_pool_refills_with_useful_pages():
    class Model:
        def encode(self, _texts):
            return np.zeros((1, 2))

    class Index:
        def search(self, _vector, k, *, exact):
            assert exact is True
            count = min(k, 200)
            return (np.arange(count), np.full(count, 0.2))

    metadata = [
        candidate(str(i), "Target", original_text="Log an issue" if i < 100 else "Useful target instructions")["metadata"]
        for i in range(200)
    ]
    assets = resources.SearchResources(metadata, Model(), Index(), None, include_disclaimers=False)
    results = resources.search("target", assets, k=3)
    assert len(results) == 3
    assert all(item["snippet"] == "Useful target instructions" for item in results)


@pytest.mark.parametrize("query", ["", "  ", "?!"])
def test_empty_query_has_no_results(query):
    assets = resources.SearchResources([], object(), None, None, include_disclaimers=False)
    assert resources.search(query, assets) == []


@pytest.mark.parametrize("architecture", ["arm64", "aarch64"])
@pytest.mark.parametrize("filters", [None, {"platform": "linux"}])
def test_sparse_search_retrieves_architecture_aliases_before_reranking(architecture, filters):
    metadata = [
        chunk(0, search_text=architecture, platform="linux"),
        chunk(1, search_text=architecture, platform="windows"),
        chunk(2, search_text="arm32"),
        chunk(3, search_text="database"),
        chunk(4, search_text="network"),
    ]
    state = SearchResources(metadata, None, None, build_bm25_index(metadata), include_disclaimers=False)
    expected = {"https://example.com/0"} if filters else {"https://example.com/0", "https://example.com/1"}
    for query in ("arm64", "aarch64"):
        hits = search(query, state, k=5, filters=filters)
        assert {hit["url"] for hit in hits} == expected


@pytest.mark.parametrize("query,architecture", [("arm64", "aarch64"), ("aarch64", "arm64")])
def test_architecture_alias_matches_without_conflating_arm32(query, architecture):
    arm32 = passage("old", "Installation", "Download the arm32 package.")
    arm64 = passage("new", "Installation", f"Download the {architecture} package.")
    ranked = search_module.rerank_candidates(query, [arm32, arm64])
    assert ranked[0]["metadata"]["chunk_uuid"] == "new"


@pytest.mark.parametrize("query,alias", [("arm64", "aarch64"), ("aarch64", "arm64")])
@pytest.mark.parametrize("field", ["url", "resolved_url"])
@pytest.mark.parametrize("template", [
    "https://example.com/downloads/{architecture}/",
    "https://example.com/downloads/?architecture={architecture}",
    "https://example.com/downloads/#{architecture}",
])
def test_url_architecture_alias_scores_like_exact_match(query, alias, field, template):
    def metadata(architecture):
        return {
            "title": "Utility downloads",
            "search_text": "Download the utility",
            field: template.format(architecture=architecture),
        }

    exact, equivalent, arm32 = (metadata(architecture) for architecture in (query, alias, "arm32"))
    analysis = search_module._analyze_query(query)
    lexical_scores = [search_module._score_lexical_exactness(analysis, item) for item in (exact, equivalent, arm32)]
    assert lexical_scores[0] == pytest.approx(lexical_scores[1])
    assert lexical_scores[1] > lexical_scores[2]

    # Fix the lexical contribution at zero to test reranking's own URL overlap.
    rerank_scores = [
        search_module.rerank_candidates(query, [{"metadata": item, "lexical_exactness_score": 0.0}])[0]["rerank_score"]
        for item in (exact, equivalent, arm32)
    ]
    assert rerank_scores[0] == pytest.approx(rerank_scores[1])
    assert rerank_scores[1] > rerank_scores[2]


def test_compact_alias_does_not_join_generic_prose():
    plain = passage("plain", "Instructions", "Ordinary instructions.")
    prose = passage("prose", "Set up", "Ordinary instructions.")
    ranked = search_module.rerank_candidates("setup", [plain, prose])
    assert ranked[0]["rerank_score"] == ranked[1]["rerank_score"]


@pytest.mark.parametrize("public_url", ["present", "missing", None, ""])
def test_chapter_navigation_does_not_displace_task_instructions(public_url):
    navigation = passage(
        'nav', 'Run a utility on Arm',
        'Document Title: Run a utility on Arm\nHeading Path: Introduction\n\n'
        'Introduction\nSet up your environment\nRun a utility on Arm\nNext Steps',
        heading_path=['Run a utility on Arm', 'Introduction', 'Set up your environment', 'Run a utility on Arm'],
        url='https://learn.arm.com/learning-paths/servers-and-cloud-computing/utility/#learning-path-step-active',
    )
    navigation["metadata"]["resolved_url"] = navigation["metadata"]["url"]
    if public_url != "present":
        del navigation["metadata"]["url"]
        if public_url != "missing":
            navigation["metadata"]["url"] = public_url
    instructions = passage('useful', 'Utility', 'Run utility --help to check the installation.')
    ranked = search_module.rerank_candidates('run utility on arm', [navigation, instructions])
    assert [r['metadata']['chunk_uuid'] for r in ranked] == ['useful']


@pytest.mark.parametrize("anchor", ["learning-path-title", "learning-path-step-active", "install-guide-title"])
@pytest.mark.parametrize("instructions", [
    "Install the utility, then run utility --help.",
    "Install the utility\nRun utility --help",
    "Install the utility\nRun the utility",
])
def test_substantive_intro_at_navigation_anchor_is_retained(anchor, instructions):
    intro = passage(
        'intro', 'Utility',
        f'Introduction\n{instructions}\nNext Steps',
        url=f'https://learn.arm.com/learning-paths/servers-and-cloud-computing/utility/#{anchor}',
        heading_path=['Utility', 'Introduction'],
    )
    assert search_module.rerank_candidates('utility', [intro])


def test_named_product_outweighs_generic_run_on_arm_title():
    generic = passage(
        'generic', 'Run applications on Arm', 'Run applications on Arm with this tutorial.',
        doc_type='Learning Paths',
        url='https://learn.arm.com/learning-paths/servers-and-cloud-computing/applications/#introduction',
    )
    product = passage('product', 'BuildCLI', 'Download BuildCLI for Linux.', doc_type='Install Guides')
    ranked = search_module.rerank_candidates('run buildcli arm', [generic, product])
    assert ranked[0]['metadata']['chunk_uuid'] == 'product'


@pytest.mark.parametrize("query", [
    "Set up graphcli on an Arm instance",
    "How do I set environment variables and set up graphcli on an Arm instance?",
])
def test_installation_retrieves_relevant_passage_beyond_initial_dense_pool(query):
    metadata = [passage(str(i), 'Other tool', 'Unrelated instructions.')['metadata'] for i in range(140)]
    metadata[120] = passage('correct', 'GraphCLI', 'Install GraphCLI on Linux.', doc_type='Install Guides')['metadata']
    assets = SearchResources(
        metadata, QueryModel(), index_for([[i / 1000, 0] for i in range(len(metadata))]),
        None, include_disclaimers=False,
    )
    result = search(query, assets, k=5)
    assert result[0]['url'] == 'https://example.com/correct/'


def test_installation_subject_is_not_overwhelmed_by_machine_context():
    machine = passage(
        'machine', 'Create an EC2 instance',
        'Set up an Arm based EC2 instance. Create an EC2 instance for your application.',
        heading='Set up your EC2 instance', doc_type='Learning Paths',
    )
    machine.update(bm25_score=15, rrf_score=0.04, lexical_exactness_score=1.2)
    product = passage('product', 'GraphCLI', 'Install GraphCLI on Linux.', doc_type='Install Guides')
    product.update(distance=0.3, rrf_score=0.007)
    ranked = search_module.rerank_candidates('set up graphcli on an arm based ec2 instance', [machine, product])
    assert ranked[0]['metadata']['chunk_uuid'] == 'product'


def test_installation_subject_preserves_explicit_operating_system():
    linux = passage('linux', 'GraphCLI', 'Install GraphCLI on Linux.', doc_type='Install Guides')
    windows = passage('windows', 'GraphCLI', 'Install GraphCLI on Windows.', doc_type='Install Guides')
    ranked = search_module.rerank_candidates('install graphcli on windows', [linux, windows])
    assert ranked[0]['metadata']['chunk_uuid'] == 'windows'
