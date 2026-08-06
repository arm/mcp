import json
from pathlib import Path
import re


REPOSITORY = Path(__file__).resolve().parents[2]
MCP_LOCAL = REPOSITORY / "mcp-local"
LOCK = json.loads((MCP_LOCAL / "build-inputs.lock.json").read_text())
MODEL_LOCK = json.loads(
    (REPOSITORY / "embedding-generation/embedding-model.lock.json").read_text()
)
DOCKERFILE = (MCP_LOCAL / "Dockerfile").read_text()
SERVER = (MCP_LOCAL / "server.py").read_text()


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
