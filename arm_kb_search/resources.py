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
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer
from usearch.index import Index

from .config import K_RESULTS
from .filters import MetadataFilterIndex, SearchFilters
from .loaders import load_metadata, load_usearch_index
from .response import add_disclaimer_to_arm_results, add_utm_source_to_results
from .search import (
    LEXICAL_PREPASS_DEPTH,
    build_bm25_index,
    deduplication_candidate_count,
    hybrid_search,
    tokenize_for_search,
)


@dataclass
class SearchResources:
    metadata: list[dict[str, Any]]
    embedding_model: SentenceTransformer
    usearch_index: Index | None
    bm25_index: BM25Okapi | None
    default_k: int = K_RESULTS
    include_disclaimers: bool = True
    utm_source: str | None = None
    _filter_index: MetadataFilterIndex = field(init=False, repr=False, compare=False)
    _parent_texts: dict[tuple[str, str], str] = field(init=False, repr=False, compare=False)

    def __post_init__(self) -> None:
        self._filter_index = MetadataFilterIndex(self.metadata)
        parents: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for row in self.metadata:
            if row.get("parent_uuid") and row.get("parent_chunk_uuid"):
                key = (row["parent_uuid"], row["parent_chunk_uuid"])
                parents.setdefault(key, []).append(row)
        self._parent_texts = {}
        for key, pieces in parents.items():
            pieces.sort(key=lambda piece: piece["source_start"])
            expected_starts = [0] + [piece["source_end"] for piece in pieces[:-1]]
            complete = all(
                piece["source_part"] == number
                and piece["source_parts"] == len(pieces)
                and piece["source_start"] == expected_starts[number - 1]
                and piece["source_end"] == piece["source_start"] + len(piece["original_text"])
                for number, piece in enumerate(pieces, 1)
            )
            if complete:
                self._parent_texts[key] = "".join(piece["original_text"] for piece in pieces)

    def snippet_for(self, metadata: dict[str, Any]) -> str:
        """Expand a ranked piece to its complete original chunk when available."""
        return self._parent_texts.get(
            (metadata.get("parent_uuid"), metadata.get("parent_chunk_uuid")),
            metadata.get("original_text", metadata.get("content", "")),
        )


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
        model = SentenceTransformer(
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
        model = SentenceTransformer(
            model_name_or_path,
            cache_folder=resolved_cache_folder,
            local_files_only=False,
            trust_remote_code=False,
        )

    model.max_seq_length = 512
    return model


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
    )


def search(
    query: str,
    resources: SearchResources,
    k: int | None = None,
    *,
    filters: SearchFilters | Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Search a resource snapshot, optionally restricting eligible metadata values."""
    eligible_ids = resources._filter_index.eligible_ids(SearchFilters.parse(filters))
    if eligible_ids == ():
        return []
    resolved_k = k or resources.default_k
    if not tokenize_for_search(query):
        return []

    candidate_depth = max(resolved_k * 20, 100)

    def ranked_candidates(pool_size: int) -> list[dict[str, Any]]:
        return hybrid_search(
            query,
            resources.usearch_index,
            resources.metadata,
            resources.embedding_model,
            resources.bm25_index,
            k=pool_size,
            candidate_depth=max(candidate_depth, pool_size),
            eligible_ids=eligible_ids,
        )

    pool_size = deduplication_candidate_count(resolved_k)
    search_results = ranked_candidates(pool_size)
    expanded_pool_size = min(LEXICAL_PREPASS_DEPTH, pool_size * 4)
    can_expand = (
        (len(eligible_ids) if eligible_ids is not None else len(resources.metadata))
        > max(candidate_depth, pool_size)
    )
    if len(search_results) < resolved_k and can_expand and expanded_pool_size > pool_size:
        search_results = ranked_candidates(expanded_pool_size)

    formatted = [
        {
            "url": item["metadata"].get("url") or item["metadata"].get("resolved_url"),
            "snippet": resources.snippet_for(item["metadata"]),
            "title": item["metadata"].get("title", ""),
            "heading": item["metadata"].get("heading", ""),
            "doc_type": item["metadata"].get("doc_type", ""),
            "product": item["metadata"].get("product", ""),
            "platform": item["metadata"].get("platform", ""),
            "edition": item["metadata"].get("edition", ""),
            "distance": item.get("distance"),
            "score": item.get("rerank_score", item.get("rrf_score")),
        }
        for item in search_results[:resolved_k]
    ]
    formatted = add_utm_source_to_results(formatted, resources.utm_source)
    if resources.include_disclaimers:
        return add_disclaimer_to_arm_results(formatted)
    return formatted
