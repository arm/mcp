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

import gzip
import hashlib
import io
import json
import logging
import os
import sys
import tempfile
import zlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from importlib.metadata import version
from pathlib import Path
from typing import Any

from rank_bm25 import BM25Okapi
from sentence_transformers import SentenceTransformer
from usearch.index import Index

from . import analysis
from .config import K_RESULTS
from .filters import MetadataFilterIndex, SearchFilters
from .loaders import load_metadata, load_usearch_index
from .response import add_disclaimer_to_arm_results, add_utm_source_to_results
from .search import (
    LEXICAL_PREPASS_DEPTH,
    _bm25_tokens,
    _search_text,
    build_bm25_index,
    deduplication_candidate_count,
    hybrid_search,
    tokenize_for_search,
)


def _file_digest(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _keyword_cache_path(metadata_path: str) -> Path:
    return Path(metadata_path).with_suffix(".keywords.json.gz")


def _keyword_fingerprint(metadata_path: str, synonyms_path: str | None) -> dict:
    return {
        "format": 1,
        "metadata": _file_digest(metadata_path),
        "synonyms": _file_digest(synonyms_path) if synonyms_path else None,
        "source": {name: _file_digest(Path(__file__).with_name(name))
                   for name in ("analysis.py", "search.py", "resources.py")},
        "python": list(sys.version_info[:2]),
        "dependencies": {name: version(name) for name in ("regex", "markdown-it-py")},
    }


def write_keyword_cache(
    metadata_path: str, *, synonyms_path: str | None = None, cache_path: str | None = None,
) -> Path:
    """Prepare portable keyword tokens without loading a model or vector index."""
    fingerprint = _keyword_fingerprint(metadata_path, synonyms_path)
    metadata = load_metadata(metadata_path)
    synonyms = analysis.Synonyms.load(synonyms_path) if synonyms_path else analysis.EMPTY
    vocabulary: dict[str, int] = {}
    documents = []
    for row in metadata:
        documents.append([vocabulary.setdefault(term, len(vocabulary))
                          for term in _bm25_tokens(_search_text(row), synonyms)])
    if _keyword_fingerprint(metadata_path, synonyms_path) != fingerprint:
        raise ValueError("Keyword inputs changed while preparing the cache")
    output = Path(cache_path) if cache_path else _keyword_cache_path(metadata_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as stream:
            temporary = Path(stream.name)
            with gzip.GzipFile(filename="", fileobj=stream, mode="wb", compresslevel=1, mtime=0) as compressed:
                with io.TextIOWrapper(compressed, encoding="utf-8") as text:
                    text.write(json.dumps(fingerprint, separators=(",", ":")) + "\n")
                    json.dump({"vocabulary": list(vocabulary), "documents": documents}, text,
                              separators=(",", ":"))
        temporary.chmod(Path(metadata_path).stat().st_mode & 0o666)
        temporary.replace(output)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return output


def _load_keyword_cache(
    cache_path: Path, metadata_path: str, synonyms_path: str | None, row_count: int,
) -> list[list[str]] | None:
    if not cache_path.is_file():
        return None
    try:
        with gzip.open(cache_path, "rt", encoding="utf-8") as stream:
            if json.loads(stream.readline()) != _keyword_fingerprint(metadata_path, synonyms_path):
                logging.getLogger(__name__).info("Keyword cache is stale; rebuilding from source fields")
                return None
            data = json.load(stream)
        vocabulary, documents = data["vocabulary"], data["documents"]
        if (not isinstance(vocabulary, list) or not all(isinstance(term, str) for term in vocabulary)
                or not isinstance(documents, list) or len(documents) != row_count):
            raise ValueError("Invalid keyword cache vocabulary or row count")
        corpus = []
        for document in documents:
            if (not isinstance(document, list)
                    or any(type(token) is not int or not 0 <= token < len(vocabulary) for token in document)):
                raise ValueError("Invalid keyword cache token IDs")
            corpus.append([vocabulary[token] for token in document])
        return corpus
    except (OSError, EOFError, ValueError, TypeError, KeyError, zlib.error) as exc:
        logging.getLogger(__name__).warning("Cannot load keyword cache; rebuilding from source fields: %s", exc)
        return None


@dataclass
class SearchResources:
    metadata: list[dict[str, Any]]
    embedding_model: SentenceTransformer
    usearch_index: Index | None
    bm25_index: BM25Okapi | None
    default_k: int = K_RESULTS
    include_disclaimers: bool = True
    utm_source: str | None = None
    synonyms: analysis.Synonyms = field(default=analysis.EMPTY, repr=False)
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
    synonyms_path: str | None = None,
    keyword_cache_path: str | None = None,
) -> SearchResources:
    """Load search resources, treating an explicit model path as local-only."""
    metadata = load_metadata(metadata_path)
    synonyms = analysis.Synonyms.load(synonyms_path) if synonyms_path else analysis.EMPTY
    embedding_model = load_embedding_model(
        model_path if model_path is not None else model_name,
        cache_folder=cache_folder,
        allow_download=model_path is None,
    )
    usearch_index = load_usearch_index(
        usearch_index_path,
        embedding_dimension(embedding_model),
    )
    corpus = _load_keyword_cache(
        Path(keyword_cache_path) if keyword_cache_path else _keyword_cache_path(metadata_path),
        metadata_path, synonyms_path, len(metadata),
    )
    bm25_index = (build_bm25_index(metadata, synonyms) if corpus is None
                  else build_bm25_index(metadata, synonyms, tokenized_corpus=corpus))
    return SearchResources(
        metadata=metadata,
        embedding_model=embedding_model,
        usearch_index=usearch_index,
        bm25_index=bm25_index,
        default_k=default_k,
        include_disclaimers=include_disclaimers,
        utm_source=utm_source,
        synonyms=synonyms,
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
            synonyms=resources.synonyms,
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
