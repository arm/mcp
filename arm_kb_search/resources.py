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

from dataclasses import dataclass
import os
from typing import Any

from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer
from usearch.index import Index

from .config import K_RESULTS
from .loaders import load_metadata, load_usearch_index
from .response import add_disclaimer_to_arm_results, add_utm_source_to_results
from .search import build_bm25_index, deduplicate_urls, deduplication_candidate_count, hybrid_search


@dataclass
class SearchResources:
    metadata: list[dict[str, Any]]
    embedding_model: SentenceTransformer
    usearch_index: Index | None
    bm25_index: BM25Okapi | None
    default_k: int = K_RESULTS
    include_disclaimers: bool = True
    utm_source: str | None = None


def sentence_transformer_cache_folder() -> str | None:
    return os.getenv("SENTENCE_TRANSFORMERS_HOME") or None


def embedding_dimension(embedding_model: SentenceTransformer) -> int:
    if hasattr(embedding_model, "get_embedding_dimension"):
        return int(embedding_model.get_embedding_dimension())
    return int(embedding_model.get_sentence_embedding_dimension())


def load_embedding_model(
    model_name: str,
    cache_folder: str | None = None,
    local_files_only_first: bool = True,
) -> SentenceTransformer:
    resolved_cache_folder = cache_folder if cache_folder is not None else sentence_transformer_cache_folder()
    if not local_files_only_first:
        return SentenceTransformer(
            model_name,
            cache_folder=resolved_cache_folder,
            local_files_only=False,
        )

    try:
        return SentenceTransformer(
            model_name,
            cache_folder=resolved_cache_folder,
            local_files_only=True,
        )
    except Exception as exc:
        print(f"Local cache miss for embedding model '{model_name}', retrying with network access: {exc}")
        return SentenceTransformer(
            model_name,
            cache_folder=resolved_cache_folder,
            local_files_only=False,
        )


def load_search_resources(
    metadata_path: str,
    usearch_index_path: str,
    model_name: str = "all-MiniLM-L6-v2",
    cache_folder: str | None = None,
    local_files_only_first: bool = True,
    default_k: int = K_RESULTS,
    include_disclaimers: bool = True,
    utm_source: str | None = None,
) -> SearchResources:
    metadata = load_metadata(metadata_path)
    embedding_model = load_embedding_model(
        model_name,
        cache_folder=cache_folder,
        local_files_only_first=local_files_only_first,
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
    )


def search(
    query: str,
    resources: SearchResources,
    k: int | None = None,
) -> list[dict[str, Any]]:
    resolved_k = k or resources.default_k
    search_results = hybrid_search(
        query,
        resources.usearch_index,
        resources.metadata,
        resources.embedding_model,
        resources.bm25_index,
        k=deduplication_candidate_count(resolved_k),
    )
    deduped = deduplicate_urls(search_results)[:resolved_k]
    formatted = [
        {
            "url": item["metadata"].get("url"),
            "snippet": item["metadata"].get("original_text", item["metadata"].get("content", "")),
            "title": item["metadata"].get("title", ""),
            "heading": item["metadata"].get("heading", ""),
            "doc_type": item["metadata"].get("doc_type", ""),
            "product": item["metadata"].get("product", ""),
            "distance": item.get("distance"),
            "score": item.get("rerank_score", item.get("rrf_score")),
        }
        for item in deduped
    ]
    formatted = add_utm_source_to_results(formatted, resources.utm_source)
    if resources.include_disclaimers:
        return add_disclaimer_to_arm_results(formatted)
    return formatted
