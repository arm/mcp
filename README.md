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

## ARM-Specific Nginx Configuration

When deploying the ARM MCP server with nginx on ARM64 architecture, consider the following ARM-specific configurations and optimizations:

### Architecture Support

The ARM MCP server automatically deploys on ARM64 instances using the latest Ubuntu 24.04 ARM64 AMI:
- **Instance Type**: Uses `m8g.large` (ARM64-based AWS Graviton processors)
- **Architecture**: `ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-arm64-server-*`
- **AWS CLI**: Uses the ARM64-specific download `awscli-exe-linux-aarch64.zip`

### Nginx Installation on ARM64

From the infrastructure code, nginx is installed using standard package management on ARM64 Ubuntu:

```bash
apt-get update
apt-get install -y python3-pip nginx
```

### ARM64 Performance Optimizations

For optimal nginx performance on ARM64 processors:

1. **Worker Processes**: Configure worker processes to match ARM64 core count
   ```nginx
   worker_processes auto;  # Automatically detects ARM64 cores
   ```

2. **CPU Affinity**: Bind nginx workers to specific ARM64 cores
   ```nginx
   worker_cpu_affinity auto;
   ```

3. **Memory Configuration**: ARM64 processors benefit from optimized buffer sizes
   ```nginx
   worker_rlimit_nofile 65535;
   events {
       worker_connections 4096;
       use epoll;
       multi_accept on;
   }
   ```

### Load Balancer Configuration

The ARM MCP server infrastructure uses:
- **Application Load Balancer** with HTTPS (port 443)
- **Target Group** routing to ARM64 instances on port 5000
- **Health Check** configured for `/health` endpoint
- **SSL Policy**: Uses AWS recommended SSL policy

### Security Group Configuration

Port configuration for ARM64 deployment:
- **Port 5000**: Application traffic (internal)
- **Port 443**: HTTPS traffic (external via ALB)
- **Outbound**: All traffic allowed for package updates and dependencies

### ARM64-Specific Compiler Flags

When building nginx modules or custom ARM applications, use these compiler optimizations:

```bash
# For ARM64 SIMD optimizations
-march=armv8-a+simd

# For ARM SVE (Scalable Vector Extension) support
-march=armv8-a+sve

# For ARM SVE2 support (newer ARM processors)
-march=armv8-a+sve2
```

### Docker Integration

The ARM MCP server supports multi-architecture Docker builds:

```bash
# ARM64-only build
docker buildx build --platform linux/arm64 -t arm-mcp .

# Multi-architecture build (ARM64 + AMD64)
docker buildx build \
  --platform linux/arm64,linux/amd64 \
  -t joestech324/mcp:arm-mcp-[version] \
  . --push
```

### Monitoring and Logging

For ARM64 deployments, the infrastructure includes:
- **CloudWatch Agent** integration
- **SSM Agent** for remote management
- **CloudWatch Logs** for centralized logging
- **Detailed monitoring** enabled on Auto Scaling Groups

### Best Practices for ARM64 Nginx

1. **Use native ARM64 packages** when available rather than x86 emulation
2. **Enable HTTP/2** for better performance on ARM64 processors
3. **Configure appropriate buffer sizes** for ARM64 memory architecture
4. **Use nginx modules compiled specifically for ARM64**
5. **Monitor CPU utilization** to ensure optimal ARM64 core usage