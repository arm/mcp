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

## 3. Arm Nginx Performance Tuning

This section provides guidance on optimizing nginx performance on Arm-based systems, particularly useful when working with containerized applications on AWS Graviton or other Arm processors.

### Key Arm-Specific Nginx Optimizations

#### Worker Process Configuration
```nginx
# Set worker processes to match available CPU cores
worker_processes auto;

# Use epoll for better performance on Linux Arm systems
events {
    worker_connections 1024;
    use epoll;
    multi_accept on;
}
```

#### Memory and Buffer Tuning
```nginx
# Optimize buffer sizes for Arm architecture
client_body_buffer_size 128k;
client_max_body_size 10m;
client_header_buffer_size 1k;
large_client_header_buffers 4 4k;
output_buffers 1 32k;
postpone_output 1460;
```

#### SSL/TLS Optimizations for Arm
```nginx
# Enable hardware acceleration when available
ssl_protocols TLSv1.2 TLSv1.3;
ssl_ciphers ECDHE-RSA-AES128-GCM-SHA256:ECDHE-RSA-AES256-GCM-SHA384;
ssl_prefer_server_ciphers off;

# Session cache optimization
ssl_session_cache shared:SSL:10m;
ssl_session_timeout 10m;
```

#### Gzip Configuration
```nginx
# Optimize compression for better CPU utilization on Arm
gzip on;
gzip_vary on;
gzip_min_length 10240;
gzip_proxied expired no-cache no-store private must-revalidate auth;
gzip_types
    text/plain
    text/css
    text/xml
    text/javascript
    application/javascript
    application/xml+rss
    application/json;
```

#### File and Connection Handling
```nginx
# Optimize file operations for Arm systems
sendfile on;
tcp_nopush on;
tcp_nodelay on;
keepalive_timeout 30;
types_hash_max_size 2048;
server_tokens off;

# Open file cache optimization
open_file_cache max=200000 inactive=20s;
open_file_cache_valid 30s;
open_file_cache_min_uses 2;
open_file_cache_errors on;
```

### Container-Specific Considerations

When running nginx in containers on Arm systems (like the setup in this repository):

1. **Resource Limits**: Set appropriate CPU and memory limits in your container configuration
2. **Multi-stage Builds**: Use multi-stage Docker builds to optimize image size for Arm64
3. **Base Image Selection**: Use ARM64-native base images like `nginx:alpine` for better performance

### Monitoring and Benchmarking

Use these commands to monitor nginx performance on Arm systems:

```bash
# Check nginx process CPU usage
top -p $(pgrep nginx)

# Monitor connection statistics
ss -tuln | grep :80

# Check system-wide performance
iostat -x 1
```

### Architecture-Specific Compiler Flags

If building nginx from source on Arm systems, use these compiler optimizations:

```bash
# For ARMv8-A architecture
export CFLAGS="-march=armv8-a -mtune=generic -O2"

# For specific Graviton processors
export CFLAGS="-march=armv8.2-a+crypto+crc -mtune=neoverse-n1 -O2"
```

For more detailed performance tuning guidance, use the `knowledge_base_search` tool in this MCP server to find additional Arm-specific optimization resources.