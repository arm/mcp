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
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
from rank_bm25 import BM25Okapi
from usearch.index import Index

from arm_kb_search import SearchFilters, SearchResources, resources, search
from arm_kb_search.analysis import Synonyms, analyze, atom, name_keys
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

    def get_sentence_embedding_dimension(self):
        return 2


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


@pytest.mark.parametrize("rules", [{}, {"awscli": ["aws cli", "awscli"]}])
def test_embedding_keeps_original_cli_query(rules):
    class Model:
        def encode(self, texts):
            assert texts == ["Install AWS-CLI!"]
            return np.zeros((1, 2))

    class Index:
        def search(self, _vector, _k, *, exact):
            assert exact is True
            return (np.array([0]), np.array([0.1]))

    metadata = [candidate("aws-cli", "AWS CLI")["metadata"]]
    results = search_module.hybrid_search(
        "Install AWS-CLI!", Index(), metadata, Model(), None, k=1, synonyms=Synonyms(rules),
    )
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


def intrinsic(name="svld1ub_u32", isa="SVE", signature="svuint32_t svld1ub_u32(svbool_t pg, const uint8_t *base);"):
    text = f"The intrinsic is part of the {isa} instruction set architecture. The signature is as follows:\n`{signature}`"
    record = passage(name, name, text, doc_type="Intrinsic", product=isa)
    record["metadata"]["search_text"] = f"Arm Intrinsics - {name} {isa} {name} Intrinsic {isa} {text}"
    return record


def test_technical_evidence_preserves_internal_punctuation():
    tokens = tokenize_for_search("Node.js. C++. 3.12.2. arm_neon.h. vaddq_u8... __ARM_FEATURE_SVE.")
    assert search_module._evidence_tokens(tokens) == [
        "node.js", "c++", "3.12.2", "arm_neon.h", "vaddq_u8", "__arm_feature_sve",
    ]
    assert "node.js." in tokens  # Ordinary BM25 tokens are not rewritten.
    query = search_module._analyze_query("SME2 ZA svbool_t uint8x16_t x86_64 svmopa_za32_m.")
    assert query.intrinsic_isas == {"sme"}
    assert query.acle_types == {"svbool_t", "uint8x16_t"}
    assert query.code_identifiers == {"svmopa_za32_m"}


def test_typed_intrinsic_question_prefers_reference_to_general_guide():
    card = intrinsic()
    guide = passage("guide", "SVE loads", "SVE intrinsics can load bytes into a svuint32_t vector.", doc_type="Tutorial")
    query = search_module._analyze_query("Which SVE intrinsic loads uint8_t into svuint32_t?")
    assert search_module._rerank_candidates(query, [guide, card])[0]["metadata"] == card["metadata"]
    control = replace(query, intrinsic_query=False)
    assert search_module._rerank_candidates(control, [guide, card])[0]["metadata"] == guide["metadata"]


@pytest.mark.parametrize("question,isa,matching_type,other_type,argument,other_bonus", [
    ("SVE intrinsic loading uint8_t into svuint32_t.", "SVE", "svuint32_t", "svint32_t", "uint8_t a", .225),
    ("SVE intrinsic for uint32_t.", "SVE", "svuint32_t", "svint32_t", "void", .10),
    ("Neon intrinsic returning poly128_t.", "Neon", "poly128_t", "poly16x8_t", "void", .10),
    ("Neon intrinsic returning float32x4_t.", "Neon", "float32x4_t", "float16x8_t", "void", .10),
    ("SVE intrinsic returning svbool_t.", "SVE", "svbool_t", "svuint32_t", "void", .10),
])
def test_signature_types_distinguish_candidates(question, isa, matching_type, other_type, argument, other_bonus):
    query = search_module._analyze_query(question)
    matching = intrinsic("matching", isa, f"{matching_type} matching({argument});")
    other = intrinsic("other", isa, f"{other_type} other({argument});")
    assert search_module._reference_record_bonus(query, matching["metadata"], "intrinsic") == pytest.approx(.35)
    assert search_module._reference_record_bonus(query, other["metadata"], "intrinsic") == pytest.approx(other_bonus)
    # Equal prose evidence makes ordering depend on the signature types.
    matching["metadata"]["search_text"] = other["metadata"]["search_text"] = f"{isa} operations"
    assert search_module._rerank_candidates(query, [other, matching])[0]["metadata"] == matching["metadata"]
    control = replace(query, acle_types=set())
    assert search_module._rerank_candidates(control, [other, matching])[0]["metadata"] == other["metadata"]


@pytest.mark.parametrize("question,expected", [
    ("Which Neon intrinsic loads uint8_t?", 0), ("Which SME intrinsic loads uint8_t?", 0),
    ("Which SME intrinsic works with SVE uint8_t vectors?", 0),
    ("Which intrinsic loads bytes?", 0), ("Which SVE load reads bytes?", 0),
    ("Which SVE intrinsic returns svuint256_t?", .10),
])
def test_intrinsic_bonus_requires_intent_isa_and_signature_evidence(question, expected):
    query = search_module._analyze_query(question)
    assert search_module._reference_record_bonus(query, intrinsic()["metadata"], "intrinsic") == expected


@pytest.mark.parametrize("separator", ["\r\n", " ", "\n\n"])
def test_signature_evidence_accepts_acquisition_whitespace(separator):
    record = intrinsic()["metadata"]
    record["original_text"] = record["original_text"].replace("follows:\n", "follows:" + separator)
    query = search_module._analyze_query("SVE intrinsic for svuint32_t")
    assert search_module._reference_record_bonus(query, record, "intrinsic") == .35


@pytest.mark.parametrize("name,text,expected", [
    ("svmopa_za32_m", "Use svmopa_za32_m...", .30),
    ("svadd_f32_m", "Use svadd[_f32]_m.", .30),
    ("svadd[_f32]_m", "Use svadd_f32_m.", .30),
    ("svmopa_za32_m", None, 0), ("svmopa_za32_m", "", 0),
])
def test_identifier_evidence_handles_catalog_spelling_punctuation_and_empty_text(name, text, expected):
    record = passage("api", "API guide", text, doc_type="Documentation")
    query = search_module._analyze_query(f"How do I use {name}.")
    score = search_module._rerank_candidates(query, [record])[0]["rerank_score"]
    control = search_module._rerank_candidates(replace(query, code_identifiers=set()), [record])[0]["rerank_score"]
    assert score - control == pytest.approx(expected)


def test_exact_api_identifier_overcomes_a_generic_competitor():
    query = search_module._analyze_query("Why does svmopa_za32_m take two predicates for outer product accumulation?")
    exact = passage("exact", "Matrix API", "Use svmopa_za32_m with row and column masks.", doc_type="Documentation")
    generic = passage("generic", "Matrix API", "Two predicates for outer product accumulation.", doc_type="Documentation")
    assert search_module._rerank_candidates(query, [generic, exact])[0]["metadata"] == exact["metadata"]
    control = replace(query, code_identifiers=set())
    assert search_module._rerank_candidates(control, [generic, exact])[0]["metadata"] == generic["metadata"]


@pytest.mark.parametrize("catalog_name,query_format", [
    ("svqrdmulh[_s32]", "How do I call {}?"), ("svadd[_f32]_m", "{}..."),
    ("svst1_scatter[_u32base]_index[_s32]", "{}..."),
    ("vaddq_u8", '"{}".'), ("svcntb", "`{}`."), ("__crc32b", "{}"),
])
@pytest.mark.parametrize("count", [1, 2])
def test_canonical_names_survive_public_search_and_filters(catalog_name, query_format, count):
    target = intrinsic(catalog_name)["metadata"]
    metadata = [target, intrinsic("unrelated_name")["metadata"]][:count]
    index = build_bm25_index(metadata)
    assets = SearchResources(metadata, object(), None, index, include_disclaimers=False)
    for name in dict.fromkeys([catalog_name, catalog_name.replace("[", "").replace("]", "")]):
        query = query_format.format(name)
        analysis = search_module._analyze_query(query)
        assert search_module._reference_record_bonus(analysis, target, "intrinsic") == .45
        assert [hit["url"] for hit in search(query, assets, k=1)] == [target["url"]]
        assert hybrid_search(query, None, metadata, object(), index, k=1, eligible_ids=(0,))[0]["metadata"] == target
        assert all(hit["metadata"] != target for hit in
                   hybrid_search(query, None, metadata, object(), index, eligible_ids=tuple(range(1, count))))


@pytest.mark.parametrize("query", ["svadd[_f32]_m.extra", "svadd[_f32]_missing", "svadd[_f32_m"])
def test_partial_catalog_names_do_not_receive_exact_bonus(query):
    record = intrinsic("svadd[_f32]_m")["metadata"]
    assert search_module._reference_record_bonus(search_module._analyze_query(query), record, "intrinsic") == 0


@pytest.mark.parametrize("count", [1, 2])
def test_exact_names_have_positive_scores_when_all_records_share_a_name(count):
    metadata = [intrinsic("svadd[_f32]_m")["metadata"] for _ in range(count)]
    hits = bm25_search("svadd_f32_m.", metadata, build_bm25_index(metadata))
    assert len(hits) == count
    assert all(hit["bm25_score"] > 0 for hit in hits)


def test_canonical_name_indexing_does_not_rewrite_other_document_types():
    metadata = [chunk(i, doc_type="Documentation", heading=text, search_text=text)
                for i, text in enumerate(["example[_s32]", "Other documentation", "Additional advice"])]
    assert bm25_search("example_s32", metadata, build_bm25_index(metadata)) == []


@pytest.mark.parametrize("query", ["SVE load vector.", "svqrdmulh", "svmissing_s32.", "svqrdmulh_s32.extra"])
def test_alias_channel_leaves_nonmatching_sparse_scores_identical(query):
    metadata = [intrinsic("svqrdmulh[_s32]")["metadata"], chunk(1, search_text="SVE load vector examples")]
    original = BM25Okapi([search_module._bm25_tokens(row["search_text"]) for row in metadata])
    actual = build_bm25_index(metadata)
    tokens = search_module._bm25_tokens(query)
    np.testing.assert_array_equal(actual.get_scores(tokens), original.get_scores(tokens))
    np.testing.assert_array_equal(actual.get_batch_scores(tokens, [0]), original.get_batch_scores(tokens, [0]))


@pytest.mark.parametrize("with_intrinsics", [False, True])
def test_full_sparse_scores_match_filtered_scores_without_using_batch_scoring(monkeypatch, with_intrinsics):
    metadata = [chunk(0, search_text="SVE arithmetic examples")]
    if with_intrinsics:
        metadata.append(intrinsic("svadd[_f32]_m")["metadata"])
    index = build_bm25_index(metadata)
    queries = [[], ["sve", "arithmetic"], ["svadd_f32_m."], ["svadd[_f32]_m"],
               ["svadd_f32_m", "svadd_f32_m"], ["unknown_name"]]
    selections = [list(range(len(metadata))), [len(metadata) - 1, 0, 0], []]
    expected = [[index.get_batch_scores(query, ids) for ids in selections] for query in queries]

    def reject_batch_scoring(*args, **kwargs):
        pytest.fail("Full-corpus scoring must use the vectorized get_scores path")

    monkeypatch.setattr(index, "get_batch_scores", reject_batch_scoring)
    if index.alias_index:
        monkeypatch.setattr(index.alias_index, "get_batch_scores", reject_batch_scoring)
    for query, batches in zip(queries, expected):
        scores = index.get_scores(query)
        for ids, batch in zip(selections, batches):
            np.testing.assert_array_equal(scores[ids], batch)


def test_sparse_name_evidence_survives_a_large_non_intrinsic_corpus():
    target = intrinsic("svqrdmulh[_s32]")["metadata"]
    metadata = [chunk(i, search_text="rounding halfway values") for i in range(450)]
    metadata.extend(chunk(i + 450, search_text="Unrelated advice") for i in range(50))
    metadata.append(target)
    hits = hybrid_search("svqrdmulh_s32 rounding halfway values", None, metadata, object(),
                         build_bm25_index(metadata), k=5)
    assert any(hit["metadata"] == target for hit in hits)


def test_preserving_catalog_names_does_not_repeat_prose_query_terms():
    metadata = [intrinsic("svadd[_f32]_m")["metadata"]] + [chunk(i, search_text="Unrelated advice") for i in range(5)]
    # A plain prose index deliberately has no canonical-name channel.
    index = BM25Okapi([search_module._bm25_tokens(row["search_text"]) for row in metadata])
    query = "SVE sve svadd[_f32]_m. svadd[_f32]_m."
    expected = bm25_search(" ".join(dict.fromkeys(tokenize_for_search(query))), metadata, index, k=10)
    actual = hybrid_search(query, None, metadata, object(), index, k=10)
    assert expected
    assert {r["metadata"]["chunk_uuid"]: r["bm25_score"] for r in actual} == {
        r["metadata"]["chunk_uuid"]: r["bm25_score"] for r in expected
    }

SYNONYM_RULES = {
    "awscli": ["aws cli", "awscli"],
    "scikitlearn": ["scikit learn", "sklearn"],
    "visualstudiocode": ["visual studio code", "vs code", "vscode"],
    "vscodetunnels": ["vs code tunnels"],
}


def synonym_resources(metadata, rules=SYNONYM_RULES, *, background=True):
    if background:
        metadata = [*metadata, *[chunk(f"background-{i}", search_text="background") for i in range(8)]]
    table = Synonyms(rules)
    return SearchResources(
        metadata, None, None, build_bm25_index(metadata, table),
        include_disclaimers=False, synonyms=table,
    )


@pytest.mark.parametrize("text,key", [
    ("AWS CLI", "awscli"), ("aws-cli", "awscli"), ("aws_cli", "awscli"),
    ("AWS.CLI.", "awscli"), ("AWS - CLI", "awscli"), ("awscli", "awscli"),
    ("visual-studio_code", "visualstudiocode"), ("vs code tunnels", "vscodetunnels"),
])
def test_synonyms_match_declared_names_and_component_separators(text, key):
    table = Synonyms(SYNONYM_RULES)
    for query in [False, True]:
        expected = {key, "visualstudiocode"} if not query and key == "vscodetunnels" else {key}
        assert name_keys(analyze(text, table, query=query), table) == expected


def test_synonyms_keep_document_words_and_balance_mixed_queries():
    table = Synonyms(SYNONYM_RULES)
    assert analyze("sklearn", table) == ["sklearn", atom("scikitlearn")]
    assert analyze("sklearn", table, query=True) == [atom("scikitlearn")]
    assert analyze("scikit learn", table, query=True) == ["scikit", "learn", atom("scikitlearn")]
    assert analyze("configure heap for scikit-learn", table, query=True) == [
        "configure", "heap", "for", atom("scikitlearn")]


@pytest.mark.parametrize("text", [
    "visualstudiocode", "VisualStudio Code", "aw_scli", "aws/cli", "aws:cli",
    "aws_cli_extra", "awscli()", "awscli[0]", ".awscli",
])
def test_synonyms_do_not_match_unlisted_joins_or_identifier_fragments(text):
    table = Synonyms(SYNONYM_RULES)
    for query in [False, True]:
        assert not name_keys(analyze(text, table, query=query), table)


@pytest.mark.parametrize("text,document_tokens,query_tokens", [
    ("open-source", ["open-source", "open", "source"], ["open-source", "open", "source"]),
    ("torch.nn", ["torch.nn", "torch", "nn"], ["torch.nn"]),
    ("pthread_create", ["pthread_create", "pthread", "create"], ["pthread_create"]),
    ("vld1q_f32", ["vld1q_f32"], ["vld1q_f32"]),
    ("svadd_n_u8", ["svadd_n_u8"], ["svadd_n_u8"]),
    ("_n_u8", ["_n_u8"], ["_n_u8"]),
    ("x86_64", ["x86_64"], ["x86_64"]),
])
def test_literal_analysis_preserves_identifiers_and_exposes_prose(text, document_tokens, query_tokens):
    table = Synonyms({"pytorch": ["pytorch", "torch"]})
    assert analyze(text, table) == document_tokens
    assert analyze(text, table, query=True) == query_tokens


@pytest.mark.parametrize("rules", [
    [], {"awscli": "aws cli"}, {"": ["aws cli"]}, {"awscli": [1]},
    {"maplenet": ["Maple .NET"]}, {"first": ["abc"], "second": ["abc"]},
])
def test_synonym_loading_rejects_invalid_or_ambiguous_tables(tmp_path, rules):
    path = tmp_path / "names.json"
    path.write_text(json.dumps(rules), encoding="utf-8")
    with pytest.raises(ValueError):
        Synonyms.load(path)


@pytest.mark.parametrize("query", ["sklearn", "Scikit-learn", "scikit_learn"])
def test_alias_retrieval_matches_both_spellings_and_respects_filters(query):
    state = synonym_resources([
        chunk(0, title="Scikit-learn", search_text="sklearn", platform="linux"),
        chunk(1, title="Training guide", search_text="Scikit-learn", platform="windows"),
        chunk(2, title="Reference", search_text="Scikit-learn", platform="linux"),
    ], background=False)
    assert {hit["url"] for hit in search(query, state, k=5)} == {
        "https://example.com/0", "https://example.com/1", "https://example.com/2"}
    assert [hit["url"] for hit in search(query, state, filters={"platform": "windows"})] == [
        "https://example.com/1"]


def test_alias_retrieval_does_not_treat_identifier_parts_as_names():
    state = synonym_resources([
        chunk(0, title="PyTorch", search_text="PyTorch documentation"),
        chunk(1, title="API reference", search_text="torch.nn documentation"),
    ], {"pytorch": ["pytorch", "torch"]})
    assert [hit["url"] for hit in search("torch", state)] == ["https://example.com/0"]
    assert [hit["url"] for hit in search("torch.nn", state)] == ["https://example.com/1"]


def test_unlisted_join_cannot_find_a_name_through_literal_expansion():
    state = synonym_resources([chunk(0, title="Visual Studio Code", search_text="Visual-Studio-Code editor")])
    assert search("visualstudiocode", state) == []
    assert [hit["url"] for hit in search("vscode", state)] == ["https://example.com/0"]


def test_symbol_parts_support_prose_but_identifier_queries_remain_literal():
    state = synonym_resources([
        chunk(0, title="Linker symbols", search_text="ARM_LIB_HEAP"),
        chunk(1, title="Concepts", search_text="arm lib heap"),
    ])
    assert "https://example.com/0" in {hit["url"] for hit in search("heap", state)}
    assert [hit["url"] for hit in search("ARM_LIB_HEAP", state)] == ["https://example.com/0"]


def test_name_recognition_does_not_add_a_separate_ranking_bonus():
    query = search_module._analyze_query("AWS CLI", Synonyms(SYNONYM_RULES))
    item = candidate("guide", "AWS CLI")
    score = search_module._rerank_candidates(query, [item])[0]["rerank_score"]
    same_tokens = replace(query, name_keys=frozenset())
    assert score == pytest.approx(search_module._rerank_candidates(same_tokens, [item])[0]["rerank_score"])


def test_query_names_preserve_raw_intent_and_complete_identifier_matching():
    table = Synonyms({"googlekubernetesengine": ["google kubernetes engine", "gke"],
                      "redhatenterpriselinux": ["red hat enterprise linux", "rhel"],
                      "armperformancelibraries": ["arm performance libraries", "armpl"], **SYNONYM_RULES})
    query = search_module._analyze_query("gke autopilot", table)
    assert "gke" in query.raw_query_tokens and atom("googlekubernetesengine") in query.query_tokens
    assert "gke" not in query.query_tokens
    assert not search_module._analyze_query("install aws_cli", table).code_identifiers
    assert search_module._analyze_query("aws_cli()", table).code_identifiers == {"aws_cli"}
    for platform in ["RHEL", "Red Hat Enterprise Linux"]:
        query = search_module._analyze_query(f"install sklearn on {platform}", table)
        assert query.salient_query_tokens == {atom("scikitlearn"), atom("redhatenterpriselinux")}
    for name in ["Arm Performance Libraries", "armpl"]:
        query = search_module._analyze_query(f"Is {name} supported on Linux?", table)
        assert query.support_question and not query.prefers_tuning_guide
    assert search_module._analyze_query("optimize Arm Performance Libraries", table).prefers_tuning_guide
    assert search_module._analyze_query("install sklearn on gke", table).salient_query_tokens == {atom("scikitlearn")}


def test_synonym_resource_loading_is_explicit_and_independent(tmp_path, monkeypatch):
    metadata = [chunk(0, title="AWS CLI", search_text="AWS CLI documentation")]
    metadata += [chunk(i, search_text="background") for i in range(1, 9)]
    monkeypatch.setattr(resources, "load_metadata", lambda path: metadata)
    monkeypatch.setattr(resources, "load_usearch_index", lambda *args: None)
    monkeypatch.setattr(resources, "load_embedding_model", lambda *args, **kwargs: QueryModel())
    path = tmp_path / "names.json"
    path.write_text(json.dumps(SYNONYM_RULES), encoding="utf-8")
    loaded = resources.load_search_resources("meta", "index", synonyms_path=str(path), include_disclaimers=False)
    before = search("awscli", loaded)
    assert [hit["url"] for hit in before] == ["https://example.com/0"]
    plain = resources.load_search_resources("meta", "index")
    assert search("awscli", plain) == []
    assert search("awscli", loaded) == before
    with pytest.raises(FileNotFoundError):
        resources.load_search_resources("meta", "index", synonyms_path=str(tmp_path / "missing.json"))
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError):
        resources.load_search_resources("meta", "index", synonyms_path=str(path))


def test_committed_synonym_map_recognizes_every_declared_form():
    path = Path(__file__).resolve().parents[1] / "mcp-local" / "name-synonyms.json"
    rules = json.loads(path.read_text(encoding="utf-8"))
    table = Synonyms.load(path)
    assert rules
    for key, forms in rules.items():
        for form in forms:
            assert name_keys(analyze(form, table, query=True), table) == {key}, form
            assert key in name_keys(analyze(form, table), table), form
    for ambiguous in ["acl", "ecs", "oci", "mcp", "spe", "gcs", "rmm"]:
        assert not name_keys(analyze(ambiguous, table, query=True), table), ambiguous
