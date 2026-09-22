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

"""Focused regressions for retrieval normalization and ranking behavior."""

import importlib
import sys
from pathlib import Path

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(_REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPOSITORY_ROOT))

resources_module = importlib.import_module("arm_kb_search.resources")
search = importlib.import_module("arm_kb_search.search")


def candidate(chunk_uuid, title, url, **metadata):
    return {
        "rrf_score": 0.0,
        "metadata": {
            "chunk_uuid": chunk_uuid,
            "title": title,
            "url": url,
            "resolved_url": url,
            "search_text": metadata.pop("search_text", title),
            **metadata,
        },
    }


def test_identifier_expansion_rejects_unsafe_generic_pieces():
    assert search._identifier_variants("ISVs") == ["isvs"]
    assert search._identifier_variants("MySQL") == ["mysql"]
    assert search._identifier_variants("app_arm64ec") == ["app_arm64ec"]

    assert search._identifier_variants("GoogleChrome") == [
        "googlechrome",
        "google",
        "chrome",
    ]
    assert search._identifier_variants("HTTPServer") == [
        "httpserver",
        "http",
        "server",
    ]
    assert search._identifier_variants("aws-cli") == [
        "aws-cli",
        "aws",
        "cli",
        "awscli",
    ]
    assert search._identifier_variants("a-b") == ["a-b"]
    assert search.normalize_query_for_search("Arm-based server") == "arm based server"


def test_camel_case_query_expansion_uses_bm25_vocabulary():
    compact_products = (
        "JavaScript",
        "PostgreSQL",
        "TensorFlow",
        "WordPress",
        "macOS",
        "OpenSSL",
    )
    metadata = [
        {"title": product, "search_text": product}
        for product in compact_products
    ]
    metadata.extend(
        [
            {"title": "Google Chrome", "search_text": "Google Chrome"},
            {"title": "HTTP Server", "search_text": "HTTP Server"},
        ]
    )
    bm25_index = search.build_bm25_index(metadata)
    assert bm25_index is not None
    vocabulary = set(bm25_index.idf)

    for product in compact_products:
        assert search.normalize_query_for_search(product, vocabulary) == product.lower()

    assert search.normalize_query_for_search(
        "GoogleChrome", vocabulary
    ) == "googlechrome google chrome"
    assert search.normalize_query_for_search(
        "HTTPServer", vocabulary
    ) == "httpserver http server"


def test_url_tokenization_splits_path_separators_but_not_hostname():
    tokens = set(
        search.tokenize_url_content_for_search(
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

    assert search._lexical_exactness_score(
        "docs.example.com linux", matching_host
    ) == search._lexical_exactness_score(
        "docs.example.com linux", different_host
    )


def test_dense_search_receives_original_query(monkeypatch):
    captured_queries = []

    def fake_embedding_search(query, *_args, **_kwargs):
        captured_queries.append(query)
        return []

    monkeypatch.setattr(search, "embedding_search", fake_embedding_search)

    search.hybrid_search(
        "Find GoogleChrome!",
        usearch_index=None,
        metadata=[],
        embedding_model=object(),
        bm25_index=None,
        k=1,
    )

    assert captured_queries == ["Find GoogleChrome!"]


def test_bm25_matches_spaced_query_to_compound_identifier():
    metadata = [
        {
            "chunk_uuid": "chrome",
            "title": "GoogleChrome",
            "url": "https://docs.example.com/install/GoogleChrome",
            "resolved_url": "https://docs.example.com/install/GoogleChrome",
            "search_text": "Install GoogleChrome",
        },
        {
            "chunk_uuid": "docker",
            "title": "Docker",
            "url": "https://example.com/docker",
            "resolved_url": "https://example.com/docker",
            "search_text": "Install Docker",
        },
        {
            "chunk_uuid": "llvm",
            "title": "LLVM",
            "url": "https://example.com/llvm",
            "resolved_url": "https://example.com/llvm",
            "search_text": "Install LLVM",
        },
    ]

    chrome_tokens = set(search._sparse_document_tokens(metadata[0]))
    assert {"google", "chrome"} <= chrome_tokens
    assert not {"docs", "example", "com"} & chrome_tokens

    index = search.build_bm25_index(metadata)
    results = search.bm25_search("google chrome", metadata, index, k=3)

    assert results
    assert results[0]["metadata"]["chunk_uuid"] == "chrome"


def test_install_bonus_requires_the_queried_product():
    candidates = [
        candidate(
            "docker",
            "Docker",
            "https://learn.arm.com/install-guides/docker/",
            doc_type="Install Guides",
            keywords="Docker; install; build; download",
        ),
        candidate(
            "generic",
            "Install Guide",
            "https://learn.arm.com/install-guides/generic/",
            doc_type="Install Guides",
            keywords="install; build; download",
        ),
    ]

    reranked = search.rerank_candidates("install docker", candidates)

    assert reranked[0]["metadata"]["chunk_uuid"] == "docker"


def test_learning_path_root_bonus_requires_learning_path_intent():
    root = candidate(
        "root",
        "Docker",
        "https://learn.arm.com/learning-paths/servers-and-cloud-computing/docker/",
        doc_type="Learning Paths",
    )
    other = candidate(
        "other",
        "Docker",
        "https://example.com/docker",
        doc_type="Tutorial",
    )

    ordinary = search.rerank_candidates("docker", [root, other])
    explicit = search.rerank_candidates("docker learning path", [root, other])
    ordinary_scores = {
        item["metadata"]["chunk_uuid"]: item["rerank_score"] for item in ordinary
    }
    explicit_scores = {
        item["metadata"]["chunk_uuid"]: item["rerank_score"] for item in explicit
    }

    assert ordinary_scores["root"] - ordinary_scores["other"] < 0.5
    assert explicit_scores["root"] - explicit_scores["other"] > 0.5


def test_page_deduplication_normalizes_tracking_and_fragments():
    results = [
        candidate(
            "first",
            "First",
            "https://Example.com/page/?b=2&utm_source=arm-mcp&a=1#first",
        ),
        candidate(
            "second",
            "Second",
            "https://example.com/page?a=1&b=2#second",
        ),
        candidate(
            "semantic",
            "Semantic",
            "https://example.com/page?a=1&b=2#mode=full",
        ),
    ]

    deduped = search.deduplicate_urls(results)

    assert [item["metadata"]["chunk_uuid"] for item in deduped] == [
        "first",
        "semantic",
    ]


def test_search_widens_pool_when_page_deduplication_exhausts_it(monkeypatch):
    calls = []

    def fake_hybrid_search(*_args, k, **_kwargs):
        calls.append(k)
        if len(calls) == 1:
            return [
                candidate(
                    f"duplicate-{index}",
                    "Duplicate",
                    f"https://example.com/page/#section-{index}",
                )
                for index in range(k)
            ]
        return [
            candidate(
                f"unique-{index}",
                f"Unique {index}",
                f"https://example.com/page-{index}/",
            )
            for index in range(3)
        ]

    monkeypatch.setattr(resources_module, "hybrid_search", fake_hybrid_search)
    resources = resources_module.SearchResources(
        metadata=[],
        embedding_model=object(),
        usearch_index=None,
        bm25_index=None,
        include_disclaimers=False,
    )

    results = resources_module.search("target", resources, k=3)

    assert calls == [50, 200]
    assert len(results) == 3
