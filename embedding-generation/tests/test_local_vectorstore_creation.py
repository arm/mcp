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
import sys

import numpy as np
import pytest

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
        vectorstore, "create_embeddings", lambda *args: np.eye(2, dtype=np.float32)
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
def test_chunk_order_ignores_file_order_and_generated_ids(
    tmp_path, monkeypatch, reverse, renamed
):
    intrinsic_dir = tmp_path / "intrinsic_chunks"
    yaml_dir = tmp_path / "yaml_data"
    intrinsic_dir.mkdir()
    yaml_dir.mkdir()
    monkeypatch.setenv("INTRINSIC_CHUNKS_DIR", str(intrinsic_dir))
    monkeypatch.setenv("YAML_DATA_DIR", str(yaml_dir))
    fixtures = [
        (intrinsic_dir, "https://example.com/z", "intrinsic"),
        (yaml_dir, "https://example.com/a", "alpha"),
        (yaml_dir, "https://example.com/a", "beta"),
        (yaml_dir, "https://example.com/b", "gamma"),
    ]
    for position, (directory, url, content) in enumerate(fixtures):
        identifier = f"new-{9 - position}" if renamed else f"old-{position}"
        chunk = {"uuid": identifier, "url": url, "title": "Reference", "content": content}
        (directory / f"chunk_{identifier}.yaml").write_text(json.dumps(chunk))
    original_glob = vectorstore.glob.glob
    monkeypatch.setattr(
        vectorstore.glob, "glob",
        lambda pattern: sorted(original_glob(pattern), reverse=reverse),
    )
    chunks = load_local_yaml_files()
    assert [chunk["content"] for chunk in chunks] == ["intrinsic", "alpha", "beta", "gamma"]
