# Copyright © 2026, Arm Limited and Contributors. All rights reserved.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy at http://www.apache.org/licenses/LICENSE-2.0
# Unless required by applicable law or agreed to in writing, software distributed
# under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
# CONDITIONS OF ANY KIND, either express or implied. See the License for the
# specific language governing permissions and limitations under the License.

import json
from unittest.mock import Mock

import pytest
import yaml

from intrinsic_catalog import build_intrinsic_chunk, refresh_catalog


def entry(name="example", families=("Neon",), **extra):
    return {"name": name, "return_type": {"value": "void"}, "arguments": [],
            "description": "Example operation.", "instruction_group": "Example",
            "Architectures": ["A64"], "SIMD_ISA": list(families), **extra}


@pytest.fixture
def source(tmp_path, monkeypatch):
    existing = tmp_path / "existing"
    existing.mkdir()
    row = build_intrinsic_chunk(entry("old"), {})
    row["uuid"] = "existing-id"
    (existing / "chunk_original.yaml").write_text(yaml.safe_dump(row))
    data = {
        "intrinsics.json": [entry("old", ("SME and SME2", "SVE2"), description="Updated operation."),
                            entry("added", Operation="operation")],
        "operations.json": [{"item": {"id": "operation", "content": "<h3>Operation</h3><pre>return;</pre>"}}],
    }
    monkeypatch.setattr("intrinsic_catalog.requests.get", lambda url, **kwargs:
                        Mock(content=json.dumps(data[url.rsplit("/", 1)[1]]).encode()))
    return data, existing


def tokenizer(text, **kwargs):
    return {"input_ids": text.split()}


def test_refresh_updates_old_records_and_preserves_identity(tmp_path, source):
    _, existing = source
    original = (existing / "chunk_original.yaml").read_bytes()
    outputs = [tmp_path / "first", tmp_path / "second"]
    for output in outputs:
        report = refresh_catalog(existing, output, tokenizer)
        assert report["records"] == 2 and report["added"] == report["updated"] == 1
        old = yaml.safe_load((output / "chunk_original.yaml").read_text())
        assert old["uuid"] == "existing-id"
        assert old["url"] == yaml.safe_load(original)["url"]
        assert old["product"] == "SME and SME2 / SVE2"
        assert "Updated operation." in old["embedding_text"]
        added = yaml.safe_load(next(output.glob("catalog_*.yaml")).read_text())
        assert "return;" in added["content"]
        manifest = json.loads((output / "catalog-manifest.json").read_text())
        assert len(manifest["source_sha256"]["intrinsics.json"]) == 64
    assert (existing / "chunk_original.yaml").read_bytes() == original
    assert {p.name: p.read_bytes() for p in outputs[0].iterdir()} == {
        p.name: p.read_bytes() for p in outputs[1].iterdir()}

    third = tmp_path / "third"
    report = refresh_catalog(outputs[0], third, tokenizer)
    assert report["added"] == report["updated"] == 0
    assert all((third / p.name).read_bytes() == p.read_bytes() for p in outputs[0].glob("*.yaml"))


@pytest.mark.parametrize("families,header", [
    (("Helium",), "arm_mve.h"), (("SME and SME2", "SVE2"), "arm_sme.h"),
    (("Neon", "SVE"), "arm_neon_sve_bridge.h"), ((), "arm_acle.h"),
])
def test_family_headers_and_required_features(families, header):
    row = entry(families=families, sme_modes=["__arm_streaming"],
                required_streaming_features={"features": "FEAT_SME"})
    chunk = build_intrinsic_chunk(row, {})
    assert header in chunk["content"]
    assert "__arm_streaming" in chunk["content"] and "FEAT_SME" in chunk["content"]
    assert "Signature: void example ();" in chunk["embedding_text"]


@pytest.mark.parametrize("failure", ["empty", "duplicate", "missing-old", "operation", "long", "http", "schema"])
def test_bad_refresh_does_not_write_a_snapshot(tmp_path, monkeypatch, source, failure):
    data, existing = source
    before = (existing / "chunk_original.yaml").read_bytes()
    catalog = data["intrinsics.json"]
    if failure == "empty":
        catalog = []
    elif failure == "duplicate":
        catalog.append(catalog[0])
    elif failure == "missing-old":
        catalog = catalog[1:]
    elif failure == "schema":
        del catalog[0]["arguments"]
    if failure == "operation":
        data["operations.json"] = []
    data["intrinsics.json"] = catalog
    if failure == "http":
        monkeypatch.setattr("intrinsic_catalog.requests.get", Mock(side_effect=RuntimeError("download failed")))
    count = (lambda *args, **kwargs: {"input_ids": [0] * 501}) if failure == "long" else tokenizer
    output = tmp_path / "output"
    with pytest.raises((ValueError, RuntimeError)):
        refresh_catalog(existing, output, count)
    assert not output.exists()
    assert (existing / "chunk_original.yaml").read_bytes() == before


def test_workflow_only_publishes_manual_main_runs():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    workflow = yaml.load((root / ".github/workflows/refresh-intrinsics.yml").read_text(), Loader=yaml.BaseLoader)
    assert set(workflow["on"]) == {"workflow_dispatch"}
    assert workflow["on"]["workflow_dispatch"]["inputs"]["dry_run"]["default"] == "true"
    guard = workflow["env"]["PUBLISH_IMAGE"]
    assert "github.repository == 'arm/mcp'" in guard
    assert "github.ref == 'refs/heads/main'" in guard and "!inputs.dry_run" in guard
    steps = workflow["jobs"]["refresh"]["steps"]
    build = next(s for s in steps if s.get("uses", "").startswith("docker/build-push-action@"))
    assert build["with"]["no-cache"] == "true"
    assert build["with"]["push"] == "${{ env.PUBLISH_IMAGE == 'true' }}"
    assert build["with"]["outputs"] == "type=local,dest=${{ runner.temp }}/intrinsic-snapshot"
    attest = next(s for s in steps if s.get("uses", "").startswith("actions/attest@"))
    assert attest["with"]["subject-digest"] == "${{ steps.snapshot.outputs.digest }}"
