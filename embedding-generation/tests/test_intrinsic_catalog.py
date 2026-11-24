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

from document_chunking import prepare_intrinsic_chunk
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
    data, existing = source
    data["intrinsics.json"][0]["return_type"]["value"] = "int"
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
        added = yaml.safe_load(next(p for p in output.glob("chunk_*.yaml") if p.name != "chunk_original.yaml").read_text())
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
    (("Helium",), "arm_mve.h"), (("SME and SME2", "SVE2"), "arm_sve.h"),
    (("SME and SME2", "SVE"), "arm_sve.h"), (("SME and SME2",), "arm_sme.h"),
    (("Neon", "SVE"), "arm_neon_sve_bridge.h"), ((), "arm_acle.h"),
])
def test_family_headers_and_required_features(families, header):
    # Interface strings from Arm's svluti4_zt_u8_x4 catalog entry.
    interfaces = [
        "This intrinsic only has <a href='https://arm-software.github.io/acle/main/acle.html#introduction-to-streaming-and-non-streaming-mode'>streaming</a> interface",
        'This intrinsic has "__arm_in("zt0")" <a href=\'https://arm-software.github.io/acle/main/acle.html#state-management\'>shared state</a> interface',
    ] if "SME and SME2" in families else []
    row = entry(families=families, interfaces=interfaces,
                required_streaming_features={"features": "FEAT_SME"})
    chunk = build_intrinsic_chunk(row, {})
    assert f"Header declarations: `#include <{header}>`.\n" in chunk["content"]
    assert "FEAT_SME" in chunk["content"]
    assert ("This intrinsic only has streaming interface" in chunk["content"]) == bool(interfaces)
    assert ('This intrinsic has "__arm_in("zt0")" shared state interface' in chunk["content"]) == bool(interfaces)
    assert "<a " not in chunk["content"]
    assert "Signature: void example ();" in chunk["embedding_text"]


def test_overloads_keep_identity_and_context_across_refreshes(tmp_path, source):
    from arm_kb_search.context import DocumentContextIndex

    data, existing = source
    data["intrinsics.json"] = [entry("old"), entry("old", return_type={"value": "float32x4_t"},
                                                arguments=["float32x4_t t"])]
    first, second, third = (tmp_path / name for name in ("first", "second", "third"))
    report = refresh_catalog(existing, first, tokenizer)
    assert report["records"] == 2 and report["added"] == 1
    rows = [yaml.safe_load(p.read_text()) for p in sorted(first.glob("*.yaml"))]
    assert len({r["uuid"] for r in rows}) == 2
    assert len({r["url"] for r in rows}) == 1
    assert yaml.safe_load((first / "chunk_original.yaml").read_text())["uuid"] == "existing-id"
    assert {r["document_context"]["chunk_index"] for r in rows} == {0, 1}
    assert all(r["document_context"]["chunk_count"] == 2 for r in rows)
    assert all(prepare_intrinsic_chunk(r) == r for r in rows)
    context = DocumentContextIndex(rows, Mock())
    assert len(context.expand([{"metadata": rows[0]}], "page")) == 2

    data["intrinsics.json"].reverse()
    refresh_catalog(existing, second, tokenizer)
    assert {p.name: p.read_bytes() for p in first.glob("*.yaml")} == {
        p.name: p.read_bytes() for p in second.glob("*.yaml")}
    report = refresh_catalog(first, third, tokenizer)
    assert report["added"] == report["updated"] == 0
    assert all((third / p.name).read_bytes() == p.read_bytes() for p in first.glob("*.yaml"))
    data["intrinsics.json"].pop()
    with pytest.raises(ValueError, match="missing.*existing"):
        refresh_catalog(first, tmp_path / "missing", tokenizer)
    assert not (tmp_path / "missing").exists()


def test_operation_text_keeps_word_boundaries():
    chunk = build_intrinsic_chunk(entry(Operation="op"), {
        "op": "<h3>Operation</h3><p>Return op1.</p><h3>Exceptions</h3><p>Active flags.</p><pre>x = 1;\ny = 2;</pre>"})
    assert "Return op1. Exceptions Active flags." in chunk["content"]
    assert "`x = 1;\ny = 2;`" in chunk["content"]


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
    fingerprint = next(s for s in steps if "build-input-fingerprint.py toolchain" in s.get("run", ""))
    buildx = next(s for s in steps if s.get("uses", "").startswith("docker/setup-buildx-action@"))
    assert steps.index(buildx) < steps.index(fingerprint) < steps.index(build)
    assert "if" not in fingerprint and fingerprint.get("continue-on-error", "false") == "false"
    assert fingerprint["env"]["GENERATOR_IMAGE"] == "${{ steps.inputs.outputs.generator_image }}"
    assert '--image "$GENERATOR_IMAGE"' in fingerprint["run"]
    attest = next(s for s in steps if s.get("uses", "").startswith("actions/attest@"))
    assert attest["with"]["subject-digest"] == "${{ steps.snapshot.outputs.digest }}"
