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
SERVER_METADATA = json.loads((MCP_LOCAL / "server.json").read_text())
INPUT_WORKFLOW = (
    REPOSITORY / ".github/workflows/build-mcp-inputs.yml"
).read_text()
TOOLCHAIN_WORKFLOW = (
    REPOSITORY / ".github/workflows/build-embedding-toolchain.yml"
).read_text()
PIN_PROMOTION_SCRIPT = (
    REPOSITORY / ".github/scripts/propose-pin-pr.sh"
).read_text()
EMBEDDING_WORKFLOW = (
    REPOSITORY / ".github/workflows/build-embeddings.yml"
).read_text()
IMAGE_WORKFLOW = (REPOSITORY / ".github/workflows/build-mcp-image.yml").read_text()
PIN_WORKFLOWS = (TOOLCHAIN_WORKFLOW, INPUT_WORKFLOW, EMBEDDING_WORKFLOW)
REQUIRED_CHECK_DISPATCH = (
    REPOSITORY / ".github/scripts/dispatch-required-pr-checks.sh"
).read_text()
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
    acquisition = pyproject["dependency-groups"]["acquisition"]
    assert len(acquisition) == 1
    assert re.fullmatch(r"pip==[^=]+", acquisition[0])
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
    assert (
        'export PYTHONPATH="/opt/arm-migration-tools/migrate-ease'
        '${PYTHONPATH:+:$PYTHONPATH}"'
    ) in DOCKERFILE
    assert "mcp-local/build-inputs/" not in DOCKERFILE
    assert "!mcp-local/build-inputs/" not in ROOT_DOCKERIGNORE
    assert "--from=embeddings /embedding-data/embedding-model/" in DOCKERFILE


def test_final_builds_do_not_acquire_inputs_live() -> None:
    for workflow in (IMAGE_WORKFLOW, INTEGRATION_WORKFLOW):
        assert "stage-build-inputs.py" not in workflow
        assert "packages: read" in workflow
        assert "Log in to GHCR for locked build inputs" in workflow
    assert "python -m pip install --upgrade pip" not in INTEGRATION_WORKFLOW


def test_final_builds_disable_network_for_every_run_instruction() -> None:
    run_instructions = [
        line.strip()
        for line in DOCKERFILE.splitlines()
        if re.match(r"(?i:RUN)(?:\s|$)", line.strip())
    ]
    assert run_instructions
    assert all(
        re.match(r"(?i:RUN)\s+--network=none(?:\s|$)", instruction)
        for instruction in run_instructions
    )
    assert "          network: none\n" in IMAGE_WORKFLOW
    assert "            --network none \\\n" in INTEGRATION_WORKFLOW


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
    assert "push:" in image_triggers
    assert "- mcp-local/server.json" in image_triggers
    assert "automation/pin-embedding-vectorstore" not in IMAGE_WORKFLOW
    assert "propose-mcp-embedding-pin:" in EMBEDDING_WORKFLOW
    assert "update-mcp-embedding-pin.py" in EMBEDDING_WORKFLOW
    assert "mcp-local/server.json" in EMBEDDING_WORKFLOW
    assert "gh pr merge" not in EMBEDDING_WORKFLOW


def test_release_uses_reviewed_server_version_without_self_merging() -> None:
    assert "Validate reviewed release version" in IMAGE_WORKFLOW
    assert "github.event_name == 'push'" in IMAGE_WORKFLOW
    assert 'version="$(jq -er' in IMAGE_WORKFLOW
    assert "gh pr merge" not in IMAGE_WORKFLOW
    assert "BUMP_BRANCH" not in IMAGE_WORKFLOW
    assert "${IMAGE}:${VERSION}-amd64" in IMAGE_WORKFLOW
    assert "${IMAGE}:${VERSION}-arm64" in IMAGE_WORKFLOW


def test_manual_release_proposals_support_all_release_types() -> None:
    assert "propose-version:" in IMAGE_WORKFLOW
    assert "- hotfix" in IMAGE_WORKFLOW
    assert "- minor" in IMAGE_WORKFLOW
    assert "- major" in IMAGE_WORKFLOW
    assert "bump_mcp_version.py" in IMAGE_WORKFLOW
    assert "gh pr create" in IMAGE_WORKFLOW
    assert "gh pr merge" not in IMAGE_WORKFLOW
    assert "RELEASE_PR_TOKEN" not in IMAGE_WORKFLOW
    assert "dispatch-required-pr-checks.sh" in IMAGE_WORKFLOW


def test_generated_prs_dispatch_required_checks_without_an_external_token() -> None:
    assert "RELEASE_PR_TOKEN" not in EMBEDDING_WORKFLOW
    assert "actions: write" in IMAGE_WORKFLOW
    assert "actions: write" in EMBEDDING_WORKFLOW
    assert "dispatch-required-pr-checks.sh" in PIN_PROMOTION_SCRIPT
    for workflow in PIN_WORKFLOWS:
        assert "actions: write" in workflow
        assert "propose-pin-pr.sh" in workflow
    for workflow in (
        "integration-tests.yml",
        "embedding-unit-tests.yml",
        "scorecard.yml",
    ):
        assert workflow in REQUIRED_CHECK_DISPATCH


def test_version_bump_script_supports_all_release_types() -> None:
    script = REPOSITORY / ".github/scripts/bump_mcp_version.py"
    major, minor, patch = map(int, SERVER_METADATA["version"].split("."))
    for bump_type, expected_version in (
        ("major", f"{major + 1}.0.0"),
        ("minor", f"{major}.{minor + 1}.0"),
        ("hotfix", f"{major}.{minor}.{patch + 1}"),
    ):
        with tempfile.TemporaryDirectory() as temporary_directory:
            server_file = Path(temporary_directory) / "server.json"
            server_file.write_text(
                (MCP_LOCAL / "server.json").read_text(), encoding="utf-8"
            )
            subprocess.run(
                [
                    sys.executable,
                    str(script),
                    "--bump-type",
                    bump_type,
                    "--server-file",
                    str(server_file),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            updated_server = json.loads(server_file.read_text())
            assert updated_server["version"] == expected_version
            assert any(
                package.get("identifier")
                == f"docker.io/armlimited/arm-mcp:{expected_version}"
                for package in updated_server["packages"]
            )


def test_server_metadata_uses_its_version_for_the_release_image() -> None:
    version = SERVER_METADATA["version"]
    assert re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version)
    assert any(
        package.get("registryType") == "oci"
        and package.get("identifier") == f"docker.io/armlimited/arm-mcp:{version}"
        for package in SERVER_METADATA["packages"]
    )


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
        server_file = temporary / "server.json"
        lock_file.write_text(
            (MCP_LOCAL / "build-inputs.lock.json").read_text(), encoding="utf-8"
        )
        dockerfile.write_text(
            (MCP_LOCAL / "Dockerfile").read_text(), encoding="utf-8"
        )
        server_file.write_text(
            (MCP_LOCAL / "server.json").read_text(), encoding="utf-8"
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
                "--server-file",
                str(server_file),
            ],
            check=True,
        )

        updated = json.loads(lock_file.read_text())
        embeddings = updated["container_images"]["embeddings"]
        assert embeddings["reference"] == new_reference
        assert embeddings["source_revision"] == new_revision
        assert embeddings["workflow_run"] == "123456"
        assert f"ARG EMBEDDINGS_IMAGE={new_reference}" in dockerfile.read_text()
        updated_server = json.loads(server_file.read_text())
        current_major, current_minor, _ = map(
            int, SERVER_METADATA["version"].split(".")
        )
        expected_version = f"{current_major}.{current_minor + 1}.0"
        assert updated_server["version"] == expected_version
        assert any(
            package.get("identifier")
            == f"docker.io/armlimited/arm-mcp:{expected_version}"
            for package in updated_server["packages"]
        )


def test_toolchain_input_changes_rebuild_and_propose_pin() -> None:
    workflow_triggers = TOOLCHAIN_WORKFLOW.split("jobs:", maxsplit=1)[0]
    assert "push:" in workflow_triggers
    assert "branches: [main]" in workflow_triggers
    for source in (
        ".dockerignore",
        ".python-version",
        "Dockerfile.toolchain",
        "acquire-model.py",
        "document_chunking.py",
        "embedding-model.lock.json",
        "generate-chunks.py",
        "local_vectorstore_creation.py",
        "pyproject.toml",
        "uv.lock",
    ):
        assert f"embedding-generation/{source}" in workflow_triggers
    assert "propose-toolchain-pin:" in TOOLCHAIN_WORKFLOW
    assert "update-embedding-toolchain-pin.py" in TOOLCHAIN_WORKFLOW
    assert "automation/pin-embedding-generator" in TOOLCHAIN_WORKFLOW
    assert "cancel-in-progress: false" in TOOLCHAIN_WORKFLOW
    assert "gh pr merge" not in TOOLCHAIN_WORKFLOW


def test_embedding_toolchain_pin_updater_changes_only_generator_input() -> None:
    script = REPOSITORY / ".github/scripts/update-embedding-toolchain-pin.py"
    new_reference = "ghcr.io/arm/mcp-embedding-generator@sha256:" + "3" * 64

    with tempfile.TemporaryDirectory() as temporary_directory:
        lock_file = Path(temporary_directory) / "pipeline-inputs.lock.json"
        original = json.loads(
            (
                REPOSITORY / "embedding-generation/pipeline-inputs.lock.json"
            ).read_text()
        )
        lock_file.write_text(json.dumps(original), encoding="utf-8")
        subprocess.run(
            [
                sys.executable,
                str(script),
                "--reference",
                new_reference,
                "--lock-file",
                str(lock_file),
            ],
            check=True,
        )

        updated = json.loads(lock_file.read_text())
        assert updated["generator_image"] == new_reference
        assert (
            updated["intrinsic_chunks_image"]
            == original["intrinsic_chunks_image"]
        )


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


def test_input_publication_is_automatic_private_and_multi_architecture() -> None:
    assert "workflow_dispatch:" in INPUT_WORKFLOW
    workflow_triggers = INPUT_WORKFLOW.split("jobs:", maxsplit=1)[0]
    assert "permissions: read-all" in workflow_triggers
    assert "push:" in workflow_triggers
    assert "branches: [main]" in workflow_triggers
    for source in (
        ".dockerignore",
        ".python-version",
        "Dockerfile.inputs",
        "pyproject.toml",
        "scripts/stage-build-inputs.py",
        "uv.lock",
    ):
        assert f"mcp-local/{source}" in workflow_triggers
    assert "mcp-local/build-inputs.lock.json" not in workflow_triggers
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
    assert "propose-input-pin:" in INPUT_WORKFLOW
    assert "update-mcp-input-pin.py" in INPUT_WORKFLOW
    assert "automation/pin-mcp-build-inputs" in INPUT_WORKFLOW
    assert "cancel-in-progress: false" in INPUT_WORKFLOW
    assert "gh pr merge" not in INPUT_WORKFLOW


def test_pin_promotions_share_review_pr_mechanics() -> None:
    # The workflows declare what to update, while one reviewed helper owns all
    # mutation of automation branches and pull requests.
    assert "gh pr create" in PIN_PROMOTION_SCRIPT
    assert "gh pr edit" in PIN_PROMOTION_SCRIPT
    assert "dispatch-required-pr-checks.sh" in PIN_PROMOTION_SCRIPT
    assert "gh pr merge" not in PIN_PROMOTION_SCRIPT
    for workflow in PIN_WORKFLOWS:
        assert "propose-pin-pr.sh" in workflow
        assert "gh pr create" not in workflow
        assert "gh pr edit" not in workflow


def test_pin_promotions_skip_candidates_built_from_stale_inputs() -> None:
    for workflow in PIN_WORKFLOWS:
        assert 'test "$(git rev-parse HEAD)" = "${GITHUB_SHA}"' in workflow


def test_mcp_input_pin_updater_keeps_manifest_and_dockerfile_in_sync() -> None:
    script = REPOSITORY / ".github/scripts/update-mcp-input-pin.py"
    index_reference = "ghcr.io/arm/mcp-build-inputs@sha256:" + "4" * 64
    amd64_reference = "ghcr.io/arm/mcp-build-inputs@sha256:" + "5" * 64
    arm64_reference = "ghcr.io/arm/mcp-build-inputs@sha256:" + "6" * 64

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
                index_reference,
                "--amd64-reference",
                amd64_reference,
                "--arm64-reference",
                arm64_reference,
                "--source-revision",
                "7" * 40,
                "--workflow-run",
                "123456",
                "--lock-file",
                str(lock_file),
                "--dockerfile",
                str(dockerfile),
            ],
            check=True,
        )

        updated = json.loads(lock_file.read_text())["container_images"][
            "mcp_build_inputs"
        ]
        assert updated["reference"] == index_reference
        assert updated["manifests"] == {
            "amd64": amd64_reference,
            "arm64": arm64_reference,
        }
        assert updated["source_revision"] == "7" * 40
        assert updated["workflow_run"] == "123456"
        assert (
            f"ARG MCP_BUILD_INPUTS_IMAGE={index_reference}"
            in dockerfile.read_text()
        )


def test_mcp_input_pin_updater_preserves_provenance_for_same_bundle() -> None:
    script = REPOSITORY / ".github/scripts/update-mcp-input-pin.py"
    current = LOCK["container_images"]["mcp_build_inputs"]

    with tempfile.TemporaryDirectory() as temporary_directory:
        temporary = Path(temporary_directory)
        lock_file = temporary / "build-inputs.lock.json"
        dockerfile = temporary / "Dockerfile"
        original_lock = (MCP_LOCAL / "build-inputs.lock.json").read_text()
        original_dockerfile = (MCP_LOCAL / "Dockerfile").read_text()
        lock_file.write_text(original_lock, encoding="utf-8")
        dockerfile.write_text(original_dockerfile, encoding="utf-8")

        subprocess.run(
            [
                sys.executable,
                str(script),
                "--reference",
                current["reference"],
                "--amd64-reference",
                current["manifests"]["amd64"],
                "--arm64-reference",
                current["manifests"]["arm64"],
                "--source-revision",
                "8" * 40,
                "--workflow-run",
                "654321",
                "--lock-file",
                str(lock_file),
                "--dockerfile",
                str(dockerfile),
            ],
            check=True,
        )

        assert lock_file.read_text() == original_lock
        assert dockerfile.read_text() == original_dockerfile
