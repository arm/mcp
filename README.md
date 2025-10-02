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

---

## Redis Configuration for ARM64/Graviton

This section provides ARM-specific guidance for configuring Redis on AWS Graviton and ARM64 systems, extracted from the knowledge base.

### AWS Managed Redis Services

#### Amazon ElastiCache for Redis
- **ARM64 Support**: ElastiCache supports Redis on ARM64 with Graviton2 and Graviton3 processors
- **Instance Types**: 
  - M6g, R6g (Graviton2-based instances)
  - T4g (Graviton2-based burstable instances)  
  - M7g, R7g (Graviton3-based instances)
- **Performance**: Up to 40% better price-performance compared to x86-based instances
- **Resources**:
  - [Amazon ElastiCache now supports M7g and R7g Graviton3-based nodes](https://aws.amazon.com/about-aws/whats-new/2023/08/amazon-elasticache-m7g-r7g-graviton-3-nodes/)
  - [Amazon ElastiCache now supports M6g and R6g Graviton2-based instances](https://aws.amazon.com/about-aws/whats-new/2020/10/amazon-elasticache-now-supports-m6g-and-r6g-graviton2-based-instances/)
  - [Amazon ElastiCache now supports T4g Graviton2-based instances](https://aws.amazon.com/about-aws/whats-new/2021/11/amazon-elasticache-supports-t4g-graviton2-based-instances/)

#### Amazon MemoryDB for Redis
- **ARM64 Support**: Fully compatible with ARM64 architecture
- **Features**: Redis-compatible, durable, in-memory database service
- **Resources**:
  - [Announcing Amazon MemoryDB for Redis](https://aws.amazon.com/about-aws/whats-new/2021/08/amazon-memorydb-redis/)
  - [Introducing Amazon MemoryDB for Redis – A Redis-Compatible, Durable, In-Memory Database Service](https://aws.amazon.com/blogs/aws/introducing-amazon-memorydb-for-redis-a-redis-compatible-durable-in-memory-database-service/)

### Self-Managed Redis Configuration

#### For containerized Redis deployments:
```bash
# Multi-architecture Redis container
docker run --platform linux/arm64 -d \
  --name redis-arm64 \
  -p 6379:6379 \
  redis:latest
```

#### Performance Considerations for ARM64:
1. **Memory Architecture**: ARM64 processors often have better memory bandwidth, which benefits Redis workloads
2. **CPU Efficiency**: Graviton processors provide better performance per watt for in-memory workloads
3. **Container Images**: Ensure you use ARM64-compatible Redis container images or compile from source

#### Migration from x86 to ARM64:
- Redis data is architecture-independent - RDB and AOF files can be transferred directly
- Client applications may need recompilation for ARM64
- Test performance characteristics as memory access patterns may differ

### Related AWS Services on ARM64:
- **Amazon ECS**: Supports ARM64 containers for Redis deployments
- **Amazon EKS**: Full ARM64 support for Kubernetes-based Redis deployments  
- **AWS Fargate**: ARM64 support for serverless Redis containers

For the latest updates on ARM64 support across AWS services, see [What's New posts](https://aws.amazon.com/new/?whats-new-content-all.sort-by=item.additionalFields.postDateTime&whats-new-content-all.sort-order=desc&whats-new-content-all.q=Graviton&whats-new-content-all.q_operator=AND#What.27s_New_Feed).