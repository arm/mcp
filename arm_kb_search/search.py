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

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional
import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import numpy as np
from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer
from usearch.index import Index, search as search_vectors

from .config import DISTANCE_THRESHOLD, K_RESULTS


SEARCH_TOKEN_PATTERN = re.compile(r"(?:_+)?[a-z0-9][a-z0-9_\-+.]*", re.IGNORECASE)
TOKEN_SPLIT_PATTERN = re.compile(r"[_\-+.]+")
RRF_K = 60
SEMANTIC_RESOURCE_WEIGHT = 0.20
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
    "options", "reference", "setup", "tutorial",
}
# Additional prose exclusions beyond SEARCH_STOPWORDS for product identity.
IDENTIFIER_PROSE_TOKENS = {
    "about", "app", "application", "as", "based", "best", "both", "by", "from", "get", "give",
    "instance", "into", "learn", "learning", "lp", "me", "my", "new", "path", "run", "same", "set",
    "that", "them", "up", "use", "using", "versus", "want", "web", "when", "where", "who", "why",
}
# Keep direct-intent stopwords separate from entity exclusions.
DIRECT_INTENT_STOPWORDS = {
    "a", "an", "and", "are", "as", "be", "both", "by", "can", "do", "does", "for", "from",
    "how", "i", "in", "into", "is", "it", "of", "on", "or", "same", "should", "that", "the",
    "them", "to", "versus", "what", "when", "where", "which", "who", "why", "with",
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
INSTALL_INTENT_TOKENS = {"install", "installing", "installation", "setup"}
INSTALL_GUIDE_BONUS = 0.30
# Acquisition adds these keywords to every install guide; they identify no product.
GENERIC_INSTALL_GUIDE_KEYWORDS = {"build", "download"}
SUPPORT_INTENT_TOKENS = {
    "available", "availability", "capable", "capabilities", "capability", "compatible",
    "compatibility", "device", "devices", "hardware", "processor", "processors", "server",
    "servers", "support", "supported", "supporting", "supports",
}
PROVIDER_DOCUMENTATION_TOKENS = {
    "autopilot", "compute", "engine", "gcp", "gke", "google", "kubernetes",
}
COMPILER_GUIDE_TOKENS = {
    "compiler", "compilers", "gcc", "llvm", "clang",
}
PLATFORM_TOKENS = {
    "aarch64", "amd64", "android", "arm64", "armv8", "armv9", "centos", "debian", "fedora",
    "ios", "linux", "mac", "macos", "os", "rhel", "ubuntu", "windows", "x86", "x86_64", "x86-64",
}
# Query tokens that never identify a product or page on their own.
GENERIC_ENTITY_TOKENS = (
    SEARCH_STOPWORDS
    | IDENTIFIER_PROSE_TOKENS
    | SUPPORT_INTENT_TOKENS
    | INSTALL_INTENT_TOKENS
    | TUTORIAL_INTENT_TOKENS
    | PLATFORM_TOKENS
    | {"guides"}
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
    """Extract technical tokens without rewriting natural-language phrases."""
    return [token.lower() for token in SEARCH_TOKEN_PATTERN.findall(text or "")]


def _query_field_tokens(tokens: set[str], query_tokens: set[str]) -> set[str]:
    """Retain explicit architecture equivalence without compound-name matching."""
    tokens = tokens.copy()
    architecture_aliases = {"arm64", "aarch64"}
    if tokens & architecture_aliases:
        tokens.update(query_tokens & architecture_aliases)
    return tokens


def tokenize_url_for_search(text: str) -> List[str]:
    """Split separators in URL content while retaining each original token."""
    tokens: List[str] = []
    for token in tokenize_for_search(text):
        tokens.append(token)
        if TOKEN_SPLIT_PATTERN.search(token):
            tokens.extend(part for part in TOKEN_SPLIT_PATTERN.split(token) if part)
    return list(dict.fromkeys(tokens))


def tokenize_url_content_for_search(text: str) -> List[str]:
    parsed = urlparse(text or "")
    return tokenize_url_for_search(" ".join((parsed.path, parsed.query, parsed.fragment)))


def _normalized_doc_type(doc_type: str) -> str:
    normalized = (doc_type or "").strip().lower()
    return {
        "install guides": "install guide",
        "learning paths": "learning path",
    }.get(normalized, normalized)


def salient_tokens(text: str) -> List[str]:
    return [token for token in tokenize_for_search(text) if token not in SEARCH_STOPWORDS]


def _installation_subject_tokens(query: str) -> set[str]:
    """Identify a short tool name before an installation's platform context."""
    match = re.search(
        r"\b(?:install(?:ing|ation)?|set\s+up|setup)\s+(.+?)\s+(?:on|in|for|using|with)\b",
        query, re.IGNORECASE,
    )
    if not match:
        return set()
    tokens = set(salient_tokens(match.group(1))) - GENERIC_ENTITY_TOKENS
    tokens -= {"tool", "tools", "package", "packages", "software", "instructions"}
    return tokens if 0 < len(tokens) <= 3 else set()


@dataclass(frozen=True)
class _QueryAnalysis:
    """Query terms and intent shared by lexical scoring and reranking."""

    query_tokens: set[str]
    lexical_query_tokens: set[str]
    salient_query_tokens: set[str]
    direct_query_tokens: set[str]
    scoring_query_tokens: set[str]
    entity_query_tokens: set[str]
    salient_query_terms: List[str]
    direct_query_terms: List[str]
    installation_query: bool
    prefers_tuning_guide: bool
    prefers_reference_architecture: bool
    prefers_tutorial: bool
    asks_for_learning_path: bool
    compiler_guide_query: bool


def _analyze_query(query: str) -> _QueryAnalysis:
    terms = tokenize_for_search(query)
    query_tokens = set(terms)
    salient_query_terms = [term for term in terms if term not in SEARCH_STOPWORDS]
    salient_query_tokens = set(salient_query_terms)
    lexical_query_tokens = salient_query_tokens.copy() or query_tokens
    setup_phrase = bool(re.search(r"\bset\s+up\b", query, re.IGNORECASE))
    installation_query = bool(query_tokens & INSTALL_INTENT_TOKENS) or setup_phrase
    if installation_query:
        if setup_phrase:
            salient_query_tokens -= {"set", "up"}
        subject_tokens = _installation_subject_tokens(query)
        if subject_tokens:
            salient_query_tokens = subject_tokens | (salient_query_tokens & PLATFORM_TOKENS)
    direct_query_terms = [term for term in terms if term not in DIRECT_INTENT_STOPWORDS]
    direct_query_tokens = set(direct_query_terms)
    scoring_query_tokens = direct_query_tokens or salient_query_tokens or query_tokens
    prefers_tuning_guide = bool(query_tokens & TUNING_INTENT_TOKENS)
    prefers_reference_architecture = bool(
        query_tokens & REFERENCE_ARCHITECTURE_INTENT_TOKENS
    )
    prefers_tutorial = bool(query_tokens & TUTORIAL_INTENT_TOKENS)
    asks_for_learning_path = (
        "lp" in query_tokens
        or {"learning", "path"}.issubset(query_tokens)
    )
    entity_query_tokens = salient_query_tokens - GENERIC_ENTITY_TOKENS
    # In a short execution request, the named tool carries more information
    # than the generic action and Arm context shared by most documents.
    if (len(direct_query_tokens) <= 3 and entity_query_tokens
            and direct_query_tokens & {"run", "use", "using"}):
        scoring_query_tokens = direct_query_tokens - {"run", "use", "using", "arm"}

    compiler_guide_query = bool(query_tokens & COMPILER_GUIDE_TOKENS) and "guide" in query_tokens
    return _QueryAnalysis(
        query_tokens=query_tokens,
        lexical_query_tokens=lexical_query_tokens,
        salient_query_tokens=salient_query_tokens,
        direct_query_tokens=direct_query_tokens,
        scoring_query_tokens=scoring_query_tokens,
        entity_query_tokens=entity_query_tokens,
        salient_query_terms=salient_query_terms,
        direct_query_terms=direct_query_terms,
        installation_query=installation_query,
        prefers_tuning_guide=prefers_tuning_guide,
        prefers_reference_architecture=prefers_reference_architecture,
        prefers_tutorial=prefers_tutorial,
        asks_for_learning_path=asks_for_learning_path,
        compiler_guide_query=compiler_guide_query,
    )


def is_navigation_only(metadata: Dict[str, Any]) -> bool:
    """Reject contribution footers and chapter menus, preserving substantive text."""
    text = metadata.get("original_text") or metadata.get("content") or ""
    if text.startswith("Document Title:"):
        text = text.partition("\n\n")[2]
    lines = [line.strip().casefold() for line in text.splitlines() if line.strip()]
    if lines and set(lines) <= {"log an issue", "fork and edit", "discuss on discord"}:
        return True
    source = urlparse(metadata.get("url") or metadata.get("resolved_url") or "")
    heading_path = metadata.get("heading_path") or []
    # Extracted chapter menus repeat the page heading around chapter headings.
    # A title anchor and short unpunctuated lines alone can also be instructions.
    return (
        source.netloc.lower() == "learn.arm.com"
        and isinstance(heading_path, list)
        and len(heading_path) >= 4
        and heading_path[0] == heading_path[-1] == metadata.get("heading")
        and heading_path[1].strip().casefold() == "introduction"
        and all(heading.strip().casefold() in lines for heading in heading_path[1:-1])
        and source.fragment in {"learning-path-title", "learning-path-step-active", "install-guide-title"}
        and len(lines) >= 3
        and lines[0] == "introduction"
        and lines[-1] == "next steps"
        and all(len(tokenize_for_search(line)) <= 18 and not re.search(r"[.!?:;`{}]", line)
                for line in lines)
    )

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


def _score_lexical_exactness(query: _QueryAnalysis, metadata: Dict[str, Any]) -> float:
    """Score field overlap, phrases, and support evidence independently of BM25."""
    query_tokens = query.query_tokens
    if not query_tokens:
        return 0.0

    weighted_overlap = 0.0
    denominator = len(query.lexical_query_tokens)
    field_weights = (
        (("title",), 0.45),
        (("heading", "heading_path"), 0.50),
        (("url", "resolved_url"), 0.35),
        (("keywords", "product", "doc_type"), 0.25),
        (("search_text",), 0.20),
    )
    for fields, weight in field_weights:
        if fields == ("url", "resolved_url"):
            field_tokens = {
                token
                for field in fields
                for token in tokenize_url_content_for_search(
                    str(metadata.get(field) or "")
                )
            }
        else:
            field_text = _metadata_text(metadata, fields)
            field_tokens = set(tokenize_for_search(field_text))
        field_tokens = _query_field_tokens(field_tokens, query_tokens)
        if not field_tokens:
            continue
        overlap = _token_match_count(
            query.lexical_query_tokens,
            field_tokens,
        ) / denominator
        weighted_overlap += weight * overlap

    all_text = _metadata_text(
        metadata,
        ("title", "heading", "heading_path", "url", "resolved_url", "keywords", "search_text"),
    )
    all_tokens = set(tokenize_for_search(all_text))
    phrase_bonus = _field_phrase_bonus(
        query.salient_query_terms, all_text, weights=(0.08, 0.12), limit=None,
    )

    support_bonus = _support_evidence_score(query_tokens, all_tokens, all_text)
    return weighted_overlap + phrase_bonus + support_bonus


def _rank_lexical_candidates(
    query: _QueryAnalysis, candidates: List[Dict[str, Any]], k: int,
) -> List[Dict[str, Any]]:
    """Rerank shared BM25 candidates by lexical evidence without rescoring BM25."""
    if not candidates:
        return []

    scored_candidates: List[Dict[str, Any]] = []
    for candidate in candidates:
        exactness = _score_lexical_exactness(query, candidate["metadata"])
        lexical_score = exactness + min(1.0, candidate.get("bm25_score", 0.0) / 25.0)
        if lexical_score <= 0:
            continue
        scored_candidates.append(
            {
                **candidate,
                "lexical_prepass_score": lexical_score,
                "lexical_exactness_score": exactness,
            }
        )

    scored_candidates.sort(key=lambda item: item["lexical_prepass_score"], reverse=True)
    pinned = []
    for rank, candidate in enumerate(scored_candidates[:k], start=1):
        pinned.append({**candidate, "lexical_prepass_rank": rank, "pinned_lexical": True})
    return pinned

def _bm25_tokens(text: str) -> List[str]:
    """Use one sparse-search term for the Arm64/AArch64 architecture aliases."""
    return ["arm64" if token == "aarch64" else token for token in tokenize_for_search(text)]


def build_bm25_index(metadata: List[Dict]) -> Optional[BM25Okapi]:
    corpus = [_bm25_tokens(item.get("search_text", "")) for item in metadata]
    if not any(corpus):
        return None
    return BM25Okapi(corpus)


def embedding_search(
    query: str,
    usearch_index: Optional[Index],
    metadata: List[Dict],
    embedding_model: SentenceTransformer,
    k: int = K_RESULTS,
    *,
    eligible_ids: Optional[tuple[int, ...]] = None,
) -> List[Dict[str, Any]]:
    """Use exact vector search, restricted to eligible IDs when supplied."""
    if usearch_index is None or eligible_ids == ():
        return []
    query_embedding = embedding_model.encode([query])[0]
    if eligible_ids is None:
        matches = usearch_index.search(query_embedding, k, exact=True)
    else:
        vectors = usearch_index.get(eligible_ids, dtype="f32")
        if any(vector is None for vector in vectors):
            raise ValueError("Search metadata and vector index have mismatched chunk IDs")
        matches = search_vectors(
            np.ascontiguousarray(vectors, dtype=np.float32),
            np.ascontiguousarray(query_embedding, dtype=np.float32),
            count=min(k, len(eligible_ids)),
            metric=usearch_index.metric,
            exact=True,
        )
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
                metadata_id = int(idx) if eligible_ids is None else eligible_ids[int(idx)]
                results.append(
                    {
                        "rank": rank,
                        "distance": distance,
                        "metadata": metadata[metadata_id],
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
    *,
    eligible_ids: Optional[tuple[int, ...]] = None,
) -> List[Dict[str, Any]]:
    if bm25_index is None or eligible_ids == ():
        return []
    tokens = _bm25_tokens(query)
    if not tokens:
        return []
    if eligible_ids is None:
        scores = bm25_index.get_scores(tokens)
    else:
        # rank-bm25 uses NumPy indexing, where a tuple means multiple axes.
        scores = bm25_index.get_batch_scores(tokens, list(eligible_ids))
    ranking = np.argsort(scores)[::-1]
    results: List[Dict[str, Any]] = []
    for rank, idx in enumerate(ranking[:k], start=1):
        score = float(scores[idx])
        if score <= 0:
            continue
        metadata_id = int(idx) if eligible_ids is None else eligible_ids[int(idx)]
        results.append(
            {
                "rank": rank,
                "bm25_score": score,
                "metadata": metadata[metadata_id],
            }
        )
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


def _field_phrase_bonus(
    query_terms: List[str], field_text: str, *,
    weights: tuple[float, float] = (0.10, 0.16), limit: Optional[float] = 0.40,
) -> float:
    """Score adjacent pairs/triples in order, with the caller's weights and cap."""
    query_terms = [re.sub(r"\baarch64\b", "arm64", term.lower()) for term in query_terms]
    field_text = re.sub(r"\baarch64\b", "arm64", field_text.lower())
    bonus = 0.0
    for size, weight in enumerate(weights, start=2):
        for index in range(len(query_terms) - size + 1):
            if " ".join(query_terms[index:index + size]) in field_text:
                bonus += weight
    return min(limit, bonus) if limit is not None else bonus


def _document_type_bonuses(
    query: _QueryAnalysis,
    metadata: Dict[str, Any],
    *,
    title_tokens: set[str],
    heading_tokens: set[str],
    url_tokens: set[str],
    title_url_tokens: set[str],
) -> tuple[float, float]:
    """Return provider and document-type preferences as separate score terms."""
    doc_type = _normalized_doc_type(metadata.get("doc_type", ""))
    provider_doc_bonus = 0.0
    if query.query_tokens & PROVIDER_DOCUMENTATION_TOKENS and doc_type == "google cloud documentation":
        provider_doc_bonus = 0.18

    doc_type_bonus = 0.0
    if query.prefers_tuning_guide and not query.compiler_guide_query:
        if doc_type == "tuning guide":
            doc_type_bonus += 0.30
        elif "brief" in doc_type:
            doc_type_bonus -= 0.12
    if query.compiler_guide_query:
        if (
            doc_type == "tutorial"
            and (title_url_tokens & COMPILER_GUIDE_TOKENS)
            and "guide" in title_url_tokens
        ):
            doc_type_bonus += 0.35
        elif (
            doc_type == "tuning guide"
            and not (title_url_tokens & COMPILER_GUIDE_TOKENS)
        ):
            doc_type_bonus -= 0.12
    if query.prefers_reference_architecture:
        if doc_type == "reference architecture":
            doc_type_bonus += 0.25
        elif "brief" in doc_type:
            doc_type_bonus -= 0.05
    if query.prefers_tutorial and doc_type in {
        "tutorial",
        "install guide",
        "learning path",
    }:
        doc_type_bonus += 0.10
    if query.installation_query and doc_type == "install guide":
        guide_entity_tokens = (
            title_tokens
            | heading_tokens
            | url_tokens
            | set(
                tokenize_for_search(
                    _metadata_text(metadata, ("keywords", "product"))
                )
            )
        )
        if query.entity_query_tokens & (
            guide_entity_tokens - GENERIC_INSTALL_GUIDE_KEYWORDS
        ):
            doc_type_bonus += INSTALL_GUIDE_BONUS

    return provider_doc_bonus, doc_type_bonus


def rerank_candidates(
    query: str,
    candidates: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Rerank candidates using the same query analysis as hybrid search."""
    return _rerank_candidates(_analyze_query(query), candidates)


def _rerank_candidates(
    query: _QueryAnalysis,
    candidates: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    query_tokens = query.query_tokens
    if not query_tokens:
        return candidates
    salient_query_tokens = query.salient_query_tokens
    direct_query_terms = query.direct_query_terms
    direct_query_tokens = query.direct_query_tokens
    scoring_query_tokens = query.scoring_query_tokens
    entity_query_tokens = query.entity_query_tokens
    short_query = len(scoring_query_tokens) <= 3
    reranked: List[Dict[str, Any]] = []
    for candidate in candidates:
        metadata = candidate["metadata"]
        if is_navigation_only(metadata):
            continue
        full_text = metadata.get("search_text", "")
        full_text_tokens = _query_field_tokens(
            set(tokenize_for_search(full_text)), query_tokens
        )
        title_text = _metadata_text(metadata, ("title",))
        heading_text = _metadata_text(metadata, ("heading", "heading_path"))
        url_text = _metadata_text(metadata, ("url", "resolved_url"))
        source_url = metadata.get("url") or metadata.get("resolved_url") or ""

        title_tokens = _query_field_tokens(
            set(tokenize_for_search(title_text)), query_tokens
        )
        heading_tokens = _query_field_tokens(
            set(tokenize_for_search(heading_text)), query_tokens
        )
        url_tokens = _query_field_tokens(
            set(tokenize_url_content_for_search(source_url)), query_tokens
        )
        resolved_url_tokens = _query_field_tokens(
            set(tokenize_url_content_for_search(metadata.get("resolved_url", ""))), query_tokens
        )
        title_url_tokens = title_tokens | url_tokens | resolved_url_tokens
        support_evidence_bonus = _support_evidence_score(
            query_tokens,
            full_text_tokens
            | title_tokens
            | heading_tokens
            | url_tokens
            | resolved_url_tokens,
            _metadata_text(
                metadata,
                (
                    "search_text",
                    "title",
                    "heading",
                    "heading_path",
                    "url",
                    "resolved_url",
                ),
            ),
        )

        entity_overlap = _overlap_ratio(salient_query_tokens, title_url_tokens)
        # Short queries use direct-name, learning-path and shallow-overlap rules.
        # Longer queries use the entity bonus below; these other scores cannot affect them.
        if short_query:
            title_url_overlap = _overlap_ratio(scoring_query_tokens, title_url_tokens)
            heading_overlap = _overlap_ratio(scoring_query_tokens, heading_tokens)
            intent_bonus = 0.35 * title_url_overlap
            intent_bonus += 0.15 * _overlap_ratio(scoring_query_tokens, url_tokens | resolved_url_tokens)
            intent_bonus += _field_phrase_bonus(
                direct_query_terms or list(scoring_query_tokens), f"{title_text} {url_text}",
            )
            if title_url_overlap >= 0.75:
                intent_bonus += 0.20
            if title_url_overlap >= 0.60:
                intent_bonus += 0.15
            if "guide" in query_tokens and "guide" in title_url_tokens:
                intent_bonus += 0.12

            if _is_learning_path_root_url(source_url):
                if query.asks_for_learning_path:
                    intent_bonus += 0.85 if title_url_overlap >= 0.60 else 0.25
                elif title_url_overlap >= 0.60:
                    intent_bonus += 0.15
            if direct_query_tokens and title_url_overlap == 0 and heading_overlap < 0.50:
                generic_matches = (query_tokens - direct_query_tokens) & (title_tokens | heading_tokens)
                if len(generic_matches) >= 2:
                    intent_bonus -= 0.12
        else:
            intent_bonus = 0.18 if entity_query_tokens & title_url_tokens else 0.0

        dense_bonus = 0.0
        if candidate.get("distance") is not None:
            dense_bonus = max(
                0.0,
                (DISTANCE_THRESHOLD - candidate["distance"]) / DISTANCE_THRESHOLD,
            )
        sparse_bonus = min(1.0, candidate.get("bm25_score", 0.0) / 10.0)

        lexical_exactness_score = candidate.get("lexical_exactness_score")
        if lexical_exactness_score is None:
            lexical_exactness_score = _score_lexical_exactness(query, metadata)
        lexical_prepass_bonus = min(1.0, lexical_exactness_score / 2.0)
        if candidate.get("pinned_lexical"):
            lexical_prepass_bonus += 1 / (
                RRF_K + candidate.get("lexical_prepass_rank", RRF_K)
            )

        provider_doc_bonus, doc_type_bonus = _document_type_bonuses(
            query, metadata, title_tokens=title_tokens, heading_tokens=heading_tokens,
            url_tokens=url_tokens, title_url_tokens=title_url_tokens,
        )

        # Preserve direct-name matching for short queries, but don't let the
        # wording of an installation question outweigh its subject. Both paths share
        # the same evidence terms and a single score calculation.
        if short_query:
            overlaps = tuple(_overlap_ratio(scoring_query_tokens, tokens)
                             for tokens in (full_text_tokens, title_tokens, heading_tokens))
            field_weights = (0.16, 0.16, 0.08)
        else:
            overlaps = tuple(len(query_tokens & tokens) / len(query_tokens)
                             for tokens in (full_text_tokens, title_tokens, heading_tokens))
            if query.installation_query:
                overlaps = tuple(
                    (overlap + _overlap_ratio(salient_query_tokens or query_tokens, tokens)) / 2
                    for overlap, tokens in zip(overlaps, (full_text_tokens, title_tokens, heading_tokens))
                )
            field_weights = (0.35, 0.20, 0.15)
        rerank_score = (
            candidate.get("rrf_score", 0.0)
            + sum(weight * overlap for weight, overlap in zip(field_weights, overlaps))
            + ((0.12 if short_query else 0.20) * entity_overlap)
            + (0.15 * dense_bonus)
            + ((0.12 if short_query else 0.15) * sparse_bonus)
            + ((0.25 if short_query else 0.35) * lexical_prepass_bonus)
            + support_evidence_bonus
            + provider_doc_bonus
            + doc_type_bonus
            + intent_bonus
        )
        reranked.append({**candidate, "rerank_score": rerank_score})

    return sorted(reranked, key=lambda item: item["rerank_score"], reverse=True)


def _candidate_key(result: Dict[str, Any]) -> str:
    metadata = result.get("metadata", {})
    chunk_uuid = metadata.get("chunk_uuid")
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
    bm25_index: Optional[BM25Okapi],
    k: int = K_RESULTS,
    candidate_depth: Optional[int] = None,
    *,
    eligible_ids: Optional[tuple[int, ...]] = None,
) -> List[Dict[str, Any]]:
    if eligible_ids == ():
        return []
    lexical_query = " ".join(dict.fromkeys(tokenize_for_search(query)))
    if not lexical_query:
        return []
    query_analysis = _analyze_query(query)

    candidate_depth = candidate_depth or max(k * 20, 100)
    lexical_limit = max(k * 3, PINNED_LEXICAL_CANDIDATES)
    bm25_depth = max(candidate_depth, LEXICAL_PREPASS_DEPTH, lexical_limit)

    # Share one BM25 ranking between the lexical prepass and sparse search.
    bm25_results = bm25_search(
        lexical_query,
        metadata,
        bm25_index,
        k=bm25_depth,
        eligible_ids=eligible_ids,
    )

    lexical_results = _rank_lexical_candidates(
        query_analysis, bm25_results, k=lexical_limit
    )
    sparse_results = bm25_results[:candidate_depth]

    dense_depth = candidate_depth
    if query_analysis.installation_query:
        dense_depth = max(dense_depth, 200)
    dense_results = embedding_search(
        query, usearch_index, metadata, embedding_model, dense_depth,
        eligible_ids=eligible_ids,
    )

    candidates: Dict[str, Dict[str, Any]] = {}
    for result in lexical_results:
        candidate_key = _candidate_key(result)
        candidates[candidate_key] = {
            **result,
            "rrf_score": 1 / (RRF_K + result["lexical_prepass_rank"]),
        }

    for results, score_field in ((dense_results, "distance"), (sparse_results, "bm25_score")):
        for result in results:
            existing = candidates.setdefault(
                _candidate_key(result), {"metadata": result["metadata"], "rrf_score": 0.0},
            )
            existing["rank"] = min(existing.get("rank", result["rank"]), result["rank"])
            existing[score_field] = result[score_field]
            existing["rrf_score"] += 1 / (RRF_K + result["rank"])

    combined = _rerank_candidates(query_analysis, list(candidates.values()))
    return fuse_semantic_resource_ranks(combined)[:k]


def _canonical_resource_key(metadata: Dict[str, Any]) -> Optional[tuple[str, str]]:
    """Identify a public section/resource and retain dashboard edition identity."""
    # The fetch location may differ from the public page for any document type.
    url = metadata.get("url") or metadata.get("resolved_url")
    if not url:
        return None
    source = urlparse(url)
    query = sorted(
        (key, val)
        for key, val in parse_qsl(source.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
    )
    canonical_url = urlunparse(
        source._replace(
            scheme=source.scheme.lower(),
            netloc=source.netloc.lower(),
            path=source.path.rstrip("/") or "/",
            query=urlencode(query),
        )
    )
    dashboard = (
        metadata.get("doc_type") == "Ecosystem Dashboard"
        and metadata.get("content_type") == "markdown"
    )
    edition = str(metadata.get("edition") or "") if dashboard else ""
    return canonical_url, edition


def fuse_semantic_resource_ranks(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Combine hybrid and semantic ranks without discarding distinct sections.

    Each URL/section gets one vote per channel, even when it has several chunks.
    Keep the hybrid-selected passage and apply fusion before candidate truncation.
    """
    resources = deduplicate_urls(results)
    semantic = deduplicate_urls(sorted(
        (item for item in results if item.get("distance") is not None),
        key=lambda item: item["distance"],
    ))
    if not semantic:
        return resources
    semantic_ranks = {
        _canonical_resource_key(item["metadata"]): rank
        for rank, item in enumerate(semantic, 1)
    }
    fused = []
    for rank, item in enumerate(resources, 1):
        semantic_rank = semantic_ranks.get(_canonical_resource_key(item["metadata"]))
        score = (1 - SEMANTIC_RESOURCE_WEIGHT) / rank
        if semantic_rank is not None:
            score += SEMANTIC_RESOURCE_WEIGHT / semantic_rank
        fused.append({**item, "rerank_score": score})
    return sorted(fused, key=lambda item: item["rerank_score"], reverse=True)


def deduplicate_urls(
    results: List[Dict[str, Any]],
    max_chunks_per_url: int = 1,
) -> List[Dict[str, Any]]:
    """Keep the highest-ranked chunk per canonical URL, preserving sections."""
    seen_counts: Dict[tuple[str, str], int] = {}
    deduplicated_results = []
    for item in results:
        page_key = _canonical_resource_key(item["metadata"])
        if not page_key:
            continue
        seen_counts[page_key] = seen_counts.get(page_key, 0) + 1
        if seen_counts[page_key] <= max_chunks_per_url:
            deduplicated_results.append(item)
    return deduplicated_results
