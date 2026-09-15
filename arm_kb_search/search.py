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

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import numpy as np
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer
from usearch.index import Index

from .config import DENSE_SEARCH_EXACT, DISTANCE_THRESHOLD, K_RESULTS

SEARCH_TOKEN_PATTERN = re.compile(r"(?:_+)?[a-z0-9][a-z0-9_\-+.]*", re.IGNORECASE)
TOKEN_SPLIT_PATTERN = re.compile(r"[_\-+.]+")
CAMEL_CASE_BOUNDARY_PATTERN = re.compile(
    r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])"
)
RRF_K = 60
LEXICAL_PREPASS_DEPTH = 400
PINNED_LEXICAL_CANDIDATES = 20
DEDUPLICATION_CANDIDATE_MULTIPLIER = 10
MIN_DEDUPLICATION_CANDIDATES = 50
SEARCH_STOPWORDS = {
    "a", "an", "and", "are", "be", "better", "can", "configured", "configuration", "for",
    "called", "do", "does", "how", "i", "improve", "in", "is", "it", "of", "on", "or", "out",
    "performance", "processor", "processors", "recommended", "settings", "should", "step", "steps",
    "system", "systems", "the", "to", "what", "which", "with", "ampere", "arm", "benchmark",
    "benchmarking", "benchmarked", "benchmarks", "brief", "cloud", "config", "configure", "guide",
    "options", "performance", "processor", "processors", "reference", "setup", "tutorial",
}
DIRECT_INTENT_STOPWORDS = {
    "a", "about", "an", "and", "app", "application", "are", "arm", "as", "based", "be", "best", "both", "by", "can", "do",
    "does", "for", "from", "get", "give", "how", "i", "in", "into", "is", "it", "learn",
    "instance", "learning", "lp", "me", "my", "new", "of", "on", "or", "path", "run", "same",
    "set", "setup", "should", "that", "the", "them", "to", "up", "use", "using", "versus", "want", "web", "what", "when", "where",
    "which", "who", "why", "with",
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
INSTALL_INTENT_TOKENS = {
    "install", "installation", "setup",
}
SUPPORT_INTENT_TOKENS = {
    "available", "availability", "capable", "capabilities", "capability", "compatible",
    "compatibility", "device", "devices", "hardware", "processor", "processors", "server",
    "servers", "support", "supported", "supporting", "supports",
}
COMPILER_GUIDE_TOKENS = {
    "compiler", "compilers", "gcc", "llvm", "clang",
}
PLATFORM_TOKENS = {
    "aarch64", "amd64", "android", "arm64", "armv8", "armv9", "centos", "debian", "fedora",
    "ios", "linux", "mac", "macos", "os", "rhel", "ubuntu", "windows", "x86", "x86_64", "x86-64",
}
# Query tokens that never identify a product or page on their own. Entity-gated
# bonuses ignore them, so "server", "install" or "linux" alone cannot satisfy a gate.
GENERIC_ENTITY_TOKENS = (
    SEARCH_STOPWORDS
    | DIRECT_INTENT_STOPWORDS
    | SUPPORT_INTENT_TOKENS
    | INSTALL_INTENT_TOKENS
    | TUTORIAL_INTENT_TOKENS
    | PLATFORM_TOKENS
    | {"app", "application", "guide", "guides", "instance", "web"}
)
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
    """Extract complete technical tokens and lowercase them."""
    return [token.lower() for token in SEARCH_TOKEN_PATTERN.findall(text or "")]


def _identifier_variants(
    raw_token: str,
    *,
    min_part_length: int = 2,
    include_compact: bool = True,
) -> List[str]:
    """Keep the exact token and add word parts and an optional compact alias.

    Queries omit compact aliases; URLs pass lowercase tokens and retain
    single-character parts. Document identifiers use the defaults.
    """
    token = raw_token.lower()
    with_camel_boundaries = CAMEL_CASE_BOUNDARY_PATTERN.sub(" ", raw_token)
    parts = [
        part.lower()
        for part in re.split(r"[_\-+.\s]+", with_camel_boundaries)
        if len(part) >= min_part_length
    ]
    variants = [token]
    if parts != [token]:
        variants.extend(parts)
    if include_compact:
        compact = TOKEN_SPLIT_PATTERN.sub("", token)
        if compact and compact != token:
            variants.append(compact)
    return variants


def _canonicalize_query_phrases(tokens: List[str]) -> List[str]:
    """Treat the adjacent words 'set up' as 'setup'."""
    canonical: List[str] = []
    for token in tokens:
        if token == "up" and canonical and canonical[-1] == "set":
            canonical[-1] = "setup"
        else:
            canonical.append(token)
    return canonical


def normalize_query_for_search(query: str) -> str:
    """Expand technical identifiers while treating generic compounds as prose."""
    expanded_tokens: List[str] = []
    for raw_token in SEARCH_TOKEN_PATTERN.findall(query or ""):
        variants = _identifier_variants(raw_token, include_compact=False)
        # Keep "pkg-config" for exact lexical matches. Generic phrases such
        # as "Arm-based" still expand to words without adding a product term.
        if (
            len(variants) > 1
            and not CAMEL_CASE_BOUNDARY_PATTERN.search(raw_token)
            and not re.search(r"[_+.0-9]", raw_token)
            and set(variants[1:]) <= GENERIC_ENTITY_TOKENS
        ):
            variants = variants[1:]
        expanded_tokens.extend(variants)

    tokens = _canonicalize_query_phrases(expanded_tokens)
    return " ".join(dict.fromkeys(tokens))


def _is_google_provider_query(query_tokens: set[str]) -> bool:
    return bool(
        query_tokens & {"autopilot", "gcp", "gke"}
        or {"google", "cloud"}.issubset(query_tokens)
        or {"compute", "engine"}.issubset(query_tokens)
    )


def tokenize_identifier_variants_for_search(text: str) -> List[str]:
    """Keep exact technical tokens and add their safe boundary variants."""
    return [
        variant
        for raw_token in SEARCH_TOKEN_PATTERN.findall(text or "")
        for variant in _identifier_variants(raw_token)
    ]


def tokenize_url_for_search(text: str) -> List[str]:
    """Expand URL tokens without camel-case splitting or dropping short parts."""
    return [
        variant
        for token in tokenize_for_search(text)
        for variant in _identifier_variants(token, min_part_length=1)
    ]


def tokenize_url_content_for_search(text: str) -> List[str]:
    parsed = urlparse(text or "")
    return tokenize_url_for_search(" ".join((parsed.path, parsed.query, parsed.fragment)))


def _normalized_doc_type(doc_type: str) -> str:
    normalized = (doc_type or "").strip().lower()
    return {
        "install guides": "install guide",
        "learning paths": "learning path",
    }.get(normalized, normalized)


def _dashboard_package_tokens(metadata: Dict[str, Any]) -> set[str]:
    tokens: set[str] = set()
    for field in ("url", "resolved_url"):
        parsed = urlparse(metadata.get(field, "") or "")
        for key, value in parse_qsl(parsed.query, keep_blank_values=True):
            if key.lower() == "package":
                tokens.update(tokenize_url_for_search(value))
    return tokens


def salient_tokens(text: str) -> List[str]:
    return [token for token in tokenize_for_search(text) if token not in SEARCH_STOPWORDS]


def direct_intent_tokens(text: str) -> List[str]:
    return [token for token in tokenize_for_search(text) if token not in DIRECT_INTENT_STOPWORDS]


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


def _lexical_exactness_score(query: str, metadata: Dict[str, Any]) -> float:
    """Score field overlap, phrases, and support evidence independently of BM25."""
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
    return weighted_overlap + phrase_bonus + support_bonus


def lexical_prepass_search(
    query: str,
    metadata: List[Dict],
    bm25_index: Optional[ParentAwareBM25],
    k: int = PINNED_LEXICAL_CANDIDATES,
    candidate_depth: int = LEXICAL_PREPASS_DEPTH,
    bm25_scores: Optional[np.ndarray] = None,
) -> List[Dict[str, Any]]:
    """Return high-exactness lexical candidates before dense retrieval is merged."""
    prepass_depth = max(k, candidate_depth)
    candidates = bm25_search(query, metadata, bm25_index, prepass_depth, scores=bm25_scores)
    if not candidates:
        return []
    scored_candidates: List[Dict[str, Any]] = []
    for candidate in candidates:
        exactness = _lexical_exactness_score(query, candidate["metadata"])
        lexical_score = exactness + min(1.0, candidate.get("bm25_score", 0.0) / 25.0)
        if lexical_score <= 0:
            continue
        scored_candidates.append({
            **candidate,
            "lexical_prepass_score": lexical_score,
            "lexical_exactness_score": exactness,
        })

    scored_candidates.sort(key=lambda item: item["lexical_prepass_score"], reverse=True)
    pinned = []
    for rank, candidate in enumerate(scored_candidates[:k], start=1):
        pinned.append({**candidate, "lexical_prepass_rank": rank, "pinned_lexical": True})
    return pinned


class ParentAwareBM25:
    """BM25 over one document per parent chunk, scored in vector-metadata index space.

    Only the first window of each parent is a BM25 document; every other window
    row receives a zero score, so callers can index the returned array with
    metadata positions without knowing about windows.
    """

    def __init__(self, corpus: List[List[str]], metadata_indices: List[int], metadata_count: int):
        self.index = BM25Okapi(corpus)
        self.metadata_indices = np.asarray(metadata_indices, dtype=int)
        self.metadata_count = metadata_count

    def get_scores(self, tokens: List[str]) -> np.ndarray:
        scores = np.zeros(self.metadata_count, dtype=float)
        scores[self.metadata_indices] = self.index.get_scores(tokens)
        return scores


def _sparse_document_tokens(metadata: Dict[str, Any]) -> List[str]:
    tokens = tokenize_for_search(metadata.get("search_text", ""))
    seen_tokens = set(tokens)
    identifier_text = _metadata_text(
        metadata,
        ("title", "heading", "heading_path", "keywords", "product", "url", "resolved_url"),
    )
    base_identifier_tokens = set(tokenize_for_search(identifier_text))
    for token in tokenize_identifier_variants_for_search(identifier_text):
        if token not in base_identifier_tokens and token not in seen_tokens:
            tokens.append(token)
            seen_tokens.add(token)
    for field in ("url", "resolved_url"):
        parsed = urlparse(str(metadata.get(field, "")))
        for token in tokenize_for_search(" ".join((parsed.path, parsed.query, parsed.fragment))):
            if TOKEN_SPLIT_PATTERN.search(token):
                compact_alias = TOKEN_SPLIT_PATTERN.sub("", token)
                if compact_alias:
                    tokens.append(compact_alias)
    return tokens


def _parent_chunk_key(metadata: Dict[str, Any]) -> str:
    return str(metadata.get("parent_chunk_uuid") or metadata.get("chunk_uuid") or "")


def _parent_representative_indices(metadata: List[Dict]) -> Dict[str, int]:
    """Choose one row per parent, preferring window 1 when present."""
    representatives: Dict[str, int] = {}
    for index, item in enumerate(metadata):
        parent_key = _parent_chunk_key(item)
        if not parent_key:
            continue
        existing_index = representatives.get(parent_key)
        if existing_index is None or (
            item.get("chunk_index", 1) == 1
            and metadata[existing_index].get("chunk_index", 1) != 1
        ):
            representatives[parent_key] = index
    return representatives


def build_bm25_index(metadata: List[Dict]) -> Optional[ParentAwareBM25]:
    representative_indices = _parent_representative_indices(metadata)
    ungrouped_indices = [
        index for index, item in enumerate(metadata) if not _parent_chunk_key(item)
    ]
    metadata_indices = sorted([*ungrouped_indices, *representative_indices.values()])
    corpus = [_sparse_document_tokens(metadata[index]) for index in metadata_indices]
    if not any(corpus):
        return None
    return ParentAwareBM25(corpus, metadata_indices, len(metadata))


def build_parent_index(metadata: List[Dict]) -> Dict[str, Dict[str, Any]]:
    """Map each parent key to its representative row carrying the full text."""
    return {
        parent_key: metadata[index]
        for parent_key, index in _parent_representative_indices(metadata).items()
    }


def _resolve_parent_representative(candidate: Dict[str, Any], parent_index: Dict[str, Dict[str, Any]]) -> None:
    """Score and display a candidate through its parent's first window.

    Later windows carry only their slice of text, so without this a parent found
    by the dense retriever through window 3 would be reranked on a fraction of
    its text and returned with a fragment as its snippet.
    """
    metadata = candidate["metadata"]
    representative = parent_index.get(_parent_chunk_key(metadata))
    if representative is None or representative is metadata:
        return
    candidate.setdefault("matched_window", {
        "chunk_uuid": metadata.get("chunk_uuid"),
        "chunk_index": metadata.get("chunk_index"),
        "chunk_count": metadata.get("chunk_count"),
    })
    candidate["metadata"] = representative


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
    results: List[Dict[str, Any]] = []
    raw_depth = min(len(metadata), max(k, k * 2))
    while raw_depth:
        matches = usearch_index.search(query_embedding, raw_depth, exact=DENSE_SEARCH_EXACT)
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
            results = []
            seen_parents: set[str] = set()
            for raw_rank, (idx, dist) in enumerate(zip(labels, distances), start=1):
                if idx == -1:
                    continue
                distance = float(dist)
                if distance >= DISTANCE_THRESHOLD:
                    break
                item_metadata = metadata[int(idx)]
                parent_key = _parent_chunk_key(item_metadata)
                if parent_key and parent_key in seen_parents:
                    continue
                if parent_key:
                    seen_parents.add(parent_key)
                results.append(
                    {
                        "rank": len(results) + 1,
                        "raw_rank": raw_rank,
                        "distance": distance,
                        "metadata": item_metadata,
                    }
                )
                if len(results) == k:
                    return results

            last_distance = float(distances[-1]) if len(distances) else DISTANCE_THRESHOLD
            if raw_depth >= len(metadata) or last_distance >= DISTANCE_THRESHOLD:
                return results
            raw_depth = min(len(metadata), raw_depth * 2)
        except Exception as exc:
            print(f"Error processing dense matches: {exc}")
            return results
    return results


def bm25_query_scores(query: str, bm25_index: Optional[ParentAwareBM25]) -> Optional[np.ndarray]:
    """BM25 score of every metadata row for ``query``; computed once per query and shared."""
    if bm25_index is None:
        return None
    tokens = tokenize_for_search(query)
    if not tokens:
        return None
    return bm25_index.get_scores(tokens)


def bm25_search(
    query: str,
    metadata: List[Dict],
    bm25_index: Optional[ParentAwareBM25],
    k: int = K_RESULTS,
    scores: Optional[np.ndarray] = None,
) -> List[Dict[str, Any]]:
    """Rank parent chunks by BM25; the index holds one document per parent."""
    if scores is None:
        scores = bm25_query_scores(query, bm25_index)
    if scores is None:
        return []
    ranking = np.argsort(scores)[::-1][:k]
    results: List[Dict[str, Any]] = []
    for rank, idx in enumerate(ranking, start=1):
        score = float(scores[idx])
        if score <= 0:
            break
        results.append({"rank": rank, "bm25_score": score, "metadata": metadata[int(idx)]})
    return results


def _overlap_ratio(query_tokens: set[str], document_tokens: set[str]) -> float:
    if not query_tokens:
        return 0.0
    return _token_match_count(query_tokens, document_tokens) / len(query_tokens)


def _is_learning_path_root_url(url: str) -> bool:
    parsed = urlparse(url or "")
    if parsed.netloc.lower() != "learn.arm.com":
        return False
    path_parts = [part for part in parsed.path.split("/") if part]
    return len(path_parts) == 3 and path_parts[0] == "learning-paths"


def _field_phrase_bonus(query_terms: List[str], field_text: str) -> float:
    if len(query_terms) < 2:
        return 0.0
    field_text = field_text.lower()
    bonus = 0.0
    for index in range(len(query_terms) - 1):
        phrase = " ".join(query_terms[index:index + 2])
        if phrase in field_text:
            bonus += 0.10
    for index in range(len(query_terms) - 2):
        phrase = " ".join(query_terms[index:index + 3])
        if phrase in field_text:
            bonus += 0.16
    return min(0.40, bonus)


def rerank_candidates(
    query: str,
    candidates: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    query_tokens = set(tokenize_for_search(query))
    if not query_tokens:
        return candidates
    salient_query_tokens = set(salient_tokens(query))
    direct_query_terms = direct_intent_tokens(query)
    direct_query_tokens = set(direct_query_terms)
    scoring_query_tokens = direct_query_tokens or salient_query_tokens or query_tokens
    prefers_tuning_guide = bool(query_tokens & TUNING_INTENT_TOKENS)
    prefers_reference_architecture = bool(query_tokens & REFERENCE_ARCHITECTURE_INTENT_TOKENS)
    prefers_tutorial = bool(query_tokens & TUTORIAL_INTENT_TOKENS)
    asks_for_learning_path = "lp" in query_tokens or {"learning", "path"}.issubset(query_tokens)
    entity_query_tokens = salient_query_tokens - GENERIC_ENTITY_TOKENS
    query_analysis = {
        "tokens": sorted(query_tokens),
        "salient_tokens": sorted(salient_query_tokens),
        "scoring_tokens": sorted(scoring_query_tokens),
        "entity_tokens": sorted(entity_query_tokens),
    }

    reranked: List[Dict[str, Any]] = []
    for candidate in candidates:
        metadata = candidate["metadata"]
        full_text_tokens = set(tokenize_for_search(metadata.get("search_text", "")))
        title_text = _metadata_text(metadata, ("title",))
        heading_text = _metadata_text(metadata, ("heading", "heading_path"))
        url_text = _metadata_text(metadata, ("url", "resolved_url"))
        source_url = metadata.get("url", "") or ""
        title_tokens = set(tokenize_identifier_variants_for_search(title_text))
        heading_tokens = set(tokenize_identifier_variants_for_search(heading_text))
        url_tokens = set(tokenize_url_content_for_search(source_url))
        resolved_url_tokens = set(tokenize_url_content_for_search(metadata.get("resolved_url", "")))
        title_url_tokens = title_tokens | url_tokens | resolved_url_tokens
        doc_type = _normalized_doc_type(metadata.get("doc_type", ""))
        provider_doc_bonus = 0.0
        if _is_google_provider_query(query_tokens) and doc_type == "google cloud documentation":
            provider_doc_bonus = 0.18
        dashboard_package_bonus = 0.0
        if (
            doc_type == "ecosystem dashboard"
            and (query_tokens & SUPPORT_INTENT_TOKENS)
            and (entity_query_tokens & _dashboard_package_tokens(metadata))
        ):
            dashboard_package_bonus = 0.30
        parent_learning_path_bonus = 0.0
        support_evidence_bonus = _support_evidence_score(
            query_tokens,
            full_text_tokens | title_tokens | heading_tokens | url_tokens | resolved_url_tokens,
            _metadata_text(metadata, ("search_text", "title", "heading", "heading_path", "url", "resolved_url")),
        )
        body_overlap = _overlap_ratio(scoring_query_tokens, full_text_tokens)
        title_overlap = _overlap_ratio(scoring_query_tokens, title_tokens)
        heading_overlap = _overlap_ratio(scoring_query_tokens, heading_tokens)
        title_url_overlap = _overlap_ratio(scoring_query_tokens, title_url_tokens)
        url_overlap = _overlap_ratio(scoring_query_tokens, url_tokens | resolved_url_tokens)
        if len(scoring_query_tokens) <= 3 and _is_learning_path_root_url(source_url):
            if asks_for_learning_path:
                parent_learning_path_bonus = 0.85 if title_url_overlap >= 0.60 else 0.25
            elif title_url_overlap >= 0.60:
                parent_learning_path_bonus = 0.15

        entity_overlap = 0.0
        if salient_query_tokens:
            entity_space = title_tokens | url_tokens | resolved_url_tokens
            entity_overlap = _overlap_ratio(salient_query_tokens, entity_space)

        direct_match_bonus = 0.0
        if scoring_query_tokens:
            direct_match_bonus += 0.35 * title_url_overlap
            direct_match_bonus += 0.15 * url_overlap
            direct_match_bonus += _field_phrase_bonus(
                direct_query_terms or list(scoring_query_tokens),
                f"{title_text} {url_text}",
            )
            if title_url_overlap >= 0.75:
                direct_match_bonus += 0.20
            if len(scoring_query_tokens) <= 3 and title_url_overlap >= 0.60:
                direct_match_bonus += 0.15
            if "guide" in query_tokens and "guide" in title_url_tokens:
                direct_match_bonus += 0.12

        shallow_overlap_penalty = 0.0
        if direct_query_tokens and title_url_overlap == 0 and heading_overlap < 0.50:
            generic_matches = len((query_tokens - direct_query_tokens) & (title_tokens | heading_tokens))
            if generic_matches >= 2:
                shallow_overlap_penalty = 0.12

        dense_bonus = 0.0
        if candidate.get("distance") is not None:
            dense_bonus = max(0.0, (DISTANCE_THRESHOLD - candidate["distance"]) / DISTANCE_THRESHOLD)
        sparse_bonus = min(1.0, candidate.get("bm25_score", 0.0) / 10.0)
        # Every fused candidate gets a lexical exactness score, so the result does
        # not depend on which candidates the prepass happened to reach. Candidates
        # the prepass already scored reuse that value.
        lexical_exactness_score = candidate.get("lexical_exactness_score")
        if lexical_exactness_score is None:
            lexical_exactness_score = _lexical_exactness_score(query, metadata)
        lexical_prepass_bonus = min(1.0, lexical_exactness_score / 2.0)
        if candidate.get("pinned_lexical"):
            lexical_prepass_bonus += 1 / (RRF_K + candidate.get("lexical_prepass_rank", RRF_K))
        doc_type_bonus = 0.0
        compiler_guide_query = bool((query_tokens & COMPILER_GUIDE_TOKENS) and "guide" in query_tokens)
        if prefers_tuning_guide and not compiler_guide_query:
            if doc_type == "tuning guide":
                doc_type_bonus += 0.30
            elif "brief" in doc_type:
                doc_type_bonus -= 0.12
        if compiler_guide_query:
            if doc_type == "tutorial" and (title_url_tokens & COMPILER_GUIDE_TOKENS) and "guide" in title_url_tokens:
                doc_type_bonus += 0.35
            elif doc_type == "tuning guide" and not (title_url_tokens & COMPILER_GUIDE_TOKENS):
                doc_type_bonus -= 0.12
        if prefers_reference_architecture:
            if doc_type == "reference architecture":
                doc_type_bonus += 0.25
            elif "brief" in doc_type:
                doc_type_bonus -= 0.05
        if prefers_tutorial:
            if doc_type in {"tutorial", "install guide", "learning path"}:
                doc_type_bonus += 0.10
        if (query_tokens & INSTALL_INTENT_TOKENS) and doc_type == "install guide":
            # Only the guide for the product the query names gets the install bonus;
            # every install guide already receives the tutorial bonus above.
            guide_entity_tokens = (
                title_tokens
                | heading_tokens
                | url_tokens
                | set(tokenize_for_search(_metadata_text(metadata, ("keywords", "product"))))
            )
            if entity_query_tokens & guide_entity_tokens:
                doc_type_bonus += 0.25
        if len(scoring_query_tokens) <= 3:
            scoring_profile = "short_query"
            contributions = {
                "reciprocal_rank_fusion": candidate.get("rrf_score", 0.0),
                "body_overlap": 0.16 * body_overlap,
                "title_overlap": 0.16 * title_overlap,
                "heading_overlap": 0.08 * heading_overlap,
                "entity_overlap": 0.12 * entity_overlap,
                "dense_similarity": 0.15 * dense_bonus,
                "bm25": 0.12 * sparse_bonus,
                "lexical_prepass": 0.25 * lexical_prepass_bonus,
                "direct_match": direct_match_bonus,
                "support_evidence": support_evidence_bonus,
                "provider_documentation": provider_doc_bonus,
                "dashboard_package_match": dashboard_package_bonus,
                "parent_learning_path": parent_learning_path_bonus,
                "document_type": doc_type_bonus,
                "shallow_overlap_penalty": -shallow_overlap_penalty,
            }
        else:
            scoring_profile = "long_query"
            full_query_body_overlap = len(query_tokens & full_text_tokens) / len(query_tokens)
            full_query_title_overlap = len(query_tokens & title_tokens) / len(query_tokens)
            full_query_heading_overlap = len(query_tokens & heading_tokens) / len(query_tokens)
            exact_entity_bonus = 0.0
            if entity_query_tokens and (entity_query_tokens & title_url_tokens):
                exact_entity_bonus = 0.18
            contributions = {
                "reciprocal_rank_fusion": candidate.get("rrf_score", 0.0),
                "body_overlap": 0.35 * full_query_body_overlap,
                "title_overlap": 0.20 * full_query_title_overlap,
                "heading_overlap": 0.15 * full_query_heading_overlap,
                "entity_overlap": 0.20 * entity_overlap,
                "dense_similarity": 0.15 * dense_bonus,
                "bm25": 0.15 * sparse_bonus,
                "lexical_prepass": 0.35 * lexical_prepass_bonus,
                "support_evidence": support_evidence_bonus,
                "provider_documentation": provider_doc_bonus,
                "dashboard_package_match": dashboard_package_bonus,
                "exact_entity": exact_entity_bonus,
                "document_type": doc_type_bonus,
            }
        rerank_score = sum(contributions.values())
        score_debug = {
            "scoring_profile": scoring_profile,
            "query_analysis": query_analysis,
            "retrieval": {
                "dense": {
                    "rank": candidate.get("dense_rank"),
                    "raw_window_rank": candidate.get("dense_raw_rank"),
                    "distance": candidate.get("distance"),
                    "distance_threshold": DISTANCE_THRESHOLD,
                },
                "bm25": {
                    "rank": candidate.get("bm25_rank"),
                    "raw_score": candidate.get("bm25_score"),
                },
                "lexical_prepass": {
                    "rank": candidate.get("lexical_prepass_rank"),
                    "raw_score": candidate.get("lexical_prepass_score"),
                    "pinned": bool(candidate.get("pinned_lexical")),
                },
                "rrf_contributions": candidate.get("rrf_contributions", {}),
                "matched_window": candidate.get("matched_window"),
            },
            "contributions": contributions,
            "final_score": rerank_score,
        }
        reranked.append({**candidate, "rerank_score": rerank_score, "score_debug": score_debug})
    return sorted(reranked, key=lambda item: item["rerank_score"], reverse=True)


def _candidate_key(result: Dict[str, Any]) -> str:
    metadata = result.get("metadata", {})
    chunk_uuid = metadata.get("parent_chunk_uuid") or metadata.get("chunk_uuid")
    if not chunk_uuid:
        url = metadata.get("url") or metadata.get("resolved_url") or "<unknown url>"
        raise ValueError(f"Search metadata missing required chunk_uuid for {url}")
    return str(chunk_uuid)


def deduplication_candidate_count(k: int) -> int:
    return max(k, min(LEXICAL_PREPASS_DEPTH, max(k * DEDUPLICATION_CANDIDATE_MULTIPLIER, MIN_DEDUPLICATION_CANDIDATES)))


def hybrid_search(
    query: str,
    usearch_index: Optional[Index],
    metadata: List[Dict],
    embedding_model: SentenceTransformer,
    bm25_index: Optional[ParentAwareBM25],
    k: int = K_RESULTS,
    candidate_depth: Optional[int] = None,
    parent_index: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Fuse lexical, dense and BM25 candidates per parent chunk and rerank them."""
    if not tokenize_for_search(query):
        return []
    if parent_index is None:
        parent_index = build_parent_index(metadata)
    candidate_depth = candidate_depth or max(k * 20, 100)
    bm25_scores = bm25_query_scores(query, bm25_index)
    lexical_results = lexical_prepass_search(
        query,
        metadata,
        bm25_index,
        k=max(k * 3, PINNED_LEXICAL_CANDIDATES),
        candidate_depth=max(candidate_depth, LEXICAL_PREPASS_DEPTH),
        bm25_scores=bm25_scores,
    )
    dense_results = embedding_search(query, usearch_index, metadata, embedding_model, candidate_depth)
    sparse_results = bm25_search(query, metadata, bm25_index, candidate_depth, scores=bm25_scores)

    candidates: Dict[str, Dict[str, Any]] = {}
    for result in lexical_results:
        candidate_key = _candidate_key(result)
        lexical_rrf = 1 / (RRF_K + result["lexical_prepass_rank"])
        candidates[candidate_key] = {
            **result,
            "rrf_score": lexical_rrf,
            "rrf_contributions": {"lexical_prepass": lexical_rrf},
        }

    for result in dense_results:
        # Capture the matching window before merging with a lexical parent.
        _resolve_parent_representative(result, parent_index)
        candidate_key = _candidate_key(result)
        existing = candidates.get(candidate_key, {"metadata": result["metadata"], "rrf_score": 0.0})
        if "matched_window" in result:
            existing["matched_window"] = result["matched_window"]
        existing["rank"] = min(existing.get("rank", result["rank"]), result["rank"])
        existing["dense_rank"] = result["rank"]
        existing["dense_raw_rank"] = result.get("raw_rank", result["rank"])
        existing["distance"] = result["distance"]
        dense_rrf = 1 / (RRF_K + result["rank"])
        existing["rrf_score"] += dense_rrf
        existing.setdefault("rrf_contributions", {})["dense"] = dense_rrf
        candidates[candidate_key] = existing

    for result in sparse_results:
        candidate_key = _candidate_key(result)
        existing = candidates.get(candidate_key, {"metadata": result["metadata"], "rrf_score": 0.0})
        existing["rank"] = min(existing.get("rank", result["rank"]), result["rank"])
        existing["bm25_rank"] = result["rank"]
        existing["bm25_score"] = result["bm25_score"]
        bm25_rrf = 1 / (RRF_K + result["rank"])
        existing["rrf_score"] += bm25_rrf
        existing.setdefault("rrf_contributions", {})["bm25"] = bm25_rrf
        candidates[candidate_key] = existing

    if parent_index:
        for candidate in candidates.values():
            _resolve_parent_representative(candidate, parent_index)

    combined = rerank_candidates(query, list(candidates.values()))
    pipeline_debug = {
        "candidate_depth": candidate_depth,
        "lexical_candidates": len(lexical_results),
        "dense_candidates": len(dense_results),
        "bm25_candidates": len(sparse_results),
        "fused_candidates": len(candidates),
    }
    for rank, result in enumerate(combined, start=1):
        result["score_debug"]["pre_dedup_rank"] = rank
        result["score_debug"]["pipeline"] = pipeline_debug
    return combined[:k]


def deduplicate_urls(results: List[Dict[str, Any]], max_chunks_per_url: int = 1) -> List[Dict[str, Any]]:
    """Keep the highest-ranked chunk for each canonical page."""
    seen_counts: Dict[str, int] = {}
    deduplicated_results = []
    for item in results:
        metadata = item["metadata"]
        url = metadata.get("resolved_url") or metadata.get("url")
        if not url:
            continue
        parsed = urlparse(url)
        query = urlencode(sorted([
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if key.lower() != "utm_source"
        ]))
        semantic_fragment = parsed.fragment if "=" in parsed.fragment else ""
        page_key = urlunparse(parsed._replace(
            scheme=parsed.scheme.lower(),
            netloc=parsed.netloc.lower(),
            path=parsed.path.rstrip("/") or "/",
            query=query,
            fragment=semantic_fragment,
        ))
        seen_counts[page_key] = seen_counts.get(page_key, 0) + 1
        if seen_counts[page_key] <= max_chunks_per_url:
            deduplicated_results.append(item)
    return deduplicated_results
