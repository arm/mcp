import json
from pathlib import Path
import re
import tomllib


REPOSITORY = Path(__file__).resolve().parents[2]
MCP_LOCAL = REPOSITORY / "mcp-local"
LOCK = json.loads((MCP_LOCAL / "build-inputs.lock.json").read_text())
MODEL_LOCK = json.loads(
    (REPOSITORY / "embedding-generation/embedding-model.lock.json").read_text()
)
DOCKERFILE = (MCP_LOCAL / "Dockerfile").read_text()
INPUT_DOCKERFILE = (MCP_LOCAL / "Dockerfile.inputs").read_text()
INPUT_DOCKERIGNORE = (MCP_LOCAL / ".dockerignore").read_text()
SERVER = (MCP_LOCAL / "server.py").read_text()
INPUT_WORKFLOW = (
    REPOSITORY / ".github/workflows/build-mcp-inputs.yml"
).read_text()


def test_docker_base_images_match_manifest() -> None:
    for image in LOCK["container_images"].values():
        assert image["reference"] in DOCKERFILE
        assert "@sha256:" in image["reference"]
    ubuntu_manifests = LOCK["container_images"]["ubuntu"]["manifests"]
    assert set(ubuntu_manifests) == {"amd64", "arm64"}
    assert all("@sha256:" in reference for reference in ubuntu_manifests.values())


def test_all_architecture_specific_inputs_cover_release_architectures() -> None:
    expected = {"amd64", "arm64"}
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
    assert re.fullmatch(r"[0-9a-f]{40}", migration["revision"])
    assert re.fullmatch(r"[0-9a-f]{64}", migration["sha256"])

    for artifact in LOCK["performix"]["artifacts"].values():
        assert re.fullmatch(r"[0-9a-f]{64}", artifact["sha256"])


def test_direct_python_requirements_are_exactly_pinned() -> None:
    requirements = (MCP_LOCAL / "requirements.txt").read_text().splitlines()
    dependencies = [line for line in requirements if line and not line.startswith("#")]
    assert dependencies
    assert all("==" in dependency for dependency in dependencies)
    pyproject = tomllib.loads((MCP_LOCAL / "pyproject.toml").read_text())
    assert set(dependencies) == set(pyproject["project"]["dependencies"])


def test_dockerfile_consumes_only_staged_third_party_inputs() -> None:
    assert "arm-linux-migration-tools/main/scripts/install.sh" not in DOCKERFILE
    assert "curl " not in DOCKERFILE
    assert "https://" not in DOCKERFILE
    assert "--network=none pip install" in DOCKERFILE
    assert "apt-get update" not in DOCKERFILE
    assert "--network=none apt-get install" in DOCKERFILE
    assert "--no-download" in DOCKERFILE
    assert "build-inputs/${TARGETARCH}/performix.tar.gz" in DOCKERFILE
    assert "build-inputs/${TARGETARCH}/debs/builder/" in DOCKERFILE
    assert "build-inputs/${TARGETARCH}/debs/runtime/" in DOCKERFILE
    assert "build-inputs/migrate-ease.tar.gz" in DOCKERFILE
    assert "--from=embeddings /embedding-data/embedding-model/" in DOCKERFILE
    assert "build-inputs/embedding-model/" not in DOCKERFILE


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
    assert "/mcp-build-inputs/metadata/" in INPUT_DOCKERFILE
    for source in (
        "build-inputs/**",
        "build-inputs.lock.json",
        "requirements.lock",
        "requirements.txt",
        "pyproject.toml",
        "uv.lock",
    ):
        assert f"!{source}" in INPUT_DOCKERIGNORE


def test_input_publication_is_manual_private_and_multi_architecture() -> None:
    assert "workflow_dispatch:" in INPUT_WORKFLOW
    assert "push:" not in INPUT_WORKFLOW.split("jobs:", maxsplit=1)[0]
    assert "packages: write" in INPUT_WORKFLOW
    assert "verify-ghcr-package-private.sh" in INPUT_WORKFLOW
    assert "ubuntu-24.04-arm" in INPUT_WORKFLOW
    assert "linux/amd64" in INPUT_WORKFLOW
    assert "linux/arm64" in INPUT_WORKFLOW
    assert "docker buildx imagetools create" in INPUT_WORKFLOW
    assert "stage-build-inputs.py --arch ${{ matrix.arch }}" in INPUT_WORKFLOW
    assert 'echo "- MCP build input: \\`${IMAGE}@${digest}\\`"' in INPUT_WORKFLOW


def test_input_publication_uses_pinned_build_actions() -> None:
    action_lines = [
        line.strip()
        for line in INPUT_WORKFLOW.splitlines()
        if line.strip().startswith("uses:")
    ]
    assert action_lines
    assert all(re.fullmatch(r"uses: [^@]+@[0-9a-f]{40}(?: # .+)?", line) for line in action_lines)
