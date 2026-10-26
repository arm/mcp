"""Offline builder integration: immutable source and auditable optional aliases."""

import json
import subprocess
import sys

from arm_kb_search.names import NameIndex


def test_offline_builder_roundtrip_and_explicit_alias_output(tmp_path):
    source = tmp_path / "metadata.json"
    alias_path = tmp_path / "aliases.json"
    artifact = tmp_path / "names.json"
    report = tmp_path / "report.json"
    rows = [
        dict(
            chunk_uuid="one",
            doc_type="ecosystem dashboard",
            heading_path=["Catalog", "Maple Studio Editor (MSE)"],
            title="Maple Studio Editor (MSE)",
            original_text="Editor 💻",
            search_text="Maple Studio Editor (MSE) Editor 💻",
        )
    ]
    alias_path.write_text(json.dumps([dict(canonical="Maple Studio Editor",
        labels=["Maple Studio Editor (MSE)"], aliases=["MSE"], provenance="test catalog label")]))
    source.write_text(json.dumps(rows))
    before = source.read_bytes()
    command = [
        sys.executable,
        "-m",
        "arm_kb_search.build_names",
        "--metadata",
        str(source),
        "--output",
        str(artifact),
        "--aliases",
        str(alias_path),
        "--report",
        str(report),
    ]
    result = subprocess.run(command, text=True, capture_output=True)
    assert result.returncode == 0, result.stderr
    assert source.read_bytes() == before
    index = NameIndex.load_precomputed(rows, artifact)
    assert index.candidates("mse") == [0]
    assert index.candidates("maple_studio-editor") == [0]
    assert len(json.loads(report.read_text())["coverage"]["aliases"]["accepted"]) == 1


def test_offline_builder_refuses_overwriting_source(tmp_path):
    source = tmp_path / "metadata.json"
    source.write_text("[]")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "arm_kb_search.build_names",
            "--metadata",
            str(source),
            "--output",
            str(source),
        ],
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "distinct" in result.stderr
    assert source.read_text() == "[]"
