# Contributing to Arm MCP Server

Thank you for contributing. This guide covers repository development, testing,
reproducible build inputs, and the reviewed release workflows.

## Repository Structure

- **`mcp-local/`**: The MCP server implementation
  - `server.py`: Main FastMCP server with tool definitions
  - `utils/`: Helper modules for each tool
  - `data/`: Pre-built knowledge base (embeddings and metadata)
  - `Dockerfile`: Multi-stage Docker build
- **`embedding-generation/`**: Scripts for regenerating the knowledge base from source documents

## Integration Testing

### Pre-requisites

- Build the mcp server docker image
- Install the locked test dependencies with `uv sync --locked --only-group test`
  within the `mcp-local` directory.

### Testing Steps

- Run the test script with
  `uv run --locked --only-group test pytest -s tests/test_mcp.py`
- Check if following 2 docker containers have started - **mcp server** & **testcontainer**
- All tests should pass without any errors. Warnings can be ignored.

## Reproducible MCP Build Inputs

The final MCP image build does not resolve or download Python packages, Ubuntu
packages, or migrate-ease. Those inputs are acquired separately by
the manually triggered **Build MCP Input Bundle** workflow and published as a
private, multi-architecture OCI image at `ghcr.io/arm/mcp-build-inputs`.

The acquisition workflow runs natively on AMD64 and Arm64. For each
architecture it:

1. verifies the checked-in uv lock and exports hash-locked pip requirements;
2. downloads the exact Python wheels allowed by those hashes;
3. downloads the complete `.deb` closures from the recorded Ubuntu snapshot
   and checks every package against `mcp-local/build-inputs.lock.json`;
4. downloads and verifies the pinned migrate-ease source archive; and
5. publishes those bytes and their lock metadata in a scratch image, then
   combines both architecture images into one private OCI image index.

`mcp-local/Dockerfile` selects the matching architecture from that index and
copies the files from it. Python and apt installation use only those local
files with network access disabled. The Ubuntu base image, input bundle, and
embedding vector-store image are all selected by immutable OCI digest. The
currently approved input bundle is recorded in
`mcp-local/build-inputs.lock.json` and defaults to:

```text
ghcr.io/arm/mcp-build-inputs@sha256:8db95af8e7d819b82adbed0bd1c9eadcd1d0f2afdd144c52618b58bccfbf07cf
```

### Why the Build Uses Multiple Dockerfiles

Each Dockerfile represents a different trust or network boundary:

- `mcp-local/Dockerfile.inputs` has no `RUN` commands and starts from
  `scratch`. It packages the verified wheels, `.deb` files, archives, and lock
  metadata into the multi-architecture OCI artifact that GHCR can store.
- `mcp-local/Dockerfile` is the final application build. It consumes the
  approved MCP-input and embedding artifacts by digest and installs their
  contents with networking disabled.
- `embedding-generation/Dockerfile.toolchain` creates the pinned Python and
  model environment used by the embedding pipeline.
- `embedding-generation/Dockerfile.acquire` is the controlled network phase
  that collects source material and publishes the resulting chunks.
- `embedding-generation/Dockerfile.vectorstore` consumes the pinned toolchain
  and chunks, generates the model index and metadata offline, and packages the
  output in a `scratch` artifact for the MCP image.

These could technically be stages in one large Dockerfile, but keeping the
artifacts separate lets the workflows publish, inspect, cache, approve, and
pin each boundary independently. It also makes it difficult for a supposedly
offline phase to acquire dependencies accidentally. `Dockerfile.inputs` is
the small adapter needed because GHCR stores OCI images rather than arbitrary
directories; using a `scratch` image adds no runtime operating system.

### Building the MCP Image

Authenticate Docker to GHCR before building because the build-input and
embedding images are private:

```bash
docker login ghcr.io
docker buildx build \
  --network none \
  --file mcp-local/Dockerfile \
  --tag arm-mcp:local \
  --load \
  .
```

The local build defaults to the Docker host's native architecture. GitHub
Actions performs the same GHCR login and explicitly builds both release
architectures without running the acquisition script.

### Testing a Local MCP Image

The Dockerfile installs the application but does not run the application test
suite during image assembly. After building `arm-mcp:local`, run a lightweight
container smoke test explicitly:

```bash
docker run --rm \
  --entrypoint sh \
  arm-mcp:local \
  -c 'set -eu
      skopeo --version
      llvm-mca --version
      git --version
      migrate-ease-cpp --help >/dev/null
      python -c "import magic, requests; from utils.docker_utils import check_docker_image_architectures"'
```

The packaged embedding model can be checked separately without network
access:

```bash
docker run --rm \
  --network none \
  --entrypoint python \
  arm-mcp:local \
  -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('/app/embedding-model', local_files_only=True, trust_remote_code=False)"
```

For the full MCP protocol and tool integration suite, tag the local image as
`arm-mcp:latest` or set `MCP_IMAGE=arm-mcp:local`, then follow the repository's
integration-test setup.

### Runtime Egress Release Gate

The trusted release workflow validates each final AMD64 and Arm64 image after
the architecture-specific image is pushed and before the production
multi-architecture tags or GitHub release are created. The validator addresses
runtime behavior; the build-time network isolation described above is a
separate control.

Each image is selected by the immutable digest emitted by BuildKit and run with
Docker's `none` network. The runner's `strace` executable records network
syscalls from the MCP process and all children. Trace output is collected from
Docker's host-captured standard-error channel and persisted only after the
container exits; the image under test receives no writable evidence mount. The
workflow pins the Ubuntu package version, verifies the installed version, and
records it in both `runtime-egress-evidence.json` and the workflow summary. The
test exercises MCP startup, the embedded knowledge/vector search, a local
migrate-ease scan, sysreport instructions, and (on Arm64) local llvm-mca
analysis. Any non-loopback IPv4 or IPv6 `connect`, `sendto`, `sendmsg`, or
`sendmmsg` destination fails the gate.
The production image sets `FASTMCP_CHECK_FOR_UPDATES=off` so FastMCP does not
contact PyPI during server startup; dependency updates remain a build/release
responsibility rather than a runtime side effect.
MCP communication over standard input/output, Unix-domain sockets, and local
loopback traffic are permitted because they cannot produce outbound traffic.

A negative control deliberately attempts DNS, UDP, TCP, HTTP, and HTTPS egress
to the documentation-only `203.0.113.0/24` range. The gate also fails unless
those attempts are both blocked and present in the trace, proving that an empty
application trace is meaningful. The workflow retains the raw traces, process
output, and `runtime-egress-evidence.json` for 90 days and adds a digest- and
platform-specific summary to the workflow run.

After both architecture gates pass, the release job retrieves their validated
image digests from workflow artifacts and creates the production manifest from
digest-qualified references. Mutable architecture tags are never used as
manifest sources, so the published AMD64 and Arm64 images are the exact images
that passed validation.

There are no approved unsolicited-runtime exceptions. Tools whose explicit
purpose is remote access are covered by the separate integration suite and are
not invoked by this offline gate. A future exception must be documented here
with its destination,
protocol, port, owner, and rationale, implemented as a narrow reviewed rule in
`mcp-local/scripts/validate-runtime-egress.py`, and approved before release.
Missing, skipped, or failed evidence in either architecture matrix leg prevents
the production manifest and release from being published.

### Inspecting the Published Inputs

The index and its platform manifests can be inspected without unpacking it:

```bash
MCP_INPUTS="ghcr.io/arm/mcp-build-inputs@sha256:8db95af8e7d819b82adbed0bd1c9eadcd1d0f2afdd144c52618b58bccfbf07cf"
docker buildx imagetools inspect "$MCP_INPUTS"
docker buildx imagetools inspect "$MCP_INPUTS" --format '{{json .Manifest}}' | jq
```

To inspect the actual files for the Docker host's native architecture:

```bash
docker pull "$MCP_INPUTS"
container_id="$(docker create "$MCP_INPUTS")"
docker cp "$container_id:/mcp-build-inputs" ./mcp-build-inputs-inspect
docker rm "$container_id"
find ./mcp-build-inputs-inspect -maxdepth 3 -type f | sort
```

The copied `metadata/` directory contains the checked-in dependency metadata
and the generated pip-compatible lock used during acquisition. The checked-in
manifest additionally records the published index digest, per-architecture
manifest digests, source commit, workflow run, and verification method.

### Refreshing the Inputs

Refreshing is deliberately a reviewed two-commit process because an OCI artifact
cannot contain its own not-yet-known digest:

#### Updating Python Packages

`mcp-local/pyproject.toml` is the only direct dependency declaration, and
`mcp-local/uv.lock` is the only checked-in transitive dependency lock. Use the
uv version recorded in `mcp-local/build-inputs.lock.json` to update the lock:

```bash
uv --version
uv lock --directory mcp-local --upgrade-package PACKAGE_NAME
```

Review and commit the `pyproject.toml` and `uv.lock` changes. During input
acquisition, pinned uv exports a pip-compatible hashed lock from `uv.lock`.
That generated file is used to download the AMD64 and Arm64 wheelhouses and is
preserved as `metadata/requirements.lock` in the immutable GHCR input artifact;
it is not checked into the repository.

#### Updating the Python Interpreter

An interpreter upgrade changes the wheel ABI and the Ubuntu package closure.
Update all of the following together:

- `mcp-local/.python-version`;
- `project.requires-python` in `mcp-local/pyproject.toml`;
- `generated_with.python` in `mcp-local/build-inputs.lock.json`;
- `python-version` in `.github/workflows/build-mcp-inputs.yml`;
- the `--python-version` and `--abi` arguments in
  `mcp-local/scripts/stage-build-inputs.py`; and
- the builder and runtime Python packages in the Ubuntu package lock, if the
  selected Ubuntu base does not provide the new interpreter through the
  existing `python3` package.

Regenerate the uv lock, refresh the Ubuntu package manifests as described
below, and build both architectures before accepting the upgrade.

#### Updating Ubuntu Packages

Change the snapshot timestamp and/or requested package roles in
`mcp-local/build-inputs.lock.json`. On Linux with Docker configured for both
target architectures, regenerate the exact `.deb` closures and hashes with:

```bash
python3 mcp-local/scripts/stage-build-inputs.py \
  --arch all \
  --skip-wheels \
  --refresh-os-lock
```

Review every package addition, removal, version change, and checksum change in
the manifest before committing it. The normal publication workflow does not
rewrite this lock; it fails if the snapshot produces different bytes.

#### Updating Migrate-ease

Update the versioned URL or source revision and the expected SHA256 in
`mcp-local/build-inputs.lock.json`. Prefer an upstream-published checksum when
one is available. Migrate-ease is one pinned source archive used by both architectures. The
publication workflow fails before publishing if any archive differs from its
recorded checksum.

#### Updating Container Images or Embeddings

Record immutable `@sha256:` references for new Ubuntu or MCP-input images. For
a multi-architecture image, also record its AMD64 and Arm64 platform manifest
digests. Keep the corresponding `UBUNTU_IMAGE` or `MCP_BUILD_INPUTS_IMAGE`
default in `mcp-local/Dockerfile` synchronized with the checked-in manifest.
Production must never consume a mutable tag.

Embedding updates use an automated promotion PR instead of being copied into
the MCP release directly:

1. Let **Build Offline Embedding Pipeline** run from `main` every Sunday at
   09:00 UTC, or start it manually for an out-of-band update.
2. The workflow publishes an immutable candidate vector-store image and opens
   or updates `automation/pin-embedding-vectorstore`.
3. The promotion branch updates both `container_images.embeddings` in
   `mcp-local/build-inputs.lock.json` and `EMBEDDINGS_IMAGE` in
   `mcp-local/Dockerfile`. It also records the embedding source commit and
   workflow run and proposes the next minor version in `mcp-local/server.json`.
4. Review the source revision, digest, and proposed version before merging.
5. Merge the approved promotion PR to publish the MCP release using that exact
   embedding digest and version.

The promotion workflow never merges its own PR. This preserves the reviewed,
checked-in digest as the release boundary and keeps MCP releases independent
from unsuccessful or unwanted embedding candidates.

#### Creating a Reviewed MCP Release

Production releases are initiated only by a reviewed PR that updates
`mcp-local/server.json` on `main`. Embedding promotion PRs make this update
automatically as a minor release. For a release that does not promote a new
embedding, ask the workflow to create a reviewed version PR:

1. Start **Build MCP Image** manually and select `hotfix`, `minor`, or `major`.
   From the CLI, for example:

   ```bash
   gh workflow run build-mcp-image.yml -f release_action=hotfix
   ```

2. The workflow opens or updates a version PR with the matching semantic
   version change in `mcp-local/server.json`.
3. Allow the required status checks and security-team review to complete.
4. Merge the approved PR. **Build MCP Image** validates the version, builds the
   exact merge commit for AMD64 and Arm64, publishes the version and `latest`
   tags, and creates the matching `vX.Y.Z` Git tag and GitHub Release.

Manual workflow runs are dry runs: they build both architectures but cannot
publish images, tags, or releases when `dry-run` is selected.

Generated PRs use the workflow's short-lived `GITHUB_TOKEN`. Because GitHub
leaves `pull_request` runs created by that token awaiting manual workflow
approval, the automation explicitly dispatches the required test workflows
against the generated branch after opening or updating the PR.

#### Publishing and Pinning the Updated Bundle

After updating any source lock, use the same common publication process:

1. Commit and push the updated source locks to a branch.
2. Start the workflow on that branch:

   ```bash
   gh workflow run build-mcp-inputs.yml --ref YOUR_BRANCH
   ```

3. Confirm that both
   native architecture jobs pass and that the workflow reports the package as
   private.
4. Inspect the published index, then copy its immutable index digest,
   per-architecture manifest digests, source commit, and workflow run into the
   `container_images.mcp_build_inputs` entry in
   `mcp-local/build-inputs.lock.json`.
5. Update the `MCP_BUILD_INPUTS_IMAGE` default in `mcp-local/Dockerfile` to the
   same index digest and submit that pin as a reviewed follow-up change.
6. Run the integration workflow. The release and integration builds must pull
   the digest and must never invoke `stage-build-inputs.py`.

The publication workflow also creates a tag containing the source commit,
workflow run ID, and attempt. That tag is only a discovery aid; production
builds always use the digest.

#### Rolling Back an Input Update

Rollback is a reviewed pin change. Restore the last approved image references
and metadata in `mcp-local/build-inputs.lock.json`, and keep the corresponding
image defaults in `mcp-local/Dockerfile` synchronized. Submit the rollback
through the normal pull-request process and run the AMD64 and Arm64 integration
builds before release. Do not delete, overwrite, or retag the immutable GHCR
artifacts.

## Contribution guidelines

Contributions are welcome! Please feel free to submit issues or pull requests.

When contributing:
- Follow PEP 8 style guidelines for Python code
- Update documentation for any new features or changes
- Ensure the Docker image builds successfully before submitting

**Note:**
Images tagged `latest` and semantic version tags (e.g., `2.3.0`) should be treated as the **prod** environment, while dated tags (`YYYY-MM-DD-<run_number>`, e.g., `2026-05-31-123`) should be treated as the **stage** environment. The **dev** environment refers only to locally built images created by individual developers.
