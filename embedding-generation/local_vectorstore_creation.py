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
import uuid

import numpy as np
import torch
import yaml
from sentence_transformers import SentenceTransformer
from usearch.index import Index


def load_local_yaml_files() -> list[dict]:
    """Load locally stored YAML files and return their contents as a list of dictionaries."""
    print("Loading local YAML files")
    yaml_contents = []
    intrinsic_dir = os.getenv("INTRINSIC_CHUNKS_DIR", "intrinsic_chunks")
    yaml_dir = os.getenv("YAML_DATA_DIR", "yaml_data")

    intrinsic_files = glob.glob(os.path.join(intrinsic_dir, "*.yaml"))
    print(f"Found {len(intrinsic_files)} YAML files in {intrinsic_dir} directory")
    if not intrinsic_files:
        raise FileNotFoundError(
            f"No intrinsic chunk YAML files found in '{intrinsic_dir}'. "
            "Supply the intrinsic chunks before creating the vector store."
        )

    yaml_data_files = glob.glob(os.path.join(yaml_dir, "*.yaml"))
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

    # Generated IDs change on acquisition; order by stable chunk data instead.
    yaml_contents.sort(
        key=lambda chunk: (
            0 if chunk["chunk_uuid"].startswith("intrinsic_") else 1,
            chunk.get("url", ""),
            json.dumps(
                {
                    key: value
                    for key, value in chunk.items()
                    if key not in {"uuid", "chunk_uuid"}
                },
                sort_keys=True,
            ),
        )
    )

    print(f"Successfully loaded {len(yaml_contents)} YAML files")
    return yaml_contents


EMBEDDING_TOKEN_CAP = 500
PIECE_NAMESPACE = uuid.UUID("4729167e-eac3-5d52-af2b-f7f366cffb29")


def token_count(tokenizer, text: str) -> int:
    """Count the complete embedding input, including specials, without truncation."""
    return len(tokenizer(text, add_special_tokens=True, truncation=False)["input_ids"])


def choose_end(text: str, start: int, tokenizer) -> int:
    """Reuse the experiment's tokenizer-offset and whitespace boundary selection."""
    encoded = tokenizer(
        text[start:], add_special_tokens=True, max_length=EMBEDDING_TOKEN_CAP,
        truncation=True, return_offsets_mapping=True,
    )
    ends = [end for begin, end in encoded["offset_mapping"] if end > 0]
    if not ends:
        raise ValueError(f"Tokenizer made no progress at character {start}")
    proposed = min(len(text), start + max(ends))
    floor = start + max(1, int((proposed - start) * 0.8))
    end = next(
        (i + 1 for i in range(proposed - 1, floor - 1, -1) if text[i].isspace()),
        proposed,
    )
    while end > start and token_count(tokenizer, text[start:end]) > EMBEDDING_TOKEN_CAP:
        prior = next((i + 1 for i in range(end - 2, start - 1, -1) if text[i].isspace()), None)
        end = prior if prior and prior > start else end - 1
    if end <= start:
        raise ValueError(f"No tokenizer-safe slice begins at character {start}")
    return end


def split_embedding_inputs(metadata: list[dict], tokenizer) -> list[dict]:
    """Return lossless consecutive pieces; leave fitting records unchanged."""
    output = []
    for row in metadata:
        text = row["original_text"]
        if token_count(tokenizer, text) <= EMBEDDING_TOKEN_CAP:
            output.append(row)
            continue
        if not row["search_text"].endswith(text):
            raise ValueError("search_text must end with the complete embedding input")
        intervals = []
        start = 0
        while start < len(text):
            end = (len(text) if token_count(tokenizer, text[start:]) <= EMBEDDING_TOKEN_CAP
                   else choose_end(text, start, tokenizer))
            intervals.append((start, end))
            start = end
        for part, (start, end) in enumerate(intervals, 1):
            identity = f"{row['uuid']}:{row['chunk_uuid']}:{start}:{end}"
            child = dict(row)
            child.update(
                uuid=str(uuid.uuid5(PIECE_NAMESPACE, identity)),
                chunk_uuid="cap500_nooverlap_" + str(uuid.uuid5(PIECE_NAMESPACE, "chunk:" + identity)),
                original_text=text[start:end],
                search_text=row["search_text"][:-len(text)] + text[start:end],
                parent_uuid=row["uuid"], parent_chunk_uuid=row["chunk_uuid"],
                source_start=start, source_end=end, source_part=part, source_parts=len(intervals),
            )
            output.append(child)
    return output


def create_embeddings(
    metadata: list[dict], model_path: str, device: str = "cpu",
) -> tuple[np.ndarray, list[dict]]:
    """Build fresh capped vectors in metadata order, one encode call per 32 inputs."""
    torch.manual_seed(0)
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    model = SentenceTransformer(
        model_path, device=device, local_files_only=True, trust_remote_code=False,
    ).float().eval()
    model.max_seq_length = 512
    metadata = split_embedding_inputs(metadata, model.tokenizer)
    embeddings = np.empty((len(metadata), 384), dtype=np.float32)
    for start in range(0, len(metadata), 32):
        texts = [row["original_text"] for row in metadata[start:start + 32]]
        if any(token_count(model.tokenizer, text) > EMBEDDING_TOKEN_CAP for text in texts):
            raise ValueError("Embedding input exceeds 500 tokens including special tokens")
        embeddings[start:start + len(texts)] = model.encode(
            texts, batch_size=32, show_progress_bar=False, convert_to_numpy=True,
            precision="float32", normalize_embeddings=True,
        )
        print(f"Embedded {start + len(texts)}/{len(metadata)} pieces", flush=True)
    return embeddings, metadata


def create_usearch_index(
    embeddings: np.ndarray, metadata: list[dict]
) -> tuple[Index, list[dict]]:
    """Create a USearch index with the given embeddings and metadata."""
    print("Creating USearch index")
    print(f"Embeddings shape: {embeddings.shape}")

    dimension = embeddings.shape[1]
    num_vectors = embeddings.shape[0]

    if num_vectors != len(metadata):
        raise ValueError("Embedding and metadata counts differ")

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
    parser.add_argument("--device", choices=("cpu", "mps", "cuda"), default="cpu",
                        help="Document encoding device; record this when comparing builds.")
    return parser.parse_args()


def main():
    args = parse_args()
    print("Starting the USearch datastore creation process")

    # Load local YAML files
    yaml_contents = load_local_yaml_files()

    # Extract content, uuid, url, and original text from YAML files
    print("Extracting content and metadata from YAML files")
    metadata = []
    for i, yaml_content in enumerate(yaml_contents, 1):
        if i <= 10 or i % 1000 == 0 or i == len(yaml_contents):
            print(f"Processing YAML content {i}/{len(yaml_contents)}")
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
                yaml_content.get("content", ""),
            ]
            if value
        )
        metadata.append(
            {
                "uuid": yaml_content["uuid"],
                "url": yaml_content["url"],
                "resolved_url": yaml_content.get("resolved_url", yaml_content["url"]),
                "original_text": yaml_content["content"],
                "title": yaml_content["title"],
                "keywords": yaml_content["keywords"],
                "chunk_uuid": yaml_content["chunk_uuid"],
                "heading": yaml_content.get("heading", ""),
                "heading_path": heading_path,
                "doc_type": yaml_content.get("doc_type", ""),
                "product": yaml_content.get("product", ""),
                "version": yaml_content.get("version", ""),
                "content_type": yaml_content.get("content_type", ""),
                "platform": yaml_content.get("platform", ""),
                "edition": yaml_content.get("edition", ""),
                "search_text": search_text,
            }
        )

    # Create embeddings
    embeddings, metadata = create_embeddings(metadata, args.model_path, args.device)

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

    print("USearch index and metadata have been created and saved.")
    print(f"Total documents processed: {len(metadata)}")
    print(f"USearch index saved to: {os.path.abspath(index_filename)}")
    print(f"Metadata saved to: {os.path.abspath(metadata_filename)}")


if __name__ == "__main__":
    main()
