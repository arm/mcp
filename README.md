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

Refreshing is deliberately a reviewed two-step process because an OCI artifact
cannot contain its own not-yet-known digest:

1. Update the relevant versions and hashes in `mcp-local/pyproject.toml`,
   `mcp-local/uv.lock`, `mcp-local/requirements.lock`, and/or
   `mcp-local/build-inputs.lock.json`. Commit those source locks.
2. From that branch, manually run **Build MCP Input Bundle**. Confirm that both
   native architecture jobs pass and that the workflow reports the package as
   private.
3. Inspect the published index, then copy its immutable index digest,
   per-architecture manifest digests, source commit, and workflow run into the
   `container_images.mcp_build_inputs` entry in
   `mcp-local/build-inputs.lock.json`.
4. Update the `MCP_BUILD_INPUTS_IMAGE` default in `mcp-local/Dockerfile` to the
   same index digest and submit that pin as a reviewed follow-up change.
5. Run the integration workflow. The release and integration builds must pull
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
