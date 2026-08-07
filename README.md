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

## Refreshing MCP Build Inputs

Python wheels, Ubuntu packages, Performix, and migrate-ease are captured in a
private, multi-architecture GHCR artifact before the MCP release consumes
them. Refreshing that artifact is a deliberate two-step process:

1. Run the manually triggered **Build MCP Input Bundle** workflow. It resolves
   only the versions and hashes in `mcp-local/build-inputs.lock.json` and the uv
   locks, builds native amd64 and arm64 scratch images, and publishes a private
   `ghcr.io/arm/mcp-build-inputs` image index.
2. Copy the immutable `ghcr.io/arm/mcp-build-inputs@sha256:...` reference from
   the workflow summary into `mcp-local/build-inputs.lock.json` in a reviewed
   follow-up change. For the initial publication, that follow-up also switches
   the Dockerfile and release workflows from acquisition to the GHCR artifact.
   Release builds must consume the digest, never the workflow tag.

The workflow tag contains the source commit, workflow run ID, and attempt for
traceability. It is only a discovery aid; the digest is the build input.

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
