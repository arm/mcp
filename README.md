# Arm MCP Server

An [MCP](https://modelcontextprotocol.io/) server providing AI assistants with tools and knowledge for Arm architecture development, migration, and optimization.

## Using the Arm MCP Server

If your goal is to migrate an application from x86 to Arm as quickly as possible, start here:

[Automate x86-to-Arm application migration using Arm MCP Server](https://learn.arm.com/learning-paths/servers-and-cloud-computing/arm-mcp-server/)

## Features

This MCP server equips AI assistants with specialized tools for Arm development:

- **Knowledge Base Search**: Semantic search across Arm documentation, learning resources, intrinsics, and software compatibility information
- **Code Migration Analysis**: Scan codebases for Arm compatibility using [migrate-ease](https://github.com/migrate-ease/migrate-ease) (supports C++, Python, Go, JavaScript, Java)
- **Container Architecture Inspection**: Check Docker image architecture support using integrated [Skopeo](https://github.com/containers/skopeo) and check-image tools.
- **Assembly Performance Analysis**: Analyze assembly code performance using LLVM-MCA
- **Arm Performix**: Run APX recipe workflows against a target device over SSH to capture and analyze workload performance data
- **System Information**: Instructions for gathering detailed system architecture information via [sysreport](https://github.com/ArmDeveloperEcosystem/sysreport)

## Pre-Built Image

If you would prefer to use a pre-built, multi-arch image, the official image can be found in Docker Hub here: `armlimited/arm-mcp:latest`

## Prerequisites

- Docker (with buildx support for multi-arch builds)
- An MCP-compatible AI assistant client (e.g. GitHub Copilot, Kiro CLI, Codex CLI, Claude Code, etc)

## Quick Start

### 1. Build the Docker Image

From the root of this repository:

```bash
docker buildx build --platform linux/arm64,linux/amd64 -f mcp-local/Dockerfile -t armlimited/arm-mcp .
```

For a single-platform build (faster):

```bash
docker buildx build -f mcp-local/Dockerfile -t armlimited/arm-mcp . --load
```

### 2. Configure Your MCP Client

Choose the configuration that matches your MCP client:

The examples below include the optional Docker arguments required for **Arm Performix**. These SSH-related settings are only needed when you want the MCP server to run remote commands on a target device through Arm Performix. If you are not using Arm Performix, you can omit the SSH `-v` lines.

#### Claude Code

Add to `.mcp.json` in your project:

```json
{
  "mcpServers": {
    "arm-mcp": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "-i",
        "--pull=always",
        "-v", "/path/to/your/workspace:/workspace",
        "-v", "/path/to/your/ssh/private_key:/run/keys/ssh-key.pem:ro",
        "-v", "/path/to/your/ssh/known_hosts:/run/keys/known_hosts:ro",
        "armlimited/arm-mcp"
      ]
    }
  }
}
```

#### GitHub Copilot (VS Code)

Add to `.vscode/mcp.json` in your project, or globally at `~/Library/Application Support/Code/User/mcp.json` (macOS):

```json
{
  "servers": {
    "arm-mcp": {
      "type": "stdio",
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "-i",
        "--pull=always",
        "-v", "/path/to/your/workspace:/workspace",
        "-v", "/path/to/your/ssh/private_key:/run/keys/ssh-key.pem:ro",
        "-v", "/path/to/your/ssh/known_hosts:/run/keys/known_hosts:ro",
        "armlimited/arm-mcp"
      ]
    }
  }
}
```

The easiest way to open this file in VS Code for editing is command+shift+p and search for

MCP: Open User Configuration

#### AWS Kiro CLI

Add to `~/.kiro/settings/mcp.json`:

```json
{
  "mcpServers": {
    "arm-mcp": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "-i",
        "--pull=always",
        "-v", "/path/to/your/workspace:/workspace",
        "-v", "/path/to/your/ssh/private_key:/run/keys/ssh-key.pem:ro",
        "-v", "/path/to/your/ssh/known_hosts:/run/keys/known_hosts:ro",
        "armlimited/arm-mcp"
      ],
      "timeout": 60000
    }
  }
}
```

#### Gemini CLI

It is recommended to use a project-local configuration file to ensure the relevant workspace is mounted.

Add to `.gemini/settings.json` in your project root:

```json
{
  "mcpServers": {
    "arm-mcp": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "-i",
        "--pull=always",
        "-v", "/path/to/your/workspace:/workspace",
        "-v", "/path/to/your/ssh/private_key:/run/keys/ssh-key.pem:ro",
        "-v", "/path/to/your/ssh/known_hosts:/run/keys/known_hosts:ro",
        "armlimited/arm-mcp"
      ]
    }
  }
}
```

#### MCP Clients using TOML format (e.g. Codex CLI)

```toml
[mcp_servers.arm-mcp]
command = "docker"
args = [
  "run",
  "--rm",
  "-i",
  "--pull=always",
  "-v", "/path/to/your/workspace:/workspace",
  "-v", "/path/to/your/ssh/private_key:/run/keys/ssh-key.pem:ro",
  "-v", "/path/to/your/ssh/known_hosts:/run/keys/known_hosts:ro",
  "armlimited/arm-mcp"
]
```

**Note**: Replace `/path/to/your/workspace` with the actual path to your project directory that you want the MCP server to access. If you are enabling Arm Performix, also replace the `/path/to/your/ssh/private_key` and `/path/to/your/ssh/known_hosts` paths with your local files. The MCP container auto-discovers files mounted under `/run/keys`, as shown in the configs above.

### 3. Restart Your MCP Client

After updating the configuration, restart your MCP client to load the Arm MCP server.

## Logging

Depending on usage, the server may write two log files under `/workspace`. With the
configuration examples above, these files appear in the project directory on
your computer:

- `mcp-traffic.jsonl` records when tools are used, the inputs provided, and the
  reason for each tool call. It also records results from knowledge base
  searches.
- `error_logging.yaml` records details about errors encountered by the server.
  This information can help with troubleshooting.

These logs may contain information from your project and tool requests. Review
their contents before sharing them.

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
- Install the required test packages using - `pip install -r tests/requirements.txt` within the `mcp_local` directory.

### Testing Steps

- Run the test script - `python -m pytest -s tests/test_mcp.py`
- Check if following 2 docker containers have started - **mcp server** & **testcontainer**
- All tests should pass without any errors. Warnings can be ignored.

## Reproducible MCP Build Inputs

The final MCP image build does not resolve or download Python packages, Ubuntu
packages, Performix, or migrate-ease. Those inputs are acquired separately by
the manually triggered **Build MCP Input Bundle** workflow and published as a
private, multi-architecture OCI image at `ghcr.io/arm/mcp-build-inputs`.

The acquisition workflow runs natively on AMD64 and Arm64. For each
architecture it:

1. verifies the checked-in uv lock and exported, hash-locked requirements;
2. downloads the exact Python wheels allowed by those hashes;
3. downloads the complete `.deb` closures from the recorded Ubuntu snapshot
   and checks every package against `mcp-local/build-inputs.lock.json`;
4. downloads and verifies the architecture-specific Performix archive and the
   pinned migrate-ease source archive; and
5. publishes those bytes and their lock metadata in a scratch image, then
   combines both architecture images into one private OCI image index.

`mcp-local/Dockerfile` selects the matching architecture from that index and
copies the files from it. Python and apt installation use only those local
files with network access disabled. The Ubuntu base image, input bundle, and
embedding vector-store image are all selected by immutable OCI digest. The
currently approved input bundle is recorded in
`mcp-local/build-inputs.lock.json` and defaults to:

```text
ghcr.io/arm/mcp-build-inputs@sha256:d38c64ad12493ddacfe7a99e49f47e6cfcf1f9d2acf1696c797645d3099758a3
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
echo "$GHCR_TOKEN" | docker login ghcr.io --username "$GHCR_USER" --password-stdin
docker buildx build \
  --platform linux/amd64 \
  --file mcp-local/Dockerfile \
  --tag arm-mcp:local \
  --load \
  .
```

Use `linux/arm64` to build the Arm64 image. GitHub Actions performs the same
GHCR login and builds both architectures without running the acquisition
script.

### Inspecting the Published Inputs

The index and its platform manifests can be inspected without unpacking it:

```bash
MCP_INPUTS="ghcr.io/arm/mcp-build-inputs@sha256:d38c64ad12493ddacfe7a99e49f47e6cfcf1f9d2acf1696c797645d3099758a3"
docker buildx imagetools inspect "$MCP_INPUTS"
docker buildx imagetools inspect "$MCP_INPUTS" --format '{{json .Manifest}}' | jq
```

To inspect the actual files for one architecture:

```bash
docker pull --platform linux/amd64 "$MCP_INPUTS"
container_id="$(docker create --platform linux/amd64 "$MCP_INPUTS")"
docker cp "$container_id:/mcp-build-inputs" ./mcp-build-inputs-inspect
docker rm "$container_id"
find ./mcp-build-inputs-inspect -maxdepth 3 -type f | sort
```

The copied `metadata/` directory contains the source locks used during
acquisition. The checked-in manifest additionally records the published index
digest, per-architecture manifest digests, source commit, workflow run, and
verification method.

### Refreshing the Inputs

Refreshing is deliberately a reviewed two-commit process because an OCI artifact
cannot contain its own not-yet-known digest:

#### Updating Python Packages

Keep the direct dependency pins in `mcp-local/pyproject.toml` and
`mcp-local/requirements.txt` synchronized. Use the uv version recorded in
`mcp-local/build-inputs.lock.json`, then regenerate both locks:

```bash
uv --version
uv lock --directory mcp-local --upgrade-package PACKAGE_NAME
uv export \
  --directory mcp-local \
  --locked \
  --no-dev \
  --no-emit-project \
  --format requirements-txt \
  --output-file mcp-local/requirements.lock
shasum -a 256 mcp-local/requirements.lock
```

Record the final checksum as `python.install_requirements_sha256` in
`mcp-local/build-inputs.lock.json`. The publication workflow checks that the uv
lock and exported requirements agree before downloading the AMD64 and Arm64
wheels.

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

Regenerate the uv and requirements locks, refresh the Ubuntu package manifests
as described below, and build both architectures before accepting the upgrade.

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

#### Updating Performix or Migrate-ease

Update the versioned URL or source revision and the expected SHA256 in
`mcp-local/build-inputs.lock.json`. Prefer an upstream-published checksum when
one is available. Performix has separate AMD64 and Arm64 artifacts;
migrate-ease is one pinned source archive used by both architectures. The
publication workflow fails before publishing if any archive differs from its
recorded checksum.

#### Updating Container Images or Embeddings

Record immutable `@sha256:` references for new Ubuntu, embedding-vector-store,
or MCP-input images. For a multi-architecture image, also record its AMD64 and
Arm64 platform manifest digests. Keep the corresponding `UBUNTU_IMAGE`,
`EMBEDDINGS_IMAGE`, or `MCP_BUILD_INPUTS_IMAGE` default in
`mcp-local/Dockerfile` synchronized with the checked-in manifest. Production
must never consume a mutable tag.

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

## Troubleshooting

### Accessing the Container Shell

To debug or explore the container environment:

```bash
docker run --rm -it --entrypoint /bin/bash armlimited/arm-mcp
```

### Common Issues

- **Timeout errors during migration scans**: Increase the `timeout` value in your MCP client configuration (e.g., `"timeout": 120000` for 2 minutes)
- **Empty workspace**: Ensure your volume mount path is correct and the directory exists
- **Architecture mismatches**: If you encounter platform-specific issues, rebuild for your specific platform using `--platform linux/amd64` or `--platform linux/arm64`

## Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.

When contributing:
- Follow PEP 8 style guidelines for Python code
- Update documentation for any new features or changes
- Ensure the Docker image builds successfully before submitting

**Note:**
Images tagged `latest` and semantic version tags (e.g., `2.3.0`) should be treated as the **prod** environment, while dated tags (`YYYY-MM-DD-<run_number>`, e.g., `2026-05-31-123`) should be treated as the **stage** environment. The **dev** environment refers only to locally built images created by individual developers.

## License

Copyright © 2026, Arm Limited and Contributors. All rights reserved.

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE) for details.
