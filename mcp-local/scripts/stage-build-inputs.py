#!/usr/bin/env python3
"""Download and verify the inputs consumed by mcp-local/Dockerfile.

This is the deliberately network-capable prebuild step. The Docker build only
reads the resulting build-inputs directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from urllib.request import urlopen


MCP_LOCAL = Path(__file__).resolve().parents[1]
REPOSITORY = MCP_LOCAL.parent
LOCK_PATH = MCP_LOCAL / "build-inputs.lock.json"
PLATFORM_MACHINES = {"amd64": "x86_64", "arm64": "aarch64"}
DOCKER_PLATFORMS = {"amd64": "linux/amd64", "arm64": "linux/arm64"}
DOWNLOAD_TIMEOUT_SECONDS = 5 * 60


def ca_certificate_bundle() -> Path:
    """Find a complete CA bundle to mount into the minimal Ubuntu image."""
    candidates: list[Path] = []
    try:
        import certifi

        candidates.append(Path(certifi.where()))
    except ImportError:
        pass
    candidates.append(Path("/etc/ssl/certs/ca-certificates.crt"))
    for variable in ("REQUESTS_CA_BUNDLE", "SSL_CERT_FILE"):
        if value := os.getenv(variable):
            candidates.append(Path(value))
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise RuntimeError("no CA certificate bundle is available for Ubuntu snapshot TLS")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download(url: str, destination: Path, expected_sha256: str | None = None) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and (
        expected_sha256 is None or sha256(destination) == expected_sha256
    ):
        return

    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.unlink(missing_ok=True)
    with urlopen(url, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response, temporary.open(
        "wb"
    ) as output:
        shutil.copyfileobj(response, output)
    if expected_sha256 is not None:
        actual = sha256(temporary)
        if actual != expected_sha256:
            temporary.unlink()
            raise RuntimeError(
                f"SHA256 mismatch for {url}: expected {expected_sha256}, got {actual}"
            )
    temporary.replace(destination)


def export_install_requirements(output: Path) -> Path:
    """Export the uv lock into the hashed format consumed by pip."""
    requirements = output / "requirements.lock"
    temporary = output / ".requirements.lock.part"
    temporary.unlink(missing_ok=True)
    subprocess.run(
        [
            "uv",
            "export",
            "--quiet",
            "--directory",
            str(MCP_LOCAL),
            "--locked",
            "--no-default-groups",
            "--no-emit-project",
            "--format",
            "requirements-txt",
            "--no-header",
            "--output-file",
            str(temporary),
        ],
        check=True,
    )
    if not temporary.is_file() or temporary.stat().st_size == 0:
        raise RuntimeError("uv exported an empty pip requirements lock")
    temporary.replace(requirements)
    return requirements


def stage_wheels(arch: str, output: Path, requirements: Path) -> None:
    if sys.platform != "linux":
        raise RuntimeError("wheel staging must run on Linux so Linux markers are selected")
    wheelhouse = output / arch / "wheels"
    wheelhouse.parent.mkdir(parents=True, exist_ok=True)
    machine = PLATFORM_MACHINES[arch]
    # With an explicit target, pip does not infer older compatible manylinux
    # tags. Enumerate the Ubuntu 24.04 glibc range so it can select locked
    # wheels tagged anywhere from manylinux_2_17 through manylinux_2_39.
    platform_args = [
        f"--platform=manylinux_2_{minor}_{machine}" for minor in range(39, 16, -1)
    ]
    # Resolve into a temporary sibling so a failed download cannot leave a
    # partially refreshed or mixed-version wheelhouse behind.
    with tempfile.TemporaryDirectory(
        prefix=".wheels-", dir=wheelhouse.parent
    ) as temporary_directory:
        temporary = Path(temporary_directory)
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "download",
                "--require-hashes",
                "--only-binary=:all:",
                "--python-version=3.12",
                "--implementation=cp",
                "--abi=cp312",
                *platform_args,
                "--index-url=https://download.pytorch.org/whl/cpu",
                "--extra-index-url=https://pypi.org/simple",
                f"--dest={temporary}",
                "--requirement",
                str(requirements),
            ],
            check=True,
            env={**os.environ, "PIP_DISABLE_PIP_VERSION_CHECK": "1"},
        )
        manifest = artifact_manifest(temporary, "*.whl")
        if not manifest:
            raise RuntimeError(f"wheel staging produced no artifacts for {arch}")
        (temporary / "wheelhouse-manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
        )
        if wheelhouse.exists():
            shutil.rmtree(wheelhouse)
        shutil.copytree(temporary, wheelhouse)


def artifact_manifest(directory: Path, pattern: str) -> dict[str, str]:
    """Return a stable filename-to-SHA256 manifest for staged artifacts."""
    return {
        artifact.name: sha256(artifact)
        for artifact in sorted(directory.glob(pattern), key=lambda path: path.name)
    }


def stage_os_package_role(
    lock: dict[str, object],
    arch: str,
    role: str,
    output: Path,
    refresh_lock: bool = False,
) -> dict[str, str]:
    """Resolve one Ubuntu package role from the repository snapshot."""
    os_packages = lock["os_packages"]
    assert isinstance(os_packages, dict)
    roles = os_packages["roles"]
    assert isinstance(roles, dict)
    packages = roles[role]
    assert isinstance(packages, list)
    snapshot = str(os_packages["snapshot"])

    container_images = lock["container_images"]
    assert isinstance(container_images, dict)
    ubuntu = container_images["ubuntu"]
    assert isinstance(ubuntu, dict)
    ubuntu_manifests = ubuntu["manifests"]
    assert isinstance(ubuntu_manifests, dict)
    ubuntu_image = str(ubuntu_manifests[arch])

    role_output = output / arch / "debs" / role
    role_output.parent.mkdir(parents=True, exist_ok=True)
    bundles = os_packages["bundles"]
    assert isinstance(bundles, dict)
    architecture_bundle = bundles[arch]
    assert isinstance(architecture_bundle, dict)
    role_bundle = architecture_bundle[role]
    assert isinstance(role_bundle, dict)
    expected = role_bundle["artifacts"]
    assert isinstance(expected, dict)
    if not refresh_lock and artifact_manifest(role_output, "*.deb") == expected:
        return expected

    with tempfile.TemporaryDirectory(
        prefix=f".{role}-", dir=role_output.parent
    ) as temporary_directory:
        temporary = Path(temporary_directory)
        mounted_ca_bundle = temporary / "ca-certificates.crt"
        shutil.copyfile(ca_certificate_bundle(), mounted_ca_bundle)
        script = """
set -euo pipefail
mkdir -p /bundle/partial
cat > /etc/apt/sources.list.d/ubuntu.sources <<EOF
Types: deb
URIs: https://snapshot.ubuntu.com/ubuntu/${APT_SNAPSHOT}
Suites: noble noble-updates noble-backports noble-security
Components: main restricted universe multiverse
Signed-By: /usr/share/keyrings/ubuntu-archive-keyring.gpg
EOF
apt-get update
apt-get install --yes --download-only --reinstall --no-install-recommends \
    -o Dir::Cache::archives=/bundle \
    ${APT_PACKAGES}
rm -rf /bundle/lock /bundle/partial
chmod -R a+rX /bundle
"""
        subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--platform",
                DOCKER_PLATFORMS[arch],
                "--env",
                f"APT_SNAPSHOT={snapshot}",
                "--env",
                f"APT_PACKAGES={' '.join(str(package) for package in packages)}",
                "--volume",
                f"{temporary}:/bundle",
                "--volume",
                f"{mounted_ca_bundle}:/etc/ssl/certs/ca-certificates.crt:ro",
                ubuntu_image,
                "bash",
                "-ceu",
                script,
            ],
            check=True,
        )
        mounted_ca_bundle.unlink()

        manifest = artifact_manifest(temporary, "*.deb")
        if not manifest:
            raise RuntimeError(
                f"Ubuntu snapshot produced no {role} packages for {arch}"
            )

        if not refresh_lock and manifest != expected:
            missing = sorted(set(expected) - set(manifest))
            unexpected = sorted(set(manifest) - set(expected))
            changed = sorted(
                filename
                for filename in set(expected) & set(manifest)
                if expected[filename] != manifest[filename]
            )
            raise RuntimeError(
                f"Ubuntu {role} bundle for {arch} does not match the lock; "
                f"missing={missing}, unexpected={unexpected}, changed={changed}"
            )

        if role_output.exists():
            shutil.rmtree(role_output)
        shutil.copytree(temporary, role_output)
        return manifest


def stage_os_packages(lock: dict[str, object], arch: str, output: Path) -> None:
    """Stage all native packages required by the Docker build."""
    for role in ("builder", "runtime"):
        stage_os_package_role(lock, arch, role, output)


def stage_arch(lock: dict[str, object], arch: str, output: Path) -> None:
    performix = lock["performix"]
    assert isinstance(performix, dict)
    artifacts = performix["artifacts"]
    assert isinstance(artifacts, dict)
    artifact = artifacts[arch]
    assert isinstance(artifact, dict)
    download(
        str(artifact["url"]),
        output / arch / "performix.tar.gz",
        str(artifact["sha256"]),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--arch", choices=(*PLATFORM_MACHINES, "all"), required=True)
    parser.add_argument(
        "--output", type=Path, default=MCP_LOCAL / "build-inputs"
    )
    parser.add_argument("--skip-wheels", action="store_true")
    parser.add_argument("--skip-os-packages", action="store_true")
    parser.add_argument(
        "--refresh-os-lock",
        action="store_true",
        help="Resolve the snapshot and replace the checked-in deb manifests.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    lock = json.loads(LOCK_PATH.read_text(encoding="utf-8"))
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    requirements = export_install_requirements(output)

    migration = lock["migrate_ease"]
    assert isinstance(migration, dict)
    download(
        str(migration["url"]),
        output / "migrate-ease.tar.gz",
        str(migration["sha256"]),
    )
    arches = PLATFORM_MACHINES if args.arch == "all" else (args.arch,)
    for arch in arches:
        stage_arch(lock, arch, output)
        if not args.skip_os_packages:
            if args.refresh_os_lock:
                os_packages = lock["os_packages"]
                assert isinstance(os_packages, dict)
                bundles = os_packages["bundles"]
                assert isinstance(bundles, dict)
                architecture_bundle = bundles[arch]
                assert isinstance(architecture_bundle, dict)
                for role in ("builder", "runtime"):
                    role_bundle = architecture_bundle[role]
                    assert isinstance(role_bundle, dict)
                    role_bundle["artifacts"] = stage_os_package_role(
                        lock, arch, role, output, refresh_lock=True
                    )
            else:
                stage_os_packages(lock, arch, output)
        if not args.skip_wheels:
            stage_wheels(arch, output, requirements)

    if args.refresh_os_lock:
        LOCK_PATH.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")

    (output / ".complete").write_text("verified\n", encoding="utf-8")


if __name__ == "__main__":
    main()
