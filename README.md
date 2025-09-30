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

---

## Nginx Configuration for ARM64/Graviton

This section contains ARM-specific information for configuring Nginx web server on ARM64 architecture, particularly optimized for AWS Graviton processors.

### Installation on ARM64 Ubuntu

Based on the MCP infrastructure stack, Nginx is installed on Ubuntu 24.04 ARM64 using:

```bash
apt-get update
apt-get install -y nginx
```

### ARM64/Graviton Compatibility

Nginx has native ARM64 support and works out-of-the-box on AWS Graviton instances. The default Ubuntu package repository provides ARM64-optimized Nginx binaries.

### Infrastructure Configuration

The MCP remote infrastructure demonstrates a production-ready ARM64 setup:

**Instance Configuration:**
- **AMI**: Ubuntu 24.04 ARM64 Server (`ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-arm64-server-*`)
- **Instance Type**: AWS Graviton-based instances (e.g., `m8g.large`)
- **Architecture**: ARM64 (AArch64)

**Network Configuration:**
- **Load Balancer**: Application Load Balancer (ALB) with HTTPS termination
- **Security Groups**: Port 5000 exposed for application traffic
- **SSL/TLS**: AWS Certificate Manager integration
- **Route 53**: DNS management with alias records

### Performance Considerations

When running Nginx on ARM64/Graviton instances:

1. **Native Performance**: Nginx compiled for ARM64 delivers excellent performance on Graviton processors
2. **Memory Efficiency**: ARM64 architecture provides efficient memory usage patterns
3. **Scalability**: Graviton instances offer strong price-performance characteristics for web workloads

### Configuration Best Practices

For optimal performance on ARM64/Graviton:

```nginx
# /etc/nginx/nginx.conf
worker_processes auto;  # Automatically detect ARM64 cores
worker_cpu_affinity auto;  # Optimize CPU affinity for ARM64

events {
    worker_connections 1024;
    use epoll;  # Efficient on ARM64 Linux
}

http {
    # Enable gzip compression (ARM64 optimized)
    gzip on;
    gzip_vary on;
    gzip_types text/plain text/css application/json application/javascript;
    
    # Optimize sendfile for ARM64
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
}
```

### Container Deployment

For containerized Nginx deployments on ARM64:

```dockerfile
# Use ARM64-compatible base image
FROM nginx:alpine

# The official Nginx images support multi-arch (ARM64/AMD64)
# No special configuration needed for ARM64 compatibility
```

### Monitoring and Logging

The MCP infrastructure includes comprehensive logging:

```bash
# System logs are captured in
/var/log/nginx/access.log
/var/log/nginx/error.log

# Infrastructure logs available via
/var/log/ssm-setup.log
```

### Load Balancer Integration

The infrastructure stack demonstrates integration with AWS Application Load Balancer:

- **Target Groups**: Nginx instances registered as targets
- **Health Checks**: HTTP health check on `/health` endpoint
- **SSL Termination**: Handled at ALB level
- **Port Configuration**: Internal port 5000, external HTTPS 443

### Ecosystem Compatibility

Nginx integrates well with the ARM64 ecosystem including:
- **PHP-FPM**: Native ARM64 support for dynamic content
- **Let's Encrypt**: SSL certificate automation works seamlessly
- **Docker**: Multi-arch container images available
- **Kubernetes**: Full compatibility with ARM64 node groups

This configuration provides a solid foundation for running high-performance web applications on ARM64/Graviton infrastructure.