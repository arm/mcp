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


@pytest.mark.parametrize(
    "kind,workflow_name",
    [
        ("toolchain", "build-embedding-toolchain.yml"),
        ("mcp-inputs", "build-mcp-inputs.yml"),
    ],
)
def test_build_triggers_match_fingerprint_inputs(kind, workflow_name):
    # BaseLoader preserves GitHub's "on" key instead of treating it as a boolean.
    workflow = yaml.load(
        (ROOT / ".github/workflows" / workflow_name).read_text(), Loader=yaml.BaseLoader
    )
    expected = set(fingerprints.INPUTS[kind]) | {
        ".github/scripts/build-input-fingerprint.py"
    }
    # Promotions update this lock too; OS/migrate-ease changes need a manual build.
    expected.discard("mcp-local/build-inputs.lock.json")
    assert set(workflow["on"]["push"]["paths"]) == expected


def test_mcp_bundle_is_checked_before_expensive_embedding_builds():
    workflow = yaml.safe_load(
        (ROOT / ".github/workflows/build-embeddings.yml").read_text()
    )
    steps = workflow["jobs"]["acquire-and-publish-chunks"]["steps"]
    check_index = next(
        i
        for i, step in enumerate(steps)
        if "build-input-fingerprint.py mcp-inputs" in step.get("run", "")
    )
    assert not steps[check_index].get("continue-on-error", False)
    assert "if" not in steps[check_index]
    assert all(
        check_index < i
        for i, step in enumerate(steps)
        if step.get("uses", "").startswith("docker/build-push-action@")
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


@pytest.mark.parametrize("multi_platform", [False, True])
@pytest.mark.parametrize(
    "platform,label,error",
    [
        ("linux/arm64", "matching", None),
        ("linux/arm64", "stale", "found stale"),
        ("linux/arm64", None, "found missing"),
        ("linux/s390x", "matching", "does not contain platform linux/s390x"),
    ],
)
def test_image_check(monkeypatch, capsys, multi_platform, platform, label, error):
    image = "ghcr.io/arm/mcp-build-inputs@sha256:" + "a" * 64
    expected = fingerprints.fingerprint("mcp-inputs")
    config = {
        "os": "linux",
        "architecture": "arm64",
        "variant": "v8",
        "config": {
            "Labels": {fingerprints.LABEL: expected if label == "matching" else label}
        },
    }
    metadata = config
    if multi_platform:
        metadata = {
            "linux/arm64": config,
            "linux/amd64": {"config": {"Labels": {fingerprints.LABEL: expected}}},
        }
    monkeypatch.setattr(
        sys, "argv", ["fingerprint", "mcp-inputs", "--image", image, "--platform", platform]
    )

    def inspect(command, *, text):
        assert command[:4] == ["docker", "buildx", "imagetools", "inspect"]
        assert command[-1] == image and text
        return json.dumps(metadata)

    monkeypatch.setattr(
        fingerprints.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("unexpected pull"),
    )
    monkeypatch.setattr(fingerprints.subprocess, "check_output", inspect)
    if error is None:
        fingerprints.main()
    else:
        with pytest.raises(SystemExit) as failure:
            fingerprints.main()
        assert failure.value.code == 1
        message = capsys.readouterr().out
        assert error in message
        if label != "matching":
            assert "Check for a pending pin-update PR" in message
            assert "merge its pin-update PR" in message
