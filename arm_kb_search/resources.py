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

import os
from dataclasses import dataclass
from typing import Any

from sentence_transformers import SentenceTransformer
from usearch.index import Index

from .config import K_RESULTS
from .loaders import load_metadata, load_usearch_index
from .response import add_disclaimer_to_arm_results, add_utm_source_to_results
from .search import (
    LEXICAL_PREPASS_DEPTH,
    ParentAwareBM25,
    build_bm25_index,
    build_parent_index,
    deduplicate_urls,
    deduplication_candidate_count,
    hybrid_search,
    normalize_query_for_search,
)


@dataclass
class SearchResources:
    metadata: list[dict[str, Any]]
    embedding_model: SentenceTransformer
    usearch_index: Index | None
    bm25_index: ParentAwareBM25 | None
    default_k: int = K_RESULTS
    include_disclaimers: bool = True
    utm_source: str | None = None
    parent_index: dict[str, dict[str, Any]] | None = None

    def __post_init__(self) -> None:
        if self.parent_index is None:
            self.parent_index = build_parent_index(self.metadata)


def sentence_transformer_cache_folder() -> str | None:
    return os.getenv("SENTENCE_TRANSFORMERS_HOME") or None


def embedding_dimension(embedding_model: SentenceTransformer) -> int:
    if hasattr(embedding_model, "get_embedding_dimension"):
        return int(embedding_model.get_embedding_dimension())
    return int(embedding_model.get_sentence_embedding_dimension())


def load_embedding_model(
    model_name_or_path: str,
    cache_folder: str | None = None,
    allow_download: bool = True,
) -> SentenceTransformer:
    resolved_cache_folder = cache_folder if cache_folder is not None else sentence_transformer_cache_folder()
    try:
        return SentenceTransformer(
            model_name_or_path,
            cache_folder=resolved_cache_folder,
            local_files_only=True,
            trust_remote_code=False,
        )
    except Exception as exc:
        if not allow_download:
            raise
        print(
            f"Local cache miss for embedding model '{model_name_or_path}', "
            f"retrying with network access: {exc}"
        )
        return SentenceTransformer(
            model_name_or_path,
            cache_folder=resolved_cache_folder,
            local_files_only=False,
            trust_remote_code=False,
        )


def load_search_resources(
    metadata_path: str,
    usearch_index_path: str,
    model_name: str = "all-MiniLM-L6-v2",
    cache_folder: str | None = None,
    default_k: int = K_RESULTS,
    include_disclaimers: bool = True,
    utm_source: str | None = None,
    model_path: str | None = None,
) -> SearchResources:
    """Load search resources, treating an explicit model path as local-only."""
    metadata = load_metadata(metadata_path)
    embedding_model = load_embedding_model(
        model_path if model_path is not None else model_name,
        cache_folder=cache_folder,
        allow_download=model_path is None,
    )
    usearch_index = load_usearch_index(
        usearch_index_path,
        embedding_dimension(embedding_model),
    )
    bm25_index = build_bm25_index(metadata)
    return SearchResources(
        metadata=metadata,
        embedding_model=embedding_model,
        usearch_index=usearch_index,
        bm25_index=bm25_index,
        default_k=default_k,
        include_disclaimers=include_disclaimers,
        utm_source=utm_source,
        parent_index=build_parent_index(metadata),
    )


def search(
    query: str,
    resources: SearchResources,
    k: int | None = None,
    include_debug: bool = False,
) -> list[dict[str, Any]]:
    """Return the top ``k`` pages for ``query``; ``include_debug`` attaches the score breakdown."""
    resolved_k = k or resources.default_k
    normalized_query = normalize_query_for_search(query)
    if not normalized_query:
        return []
    candidate_depth = max(resolved_k * 20, 100)

    def ranked_candidates(pool_size: int) -> list[dict[str, Any]]:
        return hybrid_search(
            normalized_query,
            resources.usearch_index,
            resources.metadata,
            resources.embedding_model,
            resources.bm25_index,
            k=pool_size,
            candidate_depth=max(candidate_depth, pool_size),
            parent_index=resources.parent_index,
        )

    pool_size = deduplication_candidate_count(resolved_k)
    search_results = ranked_candidates(pool_size)
    deduped = deduplicate_urls(search_results)
    if len(deduped) < resolved_k and len(search_results) >= pool_size:
        # Page-level deduplication collapsed most of the pool; widen it once.
        search_results = ranked_candidates(min(LEXICAL_PREPASS_DEPTH, pool_size * 4))
        deduped = deduplicate_urls(search_results)
    deduped = deduped[:resolved_k]
    formatted = []
    for rank, item in enumerate(deduped, start=1):
        result = {
            "url": item["metadata"].get("url"),
            "snippet": item["metadata"].get("original_text", item["metadata"].get("content", "")),
            "title": item["metadata"].get("title", ""),
            "heading": item["metadata"].get("heading", ""),
            "doc_type": item["metadata"].get("doc_type", ""),
            "product": item["metadata"].get("product", ""),
            "distance": item.get("distance"),
            "score": item.get("rerank_score", item.get("rrf_score")),
        }
        if include_debug:
            result["debug"] = {
                **item.get("score_debug", {}),
                "query_normalization": {
                    "original": query,
                    "normalized": normalized_query,
                },
                "result_rank": rank,
                "returned_results": len(deduped),
                "requested_results": resolved_k,
            }
        formatted.append(result)
    formatted = add_utm_source_to_results(formatted, resources.utm_source)
    if resources.include_disclaimers:
        return add_disclaimer_to_arm_results(formatted)
    return formatted
