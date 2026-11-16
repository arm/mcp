"""Focused checks for pinned build-environment freshness."""

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "build_input_fingerprint", ROOT / ".github/scripts/build-input-fingerprint.py"
)
fingerprints = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fingerprints)


def test_scanned_and_published_bundle_have_identical_labels():
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/build-mcp-inputs.yml").read_text()
    )
    builds = [
        step["with"]
        for step in workflow["jobs"]["acquire-and-publish-architecture"]["steps"]
        if step.get("uses", "").startswith("docker/build-push-action@")
    ]
    assert len(builds) == 2
    assert builds[0]["labels"] == builds[1]["labels"]
    assert (
        f"{fingerprints.LABEL}=${{{{ steps.fingerprint.outputs.value }}}}"
        in builds[0]["labels"].splitlines()
    )


@pytest.mark.parametrize("kind", ["toolchain", "mcp-inputs"])
def test_fingerprint_tracks_inputs_but_ignores_promotions_and_generation_code(
    tmp_path, kind
):
    for name in (
        *fingerprints.INPUTS[kind],
        ".github/scripts/build-input-fingerprint.py",
    ):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    original = fingerprints.fingerprint(kind, tmp_path)
    if kind == "mcp-inputs":
        path = tmp_path / "mcp-local/build-inputs.lock.json"
        lock = json.loads(path.read_text())
        for key in ("embeddings", "mcp_build_inputs"):
            lock["container_images"][key]["reference"] = "new promotion"
        path.write_text(json.dumps(lock))
    else:
        (tmp_path / "embedding-generation/generate-chunks.py").write_text("new code")
    assert fingerprints.fingerprint(kind, tmp_path) == original

    directory = "embedding-generation" if kind == "toolchain" else "mcp-local"
    with (tmp_path / directory / "uv.lock").open("a") as output:
        output.write("\n# dependency update\n")
    assert fingerprints.fingerprint(kind, tmp_path) != original


@pytest.mark.parametrize("actual", ["matching", "stale", None])
def test_image_check_passes_only_with_matching_label(monkeypatch, capsys, actual):
    image = "ghcr.io/arm/mcp-build-inputs@sha256:" + "a" * 64
    expected = fingerprints.fingerprint("mcp-inputs")
    label = expected if actual == "matching" else actual
    monkeypatch.setattr(sys, "argv", ["fingerprint", "mcp-inputs", "--image", image])
    monkeypatch.setattr(fingerprints.subprocess, "run", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        fingerprints.subprocess,
        "check_output",
        lambda *args, **kwargs: json.dumps(
            [{"Config": {"Labels": {fingerprints.LABEL: label}}}]
        ),
    )
    if actual == "matching":
        fingerprints.main()
    else:
        with pytest.raises(SystemExit) as failure:
            fingerprints.main()
        assert failure.value.code == 1
        assert "merge its pin-update PR" in capsys.readouterr().out
