"""Publish metadata only for an existing, verified Arm MCP release."""

import argparse
import base64
import json
import os
from pathlib import Path
import re
import subprocess
import time
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import urlopen

REPOSITORY = "arm/mcp"
NAME = "io.github.arm/arm-mcp"
IMAGE = "docker.io/armlimited/arm-mcp"
REGISTRY = "https://registry.modelcontextprotocol.io/v0.1"
OFFICIAL = "io.modelcontextprotocol.registry/official"


def run(*args):
    return subprocess.check_output(args, text=True).strip()


def github(path):
    return json.loads(run("gh", "api", f"repos/{REPOSITORY}/{path}"))


def version_value(value):
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", value):
        raise ValueError("Release version must use X.Y.Z without a v prefix")
    return value


def release(version):
    result = github(f"releases/tags/v{version_value(version)}")
    if (
        result["draft"]
        or result["prerelease"]
        or result["tag_name"] != f"v{version}"
        or "<!-- arm-mcp-withdrawn -->" in (result.get("body") or "")
        or "WITHDRAWN" in (result.get("name") or "").upper()
    ):
        raise ValueError(
            "Only published, non-withdrawn production releases are eligible"
        )
    return result


def validate_manifest(manifest, version):
    if manifest.get("name") != NAME or manifest.get("version") != version:
        raise ValueError("Registry identity/version does not match the release")
    packages = manifest.get("packages", [])
    if len(packages) != 1 or (
        packages[0].get("registryType") != "oci"
        or packages[0].get("identifier") != f"{IMAGE}:{version}"
        or packages[0].get("transport") != {"type": "stdio"}
    ):
        raise ValueError("Manifest must reference the released OCI image over stdio")


def summary(message):
    print(message)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as output:
            output.write(message + "\n")


def prepare(version, expected_source_sha, manifest_path):
    details = release(version)
    source_sha = github(f"commits/v{version}")["sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise ValueError("Release tag did not resolve to a full commit SHA")
    if expected_source_sha and source_sha != expected_source_sha:
        raise ValueError("Release tag differs from the authorized source commit")
    if github(f"compare/{source_sha}...main")["status"] not in {"ahead", "identical"}:
        raise ValueError("Released commit must be an ancestor of main")
    file = github(f"contents/mcp-local/server.json?ref={source_sha}")
    manifest = json.loads(base64.b64decode(file["content"]))
    validate_manifest(manifest, version)
    match = re.search(
        r"Immutable digest: `(?P<digest>sha256:[0-9a-f]{64})`",
        details.get("body") or "",
    )
    if not match:
        raise ValueError("GitHub release has no immutable image digest")
    digest = match["digest"]
    resolved = json.loads(
        run(
            "docker",
            "buildx",
            "imagetools",
            "inspect",
            f"{IMAGE}:{version}",
            "--format",
            "{{json .Manifest}}",
        )
    )["digest"]
    if resolved != digest:
        raise ValueError("Released image tag does not match the recorded digest")
    run(
        "gh",
        "attestation",
        "verify",
        f"oci://{IMAGE}@{digest}",
        "--repo",
        REPOSITORY,
        "--signer-workflow",
        f"{REPOSITORY}/.github/workflows/trusted-mcp-release.yml",
        "--source-ref",
        "refs/heads/main",
        "--source-digest",
        source_sha,
        "--bundle-from-oci",
    )
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    summary(
        f"Verified registry metadata for {NAME} {version}: source `{source_sha}`, image `{digest}`."
    )


def lookup(version):
    url = (
        f"{REGISTRY}/servers/{quote(NAME, safe='')}/versions/{quote(version, safe='')}"
    )
    try:
        with urlopen(url, timeout=30) as response:
            return json.load(response)
    except HTTPError as error:
        if error.code == 404:
            return None
        raise


def assert_published(record, manifest):
    if not record or record["_meta"][OFFICIAL]["status"] != "active":
        raise ValueError("Registry version is absent or not active")

    # The registry may migrate its schema and attach publisher metadata. All
    # installation and descriptive metadata must still match the release.
    def comparable(value):
        return {k: v for k, v in value.items() if k not in {"$schema", "_meta"}}

    if comparable(record["server"]) != comparable(manifest):
        raise ValueError("Existing registry metadata differs; do not overwrite it")


def publish(manifest_path):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    version = version_value(manifest["version"])
    validate_manifest(manifest, version)
    release(version)  # Recheck after waiting for production approval.
    record = lookup(version)
    if record is not None:
        assert_published(record, manifest)
        summary(f"{NAME} {version} is already published with matching metadata.")
        return
    subprocess.run(["mcp-publisher", "publish", str(manifest_path)], check=True)
    for attempt in range(6):
        record = lookup(version)
        if record is not None:
            assert_published(record, manifest)
            summary(
                f"Published and verified {NAME} {version} in the official MCP Registry."
            )
            return
        if attempt < 5:
            time.sleep(5)
    raise ValueError("Publication was not visible; retry the registry-only workflow")


def withdraw(version):
    version_value(version)
    record = lookup(version)
    if record is None:
        summary(
            f"{NAME} {version} was never registered; no registry withdrawal needed."
        )
        return
    if record["_meta"][OFFICIAL]["status"] != "deleted":
        subprocess.run(
            [
                "mcp-publisher",
                "status",
                "--status",
                "deleted",
                "--message",
                "This Arm MCP release has been withdrawn; see GitHub releases.",
                NAME,
                version,
            ],
            check=True,
        )
    record = lookup(version)
    if record is not None and record["_meta"][OFFICIAL]["status"] != "deleted":
        raise ValueError("Registry version is still visible after withdrawal")
    summary(f"{NAME} {version} is withdrawn from the official MCP Registry.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["prepare", "publish", "withdraw"])
    parser.add_argument("--version")
    parser.add_argument("--expected-source-sha", default="")
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    if args.operation == "prepare":
        if not args.version or not args.manifest:
            parser.error("prepare requires --version and --manifest")
        prepare(args.version, args.expected_source_sha, args.manifest)
    elif args.operation == "publish":
        if not args.manifest:
            parser.error("publish requires --manifest")
        publish(args.manifest)
    else:
        if not args.version:
            parser.error("withdraw requires --version")
        withdraw(args.version)


if __name__ == "__main__":
    main()
