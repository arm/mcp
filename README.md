[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/arm/mcp/badge)](https://scorecard.dev/viewer/?uri=github.com/arm/mcp)
[![SLSA Build Level 3](https://slsa.dev/images/gh-badge-level3.svg)](docs/slsa-build-level-3.md)

# Arm MCP Server

An [MCP](https://modelcontextprotocol.io/) server providing AI assistants with tools and knowledge for Arm architecture development, migration, and optimization.

## Using the Arm MCP Server

If your goal is to migrate an application from x86 to Arm as quickly as possible, start here:

[Automate x86-to-Arm application migration using Arm MCP Server](https://learn.arm.com/learning-paths/servers-and-cloud-computing/arm-mcp-server/)

## Features

This MCP server equips AI assistants with specialized tools for Arm development:

- **[Knowledge Base Search](arm_kb_search/README.md)**: Keyword and semantic search across Arm documentation, learning resources, intrinsics, and software compatibility information, with technical-name aliases
- **Code Migration Analysis**: Scan codebases for Arm compatibility using [migrate-ease](https://github.com/migrate-ease/migrate-ease) (supports C++, Python, Go, JavaScript, Java)
- **Container Architecture Inspection**: Check Docker image architecture support using integrated [Skopeo](https://github.com/containers/skopeo) and check-image tools.
- **Assembly Performance Analysis**: Analyze assembly code performance using LLVM-MCA

## Pre-Built Image

If you would prefer to use a pre-built, multi-arch image, the official image can be found in Docker Hub here: `armlimited/arm-mcp:latest`

## Prerequisites

- Docker with Buildx support
- An MCP-compatible AI assistant client (e.g. GitHub Copilot, Kiro CLI, Codex CLI, Claude Code, etc)

## Quick Start

### 1. Build the Docker Image

From the root of this repository:

```bash
docker buildx build -f mcp-local/Dockerfile -t armlimited/arm-mcp . --load
```

This builds for the Docker host's native architecture. The release workflow is
responsible for explicit multi-architecture builds.

For local development builds, see the
[Quick Local Development Builds section in CONTRIBUTING.md](CONTRIBUTING.md#quick-local-development-builds).

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

**Note**: Replace `/path/to/your/workspace` with the actual path to your project directory that you want the MCP server to access.

### 3. Restart Your MCP Client

After updating the configuration, restart your MCP client to load the Arm MCP server.

## Knowledge-base search

`knowledge_base_search` accepts optional `filters`, `k`, and `scope`. Omitting
these options keeps the default unfiltered search with up to five matching chunks.

```json
{"query": "How do SVE predicated loads work?", "filters": {"doc_type": "Intrinsic", "product": "SVE"}, "k": 3}
```

- `filters`: each `doc_type`, `product`, `platform`, or `edition` accepts a string
  or non-empty list, e.g. `"platform": ["linux", "windows"]`. Alternatives within
  a field combine with OR; different fields combine with AND. Matching ignores
  case, surrounding whitespace, and duplicate choices. Empty lists and blank or
  non-string items are rejected. Missing tags cannot match; use known labels.
  Platform/edition coverage is currently sparse.
- `k`: any positive integer, default 5 when omitted/null. Limits ranked seed
  results, not tokens or expanded chunks. Fewer results may be available.
  Agents are instructed to use at most 20; this is guidance, not an API limit.
  Direct calls such as `k=100` use the same interface without special configuration.
  Invalid types and non-positive values are rejected.

| Scope | Content returned |
| --- | --- |
| `chunks` (default) | Ranked matching chunks. |
| `page` | Every matched document's stored chunks, in order. |
| `parent_resource` | Every matched parent's stored pages/chunks, in order; page scope when no parent is known. |

Expansion deduplicates shared documents. Filters and `k` apply only to seed
matches; expanded sibling pages are unrestricted. Results include stored
`page_url`/`parent_page_url` links and, for expansion, position/count metadata.
Request wider context only when the user asks; responses can be large and client
output limits apply. Links and expansion do not fetch live pages.

Expansion requires regenerated chunk/vector artifacts with complete ordering
metadata; missing or conflicting data returns an error. Parent manifests are
currently acquired for Arm Learning Paths. See the [shared search documentation](arm_kb_search/README.md)
for metadata details and other-source limitations.

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

- **Timeout errors during migration scans**: Increase the `timeout` value in your MCP client configuration (e.g., `"timeout": 120000` for 2 minutes)
- **Empty workspace**: Ensure your volume mount path is correct and the directory exists
- **Architecture mismatches**: Confirm that the local image matches the Docker host's native architecture; use the release workflow for explicit cross-platform builds.

Suspected vulnerabilities must not be reported in public issues. See the [Arm MCP security policy](https://github.com/arm/mcp/security/policy) and report them via [Arm PSIRT](https://developer.arm.com/support/arm-security-updates/report-security-vulnerabilities).

## License

Copyright © 2026, Arm Limited and Contributors. All rights reserved.

Licensed under the Apache License, Version 2.0. See [LICENSE](LICENSE) for details.
