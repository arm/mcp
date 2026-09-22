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

import argparse
import datetime
import glob
import json
import os
import re
from typing import Any

import numpy as np
import yaml
from sentence_transformers import SentenceTransformer
from usearch.index import Index

EMBEDDING_WINDOW_OVERLAP_TOKENS = 0
MAX_EMBEDDING_CONTEXT_TOKENS = 64
EMBEDDING_TOKEN_SAFETY_MARGIN = 2
CONTENT_PREFIX_PATTERN = re.compile(
    r"^Document Title:\s*(.*?)\nHeading Path:\s*(.*?)\n\n",
    re.DOTALL,
)


def load_local_yaml_files() -> list[dict]:
    """Load locally stored YAML files and return their contents as a list of dictionaries."""
    print("Loading local YAML files")
    yaml_contents = []
    intrinsic_dir = os.getenv("INTRINSIC_CHUNKS_DIR", "intrinsic_chunks")
    yaml_dir = os.getenv("YAML_DATA_DIR", "yaml_data")

    intrinsic_files = sorted(glob.glob(os.path.join(intrinsic_dir, "*.yaml")))
    print(f"Found {len(intrinsic_files)} YAML files in {intrinsic_dir} directory")
    if not intrinsic_files:
        raise FileNotFoundError(
            f"No intrinsic chunk YAML files found in '{intrinsic_dir}'. "
            "Supply the intrinsic chunks before creating the vector store."
        )

    yaml_data_files = sorted(glob.glob(os.path.join(yaml_dir, "*.yaml")))
    print(f"Found {len(yaml_data_files)} YAML files in {yaml_dir} directory")

    # Combine all files
    all_files = intrinsic_files + yaml_data_files
    total_files = len(all_files)
    print(f"Total files to process: {total_files}")

    for i, file_path in enumerate(all_files, 1):
        if i <= 10 or i % 1000 == 0 or i == total_files:
            print(f"Loading file {i}/{total_files}: {file_path}")

        # Extract chunk identifier based on file location
        if os.path.normpath(file_path).startswith(os.path.normpath(intrinsic_dir)):
            chunk_uuid = f"intrinsic_{os.path.basename(file_path).replace('.yaml', '')}"
        elif os.path.normpath(file_path).startswith(os.path.normpath(yaml_dir)):
            chunk_uuid = f"yaml_data_{os.path.basename(file_path).replace('.yaml', '')}"
        else:
            chunk_uuid = file_path.replace("chunk_", "").replace(".yaml", "")

        try:
            with open(file_path, "r") as f:
                yaml_content = yaml.safe_load(f)
                yaml_content["chunk_uuid"] = chunk_uuid
                yaml_contents.append(yaml_content)
        except Exception as e:
            print(f"Error loading {file_path}: {e}")
            continue

    print(f"Successfully loaded {len(yaml_contents)} YAML files")
    return yaml_contents


def load_embedding_model(model_path: str) -> SentenceTransformer:
    """Load the local SentenceTransformer used for splitting and embedding."""
    return SentenceTransformer(
        model_path,
        local_files_only=True,
        trust_remote_code=False,
    )


def _token_offsets(tokenizer: Any, text: str) -> list[tuple[int, int]]:
    encoded = tokenizer(
        text,
        add_special_tokens=False,
        return_offsets_mapping=True,
        truncation=False,
        padding=False,
    )
    return [
        tuple(offset) for offset in encoded["offset_mapping"] if tuple(offset) != (0, 0)
    ]


def _truncate_to_tokens(tokenizer: Any, text: str, max_tokens: int) -> str:
    offsets = _token_offsets(tokenizer, text)
    if len(offsets) <= max_tokens:
        return text
    return text[: offsets[max_tokens - 1][1]]


def _word_start(offsets: list[tuple[int, int]], token_index: int) -> int:
    """Return the index of the first piece of the word that contains ``token_index``.

    Sub-word pieces are contiguous in the character offsets (a piece starts where
    the previous one ends), so walking back over contiguous pieces lands on the
    first piece of the word. Whitespace between words breaks the chain.
    """
    while token_index > 0 and offsets[token_index][0] == offsets[token_index - 1][1]:
        token_index -= 1
    return token_index


def _window_spans(
    tokenizer: Any,
    text: str,
    max_tokens: int,
    overlap_tokens: int,
) -> list[tuple[int, int]]:
    """Split ``text`` into lossless character spans of at most ``max_tokens`` tokens.

    Windows start and end on word boundaries whenever the budget allows it, so
    neither the embedded text nor a displayed window begins with a word fragment.
    A single word longer than the budget is the only case that is cut mid-word.
    """
    if max_tokens <= 0:
        raise ValueError("Embedding body token budget must be positive")
    if overlap_tokens < 0 or overlap_tokens >= max_tokens:
        raise ValueError("Embedding overlap must be smaller than the body token budget")
    offsets = _token_offsets(tokenizer, text)
    if len(offsets) <= max_tokens:
        return [(0, len(text))]

    spans = []
    start_token = 0
    covered_end_token = 0
    while start_token < len(offsets):
        end_token = min(len(offsets), start_token + max_tokens)
        if end_token < len(offsets):
            word_start = _word_start(offsets, end_token)
            # Prefer a word boundary only if doing so still extends coverage.
            # A long sub-word-tokenized word can otherwise make many later
            # windows backtrack to the same end and embed no new content.
            if word_start > max(start_token, covered_end_token):
                end_token = word_start
        if end_token <= covered_end_token:
            # Splitting an oversized word is better than emitting a redundant
            # window or stalling before the word's remaining pieces.
            end_token = min(
                len(offsets), max(covered_end_token + 1, start_token + max_tokens)
            )
        start_char = 0 if start_token == 0 else offsets[start_token][0]
        end_char = len(text) if end_token == len(offsets) else offsets[end_token][0]
        spans.append((start_char, end_char))
        covered_end_token = end_token
        if end_token == len(offsets):
            break
        next_start = _word_start(
            offsets, max(end_token - overlap_tokens, start_token + 1)
        )
        if next_start <= start_token:
            next_start = max(end_token - overlap_tokens, start_token + 1)
        start_token = next_start
    return spans


def _embedding_context(yaml_content: dict, tokenizer: Any) -> str:
    """Title plus the full heading path, the context prepended to every window."""
    heading_path = [
        str(heading).strip()
        for heading in (yaml_content.get("heading_path", []) or [])
        if str(heading).strip()
    ]
    values = [yaml_content.get("title", "")]
    if heading_path:
        values.append(" > ".join(heading_path))
    elif yaml_content.get("heading"):
        values.append(str(yaml_content["heading"]))
    unique_values = []
    for value in values:
        normalized = str(value).strip()
        if normalized and normalized not in unique_values:
            unique_values.append(normalized)
    return _truncate_to_tokens(
        tokenizer,
        "\n".join(unique_values),
        MAX_EMBEDDING_CONTEXT_TOKENS,
    )


def _content_body(content: str) -> str:
    match = CONTENT_PREFIX_PATTERN.match(content)
    return content[match.end() :] if match else content


def _is_legacy_intrinsic(record: dict) -> bool:
    """Keep intrinsic embedding inputs unchanged while document windowing evolves."""
    return str(record.get("chunk_uuid", "")).startswith("intrinsic_") or (
        "/instruction-sets/intrinsics/" in str(record.get("url", ""))
    )


def _metadata_for_window(
    yaml_content: dict,
    original_text: str,
    search_text_content: str,
    chunk_uuid: str,
    parent_chunk_uuid: str,
    chunk_index: int,
    chunk_count: int,
    content_start_char: int,
    content_end_char: int,
    parent_content_length: int,
    embedding_token_count: int,
    embedding_window_policy: str,
    overlap_tokens: int = 0,
    source_embedding_token_count: int | None = None,
) -> dict:
    source_token_count = source_embedding_token_count or embedding_token_count
    window_reference = {
        "chunk_uuid": chunk_uuid,
        "parent_chunk_uuid": parent_chunk_uuid,
        "chunk_index": chunk_index,
        "chunk_count": chunk_count,
        "content_start_char": content_start_char,
        "content_end_char": content_end_char,
        "parent_content_length": parent_content_length,
        "embedding_token_count": embedding_token_count,
        "source_embedding_token_count": source_token_count,
        "embedding_was_truncated": source_token_count > embedding_token_count,
        "embedding_window_policy": embedding_window_policy,
        "embedding_window_overlap_tokens": overlap_tokens,
    }
    if chunk_index != 1:
        # Dense retrieval only needs enough information to resolve this vector
        # to the first (representative) row. Keeping the parent text and all of
        # its lexical fields on every child duplicates tens of megabytes and
        # those fields are never scored or returned.
        return window_reference

    heading_path = yaml_content.get("heading_path", []) or []
    search_text = " ".join(
        str(value)
        for value in [
            yaml_content.get("title", ""),
            " ".join(heading_path),
            yaml_content.get("heading", ""),
            yaml_content.get("doc_type", ""),
            yaml_content.get("product", ""),
            yaml_content.get("version", ""),
            yaml_content.get("keywords", ""),
            search_text_content,
        ]
        if value
    )
    return {
        "uuid": yaml_content["uuid"],
        "url": yaml_content["url"],
        "resolved_url": yaml_content.get("resolved_url", yaml_content["url"]),
        "original_text": original_text,
        "title": yaml_content["title"],
        "keywords": yaml_content["keywords"],
        **window_reference,
        "heading": yaml_content.get("heading", ""),
        "heading_path": heading_path,
        "doc_type": yaml_content.get("doc_type", ""),
        "product": yaml_content.get("product", ""),
        "version": yaml_content.get("version", ""),
        "content_type": yaml_content.get("content_type", ""),
        "search_text": search_text,
    }


def _fit_embedding_text(
    tokenizer: Any,
    context: str,
    separator: str,
    body_window: str,
    max_seq_length: int,
) -> tuple[str, int, str, bool]:
    """Return the longest prefix of a window that fits after adding context.

    Windows are budgeted with a safety margin, but joining the context and the
    window can tokenise differently at the seam. Retrying shorter prefixes
    guarantees the returned input actually fits. The caller verifies that
    fitted windows still cover the full parent body, so trimming
    can never silently lose content. This correctness-first fallback is linear
    in the bounded model token limit; the pinned corpus currently fits without
    invoking it, and each invocation is reported by ``prepare_embedding_records``.
    """

    def render(window: str) -> tuple[str, int]:
        embedding_text = f"{context}{separator}{window}"
        token_count = len(
            tokenizer(
                embedding_text,
                add_special_tokens=True,
                truncation=False,
                padding=False,
            )["input_ids"]
        )
        return embedding_text, token_count

    embedding_text, token_count = render(body_window)
    if token_count <= max_seq_length:
        return embedding_text, token_count, body_window, False

    window_offsets = _token_offsets(tokenizer, body_window)
    for keep_tokens in range(len(window_offsets) - 1, -1, -1):
        trimmed_window = (
            ""
            if keep_tokens == 0
            else body_window[: window_offsets[keep_tokens - 1][1]]
        )
        candidate_text, candidate_count = render(trimmed_window)
        if candidate_count <= max_seq_length:
            return candidate_text, candidate_count, trimmed_window, True
    raise ValueError("Embedding context alone exceeds the model token limit")


def prepare_embedding_records(
    yaml_contents: list[dict],
    tokenizer: Any,
    max_seq_length: int,
    overlap_tokens: int = EMBEDDING_WINDOW_OVERLAP_TOKENS,
) -> tuple[list[str], list[dict]]:
    """Create adaptive embedding records that fit the embedding model.

    Documentation uses lossless tokenizer-aligned windows. The production
    default is zero overlap, as selected by the retrieval ablation. Intrinsics keep main's
    original input text and one-vector encoding, including the model's existing
    truncation behavior. Their complete text remains available for lexical search
    and display. The server groups document windows by ``parent_chunk_uuid`` and
    scores and displays each parent through its first window.
    """
    special_tokens = tokenizer.num_special_tokens_to_add(pair=False)
    contents = []
    metadata = []
    trimmed_windows = 0
    for yaml_content in yaml_contents:
        source_content = yaml_content["content"]
        if _is_legacy_intrinsic(yaml_content):
            # Do not rewrite intrinsic descriptions or lexical metadata in the
            # document-windowing change. The encoder retains its legacy limit.
            contents.append(source_content)
            token_count = len(
                tokenizer(
                    source_content,
                    add_special_tokens=True,
                    truncation=False,
                    padding=False,
                )["input_ids"]
            )
            metadata.append(
                _metadata_for_window(
                    yaml_content,
                    source_content,
                    source_content,
                    yaml_content["chunk_uuid"],
                    yaml_content["chunk_uuid"],
                    1,
                    1,
                    0,
                    len(source_content),
                    len(source_content),
                    min(token_count, max_seq_length),
                    "legacy_single_vector",
                    source_embedding_token_count=token_count,
                )
            )
            continue
        body = _content_body(source_content)
        context = _embedding_context(yaml_content, tokenizer)
        separator = "\n\n" if context and body else ""
        context_token_count = len(
            tokenizer(
                f"{context}{separator}",
                add_special_tokens=False,
                truncation=False,
                padding=False,
            )["input_ids"]
        )
        body_budget = (
            max_seq_length
            - special_tokens
            - context_token_count
            - EMBEDDING_TOKEN_SAFETY_MARGIN
        )
        parent_chunk_uuid = yaml_content["chunk_uuid"]
        embedding_window_policy = "lossless_windows"
        while True:
            spans = _window_spans(tokenizer, body, body_budget, overlap_tokens)
            fitted_windows = []
            covered_end_char = 0
            budget_reduction = 0
            coverage_is_lossless = True
            for start_char, end_char in spans:
                body_window = body[start_char:end_char]
                embedding_text, embedding_token_count, fitted_body_window, trimmed = (
                    _fit_embedding_text(
                        tokenizer, context, separator, body_window, max_seq_length
                    )
                )
                fitted_end_char = start_char + len(fitted_body_window)
                if trimmed:
                    budget_reduction = max(
                        budget_reduction,
                        len(_token_offsets(tokenizer, body_window))
                        - len(_token_offsets(tokenizer, fitted_body_window)),
                    )
                if start_char > covered_end_char or (
                    body and fitted_end_char <= covered_end_char
                ):
                    coverage_is_lossless = False
                    break
                covered_end_char = fitted_end_char
                fitted_windows.append(
                    (
                        start_char,
                        fitted_end_char,
                        embedding_text,
                        embedding_token_count,
                        trimmed,
                    )
                )
            if coverage_is_lossless and covered_end_char == len(body):
                break
            body_budget -= max(1, budget_reduction)
            if body_budget <= overlap_tokens:
                raise ValueError(
                    f"Unable to create lossless embedding windows for {parent_chunk_uuid}"
                )

        chunk_count = len(fitted_windows)
        for chunk_index, (
            start_char,
            fitted_end_char,
            embedding_text,
            embedding_token_count,
            trimmed,
        ) in enumerate(fitted_windows, start=1):
            if trimmed:
                trimmed_windows += 1
                print(
                    f"Warning: trimmed window {chunk_index}/{chunk_count} of {parent_chunk_uuid} "
                    f"to {embedding_token_count} tokens to fit the model limit"
                )
            chunk_uuid = parent_chunk_uuid
            if chunk_count > 1:
                chunk_uuid = (
                    f"{parent_chunk_uuid}__window_{chunk_index}_of_{chunk_count}"
                )
            original_text = source_content if chunk_index == 1 else ""
            search_text_content = ""
            if chunk_index == 1:
                search_text_content = source_content
            contents.append(embedding_text)
            metadata.append(
                _metadata_for_window(
                    yaml_content,
                    original_text,
                    search_text_content,
                    chunk_uuid,
                    parent_chunk_uuid,
                    chunk_index,
                    chunk_count,
                    start_char,
                    fitted_end_char,
                    len(body),
                    embedding_token_count,
                    embedding_window_policy,
                    overlap_tokens,
                )
            )
    if trimmed_windows:
        print(
            f"Trimmed {trimmed_windows} embedding windows that overflowed the model limit"
        )
    return contents, metadata


def create_embeddings(
    contents: list[str],
    model: SentenceTransformer,
) -> np.ndarray:
    """Create embeddings for the given contents using SentenceTransformers."""
    embeddings = model.encode(contents, show_progress_bar=True, convert_to_numpy=True)
    print(f"Created embeddings with shape: {embeddings.shape}")
    return embeddings


def create_usearch_index(
    embeddings: np.ndarray, metadata: list[dict]
) -> tuple[Index, list[dict]]:
    """Create a USearch index with the given embeddings and metadata."""
    print("Creating USearch index")
    print(f"Embeddings shape: {embeddings.shape}")

    dimension = embeddings.shape[1]
    num_vectors = embeddings.shape[0]

    # Create USearch index
    index = Index(
        ndim=dimension,
        metric="l2sq",
        dtype="f32",
        connectivity=16,
        expansion_add=128,
        expansion_search=64,
    )

    # Add vectors to the index
    print(f"Adding {num_vectors} vectors to the index")
    for i, embedding in enumerate(embeddings):
        index.add(i, embedding)

    print(f"Added {len(index)} vectors to the index")
    return index, metadata


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create the USearch datastore from local chunks and a local embedding model."
    )
    parser.add_argument(
        "--model-path",
        required=True,
        help="Path to the embedding model created by acquire-model.py.",
    )
    parser.add_argument(
        "--skip-embeddings-text",
        action="store_true",
        help="Do not write the optional plain-text embedding matrix.",
    )
    parser.add_argument(
        "--window-overlap-tokens",
        type=int,
        default=EMBEDDING_WINDOW_OVERLAP_TOKENS,
        help="Body-token overlap between windows (production default: 0).",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    print("Starting the USearch datastore creation process")

    # Load local YAML files
    yaml_contents = load_local_yaml_files()

    print(f"Loading embedding model: {args.model_path}")
    model = load_embedding_model(args.model_path)

    print("Creating tokenizer-aligned embedding windows")
    contents, metadata = prepare_embedding_records(
        yaml_contents,
        model.tokenizer,
        model.max_seq_length,
        overlap_tokens=args.window_overlap_tokens,
    )
    split_parents = len(
        {item["parent_chunk_uuid"] for item in metadata if item["chunk_count"] > 1}
    )
    legacy_intrinsic_parents = len(
        {
            item["parent_chunk_uuid"]
            for item in metadata
            if item["embedding_window_policy"] == "legacy_single_vector"
        }
    )
    print(
        f"Prepared {len(contents)} embedding windows from {len(yaml_contents)} source chunks; "
        f"split {split_parents} oversized document chunks and preserved "
        f"{legacy_intrinsic_parents} legacy intrinsic vectors"
    )

    # Create embeddings
    embeddings = create_embeddings(contents, model)

    if not args.skip_embeddings_text:
        print("Saving embeddings to file")
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"embeddings_{timestamp}.txt"
        np.savetxt(filename, embeddings)

    # Create USearch index
    print("Creating USearch index")
    index, metadata = create_usearch_index(embeddings, metadata)

    # Save the USearch index
    index_filename = os.getenv("USEARCH_INDEX_FILENAME", "usearch_index.bin")
    print(f"Saving USearch index to {index_filename}")
    index.save(index_filename)

    # Save metadata
    metadata_filename = os.getenv("METADATA_FILENAME", "metadata.json")
    print(f"Saving metadata to {metadata_filename}")
    with open(metadata_filename, "w") as f:
        json.dump(metadata, f, indent=2)

    manifest_filename = os.getenv(
        "VECTORSTORE_BUILD_MANIFEST_FILENAME",
        "vectorstore-build-manifest.json",
    )
    manifest = {
        "model_max_seq_length": int(model.max_seq_length),
        "dimensions": int(embeddings.shape[1]),
        "source_parent_records": len(yaml_contents),
        "vector_records": len(metadata),
        "split_parents": split_parents,
        "legacy_intrinsic_parents": legacy_intrinsic_parents,
        "embedding_window_policy": "lossless_windows",
        "embedding_window_overlap_tokens": args.window_overlap_tokens,
    }
    with open(manifest_filename, "w") as f:
        json.dump(manifest, f, indent=2)

    print("USearch index and metadata have been created and saved.")
    print(f"Total documents processed: {len(contents)}")
    print(f"USearch index saved to: {os.path.abspath(index_filename)}")
    print(f"Metadata saved to: {os.path.abspath(metadata_filename)}")
    print(f"Build manifest saved to: {os.path.abspath(manifest_filename)}")


if __name__ == "__main__":
    main()
