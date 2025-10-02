# Arm MCP Server

This repository contains a Model Context Protocol (MCP) server that integrates:
- [migrate-ease](https://github.com/migrate-ease/migrate-ease) for scanning codebases
- [sysreport](https://github.com/ArmDeveloperEcosystem/sysreport) for system information
- Docker image architecture checks
- A semantic search knowledge base (using USearch + embeddings)

The server is designed to run inside a Docker container and expose tools to MCP clients such as **q CLI** or **VS Code MCP integration**.

The Dockerfile is located in mcp-local.

embedding-generation is exclusively for creating the vector db, and mcp-remote is the IaC for AWS

---

## 1. Build the container

From the root of this project (where the `Dockerfile` lives):

```bash
docker buildx build --platform linux/arm64 -t arm-mcp .
```

The command above will only build the Arm version. To build the multi-arch version and push to dockerhub:

```bash
docker buildx build \
  --platform linux/arm64,linux/amd64 \
  -t joestech324/mcp:arm-mcp-[version-number] \
  -t joestech324/mcp:latest \
  . --push
```

Where [version-number] is the current version.

To get into the container for troubleshooting, use

```bash
docker run --rm -it --entrypoint /bin/bash arm-mcp
```

## 2. Set up the MCP config

### for q cli

```json
{
  "mcpServers": {
    "arm_torq": {
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "-i",
        "-v", "[local directory path]:/workspace",
        "--name", "arm-mcp",
        "arm-mcp"
      ],
      "env": {},
      "timeout": 60000
    }
  }
}
```

Replace [local directory path] with the local path that you want the mcp server to be able to access.

For q cli this config should be placed in ~/.aws/amazonq/mcp.json

### Codex CLI

```toml
[projects."/path/to/your/project"]
trust_level = "trusted"

[mcp_servers.arm_torq]
command = "docker"
args = [
  "run",
  "--rm",
  "-i",
  "-v", "[local directory path]:/workspace",
  "--name", "arm-mcp",
  "arm-mcp"
]
env = {}
```

Replace `[local directory path]` with the local path that you want the mcp server to be able to access, and replace `/path/to/your/project` with your actual project path.

For Codex CLI this config should be saved in `~/.codex/config.toml`.

### GitHub Copilot in VS Code

```json
{
  "servers": {
    "arm_torq": {
      "type": "stdio",
      "command": "docker",
      "args": [
        "run",
        "--rm",
        "-i",
        "-v", "[local directory path]:/workspace",
        "arm-mcp"
      ]
    }
  }
}
```

The config can either be put in:

`.vscode/mcp.json` local to the open project folder, or

globally here (for macOS):

`~/Library/Application Support/Code/User/mcp.json`

The easiest way to open this file in VS Code for editing is command+shift+p and search for

MCP: Open User Configuration

## Redis Configuration for Arm Architecture

Based on the Arm knowledge base, here's important information about Redis configuration and deployment on Arm-based systems:

### Amazon ElastiCache for Redis on Graviton

Amazon ElastiCache provides managed Redis clusters that support AWS Graviton processors for better price-performance:

**Supported Graviton Instance Types:**
- **Graviton3**: M7g and R7g instances (latest generation)
- **Graviton2**: M6g, R6g, and T4g instances

**Key Benefits:**
- Better price-performance compared to x86 instances
- Native Arm64 architecture support
- Fully managed service with automatic scaling

**Configuration Example:**
```bash
# Create ElastiCache Redis cluster on Graviton3
aws elasticache create-cache-cluster \
    --cache-cluster-id "redis-graviton" \
    --cache-node-type "cache.m7g.large" \
    --engine "redis" \
    --num-cache-nodes 1
```

### Amazon MemoryDB for Redis

Amazon MemoryDB provides a Redis-compatible, durable, in-memory database service:

**Features:**
- Redis-compatible APIs and data structures
- Built-in durability with Multi-AZ
- Microsecond read and single-digit millisecond write latencies
- Supports Redis 6.2+ features

**Resources:**
- [Announcing Amazon MemoryDB for Redis](https://aws.amazon.com/about-aws/whats-new/2021/08/amazon-memorydb-redis/)
- [Launch Blog: Introducing Amazon MemoryDB for Redis](https://aws.amazon.com/blogs/aws/introducing-amazon-memorydb-for-redis-a-redis-compatible-durable-in-memory-database-service/)

### Self-Hosted Redis on Arm64

For self-hosted Redis deployments on Arm64 systems:

**Docker Configuration:**
```bash
# Run Redis on Arm64
docker run --name redis-arm64 \
    --platform linux/arm64 \
    -p 6379:6379 \
    -d redis:latest
```

**Performance Considerations:**
- Redis performs well on Arm64 architecture
- Consider memory optimization for Graviton instances
- Use Redis Cluster mode for horizontal scaling
- Monitor performance with Redis INFO commands

**Installation on Ubuntu/Debian Arm64:**
```bash
# Install Redis from package manager
sudo apt update
sudo apt install redis-server

# Or build from source for latest version
wget http://download.redis.io/redis-stable.tar.gz
tar xzf redis-stable.tar.gz
cd redis-stable
make
```

### Migration Considerations

When migrating Redis workloads to Arm64:
- Redis is architecture-agnostic for data compatibility
- No application code changes required for standard Redis usage
- Test performance characteristics in your specific workload
- Consider using AWS services for simplified migration path