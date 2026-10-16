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

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call

import numpy as np
import pytest
import torch
from arm_kb_search import resources
from transformers import AutoTokenizer

import local_vectorstore_creation as vectorstore
from local_vectorstore_creation import load_local_yaml_files


def test_load_local_yaml_files_requires_intrinsic_chunks(tmp_path, monkeypatch):
    intrinsic_dir = tmp_path / "intrinsic_chunks"
    intrinsic_dir.mkdir()
    monkeypatch.setenv("INTRINSIC_CHUNKS_DIR", str(intrinsic_dir))
    monkeypatch.setenv("YAML_DATA_DIR", str(tmp_path / "yaml_data"))

    with pytest.raises(FileNotFoundError, match="No intrinsic chunk YAML files found"):
        load_local_yaml_files()


def test_vectorstore_serialization_preserves_dashboard_scope(tmp_path, monkeypatch):
    records = [
        dict(
            uuid="a",
            chunk_uuid="a",
            url="https://example.com/linux",
            title="Package",
            keywords="package",
            content="Useful software",
            doc_type="Ecosystem Dashboard",
            product="",
            version="",
            platform="linux",
            edition="open-source",
        ),
        dict(
            uuid="b",
            chunk_uuid="b",
            url="https://example.com/guide",
            title="Guide",
            keywords="guide",
            content="Existing document",
        ),
    ]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        sys, "argv", ["local_vectorstore_creation.py", "--model-path", "unused"]
    )
    monkeypatch.setattr(vectorstore, "load_local_yaml_files", lambda: records)
    monkeypatch.setattr(
        vectorstore, "create_embeddings", lambda metadata, *args: (np.eye(2, dtype=np.float32), metadata)
    )
    vectorstore.main()
    metadata = json.loads((tmp_path / "metadata.json").read_text())
    assert (
        metadata[0]["platform"] == "linux" and metadata[0]["edition"] == "open-source"
    )
    assert metadata[0]["product"] == metadata[0]["version"] == ""
    assert metadata[1]["platform"] == metadata[1]["edition"] == ""


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("renamed", [False, True])
def test_chunk_order_ignores_file_order_and_generated_ids(tmp_path, monkeypatch, reverse, renamed):
    monkeypatch.chdir(tmp_path)
    for env, directory in [("INTRINSIC_CHUNKS_DIR", "intrinsic_chunks"), ("YAML_DATA_DIR", "yaml_data")]:
        monkeypatch.setenv(env, directory)
        (tmp_path / directory).mkdir()
    for position, content in enumerate(["intrinsic", "beta", "alpha"]):
        directory = "intrinsic_chunks" if position == 0 else "yaml_data"
        identifier = f"new-{9 - position}" if renamed else f"old-{position}"
        chunk = {"uuid": identifier, "url": "https://example.com", "content": content}
        (tmp_path / directory / f"chunk_{identifier}.yaml").write_text(json.dumps(chunk))
    original_glob = vectorstore.glob.glob
    monkeypatch.setattr(
        vectorstore.glob, "glob",
        lambda pattern: sorted(original_glob(pattern), reverse=reverse),
    )
    assert [chunk["content"] for chunk in load_local_yaml_files()] == ["intrinsic", "alpha", "beta"]


@pytest.fixture(scope="module")
def tokenizer():
    path = os.getenv("MINILM_MODEL_PATH", str(Path(__file__).parents[1] / ".cache/embedding-model"))
    if not Path(path).is_dir():
        pytest.skip("Acquire the locked MiniLM model or set MINILM_MODEL_PATH for tokenizer checks")
    return AutoTokenizer.from_pretrained(path, local_files_only=True, use_fast=True)


def record(text, identifier="doc"):
    return dict(
        uuid=identifier, chunk_uuid=identifier, original_text=text,
        search_text="Metadata title keywords " + text,
        url="https://example.com/guide?version=2#section",
        resolved_url="https://example.com/source#original", title="Original title",
        heading_path=["Chapter", "Section"], keywords="Arm", custom={"keep": True},
    )


@pytest.mark.parametrize("text", ["", " \t\n", "word " * 498])
def test_fitting_input_is_unchanged(tokenizer, text):
    row = record(text)
    assert vectorstore.token_count(tokenizer, text) <= 500
    assert vectorstore.split_embedding_inputs([row], tokenizer) == [row]


@pytest.mark.parametrize("identifier", ["yaml_data_doc", "intrinsic_vadd"])
@pytest.mark.parametrize("text", [
    "word " * 499,
    "Document Title: Code\n\n" + "\tint café = foo(a, b);  // 雪\r\n" * 400 + "  \n",
    "a;" * 1500,
])
def test_cap_preserves_exact_text_metadata_and_piece_identity(tokenizer, identifier, text):
    row = record(text, identifier)
    pieces = vectorstore.split_embedding_inputs([row], tokenizer)
    assert len(pieces) > 1
    assert "".join(piece["original_text"] for piece in pieces) == text
    assert all(vectorstore.token_count(tokenizer, piece["original_text"]) <= 500 for piece in pieces)
    assert len({piece["uuid"] for piece in pieces}) == len(pieces)
    assert len({piece["chunk_uuid"] for piece in pieces}) == len(pieces)
    cursor = 0
    for number, piece in enumerate(pieces, 1):
        assert piece["source_start"] == cursor
        cursor = piece["source_end"]
        assert piece["original_text"] == text[piece["source_start"]:cursor]
        assert piece["parent_uuid"] == piece["parent_chunk_uuid"] == identifier
        assert piece["uuid"] != identifier and piece["chunk_uuid"] != identifier
        assert (piece["source_part"], piece["source_parts"]) == (number, len(pieces))
        assert piece["search_text"] == "Metadata title keywords " + piece["original_text"]
        for key in ("url", "resolved_url", "title", "heading_path", "keywords", "custom"):
            assert piece[key] == row[key]
    assert cursor == len(text)
    assert vectorstore.split_embedding_inputs([row], tokenizer) == pieces


def test_bad_search_text_is_rejected(tokenizer):
    row = record("word " * 499)
    row["search_text"] = "missing body"
    with pytest.raises(ValueError, match="search_text"):
        vectorstore.split_embedding_inputs([row], tokenizer)


def test_consecutive_calls_and_index_metadata_alignment(tokenizer, monkeypatch):
    rows = [record(f"Record {i} " + "word " * (499 if i == 2 else 1), str(i)) for i in range(64)]
    expected = vectorstore.split_embedding_inputs(rows, tokenizer)
    texts = [row["original_text"] for row in expected]
    # Each vector identifies its input position, including through the real USearch store.
    expected_vectors = np.repeat(np.arange(len(expected), dtype=np.float32)[:, None], 384, axis=1)
    model = Mock(tokenizer=tokenizer)
    model.float.return_value = model.eval.return_value = model
    model.encode.side_effect = [expected_vectors[i:i + 32] for i in range(0, len(expected), 32)]
    load = Mock(return_value=model)
    monkeypatch.setattr(vectorstore, "SentenceTransformer", load)
    monkeypatch.setattr(vectorstore.torch, "set_num_interop_threads", lambda _: None)

    vectors, metadata = vectorstore.create_embeddings(rows, "unused")

    load.assert_called_once_with("unused", device="cpu", local_files_only=True, trust_remote_code=False)
    assert model.max_seq_length == 512
    assert len(expected) == 65  # Calls contain 32, 32, then 1 input.
    assert model.encode.call_args_list == [
        call(texts[i:i + 32], batch_size=32, show_progress_bar=False, convert_to_numpy=True,
             precision="float32", normalize_embeddings=True)
        for i in range(0, len(texts), 32)
    ]
    assert metadata == expected
    index, metadata = vectorstore.create_usearch_index(vectors, metadata)
    for position, row in enumerate(metadata):
        assert row == expected[position]
        np.testing.assert_array_equal(index.get(position), expected_vectors[position])
    with pytest.raises(ValueError, match="counts differ"):
        vectorstore.create_usearch_index(vectors[:-1], metadata)


@pytest.mark.parametrize("cache_miss", [False, True])
def test_query_loader_sets_512_on_local_and_download_paths(monkeypatch, cache_miss):
    model = SimpleNamespace(max_seq_length=256)
    load = Mock(side_effect=[OSError("cache miss"), model] if cache_miss else [model])
    monkeypatch.setattr(resources, "SentenceTransformer", load)
    assert resources.load_embedding_model("all-MiniLM-L6-v2") is model
    assert model.max_seq_length == 512
    assert load.call_args.kwargs["local_files_only"] is not cache_miss


def test_real_query_window_and_builtin_normalization(tokenizer):
    torch.set_num_threads(2)
    model = resources.load_embedding_model(tokenizer.name_or_path, allow_download=False).to("cpu")
    assert model.max_seq_length == 512
    assert model.tokenize(["hello " * 510])["input_ids"].shape[1] == 512
    assert model.get_embedding_dimension() == 384
    assert type(model[-1]).__name__ == "Normalize"
    vectors = model.encode(["Arm intrinsics", "hello " * 510], convert_to_numpy=True)
    np.testing.assert_allclose(np.linalg.norm(vectors, axis=1), 1, atol=1e-6)
