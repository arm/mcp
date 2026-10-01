[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/arm/mcp/badge)](https://scorecard.dev/viewer/?uri=github.com/arm/mcp)
[![SLSA Build Level 3](https://slsa.dev/images/gh-badge-level3.svg)](docs/slsa-build-level-3.md)

# Arm MCP Server

An [MCP](https://modelcontextprotocol.io/) server providing Arm knowledge-base search and skills for command-line development, migration, and optimization.

## Using the Arm MCP Server

If your goal is to migrate an application from x86 to Arm as quickly as possible, start here:

[Automate x86-to-Arm application migration using Arm MCP Server](https://learn.arm.com/learning-paths/servers-and-cloud-computing/arm-mcp-server/)

## Features

The server exposes one MCP tool, **`knowledge_base_search`**, for semantic search
across Arm documentation, learning resources, intrinsics, and software compatibility.

Three bundled Agent Skills guide the assistant in running commands through its
own shell:

| Skill | CLI workflow | Replaces MCP tools |
| --- | --- | --- |
| `arm-container-inspect` | Skopeo or Docker Buildx image/platform inspection | `check_image`, `skopeo` |
| `arm-migration-scan` | migrate-ease scans for C/C++, Python, Go, JavaScript, Java | `migrate_ease_scan` |
| `arm-assembly-analyze` | LLVM MCA assembly throughput/resource analysis | `mca` |

Skills are served as standard MCP resources (`skill://<name>/SKILL.md`) with
file manifests and as same-named MCP prompts. See
[skill delivery and client compatibility](docs/skills.md) for loading them or
installing them locally. The Docker image retains the CLI binaries; the skills
show how to invoke them with `docker run --entrypoint` without starting the server.

## Pre-Built Image

If you would prefer to use a pre-built, multi-arch image, the official image can be found in Docker Hub here: `armlimited/arm-mcp:latest`

## Prerequisites

- Docker with Buildx support
- An MCP-compatible AI assistant client (e.g. GitHub Copilot, Kiro CLI, Codex CLI, Claude Code, etc)
- Client-side shell/terminal access for the CLI skills; knowledge-base search does not require it

## Quick Start

### 1. Build the Docker Image

From the root of this repository:

```bash
docker buildx build -f mcp-local/Dockerfile -t armlimited/arm-mcp . --load
```

This builds for the Docker host's native architecture. The release workflow is
responsible for explicit multi-architecture builds. If dependencies changed and
the pinned input bundle is stale, follow the [branch build instructions](CONTRIBUTING.md#building-with-changed-python-dependencies) first.

### 2. Configure Your MCP Client

Choose the configuration that matches your MCP client:

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
        "armlimited/arm-mcp"
      ],
      "timeout": 60000
    }
  }
}
```

#### Gemini CLI

A project-local configuration file can keep invocation logs with the project.

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
  "armlimited/arm-mcp"
]
```

**Note**: The `/workspace` mount is optional and used for invocation/error logs.
Knowledge-base search and skill delivery do not read project source. CLI scans
use a separate shell invocation and workspace mount as shown in each skill.

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

## Development and contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for repository structure, integration
testing, reproducible build inputs, runtime-egress validation, dependency
updates, and release workflows.

## Troubleshooting

### Accessing the Container Shell

To debug or explore the container environment:

```bash
docker run --rm -it --entrypoint /bin/bash armlimited/arm-mcp
```

### Common Issues

- **Timeout errors during migration scans**: Increase the client shell command timeout; scans no longer run as MCP tool calls.
- **Removed tool errors**: Reload the server tool list and use the corresponding skill resource or prompt.
- **Empty workspace**: Ensure your volume mount path is correct and the directory exists
- **Architecture mismatches**: Confirm that the local image matches the Docker host's native architecture; use the release workflow for explicit cross-platform builds.

Suspected vulnerabilities must not be reported in public issues. See the [Arm MCP security policy](https://github.com/arm/mcp/security/policy) and report them via [Arm PSIRT](https://developer.arm.com/support/arm-security-updates/report-security-vulnerabilities).

## License

Copyright © 2026, Arm Limited and Contributors. All rights reserved.

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE) for details.
