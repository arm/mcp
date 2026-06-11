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

from typing import Any, Dict, Iterable, List, Optional
import re

import numpy as np
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer
from usearch.index import Index

from .config import DISTANCE_THRESHOLD, K_RESULTS


SEARCH_TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9_\-+.]*", re.IGNORECASE)
RRF_K = 60
LEXICAL_PREPASS_DEPTH = 400
PINNED_LEXICAL_CANDIDATES = 20
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
SUPPORT_INTENT_TOKENS = {
    "available", "availability", "capable", "capabilities", "capability", "compatible",
    "compatibility", "device", "devices", "hardware", "processor", "processors", "server",
    "servers", "support", "supported", "supporting", "supports",
}
VERSIONED_CAPABILITY_PREFIXES = {
    "sme",
    "sve",
}
NEGATIVE_SUPPORT_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bdoes\s+not\s+support\b",
        r"\bdo\s+not\s+support\b",
        r"\bdoesn't\s+support\b",
        r"\bdon't\s+support\b",
        r"\bnot\s+supported\b",
        r"\bno\s+support\b",
        r"\bwithout\s+support\b",
        r"\bunsupported\b",
    )
)


def tokenize_for_search(text: str) -> List[str]:
    return [token.lower() for token in SEARCH_TOKEN_PATTERN.findall(text or "")]


def salient_tokens(text: str) -> List[str]:
    return [token for token in tokenize_for_search(text) if token not in SEARCH_STOPWORDS]


def _metadata_text(metadata: Dict[str, Any], fields: Iterable[str]) -> str:
    values: List[str] = []
    for field in fields:
        value = metadata.get(field)
        if isinstance(value, list):
            values.append(" ".join(str(item) for item in value))
        elif value:
            values.append(str(value))
    return " ".join(values)


def _token_match_count(query_tokens: set[str], document_tokens: set[str]) -> int:
    matches = 0
    for token in query_tokens:
        if token in document_tokens:
            matches += 1
            continue
        if token in VERSIONED_CAPABILITY_PREFIXES and any(
            doc_token.startswith(token) and doc_token[len(token):].isdigit()
            for doc_token in document_tokens
        ):
            matches += 1
    return matches


def _capability_tokens(tokens: set[str]) -> set[str]:
    capability_tokens = set()
    for token in tokens:
        if token in VERSIONED_CAPABILITY_PREFIXES:
            capability_tokens.add(token)
            continue
        for prefix in VERSIONED_CAPABILITY_PREFIXES:
            if token.startswith(prefix) and token[len(prefix):].isdigit():
                capability_tokens.add(token)
    return capability_tokens


def _has_negative_support_evidence(text: str) -> bool:
    return any(pattern.search(text) for pattern in NEGATIVE_SUPPORT_PATTERNS)


def _support_evidence_score(query_tokens: set[str], text_tokens: set[str], text: str) -> float:
    if not (query_tokens & SUPPORT_INTENT_TOKENS):
        return 0.0

    capability_query_tokens = _capability_tokens(query_tokens)
    if not capability_query_tokens:
        return 0.0

    capability_matches = _token_match_count(capability_query_tokens, text_tokens)
    if capability_matches == 0:
        return 0.0

    support_terms = text_tokens & SUPPORT_INTENT_TOKENS
    if not support_terms:
        return 0.0

    score = 0.12 * capability_matches
    if {"device", "devices"} & query_tokens and {"device", "devices"} & text_tokens:
        score += 0.20
    if {"server", "servers"} & query_tokens and {"server", "servers"} & text_tokens:
        score += 0.10
    if {"support", "supported", "supports", "capable"} & text_tokens:
        score += 0.15
    if _has_negative_support_evidence(text):
        score += 0.25
    return score


def _lexical_prepass_score(query: str, metadata: Dict[str, Any], bm25_score: float) -> float:
    query_tokens = set(tokenize_for_search(query))
    salient_query_tokens = set(salient_tokens(query))
    if not query_tokens:
        return 0.0

    weighted_overlap = 0.0
    field_weights = (
        (("title",), 0.45),
        (("heading", "heading_path"), 0.50),
        (("url", "resolved_url"), 0.35),
        (("keywords", "product", "doc_type"), 0.25),
        (("search_text",), 0.20),
    )
    for fields, weight in field_weights:
        field_text = _metadata_text(metadata, fields)
        field_tokens = set(tokenize_for_search(field_text))
        if not field_tokens:
            continue
        denominator = len(salient_query_tokens) or len(query_tokens)
        overlap = _token_match_count(salient_query_tokens or query_tokens, field_tokens) / denominator
        weighted_overlap += weight * overlap

    all_text = _metadata_text(
        metadata,
        ("title", "heading", "heading_path", "url", "resolved_url", "keywords", "search_text"),
    )
    all_text_lower = all_text.lower()
    all_tokens = set(tokenize_for_search(all_text))

    phrase_bonus = 0.0
    salient_sequence = salient_tokens(query)
    for index in range(len(salient_sequence) - 1):
        phrase = " ".join(salient_sequence[index:index + 2])
        if phrase and phrase in all_text_lower:
            phrase_bonus += 0.08
    for index in range(len(salient_sequence) - 2):
        phrase = " ".join(salient_sequence[index:index + 3])
        if phrase and phrase in all_text_lower:
            phrase_bonus += 0.12

    support_bonus = _support_evidence_score(query_tokens, all_tokens, all_text)
    sparse_score = min(1.0, bm25_score / 25.0)
    return sparse_score + weighted_overlap + phrase_bonus + support_bonus


def lexical_prepass_search(
    query: str,
    metadata: List[Dict],
    bm25_index: Optional[BM25Okapi],
    k: int = PINNED_LEXICAL_CANDIDATES,
    candidate_depth: int = LEXICAL_PREPASS_DEPTH,
) -> List[Dict[str, Any]]:
    """Return high-exactness lexical candidates before dense retrieval is merged."""
    prepass_depth = max(k, candidate_depth)
    candidates = bm25_search(query, metadata, bm25_index, prepass_depth)
    if not candidates:
        candidates = [
            {
                "rank": rank,
                "bm25_score": 0.0,
                "metadata": item,
            }
            for rank, item in enumerate(metadata, start=1)
        ]
    scored_candidates: List[Dict[str, Any]] = []
    for candidate in candidates:
        lexical_score = _lexical_prepass_score(
            query,
            candidate["metadata"],
            candidate.get("bm25_score", 0.0),
        )
        if lexical_score <= 0:
            continue
        scored_candidates.append({**candidate, "lexical_prepass_score": lexical_score})

    scored_candidates.sort(key=lambda item: item["lexical_prepass_score"], reverse=True)
    pinned = []
    for rank, candidate in enumerate(scored_candidates[:k], start=1):
        pinned.append({**candidate, "lexical_prepass_rank": rank, "pinned_lexical": True})
    return pinned


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
        resolved_url_tokens = set(tokenize_for_search(metadata.get("resolved_url", "")))
        doc_type = (metadata.get("doc_type", "") or "").strip().lower()
        support_evidence_bonus = _support_evidence_score(
            query_tokens,
            full_text_tokens | title_tokens | heading_tokens | url_tokens | resolved_url_tokens,
            _metadata_text(metadata, ("search_text", "title", "heading", "heading_path", "url", "resolved_url")),
        )
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
        lexical_prepass_bonus = min(1.0, candidate.get("lexical_prepass_score", 0.0) / 2.0)
        if candidate.get("pinned_lexical"):
            lexical_prepass_bonus += 1 / (RRF_K + candidate.get("lexical_prepass_rank", RRF_K))
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
            + (0.35 * lexical_prepass_bonus)
            + support_evidence_bonus
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
    lexical_results = lexical_prepass_search(
        query,
        metadata,
        bm25_index,
        k=max(k * 3, PINNED_LEXICAL_CANDIDATES),
        candidate_depth=max(candidate_depth, LEXICAL_PREPASS_DEPTH),
    )
    dense_results = embedding_search(query, usearch_index, metadata, embedding_model, candidate_depth)
    sparse_results = bm25_search(query, metadata, bm25_index, candidate_depth)

    candidates: Dict[str, Dict[str, Any]] = {}
    for result in lexical_results:
        chunk_uuid = result["metadata"].get("chunk_uuid") or result["metadata"].get("uuid")
        candidates[chunk_uuid] = {
            **result,
            "rrf_score": 1 / (RRF_K + result["lexical_prepass_rank"]),
        }

    for result in dense_results:
        chunk_uuid = result["metadata"].get("chunk_uuid") or result["metadata"].get("uuid")
        existing = candidates.get(chunk_uuid, {"metadata": result["metadata"], "rrf_score": 0.0})
        existing["rank"] = min(existing.get("rank", result["rank"]), result["rank"])
        existing["distance"] = result["distance"]
        existing["rrf_score"] += 1 / (RRF_K + result["rank"])
        candidates[chunk_uuid] = existing

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
