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

from typing import Any, Dict, List, Optional
import json
import os
import re

import numpy as np
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer
from usearch.index import Index

from .config import DISTANCE_THRESHOLD, K_RESULTS


SEARCH_TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9_\-+.]*", re.IGNORECASE)
RRF_K = 60
SEARCH_STOPWORDS = {
    "a", "an", "and", "are", "be", "better", "can", "configured", "configuration", "for",
    "called", "how", "i", "improve", "in", "is", "it", "of", "on", "or", "out", "performance", "processor",
    "processors", "recommended", "settings", "should", "step", "steps", "system", "systems",
    "the", "to", "use", "what", "which", "with", "ampere", "arm", "benchmark", "benchmarking",
    "benchmarked", "benchmarks", "brief", "cloud", "config", "configure", "guide", "options",
    "performance", "processor", "processors", "reference", "setup", "tutorial", "tune",
    "tuned", "tuning",
}
TUNING_INTENT_TOKENS = {
    "benchmark", "benchmarking", "benchmarked", "benchmarks", "config", "configure",
    "configured", "configuration", "latency", "oltp", "optimize", "optimized", "performance",
    "throughput", "tune", "tuned", "tuning",
}
REFERENCE_ARCHITECTURE_INTENT_TOKENS = {
    "architecture", "deploy", "deployment", "reference", "steps",
}
TUTORIAL_INTENT_TOKENS = {
    "how", "install", "migration", "migrate", "port", "porting", "setup", "tutorial",
}


def tokenize_for_search(text: str) -> List[str]:
    return [token.lower() for token in SEARCH_TOKEN_PATTERN.findall(text or "")]


def salient_tokens(text: str) -> List[str]:
    return [token for token in tokenize_for_search(text) if token not in SEARCH_STOPWORDS]


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


def build_bm25_index(metadata: List[Dict]) -> Optional[BM25Okapi]:
    corpus = [tokenize_for_search(item.get("search_text", "")) for item in metadata]
    if not any(corpus):
        return None
    return BM25Okapi(corpus)


def embedding_search(
    query: str,
    usearch_index: Optional[Index],
    metadata: List[Dict],
    embedding_model: SentenceTransformer,
    k: int = K_RESULTS,
) -> List[Dict[str, Any]]:
    """Search the USearch index with a text query."""
    if usearch_index is None:
        return []
    query_embedding = embedding_model.encode([query])[0]
    matches = usearch_index.search(query_embedding, k)
    results: List[Dict[str, Any]] = []
    if matches is None:
        return results

    try:
        labels = getattr(matches, "keys", None)
        distances = getattr(matches, "distances", None)
        if labels is None or distances is None:
            if isinstance(matches, tuple) and len(matches) == 2:
                labels, distances = matches
            elif isinstance(matches, dict):
                labels = matches.get("labels", matches.get("indices"))
                distances = matches.get("distances")
        if labels is None or distances is None:
            return results

        labels = np.atleast_1d(labels)
        distances = np.atleast_1d(distances)
        for rank, (idx, dist) in enumerate(zip(labels, distances), start=1):
            if idx == -1:
                continue
            distance = float(dist)
            if distance < DISTANCE_THRESHOLD:
                results.append(
                    {
                        "rank": rank,
                        "distance": distance,
                        "metadata": metadata[int(idx)],
                    }
                )
    except Exception as exc:
        print(f"Error processing dense matches: {exc}")
    return results


def bm25_search(
    query: str,
    metadata: List[Dict],
    bm25_index: Optional[BM25Okapi],
    k: int = K_RESULTS,
) -> List[Dict[str, Any]]:
    if bm25_index is None:
        return []
    tokens = tokenize_for_search(query)
    if not tokens:
        return []
    scores = bm25_index.get_scores(tokens)
    ranking = np.argsort(scores)[::-1]
    results: List[Dict[str, Any]] = []
    for rank, idx in enumerate(ranking[:k], start=1):
        score = float(scores[idx])
        if score <= 0:
            continue
        results.append(
            {
                "rank": rank,
                "bm25_score": score,
                "metadata": metadata[int(idx)],
            }
        )
    return results


def rerank_candidates(query: str, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    query_tokens = set(tokenize_for_search(query))
    if not query_tokens:
        return candidates
    salient_query_tokens = set(salient_tokens(query))
    prefers_tuning_guide = bool(query_tokens & TUNING_INTENT_TOKENS)
    prefers_reference_architecture = bool(query_tokens & REFERENCE_ARCHITECTURE_INTENT_TOKENS)
    prefers_tutorial = bool(query_tokens & TUTORIAL_INTENT_TOKENS)

    reranked: List[Dict[str, Any]] = []
    for candidate in candidates:
        metadata = candidate["metadata"]
        full_text_tokens = set(tokenize_for_search(metadata.get("search_text", "")))
        title_tokens = set(tokenize_for_search(metadata.get("title", "")))
        heading_tokens = set(tokenize_for_search(" ".join(metadata.get("heading_path", []))))
        url_tokens = set(tokenize_for_search(metadata.get("url", "")))
        doc_type = (metadata.get("doc_type", "") or "").strip().lower()
        overlap = len(query_tokens & full_text_tokens) / len(query_tokens)
        title_overlap = len(query_tokens & title_tokens) / len(query_tokens)
        heading_overlap = len(query_tokens & heading_tokens) / len(query_tokens)
        entity_overlap = 0.0
        if salient_query_tokens:
            entity_space = title_tokens | heading_tokens | url_tokens
            entity_overlap = len(salient_query_tokens & entity_space) / len(salient_query_tokens)
        exact_entity_bonus = 0.0
        if salient_query_tokens and (salient_query_tokens & (title_tokens | url_tokens)):
            exact_entity_bonus = 0.18
        dense_bonus = 0.0
        if candidate.get("distance") is not None:
            dense_bonus = max(0.0, (DISTANCE_THRESHOLD - candidate["distance"]) / DISTANCE_THRESHOLD)
        sparse_bonus = min(1.0, candidate.get("bm25_score", 0.0) / 10.0)
        doc_type_bonus = 0.0
        if prefers_tuning_guide:
            if doc_type == "tuning guide":
                doc_type_bonus += 0.30
            elif "brief" in doc_type:
                doc_type_bonus -= 0.12
        if prefers_reference_architecture:
            if doc_type == "reference architecture":
                doc_type_bonus += 0.25
            elif "brief" in doc_type:
                doc_type_bonus -= 0.05
        if prefers_tutorial:
            if doc_type in {"tutorial", "install guide", "learning path", "learning paths"}:
                doc_type_bonus += 0.10
        rerank_score = (
            candidate.get("rrf_score", 0.0)
            + (0.35 * overlap)
            + (0.20 * title_overlap)
            + (0.15 * heading_overlap)
            + (0.20 * entity_overlap)
            + (0.15 * dense_bonus)
            + (0.15 * sparse_bonus)
            + exact_entity_bonus
            + doc_type_bonus
        )
        reranked.append({**candidate, "rerank_score": rerank_score})
    return sorted(reranked, key=lambda item: item["rerank_score"], reverse=True)


def hybrid_search(
    query: str,
    usearch_index: Optional[Index],
    metadata: List[Dict],
    embedding_model: SentenceTransformer,
    bm25_index: Optional[BM25Okapi],
    k: int = K_RESULTS,
) -> List[Dict[str, Any]]:
    candidate_depth = max(k * 20, 100)
    dense_results = embedding_search(query, usearch_index, metadata, embedding_model, candidate_depth)
    sparse_results = bm25_search(query, metadata, bm25_index, candidate_depth)

    candidates: Dict[str, Dict[str, Any]] = {}
    for result in dense_results:
        chunk_uuid = result["metadata"].get("chunk_uuid") or result["metadata"].get("uuid")
        candidates[chunk_uuid] = {**result, "rrf_score": 1 / (RRF_K + result["rank"])}

    for result in sparse_results:
        chunk_uuid = result["metadata"].get("chunk_uuid") or result["metadata"].get("uuid")
        existing = candidates.get(chunk_uuid, {"metadata": result["metadata"], "rrf_score": 0.0})
        existing["rank"] = min(existing.get("rank", result["rank"]), result["rank"])
        existing["bm25_score"] = result["bm25_score"]
        existing["rrf_score"] += 1 / (RRF_K + result["rank"])
        candidates[chunk_uuid] = existing

    combined = rerank_candidates(query, list(candidates.values()))
    return combined[:k]


def deduplicate_urls(results: List[Dict[str, Any]], max_chunks_per_url: int = 1) -> List[Dict[str, Any]]:
    """Keep the highest-ranked chunk for each URL by default."""
    seen_counts: Dict[str, int] = {}
    deduplicated_results = []
    for item in results:
        url = item["metadata"].get("url")
        if not url:
            continue
        seen_counts[url] = seen_counts.get(url, 0) + 1
        if seen_counts[url] <= max_chunks_per_url:
            deduplicated_results.append(item)
    return deduplicated_results
