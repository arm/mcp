import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import tomllib


REPOSITORY = Path(__file__).resolve().parents[2]
MCP_LOCAL = REPOSITORY / "mcp-local"
LOCK = json.loads((MCP_LOCAL / "build-inputs.lock.json").read_text())
MODEL_LOCK = json.loads(
    (REPOSITORY / "embedding-generation/embedding-model.lock.json").read_text()
)
DOCKERFILE = (MCP_LOCAL / "Dockerfile").read_text()
INPUT_DOCKERFILE = (MCP_LOCAL / "Dockerfile.inputs").read_text()
STAGE_INPUTS = (MCP_LOCAL / "scripts/stage-build-inputs.py").read_text()
INPUT_DOCKERIGNORE = (MCP_LOCAL / ".dockerignore").read_text()
ROOT_DOCKERIGNORE = (REPOSITORY / ".dockerignore").read_text()
SERVER = (MCP_LOCAL / "server.py").read_text()
INPUT_WORKFLOW = (
    REPOSITORY / ".github/workflows/build-mcp-inputs.yml"
).read_text()
EMBEDDING_WORKFLOW = (
    REPOSITORY / ".github/workflows/build-embeddings.yml"
).read_text()
IMAGE_WORKFLOW = (REPOSITORY / ".github/workflows/build-mcp-image.yml").read_text()
INTEGRATION_WORKFLOW = (
    REPOSITORY / ".github/workflows/integration-tests.yml"
).read_text()


def test_docker_base_images_match_manifest() -> None:
    docker_args = {
        "ubuntu": "UBUNTU_IMAGE",
        "embeddings": "EMBEDDINGS_IMAGE",
        "mcp_build_inputs": "MCP_BUILD_INPUTS_IMAGE",
    }
    for name, image in LOCK["container_images"].items():
        assert f'ARG {docker_args[name]}={image["reference"]}' in DOCKERFILE
        assert "@sha256:" in image["reference"]
    ubuntu_manifests = LOCK["container_images"]["ubuntu"]["manifests"]
    assert set(ubuntu_manifests) == {"amd64", "arm64"}
    assert all("@sha256:" in reference for reference in ubuntu_manifests.values())


def test_all_architecture_specific_inputs_cover_release_architectures() -> None:
    expected = {"amd64", "arm64"}
    build_inputs = LOCK["container_images"]["mcp_build_inputs"]
    assert set(build_inputs["architectures"]) == expected
    assert set(build_inputs["manifests"]) == expected
    assert set(LOCK["python"]["architectures"]) == expected
    assert set(LOCK["performix"]["artifacts"]) == expected
    assert set(LOCK["migrate_ease"]["architectures"]) == expected
    assert set(LOCK["os_packages"]["bundles"]) == expected


def test_native_tool_packages_are_explicitly_requested() -> None:
    runtime = set(LOCK["os_packages"]["roles"]["runtime"])
    assert {"git", "libmagic1", "llvm-18", "python3", "skopeo"} <= runtime
    assert re.fullmatch(r"[0-9]{8}T[0-9]{6}Z", LOCK["os_packages"]["snapshot"])


def test_os_package_bundles_are_hash_locked() -> None:
    for architecture in ("amd64", "arm64"):
        for role in ("builder", "runtime"):
            artifacts = LOCK["os_packages"]["bundles"][architecture][role][
                "artifacts"
            ]
            assert artifacts
            assert all(filename.endswith(".deb") for filename in artifacts)
            assert all(
                re.fullmatch(r"[0-9a-f]{64}", digest)
                for digest in artifacts.values()
            )


def test_external_inputs_are_immutable_and_have_digests() -> None:
    migration = LOCK["migrate_ease"]
    assert migration["repository"] == "https://github.com/migrate-ease/migrate-ease"
    assert migration["revision"] in migration["url"]
    assert re.fullmatch(r"[0-9a-f]{40}", migration["revision"])
    assert re.fullmatch(r"[0-9a-f]{64}", migration["sha256"])
    assert migration["verification"].startswith("locally calculated SHA256")

    for artifact in LOCK["performix"]["artifacts"].values():
        assert re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"])
    assert LOCK["performix"]["verification"].startswith(
        "locally calculated SHA256"
    )


def test_python_dependencies_have_one_exactly_pinned_source() -> None:
    pyproject = tomllib.loads((MCP_LOCAL / "pyproject.toml").read_text())
    dependencies = pyproject["project"]["dependencies"]
    assert dependencies
    assert all(
        re.fullmatch(r"[A-Za-z0-9_.-]+==[^=]+", dependency)
        for dependency in dependencies
    )
    assert pyproject["dependency-groups"]["acquisition"] == ["pip==25.1.1"]
    assert not (MCP_LOCAL / "requirements.txt").exists()
    assert not (MCP_LOCAL / "requirements.lock").exists()


def test_dockerfile_consumes_only_staged_third_party_inputs() -> None:
    assert "arm-linux-migration-tools/main/scripts/install.sh" not in DOCKERFILE
    assert "curl " not in DOCKERFILE
    assert "https://" not in DOCKERFILE
    assert "--network=none pip install" in DOCKERFILE
    assert "apt-get update" not in DOCKERFILE
    assert "--network=none apt-get install" in DOCKERFILE
    assert "--no-download" in DOCKERFILE
    assert "FROM ${MCP_BUILD_INPUTS_IMAGE} AS mcp-inputs" in DOCKERFILE
    assert "--from=mcp-inputs /mcp-build-inputs/wheels/" in DOCKERFILE
    assert "--from=mcp-inputs /mcp-build-inputs/debs/builder/" in DOCKERFILE
    assert "--from=mcp-inputs /mcp-build-inputs/debs/runtime/" in DOCKERFILE
    assert "--from=mcp-inputs /mcp-build-inputs/performix.tar.gz" in DOCKERFILE
    assert "--from=mcp-inputs /mcp-build-inputs/migrate-ease.tar.gz" in DOCKERFILE
    assert "mcp-local/build-inputs/" not in DOCKERFILE
    assert "!mcp-local/build-inputs/" not in ROOT_DOCKERIGNORE
    assert "--from=embeddings /embedding-data/embedding-model/" in DOCKERFILE


def test_final_builds_do_not_acquire_inputs_live() -> None:
    for workflow in (IMAGE_WORKFLOW, INTEGRATION_WORKFLOW):
        assert "stage-build-inputs.py" not in workflow
        assert "packages: read" in workflow
        assert "Log in to GHCR for locked build inputs" in workflow
    assert "python -m pip install --upgrade pip" not in INTEGRATION_WORKFLOW


def test_release_build_loads_image_arguments_from_manifest() -> None:
    assert 'lock_file="mcp-local/build-inputs.lock.json"' in IMAGE_WORKFLOW
    assert "@sha256:[0-9a-f]{64}" in IMAGE_WORKFLOW
    assert (
        "UBUNTU_IMAGE=${{ steps.locked_images.outputs.ubuntu_image }}"
        in IMAGE_WORKFLOW
    )
    assert (
        "EMBEDDINGS_IMAGE=${{ steps.locked_images.outputs.embeddings_image }}"
        in IMAGE_WORKFLOW
    )
    assert (
        "MCP_BUILD_INPUTS_IMAGE=${{ steps.locked_images.outputs.mcp_build_inputs_image }}"
        in IMAGE_WORKFLOW
    )


def test_model_index_and_metadata_come_from_one_immutable_image() -> None:
    embeddings = LOCK["container_images"]["embeddings"]
    assert embeddings["reference"].startswith(
        "ghcr.io/arm/mcp-embedding-vectorstore@sha256:"
    )
    assert set(embeddings["contents"]) == {
        "/embedding-data/embedding-model/",
        "/embedding-data/metadata.json",
        "/embedding-data/usearch_index.bin",
    }
    assert embeddings["model"] == MODEL_LOCK


def test_embedding_candidate_requires_reviewed_promotion_before_release() -> None:
    image_triggers = IMAGE_WORKFLOW.split("jobs:", maxsplit=1)[0]
    assert "workflow_run:" not in image_triggers
    assert "pull_request:" in image_triggers
    assert "types: [closed]" in image_triggers
    assert "automation/pin-embedding-vectorstore" in IMAGE_WORKFLOW
    assert "propose-mcp-embedding-pin:" in EMBEDDING_WORKFLOW
    assert "update-mcp-embedding-pin.py" in EMBEDDING_WORKFLOW
    assert "gh pr merge" not in EMBEDDING_WORKFLOW


def test_embedding_pin_updater_keeps_manifest_and_dockerfile_in_sync() -> None:
    script = REPOSITORY / ".github/scripts/update-mcp-embedding-pin.py"
    new_digest = "1" * 64
    new_revision = "2" * 40
    new_reference = (
        "ghcr.io/arm/mcp-embedding-vectorstore@sha256:" + new_digest
    )

    with tempfile.TemporaryDirectory() as temporary_directory:
        temporary = Path(temporary_directory)
        lock_file = temporary / "build-inputs.lock.json"
        dockerfile = temporary / "Dockerfile"
        lock_file.write_text(
            (MCP_LOCAL / "build-inputs.lock.json").read_text(), encoding="utf-8"
        )
        dockerfile.write_text(
            (MCP_LOCAL / "Dockerfile").read_text(), encoding="utf-8"
        )
        subprocess.run(
            [
                sys.executable,
                str(script),
                "--reference",
                new_reference,
                "--source-revision",
                new_revision,
                "--workflow-run",
                "123456",
                "--lock-file",
                str(lock_file),
                "--dockerfile",
                str(dockerfile),
            ],
            check=True,
        )

        updated = json.loads(lock_file.read_text())
        embeddings = updated["container_images"]["embeddings"]
        assert embeddings["reference"] == new_reference
        assert embeddings["source_revision"] == new_revision
        assert embeddings["workflow_run"] == "123456"
        assert f"ARG EMBEDDINGS_IMAGE={new_reference}" in dockerfile.read_text()


def test_build_input_bundle_is_immutable_and_auditable() -> None:
    build_inputs = LOCK["container_images"]["mcp_build_inputs"]
    assert build_inputs["reference"].startswith(
        "ghcr.io/arm/mcp-build-inputs@sha256:"
    )
    assert build_inputs["reference"] in DOCKERFILE
    assert re.fullmatch(r"[0-9a-f]{40}", build_inputs["source_revision"])
    assert build_inputs["workflow_run"].isdigit()
    assert all(
        reference.startswith("ghcr.io/arm/mcp-build-inputs@sha256:")
        for reference in build_inputs["manifests"].values()
    )


def test_mcp_runtime_treats_packaged_model_as_local_only() -> None:
    assert "SENTENCE_TRANSFORMER_MODEL_PATH=/app/embedding-model" in DOCKERFILE
    assert "model_path=MODEL_PATH" in SERVER


def test_input_artifact_has_one_platform_neutral_layout() -> None:
    assert "FROM scratch AS inputs" in INPUT_DOCKERFILE
    assert "ARG TARGETARCH" in INPUT_DOCKERFILE
    assert "build-inputs/${TARGETARCH}/wheels/" in INPUT_DOCKERFILE
    assert "build-inputs/${TARGETARCH}/debs/" in INPUT_DOCKERFILE
    assert "build-inputs/${TARGETARCH}/performix.tar.gz" in INPUT_DOCKERFILE
    assert "build-inputs/migrate-ease.tar.gz" in INPUT_DOCKERFILE
    assert "build-inputs/requirements.lock" in INPUT_DOCKERFILE
    assert "/mcp-build-inputs/metadata/" in INPUT_DOCKERFILE
    for source in (
        "build-inputs/**",
        "build-inputs.lock.json",
        "pyproject.toml",
        "uv.lock",
    ):
        assert f"!{source}" in INPUT_DOCKERIGNORE


def test_input_publication_is_manual_private_and_multi_architecture() -> None:
    assert "workflow_dispatch:" in INPUT_WORKFLOW
    workflow_triggers = INPUT_WORKFLOW.split("jobs:", maxsplit=1)[0]
    assert "permissions: read-all" in workflow_triggers
    assert "push:" not in workflow_triggers
    assert "tags:" not in workflow_triggers
    assert "packages: write" in INPUT_WORKFLOW
    assert "verify-ghcr-package-private.sh" in INPUT_WORKFLOW
    assert "ubuntu-24.04-arm" in INPUT_WORKFLOW
    assert "linux/amd64" in INPUT_WORKFLOW
    assert "linux/arm64" in INPUT_WORKFLOW
    assert "docker buildx imagetools create" in INPUT_WORKFLOW
    assert "stage-build-inputs.py --arch ${{ matrix.arch }}" in INPUT_WORKFLOW
    assert "--only-group acquisition" in INPUT_WORKFLOW
    assert "pip install" not in INPUT_WORKFLOW
    assert '"uv",' in STAGE_INPUTS
    assert '"export",' in STAGE_INPUTS
    assert 'output / "requirements.lock"' in STAGE_INPUTS
    assert 'echo "- MCP build input: \\`${IMAGE}@${digest}\\`"' in INPUT_WORKFLOW


def test_input_publication_uses_pinned_build_actions() -> None:
    action_lines = [
        line.strip()
        for line in INPUT_WORKFLOW.splitlines()
        if line.strip().startswith("uses:")
    ]
    assert action_lines
    assert all(re.fullmatch(r"uses: [^@]+@[0-9a-f]{40}(?: # .+)?", line) for line in action_lines)
